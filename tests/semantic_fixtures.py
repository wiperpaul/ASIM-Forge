"""Shared fixtures for the semantic mapping test modules."""

from pathlib import Path

from asim_forge.evaluation import load_semantic_mapping_cases
from asim_forge.models import AsimCatalog, AsimCatalogField, AsimCatalogManifest

EXAMPLE_CASES = Path("examples/evaluation/semantic-mapping-cases.jsonl")


def build_catalog() -> AsimCatalog:
    """A minimal NetworkSession catalogue pinned to the example case revision."""
    case = load_semantic_mapping_cases(EXAMPLE_CASES)[0]
    fields = [
        AsimCatalogField(
            name="EventResult",
            kql_type="string",
            field_class="Recommended",
            schema_name="Common",
            logical_type="Event result",
        ),
        AsimCatalogField(
            name="SrcIpAddr",
            kql_type="string",
            field_class="Recommended",
            schema_name="NetworkSession",
            logical_type="IP Address",
        ),
        AsimCatalogField(
            name="DstIpAddr",
            kql_type="string",
            field_class="Recommended",
            schema_name="NetworkSession",
            logical_type="IP Address",
        ),
        AsimCatalogField(
            name="DstPortNumber",
            kql_type="int",
            field_class="Recommended",
            schema_name="NetworkSession",
            logical_type="Port Number",
        ),
    ]
    return AsimCatalog(
        manifest=AsimCatalogManifest(
            source_repository="https://github.com/Azure/Azure-Sentinel",
            source_path="ASIM/dev/ASimTester/ASimTester.csv",
            requested_revision=case.catalogue_revision,
            resolved_revision=case.catalogue_revision,
            content_sha256="0" * 64,
            schema_count=1,
            field_count=len(fields),
            schemas=["NetworkSession"],
        ),
        fields=fields,
    )
