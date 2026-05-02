/**
 * extractor.js — pure ES module for extracting Upwork job tiles from a document.
 *
 * Selectors validated against real Upwork search page HTML (May 2026).
 *
 * Key selector notes (current DOM):
 *   - Job tiles are <section data-ev-opening_uid="..."> (was article[data-ev-job-uid])
 *   - Job ID lives on data-ev-opening_uid
 *   - Title link: h3.job-tile-title a (no data-test on the anchor)
 *   - Description: data-test="job-description-text"
 *   - Job type: data-test="job-type"
 *   - Budget: data-test="budget"
 *   - Experience: data-test="contractor-tier"
 *   - Skills: data-test="attr-item"
 *   - Posted: data-test="posted-on"
 *   - Proposals: data-test="proposals"
 *   - Payment verified: data-test="payment-verification-status"
 *   - Client spent: data-test="client-spendings" > data-test="formatted-amount"
 *   - Client rating: [data-test="js-feedback"] .sr-only (text: "Rating is X out of 5.")
 *   - Client location: data-test="client-country"
 */

function getText(parent, selectors) {
    for (const sel of selectors) {
        const el = parent.querySelector(sel);
        if (el) {
            const srOnly = el.querySelectorAll('.sr-only');
            if (srOnly.length) {
                const clone = el.cloneNode(true);
                clone.querySelectorAll('.sr-only').forEach(n => n.remove());
                const t = clone.textContent.trim();
                if (t) return t;
            }
            const t = el.textContent.trim();
            if (t) return t;
        }
    }
    return null;
}

function cleanTitle(el) {
    try {
        return (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    } catch (e) {
        return (el.textContent || '').trim().replace(/\s+/g, ' ');
    }
}

function cleanUrl(href) {
    if (!href) return null;
    try {
        const base = 'https://www.upwork.com';
        const url = href.startsWith('http') ? new URL(href) : new URL(href, base);
        url.searchParams.delete('referrer_url_path');
        return url.toString();
    } catch (e) {
        return href;
    }
}

export function extractVisibleJobs(doc) {
    const jobs = [];
    const now = new Date().toISOString();

    // section[data-ev-opening_uid] as of 2026; article[data-ev-job-uid] kept as fallback
    const tiles = doc.querySelectorAll(
        'section[data-ev-opening_uid], article[data-ev-job-uid]'
    );

    tiles.forEach(tile => {
        // ── Job ID ──────────────────────────────────────────────────────────────
        const jobId = tile.getAttribute('data-ev-opening_uid')
            || tile.getAttribute('data-ev-job-uid');
        if (!jobId) return;

        // ── Title + URL ─────────────────────────────────────────────────────────
        // .job-tile-title covers both h2 (search page) and h3 (find-work page).
        // ~= matches a token in a space-separated data-test value ("job-tile-title-link UpLink").
        const titleLink = tile.querySelector('.job-tile-title a')
            || tile.querySelector('[data-test~="job-tile-title-link"]');
        if (!titleLink) return;

        const job_url = cleanUrl(titleLink.getAttribute('href'));
        const title = cleanTitle(titleLink);

        // ── Description ─────────────────────────────────────────────────────────
        const description = getText(tile, [
            '[data-test="job-description-text"]',
            '[class*="air3-line-clamp"] p',
            'p.text-body-sm',
            '[data-test="job-description-line-clamp"]',
        ]);

        // ── Job type ────────────────────────────────────────────────────────────
        const jobTypeText = getText(tile, [
            '[data-test="job-type"]',
            '[data-test="job-type-label"]',
        ]);

        let job_type = null;
        if (jobTypeText) {
            const lower = jobTypeText.toLowerCase();
            if (lower.includes('hourly'))      job_type = 'Hourly';
            else if (lower.includes('fixed'))  job_type = 'Fixed price';
            else                               job_type = jobTypeText.split('\n')[0].trim();
        }

        // ── Budget ──────────────────────────────────────────────────────────────
        const budgetText = getText(tile, [
            '[data-test="budget"]',
            '[data-test="is-fixed-price"]',
        ]);

        let budget = null;
        if (budgetText) {
            const match = budgetText.match(/\$[\d,K.+]+/);
            budget = match ? match[0] : budgetText.trim();
        } else if (job_type === 'Hourly' && jobTypeText) {
            const match = jobTypeText.match(/\$[\d,.K+]+(?:\s*[-–]\s*\$[\d,.K+]+)?/);
            budget = match ? match[0].trim() : null;
        }

        // ── Experience level ────────────────────────────────────────────────────
        const experience_level = getText(tile, [
            '[data-test="contractor-tier"]',
            '[data-test="experience-level"]',
        ]);

        // ── Duration ────────────────────────────────────────────────────────────
        const duration = getText(tile, [
            '[data-test="duration-label"]',
            '[data-test="duration"]',
        ]);

        // ── Skills ──────────────────────────────────────────────────────────────
        const skills = [
            ...tile.querySelectorAll('[data-test="attr-item"]'),
            ...tile.querySelectorAll('[data-test="token"]'),
        ]
            .map(el => el.textContent.trim())
            .filter(Boolean)
            .filter((v, i, a) => a.indexOf(v) === i); // dedupe

        // ── Posted time ─────────────────────────────────────────────────────────
        const posted_time = getText(tile, [
            '[data-test="posted-on"]',
            '[data-test="job-pubilshed-date"]',
            '[data-test="job-published-date"]',
            'time',
        ]);

        // ── Proposals ───────────────────────────────────────────────────────────
        const proposals = getText(tile, [
            '[data-test="proposals"]',
            '[data-test="proposals-tier"]',
        ]);

        // ── Payment verified ────────────────────────────────────────────────────
        const pvEl = tile.querySelector(
            '[data-test="payment-verification-status"], [data-test="payment-verified"]'
        );
        const payment_verified = pvEl
            ? /verified/i.test(pvEl.textContent) && !/not/i.test(pvEl.textContent)
            : false;

        // ── Client total spent ──────────────────────────────────────────────────
        let client_spent = null;
        const spentEl = tile.querySelector(
            '[data-test="client-spendings"], [data-test="total-spent"]'
        );
        if (spentEl) {
            const amtEl = spentEl.querySelector('[data-test="formatted-amount"]')
                || spentEl.querySelector('strong');
            client_spent = amtEl
                ? amtEl.textContent.trim()
                : spentEl.textContent.replace(/spent/i, '').trim();
        }

        // ── Client rating ───────────────────────────────────────────────────────
        // Rating rendered as star width%; text is in sr-only: "Rating is X out of 5."
        let client_rating = null;
        const ratingEl = tile.querySelector(
            '[data-test="js-feedback"] .air3-rating .sr-only'
        );
        if (ratingEl) {
            const m = ratingEl.textContent.match(/([\d.]+)\s+out\s+of/i);
            if (m && parseFloat(m[1]) > 0) client_rating = m[1];
        }
        if (!client_rating) {
            client_rating = getText(tile, [
                '[data-test="feedback-rating"] .air3-rating-value-text',
                '[data-test="total-feedback"] .air3-rating-value-text',
                '[data-test="client-rating"]',
            ]);
        }

        // ── Client location ─────────────────────────────────────────────────────
        const client_location = getText(tile, [
            '[data-test="client-country"]',
            '[data-test="location"]',
        ]);

        // ── Assemble ────────────────────────────────────────────────────────────
        jobs.push({
            id:               jobId,
            title:            title || null,
            description:      description || null,
            budget:           budget || null,
            job_type:         job_type || null,
            experience_level: experience_level || null,
            duration:         duration || null,
            skills:           skills,
            posted_time:      posted_time || null,
            proposals:        proposals || null,
            client_spent:     client_spent || null,
            client_rating:    client_rating || null,
            client_location:  client_location || null,
            payment_verified: payment_verified,
            url:              job_url,
            source:           'extension_channel',
            observed_at:      now,
        });
    });

    return jobs;
}
