from pathlib import Path
from time import perf_counter
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.schemas.common import (
    AnalysisResult,
    AnalyzedDocument,
    DocumentType,
    ExtractedField,
)
from app.services.ai.classifier import classify_and_split_pages
from app.services.ai.extractor import populate_segment_fields
from app.services.ai.pdf_reader import PageReadOutput, read_document_pages


class AIEngineClient(Protocol):
    def analyze_document(
        self,
        *,
        file_path: Path,
        media_type: str,
    ) -> AnalysisResult:
        ...


class MockAIEngineClient:
    def analyze_document(
        self,
        *,
        file_path: Path,
        media_type: str,
    ) -> AnalysisResult:
        if not file_path.is_file():
            raise FileNotFoundError(file_path)

        return AnalysisResult(
            documents=[
                AnalyzedDocument(
                    document_type=DocumentType.UNKNOWN,
                    classification_confidence=0,
                    pages=[1],
                ),
            ],
            engine_version="mock-0.1.0",
            processing_time_ms=0,
        )


class LocalAIEngineClient:
    """In-process AI Engine Client for PDF/Image/XML reading, OCR, Classification & Field Extraction (AI-02..AI-09)."""

    engine_version: str = "ai-engine-0.1.0"

    def extract_pages(
        self,
        *,
        file_path: Path,
        media_type: str = "application/pdf",
    ) -> list[PageReadOutput]:
        """Read pages and extract OCR blocks with normalized bounding boxes [0..1]."""
        return read_document_pages(file_path=file_path, media_type=media_type)

    def analyze_document(
        self,
        *,
        file_path: Path,
        media_type: str = "application/pdf",
    ) -> AnalysisResult:
        start_ts = perf_counter()
        pages_output = self.extract_pages(
            file_path=file_path,
            media_type=media_type,
        )
        page_text_layer_map = {p.page_number: p.has_text_layer for p in pages_output}

        segments, _ = classify_and_split_pages(pages_output)
        segments_with_fields = populate_segment_fields(segments)

        documents: list[AnalyzedDocument] = []
        for seg, fields in segments_with_fields:
            refined_fields: list[ExtractedField] = []
            for f in fields:
                if f.source == "rule" and f.page is not None:
                    actual_src = "text_layer" if page_text_layer_map.get(f.page, False) else "ocr"
                    refined_fields.append(f.model_copy(update={"source": actual_src}))
                else:
                    refined_fields.append(f)

            documents.append(
                AnalyzedDocument(
                    document_type=seg.document_type,
                    classification_confidence=seg.classification_confidence,
                    pages=seg.pages,
                    fields=refined_fields,
                    ocr_blocks=seg.ocr_blocks,
                )
            )

        elapsed_ms = max(0, int(round((perf_counter() - start_ts) * 1000)))

        return AnalysisResult(
            documents=documents,
            engine_version=self.engine_version,
            processing_time_ms=elapsed_ms,
        )


class HTTPAIEngineClient:
    """HTTP client calling the standalone AI Engine service (`POST /analyze` multipart `file`)."""

    def __init__(
        self,
        *,
        base_url: str = "http://ai-engine:8001",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def analyze_document(
        self,
        *,
        file_path: Path,
        media_type: str = "application/pdf",
    ) -> AnalysisResult:
        if not file_path.is_file():
            raise FileNotFoundError(file_path)

        with file_path.open("rb") as fh:
            response = httpx.post(
                f"{self.base_url}/analyze",
                files={"file": (file_path.name, fh, media_type)},
                timeout=self.timeout_seconds,
            )

        response.raise_for_status()
        return AnalysisResult.model_validate(response.json())


def build_ai_engine_client(settings: Settings | None = None) -> AIEngineClient:
    """Instantiate the configured AI Engine client (`mock`, `local`, or `http`)."""
    cfg = settings or get_settings()
    mode = cfg.ai_engine_mode.strip().lower()

    if mode == "mock":
        return MockAIEngineClient()
    if mode == "http":
        return HTTPAIEngineClient(
            base_url=cfg.ai_engine_url,
            timeout_seconds=cfg.ai_engine_timeout_seconds,
        )
    return LocalAIEngineClient()
