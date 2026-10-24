"""AI, OCR, Classification, Normalization, and Field Extraction modules for DocFlow VN."""

from app.services.ai.classifier import (
    DocumentSegment,
    PageClassificationResult,
    classify_and_split_pages,
    score_page_by_keywords,
    segments_to_analyzed_documents,
    strip_vietnamese_accents,
)
from app.services.ai.extractor import (
    extract_fields_by_rules,
    extract_missing_fields_with_ollama,
    populate_segment_fields,
)
from app.services.ai.normalizers import (
    normalize_currency,
    normalize_date,
    normalize_document_code,
    normalize_money_amount,
    normalize_tax_id,
    normalize_vat_rate,
    parse_vietnamese_amount_in_words,
)
from app.services.ai.ocr_processor import deskew_image, run_ocr_on_image
from app.services.ai.pdf_reader import PageReadOutput, read_document_pages

__all__ = [
    "DocumentSegment",
    "PageClassificationResult",
    "PageReadOutput",
    "classify_and_split_pages",
    "deskew_image",
    "extract_fields_by_rules",
    "extract_missing_fields_with_ollama",
    "normalize_currency",
    "normalize_date",
    "normalize_document_code",
    "normalize_money_amount",
    "normalize_tax_id",
    "normalize_vat_rate",
    "parse_vietnamese_amount_in_words",
    "populate_segment_fields",
    "read_document_pages",
    "run_ocr_on_image",
    "score_page_by_keywords",
    "segments_to_analyzed_documents",
    "strip_vietnamese_accents",
]
