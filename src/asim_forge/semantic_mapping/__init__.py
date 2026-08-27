"""Separated deterministic semantic mapping approaches and contracts."""

from .contracts import MappingRequest, SemanticMappingApproach, SemanticMappingPrediction
from .types import SemanticMappingInput, SemanticSourceMetadata
from .direct import DirectLexicalApproach
from .frame import SemanticFrameApproach

APPROACH_NAMES = ("direct-lexical", "semantic-frame")

__all__ = [
    "APPROACH_NAMES",
    "DirectLexicalApproach",
    "MappingRequest",
    "SemanticFrameApproach",
    "SemanticMappingApproach",
    "SemanticMappingInput",
    "SemanticMappingPrediction",
    "SemanticSourceMetadata",
]
