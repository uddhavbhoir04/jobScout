from playwright.sync_api import BrowserContext

from jobscout.db.models import Platform
from jobscout.scrapers.base import Scraper


def get_scraper(platform: Platform, ctx: BrowserContext) -> Scraper:
    if platform == Platform.linkedin:
        from jobscout.scrapers.linkedin import LinkedInScraper

        return LinkedInScraper(ctx)
    raise NotImplementedError(
        f"{platform.value} scraping is planned for a later phase (keyword-based job listings)."
    )


def get_board_scraper(platform: Platform, ctx: BrowserContext, headless: bool = False):
    """Job-board scrapers (no login): Naukri and Indeed."""
    if platform == Platform.naukri:
        from jobscout.scrapers.naukri import NaukriScraper

        return NaukriScraper(ctx, headless)
    if platform == Platform.indeed:
        from jobscout.scrapers.indeed import IndeedScraper

        return IndeedScraper(ctx, headless)
    raise ValueError(f"{platform.value} is not a job board.")
