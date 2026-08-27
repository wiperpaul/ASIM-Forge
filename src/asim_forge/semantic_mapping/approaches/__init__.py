"""Registry for independently packaged semantic mapping approaches."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ...evaluation import SemanticMappingCase
from ..contracts import SemanticMappingApproach
from .case_retrieval import CaseRetrievalApproach
from .direct_lexical import DirectLexicalApproach
from .semantic_frame import SemanticFrameApproach

ApproachFactory = Callable[[Sequence[SemanticMappingCase]], SemanticMappingApproach]


def _build_direct_lexical(_: Sequence[SemanticMappingCase]) -> SemanticMappingApproach:
    return DirectLexicalApproach()


def _build_semantic_frame(_: Sequence[SemanticMappingCase]) -> SemanticMappingApproach:
    return SemanticFrameApproach()


def _build_case_retrieval(
    reference_cases: Sequence[SemanticMappingCase],
) -> SemanticMappingApproach:
    return CaseRetrievalApproach(reference_cases)


_APPROACH_FACTORIES: dict[str, ApproachFactory] = {
    DirectLexicalApproach.identity.name: _build_direct_lexical,
    SemanticFrameApproach.identity.name: _build_semantic_frame,
    CaseRetrievalApproach.identity.name: _build_case_retrieval,
}

APPROACH_NAMES = tuple(_APPROACH_FACTORIES)


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
    "CaseRetrievalApproach",
    "DirectLexicalApproach",
    "SemanticFrameApproach",
    "build_approach",
]
