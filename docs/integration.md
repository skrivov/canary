# Using Canary in an existing application

Canary is built to drop into an application that already exists — its virtual
environment or lockfile, container image, CI, configured model client, API
keys, and storage — without changing any of them. This guide shows how: what
Canary needs (almost nothing), how to install it with the tools you already
use, and how to connect a model judge while your credentials stay exactly
where they are.

## 1. What Canary needs from your environment

| Need | Canary's answer |
|---|---|
| Python | 3.11 or newer. |
| Runtime dependencies | `pydantic>=2.7`, shared with your application (Pydantic v2 only). `jsonschema>=4.21` only with the `schema` extra. |
| Environment variables | None. Canary never reads `os.environ`, `.env` files, or configuration files. |
| API keys and credentials | None. Your application's model client keeps its own keys; Canary only calls the port object you hand it. |
| Network | None. No provider SDK or HTTP client is imported. |
| Files | Only `canary.ledger.append(path, record)` writes, to the path you pass. It appends, and creates new files readable by the owner only (mode `0600`). Every other API returns data for you to store. |
| Clocks, randomness, global state | None in scoring. Dates and timestamps are parameters. |
| Async | Model judges are `async`. Comparison, metrics, ledgers, freezes, and diffs are plain functions. |

The "no environment, no network, no provider SDK" guarantees are enforced by
`tests/test_boundaries.py`, which walks the package's syntax tree and fails on
any environment lookup, provider SDK, or network import.

## 2. Install into your project

> **Never install the bare name.** `pip install canary` or `uv add canary`
> resolves to an unrelated project on PyPI. Always pin Canary's source, as
> below. The pin is also your guard against dependency confusion when your
> installer consults more than one index.

### uv

```bash
uv add "git+https://github.com/skrivov/canary" --tag v0.4.0
uv add "git+https://github.com/skrivov/canary" --tag v0.4.0 --extra schema   # with JSON Schema metric
```

uv records the dependency and its source separately:

```toml
[project]
dependencies = ["canary[schema]"]

[tool.uv.sources]
canary = { git = "https://github.com/skrivov/canary", tag = "v0.4.0" }
```

`uv.lock` then records the exact commit the tag resolved to.

### pip, requirements files, and other PEP 508 tools

```bash
pip install "canary @ git+https://github.com/skrivov/canary@v0.4.0"
pip install "canary[schema] @ git+https://github.com/skrivov/canary@v0.4.0"
```

In `requirements.txt` or a `[project]` dependency list:

```text
canary[schema] @ git+https://github.com/skrivov/canary@v0.4.0
```

### Poetry

```bash
poetry add "git+https://github.com/skrivov/canary.git#v0.4.0"
```

### Pin a commit when immutability matters

Git tags can be moved. For a supply-chain-strict pin, use the full commit SHA
of the release instead of the tag: `--rev <sha>` with uv, or
`...canary@<sha>` in a PEP 508 requirement.

### Hermetic builds: Docker, air-gapped hosts, locked-down CI

Installing from Git builds the wheel inside your environment, which needs
`git` and access to the `uv_build` build backend from your package index.
Where either is unavailable, install the prebuilt wheel instead:

1. Download `canary-0.4.0-py3-none-any.whl` from the GitHub release and check
   its SHA-256 against the release notes, or build it from a checkout with
   `scripts/release.sh /path/to/your/app` (which copies it into
   `/path/to/your/app/vendor/`).
2. Commit the wheel under `vendor/` and point your project at the file:

   ```toml
   [project]
   dependencies = ["canary"]

   [tool.uv.sources]
   canary = { path = "vendor/canary-0.4.0-py3-none-any.whl" }
   ```

   With pip, use `./vendor/canary-0.4.0-py3-none-any.whl` in the
   requirements file, or in a Dockerfile:

   ```dockerfile
   COPY vendor/ vendor/
   RUN pip install ./vendor/canary-0.4.0-py3-none-any.whl
   ```

The wheel's filename carries the version, so an upgrade is a visible
two-line change in your repository.

### Private repositories and forks

If you install from a private repository, authenticate Git outside your
project files: use an SSH URL (`git+ssh://git@github.com/<owner>/canary.git`)
or a Git credential helper. Never put a token inside a URL in
`pyproject.toml`, a requirements file, or a lockfile: lockfiles copy the URL
verbatim. In CI, give the job's Git credential helper a token from the CI
secret store.

### Verify what was installed

```bash
python -c "import canary; print(canary.TAXONOMY_VERSION)"
```

This prints `canary-taxonomy/1`. An `AttributeError` means the unrelated
package was installed: uninstall `canary` and reinstall from the pinned
source. The [Codex skill](../skills/canary-evals/SKILL.md) ships
`scripts/inspect_canary.py`, which checks the installed distribution (or a
wheel file) for the right name, classifier, rubric seeds, and license notice.

## 3. Where Canary sits in your application

```text
your stored facts ──project──▶ Observation / Score ──▶ canary (pure) ──▶ VerdictRecord / Score / RunDiff ──▶ your storage

your model client ◀── ModelPort adapter (your code) ◀── canary judges
```

