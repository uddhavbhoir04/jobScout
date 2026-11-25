"""Job boards (Naukri, Indeed) -> filter -> save jobs whose description has an email.

Only jobs with a recruiter email in the full description are saved (most listings have none, so
runs check many jobs per save). The email, and any phone next to it, goes to Contacts. The target
counts jobs saved.

Shares post_event / save_contacts / ScrapeResult with the LinkedIn pipeline so the live feed and
contacts work the same way for every source.
"""
import logging
from dataclasses import dataclass
from datetime import timedelta

from jobscout.browser.manager import open_anonymous_context, open_context
from jobscout.config import get_settings
from jobscout.db import repo
from jobscout.db.models import Account, Platform, RunStatus, ScrapeRun
from jobscout.db.session import new_session
from jobscout.extract.ai import fallback_post_info
from jobscout.extract.contacts import find_emails, find_phones
from jobscout.extract.dates import DateRange, now
from jobscout.extract.rules import WORK_TYPES, experience_ok, location_ok, work_type_ok
from jobscout.pipeline.scrape import MAX_LIMIT, MAX_SCAN, ScrapeResult, load_accounts, post_event, save_contacts
from jobscout.pipeline.telegram import _SCAM, normalise_keywords
from jobscout.scrapers import get_board_scraper
from jobscout.scrapers.base import BoardBlocked, JobBoardScraper, JobListing, RawPost
from jobscout.security.crypto import decrypt

log = logging.getLogger(__name__)

BOARDS = (Platform.naukri, Platform.indeed)
# The job boards' own addresses (support, alerts) are not a recruiter to email.
BOARD_EMAIL_DOMAINS = ("naukri.com", "indeed.com", "infoedge.com")


def recruiter_emails(text: str) -> list[str]:
    return [e for e in find_emails(text)
            if not any(e.endswith("@" + d) or e.endswith("." + d) for d in BOARD_EMAIL_DOMAINS)]
SITE_NAME = {Platform.naukri: "Naukri", Platform.indeed: "Indeed"}


@dataclass(frozen=True)
class Search:
    keyword: str
    location: str | None
    work_types: tuple[str, ...]   # passed to the site's own filter; empty = any


def plan_searches(keywords: list[str], location: str | None, work_types: list[str] | None) -> list[Search]:
    """One search per keyword x location, matching the location rule:
    hybrid / on-site jobs must be in one of your locations, remote jobs can be anywhere.

    - Only Remote selected: one search per keyword with no location.
    - Locations set and remote wanted too: the city searches, plus one remote-only search with no
      location (a city search only finds remote jobs listed under that city).
    - No location: one search per keyword, India-wide.
    """
    cities = [c.strip() for c in (location or "").replace("/", ",").replace(";", ",").split(",") if c.strip()]
    allowed = {"on-site" if t.lower() in ("onsite", "on_site") else t.lower() for t in (work_types or [])}
    if allowed >= WORK_TYPES:
        allowed = set()
    types = tuple(sorted(allowed))
    remote_wanted = not allowed or "remote" in allowed
    out: list[Search] = []
    for kw in keywords:
        if not cities:
            out.append(Search(kw, None, types))
        elif allowed == {"remote"}:
            out.append(Search(kw, None, ("remote",)))
        else:
            out += [Search(kw, c, types) for c in cities]
            if remote_wanted:
                out.append(Search(kw, None, ("remote",)))
    return list(dict.fromkeys(out))


def listing_header(job: JobListing) -> str:
    """The structured fields as labelled lines, so the shared text filters can read them."""
    lines = [job.title]
    if job.company:
        lines.append(f"Company: {job.company}")
    if job.location:
        lines.append(f"Location: {job.location}")
    if job.work_mode:
        lines.append(f"Work mode: {job.work_mode}")
    if job.experience:
        lines.append(f"Experience: {job.experience}")
    if job.salary:
        lines.append(f"Salary: {job.salary}")
    return "\n".join(lines)


def hiring_summary(job: JobListing) -> str:
    head = f"{job.title} at {job.company}" if job.company else job.title
    return " | ".join(x for x in (head, job.experience, job.location) if x)


