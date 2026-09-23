import os
import pymupdf as fitz
import cv2

# Render zoom for page images. Text-layer coordinates are scaled by the same factor
# so boxes line up with the rendered image.
ZOOM = 2.0

# A page needs at least this many characters in its text layer to skip OCR.
MIN_TEXT_CHARS = 20


def _words_to_blocks(words, zoom):
    """
    Groups PyMuPDF words into text segments, similar to what OCR returns:
    words on the same line are joined unless separated by a wide gap (e.g. label | value columns).
    """
    lines = {}
    for x0, y0, x1, y1, text, block_no, line_no, _ in words:
        lines.setdefault((block_no, line_no), []).append((x0, y0, x1, y1, text))

    blocks = []
    for line_words in lines.values():
        line_words.sort(key=lambda w: w[0])
        segment = [line_words[0]]
        for word in line_words[1:]:
            prev = segment[-1]
            gap = word[0] - prev[2]
            height = max(prev[3] - prev[1], 1)
            if gap > height * 1.2:
                blocks.append(segment)
                segment = [word]
            else:
                segment.append(word)
        blocks.append(segment)

    result = []
    for segment in blocks:
        x0 = min(w[0] for w in segment) * zoom
        y0 = min(w[1] for w in segment) * zoom
        x1 = max(w[2] for w in segment) * zoom
        y1 = max(w[3] for w in segment) * zoom
        result.append({
            "box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "text": " ".join(w[4] for w in segment),
            "confidence": 1.0,
        })
    return result


def convert_pdf_to_images(file_path: str, images_dir: str) -> list[dict]:
    """
    Renders each page to an image. For PDFs with a real text layer, the page's text blocks
    are extracted directly (faster and more accurate than OCR).

    Returns a list of {"image_path", "text_blocks"} where text_blocks is None when OCR is needed.
    """
    pages = []

    os.makedirs(images_dir, exist_ok=True)

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        doc = fitz.open(file_path)
        try:
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)

                pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM))
                img_path = os.path.join(images_dir, f"page_{page_num + 1}.jpg")
                pix.save(img_path)

                text_blocks = None
                words = page.get_text("words")
                if sum(len(w[4]) for w in words) >= MIN_TEXT_CHARS:
                    text_blocks = _words_to_blocks(words, ZOOM)

                pages.append({"image_path": img_path, "text_blocks": text_blocks})
        finally:
            doc.close()
    else:
        # Images (png, jpg, tiff) are re-saved as jpg so the viewer can always display them.
        img = cv2.imread(file_path)
        if img is None:
            raise ValueError(f"Could not read image file: {os.path.basename(file_path)}")
        img_path = os.path.join(images_dir, "page_1.jpg")
        cv2.imwrite(img_path, img)
        pages.append({"image_path": img_path, "text_blocks": None})

    return pages
