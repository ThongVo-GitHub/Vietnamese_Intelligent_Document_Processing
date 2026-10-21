from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OcrBlock(Base):
    __tablename__ = "ocr_blocks"
    __table_args__ = (
        UniqueConstraint(
            "page_id",
            "block_index",
            name="uq_ocr_blocks_page_block_index",
        ),
        CheckConstraint(
            "block_index >= 0",
            name="ck_ocr_blocks_block_index_non_negative",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ocr_blocks_confidence_range",
        ),
        CheckConstraint(
            "x1 >= 0 AND x1 <= 1 AND "
            "y1 >= 0 AND y1 <= 1 AND "
            "x2 >= 0 AND x2 <= 1 AND "
            "y2 >= 0 AND y2 <= 1",
            name="ck_ocr_blocks_bbox_normalized",
        ),
        CheckConstraint(
            "x1 <= x2 AND y1 <= y2",
            name="ck_ocr_blocks_bbox_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )
    page_id: Mapped[UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    x1: Mapped[float] = mapped_column(Float, nullable=False)
    y1: Mapped[float] = mapped_column(Float, nullable=False)
    x2: Mapped[float] = mapped_column(Float, nullable=False)
    y2: Mapped[float] = mapped_column(Float, nullable=False)
    block_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="text",
        server_default="text",
    )
    engine: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )