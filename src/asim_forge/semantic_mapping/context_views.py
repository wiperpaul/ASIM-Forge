"""Context views that physically remove information before an approach sees it.

Asking an implementation not to read a field is not an ablation. Each view here
constructs a request that genuinely lacks the withheld evidence, so a measured
improvement between views is attributable to the information rather than to the
approach's discipline.

The views correspond to the context ladder in the corpus plan. V4 and V5 add
external documentation and repository evidence that no current approach consumes,
so they are deliberately absent until a provider can accept them.
"""

from __future__ import annotations

from typing import Literal

from ..models import ParameterSlot, SourceEvent
from .types import SemanticMappingInput, SemanticSourceMetadata

ContextView = Literal["v0", "v1", "v2", "v3", "full"]

CONTEXT_VIEWS: tuple[ContextView, ...] = ("v0", "v1", "v2", "v3", "full")

VIEW_DESCRIPTIONS: dict[ContextView, str] = {
    "v0": "Representative values only: no slot labels, template text, or metadata.",
    "v1": "V0 plus slot labels and the immediate token window.",
    "v2": "V1 plus the full template, constants, and every sibling slot.",
    "v3": "V2 plus source system, vendor, product, and table metadata.",
    "full": "The unmodified request.",
}

# Stand-ins for fields the input contract requires but a view must withhold.
_WITHHELD_TEXT = "<withheld>"
_WITHHELD_SYSTEM = "withheld"
_GAP = "..."
# Matches the local window the direct-lexical approach reads.
_WINDOW_BEFORE = 3
_WINDOW_AFTER = 2


def apply_context_view(
    mapping_input: SemanticMappingInput,
    view: ContextView,
) -> SemanticMappingInput:
    """Return an input holding only the evidence the named view permits."""
    if view == "full":
        return mapping_input
    if view == "v3":
        return mapping_input
    if view == "v2":
        return mapping_input.model_copy(update={"source_metadata": _masked_metadata()})
    if view == "v1":
        return mapping_input.model_copy(
            update={
                "template": _slot_only_template(mapping_input),
                "source_metadata": _masked_metadata(),
            }
        )
    return mapping_input.model_copy(
        update={
            "template": _WITHHELD_TEXT,
            "parameter_slots": [_unlabelled_slot(slot) for slot in mapping_input.parameter_slots],
            "representative_events": _value_only_events(mapping_input),
            "source_metadata": _masked_metadata(),
        }
    )


def _masked_metadata() -> SemanticSourceMetadata:
    return SemanticSourceMetadata(system=_WITHHELD_SYSTEM)


def _slot_only_template(mapping_input: SemanticMappingInput) -> str:
    """Keep a bounded window around each placeholder and drop the rest of the template.

    The window is the local context the direct-lexical approach is defined to read,
    so V1 measures that assumption rather than starving it.
    """
    tokens = mapping_input.template.split()
    placeholders = {slot.placeholder for slot in mapping_input.parameter_slots}
    keep: set[int] = set()
    for index, token in enumerate(tokens):
        if not any(placeholder in token for placeholder in placeholders):
            continue
        for offset in range(index - _WINDOW_BEFORE, index + _WINDOW_AFTER + 1):
            if 0 <= offset < len(tokens):
                keep.add(offset)
    if not keep:
        return _WITHHELD_TEXT
    windowed = [
        tokens[index] if index in keep else _GAP
        for index in range(len(tokens))
        if index in keep or (index - 1) in keep
    ]
    return " ".join(windowed)


def _unlabelled_slot(slot: ParameterSlot) -> ParameterSlot:
    return slot.model_copy(update={"label": _WITHHELD_TEXT})


def _value_only_events(mapping_input: SemanticMappingInput) -> list[SourceEvent]:
    """Reduce each event to its slot example values, discarding surrounding text."""
    values = [
        example
        for slot in mapping_input.parameter_slots
        for example in slot.examples[:1]
        if example.strip()
    ]
    text = " ".join(values) if values else _WITHHELD_TEXT
    first = mapping_input.representative_events[0]
    return [first.model_copy(update={"text": text})]
