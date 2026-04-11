import random
import logging
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Realistic user agents (Chrome on Windows/Mac)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
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

        browser = await playwright.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--window-size={width},{height}",
                "--disable-extensions",
                "--disable-plugins-discovery",
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

        # Apply stealth patches
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except ImportError:
            logger.warning("playwright-stealth not installed — running without stealth patches")

        await self._apply_extra_patches(page)
        return browser, context, page

    async def _apply_extra_patches(self, page: Page) -> None:
        """Patches beyond what playwright-stealth covers."""
        await page.add_init_script("""
            // Chrome object
            if (!window.chrome) {
                window.chrome = { runtime: {}, loadTimes: function(){}, app: {} };
            }

            // Realistic plugins list
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const arr = [
                        { name: 'Chrome PDF Plugin',  filename: 'internal-pdf-viewer' },
                        { name: 'Chrome PDF Viewer',  filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                        { name: 'Native Client',      filename: 'internal-nacl-plugin' },
                    ];
                    arr.__proto__ = PluginArray.prototype;
                    return arr;
                }
            });

            // WebGL — return a real GPU string
            const _getParam = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(param) {
                if (param === 37445) return 'Intel Inc.';
                if (param === 37446) return 'Intel(R) Iris(TM) Plus Graphics 640';
                return _getParam.apply(this, arguments);
            };

            // Battery API — realistic level
            navigator.getBattery = async () => ({
                charging: Math.random() > 0.4,
                level: 0.6 + Math.random() * 0.4,
                chargingTime: 0,
                dischargingTime: Infinity,
            });

            // Remove webdriver flag
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

            // Languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)
