# Superb Pipeline v2 Rebuild Master Plan

> **For agentic workers:** REQUIRED EXECUTION ROUTE: during the bounded Phase 1 bootstrap, the coding-session controller follows this approved plan with individual Superpowers skills and the sole file-backed tracker; neither Pipeline version orchestrates the rebuild. After each tested v2 capability becomes available, use it only as specified in Phase 1. Subsequent work uses approved multi-task batches, phase verification, selected high-risk phase review, and mandatory final master review. Do not invoke `superpowers:subagent-driven-development` or `superpowers:executing-plans`; their task-bound review/handoff contracts conflict with the approved architecture.

**Goal:** Replace Superb Pipeline v1 with a compact, file-authoritative v2 orchestrator that escalates every unresolved decision, safely batches work, recovers from interruption, mechanically verifies every phase, reviews selected high-risk phases, and always runs a final master review.

**Architecture:** A concise `SKILL.md` routes to four stage-specific references. A Python 3.11 standard-library helper owns strict `progress.md` validation, locking, atomic transitions, readiness, result import, and recovery. Repository validation combines focused unit/integration tests, v2 fixtures, named mutation tests, and real-agent pressure scenarios.

**Tech Stack:** Markdown skills/templates, Python 3.11+ standard library and `unittest`, shell wrappers/mutation harness, Git/Git worktrees, installed Superpowers skills.

**Spec:** `docs/superpowers/specs/2026-09-08-pipeline-rebuild-v2-design.md`

## Global constraints

- Rebuild base is `8348959d1b201a873c68512642a0eb8e5754eaa8`; target branch is `feat/pipeline-rebuild-v2` in `/tmp/claude-plugin-pipeline-rebuild-v2`.
- Runtime decisions D-001 through D-025 in `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/decisions.md` are binding. D-017 is a one-time pre-release adoption and D-019 is a one-time historical outcome reconciliation for this exact rebuild run; neither is an ordinary future resume/migration path. D-021, D-022, D-023, and D-025 authorize only Rounds 4, 5, 6, and 7 respectively of the existing `phase-01` gate; all leave D-006's three-round default unchanged elsewhere and none authorizes the following round. D-024 narrows remediation verification and evidence reuse without weakening any gate.
- This rebuild uses global `worker_limit = 3`; future runs require their own explicit persisted positive limit compatible with detected capacity.
- Every worker prompt includes the zero-assumption contract and status vocabulary. Workers may not spawn untracked agents or edit `progress.md`.
- Every phase contains at most 12 genuine tasks. A task is not automatically a worker boundary.
- Tests precede implementation for testable code and skill behavior. Preserve current quality gates; add no numeric coverage threshold.
- Every phase gets mechanical verification. Only explicitly required high-risk gates get a phase reviewer. Final master review always uses two complementary reviewers.
- Critical/Important findings block. Every Minor has a recorded disposition. Each formal gate allows at most three ordinary remediation rounds under D-006; any finite extension requires its own explicit persisted exact-run authority. D-021, D-022, D-023, and D-025 separately supply only this rebuild's `phase-01` Rounds 4, 5, 6, and 7; D-025 does not authorize Round 8.
- V2 resumes only v2 state. Recognized v1, missing, malformed, unknown, and unsupported schemas are read-only failures.
- This rebuild alone uses the bounded bootstrap in the design/Phase 1: individual Superpowers skills plus the existing sole `progress.md` until the tested v2 primitives can validate and atomically adopt its checkpoints. Neither Pipeline version orchestrates its replacement.
- Python helper scope is Python 3.11+, cooperating processes on one host, and classified local filesystem locking/replacement semantics. Known network/distributed filesystems are rejected; unknown mount/volume types need a fingerprint-bound explicit acknowledgement. Native/simulated platform evidence is labeled exactly.
- Final state is committed and clean on the feature branch. No push, PR, publish, or merge into `main`/`master`.

## File structure map

