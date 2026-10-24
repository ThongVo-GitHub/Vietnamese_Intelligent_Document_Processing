from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExtractedFieldRecord(Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "field_index",
            name="uq_extracted_fields_document_index",
        ),
        CheckConstraint(
            "field_index >= 0",
            name="ck_extracted_fields_index_non_negative",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_extracted_fields_confidence_range",
        ),
        CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_extracted_fields_page_positive",
        ),
        CheckConstraint(
            "(x1 IS NULL AND y1 IS NULL AND x2 IS NULL AND y2 IS NULL) "
            "OR "
            "(x1 IS NOT NULL AND y1 IS NOT NULL "
            "AND x2 IS NOT NULL AND y2 IS NOT NULL)",
            name="ck_extracted_fields_bbox_complete",
        ),
        CheckConstraint(
            "x1 IS NULL OR "
            "(x1 >= 0 AND x1 <= 1 "
            "AND y1 >= 0 AND y1 <= 1 "
            "AND x2 >= 0 AND x2 <= 1 "
            "AND y2 >= 0 AND y2 <= 1)",
            name="ck_extracted_fields_bbox_normalized",
        ),
        CheckConstraint(
            "x1 IS NULL OR (x1 <= x2 AND y1 <= y2)",
            name="ck_extracted_fields_bbox_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    raw_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    normalized_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    page_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    x2: Mapped[float | None] = mapped_column(Float, nullable=True)
    y2: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    needs_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )