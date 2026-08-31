import hashlib
import json
from pathlib import Path

import pytest

from asim_forge.catalog import load_catalog, sync_catalog
from asim_forge.cli import main
from asim_forge.evaluation import ExpectedSemanticMapping, load_semantic_mapping_cases
from asim_forge.models import (
    BuildManifest,
    ClusterRecord,
    InputFile,
    ParameterSlot,
    SchemaScore,
    SchemaSuggestion,
    SourceEvent,
)
from asim_forge.semantic_annotation import (
    SemanticAnnotationDecision,
    SemanticAnnotationError,
    load_semantic_annotation_tasks,
    prepare_semantic_annotation_queue,
    promote_semantic_annotations,
    semantic_input_fingerprint,
    semantic_task_revision,
    validate_semantic_promotion_artifacts,
    write_semantic_annotation_decisions,
    write_semantic_annotation_tasks,
)

REVISION = "0123456789abcdef0123456789abcdef01234567"
OTHER_REVISION = "89abcdef0123456789abcdef0123456789abcdef"
CATALOG = (
    b"ColumnName,ColumnType,Class,Schema,LogicalType,ListOfValues,"
    b"Aliased,DynamicType,ArrayValuesType\n"
    b"EventCount,int,Mandatory,Common,,,,,\n"
    b"SrcIpAddr,string,Recommended,Authentication,IP Address,,,,\n"
    b"TargetUsername,string,Recommended,Authentication,Username,,,,\n"
    b"EventResult,string,Recommended,Authentication,Enumerated,Success|Failure,,,\n"
    b"Flag,bool,Optional,Authentication,,,,,\n"
    b"AttemptCount,int,Optional,Authentication,,,,,\n"
    b"RiskScore,real,Optional,Authentication,,,,,\n"
    b"DstIpAddr,string,Recommended,NetworkSession,IP Address,,,,\n"
)


def _cluster(cluster_id: str, template: str, *, engine_id: int) -> ClusterRecord:
    return ClusterRecord(
        cluster_id=cluster_id,
        engine_cluster_id=engine_id,
        template=template,
        event_count=2,
        representative_events=[
            SourceEvent(
                source_file="auth.log",
                line_number=engine_id,
                text=template.replace("<VAR:TEXT>", "alice"),
            )
        ],
        parameter_slots=[
            ParameterSlot(
                slot_id="p1",
                label="TEXT",
                placeholder="<VAR:TEXT>",
                occurrence=1,
                examples=["alice", "bob"],
            )
        ],
        schema_suggestion=SchemaSuggestion(
            schema_name="Authentication",
            confidence=0.99,
            ranked_scores=[SchemaScore(schema_name="Authentication", score=2, evidence=["login"])],
        ),
    )


