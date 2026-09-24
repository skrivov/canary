from __future__ import annotations

import pytest

from canary.diff import diff_scores
from canary.ruler import (
    Ruler,
    RulerError,
    RulerMismatchError,
    assert_same_ruler,
    compare_rulers,
)
from canary.score import Score


def ruler(**overrides: object) -> Ruler:
    values = {
        "taxonomy_version": "canary-taxonomy/1",
        "judge_rubric_hashes": {"quality": "sha256:" + "a" * 64},
        "calibration_ids": {"quality": "sha256:" + "b" * 64},
        "criteria": ("quality", "risk"),
        "freeze_id": "sha256:" + "c" * 64,
    }
    values.update(overrides)
    return Ruler(**values)


def artifact(value: Ruler) -> dict[str, object]:
    return {"ruler": value.model_dump(by_alias=True, mode="json")}


def score(
    case_id: str,
    name: str,
    value: float | None,
    *,
    label: str | None = None,
    direction: str = "maximize",
) -> Score:
    return Score(
        name=name,
        evaluator_id=f"e.{name}",
        evaluator_version="1",
        kind="code",
        direction=direction,  # type: ignore[arg-type]
        score=value,
        label=label,
        case_id=case_id,
    )


def test_ruler_is_read_from_artifact_and_fingerprinted() -> None:
    value = ruler()
    assert Ruler.from_artifact(artifact(value)) == value
    assert value.fingerprint == ruler().fingerprint
    comparison = compare_rulers(artifact(value), artifact(ruler()))
    assert comparison.matched
    assert comparison.changes == ()


def test_missing_or_changed_ruler_refuses_legibly() -> None:
    with pytest.raises(RulerError, match="no ruler"):
        Ruler.from_artifact({})
    changed = ruler(
        calibration_ids={"quality": "sha256:" + "d" * 64},
        taxonomy_version="canary-taxonomy/2",
    )
    comparison = compare_rulers(ruler(), changed)
    fields = {change.field for change in comparison.changes}
    assert fields == {"calibrationIds.quality", "taxonomyVersion"}
    with pytest.raises(RulerMismatchError) as captured:
        assert_same_ruler(ruler(), changed)
    assert "calibrationIds.quality" in str(captured.value)
    assert "taxonomyVersion" in str(captured.value)


def test_diff_partitions_improved_regressed_mixed_and_unchanged() -> None:
    before = (
        score("improved", "quality", 0.2, label="bad"),
        score("regressed", "quality", 0.9, label="good"),
        score("mixed", "quality", 0.2, label="bad"),
        score("mixed", "risk", 0.9, label="safe"),
        score("unchanged", "quality", 0.5, label="wrong_a"),
        score("unchanged", "risk", 0.5, label="same"),
    )
    after = (
        score("improved", "quality", 0.8, label="good"),
        score("regressed", "quality", 0.1, label="bad"),
        score("mixed", "quality", 0.8, label="good"),
        score("mixed", "risk", 0.1, label="risky"),
        score("unchanged", "quality", 0.5, label="wrong_b"),
        score("unchanged", "risk", 0.5, label="same"),
    )
    result = diff_scores(
        before,
        after,
        before_ruler=ruler(),
        after_ruler=ruler(),
    )
    assert result.improved == ("improved",)
    assert result.regressed == ("regressed",)
    assert result.mixed == ("mixed",)
    assert result.unchanged == ("unchanged",)
    assert result.incomparable == ()
    assert (
        result.label_transition_matrix["quality"]["wrong_a -> wrong_b"] == 1
    )


def test_same_score_different_failure_label_is_preserved_as_a_finding() -> None:
    result = diff_scores(
        (score("case", "quality", 0.0, label="subset"),),
        (score("case", "quality", 0.0, label="disjoint"),),
        before_ruler=ruler(),
        after_ruler=ruler(),
    )
    assert result.unchanged == ("case",)
    assert result.criteria[0].movement == "unchanged"
    assert result.label_transition_matrix == {
        "quality": {"subset -> disjoint": 1}
    }


def test_minimize_direction_is_compared_in_the_right_direction() -> None:
    result = diff_scores(
        (score("case", "risk", 0.8, direction="minimize"),),
        (score("case", "risk", 0.2, direction="minimize"),),
        before_ruler=ruler(),
        after_ruler=ruler(),
    )
    assert result.improved == ("case",)


def test_missing_or_unscoreable_criteria_are_incomparable() -> None:
    result = diff_scores(
        (
            score("missing", "quality", 0.2),
            score("none", "quality", None),
        ),
        (score("none", "quality", 0.8),),
        before_ruler=ruler(),
        after_ruler=ruler(),
    )
    assert result.incomparable == ("missing", "none")
    assert {delta.movement for delta in result.criteria} == {"incomparable"}


def test_diff_refuses_before_comparing_scores_when_ruler_changed() -> None:
    with pytest.raises(RulerMismatchError):
        diff_scores(
            (score("case", "quality", 0.0),),
            (score("case", "quality", 1.0),),
            before_ruler=ruler(),
            after_ruler=ruler(criteria=("quality",)),
        )


def test_duplicate_or_unidentified_scores_are_rejected() -> None:
    duplicate = score("case", "quality", 0.0)
    with pytest.raises(ValueError, match="duplicate"):
        diff_scores(
            (duplicate, duplicate),
            (duplicate,),
            before_ruler=ruler(),
            after_ruler=ruler(),
        )


def test_scores_outside_ruler_and_evaluator_identity_drift_are_rejected() -> None:
    with pytest.raises(ValueError, match="absent from the recorded ruler"):
        diff_scores(
            (score("case", "new_criterion", 0.0),),
            (score("case", "new_criterion", 1.0),),
            before_ruler=ruler(),
            after_ruler=ruler(),
        )
    before = score("case", "quality", 0.0)
    after = before.model_copy(
        update={"score": 1.0, "evaluator_version": "2"}
    )
    with pytest.raises(ValueError, match="changed evaluator identity"):
        diff_scores(
            (before,),
            (after,),
            before_ruler=ruler(),
            after_ruler=ruler(),
        )
    unidentified = Score(
        name="quality",
        evaluator_id="e",
        evaluator_version="1",
        kind="code",
        score=1.0,
    )
    with pytest.raises(ValueError, match="no case_id"):
        diff_scores(
            (unidentified,),
            (),
            before_ruler=ruler(),
            after_ruler=ruler(),
        )
