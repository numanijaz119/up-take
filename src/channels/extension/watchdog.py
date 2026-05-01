"""Periodic watchdog for the extension channel. Registered with APScheduler on startup."""
import logging
from datetime import datetime, timezone, timedelta

from src.config import settings
import src.app_state as app_state
from src.channels.extension import state as ext_state

logger = logging.getLogger(__name__)


async def watchdog_tick() -> None:
    """Run every 60s. Check heartbeat freshness and zero-jobs-during-peak."""
    now = datetime.now(timezone.utc)
    notifier = app_state.get_notifier()
    if not notifier:
        return

    last_hb = await ext_state.get_last_heartbeat()
    if last_hb is None:
        return

    age_s = (now - last_hb).total_seconds()
    if age_s > settings.extension_heartbeat_timeout_seconds:
        if await ext_state.should_alert("heartbeat_lost"):
            await _safe_send(notifier,
                f"💤 *Extension Heartbeat Lost*\n\n"
                f"Last heartbeat: {int(age_s)}s ago.\n"
                f"Likely causes: Chrome closed, extension disabled, "
                f"backend disconnected, machine asleep.\n\n"
                f"No new jobs will be detected until the extension reconnects."
            )
        return

    if _is_peak_hour(now):
        last_job = await ext_state.get_last_job_at()
        threshold = timedelta(minutes=settings.extension_no_jobs_alert_minutes)
        if last_job is None or (now - last_job) > threshold:
            if await ext_state.should_alert("zero_jobs_peak"):
                ago_str = (
                    "never" if last_job is None
                    else f"{int((now - last_job).total_seconds() / 60)} min ago"
                )
                await _safe_send(notifier,
                    f"🔍 *No Jobs Detected During Peak Hours*\n\n"
                    f"Last job seen: {ago_str}.\n\n"
                    f"Possible causes:\n"
                    f"• Upwork DOM selectors changed (extension breakage)\n"
                    f"• Search filters too narrow\n"
                    f"• Logged out (check the tab)\n\n"
                    f"Heartbeat is alive, so the extension is running — "
                    f"the issue is upstream."
                )


def _is_peak_hour(now: datetime) -> bool:
    import zoneinfo
    tz = zoneinfo.ZoneInfo(settings.extension_peak_hours_tz)
    local_hour = now.astimezone(tz).hour
    return settings.extension_peak_hours_start <= local_hour < settings.extension_peak_hours_end


async def _safe_send(notifier, text: str) -> None:
    try:
        await notifier.send_text(text)
    except Exception as e:
        logger.error(f"Watchdog Telegram send failed: {e}")


def schedule_watchdog(scheduler) -> None:
    scheduler.add_job(
        watchdog_tick,
        "interval",
        seconds=60,
        id="extension_watchdog",
        replace_existing=True,
    )
    logger.info("Extension watchdog scheduled (every 60s)")
