"""Image preprocessing (OpenCV deskew) and Vietnamese OCR block extraction (AI-01, AI-03).

Implements the hybrid pipeline from section 2.6 of the project plan:
  1. OpenCV Deskew straightens rotated scans/photos.
  2. PaddleOCR / RapidOCR detects text line bounding boxes.
  3. Each line is cropped with margin padding (so Vietnamese diacritics are preserved)
     and recognized by VietOCR (`vgg_seq2seq` / `vgg_transformer`, Apache-2.0) when installed.
"""

from __future__ import annotations

import logging
import os
import unicodedata
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.schemas.common import BoundingBox, OcrBlock

logger = logging.getLogger(__name__)

_PADDLE_OCR_INSTANCE: Any = None
_PADDLE_IMPORT_TRIED: bool = False

_RAPID_OCR_INSTANCE: Any = None
_RAPID_IMPORT_TRIED: bool = False

_VIETOCR_INSTANCE: Any = None
_VIETOCR_IMPORT_TRIED: bool = False


def normalize_vietnamese_text(text: str) -> str:
    """Normalize Vietnamese Unicode string to NFC and collapse extra spaces."""
    normalized = unicodedata.normalize("NFC", text)
    return " ".join(normalized.split())


def clamp01(value: float) -> float:
    """Clamp coordinate into [0.0, 1.0] range."""
    return max(0.0, min(1.0, float(value)))


def make_normalized_bbox(
    x1_px: float,
    y1_px: float,
    x2_px: float,
    y2_px: float,
    width: int,
    height: int,
) -> BoundingBox:
    """Convert pixel coordinates to normalized [0..1] BoundingBox with x1<=x2, y1<=y2."""
    w = max(1, int(width))
    h = max(1, int(height))

    nx1 = clamp01(min(x1_px, x2_px) / w)
    nx2 = clamp01(max(x1_px, x2_px) / w)
    ny1 = clamp01(min(y1_px, y2_px) / h)
    ny2 = clamp01(max(y1_px, y2_px) / h)

    if nx2 < nx1:
        nx1, nx2 = nx2, nx1
    if ny2 < ny1:
        ny1, ny2 = ny2, ny1

    return BoundingBox(
        x1=round(nx1, 6),
        y1=round(ny1, 6),
        x2=round(nx2, 6),
        y2=round(ny2, 6),
    )


def deskew_image(
    image: np.ndarray,
    max_angle: float = 15.0,
) -> tuple[np.ndarray, float]:
    """Detect skew angle of a document image using OpenCV and deskew it.

    Returns:
        Tuple of (deskewed_image, detected_angle_degrees).
    """
    if image is None or image.size == 0:
        return image, 0.0

    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image.copy()

    inv = cv2.bitwise_not(gray)
    _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    coords = np.column_stack(np.where(thresh > 0))
    if coords.shape[0] < 50:
        return image, 0.0

    rect = cv2.minAreaRect(coords.astype(np.float32))
    angle = float(rect[-1])

    # OpenCV minAreaRect angle normalization
    if angle < -45.0:
        angle = -(90.0 + angle)
    elif angle > 45.0:
        angle = 90.0 - angle
    else:
        angle = -angle

    if abs(angle) < 0.3 or abs(angle) > max_angle:
        return image, 0.0

    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        image,
        rot_mat,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated, round(angle, 2)


def _get_paddle_ocr() -> Any:
    """Lazy-load PaddleOCR if installed in the environment."""
    global _PADDLE_OCR_INSTANCE, _PADDLE_IMPORT_TRIED
    if _PADDLE_IMPORT_TRIED:
        return _PADDLE_OCR_INSTANCE

    _PADDLE_IMPORT_TRIED = True
    try:
        from paddleocr import PaddleOCR  # type: ignore[import-not-found]

        _PADDLE_OCR_INSTANCE = PaddleOCR(
            use_angle_cls=True,
            lang="vi",
            show_log=False,
        )
    except Exception as exc:
        logger.debug("PaddleOCR not available: %s", exc)
        _PADDLE_OCR_INSTANCE = None

    return _PADDLE_OCR_INSTANCE


def _get_rapid_ocr() -> Any:
    """Lazy-load RapidOCR (PaddleOCR ONNX runtime detector/recognizer, Apache-2.0)."""
    global _RAPID_OCR_INSTANCE, _RAPID_IMPORT_TRIED
    if _RAPID_IMPORT_TRIED:
        return _RAPID_OCR_INSTANCE

    _RAPID_IMPORT_TRIED = True
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-not-found]

        _RAPID_OCR_INSTANCE = RapidOCR()
    except Exception as exc:
        logger.debug("RapidOCR not available: %s", exc)
        _RAPID_OCR_INSTANCE = None

    return _RAPID_OCR_INSTANCE


