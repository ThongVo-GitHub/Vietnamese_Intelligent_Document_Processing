"""Unit and integration tests for QA-01 and AI-02..AI-09 (OCR, Classification, Splitting, Normalization & Extraction)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.schemas.common import BoundingBox, DocumentType, ExtractedField, OcrBlock
from app.services.ai.classifier import classify_and_split_pages, score_page_by_keywords
from app.services.ai.normalizers import (
    normalize_currency,
    normalize_date,
    normalize_document_code,
    normalize_money_amount,
    normalize_tax_id,
    normalize_vat_rate,
    parse_vietnamese_amount_in_words,
)
from app.services.ai.pdf_reader import PageReadOutput, read_document_pages
from app.services.ai_engine import LocalAIEngineClient
from app.services.reconciliation import DocumentSnapshot
from app.services.reconciliation_rules import (
    compare_document_pair,
    find_missing_document_types,
    find_missing_required_fields,
    validate_document_values,
)
from scripts.generate_fixtures import generate_all_fixtures

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def qa01_fixtures() -> dict[str, Path]:
    return generate_all_fixtures(FIXTURES_DIR)


def _assert_valid_ocr_blocks(blocks: list[OcrBlock]) -> None:
    assert len(blocks) > 0
    for block in blocks:
        assert block.page >= 1
        assert len(block.text.strip()) >= 1
        assert 0.0 <= block.confidence <= 1.0
        assert 0.0 <= block.bbox.x1 <= block.bbox.x2 <= 1.0
        assert 0.0 <= block.bbox.y1 <= block.bbox.y2 <= 1.0


def _assert_valid_extracted_fields(fields: list[ExtractedField]) -> None:
    assert len(fields) > 0
    for f in fields:
        assert len(f.name) >= 1
        assert f.normalized_value is not None
        assert 0.0 <= f.confidence <= 1.0
        assert f.page is not None and f.page >= 1
        assert f.bbox is not None
        assert 0.0 <= f.bbox.x1 <= f.bbox.x2 <= 1.0
        assert 0.0 <= f.bbox.y1 <= f.bbox.y2 <= 1.0


def test_read_user_sample_pdf_in_docs_is_classified_as_unknown() -> None:
    user_pdf = REPO_ROOT / "docs" / "DAY-LA-FILE-MAU-PDF.pdf"
    if not user_pdf.is_file():
        pytest.skip("docs/DAY-LA-FILE-MAU-PDF.pdf not found")

    client = LocalAIEngineClient()
    pages = client.extract_pages(file_path=user_pdf, media_type="application/pdf")

    assert len(pages) == 1
    page = pages[0]
    assert page.page_number == 1
    assert page.width > 0 and page.height > 0
    _assert_valid_ocr_blocks(page.ocr_blocks)

    combined_text = " ".join(b.text for b in page.ocr_blocks).upper()
    assert "FILE" in combined_text and "PDF" in combined_text

    result = client.analyze_document(file_path=user_pdf, media_type="application/pdf")
    assert result.engine_version == "ai-engine-0.1.0"
    assert len(result.documents) == 1
    assert result.documents[0].document_type == DocumentType.UNKNOWN
    assert result.documents[0].classification_confidence == 0.0
    assert len(result.documents[0].ocr_blocks) == len(page.ocr_blocks)


def test_ai07_and_ai09_normalizers() -> None:
    assert normalize_date("15/10/2026") == "2026-10-15"
    assert normalize_date("Ngày 05 tháng 11 năm 2026") == "2026-11-05"
    assert normalize_date("Giờ vào: 13:47 24/10/2026") == "2026-10-24"

    assert normalize_money_amount("110.000.000 VND") == "110000000"
    assert normalize_money_amount("100.000 000 VND") == "100000000"
    assert normalize_money_amount("50,000 đ") == "50000"

    assert normalize_currency("110.000.000 VND") == "VND"
    assert normalize_currency("50,000 đ") == "VND"
    assert normalize_currency("1,500 USD") == "USD"

    assert normalize_tax_id("0309876543") == "0309876543"
    assert normalize_tax_id("0309876543-001") == "0309876543-001"
    assert normalize_document_code("HD 2026-001") == "HD-2026-001"
    assert normalize_vat_rate("10%") == "10"

    # AI-09: Vietnamese amount in words -> numeric string
    assert parse_vietnamese_amount_in_words("Một trăm mười triệu đồng chẵn") == "110000000"
    assert parse_vietnamese_amount_in_words("Mot tram muoi trieu dong chan") == "110000000"
    assert (
        parse_vietnamese_amount_in_words(
            "Một trăm hai mươi lăm triệu bốn trăm linh năm nghìn đồng"
        )
        == "125405000"
    )
    assert parse_vietnamese_amount_in_words("Năm mươi nghìn đồng") == "50000"


def test_qa01_single_documents_classified_and_fields_extracted(
    qa01_fixtures: dict[str, Path],
) -> None:
    client = LocalAIEngineClient()
    expected_map = {
        "contract": (
            DocumentType.CONTRACT,
            {"contract_number": "HD-2026-001", "tax_id": "0309876543", "total_amount": "110000000"},
        ),
        "invoice": (
            DocumentType.INVOICE,
            {
                "invoice_number": "0000128",
                "contract_number": "HD-2026-001",
                "tax_id": "0309876543",
                "subtotal": "100000000",
                "vat_rate": "10",
                "vat_amount": "10000000",
                "total_amount": "110000000",
                "amount_in_words": "110000000",
            },
        ),
        "payment_request": (
            DocumentType.PAYMENT_REQUEST,
            {
                "payment_request_number": "DNTT-2026-001",
                "contract_number": "HD-2026-001",
                "invoice_number": "0000128",
                "tax_id": "0309876543",
                "payment_amount": "110000000",
                "amount_in_words": "110000000",
            },
        ),
    }

    for key, (expected_type, expected_fields) in expected_map.items():
        result = client.analyze_document(
            file_path=qa01_fixtures[key],
            media_type="application/pdf",
        )
        assert len(result.documents) == 1
        doc = result.documents[0]
        assert doc.document_type == expected_type
        assert doc.classification_confidence >= 0.85
        assert doc.pages == [1]
        _assert_valid_ocr_blocks(doc.ocr_blocks)
        _assert_valid_extracted_fields(doc.fields)

        field_dict = {f.name: f.normalized_value for f in doc.fields}
        for k, v in expected_fields.items():
            assert field_dict.get(k) == v, f"Mismatch on {key}.{k}: got {field_dict.get(k)!r}, expected {v!r}"


def test_qa01_merged_3page_dossier_end_to_end_reconciliation_passes(
    qa01_fixtures: dict[str, Path],
) -> None:
    client = LocalAIEngineClient()
    result = client.analyze_document(
        file_path=qa01_fixtures["merged_dossier"],
        media_type="application/pdf",
    )

    assert len(result.documents) == 3
    snapshots: list[DocumentSnapshot] = []
    for doc in result.documents:
        _assert_valid_extracted_fields(doc.fields)
        snapshots.append(
            DocumentSnapshot(
                id=uuid4(),
                document_type=doc.document_type.value,
                fields={f.name: f.normalized_value for f in doc.fields},
                confidences={f.name: f.confidence for f in doc.fields},
            )
        )

    assert find_missing_document_types(snapshots) == []
    assert find_missing_required_fields(snapshots) == []
    assert validate_document_values(snapshots) == []
    assert compare_document_pair(snapshots[0], snapshots[1], "contract_invoice") == []
    assert compare_document_pair(snapshots[1], snapshots[2], "invoice_payment_request") == []


def test_ai05_multipage_contract_continuation_merges_into_single_document() -> None:
    bbox = BoundingBox(x1=0.1, y1=0.1, x2=0.8, y2=0.15)
    page1 = PageReadOutput(
        page_number=1,
        width=595,
        height=842,
        has_text_layer=True,
        ocr_blocks=[
            OcrBlock(page=1, text="HỢP ĐỒNG KINH TẾ", confidence=0.99, bbox=bbox),
            OcrBlock(page=1, text="Số hợp đồng: HD-01/2026", confidence=0.99, bbox=bbox),
            OcrBlock(page=1, text="Điều 1: Nội dung công việc", confidence=0.99, bbox=bbox),
        ],
    )
    page2 = PageReadOutput(
        page_number=2,
        width=595,
        height=842,
        has_text_layer=True,
        ocr_blocks=[
            OcrBlock(page=2, text="Điều 2: Giá trị hợp đồng và phương thức thanh toán", confidence=0.99, bbox=bbox),
            OcrBlock(page=2, text="ĐẠI DIỆN BÊN A", confidence=0.99, bbox=bbox),
            OcrBlock(page=2, text="ĐẠI DIỆN BÊN B", confidence=0.99, bbox=bbox),
        ],
    )
    page3 = PageReadOutput(
        page_number=3,
        width=595,
        height=842,
        has_text_layer=True,
        ocr_blocks=[
            OcrBlock(page=3, text="HÓA ĐƠN GIÁ TRỊ GIA TĂNG", confidence=0.99, bbox=bbox),
            OcrBlock(page=3, text="Số hóa đơn: 0000128 - Ký hiệu: 1C26TAA", confidence=0.99, bbox=bbox),
        ],
    )

    segments, page_results = classify_and_split_pages([page1, page2, page3])
    assert len(page_results) == 3
    assert len(segments) == 2
    assert segments[0].document_type == DocumentType.CONTRACT
    assert segments[0].pages == [1, 2]
    assert len(segments[0].ocr_blocks) == 6

    assert segments[1].document_type == DocumentType.INVOICE
    assert segments[1].pages == [3]
    assert len(segments[1].ocr_blocks) == 2


def test_qa01_scanned_pdf_triggers_pypdfium2_deskew_and_ocr_fallback(
    qa01_fixtures: dict[str, Path],
) -> None:
    pages = read_document_pages(qa01_fixtures["scanned_invoice"], media_type="application/pdf")
    assert len(pages) == 1
    page = pages[0]
    assert page.has_text_layer is False
    assert page.engine in {
        "paddleocr",
        "paddleocr+vietocr",
        "paddleocr-onnx",
        "paddleocr-onnx+vietocr",
        "opencv-fallback",
    }
    _assert_valid_ocr_blocks(page.ocr_blocks)
    cls_res = score_page_by_keywords(page)
    assert cls_res.page_number == 1


def test_xml_einvoice_classified_and_extracted(tmp_path: Path) -> None:
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<HDon>
  <DLHDon>
    <TTChung>
      <THDon>HÓA ĐƠN GIÁ TRỊ GIA TĂNG</THDon>
      <SHDon>0000128</SHDon>
      <NLap>2026-10-18</NLap>
      <DVTTe>VND</DVTTe>
      <SHDong>HD-2026-001</SHDong>
    </TTChung>
    <NDHDon>
      <NBan>
        <Ten>CÔNG TY TNHH GIẢI PHÁP SỐ VIỆT</Ten>
        <MST>0309876543</MST>
      </NBan>
      <NMua>
        <Ten>CÔNG TY CỔ PHẦN ĐẦU TƯ ABC</Ten>
        <MST>0101234567</MST>
      </NMua>
      <TToan>
        <TgTCThue>100000000</TgTCThue>
        <TSuat>10%</TSuat>
        <TgTThue>10000000</TgTThue>
        <TgTTTBSo>110000000</TgTTTBSo>
        <TgTTTBChu>Một trăm mười triệu đồng chẵn</TgTTTBChu>
      </TToan>
    </NDHDon>
  </DLHDon>
</HDon>
"""
    xml_file = tmp_path / "sample_einvoice.xml"
    xml_file.write_text(xml_content, encoding="utf-8")

    client = LocalAIEngineClient()
    result = client.analyze_document(file_path=xml_file, media_type="application/xml")
    assert result.engine_version == "ai-engine-0.1.0"
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.document_type == DocumentType.INVOICE
    fields = {f.name: f.normalized_value for f in doc.fields}
    assert fields["invoice_number"] == "0000128"
    assert fields["contract_number"] == "HD-2026-001"
    assert fields["tax_id"] == "0309876543"
    assert fields["subtotal"] == "100000000"
    assert fields["vat_rate"] == "10"
    assert fields["vat_amount"] == "10000000"
    assert fields["total_amount"] == "110000000"
    assert fields["amount_in_words"] == "110000000"
    assert fields["currency"] == "VND"
    assert all(f.source == "text_layer" for f in doc.fields)


