// ── Constants ──────────────────────────────────────────────────────────────────
const ALARM_RELOAD = "reload-managed-tab";
const ALARM_HEARTBEAT = "heartbeat";
const ALARM_CONFIG_REFETCH = "config-refetch";
const STORAGE_KEYS = {
    backendUrl: "backendUrl",
    apiToken: "apiToken",
    config: "config",
    managedTabId: "managedTabId",
    rotationIndex: "rotationIndex",
    lastReloadAt: "lastReloadAt",
};

const DEFAULT_CONFIG = {
    searches: [{ label: "Best Matches", url: "https://www.upwork.com/nx/find-work/best-matches", weight: 2.0 }],
    reload_min_seconds: 360,
    reload_max_seconds: 840,
    quiet_hours_start: 1,
    quiet_hours_end: 7,
    heartbeat_interval_seconds: 60,
    config_refetch_interval_seconds: 300,
};

// ── Storage helpers ────────────────────────────────────────────────────────────
async function getStorage(keys) {
    return new Promise((res) => chrome.storage.local.get(keys, res));
}
async function setStorage(obj) {
    return new Promise((res) => chrome.storage.local.set(obj, res));
}
async function getConfig() {
    const { config } = await getStorage([STORAGE_KEYS.config]);
    return config || DEFAULT_CONFIG;
}

// ── Backend client ─────────────────────────────────────────────────────────────
async function backendFetch(path, init = {}) {
    const { backendUrl, apiToken } = await getStorage([STORAGE_KEYS.backendUrl, STORAGE_KEYS.apiToken]);
    if (!backendUrl || !apiToken) throw new Error("Backend URL or token not configured");
    const url = `${backendUrl.replace(/\/$/, "")}${path}`;
    const headers = {
        "Content-Type": "application/json",
        "X-Extension-Token": apiToken,
        ...(init.headers || {}),
    };
    return fetch(url, { ...init, headers });
}

// ── Reload logic ───────────────────────────────────────────────────────────────
function jitteredDelaySeconds(min, max) {
    return min + Math.random() * (max - min);
}

function isQuietHour(start, end) {
    const h = new Date().getHours();
    if (start === end) return false;
    if (start < end) return h >= start && h < end;
    return h >= start || h < end;
}

async function pickNextSearchUrl() {
    const config = await getConfig();
    const searches = config.searches;
    if (!searches.length) return null;
    let { rotationIndex } = await getStorage([STORAGE_KEYS.rotationIndex]);
    rotationIndex = (rotationIndex ?? -1) + 1;
    if (rotationIndex >= searches.length) rotationIndex = 0;
    await setStorage({ [STORAGE_KEYS.rotationIndex]: rotationIndex });
    return searches[rotationIndex].url;
}

async function scheduleNextReload() {
    const config = await getConfig();
    const delaySeconds = jitteredDelaySeconds(config.reload_min_seconds, config.reload_max_seconds);
    chrome.alarms.create(ALARM_RELOAD, { delayInMinutes: delaySeconds / 60 });
    console.log(`[bg] Next reload in ${Math.round(delaySeconds)}s`);
}

async function reloadManagedTab() {
    const config = await getConfig();
    if (isQuietHour(config.quiet_hours_start, config.quiet_hours_end)) {
        console.log("[bg] Quiet hours — skipping reload");
        await scheduleNextReload();
        return;
    }
    const { managedTabId } = await getStorage([STORAGE_KEYS.managedTabId]);
    if (!managedTabId) {
        console.log("[bg] No managed tab — skipping");
        await scheduleNextReload();
        return;
    }
    const url = await pickNextSearchUrl();
    if (!url) {
        console.log("[bg] No search URLs configured");
        await scheduleNextReload();
        return;
    }
    try {
        await chrome.tabs.update(managedTabId, { url });
        await setStorage({ [STORAGE_KEYS.lastReloadAt]: new Date().toISOString() });
        console.log(`[bg] Tab ${managedTabId} → ${url}`);
    } catch (e) {
        console.warn("[bg] Tab update failed (tab may be closed):", e);
        await setStorage({ [STORAGE_KEYS.managedTabId]: null });
    }
    await scheduleNextReload();
}

