from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, text

from src.database import get_db
from src.models.job import Job, Detection, BrowserSession
from src.models.proposal import Proposal

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


@router.get("/pipeline")
async def pipeline_analytics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Conversion funnel: detected → filtered → analyzed → proposed → submitted → hired."""
    since = text(f"NOW() - INTERVAL '{days} days'")

    total = await db.scalar(
        select(func.count()).select_from(Job).where(Job.detected_at >= since)
    ) or 0
    filtered_out = await db.scalar(
        select(func.count()).select_from(Job).where(
            Job.detected_at >= since, Job.status == "filtered_out"
        )
    ) or 0
    analyzed = await db.scalar(
        select(func.count()).select_from(Job).where(
            Job.detected_at >= since,
            Job.status.in_(["analyzed", "proposed", "submitted", "skipped"])
        )
    ) or 0
    proposed = await db.scalar(
        select(func.count()).select_from(Job).where(
            Job.detected_at >= since, Job.status.in_(["proposed", "submitted"])
        )
    ) or 0
    submitted = await db.scalar(
        select(func.count()).select_from(Job).where(
            Job.detected_at >= since, Job.status == "submitted"
        )
    ) or 0
    hired = await db.scalar(
        select(func.count()).select_from(Proposal).where(
            Proposal.hired == True, Proposal.created_at >= since
        )
    ) or 0

    passed = total - filtered_out
    return {
        "period_days": days,
        "funnel": {
            "detected": total,
            "passed_filter": passed,
            "analyzed": analyzed,
            "proposed": proposed,
            "submitted": submitted,
            "hired": hired,
        },
        "rates": {
            "filter_pass_rate": round(passed / total * 100, 1) if total else 0,
            "proposal_rate": round(proposed / analyzed * 100, 1) if analyzed else 0,
            "submission_rate": round(submitted / proposed * 100, 1) if proposed else 0,
            "hire_rate": round(hired / submitted * 100, 1) if submitted else 0,
        },
    }


@router.get("/channels")
async def channel_analytics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    since = text(f"NOW() - INTERVAL '{days} days'")
    result = await db.execute(
        select(
            Detection.source,
            func.count().label("total"),
            func.count().filter(Detection.is_new == True).label("new_jobs"),
        )
        .where(Detection.detected_at >= since)
        .group_by(Detection.source)
    )
    rows = result.fetchall()
    return {
        "period_days": days,
        "channels": [
            {"source": r[0], "total_detections": r[1], "new_jobs": r[2] or 0}
            for r in rows
        ],
    }


@router.get("/proposals")
async def proposal_analytics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    since = text(f"NOW() - INTERVAL '{days} days'")
    total = await db.scalar(
        select(func.count()).select_from(Proposal).where(Proposal.created_at >= since)
    ) or 0
    avg_quality = await db.scalar(
        select(func.avg(Proposal.quality_score)).where(Proposal.created_at >= since)
    )
    approved = await db.scalar(
        select(func.count()).select_from(Proposal).where(
            Proposal.created_at >= since,
            Proposal.status.in_(["approved", "submitted"])
        )
    ) or 0
    hired = await db.scalar(
        select(func.count()).select_from(Proposal).where(
            Proposal.created_at >= since, Proposal.hired == True
        )
    ) or 0
    sessions = await db.scalar(select(func.count()).select_from(BrowserSession)) or 0
    total_jobs_found = await db.scalar(select(func.sum(BrowserSession.jobs_found))) or 0

    return {
        "period_days": days,
        "proposals": {
            "total_generated": total,
            "approved": approved,
            "hired": hired,
            "avg_quality_score": round(float(avg_quality), 2) if avg_quality else None,
        },
        "browser_sessions": {
            "total": sessions,
            "total_jobs_found": int(total_jobs_found),
            "avg_jobs_per_session": round(total_jobs_found / sessions, 1) if sessions else 0,
        },
    }


@router.get("/sessions")
async def session_list(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total = await db.scalar(select(func.count()).select_from(BrowserSession)) or 0
    offset = (page - 1) * per_page
    result = await db.execute(
        select(BrowserSession)
        .order_by(desc(BrowserSession.created_at))
        .offset(offset)
        .limit(per_page)
    )
    sessions = result.scalars().all()
    return {
        "sessions": [
            {
                "id": str(s.id),
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "duration_s": s.duration_s,
                "jobs_found": s.jobs_found,
                "searches": s.searches,
                "error": s.error,
            }
            for s in sessions
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
