from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, HttpUrl


class ExtractedJob(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    budget: Optional[str] = None
    job_type: Optional[str] = None
    experience_level: Optional[str] = None
    duration: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    posted_time: Optional[str] = None
    proposals: Optional[str] = None
    client_spent: Optional[str] = None
    client_rating: Optional[str] = None
    client_location: Optional[str] = None
    payment_verified: Optional[bool] = None
    url: str
    source: Literal["extension_channel"] = "extension_channel"
    observed_at: datetime


class JobIngestRequest(BaseModel):
    jobs: list[ExtractedJob]
    tab_url: str
    extension_version: str


class JobIngestResponse(BaseModel):
    received: int
    new: int
    duplicates: int


class HeartbeatRequest(BaseModel):
    extension_version: str
    tabs: list[dict]
    last_job_at: Optional[datetime] = None


class HeartbeatResponse(BaseModel):
    ok: bool
    server_time: datetime


class ExtensionEvent(BaseModel):
    kind: Literal[
        "logged_out",
        "cloudflare_challenge",
        "selector_breakage",
        "extraction_error",
        "tab_closed",
    ]
    url: str
    detail: Optional[str] = None
    occurred_at: datetime


class SearchConfigEntry(BaseModel):
    label: str
    url: str
    weight: float = 1.0


class ConfigResponse(BaseModel):
    searches: list[SearchConfigEntry]
    reload_min_seconds: int
    reload_max_seconds: int
    quiet_hours_start: int
    quiet_hours_end: int
    heartbeat_interval_seconds: int
    config_refetch_interval_seconds: int
