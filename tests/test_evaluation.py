import json
from pathlib import Path

import pytest

from asim_forge.cli import main
from asim_forge.evaluation import (
    EvaluationError,
    SemanticMappingCase,
    load_semantic_mapping_cases,
    write_semantic_mapping_cases,
)

EXAMPLE_CASES = Path("examples/evaluation/semantic-mapping-cases.jsonl")


def _case_payload() -> dict[str, object]:
    return {
        "case_id": "test.network.allowed",
        "catalogue_revision": "0123456789abcdef0123456789abcdef01234567",
        "input": {
            "cluster_id": "cluster-test",
            "template": "connection allowed from <VAR:IPV4>",
            "representative_events": [
                {
                    "source_file": "security.log",
                    "line_number": 1,
                    "text": "connection allowed from 10.0.0.1",
                }
            ],
            "parameter_slots": [
                {
                    "slot_id": "p1",
                    "label": "IPV4",
                    "placeholder": "<VAR:IPV4>",
                    "occurrence": 1,
                    "examples": ["10.0.0.1"],
                }
            ],
            "source_metadata": {"system": "test-system"},
        },
        "expected": {
            "disposition": "mapped",
            "schema_name": "NetworkSession",
            "source_semantics": [
                {
                    "semantic_id": "source.address",
                    "source_kind": "slot",
                    "locator": "p1",
                    "role": "network.source.address",
                    "evidence": [
                        {
                            "kind": "template",
                            "reference": "from <VAR:IPV4>",
                        }
                    ],
                }
            ],
            "asim_fields": [
                {
                    "semantic_id": "source.address",
                    "asim_field": "SrcIpAddr",
                    "evidence": [
                        {
                            "kind": "catalogue",
                            "reference": "NetworkSession.SrcIpAddr",
                        }
                    ],
                }
            ],
        },
        "provenance": {"label_source": "human_review"},
    }


def test_checked_example_is_a_valid_provider_neutral_case() -> None:
    cases = load_semantic_mapping_cases(EXAMPLE_CASES)

    assert len(cases) == 1
    case = cases[0]
    assert case.expected.schema_name == "NetworkSession"
    assert {semantic.source_kind for semantic in case.expected.source_semantics} == {
        "slot",
        "template_constant",
    }
    assert "EventResult" in {field.asim_field for field in case.expected.asim_fields}


def test_canonical_jsonl_round_trips_without_provider_output(tmp_path: Path) -> None:
    case = SemanticMappingCase.model_validate(_case_payload())
    output = tmp_path / "cases.jsonl"

    write_semantic_mapping_cases(output, [case])
    loaded = load_semantic_mapping_cases(output)

    assert loaded == [case]
    serialized = json.loads(output.read_text(encoding="utf-8"))
    assert list(serialized) == sorted(serialized)
    assert "provider" not in serialized
    assert "confidence" not in serialized["expected"]


def test_rejects_asim_field_that_has_no_source_semantic_label() -> None:
    payload = _case_payload()
    expected = payload["expected"]
    assert isinstance(expected, dict)
    fields = expected["asim_fields"]
    assert isinstance(fields, list)
    fields[0]["semantic_id"] = "missing.role"

    with pytest.raises(ValueError, match="unknown semantic IDs"):
        SemanticMappingCase.model_validate(payload)


def test_rejects_slot_semantic_that_is_absent_from_input() -> None:
    payload = _case_payload()
    expected = payload["expected"]
    assert isinstance(expected, dict)
    semantics = expected["source_semantics"]
    assert isinstance(semantics, list)
    semantics[0]["locator"] = "p2"

    with pytest.raises(ValueError, match="unknown slot"):
        SemanticMappingCase.model_validate(payload)


def test_unresolved_case_requires_a_reason() -> None:
    payload = _case_payload()
    expected = payload["expected"]
    assert isinstance(expected, dict)
    expected["disposition"] = "unresolved"

    with pytest.raises(ValueError, match="require unresolved_reasons"):
        SemanticMappingCase.model_validate(payload)


def test_not_applicable_case_cannot_retain_asim_targets() -> None:
    payload = _case_payload()
    expected = payload["expected"]
    assert isinstance(expected, dict)
    expected["disposition"] = "not_applicable"

    with pytest.raises(ValueError, match="cannot have ASIM targets"):
        SemanticMappingCase.model_validate(payload)


def test_provider_specific_fields_are_forbidden() -> None:
    payload = _case_payload()
    payload["provider"] = {"name": "example", "confidence": 0.9}

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        SemanticMappingCase.model_validate(payload)


def test_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    case = SemanticMappingCase.model_validate(_case_payload())
    path = tmp_path / "duplicate.jsonl"
    serialized = case.model_dump_json()
    path.write_text(f"{serialized}\n{serialized}\n", encoding="utf-8")

    with pytest.raises(EvaluationError, match="must be unique"):
        load_semantic_mapping_cases(path)


def test_cli_validates_provider_neutral_cases(capsys: pytest.CaptureFixture[str]) -> None:
    main(["evaluation", "validate", str(EXAMPLE_CASES)])

    assert "Validated 1 provider-neutral semantic mapping case(s)" in capsys.readouterr().out
