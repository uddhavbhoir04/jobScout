"""Public Telegram channels, read through their web preview: https://t.me/s/<channel>.

No Telegram account, API key or browser: each page is plain HTML with ~20 posts, and older posts are
loaded with ?before=<post id>. Every selector lives in the regexes below, so a markup change means
editing this file only.
"""
import html
import logging
import random
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger(__name__)

BASE = "https://t.me"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36")
PAGE_DELAY = (1.0, 2.5)        # seconds between page requests: be polite
MAX_PAGES_PER_CHANNEL = 40     # ~800 posts: plenty for "last 30 days" on busy channels

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{3,31}$")
_MSG_SPLIT = re.compile(r'(?=<div class="tgme_widget_message_wrap)')
_POST_ID = re.compile(r'data-post="[^"/]+/(\d+)"')
_TIME = re.compile(r'<time[^>]*datetime="([^"]+)"')
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_MAILTO = re.compile(r'href="mailto:([^"?]+)')
_SUBS = re.compile(r'<div class="tgme_header_counter">([^<]+)</div>')
_TITLE = re.compile(r'<div class="tgme_channel_info_header_title"><span[^>]*>(.*?)</span>', re.S)


class ChannelNotFound(ValueError):
    """Not a public channel (private, renamed, a user/group, or no web preview)."""


class TelegramBlocked(RuntimeError):
    """t.me refused or rate-limited us."""


@dataclass
class TgPost:
    channel: str
    id: int
    posted_at: datetime | None
    text: str
    mailto: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"{BASE}/{self.channel}/{self.id}"


@dataclass
class ChannelPage:
    title: str | None
    subscribers: str | None
    posts: list[TgPost]


def normalise_channel(value: str) -> str:
    """'@ITReferral_Jobs', 't.me/s/itreferral_jobs', 'https://t.me/itreferral_jobs/123' -> 'itreferral_jobs'."""
    v = value.strip()
    v = re.sub(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(?:s/)?", "", v, flags=re.I)
    v = v.lstrip("@").split("/")[0].split("?")[0].lower()
    if not _NAME_RE.match(v):
        raise ChannelNotFound(f"“{value}” is not a valid public channel name.")
    return v


def _plain(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", t).strip()


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise TelegramBlocked(f"t.me answered {e.code}; try again later.") from e
        raise


def fetch_page(channel: str, before: int | None = None) -> ChannelPage:
    body = _get(f"{BASE}/s/{channel}" + (f"?before={before}" if before else ""))
    if "tgme_channel_info" not in body and "tgme_widget_message_wrap" not in body:
        raise ChannelNotFound(f"@{channel} has no public web preview (private, renamed, or not a channel).")
    title = _TITLE.search(body)
    subs = _SUBS.search(body)
    posts: list[TgPost] = []
    for block in _MSG_SPLIT.split(body)[1:]:
        pid, txt = _POST_ID.search(block), _TEXT.search(block)
        if not pid or not txt:
            continue  # media-only post or service message
        tm = _TIME.search(block)
        posts.append(TgPost(
            channel=channel, id=int(pid.group(1)),
            posted_at=datetime.fromisoformat(tm.group(1)) if tm else None,
            text=_plain(txt.group(1)),
            mailto=[html.unescape(m) for m in _MAILTO.findall(block)],
        ))
    return ChannelPage(title=_plain(title.group(1)) if title else None,
                       subscribers=subs.group(1).strip() if subs else None, posts=posts)


def iter_posts(channel: str, since: datetime | None = None, max_pages: int = MAX_PAGES_PER_CHANNEL,
               should_stop=None) -> Iterator[tuple[ChannelPage, TgPost]]:
    """Newest first, until posts are older than `since` (or pages run out)."""
    before = None
    for page_no in range(max_pages):
        if should_stop and should_stop():
            return
        if page_no:
            time.sleep(random.uniform(*PAGE_DELAY))
        page = fetch_page(channel, before)
        if not page.posts:
            return
        for post in sorted(page.posts, key=lambda p: p.id, reverse=True):
            yield page, post
        oldest = min(page.posts, key=lambda p: p.id)
        if since and oldest.posted_at and oldest.posted_at < since:
            return
        if before is not None and oldest.id >= before:
            return  # no progress: end of channel
        before = oldest.id
