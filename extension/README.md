# Up-take Browser Extension

Observes Upwork search pages in your own logged-in Chrome and forwards new job listings to the local Up-take backend. No automation framework; no Cloudflare bypass tricks needed.

## Install

1. Open `chrome://extensions/`
2. Toggle **Developer mode** (top-right)
3. Click **Load unpacked**
4. Select this `extension/` directory
5. Click the puzzle-piece icon in the toolbar → **Up-take** → **Options**
6. Set **Backend URL** (default: `http://localhost:8000`)
7. Set **API Token** — must match `EXTENSION_API_TOKEN` in your `.env`
8. Click **Test Connection** — should show "OK — N searches configured"
9. Open `https://www.upwork.com/nx/find-work/best-matches` — confirm you're logged in

The extension claims the first Upwork search tab it sees as the "managed tab" and will reload it on a 6–14 minute jittered schedule. New jobs appear in Telegram within one reload cycle.

## Configuration

All search URLs and timing settings live server-side. Change them in the backend dashboard or database; the extension picks them up within 5 minutes via the `/api/v1/extension/config` endpoint.

The only local settings (backend URL and API token) are in the options page.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Test Connection → HTTP 401 | Re-paste the `EXTENSION_API_TOKEN` value |
| Test Connection → Failed | Check the backend is running, URL is correct |
| No heartbeat arriving | Open options page to revive the service worker |
| Logged-out alert | Open the Upwork tab and log back in |
| Cloudflare alert | Open the tab and click the checkbox |
| Selector breakage alert | Inspect the Upwork page DOM and update selectors in `extractor.js` |
