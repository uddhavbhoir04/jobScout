"""Excel export: SNo, Name, Email, Title, Company. Anything not found stays blank."""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobscout.extract.rules import find_company, find_title

FIXTURES = json.loads((Path(__file__).parent / "fixtures_linkedin_posts.json").read_text())


@pytest.mark.parametrize("text, title, company", [
    ("Company: Acme Corp\nRole: SDE", "SDE", "Acme Corp"),
    ("We are hiring a Python Developer at Infosys Limited. DM me", "Python Developer", "Infosys Limited"),
    ("Engineer at AT&T Labs, apply now", "Engineer", "AT&T Labs"),
    ("Join the Zoho team today!", None, "Zoho"),
    ("Join our team today!", None, None),
    ("Hiring, DM me", None, None),
])
def test_title_and_company(text, title, company):
    assert find_title(text) == title
    assert find_company(text) == company


def test_title_from_real_post():
    assert find_title(FIXTURES[0]["text"]) == "Back-end Developer (Python)"


def test_company_page_author_is_the_company():
    url = "https://www.linkedin.com/company/acme/"
    assert find_company("We're hiring!", "Acme Inc", url) == "Acme Inc"
    assert find_company("We're hiring!", "Jane Doe", "https://www.linkedin.com/in/jane/") is None


@pytest.fixture
def client(db, monkeypatch):
    from cryptography.fernet import Fernet

    from jobscout.config import get_settings
    from jobscout.web.app import app

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())
    c = TestClient(app)
    assert c.post("/api/auth/register", json={"email": "u@example.com", "password": "password123"}).status_code == 201
    return c


def test_xlsx_export(client):
    from openpyxl import load_workbook
    from sqlalchemy import select

    from jobscout.db import repo
    from jobscout.db.models import Platform, User
    from jobscout.db.session import new_session

    with new_session() as s:
        uid = s.scalar(select(User.id).where(User.email == "u@example.com"))
        p1 = repo.insert_post(s, user_id=uid, platform=Platform.linkedin, external_id="a", description=(
            "Hiring Python Developer at Infosys Limited. Mail hr@infosys.com"), emails=["hr@infosys.com"])
        p2 = repo.insert_post(s, user_id=uid, platform=Platform.linkedin, external_id="b",
                              description="DM me on +91 98765 43210", phones=["+919876543210"])
        repo.upsert_contact(s, user_id=uid, name="Asha", email="hr@infosys.com", phone=None, post_id=p1.id)
        repo.upsert_contact(s, user_id=uid, name=None, email=None, phone="+919876543210", post_id=p2.id)
        s.commit()

    r = client.get("/api/contacts.xlsx")
    assert r.status_code == 200
    assert "contacts.xlsx" in r.headers["content-disposition"]
    rows = list(load_workbook(io.BytesIO(r.content)).active.iter_rows(values_only=True))
    assert rows[0] == ("SNo", "Name", "Email", "Title", "Company")
    assert sorted(rows[1:], key=lambda r: r[0]) == [
        (1, None, None, None, None),  # newest first; nothing found -> blank cells
        (2, "Asha", "hr@infosys.com", "Python Developer", "Infosys Limited"),
    ]


def test_xlsx_export_for_one_run(client):
    from openpyxl import load_workbook
    from sqlalchemy import select

    from jobscout.db import repo
    from jobscout.db.models import Platform, ScrapeRun, User
    from jobscout.db.session import new_session

    with new_session() as s:
        uid = s.scalar(select(User.id).where(User.email == "u@example.com"))
        runs = [ScrapeRun(user_id=uid, platform=Platform.linkedin, account_ids=[], hashtags=[], date_filter="x",
                          requested_limit=5) for _ in range(2)]
        s.add_all(runs)
        s.flush()
        for i, (run, email) in enumerate([(runs[0], "a@x.com"), (runs[1], "b@x.com")]):
            post = repo.insert_post(s, user_id=uid, platform=Platform.linkedin, external_id=str(i), run_id=run.id,
                                    description="Hiring Data Analyst at Acme Corp. Mail " + email, emails=[email])
            repo.upsert_contact(s, user_id=uid, name=None, email=email, phone=None, post_id=post.id)
        s.commit()
        first, second = runs[0].id, runs[1].id

    r = client.get(f"/api/contacts.xlsx?run_id={second}")
    assert r.status_code == 200
    assert f"contacts-run-{second}.xlsx" in r.headers["content-disposition"]
    rows = list(load_workbook(io.BytesIO(r.content)).active.iter_rows(values_only=True))
    assert rows[1:] == [(1, None, "b@x.com", "Data Analyst", "Acme Corp")]
    assert client.get("/api/contacts.xlsx?run_id=99999").status_code == 404
    assert first != second
