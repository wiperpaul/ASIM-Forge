"""Target-neutral source-semantic preprocessing."""

from .normalization import contains_source_phrase, source_tokens, strip_leading_bom
from .source_frame import (
    FACET_NAMES,
    REGISTERED_ROLES,
    REGISTRY_REVISION,
    SourceFrameFacets,
    SourceFrameRole,
    canonical_role,
    facet_keys,
    parse_role,
    registered_role,
)

__all__ = [
    "FACET_NAMES",
    "REGISTERED_ROLES",
    "REGISTRY_REVISION",
    "SourceFrameFacets",
    "SourceFrameRole",
    "canonical_role",
    "contains_source_phrase",
    "facet_keys",
    "parse_role",
    "registered_role",
    "source_tokens",
    "strip_leading_bom",
]
