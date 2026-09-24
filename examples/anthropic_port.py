"""A Canary ``ModelPort`` backed by the Anthropic Messages API.

This is application code, not part of Canary: copy it into your project and
adapt it. Canary never sees the API key. ``AsyncAnthropic()`` resolves
credentials itself from the application's environment — ``ANTHROPIC_API_KEY``,
or ``ANTHROPIC_AUTH_TOKEN``, or a profile stored by ``ant auth login`` — and
honours ``ANTHROPIC_BASE_URL`` when calls go through a gateway. If your
application already builds a configured client (proxy, timeouts, tracing),
pass that client in instead.

Requires the application dependency ``anthropic`` (``pip install anthropic``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from canary.model_port import Message

DEFAULT_MODEL = "claude-opus-5"

# Structured outputs do not accept these JSON Schema keywords. Canary
# re-validates every returned object against its closed rubric (and asks for
# one repair), so dropping them provider-side never weakens a verdict.
_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
    }
)
_SCHEMA_MAPS = frozenset({"properties", "$defs", "definitions"})

logger = logging.getLogger(__name__)


class AnthropicPortError(RuntimeError):
    """A sanitized provider failure.

    Canary records a port exception's text in calibration reports, so the
    message names the operation and status only — never a response body,
    header, or credential. The SDK exception stays attached as ``__cause__``
    for the application's own logs.
    """


class AnthropicModelPort:
    """Adapts ``anthropic.AsyncAnthropic`` to ``canary.model_port.ModelPort``.

    Refusals and truncated outputs raise instead of returning partial JSON, so
    a calibration run records them as unavailable rather than as answers.
    Server-side refusal fallbacks are deliberately not enabled: a different
    model answering would produce scores under a calibration that belongs to
    this model.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        client: Any | None = None,
        max_tokens: int = 16000,
    ) -> None:
        import anthropic  # an application dependency; Canary never imports it

        self._anthropic = anthropic
        self._client = client if client is not None else anthropic.AsyncAnthropic()
        self.model = model
        self.max_tokens = max_tokens

    async def generate_object(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        operation: str,
    ) -> Mapping[str, Any]:
        system, turns = to_anthropic_messages(messages)
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": turns,
            "output_config": {
                "format": {"type": "json_schema", "schema": provider_schema(schema)}
            },
        }
        if system:
            request["system"] = system

        logger.debug("canary model call %s on %s", operation, self.model)
        sdk = self._anthropic
        try:
            response = await self._client.messages.create(**request)
        except sdk.AuthenticationError as exc:
            raise AnthropicPortError(
                f"{operation}: Anthropic rejected the credentials; check "
                "ANTHROPIC_API_KEY (or your ant auth profile) in the application's "
                "environment"
            ) from exc
        except sdk.PermissionDeniedError as exc:
            raise AnthropicPortError(
                f"{operation}: the credentials may not use model {self.model}"
            ) from exc
        except sdk.RateLimitError as exc:
            raise AnthropicPortError(
                f"{operation}: rate limited after the SDK's retries"
            ) from exc
        except sdk.APIStatusError as exc:
            raise AnthropicPortError(
                f"{operation}: Anthropic API returned HTTP {exc.status_code}"
            ) from exc
        except sdk.APIConnectionError as exc:
            raise AnthropicPortError(
                f"{operation}: could not reach the Anthropic API"
            ) from exc

        if response.stop_reason == "refusal":
            raise AnthropicPortError(f"{operation}: the model declined to answer")
        if response.stop_reason == "max_tokens":
            raise AnthropicPortError(
                f"{operation}: output reached max_tokens before completing"
            )
        text = next(
            (block.text for block in response.content if block.type == "text"), None
        )
        if text is None:
            raise AnthropicPortError(f"{operation}: the response carried no text block")
        try:
            return json.loads(text)
        except ValueError as exc:
            raise AnthropicPortError(f"{operation}: the response was not JSON") from exc


def to_anthropic_messages(
    messages: Sequence[Message],
) -> tuple[str, list[dict[str, str]]]:
    """Hoist system turns into ``system``; send tool turns as user turns.

    Canary's judges put rubric instructions first and append an
    assistant/user pair only for a repair request, so hoisting system text
    keeps the conversation's order. Consecutive user turns are fine: the API
    combines them into one turn.
    """

    system = "\n\n".join(
        message.content for message in messages if message.role == "system"
    )
    turns = [
        {
            "role": "assistant" if message.role == "assistant" else "user",
            "content": (
                f"Tool output:\n{message.content}"
                if message.role == "tool"
                else message.content
            ),
        }
        for message in messages
        if message.role != "system"
    ]
    return system, turns


def provider_schema(schema: Any) -> Any:
    """Copy a JSON Schema into the subset structured outputs accept.

    Drops unsupported keywords and spells ``"type": [A, B]`` unions as
    ``anyOf`` branches; property names are never touched.
    """

    if isinstance(schema, list):
        return [provider_schema(item) for item in schema]
    if not isinstance(schema, Mapping):
        return schema
    converted: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_KEYWORDS:
            continue
        if key in _SCHEMA_MAPS and isinstance(value, Mapping):
            converted[key] = {name: provider_schema(item) for name, item in value.items()}
        else:
            converted[key] = provider_schema(value)
    kinds = converted.get("type")
    if isinstance(kinds, list):
        del converted["type"]
        converted["anyOf"] = [{"type": kind} for kind in kinds]
    return converted
