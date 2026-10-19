import json
import logging
import os
from typing import AsyncGenerator

from groq import RateLimitError, APIError

from services import db
from services.llm_parser import _get_clients, _next_client, MODEL
from services.retrieval import retrieve_relevant_pages

logger = logging.getLogger("smartextractor.chat")

# Primary model: 120B parameter model for deep contract intelligence
# Fallback model: 20B model if 120B hits quota limits
CHAT_MODEL = os.environ.get("CHAT_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODEL = os.environ.get("CHAT_FALLBACK_MODEL", MODEL)

# Character budget for document context (strictly calibrated under Groq 8,000 TPM limit)
# 20,000 characters is approximately 4,500 - 4,800 tokens.
# Combined with max_tokens=2200, total token budget stays strictly under the 8,000 TPM ceiling.
CHAT_MAX_DOC_CHARS = int(os.environ.get("CHAT_MAX_DOC_CHARS", "20000"))

SYSTEM_PROMPT = """You are SmartAssistant, a senior Corporate Legal Counsel and enterprise document review intelligence system (Harvey AI caliber).

Operational & Ethical Directives:
1. Strict Single-Document Isolation (Zero Cross-Contamination):
   - You are reviewing ONLY AND EXCLUSIVELY the single contract provided in the CURRENT DOCUMENT CONTEXT below.
   - Your legal analysis is strictly bounded by the text of this specific agreement.
   - ABSOLUTE PROHIBITION: NEVER cite, mention, import, or assume external entities, vendor names, or contracts (such as BIPL-AIK, PTCL, Bank Islami, or others) UNLESS that exact entity appears verbatim in this document's text.
   - Never confuse or bleed information from any other contract or external context into this review.

2. Forensic Evidence & Verbatim Quoting (High-Trust Provenance):
   - Always anchor your findings to specific contract sections and page numbers (e.g., "Section 14.2 (Page 6)").
   - Whenever discussing key obligations, remedies, liabilities, fees, or rights, quote the operative sentence or phrase verbatim inside quotation marks "..." directly from the text so the user has immediate factual verification.
   - For dates: Clearly distinguish between the Execution Date (signing date) and the Effective Date (commencement of term/obligations) if both exist.
   - For monetary terms: State exact figures, currency, and payment schedule/frequency (e.g., monthly recurring, one-time setup, milestone).

3. Professional Handling of Silence & Omissions (Enterprise Legal Advisory):
   - Commercial users and business stakeholders frequently ask about terms that may not be explicitly included in a given agreement (e.g., penalty clauses, termination for convenience, warranty exclusions, auto-renewal).
   - DO NOT give blunt, robotic, or dismissive responses such as "Not mentioned in document" or "This information is not specified in the document."
   - DO NOT expect or require the user to formulate special legal prompts.
   - INSTEAD, deliver a professional, contextual legal explanation:
     a) State clearly that the agreement contains no express clause or provision on that specific matter.
     b) Identify and cite the nearest governing or related clause in the contract (e.g., if asked about early termination without cause, explain what Section X states regarding termination for breach or cause upon 30 days' notice).
     c) Explain the practical legal implication of that silence in standard commercial contracting (e.g., silence on unilateral early termination means neither party has the contractual right to terminate early without cause, requiring mutual written amendment).

4. Directness, Tone & Style:
   - Provide direct, authoritative, and high-signal legal analysis.
   - Avoid conversational filler, pleasantries, or apologetic AI throat-clearing (never begin with "Certainly!", "Sure!", "As an AI legal assistant...", or "I'd be happy to help"). Begin immediately with the substantive legal analysis.
   - DEFAULT FORMAT: Always use conversational legal prose, structured bullet points, and bold highlights.
   - NEVER output a Markdown table unless the user explicitly requests one (e.g. "show in a table", "table format").

5. Interactive Document Canvas & Report Generation Protocol:
   - When the user explicitly requests to generate, draft, compile, or prepare a report, memo, summary document, audit brief, or exportable document for this contract (e.g., "generate a report", "make an audit memo", "create executive summary report", "mujhe report generate kar ke do"):
     1. In the chat message, write a crisp 1-2 sentence conversational introduction explaining that the requested document has been compiled and is open in the side canvas.
     2. Enclose the ENTIRE formatted document inside an `<artifact>` block:
        <artifact id="unique-kebab-case-id" title="Descriptive Document Title" type="report" theme="navy">
        # Document Title
        
        ## Executive Summary
        ...
        
        ## Key Legal & Financial Terms Matrix
        ... (structured tables, bullet points, callouts) ...
        
        ## Compliance, Obligations & Risk Advisory
        ...
        </artifact>
     3. Available theme values: "navy" (Executive Navy - default), "emerald" (Corporate Emerald), "blue" (Royal Blue), "burgundy" (Classic Crimson). If the user asks for a specific color/theme (e.g., "make it emerald", "change color to blue", "burgundy theme"), set theme="..." accordingly.
     4. Iterative Canvas Editing: If the user provides instructions to change headings, adjust themes, add sections, or modify terms (e.g., "change the heading to X", "change color to emerald", "add liability cap details"), acknowledge the change politely in chat and output the FULL updated document inside `<artifact id="..." title="..." type="report" theme="...">...</artifact>` with their requested changes.
   - For regular chat questions, clause searches, date lookups, and routine conversation, DO NOT use <artifact> tags. Answer directly in conversational prose.

6. Bilingual Fluency:
   - If the user asks in English, reply in crisp, professional English.
   - If the user asks in Roman Urdu (e.g., "is contract ka notice period kia hai?", "ye kab expire hoga?"), reply naturally in Roman Urdu / English using the standard Latin alphabet.
"""


def _format_extracted_fields(data: dict) -> str:
    """Formats verified extracted fields dynamically into clean structured text."""
    if not data:
        return "No extracted fields available."

    lines = []
    contract_name = data.get("contract_name")
    if isinstance(contract_name, dict) and contract_name.get("value"):
        lines.append(f"Contract / Document Title: {contract_name['value']}\n")

    for section_key, section_val in data.items():
        if section_key == "contract_name":
            continue

        if isinstance(section_val, dict):
            has_subfields = any(isinstance(v, dict) for v in section_val.values())
            if has_subfields:
                section_title = section_key.replace("_", " ").title()
                lines.append(f"[{section_title}]")
                for k, v in section_val.items():
                    if isinstance(v, dict):
                        val = v.get("value") or v.get("normalized") or ""
                        conf = v.get("confidence")
                        edited = " (Manually Edited)" if v.get("manual") else ""
                        conf_str = f" [Confidence: {int(conf * 100)}%]" if conf is not None else ""
                        field_name = k.replace("_", " ").title()
                        if val:
                            lines.append(f"- {field_name}: {val}{conf_str}{edited}")
                    elif v is not None:
                        lines.append(f"- {k.replace('_', ' ').title()}: {v}")
                lines.append("")
            else:
                val = section_val.get("value") or section_val.get("normalized") or ""
                if val:
                    lines.append(f"- {section_key.replace('_', ' ').title()}: {val}")

        elif isinstance(section_val, list):
            lines.append(f"[{section_key.replace('_', ' ').title()}]")
            for item in section_val:
                lines.append(f"- {item}")
            lines.append("")

    return "\n".join(lines).strip()


def _format_ocr_pages(pages: list, char_budget: int = CHAT_MAX_DOC_CHARS, query: str = "", client=None) -> str:
    """
    Retrieves the most relevant pages using BM25 information retrieval
    and formats them with clear page markers.
    """
    if not pages:
        return "No OCR text available."

    relevant_pages = retrieve_relevant_pages(pages, query=query, char_budget=char_budget)
    if not relevant_pages:
        return "No relevant pages found."

    blocks = []
    for page_num, text in relevant_pages:
        if text.strip():
            blocks.append(f"=== PAGE {page_num} ===\n{text}")

    return "\n\n".join(blocks).strip()


def build_system_context(doc: dict, user_message: str = "", client=None) -> str:
    """Builds the complete grounded document context passed to the LLM."""
    filename = doc.get("filename", "Document")
    current_data = doc.get("edited") if doc.get("edited") is not None else (doc.get("extracted") or {})
    ocr_pages = doc.get("pages") or []

    fields_text = _format_extracted_fields(current_data)
    ocr_context = _format_ocr_pages(ocr_pages, char_budget=CHAT_MAX_DOC_CHARS, query=user_message)

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"================ CURRENT DOCUMENT CONTEXT ================\n"
        f"File Name: {filename}\n"
        f"Document ID: {doc.get('doc_id')}\n"
        f"Total Pages: {len(ocr_pages)}\n\n"
        f"--- CURRENT EXTRACTED & VERIFIED FIELDS ---\n"
        f"{fields_text}\n\n"
        f"--- RELEVANT DOCUMENT PAGES ---\n"
        f"{ocr_context}\n"
        f"==========================================================\n"
    )


