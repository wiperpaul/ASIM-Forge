"""Versioned access to Microsoft's machine-readable ASIM field catalogue."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import ValidationError

from .models import AsimCatalog, AsimCatalogField, AsimCatalogManifest, AsimFieldClass

SOURCE_REPOSITORY = "https://github.com/Azure/Azure-Sentinel"
SOURCE_PATH = "ASIM/dev/ASimTester/ASimTester.csv"
CATALOG_FILE = "asim-catalog.csv"
MANIFEST_FILE = "catalog-manifest.json"
DEFAULT_REVISION = "master"

_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_EXPECTED_COLUMNS = {
    "ColumnName",
    "ColumnType",
    "Class",
    "Schema",
    "LogicalType",
    "ListOfValues",
    "Aliased",
    "DynamicType",
    "ArrayValuesType",
}

FetchBytes = Callable[[str], bytes]


class CatalogError(ValueError):
    """Raised when an upstream or cached catalogue cannot be trusted."""


def sync_catalog(
    output_dir: Path,
    *,
    revision: str = DEFAULT_REVISION,
    fetch_bytes: FetchBytes | None = None,
) -> AsimCatalogManifest:
    """Resolve an upstream ref, retrieve the official CSV, and cache an immutable snapshot."""
    fetch = fetch_bytes or _fetch_bytes
    requested_revision = _validate_revision(revision)
    resolved_revision = _resolve_revision(requested_revision, fetch)
    source_url = _raw_catalog_url(resolved_revision)
    content = fetch(source_url)
    fields = _parse_catalog(content)
    schemas = sorted({field.schema_name for field in fields if field.schema_name != "Common"})
    if not schemas or not any(field.schema_name == "Common" for field in fields):
        raise CatalogError("The upstream ASIM catalogue must contain Common and named schemas")

    manifest = AsimCatalogManifest(
        source_repository=SOURCE_REPOSITORY,
        source_path=SOURCE_PATH,
        requested_revision=requested_revision,
        resolved_revision=resolved_revision,
        content_sha256=hashlib.sha256(content).hexdigest(),
        schema_count=len(schemas),
        field_count=len(fields),
        schemas=schemas,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / CATALOG_FILE).write_bytes(content)
    (output_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_catalog(snapshot_dir: Path) -> AsimCatalog:
    """Load a synced snapshot and verify its content against its provenance manifest."""
    manifest_path = snapshot_dir / MANIFEST_FILE
    catalog_path = snapshot_dir / CATALOG_FILE
    if not manifest_path.is_file() or not catalog_path.is_file():
        raise CatalogError(
            f"Catalogue snapshot must contain {MANIFEST_FILE} and {CATALOG_FILE}: {snapshot_dir}"
        )
    try:
        manifest_data: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = AsimCatalogManifest.model_validate(manifest_data)
    except (json.JSONDecodeError, UnicodeError, ValidationError) as error:
        raise CatalogError(f"Invalid ASIM catalogue manifest: {error}") from error

    content = catalog_path.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != manifest.content_sha256:
        raise CatalogError("ASIM catalogue content does not match catalog-manifest.json")
    fields = _parse_catalog(content)
    schemas = sorted({field.schema_name for field in fields if field.schema_name != "Common"})
    if len(fields) != manifest.field_count or schemas != manifest.schemas:
        raise CatalogError("ASIM catalogue contents do not match the manifest counts")
    return AsimCatalog(manifest=manifest, fields=fields)


def _validate_revision(revision: str) -> str:
    revision = revision.strip()
    if not revision or any(character.isspace() for character in revision):
        raise CatalogError("ASIM catalogue revision cannot be empty or contain whitespace")
    return revision


def _resolve_revision(revision: str, fetch: FetchBytes) -> str:
    if _COMMIT_SHA.fullmatch(revision):
        return revision.lower()
    url = f"https://api.github.com/repos/Azure/Azure-Sentinel/commits/{quote(revision, safe='')}"
    try:
        payload: Any = json.loads(fetch(url).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise CatalogError(
            f"Could not resolve Azure-Sentinel revision {revision!r}: {error}"
        ) from error
    resolved = payload.get("sha") if isinstance(payload, dict) else None
    if not isinstance(resolved, str) or not _COMMIT_SHA.fullmatch(resolved):
        raise CatalogError(f"Azure-Sentinel revision {revision!r} did not resolve to a commit SHA")
    return resolved.lower()


def _raw_catalog_url(revision: str) -> str:
    return f"https://raw.githubusercontent.com/Azure/Azure-Sentinel/{revision}/{SOURCE_PATH}"


def _fetch_bytes(url: str) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ASIM-Forge",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed trusted hosts
            return bytes(response.read())
    except OSError as error:
        raise CatalogError(f"Could not retrieve the ASIM catalogue from {url}: {error}") from error


def _parse_catalog(content: bytes) -> list[AsimCatalogField]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError as error:
        raise CatalogError(f"ASIM catalogue is not valid UTF-8: {error}") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = set(reader.fieldnames or [])
    missing = sorted(_EXPECTED_COLUMNS - columns)
    if missing:
        raise CatalogError(f"ASIM catalogue is missing columns: {', '.join(missing)}")

    fields: list[AsimCatalogField] = []
    for line_number, row in enumerate(reader, start=2):
        if not any((value or "").strip() for value in row.values()):
            continue
        try:
            fields.append(
                AsimCatalogField(
                    name=_required(row, "ColumnName", line_number),
                    kql_type=_required(row, "ColumnType", line_number),
                    field_class=cast(
                        AsimFieldClass,
                        _required(row, "Class", line_number),
                    ),
                    schema_name=_required(row, "Schema", line_number),
                    logical_type=_optional(row.get("LogicalType")),
                    allowed_values=_allowed_values(row.get("ListOfValues")),
                    aliased_field=_optional(row.get("Aliased")),
                    dynamic_type=_optional(row.get("DynamicType")),
                    array_values_type=_optional(row.get("ArrayValuesType")),
                )
            )
        except ValidationError as error:
            raise CatalogError(f"Invalid ASIM catalogue row {line_number}: {error}") from error
    if not fields:
        raise CatalogError("ASIM catalogue contains no fields")
    return fields


def _required(row: dict[str, str | None], key: str, line_number: int) -> str:
    value = _optional(row.get(key))
    if value is None:
        raise CatalogError(f"ASIM catalogue row {line_number} has no {key}")
    return value


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _allowed_values(value: str | None) -> list[str]:
    normalized = _optional(value)
    return [] if normalized is None else [item.strip() for item in normalized.split("|")]
