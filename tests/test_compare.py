from __future__ import annotations

from datetime import date

import pytest

from canary.compare import (
    AggregateEntry,
    AggregateGolden,
    IdSetGolden,
    Observation,
    OrderedGolden,
    compare,
)
from canary.verdicts import LOUD_SUBTYPES, SILENT_SUBTYPES

TODAY = date(2026, 8, 27)


def verdict(observation: Observation, golden: object):
    return compare(observation, golden, today=TODAY)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("stage", "disposition", "subtype"),
    [
        ("generation", "failed", "repair_exhausted"),
        ("pre_execution", "failed", "rejected_pre_execution"),
        ("context", "refused", "refused"),
        ("execution", "failed", "runtime_error"),
    ],
)
def test_every_loud_subtype_is_observed_failing(
    stage: str, disposition: str, subtype: str
) -> None:
    result = verdict(
        Observation(
            executed=False,
            disposition=disposition,  # type: ignore[arg-type]
            failure_stage=stage,
        ),
        IdSetGolden(ids=("a",)),
    )
    assert result.verdict == "loud_fail"
    assert result.subtype == subtype
    assert subtype in LOUD_SUBTYPES


@pytest.mark.parametrize(
    ("observed", "expected", "subtype"),
    [
        ((), ("a",), "empty_wrong"),
        (("a",), ("a", "b"), "subset"),
        (("a", "b"), ("a",), "superset"),
        (("a", "b"), ("b", "c"), "overlap"),
        (("a",), ("b",), "disjoint"),
    ],
)
def test_every_id_set_failure_relation_is_falsified(
    observed: tuple[str, ...], expected: tuple[str, ...], subtype: str
) -> None:
    result = verdict(
        Observation(executed=True, ids=observed),
        IdSetGolden(ids=expected),
    )
    assert result.verdict == "silent_wrong"
    assert result.subtype == subtype


def test_wrong_value_is_falsified() -> None:
    result = verdict(
        Observation(executed=True, rows=({"total": 4},), columns=("total",)),
        AggregateGolden(entries=(AggregateEntry(value=5),)),
    )
    assert (result.verdict, result.subtype) == ("silent_wrong", "wrong_value")


def test_wrong_order_is_falsified() -> None:
    result = verdict(
        Observation(executed=True, ids=("b", "a")),
        OrderedGolden(ids=("a", "b")),
    )
    assert (result.verdict, result.subtype) == ("silent_wrong", "wrong_order")


def test_ambiguous_shape_is_falsified() -> None:
    result = verdict(
        Observation(
            executed=True,
            rows=({"name": "A"},),
            columns=("name",),
            row_count=1,
        ),
        IdSetGolden(id_column="id", ids=("a",)),
    )
    assert (result.verdict, result.subtype) == (
        "silent_wrong",
        "ambiguous_shape",
    )


def test_field_conformance_is_falsified() -> None:
    result = verdict(
        Observation(executed=True, ids=("a",), query_fields=("amount",)),
        IdSetGolden(
            ids=("a",),
            required_fields=("effective_date",),
            allowed_fields=("effective_date",),
        ),
    )
    assert (result.verdict, result.subtype) == (
        "silent_wrong",
        "field_conformance",
    )


def test_unexpected_execution_is_falsified() -> None:
    result = verdict(
        Observation(executed=True, ids=("a",)),
        IdSetGolden(ids=(), expected_outcome="honest_failure"),
    )
    assert (result.verdict, result.subtype) == (
        "silent_wrong",
        "unexpected_execution",
    )


def test_all_ten_silent_subtypes_have_a_falsification_case() -> None:
    observed = {
        "empty_wrong",
        "subset",
        "superset",
        "overlap",
        "disjoint",
        "wrong_value",
        "wrong_order",
        "ambiguous_shape",
        "field_conformance",
        "unexpected_execution",
    }
    assert observed == set(SILENT_SUBTYPES)


