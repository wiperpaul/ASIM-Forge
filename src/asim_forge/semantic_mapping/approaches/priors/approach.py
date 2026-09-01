"""Priors that use label frequency alone, with no evidence from the source event.

These exist so that a reported score can be read against class imbalance rather
than against zero. They are registered approaches because they must be measured by
the same metric engine, not because they are candidate mappers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ....models import AsimCatalog
from ...contracts import (
    ApproachIdentity,
    MappingRequest,
    PredictedAsimField,
    RankedFieldCandidate,
    RankedSchemaCandidate,
    SemanticMappingPrediction,
)

if TYPE_CHECKING:
    from ....evaluation import SemanticMappingCase

_CANDIDATE_LIMIT = 5


class NullPriorApproach:
    """Predict nothing. The absolute floor for every other reported score."""

    identity = ApproachIdentity(name="null-prior", version="1")

    def __init__(self, reference_cases: Sequence[SemanticMappingCase] = ()) -> None:
        del reference_cases

    def predict(
        self,
        request: MappingRequest,
        catalog: AsimCatalog,
    ) -> SemanticMappingPrediction:
        del catalog
        return SemanticMappingPrediction(
            case_id=request.case_id,
            catalogue_revision=request.catalogue_revision,
            approach=self.identity,
            disposition="unresolved",
            warnings=["Null prior: floor reference, not a mapping method."],
        )


class MajoritySchemaPriorApproach:
    """Rank schemas by labelled frequency alone, and map no fields."""

    identity = ApproachIdentity(name="majority-schema-prior", version="1")

    def __init__(self, reference_cases: Sequence[SemanticMappingCase] = ()) -> None:
        self.reference_cases = _mapped_references(reference_cases)

    def predict(
        self,
        request: MappingRequest,
        catalog: AsimCatalog,
    ) -> SemanticMappingPrediction:
        references = _eligible_references(self.reference_cases, request)
        ranked_schemas = _schema_frequency_ranking(references, catalog, request.schema_hint)
        warnings = (
            ["Schema frequency prior: isolates the schema floor and maps no fields."]
            if ranked_schemas
            else ["No labelled reference case supplied a schema frequency."]
        )
        return SemanticMappingPrediction(
            case_id=request.case_id,
            catalogue_revision=request.catalogue_revision,
            approach=self.identity,
            disposition="unresolved",
            ranked_schemas=ranked_schemas,
            warnings=warnings,
        )


class FieldFrequencyPriorApproach:
    """Assign the most frequently labelled field of the majority schema to every slot."""

    identity = ApproachIdentity(name="field-frequency-prior", version="1")

    def __init__(self, reference_cases: Sequence[SemanticMappingCase] = ()) -> None:
        self.reference_cases = _mapped_references(reference_cases)

    def predict(
        self,
        request: MappingRequest,
        catalog: AsimCatalog,
    ) -> SemanticMappingPrediction:
        references = _eligible_references(self.reference_cases, request)
        ranked_schemas = _schema_frequency_ranking(references, catalog, request.schema_hint)
        if not ranked_schemas:
            return SemanticMappingPrediction(
                case_id=request.case_id,
                catalogue_revision=request.catalogue_revision,
                approach=self.identity,
                disposition="unresolved",
                warnings=["No labelled reference case supplied a schema frequency."],
            )

        selected_schema = ranked_schemas[0].schema_name
        valid_fields = {field.name for field in catalog.fields_for_schema(selected_schema)}
        counts = Counter(
            field.asim_field
            for case in references
            for field in case.expected.asim_fields
            if field.asim_field in valid_fields
        )
        candidates = _frequency_candidates(counts, "labelled field frequency")
        if not candidates or not request.input.parameter_slots:
            return SemanticMappingPrediction(
                case_id=request.case_id,
                catalogue_revision=request.catalogue_revision,
                approach=self.identity,
                disposition="unresolved",
                ranked_schemas=ranked_schemas,
                warnings=["No catalogue field had a labelled reference frequency."],
            )

        considered = len(valid_fields)
        mappings = [
            PredictedAsimField(
                source_kind="slot",
                locator=slot.slot_id,
                asim_field=candidates[0].asim_field,
                score=candidates[0].score,
                ranked_candidates=candidates,
                candidate_pool_size=len(counts),
                considered_field_count=considered,
                evidence=["labelled field frequency; no source evidence used"],
            )
            for slot in request.input.parameter_slots
        ]
        return SemanticMappingPrediction(
            case_id=request.case_id,
            catalogue_revision=request.catalogue_revision,
            approach=self.identity,
            disposition="mapped",
            ranked_schemas=ranked_schemas,
            asim_fields=mappings,
            warnings=["Field frequency prior: floor reference, not a mapping method."],
        )


def _mapped_references(
    reference_cases: Sequence[SemanticMappingCase],
) -> tuple[SemanticMappingCase, ...]:
    return tuple(case for case in reference_cases if case.expected.disposition == "mapped")


def _eligible_references(
    reference_cases: Sequence[SemanticMappingCase],
    request: MappingRequest,
) -> list[SemanticMappingCase]:
    """Apply the same leave-one-out discipline the retrieval approach uses."""
    return [
        case
        for case in reference_cases
        if case.case_id != request.case_id and case.catalogue_revision == request.catalogue_revision
    ]


def _schema_frequency_ranking(
    references: Sequence[SemanticMappingCase],
    catalog: AsimCatalog,
    schema_hint: str | None,
) -> list[RankedSchemaCandidate]:
    if schema_hint is not None:
        if schema_hint not in catalog.manifest.schemas:
            raise ValueError(f"Schema oracle hint is absent from the catalogue: {schema_hint}")
        return [
            RankedSchemaCandidate(
                schema_name=schema_hint,
                score=1.0,
                evidence=["harness schema oracle"],
            )
        ]
    counts = Counter(
        case.expected.schema_name
        for case in references
        if case.expected.schema_name in catalog.manifest.schemas
    )
    if not counts:
        return []
    maximum = max(counts.values())
    return [
        RankedSchemaCandidate(
            schema_name=name,
            score=round(count / maximum, 6),
            evidence=["labelled schema frequency"],
        )
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _frequency_candidates(counts: Counter[str], evidence: str) -> list[RankedFieldCandidate]:
    if not counts:
        return []
    maximum = max(counts.values())
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ties = Counter(count for _, count in ordered)
    return [
        RankedFieldCandidate(
            asim_field=name,
            score=round(count / maximum, 6),
            tied_with=ties[count] - 1,
            evidence=[evidence],
        )
        for name, count in ordered[:_CANDIDATE_LIMIT]
    ]
