"""Registry for independently packaged semantic mapping approaches."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from ..contracts import SemanticMappingApproach
from .case_retrieval import CaseRetrievalApproach
from .direct_lexical import DirectLexicalApproach
from .priors import (
    FieldFrequencyPriorApproach,
    MajoritySchemaPriorApproach,
    NullPriorApproach,
)
from .semantic_frame import SemanticFrameApproach

if TYPE_CHECKING:
    from ...evaluation import SemanticMappingCase

ApproachFactory = Callable[[Sequence["SemanticMappingCase"]], SemanticMappingApproach]


def _build_null_prior(_: Sequence[SemanticMappingCase]) -> SemanticMappingApproach:
    return NullPriorApproach()


def _build_majority_schema_prior(
    reference_cases: Sequence[SemanticMappingCase],
) -> SemanticMappingApproach:
    return MajoritySchemaPriorApproach(reference_cases)


def _build_field_frequency_prior(
    reference_cases: Sequence[SemanticMappingCase],
) -> SemanticMappingApproach:
    return FieldFrequencyPriorApproach(reference_cases)


def _build_direct_lexical(_: Sequence[SemanticMappingCase]) -> SemanticMappingApproach:
    return DirectLexicalApproach()


def _build_semantic_frame(_: Sequence[SemanticMappingCase]) -> SemanticMappingApproach:
    return SemanticFrameApproach()


def _build_case_retrieval(
    reference_cases: Sequence[SemanticMappingCase],
) -> SemanticMappingApproach:
    return CaseRetrievalApproach(reference_cases)


# Priors are listed first so every report reads the floor before the real approaches.
_APPROACH_FACTORIES: dict[str, ApproachFactory] = {
    NullPriorApproach.identity.name: _build_null_prior,
    MajoritySchemaPriorApproach.identity.name: _build_majority_schema_prior,
    FieldFrequencyPriorApproach.identity.name: _build_field_frequency_prior,
    DirectLexicalApproach.identity.name: _build_direct_lexical,
    SemanticFrameApproach.identity.name: _build_semantic_frame,
    CaseRetrievalApproach.identity.name: _build_case_retrieval,
}

APPROACH_NAMES = tuple(_APPROACH_FACTORIES)
PRIOR_APPROACH_NAMES = (
    NullPriorApproach.identity.name,
    MajoritySchemaPriorApproach.identity.name,
    FieldFrequencyPriorApproach.identity.name,
)
# Approaches whose answer depends on a labelled reference set rather than the event.
RETRIEVAL_APPROACH_NAMES = (CaseRetrievalApproach.identity.name,)


def build_approach(
    name: str,
    *,
    reference_cases: Sequence[SemanticMappingCase] = (),
) -> SemanticMappingApproach:
    """Create one registered approach without coupling callers to its package."""
    try:
        factory = _APPROACH_FACTORIES[name]
    except KeyError as error:
        raise ValueError(f"Unknown semantic mapping approach: {name}") from error
    return factory(reference_cases)


__all__ = [
    "APPROACH_NAMES",
    "PRIOR_APPROACH_NAMES",
    "RETRIEVAL_APPROACH_NAMES",
    "CaseRetrievalApproach",
    "DirectLexicalApproach",
    "FieldFrequencyPriorApproach",
    "MajoritySchemaPriorApproach",
    "NullPriorApproach",
    "SemanticFrameApproach",
    "build_approach",
]
