"""JSON Schema conformance metric, available through the schema extra."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from canary.score import Score


def schema_conformance(
    payload: Any,
    schema: Mapping[str, Any],
    *,
    case_id: str | None = None,
) -> Score:
    """Validate a payload and return a diagnostic score.

    jsonschema is imported lazily so the base runtime remains pydantic-only.
    """

    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        raise ImportError(
            "schema_conformance requires canary[schema]"
        ) from exc

    validator = Draft202012Validator(dict(schema))
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    evidence = {
        "errors": [
            {
                "path": [str(part) for part in error.absolute_path],
                "schemaPath": [str(part) for part in error.absolute_schema_path],
                "message": error.message,
            }
            for error in errors
        ]
    }
    return Score(
        name="schema_conformance",
        evaluator_id="canary.metrics.schema_conformance",
        evaluator_version="1",
        kind="code",
        score=0.0 if errors else 1.0,
        label="invalid" if errors else "valid",
        case_id=case_id,
        evidence=evidence,
    )


__all__ = ["schema_conformance"]
