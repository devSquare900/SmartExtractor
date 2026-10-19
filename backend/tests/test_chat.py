import pytest
from services import db
from services.chat_service import _format_extracted_fields, _format_ocr_pages, build_system_context

def test_chat_db_operations(tmp_path):
    test_db = str(tmp_path / "test.db")
    db.init_db(test_db)
    
    doc_id = "test-doc-123"
    db.create_document(doc_id, "contract.pdf", "/path/to/contract.pdf", db_path=test_db)
    
    # Empty history initially
    history = db.get_chat_history(doc_id, db_path=test_db)
    assert len(history) == 0

    # Add messages
    m1 = db.add_chat_message(doc_id, "user", "What is the notice period?", db_path=test_db)
    assert m1["role"] == "user"
    assert m1["content"] == "What is the notice period?"

    m2 = db.add_chat_message(doc_id, "assistant", "The notice period is 30 days [Page 2].", db_path=test_db)
    assert m2["role"] == "assistant"

    history = db.get_chat_history(doc_id, db_path=test_db)
    assert len(history) == 2
    assert history[0]["content"] == "What is the notice period?"
    assert history[1]["content"] == "The notice period is 30 days [Page 2]."

    # Clear history
    db.clear_chat_history(doc_id, db_path=test_db)
    history_after = db.get_chat_history(doc_id, db_path=test_db)
    assert len(history_after) == 0


def test_build_system_context():
    doc = {
        "doc_id": "test-uuid",
        "filename": "Service_Agreement.pdf",
        "extracted": {
            "contract_name": {"value": "Master Services Agreement"},
            "document_info": {
                "execution_date": {"value": "2024-01-15", "confidence": 0.95},
                "expiry_date": {"value": "2025-01-14", "confidence": 0.90},
            }
        },
        "pages": [
            {
                "page_num": 1,
                "blocks": [{"text": "Master Services Agreement dated Jan 15, 2024"}]
            },
            {
                "page_num": 2,
                "blocks": [{"text": "Section 8: Either party may terminate with 30 days notice."}]
            }
        ]
    }
    
    context = build_system_context(doc)
    assert "Service_Agreement.pdf" in context
    assert "Master Services Agreement" in context
    assert "Execution Date: 2024-01-15" in context
    assert "PAGE 1" in context
    assert "PAGE 2" in context
    assert "Section 8" in context


def test_format_ocr_pages_preserves_all_pages():
    pages = [
        {"page_num": 1, "blocks": [{"text": "Page 1 intro and recitals"}]},
        {"page_num": 2, "blocks": [{"text": "Page 2 termination clause"}]},
        {"page_num": 3, "blocks": [{"text": "Page 3 liability and indemnity"}]},
    ]

    result = _format_ocr_pages(pages)
    assert "PAGE 1" in result
    assert "Page 1 intro and recitals" in result
    assert "PAGE 2" in result
    assert "Page 2 termination clause" in result
    assert "PAGE 3" in result
    assert "Page 3 liability and indemnity" in result


def test_dynamic_extracted_fields_any_section():
    data = {
        "contract_name": {"value": "Cloud SLA"},
        "custom_compliance_section": {
            "gdpr_compliant": {"value": "Yes", "confidence": 0.99},
            "audit_period": {"value": "Annual", "confidence": 0.88},
        },
        "vendor_details": {
            "vendor_name": {"value": "Acme Corp"},
        }
    }
    result = _format_extracted_fields(data)
    assert "Contract / Document Title: Cloud SLA" in result
    assert "[Custom Compliance Section]" in result
    assert "Gdpr Compliant: Yes [Confidence: 99%]" in result
    assert "[Vendor Details]" in result
    assert "Vendor Name: Acme Corp" in result


def test_chat_system_prompt_isolation_and_silence():
    from services.chat_service import SYSTEM_PROMPT, CHAT_MAX_DOC_CHARS
    assert CHAT_MAX_DOC_CHARS >= 20000
    # Strict isolation
    assert "Strict Single-Document Isolation" in SYSTEM_PROMPT
    assert "ABSOLUTE PROHIBITION" in SYSTEM_PROMPT
    assert "Zero Cross-Contamination" in SYSTEM_PROMPT
    # Professional silence
    assert "Professional Handling of Silence & Omissions" in SYSTEM_PROMPT
    assert "DO NOT give blunt, robotic, or dismissive responses" in SYSTEM_PROMPT


def test_medium_contract_bypasses_bm25_and_keeps_all_pages():
    # 8-page document, each ~1,500 chars (total ~12,000 chars <= 20,000 budget)
    pages = [
        {"page_num": i, "blocks": [{"text": f"Page {i} content: " + ("legal clause " * 120)}]}
        for i in range(1, 9)
    ]
    result = _format_ocr_pages(pages, query="termination for breach")
    for i in range(1, 9):
        assert f"=== PAGE {i} ===" in result

