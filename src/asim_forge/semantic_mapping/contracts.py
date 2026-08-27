"""Prediction contracts shared by semantic mapping approaches."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field, model_validator

from ..evaluation import (
    AsimName,
    Identifier,
    MappingDisposition,
    SemanticMappingInput,
    SourceKind,
)
from ..models import AsimCatalog, StrictModel


class MappingRequest(StrictModel):
    """Provider input with no access to expected labels."""

    case_id: Identifier
    catalogue_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    input: SemanticMappingInput


class ApproachIdentity(StrictModel):
    name: Identifier
    version: str = Field(min_length=1)


class RankedSchemaCandidate(StrictModel):
    schema_name: AsimName
    score: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class RankedFieldCandidate(StrictModel):
    asim_field: AsimName
    score: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class PredictedSourceSemantic(StrictModel):
    source_kind: SourceKind
    locator: str = Field(min_length=1)
    role: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class PredictedAsimField(StrictModel):
    source_kind: SourceKind
    locator: str = Field(min_length=1)
    asim_field: AsimName
    constant_value: str | int | float | bool | None = None
    score: float = Field(ge=0, le=1)
    ranked_candidates: list[RankedFieldCandidate] = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def selected_field_must_head_ranking(self) -> PredictedAsimField:
        if self.ranked_candidates[0].asim_field != self.asim_field:
            raise ValueError("selected ASIM field must be the first ranked candidate")
        names = [candidate.asim_field for candidate in self.ranked_candidates]
        if len(names) != len(set(names)):
            raise ValueError("ranked ASIM field candidates must be unique")
        return self


class SemanticMappingPrediction(StrictModel):
    """Provider output stored separately from provider-neutral gold cases."""

    format_version: Literal["1"] = "1"
    case_id: Identifier
    catalogue_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    approach: ApproachIdentity
    disposition: MappingDisposition
    ranked_schemas: list[RankedSchemaCandidate] = Field(default_factory=list)
    source_semantics: list[PredictedSourceSemantic] = Field(default_factory=list)
    asim_fields: list[PredictedAsimField] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def prediction_must_be_consistent(self) -> SemanticMappingPrediction:
        schema_names = [candidate.schema_name for candidate in self.ranked_schemas]
        if len(schema_names) != len(set(schema_names)):
            raise ValueError("ranked schema candidates must be unique")
        if self.disposition == "mapped":
            if not self.ranked_schemas:
                raise ValueError("mapped predictions require a schema candidate")
            if not self.asim_fields:
                raise ValueError("mapped predictions require ASIM fields")
        elif self.disposition == "not_applicable":
            if self.ranked_schemas or self.asim_fields:
                raise ValueError("not_applicable predictions cannot contain ASIM targets")

        semantic_keys = [
            (semantic.source_kind, semantic.locator.casefold(), semantic.role.casefold())
            for semantic in self.source_semantics
        ]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError("predicted source semantics must be unique")
        field_keys = [
            (field.source_kind, field.locator, field.asim_field) for field in self.asim_fields
        ]
        if len(field_keys) != len(set(field_keys)):
            raise ValueError("predicted source and ASIM field combinations must be unique")
        return self


class SemanticMappingApproach(Protocol):
    """Small boundary implemented independently by every approach."""

    identity: ApproachIdentity

    def predict(
        self,
        request: MappingRequest,
        catalog: AsimCatalog,
    ) -> SemanticMappingPrediction: ...
