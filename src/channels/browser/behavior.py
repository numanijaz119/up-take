import asyncio
import random
from playwright.async_api import Page


class HumanBehaviorEngine:
    """
    Simulates realistic human browser interaction.
    Every action introduces gaussian variance in timing and movement.
    """

    async def human_scroll(self, page: Page) -> None:
        """Scroll with variable speed, step size, and occasional backtracking."""
        direction = 1 if random.random() >= 0.05 else -1

        total_distance = abs(random.gauss(380, 120)) * direction
        if abs(total_distance) < 150:
            total_distance = 150 * direction

        steps = random.randint(8, 18)
        for _ in range(steps):
            step = (total_distance / steps) * random.gauss(1.0, 0.3)
            await page.mouse.wheel(0, step)
            await asyncio.sleep(max(0.02, random.gauss(0.08, 0.03)))

        # Occasional mid-scroll pause
        if random.random() < 0.15:
            await asyncio.sleep(random.uniform(0.5, 2.0))

    async def bezier_mouse_move(
        self, page: Page,
        start_x: float, start_y: float,
        end_x: float, end_y: float,
        steps: int = 20,
    ) -> None:
        """Move mouse along a cubic bezier curve with ease-in-out timing."""
        cp1x = start_x + random.gauss((end_x - start_x) * 0.3, 30)
        cp1y = start_y + random.gauss((end_y - start_y) * 0.3, 30)
        cp2x = start_x + random.gauss((end_x - start_x) * 0.7, 30)
        cp2y = start_y + random.gauss((end_y - start_y) * 0.7, 30)

        for i in range(steps + 1):
            t = i / steps
            x = ((1 - t) ** 3 * start_x + 3 * (1 - t) ** 2 * t * cp1x +
                 3 * (1 - t) * t ** 2 * cp2x + t ** 3 * end_x)
            y = ((1 - t) ** 3 * start_y + 3 * (1 - t) ** 2 * t * cp1y +
                 3 * (1 - t) * t ** 2 * cp2y + t ** 3 * end_y)

            await page.mouse.move(x, y)

            speed_factor = max(0.5, 1 - abs(2 * t - 1) * 0.5)
            delay = max(0.004, random.gauss(0.012, 0.004) / speed_factor)
            await asyncio.sleep(delay)

    async def reading_pause(self, num_tiles: int) -> None:
        """Pause proportional to content density."""
        base = num_tiles * random.gauss(0.6, 0.2)
        await asyncio.sleep(max(1.0, base))

    async def human_pause(self, min_s: float, max_s: float) -> None:
        """General-purpose human-like pause."""
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def hover_random_tile(self, page: Page) -> None:
        """Hover a tile without clicking — like reading the title before deciding."""
        tiles = await page.query_selector_all('article, [data-test="job-tile"], section.up-card-section')
        if not tiles:
            return
        tile = random.choice(tiles[:8])
        box = await tile.bounding_box()
        if not box:
            return

        hover_x = box["x"] + random.uniform(box["width"] * 0.1, box["width"] * 0.9)
        hover_y = box["y"] + random.uniform(box["height"] * 0.1, box["height"] * 0.9)

        vp = page.viewport_size or {"width": 1280, "height": 800}
        start_x = random.randint(100, vp["width"] - 100)
        start_y = random.randint(100, vp["height"] - 100)

        await self.bezier_mouse_move(page, start_x, start_y, hover_x, hover_y)
        await asyncio.sleep(random.gauss(1.5, 0.6))

    async def browse_distraction(self, page: Page) -> None:
        """
        Visit a non-job page to break up the job-feed browsing pattern.
        All URLs verified against real Upwork session.
        Failures are silently swallowed — distraction visits are non-critical.
        """
        distractions = [
            "https://www.upwork.com/freelancers/settings/profile",  # profile settings
            "https://www.upwork.com/ab/messages/rooms",              # messages inbox
            "https://www.upwork.com/nx/reports/overview/",           # financial overview
            "https://www.upwork.com/nx/reports/freelancer/",         # my reports
        ]
        try:
            await page.goto(random.choice(distractions), wait_until="domcontentloaded", timeout=15000)
            await self.human_pause(5, 20)
        except Exception:
            pass  # Distraction visits are non-critical — URL changes won't break anything

    async def random_mouse_wander(self, page: Page, movements: int = 3) -> None:
        """Idle mouse movement — like someone resting hand on mouse."""
        vp = page.viewport_size or {"width": 1280, "height": 800}
        x = random.randint(100, vp["width"] - 100)
        y = random.randint(100, vp["height"] - 100)
        for _ in range(movements):
            nx = x + random.gauss(0, 80)
            ny = y + random.gauss(0, 60)
            nx = max(50, min(vp["width"] - 50, nx))
            ny = max(50, min(vp["height"] - 50, ny))
            await self.bezier_mouse_move(page, x, y, nx, ny, steps=10)
            await asyncio.sleep(random.uniform(0.3, 1.5))
            x, y = nx, ny
