"""Page-level document classification (AI-04) and multi-document PDF splitting (AI-05)."""

from __future__ import annotations

import json
import logging
import os
import unicodedata
from dataclasses import dataclass, field

import httpx

from app.schemas.common import AnalyzedDocument, DocumentType, OcrBlock
from app.services.ai.pdf_reader import PageReadOutput

logger = logging.getLogger(__name__)

# Minimum weighted score to accept rule-based classification without ambiguity
MIN_RULE_SCORE_THRESHOLD = 2.5
HIGH_CONFIDENCE_SCORE = 6.0
AMBIGUOUS_CONFIDENCE_THRESHOLD = 0.55


@dataclass
class PageClassificationResult:
    """Classification result for a single page."""

    page_number: int
    document_type: DocumentType
    confidence: float
    raw_scores: dict[DocumentType, float] = field(default_factory=dict)
    source: str = "rule"
    needs_review: bool = False


@dataclass
class DocumentSegment: 
    """A contiguous range of pages belonging to a single logical document."""

    document_type: DocumentType
    classification_confidence: float
    pages: list[int]
    ocr_blocks: list[OcrBlock]
    needs_review: bool = False


# Weighted keyword dictionary (normalized lowercase ASCII without Vietnamese accents)
# Tuple format: (keyword_phrase, weight, header_bonus_if_top_of_page)
_KEYWORD_RULES: dict[DocumentType, list[tuple[str, float, float]]] = {
    DocumentType.CONTRACT: [
        ("hop dong kinh te", 5.0, 2.0),
        ("hop dong mua ban", 5.0, 2.0),
        ("hop dong cung cap", 5.0, 2.0),
        ("hop dong dich vu", 5.0, 2.0),
        ("phu luc hop dong", 4.5, 1.5),
        ("so hop dong", 2.5, 0.5),
        ("ben a (ben mua)", 2.5, 0.0),
        ("ben b (ben ban)", 2.5, 0.0),
        ("dai dien ben a", 2.5, 0.0),
        ("dai dien ben b", 2.5, 0.0),
        ("gia tri hop dong", 2.0, 0.0),
        ("hieu luc hop dong", 2.0, 0.0),
        ("dieu 1", 1.5, 0.0),
        ("dieu 2", 1.5, 0.0),
        ("dieu khoan", 1.5, 0.0),
        ("hai ben thong nhat", 1.5, 0.0),
    ],
    DocumentType.INVOICE: [
        ("hoa don gia tri gia tang", 6.0, 2.5),
        ("hoa don thanh toan", 6.0, 2.5),
        ("hoa don ban hang", 5.5, 2.0),
        ("hoa don ban le", 5.5, 2.0),
        ("hoa don dien tu", 5.0, 2.0),
        ("phieu tinh tien", 5.0, 2.0),
        ("vat invoice", 4.0, 1.5),
        ("ky hieu", 2.0, 0.5),
        ("mau so", 2.0, 0.5),
        ("so hoa don", 2.5, 0.5),
        ("don vi ban hang", 2.5, 0.0),
        ("ma so thue nguoi ban", 2.5, 0.0),
        ("don vi mua hang", 2.0, 0.0),
        ("ma so thue nguoi mua", 2.0, 0.0),
        ("cong tien hang", 2.0, 0.0),
        ("tien hang", 2.0, 0.0),
        ("mat hang", 1.5, 0.0),
        ("thanh tien", 1.5, 0.0),
        ("t.tien", 1.5, 0.0),
        ("thue suat gtgt", 2.5, 0.0),
        ("tien thue gtgt", 2.5, 0.0),
        ("tong cong tien thanh toan", 2.5, 0.0),
    ],
    DocumentType.PAYMENT_REQUEST: [
        ("giay de nghi thanh toan", 6.0, 2.5),
        ("bieu mau giay de nghi thanh toan", 6.0, 2.5),
        ("phieu de nghi thanh toan", 6.0, 2.5),
        ("de nghi thanh toan", 4.0, 1.5),
        ("so de nghi", 2.5, 0.5),
        ("ngay de nghi", 2.0, 0.5),
        ("don vi thu huong", 2.5, 0.0),
        ("ma so thue don vi thu huong", 2.5, 0.0),
        ("so tien de nghi thanh toan", 3.0, 0.0),
        ("nguoi de nghi", 2.0, 0.0),
        ("kinh gui", 1.5, 0.0),
        ("can cu hoa don", 2.0, 0.0),
        ("can cu hop dong", 1.5, 0.0),
    ],
}


def strip_vietnamese_accents(text: str) -> str:
    """Convert Vietnamese string to lowercase ASCII without diacritics for robust matching."""
    if not text:
        return ""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.lower().split())


