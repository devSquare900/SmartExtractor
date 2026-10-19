import json
import pytest
from services import db
from services.portfolio_chat_service import _build_portfolio_catalog, _resolve_portfolio_intent

def test_portfolio_db_operations(tmp_path):
    test_db = str(tmp_path / "test.db")
    db.init_db(test_db)

    # Empty initially
    history = db.get_portfolio_chat_history(db_path=test_db)
    assert len(history) == 0

    # Add messages
    m1 = db.add_portfolio_chat_message("user", "List all contracts.", db_path=test_db)
    assert m1["role"] == "user"
    assert m1["content"] == "List all contracts."

    m2 = db.add_portfolio_chat_message("assistant", "Found 5 contracts.", db_path=test_db)
    assert m2["role"] == "assistant"

    history = db.get_portfolio_chat_history(db_path=test_db)
    assert len(history) == 2
    assert history[0]["content"] == "List all contracts."

    # Clear history
    db.clear_portfolio_chat_history(db_path=test_db)
    history_after = db.get_portfolio_chat_history(db_path=test_db)
    assert len(history_after) == 0


def test_build_portfolio_catalog():
    docs = [
        {
            "doc_id": "doc-1",
            "filename": "Shufti_Agreement.pdf",
            "summary": {
                "title": "Cloud SLA",
                "customer": "Shufti Pro",
                "amount_raw": "USD 2,205",
                "date": "2025-02-19"
            },
            "status": "completed"
        },
        {
            "doc_id": "doc-2",
            "filename": "Bank_Islami.pdf",
            "summary": {
                "title": "Banking Core",
                "customer": "Bank Islami",
                "amount_raw": "PKR 1,500,000",
                "date": "2024-05-10"
            },
            "status": "completed"
        }
    ]

    catalog = _build_portfolio_catalog(docs)
    assert "Shufti_Agreement.pdf" in catalog
    assert "Shufti Pro" in catalog
    assert "USD 2,205" in catalog
    assert "Bank_Islami.pdf" in catalog
    assert "Bank Islami" in catalog
    assert "doc-1" in catalog
    assert "doc-2" in catalog


def test_resolve_portfolio_intent_fallback():
    docs = [
        {"doc_id": "doc-1", "filename": "Shufti_Agreement.pdf", "summary": {"title": "Cloud SLA", "customer": "Shufti Pro"}},
        {"doc_id": "doc-2", "filename": "Bank_Islami.pdf", "summary": {"title": "Banking Core", "customer": "Bank Islami"}}
    ]
    # Pass None as client so it falls back to token matching
    intent = _resolve_portfolio_intent("Tell me about Shufti", docs, client=None)
    assert intent["query_type"] == "TARGETED_DOCUMENTS"
    assert "doc-1" in intent["target_doc_ids"]

    # Broad query fallback
    intent_broad = _resolve_portfolio_intent("Show overview of everything", docs, client=None)
    assert intent_broad["query_type"] == "PORTFOLIO_AGGREGATE"


def test_chat_sessions_multi_thread(tmp_path):
    test_db = str(tmp_path / "test_sessions.db")
    db.init_db(test_db)

    # 1. Create Session A
    sA = db.get_or_create_chat_session("session_A", title="New Conversation", db_path=test_db)
    assert sA["session_id"] == "session_A"
    assert sA["title"] == "New Conversation"

    # Add message to Session A - should auto-generate title from first user query
    db.add_portfolio_chat_message("user", "What is the expiry of Bank Islami?", session_id="session_A", db_path=test_db)
    db.add_portfolio_chat_message("assistant", "Expired on 14 Sep 2026", session_id="session_A", db_path=test_db)

    # 2. Create Session B (completely isolated)
    sB = db.get_or_create_chat_session("session_B", title="New Conversation", db_path=test_db)
    db.add_portfolio_chat_message("user", "Compare PTCL liabilities", session_id="session_B", db_path=test_db)
    db.add_portfolio_chat_message("assistant", "PTCL liability is capped at MRC", session_id="session_B", db_path=test_db)

    # 3. Verify Session A history contains only Session A messages
    hist_A = db.get_portfolio_chat_history(session_id="session_A", db_path=test_db)
    assert len(hist_A) == 2
    assert "Bank Islami" in hist_A[0]["content"]

    # 4. Verify Session B history contains only Session B messages
    hist_B = db.get_portfolio_chat_history(session_id="session_B", db_path=test_db)
    assert len(hist_B) == 2
    assert "PTCL" in hist_B[0]["content"]

    # 5. List sessions
    all_sessions = db.list_chat_sessions(db_path=test_db)
    assert len(all_sessions) == 2
    titles = [s["title"] for s in all_sessions]
    assert any("Bank Islami" in t for t in titles)
    assert any("Compare PTCL" in t for t in titles)

    # 6. Delete Session A
    db.delete_chat_session("session_A", db_path=test_db)
    sessions_after = db.list_chat_sessions(db_path=test_db)
    assert len(sessions_after) == 1
    assert sessions_after[0]["session_id"] == "session_B"


def test_expiry_audit_detection(tmp_path):
    test_db = str(tmp_path / "test_expiry.db")
    db.init_db(test_db)

    # Insert an expired contract with explicit expiry
    db.create_document(
        doc_id="doc-exp-1",
        filename="Expired_Contract.pdf",
        file_path="dummy.pdf",
        db_path=test_db
    )
    db.update_document(
        "doc-exp-1",
        db_path=test_db,
        status="completed",
        extracted_json=json.dumps({
            "contract_name": {"value": "Expired SLA"},
            "document_info": {
                "execution_date": {"value": "2020-01-01", "normalized": "2020-01-01"},
                "expiry_date": {"value": "2021-01-01", "normalized": "2021-01-01"}
            }
        })
    )

    # Insert an expired contract derived via tenure
    db.create_document(
        doc_id="doc-exp-2",
        filename="Tenure_Contract.pdf",
        file_path="dummy2.pdf",
        db_path=test_db
    )
    db.update_document(
        "doc-exp-2",
        db_path=test_db,
        status="completed",
        extracted_json=json.dumps({
            "contract_name": {"value": "Tenure Based Agreement"},
            "document_info": {
                "execution_date": {"value": "2018-05-01", "normalized": "2018-05-01"},
                "validity_tenure": {"value": "1 year"}
            }
        })
    )

    from services.portfolio_chat_service import _load_portfolio_records, _build_portfolio_catalog

    records = _load_portfolio_records(db_path=test_db)
    assert len(records) == 2

    r1 = next(r for r in records if r["doc_id"] == "doc-exp-1")
    assert r1["is_expired"] is True
    assert r1["expiry"] == "2021-01-01"
    assert "EXPIRED" in r1["status"]

    r2 = next(r for r in records if r["doc_id"] == "doc-exp-2")
    assert r2["is_expired"] is True
    assert r2["expiry"] == "2019-05-01"
    assert r2["derived_expiry"] is True
    assert "EXPIRED" in r2["status"]

    catalog = _build_portfolio_catalog(records=records)
    assert "Expired_Contract.pdf" in catalog
    assert "Tenure_Contract.pdf" in catalog
    assert "EXPIRED" in catalog


