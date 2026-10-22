from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models.processing_job import ProcessingJob
from app.schemas.ingestion import ProcessingJobResponse


router = APIRouter(
    prefix="/jobs",
    tags=["Processing Jobs"],
)

DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/{job_id}",
    response_model=ProcessingJobResponse,
)
def get_processing_job(
    job_id: UUID,
    session: DbSession,
) -> ProcessingJob:
    job = session.get(ProcessingJob, job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processing job not found",
        )

    return job