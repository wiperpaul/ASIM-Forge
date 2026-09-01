"""Orchestration for ranking parsed clusters without coupling the parser to schemas."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..models import ClusterRecord, ParsedCluster
from .approaches import DEFAULT_SCHEMA_NAMES, SourceConceptSchemaRanker
from .compat import prediction_to_legacy_suggestion
from .contracts import SchemaRankingApproach, SchemaRankingPrediction, SchemaRankingRequest


@dataclass(frozen=True)
class SchemaRankedClusters:
    clusters: list[ClusterRecord]
    predictions: list[SchemaRankingPrediction]


def rank_clusters(
    clusters: Sequence[ParsedCluster],
    *,
    candidate_schemas: Sequence[str] = DEFAULT_SCHEMA_NAMES,
    approach: SchemaRankingApproach | None = None,
) -> SchemaRankedClusters:
    ranker = approach or SourceConceptSchemaRanker()
    ranked_clusters: list[ClusterRecord] = []
    predictions: list[SchemaRankingPrediction] = []
    for cluster in clusters:
        prediction = ranker.rank(
            SchemaRankingRequest(
                request_id=cluster.cluster_id,
                template=cluster.template,
                candidate_schemas=list(candidate_schemas),
            )
        )
        predictions.append(prediction)
        ranked_clusters.append(
            ClusterRecord.model_validate(
                {
                    **cluster.model_dump(exclude={"schema_suggestion"}),
                    "schema_suggestion": prediction_to_legacy_suggestion(prediction),
                }
            )
        )
    return SchemaRankedClusters(clusters=ranked_clusters, predictions=predictions)
