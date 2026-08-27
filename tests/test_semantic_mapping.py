from pathlib import Path

import pytest

from asim_forge.evaluation import load_semantic_mapping_cases
from asim_forge.semantic_mapping.contracts import (
    MappingRequest,
    SemanticMappingPrediction,
)
from asim_forge.semantic_mapping.metrics import EvaluationError, evaluate_predictions

EXAMPLE_CASES = Path("examples/evaluation/semantic-mapping-cases.jsonl")


def _request() -> MappingRequest:
    case = load_semantic_mapping_cases(EXAMPLE_CASES)[0]
    return MappingRequest(
        case_id=case.case_id,
        catalogue_revision=case.catalogue_revision,
        input=case.input,
    )


def _prediction_payload() -> dict[str, object]:
    request = _request()
    return {
        "case_id": request.case_id,
        "catalogue_revision": request.catalogue_revision,
        "approach": {"name": "example-approach", "version": "1"},
        "disposition": "mapped",
        "ranked_schemas": [
            {"schema_name": "NetworkSession", "score": 1.0},
        ],
        "source_semantics": [
            {
                "source_kind": "slot",
                "locator": "p1",
                "role": "network.source.address",
                "score": 1.0,
            }
        ],
        "asim_fields": [
            {
                "source_kind": "slot",
                "locator": "p1",
                "asim_field": "SrcIpAddr",
                "score": 1.0,
                "ranked_candidates": [
                    {"asim_field": "SrcIpAddr", "score": 1.0},
                    {"asim_field": "SrcMacAddr", "score": 0.5},
                ],
            }
        ],
    }


def test_request_contains_no_expected_labels() -> None:
    request = _request()

    assert "expected" not in request.model_dump()
    assert request.input.cluster_id == "cluster-734d3840beb93179"


def test_prediction_keeps_provider_output_outside_gold_case() -> None:
    prediction = SemanticMappingPrediction.model_validate(_prediction_payload())

    assert prediction.approach.name == "example-approach"
    assert prediction.ranked_schemas[0].schema_name == "NetworkSession"
    assert prediction.asim_fields[0].ranked_candidates[0].asim_field == "SrcIpAddr"


def test_selected_field_must_head_its_candidate_ranking() -> None:
    payload = _prediction_payload()
    fields = payload["asim_fields"]
    assert isinstance(fields, list)
    fields[0]["asim_field"] = "DstIpAddr"

    with pytest.raises(ValueError, match="must be the first ranked candidate"):
        SemanticMappingPrediction.model_validate(payload)


def test_selected_field_score_must_match_first_candidate() -> None:
    payload = _prediction_payload()
    fields = payload["asim_fields"]
    assert isinstance(fields, list)
    fields[0]["score"] = 0.75

    with pytest.raises(ValueError, match="score must match the first ranked candidate"):
        SemanticMappingPrediction.model_validate(payload)


def test_candidate_scores_must_be_descending() -> None:
    payload = _prediction_payload()
    fields = payload["asim_fields"]
    assert isinstance(fields, list)
    fields[0]["score"] = 0.5
    fields[0]["ranked_candidates"][0]["score"] = 0.5
    fields[0]["ranked_candidates"][1]["score"] = 0.75

    with pytest.raises(ValueError, match="field candidate scores must be descending"):
        SemanticMappingPrediction.model_validate(payload)

    payload = _prediction_payload()
    schemas = payload["ranked_schemas"]
    assert isinstance(schemas, list)
    schemas[0]["score"] = 0.5
    schemas.append({"schema_name": "Authentication", "score": 0.75})

    with pytest.raises(ValueError, match="schema candidate scores must be descending"):
        SemanticMappingPrediction.model_validate(payload)


def test_duplicate_source_semantics_are_rejected() -> None:
    payload = _prediction_payload()
    semantics = payload["source_semantics"]
    assert isinstance(semantics, list)
    semantics.append(dict(semantics[0]))

    with pytest.raises(ValueError, match="source semantics must be unique"):
        SemanticMappingPrediction.model_validate(payload)


def test_prediction_locators_are_trimmed_and_compared_case_insensitively() -> None:
    payload = _prediction_payload()
    fields = payload["asim_fields"]
    assert isinstance(fields, list)
    duplicate = dict(fields[0])
    duplicate["locator"] = " P1 "
    fields.append(duplicate)

    with pytest.raises(ValueError, match="field combinations must be unique"):
        SemanticMappingPrediction.model_validate(payload)


def test_prediction_locator_and_role_cannot_be_blank() -> None:
    payload = _prediction_payload()
    semantics = payload["source_semantics"]
    assert isinstance(semantics, list)
    semantics[0]["role"] = "   "

    with pytest.raises(ValueError, match="value cannot be blank"):
        SemanticMappingPrediction.model_validate(payload)


def test_not_applicable_prediction_cannot_contain_targets() -> None:
    payload = _prediction_payload()
    payload["disposition"] = "not_applicable"

    with pytest.raises(ValueError, match="cannot contain ASIM targets"):
        SemanticMappingPrediction.model_validate(payload)


def test_metrics_score_rankings_sets_exactness_and_edits_independently() -> None:
    case = load_semantic_mapping_cases(EXAMPLE_CASES)[0]
    prediction = SemanticMappingPrediction.model_validate(_prediction_payload())

    metrics = evaluate_predictions([case], [prediction])

    assert metrics.schema_top1_accuracy == 1
    assert metrics.schema_mrr == 1
    assert metrics.source_micro_precision == 1
    assert metrics.source_micro_recall == 0.25
    assert metrics.source_micro_f1 == 0.4
    assert metrics.field_micro_precision == 1
    assert metrics.field_micro_recall == 0.25
    assert metrics.field_mrr == 0.25
    assert metrics.field_recall_at_gold == 0.25
    assert metrics.mapping_exact_match == 0
    assert metrics.mean_mapping_edits == 3


def test_metrics_require_predictions_for_the_exact_case_set() -> None:
    case = load_semantic_mapping_cases(EXAMPLE_CASES)[0]
    payload = _prediction_payload()
    payload["case_id"] = "different-case"
    prediction = SemanticMappingPrediction.model_validate(payload)

    with pytest.raises(EvaluationError, match="cover exactly"):
        evaluate_predictions([case], [prediction])
