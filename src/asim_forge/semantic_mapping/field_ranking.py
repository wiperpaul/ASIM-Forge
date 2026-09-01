"""Deterministic field-ranking helpers for the mapping phase."""

from __future__ import annotations

from pydantic import Field

from ..models import AsimCatalogField, StrictModel
from ..source_semantics import source_tokens
from .contracts import RankedFieldCandidate

# Field, unnormalized score, and the overlapping concepts that produced it.
CandidatePool = list[tuple[AsimCatalogField, float, list[str]]]


class FieldRanking(StrictModel):
    """Scored candidates reported beside the size of the pool they were cut from."""

    candidates: list[RankedFieldCandidate] = Field(default_factory=list)
    pool_size: int = Field(default=0, ge=0)
    considered_field_count: int = Field(default=0, ge=0)


def name_tokens(text: str) -> set[str]:
    return source_tokens(text)


def generate_candidates(fields: list[AsimCatalogField], query: str) -> CandidatePool:
    """Retain every catalogue field with lexical evidence, before any cut-off."""
    query_terms = source_tokens(query)
    pool: CandidatePool = []
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
        pool.append((field, (0.35 * precision) + (0.65 * coverage), overlap))
    return pool


def score_candidates(pool: CandidatePool, *, limit: int = 5) -> list[RankedFieldCandidate]:
    """Order the generated pool deterministically and record equal-score ties."""
    if not pool:
        return []
    ordered = sorted(pool, key=lambda item: (-item[1], item[0].name))
    maximum = ordered[0][1]
    tie_counts: dict[float, int] = {}
    for _, score, _ in ordered:
        tie_counts[score] = tie_counts.get(score, 0) + 1
    return [
        RankedFieldCandidate(
            asim_field=field.name,
            score=round(score / maximum, 6),
            tied_with=tie_counts[score] - 1,
            evidence=evidence,
        )
        for field, score, evidence in ordered[:limit]
    ]


def rank_field_candidates(
    fields: list[AsimCatalogField],
    query: str,
    *,
    limit: int = 5,
) -> FieldRanking:
    """Rank fields while preserving how much candidate generation discarded."""
    pool = generate_candidates(fields, query)
    return FieldRanking(
        candidates=score_candidates(pool, limit=limit),
        pool_size=len(pool),
        considered_field_count=len(fields),
    )


def rank_fields(
    fields: list[AsimCatalogField],
    query: str,
    *,
    limit: int = 5,
) -> list[RankedFieldCandidate]:
    return score_candidates(generate_candidates(fields, query), limit=limit)
