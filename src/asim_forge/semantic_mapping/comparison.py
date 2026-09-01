"""Run and report comparisons across registered semantic mapping approaches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..evaluation import SemanticMappingCase
from ..evaluation_splits import (
    EvaluationPartition,
    SemanticDatasetSplit,
    select_semantic_split,
)
from ..models import AsimCatalog, StrictModel
from .approaches import APPROACH_NAMES, PRIOR_APPROACH_NAMES, build_approach
from .contracts import (
    ApproachIdentity,
    MappingRequest,
    SemanticMappingPrediction,
)
from .metrics import EvaluationError, EvaluationMetrics, evaluate_predictions

OracleCondition = Literal["none", "schema"]


class ComparisonError(EvaluationError):
    """Raised when approaches cannot be compared fairly."""


class ApproachEvaluation(StrictModel):
    approach: ApproachIdentity
    metrics: EvaluationMetrics
    predictions: list[SemanticMappingPrediction] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class ComparisonReport(StrictModel):
    format_version: Literal["1"] = "1"
    catalogue_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    case_count: int = Field(ge=1)
    reference_case_count: int = Field(default=0, ge=0)
    split_id: str | None = None
    evaluation_partition: EvaluationPartition | None = None
    oracle: OracleCondition = "none"
    approaches: list[ApproachEvaluation] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


def compare_approaches(
    cases: list[SemanticMappingCase],
    catalog: AsimCatalog,
    approach_names: list[str] | None = None,
    *,
    reference_cases: list[SemanticMappingCase] | None = None,
    split_id: str | None = None,
    evaluation_partition: EvaluationPartition | None = None,
    oracle: OracleCondition = "none",
) -> ComparisonReport:
    """Evaluate registered approaches against the same cases and catalogue."""
    if not cases:
        raise ComparisonError("At least one semantic mapping case is required")
    names = list(APPROACH_NAMES if approach_names is None else approach_names)
    if not names:
        raise ComparisonError("At least one semantic mapping approach is required")
    unknown = sorted(set(names) - set(APPROACH_NAMES))
    if unknown:
        raise ComparisonError(f"Unknown semantic mapping approaches: {unknown}")
    if len(names) != len(set(names)):
        raise ComparisonError("Semantic mapping approach names must be unique")

    references = cases if reference_cases is None else reference_cases
    if reference_cases is not None:
        overlap = sorted({case.case_id for case in cases} & {case.case_id for case in references})
        if overlap:
            raise ComparisonError(f"Reference and evaluation case IDs must be disjoint: {overlap}")
    revisions = {case.catalogue_revision for case in [*cases, *references]}
    if revisions != {catalog.manifest.resolved_revision}:
        raise ComparisonError(
            "Every case must use the loaded catalogue revision; "
            f"cases={sorted(revisions)}, catalogue={catalog.manifest.resolved_revision}"
        )

    evaluations: list[ApproachEvaluation] = []
    for name in names:
        approach = build_approach(name, reference_cases=references)
        predictions: list[SemanticMappingPrediction] = []
        for case in cases:
            predictions.append(
                approach.predict(
                    MappingRequest(
                        case_id=case.case_id,
                        catalogue_revision=case.catalogue_revision,
                        input=case.input,
                        schema_hint=case.expected.schema_name if oracle == "schema" else None,
                    ),
                    catalog,
                )
            )
        evaluations.append(
            ApproachEvaluation(
                approach=predictions[0].approach,
                metrics=evaluate_predictions(cases, predictions),
                predictions=predictions,
                warnings=_evaluation_warnings(
                    cases,
                    predictions,
                    has_grouped_split=reference_cases is not None,
                    oracle=oracle,
                ),
            )
        )

    return ComparisonReport(
        catalogue_revision=catalog.manifest.resolved_revision,
        case_count=len(cases),
        reference_case_count=len(references),
        split_id=split_id,
        evaluation_partition=evaluation_partition,
        oracle=oracle,
        approaches=evaluations,
        warnings=_floor_warnings(evaluations),
    )


def compare_split_approaches(
    cases: list[SemanticMappingCase],
    catalog: AsimCatalog,
    split: SemanticDatasetSplit,
    evaluation_partition: EvaluationPartition = "test",
    approach_names: list[str] | None = None,
    *,
    oracle: OracleCondition = "none",
) -> ComparisonReport:
    selection = select_semantic_split(cases, split, evaluation_partition)
    return compare_approaches(
        selection.evaluation_cases,
        catalog,
        approach_names,
        reference_cases=selection.reference_cases,
        split_id=selection.split_id,
        evaluation_partition=selection.evaluation_partition,
        oracle=oracle,
    )


def write_comparison_report(path: Path, report: ComparisonReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _evaluation_warnings(
    cases: list[SemanticMappingCase],
    predictions: list[SemanticMappingPrediction],
    *,
    has_grouped_split: bool,
    oracle: OracleCondition = "none",
) -> list[str]:
    warnings: list[str] = []
    if oracle != "none":
        warnings.append(
            f"{oracle} oracle condition: an error-decomposition diagnostic, not approach accuracy."
        )
    if len(cases) < 20:
        warnings.append("Fewer than 20 cases: results are a harness smoke test, not evidence.")
    systems = {case.input.source_metadata.system for case in cases}
    if len(systems) < 2:
        warnings.append("Only one source system: distribution shift is not measured.")
    if any(case.provenance.label_source == "synthetic" for case in cases):
        warnings.append(
            "Synthetic labels are present: do not report results as production accuracy."
        )
    if not has_grouped_split and predictions[0].approach.name == "case-retrieval":
        warnings.append("No explicit grouped split: retrieval results are not comparison evidence.")
    if not any(prediction.disposition == "mapped" for prediction in predictions):
        warnings.append("Approach produced no mapped predictions for this case set.")
    return warnings


def _floor_warnings(evaluations: list[ApproachEvaluation]) -> list[str]:
    """Name approaches that fail to beat the priors, so no score is read on its own."""
    priors = [
        evaluation for evaluation in evaluations if evaluation.approach.name in PRIOR_APPROACH_NAMES
    ]
    others = [
        evaluation
        for evaluation in evaluations
        if evaluation.approach.name not in PRIOR_APPROACH_NAMES
    ]
    if not priors:
        return ["No prior was evaluated: reported scores have no floor to be read against."]
    if not others:
        return []
    floor = max(prior.metrics.field_micro_f1 for prior in priors)
    failed = sorted(
        evaluation.approach.name
        for evaluation in others
        if evaluation.metrics.field_micro_f1 <= floor
    )
    if not failed:
        return []
    return [
        f"At or below the prior field micro F1 floor {floor:.3f}: {', '.join(failed)}.",
    ]
