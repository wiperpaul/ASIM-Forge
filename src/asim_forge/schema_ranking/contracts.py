"""Provider-neutral contracts for ranking an event cluster against target schemas."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ..models import StrictModel


class SchemaRankingRequest(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")
    template: str = Field(min_length=1)
    candidate_schemas: list[str] = Field(min_length=1)

    @field_validator("candidate_schemas")
    @classmethod
    def candidate_schemas_must_be_unique_and_valid(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("candidate schemas must be unique")
        if any(
            not value or not value[0].isalpha() or not value.replace("_", "").isalnum()
            for value in values
        ):
            raise ValueError("candidate schemas must be identifier-like names")
        return values


class SchemaRankingApproachIdentity(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")
    version: str = Field(min_length=1)


class SchemaRankingEvidence(StrictModel):
    kind: Literal["source_concept"] = "source_concept"
    concept: str = Field(min_length=1)
    weight: int = Field(default=1, ge=1)


class SchemaRankingCandidate(StrictModel):
    schema_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    score: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    evidence: list[SchemaRankingEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def evidence_must_explain_score(self) -> SchemaRankingCandidate:
        if sum(item.weight for item in self.evidence) != self.score:
            raise ValueError("schema evidence weights must sum to score")
        return self


class SchemaRankingAbstention(StrictModel):
    reason: Literal["no_evidence", "tied_top"]
    detail: str = Field(min_length=1)


class SchemaRankingPrediction(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")
    approach: SchemaRankingApproachIdentity
    disposition: Literal["ranked", "abstained"]
    selected_schema: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    confidence: float = Field(ge=0, le=1)
    ranked_schemas: list[SchemaRankingCandidate] = Field(min_length=1)
    abstention: SchemaRankingAbstention | None = None

    @model_validator(mode="after")
    def selection_or_abstention_must_be_consistent(self) -> SchemaRankingPrediction:
        names = [candidate.schema_name for candidate in self.ranked_schemas]
        if len(names) != len(set(names)):
            raise ValueError("ranked schema candidates must be unique")
        if not _scores_are_descending(self.ranked_schemas):
            raise ValueError("ranked schema candidate scores must be descending")
        if self.disposition == "ranked":
            if self.selected_schema is None or self.abstention is not None:
                raise ValueError("ranked predictions require a selection and no abstention")
            if self.ranked_schemas[0].schema_name != self.selected_schema:
                raise ValueError("selected schema must head the ranking")
            if self.ranked_schemas[0].score == 0:
                raise ValueError("selected schema must have positive evidence")
            if self.confidence != self.ranked_schemas[0].confidence:
                raise ValueError("prediction confidence must match the selected schema")
        elif self.selected_schema is not None or self.abstention is None or self.confidence != 0:
            raise ValueError("abstained predictions require zero confidence and an abstention")
        return self


class SchemaRankingApproach(Protocol):
    identity: SchemaRankingApproachIdentity

    def rank(self, request: SchemaRankingRequest) -> SchemaRankingPrediction: ...


def _scores_are_descending(candidates: Sequence[SchemaRankingCandidate]) -> bool:
    return all(
        candidate.score >= following.score
        for candidate, following in zip(candidates, candidates[1:], strict=False)
    )