// ── Heartbeat ──────────────────────────────────────────────────────────────────
async function sendHeartbeat() {
    try {
        const { managedTabId } = await getStorage([STORAGE_KEYS.managedTabId]);
        let tabs = [];
        if (managedTabId) {
            try {
                const tab = await chrome.tabs.get(managedTabId);
                tabs = [{ tab_id: tab.id, url: tab.url, last_extraction_at: null, jobs_seen: 0 }];
            } catch { /* tab gone */ }
        }
        const manifest = chrome.runtime.getManifest();
        const res = await backendFetch("/api/v1/extension/heartbeat", {
            method: "POST",
            body: JSON.stringify({
                extension_version: manifest.version,
                tabs,
                last_job_at: null,
            }),
        });
        if (!res.ok) console.warn("[bg] Heartbeat HTTP", res.status);
    } catch (e) {
        console.warn("[bg] Heartbeat failed:", e.message);
    }
}

// ── Config refetch ─────────────────────────────────────────────────────────────
async function refetchConfig() {
    try {
        const res = await backendFetch("/api/v1/extension/config", { method: "GET" });
        if (!res.ok) return;
        const config = await res.json();
        await setStorage({ [STORAGE_KEYS.config]: config });
        console.log("[bg] Config refreshed:", config.searches.length, "searches");
    } catch (e) {
        console.warn("[bg] Config refetch failed:", e.message);
    }
}

// ── Tab claiming ───────────────────────────────────────────────────────────────
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
    if (changeInfo.status !== "complete") return;
    if (!tab.url) return;
    if (!/^https:\/\/www\.upwork\.com\/nx\/(find-work|search\/jobs)/.test(tab.url)) return;
    const { managedTabId } = await getStorage([STORAGE_KEYS.managedTabId]);
    if (!managedTabId) {
        await setStorage({ [STORAGE_KEYS.managedTabId]: tabId });
        console.log(`[bg] Claimed tab ${tabId} as managed tab`);
    }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
    const { managedTabId } = await getStorage([STORAGE_KEYS.managedTabId]);
    if (tabId === managedTabId) {
        await setStorage({ [STORAGE_KEYS.managedTabId]: null });
        console.log("[bg] Managed tab closed");
    }
});

// ── Messages from content script ───────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    (async () => {
        try {
            if (msg.type === "EXTRACTED_JOBS") {
                const manifest = chrome.runtime.getManifest();
                const res = await backendFetch("/api/v1/extension/jobs", {
                    method: "POST",
                    body: JSON.stringify({
                        jobs: msg.jobs,
                        tab_url: sender.tab?.url || "unknown",
                        extension_version: manifest.version,
                    }),
                });
                sendResponse({ ok: res.ok, status: res.status });
            } else if (msg.type === "EVENT") {
                await backendFetch("/api/v1/extension/event", {
                    method: "POST",
                    body: JSON.stringify({
                        kind: msg.kind,
                        url: sender.tab?.url || "unknown",
                        detail: msg.detail || null,
                        occurred_at: new Date().toISOString(),
                    }),
                });
                sendResponse({ ok: true });
            } else {
                sendResponse({ ok: false, error: "unknown message type" });
            }
        } catch (e) {
            console.error("[bg] Message handler error:", e);
            sendResponse({ ok: false, error: e.message });
        }
    })();
    return true;
});

// ── Alarm handlers ─────────────────────────────────────────────────────────────
chrome.alarms.onAlarm.addListener(async (alarm) => {
    if (alarm.name === ALARM_RELOAD) await reloadManagedTab();
    else if (alarm.name === ALARM_HEARTBEAT) await sendHeartbeat();
    else if (alarm.name === ALARM_CONFIG_REFETCH) await refetchConfig();
});

// ── Bootstrap ──────────────────────────────────────────────────────────────────
async function bootstrap() {
    await refetchConfig();
    const config = await getConfig();
    chrome.alarms.create(ALARM_HEARTBEAT, {
        periodInMinutes: config.heartbeat_interval_seconds / 60,
    });
    chrome.alarms.create(ALARM_CONFIG_REFETCH, {
        periodInMinutes: config.config_refetch_interval_seconds / 60,
    });
    await scheduleNextReload();
}

chrome.runtime.onInstalled.addListener(async () => {
    await bootstrap();
    console.log("[bg] Extension installed and bootstrapped");
});

chrome.runtime.onStartup.addListener(async () => {
    await bootstrap();
    console.log("[bg] Extension started");
});
