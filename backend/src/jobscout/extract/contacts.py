"""Regex-based contact extraction: emails, phones, contact names."""
import re

import phonenumbers

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}")
_NOT_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")

# "name [at] company [dot] com", "name (at) company (dot) com", "name at company dot com"
_AT_RE = re.compile(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*|\s+at\s+(?=[A-Za-z0-9\-]+\s*(?:[\[\(\{]\s*dot\s*[\]\)\}]|\s+dot\s+))", re.I)
_DOT_RE = re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*|(?<=[A-Za-z0-9])\s+dot\s+(?=[A-Za-z]{2,})", re.I)

# Capitalised words, but not the local part of an email ("Careers.Team@acme.io").
_NAME = r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b(?![.\w+\-]*@)"
_NAME_PATTERNS = [
    re.compile(
        r"(?i:reach\s+out\s+to|contact|connect\s+with|dm|message|ping|talk\s+to|speak\s+to|"
        r"get\s+in\s+touch\s+with|share\s+(?:your\s+)?(?:cv|resume|profile)s?\s+(?:with|to)|"
        r"send\s+(?:your\s+)?(?:cv|resume|profile)s?\s+to|refer\s+to)\s+"
        + _NAME
    ),
    re.compile(r"(?i:contact\s+person|point\s+of\s+contact|poc|recruiter|hr|spoc)\s*[:\-]\s*" + _NAME),
]
_NAME_STOPWORDS = {
    "me", "us", "our", "the", "my", "your", "hr", "team", "linkedin", "here", "below", "them",
    "him", "her", "this", "email", "mail", "whatsapp", "inbox", "dm", "comments", "comment",
    "careers", "career", "jobs", "hiring", "recruitment", "talent",
}


def deobfuscate(text: str) -> str:
    return _DOT_RE.sub(".", _AT_RE.sub("@", text))


def find_emails(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in _EMAIL_RE.finditer(deobfuscate(text)):
        email = m.group(0).strip(".").lower()
        if email.endswith(_NOT_EMAIL_SUFFIXES):
            continue
        seen.setdefault(email, None)
    return list(seen)


def find_phones(text: str, region: str = "US") -> list[str]:
    """Return valid phone numbers formatted as E.164 (e.g. +14155552671)."""
    seen: dict[str, None] = {}
    for match in phonenumbers.PhoneNumberMatcher(text, region.upper(), leniency=phonenumbers.Leniency.VALID):
        seen.setdefault(phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164), None)
    return list(seen)


def normalize_phone(raw: str, region: str = "US") -> str | None:
    try:
        num = phonenumbers.parse(raw, region.upper())
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(num):
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def find_contact_name(text: str) -> str | None:
    """Best-effort: a person's name the post tells you to contact ("DM Priya Sharma")."""
    for pattern in _NAME_PATTERNS:
        for m in pattern.finditer(text):
            name = m.group(1).strip()
            if name.split()[0].lower() not in _NAME_STOPWORDS:
                return name
    return None


_TITLE_PREFIX = re.compile(r"^(?:(?:hr|mr|mrs|ms|miss|dr|er|ca)\.?\s+)+", re.I)


def clean_person_name(name: str | None) -> str | None:
    """'HR Srinivasan - Premium MNC Job Consultancy INDIA l USA' -> 'Srinivasan'."""
    if not name:
        return None
    name = re.split(r"\s+[-–|•,]\s+|\s*\||\s*\(", name, maxsplit=1)[0]
    name = _TITLE_PREFIX.sub("", name.strip())
    name = re.sub(r"[^\w\s.'-]", "", name).strip()
    return name or None


def qualifies(emails: list[str], contact_name: str | None) -> bool:
    """Keep rule: the post must contain an email, or a contact name written in the text."""
    return bool(emails) or bool(contact_name and contact_name.strip())


def hashtags_in(text: str, wanted: list[str]) -> list[str]:
    """Which of the wanted hashtags appear in the text (case-insensitive, whole tag)."""
    found = []
    for tag in wanted:
        body = tag.lstrip("#")
        if re.search(rf"#{re.escape(body)}(?![\w])", text, re.I):
            found.append("#" + body.lower())
    return found
