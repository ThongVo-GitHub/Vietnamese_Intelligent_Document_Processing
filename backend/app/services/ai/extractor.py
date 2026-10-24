"""Rule/Regex field extraction with bounding box grounding (AI-06) and Ollama Qwen fallback (AI-08)."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable

import httpx

from app.schemas.common import BoundingBox, DocumentType, ExtractedField, OcrBlock
from app.services.ai.classifier import DocumentSegment, strip_vietnamese_accents
from app.services.ai.normalizers import (
    normalize_currency,
    normalize_date,
    normalize_document_code,
    normalize_money_amount,
    normalize_tax_id,
    normalize_vat_rate,
    parse_vietnamese_amount_in_words,
)

logger = logging.getLogger(__name__)

# Confidence threshold below which ExtractedField.needs_review is set to True (BACKEND_WORKFLOW_GUIDE Section 18)
NEEDS_REVIEW_CONFIDENCE_THRESHOLD: float = float(os.getenv("AI_NEEDS_REVIEW_THRESHOLD", "0.80"))


def _clean_entity_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.strip(" :.-,\t\r\n").split())
    return cleaned if len(cleaned) >= 2 else None


def _merge_bboxes(b1: BoundingBox, b2: BoundingBox) -> BoundingBox:
    return BoundingBox(
        x1=round(min(b1.x1, b2.x1), 6),
        y1=round(min(b1.y1, b2.y1), 6),
        x2=round(max(b1.x2, b2.x2), 6),
        y2=round(max(b1.y2, b2.y2), 6),
    )


def _find_same_row_value_block(
    label_block: OcrBlock,
    all_blocks: list[OcrBlock],
    *,
    y_tolerance: float = 0.02,
) -> OcrBlock | None:
    """Find a block on the same page and horizontal row to the right (or left) of label_block."""
    label_y_center = (label_block.bbox.y1 + label_block.bbox.y2) / 2.0
    candidates: list[tuple[float, OcrBlock]] = []

    for b in all_blocks:
        if b is label_block or b.page != label_block.page:
            continue
        b_y_center = (b.bbox.y1 + b.bbox.y2) / 2.0
        y_diff = abs(b_y_center - label_y_center)
        if y_diff <= y_tolerance:
            # Prefer blocks to the right of the label
            x_dist = abs(b.bbox.x1 - label_block.bbox.x2)
            candidates.append((y_diff * 3.0 + x_dist, b))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _extract_by_patterns(
    ocr_blocks: list[OcrBlock],
    *,
    field_name: str,
    label_keywords: tuple[str, ...],
    value_regex: str,
    normalizer: Callable[[str | None], str | None],
    allow_same_row_neighbor: bool = True,
    exclude_keywords: tuple[str, ...] = (),
) -> ExtractedField | None:
    """Search OCR blocks for a label keyword and extract its value via regex or same-row neighbor."""
    compiled = re.compile(value_regex, re.IGNORECASE)

    for block in ocr_blocks:
        ascii_line = strip_vietnamese_accents(block.text)
        if exclude_keywords and any(ex in ascii_line for ex in exclude_keywords):
            continue

        matched_kw = next((kw for kw in label_keywords if kw in ascii_line), None)
        if matched_kw is None:
            continue

        # 1. Try extracting from the portion of the same block after the matched keyword
        kw_pos = ascii_line.find(matched_kw)
        after_kw_idx = kw_pos + len(matched_kw)
        search_sub = block.text[max(0, after_kw_idx):]
        m = compiled.search(search_sub)
        if not m:
            m = compiled.search(block.text)

        if m:
            raw_val = (m.group(1) if m.lastindex else m.group(0)).strip()
            norm_val = normalizer(raw_val)
            if norm_val is not None:
                return ExtractedField(
                    name=field_name,
                    raw_value=raw_val,
                    normalized_value=norm_val,
                    confidence=round(block.confidence, 4),
                    page=block.page,
                    bbox=block.bbox,
                    evidence_text=block.text,
                    source="rule",
                    needs_review=block.confidence < NEEDS_REVIEW_CONFIDENCE_THRESHOLD,
                )

        # 2. Try same-row neighbor block (e.g. receipt table where label is left, amount is right)
        if allow_same_row_neighbor:
            neighbor = _find_same_row_value_block(block, ocr_blocks)
            if neighbor is not None:
                m_nb = compiled.search(neighbor.text)
                if m_nb:
                    raw_val = (m_nb.group(1) if m_nb.lastindex else m_nb.group(0)).strip()
                    norm_val = normalizer(raw_val)
                    if norm_val is not None:
                        combined_bbox = _merge_bboxes(block.bbox, neighbor.bbox)
                        avg_conf = round((block.confidence + neighbor.confidence) / 2.0, 4)
                        return ExtractedField(
                            name=field_name,
                            raw_value=raw_val,
                            normalized_value=norm_val,
                            confidence=avg_conf,
                            page=neighbor.page,
                            bbox=combined_bbox,
                            evidence_text=f"{block.text} -> {neighbor.text}",
                            source="rule",
                            needs_review=avg_conf < NEEDS_REVIEW_CONFIDENCE_THRESHOLD,
                        )

    return None


def _extract_amount_in_words_field(ocr_blocks: list[OcrBlock]) -> ExtractedField | None:
    """Extract Vietnamese amount in words and normalize to numeric string for reconciliation."""
    keywords = (
        "so tien viet bang chu",
        "so tien bang chu",
        "viet bang chu",
        "bang chu",
    )
    for block in ocr_blocks:
        ascii_line = strip_vietnamese_accents(block.text)
        matched_kw = next((kw for kw in keywords if kw in ascii_line), None)
        if matched_kw is None:
            continue

        # Split after colon or after keyword
        if ":" in block.text:
            raw_words = block.text.split(":", 1)[1].strip()
        else:
            idx = ascii_line.find(matched_kw) + len(matched_kw)
            raw_words = block.text[idx:].strip(" :.-")

        if not raw_words:
            neighbor = _find_same_row_value_block(block, ocr_blocks)
            if neighbor is not None:
                raw_words = neighbor.text.strip()

        if raw_words:
            norm_num = parse_vietnamese_amount_in_words(raw_words)
            return ExtractedField(
                name="amount_in_words",
                raw_value=raw_words,
                normalized_value=norm_num,
                confidence=round(block.confidence, 4),
                page=block.page,
                bbox=block.bbox,
                evidence_text=block.text,
                source="rule",
                needs_review=norm_num is None or block.confidence < NEEDS_REVIEW_CONFIDENCE_THRESHOLD,
            )
    return None


def _extract_currency_field(ocr_blocks: list[OcrBlock]) -> ExtractedField | None:
    """Extract currency from total/amount lines or document text."""
    priority_keywords = (
        "tong cong",
        "tong gia tri",
        "thanh toan",
        "so tien",
        "cong tien hang",
        "tien hang",
    )
    for block in ocr_blocks:
        ascii_line = strip_vietnamese_accents(block.text)
        if any(kw in ascii_line for kw in priority_keywords):
            curr = normalize_currency(block.text)
            if curr is not None:
                return ExtractedField(
                    name="currency",
                    raw_value=curr,
                    normalized_value=curr,
                    confidence=round(block.confidence, 4),
                    page=block.page,
                    bbox=block.bbox,
                    evidence_text=block.text,
                    source="rule",
                    needs_review=False,
                )

    for block in ocr_blocks:
        curr = normalize_currency(block.text)
        if curr is not None:
            return ExtractedField(
                name="currency",
                raw_value=curr,
                normalized_value=curr,
                confidence=round(block.confidence, 4),
                page=block.page,
                bbox=block.bbox,
                evidence_text=block.text,
                source="rule",
                needs_review=False,
            )
    return None


def extract_fields_by_rules(
    doc_type: DocumentType,
    ocr_blocks: list[OcrBlock],
) -> list[ExtractedField]:
    """Extract structured fields with bounding box evidence for Contract, Invoice, or Payment Request (AI-06)."""
    if not ocr_blocks or doc_type == DocumentType.UNKNOWN:
        return []

    fields: list[ExtractedField] = []

    def _add(f: ExtractedField | None) -> None:
        if f is not None and not any(existing.name == f.name for existing in fields):
            fields.append(f)

    code_pattern = r"[:.\s-]*([A-Za-z0-9]{1,8}(?:[\s/-][A-Za-z0-9]{1,8})*\d[A-Za-z0-9/-]*|\d{3,20})"
    money_pattern = r"(\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d{1,2})?|\d{4,12})"
    tax_pattern = r"(\d{10}(?:-\d{3})?)"
    date_pattern = (
        r"(ngay\s*\d{1,2}\s*thang\s*\d{1,2}\s*nam\s*\d{4}"
        r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}"
        r"|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})"
    )

    if doc_type == DocumentType.CONTRACT:
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="contract_number",
                label_keywords=("so hop dong", "hop dong so"),
                value_regex=code_pattern,
                normalizer=normalize_document_code,
            )
        )
        # Prefer Vendor/Seller (Ben B) tax_id so it matches Invoice seller tax_id & Payment Request beneficiary tax_id
        vendor_tax = _extract_by_patterns(
            ocr_blocks,
            field_name="tax_id",
            label_keywords=("ma so thue ben b", "mst ben b", "ma so thue ben ban", "mst ben ban"),
            value_regex=tax_pattern,
            normalizer=normalize_tax_id,
        ) or _extract_by_patterns(
            ocr_blocks,
            field_name="tax_id",
            label_keywords=("ma so thue", "mst"),
            value_regex=tax_pattern,
            normalizer=normalize_tax_id,
            exclude_keywords=("ben a", "ben mua"),
        )
        _add(vendor_tax)

        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="buyer_tax_id",
                label_keywords=("ma so thue ben a", "mst ben a", "ma so thue ben mua", "mst ben mua"),
                value_regex=tax_pattern,
                normalizer=normalize_tax_id,
            )
        )
        contract_issue_date = _extract_by_patterns(
            ocr_blocks,
            field_name="issue_date",
            label_keywords=("ngay ky", "ngay hop dong", "ngay lap"),
            value_regex=date_pattern,
            normalizer=normalize_date,
        )
        _add(contract_issue_date)
        if contract_issue_date is not None:
            _add(
                ExtractedField(
                    name="contract_date",
                    raw_value=contract_issue_date.raw_value,
                    normalized_value=contract_issue_date.normalized_value,
                    confidence=contract_issue_date.confidence,
                    page=contract_issue_date.page,
                    bbox=contract_issue_date.bbox,
                    evidence_text=contract_issue_date.evidence_text,
                    source=contract_issue_date.source,
                    needs_review=contract_issue_date.needs_review,
                )
            )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="customer_name",
                label_keywords=("ben a (ben mua)", "ben a:", "don vi mua hang"),
                value_regex=r"[:.\s-]*([^\n\r]{3,120})",
                normalizer=_clean_entity_name,
                exclude_keywords=("ma so thue", "mst", "dai dien"),
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="supplier_name",
                label_keywords=("ben b (ben ban)", "ben b:", "don vi ban hang"),
                value_regex=r"[:.\s-]*([^\n\r]{3,120})",
                normalizer=_clean_entity_name,
                exclude_keywords=("ma so thue", "mst", "dai dien"),
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="subtotal",
                label_keywords=("gia tri hop dong truoc thue", "truoc thue", "cong tien hang"),
                value_regex=money_pattern,
                normalizer=normalize_money_amount,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="vat_rate",
                label_keywords=("thue gtgt", "thue suat"),
                value_regex=r"(\d{1,2}\s*%)",
                normalizer=normalize_vat_rate,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="vat_amount",
                label_keywords=("thue gtgt", "tien thue"),
                value_regex=money_pattern,
                normalizer=normalize_money_amount,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="total_amount",
                label_keywords=("tong gia tri hop dong", "tong cong", "gia tri hop dong"),
                value_regex=money_pattern,
                normalizer=normalize_money_amount,
                exclude_keywords=("truoc thue",),
            )
        )
        _add(_extract_amount_in_words_field(ocr_blocks))
        _add(_extract_currency_field(ocr_blocks))

    elif doc_type == DocumentType.INVOICE:
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="invoice_number",
                label_keywords=("so hoa don", "hoa don so", "so:"),
                value_regex=code_pattern,
                normalizer=normalize_document_code,
                exclude_keywords=("hop dong", "dien thoai", "thue"),
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="contract_number",
                label_keywords=("theo hop dong", "theo hopdong", "can cu hop dong", "so hop dong", "hop dong so"),
                value_regex=code_pattern,
                normalizer=normalize_document_code,
            )
        )
        seller_tax = _extract_by_patterns(
            ocr_blocks,
            field_name="tax_id",
            label_keywords=(
                "ma so thue nguoi ban",
                "ma sothue nguoi ban",
                "ma sothue nguoi bon",
                "ma so thue ben ban",
                "mst nguoi ban",
                "mst don vi ban",
            ),
            value_regex=tax_pattern,
            normalizer=normalize_tax_id,
        ) or _extract_by_patterns(
            ocr_blocks,
            field_name="tax_id",
            label_keywords=("ma so thue", "ma sothue", "mst"),
            value_regex=tax_pattern,
            normalizer=normalize_tax_id,
            exclude_keywords=("nguoi mua", "ben mua"),
        )
        _add(seller_tax)

        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="buyer_tax_id",
                label_keywords=("ma so thue nguoi mua", "ma sothue nguoi mua", "ma so thue ben mua", "mst nguoi mua"),
                value_regex=tax_pattern,
                normalizer=normalize_tax_id,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="supplier_name",
                label_keywords=("don vi ban hang", "ten don vi ban"),
                value_regex=r"[:.\s-]*([^\n\r]{3,120})",
                normalizer=_clean_entity_name,
                exclude_keywords=("ma so thue", "mst"),
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="customer_name",
                label_keywords=("don vi mua hang", "ho ten nguoi mua"),
                value_regex=r"[:.\s-]*([^\n\r]{3,120})",
                normalizer=_clean_entity_name,
                exclude_keywords=("ma so thue", "mst"),
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="issue_date",
                label_keywords=("ngay lap", "gio vao", "ngay hoa don", "ngay"),
                value_regex=date_pattern,
                normalizer=normalize_date,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="subtotal",
                label_keywords=("cong tien hang", "tien hang", "tien truoc thue"),
                value_regex=money_pattern,
                normalizer=normalize_money_amount,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="vat_rate",
                label_keywords=("thue suat", "thue gtgt"),
                value_regex=r"(\d{1,2}\s*%)",
                normalizer=normalize_vat_rate,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="vat_amount",
                label_keywords=("tien thue gtgt", "tien thue", "thue gtgt"),
                value_regex=money_pattern,
                normalizer=normalize_money_amount,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="total_amount",
                label_keywords=(
                    "tong cong tien thanh toan",
                    "tong tien thanh toan",
                    "thanh toan",
                    "tong cong",
                ),
                value_regex=money_pattern,
                normalizer=normalize_money_amount,
                exclude_keywords=("hoa don thanh toan", "de nghi thanh toan"),
            )
        )
        _add(_extract_amount_in_words_field(ocr_blocks))
        _add(_extract_currency_field(ocr_blocks))

    elif doc_type == DocumentType.PAYMENT_REQUEST:
        pr_number = _extract_by_patterns(
            ocr_blocks,
            field_name="payment_request_number",
            label_keywords=("so de nghi", "de nghi so"),
            value_regex=code_pattern,
            normalizer=normalize_document_code,
        )
        _add(pr_number)
        if pr_number is not None:
            _add(
                ExtractedField(
                    name="request_number",
                    raw_value=pr_number.raw_value,
                    normalized_value=pr_number.normalized_value,
                    confidence=pr_number.confidence,
                    page=pr_number.page,
                    bbox=pr_number.bbox,
                    evidence_text=pr_number.evidence_text,
                    source=pr_number.source,
                    needs_review=pr_number.needs_review,
                )
            )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="contract_number",
                label_keywords=("can cu hop dong", "so hop dong", "hop dong so"),
                value_regex=code_pattern,
                normalizer=normalize_document_code,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="invoice_number",
                label_keywords=("can cu hoa don", "so hoa don", "hoa don so"),
                value_regex=code_pattern,
                normalizer=normalize_document_code,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="tax_id",
                label_keywords=("ma so thue", "mst"),
                value_regex=tax_pattern,
                normalizer=normalize_tax_id,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="payee_name",
                label_keywords=("don vi thu huong", "nguoi thu huong"),
                value_regex=r"[:.\s-]*([^\n\r]{3,120})",
                normalizer=_clean_entity_name,
                exclude_keywords=("ma so thue", "mst"),
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="bank_account",
                label_keywords=("so tai khoan", "tai khoan so", "stk"),
                value_regex=r"[:.\s-]*([0-9A-Za-z-]{6,25})",
                normalizer=normalize_document_code,
            )
        )
        _add(
            _extract_by_patterns(
                ocr_blocks,
                field_name="bank_name",
                label_keywords=("tai ngan hang", "ngan hang"),
                value_regex=r"[:.\s-]*([^\n\r]{3,120})",
                normalizer=_clean_entity_name,
            )
        )
        pr_date = _extract_by_patterns(
            ocr_blocks,
            field_name="issue_date",
            label_keywords=("ngay de nghi", "ngay lap", "ngay"),
            value_regex=date_pattern,
            normalizer=normalize_date,
        )
        _add(pr_date)
        if pr_date is not None:
            _add(
                ExtractedField(
                    name="request_date",
                    raw_value=pr_date.raw_value,
                    normalized_value=pr_date.normalized_value,
                    confidence=pr_date.confidence,
                    page=pr_date.page,
                    bbox=pr_date.bbox,
                    evidence_text=pr_date.evidence_text,
                    source=pr_date.source,
                    needs_review=pr_date.needs_review,
                )
            )
        payment_amt = _extract_by_patterns(
            ocr_blocks,
            field_name="payment_amount",
            label_keywords=(
                "so tien de nghi thanh toan",
                "so tien de nghi",
                "so tien thanh toan",
                "tong tien thanh toan",
            ),
            value_regex=money_pattern,
            normalizer=normalize_money_amount,
        )
        _add(payment_amt)
        if payment_amt is not None:
            _add(
                ExtractedField(
                    name="total_amount",
                    raw_value=payment_amt.raw_value,
                    normalized_value=payment_amt.normalized_value,
                    confidence=payment_amt.confidence,
                    page=payment_amt.page,
                    bbox=payment_amt.bbox,
                    evidence_text=payment_amt.evidence_text,
                    source=payment_amt.source,
                    needs_review=payment_amt.needs_review,
                )
            )
        _add(_extract_amount_in_words_field(ocr_blocks))
        _add(_extract_currency_field(ocr_blocks))

    return fields


def _find_grounding_block_for_evidence(
    evidence_text: str,
    ocr_blocks: list[OcrBlock],
) -> OcrBlock | None:
    """Verify that LLM evidence_text actually exists in OCR blocks (Anti-Hallucination check, AI-08)."""
    if not evidence_text or not evidence_text.strip():
        return None

    ev_ascii = strip_vietnamese_accents(evidence_text)
    if not ev_ascii:
        return None

    for block in ocr_blocks:
        b_ascii = strip_vietnamese_accents(block.text)
        if ev_ascii in b_ascii or b_ascii in ev_ascii:
            return block

    return None


def extract_missing_fields_with_ollama(
    doc_type: DocumentType,
    ocr_blocks: list[OcrBlock],
    existing_fields: list[ExtractedField],
    *,
    ollama_base_url: str | None = None,
    ollama_model: str | None = None,
    timeout_seconds: float = 8.0,
) -> list[ExtractedField]:
    """Use Ollama (Qwen) to fill missing required fields, enforcing evidence grounding (AI-08)."""
    base_url = (ollama_base_url or os.getenv("OLLAMA_BASE_URL", "")).strip()
    if not base_url or not ocr_blocks or doc_type == DocumentType.UNKNOWN:
        return existing_fields

    target_schema_by_type: dict[DocumentType, tuple[str, ...]] = {
        DocumentType.CONTRACT: ("contract_number", "tax_id", "total_amount", "issue_date"),
        DocumentType.INVOICE: (
            "invoice_number",
            "contract_number",
            "tax_id",
            "subtotal",
            "vat_amount",
            "total_amount",
            "issue_date",
        ),
        DocumentType.PAYMENT_REQUEST: (
            "invoice_number",
            "contract_number",
            "tax_id",
            "payment_amount",
            "issue_date",
        ),
    }

    existing_names = {f.name for f in existing_fields}
    missing_names = [
        name for name in target_schema_by_type.get(doc_type, ()) if name not in existing_names
    ]
    if not missing_names:
        return existing_fields

    model_name = (ollama_model or os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")).strip()
    ocr_text = "\n".join(b.text for b in ocr_blocks)

    prompt = (
        f"Trich xuat cac truong sau tu van ban OCR cua tai lieu '{doc_type.value}': "
        f"{', '.join(missing_names)}.\n"
        "Chi lay thong tin CO THAT trong van ban OCR. Moi truong tra ve JSON:\n"
        "{\"<field_name>\": {\"value\": \"...\", \"evidence_text\": \"<copy nguyen van dong chua gia tri>\"}}\n\n"
        f"Van ban OCR:\n{ocr_text[:2500]}"
    )

    normalizer_map: dict[str, Callable[[str | None], str | None]] = {
        "contract_number": normalize_document_code,
        "invoice_number": normalize_document_code,
        "tax_id": normalize_tax_id,
        "subtotal": normalize_money_amount,
        "vat_amount": normalize_money_amount,
        "total_amount": normalize_money_amount,
        "payment_amount": normalize_money_amount,
        "issue_date": normalize_date,
    }

    merged = list(existing_fields)
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0},
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        parsed = json.loads(response.json().get("response", "{}"))

        for fname in missing_names:
            item = parsed.get(fname)
            if not isinstance(item, dict):
                continue
            raw_val = str(item.get("value") or "").strip()
            ev_text = str(item.get("evidence_text") or "").strip()
            if not raw_val or not ev_text:
                continue

            grounded_block = _find_grounding_block_for_evidence(ev_text, ocr_blocks)
            if grounded_block is None:
                # Anti-hallucination: reject value if evidence_text does not exist in OCR
                continue

            norm_fn = normalizer_map.get(fname, lambda x: x)
            norm_val = norm_fn(raw_val)
            if norm_val is None:
                continue

            merged.append(
                ExtractedField(
                    name=fname,
                    raw_value=raw_val,
                    normalized_value=norm_val,
                    confidence=round(min(0.85, grounded_block.confidence), 4),
                    page=grounded_block.page,
                    bbox=grounded_block.bbox,
                    evidence_text=grounded_block.text,
                    source="llm",
                    needs_review=True,
                )
            )
    except Exception as exc:
        logger.debug("Ollama field extraction fallback skipped/failed: %s", exc)

    return merged


def populate_segment_fields(
    segments: list[DocumentSegment],
    *,
    ollama_base_url: str | None = None,
    ollama_model: str | None = None,
) -> list[ tuple[DocumentSegment, list[ExtractedField]] ]:
    """Extract rule fields + optional LLM fallback fields for each DocumentSegment."""
    results: list[tuple[DocumentSegment, list[ExtractedField]]] = []
    for seg in segments:
        rule_fields = extract_fields_by_rules(seg.document_type, seg.ocr_blocks)
        all_fields = extract_missing_fields_with_ollama(
            seg.document_type,
            seg.ocr_blocks,
            rule_fields,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
        )
        results.append((seg, all_fields))
    return results
