import json
from pathlib import Path

from asim_forge.reviews import load_review_decisions


def test_normalizes_potato_user_state(tmp_path: Path) -> None:
    parser_spec = {
        "parser_name": "vimDemoAuth",
        "vendor": "Demo",
        "product": "Gateway",
        "field_mappings": [
            {"slot_id": "p1", "asim_field": "TargetUsername", "transform": "string"}
        ],
    }
    state = {
        "user_id": "alice",
        "instance_id_to_label_to_value": {
            "cluster-123": {
                "cluster_decision": {"labels": {"approved": True}},
                "asim_schema": {"labels": {"Authentication": True}},
                "parser_spec": {"text": json.dumps(parser_spec)},
                "review_notes": {"text": "Checked against the source."},
            }
        },
    }
    path = tmp_path / "user_state.json"
    path.write_text(json.dumps(state), encoding="utf-8")

    decisions = load_review_decisions(path)

    assert len(decisions) == 1
    assert decisions[0].reviewer == "alice"
    assert decisions[0].schema_name == "Authentication"
    assert decisions[0].field_mappings[0].asim_field == "TargetUsername"

