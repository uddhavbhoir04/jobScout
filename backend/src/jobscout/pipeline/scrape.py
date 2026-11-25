"""Accounts -> scraper -> extract -> qualify -> save."""
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import select

from jobscout.browser.manager import open_context
from jobscout.config import get_settings
from jobscout.db import repo
from jobscout.db.models import Account, Platform, RunStatus, ScrapeRun
from jobscout.db.session import new_session
from jobscout.extract.ai import Gemini, fallback_post_info
from jobscout.extract.contacts import clean_person_name, find_emails, find_phones, hashtags_in, qualifies
from jobscout.extract.dates import DateRange, now, relative_bounds
from jobscout.extract.rules import experience_ok, location_ok, work_type_ok
from jobscout.scrapers import get_scraper
from jobscout.scrapers.base import LoginRequired
from jobscout.security.crypto import decrypt

log = logging.getLogger(__name__)

MAX_LIMIT = 100
# Keep going until the target is reached. This cap only stops a run that can never get there.
SCAN_PER_TARGET = 60       # check at most ~60 posts per wanted contact...
MAX_SCAN = 6000            # ...and never more than this in one run
TOO_OLD_STREAK = 5         # results are newest-first; stop a tag after this many older posts
CONTACT_HINT_RE = re.compile(
    r"\b(dm|contact|reach\s+out|send|share|mail|e-?mail|cv|resume|connect\s+with|ping|poc|spoc|recruiter)\b",
    re.I,
)


@dataclass
class ScrapeResult:
    run_id: int
    scanned: int = 0
    saved: int = 0             # posts stored (incl. name-only / already-known contacts)
    collected: int = 0         # posts that gave at least one NEW email or phone: what the target counts
    stop_reason: str = ""
    skipped: dict[str, int] = field(default_factory=dict)
    failed_accounts: list[str] = field(default_factory=list)
    unprocessed_tags: list[str] = field(default_factory=list)
    stopped: bool = False

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def normalise_tags(tags: list[str]) -> list[str]:
    out: dict[str, None] = {}
    for t in tags:
        for part in t.replace(",", " ").split():
            part = part.strip().lstrip("#").lower()
            if part:
                out.setdefault("#" + part, None)
    return list(out)


HIRING_TAG = "#hiring"  # always required: every saved post must be a hiring post
# LinkedIn content search silently returns "No results found" once a query holds more than 6
# hashtags (verified Nov 2026: #hiring + 5 role tags works, #hiring + 6 does not, each tag alone works).
MAX_HASHTAGS_PER_QUERY = 6


def build_queries(required: list[str], optional: list[str]) -> tuple[str, list[str]]:
    """(first query, follow-up queries).

    Role hashtags are searched together with the required ones, as few searches as LinkedIn allows:
        required=[#hiring], optional=[#a, #b]  ->  "#hiring AND (#a OR #b)"
    Longer role lists are split into groups so no query exceeds MAX_HASHTAGS_PER_QUERY.
    Follow-ups are the remaining groups, then one search per role tag (each still with the required
    hashtags), used to keep collecting when the earlier searches run out before the target.
    Every post is checked against match_tags() whichever search found it.
    """
    group = lambda tags, op: tags[0] if len(tags) == 1 else "(" + f" {op} ".join(tags) + ")"  # noqa: E731
    req = " AND ".join(required)
    with_req = lambda q: f"{req} AND {q}" if req else q  # noqa: E731
    size = max(1, MAX_HASHTAGS_PER_QUERY - len(required))
    chunks = [optional[i:i + size] for i in range(0, len(optional), size)]
    queries = [with_req(group(c, "OR")) for c in chunks] or [req]
    if len(optional) > 1:
        queries += [with_req(t) for t in optional]
    elif not optional and len(required) > 1:
        queries += list(required)
    out: list[str] = []
    for q in queries:
        if q not in out:
            out.append(q)
    return out[0], out[1:]


def match_tags(text: str, required: list[str], optional: list[str]) -> tuple[list[str] | None, str | None]:
    """Rule: the post has ALL required hashtags and (if any are given) AT LEAST ONE optional hashtag.
    Returns (matched hashtags, None) or (None, skip reason)."""
    req = hashtags_in(text, required)
    if len(req) < len(required):
        missing = [t for t in required if t not in req]
        return None, f"missing required {' '.join(missing)}"
    opt = hashtags_in(text, optional)
    if optional and not opt:
        return None, "no role hashtag"
    return req + opt, None


def load_accounts(session, user_id: int, platform: Platform, ids: list[int] | None) -> list[Account]:
    q = (select(Account)
         .where(Account.user_id == user_id, Account.platform == platform, Account.is_active.is_(True))
         .order_by(Account.id))
    if ids:
        q = q.where(Account.id.in_(ids))
    return list(session.scalars(q))


