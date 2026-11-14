"""The email prompt: real resume facts, honest experience gap, attachment line."""
from datetime import date

from jobscout.extract.ai import AI


def test_prompt_contains_resume_post_and_gap_rules(monkeypatch):
    captured = {}

    def fake_ask_json(system, user):
        captured["system"], captured["user"] = system, user
        return {"subject": "Application: Python Backend Developer - Alex Morgan",
                "body": " ".join(["word"] * 120)}

    ai = AI()
    monkeypatch.setattr(ai.llm, "ask_json", fake_ask_json)
    d = ai.write_email(name="Garima Sharma", role="Python Backend Developer | 4+ yrs", post="Need 4+ yrs FastAPI",
                       sender="Alex Morgan", profile="AI & full-stack dev",
                       resume="One Health Assist 02/2026 - Present", has_resume=True, today=date(2026, 11, 14))
    assert d is not None and d.subject.startswith("Application")
    sys_, user = captured["system"], captured["user"]
    assert "14 November 2026" in sys_                      # experience computed against today's date
    assert "acknowledge it honestly in ONE short sentence" in sys_
    assert "more junior opening" in sys_
    assert "Never invent" in sys_
    assert "resume is attached" in sys_
    assert "One Health Assist 02/2026 - Present" in user and "Need 4+ yrs FastAPI" in user


def test_no_attachment_line_without_resume(monkeypatch):
    captured = {}
    ai = AI()
    monkeypatch.setattr(ai.llm, "ask_json", lambda s, u: captured.update(system=s) or None)
    assert ai.write_email(name=None, role=None, post="p", sender="X", profile="", has_resume=False) is None
    assert "Do not mention an attachment" in captured["system"]


def test_too_short_reply_is_rejected(monkeypatch):
    ai = AI()
    monkeypatch.setattr(ai.llm, "ask_json", lambda s, u: {"subject": "Hi", "body": "Too short."})
    assert ai.write_email(name=None, role=None, post="p", sender="X", profile="") is None


def test_resume_text_extraction(tmp_path):
    import docx
    from pypdf import PdfWriter

    from jobscout.mailer.resume import extract_text

    d = docx.Document()
    d.add_paragraph("Software Developer | One Health Assist | 02/02/2026 - Present")
    d.save(tmp_path / "cv.docx")
    assert "One Health Assist" in extract_text(tmp_path / "cv.docx")
    w = PdfWriter()
    w.add_blank_page(100, 100)
    with open(tmp_path / "blank.pdf", "wb") as f:
        w.write(f)
    assert extract_text(tmp_path / "blank.pdf") == ""      # scanned/blank PDFs give no text, no crash
    assert extract_text(tmp_path / "missing.pdf") == ""
