from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "analysis_result_id",
            "document_index",
            name="uq_documents_result_index",
        ),
        CheckConstraint(
            "document_index >= 0",
            name="ck_documents_index_non_negative",
        ),
        CheckConstraint(
            "classification_confidence >= 0 "
            "AND classification_confidence <= 1",
            name="ck_documents_confidence_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )
    analysis_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    classification_confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    page_numbers: Mapped[list[int]] = mapped_column(
        JSON,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )