# Up-take — Automated Upwork Proposal Generation

> **AI-powered job discovery and personalized proposal generation for solo freelance developers competing in the age of automation.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [The Pipeline (Step by Step)](#the-pipeline-step-by-step)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Channels](#channels)
- [The Chrome Extension](#the-chrome-extension)
- [Notifications](#notifications)
- [Safety System](#safety-system)
- [Tech Stack](#tech-stack)
- [Roadmap](#roadmap)

---

## Why This Exists

### The Problem

As a solo freelance developer on Upwork, you face the same reality as everyone else: **automation is everywhere**. Agencies and large teams use tools to scan jobs, template responses, and submit proposals within minutes of a job being posted. Competing against that speed manually is a losing game.

But here's the deeper problem — the existing automation tools are mostly **generic spam cannons**. They blast the same copy-paste template to every job, which clients immediately recognize and ignore. The proposal that wins isn't the fastest one; it's the one that demonstrates you actually read and understood the client's problem.

The grind looks like this:

1. Keep a browser tab open, constantly refreshing Upwork search
2. Scan through dozens of job listings, many irrelevant or suspicious
3. For each promising job, spend 15-30 minutes researching the client and writing a tailored proposal
4. Repeat until your connects run out or you burn out

**This is unsustainable.** But the alternative — generic automation — doesn't win jobs either.

### The Solution

Up-take automates the *discovery* and *drafting* so you can focus on the *human judgment*. It doesn't submit anything — you remain in full control.

Here's what Up-take does:

| Task | Manual | Up-take |
|------|--------|---------|
| Monitor Upwork for new jobs | Constant tab refreshing | Chrome extension passively observes your search pages |
| Filter out irrelevant jobs | Skim every listing | Rule-based QuickFilter drops obvious mismatches in <1ms |
| Analyze job quality | Gut feeling | Claude scores 10 dimensions: opportunity, relevance, client quality, red flags, etc. |
| Write a personalized proposal | 15-30 min per proposal | Claude generates a proposal in your voice, referencing your specific experience |
| Check proposal quality | Hope it's good | Built-in quality self-check with automatic regeneration if below threshold |
| Remember to check Upwork | Constant context switching | Telegram notifications with job link, score, proposal preview, and approve/skip buttons |
| Track what you sent | Spreadsheet or memory | Full database with pipeline analytics, conversion funnel, and searchable history |

**You still make the final call.** Read the proposal in Telegram, make minor edits if needed, copy it into Upwork, and submit. The machine handles the tedious parts; you handle the judgment.

---

## How It Works

```
┌──────────────────────────────────────────────────────────────────────┐
│                         THE UP-TAKE PIPELINE                          │
│                                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐       │
│  │ DISCOVER │───▶│  FILTER  │───▶│ ANALYZE  │───▶│ GENERATE │       │
│  │  (Free)  │    │  (Free)  │    │  (LLM)   │    │  (LLM)   │       │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘       │
│       │               │               │               │              │
│       ▼               ▼               ▼               ▼              │
│  Chrome           Rule-based      Claude scores    Claude writes     │
│  Extension        checks:         job quality,     proposal in       │
│  on Upwork        budget,         relevance,       YOUR voice,       │
│  search pages     skills,         red flags,       your experience,  │
│                   payment,        client intent    your tone         │
│                   blacklist                                          │
│                                                                      │
│       │               │               │               │              │
│       ▼               ▼               ▼               ▼              │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                    SAFETY CONTROLLER                       │       │
│  │  Daily/hourly limits, active hours, proposal uniqueness,  │       │
│  │  minimum intervals, natural timing variations             │       │
│  └──────────────────────────────────────────────────────────┘       │
│                              │                                       │
│                              ▼                                       │
│                    ┌─────────────────┐                               │
│                    │    TELEGRAM     │                               │
│                    │  Notification   │                               │
│                    │  with Approve/  │                               │
│                    │  Skip buttons   │                               │
│                    └─────────────────┘                               │
│                              │                                       │
│                              ▼                                       │
│                     ┌───────────────┐                                │
│                     │  YOU DECIDE   │                                │
│                     │  Edit → Send  │                                │
│                     └───────────────┘                                │
└──────────────────────────────────────────────────────────────────────┘
```

### The Core Loop

1. **Discover** — Your Chrome browser has the Up-take extension loaded. As you browse Upwork search pages normally, the extension extracts job listings and sends them to your local backend. No bot behavior — you're just browsing with your real account.

2. **Deduplicate** — A Redis-backed gateway ensures each job enters the pipeline exactly once, even if the extension sees it across multiple tabs or visits. Stale jobs (older than your configured threshold) are dropped.

3. **Filter** — A zero-cost, rule-based QuickFilter rejects jobs that don't match your profile before any LLM calls happen. It checks skill overlap, budget minimums, payment verification, blacklisted keywords, client spending history, and existing proposal counts.

4. **Analyze** — If the job passes the filter, Claude (Sonnet 4) performs a deep analysis. It scores the opportunity (0-100), assesses client quality, identifies key and hidden requirements, matches your specific experience, suggests a strategic angle, and flags any red flags. If the score is below your minimum threshold, the job is skipped — no proposal generated, no LLM cost wasted.

5. **Generate** — For jobs that score high enough, Claude writes a proposal *in your voice*. It uses your sample winning proposals as style guides, follows your tone description, references your actual experience, and targets the specific angle identified during analysis. A quality self-check scores the proposal on specificity, persuasiveness, and authenticity. If the score is below threshold, it regenerates with targeted feedback.

6. **Notify** — The proposal arrives in your Telegram chat with the job title, scores, red flags, a preview of the text, and inline **Approve** / **Skip** buttons. You can approve it, skip it, or edit it before submitting on Upwork.

7. **Submit** — You copy the proposal text, paste it into Upwork's proposal form, and submit. Mark it as submitted in the dashboard to track your conversion funnel.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            UP-TAKE SYSTEM                                │
│                                                                          │
│  ┌─────────────────────┐     ┌─────────────────────────────────────┐    │
│  │   Chrome Extension  │     │           FastAPI Backend            │    │
│  │                     │     │                                     │    │
│  │  content_script.js  │────▶│  /api/v1/extension/jobs             │    │
│  │  extractor.js       │     │  /api/v1/extension/heartbeat        │    │
│  │  background.js      │     │  /api/v1/extension/event            │    │
│  │  popup.js           │     │                                     │    │
│  └─────────────────────┘     │  /api/v1/profile/*                  │    │
│                              │  /api/v1/jobs/*                     │    │
│  ┌─────────────────────┐     │  /api/v1/proposals/*                │    │
│  │    HTMX Dashboard   │     │  /api/v1/channels/*                 │    │
│  │                     │     │  /api/v1/analytics/*                │    │
│  │  /  (dashboard)     │     │  /api/v1/settings/*                 │    │
│  │  /jobs              │     │  /api/v1/health                     │    │
│  │  /proposals         │     │                                     │    │
│  │  /channels          │     │                                     │    │
│  │  /settings          │     │                                     │    │
│  └─────────────────────┘     └──────────┬──────────────────────────┘    │
│                                         │                               │
│                    ┌────────────────────┼────────────────────┐          │
│                    │                    │                    │          │
│               ┌────▼────┐         ┌────▼────┐         ┌────▼────┐     │
│               │PostgreSQL│         │  Redis  │         │Anthropic│     │
│               │ (16)     │         │  (7)    │         │ Claude  │     │
│               │          │         │         │         │ (API)   │     │
│               │ Jobs     │         │ Job     │         │         │     │
│               │ Analyses │         │ Dedup   │         │ Analysis│     │
│               │ Proposals│         │ Ext     │         │ + Gen   │     │
│               │ Profiles │         │ State   │         │         │     │
│               │ Audit    │         │         │         │         │     │
│               └─────────┘         └─────────┘         └─────────┘     │
│                                                                          │
│                    ┌────────────────────┐                                │
│                    │ Telegram Notifier  │                                │
│                    │ (python-telegram-  │                                │
│                    │  bot)              │                                │
│                    └────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| **Async everywhere** | FastAPI + asyncpg + async Redis + async Anthropic client. Every I/O call is non-blocking. A single process handles many concurrent pipeline runs. |
| **LLM semaphore gating** | A shared `asyncio.Semaphore` caps concurrent Anthropic API calls across all pipeline instances. Prevents rate-limit errors and controls spend. |
| **Free filter before LLM** | The QuickFilter is pure Python — no network, no API cost, sub-millisecond. It eliminates 60-80% of jobs before any LLM call happens. |
| **Redis for dedup, not DB** | `SETNX` with 7-day TTL on `job:seen:{id}` is atomic, fast, and doesn't add DB load. The DB stores job data; Redis answers "have we seen this?" |
| **Channel abstraction** | `DetectionChannel` is a simple ABC: `start()`, `stop()`, `channel_id`, `display_name`, `description`. Adding a new channel means implementing 5 methods. The registry manages lifecycle. |
| **Passive extension, not active bot** | The Chrome extension only *observes* — it never submits, clicks, or modifies the page. Upwork and Cloudflare see a real user's browsing session. No automation fingerprint. |
| **PostgreSQL with JSON columns** | Job `raw_data`, `skills`, `client_info`, and `preferences` are JSONB. Flexible schema for evolving Upwork data without migrations. |
| **HTMX for dashboard** | The web UI is server-rendered HTML with HTMX for partial updates. No JavaScript framework, no build step, no API auth complexity for a local tool. |

---

## The Pipeline (Step by Step)

### 1. Deduplication Gateway (`src/pipeline/dedup.py`)

The entry point for all detected jobs. Two-stage dedup:

- **Freshness gate**: Parses relative timestamps ("12 minutes ago") and drops jobs older than `MAX_JOB_AGE_HOURS`.
- **Redis + DB dedup**: `SETNX` on `job:seen:{upwork_id}` with 7-day TTL. First detection wins — subsequent detections from other channels only enrich the existing record if they have a higher source priority.

Job data is stored in the `jobs` table with: title, description, budget, skills, client info, posted time, URL, detection source, and full raw data.

### 2. Quick Filter (`src/pipeline/filter.py`)

**Zero-cost rule engine.** No LLM calls. Configurable per freelancer profile via preferences:

| Check | Configurable |
|-------|--------------|
| Budget below minimum | `min_budget` |
| Payment not verified | `require_payment_verified` |
| Insufficient skill overlap | `min_skill_overlap` (default 1) |
| Blacklisted keywords | `blacklist_keywords` (default: "unpaid trial", "free test", "equity only", "no budget", "volunteer", "intern") |
| Too many existing proposals | `max_existing_proposals` (default 50) |
| Client spent too little | `min_client_spent` |

Returns `(passes: bool, reason: str)`. Filtered jobs are marked `filtered_out` and audited.

### 3. Deep Analyzer (`src/pipeline/analyzer.py`)

**Claude Sonnet 4** scores every dimension of the job against your profile. The prompt includes:
- Your name, skills, experience summary, and rate range
- The full job description (truncated to 3000 chars)
- Budget, required skills, experience level, project type, duration
- Client info: payment verification, total spent
- Number of existing proposals

Claude returns structured JSON with:

```
opportunity_score   (0-100)   Overall match quality
relevance_score     (0-100)   How well the job matches your skills
client_quality      (0-100)   Client history and reliability
key_requirements    [str]      Explicit requirements from the post
hidden_requirements [str]      Implicit needs read between the lines
matching_experience [str]      Your specific experience that applies
suggested_angle     str        Strategic approach for the proposal
key_selling_points  [str]      Your strongest arguments for this job
red_flags           [str]      Warnings or concerns
client_intent       enum       ready_to_hire | exploring | unclear | tire_kicker
complexity_estimate enum       low | medium | high
should_propose      bool       Derived: score >= MIN_OPPORTUNITY_SCORE
reasoning           str        Brief explanation
```

If `should_propose` is false, the job is marked `skipped` and no proposal is generated — saving both API cost and your attention.

### 4. Proposal Generator (`src/pipeline/generator.py`)

**The heart of personalization.** Claude generates a proposal in your voice using:

- Your **tone description** ("Professional, concise, confident" or whatever you configure)
- Up to 3 **sample winning proposals** as style guides
- Your **matching experience** identified during analysis
- The **suggested angle** and **key selling points** from analysis
- Your **max proposal words** limit

**Critical prompt rules** (these are what make the proposals feel human):

1. Open with a *specific detail from the job* — never "I'm excited about" or "I'd love to"
2. Show understanding of their *real problem*, not just what they listed
3. Connect 2-3 past experiences with *concrete results* (numbers, outcomes)
4. Suggest a *specific first step* that shows you've already started thinking
5. End with a *low-pressure call to action* + 1 thoughtful question
6. **FORBIDDEN phrases**: "I'd love to", "I'm the perfect fit", "I believe I can", "Dear Hiring Manager", "With X years of experience", "I am very interested"

**Quality self-check**: A second Claude call scores the proposal on specificity, persuasiveness, and authenticity (1-10). If the score is below `MIN_PROPOSAL_QUALITY`, it regenerates once with targeted feedback.

**Cost**: ~$0.02-0.04 per proposal (including quality check). Analysis adds ~$0.01-0.03. Total cost per qualified job: ~$0.03-0.07.

### 5. Notification (`src/notifications/telegram.py`)

The generated proposal is sent to your Telegram chat as a formatted message:

```
🔥 New Job Match!

*Build a Real-time Dashboard with React and D3*
Score: 82/100 | Quality: 8.5/10 | Intent: ready_to_hire

*Red Flags:*
  None

*Proposal Preview:*
```
[first 600 characters of the proposal]
```

[View Job on Upwork](https://upwork.com/...)

[✅ Approve]  [❌ Skip]
```

The inline buttons let you approve or skip directly from Telegram. The callbacks update the proposal status in the database.

---

## Project Structure

```
Up-take/
├── src/                          # Backend application
│   ├── main.py                   # FastAPI app, lifespan, route mounting
│   ├── config.py                 # All settings via environment variables
│   ├── database.py               # Async SQLAlchemy engine + session factory
│   ├── redis_client.py           # Async Redis connection singleton
│   ├── app_state.py              # Global singleton references (registry, gateway, safety)
│   │
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── job.py                # Job, Detection, BrowserSession
│   │   ├── analysis.py           # JobAnalysis (LLM output)
│   │   ├── proposal.py           # Proposal (generated text + outcomes)
│   │   ├── profile.py            # FreelancerProfile (you)
│   │   ├── channel.py            # ChannelConfig (persisted enable/disable state)
│   │   └── audit.py              # AuditLog (every pipeline action recorded)
│   │
│   ├── pipeline/                 # Core processing pipeline
│   │   ├── dedup.py              # DeduplicationGateway — entry point for all jobs
│   │   ├── filter.py             # QuickFilter — zero-cost rule-based filtering
│   │   ├── analyzer.py           # DeepAnalyzer — Claude-powered job scoring
│   │   ├── generator.py          # ProposalGenerator — personalized proposal writing
│   │   └── orchestrator.py       # PipelineOrchestrator — wires filter→analyze→generate
│   │
│   ├── channels/                 # Job discovery channel system
│   │   ├── base.py               # DetectionChannel ABC
│   │   ├── registry.py           # ChannelRegistry — lifecycle management
│   │   ├── extension/            # Chrome Extension channel
│   │   │   ├── channel.py        # ExtensionChannel (passive, receives from extension)
│   │   │   ├── ingest_api.py     # /api/v1/extension/* endpoints
│   │   │   ├── models.py         # Pydantic request/response models
│   │   │   ├── state.py          # Redis-backed extension state
│   │   │   └── watchdog.py       # Periodic heartbeat + zero-job monitoring
│   │   └── browser/              # (Deprecated) Active browser automation channel
│   │       └── _archive/         # Archived — kept for reference
│   │
│   ├── api/                      # REST API routes
│   │   ├── profile.py            # CRUD for freelancer profile
│   │   ├── jobs.py               # Job listing, stats, detail
│   │   ├── proposals.py          # Proposal listing, approve, skip, submit, outcomes
│   │   ├── channels.py           # Channel listing, enable/disable
│   │   ├── analytics.py          # Pipeline funnel, channel stats, proposal metrics
│   │   └── settings_api.py       # Runtime safety settings
│   │
│   ├── notifications/            # Alerting system
│   │   └── telegram.py           # TelegramNotifier with severity levels
│   │
│   ├── safety/                   # Safety and rate limiting
│   │   └── controller.py         # SafetyController — limits, uniqueness, timing
│   │
│   └── templates/                # HTMX dashboard (Jinja2)
│       ├── base.html
│       ├── dashboard.html
│       ├── jobs.html
│       ├── proposals.html
│       ├── channels.html
│       └── settings_page.html
│
├── extension/                    # Chrome Extension (Manifest V3)
│   ├── manifest.json             # Extension manifest
│   ├── background.js             # Service worker — scheduling, backend comms, alarms
│   ├── content_script.js         # Injected on Upwork — mutation observer, message bridge
│   ├── extractor.js              # Pure ES module — DOM extraction of job tiles
│   ├── popup.html / popup.js     # Toolbar popup — per-tab controls, settings
│   ├── options.html / options.css # Extension settings page
│   └── icons/                    # Extension icons (16, 48, 128)
│
├── docker-compose.yml            # PostgreSQL + Redis + App (3 services)
├── Dockerfile                    # Python 3.12-slim
├── requirements.txt              # Python dependencies (pinned)
├── .env                          # Secrets (gitignored)
└── .gitignore
```

---

## Quick Start

### Prerequisites

- **Python 3.12+**
- **PostgreSQL 16** (or Docker)
- **Redis 7** (or Docker)
- **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com))
- **Telegram Bot Token + Chat ID** (optional but recommended)

### Option 1: Docker (Recommended)

```bash
# Clone the repo
git clone https://github.com/your-org/up-take.git
cd up-take

# Create .env file
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Start everything
docker compose up -d

# View logs
docker compose logs -f app

# Open the dashboard
# http://localhost:8000
```

### Option 2: Local Development

```bash
# Ensure PostgreSQL and Redis are running locally
# Default: postgresql://uptake:uptake_secret@localhost:5432/uptake
# Default: redis://localhost:6379

python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env       # Edit with your keys
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### Setup Steps After Launch

1. **Create your freelancer profile** — POST to `/api/v1/profile/` or use the dashboard
2. **Load the Chrome extension** — Go to `chrome://extensions`, enable Developer Mode, "Load unpacked", select the `extension/` directory
3. **Configure the extension** — Click the Up-take icon in Chrome's toolbar, set the backend URL (`http://localhost:8000`) and API token (from your `.env`), then set your Upwork search URLs
4. **Enable the channel** — In the dashboard at `/channels`, toggle the Browser Extension channel on

The extension will now observe your Upwork tabs and forward jobs to the pipeline.

---

## Configuration

All settings are configured via environment variables in `.env`:

### Required

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key | *(required)* |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://uptake:uptake_secret@localhost:5432/uptake` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379` |

### Telegram (recommended)

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | *(empty — Telegram disabled)* |
| `TELEGRAM_CHAT_ID` | Target chat ID | *(empty)* |

### Pipeline Thresholds

| Variable | Description | Default |
|----------|-------------|---------|
| `MIN_OPPORTUNITY_SCORE` | Minimum score (0-100) to generate a proposal | `55` |
| `MIN_PROPOSAL_QUALITY` | Minimum quality (1-10) before auto-regeneration | `7.0` |
| `MAX_JOB_AGE_HOURS` | Drop jobs older than this many hours | `2` |
| `PIPELINE_MAX_CONCURRENT_LLM` | Max simultaneous Anthropic API calls | `3` |

### LLM Tuning

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_MODEL` | Anthropic model ID | `claude-sonnet-4-20250514` |
| `ANALYSIS_TEMPERATURE` | Temperature for job analysis (lower = more consistent) | `0.2` |
| `GENERATION_TEMPERATURE` | Temperature for proposal writing (higher = more creative) | `0.7` |
| `QUALITY_CHECK_TEMPERATURE` | Temperature for quality scoring (lowest = most objective) | `0.1` |

### Safety Limits

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_PROPOSALS_PER_DAY` | Hard daily limit | `12` |
| `MAX_PROPOSALS_PER_HOUR` | Hard hourly limit | `3` |
| `MIN_SECONDS_BETWEEN_PROPOSALS` | Minimum interval between approvals | `300` |
| `ACTIVE_HOURS_START` | Earliest hour to approve proposals (0-23) | `8` |
| `ACTIVE_HOURS_END` | Latest hour to approve proposals (0-23) | `23` |
| `MAX_CONNECTS_PER_DAY` | Estimated connects budget per day | `50` |
| `MAX_PROPOSAL_WORD_OVERLAP` | Max word overlap between recent proposals (0-1) | `0.30` |

### Extension Channel

| Variable | Description | Default |
|----------|-------------|---------|
| `EXTENSION_API_TOKEN` | Shared secret between extension and backend | `change-me-in-env` |
| `EXTENSION_HEARTBEAT_TIMEOUT_SECONDS` | Alert if no heartbeat for N seconds | `300` |
| `EXTENSION_PEAK_HOURS_TZ` | Timezone for peak-hour zero-job alerts | `America/New_York` |
| `EXTENSION_PEAK_HOURS_START` | Peak hours start (local) | `9` |
| `EXTENSION_PEAK_HOURS_END` | Peak hours end (local) | `22` |
| `EXTENSION_NO_JOBS_ALERT_MINUTES` | Alert if no jobs during peak for N minutes | `30` |

---

## API Reference

The full REST API is available at `http://localhost:8000/docs` (Swagger UI).

### Profile

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/profile/` | Get active freelancer profile |
| `POST` | `/api/v1/profile/` | Create profile |
| `PUT` | `/api/v1/profile/` | Update profile |
| `PUT` | `/api/v1/profile/preferences` | Update filter preferences only |

### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/jobs/` | List jobs (filterable by status, min_score; paginated) |
| `GET` | `/api/v1/jobs/stats` | Job counts by status |
| `GET` | `/api/v1/jobs/{job_id}` | Job detail with analysis |

### Proposals

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/proposals/` | List proposals (filterable by status; paginated) |
| `GET` | `/api/v1/proposals/{id}` | Proposal detail |
| `POST` | `/api/v1/proposals/{id}/approve` | Approve (optionally with edited text) |
| `POST` | `/api/v1/proposals/{id}/skip` | Skip proposal |
| `POST` | `/api/v1/proposals/{id}/submitted` | Mark as submitted on Upwork |
| `PUT` | `/api/v1/proposals/{id}/outcome` | Record client response / hire status |

### Channels

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/channels/` | List all registered channels |
| `PUT` | `/api/v1/channels/{id}/toggle` | Enable or disable a channel |

### Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/analytics/pipeline` | Conversion funnel (detected → filtered → analyzed → proposed → submitted → hired) |
| `GET` | `/api/v1/analytics/channels` | Per-channel detection stats |
| `GET` | `/api/v1/analytics/proposals` | Proposal quality metrics |
| `GET` | `/api/v1/analytics/sessions` | Browser session history |

### Extension (Internal)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/v1/extension/jobs` | Token | Ingest extracted jobs |
| `POST` | `/api/v1/extension/heartbeat` | Token | Health check + liveness |
| `POST` | `/api/v1/extension/event` | Token | Report errors/warnings |

---

## Channels

Channels are how jobs enter the pipeline. The system uses a plugin architecture — each channel implements the `DetectionChannel` abstract base class and gets registered at startup.

### Channel Interface

```python
class DetectionChannel(ABC):
    channel_id: str        # e.g. "extension_channel"
    display_name: str      # e.g. "Browser Extension"
    description: str       # Human-readable explanation

    async def start()      # Begin detecting jobs
    async def stop()       # Stop gracefully
```

### Current Channels

#### Browser Extension (`extension_channel`) — **Active**

The Chrome extension passively observes Upwork search pages in your own browser. Since you're browsing with your real, authenticated session, there is no automation footprint — Cloudflare and Upwork see normal user behavior. The extension extracts job tiles from the DOM, deduplicates them locally, and POSTs batches to the backend.

**Key properties:**
- No bot detection risk — uses your real browser session
- No login management — you're already logged in
- No CAPTCHA handling — you solve them naturally as you browse
- Per-tab scheduling — each Upwork tab has independent refresh interval
- Quiet hours — prevent tab reloading during specified hours
- Badge countdown — toolbar icon shows seconds until next refresh

#### Future Channels (Planned)

The channel abstraction makes it straightforward to add:
- **RSS/API Polling** — Poll Upwork's public feeds directly
- **Email Alerts** — Parse job alert emails
- **Slack/Discord Bots** — Receive job links shared in team channels
- **Mobile Notifications** — Push job alerts to your phone

Each would implement the same 5-method interface and plug into the existing pipeline without any changes to the core logic.

---

## The Chrome Extension

The extension is a Manifest V3 Chrome extension with four components:

### Background Service Worker (`background.js`)

The brain of the extension. Manages:

- **Per-tab scheduling** — Each Upwork tab has independent refresh intervals (fixed or random) and quiet hours. Tabs reload on their own schedule.
- **Backend communication** — All HTTP calls to the backend go through the service worker (CORS-safe). Includes the `X-Extension-Token` header for authentication.
- **Health monitoring** — Periodic heartbeat checks with configurable cooldown. 3 consecutive failures → badge shows "ERR".
- **Badge countdown** — The toolbar icon shows a live countdown to the next tab reload (MM:SS format).
- **Alarm-based persistence** — Uses Chrome Alarms API so scheduling survives service worker termination.

### Content Script (`content_script.js`)

Injected on matching Upwork pages. Handles:

- **DOM readiness detection** — Waits up to 12 seconds for job tiles to render. Reports selector breakage if none found.
- **Logged-out / Cloudflare detection** — Checks for login pages and Cloudflare challenge pages before attempting extraction.
- **MutationObserver** — Watches for DOM changes (new jobs loaded via infinite scroll or filter changes). Debounced at 800ms.
- **Message bridge** — Listens for TRIGGER_EXTRACT / STOP_EXTRACT from the service worker.

### Extractor (`extractor.js`)

A pure ES module with no side effects. Exports a single function `extractVisibleJobs(doc)` that:

1. Queries all job tiles (`section[data-ev-opening_uid]`)
2. For each tile, extracts 15+ fields using validated CSS selectors
3. Returns an array of structured job objects

The extractor is intentionally kept as a separate module — if Upwork changes their DOM, only this file needs updating. The selectors are documented with comments noting the DOM version they were validated against.

### Popup (`popup.html` + `popup.js`)

A tabbed toolbar popup for configuration:

- **Main tab** — Start/Stop toggle for the current tab, with backend connectivity indicator
- **Interval tab** — Per-tab refresh settings: fixed interval or random range, quiet hours
- **URLs tab** — Manage which Upwork search URLs the extension should monitor on
- **Status tab** — Active tabs list with live countdowns, backend connection status, extension version

---

## Notifications

### Telegram

The primary notification channel. When a proposal is generated:

```
🔥 New Job Match!

*Build a Real-time Dashboard with React and D3*
Score: 82/100 | Quality: 8.5/10 | Intent: ready_to_hire

*Red Flags:*
  None

*Proposal Preview:*
```
Hi — I noticed your dashboard needs to handle 10K+ data points
at 60fps. At [Company], I built a similar real-time analytics
dashboard using Canvas instead of SVG for the chart layer,
which cut rendering time from 400ms to 16ms...
```

[View Job on Upwork](https://upwork.com/...)

[✅ Approve]  [❌ Skip]
```

The inline buttons call back to the backend API to update the proposal status.

**Operational alerts** are also sent via Telegram with severity levels:

| Severity | Example |
|----------|---------|
| INFO | Extension channel ready, pipeline started |
| WARNING | No jobs detected during peak hours (extension may need attention) |
| ERROR | Heartbeat lost (extension disconnected) |
| CRITICAL | *(reserved for channel crashes requiring manual restart)* |

All alerts include debouncing — the same alert won't fire again within 30 minutes.

---

## Safety System

The `SafetyController` is a gatekeeper that prevents behavior that could look automated or exceed Upwork's limits:

| Check | Implementation |
|-------|---------------|
| **Active hours** | Proposals can only be approved between `ACTIVE_HOURS_START` and `ACTIVE_HOURS_END` |
| **Daily limit** | Hard cap at `MAX_PROPOSALS_PER_DAY` approved/submitted proposals |
| **Hourly limit** | Hard cap at `MAX_PROPOSALS_PER_HOUR` |
| **Minimum interval** | At least `MIN_SECONDS_BETWEEN_PROPOSALS` between approvals |
| **Proposal uniqueness** | No two recent proposals share more than `MAX_PROPOSAL_WORD_OVERLAP` (30%) of words |
| **Natural timing** | Random Gaussian delay with 2s minimum to avoid robotic submission patterns |

These checks run before every proposal approval. If any check fails, the API returns HTTP 429 with the specific reason.

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Web framework** | FastAPI 0.115 | Native async, automatic OpenAPI docs, Pydantic validation |
| **Server** | Uvicorn | ASGI server with hot reload for development |
| **Database** | PostgreSQL 16 + SQLAlchemy 2.0 (async) | Reliable, JSONB for flexible job data, async for pipeline throughput |
| **Cache** | Redis 7 | Atomic dedup via SETNX, TTL-based state, heartbeat tracking |
| **LLM** | Anthropic Claude (Sonnet 4) | Best instruction following for proposal quality, structured JSON output |
| **Notifications** | python-telegram-bot | Inline keyboards for approve/skip, Markdown formatting |
| **Task scheduling** | APScheduler | Watchdog and periodic jobs within the async event loop |
| **Browser extension** | Chrome Manifest V3 | Service worker, alarms API, content scripts, no external dependencies |
| **Frontend** | Jinja2 + HTMX | Server-rendered with partial updates, no JS framework for a local admin panel |
| **Containerization** | Docker Compose | One-command setup with PostgreSQL + Redis + App |
| **Config** | python-decouple | Environment variables with sensible defaults |

---

## Roadmap

- [ ] **Telegram callback handling** — Wire up the Approve/Skip button callbacks (currently the buttons are present but need a webhook endpoint)
- [ ] **Additional channels** — RSS/API polling channel, email alert parsing channel
- [ ] **Multi-profile support** — Manage multiple freelancer profiles for different skill sets
- [ ] **Proposal analytics** — Track which proposal styles and angles lead to client responses and hires
- [ ] **Upwork API integration** — When Upwork's API supports it, submit proposals directly
- [ ] **Discord/Slack notifications** — Alternative notification channels
- [ ] **Search configuration UI** — Configure Upwork search URLs and filters from the dashboard
- [ ] **Proposal templates** — User-defined proposal structure templates for different job types

---

## License

MIT

---

**Built for solo developers who want to compete on quality, not just speed.**