def _write_build_and_reviews(tmp_path: Path) -> tuple[Path, Path]:
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    clusters = [
        _cluster("cluster-auth", "login failed for <VAR:TEXT>", engine_id=1),
        _cluster("cluster-rejected", "debug record <VAR:TEXT>", engine_id=2),
        _cluster("cluster-unreviewed", "logout for <VAR:TEXT>", engine_id=3),
    ]
    clusters_path = build_dir / "clusters.jsonl"
    clusters_path.write_text(
        "\n".join(cluster.model_dump_json() for cluster in clusters) + "\n",
        encoding="utf-8",
    )
    manifest = BuildManifest(
        system="test-auth-source",
        engine_revision="deepparse-test-revision",
        input_root="private/input",
        input_files=[InputFile(path="auth.log", event_count=6)],
        event_count=6,
        cluster_count=3,
        masks=[],
        outputs={"clusters": "clusters.jsonl"},
    )
    (build_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reviews_path = tmp_path / "reviews.jsonl"
    reviews = [
        {
            "cluster_id": "cluster-auth",
            "reviewer": "stage-one-reviewer",
            "status": "approved",
            "schema_name": "Authentication",
            "parser_name": "vimExistingMapping",
            "vendor": "ExistingVendor",
            "product": "ExistingProduct",
            "field_mappings": [
                {"slot_id": "p1", "asim_field": "TargetUsername", "transform": "string"}
            ],
        },
        {
            "cluster_id": "cluster-rejected",
            "reviewer": "stage-one-reviewer",
            "status": "rejected",
        },
    ]
    reviews_path.write_text(
        "\n".join(json.dumps(review, sort_keys=True) for review in reviews) + "\n",
        encoding="utf-8",
    )
    return build_dir, reviews_path


def _catalog(tmp_path: Path):
    catalog_dir = tmp_path / "catalog"
    sync_catalog(catalog_dir, revision=REVISION, fetch_bytes=lambda _: CATALOG)
    return catalog_dir, load_catalog(catalog_dir)


def _queue(tmp_path: Path):
    build_dir, reviews_path = _write_build_and_reviews(tmp_path)
    catalog_dir, catalog = _catalog(tmp_path)
    output_dir = tmp_path / "queue"
    manifest = prepare_semantic_annotation_queue(
        build_dir,
        reviews_path,
        output_dir,
        catalog,
        group_id="openssh.family",
        group_strategy="source-family",
        vendor="OpenBSD",
        product="OpenSSH",
        source_table="Syslog",
        message_field="SyslogMessage",
    )
    task = load_semantic_annotation_tasks(output_dir / "tasks.jsonl")[0]
    return catalog_dir, catalog, output_dir, manifest, task


def _expected(*, field: str = "TargetUsername") -> ExpectedSemanticMapping:
    return ExpectedSemanticMapping.model_validate(
        {
            "disposition": "mapped",
            "schema_name": "Authentication",
            "source_semantics": [
                {
                    "semantic_id": "target.user",
                    "source_kind": "slot",
                    "locator": "p1",
                    "role": "identity.target.user",
                    "evidence": [
                        {
                            "kind": "representative_event",
                            "reference": "source-001:1",
                            "rationale": "The phrase 'for' identifies the account.",
                        }
                    ],
                }
            ],
            "asim_fields": [
                {
                    "semantic_id": "target.user",
                    "asim_field": field,
                    "evidence": [
                        {
                            "kind": "catalogue",
                            "reference": f"Authentication.{field}",
                        }
                    ],
                }
            ],
        }
    )


def _decision(
    task,
    decision_id: str,
    reviewer: str,
    *,
    kind: str = "annotation",
    refs: list[str] | None = None,
    field: str = "TargetUsername",
    fingerprint: str | None = None,
    revision: str = REVISION,
) -> SemanticAnnotationDecision:
    return SemanticAnnotationDecision.model_validate(
        {
            "decision_id": decision_id,
            "decision_kind": kind,
            "case_id": task.case_id,
            "catalogue_revision": revision,
            "input_fingerprint": fingerprint or task.input_fingerprint,
            "task_revision": task.task_revision,
            "reviewer_ref": reviewer,
            "expected": _expected(field=field).model_dump(mode="json"),
            "source_decision_refs": refs or [],
            "notes": f"Decision by {reviewer}",
        }
    )


def test_queue_is_deterministic_blinded_and_keeps_grouping_provenance(tmp_path: Path) -> None:
    _, catalog, output_dir, manifest, task = _queue(tmp_path)

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


def test_queue_cli_writes_only_approved_tasks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build_dir, reviews_path = _write_build_and_reviews(tmp_path)
    catalog_dir, _ = _catalog(tmp_path)
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


def test_task_loader_rejects_tampering_and_approach_fields(tmp_path: Path) -> None:
    _, _, output_dir, _, _ = _queue(tmp_path)
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


def test_single_review_requires_opt_in_and_promotes_without_group_leakage(tmp_path: Path) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decisions_path = tmp_path / "decisions.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [_decision(task, "auth.alice.v1", "alice")],
    )

    with pytest.raises(SemanticAnnotationError, match="No decisions are eligible"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "not-promoted",
            catalog,
        )

    output_dir = tmp_path / "promoted"
    manifest = promote_semantic_annotations(
        queue_dir,
        decisions_path,
        output_dir,
        catalog,
        allow_single_review=True,
    )
    case = load_semantic_mapping_cases(output_dir / "cases.jsonl")[0]

    assert manifest.promoted_count == 1
    assert manifest.label_source_counts == {"human_review": 1}
    assert case.provenance.label_source == "human_review"
    assert case.provenance.decision_refs == ["auth.alice.v1"]
    assert case.input == task.input
    raw_case = (output_dir / "cases.jsonl").read_text(encoding="utf-8")
    assert '"group_id"' not in raw_case
    group = json.loads((output_dir / "case-groups.jsonl").read_text(encoding="utf-8"))
    assert group == {
        "case_id": task.case_id,
        "group_id": "openssh.family",
        "group_strategy": "source-family",
    }


