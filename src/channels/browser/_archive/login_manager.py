"""
LoginManager — loads and saves Upwork session cookies via Playwright
storage_state so that every browser session starts already logged in.

Session file: sessions/upwork_session.json
The file is created once by running: python -m src.channels.browser.save_session
After that, the factory loads it automatically on every session start.
"""
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext

logger = logging.getLogger(__name__)

# Default path — relative to project root
_DEFAULT_SESSION_PATH = Path("sessions") / "upwork_session.json"

# Upwork domains whose cookies signal a live session
_SESSION_COOKIE_NAMES = {"master_access_token", "oauth2_global_js_token", "XSRF-TOKEN"}


class LoginManager:
    """
    Manages Playwright storage_state persistence for Upwork.

    Usage — loading into a new context:
        login_mgr = LoginManager()
        storage_state = login_mgr.load_storage_state()   # None if not saved yet
        browser, context, page = await factory.create_session(p, storage_state)

    Usage — saving after manual login:
        await login_mgr.save_storage_state(context)
    """

    def __init__(self, session_path: Path | str | None = None):
        self.session_path = Path(session_path) if session_path else _DEFAULT_SESSION_PATH

    # ── Public API ────────────────────────────────────────────────────────────

    def load_storage_state(self) -> dict | None:
        """
        Load stored Playwright storage_state from disk.
        Returns None if file does not exist or is unreadable.
        Logs a warning so the caller knows it will browse unauthenticated.
        """
        if not self.session_path.exists():
            logger.warning(
                f"No session file found at '{self.session_path}'. "
                "Browser will run unauthenticated. "
                "Run: python -m src.channels.browser.save_session  to create one."
            )
            return None

        try:
            with open(self.session_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"Session loaded from '{self.session_path}'")
            return data
        except Exception as e:
            logger.error(
                f"Failed to load session from '{self.session_path}': {e}. "
                "Browser will run unauthenticated."
            )
            return None

    async def save_storage_state(self, context: "BrowserContext") -> None:
        """
        Dump the current browser context cookies + localStorage to disk.
        Creates the sessions/ directory if it does not exist.
        """
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            state = await context.storage_state(path=str(self.session_path))
            logger.info(f"Session saved to '{self.session_path}'")
            _log_session_summary(state)
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            raise

    def is_session_file_present(self) -> bool:
        return self.session_path.exists()

    def session_file_age_hours(self) -> float | None:
        """Return age of session file in hours, or None if file is missing."""
        if not self.session_path.exists():
            return None
        import time
        mtime = os.path.getmtime(self.session_path)
        age_secs = time.time() - mtime
        return age_secs / 3600

    def check_session_freshness(self, max_age_hours: float = 168.0) -> bool:
        """
        Return True if the session file is present and younger than max_age_hours.
        Default: 7 days (Upwork sessions typically last 30 days but we warn early).
        """
        age = self.session_file_age_hours()
        if age is None:
            return False
        if age > max_age_hours:
            logger.warning(
                f"Session file is {age:.1f}h old (threshold: {max_age_hours}h). "
                "Consider refreshing: python -m src.channels.browser.save_session"
            )
            return False
        return True

    async def detect_logged_out_and_alert(
        self, context: "BrowserContext", notifier=None
    ) -> bool:
        """
        Inspect context cookies to determine if the session is still valid.
        Returns True if logged-in cookies are present.
        Sends a Telegram alert if the session has expired.
        """
        try:
            cookies = await context.cookies(["https://www.upwork.com"])
            cookie_names = {c["name"] for c in cookies}
            has_session = bool(cookie_names & _SESSION_COOKIE_NAMES)
            if not has_session:
                logger.error(
                    "Session cookies missing from context — Upwork session has expired. "
                    f"Found cookies: {cookie_names}"
                )
                if notifier:
                    try:
                        await notifier.send_text(
                            "🔑 *Upwork Session Expired*\n\n"
                            "Browser cookies are missing. Please refresh the session:\n"
                            "`python -m src.channels.browser.save_session`"
                        )
                    except Exception:
                        pass
            return has_session
        except Exception as e:
            logger.error(f"Cookie check failed: {e}")
            return True  # Assume OK if we can't check — PageGuard will catch it


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_session_summary(state: dict) -> None:
    """Log a human-readable summary of what was saved."""
    cookies = state.get("cookies", [])
    upwork_cookies = [c for c in cookies if "upwork" in c.get("domain", "")]
    session_names = [c["name"] for c in upwork_cookies if c["name"] in _SESSION_COOKIE_NAMES]
    logger.info(
        f"Session summary: {len(cookies)} total cookies, "
        f"{len(upwork_cookies)} Upwork cookies, "
        f"session tokens present: {session_names or 'NONE — not logged in!'}"
    )
    if not session_names:
        logger.warning(
            "No Upwork session tokens found in saved state. "
            "You may not have been logged in when the session was saved."
        )
