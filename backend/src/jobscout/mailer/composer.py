"""Build the subject/body for an outreach email (Gemini first, Jinja2 template fallback)."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from jobscout.db.models import Contact, Post
from jobscout.extract.ai import EmailDraft, Gemini

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
OPT_OUT = "P.S. If you'd rather not receive emails like this, just reply and I won't contact you again."

_env = Environment(loader=FileSystemLoader(TEMPLATES), keep_trailing_newline=False, autoescape=False)


def _first_name(name: str | None) -> str | None:
    return name.split()[0] if name else None


def render_template(contact: Contact, post: Post | None, sender: str, profile: str,
                    has_resume: bool = False) -> EmailDraft:
    profile_line = next((ln.strip() for ln in profile.splitlines() if ln.strip() and not ln.startswith("#")), "")
    text = _env.get_template("outreach.txt.j2").render(
        role=post.hiring_for if post else None,
        first_name=_first_name(contact.name),
        profile_line=profile_line,
        sender=sender,
        has_resume=has_resume,
    )
    subject, _, body = text.partition("\n")
    return EmailDraft(subject=subject.strip(), body=body.strip())


def compose(ai: Gemini | None, contact: Contact, post: Post | None, *, sender: str, profile: str,
            has_resume: bool, resume_text: str = "") -> tuple[EmailDraft, str]:
    """Returns (draft, source) where source is 'ai' or 'template'."""
    draft, source = None, "template"
    if ai is not None and post is not None and ai.available:
        draft = ai.write_email(name=contact.name, role=post.hiring_for, post=post.description,
                               sender=sender, profile=profile, resume=resume_text, has_resume=has_resume)
        source = "ai" if draft else "template"
    if draft is None:
        draft = render_template(contact, post, sender, profile, has_resume)
    if OPT_OUT not in draft.body:
        draft.body = f"{draft.body.rstrip()}\n\n{OPT_OUT}"
    return draft, source
