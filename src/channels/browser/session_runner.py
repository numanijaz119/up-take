"""
BrowserSessionRunner — orchestrates a single human-like Upwork browsing session.

Wires together:
  - LoginManager  : loads saved session cookies so we start authenticated
  - BrowserFactory: creates a stealth-configured browser context
  - PageGuard     : detects and handles every abnormal page state after every
                    navigation (Cloudflare challenges, hard blocks, rate limits,
                    session expiry, maintenance)
  - NavigationEngine / HumanBehaviorEngine / DOMExtractor : humanoid browsing
"""
import asyncio
import logging
import random
from datetime import datetime
from typing import Callable, Awaitable, TYPE_CHECKING

from playwright.async_api import async_playwright

from src.channels.browser.factory import BrowserFactory
from src.channels.browser.behavior import HumanBehaviorEngine
from src.channels.browser.navigation import NavigationEngine
from src.channels.browser.extractor import DOMExtractor
from src.channels.browser.login_manager import LoginManager
from src.channels.browser.page_guard import PageGuard, PageState
from src.config import settings

if TYPE_CHECKING:
    from src.notifications.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

# Page states that mean "stop this session immediately"
_FATAL_STATES = {
    PageState.HARD_BLOCK,
    PageState.LOGGED_OUT,
}

# Page states that mean "skip this search but continue the session"
_SKIP_STATES = {
    PageState.RATE_LIMITED,
    PageState.MAINTENANCE,
    PageState.JS_CHALLENGE,
    PageState.MANAGED_CHALLENGE,
    PageState.INTERACTIVE_CHALLENGE,
    PageState.UNKNOWN_ERROR,
}


