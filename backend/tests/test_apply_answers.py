"""Screening-question answers: saved sheet rules, option matching, learned answers, AI gate."""
import pytest

from jobscout.apply.answers import Answerer, match_option, normalize, valid
from jobscout.apply.base import Question

SHEET = {
    "notice_period_days": 30, "current_ctc": "12 LPA", "expected_ctc": "18 LPA", "total_experience_years": 4,
    "skills_experience": {"python": 4, "react": 2, "react native": 1}, "relocate": True,
    "authorized_to_work": True, "needs_sponsorship": False, "phone": "+919876543210", "city": "Pune",
    "linkedin_url": "https://linkedin.com/in/me", "custom": [{"q": "Why do you want to join us?", "a": "Your product."}],
}


def _a(label, kind="text", options=None, sheet=SHEET, **kw):
    return Answerer(sheet, kw.pop("learned", {}), **kw).answer(Question(label, kind, options or [], required=True))


@pytest.mark.parametrize("label, kind, options, expected", [
    ("How many years of experience do you have with Python?", "number", None, "4"),
    ("Years of experience in React Native", "number", None, "1"),          # longest skill name wins
    ("How many years of work experience do you have?", "number", None, "4"),  # total
    ("Total experience", "text", None, "4"),
    ("What is your notice period?", "select", ["Select an option", "Immediate", "15 days", "1 month", "2 months"], "1 month"),
    ("Notice period (in days)", "number", None, "30"),
    ("What is your official notice period?", "text", None, "30"),
    ("Expected CTC", "text", None, "18 LPA"),
    ("Current CTC (in lakhs)", "number", None, "12"),
    ("Are you willing to relocate?", "radio", ["Yes", "No"], "Yes"),
    ("Will you now or in the future require sponsorship?", "radio", ["Yes", "No"], "No"),
    ("Are you legally authorized to work in India?", "select", ["Select an option", "Yes", "No"], "Yes"),
    ("Mobile phone number", "text", None, "9876543210"),   # national number: forms have a country-code box
    ("LinkedIn Profile", "text", None, "https://linkedin.com/in/me"),
    ("Why do you want to join us", "textarea", None, "Your product."),   # custom Q&A, close wording
    ("I agree to the terms and privacy policy", "checkbox", None, "Yes"),
])
def test_saved_answers(label, kind, options, expected):
    qa = _a(label, kind, options)
    assert (qa.answer, qa.source) == (expected, "saved")


def test_unknown_skill_is_not_answered_with_total_experience():
    qa = _a("How many years of experience do you have with Kubernetes?", "number")
    assert qa.answer is None and qa.source == "none"


def test_prefilled_fields_are_kept():
    q = Question("Email address", "text", [], True, value="me@example.com")
    qa = Answerer(SHEET, {}).answer(q)
    assert (qa.answer, qa.source) == ("me@example.com", "prefilled")


@pytest.mark.parametrize("answer, options, expected", [
    ("30", ["0-15 days", "16-30 days", "More than 30 days"], "16-30 days"),
    ("4", ["0-2 years", "3-5 years", "5+ years"], "3-5 years"),
    ("0", ["Immediate", "15 days", "30 days"], "Immediate"),
    ("Yes", ["Yes, I am", "No"], "Yes, I am"),
    ("B.Tech", ["Select", "B.Tech / B.E.", "MCA"], "B.Tech / B.E."),
    ("Maybe", ["Yes", "No"], None),
])
def test_match_option(answer, options, expected):
    assert match_option(answer, options) == expected


def test_valid_numbers():
    assert valid(Question("x", "number"), "about 4.5 years") == "4.5"
    assert valid(Question("x", "number"), "none") is None


def test_learned_answers_are_reused():
    learned = {normalize("Do you have a valid driving licence?"): "Yes"}
    qa = _a("Do you have a valid driving licence?", "radio", ["Yes", "No"], learned=learned)
    assert (qa.answer, qa.source) == ("Yes", "learned")


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def ask_json(self, system, user):
        self.calls += 1
        return self.reply


def test_ai_answers_when_confident_and_learns():
    llm = FakeLLM({"answer": "Bachelor's", "confident": True})
    ans = Answerer(SHEET, {}, "B.Tech in CS", llm=llm)
    qa = ans.answer(Question("Highest education?", "select", ["Select", "Bachelor's", "Master's"], True))
    assert (qa.answer, qa.source) == ("Bachelor's", "ai")
    assert ans.new_learned == {"highest education": "Bachelor's"}
    # the same question again comes from the learned answers, without asking the AI
    assert ans.answer(Question("Highest education?", "select", ["Bachelor's", "Master's"], True)).source == "learned"
    assert llm.calls == 1


