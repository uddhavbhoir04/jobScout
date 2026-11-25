"""LinkedIn Easy Apply.

Search: linkedin.com/jobs/search-results with the Easy Apply filter (f_AL=true). Each job is
opened by its own URL (/jobs/view/<id>/) to read the description and start Easy Apply. The modal is
walked step by step (Next -> Review -> Submit), every field answered by the Answerer.

Every URL and selector is at the top of this file; checked against the live site in Nov 2026.
"""
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlencode

from playwright.sync_api import BrowserContext, Page

from jobscout.apply import form
from jobscout.apply.base import QA, ApplyOutcome, NeedsYou, Precheck
from jobscout.browser.manager import pause
from jobscout.config import get_settings
from jobscout.db.models import ApplyStatus, Platform
from jobscout.extract.dates import DateRange, now
from jobscout.scrapers.base import BoardBlocked, JobListing, LoginRequired  # noqa: F401

log = logging.getLogger(__name__)

BASE = "https://www.linkedin.com"
SEARCH = f"{BASE}/jobs/search-results/"
JOB = BASE + "/jobs/view/{id}/"
PAGE_SIZE = 25
MAX_PAGES = 8
BLOCKED_MARKERS = ("/login", "/checkpoint", "/authwall", "/uas/login")

# Verified on the live site (Nov 2026, "search-results" layout with generated class names).
CARD = '[componentkey^="job-card-component-ref-"]'
LIST_PANE = '[data-testid="lazy-column"]'
DESCRIPTION = '[data-testid="expandable-text-box"]'
EASY_APPLY_BUTTON = "button[data-view-name='job-apply-button'], button[aria-label^='Easy Apply'], button.jobs-apply-button"
MODAL = "dialog[data-testid='dialog'], [data-view-name='unified-apply'], div.jobs-easy-apply-modal, div[role='dialog']"
NEXT = re.compile(r"^\s*(Next|Continue)\s*$", re.I)
REVIEW = re.compile(r"^\s*Review\b", re.I)
SUBMIT = re.compile(r"^\s*Submit( application)?\s*$", re.I)
NEXT_BY_NAME = "button[data-view-name='continue-unify'], button[aria-label='Continue to next step']"
DISMISS = "button[aria-label='Dismiss']"
DISCARD = "button[data-view-name='discard-application-confirm-btn'], button[data-control-name='discard_application_confirm_btn']"
SENT = re.compile(r"application (was )?sent|your application was submitted|applied to", re.I)
APPLIED_TEXT = re.compile(r"^Applied\b", re.I)
PAGES = re.compile(r"(\d+)\s*/\s*(\d+)\s*pages?", re.I)
RESUME_STEP = re.compile(r"(select or upload a resume|resume is required|upload resume)", re.I)
UPLOAD_RESUME = re.compile(r"^\s*Upload resume\s*$", re.I)
DISCARD_NAME = re.compile(r"^\s*Discard\s*$", re.I)
MAX_RESUME_BYTES = 2 * 1024 * 1024   # LinkedIn's limit
MAX_STEPS = 12

# Job cards on the search page: [{id, lines}] (the card's visible text, line by line)
_CARDS_JS = r"""
(sel) => {
  const seen = new Set(); const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const id = el.getAttribute('componentkey').replace('job-card-component-ref-', '');
    if (!/^\d+$/.test(id) || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, lines: el.innerText.split('\n').map(s => s.trim()).filter(s => s && s !== '·') });
  }
  return out;
}
"""


def time_filter(date_range: DateRange, ref: datetime | None = None) -> str | None:
    """f_TPR=r<seconds> covering the range (exact dates are checked afterwards)."""
    secs = int(((ref or now()) - date_range.start).total_seconds())
    for limit in (86_400, 604_800, 2_592_000):
        if secs <= limit + 3_600:
            return f"r{limit}"
    return None


def search_query(keyword: str, location: str | None, work_types: list[str]) -> str:
    """LinkedIn's search ignores the location / work-type URL filters but understands them in the
    query: "react developer in Pune", "react developer remote". Without a place it would reuse the
    region of your last search, so it's always given."""
    if set(work_types) == {"remote"}:
        return f"{keyword} remote"
    return f"{keyword} in {location or 'India'}"


