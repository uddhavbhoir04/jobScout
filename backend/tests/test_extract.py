from datetime import datetime, timedelta, timezone

import pytest

from jobscout.extract.ai import fallback_post_info
from jobscout.extract.contacts import (
    find_contact_name,
    find_emails,
    find_phones,
    hashtags_in,
    qualifies,
)
from jobscout.extract.dates import parse_relative, relative_bounds, resolve
from jobscout.pipeline.scrape import normalise_tags

POST = """We're #Hiring a Python Developer (3+ yrs) in Pune! #hiringforpython
Send your resume to Careers.Team@Acme.io or call +91 98765 43210.
DM Priya Sharma for details."""


def test_emails_lowercased_and_deduped():
    assert find_emails(POST + " careers.team@acme.io") == ["careers.team@acme.io"]


def test_obfuscated_email():
    assert find_emails("mail me: rahul [at] acme [dot] com") == ["rahul@acme.com"]
    assert find_emails("rahul (at) acme (dot) co") == ["rahul@acme.co"]


def test_image_filename_not_email():
    assert find_emails("logo@2x.png") == []


def test_phones_e164():
    assert find_phones(POST, "IN") == ["+919876543210"]
    assert find_phones("call 9876543210", "IN") == ["+919876543210"]
    assert find_phones("call (415) 555-2671", "US") == ["+14155552671"]


def test_contact_name():
    assert find_contact_name(POST) == "Priya Sharma"
    assert find_contact_name("Please DM me for details") is None
    assert find_contact_name("POC: Rahul Verma") == "Rahul Verma"
    assert find_contact_name("send your CV to Anita") == "Anita"


@pytest.mark.parametrize("raw,clean", [
    ("HR Srinivasan - Premium MNC Job Consultancy  INDIA l USA", "Srinivasan"),
    ("Tanushri Kale", "Tanushri Kale"),
    ("Priya Sharma | Talent Acquisition", "Priya Sharma"),
    ("Dr. Anil Kumar (He/Him)", "Anil Kumar"),
    ("AICEA", "AICEA"),
    (None, None),
])
def test_clean_person_name(raw, clean):
    from jobscout.extract.contacts import clean_person_name

    assert clean_person_name(raw) == clean


def test_qualifies():
    assert qualifies(["a@b.co"], None)
    assert qualifies([], "Priya")
    assert not qualifies([], None)
    assert not qualifies([], "  ")


def test_hashtags_in():
    assert hashtags_in(POST, ["#hiring", "#hiringforpython", "#java"]) == ["#hiring", "#hiringforpython"]
    assert hashtags_in("#hiringnow", ["#hiring"]) == []


def test_fallback_post_info():
    info = fallback_post_info(POST)
    assert info.is_hiring_post
    assert info.hiring_for == "Python Developer (3+ yrs)"
    assert info.contact_name == "Priya Sharma"
    assert not fallback_post_info("#OpenToWork looking for a new job, email me x@y.com").is_hiring_post


def test_normalise_tags_dedupes():
    tags = normalise_tags(["#Hiring, hiringforpython  #hiring #java"])
    assert tags == ["#hiring", "#hiringforpython", "#java"]


REF = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)


def test_parse_relative():
    assert parse_relative("5h • Edited •", REF) == REF - timedelta(hours=5)
    assert parse_relative("2d •", REF) == REF - timedelta(days=2)
    assert parse_relative("3mo", REF) == REF - timedelta(days=90)
    assert parse_relative("Promoted", REF) is None


@pytest.mark.parametrize("rel,today,yesterday,dby", [
    ("5h", True, False, False),
    ("1d", False, True, True),     # 24-48h ago: could be either day
    ("3d", False, False, False),
])
def test_presets_overlap(rel, today, yesterday, dby):
    b = relative_bounds(rel, REF)
    assert resolve("today", ref=REF).overlaps(*b) is today
    assert resolve("yesterday", ref=REF).overlaps(*b) is yesterday
    assert resolve("day-before-yesterday", ref=REF).overlaps(*b) is dby


def test_linkedin_params():
    assert resolve("today", ref=REF).linkedin_params(REF) == ["past-24h", "past-week", "past-month", None]
    assert resolve("yesterday", ref=REF).linkedin_params(REF) == ["past-week", "past-month", None]
    assert resolve("last-30d", ref=REF).linkedin_params(REF) == ["past-month", None]


def test_linkedin_search_url_matches_working_format():
    from jobscout.scrapers.linkedin import LinkedInScraper

    assert LinkedInScraper.search_url("#pythonhiring", "past-week") == (
        "https://www.linkedin.com/search/results/content/?keywords=%23pythonhiring&origin=FACETED_SEARCH"
        "&sortBy=%5B%22date_posted%22%5D&datePosted=%5B%22past-week%22%5D"
    )


def test_today_is_rolling_24h_so_it_works_just_after_midnight():
    from datetime import datetime
    ref = datetime(2026, 11, 14, 0, 2, tzinfo=REF.tzinfo)  # 00:02: a calendar day would be 2 minutes long
    today = resolve("today", ref=ref)
    assert today.overlaps(*relative_bounds("5h", ref))
    assert not today.overlaps(*relative_bounds("1d", ref))


def test_last_24h_uses_linkedins_past_24h_filter_even_a_bit_later():
    from datetime import timedelta
    rng = resolve("today", ref=REF)
    assert rng.linkedin_params(REF + timedelta(seconds=5))[0] == "past-24h"
    assert rng.linkedin_params(REF + timedelta(minutes=30))[0] == "past-24h"
