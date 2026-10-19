import glob
import json
import logging
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("smartextractor.db")

STORAGE_DIR = os.environ.get("SMARTEXTRACTOR_STORAGE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage"))
DB_PATH = os.environ.get("SMARTEXTRACTOR_DB", os.path.join(STORAGE_DIR, "smartextractor.db"))
DATABASE_URL = os.environ.get("DATABASE_URL")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id     TEXT PRIMARY KEY,
    batch_name   TEXT,
    created_at   TEXT NOT NULL,
    total_files  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS departments (
    id          TEXT PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    description TEXT,
    color       TEXT DEFAULT '#17332a',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id         TEXT PRIMARY KEY,
    batch_id       TEXT,
    filename       TEXT NOT NULL,
    file_path      TEXT,
    status         TEXT NOT NULL,
    error          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT,
    pages_json     TEXT,
    extracted_json TEXT,
    edited_json    TEXT,
    summary_json   TEXT,
    progress_pct   INTEGER,
    progress_msg   TEXT,
    file_hash      TEXT,
    department     TEXT DEFAULT 'General'
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id     TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);
CREATE INDEX IF NOT EXISTS idx_documents_batch_id ON documents(batch_id);
CREATE INDEX IF NOT EXISTS idx_documents_department ON documents(department);
CREATE INDEX IF NOT EXISTS idx_chat_messages_doc_id ON chat_messages(doc_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at ON chat_sessions(updated_at);
"""

SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id     TEXT PRIMARY KEY,
    batch_name   TEXT,
    created_at   TEXT NOT NULL,
    total_files  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS departments (
    id          TEXT PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    description TEXT,
    color       TEXT DEFAULT '#17332a',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id         TEXT PRIMARY KEY,
    batch_id       TEXT,
    filename       TEXT NOT NULL,
    file_path      TEXT,
    status         TEXT NOT NULL,
    error          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT,
    pages_json     TEXT,
    extracted_json TEXT,
    edited_json    TEXT,
    summary_json   TEXT,
    progress_pct   INTEGER,
    progress_msg   TEXT,
    file_hash      TEXT,
    department     TEXT DEFAULT 'General'
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         SERIAL PRIMARY KEY,
    doc_id     TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);
CREATE INDEX IF NOT EXISTS idx_documents_batch_id ON documents(batch_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_doc_id ON chat_messages(doc_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at ON chat_sessions(updated_at);
"""

LIST_COLUMNS = ("doc_id, batch_id, filename, status, error, created_at, updated_at, summary_json, "
                "progress_pct, progress_msg, department, edited_json IS NOT NULL AS edited")


class PostgresCursorWrapper:
    """Wraps psycopg2 cursor to normalize SQL placeholders and lastrowid behavior."""
    def __init__(self, cur):
        self.cur = cur
        self.lastrowid = None
        self.rowcount = 0

    def execute(self, sql: str, params=None):
        pg_sql = sql.replace("?", "%s")
        if "INSERT OR IGNORE INTO batches" in pg_sql:
            pg_sql = pg_sql.replace("INSERT OR IGNORE INTO batches", "INSERT INTO batches") + " ON CONFLICT (batch_id) DO NOTHING"
        elif "INSERT OR IGNORE INTO departments" in pg_sql:
            pg_sql = pg_sql.replace("INSERT OR IGNORE INTO departments", "INSERT INTO departments") + " ON CONFLICT (name) DO NOTHING"
        elif "INSERT OR IGNORE INTO documents" in pg_sql:
            pg_sql = pg_sql.replace("INSERT OR IGNORE INTO documents", "INSERT INTO documents") + " ON CONFLICT (doc_id) DO NOTHING"
        elif "INSERT OR IGNORE INTO chat_messages" in pg_sql:
            pg_sql = pg_sql.replace("INSERT OR IGNORE INTO chat_messages", "INSERT INTO chat_messages") + " ON CONFLICT (id) DO NOTHING"
        elif "INSERT OR IGNORE INTO chat_sessions" in pg_sql:
            pg_sql = pg_sql.replace("INSERT OR IGNORE INTO chat_sessions", "INSERT INTO chat_sessions") + " ON CONFLICT (session_id) DO NOTHING"

        if pg_sql.strip().startswith("INSERT INTO chat_messages") and "RETURNING id" not in pg_sql:
            pg_sql = pg_sql.rstrip(";") + " RETURNING id;"
            if params:
                self.cur.execute(pg_sql, params)
            else:
                self.cur.execute(pg_sql)
            row = self.cur.fetchone()
            self.lastrowid = row["id"] if row else None
            self.rowcount = self.cur.rowcount
            return self

        if params:
            self.cur.execute(pg_sql, params)
        else:
            self.cur.execute(pg_sql)
        self.rowcount = self.cur.rowcount
        return self

    def executemany(self, sql: str, seq_of_params):
        pg_sql = sql.replace("?", "%s")
        self.cur.executemany(pg_sql, seq_of_params)
        self.rowcount = self.cur.rowcount
        return self

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()


class PostgresConnectionWrapper:
    """Wraps psycopg2 connection to provide a unified interface matching sqlite3."""
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor(cursor_factory=RealDictCursor))

    def execute(self, sql: str, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, sql_script: str):
        with self.conn.cursor() as cur:
            cur.execute(sql_script)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def _is_postgres(db_path: str = None) -> bool:
    if os.environ.get("SMARTEXTRACTOR_DB") or db_path is not None:
        return False
    return bool(DATABASE_URL) and PSYCOPG2_AVAILABLE