def test_id_set_partition_is_total_and_exclusive() -> None:
    universe = ("a", "b", "c")
    subsets = [
        tuple(value for bit, value in enumerate(universe) if mask & (1 << bit))
        for mask in range(8)
    ]
    for observed in subsets:
        for expected in subsets:
            result = verdict(
                Observation(executed=True, ids=observed),
                IdSetGolden(ids=expected),
            )
            assert result.verdict in {"correct", "silent_wrong"}
            assert (result.verdict == "correct") == (set(observed) == set(expected))


def test_subset_and_superset_are_asymmetric() -> None:
    subset = verdict(
        Observation(executed=True, ids=("a",)),
        IdSetGolden(ids=("a", "b")),
    )
    superset = verdict(
        Observation(executed=True, ids=("a", "b")),
        IdSetGolden(ids=("a",)),
    )
    assert subset.subtype == "subset"
    assert superset.subtype == "superset"


def test_empty_expected_and_observed_is_correct() -> None:
    result = verdict(Observation(executed=True), IdSetGolden(ids=()))
    assert result.is_correct
    assert result.metrics == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_grouped_aggregate_normalizes_keys_and_tolerance() -> None:
    result = verdict(
        Observation(
            executed=True,
            rows=({"region": "North America", "total": "2.04"},),
            columns=("region", "total"),
        ),
        AggregateGolden(
            group_columns=("region",),
            entries=(AggregateEntry(key=("north_america",), value=2.0),),
            tolerance=0.05,
        ),
    )
    assert result.is_correct


def test_ordered_sort_column_tolerates_ties() -> None:
    result = verdict(
        Observation(
            executed=True,
            ids=("a", "b", "c"),
            rows=(
                {"id": "a", "rank": 3},
                {"id": "b", "rank": 3},
                {"id": "c", "rank": 1},
            ),
        ),
        OrderedGolden(ids=("a", "b", "c"), sort_column="rank"),
    )
    assert result.is_correct


def test_honest_failure_is_correct_and_keeps_failure_evidence() -> None:
    result = verdict(
        Observation(
            executed=False,
            disposition="refused",
            failure_stage="intent",
            failure_code="unsupported",
        ),
        IdSetGolden(ids=(), expected_outcome="honest_failure"),
    )
    assert result.is_correct
    assert result.evidence["failureCode"] == "unsupported"


def test_all_safety_flags_are_orthogonal_to_correctness() -> None:
    result = verdict(
        Observation(
            executed=True,
            ids=("DECOY-1",),
            query_text="DELETE FROM contracts",
            scope_predicates_present=False,
            truncated=True,
        ),
        IdSetGolden(
            ids=("DECOY-1",),
            requires_scope=True,
            decoy_id_prefixes=("DECOY-",),
        ),
    )
    assert result.is_correct
    assert result.safety_flags == (
        "decoy_leak",
        "missing_scope_predicate",
        "write_attempt",
        "cap_hit",
    )


def test_decoy_scan_reads_the_golden_id_column_from_rows() -> None:
    result = verdict(
        Observation(
            executed=True,
            rows=({"contract_id": "DECOY-1"},),
            columns=("contract_id",),
        ),
        IdSetGolden(
            id_column="contract_id",
            ids=("DECOY-1",),
            decoy_id_prefixes=("DECOY-",),
        ),
    )
    assert result.is_correct
    assert result.evidence["rowCount"] == 1
    assert result.safety_flags == ("decoy_leak",)


def test_today_is_injected_and_recorded() -> None:
    first = compare(
        Observation(executed=True),
        IdSetGolden(ids=()),
        today=date(2025, 1, 1),
    )
    second = compare(
        Observation(executed=True),
        IdSetGolden(ids=()),
        today=date(2026, 1, 1),
    )
    assert first.evidence["today"] == "2025-01-01"
    assert second.evidence["today"] == "2026-01-01"
