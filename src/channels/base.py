from abc import ABC, abstractmethod
from typing import Callable, Awaitable


class DetectionChannel(ABC):
    """
    Base class for all detection channels.
    Every channel produces job dicts and feeds them to the gateway.
    """

    def __init__(self, on_job_detected: Callable[[dict], Awaitable[None]]):
        self._on_job = on_job_detected
        self._running = False

    @property
    @abstractmethod
    def channel_id(self) -> str:
        """Unique machine-readable identifier, e.g. 'browser_channel'."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in the UI."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description of how this channel works."""

    @abstractmethod
    async def start(self) -> None:
        """Start the channel loop. Should set self._running = True."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the channel. Should set self._running = False."""

    @property
    def is_running(self) -> bool:
        return self._running

    async def _emit(self, job: dict) -> bool:
        """Send a discovered job to the gateway. Returns True if it was a new job."""
        result = await self._on_job(job)
        return bool(result)
