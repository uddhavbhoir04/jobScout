"""Playwright helpers: one persistent browser profile per account, human-like pauses."""
import random
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

from jobscout.config import get_settings
from jobscout.db.models import Account


def profile_dir(account: Account) -> Path:
    p = get_settings().data_dir / "profiles" / f"{account.platform.value}_{account.id}"
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def open_context(account: Account, headless: bool | None = None) -> Iterator[BrowserContext]:
    headless = get_settings().headless if headless is None else headless
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir(account)),
            headless=headless,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            yield ctx
        finally:
            ctx.close()


def pause(lo: float = 1.0, hi: float = 3.0) -> None:
    time.sleep(random.uniform(lo, hi))
