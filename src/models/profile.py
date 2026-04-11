import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Text, JSON, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class FreelancerProfile(Base):
    __tablename__ = "freelancer_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    experience_summary: Mapped[str | None] = mapped_column(Text)
    tone_description: Mapped[str | None] = mapped_column(Text)
    sample_proposals: Mapped[list | None] = mapped_column(JSON)  # list of str
    rate_min: Mapped[float | None] = mapped_column(Numeric(10, 2))
    rate_max: Mapped[float | None] = mapped_column(Numeric(10, 2))
    max_proposal_words: Mapped[int] = mapped_column(Integer, default=200)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