def _build_dialogue_history(raw_history: list, max_turns: int = 6) -> list:
    """
    Maintains clean conversation turns without arbitrary character clipping.
    Keeps the most recent turns up to max_turns in a FIFO window.
    """
    clean_history = []
    valid_msgs = [m for m in raw_history if m.get("role") in ("user", "assistant") and m.get("content")]

    # Take the most recent turns
    recent_msgs = valid_msgs[-max_turns:] if len(valid_msgs) > max_turns else valid_msgs

    for msg in recent_msgs:
        clean_history.append({
            "role": msg["role"],
            "content": msg["content"].strip()
        })
    return clean_history


async def stream_chat(doc_id: str, user_message: str) -> AsyncGenerator[str, None]:
    """
    Streams the assistant's answer for doc_id using Groq with multi-key failover,
    saving both user and assistant messages in the database.
    """
    doc = db.get_document(doc_id)
    if not doc:
        yield f"data: {json.dumps({'error': 'Document not found'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # 1. Save user message in DB
    db.add_chat_message(doc_id, "user", user_message)

    # 2. Retrieve recent chat history (FIFO window)
    raw_history = db.get_chat_history(doc_id, limit=8)

    # 3. Initialize client pool with failover
    try:
        clients = _get_clients()
    except Exception as e:
        logger.error(f"Failed to initialize Groq clients: {e}")
        yield f"data: {json.dumps({'error': f'AI Service configuration error: {str(e)}'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # 4. Build context and messages payload
    system_content = build_system_context(doc, user_message=user_message)
    messages = [{"role": "system", "content": system_content}]

    # Include recent dialogue turns (excluding the message just added to prevent duplication)
    past_turns = _build_dialogue_history(raw_history[:-1], max_turns=6)
    messages.extend(past_turns)

    # Append current user prompt
    messages.append({"role": "user", "content": user_message})

    full_response = []
    success = False
    last_error = None

    # Try clients across pool with model fallback
    for attempt in range(len(clients)):
        client = _next_client()
        for active_model in (CHAT_MODEL, FALLBACK_MODEL):
            try:
                stream = client.chat.completions.create(
                    model=active_model,
                    messages=messages,
                    stream=True,
                    temperature=0.1,  # Focused factual accuracy
                    max_tokens=2200,
                )

                for chunk in stream:
                    content = chunk.choices[0].delta.content if chunk.choices else None
                    if content:
                        full_response.append(content)
                        yield f"data: {json.dumps({'delta': content})}\n\n"

                success = True
                break
            except (RateLimitError, APIError) as e:
                err_str = str(e)
                logger.warning(f"Groq API error with {active_model} on attempt {attempt + 1}: {err_str}.")
                last_error = err_str
                if full_response:
                    break
                continue
            except Exception as e:
                logger.error(f"Unexpected error with {active_model}: {e}")
                last_error = str(e)
                continue
        if success or full_response:
            break

    if not success:
        error_msg = f"Unable to generate response from AI service: {last_error or 'All keys exhausted'}"
        yield f"data: {json.dumps({'error': error_msg})}\n\n"
        full_response = [error_msg]

    # 5. Persist assistant message in DB
    final_content = "".join(full_response).strip()
    if final_content and success:
        db.add_chat_message(doc_id, "assistant", final_content)

    yield "data: [DONE]\n\n"
