"""Deterministic value profiling for parameter slots (the N2 rung).

The controlled track showed the frozen baseline loses most of its accuracy when
slot labels are made meaningless, and that it assigns a target to an unmapped slot
of a familiar type. Both failures share a cause: nothing reads the values.

This module derives evidence from the example values alone. It is deliberately
deterministic and inspectable rather than learned, so a downstream matcher can be
ablated against it signal by signal.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Literal

from pydantic import Field

from ..models import ParameterSlot, StrictModel

PhysicalType = Literal[
    "ipv4",
    "ipv6",
    "mac",
    "integer",
    "float",
    "hex",
    "guid",
    "timestamp",
    "email",
    "url",
    "path",
    "hostname",
    "boolean",
    "text",
]

# The highest value a TCP or UDP port can take.
MAX_PORT = 65535

# Ordered most specific first: `_detect_type` keeps the earliest pattern on a tie,
# so a MAC address must be tested before the looser IPv6 pattern that also matches it.
_PATTERNS: tuple[tuple[PhysicalType, re.Pattern[str]], ...] = (
    ("ipv4", re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")),
    ("mac", re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")),
    ("guid", re.compile(r"^\{?[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}?$")),
    ("ipv6", re.compile(r"^(?=.*:)[0-9A-Fa-f:]{2,45}$")),
    ("boolean", re.compile(r"^(?:true|false|yes|no|enabled|disabled)$", re.IGNORECASE)),
    ("integer", re.compile(r"^[+-]?\d+$")),
    ("float", re.compile(r"^[+-]?\d+\.\d+$")),
    (
        "timestamp",
        re.compile(
            r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$"
        ),
    ),
    ("email", re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")),
    ("url", re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://\S+$")),
    ("path", re.compile(r"^(?:[A-Za-z]:\\|\\\\|/)\S*$")),
    ("hex", re.compile(r"^(?:0[xX])?[0-9A-Fa-f]{8,}$")),
    ("hostname", re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?:\.(?!-)[A-Za-z0-9-]{1,63})+$")),
)


class SlotProfile(StrictModel):
    """Evidence derived from a slot's example values, independent of its label."""

    slot_id: str
    physical_type: PhysicalType = "text"
    # Share of example values matching the detected type.
    type_confidence: float = Field(default=0.0, ge=0, le=1)
    sample_count: int = Field(default=0, ge=0)
    distinct_count: int = Field(default=0, ge=0)
    uniqueness: float = Field(default=0.0, ge=0, le=1)
    min_length: int = Field(default=0, ge=0)
    max_length: int = Field(default=0, ge=0)
    numeric_min: float | None = None
    numeric_max: float | None = None
    # Shannon entropy over characters, a coarse opacity signal.
    character_entropy: float = Field(default=0.0, ge=0)
    has_letters: bool = False
    has_digits: bool = False
    has_punctuation: bool = False
    # An integer slot whose every value could be a port. Necessary, never sufficient.
    port_plausible: bool = False
    evidence: list[str] = Field(default_factory=list)


def profile_slot(slot: ParameterSlot) -> SlotProfile:
    """Derive a value profile from a slot's examples."""
    values = [value.strip() for value in slot.examples if value.strip()]
    if not values:
        return SlotProfile(
            slot_id=slot.slot_id,
            evidence=["no example values: profile carries no information"],
        )

    physical_type, confidence = _detect_type(values)
    lengths = [len(value) for value in values]
    numbers = _numeric_values(values, physical_type)
    distinct = len(set(values))
    return SlotProfile(
        slot_id=slot.slot_id,
        physical_type=physical_type,
        type_confidence=round(confidence, 6),
        sample_count=len(values),
        distinct_count=distinct,
        uniqueness=round(distinct / len(values), 6),
        min_length=min(lengths),
        max_length=max(lengths),
        numeric_min=min(numbers) if numbers else None,
        numeric_max=max(numbers) if numbers else None,
        character_entropy=round(_entropy(values), 6),
        has_letters=any(char.isalpha() for value in values for char in value),
        has_digits=any(char.isdigit() for value in values for char in value),
        has_punctuation=any(
            not char.isalnum() and not char.isspace() for value in values for char in value
        ),
        port_plausible=bool(numbers)
        and physical_type == "integer"
        and all(0 <= number <= MAX_PORT for number in numbers),
        evidence=[f"{len(values)} example value(s) profiled as {physical_type}"],
    )


def profile_slots(slots: list[ParameterSlot]) -> dict[str, SlotProfile]:
    return {slot.slot_id: profile_slot(slot) for slot in slots}


def _detect_type(values: list[str]) -> tuple[PhysicalType, float]:
    """Pick the most specific type matching the most values."""
    best: tuple[PhysicalType, float] = ("text", 0.0)
    for name, pattern in _PATTERNS:
        matched = sum(bool(pattern.match(value)) for value in values)
        if not matched:
            continue
        share = matched / len(values)
        # Pattern order encodes specificity, so only a strictly better share wins.
        if share > best[1]:
            best = (name, share)
    return best if best[1] > 0 else ("text", 1.0)


def _numeric_values(values: list[str], physical_type: PhysicalType) -> list[float]:
    if physical_type not in ("integer", "float"):
        return []
    numbers: list[float] = []
    for value in values:
        try:
            numbers.append(float(value))
        except ValueError:
            continue
    return numbers


def _entropy(values: list[str]) -> float:
    counts = Counter(char for value in values for char in value)
    total = sum(counts.values())
    if not total:
        return 0.0
    return -sum((count / total) * math.log2(count / total) for count in counts.values() if count)
