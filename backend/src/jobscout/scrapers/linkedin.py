"""LinkedIn content-search scraper.

LinkedIn changes its markup often. Every selector lives in the constants / JS below so
fixing a break means editing this file only.
"""
import hashlib
import logging
import random
import re
from collections.abc import Iterator
from urllib.parse import quote

from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import TimeoutError as PWTimeout

from jobscout.browser.manager import pause
from jobscout.db.models import Platform
from jobscout.extract.dates import DateRange, parse_relative
from jobscout.scrapers.base import LoginRequired, RawPost

log = logging.getLogger(__name__)

BASE = "https://www.linkedin.com"
FEED_URL = f"{BASE}/feed/"
LOGIN_URL = f"{BASE}/login"
BLOCKED_MARKERS = ("/login", "/checkpoint", "/authwall", "/uas/login")

MANUAL_LOGIN_TIMEOUT_MS = 5 * 60 * 1000
MAX_IDLE_SCROLLS = 7  # a search is "exhausted" after this many scrolls without new posts

# The full post text is already in the DOM (only visually clamped), so no "see more" clicks are
# needed for the 2026 layout. Old-layout toggles are still clicked once as a fallback.
_EXPAND_JS = """
() => {
  const sel = 'button.feed-shared-inline-show-more-text__see-more-less-toggle, button.see-more';
  document.querySelectorAll(sel).forEach(b => {
    if (b.dataset.jsExpanded) return;
    b.dataset.jsExpanded = '1';
    if (b.getAttribute('aria-expanded') !== 'true') { try { b.click(); } catch (e) {} }
  });
}
"""

# Returns [{key, text, author, authorUrl, sub}] for every post card on the page.
_EXTRACT_JS = r"""
() => {
  const pick = (root, sels) => { for (const s of sels) { const el = root.querySelector(s); if (el) return el; } return null; };
  // Text with <br> turned into newlines, independent of CSS clamping.
  const fullText = (el) => {
    if (!el) return '';
    const c = el.cloneNode(true);
    c.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
    c.querySelectorAll('p, li, div').forEach(b => b.append('\n'));
    return c.textContent.replace(/[ \t ]+/g, ' ').replace(/\n\s*\n\s*\n+/g, '\n\n').trim();
  };
  const TIME_RE = /^\d+\s*(s|m|h|d|w|mo|yr|y)\b/i;
  const out = [];

  // --- 2026 layout: server-driven cards ---
  for (const card of document.querySelectorAll('[role="listitem"][componentkey^="update-card"]')) {
    const textEl = card.querySelector('[data-testid="expandable-text-box"]');
    let author = '';
    const menu = card.querySelector('button[aria-label*="control menu for post by" i]');
    if (menu) author = menu.getAttribute('aria-label').replace(/^.*post by\s+/i, '').trim();
    const link = pick(card, ['a[href*="linkedin.com/in/"]', 'a[href*="/in/"]', 'a[href*="/company/"]']);
    if (!author && link) author = (link.innerText || '').trim().split('\n')[0];
    let sub = '';
    for (const p of card.querySelectorAll('p, span')) {
      const t = (p.innerText || '').trim();
      if (t.length < 40 && TIME_RE.test(t)) { sub = t; break; }
    }
    out.push({ key: card.getAttribute('componentkey'), text: fullText(textEl), author,
               authorUrl: link ? link.href.split('?')[0] : '', sub });
  }
  if (out.length) return out;

  // --- older layout (data-urn) ---
  const nodes = document.querySelectorAll(
    '[data-urn*="urn:li:activity:"], [data-urn*="urn:li:ugcPost:"], [data-id*="urn:li:activity:"]');
  for (const n of nodes) {
    if (n.parentElement && n.parentElement.closest('[data-urn*="urn:li:activity:"], [data-urn*="urn:li:ugcPost:"]')) continue;
    const textEl = pick(n, ['.update-components-text', '.feed-shared-update-v2__description',
                            '.feed-shared-inline-show-more-text', '.feed-shared-text']);
    const actor = pick(n, ['.update-components-actor__title span[aria-hidden="true"]',
                           '.update-components-actor__name span[aria-hidden="true"]',
                           '.update-components-actor__title', '.feed-shared-actor__name']);
    const link = pick(n, ['a.update-components-actor__meta-link', 'a.update-components-actor__image',
                          'a[href*="linkedin.com/in/"]', 'a[href*="/company/"]']);
    const sub = pick(n, ['.update-components-actor__sub-description', '.feed-shared-actor__sub-description']);
    out.push({ key: n.getAttribute('data-urn') || n.getAttribute('data-id'),
               text: textEl ? textEl.innerText.trim() : '',
               author: actor ? actor.innerText.trim().split('\n')[0] : '',
               authorUrl: link ? link.href.split('?')[0] : '', sub: sub ? sub.innerText.trim() : '' });
  }
  return out;
}
"""