def search_url(keyword: str, location: str | None, date_range: DateRange, work_types: list[str], page: int = 0) -> str:
    params = [("keywords", search_query(keyword, location, work_types)), ("f_AL", "true")]
    if tpr := time_filter(date_range):
        params.append(("f_TPR", tpr))
    if page:
        params.append(("start", str(page * PAGE_SIZE)))
    return f"{SEARCH}?{urlencode(params)}"


_MODE = re.compile(r"\((remote|hybrid|on-site)\)", re.I)
_AGO = re.compile(r"(\d+)\s*(minute|hour|day|week|month)s?\s+ago|just now|today", re.I)
_UNIT = {"minute": 60, "hour": 3_600, "day": 86_400, "week": 604_800, "month": 2_592_000}


def parse_card(c: dict, keyword: str) -> JobListing:
    """Card lines: title (with "(Verified job)"), title, company, location "(Hybrid)", then salary /
    status / "5 days ago" / "Easy Apply" / "Applied" in any order."""
    lines = [ln for ln in c.get("lines", []) if ln]
    title = lines[1] if len(lines) > 1 else (lines[0] if lines else "LinkedIn job")
    company = lines[2] if len(lines) > 2 else None
    loc = next((ln for ln in lines[3:6] if _MODE.search(ln)), lines[3] if len(lines) > 3 else "")
    m = _MODE.search(loc)
    posted, rel = None, None
    for ln in lines:
        if am := _AGO.search(ln):
            rel = am.group(0)
            posted = now() - timedelta(seconds=int(am.group(1)) * _UNIT[am.group(2).lower()]) if am.group(1) else now()
            break
    applied = any(APPLIED_TEXT.match(ln) for ln in lines)
    return JobListing(
        external_id=c["id"], url=JOB.format(id=c["id"]), title=title, company=company,
        location=_MODE.sub("", loc).strip(" ,") or None, work_mode=m.group(1).lower() if m else None,
        posted_at=posted, relative_time=rel, search_tag=keyword, easy_apply=not applied,
    )


