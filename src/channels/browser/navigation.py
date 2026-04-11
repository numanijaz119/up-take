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
        """Open Upwork like a real user — homepage first, then find-work."""
        await page.goto("https://www.upwork.com", wait_until="domcontentloaded", timeout=30000)
        await self.behavior.human_pause(3, 8)
        await self.behavior.random_mouse_wander(page, movements=3)
        await page.goto("https://www.upwork.com/nx/find-work/", wait_until="domcontentloaded", timeout=30000)
        await self.behavior.human_pause(2, 5)

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
            for selector in [
                '[data-test="description"] p',
                '.description p',
                'section[data-test="description"]',
                '[data-test="job-details-about-client"] ~ section p',
                '.up-lineClamp p',
            ]:
                el = await page.query_selector(selector)
                if el:
                    description = await el.inner_text()
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