def run_scrape(
    *, user_id: int, platform: Platform, tags: list[str], date_range: DateRange, limit: int,
    required_tags: list[str] | None = None, use_ai: bool = False,
    account_ids: list[int] | None = None, headless: bool | None = None,
    exp_min: int | None = None, exp_max: int | None = None,
    location: str | None = None, work_types: list[str] | None = None,
    on_progress=None, on_event=None, should_stop=None,
) -> ScrapeResult:
    """Save posts that contain #hiring (+ any extra `required_tags`) AND at least one of `tags`.

    All role hashtags are searched in one combined LinkedIn query together with #hiring.
    on_event(dict) gets one event per checked post (for live UIs); should_stop() ends the run early.
    """
    settings = get_settings()
    required = normalise_tags([HIRING_TAG] + list(required_tags or []))
    optional = [t for t in normalise_tags(tags) if t not in required]
    if not optional:
        raise ValueError("Add at least one role hashtag: every saved post must have #hiring and a role hashtag.")
    tags = required + optional
    combined, backups = build_queries(required, optional)
    limit = max(1, min(limit, MAX_LIMIT))
    headless = settings.headless if headless is None else headless
    # AI post analysis costs API money: only when enabled AND the user is on the paid plan.
    ai = Gemini(settings) if (settings.ai_extraction and use_ai) else None
    if ai is not None and not ai.available:
        log.warning("Gemini unavailable (%s): using rule-based extraction.", ai._disabled_reason)

    session = new_session()
    accounts = load_accounts(session, user_id, platform, account_ids)
    if not accounts:
        raise ValueError(f"No active {platform.value} accounts. Add one with `jobscout account add`.")

    run = ScrapeRun(user_id=user_id, platform=platform, account_ids=[a.id for a in accounts], hashtags=tags,
                    date_filter=date_range.label, requested_limit=limit)
    session.add(run)
    session.commit()
    result = ScrapeResult(run_id=run.id)
    seen_this_run: set[str] = set()
    scan_cap = min(limit * SCAN_PER_TARGET, MAX_SCAN)

    def done() -> bool:
        if should_stop and should_stop():
            result.stopped = True
            return True
        return result.collected >= limit or result.scanned >= scan_cap

    # One combined search first. If it runs out before the target is reached, keep going with
    # "#hiring AND #tag" for each role hashtag (already-seen posts are skipped).
    queue: list[str] = [combined, *backups]
    filters = PostFilters(exp_min=exp_min, exp_max=exp_max, location=location, work_types=work_types)
    try:
        for account in accounts:
            if done() or not queue:
                break
            with open_context(account, headless=headless) as ctx:
                scraper = get_scraper(platform, ctx)
                ok = scraper.ensure_logged_in(account.login_email, decrypt(account.password_enc),
                                              allow_manual=not headless)
                account.last_status = "ok" if ok else "login_failed"
                if ok:
                    account.last_login_at = now()
                session.commit()
                if not ok:
                    log.error("Login failed for account %s (%s); trying the next account.", account.id, account.login_email)
                    result.failed_accounts.append(account.login_email)
                    continue

                while queue and not done():
                    query = queue[0]
                    try:
                        found = _scrape_tag(session, scraper, ai, run, query, required, optional, date_range,
                                            result, seen_this_run, done, on_progress, on_event, filters)
                    except LoginRequired as e:
                        log.error("Account %s was logged out / challenged: %s", account.id, e)
                        account.last_status = "challenged"
                        session.commit()
                        result.failed_accounts.append(account.login_email)
                        break  # same query continues on the next account
                    queue.pop(0)
                    if not done() and queue:
                        why = "found nothing" if found == 0 else f"ran out after {found} posts"
                        log.info("Search %s %s; %d/%d collected, continuing with %s",
                                 query, why, result.collected, limit, queue[0])
        result.unprocessed_tags = [] if done() else queue
        if result.stopped:
            result.stop_reason = "stopped by you"
        elif result.collected >= limit:
            result.stop_reason = "target reached"
        elif result.scanned >= scan_cap:
            result.stop_reason = f"safety limit: checked {result.scanned} posts"
        elif queue:
            result.stop_reason = "no working LinkedIn account left"
        else:
            result.stop_reason = "no more matching posts on LinkedIn for these hashtags and dates"
        log.info("Finished: %d/%d collected (%s).", result.collected, limit, result.stop_reason)
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


@dataclass
class PostFilters:
    """Optional filters on what the post asks for. Posts that don't say are kept."""
    exp_min: int | None = None
    exp_max: int | None = None
    location: str | None = None
    work_types: list[str] | None = None

    def reject_reason(self, text: str) -> str | None:
        if not experience_ok(text, self.exp_min, self.exp_max):
            return "experience outside your range"
        if not location_ok(text, self.location, self.work_types):
            return "location doesn't match"
        if not work_type_ok(text, self.work_types):
            return "work type doesn't match"
        return None