def score_page_by_keywords(page_out: PageReadOutput) -> PageClassificationResult:
    """Score a single page across Contract, Invoice, and Payment Request keyword dictionaries (AI-04)."""
    scores: dict[DocumentType, float] = {
        DocumentType.CONTRACT: 0.0,
        DocumentType.INVOICE: 0.0,
        DocumentType.PAYMENT_REQUEST: 0.0,
    }

    # Combine full text and top-of-page header text (y1 <= 0.30)
    full_ascii = strip_vietnamese_accents(page_out.full_text)
    header_blocks = [b.text for b in page_out.ocr_blocks if b.bbox.y1 <= 0.30]
    header_ascii = strip_vietnamese_accents(" ".join(header_blocks))

    for doc_type, rules in _KEYWORD_RULES.items():
        total = 0.0
        for phrase, weight, header_bonus in rules:
            if phrase in full_ascii:
                total += weight
                if header_bonus > 0 and phrase in header_ascii:
                    total += header_bonus
        scores[doc_type] = round(total, 3)

    # BACKEND_WORKFLOW_GUIDE Section 6: Do not treat phieu chi, uy nhiem chi, or bien lai as payment_request
    if "de nghi thanh toan" not in full_ascii and any(
        non_pr in header_ascii or non_pr in full_ascii
        for non_pr in ("phieu chi", "uy nhiem chi", "bien lai thu tien", "bien lai")
    ):
        scores[DocumentType.PAYMENT_REQUEST] = 0.0

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_type, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    if best_score < MIN_RULE_SCORE_THRESHOLD:
        return PageClassificationResult(
            page_number=page_out.page_number,
            document_type=DocumentType.UNKNOWN,
            confidence=0.0,
            raw_scores=scores,
            source="rule",
            needs_review=True,
        )

    # Calculate confidence from absolute score strength and margin over runner-up
    margin_ratio = (best_score - second_score) / max(best_score, 1.0)
    strength = min(1.0, best_score / HIGH_CONFIDENCE_SCORE)
    confidence = round(min(0.99, max(0.35, 0.55 * strength + 0.44 * margin_ratio)), 4)

    is_ambiguous = confidence < AMBIGUOUS_CONFIDENCE_THRESHOLD
    return PageClassificationResult(
        page_number=page_out.page_number,
        document_type=best_type if not is_ambiguous else DocumentType.UNKNOWN,
        confidence=confidence if not is_ambiguous else round(confidence, 4),
        raw_scores=scores,
        source="rule",
        needs_review=is_ambiguous,
    )


