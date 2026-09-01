"""Adapter from independent schema rankings to semantic-mapping candidates."""

from __future__ import annotations

from ..models import AsimCatalog
from ..schema_ranking import SourceConceptSchemaRanker
from ..schema_ranking.contracts import SchemaRankingRequest
from .contracts import RankedSchemaCandidate
from .types import SemanticMappingInput


def rank_schemas(
    mapping_input: SemanticMappingInput,
    catalog: AsimCatalog,
) -> list[RankedSchemaCandidate]:
    prediction = SourceConceptSchemaRanker().rank(
        SchemaRankingRequest(
            request_id=mapping_input.cluster_id,
            template=mapping_input.template,
            candidate_schemas=catalog.manifest.schemas,
        )
    )
    if prediction.disposition == "abstained":
        return []
    maximum = prediction.ranked_schemas[0].score
    return [
        RankedSchemaCandidate(
            schema_name=candidate.schema_name,
            score=round(candidate.score / maximum, 6),
            evidence=[item.concept for item in candidate.evidence],
        )
        for candidate in prediction.ranked_schemas
        if candidate.score > 0
    ]
