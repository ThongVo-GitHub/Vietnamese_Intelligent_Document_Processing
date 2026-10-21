import pytest
from pydantic import ValidationError

from app.schemas.common import (
    AnalysisResult,
    BoundingBox,
    ExtractedField,
)

def test_bounding_box_accepts_normalized_coordinates() -> None:
    bbox = BoundingBox(
        x1=0.1,
        y1=0.2,
        x2=0.8,
        y2=0.3,
    )

    assert bbox.x1 == 0.1
    assert bbox.x2 == 0.8

def test_bounding_box_rejects_coordinates_outside_page() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(
            x1=-0.1,
            y1=0.2,
            x2=0.8,
            y2=0.3,
        )

def test_extracted_field_keeps_evidence() -> None:
    bbox = BoundingBox(
        x1=0.1,
        y1=0.7,
        x2=0.8,
        y2=0.8,
    )

    field = ExtractedField(
        name="total_amount",
        raw_value="12.500.000 VND",
        normalized_value="12500000",
        confidence=0.91,
        page=1,
        bbox=bbox,
        evidence_text="Tong tien: 12.500.000 VND",
        source="ocr",
    )

    assert field.normalized_value == "12500000"
    assert field.page == 1
    assert field.bbox == bbox

def test_analysis_result_has_empty_document_list_by_default() -> None:
    result = AnalysisResult(
        engine_version="0.1.0",
        processing_time_ms=120,
    )

    assert result.documents == []