"""
PageGuard — detects every abnormal page state Upwork / Cloudflare can show
and decides what to do about it.

Called after every page.goto() in the session runner.
"""
import asyncio
import logging
import random
from enum import Enum
from typing import TYPE_CHECKING

from playwright.async_api import Page

if TYPE_CHECKING:
    from src.notifications.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


class PageState(str, Enum):
    OK                   = "ok"
    JS_CHALLENGE         = "js_challenge"           # Cloudflare JS — auto-resolves
    MANAGED_CHALLENGE    = "managed_challenge"       # Cloudflare managed — usually auto
    INTERACTIVE_CHALLENGE = "interactive_challenge"  # press-and-hold / hCaptcha — needs human
    RATE_LIMITED         = "rate_limited"            # 429 — back off
    HARD_BLOCK           = "hard_block"              # 403 / IP banned — stop channel
    LOGGED_OUT           = "logged_out"              # session expired — re-login needed
    MAINTENANCE          = "maintenance"             # Upwork down — wait and retry
    UNKNOWN_ERROR        = "unknown_error"           # catch-all


# ── Cloudflare / Upwork fingerprint strings ──────────────────────────────────

_CF_JS_TITLES = [
    "just a moment",
    "checking your browser",
    "please wait",
    "one moment please",
]

_CF_INTERACTIVE_TITLES = [
    "verify you are human",
    "attention required",
    "security check",
    "are you a human",
]

_CF_INTERACTIVE_SELECTORS = [
    "#challenge-form",
    "#cf-challenge-running",
    "input#challenge-input",          # press-and-hold input
    ".cf-turnstile",                  # Cloudflare Turnstile widget
    "iframe[src*='challenges.cloudflare.com']",
    "iframe[src*='hcaptcha.com']",
    "#hcaptcha-demo",
    ".h-captcha",
]

_BLOCK_TITLES = [
    "access denied",
    "403 forbidden",
    "error 1020",
    "error 1006",
    "error 1010",
    "blocked",
    "banned",
]

_RATE_LIMIT_TITLES = [
    "429",
    "too many requests",
    "rate limit",
]

_LOGGED_OUT_PATTERNS = [
    "/login",
    "/ab/account-security/login",
    "signup",
]

_LOGGED_OUT_TITLES = [
    "log in",
    "sign in",
    "sign up",
]

_MAINTENANCE_TITLES = [
    "maintenance",
    "service unavailable",
    "503",
    "temporarily unavailable",
    "down for maintenance",
]


