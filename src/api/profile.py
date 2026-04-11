import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database import get_db
from src.models.profile import FreelancerProfile

router = APIRouter(prefix="/api/v1/profile", tags=["Profile"])


class ProfileCreate(BaseModel):
    name: str
    skills: List[str] = []
    experience_summary: Optional[str] = None
    tone_description: Optional[str] = None
    sample_proposals: Optional[List[str]] = None
    rate_min: Optional[float] = None
    rate_max: Optional[float] = None
    max_proposal_words: int = 200
    preferences: dict = {}


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    skills: Optional[List[str]] = None
    experience_summary: Optional[str] = None
    tone_description: Optional[str] = None
    sample_proposals: Optional[List[str]] = None
    rate_min: Optional[float] = None
    rate_max: Optional[float] = None
    max_proposal_words: Optional[int] = None
    preferences: Optional[dict] = None


class PreferencesUpdate(BaseModel):
    min_budget: Optional[float] = None
    require_payment_verified: Optional[bool] = None
    min_client_spent: Optional[float] = None
    max_existing_proposals: Optional[int] = None
    blacklist_keywords: Optional[List[str]] = None
    min_skill_overlap: Optional[int] = None


@router.get("/")
async def get_profile(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FreelancerProfile).where(FreelancerProfile.is_active == True).limit(1)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "No active profile found. Create one with POST /api/v1/profile/")
    return _profile_out(profile)


@router.post("/", status_code=201)
async def create_profile(data: ProfileCreate, db: AsyncSession = Depends(get_db)):
    profile = FreelancerProfile(
        name=data.name,
        skills=data.skills,
        experience_summary=data.experience_summary,
        tone_description=data.tone_description,
        sample_proposals=data.sample_proposals,
        rate_min=data.rate_min,
        rate_max=data.rate_max,
        max_proposal_words=data.max_proposal_words,
        preferences=data.preferences,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return _profile_out(profile)


@router.put("/")
async def update_profile(data: ProfileUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FreelancerProfile).where(FreelancerProfile.is_active == True).limit(1)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "No active profile found")

    for k, v in data.model_dump(exclude_none=True).items():
        setattr(profile, k, v)
    profile.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(profile)
    return _profile_out(profile)


@router.put("/preferences")
async def update_preferences(data: PreferencesUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FreelancerProfile).where(FreelancerProfile.is_active == True).limit(1)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "No active profile found")

    prefs = dict(profile.preferences or {})
    prefs.update({k: v for k, v in data.model_dump().items() if v is not None})
    profile.preferences = prefs
    profile.updated_at = datetime.utcnow()

    await db.commit()
    return {"preferences": prefs}


def _profile_out(p: FreelancerProfile) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "skills": p.skills,
        "experience_summary": p.experience_summary,
        "tone_description": p.tone_description,
        "sample_proposals": p.sample_proposals,
        "rate_min": float(p.rate_min) if p.rate_min else None,
        "rate_max": float(p.rate_max) if p.rate_max else None,
        "max_proposal_words": p.max_proposal_words,
        "preferences": p.preferences,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
