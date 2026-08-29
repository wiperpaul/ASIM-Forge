"""Registry for independently packaged semantic mapping approaches."""

from __future__ import annotations

from collections.abc import Callable

from ..contracts import SemanticMappingApproach
from .direct_lexical import DirectLexicalApproach
from .semantic_frame import SemanticFrameApproach

_APPROACH_FACTORIES: dict[str, Callable[[], SemanticMappingApproach]] = {
    DirectLexicalApproach.identity.name: DirectLexicalApproach,
    SemanticFrameApproach.identity.name: SemanticFrameApproach,
}

APPROACH_NAMES = tuple(_APPROACH_FACTORIES)


def build_approach(name: str) -> SemanticMappingApproach:
    """Create one registered approach without coupling callers to its package."""
    try:
        factory = _APPROACH_FACTORIES[name]
    except KeyError as error:
        raise ValueError(f"Unknown semantic mapping approach: {name}") from error
    return factory()


__all__ = [
    "APPROACH_NAMES",
    "DirectLexicalApproach",
    "SemanticFrameApproach",
    "build_approach",
]
