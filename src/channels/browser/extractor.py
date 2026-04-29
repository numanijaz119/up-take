"""
DOMExtractor — extracts job data from rendered Upwork search pages.

Pure read-only: no DOM modifications, no clicks, no network requests.
Runs a JavaScript function inside the live browser tab via page.evaluate().

Selectors validated against real Upwork search page HTML (April 2026).
All selectors use data-test attributes where available (stable across builds),
with fallbacks for resilience against minor DOM changes.

Key selector discoveries from HTML audit:
  - Job tiles are <article data-ev-job-uid="..."> — no data-test on the container
  - Job ID lives on data-ev-job-uid, NOT in the URL (URL has "02" prefix)
  - Title link: data-test="job-tile-title-link"  (NOT "job-tile-title")
  - Description: <p class="mb-0 text-body-sm rr-mask"> inside .air3-line-clamp
  - Job type + rate: data-test="job-type-label"   (NOT "job-type" or "budget")
  - Fixed price budget: data-test="is-fixed-price"
  - Duration: data-test="duration-label"          (NOT "duration")
  - Posted: data-test="job-pubilshed-date"        (Upwork typo — "pubilshed")
  - Client rating value: .air3-rating-value-text inside [data-test="feedback-rating"]
  - Client location: data-test="location"         (NOT "client-country")
  - Skills: data-test="token"                     ✓ correct
  - Proposals: data-test="proposals-tier"         ✓ correct
  - Payment verified: data-test="payment-verified" ✓ correct
  - Client spent: data-test="total-spent"         ✓ correct (use strong child for clean value)
  - Connects required: NOT present on search tiles (only on job detail page)
"""
import logging
from playwright.async_api import Page

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JavaScript extraction function — runs inside the browser tab's JS context.
# Called once per scroll position via page.evaluate().
# ---------------------------------------------------------------------------

