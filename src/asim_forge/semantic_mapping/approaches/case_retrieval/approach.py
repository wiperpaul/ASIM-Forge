"""Case-retrieval baseline over previously labelled mapping cases."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ....models import AsimCatalog, ParameterSlot
from ....source_normalization import contains_source_phrase
from ...contracts import (
    ApproachIdentity,
    MappingRequest,
    PredictedAsimField,
    PredictedSourceSemantic,
    RankedSchemaCandidate,
    SemanticMappingPrediction,
)
from .._lexical import slot_context
from .matching import similarity, weighted_candidates

if TYPE_CHECKING:
    from ....evaluation import SemanticMappingCase, SourceSemanticLabel


class CaseRetrievalApproach:
    """Transfer labels from similar approved cases without training a model."""

    identity = ApproachIdentity(name="case-retrieval", version="2")

    def __init__(
        self,
        reference_cases: Sequence[SemanticMappingCase],
        *,
        neighbors: int = 3,
    ) -> None:
        if neighbors < 1:
            raise ValueError("neighbors must be at least one")
        self.reference_cases = tuple(
            case for case in reference_cases if case.expected.disposition == "mapped"
        )
        self.neighbors = neighbors

    def predict(
        self,
        request: MappingRequest,
        catalog: AsimCatalog,
    ) -> SemanticMappingPrediction:
        references = self._rank_references(request)[: self.neighbors]
        if not references:
            return SemanticMappingPrediction(
                case_id=request.case_id,
                catalogue_revision=request.catalogue_revision,
                approach=self.identity,
                disposition="unresolved",
                warnings=["No labelled reference case had lexical overlap."],
            )

        schema_scores: defaultdict[str, float] = defaultdict(float)
        for case, score in references:
            if case.expected.schema_name in catalog.manifest.schemas:
                schema_scores[case.expected.schema_name] += score
        if not schema_scores:
            return SemanticMappingPrediction(
                case_id=request.case_id,
                catalogue_revision=request.catalogue_revision,
                approach=self.identity,
                disposition="unresolved",
                warnings=["Reference schemas are absent from the pinned catalogue."],
            )

        maximum_schema_score = max(schema_scores.values())
        ranked_schemas = [
            RankedSchemaCandidate(
                schema_name=name,
                score=round(score / maximum_schema_score, 6),
                evidence=["weighted vote from similar labelled cases"],
            )
            for name, score in sorted(
                schema_scores.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
        selected_schema = ranked_schemas[0].schema_name
        valid_fields = {field.name for field in catalog.fields_for_schema(selected_schema)}

        semantics: list[PredictedSourceSemantic] = []
        mappings: list[PredictedAsimField] = []
        for slot in request.input.parameter_slots:
            transfer = self._best_slot_transfer(request, slot, references, selected_schema)
            if transfer is None:
                continue
            semantic, role_score, field_scores, constant_values, reference_ids = transfer
            semantics.append(
                PredictedSourceSemantic(
                    source_kind="slot",
                    locator=slot.slot_id,
                    role=semantic.role,
                    score=round(role_score, 6),
                    evidence=[f"retrieved cases: {', '.join(reference_ids)}"],
                )
            )
            candidates = weighted_candidates(
                {name: score for name, score in field_scores.items() if name in valid_fields}
            )
            if not candidates:
                continue
            selected_field = candidates[0].asim_field
            mappings.append(
                PredictedAsimField(
                    source_kind="slot",
                    locator=slot.slot_id,
                    asim_field=selected_field,
                    constant_value=constant_values.get(selected_field),
                    score=candidates[0].score,
                    ranked_candidates=candidates,
                    evidence=[f"retrieved cases: {', '.join(reference_ids)}"],
                )
            )

        self._transfer_template_constants(
            request,
            references,
            selected_schema,
            valid_fields,
            semantics,
            mappings,
        )
        disposition = "mapped" if mappings else "unresolved"
        warnings = [] if mappings else ["Retrieved labels could not be transferred to this input."]
        return SemanticMappingPrediction(
            case_id=request.case_id,
            catalogue_revision=request.catalogue_revision,
            approach=self.identity,
            disposition=disposition,
            ranked_schemas=ranked_schemas,
            source_semantics=semantics,
            asim_fields=mappings,
            warnings=warnings,
        )

    def _rank_references(
        self,
        request: MappingRequest,
    ) -> list[tuple[SemanticMappingCase, float]]:
        target = _input_signature(request)
        ranked = [
            (case, similarity(target, _case_signature(case)))
            for case in self.reference_cases
            if case.case_id != request.case_id
            and case.catalogue_revision == request.catalogue_revision
        ]
        return sorted(
            (item for item in ranked if item[1] > 0),
            key=lambda item: (-item[1], item[0].case_id),
        )

    def _best_slot_transfer(
        self,
        request: MappingRequest,
        target_slot: ParameterSlot,
        references: list[tuple[SemanticMappingCase, float]],
        selected_schema: str,
    ) -> (
        tuple[
            SourceSemanticLabel,
            float,
            dict[str, float],
            dict[str, str | int | float | bool | None],
            list[str],
        ]
        | None
    ):
        target_context = slot_context(request.input, target_slot)
        candidates: list[tuple[float, SemanticMappingCase, SourceSemanticLabel]] = []
        for case, case_score in references:
            if case.expected.schema_name != selected_schema:
                continue
            slots = {slot.slot_id: slot for slot in case.input.parameter_slots}
            for semantic in case.expected.source_semantics:
                if semantic.source_kind != "slot" or semantic.locator not in slots:
                    continue
                reference_context = slot_context(case.input, slots[semantic.locator])
                transfer_score = case_score * similarity(target_context, reference_context)
                if transfer_score > 0:
                    candidates.append((transfer_score, case, semantic))
        if not candidates:
            return None

        candidates.sort(key=lambda item: (-item[0], item[1].case_id, item[2].semantic_id))
        best_score, _, best_semantic = candidates[0]
        field_scores: defaultdict[str, float] = defaultdict(float)
        constant_values: dict[str, str | int | float | bool | None] = {}
        reference_ids: list[str] = []
        for score, case, semantic in candidates:
            if semantic.role != best_semantic.role:
                continue
            reference_ids.append(case.case_id)
            for field in case.expected.asim_fields:
                if field.semantic_id == semantic.semantic_id:
                    field_scores[field.asim_field] += score
                    constant_values.setdefault(field.asim_field, field.constant_value)
        return (
            best_semantic,
            min(best_score, 1.0),
            dict(field_scores),
            constant_values,
            sorted(set(reference_ids)),
        )

    def _transfer_template_constants(
        self,
        request: MappingRequest,
        references: list[tuple[SemanticMappingCase, float]],
        selected_schema: str,
        valid_fields: set[str],
        semantics: list[PredictedSourceSemantic],
        mappings: list[PredictedAsimField],
    ) -> None:
        semantic_keys = {
            (semantic.source_kind, semantic.locator.casefold(), semantic.role.casefold())
            for semantic in semantics
        }
        mapping_keys = {
            (mapping.source_kind, mapping.locator.casefold(), mapping.asim_field)
            for mapping in mappings
        }
        for case, case_score in references:
            if case.expected.schema_name != selected_schema:
                continue
            for semantic in case.expected.source_semantics:
                if semantic.source_kind != "template_constant":
                    continue
                if not contains_source_phrase(request.input.template, semantic.locator):
                    continue
                semantic_key = (
                    "template_constant",
                    semantic.locator.casefold(),
                    semantic.role.casefold(),
                )
                if semantic_key not in semantic_keys:
                    semantics.append(
                        PredictedSourceSemantic(
                            source_kind="template_constant",
                            locator=semantic.locator.casefold(),
                            role=semantic.role,
                            score=round(case_score, 6),
                            evidence=[f"retrieved case: {case.case_id}"],
                        )
                    )
                    semantic_keys.add(semantic_key)
                for expected_field in case.expected.asim_fields:
                    if (
                        expected_field.semantic_id != semantic.semantic_id
                        or expected_field.asim_field not in valid_fields
                    ):
                        continue
                    mapping_key = (
                        "template_constant",
                        semantic.locator.casefold(),
                        expected_field.asim_field,
                    )
                    if mapping_key in mapping_keys:
                        continue
                    candidate = weighted_candidates({expected_field.asim_field: case_score})
                    mappings.append(
                        PredictedAsimField(
                            source_kind="template_constant",
                            locator=semantic.locator.casefold(),
                            asim_field=expected_field.asim_field,
                            constant_value=expected_field.constant_value,
                            score=candidate[0].score,
                            ranked_candidates=candidate,
                            evidence=[f"retrieved case: {case.case_id}"],
                        )
                    )
                    mapping_keys.add(mapping_key)


def _input_signature(request: MappingRequest) -> str:
    metadata = request.input.source_metadata
    return "\n".join(
        [
            request.input.template,
            metadata.system,
            metadata.vendor or "",
            metadata.product or "",
            *(slot.label for slot in request.input.parameter_slots),
        ]
    )


def _case_signature(case: SemanticMappingCase) -> str:
    return _input_signature(
        MappingRequest(
            case_id=case.case_id,
            catalogue_revision=case.catalogue_revision,
            input=case.input,
        )
    )
