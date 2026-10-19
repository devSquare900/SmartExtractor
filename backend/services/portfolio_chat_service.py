import json
import logging
import os
import re
from datetime import datetime, date
from typing import AsyncGenerator, Dict, Any, List

from dateutil.relativedelta import relativedelta
from groq import RateLimitError, APIError

from services import db
from services.llm_parser import _get_clients, _next_client, MODEL
from services.chat_service import _format_extracted_fields
from services.retrieval import retrieve_relevant_pages, tokenize, BM25Okapi

logger = logging.getLogger("smartextractor.portfolio_chat")

CHAT_MODEL = os.environ.get("CHAT_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODEL = os.environ.get("CHAT_FALLBACK_MODEL", MODEL)
ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "openai/gpt-oss-20b")

PORTFOLIO_MAX_CHARS = int(os.environ.get("PORTFOLIO_MAX_CHARS", "16000"))

PORTFOLIO_SYSTEM_PROMPT = """You are PortfolioAssistant, the enterprise corporate legal counsel and portfolio auditor for SmartExtractor.
You have direct visibility and auditing intelligence across the entire repository of contracts and agreements stored in the database.

Core Directives:
1. Precision & Natural Conversational Flow:
   - Answer the user's query directly, naturally, and factually based strictly on the provided portfolio documents, verified attributes, and catalog.
   - Do not use conversational filler, pleasantries, or self-introductions (avoid "Certainly!", "Sure!", "As an AI..."). Start immediately with the answer.
   - Speak like a seasoned corporate counsel: fluent narrative, clear context, and structured bullet points.

2. Formatting & Strict Table Protocol:
   - DEFAULT FORMAT: Always use natural conversational prose and clean bullet points with bold subheadings (e.g. `• **Service Scope:** ...`, `• **Termination for Convenience:** ...`).
   - If the user asks for a comparison, a portfolio audit, or a list of expired/active contracts, format with clean structured bullet points or a concise comparison table.
   - STRICT TABLE FORBIDDEN RULE: NEVER generate a Markdown table for single-document queries, clause explanations (e.g. termination, liabilities, services, payment terms), or routine status/date queries. Use clean bulleted lists instead.
   - ONLY generate a Markdown table if:
     a) The user explicitly asks for a table (e.g. "show in a table", "table format", "make a table"), OR
     b) Performing a comparative multi-contract matrix across 3 or more distinct contracts.

3. Interactive Document Canvas & Report Generation Protocol:
   - When the user explicitly requests to generate, draft, compile, or prepare a report, memo, summary document, audit brief, or exportable document (e.g., "generate a report", "make an audit report", "compile a memo", "prepare report on expired contracts", "mujhe report generate kar ke do"):
     1. In the chat message, write a crisp 1-2 sentence conversational introduction explaining that the requested document has been compiled and is open in the side canvas.
     2. Enclose the ENTIRE formatted document inside an `<artifact>` block:
        <artifact id="unique-kebab-case-id" title="Descriptive Document Title" type="report" theme="navy">
        # Document Title
        
        ## Executive Summary
        ...
        
        ## Comprehensive Findings & Audit Matrix
        ... (structured tables, bullet points, callouts) ...
        
        ## Risk Analysis & Strategic Recommendations
        ...
        </artifact>
     3. Available theme values: "navy" (Executive Navy - default), "emerald" (Corporate Emerald), "blue" (Royal Blue), "burgundy" (Classic Crimson). If the user asks for a specific color/theme (e.g., "make it emerald", "change color to blue", "burgundy theme"), set theme="..." accordingly.
     4. Iterative Canvas Editing: If the user provides instructions to change headings, adjust themes, add columns, or rewrite sections (e.g., "change the heading to X", "change color to emerald", "add a column for notice period"), acknowledge the change politely in chat and output the FULL updated document inside `<artifact id="..." title="..." type="report" theme="...">...</artifact>` with their requested changes.
   - For regular chat questions, clause searches, date lookups, and routine conversation, DO NOT use <artifact> tags. Answer directly in conversational prose.

4. Citation & Sources Protocol (Enterprise Integrity):
   - For queries listing, comparing, or referencing specific contracts:
     Format the answer clearly with the contract name/filename, key dates, and findings.
   - At the bottom of your response, provide clean clickable source pills ONLY for the contracts directly mentioned in the answer:
     ---
     **Sources:**
     • [<Contract Title or Filename>](doc:<doc_id>)
   - STRICT INTEGRITY: ONLY cite contracts that actually exist in the provided audit/catalog and are directly relevant to the user's query.
   - NEVER invent, copy, or hallucinate placeholder names, page numbers, or sources.
   - If no contracts match the user's query or no specific document applies, DO NOT include a "Sources:" footnote at all.

5. Date & Temporal Calculations:
   - Use the provided Today's Real-Time Date and the verified expiry status in the audit.
   - If a contract is marked EXPIRED, clearly report it as EXPIRED with its exact expiry date and days elapsed.
   - If a contract has an active future expiry date, clearly state the remaining time.

6. Strict Honesty:
   - If a requested detail or contract is not found in the portfolio, clearly state that it is not in the database. Do not speculate or invent contracts.

7. Language:
   - If the user asks in English, reply in crisp English.
   - If the user asks in Roman Urdu, reply naturally in Roman Urdu / English using the standard Latin alphabet.
"""


