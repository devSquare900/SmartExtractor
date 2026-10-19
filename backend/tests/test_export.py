import io
import pytest
from fastapi.testclient import TestClient
from main import app
from services.export_service import export_chat_response, parse_chat_markdown

client = TestClient(app)

SAMPLE_MARKDOWN = """# Vendor Financial & Risk Report
Executive overview of analyzed contracts across Data Center and Cloud Services.

| Contract Name | Category | Expiry Date | Monthly Charges | Notice Period |
| --- | --- | --- | --- | --- |
| PTCL Sd Contract - VMs on IaaS | Cloud Services | 2025-04-14 | PKR 1,250,000 | 90 days written notice |
| Bank Islami SLA | Data Center | 2026-09-14 | PKR 12,760,000 | 30-day cure period |

• **Exposure Window:** Bank Islami requires strict 30-day notice for remedy.
• **Recurring Total:** Over PKR 14M committed across both facilities.

---
**Sources:**
• [PTCL Sd Contract · Page 4](doc:doc-1)
• [Bank Islami SLA · Page 5](doc:doc-2)
"""


def test_markdown_parser():
    parsed = parse_chat_markdown(SAMPLE_MARKDOWN)
    assert parsed["title"] == "Vendor Financial & Risk Report"
    assert len(parsed["paragraphs"]) >= 1
    assert len(parsed["tables"]) == 1
    table = parsed["tables"][0]
    assert len(table["headers"]) == 5
    assert len(table["rows"]) == 2
    assert table["rows"][0][0] == "PTCL Sd Contract - VMs on IaaS"
    assert len(parsed["bullets"]) == 2
    assert len(parsed["citations"]) == 2


def test_excel_export_bytes():
    file_bytes, media_type, filename = export_chat_response(
        SAMPLE_MARKDOWN, "excel", query="Compare vendors", scope="Cloud & DC"
    )
    assert len(file_bytes) > 1000
    assert "openxmlformats" in media_type
    assert filename.endswith(".xlsx")


def test_word_export_bytes():
    file_bytes, media_type, filename = export_chat_response(
        SAMPLE_MARKDOWN, "word", query="Compare vendors", scope="Cloud & DC"
    )
    assert len(file_bytes) > 1000
    assert "wordprocessingml" in media_type
    assert filename.endswith(".docx")


def test_pdf_export_bytes():
    file_bytes, media_type, filename = export_chat_response(
        SAMPLE_MARKDOWN, "pdf", query="Compare vendors", scope="Cloud & DC"
    )
    assert len(file_bytes) > 1000
    assert media_type == "application/pdf"
    assert filename.endswith(".pdf")


def test_api_chat_export_endpoint():
    # Excel
    res_xlsx = client.post("/api/chat/export", json={
        "content": SAMPLE_MARKDOWN,
        "format": "excel",
        "query": "Test query",
        "scope": "Test Scope"
    })
    assert res_xlsx.status_code == 200
    assert "openxmlformats" in res_xlsx.headers["content-type"]
    assert len(res_xlsx.content) > 1000

    # Word
    res_docx = client.post("/api/chat/export", json={
        "content": SAMPLE_MARKDOWN,
        "format": "word",
        "query": "Test query"
    })
    assert res_docx.status_code == 200
    assert "wordprocessingml" in res_docx.headers["content-type"]
    assert len(res_docx.content) > 1000

    # PDF
    res_pdf = client.post("/api/chat/export", json={
        "content": SAMPLE_MARKDOWN,
        "format": "pdf",
        "query": "Test query"
    })
    assert res_pdf.status_code == 200
    assert res_pdf.headers["content-type"] == "application/pdf"
    assert len(res_pdf.content) > 1000

    # Validation: empty content
    res_bad = client.post("/api/chat/export", json={"content": "  ", "format": "excel"})
    assert res_bad.status_code == 400

    # Validation: bad format
    res_bad_fmt = client.post("/api/chat/export", json={"content": "Some text", "format": "unsupported"})
    assert res_bad_fmt.status_code == 400