class PageGuard:
    """
    Detects abnormal page states and handles them.

    Usage:
        guard = PageGuard(notifier=notifier, stop_event=stop_event)
        state = await guard.check_and_handle(page, context_label="homepage")
        if state in (PageState.HARD_BLOCK, PageState.LOGGED_OUT):
            break  # abort session
    """

    # How long to wait for an interactive challenge to be solved by the human
    INTERACTIVE_CHALLENGE_TIMEOUT_S = 300   # 5 minutes
    # How long to wait for a JS challenge to auto-resolve
    JS_CHALLENGE_TIMEOUT_S = 20
    # How long to back off after rate limiting
    RATE_LIMIT_BACKOFF_RANGE = (120, 300)   # 2–5 minutes

    def __init__(
        self,
        notifier: "TelegramNotifier | None" = None,
        stop_event: asyncio.Event | None = None,
    ):
        self._notifier = notifier
        self._stop_event = stop_event

    # ── Public API ────────────────────────────────────────────────────────────

    async def check_and_handle(self, page: Page, context_label: str = "") -> PageState:
        """
        Detect the current page state and take appropriate action.
        Returns the final PageState after any handling attempt.
        """
        state = await self._detect(page)

        if state == PageState.OK:
            return state

        label = f" (after {context_label})" if context_label else ""
        logger.warning(f"PageGuard detected: {state.value}{label} — URL: {page.url[:120]}")

        if state == PageState.JS_CHALLENGE:
            return await self._handle_js_challenge(page)

        if state == PageState.MANAGED_CHALLENGE:
            return await self._handle_managed_challenge(page)

        if state == PageState.INTERACTIVE_CHALLENGE:
            return await self._handle_interactive_challenge(page, context_label)

        if state == PageState.RATE_LIMITED:
            return await self._handle_rate_limited(page)

        if state == PageState.HARD_BLOCK:
            await self._handle_hard_block(page)
            return PageState.HARD_BLOCK

        if state == PageState.LOGGED_OUT:
            await self._handle_logged_out(page)
            return PageState.LOGGED_OUT

        if state == PageState.MAINTENANCE:
            return await self._handle_maintenance(page)

        # UNKNOWN_ERROR
        logger.error(
            f"PageGuard: unknown page state{label}. "
            f"Title: '{await self._title(page)}' URL: {page.url[:120]}"
        )
        return PageState.UNKNOWN_ERROR

    async def wait_for_ok_or_challenge(self, page: Page, timeout_ms: int = 10000) -> PageState:
        """
        After a navigation, wait briefly for the page to settle, then check.
        Useful after goto() returns before the page fully renders.
        """
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        return await self.check_and_handle(page, "post-load")

    # ── Detection ─────────────────────────────────────────────────────────────

    async def _detect(self, page: Page) -> PageState:
        try:
            url = page.url.lower()
            title = (await self._title(page)).lower()
        except Exception:
            return PageState.UNKNOWN_ERROR

        # Hard block
        if any(t in title for t in _BLOCK_TITLES):
            return PageState.HARD_BLOCK
        if "cdn-cgi/challenge-platform" in url and "error" in url:
            return PageState.HARD_BLOCK

        # Rate limited
        if any(t in title for t in _RATE_LIMIT_TITLES):
            return PageState.RATE_LIMITED

        # Logged out
        if any(p in url for p in _LOGGED_OUT_PATTERNS):
            return PageState.LOGGED_OUT
        if any(t in title for t in _LOGGED_OUT_TITLES) and "upwork.com" in url:
            return PageState.LOGGED_OUT

        # Maintenance
        if any(t in title for t in _MAINTENANCE_TITLES):
            return PageState.MAINTENANCE

        # Interactive challenge — check both title and DOM
        if any(t in title for t in _CF_INTERACTIVE_TITLES):
            return PageState.INTERACTIVE_CHALLENGE
        for sel in _CF_INTERACTIVE_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el:
                    return PageState.INTERACTIVE_CHALLENGE
            except Exception:
                pass

        # JS / managed challenge
        if any(t in title for t in _CF_JS_TITLES):
            return PageState.JS_CHALLENGE
        if "cdn-cgi/challenge-platform" in url:
            return PageState.MANAGED_CHALLENGE

        return PageState.OK

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def _handle_js_challenge(self, page: Page) -> PageState:
        """Cloudflare JS challenge — normally auto-resolves in <5s."""
        logger.info("Cloudflare JS challenge detected — waiting for auto-resolve (up to 20s)…")
        try:
            await page.wait_for_function(
                """() => !['just a moment','checking your browser','please wait']
                    .some(t => document.title.toLowerCase().includes(t))""",
                timeout=self.JS_CHALLENGE_TIMEOUT_S * 1000,
            )
            await asyncio.sleep(random.uniform(1.5, 3.0))
            state = await self._detect(page)
            if state == PageState.OK:
                logger.info("JS challenge auto-resolved successfully")
                return PageState.OK
            logger.warning(f"JS challenge resolved but page state is now: {state.value}")
            return state
        except asyncio.TimeoutError:
            logger.error("JS challenge did not resolve in 20s — may have escalated to interactive")
            # Re-check in case it escalated
            new_state = await self._detect(page)
            if new_state == PageState.INTERACTIVE_CHALLENGE:
                return await self._handle_interactive_challenge(page, "post-js-challenge-escalation")
            await self._alert(
                "⚠️ *Cloudflare JS challenge did not resolve*\n"
                "Browser session aborted. Will retry at next scheduled session.\n"
                f"URL: `{page.url[:100]}`"
            )
            return PageState.JS_CHALLENGE

    async def _handle_managed_challenge(self, page: Page) -> PageState:
        """Cloudflare managed challenge — usually auto-resolves, slightly longer wait."""
        logger.info("Cloudflare managed challenge — waiting up to 25s…")
        try:
            await page.wait_for_function(
                "() => !document.title.toLowerCase().includes('checking')",
                timeout=25000,
            )
            await asyncio.sleep(random.uniform(2.0, 4.0))
            state = await self._detect(page)
            if state == PageState.OK:
                logger.info("Managed challenge resolved")
                return PageState.OK
            return state
        except asyncio.TimeoutError:
            logger.warning("Managed challenge timed out — re-checking for interactive")
            new_state = await self._detect(page)
            if new_state == PageState.INTERACTIVE_CHALLENGE:
                return await self._handle_interactive_challenge(page, "post-managed-escalation")
            return PageState.MANAGED_CHALLENGE

    async def _handle_interactive_challenge(
        self, page: Page, context_label: str = ""
    ) -> PageState:
        """
        Interactive challenge (press-and-hold, hCaptcha, Turnstile checkbox).
        Cannot be solved automatically — alert the human and wait.
        """
        logger.warning(
            "INTERACTIVE CHALLENGE detected — human intervention required. "
            f"Waiting up to {self.INTERACTIVE_CHALLENGE_TIMEOUT_S}s."
        )

        title = await self._title(page)
        await self._alert(
            "🚨 *Interactive Challenge Detected!*\n\n"
            "Upwork / Cloudflare is showing a human verification challenge "
            "(press-and-hold, image puzzle, or checkbox).\n\n"
            f"*Page:* `{title[:60]}`\n"
            f"*URL:* `{page.url[:100]}`\n\n"
            "👉 Please solve it in the browser window.\n"
            f"The session will wait *{self.INTERACTIVE_CHALLENGE_TIMEOUT_S // 60} minutes* "
            "then continue if solved, or abort if not."
        )

        # Poll every 3s to see if the challenge has gone away
        elapsed = 0
        poll_interval = 3
        while elapsed < self.INTERACTIVE_CHALLENGE_TIMEOUT_S:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            if self._stop_event and self._stop_event.is_set():
                logger.info("Stop event set during challenge wait — aborting")
                return PageState.INTERACTIVE_CHALLENGE

            state = await self._detect(page)
            if state == PageState.OK:
                logger.info(
                    f"Interactive challenge resolved by human after {elapsed}s — continuing session"
                )
                await self._alert("✅ Challenge solved! Continuing session…")
                await asyncio.sleep(random.uniform(1.5, 3.0))
                return PageState.OK
            if state not in (
                PageState.INTERACTIVE_CHALLENGE,
                PageState.JS_CHALLENGE,
                PageState.MANAGED_CHALLENGE,
            ):
                # Something else happened (hard block, logged out)
                return state

        logger.error(
            f"Interactive challenge not solved within {self.INTERACTIVE_CHALLENGE_TIMEOUT_S}s — aborting session"
        )
        await self._alert(
            "⏰ *Challenge timeout* — session aborted.\n"
            "The browser will retry at the next scheduled session."
        )
        return PageState.INTERACTIVE_CHALLENGE

    async def _handle_rate_limited(self, page: Page) -> PageState:
        """429 rate limit — sleep and signal backoff."""
        backoff = random.randint(*self.RATE_LIMIT_BACKOFF_RANGE)
        logger.warning(f"Rate limited (429) — backing off for {backoff}s")
        await self._alert(
            f"⚡ *Rate Limited (429)*\n"
            f"Upwork returned 429. Sleeping {backoff}s before next session.\n"
            f"URL: `{page.url[:100]}`"
        )
        await asyncio.sleep(backoff)
        return PageState.RATE_LIMITED

    async def _handle_hard_block(self, page: Page) -> None:
        """403 / IP ban / hard block — stop the channel entirely."""
        title = await self._title(page)
        logger.error(
            f"HARD BLOCK detected — channel will be stopped. "
            f"Title: '{title}' URL: {page.url[:120]}"
        )
        await self._alert(
            "🔴 *Hard Block / Access Denied*\n\n"
            "Upwork returned a hard block (403 or similar).\n"
            f"*Page:* `{title[:60]}`\n"
            f"*URL:* `{page.url[:100]}`\n\n"
            "The browser channel has been *stopped automatically*.\n"
            "⚠️ Check your Upwork account status before re-enabling.\n"
            "You may need to change IP or wait before retrying."
        )
        # Signal the channel scheduler to stop
        if self._stop_event:
            self._stop_event.set()

    async def _handle_logged_out(self, page: Page) -> None:
        """Session expired — stop the channel and ask for re-login."""
        logger.error(
            f"Browser is LOGGED OUT of Upwork. URL: {page.url[:120]}"
        )
        await self._alert(
            "🔑 *Upwork Session Expired — Re-Login Required*\n\n"
            "The browser session cookie has expired and Upwork is showing the login page.\n\n"
            "*What to do:*\n"
            "1. Stop the browser channel from the dashboard\n"
            "2. Run: `python -m src.channels.browser.save_session`\n"
            "3. Log in manually in the browser that opens\n"
            "4. Press Enter in the terminal to save the session\n"
            "5. Re-enable the channel from the dashboard\n\n"
            "The browser channel has been *stopped automatically*."
        )
        if self._stop_event:
            self._stop_event.set()

    async def _handle_maintenance(self, page: Page) -> PageState:
        """Upwork maintenance page — wait and retry later."""
        logger.warning("Upwork maintenance page detected — aborting current session")
        await self._alert(
            "🔧 *Upwork Maintenance*\n"
            "Upwork appears to be down for maintenance.\n"
            "Current session aborted. Will retry at next scheduled session."
        )
        return PageState.MAINTENANCE

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _title(self, page: Page) -> str:
        try:
            return await page.title()
        except Exception:
            return ""

    async def _alert(self, message: str) -> None:
        """Send Telegram alert and always log."""
        logger.warning(f"[PageGuard Alert] {message.replace('*', '').replace('`', '')}")
        if self._notifier:
            try:
                await self._notifier.send_text(message)
            except Exception as e:
                logger.error(f"Failed to send PageGuard Telegram alert: {e}")
