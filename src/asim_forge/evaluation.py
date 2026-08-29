"""Provider-neutral fixtures for evaluating semantic mapping approaches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from .models import StrictModel
from .semantic_mapping.types import (
    AsimName,
    Identifier,
    Locator,
    MappingDisposition,
    SemanticMappingInput,
    SemanticRole,
    SemanticSourceMetadata,
    SourceKind,
)

EvidenceKind = Literal[
    "template",
    "representative_event",
    "source_metadata",
    "catalogue",
    "review",
]
LabelSource = Literal["human_review", "adjudicated", "synthetic", "imported"]

# Keep the original public name available to existing evaluation fixture users.
EvaluationSourceMetadata = SemanticSourceMetadata


class EvaluationError(ValueError):
    """Raised when an evaluation fixture cannot be trusted."""


class EvaluationEvidence(StrictModel):
    """A traceable reason for a human-authored expected label."""

    kind: EvidenceKind
    reference: str = Field(min_length=1)
    rationale: str = ""


class SourceSemanticLabel(StrictModel):
    """Meaning assigned in source terms before projection into ASIM."""

    semantic_id: Identifier
    source_kind: SourceKind
    locator: Locator
    role: SemanticRole
    evidence: list[EvaluationEvidence] = Field(min_length=1)


class ExpectedAsimField(StrictModel):
    """Expected projection of one source semantic label into an ASIM field."""

    semantic_id: Identifier
    asim_field: AsimName
    constant_value: str | int | float | bool | None = None
    evidence: list[EvaluationEvidence] = Field(min_length=1)


class ExpectedSemanticMapping(StrictModel):
    """Human-labelled outcome, independent of how a provider predicts it."""

    disposition: MappingDisposition
    schema_name: AsimName | None = None
    source_semantics: list[SourceSemanticLabel] = Field(default_factory=list)
    asim_fields: list[ExpectedAsimField] = Field(default_factory=list)
    unresolved_reasons: list[str] = Field(default_factory=list)

    @field_validator("unresolved_reasons")
    @classmethod
    def unresolved_reasons_cannot_be_blank(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("unresolved reasons cannot be blank")
        return values

    @model_validator(mode="after")
    def disposition_must_match_expected_output(self) -> ExpectedSemanticMapping:
        if self.disposition == "mapped":
            if self.schema_name is None:
                raise ValueError("mapped cases require schema_name")
            if not self.source_semantics:
                raise ValueError("mapped cases require source_semantics")
            if not self.asim_fields:
                raise ValueError("mapped cases require asim_fields")
            if self.unresolved_reasons:
                raise ValueError("mapped cases cannot have unresolved_reasons")
        elif self.disposition == "unresolved":
            if not self.unresolved_reasons:
                raise ValueError("unresolved cases require unresolved_reasons")
        else:
            if self.schema_name is not None or self.asim_fields:
                raise ValueError("not_applicable cases cannot have ASIM targets")
            if self.unresolved_reasons:
                raise ValueError("not_applicable cases cannot have unresolved_reasons")
        return self


class EvaluationProvenance(StrictModel):
    """Origin of the expected labels without coupling them to a provider."""

    label_source: LabelSource
    decision_refs: list[str] = Field(default_factory=list)
    annotator_refs: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("decision_refs", "annotator_refs")
    @classmethod
    def references_cannot_be_blank(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("provenance references cannot be blank")
        return values


class SemanticMappingCase(StrictModel):
    """Versioned, self-contained gold case shared by all evaluated approaches."""

    format_version: Literal["1"] = "1"
    case_id: Identifier
    catalogue_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    input: SemanticMappingInput
    expected: ExpectedSemanticMapping
    provenance: EvaluationProvenance

    @model_validator(mode="after")
    def references_must_resolve(self) -> SemanticMappingCase:
        semantics = self.expected.source_semantics
        semantic_ids = [semantic.semantic_id for semantic in semantics]
        if len(semantic_ids) != len(set(semantic_ids)):
            raise ValueError("semantic IDs must be unique")

        known_semantic_ids = set(semantic_ids)
        unknown_ids = sorted(
            {
                field.semantic_id
                for field in self.expected.asim_fields
                if field.semantic_id not in known_semantic_ids
            }
        )
        if unknown_ids:
            raise ValueError(f"ASIM fields reference unknown semantic IDs: {unknown_ids}")

        field_pairs = [(field.semantic_id, field.asim_field) for field in self.expected.asim_fields]
        if len(field_pairs) != len(set(field_pairs)):
            raise ValueError("semantic ID and ASIM field pairs must be unique")

        slot_ids = {slot.slot_id for slot in self.input.parameter_slots}
        for semantic in semantics:
            if semantic.source_kind == "slot" and semantic.locator not in slot_ids:
                raise ValueError(
                    f"slot semantic {semantic.semantic_id!r} references unknown slot "
                    f"{semantic.locator!r}"
                )
            if (
                semantic.source_kind == "template_constant"
                and semantic.locator.casefold() not in self.input.template.casefold()
            ):
                raise ValueError(
                    f"template constant {semantic.semantic_id!r} is absent from the template"
                )
        return self


def load_semantic_mapping_cases(path: Path) -> list[SemanticMappingCase]:
    """Load and validate canonical JSONL semantic mapping cases."""
    if not path.is_file():
        raise EvaluationError(f"Evaluation fixture does not exist: {path}")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeError as error:
        raise EvaluationError(f"Evaluation fixture is not valid UTF-8: {path}") from error

    cases: list[SemanticMappingCase] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            cases.append(SemanticMappingCase.model_validate_json(line))
        except (ValidationError, ValueError) as error:
            raise EvaluationError(
                f"Invalid semantic mapping case on line {line_number} of {path}: {error}"
            ) from error

    if not cases:
        raise EvaluationError(f"No semantic mapping cases found in {path}")
    _ensure_unique_case_ids(cases)
    return cases


def write_semantic_mapping_cases(path: Path, cases: list[SemanticMappingCase]) -> None:
    """Write deterministic canonical JSONL without provider-specific results."""
    if not cases:
        raise EvaluationError("At least one semantic mapping case is required")
    _ensure_unique_case_ids(cases)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(case.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
        for case in cases
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _ensure_unique_case_ids(cases: list[SemanticMappingCase]) -> None:
    case_ids = [case.case_id for case in cases]
    duplicates = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
    if duplicates:
        raise EvaluationError(f"Evaluation case IDs must be unique: {duplicates}")
