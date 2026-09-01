# ASIM field-mapping baseline plan

Status: implementation plan
Last reviewed: 2026-09-02

## Purpose

[The non-LLM corpus plan](non-llm-baseline-corpus.md) decides *which evidence* may
support which claim. This note decides *what to build, in what order*, so the field
mapping stage acquires an interpretable baseline. It is a sequencing and
implementation document, not a new evidence contract.

## Problem statement

[artifacts/evaluation-baseline.json](../artifacts/evaluation-baseline.json) currently
reports `direct-lexical` at `field_micro_f1 = 0.857` on one synthetic case. That
number has no floor, no ceiling, and no error decomposition, so it cannot support
any statement about approach quality — including the statement that the approach
works at all.

A baseline for this stage is therefore not one score. It is four reference points
reported with the same metric engine, each carrying a different permitted claim.

| Reference point | Definition | Permitted claim |
| --- | --- | --- |
| **B-floor** | Trivial priors that use no source evidence | Whether an approach beats class imbalance |
| **B-frozen** | `direct-lexical` v3, `semantic-frame` v3, `case-retrieval` v2, never tuned on harvested evidence | What existed before evidence was acquired |
| **B-oracle** | The same approaches given gold schema, and later gold source frame | Where the error actually is |
| **B-ceiling** | Signature-collision ceiling per context view; later, inter-annotator agreement | What is identifiable from the available context |

