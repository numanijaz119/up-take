import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upwork_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    budget: Mapped[dict | None] = mapped_column(JSON)
    job_type: Mapped[str | None] = mapped_column(String(50))
    experience_level: Mapped[str | None] = mapped_column(String(100))
    duration: Mapped[str | None] = mapped_column(String(100))
    skills: Mapped[list | None] = mapped_column(JSON)
    client_info: Mapped[dict | None] = mapped_column(JSON)
    connects_required: Mapped[int | None] = mapped_column(Integer)
    proposals_count: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[str | None] = mapped_column(String(100))
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    detected_via: Mapped[str | None] = mapped_column(String(50))
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50), default="new", index=True)

    analyses: Mapped[list["JobAnalysis"]] = relationship("JobAnalysis", back_populates="job", cascade="all, delete-orphan")
    proposals: Mapped[list["Proposal"]] = relationship("Proposal", back_populates="job", cascade="all, delete-orphan")
    detections: Mapped[list["Detection"]] = relationship(
        "Detection",
        primaryjoin="Job.upwork_id == foreign(Detection.upwork_job_id)",
        back_populates="job_record",
        cascade="all, delete-orphan",
    )


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upwork_job_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    is_new: Mapped[bool | None] = mapped_column(Boolean)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job_record: Mapped["Job | None"] = relationship(
        "Job",
        primaryjoin="foreign(Detection.upwork_job_id) == Job.upwork_id",
        back_populates="detections",
    )


class BrowserSession(Base):
    __tablename__ = "browser_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    searches: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
