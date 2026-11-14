"""DB tests run against TEST_DATABASE_URL (a scratch database that is wiped on every test)."""
import os

import pytest

TEST_URL = os.getenv("TEST_DATABASE_URL")
# API tests call the FastAPI app directly (no Next.js in front), so the shared-secret check is off by
# default here; test_internal_key.py turns it on explicitly.
os.environ["INTERNAL_API_KEY"] = ""


@pytest.fixture
def db():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    from jobscout.config import get_settings
    from jobscout.db.models import Base
    from jobscout.db.session import get_engine
    from jobscout.security.ratelimit import limiter

    limiter.clear()  # sign-up/login limits are per client IP, and every TestClient shares one
    os.environ["DATABASE_URL"] = TEST_URL  # env vars win over .env
    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = get_engine()
    assert engine.url.database != "jobscout", "refusing to wipe the main database"
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
    get_engine.cache_clear()


@pytest.fixture
def session(db):
    from jobscout.db.session import new_session

    with new_session() as s:
        yield s
