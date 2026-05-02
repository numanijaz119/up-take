"""
BrowserChannel — Channel 1: Humanoid Browser.

Navigates Upwork job feeds using a stealth-configured Playwright browser
with human-like timing, scroll behavior, mouse movement, and random pauses.
Read-only — never submits anything, never modifies any page.
"""
import asyncio
import logging
from datetime import datetime
from typing import Callable, Awaitable, TYPE_CHECKING

from src.channels.base import DetectionChannel
from src.channels.browser.scheduler import SessionScheduler
from src.channels.browser.factory import BrowserFactory
from src.channels.browser.session_runner import BrowserSessionRunner
from src.config import settings, WORK_WINDOWS, DAY_WEIGHTS, HOUR_WEIGHTS

if TYPE_CHECKING:
    from src.notifications.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

# How many consecutive failed sessions trigger a "channel degraded" alert
_CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 3


class BrowserChannel(DetectionChannel):
    """
    Channel 1: Humanoid Browser.
    Navigates Upwork job feeds using a stealth-configured browser
    with human-like timing and behavior. Read-only — never submits anything.
    """

    def __init__(
        self,
        on_job_detected: Callable[[dict], Awaitable[None]],
        search_configs: list[dict] | None = None,
        on_session_complete: Callable[[dict], Awaitable[None]] | None = None,
        notifier: "TelegramNotifier | None" = None,
    ):
        super().__init__(on_job_detected)
        self._search_configs = search_configs or []
        self._on_session_complete = on_session_complete
        self._notifier = notifier
        self._stop_event = asyncio.Event()

        self._scheduler = SessionScheduler(
            work_windows=WORK_WINDOWS,
            day_weights=DAY_WEIGHTS,
            hour_weights=HOUR_WEIGHTS,
        )
        self._factory = BrowserFactory(timezone=settings.browser_timezone)
        self._runner: BrowserSessionRunner | None = None

        # Failure tracking for alerting
        self._consecutive_failures = 0
        self._last_success_at: datetime | None = None

    @property
    def channel_id(self) -> str:
        return "browser_channel"

    @property
    def display_name(self) -> str:
        return "Humanoid Browser"

    @property
    def description(self) -> str:
        return (
            "Navigates Upwork job feeds using a stealth-configured browser "
            "with human-like timing and behavior. Read-only — never modifies "
            "any page or submits anything."
        )

    def update_search_configs(self, configs: list[dict]) -> None:
        """Update the search configs at runtime."""
        self._search_configs = configs
        if self._runner:
            self._runner.search_configs = configs
        logger.info(f"Search configs updated: {len(configs)} config(s)")

    async def trigger_manual_session(self) -> None:
        """Run a single session immediately, outside the scheduler."""
        if not self._runner:
            self._build_runner()
        logger.info("Manual session triggered")
        await self._runner.run_session(settings.session_duration_mean)

    def _build_runner(self) -> None:
        self._runner = BrowserSessionRunner(
            factory=self._factory,
            on_job_detected=self._emit,
            search_configs=self._search_configs,
            on_session_complete=self._wrapped_session_complete,
            notifier=self._notifier,
            stop_event=self._stop_event,
        )

    async def _wrapped_session_complete(self, session_data: dict) -> None:
        """Track consecutive failures, alert on degradation, then forward callback."""
        error = session_data.get("error")
        aborted = session_data.get("aborted", False)
        jobs_found = session_data.get("jobs_found", 0)

        if error or aborted:
            self._consecutive_failures += 1
            logger.warning(
                f"Session completed with issues — "
                f"consecutive failures: {self._consecutive_failures} | "
                f"error: {error} | aborted: {aborted}"
            )

            if self._consecutive_failures >= _CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
                await self._alert(
                    f"⚠️ *Browser Channel Degraded*\n\n"
                    f"{self._consecutive_failures} consecutive sessions have failed or been aborted.\n\n"
                    f"Last error: `{(error or 'aborted')[:200]}`\n\n"
                    "Please check:\n"
                    "• Upwork session freshness (run save_session script)\n"
                    "• IP / Cloudflare status\n"
                    "• Log files for detailed errors\n\n"
                    "The channel will keep retrying at scheduled intervals."
                )
        else:
            if self._consecutive_failures > 0:
                logger.info(
                    f"Session recovered after {self._consecutive_failures} failures "
                    f"— found {jobs_found} jobs"
                )
                await self._alert(
                    f"✅ *Browser Channel Recovered*\n"
                    f"Session succeeded after {self._consecutive_failures} consecutive failures.\n"
                    f"Jobs found this session: {jobs_found}"
                )
            self._consecutive_failures = 0
            self._last_success_at = datetime.utcnow()

        # Forward to original callback (persists to DB)
        if self._on_session_complete:
            try:
                await self._on_session_complete(session_data)
            except Exception as e:
                logger.error(f"on_session_complete callback error: {e}")

    async def start(self) -> None:
        self._running = True
        self._stop_event.clear()
        self._build_runner()
        logger.info(
            f"BrowserChannel starting — "
            f"{len(self._search_configs)} search config(s) | "
            f"notifier: {'yes' if self._notifier else 'no'}"
        )

        await self._alert(
            "🚀 *Humanoid Browser Channel Started*\n"
            f"Search configs loaded: {len(self._search_configs)}\n"
            "Sessions will run on a human-like schedule.\n"
            "Alerts will be sent for any issues requiring attention."
        )

        try:
            await self._scheduler.run_forever(
                self._runner.run_session,
                self._stop_event,
            )
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            logger.info("BrowserChannel stopped")

    async def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        logger.info("BrowserChannel stop requested")
        await self._alert("🛑 *Humanoid Browser Channel Stopped*\nSessions paused until re-enabled.")

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _alert(self, message: str) -> None:
        logger.info(f"[BrowserChannel] {message.replace('*', '').replace('`', '')}")
        if self._notifier:
            try:
                await self._notifier.send_text(message)
            except Exception as e:
                logger.error(f"Telegram alert failed in BrowserChannel: {e}")
