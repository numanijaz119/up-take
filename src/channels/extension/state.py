"""Redis-backed state for the extension channel."""
from datetime import datetime, timezone
from typing import Optional
from src.redis_client import get_redis

_HEARTBEAT_KEY = "extension:heartbeat:last"
_LAST_JOB_KEY = "extension:last_job_at"
_LAST_EVENT_KEY_FMT = "extension:last_event:{kind}"
_LAST_ALERT_KEY_FMT = "extension:last_alert:{name}"

_HEARTBEAT_TTL_S = 600
_ALERT_DEBOUNCE_TTL_S = 1800


async def record_heartbeat(version: str, tabs_count: int) -> None:
    r = await get_redis()
    now = datetime.now(timezone.utc).isoformat()
    await r.setex(_HEARTBEAT_KEY, _HEARTBEAT_TTL_S, f"{now}|{version}|{tabs_count}")


async def get_last_heartbeat() -> Optional[datetime]:
    r = await get_redis()
    raw = await r.get(_HEARTBEAT_KEY)
    if not raw:
        return None
    ts_str = raw.split("|", 1)[0] if isinstance(raw, str) else raw.decode().split("|", 1)[0]
    return datetime.fromisoformat(ts_str)


async def record_last_job_at(when: datetime) -> None:
    r = await get_redis()
    await r.set(_LAST_JOB_KEY, when.isoformat())


async def get_last_job_at() -> Optional[datetime]:
    r = await get_redis()
    raw = await r.get(_LAST_JOB_KEY)
    if not raw:
        return None
    return datetime.fromisoformat(raw if isinstance(raw, str) else raw.decode())


async def record_event(kind: str, detail: str | None = None) -> None:
    r = await get_redis()
    now = datetime.now(timezone.utc).isoformat()
    payload = f"{now}|{detail or ''}"
    await r.setex(_LAST_EVENT_KEY_FMT.format(kind=kind), _HEARTBEAT_TTL_S, payload)


async def should_alert(name: str) -> bool:
    """True if this alert hasn't fired recently. Sets debounce key as side effect."""
    r = await get_redis()
    key = _LAST_ALERT_KEY_FMT.format(name=name)
    if await r.exists(key):
        return False
    await r.setex(key, _ALERT_DEBOUNCE_TTL_S, "1")
    return True
