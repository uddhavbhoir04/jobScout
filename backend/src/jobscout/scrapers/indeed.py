"""Indeed India (in.indeed.com) job search, logged in (account from the Accounts page) or as a guest.

Results come from the JSON the search page embeds (window.mosaic.providerData). Logged in, a
search is read page by page (newest first). Logged out, Indeed only shows the first page (~15 jobs):
page 2 sends you to sign-in, so the search is run twice instead, newest first and by relevance.

Indeed sits behind Cloudflare. With the browser visible, a human check can be clicked through
(we wait up to 2 minutes); hidden, the run stops with a message. Cookies are kept in the profile.

Every URL, key and selector lives at the top of this file. Verified against the live site Nov 2026.
"""
import logging
import re
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from math import ceil
from urllib.parse import urlencode

from playwright.sync_api import BrowserContext, Page

from jobscout.browser.manager import pause
from jobscout.db.models import Platform
from jobscout.extract.dates import DateRange, now
from jobscout.scrapers.base import BoardBlocked, JobListing, html_to_text

log = logging.getLogger(__name__)

BASE = "https://in.indeed.com"
FROM_AGES = (1, 3, 7, 14)                # "Date posted" values Indeed accepts (days)
REMOTE_FILTER = "0kf:attr(DSQF7);"       # Indeed's "Remote" attribute
SORTS = ("date", None)                   # None = relevance (Indeed's default)
DESCRIPTION_SELECTORS = (".simple-job-description-html", "#jobDescriptionText",
                         "[data-testid='jobsearch-JobComponent-description']")
CHALLENGE_TITLES = ("just a moment", "security check", "attention required", "verify")
SIGN_IN_MARKERS = ("secure.indeed.com", "/account/login", "/auth")
HUMAN_CHECK_WAIT_S = 120
PAGE_SIZE = 10                           # Indeed's `start` step
MAX_PAGES = 15                           # logged in only
LOGIN_URL = "https://secure.indeed.com/auth?hl=en_IN&co=IN&continue=https%3A%2F%2Fin.indeed.com%2F"
LOGIN_EMAIL = "input[name='__email'], input[type='email']"
LOGIN_PASSWORD = "input[type='password']"
LOGIN_SUBMIT = "button[type='submit']"
CHECK_URL = f"{BASE}/jobs?q=python&fromage=1"   # any search: its data says whether we're logged in
MANUAL_LOGIN_TIMEOUT_S = 5 * 60
WORK_MODEL = {"REMOTE_ALWAYS": "remote", "REMOTE_HYBRID": "hybrid"}

_CARDS_JS = """
() => {
  try {
    const m = window.mosaic.providerData["mosaic-provider-jobcards"].metaData.mosaicProviderJobCardsModel;
    return { results: m.results || [], loggedIn: !!m.loggedIn };
  } catch (e) { return null; }
}
"""


def from_age(date_range: DateRange, ref: datetime | None = None) -> int | None:
    """Smallest Indeed 'date posted' filter that covers the range; None = no filter (older than 14 days)."""
    # 1h slack: the range is set a moment before the search runs ("last 7 days" must stay 7, not 8)
    days = max(1, ceil(((ref or now()) - date_range.start - timedelta(hours=1)).total_seconds() / 86400))
    return next((a for a in FROM_AGES if a >= days), None)


def search_url(keyword: str, location: str | None, age: int | None, work_types: list[str],
               sort: str | None, start: int = 0) -> str:
    params: list[tuple[str, str]] = [("q", keyword)]
    if location:
        params.append(("l", location))
    if set(work_types) == {"remote"}:
        params.append(("sc", REMOTE_FILTER))
    if age:
        params.append(("fromage", str(age)))
    if sort:
        params.append(("sort", sort))
    if start:
        params.append(("start", str(start)))
    return f"{BASE}/jobs?{urlencode(params)}"


_REL = re.compile(r"(\d+)\+?\s*days?\s+ago", re.I)


def posted_at(job: dict, ref: datetime | None = None) -> datetime | None:
    """'Just posted' / 'Today' / '3 days ago' first (it's what Indeed shows), else the publish date."""
    ref = ref or now()
    rel = (job.get("formattedRelativeTime") or "").strip().lower()
    if rel in ("just posted", "today"):
        return ref
    if m := _REL.search(rel):
        return ref - timedelta(days=int(m.group(1)))
    for key in ("pubDate", "createDate"):
        if job.get(key):
            try:
                return datetime.fromtimestamp(int(job[key]) / 1000).astimezone()
            except (TypeError, ValueError, OSError):
                pass
    return None


def work_mode(job: dict) -> str | None:
    model = (job.get("remoteWorkModel") or {}).get("type")
    if model in WORK_MODEL:
        return WORK_MODEL[model]
    if job.get("remoteLocation") or (job.get("formattedLocation") or "").strip().lower() == "remote":
        return "remote"
    return None


def parse_results(results: list[dict], keyword: str = "") -> list[JobListing]:
    out = []
    for j in results or []:
        jk = j.get("jobkey")
        title = (j.get("displayTitle") or j.get("title") or "").strip()
        if not jk or not title:
            continue
        out.append(JobListing(
            external_id=jk,
            url=f"{BASE}/viewjob?jk={jk}",
            title=title,
            company=(j.get("company") or "").strip() or None,
            location=(j.get("formattedLocation") or "").strip() or None,
            experience=None,  # Indeed doesn't have a field for it; read from the description
            salary=((j.get("salarySnippet") or {}).get("text") or None),
            work_mode=work_mode(j),
            posted_at=posted_at(j),
            relative_time=j.get("formattedRelativeTime"),
            description=html_to_text(j.get("snippet")),
            search_tag=keyword,
            easy_apply=bool(j.get("indeedApplyEnabled")),   # "Easily apply"
        ))
    return out


