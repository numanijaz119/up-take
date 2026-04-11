"""
Global application state — avoids circular imports by centralizing
shared singleton references that other modules need to access.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.channels.registry import ChannelRegistry
    from src.pipeline.dedup import DeduplicationGateway
    from src.safety.controller import SafetyController
    from src.notifications.telegram import TelegramNotifier

_registry: "ChannelRegistry | None" = None
_gateway: "DeduplicationGateway | None" = None
_safety: "SafetyController | None" = None
_session_callback = None
_notifier: "TelegramNotifier | None" = None


def set_registry(r) -> None:
    global _registry
    _registry = r


def get_registry():
    return _registry


def set_gateway(g) -> None:
    global _gateway
    _gateway = g


def get_gateway():
    return _gateway


def set_safety(s) -> None:
    global _safety
    _safety = s


def get_safety():
    return _safety


def set_session_callback(cb) -> None:
    global _session_callback
    _session_callback = cb


def get_session_callback():
    return _session_callback


def set_notifier(n) -> None:
    global _notifier
    _notifier = n


def get_notifier():
    return _notifier
