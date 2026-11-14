"""Rule-based post understanding (no API calls): is it a hiring post, what role, contact name."""
import re

from jobscout.extract.contacts import find_contact_name

_ROLE_NOUN = (
    r"(?i:Developers?|Engineers?|Architects?|Analysts?|Scientists?|Managers?|Leads?|Interns?|Designers?|"
    r"Consultants?|Testers?|Administrators?|Admins?|Specialists?|Programmers?|Trainees?|SDETs?|"
    r"Freshers?|Executives?|Officers?|Recruiters?|Associates?)"
)
# "Senior Python Backend Engineer", "Back-end Developer (Python)", "Lead Python Full Stack Developer"
_ROLE_TITLE = re.compile(
    r"((?:[A-Z][\w+#./&-]*\s+){0,5}" + _ROLE_NOUN + r")\b(\s*\([^)\n]{1,30}\))?"
)
_LABELLED = re.compile(
    r"(?im)^[^\w\n]*(?:position|role|job\s*title|designation|opening|profile)\s*[:\-–|]\s*(.{3,80})$"
)
_HIRING_LINE = re.compile(
    r"(?i)(?:hiring|looking\s+for|opening\s+for|vacancy\s+for|requirement\s+for)\s*(?:for)?\s*[:|\-–]?\s*"
    r"(?:an?\s+|experienced\s+|skilled\s+)*(.{3,80})"
)
_EXPERIENCE = re.compile(
    r"(?im)(?:^[^\w\n]*experience\s*[:\-–|]\s*(.{1,40})$)|"
    r"(\b\d{1,2}\s*(?:\+|\s*(?:-|–|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b)"
)
_LOCATION = re.compile(r"(?im)^[^\w\n]*(?:location|job\s*location|city)\s*[:\-–|]\s*(.{2,50})$")

_NOT_HIRING = re.compile(
    r"#opentowork|\bopen\s+to\s+work\b|\bi\s*(?:am|'m)\s+(?:actively\s+)?(?:looking|seeking)\s+for\b|"
    r"\bi\s*(?:am|'m)\s+(?:actively\s+)?(?:looking|seeking)\s+(?:a\s+)?(?:new\s+)?(?:job|role|opportunit)|"
    r"\bseeking\s+(?:a\s+)?(?:new\s+)?(?:job|role|opportunit)",
    re.I,
)
_HIRING = re.compile(
    r"\b(hiring|we(?:'|’)?re\s+looking|we\s+are\s+looking|opening|vacanc|join\s+(?:our|us)|apply|"
    r"position|requirement|job\s+details|job\s+description|jd\b)",
    re.I,
)


def _clean(s: str) -> str:
    s = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", s)   # emojis
    s = re.sub(r"\s+", " ", s).strip(" -–|:!.,*#")
    return s


def _first_role(text: str) -> str | None:
    for m in _ROLE_TITLE.finditer(text):
        role = _clean(m.group(1) + (m.group(2) or ""))
        words = role.split()
        # Drop leading sentence words that happen to be capitalised ("Are", "We", "Our").
        while words and words[0].lower() in {"are", "we", "our", "the", "a", "an", "join", "as", "hiring", "urgent"}:
            words.pop(0)
        if words:
            return " ".join(words)
    return None


def find_role(text: str) -> str | None:
    """Most specific role mentioned in the post."""
    for pattern in (_LABELLED, _HIRING_LINE):
        for m in pattern.finditer(text):
            role = _first_role(_clean(m.group(1).split("\n")[0]))
            if role and role[0].isupper():
                return role
    return _first_role(text)


def find_experience(text: str) -> str | None:
    m = _EXPERIENCE.search(text)
    if not m:
        return None
    return _clean(m.group(1) or m.group(2))[:30]


def find_location(text: str) -> str | None:
    m = _LOCATION.search(text)
    return _clean(m.group(1))[:40] if m else None


def hiring_summary(text: str) -> str | None:
    """e.g. 'Lead Python Full Stack Developer | 8+ Years | Hyderabad'."""
    role = find_role(text)
    if not role:
        return None
    extras = [x for x in (find_experience(text), find_location(text)) if x and x.lower() not in role.lower()]
    return " | ".join([role] + extras)


def is_hiring_post(text: str) -> bool:
    return not _NOT_HIRING.search(text) and bool(_HIRING.search(text))


def post_info(text: str) -> dict:
    return {
        "is_hiring_post": is_hiring_post(text),
        "hiring_for": hiring_summary(text),
        "contact_name": find_contact_name(text),
    }
