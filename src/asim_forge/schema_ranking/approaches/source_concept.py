"""Auditable schema ranking from normalized source concepts."""

from __future__ import annotations

from typing import Literal

from ...source_semantics import source_tokens
from ..contracts import (
    SchemaRankingAbstention,
    SchemaRankingApproachIdentity,
    SchemaRankingCandidate,
    SchemaRankingEvidence,
    SchemaRankingPrediction,
    SchemaRankingRequest,
)

DEFAULT_SCHEMA_NAMES = ("Authentication", "NetworkSession", "AuditEvent")

_SCHEMA_CONCEPTS: dict[str, frozenset[str]] = {
    "Authentication": frozenset(
        {
            "auth",
            "authentication",
            "credential",
            "login",
            "logon",
            "logout",
            "password",
            "signedin",
        }
    ),
    "NetworkSession": frozenset(
        {
            "connection",
            "destination",
            "firewall",
            "flow",
            "network",
            "session",
            "source",
            "traffic",
        }
    ),
    "AuditEvent": frozenset(
        {
            "audit",
            "configuration",
            "create",
            "delete",
            "disable",
            "enable",
            "modify",
            "policy",
            "update",
        }
    ),
}


class SourceConceptSchemaRanker:
    """Rank candidate schemas using only normalized concepts in a cluster template."""

    identity = SchemaRankingApproachIdentity(name="source-concept", version="1")

    def rank(self, request: SchemaRankingRequest) -> SchemaRankingPrediction:
        source_concepts = source_tokens(request.template)
        scored: list[tuple[str, list[str]]] = []
        for schema_name in request.candidate_schemas:
            schema_concepts = _SCHEMA_CONCEPTS.get(schema_name)
            if schema_concepts is None:
                schema_concepts = frozenset(source_tokens(schema_name))
            scored.append((schema_name, sorted(source_concepts & schema_concepts)))
        scored.sort(key=lambda item: (-len(item[1]), item[0]))

        total = sum(len(evidence) for _, evidence in scored)
        candidates = [
            SchemaRankingCandidate(
                schema_name=schema_name,
                score=len(evidence),
                confidence=round(len(evidence) / total, 6) if total else 0,
                evidence=[SchemaRankingEvidence(concept=concept) for concept in evidence],
            )
            for schema_name, evidence in scored
        ]
        best = candidates[0]
        if best.score == 0:
            return self._abstain(
                request, candidates, "no_evidence", "No schema had source-concept evidence."
            )
        if len(candidates) > 1 and candidates[1].score == best.score:
            return self._abstain(
                request, candidates, "tied_top", "Multiple schemas had equal leading evidence."
            )
        return SchemaRankingPrediction(
            request_id=request.request_id,
            approach=self.identity,
            disposition="ranked",
            selected_schema=best.schema_name,
            confidence=best.confidence,
            ranked_schemas=candidates,
        )

    def _abstain(
        self,
        request: SchemaRankingRequest,
        candidates: list[SchemaRankingCandidate],
        reason: Literal["no_evidence", "tied_top"],
        detail: str,
    ) -> SchemaRankingPrediction:
        return SchemaRankingPrediction(
            request_id=request.request_id,
            approach=self.identity,
            disposition="abstained",
            confidence=0,
            ranked_schemas=candidates,
            abstention=SchemaRankingAbstention(reason=reason, detail=detail),
        )
