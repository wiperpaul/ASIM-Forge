"""Shared semantic mapping vocabulary independent of evaluation and providers."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator, model_validator

from ..models import ParameterSlot, SourceEvent, StrictModel


def _strip_non_blank(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value cannot be blank")
    return value


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")]
AsimName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
NonBlankText = Annotated[str, AfterValidator(_strip_non_blank)]
Locator = NonBlankText
SemanticRole = NonBlankText
SourceKind = Literal["slot", "template_constant", "derived"]
MappingDisposition = Literal["mapped", "unresolved", "not_applicable"]


class SemanticSourceMetadata(StrictModel):
    """Source context available to every semantic mapping approach."""

    system: str = Field(min_length=1)
    vendor: str | None = None
    product: str | None = None
    source_table: AsimName | None = None
    message_field: AsimName | None = None

    @field_validator("system", "vendor", "product")
    @classmethod
    def values_cannot_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value cannot be blank")
        return value


class SemanticMappingInput(StrictModel):
    """Self-contained input shown to a semantic mapping approach."""

    cluster_id: Identifier
    template: str = Field(min_length=1)
    representative_events: list[SourceEvent] = Field(min_length=1)
    parameter_slots: list[ParameterSlot] = Field(default_factory=list)
    source_metadata: SemanticSourceMetadata

    @model_validator(mode="after")
    def slot_ids_must_be_unique(self) -> SemanticMappingInput:
        slot_ids = [slot.slot_id for slot in self.parameter_slots]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("parameter slot IDs must be unique")
        return self
