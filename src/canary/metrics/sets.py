"""Set-relation arithmetic exposed independently of the comparator."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from canary.score import Score

SetRelation = Literal["exact", "empty_wrong", "subset", "superset", "overlap", "disjoint"]


def set_relation(observed: Iterable[str], expected: Iterable[str]) -> SetRelation:
    """Classify one observed set against the expected set."""

    got = {str(value) for value in observed}
    want = {str(value) for value in expected}
    if got == want:
        return "exact"
    if not got:
        return "empty_wrong"
    if got < want:
        return "subset"
    if got > want:
        return "superset"
    if got & want:
        return "overlap"
    return "disjoint"


def id_set_score(
    observed: Iterable[str],
    expected: Iterable[str],
    *,
    case_id: str | None = None,
) -> Score:
    """Score exact id-set equality and retain relation diagnostics."""

    got = {str(value) for value in observed}
    want = {str(value) for value in expected}
    hit = len(got & want)
    precision = hit / len(got) if got else (1.0 if not want else 0.0)
    recall = hit / len(want) if want else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    relation = set_relation(got, want)
    return Score(
        name="id_set_exact",
        evaluator_id="canary.metrics.sets",
        evaluator_version="1",
        kind="code",
        score=1.0 if relation == "exact" else 0.0,
        label=relation,
        case_id=case_id,
        evidence={
            "observed": sorted(got),
            "expected": sorted(want),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
    )


__all__ = ["SetRelation", "id_set_score", "set_relation"]
