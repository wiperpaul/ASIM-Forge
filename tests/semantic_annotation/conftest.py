import json
from collections.abc import Callable
from pathlib import Path

import pytest

from asim_forge.catalog import load_catalog, sync_catalog
from asim_forge.evaluation import ExpectedSemanticMapping
from asim_forge.models import (
    AsimCatalog,
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
    SemanticAnnotationQueueManifest,
    SemanticAnnotationTask,
    load_semantic_annotation_tasks,
    prepare_semantic_annotation_queue,
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


@pytest.fixture
def semantic_build(tmp_path: Path) -> tuple[Path, Path]:
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


@pytest.fixture
def semantic_catalog(tmp_path: Path) -> tuple[Path, AsimCatalog]:
    catalog_dir = tmp_path / "catalog"
    sync_catalog(catalog_dir, revision=REVISION, fetch_bytes=lambda _: CATALOG)
    return catalog_dir, load_catalog(catalog_dir)


@pytest.fixture
def annotation_queue(
    tmp_path: Path,
    semantic_build: tuple[Path, Path],
    semantic_catalog: tuple[Path, AsimCatalog],
) -> tuple[
    Path,
    AsimCatalog,
    Path,
    SemanticAnnotationQueueManifest,
    SemanticAnnotationTask,
]:
    build_dir, reviews_path = semantic_build
    catalog_dir, catalog = semantic_catalog
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
    task: SemanticAnnotationTask,
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


@pytest.fixture
def decision_factory() -> Callable[..., SemanticAnnotationDecision]:
    return _decision


@pytest.fixture
def other_catalog_revision() -> str:
    return OTHER_REVISION
