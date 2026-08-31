import hashlib
import json
from pathlib import Path

import pytest

from asim_forge.models import AsimCatalog
from asim_forge.semantic_annotation import (
    SemanticAnnotationError,
    prepare_semantic_annotation_queue,
)


def test_queue_is_deterministic_blinded_and_keeps_grouping_provenance(
    tmp_path: Path,
    annotation_queue,
) -> None:
    _, catalog, output_dir, manifest, task = annotation_queue

    assert manifest.task_count == 1
    assert manifest.review_status_counts == {"approved": 1, "rejected": 1}
    assert manifest.unreviewed_cluster_count == 1
    assert task.case_id == "cluster-auth"
    assert task.group_id == "openssh.family"
    assert task.input.source_metadata.model_dump() == {
        "system": "test-auth-source",
        "vendor": "OpenBSD",
        "product": "OpenSSH",
        "source_table": "Syslog",
        "message_field": "SyslogMessage",
    }
    assert task.provenance.clustering_engine == "DeepParse"
    assert task.provenance.reviewer_ref == "stage-one-reviewer"
    assert task.input.representative_events[0].source_file == "source-001"
    assert (
        manifest.tasks_sha256
        == hashlib.sha256((output_dir / "tasks.jsonl").read_bytes()).hexdigest()
    )
    assert (
        manifest.submission_schema_sha256
        == hashlib.sha256((output_dir / "submission-schema.json").read_bytes()).hexdigest()
    )
    raw_tasks = (output_dir / "tasks.jsonl").read_text(encoding="utf-8")
    assert "schema_suggestion" not in raw_tasks
    assert "suggestion" not in raw_tasks
    assert "confidence" not in raw_tasks
    assert '"expected"' not in raw_tasks
    assert '"schema_name"' not in raw_tasks
    assert "auth.log" not in raw_tasks
    assert (output_dir / "submission-schema.json").is_file()

    second_output = tmp_path / "queue-again"
    build_dir = tmp_path / "build"
    prepare_semantic_annotation_queue(
        build_dir,
        tmp_path / "reviews.jsonl",
        second_output,
        catalog,
        group_id="openssh.family",
        group_strategy="source-family",
        vendor="OpenBSD",
        product="OpenSSH",
        source_table="Syslog",
        message_field="SyslogMessage",
    )
    assert (second_output / "tasks.jsonl").read_bytes() == (output_dir / "tasks.jsonl").read_bytes()


def test_queue_rejects_inconsistent_selection_inputs(
    semantic_build: tuple[Path, Path],
    semantic_catalog: tuple[Path, AsimCatalog],
    tmp_path: Path,
) -> None:
    build_dir, reviews_path = semantic_build
    _, catalog = semantic_catalog
    with pytest.raises(SemanticAnnotationError, match="Build-level queues support"):
        prepare_semantic_annotation_queue(
            build_dir,
            reviews_path,
            tmp_path / "manual-groups",
            catalog,
            group_id="manual.group",
            group_strategy="manual",  # ty: ignore[invalid-argument-type]
        )
    manifest_path = build_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cluster_count"] = 2
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(SemanticAnnotationError, match="cluster_count"):
        prepare_semantic_annotation_queue(
            build_dir,
            reviews_path,
            tmp_path / "bad-count",
            catalog,
            group_id="openssh.family",
            group_strategy="source-family",
        )

    manifest["cluster_count"] = 3
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    reviews_path.write_text(
        json.dumps(
            {
                "cluster_id": "cluster-missing",
                "reviewer": "alice",
                "status": "approved",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SemanticAnnotationError, match="unknown clusters"):
        prepare_semantic_annotation_queue(
            build_dir,
            reviews_path,
            tmp_path / "unknown-cluster",
            catalog,
            group_id="openssh.family",
            group_strategy="source-family",
        )

    reviews_path.write_text(
        json.dumps(
            {
                "cluster_id": "cluster-rejected",
                "reviewer": "alice",
                "status": "rejected",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SemanticAnnotationError, match="No approved clusters"):
        prepare_semantic_annotation_queue(
            build_dir,
            reviews_path,
            tmp_path / "no-approved",
            catalog,
            group_id="openssh.family",
            group_strategy="source-family",
        )
