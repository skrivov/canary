"""Pure pre-registration manifests over caller-supplied source content."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from ._models import FrozenModel
from .hashing import canonical_json, content_hash
from .score import WorldRef

FREEZE_SCHEMA_VERSION = "canary-freeze/v1"


class FreezeManifest(FrozenModel):
    schema_version: Literal["canary-freeze/v1"] = FREEZE_SCHEMA_VERSION
    manifest_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime
    config_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    corpus_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_hashes: dict[str, str]
    world: WorldRef
    hypotheses: tuple[dict[str, Any], ...]
    config: dict[str, Any]

    @field_validator("created_at")
    @classmethod
    def _created_at_is_explicitly_zoned(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @field_validator("source_hashes")
    @classmethod
    def _source_hashes_are_complete(
        cls, value: dict[str, str]
    ) -> dict[str, str]:
        if not value:
            raise ValueError("source_hashes cannot be empty")
        if any(
            not name.strip()
            or len(digest) != 71
            or not digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in digest[7:])
            for name, digest in value.items()
        ):
            raise ValueError("source_hashes require names and lowercase SHA-256 ids")
        return value


def source_hash(content: str | bytes) -> str:
    """Hash source bytes without reading a path or consulting current code."""

    text = content.decode("utf-8") if isinstance(content, bytes) else content
    return content_hash({"source": text})


def build_freeze(
    *,
    config: Mapping[str, Any],
    corpus_hash: str,
    sources: Mapping[str, str | bytes],
    world: WorldRef,
    hypotheses: Sequence[Mapping[str, Any]],
    created_at: datetime,
) -> FreezeManifest:
    """Freeze all inputs; time and source bytes are explicit caller data."""

    if not sources:
        raise ValueError("at least one declared source is required")
    source_hashes = {
        str(name): source_hash(content)
        for name, content in sorted(sources.items())
        if str(name).strip()
    }
    if len(source_hashes) != len(sources):
        raise ValueError("source names must be non-empty and unique")
    identity = {
        "schemaVersion": FREEZE_SCHEMA_VERSION,
        "createdAt": created_at.isoformat(),
        "configHash": content_hash(config),
        "corpusHash": corpus_hash,
        "sourceHashes": source_hashes,
        "world": world.model_dump(by_alias=True, mode="json"),
        "hypotheses": list(hypotheses),
        "config": dict(config),
    }
    return FreezeManifest(
        manifest_id=content_hash(identity),
        created_at=created_at,
        config_hash=content_hash(config),
        corpus_hash=corpus_hash,
        source_hashes=source_hashes,
        world=world,
        hypotheses=tuple(dict(hypothesis) for hypothesis in hypotheses),
        config=dict(config),
    )


def render_preregistration(manifest: FreezeManifest) -> str:
    """Render a compact human-readable half of a freeze."""

    lines = [
        f"# Evaluation pre-registration — {manifest.manifest_id}",
        "",
        f"- Created: {manifest.created_at.isoformat()}",
        f"- World: {manifest.world.name} @ {manifest.world.revision}",
        f"- Config: {manifest.config_hash}",
        f"- Corpus: {manifest.corpus_hash}",
        "",
        "## Declared sources",
        "",
    ]
    lines.extend(
        f"- {name}: {digest}" for name, digest in manifest.source_hashes.items()
    )
    lines.extend(["", "## Hypotheses", ""])
    if manifest.hypotheses:
        for hypothesis in manifest.hypotheses:
            identifier = hypothesis.get("id") or "(unnamed)"
            statement = hypothesis.get("statement") or canonical_json(hypothesis)
            lines.append(f"- {identifier}: {statement}")
    else:
        lines.append("- None declared.")
    return "\n".join(lines) + "\n"


def preregistration_files(manifest: FreezeManifest) -> dict[str, str]:
    """Return the two artifacts for the consumer-controlled writer."""

    return {
        "preregistration.json": canonical_json(
            manifest.model_dump(by_alias=True, mode="json")
        )
        + "\n",
        "preregistration.md": render_preregistration(manifest),
    }


__all__ = [
    "FREEZE_SCHEMA_VERSION",
    "FreezeManifest",
    "build_freeze",
    "preregistration_files",
    "render_preregistration",
    "source_hash",
]
