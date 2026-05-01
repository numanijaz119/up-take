import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from src.models.job import Job, Detection
from src.models.audit import AuditLog

logger = logging.getLogger(__name__)

SOURCE_PRIORITY = {
    "api_polling": 3,
    "browser_channel": 2,
    "email_alert": 1,
}


class DeduplicationGateway:
    """
    Central hub for all detection channels.
    First detection triggers the pipeline;
    later detections from other channels only enrich the existing record.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        db_session_factory,
        on_new_job: Callable[[dict, "AsyncSession"], Awaitable[None]],
    ):
        self.redis = redis
        self.db = db_session_factory
        self._on_new_job = on_new_job

    async def process(self, job_data: dict) -> bool:
        """
        Process a detected job.
        Returns True if this was a new job that triggered the pipeline.
        """
        job_id = job_data.get("id")
        if not job_id:
            logger.debug("Received job data without ID — skipping")
            return False

        source = job_data.get("source", "unknown")
        cache_key = f"job:seen:{job_id}"

        is_new = not bool(await self.redis.exists(cache_key))

        async with self.db() as session:
            # Log every detection for channel analytics
            detection = Detection(
                upwork_job_id=job_id,
                source=source,
                is_new=is_new,
                detected_at=datetime.now(timezone.utc),
            )
            session.add(detection)

            if is_new:
                # Store job
                job = Job(
                    upwork_id=job_id,
                    title=job_data.get("title"),
                    description=job_data.get("description"),
                    budget=_parse_budget_field(job_data.get("budget")),
                    job_type=job_data.get("job_type") or job_data.get("jobType"),
                    experience_level=job_data.get("experience_level") or job_data.get("experienceLevel"),
                    duration=job_data.get("duration"),
                    skills=job_data.get("skills", []),
                    client_info={
                        "paymentVerified": job_data.get("payment_verified") or job_data.get("paymentVerified"),
                        "clientSpent": job_data.get("client_spent") or job_data.get("clientSpent"),
                        "clientRating": job_data.get("client_rating") or job_data.get("clientRating"),
                        "clientLocation": job_data.get("client_location") or job_data.get("clientLocation"),
                    },
                    proposals_count=job_data.get("proposals"),
                    url=job_data.get("url"),
                    posted_at=_parse_posted_time(job_data.get("posted_time") or job_data.get("postedTime")),
                    detected_at=datetime.now(timezone.utc),
                    detected_via=source,
                    raw_data=job_data,
                    status="new",
                )
                session.add(job)

                audit = AuditLog(
                    action="job_detected",
                    entity_type="job",
                    entity_id=job_id,
                    details={"source": source},
                )
                session.add(audit)

                await session.commit()
                # Mark seen in Redis only after successful DB commit
                await self.redis.set(cache_key, "1", ex=604800)
                await session.refresh(job)

                logger.info(f"New job detected: {job_id} via {source} — '{job_data.get('title', '?')}'")

                try:
                    await self._on_new_job(job_data, session)
                except Exception as e:
                    logger.error(f"Pipeline error for job {job_id}: {e}", exc_info=True)

                return True

            else:
                await self._maybe_enrich(job_id, job_data, source, session)
                await session.commit()
                return False

    async def _maybe_enrich(
        self, job_id: str, job_data: dict, source: str, session: AsyncSession
    ) -> None:
        """Enrich existing record if this source has better/more complete data."""
        new_priority = SOURCE_PRIORITY.get(source, 0)

        result = await session.execute(
            select(Job).where(Job.upwork_id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            return

        old_priority = SOURCE_PRIORITY.get(job.detected_via or "", 0)

        if new_priority > old_priority:
            updates: dict = {}
            if job_data.get("description") and not job.description:
                updates["description"] = job_data["description"]
            client_spent = job_data.get("client_spent") or job_data.get("clientSpent")
            if client_spent and not (job.client_info or {}).get("clientSpent"):
                client_info = dict(job.client_info or {})
                client_info["clientSpent"] = client_spent
                updates["client_info"] = client_info

            if updates:
                await session.execute(
                    update(Job).where(Job.upwork_id == job_id).values(**updates)
                )
                logger.debug(f"Enriched job {job_id} from {source}")


def _parse_posted_time(relative: str | None) -> str | None:
    """
    Convert Upwork relative string ('12 minutes ago', 'about 1 hour ago')
    to an ISO 8601 UTC datetime string with +00:00 suffix.
    Returns None for unrecognised formats so callers get null, not garbage.
    """
    if not relative:
        return None
    s = relative.strip().lower()
    now = datetime.now(timezone.utc)

    # re.search handles prefixes like "about", "Posted", etc.
    m = re.search(r'(\d+)\s+(second|minute|hour|day|week)s?\s+ago', s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {
            'second': timedelta(seconds=n),
            'minute': timedelta(minutes=n),
            'hour':   timedelta(hours=n),
            'day':    timedelta(days=n),
            'week':   timedelta(weeks=n),
        }[unit]
        return (now - delta).isoformat()

    if any(x in s for x in ('just now', 'moment', 'recently')):
        return now.isoformat()

    return None  # unrecognised — let caller show '—'


def _parse_budget_field(budget_raw) -> dict | None:
    if not budget_raw:
        return None
    if isinstance(budget_raw, dict):
        return budget_raw
    return {"raw": str(budget_raw)}
