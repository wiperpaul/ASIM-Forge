# Semantic mapping approach comparison

ASIM Forge compares semantic mapping approaches through one request/prediction
boundary while keeping each implementation in its own module:

```text
provider-neutral case input + pinned ASIM catalogue
                         |
                MappingRequest
                         |
       +-----------------+------------------+
       |                 |                  |
 direct-lexical    semantic-frame     case-retrieval
       |                 |                  |
       +-----------------+------------------+
                         |
           SemanticMappingPrediction
                         |
             shared evaluation metrics
```

The approach receives `MappingRequest`, which contains no expected labels. Provider
identity, rankings, scores, evidence, and warnings live in
`SemanticMappingPrediction`, never in the gold case.

## Initial approaches

| Approach | Module | Purpose |
| --- | --- | --- |
| `direct-lexical` | `semantic_mapping/approaches/direct_lexical/` | A deliberately cheap benchmark that ranks catalogue fields directly from local slot context. It does not emit source-semantic roles or infer important constants. |
| `semantic-frame` | `semantic_mapping/approaches/semantic_frame/` | A two-stage benchmark that first names source roles and static meanings, then projects them into the catalogue. Its small lexical normalizers are evaluation baselines, not production vendor rules. |
| `case-retrieval` | `semantic_mapping/approaches/case_retrieval/` | Retrieves similar labelled cases and transfers their schema, source roles, and target mappings. It excludes the current case by stable case ID, preventing direct target-label leakage. |

Each approach owns a package under `semantic_mapping/approaches/`. Shared
tokenization and catalogue-ranking primitives live in the private
`approaches/_lexical.py` module; they do not own provider state or feedback. Adding
an API, local model, MCP-backed service, retrieval method, or uncertainty-only
oracle means implementing `SemanticMappingApproach` in a new package and adding its
factory to the approach registry. Existing cases and metrics remain unchanged.

## Metrics

The provider-independent [evaluation metric layer](evaluation-metrics.md) defines
schema and field ranking, source-role and field F1, exact completion, coverage, and
edit-count measures. The comparison runner only invokes registered approaches and
attaches their predictions to that shared report.

## Running the comparison

Cases and the loaded catalogue must have the exact same immutable Azure-Sentinel
revision:

```powershell
uv run asim-forge catalog sync `
  --output artifacts/asim-catalog `
  --revision 027a0f9338bfabcb27b784571b771c54572ebf01

uv run asim-forge evaluation compare `
  examples/evaluation/semantic-mapping-cases.jsonl `
  --catalog artifacts/asim-catalog `
  --output artifacts/semantic-comparison.json
```

Repeat `--approach` to compare a selected subset. Without it, all registered
approaches run. The JSON report records every prediction as well as aggregate
metrics, making failures and candidate ranks inspectable.

## Evaluation discipline

The checked example contains one synthetic source and exists only to exercise the
harness. The report emits warnings for fewer than 20 cases, a single source system,
synthetic labels, and any approach that produces no mapped predictions. Individual
retrieval predictions explain when no eligible reference case was available. These
numbers must not be reported as approach quality.

A useful dataset should:

1. contain adjudicated cases from multiple products and event families;
2. preserve `unresolved` and `not_applicable` outcomes;
3. group train/test splits by source or template family rather than random row;
4. report per-schema and minority-role results in addition to micro averages;
5. run each ablation against the exact same cases and catalogue revision;
6. later add parser execution and security-query precision/recall.

Without a split manifest, case retrieval uses leave-one-out evaluation for backwards-
compatible smoke tests. It is safe from same-case leakage but not from near-duplicate
templates, and the report now warns that its result is not comparison evidence. Use
the [grouped split manifest](semantic-dataset-splits.md) for real comparisons: retrieval
then sees only declared reference partitions while every approach is scored on the
same held-out validation or test cases. The CLI also requires the promoted
`case-groups.jsonl` and `promotion-manifest.json` so a split cannot rewrite groups
after labels are visible.
