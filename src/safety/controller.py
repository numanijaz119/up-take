import logging
import random
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.models.proposal import Proposal
from src.config import settings

logger = logging.getLogger(__name__)


class SafetyController:
    """
    Central safety enforcement.
    Every proposal action passes through this controller.
    """

    def __init__(self, db_session_factory):
        self.db = db_session_factory

    async def can_send_proposal(self) -> tuple[bool, str]:
        now = datetime.now()
        s = settings

        # Active hours only
        if not (s.active_hours_start <= now.hour < s.active_hours_end):
            return False, f"Outside active hours ({s.active_hours_start}:00 – {s.active_hours_end}:00)"

        async with self.db() as db:
            # Daily limit
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            day_count = await db.scalar(
                select(func.count()).select_from(Proposal).where(
                    Proposal.status.in_(["approved", "submitted"]),
                    Proposal.approved_at >= today_start,
                )
            )
            if (day_count or 0) >= s.max_proposals_per_day:
                return False, f"Daily limit reached ({day_count}/{s.max_proposals_per_day})"

            # Hourly limit
            hour_ago = now - timedelta(hours=1)
            hour_count = await db.scalar(
                select(func.count()).select_from(Proposal).where(
                    Proposal.status.in_(["approved", "submitted"]),
                    Proposal.approved_at >= hour_ago,
                )
            )
            if (hour_count or 0) >= s.max_proposals_per_hour:
                return False, f"Hourly limit reached ({hour_count}/{s.max_proposals_per_hour})"

            # Minimum interval
            last_proposal = await db.scalar(
                select(Proposal.approved_at).where(
                    Proposal.status.in_(["approved", "submitted"]),
                    Proposal.approved_at.isnot(None),
                ).order_by(Proposal.approved_at.desc()).limit(1)
            )
            if last_proposal:
                elapsed = (now - last_proposal).total_seconds()
                min_interval = s.min_seconds_between_proposals
                if elapsed < min_interval:
                    wait = int(min_interval - elapsed)
                    return False, f"Wait {wait}s before next proposal"

        return True, "OK"

    async def check_proposal_uniqueness(self, new_text: str, db: AsyncSession) -> bool:
        """Ensure no two recent proposals share >30% word overlap."""
        result = await db.execute(
            select(Proposal.proposal_text).where(
                Proposal.status.in_(["approved", "submitted"])
            ).order_by(Proposal.created_at.desc()).limit(10)
        )
        recent_texts = [row[0] for row in result.fetchall()]

        new_words = set(new_text.lower().split())
        for existing in recent_texts:
            if not existing:
                continue
            existing_words = set(existing.lower().split())
            if not existing_words:
                continue
            overlap = len(new_words & existing_words) / max(len(new_words), len(existing_words))
            if overlap > settings.max_proposal_word_overlap:
                return False
        return True

    def natural_delay(self) -> float:
        """Random timing variation to appear human."""
        return max(2.0, random.gauss(5.0, 2.0))
