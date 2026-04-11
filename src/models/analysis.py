import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Text, JSON, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class JobAnalysis(Base):
    __tablename__ = "job_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    freelancer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("freelancer_profiles.id"))
    opportunity_score: Mapped[int | None] = mapped_column(Integer, index=True)
    relevance_score: Mapped[int | None] = mapped_column(Integer)
    client_quality: Mapped[int | None] = mapped_column(Integer)
    key_requirements: Mapped[list | None] = mapped_column(JSON)
    hidden_requirements: Mapped[list | None] = mapped_column(JSON)
    matching_experience: Mapped[list | None] = mapped_column(JSON)
    suggested_angle: Mapped[str | None] = mapped_column(Text)
    key_selling_points: Mapped[list | None] = mapped_column(JSON)
    red_flags: Mapped[list | None] = mapped_column(JSON)
    client_intent: Mapped[str | None] = mapped_column(String(50))
    complexity_estimate: Mapped[str | None] = mapped_column(String(20))
    should_propose: Mapped[bool | None] = mapped_column(Boolean)
    reasoning: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["Job"] = relationship("Job", back_populates="analyses")
    proposal: Mapped["Proposal | None"] = relationship("Proposal", back_populates="analysis", uselist=False)