def test_two_independent_reviews_and_adjudication_promote_by_default(tmp_path: Path) -> None:
    catalog_dir, _, queue_dir, _, task = _queue(tmp_path)
    decisions = [
        _decision(task, "auth.alice.v1", "alice"),
        _decision(task, "auth.bob.v1", "bob"),
        _decision(
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


def test_promotion_rejects_stale_and_unknown_catalogue_mappings(tmp_path: Path) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decisions_path = tmp_path / "bad.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [_decision(task, "auth.stale.v1", "alice", fingerprint="0" * 64)],
    )
    with pytest.raises(SemanticAnnotationError, match="is stale"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "stale",
            catalog,
            allow_single_review=True,
        )


def test_promotion_rejects_a_changed_queue_task_set(tmp_path: Path) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decisions_path = tmp_path / "decisions.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [_decision(task, "auth.alice.v1", "alice")],
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
def test_promotion_rejects_invalid_queue_manifests(tmp_path: Path, mode: str) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decisions_path = tmp_path / "decisions.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [_decision(task, "auth.alice.v1", "alice")],
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
    tmp_path: Path, mode: str, match: str
) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decisions_path = tmp_path / "decisions.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [_decision(task, "auth.alice.v1", "alice")],
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
        manifest["catalogue_revision"] = OTHER_REVISION
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


def test_promotion_reports_tasks_with_no_submission(tmp_path: Path) -> None:
    _, catalog, queue_dir, _, first = _queue(tmp_path)
    second = first.model_copy(deep=True)
    second.case_id = "cluster-second"
    second.input.cluster_id = second.case_id
    second.input_fingerprint = semantic_input_fingerprint(second.input)
    second.task_revision = semantic_task_revision(
        case_id=second.case_id,
        catalogue_revision=second.catalogue_revision,
        group_id=second.group_id,
        group_strategy=second.group_strategy,
        input_fingerprint=second.input_fingerprint,
        provenance=second.provenance,
        protocol_revision=second.protocol_revision,
    )
    tasks_path = queue_dir / "tasks.jsonl"
    write_semantic_annotation_tasks(tasks_path, [first, second])
    queue_manifest_path = queue_dir / "queue-manifest.json"
    queue_manifest = json.loads(queue_manifest_path.read_text(encoding="utf-8"))
    queue_manifest["task_count"] = 2
    queue_manifest["tasks_sha256"] = hashlib.sha256(tasks_path.read_bytes()).hexdigest()
    queue_manifest_path.write_text(json.dumps(queue_manifest) + "\n", encoding="utf-8")
    decisions_path = tmp_path / "decisions.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [_decision(first, "auth.alice.v1", "alice")],
    )

    manifest = promote_semantic_annotations(
        queue_dir,
        decisions_path,
        tmp_path / "partial-gold",
        catalog,
        allow_single_review=True,
    )

    assert manifest.skipped_tasks == {"unsubmitted": 1}


