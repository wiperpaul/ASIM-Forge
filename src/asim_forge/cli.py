"""Command-line entry point for the walking skeleton."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .catalog import sync_catalog
from .compiler import compile_reviews
from .evaluation import EvaluationError, load_semantic_mapping_cases
from .ingestion import InputError
from .pipeline import build_review_bundle
from .reviews import ReviewError


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
        else:
            cases = load_semantic_mapping_cases(args.cases)
            print(f"Validated {len(cases)} provider-neutral semantic mapping case(s)")
    except (EvaluationError, InputError, ReviewError, UnicodeError, ValueError) as error:
        parser.error(str(error))
