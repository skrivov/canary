"""Deterministic evaluation with no model, no API key, and no network.

    python examples/offline_quickstart.py

Stored observations are compared with a golden, projected into ``Score``
records, and checkpointed in an append-only ledger inside a temporary
directory, exactly as an application would do with its own stored runs.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from canary import IdSetGolden, Observation, Score, compare
from canary.ledger import (
    LedgerRecord,
    append,
    context_fingerprint,
    passing_checkpoints,
    revision_identity,
)


def main() -> None:
    golden = IdSetGolden(id_column="contract_id", ids=("C-100", "C-200", "C-300"))
    stored_observations = {
        "case-1": Observation(
            executed=True,
            columns=("contract_id",),
            rows=(
                {"contract_id": "C-100"},
                {"contract_id": "C-200"},
                {"contract_id": "C-300"},
            ),
        ),
        "case-2": Observation(
            executed=True,
            columns=("contract_id",),
            rows=({"contract_id": "C-100"},),
        ),
        "case-3": Observation(
            executed=False,
            failure_stage="runtime",
            failure_code="timeout",
        ),
    }
    # Recorded with the run and passed in; scoring never reads the clock.
    run_date = date(2026, 9, 1)
    context = context_fingerprint({"dataset": "contracts", "schemaRevision": "7"})

    with tempfile.TemporaryDirectory() as workdir:
        ledger = Path(workdir) / "evaluation.jsonl"
        for case_id, observation in stored_observations.items():
            verdict = compare(observation, golden, today=run_date)
            score = Score(
                name="answer_set",
                evaluator_id="example.answer-set",
                evaluator_version="1",
                kind="code",
                score=1.0 if verdict.is_correct else 0.0,
                label=verdict.subtype or verdict.verdict,
                evidence={"verdict": verdict.verdict, "missing": verdict.evidence.get("missing", [])},
                case_id=case_id,
                run_id="example-run",
            )
            append(
                ledger,
                LedgerRecord(
                    case_id=case_id,
                    revision_identity=revision_identity(
                        {"case": case_id}, {"goldenHash": golden.content_hash}
                    ),
                    context_fingerprint=context,
                    status="passed" if verdict.is_correct else "failed",
                    payload=score.model_dump(by_alias=True, mode="json"),
                ),
            )
            print(f"{case_id}: {verdict.verdict} ({verdict.subtype or 'no failure'})")
        print("passing checkpoints:", ", ".join(sorted(passing_checkpoints(ledger))))


if __name__ == "__main__":
    main()
