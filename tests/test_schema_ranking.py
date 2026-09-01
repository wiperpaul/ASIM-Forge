import pytest

from asim_forge.clustering import DeepParseClusterer
from asim_forge.models import ClusterRecord, ParsedCluster, SourceEvent
from asim_forge.schema_ranking import (
    DEFAULT_SCHEMA_NAMES,
    SchemaRankingRequest,
    SourceConceptSchemaRanker,
    rank_clusters,
)
from asim_forge.semantic_mapping.approaches._lexical import rank_fields as legacy_rank_fields
from asim_forge.semantic_mapping.field_ranking import rank_fields
from asim_forge.suggestions import suggest_schema


def _request(template: str) -> SchemaRankingRequest:
    return SchemaRankingRequest(
        request_id="cluster-test",
        template=template,
        candidate_schemas=list(DEFAULT_SCHEMA_NAMES),
    )


def test_source_concept_ranking_exposes_selection_evidence_and_confidence() -> None:
    prediction = SourceConceptSchemaRanker().rank(
        _request("CEF:0|Vendor|Product|userAuthenticate|cat=AuthActivityAuditEvent")
    )

    assert prediction.disposition == "ranked"
    assert prediction.selected_schema == "Authentication"
    assert prediction.confidence == prediction.ranked_schemas[0].confidence
    assert {item.concept for item in prediction.ranked_schemas[0].evidence} == {
        "auth",
        "authentication",
    }
    assert prediction.abstention is None


@pytest.mark.parametrize(
    ("template", "reason"),
    [
        ("temperature reading", "no_evidence"),
        ("authentication audit", "tied_top"),
    ],
)
def test_source_concept_ranking_has_explicit_abstention(
    template: str,
    reason: str,
) -> None:
    prediction = SourceConceptSchemaRanker().rank(_request(template))

    assert prediction.disposition == "abstained"
    assert prediction.selected_schema is None
    assert prediction.confidence == 0
    assert prediction.abstention is not None
    assert prediction.abstention.reason == reason


def test_schema_ranking_request_rejects_duplicate_candidates() -> None:
    with pytest.raises(ValueError, match="candidate schemas must be unique"):
        SchemaRankingRequest(
            request_id="cluster-test",
            template="login",
            candidate_schemas=["Authentication", "Authentication"],
        )


def test_deepparse_returns_unranked_clusters_and_orchestration_enriches_them() -> None:
    events = [
        SourceEvent(source_file="test.log", line_number=1, text="user login alice"),
        SourceEvent(source_file="test.log", line_number=2, text="user login bob"),
    ]

    clustering = DeepParseClusterer(system="test").cluster(events)
    parsed = clustering.clusters[0]
    ranking = rank_clusters(clustering.clusters)

    assert isinstance(parsed, ParsedCluster)
    assert not hasattr(parsed, "schema_suggestion")
    assert ranking.clusters[0].schema_suggestion.schema_name == "Authentication"
    assert ranking.predictions[0].request_id == parsed.cluster_id


def test_legacy_suggestion_import_and_cluster_artifact_remain_readable() -> None:
    suggestion = suggest_schema("user login succeeded")
    artifact = {
        "cluster_id": "cluster-legacy",
        "engine_cluster_id": 1,
        "template": "user login <VAR:TEXT>",
        "event_count": 1,
        "representative_events": [
            {"source_file": "legacy.log", "line_number": 1, "text": "user login alice"}
        ],
        "parameter_slots": [],
        "schema_suggestion": {
            "schema_name": "Authentication",
            "confidence": 1.0,
            "ranked_scores": [{"schema_name": "Authentication", "score": 1, "evidence": ["login"]}],
        },
    }

    loaded = ClusterRecord.model_validate(artifact)

    assert suggestion.schema_name == "Authentication"
    assert loaded.schema_suggestion.method == "keyword-baseline"
    assert legacy_rank_fields is rank_fields
