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

Before selecting a semantic suggestion approach, the project defines
[provider-neutral semantic mapping cases](docs/evaluation-fixtures.md). These cases
separate source-event meaning from its expected ASIM projection and can be replayed
unchanged through later baselines or model providers.

## Why DeepParse

The clustering adapter uses [DeepParse v1.0.0](https://github.com/NightBaRron1412/DeepParse/tree/v1.0.0), pinned to commit `b53c29b379be5ab834ff990154297ef8fea8d98a`. Its repository describes an EASE 2026 mask-first approach: typed regex masks are synthesized once, then a deterministic Drain runtime handles each log line. The project is Apache-2.0 and includes a package, CLI, tests, CI, lockfile, and offline CPU mode.

DeepParse is still a young project. ASIM Forge therefore confines it to `clustering.py` and records the immutable revision in every build manifest. Milestone 1 uses its deterministic offline mask bundle; it does not download or invoke an LLM.

## Run the sample end to end

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required.

```powershell
uv sync

uv run asim-forge build examples/sample-logs `
  --output artifacts/demo `
  --system demo

uv run asim-forge compile `
  artifacts/demo/clusters.jsonl `
  examples/sample-review/reviews.jsonl `
  --output artifacts/demo/compiled

uv run pytest
```

Validate the checked synthetic semantic-mapping case independently:

```console
uv run asim-forge evaluation validate examples/evaluation/semantic-mapping-cases.jsonl
```

Once the matching catalogue revision is synced, compare the separated direct and
source-frame baselines against exactly the same cases:

```powershell
uv run asim-forge evaluation compare `
  examples/evaluation/semantic-mapping-cases.jsonl `
  --catalog artifacts/asim-catalog `
  --output artifacts/semantic-comparison.json
```

The [comparison design and metric rationale](docs/approach-comparison.md) explains
how the implementations remain isolated and which results are comparable to the
schema-matching and semantic-annotation literature.

The checked-in decisions approve the Authentication and NetworkSession clusters and reject the AuditEvent cluster. The compile manifest therefore reports two generated parsers and one skipped review.

## Before opening a PR

The CI checks are ordinary project commands and can be run directly from any shell:

```console
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

Enable the commit-time checks once after cloning:

```console
uv run pre-commit install
```

The hook keeps `uv.lock` synchronized, checks common repository hygiene, applies
safe Ruff fixes and formatting, and runs ty across the project. Run every hook
against the whole repository at any time with:

```console
uv run pre-commit run --all-files
```

GitHub Actions runs the same pre-commit checks for pull requests and pushes to
`main`, with pytest covering every supported Python version from 3.11 through 3.14.

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

## Sync the ASIM catalogue

Stage 2 uses the machine-readable field catalogue consumed by Microsoft's own
`ASimSchemaTester`; ASIM Forge does not maintain a copied list of ASIM fields.
Syncing resolves the requested Azure-Sentinel ref to an immutable commit before
retrieving the catalogue:

```powershell
uv run asim-forge catalog sync `
  --output artifacts/asim-catalog `
  --revision master
```

The snapshot contains the unchanged upstream `ASimTester.csv` and a
`catalog-manifest.json` recording the requested ref, resolved 40-character commit,
content SHA-256, supported schemas, and field count. Use the resolved commit from
that manifest as `--revision` to reproduce the exact catalogue without resolving a
moving branch again. `GITHUB_TOKEN` is used when present but is not required for a
public, low-volume sync.

The cached snapshot is a generated input and remains under `artifacts/`; it is not
a maintained fork of Microsoft's catalogue. The upstream CSV supplies field names,
KQL types, field classes, logical types, enumerations, aliases, and dynamic types.
Human-readable schema guidance and semantic schema-version enrichment remain a
separate upstream documentation concern because the tester CSV does not contain
those descriptions or version numbers.

## Artefacts

`asim-forge build` writes:

- `clusters.jsonl`: stable cluster IDs, typed templates, samples, slot examples, and transparent schema suggestions.
- `manifest.json`: input counts, DeepParse revision, masks, and output provenance.
- `potato/items.jsonl`: one task per cluster.
- `potato/config.yaml`: a portable Potato configuration.

`asim-forge catalog sync` writes:

- `asim-catalog.csv`: an unchanged, commit-pinned snapshot of Microsoft's tester catalogue.
- `catalog-manifest.json`: source revision, integrity hash, and catalogue coverage.

The checked `examples/evaluation/semantic-mapping-cases.jsonl` file demonstrates the
provider-neutral evaluation contract. Real evaluation cases can contain sensitive
event data and should remain under `artifacts/` or another explicitly ignored secure
location.

`asim-forge compile` writes one `*.parser-spec.json` and one `*.kql` per approved and fully mapped engineering review, plus `compile-manifest.json` recording generated, rejected, and awaiting-mapping decisions.

Operational logs, generated artefacts, and Potato annotation state are ignored by Git by default because they may contain sensitive security data.

## Current boundary

The KQL files are reviewable candidates, not production-ready Sentinel releases. Milestone 1 does not yet:

- use the synced catalogue to generate and validate mapping suggestions;
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
