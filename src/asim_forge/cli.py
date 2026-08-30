"""Command-line entry point for the walking skeleton."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .benchmarking import BenchmarkError, run_benchmarks
from .catalog import load_catalog, sync_catalog
from .compiler import compile_reviews
from .evaluation import EvaluationError, load_semantic_mapping_cases
from .ingestion import InputError
from .pipeline import build_review_bundle
from .reviews import ReviewError
from .semantic_mapping import APPROACH_NAMES
from .semantic_mapping.comparison import compare_approaches, write_comparison_report


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
        elif args.evaluation_command == "validate":
            cases = load_semantic_mapping_cases(args.cases)
            print(f"Validated {len(cases)} provider-neutral semantic mapping case(s)")
        elif args.evaluation_command == "compare":
            cases = load_semantic_mapping_cases(args.cases)
            report = compare_approaches(
                cases,
                load_catalog(args.catalog),
                args.approaches,
            )
            if args.output is not None:
                write_comparison_report(args.output, report)
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
