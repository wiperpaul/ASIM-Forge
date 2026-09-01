"""Signals for the classical matcher ensemble, each scored and reported separately.

Valentine's broad evaluation found no single matcher dominates and recommended
composing them. It also found that composing badly performs poorly, so every signal
here stays individually inspectable: an ensemble that wins for the wrong reason
should be visible as such rather than hidden inside one blended number.
"""

from __future__ import annotations

from pydantic import Field

from ..models import AsimCatalogField, StrictModel
from ..source_semantics import source_tokens
from .profiling import SlotProfile

# Catalogue types a physical type may legitimately populate.
_TYPE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "ipv4": frozenset({"string"}),
    "ipv6": frozenset({"string"}),
    "mac": frozenset({"string"}),
    "guid": frozenset({"string"}),
    "email": frozenset({"string"}),
    "url": frozenset({"string"}),
    "path": frozenset({"string"}),
    "hostname": frozenset({"string"}),
    "hex": frozenset({"string"}),
    "boolean": frozenset({"bool", "boolean", "string"}),
    "integer": frozenset({"int", "long", "real", "double", "string"}),
    "float": frozenset({"real", "double", "string"}),
    "timestamp": frozenset({"datetime", "string"}),
    "text": frozenset(),
}

# Catalogue logical types that describe a network port.
_PORT_LOGICAL_TYPES = frozenset({"port number", "port"})

# Concepts a profiled physical type expects to see in its target field's name or
# logical type. This is what separates `SrcIpAddr` from a bare `Src` when both are
# strings and the slot label carries no meaning.
_TYPE_AFFINITY: dict[str, frozenset[str]] = {
    "ipv4": frozenset({"ip", "address"}),
    "ipv6": frozenset({"ip", "address"}),
    "mac": frozenset({"mac", "address"}),
    "guid": frozenset({"id"}),
    "email": frozenset({"email"}),
    "url": frozenset({"url"}),
    "path": frozenset({"path"}),
    "timestamp": frozenset({"time"}),
    "hostname": frozenset({"hostname"}),
}

_NGRAM_SIZE = 3


class MatchSignals(StrictModel):
    """One candidate field scored by each signal independently."""

    asim_field: str
    lexical: float = Field(default=0.0, ge=0, le=1)
    character_ngram: float = Field(default=0.0, ge=0, le=1)
    type_compatibility: float = Field(default=0.0, ge=0, le=1)
    type_affinity: float = Field(default=0.0, ge=0, le=1)
    value_enumeration: float = Field(default=0.0, ge=0, le=1)
    range_plausibility: float = Field(default=0.0, ge=0, le=1)
    combined: float = Field(default=0.0, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


def character_ngram_similarity(left: str, right: str) -> float:
    """Dice coefficient over character n-grams, robust to affixes and typos."""
    left_grams = _ngrams(left)
    right_grams = _ngrams(right)
    if not left_grams or not right_grams:
        return 0.0
    overlap = len(left_grams & right_grams)
    return (2 * overlap) / (len(left_grams) + len(right_grams))


def type_compatibility(profile: SlotProfile | None, field: AsimCatalogField) -> float:
    """1 when the profiled type can populate the catalogue type, 0 when it cannot.

    A `text` profile is uninformative rather than incompatible, so it returns a
    neutral score instead of vetoing every candidate.
    """
    if profile is None or profile.physical_type == "text":
        return 0.5
    allowed = _TYPE_COMPATIBILITY.get(profile.physical_type, frozenset())
    if not allowed:
        return 0.5
    return 1.0 if field.kql_type.casefold() in allowed else 0.0


def type_affinity(profile: SlotProfile | None, field: AsimCatalogField) -> float:
    """Share of the profiled type's expected concepts present in the target field.

    Catalogue types are too coarse to separate an address from any other string, so
    this reads the value shape against the field's own naming instead.
    """
    if profile is None:
        return 0.0
    expected = set(_TYPE_AFFINITY.get(profile.physical_type, frozenset()))
    if profile.port_plausible:
        expected.add("port")
    if not expected:
        return 0.0
    field_terms = source_tokens(field.name)
    if field.logical_type:
        field_terms |= source_tokens(field.logical_type)
    return len(expected & field_terms) / len(expected)


def value_enumeration(values: list[str], field: AsimCatalogField) -> float:
    """Instance containment against the catalogue's own allowed values."""
    if not field.allowed_values or not values:
        return 0.0
    permitted = {allowed.casefold() for allowed in field.allowed_values}
    matched = sum(value.strip().casefold() in permitted for value in values)
    return matched / len(values)


def range_plausibility(profile: SlotProfile | None, field: AsimCatalogField) -> float:
    """Penalise a numeric slot whose observed range cannot fit the target field."""
    if profile is None or profile.numeric_max is None:
        return 0.5
    if not _is_port_field(field):
        return 0.5
    return 1.0 if profile.port_plausible else 0.0


def _is_port_field(field: AsimCatalogField) -> bool:
    logical = (field.logical_type or "").casefold()
    if logical in _PORT_LOGICAL_TYPES:
        return True
    return "port" in source_tokens(field.name)


def _ngrams(text: str) -> set[str]:
    normalized = " ".join(sorted(source_tokens(text)))
    if len(normalized) < _NGRAM_SIZE:
        return {normalized} if normalized else set()
    return {normalized[index : index + _NGRAM_SIZE] for index in range(len(normalized) - 2)}
