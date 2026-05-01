from decouple import config


class Settings:
    def __init__(self):
        # ── Database ──────────────────────────────────────────────────────────
        self.database_url: str = config(
            "DATABASE_URL",
            default="postgresql+asyncpg://uptake:uptake_secret@localhost:5432/uptake",
        )

        # ── Redis ─────────────────────────────────────────────────────────────
        self.redis_url: str = config("REDIS_URL", default="redis://localhost:6379")

        # ── Anthropic ─────────────────────────────────────────────────────────
        self.anthropic_api_key: str = config("ANTHROPIC_API_KEY", default="")

        # ── Telegram ──────────────────────────────────────────────────────────
        self.telegram_bot_token: str = config("TELEGRAM_BOT_TOKEN", default="")
        self.telegram_chat_id: str = config("TELEGRAM_CHAT_ID", default="")

        # ── App ───────────────────────────────────────────────────────────────
        self.debug: bool = config("DEBUG", default=False, cast=bool)
        self.log_level: str = config("LOG_LEVEL", default="INFO")

        # ── Pipeline Thresholds ───────────────────────────────────────────────
        self.min_opportunity_score: int = config(
            "MIN_OPPORTUNITY_SCORE", default=55, cast=int
        )
        self.min_proposal_quality: float = config(
            "MIN_PROPOSAL_QUALITY", default=7.0, cast=float
        )

        # ── Safety Limits ─────────────────────────────────────────────────────
        self.max_proposals_per_day: int = config(
            "MAX_PROPOSALS_PER_DAY", default=12, cast=int
        )
        self.max_proposals_per_hour: int = config(
            "MAX_PROPOSALS_PER_HOUR", default=3, cast=int
        )
        self.min_seconds_between_proposals: int = config(
            "MIN_SECONDS_BETWEEN_PROPOSALS", default=300, cast=int
        )
        self.active_hours_start: int = config(
            "ACTIVE_HOURS_START", default=8, cast=int
        )
        self.active_hours_end: int = config("ACTIVE_HOURS_END", default=23, cast=int)
        self.max_connects_per_day: int = config(
            "MAX_CONNECTS_PER_DAY", default=50, cast=int
        )
        self.max_proposal_word_overlap: float = config(
            "MAX_PROPOSAL_WORD_OVERLAP", default=0.30, cast=float
        )

        # ── LLM ───────────────────────────────────────────────────────────────
        self.llm_model: str = config(
            "LLM_MODEL", default="claude-sonnet-4-20250514"
        )
        self.analysis_temperature: float = config(
            "ANALYSIS_TEMPERATURE", default=0.2, cast=float
        )
        self.generation_temperature: float = config(
            "GENERATION_TEMPERATURE", default=0.7, cast=float
        )
        self.quality_check_temperature: float = config(
            "QUALITY_CHECK_TEMPERATURE", default=0.1, cast=float
        )

        # ── Extension Channel ─────────────────────────────────────────────────
        self.extension_api_token: str = config(
            "EXTENSION_API_TOKEN", default="change-me-in-env"
        )
        self.extension_reload_min_seconds: int = config(
            "EXTENSION_RELOAD_MIN_SECONDS", default=360, cast=int
        )
        self.extension_reload_max_seconds: int = config(
            "EXTENSION_RELOAD_MAX_SECONDS", default=840, cast=int
        )
        self.extension_heartbeat_interval_seconds: int = config(
            "EXTENSION_HEARTBEAT_INTERVAL_SECONDS", default=60, cast=int
        )
        self.extension_heartbeat_timeout_seconds: int = config(
            "EXTENSION_HEARTBEAT_TIMEOUT_SECONDS", default=300, cast=int
        )
        self.extension_config_refetch_seconds: int = config(
            "EXTENSION_CONFIG_REFETCH_SECONDS", default=300, cast=int
        )
        self.extension_quiet_hours_start: int = config(
            "EXTENSION_QUIET_HOURS_START", default=1, cast=int
        )
        self.extension_quiet_hours_end: int = config(
            "EXTENSION_QUIET_HOURS_END", default=7, cast=int
        )
        self.extension_peak_hours_tz: str = config(
            "EXTENSION_PEAK_HOURS_TZ", default="America/New_York"
        )
        self.extension_peak_hours_start: int = config(
            "EXTENSION_PEAK_HOURS_START", default=9, cast=int
        )
        self.extension_peak_hours_end: int = config(
            "EXTENSION_PEAK_HOURS_END", default=22, cast=int
        )
        self.extension_no_jobs_alert_minutes: int = config(
            "EXTENSION_NO_JOBS_ALERT_MINUTES", default=30, cast=int
        )


settings = Settings()
