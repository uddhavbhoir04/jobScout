"""Naukri / Indeed parsing (saved live responses, Nov 2026), URL building and search planning."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from jobscout.extract.dates import DateRange
from jobscout.pipeline.boards import BoardFilters, hiring_summary, listing_header, plan_searches, Search
from jobscout.scrapers import indeed, naukri
from jobscout.scrapers.base import JobListing, html_to_text

HERE = Path(__file__).parent
REF = datetime(2026, 11, 25, 15, 0).astimezone()


def _range(days: int) -> DateRange:
    return DateRange(f"last-{days}d", REF - timedelta(days=days), REF)


def _load(name):
    return json.loads((HERE / name).read_text())


# ---------------------------------------------------------------- Naukri
def test_naukri_parse_search():
    jobs = naukri.parse_search(_load("fixtures_naukri_search.json"), "python developer")
    assert len(jobs) == 7
    j = jobs[0]
    assert j.external_id == "241126021673"
    assert j.title == "Python developer +SRE For LTI Mindtree"
    assert j.company == "Intellics Global Services"
    assert (j.experience, j.salary) == ("5-8 Yrs", "15-20 Lacs PA")
    assert j.location == "Pune, Bengaluru, Delhi / NCR"
    assert j.url.startswith("https://www.naukri.com/job-listings-")
    assert j.posted_at is not None and j.relative_time == "1 Day Ago"
    assert j.search_tag == "python developer"
    by_title = {x.title: x for x in jobs}
    assert by_title["Python Software Developer ( AI ML )"].work_mode == "remote"
    assert by_title["Robotics Software Engineer"].work_mode == "hybrid"
    assert by_title["Senior Analytics Engineer - Pune - Rudder Analytics"].salary is None  # "Not disclosed"


def test_naukri_parse_job_detail():
    text, mode = naukri.parse_job(_load("fixtures_naukri_job.json"))
    assert "Python API" in text and "<p>" not in text
    assert "Key skills:" in text
    assert mode == "on-site"  # wfhType "0"


@pytest.mark.parametrize("loc, expected", [
    ("Remote", "remote"), ("Hybrid - Pune, Mumbai", "hybrid"), ("Pune", None), (None, None),
])
def test_naukri_work_mode_from_location(loc, expected):
    assert naukri.work_mode_from_location(loc) == expected


def test_naukri_search_url():
    url = naukri.search_url("Python Developer", "Pune", 3, ["remote", "hybrid"], page=2)
    u = urlparse(url)
    assert u.path == "/python-developer-jobs-in-pune-2"
    q = parse_qs(u.query)
    assert q["jobAge"] == ["3"] and sorted(q["wfhType"]) == ["2", "3"]
    assert "k" not in q and "l" not in q  # with these, Naukri ignores the page number (checked live)
    # all types / none: no work-type filter; no location: India-wide path
    assert "wfhType" not in naukri.search_url("react", None, 1, ["remote", "hybrid", "on-site"])
    assert urlparse(naukri.search_url("react", None, 1, [])).path == "/react-jobs"


def test_naukri_api_page():
    assert naukri.api_page("https://www.naukri.com/jobapi/v3/search?noOfResults=20&pageNo=2&jobAge=3") == 2
    assert naukri.api_page("") is None


@pytest.mark.parametrize("days, age", [(1, 1), (2, 3), (3, 3), (5, 7), (10, 15), (60, 30)])
def test_naukri_job_age(days, age):
    assert naukri.job_age(_range(days), ref=REF) == age
    # the run starts a little after the range was set: still the same filter
    assert naukri.job_age(_range(days), ref=REF + timedelta(seconds=30)) == age


# ---------------------------------------------------------------- Indeed
def test_indeed_parse_results():
    jobs = indeed.parse_results(_load("fixtures_indeed_jobcards.json")["results"], "python developer")
    assert len(jobs) == 15
    j = jobs[0]
    assert (j.external_id, j.title, j.company) == ("fcb16f0aa1f37854", "Full Stack Intern", "WeIntern Pvt Ltd")
    assert j.url == "https://in.indeed.com/viewjob?jk=fcb16f0aa1f37854"
    assert j.location == "Pune, Maharashtra"
    assert j.salary == "₹10,000 - ₹20,000 a month"
    assert j.experience is None
    modes = {x.external_id: x.work_mode for x in jobs}
    assert modes["945f6c65b18d6048"] == "hybrid"
    assert modes["060ffa998683f98f"] == "remote"


def test_indeed_posted_at():
    assert indeed.posted_at({"formattedRelativeTime": "Just posted"}, ref=REF) == REF
    assert indeed.posted_at({"formattedRelativeTime": "3 days ago"}, ref=REF) == REF - timedelta(days=3)
    assert indeed.posted_at({"formattedRelativeTime": "30+ days ago"}, ref=REF) == REF - timedelta(days=30)
    assert indeed.posted_at({"pubDate": 1795500000000}) is not None


def test_indeed_search_url():
    q = parse_qs(urlparse(indeed.search_url("python", None, 3, ["remote"], "date")).query)
    assert q == {"q": ["python"], "sc": [indeed.REMOTE_FILTER], "fromage": ["3"], "sort": ["date"]}
    q = parse_qs(urlparse(indeed.search_url("python", "Pune", None, ["remote", "hybrid"], None)).query)
    assert q == {"q": ["python"], "l": ["Pune"]}


@pytest.mark.parametrize("days, age", [(1, 1), (3, 3), (5, 7), (14, 14), (30, None)])
def test_indeed_from_age(days, age):
    assert indeed.from_age(_range(days), ref=REF) == age
    assert indeed.from_age(_range(days), ref=REF + timedelta(seconds=30)) == age


def test_html_to_text():
    assert html_to_text("<p>Hello&nbsp;<b>world</b></p><ul><li>One</li><li>Two</li></ul>") == "Hello world\n\n• One\n• Two"
    assert html_to_text(None) == ""


# ---------------------------------------------------------------- search planning (location rule)
def test_plan_only_remote_ignores_location():
    assert plan_searches(["python"], "Pune, Mumbai", ["remote"]) == [Search("python", None, ("remote",))]


def test_plan_hybrid_onsite_searches_each_city_only():
    assert plan_searches(["python"], "Pune, Mumbai", ["hybrid", "on-site"]) == [
        Search("python", "Pune", ("hybrid", "on-site")), Search("python", "Mumbai", ("hybrid", "on-site"))]


def test_plan_any_type_adds_a_remote_search_anywhere():
    assert plan_searches(["python", "react"], "Pune", []) == [
        Search("python", "Pune", ()), Search("python", None, ("remote",)),
        Search("react", "Pune", ()), Search("react", None, ("remote",))]


def test_plan_no_location_is_india_wide():
    assert plan_searches(["python"], "", ["hybrid"]) == [Search("python", None, ("hybrid",))]


# ---------------------------------------------------------------- filters on listings
def _job(**kw):
    base = dict(external_id="1", url=None, title="Python Developer", company="Acme")
    return JobListing(**{**base, **kw})


def test_board_filters_location_rule():
    f = BoardFilters(location="Pune", work_types=["hybrid", "on-site"])
    assert f.listing_reason(_job(location="Hybrid - Pune", work_mode="hybrid")) is None
    assert f.listing_reason(_job(location="Chennai")) == "location doesn't match"
    assert f.listing_reason(_job(location="Remote", work_mode="remote")) == "location doesn't match"
    # company names don't count as a location
    assert f.listing_reason(_job(company="Pune Softech", location="Chennai")) == "location doesn't match"

    remote = BoardFilters(location="Pune", work_types=["remote", "hybrid"])
    assert remote.listing_reason(_job(location="Remote", work_mode="remote")) is None
    assert remote.listing_reason(_job(location="Hybrid - Chennai", work_mode="hybrid")) == "location doesn't match"


def test_board_filters_experience_and_work_type():
    f = BoardFilters(exp_min=0, exp_max=3, work_types=["remote"])
    assert f.listing_reason(_job(experience="5-8 Yrs")) == "experience outside your range"
    assert f.listing_reason(_job(experience="0-2 Yrs", work_mode="hybrid", location="Pune")) == "work type doesn't match"
    # Indeed: no experience field, read from the description after the job page is opened
    j = _job(location="Remote", work_mode="remote")
    assert f.listing_reason(j) is None
    j.description = "We need 6+ years of Python"
    assert f.description_reason(j) == "experience outside your range"
    j.description = "Pay a registration fee of Rs 2000"
    assert f.description_reason(j) == "asks for a fee: likely a scam"


def test_summary_and_header():
    j = _job(location="Pune", experience="3-6 Yrs", salary="10 LPA", work_mode="hybrid")
    assert hiring_summary(j) == "Python Developer at Acme | 3-6 Yrs | Pune"
    assert "Work mode: hybrid" in listing_header(j)


def test_naukri_recruiter_details_are_kept():
    body = {"jobDetails": {"description": "<p>Python role</p>",
                           "contactDetails": {"email": "hr@acme.io", "phone": None}, "hrName": "Priya"}}
    text, _ = naukri.parse_job(body)
    assert "Recruiter contact: hr@acme.io | Priya" in text


def test_indeed_search_url_start():
    q = parse_qs(urlparse(indeed.search_url("python", None, 3, [], "date", start=20)).query)
    assert q["start"] == ["20"]
