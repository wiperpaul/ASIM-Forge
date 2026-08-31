# Provider-neutral semantic mapping cases

The semantic mapping evaluation contract is a versioned JSONL format for replaying
the same human-labelled cases through different deterministic, retrieval, local-model,
or API-backed approaches. It deliberately contains no provider name, prompt, candidate
rank, score, or confidence.

Each line is one self-contained `SemanticMappingCase` with four parts:

| Part | Purpose |
| --- | --- |
| `input` | The template, representative events, parameter slots, and source metadata available to every approach. It excludes the existing keyword schema suggestion. |
| `expected.source_semantics` | Source-oriented roles for slots, meaningful template constants, or derived concepts. The role vocabulary is intentionally not closed in format version 1. |
| `expected.asim_fields` | The expected projection from a source-semantic ID to an ASIM field, including a normalized constant when the event meaning comes from static template text. |
| `provenance` | Whether labels came from human review, adjudication, synthetic data, or an import, plus optional non-provider decision and annotator references. |

`catalogue_revision` is the immutable Azure-Sentinel commit against which the ASIM
targets were labelled. A later result format can join predictions to `case_id` and the
catalogue revision without modifying the gold case.

## Outcomes

The expected `disposition` is explicit:

- `mapped` requires a schema, at least one source-semantic label, and at least one
  ASIM field projection.
- `unresolved` retains partial labels when useful and requires one or more reasons.
- `not_applicable` records a deliberate no-ASIM outcome and cannot contain ASIM
  targets.

This permits abstention to be measured rather than treating every missing answer as
an error. A source-semantic label must cite evidence and identify its origin as a
parameter `slot`, a `template_constant`, or a `derived` concept. Template constants
must occur in the stored template, slot locators must resolve to stored parameter
slots, and every ASIM projection must resolve to a source-semantic ID.

## Checked example and validation

The synthetic [network-session case](../examples/evaluation/semantic-mapping-cases.jsonl)
captures the three parameter slots and the static phrase `connection allowed`. The
latter can carry an expected normalized `EventResult` even though it is not a parser
slot.

Validate a fixture before committing or evaluating it:

```console
uv run asim-forge evaluation validate examples/evaluation/semantic-mapping-cases.jsonl
```

The Python API provides `load_semantic_mapping_cases` and
`write_semantic_mapping_cases`; the writer produces deterministic, key-sorted JSONL.
Pydantic rejects extra fields so provider output cannot accidentally become part of
the gold contract.

Operational fixtures may contain sensitive representative events. Keep them outside
source control under `artifacts/` or another explicitly ignored secure location. Only
synthetic or suitably sanitized cases should be checked in.

## Deliberate exclusions from the gold format

Format version 1 does not define:

- a provider request or prediction contract;
- candidate scores, thresholds, or confidence calibration;
- evaluation metrics or train/test splits;
- a controlled source-role ontology;
- parser expressions and transform implementation;
- direct or automatic conversion from Stage 1 decisions into gold labels.

The separate [approach comparison contract](approach-comparison.md) now defines
provider predictions and the initial evaluation metrics. Keeping them out of the
gold format is what makes the dataset reusable across approaches.

Train/validation/test membership is also deliberately external to the gold case.
Use the [grouped split contract](semantic-dataset-splits.md) to prevent source or
template-family leakage while preserving reusable labels.

The [blinded annotation workflow](semantic-annotation-workflow.md) can turn an
approved Stage 1 cluster into an unlabeled task. Only a separate, completed typed
annotation, and by default its adjudication, is promoted into this gold format;
existing suggestions and engineering mappings are never copied as expected labels.