def _get_vietocr_predictor() -> Any:
    """Lazy-load VietOCR Predictor for accurate Vietnamese diacritics recognition (Apache-2.0)."""
    global _VIETOCR_INSTANCE, _VIETOCR_IMPORT_TRIED
    if _VIETOCR_IMPORT_TRIED:
        return _VIETOCR_INSTANCE

    _VIETOCR_IMPORT_TRIED = True

    # Compatibility shim for Pillow >= 10 where Image.ANTIALIAS was removed
    if not hasattr(Image, "ANTIALIAS") and hasattr(Image, "Resampling"):
        setattr(Image, "ANTIALIAS", Image.Resampling.LANCZOS)

    try:
        import torch  # type: ignore[import-not-found]
        from vietocr.tool.config import Cfg  # type: ignore[import-not-found]
        from vietocr.tool.predictor import Predictor  # type: ignore[import-not-found]

        default_device = "cuda:0" if torch.cuda.is_available() else "cpu"
        model_name = os.getenv("VIETOCR_MODEL", "vgg_seq2seq").strip()
        device = os.getenv("VIETOCR_DEVICE", default_device).strip()

        config = Cfg.load_config_from_name(model_name)
        config["device"] = device
        config["cnn"]["pretrained"] = False
        config["predictor"]["beamsearch"] = False

        _VIETOCR_INSTANCE = Predictor(config)
        logger.info("Loaded VietOCR predictor (%s on %s)", model_name, device)
    except Exception as exc:
        logger.debug("VietOCR not available yet (falling back to default OCR recognizer): %s", exc)
        _VIETOCR_INSTANCE = None

    return _VIETOCR_INSTANCE


def crop_line_with_margin(
    image: np.ndarray,
    x1_px: float,
    y1_px: float,
    x2_px: float,
    y2_px: float,
    *,
    pad_x: int = 6,
    pad_y: int = 5,
) -> Image.Image:
    """Crop a detected text line with padding so Vietnamese diacritics are not clipped."""
    h, w = image.shape[:2]
    cx1 = max(0, int(np.floor(min(x1_px, x2_px))) - pad_x)
    cy1 = max(0, int(np.floor(min(y1_px, y2_px))) - pad_y)
    cx2 = min(w, int(np.ceil(max(x1_px, x2_px))) + pad_x)
    cy2 = min(h, int(np.ceil(max(y1_px, y2_px))) + pad_y)

    if cx2 <= cx1 or cy2 <= cy1:
        return Image.fromarray(image)

    cropped = image[cy1:cy2, cx1:cx2]
    return Image.fromarray(cropped)


def _recognize_with_vietocr_if_available(
    image: np.ndarray,
    xs: list[float],
    ys: list[float],
    default_text: str,
    default_conf: float,
) -> tuple[str, float, bool]:
    """Recognize cropped line with VietOCR if installed; otherwise return default OCR result."""
    vietocr = _get_vietocr_predictor()
    if vietocr is None:
        return default_text, default_conf, False

    try:
        crop_pil = crop_line_with_margin(
            image,
            min(xs),
            min(ys),
            max(xs),
            max(ys),
        )
        result = vietocr.predict(crop_pil, return_prob=True)
        if isinstance(result, tuple) and len(result) == 2:
            viet_text, prob = str(result[0]), float(result[1])
        else:
            viet_text, prob = str(result), default_conf

        clean_viet = normalize_vietnamese_text(viet_text)
        if clean_viet:
            return clean_viet, clamp01(prob), True
    except Exception as exc:
        logger.debug("VietOCR line prediction failed, using default text: %s", exc)

    return default_text, default_conf, False


