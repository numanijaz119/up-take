import logging
from playwright.async_api import Page
from src.channels.browser.behavior import HumanBehaviorEngine

logger = logging.getLogger(__name__)


class NavigationEngine:
    """
    Handles page navigation with human-like flow.
    Never jumps directly to deep URLs from a cold start.
    """

    def __init__(self, behavior: HumanBehaviorEngine):
        self.behavior = behavior

    async def natural_entry(self, page: Page) -> None:
        """Open Upwork like a real user — homepage first, then the best-matches feed."""
        await page.goto("https://www.upwork.com", wait_until="domcontentloaded", timeout=30000)
        await self.behavior.human_pause(3, 8)
        await self.behavior.random_mouse_wander(page, movements=3)
        # Logged-in users land on /nx/find-work/best-matches (the default feed)
        await page.goto("https://www.upwork.com/nx/find-work/best-matches", wait_until="domcontentloaded", timeout=30000)
        await self.behavior.human_pause(2, 5)
        # Dismiss any Upwork modal that may be blocking the feed (2FA prompts,
        # feature announcements, cookie banners). Cloudflare challenges are handled
        # separately by PageGuard — this covers Upwork-native overlays only.
        await self.dismiss_popups(page)

    async def dismiss_popups(self, page: Page) -> None:
        """
        Silently close any Upwork-native modal or overlay.
        Tries common close-button selectors in order; stops at first success.
        Safe to call any time — no-op if nothing is present.
        """
        close_selectors = [
            '[data-test="modal-close-btn"]',
            '[data-test="modal-close"]',
            '[data-test="close-btn"]',
            'button[aria-label="Close"]',
            'button[aria-label="close"]',
            '.air3-modal-close',
            '[data-dismiss="modal"]',
        ]
        for sel in close_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    logger.info(f"Dismissed Upwork popup (selector: {sel})")
                    await self.behavior.human_pause(0.3, 0.8)
                    break
            except Exception:
                pass

    async def navigate_to_search(self, page: Page, search_url: str) -> None:
        """Navigate to a search URL with natural timing."""
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await self.behavior.human_pause(2, 6)

    async def open_job_detail(self, page: Page, job_url: str) -> str | None:
        """Open a job detail page, read it, extract full description, go back."""
        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            await self.behavior.human_pause(3, 10)
            await self.behavior.human_scroll(page)
            await self.behavior.human_pause(2, 6)
            await self.behavior.human_scroll(page)

            description = None
            # Validated against real Upwork job detail HTML (April 2026).
            # data-test="Description" uses capital D — querySelector is case-sensitive.
            # Removed '.description p' — it matched feature labels ("Hourly", "Duration").
            for selector in [
                '[data-test="Description"] p.text-body-sm',  # primary
                '[data-test="Description"] p',               # fallback
            ]:
                el = await page.query_selector(selector)
                if el:
                    text = (await el.inner_text() or "").strip()
                    if len(text) > 20:
                        description = text
                        break

            await page.go_back(wait_until="domcontentloaded", timeout=15000)
            await self.behavior.human_pause(1, 4)
            return description

        except Exception as e:
            logger.warning(f"Failed to open job detail {job_url}: {e}")
            try:
                await page.go_back(wait_until="domcontentloaded", timeout=10000)
            except Exception:
                pass
            return None
