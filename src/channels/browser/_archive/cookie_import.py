"""
Cookie import — pull Upwork session cookies from your installed Chrome browser.

Why this exists
---------------
Cloudflare Turnstile detects Playwright on the login page (even with
channel="chrome") and loops the verification challenge indefinitely. Logging in
via your normal Chrome (no Playwright in the picture) bypasses the challenge.
This script converts the resulting cookies into Playwright's storage_state
format so automated sessions can use them.

Two import paths (script tries both)
------------------------------------

PATH A — Manual export via Cookie-Editor extension  [RECOMMENDED]
    Required for Chrome 127+ (App-Bound Encryption blocks automatic decryption).

    1. Install "Cookie-Editor" from the Chrome Web Store
       https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm
    2. Open upwork.com in Chrome and confirm you are logged in
    3. Click the Cookie-Editor icon  →  "Export"  →  "Export as JSON"
    4. Save the file to:  sessions/upwork_cookies_export.json
    5. Run:  python -m src.channels.browser.cookie_import

PATH B — Automatic via browser-cookie3   [older Chrome only]
    Works on Chrome <127 where cookies are encrypted with DPAPI only.
    Will fail on modern Chrome with "Unable to get key for cookie decryption".

Re-run when
-----------
    - Telegram sends a "Session expired" alert
    - Roughly every 30 days (Upwork session lifetime)
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

SESSION_PATH = Path("sessions") / "upwork_session.json"
EXPORT_PATH = Path("sessions") / "upwork_cookies_export.json"

# At least one of these must be present to confirm a real logged-in session
REQUIRED_TOKENS = {"master_access_token", "oauth2_global_js_token"}


# ── Path A: Cookie-Editor JSON export ────────────────────────────────────────

def _normalize_samesite(value) -> str:
    """Map Cookie-Editor / browser samesite values to Playwright's enum."""
    if not value:
        return "Lax"
    v = str(value).strip().lower()
    if v in ("no_restriction", "none", "unspecified"):
        return "None"
    if v == "strict":
        return "Strict"
    return "Lax"


def _from_cookie_editor_export(path: Path) -> list[dict]:
    """Parse a Cookie-Editor 'Export as JSON' file into Playwright cookies."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"Expected a JSON array of cookies, got {type(raw).__name__}. "
            "Make sure you used Cookie-Editor's 'Export as JSON' option."
        )

    pw_cookies = []
    for c in raw:
        if "upwork.com" not in (c.get("domain") or "").lower():
            continue

        # Cookie-Editor uses 'expirationDate' (float seconds since epoch).
        # Session cookies omit this field; Playwright wants -1 for those.
        expires = c.get("expirationDate")
        if expires is None:
            expires = -1

        pw_cookies.append({
            "name":     c["name"],
            "value":    c["value"],
            "domain":   c["domain"],
            "path":     c.get("path") or "/",
            "expires":  float(expires),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure":   bool(c.get("secure", False)),
            "sameSite": _normalize_samesite(c.get("sameSite")),
        })
    return pw_cookies


# ── Path B: browser_cookie3 automatic ────────────────────────────────────────

def _from_browser_cookie3() -> list[dict]:
    """Read cookies directly from Chrome's SQLite DB. Fails on Chrome 127+ ABE."""
    import browser_cookie3
    cj = browser_cookie3.chrome(domain_name="upwork.com")
    pw_cookies = []
    for c in cj:
        if "upwork.com" not in (c.domain or "").lower():
            continue

        http_only = False
        if hasattr(c, "_rest") and c._rest:
            http_only = bool(c._rest.get("HttpOnly"))

        pw_cookies.append({
            "name":     c.name,
            "value":    c.value,
            "domain":   c.domain,
            "path":     c.path or "/",
            "expires":  c.expires if c.expires else -1,
            "httpOnly": http_only,
            "secure":   bool(c.secure),
            "sameSite": "Lax",
        })
    return pw_cookies


# ── Entry point ──────────────────────────────────────────────────────────────

