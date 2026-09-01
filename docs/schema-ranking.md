# Schema ranking phase

Schema ranking is the bounded phase that estimates which normalization schema best
fits a parsed event cluster. It does not approve a schema or predict target fields.

```text
DeepParse -> ParsedCluster -> SchemaRankingRequest -> schema-ranking approach
                                                   |
                                                   v
                                      SchemaRankingPrediction
                                      - ranked candidates
                                      - evidence
                                      - confidence
                                      - selection or abstention
```

The initial `source-concept` approach consumes only the cluster template and an
explicit candidate-schema list. It uses target-neutral tokens from
`source_semantics/normalization.py`, attaches attributable concept evidence, and
abstains when there is no evidence or the leading scores are tied.

`DeepParseClusterer` owns no schema state. Build orchestration ranks its parsed
clusters separately and writes `schema-rankings.jsonl`. The existing
`clusters.jsonl` remains enriched with the legacy `schema_suggestion` object so
current compiler, annotation, and external artifact readers continue to work.
Likewise, `asim_forge.suggestions.suggest_schema` and
`asim_forge.source_normalization` remain compatibility imports.

Schema ranking and field mapping are deliberately different packages:

- `schema_ranking/` owns schema requests, candidates, evidence, confidence,
  abstention, approaches, and cluster enrichment;
- `source_semantics/` owns target-neutral token and phrase normalization;
- `semantic_mapping/field_ranking.py` owns target-field ranking;
- `semantic_mapping/source_context.py` owns structured key-to-slot context; and
- `semantic_mapping/approaches/_lexical.py` is now only a compatibility import.

The `schema-hint` corpus track evaluates the schema-ranking phase. Field ranking,
source-role prediction, and mapping correctness require adjudicated
`semantic-gold` cases and are not inferred from Microsoft sample placement.
