"""The examples are documentation that runs.

The quickstarts execute in a subprocess stripped of every provider credential,
which proves the offline path needs none. The provider adapters are exercised
against stand-in SDK modules, so the suite never installs a provider SDK or
opens a connection, yet still watches each adapter refuse, truncate, and
sanitize the way the integration guide promises.
"""

from __future__ import annotations

import importlib
import json
import os
import py_compile
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from canary.judge import ClosedChoiceJudge, FindingsJudge
from canary.model_port import Message

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
CREDENTIAL_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
)


def run_example(name: str, **env: str) -> subprocess.CompletedProcess[str]:
    clean = {key: value for key, value in os.environ.items() if key not in CREDENTIAL_VARIABLES}
    clean.pop("JUDGE_PROVIDER", None)
    clean.pop("JUDGE_MODEL", None)
    clean.update(env)
    return subprocess.run(
        [sys.executable, str(EXAMPLES / name)],
        capture_output=True,
        text=True,
        env=clean,
        timeout=60,
    )


def test_every_example_compiles(tmp_path: Path) -> None:
    for source in sorted(EXAMPLES.glob("*.py")):
        py_compile.compile(str(source), cfile=str(tmp_path / f"{source.stem}.pyc"), doraise=True)


def test_offline_quickstart_runs_without_credentials() -> None:
    result = run_example("offline_quickstart.py")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "case-1: correct (no failure)",
        "case-2: silent_wrong (subset)",
        "case-3: loud_fail (runtime_error)",
        "passing checkpoints: case-1",
    ]


def test_judge_quickstart_calibrates_and_scores_offline() -> None:
    result = run_example("judge_quickstart.py")
    assert result.returncode == 0, result.stderr
    first, _, rest = result.stdout.partition("\n")
    assert first.startswith("calibration: passed with 100% agreement on 6/6 records")
    score = json.loads(rest)
    assert score["label"] == "grounded"
    assert score["evaluatorVersion"] == "1:record-overlap-rule"
    assert score["evidence"]["calibration"]["status"] == "calibrated"


def test_judge_quickstart_explains_missing_configuration() -> None:
    result = run_example("judge_quickstart.py", JUDGE_PROVIDER="openai")
    assert result.returncode == 1
    assert "JUDGE_MODEL" in result.stderr
    unknown = run_example("judge_quickstart.py", JUDGE_PROVIDER="elsewhere")
    assert unknown.returncode == 1
    assert "unknown JUDGE_PROVIDER" in unknown.stderr


# --- provider adapters against stand-in SDK modules -------------------------


def stand_in_sdk(name: str) -> types.ModuleType:
    """The exception surface both official SDKs share."""

    module = types.ModuleType(name)

    class APIError(Exception):
        pass

    class APIStatusError(APIError):
        def __init__(self, message: str, status_code: int) -> None:
            super().__init__(message)
            self.status_code = status_code

    class AuthenticationError(APIStatusError):
        pass

    class PermissionDeniedError(APIStatusError):
        pass

    class RateLimitError(APIStatusError):
        pass

    class APIConnectionError(APIError):
        pass

    for cls in (
        APIError,
        APIStatusError,
        AuthenticationError,
        PermissionDeniedError,
        RateLimitError,
        APIConnectionError,
    ):
        setattr(module, cls.__name__, cls)
    return module


class Recorder:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.requests: list[dict[str, Any]] = []

    async def create(self, **request: Any) -> Any:
        self.requests.append(request)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def load_adapter(monkeypatch: pytest.MonkeyPatch, module: str, sdk: str) -> tuple[Any, types.ModuleType]:
    monkeypatch.syspath_prepend(str(EXAMPLES))
    fake = stand_in_sdk(sdk)
    monkeypatch.setitem(sys.modules, sdk, fake)
    return importlib.import_module(module), fake


CHOICE_SCHEMA = ClosedChoiceJudge(
    port=None,  # type: ignore[arg-type]
    evaluator_id="x",
    evaluator_version="1",
    choices={"grounded": 1.0, "unsupported": 0.0},
    operation="eval.x",
).output_schema
FINDINGS_SCHEMA = FindingsJudge(
    port=None,  # type: ignore[arg-type]
    evaluator_id="x",
    evaluator_version="1",
    criteria=("grounding",),
    localities=("answer",),
    operation="eval.x",
).output_schema
MESSAGES = (
    Message(role="system", content="Grade grounding."),
    Message(role="user", content="Record: A\nAnswer: A"),
    Message(role="tool", content="lookup ok"),
)


