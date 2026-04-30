"""
BrowserSessionRunner — orchestrates a single human-like Upwork browsing session.

Wires together:
  - LoginManager  : loads saved session cookies so we start authenticated
  - BrowserFactory: creates a stealth-configured browser context
  - PageGuard     : detects and handles every abnormal page state after every
                    navigation (Cloudflare challenges, hard blocks, rate limits,
                    session expiry, maintenance)
  - NavigationEngine / HumanBehaviorEngine / DOMExtractor : humanoid browsing

Pagination behaviour (validated against real Upwork HTML):
  - Upwork uses traditional page-based pagination, NOT infinite scroll.
  - Default per_page=10; we inject per_page=50 into every search URL so each
    page load returns up to 50 jobs instead of 10.
  - After exhausting a page we click [data-test="next-page"] (up to
    MAX_PAGES_PER_SEARCH pages) if the session time budget allows.
"""
import asyncio
import logging
import random
from datetime import datetime
from typing import Callable, Awaitable, TYPE_CHECKING
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from patchright.async_api import async_playwright

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

# Upwork supports per_page values of 10, 20, 50. Use 50 for maximum yield.
_PER_PAGE = 50

# Max pages to browse per search config per session.
# A real freelancer rarely goes past page 3 — keeps behaviour natural.
MAX_PAGES_PER_SEARCH = 3


def _inject_per_page(url: str, per_page: int = _PER_PAGE) -> str:
    """
    Normalise a search URL before first use:
      - Sets per_page=50  (Upwork default is 10; 50 gives 5x more jobs per load)
      - Sets sort=recency if no sort is specified (newest jobs first)
      - Preserves nbs=1   (Upwork "new best search" flag — must be kept)
      - Resets page=1     (pagination loop controls page navigation)
      - Strips referrer_url_path tracking param

    sort=recency is only injected when the URL has no sort param already — if
    you explicitly configure sort=relevance it will be respected.

    Example:
        https://www.upwork.com/nx/search/jobs/?nbs=1&q=python&per_page=10
        → https://www.upwork.com/nx/search/jobs/?nbs=1&q=python&per_page=50&sort=recency
    """
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params["per_page"] = [str(per_page)]
        params["nbs"] = ["1"]                    # required for correct results
        params.setdefault("sort", ["recency"])   # newest-first unless caller overrides
        params.pop("page", None)                 # reset to page 1
        params.pop("referrer_url_path", None)    # strip tracking
        new_query = urlencode({k: v[0] for k, v in params.items()})
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url  # return original if parsing fails