def post_id(item: dict) -> str:
    """Stable ID across sessions. Old layout exposes a real URN; the 2026 layout only has
    per-session keys, so fingerprint author profile + normalised text instead."""
    key = item.get("key") or ""
    if key.startswith("urn:li:"):
        return key
    norm = re.sub(r"\s+", " ", item.get("text", "")).strip().lower()[:1000]
    digest = hashlib.sha1(f"{item.get('authorUrl', '')}|{norm}".encode()).hexdigest()[:24]
    return f"post:{digest}"


def post_url(item: dict, pid: str) -> str | None:
    if pid.startswith("urn:li:"):
        return f"{BASE}/feed/update/{pid}/"
    return None  # new layout has no per-post link in the page; author_profile_url is stored instead

_LOAD_MORE = "button.scaffold-finite-scroll__load-button, button:has-text('Show more results')"
_LAST_CARD_INTO_VIEW_JS = """
() => {
  const cards = document.querySelectorAll(
    '[role="listitem"][componentkey^="update-card"], [data-urn*="urn:li:activity:"], [data-urn*="urn:li:ugcPost:"]');
  if (cards.length) cards[cards.length - 1].scrollIntoView({block: 'end', behavior: 'smooth'});
  else window.scrollTo(0, document.scrollingElement.scrollHeight);
}
"""


