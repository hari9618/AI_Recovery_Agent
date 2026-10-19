"""Reciprocal Rank Fusion (Cormack et al., 2009).

RRF combines ranked lists without needing comparable scores: BM25 scores and cosine similarities
live on different scales, but ranks do not. score(d) = Σ 1 / (k + rank_i(d)).
"""

from __future__ import annotations

from collections.abc import Sequence


def reciprocal_rank_fusion(rankings: dict[str, Sequence[str]], k: int = 60) -> list[tuple[str, float, dict[str, int]]]:
    """Fuse named rankings. Returns (id, fused_score, {ranking_name: 1-based rank}) sorted by score."""
    fused: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for name, ranking in rankings.items():
        for position, doc_id in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + position)
            ranks.setdefault(doc_id, {})[name] = position
    ordered = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(doc_id, score, ranks[doc_id]) for doc_id, score in ordered]
