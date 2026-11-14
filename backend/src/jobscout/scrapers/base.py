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
