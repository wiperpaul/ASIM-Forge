"""Integrity verification for promoted semantic evaluation artifacts."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from ..evaluation import load_semantic_mapping_cases
from ..evaluation_splits import SemanticCaseGroup, load_semantic_case_groups
from .artifacts import _sha256_file
from .contracts import (
    SemanticAnnotationError,
    SemanticAnnotationPromotionManifest,
)


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
