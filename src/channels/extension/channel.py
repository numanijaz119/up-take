"""ExtensionChannel — passive channel that receives jobs pushed from the Chrome extension."""
import logging
from typing import Awaitable, Callable

from src.channels.base import DetectionChannel

logger = logging.getLogger(__name__)


class ExtensionChannel(DetectionChannel):
    """
    Channel 4: Browser Extension.

    Unlike BrowserChannel (deprecated), this channel does not own a loop.
    The Chrome extension running in the user's browser is the actual data
    source. This class exists so that:
      • the channel registry has a target for extension_channel
      • the API ingest router can call ._emit(job) to push jobs into the pipeline
      • start/stop are no-ops; "stopping" means the user closes Chrome.
    """

    def __init__(
        self,
        on_job_detected: Callable[[dict], Awaitable[None]],
        notifier=None,
    ):
        super().__init__(on_job_detected)
        self._notifier = notifier
        self._running = False

    @property
    def channel_id(self) -> str:
        return "extension_channel"

    @property
    def display_name(self) -> str:
        return "Browser Extension"

    @property
    def description(self) -> str:
        return (
            "User-controlled Chrome extension that observes Upwork search "
            "pages in the user's own logged-in session. Read-only; never "
            "submits, never modifies the page."
        )

    async def start(self) -> None:
        self._running = True
        logger.info("ExtensionChannel registered (passive — extension is the actual source)")
        if self._notifier:
            try:
                await self._notifier.send_text(
                    "🧩 *Extension Channel Ready*\n"
                    "Backend listening for jobs on /api/v1/extension/jobs.\n"
                    "Make sure the Chrome extension is loaded and at least one "
                    "Upwork search tab is open."
                )
            except Exception as e:
                logger.warning(f"Telegram start alert failed: {e}")

    async def stop(self) -> None:
        self._running = False
        logger.info("ExtensionChannel stopped (jobs will no longer be accepted)")
