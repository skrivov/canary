"""Closed-schema choice and findings judges over an injected ModelPort."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, model_validator

from ._models import FrozenModel
from .calibration import CalibrationReport
from .hashing import canonical_json, content_hash
from .model_port import Message, ModelPort
from .score import OptimizationDirection, Score

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


class JudgeError(RuntimeError):
    """A judge cannot produce a trustworthy artifact."""


class UncalibratedJudgeError(JudgeError):
    """Scoring was attempted without a matching passing calibration."""


class Finding(FrozenModel):
    criterion: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    locality: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    complaint: str = Field(min_length=1)


class FindingsResult(FrozenModel):
    evaluator_id: str
    evaluator_version: str
    case_id: str | None = None
    findings: tuple[Finding, ...] = ()
    met: tuple[str, ...] = ()
    available: bool = True
    unavailable: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _availability_is_coherent(self) -> "FindingsResult":
        if self.available and self.unavailable is not None:
            raise ValueError("available findings cannot carry an unavailable reason")
        if not self.available and not self.unavailable:
            raise ValueError("unavailable findings require a reason")
        return self


class _JudgeBase:
    mode: Literal["choice", "findings"]
    choice_labels: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        port: ModelPort,
        evaluator_id: str,
        evaluator_version: str,
        operation: str,
        prompt_messages: Sequence[Message] = (),
        calibration: CalibrationReport | None = None,
        allow_uncalibrated: bool = False,
    ) -> None:
        if not evaluator_id.strip() or not evaluator_version.strip():
            raise ValueError("judge identity fields must be non-empty")
        if not operation.strip():
            raise ValueError("judge operation must be non-empty")
        self.port = port
        self.evaluator_id = evaluator_id
        self.evaluator_version = evaluator_version
        self.operation = operation
        self.prompt_messages = tuple(prompt_messages)
        self.calibration = calibration
        self.allow_uncalibrated = allow_uncalibrated

    def with_calibration(self, report: CalibrationReport) -> "_JudgeBase":
        clone = copy.copy(self)
        clone.calibration = report
        clone.allow_uncalibrated = False
        return clone

    def _calibration_evidence(self, *, calibration_mode: bool) -> dict[str, Any]:
        if calibration_mode:
            return {"status": "uncalibrated", "purpose": "calibration"}
        report = self.calibration
        if report and report.applies_to(
            judge_id=self.evaluator_id,
            judge_version=self.evaluator_version,
            rubric_hash=self.rubric_hash,
        ):
            return {"status": "calibrated", "calibrationId": report.calibration_id}
        if self.allow_uncalibrated:
            return {"status": "uncalibrated", "allowUncalibrated": True}
        if report is None:
            reason = "no calibration artifact is attached"
        elif not report.calibrated:
            reason = "the attached calibration did not pass"
        else:
            reason = "the attached calibration belongs to a different judge identity"
        raise UncalibratedJudgeError(
            f"{self.evaluator_id}@{self.evaluator_version} cannot score: {reason}"
        )

    def _render_messages(
        self,
        messages: Sequence[Message],
        inputs: Mapping[str, Any] | None,
    ) -> tuple[Message, ...]:
        values = dict(inputs or {})

        def render(content: str) -> str:
            missing: set[str] = set()

            def replace(match: re.Match[str]) -> str:
                key = match.group(1)
                if key not in values:
                    missing.add(key)
                    return match.group(0)
                value = values[key]
                return value if isinstance(value, str) else canonical_json(value)

            rendered = _PLACEHOLDER.sub(replace, content)
            if missing:
                raise JudgeError(
                    "missing prompt substitutions: " + ", ".join(sorted(missing))
                )
            return rendered

        return tuple(
            Message(role=message.role, content=render(message.content))
            for message in self.prompt_messages
        ) + tuple(messages)

    async def _generate_with_repair(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        validate: Any,
    ) -> tuple[Any | None, list[str]]:
        current = tuple(messages)
        errors: list[str] = []
        for attempt in range(2):
            payload = await self.port.generate_object(
                schema=schema,
                messages=current,
                operation=self.operation if attempt == 0 else f"{self.operation}.repair",
            )
            try:
                return validate(payload), errors
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))
                if attempt == 0:
                    current = (
                        *current,
                        Message(role="assistant", content=canonical_json(payload)),
                        Message(
                            role="user",
                            content=(
                                "The object did not match the closed rubric: "
                                f"{exc}. Return only a corrected object."
                            ),
                        ),
                    )
        return None, errors


class ClosedChoiceJudge(_JudgeBase):
    """A calibrated, explanation-bearing closed-choice classifier."""

    mode: Literal["choice"] = "choice"

    def __init__(
        self,
        *,
        port: ModelPort,
        evaluator_id: str,
        evaluator_version: str,
        choices: Mapping[str, float | None],
        operation: str,
        name: str | None = None,
        direction: OptimizationDirection = "maximize",
        explanation: bool = True,
        prompt_messages: Sequence[Message] = (),
        calibration: CalibrationReport | None = None,
        allow_uncalibrated: bool = False,
    ) -> None:
        super().__init__(
            port=port,
            evaluator_id=evaluator_id,
            evaluator_version=evaluator_version,
            operation=operation,
            prompt_messages=prompt_messages,
            calibration=calibration,
            allow_uncalibrated=allow_uncalibrated,
        )
        if not choices:
            raise ValueError("a closed-choice judge needs at least one choice")
        if any(not str(label).strip() for label in choices):
            raise ValueError("choice labels must be non-empty")
        self.choices = dict(choices)
        self.choice_labels = tuple(self.choices)
        self.name = name or evaluator_id
        self.direction = direction
        self.explanation = explanation
        self.rubric_hash = content_hash(
            {
                "mode": self.mode,
                "choices": self.choices,
                "direction": direction,
                "explanation": explanation,
                "messages": [
                    message.model_dump(by_alias=True, mode="json")
                    for message in self.prompt_messages
                ],
            }
        )

    @property
    def output_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {
            "label": {"type": "string", "enum": list(self.choice_labels)}
        }
        required = ["label"]
        if self.explanation:
            properties["explanation"] = {"type": ["string", "null"]}
            required.append("explanation")
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        }

    async def evaluate(
        self,
        messages: Sequence[Message],
        *,
        inputs: Mapping[str, Any] | None = None,
        case_id: str | None = None,
        run_id: str | None = None,
        dataset: str | None = None,
    ) -> Score:
        calibration = self._calibration_evidence(calibration_mode=False)
        return await self._run(
            messages,
            inputs=inputs,
            case_id=case_id,
            run_id=run_id,
            dataset=dataset,
            calibration=calibration,
        )

    async def _evaluate_uncalibrated(
        self,
        messages: Sequence[Message],
        *,
        inputs: Mapping[str, Any] | None = None,
        case_id: str | None = None,
    ) -> Score:
        return await self._run(
            messages,
            inputs=inputs,
            case_id=case_id,
            run_id=None,
            dataset=None,
            calibration=self._calibration_evidence(calibration_mode=True),
        )

    async def _run(
        self,
        messages: Sequence[Message],
        *,
        inputs: Mapping[str, Any] | None,
        case_id: str | None,
        run_id: str | None,
        dataset: str | None,
        calibration: Mapping[str, Any],
    ) -> Score:
        rendered = self._render_messages(messages, inputs)

        def validate(payload: Any) -> tuple[str, str | None]:
            if not isinstance(payload, Mapping):
                raise TypeError("judge output is not an object")
            expected_keys = {"label", "explanation"} if self.explanation else {"label"}
            if set(payload) != expected_keys:
                raise ValueError(
                    f"expected keys {sorted(expected_keys)}, got {sorted(payload)}"
                )
            label = payload.get("label")
            if not isinstance(label, str) or label not in self.choices:
                raise ValueError(f"label {label!r} is outside the closed choices")
            explanation = payload.get("explanation") if self.explanation else None
            if explanation is not None and not isinstance(explanation, str):
                raise ValueError("explanation must be a string or null")
            return label, explanation

        parsed, errors = await self._generate_with_repair(
            schema=self.output_schema,
            messages=rendered,
            validate=validate,
        )
        base_evidence = {
            "rubricHash": self.rubric_hash,
            "calibration": dict(calibration),
            "modelAttempts": len(errors) + (1 if parsed is not None else 0),
        }
        if parsed is None:
            return Score(
                name=self.name,
                evaluator_id=self.evaluator_id,
                evaluator_version=self.evaluator_version,
                kind="llm",
                direction=self.direction,
                score=None,
                label=None,
                explanation="closed-choice output refused after repair",
                evidence={**base_evidence, "judgeStatus": "refused", "errors": errors},
                case_id=case_id,
                run_id=run_id,
                dataset=dataset,
            )
        label, explanation = parsed
        return Score(
            name=self.name,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            kind="llm",
            direction=self.direction,
            score=self.choices[label],
            label=label,
            explanation=explanation,
            evidence={**base_evidence, "judgeStatus": "scored"},
            case_id=case_id,
            run_id=run_id,
            dataset=dataset,
        )


class FindingsJudge(_JudgeBase):
    """A calibrated judge that preserves findings instead of reducing scores."""

    mode: Literal["findings"] = "findings"

    def __init__(
        self,
        *,
        port: ModelPort,
        evaluator_id: str,
        evaluator_version: str,
        criteria: Sequence[str],
        localities: Sequence[str],
        operation: str,
        severities: Sequence[str] = ("fatal", "weak", "nit"),
        prompt_messages: Sequence[Message] = (),
        calibration: CalibrationReport | None = None,
        allow_uncalibrated: bool = False,
    ) -> None:
        super().__init__(
            port=port,
            evaluator_id=evaluator_id,
            evaluator_version=evaluator_version,
            operation=operation,
            prompt_messages=prompt_messages,
            calibration=calibration,
            allow_uncalibrated=allow_uncalibrated,
        )
        self.criteria = _unique_nonempty(criteria, "criteria")
        self.localities = _unique_nonempty(localities, "localities")
        self.severities = _unique_nonempty(severities, "severities")
        self.rubric_hash = content_hash(
            {
                "mode": self.mode,
                "criteria": self.criteria,
                "localities": self.localities,
                "severities": self.severities,
                "messages": [
                    message.model_dump(by_alias=True, mode="json")
                    for message in self.prompt_messages
                ],
            }
        )

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "criterion": {
                                "type": "string",
                                "enum": list(self.criteria),
                            },
                            "severity": {
                                "type": "string",
                                "enum": list(self.severities),
                            },
                            "locality": {
                                "type": "string",
                                "enum": list(self.localities),
                            },
                            "evidence": {"type": "string", "minLength": 1},
                            "complaint": {"type": "string", "minLength": 1},
                        },
                        "required": [
                            "criterion",
                            "severity",
                            "locality",
                            "evidence",
                            "complaint",
                        ],
                    },
                },
                "met": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(self.criteria)},
                },
            },
            "required": ["findings", "met"],
        }

    async def evaluate(
        self,
        messages: Sequence[Message],
        *,
        inputs: Mapping[str, Any] | None = None,
        case_id: str | None = None,
    ) -> FindingsResult:
        calibration = self._calibration_evidence(calibration_mode=False)
        return await self._run(
            messages, inputs=inputs, case_id=case_id, calibration=calibration
        )

    async def _evaluate_uncalibrated(
        self,
        messages: Sequence[Message],
        *,
        inputs: Mapping[str, Any] | None = None,
        case_id: str | None = None,
    ) -> FindingsResult:
        return await self._run(
            messages,
            inputs=inputs,
            case_id=case_id,
            calibration=self._calibration_evidence(calibration_mode=True),
        )

    async def _run(
        self,
        messages: Sequence[Message],
        *,
        inputs: Mapping[str, Any] | None,
        case_id: str | None,
        calibration: Mapping[str, Any],
    ) -> FindingsResult:
        rendered = self._render_messages(messages, inputs)

        def validate(payload: Any) -> tuple[tuple[Finding, ...], tuple[str, ...]]:
            if not isinstance(payload, Mapping):
                raise TypeError("judge output is not an object")
            if set(payload) != {"findings", "met"}:
                raise ValueError("findings output requires exactly findings and met")
            raw_findings = payload.get("findings")
            raw_met = payload.get("met")
            if not isinstance(raw_findings, list) or not isinstance(raw_met, list):
                raise TypeError("findings and met must be arrays")
            findings: list[Finding] = []
            for raw in raw_findings:
                if not isinstance(raw, Mapping):
                    raise TypeError("each finding must be an object")
                if set(raw) != {
                    "criterion",
                    "severity",
                    "locality",
                    "evidence",
                    "complaint",
                }:
                    raise ValueError("a finding has missing or additional properties")
                finding = Finding.model_validate(raw)
                if finding.criterion not in self.criteria:
                    raise ValueError(f"unknown criterion {finding.criterion!r}")
                if finding.severity not in self.severities:
                    raise ValueError(f"unknown severity {finding.severity!r}")
                if finding.locality not in self.localities:
                    raise ValueError(f"unknown locality {finding.locality!r}")
                findings.append(finding)
            if any(not isinstance(name, str) or name not in self.criteria for name in raw_met):
                raise ValueError("met contains an unknown criterion")
            faulted = {finding.criterion for finding in findings}
            met = tuple(
                name for name in dict.fromkeys(raw_met) if name not in faulted
            )
            return tuple(findings), met

        parsed, errors = await self._generate_with_repair(
            schema=self.output_schema,
            messages=rendered,
            validate=validate,
        )
        evidence = {
            "rubricHash": self.rubric_hash,
            "calibration": dict(calibration),
            "modelAttempts": len(errors) + (1 if parsed is not None else 0),
        }
        if parsed is None:
            return FindingsResult(
                evaluator_id=self.evaluator_id,
                evaluator_version=self.evaluator_version,
                case_id=case_id,
                available=False,
                unavailable="closed findings output refused after repair",
                evidence={**evidence, "errors": errors},
            )
        findings, met = parsed
        return FindingsResult(
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            case_id=case_id,
            findings=findings,
            met=met,
            evidence=evidence,
        )


def _unique_nonempty(values: Sequence[str], name: str) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in values)
    if not normalized or any(not value for value in normalized):
        raise ValueError(f"{name} must contain non-empty values")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must be unique")
    return normalized


__all__ = [
    "ClosedChoiceJudge",
    "Finding",
    "FindingsJudge",
    "FindingsResult",
    "JudgeError",
    "UncalibratedJudgeError",
]
