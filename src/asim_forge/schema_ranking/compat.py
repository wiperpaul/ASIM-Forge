"""Adapters that preserve the original cluster suggestion artifact contract."""

from __future__ import annotations

from ..models import SchemaSuggestion
from .approaches import DEFAULT_SCHEMA_NAMES, SourceConceptSchemaRanker
from .contracts import SchemaRankingPrediction, SchemaRankingRequest


def suggest_schema(template: str) -> SchemaSuggestion:
    """Compatibility entry point for the former ``asim_forge.suggestions`` module."""

    prediction = SourceConceptSchemaRanker().rank(
        SchemaRankingRequest(
            request_id="legacy-template",
            template=template,
            candidate_schemas=list(DEFAULT_SCHEMA_NAMES),
        )
    )
    return prediction_to_legacy_suggestion(prediction)


def prediction_to_legacy_suggestion(prediction: SchemaRankingPrediction) -> SchemaSuggestion:
    return SchemaSuggestion.model_validate(
        {
            "schema_name": prediction.selected_schema or "NoFit",
            "confidence": prediction.confidence,
            "ranked_scores": [
                {
                    "schema_name": candidate.schema_name,
                    "score": candidate.score,
                    "evidence": [item.concept for item in candidate.evidence],
                }
                for candidate in prediction.ranked_schemas
            ],
            "method": "source-concept-v1",
        }
    )
