---
name: canary-evals
description: Use the Canary Python evaluation library to install it from a pinned Git source or wheel, audit an installed copy, implement deterministic comparisons and metrics, project results into Score records, manage ledgers and freezes, add calibrated ModelPort judges, or compare runs under a shared ruler. Trigger for Canary integration, evaluator migration, parity re-scoring, calibration, rubric seeds, model-adapter and API-key wiring, and Canary-specific troubleshooting. Do not use for generic bird canaries, deployment canaries, or the unrelated public package named canary.
---

# Canary Evaluations

Use Canary as the evaluation method while leaving each application in control of
its instruments: execution, prompts, provider access, traces, corpora, storage,
and reporting.

## Start with discovery

1. Read the target repository's instructions and authoritative plan before
   editing.
2. Use its local `.venv` or `uv run` for every Python command when available.
3. Locate the existing evaluator seam, stored observations, result model, tests,
   and release gate. Extend those surfaces instead of creating a parallel stack.
4. Verify dependency provenance before importing Canary. Install only from a
   pinned source — the Git repository at a tag or commit, or a vendored release
   wheel — then run `scripts/inspect_canary.py` from this skill directory
   against the installed distribution or candidate wheel. Never run a bare
   `uv add canary` or `pip install canary`; it resolves to an unrelated public
   project.
5. Read [references/api-reference.md](references/api-reference.md) when choosing
   types or explaining nomenclature. Read
   [references/workflows.md](references/workflows.md) for implementation recipes
   and evidence gates.

## Choose the smallest fitting surface

- Use `compare()` plus a golden when an observation has a known answer shape.
- Use a pure metric when one local property is enough.
- Use `Score` to normalize code, model, and human evaluator outputs.
- Use `ledger`, `freeze`, `manifest`, and `stability` to make runs resumable and
  auditable.
- Use a judge only when deterministic rules cannot express the criterion.
- Use `Ruler` plus `diff_scores()` only for artifacts measured under the same
  grading standard.

Do not add a model judge merely because it is convenient. Prefer the deterministic
surface whenever it answers the question.

## Preserve Canary's boundaries

- Keep provider SDKs, HTTP clients, environment lookups, database access,
  clocks, randomness, and application storage outside Canary. A model enters
  only through an injected, async `ModelPort` adapter around the application's
  existing traced JSON seam.
- Leave credentials where the application keeps them. The provider client
  inside the adapter reads its own API key (for example `ANTHROPIC_API_KEY` or
  `OPENAI_API_KEY`) from the application's environment. Never put a key into
  messages, judge inputs, calibration records, ledger payloads, score
  evidence, or freeze configuration, and make adapters raise sanitized errors:
  `calibrate()` stores each failed call's exception text in its report.
- Pass ambient values explicitly: `today`, zoned `created_at`, source contents,
  world revisions, and corpus hashes.
- Treat `canary.ledger` as Canary's only writer. Other modules return values or
  artifact contents for the application to persist.
- Keep the closed verdict taxonomy intact. A taxonomy change requires a version
  bump and re-scoring of parity fixtures.
- Preserve `score=None` as “not scoreable”; never coerce it to zero or a pass.
- Serialize public Pydantic records with
  `model_dump(by_alias=True, mode="json")` when writing wire artifacts.
- Keep rubric provenance and `THIRD_PARTY_NOTICES.md` with every distributed
  wheel. A bundled rubric is an inert seed until calibrated.

## Implement deterministic evaluation

1. Project application facts into `Observation`; do not move witness execution
   into Canary.
2. Choose `IdSetGolden`, `AggregateGolden`, or `OrderedGolden` and pass an
   explicit `date` to `compare()`.
3. Retain the full `VerdictRecord`: top-level verdict, subtype, safety flags,
   metrics, and evidence. Safety flags are independent of correctness.
4. For a standalone evaluator, emit a stable `Score` with an evaluator ID,
   version, kind, direction, case ID, run ID, and world reference.
5. Add at least one test deliberately built to fail the evaluator. For branching
   graders, falsify every meaningful branch rather than varying only a label.

## Implement a model judge

1. Adapt the application's existing async, traced, schema-enforced model call to
   `ModelPort.generate_object()`; do not construct a second provider path. When
   the application has no such call, start from the Anthropic or OpenAI
   adapter in Canary's `examples/` directory.
2. Use `ClosedChoiceJudge` for a fixed label set or `FindingsJudge` when the
   application must retain concrete issues and own the arithmetic.
3. Give the judge a stable evaluator ID, a version that identifies the model or
   model configuration, an operation name, and a closed prompt schema.
4. Build hand-labelled `CalibrationRecord` values, run `calibrate()`, persist the
   report, and require `report.calibrated` before production scoring.
5. Attach the report with `with_calibration()`. Prompt, choices, direction,
   evaluator identity, or rubric changes invalidate the calibration binding.
6. Use `allow_uncalibrated=True` only for explicit authoring or calibration
   workflows whose artifacts remain visibly marked uncalibrated.
7. Treat a second malformed or off-rubric response as unavailable or
   unscoreable, never as a passing answer.

## Migrate or compare existing evaluations

1. Freeze the old implementation and name the stored run, dataset, world, and
   evaluator versions.
2. Re-score stored observations offline through both paths. Do not rerun models,
   providers, witnesses, or databases merely to prove scorer parity.
3. Require exact result identity where semantics are unchanged. If the shared
   taxonomy is more precise, record an explicit old-to-new subtype mapping.
4. Keep the application-facing CLI and artifact schema stable unless the task
   explicitly authorizes a contract change.
5. Delete superseded scoring logic in the same change once parity is proven;
   retain only a typed adapter or re-export when an application seam requires it.
6. Before diffing runs, construct rulers from recorded artifacts. Treat a ruler
   mismatch as a measurement change, not product improvement or regression.

## Verify before handing off

- Run the focused tests, then the repository's full local gate.
- Run `scripts/inspect_canary.py` against the exact vendored wheel, if any,
  and, after locking, against the target environment.
- Confirm the lockfile pins Canary's Git tag or commit, or the vendored wheel,
  and that the distribution carries the `Private :: Do Not Upload`
  classifier, five required rubric seeds, and third-party notice.
- Confirm no credential entered a Canary record or a committed file.
- Confirm every new grader has a witnessed failing case.
- Confirm judge evidence names the calibration artifact and exact judge identity.
- Confirm parity evidence names the input run, artifact path, world revision, and
  any intentional exclusions.
- Report library qualification separately from application adoption and runtime
  proof. One does not imply the other.
