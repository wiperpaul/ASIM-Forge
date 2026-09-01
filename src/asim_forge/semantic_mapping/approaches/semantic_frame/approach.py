"""Two-stage source-semantic-frame baseline."""

from __future__ import annotations

from ....models import AsimCatalog, ParameterSlot
from ....source_semantics import contains_source_phrase, source_tokens
from ...contracts import (
    ApproachIdentity,
    MappingRequest,
    PredictedAsimField,
    PredictedSourceSemantic,
    SemanticMappingPrediction,
)
from ...field_ranking import rank_fields
from ...schema_candidates import rank_schemas
from ...source_context import slot_context
from ...types import SemanticMappingInput

_STATIC_SEMANTICS = (
    ("connection allowed", "network.connection.allowed", "event result", "Success"),
    ("connection denied", "network.connection.denied", "event result", "Failure"),
    ("login failed", "authentication.login.failed", "event result", "Failure"),
    ("login succeeded", "authentication.login.succeeded", "event result", "Success"),
)


class SemanticFrameApproach:
    """Infer source roles first, then project those roles into ASIM."""

    identity = ApproachIdentity(name="semantic-frame", version="3")

    def predict(
        self,
        request: MappingRequest,
        catalog: AsimCatalog,
    ) -> SemanticMappingPrediction:
        schemas = rank_schemas(request.input, catalog)
        if not schemas:
            return SemanticMappingPrediction(
                case_id=request.case_id,
                catalogue_revision=request.catalogue_revision,
                approach=self.identity,
                disposition="unresolved",
                warnings=["No schema had lexical evidence."],
            )

        fields = catalog.fields_for_schema(schemas[0].schema_name)
        semantics: list[PredictedSourceSemantic] = []
        mappings: list[PredictedAsimField] = []
        for slot in request.input.parameter_slots:
            context = slot_context(request.input, slot)
            role = _infer_slot_role(request.input, slot, context)
            if role is None:
                continue
            semantics.append(
                PredictedSourceSemantic(
                    source_kind="slot",
                    locator=slot.slot_id,
                    role=role,
                    score=1.0,
                    evidence=[f"normalized slot context: {context}"],
                )
            )
            candidates = rank_fields(fields, f"{role} {slot.label}")
            if candidates:
                mappings.append(
                    PredictedAsimField(
                        source_kind="slot",
                        locator=slot.slot_id,
                        asim_field=candidates[0].asim_field,
                        score=candidates[0].score,
                        ranked_candidates=candidates,
                        evidence=[f"source role: {role}"],
                    )
                )

        for phrase, role, target_query, constant_value in _STATIC_SEMANTICS:
            if not contains_source_phrase(request.input.template, phrase):
                continue
            semantics.append(
                PredictedSourceSemantic(
                    source_kind="template_constant",
                    locator=phrase,
                    role=role,
                    score=1.0,
                    evidence=[f"template constant: {phrase}"],
                )
            )
            candidates = rank_fields(fields, target_query)
            if candidates:
                mappings.append(
                    PredictedAsimField(
                        source_kind="template_constant",
                        locator=phrase,
                        asim_field=candidates[0].asim_field,
                        constant_value=constant_value,
                        score=candidates[0].score,
                        ranked_candidates=candidates,
                        evidence=[f"source role: {role}"],
                    )
                )

        disposition = "mapped" if mappings else "unresolved"
        warnings = [] if mappings else ["Source roles did not project to catalogue fields."]
        return SemanticMappingPrediction(
            case_id=request.case_id,
            catalogue_revision=request.catalogue_revision,
            approach=self.identity,
            disposition=disposition,
            ranked_schemas=schemas,
            source_semantics=semantics,
            asim_fields=mappings,
            warnings=warnings,
        )


def _infer_slot_role(
    mapping_input: SemanticMappingInput,
    slot: ParameterSlot,
    context: str,
) -> str | None:
    terms = source_tokens(context)
    label_terms = source_tokens(slot.label)
    is_address = "ip" in label_terms or "address" in label_terms
    if "port" in terms:
        if "source" in terms:
            return "network.source.port"
        if "destination" in terms:
            return "network.destination.port"
        return None
    if is_address and "source" in terms:
        return "network.source.address"
    if is_address and "destination" in terms:
        return "network.destination.address"
    if "user" in terms:
        if source_tokens(mapping_input.template) & {"login", "logon", "authentication"}:
            return "authentication.target.user"
        return "event.actor.user"
    return None
