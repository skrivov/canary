"""Shared pydantic configuration for public canary records."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class FrozenModel(BaseModel):
    """A closed, frozen record with camelCase serialization aliases."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        # Fields such as Usage.model_calls would otherwise make pydantic 2.7-2.9
        # warn at import time, which breaks applications that run with
        # warnings treated as errors.
        protected_namespaces=(),
    )


__all__ = ["FrozenModel"]