@contextmanager
def connect(db_path: str = None):
    if _is_postgres(db_path):
        conn = psycopg2.connect(DATABASE_URL)
        wrapper = PostgresConnectionWrapper(conn)
        try:
            yield wrapper
            wrapper.commit()
        finally:
            wrapper.close()
    else:
        conn = sqlite3.connect(db_path or DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


DEFAULT_DEPARTMENTS = [
    {
        "id": "dept_data_center",
        "name": "Data Center",
        "slug": "data-center",
        "description": "Colocation, physical rack space, power & cooling, cages, and facility infrastructure",
        "color": "#1d4ed8"
    },
    {
        "id": "dept_cloud_services",
        "name": "Cloud Services",
        "slug": "cloud-services",
        "description": "Virtual machines (VMs), IaaS, cloud compute, cloud storage, and managed cloud",
        "color": "#7c3aed"
    },
    {
        "id": "dept_general",
        "name": "General",
        "slug": "general",
        "description": "Contracts and agreements outside Data Center and Cloud Services",
        "color": "#4b5563"
    }
]


def _seed_default_departments(conn):
    for dept in DEFAULT_DEPARTMENTS:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO departments (id, name, slug, description, color, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (dept["id"], dept["name"], dept["slug"], dept["description"], dept["color"], _now())
            )
        except Exception as e:
            logger.debug(f"Department seed note: {e}")

    # Remove deprecated directories and move their documents to 'General'
    try:
        conn.execute("UPDATE documents SET department = 'General' WHERE department IN ('Network & Telecom', 'Software & SaaS')")
        conn.execute("DELETE FROM departments WHERE name IN ('Network & Telecom', 'Software & SaaS')")
    except Exception as e:
        logger.debug(f"Department cleanup note: {e}")


def init_db(db_path: str = None):
    if _is_postgres(db_path):
        with connect(db_path) as conn:
            conn.executescript(SCHEMA_POSTGRES)
            try:
                conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS department TEXT DEFAULT 'General';")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_department ON documents(department);")
            except Exception as e:
                logger.debug(f"Postgres column migration note: {e}")
            _seed_default_departments(conn)
        logger.info("Connected and initialized Supabase PostgreSQL database.")
    else:
        os.makedirs(os.path.dirname(db_path or DB_PATH), exist_ok=True)
        with connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA_SQLITE)
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(documents)")}
            if "batch_id" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN batch_id TEXT")
            if "summary_json" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN summary_json TEXT")
            if "progress_pct" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN progress_pct INTEGER")
                conn.execute("ALTER TABLE documents ADD COLUMN progress_msg TEXT")
            if "file_hash" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN file_hash TEXT")
            if "department" not in columns:
                conn.execute("ALTER TABLE documents ADD COLUMN department TEXT DEFAULT 'General'")
            _seed_default_departments(conn)


