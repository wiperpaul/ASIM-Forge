"""Run and report comparisons across registered semantic mapping approaches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..evaluation import SemanticMappingCase
from ..models import AsimCatalog, StrictModel
from .approaches import APPROACH_NAMES, build_approach
from .contracts import (
    ApproachIdentity,
    MappingRequest,
    SemanticMappingPrediction,
)
from .metrics import EvaluationError, EvaluationMetrics, evaluate_predictions


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
    approaches: list[ApproachEvaluation] = Field(min_length=1)


def compare_approaches(
    cases: list[SemanticMappingCase],
    catalog: AsimCatalog,
    approach_names: list[str] | None = None,
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

    revisions = {case.catalogue_revision for case in cases}
    if revisions != {catalog.manifest.resolved_revision}:
        raise ComparisonError(
            "Every case must use the loaded catalogue revision; "
            f"cases={sorted(revisions)}, catalogue={catalog.manifest.resolved_revision}"
        )

    evaluations: list[ApproachEvaluation] = []
    for name in names:
        approach = build_approach(name, reference_cases=cases)
        predictions: list[SemanticMappingPrediction] = []
        for case in cases:
            predictions.append(
                approach.predict(
                    MappingRequest(
                        case_id=case.case_id,
                        catalogue_revision=case.catalogue_revision,
                        input=case.input,
                    ),
                    catalog,
                )
            )
        evaluations.append(
            ApproachEvaluation(
                approach=predictions[0].approach,
                metrics=evaluate_predictions(cases, predictions),
                predictions=predictions,
                warnings=_evaluation_warnings(cases),
            )
        )

    return ComparisonReport(
        catalogue_revision=catalog.manifest.resolved_revision,
        case_count=len(cases),
        approaches=evaluations,
    )


def write_comparison_report(path: Path, report: ComparisonReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _evaluation_warnings(cases: list[SemanticMappingCase]) -> list[str]:
    warnings: list[str] = []
    if len(cases) < 20:
        warnings.append("Fewer than 20 cases: results are a harness smoke test, not evidence.")
    systems = {case.input.source_metadata.system for case in cases}
    if len(systems) < 2:
        warnings.append("Only one source system: distribution shift is not measured.")
    if any(case.provenance.label_source == "synthetic" for case in cases):
        warnings.append(
            "Synthetic labels are present: do not report results as production accuracy."
        )
    return warnings
