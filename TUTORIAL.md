# Canary tutorial

This tutorial takes one evaluation workflow from its first deterministic check
to a calibrated LLM judge and a run diff you can defend in review. Along the
way you will catch a silent failure, checkpoint results in an append-only
ledger, freeze an experiment before running it, make a judge prove itself
against hand-labelled examples, and re-score stored history without calling a
model.

The examples target Canary 0.4.0 and Python 3.11 or newer. Each section
stands on its own. If the vocabulary is new, start with the
[evaluation nomenclature](#evaluation-nomenclature).

## 1. Install Canary safely

Canary is installed from its Git repository or from a release wheel. Never
install the bare name from a package registry; `canary` on PyPI is an
unrelated project.

In a uv project, pin the Git source (drop `--extra schema` if you do not need
JSON Schema conformance):

```bash
uv add "git+https://github.com/skrivov/canary" --tag v0.4.0 --extra schema
```

uv declares the dependency and its source separately, and `uv.lock` records
the exact commit:

```toml
[project]
dependencies = ["canary[schema]"]

[tool.uv.sources]
canary = { git = "https://github.com/skrivov/canary", tag = "v0.4.0" }
```

With pip, use `canary[schema] @ git+https://github.com/skrivov/canary@v0.4.0`.
For hermetic builds, vendor the release wheel and use
`canary = { path = "vendor/canary-0.4.0-py3-none-any.whl" }` as the source.
The [integration guide](docs/integration.md) covers every installer, commit
pinning, and private forks.

## 2. Understand the evaluation boundary

Canary owns method:

- neutral observations and goldens;
- deterministic verdict and metric derivation;
- immutable `Score` records;
- calibration rules and closed judge schemas;
- content identities, checkpoints, freezes, rulers, and run diffs.

Your application owns instruments:

- executing queries or agents;
- collecting traces and rows;
- calling a model through an existing traced seam, with its own API keys;
- choosing corpus cases and prompt text;
- writing non-ledger artifacts and database rows;
- rendering reports and UI.

The practical rule is: reduce application-specific data to Canary types at the
boundary, then project Canary's result back into application-owned storage.

## Evaluation nomenclature

This section is the complete plain-language catalog of evaluation concepts and
built-in evaluators in Canary. No machine-learning background is required.

### The basic nouns

| Term | Plain-language meaning |
|---|---|
| **Evaluation** or **evaluator** | A named rule that examines one case and produces a verdict, score, or list of findings. |
| **Case** | One example to test, such as one question, query, document, or agent run. |
| **Observation** | What actually happened: returned rows, IDs, query text, failure details, attempts, and usage. |
| **Golden** | The expected answer or expected behavior for the case. It is the answer key. |
| **Verdict** | A categorical conclusion: correct, visibly failed, or silently wrong. |
| **Subtype** | A more precise explanation of why a verdict failed. |
| **Safety flag** | A separate warning about unsafe behavior. A result can be factually correct and still have a safety flag. |
| **Score** | A common result record. Its number may be present, or `None` when the case could not be scored. |
| **Label** | A readable category attached to a score, such as `pass`, `fail`, `grounded`, or `subset`. |
| **Evidence** | The facts that justify the result, such as missing IDs, validation errors, or an explanation. |
| **Evaluator ID and version** | The stable identity of the rule that produced the result. Changing the rule requires a new version. |
| **Kind** | Who or what evaluated the case: deterministic code, a model judge, or a human. |
| **Direction** | Whether a larger number is better (`maximize`) or a smaller number is better (`minimize`). |
| **World** | The named, content-addressed data and schema revision against which the case ran. |

A golden can expect one of three outcomes:

| Expected outcome | Meaning |
|---|---|
| `result` | A normal answer is expected. |
| `supported_empty` | An empty answer is valid because the answer key itself is empty. |
| `honest_failure` | Safe non-execution is the correct behavior; executing anyway is wrong. |

### Deterministic answer comparisons

These evaluators use ordinary code. They do not call a model and always return
the same result for the same inputs.

| Evaluation | API | Question it answers | Result |
|---|---|---|---|
| **ID-set comparison** | `IdSetGolden` + `compare` | Did we return exactly the right items, regardless of order or duplicates? | A `VerdictRecord` with set-relation evidence and precision, recall, and F1 measurements. |
| **Aggregate comparison** | `AggregateGolden` + `compare` | Did we return the right number, or the right number for every group? | A verdict that detects empty, malformed, missing, extra, or numerically wrong groups. |
| **Ordered comparison** | `OrderedGolden` + `compare` | Did we return the right items in the right order? | A verdict that separates wrong membership from wrong ordering. |
| **Exact text match** | `exact_match` | Is the text identical to the expected text? | A `Score` of 1 for a match and 0 for a mismatch; matching can be case-insensitive. |
| **Pattern match** | `matches_regex` | Does the text contain, or fully match, a required pattern? | A `Score` of 1 for a match and 0 otherwise. |
| **Exact ID-set score** | `id_set_score` | Are the observed and expected ID sets equal? | A 1-or-0 `Score` with the set relationship and overlap measurements in evidence. |
| **Span F1 score** | `span_f1_score` | Did extraction identify the expected text ranges with enough overlap? | An F1 `Score` based on one-to-one span matches. |
| **Safety score** | `safety_score` | Did a query avoid write operations, and did a payload avoid prohibited values? | A 1-or-0 `Score` labelled `safe` or `unsafe`, with every triggered flag. |
| **JSON Schema conformance** | `schema_conformance` | Does a JSON-like value have the required fields, types, and shape? | A 1-or-0 `Score` with every schema error and its path. Requires `canary[schema]`. |

Canary also exposes lower-level measurements used by those evaluators:

| Measurement | API | Plain-language meaning |
|---|---|---|
| **Set relationship** | `set_relation` | Says whether a set is exact, empty, a subset, a superset, overlapping, or completely disjoint. |
| **Span overlap** | `span_iou` | Measures how much two text ranges overlap, from 0 (none) to 1 (identical). |
| **Span matching** | `match_spans` | Pairs expected and predicted text ranges once each when they overlap enough. |
| **Precision, recall, F1** | `precision_recall_f1` | Summarizes correct matches, extra predictions, and missed expectations. |
| **Write detection** | `contains_write_verb` | Detects data-changing SQL verbs outside comments and quoted text. |
| **Forbidden-value detection** | `contains_forbidden_value` | Walks nested data and detects an exact prohibited value. |

In plain language, **precision** asks “of everything returned, how much was
right?”, **recall** asks “of everything expected, how much was found?”, and
**F1** combines both into one number. These measurements are diagnostic; the
closed verdict remains the authoritative classification for golden
comparison.

### Verdicts and failure subtypes

Every golden comparison produces exactly one top-level verdict:

| Verdict | Plain-language meaning |
|---|---|
| `correct` | The observed answer matches the answer key. |
| `loud_fail` | The system visibly failed, refused, or never produced an executable answer. |
| `silent_wrong` | The system appeared to work but returned the wrong answer or behaved when it should not have. This is usually the most dangerous category. |

The four loud-failure subtypes are:

| Subtype | Plain-language meaning |
|---|---|
| `rejected_pre_execution` | The request was rejected before execution began. |
| `runtime_error` | Execution started but failed in a tool, database, or runtime. |
| `repair_exhausted` | The system tried to repair invalid output but ran out of allowed attempts. |
| `refused` | The system explicitly declined or could not proceed because required context or intent was unavailable. |

The ten silent-wrong subtypes are:

| Subtype | Plain-language meaning |
|---|---|
| `empty_wrong` | Nothing was returned even though the answer key expected something. |
| `subset` | Every returned item was valid, but one or more expected items were missing. |
| `superset` | All expected items were returned, plus one or more items that should not be there. |
| `overlap` | Some returned items were right and some were wrong; neither side fully contains the other. |
| `disjoint` | The returned and expected item sets have nothing in common. |
| `wrong_value` | An aggregate or scalar number was outside the allowed tolerance, or grouped values were missing or extra. |
| `wrong_order` | The right items were returned in the wrong ranking or sort order. |
| `ambiguous_shape` | The result could not be interpreted reliably, for example because a required ID or numeric column was absent. |
| `field_conformance` | The authored query omitted a required field or used a field outside the allowed catalog. |
| `unexpected_execution` | The answer key required an honest failure, but the system executed anyway. |

### Safety flags

Safety flags do not replace the verdict. They record independent concerns:

| Flag | Plain-language meaning |
|---|---|
| `decoy_leak` | The output exposed a deliberately planted decoy value that should never appear. |
| `missing_scope_predicate` | The query omitted a required workspace or tenant boundary. |
| `write_attempt` | The generated query attempted to create, change, or delete data. |
| `cap_hit` | The observed result was truncated or reached a configured output cap, so completeness is uncertain. |

### Model-based evaluation modes

Canary provides two ways to use a model as a judge. Both require the consuming
application to supply a traced `ModelPort`, and both are blocked from normal
scoring until calibrated against hand-labelled examples.

| Mode | API | Use it when | Output |
|---|---|---|---|
| **Closed-choice judge** | `ClosedChoiceJudge` | The answer must be one of a small set of labels such as pass/fail or grounded/unsupported. | A `Score` using only the declared labels and numbers, plus an explanation. |
| **Findings judge** | `FindingsJudge` | You need concrete issues for later review or separate scoring rather than one immediate number. | A list of findings with criterion, severity, location, evidence, and complaint, plus criteria that were met. |

Closed schemas mean the judge cannot invent a new label or extra output field.
Canary requests one repair for malformed output; a second invalid response is
marked unavailable rather than silently treated as a pass.

### Bundled model-judge rubric seeds

The five bundled rubrics are starting texts, not active evaluators. Each must
be calibrated for the exact model, corpus, evaluator identity, and version
before it can be trusted in production.

| Rubric | What it checks in plain language | Labels and better direction |
|---|---|---|
| `hallucination` | Whether the assistant made a claim unsupported by the conversation, retrieved content, or tool results it actually received. | `grounded=0`, `hallucinated=1`; lower is better. |
| `tool_selection` | Whether the agent chose the right tool for the user's request and available context. | `correct=1`, `incorrect=0`; higher is better. |
| `tool_invocation` | Whether the chosen tool was called with correct arguments, valid formatting, and safe content. | `correct=1`, `incorrect=0`; higher is better. |
| `tool_response_handling` | Whether the agent understood tool output, handled errors, transformed data correctly, and avoided unsafe disclosure. | `correct=1`, `incorrect=0`; higher is better. |
| `user_friction` | Whether the user's next message shows frustration caused by the assistant's preceding behavior. | `no_friction=0`, `friction=1`; lower is better. |

### Reliability and governance terms

The following are not additional evaluators. They make evaluator results
repeatable, comparable, and reviewable:

| Term | Plain-language meaning |
|---|---|
| **Calibration report** | Evidence that one exact model judge agrees often enough with hand-labelled examples. A report for another prompt, model, or version cannot be reused. |
| **Ledger** | An append-only JSONL history of case checkpoints. It enables safe resume and refuses damaged or truncated data. |
| **Revision identity** | A content hash of the case plus every rule or data revision that can change its meaning. |
| **Context fingerprint** | A content hash of the external world used for a run, such as workspace and schema context. |
| **Corpus manifest** | A fail-closed inventory proving that all expected cases and reviews are present. |
| **Freeze** | A pre-run snapshot of configuration, corpus hash, source hashes, hypotheses, time, and world identity. |
| **Stability bar** | A repeated-attempt rule requiring at least `ceil(2n/3)` successes. It helps distinguish a repeatable result from a lucky one. |
| **Ruler** | The fingerprint of the grading standard: taxonomy, criteria, rubric hashes, calibration IDs, and optional freeze identity. |
| **Run diff** | A comparison of scores from two runs measured with the same ruler. Cases are grouped as improved, regressed, mixed, unchanged, or incomparable. |

If rulers differ, Canary refuses to call score movement an improvement or
regression. That is a change in measurement, not proven change in product
behavior.

## 3. Compare an observation with a golden

### ID-set answers

Use `IdSetGolden` when order and duplicates do not matter:

```python
from datetime import date

from canary import IdSetGolden, Observation, compare

golden = IdSetGolden(
    id_column="contract_id",
    ids=("C-100", "C-200", "C-300"),
    required_fields=("status",),
    allowed_fields=("status", "region"),
    requires_scope=True,
    decoy_id_prefixes=("DECOY-",),
)

observation = Observation(
    executed=True,
    columns=("contract_id",),
    rows=(
        {"contract_id": "C-100"},
        {"contract_id": "C-200"},
    ),
    query_fields=("status",),
    scope_predicates_present=True,
    write_attempted=False,
)

verdict = compare(observation, golden, today=date(2026, 9, 1))

assert verdict.verdict == "silent_wrong"
assert verdict.subtype == "subset"
assert verdict.evidence["missing"] == ["C-300"]
assert verdict.safety_flags == ()
```

The result is a `silent_wrong` rather than a generic failure because execution
succeeded while returning a plausible but incomplete answer.

Canary's closed failure subtypes distinguish empty, subset, superset, overlap,
disjoint, wrong value, wrong order, ambiguous shape, field conformance, and
unexpected execution. Loud failures distinguish pre-execution rejection,
runtime errors, exhausted repair, and refusal.

### Aggregate answers

Use `AggregateGolden` for one scalar or a group-to-number mapping:

```python
from datetime import date

from canary import AggregateEntry, AggregateGolden, Observation, compare

golden = AggregateGolden(
    group_columns=("region",),
    entries=(
        AggregateEntry(key=("North",), value=12.0),
        AggregateEntry(key=("South",), value=8.0),
    ),
    tolerance=0.01,
)
observation = Observation(
    executed=True,
    columns=("region", "total"),
    rows=(
        {"region": "North", "total": 12},
        {"region": "South", "total": 8},
    ),
)

verdict = compare(observation, golden, today=date(2026, 9, 1))
assert verdict.is_correct
```

For an ungrouped scalar, leave `group_columns` empty and supply exactly one
`AggregateEntry` whose key is `()`.

### Ordered answers

Use `OrderedGolden` when rank matters:

```python
from datetime import date

from canary import Observation, OrderedGolden, compare

golden = OrderedGolden(
    id_column="contract_id",
    ids=("C-9", "C-3", "C-1"),
    sort_column="risk",
    descending=True,
)
observation = Observation(
    executed=True,
    columns=("contract_id", "risk"),
    rows=(
        {"contract_id": "C-9", "risk": 90},
        {"contract_id": "C-3", "risk": 70},
        {"contract_id": "C-1", "risk": 40},
    ),
)

assert compare(observation, golden, today=date(2026, 9, 1)).is_correct
```

### Safety flags are independent findings

A result can be semantically correct and still carry a safety flag. Canary
checks for decoy leakage, missing scope predicates, write attempts, and result
caps:

```python
from datetime import date

from canary import IdSetGolden, Observation, compare

golden = IdSetGolden(
    ids=("C-1",),
    requires_scope=True,
)
observation = Observation(
    executed=True,
    ids=("C-1",),
    scope_predicates_present=False,
)

verdict = compare(observation, golden, today=date(2026, 9, 1))
assert verdict.verdict == "correct"
assert verdict.safety_flags == ("missing_scope_predicate",)
```

Applications decide whether a safety flag separately blocks promotion.

## 4. Use the `Score` normal form

`Score` gives code, model, and human evaluators one immutable record shape:

```python
from canary import Score, WorldRef
from canary.hashing import content_hash

world = WorldRef(
    name="demo-workspace",
    revision="workspace-42",
    content_hash=content_hash({"workspace": "demo", "revision": 42}),
    revisions={"schema": "7", "corpus": "2026-09-01"},
)

score = Score(
    name="answer_quality",
    evaluator_id="example.answer-quality",
    evaluator_version="1",
    kind="code",
    direction="maximize",
    score=1.0,
    label="pass",
    evidence={"matchedFacts": 4, "expectedFacts": 4},
    world=world,
    dataset="contract-answers",
    case_id="case-17",
    run_id="run-2026-09-01",
)

wire_payload = score.model_dump(by_alias=True, mode="json")
assert wire_payload["evaluatorId"] == "example.answer-quality"
```

All public Pydantic records accept snake_case input and serialize with
camelCase aliases. Extra fields are rejected and records are frozen.

`score=None` means the evaluator could not score the case. It is not a zero
and must remain distinct in aggregation and persistence.

For idempotent delivery, derive a stable row identity:

```python
from canary import outcome_id

identifier = outcome_id(
    "run-2026-09-01",
    "example.answer-quality",
    "1",
)
assert identifier == "eval:run-2026-09-01:example.answer-quality:1"
```

## 5. Use pure metrics

The common metrics return `Score` or deterministic arithmetic:

```python
from canary.metrics import (
    TextSpan,
    exact_match,
    id_set_score,
    safety_score,
    span_f1_score,
)

assert exact_match("Approved", "approved", case_sensitive=False).score == 1.0
assert id_set_score({"A", "B"}, {"A", "B"}).label == "exact"
assert safety_score(query="SELECT * FROM contracts").label == "safe"

span_score = span_f1_score(
    expected=(TextSpan(0, 10, "term"),),
    predicted=(TextSpan(0, 8, "term"),),
    minimum_iou=0.5,
)
assert span_score.score == 1.0
```

With the optional `schema` extra:

```python
from canary.metrics.schema_conformance import schema_conformance

result = schema_conformance(
    {"status": "approved"},
    {
        "type": "object",
        "properties": {"status": {"const": "approved"}},
        "required": ["status"],
        "additionalProperties": False,
    },
)
assert result.label == "valid"
```

## 6. Append and resume a JSONL ledger

Canary's ledger is strict and append-only. Each case identity includes the
case content and every revision that can change its meaning:

```python
from pathlib import Path

from canary.ledger import (
    LedgerRecord,
    append,
    context_fingerprint,
    passing_checkpoints,
    revision_identity,
)

ledger_path = Path("artifacts/evaluation.jsonl")
identity = revision_identity(
    {"question": "Which contracts are active?"},
    {"goldenRevision": "goldens-7"},
    {"scorerVersion": "1"},
)
context = context_fingerprint(
    {"workspace": "demo-workspace", "schemaRevision": "42"}
)

append(
    ledger_path,
    LedgerRecord(
        case_id="case-17",
        revision_identity=identity,
        context_fingerprint=context,
        status="passed",
        payload={"verdict": "correct"},
    ),
)

assert passing_checkpoints(ledger_path)["case-17"] == identity
```

`read()` rejects blank, malformed, non-finite, and truncated lines instead of
silently losing the last record. Use `resume_filter()` with the passing
checkpoint map to rerun exactly the cases whose revision identity changed.

## 7. Freeze the inputs before a run

A freeze records configuration, corpus identity, source content, world, and
hypotheses. All ambient inputs, including time, are supplied explicitly:

```python
from datetime import datetime, timezone

from canary import WorldRef
from canary.freeze import build_freeze, preregistration_files
from canary.hashing import content_hash

world = WorldRef(
    name="benchmark-workspace",
    revision="workspace-42",
    content_hash=content_hash({"workspace": "benchmark", "revision": 42}),
)
freeze = build_freeze(
    config={"arms": ["structured", "sql"], "attempts": 3},
    corpus_hash=content_hash({"cases": ["case-1", "case-2"]}),
    sources={
        "adapter.py": "def project(value): return value\n",
        "grader.py": "GRADER_VERSION = '1'\n",
    },
    world=world,
    hypotheses=(
        {"id": "H1", "statement": "Structured output improves exactness."},
    ),
    created_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
)

artifacts = preregistration_files(freeze)
assert set(artifacts) == {"preregistration.json", "preregistration.md"}
```

`preregistration_files()` returns content; the consuming application chooses
where and how to write it. That keeps `canary.ledger` as Canary's sole writer.

## 8. Validate a reviewed corpus

A `CorpusManifest` fails closed if counts, categories, reviews, or
model-review provenance are incomplete. It supports two review profiles in one
schema.

The `annotation` profile approves one annotation per case against a hashed
golden set:

```python
from datetime import date

from canary import WorldRef
from canary.hashing import content_hash
from canary.manifest import AnnotationReview, CorpusManifest

world = WorldRef(
    name="benchmark-workspace",
    revision="workspace-42",
    content_hash=content_hash({"workspace": "benchmark", "revision": 42}),
)
review = AnnotationReview(
    case_id="case-1",
    reviewer="GPT evaluation model",
    reviewed_at=date(2026, 9, 1),
    review_status="approved",
    annotation_hash=content_hash({"case": "case-1", "status": "approved"}),
    golden_set_hash=content_hash({"ids": ["C-1"]}),
)
manifest = CorpusManifest(
    corpus_id="benchmark-goldens",
    corpus_revision="7",
    profile="annotation",
    expected_total=1,
    counts={"approved": 1},
    category_counts={"lookup": 1},
    world=world,
    llm_audit_required=True,
    reviews=(review,),
)

assert manifest.expected_total == len(manifest.reviews)
```

The `checklist` profile lets you declare the review dimensions your corpus
needs. Every review must sign off exactly the dimensions listed in
`required_checks` and then bless the case:

```python
from canary.manifest import ChecklistReview

checklist = CorpusManifest(
    corpus_id="query-filters",
    corpus_revision="3",
    profile="checklist",
    required_checks=("meaning", "query", "evidence", "ambiguity"),
    expected_total=1,
    counts={"ready": 1},
    category_counts={"scope": 1},
    world=world,
    llm_audit_required=True,
    reviews=(
        ChecklistReview(
            case_id="case-1",
            reviewer="Claude evaluation model",
            reviewed_at=date(2026, 9, 1),
            checks={
                "meaning": True,
                "query": True,
                "evidence": True,
                "ambiguity": True,
            },
            blessed=True,
        ),
    ),
)
```

A missing or extra dimension, any dimension marked `False`, or `blessed=False`
rejects the whole manifest. Reviewer strings for model-produced review records
must clearly identify a model; placeholders such as `pending` and `unknown` are
rejected.

## 9. Add a calibrated closed-choice judge

Canary never imports a provider SDK, opens a network connection, or reads an
API key. Its judge calls only the `ModelPort` supplied by the consuming
application. Adapt the application's existing async, traced JSON-generation
call:

```python
from collections.abc import Mapping, Sequence
from typing import Any

from canary.model_port import Message, ModelPort


class ApplicationModelPort(ModelPort):
    async def generate_object(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        operation: str,
    ) -> Mapping[str, Any]:
        # llm_json is the application's existing traced model call. Its client
        # reads the provider API key from the application's environment.
        return await llm_json(
            messages=[message.model_dump(mode="json") for message in messages],
            schema=dict(schema),
            trace_name=operation,
        )
```

Do not import a provider SDK into Canary or build a second untraced path in the
application. If the application has no such call yet, start from the Anthropic
or OpenAI adapter in [`examples/`](examples/); the
[integration guide](docs/integration.md#4-model-access-and-api-keys) explains
which environment variables each SDK reads and how to keep keys out of
evaluation artifacts.

Construct a judge with closed choices and a stable identity:

```python
from canary.judge import ClosedChoiceJudge
from canary.model_port import Message

port = ApplicationModelPort()
judge = ClosedChoiceJudge(
    port=port,
    evaluator_id="example.answer-grounding",
    # Fold the model into the version: a model change then invalidates the
    # calibration instead of silently reusing it.
    evaluator_version="1:model-name",
    name="answer_grounding",
    choices={"grounded": 1.0, "unsupported": 0.0},
    operation="eval.answer-grounding",
    prompt_messages=(
        Message(
            role="system",
            content=(
                "Judge the answer only against the supplied record. "
                "Return grounded or unsupported."
            ),
        ),
    ),
)
```

Before production scoring, run the exact judge against hand-labelled records.
The default activation floor requires at least five available records and 80%
aggregate agreement:

```python
from canary.calibration import CalibrationRecord, calibrate
from canary.model_port import Message

records = tuple(
    CalibrationRecord(
        record_id=f"grounding-{index}",
        mode="choice",
        messages=(Message(role="user", content=example["input"]),),
        expected_label=example["label"],
        why=example["why"],
    )
    for index, example in enumerate(hand_labelled_examples, start=1)
)

report = await calibrate(judge, records)
if not report.calibrated:
    raise RuntimeError(
        f"judge failed calibration: {report.aggregate_agreement:.1%} agreement"
    )

production_judge = judge.with_calibration(report)
score = await production_judge.evaluate(
    (Message(role="user", content=current_case),),
    case_id="case-17",
    run_id="run-2026-09-01",
    dataset="answer-grounding",
)
```

The calibration report is bound to the exact evaluator ID, evaluator version,
and rubric hash. Changing the prompt, choices, direction, identity, or model
invalidates the attachment and blocks scoring.

The judge retries one malformed or off-rubric object with a repair request. A
second invalid object produces an unscoreable `Score`; it is never silently
coerced into a passing choice.

When replacing existing threshold-based judges, run the old and calibrated
judges side by side in shadow mode, commit the calibration reports as
artifacts, and switch only after every disagreement is explained.

### Preserve findings instead of reducing them

Use `FindingsJudge` when downstream code should own the scoring arithmetic:

```python
from canary.judge import FindingsJudge
from canary.model_port import Message

findings_judge = FindingsJudge(
    port=port,
    evaluator_id="example.answer-findings",
    evaluator_version="1:model-name",
    operation="eval.answer-findings",
    criteria=("grounding", "completeness"),
    localities=("answer", "citation"),
    severities=("fatal", "weak", "nit"),
    prompt_messages=(
        Message(
            role="system",
            content="Return concrete findings and the criteria that were met.",
        ),
    ),
)
```

Calibrate it with `CalibrationRecord(mode="findings")` and
`FindingLabel` expectations, then attach the resulting report with
`with_calibration()`. A valid result retains criterion, severity, locality,
evidence, and complaint for every finding instead of collapsing them into a
number.

## 10. Start from an attributed rubric seed

Canary bundles five inert, attributed seeds:

```python
from canary.rubrics import available_rubrics, load_rubric

assert available_rubrics() == (
    "hallucination",
    "tool_invocation",
    "tool_response_handling",
    "tool_selection",
    "user_friction",
)

seed = load_rubric("hallucination")
assert seed.provenance.license == "Elastic-2.0"
```

Loading a seed does not score anything. Build and calibrate the exact seed
judge before activation:

```python
from canary.calibration import calibrate
from canary.rubrics import judge_from_rubric

authoring_judge = judge_from_rubric(
    seed,
    port=port,
    evaluator_id="example.hallucination",
    evaluator_version="1:model-name",
)
report = await calibrate(authoring_judge, labelled_seed_records)
if not report.calibrated:
    raise RuntimeError("rubric seed is not calibrated for this model and corpus")

active_judge = judge_from_rubric(
    seed,
    port=port,
    evaluator_id="example.hallucination",
    evaluator_version="1:model-name",
    calibration=report,
)
```

Keep `THIRD_PARTY_NOTICES.md` and every seed's provenance intact when the wheel
is copied.

## 11. Measure stability

Canary uses a `ceil(2n/3)` bar:

```python
from canary.stability import bar, n_sensitivity, score_bar

assert bar([True, True, False]).passed
assert not bar([True, False, False]).passed
assert score_bar([0.9, 0.8, None], threshold=0.8).passed

points = n_sensitivity(0.8, (3, 5, 10))
assert [point.required for point in points] == [2, 4, 7]
```

An unscoreable attempt cannot count as a success. Use `n_sensitivity()` to
show when a reported movement comes from sample size rather than product
behavior.

## 12. Diff runs only under the same ruler

A ruler records the standard that produced the scores. It comes from stored
artifacts, not current constants:

```python
from canary import Score
from canary.diff import diff_scores
from canary.hashing import content_hash
from canary.ruler import Ruler
from canary.verdicts import TAXONOMY_VERSION

ruler = Ruler(
    taxonomy_version=TAXONOMY_VERSION,
    judge_rubric_hashes={
        "answer_quality": content_hash({"rubric": "answer-quality/v1"}),
    },
    calibration_ids={
        "answer_quality": content_hash({"calibration": "cal-2026-09-01"}),
    },
    criteria=("answer_quality",),
)

before = (
    Score(
        name="answer_quality",
        evaluator_id="example.answer-quality",
        evaluator_version="1",
        kind="code",
        score=0.0,
        label="fail",
        case_id="case-17",
    ),
)
after = (
    Score(
        name="answer_quality",
        evaluator_id="example.answer-quality",
        evaluator_version="1",
        kind="code",
        score=1.0,
        label="pass",
        case_id="case-17",
    ),
)

movement = diff_scores(
    before,
    after,
    before_ruler=ruler,
    after_ruler=ruler,
)

assert movement.improved == ("case-17",)
assert movement.label_transition_matrix == {
    "answer_quality": {"fail -> pass": 1},
}
```

Canary refuses a diff if taxonomy, rubric hashes, calibration IDs, criteria,
freeze identity, evaluator identity, version, or direction changed. Report
that as a measurement change rather than pretending it is product movement.

A benchmark runner typically stores a freeze and a ruler beside each run's
results, projects per-case verdicts into `Score` records, and invokes
`canary.diff` only when the artifact-recorded rulers match. Anything else it
reports — qualification changes, cost, latency — remains an
application-owned report.

## 13. Re-score stored history without providers

The most valuable operational pattern is offline re-scoring:

1. Store raw observations, golden identities, context fingerprints, and run
   metadata.
2. Keep product-specific harvesting and query parsing in the application.
3. Project each stored record into `Observation`.
4. Call `compare(..., today=<recorded date>)` without a model or database.
5. Compare the new `VerdictRecord` with the historical projection.
6. Record exact parity or an explicit old-to-new subtype mapping.

Re-score several stored histories spread across configuration versions, not
adjacent runs: close samples underestimate variance. Rerunning a provider
would test a different world and cannot prove that two scoring
implementations agree.

## 14. Application boundary map

A typical integration keeps a few thin adapter modules in the application:

| Pattern | Lives in the application as |
|---|---|
| Project stored records into `Observation` | a comparator or harvester module beside the result model |
| Wrap the traced async JSON call and load calibration | a `ModelPort` adapter plus checked-in `CalibrationReport` artifacts |
| Store freeze and ruler sidecars and invoke `canary.diff` | the benchmark or run-report command |
| Project `Score` into application-owned tables | the persistence layer that already writes evaluation rows |
| Keep parity, shadow, and historical-run evidence | a checked-in adoption note that names its inputs |

Trace harvesting, qualification logic, database writes, and model tracing stay
in the application; Canary receives only neutral records and returns neutral
results.

## 15. Test the evaluator failing

Every comparator, grader, and metric needs a falsification test. A passing
example proves that the happy path is reachable; a deliberately failing
example proves that the evaluator observes the behavior it claims to grade:

```python
from datetime import date

from canary import IdSetGolden, Observation, compare


def test_id_set_grader_detects_a_missing_result() -> None:
    golden = IdSetGolden(ids=("A", "B"))
    observation = Observation(executed=True, ids=("A",))

    verdict = compare(observation, golden, today=date(2026, 9, 1))

    assert verdict.verdict == "silent_wrong"
    assert verdict.subtype == "subset"
```

For filters and branch-heavy graders, mutate every independent condition. A
fixture with one repeated value can stay green even when a filter is broken.

## 16. Common mistakes

- **Installing `canary` from a registry:** pin the Git source or a vendored
  wheel with an explicit `[tool.uv.sources]` entry.
- **Calling a provider from Canary:** implement `ModelPort` in the consuming
  application and route it through the existing traced seam.
- **Passing credentials into Canary:** keys belong to the application's model
  client. Messages, judge inputs, calibration records, ledger payloads, score
  evidence, and freeze configuration are stored and shared.
- **Scoring with an uncalibrated judge:** calibrate the exact judge identity,
  prompt, choices, and model first.
- **Treating `None` as zero:** `None` means unavailable or unscoreable.
- **Diffing with current constants:** reconstruct the ruler from each stored
  artifact and require equality.
- **Reading the clock inside scoring:** pass `today` or `created_at`
  explicitly.
- **Silently dropping a damaged ledger tail:** let `read()` fail closed and
  repair the producing workflow.
- **Mixing application behavior into Canary:** keep witness execution,
  persistence projections, prompts, and report rendering in the application.

## API map

| Need | API |
|---|---|
| Compare set answers | `IdSetGolden`, `Observation`, `compare` |
| Compare aggregates | `AggregateGolden`, `AggregateEntry`, `compare` |
| Compare rankings | `OrderedGolden`, `compare` |
| Normalize evaluator output | `Score`, `WorldRef`, `outcome_id` |
| Append and resume runs | `LedgerRecord`, `append`, `passing_checkpoints`, `resume_filter` |
| Hash structured inputs | `content_hash`, `canonical_json` |
| Run pure metrics | `canary.metrics` |
| Validate JSON Schema | `schema_conformance` with `canary[schema]` |
| Call a consumer model seam | `ModelPort`, `Message` |
| Judge closed labels | `ClosedChoiceJudge` |
| Preserve findings | `FindingsJudge` |
| Calibrate a judge | `CalibrationRecord`, `calibrate`, `CalibrationReport` |
| Load attributed seeds | `available_rubrics`, `load_rubric`, `judge_from_rubric` |
| Validate reviewed corpora | `CorpusManifest`, `ChecklistReview`, `AnnotationReview` |
| Freeze run inputs | `build_freeze`, `preregistration_files` |
| Measure repeated attempts | `bar`, `score_bar`, `n_sensitivity` |
| Record grading standards | `Ruler` |
| Compare runs | `diff_scores` |

## Next steps

- Read the [integration guide](docs/integration.md) before wiring Canary into
  an application with real model credentials.
- Read the [design notes](docs/design.md) for the invariants and the rationale
  behind them.
- Run the scripts in [`examples/`](examples/), and inspect `tests/` for
  executable falsification examples.
- Preserve [third-party notices](THIRD_PARTY_NOTICES.md) when using the bundled
  rubric seeds.
