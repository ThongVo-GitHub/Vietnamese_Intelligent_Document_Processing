from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from app.schemas.common import DocumentType


class DocumentLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dossier_id: UUID
    source_document_id: UUID
    target_document_id: UUID
    relation_type: str
    confidence: float
    matched_by: str
    created_at: datetime


class DossierCompletenessResponse(BaseModel):
    dossier_id: UUID
    status: Literal[
        "incomplete",
        "ready"
    ]
    required_document_types: list[DocumentType]
    present_document_types: list[DocumentType]
    missing_document_types: list[DocumentType]
    can_reconcile: bool


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dossier_id: UUID
    rule_code: str
    severity: str
    status: str
    message: str
    source_document_id: UUID | None
    target_document_id: UUID | None
    field_name: str | None
    expected_value: str | None
    actual_value: str | None
    details: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None


class ReconciliationResponse(BaseModel):
    dossier_id: UUID
    alert_count: int
    severity_counts: dict[str, int]
    rule_counts: dict[str, int]
    alerts: list[AlertResponse]


class AlertListResponse(BaseModel):
    dossier_id: UUID
    count: int
    alerts: list[AlertResponse]


class AlertStatusUpdate(BaseModel):
    status: Literal[
        "open",
        "resolved",
        "ignored",
    ]