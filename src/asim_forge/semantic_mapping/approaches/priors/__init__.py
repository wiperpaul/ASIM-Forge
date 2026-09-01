"""Trivial priors that establish the floor every real approach must beat."""

from .approach import (
    FieldFrequencyPriorApproach,
    MajoritySchemaPriorApproach,
    NullPriorApproach,
)

__all__ = [
    "FieldFrequencyPriorApproach",
    "MajoritySchemaPriorApproach",
    "NullPriorApproach",
]
