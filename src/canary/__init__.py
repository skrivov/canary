"""canary — a provider-neutral evaluation kernel.

The library holds evaluation *method*: a closed verdict taxonomy, score
records, re-scorable run ledgers, calibrated closed-choice judges, corpus
manifests with review provenance, world/source freezes, and run diffing. The
application that uses it keeps its *instruments*: execution, corpora, judge
prompts, model access, trace storage, and UI.

Two invariants hold everywhere in this package (see docs/design.md):

* No provider SDK, network client, or environment lookup is used here, ever.
  Model access enters through the ``ModelPort`` protocol and is supplied by
  the application, so its own traced, schema-enforced client — and the API
  keys that client reads — stay the only way a model is called.
* Verdicts are derived. Every scoring function is pure — no I/O, no clock,
  no randomness — so any stored run can be re-scored for free when the
  taxonomy improves.
"""

from .compare import (
    AggregateEntry,
    AggregateGolden,
    IdSetGolden,
    Observation,
    OrderedGolden,
    compare,
)
from .score import Score, WorldRef, outcome_id
from .verdicts import TAXONOMY_VERSION, VerdictRecord

__all__ = [
    "TAXONOMY_VERSION",
    "AggregateEntry",
    "AggregateGolden",
    "IdSetGolden",
    "Observation",
    "OrderedGolden",
    "Score",
    "VerdictRecord",
    "WorldRef",
    "compare",
    "outcome_id",
]
