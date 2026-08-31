"""Build blinded semantic annotation queues from reviewed parser clusters."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from ..models import (
    AsimCatalog,
    BuildManifest,
    ClusterRecord,
    ReviewDecision,
    SourceEvent,
)
from ..reviews import ReviewError, load_review_decisions
from ..semantic_mapping.types import SemanticMappingInput, SemanticSourceMetadata
from .artifacts import (
    _ensure_unique,
    _sha256_file,
    _write_json,
    write_semantic_annotation_tasks,
)
from .contracts import (
    ANNOTATION_PROTOCOL_REVISION,
    QUEUE_MANIFEST_FILE,
    SUBMISSION_SCHEMA_FILE,
    TASKS_FILE,
    QueueGroupStrategy,
    SemanticAnnotationDecision,
    SemanticAnnotationError,
    SemanticAnnotationQueueManifest,
    SemanticAnnotationTask,
    SemanticAnnotationTaskProvenance,
    semantic_input_fingerprint,
    semantic_task_revision,
)


def _blind_source_event_refs(events: list[SourceEvent]) -> list[SourceEvent]:
    """Replace potentially label-bearing corpus paths with stable neutral references."""
    source_ids = {
        source_file: f"source-{index:03d}"
        for index, source_file in enumerate(
            sorted({event.source_file for event in events}),
            start=1,
        )
    }
    return [
        event.model_copy(update={"source_file": source_ids[event.source_file]}) for event in events
    ]


def prepare_semantic_annotation_queue(
    build_dir: Path,
    reviews_path: Path,
    output_dir: Path,
    catalog: AsimCatalog,
    *,
    group_id: str,
    group_strategy: QueueGroupStrategy,
    system: str | None = None,
    vendor: str | None = None,
    product: str | None = None,
    source_table: str | None = None,
    message_field: str | None = None,
) -> SemanticAnnotationQueueManifest:
    """Export Stage 1-approved clusters as a blinded semantic annotation queue."""
    if group_strategy not in ("source", "source-family"):
        raise SemanticAnnotationError(
            "Build-level queues support source or source-family grouping; "
            "assign template/manual groups with a per-case curation workflow"
        )
    manifest_path = build_dir / "manifest.json"
    build_manifest = _load_build_manifest(manifest_path)
    clusters_path = _build_output_path(build_dir, build_manifest, "clusters")
    clusters = _load_clusters(clusters_path)
    if len(clusters) != build_manifest.cluster_count:
        raise SemanticAnnotationError(
            "Build manifest cluster_count does not match its clusters output"
        )

    decisions = load_review_decisions(reviews_path)
    _ensure_unique_review_clusters(decisions)
    cluster_by_id = {cluster.cluster_id: cluster for cluster in clusters}
    unknown_reviews = sorted(
        decision.cluster_id for decision in decisions if decision.cluster_id not in cluster_by_id
    )
    if unknown_reviews:
        raise SemanticAnnotationError(
            f"Review decisions reference unknown clusters: {unknown_reviews}"
        )

    approved = sorted(
        (decision for decision in decisions if decision.status == "approved"),
        key=lambda decision: decision.cluster_id,
    )
    if not approved:
        raise SemanticAnnotationError("No approved clusters are available for semantic annotation")

    source_metadata = SemanticSourceMetadata(
        system=system or build_manifest.system,
        vendor=vendor,
        product=product,
        source_table=source_table,
        message_field=message_field,
    )
    catalogue_revision = catalog.manifest.resolved_revision
    build_hash = _sha256_file(manifest_path)
    cluster_file_hash = _sha256_file(clusters_path)
    review_file_hash = _sha256_file(reviews_path)
    tasks: list[SemanticAnnotationTask] = []
    for decision in approved:
        cluster = cluster_by_id[decision.cluster_id]
        mapping_input = SemanticMappingInput(
            cluster_id=cluster.cluster_id,
            template=cluster.template,
            representative_events=_blind_source_event_refs(cluster.representative_events),
            parameter_slots=cluster.parameter_slots,
            source_metadata=source_metadata,
        )
        input_fingerprint = semantic_input_fingerprint(mapping_input)
        provenance = SemanticAnnotationTaskProvenance(
            build_manifest_ref=manifest_path.name,
            build_manifest_sha256=build_hash,
            cluster_ref=f"{build_manifest.outputs['clusters']}#{cluster.cluster_id}",
            cluster_file_sha256=cluster_file_hash,
            cluster_review_ref=f"{reviews_path.name}#{cluster.cluster_id}",
            review_file_sha256=review_file_hash,
            reviewer_ref=decision.reviewer,
            clustering_engine=build_manifest.engine,
            clustering_engine_revision=build_manifest.engine_revision,
        )
        tasks.append(
            SemanticAnnotationTask(
                case_id=cluster.cluster_id,
                catalogue_revision=catalogue_revision,
                group_id=group_id,
                group_strategy=group_strategy,
                input_fingerprint=input_fingerprint,
                task_revision=semantic_task_revision(
                    case_id=cluster.cluster_id,
                    catalogue_revision=catalogue_revision,
                    group_id=group_id,
                    group_strategy=group_strategy,
                    input_fingerprint=input_fingerprint,
                    provenance=provenance,
                    protocol_revision=ANNOTATION_PROTOCOL_REVISION,
                ),
                input=mapping_input,
                provenance=provenance,
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = output_dir / TASKS_FILE
    write_semantic_annotation_tasks(tasks_path, tasks)
    schema_path = output_dir / SUBMISSION_SCHEMA_FILE
    schema_path.write_text(
        json.dumps(SemanticAnnotationDecision.model_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    reviewed_ids = {decision.cluster_id for decision in decisions}
    tasks_hash = _sha256_file(tasks_path)
    submission_schema_hash = _sha256_file(schema_path)
    queue_manifest = SemanticAnnotationQueueManifest(
        catalogue_revision=catalogue_revision,
        group_id=group_id,
        group_strategy=group_strategy,
        source_metadata=source_metadata,
        build_manifest_sha256=build_hash,
        cluster_file_sha256=cluster_file_hash,
        review_file_sha256=review_file_hash,
        submission_schema_sha256=submission_schema_hash,
        tasks_sha256=tasks_hash,
        cluster_count=len(clusters),
        review_count=len(decisions),
        task_count=len(tasks),
        unreviewed_cluster_count=len(set(cluster_by_id) - reviewed_ids),
        review_status_counts=dict(sorted(Counter(d.status for d in decisions).items())),
        outputs={
            "submission_schema": SUBMISSION_SCHEMA_FILE,
            "tasks": TASKS_FILE,
        },
    )
    _write_json(output_dir / QUEUE_MANIFEST_FILE, queue_manifest.model_dump(mode="json"))
    return queue_manifest


def _load_build_manifest(path: Path) -> BuildManifest:
    if not path.is_file():
        raise SemanticAnnotationError(f"Build manifest does not exist: {path}")
    try:
        return BuildManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError, ValueError) as error:
        raise SemanticAnnotationError(f"Invalid build manifest {path}: {error}") from error


def _build_output_path(build_dir: Path, manifest: BuildManifest, output: str) -> Path:
    relative = manifest.outputs.get(output)
    if relative is None:
        raise SemanticAnnotationError(f"Build manifest has no {output!r} output")
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise SemanticAnnotationError(f"Build output {output!r} must be relative to its build")
    build_root = build_dir.resolve()
    resolved = (build_root / relative_path).resolve()
    if not resolved.is_relative_to(build_root):
        raise SemanticAnnotationError(f"Build output {output!r} escapes its build directory")
    return resolved


def _load_clusters(path: Path) -> list[ClusterRecord]:
    if not path.is_file():
        raise SemanticAnnotationError(f"Cluster file does not exist: {path}")
    clusters: list[ClusterRecord] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise SemanticAnnotationError(f"Could not read cluster file {path}: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            clusters.append(ClusterRecord.model_validate_json(line))
        except (ValidationError, ValueError) as error:
            raise SemanticAnnotationError(
                f"Invalid cluster on line {line_number} of {path}: {error}"
            ) from error
    if not clusters:
        raise SemanticAnnotationError(f"No cluster records found in {path}")
    _ensure_unique([cluster.cluster_id for cluster in clusters], "Cluster IDs")
    return clusters


def _ensure_unique_review_clusters(decisions: list[ReviewDecision]) -> None:
    counts = Counter(decision.cluster_id for decision in decisions)
    duplicates = sorted(cluster_id for cluster_id, count in counts.items() if count > 1)
    if duplicates:
        raise ReviewError(
            "One authoritative cluster decision is required per queue; duplicates: "
            + ", ".join(duplicates)
        )
