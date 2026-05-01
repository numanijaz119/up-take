const $ = (id) => document.getElementById(id);

async function load() {
    const data = await chrome.storage.local.get([
        "backendUrl", "apiToken", "config", "managedTabId", "lastReloadAt"
    ]);
    $("backendUrl").value = data.backendUrl || "http://localhost:8000";
    $("apiToken").value = data.apiToken || "";
    $("configDump").textContent = JSON.stringify(data.config || {}, null, 2);
    $("managedTab").textContent = data.managedTabId ?? "none";
    $("lastReload").textContent = data.lastReloadAt ?? "never";
}

$("save").onclick = async () => {
    await chrome.storage.local.set({
        backendUrl: $("backendUrl").value.trim(),
        apiToken: $("apiToken").value.trim(),
    });
    $("status").textContent = "Saved.";
};

$("test").onclick = async () => {
    $("status").textContent = "Testing…";
    try {
        const url = $("backendUrl").value.trim().replace(/\/$/, "") + "/api/v1/extension/config";
        const res = await fetch(url, {
            headers: { "X-Extension-Token": $("apiToken").value.trim() }
        });
        if (res.ok) {
            const cfg = await res.json();
            $("status").textContent = `OK — ${cfg.searches.length} searches configured.`;
            $("configDump").textContent = JSON.stringify(cfg, null, 2);
        } else {
            $("status").textContent = `HTTP ${res.status}`;
        }
    } catch (e) {
        $("status").textContent = `Failed: ${e.message}`;
    }
};

load();
