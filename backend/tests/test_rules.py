"""Rule-based extraction on real-world LinkedIn post wording (tests/fixtures_linkedin_posts.json).

Names, emails and profile links in the fixture are replaced with fictional ones."""
import json
from pathlib import Path

import pytest

from jobscout.extract.rules import is_hiring_post, post_info

POSTS = {p["author"].split(" - ")[0]: p["text"] for p in json.loads(
    (Path(__file__).parent / "fixtures_linkedin_posts.json").read_text(encoding="utf-8"))}


@pytest.mark.parametrize("author,expected", [
    ("Priya Raman", "Back-end Developer (Python) | 5–7 years | Chennai, Tamil Nadu"),
    ("Northwind Labs", "Python developers | 5–6 years"),
    ("HR Arjun Mehta", "Lead Python Full Stack Developer | 8+ Years | Hyderabad"),
])
def test_real_posts_hiring_for(author, expected):
    info = post_info(POSTS[author])
    assert info["is_hiring_post"]
    assert info["hiring_for"] == expected


@pytest.mark.parametrize("text,expected", [
    ("Hiring | SDET (Python) | 3-5 yrs | Remote. DM Rahul Verma",
     {"is_hiring_post": True, "hiring_for": "SDET (Python) | 3-5 yrs", "contact_name": "Rahul Verma"}),
    ("We are hiring for Senior Data Engineer - Bangalore. Share CV to hr@x.com",
     {"is_hiring_post": True, "hiring_for": "Senior Data Engineer", "contact_name": None}),
])
def test_samples(text, expected):
    assert post_info(text) == expected


@pytest.mark.parametrize("text", [
    "#OpenToWork I am looking for a new role as Python dev, mail me a@b.com",
    "I'm actively seeking new opportunities in backend development #hiring",
    "Happy to share I completed my AWS certification! #learning",
])
def test_not_hiring(text):
    assert not is_hiring_post(text)
