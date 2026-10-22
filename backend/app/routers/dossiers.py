from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
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
