# Canary API and evaluation nomenclature

Use this reference to select the correct public surface and explain results in
plain language. Examples target Canary 0.4.0 and Python 3.11 or newer.

## Core result vocabulary

| Term | Plain-language meaning |
|---|---|
| Case | One example being tested. |
| Observation | What actually happened: output rows or IDs, query text, failure details, retries, and usage. |
| Golden | The answer key or expected behavior. |
| Verdict | A closed category describing whether execution was correct, visibly failed, or silently returned the wrong result. |
| Safety flag | An independent warning. A correct result can still be unsafe. |
| Score | The immutable common record for code, model, and human evaluators. |
| Evidence | Facts supporting a result, such as missing IDs or validation errors. |
| World | A named, content-addressed data and schema revision. |
| Ruler | The recorded grading standard used to decide whether two runs are comparable. |

All public Pydantic records accept snake_case fields and emit camelCase aliases.
They reject unknown fields and are frozen after construction.

## Deterministic golden comparisons

Import the common types from `canary`.

| API | Use it to answer | Output |
|---|---|---|
| `IdSetGolden` + `compare()` | Did we return exactly the right items, ignoring order and duplicates? | `VerdictRecord`, plus precision, recall, and F1 evidence. |
| `AggregateGolden` + `AggregateEntry` + `compare()` | Did we return the right scalar or one numeric value per group? | `VerdictRecord` with missing, extra, malformed, or wrong-value detail. |
| `OrderedGolden` + `compare()` | Did we return the right items in the right ranking? | `VerdictRecord` separating membership and ordering failures. |
| `Observation` | What application facts should the comparator see? | A neutral, immutable input record. |

`compare(observation, golden, *, today=date(...))` is pure. The explicit date is
evidence that the evaluator did not consult the wall clock.

A golden's `expected_outcome` is one of:

- `result`: a normal result is expected;
- `supported_empty`: an empty result is a valid answer;
- `honest_failure`: safe non-execution is correct and executing is wrong.

## Verdict taxonomy

`TAXONOMY_VERSION` is `canary-taxonomy/1` in Canary 0.4.0.

| Verdict | Meaning |
|---|---|
| `correct` | The observation matches the answer key. |
| `loud_fail` | The system visibly failed, refused, or produced nothing executable. |
| `silent_wrong` | The system appeared to work but produced the wrong answer or executed when it should not have. |

Loud-failure subtypes:

| Subtype | Meaning |
|---|---|
| `rejected_pre_execution` | Rejected before execution began. |
| `runtime_error` | Failed in a tool, database, or runtime after execution began. |
| `repair_exhausted` | Output repair attempts were exhausted. |
| `refused` | Explicitly declined or could not proceed with the available context. |

Silent-wrong subtypes:

| Subtype | Meaning |
|---|---|
| `empty_wrong` | Returned nothing when something was expected. |
| `subset` | Returned only valid items but missed some expected items. |
| `superset` | Returned every expected item plus invalid extras. |
| `overlap` | Mixed valid and invalid items, with expected items also missing. |
| `disjoint` | Returned and expected sets have no items in common. |
| `wrong_value` | A scalar or grouped numeric result is outside tolerance. |
| `wrong_order` | Correct membership, incorrect ranking or sort order. |
| `ambiguous_shape` | Missing or ambiguous columns prevent reliable interpretation. |
| `field_conformance` | Required authored fields are absent or disallowed fields are present. |
| `unexpected_execution` | Execution happened when honest failure was expected. |

Safety flags:

| Flag | Meaning |
|---|---|
| `decoy_leak` | Output exposed a planted value that should never appear. |
| `missing_scope_predicate` | A required tenant or workspace boundary is absent. |
| `write_attempt` | Generated text attempted a data-changing operation. |
| `cap_hit` | Truncation or an output limit makes completeness uncertain. |

## Pure metrics

Import these from `canary.metrics`, except for the optional schema function.

| API | Plain-language question | Result |
|---|---|---|
| `exact_match()` | Is text identical, optionally ignoring case? | Binary `Score`. |
| `matches_regex()` | Does text contain or fully match a required pattern? | Binary `Score`. |
| `set_relation()` | Are two sets exact, empty, subset, superset, overlapping, or disjoint? | Relationship label. |
| `id_set_score()` | Are observed and expected ID sets equal? | Binary `Score` with overlap evidence. |
| `span_iou()` | How much do two text ranges overlap? | Number from 0 to 1. |
| `match_spans()` | Which predicted and expected ranges match one-to-one? | Pairing details. |
| `precision_recall_f1()` | How many matches, extras, and misses are present? | Three diagnostic numbers. |
| `span_f1_score()` | Did extraction find the expected ranges at the chosen overlap threshold? | F1 `Score`. |
| `contains_write_verb()` | Does query text contain a data-changing verb outside strings and comments? | Boolean. |
| `contains_forbidden_value()` | Does nested output contain an exact prohibited value? | Boolean. |
| `safety_score()` | Did query and payload avoid configured safety violations? | Binary safe/unsafe `Score`. |
| `schema_conformance()` | Does a JSON-like value obey a JSON Schema? | Binary valid/invalid `Score`; requires `canary[schema]`. |

