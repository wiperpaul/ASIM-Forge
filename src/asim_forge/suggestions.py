"""Transparent schema suggestions used only to exercise human review."""

from __future__ import annotations

from .models import AsimSchema, SchemaScore, SchemaSuggestion
from .source_normalization import source_tokens

_KEYWORDS: dict[AsimSchema, frozenset[str]] = {
    "Authentication": frozenset(
        (
            "auth",
            "authentication",
            "credential",
            "login",
            "logon",
            "logout",
            "password",
            "signedin",
        )
    ),
    "NetworkSession": frozenset(
        (
            "connection",
            "destination",
            "firewall",
            "flow",
            "network",
            "session",
            "source",
            "traffic",
        )
    ),
    "AuditEvent": frozenset(
        (
            "audit",
            "configuration",
            "create",
            "delete",
            "disable",
            "enable",
            "modify",
            "policy",
            "update",
        )
    ),
}


def suggest_schema(template: str) -> SchemaSuggestion:
    concepts = source_tokens(template)
    ranked: list[SchemaScore] = []
    for schema_name, keywords in _KEYWORDS.items():
        evidence = sorted(concepts & keywords)
        ranked.append(
            SchemaScore(
                schema_name=schema_name,
                score=len(evidence),
                evidence=evidence,
            )
        )

    ranked.sort(key=lambda item: (-item.score, item.schema_name))
    best = ranked[0]
    tied = len(ranked) > 1 and ranked[1].score == best.score
    if best.score == 0 or tied:
        return SchemaSuggestion(
            schema_name="NoFit",
            confidence=0.0,
            ranked_scores=ranked,
            method="source-concept-v1",
        )

    total = sum(item.score for item in ranked)
    return SchemaSuggestion(
        schema_name=best.schema_name,
        confidence=round(best.score / total, 4),
        ranked_scores=ranked,
        method="source-concept-v1",
    )
