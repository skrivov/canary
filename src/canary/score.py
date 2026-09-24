"""A provider-neutral normal form for evaluator outcomes."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ._models import FrozenModel

EvaluatorKind = Literal["code", "llm", "human"]
OptimizationDirection = Literal["maximize", "minimize"]


class WorldRef(FrozenModel):
    """The named, content-addressed world against which an evaluation ran."""

    name: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    revisions: dict[str, str] = Field(default_factory=dict)


class Score(FrozenModel):
    """One re-scorable evaluator result.

    A missing score means not scoreable. It is deliberately distinct from zero.
    """

    name: str = Field(min_length=1)
    evaluator_id: str = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    kind: EvaluatorKind
    direction: OptimizationDirection = "maximize"
    score: float | None = None
    label: str | None = None
    explanation: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    world: WorldRef | None = None
    dataset: str | None = None
    case_id: str | None = None
    run_id: str | None = None

    @field_validator(
        "dataset",
        "case_id",
        "run_id",
        "label",
        "explanation",
        mode="before",
    )
    @classmethod
    def _empty_strings_are_absent(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _finite_score(self) -> "Score":
        if self.score is not None and not math.isfinite(self.score):
            raise ValueError("score must be finite")
        return self


def outcome_id(run_id: str, evaluator_id: str, version: str) -> str:
    """Return the deterministic consumer row identity for one evaluator run."""

    parts = (run_id.strip(), evaluator_id.strip(), version.strip())
    if not all(parts):
        raise ValueError("run_id, evaluator_id, and version must be non-empty")
    return f"eval:{parts[0]}:{parts[1]}:{parts[2]}"


__all__ = [
    "EvaluatorKind",
    "OptimizationDirection",
    "Score",
    "WorldRef",
    "outcome_id",
]
