import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database import get_db
from src.models.channel import ChannelConfig
from src.models.search_config import SearchConfig

router = APIRouter(prefix="/api/v1/channels", tags=["Channels"])


class ChannelToggle(BaseModel):
    enabled: bool


@router.get("/")
async def list_channels(db: AsyncSession = Depends(get_db)):
    """List all registered channels with their current state."""
    from src.app_state import get_registry
    registry = get_registry()

    runtime_map: dict = {}
    if registry:
        for ch in registry.list_channels():
            runtime_map[ch["channel_id"]] = ch

    db_result = await db.execute(select(ChannelConfig))
    db_map = {c.channel_id: c for c in db_result.scalars().all()}

    out = []
    for cid, runtime in runtime_map.items():
        cfg = db_map.get(cid)
        out.append({
            "channel_id": cid,
            "display_name": runtime.get("display_name", cid),
            "description": runtime.get("description", ""),
            "is_enabled": cfg.is_enabled if cfg else False,
            "is_running": runtime.get("is_running", False),
            "status": cfg.status if cfg else "stopped",
            "last_run_at": cfg.last_run_at.isoformat() if cfg and cfg.last_run_at else None,
            "error_message": cfg.error_message if cfg else None,
        })

    return {"channels": out}


@router.put("/{channel_id}/toggle")
async def toggle_channel(
    channel_id: str,
    body: ChannelToggle,
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable a detection channel."""
    from src.app_state import get_registry
    registry = get_registry()
    if not registry:
        raise HTTPException(503, "Channel registry not initialized")

    known = {ch["channel_id"] for ch in registry.list_channels()}
    if channel_id not in known:
        raise HTTPException(404, f"Channel '{channel_id}' not found")

    if body.enabled:
        extra: dict = {}
        if channel_id == "browser_channel":
            sc_result = await db.execute(
                select(SearchConfig).where(SearchConfig.is_active == True)
            )
            configs = sc_result.scalars().all()
            extra["search_configs"] = [{"name": c.name, "url": c.url} for c in configs]
            # Wire DB session persistence callback from app_state
            from src.app_state import get_session_callback, get_notifier
            cb = get_session_callback()
            if cb:
                extra["on_session_complete"] = cb
            notifier = get_notifier()
            if notifier:
                extra["notifier"] = notifier

        success = await registry.enable(channel_id, extra or None)
        new_status = "running" if success else "error"
    else:
        success = await registry.disable(channel_id)
        new_status = "stopped"

    # Upsert DB config record
    db_result = await db.execute(
        select(ChannelConfig).where(ChannelConfig.channel_id == channel_id)
    )
    cfg = db_result.scalar_one_or_none()
    if cfg:
        cfg.is_enabled = body.enabled
        cfg.status = new_status
        cfg.updated_at = datetime.utcnow()
    else:
        ch_info = next(
            (ch for ch in registry.list_channels() if ch["channel_id"] == channel_id), {}
        )
        cfg = ChannelConfig(
            channel_id=channel_id,
            display_name=ch_info.get("display_name", channel_id),
            description=ch_info.get("description", ""),
            is_enabled=body.enabled,
            status=new_status,
        )
        db.add(cfg)

    await db.commit()
    return {"channel_id": channel_id, "is_enabled": body.enabled, "status": new_status}


@router.post("/{channel_id}/trigger")
async def trigger_session(channel_id: str):
    """Manually trigger a single session for a channel (runs in background)."""
    from src.app_state import get_registry
    registry = get_registry()
    if not registry:
        raise HTTPException(503, "Channel registry not initialized")

    instance = registry._instances.get(channel_id)
    if not instance:
        raise HTTPException(
            400, f"Channel '{channel_id}' is not running. Enable it first."
        )

    if channel_id == "browser_channel":
        asyncio.create_task(instance.trigger_manual_session())
        return {"status": "triggered", "message": "Manual session started in background"}

    raise HTTPException(400, f"Manual trigger not supported for '{channel_id}'")
