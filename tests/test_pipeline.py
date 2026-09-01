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
        json.loads(line) for line in (output_dir / "clusters.jsonl").read_text("utf-8").splitlines()
    ]
    assert {record["schema_suggestion"]["schema_name"] for record in records} == {
        "Authentication",
        "NetworkSession",
    }
    rankings = [
        json.loads(line)
        for line in (output_dir / "schema-rankings.jsonl").read_text("utf-8").splitlines()
    ]
    assert {prediction["selected_schema"] for prediction in rankings} == {
        "Authentication",
        "NetworkSession",
    }
    assert all(
        prediction["approach"] == {"name": "source-concept", "version": "1"}
        for prediction in rankings
    )
    assert manifest.outputs["schema_rankings"] == "schema-rankings.jsonl"
    assert all(record["parameter_slots"] for record in records)
    review_items = [
        json.loads(line)
        for line in (output_dir / "potato" / "items.jsonl").read_text("utf-8").splitlines()
    ]
    assert all("BASELINE SUGGESTION" not in item["text"] for item in review_items)
    assert all("<mark><code>p1 · " in item["template_html"] for item in review_items)
    assert all(
        item["representative_events_table"]["headers"] == ["Source", "Event"]
        for item in review_items
    )
    assert all(
        item["parameter_slots_table"]["headers"] == ["Slot", "Type", "Example values"]
        for item in review_items
    )
    assert all("predictions" not in item for item in review_items)
    assert all("suggested_schema" not in item for item in review_items)

    config = yaml.safe_load((output_dir / "potato" / "config.yaml").read_text("utf-8"))
    assert config["task_dir"] == "."
    assert config["data_files"] == ["items.jsonl"]
    assert config["require_password"] is False
    assert [field["key"] for field in config["instance_display"]["fields"]] == [
        "template_html",
        "representative_events_table",
        "parameter_slots_table",
    ]
    assert [field["type"] for field in config["instance_display"]["fields"]] == [
        "html",
        "spreadsheet",
        "spreadsheet",
    ]
    assert "pre_annotation" not in config
    instructions = config["annotation_instructions"]
    assert "<ol>" in instructions
    assert "Not part of this review:" in instructions
    assert "handled in later" in instructions
    assert "baseline" not in instructions.casefold()
    assert "<pre><code>" not in instructions
    assert "vimAsimForgeExample" not in instructions
    assert {scheme["name"] for scheme in config["annotation_schemes"]} == {
        "cluster_decision",
        "review_notes",
    }
    schemes = {scheme["name"]: scheme for scheme in config["annotation_schemes"]}
    assert (
        schemes["cluster_decision"]["description"]
        == "Does this cluster represent a coherent event pattern?"
    )
