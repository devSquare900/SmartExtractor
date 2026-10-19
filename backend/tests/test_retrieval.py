import pytest
from services.retrieval import BM25Okapi, tokenize, retrieve_relevant_pages

def test_tokenize():
    text = "The Master Services Agreement was executed on October 12, 2023 for $150,000."
    tokens = tokenize(text)
    assert "master" in tokens
    assert "services" in tokens
    assert "agreement" in tokens
    assert "executed" in tokens
    assert "october" in tokens
    assert "$150" in tokens or "150" in tokens
    # Stop words must be filtered
    assert "the" not in tokens
    assert "was" not in tokens
    assert "on" not in tokens
    assert "for" not in tokens

def test_bm25_ranking():
    corpus = [
        tokenize("Page 1: Master Services Agreement between Acme Corp and Cloud Solutions."),
        tokenize("Page 2: Monthly Recurring Charges (MRC) shall be USD 10,000 payable net 30 days."),
        tokenize("Page 3: Either party may terminate this agreement with 60 days written notice for convenience."),
        tokenize("Page 4: Governing Law: This contract shall be governed by the laws of the State of New York.")
    ]
    bm25 = BM25Okapi(corpus)

    # Query 1: Termination notice
    q1 = tokenize("What is the termination notice period?")
    scores1 = bm25.get_scores(q1)
    assert scores1[2] > scores1[0]
    assert scores1[2] > scores1[1]
    assert scores1[2] > scores1[3]

    # Query 2: Pricing / MRC
    q2 = tokenize("Tell me the MRC and payment terms.")
    scores2 = bm25.get_scores(q2)
    assert scores2[1] > scores2[0]
    assert scores2[1] > scores2[2]
    assert scores2[1] > scores2[3]

def test_retrieve_relevant_pages_small_doc():
    pages = [
        {"page_num": 1, "text": "Page 1 title"},
        {"page_num": 2, "text": "Page 2 termination"}
    ]
    # Under budget: All pages returned
    res = retrieve_relevant_pages(pages, "termination", char_budget=5000)
    assert len(res) == 2
    assert res[0][0] == 1
    assert res[1][0] == 2

def test_retrieve_relevant_pages_large_doc_budget():
    pages = [
        {"page_num": 1, "text": "A " * 3000},
        {"page_num": 2, "text": "Termination clause: 30 days notice required. " + "B " * 3000},
        {"page_num": 3, "text": "C " * 3000},
        {"page_num": 4, "text": "D " * 3000},
    ]
    # Budget only fits ~1-2 pages (e.g. 7000 chars)
    res = retrieve_relevant_pages(pages, "termination notice period", char_budget=7000)
    page_nums = [p[0] for p in res]
    assert 2 in page_nums
    total_len = sum(len(p[1]) for p in res)
    assert total_len <= 7500