class IndeedScraper:
    platform = Platform.indeed

    def __init__(self, ctx: BrowserContext, headless: bool = False):
        self.ctx = ctx
        self.headless = headless
        self.page: Page = ctx.pages[0] if ctx.pages else ctx.new_page()

    def _goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self._pass_human_check()

    def _is_challenge(self) -> bool:
        try:
            title = self.page.title().lower()
        except Exception:  # noqa: BLE001
            return False
        return any(t in title for t in CHALLENGE_TITLES)

    def _pass_human_check(self) -> None:
        if not self._is_challenge():
            return
        if self.headless:
            raise BoardBlocked("Indeed asked for a human check. Turn on “Show browser” and run again: "
                               "once you've passed it, later runs reuse the cookie.")
        log.warning("Indeed is showing a human check: complete it in the browser window (waiting up to 2 minutes).")
        deadline = time.monotonic() + HUMAN_CHECK_WAIT_S
        while time.monotonic() < deadline:
            self.page.wait_for_timeout(2_000)
            if not self._is_challenge():
                self.page.wait_for_load_state("domcontentloaded")
                return
        raise BoardBlocked("Indeed's human check wasn't completed in time.")

    def _signed_out_wall(self) -> bool:
        return any(m in self.page.url for m in SIGN_IN_MARKERS)

    def _cards(self, url: str) -> dict | None:
        """Open a search page; its job cards + login state, or None (sign-in wall / no data)."""
        log.info("Indeed: %s", url)
        self._goto(url)
        if self._signed_out_wall():
            log.warning("Indeed asked to sign in for %s.", url)
            return None
        self.page.wait_for_timeout(1_500)
        data = self.page.evaluate(_CARDS_JS)
        if not data:
            log.warning("Indeed: no results data on %s", self.page.url)
        return data

    # ---------- login ----------
    def is_logged_in(self) -> bool:
        data = self._cards(CHECK_URL)
        return bool(data and data.get("loggedIn"))

    def ensure_logged_in(self, email: str, password: str, allow_manual: bool) -> bool:
        """Uses the saved session when there is one. Otherwise fills the email (and the password,
        if Indeed asks for one and it was given); Indeed usually emails a code, which the user
        types in the visible browser window (we wait up to 5 minutes)."""
        if self.is_logged_in():
            return True
        if not allow_manual:
            log.warning("Indeed login needs the browser window (Indeed sends a code by email).")
            return False
        log.info("Logging in to Indeed as %s", email)
        self._goto(LOGIN_URL)
        try:
            self.page.fill(LOGIN_EMAIL, email, timeout=15_000)
            pause(0.5, 1.5)
            self.page.locator(LOGIN_SUBMIT).first.click()
        except Exception:  # noqa: BLE001 - the user can still log in by hand
            log.warning("Indeed login form not found: log in by hand in the browser window.")
        deadline = time.monotonic() + MANUAL_LOGIN_TIMEOUT_S
        filled_password = False
        while time.monotonic() < deadline and "secure.indeed.com" in self.page.url:
            if password and not filled_password:
                pw = self.page.locator(LOGIN_PASSWORD).first
                try:
                    if pw.count() and pw.is_visible():
                        pw.fill(password)
                        pause(0.5, 1.0)
                        self.page.locator(LOGIN_SUBMIT).first.click()
                        filled_password = True
                except Exception:  # noqa: BLE001
                    pass
            self.page.wait_for_timeout(2_000)
        pause(1, 2)
        return self.is_logged_in()

    # ---------- search ----------
    def search(self, keyword: str, location: str | None, date_range: DateRange,
               work_types: list[str]) -> Iterator[JobListing]:
        age = from_age(date_range)
        data = self._cards(search_url(keyword, location, age, work_types, SORTS[0]))
        if not data:
            return
        if data.get("loggedIn"):
            # Logged in: newest first, page after page.
            for page in range(1, MAX_PAGES + 1):
                jobs = parse_results(data["results"], keyword)
                if not jobs:
                    return
                yield from jobs
                if len(data["results"]) < PAGE_SIZE or page == MAX_PAGES:
                    return
                pause(2, 4)
                data = self._cards(search_url(keyword, location, age, work_types, SORTS[0], start=page * PAGE_SIZE))
                if not data:
                    return
            return
        # Guest: one page each, newest first and by relevance.
        yield from parse_results(data["results"], keyword)
        for sort in SORTS[1:]:
            pause(2, 4)
            data = self._cards(search_url(keyword, location, age, work_types, sort))
            if not data:
                return
            yield from parse_results(data["results"], keyword)

    def fetch_description(self, listing: JobListing) -> str:
        if not listing.url:
            return listing.description
        self._goto(listing.url)
        text = ""
        try:
            self.page.locator(", ".join(DESCRIPTION_SELECTORS)).first.wait_for(timeout=10_000)
        except Exception:  # noqa: BLE001 - fall through to the snippet
            pass
        for sel in DESCRIPTION_SELECTORS:
            el = self.page.locator(sel).first
            try:
                if el.count() and (text := el.inner_text(timeout=5_000).strip()):
                    break
            except Exception:  # noqa: BLE001
                continue
        pause(1, 2.5)
        return text or listing.description
