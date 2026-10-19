import csv
import io
import os
import re
import shutil
import traceback
import uuid
import hashlib
import json
import asyncio
import time
import dataclasses
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger("smartextractor.main")

from fastapi import Body, FastAPI, File, BackgroundTasks, HTTPException, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from services import db
from services.chat_service import stream_chat
from services.portfolio_chat_service import stream_portfolio_chat
from services.pdf_processor import convert_pdf_to_images, is_digital_page
from services.ocr_engine import recognize_region, run_ocr_on_images
from services.cell_recovery import recover_empty_cells
from services.llm_parser import extract_fields
from services.classifier import classify_contract_department
from services.parser import (build_blocks, extract_contract_name, load_config, normalize_fields,
                             parse_extracted_data)
from services.export_service import export_chat_response

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
    scored = [
        item["confidence"] for item in [*fields, *rows]
        if item and not item.get("manual")
        and str(item.get("value") or "").strip()
        and isinstance(item.get("confidence"), (int, float))
    ]

    field_status = {}
    for f, field in zip([f for f in config["fields"] if f["section"]], fields):
        value = (field or {}).get("value") or ""
        low = field and not field.get("manual") and isinstance(field.get("confidence"), (int, float)) \
            and field["confidence"] < threshold and bool(value.strip())
        field_status[f"{f['section']}.{f['key']}"] = "missing" if not value.strip() else "low" if low else "ok"

    amount = get("document_info", "mrc") or get("document_info", "amount") or {}
    date = get("document_info", "execution_date") or get("document_info", "date") or {}
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


MAX_CONCURRENT_DOCS = 2

@dataclasses.dataclass(order=True)
class QueueItem:
    priority: int
    size: int
    timestamp: float
    doc_id: str = dataclasses.field(compare=False)
    file_path: str = dataclasses.field(compare=False)

document_queue = asyncio.PriorityQueue()
workers = []

async def queue_document(doc_id: str, file_path: str):
    is_digital = False
    if file_path.lower().endswith(".pdf"):
        try:
            import pymupdf as fitz
            with fitz.open(file_path) as doc:
                if len(doc) > 0:
                    page = doc.load_page(0)
                    words = page.get_text("words")
                    is_digital = is_digital_page(page, words)
        except Exception:
            pass
    try:
        size = os.path.getsize(file_path)
    except OSError:
        size = 0
    priority = 1 if is_digital else 2
    await document_queue.put(QueueItem(priority, size, time.time(), doc_id, file_path))

async def document_worker():
    while True:
        item = await document_queue.get()
        doc_id, file_path = item.doc_id, item.file_path
        try:
            doc = db.get_document(doc_id)
            if doc:
                db.update_document(doc_id, status="processing", progress_pct=1, progress_msg="Starting...")
                await asyncio.to_thread(process_document, doc_id, file_path)
        except asyncio.CancelledError:
            break
        except Exception as e:
            traceback.print_exc()
        finally:
            document_queue.task_done()

