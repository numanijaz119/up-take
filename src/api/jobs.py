import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from src.database import get_db
from src.models.job import Job
from src.models.analysis import JobAnalysis

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


@router.get("/")
async def list_jobs(
    status: Optional[str] = None,
    min_score: Optional[int] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Job)
    if status:
        query = query.where(Job.status == status)

    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(desc(Job.detected_at)).offset(offset).limit(per_page)
    )
    jobs = result.scalars().all()

    out = []
    for job in jobs:
        ar = await db.execute(
            select(JobAnalysis).where(JobAnalysis.job_id == job.id)
            .order_by(desc(JobAnalysis.analyzed_at)).limit(1)
        )
        analysis = ar.scalar_one_or_none()
        if min_score and analysis and (analysis.opportunity_score or 0) < min_score:
            continue
        out.append({
            **_job_out(job),
            "opportunity_score": analysis.opportunity_score if analysis else None,
            "client_intent": analysis.client_intent if analysis else None,
            "should_propose": analysis.should_propose if analysis else None,
        })

    return {"jobs": out, "total": total, "page": page, "per_page": per_page}


@router.get("/stats")
async def job_stats(db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count()).select_from(Job)) or 0
    rows = await db.execute(select(Job.status, func.count()).group_by(Job.status))
    by_status = {r[0]: r[1] for r in rows.fetchall()}
    return {"total": total, "by_status": by_status}


@router.get("/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    # Try by upwork_id first
    result = await db.execute(select(Job).where(Job.upwork_id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        try:
            uid = uuid.UUID(job_id)
            result = await db.execute(select(Job).where(Job.id == uid))
            job = result.scalar_one_or_none()
        except ValueError:
            pass
    if not job:
        raise HTTPException(404, "Job not found")

    ar = await db.execute(
        select(JobAnalysis).where(JobAnalysis.job_id == job.id)
        .order_by(desc(JobAnalysis.analyzed_at)).limit(1)
    )
    analysis = ar.scalar_one_or_none()
    return {**_job_out(job), "analysis": _analysis_out(analysis) if analysis else None}


@router.post("/observed")
async def receive_observed_jobs(payload: dict):
    """Internal endpoint: receive jobs from any detection channel."""
    from src.app_state import get_gateway
    gateway = get_gateway()
    if not gateway:
        raise HTTPException(503, "Pipeline not initialized")

    jobs = payload.get("jobs", [])
    new_count = 0
    for job in jobs:
        is_new = await gateway.process(job)
        if is_new:
            new_count += 1
    return {"received": len(jobs), "new": new_count}


def _job_out(j: Job) -> dict:
    return {
        "id": str(j.id),
        "upwork_id": j.upwork_id,
        "title": j.title,
        "description": j.description,
        "budget": j.budget,
        "job_type": j.job_type,
        "experience_level": j.experience_level,
        "duration": j.duration,
        "skills": j.skills,
        "client_info": j.client_info,
        "proposals_count": j.proposals_count,
        "url": j.url,
        "posted_at": j.posted_at,
        "detected_at": j.detected_at.isoformat() if j.detected_at else None,
        "detected_via": j.detected_via,
        "status": j.status,
    }


def _analysis_out(a: JobAnalysis) -> dict:
    return {
        "id": str(a.id),
        "opportunity_score": a.opportunity_score,
        "relevance_score": a.relevance_score,
        "client_quality": a.client_quality,
        "key_requirements": a.key_requirements,
        "hidden_requirements": a.hidden_requirements,
        "matching_experience": a.matching_experience,
        "suggested_angle": a.suggested_angle,
        "key_selling_points": a.key_selling_points,
        "red_flags": a.red_flags,
        "client_intent": a.client_intent,
        "complexity_estimate": a.complexity_estimate,
        "should_propose": a.should_propose,
        "reasoning": a.reasoning,
        "analyzed_at": a.analyzed_at.isoformat() if a.analyzed_at else None,
    }
