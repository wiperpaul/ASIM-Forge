import hashlib
import json
from pathlib import Path

import pytest

from asim_forge.cli import main
from asim_forge.evaluation import load_semantic_mapping_cases
from asim_forge.models import AsimCatalog
from asim_forge.semantic_annotation import (
    load_semantic_annotation_tasks,
    write_semantic_annotation_decisions,
)


def test_queue_cli_writes_only_approved_tasks(
    capsys: pytest.CaptureFixture[str],
    semantic_build: tuple[Path, Path],
    semantic_catalog: tuple[Path, AsimCatalog],
    tmp_path: Path,
) -> None:
    build_dir, reviews_path = semantic_build
    catalog_dir, _ = semantic_catalog
    output_dir = tmp_path / "cli-queue"

    main(
        [
            "evaluation",
            "queue",
            str(build_dir),
            str(reviews_path),
            "--catalog",
            str(catalog_dir),
            "--group-id",
            "openssh.family",
            "--group-strategy",
            "source-family",
            "--output",
            str(output_dir),
        ]
    )

    assert "Prepared 1 blinded semantic annotation task(s)" in capsys.readouterr().out
    assert load_semantic_annotation_tasks(output_dir / "tasks.jsonl")[0].case_id == "cluster-auth"


def test_two_independent_reviews_and_adjudication_promote_by_default(
    annotation_queue,
    decision_factory,
    tmp_path: Path,
) -> None:
    catalog_dir, _, queue_dir, _, task = annotation_queue
    decisions = [
        decision_factory(task, "auth.alice.v1", "alice"),
        decision_factory(task, "auth.bob.v1", "bob"),
        decision_factory(
            task,
            "auth.adjudicated.v1",
            "carol",
            kind="adjudication",
            refs=["auth.alice.v1", "auth.bob.v1"],
        ),
    ]
    decisions_path = tmp_path / "adjudicated.jsonl"
    write_semantic_annotation_decisions(decisions_path, decisions)
    output_dir = tmp_path / "gold"

    main(
        [
            "evaluation",
            "promote",
            str(queue_dir),
            str(decisions_path),
            "--catalog",
            str(catalog_dir),
            "--output",
            str(output_dir),
        ]
    )

    case = load_semantic_mapping_cases(output_dir / "cases.jsonl")[0]
    manifest = json.loads((output_dir / "promotion-manifest.json").read_text("utf-8"))
    assert case.provenance.label_source == "adjudicated"
    assert case.provenance.decision_refs == [
        "auth.alice.v1",
        "auth.bob.v1",
        "auth.adjudicated.v1",
    ]
    assert case.provenance.annotator_refs == ["alice", "bob", "carol"]
    assert (
        manifest["cases_sha256"]
        == hashlib.sha256((output_dir / "cases.jsonl").read_bytes()).hexdigest()
    )