Keep product-specific parsing, execution, prompts, and persistence in your
application. Convert to Canary's neutral records at the boundary, and store
Canary's results in your own tables or files.

## 4. Model access and API keys

### The rule

Canary holds no credentials and reads no environment. Your keys stay where
they already are — the process environment, a `.env` file loaded by your
application, a secret manager, or a cloud identity — and your model client
reads them as it does today. A judge only ever calls:

```python
await port.generate_object(schema=..., messages=..., operation=...)
```

on the port object you constructed.

```text
secret store / environment ── ANTHROPIC_API_KEY, OPENAI_API_KEY, ...
        │
        ▼
provider SDK client (your application)
        │
        ▼
ModelPort adapter (your application) ──▶ ClosedChoiceJudge / FindingsJudge (canary)
```

### Variables the official SDKs read

These are read by the provider SDK inside your application, never by Canary:

| Provider | Client | Environment variables |
|---|---|---|
| Anthropic | `anthropic.AsyncAnthropic()` | `ANTHROPIC_API_KEY`, or `ANTHROPIC_AUTH_TOKEN`, or a profile saved by `ant auth login`; optional `ANTHROPIC_BASE_URL` |
| OpenAI | `openai.AsyncOpenAI()` | `OPENAI_API_KEY`; optional `OPENAI_BASE_URL`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID` |
| Azure OpenAI | `openai.AsyncAzureOpenAI()` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `OPENAI_API_VERSION` |
| Your own gateway or wrapper | whatever you use today | unchanged |

Settings such as which model a judge uses are your application's own. The
examples use `JUDGE_PROVIDER` and `JUDGE_MODEL`, but those names belong to the
example application; see [`.env.example`](../.env.example).

### The smallest adapter: wrap what you already have

If your application already has a traced function that returns JSON for a
schema, the adapter is a few lines. `ModelPort` is a runtime-checkable
protocol, so no inheritance is required:

```python
from collections.abc import Mapping, Sequence
from typing import Any

from canary.model_port import Message


class ApplicationModelPort:
    async def generate_object(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        operation: str,
    ) -> Mapping[str, Any]:
        # llm_json is your existing, traced, schema-enforced model call.
        return await llm_json(
            schema=dict(schema),
            messages=[message.model_dump(mode="json") for message in messages],
            trace_name=operation,
        )
```

### Ready-made provider adapters

Copy one into your application and adapt it:

- [`examples/anthropic_port.py`](../examples/anthropic_port.py):
  `AnthropicModelPort`, which uses the Messages API with structured outputs
  (`output_config.format`) and defaults to `claude-opus-5`.
- [`examples/openai_port.py`](../examples/openai_port.py): `OpenAIModelPort`,
  which uses Chat Completions with a strict `json_schema` response format.

Both adapters:

- construct the SDK client with no arguments, so the SDK reads its key from
  the environment — or accept the client your application already configured;
- map Canary's message roles onto the provider's (system text hoisted into
  Anthropic's `system` parameter; plain `tool` turns sent as user turns);
- drop JSON Schema keywords the provider rejects (`minLength` and friends).
  Canary validates every answer against its own closed rubric and asks for one
  repair, so the verdict is never weakened;
- raise on refusals and truncated outputs instead of returning partial JSON;
- raise sanitized errors (see below).

Wiring one up looks like this:

```python
import os

from anthropic import AsyncAnthropic

from canary.judge import ClosedChoiceJudge
from canary.model_port import Message
from your_app.eval_ports import AnthropicModelPort  # copied from examples/

model = os.environ.get("JUDGE_MODEL", "claude-opus-5")  # your setting, not Canary's
port = AnthropicModelPort(client=AsyncAnthropic(), model=model)