def run_ocr_on_image(
    image: np.ndarray,
    *,
    page_number: int = 1,
    fallback_text_hint: str | None = None,
) -> tuple[list[OcrBlock], float, str]:
    """Run deskew + OCR on a rendered page or uploaded image.

    Pipeline priority:
      1. PaddleOCR / RapidOCR text detection + VietOCR Vietnamese recognition (if `vietocr` installed)
      2. PaddleOCR / RapidOCR standalone recognition
      3. OpenCV morphological line box fallback

    Returns:
        Tuple of (ocr_blocks, rotation_degrees, engine_name).
    """
    deskewed, angle = deskew_image(image)
    h, w = deskewed.shape[:2]

    # 1. Try PaddleOCR (+ optional VietOCR line recognizer)
    paddle_ocr = _get_paddle_ocr()
    if paddle_ocr is not None:
        try:
            raw_result = paddle_ocr.ocr(deskewed, cls=True)
            blocks: list[OcrBlock] = []
            used_vietocr = False
            lines = raw_result[0] if raw_result and raw_result[0] else []
            for item in lines:
                poly, (raw_text, conf) = item[0], item[1]
                xs = [float(pt[0]) for pt in poly]
                ys = [float(pt[1]) for pt in poly]
                text_str, conf_val, is_viet = _recognize_with_vietocr_if_available(
                    deskewed,
                    xs,
                    ys,
                    str(raw_text),
                    float(conf),
                )
                used_vietocr = used_vietocr or is_viet
                clean_text = normalize_vietnamese_text(text_str)
                if not clean_text:
                    continue
                bbox = make_normalized_bbox(min(xs), min(ys), max(xs), max(ys), w, h)
                blocks.append(
                    OcrBlock(
                        page=page_number,
                        text=clean_text,
                        confidence=clamp01(conf_val),
                        bbox=bbox,
                    )
                )
            if blocks:
                blocks.sort(key=lambda b: (b.bbox.y1, b.bbox.x1))
                engine_label = "paddleocr+vietocr" if used_vietocr else "paddleocr"
                return blocks, angle, engine_label
        except Exception as exc:
            logger.warning("PaddleOCR execution failed on page %d: %s", page_number, exc)

    # 2. Try RapidOCR (PaddleOCR ONNX detector) + VietOCR line recognizer (if installed)
    rapid_ocr = _get_rapid_ocr()
    if rapid_ocr is not None:
        try:
            raw_lines, _ = rapid_ocr(deskewed)
            blocks = []
            used_vietocr = False
            for item in raw_lines or []:
                poly, raw_text, conf = item[0], item[1], item[2]
                xs = [float(pt[0]) for pt in poly]
                ys = [float(pt[1]) for pt in poly]
                text_str, conf_val, is_viet = _recognize_with_vietocr_if_available(
                    deskewed,
                    xs,
                    ys,
                    str(raw_text),
                    float(conf),
                )
                used_vietocr = used_vietocr or is_viet
                clean_text = normalize_vietnamese_text(text_str)
                if not clean_text:
                    continue
                bbox = make_normalized_bbox(min(xs), min(ys), max(xs), max(ys), w, h)
                blocks.append(
                    OcrBlock(
                        page=page_number,
                        text=clean_text,
                        confidence=clamp01(conf_val),
                        bbox=bbox,
                    )
                )
            if blocks:
                blocks.sort(key=lambda b: (b.bbox.y1, b.bbox.x1))
                engine_label = "paddleocr-onnx+vietocr" if used_vietocr else "paddleocr-onnx"
                return blocks, angle, engine_label
        except Exception as exc:
            logger.warning("RapidOCR execution failed on page %d: %s", page_number, exc)

    # 3. Lightweight OpenCV morphological line box detector fallback
    blocks = _detect_opencv_text_blocks(
        deskewed,
        page_number=page_number,
        fallback_text_hint=fallback_text_hint,
    )
    return blocks, angle, "opencv-fallback"


def _detect_opencv_text_blocks(
    image: np.ndarray,
    *,
    page_number: int,
    fallback_text_hint: str | None = None,
) -> list[OcrBlock]:
    """Detect text line bounding boxes using OpenCV morphology for offline/CI runs."""
    h, w = image.shape[:2]
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image

    inv = cv2.bitwise_not(gray)
    _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 35), max(3, h // 200)))
    dilated = cv2.dilate(thresh, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < 12 or bh < 6:
            continue
        if bw > w * 0.98 and bh > h * 0.98:
            continue
        boxes.append((x, y, x + bw, x + bh))

    boxes.sort(key=lambda b: (b[1], b[0]))

    hint_lines = [
        normalize_vietnamese_text(line)
        for line in (fallback_text_hint or "").splitlines()
        if normalize_vietnamese_text(line)
    ]

    blocks: list[OcrBlock] = []
    for idx, (x1, y1, x2, y2) in enumerate(boxes):
        text_val = (
            hint_lines[idx]
            if idx < len(hint_lines)
            else f"[SCAN_LINE_{page_number}_{idx + 1}]"
        )
        blocks.append(
            OcrBlock(
                page=page_number,
                text=text_val,
                confidence=0.75,
                bbox=make_normalized_bbox(x1, y1, x2, y2, w, h),
            )
        )

    if not blocks and hint_lines:
        for idx, line in enumerate(hint_lines):
            y_top = min(0.9, 0.1 + idx * 0.05)
            blocks.append(
                OcrBlock(
                    page=page_number,
                    text=line,
                    confidence=0.75,
                    bbox=BoundingBox(x1=0.1, y1=y_top, x2=0.9, y2=min(1.0, y_top + 0.04)),
                )
            )

    return blocks
