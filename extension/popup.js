// ── Helpers ────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

let state         = null;
let currentTab    = null;   // set from popup context — reliable unlike SW's lastFocusedWindow
let countdownTimer = null;

const DEFAULT_TAB_SETTINGS = {
    interval:          { mode: "random", fixedSeconds: 600, randomMinSeconds: 360, randomMaxSeconds: 840 },
    quietHoursEnabled: false,
    quietHoursStart:   1,
    quietHoursEnd:     7,
};

function send(msg) {
    return new Promise((resolve) =>
        chrome.runtime.sendMessage(msg, (r) => resolve(r || { ok: false }))
    );
}

// ── Tab navigation ─────────────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        $("tab-" + btn.dataset.tab).classList.add("active");
    });
});

// ── Per-tab state helpers ──────────────────────────────────────────────────────
function currentTabEntry() {
    if (!state || !currentTab) return null;
    return state.tabState?.[currentTab.id] || null;
}

// Returns current tab's effective settings, falling back to defaults.
function currentTabSettings() {
    const e = currentTabEntry();
    return {
        interval:          e?.interval          || DEFAULT_TAB_SETTINGS.interval,
        quietHoursEnabled: e?.quietHoursEnabled ?? DEFAULT_TAB_SETTINGS.quietHoursEnabled,
        quietHoursStart:   e?.quietHoursStart   ?? DEFAULT_TAB_SETTINGS.quietHoursStart,
        quietHoursEnd:     e?.quietHoursEnd     ?? DEFAULT_TAB_SETTINGS.quietHoursEnd,
        running:           e?.running           || false,
    };
}

function isCurrentTabEligible() {
    if (!state || !currentTab?.url) return false;
    return state.settings.urls.some((u) => currentTab.url.startsWith(u.split("*")[0]));
}

// ── Fetch state from background ────────────────────────────────────────────────
async function loadState() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    currentTab = tab || null;

    state = await send({ type: "GET_STATE" });
    if (!state || !state.ok) return;

    // Popup's active-tab determination overrides the SW's (which uses lastFocusedWindow).
    if (currentTab) {
        state.activeTab = { id: currentTab.id, url: currentTab.url, title: currentTab.title };
    }

    renderAll();
}

// ── Render everything ──────────────────────────────────────────────────────────
function renderAll() {
    if (!state || !state.ok) return;
    const { settings, tabState, backendOnline } = state;
    const ts       = currentTabSettings();
    const eligible = isCurrentTabEligible();

    // Version
    $("version").textContent = chrome.runtime.getManifest().version;

    // Header sub-line: show current tab URL
    if (currentTab?.url) {
        try {
            const u = new URL(currentTab.url);
            $("headerSub").textContent = u.hostname + u.pathname.slice(0, 40);
        } catch { $("headerSub").textContent = currentTab.url.slice(0, 50); }
    } else {
        $("headerSub").textContent = "No active tab";
    }

    // Toggle button — controls ONLY the current tab
    const btn = $("toggleBtn");
    if (!eligible) {
        btn.className = "toggle-btn disabled";
        btn.querySelector(".toggle-icon").textContent = "⏵";
        btn.querySelector(".toggle-label").textContent = "Start";
        btn.disabled = true;
    } else {
        btn.disabled  = false;
        btn.className = "toggle-btn " + (ts.running ? "on" : "off");
        btn.querySelector(".toggle-icon").textContent  = ts.running ? "⏹" : "⏵";
        btn.querySelector(".toggle-label").textContent = ts.running ? "Stop" : "Start";
    }

    // Per-tab indicator in the Interval tab heading
    const ind = $("tabIndicator");
    if (ind) {
        if (eligible && currentTab) {
            ind.textContent = `· Tab ${currentTab.id}`;
            ind.style.display = "";
        } else {
            ind.style.display = "none";
        }
    }

    // Not-eligible hint
    $("notEligibleHint").classList.toggle("hidden", eligible);

    // Interval form — shows this tab's own settings
    renderIntervalForm(ts.interval);
    $("quietEnabled").checked = !!ts.quietHoursEnabled;
    $("quietStart").value     = ts.quietHoursStart ?? 1;
    $("quietEnd").value       = ts.quietHoursEnd   ?? 7;

    // autoOpen is global
    $("autoOpen").checked = !!settings.autoOpenUrls;

    // URLs tab
    renderUrlList(settings.urls);

    // Status tab
    renderStatus(backendOnline, tabState);
}

