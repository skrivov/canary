"""Pure ceil(2n/3) stability arithmetic and n-sensitivity."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from pydantic import Field

from ._models import FrozenModel
from .score import OptimizationDirection


class BarResult(FrozenModel):
    attempts: int = Field(ge=1)
    successes: int = Field(ge=0)
    required: int = Field(ge=1)
    strictness: float = Field(gt=0.0, le=1.0)
    passed: bool


class SensitivityPoint(FrozenModel):
    attempts: int
    required: int
    strictness: float
    reporting_probability: float


def required_successes(n: int) -> int:
    if n < 1:
        raise ValueError("n must be positive")
    return math.ceil(2 * n / 3)


def threshold_strictness(n: int) -> float:
    return required_successes(n) / n


def bar(outcomes: Iterable[bool]) -> BarResult:
    values = tuple(bool(outcome) for outcome in outcomes)
    if not values:
        raise ValueError("at least one attempt is required")
    required = required_successes(len(values))
    successes = sum(values)
    return BarResult(
        attempts=len(values),
        successes=successes,
        required=required,
        strictness=required / len(values),
        passed=successes >= required,
    )


def score_bar(
    scores: Sequence[float | None],
    *,
    threshold: float,
    direction: OptimizationDirection = "maximize",
) -> BarResult:
    """Apply the stability bar; unscoreable attempts cannot count as success."""

    if direction == "maximize":
        outcomes = [score is not None and score >= threshold for score in scores]
    else:
        outcomes = [score is not None and score <= threshold for score in scores]
    return bar(outcomes)


def reporting_probability(rate: float, n: int) -> float:
    """Probability the bar reports success at an independent success rate."""

    if not 0.0 <= rate <= 1.0:
        raise ValueError("rate must be between 0 and 1")
    need = required_successes(n)
    return sum(
        math.comb(n, successes)
        * rate**successes
        * (1.0 - rate) ** (n - successes)
        for successes in range(need, n + 1)
    )


def n_sensitivity(
    rate: float, sample_sizes: Iterable[int]
) -> tuple[SensitivityPoint, ...]:
    """Show how the same underlying rate moves under different sample sizes."""

    return tuple(
        SensitivityPoint(
            attempts=n,
            required=required_successes(n),
            strictness=threshold_strictness(n),
            reporting_probability=reporting_probability(rate, n),
        )
        for n in sample_sizes
    )


__all__ = [
    "BarResult",
    "SensitivityPoint",
    "bar",
    "n_sensitivity",
    "reporting_probability",
    "required_successes",
    "score_bar",
    "threshold_strictness",
]
