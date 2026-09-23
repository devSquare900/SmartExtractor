import json
import os
import re
from statistics import median

from services.normalize import apply_normalization

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "fields.json")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_label(text: str) -> str:
    """Lowercase, no spaces, trailing ':' '-' '.' removed. Keeps '#' so 'Invoice #' stays 'invoice#'."""
    return re.sub(r"\s+", "", text.lower()).rstrip(":-.")


def box_bounds(box):
    xs = [pt[0] for pt in box]
    ys = [pt[1] for pt in box]
    return min(xs), min(ys), max(xs), max(ys)


def merge_boxes(boxes):
    bounds = [box_bounds(b) for b in boxes]
    x0 = min(b[0] for b in bounds)
    y0 = min(b[1] for b in bounds)
    x1 = max(b[2] for b in bounds)
    y1 = max(b[3] for b in bounds)
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def find_block_to_right(anchor_block, all_blocks_on_page, y_tolerance=None):
    """
    Finds the closest text block directly to the right of the anchor block on the same line.
    The tolerance scales with the anchor's height so it works at any resolution.
    """
    if y_tolerance is None:
        y_tolerance = max(8, anchor_block["height"] * 0.6)

    candidates = [
        block for block in all_blocks_on_page
        if block is not anchor_block
        and abs(block["center_y"] - anchor_block["center_y"]) <= y_tolerance
        and block["center_x"] > anchor_block["center_x"]
    ]
    if candidates:
        return min(candidates, key=lambda b: b["center_x"])
    return None


def find_block_below(anchor_block, all_blocks_on_page, max_gap_factor=2.5):
    """
    Finds the closest block directly under the anchor that overlaps it horizontally
    (for layouts where the value sits below its label).
    """
    ax0, _, ax1, ay1 = anchor_block["bounds"]
    max_gap = max(anchor_block["height"], 8) * max_gap_factor

    candidates = []
    for block in all_blocks_on_page:
        if block is anchor_block:
            continue
        bx0, by0, bx1, _ = block["bounds"]
        overlaps_x = bx0 < ax1 and bx1 > ax0
        if overlaps_x and block["center_y"] > anchor_block["center_y"] and by0 - ay1 <= max_gap:
            candidates.append(block)
    if candidates:
        return min(candidates, key=lambda b: b["center_y"])
    return None


def format_field(block, value=None):
    """
    Formats the block into a dictionary with bounding box for frontend highlighting.
    """
    if not block:
        return None
    return {
        "value": value if value is not None else block["text"],
        "box": block["box"],
        "page_num": block["page_num"],
        "confidence": round(block["confidence"], 4),
    }


def label_rank(label_norm: str, field_def: dict, max_label_length: int):
    """
    Returns the index of the matching label (labels are listed in priority order), or None.
    """
    for rank, lbl in enumerate(field_def["labels"]):
        if field_def.get("match") == "exact":
            if label_norm == lbl:
                return rank
        elif len(label_norm) <= max_label_length and lbl in label_norm:
            return rank
    return None


def has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def find_value_block(anchor, page_blocks, field_type):
    """
    Value to the right, else below. Dates and amounts must contain a digit, so unit labels
    like '(USD)' under a column header are skipped and the search looks a little further down.
    """
    if field_type == "text":
        return find_block_to_right(anchor, page_blocks) or find_block_below(anchor, page_blocks)

    others = [b for b in page_blocks if has_digit(b["text"])]
    return (find_block_to_right(anchor, others + [anchor])
            or find_block_below(anchor, others + [anchor], max_gap_factor=5))


def extract_field_value(block, page_blocks, field_def, max_label_length):
    """
    Returns (rank, formatted field) if this block is a label for field_def, else None.
    Handles 'Label: value' in a single block, value to the right, and value below.
    """
    text = block["text"]
    field_type = field_def.get("type", "text")

    if ":" in text:
        label_part, value_part = text.split(":", 1)
        rank = label_rank(normalize_label(label_part), field_def, max_label_length)
        if rank is not None:
            value_part = value_part.strip()
            if value_part and (field_type == "text" or has_digit(value_part)):
                return rank, format_field(block, value_part)
            neighbour = find_value_block(block, page_blocks, field_type)
            return (rank, format_field(neighbour)) if neighbour else None

    rank = label_rank(normalize_label(text), field_def, max_label_length)
    if rank is not None:
        neighbour = find_value_block(block, page_blocks, field_type)
        return (rank, format_field(neighbour)) if neighbour else None

    return None


def build_blocks(ocr_pages: list) -> list:
    all_blocks = []
    for page in ocr_pages:
        page_blocks = []
        for block in page.get("blocks", []):
            box = block["box"]
            x0, y0, x1, y1 = box_bounds(box)
            page_blocks.append({
                "text": block.get("text", "").strip(),
                "page_num": page.get("page_number", 1),
                "center_y": (y0 + y1) / 2,
                "center_x": (x0 + x1) / 2,
                "height": y1 - y0,
                "bounds": (x0, y0, x1, y1),
                "box": box,
                "confidence": float(block.get("confidence", 1.0)),
            })
        page_blocks.sort(key=lambda b: (round(b["center_y"]), b["center_x"]))
        all_blocks.extend(page_blocks)
    return all_blocks


def extract_contract_name(page1_blocks, config):
    keywords = config["contract_title_keywords"]
    by_y = sorted(page1_blocks, key=lambda b: b["center_y"])
    for block in by_y[:15]:
        if any(kw in block["text"].upper() for kw in keywords):
            return format_field(block)
    return format_field(by_y[0]) if by_y else None


