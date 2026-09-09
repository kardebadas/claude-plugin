# Pipeline v2 Recovery Phase 1 — Master Evidence Completion Plan

> **For agentic workers:** REQUIRED EXECUTION ROUTE: approved controller-led multi-task batches. Do **not** invoke `superb:pipeline`, SDD, or executing-plans. Every prompt includes zero-assumption escalation; workers publish attempt-bound evidence and never edit `progress.md`.

**Goal:** Close the remaining review-evidence contract gaps, document the exact format, and produce fresh integrated evidence for the mandatory master gate.

**Architecture:** Extend the existing strict report parser and gate evaluator rather than adding a parallel review system. Newly published reports carry explicit per-finding outcomes; digest-sealed historical five-field reports remain lineage-only. Direct reference documentation changes follow the tested helper behavior, and local artifact tasks capture phase/master-review evidence.

**Tech Stack:** Python 3.11 standard library, `unittest`, Markdown, Git.

**Spec:** `docs/superpowers/specs/2026-09-08-pipeline-rebuild-v2-design.md`

<!-- pipeline-v2-phase: id=recovery-01; deps=none; review_gate=final-only; review_reason=This recovery phase receives mechanical verification and then enters the mandatory master gate; no additional phase reviewer is authorized. -->
<!-- pipeline-v2-phase-suite: id=recovery-01; commands=["python3.11 -m unittest discover -s plugins/superb/skills/pipeline/tests -v","./tools/check-plugin.sh","./tools/check-plugin-mutants.sh","git diff --check","git status --short --branch"] -->

## Contracts

- A new strict review report has ordered fields `gate`, `assignment`, `base`, `head`, `findings`, and `outcomes`.
- `outcomes` is a JSON object. Keys are stable finding IDs and values are exactly `Open` or `Resolved`.
- Initial reports map each finding they introduce to `Open`; a clean report uses `findings=-` and `{}`.
- Every active re-review assignment maps every existing finding for the gate exactly once. Any `Open`, missing outcome, disagreement, or invalid value blocks acceptance and requires consolidation or user resolution.
- Existing five-field reports are accepted only when already digest-sealed as historical lineage. They cannot be supplied as newly published initial or re-review evidence.
- The evaluator keeps seal metadata distinct from typed verification evidence and validates actual verification records.

## Tasks

### REC-01 — Enforce explicit reviewer outcomes and recovery invariants
<!-- pipeline-v2-task: id=REC-01; deps=none; kind=source; batch=evaluator; order=1; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py; outputs=none -->
<!-- pipeline-v2-task-suite: id=REC-01; commands=["python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.PhaseGateAndRemediationTest -v","python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.MasterProofIntegrityRegressionTest -v"] -->

**Objective / behavior:** Reuse `_parse_review_report`, `_review_report_set`, `_validated_review_lineage`, and `evaluate_and_close_review_gate`. Add the narrow six-field outcome contract, allow old five-field parsing only for digest-sealed historical paths, keep the D-027 seal outside typed verification records, and retain strict task/gate/remediation semantic and capacity guards.

- [ ] **RED:** Add focused regressions proving a new five-field report fails, a full `Resolved` mapping can close an otherwise valid gate, any `Open` prevents closure, conflicting master-reviewer outcomes cannot pass, missing/extra/invalid outcome entries fail without tracker mutation, and old five-field reports remain valid only through already-sealed lineage. Run the two named test classes and confirm each new test fails for the intended absent behavior.
- [ ] **GREEN:** Implement the smallest parser/evaluator extension. Do not add a new state store, reviewer type, compatibility mode, or acceptance bypass.
- [ ] **GREEN verification:** Re-run the two named test classes. Confirm rejected imports preserve exact tracker bytes and valid evidence advances only its intended gate transition.
- [ ] **Commit:** Stage only the helper and its tests; inspect the staged diff; commit `fix(pipeline): bind reviewer outcomes to gate acceptance`.

### REC-02 — Publish the tested report contract
<!-- pipeline-v2-task: id=REC-02; deps=REC-01; kind=source; batch=documentation; order=1; write_scope=file:plugins/superb/skills/pipeline/references/review.md,file:docs/superpowers/specs/2026-09-08-pipeline-rebuild-v2-design.md,file:docs/superpowers/plans/2026-09-08-pipeline-rebuild-v2-master-plan.md,file:docs/superpowers/plans/pipeline-rebuild-v2/phase-01.md; outputs=none -->
<!-- pipeline-v2-task-suite: id=REC-02; commands=["./tools/check-plugin.sh","git diff --check"] -->

**Objective / behavior:** Document D-029's exact `outcomes` field, active-report completeness, disagreement blocking, and the historical-lineage-only exception without changing the approved hybrid review architecture.

- [ ] Update only the direct design, master-plan, Phase 1 contract, and stage-specific review reference.
- [ ] Run plugin validation and `git diff --check`.
- [ ] Stage only the four declared files; inspect the staged diff; commit `docs(pipeline): specify reviewer outcome evidence`.

### REC-03 — Capture fresh integrated phase verification
<!-- pipeline-v2-task: id=REC-03; deps=REC-02; kind=artifact; batch=evidence; order=1; write_scope=file:docs/superpowers/runs/2026-09-09-pipeline-rebuild-v2-recovery/agent-output/phase-verification.md; outputs=docs/superpowers/runs/2026-09-09-pipeline-rebuild-v2-recovery/agent-output/phase-verification.md -->

**Objective / behavior:** Run the complete recovery phase suite at the committed target tip, record elapsed time, environment and exact inputs, and publish one typed PASS artifact only when every command passes. This task is artifact-only and records integration `N/A`.

- [ ] Run every declared command against the committed integrated HEAD.
- [ ] Write the typed evidence artifact with exact command list, code-state SHA, environment, applicable input identities, outcomes, and elapsed times.
- [ ] Validate its marker, identity, and digest through the existing helper before task completion.

### REC-04 — Prepare the mandatory master-review package
<!-- pipeline-v2-task: id=REC-04; deps=REC-03; kind=artifact; batch=evidence; order=2; write_scope=file:docs/superpowers/runs/2026-09-09-pipeline-rebuild-v2-recovery/agent-output/master-review-package.md; outputs=docs/superpowers/runs/2026-09-09-pipeline-rebuild-v2-recovery/agent-output/master-review-package.md -->

**Objective / behavior:** Record the approved design/plan/decision paths, immutable original base, full reviewed HEAD, fresh verification reference, changed-file inventory, and complementary Reviewer A/B assignments. This task prepares evidence only and does not dispatch reviewers or accept the gate.

- [ ] Write and validate the package against the current target tip and fresh REC-03 evidence.
- [ ] Complete the artifact task with exact output and validation evidence, integration `N/A`.
- [ ] After all four tasks complete, record phase verification, explicitly advance the final phase, and only then open the mandatory two-reviewer master gate.

## Whole-phase acceptance

- Every source task has a post-baseline implementation commit, task-test evidence, and verified integration into `feat/pipeline-rebuild-v2`.
- Every artifact task has its exact output and validation evidence with integration `N/A`.
- The full declared phase suite passes on the integrated committed HEAD.
- The final-only phase receives no phase reviewer; advancing it routes to the mandatory master gate, never project completion.
