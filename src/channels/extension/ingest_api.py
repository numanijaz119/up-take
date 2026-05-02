"""FastAPI router for the extension's three endpoints.
Mounted at /api/v1/extension/* in src/main.py."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select

from src.config import settings
from src.database import AsyncSessionLocal
import src.app_state as app_state
from src.channels.extension.models import (
    JobIngestRequest, JobIngestResponse,
    HeartbeatRequest, HeartbeatResponse,
    ExtensionEvent,
)
from src.channels.extension import state as ext_state
from src.models.job import Job
from src.pipeline.dedup import parse_posted_time

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_fresh(job) -> bool:
    """Return False if the job's posted_time is older than MAX_JOB_AGE_HOURS."""
    posted_at_str = parse_posted_time(job.posted_time)
    if not posted_at_str:
        return True  # unknown age — let it through
    try:
        posted_dt = datetime.fromisoformat(posted_at_str)
        if posted_dt.tzinfo is None:
            posted_dt = posted_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - posted_dt <= timedelta(hours=settings.max_job_age_hours)
    except Exception:
        return True


async def _emit_one(channel, job_data: dict) -> bool:
    """Emit one job. Returns True only if the dedup gateway confirmed it as new."""
    try:
        return bool(await channel._emit(job_data))
    except Exception as e:
        logger.error(f"Failed to emit job {job_data.get('id')}: {e}")
        return False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/jobs", response_model=JobIngestResponse,
             dependencies=[Depends(require_extension_token)])
async def ingest_jobs(payload: JobIngestRequest):
    channel = app_state.get_registry().get("extension_channel") if app_state.get_registry() else None
    if not channel or not channel.is_running:
        raise HTTPException(503, "extension_channel not enabled")

    if not payload.jobs:
        return JobIngestResponse(received=0, new=0, duplicates=0, stale=0)

    # ── Step 1: Freshness pre-filter ──────────────────────────────────────────
    # Reject jobs older than MAX_JOB_AGE_HOURS before any DB work.
    fresh_jobs = [j for j in payload.jobs if _is_fresh(j)]
    stale_count = len(payload.jobs) - len(fresh_jobs)

    if not fresh_jobs:
        logger.info(
            f"Extension batch: received={len(payload.jobs)} all stale "
            f"(>{settings.max_job_age_hours}h old) from {payload.tab_url}"
        )
        return JobIngestResponse(
            received=len(payload.jobs), new=0, duplicates=0, stale=stale_count
        )

    # ── Step 2: Bulk DB dedup ─────────────────────────────────────────────────
    # One query to find which fresh job IDs are already in the database.
    incoming_ids = [j.id for j in fresh_jobs]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Job.upwork_id).where(Job.upwork_id.in_(incoming_ids))
        )
        known_ids = {row[0] for row in result}

    new_jobs = [j for j in fresh_jobs if j.id not in known_ids]
    duplicate_count = len(fresh_jobs) - len(new_jobs)

    if not new_jobs:
        logger.info(
            f"Extension batch: received={len(payload.jobs)} "
            f"stale={stale_count} duplicates={duplicate_count} new=0 "
            f"from {payload.tab_url}"
        )
        return JobIngestResponse(
            received=len(payload.jobs), new=0,
            duplicates=duplicate_count, stale=stale_count
        )

    # ── Step 3: Emit each new job concurrently ────────────────────────────────
    # Each job triggers its own independent pipeline run.
    # _emit_one returns True only when the dedup gateway confirms it's new.
    results = await asyncio.gather(
        *[_emit_one(channel, j.model_dump(mode="json")) for j in new_jobs],
    )
    new_count = sum(results)

    if new_count:
        await ext_state.record_last_job_at(datetime.now(timezone.utc))

    logger.info(
        f"Extension batch: received={len(payload.jobs)} "
        f"stale={stale_count} duplicates={duplicate_count} new={new_count} "
        f"from {payload.tab_url} (ext v{payload.extension_version})"
    )
    return JobIngestResponse(
        received=len(payload.jobs),
        new=new_count,
        duplicates=duplicate_count,
        stale=stale_count,
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
