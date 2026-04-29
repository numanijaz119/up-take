# Channel 1 — Humanoid Browser: Complete Technical Deep Dive

> **Phase 1 focus.** This document covers everything about how the browser channel
> works, what data it collects from Upwork, how detection-evasion is implemented,
> how to test it, what stealth rating it currently has, and a concrete roadmap of
> improvements to make it harder to detect.

---

## Table of Contents

1. [What Channel 1 Actually Does](#1-what-channel-1-actually-does)
2. [Architecture — How All the Pieces Fit](#2-architecture--how-all-the-pieces-fit)
3. [Session Lifecycle — Step by Step](#3-session-lifecycle--step-by-step)
4. [Code Deep Dive — Every Layer Explained](#4-code-deep-dive--every-layer-explained)
   - 4.1 [Scheduler — When Sessions Run](#41-scheduler--when-sessions-run)
   - 4.2 [Factory — Building the Browser](#42-factory--building-the-browser)
   - 4.3 [Login Manager — Session Persistence](#43-login-manager--session-persistence)
   - 4.4 [Navigation Engine — Acting Like a Human](#44-navigation-engine--acting-like-a-human)
   - 4.5 [Behavior Engine — Humanoid Interactions](#45-behavior-engine--humanoid-interactions)
   - 4.6 [DOM Extractor — What Data We Pull](#46-dom-extractor--what-data-we-pull)
   - 4.7 [Page Guard — Edge Case Handling](#47-page-guard--edge-case-handling)
   - 4.8 [Session Runner — The Orchestrator](#48-session-runner--the-orchestrator)
   - 4.9 [BrowserChannel — Top Level](#49-browserchannel--top-level)
5. [What Data Is Extracted From Upwork](#5-what-data-is-extracted-from-upwork)
6. [How the DOM Selectors Work (Without Upwork Source Code)](#6-how-the-dom-selectors-work-without-upwork-source-code)
7. [Edge Cases and How Each Is Handled](#7-edge-cases-and-how-each-is-handled)
8. [Stealth Rating and Analysis](#8-stealth-rating-and-analysis)
9. [Setup Guide — First Run](#9-setup-guide--first-run)
10. [Testing Guide — How to Verify Everything Works](#10-testing-guide--how-to-verify-everything-works)
11. [What to Improve to Become More Undetectable](#11-what-to-improve-to-become-more-undetectable)

---

## 1. What Channel 1 Actually Does

Channel 1 is a **read-only browser automation** that behaves exactly like a
real freelancer browsing Upwork job feeds to look for work.

**It does:**

- Opens a real visible Chrome browser window (not headless)
- Navigates to Upwork like a human — homepage first, then find-work
- Browses your configured search URLs
- Scrolls through job listings, hovers cards, reads titles
- Occasionally clicks into a job detail page, reads it, goes back
- Extracts job data from the rendered HTML (no API calls)
- Sends job data into the pipeline → filter → Claude analysis → proposal generation

**It does NOT:**

- Submit proposals
- Click any buttons or forms
- Modify any page
- Make any Upwork API calls
- Store or transmit your credentials anywhere

---

## 2. Architecture — How All the Pieces Fit

```
BrowserChannel (channel.py)
│
├── SessionScheduler (scheduler.py)
│     Decides WHEN to run sessions based on time-of-day weights,
│     day-of-week weights, and work windows
│
└── BrowserSessionRunner (session_runner.py)
      Orchestrates a single session. Wires everything together.
      │
      ├── LoginManager (login_manager.py)
      │     Loads saved Upwork cookies from sessions/upwork_session.json
      │
      ├── BrowserFactory (factory.py)
      │     Creates the Chrome browser with stealth config + saved cookies
      │
      ├── PageGuard (page_guard.py)
      │     Checks page state after every navigation.
      │     Handles: Cloudflare, hard blocks, rate limits, session expiry
      │
      ├── NavigationEngine (navigation.py)
      │     Controls where the browser goes and in what order
      │
      ├── HumanBehaviorEngine (behavior.py)
      │     Scrolling, mouse movement, pauses, distraction visits
      │
      └── DOMExtractor (extractor.py)
            Pulls job data from rendered page HTML via evaluate()
```

### Data flow after extraction

```
DOMExtractor
    → job dict (id, title, description, budget, skills…)
    → BrowserSessionRunner._on_job()
    → DeduplicationGateway (Redis 7-day TTL dedup)
    → PipelineOrchestrator
        → QuickFilter (budget, skills, blacklist, proposals count…)
        → DeepAnalyzer (Claude, temp=0.2, opportunity score)
        → ProposalGenerator (Claude, temp=0.7 generate + 0.1 quality check)
        → TelegramNotifier (send_proposal_alert with Approve/Skip buttons)
```

---

## 3. Session Lifecycle — Step by Step

Here is the complete sequence of what happens when a session runs:

```
1. Scheduler decides it is time to run
   └── is_work_hour() = True, should_run_today() = True
   └── session_duration = gauss(720s, 240s) = e.g. 690s

2. SessionRunner.run_session(690) begins
   └── LoginManager.load_storage_state()
       → reads sessions/upwork_session.json
       → returns dict of cookies + localStorage
       → warns if file missing or >7 days old

3. Playwright async_playwright() context opens
   └── BrowserFactory.create_session(playwright, storage_state)
       → chromium.launch(headless=False, args=[...stealth args...])
       → browser.new_context(storage_state=<cookies>, viewport, UA, locale…)
       → page = context.new_page()
       → stealth_async(page)             ← playwright-stealth patches
       → _apply_extra_patches(page)      ← WebGL, plugins, battery, webdriver

4. NavigationEngine.natural_entry(page)
   └── goto("https://www.upwork.com")    ← homepage first
   └── human_pause(3–8s)
   └── random_mouse_wander(3 movements)  ← idle mouse before navigating
   └── goto("https://www.upwork.com/nx/find-work/")
   └── human_pause(2–5s)

5. PageGuard.check_and_handle(page, "homepage")
   └── _detect() inspects title + URL + DOM selectors
   └── If OK → continue
   └── If challenge/block → handle (see section 7)

6. For each chosen search config (2–4 chosen at random):
   a. navigate_to_search(page, config.url)
      └── goto(url, wait_until="domcontentloaded")
      └── human_pause(2–6s)
   b. PageGuard.check_and_handle(page, "search:name")
   c. 3–6 scroll rounds:
      → extract_visible_jobs(page)        ← evaluate() JS into DOM
      → human_scroll(page)               ← gaussian scroll steps
      → reading_pause(num_jobs)          ← proportional wait
      → 40% chance: hover_random_tile()  ← bezier curve mouse hover
   d. 35% chance: open_job_detail(page, job.url)
      → goto(job_url)
      → human_pause(3–10s)
      → human_scroll() x2
      → extract full description
      → page.go_back()
      → PageGuard.check_and_handle(page, "job-detail")

7. 30% chance: browse_distraction(page)
   → goto one of: /settings, /messages, /my-stats
   → human_pause(5–20s)

8. Browser closes

9. Deduplicate jobs by ID within session
10. Emit each unique job → pipeline

11. _wrapped_session_complete()
    → track consecutive failures
    → alert Telegram if 3+ failures in a row
    → persist session stats to BrowserSession DB table
```

---

## 4. Code Deep Dive — Every Layer Explained

### 4.1 Scheduler — When Sessions Run

**File:** `src/channels/browser/scheduler.py`

The scheduler prevents a machine-like pattern of running at exactly the same
time every day. Every timing decision has randomness baked in.

```python
# Work windows — sessions only run in these time ranges
WORK_WINDOWS = [
    (time(9, 0),  time(12, 30)),   # Morning block
    (time(14, 0), time(18, 0)),    # Afternoon block
    (time(20, 0), time(22, 30)),   # Evening block
]

# Day weights — probability of running on each day of the week
DAY_WEIGHTS = {
    0: 1.0,   # Monday    — full probability
    1: 0.95,  # Tuesday
    2: 0.9,   # Wednesday
    3: 0.85,  # Thursday
    4: 0.7,   # Friday    — less likely
    5: 0.4,   # Saturday  — much less
    6: 0.25,  # Sunday    — rare
}
```

**Session duration** uses a Gaussian distribution:

```python
duration = random.gauss(720, 240)   # mean 12 min, stddev 4 min
# Clamped: min 5 min, max 25 min
```

This means most sessions are 8–16 minutes but some are shorter or longer —
exactly like a real person who sometimes quickly scans and sometimes browses longer.

**Gap between sessions** depends on time of day:

```python
if 9 <= hour <= 12:   gap = random.randint(20*60, 40*60)  # 20–40 min
elif 13 <= hour <= 15: gap = random.randint(35*60, 65*60)  # 35–65 min
elif 16 <= hour <= 18: gap = random.randint(25*60, 50*60)  # 25–50 min
else:                  gap = random.randint(45*60, 90*60)  # 45–90 min
```

**Why this matters for detection:** Bot traffic has perfectly uniform gaps
between requests. Our varied gaps look like a person who sometimes gets
distracted between browsing sessions.

---

### 4.2 Factory — Building the Browser

**File:** `src/channels/browser/factory.py`

The factory creates a Chrome instance that is indistinguishable from a user
running Chrome normally. Two layers of stealth are applied:

**Layer 1 — Launch args:**

```python
browser = await playwright.chromium.launch(
    headless=False,   # REAL visible window — not headless
    args=[
        "--disable-blink-features=AutomationControlled",  # removes navigator.webdriver
        "--no-sandbox",
        "--disable-dev-shm-usage",
        f"--window-size={width},{height}",                # randomized per session
    ],
)
```

**Layer 2 — Context fingerprint randomization:**

```python
width  = random.randint(1280, 1440)   # slightly different every session
height = random.randint(780, 900)
user_agent = random.choice(USER_AGENTS)   # 5 real Chrome UA strings

context = await browser.new_context(
    viewport        = {"width": width, "height": height},
    user_agent      = user_agent,
    locale          = "en-US",
    timezone_id     = settings.browser_timezone,  # "America/New_York"
    color_scheme    = "light",
    device_scale_factor = random.choice([1, 1, 1, 2]),  # 75% = 1x, 25% = 2x
    extra_http_headers = {"Accept-Language": "en-US,en;q=0.9"},
    storage_state   = <your_saved_upwork_cookies>,   # starts authenticated
)
```

**Layer 3 — JS patches injected at page load:**

```python
await page.add_init_script("""
    // 1. Chrome extension object (all real Chromes have this)
    if (!window.chrome) {
        window.chrome = { runtime: {}, loadTimes: function(){}, app: {} };
    }

    // 2. Realistic plugins list (bots have 0 plugins; real Chrome has these)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [{name:'Chrome PDF Plugin'}, {name:'Chrome PDF Viewer'}, ...]
    });

    // 3. WebGL — return real GPU strings instead of "Google SwiftShader" (headless giveaway)
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel(R) Iris(TM) Plus Graphics 640';
        return _original.apply(this, arguments);
    };

    // 4. Battery API — returns a realistic charge level
    navigator.getBattery = async () => ({
        charging: Math.random() > 0.4,
        level: 0.6 + Math.random() * 0.4,   // 60–100%
    });

    // 5. Remove webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 6. Languages
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
""")
```

**Layer 4 — playwright-stealth:**

```python
from playwright_stealth import stealth_async
await stealth_async(page)
```

This library patches ~20 additional fingerprint vectors including:
`navigator.permissions`, `chrome.runtime`, `window.outerWidth`,
`navigator.hardwareConcurrency`, `navigator.deviceMemory`, and more.

---

### 4.3 Login Manager — Session Persistence

**File:** `src/channels/browser/login_manager.py`

Playwright's `storage_state` saves everything a browser context knows about
a domain: cookies, localStorage, sessionStorage. When we inject this on
context creation, Upwork thinks this is a continuing session from a logged-in
user — no login page, no 2FA, no redirect.

```python
# Save (run once manually)
await context.storage_state(path="sessions/upwork_session.json")

# Load (automatic on every session)
storage_state = json.load(open("sessions/upwork_session.json"))
context = await browser.new_context(storage_state=storage_state, ...)
```

The saved file looks like:

```json
{
  "cookies": [
    {"name": "master_access_token", "value": "...", "domain": ".upwork.com", ...},
    {"name": "oauth2_global_js_token", "value": "...", ...},
    {"name": "XSRF-TOKEN", "value": "...", ...},
    ...40+ more cookies...
  ],
  "origins": [
    {"origin": "https://www.upwork.com", "localStorage": [...]}
  ]
}
```

**Freshness check** — warns you if the file is older than 7 days:

```python
def check_session_freshness(self, max_age_hours=168.0) -> bool:
    age = self.session_file_age_hours()
    if age > max_age_hours:
        logger.warning(f"Session file is {age:.1f}h old — consider refreshing")
```

**Cookie validation** — detects if session has expired mid-run:

```python
async def detect_logged_out_and_alert(self, context, notifier):
    cookies = await context.cookies(["https://www.upwork.com"])
    cookie_names = {c["name"] for c in cookies}
    has_session = bool(cookie_names & {"master_access_token", "oauth2_global_js_token"})
    # If False → send Telegram alert with re-login instructions
```

---

### 4.4 Navigation Engine — Acting Like a Human

**File:** `src/channels/browser/navigation.py`

The critical insight here: **real users never jump cold to a deep URL.**
They type a domain, see the homepage, then navigate from there.

```python
async def natural_entry(self, page: Page) -> None:
    # Step 1: Homepage first (like typing upwork.com in the address bar)
    await page.goto("https://www.upwork.com", wait_until="domcontentloaded")
    await self.behavior.human_pause(3, 8)        # 3–8s reading the homepage
    await self.behavior.random_mouse_wander(3)    # move mouse around idly

    # Step 2: Navigate to the job feed (like clicking "Find Work")
    await page.goto("https://www.upwork.com/nx/find-work/", wait_until="domcontentloaded")
    await self.behavior.human_pause(2, 5)
```

**Job detail opening** — when the channel visits a job detail:

```python
async def open_job_detail(self, page, job_url):
    await page.goto(job_url, wait_until="domcontentloaded")
    await self.behavior.human_pause(3, 10)     # Read for 3–10s
    await self.behavior.human_scroll(page)     # Scroll down
    await self.behavior.human_pause(2, 6)      # Keep reading
    await self.behavior.human_scroll(page)     # Scroll more
    # Extract full description
    await page.go_back()                       # Go back to search
    await self.behavior.human_pause(1, 4)
```

---

### 4.5 Behavior Engine — Humanoid Interactions

**File:** `src/channels/browser/behavior.py`

Every interaction is modelled on real human behavior with mathematical variance.

**Scrolling — Gaussian steps with occasional backtrack:**

```python
async def human_scroll(self, page):
    direction  = 1 if random.random() >= 0.05 else -1   # 5% chance scroll up
    distance   = abs(random.gauss(380, 120)) * direction  # ~380px mean, varies
    steps      = random.randint(8, 18)                   # 8–18 wheel events

    for _ in range(steps):
        step = (distance / steps) * random.gauss(1.0, 0.3)  # each step varies
        await page.mouse.wheel(0, step)
        await asyncio.sleep(max(0.02, random.gauss(0.08, 0.03)))  # 50–110ms between steps

    if random.random() < 0.15:    # 15% chance: pause mid-scroll
        await asyncio.sleep(random.uniform(0.5, 2.0))
```

Compare this to a bot's scroll: `window.scrollBy(0, 5000)` — a single instant
jump, zero intermediate events, impossible for a human.

**Mouse movement — Cubic Bezier curve:**

```python
async def bezier_mouse_move(self, page, start_x, start_y, end_x, end_y, steps=20):
    # Control points with gaussian noise — no two paths are identical
    cp1x = start_x + random.gauss((end_x - start_x) * 0.3, 30)
    cp1y = start_y + random.gauss((end_y - start_y) * 0.3, 30)
    cp2x = start_x + random.gauss((end_x - start_x) * 0.7, 30)
    cp2y = start_y + random.gauss((end_y - start_y) * 0.7, 30)

    for i in range(steps + 1):
        t = i / steps
        # Cubic Bezier formula
        x = (1-t)³*start_x + 3*(1-t)²*t*cp1x + 3*(1-t)*t²*cp2x + t³*end_x
        y = (1-t)³*start_y + 3*(1-t)²*t*cp1y + 3*(1-t)*t²*cp2y + t³*end_y
        await page.mouse.move(x, y)

        # Ease-in-out speed: slower at start and end, faster in the middle
        speed_factor = max(0.5, 1 - abs(2*t - 1) * 0.5)
        await asyncio.sleep(random.gauss(0.012, 0.004) / speed_factor)
```

This produces a curved, organic path that slows at the start and end — exactly
like a human's hand movement.

**Reading pause — proportional to content:**

```python
async def reading_pause(self, num_tiles):
    base = num_tiles * random.gauss(0.6, 0.2)  # ~0.6s per job card visible
    await asyncio.sleep(max(1.0, base))         # minimum 1s
```

If 10 job tiles are visible → wait ~6s (with variance). Bots don't do this.

**Tile hovering — 40% of scroll rounds:**

```python
async def hover_random_tile(self, page):
    tiles = await page.query_selector_all('article, [data-test="job-tile"]')
    tile = random.choice(tiles[:8])              # pick from first 8 visible
    box  = await tile.bounding_box()
    # Random point inside the tile
    hover_x = box["x"] + random.uniform(box["width"] * 0.1, box["width"] * 0.9)
    hover_y = box["y"] + random.uniform(box["height"] * 0.1, box["height"] * 0.9)
    await self.bezier_mouse_move(page, start_x, start_y, hover_x, hover_y)
    await asyncio.sleep(random.gauss(1.5, 0.6))  # hover for ~1.5s
```

**Distraction browsing — 30% of sessions:**

```python
distractions = [
    "https://www.upwork.com/freelancers/settings/",
    "https://www.upwork.com/ab/messages/rooms",
    "https://www.upwork.com/nx/wm/my-stats",
]
await page.goto(random.choice(distractions))
await self.human_pause(5, 20)
```

A real freelancer doesn't only ever go to job search — they check messages,
settings, stats. This traffic pattern matters.

---

### 4.6 DOM Extractor — What Data We Pull

**File:** `src/channels/browser/extractor.py`

The extractor runs a JavaScript function directly inside the rendered page
via `page.evaluate()`. This is the most reliable approach because we get
the already-rendered DOM after React has populated it — no network interception,
no API call, no HTTP headers to set.

```python
jobs = await page.evaluate(EXTRACT_SCRIPT)
```

The JS function (`EXTRACT_SCRIPT`) runs inside the browser tab's JS context:

```javascript
() => {
    const getText = (parent, selectors) => {
        // Try each selector in order, return first match
        for (const sel of selectors) {
            const el = parent.querySelector(sel);
            if (el) return el.textContent.trim();
        }
        return null;
    };

    // Find all job tile containers
    const tiles = document.querySelectorAll(
        'article, [data-test="job-tile"], section.up-card-section'
    );

    tiles.forEach(tile => {
        // Find the job link — must contain /jobs/~ (Upwork job URL pattern)
        const link = tile.querySelector('a[href*="/jobs/~"]');
        if (!link) return;

        // Extract Upwork job ID from URL: /jobs/~01234567890abcdef → "01234567890abcdef"
        const jobId = (link.href.match(/~(\w+)/) || [])[1];
        if (!jobId) return;

        jobs.push({
            id:               jobId,
            title:            getText(tile, ['h2', 'h3', '[data-test="job-tile-title"]']),
            description:      getText(tile, ['[data-test="job-description-text"]', ...]),
            budget:           getText(tile, ['[data-test="budget"]', ...]),
            jobType:          getText(tile, ['[data-test="job-type"]', ...]),
            experienceLevel:  getText(tile, ['[data-test="experience-level"]', ...]),
            duration:         getText(tile, ['[data-test="duration"]', ...]),
            skills:           [...tile.querySelectorAll('.up-skill-badge, [data-test="token"]')]
                                  .map(el => el.textContent.trim()),
            postedTime:       getText(tile, ['[data-test="posted-on"]', 'time', ...]),
            proposals:        getText(tile, ['[data-test="proposals-tier"]', ...]),
            clientSpent:      getText(tile, ['[data-test="total-spent"]', ...]),
            clientRating:     getText(tile, ['[data-test="client-rating"]', ...]),
            clientLocation:   getText(tile, ['[data-test="client-country"]', ...]),
            paymentVerified:  !!tile.querySelector('[data-test="payment-verified"]'),
            connectsRequired: getText(tile, ['[data-test="connects"]', ...]),
            url:              link.href,
            source:           'browser_channel',
            observedAt:       new Date().toISOString(),
        });
    });
    return jobs;
}
```

---

### 4.7 Page Guard — Edge Case Handling

**File:** `src/channels/browser/page_guard.py`

Called after **every single navigation**. Never assumes the page loaded correctly.

```
After every page.goto() or page.go_back():
    state = await guard.check_and_handle(page, label)
    if state in FATAL_STATES: abort session
    if state in SKIP_STATES:  skip this search, try next
```

**Detection logic — priority order:**

```python
async def _detect(self, page) -> PageState:
    url   = page.url.lower()
    title = (await page.title()).lower()

    # 1. Hard block (403, Error 1020, "access denied")
    if any(t in title for t in ["access denied", "403 forbidden", "error 1020", ...]):
        return PageState.HARD_BLOCK
    if "cdn-cgi/challenge-platform" in url and "error" in url:
        return PageState.HARD_BLOCK

    # 2. Rate limited (429)
    if any(t in title for t in ["429", "too many requests", "rate limit"]):
        return PageState.RATE_LIMITED

    # 3. Logged out
    if any(p in url for p in ["/login", "/ab/account-security/login", "signup"]):
        return PageState.LOGGED_OUT
    if any(t in title for t in ["log in", "sign in"]) and "upwork.com" in url:
        return PageState.LOGGED_OUT

    # 4. Maintenance
    if any(t in title for t in ["maintenance", "503", "service unavailable"]):
        return PageState.MAINTENANCE

    # 5. Interactive challenge (hCaptcha, Turnstile, press-and-hold)
    if any(t in title for t in ["verify you are human", "attention required", "security check"]):
        return PageState.INTERACTIVE_CHALLENGE
    for sel in ["#challenge-form", ".cf-turnstile", "iframe[src*='hcaptcha.com']", ...]:
        if await page.query_selector(sel):
            return PageState.INTERACTIVE_CHALLENGE

    # 6. JS challenge (auto-resolving Cloudflare)
    if any(t in title for t in ["just a moment", "checking your browser", "please wait"]):
        return PageState.JS_CHALLENGE

    # 7. Managed challenge
    if "cdn-cgi/challenge-platform" in url:
        return PageState.MANAGED_CHALLENGE

    return PageState.OK
```

**What happens for each state:**

| State                     | Auto-handled?        | What it does                                                   |
| ------------------------- | -------------------- | -------------------------------------------------------------- |
| `OK`                    | —                   | Continue normally                                              |
| `JS_CHALLENGE`          | Yes (20s wait)       | Waits for Cloudflare to auto-resolve, re-checks                |
| `MANAGED_CHALLENGE`     | Yes (25s wait)       | Same — usually auto-resolves                                  |
| `INTERACTIVE_CHALLENGE` | No — needs you      | Telegram alert with page title + URL, polls every 3s for 5 min |
| `RATE_LIMITED`          | Yes (sleep 2–5 min) | Telegram alert, sleeps, returns state                          |
| `HARD_BLOCK`            | No — stops channel  | Telegram alert with remediation, sets stop_event               |
| `LOGGED_OUT`            | No — stops channel  | Telegram alert with exact re-login commands, sets stop_event   |
| `MAINTENANCE`           | Yes (skip session)   | Telegram alert, session aborted, retry next scheduled slot     |

---

### 4.8 Session Runner — The Orchestrator

**File:** `src/channels/browser/session_runner.py`

The runner wires all layers together. Key design decisions:

**Fatal vs skippable states:**

```python
_FATAL_STATES = {PageState.HARD_BLOCK, PageState.LOGGED_OUT}
# → abort session immediately, stop_event is already set

_SKIP_STATES = {
    PageState.RATE_LIMITED, PageState.MAINTENANCE,
    PageState.JS_CHALLENGE, PageState.MANAGED_CHALLENGE,
    PageState.INTERACTIVE_CHALLENGE, PageState.UNKNOWN_ERROR,
}
# → skip the current search, try the next one (or abort session if on homepage)
```

**Zero-jobs alert:**

```python
if searches_done and not unique_jobs and not aborted:
    # Something is wrong — searches ran but found nothing
    await self._alert("⚠️ Zero jobs found this session — check DOM selectors")
```

**Per-session deduplication:**

```python
seen_ids: set[str] = set()
for job in all_jobs:
    if job["id"] not in seen_ids:
        seen_ids.add(job["id"])
        unique_jobs.append(job)
# Prevents same job appearing in multiple scroll rounds from being emitted twice
```

---

### 4.9 BrowserChannel — Top Level

**File:** `src/channels/browser/channel.py`

**Consecutive failure tracking:**

```python
_CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 3

async def _wrapped_session_complete(self, session_data):
    if session_data["error"] or session_data["aborted"]:
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            await self._alert("⚠️ Browser Channel Degraded — 3 consecutive failures")
    else:
        if self._consecutive_failures > 0:
            await self._alert("✅ Browser Channel Recovered")
        self._consecutive_failures = 0
```

---

## 5. What Data Is Extracted From Upwork

Every job card in the feed produces this data structure:

```python
{
    # Identity
    "id":               "01234567890abcdef",     # Upwork job ID from URL
    "url":              "https://www.upwork.com/jobs/~01234567890abcdef",

    # Core job info
    "title":            "Senior Python Developer for FastAPI Project",
    "description":      "We are looking for an experienced developer...",  # snippet
    "budget":           "$500",                  # or "$25–$50/hr"
    "jobType":          "Fixed price",           # or "Hourly"
    "experienceLevel":  "Expert",                # Entry / Intermediate / Expert
    "duration":         "Less than 1 month",

    # Skills
    "skills":           ["Python", "FastAPI", "PostgreSQL", "Docker"],

    # Client info
    "clientSpent":      "$10K+ spent",
    "clientRating":     "4.9",
    "clientLocation":   "United States",
    "paymentVerified":  True,

    # Competition info
    "proposals":        "10 to 15",             # proposal count range

    # Cost
    "connectsRequired": "6",

    # Meta
    "postedTime":       "2 hours ago",
    "source":           "browser_channel",
    "observedAt":       "2026-04-11T14:23:00.000Z",
}
```

**From job detail page** (when the 35% detail-open probability triggers):

```python
"description": "Full multi-paragraph job description text..."
# replaces the truncated snippet from the search tile
```

---

## 6. How the DOM Selectors Work (Without Upwork Source Code)

This is an important question. We never had Upwork's source code. Here is how
the selectors were determined:

**The key insight: Upwork uses React with `data-test` attributes.**

React developers add `data-test="..."` attributes to elements as stable handles
for their own test suite. These attributes are:

- Present in production HTML
- More stable than CSS classes (which get hash-renamed in builds like `.up-a3x7f`)
- The standard convention: `data-test="semantic-name"`

So instead of guessing unstable CSS classes, we target the semantic test attributes:

```javascript
// Fragile (class names change with every build):
tile.querySelector('.jss-1a2b3c-title')     // ❌ breaks on redeploy

// Stable (test attributes rarely change):
tile.querySelector('[data-test="job-tile-title"]')  // ✅ stable

// And we always provide fallbacks:
getText(tile, [
    '[data-test="job-tile-title"]',  // primary: data-test attr
    'h2',                            // fallback 1: semantic HTML
    'h3',                            // fallback 2
    '.job-title',                    // fallback 3: likely class name
])
```

**Multi-selector fallback chain** means if Upwork updates their DOM, the
extractor degrades gracefully — it extracts what it can instead of failing
completely. The zero-jobs alert in the session runner tells you when
extraction has broken so you can update selectors.

**How to verify current selectors are working:**
See Testing section (§10) for the selector audit procedure.

---

## 7. Edge Cases and How Each Is Handled

### Cloudflare JS Challenge

**Trigger:** Any navigation — Cloudflare suspects automation.
**Detection:** Title contains "Just a moment" / "Checking your browser"
**Handling:**

```python
# Waits up to 20s for the challenge to auto-resolve
await page.wait_for_function(
    "() => !['just a moment','checking your browser','please wait']"
    "    .some(t => document.title.toLowerCase().includes(t))",
    timeout=20_000,
)
await asyncio.sleep(random.uniform(1.5, 3.0))  # settle time
state = await self._detect(page)  # re-check
```

Usually resolves in 3–5s. If not resolved → check if it escalated to interactive.

### Cloudflare Interactive Challenge (hCaptcha, Turnstile, press-and-hold)

**Trigger:** Cloudflare decides JS challenge alone isn't enough.
**Detection:** DOM selectors: `.cf-turnstile`, `iframe[src*='hcaptcha.com']`,
`iframe[src*='challenges.cloudflare.com']`, `#challenge-form`
**Handling:**

```python
# 1. Immediately send Telegram alert
await self._alert("🚨 Interactive Challenge — please solve in browser window")

# 2. Poll every 3s for up to 5 minutes
while elapsed < 300:
    await asyncio.sleep(3)
    state = await self._detect(page)
    if state == PageState.OK:
        await self._alert("✅ Challenge solved — continuing")
        return PageState.OK
```

You see the browser on your screen, solve it, the session continues automatically.

### Session Expiry (Logged Out)

**Trigger:** Upwork session cookie expired (~30 days), redirected to login.
**Detection:** URL contains `/login` or `/ab/account-security/login`
**Handling:**

```python
await self._alert(
    "🔑 Upwork Session Expired\n"
    "Run: python -m src.channels.browser.save_session"
)
self._stop_event.set()  # stop the channel
```

Channel stops itself. You get a Telegram message with the exact command to run.

### Hard Block / IP Ban (403)

**Trigger:** Upwork or Cloudflare has flagged your IP.
**Detection:** Title contains "Access Denied", "Error 1020", "Blocked"
**Handling:**

```python
await self._alert(
    "🔴 Hard Block — channel stopped\n"
    "Check your IP, wait before retrying, check Upwork account status"
)
self._stop_event.set()  # stop the channel entirely
```

### Rate Limiting (429)

**Trigger:** Too many requests in a short time.
**Handling:**

```python
backoff = random.randint(120, 300)   # 2–5 minutes random sleep
await self._alert(f"⚡ Rate Limited — sleeping {backoff}s")
await asyncio.sleep(backoff)
```

### Navigation Failure

**Trigger:** Network timeout, DNS failure, Upwork returns 5xx.
**Handling:**

```python
try:
    await self.navigation.navigate_to_search(page, config["url"])
except Exception as e:
    logger.warning(f"Navigation to '{config_name}' failed: {e} — skipping")
    continue   # skip this search URL, try the next one
```

### Zero Jobs Extracted

**Trigger:** DOM structure changed, selectors no longer match.
**Detection:** `searches_done` is non-empty but `unique_jobs` is empty.
**Handling:** Telegram alert with specific diagnosis hint + log the issue.
Does NOT stop the channel — next session might succeed.

### Consecutive Failures

**Trigger:** 3+ sessions in a row with errors or aborts.
**Handling:**

```python
if self._consecutive_failures >= 3:
    await self._alert(
        "⚠️ Browser Channel Degraded — 3 consecutive failures\n"
        "Last error: ...\n"
        "Check: session freshness, IP status, log files"
    )
```

Channel keeps running — just alerts you so you can investigate.

### Stop Event During Session

**Trigger:** You disable the channel from the UI while a session is running.
**Handling:** `stop_event` is checked between every search in the loop.
The session finishes its current action and exits cleanly.

---

## 8. Stealth Rating and Analysis

### Current Rating: **6.5 / 10**

This is honest. Here is the breakdown by detection vector:

| Vector                       | Status                                          | Score  |
| ---------------------------- | ----------------------------------------------- | ------ |
| Headless mode                | Real visible Chrome,`headless=False`          | 10/10  |
| `navigator.webdriver` flag | Removed by stealth + our patch                  | 10/10  |
| Chrome runtime object        | Injected (`window.chrome`)                    | 9/10   |
| Plugin list                  | Realistic 3-plugin list                         | 8/10   |
| WebGL fingerprint            | Patched (Intel GPU string)                      | 7/10   |
| User agent                   | Real Chrome UAs, randomized                     | 8/10   |
| Viewport                     | Randomized per session                          | 8/10   |
| Device scale factor          | Varied (1x / 2x)                                | 7/10   |
| Accept-Language header       | Correct en-US                                   | 9/10   |
| Timezone                     | Configurable, defaults NYC                      | 8/10   |
| Mouse movement               | Bezier curves, gaussian variance                | 7/10   |
| Scroll behavior              | Gaussian steps, occasional backtrack            | 7/10   |
| Session timing               | Work hours, day weights, gaussian duration      | 8/10   |
| Traffic pattern              | Homepage-first entry, distractions              | 8/10   |
| TLS fingerprint              | Not addressed (Chromium default)                | 5/10   |
| Canvas fingerprint           | Partially covered by playwright-stealth         | 5/10   |
| Font fingerprint             | Not addressed                                   | 4/10   |
| Audio fingerprint            | Not addressed                                   | 4/10   |
| Screen resolution            | Static (viewport only, not `screen.width`)    | 5/10   |
| Session cookie freshness     | Human-saved, real cookie values                 | 9/10   |
| Request ordering / timing    | Natural (goto, settle, interact)                | 7/10   |
| IP reputation                | Depends on your network — not controlled by us | varies |

### What a sophisticated detector would see

A bot detection system like Cloudflare Bot Management or Datadome runs
behavioral analysis (not just one-time fingerprinting). They look for:

1. **Perfect timing regularity** — we address this with Gaussian variance and
   day/hour weights
2. **Absence of hover events between navigation** — we address this with
   `hover_random_tile` and `random_mouse_wander`
3. **Canvas fingerprint inconsistency** — playwright-stealth handles some of
   this but the canvas hash may still be distinctive
4. **Missing or fake font metrics** — not currently addressed
5. **Audio context fingerprint** — not currently addressed
6. **Screen vs viewport mismatch** — `window.screen.width` may reveal automation
7. **TLS JA3 hash** — Chromium produces a consistent JA3 hash that bot
   detection tools catalog; not addressed

### Why the rating isn't lower

The biggest protection we have is the **real browser + real cookies** combination.
Most bot detection focuses on distinguishing headless bots or browserless HTTP
scrapers. A real Chrome window with real Upwork session cookies, behaving within
work hours, is a high bar to flag confidently. Most systems would classify this
as a low-risk user.

### Why the rating isn't higher

Advanced behavioral analysis (mouse entropy, click-path analysis, timing
micro-patterns) and server-side signals (IP reputation, account behavior
history) are outside what we can control purely at the browser layer.

---

## 9. Setup Guide — First Run

### Prerequisites

```
Python 3.12+
PostgreSQL 16+ running on localhost:5432
Redis 7+ running on localhost:6379
```

### Step 1: Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Mac/Linux

pip install -r requirements.txt
python -m playwright install chromium
```

### Step 2: Configure environment

Edit `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...        # Required for analysis + proposals
TELEGRAM_BOT_TOKEN=123456:ABC...    # Optional — get from @BotFather
TELEGRAM_CHAT_ID=123456789          # Your Telegram user ID — get from @userinfobot
BROWSER_TIMEZONE=America/New_York   # Match your intended region
```

### Step 3: Save your Upwork session (REQUIRED)

```bash
 python -m src.channels.browser.save_session
```

What happens:

1. Chrome opens at `https://www.upwork.com/ab/account-security/login`
2. You log in normally (including any 2FA)
3. The script detects when you reach your dashboard (URL changes)
4. Cookies are saved to `sessions/upwork_session.json`
5. Script closes and confirms how many session tokens were saved

You should see:

```
Session saved to: sessions/upwork_session.json
Total cookies: 47
Upwork cookies: 23
Session tokens: ['master_access_token', 'oauth2_global_js_token', 'XSRF-TOKEN']
SUCCESS! The automated browser will now use this session.
```

If you see `Session tokens: NONE` — you were not logged in when the script
detected the URL change. Run it again and make sure you complete login fully
before it saves.

### Step 4: Start the app

```bash
start.bat      # Windows
```

Or:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 5: Add search URLs

Go to `http://localhost:8000/channels` → Search Configurations section.

Add your Upwork search URLs. Example searches:

- `https://www.upwork.com/nx/jobs/search/?q=python+fastapi&sort=recency`
- `https://www.upwork.com/nx/jobs/search/?q=react+typescript&hourly_rate=50-&sort=recency`
- `https://www.upwork.com/nx/jobs/search/?category2_uid=531770282580668418&sort=recency`

To build a search URL: go to Upwork → Find Work → search → filter → copy the URL
from your browser. Paste it into the dashboard.

### Step 6: Enable the channel

Go to `http://localhost:8000/channels` → toggle "Humanoid Browser" ON.

The channel will:

1. Check if it is a work hour (9–12:30, 14–18, 20–22:30)
2. Wait until the next work window if not
3. Run its first session and send you a Telegram notification

---

## 10. Testing Guide — How to Verify Everything Works

### Test 1: Verify session cookies are valid

```bash
python -c "
import json
data = json.load(open('sessions/upwork_session.json'))
cookies = data['cookies']
upwork = [c for c in cookies if 'upwork' in c.get('domain','')]
tokens = [c['name'] for c in upwork if c['name'] in
          {'master_access_token','oauth2_global_js_token','XSRF-TOKEN'}]
print(f'Total cookies: {len(cookies)}')
print(f'Upwork cookies: {len(upwork)}')
print(f'Session tokens: {tokens}')
"
```

Expected: `Session tokens: ['master_access_token', 'oauth2_global_js_token', 'XSRF-TOKEN']`

### Test 2: Manual session trigger (test browser + extraction)

In the UI: **Channels page → Trigger Session button.**

Or via API:

```bash
curl -X POST http://localhost:8000/api/v1/channels/browser_channel/trigger
```

Watch:

1. A Chrome window opens on your screen
2. It navigates to Upwork homepage, waits, then goes to Find Work
3. It opens your first search URL and scrolls
4. The window eventually closes
5. Check logs: `tail -f app.log` (or your log output)

Expected log output:

```
Session START | planned duration: 720s | search configs: 3
Session loaded from 'sessions/upwork_session.json'
Creating browser context WITH saved session state (authenticated)
Navigating to Upwork homepage (natural entry)...
PageGuard detected: ok (after homepage)    ← no challenges
Search 1/3: 'Python FastAPI Jobs' | elapsed: 12s
  Scroll 1/5: extracted 10 jobs (session total: 10)
  Scroll 2/5: extracted 8 jobs (session total: 18)
...
Session END | unique jobs: 24 | searches completed: 3 | aborted: False | error: none
```

### Test 3: Verify jobs are being extracted correctly

```bash
# After a manual session, check what was stored
curl http://localhost:8000/api/v1/jobs/?limit=5 | python -m json.tool
```

Or go to `http://localhost:8000/jobs` — you should see jobs in the table.

For each job, verify:

- Title: looks like a real job title
- Budget: has a value (not null)
- Skills: list of technologies
- Client rating / payment verified: populated (if Upwork shows them)

### Test 4: Selector audit — are DOM selectors still working?

Run this in the browser devtools console while on a Upwork job search page to
validate the current selectors:

```javascript
// Paste this in Chrome devtools console on https://www.upwork.com/nx/jobs/search/?q=python

const tiles = document.querySelectorAll('article, [data-test="job-tile"], section.up-card-section');
console.log(`Found ${tiles.length} job tiles`);

tiles.forEach((tile, i) => {
    const link = tile.querySelector('a[href*="/jobs/~"]');
    if (!link) { console.log(`Tile ${i}: NO LINK`); return; }
    const jobId = (link.href.match(/~(\w+)/) || [])[1];
    const title = tile.querySelector('h2,h3,[data-test="job-tile-title"]')?.textContent?.trim();
    const budget = tile.querySelector('[data-test="budget"],[data-test="is-fixed-price"]')?.textContent?.trim();
    const skills = [...tile.querySelectorAll('.up-skill-badge,[data-test="token"]')].map(e=>e.textContent.trim());
    console.log(`${i}: ${jobId} | "${title}" | ${budget} | Skills: ${skills.join(', ')}`);
});
```

If all tiles show up with IDs and titles — selectors are working.
If you see `NO LINK` or blank titles — Upwork has updated their DOM and selectors need updating.

### Test 5: PageGuard — test challenge detection

To verify PageGuard works without triggering a real challenge:

```bash
python -c "
import asyncio
from playwright.async_api import async_playwright
from src.channels.browser.page_guard import PageGuard, PageState

async def test():
    guard = PageGuard()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Test 1: Normal page
        await page.goto('https://www.upwork.com')
        state = await guard._detect(page)
        print(f'Upwork homepage: {state.value}')  # expect: ok

        # Test 2: Simulate login page detection
        await page.goto('https://www.upwork.com/ab/account-security/login')
        state = await guard._detect(page)
        print(f'Login page: {state.value}')  # expect: logged_out

        await browser.close()

asyncio.run(test())
"
```

### Test 6: Verify Telegram alerts work

```bash
python -c "
import asyncio
from src.config import settings
from src.notifications.telegram import TelegramNotifier, AlertSeverity

async def test():
    n = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    await n.send_alert('Test alert from Up-take', AlertSeverity.INFO, title='Setup Test')
    print('Alert sent (check Telegram)')

asyncio.run(test())
"
```

### Test 7: Check scheduler timing

```bash
python -c "
from src.channels.browser.scheduler import SessionScheduler
from src.config import WORK_WINDOWS, DAY_WEIGHTS, HOUR_WEIGHTS

s = SessionScheduler(WORK_WINDOWS, DAY_WEIGHTS, HOUR_WEIGHTS)
print(f'Is work hour now: {s.is_work_hour()}')
print(f'Should run today: {s.should_run_today()}')
print(f'Next session gap: {s.next_session_gap()}s')
print(f'Session duration: {s.session_duration()}s')
print(f'Seconds until next window: {s.seconds_until_next_window()}')
"
```

### Reading the logs during a live session

With `LOG_LEVEL=DEBUG` in `.env`:

```
Session START | planned duration: 690s | search configs: 3
Session loaded from 'sessions/upwork_session.json'
Creating browser context WITH saved session state (authenticated)
Navigating to Upwork homepage (natural entry)...
Running 3 movements of random mouse wander
PageGuard: ok (after homepage)
Will run 2 searches this session (of 3 available configs)
Search 1/2: 'Python FastAPI' | elapsed: 15s
Running 4 scroll rounds...
  Scroll 1/4: extracted 10 jobs (session total: 10)
  Scroll 2/4: extracted 9 jobs (session total: 19)
  Scroll 3/4: extracted 11 jobs (session total: 30)
  Scroll 4/4: extracted 0 jobs (session total: 30)   ← reached end of page
Search 'Python FastAPI' complete: 30 job cards seen
Opening job detail: https://www.upwork.com/jobs/~abc...
Job detail extracted (1240 chars)
Search 2/2: 'React TypeScript' | elapsed: 180s
...
Running distraction browse...
Session END | unique jobs: 43 | searches completed: 2 | aborted: False | error: none
```

---

## 11. What to Improve to Become More Undetectable

Ranked by impact vs implementation effort:

### Priority 1 — HIGH IMPACT, Medium Effort

**1.1 Canvas fingerprint randomization**

The canvas element produces a unique fingerprint per machine because of
GPU rendering differences. Automation tools often produce a "flat" canvas
fingerprint that fingerprinting services recognize.

```javascript
// Add to factory.py _apply_extra_patches():
const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    if (type === 'image/png' && this.width === 16 && this.height === 16) {
        // Fingerprinting canvas — add sub-pixel noise
        const ctx = this.getContext('2d');
        const imageData = ctx.getImageData(0, 0, this.width, this.height);
        for (let i = 0; i < imageData.data.length; i += 4) {
            imageData.data[i]     += Math.floor(Math.random() * 3) - 1;   // R
            imageData.data[i + 1] += Math.floor(Math.random() * 3) - 1;   // G
        }
        ctx.putImageData(imageData, 0, 0);
    }
    return originalToDataURL.apply(this, arguments);
};
```

**1.2 Audio fingerprint randomization**

Audio context fingerprinting reads subtle differences in audio processing.
Headless/automated browsers return flat values.

```javascript
// Add to _apply_extra_patches():
const originalGetChannelData = AudioBuffer.prototype.getChannelData;
AudioBuffer.prototype.getChannelData = function() {
    const result = originalGetChannelData.apply(this, arguments);
    for (let i = 0; i < result.length; i += 100) {
        result[i] += Math.random() * 0.0000001;   // imperceptible noise
    }
    return result;
};
```

**1.3 Screen resolution consistency**

Currently, `window.screen.width` may show the actual monitor resolution
which could mismatch the viewport. Set it to be consistent:

```javascript
// Add to _apply_extra_patches() — match screen to viewport
Object.defineProperty(screen, 'width',       { get: () => <viewport_width> });
Object.defineProperty(screen, 'height',      { get: () => <viewport_height> });
Object.defineProperty(screen, 'availWidth',  { get: () => <viewport_width> });
Object.defineProperty(screen, 'availHeight', { get: () => <viewport_height> - 40 });
```

---

### Priority 2 — HIGH IMPACT, High Effort

**2.1 Residential proxy rotation**

Your home IP or VPS IP has a reputation score. If it has been flagged before,
all sessions from it are suspect regardless of browser behavior.

Services: Bright Data, Oxylabs, Smartproxy (residential proxies, not datacenter)

```python
# In factory.py create_session():
context = await browser.new_context(
    proxy={
        "server":   "http://proxy.brightdata.com:22225",
        "username": "user-zone-residential",
        "password": "your_password",
    },
    ...
)
```

**2.2 Typing simulation for future form interactions**

If you ever need to interact with forms (search boxes, filters), replace
`page.fill()` with character-by-character typing with human-like delay:

```python
async def human_type(page, selector, text):
    await page.click(selector)
    for char in text:
        await page.keyboard.press(char)
        # Variable delay: fast typist with occasional hesitation
        delay = random.gauss(0.08, 0.03)
        if random.random() < 0.05:   # 5%: pause as if thinking
            delay += random.uniform(0.3, 1.2)
        await asyncio.sleep(max(0.04, delay))
```

**2.3 Persistent browser profile**

Instead of creating a fresh context each session (no history, no cached
resources), use a persistent browser profile:

```python
context = await browser.new_persistent_context(
    user_data_dir="./browser_profile",
    ...
)
```

This means:

- Browser history accumulates
- Cache grows (faster page loads, matching real user behavior)
- Cookies persist naturally without storage_state injection
- IndexedDB, localStorage all persist

This makes the browser look like an established user, not a fresh install.

---

### Priority 3 — Medium Impact, Low Effort

**3.1 Referer header chain**

Real navigations build a Referer chain. When jumping to a search URL, set
the Referer:

```python
await page.set_extra_http_headers({
    "Referer": "https://www.upwork.com/nx/find-work/",
})
```

**3.2 Mouse movement on page load**

Before any scrolling, wander the mouse as if orienting to the new page:

```python
# Add to navigate_to_search():
await self.behavior.random_mouse_wander(page, movements=2)
await self.behavior.reading_pause(3)   # look at the top of the page first
```

**3.3 Scroll-up occasionally at start**

Real users often scroll up slightly to "reset" after navigation:

```python
# 20% chance at start of a search page
if random.random() < 0.2:
    await page.mouse.wheel(0, -random.randint(50, 200))
    await asyncio.sleep(random.uniform(0.5, 1.5))
```

**3.4 Random viewport jitter between sessions**

Currently viewport is random per session but within a fixed range. Expand
the range slightly:

```python
width  = random.choice([1280, 1366, 1440, 1536, 1920])
height = random.choice([720, 768, 800, 864, 900, 1080])
```

**3.5 `hardwareConcurrency` and `deviceMemory` randomization**

These are quick patches:

```javascript
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => [4, 8, 12, 16][Math.floor(Math.random() * 4)]
});
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => [4, 8, 16][Math.floor(Math.random() * 3)]
});
```

**3.6 Permissions API consistency**

Some detectors query `navigator.permissions` for `notifications` and
compare the result against expected values:

```javascript
const originalQuery = navigator.permissions.query.bind(navigator.permissions);
navigator.permissions.query = (params) => {
    if (params.name === 'notifications') {
        return Promise.resolve({ state: 'denied', onchange: null });
    }
    return originalQuery(params);
};
```

---

### Priority 4 — Architectural (Long Term)

**4.1 Multiple browser profiles**

Rotate between 3–5 different saved browser profiles (different cookies, history,
fingerprints). One active profile per day or per session group.

**4.2 Session warming**

Before going to job search, spend 1–2 minutes doing random "warm-up" activity:

- Check notifications
- Read one message in the inbox
- Visit your own profile

This builds a pre-search activity trail that looks organic.

**4.3 Entropy-based idle simulation**

During long reading pauses, don't just `sleep()` — move the mouse randomly
to simulate a person whose hand is resting on the mouse while their eyes read:

```python
async def idle_with_mouse_entropy(page, duration_s):
    end = asyncio.get_event_loop().time() + duration_s
    while asyncio.get_event_loop().time() < end:
        await behavior.random_mouse_wander(page, movements=1)
        await asyncio.sleep(random.uniform(2, 8))
```

---

## Summary Table

| What               | Where                                    | Key config                                                     |
| ------------------ | ---------------------------------------- | -------------------------------------------------------------- |
| Session timing     | `scheduler.py`                         | `WORK_WINDOWS`, `DAY_WEIGHTS`, `session_duration_mean`   |
| Stealth patches    | `factory.py`                           | `_apply_extra_patches()`, playwright-stealth                 |
| Session cookies    | `login_manager.py` + `sessions/` dir | Run `save_session.py` once                                   |
| Challenge handling | `page_guard.py`                        | `INTERACTIVE_CHALLENGE_TIMEOUT_S = 300`                      |
| Job data structure | `extractor.py`                         | `EXTRACT_SCRIPT` JS function                                 |
| Scroll / mouse     | `behavior.py`                          | Gaussian params in `human_scroll()`, `bezier_mouse_move()` |
| Navigation         | `navigation.py`                        | `natural_entry()`, `open_job_detail()`                     |
| Error handling     | `session_runner.py`                    | `_FATAL_STATES`, `_SKIP_STATES`                            |
| Failure alerts     | `channel.py`                           | `_CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 3`                   |

---

*Document reflects codebase state as of 2026-04-11.*