def test_phieu_chi_and_uy_nhiem_chi_are_not_classified_as_payment_request() -> None:
    bbox = BoundingBox(x1=0.1, y1=0.08, x2=0.8, y2=0.14)
    for title in ("PHIẾU CHI", "ỦY NHIỆM CHI", "BIÊN LAI THU TIỀN"):
        page = PageReadOutput(
            page_number=1,
            width=595,
            height=842,
            has_text_layer=True,
            ocr_blocks=[
                OcrBlock(page=1, text=title, confidence=0.99, bbox=bbox),
                OcrBlock(page=1, text="Kính gửi: Phòng Kế toán", confidence=0.99, bbox=bbox),
                OcrBlock(page=1, text="Đơn vị thụ hưởng: Công ty B", confidence=0.99, bbox=bbox),
            ],
        )
        res = score_page_by_keywords(page)
        assert res.document_type == DocumentType.UNKNOWN


def test_standalone_ai_engine_fastapi_endpoints(qa01_fixtures: dict[str, Path]) -> None:
    import importlib.util
    from fastapi.testclient import TestClient

    ai_main_path = REPO_ROOT / "ai-engine" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("ai_engine_main", ai_main_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    api_client = TestClient(module.app)

    health_resp = api_client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"
    assert health_resp.json()["engine_version"] == "ai-engine-0.1.0"

    for key, expected_type in (
        ("contract", "contract"),
        ("invoice", "invoice"),
        ("payment_request", "payment_request"),
    ):
        pdf_bytes = qa01_fixtures[key].read_bytes()
        resp = api_client.post(
            "/analyze",
            files={"file": (f"{key}.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["engine_version"] == "ai-engine-0.1.0"
        assert payload["documents"][0]["document_type"] == expected_type
        assert len(payload["documents"][0]["fields"]) >= 3

    bad_resp = api_client.post(
        "/analyze",
        files={"file": ("bad.txt", b"plain text not supported", "text/plain")},
    )
    assert bad_resp.status_code == 415
