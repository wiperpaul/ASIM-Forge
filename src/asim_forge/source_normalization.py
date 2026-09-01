"""Compatibility imports for the original source-normalization module."""

from .source_semantics import contains_source_phrase, source_tokens, strip_leading_bom


def structured_key_before(text: str, offset: int) -> str | None:
    """Compatibility wrapper for mapping-specific structured slot context."""

    from .semantic_mapping.source_context import structured_key_before as implementation

    return implementation(text, offset)


__all__ = [
    "contains_source_phrase",
    "source_tokens",
    "strip_leading_bom",
    "structured_key_before",
]
