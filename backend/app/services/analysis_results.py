from sqlalchemy import func, select
from sqlalchemy.orm import Session
from uuid import UUID

from app.models.analysis_result import AnalysisResultRecord
from app.models.document import Document as DocumentRecord
from app.models.extracted_field import ExtractedFieldRecord
from app.models.processing_job import ProcessingJob
from app.schemas.common import (
    AnalysisResult,
    AnalyzedDocument,
    BoundingBox,
    ExtractedField,
    OcrBlock,
)
from app.models.ocr_block import OcrBlock as OcrBlockRecord
from app.models.page import Page
from app.models.source_file import SourceFile


def _save_ocr_content(
    *,
    session: Session,
    source_file_id: UUID,
    result: AnalysisResult,
) -> None:
    page_records: dict[int, Page] = {}
    next_block_indexes: dict[int, int] = {}

    def get_or_create_page(page_number: int) -> Page:
        cached_page = page_records.get(page_number)
        if cached_page is not None:
            return cached_page

        page_record = session.scalar(
            select(Page).where(
                Page.source_file_id == source_file_id,
                Page.page_number == page_number,
            )
        )

        if page_record is None:
            page_record = Page(
                source_file_id=source_file_id,
                page_number=page_number,
            )
            session.add(page_record)
            session.flush()

        maximum_index = session.scalar(
            select(func.max(OcrBlockRecord.block_index)).where(
                OcrBlockRecord.page_id == page_record.id,
            )
        )

        page_records[page_number] = page_record
        next_block_indexes[page_number] = (
            0 if maximum_index is None else maximum_index + 1
        )

        return page_record

    for analyzed_document in result.documents:
        for page_number in analyzed_document.pages:
            get_or_create_page(page_number)

        for block in analyzed_document.ocr_blocks:
            page_record = get_or_create_page(block.page)
            block_index = next_block_indexes[block.page]

            session.add(
                OcrBlockRecord(
                    page_id=page_record.id,
                    block_index=block_index,
                    text=block.text,
                    confidence=block.confidence,
                    x1=block.bbox.x1,
                    y1=block.bbox.y1,
                    x2=block.bbox.x2,
                    y2=block.bbox.y2,
                    engine=result.engine_version,
                )
            )

            next_block_indexes[block.page] = block_index + 1

    source_file = session.get(SourceFile, source_file_id)
    if source_file is not None and page_records:
        source_file.page_count = max(
            source_file.page_count or 0,
            max(page_records),
        )

def save_analysis_result(
    *,
    session: Session,
    job: ProcessingJob,
    result: AnalysisResult,  
) -> AnalysisResultRecord:
    if job.source_file_id is None:
        raise ValueError("Job does not have a source file")

    existing_result = session.scalar(
        select(AnalysisResultRecord).where(AnalysisResultRecord.job_id == job.id)
    )
    if existing_result is not None:
        raise ValueError("Analysis result already exists for job")

    result_record = AnalysisResultRecord(
        job_id=job.id,
        dossier_id=job.dossier_id,
        source_file_id=job.source_file_id,
        engine_version=result.engine_version,
        processing_time_ms=result.processing_time_ms,
    )
    session.add(result_record)
    session.flush()

    for document_index, analyzed_document in enumerate(
        result.documents
    ):
        document_record = DocumentRecord(
            analysis_result_id=result_record.id,
            document_index=document_index,
            document_type=analyzed_document.document_type.value,
            classification_confidence=(
                analyzed_document.classification_confidence
            ),
            page_numbers=list(analyzed_document.pages),
        )
        session.add(document_record)
        session.flush()

        for field_index, field in enumerate(
            analyzed_document.fields
        ):
            bbox = field.bbox

            session.add(
                ExtractedFieldRecord(
                    document_id=document_record.id,
                    field_index=field_index,
                    name=field.name,
                    raw_value=field.raw_value,
                    normalized_value=field.normalized_value,
                    confidence=field.confidence,
                    page_number=field.page,
                    x1=bbox.x1 if bbox is not None else None,
                    y1=bbox.y1 if bbox is not None else None,
                    x2=bbox.x2 if bbox is not None else None,
                    y2=bbox.y2 if bbox is not None else None,
                    evidence_text=field.evidence_text,
                    source=field.source,
                    needs_review=field.needs_review,
                )
            )

    _save_ocr_content(
        session=session,
        source_file_id=job.source_file_id,
        result=result,
    )

    session.flush()
    return result_record

def load_analysis_result(
    *,
    session: Session,
    job_id: UUID,
) -> AnalysisResult | None:
    result_record = session.scalar(
        select(AnalysisResultRecord).where(
            AnalysisResultRecord.job_id == job_id
        )
    )

    if result_record is None:
        return None

    document_records = session.scalars(
        select(DocumentRecord)
        .where(
            DocumentRecord.analysis_result_id == result_record.id
        )
        .order_by(DocumentRecord.document_index)
    ).all()

    analyzed_documents: list[AnalyzedDocument] = []

    for document_record in document_records:
        field_records = session.scalars(
            select(ExtractedFieldRecord)
            .where(
                ExtractedFieldRecord.document_id
                == document_record.id
            )
            .order_by(ExtractedFieldRecord.field_index)
        ).all()

        extracted_fields: list[ExtractedField] = []

        for field_record in field_records:
            bbox = None

            if field_record.x1 is not None:
                bbox = BoundingBox(
                    x1=field_record.x1,
                    y1=field_record.y1,
                    x2=field_record.x2,
                    y2=field_record.y2,
                )

            extracted_fields.append(
                ExtractedField(
                    name=field_record.name,
                    raw_value=field_record.raw_value,
                    normalized_value=field_record.normalized_value,
                    confidence=field_record.confidence,
                    page=field_record.page_number,
                    bbox=bbox,
                    evidence_text=field_record.evidence_text,
                    source=field_record.source,
                    needs_review=field_record.needs_review,
                )
            )

        page_numbers = list(document_record.page_numbers)

        page_records = session.scalars(
            select(Page)
            .where(
                Page.source_file_id
                == result_record.source_file_id,
                Page.page_number.in_(page_numbers),
            )
            .order_by(Page.page_number)
        ).all()

        ocr_blocks: list[OcrBlock] = []

        for page_record in page_records:
            block_records = session.scalars(
                select(OcrBlockRecord)
                .where(OcrBlockRecord.page_id == page_record.id)
                .order_by(OcrBlockRecord.block_index)
            ).all()

            for block_record in block_records:
                ocr_blocks.append(
                    OcrBlock(
                        page=page_record.page_number,
                        text=block_record.text,
                        confidence=block_record.confidence,
                        bbox=BoundingBox(
                            x1=block_record.x1,
                            y1=block_record.y1,
                            x2=block_record.x2,
                            y2=block_record.y2,
                        ),
                    )
                )

        analyzed_documents.append(
            AnalyzedDocument(
                document_type=document_record.document_type,
                classification_confidence=(
                    document_record.classification_confidence
                ),
                pages=page_numbers,
                fields=extracted_fields,
                ocr_blocks=ocr_blocks,
            )
        )

    return AnalysisResult(
        documents=analyzed_documents,
        engine_version=result_record.engine_version,
        processing_time_ms=result_record.processing_time_ms,
    )