"""Relative-time parsing ("5h", "2d") and date filter presets."""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

PRESETS = ("today", "yesterday", "day-before-yesterday", "last-3d", "last-7d", "last-30d")

_REL_RE = re.compile(r"^\s*(\d+)\s*(mo|yr|y|w|d|h|m|s)\b", re.I)
_UNIT = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
    "mo": timedelta(days=30),
    "y": timedelta(days=365),
    "yr": timedelta(days=365),
}


def now() -> datetime:
    return datetime.now().astimezone()


def parse_relative(text: str, ref: datetime | None = None) -> datetime | None:
    """Turn LinkedIn's '3h • Edited •' / '1d' / '2w' / '3mo' into an approximate datetime."""
    if not text:
        return None
    m = _REL_RE.match(text)
    if not m:
        if text.strip().lower().startswith("now"):
            return ref or now()
        return None
    return (ref or now()) - int(m.group(1)) * _UNIT[m.group(2).lower()]


def relative_bounds(text: str, ref: datetime | None = None) -> tuple[datetime, datetime] | None:
    """Possible posting window for a relative time. '1d' means 24-48h ago, '5h' 5-6h ago."""
    if not text:
        return None
    m = _REL_RE.match(text)
    if not m:
        return None
    ref = ref or now()
    n, unit = int(m.group(1)), _UNIT[m.group(2).lower()]
    return ref - (n + 1) * unit, ref - n * unit


@dataclass(frozen=True)
class DateRange:
    label: str
    start: datetime
    end: datetime

    def contains(self, dt: datetime) -> bool:
        return self.start <= dt <= self.end

    def overlaps(self, earliest: datetime, latest: datetime) -> bool:
        return earliest <= self.end and latest > self.start

    def linkedin_params(self, ref: datetime | None = None) -> list[str | None]:
        """LinkedIn 'datePosted' values to try, narrowest first, that still cover this range.
        Wider ones are fallbacks for when LinkedIn returns nothing for the narrow filter;
        exact date filtering happens afterwards on each post's own timestamp."""
        # Slack: "last 24 hours" starts exactly 24h before the run began, so a few seconds (or a long
        # run) later it is just over 24h old. Without slack every "last 24 hours" search silently
        # became "past week". At worst we miss posts from the run's first hour, which is acceptable.
        age = (ref or now()) - self.start - timedelta(hours=1)
        options = ["past-24h", "past-week", "past-month"]
        if age <= timedelta(hours=24):
            start = 0
        elif age <= timedelta(days=7):
            start = 1
        elif age <= timedelta(days=30):
            start = 2
        else:
            return [None]
        return options[start:] + [None]


def _midnight(d: date, tz) -> datetime:
    return datetime.combine(d, time.min, tzinfo=tz)


def resolve(preset: str | None = None, date_from: date | None = None,
            date_to: date | None = None, ref: datetime | None = None) -> DateRange:
    ref = ref or now()
    tz = ref.tzinfo
    today0 = _midnight(ref.date(), tz)
    if date_from or date_to:
        start = _midnight(date_from, tz) if date_from else today0 - timedelta(days=30)
        end = _midnight(date_to, tz) + timedelta(days=1) - timedelta(microseconds=1) if date_to else ref
        return DateRange(f"{start.date()}..{end.date()}", start, end)

    preset = (preset or "today").lower()
    one = timedelta(days=1)
    eps = timedelta(microseconds=1)
    if preset == "today":
        # Rolling 24 hours (LinkedIn's own "Past 24 hours"). A calendar day would be almost empty
        # just after midnight and skip every post as "outside date range".
        return DateRange(preset, ref - one, ref)
    if preset == "yesterday":
        return DateRange(preset, today0 - one, today0 - eps)
    if preset == "day-before-yesterday":
        return DateRange(preset, today0 - 2 * one, today0 - one - eps)
    m = re.fullmatch(r"last-(\d+)d", preset)
    if m:
        return DateRange(preset, ref - int(m.group(1)) * one, ref)
    raise ValueError(f"Unknown date filter {preset!r}. Use one of {', '.join(PRESETS)} or --from/--to.")
