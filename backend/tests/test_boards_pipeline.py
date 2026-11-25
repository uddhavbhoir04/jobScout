"""run_board_scrape end to end with a fake job board (needs TEST_DATABASE_URL)."""
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import select

from jobscout.db.models import Contact, Platform, Post, RunStatus, ScrapeRun
from jobscout.extract.dates import DateRange, now
from jobscout.pipeline.boards import run_board_scrape
from jobscout.scrapers.base import BoardBlocked, JobListing
from jobscout.security.users import create_user

DESCRIPTIONS = {
    "with-mail": "Great role. Send your CV to Priya at careers@acme.io or call 9876543210.",
    "senior": "Looking for someone with 8+ years of Python. Mail hr@acme.io",
    "plain": "Apply on the site.",
    "phone-only": "Call 9876543210 to apply.",
    "board-mail": "Questions? Write to support@naukri.com",
}


def _job(ext, location="Pune", work_mode=None, experience="2-4 Yrs", days_old=0, **kw):
    return JobListing(external_id=ext, url=f"https://example.test/{ext}", title=f"Python Dev {ext}",
                      company="Acme", location=location, experience=experience, work_mode=work_mode,
                      posted_at=now() - timedelta(days=days_old), description="snippet", **kw)


class FakeBoard:
    platform = Platform.naukri

    def __init__(self, results, blocked_after=None, login_ok=True):
        self.results = results           # {(keyword, location): [JobListing]}
        self.login_ok = login_ok
        self.logins = []
        self.searches = []
        self.opened = []
        self.blocked_after = blocked_after

    def search(self, keyword, location, date_range, work_types):
        self.searches.append((keyword, location, tuple(work_types)))
        if self.blocked_after is not None and len(self.searches) > self.blocked_after:
            raise BoardBlocked("Naukri refused the browser (Access Denied).")
        for j in self.results.get((keyword, location), []):
            j.search_tag = keyword
            yield j

    def ensure_logged_in(self, email, password, allow_manual):
        self.logins.append((email, password, allow_manual))
        return self.login_ok

    def fetch_description(self, job):
        self.opened.append(job.external_id)
        return DESCRIPTIONS.get(job.external_id, f"Mail jobs{job.external_id}@acme.io")


def _run(session, board, **kw):
    uid = create_user(session, "u@example.com", "password123").id

    @contextmanager
    def factory(account=None):
        yield board

    week = DateRange("last-7d", now() - timedelta(days=7), now())
    args = dict(user_id=uid, platform=Platform.naukri, keywords=["python"], date_range=week, limit=20,
                location="Pune", work_types=["hybrid", "on-site"], scraper_factory=factory)
    events = []
    res = run_board_scrape(**{**args, **kw}, on_event=events.append)
    return uid, res, events


def test_saves_only_jobs_with_an_email(session):
    board = FakeBoard({("python", "Pune"): [
        _job("plain"),                                           # no email: skipped
        _job("with-mail"),                                       # email -> saved + Contacts
        _job("phone-only"),                                      # a phone alone doesn't count
        _job("board-mail"),                                      # the board's own address doesn't count
        _job("plain"),                                           # duplicate in this run
        _job("chennai", location="Chennai"),                     # wrong city
        _job("remote", location="Remote", work_mode="remote"),   # remote not wanted: needs a Pune location
        _job("old", days_old=20),                                # outside the date range
        _job("senior", experience=None),                         # experience read from the description
    ]})
    uid, res, events = _run(session, board, exp_max=5)

    assert board.searches == [("python", "Pune", ("hybrid", "on-site"))]
    assert res.collected == res.saved == 1
    assert res.skipped == {"duplicate in this run": 1, "location doesn't match": 2, "outside date range": 1,
                           "experience outside your range": 1, "no email in description": 3}
    # job pages are only opened after the cheap filters
    assert board.opened == ["plain", "with-mail", "phone-only", "board-mail", "senior"]
    assert res.stop_reason == "no more jobs with an email on Naukri for these keywords and dates"

    posts = {p.external_id: p for p in session.scalars(select(Post).where(Post.user_id == uid))}
    assert set(posts) == {"with-mail"}
    p = posts["with-mail"]
    assert (p.job_title, p.company, p.job_location, p.experience) == ("Python Dev with-mail", "Acme", "Pune", "2-4 Yrs")
    assert p.hiring_for == "Python Dev with-mail at Acme | 2-4 Yrs | Pune"
    assert p.emails == ["careers@acme.io"] and p.phones == ["+919876543210"]
    contacts = session.scalars(select(Contact).where(Contact.user_id == uid)).all()
    assert [(c.email, c.phone) for c in contacts] == [("careers@acme.io", "+919876543210")]

    run = session.get(ScrapeRun, res.run_id)
    assert run.status == RunStatus.completed and run.platform == Platform.naukri and run.posts_saved == 1
    saved = [e for e in events if e["type"] == "post" and e["status"] == "saved"]
    assert saved[0]["kind"] == "job" and saved[0]["url"] == "https://example.test/with-mail"


