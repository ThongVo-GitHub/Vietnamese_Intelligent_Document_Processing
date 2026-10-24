"""Standalone FastAPI service for DocFlow VN AI Engine (`GET /health` & `POST /analyze`)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter

from fastapi import FastAPI, File, HTTPException, UploadFile, status

from app.schemas.common import AnalysisResult, AnalyzedDocument, ExtractedField
from app.services.ai.classifier import classify_and_split_pages
from app.services.ai.extractor import populate_segment_fields
from app.services.ai.pdf_reader import read_document_pages
from app.services.file_validation import detect_media_type

logger = logging.getLogger(__name__)

ENGINE_VERSION = "ai-engine-0.1.0"
MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(10 * 1024 * 1024)))

_MEDIA_TYPE_SUFFIX: dict[str, str] = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "application/xml": ".xml",
}

app = FastAPI(
    title="DocFlow VN AI Engine",
    version="0.1.0",
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "ai-engine",
        "engine_version": ENGINE_VERSION,
    }


@app.post("/analyze", response_model=AnalysisResult)
async def analyze_file(file: UploadFile = File(...)) -> AnalysisResult:
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file exceeds maximum allowed size ({MAX_UPLOAD_SIZE_BYTES} bytes)",
        )

    media_type = detect_media_type(content)
    if media_type is None or media_type not in _MEDIA_TYPE_SUFFIX:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported media type. Expected PDF, PNG, JPEG, or XML",
        )

    suffix = _MEDIA_TYPE_SUFFIX[media_type]
    tmp_path: Path | None = None

    try:
        start_ts = perf_counter()
        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)

        pages_output = read_document_pages(file_path=tmp_path, media_type=media_type)
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
            engine_version=ENGINE_VERSION,
            processing_time_ms=elapsed_ms,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("AI Engine failed to analyze document")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI analysis failed: {exc}",
        ) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
