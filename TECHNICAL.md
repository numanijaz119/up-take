# Up-take — Complete Technical Reference

**Version:** 1.0  
**Total source files:** 43 Python modules, 6 HTML templates, 3254 lines of code  
**Stack:** Python 3.12 · FastAPI · PostgreSQL · Redis · Playwright · Claude Sonnet 4 · HTMX · Tailwind

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [Full End-to-End Flow](#2-full-end-to-end-flow)
3. [Project Structure — Every File Explained](#3-project-structure--every-file-explained)
4. [Application Startup Sequence](#4-application-startup-sequence)
5. [Detection Channels — Architecture & Status](#5-detection-channels--architecture--status)
6. [Channel 1: Humanoid Browser — Deep Dive](#6-channel-1-humanoid-browser--deep-dive)
7. [DOM Extraction — How We Know What to Scrape](#7-dom-extraction--how-we-know-what-to-scrape)
8. [Processing Pipeline — Step by Step](#8-processing-pipeline--step-by-step)
9. [AI/LLM Integration](#9-aillm-integration)
10. [Safety System](#10-safety-system)
11. [Database Schema — Every Table](#11-database-schema--every-table)
12. [API Reference — Every Endpoint](#12-api-reference--every-endpoint)
13. [Frontend Dashboard](#13-frontend-dashboard)
14. [Configuration Reference — Every Setting](#14-configuration-reference--every-setting)
15. [How to First-Run Setup](#15-how-to-first-run-setup)
16. [What Is Implemented vs. What Remains](#16-what-is-implemented-vs-what-remains)
17. [Known Limitations & Edge Cases](#17-known-limitations--edge-cases)
18. [How to Add a New Channel](#18-how-to-add-a-new-channel)

---

## 1. What This System Does

Up-take is an **automation-assisted** job proposal system for Upwork freelancers. It does the following:

1. Discovers new job postings on Upwork automatically.
2. Filters jobs against your preferences without spending any API tokens.
3. Analyzes surviving jobs with Claude AI — scoring them 0–100 and extracting requirements.
4. Writes a personalized proposal for every job that scores above your threshold.
5. Evaluates its own proposals with a quality score (0–10) and regenerates if below threshold.
6. Notifies you via Telegram with a preview and Approve/Skip buttons.
7. Copies the approved proposal to your clipboard and opens the job URL so you can paste and submit manually.

**The system never touches the Submit button.** Every proposal requires your explicit approval. The automation handles preparation; you handle the final action.

---

## 2. Full End-to-End Flow

```
UPWORK
  └── Job posted publicly
          │
          │  (T+30s – T+3min)
          ▼
┌─────────────────────────────────────────────────────────┐
│  DETECTION LAYER                                        │
│                                                         │
│  BrowserChannel (enabled)                               │
│  └── SessionScheduler fires when:                       │
│       • current time is inside a WORK_WINDOW            │
│       • day_weight random check passes                  │
│                                                         │
│  BrowserFactory creates a stealth Chromium instance     │
│  NavigationEngine goes: upwork.com → find-work → search │
│                                                         │
│  Per scroll round:                                      │
│    DOMExtractor.extract_visible_jobs()                  │
│    → runs JS in page context (read-only)                │
│    → returns list of job dicts                          │
│                                                         │
│  Optional (35% chance): open one job detail page        │
│   → extract full description → go back                  │
│  Optional (30% chance): visit distraction page          │
└─────────────────────────────────────────────────────────┘
          │
          │  job dict emitted via BrowserChannel._emit()
          ▼
┌─────────────────────────────────────────────────────────┐
│  DEDUPLICATION GATEWAY                                  │
│                                                         │
│  Redis lookup: "job:seen:{upwork_id}"                   │
│  ├── Already seen? → enrich DB record if better data    │
│  │                    log Detection row, stop           │
│  └── New? → set Redis key (TTL 7 days)                  │
│             INSERT into jobs table                       │
│             INSERT into detections table                │
│             INSERT into audit_log                       │
│             → trigger pipeline                          │
└─────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  PIPELINE ORCHESTRATOR                                  │
│                                                         │
│  Step 1 — QuickFilter (0 API calls, <500ms)             │
│  Checks: budget floor, payment verification,            │
│          skill overlap, blacklist keywords,             │
│          proposals count, client spend                  │
│  FAIL → status = "filtered_out", audit log, stop        │
│  PASS → continue                                        │
│                                                         │
│  Step 2 — DeepAnalyzer (Claude API, ~15-30s)            │
│  Sends: job title, description (≤3000 chars),           │
│         budget, skills, client info, your profile       │
│  Returns JSON: opportunity_score, relevance_score,      │
│    client_quality, key_requirements,                    │
│    hidden_requirements, matching_experience,            │
│    suggested_angle, red_flags, client_intent,           │
│    complexity_estimate, reasoning                       │
│  score < MIN_SCORE → status = "skipped", stop           │
│  score ≥ MIN_SCORE → continue                           │
│                                                         │
│  Step 3 — ProposalGenerator (Claude API, ~30-60s)       │
│  Generates personalized proposal using:                 │
│    • Your tone_description                              │
│    • Your sample_proposals (few-shot examples)          │
│    • Analysis results (angle, selling points, etc.)     │
│  Quality check → score < MIN_QUALITY → regenerate once  │
│  INSERT into proposals table, status = "draft"          │
│  UPDATE job status = "proposed"                         │
└─────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  NOTIFICATION                                           │
│                                                         │
│  TelegramNotifier.send_proposal_alert()                 │
│  Sends: score, quality, red flags, proposal preview     │
│  Inline buttons: ✅ Approve  ❌ Skip                    │
│                                                         │
│  If Telegram not configured → info logged to console    │
└─────────────────────────────────────────────────────────┘
          │
          │  YOU REVIEW via:
          │  • Telegram buttons, OR
          │  • Dashboard → /proposals page
          ▼
┌─────────────────────────────────────────────────────────┐
│  APPROVAL FLOW                                          │
│                                                         │
│  POST /api/v1/proposals/{id}/approve                    │
│  SafetyController checks:                               │
│    active hours · daily cap · hourly cap · min interval │
│  status → "approved", approved_at set                   │
│  Response includes: final proposal text + job URL       │
│  Dashboard: copies proposal to clipboard, opens job URL │
│                                                         │
│  YOU: paste proposal into Upwork, click Submit          │
│                                                         │
│  POST /api/v1/proposals/{id}/submitted → "submitted"    │
│  Later: PUT /outcome → record client_responded / hired  │
└─────────────────────────────────────────────────────────┘
```

**Timing summary:**

| Stage | Time |
|---|---|
| Job posted → detected | 30s – 3 min (depends on session timing) |
| Dedup + quick filter | < 1s |
| Deep analysis (Claude) | 15–30s |
| Proposal generation (Claude) | 30–60s |
| Quality check + possible regen | 0–60s extra |
| Telegram notification | ~1s |
| **Total: job posted → proposal ready** | **~2–7 minutes** |

---

## 3. Project Structure — Every File Explained

```
Up-take/
├── .env                         ← Runtime secrets and overrides (fill in API keys)
├── .env.example                 ← Template for .env
├── docker-compose.yml           ← Postgres 16 + Redis 7 + app container
├── Dockerfile                   ← Python 3.12-slim, Playwright Chromium, uvicorn
├── requirements.txt             ← All pinned Python dependencies
├── start.bat / start.sh         ← One-click local start (creates venv, installs, runs)
│
└── src/
    ├── main.py                  ← FastAPI app, lifespan startup/shutdown wiring
    ├── app_state.py             ← Global singletons (registry, gateway, safety, session_callback)
    ├── config.py                ← All settings via pydantic-settings, env vars, defaults
    ├── database.py              ← SQLAlchemy async engine, session factory, init_db()
    ├── redis_client.py          ← Singleton async Redis client
    │
    ├── models/
    │   ├── __init__.py          ← Re-exports all ORM classes for init_db()
    │   ├── job.py               ← Job, Detection, BrowserSession tables
    │   ├── analysis.py          ← JobAnalysis table (Claude output per job)
    │   ├── proposal.py          ← Proposal table (generated text + lifecycle)
    │   ├── profile.py           ← FreelancerProfile (your identity, skills, voice)
    │   ├── search_config.py     ← SearchConfig (named Upwork search URLs)
    │   ├── audit.py             ← AuditLog (every action with timestamp)
    │   └── channel.py           ← ChannelConfig (per-channel enable state + status)
    │
    ├── channels/
    │   ├── base.py              ← DetectionChannel ABC — all channels implement this
    │   ├── registry.py          ← ChannelRegistry — start/stop channels by ID
    │   └── browser/
    │       ├── scheduler.py     ← SessionScheduler — when to run
    │       ├── factory.py       ← BrowserFactory — stealth Chromium creation
    │       ├── behavior.py      ← HumanBehaviorEngine — scroll, mouse, pauses
    │       ├── navigation.py    ← NavigationEngine — how to move between pages
    │       ├── extractor.py     ← DOMExtractor — read-only JS job extraction
    │       ├── session_runner.py← BrowserSessionRunner — one complete session
    │       └── channel.py       ← BrowserChannel — top-level channel class
    │
    ├── pipeline/
    │   ├── dedup.py             ← DeduplicationGateway — Redis + DB dedup
    │   ├── filter.py            ← QuickFilter + FilterPreferences — rule-based
    │   ├── analyzer.py          ← DeepAnalyzer — Claude job analysis
    │   ├── generator.py         ← ProposalGenerator — Claude proposal writing
    │   └── orchestrator.py      ← PipelineOrchestrator — sequences all steps
    │
    ├── safety/
    │   └── controller.py        ← SafetyController — rate limits, active hours
    │
    ├── notifications/
    │   └── telegram.py          ← TelegramNotifier — Telegram bot alerts
    │
    ├── api/
    │   ├── profile.py           ← GET/POST/PUT /api/v1/profile/
    │   ├── jobs.py              ← GET /api/v1/jobs/, GET /{id}, POST /observed
    │   ├── proposals.py         ← GET/approve/skip/submitted/outcome
    │   ├── channels.py          ← GET /channels/, PUT /toggle, POST /trigger
    │   ├── search_configs.py    ← CRUD for search URLs
    │   ├── analytics.py         ← Pipeline funnel, channel stats, session list
    │   └── settings_api.py      ← GET/PUT /api/v1/settings/safety
    │
    └── templates/
        ├── base.html            ← Sidebar nav, Tailwind CDN, JS utils
        ├── dashboard.html       ← Stats cards, funnel, pending proposals, recent jobs
        ├── jobs.html            ← Jobs table with status/score filter, job detail modal
        ├── proposals.html       ← Proposal cards, edit modal, approve/skip/submit flow
        ├── channels.html        ← Channel enable/disable toggles, search config CRUD
        └── settings_page.html   ← Profile form, safety limits, filter preferences
```

---

## 4. Application Startup Sequence

When `uvicorn src.main:app` starts, the `lifespan` async context manager in `main.py` executes in order:

1. **`init_db()`** — connects to PostgreSQL, runs `Base.metadata.create_all()`. All tables are created if they don't exist. No migration tool used — SQLAlchemy creates the schema directly.

2. **`get_redis()`** — creates a connection pool to Redis. Used for deduplication key-value store.

3. **`TelegramNotifier` constructed** — reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. If either is blank or default placeholder, the notifier is disabled and alerts are logged to console only. No error is raised.

4. **`PipelineOrchestrator` constructed** — holds references to `DeepAnalyzer` and `ProposalGenerator`. The notifier's `send_proposal_alert` is passed as the `on_proposal_ready` callback.

5. **`DeduplicationGateway` constructed** — wires together Redis, the DB session factory, and `orchestrator.process` as the callback for new jobs.

6. **`SafetyController` constructed** — holds the DB session factory, checks the DB on every proposal approval.

7. **All singletons stored in `app_state.py`** — a plain module with global variables. This is intentional to avoid circular imports between `main.py` and `api/*.py` routers.

8. **`ChannelRegistry` constructed** — `BrowserChannel` is registered. During registration, a temporary instance is created with a no-op callback purely to read the `channel_id`, `display_name`, and `description` properties. This metadata is cached.

9. **`_on_session_complete` callback defined and stored in `app_state`** — when the browser channel finishes a session, this async function persists a `BrowserSession` row to the DB.

10. **Auto-enable channels from DB** — queries `channel_configs` where `is_enabled = True`. For each, loads active `search_configs` and calls `registry.enable()`. This means if the server restarts while a channel was running, it auto-resumes.

11. **FastAPI begins serving requests.**

On shutdown, `registry.stop_all()` signals every running channel's `asyncio.Event`, cancels the background tasks, then Redis is closed.

---

## 5. Detection Channels — Architecture & Status

### Channel Architecture

All channels implement the abstract base class in `channels/base.py`:

```python
class DetectionChannel(ABC):
    channel_id: str      # machine identifier, e.g. "browser_channel"
    display_name: str    # shown in UI, e.g. "Humanoid Browser"
    description: str     # shown in UI

    async def start(self) -> None: ...   # begins the detection loop
    async def stop(self) -> None: ...    # graceful shutdown
    is_running: bool                     # runtime state

    async def _emit(self, job: dict)     # sends to gateway (inherited)
```

The `ChannelRegistry` manages a dict of `{channel_id: asyncio.Task}`. When you toggle a channel in the UI, it calls `registry.enable()` or `registry.disable()`. The enabled/disabled state is persisted to the `channel_configs` table so it survives restarts.

### Channels Status

| Channel | Channel ID | Status | Description |
|---|---|---|---|
| Humanoid Browser | `browser_channel` | **✅ Implemented** | Stealth Playwright browser with human-like behavior |
| Email Monitor | `email_channel` | ❌ Not implemented | Gmail API + Pub/Sub for Upwork alert emails |
| Official API Polling | `api_channel` | ❌ Not implemented | Upwork GraphQL API (requires approved API key) |
| Webhook (Vollna etc.) | `webhook_channel` | ❌ Not implemented | Third-party job alert webhooks |

Adding any new channel requires only:
1. Create `src/channels/your_channel/channel.py` implementing `DetectionChannel`
2. `registry.register(YourChannel)` in `main.py` lifespan
3. The toggle UI appears automatically — no template changes needed

---

## 6. Channel 1: Humanoid Browser — Deep Dive

The browser channel has five internal layers that work in sequence. Understanding all five is important for tuning behavior and debugging.

### Layer 1 — SessionScheduler (`scheduler.py`)

Controls **when** sessions fire. This is the outermost loop.

```
run_forever(session_runner_fn, stop_event)
  └── loop:
        should_run_today()? → random.random() < DAY_WEIGHTS[weekday]
        is_work_hour()? → current time inside any WORK_WINDOW
        session_duration() → gauss(720s, 240s) clamped to [300s, 1500s]
        → call session_runner_fn(duration_seconds)
        → sleep next_session_gap()
```

**Day weights** (probability session fires on that day):
- Monday: 100% · Tuesday: 95% · Wednesday: 90% · Thursday: 85%
- Friday: 70% · Saturday: 40% · Sunday: 25%

**Hour weights** determine session gap length — not probability. Higher-weight hours = shorter gaps between sessions.

**Work windows** (default):
- 09:00 – 12:30
- 14:00 – 18:00
- 20:00 – 22:30

**Session gap by time of day:**
- 09:00–12:00 → 20–40 minutes between sessions
- 13:00–15:00 → 35–65 minutes (post-lunch, fewer sessions)
- 16:00–18:00 → 25–50 minutes
- Evening/outside windows → 45–90 minutes

The `_interruptible_sleep()` method uses `asyncio.wait_for(stop_event.wait(), timeout=N)`. This means the stop signal is never blocked waiting for a gap to expire — the channel responds to stop requests within milliseconds.

### Layer 2 — BrowserFactory (`factory.py`)

Creates a new stealth Chromium instance for **every session**. Never reuses sessions between runs.

**Browser launch args:**
```
--disable-blink-features=AutomationControlled   ← most critical: removes "Chrome is controlled by automation" banner
--no-sandbox                                     ← required for Docker/Linux
--disable-dev-shm-usage                          ← prevents memory issues on Linux
--window-size={random 1280-1440}x{random 780-900}
--disable-extensions
--disable-plugins-discovery
```

**Context settings (randomized per session):**
- Viewport: 1280–1440 wide, 780–900 tall (random each session)
- User agent: randomly selected from 5 realistic Chrome 128–130 UA strings (Windows + Mac mix)
- Locale: `en-US`
- Timezone: from `BROWSER_TIMEZONE` env var (default: `America/New_York`)
- Color scheme: `light`
- Device scale factor: 1x (75% of time) or 2x (25% of time) — mimics Retina screens
- Accept-Language header: `en-US,en;q=0.9`

**playwright-stealth patches** (applied via `stealth_async(page)`):
The `playwright-stealth` library patches 20+ browser signals that headless/automated browsers typically leak. If the library is not installed, a warning is logged and the session runs without it (still works, less protected).

**Additional manual JS patches** (applied via `add_init_script`):
These run before any page JS executes:

| What's patched | Why |
|---|---|
| `window.chrome` object | Real Chrome has this; headless Chromium doesn't by default |
| `navigator.plugins` | Real browsers have 3 plugins; headless has 0 (obvious bot signal) |
| `WebGLRenderingContext.getParameter(37445/37446)` | Returns "Intel Inc." / "Intel Iris 640" instead of "Google SwiftShader" which is the headless GPU indicator |
| `navigator.getBattery()` | Returns a realistic battery level (60–100%, 40% chance charging) |
| `navigator.webdriver` | Set to `undefined` instead of `true` |
| `navigator.languages` | Set to `['en-US', 'en']` |

**`BROWSER_HEADLESS=false` is critical.** Headless browsers leak dozens of signals. On a server without a display, run with `xvfb-run` (installed in the Dockerfile).

### Layer 3 — HumanBehaviorEngine (`behavior.py`)

Four behavior primitives that create realistic interaction patterns.

**`human_scroll(page)`**
- Direction: 95% downward, 5% upward (backtracking)
- Distance: `gauss(380px, 120px)` minimum 150px
- Steps: 8–18 micro-scroll events
- Step variance: each step = `(total/steps) * gauss(1.0, 0.3)` — uneven speed
- Delay between steps: `max(0.02s, gauss(0.08s, 0.03s))`
- 15% chance of a mid-scroll pause: `uniform(0.5s, 2.0s)`

**`bezier_mouse_move(page, sx, sy, ex, ey, steps=20)`**
- Moves mouse along a cubic Bezier curve (4 control points)
- Control points have `gauss(0, 30px)` random offset from the straight-line path → natural curves
- Ease-in-out timing: slower at start and end, faster in middle
- Per-step delay: `max(0.004s, gauss(0.012s, 0.004s) / speed_factor)`

**`reading_pause(num_tiles)`**
- Pauses `max(1.0s, num_tiles * gauss(0.6, 0.2))` seconds
- More jobs on screen → longer reading time before scrolling again

**`browse_distraction(page)`** (30% chance per session)
- Navigates to one of three non-job pages:
  - `upwork.com/freelancers/settings/`
  - `upwork.com/ab/messages/rooms`
  - `upwork.com/nx/wm/my-stats`
- Stays 5–20 seconds, then returns
- Simulates a real user who doesn't only look at jobs

**`random_mouse_wander(page, movements=3)`**
- Moves mouse in random Gaussian paths without any purpose
- Simulates idle hand movement
- Used during the initial page load pause

### Layer 4 — NavigationEngine (`navigation.py`)

Controls **how** the browser moves between pages.

**`natural_entry(page)`**
Opens `https://www.upwork.com` first (homepage). Pauses 3–8 seconds with random mouse wander. Then navigates to `https://www.upwork.com/nx/find-work/`. Pauses 2–5 more seconds.

**Why not jump directly to the search URL?** A real user opens the site, sees the homepage, then navigates. Jumping directly to a deep search URL from every cold-start is a bot signal.

**`navigate_to_search(page, search_url)`**
Navigates to the configured Upwork search URL. Waits for `domcontentloaded` (not `networkidle` — networkidle can be slow on Upwork's SPA). Pauses 2–6 seconds after load.

**`open_job_detail(page, job_url)`** (35% chance per search)
Navigates to the full job page. Scrolls twice with pauses. Tries to extract the full description from several selectors. Returns the description text, then calls `page.go_back()`. If anything fails, handles the exception gracefully and still attempts to go back.

### Layer 5 — BrowserSessionRunner (`session_runner.py`)

The top-level orchestrator for one complete session. Called with a `duration_seconds` argument from the scheduler.

```
run_session(duration_seconds):
  1. async with async_playwright() → launch browser via BrowserFactory
  2. NavigationEngine.natural_entry()
  3. Randomly pick 2–4 search configs from the DB
  4. For each search config:
       check if session time budget exhausted
       navigate_to_search(url)
       for 3–6 scroll rounds:
           extract_visible_jobs() → job list
           human_scroll()
           reading_pause(len(jobs))
           40% chance: hover_random_tile()
       35% chance: open_job_detail() on one recent job
  5. 30% chance: browse_distraction()
  6. browser.close()
  7. Deduplicate within-session by job ID (prevents same job from being emitted twice)
  8. Emit each unique job via self._on_job(job_dict)
  9. Call on_session_complete(session_data) → persists BrowserSession to DB
```

Session failures are caught at the top level — if the browser crashes or Upwork shows a CAPTCHA or maintenance page, the error is logged and stored in the `BrowserSession.error` column. The scheduler then sleeps normally and tries again at the next gap.

---

## 7. DOM Extraction — How We Know What to Scrape

**You did not provide Upwork's source code. The selectors were derived from two sources:**

### Source 1: Upwork's `data-test` attribute convention

Upwork is a React SPA that uses a consistent pattern for testable DOM attributes: `data-test="semantic-name"`. This is a standard testing practice where the QA/dev team annotates elements for automated testing. These attributes are:
- Present in the production HTML (not removed during build)
- More stable than CSS class names (which Upwork obfuscates/hashes)
- Public knowledge — any developer can open DevTools on upwork.com and see them

The selectors in `extractor.py` use `data-test` as the primary selector and CSS class names as fallbacks:

```javascript
// Example: job tile container
'article, [data-test="job-tile"], section.up-card-section'

// Job title — tries in order until one matches
['h2', 'h3', '[data-test="job-tile-title"]', '.job-title']

// Budget
['[data-test="budget"]', '.budget', '[data-test="is-fixed-price"]', 
 '[data-test="job-type"]', '.js-budget']

// Skills/tags
'.up-skill-badge, [data-test="token"], .air3-token, [data-test="skill"]'
```

### Source 2: General Upwork DOM knowledge from public documentation + community

Upwork's DOM structure has been publicly documented by developers, researchers, and the browser automation community. The key structural facts used:

| Knowledge | How it's used |
|---|---|
| Job URLs always contain `/jobs/~{alphanumeric_id}` | Job ID extracted via regex `~(\w+)` from the `<a href>` |
| Upwork uses `air3-*` CSS prefix for their design system components | `air3-token` for skill badges |
| The `up-skill-badge` class is used for skill tag elements | Skill extraction |
| `up-lineClamp` is their truncated-text component class | Description fallback |
| Job tiles are `<article>` elements or have `data-test="job-tile"` | Root tile selector |
| Payment verified shows a specific element when payment is verified | Boolean detection via `!!element` |

### Selector robustness — multi-selector fallback pattern

The `getText()` helper in the extraction script accepts an array of selectors and tries each in order:

```javascript
const getText = (parent, selectors) => {
    for (const sel of selectors) {
        const el = parent.querySelector(sel);
        if (el) return el.textContent.trim();
    }
    return null;
};
```

This means if Upwork updates their DOM and removes `[data-test="budget"]`, the next fallback `.budget` is tried automatically. The extraction degrades gracefully rather than breaking entirely.

### What can break

Upwork updates their frontend regularly. If they:
- Rename `data-test` attributes → update the selector arrays in `extractor.py`
- Change the job URL format (`/jobs/~ID`) → update the regex in the extraction script
- Switch to a different rendering strategy (e.g., server-side streaming) → DOM timing may need adjustment

The extraction is the most maintenance-sensitive part of the system.

### What is extracted per job tile

| Field | Source selector | Notes |
|---|---|---|
| `id` | `a[href*="/jobs/~"]` regex | The Upwork job ID, used as dedup key |
| `title` | `h2, h3, [data-test="job-tile-title"]` | |
| `description` | `[data-test="job-description-text"], .up-lineClamp` | Truncated on feed page, full on detail page |
| `budget` | `[data-test="budget"], [data-test="is-fixed-price"]` | Raw text, parsed later in filter |
| `jobType` | `[data-test="job-type"]` | "Fixed Price" or "Hourly" |
| `experienceLevel` | `[data-test="experience-level"]` | Entry / Intermediate / Expert |
| `duration` | `[data-test="duration"]` | "Less than 1 month", etc. |
| `skills` | `.up-skill-badge, .air3-token` | Array of strings |
| `postedTime` | `[data-test="posted-on"], time` | Relative string like "2 hours ago" |
| `proposals` | `[data-test="proposals-tier"]` | "5 to 10", "Less than 5", etc. |
| `clientSpent` | `[data-test="total-spent"]` | "$5K+ spent" |
| `clientRating` | `[data-test="client-rating"]` | |
| `clientLocation` | `[data-test="client-country"]` | |
| `paymentVerified` | `[data-test="payment-verified"]` | Boolean |
| `connectsRequired` | `[data-test="connects"]` | |
| `url` | `a[href*="/jobs/~"].href` | Full absolute URL |

---

## 8. Processing Pipeline — Step by Step

### Step 1 — DeduplicationGateway (`pipeline/dedup.py`)

Every job dict emitted by any channel arrives here first.

**Redis key:** `job:seen:{upwork_id}` with 7-day TTL  
**New job path:** Redis key doesn't exist → set key → INSERT to `jobs` table → INSERT to `detections` → INSERT to `audit_log` → call `pipeline.process()`  
**Seen job path:** Redis key exists → log Detection row → call `_maybe_enrich()` → stop

`_maybe_enrich()` upgrades the stored job data if the new source has higher priority (API > browser > email). If the existing DB record has no description but the new detection does, the description is added. This handles the case where the browser detects a job from the feed (no full description) and later a higher-quality source detects the same job with the full description.

### Step 2 — QuickFilter (`pipeline/filter.py`)

Rule-based, synchronous, zero API calls. Reads `FilterPreferences` built from the active `FreelancerProfile.preferences` JSON column.

**Checks in order:**

1. **Budget floor** — parses budget field (handles dict `{"amount": 500}`, raw string `"$500"`, K-suffix `"$5K"`)
2. **Payment verification** — checks `client_info.paymentVerified` or `client_info.verificationStatus`. Rejects `False`, `"UNVERIFIED"`, `0`, `"false"`.
3. **Skill overlap** — converts job skills and your skills to lowercase sets, checks intersection ≥ `min_skill_overlap`. Only applied if both sets are non-empty.
4. **Blacklist keywords** — searches full-text of `title + description` for any blacklisted phrase.
5. **Proposal count ceiling** — parses the proposals tier string (e.g., "5 to 10" → 10), rejects if > `max_existing_proposals`.
6. **Client spend minimum** — parses client spent from `clientSpent` or `totalSpent`, handles K-suffix.

Returns `(True, "Passed all filters")` or `(False, "reason string")`. The reason is stored in `audit_log`.

### Step 3 — DeepAnalyzer (`pipeline/analyzer.py`)

Calls Claude with the analysis prompt. The prompt includes:
- Your full profile (name, skills, experience summary, rate range)
- The job's title, description (truncated to 3000 chars), budget, required skills, experience level, job type, duration
- Client info (payment verified, total spent)
- Proposal count so far

**Temperature: 0.2** — low randomness because analysis needs to be consistent and accurate.

The response is pure JSON (no markdown fences allowed in the prompt instruction). If Claude wraps it in ` ```json ``` ` anyway, regex strips the fences before `json.loads()`.

**Output fields used downstream:**

| Field | Used by |
|---|---|
| `opportunity_score` | Threshold check → `should_propose` decision, displayed in UI |
| `key_requirements` | Passed to proposal generator prompt |
| `hidden_requirements` | Passed to proposal generator prompt |
| `matching_experience` | Passed to proposal generator prompt |
| `suggested_angle` | Passed to proposal generator prompt |
| `key_selling_points` | Passed to proposal generator prompt |
| `red_flags` | Displayed in Telegram notification and UI |
| `client_intent` | Displayed in Telegram notification and UI |
| `reasoning` | Stored in DB, shown in job detail modal |

### Step 4 — ProposalGenerator (`pipeline/generator.py`)

**Generation temperature: 0.7** — higher randomness for natural-sounding, varied text.

The generation prompt contains:
- Your name and tone description
- Up to 3 of your sample winning proposals (few-shot examples — this is what calibrates the AI to write like you)
- The job title
- Key + hidden requirements from the analysis
- Client intent + complexity estimate
- Your matching experience (from analysis)
- The suggested angle and key selling points
- Your max word count

**Forbidden phrases enforced in the prompt:**
"I'd love to", "I'm the perfect fit", "I believe I can", "Dear Hiring Manager", "With X years of experience", "I am very interested"

**Quality check (temperature 0.1):**
A second Claude call rates the proposal on three dimensions (1–10 each):
- Specificity: Does it reference specific job details?
- Persuasiveness: Would a client want to respond?
- Authenticity: Does it sound human, not AI?

The average becomes `quality_score`. If below `MIN_PROPOSAL_QUALITY` (default 7.0), one regeneration is attempted with the feedback included. The final quality score is stored in `proposals.quality_detail` as a JSON dict.

---

## 9. AI/LLM Integration

**Model:** `claude-sonnet-4-20250514` (configurable via `LLM_MODEL` env var)

| Call | Temperature | Max tokens | Cost estimate |
|---|---|---|---|
| Deep Analysis | 0.2 | 900 | ~$0.009 |
| Proposal Generation | 0.7 | 1200 | ~$0.012 |
| Quality Check | 0.1 | 200 | ~$0.003 |
| Regeneration (50% of proposals) | 0.7 | 1200 | ~$0.009 |

**Per proposal total: ~$0.025–0.033**  
**At 10 proposals/day: ~$9/month**

The `anthropic.AsyncAnthropic` client is instantiated once per `DeepAnalyzer` and `ProposalGenerator` instance (created at startup). All calls are async and non-blocking.

**What happens when Claude returns invalid JSON:** `json.loads()` raises `JSONDecodeError`. The orchestrator catches this, logs the error, reverts the job status to `"new"` (so it could theoretically be retried), and returns. The job is not lost but no analysis/proposal is created.

**What happens when the API is unavailable:** Same error handling — the exception propagates up to the orchestrator's try/except, the job status is set back, and the pipeline stops for that job cleanly.

---

## 10. Safety System

The `SafetyController` in `safety/controller.py` is checked every time you try to approve a proposal.

**Checks (in order):**

1. **Active hours** — `active_hours_start ≤ current_hour < active_hours_end`. Default: 8–23. If you try to approve at 2 AM, it blocks.

2. **Daily cap** — counts `proposals` with status `approved` or `submitted` where `approved_at >= today 00:00`. If ≥ `max_proposals_per_day` (default 12), blocked.

3. **Hourly cap** — counts same in the last 60 minutes. If ≥ `max_proposals_per_hour` (default 3), blocked.

4. **Minimum interval** — finds the most recent `approved_at` timestamp. If less than `min_seconds_between_proposals` (default 300 = 5 minutes) has elapsed, blocked with a "wait Xs" message.

**Uniqueness check** (`check_proposal_uniqueness`): Loads the last 10 approved/submitted proposals. For each, computes Jaccard similarity (word set intersection / union). If any existing proposal shares >30% overlap with the new one, returns False. **Note: this check is implemented but not wired into the approval endpoint yet** — it would need to be called from `api/proposals.py:approve_proposal()`.

**`natural_delay()`** — returns `max(2.0, gauss(5.0, 2.0))` seconds. Not currently used automatically but available for future submission automation.

---

## 11. Database Schema — Every Table

All tables are created automatically by SQLAlchemy on startup. PostgreSQL only — no SQLite fallback because JSONB columns are used.

### `freelancer_profiles`
Your identity. The pipeline reads the single `is_active=True` profile on every job.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| name | TEXT | Your name, used in proposal prompt |
| skills | JSONB | `["python", "fastapi", "react"]` — used for filter overlap check |
| experience_summary | TEXT | Passed to analysis prompt (100–300 words recommended) |
| tone_description | TEXT | Describes your writing style, e.g. "Direct, technical, uses concrete numbers" |
| sample_proposals | JSONB | List of strings — 3–5 past winning proposals. **This is the most important field for proposal quality.** |
| rate_min / rate_max | NUMERIC | Used in analysis prompt |
| max_proposal_words | INTEGER | Default 200 — enforced in generation prompt |
| preferences | JSONB | Filter prefs: `{min_budget, require_payment_verified, min_client_spent, max_existing_proposals, blacklist_keywords, min_skill_overlap}` |
| is_active | BOOLEAN | Only one active profile at a time |

### `jobs`
Every job ever detected.

| Column | Type | Notes |
|---|---|---|
| upwork_id | TEXT UNIQUE | The Upwork job ID extracted from the URL (`~XXXXX`) |
| title | TEXT | |
| description | TEXT | May be partial (feed) or full (detail page) |
| budget | JSONB | `{"raw": "$500"}` or `{"amount": 500}` |
| job_type | TEXT | "fixed" / "hourly" |
| skills | JSONB | Array of skill strings |
| client_info | JSONB | `{paymentVerified, clientSpent, clientRating, clientLocation}` |
| detected_via | TEXT | Which channel found it first |
| status | TEXT | `new → analyzing → proposed → submitted` or `filtered_out / skipped` |

### `job_analyses`
One row per analysis. Multiple analyses per job are possible (if re-analyzed), but only the latest is shown in the UI.

| Column | Notes |
|---|---|
| opportunity_score | 0–100 integer. The primary scoring metric. |
| relevance_score | How relevant to your skills (separate from opportunity quality) |
| client_quality | Assessment of client reliability/history |
| key_requirements | JSON array — what the client explicitly wants |
| hidden_requirements | JSON array — what they implicitly need but didn't state |
| matching_experience | JSON array — which of your experiences Claude matched |
| suggested_angle | Single string — the best strategic angle for this proposal |
| red_flags | JSON array — concerns to be aware of |
| client_intent | `ready_to_hire` / `exploring` / `unclear` / `tire_kicker` |
| complexity_estimate | `low` / `medium` / `high` |
| should_propose | Boolean — `opportunity_score >= MIN_OPPORTUNITY_SCORE` |

### `proposals`
One row per generated proposal.

| Column | Notes |
|---|---|
| proposal_text | The full generated proposal text |
| quality_score | Numeric 0–10, from the self-evaluation step |
| quality_detail | JSONB: `{score, specificity, persuasiveness, authenticity, feedback}` |
| word_count | Counted from the generated text |
| status | `draft → approved → submitted` or `skipped` |
| approved_at | Set when you approve |
| submitted_at | Set when you mark as submitted |
| client_responded | Boolean — you update this manually |
| hired | Boolean — you update this manually |

### `detections`
One row per detection event from any channel. Used for channel analytics.

| Column | Notes |
|---|---|
| upwork_job_id | The Upwork ID (not the DB UUID) |
| source | Channel ID that detected it |
| is_new | True if this was the first detection of this job |

### `browser_sessions`
One row per browser session run.

| Column | Notes |
|---|---|
| started_at / ended_at | Session wall clock times |
| duration_s | Planned duration (actual may differ) |
| jobs_found | Number of unique jobs extracted |
| searches | JSON array of search config names used |
| error | Error message if session crashed, null on success |

### `channel_configs`
Persists channel enable/disable state.

| Column | Notes |
|---|---|
| channel_id | e.g. `"browser_channel"` |
| is_enabled | Whether to auto-enable on restart |
| status | `running` / `stopped` / `error` |
| last_run_at | Timestamp of last activity |
| error_message | Last error if status = error |

### `search_configs`
The Upwork search URLs the browser channel monitors.

| Column | Notes |
|---|---|
| name | Human label, e.g. "Python Backend" |
| url | Full Upwork search URL with all parameters |
| search_term | Extracted search term (for display only) |
| category | Category label (for display only) |
| is_active | Only active configs are used by the browser channel |

### `audit_log`
Append-only log of every significant action.

Actions logged: `job_detected`, `job_filtered_out`, `job_analyzed`, `proposal_generated`, `proposal_approved`, `proposal_skipped`, `proposal_submitted`, `proposal_outcome`

---

## 12. API Reference — Every Endpoint

Base URL: `http://localhost:8000`  
Interactive docs: `http://localhost:8000/docs` (Swagger UI, auto-generated)

### Health
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | Returns `{"status":"ok","timestamp":"..."}` |

### Profile
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/profile/` | Get active profile (404 if none) |
| POST | `/api/v1/profile/` | Create profile |
| PUT | `/api/v1/profile/` | Update active profile (partial update supported) |
| PUT | `/api/v1/profile/preferences` | Update filter preferences only |

### Jobs
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/jobs/` | List jobs. Params: `status`, `min_score`, `page`, `per_page` |
| GET | `/api/v1/jobs/stats` | Count by status |
| GET | `/api/v1/jobs/{id}` | Single job with analysis. `{id}` = upwork_id or UUID |
| POST | `/api/v1/jobs/observed` | Internal: receive jobs from detection channel |

### Proposals
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/proposals/` | List proposals. Params: `status`, `page`, `per_page` |
| GET | `/api/v1/proposals/{id}` | Single proposal with job title/URL |
| POST | `/api/v1/proposals/{id}/approve` | Approve. Body: `{"edited_text": "..."}` (optional) |
| POST | `/api/v1/proposals/{id}/skip` | Skip proposal |
| POST | `/api/v1/proposals/{id}/submitted` | Mark as manually submitted |
| PUT | `/api/v1/proposals/{id}/outcome` | Record `{client_responded, hired}` |

### Channels
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/channels/` | List all registered channels with status |
| PUT | `/api/v1/channels/{id}/toggle` | Enable/disable. Body: `{"enabled": true}` |
| POST | `/api/v1/channels/{id}/trigger` | Manually trigger one session immediately |

### Search Configs
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/search-configs/` | List all |
| POST | `/api/v1/search-configs/` | Create. Body: `{name, url, search_term?, category?}` |
| PUT | `/api/v1/search-configs/{id}` | Update (partial) |
| DELETE | `/api/v1/search-configs/{id}` | Delete |

### Analytics
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/analytics/pipeline` | Conversion funnel. Param: `days=30` |
| GET | `/api/v1/analytics/channels` | Per-channel detection counts |
| GET | `/api/v1/analytics/proposals` | Proposal metrics + session stats |
| GET | `/api/v1/analytics/sessions` | Browser session history |

### Settings
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/settings/safety` | Current safety limits |
| PUT | `/api/v1/settings/safety` | Update safety limits (runtime only, resets on restart) |

---

## 13. Frontend Dashboard

Five-page HTMX + Tailwind CSS web app served from `http://localhost:8000`.

All data is loaded via `fetch()` calls to the API — the HTML templates are static shells; the JavaScript fetches and renders data dynamically. HTMX is loaded but most interaction is plain JavaScript fetch calls (simpler to control).

| Page | URL | What it does |
|---|---|---|
| Dashboard | `/` | Stats cards, pipeline funnel, pending proposals queue, recent jobs |
| Jobs | `/jobs` | Full jobs table with status/score filter, click row to open job detail modal |
| Proposals | `/proposals` | Proposal cards with approve/skip/mark-submitted, edit modal with full text |
| Channels | `/channels` | Channel on/off toggles, "Run Now" button, search config CRUD |
| Settings | `/settings` | Profile form, safety limits form, filter preferences form |

**Key UI behaviors:**
- Approve button on dashboard/proposals: calls `/approve`, receives proposal text, copies to clipboard, opens job URL in new tab
- Edit modal on proposals: shows textarea pre-filled with proposal text, allows editing before approving
- Channel toggles: call PUT `/toggle`, show live status, re-fetch after 1.2s
- Stats auto-refresh: dashboard calls `/jobs/stats` every 30s in the background
- Pagination: proposals and jobs pages support server-side pagination (page parameter)

---

## 14. Configuration Reference — Every Setting

All settings are in `src/config.py` as a `pydantic-settings` class. They can be overridden via `.env` file or environment variables (uppercase).

### Required
| Env var | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key. Pipeline fails silently if missing. |
| `DATABASE_URL` | PostgreSQL async URL. Default points to Docker compose Postgres. |
| `REDIS_URL` | Redis URL. Default points to Docker compose Redis. |

### Optional
| Env var | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `""` | If empty, Telegram notifications are disabled (console log only) |
| `TELEGRAM_CHAT_ID` | `""` | Your personal Telegram chat ID |
| `BROWSER_TIMEZONE` | `America/New_York` | Timezone for the browser context. Use your real timezone. |
| `BROWSER_HEADLESS` | `false` | Never set to true in production — use xvfb instead |
| `LOG_LEVEL` | `INFO` | `DEBUG` for verbose output during debugging |
| `DEBUG` | `false` | Enables SQLAlchemy query logging if true |

### Session Scheduler
| Setting | Default | Description |
|---|---|---|
| `SESSION_DURATION_MEAN` | `720` (12 min) | Mean session length in seconds |
| `SESSION_DURATION_STDDEV` | `240` (4 min) | Standard deviation for session length |
| `SESSION_DURATION_MIN` | `300` (5 min) | Minimum session length |
| `SESSION_DURATION_MAX` | `1500` (25 min) | Maximum session length |
| `SEARCHES_PER_SESSION_MIN` | `2` | Min search configs used per session |
| `SEARCHES_PER_SESSION_MAX` | `4` | Max search configs used per session |

### Browser Behavior Probabilities
| Setting | Default | Description |
|---|---|---|
| `SCROLL_BACK_PROBABILITY` | `0.05` | 5% chance of scrolling upward instead of down |
| `MID_SCROLL_PAUSE_PROBABILITY` | `0.15` | 15% chance of pausing mid-scroll |
| `TILE_HOVER_PROBABILITY` | `0.40` | 40% chance of hovering a job tile per scroll round |
| `JOB_DETAIL_OPEN_PROBABILITY` | `0.35` | 35% chance of opening a job detail page per search |
| `DISTRACTION_PROBABILITY` | `0.30` | 30% chance of visiting a non-job page per session |

### Pipeline Thresholds
| Setting | Default | Description |
|---|---|---|
| `MIN_OPPORTUNITY_SCORE` | `55` | Jobs scoring below this are skipped after analysis |
| `MIN_PROPOSAL_QUALITY` | `7.0` | Proposals below this score are regenerated once |

### Safety Limits
| Setting | Default | Description |
|---|---|---|
| `MAX_PROPOSALS_PER_DAY` | `12` | Hard cap on approvals per calendar day |
| `MAX_PROPOSALS_PER_HOUR` | `3` | Hard cap on approvals per rolling hour |
| `MIN_SECONDS_BETWEEN_PROPOSALS` | `300` | Must wait 5 minutes between approvals |
| `ACTIVE_HOURS_START` | `8` | Approvals blocked before 8 AM |
| `ACTIVE_HOURS_END` | `23` | Approvals blocked at or after 11 PM |
| `MAX_CONNECTS_PER_DAY` | `50` | Stored for reference — not enforced in code currently |
| `MAX_PROPOSAL_WORD_OVERLAP` | `0.30` | Max Jaccard similarity allowed between proposals |

### LLM
| Setting | Default | Description |
|---|---|---|
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Model ID for all three Claude calls |
| `ANALYSIS_TEMPERATURE` | `0.2` | Low temp → deterministic, consistent analysis |
| `GENERATION_TEMPERATURE` | `0.7` | Higher temp → varied, natural proposal writing |
| `QUALITY_CHECK_TEMPERATURE` | `0.1` | Very low temp → consistent quality scoring |

---

## 15. How to First-Run Setup

### Option A — Docker (recommended for servers)

```bash
# 1. Clone/copy project to server
cd Up-take

# 2. Fill in your API key
cp .env.example .env
nano .env     # set ANTHROPIC_API_KEY, optionally TELEGRAM_BOT_TOKEN

# 3. Start everything
docker-compose up -d

# 4. Check logs
docker logs uptake_app -f
```

### Option B — Local (Windows)

```bash
# Double-click start.bat
# OR in a terminal:
cd D:\working-dir-d\Up-take
start.bat
```

The script: creates `.venv`, installs requirements, installs Playwright Chromium, starts uvicorn on port 8000.

### First-use steps in the dashboard

1. **Go to Settings (`/settings`)**
   - Fill in your name, skills (comma-separated), experience summary
   - Paste 3–5 of your past winning proposals into "Sample Winning Proposals" (separate with `---`)
   - The sample proposals are the single most important input for proposal quality
   - Set your min/max hourly rate
   - Set your tone description (e.g., "Direct and technical, avoids fluff, uses specific numbers")
   - Click **Save Profile**

2. **Set filter preferences** (same Settings page)
   - Min budget: minimum acceptable job budget ($)
   - Min client spent: minimum total the client has spent on Upwork ($)
   - Max existing proposals: skip jobs that already have many proposals
   - Require payment verified: recommended to leave ON
   - Blacklist keywords: one per line

3. **Go to Channels (`/channels`)**
   - Click **+ Add Config** to add your first Upwork search URL
   - Go to Upwork → find-work → search for your niche → copy the full URL (with all filters applied)
   - Paste it in, give it a name (e.g., "Python API Backend")
   - Add 2–4 search URLs for different aspects of your niche
   - **Toggle ON the Humanoid Browser channel**

4. **Watch the logs** — within a few minutes (depending on the session scheduler's timing), a browser session will start. You'll see log lines like:
   ```
   BrowserChannel started
   Starting browser session, planned duration: 847s
   Searching: Python API Backend
   New job detected: abc123def via browser_channel — 'Build REST API with FastAPI'
   Proposal ready for abc123def: quality=7.8, words=187
   ```

5. **Check Proposals (`/proposals`)** for draft proposals ready to review.

---

## 16. What Is Implemented vs. What Remains

### ✅ Fully Implemented

| Component | Details |
|---|---|
| Channel architecture | Abstract base, registry, enable/disable, auto-restart |
| Browser Channel | Scheduler, stealth factory, behavior engine, navigation, extraction, session runner |
| Deduplication Gateway | Redis + DB, source priority enrichment |
| Quick Filter | All 6 checks: budget, payment, skill overlap, blacklist, proposals, client spend |
| Deep Analyzer | Claude API, full prompt, JSON parse, score threshold |
| Proposal Generator | Claude API, voice calibration, quality check, one-shot regeneration |
| Safety Controller | Active hours, daily/hourly caps, minimum interval |
| Telegram Notifier | Message formatting, inline buttons, graceful degradation |
| Full REST API | 30+ endpoints across 7 routers |
| Web Dashboard | 5 pages: dashboard, jobs, proposals, channels, settings |
| Database schema | 8 tables, all relationships, auto-created on startup |
| Audit log | Every action logged with timestamp |
| Session persistence | BrowserSession rows saved after each session |
| Docker deployment | docker-compose with Postgres + Redis + app |
| One-click local start | start.bat / start.sh |

### ⚠️ Implemented But Needs Wiring / Testing

| Issue | Location | What to do |
|---|---|---|
| Uniqueness check not called on approval | `api/proposals.py:approve_proposal` | Call `safety.check_proposal_uniqueness(text, db)` before approving |
| Telegram callback buttons not handled | `notifications/telegram.py` | Telegram sends callback queries when user taps ✅/❌ — need a webhook endpoint or polling loop to receive them and call the approve/skip API |
| Channel status not updated on session complete | `models/channel.py` → `last_run_at` | Update `ChannelConfig.last_run_at` in `_on_session_complete` callback |
| `check_proposal_uniqueness` uses raw DB session | `safety/controller.py` | The method signature accepts `AsyncSession` but callers in `api/proposals.py` use `Depends(get_db)` — straightforward to wire |

### ❌ Not Implemented (Planned for Future Phases)

| Feature | Phase | Complexity |
|---|---|---|
| Email monitoring channel (Gmail API) | Phase 2 | Medium — Gmail Pub/Sub push subscription + email parser |
| Official Upwork API polling channel | Phase 3 | Medium — need approved API key, GraphQL queries |
| Third-party webhook receiver (Vollna, etc.) | Phase 3 | Low — FastAPI POST endpoint that receives and normalizes job data |
| Telegram callback query handler | Phase 2 | Low — python-telegram-bot Application with callback handler, calls approve/skip API |
| Full Connects tracking | Any | Low — currently stored but not enforced in safety controller |
| Feedback loop / learning | Phase 3 | High — use hire/response outcomes to tune scoring weights |
| A/B testing for proposal variants | Phase 3 | Medium — generate 2 variants, track which gets better responses |
| Multi-freelancer / agency mode | Phase 4 | High — tenant isolation, separate profiles, separate channels per user |
| Browser profile persistence | Ongoing | Medium — save/restore cookies and localStorage so Upwork remembers your login session across runs |
| Automatic Upwork login | Needed for real use | Medium — the browser needs to be logged into your Upwork account; currently assumes you've set up a saved session or the browser has cached cookies |
| CAPTCHA handling | Needed for real use | Hard — Upwork occasionally shows CAPTCHA; need detection + graceful pause |
| Session health monitoring | Phase 2 | Low — detect when a session gets no jobs (possible ban/block signal), alert user |

---

## 17. Known Limitations & Edge Cases

### Critical — Must Address Before Real Use

**1. The browser must be logged into Upwork.**  
The current code navigates to Upwork but doesn't handle login. You have two options:
- Manually log into Upwork in the launched browser window before the first automated session
- Implement cookie persistence: save the browser context's storage state after login, load it at the start of each session

Without being logged in, Upwork will show the marketing homepage, not the job feed. The extractor will return 0 jobs.

**2. Upwork DOM selectors may need updating.**  
The selectors in `extractor.py` were based on known Upwork DOM patterns. If Upwork has updated their frontend since then, some selectors may return null. Add `LOG_LEVEL=DEBUG` and check the extraction output. If jobs are extracted as empty objects, update the selector arrays.

**3. Search URLs must be pre-configured.**  
If no search configs are in the DB, the session runs but searches no URLs and finds 0 jobs.

### Non-Critical But Should Know

- The `MIN_OPPORTUNITY_SCORE` threshold (default 55) is what triggers proposal generation. If you're getting too many proposals, raise it to 65–70. If too few, lower it to 45.
- Analysis fails gracefully if Claude returns malformed JSON — the job status reverts to `"new"` but there's no retry logic. It simply won't be re-analyzed unless you manually trigger it.
- The `LLM_MODEL` env var must be a valid Anthropic model ID. If the model ID is wrong, all API calls fail.
- Safety settings changed via the API (`PUT /settings/safety`) take effect immediately but reset on server restart. To persist them, add them to `.env`.
- The dashboard stats auto-refresh every 30 seconds but the fetch calls are fire-and-forget — if the API is slow, the DOM may briefly show stale data.

---

## 18. How to Add a New Channel

The channel system is designed so that adding a new detection source requires **zero changes** to the pipeline, dashboard, or API — just implement the interface and register it.

### Step 1 — Create the channel class

```python
# src/channels/email/channel.py
import asyncio
from typing import Callable, Awaitable
from src.channels.base import DetectionChannel

class EmailChannel(DetectionChannel):
    
    def __init__(self, on_job_detected: Callable[[dict], Awaitable[None]]):
        super().__init__(on_job_detected)
        # your setup here
    
    @property
    def channel_id(self) -> str:
        return "email_channel"
    
    @property
    def display_name(self) -> str:
        return "Email Monitor"
    
    @property
    def description(self) -> str:
        return "Monitors Gmail for Upwork job alert emails via Gmail API."
    
    async def start(self) -> None:
        self._running = True
        # your detection loop here
        # call await self._emit(job_dict) for each discovered job
        # job_dict must contain at least: {id, title, url, source: "email_channel"}
    
    async def stop(self) -> None:
        self._running = False
        # signal your loop to stop
```

### Step 2 — Register in main.py

```python
# In src/main.py lifespan, after BrowserChannel:
from src.channels.email.channel import EmailChannel
registry.register(EmailChannel)
```

That's it. The channel will:
- Appear in the Channels UI at `/channels` with its own toggle
- Be persisted in `channel_configs` when enabled
- Auto-restart on server restart if it was enabled
- Feed into the same dedup → filter → analyze → generate pipeline
- Show its job counts in the channel analytics endpoint

### What the emitted job dict must contain

```python
{
    "id": "upwork_job_id",          # required — used as dedup key
    "title": "Job title",           # recommended
    "description": "Full text...",  # recommended — used in analysis
    "skills": ["python", "etc"],    # recommended — used in filter
    "budget": {"raw": "$500"},      # optional
    "client_info": {                # optional
        "paymentVerified": True,
        "clientSpent": "$5K+",
    },
    "url": "https://upwork.com/jobs/~ID",  # recommended
    "source": "email_channel",      # required — set to your channel_id
    "postedTime": "2 hours ago",    # optional
    "proposals": "5 to 10",         # optional
}
```

Any field not provided defaults to None in the DB. The filter and analyzer handle missing fields gracefully.
