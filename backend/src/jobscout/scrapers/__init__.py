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
