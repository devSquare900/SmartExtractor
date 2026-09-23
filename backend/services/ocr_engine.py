import threading

import cv2

# PaddleOCR is loaded lazily and shared. It is not thread-safe, so every call
# goes through _ocr_lock (background tasks run in a thread pool).
_ocr = None
_ocr_lock = threading.Lock()


def _get_ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        # use_angle_cls=True to automatically detect orientation
        _ocr = PaddleOCR(use_angle_cls=True, lang='en')
    return _ocr


def ocr_image(img_path: str) -> list[dict]:
    """Runs OCR on one image and returns text blocks with their bounding boxes."""
    with _ocr_lock:
        result = _get_ocr().ocr(img_path, cls=True)

    # Format: [[[[x1, y1], [x2, y2], [x3, y3], [x4, y4]], ('text', confidence)], ...]
    blocks = []
    if result and result[0] is not None:
        for line in result[0]:
            blocks.append({
                "box": line[0],
                "text": line[1][0],
                "confidence": float(line[1][1]),
            })
    return blocks


def run_ocr_on_images(pages: list[dict]) -> list[dict]:
    """
    Builds structured page data. Pages that already have text_blocks (PDF text layer)
    skip OCR; the rest are OCR'd.
    """
    pages_data = []

    for page_idx, page in enumerate(pages):
        img_path = page["image_path"]
        blocks = page.get("text_blocks")
        source = "text_layer"
        if blocks is None:
            print(f"Running OCR on page {page_idx + 1}: {img_path}")
            blocks = ocr_image(img_path)
            source = "ocr"

        img = cv2.imread(img_path)
        height, width = img.shape[:2] if img is not None else (0, 0)

        pages_data.append({
            "page_number": page_idx + 1,
            "width": width,
            "height": height,
            "source": source,
            "blocks": blocks,
        })

    return pages_data


def recognize_region(img_path: str, x0: float, y0: float, x1: float, y1: float, scale: float = 2.0):
    """
    Re-reads one small region (e.g. an empty table cell). Short isolated text such as a
    single digit is often missed by full-page detection but is found in an upscaled crop.
    Returns (text, confidence) or None.
    """
    img = cv2.imread(img_path)
    if img is None:
        return None
    h, w = img.shape[:2]
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(x1)), min(h, int(y1))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    crop = cv2.resize(img[y0:y1, x0:x1], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    with _ocr_lock:
        ocr = _get_ocr()
        detected = ocr.ocr(crop, cls=False)
        lines = detected[0] if detected and detected[0] else []
        if not lines:
            recognized = ocr.ocr(crop, det=False, cls=False)
            lines = [[None, r] for r in (recognized[0] if recognized and recognized[0] else [])]

    lines = [ln for ln in lines if ln[1][0].strip()]
    if not lines:
        return None
    if lines[0][0] is not None:
        lines.sort(key=lambda ln: min(pt[0] for pt in ln[0]))
    text = " ".join(ln[1][0].strip() for ln in lines)
    confidence = min(float(ln[1][1]) for ln in lines)
    # Recognition-only results are less reliable; require a higher score.
    if lines[0][0] is None and confidence < 0.6:
        return None
    return text, confidence