Precision asks “of what was returned, how much was right?” Recall asks “of what
was expected, how much was found?” F1 balances both.

## Score normal form

`canary.Score` records:

- `name`: criterion name; it must match a ruler criterion when diffing;
- `evaluator_id` and `evaluator_version`: stable producer identity;
- `kind`: `code`, `llm`, or `human`;
- `direction`: `maximize` or `minimize`;
- `score`: finite number or `None` for unavailable/unscoreable;
- `label`, `explanation`, and structured `evidence`;
- optional `world`, `dataset`, `case_id`, and `run_id`.

Use `WorldRef` to bind a score to named, content-addressed data. Use
`outcome_id(run_id, evaluator_id, version)` for idempotent application rows.

## Model judging

| API | Use it when | Output |
|---|---|---|
| `ModelPort` | Adapting the application's existing async traced JSON-model seam. The application's client keeps reading its own API key. | Provider-neutral protocol. |
| `Message` | Passing role/content messages into a judge. | Immutable message. |
| `ClosedChoiceJudge` | The result must be one declared label. | `Score` with choice, number, and explanation. |
| `FindingsJudge` | The application needs concrete issues and owns later arithmetic. | `FindingsResult` with findings and met criteria. |
| `CalibrationRecord` | Recording one hand-labelled judge example. | Labelled input and rationale. |
| `calibrate()` | Measuring the exact judge against labelled examples. | Identity-bound `CalibrationReport`. |

The default calibration gate requires at least five available records and 80%
aggregate agreement. A report applies only to the exact evaluator ID, version,
and rubric hash that produced it.

## Bundled rubric seeds

Use `available_rubrics()`, `load_rubric()`, and `judge_from_rubric()` from
`canary.rubrics`. Loading a seed performs no scoring.

| Seed | What it checks | Labels and direction |
|---|---|---|
| `hallucination` | Claims unsupported by supplied conversation, records, or tool results. | `grounded=0`, `hallucinated=1`; minimize. |
| `tool_selection` | Whether the right tool was chosen. | `correct=1`, `incorrect=0`; maximize. |
| `tool_invocation` | Whether arguments, formatting, and safety were correct. | `correct=1`, `incorrect=0`; maximize. |
| `tool_response_handling` | Whether tool output and errors were understood and used safely. | `correct=1`, `incorrect=0`; maximize. |
| `user_friction` | Whether the next user message shows assistant-caused frustration. | `no_friction=0`, `friction=1`; minimize. |

## Reliability and governance APIs

| Module | Main APIs | Purpose |
|---|---|---|
| `canary.hashing` | `canonical_json`, `content_hash` | Stable canonical serialization and SHA-256 content identities. |
| `canary.ledger` | `LedgerRecord`, `append`, `read`, `passing_checkpoints`, `resume_filter`, `revision_identity`, `context_fingerprint` | Strict append-only history and exact resume. |
| `canary.freeze` | `build_freeze`, `preregistration_files` | Record config, corpus, sources, hypotheses, time, and world before a run. |
| `canary.manifest` | `CorpusManifest`, `ChecklistReview`, `AnnotationReview` | Fail closed when case counts or review provenance are incomplete. The `checklist` profile checks the dimensions a manifest declares in `required_checks`; the `annotation` profile checks hashed annotation approvals. |
| `canary.stability` | `bar`, `score_bar`, `n_sensitivity` | Require at least `ceil(2n/3)` successes and show sample-size sensitivity. |
| `canary.ruler` | `Ruler`, `compare_rulers`, `assert_same_ruler` | Fingerprint and verify the grading standard recorded in artifacts. |
| `canary.diff` | `diff_scores` | Partition cases into improved, regressed, mixed, unchanged, or incomparable. |

`preregistration_files()` returns file contents; the application writes them.
`read()` refuses blank, malformed, non-finite, or truncated ledger lines.
`diff_scores()` refuses ruler mismatches and treats any `score=None` pair as
incomparable.
