import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, update

from src.database import get_db
from src.models.proposal import Proposal
from src.models.job import Job
from src.models.audit import AuditLog

router = APIRouter(prefix="/api/v1/proposals", tags=["Proposals"])


class ApproveRequest(BaseModel):
    edited_text: Optional[str] = None


class OutcomeRequest(BaseModel):
    client_responded: bool
    hired: bool = False


@router.get("/")
async def list_proposals(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Proposal)
    if status:
        query = query.where(Proposal.status == status)

    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * per_page
    result = await db.execute(
        query.order_by(desc(Proposal.created_at)).offset(offset).limit(per_page)
    )
    proposals = result.scalars().all()

    out = []
    for p in proposals:
        jr = await db.execute(select(Job).where(Job.id == p.job_id))
        job = jr.scalar_one_or_none()
        out.append({
            **_proposal_out(p),
            "job_title": job.title if job else None,
            "job_url": job.url if job else None,
        })
    return {"proposals": out, "total": total, "page": page, "per_page": per_page}


@router.get("/{proposal_id}")
async def get_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    p = await _get_proposal(proposal_id, db)
    jr = await db.execute(select(Job).where(Job.id == p.job_id))
    job = jr.scalar_one_or_none()
    return {
        **_proposal_out(p),
        "job_title": job.title if job else None,
        "job_url": job.url if job else None,
    }


@router.post("/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    request: ApproveRequest,
    db: AsyncSession = Depends(get_db),
):
    from src.app_state import get_safety
    safety = get_safety()
    if safety:
        can_send, reason = await safety.can_send_proposal()
        if not can_send:
            raise HTTPException(429, f"Safety limit: {reason}")

    p = await _get_proposal(proposal_id, db)
    if p.status not in ("draft", "approved"):
        raise HTTPException(400, f"Cannot approve a proposal with status '{p.status}'")

    final_text = request.edited_text or p.proposal_text
    await db.execute(
        update(Proposal).where(Proposal.id == p.id).values(
            status="approved",
            proposal_text=final_text,
            approved_at=datetime.utcnow(),
        )
    )
    db.add(AuditLog(
        action="proposal_approved",
        entity_type="proposal",
        entity_id=str(p.id),
        details={"edited": request.edited_text is not None},
    ))
    await db.commit()

    jr = await db.execute(select(Job).where(Job.id == p.job_id))
    job = jr.scalar_one_or_none()

    return {
        "status": "approved",
        "proposal_text": final_text,
        "job_url": job.url if job else None,
        "message": "Proposal approved. Copy the text above and paste it into Upwork.",
    }


@router.post("/{proposal_id}/skip")
async def skip_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    p = await _get_proposal(proposal_id, db)
    await db.execute(update(Proposal).where(Proposal.id == p.id).values(status="skipped"))
    db.add(AuditLog(action="proposal_skipped", entity_type="proposal", entity_id=str(p.id), details={}))
    await db.commit()
    return {"status": "skipped"}


@router.post("/{proposal_id}/submitted")
async def mark_submitted(proposal_id: str, db: AsyncSession = Depends(get_db)):
    p = await _get_proposal(proposal_id, db)
    await db.execute(
        update(Proposal).where(Proposal.id == p.id).values(
            status="submitted", submitted_at=datetime.utcnow()
        )
    )
    await db.execute(update(Job).where(Job.id == p.job_id).values(status="submitted"))
    db.add(AuditLog(action="proposal_submitted", entity_type="proposal", entity_id=str(p.id), details={}))
    await db.commit()
    return {"status": "submitted"}


@router.put("/{proposal_id}/outcome")
async def record_outcome(proposal_id: str, request: OutcomeRequest, db: AsyncSession = Depends(get_db)):
    p = await _get_proposal(proposal_id, db)
    await db.execute(
        update(Proposal).where(Proposal.id == p.id).values(
            client_responded=request.client_responded,
            hired=request.hired,
        )
    )
    db.add(AuditLog(
        action="proposal_outcome",
        entity_type="proposal",
        entity_id=str(p.id),
        details={"client_responded": request.client_responded, "hired": request.hired},
    ))
    await db.commit()
    return {"status": "updated"}


async def _get_proposal(proposal_id: str, db: AsyncSession) -> Proposal:
    try:
        pid = uuid.UUID(proposal_id)
    except ValueError:
        raise HTTPException(400, "Invalid proposal ID format")
    result = await db.execute(select(Proposal).where(Proposal.id == pid))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Proposal not found")
    return p


def _proposal_out(p: Proposal) -> dict:
    return {
        "id": str(p.id),
        "job_id": str(p.job_id),
        "analysis_id": str(p.analysis_id) if p.analysis_id else None,
        "proposal_text": p.proposal_text,
        "quality_score": float(p.quality_score) if p.quality_score else None,
        "quality_detail": p.quality_detail,
        "word_count": p.word_count,
        "status": p.status,
        "approved_at": p.approved_at.isoformat() if p.approved_at else None,
        "submitted_at": p.submitted_at.isoformat() if p.submitted_at else None,
        "client_responded": p.client_responded,
        "hired": p.hired,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