EXTRACT_SCRIPT = r"""
() => {
    // ── Helpers ─────────────────────────────────────────────────────────────

    /**
     * getText: try each CSS selector in order, return trimmed text of first match.
     * Returns null if none match.
     */
    const getText = (parent, selectors) => {
        for (const sel of selectors) {
            const el = parent.querySelector(sel);
            if (el) {
                // Strip any sr-only (screen-reader-only) spans that pollute text
                // e.g. location li has <span class="sr-only">Location </span>
                const srOnly = el.querySelectorAll('.sr-only');
                if (srOnly.length) {
                    // Clone, remove sr-only nodes, return remaining text
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
    };

    /**
     * cleanTitle: remove highlight wrapper text artifacts.
     * Upwork wraps matched search terms in <span class="highlight">.
     * textContent merges them without spaces sometimes ("DjangoWeb Developer").
     * Use innerText instead which respects whitespace better, with fallback.
     */
    const cleanTitle = (el) => {
        try {
            // innerText respects CSS whitespace; textContent does not
            return (el.innerText || el.textContent || '').trim()
                .replace(/\s+/g, ' ');
        } catch(e) {
            return (el.textContent || '').trim().replace(/\s+/g, ' ');
        }
    };

    /**
     * cleanUrl: strip Upwork tracking query params and make absolute.
     */
    const cleanUrl = (href) => {
        if (!href) return null;
        try {
            // Resolve relative URLs (href may be "/jobs/...")
            const base = 'https://www.upwork.com';
            const url = href.startsWith('http') ? new URL(href) : new URL(href, base);
            // Remove referrer_url_path tracking param
            url.searchParams.delete('referrer_url_path');
            return url.toString();
        } catch(e) {
            return href;
        }
    };

    // ── Main extraction ──────────────────────────────────────────────────────

    const jobs = [];

    // Tile container: <article data-ev-job-uid="...">
    // Note: no data-test on the article itself — match by tag name and class
    const tiles = document.querySelectorAll(
        'article.job-tile, article[data-ev-job-uid]'
    );

    tiles.forEach(tile => {
        // ── Job ID ───────────────────────────────────────────────────────────
        // data-ev-job-uid is the canonical Upwork job UID on the <article> tag.
        // The URL has a "02" prefix — do NOT extract from URL.
        const jobId = tile.getAttribute('data-ev-job-uid');
        if (!jobId) return;   // skip malformed tiles

        // ── Title link ───────────────────────────────────────────────────────
        // <a data-test="job-tile-title-link" href="/jobs/<slug>_~02<id>/...">
        const titleLink = tile.querySelector('[data-test="job-tile-title-link"]');
        if (!titleLink) return;  // skip tiles without a title link

        const jobUrl = cleanUrl(titleLink.getAttribute('href'));
        const title  = cleanTitle(titleLink);

        // ── Description snippet ──────────────────────────────────────────────
        // <div class="air3-line-clamp is-clamped">
        //   <p class="mb-0 text-body-sm rr-mask">...</p>
        // </div>
        // No data-test on description in search tiles.
        const description = getText(tile, [
            '[class*="air3-line-clamp"] p',
            'p.text-body-sm',
            '.up-lineClamp p',
            '[data-test="description"] p',    // job detail page fallback
            '[data-test="job-description-text"]',
        ]);

        // ── Job type & budget ────────────────────────────────────────────────
        // Hourly: <li data-test="job-type-label"><strong>Hourly: $15.00 - $35.00</strong>
        // Fixed:  <li data-test="job-type-label"><strong>Fixed price</strong>
        //         <li data-test="is-fixed-price"><strong>Est. budget:</strong><strong>$20.00</strong>
        const jobTypeText = getText(tile, [
            '[data-test="job-type-label"]',
            '[data-test="job-type"]',   // legacy fallback
        ]);

        // Budget: for hourly it's embedded in jobTypeText; for fixed, separate li
        const fixedBudget = getText(tile, ['[data-test="is-fixed-price"]']);
        let budget = null;
        if (fixedBudget) {
            // Extract just the dollar amount from "Est. budget: $20.00"
            const match = fixedBudget.match(/\$[\d,K.+]+/);
            budget = match ? match[0] : fixedBudget;
        } else if (jobTypeText && jobTypeText.toLowerCase().includes('hourly')) {
            // Hourly rate is part of the job type label: "Hourly: $15.00 - $35.00"
            const match = jobTypeText.match(/\$[\d,K.+\s\-]+/);
            budget = match ? match[0].trim() : null;
        }

        // Normalise jobType to "Hourly" or "Fixed price"
        let jobType = null;
        if (jobTypeText) {
            const lower = jobTypeText.toLowerCase();
            if (lower.includes('hourly'))       jobType = 'Hourly';
            else if (lower.includes('fixed'))   jobType = 'Fixed price';
            else                                 jobType = jobTypeText.split('\n')[0].trim();
        }

        // ── Experience level ─────────────────────────────────────────────────
        // <li data-test="experience-level"><strong>Intermediate</strong>
        const experienceLevel = getText(tile, ['[data-test="experience-level"]']);

        // ── Duration ─────────────────────────────────────────────────────────
        // <li data-test="duration-label"><strong>Est. time:</strong><strong>3 to 6 months...</strong>
        // Note: "duration" (no suffix) does NOT exist — must be "duration-label"
        const duration = getText(tile, [
            '[data-test="duration-label"]',
            '[data-test="duration"]',   // legacy fallback
        ]);

        // ── Skills ───────────────────────────────────────────────────────────
        // <button data-test="token" class="air3-token">Django</button>
        const skills = [...tile.querySelectorAll('[data-test="token"]')]
            .map(el => el.textContent.trim())
            .filter(Boolean);

        // ── Posted time ──────────────────────────────────────────────────────
        // <small data-test="job-pubilshed-date"> — Upwork has a typo: "pubilshed"
        const postedTime = getText(tile, [
            '[data-test="job-pubilshed-date"]',   // actual Upwork typo
            '[data-test="job-published-date"]',   // in case they fix the typo
            '[data-test="posted-on"]',            // legacy fallback
            'time',
        ]);

        // ── Proposal count ───────────────────────────────────────────────────
        // <li data-test="proposals-tier"><strong>50+</strong>
        const proposals = getText(tile, ['[data-test="proposals-tier"]']);

        // ── Payment verified ─────────────────────────────────────────────────
        // <li data-test="payment-verified"> present = verified, absent = not
        const paymentVerifiedEl = tile.querySelector('[data-test="payment-verified"]');
        const paymentVerified = !!paymentVerifiedEl;

        // ── Client total spent ───────────────────────────────────────────────
        // <li data-test="total-spent"><strong class="rr-mask">$1K+</strong><span>spent</span>
        // Use the strong child to get just the amount, not "spent" appended
        let clientSpent = null;
        const spentEl = tile.querySelector('[data-test="total-spent"]');
        if (spentEl) {
            const strongEl = spentEl.querySelector('strong');
            clientSpent = strongEl
                ? strongEl.textContent.trim()
                : spentEl.textContent.trim().replace(/\s*spent\s*/i, '').trim();
        }

        // ── Client rating ────────────────────────────────────────────────────
        // The star rating widget uses SVGs; the numeric value is in:
        // [data-test="feedback-rating"] .air3-rating-value-text
        const clientRating = getText(tile, [
            '[data-test="feedback-rating"] .air3-rating-value-text',
            '[data-test="total-feedback"] .air3-rating-value-text',
            '[data-test="client-rating"]',   // legacy fallback
        ]);

        // ── Client location ──────────────────────────────────────────────────
        // <li data-test="location"><div><svg...></div><span>...<span class="sr-only">Location </span>United States</span></li>
        // getText() already strips .sr-only spans above.
        const clientLocation = getText(tile, [
            '[data-test="location"]',
            '[data-test="client-country"]',  // legacy fallback
        ]);

        // ── Assemble ─────────────────────────────────────────────────────────
        jobs.push({
            id:               jobId,
            title:            title || null,
            description:      description || null,
            budget:           budget || null,
            jobType:          jobType || null,
            experienceLevel:  experienceLevel || null,
            duration:         duration || null,
            skills:           skills,
            postedTime:       postedTime || null,
            proposals:        proposals || null,
            clientSpent:      clientSpent || null,
            clientRating:     clientRating || null,
            clientLocation:   clientLocation || null,
            paymentVerified:  paymentVerified,
            // connectsRequired: not present on search tiles (only on job detail)
            url:              jobUrl,
            source:           'browser_channel',
            observedAt:       new Date().toISOString(),
        });
    });

    return jobs;
}
"""


class DOMExtractor:
    """
    Extracts job data from rendered Upwork job feed pages.
    Pure read-only — no DOM modification, no clicks, no side effects.
    """

    async def extract_visible_jobs(self, page: Page) -> list[dict]:
        """
        Extract all job tiles currently rendered on the page.
        Returns list of job dicts; empty list on error (never raises).
        """
        try:
            jobs = await page.evaluate(EXTRACT_SCRIPT)
            result = jobs or []
            if result:
                logger.debug(f"Extracted {len(result)} job tiles from page")
            else:
                logger.warning(
                    "extract_visible_jobs returned 0 jobs. "
                    "Possible causes: page not loaded yet, DOM selectors changed, "
                    "or search returned no results."
                )
            return result
        except Exception as e:
            logger.warning(f"DOM extraction failed: {e}")
            return []
