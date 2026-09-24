from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from canary.judge import UncalibratedJudgeError
from canary.model_port import Message
from canary.rubrics import (
    available_rubrics,
    judge_from_rubric,
    load_rubric,
)

PROMPT_HASHES = {
    "hallucination": "2188302ccbdaf6caf54795b14bfddbdb1fb2229accc820ec5e396691ecb849db",
    "tool_invocation": "922dce6f9dba177fa2a37a1458509aeb6de5fe7a7b54d136e6fdc26c33b22b05",
    "tool_response_handling": "6df54961fce274b2e44fb772b1e881dcd2c0d18e6f79596f36907c56e367981b",
    "tool_selection": "a0119f07b83c5535a4d0440ee0ae9bf0e58cb420746d6048db87fee541e68601",
    "user_friction": "6057a13e20be2d91e753c09706bc0b4c8a1597bc630bb781147cf0b5baa0444b",
}


class RecordingPort:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def generate_object(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        operation: str,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {"schema": schema, "messages": tuple(messages), "operation": operation}
        )
        return self.response


def test_exact_five_seed_catalog_and_attribution() -> None:
    assert available_rubrics() == (
        "hallucination",
        "tool_invocation",
        "tool_response_handling",
        "tool_selection",
        "user_friction",
    )
    for name, expected_hash in PROMPT_HASHES.items():
        rubric = load_rubric(name)
        digest = hashlib.sha256(rubric.messages[0].content.encode()).hexdigest()
        assert digest == expected_hash
        assert rubric.provenance.source == "arize-phoenix-evals"
        assert rubric.provenance.version == "3.5.1"
        assert rubric.provenance.license == "Elastic-2.0"
        assert rubric.provenance.modified is True
        assert rubric.provenance.upstream_path.endswith(
            f"_{name}_classification_evaluator_config.py"
        )


def test_hallucination_seed_preserves_choices_direction_and_failed_tool_rule() -> None:
    rubric = load_rubric("hallucination")
    assert rubric.direction == "minimize"
    assert rubric.choices == {"hallucinated": 1.0, "grounded": 0.0}
    assert "A failed tool is not a source." in rubric.messages[0].content


@pytest.mark.asyncio
async def test_seed_is_inert_until_calibrated() -> None:
    port = RecordingPort({"label": "grounded", "explanation": "supported"})
    judge = judge_from_rubric(load_rubric("hallucination"), port=port)
    with pytest.raises(UncalibratedJudgeError):
        await judge.evaluate(
            (),
            inputs={"input": "record", "output_with_tool_calls": "answer"},
        )
    assert port.calls == []


@pytest.mark.asyncio
async def test_explicit_authoring_mode_marks_seed_output_uncalibrated() -> None:
    port = RecordingPort({"label": "grounded", "explanation": "supported"})
    judge = judge_from_rubric(
        load_rubric("hallucination"),
        port=port,
        allow_uncalibrated=True,
    )
    score = await judge.evaluate(
        (),
        inputs={"input": "record", "output_with_tool_calls": "answer"},
    )
    assert score.evidence["calibration"]["status"] == "uncalibrated"
    prompt = port.calls[0]["messages"][0].content
    assert "<input>\nrecord\n</input>" in prompt
    assert "<output>\nanswer\n</output>" in prompt


@pytest.mark.asyncio
async def test_tool_seed_substitutions_use_declared_dataset_fields() -> None:
    port = RecordingPort({"label": "correct", "explanation": "valid"})
    judge = judge_from_rubric(
        load_rubric("tool_selection"),
        port=port,
        allow_uncalibrated=True,
    )
    await judge.evaluate(
        (),
        inputs={
            "input": "Find the contract",
            "available_tools_list": [{"name": "search"}],
            "output_with_tool_calls": {"name": "search"},
        },
    )
    prompt = port.calls[0]["messages"][0].content
    assert "Find the contract" in prompt
    assert '{"name":"search"}' in prompt


def test_rubric_loader_rejects_traversal_and_unknown_names() -> None:
    with pytest.raises(ValueError):
        load_rubric("../hallucination")
    with pytest.raises(KeyError):
        load_rubric("missing")


def test_third_party_notice_carries_copyright_modification_and_license() -> None:
    notice = (
        Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md"
    ).read_text(encoding="utf-8")
    assert "Copyright 2024 Arize AI, Inc. All Rights Reserved." in notice
    assert "The copies are modified" in notice
    assert "Elastic License 2.0 (ELv2)" in notice
    assert "You must ensure that anyone who gets a copy" in notice