def is_header_cell(text: str, header_words: list) -> bool:
    norm = re.sub(r"[^a-z#]", "", text.lower())
    if not norm:
        return False
    return any(norm == w or (len(w) >= 2 and norm.startswith(w)) for w in header_words)


def group_rows(blocks):
    """Groups blocks into visual rows (per page) using a tolerance based on typical text height."""
    rows = []
    for page_num in sorted({b["page_num"] for b in blocks}):
        page_blocks = sorted((b for b in blocks if b["page_num"] == page_num), key=lambda b: b["center_y"])
        heights = [b["height"] for b in page_blocks if b["height"] > 0]
        tolerance = max(6, median(heights) * 0.5) if heights else 15

        current, last_y = [], None
        for block in page_blocks:
            if last_y is None or abs(block["center_y"] - last_y) < tolerance:
                current.append(block)
            else:
                rows.append(sorted(current, key=lambda b: b["center_x"]))
                current = [block]
            last_y = block["center_y"]
        if current:
            rows.append(sorted(current, key=lambda b: b["center_x"]))
    return rows


def assign_to_columns(row, column_centers):
    cells = [""] * len(column_centers)
    for block in row:
        idx = min(range(len(column_centers)), key=lambda i: abs(column_centers[i] - block["center_x"]))
        cells[idx] = f"{cells[idx]} {block['text']}".strip()
    return cells


def extract_line_items(all_blocks, config):
    li_config = config["line_items"]
    result = {"columns": [], "column_centers": [], "rows": []}

    start_idx, end_idx = -1, len(all_blocks)
    for i, block in enumerate(all_blocks):
        text_norm = normalize_label(block["text"])
        if start_idx == -1:
            if any(lbl in text_norm for lbl in li_config["start_labels"]):
                start_idx = i + 1
            continue
        if len(block["text"]) < 50 and any(kw in block["text"].lower() for kw in li_config["stop_keywords"]):
            end_idx = i
            break

    if start_idx == -1:
        return result

    ignore = li_config["ignore_keywords"]
    scope_blocks = [b for b in all_blocks[start_idx:end_idx]
                    if b["text"] and not any(kw in b["text"].lower() for kw in ignore)]
    rows = group_rows(scope_blocks)
    if not rows:
        return result

    def looks_like_header(row):
        hits = sum(is_header_cell(b["text"], li_config["header_words"]) for b in row)
        return hits >= 2 and hits * 2 >= len(row)

    header_idx = next((i for i, row in enumerate(rows[:4]) if looks_like_header(row)), None)

    if header_idx is not None:
        header_row = rows[header_idx]
        columns = [b["text"] for b in header_row]
        column_centers = [b["center_x"] for b in header_row]
        # Rows above the header are table titles; repeated headers (e.g. a second table) are dropped.
        data_rows = [r for r in rows[header_idx + 1:] if not looks_like_header(r)]
    else:
        widest = max(rows, key=len)
        columns = [f"Column {i + 1}" for i in range(len(widest))]
        column_centers = [b["center_x"] for b in widest]
        data_rows = rows

    result["columns"] = columns
    result["column_centers"] = [round(c, 1) for c in column_centers]
    for row in data_rows:
        result["rows"].append({
            "cells": assign_to_columns(row, column_centers),
            "box": merge_boxes([b["box"] for b in row]),
            "page_num": row[0]["page_num"],
            "confidence": round(min(b["confidence"] for b in row), 4),
        })
    return result


def normalize_fields(structured_data: dict, config: dict) -> dict:
    """(Re)computes normalized date/amount values. Used after parsing and after user edits."""
    date_order = config.get("date_order", "DMY")
    for field_def in config["fields"]:
        if field_def.get("type", "text") == "text":
            continue
        section = field_def["section"]
        container = structured_data.get(section) if section else structured_data
        if isinstance(container, dict) and isinstance(container.get(field_def["key"]), dict):
            apply_normalization(container[field_def["key"]], field_def["type"], date_order)
    return structured_data


def parse_extracted_data(ocr_pages: list, config: dict = None) -> dict:
    """
    Parses OCR page output into structured data fields using spatial X,Y coordinates.
    Field labels and keywords come from config/fields.json.
    """
    config = config or load_config()
    max_label_length = config.get("max_label_length", 40)

    structured_data = {
        "contract_name": None,
        "document_info": {},
        "customer_info": {},
        "service_provider": None,
        "line_items": {"columns": [], "rows": []},
    }

    all_blocks = build_blocks(ocr_pages)
    if not all_blocks:
        return structured_data

    page1_blocks = [b for b in all_blocks if b["page_num"] == 1]
    structured_data["contract_name"] = extract_contract_name(page1_blocks, config)

    # For each field keep the match with the best (lowest) label rank; ties go to the first in reading order.
    best = {}
    for page_num in sorted({b["page_num"] for b in all_blocks}):
        page_blocks = [b for b in all_blocks if b["page_num"] == page_num]
        for block in page_blocks:
            for idx, field_def in enumerate(config["fields"]):
                if idx in best and best[idx][0] == 0:
                    continue
                match = extract_field_value(block, page_blocks, field_def, max_label_length)
                if match and (idx not in best or match[0] < best[idx][0]):
                    best[idx] = match

    for idx, (_, field) in best.items():
        field_def = config["fields"][idx]
        container = structured_data[field_def["section"]] if field_def["section"] else structured_data
        container[field_def["key"]] = field

    structured_data["line_items"] = extract_line_items(all_blocks, config)
    return normalize_fields(structured_data, config)
