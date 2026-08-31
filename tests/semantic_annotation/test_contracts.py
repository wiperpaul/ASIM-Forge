import json
from pathlib import Path

import pytest

from asim_forge.semantic_annotation import (
    SemanticAnnotationDecision,
    SemanticAnnotationError,
    load_semantic_annotation_tasks,
    write_semantic_annotation_decisions,
    write_semantic_annotation_tasks,
)


def test_task_loader_rejects_tampering_and_approach_fields(
    annotation_queue,
    tmp_path: Path,
) -> None:
    _, _, output_dir, _, _ = annotation_queue
    raw_task = (output_dir / "tasks.jsonl").read_text(encoding="utf-8")
    task_payload = json.loads(raw_task)
    task_payload["input"]["template"] = "changed <VAR:TEXT>"
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text(json.dumps(task_payload) + "\n", encoding="utf-8")

    with pytest.raises(SemanticAnnotationError, match="input_fingerprint"):
        load_semantic_annotation_tasks(tampered)

    task_payload = json.loads(raw_task)
    task_payload["group_id"] = "changed.family"
    changed_group = tmp_path / "changed-group.jsonl"
    changed_group.write_text(json.dumps(task_payload) + "\n", encoding="utf-8")
    with pytest.raises(SemanticAnnotationError, match="task_revision"):
        load_semantic_annotation_tasks(changed_group)

    task_payload = json.loads(raw_task)
    task_payload["provenance"]["reviewer_ref"] = "changed-reviewer"
    changed_provenance = tmp_path / "changed-provenance.jsonl"
    changed_provenance.write_text(json.dumps(task_payload) + "\n", encoding="utf-8")
    with pytest.raises(SemanticAnnotationError, match="task_revision"):
        load_semantic_annotation_tasks(changed_provenance)

    task_payload = json.loads(raw_task)
    task_payload["schema_suggestion"] = {"schema_name": "Authentication"}
    injected = tmp_path / "injected.jsonl"
    injected.write_text(json.dumps(task_payload) + "\n", encoding="utf-8")
    with pytest.raises(SemanticAnnotationError, match="Extra inputs are not permitted"):
        load_semantic_annotation_tasks(injected)


def test_decision_contract_rejects_invalid_reference_shapes(
    annotation_queue,
    decision_factory,
) -> None:
    _, _, _, _, task = annotation_queue
    payload = decision_factory(task, "auth.alice.v1", "alice").model_dump(mode="json")
    payload["source_decision_refs"] = ["one", "one"]
    with pytest.raises(ValueError, match="must be unique"):
        SemanticAnnotationDecision.model_validate(payload)

    payload["source_decision_refs"] = ["one"]
    with pytest.raises(ValueError, match="annotations cannot reference"):
        SemanticAnnotationDecision.model_validate(payload)

    payload["decision_kind"] = "adjudication"
    with pytest.raises(ValueError, match="at least two"):
        SemanticAnnotationDecision.model_validate(payload)


def test_annotation_writers_reject_empty_and_duplicate_records(
    annotation_queue,
    decision_factory,
    tmp_path: Path,
) -> None:
    _, _, _, _, task = annotation_queue
    with pytest.raises(SemanticAnnotationError, match="At least one semantic annotation task"):
        write_semantic_annotation_tasks(tmp_path / "empty-tasks.jsonl", [])
    with pytest.raises(SemanticAnnotationError, match="At least one semantic annotation decision"):
        write_semantic_annotation_decisions(tmp_path / "empty-decisions.jsonl", [])
    decision = decision_factory(task, "auth.alice.v1", "alice")
    with pytest.raises(SemanticAnnotationError, match="must be unique"):
        write_semantic_annotation_decisions(
            tmp_path / "duplicate-decisions.jsonl", [decision, decision]
        )
