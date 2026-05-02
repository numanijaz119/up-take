// ── Constants ──────────────────────────────────────────────────────────────────
const ALARM_TICK   = "uptake-tick";
const ALARM_HEALTH = "uptake-health";

const SK = {
    backendUrl: "backendUrl",
    apiToken:   "apiToken",
    settings:   "settings",
    tabState:   "tabState",
    seenJobs:   "seenJobs",   // extension-level dedup: jobId → timestamp
};

// Global settings — shared across all tabs (URL list, auto-open)
const DEFAULT_SETTINGS = {
    urls:         ["https://www.upwork.com/nx/find-work/best-matches"],
    autoOpenUrls: false,
};

// Per-tab defaults — each tab starts with these unless configured otherwise
const DEFAULT_TAB_SETTINGS = {
    interval: {
        mode:             "random",
        fixedSeconds:     600,
        randomMinSeconds: 360,
        randomMaxSeconds: 840,
    },
    quietHoursEnabled: false,
    quietHoursStart:   1,
    quietHoursEnd:     7,
};

// ── In-memory health state ─────────────────────────────────────────────────────
let backendOnline = null;   // null=unknown  true=ok  false=offline
let consecutiveFailures = 0;
const FAIL_THRESHOLD = 3;
let _lastHealthCheckAt = 0;
const HEALTH_CHECK_COOLDOWN_MS = 30_000; // don't re-check within 30s

// ── Storage helpers ────────────────────────────────────────────────────────────
function getStorage(keys) {
    return new Promise((r) => chrome.storage.local.get(keys, r));
}
function setStorage(obj) {
    return new Promise((r) => chrome.storage.local.set(obj, r));
}
async function getSettings() {
    const { settings } = await getStorage([SK.settings]);
    return Object.assign({}, DEFAULT_SETTINGS, settings || {});
}
async function getTabState() {
    const { tabState } = await getStorage([SK.tabState]);
    return tabState || {};
}
async function saveTabState(state) {
    return setStorage({ [SK.tabState]: state });
}
async function patchTab(tabId, patch) {
    const s = await getTabState();
    s[tabId] = Object.assign({}, s[tabId] || {}, patch);
    await saveTabState(s);
}

// Extract per-tab interval/quiet-hours settings, falling back to defaults.
function resolveTabSettings(ts) {
    return {
        interval:          ts.interval          || DEFAULT_TAB_SETTINGS.interval,
        quietHoursEnabled: ts.quietHoursEnabled ?? DEFAULT_TAB_SETTINGS.quietHoursEnabled,
        quietHoursStart:   ts.quietHoursStart   ?? DEFAULT_TAB_SETTINGS.quietHoursStart,
        quietHoursEnd:     ts.quietHoursEnd     ?? DEFAULT_TAB_SETTINGS.quietHoursEnd,
    };
}

// ── URL matching ───────────────────────────────────────────────────────────────
function feedBaseFor(url, urls) {
    if (!url) return null;
    return urls.find((u) => url.startsWith(u.split("*")[0])) ?? null;
}

// ── Backend client ─────────────────────────────────────────────────────────────
async function backendFetch(path, init = {}) {
    const { backendUrl, apiToken } = await getStorage([SK.backendUrl, SK.apiToken]);
    if (!backendUrl || !apiToken) throw new Error("Backend not configured");
    const url = backendUrl.replace(/\/$/, "") + path;
    return fetch(url, {
        ...init,
        headers: {
            "Content-Type": "application/json",
            "X-Extension-Token": apiToken,
            ...(init.headers || {}),
        },
    });
}

// ── Backend health check ───────────────────────────────────────────────────────
// Skips the HTTP call if a check already ran within the cooldown window.
// This prevents bursts of heartbeats when multiple tabs are started in quick succession.
async function checkBackendHealth(force = false) {
    const now = Date.now();
    if (!force && now - _lastHealthCheckAt < HEALTH_CHECK_COOLDOWN_MS) return backendOnline;
    _lastHealthCheckAt = now;
    try {
        const { backendUrl, apiToken } = await getStorage([SK.backendUrl, SK.apiToken]);
        if (!backendUrl || !apiToken) {
            backendOnline = false;
            return false;
        }
        const manifest = chrome.runtime.getManifest();
        const state    = await getTabState();
        const tabs     = [];
        for (const id of Object.keys(state).map(Number)) {
            const tab = await safeGetTab(id);
            if (tab) tabs.push({ tab_id: id, url: tab.url, last_extraction_at: null, jobs_seen: 0 });
        }
        const res = await backendFetch("/api/v1/extension/heartbeat", {
            method: "POST",
            body:   JSON.stringify({ extension_version: manifest.version, tabs, last_job_at: null }),
            signal: AbortSignal.timeout(8000),
        });
        if (res.ok || res.status === 401) {
            backendOnline       = true;
            consecutiveFailures = 0;
        } else {
            throw new Error(`HTTP ${res.status}`);
        }
    } catch (e) {
        consecutiveFailures++;
        if (consecutiveFailures >= FAIL_THRESHOLD) backendOnline = false;
        console.warn("[bg] health check failed:", e.message || e);
    }
    await broadcastState();
    return backendOnline;
}

