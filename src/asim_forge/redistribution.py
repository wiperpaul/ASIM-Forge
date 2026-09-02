"""Machine-actionable redistribution classes for evaluation evidence.

Some of the most useful corpora may be evaluated locally but not republished. The
Elastic integrations are Elastic Licence 2.0, LogHub 2.0 restricts use to research,
AIT-LDS is CC BY-NC-SA, and several community repositories carry no root licence at
all. Recording that as prose in a `terms` string does not stop a release from
publishing derived content.

A redistribution class is therefore a declared property of every corpus, and the
report writers enforce it rather than trusting the caller to remember.
"""

from __future__ import annotations

from typing import Literal

RedistributionClass = Literal["content", "derived", "metrics", "none"]

REDISTRIBUTION_CLASSES: tuple[RedistributionClass, ...] = (
    "content",
    "derived",
    "metrics",
    "none",
)

DESCRIPTIONS: dict[RedistributionClass, str] = {
    "content": "Source content, derived artefacts, and metrics may all be published.",
    "derived": (
        "Derived artefacts such as templates, predictions, and evidence may be published; "
        "the source content may not."
    ),
    "metrics": (
        "Aggregate metrics and the acquisition manifest may be published; "
        "no source content and no per-case output."
    ),
    "none": "Nothing derived from this corpus may be published, including metrics.",
}

# Increasing permissiveness, so a report can take the strictest class it contains.
_RANK: dict[RedistributionClass, int] = {
    "none": 0,
    "metrics": 1,
    "derived": 2,
    "content": 3,
}


class RedistributionError(RuntimeError):
    """Raised when an artefact would publish more than its licence permits."""


def strictest(classes: list[RedistributionClass]) -> RedistributionClass:
    """The least permissive class in a set, which governs a combined artefact."""
    if not classes:
        return "none"
    return min(classes, key=lambda value: _RANK[value])


def permits_per_case_output(value: RedistributionClass) -> bool:
    """Whether predictions, evidence strings, and templates may leave the machine."""
    return _RANK[value] >= _RANK["derived"]


def permits_publication(value: RedistributionClass) -> bool:
    """Whether any result at all may be published."""
    return _RANK[value] >= _RANK["metrics"]


def require_publishable(value: RedistributionClass, subject: str) -> None:
    if not permits_publication(value):
        raise RedistributionError(
            f"{subject} is classed {value!r}: {DESCRIPTIONS[value]} "
            "Evaluate it locally and publish only the manifest reference."
        )
