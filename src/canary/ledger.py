"""The package's sole file writer: a strict append-only JSONL ledger."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import Field

from ._models import FrozenModel
from .hashing import canonical_json, content_hash

LEDGER_SCHEMA_VERSION = "canary-ledger/v1"
T = TypeVar("T")


class LedgerError(ValueError):
    """A ledger cannot be trusted as a complete sequence of records."""


class TruncatedLedgerError(LedgerError):
    """The final append did not reach its newline commit marker."""


class LedgerRecord(FrozenModel):
    schema_version: Literal["canary-ledger/v1"] = LEDGER_SCHEMA_VERSION
    case_id: str = Field(min_length=1)
    revision_identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    context_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    status: Literal["passed", "failed", "skipped"]
    payload: dict[str, Any] = Field(default_factory=dict)


def append(path: Path, record: LedgerRecord | Mapping[str, Any]) -> None:
    """Append one validated record with a single O_APPEND write."""

    validated = (
        record
        if isinstance(record, LedgerRecord)
        else LedgerRecord.model_validate(record)
    )
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    line = (
        canonical_json(validated.model_dump(by_alias=True, mode="json")) + "\n"
    ).encode("utf-8")
    # O_BINARY exists only on Windows, where descriptors otherwise open in text
    # mode and would rewrite every "\n" commit marker as "\r\n".
    descriptor = os.open(
        destination,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        written = os.write(descriptor, line)
        if written != len(line):  # pragma: no cover - defensive OS failure
            raise OSError(f"short ledger write: {written} of {len(line)} bytes")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read(path: Path) -> tuple[LedgerRecord, ...]:
    """Read a complete ledger, refusing malformed or truncated data."""

    source = Path(path)
    if not source.exists():
        return ()
    raw = source.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise TruncatedLedgerError(
            f"{source} ends without a newline; the final record is truncated"
        )
    records: list[LedgerRecord] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise LedgerError(f"{source}:{line_number}: blank ledger line")
        try:
            payload = json.loads(line, parse_constant=_reject_json_constant)
            records.append(LedgerRecord.model_validate(payload))
        except (json.JSONDecodeError, ValueError) as exc:
            raise LedgerError(f"{source}:{line_number}: {exc}") from exc
    return tuple(records)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def passing_checkpoints(path: Path) -> dict[str, str]:
    """Return the last passing revision identity for each case."""

    checkpoints: dict[str, str] = {}
    for record in read(path):
        if record.status == "passed":
            checkpoints[record.case_id] = record.revision_identity
    return checkpoints


def resume_filter(
    cases: Iterable[T],
    checkpoints: Mapping[str, str],
    *,
    case_id: Callable[[T], str],
    identity: Callable[[T], str],
) -> tuple[T, ...]:
    """Keep exactly the cases whose current identity has not passed."""

    return tuple(
        case
        for case in cases
        if checkpoints.get(case_id(case)) != identity(case)
    )


def revision_identity(case_content: Any, *revisions: Any) -> str:
    """Content-address one case together with every governing revision."""

    return content_hash({"case": case_content, "revisions": list(revisions)})


def context_fingerprint(context: Any) -> str:
    """Content-address consumer context used for parity assertions."""

    return content_hash({"context": context})


__all__ = [
    "LEDGER_SCHEMA_VERSION",
    "LedgerError",
    "LedgerRecord",
    "TruncatedLedgerError",
    "append",
    "context_fingerprint",
    "passing_checkpoints",
    "read",
    "resume_filter",
    "revision_identity",
]