def _parse_contract_date(d_str: str) -> date | None:
    if not d_str or not isinstance(d_str, str):
        return None
    d_str = d_str.strip()
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', d_str)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except Exception:
            pass
    m = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', d_str)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()
        except Exception:
            pass
    return None


def _parse_contract_tenure(tenure_str: str):
    if not tenure_str or not isinstance(tenure_str, str):
        return None
    s = tenure_str.lower()
    m_yr = re.search(r'(\d+)\s*year', s)
    if m_yr:
        return relativedelta(years=int(m_yr.group(1)))
    if 'one' in s and 'year' in s:
        return relativedelta(years=1)
    if 'two' in s and 'year' in s:
        return relativedelta(years=2)
    if 'three' in s and 'year' in s:
        return relativedelta(years=3)
    if 'four' in s and 'year' in s:
        return relativedelta(years=4)
    if 'five' in s and 'year' in s:
        return relativedelta(years=5)
    m_mo = re.search(r'(\d+)\s*month', s)
    if m_mo:
        return relativedelta(months=int(m_mo.group(1)))
    return None


def _safe_get_extracted(d: Dict[str, Any]) -> Dict[str, Any]:
    """Safely extracts dictionary fields, guarding against booleans, strings, or None."""
    data = d.get("edited")
    if not isinstance(data, dict):
        data = d.get("extracted")
    if not isinstance(data, dict):
        doc_id = d.get("doc_id")
        if doc_id:
            try:
                doc = db.get_document(doc_id)
                if doc:
                    data = doc.get("edited") if isinstance(doc.get("edited"), dict) else doc.get("extracted")
            except Exception:
                pass
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = {}
    return data if isinstance(data, dict) else {}


def _load_portfolio_records(db_path: str = None) -> List[Dict[str, Any]]:
    today = datetime.now().date()
    with db.connect(db_path) as conn:
        rows = conn.execute("""
            SELECT doc_id, filename, department, summary_json,
                   COALESCE(edited_json, extracted_json) AS data_json
            FROM documents
            ORDER BY created_at DESC
        """).fetchall()

    records = []
    for r in rows:
        raw = r["data_json"]
        data = json.loads(raw) if raw else {}
        doc_info = data.get("document_info") or {}
        summ = json.loads(r["summary_json"]) if r["summary_json"] else {}

        title = (data.get("contract_name") or {}).get("value") or summ.get("title") or r["filename"]
        customer = ((data.get("customer_info") or {}).get("name") or {}).get("value") or summ.get("customer") or "Unspecified"
        amount = summ.get("amount_raw") or "N/A"

        raw_exec = (doc_info.get("execution_date") or {}).get("normalized") or (doc_info.get("execution_date") or {}).get("value") or summ.get("date") or ""
        raw_exp = (doc_info.get("expiry_date") or {}).get("normalized") or (doc_info.get("expiry_date") or {}).get("value") or ""
        raw_tenure = (doc_info.get("validity_tenure") or {}).get("value") or ""

        exec_dt = _parse_contract_date(raw_exec)
        exp_dt = _parse_contract_date(raw_exp)

        # If no explicit expiry, derive from exec_date + tenure
        derived = False
        if not exp_dt and exec_dt and raw_tenure:
            delta = _parse_contract_tenure(raw_tenure)
            if delta:
                exp_dt = exec_dt + delta
                derived = True

        status_str = "NO_EXPIRY_RECORDED"
        days_diff = None
        is_expired = False
        is_active = False

        if exp_dt:
            if exp_dt < today:
                days_diff = (today - exp_dt).days
                is_expired = True
                status_str = f"EXPIRED ({days_diff} days ago on {exp_dt.strftime('%Y-%m-%d')})"
            else:
                days_diff = (exp_dt - today).days
                is_active = True
                status_str = f"ACTIVE ({days_diff} days remaining until {exp_dt.strftime('%Y-%m-%d')})"

        records.append({
            "doc_id": r["doc_id"],
            "filename": r["filename"],
            "department": r["department"] or "General",
            "title": title,
            "customer": customer,
            "amount": amount,
            "start": raw_exec or "N/A",
            "expiry": exp_dt.strftime("%Y-%m-%d") if exp_dt else (raw_exp or "N/A"),
            "tenure": raw_tenure or "N/A",
            "status": status_str,
            "is_expired": is_expired,
            "is_active": is_active,
            "days_diff": days_diff,
            "derived_expiry": derived
        })
    return records