| Path | Responsibility | Planned action |
| --- | --- | --- |
| `plugins/superb/skills/pipeline/SKILL.md` | Compact invocation/control plane and stage router | Rewrite; target under 500 lines where practical |
| `plugins/superb/skills/pipeline/references/planning.md` | Discovery, design/master/phase plan gates and question escalation | Create |
| `plugins/superb/skills/pipeline/references/execution.md` | Batch selection, worker contract, TDD, integration, phase verification | Create from useful v1 execution rules |
| `plugins/superb/skills/pipeline/references/persistence.md` | Tracker schema, decisions, worker results, resume/reconciliation | Create from useful v1 run-state rules |
| `plugins/superb/skills/pipeline/references/review.md` | Hybrid review, severity, consolidation, remediation, master gate | Create from useful v1 fix/review rules |
| `plugins/superb/skills/pipeline/scripts/pipeline_state.py` | Strict tracker CLI/module, lock/atomic writes, readiness, imports, recovery, gate transitions | Create |
| `plugins/superb/skills/pipeline/templates/progress.md` | Canonical v2 tracker schema | Rewrite |
| `plugins/superb/skills/pipeline/templates/decisions.md` | Stable questions/answers | Replace v1 register template |
| `plugins/superb/skills/pipeline/templates/findings.md` | Critical/Important/Minor evidence and dispositions | Rewrite |
| `plugins/superb/skills/pipeline/templates/fix-plan.md` | One scoped plan per gate remediation round | Rewrite |
| `plugins/superb/skills/pipeline/templates/worker-result.md` | Atomic attempt/task checkpoint evidence | Create |
| `plugins/superb/skills/pipeline/templates/verification-evidence.md` | Digest-referenced PASS evidence bound to the tested code state | Create |
| `plugins/superb/skills/pipeline/tests/test_pipeline_state.py` | Unit/integration/regression tests for helper | Create |
| `plugins/superb/skills/pipeline/tests/fixtures/` | Valid v2, legacy v1, malformed/unknown, blocked/interrupted/review states | Create |
| `plugins/superb/skills/pipeline/README.md` | User-facing v2 behavior and requirements | Rewrite |
| `plugins/superb/skills/pipeline/references/{run-state,implement,parallel,fix-loop}.md` | V1 architecture | Delete after v2 replacements cover retained invariants |
| `plugins/superb/skills/pipeline/templates/{register,implementer-prompt,kit}.md` | V1 artifacts superseded by v2 plans/result contract | Delete after replacement tests fail then pass |
| `plugins/superb/skills/pipeline/scripts/task-brief` | V1 one-task extraction | Delete; v2 workers receive the phase-plan path plus assigned task IDs and batch order |
| `tools/check-plugin.py` | Shared plugin validation plus focused v2 structural checks | Preserve shared checks; replace v1 semantic block |
| `tools/check-plugin-mutants.sh` | No-op-aware mutation proof | Preserve shared mutants; replace v1-only mutants with v2 mutations |
| `tools/fixtures/run-*` | V1 tracker fixtures | Replace with focused v2 fixtures or move canonical inputs under Pipeline tests |
| `.github/workflows/checks.yml` | Repository CI | Replace v1 fixture invocations; add Pipeline unit/integration command |
| `plugins/superb/skills/setup/{check-deps.sh,SKILL.md,README.md}` | Dependency reporting | Add narrowly scoped Python 3.11+ Pipeline requirement without changing Craft 3.9+ |
| `README.md`, `plugins/superb/README.md` | Repository/plugin documentation | Update v2 flow, dependencies, commands, and guarantees |
| `plugins/superb/.claude-plugin/plugin.json`, `plugins/superb/.codex-plugin/plugin.json` | Plugin package metadata | Set version `0.14.0`; update Pipeline descriptions only as needed |

## Shared interfaces fixed before phase expansion