def test_promotion_validates_constant_types_and_catalogue_domains(tmp_path: Path) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decisions_path = tmp_path / "constant-decisions.jsonl"
    invalid_domain = _decision(
        task,
        "auth.invalid-domain.v1",
        "alice",
        field="EventResult",
    )
    invalid_domain.expected.asim_fields[0].constant_value = "Banana"
    write_semantic_annotation_decisions(decisions_path, [invalid_domain])
    with pytest.raises(SemanticAnnotationError, match="outside the allowed values"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "invalid-domain",
            catalog,
            allow_single_review=True,
        )

    invalid_type = _decision(task, "auth.invalid-type.v1", "alice")
    invalid_type.expected.asim_fields[0].constant_value = True
    write_semantic_annotation_decisions(decisions_path, [invalid_type])
    with pytest.raises(SemanticAnnotationError, match="constant incompatible"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "invalid-type",
            catalog,
            allow_single_review=True,
        )

    write_semantic_annotation_decisions(
        decisions_path,
        [_decision(task, "auth.unknown-field.v1", "alice", field="UnknownAsimField")],
    )
    with pytest.raises(SemanticAnnotationError, match="maps unknown fields"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "unknown-field",
            catalog,
            allow_single_review=True,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("Flag", True), ("AttemptCount", 3), ("RiskScore", 0.75)],
)
def test_promotion_accepts_catalogue_compatible_scalar_constants(
    tmp_path: Path, field: str, value: bool | int | float
) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decision = _decision(task, f"auth.{field}.v1", "alice", field=field)
    decision.expected.asim_fields[0].constant_value = value
    decisions_path = tmp_path / "scalar-decision.jsonl"
    write_semantic_annotation_decisions(decisions_path, [decision])

    manifest = promote_semantic_annotations(
        queue_dir,
        decisions_path,
        tmp_path / "scalar-gold",
        catalog,
        allow_single_review=True,
    )

    assert manifest.promoted_count == 1


def test_promotion_rejects_catalogue_drift_and_unknown_cases(tmp_path: Path) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decisions_path = tmp_path / "bad.jsonl"
    write_semantic_annotation_decisions(
        decisions_path,
        [_decision(task, "auth.other-catalog.v1", "alice", revision=OTHER_REVISION)],
    )
    with pytest.raises(SemanticAnnotationError, match="catalogue revision"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "other-catalog",
            catalog,
            allow_single_review=True,
        )

    unknown_payload = _decision(task, "auth.unknown-case.v1", "alice").model_dump(mode="json")
    unknown_payload["case_id"] = "cluster-unknown"
    decisions_path.write_text(json.dumps(unknown_payload) + "\n", encoding="utf-8")
    with pytest.raises(SemanticAnnotationError, match="unknown case"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "unknown-case",
            catalog,
            allow_single_review=True,
        )


def test_adjudication_requires_known_independent_annotations(tmp_path: Path) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decisions_path = tmp_path / "bad-adjudication.jsonl"
    same_reviewer = [
        _decision(task, "auth.alice.v1", "alice"),
        _decision(task, "auth.alice.v2", "alice"),
        _decision(
            task,
            "auth.adjudicated.v1",
            "carol",
            kind="adjudication",
            refs=["auth.alice.v1", "auth.alice.v2"],
        ),
    ]
    write_semantic_annotation_decisions(decisions_path, same_reviewer)
    with pytest.raises(SemanticAnnotationError, match="independent reviewers"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "same-reviewer",
            catalog,
        )

    unknown_reference = [
        _decision(task, "auth.alice.v1", "alice"),
        _decision(
            task,
            "auth.adjudicated.v1",
            "carol",
            kind="adjudication",
            refs=["auth.alice.v1", "auth.missing.v1"],
        ),
    ]
    write_semantic_annotation_decisions(decisions_path, unknown_reference)
    with pytest.raises(SemanticAnnotationError, match="references unknown decision"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "unknown-reference",
            catalog,
        )

    multiple_adjudications = [
        _decision(task, "auth.alice.v1", "alice"),
        _decision(task, "auth.bob.v1", "bob"),
        _decision(
            task,
            "auth.adjudicated.v1",
            "carol",
            kind="adjudication",
            refs=["auth.alice.v1", "auth.bob.v1"],
        ),
        _decision(
            task,
            "auth.adjudicated.v2",
            "dave",
            kind="adjudication",
            refs=["auth.alice.v1", "auth.bob.v1"],
        ),
    ]
    write_semantic_annotation_decisions(decisions_path, multiple_adjudications)
    with pytest.raises(SemanticAnnotationError, match="more than one adjudication"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "multiple-adjudications",
            catalog,
        )


