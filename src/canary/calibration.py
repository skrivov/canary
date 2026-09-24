"""Calibration artifacts that license one exact judge to score."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from ._models import FrozenModel
from .hashing import content_hash
from .model_port import Message

CALIBRATION_SCHEMA_VERSION = "canary-calibration/v1"
SCORE_AGREEMENT_FLOOR = 0.8
MINIMUM_RECORDS = 5


class CalibrationError(ValueError):
    """A calibration set or result cannot license scoring."""


class FindingLabel(FrozenModel):
    criterion: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    locality: str = Field(min_length=1)

    @property
    def key(self) -> str:
        return f"{self.criterion}:{self.severity}:{self.locality}"


class CalibrationRecord(FrozenModel):
    """One hand-labelled judge input."""

    record_id: str = Field(min_length=1)
    mode: Literal["choice", "findings"]
    messages: tuple[Message, ...] = ()
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_label: str | None = None
    expected_findings: tuple[FindingLabel, ...] = ()
    why: str = Field(min_length=1)

    @model_validator(mode="after")
    def _expectation_matches_mode(self) -> "CalibrationRecord":
        if self.mode == "choice" and not self.expected_label:
            raise ValueError("choice calibration records require expected_label")
        if self.mode == "choice" and self.expected_findings:
            raise ValueError("choice records cannot carry expected_findings")
        if self.mode == "findings" and self.expected_label is not None:
            raise ValueError("findings records cannot carry expected_label")
        if len({finding.key for finding in self.expected_findings}) != len(
            self.expected_findings
        ):
            raise ValueError("expected findings must be unique")
        return self


class CalibrationOutcome(FrozenModel):
    record_id: str
    available: bool
    agreed: bool | None = None
    expected_label: str | None = None
    actual_label: str | None = None
    expected_findings: tuple[FindingLabel, ...] = ()
    actual_findings: tuple[FindingLabel, ...] = ()
    error: str | None = None


class Agreement(FrozenModel):
    records: int = Field(ge=0)
    agreed: int = Field(ge=0)
    agreement: float = Field(ge=0.0, le=1.0)


class CalibrationReport(FrozenModel):
    schema_version: Literal["canary-calibration/v1"] = CALIBRATION_SCHEMA_VERSION
    calibration_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    judge_id: str = Field(min_length=1)
    judge_version: str = Field(min_length=1)
    rubric_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    mode: Literal["choice", "findings"]
    minimum_records: int = Field(ge=1)
    agreement_floor: float = Field(ge=0.0, le=1.0)
    records_total: int = Field(ge=0)
    records_available: int = Field(ge=0)
    aggregate_agreement: float = Field(ge=0.0, le=1.0)
    enough_records: bool
    calibrated: bool
    per_label: dict[str, Agreement] = Field(default_factory=dict)
    outcomes: tuple[CalibrationOutcome, ...] = ()

    def applies_to(
        self, *, judge_id: str, judge_version: str, rubric_hash: str
    ) -> bool:
        return (
            self.calibrated
            and self.judge_id == judge_id
            and self.judge_version == judge_version
            and self.rubric_hash == rubric_hash
        )


class CalibratableJudge(Protocol):
    evaluator_id: str
    evaluator_version: str
    rubric_hash: str
    mode: Literal["choice", "findings"]
    choice_labels: tuple[str, ...]

    async def _evaluate_uncalibrated(
        self,
        messages: Sequence[Message],
        *,
        inputs: Mapping[str, Any] | None = None,
        case_id: str | None = None,
    ) -> Any:
        ...


async def calibrate(
    judge: CalibratableJudge,
    labelled_records: Sequence[CalibrationRecord],
    *,
    agreement_floor: float = SCORE_AGREEMENT_FLOOR,
    minimum_records: int = MINIMUM_RECORDS,
) -> CalibrationReport:
    """Run labelled records and bind the result to the exact judge identity."""

    if not labelled_records:
        raise CalibrationError("the calibration set has no records")
    if not 0.0 <= agreement_floor <= 1.0:
        raise CalibrationError("agreement_floor must be between 0 and 1")
    if minimum_records < 1:
        raise CalibrationError("minimum_records must be positive")
    seen: set[str] = set()
    for record in labelled_records:
        if record.record_id in seen:
            raise CalibrationError(f"duplicate record id {record.record_id!r}")
        seen.add(record.record_id)
        if record.mode != judge.mode:
            raise CalibrationError(
                f"record {record.record_id!r} is {record.mode}, judge is {judge.mode}"
            )

    outcomes: list[CalibrationOutcome] = []
    for record in labelled_records:
        try:
            result = await judge._evaluate_uncalibrated(
                record.messages,
                inputs=record.inputs,
                case_id=record.record_id,
            )
            outcomes.append(_compare_result(record, result))
        except Exception as exc:
            outcomes.append(
                CalibrationOutcome(
                    record_id=record.record_id,
                    available=False,
                    error=f"{type(exc).__name__}: {exc}",
                    expected_label=record.expected_label,
                    expected_findings=record.expected_findings,
                )
            )

    available = [outcome for outcome in outcomes if outcome.available]
    agreed = [outcome for outcome in available if outcome.agreed]
    aggregate = len(agreed) / len(available) if available else 0.0
    enough = len(available) >= minimum_records
    per_label = _per_label(judge, labelled_records, outcomes)
    identity = {
        "judgeId": judge.evaluator_id,
        "judgeVersion": judge.evaluator_version,
        "rubricHash": judge.rubric_hash,
        "mode": judge.mode,
        "minimumRecords": minimum_records,
        "agreementFloor": agreement_floor,
        "labelledRecords": [
            record.model_dump(by_alias=True, mode="json")
            for record in labelled_records
        ],
        "outcomes": [
            outcome.model_dump(by_alias=True, mode="json") for outcome in outcomes
        ],
    }
    return CalibrationReport(
        calibration_id=content_hash(identity),
        judge_id=judge.evaluator_id,
        judge_version=judge.evaluator_version,
        rubric_hash=judge.rubric_hash,
        mode=judge.mode,
        minimum_records=minimum_records,
        agreement_floor=agreement_floor,
        records_total=len(labelled_records),
        records_available=len(available),
        aggregate_agreement=round(aggregate, 6),
        enough_records=enough,
        calibrated=enough and aggregate >= agreement_floor,
        per_label=per_label,
        outcomes=tuple(outcomes),
    )


def _compare_result(
    record: CalibrationRecord, result: Any
) -> CalibrationOutcome:
    if record.mode == "choice":
        actual = getattr(result, "label", None)
        available = actual is not None
        return CalibrationOutcome(
            record_id=record.record_id,
            available=available,
            agreed=(actual == record.expected_label) if available else None,
            expected_label=record.expected_label,
            actual_label=actual,
            error=None if available else getattr(result, "explanation", None),
        )

    result_available = bool(getattr(result, "available", False))
    actual = tuple(
        FindingLabel(
            criterion=str(finding.criterion),
            severity=str(finding.severity),
            locality=str(finding.locality),
        )
        for finding in getattr(result, "findings", ())
    )
    expected_keys = {finding.key for finding in record.expected_findings}
    actual_keys = {finding.key for finding in actual}
    return CalibrationOutcome(
        record_id=record.record_id,
        available=result_available,
        agreed=(expected_keys == actual_keys) if result_available else None,
        expected_findings=record.expected_findings,
        actual_findings=actual,
        error=None if result_available else getattr(result, "unavailable", None),
    )


def _per_label(
    judge: CalibratableJudge,
    records: Sequence[CalibrationRecord],
    outcomes: Sequence[CalibrationOutcome],
) -> dict[str, Agreement]:
    by_id = {outcome.record_id: outcome for outcome in outcomes}
    if judge.mode == "choice":
        labels = tuple(dict.fromkeys((*judge.choice_labels,)))
        result: dict[str, Agreement] = {}
        for label in labels:
            labelled = [
                by_id[record.record_id]
                for record in records
                if record.expected_label == label
                and by_id[record.record_id].available
            ]
            count = len(labelled)
            matching = sum(outcome.actual_label == label for outcome in labelled)
            result[label] = Agreement(
                records=count,
                agreed=matching,
                agreement=round(matching / count, 6) if count else 0.0,
            )
        return result

    keys = sorted(
        {
            finding.key
            for record in records
            for finding in record.expected_findings
        }
        or {"<no_findings>"}
    )
    result = {}
    for key in keys:
        relevant: list[tuple[CalibrationRecord, CalibrationOutcome]] = []
        for record in records:
            outcome = by_id[record.record_id]
            if not outcome.available:
                continue
            expected_keys = {finding.key for finding in record.expected_findings}
            if key in expected_keys or (key == "<no_findings>" and not expected_keys):
                relevant.append((record, outcome))
        matching = sum(
            key in {finding.key for finding in outcome.actual_findings}
            if key != "<no_findings>"
            else not outcome.actual_findings
            for _record, outcome in relevant
        )
        count = len(relevant)
        result[key] = Agreement(
            records=count,
            agreed=matching,
            agreement=round(matching / count, 6) if count else 0.0,
        )
    return result


__all__ = [
    "CALIBRATION_SCHEMA_VERSION",
    "MINIMUM_RECORDS",
    "SCORE_AGREEMENT_FLOOR",
    "Agreement",
    "CalibrationError",
    "CalibrationOutcome",
    "CalibrationRecord",
    "CalibrationReport",
    "FindingLabel",
    "calibrate",
]