class BrowserSessionRunner:
    """
    Runs a single human-like browsing session end-to-end.

    One instance is reused across many sessions (the channel keeps it alive).
    All mutable per-session state is local to run_session().
    """

    def __init__(
        self,
        factory: BrowserFactory,
        on_job_detected: Callable[[dict], Awaitable[None]],
        search_configs: list[dict],
        on_session_complete: Callable[[dict], Awaitable[None]] | None = None,
        notifier: "TelegramNotifier | None" = None,
        stop_event: asyncio.Event | None = None,
    ):
        self.factory = factory
        self._on_job = on_job_detected
        self.search_configs = search_configs
        self._on_session_complete = on_session_complete
        self._notifier = notifier
        self._stop_event = stop_event

        self.behavior = HumanBehaviorEngine()
        self.navigation = NavigationEngine(self.behavior)
        self.extractor = DOMExtractor()
        self.login_manager = LoginManager()

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run_session(self, duration_seconds: int) -> None:
        """Execute one complete browsing session."""
        started_at = datetime.utcnow()
        all_jobs: list[dict] = []
        searches_done: list[str] = []
        error_msg: str | None = None
        aborted = False

        logger.info(
            f"{'='*60}\n"
            f"Session START | planned duration: {duration_seconds}s | "
            f"search configs: {len(self.search_configs)}\n"
            f"{'='*60}"
        )

        # Warn if session file is stale / missing
        self.login_manager.check_session_freshness(max_age_hours=168)

        # Load session state (None = unauthenticated)
        storage_state = self.login_manager.load_storage_state()

        try:
            async with async_playwright() as p:
                logger.debug("Launching browser…")
                browser, context, page = await self.factory.create_session(
                    p, storage_state=storage_state
                )

                guard = PageGuard(
                    notifier=self._notifier,
                    stop_event=self._stop_event,
                )

                try:
                    # ── Natural homepage entry ────────────────────────────────
                    logger.info("Navigating to Upwork homepage (natural entry)…")
                    try:
                        await self.navigation.natural_entry(page)
                    except Exception as e:
                        logger.error(f"natural_entry raised: {e}", exc_info=True)
                        error_msg = f"natural_entry: {e}"
                        aborted = True
                        await self._alert_session_error("Homepage navigation failed", str(e))
                        return

                    home_state = await guard.check_and_handle(page, "homepage")
                    if home_state in _FATAL_STATES:
                        logger.error(f"Fatal state on homepage: {home_state.value} — aborting session")
                        aborted = True
                        error_msg = f"fatal:{home_state.value}"
                        return

                    if home_state in _SKIP_STATES:
                        logger.warning(
                            f"Abnormal state on homepage ({home_state.value}) — "
                            "aborting session, will retry at next scheduled slot"
                        )
                        aborted = True
                        error_msg = f"page_state:{home_state.value}"
                        return

                    # ── Search phase ──────────────────────────────────────────
                    if not self.search_configs:
                        logger.warning(
                            "No search configs defined — skipping search phase. "
                            "Add search URLs at /channels or via PUT /api/v1/search-configs."
                        )
                    else:
                        num_searches = random.randint(
                            settings.searches_per_session_min,
                            min(settings.searches_per_session_max, len(self.search_configs)),
                        )
                        chosen_configs = random.sample(
                            self.search_configs,
                            min(num_searches, len(self.search_configs)),
                        )
                        logger.info(
                            f"Will run {len(chosen_configs)} searches this session "
                            f"(of {len(self.search_configs)} available configs)"
                        )

                        session_start = asyncio.get_event_loop().time()

                        for idx, config in enumerate(chosen_configs, 1):
                            # Check stop signal between searches
                            if self._stop_event and self._stop_event.is_set():
                                logger.info("Stop event detected — ending session early")
                                break

                            elapsed = asyncio.get_event_loop().time() - session_start
                            if elapsed >= duration_seconds:
                                logger.info(
                                    f"Session time budget exhausted ({elapsed:.0f}s >= {duration_seconds}s)"
                                )
                                break

                            config_name = config.get("name", config.get("url", "?"))
                            logger.info(
                                f"Search {idx}/{len(chosen_configs)}: '{config_name}' "
                                f"| elapsed: {elapsed:.0f}s"
                            )

                            # ── Navigate to search URL ────────────────────────
                            try:
                                await self.navigation.navigate_to_search(page, config["url"])
                            except Exception as e:
                                logger.warning(
                                    f"Navigation to '{config_name}' failed: {e} — skipping"
                                )
                                continue

                            search_state = await guard.check_and_handle(page, f"search:{config_name}")
                            if search_state in _FATAL_STATES:
                                logger.error(
                                    f"Fatal state after navigating to '{config_name}': "
                                    f"{search_state.value} — aborting session"
                                )
                                aborted = True
                                error_msg = f"fatal:{search_state.value}"
                                break

                            if search_state in _SKIP_STATES:
                                logger.warning(
                                    f"Abnormal state on '{config_name}': "
                                    f"{search_state.value} — skipping this search"
                                )
                                continue

                            searches_done.append(config_name)

                            # ── Scroll and extract ────────────────────────────
                            jobs_this_search = 0
                            scroll_rounds = random.randint(3, 6)
                            logger.debug(f"Running {scroll_rounds} scroll rounds…")

                            for scroll_idx in range(scroll_rounds):
                                if self._stop_event and self._stop_event.is_set():
                                    break

                                jobs = await self.extractor.extract_visible_jobs(page)
                                new_count = 0
                                for j in jobs:
                                    if j.get("id"):
                                        all_jobs.append(j)
                                        new_count += 1

                                jobs_this_search += new_count
                                logger.debug(
                                    f"  Scroll {scroll_idx + 1}/{scroll_rounds}: "
                                    f"extracted {new_count} jobs (session total: {len(all_jobs)})"
                                )

                                await self.behavior.human_scroll(page)
                                await self.behavior.reading_pause(len(jobs))

                                if random.random() < settings.tile_hover_probability:
                                    await self.behavior.hover_random_tile(page)

                            logger.info(
                                f"Search '{config_name}' complete: "
                                f"{jobs_this_search} job cards seen"
                            )

                            # ── Maybe open a job detail ───────────────────────
                            if (
                                random.random() < settings.job_detail_open_probability
                                and all_jobs
                            ):
                                candidates = [j for j in all_jobs[-8:] if j.get("url")]
                                if candidates:
                                    chosen_job = random.choice(candidates)
                                    logger.debug(f"Opening job detail: {chosen_job.get('url', '')[:80]}")
                                    try:
                                        desc = await self.navigation.open_job_detail(
                                            page, chosen_job["url"]
                                        )
                                        if desc:
                                            chosen_job["description"] = desc
                                            logger.debug(f"Job detail extracted ({len(desc)} chars)")

                                        detail_state = await guard.check_and_handle(
                                            page, "job-detail"
                                        )
                                        if detail_state in _FATAL_STATES:
                                            logger.error(
                                                f"Fatal state on job detail page: {detail_state.value}"
                                            )
                                            aborted = True
                                            error_msg = f"fatal:{detail_state.value}"
                                            break

                                    except Exception as e:
                                        logger.warning(f"Job detail open failed: {e} — continuing")

                            if aborted:
                                break

                    # ── Optional distraction browsing ─────────────────────────
                    if not aborted and random.random() < settings.distraction_probability:
                        logger.debug("Running distraction browse…")
                        try:
                            await self.behavior.browse_distraction(page)
                            distract_state = await guard.check_and_handle(page, "distraction")
                            if distract_state in _FATAL_STATES:
                                logger.error(
                                    f"Fatal state after distraction browse: {distract_state.value}"
                                )
                                aborted = True
                                error_msg = f"fatal:{distract_state.value}"
                        except Exception as e:
                            logger.warning(f"Distraction browse failed: {e} — ignoring")

                finally:
                    logger.debug("Closing browser…")
                    try:
                        await browser.close()
                    except Exception as e:
                        logger.warning(f"Browser close raised: {e}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Unhandled session error: {e}", exc_info=True)
            await self._alert_session_error("Unhandled session exception", str(e))

        # ── Deduplicate and emit ──────────────────────────────────────────────
        seen_ids: set[str] = set()
        unique_jobs: list[dict] = []
        for job in all_jobs:
            jid = job.get("id")
            if jid and jid not in seen_ids:
                seen_ids.add(jid)
                unique_jobs.append(job)

        logger.info(
            f"{'='*60}\n"
            f"Session END | unique jobs: {len(unique_jobs)} | "
            f"searches completed: {len(searches_done)} | "
            f"aborted: {aborted} | error: {error_msg or 'none'}\n"
            f"{'='*60}"
        )

        # Alert if session found nothing (after searches were done)
        if searches_done and not unique_jobs and not aborted:
            logger.warning(
                "Session completed but found ZERO jobs. "
                "Possible causes: DOM structure changed, all jobs were duplicates, "
                "or search URLs returned no results."
            )
            await self._alert(
                "⚠️ *Zero jobs found this session*\n"
                f"Searches run: {len(searches_done)}\n"
                "Possible: DOM selectors need update, or search returned no results.\n"
                "Check logs for details."
            )

        # Emit each unique job through the pipeline gateway
        emit_errors = 0
        for job in unique_jobs:
            try:
                await self._on_job(job)
            except Exception as e:
                emit_errors += 1
                logger.error(f"Failed to emit job '{job.get('id')}': {e}")

        if emit_errors:
            logger.warning(f"{emit_errors} jobs failed to emit to the pipeline")

        ended_at = datetime.utcnow()
        session_data = {
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_s": duration_seconds,
            "jobs_found": len(unique_jobs),
            "searches": searches_done,
            "error": error_msg,
            "aborted": aborted,
        }

        if self._on_session_complete:
            try:
                await self._on_session_complete(session_data)
            except Exception as e:
                logger.error(f"Session complete callback error: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _alert(self, message: str) -> None:
        logger.warning(f"[SessionRunner] {message.replace('*', '').replace('`', '')}")
        if self._notifier:
            try:
                await self._notifier.send_text(message)
            except Exception as e:
                logger.error(f"Telegram alert failed: {e}")

    async def _alert_session_error(self, title: str, detail: str) -> None:
        await self._alert(
            f"🔴 *Session Error: {title}*\n\n"
            f"```{detail[:300]}```\n\n"
            "Session aborted. Will retry at next scheduled slot."
        )
