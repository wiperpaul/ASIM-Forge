# Blinded semantic annotation workflow

The semantic annotation workflow turns approved cluster evidence into
provider-neutral evaluation cases without exposing an annotator to the answer they
are meant to produce. Queue records are unlabeled tasks, not gold data. A task
becomes gold only after a typed human decision is promoted.

This is pilot curator tooling. It provides a reproducible bridge into the first
semantic-mapping dataset while the dedicated mapping-review UI remains a follow-up.
Operational logs and reviewer records may be sensitive; keep generated queues,
submissions, and promoted artifacts below the ignored `artifacts/` directory or in
another access-controlled location.

## Prepare the queue

Start with a completed build directory, its cluster-review decisions, and a
commit-pinned ASIM catalogue snapshot. Choose the strongest plausible leakage group
before anyone labels the tasks or views approach predictions. For the pilot this is
normally the source or product family.

```powershell
uv run asim-forge evaluation queue artifacts/source-build path/to/reviews.jsonl `
  --catalog artifacts/asim-catalog `
  --group-id vendor-product.authentication `
  --group-strategy source-family `
  --output artifacts/semantic-annotation/vendor-product
```

Only clusters with an `approved` cluster-coherence decision enter the queue.
Rejected, needs-split, insufficient-evidence, and unreviewed clusters remain
excluded. Approval establishes that the examples form a usable event pattern; it
does not supply an ASIM label.

The task's `system` comes from the build manifest. When source-onboarding metadata
is available, pass `--vendor`, `--product`, `--source-table`, and `--message-field`
so annotators can cite it rather than infer it from event text.

Representative-event filenames are replaced with stable neutral references such
as `source-001`; the original paths remain only in the sealed build evidence.
Corpus paths often encode labels such as benign, anomalous, or attack. If the
build's `system` identifier does too, replace it with a neutral value using
`--system` when creating the queue.

The command writes:

| File | Purpose |
| --- | --- |
| `tasks.jsonl` | Typed, unlabeled tasks containing the frozen template, representative events, parameter slots, source metadata, catalogue revision, and group assignment. |
| `queue-manifest.json` | Queue-level provenance and counts needed to reproduce and audit selection. |
| `submission-schema.json` | The machine-readable schema that annotation and adjudication submissions must satisfy. |

Task provenance retains the clustering engine name and revision so the evidence can
be reproduced. Task records intentionally contain no cluster `schema_suggestion`
or confidence, previously approved ASIM mapping, or output from any of the three
semantic approaches. DeepParse remains the trusted clustering and initial-template
boundary; its frozen template, examples, and parameter slots are evidence, while
downstream suggestions are not annotation inputs. This blinding prevents the queue
from turning an existing suggestion into apparent human gold.

Each task records both an `input_fingerprint` over all approach-visible evidence
and a `task_revision` binding that fingerprint to the case ID, catalogue revision,
preassigned group, and frozen build/review provenance. Every decision repeats both
values. Promotion rejects stale, regrouped, or provenance-altered submissions
rather than joining them by case ID alone.

The manifest hashes the complete canonical task file and submission schema.
Promotion consumes the queue directory, verifies those hashes and the task count,
and rejects deleted, inserted, spliced, or schema-altered queues before considering
any decisions. The annotation protocol revision is also part of every task revision.

`group_id` and `group_strategy` are recorded when the queue is created. They must
describe the source relationship, not the eventual label or an approach result.
Assigning them before labeling makes the later train/validation/test split auditable
and reduces near-duplicate leakage.

The build-level queue command supports `source` and `source-family`, assigning the
same conservative group to every approved cluster in that build. Per-template or
manual grouping needs a future per-case curation surface; the CLI does not pretend
that one build-wide ID is a template-family assignment.

## Record typed decisions

Use `submission-schema.json` to validate every JSONL decision. Each record identifies
its task and whether it is an independent `annotation` or the final
`adjudication`. Annotators should work in this order:

1. Decide whether the task is `mapped`, `unresolved`, or `not_applicable`.
2. Describe source semantics from the stored evidence, including meaningful static
   template text as well as parameter slots.
3. Project those source semantics into fields from the pinned ASIM catalogue when
   the disposition is `mapped`.
4. Cite the supporting template, representative event, source metadata, catalogue,
   or review evidence.
5. Have a second qualified reviewer resolve disagreements and submit the
   adjudication record.

Incident, anomaly, injection, and source-corpus labels can guide case selection but
must not be copied into schema or field gold. Likewise, a cluster's historical
parser mapping is not an annotation answer. Record genuine ambiguity as
`unresolved`, and use `not_applicable` when the event has no defensible ASIM target.

Raw JSONL is suitable for a small, technically curated pilot and for integration
with annotation systems that consume the supplied JSON Schema. It is not the final
review experience. The planned UI should present source semantics and ASIM mappings
as typed, editable rows so ordinary reviewers do not need to edit JSON directly.

## Promote reviewed tasks

Promotion joins decisions back to the exact task evidence, validates ASIM targets
against the same pinned catalogue, and emits provider-neutral gold cases and their
external grouping metadata under the output directory:

```powershell
uv run asim-forge evaluation promote `
  artifacts/semantic-annotation/vendor-product `
  path/to/decisions.jsonl `
  --catalog artifacts/asim-catalog `
  --output artifacts/semantic-pilot/vendor-product
```

The output directory contains:

| File | Purpose |
| --- | --- |
| `cases.jsonl` | Promoted provider-neutral semantic-mapping gold cases. |
| `case-groups.jsonl` | The pre-label group ID and strategy for each promoted case, kept outside the gold format. |
| `promotion-manifest.json` | Catalogue revision, input and promotion counts, skipped-task reasons, output names, and output hashes. |

By default, only tasks with an adjudication decision are promoted. This is the
appropriate path for held-out comparison evidence. During early instruction
calibration, a curator can explicitly permit a single annotation:

```powershell
uv run asim-forge evaluation promote `
  artifacts/semantic-annotation/vendor-product `
  path/to/decisions.jsonl `
  --catalog artifacts/asim-catalog `
  --output artifacts/semantic-pilot/vendor-product-calibration `
  --allow-single-review
```

Promotion also rejects ASIM constants whose scalar type or enumerated value does
not agree with the pinned catalogue. `--allow-single-review` weakens the evidence
standard; identify those cases as
calibration material and do not use them for approach-selection claims until they
are independently reviewed and adjudicated. Promotion never converts absent or
malformed decisions into labels.

After assembling queues from multiple independent families, combine the promoted
cases and create a train/validation/test manifest using the recorded group
assignments. Validate exact case coverage and catalogue revision agreement with the
[grouped split contract](semantic-dataset-splits.md) before running approach
comparisons.

## Reproducibility boundary

Treat the build, review decisions, catalogue snapshot, queue, submissions, and
promotion outputs as an ordered evidence chain. If a cluster's template,
representative events, slots, review status, source metadata, group, or catalogue
revision changes, prepare a new queue rather than silently relabeling the old task.
Do not add semantic predictions to a task after queue creation. Predictions belong
in comparison reports produced from locked gold cases.
