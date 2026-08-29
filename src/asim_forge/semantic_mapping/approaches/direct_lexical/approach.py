"""Direct lexical slot-to-ASIM baseline."""

from __future__ import annotations

from ....models import AsimCatalog
from ...contracts import (
    ApproachIdentity,
    MappingRequest,
    PredictedAsimField,
    SemanticMappingPrediction,
)
from .._lexical import rank_fields, rank_schemas, slot_context


class DirectLexicalApproach:
    """Rank ASIM fields directly from local slot context."""

    identity = ApproachIdentity(name="direct-lexical", version="1")

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

        schema_name = schemas[0].schema_name
        fields = catalog.fields_for_schema(schema_name)
        predictions: list[PredictedAsimField] = []
        for slot in request.input.parameter_slots:
            context = slot_context(request.input, slot)
            candidates = rank_fields(fields, context)
            if not candidates:
                continue
            predictions.append(
                PredictedAsimField(
                    source_kind="slot",
                    locator=slot.slot_id,
                    asim_field=candidates[0].asim_field,
                    score=candidates[0].score,
                    ranked_candidates=candidates,
                    evidence=[f"local slot context: {context}"],
                )
            )

        disposition = "mapped" if predictions else "unresolved"
        warnings = [] if predictions else ["No slot-to-field candidate had lexical overlap."]
        return SemanticMappingPrediction(
            case_id=request.case_id,
            catalogue_revision=request.catalogue_revision,
            approach=self.identity,
            disposition=disposition,
            ranked_schemas=schemas,
            asim_fields=predictions,
            warnings=warnings,
        )
