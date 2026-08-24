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


def test_ignores_parser_draft_when_cluster_is_not_approved(tmp_path: Path) -> None:
    state = {
        "user_id": "alice",
        "instance_id_to_label_to_value": {
            "cluster-123": {
                "cluster_decision": {"labels": {"rejected": True}},
                "parser_spec": {"text": "generated draft that was never completed"},
                "review_notes": {"text": "Mixed and unusable events."},
            }
        },
    }
    path = tmp_path / "user_state.json"
    path.write_text(json.dumps(state), encoding="utf-8")

    decisions = load_review_decisions(path)

    assert len(decisions) == 1
    assert decisions[0].status == "rejected"
    assert decisions[0].parser_name is None
    assert decisions[0].field_mappings == []


def test_normalizes_potato_28_identifier_value_pairs(tmp_path: Path) -> None:
    state = {
        "user_id": "alice",
        "instance_id_to_label_to_value": {
            "cluster-123": [
                [{"schema": "cluster_decision", "name": "approved"}, "approved"],
                [
                    {"schema": "review_notes", "name": "text_box"},
                    "The examples form one pattern.",
                ],
            ]
        },
    }
    path = tmp_path / "user_state.json"
    path.write_text(json.dumps(state), encoding="utf-8")

    decisions = load_review_decisions(path)

    assert len(decisions) == 1
    assert decisions[0].status == "approved"
    assert decisions[0].notes == "The examples form one pattern."
    assert decisions[0].schema_name is None


def test_incomplete_approved_parser_draft_remains_awaiting_mapping(tmp_path: Path) -> None:
    draft = {
        "parser_name": "vimDraft",
        "vendor": "",
        "product": "",
        "field_mappings": [{"slot_id": "p1", "asim_field": "", "transform": "string"}],
    }
    state = {
        "user_id": "alice",
        "instance_id_to_label_to_value": {
            "cluster-123": [
                [{"schema": "cluster_decision", "name": "approved"}, "approved"],
                [{"schema": "parser_spec", "name": "text_box"}, json.dumps(draft)],
            ]
        },
    }
    path = tmp_path / "user_state.json"
    path.write_text(json.dumps(state), encoding="utf-8")

    decisions = load_review_decisions(path)

    assert decisions[0].status == "approved"
    assert decisions[0].parser_name is None
    assert decisions[0].field_mappings == []