async def async_backfill_departments():
    """Background startup task: classifies any legacy completed documents without blocking server startup."""
    try:
        await asyncio.sleep(2)
        all_docs = db.list_documents()
        all_depts = db.list_departments(include_counts=False)
        for d in all_docs:
            if d.get("status") == "completed" and (not d.get("department") or d.get("department") == "General"):
                full_doc = db.get_document(d["doc_id"])
                if full_doc and full_doc.get("pages"):
                    cls_res = await asyncio.to_thread(
                        classify_contract_department,
                        "",
                        full_doc.get("pages") or [],
                        full_doc.get("filename") or "",
                        current_data(full_doc),
                        all_depts
                    )
                    if cls_res.get("department") and cls_res["department"] != "General":
                        db.update_document_department(d["doc_id"], cls_res["department"])
                        logger.info(f"Auto-classified existing doc {d['filename']} -> {cls_res['department']}")
                    await asyncio.sleep(0.5)
    except Exception as e:
        logger.warning(f"Startup classification backfill note: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.mark_interrupted()
    imported = db.import_legacy_json(OCR_RESULTS_DIR, UPLOAD_DIR, parse_extracted_data)
    if imported:
        logger.info(f"Imported {imported} document(s) from legacy JSON storage")
    config = load_config()
    for doc_id in db.ids_needing_summary():
        doc = db.get_document(doc_id)
        db.update_document(doc_id, summary=compute_summary(current_data(doc), doc["pages"], config))
        
    # Enterprise Queue: Start Workers
    for _ in range(MAX_CONCURRENT_DOCS):
        workers.append(asyncio.create_task(document_worker()))
        
    # Crash Recovery: Requeue pending documents
    queued_docs = db.get_queued_documents()
    for doc in queued_docs:
        await queue_document(doc["doc_id"], doc["file_path"])

    # Startup Auto-Classification: Classify existing completed documents in background (skip in pytest)
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        asyncio.create_task(async_backfill_departments())
        
    yield
    
    # Shutdown workers
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


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
    """Parses fields using the Groq LLM; the line IDs it cites give each field its highlight box."""
    config = load_config()
    fields = extract_fields(pages)
    title = fields.pop("contract_name")
    if not title["value"]:
        # The LLM found no title: fall back to the keyword search on page 1
        page1_blocks = [b for b in build_blocks(pages) if b["page_num"] == 1 and b["text"]]
        title = extract_contract_name(page1_blocks, config) or title

    # Shaped like the legacy parser output so the Frontend doesn't crash
    formatted_data = {
        "contract_name": title,
        "document_info": fields,
        "customer_info": {},
        "line_items": {"columns": [], "rows": []}
    }

    # Normalize fields before saving so that amounts and dates are correctly parsed
    return normalize_fields(formatted_data, config)


def process_document(doc_id: str, file_path: str):
    """Background task: render pages, get text (PDF text layer or OCR), parse fields, and classify department."""
    def progress(pct: int, msg: str):
        db.update_document(doc_id, status="processing", progress_pct=pct, progress_msg=msg)

    try:
        progress(5, "Converting pages...")
        pages = convert_pdf_to_images(file_path, os.path.join(IMAGES_DIR, doc_id), progress_callback=progress)
        ocr_pages = run_ocr_on_images(pages, progress_callback=progress)
        
        progress(80, "Extracting fields and line items...")
        extracted = extract_data(doc_id, ocr_pages)

        progress(90, "Classifying contract department...")
        doc_obj = db.get_document(doc_id)
        current_dept = doc_obj.get("department") if doc_obj else None
        
        if not current_dept or current_dept == "General":
            all_depts = db.list_departments(include_counts=False)
            file_name = doc_obj.get("filename") if doc_obj else ""
            classification = classify_contract_department(
                text="",
                ocr_pages=ocr_pages,
                filename=file_name,
                extracted=extracted,
                departments=all_depts
            )
            assigned_dept = classification.get("department") or "General"
        else:
            assigned_dept = current_dept

        progress(95, "Saving document...")
        db.update_document(doc_id, status="completed", error=None, pages=ocr_pages, extracted=extracted,
                           department=assigned_dept,
                           summary=compute_summary(extracted, ocr_pages), progress_pct=100, progress_msg="Done")
    except Exception as e:
        logger.error(f"Error processing {doc_id}: {traceback.format_exc()}")
        db.update_document(doc_id, status="error", error=str(e) or e.__class__.__name__, progress_msg="Failed")


@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    batch_id: str = Form(None),
    batch_total: int = Form(None),
    department: str = Form(None),
):
    original_name = os.path.basename(file.filename or "").strip()[:200] or "document"
    file_ext = os.path.splitext(original_name)[1].lower()
    if file_ext not in FILE_SIGNATURES:
        raise HTTPException(status_code=400, detail="Unsupported file format. Use PDF, PNG, JPG or TIFF.")

    if batch_id:
        db.create_batch(batch_id=batch_id, total_files=batch_total or 0)

    doc_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{doc_id}{file_ext}")

    # Stream to disk in chunks so large files never sit fully in memory.
    size = 0
    hasher = hashlib.sha256()
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
                hasher.update(chunk) # Hash the PDF bytes
        if size == 0:
            raise HTTPException(status_code=400, detail="File is empty.")
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise

    # --- Deduplication & Combined Hash ---
    # We hash the config rules so if admin adds a new field, it automatically forces a rescan.
    config = load_config()
    rules_json = json.dumps(config, sort_keys=True)
    hasher.update(rules_json.encode('utf-8'))
    file_hash = hasher.hexdigest()

    # Deduplication Logic
    existing_doc_id = db.get_document_by_hash(file_hash)
    
    if existing_doc_id:
        # We found a duplicate! No need to re-scan. (Time & Cost Saved)
        # Clean up the physical file we just saved to save disk space
        if os.path.exists(file_path):
            os.remove(file_path)
        
        if batch_id:
            db.update_document(existing_doc_id, batch_id=batch_id)
        if department and department != "General":
            db.update_document(existing_doc_id, department=department)

        # Update progress so the frontend widget shows it's instantly completed
        db.update_document(existing_doc_id, progress_pct=100, progress_msg="Smart match")
        
        return {
            "doc_id": existing_doc_id, 
            "batch_id": batch_id,
            "filename": original_name, 
            "message": "Recognized existing document. Smart match applied."
        }

    # Not a duplicate. Add to processing queue.
    db.create_document(doc_id, original_name, file_path, file_hash, batch_id=batch_id, department=department or "General")
    db.update_document(doc_id, status="queued", progress_pct=0, progress_msg="Waiting in queue...")
    await queue_document(doc_id, file_path)

    return {"doc_id": doc_id, "batch_id": batch_id, "filename": original_name, "message": "Document queued for processing"}


