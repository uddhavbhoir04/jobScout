"""Telegram channels -> filter -> extract -> save. Separate from the LinkedIn pipeline on purpose.

Shares the contact saving (save_contacts) and the live-event format (post_event) with LinkedIn,
so contacts, emails and the live feed work the same way for both sources.
"""
import hashlib
import logging
import re
from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from jobscout.config import get_settings
from jobscout.db import repo
from jobscout.db.models import Platform, RunStatus, ScrapeRun, TelegramChannel
from jobscout.db.session import new_session
from jobscout.extract.ai import fallback_post_info
from jobscout.extract.contacts import find_emails, find_phones
from jobscout.extract.dates import DateRange, now
from jobscout.extract.rules import experience_ok, experience_range, location_ok, work_type_ok  # noqa: F401
from jobscout.extract.rules import labelled_field as _field
from jobscout.pipeline.scrape import MAX_LIMIT, ScrapeResult, post_event, save_contacts
from jobscout.scrapers.base import RawPost
from jobscout.scrapers.telegram import ChannelNotFound, TelegramBlocked, TgPost, fetch_page, iter_posts

log = logging.getLogger(__name__)

DEFAULT_CHANNELS = ["itreferral_jobs", "merntech"]  # measured Nov 2026: 65% / 71% of posts carry a contact
OWN_ADDRESS_REPEAT = 3  # an address in 3+ posts of one channel is the channel's own promo address

_SCAM = re.compile(
    r"(?i)\b(registration\s+fee|processing\s+fee|security\s+deposit|refundable\s+(?:fee|amount|deposit)|"
    r"pay\s+(?:rs\.?|₹|inr)\s*\d|training\s+fee|joining\s+fee)"
)


# ------------------------------------------------------------------ text helpers
def normalise_keywords(keywords: list[str]) -> list[str]:
    out: dict[str, None] = {}
    for k in keywords:
        for part in re.split(r"[,\n]", k):
            part = part.strip().lstrip("#").lower()
            if part:
                out.setdefault(part, None)
    return list(out)


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Keywords found as whole words ('react' matches 'React.js' but not 'reactive'). No keywords = all match."""
    found = []
    for k in keywords:
        if re.search(rf"(?<![\w]){re.escape(k)}(?![a-z0-9])", text, re.I):
            found.append(k)
    return found


def hiring_summary(text: str) -> str | None:
    """'C++ Developer at Quant Mutual Fund | 5+ yrs | Mumbai' from a structured job post, else the rule-based guess."""
    role = _field(text, r"role\s*/\s*title", r"role", r"job\s*title", r"title", r"position", r"designation")
    company = _field(text, r"company(?:\s*name)?", r"organi[sz]ation")
    if not role:
        return fallback_post_info(text).hiring_for
    parts = [f"{role} at {company}" if company else role]
    exp = _field(text, r"experience", r"exp")
    loc = _field(text, r"location", r"job\s*location")
    parts += [x for x in (exp, loc) if x]
    return " | ".join(parts)[:200]


def own_addresses(channel: str, posts: list[TgPost]) -> set[str]:
    """The channel's own promo/admin addresses: repeated across posts, or named after the channel."""
    counts = Counter(e for p in posts for e in set(find_emails(p.text) + p.mailto))
    core = re.sub(r"[^a-z]", "", channel)
    own = {e for e, n in counts.items() if n >= OWN_ADDRESS_REPEAT}
    if len(core) >= 5:
        own |= {e for e in counts if core in re.sub(r"[^a-z]", "", e.split("@")[0].lower())}
    return own


def contacts_in(post: TgPost, own: set[str], region: str) -> tuple[list[str], list[str]]:
    emails = [e for e in dict.fromkeys(find_emails(post.text) + [m.lower() for m in post.mailto]) if e not in own]
    return emails, find_phones(post.text, region)