1. `progress.md` is the sole mutable authority; ordinary v2 trackers begin with schema `pipeline-run/v2` and carry revision/last-transition identity. The rebuild bootstrap converts its same tracker in place once, never creates a competing tracker.
2. Phase plans expose strict task and batch metadata: stable ID, dependencies, plan-declared `source`/`artifact` kind, typed `file:`/`tree:` write scopes, exact artifact outputs (`outputs=none` for source), batch ID/order, review gate/reason, one adjacent exact ordered phase-suite JSON array, and one adjacent exact ordered task-suite JSON array for every source task.
3. The helper CLI provides read-only `validate`, `inspect`, and `next`; controller transitions for first task start, D-011 answered-block resume, reservation/block/result import/integration, phase verification, review gate, and remediation rounds. Ordinary initialization may populate an existing artifact-only run directory only when `progress.md` is absent and every existing path is explicitly approved; it never overwrites any tracker or unrelated file.
4. All mutating commands lock a separate run-local resource and atomically replace only the canonical tracker. Failures before replacement preserve the old tracker; failures after replacement report uncertain application and reconcile the stable transition identity without duplicate effects.
5. Worker results identify the controller-assigned run/task/attempt/owner plus plan-declared kind, status, checkpoints, source commits or artifact paths, tests/evidence, and concerns/questions, and are atomically published as immutable evidence. Only the controller imports them; under the tracker lock it validates all four assignment identities for every status and task kind, never changes tracker ownership from a result, and requires the declared kind to match the approved phase task. A new source start/resume records the exact target baseline; completion proves the exact nonempty baseline-to-source commit range, typed write scope, and digest-bound typed task-suite PASS evidence.
6. Source-task integration requires every implementation commit to be an ancestor of the integration commit, that integration commit to be an ancestor of the target branch, and one typed digest-bound `task-integration` PASS record to name the exact integrated commit; artifact tasks record verified completion and `N/A` integration. Rewritten-history modes are not planned.
7. Readiness uses typed scope overlap and is advisory; serialized task, review, fixer, and re-review reservation/start revalidates dependencies, questions, ownership, pairwise candidate conflicts, and fresh controller-bound capacity inside the tracker lock. Caller capacity is not dispatch authority, and missing/invalid capacity fails closed (D-018, D-026).
8. Formal reviewer reports are stored in `agent-output/`; findings and dispositions live in `findings.md`; gate/round state and evidence references live in `progress.md`. Under D-029 (recorded for the recovery run as D-002), every new report includes a strict JSON `outcomes` map. Initial reports map introduced findings to `Open`; every active re-review assignment maps every existing gate finding exactly once to `Open` or `Resolved`. Any open, missing, or conflicting conclusion blocks; already digest-sealed five-field reports are historical lineage only. Initial reports are persisted as content-digest identities and each finding introduction is bound to gate/ID/severity and its introducing report digest(s). `gate.base` and sealed initial reports form an immutable anchor while `gate.head` rolls only after a validated contiguous remediation edge. Gate acceptance is computed from the full initial-plus-remediation report lineage, typed digest-bound recorded verification, blockers/questions, Minor dispositions, exact-round fix provenance, explicit reviewer outcomes, and re-review evidence—not accepted from a boolean flag. A historical round cannot prove a Fixed disposition for a finding its own outcome still listed as blocking; Rejected evidence uses exact structured finding identity plus a rationale. Every completed remediation round has exactly one semantically valid remaining-blocker outcome; D-019 is the one evidence-backed active-rebuild reconciliation for its historical omission, not an ordinary resume/migration path. D-021/D-022 exact-run authority is persisted on its respective row and excluded from code-state verification evidence. D-027 is the single exact-run sealing bridge for the already-open master Round 1; it is not an ordinary transition or migration path.
9. The final acceptance matrix uses the 20 numbered scenarios from the rebuild request as stable `A-01` through `A-20` mappings.
10. `next_action` is a derived persisted summary refreshed atomically with every relevant transition, not permission by itself. `advance_phase(run_dir, *, completed_phase_id, next_phase_id)` is the sole explicit phase cursor transition and validates completed tasks/integration, phase verification, required review acceptance, questions, and the approved immediate successor/dependencies. The final phase routes to the mandatory master gate rather than a nonexistent successor or DONE.