def classify_page_with_ollama_fallback(
    page_out: PageReadOutput,
    rule_result: PageClassificationResult,
    *,
    ollama_base_url: str | None = None,
    ollama_model: str | None = None,
    timeout_seconds: float = 5.0,
) -> PageClassificationResult:
    """Use Ollama (Qwen) fallback only when rule classification is ambiguous and Ollama is configured (AI-05)."""
    if not rule_result.needs_review and rule_result.document_type != DocumentType.UNKNOWN:
        return rule_result

    base_url = (ollama_base_url or os.getenv("OLLAMA_BASE_URL", "")).strip()
    if not base_url:
        return rule_result

    model_name = (ollama_model or os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")).strip()
    page_text = page_out.full_text.strip()
    if len(page_text) < 10:
        return rule_result

    prompt = (
        "Phan loai trang tai lieu tieng Viet sau day vao dung 1 trong 4 nhom: "
        "'contract' (hop dong), 'invoice' (hoa don), 'payment_request' (de nghi thanh toan), "
        "hoac 'unknown' (khong ro).\n"
        "Tra ve JSON: {\"document_type\": \"...\", \"confidence\": 0.0..1.0}\n\n"
        f"Noi dung trang:\n{page_text[:2000]}"
    )

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
        payload = response.json()
        parsed = json.loads(payload.get("response", "{}"))
        raw_type = str(parsed.get("document_type", "unknown")).lower().strip()
        llm_conf = float(parsed.get("confidence", 0.0))
        llm_conf = max(0.0, min(1.0, llm_conf))

        if raw_type in {
            DocumentType.CONTRACT.value,
            DocumentType.INVOICE.value,
            DocumentType.PAYMENT_REQUEST.value,
        } and llm_conf >= AMBIGUOUS_CONFIDENCE_THRESHOLD:
            return PageClassificationResult(
                page_number=page_out.page_number,
                document_type=DocumentType(raw_type),
                confidence=round(llm_conf, 4),
                raw_scores=rule_result.raw_scores,
                source="llm",
                needs_review=False,
            )
    except Exception as exc:
        logger.debug("Ollama page classification fallback skipped/failed: %s", exc)

    return rule_result


def classify_and_split_pages(
    pages_output: list[PageReadOutput],
    *,
    ollama_base_url: str | None = None,
    ollama_model: str | None = None,
) -> tuple[list[DocumentSegment], list[PageClassificationResult]]:
    """Classify each page and merge consecutive pages of the same document type into segments (AI-04 + AI-05)."""
    if not pages_output:
        return (
            [
                DocumentSegment(
                    document_type=DocumentType.UNKNOWN,
                    classification_confidence=0.0,
                    pages=[1],
                    ocr_blocks=[],
                    needs_review=True,
                )
            ],
            [],
        )

    page_results: list[PageClassificationResult] = []
    for idx, page_out in enumerate(pages_output):
        rule_res = score_page_by_keywords(page_out)

        # Continuation heuristic: if a page is slightly below threshold but has positive score
        # for the immediately preceding page's known type (e.g., page 2 of a multi-page contract)
        # and no competing header keyword, inherit the previous page's type.
        if (
            rule_res.document_type == DocumentType.UNKNOWN
            and idx > 0
            and page_results[-1].document_type != DocumentType.UNKNOWN
        ):
            prev_type = page_results[-1].document_type
            prev_type_score = rule_res.raw_scores.get(prev_type, 0.0)
            other_max = max(
                (sc for dt, sc in rule_res.raw_scores.items() if dt != prev_type),
                default=0.0,
            )
            if prev_type_score >= 1.5 and other_max < MIN_RULE_SCORE_THRESHOLD:
                rule_res = PageClassificationResult(
                    page_number=page_out.page_number,
                    document_type=prev_type,
                    confidence=round(max(0.65, page_results[-1].confidence * 0.85), 4),
                    raw_scores=rule_res.raw_scores,
                    source="rule_continuation",
                    needs_review=False,
                )

        final_res = classify_page_with_ollama_fallback(
            page_out,
            rule_res,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
        )
        page_results.append(final_res)

    # Group consecutive pages with the same DocumentType into DocumentSegments
    # Note: If a new page has a strong explicit title header of the SAME type (e.g. two separate invoices back-to-back),
    # split them if the new page contains a primary document title header.
    segments: list[DocumentSegment] = []
    current_pages: list[int] = []
    current_blocks: list[OcrBlock] = []
    current_confs: list[float] = []
    current_type: DocumentType | None = None
    current_review: bool = False

    for page_out, cls_res in zip(pages_output, page_results):
        starts_new_same_type_doc = False
        if (
            current_type is not None
            and cls_res.document_type == current_type
            and current_type in {DocumentType.INVOICE, DocumentType.PAYMENT_REQUEST}
        ):
            header_ascii = strip_vietnamese_accents(
                " ".join(b.text for b in page_out.ocr_blocks if b.bbox.y1 <= 0.25)
            )
            if (
                current_type == DocumentType.INVOICE
                and "hoa don gia tri gia tang" in header_ascii
            ) or (
                current_type == DocumentType.PAYMENT_REQUEST
                and "de nghi thanh toan" in header_ascii
            ):
                starts_new_same_type_doc = True

        if current_type is None:
            current_type = cls_res.document_type
            current_pages = [page_out.page_number]
            current_blocks = list(page_out.ocr_blocks)
            current_confs = [cls_res.confidence]
            current_review = cls_res.needs_review
        elif cls_res.document_type == current_type and not starts_new_same_type_doc:
            current_pages.append(page_out.page_number)
            current_blocks.extend(page_out.ocr_blocks)
            current_confs.append(cls_res.confidence)
            current_review = current_review or cls_res.needs_review
        else:
            avg_conf = round(sum(current_confs) / len(current_confs), 4)
            segments.append(
                DocumentSegment(
                    document_type=current_type,
                    classification_confidence=avg_conf,
                    pages=current_pages,
                    ocr_blocks=current_blocks,
                    needs_review=current_review,
                )
            )
            current_type = cls_res.document_type
            current_pages = [page_out.page_number]
            current_blocks = list(page_out.ocr_blocks)
            current_confs = [cls_res.confidence]
            current_review = cls_res.needs_review

    if current_type is not None:
        avg_conf = round(sum(current_confs) / len(current_confs), 4)
        segments.append(
            DocumentSegment(
                document_type=current_type,
                classification_confidence=avg_conf,
                pages=current_pages,
                ocr_blocks=current_blocks,
                needs_review=current_review,
            )
        )

    return segments, page_results


def segments_to_analyzed_documents(
    segments: list[DocumentSegment],
) -> list[AnalyzedDocument]:
    """Convert DocumentSegments into AnalyzedDocument schema models."""
    return [
        AnalyzedDocument(
            document_type=seg.document_type,
            classification_confidence=seg.classification_confidence,
            pages=seg.pages,
            fields=[],
            ocr_blocks=seg.ocr_blocks,
        )
        for seg in segments
    ]
