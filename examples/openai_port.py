"""A Canary ``ModelPort`` backed by the OpenAI Chat Completions API.

This is application code, not part of Canary: copy it into your project and
adapt it. Canary never sees the API key. ``AsyncOpenAI()`` reads
``OPENAI_API_KEY`` (and, when set, ``OPENAI_BASE_URL``, ``OPENAI_ORG_ID``, and
``OPENAI_PROJECT_ID``) from the application's environment. For Azure OpenAI,
pass an ``openai.AsyncAzureOpenAI`` client, which reads
``AZURE_OPENAI_API_KEY``, ``AZURE_OPENAI_ENDPOINT``, and ``OPENAI_API_VERSION``.
If your application already builds a configured client, pass that instead.

Requires the application dependency ``openai`` (``pip install openai``).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from canary.model_port import Message

# Strict structured outputs reject string-length keywords. Canary re-validates
# every returned object against its closed rubric (and asks for one repair),
# so dropping them provider-side never weakens a verdict.
_UNSUPPORTED_KEYWORDS = frozenset({"minLength", "maxLength"})
_SCHEMA_MAPS = frozenset({"properties", "$defs", "definitions"})
_SCHEMA_NAME = re.compile(r"[^A-Za-z0-9_-]+")

logger = logging.getLogger(__name__)


class OpenAIPortError(RuntimeError):
    """A sanitized provider failure.

    Canary records a port exception's text in calibration reports, so the
    message names the operation and status only — never a response body,
    header, or credential. The SDK exception stays attached as ``__cause__``
    for the application's own logs.
    """


class OpenAIModelPort:
    """Adapts ``openai.AsyncOpenAI`` to ``canary.model_port.ModelPort``.

    Refusals and truncated outputs raise instead of returning partial JSON, so
    a calibration run records them as unavailable rather than as answers.
    """

    def __init__(self, *, model: str, client: Any | None = None) -> None:
        import openai  # an application dependency; Canary never imports it

        self._openai = openai
        self._client = client if client is not None else openai.AsyncOpenAI()
        self.model = model

    async def generate_object(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        operation: str,
    ) -> Mapping[str, Any]:
        request = {
            "model": self.model,
            "messages": [to_openai_message(message) for message in messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": _SCHEMA_NAME.sub("_", operation)[:64] or "canary_output",
                    "schema": provider_schema(schema),
                    "strict": True,
                },
            },
        }

        logger.debug("canary model call %s on %s", operation, self.model)
        sdk = self._openai
        try:
            completion = await self._client.chat.completions.create(**request)
        except sdk.AuthenticationError as exc:
            raise OpenAIPortError(
                f"{operation}: OpenAI rejected the credentials; check OPENAI_API_KEY "
                "in the application's environment"
            ) from exc
        except sdk.PermissionDeniedError as exc:
            raise OpenAIPortError(
                f"{operation}: the credentials may not use model {self.model}"
            ) from exc
        except sdk.RateLimitError as exc:
            raise OpenAIPortError(
                f"{operation}: rate limited after the SDK's retries"
            ) from exc
        except sdk.APIStatusError as exc:
            raise OpenAIPortError(
                f"{operation}: OpenAI API returned HTTP {exc.status_code}"
            ) from exc
        except sdk.APIConnectionError as exc:
            raise OpenAIPortError(f"{operation}: could not reach the OpenAI API") from exc

        choice = completion.choices[0]
        if getattr(choice.message, "refusal", None):
            raise OpenAIPortError(f"{operation}: the model declined to answer")
        if choice.finish_reason == "length":
            raise OpenAIPortError(
                f"{operation}: output reached the token limit before completing"
            )
        if not choice.message.content:
            raise OpenAIPortError(f"{operation}: the response carried no content")
        try:
            return json.loads(choice.message.content)
        except ValueError as exc:
            raise OpenAIPortError(f"{operation}: the response was not JSON") from exc


def to_openai_message(message: Message) -> dict[str, str]:
    """Send Canary's plain tool turns as user turns.

    Chat Completions reserves the ``tool`` role for replies to its own tool
    calls, which carry a call id that a plain Canary message does not have.
    """

    if message.role == "tool":
        return {"role": "user", "content": f"Tool output:\n{message.content}"}
    return {"role": message.role, "content": message.content}


def provider_schema(schema: Any) -> Any:
    """Copy a JSON Schema without keywords strict mode rejects.

    Property names are never touched, only schema keywords.
    """

    if isinstance(schema, list):
        return [provider_schema(item) for item in schema]
    if not isinstance(schema, Mapping):
        return schema
    return {
        key: (
            {name: provider_schema(item) for name, item in value.items()}
            if key in _SCHEMA_MAPS and isinstance(value, Mapping)
            else provider_schema(value)
        )
        for key, value in schema.items()
        if key not in _UNSUPPORTED_KEYWORDS
    }