def _build_portfolio_catalog(docs: List[Dict[str, Any]] = None, records: List[Dict[str, Any]] = None) -> str:
    """Builds a token-efficient structured catalog of all unique agreements in the repository."""
    if records is None:
        if docs is not None and len(docs) > 0 and "is_expired" in docs[0]:
            records = docs
        elif docs is not None:
            today = datetime.now().date()
            records = []
            for d in docs:
                summary = d.get("summary") or {}
                extracted = _safe_get_extracted(d)
                doc_info = extracted.get("document_info") or {}
                raw_exp = (doc_info.get("expiry_date") or {}).get("value") or (doc_info.get("expiry_date") or {}).get("normalized") or ""
                raw_exec = (doc_info.get("execution_date") or {}).get("value") or summary.get("date") or ""
                raw_tenure = (doc_info.get("validity_tenure") or {}).get("value") or ""
                exec_dt = _parse_contract_date(raw_exec)
                exp_dt = _parse_contract_date(raw_exp)
                if not exp_dt and exec_dt and raw_tenure:
                    delta = _parse_contract_tenure(raw_tenure)
                    if delta:
                        exp_dt = exec_dt + delta
                status = "NO_EXPIRY_RECORDED"
                if exp_dt:
                    status = f"EXPIRED (on {exp_dt})" if exp_dt < today else f"ACTIVE (until {exp_dt})"
                records.append({
                    "doc_id": d.get("doc_id", ""),
                    "filename": d.get("filename", ""),
                    "department": d.get("department", "General"),
                    "title": summary.get("title") or "Untitled Document",
                    "customer": summary.get("customer") or "Unspecified",
                    "amount": summary.get("amount_raw") or "N/A",
                    "start": raw_exec or "N/A",
                    "expiry": exp_dt.strftime("%Y-%m-%d") if exp_dt else (raw_exp or "N/A"),
                    "tenure": raw_tenure or "N/A",
                    "status": status,
                    "is_expired": bool(exp_dt and exp_dt < today),
                    "is_active": bool(exp_dt and exp_dt >= today),
                })
        else:
            records = _load_portfolio_records()

    # Group identical duplicate files by (filename, expiry, status) to preserve token budget
    groups = {}
    for r in records:
        key = (r["filename"], r["expiry"], r["status"])
        if key not in groups:
            groups[key] = {
                "doc_id": r["doc_id"],
                "filename": r["filename"],
                "department": r["department"],
                "title": r["title"],
                "customer": r["customer"],
                "amount": r["amount"],
                "start": r["start"],
                "expiry": r["expiry"],
                "tenure": r["tenure"],
                "status": r["status"],
                "count": 1
            }
        else:
            groups[key]["count"] += 1

    lines = []
    for g in groups.values():
        dup_str = f" ({g['count']} copies in DB)" if g["count"] > 1 else ""
        lines.append(
            f"- [{g['doc_id']}] {g['filename']}{dup_str} | Title: {g['title']} | Cust: {g['customer']} | Amount: {g['amount']} | Start: {g['start']} | Expiry: {g['expiry']} | Status: {g['status']}"
        )
    return "\n".join(lines)


