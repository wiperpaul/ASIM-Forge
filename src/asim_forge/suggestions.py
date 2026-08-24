"""Transparent schema suggestions used only to exercise human review."""

from __future__ import annotations

import re

from .models import SchemaScore, SchemaSuggestion

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Authentication": (
        "auth",
        "credential",
        "login",
        "logon",
        "logout",
        "password",
        "signed in",
    ),
    "NetworkSession": (
        "connection",
        "destination",
        "dst",
        "firewall",
        "flow",
        "network",
        "session",
        "source ip",
        "src",
        "traffic",
    ),
    "AuditEvent": (
        "audit",
        "configuration",
        "created",
        "deleted",
        "disabled",
        "enabled",
        "modified",
        "policy",
        "updated",
    ),
}


def suggest_schema(template: str) -> SchemaSuggestion:
    normalized = template.casefold()
    ranked: list[SchemaScore] = []
    for schema_name, keywords in _KEYWORDS.items():
        evidence = [word for word in keywords if _contains(normalized, word)]
        ranked.append(
            SchemaScore(
                schema_name=schema_name,  # type: ignore[arg-type]
                score=len(evidence),
                evidence=evidence,
            )
        )

    ranked.sort(key=lambda item: (-item.score, item.schema_name))
    best = ranked[0]
    if best.score == 0:
        return SchemaSuggestion(schema_name="NoFit", confidence=0.0, ranked_scores=ranked)

    total = sum(item.score for item in ranked)
    return SchemaSuggestion(
        schema_name=best.schema_name,
        confidence=round(best.score / total, 4),
        ranked_scores=ranked,
    )


def _contains(text: str, keyword: str) -> bool:
    if " " in keyword:
        return keyword in text
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None

