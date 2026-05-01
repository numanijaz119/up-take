(async () => {
    console.log('[cs] content_script.js injected — url:', location.href);

    // ── Detect logged-out / Cloudflare states ──────────────────────────────────
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

    if (isCloudflareChallenge()) {
        chrome.runtime.sendMessage({ type: "EVENT", kind: "cloudflare_challenge" });
        return;
    }
    if (isLoggedOut()) {
        chrome.runtime.sendMessage({ type: "EVENT", kind: "logged_out" });
        return;
    }

    // ── Wait for job-list container ────────────────────────────────────────────
    async function waitFor(selector, timeoutMs = 10000) {
        const start = Date.now();
        while (Date.now() - start < timeoutMs) {
            const el = document.querySelector(selector);
            if (el) return el;
            await new Promise((r) => setTimeout(r, 250));
        }
        return null;
    }

    const container = await waitFor('[data-test="job-tile-list"], [data-test="JobTileList"]');
    if (!container) {
        chrome.runtime.sendMessage({
            type: "EVENT",
            kind: "selector_breakage",
            detail: "job-tile-list container not found within 10s",
        });
        return;
    }

    // ── Import extractor and send jobs ─────────────────────────────────────────
    const { extractVisibleJobs } = await import(chrome.runtime.getURL("extractor.js"));

    async function extractAndSend(reason) {
        let jobs;
        try {
            jobs = extractVisibleJobs(document);
        } catch (e) {
            chrome.runtime.sendMessage({
                type: "EVENT", kind: "extraction_error", detail: String(e),
            });
            return;
        }
        if (!jobs.length) return;
        chrome.runtime.sendMessage({ type: "EXTRACTED_JOBS", jobs });
        console.log(`[cs] Extracted ${jobs.length} jobs (${reason})`);
    }

    await extractAndSend("initial");

    // ── MutationObserver for incremental updates ───────────────────────────────
    const observer = new MutationObserver(() => {
        clearTimeout(window.__upTakeExtractTimer);
        window.__upTakeExtractTimer = setTimeout(() => extractAndSend("mutation"), 800);
    });
    observer.observe(container, { childList: true, subtree: false });
})();
