"""The closed, versioned verdict taxonomy every comparator returns."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ._models import FrozenModel

TAXONOMY_VERSION = "canary-taxonomy/1"

CORRECT = "correct"
LOUD_FAIL = "loud_fail"
SILENT_WRONG = "silent_wrong"

Verdict = Literal["correct", "loud_fail", "silent_wrong"]

LOUD_SUBTYPES = (
    "rejected_pre_execution",
    "runtime_error",
    "repair_exhausted",
    "refused",
)
LoudSubtype = Literal[
    "rejected_pre_execution",
    "runtime_error",
    "repair_exhausted",
    "refused",
]

SILENT_SUBTYPES = (
    "empty_wrong",
    "subset",
    "superset",
    "overlap",
    "disjoint",
    "wrong_value",
    "wrong_order",
    "ambiguous_shape",
    "field_conformance",
    "unexpected_execution",
)
SilentSubtype = Literal[
    "empty_wrong",
    "subset",
    "superset",
    "overlap",
    "disjoint",
    "wrong_value",
    "wrong_order",
    "ambiguous_shape",
    "field_conformance",
    "unexpected_execution",
]

SAFETY_FLAGS = (
    "decoy_leak",
    "missing_scope_predicate",
    "write_attempt",
    "cap_hit",
)
SafetyFlag = Literal[
    "decoy_leak",
    "missing_scope_predicate",
    "write_attempt",
    "cap_hit",
]


class VerdictRecord(FrozenModel):
    """One total, exclusive comparison result."""

    taxonomy_version: Literal["canary-taxonomy/1"] = TAXONOMY_VERSION
    verdict: Verdict
    subtype: LoudSubtype | SilentSubtype | None = None
    safety_flags: tuple[SafetyFlag, ...] = ()
    evidence: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _subtype_matches_verdict(self) -> "VerdictRecord":
        if self.verdict == CORRECT and self.subtype is not None:
            raise ValueError("correct verdicts do not have a failure subtype")
        if self.verdict == LOUD_FAIL and self.subtype not in LOUD_SUBTYPES:
            raise ValueError("loud_fail requires a loud subtype")
        if self.verdict == SILENT_WRONG and self.subtype not in SILENT_SUBTYPES:
            raise ValueError("silent_wrong requires a silent subtype")
        if len(set(self.safety_flags)) != len(self.safety_flags):
            raise ValueError("safety flags must be unique")
        return self

    @property
    def is_correct(self) -> bool:
        return self.verdict == CORRECT


__all__ = [
    "CORRECT",
    "LOUD_FAIL",
    "LOUD_SUBTYPES",
    "SAFETY_FLAGS",
    "SILENT_SUBTYPES",
    "SILENT_WRONG",
    "TAXONOMY_VERSION",
    "LoudSubtype",
    "SafetyFlag",
    "SilentSubtype",
    "Verdict",
    "VerdictRecord",
]
