from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.analysis_result import AnalysisResultRecord
from app.models.document import Document
from app.models.extracted_field import ExtractedFieldRecord
from app.models.ocr_block import OcrBlock
from app.models.page import Page
from app.models.source_file import SourceFile
from app.schemas.search import (
    DocumentSearchResponse,
    DocumentSearchResult,
    SearchMatch,
)


def _unaccent_contains(
    column: object,
    query: str,
) -> object:
    return func.unaccent(
        func.coalesce(column, "")
    ).ilike(
        func.unaccent(f"%{query}%")
    )


def search_dossier_documents(
    *,
    session: Session,
    dossier_id: UUID,
    query: str | None = None,
    document_type: str | None = None,
    field_name: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 20,
    offset: int = 0,
) -> DocumentSearchResponse:
    document_statement = (
        select(
            Document,
            AnalysisResultRecord.source_file_id,
            SourceFile.original_name,
        )
        .join(
            AnalysisResultRecord,
            AnalysisResultRecord.id
            == Document.analysis_result_id,
        )
        .join(
            SourceFile,
            SourceFile.id
            == AnalysisResultRecord.source_file_id,
        )
        .where(
            AnalysisResultRecord.dossier_id
            == dossier_id
        )
        .order_by(Document.created_at.desc())
    )

    if document_type is not None:
        document_statement = (
            document_statement.where(
                Document.document_type
                == document_type
            )
        )

    document_rows = session.execute(
        document_statement
    ).all()
    results: list[DocumentSearchResult] = []

    for document, source_file_id, original_name in (
        document_rows
    ):
        matches: list[SearchMatch] = []

        field_statement = (
            select(ExtractedFieldRecord)
            .where(
                ExtractedFieldRecord.document_id
                == document.id,
                ExtractedFieldRecord.confidence
                >= min_confidence,
            )
            .order_by(
                ExtractedFieldRecord.field_index
            )
        )

        if field_name is not None:
            field_statement = (
                field_statement.where(
                    func.lower(
                        ExtractedFieldRecord.name
                    )
                    == field_name.lower()
                )
            )

        if query is not None:
            field_statement = (
                field_statement.where(
                    or_(
                        _unaccent_contains(
                            ExtractedFieldRecord.name,
                            query,
                        ),
                        _unaccent_contains(
                            ExtractedFieldRecord.raw_value,
                            query,
                        ),
                        _unaccent_contains(
                            ExtractedFieldRecord.normalized_value,
                            query,
                        ),
                        _unaccent_contains(
                            ExtractedFieldRecord.evidence_text,
                            query,
                        ),
                    )
                )
            )

        fields = session.scalars(
            field_statement
        ).all()

        for extracted_field in fields:
            text = (
                extracted_field.normalized_value
                or extracted_field.raw_value
                or extracted_field.evidence_text
                or ""
            )
            matches.append(
                SearchMatch(
                    source="extracted_field",
                    field_name=extracted_field.name,
                    text=text,
                    page_number=(
                        extracted_field.page_number
                    ),
                    confidence=(
                        extracted_field.confidence
                    ),
                )
            )

        if (
            query is not None
            and field_name is None
        ):
            ocr_statement = (
                select(OcrBlock, Page.page_number)
                .join(
                    Page,
                    Page.id == OcrBlock.page_id,
                )
                .where(
                    Page.source_file_id
                    == source_file_id,
                    Page.page_number.in_(
                        document.page_numbers
                    ),
                    OcrBlock.confidence
                    >= min_confidence,
                    _unaccent_contains(
                        OcrBlock.text,
                        query,
                    ),
                )
                .order_by(
                    Page.page_number,
                    OcrBlock.block_index,
                )
            )

            ocr_rows = session.execute(
                ocr_statement
            ).all()

            for ocr_block, page_number in ocr_rows:
                matches.append(
                    SearchMatch(
                        source="ocr_block",
                        field_name=None,
                        text=ocr_block.text,
                        page_number=page_number,
                        confidence=ocr_block.confidence,
                    )
                )

        if query is not None and not matches:
            continue

        if field_name is not None and not matches:
            continue

        results.append(
            DocumentSearchResult(
                document_id=document.id,
                source_file_id=source_file_id,
                original_name=original_name,
                document_type=document.document_type,
                classification_confidence=(
                    document.classification_confidence
                ),
                page_numbers=document.page_numbers,
                created_at=document.created_at,
                matches=matches,
            )
        )

    count = len(results)
    paginated_results = results[
        offset : offset + limit
    ]

    return DocumentSearchResponse(
        query=query,
        document_type=document_type,
        field_name=field_name,
        count=count,
        limit=limit,
        offset=offset,
        results=paginated_results,
    )