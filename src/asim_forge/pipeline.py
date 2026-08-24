"""Milestone 1 build orchestration."""

from __future__ import annotations

import json
from pathlib import Path

from .clustering import DEEPPARSE_REVISION, DeepParseClusterer
from .ingestion import read_events
from .models import BuildManifest
from .potato_bundle import write_potato_bundle


def build_review_bundle(
    input_root: Path,
    output_dir: Path,
    *,
    system: str,
    encoding: str = "utf-8",
    sample_size: int = 50,
    samples_per_cluster: int = 5,
) -> BuildManifest:
    events, input_files = read_events(input_root, encoding=encoding)
    result = DeepParseClusterer(
        system=system,
        sample_size=sample_size,
        samples_per_cluster=samples_per_cluster,
    ).cluster(events)

    output_dir.mkdir(parents=True, exist_ok=True)
    clusters_path = output_dir / "clusters.jsonl"
    with clusters_path.open("w", encoding="utf-8", newline="\n") as handle:
        for cluster in result.clusters:
            handle.write(cluster.model_dump_json())
            handle.write("\n")

    potato_items, potato_config = write_potato_bundle(result.clusters, output_dir)
    manifest = BuildManifest(
        system=system,
        engine_revision=DEEPPARSE_REVISION,
        input_root=str(input_root.resolve()),
        input_files=input_files,
        event_count=len(events),
        cluster_count=len(result.clusters),
        masks=result.masks,
        outputs={
            "clusters": clusters_path.relative_to(output_dir).as_posix(),
            "potato_items": potato_items.relative_to(output_dir).as_posix(),
            "potato_config": potato_config.relative_to(output_dir).as_posix(),
        },
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
