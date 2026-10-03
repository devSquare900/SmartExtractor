import itertools
import os
from types import SimpleNamespace

import httpx
import pytest

from conftest import make_block, make_page
from services import llm_parser
from services.llm_parser import build_field, build_lines, extract_fields, render_lines, select_lines


def contract_pages():
    return [
        make_page([
            make_block("SERVICE AGREEMENT", 100, 50, 500, 80),
            make_block("Execution Date", 100, 120, 300, 140, confidence=0.9),
            make_block("12 October 2023", 400, 120, 600, 140, confidence=0.8),
        ]),
        make_page([
            make_block("Public IP", 100, 100, 250, 120),
            make_block("4", 400, 100, 420, 120),
            make_block("PKR 2,000", 600, 100, 720, 120),
        ], page_number=2),
    ]


def test_rows_are_merged_and_pages_marked():
    lines = build_lines(contract_pages())
    assert render_lines(lines) == "\n".join([
        "--- Page 1 ---",
        "[0] SERVICE AGREEMENT",
        "[1] Execution Date | 12 October 2023",
        "--- Page 2 ---",
        "[2] Public IP | 4 | PKR 2,000",
    ])


def test_everything_is_sent_when_it_fits():
    lines = build_lines(contract_pages())
    assert select_lines(lines, budget=10_000) == lines


def test_over_budget_keeps_keyword_lines_and_marks_gaps():
    blocks = [make_block(f"filler text number {i}", 100, 100 + i * 40, 600, 120 + i * 40) for i in range(40)]
    blocks[20] = make_block("Either party may terminate with 30 days notice", 100, 900, 900, 920)
    lines = build_lines([make_page([make_block("TITLE", 100, 50, 300, 70)]), make_page(blocks, page_number=2),
                         make_page([make_block("Signature", 100, 50, 300, 70)], page_number=3)])

    sent = select_lines(lines, budget=300)
    assert sum(len(ln["text"]) + 8 for ln in sent) <= 300
    texts = [ln["text"] for ln in sent]
    assert "Either party may terminate with 30 days notice" in texts
    assert "TITLE" in texts and "Signature" in texts
    assert "filler text number 30" not in texts
    assert "..." in render_lines(sent).split("\n")


def test_field_box_covers_only_the_value_cell():
    lines = {ln["id"]: ln for ln in build_lines(contract_pages())}
    field = build_field({"value": "12 October 2023", "source_ids": ["1"]}, lines)
    assert field["confidence"] == 0.8
    assert field["page_num"] == 1
    assert field["box"] == [[400, 120], [600, 120], [600, 140], [400, 140]]


def test_value_not_backed_by_its_source_gets_low_confidence():
    lines = {ln["id"]: ln for ln in build_lines(contract_pages())}
    assert build_field({"value": "30 June 2027", "source_ids": [1]}, lines)["confidence"] == 0.5
    assert build_field({"value": "30 June 2027", "source_ids": []}, lines) == {"value": "30 June 2027", "confidence": 0.5}
    assert build_field({"value": "30 June 2027", "source_ids": [99]}, lines)["confidence"] == 0.5


def test_value_wrapping_onto_the_next_row_is_still_backed():
    page = make_page([
        make_block("The duration shall be one", 100, 100, 900, 120, confidence=0.9),
        make_block("year from the Effective Date", 100, 130, 900, 150, confidence=0.7),
    ])
    lines = {ln["id"]: ln for ln in build_lines([page])}
    field = build_field({"value": "one year", "source_ids": [0]}, lines)
    assert field["confidence"] == 0.9
    assert field["box"] == [[100, 100], [900, 100], [900, 120], [100, 120]]


def test_summary_is_not_checked_word_for_word():
    lines = {ln["id"]: ln for ln in build_lines(contract_pages())}
    field = build_field({"value": "Reworded summary.", "source_ids": [1]}, lines, summary=True)
    assert field["confidence"] == 0.85
    assert field["box"] == [[100, 120], [600, 120], [600, 140], [100, 140]]


def test_missing_values_are_empty():
    for raw in (None, {"value": None, "source_ids": []}, {"value": "N/A", "source_ids": []}):
        assert build_field(raw, {}) == {"value": "", "confidence": 1.0}


def test_extract_fields_maps_llm_answer_to_boxes(monkeypatch):
    seen = {}

    def fake_llm(text, keys):
        seen["text"] = text
        return {"execution_date": {"value": "12 October 2023", "source_ids": [1]},
                "mrc": {"value": "PKR 2,000", "source_ids": [2]}}

    monkeypatch.setattr(llm_parser, "extract_data_with_llm", fake_llm)
    fields = extract_fields(contract_pages())
    assert "[2] Public IP | 4 | PKR 2,000" in seen["text"]
    assert fields["execution_date"]["page_num"] == 1
    assert fields["mrc"]["page_num"] == 2
    assert fields["expiry_date"] == {"value": "", "confidence": 1.0}
    assert set(fields) == set(llm_parser.FIELDS)


def test_empty_document_skips_the_llm(monkeypatch):
    monkeypatch.setattr(llm_parser, "extract_data_with_llm", lambda text, keys: 1 / 0)
    assert extract_fields([make_page([])])["execution_date"] == {"value": "", "confidence": 1.0}