## Phase sequence

### Phase 1 — Durable state, recovery, and scheduling foundation

- **Detailed plan:** `docs/superpowers/plans/pipeline-rebuild-v2/phase-01.md`
- **Dependencies:** none after design/master interface approval.
- **Outcome:** Tested Python helper, strict v2 tracker, result contract, legacy rejection, scheduler, gate/remediation state transitions, and recovery reconciliation.
- **Implementation batching:** Use the explicit rebuild bootstrap through P1-04; then adopt the same tracker into validated v2 format. Prefer one coherent state-helper executor for shared parser/transition code; split only truly disjoint fixture/platform work. Task checkpoints remain individual.
- **Mechanical verification:** Pipeline helper unit/integration suite; valid/invalid fixture CLI checks; real-process lock tests; Python 3.11 syntax/runtime check; targeted mutations; `git diff --check`.
- **Review gate:** required.
- **Reason:** This is the single source of execution truth and concurrency/recovery foundation consumed by every later phase; state corruption or unsafe readiness would repeat/skip work and invalidate all downstream gates.

### Phase 2 — Compact skill orchestration and durable templates

- **Detailed plan:** `docs/superpowers/plans/pipeline-rebuild-v2/phase-02.md`
- **Dependencies:** Phase 1 verified and high-risk review accepted.
- **Outcome:** New compact control plane, four stage references, v2 templates, zero-assumption worker/reviewer contracts, batch flow, hybrid review, bounded remediation, and final branch policy; v1 orchestration files removed.
- **Implementation batching:** Run writing-skills RED controls before edits. Then use disjoint documentation batches only where interfaces are fixed; integrate and inspect cross-reference consistency before verification.
- **Mechanical verification:** Skill/frontmatter validation; word/line and reference routing checks; stale v1/SDD/per-task-review scans; helper/template contract checks; deterministic scenario simulations; targeted mutations; `git diff --check`.
- **Review gate:** required.
- **Reason:** The instructions control user escalation, dispatch authority, destructive boundaries, and formal acceptance. A prose ambiguity can cause unauthorized decisions or false completion across every future run.

### Phase 3 — Repository validation, packaging, and documentation

- **Detailed plan:** `docs/superpowers/plans/pipeline-rebuild-v2/phase-03.md`
- **Dependencies:** Phases 1 and 2 verified and their required reviews accepted.
- **Outcome:** Shared plugin checks preserved, v1-only checks classified/removed, v2 fixtures/mutations wired to CI, setup reports the new Python requirement, user docs describe v2, and both manifests are `0.14.0`.
- **Implementation batching:** Cycle-free order is P3-T01 targeted validator work → P3-T03 CI → P3-T06 manifests → P3-T02 mutation baseline/harness. P3-T04 setup and P3-T05 docs may run independently where typed scopes remain disjoint. The strict complete release gate runs only after its prerequisites land.
- **Mechanical verification:** Pipeline unit suite; default plugin gate; every v2 fixture gate; full no-op-aware mutation harness; JSON parsing; setup regression checks; CI command audit; repository documentation scans; `git diff --check`.
- **Review gate:** final-only.

### Phase 4 — Behavioral pressure, acceptance, and performance evidence

- **Detailed plan:** `docs/superpowers/plans/pipeline-rebuild-v2/phase-04.md`
- **Dependencies:** Phases 1–3 implemented, integrated, verified, and required gates accepted.
- **Outcome:** Writing-skills RED/GREEN real-agent evidence, complete A-01–A-20 acceptance map, recovery/finish rehearsal, comparable measurements, limitation record, and a prepared master-review package. Only after all Phase 4 tasks finish does the controller validate phase prerequisites, record Phase 4 verified, and dispatch the master gate.
- **Implementation batching:** Fresh-context pressure samples may run concurrently up to the global limit; measurement and acceptance consolidation remain controller-owned.
- **Mechanical verification:** Fresh full repository commands; acceptance-matrix completeness; artifact/path/state validation; performance comparison; Git/worktree/remote checks.
- **Review gate:** final-only; the mandatory master gate immediately follows.

## Mandatory final master gate

After Phase 4 verification, record review base `8348959d1b201a873c68512642a0eb8e5754eaa8` and current integrated HEAD. Dispatch exactly two independent complementary reviewers under D-007. Collect both reports; validate/deduplicate all findings; ask unresolved questions; persist one scoped fix plan per remediation round; implement compatible fix batches with TDD; verify; and re-review the same master gate. After any fix, compare affected automated/pressure evidence's recorded HEAD and input/instruction digests with the new code state; rerun only evidence affected by the change. If an actual-agent rerun would exceed the approved campaign budget, keep the gate unresolved and ask for authorization. Stop when D-005 acceptance passes or D-006 blocks/escalates. No ordinary fixes restart the full pipeline.

## Commit strategy

- Commit the approved design independently before plan expansion.
- During implementation, source tasks commit coherent tested changes and retain their result/commit/integration evidence. Plan-declared artifact tasks retain exact artifact/attempt/validation evidence with integration `N/A`; they never create empty commits or stage ignored run files.
- Formal review fixes use separate commits associated with their persisted round.
- Commit curated plan/documentation artifacts. Never stage `docs/superpowers/runs/<run-id>/` runtime state.
- Before each completion claim or phase/master advancement, run the exact fresh command that proves it.

## Final verification commands planned

These commands may be refined only by the approved phase plans when their files exist:

```bash
python3.11 -m unittest discover -s plugins/superb/skills/pipeline/tests -v
./tools/check-plugin.sh
./tools/check-plugin-mutants.sh
python3 -m unittest discover -s plugins/superb/skills/craft/tests -v
./tools/test-craftui.sh
git diff --check
git status --short --branch
```

Platform-specific tests unavailable locally are reported rather than claimed. Current local runtime has Python 3.11.2 only; native macOS and Windows evidence requires those environments.

## Corrected whole-plan execution order

1. Bootstrap P1-01 through P1-04 directly from approved files and the sole rebuild tracker; atomically adopt that same tracker into canonical v2 after P1-04 passes.
2. Use tested transitions for P1-05, tested reservations after P1-05, and normal result import after P1-06. Complete Phase 1, verify, then pass its required gate.
3. Complete Phase 2's artifact/source tasks under their distinct evidence contracts, verify active routes without rejecting legacy fixtures/detectors/prohibitions, then pass its required gate.
4. Execute Phase 3 without a cycle: P3-T01 → P3-T03 → P3-T06 → P3-T02, with P3-T04/P3-T05 scheduled only where current capacity/scopes allow; run the strict integrated release gate after all prerequisites exist.
5. Execute P4-01 through P4-08. P4-06 collects verification evidence but does not close the phase; after P4-08, validate all source/artifact completions and evidence freshness, record Phase 4 verified, then open the mandatory two-reviewer master gate.

At every start/resume, source dependencies use complete Git ancestry proof, artifact dependencies use verified completion, typed scopes are checked pairwise during serialized reservation, phase reasons come from the applicable plan metadata, and post-replacement uncertainty reconciles transition identity before retry.

## Plan expansion and approval gate

One writing-plans agent expands each phase. With `worker_limit = 3`, Phases 1–3 are expanded together because this master plan fixes their shared interfaces and each agent writes only its own phase-plan file; Phase 4 queues until a slot is free. The controller then checks task caps, dependencies, interfaces, TDD steps, exact commands, batching/write scopes, review classifications, and A-01–A-20 coverage. Implementation remains blocked until the user explicitly approves this master plan and all four detailed phase plans.
