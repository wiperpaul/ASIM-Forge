"""Command-line entry point for the walking skeleton."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .benchmarking import BenchmarkError, run_benchmarks
from .catalog import load_catalog, sync_catalog
from .compiler import compile_reviews
from .evaluation import EvaluationError, SemanticMappingCase, load_semantic_mapping_cases
from .evaluation_splits import (
    SemanticDatasetSplit,
    load_semantic_dataset_split,
    validate_semantic_case_groups,
    validate_semantic_dataset_split,
)
from .ingestion import InputError
from .pipeline import build_review_bundle
from .reviews import ReviewError
from .semantic_annotation import (
    prepare_semantic_annotation_queue,
    promote_semantic_annotations,
    validate_semantic_promotion_artifacts,
)
from .semantic_mapping import APPROACH_NAMES
from .semantic_mapping.comparison import (
    compare_approaches,
    compare_split_approaches,
    write_comparison_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asim-forge",
        description="Build and compile human-reviewed ASIM parser candidates.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Cluster a folder of .log/.txt files")
    build.add_argument("input", type=Path, help="Folder containing line-oriented log files")
    build.add_argument("--output", type=Path, default=Path("artifacts/latest"))
    build.add_argument("--system", required=True, help="Stable source system identifier")
    build.add_argument("--encoding", default="utf-8")
    build.add_argument("--sample-size", type=int, default=50)
    build.add_argument("--samples-per-cluster", type=int, default=5)

    compile_parser = subparsers.add_parser(
        "compile",
        help="Compile approved review decisions into parser specs and KQL",
    )
    compile_parser.add_argument("clusters", type=Path, help="clusters.jsonl from build")
    compile_parser.add_argument(
        "reviews",
        type=Path,
        help="Canonical review JSONL or a Potato user_state.json",
    )
    compile_parser.add_argument("--output", type=Path, default=Path("artifacts/compiled"))

    catalog = subparsers.add_parser(
        "catalog",
        help="Manage the versioned upstream ASIM field catalogue",
    )
    catalog_subparsers = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_sync = catalog_subparsers.add_parser(
        "sync",
        help="Retrieve Microsoft's ASimSchemaTester catalogue at an immutable revision",
    )
    catalog_sync.add_argument("--output", type=Path, default=Path("artifacts/asim-catalog"))
    catalog_sync.add_argument(
        "--revision",
        default="master",
        help="Azure-Sentinel branch, tag, or full commit SHA (default: master)",
    )

    evaluation = subparsers.add_parser(
        "evaluation",
        help="Manage provider-neutral semantic mapping evaluation cases",
    )
    evaluation_subparsers = evaluation.add_subparsers(
        dest="evaluation_command",
        required=True,
    )
    evaluation_validate = evaluation_subparsers.add_parser(
        "validate",
        help="Validate canonical semantic mapping case JSONL",
    )
    evaluation_validate.add_argument("cases", type=Path, help="Semantic mapping case JSONL")
    evaluation_validate.add_argument(
        "--split",
        type=Path,
        help="Optional grouped train/validation/test split manifest",
    )
    evaluation_validate.add_argument(
        "--case-groups",
        type=Path,
        help="Pre-label case-groups.jsonl from semantic promotion",
    )
    evaluation_validate.add_argument(
        "--promotion-manifest",
        type=Path,
        help="Promotion manifest that authenticates the cases and case groups",
    )
    evaluation_queue = evaluation_subparsers.add_parser(
        "queue",
        help="Export approved clusters as a blinded semantic annotation queue",
    )
    evaluation_queue.add_argument(
        "build_dir",
        type=Path,
        help="Build directory containing manifest.json and clusters.jsonl",
    )
    evaluation_queue.add_argument(
        "reviews",
        type=Path,
        help="Canonical cluster-review JSONL or a Potato user_state.json",
    )
    evaluation_queue.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="Directory containing a pinned ASIM catalogue snapshot",
    )
    evaluation_queue.add_argument("--group-id", required=True)
    evaluation_queue.add_argument(
        "--group-strategy",
        required=True,
        choices=("source", "source-family"),
        help="Build-level leakage-control grouping assigned before annotation",
    )
    evaluation_queue.add_argument(
        "--system",
        help="Optional neutral annotation identifier replacing the build system name",
    )
    evaluation_queue.add_argument("--vendor")
    evaluation_queue.add_argument("--product")
    evaluation_queue.add_argument("--source-table")
    evaluation_queue.add_argument("--message-field")
    evaluation_queue.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/semantic-annotation"),
    )
    evaluation_promote = evaluation_subparsers.add_parser(
        "promote",
        help="Promote completed semantic annotations into provider-neutral gold cases",
    )
    evaluation_promote.add_argument(
        "queue_dir",
        type=Path,
        help="Hash-verified queue directory containing queue-manifest.json",
    )
    evaluation_promote.add_argument("decisions", type=Path, help="Typed decision JSONL")
    evaluation_promote.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="The same pinned ASIM catalogue used to create the queue",
    )
    evaluation_promote.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/semantic-gold"),
    )
    evaluation_promote.add_argument(
        "--allow-single-review",
        action="store_true",
        help="Permit provisional human-review cases without adjudication",
    )
    evaluation_compare = evaluation_subparsers.add_parser(
        "compare",
        help="Compare separated semantic mapping approaches against the same cases",
    )
    evaluation_compare.add_argument("cases", type=Path, help="Semantic mapping case JSONL")
    evaluation_compare.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="Directory containing a pinned ASIM catalogue snapshot",
    )
    evaluation_compare.add_argument(
        "--approach",
        action="append",
        choices=APPROACH_NAMES,
        dest="approaches",
        help="Approach to compare; repeat to select several (default: all)",
    )
    evaluation_compare.add_argument(
        "--output",
        type=Path,
        help="Optional path for the complete JSON comparison report",
    )
    evaluation_compare.add_argument(
        "--split",
        type=Path,
        help="Grouped split manifest; retrieval references come only from its reference partitions",
    )
    evaluation_compare.add_argument(
        "--partition",
        choices=("validation", "test"),
        default="test",
        help="Held-out partition to evaluate when --split is supplied (default: test)",
    )
    evaluation_compare.add_argument(
        "--case-groups",
        type=Path,
        help="Pre-label case-groups.jsonl from semantic promotion",
    )
    evaluation_compare.add_argument(
        "--promotion-manifest",
        type=Path,
        help="Promotion manifest that authenticates the cases and case groups",
    )
    evaluation_benchmark = evaluation_subparsers.add_parser(
        "benchmark",
        help="Run the registered parsing, security-format, and ASIM evaluation corpora",
    )
    evaluation_benchmark.add_argument(
        "registry", type=Path, help="Directory containing corpus manifest folders"
    )
    evaluation_benchmark.add_argument(
        "--catalog",
        type=Path,
        help="Pinned ASIM catalogue (required when semantic-gold corpora are present)",
    )
    evaluation_benchmark.add_argument("--output", type=Path, default=Path("artifacts/evaluation"))
    evaluation_benchmark.add_argument("--cache", type=Path, help="Optional shared download cache")
    evaluation_benchmark.add_argument(
        "--revision", default="unknown", help="Source revision recorded in the report"
    )
    evaluation_benchmark.add_argument(
        "--baseline", type=Path, help="Previous benchmark-report.json for comparable deltas"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_manifest = build_review_bundle(
                args.input,
                args.output,
                system=args.system,
                encoding=args.encoding,
                sample_size=args.sample_size,
                samples_per_cluster=args.samples_per_cluster,
            )
            print(
                f"Built {build_manifest.cluster_count} clusters from "
                f"{build_manifest.event_count} events "
                f"in {args.output}"
            )
        elif args.command == "compile":
            compile_manifest = compile_reviews(args.clusters, args.reviews, args.output)
            message = (
                f"Compiled {compile_manifest.compiled_count} approved parser(s) in {args.output}"
            )
            if compile_manifest.skipped_reviews:
                skipped = ", ".join(
                    f"{reason}={count}"
                    for reason, count in compile_manifest.skipped_reviews.items()
                )
                message += f"; not compiled: {skipped}"
            print(message)
        elif args.command == "catalog":
            catalog_manifest = sync_catalog(args.output, revision=args.revision)
            print(
                f"Synced {catalog_manifest.schema_count} ASIM schemas and "
                f"{catalog_manifest.field_count} field definitions from "
                f"Azure-Sentinel@{catalog_manifest.resolved_revision} into {args.output}"
            )
        elif args.evaluation_command == "queue":
            queue_manifest = prepare_semantic_annotation_queue(
                args.build_dir,
                args.reviews,
                args.output,
                load_catalog(args.catalog),
                group_id=args.group_id,
                group_strategy=args.group_strategy,
                system=args.system,
                vendor=args.vendor,
                product=args.product,
                source_table=args.source_table,
                message_field=args.message_field,
            )
            excluded = queue_manifest.review_count - queue_manifest.task_count
            print(
                f"Prepared {queue_manifest.task_count} blinded semantic annotation task(s) "
                f"in {args.output}; excluded reviews={excluded}, "
                f"unreviewed clusters={queue_manifest.unreviewed_cluster_count}"
            )
        elif args.evaluation_command == "promote":
            promotion_manifest = promote_semantic_annotations(
                args.queue_dir,
                args.decisions,
                args.output,
                load_catalog(args.catalog),
                allow_single_review=args.allow_single_review,
            )
            skipped = ", ".join(
                f"{reason}={count}" for reason, count in promotion_manifest.skipped_tasks.items()
            )
            message = (
                f"Promoted {promotion_manifest.promoted_count} semantic mapping case(s) "
                f"into {args.output}"
            )
            if skipped:
                message += f"; not promoted: {skipped}"
            print(message)
        elif args.evaluation_command == "validate":
            cases = load_semantic_mapping_cases(args.cases)
            message = f"Validated {len(cases)} provider-neutral semantic mapping case(s)"
            if args.split is None and (
                args.case_groups is not None or args.promotion_manifest is not None
            ):
                raise EvaluationError("--case-groups and --promotion-manifest require --split")
            if args.split is not None:
                split = load_semantic_dataset_split(args.split)
                _validate_promoted_split(
                    cases,
                    split,
                    args.case_groups,
                    args.promotion_manifest,
                    args.cases,
                )
                counts = validate_semantic_dataset_split(cases, split)
                partitions = ", ".join(
                    f"{partition}={count}" for partition, count in counts.items()
                )
                message += f" with grouped split {split.split_id} ({partitions})"
            print(message)
        elif args.evaluation_command == "compare":
            cases = load_semantic_mapping_cases(args.cases)
            catalog = load_catalog(args.catalog)
            if args.split is None and (
                args.case_groups is not None or args.promotion_manifest is not None
            ):
                raise EvaluationError("--case-groups and --promotion-manifest require --split")
            if args.split is None:
                report = compare_approaches(cases, catalog, args.approaches)
            else:
                split = load_semantic_dataset_split(args.split)
                _validate_promoted_split(
                    cases,
                    split,
                    args.case_groups,
                    args.promotion_manifest,
                    args.cases,
                )
                report = compare_split_approaches(
                    cases,
                    catalog,
                    split,
                    args.partition,
                    args.approaches,
                )
            if args.output is not None:
                write_comparison_report(args.output, report)
            if report.split_id is not None:
                print(
                    f"split={report.split_id} partition={report.evaluation_partition} "
                    f"references={report.reference_case_count} cases={report.case_count}"
                )
            print(
                "approach          schema@1  schema@3  field-f1  field-mrr  "
                "field-r@gt  role-f1  exact  coverage  edits"
            )
            for evaluation in report.approaches:
                metrics = evaluation.metrics
                print(
                    f"{evaluation.approach.name:<17} "
                    f"{metrics.schema_top1_accuracy:>8.3f}  "
                    f"{metrics.schema_top3_hit_rate:>8.3f}  "
                    f"{metrics.field_micro_f1:>8.3f}  "
                    f"{metrics.field_mrr:>9.3f}  "
                    f"{metrics.field_recall_at_gold:>10.3f}  "
                    f"{metrics.source_micro_f1:>7.3f}  "
                    f"{metrics.mapping_exact_match:>5.3f}  "
                    f"{metrics.coverage:>8.3f}  "
                    f"{metrics.mean_mapping_edits:>5.2f}"
                )
                for warning in evaluation.warnings:
                    print(f"  warning: {warning}")
        else:
            report = run_benchmarks(
                args.registry,
                args.output,
                catalog_dir=args.catalog,
                cache_dir=args.cache,
                revision=args.revision,
                baseline_path=args.baseline,
            )
            print(
                f"Evaluated {len(report.corpora)} corpora and wrote "
                f"{len(report.results)} result row(s) to {args.output}"
            )
    except (
        BenchmarkError,
        EvaluationError,
        InputError,
        ReviewError,
        UnicodeError,
        ValueError,
    ) as error:
        parser.error(str(error))


def _validate_promoted_split(
    cases: list[SemanticMappingCase],
    split: SemanticDatasetSplit,
    case_groups_path: Path | None,
    promotion_manifest_path: Path | None,
    cases_path: Path,
) -> None:
    if case_groups_path is None or promotion_manifest_path is None:
        raise EvaluationError(
            "Grouped evaluation requires --case-groups and --promotion-manifest "
            "to verify pre-label group assignments"
        )
    groups = validate_semantic_promotion_artifacts(
        cases_path,
        case_groups_path,
        promotion_manifest_path,
    )
    validate_semantic_case_groups(cases, split, groups)