@pytest.mark.parametrize("reply", [
    {"answer": "Bachelor's", "confident": False},   # not sure: leave it to the user
    {"answer": "PhD", "confident": True},           # not one of the options
    None,                                           # AI failed
])
def test_ai_unsure_or_invalid_is_not_used(reply):
    ans = Answerer(SHEET, {}, llm=FakeLLM(reply))
    qa = ans.answer(Question("Highest education?", "select", ["Bachelor's", "Master's"], True))
    assert qa.answer is None and ans.new_learned == {}


def test_no_ai_without_llm():
    qa = Answerer({}, {}).answer(Question("Highest education?", "text", [], True))
    assert qa.answer is None and qa.source == "none"


# ---------------------------------------------------------------- LinkedIn search URL / cards
def test_linkedin_search_url_and_cards():
    from datetime import timedelta
    from urllib.parse import parse_qs, urlparse

    from jobscout.apply import linkedin
    from jobscout.extract.dates import DateRange, now

    ref = now()
    week = DateRange("last-7d", ref - timedelta(days=7), ref)
    # LinkedIn ignores location / work-type URL filters (checked live): they go in the query instead
    q = parse_qs(urlparse(linkedin.search_url("python developer", "Pune", week, ["hybrid", "on-site"], page=2)).query)
    assert q["keywords"] == ["python developer in Pune"] and q["f_AL"] == ["true"] and q["f_TPR"] == ["r604800"]
    assert q["start"] == ["50"] and "location" not in q
    assert parse_qs(urlparse(linkedin.search_url("python", None, week, [], 0)).query)["keywords"] == ["python in India"]
    assert parse_qs(urlparse(linkedin.search_url("python", None, week, ["remote"], 0)).query)["keywords"] == ["python remote"]
    assert linkedin.time_filter(DateRange("today", ref - timedelta(days=1), ref), ref=ref) == "r86400"

    # card text as the live site renders it (Nov 2026)
    job = linkedin.parse_card({"id": "4492571619", "lines": [
        "Full Stack Engineer (Verified job)", "Full Stack Engineer", "The Yellow Network", "Mumbai (Hybrid)",
        "Actively reviewing applicants", "Posted 5 days ago", "5 days ago", "Easy Apply"]}, "react")
    assert (job.title, job.company, job.location, job.work_mode) == ("Full Stack Engineer", "The Yellow Network", "Mumbai", "hybrid")
    assert job.url == "https://www.linkedin.com/jobs/view/4492571619/" and job.easy_apply
    assert job.relative_time == "5 days ago" and (now() - job.posted_at).days == 5
    applied = linkedin.parse_card({"id": "1", "lines": ["Dev", "Dev", "Acme", "Pune (On-site)", "Applied 2 days ago"]}, "x")
    assert applied.easy_apply is False


def test_board_listings_easy_apply_flag():
    import json
    from pathlib import Path

    from jobscout.scrapers import indeed, naukri

    here = Path(__file__).parent
    n = naukri.parse_search(json.loads((here / "fixtures_naukri_search.json").read_text()))
    assert all(j.easy_apply for j in n)       # none of the fixture jobs apply on a company site
    i = indeed.parse_results(json.loads((here / "fixtures_indeed_jobcards.json").read_text())["results"])
    assert sum(j.easy_apply for j in i) == 3  # 3 of 15 are "Easily apply"


def test_cv_facts_fill_gaps_but_the_sheet_wins():
    from jobscout.apply.answers import cv_facts

    cv = "Jane Doe\n+91 98765 43210 | jane@x.io\nhttps://www.linkedin.com/in/jane-doe | https://github.com/janed"
    assert cv_facts(cv) == {"phone": "9876543210", "linkedin_url": "https://www.linkedin.com/in/jane-doe",
                            "portfolio_url": "https://github.com/janed"}
    a = Answerer({"phone": "+91 99999 88888"}, {}, cv)
    assert a.answer(Question("Mobile phone number", "text", [], True)).answer == "9999988888"
    assert a.answer(Question("LinkedIn Profile", "text", [], True)).answer == "https://www.linkedin.com/in/jane-doe"


def test_notice_in_a_text_box_is_just_the_number():
    assert _a("What is your official notice period?", "text", sheet={"notice_period_days": 0}).answer == "0"
