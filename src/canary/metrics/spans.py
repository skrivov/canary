"""Span matching and precision/recall/F1 arithmetic."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from canary.score import Score


@dataclass(frozen=True, slots=True)
class TextSpan:
    start: int
    end: int
    label: str | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("span must be non-empty and ordered")


def span_iou(left: TextSpan, right: TextSpan) -> float:
    intersection = max(0, min(left.end, right.end) - max(left.start, right.start))
    union = max(left.end, right.end) - min(left.start, right.start)
    return intersection / union if union else 0.0


def match_spans(
    expected: Iterable[TextSpan],
    predicted: Iterable[TextSpan],
    *,
    minimum_iou: float = 0.5,
) -> tuple[int, int, int]:
    if not 0.0 <= minimum_iou <= 1.0:
        raise ValueError("minimum_iou must be between 0 and 1")
    gold = list(expected)
    guesses = list(predicted)
    candidates = sorted(
        (
            (span_iou(gold_item, guess), gold_index, guess_index)
            for gold_index, gold_item in enumerate(gold)
            for guess_index, guess in enumerate(guesses)
            if gold_item.label is None
            or guess.label is None
            or gold_item.label == guess.label
        ),
        reverse=True,
    )
    matched_gold: set[int] = set()
    matched_guesses: set[int] = set()
    for overlap, gold_index, guess_index in candidates:
        if overlap < minimum_iou:
            break
        if gold_index in matched_gold or guess_index in matched_guesses:
            continue
        matched_gold.add(gold_index)
        matched_guesses.add(guess_index)
    return (
        len(matched_gold),
        len(guesses) - len(matched_guesses),
        len(gold) - len(matched_gold),
    )


def precision_recall_f1(
    true_positive: int, false_positive: int, false_negative: int
) -> dict[str, float]:
    if min(true_positive, false_positive, false_negative) < 0:
        raise ValueError("confusion counts cannot be negative")
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 1.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def span_f1_score(
    expected: Iterable[TextSpan],
    predicted: Iterable[TextSpan],
    *,
    minimum_iou: float = 0.5,
    case_id: str | None = None,
) -> Score:
    true_positive, false_positive, false_negative = match_spans(
        expected, predicted, minimum_iou=minimum_iou
    )
    metrics = precision_recall_f1(true_positive, false_positive, false_negative)
    return Score(
        name="span_f1",
        evaluator_id="canary.metrics.spans",
        evaluator_version="1",
        kind="code",
        score=metrics["f1"],
        label="exact" if metrics["f1"] == 1.0 else "mismatch",
        case_id=case_id,
        evidence={
            **metrics,
            "truePositive": true_positive,
            "falsePositive": false_positive,
            "falseNegative": false_negative,
            "minimumIou": minimum_iou,
        },
    )


__all__ = [
    "TextSpan",
    "match_spans",
    "precision_recall_f1",
    "span_f1_score",
    "span_iou",
]
