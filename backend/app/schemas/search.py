from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class SearchMatch(BaseModel):
    source: Literal[
        "extracted_field",
        "ocr_block",
    ]
    field_name: str | None
    text: str
    page_number: int | None
    confidence: float


class DocumentSearchResult(BaseModel):
    document_id: UUID
    source_file_id: UUID
    original_name: str
    document_type: str
    classification_confidence: float
    page_numbers: list[int]
    created_at: datetime
    matches: list[SearchMatch]


class DocumentSearchResponse(BaseModel):
    query: str | None
    document_type: str | None
    field_name: str | None
    count: int
    limit: int
    offset: int
    results: list[DocumentSearchResult]