"""
TelegramNotifier — sends alerts and proposal notifications to a Telegram chat.

Falls back to logging if Telegram is not configured (bot token / chat ID empty).
Every method always logs regardless of whether Telegram is reachable.
"""
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    INFO     = "info"      # routine status
    WARNING  = "warning"   # needs attention but not urgent
    ERROR    = "error"     # something broke, will auto-retry
    CRITICAL = "critical"  # channel stopped, human must act


_SEVERITY_EMOJI = {
    AlertSeverity.INFO:     "ℹ️",
    AlertSeverity.WARNING:  "⚠️",
    AlertSeverity.ERROR:    "🔴",
    AlertSeverity.CRITICAL: "🚨",
}


class TelegramNotifier:
    """
    Sends proposal alerts and operational alerts to a Telegram chat.

    Proposal alerts include inline Approve / Skip buttons.
    Operational alerts use send_alert() or send_text().
    All methods are safe to call even when Telegram is not configured.
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._bot = None
        self._enabled = bool(
            bot_token and chat_id
            and bot_token not in ("", "your_telegram_bot_token_here")
        )
        if not self._enabled:
            logger.info(
                "Telegram not configured — all alerts will be logged only. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable."
            )

    # ── Bot initialisation ────────────────────────────────────────────────────

    async def _get_bot(self):
        if self._bot is None and self._enabled:
            try:
                from telegram import Bot
                self._bot = Bot(token=self.bot_token)
            except ImportError:
                logger.warning(
                    "python-telegram-bot not installed — Telegram disabled. "
                    "Install with: pip install python-telegram-bot"
                )
                self._enabled = False
            except Exception as e:
                logger.warning(f"Telegram bot init failed: {e}")
                self._enabled = False
        return self._bot

    # ── Public API ────────────────────────────────────────────────────────────

    async def send_proposal_alert(self, data: dict) -> None:
        """
        Send a job + proposal alert with inline Approve / Skip buttons.
        data keys: job, analysis, proposal, proposal_id, job_db_id
        """
        job      = data.get("job", {})
        analysis = data.get("analysis", {})
        proposal = data.get("proposal", {})

        score    = analysis.get("opportunity_score", 0)
        quality  = proposal.get("quality_score", 0)
        title    = (job.get("title") or "Untitled")[:80]
        url      = job.get("url", "")
        preview  = (proposal.get("text") or "")[:600]
        flags    = analysis.get("red_flags") or []
        intent   = analysis.get("client_intent", "unknown")

        # Always log
        logger.info(
            f"PROPOSAL READY | Score: {score}/100 | Quality: {quality:.1f}/10 | "
            f"'{title}' | {url}"
        )

        if not self._enabled:
            logger.info("Telegram not configured — proposal alert logged only")
            return

        bot = await self._get_bot()
        if not bot:
            return

        score_emoji = "🔥" if score >= 80 else "✅" if score >= 65 else "⚠️"
        flag_text   = "\n".join(f"  ⚠️ {f}" for f in flags) if flags else "  None"

        message = (
            f"{score_emoji} *New Job Match!*\n\n"
            f"*{title}*\n"
            f"Score: `{score}/100` | Quality: `{quality:.1f}/10` | Intent: `{intent}`\n\n"
            f"*Red Flags:*\n{flag_text}\n\n"
            f"*Proposal Preview:*\n```\n{preview}\n```\n\n"
            f"[View Job on Upwork]({url})"
        )

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Approve", callback_data=f"approve:{data['proposal_id']}"
                    ),
                    InlineKeyboardButton(
                        "❌ Skip", callback_data=f"skip:{data['proposal_id']}"
                    ),
                ]
            ])
            await bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown",
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )
            logger.info(f"Telegram proposal alert sent for proposal {data['proposal_id']}")
        except Exception as e:
            logger.error(f"Telegram send_proposal_alert failed: {e}")

    async def send_alert(
        self,
        message: str,
        severity: AlertSeverity = AlertSeverity.INFO,
        *,
        title: str | None = None,
    ) -> None:
        """
        Send an operational alert with a severity level.

        Args:
            message: Alert body (Markdown supported).
            severity: INFO / WARNING / ERROR / CRITICAL.
            title: Optional override for the alert title.
        """
        emoji = _SEVERITY_EMOJI[severity]
        heading = title or severity.value.upper()

        full_log = f"[{severity.value.upper()}] {heading}: {_strip_md(message)}"
        if severity == AlertSeverity.CRITICAL:
            logger.critical(full_log)
        elif severity == AlertSeverity.ERROR:
            logger.error(full_log)
        elif severity == AlertSeverity.WARNING:
            logger.warning(full_log)
        else:
            logger.info(full_log)

        if not self._enabled:
            return

        bot = await self._get_bot()
        if not bot:
            return

        text = f"{emoji} *{heading}*\n\n{message}"
        try:
            await bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error(f"Telegram send_alert failed: {e}")

    async def send_text(self, text: str) -> None:
        """
        Send raw Markdown text to the Telegram chat.
        Always logs; silently skips if Telegram is not configured.
        """
        logger.info(f"[TG] {_strip_md(text)[:200]}")

        if not self._enabled:
            return

        bot = await self._get_bot()
        if not bot:
            return

        try:
            await bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error(f"Telegram send_text failed: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_md(text: str) -> str:
    """Remove Markdown formatting characters for clean log output."""
    return text.replace("*", "").replace("`", "").replace("_", "")
