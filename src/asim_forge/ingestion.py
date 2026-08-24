"""Read static, line-oriented log files without mutating the source directory."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .models import InputFile, SourceEvent

SUPPORTED_SUFFIXES = frozenset({".log", ".txt"})


class InputError(ValueError):
    """Raised when an input path cannot produce a usable corpus."""


def discover_log_files(root: Path) -> list[Path]:
    if not root.exists():
        raise InputError(f"Input folder does not exist: {root}")
    if not root.is_dir():
        raise InputError(f"Input path is not a folder: {root}")

    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES
    )
    if not files:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise InputError(f"No supported log files found in {root} ({supported})")
    return files


def read_events(
    root: Path,
    *,
    encoding: str = "utf-8",
) -> tuple[list[SourceEvent], list[InputFile]]:
    events: list[SourceEvent] = []
    inputs: list[InputFile] = []

    for path in discover_log_files(root):
        relative_path = path.relative_to(root).as_posix()
        file_events = list(_read_file(path, relative_path, encoding=encoding))
        events.extend(file_events)
        inputs.append(InputFile(path=relative_path, event_count=len(file_events)))

    if not events:
        raise InputError(f"Log files in {root} did not contain any non-empty events")
    return events, inputs


def _read_file(path: Path, relative_path: str, *, encoding: str) -> Iterable[SourceEvent]:
    with path.open("r", encoding=encoding) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            text = raw_line.rstrip("\r\n")
            if text.strip():
                yield SourceEvent(source_file=relative_path, line_number=line_number, text=text)