def _now():
    return datetime.now().isoformat()


def create_batch(batch_id: str, batch_name: str = None, total_files: int = 0, db_path: str = None):
    if not batch_name:
        batch_name = f"Batch {datetime.now().strftime('%b %d, %I:%M %p')}"
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO batches (batch_id, batch_name, created_at, total_files) VALUES (?, ?, ?, ?)",
            (batch_id, batch_name, _now(), total_files),
        )


def get_batch(batch_id: str, db_path: str = None):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if not row:
            return None
        batch = dict(row)
        docs = conn.execute(
            f"SELECT {LIST_COLUMNS} FROM documents WHERE batch_id = ? ORDER BY created_at ASC", (batch_id,)
        ).fetchall()
        parsed_docs = []
        for r in docs:
            d = dict(r)
            raw = d.pop("summary_json")
            d["summary"] = json.loads(raw) if raw else None
            d["edited"] = bool(d["edited"])
            parsed_docs.append(d)
        batch["documents"] = parsed_docs
        return batch


def list_batches(db_path: str = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM batches ORDER BY created_at DESC").fetchall()
        batches = []
        for r in rows:
            batch = dict(r)
            docs = conn.execute(
                f"SELECT {LIST_COLUMNS} FROM documents WHERE batch_id = ? ORDER BY created_at ASC",
                (batch["batch_id"],)
            ).fetchall()
            parsed_docs = []
            for dr in docs:
                d = dict(dr)
                raw = d.pop("summary_json")
                d["summary"] = json.loads(raw) if raw else None
                d["edited"] = bool(d["edited"])
                parsed_docs.append(d)
            batch["documents"] = parsed_docs
            batches.append(batch)
        return batches


def delete_batch(batch_id: str, db_path: str = None) -> list[str]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT doc_id FROM documents WHERE batch_id = ?", (batch_id,)).fetchall()
        doc_ids = [r["doc_id"] if isinstance(r, dict) else r[0] for r in rows]
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            conn.execute(f"DELETE FROM chat_messages WHERE doc_id IN ({placeholders})", doc_ids)
        conn.execute("DELETE FROM documents WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))
        return doc_ids


def create_document(doc_id: str, filename: str, file_path: str, file_hash: str = None, batch_id: str = None, department: str = "General", db_path: str = None):
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO documents (doc_id, batch_id, filename, file_path, status, created_at, updated_at, file_hash, department) "
            "VALUES (?, ?, ?, ?, 'processing', ?, ?, ?, ?)",
            (doc_id, batch_id, filename, file_path, _now(), _now(), file_hash, department or "General"),
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


def list_documents(department: str = None, db_path: str = None) -> list[dict]:
    with connect(db_path) as conn:
        if department and department.strip().lower() != "all":
            rows = conn.execute(
                f"SELECT {LIST_COLUMNS} FROM documents WHERE department = ? ORDER BY created_at DESC",
                (department.strip(),)
            ).fetchall()
        else:
            rows = conn.execute(f"SELECT {LIST_COLUMNS} FROM documents ORDER BY created_at DESC").fetchall()
    docs = []
    for r in rows:
        doc = dict(r)
        raw = doc.pop("summary_json")
        doc["summary"] = json.loads(raw) if raw else None
        doc["edited"] = bool(doc["edited"])
        if not doc.get("department"):
            doc["department"] = "General"
        docs.append(doc)
    return docs


def list_departments(include_counts: bool = True, db_path: str = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT id, name, slug, description, color, created_at FROM departments ORDER BY created_at ASC").fetchall()
        depts = [dict(r) for r in rows]
        if include_counts:
            count_rows = conn.execute(
                "SELECT department, count(*) as cnt FROM documents GROUP BY department"
            ).fetchall()
            counts = {r["department"]: r["cnt"] for r in count_rows if r["department"]}
            for d in depts:
                d["document_count"] = counts.get(d["name"], 0)
        return depts


def get_department(name_or_id: str, db_path: str = None) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, name, slug, description, color, created_at FROM departments WHERE id = ? OR name = ? OR slug = ?",
            (name_or_id, name_or_id, name_or_id)
        ).fetchone()
        return dict(row) if row else None


def create_department(name: str, description: str = "", color: str = "#17332a", db_path: str = None) -> dict:
    import re
    clean_name = name.strip()
    slug = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-")
    dept_id = f"dept_{slug.replace('-', '_')}"
    created_at = _now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO departments (id, name, slug, description, color, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (dept_id, clean_name, slug, description, color or "#17332a", created_at)
        )
    return {"id": dept_id, "name": clean_name, "slug": slug, "description": description, "color": color or "#17332a", "created_at": created_at}


def update_document_department(doc_id: str, department: str, db_path: str = None) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE documents SET department = ?, updated_at = ? WHERE doc_id = ?",
            (department, _now(), doc_id)
        )
        return cur.rowcount > 0


def bulk_update_document_department(doc_ids: list[str], department: str, db_path: str = None) -> int:
    if not doc_ids:
        return 0
    with connect(db_path) as conn:
        placeholders = ",".join("?" for _ in doc_ids)
        cur = conn.execute(
            f"UPDATE documents SET department = ?, updated_at = ? WHERE doc_id IN ({placeholders})",
            [department, _now(), *doc_ids]
        )
        return cur.rowcount


def get_queued_documents(db_path: str = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT doc_id, file_path FROM documents WHERE status = 'queued' ORDER BY created_at ASC").fetchall()
    return [dict(r) for r in rows]


def get_document_by_hash(file_hash: str, db_path: str = None):
    """Returns the ID of an existing document with the exact same hash."""
    if not file_hash:
        return None
    with connect(db_path) as conn:
        row = conn.execute("SELECT doc_id FROM documents WHERE file_hash = ?", (file_hash,)).fetchone()
    if not row:
        return None
    return row["doc_id"] if isinstance(row, dict) else row[0]


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
        conn.execute("DELETE FROM chat_messages WHERE doc_id = ?", (doc_id,))
        cur = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    return cur.rowcount > 0


def import_legacy_json(ocr_results_dir: str, uploads_dir: str, reparse, db_path: str = None) -> int:
    """One-time import of legacy JSON files."""
    imported = 0
    with connect(db_path) as conn:
        rows = conn.execute("SELECT doc_id FROM documents").fetchall()
        known = {r["doc_id"] if isinstance(r, dict) else r[0] for r in rows}

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
    return [r["doc_id"] if isinstance(r, dict) else r[0] for r in rows]


def mark_interrupted(db_path: str = None):
    """Documents left 'processing' by a previous server run can never finish."""
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE documents SET status = 'error', error = 'Processing was interrupted. Please upload again.' "
            "WHERE status = 'processing'"
        )


def get_chat_history(doc_id: str, limit: int = 50, db_path: str = None) -> list[dict]:
    """Returns the chat messages for a document in chronological order."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, doc_id, role, content, created_at FROM chat_messages "
            "WHERE doc_id = ? ORDER BY id ASC LIMIT ?",
            (doc_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def add_chat_message(doc_id: str, role: str, content: str, db_path: str = None) -> dict:
    """Inserts a chat message and returns it."""
    created_at = _now()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO chat_messages (doc_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (doc_id, role, content, created_at),
        )
        msg_id = cur.lastrowid
    return {"id": msg_id, "doc_id": doc_id, "role": role, "content": content, "created_at": created_at}


def clear_chat_history(doc_id: str, db_path: str = None):
    """Deletes all chat messages for a document."""
    with connect(db_path) as conn:
        conn.execute("DELETE FROM chat_messages WHERE doc_id = ?", (doc_id,))


PORTFOLIO_DOC_ID = "__portfolio__"

def _portfolio_doc_id(session_id: str = None) -> str:
    if not session_id or session_id == "default":
        return PORTFOLIO_DOC_ID
    return f"portfolio:{session_id}"


def list_chat_sessions(db_path: str = None) -> list[dict]:
    """Returns all chat sessions ordered by updated_at DESC, along with message counts."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM chat_sessions ORDER BY updated_at DESC"
        ).fetchall()
        sessions = [dict(r) for r in rows]

        # Check if legacy __portfolio__ messages exist and whether 'default' session is in sessions
        cur = conn.execute(
            "SELECT count(*) as cnt FROM chat_messages WHERE doc_id = ?",
            (PORTFOLIO_DOC_ID,)
        )
        legacy_row = cur.fetchone()
        legacy_cnt = legacy_row["cnt"] if legacy_row else 0

        has_default = any(s["session_id"] == "default" for s in sessions)
        if legacy_cnt > 0 and not has_default:
            sessions.insert(0, {
                "session_id": "default",
                "title": "Initial Portfolio Audit",
                "created_at": _now(),
                "updated_at": _now(),
                "message_count": legacy_cnt
            })

        for s in sessions:
            if "message_count" not in s:
                d_id = _portfolio_doc_id(s["session_id"])
                c = conn.execute(
                    "SELECT count(*) as cnt FROM chat_messages WHERE doc_id = ?",
                    (d_id,)
                ).fetchone()
                s["message_count"] = c["cnt"] if c else 0

        return sessions


