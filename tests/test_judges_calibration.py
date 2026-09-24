from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from canary.calibration import (
    CalibrationRecord,
    FindingLabel,
    calibrate,
)
from canary.judge import (
    ClosedChoiceJudge,
    FindingsJudge,
    JudgeError,
    UncalibratedJudgeError,
)
from canary.model_port import Message


class QueuePort:
    def __init__(self, responses: Sequence[Mapping[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate_object(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        operation: str,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "schema": schema,
                "messages": tuple(messages),
                "operation": operation,
            }
        )
        if not self.responses:
            raise RuntimeError("fake port exhausted")
        return self.responses.pop(0)


def choice_judge(port: QueuePort, **overrides: Any) -> ClosedChoiceJudge:
    kwargs = {
        "port": port,
        "evaluator_id": "grounded",
        "evaluator_version": "1",
        "choices": {"grounded": 1.0, "hallucinated": 0.0},
        "operation": "eval.grounded",
    }
    kwargs.update(overrides)
    return ClosedChoiceJudge(**kwargs)


def finding_payload(
    *,
    criterion: str = "grounded",
    severity: str = "fatal",
    locality: str = "never_looked",
) -> dict[str, Any]:
    return {
        "findings": [
            {
                "criterion": criterion,
                "severity": severity,
                "locality": locality,
                "evidence": "tool.search",
                "complaint": "No supporting lookup was made.",
            }
        ],
        "met": [],
    }


def findings_judge(port: QueuePort, **overrides: Any) -> FindingsJudge:
    kwargs = {
        "port": port,
        "evaluator_id": "findings",
        "evaluator_version": "1",
        "criteria": ("grounded", "legible"),
        "localities": ("never_looked", "wording_only"),
        "operation": "eval.findings",
    }
    kwargs.update(overrides)
    return FindingsJudge(**kwargs)


def labelled_choices(label: str = "grounded") -> tuple[CalibrationRecord, ...]:
    return tuple(
        CalibrationRecord(
            record_id=f"record-{index}",
            mode="choice",
            messages=(Message(role="user", content=f"case {index}"),),
            expected_label=label,
            why="Exercises a labelled choice.",
        )
        for index in range(5)
    )


def labelled_findings() -> tuple[CalibrationRecord, ...]:
    return tuple(
        CalibrationRecord(
            record_id=f"record-{index}",
            mode="findings",
            messages=(Message(role="user", content=f"case {index}"),),
            expected_findings=(
                FindingLabel(
                    criterion="grounded",
                    severity="fatal",
                    locality="never_looked",
                ),
            ),
            why="Exercises a labelled finding.",
        )
        for index in range(5)
    )


def test_closed_choice_schema_is_closed_required_and_nullable() -> None:
    judge = choice_judge(QueuePort([]), allow_uncalibrated=True)
    schema = judge.output_schema
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["label", "explanation"]
    assert schema["properties"]["explanation"]["type"] == ["string", "null"]
    assert schema["properties"]["label"]["enum"] == ["grounded", "hallucinated"]


@pytest.mark.asyncio
async def test_uncalibrated_judge_fails_before_calling_port() -> None:
    port = QueuePort([{"label": "grounded", "explanation": "supported"}])
    judge = choice_judge(port)
    with pytest.raises(UncalibratedJudgeError):
        await judge.evaluate((Message(role="user", content="answer"),))
    assert port.calls == []


@pytest.mark.asyncio
async def test_authoring_mode_is_loud_in_score_artifact() -> None:
    judge = choice_judge(
        QueuePort([{"label": "grounded", "explanation": "supported"}]),
        allow_uncalibrated=True,
    )
    score = await judge.evaluate((Message(role="user", content="answer"),))
    assert score.score == 1.0
    assert score.evidence["calibration"] == {
        "status": "uncalibrated",
        "allowUncalibrated": True,
    }


@pytest.mark.asyncio
async def test_off_rubric_label_repairs_then_refuses_instead_of_passing() -> None:
    port = QueuePort(
        [
            {"label": "maybe", "explanation": "unclear"},
            {"label": "still-maybe", "explanation": "unclear"},
        ]
    )
    judge = choice_judge(port, allow_uncalibrated=True)
    score = await judge.evaluate((Message(role="user", content="answer"),))
    assert score.score is None
    assert score.label is None
    assert score.evidence["judgeStatus"] == "refused"
    assert score.evidence["modelAttempts"] == 2
    assert [call["operation"] for call in port.calls] == [
        "eval.grounded",
        "eval.grounded.repair",
    ]


@pytest.mark.asyncio
async def test_invalid_first_object_can_repair_to_closed_choice() -> None:
    port = QueuePort(
        [
            {"label": "outside", "explanation": "bad"},
            {"label": "grounded", "explanation": "fixed"},
        ]
    )
    score = await choice_judge(
        port, allow_uncalibrated=True
    ).evaluate((Message(role="user", content="answer"),))
    assert score.score == 1.0
    assert score.label == "grounded"
    assert score.evidence["modelAttempts"] == 2


@pytest.mark.asyncio
async def test_calibration_licenses_only_the_exact_passing_judge() -> None:
    responses = [
        {"label": "grounded", "explanation": "supported"} for _ in range(6)
    ]
    port = QueuePort(responses)
    authoring = choice_judge(port, allow_uncalibrated=True)
    report = await calibrate(authoring, labelled_choices())
    assert report.calibrated
    assert report.aggregate_agreement == 1.0
    assert report.records_available == 5
    assert report.per_label["grounded"].agreement == 1.0

    active = authoring.with_calibration(report)
    score = await active.evaluate((Message(role="user", content="answer"),))
    assert score.score == 1.0
    assert score.evidence["calibration"]["calibrationId"] == report.calibration_id

    drifted = choice_judge(
        QueuePort([{"label": "grounded", "explanation": "supported"}]),
        choices={"grounded": 1.0, "hallucinated": 0.0, "mixed": 0.5},
        calibration=report,
    )
    with pytest.raises(UncalibratedJudgeError):
        await drifted.evaluate((Message(role="user", content="answer"),))


@pytest.mark.asyncio
async def test_failed_calibration_cannot_activate_judge() -> None:
    port = QueuePort(
        [{"label": "hallucinated", "explanation": "wrong"} for _ in range(5)]
    )
    authoring = choice_judge(port, allow_uncalibrated=True)
    report = await calibrate(authoring, labelled_choices())
    assert not report.calibrated
    assert report.aggregate_agreement == 0.0
    with pytest.raises(UncalibratedJudgeError):
        await authoring.with_calibration(report).evaluate(
            (Message(role="user", content="answer"),)
        )


@pytest.mark.asyncio
async def test_too_few_records_never_calibrates_even_at_full_agreement() -> None:
    port = QueuePort(
        [{"label": "grounded", "explanation": "right"} for _ in range(2)]
    )
    report = await calibrate(
        choice_judge(port, allow_uncalibrated=True),
        labelled_choices()[:2],
    )
    assert report.aggregate_agreement == 1.0
    assert not report.enough_records
    assert not report.calibrated


@pytest.mark.asyncio
async def test_valid_null_scored_choice_still_counts_as_a_calibration_reading() -> None:
    port = QueuePort(
        [{"label": "abstain", "explanation": "not scoreable"} for _ in range(5)]
    )
    judge = choice_judge(
        port,
        choices={"abstain": None, "grounded": 1.0},
        allow_uncalibrated=True,
    )
    records = labelled_choices("abstain")
    report = await calibrate(judge, records)
    assert report.records_available == 5
    assert report.aggregate_agreement == 1.0
    assert report.calibrated


@pytest.mark.asyncio
async def test_calibration_identity_includes_labelled_input_content() -> None:
    first_port = QueuePort(
        [{"label": "grounded", "explanation": "right"} for _ in range(5)]
    )
    second_port = QueuePort(
        [{"label": "grounded", "explanation": "right"} for _ in range(5)]
    )
    original = labelled_choices()
    changed = tuple(
        record.model_copy(
            update={
                "messages": (
                    Message(role="user", content=f"changed {record.record_id}"),
                )
            }
        )
        for record in original
    )
    first = await calibrate(
        choice_judge(first_port, allow_uncalibrated=True), original
    )
    second = await calibrate(
        choice_judge(second_port, allow_uncalibrated=True), changed
    )
    assert first.calibration_id != second.calibration_id


def test_findings_schema_is_closed_at_every_object_level() -> None:
    schema = findings_judge(QueuePort([]), allow_uncalibrated=True).output_schema
    assert schema["additionalProperties"] is False
    finding = schema["properties"]["findings"]["items"]
    assert finding["additionalProperties"] is False
    assert set(finding["required"]) == set(finding["properties"])
    assert schema["required"] == ["findings", "met"]


@pytest.mark.asyncio
async def test_findings_judge_falsifies_off_rubric_finding() -> None:
    port = QueuePort(
        [
            finding_payload(criterion="invented"),
            finding_payload(criterion="still_invented"),
        ]
    )
    result = await findings_judge(
        port, allow_uncalibrated=True
    ).evaluate((Message(role="user", content="answer"),))
    assert not result.available
    assert result.findings == ()
    assert len(result.evidence["errors"]) == 2


@pytest.mark.asyncio
async def test_findings_calibration_preserves_evidence_and_activates() -> None:
    port = QueuePort([finding_payload() for _ in range(6)])
    authoring = findings_judge(port, allow_uncalibrated=True)
    report = await calibrate(authoring, labelled_findings())
    assert report.calibrated
    active = authoring.with_calibration(report)
    result = await active.evaluate((Message(role="user", content="answer"),))
    assert result.available
    assert result.findings[0].complaint == "No supporting lookup was made."
    assert result.evidence["calibration"]["calibrationId"] == report.calibration_id


@pytest.mark.asyncio
async def test_finding_wins_over_same_criterion_in_met() -> None:
    payload = finding_payload()
    payload["met"] = ["grounded", "legible"]
    result = await findings_judge(
        QueuePort([payload]), allow_uncalibrated=True
    ).evaluate((Message(role="user", content="answer"),))
    assert result.met == ("legible",)


@pytest.mark.asyncio
async def test_prompt_substitutions_are_strict() -> None:
    judge = choice_judge(
        QueuePort([{"label": "grounded", "explanation": "right"}]),
        prompt_messages=(
            Message(role="user", content="Input: {{input}}\nOutput: {{output}}"),
        ),
        allow_uncalibrated=True,
    )
    with pytest.raises(JudgeError, match="output"):
        await judge.evaluate((), inputs={"input": "record"})
    score = await judge.evaluate(
        (), inputs={"input": "record", "output": "answer"}
    )
    assert score.score == 1.0
    sent = judge.port.calls[-1]["messages"][0].content
    assert sent == "Input: record\nOutput: answer"
