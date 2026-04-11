import logging
from datetime import datetime
from playwright.async_api import Page

logger = logging.getLogger(__name__)

EXTRACT_SCRIPT = """
() => {
    const getText = (parent, selectors) => {
        for (const sel of selectors) {
            const el = parent.querySelector(sel);
            if (el) return el.textContent.trim();
        }
        return null;
    };

    const jobs = [];
    const tiles = document.querySelectorAll(
        'article, [data-test="job-tile"], section.up-card-section'
    );

    tiles.forEach(tile => {
        const link = tile.querySelector('a[href*="/jobs/~"]');
        if (!link) return;

        const jobId = (link.href.match(/~(\\w+)/) || [])[1];
        if (!jobId) return;

        const paymentVerifiedEl = tile.querySelector(
            '[data-test="payment-verified"], .payment-verified, ' +
            '[data-test="payment-status-verified"]'
        );

        jobs.push({
            id: jobId,
            title: getText(tile, ['h2', 'h3', '[data-test="job-tile-title"]', '.job-title']),
            description: getText(tile, [
                '[data-test="job-description-text"]',
                '.job-description',
                '[data-test="UpCOntractorSearchResult-text"]',
                '[data-test="description"]',
                '.up-lineClamp',
            ]),
            budget: getText(tile, [
                '[data-test="budget"]', '.budget', '[data-test="is-fixed-price"]',
                '[data-test="job-type"]', '.js-budget',
            ]),
            jobType: getText(tile, ['[data-test="job-type"]', '.job-type']),
            experienceLevel: getText(tile, ['[data-test="experience-level"]', '.level']),
            duration: getText(tile, ['[data-test="duration"]', '.duration']),
            skills: [...tile.querySelectorAll(
                '.up-skill-badge, [data-test="token"], .air3-token, [data-test="skill"]'
            )].map(el => el.textContent.trim()).filter(Boolean),
            postedTime: getText(tile, [
                '[data-test="posted-on"]', '.posted-on',
                '[data-test="job-tile-timestamp"]', 'time',
            ]),
            proposals: getText(tile, [
                '[data-test="proposals-tier"]', '.proposals-tier',
                '[data-test="contractor-tier"]', '[data-test="proposals"]',
            ]),
            clientSpent: getText(tile, ['[data-test="total-spent"]', '.client-spent']),
            clientRating: getText(tile, ['[data-test="client-rating"]', '.rating']),
            clientLocation: getText(tile, ['[data-test="client-country"]', '.location']),
            paymentVerified: !!paymentVerifiedEl,
            connectsRequired: getText(tile, ['[data-test="connects"]', '.connects']),
            url: link.href,
            source: 'browser_channel',
            observedAt: new Date().toISOString(),
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
        """Extract all job tiles currently rendered on the page."""
        try:
            jobs = await page.evaluate(EXTRACT_SCRIPT)
            return jobs or []
        except Exception as e:
            logger.warning(f"DOM extraction failed: {e}")
            return []