def get_or_create_chat_session(session_id: str = None, title: str = None, db_path: str = None) -> dict:
    """Gets an existing session or creates a new one."""
    import uuid
    sid = session_id or f"s_{uuid.uuid4().hex[:10]}"
    t = title or "New Conversation"
    now_ts = _now()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM chat_sessions WHERE session_id = ?",
            (sid,)
        ).fetchone()
        if row:
            res = dict(row)
            d_id = _portfolio_doc_id(sid)
            c = conn.execute("SELECT count(*) as cnt FROM chat_messages WHERE doc_id = ?", (d_id,)).fetchone()
            res["message_count"] = c["cnt"] if c else 0
            return res
        conn.execute(
            "INSERT INTO chat_sessions (session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (sid, t, now_ts, now_ts)
        )
    return {"session_id": sid, "title": t, "created_at": now_ts, "updated_at": now_ts, "message_count": 0}


def update_chat_session_title(session_id: str, title: str, db_path: str = None):
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (title, _now(), session_id)
        )


def delete_chat_session(session_id: str, db_path: str = None):
    doc_target = _portfolio_doc_id(session_id)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_messages WHERE doc_id = ?", (doc_target,))
        if session_id == "default":
            conn.execute("DELETE FROM chat_messages WHERE doc_id = ?", (PORTFOLIO_DOC_ID,))


