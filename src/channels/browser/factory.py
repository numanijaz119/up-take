import random
import logging
from rebrowser_playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Realistic user agents (Chrome on Windows/Mac).
# Keep these within ~2 major versions of current Chrome — stale UAs are a fingerprint signal.
# Chrome releases a new major version every ~4 weeks. Update this list periodically.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
]


class BrowserFactory:
    """
    Creates stealth-configured browser instances.
    Each session gets slightly varied fingerprint parameters.
    """

    def __init__(self, timezone: str = "America/New_York"):
        self.timezone = timezone

    async def create_session(
        self,
        playwright,
        storage_state: dict | None = None,
    ) -> tuple[Browser, BrowserContext, Page]:
        """
        Create a stealth browser session.

        Args:
            playwright: The async_playwright instance.
            storage_state: Optional Playwright storage_state dict (cookies +
                localStorage) loaded by LoginManager.  When provided the browser
                context starts already authenticated as the Upwork user.
        """
        width = random.randint(1280, 1440)
        height = random.randint(780, 900)
        user_agent = random.choice(USER_AGENTS)

        # channel="chrome" uses the real installed Chrome binary rather than
        # Playwright's bundled Chromium. Real Chrome passes Cloudflare's browser
        # fingerprint checks; Playwright's Chromium is identifiable and gets flagged.
        # Requires Google Chrome installed at its default path on this machine.
        browser = await playwright.chromium.launch(
            channel="chrome",   # real Chrome — not Playwright's Chromium
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                # --no-sandbox removed: known automation signal; not needed on Windows
                "--disable-dev-shm-usage",
                f"--window-size={width},{height}",
                # --disable-extensions and --disable-plugins-discovery removed:
                # real Chrome doesn't run with these flags and they reduce trust score
            ],
        )

        context_kwargs: dict = dict(
            viewport={"width": width, "height": height},
            user_agent=user_agent,
            locale="en-US",
            timezone_id=self.timezone,
            color_scheme="light",
            device_scale_factor=random.choice([1, 1, 1, 2]),
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        if storage_state is not None:
            context_kwargs["storage_state"] = storage_state
            logger.info("Creating browser context WITH saved session state (authenticated)")
        else:
            logger.warning("Creating browser context WITHOUT session state (unauthenticated)")

        context = await browser.new_context(**context_kwargs)

        page = await context.new_page()

        await self._apply_extra_patches(page)
        return browser, context, page

    async def _apply_extra_patches(self, page: Page) -> None:
        """
        Minimal patches — only what's needed to hide Playwright-specific signals.

        Important: when using channel="chrome", the real Chrome already provides
        authentic values for window.chrome, navigator.plugins, WebGL renderer,
        battery state, etc. Overwriting them with fake values is WORSE than no
        patch — a hardcoded GPU string mismatches your real GPU; a 3-plugin list
        looks fake against real Chrome's 5+ plugins; randomized battery readings
        are inconsistent across calls.

        We only patch what Playwright actively breaks:
          - navigator.webdriver (Playwright sets this to true)
        Everything else is left as real Chrome reports it.
        """
        await page.add_init_script("""
            // Remove the webdriver flag — Playwright sets navigator.webdriver=true.
            // 'undefined' (rather than false) matches what real Chrome reports.
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