def test_contents_page_entries_are_dropped():
    toc = [make_block(f"{i}. CLAUSE TITLE {'.' * 30} {i + 3}", 100, 100 + i * 40, 900, 120 + i * 40) for i in range(1, 8)]
    toc.append(make_block("2", 500, 1600, 520, 1620))
    body = [make_block("Total ........ 5,000", 100, 100, 600, 120), make_block("Thank you", 100, 200, 300, 220)]
    lines = build_lines([make_page(toc), make_page(body, page_number=2)])

    texts = [ln["text"] for ln in llm_parser.drop_contents_lines(lines)]
    assert texts == ["2", "Total ........ 5,000", "Thank you"]


def test_every_field_gets_a_share_and_headings_bring_their_clause():
    blocks = [make_block(f"Payment is due on the date number {i}", 100, 100 + i * 40, 900, 120 + i * 40) for i in range(60)]
    blocks.append(make_block("19. Termination by the Customer", 100, 2600, 600, 2620))
    blocks += [make_block(f"clause body row {i}", 100, 2640 + i * 40, 900, 2660 + i * 40) for i in range(5)]
    lines = build_lines([make_page(blocks, height=4000)])

    texts = [ln["text"] for ln in select_lines(lines, budget=2000)]
    assert "19. Termination by the Customer" in texts
    assert "clause body row 4" in texts
    assert len(texts) < len(lines)


class FakeClient:
    """Stands in for a Groq client; `replies` are returned (or raised) one per call."""

    def __init__(self, name, replies, log):
        self.name, self.replies, self.log = name, replies, log
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **options):
        self.options = options
        return self

    def create(self, **kwargs):
        self.log.append((self.name, self.options["max_retries"]))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def groq_error(cls, status, message):
    return cls(message, response=httpx.Response(status, request=httpx.Request("POST", "http://x")), body=None)


def use_clients(monkeypatch, clients):
    monkeypatch.setattr(llm_parser, "_clients", clients)
    monkeypatch.setattr(llm_parser, "_client_cycle", itertools.cycle(clients))


def test_llm_call_is_repeated_when_no_json_comes_back(monkeypatch):
    log = []
    failure = groq_error(llm_parser.BadRequestError, 400, "json_validate_failed")
    use_clients(monkeypatch, [FakeClient("a", [failure, '{"ok": 1}'], log)])
    assert llm_parser.extract_data_with_llm("[0] text") == {"ok": 1}
    assert log == [("a", 0), ("a", 0)]


def test_keys_take_turns_and_a_rate_limited_key_is_skipped(monkeypatch):
    log = []
    limited = groq_error(llm_parser.RateLimitError, 429, "rate limit")
    use_clients(monkeypatch, [FakeClient("a", ['{"n": 1}', limited], log), FakeClient("b", ['{"n": 2}', '{"n": 3}'], log)])

    assert [llm_parser.extract_data_with_llm("x")["n"] for _ in range(3)] == [1, 2, 3]
    assert [name for name, _ in log] == ["a", "b", "a", "b"]


def test_last_attempt_waits_for_the_rate_limit(monkeypatch):
    log = []
    limited = [groq_error(llm_parser.RateLimitError, 429, "rate limit") for _ in range(3)]
    use_clients(monkeypatch, [FakeClient("a", limited, log)])
    with pytest.raises(RuntimeError, match="Groq LLM Error"):
        llm_parser.extract_data_with_llm("x")
    assert log == [("a", 0), ("a", 0), ("a", 2)]


def test_api_keys_are_read_from_every_groq_variable(monkeypatch):
    for name in [n for n in os.environ if n.startswith("GROQ_API_KEY")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("GROQ_API_KEY", "key-1")
    monkeypatch.setenv("GROQ_API_KEY_2", "key-2, key-1,key-3")
    assert llm_parser._api_keys() == ["key-1", "key-2", "key-3"]


def test_large_document_divides_the_fields_over_the_keys(monkeypatch):
    blocks = [make_block(f"filler row number {i}", 100, 100 + i * 40, 900, 120 + i * 40) for i in range(50)]
    blocks[5] = make_block("MASTER SERVICE AGREEMENT", 100, 300, 900, 320)
    blocks[40] = make_block("19. Termination by the Customer", 100, 1700, 900, 1720)
    calls = {}

    def fake_llm(text, keys):
        calls[tuple(keys)] = text
        answers = {"contract_name": {"value": "MASTER SERVICE AGREEMENT", "source_ids": [5]},
                   "termination_clause": {"value": "Customer may terminate.", "source_ids": [40]}}
        return {key: answers.get(key, {"value": None, "source_ids": []}) for key in keys}

    monkeypatch.setattr(llm_parser, "MAX_INPUT_CHARS", 600)
    monkeypatch.setattr(llm_parser, "_get_clients", lambda: ["key a", "key b"])
    monkeypatch.setattr(llm_parser, "extract_data_with_llm", fake_llm)
    fields = extract_fields([make_page(blocks, height=2200)])

    groups = sorted(calls, key=lambda keys: "contract_name" not in keys)
    assert groups[1] == ("mrc", "mrc_discounted", "otc", "otc_discounted")
    assert sorted(groups[0] + groups[1]) == sorted(llm_parser.FIELDS)
    assert "19. Termination by the Customer" in calls[groups[0]]
    assert list(fields) == list(llm_parser.FIELDS)
    assert fields["contract_name"]["value"] == "MASTER SERVICE AGREEMENT"
    assert fields["termination_clause"]["box"] == [[100, 1700], [900, 1700], [900, 1720], [100, 1720]]


def test_field_groups():
    assert llm_parser.field_groups(1) == [list(llm_parser.FIELDS)]
    assert [len(g) for g in llm_parser.field_groups(2)] == [5, 4]
    assert [len(g) for g in llm_parser.field_groups(99)] == [1] * len(llm_parser.FIELDS)
