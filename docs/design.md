# Canary design

Evaluation plumbing tends to be rebuilt inside every application that needs
it, and the copies drift: a verdict taxonomy copied between projects gains
and loses categories, judge plumbing is reinvented with different failure
handling, and nobody can re-score old runs after the rules change. Canary
holds the evaluation *method* once. Each application keeps its
*instruments*: what it executes, its corpora, its prompts, its model access,
its storage, and its UI.

## Invariants

1. **No provider SDKs, no network, no environment.** Nothing under
   `src/canary/` imports a model SDK or network client, or reads environment
   variables. Model access enters only through the injected, async
   `ModelPort`. `tests/test_boundaries.py` enforces this over the package's
   syntax tree; extend its forbidden sets rather than weakening them.
2. **Verdicts are derived.** Comparing, scoring, and diffing are pure
   functions: no I/O, no wall clock (`today` is a parameter), no randomness.
   `canary.ledger` is the only writer, and it only appends. Any stored run can
   be re-scored bit-for-bit without a provider or a database.
3. **Falsification.** Every grader, comparator, and metric ships with a test
   that shows it failing on a case built to fail it. A grader nobody has
   watched fail may be green for structural reasons, and a fixture with one
   repeated value never tests a filter.
4. **The taxonomy is closed and versioned.** `correct / loud_fail /
   silent_wrong`, the loud and silent subtypes, and the safety flags change
   only with a version bump and a stated old-to-new mapping.
5. **Rubric seeds are inert until calibrated.** The bundled seeds are
   Elastic License 2.0 material with per-file provenance and
   `THIRD_PARTY_NOTICES.md`; none may score without a calibration report.
6. **Never publish to a registry under the bare name.** `canary` on PyPI
   belongs to an unrelated project. Canary is installed from a pinned Git
   source or a release wheel, and the `Private :: Do Not Upload` classifier
   makes an accidental upload fail.

## Decisions

Each decision lists the choice, why, the runner-up, and what would change it.

**D1 — Shape.** A standalone library in src layout, `requires-python >=
3.11`, with Pydantic as the only runtime dependency and `jsonschema` behind
the `schema` extra for the one metric that needs it. Runner-up: a module
copied into each application — rejected, because copying across repository
boundaries is exactly how the taxonomies drift.

**D2 — Distribution.** Applications pin a Git tag (or commit) or a release
wheel; the dependency and its source are declared separately (for example
`dependencies = ["canary"]` plus a `[tool.uv.sources]` entry). The explicit
source is also the dependency-confusion guard. Hermetic builds vendor the
wheel inside their build context, which needs no network and makes each
upgrade a visible diff. Runner-up: a registry release under a different
distribution name — deferred until someone needs registry installs.
The `canary-evals` agent skill ships from the same tags, as a plain folder or
through the Claude Code plugin marketplace in `.claude-plugin/`, whose one
entry pins the current release tag, so an agent's instructions always describe
a released API.

**D3 — Model seam: `ModelPort`, async, injected.** A protocol with one method,
`generate_object(*, schema, messages, operation) -> Mapping`. The application
adapts the traced, schema-enforced client it already has, and that client
keeps reading its own credentials. Async because application model clients
overwhelmingly are; synchronous callers use `asyncio.run`. Runner-up: shipping
provider wrappers inside Canary — rejected: it would create a second, untraced
path to the model and pull credentials into the library.

**D4 — Taxonomy.** Three verdicts, four loud subtypes, ten silent subtypes,
and four safety flags, versioned as `canary-taxonomy/1`. When an application
adopts Canary over an existing scorer, the top-level verdict and loud/silent
class must match bit-for-bit on stored history. Where Canary is finer, the
old-to-new subtype mapping must be deterministic and written down.

**D5 — `Score` normal form.** A frozen record with snake_case fields and
camelCase aliases: `name`, `evaluator_id`, `evaluator_version`, `kind` (`code`,
`llm`, or `human`), `direction` (`maximize` or `minimize`), `score`, `label`,
`explanation`, `evidence`, `world`, `dataset`, `case_id`, and `run_id`.
`score=None` means not scoreable and is never zero. Applications project
scores into their own rows; Canary never knows their tables.

