"""Sign-up / login / logout and per-user data isolation through the HTTP API."""
import pytest
from fastapi.testclient import TestClient

from jobscout.security.users import hash_password, verify_password


def test_password_hashing():
    h = hash_password("correct horse")
    assert h.startswith("scrypt$") and "correct horse" not in h
    assert verify_password("correct horse", h)
    assert not verify_password("wrong", h)
    assert hash_password("same") != hash_password("same")  # salted


@pytest.fixture
def client(db, monkeypatch):
    from cryptography.fernet import Fernet

    from jobscout.config import get_settings
    from jobscout.web.app import app

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())
    return lambda: TestClient(app)


def _signup(c, email, password="password123"):
    r = c.post("/api/auth/register", json={"email": email, "password": password, "name": "Test"})
    assert r.status_code == 201, r.text
    return r.json()


def test_requires_login(client):
    c = client()
    for path in ["/api/accounts", "/api/stats", "/api/contacts", "/api/posts", "/api/runs", "/api/auth/me"]:
        assert c.get(path).status_code == 401, path


def test_signup_login_logout(client):
    c = client()
    me = _signup(c, "Alex@Example.com")
    assert me["email"] == "alex@example.com"
    assert c.get("/api/auth/me").json()["email"] == "alex@example.com"

    assert c.post("/api/auth/register", json={"email": "alex@example.com", "password": "password123"}).status_code == 400
    assert c.post("/api/auth/register", json={"email": "x@y.io", "password": "short"}).status_code == 400

    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/auth/me").status_code == 401

    assert c.post("/api/auth/login", json={"email": "alex@example.com", "password": "nope"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "ALEX@example.com", "password": "password123"}).status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_users_only_see_their_own_linkedin_accounts(client):
    alice, bob = client(), client()
    _signup(alice, "alice@x.io")
    _signup(bob, "bob@x.io")

    acc = alice.post("/api/accounts", json={"email": "alice.li@x.io", "password": "pw"}).json()
    # same LinkedIn email can be connected by another user, but not twice by the same user
    assert bob.post("/api/accounts", json={"email": "alice.li@x.io", "password": "pw"}).status_code == 201
    assert alice.post("/api/accounts", json={"email": "alice.li@x.io", "password": "pw"}).status_code == 409

    assert [a["email"] for a in alice.get("/api/accounts").json()] == ["alice.li@x.io"]
    assert len(bob.get("/api/accounts").json()) == 1
    # bob cannot touch alice's account
    assert bob.patch(f"/api/accounts/{acc['id']}?active=false").status_code == 404
    assert bob.delete(f"/api/accounts/{acc['id']}").status_code == 404
    assert bob.post(f"/api/accounts/{acc['id']}/login").status_code == 404
    assert alice.delete(f"/api/accounts/{acc['id']}").status_code == 204


def test_first_user_adopts_existing_data(db, client):
    from jobscout.db import repo
    from jobscout.db.models import Platform
    from jobscout.db.session import new_session
    from jobscout.pipeline.scrape import save_contacts

    with new_session() as s:  # data from before users existed
        post = repo.insert_post(s, user_id=None, platform=Platform.linkedin, external_id="old", description="x")
        save_contacts(s, None, post.id, "Old HR", ["old@hr.io"], [])
        s.commit()

    first, second = client(), client()
    _signup(first, "first@x.io")
    _signup(second, "second@x.io")
    assert first.get("/api/stats").json()["contacts"] == 1
    assert first.get("/api/posts").json()["total"] == 1
    assert second.get("/api/stats").json()["contacts"] == 0
    assert second.get("/api/contacts").json()["items"] == []
