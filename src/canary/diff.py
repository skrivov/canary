"""Pure case/criterion score movement with label-transition findings."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field

from ._models import FrozenModel
from .ruler import Ruler, assert_same_ruler
from .score import Score

Movement = Literal["improved", "regressed", "unchanged", "incomparable"]


class CriterionDelta(FrozenModel):
    case_id: str
    criterion: str
    movement: Movement
    before_score: float | None = None
    after_score: float | None = None
    before_label: str | None = None
    after_label: str | None = None


class RunDiff(FrozenModel):
    ruler_fingerprint: str
    improved: tuple[str, ...] = ()
    regressed: tuple[str, ...] = ()
    mixed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    incomparable: tuple[str, ...] = ()
    criteria: tuple[CriterionDelta, ...] = ()
    label_transition_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)


def diff_scores(
    before: Sequence[Score],
    after: Sequence[Score],
    *,
    before_ruler: Ruler | Mapping[str, object],
    after_ruler: Ruler | Mapping[str, object],
) -> RunDiff:
    """Partition comparable cases and retain same-score label transitions."""

    ruler = assert_same_ruler(before_ruler, after_ruler)
    left = _index(before, side="before")
    right = _index(after, side="after")
    unknown_criteria = {
        criterion for _case_id, criterion in set(left) | set(right)
    } - set(ruler.criteria)
    if unknown_criteria:
        raise ValueError(
            "scores name criteria absent from the recorded ruler: "
            + ", ".join(sorted(unknown_criteria))
        )
    all_keys = sorted(set(left) | set(right))
    deltas: list[CriterionDelta] = []
    transitions: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_case: dict[str, list[Movement]] = defaultdict(list)

    for case_id, criterion in all_keys:
        mine = left.get((case_id, criterion))
        theirs = right.get((case_id, criterion))
        if mine is None or theirs is None:
            delta = CriterionDelta(
                case_id=case_id,
                criterion=criterion,
                movement="incomparable",
                before_score=mine.score if mine else None,
                after_score=theirs.score if theirs else None,
                before_label=mine.label if mine else None,
                after_label=theirs.label if theirs else None,
            )
        else:
            if mine.direction != theirs.direction:
                raise ValueError(
                    f"{case_id}/{criterion} changed direction "
                    f"{mine.direction!r} -> {theirs.direction!r}"
                )
            if (
                mine.evaluator_id,
                mine.evaluator_version,
            ) != (
                theirs.evaluator_id,
                theirs.evaluator_version,
            ):
                raise ValueError(
                    f"{case_id}/{criterion} changed evaluator identity "
                    f"{mine.evaluator_id}@{mine.evaluator_version} -> "
                    f"{theirs.evaluator_id}@{theirs.evaluator_version}"
                )
            movement = _movement(mine, theirs)
            delta = CriterionDelta(
                case_id=case_id,
                criterion=criterion,
                movement=movement,
                before_score=mine.score,
                after_score=theirs.score,
                before_label=mine.label,
                after_label=theirs.label,
            )
            transition = f"{mine.label or '<none>'} -> {theirs.label or '<none>'}"
            transitions[criterion][transition] += 1
        deltas.append(delta)
        per_case[case_id].append(delta.movement)

    buckets: dict[str, list[str]] = {
        "improved": [],
        "regressed": [],
        "mixed": [],
        "unchanged": [],
        "incomparable": [],
    }
    for case_id, movements in sorted(per_case.items()):
        comparable = [movement for movement in movements if movement != "incomparable"]
        if not comparable:
            buckets["incomparable"].append(case_id)
        elif "improved" in comparable and "regressed" in comparable:
            buckets["mixed"].append(case_id)
        elif "regressed" in comparable:
            buckets["regressed"].append(case_id)
        elif "improved" in comparable:
            buckets["improved"].append(case_id)
        else:
            buckets["unchanged"].append(case_id)

    return RunDiff(
        ruler_fingerprint=ruler.fingerprint,
        improved=tuple(buckets["improved"]),
        regressed=tuple(buckets["regressed"]),
        mixed=tuple(buckets["mixed"]),
        unchanged=tuple(buckets["unchanged"]),
        incomparable=tuple(buckets["incomparable"]),
        criteria=tuple(deltas),
        label_transition_matrix={
            criterion: dict(sorted(rows.items()))
            for criterion, rows in sorted(transitions.items())
        },
    )


def _index(scores: Sequence[Score], *, side: str) -> dict[tuple[str, str], Score]:
    result: dict[tuple[str, str], Score] = {}
    for score in scores:
        if not score.case_id:
            raise ValueError(f"{side} score {score.name!r} has no case_id")
        key = (score.case_id, score.name)
        if key in result:
            raise ValueError(f"duplicate {side} score for {key[0]}/{key[1]}")
        result[key] = score
    return result


def _movement(before: Score, after: Score) -> Movement:
    if before.score is None or after.score is None:
        return "incomparable"
    if before.score == after.score:
        return "unchanged"
    if before.direction == "maximize":
        return "improved" if after.score > before.score else "regressed"
    return "improved" if after.score < before.score else "regressed"


__all__ = ["CriterionDelta", "Movement", "RunDiff", "diff_scores"]