// ── Render interval form ───────────────────────────────────────────────────────
function renderIntervalForm(iv) {
    const isRandom = iv.mode === "random";
    const fixedRadio  = document.querySelector('input[name="iv"][value="fixed"]');
    const randomRadio = document.querySelector('input[name="iv"][value="random"]');

    if (isRandom) { if (randomRadio) randomRadio.checked = true; }
    else          { if (fixedRadio)  fixedRadio.checked  = true; }

    $("randomRow").classList.toggle("visible", isRandom);
    $("fixedRow").classList.toggle("visible", !isRandom);

    $("ivSec").value = iv.fixedSeconds;
    $("rMin").value  = iv.randomMinSeconds;
    $("rMax").value  = iv.randomMaxSeconds;
}

// ── Render URL list ────────────────────────────────────────────────────────────
function renderUrlList(urls) {
    const list = $("urlList");
    list.innerHTML = "";
    if (!urls.length) {
        list.innerHTML = '<li class="hint">No URLs configured. Click "+ Add".</li>';
        return;
    }
    for (const url of urls) {
        const li = document.createElement("li");
        li.className = "url-item";
        li.innerHTML = `
            <span class="dot"></span>
            <span title="${esc(url)}">${esc(url)}</span>
            <button class="rm-btn" title="Remove">✕</button>
        `;
        li.querySelector(".rm-btn").addEventListener("click", () => {
            state.settings.urls = state.settings.urls.filter((u) => u !== url);
            saveGlobalSettings();
        });
        list.appendChild(li);
    }
}

// ── Render status tab ──────────────────────────────────────────────────────────
function renderStatus(backendOnline, tabState) {
    const badge = $("backendBadge");
    if (backendOnline === true)       { badge.className = "badge online";  badge.textContent = "Online"; }
    else if (backendOnline === false) { badge.className = "badge offline"; badge.textContent = "Offline"; }
    else                             { badge.className = "badge unknown"; badge.textContent = "Checking…"; }

    chrome.storage.local.get(["backendUrl"], ({ backendUrl }) => {
        $("backendUrl").textContent = backendUrl || "";
    });

    const entries = Object.entries(tabState || {}).filter(([, ts]) => ts.running);
    const list    = $("activeTabsList");
    list.innerHTML = "";
    $("noTabsMsg").classList.toggle("hidden", entries.length > 0);

    for (const [idStr, ts] of entries) {
        const tabId     = Number(idStr);
        const isCurrent = currentTab && tabId === currentTab.id;
        const remaining = ts.nextReloadAt
            ? Math.max(0, Math.round((ts.nextReloadAt - Date.now()) / 1000))
            : 0;
        const modeTag   = ts.interval?.mode === "random" ? " ~" : "";
        const li = document.createElement("li");
        li.className = "active-tab-item" + (isCurrent ? " current" : "");
        li.innerHTML = `
            <span class="tab-url" title="${esc(ts.url || "")}">${isCurrent ? "▶ " : ""}${esc(shortUrl(ts.url || ""))}</span>
            <span class="tab-mode">${modeTag}</span>
            <span class="countdown" data-tabid="${tabId}">${fmtTime(remaining)}</span>
            <button class="stop-small" data-tabid="${tabId}">Stop</button>
        `;
        li.querySelector(".stop-small").addEventListener("click", async (e) => {
            await send({ type: "STOP_TAB", tabId: Number(e.target.dataset.tabid) });
            await loadState();
        });
        list.appendChild(li);
    }
}

// ── Live countdown ─────────────────────────────────────────────────────────────
function startCountdown() {
    if (countdownTimer) clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
        if (!state) return;
        for (const [idStr, ts] of Object.entries(state.tabState || {})) {
            if (!ts.running || !ts.nextReloadAt) continue;
            const remaining = Math.max(0, Math.round((ts.nextReloadAt - Date.now()) / 1000));
            const el = document.querySelector(`.countdown[data-tabid="${idStr}"]`);
            if (el) el.textContent = fmtTime(remaining);
            if (remaining === 0) loadState();
        }
    }, 1000);
}

// ── Format helpers ─────────────────────────────────────────────────────────────
function fmtTime(s) {
    s = Math.max(0, Math.round(s));
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
function shortUrl(url) {
    try {
        const u = new URL(url);
        return (u.pathname + u.search).slice(0, 48) || u.hostname;
    } catch { return url.slice(0, 48); }
}
function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
}

// ── Read interval from form ────────────────────────────────────────────────────
function readInterval() {
    const sel  = document.querySelector('input[name="iv"]:checked');
    const mode = sel?.value || "random";
    const fixedSeconds     = Math.max(1, parseInt($("ivSec").value, 10) || 600);
    const randomMinSeconds = Math.max(1, parseInt($("rMin").value,  10) || 360);
    const randomMaxSeconds = Math.max(randomMinSeconds, parseInt($("rMax").value, 10) || 840);
    return { mode, fixedSeconds, randomMinSeconds, randomMaxSeconds };
}

