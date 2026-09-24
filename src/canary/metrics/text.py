"""Small deterministic text evaluators."""

from __future__ import annotations

import re

from canary.score import Score


def exact_match(
    observed: str,
    expected: str,
    *,
    case_sensitive: bool = True,
    case_id: str | None = None,
) -> Score:
    left = str(observed)
    right = str(expected)
    matched = left == right if case_sensitive else left.casefold() == right.casefold()
    return Score(
        name="exact_match",
        evaluator_id="canary.metrics.text.exact_match",
        evaluator_version="1",
        kind="code",
        score=1.0 if matched else 0.0,
        label="match" if matched else "mismatch",
        case_id=case_id,
        evidence={
            "observed": left,
            "expected": right,
            "caseSensitive": case_sensitive,
        },
    )


def matches_regex(
    observed: str,
    pattern: str,
    *,
    flags: int = 0,
    full_match: bool = False,
    case_id: str | None = None,
) -> Score:
    compiled = re.compile(pattern, flags)
    matched = (
        compiled.fullmatch(str(observed)) is not None
        if full_match
        else compiled.search(str(observed)) is not None
    )
    return Score(
        name="matches_regex",
        evaluator_id="canary.metrics.text.matches_regex",
        evaluator_version="1",
        kind="code",
        score=1.0 if matched else 0.0,
        label="match" if matched else "mismatch",
        case_id=case_id,
        evidence={"pattern": pattern, "fullMatch": full_match},
    )


__all__ = ["exact_match", "matches_regex"]