The gap B-frozen to B-oracle is engineering headroom. The gap B-oracle to B-ceiling
is information headroom. Anything above B-ceiling requires the human or
repository-agent inputs described in
[the corpus plan](non-llm-baseline-corpus.md#later-human-and-repository-agent-assistance).

## Known defects in the current field mapping stage

These are recorded so the frozen baseline is understood rather than mistaken for a
tuned system. None should be fixed before B-frozen is captured.

| Defect | Location | Consequence |
| --- | --- | --- |
| Candidate generation and ranking are one function | [field_ranking.py](../src/asim_forge/semantic_mapping/field_ranking.py) | Fields with zero token overlap are discarded before scoring, creating an unmeasured recall ceiling |
| `Alias` fields are excluded from ranking | `rank_fields` | Legitimate ASIM alias targets can never be predicted; the cost is unmeasured |
| Only `name` and `logical_type` are used | `rank_fields` | Catalogue descriptions, requirement level, and `allowed_values` enumerations are unused |
| `0.35`/`0.65` precision and coverage weights | `rank_fields` | Arbitrary constants with no train partition on which they could be tuned legitimately |
| Alphabetical tie-breaking | `rank_fields` sort key | Systematic bias toward `ActorUsername` over `TargetUsername` and similar pairs |
| Schema concept overlap is an unnormalized count | [source_concept.py](../src/asim_forge/schema_ranking/approaches/source_concept.py) | Schemas with larger concept sets are structurally favoured; invisible at three schemas |
| Slots are mapped independently | all approaches | Two slots may claim one target that the compiler will reject; no assignment step exists |

The catalogue `allowed_values` enumerations (`EventResult`, `DvcAction`, and
similar) are the largest cheap win available: matching template *constants* against
target enumerations is high precision and needs no corpus. It is deliberately
deferred until after B-frozen so the improvement is measurable.

## Sequenced work

### PR 1 — floor, decomposition, and visible ties

No new corpus. Establishes the interpretation machinery for every later number.

1. Register prior approaches so the metric engine scores them identically to real
   approaches: `null-prior`, `majority-schema-prior`, `field-frequency-prior`.
   Priors fit on reference cases only and exclude the case under evaluation, using
   the same leave-one-out discipline as `case-retrieval`.
2. Add the schema oracle as an explicit, recorded harness condition rather than an
   approach, so oracle results can never be reported as approach results.
3. Separate candidate generation from candidate scoring in `field_ranking`, and
   emit `candidate_recall_at_1/3/5` and `candidate_reduction_ratio` so retrieval
   failure is distinguishable from ranking failure.
4. Make ties machine-readable and report `field_top1_tie_rate`. Do not change the
   deterministic tie-break order: B-frozen must stay frozen.
5. Warn at report level when a registered approach fails to beat the best prior.

The source-frame oracle is intentionally **not** in PR 1. It requires the source
frame and target projection to be separable stages, which only `semantic-frame`
currently is. It lands with the v2 contracts in PR 3.

### PR 2 — statistical honesty

1. Source-family cluster bootstrap confidence intervals on every reported metric.
2. Paired permutation tests for approach differences.
3. Report the minimum detectable effect in the report header. At the planned 30–50
   calibration cases this is roughly 15 F1 points, which bounds what that set can
   decide and should be stated rather than discovered later.
4. Replace bare `coverage` with a selective risk–coverage curve and its AUC.

Implemented in [statistics.py](../src/asim_forge/semantic_mapping/statistics.py).
Two decisions are worth recording because they constrain later work.

**The exchangeable unit is the source family, not the case.** Templates from one
product are not independent observations, so the bootstrap resamples whole groups
and the permutation test swaps whole groups. The pre-label split group is used when
a split is supplied; source metadata is a fallback, and the report names which was
used. Case-level resampling would report differences a new source family would not
reproduce.

**Approaches are tested against one baseline, not all pairs.** All-pairs testing
across six registered approaches multiplies the false-positive rate on a sample far
too small to absorb it. The default baseline is the first registered prior.

The risk–coverage curve orders cases by the approach's own scores. Those scores are
normalized lexical overlap, so the curve measures ranking quality only and must not
be read as calibration. Brier score and reliability diagrams stay out of scope until
a provider emits probabilities, as
[the corpus plan](non-llm-baseline-corpus.md#metrics-and-reports) requires.

### PR 3 — version 2 contracts

1. Freeze the source-frame facet registry (`domain` / `relation` / `entity` /
   `property`) and report facet accuracy beside exact-role accuracy, so vocabulary
   growth does not read as regression.
2. Version 2 `MappingRequest` supporting genuinely absent fields, so the V0–V5
   context-mask adapter physically removes information instead of asking approaches
   not to read it.
3. Add the source-frame oracle once projection is a separable stage.

### PR 4 — controlled track and the N2/N3 rungs

Build the controlled and metamorphic track from the pinned catalogue before any
external acquisition. It has zero acquisition cost and zero licence risk, its
answers are known by construction, and it exercises the version 2 record format
end-to-end while defects are still cheap to fix. Then add the deterministic slot
profiler (N2) and the classical matcher ensemble (N3).

### PR 5 — bounded ASIM parser silver

The B1 release described in [the corpus plan](non-llm-baseline-corpus.md#baseline-release-b1-automated-asim-silver),
bounded to Authentication, NetworkSession, and AuditEvent, CEF parser families
first, split by parser family before anything is tuned.

## Corpus selection

The corpus decision in [the corpus plan](non-llm-baseline-corpus.md) stands. This
note records only the sequencing change and the documented-silver sources that plan
did not itemise.

**Sequencing change.** Build the controlled/metamorphic track *before* ASIM parser
lineage extraction, for the reasons in PR 4.

**Additional documented-silver sources**, all inexpensive and licence-clean:

| Source | Contribution | Note |
| --- | --- | --- |
| ArcSight CEF and IBM LEEF field dictionaries | The canonical abbreviation table (`src`, `dst`, `spt`, `dpt`, `suser`, `duser`, `deviceAction`) with documented meanings | A subset is already hand-coded in `_ALIASES` in [normalization.py](../src/asim_forge/source_semantics/normalization.py). Adopting the published dictionary grows source vocabulary without label leakage |
| Windows EventLog manifests (`wevtutil gp`, `.man` files) | Machine-readable EventData field names and types per event ID, generated locally | No redistribution question; complements OSSEM-DD's uneven coverage |
| Zeek log documentation | Documented column names, types, and descriptions per log type | Strong NetworkSession source dictionary; BSD-licensed documentation |
| RFC 5424 structured data and RFC 3164 | Normative syslog element semantics | `normative-schema` evidence class |

## Techniques from adjacent fields

[The research note](semantic-mapping-research.md) covers semantic typing, schema
matching, and log-specific systems. These adjacent fields fill gaps that note does
not address. None is a near-term dependency; each is recorded so the relevant PR
can adopt an established protocol instead of inventing one.

| Field or work | What it contributes here |
| --- | --- |
| **Semantic role labelling** (PropBank/FrameNet; CoNLL-2005/2012 protocol) | The source frame is an SRL task. Borrow its evaluation protocol directly: report **argument identification** separately from **argument classification**, and report both *given gold structure* and end-to-end. This is a mature precedent for the decomposition the corpus plan requires, including partial-credit conventions for role granularity |
| **Schema-Guided Dialogue** (Rastogi et al., AAAI 2020) and zero-shot slot filling from slot descriptions | The closest task analogue. Its premise is generalising to **unseen services** using natural-language schema descriptions — that is, unseen source families using ASIM field descriptions. Direct evidence that the currently unused catalogue descriptions carry the transfer signal, and a better template for the unseen-family split than a generic grouped split |
| **SemTab** (ISWC challenge; CTA/CEA/CPA) | Established hierarchy-aware approximate scoring. Predicting `SrcIpAddr` when gold is `SrcDvcIpAddr` should not score identically to predicting `EventResult`. Gives partial credit a published basis |
| **V-usable information** (Xu et al.); **pointwise V-information / dataset difficulty** (Ethayarajh et al.); **MDL probing** (Voita and Titov) | A principled quantity for the V0–V6 context ladder. Delta-accuracy between views confounds "more information available" with "this method can exploit it"; V-information separates them. The pointwise variant yields a per-case difficulty score that populates the irresolvable bucket directly |
| **Selective prediction and learning with rejection** (Chow's rule; Geifman and El-Yaniv; Cortes et al.; Mozannar and Sontag on learning to defer) | Turns `coverage` into a risk–coverage curve and supplies a principled deferral policy. "Learning to defer" is the formalism for the detection-engineer-in-the-loop design |
| **Conformal prediction and conformal risk control** | Produces a candidate *set* with a distribution-free coverage guarantee: "the correct field is in this set 90% of the time." Split conformal needs only a small calibration set, so it is viable at this scale, and it maps onto the existing ranked-candidate reviewer surface. This is how abstention becomes defensible before scores have a probabilistic interpretation |
| **Schema matching without a reference alignment** (Gal, *Uncertain Schema Matching*; matching predictors; top-K matching) | Estimates matcher quality and ensemble weights **without gold**. Given that the central constraint is the absence of row-level gold, this literature is unusually on-point |
| **COMA/COMA++ matcher composition** (Do and Rahm); **Rahm and Bernstein's 2001 taxonomy** | The canonical design vocabulary for the N3 ensemble rung: aggregation strategies, thresholding, and reuse of prior match results |
| **Clinical terminology mapping** — OHDSI Usagi and OMOP CDM; LOINC RELMA | The closest *operational* analogue: domain experts mapping local codes into a fixed target vocabulary at scale, with a ranked-suggestion tool, dual review, and published inter-mapper agreement studies. Precedent for the annotation workflow, the agreement ceiling, and reviewer-effort metrics |
| **Active learning** — uncertainty sampling, core-set diversity, query-by-committee | The three registered approaches already form a committee. Mining disagreement maximises information per adjudication hour. Critical caveat: this biases the sample, so the calibration budget must split into a stratified random **test** portion and a separately reported disagreement-mined **diagnostic** portion |
| **Record linkage blocking metrics** (Christen) — pair completeness, reduction ratio | The standard names and definitions for the candidate-generation metrics added in PR 1 |
| **Ontology alignment semantic precision and recall** (Ehrig and Euzenat) | Hierarchy-aware partial credit; complements SemTab scoring |
| **Auto-Suggest and Auto-Pipeline** (Microsoft) | Companion precedent to the Auto-Type citation already recorded, for the future repository-agent context provider |

## Deferral and hand-off, recorded for later

These are noted so the version 2 prediction contract does not have to be reopened
to support them. They are not in scope before B-ceiling exists.

- **Route by expected reuse, not by uncertainty alone.** A question about a vendor
  enumeration appearing across forty templates in a product family is worth an
  owner's time; a one-off is not. Rank the deferral queue by collision-ceiling
  contribution multiplied by source-family frequency.
- **Give the deferral a guarantee.** With conformal candidate sets the question
  becomes "the answer is one of these three, which is it?" rather than "what does
  this field mean?" That is a materially cheaper question for a detection engineer,
  and the same interface is usable by a read-only repository agent without changing
  the provider contract.
- **Design conformal calibration into the version 2 prediction record now.**
  Retrofitting it later means re-running every evaluation.

Raw logs remain untrusted data throughout. Any future agent keeps read-only scoped
access, no deployment authority, a strict output contract, full provenance, and a
deterministic validation and review boundary.
