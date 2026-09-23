from conftest import make_block, make_page
from services.parser import find_block_to_right, build_blocks, parse_extracted_data


def test_label_value_to_the_right():
    page = make_page([
        make_block("SERVICE AGREEMENT", 400, 50, 800, 90),
        make_block("Name of Customer", 100, 200, 300, 220),
        make_block("Acme Traders", 400, 202, 600, 222, confidence=0.7),
        make_block("Billing Address", 100, 250, 300, 270),
        make_block("12 Main St, Lahore", 400, 251, 700, 271),
    ])
    data = parse_extracted_data([page])
    assert data["contract_name"]["value"] == "SERVICE AGREEMENT"
    assert data["customer_info"]["name"]["value"] == "Acme Traders"
    assert data["customer_info"]["name"]["confidence"] == 0.7
    assert data["customer_info"]["name"]["page_num"] == 1
    assert data["customer_info"]["billing_address"]["value"] == "12 Main St, Lahore"


def test_inline_label_and_value():
    page = make_page([make_block("Invoice #: INV-0042", 100, 100, 400, 120)])
    data = parse_extracted_data([page])
    assert data["document_info"]["doc_number"]["value"] == "INV-0042"


def test_value_below_label():
    page = make_page([
        make_block("Email Address", 100, 100, 300, 120),
        make_block("ops@acme.pk", 100, 130, 300, 150),
    ])
    data = parse_extracted_data([page])
    assert data["customer_info"]["email"]["value"] == "ops@acme.pk"


def test_amount_label_must_match_exactly():
    page = make_page([
        make_block("Amount in words shall be as per annexure", 100, 100, 700, 120),
        make_block("Something", 800, 100, 900, 120),
        make_block("Grand Total:", 100, 300, 250, 320),
        make_block("PKR 150,000", 400, 300, 550, 320),
    ])
    data = parse_extracted_data([page])
    assert data["document_info"]["amount"]["value"] == "PKR 150,000"
    assert data["document_info"]["amount"]["normalized"] == "150000.00"
    assert data["document_info"]["amount"]["currency"] == "PKR"


def test_date_is_normalized():
    page = make_page([make_block("Date", 100, 100, 160, 120), make_block("05/01/2025", 300, 100, 420, 120)])
    data = parse_extracted_data([page])
    assert data["document_info"]["date"]["normalized"] == "2025-01-05"


def test_right_search_tolerance_scales_with_text_height():
    # Large text (60px high) with a 25px vertical offset: fixed 20px tolerance would miss it.
    blocks = build_blocks([make_page([
        make_block("Customer Name", 100, 100, 500, 160),
        make_block("Big Co", 700, 125, 900, 185),
    ])])
    assert find_block_to_right(blocks[0], blocks)["text"] == "Big Co"


def test_line_items_split_into_columns():
    page = make_page([
        make_block("Scope of Work", 100, 100, 300, 120),
        make_block("Item", 100, 150, 150, 170),
        make_block("Description", 300, 150, 450, 170),
        make_block("Qty", 700, 150, 740, 170),
        make_block("1", 105, 200, 115, 220),
        make_block("Internet 20 Mbps", 300, 200, 500, 220),
        make_block("2", 700, 200, 715, 220),
        make_block("2", 105, 250, 115, 270),
        make_block("Static IP", 300, 250, 420, 270),
        make_block("1", 700, 250, 715, 270),
        make_block("Payment Terms", 100, 320, 300, 340),
        make_block("Net 30", 400, 320, 500, 340),
    ])
    items = parse_extracted_data([page])["line_items"]
    assert items["columns"] == ["Item", "Description", "Qty"]
    assert [r["cells"] for r in items["rows"]] == [["1", "Internet 20 Mbps", "2"], ["2", "Static IP", "1"]]
    assert items["rows"][0]["box"] == [[105, 200], [715, 200], [715, 220], [105, 220]]


def test_empty_input():
    data = parse_extracted_data([])
    assert data["contract_name"] is None
    assert data["line_items"] == {"columns": [], "rows": []}


def test_amount_prefers_grand_total_and_skips_unit_labels():
    page = make_page([
        make_block("Amount", 650, 1085, 760, 1104),
        make_block("Grand Total", 920, 1084, 1030, 1103),
        make_block("(USD)", 680, 1107, 740, 1126),
        make_block("(USD)", 945, 1107, 1005, 1126),
        make_block("1,050", 680, 1165, 740, 1184),
        make_block("1,102.50", 940, 1163, 1010, 1182),
    ])
    amount = parse_extracted_data([page])["document_info"]["amount"]
    assert amount["value"] == "1,102.50"
    assert amount["normalized"] == "1102.50"


def test_line_items_drop_title_rows_and_repeated_headers():
    page = make_page([
        make_block("Scope of Work", 500, 100, 700, 120),
        make_block("Summary of Requirements (Primary)", 400, 150, 800, 170),
        make_block("Sr.#", 100, 200, 150, 220),
        make_block("Description", 300, 200, 450, 220),
        make_block("Quantity", 700, 200, 800, 220),
        make_block("1", 105, 250, 115, 270),
        make_block("RAM-GB", 300, 250, 400, 270),
        make_block("24", 720, 250, 740, 270),
        make_block("Description", 300, 300, 450, 320),
        make_block("Quantity", 700, 300, 800, 320),
        make_block("2", 105, 350, 115, 370),
        make_block("Storage-GB", 300, 350, 420, 370),
        make_block("300", 720, 350, 750, 370),
    ])
    items = parse_extracted_data([page])["line_items"]
    assert items["columns"] == ["Sr.#", "Description", "Quantity"]
    assert [r["cells"] for r in items["rows"]] == [["1", "RAM-GB", "24"], ["2", "Storage-GB", "300"]]
