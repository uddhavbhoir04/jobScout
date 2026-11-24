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


# ---------------------------------------------------------------- filters: exp, loc, work type
_EXP_LINE = re.compile(r"(?im)^[^\w\n]*(?:experience|exp)\b[^\n:]*[:\-–]?\s*(.{1,60})$")
_EXP_RANGE = re.compile(r"(?i)(\d{1,2})\s*\+?\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)")
_EXP_PLUS = re.compile(r"(?i)(\d{1,2})\s*\+\s*(?:years?|yrs?)")
_EXP_ONE = re.compile(r"(?i)(\d{1,2})\s*(?:years?|yrs?)")
_FRESHER = re.compile(r"(?i)\bfreshers?\b|\b0\s*(?:-|to)\s*1\s*(?:years?|yrs?)")


def experience_range(text: str) -> tuple[int, int] | None:
    """(min, max) years the post asks for, or None if it doesn't say. Prefers an 'Experience:' line."""
    line = _EXP_LINE.search(text)
    for scope in ([line.group(1)] if line else []) + [text]:
        if m := _EXP_RANGE.search(scope):
            a, b = int(m.group(1)), int(m.group(2))
            return (min(a, b), max(a, b))
        if m := _EXP_PLUS.search(scope):
            return (int(m.group(1)), 99)
        if _FRESHER.search(scope):
            return (0, 1)
        if m := _EXP_ONE.search(scope):
            return (int(m.group(1)), int(m.group(1)))
    return None


def experience_ok(text: str, exp_min: int | None, exp_max: int | None) -> bool:
    """The post's experience must fit your range: its upper end may not go above `exp_max`
    ('2-6 yrs' or '5+ yrs' fail a max of 3) and must reach `exp_min`. Posts that don't say are kept."""
    if exp_min is None and exp_max is None:
        return True
    rng = experience_range(text)
    if rng is None:
        return True  # unknown: keep it, the user can judge
    _, hi = rng
    return hi <= (exp_max if exp_max is not None else 99) and hi >= (exp_min or 0)


def location_ok(text: str, location: str | None) -> bool:
    """The post must mention at least one of the comma/slash separated locations (whole words).
    Remote posts pass whatever their location, because a remote job isn't tied to a city."""
    terms = [t.strip().lower() for t in re.split(r"[,/|;]", location or "") if t.strip()]
    if not terms:
        return True
    text_lower = text.lower()
    if any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text_lower) for t in terms):
        return True
    return "remote" in detect_work_types(text)


_REMOTE_RE = re.compile(
    r"(?i)\b(remote|remotely|wfh|work\s+from\s+home|telecommute|telecommuting|work\s+from\s+anywhere|100%\s*remote)\b"
)
_NOT_REMOTE_RE = re.compile(r"(?i)\b(?:no|not|non)\s+remote\b")

_HYBRID_RE = re.compile(
    r"(?i)\b(hybrid|flexible\s*(?:work|working|location)|\d\s*days?\s+(?:in\s+office|wfh|from\s+home)|partially\s+remote)\b"
)

_ONSITE_RE = re.compile(
    r"(?i)\b(on[\s-]?site|in-?office|work\s+from\s+office|wfo|office[\s-]based)\b"
)
WORK_TYPES = {"remote", "hybrid", "on-site"}


def detect_work_types(text: str) -> set[str]:
    types = set()
    if _REMOTE_RE.search(text) and not _NOT_REMOTE_RE.search(text):
        types.add("remote")
    if _HYBRID_RE.search(text):
        types.add("hybrid")
    if _ONSITE_RE.search(text):
        types.add("on-site")
    return types


def work_type_ok(text: str, allowed_types: list[str] | set[str] | None) -> bool:
    """True if the post matches one of the selected work types (remote, hybrid, on-site).
    Posts that don't say how the job is worked are kept."""
    allowed = {
        "on-site" if t.strip().lower() in ("onsite", "on_site") else t.strip().lower()
        for t in (allowed_types or []) if t.strip()
    }
    if not allowed or allowed >= WORK_TYPES:
        return True
    detected = detect_work_types(text)
    return not detected or bool(detected & allowed)



# ---------------------------------------------------------------- export: title, company
_FIELD = r"(?im)^[^\w\n]*{label}\s*[:\-–]\s*(.+)$"


def labelled_field(text: str, *labels: str) -> str | None:
    """Value of the first 'Label: value' line found, trying `labels` (regexes) in order."""
    for label in labels:
        if m := re.search(_FIELD.format(label=label), text):
            return m.group(1).strip()[:80]
    return None


_CO_WORD = r"[A-Z][\w&'-]*(?:\.[A-Za-z]+)*"  # 'Zoho', 'AT&T', 'Infosys.com'; a sentence's full stop ends it
_CO_NAME = rf"({_CO_WORD}(?:[ \t]+(?:&[ \t]+)?{_CO_WORD}){{0,3}})"
_AT_COMPANY = re.compile(rf"(?:{_ROLE_NOUN}|hiring|opening|opportunity|role|position)\s+(?:at|@)\s+{_CO_NAME}")
_JOIN_COMPANY = re.compile(rf"(?i:join)\s+(?:(?i:the|our)\s+)?{_CO_NAME}\s+(?i:team|family)")
_NOT_COMPANY = {"we", "our", "us", "the", "a", "an", "this", "my", "linkedin"}


def find_title(text: str) -> str | None:
    """Job title the post is hiring for, e.g. 'Back-end Developer (Python)'."""
    role = find_role(text) or labelled_field(
        text, r"role\s*/\s*title", r"role", r"job\s*title", r"title", r"position", r"designation")
    role = _clean(role) if role else None
    return role[:120] if role else None


def find_company(text: str, author_name: str | None = None, author_url: str | None = None) -> str | None:
    """Hiring company: a 'Company:' line, '<role> at X', 'join the X team', or the LinkedIn company page
    that posted it. None when the post doesn't say."""
    if v := labelled_field(text, r"company(?:\s*name)?", r"organi[sz]ation", r"client", r"employer"):
        return _clean(v)[:80] or None
    for pattern in (_AT_COMPANY, _JOIN_COMPANY):
        for m in pattern.finditer(text):
            name = _clean(m.group(m.lastindex))
            if name and name.split()[0].lower() not in _NOT_COMPANY:
                return name[:80]
    if author_url and "/company/" in author_url and author_name:
        return author_name.strip()[:80]
    return None
