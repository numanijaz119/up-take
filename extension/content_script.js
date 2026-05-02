(async () => {
    console.log('[cs] injected —', location.href);

    // ── Extension context guard ────────────────────────────────────────────────
    function isAlive() {
        try { return !!chrome.runtime?.id; } catch { return false; }
    }
    function safeSend(msg) {
        if (!isAlive()) return;
        try { chrome.runtime.sendMessage(msg).catch(() => {}); } catch (_) {}
    }

    // ── Detect logged-out / Cloudflare ─────────────────────────────────────────
    function isCloudflareChallenge() {
        const title = document.title || "";
        if (title === "Just a moment...") return true;
        if (document.querySelector("#challenge-form, .cf-turnstile, #challenge-stage")) return true;
        return false;
    }
    function isLoggedOut() {
        if (document.querySelector('[data-test="user-menu-trigger"]')) return false;
        if (document.querySelector('header [data-test*="avatar" i]')) return false;
        if (location.pathname.startsWith("/ab/account-security/login")) return true;
        if (location.search.includes("redir=") && location.pathname.includes("/login")) return true;
        return false;
    }

    if (isCloudflareChallenge()) { safeSend({ type: "EVENT", kind: "cloudflare_challenge" }); return; }
    if (isLoggedOut())           { safeSend({ type: "EVENT", kind: "logged_out" });            return; }

    // ── Running flag + setup bridge ────────────────────────────────────────────
    let _running = false;
    let _resolveSetup;
    const _setupReady = new Promise(resolve => { _resolveSetup = resolve; });

    try {
        chrome.runtime.onMessage.addListener((msg) => {
            if (msg.type === "TRIGGER_EXTRACT") {
                console.log('[cs] TRIGGER_EXTRACT received');
                _running = true;
                _setupReady.then(ctx => {
                    if (!ctx) { console.warn('[cs] setup failed — no ctx'); return; }
                    ctx.extractAndSend("trigger").catch(() => {});
                    ctx.startObserver();
                });
            }
            if (msg.type === "STOP_EXTRACT") {
                console.log('[cs] STOP_EXTRACT received');
                _running = false;
                _setupReady.then(ctx => { if (ctx) ctx.stopObserver(); });
            }
        });
    } catch (_) {
        return; // context already gone
    }

    // ── Wait for page to render job tiles ─────────────────────────────────────
    async function waitFor(selector, timeoutMs = 12000) {
        const start = Date.now();
        while (Date.now() - start < timeoutMs) {
            const el = document.querySelector(selector);
            if (el) return el;
            await new Promise((r) => setTimeout(r, 300));
        }
        return null;
    }

    // Wait for a job tile — common to both find-work and search/jobs pages.
    // The container (for MutationObserver) is best-effort; extraction works on
    // the full document regardless.
    const tile = await waitFor(
        'section[data-ev-opening_uid], ' +
        'article[data-ev-job-uid], ' +
        '[data-test="job-tile-list"], ' +
        '[data-test="JobTileList"]'
    );

    if (tile) {
        console.log('[cs] page ready, anchor el:', tile.tagName, [...tile.attributes].map(a => `${a.name}="${a.value}"`).join(' '));
    } else {
        console.warn('[cs] waitFor timed out — no job tiles or container found');
        safeSend({ type: "EVENT", kind: "selector_breakage", detail: "No job tiles found within 12s on " + location.pathname });
        _resolveSetup(null);
        return;
    }

    // ── Import extractor ───────────────────────────────────────────────────────
    let extractVisibleJobs;
    try {
        const mod = await import(chrome.runtime.getURL("extractor.js"));
        extractVisibleJobs = mod.extractVisibleJobs;
    } catch (_) {
        _resolveSetup(null);
        return;
    }

    async function extractAndSend(reason) {
        if (!_running || !isAlive()) return;
        let jobs;
        try {
            jobs = extractVisibleJobs(document);
        } catch (e) {
            safeSend({ type: "EVENT", kind: "extraction_error", detail: String(e) });
            return;
        }
        console.log(`[cs] extracted ${jobs.length} jobs (${reason})`);
        if (!jobs.length) return;
        safeSend({ type: "EXTRACTED_JOBS", jobs });
    }

    // ── MutationObserver — best-effort, only if we have a list container ───────
    // Walk up from the tile to find a stable list wrapper for the observer.
    const container = tile.closest('[data-test="job-tile-list"], [data-test="JobTileList"]')
        || (tile.matches('section[data-ev-opening_uid], article[data-ev-job-uid]') ? tile.parentElement : tile)
        || tile;

    let observerStarted = false;
    const observer = new MutationObserver(() => {
        clearTimeout(window.__upTakeExtractTimer);
        window.__upTakeExtractTimer = setTimeout(() => extractAndSend("mutation"), 800);
    });
    function startObserver() {
        if (observerStarted || !container) return;
        observerStarted = true;
        observer.observe(container, { childList: true, subtree: false });
        console.log('[cs] observer started on', container.tagName, container.getAttribute('data-test') || '');
    }
    function stopObserver() {
        if (!observerStarted) return;
        observer.disconnect();
        observerStarted = false;
        console.log('[cs] observer stopped');
    }

    console.log('[cs] setup complete — waiting for TRIGGER_EXTRACT');
    _resolveSetup({ extractAndSend, startObserver, stopObserver });
})();
