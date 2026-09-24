from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from canary.freeze import build_freeze, preregistration_files, source_hash
from canary.manifest import (
    AnnotationReview,
    ChecklistReview,
    CorpusManifest,
)
from canary.score import WorldRef
from canary.stability import (
    bar,
    n_sensitivity,
    reporting_probability,
    required_successes,
    score_bar,
    threshold_strictness,
)

REQUIRED_CHECKS = ("meaning", "query", "evidence", "ambiguity")


def world() -> WorldRef:
    return WorldRef(
        name="workspace",
        revision="fixture-v1",
        content_hash="sha256:" + "a" * 64,
    )


def checklist_review(**overrides: object) -> ChecklistReview:
    values = {
        "case_id": "case-1",
        "reviewer": "Claude Opus 5 model evaluator",
        "reviewed_at": date(2026, 8, 27),
        "checks": {name: True for name in REQUIRED_CHECKS},
        "blessed": True,
    }
    values.update(overrides)
    return ChecklistReview(**values)


def annotation_review(**overrides: object) -> AnnotationReview:
    values = {
        "case_id": "case-1",
        "reviewer": "GPT-5.6 LLM judge",
        "reviewed_at": date(2026, 8, 27),
        "review_status": "approved",
        "annotation_hash": "sha256:" + "b" * 64,
        "golden_set_hash": "sha256:" + "c" * 64,
    }
    values.update(overrides)
    return AnnotationReview(**values)


def checklist_manifest(**overrides: object) -> CorpusManifest:
    values: dict[str, object] = {
        "corpus_id": "filters",
        "corpus_revision": "v1",
        "profile": "checklist",
        "required_checks": REQUIRED_CHECKS,
        "expected_total": 1,
        "counts": {"ready": 1},
        "category_counts": {"scope": 1},
        "world": world(),
        "llm_audit_required": True,
        "reviews": (checklist_review(),),
    }
    values.update(overrides)
    return CorpusManifest(**values)


def annotation_manifest(**overrides: object) -> CorpusManifest:
    values: dict[str, object] = {
        "corpus_id": "benchmark",
        "corpus_revision": "v2",
        "profile": "annotation",
        "expected_total": 1,
        "counts": {"approved": 1},
        "category_counts": {"aggregation": 1},
        "world": world(),
        "llm_audit_required": True,
        "reviews": (annotation_review(),),
    }
    values.update(overrides)
    return CorpusManifest(**values)


def test_checklist_manifest_is_complete_and_camel_cased() -> None:
    manifest = checklist_manifest()
    payload = manifest.model_dump(by_alias=True, mode="json")
    assert payload["schemaVersion"] == "canary-corpus/v2"
    assert payload["llmAuditRequired"] is True
    assert payload["requiredChecks"] == list(REQUIRED_CHECKS)
    assert payload["reviews"][0]["checks"] == {name: True for name in REQUIRED_CHECKS}
    assert CorpusManifest.model_validate(payload) == manifest


def test_annotation_profile_uses_the_same_manifest_schema() -> None:
    manifest = annotation_manifest()
    assert manifest.required_checks == ()
    assert manifest.reviews[0].complete


