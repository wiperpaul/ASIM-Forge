import hashlib
import json
from pathlib import Path

import pytest

from asim_forge.catalog import CATALOG_FILE, MANIFEST_FILE, CatalogError, load_catalog, sync_catalog

_REVISION = "0123456789abcdef0123456789abcdef01234567"
_CATALOG = (
    b"ColumnName,ColumnType,Class,Schema,LogicalType,ListOfValues,"
    b"Aliased,DynamicType,ArrayValuesType\n"
    b"EventCount,int,Mandatory,Common,,,,,\n"
    b"SrcIpAddr,string,Optional,Common,IP Address,,,,\n"
    b"EventType,string,Mandatory,NetworkSession,Enumerated,NetworkSession|Flow,,,\n"
    b"SrcIpAddr,string,Recommended,NetworkSession,IP Address,,,,\n"
    b"EventType,string,Mandatory,Authentication,Enumerated,Logon|Logoff,,,\n"
    b"User,string,Alias,Authentication,Username,,TargetUsername,,\n"
)


def test_syncs_symbolic_revision_and_loads_schema_overrides(tmp_path: Path) -> None:
    requested_urls: list[str] = []

    def fetch(url: str) -> bytes:
        requested_urls.append(url)
        if "api.github.com" in url:
            return json.dumps({"sha": _REVISION}).encode()
        return _CATALOG

    manifest = sync_catalog(tmp_path, revision="master", fetch_bytes=fetch)
    catalog = load_catalog(tmp_path)

    assert manifest.resolved_revision == _REVISION
    assert manifest.content_sha256 == hashlib.sha256(_CATALOG).hexdigest()
    assert manifest.schemas == ["Authentication", "NetworkSession"]
    assert requested_urls[1].endswith(f"/{_REVISION}/ASIM/dev/ASimTester/ASimTester.csv")
    network_fields = catalog.fields_for_schema("NetworkSession")
    assert [(field.name, field.field_class) for field in network_fields] == [
        ("EventCount", "Mandatory"),
        ("EventType", "Mandatory"),
        ("SrcIpAddr", "Recommended"),
    ]
    assert network_fields[1].allowed_values == ["NetworkSession", "Flow"]


def test_full_commit_revision_does_not_need_ref_resolution(tmp_path: Path) -> None:
    requested_urls: list[str] = []

    def fetch(url: str) -> bytes:
        requested_urls.append(url)
        return _CATALOG

    sync_catalog(tmp_path, revision=_REVISION.upper(), fetch_bytes=fetch)

    assert len(requested_urls) == 1
    assert _REVISION in requested_urls[0]


def test_loader_rejects_catalogue_changed_after_sync(tmp_path: Path) -> None:
    sync_catalog(tmp_path, revision=_REVISION, fetch_bytes=lambda _: _CATALOG)
    (tmp_path / CATALOG_FILE).write_bytes(_CATALOG + b"unexpected")

    with pytest.raises(CatalogError, match="does not match"):
        load_catalog(tmp_path)

    assert (tmp_path / MANIFEST_FILE).is_file()
