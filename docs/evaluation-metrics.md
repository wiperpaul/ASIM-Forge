# Semantic mapping evaluation metrics

The metric engine accepts provider-neutral `SemanticMappingCase` records and
`SemanticMappingPrediction` records. It has no registry of concrete approaches and
does not invoke providers. This keeps metric correctness reviewable independently
from lexical, retrieval, local-model, or API implementations.

The report includes:

| Metric | Purpose |
| --- | --- |
| Schema top-1 and top-3 | Measures the answer shown first and whether a short reviewer candidate list contains the expected schema. |
| Schema MRR | Measures how quickly a reviewer encounters the first correct schema in a ranking. |
| Source-role micro/macro F1 | Evaluates exact source-kind, locator, and semantic-role triples before ASIM projection. |
| ASIM-field micro/macro F1 | Evaluates exact source-locator-to-field projections. Normalized constants include their expected value. |
| Field MRR | Measures the rank of the expected ASIM field for each source locator. |
| Field recall at ground-truth size | Globally ranks candidate source-field pairs and measures recall in the top `|gold|` pairs. |
| Mapping and full exact match | Requires a complete schema and field set; full exact match additionally requires the complete source frame. |
| Coverage and disposition accuracy | Makes abstention visible rather than allowing difficult cases to disappear from precision. |
| Mean mapping edits | Counts a schema correction plus missing and extra field mappings as a rough reviewer-work proxy. |

Every aggregate contains predictions from exactly one approach name and version.
Each prediction must match its case ID and immutable catalogue revision. Correctly
empty source and field sets receive full case-level F1, while false-positive labels
on an empty case still receive zero.

The ranking measures follow the evaluation shape used by
[Magneto](https://www.vldb.org/pvldb/vol18/p2681-freire.pdf). Micro-F1 and macro-F1
follow common semantic-annotation reporting, including
[REVEAL](https://arxiv.org/abs/2508.17203). The metrics are complementary:

- F1 evaluates the selected set;
- MRR evaluates ranking effort;
- exact match evaluates completion;
- coverage exposes abstention;
- edit count approximates human correction effort.

[Matryoshka](https://arxiv.org/abs/2506.17512) evaluates syntax, semantic naming,
normalized mapping, and final security-query results separately. ASIM Forge follows
that stage-wise principle. End-to-end parser execution and query precision/recall are
not part of this metric layer because they require the schema-aware validation work
planned for Milestone 3.

Scores from the single checked synthetic case are harness smoke tests, not evidence
about approach quality. A useful comparison dataset needs multiple source systems,
adjudicated labels, unresolved examples, and grouped source/template-family splits.
