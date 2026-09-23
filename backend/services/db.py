import glob
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

STORAGE_DIR = os.environ.get("SMARTEXTRACTOR_STORAGE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage"))
DB_PATH = os.environ.get("SMARTEXTRACTOR_DB", os.path.join(STORAGE_DIR, "smartextractor.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id         TEXT PRIMARY KEY,
    filename       TEXT NOT NULL,
    file_path      TEXT,
    status         TEXT NOT NULL,
    error          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT,
    pages_json     TEXT,
    extracted_json TEXT,
    edited_json    TEXT,
    summary_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);
"""

LIST_COLUMNS = ("doc_id, filename, status, error, created_at, updated_at, summary_json, "
                "edited_json IS NOT NULL AS edited")


@contextmanager
def connect(db_path: str = None):
    conn = sqlite3.connect(db_path or DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str = None):
    os.makedirs(os.path.dirname(db_path or DB_PATH), exist_ok=True)
    with connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(documents)")}
        if "summary_json" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN summary_json TEXT")


def _now():
    return datetime.now().isoformat()


def create_document(doc_id: str, filename: str, file_path: str, db_path: str = None):
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO documents (doc_id, filename, file_path, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'processing', ?, ?)",
            (doc_id, filename, file_path, _now(), _now()),
        )


def update_document(doc_id: str, db_path: str = None, **fields):
    """Updates columns. 'pages', 'extracted' and 'edited' are stored as JSON."""
    columns = {}
    for key, value in fields.items():
        if key in ("pages", "extracted", "edited", "summary"):
            columns[f"{key}_json"] = json.dumps(value) if value is not None else None
        else:
            columns[key] = value
    columns["updated_at"] = _now()
    assignments = ", ".join(f"{col} = ?" for col in columns)
    with connect(db_path) as conn:
        conn.execute(f"UPDATE documents SET {assignments} WHERE doc_id = ?", (*columns.values(), doc_id))


def list_documents(db_path: str = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(f"SELECT {LIST_COLUMNS} FROM documents ORDER BY created_at DESC").fetchall()
    docs = []
    for r in rows:
        doc = dict(r)
        raw = doc.pop("summary_json")
        doc["summary"] = json.loads(raw) if raw else None
        doc["edited"] = bool(doc["edited"])
        docs.append(doc)
    return docs


def get_document(doc_id: str, db_path: str = None):
    """Returns the full document (with pages/extracted/edited decoded) or None."""
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if row is None:
        return None
    doc = dict(row)
    for key in ("pages", "extracted", "edited", "summary"):
        raw = doc.pop(f"{key}_json")
        doc[key] = json.loads(raw) if raw else None
    return doc


def delete_document(doc_id: str, db_path: str = None) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    return cur.rowcount > 0


def import_legacy_json(ocr_results_dir: str, uploads_dir: str, reparse, db_path: str = None) -> int:
    """
    One-time import of the old storage/ocr_results/*.json files. Completed documents are
    re-parsed so they get the current extracted-data format. The JSON files are left in place.
    """
    imported = 0
    with connect(db_path) as conn:
        known = {r[0] for r in conn.execute("SELECT doc_id FROM documents")}

    for path in glob.glob(os.path.join(ocr_results_dir, "*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        doc_id = data.get("doc_id")
        if not doc_id or doc_id in known:
            continue

        uploads = glob.glob(os.path.join(uploads_dir, f"{doc_id}.*"))
        file_path = uploads[0] if uploads else None
        ext = os.path.splitext(file_path)[1] if file_path else ""
        pages = data.get("pages") or []
        status = data.get("status") or "error"
        error = data.get("error")
        if status == "processing":
            # The server stopped mid-processing; this job will never finish.
            status, error = "error", "Processing was interrupted. Please upload again."
        extracted = reparse(pages) if status == "completed" else None

        with connect(db_path) as conn:
            conn.execute(
                "INSERT INTO documents (doc_id, filename, file_path, status, error, created_at, updated_at, "
                "pages_json, extracted_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, f"Doc_{doc_id[:6]}{ext}", file_path, status, error,
                 data.get("created_at") or _now(), _now(),
                 json.dumps(pages), json.dumps(extracted) if extracted is not None else None),
            )
        imported += 1
    return imported


def ids_needing_summary(db_path: str = None) -> list[str]:
    """Completed documents whose summary is missing or from an older format."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT doc_id FROM documents WHERE status = 'completed' "
            "AND (summary_json IS NULL OR summary_json NOT LIKE '%field_status%')").fetchall()
    return [r[0] for r in rows]


def mark_interrupted(db_path: str = None):
    """Documents left 'processing' by a previous server run can never finish."""
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE documents SET status = 'error', error = 'Processing was interrupted. Please upload again.' "
            "WHERE status = 'processing'"
        )
