"""Indeed "Easily apply" (Indeed Apply).

Search reuses the Indeed scraper (logged-in profile) and keeps jobs with indeedApplyEnabled. On the
job page, "Apply now" opens Indeed's apply flow (smartapply.indeed.com), sometimes in a new tab:
contact info (prefilled from your Indeed profile) -> resume (the one on your Indeed profile is
preselected) -> employer questions -> review -> "Submit your application".

Every selector is at the top of this file. Confirm with a dry run on a logged-in account.
"""
import logging
from collections.abc import Iterator

from playwright.sync_api import BrowserContext, Page

from jobscout.apply import form
from jobscout.apply.base import ApplyOutcome, NeedsYou, Precheck
from jobscout.browser.manager import pause
from jobscout.config import get_settings
from jobscout.db.models import ApplyStatus, Platform
from jobscout.extract.dates import DateRange
from jobscout.scrapers.base import BoardBlocked, JobListing, LoginRequired
from jobscout.scrapers.indeed import IndeedScraper

log = logging.getLogger(__name__)

APPLY_BUTTON = "#indeedApplyButton, button[id*='indeedApply']:has-text('Apply'), button:has-text('Apply now')"
ALREADY_APPLIED = "button:has-text('Applied'), :text('You applied')"
FLOW_HOST = "smartapply.indeed.com"
FORM_ROOT = "main"
RESUME_STEP = "/resume"
CONTINUE = "button:has-text('Continue'), button[data-testid*='continue']"
SUBMIT = "button:has-text('Submit your application'), button:has-text('Submit application')"
SUCCESS = ":text('application has been submitted'), :text('Your application has been submitted'), h1:has-text('submitted')"
MAX_STEPS = 12


class IndeedApplier:
    platform = Platform.indeed

    def __init__(self, ctx: BrowserContext, headless: bool = False):
        self.ctx = ctx
        self.scraper = IndeedScraper(ctx, headless)
        self.page: Page = self.scraper.page
        self.headless = headless

    def ensure_logged_in(self, email: str, password: str, allow_manual: bool) -> bool:
        return self.scraper.ensure_logged_in(email, password, allow_manual)

    def search(self, keyword: str, location: str | None, date_range: DateRange,
               work_types: list[str]) -> Iterator[JobListing]:
        for job in self.scraper.search(keyword, location, date_range, work_types):
            if job.easy_apply:
                yield job

    def apply(self, job: JobListing, answerer, dry_run: bool, precheck: Precheck) -> ApplyOutcome:
        job.description = self.scraper.fetch_description(job) or job.description  # opens the job page
        if reason := precheck(job):
            return ApplyOutcome(ApplyStatus.skipped, reason, filtered=True)
        if self.page.locator(ALREADY_APPLIED).count():
            return ApplyOutcome(ApplyStatus.skipped, "already applied on Indeed")
        button = self.page.locator(APPLY_BUTTON).first
        if not button.count():
            return ApplyOutcome(ApplyStatus.skipped, "no Indeed Apply button (applies on the company site)")

        flow = self._open_flow(button)
        answered = []
        try:
            for _ in range(MAX_STEPS):
                flow.wait_for_load_state("domcontentloaded")
                flow.wait_for_timeout(2_000)
                if "secure.indeed.com" in flow.url:
                    raise LoginRequired("Indeed asked you to sign in again. Log in on the Accounts page.")
                if flow.locator(SUBMIT).count():
                    if dry_run:
                        shot = self._screenshot(flow, job)
                        return ApplyOutcome(ApplyStatus.dry_run, "filled; not submitted (dry run)", answered, shot)
                    flow.locator(SUBMIT).first.click()
                    try:
                        flow.locator(SUCCESS).first.wait_for(timeout=20_000)
                    except Exception:  # noqa: BLE001
                        return ApplyOutcome(ApplyStatus.failed, "Indeed didn't confirm the application", answered)
                    return ApplyOutcome(ApplyStatus.applied, None, answered)
                if RESUME_STEP not in flow.url:   # the resume step: Indeed preselects your profile resume
                    answered += form.fill_step(flow, FORM_ROOT, answerer, answerer.resume_path)
                pause(0.5, 1.2)
                nxt = flow.locator(CONTINUE).first
                if not nxt.count():
                    raise NeedsYou("The form has a step jobscout doesn't recognise.", answered)
                before = flow.url
                nxt.click()
                flow.wait_for_timeout(2_000)
                if flow.url == before and (errs := form.errors(flow, FORM_ROOT)):
                    raise NeedsYou("Indeed rejected an answer: " + "; ".join(errs[:2]), answered)
            raise NeedsYou("The form has more steps than expected.", answered)
        except NeedsYou as e:
            return ApplyOutcome(ApplyStatus.needs_you, str(e), e.questions or answered)
        except (BoardBlocked, LoginRequired):
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Indeed apply failed for %s: %s", job.url, e)
            return ApplyOutcome(ApplyStatus.failed, f"{type(e).__name__}: {str(e)[:200]}", answered)
        finally:
            if flow is not self.page:
                flow.close()

    def _open_flow(self, button) -> Page:
        """Apply now opens the flow in this tab or a new one."""
        try:
            with self.ctx.expect_page(timeout=6_000) as new:
                button.click()
            page = new.value
        except Exception:  # noqa: BLE001 - same tab
            page = self.page
        try:
            page.wait_for_url(f"**{FLOW_HOST}**", timeout=15_000)
        except Exception:  # noqa: BLE001
            pass
        return page

    def _screenshot(self, page: Page, job: JobListing) -> str | None:
        folder = get_settings().data_dir / "apply_screens"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"indeed_{job.external_id}.png"
        try:
            page.screenshot(path=str(path))
            return str(path)
        except Exception:  # noqa: BLE001
            return None