@pytest.mark.parametrize(
    "mutation",
    [
        {"expected_total": 2},
        {"counts": {"ready": 0}},
        {"category_counts": {"scope": 2}},
        {"reviews": ()},
        {"profile": "annotation"},
        {"required_checks": ()},
        {"required_checks": REQUIRED_CHECKS[:-1]},
        {"required_checks": (*REQUIRED_CHECKS, "citations")},
        {"required_checks": ("meaning", "meaning")},
        {"required_checks": ("meaning", " ")},
    ],
)
def test_manifest_fails_closed_on_count_profile_or_checklist_drift(
    mutation: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        checklist_manifest(**mutation)


def test_checklist_mismatch_names_missing_and_unexpected_checks() -> None:
    review = checklist_review(checks={"meaning": True, "citations": True})
    with pytest.raises(ValidationError, match=r"missing \['ambiguity', 'evidence', 'query'\]"):
        checklist_manifest(reviews=(review,))
    with pytest.raises(ValidationError, match=r"unexpected \['citations'\]"):
        checklist_manifest(reviews=(review,))


def test_annotation_manifest_rejects_required_checks() -> None:
    with pytest.raises(ValidationError, match="only to the checklist profile"):
        annotation_manifest(required_checks=("meaning",))


@pytest.mark.parametrize("unreviewed", REQUIRED_CHECKS)
def test_every_unreviewed_check_is_seen_failing(unreviewed: str) -> None:
    """Mutate each dimension alone: one repeated value never tests the filter."""

    checks = {name: name != unreviewed for name in REQUIRED_CHECKS}
    with pytest.raises(ValidationError, match="incomplete"):
        checklist_manifest(reviews=(checklist_review(checks=checks),))


def test_incomplete_or_placeholder_review_is_rejected() -> None:
    with pytest.raises(ValidationError):
        checklist_review(reviewer="pending")
    with pytest.raises(ValidationError):
        checklist_review(checks={})
    with pytest.raises(ValidationError, match="incomplete"):
        checklist_manifest(reviews=(checklist_review(blessed=False),))


def test_model_named_reviewer_accepts_compact_model_identifiers() -> None:
    assert checklist_review(reviewer="o3 model").reviewer == "o3 model"


def test_human_review_alias_can_never_enter_manifest() -> None:
    payload = {
        "corpusId": "c",
        "corpusRevision": "v1",
        "profile": "annotation",
        "expectedTotal": 1,
        "counts": {"approved": 1},
        "categoryCounts": {"a": 1},
        "world": world().model_dump(by_alias=True, mode="json"),
        "llmAuditRequired": True,
        "humanReviewRequired": True,
        "reviews": [
            annotation_review().model_dump(by_alias=True, mode="json")
        ],
    }
    with pytest.raises(ValidationError):
        CorpusManifest.model_validate(payload)


def test_llm_audit_required_is_literal_true() -> None:
    with pytest.raises(ValidationError):
        annotation_manifest(llm_audit_required=False)


def test_previous_manifest_schema_version_is_refused() -> None:
    payload = annotation_manifest().model_dump(by_alias=True, mode="json")
    assert CorpusManifest.model_validate(payload)
    payload["schemaVersion"] = "canary-corpus/v1"
    with pytest.raises(ValidationError):
        CorpusManifest.model_validate(payload)


def test_freeze_is_deterministic_over_explicit_inputs() -> None:
    kwargs = {
        "config": {"arms": ["a", "b"]},
        "corpus_hash": "sha256:" + "d" * 64,
        "sources": {"compare.py": "source", "metrics.py": b"metric"},
        "world": world(),
        "hypotheses": ({"id": "H1", "statement": "The gate passes."},),
        "created_at": datetime(2026, 8, 27, 12, tzinfo=timezone.utc),
    }
    first = build_freeze(**kwargs)
    second = build_freeze(**kwargs)
    assert first == second
    assert first.manifest_id == second.manifest_id
    files = preregistration_files(first)
    assert set(files) == {"preregistration.json", "preregistration.md"}
    assert first.manifest_id in files["preregistration.md"]


def test_source_mutation_falsifies_freeze_identity() -> None:
    assert source_hash("a") != source_hash("b")
    common = {
        "config": {"tier": "mini"},
        "corpus_hash": "sha256:" + "d" * 64,
        "world": world(),
        "hypotheses": (),
        "created_at": datetime(2026, 8, 27, tzinfo=timezone.utc),
    }
    before = build_freeze(sources={"compare.py": "a"}, **common)
    after = build_freeze(sources={"compare.py": "b"}, **common)
    assert before.manifest_id != after.manifest_id
    assert before.source_hashes != after.source_hashes


def test_freeze_never_reads_wall_clock_implicitly() -> None:
    with pytest.raises(ValidationError):
        build_freeze(
            config={},
            corpus_hash="sha256:" + "d" * 64,
            sources={"compare.py": "a"},
            world=world(),
            hypotheses=(),
            created_at=datetime(2026, 8, 27),
        )


@pytest.mark.parametrize(
    ("n", "required"),
    [(1, 1), (2, 2), (3, 2), (4, 3), (5, 4), (6, 4), (7, 5)],
)
def test_ceil_two_thirds_bar(n: int, required: int) -> None:
    assert required_successes(n) == required
    assert threshold_strictness(n) == pytest.approx(required / n)


def test_stability_bar_is_seen_failing() -> None:
    assert bar((True, True, False)).passed
    failed = bar((True, False, False))
    assert not failed.passed
    assert failed.required == 2
    assert score_bar((1.0, None, 0.9), threshold=0.95).successes == 1
    assert not score_bar((1.0, None, 0.9), threshold=0.95).passed


def test_minimize_score_bar_and_reporting_probability() -> None:
    assert score_bar((0.1, 0.2, 0.9), threshold=0.3, direction="minimize").passed
    assert reporting_probability(0.0, 3) == 0.0
    assert reporting_probability(1.0, 3) == 1.0
    assert reporting_probability(0.5, 3) == pytest.approx(0.5)


def test_n_sensitivity_names_sample_size_effect() -> None:
    points = n_sensitivity(0.7, (3, 4, 5))
    assert [point.required for point in points] == [2, 3, 4]
    assert len({point.reporting_probability for point in points}) > 1