def _print_export_instructions():
    logger.error("")
    logger.error("=" * 60)
    logger.error("HOW TO EXPORT COOKIES MANUALLY (Chrome 127+)")
    logger.error("=" * 60)
    logger.error("")
    logger.error("1. Install Cookie-Editor in Chrome:")
    logger.error("   https://chromewebstore.google.com/detail/cookie-editor/")
    logger.error("   hlkenndednhfkekhgcdicdfddnkalmdm")
    logger.error("")
    logger.error("2. Open upwork.com in Chrome (you should be logged in).")
    logger.error("")
    logger.error("3. Click the Cookie-Editor extension icon in the toolbar.")
    logger.error("   You should see a list of upwork.com cookies.")
    logger.error("")
    logger.error("4. Click the 'Export' button (icon at top of the popup),")
    logger.error("   then choose 'Export as JSON'.")
    logger.error("")
    logger.error("5. Save the resulting JSON to:")
    logger.error(f"   {EXPORT_PATH.resolve()}")
    logger.error("")
    logger.error("6. Re-run this script.")
    logger.error("")


def main():
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.info("=" * 60)
    logger.info("Up-take — Importing Upwork cookies from Chrome")
    logger.info("=" * 60)

    pw_cookies: list[dict] | None = None
    source = None

    # --- Path A: Cookie-Editor JSON export (preferred for modern Chrome) ----
    if EXPORT_PATH.exists():
        logger.info(f"Found manual export at {EXPORT_PATH} — using it.")
        try:
            pw_cookies = _from_cookie_editor_export(EXPORT_PATH)
            source = "cookie-editor-export"
        except Exception as e:
            logger.error(f"Failed to parse {EXPORT_PATH}: {e}")
            logger.error(
                "Check that the file is a JSON array exported by Cookie-Editor.\n"
                "Use 'Export as JSON' (NOT 'Export as Header String' or 'Netscape')."
            )
            sys.exit(1)
    else:
        # --- Path B: browser_cookie3 automatic (works only on older Chrome) -
        logger.info(
            f"No manual export file at {EXPORT_PATH}\n"
            "                          Trying automatic decryption via browser-cookie3…"
        )
        try:
            import browser_cookie3  # noqa: F401  (just to give a clean error if missing)
        except ImportError:
            logger.error("browser-cookie3 is not installed:  pip install browser-cookie3")
            sys.exit(1)

        try:
            pw_cookies = _from_browser_cookie3()
            source = "browser-cookie3"
        except Exception as e:
            logger.error(f"Automatic cookie read failed: {e}")
            logger.error(
                "\nThis is expected on Chrome 127+ (App-Bound Encryption).\n"
                "Use the manual export path instead."
            )
            _print_export_instructions()
            sys.exit(1)

    # --- Validate ----------------------------------------------------------
    if not pw_cookies:
        logger.error("No upwork.com cookies were found in the import source.")
        logger.error(
            "Make sure you are logged into Upwork in Chrome before exporting."
        )
        sys.exit(1)

    cookie_names = {c["name"] for c in pw_cookies}
    found_tokens = REQUIRED_TOKENS & cookie_names
    if not found_tokens:
        logger.error(
            "Cookies were imported, but no Upwork session tokens were found.\n"
            f"Expected at least one of: {sorted(REQUIRED_TOKENS)}\n"
            f"Got: {sorted(cookie_names)}\n"
            "You are probably not fully logged in. Log in again in Chrome and re-export."
        )
        sys.exit(1)

    storage_state = {"cookies": pw_cookies, "origins": []}
    SESSION_PATH.write_text(json.dumps(storage_state, indent=2))

    logger.info("")
    logger.info(f"Source:                 {source}")
    logger.info(f"Saved to:               {SESSION_PATH.resolve()}")
    logger.info(f"Total Upwork cookies:   {len(pw_cookies)}")
    logger.info(f"Session tokens present: {sorted(found_tokens)}")

    earliest = None
    for c in pw_cookies:
        if c["name"] in REQUIRED_TOKENS and c["expires"] and c["expires"] > 0:
            exp = datetime.fromtimestamp(c["expires"])
            if earliest is None or exp < earliest:
                earliest = exp
    if earliest:
        logger.info(f"Session token expires:  {earliest.isoformat()}")

    logger.info("=" * 60)
    logger.info("SUCCESS — automated browser sessions will now use these cookies.")
    logger.info("Re-run this script when you see 'Session Expired' alerts on Telegram.")


if __name__ == "__main__":
    main()
