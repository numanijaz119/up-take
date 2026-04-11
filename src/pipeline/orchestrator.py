import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from src.models.job import Job
from src.models.analysis import JobAnalysis
from src.models.proposal import Proposal
from src.models.profile import FreelancerProfile
from src.models.audit import AuditLog
from src.pipeline.filter import QuickFilter, FilterPreferences
from src.pipeline.analyzer import DeepAnalyzer
from src.pipeline.generator import ProposalGenerator
from src.config import settings

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Orchestrates the full pipeline:
    job_data → quick filter → deep analysis → proposal generation
    """

    def __init__(
        self,
        db_session_factory,
        on_proposal_ready=None,
    ):
        self.db = db_session_factory
        self._on_proposal_ready = on_proposal_ready
        self._analyzer = DeepAnalyzer()
        self._generator = ProposalGenerator()

    async def process(self, job_data: dict, session: AsyncSession | None = None) -> None:
        """Entry point called by the dedup gateway for each new job."""
        job_id = job_data.get("id")

        async with self.db() as db:
            # Load the job from DB
            result = await db.execute(select(Job).where(Job.upwork_id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                logger.warning(f"Job {job_id} not found in DB during pipeline")
                return

            # Load active profile
            profile = await self._load_active_profile(db)
            if not profile:
                logger.warning("No active freelancer profile — skipping pipeline")
                return

            profile_dict = self._profile_to_dict(profile)

            # ── Step 1: Quick Filter ─────────────────────────────────────────
            prefs = self._build_filter_prefs(profile)
            quick_filter = QuickFilter(prefs)
            passes, reason = quick_filter.evaluate(job_data)

            if not passes:
                await self._update_job_status(db, job.id, "filtered_out")
                await self._log(db, "job_filtered_out", "job", str(job.id), {"reason": reason})
                await db.commit()
                logger.info(f"Job {job_id} filtered out: {reason}")
                return

            # ── Step 2: Deep Analysis ────────────────────────────────────────
            await self._update_job_status(db, job.id, "analyzing")
            await db.commit()

            try:
                analysis_result = await self._analyzer.analyze(job_data, profile_dict)
            except Exception as e:
                logger.error(f"Analysis failed for {job_id}: {e}")
                await self._update_job_status(db, job.id, "new")
                return

            analysis = JobAnalysis(
                job_id=job.id,
                freelancer_id=profile.id,
                opportunity_score=analysis_result.get("opportunity_score"),
                relevance_score=analysis_result.get("relevance_score"),
                client_quality=analysis_result.get("client_quality"),
                key_requirements=analysis_result.get("key_requirements"),
                hidden_requirements=analysis_result.get("hidden_requirements"),
                matching_experience=analysis_result.get("matching_experience"),
                suggested_angle=analysis_result.get("suggested_angle"),
                key_selling_points=analysis_result.get("key_selling_points"),
                red_flags=analysis_result.get("red_flags"),
                client_intent=analysis_result.get("client_intent"),
                complexity_estimate=analysis_result.get("complexity_estimate"),
                should_propose=analysis_result.get("should_propose"),
                reasoning=analysis_result.get("reasoning"),
            )
            db.add(analysis)
            await self._log(db, "job_analyzed", "job", str(job.id), {
                "score": analysis_result.get("opportunity_score"),
                "should_propose": analysis_result.get("should_propose"),
            })

            if not analysis_result.get("should_propose"):
                await self._update_job_status(db, job.id, "skipped")
                await db.commit()
                logger.info(f"Job {job_id} skipped (score={analysis_result.get('opportunity_score')}): {analysis_result.get('reasoning')}")
                return

            await db.commit()
            await db.refresh(analysis)

            # ── Step 3: Proposal Generation ──────────────────────────────────
            try:
                proposal_result = await self._generator.generate(job_data, analysis_result, profile_dict)
            except Exception as e:
                logger.error(f"Proposal generation failed for {job_id}: {e}")
                await self._update_job_status(db, job.id, "analyzed")
                await db.commit()
                return

            proposal = Proposal(
                job_id=job.id,
                analysis_id=analysis.id,
                freelancer_id=profile.id,
                proposal_text=proposal_result["text"],
                quality_score=proposal_result["quality_score"],
                quality_detail=proposal_result["quality_detail"],
                word_count=proposal_result["word_count"],
                status="draft",
            )
            db.add(proposal)
            await self._update_job_status(db, job.id, "proposed")
            await self._log(db, "proposal_generated", "proposal", str(job.id), {
                "quality": proposal_result["quality_score"],
                "words": proposal_result["word_count"],
            })
            await db.commit()
            await db.refresh(proposal)

            logger.info(
                f"Proposal ready for {job_id}: quality={proposal_result['quality_score']:.1f}, "
                f"words={proposal_result['word_count']}"
            )

            # Notify
            if self._on_proposal_ready:
                try:
                    await self._on_proposal_ready({
                        "job": job_data,
                        "analysis": analysis_result,
                        "proposal": proposal_result,
                        "proposal_id": str(proposal.id),
                        "job_db_id": str(job.id),
                    })
                except Exception as e:
                    logger.error(f"Notification callback error: {e}")

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _load_active_profile(self, db: AsyncSession) -> FreelancerProfile | None:
        result = await db.execute(
            select(FreelancerProfile).where(FreelancerProfile.is_active == True).limit(1)
        )
        return result.scalar_one_or_none()

    def _profile_to_dict(self, profile: FreelancerProfile) -> dict:
        return {
            "id": str(profile.id),
            "name": profile.name,
            "skills": profile.skills or [],
            "experience_summary": profile.experience_summary or "",
            "tone_description": profile.tone_description or "Professional, concise, confident.",
            "sample_proposals": profile.sample_proposals or [],
            "rate_min": float(profile.rate_min) if profile.rate_min else None,
            "rate_max": float(profile.rate_max) if profile.rate_max else None,
            "max_proposal_words": profile.max_proposal_words,
            "preferences": profile.preferences or {},
        }

    def _build_filter_prefs(self, profile: FreelancerProfile) -> FilterPreferences:
        prefs_data = profile.preferences or {}
        return FilterPreferences(
            skills=profile.skills or [],
            min_skill_overlap=prefs_data.get("min_skill_overlap", 1),
            min_budget=prefs_data.get("min_budget", 0),
            require_payment_verified=prefs_data.get("require_payment_verified", True),
            min_client_spent=prefs_data.get("min_client_spent", 0),
            max_existing_proposals=prefs_data.get("max_existing_proposals", 50),
            blacklist_keywords=prefs_data.get("blacklist_keywords", []),
        )

    async def _update_job_status(self, db: AsyncSession, job_id, status: str) -> None:
        await db.execute(update(Job).where(Job.id == job_id).values(status=status))

    async def _log(self, db: AsyncSession, action: str, entity_type: str, entity_id: str, details: dict) -> None:
        db.add(AuditLog(action=action, entity_type=entity_type, entity_id=entity_id, details=details))
