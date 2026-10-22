from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.processing_job import ProcessingJob
from app.models.source_file import SourceFile
from app.schemas.common import AnalysisResult
from app.services.ai_engine import AIEngineClient


def claim_next_job(session: Session) -> ProcessingJob | None:
    statement: Select[tuple[ProcessingJob]] = (
        select(ProcessingJob)
        .where(ProcessingJob.status == "queued")
        .order_by(
            ProcessingJob.created_at,
            ProcessingJob.id,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )

    job = session.scalar(statement)

    if job is None:
        return None

    job.status = "running"
    job.current_step = "ai_analysis"
    job.progress = 10
    job.started_at = datetime.now(timezone.utc)
    job.attempts += 1

    session.commit()
    session.refresh(job)

    return job


def process_job(
    *,
    session: Session,
    job: ProcessingJob,
    ai_client: AIEngineClient,
    upload_dir: Path,
) -> AnalysisResult:
    if job.status != "running":
        raise ValueError("Job must be running before processing")

    try:
        if job.source_file_id is None:
            raise ValueError("Job does not have a source file")

        source_file = session.get(SourceFile, job.source_file_id)
        if source_file is None:
            raise ValueError("Source file not found")

        result = ai_client.analyze_document(
            file_path=upload_dir / source_file.storage_key,
            media_type=source_file.media_type,
        )
    except Exception as exc:
        job.status = "failed"
        job.current_step = "failed"
        job.error_message = str(exc)
        job.finished_at = datetime.now(timezone.utc)

        session.commit()
        raise

    job.status = "succeeded"
    job.current_step = "completed"
    job.progress = 100
    job.error_message = None
    job.finished_at = datetime.now(timezone.utc)

    session.commit()
    session.refresh(job)

    return result