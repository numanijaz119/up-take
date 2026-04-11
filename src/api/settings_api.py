from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

from src.config import settings

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])


class SafetySettingsUpdate(BaseModel):
    max_proposals_per_day: Optional[int] = None
    max_proposals_per_hour: Optional[int] = None
    min_seconds_between_proposals: Optional[int] = None
    min_opportunity_score: Optional[int] = None
    min_proposal_quality: Optional[float] = None
    active_hours_start: Optional[int] = None
    active_hours_end: Optional[int] = None
    max_connects_per_day: Optional[int] = None
    max_proposal_word_overlap: Optional[float] = None


@router.get("/safety")
async def get_safety_settings():
    return {
        "max_proposals_per_day": settings.max_proposals_per_day,
        "max_proposals_per_hour": settings.max_proposals_per_hour,
        "min_seconds_between_proposals": settings.min_seconds_between_proposals,
        "min_opportunity_score": settings.min_opportunity_score,
        "min_proposal_quality": settings.min_proposal_quality,
        "active_hours_start": settings.active_hours_start,
        "active_hours_end": settings.active_hours_end,
        "max_connects_per_day": settings.max_connects_per_day,
        "max_proposal_word_overlap": settings.max_proposal_word_overlap,
    }


@router.put("/safety")
async def update_safety_settings(data: SafetySettingsUpdate):
    """Update runtime safety settings. Changes apply immediately, reset on restart."""
    updated = {}
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(settings, field, value)
        updated[field] = value
    return {"updated": updated, "current": await get_safety_settings()}
