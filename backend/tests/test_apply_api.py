"""Auto-apply API: answers sheet, start checks, applications are per user."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(db, monkeypatch):
    from cryptography.fernet import Fernet

    from jobscout.config import get_settings
    from jobscout.web.app import app

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())

    def make(email):
        c = TestClient(app)
        assert c.post("/api/auth/register", json={"email": email, "password": "password123"}).status_code == 201
        return c
    return make


def test_settings_round_trip(client):
    c = client("a@x.io")
    s = c.get("/api/apply/settings").json()
    assert s["daily_cap"] == 25 and s["answers"] == {} and s["applied_today"] == {"linkedin": 0, "naukri": 0, "indeed": 0}
    body = {"answers": {"notice_period_days": 30, "expected_ctc": " 18 LPA ", "skills_experience": {" Python ": 4},
                        "relocate": True, "custom": [{"q": "Why us?", "a": "Product."}]},
            "daily_cap": 10, "learned": {"highest education": "Bachelor's", "empty": " "}}
    s = c.put("/api/apply/settings", json=body).json()
    assert s["daily_cap"] == 10
    assert s["answers"]["expected_ctc"] == "18 LPA" and s["answers"]["skills_experience"] == {"python": 4}
    assert s["learned"] == {"highest education": "Bachelor's"}
    assert c.put("/api/apply/settings", json={"daily_cap": 500}).status_code == 422


def test_start_checks(client):
    c = client("b@x.io")
    r = c.post("/api/apply", json={"source": "linkedin", "keywords": ["python"]})
    assert r.status_code == 422 and "Connect a LinkedIn account" in r.json()["detail"]
    assert c.post("/api/apply", json={"source": "telegram", "keywords": ["python"]}).status_code == 422
    assert c.post("/api/apply", json={"source": "naukri", "keywords": []}).status_code == 422


def test_applications_are_per_user(client):
    from jobscout.db.models import Application, ApplyStatus, Platform, User
    from jobscout.db.session import new_session
    from sqlalchemy import select

    alice, bob = client("alice@x.io"), client("bob@x.io")
    with new_session() as s:
        uid = s.scalar(select(User.id).where(User.email == "alice@x.io"))
        a = Application(user_id=uid, platform=Platform.naukri, external_id="1", title="Python Dev",
                        status=ApplyStatus.needs_you, reason="Couldn't answer: “x”", questions=[])
        s.add(a)
        s.commit()
        app_id = a.id
    items = alice.get("/api/applications?status=needs_you").json()["items"]
    assert [i["title"] for i in items] == ["Python Dev"]
    assert bob.get("/api/applications").json()["total"] == 0
    assert bob.patch(f"/api/applications/{app_id}", json={"status": "applied"}).status_code == 404
    r = alice.patch(f"/api/applications/{app_id}", json={"status": "applied"}).json()
    assert r["status"] == "applied" and r["reason"] == "marked by you"
    assert alice.patch(f"/api/applications/{app_id}", json={"status": "failed"}).status_code == 422


def test_cv_upload_for_auto_apply(client, tmp_path, monkeypatch):
    import base64

    import docx

    from jobscout.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    d = docx.Document()
    d.add_paragraph("Jane Doe, +91 98765 43210, 4 years of Python")
    path = tmp_path / "cv.docx"
    d.save(path)
    c = client("cv@x.io")
    r = c.post("/api/apply/resume", json={"filename": "Jane CV.docx",
                                          "content_base64": base64.b64encode(path.read_bytes()).decode()})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["resume_filename"] == "Jane CV.docx" and s["resume_chars"] > 20
    assert c.get("/api/apply/settings").json()["resume_filename"] == "Jane CV.docx"
    assert c.post("/api/apply/resume", json={"filename": "cv.exe", "content_base64": "eA=="}).status_code == 422