def _resolve_portfolio_intent(
    user_message: str,
    docs: List[Dict[str, Any]],
    client,
    recent_history: List[Dict[str, str]] = None,
    catalog: str = None
) -> Dict[str, Any]:
    """
    Uses fast structured intelligence to determine:
    1. Query type: PORTFOLIO_AGGREGATE, TARGETED_DOCUMENTS, or CLAUSE_DISCOVERY.
    2. Target document IDs (matching by customer, filename, title, or conversational context).
    3. Specific clause search terms.
    """
    if catalog is None:
        catalog = _build_portfolio_catalog(docs)

    history_context = ""
    if recent_history:
        recent_turns = [
            f"{m.get('role', 'user')}: {str(m.get('content', ''))[:160]}"
            for m in recent_history[-2:]
            if m.get("content")
        ]
        if recent_turns:
            history_context = "Recent Conversation Context:\n" + "\n".join(recent_turns) + "\n\n"

    # Limit router catalog slice to prevent exceeding 8000 token limit
    router_catalog = catalog if len(catalog) <= 6500 else catalog[:6500] + "\n... [catalog summary truncated for router]"

    prompt = f"""You are an enterprise legal document router.
Below is the catalog of contracts in the repository.

{history_context}Analyze the user's current query:
"{user_message}"

Determine:
1. "query_type":
   - "PORTFOLIO_AGGREGATE": If user asks for an overview, count, list, comparison across all contracts, or overall metrics (e.g. "list all contracts", "which contracts are expired?", "highest MRC", "what vendors exist?", "contracts expiring in 2026").
   - "TARGETED_DOCUMENTS": If the user refers to one or more specific contracts by vendor name, document title, concept, or pronoun/continuation from the Recent Conversation Context (e.g. "Vendor X agreement", "this contract", "cloud SLA").
   - "CLAUSE_DISCOVERY": If user asks for a specific legal clause, term, or rate without specifying which contract has it (e.g. "which contract requires 90 days notice?", "find 5% late interest").
2. "target_doc_ids": Array of matching doc_id(s) from the catalog (up to 3 most relevant). Empty if PORTFOLIO_AGGREGATE.
3. "clause_keywords": Array of specific legal clause keywords (e.g. ["termination", "notice period", "expiry", "90 days"]).

Return JSON only:
{{
  "query_type": "PORTFOLIO_AGGREGATE" | "TARGETED_DOCUMENTS" | "CLAUSE_DISCOVERY",
  "target_doc_ids": ["doc_id"],
  "clause_keywords": ["keyword"]
}}

Repository Catalog:
{router_catalog}
"""
    if client is not None:
        for model_name in (ROUTER_MODEL, MODEL, CHAT_MODEL):
            try:
                resp = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are a legal intent routing engine. Output valid JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_tokens=1024
                )
                content = resp.choices[0].message.content or "{}"
                data = json.loads(content)
                q_type = data.get("query_type") or "PORTFOLIO_AGGREGATE"
                doc_ids = data.get("target_doc_ids") or []
                valid_ids = [did for did in doc_ids if any(d.get("doc_id") == did for d in docs)] if docs else doc_ids
                return {
                    "query_type": q_type if valid_ids or q_type == "PORTFOLIO_AGGREGATE" else "CLAUSE_DISCOVERY",
                    "target_doc_ids": valid_ids,
                    "clause_keywords": data.get("clause_keywords") or []
                }
            except Exception as e:
                logger.warning(f"Router attempt failed with {model_name}: {e}")
                continue

    # Fallback: token matching against catalog + history
    combined_query = user_message
    if recent_history:
        for m in reversed(recent_history):
            if m.get("content"):
                combined_query += " " + m["content"]
                break

    q_lower = combined_query.lower()
    matched = []
    if docs:
        for d in docs:
            fn = str(d.get("filename") or "").lower()
            title = str((d.get("summary") or {}).get("title") or "").lower()
            cust = str((d.get("summary") or {}).get("customer") or "").lower()
            if any(w in fn or w in title or w in cust for w in q_lower.split() if len(w) > 3):
                matched.append(d.get("doc_id"))

    # If asking for expired or portfolio aggregate, do not misclassify as targeted
    is_aggregate_word = any(w in q_lower for w in ["expired", "expir", "all", "list", "total", "summary", "every", "compare", "active"])
    query_type = "PORTFOLIO_AGGREGATE" if is_aggregate_word or not matched else "TARGETED_DOCUMENTS"

    return {
        "query_type": query_type,
        "target_doc_ids": [] if query_type == "PORTFOLIO_AGGREGATE" else matched[:2],
        "clause_keywords": [w for w in user_message.lower().split() if len(w) > 3]
    }


