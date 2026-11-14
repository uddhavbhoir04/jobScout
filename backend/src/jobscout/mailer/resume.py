"""Pull plain text out of an uploaded resume so the AI can write from the candidate's real experience."""
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)
MAX_CHARS = 12000


def _pdf_links(reader) -> list[str]:
    found: dict[str, None] = {}
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            try:
                action = annot.get_object().get("/A") or {}
                uri = action.get("/URI")
            except Exception:
                continue
            if uri and str(uri).startswith(("http://", "https://")) and "mailto:" not in str(uri):
                found.setdefault(str(uri).strip(), None)
    return list(found)


def extract_text(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    try:
        suffix = p.suffix.lower()
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(p))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            links = _pdf_links(reader)
            if links:  # "LinkedIn" / "GitHub" are often clickable words whose URL isn't in the text
                text += "\nLinks in resume: " + " ".join(links)
        elif suffix == ".docx":
            import docx

            d = docx.Document(str(p))
            parts = [para.text for para in d.paragraphs]
            for table in d.tables:
                for row in table.rows:
                    parts.append(" | ".join(cell.text for cell in row.cells))
            text = "\n".join(parts)
        else:  # .doc (old Word) can't be read without extra tools
            return ""
    except Exception as e:  # corrupt / encrypted files: the email still works from "About you"
        log.warning("Could not read resume text from %s: %s", p.name, e)
        return ""
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:MAX_CHARS]
