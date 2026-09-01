"""Deterministic field-ranking helpers for the mapping phase."""

from __future__ import annotations

from ..models import AsimCatalogField
from ..source_semantics import source_tokens
from .contracts import RankedFieldCandidate


def name_tokens(text: str) -> set[str]:
    return source_tokens(text)


def rank_fields(
    fields: list[AsimCatalogField],
    query: str,
    *,
    limit: int = 5,
) -> list[RankedFieldCandidate]:
    query_terms = source_tokens(query)
    scored: list[tuple[AsimCatalogField, float, list[str]]] = []
    for field in fields:
        if field.field_class == "Alias":
            continue
        field_terms = name_tokens(field.name)
        if field.logical_type:
            field_terms |= source_tokens(field.logical_type)
        overlap = sorted(query_terms & field_terms)
        if not overlap:
            continue
        precision = len(overlap) / len(field_terms)
        coverage = len(overlap) / len(query_terms)
        score = (0.35 * precision) + (0.65 * coverage)
        scored.append((field, score, overlap))
    scored.sort(key=lambda item: (-item[1], item[0].name))
    if not scored:
        return []
    maximum = scored[0][1]
    return [
        RankedFieldCandidate(
            asim_field=field.name,
            score=round(score / maximum, 6),
            evidence=evidence,
        )
        for field, score, evidence in scored[:limit]
    ]
