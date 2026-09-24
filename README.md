# Canary

Canary is a small, provider-neutral evaluation kernel for Python 3.11+. Its
deterministic path turns stored observations into reproducible verdicts and
scores without a model, database, clock, or network service. Optional model
judges call only an async port supplied by the consuming application, so
Canary never touches API keys or provider SDKs.

Use Canary when you need:

- a closed `correct / loud_fail / silent_wrong` verdict taxonomy;
- deterministic comparison against ID-set, aggregate, or ordered goldens;
- a common `Score` record for code, model, and human evaluators;
- append-only JSONL checkpoints and content-addressed run identities;
- closed-schema judges that cannot score until they are calibrated;
- frozen evaluation inputs and artifact-bound run diffing; or
- pure set, span, safety, text, and optional JSON Schema metrics.

Canary contains evaluation method. Your application still owns data
collection, model access and credentials, databases, prompts, report formats,
and UI.

New to evaluation terminology? Start with the plain-language
[evaluation nomenclature](TUTORIAL.md#evaluation-nomenclature), which catalogs
every built-in comparison, metric, judge mode, rubric seed, verdict, subtype,
and safety flag.

## Install

The name `canary` on PyPI belongs to an unrelated project, so never install
the bare name. Pin Canary's Git source instead:

```bash
uv add "git+https://github.com/skrivov/canary" --tag v0.4.0
```

```bash
pip install "canary @ git+https://github.com/skrivov/canary@v0.4.0"
```

Add the `schema` extra (`--extra schema` with uv, `canary[schema] @ ...` with
pip) for the JSON Schema conformance metric. The only other runtime dependency
is Pydantic v2, which Canary shares with your application.

For Docker images, air-gapped hosts, or CI without Git access, vendor the
release wheel and point your project at the file. The
[integration guide](docs/integration.md#2-install-into-your-project) covers
uv, pip, Poetry, commit pinning, vendored wheels, and private forks.

## Quick start

The simplest evaluation projects application data into a neutral
`Observation`, compares it with a golden, and stores the resulting
`VerdictRecord`:

```python
from datetime import date

from canary import IdSetGolden, Observation, compare

golden = IdSetGolden(
    id_column="contract_id",
    ids=("C-100", "C-200"),
)
observation = Observation(
    executed=True,
    columns=("contract_id",),
    rows=(
        {"contract_id": "C-100"},
        {"contract_id": "C-200"},
    ),
)

verdict = compare(observation, golden, today=date(2026, 9, 1))

assert verdict.verdict == "correct"
assert verdict.subtype is None
assert verdict.metrics["f1"] == 1.0
```

`today` is explicit because comparison is pure. The same stored observation
and golden always produce the same verdict.

Runnable versions live in [`examples/`](examples/): `offline_quickstart.py`
needs nothing but Canary, and `judge_quickstart.py` calibrates and runs a model
judge, against an offline fake by default or against a real provider when you
set its API key.

## Using Canary inside your application

Canary plugs into the environment your application already has:

- **Configuration and secrets.** Canary reads no environment variables, `.env`
  files, or configuration files, and holds no credentials. Tests enforce this.
- **Model access.** Wrap the model client your application already uses (and
  traces) in a small `ModelPort` adapter. The client keeps reading its own API
  key — for example `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` — from your
  environment. Ready-made adapters for the Anthropic and OpenAI SDKs are in
  [`examples/`](examples/).
- **Storage.** Canary returns records. Your application stores them wherever
  it stores data today; only `canary.ledger.append` writes a file, and only to
  the path you pass.
- **Re-scoring.** Stored observations can be re-scored offline, with no
  provider call, whenever the rules improve.

Read the [integration guide](docs/integration.md) before wiring a model judge:
it covers the adapter pattern, which environment variables each provider SDK
reads, binding the model identity to calibration, and keeping keys out of
stored evaluation artifacts.

## Codex skill

The source-controlled [Canary Evaluations skill](skills/canary-evals/SKILL.md)
guides Codex through pinned installation, API selection, deterministic
re-scoring, judge calibration, and parity evidence. It also includes a helper
that rejects the unrelated public package and verifies the classifier, rubric
seeds, license notices, version, and optional wheel digest.

Install the skill by copying its complete directory into the Codex skills
directory:

```bash
canary_skill_root="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$canary_skill_root"
test ! -e "$canary_skill_root/canary-evals"
cp -R skills/canary-evals "$canary_skill_root/canary-evals"
```

Invoke it explicitly as `$canary-evals`; automatic discovery remains enabled.

## Core rules

- Do not add provider SDKs, networking, or environment lookups to Canary.
  Supply model access through `ModelPort`.
- Never pass credentials into Canary records: messages, judge inputs,
  calibration records, ledger payloads, score evidence, and freeze
  configuration are all meant to be stored and shared.
- Treat `score=None` as unscoreable, never as numeric zero.
- Pass clocks and source content explicitly; do not read ambient state inside
  scoring code.
- Use `canary.ledger` as Canary's only writer. Other artifacts are returned as
  data for the consuming application to persist.
- Attach a passing `CalibrationReport` to the exact judge identity and rubric
  before production scoring.
- Diff only scores measured with matching artifact-recorded rulers.
- Add a falsification test for every comparator, grader, and metric: every
  evaluator must be observed failing a deliberately failing case.

## Documentation

- [Evaluation nomenclature](TUTORIAL.md#evaluation-nomenclature) — the complete
  evaluator catalog in plain language.
- [Tutorial](TUTORIAL.md) — end-to-end examples of every surface.
- [Integration guide](docs/integration.md) — installing into an existing
  environment, model adapters, and API keys.
- [Examples](examples/) — runnable quickstarts and provider adapters.
- [Design](docs/design.md) — invariants, design decisions, and adoption method.
- [Changelog](CHANGELOG.md) — release notes and migrations.
- [Security policy](SECURITY.md) — reporting vulnerabilities and secret
  handling.
- [Codex skill](skills/canary-evals/SKILL.md) — reusable implementation and
  verification workflow.

## Develop Canary

```bash
uv sync --extra schema
.venv/bin/python -m pytest -q
scripts/release.sh
```

`scripts/release.sh` runs the suite, builds the wheel and sdist into `dist/`,
and prints the wheel's SHA-256. Given an application directory, it also copies
the wheel into that directory's `vendor/` folder and prints the source stanza
to add there.

## Questions, bugs, and security reports

All communication about Canary happens in its GitHub repository. Open an
[issue](https://github.com/skrivov/canary/issues) for questions, bugs, and
feature requests. Report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md) — never in a public issue.

## License

Canary's own code is released under the [MIT License](LICENSE).

The five rubric seeds in `src/canary/rubrics/*.json` are modified copies of
Arize Phoenix rubric texts and remain under the Elastic License 2.0; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). If ELv2 terms do not suit
your use, leave the seeds unused. Everything else in Canary works without
them.
