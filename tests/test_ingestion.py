from pathlib import Path

import pytest

from asim_forge.ingestion import InputError, read_events


def test_reads_supported_files_in_stable_order(tmp_path: Path) -> None:
    (tmp_path / "b.log").write_text("second\n\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("first\n", encoding="utf-8")
    (tmp_path / "ignored.json").write_text('{"ignored": true}', encoding="utf-8")

    events, inputs = read_events(tmp_path)

    assert [event.text for event in events] == ["first", "second"]
    assert [item.path for item in inputs] == ["a.txt", "b.log"]


def test_strips_a_decoded_byte_order_mark_from_the_first_event(tmp_path: Path) -> None:
    (tmp_path / "cef.log").write_text("\ufeffCEF:0|Vendor|Product|event\n", encoding="utf-8")

    events, _ = read_events(tmp_path)

    assert [event.text for event in events] == ["CEF:0|Vendor|Product|event"]


def test_rejects_empty_folder(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="No supported log files"):
        read_events(tmp_path)
