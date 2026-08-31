# Grouped semantic dataset splits

Semantic mapping results are comparison evidence only when evaluation cases are
held out from retrieval memory. Random row splitting is insufficient because
near-identical templates from one product or event family can otherwise appear on
both sides.

Split metadata remains outside the provider-neutral gold JSONL. Partition choices
can change for a new experiment, but the pre-label case-to-group assignment cannot.
Promotion therefore emits a hash-verified `case-groups.jsonl` sidecar before the
split is authored.

## Manifest

```json
{
  "format_version": "1",
  "split_id": "security-pilot.source-family.v1",
  "catalogue_revision": "027a0f9338bfabcb27b784571b771c54572ebf01",
  "group_strategy": "source-family",
  "reference_partitions": ["train"],
  "entries": [
    {
      "case_id": "vendor-a.authentication.accepted",
      "group_id": "vendor-a.ssh-authentication",
      "partition": "train"
    },
    {
      "case_id": "vendor-b.authentication.failed",
      "group_id": "vendor-b.ssh-authentication",
      "partition": "test"
    }
  ]
}
```

The promotion sidecar is canonical JSONL, with one assignment per case:

```json
{"case_id":"vendor-a.authentication.accepted","group_id":"vendor-a.ssh-authentication","group_strategy":"source-family"}
```

The supported partitions are `train`, `validation`, and `test`. Every case must
appear exactly once, and every `group_id` must belong to one partition only. The
manifest and cases must use the same pinned ASIM catalogue revision.

Group IDs should identify the strongest plausible leakage unit. Prefer an entire
source/product family when sufficient data exists. A template-family split is
acceptable for experiments within one source, provided mechanically similar
templates remain in the same group. Record ambiguous cases conservatively in the
larger group.

## Commands

Validate labels and split coverage together:

```powershell
uv run asim-forge evaluation validate path/to/cases.jsonl `
  --split path/to/split.json `
  --case-groups path/to/case-groups.jsonl `
  --promotion-manifest path/to/promotion-manifest.json
```

Evaluate the held-out test partition:

```powershell
uv run asim-forge evaluation compare path/to/cases.jsonl `
  --split path/to/split.json `
  --case-groups path/to/case-groups.jsonl `
  --promotion-manifest path/to/promotion-manifest.json `
  --partition test `
  --catalog artifacts/asim-catalog `
  --output artifacts/semantic-comparison.json
```

Direct lexical and semantic frame receive only the selected evaluation cases.
Case retrieval receives only cases in `reference_partitions`; evaluation case IDs
are rejected if they overlap that reference set. The report records the split ID,
partition, reference-case count, and evaluation-case count.

Validation first checks the case and group files against the promotion manifest's
hashes, then requires exact case coverage, one global grouping strategy, and the
same `(case_id, group_id)` pairs in the split. This prevents regrouping after labels
or approach behavior are visible. A release benchmark corpus that declares a
semantic split must likewise declare `case_groups` and `promotion_manifest` paths.

The old no-split command remains available for harness smoke tests, but its report
warns that retrieval results are not comparison evidence.

## Pilot readiness

The single checked synthetic case cannot form an honest grouped split. Do not add
a nominal split merely to remove the warning. The first useful pilot should contain
traceably adjudicated cases from multiple independent source families, including
mapped, unresolved, and not-applicable outcomes. Keep the final test labels locked
while tuning approaches against training and validation partitions.
