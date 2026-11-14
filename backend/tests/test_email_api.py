"""Email outreach through the API against a local fake SMTP server (no real Gmail)."""
import base64
import socket
import time
from email import message_from_bytes

import pytest
from fastapi.testclient import TestClient

GOOD_PW = "abcdabcdabcdabcd"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def smtp(db, monkeypatch):  # after `db`: it resets the cached Settings we patch below
    from aiosmtpd.controller import Controller
    from aiosmtpd.smtp import AuthResult, LoginPassword

    from jobscout.config import get_settings

    class Handler:
        def __init__(self):
            self.messages = []

        async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
            if "reject" in address:
                return "550 No such user"
            envelope.rcpt_tos.append(address)
            return "250 OK"

        async def handle_DATA(self, server, session, envelope):
            self.messages.append(envelope)
            return "250 OK"

    def auth(server, session, envelope, mechanism, data):
        if isinstance(data, LoginPassword) and data.password == GOOD_PW.encode():
            return AuthResult(success=True)
        # answer like Gmail does (aiosmtpd's default failure path stalls the client)
        return AuthResult(success=False, handled=False, message="535 5.7.8 Username and Password not accepted")

    handler = Handler()
    port = _free_port()
    ctl = Controller(handler, hostname="127.0.0.1", port=port, authenticator=auth, auth_require_tls=False,
                     auth_exclude_mechanism=["LOGIN"])  # fake server hangs on LOGIN retry; Gmail answers 535
    ctl.start()
    s = get_settings()
    for k, v in {"smtp_host": "127.0.0.1", "smtp_port": port, "smtp_starttls": False, "smtp_ssl_fallback_port": 0,
                 "email_min_delay": 0, "email_max_delay": 0, "gemini_api_key": ""}.items():
        monkeypatch.setattr(s, k, v)
    yield handler
    ctl.stop()


