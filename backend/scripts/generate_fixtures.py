"""Generate synthetic sample PDFs and Vietnamese invoice image for QA-01 in backend/tests/fixtures/."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _load_vietnamese_font(size: int = 20) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType font supporting Vietnamese Unicode diacritics if available."""
    candidate_paths = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for font_path in candidate_paths:
        if font_path.is_file():
            try:
                return ImageFont.truetype(str(font_path), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def build_text_pdf(file_path: Path, pages_lines: list[list[str]]) -> None:
    """Create a multi-page digital PDF with an embedded Type1 Helvetica text layer."""
    writer = PdfWriter()
    page_w, page_h = 595, 842  # A4 in points

    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    for lines in pages_lines:
        page = writer.add_blank_page(width=page_w, height=page_h)

        font_dict = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_dict}
                )
            }
        )
        page[NameObject("/Resources")] = resources

        ops: list[str] = []
        y = 780
        for idx, line in enumerate(lines):
            font_size = 14 if idx == 0 else 11
            ops.append("BT")
            ops.append(f"/F1 {font_size} Tf")
            ops.append(f"50 {y} Td")
            ops.append(f"({_escape_pdf_text(line)}) Tj")
            ops.append("ET")
            y -= 24

        stream = DecodedStreamObject()
        stream.set_data("\n".join(ops).encode("latin-1", errors="replace"))
        page[NameObject("/Contents")] = ArrayObject([stream])

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("wb") as f:
        writer.write(f)


def render_lines_to_image(
    lines: list[str],
    *,
    skew_angle: float = 0.0,
) -> np.ndarray:
    """Render Vietnamese text lines onto a high-contrast page image (optionally skewed)."""
    w, h = 1000, 1300
    img = Image.new("RGB", (w, h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    title_font = _load_vietnamese_font(size=24)
    body_font = _load_vietnamese_font(size=20)

    y = 90
    for idx, line in enumerate(lines):
        font = title_font if idx == 0 else body_font
        draw.text((70, y), line, fill=(10, 10, 10), font=font)
        y += 52

    np_img = np.array(img)
    if abs(skew_angle) > 0.1:
        center = (w // 2, h // 2)
        rot_mat = cv2.getRotationMatrix2D(center, skew_angle, 1.0)
        np_img = cv2.warpAffine(
            np_img,
            rot_mat,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )
    return np_img


def build_scanned_image_pdf(
    file_path: Path,
    lines: list[str],
    skew_angle: float = 2.0,
) -> None:
    """Create a scanned image-only PDF (no text layer) slightly rotated to test Deskew + OCR."""
    np_img = render_lines_to_image(lines, skew_angle=skew_angle)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np_img).save(file_path, "PDF", resolution=150.0)


def generate_all_fixtures(fixtures_dir: Path | None = None) -> dict[str, Path]:
    """Generate the QA-01 fixture suite and return their paths."""
    if fixtures_dir is None:
        fixtures_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

    contract_lines = [
        "CONG HOA XA HOI CHU NGHIA VIET NAM",
        "HOP DONG KINH TE",
        "So hop dong: HD-2026-001",
        "Ngay ky: 15/10/2026",
        "Ben A (Ben mua): CONG TY TNHH CONG NGHE DOCFLOW VIET NAM",
        "Ma so thue Ben A: 0101234567",
        "Ben B (Ben ban): CONG TY CO PHAN GIAI PHAP PHAN MEM SAO VIET",
        "Ma so thue Ben B: 0309876543",
        "Gia tri hop dong truoc thue: 100.000.000 VND",
        "Thue GTGT (10%): 10.000.000 VND",
        "Tong gia tri hop dong: 110.000.000 VND",
        "So tien bang chu: Mot tram muoi trieu dong chan",
    ]

    invoice_lines = [
        "HOA DON GIA TRI GIA TANG",
        "Ky hieu: 1C26TAA - So hoa don: 0000128",
        "Ngay lap: 18/10/2026",
        "Don vi ban hang: CONG TY CO PHAN GIAI PHAP PHAN MEM SAO VIET",
        "Ma so thue nguoi ban: 0309876543",
        "Don vi mua hang: CONG TY TNHH CONG NGHE DOCFLOW VIET NAM",
        "Ma so thue nguoi mua: 0101234567",
        "Theo hop dong so: HD-2026-001",
        "Cong tien hang: 100.000.000 VND",
        "Thue suat GTGT: 10% - Tien thue GTGT: 10.000.000 VND",
        "Tong cong tien thanh toan: 110.000.000 VND",
        "So tien viet bang chu: Mot tram muoi trieu dong chan",
    ]

    invoice_vietnamese_unicode_lines = [
        "HÓA ĐƠN GIÁ TRỊ GIA TĂNG",
        "Ký hiệu: 1C26TAA - Số hóa đơn: 0000128",
        "Ngày lập: 18/10/2026",
        "Đơn vị bán hàng: CÔNG TY CỔ PHẦN GIẢI PHÁP PHẦN MỀM SAO VIỆT",
        "Mã số thuế người bán: 0309876543",
        "Đơn vị mua hàng: CÔNG TY TNHH CÔNG NGHỆ DOCFLOW VIỆT NAM",
        "Mã số thuế người mua: 0101234567",
        "Theo hợp đồng số: HD-2026-001",
        "Cộng tiền hàng: 100.000.000 VND",
        "Thuế suất GTGT: 10% - Tiền thuế GTGT: 10.000.000 VND",
        "Tổng cộng tiền thanh toán: 110.000.000 VND",
        "Số tiền viết bằng chữ: Một trăm mười triệu đồng chẵn",
    ]

    payment_request_lines = [
        "BIEU MAU GIAY DE NGHI THANH TOAN",
        "So de nghi: DNTT-2026-001",
        "Ngay de nghi: 20/10/2026",
        "Don vi thu huong: CONG TY CO PHAN GIAI PHAP PHAN MEM SAO VIET",
        "Ma so thue don vi thu huong: 0309876543",
        "Can cu hop dong so: HD-2026-001",
        "Can cu hoa don so: 0000128",
        "So tien de nghi thanh toan: 110.000.000 VND",
        "Bang chu: Mot tram muoi trieu dong chan",
    ]

    paths = {
        "contract": fixtures_dir / "sample_contract.pdf",
        "invoice": fixtures_dir / "sample_invoice.pdf",
        "payment_request": fixtures_dir / "sample_payment_request.pdf",
        "merged_dossier": fixtures_dir / "sample_merged_dossier.pdf",
        "scanned_invoice": fixtures_dir / "sample_scanned_invoice.pdf",
        "invoice_image": fixtures_dir / "sample_invoice_image.png",
    }

    build_text_pdf(paths["contract"], [contract_lines])
    build_text_pdf(paths["invoice"], [invoice_lines])
    build_text_pdf(paths["payment_request"], [payment_request_lines])
    build_text_pdf(
        paths["merged_dossier"],
        [contract_lines, invoice_lines, payment_request_lines],
    )
    build_scanned_image_pdf(
        paths["scanned_invoice"],
        invoice_vietnamese_unicode_lines,
        skew_angle=2.0,
    )

    # Save a direct PNG image of a Vietnamese invoice with full diacritics
    vn_img = render_lines_to_image(invoice_vietnamese_unicode_lines, skew_angle=0.0)
    Image.fromarray(vn_img).save(paths["invoice_image"], "PNG")

    return paths


if __name__ == "__main__":
    generated = generate_all_fixtures()
    for name, path in generated.items():
        print(f"[QA-01] Generated {name}: {path} ({path.stat().st_size} bytes)")