class LinkedInApplier:
    platform = Platform.linkedin

    def __init__(self, ctx: BrowserContext, headless: bool = False):
        self.ctx = ctx
        self.headless = headless
        self.page: Page = ctx.pages[0] if ctx.pages else ctx.new_page()

    def _check_blocked(self) -> None:
        if any(m in self.page.url for m in BLOCKED_MARKERS):
            raise LoginRequired(f"LinkedIn logged you out or asked for a security check ({self.page.url}).")

    def ensure_logged_in(self, email: str, password: str, allow_manual: bool) -> bool:
        from jobscout.scrapers.linkedin import LinkedInScraper

        return LinkedInScraper(self.ctx).ensure_logged_in(email, password, allow_manual)

    # ---------- search ----------
    def search(self, keyword: str, location: str | None, date_range: DateRange,
               work_types: list[str]) -> Iterator[JobListing]:
        for page in range(MAX_PAGES):
            url = search_url(keyword, location, date_range, work_types, page)
            log.info("LinkedIn jobs: %s", url)
            self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            self._check_blocked()
            try:
                self.page.locator(CARD).first.wait_for(timeout=15_000)
            except Exception:  # noqa: BLE001
                log.info("LinkedIn: no Easy Apply jobs on this page.")
                return
            self._load_all_cards()
            cards = self.page.evaluate(_CARDS_JS, CARD)
            if not cards:
                return
            jobs = [parse_card(c, keyword) for c in cards]
            log.info("LinkedIn: %d jobs on page %d.", len(jobs), page + 1)
            # opening a job moves this page away, so the whole list is read first
            yield from jobs
            if len(cards) < PAGE_SIZE:
                return
            pause(2, 4)

    def _load_all_cards(self) -> None:
        """The result list renders cards as it's scrolled."""
        for _ in range(10):
            self.page.evaluate("""(sel) => { const p = document.querySelector(sel); if (p) p.scrollBy(0, 900); }""",
                               LIST_PANE)
            self.page.wait_for_timeout(350)

    # ---------- apply ----------
    def _modal(self):
        """The apply form: the first of MODAL's selectors that's on the page (priority order)."""
        for sel in MODAL.split(","):
            loc = self.page.locator(sel.strip())
            if loc.count():
                return loc.first
        return self.page.locator(MODAL).first

    def _button(self, pattern) -> object | None:
        b = self._modal().get_by_role("button", name=pattern)
        return b.first if b.count() else None

    def apply(self, job: JobListing, answerer, dry_run: bool, precheck: Precheck) -> ApplyOutcome:
        if job.easy_apply is False:
            return ApplyOutcome(ApplyStatus.skipped, "already applied on LinkedIn")
        self.page.goto(job.url, wait_until="domcontentloaded", timeout=60_000)
        self._check_blocked()
        try:
            self.page.locator(f"{EASY_APPLY_BUTTON}, {DESCRIPTION}").first.wait_for(timeout=12_000)
        except Exception:  # noqa: BLE001
            pass
        boxes = self.page.locator(DESCRIPTION)
        texts = [boxes.nth(i).inner_text() for i in range(min(boxes.count(), 4))]
        if texts:
            job.description = max(texts, key=len).strip()
        if reason := precheck(job):
            return ApplyOutcome(ApplyStatus.skipped, reason, filtered=True)
        button = self.page.locator(EASY_APPLY_BUTTON).first
        if not button.count():
            if self.page.get_by_text(APPLIED_TEXT).count():
                return ApplyOutcome(ApplyStatus.skipped, "already applied on LinkedIn")
            return ApplyOutcome(ApplyStatus.skipped, "no Easy Apply button (applies on the company site)")
        button.click()
        try:
            self._modal().wait_for(timeout=12_000)
            self.page.wait_for_timeout(1_500)
        except Exception:  # noqa: BLE001
            return ApplyOutcome(ApplyStatus.failed, "the Easy Apply form didn't open")

        answered = []
        try:
            for _ in range(MAX_STEPS):
                answered += form.fill_step(self.page, MODAL, answerer, answerer.resume_path)
                self._attach_cv_if_missing(answerer, answered)
                self._untick_follow()
                pause(0.6, 1.4)
                submit = self._button(SUBMIT)
                if submit is not None:
                    if dry_run:
                        shot = self._screenshot(job)
                        self._discard()
                        return ApplyOutcome(ApplyStatus.dry_run, "filled; not submitted (dry run)", answered, shot)
                    submit.click()
                    self.page.wait_for_timeout(3_000)
                    sent = bool(self.page.get_by_text(SENT).count()) or not self._modal().count()
                    self._close_modal()
                    if not sent:
                        return ApplyOutcome(ApplyStatus.failed, "LinkedIn didn't confirm the application", answered)
                    return ApplyOutcome(ApplyStatus.applied, None, answered)
                nxt = self._button(REVIEW) or self._button(NEXT)
                if nxt is None and self._modal().locator(NEXT_BY_NAME).count():
                    nxt = self._modal().locator(NEXT_BY_NAME).first
                if nxt is None:
                    raise NeedsYou("The form has a step jobscout doesn't recognise.", answered)
                before = self._step_signature()
                nxt.click()
                self.page.wait_for_timeout(1_800)
                if self._step_signature() == before:  # didn't move on: fix what LinkedIn rejected, once
                    if self._fix_step(answerer, answered):
                        nxt = self._button(REVIEW) or self._button(NEXT) or self._modal().locator(NEXT_BY_NAME).first
                        nxt.click()
                        self.page.wait_for_timeout(1_800)
                    if self._step_signature() == before:
                        errs = form.errors(self.page, MODAL)
                        raise NeedsYou("LinkedIn didn't accept this step"
                                       + (": " + "; ".join(errs[:3]) if errs else "."), answered)
            raise NeedsYou("The form has more steps than expected.", answered)
        except NeedsYou as e:
            self._discard()
            return ApplyOutcome(ApplyStatus.needs_you, str(e), e.questions or answered)
        except (BoardBlocked, LoginRequired):
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("LinkedIn apply failed for %s: %s", job.url, e)
            self._discard()
            return ApplyOutcome(ApplyStatus.failed, f"{type(e).__name__}: {str(e)[:200]}", answered)

    def _fix_step(self, answerer, answered: list) -> bool:
        """After a rejected Next: upload the CV on the resume step, or re-answer the invalid fields."""
        text = self._modal().inner_text()
        if RESUME_STEP.search(text) and not form.read_fields(self.page, MODAL):
            return self._upload_resume(answerer, answered)
        return form.fix_invalid(self.page, MODAL, answerer, answered)

    def _attach_cv_if_missing(self, answerer, answered: list) -> None:
        """On the resume step, upload the CV unless a resume is already attached (a file name shows)."""
        try:
            text = self._modal().inner_text(timeout=3_000)
        except Exception:  # noqa: BLE001
            return
        has_file = re.search(r"\.(pdf|docx?)\b", text, re.I)
        if RESUME_STEP.search(text) and not has_file and answerer.resume_path and Path(answerer.resume_path).is_file():
            try:
                self._upload_resume(answerer, answered)
            except NeedsYou:
                pass   # too big: the step may still accept no resume; if not, Next will say so

    def _upload_resume(self, answerer, answered: list) -> bool:
        path = answerer.resume_path
        if not path or not Path(path).is_file():
            raise NeedsYou("LinkedIn needs a resume: upload your CV under Auto apply → Answers & limits.", answered)
        if Path(path).stat().st_size > MAX_RESUME_BYTES:
            raise NeedsYou("LinkedIn takes resumes under 2 MB: upload a smaller CV under Answers & limits.", answered)
        button = self._button(UPLOAD_RESUME)
        file_input = self._modal().locator("input[type='file']")
        if file_input.count():
            file_input.first.set_input_files(path)
        elif button is not None:
            with self.page.expect_file_chooser(timeout=10_000) as fc:
                button.click()
            fc.value.set_files(path)
        else:
            return False
        self.page.wait_for_timeout(4_000)   # LinkedIn uploads it right away
        answered.append(QA("Resume", Path(path).name, "saved"))
        return True

    def _untick_follow(self) -> None:
        """The review step ticks "Follow <company> to stay up to date" by default (its label isn't
        linked to the box, so it's found by the text next to it)."""
        try:
            box = self._modal().locator("input[type='checkbox']")
            for i in range(box.count()):
                el = box.nth(i)
                text = el.evaluate("""e => { let p = e.parentElement;
                    for (let n = 0; n < 4 && p; n++, p = p.parentElement) { const t = (p.innerText || '').trim(); if (t) return t; }
                    return ''; }""")
                if text.lower().startswith("follow") and el.is_checked():
                    # the input is hidden behind a styled box: click its label like a person would
                    el.evaluate("e => (e.labels && e.labels[0] ? e.labels[0] : e).click()")
                    self.page.wait_for_timeout(300)
        except Exception:  # noqa: BLE001
            pass

    def _step_signature(self) -> str:
        try:
            text = self._modal().inner_text(timeout=3_000)
        except Exception:  # noqa: BLE001
            return ""
        m = PAGES.search(text)
        labels = [q.label for q in form.read_fields(self.page, MODAL)]
        return f"{m.group(0) if m else ''}|{'|'.join(labels)}"

    def _screenshot(self, job: JobListing) -> str | None:
        folder = get_settings().data_dir / "apply_screens"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"linkedin_{job.external_id}.png"
        try:
            self.page.screenshot(path=str(path), full_page=False)
            return str(path)
        except Exception:  # noqa: BLE001
            return None

    def _discard(self) -> None:
        """Close the form without applying. LinkedIn then asks "Save this application?": Discard."""
        try:
            if self._modal().count():
                self.page.keyboard.press("Escape")
            confirm = self.page.get_by_role("button", name=DISCARD_NAME)
            try:
                confirm.first.wait_for(timeout=4_000)
                confirm.first.click()
            except Exception:  # noqa: BLE001 - no confirm: try the X button, then the old selector
                d = self.page.locator(DISMISS)
                if d.count():
                    d.first.click(timeout=3_000)
                if self.page.locator(DISCARD).count():
                    self.page.locator(DISCARD).first.click(timeout=3_000)
            self.page.wait_for_timeout(1_000)
        except Exception:  # noqa: BLE001
            pass

    def _close_modal(self) -> None:
        try:
            if self._modal().count():
                d = self._modal().locator(DISMISS)
                (d.first.click if d.count() else lambda **_: self.page.keyboard.press("Escape"))(timeout=3_000)
        except Exception:  # noqa: BLE001
            pass
