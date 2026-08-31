# LogLathe roadmap

LogLathe is ASIM-first while the initial workflow and evidence base mature. It
separates review decisions in the data model, but it should not force
those decisions into disconnected human sessions. The intended experience is a
progressive review: prepare suggestions before the reviewer arrives, record each
decision as its own auditable checkpoint, and let an eligible reviewer continue
to the next checkpoint while the examples are still fresh.

## Product principles

- Automate preparation; ask a person to confirm judgement, ambiguity, and risk.
- Preserve separate approval records for cluster coherence, ASIM mapping, and
  release readiness.
- Do not make the reviewer reread the same events at each checkpoint.
- Prefill source metadata from onboarding and suggestions from analysis. Never
  ask a reviewer to retype information the system already has.
- Show why a suggestion was made, its confidence, and what remains unresolved.
- Allow **continue now**, **save for an ASIM reviewer**, and **defer**. A stage is
  a governance boundary, not necessarily a page or a separate work queue.
- Do not let an ASIM suggestion influence the independent cluster-coherence
  decision. Reveal it after that decision, or clearly isolate it until then.
- Keep adjudicated gold, upstream hints, parser-derived references, and unlabelled
  diagnostics in separate evaluation tracks. Never turn provenance into accuracy
  by changing a label in a manifest.

## Direction — ASIM first, target neutral

The first complete workflow targets ASIM because its schemas, parser catalogue,
review process, and Microsoft Sentinel output give the project a concrete boundary.
The long-term product boundary is security-log understanding and normalization,
not one target schema. OCSF is the next intended target once the ASIM evaluation
loop is credible; adding it must not weaken or reinterpret existing ASIM results.

The stable centre should be a target-neutral source-semantic frame. Input and
normalization concerns sit on either side:

```text
unstructured text -> DeepParse ---------+
CEF/JSON/CSV -> structure adapter -------+-> source semantics -> ASIM target adapter
                                                +-----------> OCSF target adapter
```

This direction requires explicit seams rather than replacing ASIM names throughout
the codebase in one large refactor:

- introduce versioned normalization-target and catalogue interfaces while keeping
  the ASIM adapter as the default implementation;
- represent target fields as paths with target-specific constraints, because ASIM
  columns are flat while OCSF includes nested objects, arrays, class/type UIDs, and
  enumerated values;
- keep source roles and evidence independent of ASIM and OCSF field names;
- evaluate each target against its own pinned catalogue and labels, never by
  comparing raw ASIM and OCSF scores as though the tasks had identical granularity;
- preserve a compatibility reader for existing ASIM fixtures and generated
  artefacts before changing the public package or CLI contract.

Known data challenges are part of the design. Microsoft `RawLogs` and
`IngestedLogs` samples are useful, but ingestion output is not normalized ASIM
output. ASIM schema/data tester CSVs contain aggregate conformance findings rather
than row-level expected mappings. Existing parsers can provide silver reference
mappings, but evaluating against the same parsers is reproduction, not independent
correctness, and can inherit their defects. OCSF's paired examples are closer to
the desired raw-to-normalized shape, but upstream explicitly describes them as
informative rather than gold. Larger converter-generated corpora such as SETC need
the same silver-label treatment.

Structured sources add another challenge. JSON and CEF fields should be preserved
by deterministic adapters instead of flattened and rediscovered by DeepParse.
Original records, decoded structure, transformations, target versions, and label
provenance must remain inspectable through review and release reports.

## Milestone 1 — Cluster-review walking skeleton (current)

Goal: establish stable clusters, an independent cluster-coherence decision, and
the deterministic compiler boundary.

- Cluster logs and retain representative events and typed slots.
- Review each cluster as `approved`, `needs_split`, `insufficient_evidence`, or
  `rejected`.
- Keep vendor/product and ASIM mapping out of the cluster decision.
- Record an approved but unmapped cluster as `awaiting_mapping`.
- Compile only a complete, explicitly approved parser specification.

Exit criteria: Stage 1 decisions round-trip from Potato, incomplete approvals do
not generate KQL, and every generated artefact has deterministic provenance.

## Milestone 2 — Continuous assisted ASIM review

Goal: after cluster approval, carry the reviewer directly into a prefilled ASIM
suggestion without losing context or weakening the Stage 1 checkpoint.

The architecture rationale and proposed evaluation boundary are recorded in
[the semantic typing and schema matching research note](docs/semantic-mapping-research.md).

### Catalogue foundation

- Retrieve the machine-readable field catalogue used by Microsoft's
  `ASimSchemaTester` from the Azure-Sentinel repository instead of maintaining a
  local copy of ASIM field definitions.
- Resolve branches and tags to an immutable Git commit and record both that commit
  and the downloaded content hash in a generated snapshot manifest.
- Preserve Microsoft's CSV unchanged in the snapshot; parse it into typed fields
  only at the ASIM Forge boundary.
- Merge `Common` fields with schema-specific overrides when presenting a target
  schema to suggestion providers.
- Treat human-readable descriptions and semantic schema versions as separately
  versioned upstream documentation. Add them through an enrichment adapter rather
  than embedding or hand-maintaining them in the core catalogue.

### Preparation before review

