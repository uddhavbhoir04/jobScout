"""Answers to application screening questions.

In order: the user's saved answers sheet (rules on the question text), answers learned on earlier
applications, then (paid plan) the AI, from the resume. Anything the AI isn't sure of returns None:
the job is left for the user ("needs you") rather than answered with a guess.
"""
import difflib
import json
import logging
import re

from jobscout.apply.base import QA, Question

log = logging.getLogger(__name__)

YES, NO = "Yes", "No"

# answers sheet keys (see web/apply_api.py AnswersIn)
SHEET_KEYS = ("notice_period_days", "current_ctc", "expected_ctc", "total_experience_years", "skills_experience",
              "relocate", "authorized_to_work", "needs_sponsorship", "phone", "city", "linkedin_url",
              "portfolio_url", "custom")


def normalize(text: str) -> str:
    """'Years of experience with Python? *' -> 'years of experience with python'"""
    t = re.sub(r"[*:?]+", " ", (text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _num(text) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", str(text or "").replace(",", ""))
    return float(m.group(0)) if m else None


def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def _yes_no(v) -> str | None:
    if isinstance(v, bool):
        return YES if v else NO
    if isinstance(v, str) and v.strip().lower() in ("yes", "y", "true"):
        return YES
    if isinstance(v, str) and v.strip().lower() in ("no", "n", "false"):
        return NO
    return None


def _option_range(option: str) -> tuple[float, float] | None:
    """'0-15 days' -> (0, 15), '3+ years' -> (3, inf), 'Immediate' -> (0, 0), '1 month' -> (30, 30)."""
    low = option.lower()
    if re.search(r"\bimmediate", low):
        return (0, 0)
    mult = 30 if re.search(r"\bmonths?\b", low) else 1
    nums = [float(n) * mult for n in re.findall(r"\d+(?:\.\d+)?", low.replace(",", ""))]
    if not nums:
        return None
    if len(nums) >= 2:
        return (min(nums[:2]), max(nums[:2]))
    if "+" in low or "more" in low or "above" in low:
        return (nums[0], float("inf"))
    if "less" in low or "below" in low or "under" in low or "<" in low:
        return (0, nums[0])
    return (nums[0], nums[0])


def match_option(answer: str | None, options: list[str]) -> str | None:
    """The option that means `answer`: exact, yes/no, containing, numeric range, then close spelling."""
    if answer is None or not options:
        return None
    a = answer.strip().lower()
    real = [o for o in options if normalize(o) not in ("", "select an option", "select", "choose", "please select")]
    for o in real:
        if o.strip().lower() == a:
            return o
    yn = _yes_no(answer)
    if yn:
        for o in real:
            if o.strip().lower().startswith(yn.lower()):
                return o
    if re.search(r"[a-z]", a):  # text answers only: "4" must not match "14 days"
        for o in real:
            if a in o.lower() or o.strip().lower() in a:
                return o
    n = _num(answer)
    if n is not None:
        best, best_d = None, None
        for o in real:
            r = _option_range(o)
            if r is None:
                continue
            d = 0 if r[0] <= n <= r[1] else min(abs(n - r[0]), abs(n - r[1]))
            if best_d is None or d < best_d:
                best, best_d = o, d
        if best is not None:
            return best
    close = difflib.get_close_matches(a, [o.lower() for o in real], n=1, cutoff=0.8)
    if close:
        return next(o for o in real if o.lower() == close[0])
    return None


def valid(q: Question, answer: str | None) -> str | None:
    """The answer in the form the field takes, or None if it doesn't fit."""
    if answer is None or str(answer).strip() == "":
        return None
    answer = str(answer).strip()
    if q.kind in ("select", "radio") or (q.kind == "checkbox" and q.options):
        return match_option(answer, q.options)
    if q.kind == "checkbox":
        return _yes_no(answer)
    if q.kind == "number":
        n = _num(answer)
        return _fmt_num(n) if n is not None else None
    return answer


# ---------------------------------------------------------------- saved-answer rules
_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"notice"), "notice"),
    (re.compile(r"(expected|desired|asking).*(ctc|salary|compensation|package|pay)|(ctc|salary).*expect"), "expected_ctc"),
    (re.compile(r"(current|present|last|existing).*(ctc|salary|compensation|package)|^ctc$"), "current_ctc"),
    (re.compile(r"sponsor"), "needs_sponsorship"),
    (re.compile(r"authori[sz]ed|legally (eligible|allowed|permitted)|right to work|work permit"), "authorized_to_work"),
    (re.compile(r"relocat"), "relocate"),
    (re.compile(r"linkedin"), "linkedin_url"),
    (re.compile(r"portfolio|website|github|personal url"), "portfolio_url"),
    (re.compile(r"(mobile|phone|contact) (number|no)|^phone$|^mobile$"), "phone"),
    (re.compile(r"(current|present) (city|location)|where are you (based|located)|^city$|^location$"), "city"),
    (re.compile(r"\b(i )?(agree|acknowledge|consent|confirm that)\b"), "agree"),
]
_EXPERIENCE = re.compile(r"(how many|number of)?\s*(years?|yrs)\b.*\bexperience|experience.*\b(years?|yrs)\b|^(total |overall |relevant )?experience$")
_TOTAL_HINT = re.compile(r"\b(total|overall|professional|work|relevant|it|industry)\b")