def _build_portfolio_context(
    user_message: str,
    docs: List[Dict[str, Any]],
    client,
    recent_history: List[Dict[str, str]] = None
) -> str:
    """Builds grounded context combining verified database attributes, audit insights, and BM25 clause pages."""
    today_dt = datetime.now().date()
    today_str = today_dt.strftime("%Y-%m-%d")
    today_header = (
        f"Today's Real-Time Date: {today_str}\n"
        f"(Use this date to determine whether contracts are active or expired, and to calculate exact remaining/elapsed time.)\n\n"
    )

    records = _load_portfolio_records()
    catalog = _build_portfolio_catalog(records=records)
    intent = _resolve_portfolio_intent(user_message, docs, client, recent_history=recent_history, catalog=catalog)
    q_type = intent["query_type"]
    target_ids = intent["target_doc_ids"]
    clause_kws = " ".join(intent["clause_keywords"]) or user_message

    # Check if query is asking about contract expiry, dates, or renewals
    q_lower = user_message.lower()
    is_expiry_query = any(w in q_lower for w in ["expir", "ended", "khatam", "remain", "active", "validity", "tenure", "renewal"])

    expiry_audit_block = ""
    if is_expiry_query:
        expired_records = [r for r in records if r.get("is_expired")]
        active_records = [r for r in records if r.get("is_active")]

        # Deduplicate by filename + expiry date for crystal-clear presentation
        unique_expired = {}
        for r in expired_records:
            k = (r["filename"], r["expiry"])
            if k not in unique_expired:
                unique_expired[k] = r

        unique_active = {}
        for r in active_records:
            k = (r["filename"], r["expiry"])
            if k not in unique_active:
                unique_active[k] = r

        audit_lines = [
            f"================ PORTFOLIO EXPIRY AUDIT (Today: {today_str}) ================",
            f"Total Contracts in System: {len(records)}",
            f"Total Expired Contract Records: {len(expired_records)} ({len(unique_expired)} unique agreements)",
            f"Total Active Contract Records: {len(active_records)} ({len(unique_active)} unique agreements)",
            "\n--- VERIFIED EXPIRED CONTRACTS IN SYSTEM ---"
        ]
        if unique_expired:
            for r in unique_expired.values():
                audit_lines.append(
                    f"• [{r['doc_id']}] **{r['title']}** (File: `{r['filename']}`) | Expiry: {r['expiry']} | Status: {r['status']} | Cust: {r['customer']} | Amount: {r['amount']}"
                )
        else:
            audit_lines.append("No expired contracts found.")

        if unique_active:
            audit_lines.append("\n--- VERIFIED ACTIVE CONTRACTS WITH FUTURE EXPIRY ---")
            for r in unique_active.values():
                audit_lines.append(
                    f"• [{r['doc_id']}] **{r['title']}** (File: `{r['filename']}`) | Expiry: {r['expiry']} | Status: {r['status']} | Cust: {r['customer']} | Amount: {r['amount']}"
                )

        audit_lines.append("=========================================================================\n")
        expiry_audit_block = "\n".join(audit_lines) + "\n\n"

    # Case 1: Broad Portfolio / Aggregate Query
    if q_type == "PORTFOLIO_AGGREGATE" or not target_ids:
        return (
            f"{PORTFOLIO_SYSTEM_PROMPT}\n\n"
            f"{today_header}"
            f"{expiry_audit_block}"
            f"================ REPOSITORY PORTFOLIO OVERVIEW ================\n"
            f"Total Contracts: {len(records)}\n\n"
            f"--- STRUCTURED CONTRACT CATALOG ---\n"
            f"{catalog}\n"
            f"===============================================================\n"
        )

    # Case 2: Targeted Document(s) or Clause Discovery
    sections = [
        f"{PORTFOLIO_SYSTEM_PROMPT}\n\n",
        f"{today_header}",
        f"================ REPOSITORY CONTEXT ================\n",
        f"Total Contracts in System: {len(records)}\n",
        f"Targeted Contract(s) Identified: {len(target_ids)}\n"
    ]

    per_doc_budget = PORTFOLIO_MAX_CHARS // max(1, len(target_ids))

    for did in target_ids:
        doc = db.get_document(did)
        if not doc:
            continue
        summary = doc.get("summary") or {}
        title = summary.get("title") or doc.get("filename", "Contract")
        pages = doc.get("pages") or []

        # Ground-truth verified attributes from DB
        current_data = _safe_get_extracted(doc)
        fields_text = _format_extracted_fields(current_data)

        # Mathematical BM25 retrieval for source evidence pages
        relevant = retrieve_relevant_pages(pages, query=clause_kws, char_budget=per_doc_budget, include_preamble=True)
        page_text = "\n\n".join(f"=== PAGE {pnum} ===\n{text}" for pnum, text in relevant if text.strip())

        sections.append(
            f"\n--- TARGET CONTRACT: {title} (ID: {did}, File: {doc.get('filename')}) ---\n"
            f"[VERIFIED CONTRACT ATTRIBUTES]\n"
            f"{fields_text}\n\n"
            f"[SOURCE CONTRACT CLAUSES & PAGES]\n"
            f"{page_text}\n"
        )

    sections.append("====================================================\n")
    return "\n".join(sections)


