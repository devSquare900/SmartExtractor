"""
Enterprise Document Retrieval Engine (BM25 Information Retrieval)
Provides mathematical, deterministic relevance scoring for contract pages and clauses.
Zero brittle regexes, zero hardcoded keyword heuristics.
"""

import math
import re
from collections import Counter
from typing import List, Dict, Any, Tuple

# Standard English stopwords to remove noise from term-frequency calculations
STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had",
    "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
    "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off",
    "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own",
    "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some",
    "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then",
    "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "we'd",
    "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
}


def tokenize(text: str) -> List[str]:
    """Tokenizes alphanumeric terms and strips standard noise stopwords."""
    if not text:
        return []
    words = re.findall(r"[a-zA-Z0-9_\-\$]+", text.lower())
    return [w for w in words if len(w) > 1 and w not in STOP_WORDS]


class BM25Okapi:
    """
    Standard Okapi BM25 implementation for ranking document pages.
    k1: controls non-linear term frequency saturation (default 1.5)
    b: controls document length normalization (default 0.75)
    """

    def __init__(self, corpus: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.doc_lens = [len(doc) for doc in corpus]
        self.avgdl = sum(self.doc_lens) / max(1, self.corpus_size)

        self.doc_freqs = []
        df = Counter()
        for doc in corpus:
            counts = Counter(doc)
            self.doc_freqs.append(counts)
            for token in counts:
                df[token] += 1

        self.idf = {}
        for token, freq in df.items():
            # Standard Robertson-Spärck Jones IDF with smoothing
            self.idf[token] = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1.0)

    def get_scores(self, query: List[str]) -> List[float]:
        """Calculates relevance score for every document in the corpus."""
        scores = [0.0] * self.corpus_size
        for token in query:
            if token not in self.idf:
                continue
            idf_val = self.idf[token]
            for i, doc_freq in enumerate(self.doc_freqs):
                tf = doc_freq.get(token, 0)
                if tf > 0:
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * (self.doc_lens[i] / max(1, self.avgdl)))
                    scores[i] += idf_val * (numerator / denominator)
        return scores


def retrieve_relevant_pages(
    pages: List[Dict[str, Any]],
    query: str,
    char_budget: int = 12000,
    include_preamble: bool = True
) -> List[Tuple[int, str]]:
    """
    Retrieves the most relevant pages for a user's query within the token/character budget.
    - If total text fits within budget, preserves ALL pages intact.
    - If document exceeds budget:
        * Anchors Page 1 (Preamble / Parties / Contract Title) as foundational context.
        * Applies mathematical BM25 ranking to retrieve highest scoring pages for the specific query.
    - Always preserves sequential page order.
    """
    if not pages:
        return []

    # Prepare (page_num, text) pairs
    prepared_pages = []
    total_chars = 0
    for p in pages:
        p_num = int(p.get("page_num") or p.get("page_number") or 1)
        blocks = p.get("blocks") or []
        lines = [b.get("text", "").strip() for b in blocks if b.get("text")]
        if not lines and p.get("text"):
            lines = [p["text"].strip()]
        page_text = "\n".join(lines).strip()
        prepared_pages.append((p_num, page_text))
        total_chars += len(page_text)

    # Sort sequentially
    prepared_pages.sort(key=lambda x: x[0])

    # If the whole contract fits in budget, return all pages
    if total_chars <= char_budget:
        return prepared_pages

    # Large contract: Select pages within budget
    selected_indices = set()
    current_chars = 0

    # 1. Anchor Page 1 (Preamble & Parties) if requested and fits
    if include_preamble and prepared_pages:
        p1_len = len(prepared_pages[0][1])
        if p1_len < char_budget * 0.4:  # Only if Page 1 doesn't consume more than 40% of budget
            selected_indices.add(0)
            current_chars += p1_len

    # 2. Tokenize and score with BM25
    q_tokens = tokenize(query)
    corpus = [tokenize(text) for _, text in prepared_pages]

    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(q_tokens) if q_tokens else [0.0] * len(prepared_pages)

    # Pair each page with its score and index
    scored_pages = []
    for idx, (p_num, text) in enumerate(prepared_pages):
        if idx in selected_indices:
            continue
        scored_pages.append({
            "idx": idx,
            "page_num": p_num,
            "text": text,
            "score": scores[idx]
        })

    # Sort descending by relevance score
    scored_pages.sort(key=lambda x: x["score"], reverse=True)

    # Greedily take highest-scoring pages within rmaining budget
    for p in scored_pages:
        p_len = len(p["text"])
        if current_chars + p_len <= char_budget:
            selected_indices.add(p["idx"])
            current_chars += p_len
        elif not selected_indices:
            selected_indices.add(p["idx"])
            break
        if current_chars >= char_budget:
            break

    # Return selected pages in sequential order
    return [prepared_pages[i] for i in sorted(selected_indices)]
