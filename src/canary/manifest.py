"""One fail-closed corpus manifest schema with two review profiles.

A manifest proves that every expected case in a corpus is present and was
reviewed before the corpus is allowed to score anything. The two profiles
share one schema:

* ``checklist`` — each review signs off every dimension the manifest names in
  ``required_checks`` and carries an explicit ``blessed`` decision.
* ``annotation`` — each review approves one annotation and records the content
  hashes of the annotation and of the golden set it belongs to.

Reviews record model-produced audits, so reviewer strings must unmistakably
name a model and placeholders such as ``pending`` are rejected.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union

from pydantic import Field, field_validator, model_validator

from ._models import FrozenModel
from .score import WorldRef

CORPUS_SCHEMA_VERSION = "canary-corpus/v2"

ReviewProfile = Literal["checklist", "annotation"]

PLACEHOLDER_REVIEWERS = frozenset(
    {
        "pending",
        "pending audit",
        "pending human review",
        "pending llm audit",
        "pending review",
        "tbd",
        "unknown",
    }
)
_MODEL_MARKER = re.compile(
    r"\b(model|llm|gpt|claude|gemini|llama|mistral|qwen|judge|evaluator|sonnet|opus|grok|deepseek|command|nova|phi|o[1-9])\b",
    re.IGNORECASE,
)


class ReviewBase(FrozenModel):
    case_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=3, max_length=200)
    reviewer_type: Literal["model"] = "model"
    reviewed_at: date

    @field_validator("reviewer")
    @classmethod
    def _reviewer_names_a_model(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if normalized.casefold() in PLACEHOLDER_REVIEWERS:
            raise ValueError("reviewer cannot be a placeholder")
        if _MODEL_MARKER.search(normalized) is None:
            raise ValueError(
                "reviewer must unmistakably identify a model, LLM, judge, or evaluator"
            )
        return normalized

    @property
    def complete(self) -> bool:
        raise NotImplementedError


class ChecklistReview(ReviewBase):
    """A review that signs off each named dimension, then blesses the case."""

    profile: Literal["checklist"] = "checklist"
    checks: dict[str, bool]
    blessed: bool

    @field_validator("checks")
    @classmethod
    def _checks_are_named(cls, value: dict[str, bool]) -> dict[str, bool]:
        if not value or any(not name.strip() for name in value):
            raise ValueError("checks must name at least one non-empty dimension")
        return value

    @property
    def complete(self) -> bool:
        return self.blessed and all(self.checks.values())


class AnnotationReview(ReviewBase):
    """A review that approves one annotation against a hashed golden set."""

    profile: Literal["annotation"] = "annotation"
    review_status: Literal["approved"]
    annotation_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    golden_set_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @property
    def complete(self) -> bool:
        return self.review_status == "approved"


CaseReview = Annotated[
    Union[ChecklistReview, AnnotationReview],
    Field(discriminator="profile"),
]


class CorpusManifest(FrozenModel):
    schema_version: Literal["canary-corpus/v2"] = CORPUS_SCHEMA_VERSION
    corpus_id: str = Field(min_length=1)
    corpus_revision: str = Field(min_length=1)
    profile: ReviewProfile
    required_checks: tuple[str, ...] = ()
    expected_total: int = Field(ge=1)
    counts: dict[str, int]
    category_counts: dict[str, int]
    world: WorldRef
    llm_audit_required: Literal[True]
    reviews: tuple[CaseReview, ...]

    @field_validator("counts", "category_counts")
    @classmethod
    def _counts_are_nonnegative(cls, value: dict[str, int]) -> dict[str, int]:
        if not value or any(not key.strip() for key in value):
            raise ValueError("count mappings must have non-empty keys")
        if any(count < 0 for count in value.values()):
            raise ValueError("counts cannot be negative")
        return value

    @field_validator("required_checks")
    @classmethod
    def _required_checks_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not name.strip() for name in value):
            raise ValueError("required_checks must contain non-empty names")
        if len(set(value)) != len(value):
            raise ValueError("required_checks must be unique")
        return value

    @model_validator(mode="after")
    def _fail_closed_totals_and_reviews(self) -> "CorpusManifest":
        if sum(self.counts.values()) != self.expected_total:
            raise ValueError("counts do not equal expected_total")
        if sum(self.category_counts.values()) != self.expected_total:
            raise ValueError("category_counts do not equal expected_total")
        if self.profile == "checklist" and not self.required_checks:
            raise ValueError("the checklist profile requires required_checks")
        if self.profile != "checklist" and self.required_checks:
            raise ValueError("required_checks applies only to the checklist profile")
        if len(self.reviews) != self.expected_total:
            raise ValueError("every expected case must have exactly one review")
        case_ids = [review.case_id for review in self.reviews]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case review ids must be unique")
        if any(review.profile != self.profile for review in self.reviews):
            raise ValueError("all reviews must use the manifest profile")
        required = set(self.required_checks)
        for review in self.reviews:
            if isinstance(review, ChecklistReview) and set(review.checks) != required:
                raise ValueError(
                    f"review {review.case_id!r} checks do not match required_checks: "
                    f"missing {sorted(required - set(review.checks))}, "
                    f"unexpected {sorted(set(review.checks) - required)}"
                )
        incomplete = [review.case_id for review in self.reviews if not review.complete]
        if incomplete:
            raise ValueError(f"incomplete reviews: {sorted(incomplete)}")
        return self


__all__ = [
    "CORPUS_SCHEMA_VERSION",
    "PLACEHOLDER_REVIEWERS",
    "AnnotationReview",
    "CaseReview",
    "ChecklistReview",
    "CorpusManifest",
    "ReviewProfile",
]