def get_portfolio_chat_history(session_id: str = None, limit: int = 50, db_path: str = None) -> list[dict]:
    target_id = _portfolio_doc_id(session_id)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, doc_id, role, content, created_at FROM chat_messages "
            "WHERE doc_id = ? "
            "ORDER BY id ASC LIMIT ?",
            (target_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def add_portfolio_chat_message(role: str, content: str, session_id: str = None, db_path: str = None) -> dict:
    target_id = _portfolio_doc_id(session_id)
    msg = add_chat_message(target_id, role=role, content=content, db_path=db_path)

    # If this is a named session, update updated_at and auto-generate title from first user query
    if session_id and session_id != "default":
        with connect(db_path) as conn:
            s_row = conn.execute(
                "SELECT title FROM chat_sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if s_row:
                if s_row["title"] == "New Conversation" and role == "user":
                    clean_title = content.strip().replace("\n", " ")[:38]
                    if len(content.strip()) > 38:
                        clean_title += "..."
                    conn.execute(
                        "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                        (clean_title, _now(), session_id)
                    )
                else:
                    conn.execute(
                        "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                        (_now(), session_id)
                    )

    return msg


def clear_portfolio_chat_history(session_id: str = None, db_path: str = None):
    target_id = _portfolio_doc_id(session_id)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM chat_messages WHERE doc_id = ?", (target_id,))
        if target_id == PORTFOLIO_DOC_ID:
            conn.execute("DELETE FROM chat_messages WHERE doc_id = 'portfolio:default'")