// ── Save per-tab settings (interval + quiet hours) ─────────────────────────────
async function saveTabSettings() {
    if (!state || !currentTab) return;
    await send({
        type:              "SAVE_TAB_SETTINGS",
        tabId:             currentTab.id,
        interval:          readInterval(),
        quietHoursEnabled: $("quietEnabled").checked,
        quietHoursStart:   parseInt($("quietStart").value, 10) || 0,
        quietHoursEnd:     parseInt($("quietEnd").value,   10) || 0,
    });
    // Don't call loadState() here — avoid re-render loops on every keystroke.
}

// ── Save global settings (URL list, auto-open) ─────────────────────────────────
async function saveGlobalSettings() {
    if (!state) return;
    await send({
        type:     "SAVE_SETTINGS",
        settings: { ...state.settings, autoOpenUrls: $("autoOpen").checked },
    });
    await loadState();
}

// ── Start / Stop toggle — acts ONLY on the current tab ────────────────────────
$("toggleBtn").addEventListener("click", async () => {
    if (!state || !currentTab || !isCurrentTabEligible()) return;
    const ts         = currentTabSettings();
    const nowEnabled = !ts.running;
    // Save latest interval/quiet-hours into this tab's state before starting.
    await saveTabSettings();
    await send({ type: "SET_TAB_ENABLED", tabId: currentTab.id, enabled: nowEnabled });
    await loadState();
});

// ── Interval form auto-save ────────────────────────────────────────────────────
document.querySelectorAll('input[name="iv"]').forEach((r) => {
    r.addEventListener("change", () => {
        const v = document.querySelector('input[name="iv"]:checked')?.value;
        $("randomRow").classList.toggle("visible", v === "random");
        $("fixedRow").classList.toggle("visible",  v === "fixed");
        saveTabSettings();
    });
});

["ivSec", "rMin", "rMax"].forEach((id) => {
    $(id)?.addEventListener("change", saveTabSettings);
});

$("quietEnabled").addEventListener("change", saveTabSettings);
["quietStart", "quietEnd"].forEach((id) => $(id)?.addEventListener("change", saveTabSettings));

$("autoOpen").addEventListener("change", saveGlobalSettings);

// ── URL tab ────────────────────────────────────────────────────────────────────
$("addUrlBtn").addEventListener("click", () => {
    $("addUrlForm").classList.remove("hidden");
    $("newUrlInput").value = "";
    $("newUrlInput").focus();
});
$("cancelUrlBtn").addEventListener("click", () => $("addUrlForm").classList.add("hidden"));

$("confirmUrlBtn").addEventListener("click", () => {
    const url = $("newUrlInput").value.trim();
    if (!url) return;
    try { new URL(url); } catch { alert("Please enter a valid URL."); return; }
    if (!state.settings.urls.includes(url)) state.settings.urls.push(url);
    $("addUrlForm").classList.add("hidden");
    saveGlobalSettings();
});

$("newUrlInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter")  $("confirmUrlBtn").click();
    if (e.key === "Escape") $("cancelUrlBtn").click();
});

// ── Backend settings ───────────────────────────────────────────────────────────
async function loadBackend() {
    const d = await chrome.storage.local.get(["backendUrl", "apiToken"]);
    $("backendUrlInput").value = d.backendUrl || "http://localhost:8000";
    $("apiTokenInput").value   = d.apiToken   || "";
}

$("saveBackendBtn").addEventListener("click", async () => {
    await chrome.storage.local.set({
        backendUrl: $("backendUrlInput").value.trim(),
        apiToken:   $("apiTokenInput").value.trim(),
    });
    $("backendTestMsg").textContent = "Saved.";
    setTimeout(() => { $("backendTestMsg").textContent = ""; }, 1500);
});

$("testBackendBtn").addEventListener("click", async () => {
    $("backendTestMsg").textContent = "Testing…";
    try {
        const url = $("backendUrlInput").value.trim().replace(/\/$/, "");
        const res = await fetch(`${url}/api/v1/extension/heartbeat`, {
            method:  "POST",
            headers: { "Content-Type": "application/json", "X-Extension-Token": $("apiTokenInput").value.trim() },
            body:    JSON.stringify({ extension_version: "1.0.0", tabs: [], last_job_at: null }),
            signal:  AbortSignal.timeout(6000),
        });
        $("backendTestMsg").textContent = (res.ok || res.status === 401)
            ? `Connected (HTTP ${res.status})`
            : `HTTP ${res.status}`;
    } catch (e) {
        $("backendTestMsg").textContent = "Failed: " + e.message;
    }
});

// ── Live refresh on background state changes ───────────────────────────────────
chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "_STATE_CHANGED") loadState();
});

// ── Boot ───────────────────────────────────────────────────────────────────────
(async function init() {
    await loadBackend();
    await loadState();
    startCountdown();
})();

window.addEventListener("unload", () => {
    if (countdownTimer) clearInterval(countdownTimer);
});
