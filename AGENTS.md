# Agent Instructions for canary

Canary is a provider-neutral evaluation kernel that applications install as a
library. It holds evaluation *method*; each application keeps its
*instruments*. `docs/design.md` records the invariants and design decisions —
read it before adding or moving anything, and keep it and `CHANGELOG.md`
honest when you land work.

## Invariants (do not erode)

1. **No provider SDKs, no network, no environment.** Nothing under
   `src/canary/` may import `openai`, `anthropic`, `litellm`, `langchain`,
   `google`, `boto3`, or any other model SDK or network client (`requests`,
   `httpx`, `aiohttp`, `urllib3`, …), and nothing may read environment
   variables or `.env` files. Model access enters only through the async
   `ModelPort` protocol and is supplied by the caller, whose own client reads
   its own API keys. `tests/test_boundaries.py` enforces this over the package
   AST; extend the forbidden sets rather than weakening them.
2. **Verdicts are derived.** Scoring, comparing, and diffing functions are
   pure: no I/O, no wall clock (`today` is a parameter), no randomness. The
   ledger module is the only writer, and it only appends. Any stored run must
   be re-scorable bit-for-bit without a provider or a database.
3. **Falsification rule.** Every grader, comparator, and metric ships with a
   test that shows it *failing* on a case built to fail it. A grader nobody
   has watched fail may be green for structural reasons, and a fixture with
   one value never tests the filter.
4. **Versioned records are closed.** `correct / loud_fail / silent_wrong`, the
   loud/silent subtypes, and the safety flags change only with a version bump
   plus a stated old-to-new mapping; so does every other `canary-*/vN`
   record. An edit that cannot say what old artifacts become is not landable.
5. **Rubric seeds are inert until calibrated.** Files under
   `src/canary/rubrics/` derived from Arize Phoenix are Elastic License 2.0
   material: keep each attribution block and `THIRD_PARTY_NOTICES.md` intact,
   and never let a seed score without a calibration report.
6. **Never publish to a package registry.** The bare name `canary` on PyPI
   belongs to an unrelated project. Canary is distributed from its Git
   repository and release wheels; the `Private :: Do Not Upload` classifier
   makes an accidental upload fail. Documentation must always show a pinned
   source, never a bare `pip install canary`.
7. **No secrets in the repository.** No API key, token, or `.env` file is ever
   committed — not in scripts, examples, fixtures, or docs.
   `tests/test_repository_hygiene.py` scans every publishable file.

## Working here

- Python floor is 3.11, and the dev interpreter is pinned to 3.11.16
  (`.python-version`): use no 3.12-only syntax. uv is pinned `>= 0.12.5`.
  The runtime dependency is Pydantic only; anything else goes behind an
  optional extra with a stated reason.
- Serialization uses camelCase aliases over snake_case fields
  (`populate_by_name=True`).
- Keep documentation application-neutral: describe integration patterns, not
  any particular application that uses Canary.
- Examples in `examples/` are application code. They may import provider
  SDKs lazily, must run offline by default, and are exercised by
  `tests/test_examples.py`.
- Run `.venv/bin/python -m pytest -q` before calling anything done. There is
  no CI; the local suite is the gate.
- Adoption work inside an application happens in that application's
  repository under its own rules. Parity evidence (re-score reports) lives
  with the application that produced it.