def post_event(raw, status: str, reason: str | None = None, **extra) -> dict:
    return {
        "type": "post", "status": status, "reason": reason, "tag": raw.search_tag,
        "author": raw.author_name, "author_url": raw.author_profile_url, "posted": raw.relative_time,
        "text": raw.text[:1200], **extra,
    }


def _scrape_tag(session, scraper, ai: Gemini | None, run: ScrapeRun, query: str,
                required: list[str], optional: list[str], date_range: DateRange, result: ScrapeResult,
                seen_this_run: set[str], done, on_progress, on_event=None,
                filters: PostFilters | None = None) -> int:
    """Process one LinkedIn search. Returns how many posts the search showed (0 = no results)."""
    region = get_settings().default_phone_region
    too_old = 0
    found = 0

    def skip(raw, reason: str, notify: bool = True) -> None:
        result.skip(reason)
        if on_event and notify:
            on_event(post_event(raw, "skipped", reason))

    for raw in scraper.search(query, date_range):
        found += 1
        if done():
            return found
        result.scanned += 1
        if on_progress:
            on_progress(result)

        if raw.external_id in seen_this_run:
            skip(raw, "duplicate in this run", notify=False)
            continue
        seen_this_run.add(raw.external_id)

        bounds = relative_bounds(raw.relative_time or "")
        if bounds is not None:
            earliest, latest = bounds
            if latest < date_range.start:
                too_old += 1
                skip(raw, "outside date range")
                if too_old >= TOO_OLD_STREAK:
                    return found
                continue
            too_old = 0
            if not date_range.overlaps(earliest, latest):
                skip(raw, "outside date range")
                continue

        matched, reason = match_tags(raw.text, required, optional)
        if matched is None:
            skip(raw, reason)
            continue
        if filters and (reason := filters.reject_reason(raw.text)):
            skip(raw, reason)
            continue

        if repo.existing_external_ids(session, run.user_id, scraper.platform, [raw.external_id]):
            skip(raw, "already in database")
            continue

        emails = find_emails(raw.text)
        phones = find_phones(raw.text, region)
        # Cheap pre-check: no email/phone and no "contact X" style wording → nothing to save.
        if not emails and not phones and not CONTACT_HINT_RE.search(raw.text):
            skip(raw, "no email or contact name")
            continue
        info = ai.analyse_post(raw.text, raw.author_name) if ai is not None else fallback_post_info(raw.text)
        if not info.is_hiring_post:
            skip(raw, "not a hiring post")
            continue
        if not qualifies(emails, info.contact_name):
            skip(raw, "no email or contact name")
            continue

        post = repo.insert_post(
            session,
            user_id=run.user_id,
            platform=scraper.platform,
            external_id=raw.external_id,
            url=raw.url,
            author_name=raw.author_name,
            author_profile_url=raw.author_profile_url,
            description=raw.text,
            hiring_for=info.hiring_for,
            contact_name=info.contact_name,
            emails=emails,
            phones=phones,
            matched_hashtags=matched,
            posted_at=raw.posted_at,
            run_id=run.id,
        )
        if post is None:
            skip(raw, "already in database")
            continue
        contact_name = info.contact_name or clean_person_name(raw.author_name)
        new_values = save_contacts(session, run.user_id, post.id, contact_name, emails, phones)
        session.commit()
        result.saved += 1
        counted = new_values > 0
        if counted:
            result.collected += 1
        if on_event:
            on_event(post_event(raw, "saved", post_id=post.id, hiring_for=info.hiring_for,
                                contact_name=contact_name, emails=emails, phones=phones, hashtags=matched,
                                counted=counted,
                                note=None if counted else ("no email or phone, name only" if not (emails or phones)
                                                           else "you already have this email/phone")))
        if on_progress:
            on_progress(result)
    return found


def save_contacts(session, user_id: int, post_id: int, name: str | None,
                  emails: list[str], phones: list[str]) -> int:
    """One contact per email; the first phone goes with the first email; extra phones get their own row.
    Returns how many emails/phones were new for this user."""
    phones = list(phones)
    new = 0

    def upsert(**kw):
        nonlocal new
        new += repo.upsert_contact(session, user_id=user_id, post_id=post_id, **kw)[1]

    if emails:
        for i, email in enumerate(emails):
            upsert(name=name if i == 0 else None, email=email, phone=phones.pop(0) if i == 0 and phones else None)
    elif phones:
        upsert(name=name, email=None, phone=phones.pop(0))
    else:
        upsert(name=name, email=None, phone=None)
    for phone in phones:
        upsert(name=None, email=None, phone=phone)
    return new