def _from_sheet(q: Question, sheet: dict) -> str | None:
    label = normalize(q.label)
    for c in sheet.get("custom") or []:
        cq = normalize(c.get("q", ""))
        if cq and (cq == label or difflib.SequenceMatcher(None, cq, label).ratio() >= 0.88):
            return c.get("a")
    if _EXPERIENCE.search(label):
        skills = sheet.get("skills_experience") or {}
        for skill, years in sorted(skills.items(), key=lambda kv: -len(kv[0])):  # "react native" before "react"
            if re.search(rf"(?<![a-z0-9]){re.escape(skill.lower())}(?![a-z0-9])", label):
                return _fmt_num(float(years)) if _num(years) is not None else None
        mentions_other = re.search(r"\b(with|in|using|of working (with|on)|on)\s+[a-z]", label.split("experience", 1)[-1])
        if sheet.get("total_experience_years") is not None and (not mentions_other or _TOTAL_HINT.search(label)):
            return _fmt_num(float(sheet["total_experience_years"]))
        return None
    for rx, key in _RULES:
        if not rx.search(label):
            continue
        if key == "notice":
            days = sheet.get("notice_period_days")
            if days is None:
                return None
            if q.kind in ("select", "radio"):
                return "Immediate" if int(days) == 0 and match_option("Immediate", q.options) else _fmt_num(days)
            return _fmt_num(days)  # "0" / "30": numeric fields reject "30 days"; the label says the unit
        if key == "agree":
            return YES
        v = sheet.get(key)
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return _yes_no(v)
        if key in ("current_ctc", "expected_ctc") and q.kind == "number":
            return _fmt_num(_num(v)) if _num(v) is not None else None
        return str(v)
    return None


# ---------------------------------------------------------------- facts read from the CV
_URL = re.compile(r"https?://[^\s)>\]]+", re.I)


def national_phone(phone: str) -> str:
    """+919876543210 -> 9876543210: forms have a separate country-code box."""
    digits = re.sub(r"\D", "", phone or "")
    if phone.startswith("+91") and len(digits) == 12:
        return digits[2:]
    return digits[-10:] if len(digits) > 10 and phone.startswith("+") else (digits or phone)


def cv_facts(resume_text: str, region: str = "IN") -> dict:
    """Contact details straight from the CV text (no AI): phone, LinkedIn and portfolio URLs."""
    from jobscout.extract.contacts import find_phones

    text = resume_text or ""
    facts: dict = {}
    if phones := find_phones(text, region):
        facts["phone"] = national_phone(phones[0])
    urls = [u.rstrip(".,;") for u in _URL.findall(text)]
    if li := next((u for u in urls if "linkedin.com/in/" in u.lower()), None):
        facts["linkedin_url"] = li
    if pf := next((u for u in urls if "github.com/" in u.lower()), None) or next(
            (u for u in urls if "linkedin.com" not in u.lower()), None):
        facts["portfolio_url"] = pf
    return facts


# ---------------------------------------------------------------- AI
_SYSTEM = """You fill in job application forms for a candidate, using ONLY facts from their resume and
answers sheet. Reply with JSON: {"answer": "...", "confident": true|false}.
- For a question with options, "answer" must be exactly one of the options.
- For a number question, "answer" is just the number.
- Keep text answers short and factual (one or two sentences at most).
- If the resume and sheet don't tell you, or the honest answer would hurt the candidate in a way
  they'd want to decide themselves, set "confident": false. Never invent facts."""


class Answerer:
    def __init__(self, sheet: dict | None, learned: dict | None, resume_text: str = "", llm=None,
                 resume_path: str | None = None):
        filled = {k: v for k, v in (sheet or {}).items() if v not in (None, "", [], {})}
        self.sheet = {**cv_facts(resume_text), **filled}   # the sheet wins over what the CV says
        if self.sheet.get("phone"):
            self.sheet["phone"] = national_phone(str(self.sheet["phone"]))
        self.resume_path = resume_path      # uploaded CV, for file-upload fields
        self.learned = dict(learned or {})
        self.resume_text = (resume_text or "")[:8000]
        self.llm = llm                      # None = no AI (free plan / not configured)
        self.new_learned: dict[str, str] = {}

    def answer(self, q: Question) -> QA:
        if (q.value or "").strip() and q.kind not in ("radio", "checkbox"):
            return QA(q.label, q.value, "prefilled")
        if (ans := valid(q, _from_sheet(q, self.sheet))) is not None:
            return QA(q.label, ans, "saved")
        key = normalize(q.label)
        if key in self.learned and (ans := valid(q, self.learned[key])) is not None:
            return QA(q.label, ans, "learned")
        if self.llm is not None and q.kind != "file":
            if (ans := self._ask_ai(q)) is not None:
                self.learned[key] = ans
                self.new_learned[key] = ans
                return QA(q.label, ans, "ai")
        return QA(q.label, None, "none")

    def retry(self, q: Question, rejected: str | None, message: str) -> str | None:
        """The site rejected `rejected` with `message` ("Enter a whole number"...): ask the AI again."""
        if self.llm is None:
            return None
        hint = Question(f"{q.label} (the form rejected “{rejected}”: {message})", q.kind, q.options, q.required)
        ans = self._ask_ai(hint)
        if ans is not None:
            key = normalize(q.label)
            self.learned[key] = self.new_learned[key] = ans
        return ans

    def _ask_ai(self, q: Question) -> str | None:
        user = json.dumps({
            "question": q.label, "type": q.kind, "options": q.options or None,
            "answers_sheet": {k: v for k, v in self.sheet.items() if v not in (None, "", [], {})},
            "resume": self.resume_text,
        }, ensure_ascii=False)
        reply = self.llm.ask_json(_SYSTEM, user)
        if not isinstance(reply, dict) or not reply.get("confident"):
            return None
        return valid(q, reply.get("answer"))
