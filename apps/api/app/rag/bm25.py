"""Okapi BM25 lexical retrieval (small, dependency-free, deterministic).

Lexical retrieval matters for policy questions: exact tokens like "10%", "SVC-AMC" or "₹50,000"
are often what distinguishes the right clause, and dense embeddings blur them.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*%?|₹[0-9][0-9,]*", re.I)
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "may",
        "of",
        "on",
        "or",
        "our",
        "should",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "us",
        "was",
        "we",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "without",
        "would",
        "you",
        "your",
    ]
)


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _TOKEN.findall(text.lower()):
        tok = raw.replace(",", "") if raw[:1].isdigit() or raw.startswith("₹") else raw
        if tok not in STOPWORDS and len(tok) > 1 or tok.isdigit():
            tokens.append(tok)
    return tokens


@dataclass
class BM25Index:
    doc_ids: list[str]
    term_freqs: list[Counter[str]]
    doc_lens: list[int]
    idf: dict[str, float]
    avgdl: float
    k1: float = 1.5
    b: float = 0.75

    @classmethod
    def build(cls, docs: dict[str, str], k1: float = 1.5, b: float = 0.75) -> BM25Index:
        ids = list(docs)
        tfs = [Counter(tokenize(docs[i])) for i in ids]
        lens = [sum(tf.values()) for tf in tfs]
        n = len(ids)
        df: Counter[str] = Counter()
        for tf in tfs:
            df.update(tf.keys())
        # BM25+ style idf floor keeps very common terms non-negative.
        idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        return cls(ids, tfs, lens, idf, (sum(lens) / n) if n else 0.0, k1, b)

    def search(self, query: str, top_k: int, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        q = tokenize(query)
        if not q or not self.doc_ids:
            return []
        scores: list[tuple[str, float]] = []
        for doc_id, tf, dl in zip(self.doc_ids, self.term_freqs, self.doc_lens, strict=True):
            if allowed is not None and doc_id not in allowed:
                continue
            s = 0.0
            for term in q:
                f = tf.get(term)
                if not f:
                    continue
                s += self.idf[term] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            if s > 0:
                scores.append((doc_id, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
