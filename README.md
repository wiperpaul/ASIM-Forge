# LogLathe

LogLathe is an early-stage, human-in-the-loop toolkit for turning raw security
logs into auditable Microsoft Advanced Security Information Model (ASIM) parser
candidates. It also provides a controlled evaluation harness for comparing ways to
suggest ASIM schemas and field mappings before those suggestions reach a reviewer.

It is designed for security and detection engineers working with large volumes of
unstructured telemetry. In particular, it supports organisations trying to enforce
consistent application and infrastructure security-logging requirements across
large environments where strong logging standards were not established from the
outset.

The current implementation targets ASIM, but the longer-term direction is broader:
an open, modular workbench in which normalization targets such as OCSF, alternative
mapping techniques, and external integrations can be added behind explicit
contracts. The aim is to make approaches replaceable and outputs interoperable,
rather than requiring the entire workflow to live inside one proprietary suite.

The project is deliberately conservative: clustering, semantic suggestions, human
decisions, parser generation, validation, and release are separate boundaries. A
generated KQL file is a reviewable candidate, not a production-ready Microsoft
Sentinel parser.

## What exists today

LogLathe currently has two connected areas of work.

### Parser engineering walking skeleton

```text
line-oriented logs
      |
      v
DeepParse mask synthesis + Drain clustering
      |
      v
typed clusters + representative events + parameter slots
      +----------------------------+
      |                            |
      v                            v
independent cluster review    source-concept schema ranking
      |                       (rank, evidence, confidence,
      |                        selection or abstention)
      |
      +-- rejected / split / insufficient evidence --> no parser
      +-- approved but not mapped ------------------> awaiting_mapping
      +-- approved with complete mapping ----------> parser spec + KQL candidate
```

The cluster reviewer decides only whether examples form a coherent event pattern.
Vendor and product metadata, ASIM schema selection, and field mapping belong to a
separate engineering decision. The compiler enforces that boundary: Stage 1 approval
alone never produces KQL. Build orchestration prepares schema rankings separately;
the Potato cluster-review bundle contains no schema suggestion.

### Semantic-mapping evaluation

```text
provider-neutral labelled cases + commit-pinned ASIM catalogue
                              |
                              v
                         MappingRequest
                              |
              +---------------+----------------+
              |               |                |
       direct-lexical   semantic-frame   case-retrieval
              |               |                |
              +---------------+----------------+
                              |
                              v
                SemanticMappingPrediction
                              |
                              v
                shared, provider-neutral metrics
```

All approaches receive the same input and return the same typed prediction contract.
Expected labels never enter `MappingRequest`, and predictions remain separate from
the gold cases. This makes deterministic baselines, retrieval, local models, and
future API-backed approaches comparable without changing the fixtures or metrics.

| Capability | Status |
| --- | --- |
| Ingest `.log` and `.txt` files | Implemented |
| Deterministic mask-first clustering | Implemented |
| Target-neutral source-concept normalization | Implemented |
| Independent schema-ranking contracts and abstention | Implemented |
| Portable Potato cluster-review task | Implemented |
| Typed review and parser-spec contracts | Implemented |
| Deterministic parser-spec and KQL generation | Implemented |
| Commit-pinned Microsoft ASIM field catalogue | Implemented |
| Provider-neutral semantic-mapping fixtures | Implemented |
| Blinded semantic annotation queue and gold promotion | Implemented |
| Shared ranking, F1, exact-match, coverage, and edit metrics | Implemented |
| Direct lexical, semantic-frame, and case-retrieval baselines | Implemented |
| Integrated ASIM mapping review UI | Planned |
| Schema/data validation and Sentinel execution | Planned |
| Additional normalization targets, such as OCSF | Contributions welcome |
| Corpus benchmark reports and evaluation prereleases | Implemented |
| Automatic production deployment | Not implemented |

LogLathe is pre-alpha. The contracts and evaluation boundaries are intentional,
but the end-to-end reviewer experience is still under construction.

## Quick start

