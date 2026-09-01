# Semantic mapping pilot dataset plan

This folder tracks the acquisition and adjudication plan; it is not itself a gold
dataset. Cases become evaluation evidence only after their JSONL provenance points
to completed review and adjudication decisions. Use the
[blinded semantic annotation workflow](../../docs/semantic-annotation-workflow.md)
to prepare approved clusters for review and promote adjudicated decisions without
exposing approach predictions to annotators.

## First calibration target

Build 30–50 cases before tuning the three semantic approaches. Select clusters
across independent source families rather than taking the most frequent templates
from one corpus.

| Coverage area | Initial sources | Cases to include |
| --- | --- | --- |
| Authentication | LogHub OpenSSH, LogInject SSH, Matryoshka SSH, sanitized operational authentication logs | Success, failure, logout, invalid user, key/password method, ambiguous actor/target. |
| Network session | Sanitized firewall, flow, proxy, or network-device logs | Source/destination addresses and ports, allow/deny constants, missing direction, reporting-device ambiguity. |
| Audit event | Linux security/system audit, Windows audit, and application administrative logs | Actor, target object, action, result, policy/configuration changes, partial evidence. |
| Boundary outcomes | Mixed application and infrastructure logs | Legitimate `unresolved` and `not_applicable` cases; do not force every cluster into ASIM. |

The public paper corpora provide candidate source events, not ASIM labels. Incident,
anomaly, prompt-injection, and LogHub template labels must never be imported as
schema or field gold.

The [non-LLM corpus and baseline plan](../../docs/non-llm-baseline-corpus.md)
defines the automated evidence tracks that should be frozen before these cases are
used for tuning. Parser-derived and paired-output silver can select and diagnose
candidate methods, but it does not replace this independent adjudication step.

## Adjudication workflow

1. Freeze the cluster/template revision and representative events.
2. Assign a source-family group before viewing approach predictions.
3. Label source semantics first, including meaningful template constants.
4. Project those semantics into the pinned ASIM catalogue or record an explicit
   unresolved/not-applicable outcome.
5. Have a second qualified reviewer adjudicate disagreements and record both
   decision references.
6. Lock test cases before changing an approach.
7. Create the external grouped split described in
   [the split contract](../../docs/semantic-dataset-splits.md).

The initial calibration set is for error discovery. Approach-selection claims
require a larger multi-source set and per-family results after the label vocabulary
and review instructions stabilize.
