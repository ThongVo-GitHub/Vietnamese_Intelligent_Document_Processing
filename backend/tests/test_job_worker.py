from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.dossier import Dossier
from app.models.processing_job import ProcessingJob
from app.models.source_file import SourceFile
from app.schemas.common import AnalysisResult
from app.services.ai_engine import MockAIEngineClient
from app.services.job_worker import claim_next_job, process_job


@pytest.fixture
def worker_context(
    tmp_path: Path,
) -> Iterator[tuple[Session, Path]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    testing_session_local = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    upload_dir = tmp_path / "uploads"

    try:
        with testing_session_local() as session:
            yield session, upload_dir
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_queued_job(
    session: Session,
    upload_dir: Path,
) -> ProcessingJob:
    dossier = Dossier(name="Worker test")
    session.add(dossier)
    session.flush()

    content = b"%PDF-1.7 worker test"
    storage_key = f"{dossier.id}/sample.pdf"
    file_path = upload_dir / storage_key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)

    source_file = SourceFile(
        dossier_id=dossier.id,
        original_name="sample.pdf",
        storage_key=storage_key,
        media_type="application/pdf",
        size_bytes=len(content),
        sha256="a" * 64,
    )
    session.add(source_file)
    session.flush()

    job = ProcessingJob(
        dossier_id=dossier.id,
        source_file_id=source_file.id,
    )
    session.add(job)
    session.commit()

    return job


def test_worker_processes_queued_job_successfully(
    worker_context: tuple[Session, Path],
) -> None:
    session, upload_dir = worker_context
    queued_job = create_queued_job(session, upload_dir)

    claimed_job = claim_next_job(session)

    assert claimed_job is not None
    assert claimed_job.id == queued_job.id
    assert claimed_job.status == "running"
    assert claimed_job.progress == 10
    assert claimed_job.attempts == 1
    assert claimed_job.started_at is not None

    result = process_job(
        session=session,
        job=claimed_job,
        ai_client=MockAIEngineClient(),
        upload_dir=upload_dir,
    )

    assert result.engine_version == "mock-0.1.0"
    assert claimed_job.status == "succeeded"
    assert claimed_job.current_step == "completed"
    assert claimed_job.progress == 100
    assert claimed_job.error_message is None
    assert claimed_job.finished_at is not None


class FailingAIEngineClient:
    def analyze_document(
        self,
        *,
        file_path: Path,
        media_type: str,
    ) -> AnalysisResult:
        raise RuntimeError("AI unavailable")


def test_worker_marks_job_failed_when_ai_raises(
    worker_context: tuple[Session, Path],
) -> None:
    session, upload_dir = worker_context
    create_queued_job(session, upload_dir)
    claimed_job = claim_next_job(session)

    assert claimed_job is not None

    with pytest.raises(RuntimeError, match="AI unavailable"):
        process_job(
            session=session,
            job=claimed_job,
            ai_client=FailingAIEngineClient(),
            upload_dir=upload_dir,
        )

    session.refresh(claimed_job)

    assert claimed_job.status == "failed"
    assert claimed_job.current_step == "failed"
    assert claimed_job.error_message == "AI unavailable"
    assert claimed_job.finished_at is not None


def test_claim_next_job_returns_none_when_queue_is_empty(
    worker_context: tuple[Session, Path],
) -> None:
    session, _ = worker_context

    assert claim_next_job(session) is None