LogLathe supports Python 3.11 through 3.14 and uses
[uv](https://docs.astral.sh/uv/) for dependency management.

```powershell
git clone https://github.com/wiperpaul/LogLathe.git
Set-Location LogLathe
uv sync --locked
```

Build clusters and a review bundle from the checked sample logs:

```powershell
uv run asim-forge build examples/sample-logs `
  --output artifacts/demo `
  --system demo
```

Compile the checked sample engineering decisions:

```powershell
uv run asim-forge compile `
  artifacts/demo/clusters.jsonl `
  examples/sample-review/reviews.jsonl `
  --output artifacts/demo/compiled
```

The sample contains nine events in three clusters. Its decisions produce two parser
candidates and skip one rejected cluster.

Run the test suite:

```console
uv run pytest
```

## Review clusters with Potato

`asim-forge build` creates a self-contained Potato task alongside the cluster data.
Install the optional review dependency and start the task:

```powershell
uv sync --extra review
uv run potato start artifacts/demo/potato/config.yaml -p 8000
```

The task presents each template, its representative events, and extracted parameter
slots as structured views. A reviewer can approve the cluster, request a split,
reject it, ask for more evidence, and add notes. The task does not ask that reviewer
to edit JSON or choose ASIM fields.

Potato writes reviewer state below
`potato/annotation_output/<reviewer>/user_state.json`. The compiler can read that
state directly:

```powershell
uv run asim-forge compile `
  artifacts/demo/clusters.jsonl `
  artifacts/demo/potato/annotation_output/<reviewer>/user_state.json `
  --output artifacts/demo/compiled
```

An approved Potato decision is expected to report `awaiting_mapping`; it does not
contain the later source metadata and ASIM field decisions required for compilation.
Canonical engineering-review JSONL remains available for reproducible tests and
future UI integration; see
[`examples/sample-review/reviews.jsonl`](examples/sample-review/reviews.jsonl).

## Work with the ASIM catalogue

LogLathe consumes the machine-readable field catalogue used by Microsoft's
`ASimSchemaTester`. It does not maintain a hand-copied list of ASIM fields.

```powershell
uv run asim-forge catalog sync `
  --output artifacts/asim-catalog `
  --revision master
```

The command resolves a branch or tag to an immutable Azure-Sentinel commit, stores
the upstream CSV unchanged, and writes a manifest containing the resolved revision,
content SHA-256, schema coverage, and field count. Use that resolved 40-character
commit for later runs when exact reproduction matters. `GITHUB_TOKEN` is used when
available but is not required for occasional public catalogue access.

Human-readable schema descriptions and semantic schema versions are not present in
the tester CSV. They remain a separate, future enrichment concern rather than being
embedded as locally maintained catalogue data.

## Build the semantic pilot safely

Approved clusters can now enter a blinded annotation queue without carrying their
provisional schema suggestion, historic parser mapping, or any approach prediction:

```powershell
uv run asim-forge evaluation queue artifacts/demo path/to/cluster-reviews.jsonl `
  --catalog artifacts/asim-catalog `
  --group-id demo.authentication `
  --group-strategy source-family `
  --output artifacts/semantic-annotation/demo
```

The queue fixes the source-family group and fingerprints the exact template,
representative events, slots, metadata, and catalogue boundary before labels are
collected. It neutralizes source filenames and hashes the complete selected task
set. Promotion consumes that verified queue, validates typed decisions against the
frozen evidence and pinned ASIM catalogue, and requires an explicit adjudication
by default; `--allow-single-review` is reserved for provisional calibration cases.

This is curator tooling for assembling the first 30-50 multi-source cases, while
the structured semantic-review UI remains planned. See the
[blinded annotation workflow](docs/semantic-annotation-workflow.md) and
[pilot acquisition plan](evaluation/semantic-pilot/README.md).

## Compare semantic-mapping approaches

The checked fixture is synthetic and exists to exercise the contracts and comparison
harness. First validate it:

```console
uv run asim-forge evaluation validate examples/evaluation/semantic-mapping-cases.jsonl
```

The fixture is labelled against a specific Azure-Sentinel commit. Sync that exact
catalogue revision, then run all registered approaches against the same case:

```powershell
uv run asim-forge catalog sync `
  --output artifacts/asim-catalog `
  --revision 027a0f9338bfabcb27b784571b771c54572ebf01

uv run asim-forge evaluation compare `
  examples/evaluation/semantic-mapping-cases.jsonl `
  --catalog artifacts/asim-catalog `
  --output artifacts/semantic-comparison.json
```

Repeat `--approach` to run only selected approaches. Without it, the comparison runs
all three:

| Approach | Role in the evaluation |
| --- | --- |
| `direct-lexical` | Cheap benchmark that ranks catalogue fields directly from local slot context. |
| `semantic-frame` | Two-stage benchmark that names source semantics before projecting them into ASIM. |
| `case-retrieval` | Transfers schemas, source roles, and mappings from similar labelled cases while excluding the current case ID. |

Schema ranking is now an independent phase with its own request, prediction,
evidence, confidence, and abstention contracts. Its initial `source-concept`
approach estimates only the likely schema; it does not guess fields. The semantic
mapping approaches compose that phase with later field-specific behavior.

All phases share the versioned, target-neutral tokenizer in `source_semantics/`.
Field mapping separately retains the nearest CEF/JSON-style key for a parameter
slot in `semantic_mapping/source_context.py`. Neither layer reads expected labels.
See the [schema-ranking boundary](docs/schema-ranking.md).

For comparison evidence, provide an external grouped split. Retrieval then receives
only the declared training/reference cases while every approach is scored on the
same held-out partition:

```powershell
uv run asim-forge evaluation compare path/to/cases.jsonl `
  --split path/to/split.json `
  --case-groups path/to/case-groups.jsonl `
  --promotion-manifest path/to/promotion-manifest.json `
  --partition test `
  --catalog artifacts/asim-catalog `
  --output artifacts/semantic-comparison.json
```

The report includes every prediction plus aggregate schema ranking, source-role and
field F1, field ranking, exact-match, coverage, disposition, and edit-count metrics.
See the [approach comparison](docs/approach-comparison.md),
[metric definitions](docs/evaluation-metrics.md), and
[fixture contract](docs/evaluation-fixtures.md) for the design details. The
[grouped split contract](docs/semantic-dataset-splits.md) defines the leakage
boundary required for retrieval comparisons.

> [!WARNING]
> The repository currently contains one synthetic semantic-mapping case. Its scores
> are smoke-test results, not evidence that one approach is better than another.
> Case retrieval correctly abstains when leave-one-out evaluation leaves no eligible
> reference case. A multi-source, adjudicated dataset with grouped source or template
> family splits is required before drawing quality conclusions.

## Run the corpus benchmark

The checked corpus registry combines three small LogHub datasets, security-paper
artifacts, commit-pinned Microsoft ASIM parser-development samples, and the
adjudicated ASIM fixture. The report keeps their objectives separate: LogHub
template labels score clustering, paper artifacts provide format/stress
diagnostics, Microsoft sample placement provides weak file-level schema hints, and
only ASIM-labelled cases score adjudicated schema and field correctness.

```powershell
uv run asim-forge evaluation benchmark evaluation/corpora `
  --catalog artifacts/asim-catalog `
  --output artifacts/evaluation `
  --revision (git rev-parse HEAD)
```

Remote inputs are fetched from pinned sources, checksum-verified, and cached under
ignored artifacts rather than committed. The command writes machine-readable JSON
and a release-ready Markdown table. CI publishes the same files as an artifact on
pull requests and as an evaluation prerelease after successful relevant changes on
`main`; tagged releases receive the reports too. See the
[corpus and release design](docs/benchmark-releases.md) for corpus provenance,
metric boundaries, local reproduction, and baseline-delta rules.

## Generated artefacts

`asim-forge build` writes:

- `clusters.jsonl` — stable cluster IDs, templates, representative events, parameter
  slots, and a compatibility copy of the schema suggestion.
- `schema-rankings.jsonl` — independent schema-ranking predictions with approach
  identity, evidence, confidence, candidates, and explicit abstention.
- `manifest.json` — inputs, event and cluster counts, masks, DeepParse revision, and
  output provenance.
- `potato/items.jsonl` and `potato/config.yaml` — a portable Stage 1 review task.

`asim-forge catalog sync` writes:

- `asim-catalog.csv` — an unchanged, commit-pinned upstream catalogue snapshot.
- `catalog-manifest.json` — the source revision, integrity hash, and catalogue
  coverage.

`asim-forge evaluation compare` can write:

- A JSON report containing approach identities, warnings, individual predictions,
  and shared aggregate metrics.

`asim-forge evaluation benchmark` writes:

- `benchmark-report.json` — revisioned corpus results and comparable baseline deltas.
- `benchmark-report.md` — objective-separated tables suitable for release notes.

`asim-forge compile` writes:

- One `*.parser-spec.json` and `*.kql` pair per approved, fully mapped review.
- `compile-manifest.json` — generated outputs plus rejected, deferred, and
  `awaiting_mapping` counts.

Generated artefacts, raw operational logs, and Potato annotation state are ignored
by Git because they may contain sensitive security data. Only synthetic or suitably
sanitized evaluation cases should be committed.

## Design boundaries

- **Cluster judgement is independent.** DeepParse produces schema-free parsed
  clusters, and the Potato task contains no schema suggestion that could anchor the
  initial coherence decision.
- **Suggestions are not approvals.** Generated rankings, confidence, evidence, and
  warnings remain distinct from human decisions.
- **Provenance is part of the output.** DeepParse, catalogue, approach, case, and
  decision revisions are recorded at their respective boundaries.
- **Source normalization is target neutral.** Original events remain unchanged in
  evidence while deterministic concepts are shared across ranking and mapping.
- **Schema ranking is not field mapping.** Schema candidates and abstention are
  evaluated before source roles or target fields are considered.
- **Compilation is deterministic.** The same complete cluster and review contracts
  produce the same parser specification and KQL candidate.
- **Deployment is out of scope.** LogLathe neither connects to a Sentinel workspace
  nor promotes generated KQL automatically.

The clustering adapter uses
[DeepParse v1.0.0](https://github.com/NightBaRron1412/DeepParse/tree/v1.0.0), pinned
to commit `b53c29b379be5ab834ff990154297ef8fea8d98a`. LogLathe confines that
dependency to the clustering boundary and uses its deterministic offline mask
bundle; the current build workflow does not download or invoke an LLM.

After clustering, build orchestration invokes the independent `source-concept`
schema ranker. It uses normalized source concepts and abstains when schemas have
equal evidence. Structured key-to-slot context remains on the later mapping side;
neither boundary replaces a future format-aware CEF, JSON, or multiline adapter.

## What comes next

The next product milestone is a continuous assisted review: prepare a semantic
suggestion before review, preserve cluster approval as an independent checkpoint,
then let an eligible reviewer continue into editable ASIM schema and field mappings
without rereading the event evidence or editing raw JSON.

Before choosing a production suggestion provider, the evaluation work needs:

1. adjudicated cases from multiple products and event families;
2. explicit unresolved and not-applicable examples;
3. grouped train/test splits that prevent near-duplicate template leakage; and
4. per-schema and minority-role reporting alongside aggregate metrics.

Later milestones add catalogue-aware validation, ASIM schema/data tests, parser
preview, reviewer agreement, release packaging, and opt-in deployment gates. The
full sequence and exit criteria are in the [roadmap](ROADMAP.md). The research basis
for the semantic-mapping boundary is in
[the semantic mapping research note](docs/semantic-mapping-research.md).

## Development

Run the same checks used in CI:

```console
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

Enable commit-time checks after cloning:

```console
uv run pre-commit install
uv run pre-commit run --all-files
```

GitHub Actions runs the quality checks and tests Python 3.11, 3.12, 3.13, and 3.14.

## Contributing

Contributions are welcome, particularly where they make the project more modular or
interoperable. Useful directions include:

- adapters for other normalization targets, including OCSF;
- semantic-mapping techniques not represented by the current lexical, frame, and
  retrieval baselines;
- integrations with review tools, data platforms, and downstream validation
  workflows;
- provider-neutral evaluation cases, metrics, and leakage-resistant dataset splits;
  and
- improvements that separate general workflow contracts from ASIM-specific types
  without weakening provenance or human approval boundaries.

Please open an issue before starting a substantial architectural change so the
contract boundary can be agreed first. Evaluation fixtures and examples must be
synthetic or suitably sanitized; do not commit operational logs, credentials,
customer data, or other sensitive telemetry.

## Licence

LogLathe is licensed under GPL-3.0-or-later. DeepParse remains Apache-2.0 and is
not vendored. Potato is an optional, separately installed GPL dependency. See
[`LICENSE`](LICENSE) and [`THIRD_PARTY_NOTICES`](THIRD_PARTY_NOTICES).
