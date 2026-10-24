from enum import StrEnum
from pydantic import BaseModel, Field

class DocumentType(StrEnum):
    CONTRACT = "contract"
    INVOICE = "invoice"
    PAYMENT_REQUEST = "payment_request"
    UNKNOWN = "unknown"

class BoundingBox(BaseModel):
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1)
    y2: float = Field(ge=0, le=1)

class OcrBlock(BaseModel):
    page: int = Field(ge=1)
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    bbox: BoundingBox

class ExtractedField(BaseModel):
    name: str = Field(min_length=1)
    raw_value: str | None = None
    normalized_value: str | None = None
    confidence: float = Field(ge=0, le=1)
    page: int | None = Field(default=None, ge=1)
    bbox: BoundingBox | None = None
    evidence_text: str | None = None
    source: str = "unknown"
    needs_review: bool = False

class AnalyzedDocument(BaseModel):
    document_type: DocumentType
    classification_confidence: float = Field(ge=0, le=1)
    pages: list[int] = Field(min_length=1)
    fields: list[ExtractedField] = Field(default_factory=list)
    ocr_blocks: list[OcrBlock] = Field(default_factory=list)

class AnalysisResult(BaseModel):
    documents: list[AnalyzedDocument] = Field(default_factory=list)
    engine_version: str = Field(min_length=1)
    processing_time_ms: int = Field(ge=0)