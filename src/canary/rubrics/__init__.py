"""Attributed, inert rubric seeds loaded from package JSON."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any, Literal

from pydantic import Field, model_validator

from canary._models import FrozenModel
from canary.calibration import CalibrationReport
from canary.judge import ClosedChoiceJudge
from canary.model_port import Message, ModelPort
from canary.score import OptimizationDirection

RUBRIC_SCHEMA_VERSION = "canary-rubric/v1"
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class RubricProvenance(FrozenModel):
    source: Literal["arize-phoenix-evals"]
    version: Literal["3.5.1"]
    commit: Literal["77de515fa1bf62333356fd2755b9e0cd4f6f7100"]
    license: Literal["Elastic-2.0"]
    upstream_path: str = Field(min_length=1)
    copyright: Literal["Copyright 2024 Arize AI, Inc. All Rights Reserved."]
    modified: Literal[True]


class Rubric(FrozenModel):
    schema_version: Literal["canary-rubric/v1"] = RUBRIC_SCHEMA_VERSION
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    direction: OptimizationDirection
    messages: tuple[Message, ...]
    choices: dict[str, float | None]
    substitutions: dict[str, str] | None = None
    labels: tuple[str, ...] = ()
    provenance: RubricProvenance

    @model_validator(mode="after")
    def _is_a_usable_inert_seed(self) -> "Rubric":
        if not self.messages:
            raise ValueError("rubric must carry at least one prompt message")
        if not self.choices:
            raise ValueError("rubric choices cannot be empty")
        return self


def available_rubrics() -> tuple[str, ...]:
    root = resources.files(__package__)
    return tuple(
        sorted(
            path.name.removesuffix(".json")
            for path in root.iterdir()
            if path.name.endswith(".json")
        )
    )


def load_rubric(name: str) -> Rubric:
    """Load an inert seed; this function never constructs or calls a judge."""

    if _SAFE_NAME.fullmatch(name) is None:
        raise ValueError(f"invalid rubric name {name!r}")
    if name not in available_rubrics():
        raise KeyError(f"unknown rubric {name!r}")
    payload = json.loads(
        resources.files(__package__).joinpath(f"{name}.json").read_text("utf-8")
    )
    return Rubric.model_validate(payload)


def judge_from_rubric(
    rubric: Rubric,
    *,
    port: ModelPort,
    evaluator_id: str | None = None,
    evaluator_version: str = "seed-1",
    operation: str | None = None,
    calibration: CalibrationReport | None = None,
    allow_uncalibrated: bool = False,
) -> ClosedChoiceJudge:
    """Construct a judge only under the normal calibration activation rule."""

    prompt_messages = rubric.messages
    if rubric.substitutions:
        prompt_messages = tuple(
            Message(
                role=message.role,
                content=_apply_substitutions(message.content, rubric.substitutions),
            )
            for message in rubric.messages
        )
    return ClosedChoiceJudge(
        port=port,
        evaluator_id=evaluator_id or f"phoenix.{rubric.name}",
        evaluator_version=evaluator_version,
        name=rubric.name,
        choices=rubric.choices,
        direction=rubric.direction,
        operation=operation or f"eval.rubric.{rubric.name}",
        prompt_messages=prompt_messages,
        calibration=calibration,
        allow_uncalibrated=allow_uncalibrated,
    )


def _apply_substitutions(content: str, substitutions: dict[str, str]) -> str:
    result = content
    for template_name, input_name in substitutions.items():
        pattern = re.compile(
            r"\{\{\s*" + re.escape(template_name) + r"\s*\}\}"
        )
        result = pattern.sub("{{" + input_name + "}}", result)
    return result


__all__ = [
    "RUBRIC_SCHEMA_VERSION",
    "Rubric",
    "RubricProvenance",
    "available_rubrics",
    "judge_from_rubric",
    "load_rubric",
]
