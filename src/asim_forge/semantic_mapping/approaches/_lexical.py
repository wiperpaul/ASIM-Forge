"""Shared deterministic text primitives; not a production semantic rules engine."""

from __future__ import annotations

import re

from ...models import AsimCatalog, AsimCatalogField, ParameterSlot
from ...source_normalization import source_tokens, structured_key_before
from ..contracts import RankedFieldCandidate, RankedSchemaCandidate
from ..types import SemanticMappingInput

_SCHEMA_KEYWORDS: dict[str, set[str]] = {
    "Authentication": {
        "auth",
        "authentication",
        "credential",
        "login",
        "logon",
        "logout",
        "password",
    },
    "NetworkSession": {
        "connection",
        "destination",
        "firewall",
        "flow",
        "network",
        "session",
        "source",
        "traffic",
    },
    "AuditEvent": {
        "audit",
        "configuration",
        "create",
        "delete",
        "disable",
        "enable",
        "modify",
        "policy",
        "update",
    },
}


def tokens(text: str) -> set[str]:
    return source_tokens(text)


def name_tokens(text: str) -> set[str]:
    return source_tokens(text)


def slot_context(mapping_input: SemanticMappingInput, slot: ParameterSlot) -> str:
    matches = list(re.finditer(re.escape(slot.placeholder), mapping_input.template))
    if slot.occurrence > len(matches):
        return f"{slot.label} {' '.join(slot.examples)}"
    match = matches[slot.occurrence - 1]
    structured_key = structured_key_before(mapping_input.template, match.start())
    if structured_key is not None:
        return f"{structured_key} {slot.label}"
    before = mapping_input.template[: match.start()].split()[-3:]
    after = mapping_input.template[match.end() :].split()[:2]
    if before and before[-1].casefold() in {"from", "to", "client", "server"}:
        return " ".join([before[-1], slot.label])
    if before and before[-1].casefold() == "port":
        return " ".join([*before[-2:], slot.label])
    return " ".join([*before, slot.label, *after])


def rank_schemas(
    mapping_input: SemanticMappingInput, catalog: AsimCatalog
) -> list[RankedSchemaCandidate]:
    context = tokens(mapping_input.template)
    scored: list[tuple[str, int, list[str]]] = []
    for schema_name in catalog.manifest.schemas:
        schema_terms = name_tokens(schema_name) | _SCHEMA_KEYWORDS.get(schema_name, set())
        evidence = sorted(context & schema_terms)
        scored.append((schema_name, len(evidence), evidence))
    scored.sort(key=lambda item: (-item[1], item[0]))
    maximum = max((score for _, score, _ in scored), default=0)
    if maximum == 0:
        return []
    return [
        RankedSchemaCandidate(
            schema_name=schema_name,
            score=round(score / maximum, 6),
            evidence=evidence,
        )
        for schema_name, score, evidence in scored
        if score > 0
    ]


def rank_fields(
    fields: list[AsimCatalogField],
    query: str,
    *,
    limit: int = 5,
) -> list[RankedFieldCandidate]:
    query_terms = tokens(query)
    scored: list[tuple[AsimCatalogField, float, list[str]]] = []
    for field in fields:
        if field.field_class == "Alias":
            continue
        field_terms = name_tokens(field.name)
        if field.logical_type:
            field_terms |= tokens(field.logical_type)
        overlap = sorted(query_terms & field_terms)
        if not overlap:
            continue
        precision = len(overlap) / len(field_terms)
        coverage = len(overlap) / len(query_terms)
        score = (0.35 * precision) + (0.65 * coverage)
        scored.append((field, score, overlap))
    scored.sort(key=lambda item: (-item[1], item[0].name))
    if not scored:
        return []
    maximum = scored[0][1]
    return [
        RankedFieldCandidate(
            asim_field=field.name,
            score=round(score / maximum, 6),
            evidence=evidence,
        )
        for field, score, evidence in scored[:limit]
    ]
