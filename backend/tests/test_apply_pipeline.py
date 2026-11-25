"""run_apply end to end with a fake site (needs TEST_DATABASE_URL)."""
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import select

from jobscout.apply.base import QA, ApplyOutcome
from jobscout.db.models import Account, Application, ApplyStatus, Platform, ScrapeRun
from jobscout.extract.dates import DateRange, now
from jobscout.pipeline.apply import get_or_create_apply_settings, preflight, run_apply
from jobscout.scrapers.base import JobListing, LoginRequired
from jobscout.security.crypto import encrypt
from jobscout.security.users import create_user


@pytest.fixture(autouse=True)
def fernet(monkeypatch):
    from cryptography.fernet import Fernet

    from jobscout.config import get_settings

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())


def _job(ext, **kw):
    base = dict(external_id=ext, url=f"https://example.test/{ext}", title=f"Python Dev {ext}", company="Acme",
                location="Pune", experience="2-4 Yrs", posted_at=now(), easy_apply=True)
    return JobListing(**{**base, **kw})


class FakeSite:
    platform = Platform.linkedin

    def __init__(self, jobs, outcomes=None, login_ok=True, raise_on=None):
        self.jobs, self.outcomes, self.login_ok, self.raise_on = jobs, outcomes or {}, login_ok, raise_on
        self.applied, self.dry = [], []

    def ensure_logged_in(self, email, password, allow_manual):
        return self.login_ok

    def search(self, keyword, location, date_range, work_types):
        for j in self.jobs:
            j.search_tag = keyword
            yield j

    def apply(self, job, answerer, dry_run, precheck):
        if self.raise_on == job.external_id:
            raise LoginRequired("LinkedIn asked for a security check.")
        job.description = "We need 8+ years" if job.external_id == "senior" else "Python role"
        if reason := precheck(job):
            return ApplyOutcome(ApplyStatus.skipped, reason, filtered=True)
        (self.dry if dry_run else self.applied).append(job.external_id)
        if job.external_id in self.outcomes:
            return self.outcomes[job.external_id](answerer)
        q = answerer.answer(__import__("jobscout.apply.base", fromlist=["Question"]).Question(
            "Notice period in days", "number", [], True))
        return ApplyOutcome(ApplyStatus.dry_run if dry_run else ApplyStatus.applied, None, [q])


def _setup(session, platform=Platform.linkedin, cap=25):
    uid = create_user(session, "u@example.com", "password123").id
    session.add(Account(user_id=uid, platform=platform, login_email="me@example.com", password_enc=encrypt("pw")))
    prefs = get_or_create_apply_settings(session, uid)
    prefs.answers = {"notice_period_days": 30}
    prefs.daily_cap = cap
    session.commit()
    return uid


def _run(uid, site, **kw):
    @contextmanager
    def factory(account):
        yield site

    week = DateRange("last-7d", now() - timedelta(days=7), now())
    # hybrid/on-site in Pune: one search (with remote wanted, a second remote-anywhere search would run)
    args = dict(user_id=uid, platform=Platform.linkedin, keywords=["python"], date_range=week, limit=10,
                location="Pune", work_types=["hybrid", "on-site"], applier_factory=factory, sleep=lambda s: None)
    events = []
    res = run_apply(**{**args, **kw}, on_event=events.append)
    return res, events


def _apps(session, uid):
    session.expire_all()
    return {a.external_id: a for a in session.scalars(select(Application).where(Application.user_id == uid))}


def test_applies_records_and_never_twice(session):
    uid = _setup(session)
    site = FakeSite([_job("a"), _job("b"), _job("chennai", location="Chennai"), _job("senior", experience=None)])
    res, events = _run(uid, site, exp_max=5)
    assert site.applied == ["a", "b"]
    assert res.collected == 2 and res.skipped == {"location doesn't match": 1, "experience outside your range": 1}
    apps = _apps(session, uid)
    assert set(apps) == {"a", "b"}                         # filtered jobs aren't recorded
    assert apps["a"].status == ApplyStatus.applied
    assert apps["a"].questions == [{"q": "Notice period in days", "answer": "30", "source": "saved"}]
    run = session.get(ScrapeRun, res.run_id)
    assert run.kind == "apply" and run.posts_saved == 2
    sent = [e for e in events if e.get("apply_status") == "applied"]
    assert len(sent) == 2 and sent[0]["url"] == "https://example.test/a"

    site2 = FakeSite([_job("a"), _job("c")])
    res2, _ = _run(uid, site2)
    assert site2.applied == ["c"] and res2.skipped == {"already applied": 1}


def test_daily_cap(session):
    uid = _setup(session, cap=2)
    site = FakeSite([_job(str(i)) for i in range(5)])
    res, _ = _run(uid, site)
    assert site.applied == ["0", "1"] and res.stop_reason == "today's limit of 2 reached"
    assert preflight(session, uid, Platform.linkedin, dry_run=False).startswith("You've reached today's limit of 2")
    assert preflight(session, uid, Platform.linkedin, dry_run=True) is None       # dry runs don't count


def test_dry_run_is_recorded_and_retried_for_real(session):
    uid = _setup(session)
    site = FakeSite([_job("a")])
    res, _ = _run(uid, site, dry_run=True)
    assert site.dry == ["a"] and site.applied == [] and _apps(session, uid)["a"].status == ApplyStatus.dry_run
    site2 = FakeSite([_job("a")])
    _run(uid, site2)
    assert site2.applied == ["a"] and _apps(session, uid)["a"].status == ApplyStatus.applied


def test_needs_you_and_learned_answers(session):
    def needs(answerer):
        return ApplyOutcome(ApplyStatus.needs_you, "Couldn't answer: “Kubernetes years?”",
                            [QA("Kubernetes years?", None, "none")])

    def learns(answerer):
        answerer.new_learned["highest education"] = "Bachelor's"
        return ApplyOutcome(ApplyStatus.applied, None, [QA("Highest education", "Bachelor's", "ai")])

    uid = _setup(session)
    res, _ = _run(uid, FakeSite([_job("k"), _job("e")], outcomes={"k": needs, "e": learns}))
    apps = _apps(session, uid)
    assert apps["k"].status == ApplyStatus.needs_you and "Kubernetes" in apps["k"].reason
    assert res.skipped == {"needs you": 1} and res.collected == 1
    session.expire_all()
    assert get_or_create_apply_settings(session, uid).learned == {"highest education": "Bachelor's"}


def test_stops_after_three_failures_in_a_row(session):
    def fail(answerer):
        return ApplyOutcome(ApplyStatus.failed, "the form didn't open")

    uid = _setup(session)
    site = FakeSite([_job(str(i)) for i in range(6)], outcomes={str(i): fail for i in range(6)})
    res, _ = _run(uid, site)
    assert site.applied == ["0", "1", "2"]
    assert res.stop_reason == "stopped after 3 failed applications in a row"


def test_security_check_stops_the_run(session):
    uid = _setup(session)
    site = FakeSite([_job("a"), _job("b"), _job("c")], raise_on="b")
    res, _ = _run(uid, site)
    assert site.applied == ["a"] and res.stop_reason == "LinkedIn asked for a security check."


def test_login_failure_and_missing_account(session):
    uid = _setup(session)
    res, _ = _run(uid, FakeSite([_job("a")], login_ok=False))
    assert res.collected == 0 and "Couldn't log in to LinkedIn" in res.stop_reason
    assert session.scalar(select(Account.last_status)) == "login_failed"
    with pytest.raises(ValueError, match="Connect a Naukri account"):
        _run(uid, FakeSite([]), platform=Platform.naukri)
