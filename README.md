# ASIM Forge

ASIM Forge is a human-supervised walking skeleton for turning static security logs into reviewed Microsoft Advanced Security Information Model (ASIM) parser candidates.

Milestone 1 implements the cluster-review boundary and a deterministic compiler walking skeleton:

```text
data/logs/*.{log,txt}
  -> DeepParse mask synthesis and Drain clustering
  -> stable typed cluster records
  -> Stage 1 Potato cluster review
  -> accepted cluster awaiting ASIM mapping
  -> later engineering review / typed parser specification
  -> deterministic KQL candidate
```

Stage 1 decides only whether the examples form a coherent event pattern. Vendor/product metadata belongs to source onboarding, and ASIM schema and field mapping belong to a later engineering review. The compiler accepts the complete canonical review contract to exercise the downstream gate; a Stage 1 approval is reported as `awaiting_mapping` and never produces KQL by itself.

The stages are separate approval checkpoints, not necessarily separate human sessions. [The roadmap](ROADMAP.md) plans a progressive review that prepares an ASIM suggestion in advance and reveals it immediately after cluster approval, so an eligible reviewer can continue while the examples are still fresh or defer it to an ASIM specialist.

## Why DeepParse

The clustering adapter uses [DeepParse v1.0.0](https://github.com/NightBaRron1412/DeepParse/tree/v1.0.0), pinned to commit `b53c29b379be5ab834ff990154297ef8fea8d98a`. Its repository describes an EASE 2026 mask-first approach: typed regex masks are synthesized once, then a deterministic Drain runtime handles each log line. The project is Apache-2.0 and includes a package, CLI, tests, CI, lockfile, and offline CPU mode.

DeepParse is still a young project. ASIM Forge therefore confines it to `clustering.py` and records the immutable revision in every build manifest. Milestone 1 uses its deterministic offline mask bundle; it does not download or invoke an LLM.

## Run the sample end to end

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required.

```powershell
uv sync --extra dev

uv run asim-forge build examples/sample-logs `
  --output artifacts/demo `
  --system demo

uv run asim-forge compile `
  artifacts/demo/clusters.jsonl `
  examples/sample-review/reviews.jsonl `
  --output artifacts/demo/compiled

uv run pytest
```

The checked-in decisions approve the Authentication and NetworkSession clusters and reject the AuditEvent cluster. The compile manifest therefore reports two generated parsers and one skipped review.

## Review with Potato

Build creates a self-contained Potato task under the selected output directory:

```powershell
uv sync --extra review
uv run potato start artifacts/demo/potato/config.yaml -p 8000
```

Potato persists Stage 1 review state under `potato/annotation_output/<reviewer>/user_state.json`. Passing that state to the compiler is safe, but accepted clusters are reported as `awaiting_mapping` until the later engineering review supplies parser metadata and ASIM mappings:

```powershell
uv run asim-forge compile `
  artifacts/demo/clusters.jsonl `
  artifacts/demo/potato/annotation_output/<reviewer>/user_state.json `
  --output artifacts/demo/compiled
```

Potato presents the template, representative events, and extracted slots as separate structured views. The reviewer approves, splits, rejects, or requests more evidence and can add notes. It does not ask the cluster reviewer to identify the vendor/product, choose an ASIM schema, edit JSON, or map fields.

Canonical engineering-review JSONL is accepted for reproducible compiler tests, source control, and integration with the later mapping UI. See `examples/sample-review/reviews.jsonl` for the complete contract.

## Artefacts

`asim-forge build` writes:

- `clusters.jsonl`: stable cluster IDs, typed templates, samples, slot examples, and transparent schema suggestions.
- `manifest.json`: input counts, DeepParse revision, masks, and output provenance.
- `potato/items.jsonl`: one task per cluster.
- `potato/config.yaml`: a portable Potato configuration.

`asim-forge compile` writes one `*.parser-spec.json` and one `*.kql` per approved and fully mapped engineering review, plus `compile-manifest.json` recording generated, rejected, and awaiting-mapping decisions.

Operational logs, generated artefacts, and Potato annotation state are ignored by Git by default because they may contain sensitive security data.

## Current boundary

The KQL files are reviewable candidates, not production-ready Sentinel releases. Milestone 1 does not yet:

- validate mappings against a pinned ASIM catalogue;
- provide the later source-metadata and ASIM-mapping review interface;
- run ASIM schema or data testers;
- execute KQL against a Sentinel workspace;
- generate schema-specific mandatory fields or event-result normalization;
- resolve agreement between multiple reviewers;
- deploy parsers automatically;
- use a database, cloud service, Kubernetes, or external LLM.

Those validation and release gates belong to later milestones. Keeping them out of this slice makes the approval boundary and generated provenance easy to inspect.

## Licence

ASIM Forge is GPL-3.0-or-later. DeepParse remains Apache-2.0 and is not vendored. Potato is an optional, separately installed GPL dependency. See `LICENSE` and `THIRD_PARTY_NOTICES`.
