"""Typed contracts for blinded semantic annotation and promotion artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from ..evaluation import EvaluationError, ExpectedSemanticMapping
from ..evaluation_splits import GroupStrategy
from ..models import StrictModel
from ..semantic_mapping.types import (
    Identifier,
    NonBlankText,
    SemanticMappingInput,
    SemanticSourceMetadata,
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CommitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
DecisionKind = Literal["annotation", "adjudication"]
QueueGroupStrategy = Literal["source", "source-family"]

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
