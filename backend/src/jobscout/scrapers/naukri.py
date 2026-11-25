"""Naukri.com job search, logged in (with an account from the Accounts page) or as a guest.

The search page loads its results from Naukri's own JSON API (/jobapi/v3/search) and the job
page from /jobapi/v4/job/<id>. We open the normal pages in a real browser and read those JSON
responses, so Naukri's request signing stays their problem. Naukri blocks headless browsers
("Access Denied"), so runs need the visible browser.

Every URL, endpoint and selector lives at the top of this file: a Naukri change is a one-file fix.
Verified against the live site Nov 2026.
"""
import logging
import re
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from math import ceil
from urllib.parse import urlencode

from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import TimeoutError as PWTimeout

from jobscout.browser.manager import pause
from jobscout.db.models import Platform
from jobscout.extract.dates import DateRange, now
from jobscout.scrapers.base import BoardBlocked, JobListing, html_to_text

log = logging.getLogger(__name__)

BASE = "https://www.naukri.com"
SEARCH_API = "/jobapi/v3/search"
JOB_API = "/jobapi/v4/job/"
JD_SELECTORS = ("[class*='JDC__dang-inner-html']", "section[class*='job-desc']")
PAGE_SIZE = 20
MAX_PAGES = 25                 # most jobs are skipped (no email), so search deep
JOB_AGES = (1, 3, 7, 15, 30)          # the values Naukri's "Freshness" filter accepts (days)
WFH_TYPE = {"on-site": "0", "remote": "2", "hybrid": "3"}
WFH_NAME = {v: k for k, v in WFH_TYPE.items()}
ALL_TYPES = set(WFH_TYPE)
BLOCKED_TITLES = ("access denied",)
LOGIN_URL = f"{BASE}/nlogin/login"
LOGIN_EMAIL, LOGIN_PASSWORD = "#usernameField", "#passwordField"
LOGIN_SUBMIT = "button[type=submit]:text-is('Login')"   # not "Use OTP to Login"
LOGIN_PAGE_MARKER = "/nlogin/"
CHECK_URL = f"{BASE}/python-jobs?jobAge=1"   # any search: its JSON says whether we're logged in
MANUAL_LOGIN_TIMEOUT_S = 5 * 60


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def job_age(date_range: DateRange, ref: datetime | None = None) -> int:
    """Smallest Naukri freshness filter that still covers the range (exact dates are checked later)."""
    # 1h slack: the range is set a moment before the search runs ("last 7 days" must stay 7, not 8)
    days = max(1, ceil(((ref or now()) - date_range.start - timedelta(hours=1)).total_seconds() / 86400))
    return next((a for a in JOB_AGES if a >= days), JOB_AGES[-1])


def search_url(keyword: str, location: str | None, age: int, work_types: list[str], page: int = 1) -> str:
    """https://www.naukri.com/python-developer-jobs-in-pune-2?jobAge=3&wfhType=2

    Keyword and city go in the path only: with k= / l= query params Naukri ignores the page number."""
    path = f"{_slug(keyword)}-jobs" + (f"-in-{_slug(location)}" if location else "")
    if page > 1:
        path += f"-{page}"
    params: list[tuple[str, str]] = [("jobAge", str(age))]
    wanted = {t for t in work_types if t in WFH_TYPE}
    if wanted and wanted != ALL_TYPES:
        params += [("wfhType", WFH_TYPE[t]) for t in sorted(wanted)]
    return f"{BASE}/{path}?{urlencode(params)}"


def api_page(api_url: str) -> int | None:
    m = re.search(r"[?&]pageNo=(\d+)", api_url or "")
    return int(m.group(1)) if m else None


def work_mode_from_location(label: str | None) -> str | None:
    """Naukri writes the mode into the location: 'Remote', 'Hybrid - Pune, Mumbai'."""
    low = (label or "").strip().lower()
    if low.startswith("remote") or low in ("work from home", "wfh"):
        return "remote"
    if low.startswith("hybrid"):
        return "hybrid"
    return None


def _epoch_ms(v) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v) / 1000).astimezone()
    except (TypeError, ValueError, OSError):
        return None


def parse_search(body: dict, keyword: str = "") -> list[JobListing]:
    out = []
    for j in body.get("jobDetails") or []:
        if not j.get("jobId") or not j.get("title"):
            continue
        ph = {p.get("type"): p.get("label") for p in j.get("placeholders") or []}
        location = ph.get("location")
        salary = ph.get("salary")
        jd_url = j.get("jdURL") or ""
        out.append(JobListing(
            external_id=str(j["jobId"]),
            url=jd_url if jd_url.startswith("http") else (BASE + jd_url if jd_url else None),
            title=j["title"].strip(),
            company=(j.get("companyName") or "").strip() or None,
            location=location,
            experience=ph.get("experience") or j.get("experienceText"),
            salary=None if not salary or salary.lower() == "not disclosed" else salary,
            work_mode=work_mode_from_location(location),
            posted_at=_epoch_ms(j.get("createdDate")),
            relative_time=j.get("footerPlaceholderLabel"),
            description=html_to_text(j.get("jobDescription")),
            search_tag=keyword,
            easy_apply=not j.get("companyApplyJob"),   # True = "Apply on company site"
        ))
    return out


