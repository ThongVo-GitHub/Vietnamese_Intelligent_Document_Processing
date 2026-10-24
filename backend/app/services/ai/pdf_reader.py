"""PDF text-layer extraction (pypdf) and page rendering (pypdfium2) (AI-02)."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader

from app.schemas.common import BoundingBox, OcrBlock
from app.services.ai.ocr_processor import (
    clamp01,
    make_normalized_bbox,
    normalize_vietnamese_text,
    run_ocr_on_image,
)

MIN_TEXT_LAYER_CHARS = 5


@dataclass
class PageReadOutput:
    """Output for a single page after text-layer extraction or OCR fallback."""

    page_number: int
    width: int
    height: int
    has_text_layer: bool
    rotation_degrees: float = 0.0
    engine: str = "pypdf"
    ocr_blocks: list[OcrBlock] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(block.text for block in self.ocr_blocks)


def render_pdf_page_to_numpy(
    file_path: Path,
    page_index: int,
    scale: float = 2.0,
) -> np.ndarray:
    """Render a 0-indexed PDF page to an RGB numpy array using pypdfium2."""
    pdf_doc = pdfium.PdfDocument(str(file_path))
    try:
        page = pdf_doc[page_index]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil().convert("RGB")
        return np.array(pil_image)
    finally:
        pdf_doc.close()


def _extract_pypdf_blocks_for_page(
    page: object,
    page_number: int,
) -> tuple[list[OcrBlock], int, int]:
    """Extract text lines and normalized bounding boxes from a pypdf PageObject."""
    mediabox = getattr(page, "mediabox")
    page_w = max(1.0, float(mediabox.width))
    page_h = max(1.0, float(mediabox.height))

    raw_fragments: list[tuple[str, float, float, float]] = []

    def _visitor(
        text: str,
        cm: list[float],
        tm: list[float],
        font_dict: dict[str, object] | None,
        font_size: float,
    ) -> None:
        if not text or not text.strip():
            return
        # tm is [a, b, c, d, e, f] where (e, f) is translation in user space
        x_pdf = float(tm[4]) if len(tm) >= 6 else float(cm[4])
        y_pdf = float(tm[5]) if len(tm) >= 6 else float(cm[5])
        effective_fs = max(8.0, abs(float(font_size or 12.0)))
        raw_fragments.append((text, x_pdf, y_pdf, effective_fs))

    extract_fn = getattr(page, "extract_text")
    extract_fn(visitor_text=_visitor)

    # Group fragments that lie on approximately the same horizontal line (y_pdf within 4pt)
    merged_lines: list[tuple[str, float, float, float, float]] = []
    for raw_text, x_pdf, y_pdf, fs in raw_fragments:
        lines = [line for line in raw_text.splitlines() if line.strip()]
        for line_idx, line_str in enumerate(lines):
            curr_y = y_pdf - (line_idx * fs * 1.2)
            est_w = min(page_w - max(0.0, x_pdf), max(fs * 0.5, len(line_str) * fs * 0.52))
            if (
                merged_lines
                and abs(merged_lines[-1][2] - curr_y) <= 4.0
                and line_idx == 0
            ):
                prev_str, px1, py, px2, pfs = merged_lines[-1]
                gap = x_pdf - px2
                sep = " " if gap > (pfs * 0.25) and not prev_str.endswith(" ") and not line_str.startswith(" ") else ""
                merged_lines[-1] = (
                    f"{prev_str}{sep}{line_str}",
                    min(px1, x_pdf),
                    py,
                    max(px2, x_pdf + est_w),
                    max(pfs, fs),
                )
            else:
                merged_lines.append((line_str, x_pdf, curr_y, x_pdf + est_w, fs))

    blocks: list[OcrBlock] = []
    for text_line, x1_pdf, y_pdf, x2_pdf, fs in merged_lines:
        clean_line = normalize_vietnamese_text(text_line)
        if not clean_line:
            continue

        # Convert PDF bottom-left origin to top-left normalized [0..1]
        x1_norm = clamp01(x1_pdf / page_w)
        x2_norm = clamp01(max(x1_pdf + fs, x2_pdf) / page_w)
        y_top_norm = clamp01(1.0 - ((y_pdf + fs * 1.15) / page_h))
        y_bot_norm = clamp01(1.0 - (max(0.0, y_pdf - fs * 0.2) / page_h))

        bbox = BoundingBox(
            x1=round(min(x1_norm, x2_norm), 6),
            y1=round(min(y_top_norm, y_bot_norm), 6),
            x2=round(max(x1_norm, x2_norm), 6),
            y2=round(max(y_top_norm, y_bot_norm), 6),
        )
        blocks.append(
            OcrBlock(
                page=page_number,
                text=clean_line,
                confidence=0.99,
                bbox=bbox,
            )
        )

    # Sort top-to-bottom, left-to-right
    blocks.sort(key=lambda b: (b.bbox.y1, b.bbox.x1))
    return blocks, int(round(page_w)), int(round(page_h))


_XML_TAG_LABELS: dict[str, str] = {
    "thdon": "",
    "document_title": "",
    "title": "",
    "shdon": "Số hóa đơn: ",
    "invoice_number": "Số hóa đơn: ",
    "shdong": "Căn cứ Hợp đồng số: ",
    "contract_number": "Số hợp đồng: ",
    "request_number": "Số đề nghị: ",
    "payment_request_number": "Số đề nghị: ",
    "nlap": "Ngày lập: ",
    "issue_date": "Ngày lập: ",
    "contract_date": "Ngày ký: ",
    "request_date": "Ngày đề nghị: ",
    "dvtte": "Đơn vị tiền tệ: ",
    "currency": "Đơn vị tiền tệ: ",
    "tgtcthue": "Cộng tiền hàng: ",
    "subtotal": "Cộng tiền hàng: ",
    "tsuat": "Thuế suất GTGT: ",
    "vat_rate": "Thuế suất GTGT: ",
    "tgtthue": "Tiền thuế GTGT: ",
    "vat_amount": "Tiền thuế GTGT: ",
    "tgtttbso": "Tổng cộng tiền thanh toán: ",
    "total_amount": "Tổng cộng tiền thanh toán: ",
    "payment_amount": "Số tiền đề nghị thanh toán: ",
    "tgtttbchu": "Số tiền viết bằng chữ: ",
    "amount_in_words": "Số tiền viết bằng chữ: ",
    "tax_id": "Mã số thuế bên bán: ",
    "buyer_tax_id": "Mã số thuế bên mua: ",
    "supplier_name": "Đơn vị bán hàng: ",
    "customer_name": "Đơn vị mua hàng: ",
    "payee_name": "Đơn vị thụ hưởng: ",
    "bank_account": "Số tài khoản: ",
    "bank_name": "Tại ngân hàng: ",
}


def _local_tag_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1].lower().strip()
    return tag.lower().strip()


def _read_xml_pages(file_path: Path) -> list[PageReadOutput]:
    """Parse an XML document (e.g. Vietnamese e-invoice XML or structured XML) into PageReadOutput."""
    from defusedxml.ElementTree import fromstring

    raw_bytes = file_path.read_bytes()
    root = fromstring(raw_bytes)
    root_tag = _local_tag_name(root.tag)

    lines: list[str] = []
    if root_tag in {"hdon", "dlhdon", "invoice", "einvoice"}:
        lines.append("HÓA ĐƠN GIÁ TRỊ GIA TĂNG")
    elif root_tag in {"hopdong", "contract"}:
        lines.append("HỢP ĐỒNG KINH TẾ")
    elif root_tag in {"denghithanhtoan", "payment_request", "paymentrequest"}:
        lines.append("GIẤY ĐỀ NGHỊ THANH TOÁN")

    def _walk(elem: object, parent_tag: str = "") -> None:
        tag = _local_tag_name(getattr(elem, "tag", ""))
        text = (getattr(elem, "text", None) or "").strip()
        children = list(elem)  # type: ignore[call-overload]
        if text and not children:
            if tag == "mst":
                if parent_tag in {"nmua", "buyer", "ben_a", "customer"}:
                    lines.append(f"Mã số thuế người mua: {text}")
                else:
                    lines.append(f"Mã số thuế người bán: {text}")
            elif tag == "ten":
                if parent_tag in {"nmua", "buyer", "ben_a", "customer"}:
                    lines.append(f"Đơn vị mua hàng: {text}")
                elif parent_tag in {"nban", "seller", "ben_b", "supplier", "vendor"}:
                    lines.append(f"Đơn vị bán hàng: {text}")
                else:
                    lines.append(text)
            elif tag in _XML_TAG_LABELS:
                prefix = _XML_TAG_LABELS[tag]
                lines.append(f"{prefix}{text}" if prefix else text)
            else:
                lines.append(f"{tag}: {text}")
        for child in children:
            _walk(child, parent_tag=tag)

    _walk(root)

    if not lines:
        lines = ["[XML_DOCUMENT]"]

    blocks: list[OcrBlock] = []
    total_lines = max(len(lines), 1)
    for idx, line in enumerate(lines):
        y1 = round(min(0.95, 0.05 + (idx / total_lines) * 0.85), 6)
        y2 = round(min(0.99, y1 + (0.75 / total_lines)), 6)
        blocks.append(
            OcrBlock(
                page=1,
                text=line,
                confidence=0.99,
                bbox=make_normalized_bbox(50, y1 * 1000, 550, y2 * 1000, 600, 1000),
            )
        )

    return [
        PageReadOutput(
            page_number=1,
            width=600,
            height=1000,
            has_text_layer=True,
            rotation_degrees=0.0,
            engine="xml-parser",
            ocr_blocks=blocks,
        )
    ]


def read_document_pages(
    file_path: Path,
    media_type: str = "application/pdf",
) -> list[PageReadOutput]:
    """Read a PDF, PNG/JPEG image, or XML file and return PageReadOutput for each page (AI-02 + AI-03).

    - For XML (`application/xml`, `.xml`): parses Vietnamese E-Invoice / structured XML directly.
    - For PDFs: checks each page's text layer with `pypdf`. If sufficient text exists,
      extracts text + normalized bounding boxes directly. Otherwise renders page via
      `pypdfium2`, deskews with OpenCV, and runs OCR.
    - For PNG/JPEG images: loads image, deskews with OpenCV, and runs OCR.
    """
    if not file_path.is_file():
        raise FileNotFoundError(file_path)

    normalized_media = media_type.lower().strip()

    if normalized_media in {"application/xml", "text/xml"} or file_path.suffix.lower() == ".xml":
        return _read_xml_pages(file_path)

    if normalized_media in {"image/png", "image/jpeg", "image/jpg"} or file_path.suffix.lower() in {
        ".png",
        ".jpg",
        ".jpeg",
    }:
        pil_img = Image.open(BytesIO(file_path.read_bytes())).convert("RGB")
        np_img = np.array(pil_img)
        h, w = np_img.shape[:2]
        blocks, angle, engine = run_ocr_on_image(np_img, page_number=1)
        if not blocks:
            blocks = [
                OcrBlock(
                    page=1,
                    text="[IMAGE_DOCUMENT]",
                    confidence=0.5,
                    bbox= make_normalized_bbox(0, 0, w, h, w, h),
                )
            ]
        return [
            PageReadOutput(
                page_number=1,
                width=w,
                height=h,
                has_text_layer=False,
                rotation_degrees=angle,
                engine=engine,
                ocr_blocks=blocks,
            )
        ]

    # Default: PDF processing
    reader = PdfReader(str(file_path))
    outputs: list[PageReadOutput] = []

    for idx, page in enumerate(reader.pages):
        page_num = idx + 1
        blocks, page_w, page_h = _extract_pypdf_blocks_for_page(page, page_num)
        total_chars = sum(len(b.text) for b in blocks)

        if total_chars >= MIN_TEXT_LAYER_CHARS:
            outputs.append(
                PageReadOutput(
                    page_number=page_num,
                    width=page_w,
                    height=page_h,
                    has_text_layer=True,
                    rotation_degrees=0.0,
                    engine="pypdf",
                    ocr_blocks=blocks,
                )
            )
        else:
            # Scanned PDF page -> render via pypdfium2 + deskew + OCR
            np_img = render_pdf_page_to_numpy(file_path, idx, scale=2.0)
            img_h, img_w = np_img.shape[:2]
            ocr_blocks, angle, engine = run_ocr_on_image(np_img, page_number=page_num)
            outputs.append(
                PageReadOutput(
                    page_number=page_num,
                    width=img_w,
                    height=img_h,
                    has_text_layer=False,
                    rotation_degrees=angle,
                    engine=engine,
                    ocr_blocks=ocr_blocks,
                )
            )

    return outputs