@app.get("/api/departments")
def get_departments():
    return db.list_departments(include_counts=True)


@app.post("/api/departments")
def create_new_department(payload: dict = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Department name is required.")
    description = (payload.get("description") or "").strip()
    color = (payload.get("color") or "#17332a").strip()
    dept = db.create_department(name=name, description=description, color=color)
    return dept


@app.patch("/api/documents/{doc_id}/department")
def update_doc_department(doc_id: str, payload: dict = Body(...)):
    get_doc_or_404(doc_id)
    dept = (payload.get("department") or "General").strip()
    db.update_document_department(doc_id, dept)
    return {"doc_id": doc_id, "department": dept}


@app.post("/api/documents/bulk-department")
def bulk_update_doc_department(payload: dict = Body(...)):
    doc_ids = payload.get("doc_ids") or []
    department = (payload.get("department") or "General").strip()
    updated_count = db.bulk_update_document_department(doc_ids, department)
    return {"updated_count": updated_count, "department": department}


@app.post("/api/documents/{doc_id}/classify-department")
def reclassify_doc_department(doc_id: str):
    doc = get_doc_or_404(doc_id)
    all_depts = db.list_departments(include_counts=False)
    cls_res = classify_contract_department(
        text="",
        ocr_pages=doc.get("pages") or [],
        filename=doc.get("filename") or "",
        extracted=current_data(doc),
        departments=all_depts
    )
    new_dept = cls_res.get("department") or "General"
    db.update_document_department(doc_id, new_dept)
    return {"doc_id": doc_id, "department": new_dept, "classification": cls_res}


@app.get("/api/documents")
def list_documents(department: str = None):
    return db.list_documents(department=department)


@app.get("/api/batches")
def list_batches():
    return db.list_batches()


@app.get("/api/batches/{batch_id}")
def get_batch_info(batch_id: str):
    batch = db.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@app.delete("/api/batches/{batch_id}")
def delete_batch(batch_id: str):
    doc_ids = db.delete_batch(batch_id)
    for doc_id in doc_ids:
        shutil.rmtree(os.path.join(IMAGES_DIR, doc_id), ignore_errors=True)
    return {"deleted": batch_id, "count": len(doc_ids)}


@app.get("/api/documents/{doc_id}")
def get_document_info(doc_id: str):
    doc = get_doc_or_404(doc_id)
    info = {k: doc[k] for k in ("doc_id", "batch_id", "filename", "status", "error", "created_at", "updated_at", "summary", "department") if k in doc}
    if "department" not in info or not info["department"]:
        info["department"] = "General"
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
    try:
        extracted = extract_data(doc_id, doc["pages"] or [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    db.update_document(doc_id, extracted=extracted, edited=None, summary=compute_summary(extracted, doc["pages"]))
    return {"edited": False, "data": extracted}


@app.post("/api/documents/{doc_id}/reprocess")
async def reprocess_document(doc_id: str):
    """Re-runs the entire pipeline: rendering, AI OCR, and LLM extraction."""
    doc = get_doc_or_404(doc_id)
    if not doc.get("file_path") or not os.path.exists(doc["file_path"]):
        raise HTTPException(status_code=404, detail="Original document file not found on server")
    db.update_document(doc_id, status="queued", error=None, progress_pct=0, progress_msg="Queued for reprocessing...")
    await queue_document(doc_id, doc["file_path"])
    return {"message": "Document queued for complete reprocessing", "doc_id": doc_id}


@app.post("/api/documents/bulk-reprocess")
async def bulk_reprocess_documents(body: dict = Body(...)):
    """Queues multiple documents for reprocessing."""
    doc_ids = body.get("doc_ids", [])
    if not doc_ids:
        raise HTTPException(status_code=400, detail="doc_ids list required")
    queued = []
    for doc_id in doc_ids:
        doc = db.get_document(doc_id)
        if doc and doc.get("file_path") and os.path.exists(doc["file_path"]):
            db.update_document(doc_id, status="queued", error=None, progress_pct=0, progress_msg="Queued for reprocessing...")
            await queue_document(doc_id, doc["file_path"])
            queued.append(doc_id)
    return {"queued_count": len(queued), "doc_ids": queued}


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


@app.get("/api/documents/{doc_id}/chat")
def get_chat(doc_id: str):
    get_doc_or_404(doc_id)
    return db.get_chat_history(doc_id)


@app.post("/api/documents/{doc_id}/chat")
async def chat_document(doc_id: str, payload: dict = Body(...)):
    get_doc_or_404(doc_id)
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    return StreamingResponse(
        stream_chat(doc_id, message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/api/documents/{doc_id}/chat")
def clear_chat(doc_id: str):
    get_doc_or_404(doc_id)
    db.clear_chat_history(doc_id)
    return {"message": "Chat history cleared"}


@app.get("/api/chat/portfolio/sessions")
def get_portfolio_sessions():
    return db.list_chat_sessions()


@app.post("/api/chat/portfolio/sessions")
def create_portfolio_session(payload: dict = Body(default={})):
    title = (payload.get("title") or "New Conversation").strip()
    session_id = payload.get("session_id")
    return db.get_or_create_chat_session(session_id=session_id, title=title)


@app.patch("/api/chat/portfolio/sessions/{session_id}")
def update_portfolio_session(session_id: str, payload: dict = Body(...)):
    title = (payload.get("title") or "").strip()
    if title:
        db.update_chat_session_title(session_id, title)
    return {"session_id": session_id, "title": title}


@app.delete("/api/chat/portfolio/sessions/{session_id}")
def delete_portfolio_session(session_id: str):
    db.delete_chat_session(session_id)
    return {"message": f"Session {session_id} deleted"}


@app.get("/api/chat/portfolio")
def get_portfolio_chat(session_id: str = None):
    return db.get_portfolio_chat_history(session_id=session_id)


@app.post("/api/chat/portfolio")
async def chat_portfolio(payload: dict = Body(...)):
    message = (payload.get("message") or "").strip()
    session_id = payload.get("session_id")
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    return StreamingResponse(
        stream_portfolio_chat(message, session_id=session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/api/chat/portfolio")
def clear_portfolio_chat(session_id: str = None):
    db.clear_portfolio_chat_history(session_id=session_id)
    return {"message": "Portfolio chat history cleared"}


@app.post("/api/chat/export")
def export_chat_document(payload: dict = Body(...)):
    content = (payload.get("content") or "").strip()
    export_format = (payload.get("format") or "excel").strip()
    query = (payload.get("query") or "").strip()
    scope = (payload.get("scope") or "SmartExtractor Intelligence").strip()

    if not content:
        raise HTTPException(status_code=400, detail="Content cannot be empty.")

    try:
        file_bytes, media_type, filename = export_chat_response(
            content=content,
            export_format=export_format,
            query=query,
            scope=scope
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate export: {str(e)}")

    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )



