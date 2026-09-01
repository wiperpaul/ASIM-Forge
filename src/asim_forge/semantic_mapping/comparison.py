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
from .context_views import ContextView, apply_context_view
from .contracts import (
    ApproachIdentity,
    MappingRequest,
    SemanticMappingPrediction,
    SourceFrameHint,
)
from .metrics import EvaluationError, EvaluationMetrics, evaluate_predictions
from .statistics import (
    DEFAULT_RESAMPLES,
    BootstrapInterval,
    PairedApproachTest,
    RiskCoverageCurve,
    SampleAdequacy,
    bootstrap_intervals,
    describe_sample,
    paired_permutation_test,
    risk_coverage_curve,
)

OracleCondition = Literal["none", "schema", "source-frame", "schema-and-source-frame"]

ORACLE_CONDITIONS: tuple[OracleCondition, ...] = (
    "none",
    "schema",
    "source-frame",
    "schema-and-source-frame",
)


class ComparisonError(EvaluationError):
    """Raised when approaches cannot be compared fairly."""


class ApproachEvaluation(StrictModel):
    approach: ApproachIdentity
    metrics: EvaluationMetrics
    intervals: list[BootstrapInterval] = Field(default_factory=list)
    risk_coverage: RiskCoverageCurve | None = None
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
    context_view: ContextView = "full"
    sample: SampleAdequacy | None = None
    approaches: list[ApproachEvaluation] = Field(min_length=1)
    paired_tests: list[PairedApproachTest] = Field(default_factory=list)
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
    context_view: ContextView = "full",
    split: SemanticDatasetSplit | None = None,
    resamples: int = DEFAULT_RESAMPLES,
    baseline_approach: str | None = None,
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
                        input=apply_context_view(case.input, context_view),
                        schema_hint=_schema_hint(case, oracle),
                        frame_hint=_frame_hint(case, oracle),
                    ),
                    catalog,
                )
            )
        evaluations.append(
            ApproachEvaluation(
                approach=predictions[0].approach,
                metrics=evaluate_predictions(cases, predictions),
                intervals=bootstrap_intervals(cases, predictions, split=split, resamples=resamples),
                risk_coverage=risk_coverage_curve(cases, predictions),
                predictions=predictions,
                warnings=_evaluation_warnings(
                    cases,
                    predictions,
                    has_grouped_split=reference_cases is not None,
                    oracle=oracle,
                    context_view=context_view,
                ),
            )
        )

    sample = describe_sample(cases, split)
    paired_tests = _paired_tests(
        cases,
        evaluations,
        split=split,
        resamples=resamples,
        baseline_approach=baseline_approach,
    )
    return ComparisonReport(
        catalogue_revision=catalog.manifest.resolved_revision,
        case_count=len(cases),
        reference_case_count=len(references),
        split_id=split_id,
        evaluation_partition=evaluation_partition,
        oracle=oracle,
        context_view=context_view,
        sample=sample,
        approaches=evaluations,
        paired_tests=paired_tests,
        warnings=[*_floor_warnings(evaluations), *_resolution_warnings(sample, paired_tests)],
    )


def compare_split_approaches(
    cases: list[SemanticMappingCase],
    catalog: AsimCatalog,
    split: SemanticDatasetSplit,
    evaluation_partition: EvaluationPartition = "test",
    approach_names: list[str] | None = None,
    *,
    oracle: OracleCondition = "none",
    context_view: ContextView = "full",
    resamples: int = DEFAULT_RESAMPLES,
    baseline_approach: str | None = None,
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
        context_view=context_view,
        split=split,
        resamples=resamples,
        baseline_approach=baseline_approach,
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
    context_view: ContextView = "full",
) -> list[str]:
    warnings: list[str] = []
    if oracle != "none":
        warnings.append(
            f"{oracle} oracle condition: an error-decomposition diagnostic, not approach accuracy."
        )
    if context_view != "full":
        warnings.append(
            f"{context_view} context view: evidence was withheld, so this is an ablation "
            "rather than the approach's own result."
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


def _schema_hint(case: SemanticMappingCase, oracle: OracleCondition) -> str | None:
    if oracle in ("schema", "schema-and-source-frame"):
        return case.expected.schema_name
    return None


def _frame_hint(
    case: SemanticMappingCase,
    oracle: OracleCondition,
) -> list[SourceFrameHint] | None:
    if oracle not in ("source-frame", "schema-and-source-frame"):
        return None
    return [
        SourceFrameHint(
            source_kind=semantic.source_kind,
            locator=semantic.locator,
            role=semantic.role,
        )
        for semantic in case.expected.source_semantics
    ]


def _paired_tests(
    cases: list[SemanticMappingCase],
    evaluations: list[ApproachEvaluation],
    *,
    split: SemanticDatasetSplit | None,
    resamples: int,
    baseline_approach: str | None,
) -> list[PairedApproachTest]:
    """Test every approach against one baseline rather than against each other.

    All-pairs testing over a handful of approaches multiplies the false-positive
    rate on a sample already too small to support it.
    """
    if len(evaluations) < 2:
        return []
    by_name = {evaluation.approach.name: evaluation for evaluation in evaluations}
    baseline_name = baseline_approach or _default_baseline(evaluations)
    if baseline_name not in by_name:
        raise ComparisonError(
            f"Baseline approach {baseline_name!r} is not among the compared approaches"
        )
    baseline = by_name[baseline_name]
    return [
        paired_permutation_test(
            cases,
            baseline.predictions,
            evaluation.predictions,
            split=split,
            resamples=resamples,
        )
        for evaluation in evaluations
        if evaluation.approach.name != baseline_name
    ]


def _default_baseline(evaluations: list[ApproachEvaluation]) -> str:
    for evaluation in evaluations:
        if evaluation.approach.name in PRIOR_APPROACH_NAMES:
            return evaluation.approach.name
    return evaluations[0].approach.name


def _resolution_warnings(
    sample: SampleAdequacy,
    paired_tests: list[PairedApproachTest],
) -> list[str]:
    """State what the sample cannot decide before any difference is read as real."""
    warnings = [
        f"{sample.group_count} {sample.grouping} group(s): differences below "
        f"{sample.minimum_detectable_effect:.3f} are not resolvable by this sample."
    ]
    if sample.group_count < 2:
        warnings.append(
            "One group only: intervals and permutation tests cannot separate approach "
            "quality from source-family effects."
        )
    undecided = sorted(
        test.candidate for test in paired_tests if not test.significant and abs(test.difference) > 0
    )
    if undecided:
        warnings.append(f"Difference not distinguishable from group noise: {', '.join(undecided)}.")
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
