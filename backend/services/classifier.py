"""Forensic AI Contract Classifier for SmartExtractor.

Categorizes contracts into organizational departments (directories) using a 4-Pillar
Forensic AI legal analysis:
  1. Recitals & Preamble (WHEREAS clauses)
  2. Scope of Work / Annexure A deliverables
  3. Pricing & Billing metric units (KVA/Rack vs vCPU/Storage vs Bandwidth vs Seats)
  4. Primary Objective vs Incidental Mention (e.g. Cloud VM hosted in a DC = Cloud Services)
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional

from services.llm_parser import _get_clients, _next_client, MODEL

logger = logging.getLogger("smartextractor.classifier")

# Heuristic scoring rules for offline / rate-limit fallback
FORENSIC_RULES = {
    "Data Center": {
        "strong": [
            r"\bcolocation\b", r"\bcolo\b", r"\brack\s*(?:space|unit|cabinet)\b",
            r"\btier\s*(?:iii|iv|3|4)\b", r"\bpower\s+and\s+cooling\b",
            r"\bkva\b", r"\bkwh\b", r"\bserver\s+cage\b", r"\braised\s+floor\b",
            r"\bmeet-me\s+room\b", r"\bmmr\b", r"\bcross[- ]connect\b", r"\bdatacenter\b", r"\bdata\s+center\b"
        ],
        "context": [r"\bfacility\b", r"\buptime\s+99\.9\b", r"\bgenerator\b", r"\bups\b"]
    },
    "Cloud Services": {
        "strong": [
            r"\bvirtual\s+machine\b", r"\bvm[s]?\b", r"\biaas\b", r"\bpaas\b",
            r"\bcloud\s+(?:compute|storage|backup|hosting|service)\b",
            r"\bvcpu\b", r"\bram\s*(?:gb|tb)\b", r"\bobject\s+storage\b",
            r"\baws\b", r"\bazure\b", r"\bgcp\b", r"\bvirtual\s+server\b",
            r"\bcompute\s+instance\b", r"\bkubernetes\b", r"\bcontainer\b"
        ],
        "context": [r"\bcloud\b", r"\bsla\b", r"\binstance\b", r"\bscalable\b"]
    }
}


def _heuristic_classify(text: str, filename: str = "", allowed_departments: List[str] = None) -> Dict[str, Any]:
    """Forensic pattern heuristic classifier as high-resilience fallback."""
    combined_text = f"{filename}\n{text}".lower()
    scores = {}
    signals = {}

    allowed = set(allowed_departments) if allowed_departments else None

    for dept, rules in FORENSIC_RULES.items():
        if allowed and dept not in allowed:
            continue
        strong_matches = []
        for pat in rules["strong"]:
            m = re.findall(pat, combined_text)
            if m:
                strong_matches.extend(m)
        context_matches = []
        for pat in rules["context"]:
            m = re.findall(pat, combined_text)
            if m:
                context_matches.extend(m)

        # 3 points per strong pattern, 1 point per context pattern
        total_score = (len(strong_matches) * 3) + len(context_matches)
        scores[dept] = total_score
        signals[dept] = {
            "strong": list(set(strong_matches))[:5],
            "context": list(set(context_matches))[:5]
        }

    # Pick the top scorer
    sorted_depts = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if not sorted_depts or sorted_depts[0][1] < 3:
        return {
            "department": "General",
            "confidence": 0.85,
            "rationale": "Document does not exhibit dominant technical patterns for Data Center or Cloud Services. Categorized as General.",
            "method": "heuristic_fallback",
            "signals": {}
        }

    top_dept, top_score = sorted_depts[0]
    runner_up_score = sorted_depts[1][1] if len(sorted_depts) > 1 else 0

    # Margin check
    confidence = min(0.95, 0.70 + (0.05 * min(5, (top_score - runner_up_score))))
    top_signals = signals.get(top_dept, {})
    matched_words = top_signals.get("strong", []) + top_signals.get("context", [])

    return {
        "department": top_dept,
        "confidence": round(confidence, 2),
        "rationale": f"Matched forensic indicators for {top_dept}: {', '.join(matched_words[:4])}.",
        "method": "heuristic_fallback",
        "signals": top_signals
    }


def classify_contract_department(
    text: str,
    ocr_pages: Optional[List[Dict[str, Any]]] = None,
    filename: str = "",
    extracted: Optional[Dict[str, Any]] = None,
    departments: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Classifies a contract into a department using Groq LLM with 4-pillar forensic analysis.
    Falls back gracefully to forensic regex heuristics if LLM is unavailable.
    """
    dept_names = [d["name"] for d in departments] if departments else [
        "Data Center", "Cloud Services", "General"
    ]

    # Synthesize best context text (first 3-4 pages or up to 6000 chars covers Preamble, Scope, Pricing)
    doc_sample = ""
    if ocr_pages:
        sample_pages = []
        for p in ocr_pages[:4]:
            t = p.get("text", "") or ""
            if not t and "lines" in p:
                t = "\n".join(" ".join(w.get("text", "") for w in line) for line in p["lines"])
            sample_pages.append(t)
        doc_sample = "\n--- PAGE BREAK ---\n".join(sample_pages)

    if not doc_sample.strip():
        doc_sample = text[:6000] if text else ""

    if extracted:
        # Append extracted scope or title if available
        doc_info = extracted.get("document_info", {})
        cust_info = extracted.get("customer_info", {})
        price_info = extracted.get("financial_terms", {}) or extracted.get("pricing", {})
        doc_sample = (
            f"FILE_NAME: {filename}\n"
            f"CONTRACT_NAME: {doc_info.get('contract_name', {}).get('value', '')}\n"
            f"CUSTOMER: {cust_info.get('name', {}).get('value', '')}\n"
            f"DOCUMENT_TEXT_SAMPLE:\n{doc_sample}"
        )

    # If document sample is too sparse, run heuristic fallback immediately
    if len(doc_sample.strip()) < 30:
        return _heuristic_classify(text or filename, filename=filename, allowed_departments=dept_names)

    # Build Forensic LLM prompt
    dept_descriptions = []
    if departments:
        for d in departments:
            desc = d.get("description", "")
            dept_descriptions.append(f"- **{d['name']}**: {desc}")
    else:
        dept_descriptions = [
            "- **Data Center**: Colocation, physical rack space, power & cooling, cages, MMR cross-connects, facility infrastructure.",
            "- **Cloud Services**: Virtual machines (VMs), IaaS, cloud compute, cloud storage, managed cloud, container services.",
            "- **General**: All contracts and agreements that are neither Data Center colocation nor Cloud services (e.g. non-infrastructure contracts, MSAs, NDAs, or other agreements)."
        ]

    system_prompt = (
        "You are an enterprise legal counsel and forensic contract auditor.\n"
        "Your task is to classify the provided contract into exactly one organizational Directory: Data Center, Cloud Services, or General.\n\n"
        "Apply the 4-Pillar Forensic Legal Methodology:\n"
        "1. Preamble & Recitals ('WHEREAS' clauses): Identify legal intent and governing subject matter.\n"
        "2. Scope of Work / Annexures: Identify the primary deliverable being provisioned.\n"
        "3. Pricing & Billing Model: Identify metric units (e.g. KVA/Rack = Data Center; vCPU/RAM/Storage = Cloud Services).\n"
        "4. Primary Objective vs Incidental Reference: If a Cloud provider mentions servers in a physical data center, the contract is CLOUD SERVICES because the primary deliverable is virtual compute.\n"
        "5. Fallback Rule for General: If the contract is neither Data Center colocation/power nor Cloud compute/storage, classify it as General.\n\n"
        "Available Departments:\n" + "\n".join(dept_descriptions) + "\n\n"
        "Output MUST be strict JSON in this exact structure:\n"
        "{\n"
        f'  "department": "One of {json.dumps(dept_names)}",\n'
        '  "confidence": 0.95,\n'
        '  "rationale": "Concise 1-2 sentence explanation citing primary deliverables and pricing units."\n'
        "}"
    )

    try:
        clients = _get_clients()
        client = _next_client()
        classifier_model = os.environ.get("CLASSIFIER_MODEL", "llama-3.1-8b-instant")
        try:
            response = client.chat.completions.create(
                model=classifier_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Document Snippet:\n{doc_sample[:5000]}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=1024
            )
        except Exception:
            # Fall back to default model with larger token budget for reasoning
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Document Snippet:\n{doc_sample[:5000]}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2048
            )
        content = response.choices[0].message.content
        result = json.loads(content)
        parsed_dept = result.get("department", "").strip()

        # Validate that returned department is in allowed list
        matched_dept = None
        for d in dept_names:
            if d.lower() == parsed_dept.lower():
                matched_dept = d
                break

        if not matched_dept:
            for d in dept_names:
                if d.lower() in parsed_dept.lower():
                    matched_dept = d
                    break

        if matched_dept:
            return {
                "department": matched_dept,
                "confidence": float(result.get("confidence", 0.9)),
                "rationale": result.get("rationale", f"Classified as {matched_dept} via forensic analysis."),
                "method": "llm_forensic"
            }
        else:
            logger.warning(f"LLM returned department '{parsed_dept}' not in allowed list, falling back to heuristic.")
            return _heuristic_classify(doc_sample, filename=filename, allowed_departments=dept_names)

    except Exception as e:
        logger.warning(f"LLM classification encountered error ({e}); falling back to forensic heuristics.")
        return _heuristic_classify(doc_sample, filename=filename, allowed_departments=dept_names)
