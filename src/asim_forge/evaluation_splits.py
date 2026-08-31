"""Leakage-resistant grouped splits for semantic mapping evaluation."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from .evaluation import EvaluationError, SemanticMappingCase
from .models import StrictModel
from .semantic_mapping.types import Identifier

DatasetPartition = Literal["train", "validation", "test"]
EvaluationPartition = Literal["validation", "test"]
GroupStrategy = Literal["source", "source-family", "template-family", "manual"]


def _default_reference_partitions() -> list[DatasetPartition]:
    return ["train"]


class SemanticSplitEntry(StrictModel):
    case_id: Identifier
    group_id: Identifier
    partition: DatasetPartition


class SemanticCaseGroup(StrictModel):
    """Pre-label group assignment retained outside semantic gold cases."""

    case_id: Identifier
    group_id: Identifier
    group_strategy: GroupStrategy


class SemanticDatasetSplit(StrictModel):
    """External split metadata kept separate from provider-neutral gold cases."""

    format_version: Literal["1"] = "1"
    split_id: Identifier
    catalogue_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    group_strategy: GroupStrategy
    reference_partitions: list[DatasetPartition] = Field(
        default_factory=_default_reference_partitions
    )
    entries: list[SemanticSplitEntry] = Field(min_length=1)

    @field_validator("reference_partitions")
    @classmethod
    def reference_partitions_must_be_unique(
        cls, values: list[DatasetPartition]
    ) -> list[DatasetPartition]:
        if not values:
            raise ValueError("at least one reference partition is required")
        if len(values) != len(set(values)):
            raise ValueError("reference partitions must be unique")
        return values

    @model_validator(mode="after")
    def entries_must_be_disjoint(self) -> SemanticDatasetSplit:
        case_ids = [entry.case_id for entry in self.entries]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("split case IDs must be unique")
        group_partitions: dict[str, set[str]] = {}
        for entry in self.entries:
            group_partitions.setdefault(entry.group_id, set()).add(entry.partition)
        leaked = sorted(
            group_id for group_id, partitions in group_partitions.items() if len(partitions) > 1
        )
        if leaked:
            raise ValueError(f"groups cannot cross partitions: {leaked}")
        return self


class SemanticSplitSelection(StrictModel):
    split_id: Identifier
    evaluation_partition: EvaluationPartition
    reference_cases: list[SemanticMappingCase] = Field(min_length=1)
    evaluation_cases: list[SemanticMappingCase] = Field(min_length=1)


def load_semantic_dataset_split(path: Path) -> SemanticDatasetSplit:
    if not path.is_file():
        raise EvaluationError(f"Semantic dataset split does not exist: {path}")
    try:
        return SemanticDatasetSplit.model_validate_json(path.read_bytes())
    except (ValidationError, ValueError) as error:
        raise EvaluationError(f"Invalid semantic dataset split {path}: {error}") from error


def load_semantic_case_groups(path: Path) -> list[SemanticCaseGroup]:
    """Load canonical pre-label group assignments from JSONL."""
    if not path.is_file():
        raise EvaluationError(f"Semantic case-group file does not exist: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise EvaluationError(f"Could not read semantic case groups {path}: {error}") from error
    groups: list[SemanticCaseGroup] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            groups.append(SemanticCaseGroup.model_validate_json(line))
        except (ValidationError, ValueError) as error:
            raise EvaluationError(
                f"Invalid semantic case group on line {line_number} of {path}: {error}"
            ) from error
    if not groups:
        raise EvaluationError(f"No semantic case groups found in {path}")
    case_ids = [group.case_id for group in groups]
    duplicates = sorted(case_id for case_id, count in Counter(case_ids).items() if count > 1)
    if duplicates:
        raise EvaluationError(f"Semantic case-group IDs must be unique: {duplicates}")
    return groups


def write_semantic_case_groups(path: Path, groups: list[SemanticCaseGroup]) -> None:
    """Write deterministic pre-label group assignments."""
    if not groups:
        raise EvaluationError("At least one semantic case group is required")
    case_ids = [group.case_id for group in groups]
    duplicates = sorted(case_id for case_id, count in Counter(case_ids).items() if count > 1)
    if duplicates:
        raise EvaluationError(f"Semantic case-group IDs must be unique: {duplicates}")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(group.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
        for group in sorted(groups, key=lambda item: item.case_id)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def validate_semantic_dataset_split(
    cases: list[SemanticMappingCase], split: SemanticDatasetSplit
) -> dict[str, int]:
    """Validate exact case coverage and catalogue compatibility."""
    if not cases:
        raise EvaluationError("At least one semantic mapping case is required")
    case_ids = {case.case_id for case in cases}
    entry_ids = {entry.case_id for entry in split.entries}
    missing = sorted(case_ids - entry_ids)
    unknown = sorted(entry_ids - case_ids)
    if missing or unknown:
        raise EvaluationError(
            f"Split must cover the case set exactly; missing={missing}, unknown={unknown}"
        )
    revisions = {case.catalogue_revision for case in cases}
    if revisions != {split.catalogue_revision}:
        raise EvaluationError(
            "Split and cases must use one catalogue revision; "
            f"cases={sorted(revisions)}, split={split.catalogue_revision}"
        )
    return dict(sorted(Counter(entry.partition for entry in split.entries).items()))


def validate_semantic_case_groups(
    cases: list[SemanticMappingCase],
    split: SemanticDatasetSplit,
    groups: list[SemanticCaseGroup],
) -> None:
    """Require split groups to match the assignments frozen before labelling."""
    validate_semantic_dataset_split(cases, split)
    case_ids = {case.case_id for case in cases}
    group_ids = {group.case_id for group in groups}
    missing = sorted(case_ids - group_ids)
    unknown = sorted(group_ids - case_ids)
    if missing or unknown:
        raise EvaluationError(
            f"Case groups must cover the case set exactly; missing={missing}, unknown={unknown}"
        )
    strategies = {group.group_strategy for group in groups}
    if strategies != {split.group_strategy}:
        raise EvaluationError(
            "Case-group and split strategies differ; "
            f"groups={sorted(strategies)}, split={split.group_strategy}"
        )
    frozen_by_id = {group.case_id: group.group_id for group in groups}
    changed = sorted(
        entry.case_id for entry in split.entries if entry.group_id != frozen_by_id[entry.case_id]
    )
    if changed:
        raise EvaluationError(f"Split changes frozen case groups: {changed}")


def select_semantic_split(
    cases: list[SemanticMappingCase],
    split: SemanticDatasetSplit,
    evaluation_partition: EvaluationPartition,
) -> SemanticSplitSelection:
    counts = validate_semantic_dataset_split(cases, split)
    if evaluation_partition in split.reference_partitions:
        raise EvaluationError(
            f"Evaluation partition {evaluation_partition!r} is also a reference partition"
        )
    if counts.get(evaluation_partition, 0) == 0:
        raise EvaluationError(f"Split has no {evaluation_partition!r} evaluation cases")
    if not any(counts.get(partition, 0) for partition in split.reference_partitions):
        raise EvaluationError("Split has no cases in its reference partitions")

    partition_by_id = {entry.case_id: entry.partition for entry in split.entries}
    references = [
        case for case in cases if partition_by_id[case.case_id] in split.reference_partitions
    ]
    evaluation = [case for case in cases if partition_by_id[case.case_id] == evaluation_partition]
    return SemanticSplitSelection(
        split_id=split.split_id,
        evaluation_partition=evaluation_partition,
        reference_cases=references,
        evaluation_cases=evaluation,
    )
