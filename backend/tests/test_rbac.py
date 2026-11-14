"""RBAC: free vs paid plan. Paid unlocks the features that cost money (AI email writing + sending)."""
import pytest
from fastapi.testclient import TestClient

EMAIL_ENDPOINTS = [
    ("get", "/api/email/settings", None),
    ("put", "/api/email/settings", {"sender_name": "x"}),
    ("post", "/api/email/test", {}),
    ("get", "/api/email/stats", None),
    ("get", "/api/emails", None),
    ("post", "/api/emails/draft", {}),
    ("post", "/api/emails/send", {}),
    ("patch", "/api/emails/1", {"subject": "x"}),
    ("post", "/api/email/settings/resume", {"filename": "a.pdf", "content_base64": "eA=="}),
]


@pytest.fixture
def client(db, monkeypatch):
    from cryptography.fernet import Fernet

    from jobscout.config import get_settings
    from jobscout.web.app import app

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())
    c = TestClient(app)
    assert c.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"}).status_code == 201
    return c


def _set_paid(email, paid):
    from sqlalchemy import select

    from jobscout.db.models import User
    from jobscout.db.session import new_session

    with new_session() as s:
        s.scalar(select(User).where(User.email == email)).is_paid = paid
        s.commit()


def test_new_users_are_free_and_profile_says_so(client):
    for path in ("/api/profile", "/api/auth/me"):
        body = client.get(path).json()
        assert body["is_paid"] is False and body["plan"] == "free"


def test_free_user_is_blocked_from_every_email_endpoint(client):
    for method, path, payload in EMAIL_ENDPOINTS:
        r = getattr(client, method)(path, **({"json": payload} if payload is not None else {}))
        assert r.status_code == 403, (method, path, r.status_code)
        assert "paid plan" in r.json()["detail"]


def test_free_user_can_still_scrape_and_see_data(client):
    for path in ("/api/accounts", "/api/stats", "/api/contacts", "/api/posts", "/api/runs"):
        assert client.get(path).status_code == 200, path


def test_paid_user_gets_email_features(client):
    _set_paid("u@example.com", True)
    assert client.get("/api/profile").json() == {**client.get("/api/profile").json(), "is_paid": True, "plan": "paid"}
    assert client.get("/api/email/settings").status_code == 200
    assert client.get("/api/emails").status_code == 200
    _set_paid("u@example.com", False)  # downgrade takes effect immediately
    assert client.get("/api/emails").status_code == 403


def test_ai_post_analysis_only_for_paid(monkeypatch):
    """Scraping never calls the LLM for free users, even when AI_EXTRACTION is on."""
    from jobscout.config import get_settings
    from jobscout.pipeline import scrape as pipeline

    monkeypatch.setattr(get_settings(), "ai_extraction", True)
    built = []
    from types import SimpleNamespace

    monkeypatch.setattr(pipeline, "Gemini", lambda settings: built.append(1) or SimpleNamespace(available=True))
    monkeypatch.setattr(pipeline, "new_session", lambda: (_ for _ in ()).throw(RuntimeError("stop here")))
    from jobscout.extract.dates import resolve

    for use_ai, expected in ((False, 0), (True, 1)):
        built.clear()
        with pytest.raises(RuntimeError, match="stop here"):
            pipeline.run_scrape(user_id=1, platform="linkedin", tags=["#x"], use_ai=use_ai,
                                date_range=resolve("today"), limit=1)
        assert len(built) == expected
