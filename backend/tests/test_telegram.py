"""Telegram source: page parsing, filters, the run pipeline and the channel API (no network)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from jobscout.pipeline import telegram as tg
from jobscout.scrapers import telegram as scraper
from jobscout.scrapers.telegram import ChannelNotFound, TgPost, normalise_channel

NOW = datetime.now(timezone.utc)


def _msg(pid: int, text_html: str, ago: timedelta, channel: str = "itreferral_jobs") -> str:
    ts = (NOW - ago).isoformat()
    return (f'<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" '
            f'data-post="{channel}/{pid}"><div class="tgme_widget_message_text js-message_text" dir="auto">'
            f'{text_html}</div><a class="tgme_widget_message_date"><time datetime="{ts}" class="time"></time></a>'
            f'</div></div>')


PAGE = ('<html><div class="tgme_channel_info"><div class="tgme_channel_info_header_title"><span dir="auto">'
        'IT Referral Jobs</span></div></div><div class="tgme_header_counter">18.7K subscribers</div><section>'
        + _msg(101, '<i class="emoji"><b>🚨</b></i> Job Alert<br/><br/>Role / Title: Python Developer<br/>'
                    'Company: Acme Tech<br/>Location: Pune<br/>Experience: 2-4 Years<br/>'
                    'Send CV to <a href="mailto:priya.hr@acme.example">priya.hr@acme.example</a>',
               timedelta(hours=2))
        + _msg(102, 'Hiring React developer, 6+ yrs. Call +91 98765 43210', timedelta(hours=5))
        + _msg(103, 'Join our channel for daily updates!', timedelta(hours=6))
        + '</section></html>')


def test_normalise_channel_accepts_names_handles_and_links():
    for v in ["ITReferral_Jobs", "@itreferral_jobs", "https://t.me/s/itreferral_jobs", "t.me/itreferral_jobs/7437",
              "https://telegram.me/itreferral_jobs?before=10"]:
        assert normalise_channel(v) == "itreferral_jobs"
    for bad in ["", "ab", "https://example.com/x", "1startswithdigit", "has space"]:
        with pytest.raises(ChannelNotFound):
            normalise_channel(bad)


def test_fetch_page_parses_posts_title_and_mailto(monkeypatch):
    monkeypatch.setattr(scraper, "_get", lambda url: PAGE)
    page = scraper.fetch_page("itreferral_jobs")
    assert page.title == "IT Referral Jobs" and page.subscribers == "18.7K subscribers"
    assert [p.id for p in page.posts] == [101, 102, 103]
    first = page.posts[0]
    assert "Role / Title: Python Developer\nCompany: Acme Tech" in first.text  # <br> -> newlines, tags stripped
    assert first.mailto == ["priya.hr@acme.example"] and first.url == "https://t.me/itreferral_jobs/101"
    assert first.posted_at is not None


def test_fetch_page_rejects_non_channels(monkeypatch):
    monkeypatch.setattr(scraper, "_get", lambda url: "<html>If you have Telegram, you can contact</html>")
    with pytest.raises(ChannelNotFound):
        scraper.fetch_page("someuser")


@pytest.mark.parametrize("text,expected", [
    ("Experience: 2-4 Years", (2, 4)),
    ("Experience: 6 to 10 yrs", (6, 10)),
    ("5+ years experience required", (5, 99)),
    ("Freshers can apply", (0, 1)),
    ("Exp: 3 years", (3, 3)),
    ("Great team, apply now", None),
])
def test_experience_range(text, expected):
    assert tg.experience_range(text) == expected


def test_experience_filter_keeps_unknown_and_overlapping():
    assert tg.experience_ok("Experience: 2-4 Years", 0, 3)
    assert not tg.experience_ok("Experience: 6-10 Years", 0, 3)
    assert tg.experience_ok("no experience mentioned", 0, 3)
    assert tg.experience_ok("Experience: 6-10 Years", None, None)


def test_keywords_match_whole_words():
    assert tg.match_keywords("Hiring React.js developer", ["react"]) == ["react"]
    assert tg.match_keywords("reactive systems", ["react"]) == []
    assert tg.match_keywords("C++ and Node.js", ["c++", "node.js", "java"]) == ["c++", "node.js"]
    assert tg.normalise_keywords(["#Python, django", "react\n", "python"]) == ["python", "django", "react"]


def test_hiring_summary_from_structured_post():
    text = "Role / Title: C++ Developer\nCompany: Quant Fund\nLocation: Mumbai\nExperience: 5+ years"
    assert tg.hiring_summary(text) == "C++ Developer at Quant Fund | 5+ years | Mumbai"


def test_channel_own_addresses_are_ignored():
    posts = [TgPost("itreferral_jobs", i, NOW, f"Job {i}. Mail hr{i}@co{i}.example. More jobs: itreferraljobs13@gmail.com")
             for i in range(2)]
    posts += [TgPost("itreferral_jobs", 9, NOW, "Promo: promo@agency.example")] * 3
    own = tg.own_addresses("itreferral_jobs", posts)
    assert "itreferraljobs13@gmail.com" in own        # named after the channel
    assert "promo@agency.example" in own              # repeated in 3+ posts
    assert "hr0@co0.example" not in own


def _posts(channel, specs):
    return [TgPost(channel, pid, NOW - ago, text) for pid, text, ago in specs]


def test_run_saves_only_matching_posts_with_contacts(session, monkeypatch):
    from jobscout.db.models import Contact, Post, TelegramChannel, User

    user = User(email="tg@example.com", password_hash="x")
    session.add(user)
    session.commit()
    channels = {
        "itreferral_jobs": _posts("itreferral_jobs", [
            (1, "Role: Python Developer\nCompany: Acme\nExperience: 2-4 Years\nMail priya@acme.example", timedelta(hours=1)),
            (2, "Java developer wanted, mail java@corp.example", timedelta(hours=2)),               # no keyword
            (3, "Python intern, registration fee Rs 2000, mail scam@x.example", timedelta(hours=3)),  # scam
            (4, "Python dev needed. Contact our channel: itreferraljobs13@gmail.com", timedelta(hours=4)),  # own address
            (5, "Python Lead, Experience: 9-12 years, mail lead@big.example", timedelta(hours=5)),     # exp range
            (6, "Old python job mail old@co.example", timedelta(days=10)),                           # out of date range
        ]),
        "merntech": _posts("merntech", [
            (7, "Role: Python Developer\nCompany: Acme\nExperience: 2-4 Years\nMail priya@acme.example", timedelta(hours=1)),  # same job
            (8, "Python + Django role, call +91 98765 43210", timedelta(hours=6)),
        ]),
    }
    page = scraper.ChannelPage(title="Some Channel", subscribers="1K subscribers", posts=[])

    def fake_iter(name, since=None, max_pages=0, should_stop=None):
        for p in channels[name]:
            yield page, p

    monkeypatch.setattr(tg, "iter_posts", fake_iter)
    events = []
    res = tg.run_telegram_scrape(user_id=user.id, keywords=["python"], date_range=tg_range(days=7), limit=20,
                                 exp_min=0, exp_max=5, on_event=events.append)

    saved = sorted(p.external_id for p in session.query(Post).filter_by(user_id=user.id))
    assert saved == ["itreferral_jobs/1", "merntech/8"]
    contacts = {(c.email, c.phone) for c in session.query(Contact).filter_by(user_id=user.id)}
    assert contacts == {("priya@acme.example", None), (None, "+919876543210")}
    assert res.collected == 2 and res.stop_reason.startswith("no more matching posts")
    reasons = {e["reason"] for e in events if e["status"] == "skipped"}
    assert {"no keyword match", "asks for a fee: likely a scam", "no email or phone",
            "experience outside your range"} <= reasons
    assert res.skipped.get("same job already seen in this run") == 1
    # channel quality numbers were refreshed from the posts read
    ch = session.query(TelegramChannel).filter_by(user_id=user.id, name="itreferral_jobs").one()
    session.refresh(ch)
    assert ch.posts_checked == 6 and ch.checked_at is not None


def tg_range(days: int):
    from jobscout.extract.dates import resolve

    return resolve(f"last-{days}d")


@pytest.fixture
def client(db):
    from jobscout.web.app import app

    return TestClient(app)


def test_channel_api_seeds_defaults_and_adds_checked_channels(client, monkeypatch):
    from jobscout.web import telegram_api

    client.post("/api/auth/register", json={"email": "ch@example.com", "password": "password123"})
    names = [c["name"] for c in client.get("/api/telegram/channels").json()]
    assert names == tg.DEFAULT_CHANNELS

    monkeypatch.setattr(telegram_api, "channel_stats", lambda name: {
        "title": "Dev Jobs", "subscribers": "5K subscribers", "posts_checked": 60, "contact_pct": 71,
        "posts_per_day": "2.5", "last_post_at": NOW})
    r = client.post("/api/telegram/channels", json={"name": "https://t.me/s/Dev_Jobs_India"})
    assert r.status_code == 201 and r.json()["name"] == "dev_jobs_india" and r.json()["contact_pct"] == 71
    assert client.post("/api/telegram/channels", json={"name": "@dev_jobs_india"}).status_code == 409
    assert client.post("/api/telegram/channels", json={"name": "not a channel!"}).status_code == 422

    cid = r.json()["id"]
    assert client.patch(f"/api/telegram/channels/{cid}?active=false").json()["active"] is False
    assert client.delete(f"/api/telegram/channels/{cid}").status_code == 204

    def missing(name):
        raise ChannelNotFound("@ghost has no public web preview")
    monkeypatch.setattr(telegram_api, "channel_stats", missing)
    assert client.post("/api/telegram/channels", json={"name": "ghost_channel"}).status_code == 404


def test_channels_are_private_per_user(client, monkeypatch):
    client.post("/api/auth/register", json={"email": "a1@example.com", "password": "password123"})
    mine = client.get("/api/telegram/channels").json()[0]["id"]
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "b1@example.com", "password": "password123"})
    assert client.delete(f"/api/telegram/channels/{mine}").status_code == 404
    assert client.patch(f"/api/telegram/channels/{mine}?active=false").status_code == 404


def test_telegram_scrape_is_free_and_skips_browser_capacity(client, monkeypatch):
    from jobscout.web import app as app_module

    client.post("/api/auth/register", json={"email": "free@example.com", "password": "password123"})
    monkeypatch.setattr(app_module.manager, "count_running", lambda kinds, where=None: 99)  # browsers "full"
    started = {}
    monkeypatch.setattr(app_module.manager, "start",
                        lambda kind, params, target, user_id=None: started.update(params=params) or
                        type("J", (), {"summary": lambda self: {"id": "abc123abc123", "kind": kind}})())
    r = client.post("/api/scrape", json={"source": "telegram", "keywords": ["python"], "date_filter": "last-7d"})
    assert r.status_code == 200 and started["params"]["source"] == "telegram"
    # LinkedIn is still capped when browsers are full, and still the default source
    r = client.post("/api/scrape", json={"tags": ["#python"]})
    assert r.status_code == 503
    assert client.post("/api/scrape", json={"source": "telegram", "exp_min": 5, "exp_max": 2}).status_code == 422


def test_default_channels_survive_concurrent_first_requests(session):
    """Two first page loads at once (two tabs / React dev double-mount) must not crash."""
    from concurrent.futures import ThreadPoolExecutor

    from jobscout.db.models import TelegramChannel, User
    from jobscout.db.session import new_session

    user = User(email="race@example.com", password_hash="x")
    session.add(user)
    session.commit()

    def first_load(_):
        with new_session() as s:
            tg.ensure_default_channels(s, user.id)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(first_load, range(8)))
    names = sorted(c.name for c in session.query(TelegramChannel).filter_by(user_id=user.id))
    assert names == sorted(tg.DEFAULT_CHANNELS)