def _strings(v) -> list[str]:
    """Every non-empty string inside a JSON value (the recruiter block's shape varies)."""
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    return []


def parse_job(body: dict) -> tuple[str, str | None]:
    """(full description, work mode) from the job page's JSON."""
    d = body.get("jobDetails") or {}
    parts = [html_to_text(d.get("description"))]
    skills = [s.get("label") for group in (d.get("keySkills") or {}).values() if isinstance(group, list)
              for s in group if isinstance(s, dict) and s.get("label")]
    if skills:
        parts.append("Key skills: " + ", ".join(skills))
    # Logged in, Naukri sometimes shows the recruiter: keep it so emails / names get picked up.
    recruiter = _strings(d.get("contactDetails")) + _strings(d.get("hrName"))
    if recruiter:
        parts.append("Recruiter contact: " + " | ".join(dict.fromkeys(recruiter)))
    return "\n\n".join(p for p in parts if p), WFH_NAME.get(str(d.get("wfhType")))


class NaukriScraper:
    platform = Platform.naukri

    def __init__(self, ctx: BrowserContext, headless: bool = False):
        self.ctx = ctx
        self.headless = headless
        self.page: Page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.last_api_url = ""

    def _open(self, url: str, api: str) -> dict | None:
        """Load a Naukri page and return the JSON of the API call it makes (None if it made none).
        The API call's URL is kept in self.last_api_url."""
        try:
            with self.page.expect_response(lambda r: api in r.url and r.request.method == "GET",
                                           timeout=30_000) as resp:
                self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            r = resp.value
            self.last_api_url = r.url
            return r.json() if r.ok else None
        except PWTimeout:
            self._check_blocked()
            return None
        except Exception as e:  # noqa: BLE001 - bad JSON / navigation error: treat as no data
            log.warning("Naukri: couldn't read %s (%s)", url, e)
            self._check_blocked()
            return None

    def _check_blocked(self) -> None:
        try:
            title = self.page.title().lower()
        except Exception:  # noqa: BLE001
            return
        if any(t in title for t in BLOCKED_TITLES):
            hint = " Turn on “Show browser”: Naukri blocks hidden browsers." if self.headless else ""
            raise BoardBlocked("Naukri refused the browser (Access Denied)." + hint)

    # ---------- login ----------
    def is_logged_in(self) -> bool:
        body = self._open(CHECK_URL, SEARCH_API)
        return bool(body and body.get("isLoggedIn"))

    def ensure_logged_in(self, email: str, password: str, allow_manual: bool) -> bool:
        """Uses the saved session when there is one, else fills the login form. With the browser
        visible, waits up to 5 minutes for the user to finish (OTP, captcha) in the window."""
        if self.is_logged_in():
            return True
        log.info("Logging in to Naukri as %s", email)
        self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
        self._check_blocked()
        try:
            self.page.fill(LOGIN_EMAIL, email, timeout=15_000)
            pause(0.5, 1.5)
            if password:
                self.page.fill(LOGIN_PASSWORD, password)
                pause(0.5, 1.5)
                self.page.click(LOGIN_SUBMIT)
        except PWTimeout:
            log.warning("Naukri login form not found.")
        deadline = time.monotonic() + (MANUAL_LOGIN_TIMEOUT_S if allow_manual else 20)
        while time.monotonic() < deadline and LOGIN_PAGE_MARKER in self.page.url:
            self.page.wait_for_timeout(2_000)
        pause(1, 2)
        return self.is_logged_in()

    # ---------- search ----------
    def search(self, keyword: str, location: str | None, date_range: DateRange,
               work_types: list[str]) -> Iterator[JobListing]:
        age = job_age(date_range)
        for page in range(1, MAX_PAGES + 1):
            url = search_url(keyword, location, age, work_types, page)
            log.info("Naukri: %s", url)
            body = self._open(url, SEARCH_API)
            if not body:
                return
            if page > 1 and api_page(self.last_api_url) != page:
                log.warning("Naukri served page %s instead of %d; stopping this search.",
                            api_page(self.last_api_url), page)
                return
            jobs = parse_search(body, keyword)
            if not jobs:
                return
            yield from jobs
            total = int(body.get("noOfJobs") or 0)
            if page * PAGE_SIZE >= total:
                return
            pause(2, 4)

    def fetch_description(self, listing: JobListing) -> str:
        if not listing.url:
            return listing.description
        body = self._open(listing.url, JOB_API + listing.external_id)
        text, mode = parse_job(body) if body else ("", None)
        if mode and not listing.work_mode:
            listing.work_mode = mode
        if not text:
            for sel in JD_SELECTORS:
                el = self.page.locator(sel).first
                try:
                    if el.count():
                        text = el.inner_text(timeout=5_000).strip()
                        break
                except Exception:  # noqa: BLE001
                    continue
        pause(1, 2.5)
        return text or listing.description
