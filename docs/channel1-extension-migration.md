# Channel 1 — Browser Extension Migration

**Branch:** `ch1-migration`  
**Status:** Implemented, pending first run  
**Replaces:** Patchright-based Humanoid Browser (`browser_channel`)  
**New channel ID:** `extension_channel`

---

## Table of Contents

1. [Why This Was Done](#1-why-this-was-done)
2. [What Changed](#2-what-changed)
3. [Architecture Overview](#3-architecture-overview)
4. [How It Works End-to-End](#4-how-it-works-end-to-end)
5. [Backend — New Files in Detail](#5-backend--new-files-in-detail)
6. [Chrome Extension — Files in Detail](#6-chrome-extension--files-in-detail)
7. [API Endpoints Reference](#7-api-endpoints-reference)
8. [Redis State Keys](#8-redis-state-keys)
9. [Watchdog & Alerts](#9-watchdog--alerts)
10. [Configuration Reference](#10-configuration-reference)
11. [What Stayed the Same](#11-what-stayed-the-same)
12. [What Was Deprecated](#12-what-was-deprecated)
13. [Next Steps](#13-next-steps)

---

## 1. Why This Was Done

The original Channel 1 (`browser_channel`) used **Patchright** — a patched fork of Playwright — to drive a persistent Chrome profile at `sessions/chrome_profile/`. It simulated human-like browser behaviour (Bezier mouse curves, Gaussian scroll variance, randomised work windows) to avoid Cloudflare detection while scraping Upwork job feeds.

The fundamental problem: **CDP/WebDriver automation signals are detectable at the browser binary level**, and every session started from a stale cookie or a new IP was one Cloudflare challenge away from breaking the whole pipeline. Maintenance cost was open-ended.

The extension approach sidesteps this entirely:

| Old (Patchright) | New (Extension) |
|---|---|
| Automation framework drives Chrome | User's own Chrome, manually opened |
| Cookie injection, UA matching, fingerprint management | No fingerprint to manage — user's real browser IS the fingerprint |
| `sessions/chrome_profile/` accumulated trust | Session trust is the user's actual logged-in Upwork session |
| CDP signals visible to Cloudflare | No CDP — extension is just JavaScript running in a normal tab |
| Constant Cloudflare debugging | Cloudflare challenges are rare in a real user's browser; when they appear the user solves them manually |
| Breaks on stale cookies | Breaks only when the user's own session expires (~monthly) |

---

## 2. What Changed

### 2.1 Files Deprecated (moved to `_archive/`)

All browser channel implementation files were moved via `git mv` to `src/channels/browser/_archive/` to preserve full git history. The directory still exists but is not importable by live code — its `__init__.py` raises `ImportError` on import.

```
src/channels/browser/_archive/
├── __init__.py          ← raises ImportError ("not for runtime import")
├── behavior.py          ← HumanBehaviorEngine (Gaussian scroll, Bezier mouse)
├── channel.py           ← BrowserChannel class
├── cookie_import.py     ← Chrome cookie import script
├── extractor.py         ← DOMExtractor + EXTRACT_SCRIPT (JS source of truth)
├── factory.py           ← BrowserFactory (Patchright persistent context)
├── login_manager.py     ← Session cookie persistence
├── navigation.py        ← NavigationEngine
├── page_guard.py        ← PageGuard (Cloudflare/error detection)
├── save_session.py      ← Manual login script (legacy)
├── scheduler.py         ← SessionScheduler (work-window timing)
├── session_runner.py    ← BrowserSessionRunner (main session loop)
└── test_channel1.py     ← Smoke test (moved from project root)
```

`src/channels/browser/__init__.py` was stripped to a stub comment — the module is importable but exports nothing.

### 2.2 Files Deleted

- `sessions/chrome_profile/` — entire Patchright persistent profile directory
- `sessions/upwork_session.json` — exported session cookies

### 2.3 Dependencies Removed from `requirements.txt`

```
playwright==1.48.0          ← removed
patchright==1.59.1          ← removed
fake-useragent==1.5.1       ← removed
browser-cookie3==0.20.1     ← removed
```

No new dependencies added. The extension channel uses only what was already in the stack (FastAPI, Redis, APScheduler, Pydantic).

### 2.4 Files Modified

| File | What changed |
|---|---|
| `src/main.py` | Replaced `BrowserChannel` registration with `ExtensionChannel`; mounted extension API router; added CORS for `chrome-extension://` origins; added APScheduler + watchdog startup |
| `src/config.py` | Added 12 `extension_*` settings (see §10) |
| `src/channels/registry.py` | Added `get(channel_id)` method so the API router can retrieve a live channel instance |
| `src/api/channels.py` | Updated toggle endpoint to pass `notifier` for `extension_channel` instead of `search_configs` for `browser_channel`; updated trigger endpoint to return a meaningful message for passive channel |
| `requirements.txt` | Removed 4 browser automation deps |
| `.env` | Added `EXTENSION_API_TOKEN` and commented-out extension settings |

### 2.5 Files Created

```
src/channels/extension/
├── __init__.py          ← exports ExtensionChannel
├── channel.py           ← ExtensionChannel class (passive, no loop)
├── ingest_api.py        ← FastAPI router — 4 endpoints
├── models.py            ← Pydantic request/response schemas
├── state.py             ← Redis state accessors
└── watchdog.py          ← APScheduler watchdog task

extension/               ← Chrome extension (top-level, not under src/)
├── manifest.json
├── background.js        ← Service worker (alarms, rotation, heartbeat)
├── content_script.js    ← Injected into Upwork search tabs
├── extractor.js         ← ES module: extractVisibleJobs(doc)
├── options.html
├── options.js
├── options.css
├── icons/
│   ├── icon16.png
│   ├── icon48.png
│   └── icon128.png
└── README.md

scripts/
└── enable_extension_channel.py   ← one-off DB seed
```

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────┐         ┌────────────────────────────────────────┐
│  User's normal Chrome (manually opened)      │         │  FastAPI backend (localhost:8000)       │
│                                              │         │                                        │
│  ┌──────────────────────────────────────┐    │  HTTP   │  ┌────────────────────────────────┐   │
│  │  Pinned Upwork search tab            │    │  POST   │  │  ingest_api.py                 │   │
│  │                                      │────┼─────────┼─▶│  POST /api/v1/extension/jobs   │   │
│  │  content_script.js                   │    │         │  │  POST /api/v1/extension/hbeat  │   │
│  │  ├─ Cloudflare / logout detection    │    │         │  │  POST /api/v1/extension/event  │   │
│  │  ├─ waitFor(job-tile-list)           │    │         │  │  GET  /api/v1/extension/config │   │
│  │  ├─ import extractor.js             │    │         │  └───────────────┬────────────────┘   │
│  │  ├─ extractVisibleJobs(document)    │    │         │                  │ channel._emit()     │
│  │  └─ MutationObserver → re-extract  │    │         │                  ▼                     │
│  └────────────────────────────────────┘    │         │  ┌────────────────────────────────┐   │
│       ↕  chrome.runtime messages           │         │  │  ExtensionChannel (passive)    │   │
│  ┌──────────────────────────────────────┐   │         │  │  channel_id = extension_channel│   │
│  │  background.js (service worker)      │   │         │  └───────────────┬────────────────┘   │
│  │  ├─ chrome.alarms (reload timer)    │   │         │                  │ _on_job callback    │
│  │  ├─ Tab claiming & rotation         │   │         │                  ▼                     │
│  │  ├─ Heartbeat every 60s            │   │         │  ┌────────────────────────────────┐   │
│  │  └─ Config refetch every 5min      │   │         │  │  DeduplicationGateway (Redis)  │   │
│  └──────────────────────────────────────┘   │         │  └───────────────┬────────────────┘   │
│                                              │         │                  ▼                     │
│  options.html  ─  backend URL + token UI     │         │  ┌────────────────────────────────┐   │
└──────────────────────────────────────────────┘         │  │  PipelineOrchestrator          │   │
                                                         │  │  ├─ QuickFilter                │   │
                                                         │  │  ├─ DeepAnalyzer (Claude)      │   │
                                                         │  │  └─ ProposalGenerator          │   │
                                                         │  └───────────────┬────────────────┘   │
                                                         │                  ▼                     │
                                                         │  ┌────────────────────────────────┐   │
                                                         │  │  TelegramNotifier              │   │
                                                         │  │  → Proposal alert to user      │   │
                                                         │  └────────────────────────────────┘   │
                                                         │                                        │
                                                         │  ┌────────────────────────────────┐   │
                                                         │  │  watchdog.py (APScheduler 60s) │   │
                                                         │  │  ├─ Heartbeat stale? → alert  │   │
                                                         │  │  └─ No jobs in peak? → alert  │   │
                                                         │  └────────────────────────────────┘   │
                                                         └────────────────────────────────────────┘
```

### Key Architectural Point: Extension vs. Backend Separation

The extension and backend are completely decoupled. The **extension knows nothing about the pipeline**. It only knows:
1. Where the backend is (URL + token, set by the user in options.html)
2. That it should POST extracted jobs to `/api/v1/extension/jobs`
3. That it should POST a heartbeat every 60s
4. That it can GET its config (search URLs, timing) from the backend

The **backend knows nothing about Chrome**. It only knows:
1. A batch of jobs arrived via HTTP POST
2. Each job is a plain dict → feed into the existing dedup → pipeline chain
3. No heartbeat arrived for >5 min → alert

The JSON payload over HTTP is the only contract. If the extension is rewritten in a different language tomorrow, or the backend pipeline changes completely, neither side needs to know about the other's internals.

---

## 4. How It Works End-to-End

### 4.1 Normal job discovery cycle

```
1. User opens Chrome, navigates to upwork.com/nx/find-work/best-matches
   └── background.js sees tab URL matches pattern → claims it as "managed tab"

2. content_script.js injects into the tab (run_at: document_idle)
   ├── Checks for Cloudflare challenge → POSTs EVENT if found
   ├── Checks for logged-out state → POSTs EVENT if found
   ├── waitFor('[data-test="job-tile-list"]', 10s)
   │   └── If not found → POSTs selector_breakage EVENT
   └── Imports extractor.js dynamically → calls extractVisibleJobs(document)
       └── Returns array of job objects with snake_case field names

3. content_script.js → chrome.runtime.sendMessage({ type: "EXTRACTED_JOBS", jobs })
   └── background.js receives message → POSTs to /api/v1/extension/jobs

4. Backend ingest_api.py receives batch
   ├── Validates X-Extension-Token header
   ├── Checks ExtensionChannel is running
   ├── For each job: calls channel._emit(job.model_dump())
   │   └── _emit() calls _on_job() callback → DeduplicationGateway.process()
   │       ├── Redis SETNX check: job ID already seen? → drop silently
   │       └── New job → PipelineOrchestrator.process()
   │           ├── QuickFilter: title/budget/skills heuristics
   │           ├── DeepAnalyzer: Claude LLM scores the opportunity
   │           └── ProposalGenerator: Claude drafts a proposal
   │               └── TelegramNotifier.send_proposal_alert() → user's phone
   └── Records last_job_at in Redis

5. MutationObserver in content_script.js watches for DOM changes
   └── If Upwork re-renders tiles (sort change, filter change) → re-extracts after 800ms debounce

6. chrome.alarms fires after 6–14 min (jittered)
   └── background.js picks next URL from rotation → chrome.tabs.update(managedTabId, { url })
       └── Tab navigates → content_script.js fires again → new extraction cycle
```

### 4.2 Heartbeat cycle (independent of job discovery)

```
Every 60 seconds:
  background.js alarm fires → POSTs /api/v1/extension/heartbeat
  ├── Payload: { extension_version, tabs: [{tab_id, url}], last_job_at }
  └── Backend records timestamp in Redis key "extension:heartbeat:last" (TTL 10 min)

Every 60 seconds on the backend:
  watchdog_tick() runs
  ├── Reads "extension:heartbeat:last" from Redis
  ├── If age > 300s (5 min): fires "💤 Extension Heartbeat Lost" Telegram alert
  │   └── Debounced 30 min (won't re-alert until key expires)
  └── If in peak hours AND no job seen in 30+ min: fires "🔍 No Jobs" alert
      └── Also debounced 30 min
```

### 4.3 Config refetch cycle

```
Every 5 minutes:
  background.js alarm fires → GETs /api/v1/extension/config
  └── Backend reads SearchConfig rows from Postgres (is_active=True)
      └── Returns { searches, reload_min_seconds, reload_max_seconds, quiet_hours, ... }
          └── background.js stores in chrome.storage.local["config"]
              └── All subsequent reloads use the updated search list
```

This means changing search URLs or timing in the backend dashboard takes effect in the extension within 5 minutes — no reinstall, no options page visit required.

### 4.4 Quiet hours

During configured quiet hours (default 1am–7am local time), the reload alarm still fires on schedule but `reloadManagedTab()` detects the quiet window and skips the navigation. Heartbeats continue — the backend knows the extension is alive; it just isn't cycling tabs.

---

## 5. Backend — New Files in Detail

### `src/channels/extension/__init__.py`

Package initialiser. Imports and re-exports `ExtensionChannel` so callers can write `from src.channels.extension import ExtensionChannel`.

### `src/channels/extension/channel.py` — `ExtensionChannel`

Implements `DetectionChannel` (the abstract base class shared by all channels).

**Critical difference from `BrowserChannel`:** `start()` is a near-no-op. There is no internal async loop, no scheduler, no factory, no browser. The channel just sets `_running = True`, logs a line, and optionally sends a Telegram startup notification.

The only work this class does at runtime is when `ingest_api.py` calls `channel._emit(job)` — which calls the `_on_job` callback that was wired in during registry initialisation. That callback leads straight into `DeduplicationGateway.process()`.

```python
# Registry wires it like this (in main.py):
registry = ChannelRegistry(on_job_detected=_on_job)   # _on_job → gateway.process
registry.register(ExtensionChannel)

# When enable() is called:
instance = ExtensionChannel(on_job_detected=_on_job, notifier=notifier)
asyncio.create_task(instance.start())   # essentially instant

# When a job batch arrives via HTTP:
await channel._emit(job_dict)   # → _on_job(job_dict) → gateway.process(job_dict)
```

### `src/channels/extension/models.py` — Pydantic Schemas

Seven models that define the exact wire format between the extension (JavaScript) and the backend (Python).

| Model | Direction | Purpose |
|---|---|---|
| `ExtractedJob` | ext → backend | One job tile. All fields snake_case. `source` is always `"extension_channel"`. |
| `JobIngestRequest` | ext → backend | Batch of `ExtractedJob`, plus `tab_url` and `extension_version` for logging |
| `JobIngestResponse` | backend → ext | `{received, new, duplicates}` counts |
| `HeartbeatRequest` | ext → backend | Extension version, list of managed tab metadata |
| `HeartbeatResponse` | backend → ext | `{ok, server_time}` |
| `ExtensionEvent` | ext → backend | Out-of-band events: `logged_out`, `cloudflare_challenge`, `selector_breakage`, `extraction_error`, `tab_closed` |
| `ConfigResponse` | backend → ext | Search URLs, timing windows, interval settings |

`ExtractedJob` field names deliberately match the fields produced by `extractor.js` and expected by `PipelineOrchestrator`. No transformation happens in between.

### `src/channels/extension/state.py` — Redis State

Thin async wrapper around six Redis keys, all prefixed `extension:`.

| Key | TTL | Stores |
|---|---|---|
| `extension:heartbeat:last` | 600s | `"{iso_timestamp}|{version}|{tabs_count}"` |
| `extension:last_job_at` | permanent | ISO timestamp of last ingested job |
| `extension:last_event:{kind}` | 600s | `"{iso_timestamp}|{detail}"` |
| `extension:last_alert:{name}` | 1800s | `"1"` (existence = debounce active) |

`should_alert(name)` is the debounce primitive: it checks if the key exists; if not, sets it with 30-min TTL and returns `True`. This prevents the same alert from firing multiple times within the cooldown window even if the watchdog runs every 60s.

### `src/channels/extension/ingest_api.py` — FastAPI Router

Mounted at `/api/v1/extension` in `main.py`. All four endpoints require the `X-Extension-Token` header.

Full reference in [§7 API Endpoints Reference](#7-api-endpoints-reference).

### `src/channels/extension/watchdog.py` — APScheduler Task

`watchdog_tick()` runs every 60 seconds via an `AsyncIOScheduler` created in `main.py`. It performs two independent checks:

1. **Heartbeat freshness.** Reads the last heartbeat timestamp from Redis. If older than `EXTENSION_HEARTBEAT_TIMEOUT_SECONDS` (default 300s), fires a Telegram alert and returns early (skips the second check — if the extension is dead, the zero-jobs check is noise).

2. **Zero-jobs during peak hours.** Only runs if the heartbeat is fresh (extension is alive). Checks the `extension:last_job_at` Redis key. If the value is missing or older than `EXTENSION_NO_JOBS_ALERT_MINUTES` (default 30) during peak hours, fires a different Telegram alert distinguishing "alive but not seeing jobs" from "extension is gone".

Both alerts are debounced at 30 minutes via `should_alert()`.

---

## 6. Chrome Extension — Files in Detail

### `extension/manifest.json`

Manifest V3. Permissions kept to the absolute minimum required:

| Permission | Why needed |
|---|---|
| `storage` | Save backend URL, API token, config, managed tab ID |
| `alarms` | Schedule reload and heartbeat timers (survives service worker suspension) |
| `tabs` | Read tab URLs, update managed tab URL, listen for tab close |
| `scripting` | Required by MV3 when content scripts use dynamic import |
| `host_permissions: upwork.com/*` | Send HTTP requests to Upwork tabs, inject content scripts |

`content_scripts` is limited to `/nx/find-work/*` and `/nx/search/jobs*` — the extension only activates on actual search result pages, not on every Upwork page.

### `extension/extractor.js`

An ES module (importable with `import()`). Exports a single function:

```javascript
export function extractVisibleJobs(doc) → Array<Object>
```

This is a direct port of the original Python `EXTRACT_SCRIPT` string from `src/channels/browser/_archive/extractor.py`. All extraction logic, selectors, and fallback sequences were preserved exactly. The only changes were:

1. Wrapped in an ES module `export function` instead of an IIFE
2. Changed `document.querySelectorAll(...)` to `doc.querySelectorAll(...)` so the function accepts any document object (testable in isolation)
3. Renamed output fields from camelCase to snake_case to match `ExtractedJob` Pydantic model: `jobType` → `job_type`, `experienceLevel` → `experience_level`, `postedTime` → `posted_time`, `clientSpent` → `client_spent`, `clientRating` → `client_rating`, `clientLocation` → `client_location`, `paymentVerified` → `payment_verified`, `observedAt` → `observed_at`
4. Changed `source: 'browser_channel'` to `source: 'extension_channel'`

**The selectors themselves are unchanged.** They were validated against live Upwork HTML in April 2026 and are the most operationally valuable part of the old codebase.

Key selectors (for reference when debugging):

| Field | Selector |
|---|---|
| Job tile container | `article.job-tile, article[data-ev-job-uid]` |
| Job ID | `data-ev-job-uid` attribute on tile |
| Title | `[data-test="job-tile-title-link"]` |
| Description | `[class*="air3-line-clamp"] p` → `p.text-body-sm` |
| Job type | `[data-test="job-type-label"]` |
| Fixed budget | `[data-test="is-fixed-price"]` |
| Duration | `[data-test="duration-label"]` |
| Posted time | `[data-test="job-pubilshed-date"]` ← Upwork typo intentional |
| Proposals | `[data-test="proposals-tier"]` |
| Payment verified | `[data-test="payment-verified"]` presence |
| Client spent | `[data-test="total-spent"] strong` |
| Client rating | `[data-test="feedback-rating"] .air3-rating-value-text` |
| Client location | `[data-test="location"]` |
| Skills | `[data-test="token"]` (all matching) |

### `extension/content_script.js`

Injected into matching Upwork pages at `document_idle`. Execution flow:

```
1. Detect Cloudflare challenge (title="Just a moment...", #challenge-form, .cf-turnstile)
   └── If found → sendMessage(EVENT: cloudflare_challenge) → return

2. Detect logged-out state (absence of user-menu-trigger, login URL patterns)
   └── If found → sendMessage(EVENT: logged_out) → return

3. waitFor('[data-test="job-tile-list"]', 10s)
   └── If not found → sendMessage(EVENT: selector_breakage) → return

4. Dynamic import of extractor.js via chrome.runtime.getURL()

5. extractVisibleJobs(document) → jobs array

6. sendMessage(EXTRACTED_JOBS: jobs)
   └── background.js receives → POSTs to backend

7. MutationObserver on container (childList: true, subtree: false)
   └── On change → debounced 800ms → extractAndSend("mutation")
```

The content script only communicates with `background.js` via `chrome.runtime.sendMessage`. It never calls the backend directly. All network requests go through the service worker.

### `extension/background.js`

The service worker. Manages all timers and network calls.

**Tab management:** Listens to `chrome.tabs.onUpdated` — the first tab that navigates to a matching Upwork URL becomes the "managed tab" (stored in `chrome.storage.local.managedTabId`). When that tab closes, the stored ID is cleared. The next qualifying tab that opens will be claimed.

**Reload cycle:**
```
scheduleNextReload()
  → chrome.alarms.create(ALARM_RELOAD, { delayInMinutes: rand(6..14) })

Alarm fires → reloadManagedTab()
  → isQuietHour()? → skip, reschedule
  → pickNextSearchUrl() → rotates through config.searches
  → chrome.tabs.update(managedTabId, { url: nextUrl })
  → scheduleNextReload()
```

Rotation is sequential through the searches array (not weighted — weight field reserved for future use). Each alarm creates the next alarm, so the cycle is self-perpetuating.

**Bootstrap:** `onInstalled` and `onStartup` both call `bootstrap()` which:
1. Attempts a config refetch from the backend (may fail if backend isn't up yet — harmless)
2. Creates the `heartbeat` alarm with `periodInMinutes` (repeating)
3. Creates the `config-refetch` alarm with `periodInMinutes` (repeating)
4. Calls `scheduleNextReload()` for the first one-shot reload alarm

`chrome.alarms` are used instead of `setInterval` because service workers are suspended by the browser when idle. Alarms persist through suspension and wake the worker when they fire.

### `extension/options.html` / `options.js` / `options.css`

A single-page settings UI. The user sets exactly two values:

- **Backend URL** — where `uvicorn` is running (default `http://localhost:8000`)
- **API Token** — must match `EXTENSION_API_TOKEN` in `.env`

**Test Connection** button hits `/api/v1/extension/config` live and displays the result, confirming auth and connectivity in one action.

The read-only section shows the last-fetched config (search list and timing settings) pulled from `chrome.storage.local`.

---

## 7. API Endpoints Reference

All endpoints are under the prefix `/api/v1/extension` and require the header:

```
X-Extension-Token: <value of EXTENSION_API_TOKEN>
```

Missing or wrong token → `401 Unauthorized`. Token not configured on server → `500 Internal Server Error`.

---

### `POST /api/v1/extension/jobs`

Ingest a batch of job tiles extracted by the content script.

**Request body:**
```json
{
  "jobs": [
    {
      "id": "~01abc123def456",
      "title": "Django Backend Developer",
      "description": "We need a senior Django developer...",
      "budget": null,
      "job_type": "Hourly",
      "experience_level": "Expert",
      "duration": "3 to 6 months",
      "skills": ["Django", "Python", "REST API"],
      "posted_time": "Posted 2 hours ago",
      "proposals": "5 to 10",
      "client_spent": "$10K+",
      "client_rating": "4.95",
      "client_location": "United States",
      "payment_verified": true,
      "url": "https://www.upwork.com/jobs/Django-Backend-Developer_~01abc123def456/",
      "source": "extension_channel",
      "observed_at": "2026-04-30T14:23:01.000Z"
    }
  ],
  "tab_url": "https://www.upwork.com/nx/find-work/best-matches",
  "extension_version": "1.0.0"
}
```

**Response:**
```json
{
  "received": 12,
  "new": 12,
  "duplicates": 0
}
```

**Backend behaviour:**
- Validates channel is running (`extension_channel.is_running`)
- Iterates `jobs`, calls `channel._emit(job)` for each
- Each `_emit` calls `DeduplicationGateway.process()` which does the Redis dedup
- Records `last_job_at` in Redis
- Logs one line per batch: `Extension batch: received=N from <url> (ext v1.0.0)`

**Error codes:**
- `401` — bad token
- `503` — extension channel not enabled

---

### `POST /api/v1/extension/heartbeat`

Liveness ping. Called by the service worker every 60 seconds.

**Request body:**
```json
{
  "extension_version": "1.0.0",
  "tabs": [
    {
      "tab_id": 42,
      "url": "https://www.upwork.com/nx/find-work/best-matches",
      "last_extraction_at": null,
      "jobs_seen": 0
    }
  ],
  "last_job_at": null
}
```

**Response:**
```json
{
  "ok": true,
  "server_time": "2026-04-30T14:24:00.000Z"
}
```

**Backend behaviour:**
- Writes `"{now}|{version}|{tabs_count}"` to `extension:heartbeat:last` in Redis with 600s TTL
- If `last_job_at` is provided, also writes `extension:last_job_at`
- Watchdog reads this key every 60s to detect staleness

---

### `POST /api/v1/extension/event`

Report an out-of-band event from the content script. Used for states the content script detects that aren't normal job extraction.

**Request body:**
```json
{
  "kind": "cloudflare_challenge",
  "url": "https://www.upwork.com/nx/find-work/best-matches",
  "detail": null,
  "occurred_at": "2026-04-30T14:25:00.000Z"
}
```

Valid `kind` values:

| Kind | When sent | Immediate Telegram alert |
|---|---|---|
| `logged_out` | Login page detected, user-menu absent | Yes (debounced 30 min) |
| `cloudflare_challenge` | CF challenge page detected | Yes (debounced 30 min) |
| `selector_breakage` | `job-tile-list` container not found after 10s | Yes (debounced 60 min, set in code at 30 min) |
| `extraction_error` | JavaScript exception inside `extractVisibleJobs()` | No (logged only) |
| `tab_closed` | Reserved for future use | No |

**Response:**
```json
{ "ok": true }
```

---

### `GET /api/v1/extension/config`

Pull current search configuration. Called by the service worker every 5 minutes.

**Response:**
```json
{
  "searches": [
    {
      "label": "Python Django",
      "url": "https://www.upwork.com/nx/search/jobs?q=django+python&sort=recency",
      "weight": 1.0
    },
    {
      "label": "Best Matches",
      "url": "https://www.upwork.com/nx/find-work/best-matches",
      "weight": 1.0
    }
  ],
  "reload_min_seconds": 360,
  "reload_max_seconds": 840,
  "quiet_hours_start": 1,
  "quiet_hours_end": 7,
  "heartbeat_interval_seconds": 60,
  "config_refetch_interval_seconds": 300
}
```

**Backend behaviour:**
- Queries `SearchConfig` table for `is_active=True` rows
- Falls back to a hardcoded Best Matches entry if the table is empty
- Reads timing values from `settings` (loaded from `.env`)

This endpoint is the single source of truth for what the extension should do. No extension reinstall is needed to change search URLs or timing.

---

## 8. Redis State Keys

All keys are prefixed `extension:` and use the existing Redis connection from `src/redis_client.py`.

| Key | Type | TTL | Meaning |
|---|---|---|---|
| `extension:heartbeat:last` | String | 600s | `"{iso}|{version}|{tabs}"` — last heartbeat timestamp |
| `extension:last_job_at` | String | none | ISO timestamp of last job ingested |
| `extension:last_event:{kind}` | String | 600s | `"{iso}|{detail}"` — last occurrence of this event kind |
| `extension:last_alert:{name}` | String | 1800s | `"1"` — debounce sentinel; existence means alert is on cooldown |

Alert names used with `last_alert`:

| Name | Debounce |
|---|---|
| `heartbeat_lost` | 30 min |
| `zero_jobs_peak` | 30 min |
| `event:logged_out` | 30 min |
| `event:cloudflare_challenge` | 30 min |
| `event:selector_breakage` | 30 min |

---

## 9. Watchdog & Alerts

The watchdog (`watchdog_tick`) runs every 60s via APScheduler. It fires Telegram alerts through the standard `TelegramNotifier` instance already used by the pipeline.

### Alert decision tree

```
watchdog_tick()
│
├─ get_notifier() → None?  →  return (Telegram not configured)
│
├─ get_last_heartbeat() → None?  →  return (never seen a heartbeat — fresh boot, no alert)
│
├─ heartbeat age > 300s?
│   └─ YES → should_alert("heartbeat_lost")?
│       ├─ YES → send "💤 Extension Heartbeat Lost" → return
│       └─ NO  → return (debounce active)
│
└─ is_peak_hour(now)?
    └─ YES → last_job_at missing OR age > 30min?
        └─ YES → should_alert("zero_jobs_peak")?
            ├─ YES → send "🔍 No Jobs Detected During Peak Hours"
            └─ NO  → (debounce active)
```

### Alert messages

**💤 Extension Heartbeat Lost**
Fires when heartbeat is >5 min stale. Means Chrome closed, machine slept, extension disabled, or network issue. No job discovery happening.

**🔍 No Jobs Detected During Peak Hours**
Fires during peak hours (9am–10pm configured timezone) when the last job was seen >30 min ago AND heartbeat is fresh. Means the extension is running but not finding jobs — likely a selector change, a logged-out tab, or overly narrow search filters.

**🔑 Upwork Session Expired** (from `/event` endpoint)
Immediate alert when the content script detects a login page. Debounced 30 min.

**🛡️ Cloudflare Challenge** (from `/event` endpoint)
Immediate alert when the content script detects a CF challenge page. User should open the tab and click the checkbox.

**⚙️ Extension Selector Broken** (from `/event` endpoint)
Fires when `job-tile-list` container is not found after 10s. Upwork likely refactored their HTML. Requires updating selectors in `extension/extractor.js`.

---

## 10. Configuration Reference

### New settings added to `src/config.py`

```python
extension_api_token: str = "change-me-in-env"
extension_reload_min_seconds: int = 360          # 6 min
extension_reload_max_seconds: int = 840          # 14 min
extension_heartbeat_interval_seconds: int = 60
extension_heartbeat_timeout_seconds: int = 300   # 5 min before alert
extension_config_refetch_seconds: int = 300      # 5 min
extension_quiet_hours_start: int = 1             # 1am local
extension_quiet_hours_end: int = 7               # 7am local
extension_peak_hours_tz: str = "America/New_York"
extension_peak_hours_start: int = 9              # 9am local
extension_peak_hours_end: int = 22               # 10pm local
extension_no_jobs_alert_minutes: int = 30
```

All values are loaded from environment variables (same names, uppercased). Only `EXTENSION_API_TOKEN` is required to be set; all others have usable defaults.

### `.env` additions

```dotenv
# Required: generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
EXTENSION_API_TOKEN=change-me-in-env

# Optional overrides (defaults shown)
# EXTENSION_RELOAD_MIN_SECONDS=360
# EXTENSION_RELOAD_MAX_SECONDS=840
# EXTENSION_HEARTBEAT_INTERVAL_SECONDS=60
# EXTENSION_HEARTBEAT_TIMEOUT_SECONDS=300
# EXTENSION_CONFIG_REFETCH_SECONDS=300
# EXTENSION_QUIET_HOURS_START=1
# EXTENSION_QUIET_HOURS_END=7
# EXTENSION_PEAK_HOURS_TZ=America/New_York
# EXTENSION_PEAK_HOURS_START=9
# EXTENSION_PEAK_HOURS_END=22
# EXTENSION_NO_JOBS_ALERT_MINUTES=30
```

---

## 11. What Stayed the Same

The following components are completely untouched. The extension channel plugs into them identically to how the browser channel did.

| Component | Location | Role |
|---|---|---|
| `DeduplicationGateway` | `src/pipeline/dedup.py` | Redis 7-day dedup; drops duplicate job IDs silently |
| `PipelineOrchestrator` | `src/pipeline/orchestrator.py` | Quick filter → LLM analysis → proposal generation |
| `TelegramNotifier` | `src/notifications/telegram.py` | Sends proposal alerts and watchdog alerts |
| `SafetyController` | `src/safety/controller.py` | Rate limiting, proposal throttling |
| `ChannelRegistry` | `src/channels/registry.py` | Lifecycle management (start/stop/list) |
| `DetectionChannel` | `src/channels/base.py` | Abstract base; `_emit()` is the handoff point |
| All database models | `src/models/` | Job, Proposal, ChannelConfig, SearchConfig, BrowserSession all unchanged |
| All dashboard API routes | `src/api/` | Channels, jobs, proposals, analytics, settings, search configs |
| All templates | `src/templates/` | Dashboard HTML unchanged |

The `BrowserSession` table still exists and is still written to by `_on_session_complete` — there just won't be any new rows because no sessions are running. Old session history is preserved.

---

## 12. What Was Deprecated

Everything under `src/channels/browser/` except `__init__.py` is now in `_archive/`. These files are **not deleted** — they're accessible via `git log`, readable for reference, and contain the JS selectors that were ported to `extractor.js`.

The `_archive/__init__.py` makes accidental re-importation impossible:

```python
raise ImportError("src.channels.browser._archive is not for runtime import")
```

If you ever need to refer back to the old session runner logic or the Cloudflare handling in `PageGuard`, the code is in `_archive/` and in git history.

---

## 13. Next Steps

Work through these in order. Each step has a clear done-condition.

### Step 1 — Generate and set the API token

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output. Open `.env`, replace `change-me-in-env` on the `EXTENSION_API_TOKEN` line with the generated value.

**Done when:** `.env` has a real token (not the placeholder).

---

### Step 2 — Enable the channel in the database

Run the seed script to create the `ChannelConfig` row:

```bash
python scripts/enable_extension_channel.py
```

This creates a row with `channel_id="extension_channel"`, `is_enabled=True` and (if it exists) sets `browser_channel.is_enabled=False` so the old channel doesn't try to start.

**Done when:** Script prints "extension_channel created and enabled" or "extension_channel re-enabled".

---

### Step 3 — Uninstall old browser automation packages

```bash
pip uninstall -y playwright patchright fake-useragent browser-cookie3
pip install -r requirements.txt
```

The second command is a no-op (nothing new to install) but confirms the requirements file is clean.

**Done when:** `pip list | grep -E "playwright|patchright|fake-useragent|browser-cookie3"` returns nothing.

---

### Step 4 — Start the backend

```bash
uvicorn src.main:app --reload
```

Watch the startup log. You should see:

```
INFO  src.channels.registry — Registered channel: extension_channel
INFO  src.channels.extension.watchdog — Extension watchdog scheduled (every 60s)
INFO  src.main — Auto-enabled channel: extension_channel
INFO  src.channels.extension.channel — ExtensionChannel registered (passive — extension is the actual source)
INFO  src.main — Up-take ready. Visit http://localhost:8000 for the dashboard.
```

**Done when:** Server starts without errors and those four log lines appear.

---

### Step 5 — Load the Chrome extension

1. Open `chrome://extensions/`
2. Toggle **Developer mode** (top-right corner)
3. Click **Load unpacked**
4. Select the `extension/` directory in this project
5. The extension appears in the list. Note the generated ID (looks like `abcdefghijklmnopqrstuvwxyz123456`)
6. Click the puzzle icon in the toolbar → find **Upwork Job Sentinel (Up-take)** → click **Options**
7. Set **Backend URL**: `http://localhost:8000`
8. Set **API Token**: paste the value from `EXTENSION_API_TOKEN` in `.env`
9. Click **Save**
10. Click **Test Connection**

**Done when:** Test Connection shows `OK — N searches configured`.

---

### Step 6 — Configure search URLs (if not done already)

The extension reads search URLs from the backend's `SearchConfig` table. If the table is empty, it falls back to `Best Matches`.

To add searches, use the existing dashboard at `http://localhost:8000/settings` or insert directly:

```sql
INSERT INTO search_configs (id, name, url, is_active, created_at)
VALUES (gen_random_uuid(), 'Python Django', 'https://www.upwork.com/nx/search/jobs?q=django+python&sort=recency', true, now());
```

**Done when:** Test Connection in the options page shows the search list you expect.

---

### Step 7 — Open an Upwork search tab and verify

1. In Chrome, open `https://www.upwork.com/nx/find-work/best-matches`
2. Confirm you are logged in (your avatar/name is visible)
3. Wait up to 30 seconds

**Expected backend log output:**
```
INFO  src.channels.extension.ingest_api — Extension batch: received=12 from https://www.upwork.com/... (ext v1.0.0)
```

**Expected service worker output** (check via `chrome://extensions/` → Inspect service worker):
```
[cs] Extracted 12 jobs (initial)
[bg] Next reload in 487s
```

**Done when:** Backend logs show a job batch with a non-zero `received` count.

---

### Step 8 — Verify end-to-end pipeline

Leave the system running for one full reload cycle (6–14 minutes). Watch for:

1. **Tab reloads** to a different search URL (if you have multiple configured)
2. **Second extraction batch** in backend logs
3. **Telegram alert** if any job passes the quick filter and LLM analysis

If no Telegram alerts after 2–3 cycles: check pipeline logs for filter rejections. The `min_opportunity_score` default is 55 — adjust in `.env` as needed.

**Done when:** At least one Telegram proposal alert received.

---

### Step 9 — Delete the old session files (optional cleanup)

If you didn't do this during the migration, delete the Patchright profile:

```bash
rm -rf sessions/chrome_profile/
rm -f sessions/upwork_session.json
```

These are no longer used by anything.

---

### Step 10 — Monitor for one week

Watch for these in Telegram:

| Alert | Action |
|---|---|
| 💤 Heartbeat Lost | Check Chrome is open and on an Upwork tab |
| 🔍 No Jobs in Peak | Check extension service worker is alive (open options page to revive it); check Upwork tab is logged in |
| 🔑 Session Expired | Log back into Upwork in Chrome |
| 🛡️ Cloudflare | Open the tab, click the checkbox |
| ⚙️ Selector Broken | Inspect Upwork DOM, update `extension/extractor.js` selectors |

If you see selector breakage, the fix is: open Chrome DevTools on an Upwork search page, inspect a job tile, find the new attribute or class, update the relevant selector in `extractor.js`, reload the extension.

---

### Future Improvements (not in scope for this migration)

- **Browser-side dedup**: track tile IDs in `chrome.storage.session` so the same page load doesn't re-POST unchanged tiles on every mutation event
- **Weighted search rotation**: use the `weight` field already present in `SearchConfigEntry` to bias the rotation toward higher-value searches
- **Job detail crawl**: when a high-scoring job is found, open the detail page in a background tab to extract `connectsRequired` and the full description, then close it
- **Extension auto-update**: currently requires manual "Load unpacked" each time `extractor.js` selectors change; a published Chrome Web Store version would auto-update
- **Multi-tab support**: claim and cycle multiple Upwork tabs for higher discovery rate without reducing intervals below 6 min