@pytest.fixture
def app_client(db, monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    from jobscout.config import get_settings
    from jobscout.web.app import app

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    return lambda: TestClient(app)


def _signup(c, email, paid=True):
    assert c.post("/api/auth/register", json={"email": email, "password": "password123"}).status_code == 201
    uid = c.get("/api/auth/me").json()["id"]
    if paid:  # email outreach is a paid feature
        from jobscout.db.models import User
        from jobscout.db.session import new_session

        with new_session() as s:
            s.get(User, uid).is_paid = True
            s.commit()
    return uid


def _add_contacts(user_id, emails):
    from jobscout.db import repo
    from jobscout.db.models import Platform
    from jobscout.db.session import new_session
    from jobscout.pipeline.scrape import save_contacts

    with new_session() as s:
        for i, e in enumerate(emails):
            post = repo.insert_post(s, user_id=user_id, platform=Platform.linkedin, external_id=f"p{i}{e}",
                                    description="We are #hiring a Python Developer", hiring_for="Python Developer")
            save_contacts(s, user_id, post.id, f"Recruiter {i}", [e], [])
        s.commit()


def _wait(c, job, timeout=30):
    from jobscout.web.jobs import manager

    end = time.time() + timeout
    while time.time() < end and manager.get(job["id"]).status == "running":
        time.sleep(0.05)
    return manager.get(job["id"])


def test_email_flow(smtp, app_client):
    c = app_client()
    uid = _signup(c, "me@example.com")
    _add_contacts(uid, ["hr0@acme.io", "hr1@acme.io", "reject@acme.io"])

    # not connected yet
    assert c.get("/api/email/settings").json()["connected"] is False
    assert c.post("/api/emails/send", json={}).status_code == 409

    # wrong app password -> test fails with a helpful message
    c.put("/api/email/settings", json={"gmail_address": "Me@Gmail.com", "app_password": "wrongwrongwrong1",
                                       "sender_name": "Alex", "daily_cap": 2,
                                       "profile_text": "Python dev, 3 yrs FastAPI"})
    r = c.post("/api/email/test", json={}).json()
    assert r["ok"] is False and "App Password" in r["message"] and "Gmail said: 535" in r["message"]

    # correct password, plus resume
    s = c.put("/api/email/settings", json={"app_password": "abcd abcd abcd abcd"}).json()
    assert s["gmail_address"] == "me@gmail.com" and s["has_app_password"] and "app_password" not in s
    pdf = base64.b64encode(b"%PDF-1.4 fake resume").decode()
    assert c.post("/api/email/settings/resume", json={"filename": "My CV.pdf", "content_base64": pdf}).json()["resume_filename"] == "My CV.pdf"
    r = c.post("/api/email/test", json={"send_to_self": True}).json()
    assert r["ok"] is True
    assert smtp.messages[-1].rcpt_tos == ["me@gmail.com"]
    assert c.get("/api/email/settings").json()["verified_at"]

    # draft all pending (template, Gemini disabled)
    assert c.get("/api/email/stats").json()["pending"] == 3
    job = c.post("/api/emails/draft", json={}).json()
    assert _wait(c, job).status == "done"
    drafts = c.get("/api/emails?status=drafted").json()["items"]
    assert len(drafts) == 3
    d0 = next(d for d in drafts if d["contact"]["email"] == "hr0@acme.io")
    assert "Recruiter" in d0["body"] and "Alex" in d0["body"] and "attached my resume" in d0["body"]

    # edit one draft
    edited = c.patch(f"/api/emails/{d0['id']}", json={"subject": "Python role at Acme", "body": "Hi!\n\nThanks"}).json()
    assert edited["subject"] == "Python role at Acme" and edited["status"] == "drafted"

    # send: daily cap 2, one test email already counts? (test emails aren't outreach) -> 2 sent, 1 waits
    job = c.post("/api/emails/send", json={"limit": 10}).json()
    j = _wait(c, job)
    assert j.status == "done", j.events
    outcomes = [e["outcome"] for e in j.events if e["type"] == "email"]
    assert len(outcomes) == 2
    stats = c.get("/api/email/stats").json()
    assert stats["sent"] + stats["failed"] == 2 and stats["drafted"] == 1

    sent_msg = next(m for m in smtp.messages if m.rcpt_tos == ["hr0@acme.io"])
    parsed = message_from_bytes(sent_msg.content)
    assert parsed["Subject"] == "Python role at Acme"
    assert parsed["From"] == "Alex <me@gmail.com>"
    assert [p.get_filename() for p in parsed.walk() if p.get_filename()] == ["My CV.pdf"]

    # sent emails can't be edited
    assert c.patch(f"/api/emails/{d0['id']}", json={"body": "changed"}).status_code == 409


def test_rejected_recipient_fails_permanently(smtp, app_client):
    c = app_client()
    uid = _signup(c, "me@example.com")
    _add_contacts(uid, ["reject@acme.io"])
    c.put("/api/email/settings", json={"gmail_address": "me@gmail.com", "app_password": GOOD_PW})
    _wait(c, c.post("/api/emails/draft", json={}).json())
    j = _wait(c, c.post("/api/emails/send", json={}).json())
    ev = [e for e in j.events if e["type"] == "email"]
    assert ev[0]["outcome"] == "failed" and "rejected" in ev[0]["error"]
    assert c.get("/api/emails?status=failed").json()["total"] == 1


def test_send_selected_only_and_isolation(smtp, app_client):
    a, b = app_client(), app_client()
    ua = _signup(a, "a@example.com")
    _signup(b, "b@example.com")
    _add_contacts(ua, ["x@acme.io", "y@acme.io"])
    a.put("/api/email/settings", json={"gmail_address": "a@gmail.com", "app_password": GOOD_PW, "daily_cap": 50})
    _wait(a, a.post("/api/emails/draft", json={}).json())
    items = a.get("/api/emails").json()["items"]
    target = items[0]

    # user B sees nothing and can't touch A's emails
    assert b.get("/api/emails").json()["total"] == 0
    assert b.patch(f"/api/emails/{target['id']}", json={"status": "skipped"}).status_code == 404

    j = _wait(a, a.post("/api/emails/send", json={"ids": [target["id"]]}).json())
    assert [e["id"] for e in j.events if e["type"] == "email"] == [target["id"]]
    assert a.get("/api/email/stats").json()["sent"] == 1


def test_wrong_password_aborts_send_job(smtp, app_client):
    c = app_client()
    uid = _signup(c, "me@example.com")
    _add_contacts(uid, ["hr@acme.io"])
    c.put("/api/email/settings", json={"gmail_address": "me@gmail.com", "app_password": "wrongwrongwrong1"})
    _wait(c, c.post("/api/emails/draft", json={}).json())
    j = _wait(c, c.post("/api/emails/send", json={}).json())
    assert j.status == "error"
    assert any(e["type"] == "error" and "App Password" in e["message"] for e in j.events)
    assert c.get("/api/email/stats").json()["drafted"] == 1  # nothing lost


def test_settings_row_created_once_under_concurrent_requests(db):
    """Regression: the Emails page loads settings + stats in parallel; both used to INSERT and one 500'd."""
    import threading

    from sqlalchemy import func, select

    from jobscout.db.models import EmailSettings
    from jobscout.db.session import new_session
    from jobscout.mailer.sender_config import get_or_create_settings
    from jobscout.security.users import create_user

    with new_session() as s:
        uid = create_user(s, "race@example.com", "password123").id
    barrier, errors = threading.Barrier(8), []

    def worker():
        try:
            with new_session() as s:
                barrier.wait()
                assert get_or_create_settings(s, uid).user_id == uid
                s.commit()
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with new_session() as s:
        assert s.scalar(select(func.count()).select_from(EmailSettings)) == 1


def test_blocked_ports_give_a_clear_message(db, app_client, monkeypatch):
    """587 cut off and 465 cut off too -> explain it's the PC/network, not the password."""
    from jobscout.config import get_settings

    closed_a, closed_b = _free_port(), _free_port()   # nothing listens on these
    s = get_settings()
    for k, v in {"smtp_host": "127.0.0.1", "smtp_port": closed_a, "smtp_starttls": False,
                 "smtp_ssl_fallback_port": closed_b}.items():
        monkeypatch.setattr(s, k, v)
    c = app_client()
    _signup(c, "me@example.com")
    c.put("/api/email/settings", json={"gmail_address": "me@gmail.com", "app_password": GOOD_PW})
    r = c.post("/api/email/test", json={}).json()
    assert r["ok"] is False
    assert f"port {closed_a} failed at connect" in r["message"] and f"port {closed_b} failed at connect" in r["message"]
    assert "antivirus" in r["message"]
