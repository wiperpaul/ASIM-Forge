import json
from pathlib import Path

import yaml

from asim_forge.pipeline import build_review_bundle


def test_builds_typed_clusters_and_potato_bundle(tmp_path: Path) -> None:
    input_dir = tmp_path / "logs"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "security.log").write_text(
        "Demo gateway auth event login failed for user alice from 10.0.0.1\n"
        "Demo gateway auth event login failed for user bob from 10.0.0.2\n"
        "Demo gateway network event connection allowed from 10.0.0.3 to 192.0.2.10\n"
        "Demo gateway network event connection allowed from 10.0.0.4 to 192.0.2.20\n",
        encoding="utf-8",
    )

    manifest = build_review_bundle(input_dir, output_dir, system="test-system")

    assert manifest.event_count == 4
    assert manifest.cluster_count == 2
    records = [
        json.loads(line)
        for line in (output_dir / "clusters.jsonl").read_text("utf-8").splitlines()
    ]
    assert {record["schema_suggestion"]["schema_name"] for record in records} == {
        "Authentication",
        "NetworkSession",
    }
    assert all(record["parameter_slots"] for record in records)
    config = yaml.safe_load((output_dir / "potato" / "config.yaml").read_text("utf-8"))
    assert config["task_dir"] == "."
    assert config["data_files"] == ["items.jsonl"]
    assert config["require_password"] is False
    assert {scheme["name"] for scheme in config["annotation_schemes"]} >= {
        "cluster_decision",
        "asim_schema",
        "parser_spec",
    }