- Import vendor, product, source table, and message field from a source-onboarding
  record.
- Generate a versioned, ranked ASIM-schema suggestion for every cluster.
- Propose slot-to-ASIM-field mappings and transforms from slot types, template
  context, examples, and the selected schema.
- Identify mandatory and recommended ASIM fields that cannot yet be populated.
- Store method/version, confidence, evidence, and unresolved warnings with the
  suggestion. A low-confidence suggestion is still useful as a draft, not as an
  approval.
- Compare direct lexical, source-frame, and approved-case retrieval approaches
  through the same prediction contract and evaluation harness before selecting a
  production suggestion provider.
- Use an external grouped dataset split so approved-case retrieval sees only
  reference partitions and cannot learn from held-out source/template families.

### ASIM-first evidence ladder

- Run commit-pinned Microsoft ASIM parser-development raw samples in a dedicated
  `schema-hint` track. Score agreement with their file-level schema placement only;
  do not claim field-mapping accuracy from it.
- Use the small Authentication, NetworkSession, and AuditEvent CEF pilot to expose
  obvious baseline gaps before expanding to more schemas or structured formats.
- Treat mappings extracted from existing Microsoft parsers as `upstream-silver`
  when that track is implemented. Show them to reviewers as attributable reference
  material and never promote them automatically into gold.
- Promote selected clusters into `semantic-gold` only through the frozen queue,
  independent review, and adjudication workflow.
- Expand by source/template family, keeping grouped validation and test labels
  locked before approach comparison.

### Progressive review experience

1. Show the existing cluster review without exposing the ASIM answer.
2. Save the cluster decision as its own immutable/versioned checkpoint.
3. On approval, expand an **ASIM suggestion** step in the same task and retain the
   template, events, and slots on screen.
4. Prefill source metadata read-only by default and make its origin visible.
5. Present ranked schemas and mappings as editable rows, not raw JSON.
6. Let a qualified reviewer accept, edit, reject, or defer the suggestion. A
   general cluster reviewer may choose **Send to ASIM review** without completing
   it.
7. Save the ASIM decision separately, then offer parser preview and validation.

Reject, split, and insufficient-evidence decisions do not open ASIM review.
Changing an approved cluster later invalidates its downstream suggestion and
mapping rather than silently reusing stale work.

### Data and API changes

- Use the versioned provider-neutral semantic mapping case contract as the common
  gold format for baseline, retrieval, and model comparisons. Keep provider output
  and confidence outside the gold cases.
- Split the current combined review record into `ClusterDecision`,
  `SourceMetadata`, `AsimSuggestion`, and `AsimMappingDecision` records.
- Link records with stable cluster and source IDs plus explicit revision IDs.
- Keep generated suggestions distinct from human decisions; accepting a draft
  creates a decision record rather than overwriting the draft.
- Add lifecycle states such as `awaiting_cluster_review`, `awaiting_mapping`,
  `mapping_in_progress`, `awaiting_validation`, and `invalidated`.
- Export canonical JSONL for reproducibility while the UI edits typed fields.

### Exit criteria

- An approved cluster can continue into ASIM review without a page/task change or
  repeated event reading.
- Onboarding metadata and suggested mappings are prefilled and attributable.
- The reviewer never needs to edit JSON.
- Cluster and mapping approvals remain independently auditable and can be made by
  different people.
- Deferred work resumes with the exact examples, suggestion revision, and edits.
- Measure median active time per cluster, suggestion acceptance/edit rates,
  deferral rate, and invalidation rate to confirm the flow reduces human work.

## Milestone 3 — Schema-aware validation and parser refinement

Goal: turn an approved mapping into a parser candidate with actionable checks.

- Pin and version the supported ASIM schema catalogue.
- Validate field names, types, mandatory fields, aliases, and normalization rules.
- Generate a parser preview alongside sample normalized output.
- Run deterministic fixtures and ASIM schema/data tests where available.
- Return validation failures to the mapping rows that caused them.
- Require an explicit validation decision; do not equate successful generation
  with production approval.

Exit criteria: every candidate reports schema coverage, test evidence, warnings,
and the exact input/mapping revisions used to generate it.

## Milestone 4 — Agreement, packaging, and release gates

Goal: make reviewed candidates safe to collaborate on and promote.

- Support reviewer roles, assignment, disagreement resolution, and sign-off.
- Produce source-controlled parser packages and reviewable diffs.
- Test against an authorized Sentinel workspace when configured.
- Add release policy, versioning, rollback metadata, and deployment approval.
- Keep deployment opt-in and separate from review completion.

Exit criteria: a candidate can move from reviewed evidence to a reproducible
release package with explicit ownership and no implicit deployment.

## Deliberately deferred

- Automatically approving clusters or ASIM mappings solely from confidence.
- Showing ASIM suggestions before cluster judgement unless testing demonstrates
  that anchoring does not damage cluster-review quality.
- Requiring the same person to perform cluster, ASIM, and release review.
- Treating generated KQL as production-ready without validation and release gates.
- Extending the frozen DeepParse path for structured and multiline formats such as
  JSON, CEF/LEEF, syslog variants, stack traces, and system-specific records; track
  this separately in [the input-enrichment backlog](docs/log-input-enrichment-backlog.md).
