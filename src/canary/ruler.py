"""Artifact-recorded grading rulers and fail-closed comparability."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, field_validator

from ._models import FrozenModel
from .hashing import content_hash

RULER_SCHEMA_VERSION = "canary-ruler/v1"


class RulerError(ValueError):
    """An artifact does not carry a readable grading ruler."""


class RulerMismatchError(RulerError):
    """Two artifacts were measured under different standards."""

    def __init__(self, changes: Sequence["RulerChange"]) -> None:
        self.changes = tuple(changes)
        detail = "; ".join(change.describe() for change in self.changes)
        super().__init__(f"rulers do not match: {detail}")


class RulerChange(FrozenModel):
    field: str
    before: Any = None
    after: Any = None

    def describe(self) -> str:
        return f"{self.field}: {self.before!r} -> {self.after!r}"


class Ruler(FrozenModel):
    """The complete standard needed to interpret a set of scores."""

    schema_version: Literal["canary-ruler/v1"] = RULER_SCHEMA_VERSION
    taxonomy_version: str = Field(min_length=1)
    judge_rubric_hashes: dict[str, str] = Field(default_factory=dict)
    calibration_ids: dict[str, str] = Field(default_factory=dict)
    criteria: tuple[str, ...]
    freeze_id: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )

    @field_validator("criteria")
    @classmethod
    def _criteria_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not criterion.strip() for criterion in value):
            raise ValueError("criteria must contain non-empty names")
        if len(set(value)) != len(value):
            raise ValueError("criteria must be unique and ordered")
        return value

    @field_validator("judge_rubric_hashes", "calibration_ids")
    @classmethod
    def _identities_are_content_hashes(
        cls, value: dict[str, str]
    ) -> dict[str, str]:
        if any(
            not key.strip()
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
            for key, digest in value.items()
        ):
            raise ValueError("ruler identity mappings require names and sha256 hashes")
        return value

    @property
    def fingerprint(self) -> str:
        return content_hash(self.model_dump(by_alias=True, mode="json"))

    @classmethod
    def from_artifact(cls, artifact: Mapping[str, Any]) -> "Ruler":
        raw = artifact.get("ruler")
        if not isinstance(raw, Mapping):
            raise RulerError("artifact records no ruler")
        try:
            return cls.model_validate(raw)
        except ValueError as exc:
            raise RulerError(f"artifact ruler is invalid: {exc}") from exc


class RulerComparison(FrozenModel):
    matched: bool
    before_fingerprint: str
    after_fingerprint: str
    changes: tuple[RulerChange, ...] = ()


def compare_rulers(
    before: Ruler | Mapping[str, Any],
    after: Ruler | Mapping[str, Any],
) -> RulerComparison:
    """Compare only ruler values recorded in the supplied artifacts."""

    left = before if isinstance(before, Ruler) else Ruler.from_artifact(before)
    right = after if isinstance(after, Ruler) else Ruler.from_artifact(after)
    changes = tuple(
        _diff(
            left.model_dump(by_alias=True, mode="json"),
            right.model_dump(by_alias=True, mode="json"),
        )
    )
    return RulerComparison(
        matched=not changes,
        before_fingerprint=left.fingerprint,
        after_fingerprint=right.fingerprint,
        changes=changes,
    )


def assert_same_ruler(
    before: Ruler | Mapping[str, Any],
    after: Ruler | Mapping[str, Any],
) -> Ruler:
    """Return the shared ruler or refuse with every recorded difference."""

    left = before if isinstance(before, Ruler) else Ruler.from_artifact(before)
    comparison = compare_rulers(left, after)
    if comparison.changes:
        raise RulerMismatchError(comparison.changes)
    return left


def _diff(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    prefix: str = "",
) -> list[RulerChange]:
    changes: list[RulerChange] = []
    for key in sorted(set(before) | set(after)):
        path = f"{prefix}{key}"
        left = before.get(key)
        right = after.get(key)
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            changes.extend(_diff(left, right, prefix=f"{path}."))
        elif _normalize(left) != _normalize(right):
            changes.append(RulerChange(field=path, before=left, after=right))
    return changes


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    return value


__all__ = [
    "RULER_SCHEMA_VERSION",
    "Ruler",
    "RulerChange",
    "RulerComparison",
    "RulerError",
    "RulerMismatchError",
    "assert_same_ruler",
    "compare_rulers",
]
