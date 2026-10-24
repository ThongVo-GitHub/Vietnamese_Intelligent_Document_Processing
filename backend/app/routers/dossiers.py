from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db_session
from app.models.dossier import Dossier
from app.models.processing_job import ProcessingJob
from app.models.source_file import SourceFile
from app.schemas.dossier import DossierCreate, DossierResponse
from app.schemas.ingestion import FileUploadResponse
from app.services.file_storage import store_file
from app.services.file_validation import detect_media_type
from collections import Counter
from typing import Literal
from sqlalchemy import select
from app.models.alert import Alert
from app.schemas.reconciliation import (
    AlertListResponse,
    AlertResponse,
    AlertStatusUpdate,
    ReconciliationResponse,
)
from app.services.reconciliation_engine import (
    run_reconciliation,
)
from datetime import datetime, timezone
from app.models.audit_event import AuditEvent
from app.schemas.search import DocumentSearchResponse
from app.services.document_search import (
    search_dossier_documents,
)

router = APIRouter(
    prefix="/dossiers",
    tags=["Dossiers"],
)

DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "",
    response_model=DossierResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dossier(
    payload: DossierCreate,
    session: DbSession,
) -> Dossier:
    dossier = Dossier(name=payload.name)

    session.add(dossier)
    session.commit()
    session.refresh(dossier)

    return dossier


@router.post(
    "/{dossier_id}/files",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    dossier_id: UUID,
    session: DbSession,
    file: UploadFile = File(...),
) -> FileUploadResponse:
    settings = get_settings()

    dossier = session.get(Dossier, dossier_id)
    if dossier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier not found",
        )

    try:
        content = await file.read(settings.max_upload_size_bytes + 1)
    finally:
        await file.close()

    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail="File exceeds the 10 MB limit",
        )

    media_type = detect_media_type(content)
    if media_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported or invalid file",
        )

    original_name = Path(file.filename or "").name
    if not original_name or len(original_name) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file name",
        )

    stored = store_file(
        content=content,
        media_type=media_type,
        dossier_id=dossier_id,
        upload_dir=settings.upload_dir,
    )

    try:
        source_file = SourceFile(
            dossier_id=dossier_id,
            original_name=original_name,
            storage_key=stored.storage_key,
            media_type=media_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
        )
        session.add(source_file)
        session.flush()

        job = ProcessingJob(
            dossier_id=dossier_id,
            source_file_id=source_file.id,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
    except SQLAlchemyError as exc:
        session.rollback()
        (settings.upload_dir / stored.storage_key).unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save upload",
        ) from exc

    return FileUploadResponse(
        dossier_id=dossier_id,
        source_file_id=source_file.id,
        job_id=job.id,
        original_name=source_file.original_name,
        media_type=source_file.media_type,
        size_bytes=source_file.size_bytes,
        sha256=source_file.sha256,
        job_status=job.status,
    )

@router.post(
    "/{dossier_id}/reconcile",
    response_model=ReconciliationResponse,
)
def reconcile_dossier(
    dossier_id: UUID,
    session: DbSession,
) -> ReconciliationResponse:
    dossier = session.get(Dossier, dossier_id)

    if dossier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier not found",
        )

    try:
        alerts = run_reconciliation(
            session=session,
            dossier_id=dossier_id,
        )

        severity_counts = dict(
            Counter(
                alert.severity
                for alert in alerts
            )
        )
        rule_counts = dict(
            Counter(
                alert.rule_code
                for alert in alerts
            )
        )
        alert_responses = [
            AlertResponse.model_validate(alert)
            for alert in alerts
        ]

        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Could not run reconciliation",
        ) from exc

    return ReconciliationResponse(
        dossier_id=dossier_id,
        alert_count=len(alert_responses),
        severity_counts=severity_counts,
        rule_counts=rule_counts,
        alerts=alert_responses,
    )


@router.get(
    "/{dossier_id}/alerts",
    response_model=AlertListResponse,
)
def list_dossier_alerts(
    dossier_id: UUID,
    session: DbSession,
    alert_status: Literal[
        "open",
        "resolved",
        "ignored",
    ]
    | None = Query(
        default=None,
        alias="status",
    ),
    severity: Literal[
        "info",
        "warning",
        "error",
    ]
    | None = Query(default=None),
) -> AlertListResponse:
    dossier = session.get(Dossier, dossier_id)

    if dossier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier not found",
        )

    statement = select(Alert).where(
        Alert.dossier_id == dossier_id
    )

    if alert_status is not None:
        statement = statement.where(
            Alert.status == alert_status
        )

    if severity is not None:
        statement = statement.where(
            Alert.severity == severity
        )

    statement = statement.order_by(
        Alert.created_at.desc()
    )
    alerts = list(
        session.scalars(statement).all()
    )

    return AlertListResponse(
        dossier_id=dossier_id,
        count=len(alerts),
        alerts=alerts,
    )

@router.patch(
    "/{dossier_id}/alerts/{alert_id}",
    response_model=AlertResponse,
)
def update_alert_status(
    dossier_id: UUID,
    alert_id: UUID,
    payload: AlertStatusUpdate,
    session: DbSession,
) -> Alert:
    dossier = session.get(Dossier, dossier_id)

    if dossier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier not found",
        )

    alert = session.get(Alert, alert_id)

    if (
        alert is None
        or alert.dossier_id != dossier_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    previous_status = alert.status
    alert.status = payload.status

    if payload.status == "open":
        alert.resolved_at = None
    else:
        alert.resolved_at = datetime.now(timezone.utc)

    session.add(
        AuditEvent(
            dossier_id=dossier_id,
            event_type="alert_status_changed",
            entity_type="alert",
            entity_id=alert.id,
            actor="user",
            details={
                "previous_status": previous_status,
                "new_status": payload.status,
            },
        )
    )

    try:
        session.commit()
        session.refresh(alert)
    except SQLAlchemyError as exc:
        session.rollback()

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Could not update alert",
        ) from exc

    return alert

@router.get(
    "/{dossier_id}/search",
    response_model=DocumentSearchResponse,
)
def search_documents(
    dossier_id: UUID,
    session: DbSession,
    q: str | None = Query(
        default=None,
        max_length=200,
    ),
    document_type: str | None = Query(
        default=None,
        max_length=32,
    ),
    field_name: str | None = Query(
        default=None,
        max_length=128,
    ),
    min_confidence: float = Query(
        default=0.0,
        ge=0.0,
        le=1.0,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
) -> DocumentSearchResponse:
    dossier = session.get(Dossier, dossier_id)

    if dossier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dossier not found",
        )

    normalized_query = (
        q.strip()
        if q is not None and q.strip()
        else None
    )
    normalized_document_type = (
        document_type.strip().lower()
        if document_type is not None
        and document_type.strip()
        else None
    )
    normalized_field_name = (
        field_name.strip().lower()
        if field_name is not None
        and field_name.strip()
        else None
    )

    return search_dossier_documents(
        session=session,
        dossier_id=dossier_id,
        query=normalized_query,
        document_type=normalized_document_type,
        field_name=normalized_field_name,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )