import html
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from jobscout.db.models import Platform
from jobscout.extract.dates import DateRange


class LoginRequired(RuntimeError):
    """The site asked for login / checkpoint in the middle of scraping."""


@dataclass
class RawPost:
    external_id: str
    url: str | None
    author_name: str | None
    author_profile_url: str | None
    text: str
    relative_time: str | None
    posted_at: datetime | None
    search_tag: str


class Scraper(Protocol):
    platform: Platform

    def ensure_logged_in(self, email: str, password: str, allow_manual: bool) -> bool: ...

    def search(self, tag: str, date_range: DateRange) -> Iterator[RawPost]: ...


# ---------------------------------------------------------------- job boards (Naukri, Indeed)
class BoardBlocked(RuntimeError):
    """The job board refused the browser (bot check, sign-in wall). Message is shown to the user."""


@dataclass
class JobListing:
    """One job from a job board's search results. `description` starts as the search snippet
    and is replaced by the full text from the job page (fetch_description)."""
    external_id: str
    url: str | None
    title: str
    company: str | None
    location: str | None = None
    experience: str | None = None      # as the site shows it, e.g. "3-6 Yrs"
    salary: str | None = None
    work_mode: str | None = None       # "remote" | "hybrid" | "on-site" | None (not stated)
    posted_at: datetime | None = None
    relative_time: str | None = None   # "Today", "1 Day Ago"... for the live feed
    description: str = ""
    search_tag: str = ""
    easy_apply: bool | None = None     # can be applied to on the site itself (None = unknown)


class JobBoardScraper(Protocol):
    platform: Platform

    def search(self, keyword: str, location: str | None, date_range: DateRange,
               work_types: list[str]) -> Iterator[JobListing]: ...

    def fetch_description(self, listing: JobListing) -> str: ...


_TAG_BREAKS = re.compile(r"(?i)<\s*(?:br|/p|/ul|/ol|/div|/h\d|/tr)\s*/?>")
_LI = re.compile(r"(?i)<\s*li[^>]*>")
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(html_text: str | None) -> str:
    """Job descriptions come as HTML: keep line breaks and bullets, drop the tags."""
    if not html_text:
        return ""
    s = _TAG_BREAKS.sub("\n", html_text)
    s = _LI.sub("\n• ", s)
    s = html.unescape(_TAGS.sub("", s)).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()
