import importlib
import os

import pytest

fitz = pytest.importorskip("pymupdf")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTEXTRACTOR_STORAGE", str(tmp_path))
    monkeypatch.setenv("SMARTEXTRACTOR_DB", str(tmp_path / "test.db"))
    from services import db
    importlib.reload(db)
    import main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def text_pdf_bytes():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "MASTER SERVICE AGREEMENT", fontsize=16)
    page.insert_text((72, 100), "This Agreement is entered into between Customer and Provider for services.")
    page.insert_text((72, 120), "Customer Name")
    page.insert_text((300, 120), "Acme Traders")
    page.insert_text((72, 150), "Execution Date")
    page.insert_text((300, 150), "12/03/2024")
    data = doc.tobytes()
    doc.close()
    return data


def upload(client, name="contract.pdf", content=None):
    res = client.post("/api/upload", files={"file": (name, content or text_pdf_bytes(), "application/pdf")})
    if res.status_code == 200:
        doc_id = res.json().get("doc_id")
        if doc_id:
            import time
            for _ in range(300):
                d = client.get(f"/api/documents/{doc_id}").json()
                if d.get("status") in ("completed", "error"):
                    break
                time.sleep(0.1)
    return res


def test_upload_uses_pdf_text_layer_and_keeps_filename(client):
    res = upload(client)
    assert res.status_code == 200
    doc_id = res.json()["doc_id"]

    docs = client.get("/api/documents").json()
    assert docs[0]["filename"] == "contract.pdf"
    assert docs[0]["status"] == "completed"

    ocr = client.get(f"/api/documents/{doc_id}/ocr").json()
    assert ocr["pages"][0]["source"] == "text_layer"

    extracted = client.get(f"/api/documents/{doc_id}/extracted").json()
    assert extracted["edited"] is False
    assert extracted["data"]["document_info"]["execution_date"]["normalized"] == "2024-03-12"


def test_rejects_wrong_content_and_extension(client):
    assert upload(client, "fake.pdf", b"hello world").status_code == 400
    assert upload(client, "notes.txt", b"hello").status_code == 400


def test_rejects_too_large(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    assert upload(client).status_code == 413
    assert os.listdir(main.UPLOAD_DIR) == []


def test_edit_reextract_export_delete(client):
    doc_id = upload(client).json()["doc_id"]
    data = client.get(f"/api/documents/{doc_id}/extracted").json()["data"]

    data["document_info"]["execution_date"]["value"] = "1 January 2025"
    saved = client.put(f"/api/documents/{doc_id}/extracted", json=data).json()
    assert saved["data"]["document_info"]["execution_date"]["normalized"] == "2025-01-01"
    assert client.get(f"/api/documents/{doc_id}/extracted").json()["edited"] is True

    csv_res = client.get(f"/api/documents/{doc_id}/export?format=csv")
    assert csv_res.status_code == 200
    assert "1 January 2025" in csv_res.text
    assert 'filename="contract.csv"' in csv_res.headers["content-disposition"]

    client.post(f"/api/documents/{doc_id}/reextract")
    assert client.get(f"/api/documents/{doc_id}/extracted").json()["edited"] is False

    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}").status_code == 404


def test_invalid_doc_id_is_404(client):
    assert client.get("/api/documents/..%2F..%2Fetc/images").status_code == 404
    assert client.get("/api/documents/not-a-uuid").status_code == 404


def test_list_includes_summary(client):
    doc_id = upload(client).json()["doc_id"]
    summary = client.get("/api/documents").json()[0]["summary"]
    assert summary["date"] == "2024-03-12"
    assert summary["pages"] == 1
    assert "AGREEMENT" in client.get(f"/api/documents/{doc_id}").json()["summary"]["title"]


def test_department_endpoints_and_filtering(client):
    # Check default departments seeded
    depts = client.get("/api/departments").json()
    dept_names = [d["name"] for d in depts]
    assert "Data Center" in dept_names
    assert "Cloud Services" in dept_names
    assert "General" in dept_names
    assert "Network & Telecom" not in dept_names
    assert "Software & SaaS" not in dept_names
    assert len(depts) == 3

    # Upload document
    doc_id = upload(client).json()["doc_id"]
    doc_info = client.get(f"/api/documents/{doc_id}").json()
    assert doc_info["department"] in dept_names

    # Update document department
    res = client.patch(f"/api/documents/{doc_id}/department", json={"department": "Data Center"}).json()
    assert res["department"] == "Data Center"
    assert client.get(f"/api/documents/{doc_id}").json()["department"] == "Data Center"

    # Filter documents by department
    filtered_dc = client.get("/api/documents?department=Data Center").json()
    assert len(filtered_dc) >= 1
    assert all(d["department"] == "Data Center" for d in filtered_dc)
    assert any(d["doc_id"] == doc_id for d in filtered_dc)

    filtered_other = client.get("/api/documents?department=Cloud Services").json()
    assert all(d["department"] == "Cloud Services" for d in filtered_other)
    assert not any(d["doc_id"] == doc_id for d in filtered_other)

    # Bulk update
    bulk_res = client.post("/api/documents/bulk-department", json={"doc_ids": [doc_id], "department": "Cloud Services"}).json()
    assert bulk_res["updated_count"] == 1
    assert client.get(f"/api/documents/{doc_id}").json()["department"] == "Cloud Services"
    
    # After moving, doc_id should now be in Cloud Services
    filtered_now = client.get("/api/documents?department=Cloud Services").json()
    assert any(d["doc_id"] == doc_id for d in filtered_now)

    # Create custom department
    new_dept = client.post("/api/departments", json={"name": "Cybersecurity", "description": "Security audits & SOC contracts", "color": "#dc2626"}).json()
    assert new_dept["name"] == "Cybersecurity"
    assert new_dept["slug"] == "cybersecurity"


def test_reprocess_and_bulk_reprocess(client):
    doc_id = upload(client).json()["doc_id"]
    # Single reprocess
    res = client.post(f"/api/documents/{doc_id}/reprocess")
    assert res.status_code == 200
    assert res.json()["doc_id"] == doc_id

    # Bulk reprocess
    bulk_res = client.post("/api/documents/bulk-reprocess", json={"doc_ids": [doc_id]})
    assert bulk_res.status_code == 200
    assert bulk_res.json()["queued_count"] == 1