async def stream_portfolio_chat(user_message: str, session_id: str = None) -> AsyncGenerator[str, None]:
    """Streams responses for global queries across the entire repository for a specific session."""
    # 1. Save user prompt to portfolio chat history for this session
    db.add_portfolio_chat_message("user", user_message, session_id=session_id)

    # 2. Retrieve recent portfolio chat turns for this session
    raw_history = db.get_portfolio_chat_history(session_id=session_id, limit=8)

    # 3. Load all completed/available documents
    docs = db.list_documents()

    # 4. Initialize client
    try:
        clients = _get_clients()
    except Exception as e:
        logger.error(f"Failed to initialize Groq clients: {e}")
        yield f"data: {json.dumps({'error': f'AI Service configuration error: {str(e)}'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    router_client = _next_client()
    system_content = _build_portfolio_context(user_message, docs, router_client, recent_history=raw_history[:-1])

    messages = [{"role": "system", "content": system_content}]

    # Include recent dialogue turns
    for msg in raw_history[:-1]:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"].strip()})

    messages.append({"role": "user", "content": user_message})

    full_response = []
    success = False
    last_error = None

    for attempt in range(len(clients)):
        client = _next_client()
        for active_model in (CHAT_MODEL, FALLBACK_MODEL):
            try:
                stream = client.chat.completions.create(
                    model=active_model,
                    messages=messages,
                    stream=True,
                    temperature=0.1,
                    max_tokens=3500,
                )

                for chunk in stream:
                    content = chunk.choices[0].delta.content if chunk.choices else None
                    if content:
                        full_response.append(content)
                        yield f"data: {json.dumps({'delta': content})}\n\n"

                success = True
                break

            except RateLimitError as e:
                logger.warning(f"Rate limited on {active_model} (key attempt {attempt}): {e}")
                last_error = e
                break
            except Exception as e:
                logger.warning(f"Error on {active_model} (key attempt {attempt}): {e}")
                last_error = e
                continue

        if success:
            break

    if not success:
        error_msg = f"Portfolio AI temporarily unavailable: {last_error or 'all attempts failed'}"
        yield f"data: {json.dumps({'error': error_msg})}\n\n"
        db.add_portfolio_chat_message("assistant", f"Error: {error_msg}", session_id=session_id)
    else:
        assistant_reply = "".join(full_response).strip()
        db.add_portfolio_chat_message("assistant", assistant_reply, session_id=session_id)

    yield "data: [DONE]\n\n"
