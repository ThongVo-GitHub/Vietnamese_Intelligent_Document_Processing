from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalysisResultRecord(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            name="uq_analysis_results_job_id",
        ),
        CheckConstraint(
            "processing_time_ms >= 0",
            name="ck_analysis_results_processing_time_non_negative",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dossier_id: Mapped[UUID] = mapped_column(
        ForeignKey("dossiers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    engine_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    processing_time_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )