import hashlib
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
from asim_forge.evaluation_splits import (
    SemanticCaseGroup,
    SemanticDatasetSplit,
    load_semantic_case_groups,
    load_semantic_dataset_split,
    select_semantic_split,
    validate_semantic_case_groups,
    validate_semantic_dataset_split,
    write_semantic_case_groups,
)
from asim_forge.models import AsimCatalog, AsimCatalogField, AsimCatalogManifest
from asim_forge.semantic_mapping.comparison import compare_split_approaches

EXAMPLE_CASES = Path("examples/evaluation/semantic-mapping-cases.jsonl")


def _cases() -> list[SemanticMappingCase]:
    reference = load_semantic_mapping_cases(EXAMPLE_CASES)[0]
    target = reference.model_copy(deep=True, update={"case_id": "heldout.network.allowed"})
    target.input.source_metadata.system = "heldout-gateway"
    return [reference, target]


def _split_payload() -> dict[str, object]:
    revision = _cases()[0].catalogue_revision
    return {
        "format_version": "1",
        "split_id": "pilot.source.v1",
        "catalogue_revision": revision,
        "group_strategy": "source",
        "reference_partitions": ["train"],
        "entries": [
            {
                "case_id": "demo.network.allowed",
                "group_id": "demo-gateway",
                "partition": "train",
            },
            {
                "case_id": "heldout.network.allowed",
                "group_id": "heldout-gateway",
                "partition": "test",
            },
        ],
    }


def _catalog() -> AsimCatalog:
    revision = _cases()[0].catalogue_revision
    fields = [
        AsimCatalogField(
            name="EventResult",
            kql_type="string",
            field_class="Recommended",
            schema_name="Common",
            logical_type="Event result",
        ),
        AsimCatalogField(
            name="SrcIpAddr",
            kql_type="string",
            field_class="Recommended",
            schema_name="NetworkSession",
            logical_type="IP Address",
        ),
        AsimCatalogField(
            name="DstIpAddr",
            kql_type="string",
            field_class="Recommended",
            schema_name="NetworkSession",
            logical_type="IP Address",
        ),
        AsimCatalogField(
            name="DstPortNumber",
            kql_type="int",
            field_class="Recommended",
            schema_name="NetworkSession",
            logical_type="Port Number",
        ),
    ]
    return AsimCatalog(
        manifest=AsimCatalogManifest(
            source_repository="https://github.com/Azure/Azure-Sentinel",
            source_path="ASIM/dev/ASimTester/ASimTester.csv",
            requested_revision=revision,
            resolved_revision=revision,
            content_sha256="0" * 64,
            schema_count=1,
            field_count=len(fields),
            schemas=["NetworkSession"],
        ),
        fields=fields,
    )


def test_split_groups_cannot_cross_partitions() -> None:
    payload = _split_payload()
    entries = payload["entries"]
    assert isinstance(entries, list)
    entries[1]["group_id"] = "demo-gateway"

    with pytest.raises(ValueError, match="groups cannot cross partitions"):
        SemanticDatasetSplit.model_validate(payload)


def test_split_must_cover_cases_exactly() -> None:
    split = SemanticDatasetSplit.model_validate(_split_payload())

    with pytest.raises(EvaluationError, match="cover the case set exactly"):
        validate_semantic_dataset_split(_cases()[:1], split)


def test_split_cannot_change_groups_assigned_before_labelling() -> None:
    split = SemanticDatasetSplit.model_validate(_split_payload())
    groups = [
        SemanticCaseGroup(
            case_id=entry.case_id,
            group_id=entry.group_id,
            group_strategy="source",
        )
        for entry in split.entries
    ]
    groups[1].group_id = "changed-after-labelling"

    with pytest.raises(EvaluationError, match="changes frozen case groups"):
        validate_semantic_case_groups(_cases(), split, groups)


def test_frozen_case_groups_require_exact_coverage_and_strategy() -> None:
    split = SemanticDatasetSplit.model_validate(_split_payload())
    one_group = [
        SemanticCaseGroup(
            case_id=split.entries[0].case_id,
            group_id=split.entries[0].group_id,
            group_strategy="source",
        )
    ]
    with pytest.raises(EvaluationError, match="cover the case set exactly"):
        validate_semantic_case_groups(_cases(), split, one_group)

    groups = [
        SemanticCaseGroup(
            case_id=entry.case_id,
            group_id=entry.group_id,
            group_strategy="source-family",
        )
        for entry in split.entries
    ]
    with pytest.raises(EvaluationError, match="strategies differ"):
        validate_semantic_case_groups(_cases(), split, groups)


def test_case_group_jsonl_rejects_empty_and_duplicate_records(tmp_path: Path) -> None:
    empty = tmp_path / "empty-groups.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(EvaluationError, match="No semantic case groups"):
        load_semantic_case_groups(empty)
    with pytest.raises(EvaluationError, match="At least one semantic case group"):
        write_semantic_case_groups(tmp_path / "none.jsonl", [])

    group = SemanticCaseGroup(
        case_id="duplicate.case",
        group_id="source.family",
        group_strategy="source-family",
    )
    with pytest.raises(EvaluationError, match="must be unique"):
        write_semantic_case_groups(tmp_path / "duplicate.jsonl", [group, group])
    duplicate = tmp_path / "duplicate-load.jsonl"
    duplicate.write_text(
        f"{group.model_dump_json()}\n{group.model_dump_json()}\n", encoding="utf-8"
    )
    with pytest.raises(EvaluationError, match="must be unique"):
        load_semantic_case_groups(duplicate)


def test_select_split_keeps_reference_and_evaluation_cases_disjoint() -> None:
    split = SemanticDatasetSplit.model_validate(_split_payload())

    selection = select_semantic_split(_cases(), split, "test")

    assert [case.case_id for case in selection.reference_cases] == ["demo.network.allowed"]
    assert [case.case_id for case in selection.evaluation_cases] == ["heldout.network.allowed"]


def test_grouped_comparison_gives_retrieval_only_training_references() -> None:
    split = SemanticDatasetSplit.model_validate(_split_payload())

    report = compare_split_approaches(
        _cases(),
        _catalog(),
        split,
        "test",
        ["case-retrieval"],
    )

    assert report.split_id == "pilot.source.v1"
    assert report.evaluation_partition == "test"
    assert report.reference_case_count == 1
    assert report.case_count == 1
    assert report.approaches[0].metrics.mapping_exact_match == 1
    assert not any(
        "No explicit grouped split" in warning for warning in report.approaches[0].warnings
    )


def test_cli_validates_cases_with_split(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cases_path = tmp_path / "cases.jsonl"
    groups_path = tmp_path / "case-groups.jsonl"
    promotion_path = tmp_path / "promotion-manifest.json"
    split_path = tmp_path / "split.json"
    write_semantic_mapping_cases(cases_path, _cases())
    split_path.write_text(json.dumps(_split_payload()), encoding="utf-8")
    split = SemanticDatasetSplit.model_validate(_split_payload())
    write_semantic_case_groups(
        groups_path,
        [
            SemanticCaseGroup(
                case_id=entry.case_id,
                group_id=entry.group_id,
                group_strategy="source",
            )
            for entry in split.entries
        ],
    )
    promotion_path.write_text(
        json.dumps(
            {
                "format_version": "1",
                "protocol_revision": "semantic-pilot.v1",
                "catalogue_revision": _cases()[0].catalogue_revision,
                "task_count": 2,
                "decision_count": 2,
                "promoted_count": 2,
                "label_source_counts": {"adjudicated": 2},
                "skipped_tasks": {},
                "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
                "case_groups_sha256": hashlib.sha256(groups_path.read_bytes()).hexdigest(),
                "decisions_sha256": "0" * 64,
                "queue_manifest_sha256": "1" * 64,
                "tasks_sha256": "2" * 64,
                "outputs": {
                    "cases": cases_path.name,
                    "case_groups": groups_path.name,
                },
            }
        ),
        encoding="utf-8",
    )

    main(
        [
            "evaluation",
            "validate",
            str(cases_path),
            "--split",
            str(split_path),
            "--case-groups",
            str(groups_path),
            "--promotion-manifest",
            str(promotion_path),
        ]
    )

    output = capsys.readouterr().out
    assert "grouped split pilot.source.v1" in output
    assert "test=1, train=1" in output
    assert load_semantic_dataset_split(split_path).split_id == "pilot.source.v1"