async def _get_next_page_url(page) -> str | None:
    """
    Extract the href of the [data-test="next-page"] link.
    Returns None if:
      - the link doesn't exist (last page)
      - the link is disabled (aria-disabled="true")
    """
    try:
        next_link = await page.query_selector('[data-test="next-page"]')
        if not next_link:
            return None
        # Check if disabled (first page has prev-page disabled; last has next-page disabled)
        aria_disabled = await next_link.get_attribute("aria-disabled")
        if aria_disabled == "true":
            return None
        href = await next_link.get_attribute("href")
        if not href:
            return None
        # Resolve to absolute URL
        base = "https://www.upwork.com"
        return href if href.startswith("http") else base + href
    except Exception as e:
        logger.debug(f"_get_next_page_url failed: {e}")
        return None


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
        searches_done: list[str] = []
        error_msg: str | None = None
        aborted = False

        # Session-level tracking (replaces end-of-session batch)
        session_seen_ids: set[str] = set()   # cross-search dedup — same job in two searches emitted once
        session_jobs_found: int = 0          # unique jobs emitted this session
        emit_errors: int = 0                 # failed emit() calls
        recent_jobs_buffer: list[dict] = []  # rolling last-8 for job detail page selection

        logger.info(
            f"{'='*60}\n"
            f"Session START | planned duration: {duration_seconds}s | "
            f"search configs: {len(self.search_configs)}\n"
            f"{'='*60}"
        )

        self.login_manager.check_session_freshness(max_age_hours=168)
        storage_state = self.login_manager.load_storage_state()

        try:
            async with async_playwright() as p:
                logger.debug("Launching browser…")
                context, page = await self.factory.create_session(
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
                        available = len(self.search_configs)
                        num_searches = random.randint(
                            min(settings.searches_per_session_min, available),
                            min(settings.searches_per_session_max, available),
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

                            # ── Inject per_page=50 into the search URL ────────
                            # Upwork defaults to 10 per page; scrolling does NOT
                            # load more (it's traditional pagination, not infinite
                            # scroll). per_page=50 gives 5x more jobs per page load.
                            first_page_url = _inject_per_page(config["url"])
                            logger.info(
                                f"Search {idx}/{len(chosen_configs)}: '{config_name}' "
                                f"| per_page={_PER_PAGE} | elapsed: {elapsed:.0f}s"
                            )

                            # ── Paginated browse loop ─────────────────────────
                            current_url = first_page_url
                            jobs_this_search = 0

                            for page_num in range(1, MAX_PAGES_PER_SEARCH + 1):
                                if self._stop_event and self._stop_event.is_set():
                                    break
                                elapsed = asyncio.get_event_loop().time() - session_start
                                if elapsed >= duration_seconds:
                                    logger.info("Time budget exhausted mid-pagination")
                                    break

                                logger.info(
                                    f"  Page {page_num}/{MAX_PAGES_PER_SEARCH} "
                                    f"of '{config_name}'"
                                )

                                # Navigate (first page = fresh goto, subsequent = next-page link)
                                try:
                                    await self.navigation.navigate_to_search(page, current_url)
                                except Exception as e:
                                    logger.warning(
                                        f"Navigation to '{config_name}' p{page_num} failed: {e}"
                                        " — skipping"
                                    )
                                    break

                                page_state = await guard.check_and_handle(
                                    page, f"search:{config_name}:p{page_num}"
                                )
                                if page_state in _FATAL_STATES:
                                    logger.error(
                                        f"Fatal state on '{config_name}' p{page_num}: "
                                        f"{page_state.value} — aborting session"
                                    )
                                    aborted = True
                                    error_msg = f"fatal:{page_state.value}"
                                    break
                                if page_state in _SKIP_STATES:
                                    logger.warning(
                                        f"Abnormal state on '{config_name}' p{page_num}: "
                                        f"{page_state.value} — stopping pagination for this search"
                                    )
                                    break

                                if page_num == 1:
                                    searches_done.append(config_name)

                                # ── Scroll through the page and extract ───────
                                # With per_page=50, one page has up to 50 job tiles.
                                # We do 2–4 scroll rounds to naturally pass through them.
                                scroll_rounds = random.randint(2, 4)
                                page_jobs_seen: set[str] = set()

                                for scroll_idx in range(scroll_rounds):
                                    if self._stop_event and self._stop_event.is_set():
                                        break

                                    jobs = await self.extractor.extract_visible_jobs(page)
                                    new_count = 0
                                    for j in jobs:
                                        jid = j.get("id")
                                        if jid and jid not in page_jobs_seen:
                                            page_jobs_seen.add(jid)
                                            if jid not in session_seen_ids:
                                                session_seen_ids.add(jid)
                                                session_jobs_found += 1
                                                recent_jobs_buffer.append(j)
                                                if len(recent_jobs_buffer) > 8:
                                                    recent_jobs_buffer.pop(0)
                                                # Emit immediately — don't wait until session end
                                                try:
                                                    await self._on_job(j)
                                                except Exception as e:
                                                    emit_errors += 1
                                                    logger.error(f"Failed to emit job '{jid}': {e}")
                                                new_count += 1

                                    logger.debug(
                                        f"    Scroll {scroll_idx + 1}/{scroll_rounds}: "
                                        f"{new_count} new jobs emitted "
                                        f"(page total: {len(page_jobs_seen)}, "
                                        f"session total: {session_jobs_found})"
                                    )

                                    await self.behavior.human_scroll(page)
                                    await self.behavior.reading_pause(len(jobs))

                                    if random.random() < settings.tile_hover_probability:
                                        await self.behavior.hover_random_tile(page)

                                jobs_this_search += len(page_jobs_seen)
                                logger.info(
                                    f"  Page {page_num} complete: "
                                    f"{len(page_jobs_seen)} unique jobs "
                                    f"(search total so far: {jobs_this_search})"
                                )

                                # ── Maybe open a job detail ───────────────────
                                if (
                                    random.random() < settings.job_detail_open_probability
                                    and recent_jobs_buffer
                                ):
                                    candidates = [j for j in recent_jobs_buffer if j.get("url")]
                                    if candidates:
                                        chosen_job = random.choice(candidates)
                                        logger.debug(
                                            f"Opening job detail: "
                                            f"{chosen_job.get('url', '')[:80]}"
                                        )
                                        try:
                                            desc = await self.navigation.open_job_detail(
                                                page, chosen_job["url"]
                                            )
                                            if desc:
                                                chosen_job["description"] = desc
                                                logger.debug(
                                                    f"Job detail extracted ({len(desc)} chars)"
                                                )

                                            detail_state = await guard.check_and_handle(
                                                page, "job-detail"
                                            )
                                            if detail_state in _FATAL_STATES:
                                                logger.error(
                                                    f"Fatal state on job detail: "
                                                    f"{detail_state.value}"
                                                )
                                                aborted = True
                                                error_msg = f"fatal:{detail_state.value}"
                                                break

                                        except Exception as e:
                                            logger.warning(
                                                f"Job detail open failed: {e} — continuing"
                                            )

                                if aborted:
                                    break

                                # ── Check for next page ───────────────────────
                                next_url = await _get_next_page_url(page)
                                if not next_url:
                                    logger.info(
                                        f"  No next page for '{config_name}' "
                                        f"(reached last page at p{page_num})"
                                    )
                                    break

                                # Decide whether to continue to next page:
                                # - always go to page 2 (likely has fresh jobs)
                                # - page 3+ only if < 60% of time budget used
                                elapsed_frac = (
                                    (asyncio.get_event_loop().time() - session_start)
                                    / duration_seconds
                                )
                                if page_num >= 2 and elapsed_frac > 0.6:
                                    logger.info(
                                        f"  Skipping further pages (time budget "
                                        f"{elapsed_frac:.0%} used)"
                                    )
                                    break

                                # Human pause before turning page
                                await self.behavior.human_pause(1.5, 4.0)
                                # Re-inject per_page=50 — Upwork's own "next page" href
                                # uses the default per_page=10, not our override
                                current_url = _inject_per_page(next_url)

                            if aborted:
                                break

                    # ── Optional distraction browsing ─────────────────────────
                    if not aborted and random.random() < settings.distraction_probability:
                        logger.debug("Running distraction browse…")
                        try:
                            await self.behavior.browse_distraction(page)
                            distract_state = await guard.check_and_handle(
                                page, "distraction"
                            )
                            if distract_state in _FATAL_STATES:
                                logger.error(
                                    f"Fatal state after distraction browse: "
                                    f"{distract_state.value}"
                                )
                                aborted = True
                                error_msg = f"fatal:{distract_state.value}"
                        except Exception as e:
                            logger.warning(f"Distraction browse failed: {e} — ignoring")

                finally:
                    logger.debug("Closing browser…")
                    try:
                        await context.close()
                    except Exception as e:
                        logger.warning(f"Context close raised: {e}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Unhandled session error: {e}", exc_info=True)
            await self._alert_session_error("Unhandled session exception", str(e))

        # ── Session summary ───────────────────────────────────────────────────
        # Jobs were emitted immediately on discovery — no batch emit needed here.
        logger.info(
            f"{'='*60}\n"
            f"Session END | unique jobs emitted: {session_jobs_found} | "
            f"searches completed: {len(searches_done)} | "
            f"aborted: {aborted} | error: {error_msg or 'none'}\n"
            f"{'='*60}"
        )

        if searches_done and session_jobs_found == 0 and not aborted:
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

        if emit_errors:
            logger.warning(f"{emit_errors} jobs failed to emit to the pipeline")

        ended_at = datetime.utcnow()
        session_data = {
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_s": duration_seconds,
            "jobs_found": session_jobs_found,
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