@dataclass
class BoardFilters:
    exp_min: int | None = None
    exp_max: int | None = None
    location: str | None = None
    work_types: list[str] | None = None

    def listing_reason(self, job: JobListing) -> str | None:
        """Checks on the search-result fields, before opening the job page.
        Location is only checked here: the site's location field is the job's location."""
        header = listing_header(job)
        if job.experience and not experience_ok(header, self.exp_min, self.exp_max):
            return "experience outside your range"
        where = f"Location: {job.location or ''}\nWork mode: {job.work_mode or ''}"  # not the title/company
        if not location_ok(where, self.location, self.work_types):
            return "location doesn't match"
        if job.work_mode and not work_type_ok(header, self.work_types):
            return "work type doesn't match"
        return None

    def description_reason(self, job: JobListing) -> str | None:
        """Checks the search results couldn't answer (no experience / work mode field), on the full text."""
        text = listing_header(job) + "\n\n" + job.description
        if not job.experience and not experience_ok(text, self.exp_min, self.exp_max):
            return "experience outside your range"
        if not work_type_ok(listing_header(job) if job.work_mode else text, self.work_types):
            return "work type doesn't match"
        if _SCAM.search(job.description):
            return "asks for a fee: likely a scam"
        return None


def _raw(job: JobListing, platform: Platform) -> RawPost:
    """The live-feed event format is shared with LinkedIn / Telegram."""
    return RawPost(external_id=job.external_id, url=job.url, author_name=job.company,
                   author_profile_url=None, text=listing_header(job) + "\n\n" + job.description,
                   relative_time=job.relative_time, posted_at=job.posted_at,
                   search_tag=f"{SITE_NAME[platform]}: {job.search_tag}")