def age_label(dt: datetime | None, ref: datetime | None = None) -> str | None:
    if dt is None:
        return None
    s = max(0, ((ref or now()) - dt).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{int(s // size)}{unit}"
    return "now"


def _fingerprint(text: str) -> str:
    """Same job reposted in several channels -> same fingerprint."""
    norm = re.sub(r"[^a-z0-9@.]+", " ", text.lower()).strip()[:600]
    return hashlib.sha1(norm.encode()).hexdigest()


# ------------------------------------------------------------------ channel quality
def channel_stats(channel: str, pages: int = 3) -> dict:
    """Read ~60 recent posts and measure how many carry a recruiter email or phone."""
    region = get_settings().default_phone_region
    posts, title, subs = [], None, None
    for page, post in iter_posts(channel, max_pages=pages):
        title, subs = title or page.title, subs or page.subscribers
        posts.append(post)
    if not posts:
        page = fetch_page(channel)  # raises ChannelNotFound for non-channels
        title, subs = page.title, page.subscribers
    return stats_from_posts(channel, posts, title, subs, region)


def stats_from_posts(channel: str, posts: list[TgPost], title, subs, region: str) -> dict:
    own = own_addresses(channel, posts)
    with_text = [p for p in posts if p.text.strip()]
    with_contact = [p for p in with_text if any(contacts_in(p, own, region))]
    times = sorted(p.posted_at for p in with_text if p.posted_at)
    per_day = None
    if len(times) >= 2 and (span := (times[-1] - times[0]).total_seconds() / 86400) > 0:
        per_day = f"{len(with_text) / span:.1f}"
    return {
        "title": title, "subscribers": subs, "posts_checked": len(with_text),
        "contact_pct": round(100 * len(with_contact) / len(with_text)) if with_text else 0,
        "posts_per_day": per_day, "last_post_at": times[-1] if times else None,
    }


def apply_stats(row: TelegramChannel, stats: dict) -> None:
    for k, v in stats.items():
        setattr(row, k, v)
    row.checked_at = now()


def ensure_default_channels(session, user_id: int) -> None:
    """New users start with the two channels that measured best."""
    if session.scalar(select(TelegramChannel.id).where(TelegramChannel.user_id == user_id).limit(1)):
        return
    # ON CONFLICT: two first requests at once (two tabs, React dev double-mount) must not crash.
    session.execute(
        pg_insert(TelegramChannel)
        .values([{"user_id": user_id, "name": name} for name in DEFAULT_CHANNELS])
        .on_conflict_do_nothing(constraint="uq_telegram_channels_user_name")
    )
    session.commit()


# ------------------------------------------------------------------ the run
def run_telegram_scrape(
    *, user_id: int, keywords: list[str], date_range: DateRange, limit: int,
    channel_ids: list[int] | None = None, exp_min: int | None = None, exp_max: int | None = None,
    location: str | None = None, work_types: list[str] | None = None,
    on_progress=None, on_event=None, should_stop=None,
) -> ScrapeResult:
    """Save posts from the user's Telegram channels that mention a keyword and carry an email or phone."""
    region = get_settings().default_phone_region
    keywords = normalise_keywords(keywords)
    limit = max(1, min(limit, MAX_LIMIT))
    session = new_session()
    ensure_default_channels(session, user_id)
    q = select(TelegramChannel).where(TelegramChannel.user_id == user_id, TelegramChannel.is_active.is_(True))
    if channel_ids:
        q = q.where(TelegramChannel.id.in_(channel_ids))
    channels = list(session.scalars(q.order_by(TelegramChannel.id)))
    if not channels:
        session.close()
        raise ValueError("No active Telegram channels. Add one on the Scrape page.")

    run = ScrapeRun(user_id=user_id, platform=Platform.telegram, account_ids=[],
                    hashtags=keywords or ["(any keyword)"], date_filter=date_range.label, requested_limit=limit)
    session.add(run)
    session.commit()
    result = ScrapeResult(run_id=run.id)

    def done() -> bool:
        if should_stop and should_stop():
            result.stopped = True
            return True
        return result.collected >= limit

    def skip(raw: RawPost, reason: str, notify: bool = True) -> None:
        result.skip(reason)
        if on_event and notify:
            on_event(post_event(raw, "skipped", reason))

    try:
        # 1. Read every channel back to the start of the date range (fast: plain HTML pages).
        fetched: list[tuple[TelegramChannel, str, TgPost]] = []
        own: dict[str, set[str]] = {}
        for ch in channels:
            if done():
                break
            log.info("Reading @%s…", ch.name)
            posts, title, subs = [], ch.title, ch.subscribers
            try:
                for page, post in iter_posts(ch.name, since=date_range.start, should_stop=should_stop):
                    title, subs = page.title or title, page.subscribers or subs
                    posts.append(post)
            except ChannelNotFound as e:
                log.warning("%s Skipping it.", e)
                result.failed_accounts.append("@" + ch.name)
                continue
            except TelegramBlocked as e:
                log.warning("@%s: %s", ch.name, e)
                result.failed_accounts.append("@" + ch.name)
                continue
            own[ch.name] = own_addresses(ch.name, posts)
            apply_stats(ch, stats_from_posts(ch.name, posts, title, subs, region))
            session.commit()
            in_range = [p for p in posts if p.posted_at is None or date_range.contains(p.posted_at)]
            log.info("@%s: %d posts in the date range.", ch.name, len(in_range))
            fetched += [(ch, title or ch.name, p) for p in in_range]

        # 2. Newest first across all channels; same job posted twice counts once.
        fetched.sort(key=lambda x: x[2].posted_at or now(), reverse=True)
        seen: set[str] = set()
        for ch, title, post in fetched:
            if done():
                break
            result.scanned += 1
            if on_progress:
                on_progress(result)
            raw = RawPost(external_id=f"{ch.name}/{post.id}", url=post.url, author_name=title,
                          author_profile_url=f"https://t.me/{ch.name}", text=post.text,
                          relative_time=age_label(post.posted_at), posted_at=post.posted_at,
                          search_tag="@" + ch.name)
            fp = _fingerprint(post.text)
            if fp in seen:
                skip(raw, "same job already seen in this run", notify=False)
                continue
            seen.add(fp)

            matched = match_keywords(post.text, keywords)
            if keywords and not matched:
                skip(raw, "no keyword match")
                continue
            if not experience_ok(post.text, exp_min, exp_max):
                skip(raw, "experience outside your range")
                continue
            if not location_ok(post.text, location):
                skip(raw, "location doesn't match")
                continue
            if not work_type_ok(post.text, work_types):
                skip(raw, "work type doesn't match")
                continue
            if _SCAM.search(post.text):
                skip(raw, "asks for a fee: likely a scam")
                continue
            if repo.existing_external_ids(session, user_id, Platform.telegram, [raw.external_id]):
                skip(raw, "already in database")
                continue
            emails, phones = contacts_in(post, own.get(ch.name, set()), region)
            if not emails and not phones:
                skip(raw, "no email or phone")
                continue

            info = fallback_post_info(post.text)
            hiring_for = hiring_summary(post.text)
            row = repo.insert_post(
                session, user_id=user_id, platform=Platform.telegram, external_id=raw.external_id, url=raw.url,
                author_name=title, author_profile_url=raw.author_profile_url, description=post.text,
                hiring_for=hiring_for, contact_name=info.contact_name, emails=emails, phones=phones,
                matched_hashtags=matched, posted_at=post.posted_at, run_id=run.id,
            )
            if row is None:
                skip(raw, "already in database")
                continue
            new_values = save_contacts(session, user_id, row.id, info.contact_name, emails, phones)
            session.commit()
            result.saved += 1
            counted = new_values > 0
            if counted:
                result.collected += 1
            if on_event:
                on_event(post_event(raw, "saved", post_id=row.id, hiring_for=hiring_for,
                                    contact_name=info.contact_name, emails=emails, phones=phones,
                                    hashtags=matched, counted=counted,
                                    note=None if counted else "you already have this email/phone"))
            if on_progress:
                on_progress(result)

        if result.stopped:
            result.stop_reason = "stopped by you"
        elif result.collected >= limit:
            result.stop_reason = "target reached"
        elif result.failed_accounts and len(result.failed_accounts) == len(channels):
            result.stop_reason = "no channel could be read"
        else:
            result.stop_reason = "no more matching posts in these channels for these dates"
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
