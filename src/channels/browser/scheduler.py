import asyncio
import random
from datetime import datetime, timedelta, time as dt_time
from typing import List, Tuple, Callable, Awaitable
from src.config import settings, DAY_WEIGHTS, HOUR_WEIGHTS, WORK_WINDOWS


class SessionScheduler:
    """
    Controls when browser sessions run.
    Produces human-like timing patterns with natural variance.
    """

    def __init__(
        self,
        work_windows: List[Tuple[dt_time, dt_time]] = WORK_WINDOWS,
        day_weights: dict = DAY_WEIGHTS,
        hour_weights: dict = HOUR_WEIGHTS,
    ):
        self.work_windows = work_windows
        self.day_weights = day_weights
        self.hour_weights = hour_weights

    def is_work_hour(self) -> bool:
        now = datetime.now().time()
        return any(start <= now <= end for start, end in self.work_windows)

    def should_run_today(self) -> bool:
        day = datetime.now().weekday()
        weight = self.day_weights.get(day, 0.5)
        return random.random() < weight

    def session_duration(self) -> int:
        duration = random.gauss(settings.session_duration_mean, settings.session_duration_stddev)
        return int(max(settings.session_duration_min, min(settings.session_duration_max, duration)))

    def next_session_gap(self) -> int:
        hour = datetime.now().hour
        if 9 <= hour <= 12:
            return random.randint(20 * 60, 40 * 60)
        elif 13 <= hour <= 15:
            return random.randint(35 * 60, 65 * 60)
        elif 16 <= hour <= 18:
            return random.randint(25 * 60, 50 * 60)
        else:
            return random.randint(45 * 60, 90 * 60)

    def seconds_until_next_window(self) -> int:
        now = datetime.now()
        current_time = now.time()
        for start, end in self.work_windows:
            if current_time < start:
                target = datetime.combine(now.date(), start)
                jitter = random.randint(-120, 300)
                return int((target - now).total_seconds()) + jitter
        tomorrow = now.date() + timedelta(days=1)
        first_start = self.work_windows[0][0]
        target = datetime.combine(tomorrow, first_start)
        jitter = random.randint(-120, 300)
        return int((target - now).total_seconds()) + jitter

    async def run_forever(
        self,
        session_runner_fn: Callable[[int], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        """Main loop. Runs sessions during work windows with human-like timing."""
        while not stop_event.is_set():
            if not self.should_run_today():
                wait = self.seconds_until_next_window()
                await self._interruptible_sleep(wait, stop_event)
                continue

            if not self.is_work_hour():
                wait = self.seconds_until_next_window()
                await self._interruptible_sleep(wait, stop_event)
                continue

            duration = self.session_duration()
            await session_runner_fn(duration)

            if stop_event.is_set():
                break

            gap = self.next_session_gap()
            await self._interruptible_sleep(gap, stop_event)

    @staticmethod
    async def _interruptible_sleep(seconds: int, stop_event: asyncio.Event) -> None:
        """Sleep that can be interrupted by stop_event."""
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(1, seconds))
        except asyncio.TimeoutError:
            pass
