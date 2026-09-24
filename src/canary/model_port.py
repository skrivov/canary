"""The only model-access shape canary knows: an injected async protocol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field

from ._models import FrozenModel


class Message(FrozenModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1)


@runtime_checkable
class ModelPort(Protocol):
    async def generate_object(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        operation: str,
    ) -> Mapping[str, Any]:
        """Return one schema-shaped object through the consumer's traced seam."""


__all__ = ["Message", "ModelPort"]