def anthropic_response(stop_reason: str, text: str | None) -> Any:
    blocks = [types.SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        blocks.append(types.SimpleNamespace(type="text", text=text))
    return types.SimpleNamespace(stop_reason=stop_reason, content=blocks)


def openai_response(content: str | None, *, refusal: str | None = None, finish: str = "stop") -> Any:
    message = types.SimpleNamespace(content=content, refusal=refusal)
    choice = types.SimpleNamespace(message=message, finish_reason=finish)
    return types.SimpleNamespace(choices=[choice])


@pytest.mark.asyncio
async def test_anthropic_adapter_shapes_the_request_and_reads_the_text_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _ = load_adapter(monkeypatch, "anthropic_port", "anthropic")
    recorder = Recorder(anthropic_response("end_turn", '{"label": "grounded", "explanation": null}'))
    port = adapter.AnthropicModelPort(client=types.SimpleNamespace(messages=recorder))

    payload = await port.generate_object(schema=FINDINGS_SCHEMA, messages=MESSAGES, operation="eval.x")

    assert payload == {"label": "grounded", "explanation": None}
    request = recorder.requests[0]
    assert request["model"] == adapter.DEFAULT_MODEL
    assert request["system"] == "Grade grounding."
    assert request["messages"] == [
        {"role": "user", "content": "Record: A\nAnswer: A"},
        {"role": "user", "content": "Tool output:\nlookup ok"},
    ]
    sent = request["output_config"]["format"]
    assert sent["type"] == "json_schema"
    assert "minLength" not in json.dumps(sent["schema"])


def test_anthropic_schema_conversion_touches_keywords_not_property_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _ = load_adapter(monkeypatch, "anthropic_port", "anthropic")
    converted = adapter.provider_schema(
        {
            "type": "object",
            "properties": {
                "minLength": {"type": "string", "minLength": 1},
                "explanation": {"type": ["string", "null"]},
            },
        }
    )
    assert converted["properties"]["minLength"] == {"type": "string"}
    assert converted["properties"]["explanation"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }
    choice = adapter.provider_schema(CHOICE_SCHEMA)
    assert choice["additionalProperties"] is False
    assert choice["properties"]["label"]["enum"] == ["grounded", "unsupported"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stop_reason", "text", "reason"),
    [
        ("refusal", None, "declined"),
        ("max_tokens", '{"label": "gro', "max_tokens"),
        ("end_turn", None, "no text block"),
        ("end_turn", "not json", "not JSON"),
    ],
)
async def test_anthropic_adapter_raises_instead_of_returning_partial_output(
    monkeypatch: pytest.MonkeyPatch, stop_reason: str, text: str | None, reason: str
) -> None:
    adapter, _ = load_adapter(monkeypatch, "anthropic_port", "anthropic")
    recorder = Recorder(anthropic_response(stop_reason, text))
    port = adapter.AnthropicModelPort(client=types.SimpleNamespace(messages=recorder))
    with pytest.raises(adapter.AnthropicPortError, match=reason):
        await port.generate_object(schema=CHOICE_SCHEMA, messages=MESSAGES, operation="eval.x")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "sdk", "error_type"),
    [
        ("anthropic_port", "anthropic", "AnthropicPortError"),
        ("openai_port", "openai", "OpenAIPortError"),
    ],
)
async def test_adapters_keep_provider_error_text_out_of_canary_artifacts(
    monkeypatch: pytest.MonkeyPatch, module: str, sdk: str, error_type: str
) -> None:
    adapter, fake = load_adapter(monkeypatch, module, sdk)
    leaked = "Incorrect API key provided: " + "sk-" + "proj-" + "Q" * 24
    recorder = Recorder(fake.AuthenticationError(leaked, 401))
    if sdk == "anthropic":
        port = adapter.AnthropicModelPort(client=types.SimpleNamespace(messages=recorder))
    else:
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=recorder))
        port = adapter.OpenAIModelPort(model="structured-model", client=client)

    with pytest.raises(getattr(adapter, error_type)) as raised:
        await port.generate_object(schema=CHOICE_SCHEMA, messages=MESSAGES, operation="eval.x")

    assert "sk-" not in str(raised.value)
    assert "API_KEY" in str(raised.value)
    assert raised.value.__cause__ is recorder.outcome

    recorder.outcome = fake.APIStatusError(leaked, 503)
    with pytest.raises(getattr(adapter, error_type), match="HTTP 503") as raised:
        await port.generate_object(schema=CHOICE_SCHEMA, messages=MESSAGES, operation="eval.x")
    assert "sk-" not in str(raised.value)


@pytest.mark.asyncio
async def test_openai_adapter_shapes_a_strict_json_schema_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _ = load_adapter(monkeypatch, "openai_port", "openai")
    recorder = Recorder(openai_response('{"findings": [], "met": ["grounding"]}'))
    client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=recorder))
    port = adapter.OpenAIModelPort(model="structured-model", client=client)

    payload = await port.generate_object(
        schema=FINDINGS_SCHEMA, messages=MESSAGES, operation="eval.answer-findings.repair"
    )

    assert payload == {"findings": [], "met": ["grounding"]}
    request = recorder.requests[0]
    assert [message["role"] for message in request["messages"]] == ["system", "user", "user"]
    assert request["messages"][2]["content"] == "Tool output:\nlookup ok"
    response_format = request["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["name"] == "eval_answer-findings_repair"
    assert "minLength" not in json.dumps(response_format)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (openai_response(None, refusal="I can't help with that."), "declined"),
        (openai_response('{"label": "gro', finish="length"), "token limit"),
        (openai_response(None), "no content"),
        (openai_response("not json"), "not JSON"),
    ],
)
async def test_openai_adapter_raises_instead_of_returning_partial_output(
    monkeypatch: pytest.MonkeyPatch, response: Any, reason: str
) -> None:
    adapter, _ = load_adapter(monkeypatch, "openai_port", "openai")
    client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=Recorder(response)))
    port = adapter.OpenAIModelPort(model="structured-model", client=client)
    with pytest.raises(adapter.OpenAIPortError, match=reason):
        await port.generate_object(schema=CHOICE_SCHEMA, messages=MESSAGES, operation="eval.x")