def run_board_scrape(
    *, user_id: int, platform: Platform, keywords: list[str], date_range: DateRange, limit: int,
    exp_min: int | None = None, exp_max: int | None = None,
    location: str | None = None, work_types: list[str] | None = None, headless: bool | None = None,
    account_ids: list[int] | None = None,
    on_progress=None, on_event=None, should_stop=None, scraper_factory=None,
) -> ScrapeResult:
    """Save up to `limit` jobs from Naukri or Indeed that match the keywords and filters.

    With an active account for the site (Accounts page; `account_ids` narrows the choice) the search
    runs logged in, in that account's browser profile. Without one, or if its login fails, it runs
    as a guest.

    `scraper_factory(account)` (tests) returns a context manager yielding a JobBoardScraper; by
    default a real browser is opened.
    """
    if platform not in BOARDS:
        raise ValueError(f"{platform.value} is not a job board.")
    keywords = normalise_keywords(keywords)
    if not keywords:
        raise ValueError("Add at least one job title or skill to search for.")
    settings = get_settings()
    region = settings.default_phone_region
    headless = settings.headless if headless is None else headless
    limit = max(1, min(limit, MAX_LIMIT))
    searches = plan_searches(keywords, location, work_types)
    filters = BoardFilters(exp_min=exp_min, exp_max=exp_max, location=location, work_types=work_types)
    site = SITE_NAME[platform]

    session = new_session()
    accounts = load_accounts(session, user_id, platform, account_ids)
    account = accounts[0] if accounts else None
    run = ScrapeRun(user_id=user_id, platform=platform, account_ids=[account.id] if account else [], hashtags=keywords,
                    date_filter=date_range.label, requested_limit=limit)
    session.add(run)
    session.commit()
    result = ScrapeResult(run_id=run.id)
    seen: set[str] = set()
    blocked: str | None = None
    # "last 3 days" ends when the run starts; a job posted during the run ("Just posted") still counts.
    open_ended = date_range.end >= now() - timedelta(minutes=5)

    def in_range(posted) -> bool:
        return posted >= date_range.start and (open_ended or posted <= date_range.end)

    def done() -> bool:
        if should_stop and should_stop():
            result.stopped = True
            return True
        return result.collected >= limit or result.scanned >= MAX_SCAN

    def skip(job: JobListing, reason: str, notify: bool = True) -> None:
        result.skip(reason)
        if on_event and notify:
            on_event(post_event(_raw(job, platform), "skipped", reason))

    def process(scraper: JobBoardScraper, job: JobListing) -> None:
        result.scanned += 1
        if on_progress:
            on_progress(result)
        if job.external_id in seen:
            skip(job, "duplicate in this run", notify=False)
            return
        seen.add(job.external_id)
        if job.posted_at is not None and not in_range(job.posted_at):
            skip(job, "outside date range")
            return
        if reason := filters.listing_reason(job):
            skip(job, reason)
            return
        if repo.existing_external_ids(session, user_id, platform, [job.external_id]):
            skip(job, "already in database")
            return

        job.description = scraper.fetch_description(job) or job.description
        if reason := filters.description_reason(job):
            skip(job, reason)
            return

        emails = recruiter_emails(job.description)
        if not emails:
            skip(job, "no email in description")
            return
        phones = find_phones(job.description, region)
        contact_name = fallback_post_info(job.description).contact_name
        summary = hiring_summary(job)
        post = repo.insert_post(
            session, user_id=user_id, platform=platform, external_id=job.external_id, url=job.url,
            author_name=job.company, author_profile_url=None, description=job.description,
            hiring_for=summary, contact_name=contact_name, emails=emails, phones=phones,
            matched_hashtags=[job.search_tag] if job.search_tag else [], posted_at=job.posted_at, run_id=run.id,
            job_title=job.title, company=job.company, job_location=job.location, experience=job.experience,
            salary=job.salary, work_mode=job.work_mode,
        )
        if post is None:
            skip(job, "already in database")
            return
        save_contacts(session, user_id, post.id, contact_name, emails, phones)
        session.commit()
        result.saved += 1
        result.collected += 1
        if on_event:
            on_event(post_event(_raw(job, platform), "saved", post_id=post.id, hiring_for=summary,
                                contact_name=contact_name, emails=emails, phones=phones, hashtags=[],
                                counted=True, kind="job", url=job.url, job_title=job.title,
                                company=job.company, location=job.location, salary=job.salary,
                                experience=job.experience, work_mode=job.work_mode))
        if on_progress:
            on_progress(result)

    if scraper_factory is None:
        def scraper_factory(acc):
            return _BrowserScraper(platform, headless, acc)

    try:
        with scraper_factory(account) as scraper:
            if account is not None and not log_in(session, scraper, account, headless):
                result.failed_accounts.append(account.login_email)
                log.warning("%s login failed for %s: searching as a guest.", site, account.login_email)
            for s in searches:
                if done():
                    break
                where = s.location or ("anywhere (remote)" if s.work_types == ("remote",) else "India")
                log.info("%s: searching “%s” in %s…", site, s.keyword, where)
                try:
                    for job in scraper.search(s.keyword, s.location, date_range, list(s.work_types)):
                        if done():
                            break
                        process(scraper, job)
                except BoardBlocked as e:
                    blocked = str(e)
                    log.error("%s", e)
                    break
        if result.stopped:
            result.stop_reason = "stopped by you"
        elif result.collected >= limit:
            result.stop_reason = "target reached"
        elif blocked:
            result.stop_reason = blocked
        elif result.scanned >= MAX_SCAN:
            result.stop_reason = f"safety limit: checked {result.scanned} jobs"
        else:
            result.stop_reason = f"no more jobs with an email on {site} for these keywords and dates"
        log.info("Finished: %d/%d jobs saved (%s).", result.collected, limit, result.stop_reason)
        run.status = RunStatus.completed
    except Exception as e:
        session.rollback()
        run.status = RunStatus.failed
        run.error = f"{type(e).__name__}: {e}"[:2000]
        raise
    finally:
        run.posts_scanned = result.scanned
        run.posts_saved = result.collected
        run.finished_at = now()
        session.add(run)
        session.commit()
        session.close()
    return result


def log_in(session, scraper: JobBoardScraper, account: Account, headless: bool) -> bool:
    """Log the account in (saved session first). Records the result on the account."""
    try:
        ok = scraper.ensure_logged_in(account.login_email, decrypt(account.password_enc) if account.password_enc else "",
                                      allow_manual=not headless)
    except BoardBlocked:
        raise
    except Exception as e:  # noqa: BLE001 - a broken login page must not end the run
        log.warning("Login error: %s", e)
        ok = False
    account.last_status = "ok" if ok else "login_failed"
    if ok:
        account.last_login_at = now()
    session.commit()
    return ok


class _BrowserScraper:
    """Context manager: the account's browser profile (or an anonymous one per site) and the site's scraper."""

    def __init__(self, platform: Platform, headless: bool, account: Account | None = None):
        self.platform, self.headless, self.account = platform, headless, account
        self._cm = None

    def __enter__(self) -> JobBoardScraper:
        self._cm = (open_context(self.account, headless=self.headless) if self.account is not None
                    else open_anonymous_context(self.platform.value, headless=self.headless))
        ctx = self._cm.__enter__()
        return get_board_scraper(self.platform, ctx, self.headless)

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)
