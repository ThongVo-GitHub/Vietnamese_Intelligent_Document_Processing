"""Vietnamese field normalizers and Vietnamese amount-in-words parser (AI-07, AI-09)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.services.ai.classifier import strip_vietnamese_accents


def normalize_date(raw: str | None) -> str | None:
    """Normalize Vietnamese date strings into ISO YYYY-MM-DD format."""
    if not raw or not raw.strip():
        return None

    text = strip_vietnamese_accents(raw)

    # 1. Match "ngay DD thang MM nam YYYY"
    m_vn = re.search(
        r"ngay\s*(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*(\d{4})",
        text,
    )
    if m_vn:
        day, month, year = int(m_vn.group(1)), int(m_vn.group(2)), int(m_vn.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    # 2. Match ISO YYYY-MM-DD or YYYY/MM/DD
    m_iso = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", text)
    if m_iso:
        year, month, day = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    # 3. Match DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m_dmy = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", text)
    if m_dmy:
        day, month, year = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    return None


def normalize_money_amount(raw: str | None) -> str | None:
    """Normalize Vietnamese currency/money strings into a clean Decimal string (e.g. '110000000')."""
    if not raw or not raw.strip():
        return None

    # Repair OCR space between 3-digit thousand groups like "100.000 000" -> "100.000.000"
    cleaned = re.sub(r"(?<=\d)\s+(?=\d{3}(?:\b|\D))", ".", raw.strip())

    # Extract the main numeric token
    m = re.search(r"[-+]?\d[\d.,]*", cleaned)
    if not m:
        return None

    token = m.group(0).strip(".,")
    if not token:
        return None

    # Determine if dots/commas are thousand separators or decimal points
    if "." in token and "," in token:
        if token.rfind(",") > token.rfind("."):
            # Format: 110.000.000,50
            token = token.replace(".", "").replace(",", ".")
        else:
            # Format: 110,000,000.50
            token = token.replace(",", "")
    elif "." in token:
        parts = token.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            token = "".join(parts)
    elif "," in token:
        parts = token.split(",")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            token = "".join(parts)
        else:
            token = token.replace(",", ".")

    try:
        dec = Decimal(token)
    except InvalidOperation:
        return None

    if dec == dec.to_integral_value():
        return str(dec.to_integral_value())
    return str(dec.normalize())


def normalize_currency(raw: str | None) -> str | None:
    """Detect and normalize currency code ('VND', 'USD', 'EUR')."""
    if not raw or not raw.strip():
        return None

    ascii_text = strip_vietnamese_accents(raw)
    if any(k in ascii_text for k in ("usd", "do la", "$")):
        return "USD"
    if any(k in ascii_text for k in ("eur", "euro", "€")):
        return "EUR"
    if (
        any(k in ascii_text for k in ("vnd", "vnđ", "dong"))
        or "đ" in raw.lower()
        or re.search(r"\d\s*d\b", ascii_text)
    ):
        return "VND"
    return None


def normalize_tax_id(raw: str | None) -> str | None:
    """Normalize Vietnamese Tax ID (10 digits or 10-3 branch format)."""
    if not raw or not raw.strip():
        return None

    compact = re.sub(r"\s+", "", raw)
    m = re.search(r"\b(\d{10}(?:-\d{3})?)\b", compact)
    if m:
        return m.group(1)
    return None


def normalize_document_code(raw: str | None) -> str | None:
    """Normalize contract number, invoice number, or payment request number."""
    if not raw or not raw.strip():
        return None

    val = raw.strip().strip(":-.").strip()
    # Fix OCR space in hyphenated code like "HD 2026-001" -> "HD-2026-001"
    val = re.sub(r"\b([A-Za-z]{2,6})\s+(\d{2,4}[-/]\d+)\b", r"\1-\2", val)
    val = re.sub(r"\s+", "", val)
    return val.upper() if val else None


def normalize_vat_rate(raw: str | None) -> str | None:
    """Normalize VAT rate percentage (e.g., '10%' -> '10')."""
    if not raw or not raw.strip():
        return None

    m = re.search(r"\b(\d{1,2}(?:[.,]\d+)?)\s*%", raw)
    if m:
        return m.group(1).replace(",", ".")

    m_num = re.search(r"\b(0|5|8|10)\b", raw)
    if m_num:
        return m_num.group(1)
    return None


_VN_DIGIT_MAP: dict[str, int] = {
    "khong": 0,
    "mot": 1,
    "hai": 2,
    "ba": 3,
    "bon": 4,
    "tu": 4,
    "nam": 5,
    "lam": 5,
    "nham": 5,
    "sau": 6,
    "bay": 7,
    "tam": 8,
    "chin": 9,
}

_VN_MAGNITUDE_MAP: dict[str, int] = {
    "ty": 1_000_000_000,
    "ti": 1_000_000_000,
    "trieu": 1_000_000,
    "nghin": 1_000,
    "ngan": 1_000,
}


def parse_vietnamese_amount_in_words(raw: str | None) -> str | None:
    """Parse Vietnamese amount in words into a numeric string (AI-09).

    Example:
      'Một trăm mười triệu đồng chẵn' -> '110000000'
      'Năm mươi nghìn đồng' -> '50000'
    """
    if not raw or not raw.strip():
        return None

    ascii_text = strip_vietnamese_accents(raw)
    # Remove punctuation and trailing currency/stop words
    tokens = re.findall(r"[a-z]+", ascii_text)
    if not tokens:
        return None

    stop_words = {"dong", "chan", "vnd", "tien", "viet", "bang", "chu", "so", "la"}
    filtered = [t for t in tokens if t not in stop_words]
    if not filtered:
        return None

    total = 0
    current_group = 0
    current_digit: int | None = None
    matched_any = False

    for token in filtered:
        if token in _VN_DIGIT_MAP:
            val = _VN_DIGIT_MAP[token]
            if current_digit is not None:
                current_group += current_digit
            current_digit = val
            matched_any = True
        elif token == "tram":
            hundreds = current_digit if current_digit is not None else 1
            current_group += hundreds * 100
            current_digit = None
            matched_any = True
        elif token == "muoi":
            if current_digit is not None:
                # e.g. "hai muoi" -> 20
                current_group += current_digit * 10
                current_digit = None
            else:
                # e.g. "muoi" (10)
                current_group += 10
            matched_any = True
        elif token in {"le", "linh"}:
            if current_digit is not None:
                current_group += current_digit
                current_digit = None
        elif token in _VN_MAGNITUDE_MAP:
            if current_digit is not None:
                current_group += current_digit
                current_digit = None
            if current_group == 0:
                current_group = 1
            total += current_group * _VN_MAGNITUDE_MAP[token]
            current_group = 0
            matched_any = True

    if current_digit is not None:
        current_group += current_digit

    total += current_group
    if not matched_any or total <= 0:
        return None

    return str(total)