def test_remote_jobs_anywhere_when_remote_is_wanted(session):
    board = FakeBoard({("python", "Pune"): [_job("pune", work_mode="hybrid")],
                       ("python", None): [_job("anywhere", location="Remote", work_mode="remote")]})
    uid, res, _ = _run(session, board, work_types=["remote", "hybrid"])
    assert board.searches == [("python", "Pune", ("hybrid", "remote")), ("python", None, ("remote",))]
    assert res.collected == 2


def test_job_posted_during_the_run_counts_but_not_for_a_closed_range(session):
    # "Just posted" is stamped with the current time, after the range's end (the run's start)
    def board():
        return FakeBoard({("python", "Pune"): [_job("new")]})
    b = board()
    b.results[("python", "Pune")][0].posted_at = now() + timedelta(minutes=1)
    _, res, _ = _run(session, b)
    assert res.collected == 1

    @contextmanager
    def factory(account=None):
        b2 = board()
        yield b2

    yesterday = DateRange("yesterday", now() - timedelta(days=2), now() - timedelta(days=1))
    uid = session.scalar(select(Post.user_id))
    res2 = run_board_scrape(user_id=uid, platform=Platform.naukri, keywords=["python"], date_range=yesterday,
                            limit=5, location="Pune", scraper_factory=factory)
    assert res2.skipped == {"outside date range": 1}


def test_target_and_rerun_dedupe(session):
    board = FakeBoard({("python", "Pune"): [_job(str(i)) for i in range(5)]})
    uid, res, _ = _run(session, board, limit=3)
    assert res.collected == 3 and res.stop_reason == "target reached"
    # second run: the 3 saved ones are skipped without opening their pages
    board2 = FakeBoard({("python", "Pune"): [_job(str(i)) for i in range(5)]})

    @contextmanager
    def factory(account=None):
        yield board2

    week = DateRange("last-7d", now() - timedelta(days=7), now() + timedelta(minutes=5))
    res2 = run_board_scrape(user_id=uid, platform=Platform.naukri, keywords=["python"], date_range=week, limit=10,
                            location="Pune", scraper_factory=factory)
    assert res2.skipped.get("already in database") == 3 and res2.collected == 2
    assert board2.opened == ["3", "4"]


def test_blocked_site_stops_with_its_message(session):
    board = FakeBoard({("python", "Pune"): [_job("a")]}, blocked_after=0)
    _, res, _ = _run(session, board)
    assert res.collected == 0
    assert res.stop_reason == "Naukri refused the browser (Access Denied)."


def _account(session, uid, platform=Platform.naukri, email="me@example.com", password="secret"):
    from jobscout.db.models import Account
    from jobscout.security.crypto import encrypt

    acc = Account(user_id=uid, platform=platform, login_email=email, password_enc=encrypt(password))
    session.add(acc)
    session.commit()
    return acc


def _run_with_account(session, board, login_ok_expected, monkeypatch, **kw):
    from cryptography.fernet import Fernet

    from jobscout.config import get_settings

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())
    uid = create_user(session, "u@example.com", "password123").id
    acc = _account(session, uid, **kw)
    _account(session, uid, platform=Platform.linkedin, email="li@example.com")  # other sites' accounts are ignored
    used = []

    @contextmanager
    def factory(account=None):
        used.append(account.login_email if account else None)
        yield board

    week = DateRange("last-7d", now() - timedelta(days=7), now())
    res = run_board_scrape(user_id=uid, platform=Platform.naukri, keywords=["python"], date_range=week, limit=5,
                           location="Pune", headless=False, scraper_factory=factory)
    session.refresh(acc)
    return acc, res, used


def test_runs_logged_in_with_the_sites_account(session, monkeypatch):
    board = FakeBoard({("python", "Pune"): [_job("a")]})
    acc, res, used = _run_with_account(session, board, True, monkeypatch)
    assert used == ["me@example.com"]                      # the account's browser profile
    assert board.logins == [("me@example.com", "secret", True)]
    assert acc.last_status == "ok" and acc.last_login_at is not None
    assert res.collected == 1 and res.failed_accounts == []
    assert session.get(ScrapeRun, res.run_id).account_ids == [acc.id]


def test_failed_login_still_searches_as_guest(session, monkeypatch):
    board = FakeBoard({("python", "Pune"): [_job("a")]}, login_ok=False)
    acc, res, _ = _run_with_account(session, board, False, monkeypatch)
    assert acc.last_status == "login_failed"
    assert res.failed_accounts == ["me@example.com"] and res.collected == 1


def test_no_account_searches_as_guest(session):
    board = FakeBoard({("python", "Pune"): [_job("a")]})
    _, res, _ = _run(session, board)
    assert board.logins == [] and res.collected == 1
