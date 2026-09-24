from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from canary.ledger import (
    LedgerError,
    LedgerRecord,
    TruncatedLedgerError,
    append,
    context_fingerprint,
    passing_checkpoints,
    read,
    resume_filter,
    revision_identity,
)
from canary.metrics.safety import (
    contains_forbidden_value,
    contains_write_verb,
    safety_score,
)
from canary.metrics.schema_conformance import schema_conformance
from canary.metrics.sets import id_set_score, set_relation
from canary.metrics.spans import (
    TextSpan,
    match_spans,
    precision_recall_f1,
    span_f1_score,
    span_iou,
)
from canary.metrics.text import exact_match, matches_regex


def record(case_id: str, status: str = "passed", revision: str | None = None):
    return LedgerRecord(
        case_id=case_id,
        revision_identity=revision or revision_identity({"id": case_id}, "v1"),
        context_fingerprint=context_fingerprint({"workspace": "w1"}),
        status=status,
    )


def test_ledger_append_is_one_complete_line_under_concurrency(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: append(path, record(f"case-{index}")), range(32)))
    records = read(path)
    assert len(records) == 32
    assert {item.case_id for item in records} == {f"case-{index}" for index in range(32)}
    assert path.read_bytes().count(b"\n") == 32


def test_ledger_append_requests_binary_mode_where_the_os_defines_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows text-mode descriptors would turn each "\\n" into "\\r\\n"."""

    sentinel = 1 << 30  # stands in for Windows' O_BINARY; unused by POSIX
    real_open = os.open
    requested: list[int] = []

    def spy(path: object, flags: int, mode: int = 0o777) -> int:
        requested.append(flags)
        return real_open(path, flags & ~sentinel, mode)

    monkeypatch.setattr(os, "O_BINARY", sentinel, raising=False)
    monkeypatch.setattr(os, "open", spy)
    path = tmp_path / "run.jsonl"
    append(path, record("case-1"))
    monkeypatch.undo()

    assert requested and requested[0] & sentinel
    raw = path.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw


def test_truncated_final_line_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    path.write_text('{"schemaVersion":"canary-ledger/v1"', encoding="utf-8")
    with pytest.raises(TruncatedLedgerError):
        read(path)


def test_malformed_complete_line_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(LedgerError):
        read(path)


def test_non_finite_json_is_rejected_even_if_python_json_accepts_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.jsonl"
    path.write_text('{"value":NaN}\n', encoding="utf-8")
    with pytest.raises(LedgerError, match="non-finite"):
        read(path)


def test_passing_checkpoints_and_resume_skip_exact_identities(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    one = {"id": "one", "revision": "v1"}
    two = {"id": "two", "revision": "v2"}
    one_identity = revision_identity(one, "policy-1")
    append(path, record("one", revision=one_identity))
    append(path, record("two", status="failed"))
    cases = (one, two)
    pending = resume_filter(
        cases,
        passing_checkpoints(path),
        case_id=lambda item: item["id"],
        identity=lambda item: revision_identity(item, "policy-1"),
    )
    assert pending == (two,)


def test_mutating_any_revision_changes_identity() -> None:
    baseline = revision_identity({"question": "q"}, "prompt-1", {"schema": "1"})
    assert revision_identity({"question": "changed"}, "prompt-1", {"schema": "1"}) != baseline
    assert revision_identity({"question": "q"}, "prompt-2", {"schema": "1"}) != baseline
    assert revision_identity({"question": "q"}, "prompt-1", {"schema": "2"}) != baseline


@pytest.mark.parametrize(
    ("observed", "expected", "relation"),
    [
        (("a",), ("a",), "exact"),
        ((), ("a",), "empty_wrong"),
        (("a",), ("a", "b"), "subset"),
        (("a", "b"), ("a",), "superset"),
        (("a", "b"), ("b", "c"), "overlap"),
        (("a",), ("b",), "disjoint"),
    ],
)
def test_set_metric_relations(
    observed: tuple[str, ...], expected: tuple[str, ...], relation: str
) -> None:
    assert set_relation(observed, expected) == relation
    score = id_set_score(observed, expected)
    assert score.label == relation
    assert score.score == (1.0 if relation == "exact" else 0.0)


def test_span_metrics_match_hand_computed_values_and_failures() -> None:
    left = TextSpan(0, 10, "clause")
    right = TextSpan(5, 15, "clause")
    assert span_iou(left, right) == pytest.approx(1 / 3)
    counts = match_spans((left,), (TextSpan(1, 9, "clause"), TextSpan(20, 25)))
    assert counts == (1, 1, 0)
    metrics = precision_recall_f1(*counts)
    assert metrics == {
        "precision": 0.5,
        "recall": 1.0,
        "f1": pytest.approx(2 / 3),
    }
    assert span_f1_score((left,), (TextSpan(30, 40),)).score == 0.0


def test_span_label_mismatch_falsifies_match() -> None:
    assert match_spans(
        (TextSpan(0, 10, "clause"),),
        (TextSpan(0, 10, "party"),),
    ) == (0, 1, 1)


def test_write_scan_ignores_literals_and_comments_but_catches_commands() -> None:
    assert not contains_write_verb("SELECT 'DELETE' AS [word] -- UPDATE later")
    assert contains_write_verb("SELECT 1; DELETE FROM contracts")
    assert safety_score(query="DROP TABLE contracts").score == 0.0


def test_forbidden_value_walk_falsifies_nested_payload() -> None:
    payload = {"filter": [{"value": "decoy"}]}
    assert contains_forbidden_value(payload, {"decoy"})
    assert not contains_forbidden_value(payload, {"safe"})
    assert safety_score(payload=payload, forbidden_values=("decoy",)).score == 0.0


def test_text_metrics_are_seen_failing() -> None:
    assert exact_match("Answer", "answer").score == 0.0
    assert exact_match("Answer", "answer", case_sensitive=False).score == 1.0
    assert matches_regex("contract-42", r"^contract-\d+$", full_match=True).score == 1.0
    assert matches_regex("contract-X", r"^contract-\d+$", full_match=True).score == 0.0


def test_schema_conformance_is_seen_passing_and_failing() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }
    assert schema_conformance({"id": 7}, schema).score == 1.0
    failure = schema_conformance({"id": "seven", "extra": True}, schema)
    assert failure.score == 0.0
    assert failure.label == "invalid"
    assert len(failure.evidence["errors"]) == 2