judge = ClosedChoiceJudge(
    port=port,
    evaluator_id="app.answer-grounding",
    evaluator_version=f"1:{model}",
    name="answer_grounding",
    choices={"grounded": 1.0, "unsupported": 0.0},
    operation="eval.answer-grounding",
    prompt_messages=(Message(role="system", content="..."),),
)
```

[`examples/judge_quickstart.py`](../examples/judge_quickstart.py) runs the
whole flow — calibration, activation, and one production score — against the
offline fake port by default, or against a real provider when you set
`JUDGE_PROVIDER` and the provider's key:

```bash
python examples/judge_quickstart.py                         # no key needed
JUDGE_PROVIDER=anthropic python examples/judge_quickstart.py  # uses ANTHROPIC_API_KEY
cp .env.example .env   # then edit; .env is ignored by git
uv run --env-file .env python examples/judge_quickstart.py
```

### Bind the model identity to calibration

A `CalibrationReport` applies only to the exact `evaluator_id`,
`evaluator_version`, and rubric hash it measured. Fold the model name into
`evaluator_version`, as above. Changing the model setting then makes the old
report inapplicable, and the judge raises `UncalibratedJudgeError` until you
recalibrate, instead of silently scoring a new model under an old model's
calibration.

For the same reason, do not enable provider-side automatic fallbacks to other
models for judges. A refusal should surface as an unavailable result, not as
an answer from a model that was never calibrated.

### Keep keys out of evaluation artifacts

Canary's outputs are meant to be stored, shared, and content-hashed: ledger
payloads, `Score` evidence, calibration reports (which embed every labelled
record and every error message), freeze manifests (whose `config` is copied
verbatim into `preregistration.json`), and rulers. Treat everything you pass
into Canary as publishable:

- Never put a credential, authorization header, or signed URL into `Message`
  content, judge `inputs`, `CalibrationRecord`s, `LedgerRecord.payload`,
  `Score.evidence`, `build_freeze(config=...)`, hypotheses, or operation
  names. Record the model name and its settings, not the client or its keys.
- Make your adapter raise sanitized exceptions. `calibrate()` records
  `"<ExceptionType>: <message>"` for every record whose model call failed, and
  some provider error messages quote part of the key (for example an
  "Incorrect API key provided: sk-…" message). The example adapters raise a
  message that names only the operation and the HTTP status, and keep the
  provider's exception as `__cause__` for your own logs.
- Keep `.env` files out of version control. This repository's `.gitignore`
  and `tests/test_repository_hygiene.py` enforce that here; add the same rule
  to your application.

### Tracing, retries, rate limits, and cost

- Route the adapter through the client your application already traces. The
  `operation` argument (for example `eval.answer-grounding`, and
  `eval.answer-grounding.repair` for the single repair attempt) makes a good
  span name.
- The official SDKs retry transient failures themselves. If you run many
  judge calls concurrently, bound concurrency inside your adapter, for
  example with an `asyncio.Semaphore`.
- Each judged case costs at most two model calls: the answer, plus one repair
  request if the answer broke the closed schema. Calibration costs one call
  per labelled record.

### Calling judges from sync and async code

- Async applications (FastAPI, aiohttp, async workers): `await judge.evaluate(...)`.
- Synchronous code and scripts: wrap the work in `asyncio.run(main())`.
- Notebooks: use top-level `await`.
- Batches: `await asyncio.gather(*(judge.evaluate(...) for case in cases))`.
  Judges keep no per-call state; your port decides how much concurrency the
  provider sees.

## 5. Test without keys

Use a fake port in your test suite: judge wiring, calibration, and persistence
are exercised with no credentials, no network, and no cost.
[`examples/fake_port.py`](../examples/fake_port.py) is one example. The
smallest useful fake returns a fixed answer:

```python
class FixedPort:
    def __init__(self, payload):
        self.payload = payload

    async def generate_object(self, *, schema, messages, operation):
        return self.payload
```

CI then needs no provider secrets. Exercise the real provider only in
environments that intentionally hold keys.

## 6. Store results in your own storage

- Serialize records with `model_dump(by_alias=True, mode="json")` to get
  camelCase JSON. Records accept snake_case or camelCase input.
- Store `score=None` as a null. It means "not scoreable" and is never zero.
- Use `outcome_id(run_id, evaluator_id, version)` as an idempotent row key.
  Bumping the evaluator version writes a new row beside the old one.
- `canary.ledger` is the only writer. `preregistration_files()` returns file
  contents, and your application decides where they go.

## 7. Give `compare` the facts it needs

`Observation` carries facts your application already knows. Supply
`query_fields`, `scope_predicates_present`, and `write_attempted` from your
own parser whenever a golden depends on them. When they are unset, `compare`
falls back to heuristics over `query_text` that suit only some query
languages:

- field conformance reads bracket-quoted identifiers (`[column]`) and JSON
  `field`/`value_field` keys;
- the scope check requires both of the literal column names `workspace_id` and
  `tenant_id`;
- the write check scans for SQL write verbs outside comments and string
  literals.

`failure_stage` selects the loud-failure subtype: `pre_execution` →
`rejected_pre_execution`; `generation` or `repair` → `repair_exhausted`;
`context`, `intent`, or `refusal` (or `disposition="refused"`) → `refused`;
anything else → `runtime_error`.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `AttributeError: module 'canary' has no attribute 'compare'` | The unrelated PyPI package is installed. | Uninstall it and install from the pinned Git source or wheel. |
| `ImportError: schema_conformance requires canary[schema]` | The optional extra is missing. | Depend on `canary[schema]` with the same source pin. |
| `UncalibratedJudgeError` | No passing calibration matches this judge's ID, version, and rubric. | Run `calibrate()` and attach the report with `with_calibration()`; recalibrate after changing the model, prompt, or choices. |
| Provider returns 400 about a schema keyword | The provider's structured-output mode rejects that keyword. | Drop it in the adapter; Canary re-validates the answer anyway. |
| `ValidationError` on `schemaVersion` of a corpus manifest | The manifest predates `canary-corpus/v2`. | Migrate it; see [CHANGELOG.md](../CHANGELOG.md). |
| A Git install fails while building | `git` or the `uv_build` backend is unavailable. | Install the release wheel instead (section 2). |
