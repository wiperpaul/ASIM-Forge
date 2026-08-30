# Corpus benchmarks and evaluation releases

The release-style benchmark answers a narrow question: did a code or evaluation-data
change alter ASIM Forge's behaviour on a fixed, inspectable corpus? It does not turn
every upstream security benchmark label into ASIM ground truth.

## Three evaluation tracks

| Track | What is scored | What must not be inferred |
| --- | --- | --- |
| `parsing-gold` | Pairwise template-clustering precision, recall, F1, and cluster purity against LogHub `EventId` labels. | Incident detection, ASIM schema selection, and field mapping. |
| `format-diagnostic` | Event/cluster counts, clusters with parameter slots, and the event-weighted rate receiving a provisional non-`NoFit` keyword suggestion. | Accuracy. These corpora have no adjudicated ASIM answer key. |
| `semantic-gold` | Schema ranking, source-role F1, field F1/ranking, exact match, coverage, and edits against ASIM Forge cases. | Production quality when the case set is small, synthetic, or not representative. |

The provisional ASIM-fit diagnostic is deliberately named as such. It measures the
current keyword baseline's willingness to suggest one of the implemented schemas;
it does not say that the suggestion is correct.

## Registered small corpora

| Corpus | Origin | Track | Reason for inclusion |
| --- | --- | --- | --- |
| LogHub OpenSSH 2k | [LogHub](https://github.com/logpai/loghub) | Parsing gold | Security-relevant authentication text with public template labels. |
| LogHub Linux 2k | LogHub | Parsing gold | More varied system-log syntax and substantially more templates. |
| LogHub Apache 2k | LogHub | Parsing gold | Compact web-server error-log sample. |
| Matryoshka SSH example | [Matryoshka artifact](https://github.com/julien-piet/matryoshka) | Format diagnostic | A small SSH stream from a security-log analytics research artifact. |
| LogInject benign SSH 500 | [LogInject artifact](https://zenodo.org/records/20436935) | Format diagnostic | Bounded authentication sample from the paper's open artifact. |
| LogInject benign Apache 500 | LogInject artifact | Format diagnostic | Bounded access-log sample with a different syntax. |
| ASIM semantic smoke cases | This repository | Semantic gold | Exercises the actual schema/role/field evaluation contract. |

The security papers behind Matryoshka and LogInject study objectives such as threat
analytics or prompt injection. Their logs are useful inputs, but their task labels
are not reused as ASIM labels. A security corpus moves into `semantic-gold` only
after its clusters have been labelled and adjudicated under the repository's
provider-neutral ASIM fixture contract.

Large sources such as AIT-LDS are intentionally excluded from the default release
run. They are useful for extended experiments, but are too large and operationally
expensive for a repeatable change gate.

## Reproducibility and data handling

Each corpus has an `evaluation/corpora/<id>/manifest.json`. Remote URLs refer to an
immutable source revision where possible, and every downloaded object has a SHA-256
digest. Archive inputs name one exact member; the runner never extracts an archive
tree. LogInject JSONL is converted to line-oriented input using only its declared
`raw_log` field.

Downloads and generated results remain under ignored `artifacts/`. This avoids
redistributing third-party datasets and reduces the chance of operational logs
being committed. The manifest records upstream terms, but downstream users remain
responsible for checking them.

Run the complete registry locally:

```powershell
uv run asim-forge catalog sync `
  --output artifacts/asim-catalog `
  --revision 027a0f9338bfabcb27b784571b771c54572ebf01

uv run asim-forge evaluation benchmark evaluation/corpora `
  --catalog artifacts/asim-catalog `
  --cache artifacts/corpus-cache `
  --output artifacts/evaluation `
  --revision (git rev-parse HEAD)
```

To show deltas, supply a prior JSON result with `--baseline`. A delta is calculated
only when the corpus ID, approach, primary metric, and corpus fingerprint match.
Changing a manifest or local case fixture therefore suppresses a misleading
before/after comparison.

The runner writes `benchmark-report.json` for machines and `benchmark-report.md` for
release notes.

## Automation and release policy

`.github/workflows/evaluation.yml` runs when evaluation definitions, fixtures,
implementation code, or dependency locks change. Pull requests receive a retained
workflow artifact but cannot publish a release. Successful relevant pushes to
`main` create an `eval-<run>-<sha>` prerelease containing both reports. A `v*` tag
creates its release, or attaches the reports if that release already exists.

Before evaluating, the workflow downloads the newest prior `eval-*` JSON report
when available. Failed or partial evaluations never reach the release job. The
prerelease is therefore a durable comparison point, while ordinary CI artifacts
remain short-lived diagnostics.

Because every qualifying main-branch change can produce a prerelease, old
evaluation prereleases may eventually need a separate retention policy. They
should not be deleted until any results referenced by a paper, thesis, or release
have been archived under a stable tag.
