"""
BrowserFactory — creates a Patchright-backed Chrome session with a persistent
profile and applies cookies imported from the user's real Chrome.

Why persistent context (not launch + new_context):
  - Real Chrome profiles accumulate history, cache, and IndexedDB state. Empty
    contexts fingerprint as "first time this browser ever existed" — exactly
    what Cloudflare's risk model penalises.
  - Persistent context keeps everything between sessions on disk. After a few
    sessions the profile looks like an established user.

Why no user_agent / viewport / launch args:
  - cf_clearance is bound to the UA of the Chrome that issued it. Override the
    UA here and Cloudflare invalidates the clearance on every request.
  - Patchright already sets the correct args internally (and removes the ones
    Playwright adds which leak as automation signals). Adding our own args
    reverses those fixes.

The session profile lives at:  sessions/chrome_profile/
This is a *dedicated* directory — NOT the user's real Chrome profile. Do not
point this at AppData/Local/Google/Chrome/User Data: a crash there would
corrupt the real Chrome.
"""
import logging
from pathlib import Path

from patchright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)


# Dedicated profile directory for the automated channel.
_PROFILE_DIR = Path("sessions") / "chrome_profile"


class BrowserFactory:
    """
    Creates Patchright-backed Chrome sessions with a persistent on-disk profile.
    Each call to create_session() reuses the same profile, accumulating trust
    signals across sessions.
    """

    def __init__(self, timezone: str = "America/New_York"):
        self.timezone = timezone

    async def create_session(
        self,
        playwright,
        storage_state: dict | None = None,
    ) -> tuple[BrowserContext, Page]:
        """
        Launch a persistent-profile Chrome session via Patchright.

        Args:
            playwright: The async_playwright instance (Patchright's, passed in
                from session_runner).
            storage_state: Optional Playwright storage_state dict (cookies +
                localStorage) loaded by LoginManager. Cookies are injected into
                the persistent context after launch so the session starts
                already authenticated as the Upwork user.

        Returns:
            (context, page) — no separate browser object under persistent context.
            Call context.close() for full cleanup.
        """
        profile_dir = _PROFILE_DIR.resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        is_first_run = not any(profile_dir.iterdir())
        if is_first_run:
            logger.info(
                f"First-run profile creation at {profile_dir}. "
                "Trust signals build up over the next few sessions."
            )

        # IMPORTANT: do not pass user_agent, viewport, args, or extra_http_headers.
        # Patchright + real Chrome handle all of this correctly on their own.
        # Overriding them breaks cf_clearance binding and reintroduces flag leaks.
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",       # real Chrome binary, not Patchright's Chromium
            headless=False,
            no_viewport=True,       # use Chrome's actual window size
            timezone_id=self.timezone,
            locale="en-US",
            color_scheme="light",
        )

        # Inject Upwork cookies imported from the user's real Chrome.
        # On first run this authenticates us. On subsequent runs the persistent
        # context already has cookies on disk, but re-injecting from the freshest
        # export is harmless and ensures we use the latest values.
        if storage_state and storage_state.get("cookies"):
            await context.add_cookies(storage_state["cookies"])
            logger.info(
                f"Persistent context started — {len(storage_state['cookies'])} "
                "cookies injected from saved session"
            )
        else:
            logger.warning(
                "Persistent context started WITHOUT cookies. "
                "Run: python -m src.channels.browser.cookie_import"
            )

        # Reuse the page Chrome opens by default; only create one if needed.
        page = context.pages[0] if context.pages else await context.new_page()
        return context, page
