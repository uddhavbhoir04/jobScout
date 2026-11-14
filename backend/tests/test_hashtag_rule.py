"""#hiring is always required; role hashtags are searched together with it in one query."""
from types import SimpleNamespace

from jobscout.pipeline import scrape as pipeline
from jobscout.pipeline.scrape import build_queries, match_tags, normalise_tags
from jobscout.scrapers.linkedin import LinkedInScraper

REQ = ["#hiring"]
ROLES = ["#processimprovement", "#projectcoordination", "#processtransformation", "#processmining"]


def test_one_combined_query_with_hiring_and_backups_that_keep_hiring():
    combined, backups = build_queries(REQ, ROLES)
    assert combined == "#hiring AND (#processimprovement OR #projectcoordination OR #processtransformation OR #processmining)"
    assert backups == [f"#hiring AND {t}" for t in ROLES]  # never a role tag without #hiring

    assert build_queries(REQ, ["#processmining"]) == ("#hiring AND #processmining", [])
    assert build_queries(REQ, []) == ("#hiring", [])


def test_required_and_at_least_one_role():
    ok = "We are #Hiring a Process Analyst #ProcessMining #Celonis. Mail hr@x.io"
    assert match_tags(ok, REQ, ROLES) == (["#hiring", "#processmining"], None)
    assert match_tags("Great talk on #processimprovement today", REQ, ROLES) == (None, "missing required #hiring")
    assert match_tags("#hiring Python developer, mail hr@x.io", REQ, ROLES) == (None, "no role hashtag")
    assert match_tags("#hiringnow #processmining", REQ, ROLES)[0] is None  # #hiringnow is not #hiring


def test_query_url_encoding():
    url = LinkedInScraper.search_url("#hiring AND (#processmining OR #processimprovement)", "past-week")
    assert "keywords=%23hiring%20AND%20%28%23processmining%20OR%20%23processimprovement%29" in url


def test_normalise_tags():
    assert normalise_tags(["#Hiring, processmining  #hiring #PM"]) == ["#hiring", "#processmining", "#pm"]


class FakeScraper:
    """Pretends to be LinkedIn: returns canned posts per query and records what was searched."""

    platform = "linkedin"

    def __init__(self, results: dict[str, list]):
        self.results, self.searched = results, []

    def ensure_logged_in(self, *a, **k):
        return True

    def search(self, query, date_range):
        self.searched.append(query)
        yield from self.results.get(query, [])


def _run(monkeypatch, results, tags, required=None, limit=5):
    """Drive run_scrape with a fake LinkedIn: every post a search returns counts as one new contact."""
    import contextlib

    fake = FakeScraper(results)
    monkeypatch.setattr(pipeline, "open_context", lambda *a, **k: contextlib.nullcontext(None))
    monkeypatch.setattr(pipeline, "get_scraper", lambda *a, **k: fake)
    monkeypatch.setattr(pipeline, "decrypt", lambda b: "pw")
    monkeypatch.setattr(pipeline, "load_accounts", lambda *a, **k: [SimpleNamespace(
        id=1, login_email="li@x.io", password_enc=b"", last_status=None, last_login_at=None)])

    class FakeSession:
        def add(self, obj):
            obj.id = obj.id or 1

        def commit(self):
            pass

        rollback = close = commit

    def fake_scrape_tag(session, scraper, ai, run, query, required, optional, date_range, result,
                        seen, done, *rest):
        found = 0
        for _ in scraper.search(query, None):
            found += 1
            if done():
                break
            result.scanned += 1
            result.saved += 1
            result.collected += 1
        return found

    monkeypatch.setattr(pipeline, "new_session", lambda: FakeSession())
    monkeypatch.setattr(pipeline, "_scrape_tag", fake_scrape_tag)
    from jobscout.extract.dates import resolve

    res = pipeline.run_scrape(user_id=1, platform="linkedin", tags=tags, required_tags=required,
                              date_range=resolve("last-7d"), limit=limit)
    return fake.searched, res


def test_stops_after_combined_search_once_target_is_reached(monkeypatch):
    combined, _ = build_queries(REQ, ROLES)
    searched, res = _run(monkeypatch, {combined: ["p"] * 8}, ROLES, limit=5)
    assert searched == [combined]
    assert (res.collected, res.stop_reason) == (5, "target reached")


def test_keeps_searching_with_hiring_backups_until_target(monkeypatch):
    combined, backups = build_queries(REQ, ROLES)
    # combined gives 2, first backup 1, second backup 3 -> target 5 reached during the 3rd search
    results = {combined: ["p"] * 2, backups[0]: ["p"], backups[1]: ["p"] * 3}
    searched, res = _run(monkeypatch, results, ROLES, limit=5)
    assert searched == [combined, backups[0], backups[1]]
    assert all(q.startswith("#hiring AND ") for q in searched)
    assert (res.collected, res.stop_reason) == (5, "target reached")


def test_reports_when_linkedin_has_no_more_posts(monkeypatch):
    combined, backups = build_queries(REQ, ROLES)
    searched, res = _run(monkeypatch, {combined: ["p"] * 2}, ROLES, limit=30)
    assert searched == [combined, *backups]          # tried everything
    assert res.collected == 2
    assert res.stop_reason.startswith("no more matching posts")


def test_hiring_is_always_added_even_if_not_given(monkeypatch):
    searched, _ = _run(monkeypatch, {"#hiring AND #processmining": ["p"] * 5}, ["#processmining"])
    assert searched == ["#hiring AND #processmining"]


def test_long_role_lists_are_split_to_stay_under_linkedins_hashtag_limit():
    roles = ["#pythondeveloper", "#ai", "#generativeai", "#frontenddeveloper", "#frontend", "#developer"]
    first, rest = build_queries(REQ, roles)
    assert first == "#hiring AND (#pythondeveloper OR #ai OR #generativeai OR #frontenddeveloper OR #frontend)"
    assert rest[0] == "#hiring AND #developer"
    for q in [first, *rest]:
        assert 1 < q.count("#") <= pipeline.MAX_HASHTAGS_PER_QUERY
    assert {f"#hiring AND {t}" for t in roles} <= set(rest)  # per-tag follow-ups still there
    assert len(rest) == len(set(rest))