class LinkedInScraper:
    platform = Platform.linkedin

    def __init__(self, ctx: BrowserContext):
        self.ctx = ctx
        self.page: Page = ctx.pages[0] if ctx.pages else ctx.new_page()

    # ---------- login ----------
    def _blocked(self) -> bool:
        return any(m in self.page.url for m in BLOCKED_MARKERS)

    def is_logged_in(self) -> bool:
        self.page.goto(FEED_URL, wait_until="domcontentloaded")
        pause(2, 4)
        return "/feed" in self.page.url and not self._blocked()

    def ensure_logged_in(self, email: str, password: str, allow_manual: bool) -> bool:
        if self.is_logged_in():
            return True
        log.info("Logging in to LinkedIn as %s", email)
        self.page.goto(LOGIN_URL, wait_until="domcontentloaded")
        pause(1, 2)
        try:
            self.page.fill("#username", email)
            pause(0.5, 1.5)
            self.page.fill("#password", password)
            pause(0.5, 1.5)
            self.page.click("button[type=submit]")
        except PWTimeout:
            log.warning("Login form not found (page may already show an account picker).")
        try:
            self.page.wait_for_url("**/feed/**", timeout=MANUAL_LOGIN_TIMEOUT_MS if allow_manual else 20_000)
        except PWTimeout:
            return False
        pause(2, 3)
        return not self._blocked()

    # ---------- search ----------
    @staticmethod
    def search_url(query: str, date_posted: str | None) -> str:
        """`query` is used as typed (e.g. '#hiring AND (#a OR #b)').
        Filters are JSON lists, e.g. sortBy=["date_posted"]&datePosted=["past-week"]."""
        keyword = quote(query)
        url = (f"{BASE}/search/results/content/?keywords={keyword}&origin=FACETED_SEARCH"
               f"&sortBy={quote('[\"date_posted\"]')}")
        if date_posted:
            url += f"&datePosted={quote(f'[\"{date_posted}\"]')}"
        return url

    def _no_results(self) -> bool:
        return bool(self.page.get_by_text("No results found").count())

    def _open_search(self, tag: str, date_range: DateRange) -> bool:
        """Open the narrowest date filter that returns results. False if nothing at all."""
        for dp in date_range.linkedin_params():
            self.page.goto(self.search_url(tag, dp), wait_until="domcontentloaded")
            pause(3, 5)
            if self._blocked():
                raise LoginRequired(f"LinkedIn redirected to {self.page.url}")
            if self.page.evaluate(_EXTRACT_JS) or not self._no_results():
                log.info("Searching %s (datePosted=%s)", tag, dp or "any time")
                return True
            log.info("No results for %s with datePosted=%s, widening…", tag, dp or "any time")
            pause(2, 4)
        self._dump_debug(tag)
        log.warning("LinkedIn returned no results for %s at all. If the same search is empty in your normal "
                    "browser too, LinkedIn is limiting search for this account.", tag)
        return False

    def search(self, tag: str, date_range: DateRange) -> Iterator[RawPost]:
        if not self._open_search(tag, date_range):
            return

        seen: set[str] = set()
        idle = 0
        first_pass = True
        while idle < MAX_IDLE_SCROLLS:
            if first_pass:
                first_pass = False
                if not self.page.evaluate(_EXTRACT_JS):
                    self._dump_debug(tag)  # results page loaded but our selectors found no posts
            self.page.evaluate(_EXPAND_JS)
            pause(0.8, 1.6)
            new = 0
            for item in self.page.evaluate(_EXTRACT_JS):
                if not item.get("text"):
                    continue
                pid = post_id(item)
                if pid in seen:
                    continue
                seen.add(pid)
                new += 1
                rel = item.get("sub") or None
                yield RawPost(
                    external_id=pid,
                    url=post_url(item, pid),
                    author_name=item.get("author") or None,
                    author_profile_url=item.get("authorUrl") or None,
                    text=item["text"],
                    relative_time=rel,
                    posted_at=parse_relative(rel) if rel else None,
                    search_tag=tag,
                )
            idle = 0 if new else idle + 1
            self._scroll()
            if self._blocked():
                raise LoginRequired(f"LinkedIn redirected to {self.page.url}")

    def _dump_debug(self, tag: str) -> None:
        """Save the page so selector/URL problems can be diagnosed offline."""
        from datetime import datetime

        from jobscout.config import get_settings

        d = get_settings().data_dir / "debug"
        d.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "_", tag.lower()).strip("_")[:60] or "query"
        stem = d / f"linkedin_{slug}_{datetime.now():%Y%m%d_%H%M%S}"
        try:
            stem.with_suffix(".html").write_text(self.page.content(), encoding="utf-8")
            self.page.screenshot(path=str(stem.with_suffix(".png")), full_page=False)
            log.warning("No posts found for %s. Saved page to %s.html/.png (url: %s)", tag, stem, self.page.url)
        except Exception as e:  # never fail the run because of debugging
            log.debug("debug dump failed: %s", e)

    def _scroll(self) -> None:
        # 2026 layout: results scroll inside <main id="workspace">, not the page, and a wheel event
        # only scrolls the element under the pointer. So wheel over the results, then bring the
        # last card into view, which triggers loading the next batch (verified: 6 -> 12 -> 21 cards).
        vp = self.page.viewport_size or {"width": 1366, "height": 900}
        self.page.mouse.move(vp["width"] * random.uniform(0.3, 0.45), vp["height"] * random.uniform(0.5, 0.7))
        for _ in range(random.randint(2, 4)):
            self.page.mouse.wheel(0, random.randint(600, 1200))
            pause(0.4, 1.0)
        self.page.evaluate(_LAST_CARD_INTO_VIEW_JS)
        more = self.page.locator(_LOAD_MORE)
        if more.count() and more.first.is_visible():
            try:
                more.first.click(timeout=3000)
            except PWTimeout:
                pass
        pause(2, 6)
