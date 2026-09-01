"""Retrieval-specific lexical matching and vote normalization."""

from __future__ import annotations

from collections.abc import Mapping

from ....source_semantics import source_tokens
from ...contracts import RankedFieldCandidate


def similarity(left: str, right: str) -> float:
    left_terms = source_tokens(left)
    right_terms = source_tokens(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def weighted_candidates(
    scores: Mapping[str, float],
    *,
    limit: int = 5,
) -> list[RankedFieldCandidate]:
    positive_scores = {name: score for name, score in scores.items() if score > 0}
    if not positive_scores:
        return []
    maximum = max(positive_scores.values())
    return [
        RankedFieldCandidate(asim_field=name, score=round(score / maximum, 6))
        for name, score in sorted(
            positive_scores.items(),
            key=lambda item: (-item[1], item[0]),
        )[:limit]
    ]
