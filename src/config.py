from pydantic_settings import BaseSettings
from typing import List, Tuple
from datetime import time as dt_time


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://uptake:uptake_secret@localhost:5432/uptake"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Anthropic
    anthropic_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # App
    secret_key: str = "change-me-to-random-secret"
    debug: bool = False
    log_level: str = "INFO"

    # Browser
    browser_headless: bool = False
    browser_timezone: str = "America/New_York"

    # ── Session Scheduler ─────────────────────────────────
    session_duration_mean: int = 720      # 12 min in seconds
    session_duration_stddev: int = 240    # 4 min
    session_duration_min: int = 300       # 5 min
    session_duration_max: int = 1500      # 25 min
    searches_per_session_min: int = 2
    searches_per_session_max: int = 4

    # ── Browser Behavior Probabilities ────────────────────
    scroll_back_probability: float = 0.05
    mid_scroll_pause_probability: float = 0.15
    tile_hover_probability: float = 0.40
    job_detail_open_probability: float = 0.35
    distraction_probability: float = 0.30

    # ── Pipeline Thresholds ───────────────────────────────
    min_opportunity_score: int = 55
    min_proposal_quality: float = 7.0

    # ── Safety ───────────────────────────────────────────
    max_proposals_per_day: int = 12
    max_proposals_per_hour: int = 3
    min_seconds_between_proposals: int = 300
    active_hours_start: int = 8
    active_hours_end: int = 23
    max_connects_per_day: int = 50
    max_proposal_word_overlap: float = 0.30

    # ── LLM ──────────────────────────────────────────────
    llm_model: str = "claude-sonnet-4-20250514"
    analysis_temperature: float = 0.2
    generation_temperature: float = 0.7
    quality_check_temperature: float = 0.1

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# Day-of-week activity weights (0=Monday, 6=Sunday)
DAY_WEIGHTS = {
    0: 1.0,   # Monday
    1: 0.95,  # Tuesday
    2: 0.9,   # Wednesday
    3: 0.85,  # Thursday
    4: 0.7,   # Friday
    5: 0.4,   # Saturday
    6: 0.25,  # Sunday
}

# Hour-of-day activity weights
HOUR_WEIGHTS = {
    9:  0.9, 10: 1.0, 11: 0.95,
    12: 0.5,
    13: 0.6, 14: 0.85, 15: 1.0,
    16: 0.9, 17: 0.7,
    18: 0.4, 20: 0.65, 22: 0.3,
}

# Work windows (start_hour, start_min, end_hour, end_min)
WORK_WINDOWS: List[Tuple[dt_time, dt_time]] = [
    (dt_time(9, 0),  dt_time(12, 30)),
    (dt_time(14, 0), dt_time(18, 0)),
    (dt_time(20, 0), dt_time(22, 30)),
]
