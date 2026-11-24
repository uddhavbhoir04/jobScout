"""Experience, location and work-type filters. Posts that don't say are always kept."""
import pytest

from jobscout.extract.rules import detect_work_types, location_ok, work_type_ok
from jobscout.pipeline.scrape import PostFilters


# ---------------------------------------------------------------- location
def test_location_matches_any_term_as_whole_word():
    assert location_ok("📍 Location: Pune, Maharashtra", "Bangalore, Pune")
    assert location_ok("Join our Hyderabad office", "hyderabad")


def test_location_rejects_a_stated_location_that_does_not_match():
    assert not location_ok("Location: Chennai, Tamil Nadu", "Pune, Bangalore")


def test_location_rejects_posts_without_a_location():
    assert not location_ok("We are hiring a Python developer, DM me", "Pune")


def test_location_keeps_remote_posts():
    assert location_ok("Location: Chennai (Remote)", "Pune")
    assert location_ok("Fully remote role, DM me", "Pune")


def test_location_is_not_a_substring_match():
    assert not location_ok("Location: Punekar Nagar", "pune")


def test_location_empty_filter_keeps_everything():
    assert location_ok("Location: Chennai", "")
    assert location_ok("Location: Chennai", None)
    assert location_ok("Location: Chennai", " , ")


# ---------------------------------------------------------------- work type
@pytest.mark.parametrize("text, expected", [
    ("This is a fully remote role", {"remote"}),
    ("WFH available", {"remote"}),
    ("Work from home", {"remote"}),
    ("Hybrid - 3 days in office", {"hybrid"}),
    ("Mode: On-site", {"on-site"}),
    ("on site in Pune", {"on-site"}),
    ("Work from office, WFO only", {"on-site"}),
    ("Strictly no remote", set()),
    ("Python developer needed", set()),
])
def test_detect_work_types(text, expected):
    assert detect_work_types(text) == expected


def test_work_type_filter():
    assert work_type_ok("Remote role", ["remote"])
    assert work_type_ok("Remote role", ["hybrid", "remote"])
    assert not work_type_ok("Remote role", ["on-site"])
    assert work_type_ok("Work from office", ["onsite"])  # spelling variants accepted
    assert work_type_ok("No work mode mentioned", ["remote"])  # unknown is kept
    assert work_type_ok("Work from office", [])
    assert work_type_ok("Work from office", ["remote", "hybrid", "on-site"])


# ---------------------------------------------------------------- combined (LinkedIn pipeline)
def test_post_filters_reject_reason():
    f = PostFilters(exp_min=0, exp_max=3, location="Pune", work_types=["remote", "hybrid"])
    assert f.reject_reason("Experience: 1-3 years. Location: Pune. Hybrid.") is None
    assert f.reject_reason("Experience: 2-4 years. Location: Pune.") == "experience outside your range"
    assert f.reject_reason("Remote role, 2 years") is None
    assert f.reject_reason("Experience: 6-10 years") == "experience outside your range"
    assert f.reject_reason("Location: Chennai") == "location doesn't match"
    assert f.reject_reason("Work from office in Pune") == "work type doesn't match"
    assert PostFilters().reject_reason("anything") is None


def test_linkedin_run_needs_a_role_hashtag():
    from jobscout.extract.dates import resolve
    from jobscout.pipeline.scrape import run_scrape

    with pytest.raises(ValueError, match="role hashtag"):
        run_scrape(user_id=1, platform="linkedin", tags=["#hiring"], date_range=resolve("last-7d"), limit=5)
