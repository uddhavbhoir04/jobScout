"""Naukri "Apply" (jobs that apply on Naukri itself, not on a company site).

Search reuses the Naukri scraper (logged-in profile) and keeps jobs with companyApplyJob = false.
On the job page, Apply sends your Naukri profile at once; some recruiters add a questionnaire, which
Naukri shows as a chat drawer: one question at a time, answered by typing or picking a chip.

A dry run can't fill the questionnaire without applying (it only appears after Apply), so it stops
before clicking Apply.

Every selector is at the top of this file. Confirm with a dry run on a logged-in account.
"""
import logging
from collections.abc import Iterator

from playwright.sync_api import BrowserContext

from jobscout.apply.base import QA, ApplyOutcome, NeedsYou, Precheck, Question
from jobscout.browser.manager import pause
from jobscout.config import get_settings
from jobscout.db.models import ApplyStatus, Platform
from jobscout.extract.dates import DateRange
from jobscout.scrapers.base import BoardBlocked, JobListing, LoginRequired
from jobscout.scrapers.naukri import NaukriScraper

log = logging.getLogger(__name__)

APPLY_BUTTON = "#apply-button, button.apply-button:has-text('Apply')"
COMPANY_SITE_BUTTON = "#company-site-button, button:has-text('Apply on company site')"
ALREADY_APPLIED = "#already-applied, button:has-text('Applied'), span:text-is('Applied')"
SUCCESS = ":text('successfully applied'), :text('Applied to'), [class*='apply-status-header']:has-text('Applied')"
CHAT = "[class*='chatbot_Drawer'], [class*='chatbot_DrawerContentWrapper']"
CHAT_LAST_QUESTION = "[class*='botMsg'] >> nth=-1"
CHAT_INPUT = "[class*='chatbot_Drawer'] [contenteditable='true'], [class*='chatbot_Drawer'] input[type='text']"
CHAT_CHIPS = "[class*='chatbot_Drawer'] [class*='chatbot_Chip'], [class*='chatbot_Drawer'] [class*='ssrc__radio-btn-container'] label"
CHAT_CHECKBOXES = "[class*='chatbot_Drawer'] [class*='mcc__label'], [class*='chatbot_Drawer'] input[type='checkbox'] + label"
CHAT_SAVE = "[class*='chatbot_Drawer'] [class*='sendMsg'], [class*='chatbot_Drawer'] button:has-text('Save')"
MAX_QUESTIONS = 20


class NaukriApplier:
    platform = Platform.naukri

    def __init__(self, ctx: BrowserContext, headless: bool = False):
        self.scraper = NaukriScraper(ctx, headless)
        self.page = self.scraper.page
        self.headless = headless

    def ensure_logged_in(self, email: str, password: str, allow_manual: bool) -> bool:
        return self.scraper.ensure_logged_in(email, password, allow_manual)

    def search(self, keyword: str, location: str | None, date_range: DateRange,
               work_types: list[str]) -> Iterator[JobListing]:
        for job in self.scraper.search(keyword, location, date_range, work_types):
            if job.easy_apply is not False:
                yield job

    def apply(self, job: JobListing, answerer, dry_run: bool, precheck: Precheck) -> ApplyOutcome:
        job.description = self.scraper.fetch_description(job) or job.description  # opens the job page
        if reason := precheck(job):
            return ApplyOutcome(ApplyStatus.skipped, reason, filtered=True)
        if "nlogin" in self.page.url:
            raise LoginRequired("Naukri logged you out. Log in again on the Accounts page.")
        self.page.wait_for_timeout(1_500)
        if self.page.locator(ALREADY_APPLIED).count():
            return ApplyOutcome(ApplyStatus.skipped, "already applied on Naukri")
        if self.page.locator(COMPANY_SITE_BUTTON).count() and not self.page.locator(APPLY_BUTTON).count():
            return ApplyOutcome(ApplyStatus.skipped, "applies on the company site")
        button = self.page.locator(APPLY_BUTTON).first
        if not button.count():
            return ApplyOutcome(ApplyStatus.skipped, "no Apply button")
        if dry_run:
            return ApplyOutcome(ApplyStatus.dry_run, "ready to apply; not clicked (dry run: Naukri applies on click)",
                                [], self._screenshot(job))
        button.click()
        self.page.wait_for_timeout(2_500)
        answered: list[QA] = []
        try:
            for _ in range(MAX_QUESTIONS):
                if self.page.locator(SUCCESS).count():
                    return ApplyOutcome(ApplyStatus.applied, None, answered)
                if not self.page.locator(CHAT).count():
                    break
                answered.append(self._answer_chat(answerer))
                self.page.wait_for_timeout(1_800)
            if self.page.locator(SUCCESS).count() or self.page.locator(ALREADY_APPLIED).count():
                return ApplyOutcome(ApplyStatus.applied, None, answered)
            if self.page.locator(CHAT).count():
                raise NeedsYou("The questionnaire didn't finish.", answered)
            return ApplyOutcome(ApplyStatus.failed, "Naukri didn't confirm the application", answered)
        except NeedsYou as e:
            return ApplyOutcome(ApplyStatus.needs_you, str(e), e.questions or answered)
        except (BoardBlocked, LoginRequired):
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Naukri apply failed for %s: %s", job.url, e)
            return ApplyOutcome(ApplyStatus.failed, f"{type(e).__name__}: {str(e)[:200]}", answered)

    def _answer_chat(self, answerer) -> QA:
        """Answer the questionnaire's current question (text box, single-choice chips or checkboxes)."""
        label = self.page.locator(CHAT_LAST_QUESTION).inner_text(timeout=5_000).strip()
        chips = self.page.locator(CHAT_CHIPS)
        boxes = self.page.locator(CHAT_CHECKBOXES)
        if chips.count():
            options = [chips.nth(i).inner_text().strip() for i in range(chips.count())]
            q = Question(label, "radio", options, required=True)
        elif boxes.count():
            options = [boxes.nth(i).inner_text().strip() for i in range(boxes.count())]
            q = Question(label, "checkbox", options, required=True)
        else:
            q = Question(label, "text", required=True)
        qa = answerer.answer(q)
        if qa.answer is None:
            raise NeedsYou(f"Couldn't answer: “{label}”", [qa])
        if q.options:
            pick = chips if chips.count() else boxes
            pick.nth(q.options.index(qa.answer)).click()
        else:
            box = self.page.locator(CHAT_INPUT).first
            box.click()
            box.type(qa.answer, delay=40)
        pause(0.4, 0.9)
        self.page.locator(CHAT_SAVE).first.click()
        return qa

    def _screenshot(self, job: JobListing) -> str | None:
        folder = get_settings().data_dir / "apply_screens"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"naukri_{job.external_id}.png"
        try:
            self.page.screenshot(path=str(path))
            return str(path)
        except Exception:  # noqa: BLE001
            return None