def test_decision_contract_rejects_invalid_reference_shapes(tmp_path: Path) -> None:
    _, _, _, _, task = _queue(tmp_path)
    payload = _decision(task, "auth.alice.v1", "alice").model_dump(mode="json")
    payload["source_decision_refs"] = ["one", "one"]
    with pytest.raises(ValueError, match="must be unique"):
        SemanticAnnotationDecision.model_validate(payload)

    payload["source_decision_refs"] = ["one"]
    with pytest.raises(ValueError, match="annotations cannot reference"):
        SemanticAnnotationDecision.model_validate(payload)

    payload["decision_kind"] = "adjudication"
    with pytest.raises(ValueError, match="at least two"):
        SemanticAnnotationDecision.model_validate(payload)


def test_queue_rejects_inconsistent_selection_inputs(tmp_path: Path) -> None:
    build_dir, reviews_path = _write_build_and_reviews(tmp_path)
    _, catalog = _catalog(tmp_path)
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


def test_promotion_checks_task_revision_schema_and_slot_references(tmp_path: Path) -> None:
    _, catalog, queue_dir, _, task = _queue(tmp_path)
    decisions_path = tmp_path / "invalid-decisions.jsonl"
    stale = _decision(task, "auth.stale-task.v1", "alice").model_copy(
        update={"task_revision": "0" * 64}
    )
    write_semantic_annotation_decisions(decisions_path, [stale])
    with pytest.raises(SemanticAnnotationError, match="stale task revision"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "stale-task",
            catalog,
            allow_single_review=True,
        )

    unknown_schema = _decision(task, "auth.unknown-schema.v1", "alice")
    unknown_schema.expected.schema_name = "Dns"
    write_semantic_annotation_decisions(decisions_path, [unknown_schema])
    with pytest.raises(SemanticAnnotationError, match="unknown ASIM schema"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "unknown-schema",
            catalog,
            allow_single_review=True,
        )

    bad_slot = _decision(task, "auth.bad-slot.v1", "alice")
    bad_slot.expected.source_semantics[0].locator = "p9"
    write_semantic_annotation_decisions(decisions_path, [bad_slot])
    with pytest.raises(SemanticAnnotationError, match="does not resolve against its task"):
        promote_semantic_annotations(
            queue_dir,
            decisions_path,
            tmp_path / "bad-slot",
            catalog,
            allow_single_review=True,
        )


def test_annotation_writers_reject_empty_and_duplicate_records(tmp_path: Path) -> None:
    _, _, _, _, task = _queue(tmp_path)
    with pytest.raises(SemanticAnnotationError, match="At least one semantic annotation task"):
        write_semantic_annotation_tasks(tmp_path / "empty-tasks.jsonl", [])
    with pytest.raises(SemanticAnnotationError, match="At least one semantic annotation decision"):
        write_semantic_annotation_decisions(tmp_path / "empty-decisions.jsonl", [])
    decision = _decision(task, "auth.alice.v1", "alice")
    with pytest.raises(SemanticAnnotationError, match="must be unique"):
        write_semantic_annotation_decisions(
            tmp_path / "duplicate-decisions.jsonl", [decision, decision]
        )
