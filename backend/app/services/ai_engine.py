from pathlib import Path
from typing import Protocol

from app.schemas.common import (
    AnalysisResult,
    AnalyzedDocument,
    DocumentType,
)


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