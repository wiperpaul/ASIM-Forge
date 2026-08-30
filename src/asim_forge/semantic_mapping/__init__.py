"""Separated semantic mapping approaches and contracts."""

from .approaches import (
    APPROACH_NAMES,
    CaseRetrievalApproach,
    DirectLexicalApproach,
    SemanticFrameApproach,
)
from .contracts import MappingRequest, SemanticMappingApproach, SemanticMappingPrediction
from .types import SemanticMappingInput, SemanticSourceMetadata

__all__ = [
    "APPROACH_NAMES",
    "CaseRetrievalApproach",
    "DirectLexicalApproach",
    "MappingRequest",
    "SemanticFrameApproach",
    "SemanticMappingApproach",
    "SemanticMappingInput",
    "SemanticMappingPrediction",
    "SemanticSourceMetadata",
]
