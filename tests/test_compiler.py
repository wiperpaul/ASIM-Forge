import json
from pathlib import Path

import pytest

from asim_forge.compiler import compile_reviews
from asim_forge.models import (
    ClusterRecord,
    ParameterSlot,
    SchemaScore,
    SchemaSuggestion,
    SourceEvent,
)
from asim_forge.reviews import ReviewError


def _write_cluster(path: Path) -> ClusterRecord:
    cluster = ClusterRecord(
        cluster_id="cluster-auth",
        engine_cluster_id=1,
        template="Login user <VAR:TEXT> from <VAR:IPV4>",
        event_count=2,
        representative_events=[
            SourceEvent(
                source_file="auth.log",
                line_number=1,
                text="Login user alice from 10.0.0.1",
            )
        ],
        parameter_slots=[
            ParameterSlot(
                slot_id="p1",
                label="TEXT",
                placeholder="<VAR:TEXT>",
                occurrence=1,
                examples=["alice", "bob"],
            ),
            ParameterSlot(
                slot_id="p2",
                label="IPV4",
                placeholder="<VAR:IPV4>",
                occurrence=1,
                examples=["10.0.0.1", "10.0.0.2"],
            ),
        ],
        schema_suggestion=SchemaSuggestion(
            schema_name="Authentication",
            confidence=1.0,
            ranked_scores=[
                SchemaScore(schema_name="Authentication", score=1, evidence=["login"])
            ],
        ),
    )
    path.write_text(cluster.model_dump_json() + "\n", encoding="utf-8")
    return cluster


def _review(cluster_id: str, *, slot_id: str = "p2") -> dict[str, object]:
    return {
        "cluster_id": cluster_id,
        "reviewer": "alice",
        "status": "approved",
        "schema_name": "Authentication",
        "parser_name": "vimDemoAuth",
        "vendor": "Demo",
        "product": "Gateway",
        "source_table": "Syslog",
        "message_field": "SyslogMessage",
        "field_mappings": [
            {"slot_id": "p1", "asim_field": "TargetUsername", "transform": "string"},
            {"slot_id": slot_id, "asim_field": "SrcIpAddr", "transform": "string"},
        ],
        "notes": "approved",
    }


def test_compiles_only_approved_review_to_spec_and_kql(tmp_path: Path) -> None:
    clusters_path = tmp_path / "clusters.jsonl"
    reviews_path = tmp_path / "reviews.jsonl"
    output_dir = tmp_path / "compiled"
    cluster = _write_cluster(clusters_path)
    reviews_path.write_text(json.dumps(_review(cluster.cluster_id)) + "\n", encoding="utf-8")

    manifest = compile_reviews(clusters_path, reviews_path, output_dir)

    assert manifest.compiled_count == 1
    specification = json.loads((output_dir / "vimDemoAuth.parser-spec.json").read_text("utf-8"))
    assert specification["reviewer"] == "alice"
    kql = (output_dir / "vimDemoAuth.kql").read_text("utf-8")
    assert "let vimDemoAuth" in kql
    assert "TargetUsername = tostring(_asim_forge_p1)" in kql
    assert "SrcIpAddr = tostring(_asim_forge_p2)" in kql
    assert 'EventSchema = "Authentication"' in kql
    assert r"Login user (.+?) from (.+?)" in kql
    assert r"Login\ user" not in kql


def test_rejects_mapping_to_unknown_parameter_slot(tmp_path: Path) -> None:
    clusters_path = tmp_path / "clusters.jsonl"
    reviews_path = tmp_path / "reviews.jsonl"
    cluster = _write_cluster(clusters_path)
    reviews_path.write_text(
        json.dumps(_review(cluster.cluster_id, slot_id="p9")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ReviewError, match="unknown slots: p9"):
        compile_reviews(clusters_path, reviews_path, tmp_path / "compiled")
