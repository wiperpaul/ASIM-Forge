"""Mapping-specific context extraction around parameter slots."""

from __future__ import annotations

import re

from ..models import ParameterSlot
from .types import SemanticMappingInput

_STRUCTURED_KEY = re.compile(
    r"(?:^|[\s,;|{])['\"]?([A-Za-z][A-Za-z0-9_.-]*)['\"]?"
    r"\s*(?:=|:)\s*['\"]?$"
)


def structured_key_before(text: str, offset: int) -> str | None:
    """Return the structured key directly owning a placeholder at ``offset``."""

    match = _STRUCTURED_KEY.search(text[:offset])
    return match.group(1) if match is not None else None


def slot_context(mapping_input: SemanticMappingInput, slot: ParameterSlot) -> str:
    """Keep field-level context local to one parameter slot."""

    matches = list(re.finditer(re.escape(slot.placeholder), mapping_input.template))
    if slot.occurrence > len(matches):
        return f"{slot.label} {' '.join(slot.examples)}"
    match = matches[slot.occurrence - 1]
    structured_key = structured_key_before(mapping_input.template, match.start())
    if structured_key is not None:
        return f"{structured_key} {slot.label}"
    before = mapping_input.template[: match.start()].split()[-3:]
    after = mapping_input.template[match.end() :].split()[:2]
    if before and before[-1].casefold() in {"from", "to", "client", "server"}:
        return " ".join([before[-1], slot.label])
    if before and before[-1].casefold() == "port":
        return " ".join([*before[-2:], slot.label])
    return " ".join([*before, slot.label, *after])
