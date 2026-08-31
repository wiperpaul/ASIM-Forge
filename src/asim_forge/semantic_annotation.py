"""Blinded annotation queues and promotion into semantic evaluation gold."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .evaluation import (
    EvaluationError,
    EvaluationProvenance,
    ExpectedSemanticMapping,
    SemanticMappingCase,
    load_semantic_mapping_cases,
    write_semantic_mapping_cases,
)
from .evaluation_splits import (
    GroupStrategy,
    SemanticCaseGroup,
    load_semantic_case_groups,
    write_semantic_case_groups,
)
from .models import (
    AsimCatalog,
    AsimCatalogField,
    BuildManifest,
    ClusterRecord,
    ReviewDecision,
    SourceEvent,
    StrictModel,
)
from .reviews import ReviewError, load_review_decisions
from .semantic_mapping.types import (
    Identifier,
    NonBlankText,
    SemanticMappingInput,
    SemanticSourceMetadata,
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CommitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
DecisionKind = Literal["annotation", "adjudication"]
QueueGroupStrategy = Literal["source", "source-family"]
ModelT = TypeVar("ModelT", bound=BaseModel)

ANNOTATION_PROTOCOL_REVISION = "semantic-pilot.v1"

TASKS_FILE = "tasks.jsonl"
QUEUE_MANIFEST_FILE = "queue-manifest.json"
SUBMISSION_SCHEMA_FILE = "submission-schema.json"
CASES_FILE = "cases.jsonl"
CASE_GROUPS_FILE = "case-groups.jsonl"
PROMOTION_MANIFEST_FILE = "promotion-manifest.json"


class SemanticAnnotationError(EvaluationError):
    """Raised when annotation evidence cannot safely become evaluation gold."""


class SemanticAnnotationTaskProvenance(StrictModel):
    """Frozen clustering and cluster-review evidence behind an annotation task."""

    build_manifest_ref: NonBlankText
    build_manifest_sha256: Sha256
    cluster_ref: NonBlankText
    cluster_file_sha256: Sha256
    cluster_review_ref: NonBlankText
    review_file_sha256: Sha256
    reviewer_ref: NonBlankText
    clustering_engine: NonBlankText
    clustering_engine_revision: NonBlankText


class SemanticAnnotationTask(StrictModel):
    """Unlabelled, provider-neutral input for semantic annotation."""

    format_version: Literal["1"] = "1"
    protocol_revision: Literal["semantic-pilot.v1"] = ANNOTATION_PROTOCOL_REVISION
    case_id: Identifier
    catalogue_revision: CommitSha
    group_id: Identifier
    group_strategy: GroupStrategy
    input_fingerprint: Sha256
    task_revision: Sha256
    input: SemanticMappingInput
    provenance: SemanticAnnotationTaskProvenance

    @model_validator(mode="after")
    def fingerprint_must_match_input(self) -> SemanticAnnotationTask:
        if self.case_id != self.input.cluster_id:
            raise ValueError("case_id must match the semantic mapping input cluster_id")
        expected = semantic_input_fingerprint(self.input)
        if self.input_fingerprint != expected:
            raise ValueError("input_fingerprint does not match the semantic mapping input")
        expected_revision = semantic_task_revision(
            case_id=self.case_id,
            catalogue_revision=self.catalogue_revision,
            group_id=self.group_id,
            group_strategy=self.group_strategy,
            input_fingerprint=self.input_fingerprint,
            provenance=self.provenance,
            protocol_revision=self.protocol_revision,
        )
        if self.task_revision != expected_revision:
            raise ValueError("task_revision does not match the frozen task metadata")
        return self


class SemanticAnnotationDecision(StrictModel):
    """A completed independent annotation or an explicit adjudication."""

    format_version: Literal["1"] = "1"
    decision_id: Identifier
    decision_kind: DecisionKind
    case_id: Identifier
    catalogue_revision: CommitSha
    input_fingerprint: Sha256
    task_revision: Sha256
    reviewer_ref: NonBlankText
    expected: ExpectedSemanticMapping
    source_decision_refs: list[Identifier] = Field(default_factory=list)
    notes: str = ""

    @field_validator("source_decision_refs")
    @classmethod
    def source_decision_refs_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("source decision references must be unique")
        return values

    @model_validator(mode="after")
    def decision_kind_must_match_references(self) -> SemanticAnnotationDecision:
        if self.decision_kind == "annotation" and self.source_decision_refs:
            raise ValueError("annotations cannot reference source decisions")
        if self.decision_kind == "adjudication" and len(self.source_decision_refs) < 2:
            raise ValueError("adjudication requires at least two source decisions")
        return self


class SemanticAnnotationQueueManifest(StrictModel):
    """Deterministic summary of one build/review queue export."""

    format_version: Literal["1"] = "1"
    protocol_revision: Literal["semantic-pilot.v1"] = ANNOTATION_PROTOCOL_REVISION
    catalogue_revision: CommitSha
    group_id: Identifier
    group_strategy: GroupStrategy
    source_metadata: SemanticSourceMetadata
    build_manifest_sha256: Sha256
    cluster_file_sha256: Sha256
    review_file_sha256: Sha256
    submission_schema_sha256: Sha256
    tasks_sha256: Sha256
    cluster_count: int = Field(ge=1)
    review_count: int = Field(ge=1)
    task_count: int = Field(ge=1)
    unreviewed_cluster_count: int = Field(ge=0)
    review_status_counts: dict[str, int]
    outputs: dict[str, str]


class SemanticAnnotationPromotionManifest(StrictModel):
    """Summary and grouping join for a semantic-gold promotion."""

    format_version: Literal["1"] = "1"
    protocol_revision: Literal["semantic-pilot.v1"] = ANNOTATION_PROTOCOL_REVISION
    catalogue_revision: CommitSha
    task_count: int = Field(ge=1)
    decision_count: int = Field(ge=1)
    promoted_count: int = Field(ge=1)
    label_source_counts: dict[str, int]
    skipped_tasks: dict[str, int]
    cases_sha256: Sha256
    case_groups_sha256: Sha256
    decisions_sha256: Sha256
    queue_manifest_sha256: Sha256
    tasks_sha256: Sha256
    outputs: dict[str, str]


def semantic_input_fingerprint(mapping_input: SemanticMappingInput) -> str:
    """Hash the complete approach-visible input using canonical JSON."""
    payload = json.dumps(
        mapping_input.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def semantic_task_revision(
    *,
    case_id: str,
    catalogue_revision: str,
    group_id: str,
    group_strategy: GroupStrategy,
    input_fingerprint: str,
    provenance: SemanticAnnotationTaskProvenance,
    protocol_revision: str = ANNOTATION_PROTOCOL_REVISION,
) -> str:
    """Bind a submission to its evidence, provenance, catalogue, and group."""
    payload = json.dumps(
        {
            "case_id": case_id,
            "catalogue_revision": catalogue_revision,
            "format_version": "1",
            "group_id": group_id,
            "group_strategy": group_strategy,
            "input_fingerprint": input_fingerprint,
            "protocol_revision": protocol_revision,
            "provenance": provenance.model_dump(mode="json"),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def promote_semantic_annotations(
    queue_dir: Path,
    decisions_path: Path,
    output_dir: Path,
    catalog: AsimCatalog,
    *,
    allow_single_review: bool = False,
) -> SemanticAnnotationPromotionManifest:
    """Promote completed annotations, preserving group metadata outside gold cases."""
    queue_manifest_path = queue_dir / QUEUE_MANIFEST_FILE
    queue_manifest = _load_queue_manifest(queue_manifest_path)
    tasks_path = _queue_output_path(queue_dir, queue_manifest, "tasks")
    schema_path = _queue_output_path(queue_dir, queue_manifest, "submission_schema")
    if _sha256_file(tasks_path) != queue_manifest.tasks_sha256:
        raise SemanticAnnotationError("Annotation tasks do not match queue-manifest.json")
    if _sha256_file(schema_path) != queue_manifest.submission_schema_sha256:
        raise SemanticAnnotationError("Submission schema does not match queue-manifest.json")
    tasks = load_semantic_annotation_tasks(tasks_path)
    _validate_queue_contents(tasks, queue_manifest)
    decisions = load_semantic_annotation_decisions(decisions_path)
    catalogue_revision = catalog.manifest.resolved_revision
    _validate_catalogue_revisions(tasks, decisions, catalogue_revision)
    task_by_id = {task.case_id: task for task in tasks}
    _validate_decisions(decisions, task_by_id, catalog)

    annotations_by_case: dict[str, list[SemanticAnnotationDecision]] = {}
    adjudication_by_case: dict[str, SemanticAnnotationDecision] = {}
    decision_by_id = {decision.decision_id: decision for decision in decisions}
    for decision in decisions:
        if decision.decision_kind == "annotation":
            annotations_by_case.setdefault(decision.case_id, []).append(decision)
        elif decision.case_id in adjudication_by_case:
            raise SemanticAnnotationError(
                f"Case {decision.case_id!r} has more than one adjudication decision"
            )
        else:
            adjudication_by_case[decision.case_id] = decision

    _validate_adjudications(adjudication_by_case.values(), decision_by_id)
    _reject_duplicate_reviewers(annotations_by_case)

    cases: list[SemanticMappingCase] = []
    groups: list[SemanticCaseGroup] = []
    skipped: Counter[str] = Counter()
    label_sources: Counter[str] = Counter()
    for task in sorted(tasks, key=lambda item: item.case_id):
        source_decisions: list[SemanticAnnotationDecision] = []
        selected = adjudication_by_case.get(task.case_id)
        label_source: Literal["human_review", "adjudicated"]
        if selected is not None:
            label_source = "adjudicated"
            source_decisions = [decision_by_id[ref] for ref in selected.source_decision_refs]
        else:
            annotations = annotations_by_case.get(task.case_id, [])
            if not annotations:
                skipped["unsubmitted"] += 1
                continue
            if not allow_single_review or len(annotations) != 1:
                skipped["awaiting_adjudication"] += 1
                continue
            selected = annotations[0]
            label_source = "human_review"

        decision_refs = [decision.decision_id for decision in source_decisions]
        if selected.decision_id not in decision_refs:
            decision_refs.append(selected.decision_id)
        annotator_refs = sorted(
            {selected.reviewer_ref, *(decision.reviewer_ref for decision in source_decisions)}
        )
        case = SemanticMappingCase(
            case_id=task.case_id,
            catalogue_revision=task.catalogue_revision,
            input=task.input,
            expected=selected.expected,
            provenance=EvaluationProvenance(
                label_source=label_source,
                decision_refs=decision_refs,
                annotator_refs=annotator_refs,
                notes=selected.notes,
            ),
        )
        cases.append(case)
        groups.append(
            SemanticCaseGroup(
                case_id=task.case_id,
                group_id=task.group_id,
                group_strategy=task.group_strategy,
            )
        )
        label_sources[label_source] += 1

    if not cases:
        raise SemanticAnnotationError(
            "No decisions are eligible for promotion; complete adjudication or use "
            "--allow-single-review for provisional human-review cases"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    cases_path = output_dir / CASES_FILE
    groups_path = output_dir / CASE_GROUPS_FILE
    write_semantic_mapping_cases(cases_path, cases)
    write_semantic_case_groups(groups_path, groups)
    promotion_manifest = SemanticAnnotationPromotionManifest(
        catalogue_revision=catalogue_revision,
        protocol_revision=queue_manifest.protocol_revision,
        task_count=len(tasks),
        decision_count=len(decisions),
        promoted_count=len(cases),
        label_source_counts=dict(sorted(label_sources.items())),
        skipped_tasks=dict(sorted(skipped.items())),
        cases_sha256=_sha256_file(cases_path),
        case_groups_sha256=_sha256_file(groups_path),
        decisions_sha256=_sha256_file(decisions_path),
        queue_manifest_sha256=_sha256_file(queue_manifest_path),
        tasks_sha256=queue_manifest.tasks_sha256,
        outputs={"case_groups": CASE_GROUPS_FILE, "cases": CASES_FILE},
    )
    _write_json(
        output_dir / PROMOTION_MANIFEST_FILE,
        promotion_manifest.model_dump(mode="json"),
    )
    return promotion_manifest


def _load_queue_manifest(path: Path) -> SemanticAnnotationQueueManifest:
    if not path.is_file():
        raise SemanticAnnotationError(f"Queue manifest does not exist: {path}")
    try:
        return SemanticAnnotationQueueManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError, ValueError) as error:
        raise SemanticAnnotationError(f"Invalid queue manifest {path}: {error}") from error


def validate_semantic_promotion_artifacts(
    cases_path: Path,
    case_groups_path: Path,
    manifest_path: Path,
) -> list[SemanticCaseGroup]:
    """Verify promoted cases and frozen groups against their promotion manifest."""
    if not manifest_path.is_file():
        raise SemanticAnnotationError(f"Promotion manifest does not exist: {manifest_path}")
    try:
        manifest = SemanticAnnotationPromotionManifest.model_validate_json(
            manifest_path.read_bytes()
        )
    except (OSError, ValidationError, ValueError) as error:
        raise SemanticAnnotationError(
            f"Invalid promotion manifest {manifest_path}: {error}"
        ) from error
    expected_cases = _promotion_output_path(manifest_path.parent, manifest, "cases")
    expected_groups = _promotion_output_path(manifest_path.parent, manifest, "case_groups")
    if cases_path.resolve() != expected_cases or case_groups_path.resolve() != expected_groups:
        raise SemanticAnnotationError(
            "Cases and case groups must be the outputs named by the promotion manifest"
        )
    if _sha256_file(cases_path) != manifest.cases_sha256:
        raise SemanticAnnotationError("Semantic cases do not match the promotion manifest")
    if _sha256_file(case_groups_path) != manifest.case_groups_sha256:
        raise SemanticAnnotationError("Semantic case groups do not match the promotion manifest")
    cases = load_semantic_mapping_cases(cases_path)
    groups = load_semantic_case_groups(case_groups_path)
    if len(cases) != manifest.promoted_count or len(groups) != manifest.promoted_count:
        raise SemanticAnnotationError("Promotion output counts do not match the manifest")
    if {case.catalogue_revision for case in cases} != {manifest.catalogue_revision}:
        raise SemanticAnnotationError("Promoted cases do not match the manifest catalogue revision")
    if {case.case_id for case in cases} != {group.case_id for group in groups}:
        raise SemanticAnnotationError("Promoted cases and case groups cover different case IDs")
    return groups


def _promotion_output_path(
    output_dir: Path,
    manifest: SemanticAnnotationPromotionManifest,
    output: str,
) -> Path:
    relative = manifest.outputs.get(output)
    if relative is None:
        raise SemanticAnnotationError(f"Promotion manifest has no {output!r} output")
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise SemanticAnnotationError(
            f"Promotion output {output!r} must be relative to its output directory"
        )
    output_root = output_dir.resolve()
    resolved = (output_root / relative_path).resolve()
    if not resolved.is_relative_to(output_root):
        raise SemanticAnnotationError(f"Promotion output {output!r} escapes its output directory")
    return resolved


def _queue_output_path(
    queue_dir: Path,
    manifest: SemanticAnnotationQueueManifest,
    output: str,
) -> Path:
    relative = manifest.outputs.get(output)
    if relative is None:
        raise SemanticAnnotationError(f"Queue manifest has no {output!r} output")
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise SemanticAnnotationError(f"Queue output {output!r} must be relative to its queue")
    queue_root = queue_dir.resolve()
    resolved = (queue_root / relative_path).resolve()
    if not resolved.is_relative_to(queue_root):
        raise SemanticAnnotationError(f"Queue output {output!r} escapes its queue directory")
    return resolved


def _validate_queue_contents(
    tasks: list[SemanticAnnotationTask], manifest: SemanticAnnotationQueueManifest
) -> None:
    if len(tasks) != manifest.task_count:
        raise SemanticAnnotationError("Queue task count does not match queue-manifest.json")
    for task in tasks:
        provenance = task.provenance
        if (
            task.protocol_revision != manifest.protocol_revision
            or task.catalogue_revision != manifest.catalogue_revision
            or task.group_id != manifest.group_id
            or task.group_strategy != manifest.group_strategy
            or task.input.source_metadata != manifest.source_metadata
            or provenance.build_manifest_sha256 != manifest.build_manifest_sha256
            or provenance.cluster_file_sha256 != manifest.cluster_file_sha256
            or provenance.review_file_sha256 != manifest.review_file_sha256
        ):
            raise SemanticAnnotationError(
                f"Task {task.case_id!r} does not match queue-manifest.json"
            )


def load_semantic_annotation_tasks(path: Path) -> list[SemanticAnnotationTask]:
    """Load a canonical task JSONL file and reject duplicate case IDs."""
    tasks = _load_jsonl(path, SemanticAnnotationTask, "semantic annotation task")
    _ensure_unique([task.case_id for task in tasks], "Semantic annotation case IDs")
    return tasks


def write_semantic_annotation_tasks(path: Path, tasks: list[SemanticAnnotationTask]) -> None:
    """Write blinded tasks in deterministic case-ID order."""
    if not tasks:
        raise SemanticAnnotationError("At least one semantic annotation task is required")
    _ensure_unique([task.case_id for task in tasks], "Semantic annotation case IDs")
    _write_jsonl(
        path,
        [task.model_dump(mode="json") for task in sorted(tasks, key=lambda item: item.case_id)],
    )


def load_semantic_annotation_decisions(path: Path) -> list[SemanticAnnotationDecision]:
    """Load typed annotation/adjudication JSONL and reject duplicate decision IDs."""
    decisions = _load_jsonl(path, SemanticAnnotationDecision, "semantic annotation decision")
    _ensure_unique([decision.decision_id for decision in decisions], "Annotation decision IDs")
    return decisions


def write_semantic_annotation_decisions(
    path: Path, decisions: list[SemanticAnnotationDecision]
) -> None:
    """Write typed decisions in deterministic decision-ID order."""
    if not decisions:
        raise SemanticAnnotationError("At least one semantic annotation decision is required")
    _ensure_unique([decision.decision_id for decision in decisions], "Annotation decision IDs")
    _write_jsonl(
        path,
        [
            decision.model_dump(mode="json")
            for decision in sorted(decisions, key=lambda item: item.decision_id)
        ],
    )


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


def _validate_catalogue_revisions(
    tasks: list[SemanticAnnotationTask],
    decisions: list[SemanticAnnotationDecision],
    catalogue_revision: str,
) -> None:
    task_revisions = {task.catalogue_revision for task in tasks}
    if task_revisions != {catalogue_revision}:
        raise SemanticAnnotationError(
            "Annotation tasks do not match the loaded catalogue revision; "
            f"tasks={sorted(task_revisions)}, catalog={catalogue_revision}"
        )
    decision_revisions = {decision.catalogue_revision for decision in decisions}
    if decision_revisions != {catalogue_revision}:
        raise SemanticAnnotationError(
            "Annotation decisions do not match the loaded catalogue revision; "
            f"decisions={sorted(decision_revisions)}, catalog={catalogue_revision}"
        )


def _validate_decisions(
    decisions: list[SemanticAnnotationDecision],
    task_by_id: dict[str, SemanticAnnotationTask],
    catalog: AsimCatalog,
) -> None:
    for decision in decisions:
        task = task_by_id.get(decision.case_id)
        if task is None:
            raise SemanticAnnotationError(
                f"Decision {decision.decision_id!r} references unknown case {decision.case_id!r}"
            )
        if decision.input_fingerprint != task.input_fingerprint:
            raise SemanticAnnotationError(
                f"Decision {decision.decision_id!r} is stale for case {decision.case_id!r}"
            )
        if decision.task_revision != task.task_revision:
            raise SemanticAnnotationError(
                f"Decision {decision.decision_id!r} has a stale task revision for "
                f"case {decision.case_id!r}"
            )
        _validate_expected_against_catalog(decision, catalog)
        try:
            SemanticMappingCase(
                case_id=task.case_id,
                catalogue_revision=task.catalogue_revision,
                input=task.input,
                expected=decision.expected,
                provenance=EvaluationProvenance(
                    label_source="human_review",
                    decision_refs=[decision.decision_id],
                    annotator_refs=[decision.reviewer_ref],
                ),
            )
        except ValueError as error:
            raise SemanticAnnotationError(
                f"Decision {decision.decision_id!r} does not resolve against its task: {error}"
            ) from error


def _validate_expected_against_catalog(
    decision: SemanticAnnotationDecision, catalog: AsimCatalog
) -> None:
    expected = decision.expected
    if expected.asim_fields and expected.schema_name is None:
        raise SemanticAnnotationError(
            f"Decision {decision.decision_id!r} has ASIM fields without a schema"
        )
    if expected.schema_name is None:
        return
    if expected.schema_name not in catalog.manifest.schemas:
        raise SemanticAnnotationError(
            f"Decision {decision.decision_id!r} uses unknown ASIM schema {expected.schema_name!r}"
        )
    fields_by_name = {
        field.name: field for field in catalog.fields_for_schema(expected.schema_name)
    }
    unknown_fields = sorted(
        {field.asim_field for field in expected.asim_fields} - fields_by_name.keys()
    )
    if unknown_fields:
        raise SemanticAnnotationError(
            f"Decision {decision.decision_id!r} maps unknown fields for "
            f"{expected.schema_name}: {unknown_fields}"
        )
    for expected_field in expected.asim_fields:
        if expected_field.constant_value is not None:
            _validate_constant_value(
                decision.decision_id,
                expected_field.asim_field,
                expected_field.constant_value,
                fields_by_name[expected_field.asim_field],
            )


def _validate_constant_value(
    decision_id: str,
    field_name: str,
    value: str | int | float | bool,
    catalog_field: AsimCatalogField,
) -> None:
    kql_type = catalog_field.kql_type.casefold()
    if kql_type in {"string", "datetime", "dynamic"}:
        type_matches = isinstance(value, str)
    elif kql_type == "bool":
        type_matches = isinstance(value, bool)
    elif kql_type in {"int", "long"}:
        type_matches = isinstance(value, int) and not isinstance(value, bool)
    elif kql_type in {"real", "double"}:
        type_matches = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        type_matches = False
    if not type_matches:
        raise SemanticAnnotationError(
            f"Decision {decision_id!r} uses a constant incompatible with "
            f"{field_name} ({catalog_field.kql_type})"
        )
    if catalog_field.allowed_values and str(value) not in catalog_field.allowed_values:
        raise SemanticAnnotationError(
            f"Decision {decision_id!r} uses constant {value!r} outside the allowed "
            f"values for {field_name}: {catalog_field.allowed_values}"
        )


def _reject_duplicate_reviewers(
    annotations_by_case: dict[str, list[SemanticAnnotationDecision]],
) -> None:
    for case_id, case_annotations in annotations_by_case.items():
        counts = Counter(annotation.reviewer_ref for annotation in case_annotations)
        duplicates = sorted(reviewer for reviewer, count in counts.items() if count > 1)
        if duplicates:
            raise SemanticAnnotationError(
                f"Case {case_id!r} has multiple annotations from the same reviewer: {duplicates}"
            )


def _validate_adjudications(
    adjudications: Iterable[SemanticAnnotationDecision],
    decision_by_id: dict[str, SemanticAnnotationDecision],
) -> None:
    for adjudication in adjudications:
        sources: list[SemanticAnnotationDecision] = []
        for reference in adjudication.source_decision_refs:
            source = decision_by_id.get(reference)
            if source is None:
                raise SemanticAnnotationError(
                    f"Adjudication {adjudication.decision_id!r} references unknown decision "
                    f"{reference!r}"
                )
            if source.decision_kind != "annotation":
                raise SemanticAnnotationError(
                    f"Adjudication {adjudication.decision_id!r} can reference annotations only"
                )
            if (
                source.case_id != adjudication.case_id
                or source.catalogue_revision != adjudication.catalogue_revision
                or source.input_fingerprint != adjudication.input_fingerprint
                or source.task_revision != adjudication.task_revision
            ):
                raise SemanticAnnotationError(
                    f"Adjudication {adjudication.decision_id!r} references a decision from "
                    "another case or revision"
                )
            sources.append(source)
        if len({source.reviewer_ref for source in sources}) < 2:
            raise SemanticAnnotationError(
                f"Adjudication {adjudication.decision_id!r} requires two independent reviewers"
            )


def _load_jsonl(path: Path, model: type[ModelT], description: str) -> list[ModelT]:
    if not path.is_file():
        raise SemanticAnnotationError(f"{description.capitalize()} file does not exist: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise SemanticAnnotationError(
            f"Could not read {description} file {path}: {error}"
        ) from error
    records: list[ModelT] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(model.model_validate_json(line))
        except (ValidationError, ValueError) as error:
            raise SemanticAnnotationError(
                f"Invalid {description} on line {line_number} of {path}: {error}"
            ) from error
    if not records:
        raise SemanticAnnotationError(f"No {description}s found in {path}")
    return records


def _ensure_unique(values: list[str], label: str) -> None:
    counts = Counter(values)
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    if duplicates:
        raise SemanticAnnotationError(f"{label} must be unique: {duplicates}")


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise SemanticAnnotationError(f"Could not hash {path}: {error}") from error


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        for record in records
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _write_json(path: Path, record: dict[str, object]) -> None:
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
