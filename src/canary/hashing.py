"""Canonical content identities used throughout canary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import PurePath
from typing import Any

from pydantic import BaseModel


def canonical_value(value: Any) -> Any:
    """Project supported values into a stable JSON-compatible shape."""

    if isinstance(value, BaseModel):
        return canonical_value(value.model_dump(by_alias=True, mode="json"))
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, Mapping):
        return {
            str(key): canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        normalized = [canonical_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [canonical_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def canonical_json(value: Any) -> str:
    """Serialize a value deterministically without insignificant whitespace."""

    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    """Return a namespaced SHA-256 identity for structured content."""

    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


__all__ = ["canonical_json", "canonical_value", "content_hash"]
