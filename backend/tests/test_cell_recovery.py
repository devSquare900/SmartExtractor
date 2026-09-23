from services.cell_recovery import column_bounds, recover_empty_cells


def test_column_bounds_split_between_centers():
    assert column_bounds([100, 300, 700]) == [(0, 200), (200, 500), (500, 900)]


def test_recovers_only_empty_cells_on_ocr_pages(tmp_path):
    (tmp_path / "page_1.jpg").write_bytes(b"x")
    line_items = {
        "column_centers": [100, 300, 700],
        "rows": [
            {"cells": ["4", "Public IP", ""], "box": [[90, 200], [320, 200], [320, 220], [90, 220]], "page_num": 1, "confidence": 0.94},
            {"cells": ["", "Section title", ""], "box": [[200, 250], [400, 250], [400, 270], [200, 270]], "page_num": 1, "confidence": 0.9},
        ],
    }
    calls = []

    def recognize(path, x0, y0, x1, y1):
        calls.append((x0, x1))
        return "4", 0.99

    filled = recover_empty_cells(line_items, [{"page_number": 1, "source": "ocr"}], str(tmp_path), recognize)
    assert filled == 1
    assert calls == [(500, 900)]
    assert line_items["rows"][0]["cells"] == ["4", "Public IP", "4"]
    assert line_items["rows"][0]["recovered"] == [2]
    assert line_items["rows"][1]["cells"] == ["", "Section title", ""]


def test_skips_text_layer_pages(tmp_path):
    (tmp_path / "page_1.jpg").write_bytes(b"x")
    items = {"column_centers": [100, 300], "rows": [
        {"cells": ["a", "b", ""], "box": [[0, 0], [1, 0], [1, 1], [0, 1]], "page_num": 1}]}
    assert recover_empty_cells(items, [{"page_number": 1, "source": "text_layer"}], str(tmp_path),
                               lambda *a: ("x", 1.0)) == 0
