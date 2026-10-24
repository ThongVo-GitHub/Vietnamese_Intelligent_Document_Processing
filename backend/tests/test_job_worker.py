from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.dossier import Dossier
from app.models.processing_job import ProcessingJob
from app.models.source_file import SourceFile
from app.schemas.common import (
    AnalysisResult,
    AnalyzedDocument,
    BoundingBox,
    DocumentType,
    ExtractedField,
    OcrBlock as OcrBlockSchema,
)
from app.services.ai_engine import MockAIEngineClient
from app.services.job_worker import claim_next_job, process_job
from app.models.analysis_result import AnalysisResultRecord
from app.models.document import Document as DocumentRecord
from app.models.extracted_field import ExtractedFieldRecord
from app.models.ocr_block import OcrBlock as OcrBlockRecord
from app.models.page import Page
from app.services.analysis_results import load_analysis_result

from fastapi.testclient import TestClient

from app.database import get_db_session
from app.main import app

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


class DetailedAIEngineClient:
    def analyze_document(
        self,
        *,
        file_path: Path,
        media_type: str,
    ) -> AnalysisResult:
        assert file_path.is_file()
        assert media_type == "application/pdf"

        bbox = BoundingBox(
            x1=0.1,
            y1=0.2,
            x2=0.8,
            y2=0.3,
        )

        return AnalysisResult(
            documents=[
                AnalyzedDocument(
                    document_type=DocumentType.INVOICE,
                    classification_confidence=0.97,
                    pages=[1],
                    fields=[
                        ExtractedField(
                            name="invoice_number",
                            raw_value="HD-001",
                            normalized_value="HD-001",
                            confidence=0.95,
                            page=1,
                            bbox=bbox,
                            evidence_text="Số hóa đơn HD-001",
                            source="mock",
                        )
                    ],
                    ocr_blocks=[
                        OcrBlockSchema(
                            page=1,
                            text="Số hóa đơn HD-001",
                            confidence=0.99,
                            bbox=bbox,
                        )
                    ],
                )
            ],
            engine_version="test-engine-1.0",
            processing_time_ms=42,
        )


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

def test_worker_persists_detailed_analysis_result(
    worker_context: tuple[Session, Path],
) -> None:
    session, upload_dir = worker_context
    queued_job = create_queued_job(session, upload_dir)
    claimed_job = claim_next_job(session)

    assert claimed_job is not None

    expected_result = process_job(
        session=session,
        job=claimed_job,
        ai_client=DetailedAIEngineClient(),
        upload_dir=upload_dir,
    )

    result_record = session.scalar(
        select(AnalysisResultRecord).where(
            AnalysisResultRecord.job_id == claimed_job.id
        )
    )
    assert result_record is not None
    assert result_record.engine_version == "test-engine-1.0"
    assert result_record.processing_time_ms == 42

    document_record = session.scalar(
        select(DocumentRecord).where(
            DocumentRecord.analysis_result_id == result_record.id
        )
    )
    assert document_record is not None
    assert document_record.document_type == "invoice"
    assert document_record.page_numbers == [1]

    field_record = session.scalar(
        select(ExtractedFieldRecord).where(
            ExtractedFieldRecord.document_id == document_record.id
        )
    )
    assert field_record is not None
    assert field_record.name == "invoice_number"
    assert field_record.normalized_value == "HD-001"
    assert field_record.x1 == 0.1

    page_record = session.scalar(
        select(Page).where(
            Page.source_file_id == queued_job.source_file_id,
            Page.page_number == 1,
        )
    )
    assert page_record is not None

    block_record = session.scalar(
        select(OcrBlockRecord).where(
            OcrBlockRecord.page_id == page_record.id
        )
    )
    assert block_record is not None
    assert block_record.text == "Số hóa đơn HD-001"
    assert block_record.engine == "test-engine-1.0"

    source_file = session.get(SourceFile, queued_job.source_file_id)
    assert source_file is not None
    assert source_file.page_count == 1

    loaded_result = load_analysis_result(
        session=session,
        job_id=claimed_job.id,
    )

    assert loaded_result is not None
    assert loaded_result.model_dump(mode="json") == (
        expected_result.model_dump(mode="json")
    )

    def override_get_db_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db_session] = (
        override_get_db_session
    )

    try:
        with TestClient(app) as client:
            response = client.get(
                f"/jobs/{claimed_job.id}/result"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == expected_result.model_dump(
        mode="json"
    )