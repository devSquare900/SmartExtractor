import itertools
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from groq import BadRequestError, Groq, RateLimitError

from services.parser import build_blocks, group_rows, merge_boxes

# Load .env file
load_dotenv()

MODEL = "openai/gpt-oss-20b"
# Reasoning tokens count as output: when they use up the limit Groq returns no JSON at all
# ("json_validate_failed" with an empty failed_generation), so leave room for them.
MAX_OUTPUT_TOKENS = 4096

# Groq caps the tokens of one request (8,000 per minute on the free tier), far below the
# model's context window, so the document text gets a character budget. Raise it on a higher tier.
MAX_INPUT_CHARS = int(os.environ.get("LLM_MAX_INPUT_CHARS", "16000"))

# The model sometimes ends without writing any JSON; the same request usually works when repeated.
# With several API keys there is at least one attempt per key.
MAX_ATTEMPTS = 3

# When a document is over the budget: lines kept on each side of a keyword hit,
# and lines kept after a clause heading (the clause body rarely repeats the keyword).
CONTEXT_LINES = 2
HEADING_LINES = 10
HEADING_MAX_CHARS = 80

NUMBERED_LINE = re.compile(r"^\(?\d+(\.\d+)*[.)]?(\s|$)")
DOT_LEADER = re.compile(r"\.{4,}|…{2,}")

# Confidence given to a value the cited lines do not back up, so it is flagged for review.
UNVERIFIED_CONFIDENCE = 0.5
# Share of a value's words that must appear in the cited lines for it to count as backed up.
MIN_OVERLAP = 0.75

# "summary" fields are reworded by the LLM, so their text cannot be checked against the source.
# "keywords" (most specific first) decide which lines are kept when a document is over the budget.
# The price fields are kept together at the end so they land in the same call (see field_groups).
FIELDS = {
    "contract_name": {
        "description": "The title of the document, e.g. \"Service Agreement\".",
        "keywords": [],
    },
    "execution_date": {
        "description": "The date the contract was signed/executed.",
        "keywords": ["execution date", "effective date", "dated", "signed", "executed", "commenc",
                     "entered into", "date"],
    },
    "expiry_date": {
        "description": "The date the contract expires.",
        "keywords": ["expiry", "expir", "end date", "valid until", "valid till", "valid upto", "valid up to"],
    },
    "validity_tenure": {
        "description": "The duration the contract is valid for, e.g. \"12 months\".",
        "keywords": ["tenure", "validity", "duration", "initial term", "fixed term", "term of", "valid for",
                     "period of", "renew"],
    },
    "termination_clause": {
        "description": "A summary of the termination clause in at most 2 sentences. Do not copy the full text.",
        "keywords": ["terminat", "notice period", "written notice", "days notice", "days' notice"],
        "summary": True,
    },
    "mrc": {
        "description": "The total Monthly Recurring Charges (MRC) at the full price, before any discount, "
                       "with the currency. Use the total, not a single line item.",
        "keywords": ["mrc", "monthly recurring", "recurring", "per month", "/ month", "financials", "charges",
                     "price", "monthly", "total"],
    },
    "mrc_discounted": {
        "description": "The total Monthly Recurring Charges after discount, with the currency. "
                       "null if the document shows no discounted price.",
        "keywords": ["discount", "net total", "net amount", "net price"],
    },
    "otc": {
        "description": "The total One Time Charges (OTC), e.g. installation or setup, at the full price, "
                       "before any discount, with the currency. Use the total, not a single line item.",
        "keywords": ["otc", "one time", "one-time", "non-recurring", "installation", "setup", "set-up"],
    },
    "otc_discounted": {
        "description": "The total One Time Charges after discount, with the currency. "
                       "null if the document shows no discounted price.",
        "keywords": [],
    },
}

PROMPT_INTRO = """You are an expert enterprise legal AI assistant.
Your job is to read contract and invoice documents and extract specific data.

The document text has one line per visual row, each starting with a line ID in square brackets.
Cells on the same row are separated by " | ". "--- Page N ---" marks the start of a page and "..." marks omitted lines.

Example:
--- Page 1 ---
[0] SERVICE AGREEMENT
[1] Execution Date | 12 October 2023

For each field return:
- "value": the text exactly as written in the document, or null if the document does not contain it.
- "source_ids": the IDs of the lines the value came from, or [] if the value is null.
  Cite the lines of the clause itself, never its entry in a table of contents.

The fields to extract are:
"""

_FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": ["string", "null"]},
        "source_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["value", "source_ids"],
    "additionalProperties": False,
}


def system_prompt(keys: list) -> str:
    return PROMPT_INTRO + "\n".join(f'- "{key}": {FIELDS[key]["description"]}' for key in keys)


def response_schema(keys: list) -> dict:
    return {
        "type": "object",
        "properties": {key: _FIELD_SCHEMA for key in keys},
        "required": list(keys),
        "additionalProperties": False,
    }


