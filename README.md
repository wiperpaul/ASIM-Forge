# ASIM Forge

ASIM Forge is a human-supervised walking skeleton for turning static security logs into reviewed Microsoft Advanced Security Information Model (ASIM) parser candidates.

Milestone 1 implements this complete path:

```text
data/logs/*.{log,txt}
  -> DeepParse mask synthesis and Drain clustering
  -> stable typed cluster records
  -> Potato review task
  -> explicit human decision
  -> typed parser specification
  -> deterministic KQL candidate
```

The human decision is a hard compilation gate. A baseline schema suggestion never produces KQL by itself. Rejected, split, incomplete, duplicated, unknown-cluster, and invalid-slot reviews are refused or skipped with an explicit result.

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

Potato persists live review state under `potato/annotation_output/<reviewer>/user_state.json`. ASIM Forge can compile that state directly:

```powershell
uv run asim-forge compile `
  artifacts/demo/clusters.jsonl `
  artifacts/demo/potato/annotation_output/<reviewer>/user_state.json `
  --output artifacts/demo/compiled
```

For an approved cluster, `parser_spec` is a JSON object containing `parser_name`, `vendor`, `product`, optional source table/field overrides, and a `field_mappings` list. Each mapping targets a displayed occurrence-specific slot such as `p1`; labels such as `IPV4` are descriptive and are not used as ambiguous mapping keys.

Canonical review JSONL is also accepted for reproducible tests, source control, and integration with a different review UI. See `examples/sample-review/reviews.jsonl` for the contract.

## Artefacts

`asim-forge build` writes:

- `clusters.jsonl`: stable cluster IDs, typed templates, samples, slot examples, and transparent schema suggestions.
- `manifest.json`: input counts, DeepParse revision, masks, and output provenance.
- `potato/items.jsonl`: one task per cluster.
- `potato/config.yaml`: a portable Potato configuration.

`asim-forge compile` writes one `*.parser-spec.json` and one `*.kql` per approved review, plus `compile-manifest.json` recording generated and skipped decisions.

Operational logs, generated artefacts, and Potato annotation state are ignored by Git by default because they may contain sensitive security data.

## Current boundary

The KQL files are reviewable candidates, not production-ready Sentinel releases. Milestone 1 does not yet:

- validate mappings against a pinned ASIM catalogue;
- run ASIM schema or data testers;
- execute KQL against a Sentinel workspace;
- generate schema-specific mandatory fields or event-result normalization;
- resolve agreement between multiple reviewers;
- deploy parsers automatically;
- use a database, cloud service, Kubernetes, or external LLM.

Those validation and release gates belong to later milestones. Keeping them out of this slice makes the approval boundary and generated provenance easy to inspect.

## Licence

ASIM Forge is GPL-3.0-or-later. DeepParse remains Apache-2.0 and is not vendored. Potato is an optional, separately installed GPL dependency. See `LICENSE` and `THIRD_PARTY_NOTICES`.
