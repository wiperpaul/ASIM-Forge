"""Produce a self-contained Potato review task from cluster records."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .models import ClusterRecord, ReviewTask


def write_potato_bundle(clusters: list[ClusterRecord], output_dir: Path) -> tuple[Path, Path]:
    bundle_dir = output_dir / "potato"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    items_path = bundle_dir / "items.jsonl"
    config_path = bundle_dir / "config.yaml"

    tasks = [_to_review_task(cluster) for cluster in clusters]
    _write_jsonl(items_path, [task.model_dump(mode="json") for task in tasks])
    config_path.write_text(
        yaml.safe_dump(_potato_config(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return items_path, config_path


def _to_review_task(cluster: ClusterRecord) -> ReviewTask:
    samples = "\n".join(
        f"[{event.source_file}:{event.line_number}] {event.text}"
        for event in cluster.representative_events
    )
    slots = "\n".join(
        f"- {slot.slot_id} {slot.placeholder}: {', '.join(slot.examples) or 'no samples'}"
        for slot in cluster.parameter_slots
    ) or "- No parameters detected"
    evidence = ", ".join(
        word
        for score in cluster.schema_suggestion.ranked_scores
        if score.schema_name == cluster.schema_suggestion.schema_name
        for word in score.evidence
    ) or "none"
    text = (
        f"TEMPLATE\n{cluster.template}\n\n"
        f"REPRESENTATIVE EVENTS\n{samples}\n\n"
        f"PARAMETER SLOTS\n{slots}\n\n"
        f"BASELINE SUGGESTION\n{cluster.schema_suggestion.schema_name} "
        f"({cluster.schema_suggestion.confidence:.0%}); evidence: {evidence}"
    )
    return ReviewTask(
        id=cluster.cluster_id,
        text=text,
        cluster_id=cluster.cluster_id,
        template=cluster.template,
        event_count=cluster.event_count,
        suggested_schema=cluster.schema_suggestion.schema_name,
        suggestion_confidence=cluster.schema_suggestion.confidence,
        parameter_slots=[slot.model_dump(mode="json") for slot in cluster.parameter_slots],
    )


def _potato_config() -> dict[str, object]:
    parser_spec_example = json.dumps(
        {
            "parser_name": "vimAsimForgeExample",
            "vendor": "Example Vendor",
            "product": "Example Product",
            "source_table": "Syslog",
            "message_field": "SyslogMessage",
            "field_mappings": [
                {"slot_id": "p1", "asim_field": "TargetUsername", "transform": "string"}
            ],
        },
        indent=2,
    )
    return {
        "annotation_task_name": "ASIM Forge cluster review",
        "task_dir": ".",
        "data_files": ["items.jsonl"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "output_annotation_dir": "annotation_output/",
        "export_annotation_format": "jsonl",
        "require_password": False,
        "user_config": {"allow_all_users": True, "users": []},
        "login": {"type": "open"},
        "annotation_instructions": (
            "Review the cluster before approving it. The baseline is not ground truth. "
            "For approved clusters, enter a complete JSON parser specification using this shape:\n"
            f"{parser_spec_example}"
        ),
        "annotation_schemes": [
            {
                "annotation_type": "radio",
                "name": "cluster_decision",
                "description": "Is this cluster safe to compile?",
                "labels": ["approved", "needs_split", "rejected", "insufficient_evidence"],
                "sequential_key_binding": True,
            },
            {
                "annotation_type": "radio",
                "name": "asim_schema",
                "description": "Which ASIM schema best represents the cluster?",
                "labels": ["Authentication", "NetworkSession", "AuditEvent"],
                "sequential_key_binding": True,
            },
            {
                "annotation_type": "text",
                "name": "parser_spec",
                "description": "Approved parser metadata and slot mappings as JSON.",
                "multiline": True,
                "rows": 12,
                "cols": 100,
            },
            {
                "annotation_type": "text",
                "name": "review_notes",
                "description": "Explain corrections, ambiguities, or rejection reasons.",
                "multiline": True,
                "rows": 4,
                "cols": 100,
            },
        ],
    }


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
