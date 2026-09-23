import csv
import io
import os
import re
import shutil
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, BackgroundTasks, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from services import db
from services.pdf_processor import convert_pdf_to_images
from services.ocr_engine import recognize_region, run_ocr_on_images
from services.cell_recovery import recover_empty_cells
from services.parser import load_config, normalize_fields, parse_extracted_data

STORAGE_DIR = os.environ.get("SMARTEXTRACTOR_STORAGE", os.path.join(os.path.dirname(__file__), "storage"))
UPLOAD_DIR = os.path.join(STORAGE_DIR, "uploads")
OCR_RESULTS_DIR = os.path.join(STORAGE_DIR, "ocr_results")  # legacy JSON storage, imported on startup
IMAGES_DIR = os.path.join(STORAGE_DIR, "images")

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

# Expected leading bytes for each allowed extension, so a renamed file is rejected.
FILE_SIGNATURES = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".tif": [b"II*\x00", b"MM\x00*"],
    ".tiff": [b"II*\x00", b"MM\x00*"],
}

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

for directory in (UPLOAD_DIR, OCR_RESULTS_DIR, IMAGES_DIR):
    os.makedirs(directory, exist_ok=True)


def compute_summary(data: dict, pages: list, config: dict = None) -> dict:
    """Small per-document summary used by the dashboard and document list."""
    config = config or load_config()
    threshold = config.get("low_confidence_threshold", 0.85)
    data = data or {}

    def get(section, key):
        field = (data.get(section) or {}).get(key) if section else data.get(key)
        return field if isinstance(field, dict) else None

    fields = [get(f["section"], f["key"]) for f in config["fields"] if f["section"]]
    rows = (data.get("line_items") or {}).get("rows") or []
    scored = [item["confidence"] for item in [*fields, *rows]
              if item and not item.get("manual") and isinstance(item.get("confidence"), (int, float))]

    field_status = {}
    for f, field in zip([f for f in config["fields"] if f["section"]], fields):
        value = (field or {}).get("value") or ""
        low = field and not field.get("manual") and isinstance(field.get("confidence"), (int, float)) \
            and field["confidence"] < threshold
        field_status[f"{f['section']}.{f['key']}"] = "missing" if not value.strip() else "low" if low else "ok"

    amount = get("document_info", "amount") or {}
    date = get("document_info", "date") or {}
    return {
        "title": (get(None, "contract_name") or {}).get("value"),
        "customer": (get("customer_info", "name") or {}).get("value"),
        "amount": amount.get("normalized"),
        "amount_raw": amount.get("value"),
        "currency": amount.get("currency"),
        "date": date.get("normalized") or date.get("value"),
        "fields_found": sum(1 for f in fields if f and (f.get("value") or "").strip()),
        "fields_total": len(fields),
        "line_items": len(rows),
        "low_confidence": sum(1 for c in scored if c < threshold),
        "avg_confidence": round(sum(scored) / len(scored), 4) if scored else None,
        "pages": len(pages or []),
        "field_status": field_status,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.mark_interrupted()
    imported = db.import_legacy_json(OCR_RESULTS_DIR, UPLOAD_DIR, parse_extracted_data)
    if imported:
        print(f"Imported {imported} document(s) from legacy JSON storage")
    config = load_config()
    for doc_id in db.ids_needing_summary():
        doc = db.get_document(doc_id)
        db.update_document(doc_id, summary=compute_summary(current_data(doc), doc["pages"], config))
    yield


app = FastAPI(title="SmartExtractor API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Mount images directory for static serving
app.mount("/api/images", StaticFiles(directory=IMAGES_DIR), name="images")


def get_doc_or_404(doc_id: str) -> dict:
    if not UUID_RE.match(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    doc = db.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def extract_data(doc_id: str, pages: list) -> dict:
    """Parses fields, then re-reads empty table cells on OCR'd pages."""
    extracted = parse_extracted_data(pages)
    try:
        filled = recover_empty_cells(extracted["line_items"], pages, os.path.join(IMAGES_DIR, doc_id), recognize_region)
        if filled:
            print(f"Recovered {filled} empty table cell(s) for {doc_id}")
    except Exception:
        print(f"Cell recovery skipped for {doc_id}: {traceback.format_exc()}")
    return extracted


def process_document(doc_id: str, file_path: str):
    """Background task: render pages, get text (PDF text layer or OCR), parse fields."""
    try:
        pages = convert_pdf_to_images(file_path, os.path.join(IMAGES_DIR, doc_id))
        ocr_pages = run_ocr_on_images(pages)
        extracted = extract_data(doc_id, ocr_pages)
        db.update_document(doc_id, status="completed", error=None, pages=ocr_pages, extracted=extracted,
                           summary=compute_summary(extracted, ocr_pages))
    except Exception as e:
        print(f"Error processing {doc_id}: {traceback.format_exc()}")
        db.update_document(doc_id, status="error", error=str(e) or e.__class__.__name__)


@app.post("/api/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    original_name = os.path.basename(file.filename or "").strip()[:200] or "document"
    file_ext = os.path.splitext(original_name)[1].lower()
    if file_ext not in FILE_SIGNATURES:
        raise HTTPException(status_code=400, detail="Unsupported file format. Use PDF, PNG, JPG or TIFF.")

    doc_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{doc_id}{file_ext}")

    # Stream to disk in chunks so large files never sit fully in memory.
    size = 0
    try:
        with open(file_path, "wb") as f:
            first_chunk = True
            while chunk := await file.read(1024 * 1024):
                if first_chunk:
                    if not any(chunk.startswith(sig) for sig in FILE_SIGNATURES[file_ext]):
                        raise HTTPException(status_code=400,
                                            detail="File content does not match its extension.")
                    first_chunk = False
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413,
                                        detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
                f.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="File is empty.")
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise

    db.create_document(doc_id, original_name, file_path)
    background_tasks.add_task(process_document, doc_id, file_path)

    return {"doc_id": doc_id, "filename": original_name, "message": "Document uploaded and processing started"}


@app.get("/api/documents")
def list_documents():
    return db.list_documents()


@app.get("/api/documents/{doc_id}")
def get_document_info(doc_id: str):
    doc = get_doc_or_404(doc_id)
    info = {k: doc[k] for k in ("doc_id", "filename", "status", "error", "created_at", "updated_at", "summary")}
    return {**info, "edited": doc["edited"] is not None}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    doc = get_doc_or_404(doc_id)
    db.delete_document(doc_id)
    if doc.get("file_path") and os.path.exists(doc["file_path"]):
        os.remove(doc["file_path"])
    shutil.rmtree(os.path.join(IMAGES_DIR, doc_id), ignore_errors=True)
    legacy_json = os.path.join(OCR_RESULTS_DIR, f"{doc_id}.json")
    if os.path.exists(legacy_json):
        os.remove(legacy_json)
    return {"deleted": doc_id}


@app.get("/api/documents/{doc_id}/ocr")
def get_document_ocr(doc_id: str):
    doc = get_doc_or_404(doc_id)
    return {"doc_id": doc_id, "status": doc["status"], "pages": doc["pages"] or []}


def current_data(doc: dict) -> dict:
    return doc["edited"] if doc["edited"] is not None else (doc["extracted"] or {})


@app.get("/api/documents/{doc_id}/extracted")
def get_document_extracted_data(doc_id: str):
    doc = get_doc_or_404(doc_id)
    config = load_config()
    return {
        "status": doc["status"],
        "edited": doc["edited"] is not None,
        "low_confidence_threshold": config.get("low_confidence_threshold", 0.85),
        "data": current_data(doc),
    }


@app.put("/api/documents/{doc_id}/extracted")
def save_document_extracted_data(doc_id: str, data: dict = Body(...)):
    doc = get_doc_or_404(doc_id)
    if doc["status"] != "completed":
        raise HTTPException(status_code=409, detail="Document is not processed yet.")
    config = load_config()
    data = normalize_fields(data, config)
    db.update_document(doc_id, edited=data, summary=compute_summary(data, doc["pages"], config))
    return {"edited": True, "data": data}


@app.post("/api/documents/{doc_id}/reextract")
def reextract_document(doc_id: str):
    """Re-runs the parser on stored OCR output (e.g. after changing config/fields.json). Discards edits."""
    doc = get_doc_or_404(doc_id)
    if doc["status"] != "completed":
        raise HTTPException(status_code=409, detail="Document is not processed yet.")
    extracted = extract_data(doc_id, doc["pages"] or [])
    db.update_document(doc_id, extracted=extracted, edited=None, summary=compute_summary(extracted, doc["pages"]))
    return {"edited": False, "data": extracted}


def field_rows(data: dict):
    """Flattens the extracted fields into (section, field, value, normalized) rows."""
    rows = []
    for section, content in data.items():
        if section == "line_items":
            continue
        if isinstance(content, dict) and "value" in content:
            rows.append(("", section, content.get("value", ""), content.get("normalized", "")))
        elif isinstance(content, dict):
            for key, field in content.items():
                if isinstance(field, dict):
                    rows.append((section, key, field.get("value", ""), field.get("normalized", "")))
    return rows


@app.get("/api/documents/{doc_id}/export")
def export_document(doc_id: str, format: str = "json"):
    doc = get_doc_or_404(doc_id)
    data = current_data(doc)
    # Header-safe ASCII filename
    base_name = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.splitext(doc["filename"])[0]).strip() or doc_id

    if format == "json":
        return JSONResponse(
            content={"doc_id": doc_id, "filename": doc["filename"], "data": data},
            headers={"Content-Disposition": f'attachment; filename="{base_name}.json"'},
        )
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Section", "Field", "Value", "Normalized"])
        writer.writerows(field_rows(data))

        line_items = data.get("line_items") or {}
        if line_items.get("rows"):
            writer.writerow([])
            writer.writerow(["Line Items"])
            writer.writerow(line_items.get("columns") or [])
            for row in line_items["rows"]:
                writer.writerow(row.get("cells") or [])
        # UTF-8 BOM so Excel opens non-ASCII text correctly.
        return Response(
            content="﻿" + buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{base_name}.csv"'},
        )
    raise HTTPException(status_code=400, detail="Format must be 'json' or 'csv'.")


@app.get("/api/documents/{doc_id}/file")
def download_original(doc_id: str):
    doc = get_doc_or_404(doc_id)
    if not doc.get("file_path") or not os.path.exists(doc["file_path"]):
        raise HTTPException(status_code=404, detail="Original file not found")
    return FileResponse(doc["file_path"], filename=doc["filename"])


@app.get("/api/documents/{doc_id}/images")
def get_document_images(doc_id: str):
    get_doc_or_404(doc_id)
    doc_images_dir = os.path.join(IMAGES_DIR, doc_id)
    if not os.path.exists(doc_images_dir):
        return []

    # Files are named page_1.jpg, page_2.jpg, ... sort numerically
    files = [f for f in os.listdir(doc_images_dir) if f.endswith((".jpg", ".png"))]
    files.sort(key=lambda x: int(''.join(filter(str.isdigit, x)) or 0))
    return [f"/api/images/{doc_id}/{filename}" for filename in files]
