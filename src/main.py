import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import settings
from src.database import init_db, AsyncSessionLocal
from src.redis_client import get_redis, close_redis
import src.app_state as app_state

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Starting Up-take…")

    await init_db()
    logger.info("Database tables created/verified")

    redis = await get_redis()
    logger.info("Redis connected")

    # Build services
    from src.notifications.telegram import TelegramNotifier
    from src.pipeline.orchestrator import PipelineOrchestrator
    from src.pipeline.dedup import DeduplicationGateway
    from src.safety.controller import SafetyController

    notifier = TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )

    orchestrator = PipelineOrchestrator(
        db_session_factory=AsyncSessionLocal,
        on_proposal_ready=notifier.send_proposal_alert,
    )

    gateway = DeduplicationGateway(
        redis=redis,
        db_session_factory=AsyncSessionLocal,
        on_new_job=orchestrator.process,
    )
    app_state.set_gateway(gateway)

    safety = SafetyController(db_session_factory=AsyncSessionLocal)
    app_state.set_safety(safety)

    # Build channel registry and register all available channels
    from src.channels.registry import ChannelRegistry
    from src.channels.extension import ExtensionChannel
    from src.channels.extension.watchdog import schedule_watchdog
    from src.models.channel import ChannelConfig
    from sqlalchemy import select
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    async def _on_job(job_data: dict) -> bool:
        return await gateway.process(job_data)

    async def _on_session_complete(session_data: dict):
        """Persist browser session stats to the database."""
        from src.models.job import BrowserSession
        async with AsyncSessionLocal() as db:
            session = BrowserSession(
                started_at=session_data.get("started_at"),
                ended_at=session_data.get("ended_at"),
                duration_s=session_data.get("duration_s"),
                jobs_found=session_data.get("jobs_found", 0),
                searches=session_data.get("searches", []),
                error=session_data.get("error"),
            )
            db.add(session)
            await db.commit()

    app_state.set_session_callback(_on_session_complete)
    app_state.set_notifier(notifier)

    registry = ChannelRegistry(on_job_detected=_on_job)
    registry.register(ExtensionChannel)
    app_state.set_registry(registry)

    # Auto-enable channels that were enabled at last shutdown
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ChannelConfig).where(ChannelConfig.is_enabled == True)
        )
        for ch_cfg in result.scalars().all():
            extra: dict = {}
            if ch_cfg.channel_id == "extension_channel":
                extra["notifier"] = notifier
            await registry.enable(ch_cfg.channel_id, extra or None)
            logger.info(f"Auto-enabled channel: {ch_cfg.channel_id}")

    # Start the extension watchdog
    scheduler = AsyncIOScheduler()
    scheduler.start()
    schedule_watchdog(scheduler)
    app.state.scheduler = scheduler

    logger.info("Up-take ready. Visit http://localhost:8000 for the dashboard.")
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down…")
    registry_inst = app_state.get_registry()
    if registry_inst:
        await registry_inst.stop_all()
    if hasattr(app.state, "scheduler") and app.state.scheduler.running:
        app.state.scheduler.shutdown(wait=False)
    await close_redis()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Up-take — Upwork Automation",
    version="1.0.0",
    description="Job discovery and proposal automation system",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"],
    allow_headers=["*"],
)

# ── API Routes ────────────────────────────────────────────────────────────────
from src.api.profile import router as profile_router
from src.api.jobs import router as jobs_router
from src.api.proposals import router as proposals_router
from src.api.channels import router as channels_router
from src.api.analytics import router as analytics_router
from src.api.settings_api import router as settings_router
from src.channels.extension.ingest_api import router as extension_router

for r in (
    profile_router, jobs_router, proposals_router, channels_router,
    analytics_router, settings_router, extension_router,
):
    app.include_router(r)


@app.get("/api/v1/health")
async def health():
    from datetime import datetime
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── HTMX Dashboard ───────────────────────────────────────────────────────────
from fastapi import Request
from fastapi.responses import HTMLResponse

_templates_dir = os.path.join(os.path.dirname(__file__), "templates")
_templates = Jinja2Templates(directory=_templates_dir)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return _templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    return _templates.TemplateResponse("jobs.html", {"request": request})


@app.get("/proposals", response_class=HTMLResponse)
async def proposals_page(request: Request):
    return _templates.TemplateResponse("proposals.html", {"request": request})


@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request):
    return _templates.TemplateResponse("channels.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return _templates.TemplateResponse("settings_page.html", {"request": request})
