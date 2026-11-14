"""LLM helpers (any provider via LangChain): post understanding + outreach email writing.

Everything falls back to rules/templates when no model is available, so scraping and drafting never stop.
"""
import logging
from datetime import date

from pydantic import BaseModel, ValidationError

from jobscout.config import Settings
from jobscout.llm import LLM, classify_quota_error  # noqa: F401  (re-exported for callers/tests)

log = logging.getLogger(__name__)


class PostInfo(BaseModel):
    is_hiring_post: bool = True
    hiring_for: str | None = None
    contact_name: str | None = None


class EmailDraft(BaseModel):
    subject: str
    body: str


# ---------------------------------------------------------------- post analysis
POST_SYSTEM = """You analyse LinkedIn posts for a job seeker. Return ONLY a JSON object:
{"is_hiring_post": bool, "hiring_for": string|null, "contact_name": string|null}

- is_hiring_post: true only if the author/company is hiring or sharing an opening. False for people looking for jobs (#opentowork), ads, courses, or generic content.
- hiring_for: short role summary, e.g. "Python Developer (3-5 yrs, Remote, Pune)". Multiple roles separated by "; ". null if unclear.
- contact_name: full name of a person the post explicitly tells readers to contact (e.g. "DM Priya Sharma", "send CV to Rahul"), written in the post text itself. Do NOT use the author's byline name unless the text names them. null if none."""

POST_USER = """Post author: {author}
Post text:
\"\"\"{text}\"\"\""""


# ---------------------------------------------------------------- outreach email
EMAIL_SYSTEM = """You write short cold emails from a job seeker to the recruiter or hiring manager who posted a job on LinkedIn. Write as the candidate, in the first person, in plain text.

Return ONLY a JSON object: {"subject": string, "body": string}

FACTS
- Use ONLY facts found in the candidate's resume and profile. Never invent employers, job titles, years, degrees, numbers, metrics, links or skills.
- Work out the candidate's total professional experience from the dates in the resume. Today is {today}; "Present" means today. Round sensibly ("about 1 year", "around 2 years"). Internships count, but call them internships if that is all there is.
- Work out how much experience the job asks for from the post (e.g. "5+ years", "8-10 yrs", "Experience: 4+ yrs"). If the post doesn't say, treat it as not specified.

EXPERIENCE GAP (important)
- If the job asks for more experience than the candidate has, acknowledge it honestly in ONE short sentence, without apologising or underselling, and immediately follow it with the strongest relevant work they have actually done. Example of the tone (do not copy the wording): "I know the role asks for 5+ years and I have about 1 year of professional experience, but I've built and own production FastAPI + PostgreSQL services end to end."
- Then say they would be glad to be considered for this role or for a more junior opening on the same team.
- If the candidate meets the requirement, or none is stated, do not mention years of experience at all.

CONTENT
- Greeting: "Hi <first name>," when the recipient's name is known, otherwise "Hi there,".
- Open by naming the exact role from the post and that you're applying for it.
- Give 2-3 specific points that match the post's tech stack or responsibilities to real work in the resume: name the project, product or technology (e.g. "the Health Score admin platform with FastAPI, PostgreSQL and RBAC"). Prefer what the post emphasises.
- {resume_line}
- Close with one simple ask (a short call, or forwarding the profile to the right person).
- Sign off with the candidate's full name. On the next line add their phone number if it is in the resume, and their LinkedIn/GitHub as full URLs only if the URLs appear in the resume or profile. Never write the bare word "LinkedIn" or "GitHub" without a URL.
- 110-170 words. No markdown, bullet points, emojis or placeholders like [Company]. Do not repeat the job post back. Warm, confident, professional.
- Subject: under 70 characters, specific, e.g. "Application: Python Backend Developer - <candidate name>"."""

EMAIL_USER = """RECIPIENT NAME: {name}
ROLE (as extracted from the post): {role}

JOB POST:
\"\"\"{post}\"\"\"

CANDIDATE NAME: {sender}

CANDIDATE PROFILE (written by the candidate):
\"\"\"{profile}\"\"\"

CANDIDATE RESUME (text):
\"\"\"{resume}\"\"\""""


class AI:
    """Post analysis + email writing on top of the configured LangChain model list."""

    def __init__(self, settings: Settings | None = None):
        self.llm = LLM(settings)

    @property
    def available(self) -> bool:
        return self.llm.available

    @property
    def _disabled_reason(self) -> str | None:
        return self.llm._disabled_reason

    def _ask(self, system: str, user: str, model: type[BaseModel]) -> BaseModel | None:
        data = self.llm.ask_json(system, user)
        if data is None:
            return None
        try:
            return model.model_validate(data)
        except ValidationError as e:
            log.warning("Model returned JSON in the wrong shape: %s", e)
            return None

    def analyse_post(self, text: str, author: str | None) -> PostInfo:
        info = self._ask(POST_SYSTEM, POST_USER.format(author=author or "unknown", text=text[:6000]), PostInfo)
        return info if info is not None else fallback_post_info(text)

    def write_email(self, *, name: str | None, role: str | None, post: str, sender: str, profile: str,
                    resume: str = "", has_resume: bool = False, today: date | None = None) -> EmailDraft | None:
        system = EMAIL_SYSTEM.replace("{today}", (today or date.today()).strftime("%d %B %Y")).replace(
            "{resume_line}",
            "Say that the resume is attached to this email." if has_resume
            else "Do not mention an attachment (no resume is attached).",
        )
        user = EMAIL_USER.format(
            name=name or "unknown", role=role or "see the job post", post=post[:4000], sender=sender or "the candidate",
            profile=profile[:3000] or "(not provided)", resume=resume[:8000] or "(not provided)",
        )
        draft = self._ask(system, user, EmailDraft)
        if draft and (not draft.subject.strip() or len(draft.body.split()) < 30):
            log.warning("Model returned an empty or too-short email; using the template instead.")
            return None
        return draft


Gemini = AI  # backwards-compatible name used across the codebase


def fallback_post_info(text: str) -> PostInfo:
    from jobscout.extract.rules import post_info

    return PostInfo(**post_info(text))
