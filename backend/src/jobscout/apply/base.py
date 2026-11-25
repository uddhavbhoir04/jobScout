"""Types shared by the site appliers and the apply pipeline."""
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from jobscout.db.models import ApplyStatus, Platform
from jobscout.extract.dates import DateRange
from jobscout.scrapers.base import JobListing


@dataclass
class Question:
    """One form field as the site shows it."""
    label: str
    kind: str                      # text | number | textarea | select | radio | checkbox | file
    options: list[str] = field(default_factory=list)
    required: bool = False
    value: str = ""                # what's already filled in (sites prefill email, phone...)
    key: str = ""                  # how the form module finds the field again


@dataclass
class QA:
    """A question we answered (or couldn't), for the live feed and the applications table."""
    q: str
    answer: str | None
    source: str                    # saved | learned | ai | prefilled | none

    def as_dict(self) -> dict:
        return {"q": self.q, "answer": self.answer, "source": self.source}


@dataclass
class ApplyOutcome:
    status: ApplyStatus
    reason: str | None = None
    questions: list[QA] = field(default_factory=list)
    screenshot: str | None = None  # dry run: picture of the final step
    filtered: bool = False         # skipped by the filters on the full description: not recorded


class NeedsYou(Exception):
    """A required question we couldn't answer. The message names it."""

    def __init__(self, message: str, questions: list[QA] | None = None):
        super().__init__(message)
        self.questions = questions or []


# Called by an applier once it has the job's full description, before it starts the form:
# returns a reason to skip the job (filters), or None to go ahead.
Precheck = Callable[[JobListing], str | None]


class Applier(Protocol):
    platform: Platform

    def ensure_logged_in(self, email: str, password: str, allow_manual: bool) -> bool: ...

    def search(self, keyword: str, location: str | None, date_range: DateRange,
               work_types: list[str]) -> Iterator[JobListing]: ...

    def apply(self, job: JobListing, answerer, dry_run: bool, precheck: Precheck) -> ApplyOutcome: ...