**D6 — Purity.** Pure scoring is what makes offline re-scoring and parity
checks possible. Time, source contents, and world revisions are always
parameters.

**D7 — Judges.** `ClosedChoiceJudge` builds a closed JSON schema
(`additionalProperties: false`, every property required, optional values
nullable) from a `{label: score}` mapping, with an explanation by default.
`FindingsJudge` returns findings and leaves the arithmetic to the
application. A judge scores only with a passing `CalibrationReport` bound to
its exact identity and rubric hash; `allow_uncalibrated=True` exists for
authoring and is recorded in every artifact it produces. A malformed or
off-rubric answer gets one repair request; a second failure is unavailable,
never a silent pass.

**D8 — Rubric seeds.** Five Arize Phoenix rubric texts ship as JSON with
provenance blocks and are inert until calibrated locally. Reviewer and
evaluator strings name the model in a form no reader could mistake for a
person.

**D9 — Permanently out of scope.** Execution engines, corpus content, judge
prompt texts, trace storage, detectors, UI, observability export, and any
network access.

## Versioned records

Every stored record declares its schema version and fails validation under
any other version, so an old artifact is refused rather than misread.

| Record | Version |
|---|---|
| Verdict taxonomy | `canary-taxonomy/1` |
| Ledger line | `canary-ledger/v1` |
| Calibration report | `canary-calibration/v1` |
| Corpus manifest | `canary-corpus/v2` |
| Freeze manifest | `canary-freeze/v1` |
| Ruler | `canary-ruler/v1` |
| Rubric seed | `canary-rubric/v1` |

A change to any of them bumps its version, records the migration in
`CHANGELOG.md`, and — for the taxonomy — re-scores the parity fixtures of every
application that depends on it.

## Adopting Canary over existing evaluation code

1. Install Canary with a pinned source ([integration guide](integration.md)).
2. Project stored records into `Observation`, goldens, and `Score`, keeping
   product-specific parsing in the application.
3. Re-score stored history offline through both the old and the new path. Do
   not rerun models, providers, or databases to prove scorer parity; that
   measures a different world.
4. Require exact verdict parity; write down any finer subtype mapping and any
   excluded fields.
5. Delete the superseded logic in the same change, keeping at most a typed
   adapter.
6. For model judges, run old and new side by side in shadow mode, calibrate,
   explain every disagreement, then switch.
7. Diff runs only under matching, artifact-recorded rulers.

Parity evidence names its inputs: run IDs, ledger or trace paths, world
revision, dataset revision, the wheel's SHA-256 or commit, and exclusions.

## Traps

1. **Compare catalogs, not layers.** Before deleting an application's own
   taxonomy constants, find every reader — report renderers, docs, tests. A
   string literal in a renderer will not import Canary and will silently
   disagree.
2. **A green parity run names its inputs**, or it means nothing.
3. **Falsification harnesses restore in `finally`.** A mutation test that dies
   before restoring leaves production source mutated.
4. **Stale bytecode after same-second restores** during shadow comparisons: if
   behavior refuses to change back, clear `__pycache__`.
5. **Samples drawn close together underestimate variance.** Spread calibration
   and parity draws across time and configuration versions; sub-second
   repeated agreement can be one cached response.
6. **Canary emits records; applications own aggregates.** Canary never
   reconciles or refreshes an application's tables.
7. **Rubric provenance travels with the file.** Keep the provenance block and
   `THIRD_PARTY_NOTICES.md` with every copy of a seed.

## Deferred, with triggers

- **Embedding-similarity metric** — needs an embedding port; add it when an
  application needs one.
- **Bounded-concurrency executor** — add it when a calibration run hits a
  measured wall-clock problem; until then, concurrency is the port's job.
- **Observability export** — belongs to the application's tracing stack.
- **Annotation UI** — manifests plus hand labelling suffice at current scale.
