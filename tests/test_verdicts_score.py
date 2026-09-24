from __future__ import annotations

import warnings

from pydantic import ValidationError
import pytest

from canary._models import FrozenModel
from canary.score import Score, WorldRef, outcome_id
from canary.verdicts import (
    LOUD_SUBTYPES,
    SAFETY_FLAGS,
    SILENT_SUBTYPES,
    TAXONOMY_VERSION,
    VerdictRecord,
)


def test_taxonomy_is_closed_and_versioned() -> None:
    assert TAXONOMY_VERSION == "canary-taxonomy/1"
    assert len(LOUD_SUBTYPES) == 4
    assert len(SILENT_SUBTYPES) == 10
    assert len(SAFETY_FLAGS) == 4
    with pytest.raises(ValidationError):
        VerdictRecord(verdict="silent_wrong", subtype="typo")


@pytest.mark.parametrize(
    ("verdict", "subtype"),
    [
        ("correct", "wrong_value"),
        ("correct", "runtime_error"),
        ("loud_fail", "wrong_value"),
        ("silent_wrong", "runtime_error"),
        ("loud_fail", None),
        ("silent_wrong", None),
    ],
)
def test_subtypes_cannot_cross_verdict_classes(
    verdict: str, subtype: str | None
) -> None:
    with pytest.raises(ValidationError):
        VerdictRecord(verdict=verdict, subtype=subtype)


def test_score_camel_case_round_trip_and_direction() -> None:
    world = WorldRef(
        name="fixture",
        revision="v7",
        content_hash="sha256:" + "a" * 64,
        revisions={"catalog": "v3"},
    )
    score = Score(
        name="accuracy",
        evaluator_id="judge",
        evaluator_version="2",
        kind="llm",
        direction="minimize",
        score=0.25,
        label="hallucinated",
        world=world,
        case_id="case-1",
        run_id="run-1",
    )
    payload = score.model_dump(by_alias=True, mode="json")
    assert payload["evaluatorId"] == "judge"
    assert payload["direction"] == "minimize"
    assert payload["world"]["contentHash"].startswith("sha256:")
    assert Score.model_validate(payload) == score


def test_missing_score_is_not_zero() -> None:
    common = {
        "name": "criterion",
        "evaluator_id": "e",
        "evaluator_version": "1",
        "kind": "code",
    }
    missing = Score(**common, score=None)
    failed = Score(**common, score=0.0)
    assert missing != failed
    assert missing.score is None
    assert failed.score == 0.0


def test_non_finite_scores_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Score(
            name="criterion",
            evaluator_id="e",
            evaluator_version="1",
            kind="code",
            score=float("nan"),
        )


def test_outcome_id_is_deterministic_and_versioned() -> None:
    assert outcome_id("trace-1", "grounded", "1") == "eval:trace-1:grounded:1"
    assert outcome_id("trace-1", "grounded", "1") == outcome_id(
        "trace-1", "grounded", "1"
    )
    assert outcome_id("trace-1", "grounded", "2") != outcome_id(
        "trace-1", "grounded", "1"
    )
    with pytest.raises(ValueError):
        outcome_id("", "grounded", "1")


def test_records_never_warn_about_field_names_at_import() -> None:
    """Applications that run with warnings as errors must be able to import
    canary on every supported pydantic. Pydantic 2.7-2.9 warn about any
    ``model_*`` field (``Usage.model_calls``); current releases still warn
    about ``model_dump*`` and ``model_validate*`` names by default."""

    with warnings.catch_warnings():
        warnings.simplefilter("error")

        class Probe(FrozenModel):
            model_calls: int = 0
            model_dump_mode: str = "json"

    assert Probe().model_dump(by_alias=True) == {"modelCalls": 0, "modelDumpMode": "json"}
