import asyncio
import logging
from typing import Dict, Type, Callable, Awaitable
from src.channels.base import DetectionChannel

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """
    Central registry for all detection channels.
    Manages lifecycle (start/stop) and exposes channel metadata.
    Channels are registered at startup and can be toggled at runtime.
    """

    def __init__(self, on_job_detected: Callable[[dict], Awaitable[None]]):
        self._on_job = on_job_detected
        self._channel_classes: Dict[str, Type[DetectionChannel]] = {}
        self._instances: Dict[str, DetectionChannel] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    # Metadata cache: channel_id → {display_name, description}
    _metadata: Dict[str, dict] = {}

    def register(self, channel_class: Type[DetectionChannel]) -> None:
        """Register a channel class. Called at startup for each available channel."""
        # Create a minimal instance with a no-op callback just to read property values.
        async def _noop(_): pass
        try:
            temp = channel_class(_noop)
            channel_id = temp.channel_id
            self._metadata[channel_id] = {
                "display_name": temp.display_name,
                "description": temp.description,
            }
        except Exception:
            # Fallback: derive channel_id from class name
            channel_id = channel_class.__name__.lower().replace("channel", "_channel")
            self._metadata[channel_id] = {"display_name": channel_class.__name__, "description": ""}

        self._channel_classes[channel_id] = channel_class
        logger.info(f"Registered channel: {channel_id}")

    def get(self, channel_id: str) -> "DetectionChannel | None":
        """Return the running instance of a channel by ID, or None."""
        return self._instances.get(channel_id)

    def list_channels(self) -> list[dict]:
        """Return metadata for all registered channels."""
        result = []
        for cid, cls in self._channel_classes.items():
            instance = self._instances.get(cid)
            meta = self._metadata.get(cid, {})
            result.append({
                "channel_id": cid,
                "display_name": meta.get("display_name", cid),
                "description": meta.get("description", ""),
                "is_running": instance.is_running if instance else False,
            })
        return result

    async def enable(self, channel_id: str, config: dict | None = None) -> bool:
        """Start a channel by ID. Returns True if started."""
        cls = self._channel_classes.get(channel_id)
        if not cls:
            logger.warning(f"Channel not found: {channel_id}")
            return False

        if channel_id in self._instances and self._instances[channel_id].is_running:
            logger.info(f"Channel {channel_id} already running")
            return True

        instance = cls(self._on_job, **(config or {})) if config else cls(self._on_job)
        self._instances[channel_id] = instance

        task = asyncio.create_task(instance.start(), name=f"channel-{channel_id}")
        self._tasks[channel_id] = task
        task.add_done_callback(lambda t: self._on_task_done(channel_id, t))

        logger.info(f"Channel {channel_id} started")
        return True

    async def disable(self, channel_id: str) -> bool:
        """Stop a channel by ID. Returns True if stopped."""
        instance = self._instances.get(channel_id)
        if not instance:
            return False

        await instance.stop()

        task = self._tasks.pop(channel_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        logger.info(f"Channel {channel_id} stopped")
        return True

    def _on_task_done(self, channel_id: str, task: asyncio.Task) -> None:
        if task.cancelled():
            logger.info(f"Channel {channel_id} task cancelled")
        elif task.exception():
            logger.error(f"Channel {channel_id} crashed: {task.exception()}")
        else:
            logger.info(f"Channel {channel_id} task completed normally")

    async def stop_all(self) -> None:
        for cid in list(self._instances.keys()):
            await self.disable(cid)
