"""FastAPI router for the extension's four endpoints.
Mounted at /api/v1/extension/* in src/main.py."""
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.config import settings
from src.database import get_db
import src.app_state as app_state
from src.channels.extension.models import (
    JobIngestRequest, JobIngestResponse,
    HeartbeatRequest, HeartbeatResponse,
    ExtensionEvent, ConfigResponse, SearchConfigEntry,
)
from src.channels.extension import state as ext_state
from src.models.search_config import SearchConfig as SearchConfigModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/extension", tags=["extension"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_extension_token(
    x_extension_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.extension_api_token
    if not expected or expected == "change-me-in-env":
        raise HTTPException(500, "EXTENSION_API_TOKEN not configured on server")
    if x_extension_token != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid extension token")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/jobs", response_model=JobIngestResponse,
             dependencies=[Depends(require_extension_token)])
async def ingest_jobs(payload: JobIngestRequest):
    channel = app_state.get_registry().get("extension_channel") if app_state.get_registry() else None
    if not channel or not channel.is_running:
        raise HTTPException(503, "extension_channel not enabled")

    new_count = 0
    for job in payload.jobs:
        try:
            await channel._emit(job.model_dump(mode="json"))
            new_count += 1
        except Exception as e:
            logger.error(f"Failed to emit extension job {job.id}: {e}")

    if payload.jobs:
        await ext_state.record_last_job_at(datetime.now(timezone.utc))

    logger.info(
        f"Extension batch: received={len(payload.jobs)} from {payload.tab_url} "
        f"(ext v{payload.extension_version})"
    )
    return JobIngestResponse(
        received=len(payload.jobs),
        new=new_count,
        duplicates=0,
    )


@router.post("/heartbeat", response_model=HeartbeatResponse,
             dependencies=[Depends(require_extension_token)])
async def heartbeat(payload: HeartbeatRequest):
    await ext_state.record_heartbeat(
        version=payload.extension_version,
        tabs_count=len(payload.tabs),
    )
    if payload.last_job_at:
        await ext_state.record_last_job_at(payload.last_job_at)
    return HeartbeatResponse(ok=True, server_time=datetime.now(timezone.utc))


@router.post("/event", dependencies=[Depends(require_extension_token)])
async def report_event(payload: ExtensionEvent):
    await ext_state.record_event(payload.kind, payload.detail)
    logger.warning(
        f"Extension event: kind={payload.kind} url={payload.url} detail={payload.detail}"
    )

    notifier = app_state.get_notifier()
    if notifier and payload.kind in {"logged_out", "cloudflare_challenge"}:
        if await ext_state.should_alert(f"event:{payload.kind}"):
            msg = {
                "logged_out": (
                    "🔑 *Upwork Session Expired*\n\n"
                    "The extension reports the Upwork tab is no longer logged in.\n"
                    f"URL: {payload.url}\n\n"
                    "Open Upwork in your browser, log in normally, and the "
                    "extension will resume on the next reload."
                ),
                "cloudflare_challenge": (
                    "🛡️ *Cloudflare Challenge*\n\n"
                    "The extension hit a Cloudflare verification page.\n"
                    f"URL: {payload.url}\n\n"
                    "Open that tab in Chrome and solve the challenge; "
                    "the extension will resume automatically."
                ),
            }[payload.kind]
            try:
                await notifier.send_text(msg)
            except Exception as e:
                logger.error(f"Telegram event alert failed: {e}")

    if notifier and payload.kind == "selector_breakage":
        if await ext_state.should_alert("event:selector_breakage"):
            try:
                await notifier.send_text(
                    f"⚙️ *Extension Selector Broken*\n\n"
                    f"The extension cannot find job tiles on the page.\n"
                    f"URL: {payload.url}\n"
                    f"Detail: {payload.detail or 'none'}\n\n"
                    "Upwork may have changed their DOM. Update selectors in extension/extractor.js."
                )
            except Exception as e:
                logger.error(f"Telegram selector alert failed: {e}")

    return {"ok": True}


@router.get("/config", response_model=ConfigResponse,
            dependencies=[Depends(require_extension_token)])
async def get_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SearchConfigModel).where(SearchConfigModel.is_active == True)
    )
    rows = result.scalars().all()
    searches = [
        SearchConfigEntry(label=r.name, url=r.url)
        for r in rows
    ] or [
        SearchConfigEntry(
            label="Best Matches",
            url="https://www.upwork.com/nx/find-work/best-matches",
        ),
    ]
    return ConfigResponse(
        searches=searches,
        reload_min_seconds=settings.extension_reload_min_seconds,
        reload_max_seconds=settings.extension_reload_max_seconds,
        quiet_hours_start=settings.extension_quiet_hours_start,
        quiet_hours_end=settings.extension_quiet_hours_end,
        heartbeat_interval_seconds=settings.extension_heartbeat_interval_seconds,
        config_refetch_interval_seconds=settings.extension_config_refetch_seconds,
    )
