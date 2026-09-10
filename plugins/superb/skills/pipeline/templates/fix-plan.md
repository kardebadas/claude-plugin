# Pipeline v2 — Gate Fix Plan

Complete this plan only after every required review report has returned and the
controller has validated and consolidated the findings. Once its identity and
scope are recorded in `progress.md`, this plan is immutable for the round.

## Scope

| Field | Value |
| --- | --- |
| Gate | <gate-id> |
| Round | <round-number> |
| Prior reviewed HEAD | <full-commit> |
| Targeted blocking findings | <Critical-and-Important-IDs> |
| Included Minor dispositions | <IDs-and-authority-or-none> |
| Applicable decisions | <decision-refs-or-none> |
| Fix-plan path | <run-relative-path> |

The targeted IDs must equal the gate's current open Critical and Important
findings. An explicitly included Minor does not manufacture blocker progress.
If an unanswered choice or conflicting requirement prevents a fix definition,
record it and ask the user before recording or dispatching this round.

## Machine-readable remedy authority

Include this narrow table whenever any targeted finding is artifact-only. Its
rows exactly match the ordered targeted finding set; workers cannot reclassify
them.

<!-- pipeline-remediation-scope/v2 -->
| Finding | Kind | Artifacts |
| --- | --- | --- |
| <finding-id> | <source-or-artifact> | <none-or-JSON-array-of-exact-repository-relative-paths> |

`source` uses exactly `none`. `artifact` uses a nonempty JSON string array of
unique exact paths.

## Compatible fix batches

| Batch | Finding IDs | Objective and approved behavior | Files / typed write scopes | Depends on | Focused tests and evidence |
| --- | --- | --- | --- | --- | --- |
| <batch-id> | <finding-ids> | <smallest approved fix> | <file:/tree: scopes> | <batch-ids-or-none> | <commands-and-output-paths> |

Group related findings that share context and files. Independent, disjoint
batches may run concurrently within the global worker limit; dependent or
overlapping work is sequential. A finding is not automatically a fixer
assignment. Do not add optional changes outside the recorded scope.

## Integrated verification and re-review

- Integration target: `<target-branch>`
- Required phase verification command(s): `<commands>`
- Evidence applicability requirements: `<code/tests/fixtures/config/dependencies/environment>`
- Recorded reviewer assignments reused for the same gate: `<assignments>`
- Re-review focus: `<targeted-findings, fix-diff, regressions, integration-consequences>`

The controller persists the round and active fixers before dispatch. After the
batch is committed, integrated, and verified, it records strict fix provenance,
releases fixers, and reserves the existing gate reviewers. The re-review—not
this plan—records the round outcome and remaining blocker IDs.
