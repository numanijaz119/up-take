"""
Standalone smoke-test for Channel 1 (Humanoid Browser).

Runs ONE browser session with a single search URL and prints
every job found to stdout. No database, no Redis, no Telegram required.

Usage:
    python test_channel1.py

Adjust SEARCH_URL and SESSION_DURATION_S below as needed.
"""
import asyncio
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)-35s  %(message)s",
    stream=sys.stdout,
)
# Quieten noisy libs
logging.getLogger("playwright").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

logger = logging.getLogger("test_channel1")

# ── Config ────────────────────────────────────────────────────────────────────
# Change this to any Upwork search URL you want to test.
# per_page / sort / nbs are injected automatically by _inject_per_page().
SEARCH_URL = "https://www.upwork.com/nx/search/jobs/?nbs=1&q=python+django"

# Short session: just enough to load 1-2 pages and print results.
SESSION_DURATION_S = 120  # 2 minutes

# ── Collected jobs list ───────────────────────────────────────────────────────
found_jobs: list[dict] = []


async def on_job(job: dict) -> None:
    """Called immediately when a new job is extracted."""
    found_jobs.append(job)
    title = job.get("title", "?")[:60]
    jtype = job.get("jobType", "?")
    budget = job.get("budget") or "—"
    posted = job.get("postedTime") or "?"
    skills = ", ".join(job.get("skills", [])[:4]) or "—"
    logger.info(
        f"  JOB #{len(found_jobs):03d}  [{jtype}] {title!r}  "
        f"budget={budget}  posted={posted}  skills=[{skills}]"
    )


async def main():
    from src.channels.browser.factory import BrowserFactory
    from src.channels.browser.session_runner import BrowserSessionRunner

    search_configs = [{"name": "test-search", "url": SEARCH_URL}]

    factory = BrowserFactory(timezone="America/New_York")
    runner = BrowserSessionRunner(
        factory=factory,
        on_job_detected=on_job,
        search_configs=search_configs,
        on_session_complete=None,
        notifier=None,
        stop_event=None,
    )

    logger.info("=" * 70)
    logger.info("Channel 1 smoke test — single session, no DB/Redis/Telegram")
    logger.info(f"Search URL : {SEARCH_URL}")
    logger.info(f"Duration   : {SESSION_DURATION_S}s")
    logger.info("=" * 70)

    await runner.run_session(SESSION_DURATION_S)

    logger.info("=" * 70)
    logger.info(f"DONE — total unique jobs found: {len(found_jobs)}")
    if found_jobs:
        # Dump first job as pretty JSON so we can verify field extraction
        logger.info("First job (full detail):")
        print(json.dumps(found_jobs[0], indent=2, ensure_ascii=False))
    else:
        logger.warning(
            "Zero jobs found. Check:\n"
            "  1. Is sessions/upwork_session.json present and fresh?\n"
            "  2. Did the browser navigate to the search page without Cloudflare block?\n"
            "  3. Run with DEBUG logging for more detail: "
            "LOG_LEVEL=DEBUG python test_channel1.py"
        )
    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
