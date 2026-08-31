import hashlib
import json
from pathlib import Path

import pytest

from asim_forge.semantic_annotation import (
    SemanticAnnotationError,
    promote_semantic_annotations,
    validate_semantic_promotion_artifacts,
    write_semantic_annotation_decisions,
)


def test_promotion_rejects_a_changed_queue_task_set(
    annotation_queue,
    decision_factory,
    tmp_path: Path,
) -> None:
    _, catalog, queue_dir, _, task = annotation_queue
    decisions_path = tmp_path / "decisions.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [decision_factory(task, "auth.alice.v1", "alice")],
    )
    (queue_dir / "tasks.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(SemanticAnnotationError, match="do not match queue-manifest"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "biased-subset",
            catalog,
            allow_single_review=True,
        )


@pytest.mark.parametrize("mode", ["missing", "invalid", "count", "group"])
def test_promotion_rejects_invalid_queue_manifests(
    annotation_queue,
    decision_factory,
    mode: str,
    tmp_path: Path,
) -> None:
    _, catalog, queue_dir, _, task = annotation_queue
    decisions_path = tmp_path / "decisions.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [decision_factory(task, "auth.alice.v1", "alice")],
    )
    manifest_path = queue_dir / "queue-manifest.json"
    if mode == "missing":
        manifest_path.unlink()
        match = "does not exist"
    elif mode == "invalid":
        manifest_path.write_text("not-json", encoding="utf-8")
        match = "Invalid queue manifest"
    else:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mode == "count":
            payload["task_count"] = 2
            match = "task count"
        else:
            payload["group_id"] = "changed.family"
            match = "does not match queue-manifest"
        manifest_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(SemanticAnnotationError, match=match):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / f"invalid-{mode}",
            catalog,
            allow_single_review=True,
        )


@pytest.mark.parametrize(
    ("mode", "match"),
    [
        ("cases_hash", "cases do not match"),
        ("groups_hash", "case groups do not match"),
        ("count", "output counts"),
        ("catalogue", "catalogue revision"),
        ("coverage", "different case IDs"),
        ("output", "outputs named by"),
    ],
)
def test_promotion_artifact_verifier_rejects_tampering(
    annotation_queue,
    decision_factory,
    mode: str,
    other_catalog_revision: str,
    tmp_path: Path,
    match: str,
) -> None:
    _, catalog, queue_dir, _, task = annotation_queue
    decisions_path = tmp_path / "decisions.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [decision_factory(task, "auth.alice.v1", "alice")],
    )
    output_dir = tmp_path / "gold"
    promote_semantic_annotations(
        queue_dir,
        decisions_path,
        output_dir,
        catalog,
        allow_single_review=True,
    )
    cases_path = output_dir / "cases.jsonl"
    groups_path = output_dir / "case-groups.jsonl"
    manifest_path = output_dir / "promotion-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mode == "cases_hash":
        cases_path.write_text(cases_path.read_text("utf-8") + "\n", encoding="utf-8")
    elif mode == "groups_hash":
        groups_path.write_text(groups_path.read_text("utf-8") + "\n", encoding="utf-8")
    elif mode == "count":
        manifest["promoted_count"] = 2
    elif mode == "catalogue":
        manifest["catalogue_revision"] = other_catalog_revision
    elif mode == "coverage":
        group = json.loads(groups_path.read_text(encoding="utf-8"))
        group["case_id"] = "cluster-another"
        groups_path.write_text(json.dumps(group) + "\n", encoding="utf-8")
        manifest["case_groups_sha256"] = hashlib.sha256(groups_path.read_bytes()).hexdigest()
    else:
        manifest["outputs"]["cases"] = "different-cases.jsonl"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(SemanticAnnotationError, match=match):
        validate_semantic_promotion_artifacts(cases_path, groups_path, manifest_path)
