import os


def column_bounds(centers: list[float]) -> list[tuple[float, float]]:
    """Left/right x-limits per column, split halfway between neighbouring column centers."""
    bounds = []
    for i, c in enumerate(centers):
        left = (centers[i - 1] + c) / 2 if i > 0 else c - ((centers[1] - c) / 2 if len(centers) > 1 else 60)
        right = (c + centers[i + 1]) / 2 if i < len(centers) - 1 else c + ((c - centers[i - 1]) / 2 if i > 0 else 60)
        bounds.append((left, right))
    return bounds


def recover_empty_cells(line_items: dict, pages: list, images_dir: str, recognize) -> int:
    """
    Fills empty line-item cells by re-reading just that cell's area of the page image.
    Only OCR'd pages are checked (text-layer pages are already exact), and only data rows
    that have at least two filled cells, so section-title rows are left alone.
    `recognize(img_path, x0, y0, x1, y1)` returns (text, confidence) or None.
    Returns the number of cells filled.
    """
    centers = line_items.get("column_centers") or []
    if len(centers) < 2:
        return 0
    bounds = column_bounds(centers)
    ocr_pages = {p.get("page_number"): p for p in pages if p.get("source", "ocr") == "ocr"}

    filled = 0
    for row in line_items.get("rows", []):
        cells = row.get("cells") or []
        if row.get("page_num") not in ocr_pages or not row.get("box"):
            continue
        if sum(1 for c in cells if c.strip()) < 2:
            continue
        img_path = os.path.join(images_dir, f"page_{row['page_num']}.jpg")
        if not os.path.exists(img_path):
            continue

        ys = [pt[1] for pt in row["box"]]
        pad = (max(ys) - min(ys)) * 0.45
        for i, cell in enumerate(cells):
            if cell.strip():
                continue
            left, right = bounds[i]
            result = recognize(img_path, left, min(ys) - pad, right, max(ys) + pad)
            if not result:
                continue
            text, confidence = result
            cells[i] = text
            row.setdefault("recovered", []).append(i)
            row["confidence"] = round(min(row.get("confidence", 1.0), confidence), 4)
            filled += 1
    return filled
