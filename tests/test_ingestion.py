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


def test_rejects_empty_folder(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="No supported log files"):
        read_events(tmp_path)
