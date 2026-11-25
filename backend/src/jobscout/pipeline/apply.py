"""Auto apply: search a site's Easy Apply jobs -> filter -> apply with the user's account.

Safety limits that can't be turned off: a daily cap per site, a random 20-60 s wait after every
submitted application, the run stops on any login / security check or after 3 failures in a row,
and a job is never applied to twice (unique row per user + site + job in `applications`).

Dry run fills every form but doesn't click the final submit; it doesn't count toward the daily cap.
"""
import logging
import random
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from jobscout.apply.answers import Answerer
from jobscout.apply.base import ApplyOutcome, Applier
from jobscout.browser.manager import open_context
from jobscout.config import get_settings
from jobscout.db.models import Application, ApplySettings, ApplyStatus, EmailSettings, Platform, RunStatus, ScrapeRun
from jobscout.db.session import new_session
from jobscout.extract.dates import DateRange, now
from jobscout.pipeline.boards import BoardFilters, listing_header, plan_searches
from jobscout.pipeline.scrape import MAX_LIMIT, ScrapeResult, load_accounts
from jobscout.pipeline.telegram import normalise_keywords
from jobscout.scrapers.base import BoardBlocked, JobListing, LoginRequired
from jobscout.security.crypto import decrypt

log = logging.getLogger(__name__)

SITES = (Platform.linkedin, Platform.naukri, Platform.indeed)
SITE_NAME = {Platform.linkedin: "LinkedIn", Platform.naukri: "Naukri", Platform.indeed: "Indeed"}
DEFAULT_DAILY_CAP = 25
GAP_SECONDS = (20, 60)          # wait after each submitted application
MAX_FAILURES_IN_A_ROW = 3
MAX_CHECKED = 600               # stop a run that can never fill its quota
# a job with one of these is done; dry_run and failed ones may be tried again
FINAL = (ApplyStatus.applied, ApplyStatus.skipped, ApplyStatus.needs_you)


def get_or_create_apply_settings(session, user_id: int) -> ApplySettings:
    row = session.scalar(select(ApplySettings).where(ApplySettings.user_id == user_id))
    if row is None:
        row = ApplySettings(user_id=user_id, answers={}, learned={}, daily_cap=DEFAULT_DAILY_CAP)
        session.add(row)
        session.flush()
    return row


def preflight(session, user_id: int, platform: Platform, dry_run: bool, account_ids: list[int] | None = None) -> str | None:
    """Why a run can't start (no account, today's cap used up), or None."""
    site = SITE_NAME[platform]
    if not load_accounts(session, user_id, platform, account_ids):
        return f"Connect a {site} account on the Accounts page first: applying needs you to be logged in."
    if not dry_run:
        cap = get_or_create_apply_settings(session, user_id).daily_cap
        if applied_today(session, user_id, platform) >= cap:
            return (f"You've reached today's limit of {cap} {site} applications. "
                    "Try again tomorrow, or raise the limit under Answers & limits.")
    return None


def start_of_today(ref: datetime | None = None) -> datetime:
    ref = ref or now()
    return ref.replace(hour=0, minute=0, second=0, microsecond=0)


def applied_today(session, user_id: int, platform: Platform) -> int:
    return session.scalar(select(func.count()).select_from(Application).where(
        Application.user_id == user_id, Application.platform == platform,
        Application.status == ApplyStatus.applied, Application.updated_at >= start_of_today())) or 0


def _done_ids(session, user_id: int, platform: Platform, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    return set(session.scalars(select(Application.external_id).where(
        Application.user_id == user_id, Application.platform == platform,
        Application.external_id.in_(ids), Application.status.in_(FINAL))))


def _record(session, user_id: int, platform: Platform, job: JobListing, out: ApplyOutcome, run_id: int) -> int:
    values = dict(user_id=user_id, platform=platform, external_id=job.external_id, url=job.url, title=job.title,
                  company=job.company, location=job.location, status=out.status, reason=out.reason,
                  questions=[q.as_dict() for q in out.questions], run_id=run_id)
    stmt = pg_insert(Application).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_applications_user_platform_external_id",
        set_={k: stmt.excluded[k] for k in ("url", "title", "company", "location", "status", "reason", "questions",
                                              "run_id")} | {"updated_at": func.now()},
    ).returning(Application.id)
    return session.execute(stmt).scalar()


