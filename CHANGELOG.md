# Changelog

All notable changes to Canary are recorded here. Versions follow semantic
versioning; while the major version is 0, a minor bump may change the public
API, and every such change is listed with its migration.

## 0.4.0 — 2026-09-24

First public release.

### Changed (breaking)

- **Corpus manifests are application-neutral.** The two review profiles are
  now `checklist` and `annotation`, and the manifest schema is
  `canary-corpus/v2`; a `canary-corpus/v1` manifest is refused rather than
  misread.
  - `ChecklistReview` replaces the fixed-field checklist review. A manifest
    declares its own dimensions in `required_checks`, and every review signs
    them off in `checks` (name → bool) plus `blessed`. Missing, extra, or
    `False` dimensions reject the manifest.
  - `AnnotationReview` keeps its fields; only its profile literal changed, to
    `annotation`.

  To migrate a stored v1 manifest: set `schemaVersion` to `canary-corpus/v2`;
  set `profile` on the manifest and on every review to `checklist` or
  `annotation`; for checklist manifests, move each boolean `*Reviewed` field
  of each review into `checks` under a dimension name of your choice, and list
  the same names in `requiredChecks`.

### Added

- `docs/integration.md`: installing into an existing environment (uv, pip,
  Poetry, commit pins, vendored wheels, private forks), the `ModelPort`
  adapter pattern, the environment variables each provider SDK reads,
  binding the model identity to calibration, and keeping credentials out of
  stored artifacts.
- `examples/`: an offline quickstart, a calibrated-judge quickstart, an
  offline fake port, and copyable `ModelPort` adapters for the Anthropic and
  OpenAI SDKs that raise sanitized errors.
- Boundary tests that fail if the package reads environment variables or
  loads `.env` files, and more provider SDKs in the forbidden-import set.
- A repository hygiene test that fails on credential-shaped strings or
  committed `.env` files in any publishable file.
- `LICENSE` (MIT) for Canary's own code; the rubric seeds remain Elastic-2.0.
  `SECURITY.md` and `docs/design.md`.

### Fixed

- `canary.ledger.append` opens files in binary mode where the platform
  distinguishes it, so ledgers written on Windows keep `\n` line endings and
  stay byte-identical across platforms.
- Importing Canary no longer emits pydantic's "protected namespace" warning
  on pydantic 2.7–2.9 (triggered by `Usage.model_calls`), so applications that
  treat warnings as errors can import it across the whole supported range.

### Unchanged

- The verdict taxonomy (`canary-taxonomy/1`) and every other record schema:
  verdicts, scores, ledgers, calibration reports, freezes, rulers, and rubric
  seeds from 0.3.0 remain valid and re-score identically.

## 0.3.0

Initial kernel: closed verdict taxonomy and golden comparators, `Score`
normal form, append-only re-scorable JSONL ledger, pure metrics, async
`ModelPort` with closed-choice and findings judges, calibration-gated
activation, stability arithmetic, corpus manifests, source/world freezes, run
diffing with ruler refusal, and five attributed rubric seeds.
