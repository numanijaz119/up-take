"""
One-time manual login script — run this once to save your Upwork session.

Usage:
    python -m src.channels.browser.save_session

What it does:
1. Opens a real visible Chrome browser
2. Navigates to https://www.upwork.com/login
3. Waits for you to log in manually (up to 3 minutes)
4. Detects when you reach the Upwork dashboard / home feed
5. Saves the session cookies + storage to sessions/upwork_session.json
6. The automated browser will load this file on every future session

You only need to run this once, or again if the session expires (~30 days).
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

SESSION_PATH = Path("sessions") / "upwork_session.json"
LOGIN_URL = "https://www.upwork.com/ab/account-security/login"
SUCCESS_URL_FRAGMENTS = ["/nx/find-work", "/nx/jobs", "/home", "/dashboard"]
LOGIN_WAIT_TIMEOUT_S = 180  # 3 minutes


async def main():
    from playwright.async_api import async_playwright

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Up-take — Manual Session Save")
    logger.info("=" * 60)
    logger.info(f"Opening browser and navigating to: {LOGIN_URL}")
    logger.info("Please log in to Upwork in the browser window.")
    logger.info(f"Waiting up to {LOGIN_WAIT_TIMEOUT_S}s for you to finish…")
    logger.info("")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                f"--window-size=1280,800",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
        )

        # Apply basic stealth
        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        logger.info("Browser opened. Waiting for successful login…")

        # Poll until we land on a post-login page or timeout
        elapsed = 0
        poll_interval = 2
        logged_in = False

        while elapsed < LOGIN_WAIT_TIMEOUT_S:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            url = page.url.lower()
            if any(frag in url for frag in SUCCESS_URL_FRAGMENTS):
                logger.info(f"Detected successful login! URL: {page.url}")
                logged_in = True
                break

            # Also detect if we reached the main feed (some routes)
            if "upwork.com" in url and "login" not in url and "signup" not in url:
                try:
                    # Wait a moment for the page to settle
                    await page.wait_for_load_state("networkidle", timeout=5000)
                    url = page.url.lower()
                    if any(frag in url for frag in SUCCESS_URL_FRAGMENTS):
                        logger.info(f"Detected successful login! URL: {page.url}")
                        logged_in = True
                        break
                except Exception:
                    pass

            if elapsed % 15 == 0:
                logger.info(f"Still waiting… ({elapsed}s elapsed, {LOGIN_WAIT_TIMEOUT_S - elapsed}s remaining)")

        if not logged_in:
            logger.error(
                f"Did not detect a successful login within {LOGIN_WAIT_TIMEOUT_S}s. "
                "If you did log in, you can still save the session now."
            )
            print("\nDid you log in successfully? Press Enter to save anyway, or Ctrl+C to abort: ", end="", flush=True)
            try:
                input()
                logged_in = True
            except KeyboardInterrupt:
                logger.info("Aborted — session not saved.")
                await browser.close()
                return

        if logged_in:
            # Extra wait for cookies to settle
            await asyncio.sleep(3)

            # Save storage state
            await context.storage_state(path=str(SESSION_PATH))

            # Log what we saved
            with open(SESSION_PATH, "r") as f:
                state = json.load(f)

            cookies = state.get("cookies", [])
            upwork_cookies = [c for c in cookies if "upwork" in c.get("domain", "")]
            session_tokens = [
                c["name"] for c in upwork_cookies
                if c["name"] in {"master_access_token", "oauth2_global_js_token", "XSRF-TOKEN"}
            ]

            logger.info("=" * 60)
            logger.info(f"Session saved to: {SESSION_PATH.resolve()}")
            logger.info(f"Total cookies: {len(cookies)}")
            logger.info(f"Upwork cookies: {len(upwork_cookies)}")
            logger.info(f"Session tokens: {session_tokens or 'NONE — may not be logged in!'}")
            logger.info("=" * 60)

            if not session_tokens:
                logger.warning(
                    "WARNING: No session tokens found in saved state!\n"
                    "You may not have been fully logged in.\n"
                    "Please run this script again after logging in completely."
                )
            else:
                logger.info("SUCCESS! The automated browser will now use this session.")
                logger.info(
                    "Session typically lasts ~30 days. "
                    "Re-run this script if the channel sends a 'Session Expired' alert."
                )

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
