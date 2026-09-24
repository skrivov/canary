"""Calibrate, then run, a closed-choice judge on a provider chosen by environment.

    python examples/judge_quickstart.py                                  # offline fake port
    JUDGE_PROVIDER=anthropic python examples/judge_quickstart.py          # ANTHROPIC_API_KEY
    JUDGE_PROVIDER=openai JUDGE_MODEL=<model> python examples/judge_quickstart.py
                                                                          # OPENAI_API_KEY
    uv run --env-file .env python examples/judge_quickstart.py            # settings from .env

``JUDGE_PROVIDER`` and ``JUDGE_MODEL`` are settings of this example
application; Canary itself reads no environment variables. Each provider SDK
reads its own API key from the environment, and this script never prints or
forwards it. The model identity is folded into ``evaluator_version`` so that
switching models invalidates the old calibration instead of silently reusing
it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from canary.calibration import CalibrationRecord, calibrate
from canary.judge import ClosedChoiceJudge
from canary.model_port import Message

# Hand-labelled calibration cases: (record, answer, expected label, why).
LABELLED = (
    (
        "The contract renews automatically on 2026-03-01.",
        "The contract renews automatically on 2026-03-01.",
        "grounded",
        "The answer restates the record.",
    ),
    (
        "Invoices are due within 30 days of issue.",
        "Invoices are due within 30 days of issue.",
        "grounded",
        "The answer restates the record.",
    ),
    (
        "Support is available from 9:00 to 17:00 UTC on weekdays.",
        "Support is available from 9:00 to 17:00 UTC on weekdays.",
        "grounded",
        "The answer restates the record.",
    ),
    (
        "The warranty covers parts for one year.",
        "The warranty covers parts and labour for two years.",
        "unsupported",
        "Labour and the two-year term appear nowhere in the record.",
    ),
    (
        "Refunds are issued to the original payment method.",
        "Refunds can be collected in cash at any branch.",
        "unsupported",
        "The record names only the original payment method.",
    ),
    (
        "The account was opened in 2019.",
        "The account was closed in 2021.",
        "unsupported",
        "The record says nothing about closing the account.",
    ),
)

PROMPT = (
    "You grade whether an answer is supported by the record it was given. "
    "Reply grounded when every claim in the answer is stated in the record, "
    "and unsupported otherwise. Explain the decision in one sentence."
)


def case_message(record: str, answer: str) -> Message:
    return Message(role="user", content=f"Record: {record}\nAnswer: {answer}")


def build_port() -> tuple[Any, str]:
    """Return the application's port and the model identity it runs."""

    provider = os.environ.get("JUDGE_PROVIDER", "fake").strip().lower() or "fake"
    model = os.environ.get("JUDGE_MODEL", "").strip()
    try:
        if provider == "fake":
            from fake_port import RecordOverlapPort

            return RecordOverlapPort(), "record-overlap-rule"
        if provider == "anthropic":
            from anthropic_port import DEFAULT_MODEL, AnthropicModelPort

            model = model or DEFAULT_MODEL
            return AnthropicModelPort(model=model), model
        if provider == "openai":
            if not model:
                sys.exit("set JUDGE_MODEL to an OpenAI model that supports structured outputs")
            from openai_port import OpenAIModelPort

            return OpenAIModelPort(model=model), model
    except ImportError as exc:
        sys.exit(f"install the {provider} SDK in this environment first ({exc.name} is missing)")
    except Exception as exc:  # e.g. the SDK found no credentials; its text names the variable
        sys.exit(f"cannot create the {provider} client: {exc}")
    sys.exit(f"unknown JUDGE_PROVIDER {provider!r}; use fake, anthropic, or openai")


async def main() -> None:
    port, model = build_port()
    judge = ClosedChoiceJudge(
        port=port,
        evaluator_id="example.answer-grounding",
        evaluator_version=f"1:{model}",
        name="answer_grounding",
        choices={"grounded": 1.0, "unsupported": 0.0},
        operation="eval.answer-grounding",
        prompt_messages=(Message(role="system", content=PROMPT),),
    )
    records = tuple(
        CalibrationRecord(
            record_id=f"grounding-{index}",
            mode="choice",
            messages=(case_message(record, answer),),
            expected_label=label,
            why=why,
        )
        for index, (record, answer, label, why) in enumerate(LABELLED, start=1)
    )

    report = await calibrate(judge, records)
    print(
        f"calibration: {'passed' if report.calibrated else 'FAILED'} with "
        f"{report.aggregate_agreement:.0%} agreement on "
        f"{report.records_available}/{report.records_total} records "
        f"({report.calibration_id})"
    )
    for outcome in report.outcomes:
        if outcome.error or outcome.agreed is False:
            print(f"  {outcome.record_id}: expected {outcome.expected_label}, "
                  f"got {outcome.actual_label or outcome.error}")
    if not report.calibrated:
        sys.exit("the judge did not pass calibration; it may not score")

    score = await judge.with_calibration(report).evaluate(
        (
            case_message(
                "Late payments incur a 2% monthly fee.",
                "Late payments incur a 2% monthly fee.",
            ),
        ),
        case_id="case-1",
        run_id="example-run",
        dataset="answer-grounding",
    )
    print(json.dumps(score.model_dump(by_alias=True, mode="json"), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