// ── Scheduling helpers ─────────────────────────────────────────────────────────
function pickDelay(interval) {
    if (interval.mode === "fixed") return Math.max(5, interval.fixedSeconds);
    const min = Math.max(5, interval.randomMinSeconds);
    const max = Math.max(min, interval.randomMaxSeconds);
    return Math.round(min + Math.random() * (max - min));
}

function isQuietHour(tabCfg) {
    if (!tabCfg.quietHoursEnabled) return false;
    const h = new Date().getHours();
    const a = tabCfg.quietHoursStart ?? 1;
    const b = tabCfg.quietHoursEnd   ?? 7;
    if (a === b) return false;
    return a < b ? (h >= a && h < b) : (h >= a || h < b);
}

async function safeGetTab(tabId) {
    try { return await chrome.tabs.get(tabId); } catch { return null; }
}

// ── Badge ──────────────────────────────────────────────────────────────────────
function fmtBadge(seconds) {
    const s  = Math.max(0, Math.round(seconds));
    const m  = Math.floor(s / 60);
    const ss = s % 60;
    return `${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

async function refreshBadge(tabId, ts) {
    try {
        if (!ts || !ts.running) {
            await chrome.action.setBadgeText({ tabId, text: "" });
            return;
        }
        if (backendOnline === false) {
            await chrome.action.setBadgeText({ tabId, text: "ERR" });
            await chrome.action.setBadgeBackgroundColor({ tabId, color: "#cc0000" });
            return;
        }
        const remaining = ts.nextReloadAt
            ? Math.max(0, (ts.nextReloadAt - Date.now()) / 1000)
            : 0;
        await chrome.action.setBadgeText({ tabId, text: fmtBadge(remaining) });
        await chrome.action.setBadgeBackgroundColor({ tabId, color: "#14a800" });
    } catch (_) {}
}

// ── Per-tab reload ─────────────────────────────────────────────────────────────
async function reloadTab(tabId) {
    const ts = (await getTabState())[tabId];
    if (!ts || !ts.running) return;

    const cfg = resolveTabSettings(ts);
    if (!backendOnline)    { await scheduleTab(tabId); return; }
    if (isQuietHour(cfg))  { await scheduleTab(tabId); return; }

    const tab = await safeGetTab(tabId);
    if (!tab) { await removeTab(tabId); return; }

    try {
        await chrome.tabs.reload(tabId);
        await patchTab(tabId, { lastReloadAt: Date.now() });
    } catch (e) {
        console.warn("[bg] Reload failed:", e.message);
    }
    await scheduleTab(tabId);
}

// Schedule uses the tab's OWN stored interval — each tab picks its own delay.
async function scheduleTab(tabId) {
    const ts  = (await getTabState())[tabId] || {};
    const cfg = resolveTabSettings(ts);
    const delay = pickDelay(cfg.interval);
    await patchTab(tabId, { nextReloadAt: Date.now() + delay * 1000, running: true });
    await refreshBadge(tabId, (await getTabState())[tabId]);
}

async function stopTab(tabId) {
    await patchTab(tabId, { running: false, nextReloadAt: null });
    try { await chrome.action.setBadgeText({ tabId, text: "" }); } catch (_) {}
    // Tell content script to stop: disconnect observer, clear running flag.
    chrome.tabs.sendMessage(tabId, { type: "STOP_EXTRACT" }).catch(() => {});
}

async function removeTab(tabId) {
    const s = await getTabState();
    delete s[tabId];
    await saveTabState(s);
    try { await chrome.action.setBadgeText({ tabId, text: "" }); } catch (_) {}
}

// ── Tick (1 s while SW alive; ≤30 s via alarm in production) ──────────────────
async function tick() {
    const tabState = await getTabState();
    const now      = Date.now();

    for (const [key, ts] of Object.entries(tabState)) {
        const tabId = Number(key);
        const tab   = await safeGetTab(tabId);
        if (!tab) { await removeTab(tabId); continue; }
        await refreshBadge(tabId, ts);
        if (ts.running && ts.nextReloadAt && now >= ts.nextReloadAt) {
            await reloadTab(tabId);
        }
    }
}

let _tickTimer = null;
function startTick() {
    if (_tickTimer) return;
    _tickTimer = setInterval(() => tick().catch((e) => console.warn("[bg] tick:", e)), 1000);
}

// ── Auto-open configured URLs ──────────────────────────────────────────────────
async function autoOpenUrls(settings) {
    if (!settings.autoOpenUrls) return;
    const allTabs = await chrome.tabs.query({});
    for (const urlConfig of settings.urls) {
        const base = urlConfig.split("*")[0];
        const alreadyOpen = allTabs.some((t) => t.url && t.url.startsWith(base));
        if (!alreadyOpen) {
            try {
                await chrome.tabs.create({ url: base, active: false });
                console.log("[bg] Auto-opened:", base);
            } catch (e) {
                console.warn("[bg] Auto-open failed:", e.message);
            }
        }
    }
}

// ── Tab lifecycle ──────────────────────────────────────────────────────────────
// When a tab navigates to an eligible URL, register it (preserve existing per-tab
// settings). If the tab was already running (e.g. after a scheduled reload), tell
// the freshly-injected content script to start extraction. New tabs stay idle until
// the user explicitly clicks Start.
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
    if (changeInfo.status !== "complete" || !tab.url) return;
    const settings = await getSettings();
    const feedBase = feedBaseFor(tab.url, settings.urls);
    if (!feedBase) return;
    await patchTab(tabId, { url: tab.url, feedBase });
    const ts = (await getTabState())[tabId];
    if (ts?.running) {
        chrome.tabs.sendMessage(tabId, { type: "TRIGGER_EXTRACT" }).catch(() => {});
    }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
    await removeTab(tabId);
});

// ── Broadcast state change to popup ───────────────────────────────────────────
// Popup may not be open — sendMessage returns a rejected Promise in that case,
// so we must catch the rejection (a try/catch on the call site does not help
// because the error is thrown asynchronously by the Promise, not synchronously).
function broadcastState() {
    chrome.runtime.sendMessage({ type: "_STATE_CHANGED" }).catch(() => {});
}

// ── Message API ────────────────────────────────────────────────────────────────
async function handle(msg, sender) {
    switch (msg.type) {

        case "GET_STATE": {
            const settings  = await getSettings();
            const tabState  = await getTabState();
            const [activeTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
            return {
                ok: true,
                settings,
                tabState,
                backendOnline,
                activeTab: activeTab
                    ? { id: activeTab.id, url: activeTab.url, title: activeTab.title }
                    : null,
            };
        }

        // Start or stop a single specific tab — no effect on any other tab.
        case "SET_TAB_ENABLED": {
            const { tabId, enabled } = msg;
            if (enabled) {
                const tab = await safeGetTab(tabId);
                if (tab) await patchTab(tabId, { url: tab.url });
                await scheduleTab(tabId);
                // Immediately extract jobs from the current page without waiting
                // for the first reload cycle — content script is already loaded.
                chrome.tabs.sendMessage(tabId, { type: "TRIGGER_EXTRACT" }).catch(() => {});
                await checkBackendHealth();
            } else {
                await stopTab(tabId);
            }
            await broadcastState();
            return { ok: true };
        }

        // Persist per-tab interval / quiet-hours settings without starting.
        case "SAVE_TAB_SETTINGS": {
            const { tabId, interval, quietHoursEnabled, quietHoursStart, quietHoursEnd } = msg;
            await patchTab(tabId, { interval, quietHoursEnabled, quietHoursStart, quietHoursEnd });
            // Re-schedule if already running so the new interval takes effect immediately.
            const ts = (await getTabState())[tabId];
            if (ts?.running) await scheduleTab(tabId);
            await broadcastState();
            return { ok: true };
        }

        // Save global settings (URL list, auto-open).
        case "SAVE_SETTINGS": {
            await setStorage({ [SK.settings]: msg.settings });
            if (msg.settings.autoOpenUrls) await autoOpenUrls(msg.settings);
            await broadcastState();
            return { ok: true };
        }

        case "STOP_TAB": {
            await stopTab(msg.tabId);
            await broadcastState();
            return { ok: true };
        }

        case "FORCE_RELOAD_TAB": {
            const tab = await safeGetTab(msg.tabId);
            if (tab) await chrome.tabs.reload(msg.tabId);
            await scheduleTab(msg.tabId);
            return { ok: true };
        }

        case "EXTRACTED_JOBS": {
            if (backendOnline === false) return { ok: false, error: "Backend offline" };

            const SEEN_TTL = 48 * 60 * 60 * 1000; // 48 h in ms
            const now      = Date.now();

            // Load persisted seen-job map { jobId: submittedAtMs }
            const stored   = await getStorage([SK.seenJobs]);
            const seenJobs = stored[SK.seenJobs] || {};

            // Only keep jobs the backend hasn't confirmed receiving yet
            const allJobs  = msg.jobs || [];
            const newJobs  = allJobs.filter(j => j.id && !seenJobs[j.id]);

            if (newJobs.length === 0) {
                return { ok: true, new: 0, skipped: allJobs.length };
            }

            try {
                const manifest = chrome.runtime.getManifest();
                const res = await backendFetch("/api/v1/extension/jobs", {
                    method: "POST",
                    body:   JSON.stringify({
                        jobs:              newJobs,
                        tab_url:           sender.tab?.url || "unknown",
                        tab_id:            sender.tab?.id  || null,
                        extension_version: manifest.version,
                    }),
                });

                // Only mark as seen when backend confirmed — if backend was down
                // during this call, jobs stay unseen and will be retried next cycle.
                if (res.ok) {
                    for (const job of newJobs) seenJobs[job.id] = now;
                    // Prune entries older than TTL to keep storage small
                    for (const id of Object.keys(seenJobs)) {
                        if (now - seenJobs[id] > SEEN_TTL) delete seenJobs[id];
                    }
                    await setStorage({ [SK.seenJobs]: seenJobs });
                }

                return { ok: res.ok, status: res.status, new: newJobs.length, skipped: allJobs.length - newJobs.length };
            } catch (e) {
                return { ok: false, error: e.message };
            }
        }

        case "EVENT": {
            if (backendOnline === false) return { ok: true };
            try {
                await backendFetch("/api/v1/extension/event", {
                    method: "POST",
                    body:   JSON.stringify({
                        kind:        msg.kind,
                        url:         sender.tab?.url || "unknown",
                        tab_id:      sender.tab?.id  || null,
                        detail:      msg.detail || null,
                        occurred_at: new Date().toISOString(),
                    }),
                });
            } catch (_) {}
            return { ok: true };
        }

        default:
            return { ok: false, error: "unknown type" };
    }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    handle(msg, sender).then(sendResponse).catch((e) =>
        sendResponse({ ok: false, error: e.message })
    );
    return true;
});

// ── Alarms ─────────────────────────────────────────────────────────────────────
chrome.alarms.onAlarm.addListener(async (alarm) => {
    if (alarm.name === ALARM_TICK)   { await tick(); startTick(); }
    if (alarm.name === ALARM_HEALTH) { await checkBackendHealth(true); }  // always fire on schedule
});

// ── Bootstrap ──────────────────────────────────────────────────────────────────
async function bootstrap() {
    chrome.alarms.create(ALARM_TICK,   { periodInMinutes: 1 / 60 });
    chrome.alarms.create(ALARM_HEALTH, { periodInMinutes: 1 });
    startTick();
    await checkBackendHealth();
    const settings = await getSettings();
    if (settings.autoOpenUrls) await autoOpenUrls(settings);
    const state = await getTabState();
    for (const [id, ts] of Object.entries(state)) {
        const tab = await safeGetTab(Number(id));
        if (!tab) await removeTab(Number(id));
        else      await refreshBadge(Number(id), ts);
    }
}

chrome.runtime.onInstalled.addListener(async () => {
    const { settings } = await getStorage([SK.settings]);
    if (!settings) await setStorage({ [SK.settings]: DEFAULT_SETTINGS });
    await bootstrap();
});

chrome.runtime.onStartup.addListener(bootstrap);
bootstrap().catch((e) => console.warn("[bg] bootstrap:", e));