def _event(job: JobListing, platform: Platform, status: str, reason: str | None = None, **extra) -> dict:
    """Same shape as the scrape feed's post events, so LiveFeed renders it."""
    return {"type": "post", "status": "saved" if status in ("applied", "dry_run") else "skipped",
            "apply_status": status, "reason": reason, "kind": "application",
            "tag": f"{SITE_NAME[platform]}: {job.search_tag}", "author": job.company, "author_url": None,
            "posted": job.relative_time, "text": (listing_header(job) + "\n\n" + job.description)[:1200],
            "url": job.url, "job_title": job.title, "company": job.company, "location": job.location,
            "salary": job.salary, "experience": job.experience, "work_mode": job.work_mode, **extra}


def run_apply(
    *, user_id: int, platform: Platform, keywords: list[str], date_range: DateRange, limit: int,
    exp_min: int | None = None, exp_max: int | None = None, location: str | None = None,
    work_types: list[str] | None = None, dry_run: bool = False, headless: bool | None = None,
    use_ai: bool = False, account_ids: list[int] | None = None,
    on_progress=None, on_event=None, should_stop=None, applier_factory=None, sleep=time.sleep, llm=None,
) -> ScrapeResult:
    """Apply to up to `limit` Easy Apply jobs on `platform` with the user's account.

    `applier_factory(account)` (tests) returns a context manager yielding an Applier; by default the
    account's browser profile is opened. `collected` counts applications sent (or filled, in a dry run).
    """
    if platform not in SITES:
        raise ValueError(f"Auto apply doesn't support {platform.value}.")
    keywords = normalise_keywords(keywords)
    if not keywords:
        raise ValueError("Add at least one job title or skill to search for.")
    site = SITE_NAME[platform]
    settings = get_settings()
    headless = settings.headless if headless is None else headless
    limit = max(1, min(limit, MAX_LIMIT))

    session = new_session()
    if problem := preflight(session, user_id, platform, dry_run, account_ids):
        session.close()
        raise ValueError(problem)
    account = load_accounts(session, user_id, platform, account_ids)[0]
    prefs = get_or_create_apply_settings(session, user_id)
    email_settings = session.scalar(select(EmailSettings).where(EmailSettings.user_id == user_id))
    resume_path = email_settings.resume_path if email_settings else None
    resume_text = email_settings.resume_text if email_settings else ""
    if llm is None and use_ai:
        from jobscout.llm import LLM

        llm = LLM(temperature=0.1)
        if not llm.available:
            log.warning("AI not available (%s): only saved answers will be used.", llm._disabled_reason)
            llm = None
    answerer = Answerer(prefs.answers, prefs.learned, resume_text or "", llm if use_ai else None, resume_path)

    left_today = prefs.daily_cap - applied_today(session, user_id, platform)
    target = limit if dry_run else min(limit, left_today)

    run = ScrapeRun(user_id=user_id, kind="apply", platform=platform, account_ids=[account.id], hashtags=keywords,
                    date_filter=date_range.label, requested_limit=limit)
    session.add(run)
    session.commit()
    result = ScrapeResult(run_id=run.id)
    filters = BoardFilters(exp_min=exp_min, exp_max=exp_max, location=location, work_types=work_types)
    seen: set[str] = set()
    failures = 0
    stop_reason: str | None = None
    open_ended = date_range.end >= now() - timedelta(minutes=5)

    def stopped() -> bool:
        if should_stop and should_stop():
            result.stopped = True
            return True
        return False

    def done() -> bool:
        return stopped() or result.collected >= target or result.scanned >= MAX_CHECKED or stop_reason is not None

    def skip(job: JobListing, reason: str) -> None:
        result.skip(reason)
        if on_event:
            on_event(_event(job, platform, "skipped", reason))

    def precheck(job: JobListing) -> str | None:
        """The applier calls this once it has the full description, before touching the form."""
        return filters.description_reason(job)

    def wait_between() -> None:
        left = random.uniform(*GAP_SECONDS)
        while left > 0 and not stopped():   # in small steps so Stop works during the wait
            step = min(2.0, left)
            sleep(step)
            left -= step

    if applier_factory is None:
        def applier_factory(acc):
            return _BrowserApplier(platform, headless, acc)

    try:
        with applier_factory(account) as applier:
            ok = applier.ensure_logged_in(account.login_email, decrypt(account.password_enc), not headless)
            account.last_status = "ok" if ok else "login_failed"
            if ok:
                account.last_login_at = now()
            session.commit()
            if not ok:
                result.failed_accounts.append(account.login_email)
                raise LoginRequired(f"Couldn't log in to {site} as {account.login_email}. Log in again on the Accounts page.")

            for s in plan_searches(keywords, location, work_types):
                if done():
                    break
                log.info("%s: Easy Apply jobs for “%s” in %s…", site, s.keyword, s.location or "any location")
                for job in applier.search(s.keyword, s.location, date_range, list(s.work_types)):
                    if done():
                        break
                    result.scanned += 1
                    if on_progress:
                        on_progress(result)
                    if job.external_id in seen:
                        result.skip("duplicate in this run")
                        continue
                    seen.add(job.external_id)
                    if job.posted_at is not None and (job.posted_at < date_range.start
                                                      or (not open_ended and job.posted_at > date_range.end)):
                        skip(job, "outside date range")
                        continue
                    if reason := filters.listing_reason(job):
                        skip(job, reason)
                        continue
                    if _done_ids(session, user_id, platform, [job.external_id]):
                        skip(job, "already applied")
                        continue

                    out = applier.apply(job, answerer, dry_run, precheck)
                    if out.filtered:
                        skip(job, out.reason or "filtered")   # filtered on the full description: nothing to record
                        continue
                    _record(session, user_id, platform, job, out, run.id)
                    if answerer.new_learned:
                        prefs.learned = {**(prefs.learned or {}), **answerer.new_learned}
                        answerer.new_learned = {}
                    session.commit()
                    st = out.status.value
                    if out.status in (ApplyStatus.applied, ApplyStatus.dry_run):
                        result.saved += 1
                        result.collected += 1
                        failures = 0
                    elif out.status == ApplyStatus.failed:
                        failures += 1
                        result.skip("failed")
                    else:
                        result.skip("needs you" if out.status == ApplyStatus.needs_you else (out.reason or st))
                    if on_event:
                        on_event(_event(job, platform, st, out.reason, counted=out.status in (ApplyStatus.applied, ApplyStatus.dry_run),
                                        questions=[q.as_dict() for q in out.questions], screenshot=out.screenshot))
                    if on_progress:
                        on_progress(result)
                    if failures >= MAX_FAILURES_IN_A_ROW:
                        stop_reason = f"stopped after {failures} failed applications in a row"
                        break
                    if out.status == ApplyStatus.applied and not done():
                        wait_between()
    except (BoardBlocked, LoginRequired) as e:
        stop_reason = str(e)
        log.error("%s", e)
    except Exception as e:
        session.rollback()
        run.status = RunStatus.failed
        run.error = f"{type(e).__name__}: {e}"[:2000]
        _finish(session, run, result)
        raise
    if result.stopped:
        result.stop_reason = "stopped by you"
    elif result.collected >= target:
        result.stop_reason = "target reached" if target == limit else f"today's limit of {prefs.daily_cap} reached"
    elif stop_reason:
        result.stop_reason = stop_reason
    elif result.scanned >= MAX_CHECKED:
        result.stop_reason = f"safety limit: checked {result.scanned} jobs"
    else:
        result.stop_reason = f"no more matching Easy Apply jobs on {site} for these keywords and dates"
    log.info("Finished: %d/%d %s (%s).", result.collected, target, "filled (dry run)" if dry_run else "applied",
             result.stop_reason)
    run.status = RunStatus.completed
    _finish(session, run, result)
    return result


def _finish(session, run: ScrapeRun, result: ScrapeResult) -> None:
    run.posts_scanned = result.scanned
    run.posts_saved = result.collected
    run.finished_at = now()
    session.add(run)
    session.commit()
    session.close()


class _BrowserApplier:
    """Context manager: the account's browser profile and the site's applier."""

    def __init__(self, platform: Platform, headless: bool, account):
        self.platform, self.headless, self.account = platform, headless, account
        self._cm = None

    def __enter__(self) -> Applier:
        self._cm = open_context(self.account, headless=self.headless)
        ctx = self._cm.__enter__()
        if self.platform == Platform.linkedin:
            from jobscout.apply.linkedin import LinkedInApplier

            return LinkedInApplier(ctx, self.headless)
        if self.platform == Platform.naukri:
            from jobscout.apply.naukri import NaukriApplier

            return NaukriApplier(ctx, self.headless)
        from jobscout.apply.indeed import IndeedApplier

        return IndeedApplier(ctx, self.headless)

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)
