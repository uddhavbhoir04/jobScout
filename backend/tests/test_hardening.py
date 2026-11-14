"""Login/sign-up rate limits, bounded list parameters, server-wide browser job cap."""
import pytest
from fastapi.testclient import TestClient

from jobscout.security.ratelimit import LOGIN_PER_ACCOUNT, REGISTER_PER_IP, limiter


@pytest.fixture
def client(db):
    from jobscout.web.app import app

    limiter.clear()
    yield TestClient(app)
    limiter.clear()


def test_login_is_rate_limited_per_account(client):
    client.post("/api/auth/register", json={"email": "rl@example.com", "password": "password123"})
    for _ in range(LOGIN_PER_ACCOUNT[0]):
        assert client.post("/api/auth/login", json={"email": "rl@example.com", "password": "wrong-pass"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "rl@example.com", "password": "password123"})
    assert r.status_code == 429 and "Too many attempts" in r.json()["detail"] and int(r.headers["retry-after"]) > 0


def test_correct_password_resets_failed_attempts(client):
    client.post("/api/auth/register", json={"email": "ok@example.com", "password": "password123"})
    for _ in range(LOGIN_PER_ACCOUNT[0] - 1):
        client.post("/api/auth/login", json={"email": "ok@example.com", "password": "wrong-pass"})
    assert client.post("/api/auth/login", json={"email": "ok@example.com", "password": "password123"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "ok@example.com", "password": "wrong-pass"}).status_code == 401


def test_signups_are_rate_limited_per_ip(client):
    codes = [client.post("/api/auth/register", json={"email": f"u{i}@example.com", "password": "password123"}).status_code
             for i in range(REGISTER_PER_IP[0] + 1)]
    assert codes[:-1] == [201] * REGISTER_PER_IP[0] and codes[-1] == 429


def test_list_parameters_are_bounded(client):
    client.post("/api/auth/register", json={"email": "b@example.com", "password": "password123"})
    assert client.get("/api/posts?limit=-1").status_code == 422
    assert client.get("/api/contacts?offset=-5").status_code == 422
    assert client.get("/api/runs?limit=100000").status_code == 422
    assert client.get("/api/posts?limit=50").status_code == 200


def test_server_wide_browser_job_cap(client, monkeypatch):
    from jobscout.web import app as app_module

    client.post("/api/auth/register", json={"email": "cap@example.com", "password": "password123"})
    monkeypatch.setattr(app_module.manager, "count_running", lambda kinds, where=None: 99)
    r = client.post("/api/scrape", json={"tags": ["#python"]})
    assert r.status_code == 503 and "busy" in r.json()["detail"]
