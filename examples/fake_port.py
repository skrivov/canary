"""An offline ``ModelPort`` for tests, CI, and trying Canary without a key.

Applications keep a fake like this in their own test suites: judge wiring,
calibration, and persistence are exercised with no credentials, no network,
and no cost. Only the port changes between tests and production.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from canary.model_port import Message


class RecordOverlapPort:
    """A deterministic stand-in judge for the grounding example.

    It expects the last message to read ``Record: ...`` followed by
    ``Answer: ...`` and labels the answer ``grounded`` only when the answer
    is quoted from the record — a crude rule, but one a real judge must
    agree with on the example's clear-cut cases.
    """

    def __init__(self) -> None:
        self.operations: list[str] = []

    async def generate_object(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        operation: str,
    ) -> Mapping[str, Any]:
        self.operations.append(operation)
        record, _, answer = messages[-1].content.partition("Answer:")
        quoted = answer.strip().rstrip(".").casefold()
        grounded = bool(quoted) and quoted in record.casefold()
        label = "grounded" if grounded else "unsupported"
        payload: dict[str, Any] = {"label": label}
        if "explanation" in schema.get("properties", {}):
            payload["explanation"] = (
                "The answer is quoted from the record."
                if grounded
                else "The answer states something the record does not."
            )
        return payload
