"""Only the Next.js server (which sends X-Internal-Key) may call the API."""
from fastapi.testclient import TestClient

from jobscout.config import get_settings


def test_api_rejects_calls_without_the_shared_secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "s3cret-key-for-tests")
    get_settings.cache_clear()
    try:
        from jobscout.web.app import app

        c = TestClient(app)
        assert c.get("/api/health").status_code == 404                                   # no key
        assert c.get("/api/health", headers={"x-internal-key": "wrong"}).status_code == 404
        assert c.post("/api/auth/login", json={"email": "a@b.co", "password": "x"}).status_code == 404
        assert c.get("/api/health", headers={"x-internal-key": "s3cret-key-for-tests"}).status_code == 200
    finally:
        monkeypatch.setenv("INTERNAL_API_KEY", "")
        get_settings.cache_clear()