def field_groups(count: int) -> list:
    """Splits the fields into up to `count` groups of neighbouring fields, one LLM call each."""
    keys = list(FIELDS)
    size = -(-len(keys) // max(1, min(count, len(keys))))
    return [keys[i:i + size] for i in range(0, len(keys), size)]


def _api_keys() -> list:
    """Keys from GROQ_API_KEY, GROQ_API_KEY_2, ... (each may also hold several, comma-separated)."""
    names = sorted(name for name in os.environ if name.startswith("GROQ_API_KEY"))
    keys = [key.strip() for name in names for key in os.environ[name].split(",")]
    return list(dict.fromkeys(key for key in keys if key))


# One client per API key, used in turn so the load (and each key's rate limit) is shared.
# Created on first use so the module can be imported without an API key (e.g. in tests).
_clients = None
_client_cycle = None
_client_lock = threading.Lock()  # background tasks run in a thread pool


def _get_clients() -> list:
    global _clients, _client_cycle
    with _client_lock:
        if _clients is None:
            keys = _api_keys()
            if not keys:
                raise RuntimeError("GROQ_API_KEY is not set")
            _clients = [Groq(api_key=key) for key in keys]
            _client_cycle = itertools.cycle(_clients)
        return _clients


def _next_client():
    _get_clients()
    with _client_lock:
        return next(_client_cycle)


def build_lines(ocr_pages: list) -> list:
    """Merges the blocks of each visual row into one line, so table rows reach the LLM intact."""
    blocks = [b for b in build_blocks(ocr_pages) if b["text"]]
    return [
        {"id": i, "page_num": row[0]["page_num"], "text": " | ".join(b["text"] for b in row), "blocks": row}
        for i, row in enumerate(group_rows(blocks))
    ]


def _line_cost(line: dict) -> int:
    return len(line["text"]) + 8  # "[id] " prefix and newline


def drop_contents_lines(lines: list) -> list:
    """A table of contents repeats every clause title, and the LLM then cites it instead of the clause."""
    leaders = {}
    for ln in lines:
        leaders.setdefault(ln["page_num"], []).append(bool(DOT_LEADER.search(ln["text"])))
    contents_pages = {page for page, flags in leaders.items() if sum(flags) >= 5 and sum(flags) * 2 >= len(flags)}
    return [ln for ln in lines if not (ln["page_num"] in contents_pages and DOT_LEADER.search(ln["text"]))]


def _keyword_windows(lines: list, keywords: list) -> list:
    """Indexes of the lines around each keyword hit, best hit first: clause headings, numbered clauses, the rest."""
    ranked = []
    for i, ln in enumerate(lines):
        text = ln["text"].lower()
        strength = next((k for k, kw in enumerate(keywords) if kw in text), None)
        if strength is None:
            continue
        numbered = bool(NUMBERED_LINE.match(text))
        heading = len(text) <= HEADING_MAX_CHARS and (numbered or ln["text"].isupper())
        ranked.append((0 if heading else 1 if numbered else 2, strength, i))

    indexes = []
    for tier, _, i in sorted(ranked):
        lo, hi = (i, i + HEADING_LINES) if tier == 0 else (i - CONTEXT_LINES, i + CONTEXT_LINES)
        indexes.extend(range(max(0, lo), min(len(lines), hi + 1)))
    return indexes


def _take(lines: list, order, limit: int, chosen: set) -> int:
    """Adds lines to `chosen` in the given order while they fit `limit`; returns the characters used."""
    used = 0
    for i in order:
        cost = _line_cost(lines[i])
        if i not in chosen and used + cost <= limit:
            chosen.add(i)
            used += cost
    return used


def select_lines(lines: list, budget: int = None, keys: list = None) -> list:
    """
    Returns the lines to send for the given fields, in document order. All of them if they fit the
    budget. Otherwise the first and last page and every field get an equal share, so one field's keywords
    cannot crowd out another field's clause; what is left over goes to the remaining hits and then the rest.
    """
    budget = MAX_INPUT_CHARS if budget is None else budget
    keys = list(FIELDS) if keys is None else keys
    if sum(_line_cost(ln) for ln in lines) <= budget:
        return lines

    edge_pages = (lines[0]["page_num"], lines[-1]["page_num"])
    plans = [[i for i, ln in enumerate(lines) if ln["page_num"] in edge_pages]]
    plans += [_keyword_windows(lines, FIELDS[key]["keywords"]) for key in keys if FIELDS[key]["keywords"]]

    chosen = set()
    share = budget // len(plans)
    for plan in plans:
        budget -= _take(lines, plan, share, chosen)
    for plan in [*plans, range(len(lines))]:
        budget -= _take(lines, plan, budget, chosen)
    return [ln for i, ln in enumerate(lines) if i in chosen]


def render_lines(lines: list) -> str:
    out, page, prev_id = [], None, None
    for ln in lines:
        if ln["page_num"] != page:
            page = ln["page_num"]
            out.append(f"--- Page {page} ---")
        elif ln["id"] != prev_id + 1:
            out.append("...")
        out.append(f"[{ln['id']}] {ln['text']}")
        prev_id = ln["id"]
    return "\n".join(out)


def extract_data_with_llm(document_text: str, keys: list = None) -> dict:
    """Sends the prepared document text to Groq and returns {field: {"value", "source_ids"}} for `keys`."""
    keys = list(FIELDS) if keys is None else keys
    attempts = max(MAX_ATTEMPTS, len(_get_clients()))
    for attempt in range(1, attempts + 1):
        # Every attempt uses the next key. Until the last attempt a rate-limited key fails at once,
        # so the next key is tried instead of waiting; the last attempt waits for the limit to reset.
        client = _next_client().with_options(max_retries=2 if attempt == attempts else 0)
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt(keys)},
                    {"role": "user", "content": f"Extract the data from this document text:\n\n{document_text}"},
                ],
                model=MODEL,
                # Strict schema: the reply is always valid JSON in exactly this shape
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "extraction", "strict": True, "schema": response_schema(keys)},
                },
                temperature=0.0,  # Zero creativity, 100% logic
                max_tokens=MAX_OUTPUT_TOKENS,  # Allow enough tokens so JSON is not cut off
            )
            return json.loads(chat_completion.choices[0].message.content)
        except Exception as e:
            print(f"Error during LLM extraction (attempt {attempt} of {attempts}): {e}")
            retryable = isinstance(e, RateLimitError) or (
                isinstance(e, BadRequestError) and "json_validate_failed" in str(e))
            if not retryable or attempt == attempts:
                raise RuntimeError(f"Groq LLM Error: {str(e)}")


