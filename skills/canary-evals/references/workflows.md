# Canary implementation workflows

These recipes are application-neutral. Replace IDs and field names with the
target repository's existing contracts.

## Install Canary with a pinned source

Pin the Git repository at a release tag (or a full commit SHA) and declare the
dependency and its source separately:

```bash
uv add "git+https://github.com/skrivov/canary" --tag v0.4.0
```

```toml
[project]
dependencies = ["canary"]

[tool.uv.sources]
canary = { git = "https://github.com/skrivov/canary", tag = "v0.4.0" }
```

For hermetic builds, copy the release wheel into the application's `vendor/`
directory and use `canary = { path = "vendor/canary-0.4.0-py3-none-any.whl" }`
as the source instead. Use `canary[schema]` in `dependencies` only when JSON
Schema conformance is needed; the source entry is unchanged. Run `uv lock` and
inspect the result. Never resolve the bare distribution from a registry.

Verify a candidate wheel with the helper bundled in this skill, taking the
digest from the release notes:

```bash
python scripts/inspect_canary.py \
  --wheel /path/to/vendor/canary-0.4.0-py3-none-any.whl \
  --require-version 0.4.0 \
  --expected-sha256 <sha256-from-release-notes>
```

Run it without `--wheel` through the target environment's Python to inspect the
installed distribution.

## Compare stored observations

```python
from datetime import date

from canary import IdSetGolden, Observation, compare

golden = IdSetGolden(
    id_column="item_id",
    ids=("A", "B", "C"),
    required_fields=("status",),
    allowed_fields=("status", "region"),
    requires_scope=True,
)
observation = Observation(
    executed=True,
    columns=("item_id",),
    rows=({"item_id": "A"}, {"item_id": "B"}),
    query_fields=("status",),
    scope_predicates_present=True,
)

verdict = compare(observation, golden, today=date(2026, 9, 1))
assert verdict.verdict == "silent_wrong"
assert verdict.subtype == "subset"
assert verdict.evidence["missing"] == ["C"]
```

Projection into `Observation` belongs beside the application's trace or result
model. The witness that produced the rows remains application-owned.

## Emit a normal-form score

```python
from canary import Score, WorldRef, outcome_id
from canary.hashing import content_hash

world = WorldRef(
    name="demo-world",
    revision="42",
    content_hash=content_hash({"world": "demo", "revision": 42}),
)
score = Score(
    name="answer_quality",
    evaluator_id="app.answer-quality",
    evaluator_version="1",
    kind="code",
    direction="maximize",
    score=1.0,
    label="pass",
    evidence={"matched": 4, "expected": 4},
    world=world,
    dataset="answers",
    case_id="case-17",
    run_id="run-42",
)

wire = score.model_dump(by_alias=True, mode="json")
row_id = outcome_id("run-42", "app.answer-quality", "1")
```

Do not infer missing identifiers while persisting. Make the run, case, evaluator,
and world identities explicit at the projection boundary.

## Append and resume a ledger

```python
from pathlib import Path

from canary.ledger import (
    LedgerRecord,
    append,
    context_fingerprint,
    passing_checkpoints,
    revision_identity,
)

path = Path("artifacts/evaluation.jsonl")
identity = revision_identity(
    {"case": "case-17", "input": "..."},
    {"goldenRevision": "7"},
    {"evaluatorVersion": "1"},
)
context = context_fingerprint({"worldRevision": "42", "schema": "9"})

append(
    path,
    LedgerRecord(
        case_id="case-17",
        revision_identity=identity,
        context_fingerprint=context,
        status="passed",
        payload={"verdict": "correct"},
    ),
)
assert passing_checkpoints(path)["case-17"] == identity
```

Include every input capable of changing meaning in `revision_identity()`. Use a
separate `context_fingerprint()` for the external world. Never edit or truncate a
ledger to repair it; fail visibly and preserve the damaged artifact for diagnosis.

## Calibrate and activate a closed-choice judge

Adapt the application's existing traced JSON call. Its client reads the
provider API key from the application's environment; the adapter never passes
a key to Canary:

```python
from collections.abc import Mapping, Sequence
from typing import Any

from canary.model_port import Message, ModelPort


class ApplicationPort(ModelPort):
    async def generate_object(
        self,
        *,
        schema: Mapping[str, Any],
        messages: Sequence[Message],
        operation: str,
    ) -> Mapping[str, Any]:
        return await existing_traced_llm_json(
            schema=dict(schema),
            messages=[message.model_dump(mode="json") for message in messages],
            operation=operation,
        )
```

Author the judge and hand-labelled records:

```python
from canary.calibration import CalibrationRecord, calibrate
from canary.judge import ClosedChoiceJudge
from canary.model_port import Message

judge = ClosedChoiceJudge(
    port=ApplicationPort(),
    evaluator_id="app.grounding",
    evaluator_version="1:model-config",
    operation="eval.grounding",
    name="grounding",
    choices={"grounded": 1.0, "unsupported": 0.0},
    prompt_messages=(
        Message(
            role="system",
            content="Judge only against the supplied record.",
        ),
    ),
)

records = tuple(
    CalibrationRecord(
        record_id=example["id"],
        mode="choice",
        messages=(Message(role="user", content=example["input"]),),
        expected_label=example["label"],
        why=example["why"],
    )
    for example in hand_labelled_examples
)
report = await calibrate(judge, records)
if not report.calibrated:
    raise RuntimeError("judge did not pass calibration")

active_judge = judge.with_calibration(report)
score = await active_judge.evaluate(
    (Message(role="user", content=current_case),),
    case_id="case-17",
    run_id="run-42",
    dataset="grounding",
)
```

Persist the calibration report next to the corpus revision it evaluated. A report
for another prompt, model configuration, or choice set must not activate the
judge.

## Diff only under one recorded ruler

```python
from canary import TAXONOMY_VERSION
from canary.diff import diff_scores
from canary.ruler import Ruler

ruler = Ruler(
    taxonomy_version=TAXONOMY_VERSION,
    criteria=("answer_quality",),
)
delta = diff_scores(
    before_scores,
    after_scores,
    before_ruler=ruler,
    after_ruler=ruler,
)
```

For model judges, include every judge rubric hash and calibration ID in the ruler.
Include the freeze ID when run comparability depends on the same frozen world. If
`assert_same_ruler()` reports a mismatch, describe the grading-standard change
instead of publishing an improvement or regression claim.

## Migration evidence checklist

Before replacing an existing evaluator, capture:

- old and new evaluator IDs and versions;
- exact stored run and ledger or trace paths;
- dataset and corpus revision;
- `WorldRef` or equivalent data/schema revision;
- Canary source: Git tag and commit, or wheel filename and SHA-256;
- fields included and excluded from parity;
- exact old/new output identity, or an explicit taxonomy mapping;
- a deliberately failing fixture for every grader branch;
- focused and full-gate test commands and outputs.

Re-score stored facts. Provider, database, or witness reruns test a different
world and cannot prove that two scoring implementations are identical.