def _words(text: str) -> set:
    return set(re.findall(r"\w+", text.lower()))


def _to_ids(source_ids) -> list:
    """The LLM may return IDs as strings; anything that is not a whole number is dropped."""
    ids = []
    for sid in source_ids if isinstance(source_ids, list) else []:
        try:
            ids.append(int(sid))
        except (TypeError, ValueError):
            continue
    return ids


def build_field(raw, lines_by_id: dict, summary: bool = False) -> dict:
    """
    Turns one LLM answer into a field with a highlight box. The value is checked against the lines
    the LLM cited: a value with no source, or one the source does not contain, gets a low confidence.
    """
    raw = raw if isinstance(raw, dict) else {"value": raw}
    value = str(raw.get("value") or "").strip()
    if not value or value.upper() == "N/A":
        return {"value": "", "confidence": 1.0}

    cited = [lines_by_id[i] for i in dict.fromkeys(_to_ids(raw.get("source_ids"))) if i in lines_by_id]
    if not cited:
        return {"value": value, "confidence": UNVERIFIED_CONFIDENCE}

    # One box cannot span pages: keep the page with the most cited lines.
    pages = [ln["page_num"] for ln in cited]
    page_num = max(sorted(set(pages)), key=pages.count)
    blocks = [b for ln in cited if ln["page_num"] == page_num for b in ln["blocks"]]

    verified = True
    if not summary:
        value_words = _words(value)
        # A value often wraps onto the next row, so the rows next to the cited ones count as source too.
        nearby = {j for ln in cited for j in (ln["id"] - 1, ln["id"], ln["id"] + 1)}
        found = value_words & _words(" ".join(lines_by_id[j]["text"] for j in nearby if j in lines_by_id))
        verified = bool(value_words) and len(found) / len(value_words) >= MIN_OVERLAP
        # Highlight only the cells holding the value, not the whole row.
        blocks = [b for b in blocks if value_words & _words(b["text"])] or blocks

    confidence = sum(b["confidence"] for b in blocks) / len(blocks)
    if not verified:
        confidence = min(confidence, UNVERIFIED_CONFIDENCE)
    return {
        "value": value,
        "confidence": round(confidence, 4),
        "box": merge_boxes([b["box"] for b in blocks]),
        "page_num": page_num,
    }


def extract_fields(ocr_pages: list) -> dict:
    """
    OCR pages -> {field key: field dict} for every field in FIELDS.

    A document that fits the budget takes one call. A larger one is not cut into parts (two parts could
    give two different answers for one field); instead the fields are divided over the API keys, so each
    call spends its whole budget on the lines its own fields need. The calls run at the same time.
    """
    lines = drop_contents_lines(build_lines(ocr_pages))
    if not lines:
        return {key: build_field(None, {}) for key in FIELDS}

    groups = [list(FIELDS)]
    if sum(_line_cost(ln) for ln in lines) > MAX_INPUT_CHARS:
        groups = field_groups(len(_get_clients()))

    def run(keys):
        sent = select_lines(lines, keys=keys)
        return sent, extract_data_with_llm(render_lines(sent), keys)

    with ThreadPoolExecutor(len(groups)) as pool:
        answers = list(pool.map(run, groups))

    fields = {}
    for keys, (sent, result) in zip(groups, answers):
        lines_by_id = {ln["id"]: ln for ln in sent}
        for key in keys:
            fields[key] = build_field(result.get(key), lines_by_id, FIELDS[key].get("summary", False))
    return {key: fields[key] for key in FIELDS}
