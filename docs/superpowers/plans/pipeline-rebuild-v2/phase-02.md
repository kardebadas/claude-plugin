# Pipeline Rebuild v2 — Phase 02: Compact Skill Orchestration and Durable Templates

> **For agentic workers:** REQUIRED EXECUTION ROUTE: use the approved Pipeline v2 controller and multi-task implementation batches. Do not invoke superpowers:subagent-driven-development or superpowers:executing-plans; their per-task review/handoff conflicts with the approved architecture. A task is a recovery checkpoint, not a formal-review boundary; only the phase gate below receives formal review.

**Goal:** Replace Pipeline v1's monolith, prose tracker machinery, and v1 artifacts with a compact v2 router, four stage references, and durable templates that escalate unresolved choices.

**Architecture:** SKILL.md is an under-500-line control plane that routes full, resume, and read-only status modes to planning.md, execution.md, persistence.md, and review.md. Phase 1's Python helper and strict tracker are the executable state authority; Phase 2 documents and instantiates that contract without creating an alternate state system.

**Tech Stack:** Markdown skills/references/templates; Phase 1's Python 3.11+ standard-library helper; Git/worktrees; installed Superpowers skills.

**Spec:** docs/superpowers/specs/2026-09-08-pipeline-rebuild-v2-design.md

<!-- pipeline-v2-phase: id=02; deps=01; review_gate=required; review_reason=The instructions control user escalation, dispatch authority, destructive boundaries, and formal acceptance. A prose ambiguity can cause unauthorized decisions or false completion across every future run. -->

## Global constraints

- Begin only after Phase 1 is mechanically verified and its required review gate is accepted.
- D-001 through D-010 in docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/decisions.md bind every task. An absent/conflicting requirement returns NEEDS_CONTEXT or PLAN_CONFLICT; no convention or agent resolves it.
- Preserve behavior-focused tests and existing gates; add no numeric coverage threshold (D-002). Label real-agent pressure evidence separately from deterministic simulations.
- progress.md is the sole mutable authority. Plans remain immutable definitions; decisions, findings, fix plans, and results are separate records/evidence (D-008).
- This rebuild's global worker_limit is 3. Target runs require their own explicit positive capacity-compatible persisted limit; workers cannot spawn untracked helpers or edit progress.md (D-004).
- Worker returns are only DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, PLAN_CONFLICT, or BLOCKED. Controller validation of plan, result, Git, and checks—not a report—accepts work.
- V2 rejects v1/missing/malformed/unknown/unsupported state read-only, with no migration, replacement, rename, deletion, reinitialization, or dispatch (D-003).
- Formal gates use Critical, Important, and Minor; this high-risk phase receives one independent reviewer after mechanical verification; master review receives exactly two complementary reviewers (D-005–D-007). One non-recursive gate loop has at most three fix/re-review rounds (D-006).
- Runtime state is local/ignored: it survives compaction in the same workspace but not deletion, machine loss, or a fresh clone. Never push, publish, create a PR, or merge into main/master.

## Metadata, interfaces, and batches

Every task has the Phase 1 helper's strict phase-plan metadata: Stable ID, Depends on, Batch, Write scope, and Verification. Write scopes are allowlists. A task checkpoint remains distinct even when compatible tasks share an executor or commit.

- **Consumes from Phase 1:** approved pipeline_state.py schema/field names and documented read-only validate, inspect, next interfaces plus controller-only transitions.
- **Produces for Phases 3–4:** v2 router/reference/template names, worker result/status contract, review/remediation terms, and compact-skill behavior subject to structural validation and full acceptance evidence.
- **No duplicate authority:** prose links to the helper/schema rather than defining aliases; the helper reads phase-plan dependency, behavior, scope, command, and batch metadata rather than copying it into mutable state.

| Batch | Tasks | Start condition | Compatibility |
| --- | --- | --- | --- |
| P2-pressure | P2-T01, P2-T08 | T01 starts after Phase 1; T08 waits for all source tasks | One controller executor retains the pressure-test context/evidence index; it runs RED first and GREEN second, never concurrently. |
| P2-control-plane | P2-T02 | P2-T01 complete | One executor; may dispatch concurrently with P2-planning and P2-execution. |
| P2-planning | P2-T03 | P2-T01 complete | One executor; may dispatch concurrently with P2-control-plane and P2-execution. |
| P2-execution | P2-T04 | P2-T01 complete | One executor; may dispatch concurrently with P2-control-plane and P2-planning. |
| P2-persistence | P2-T05 | P2-T01 complete | One executor; may dispatch concurrently with P2-review. |
| P2-review | P2-T06 | P2-T01 complete | One executor; may dispatch concurrently with P2-persistence. |
| P2-cleanup | P2-T07 | P2-T02–P2-T06 integrated | One executor after every v2 successor exists; it cannot overlap source deletion with its replacement. |

## File structure map

| Path | Responsibility | Action |
| --- | --- | --- |
| plugins/superb/skills/pipeline/SKILL.md | Compact invocation/control-plane router | Rewrite |
| plugins/superb/skills/pipeline/references/planning.md | Discovery, approval, planning, questions/capacity | Create |
| plugins/superb/skills/pipeline/references/execution.md | TDD batches, dispatch, integration, phase verification | Create |
| plugins/superb/skills/pipeline/references/persistence.md | Tracker/result ownership, status/resume/reconciliation | Create |
| plugins/superb/skills/pipeline/references/review.md | Hybrid gates, findings, remediation, master gate | Create |
| plugins/superb/skills/pipeline/templates/progress.md, worker-result.md | Strict tracker and result schema | Phase 1 owns creation; Phase 2 consumes/verifies only |
| plugins/superb/skills/pipeline/templates/decisions.md | Question/answer record | Create |
| plugins/superb/skills/pipeline/templates/findings.md, fix-plan.md | Finding dispositions and one gate-round plan | Rewrite |
| plugins/superb/skills/pipeline/README.md | User-facing v2 operation/guarantees | Rewrite |
| references/{run-state,implement,parallel,fix-loop}.md; templates/{register,implementer-prompt,kit}.md; scripts/task-brief | V1-only orchestration | Delete after replacements exist |

Task kind is authoritative metadata, not a worker choice. P2-T01 and P2-T08 are `artifact`: their ignored pressure records, stable attempt/input identities, and controller validation evidence complete them with integration `N/A` and no fabricated commit. P2-T02 through P2-T07 are `source`: each requires its planned repository change, implementation commit/test evidence, and the separate complete integration ancestry defined in Phase 1. Phase 2 cannot finish until both kinds satisfy their respective contracts.

### Task P2-T01: Capture writing-skills RED controls before source edits
<!-- pipeline-v2-task: id=P2-T01; deps=none; kind=artifact; batch=P2-pressure; order=1; write_scope=tree:docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output; outputs=docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-red-unresolved-choice.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-red-legacy-resume.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-red-conflicting-scopes.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-red-post-commit.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-red-review-gates.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-red-remote-completion.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-no-guidance-01.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-no-guidance-02.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-no-guidance-03.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-no-guidance-04.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-no-guidance-05.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-control-index.md -->

**Stable ID:** P2-T01
**Depends on:** Phase 1 accepted
**Batch:** P2-pressure, order 1, one controller executor retained through P2-T08
**Write scope:** docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-red-*.md and p2-micro-no-guidance-*.md only; no plugin source/template/plan or progress.md edit
**Applicable decisions:** D-002–D-008
**Consumes:** scenario facts only in no-Pipeline fresh contexts; approved design/master/decisions as the expected behavior
**Produces:** observed control behavior/rationalizations for P2-T02–P2-T08

**Acceptance behavior:** Before every Phase 2 instruction/template edit, use superpowers:writing-skills with fresh general-agent contexts containing scenario facts but **no Pipeline skill or Pipeline instructions**. Do not use the v1 Pipeline as the control. Run exactly six full pressure RED scenarios: unresolved required choice; v1/malformed resume; conflicting scopes with spare capacity; accepted Git commit but missing result; final-only versus required gate; requested push/PR completion. Each combines at least three pressures selected from time, sunk cost, authority/user insistence, and exhaustion. Separately, run exactly five no-guidance wording controls of the unresolved-required-choice prompt in fresh contexts, then manually score every sample. Every raw record names task/attempt, exact stimulus digest, worker identity, baseline commit, and validation result. These P2 records are reusable Phase 4 evidence only while their input and relevant tested instructions remain unchanged.

- [ ] **Step 1:** Write the six full-pressure prompts and a failure predicate naming the forbidden decision/write/dispatch/review/advance/remote action; write the one unresolved-choice micro-test prompt separately.
- [ ] **Step 2:** Run one fresh general-agent RED context per full-pressure prompt with no Pipeline skill/instructions; atomically save p2-red-<scenario>.md, labelled real-agent RED.
- [ ] **Step 3:** Run exactly five fresh no-guidance micro-test contexts for the same unresolved-choice wording; save p2-micro-no-guidance-01 through p2-micro-no-guidance-05, and manually score the action and rationalization in every record.
- [ ] **Step 4:** Preserve exact rationalizations, not summaries; these are the only failures later wording addresses.
- [ ] **Step 5:** Write `p2-control-index.md`, mapping all RED/micro-control files to their scenario and intended Phase 4 acceptance use; runtime evidence remains ignored and uncommitted.
- [ ] **Step 6:** Verify RED evidence and source cleanliness, then complete this plan-declared artifact task from the exact raw files, task/attempt identities, stimulus digests, baseline commit, and manual scoring evidence. Record integration `N/A`; do not create or stage an empty commit.

~~~
test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p2-red-*.md' -type f | wc -l)" -eq 6
test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p2-micro-no-guidance-*.md' -type f | wc -l)" -eq 5
test -s docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-control-index.md
git diff --name-only -- plugins/superb/skills/pipeline
~~~

Expected: the exact twelve plan-declared outputs exist (six RED, five micro-controls, and the index), and there is no Pipeline source diff.

### Task P2-T02: Rewrite the compact control-plane router
<!-- pipeline-v2-task: id=P2-T02; deps=P2-T01; kind=source; batch=P2-control-plane; order=1; write_scope=file:plugins/superb/skills/pipeline/SKILL.md; outputs=none -->

**Stable ID:** P2-T02
**Depends on:** P2-T01
**Batch:** P2-control-plane, order 1; may dispatch concurrently with P2-planning/P2-execution
**Write scope:** plugins/superb/skills/pipeline/SKILL.md only
**Applicable decisions:** D-002–D-008
**Consumes:** P2-T01 RED evidence, four fixed reference paths, Phase 1 contract
**Produces:** under-500-line pipeline router

**Acceptance behavior:** Keep valid empty/full, resume, and strictly read-only status modes; reject any other argument without guessing. Use $ARGUMENTS, not indexed placeholders. Route planning to planning.md, dispatch/integration to execution.md, recovery/status/state to persistence.md, formal gates/remediation to review.md, and skill pressure testing to superpowers:writing-skills. Make zero-assumption, durable-file authority, controller-only transitions, worker vocabulary/capacity, no remote mutation, no task formal review, the SDD/executing-plans override, and final master review explicit. Do not revive lanes, Brain Agent, RV/RVJ arithmetic, recursive fix-mode, or interactive finishing.

- [ ] **Step 1:** Map each observed P2-T01 failure to one router rule or one authoritative reference.
- [ ] **Step 2:** Rewrite frontmatter/control plane: retain name: pipeline; use trigger-only description beginning Use when; include the approved v2 execution-handoff override.
- [ ] **Step 3:** Add mode guards and stage-load routing. Resume never creates/replaces incompatible state; unknown choices return allowed status rather than an action.
- [ ] **Step 4:** Verify router shape.

~~~
test "$(wc -l < plugins/superb/skills/pipeline/SKILL.md)" -le 500
rg -n -F 'references/planning.md' plugins/superb/skills/pipeline/SKILL.md
rg -n -F 'references/execution.md' plugins/superb/skills/pipeline/SKILL.md
rg -n -F 'references/persistence.md' plugins/superb/skills/pipeline/SKILL.md
rg -n -F 'references/review.md' plugins/superb/skills/pipeline/SKILL.md
rg -n -F 'superpowers:writing-skills' plugins/superb/skills/pipeline/SKILL.md
rg -n -F 'Do not invoke superpowers:subagent-driven-development' plugins/superb/skills/pipeline/SKILL.md
! rg -n 'references/(run-state|implement|parallel|fix-loop)\.md|REQUIRED SUB-SKILL:.*subagent-driven-development|invoke .*finishing-a-development-branch' plugins/superb/skills/pipeline/SKILL.md
~~~

Expected: four v2 routes, compact file, no retired active mechanism.

- [ ] **Step 5: Commit targeted evidence.**

~~~
git add plugins/superb/skills/pipeline/SKILL.md
git commit -m "feat(pipeline): add v2 control plane"
~~~

### Task P2-T03: Create the planning-stage contract
<!-- pipeline-v2-task: id=P2-T03; deps=P2-T01; kind=source; batch=P2-planning; order=1; write_scope=file:plugins/superb/skills/pipeline/references/planning.md; outputs=none -->

**Stable ID:** P2-T03
**Depends on:** P2-T01
**Batch:** P2-planning, order 1; may dispatch concurrently with P2-control-plane/P2-execution
**Write scope:** plugins/superb/skills/pipeline/references/planning.md only
**Applicable decisions:** D-001, D-002, D-004, D-008
**Consumes:** approved design/master/decisions; Phase 1 metadata boundary
**Produces:** one authority for discovery, approval, planning, questions, and capacity

**Acceptance behavior:** Require superpowers:brainstorming before user-approved design and superpowers:writing-plans for master/phase plans. Only explicit user instructions, recorded answers, approved artifacts, and repo rules resolve choices; otherwise persist/ask and block affected work. Require an explicit positive capacity-compatible worker_limit, at-most-12 genuine tasks, and strict metadata with kind, typed scope, exact artifact outputs (`none` for source), paths/commands, and approval of master plus every phase plan before implementation. Phase 4 owns A-01–A-20 evidence; runtime-state survival limits are disclosed.

- [ ] **Step 1:** Translate P2-T01 unresolved-choice/capacity/remote controls into source-citation-or-stop rules.
- [ ] **Step 2:** Create planning.md with the exact phase metadata plus task `id`, `deps`, `kind`, `batch`, `order`, typed `write_scope`, and exact `outputs`; retain objective, acceptance, commands, and verification in task prose.
- [ ] **Step 3:** Define eligibility: compatible dependent work may share an executor; only independent disjoint scopes may overlap; shared files/prerequisites/capacity block dispatch and never authorize nested workers.
- [ ] **Step 4:** Verify scope.

~~~
rg -n 'zero-assumption|worker_limit|Stable ID|Write scope|at most 12|approval|coverage' plugins/superb/skills/pipeline/references/planning.md
! rg -n 'references/(run-state|implement|parallel|fix-loop)\.md|reviewer_count:|task_rvj:|lane_[a-z]+:' plugins/superb/skills/pipeline/references/planning.md
~~~

Expected: planning requirements are discoverable and no retired scheduling authority remains.

- [ ] **Step 5: Commit targeted evidence.**

~~~
git add plugins/superb/skills/pipeline/references/planning.md
git commit -m "docs(pipeline): add v2 planning contract"
~~~

### Task P2-T04: Create the execution-stage batch/verification contract
<!-- pipeline-v2-task: id=P2-T04; deps=P2-T01; kind=source; batch=P2-execution; order=1; write_scope=file:plugins/superb/skills/pipeline/references/execution.md; outputs=none -->

**Stable ID:** P2-T04
**Depends on:** P2-T01
**Batch:** P2-execution, order 1; may dispatch concurrently with P2-control-plane/P2-planning
**Write scope:** plugins/superb/skills/pipeline/references/execution.md only
**Applicable decisions:** D-002, D-004, D-008
**Consumes:** phase metadata, Phase 1 readiness/transitions/results, P2-T01 conflict/post-commit evidence
**Produces:** one authority for TDD batches, checkpoints, integration, mechanical completion

**Acceptance behavior:** Require superpowers:test-driven-development for testable behavior and superpowers:systematic-debugging for unexpected failures. Phase metadata declares `source`/`artifact` and only `file:`/`tree:` scopes. Readiness is advisory; serialized reservation/start revalidates dependencies, decisions/questions, global capacity, active ownership, and pairwise file/tree overlap before persisting [~], owner, attempt. Workers cannot edit tracker/spawn helpers; they publish atomic attempt results with task checkpoints. Source completion requires commits/checks and later proves every implementation commit is included in the target-branch integration commit. Artifact completion requires exact artifacts/validation with `N/A` integration and no fabricated commit. Failure of a planned integrated suite is implementation repair, never formal review.

- [ ] **Step 1:** Make P2-T01 conflict/post-commit rules observable: spare capacity cannot override conflict; missing evidence is reconciled, not accepted or blindly redispatched.
- [ ] **Step 2:** Create execution.md with required skills, write-before-dispatch order, worker contract, task checkpoints, integration evidence, and controller-only acceptance.
- [ ] **Step 3:** State phase-boundary repair and verification behavior.
- [ ] **Step 4:** Verify scope.

~~~
rg -n 'test-driven-development|systematic-debugging|\[~\]|owner|attempt|task-level checkpoint|integrated HEAD|mechanical' plugins/superb/skills/pipeline/references/execution.md
! rg -n 'per-task review|task reviewer|one fresh implementation agent per task|review before.*phase' plugins/superb/skills/pipeline/references/execution.md
~~~

Expected: TDD/checkpoints explicit; no task formal-review path.

- [ ] **Step 5: Commit targeted evidence.**

~~~
git add plugins/superb/skills/pipeline/references/execution.md
git commit -m "docs(pipeline): add v2 execution contract"
~~~

### Task P2-T05: Create persistence instructions and decisions template; verify Phase 1 state/result templates
<!-- pipeline-v2-task: id=P2-T05; deps=P2-T01; kind=source; batch=P2-persistence; order=1; write_scope=file:plugins/superb/skills/pipeline/references/persistence.md,file:plugins/superb/skills/pipeline/templates/decisions.md; outputs=none -->

**Stable ID:** P2-T05
**Depends on:** P2-T01
**Batch:** P2-persistence, order 1; may dispatch concurrently with P2-review
**Write scope:** plugins/superb/skills/pipeline/references/persistence.md and plugins/superb/skills/pipeline/templates/decisions.md only; Phase 1 owns progress.md and worker-result.md
**Applicable decisions:** D-003, D-004, D-008, D-009
**Consumes:** Phase 1 exact helper/schema/CLI names; durable-artifact design; RED legacy/post-commit evidence
**Produces:** one persistence authority, decisions template, and verification that Phase 1-owned progress/result templates remain aligned

**Acceptance behavior:** All commands validate before write. Controller mutation is lock → read → validate → transition → validate → same-directory temporary write/flush/fsync → atomic replace → directory sync where supported → unlock; no unlocked fallback, stale-lock deletion, truncation, or reinitialization. Distinguish lock failures, pre-replacement failures that preserve the old tracker, and post-replacement synchronization uncertainty that may have applied; the latter re-reads revision/transition identity and never blindly repeats. Status is read-only. Resume is file-first reconciliation of plans, decisions, findings/fix plan, Git/worktree evidence, and every in-progress attempt, including source/artifact evidence and complete integration ancestry. V1 recognition uses actual v1 grammar and emits unchanged/no-dispatch diagnostics. Consume and verify Phase 1's progress/result schemas, including kind, revision/transition identity, source commits versus artifact paths, and `N/A` integration. Create decisions.md with stable question/answer/source/status. State D-009's limits without claiming power-loss durability.

- [ ] **Step 1:** Compare Phase 1 integrated helper/test schema with design. Any mismatch is PLAN_CONFLICT with citations; do not write aliases or a second schema.
- [ ] **Step 2:** Create decisions.md using exact helper field/status spellings; inspect but do not modify Phase 1-owned progress.md and worker-result.md. Workers receive no transition authority.
- [ ] **Step 3:** Create persistence.md as sole status/resume/locking/result/rejection procedure.
- [ ] **Step 4:** Verify contract alignment.

~~~
python3.11 -m unittest discover -s plugins/superb/skills/pipeline/tests -v
rg -n 'pipeline-run/v2|worker_limit|next eligible action|\[ \]|\[~\]|\[\?\]|\[x\]|final-only|required' plugins/superb/skills/pipeline/templates/progress.md
rg -n 'Stable ID|Question|Answer|Sources|Status' plugins/superb/skills/pipeline/templates/decisions.md
rg -n 'run|task|attempt|DONE_WITH_CONCERNS|NEEDS_CONTEXT|PLAN_CONFLICT|BLOCKED|checkpoint|commit|evidence|question' plugins/superb/skills/pipeline/templates/worker-result.md
~~~

Expected: helper suite passes and required strict-schema/result components are visible.

- [ ] **Step 5: Commit targeted evidence.**

~~~
git add plugins/superb/skills/pipeline/references/persistence.md plugins/superb/skills/pipeline/templates/decisions.md
git commit -m "docs(pipeline): add v2 persistence contract"
~~~

### Task P2-T06: Create hybrid review/remediation instructions and templates
<!-- pipeline-v2-task: id=P2-T06; deps=P2-T01; kind=source; batch=P2-review; order=1; write_scope=file:plugins/superb/skills/pipeline/references/review.md,file:plugins/superb/skills/pipeline/templates/findings.md,file:plugins/superb/skills/pipeline/templates/fix-plan.md; outputs=none -->

**Stable ID:** P2-T06
**Depends on:** P2-T01
**Batch:** P2-review, order 1; may dispatch concurrently with P2-persistence
**Write scope:** plugins/superb/skills/pipeline/references/review.md, plugins/superb/skills/pipeline/templates/findings.md, plugins/superb/skills/pipeline/templates/fix-plan.md only
**Applicable decisions:** D-005, D-006, D-007, D-008
**Consumes:** Phase 1 gate/remediation fields; planned review classification/reason; P2-T01 gate control
**Produces:** one review authority plus findings/fix-plan templates

**Acceptance behavior:** final-only phases get no formal phase reviewer. A required gate validates its classification/reason against that phase's approved metadata and has exactly one independent reviewer only after full integration/mechanical verification. The master gate has exactly two D-007 reviewers on the same base/HEAD. Reports must identify the correct gate/assignment/code state; both master reports finish before consolidation. Verified Critical/Important block, approved missing requirements cannot be Minor, all Minors are Fixed/Deferred-with-authority-impact/Rejected-with-evidence. Gate closure is derived from matching reports, required verification, blockers/questions, Minor dispositions, and re-review of every repository-changing fix—never from caller `accepted=True`, an empty findings list, or silence on re-review. Persist immutable gate/round/scope/targets/fix-plan/commits/verification/reports/outcome before dispatch. D-006 remains unchanged.

- [ ] **Step 1:** Turn P2-T01 gate scenario into final-only/required timing and reviewer-count checklist.
- [ ] **Step 2:** Create review.md requiring superpowers:requesting-code-review only for high-risk/master gates and superpowers:receiving-code-review for validation/consolidation.
- [ ] **Step 3:** Rewrite findings/fix-plan templates with stable IDs, three severities, dispositions, immutable gate/round scope, compatible fix batches, verification, and re-review outcome.
- [ ] **Step 4:** Verify terms and v1-policy removal.

~~~
rg -n 'Critical|Important|Minor|Fixed|Deferred|Rejected|round zero|three|same base|same HEAD|Reviewer A|Reviewer B|final-only|required' plugins/superb/skills/pipeline/references/review.md plugins/superb/skills/pipeline/templates/findings.md plugins/superb/skills/pipeline/templates/fix-plan.md
! rg -n 'severity:[[:space:]]*Major|reviewer_count:|recursive_fix_mode:|per_finding_fixer:' plugins/superb/skills/pipeline/references/review.md plugins/superb/skills/pipeline/templates/findings.md plugins/superb/skills/pipeline/templates/fix-plan.md
~~~

Expected: D-005–D-007 vocabulary remains; abandoned mechanisms do not.

- [ ] **Step 5: Commit targeted evidence.**

~~~
git add plugins/superb/skills/pipeline/references/review.md plugins/superb/skills/pipeline/templates/findings.md plugins/superb/skills/pipeline/templates/fix-plan.md
git commit -m "docs(pipeline): add v2 review contract"
~~~

### Task P2-T07: Rewrite README and remove exactly superseded v1 artifacts
<!-- pipeline-v2-task: id=P2-T07; deps=P2-T02,P2-T03,P2-T04,P2-T05,P2-T06; kind=source; batch=P2-cleanup; order=1; write_scope=file:plugins/superb/skills/pipeline/README.md,file:plugins/superb/skills/pipeline/references/run-state.md,file:plugins/superb/skills/pipeline/references/implement.md,file:plugins/superb/skills/pipeline/references/parallel.md,file:plugins/superb/skills/pipeline/references/fix-loop.md,file:plugins/superb/skills/pipeline/templates/register.md,file:plugins/superb/skills/pipeline/templates/implementer-prompt.md,file:plugins/superb/skills/pipeline/templates/kit.md,file:plugins/superb/skills/pipeline/scripts/task-brief; outputs=none -->

**Stable ID:** P2-T07
**Depends on:** P2-T02, P2-T03, P2-T04, P2-T05, P2-T06
**Batch:** P2-cleanup, order 1; runs after every v2 successor is integrated
**Write scope:** plugins/superb/skills/pipeline/README.md; delete only references/run-state.md, references/implement.md, references/parallel.md, references/fix-loop.md, templates/register.md, templates/implementer-prompt.md, templates/kit.md, scripts/task-brief under Pipeline
**Applicable decisions:** D-001–D-010
**Consumes:** design migration map/target tree, fixed v2 paths, RED evidence
**Produces:** v2 user guide and no active v1 orchestration source

**Acceptance behavior:** Explain modes, explicit-question behavior, file authority/resume limits, worker limit/batches/checkpoints, mechanical verification/selective review/master gate, Python 3.11+ helper scope, runtime-state limit, and no-push/no-PR/no-merge policy. Name installed required skills; do not require external /review, interactive finishing, or SDD. Delete only enumerated artifacts after successors exist. Do not touch manifests, setup, CI, tools/check-plugin.py, tools/check-plugin-mutants.sh, or runtime state. Delete task-brief because the master says direct phase-plan references suffice and no batch extractor is planned.

- [ ] **Step 1:** Write README against target v2 tree, distinguishing real-agent pressure evidence from deterministic checks.
- [ ] **Step 2:** Confirm new references/templates exist; if a successor is absent, report BLOCKED and preserve its v1 source.
- [ ] **Step 3:** Delete exactly listed v1 paths.
- [ ] **Step 4:** Verify paths.

~~~
test -f plugins/superb/skills/pipeline/README.md
for f in planning execution persistence review; do test -f "plugins/superb/skills/pipeline/references/$f.md"; done
for f in run-state implement parallel fix-loop; do test ! -e "plugins/superb/skills/pipeline/references/$f.md"; done
for f in register implementer-prompt kit; do test ! -e "plugins/superb/skills/pipeline/templates/$f.md"; done
test ! -e plugins/superb/skills/pipeline/scripts/task-brief
~~~

Expected: all v2 references exist; every listed v1 artifact is absent.

- [ ] **Step 5: Commit targeted evidence.**

~~~
git add plugins/superb/skills/pipeline/README.md
git add -u -- plugins/superb/skills/pipeline/references/run-state.md plugins/superb/skills/pipeline/references/implement.md plugins/superb/skills/pipeline/references/parallel.md plugins/superb/skills/pipeline/references/fix-loop.md plugins/superb/skills/pipeline/templates/register.md plugins/superb/skills/pipeline/templates/implementer-prompt.md plugins/superb/skills/pipeline/templates/kit.md plugins/superb/skills/pipeline/scripts/task-brief
git commit -m "docs(pipeline): remove v1 orchestration artifacts"
~~~

### Task P2-T08: Run GREEN pressure tests and integrated mechanical verification
<!-- pipeline-v2-task: id=P2-T08; deps=P2-T02,P2-T03,P2-T04,P2-T05,P2-T06,P2-T07; kind=artifact; batch=P2-pressure; order=2; write_scope=tree:docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output; outputs=docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-green-unresolved-choice.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-green-legacy-resume.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-green-conflicting-scopes.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-green-post-commit.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-green-review-gates.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-green-remote-completion.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-v2-guidance-01.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-v2-guidance-02.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-v2-guidance-03.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-v2-guidance-04.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-micro-v2-guidance-05.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-guided-index.md -->

**Stable ID:** P2-T08
**Depends on:** P2-T02, P2-T03, P2-T04, P2-T05, P2-T06, P2-T07
**Batch:** P2-pressure, order 2, same controller executor as P2-T01 after all source tasks integrate
**Write scope:** docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-green-*.md and p2-micro-v2-guidance-*.md only; no source/template edit while verifying
**Applicable decisions:** D-002–D-009
**Consumes:** P2-T01 prompts/RED records and all integrated Phase 2 files
**Produces:** paired real-agent GREEN evidence and deterministic verification handoff

**Acceptance behavior:** Re-run each identical full-pressure RED prompt fresh with v2 router and only necessary stage references. Separately run the same unresolved-choice wording with the same v2 guidance variant exactly five times in fresh contexts; manually score each v2-guidance micro-test against each no-guidance control. Every GREEN record names the tested integrated HEAD, exact stimulus/reference digests, task/attempt, worker, and validation result. GREEN passes only where the agent cites an explicit source or returns allowed stop status; preserves incompatible state; queues/blocks conflicting work despite capacity; reconciles rather than accepts/duplicates contradictory post-commit evidence; applies correct review timing/composition; and refuses remote actions. A new rationalization triggers a narrow fix in its owning task and repeat of that scenario. Phase 4 may reuse these records only if the relevant files/digests still match; later behavior edits require the affected scenario only, and any dispatch beyond the approved budget requires user authorization.

- [ ] **Step 1:** Run and atomically save six p2-green-<scenario>.md records with the same full-pressure prompts as RED.
- [ ] **Step 2:** Run and save exactly five p2-micro-v2-guidance-01 through p2-micro-v2-guidance-05 records using the exact unresolved-choice wording and the same v2-guidance variant; manually score all 5+5 micro-test records rather than relying on counts.
- [ ] **Step 3:** Write `p2-guided-index.md`; compare each full-pressure pair and each micro-test set, recording control result, GREEN behavior, source citation, tested HEAD/digests, new rationalization, and its reusable Phase 4 acceptance mapping.
- [ ] **Step 4:** Run integrated deterministic checks on one HEAD.

~~~
python3.11 -m unittest discover -s plugins/superb/skills/pipeline/tests -v
test "$(wc -l < plugins/superb/skills/pipeline/SKILL.md)" -le 500
test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p2-green-*.md' -type f | wc -l)" -eq 6
test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p2-micro-no-guidance-*.md' -type f | wc -l)" -eq 5
test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p2-micro-v2-guidance-*.md' -type f | wc -l)" -eq 5
test -s docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p2-guided-index.md
for f in run-state implement parallel fix-loop; do test ! -e "plugins/superb/skills/pipeline/references/$f.md"; done
for f in register implementer-prompt kit; do test ! -e "plugins/superb/skills/pipeline/templates/$f.md"; done
! rg -n 'references/(run-state|implement|parallel|fix-loop)\.md|templates/(register|implementer-prompt|kit)\.md' plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/README.md plugins/superb/skills/pipeline/references/planning.md plugins/superb/skills/pipeline/references/execution.md plugins/superb/skills/pipeline/references/persistence.md plugins/superb/skills/pipeline/references/review.md
! rg -n 'REQUIRED SUB-SKILL:.*subagent-driven-development|invoke .*finishing-a-development-branch|run .*external /review' plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/references/*.md
rg -n -F 'superpowers:writing-skills' plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/references/*.md
rg -n -F 'superpowers:requesting-code-review' plugins/superb/skills/pipeline/references/review.md
rg -n -F 'superpowers:receiving-code-review' plugins/superb/skills/pipeline/references/review.md
git diff --check
~~~

Expected: helper suite/structural checks pass, six GREEN records exist, deleted v1 routes are absent/unreferenced from active v2 instructions, and legitimate v1 detector/fixture/prohibition vocabulary is not treated as an active route.

- [ ] **Step 5:** Run no-op-aware throwaway-copy simulations. Mutation A removes router's explicit no-guess rule; mutation B changes a required-gate reason to final-only. First assert anchor exists and changed, then run relevant deterministic check and require named failure. Until Phase 3 rewires shared mutation harness, label them Phase 2 simulations and do not edit Phase 3 tooling.
- [ ] **Step 6:** Complete this plan-declared artifact task only after the controller validates every expected raw report, stimulus/reference digest, tested HEAD, and scoring record. Record integration `N/A`; do not create/stage an empty commit. Hand off applicable evidence only. Runtime pressure evidence remains ignored and uncommitted. Failures return to owning task under TDD/systematic-debugging, never formal remediation.

## Phase verification and review gate

**Mechanical verification:** On integrated Phase 2 HEAD: verified P2-T01/P2-T08 artifact evidence with `N/A` integration; complete ancestry/integration evidence for P2-T02–P2-T07; paired RED/GREEN real-agent evidence; Phase 1 helper suite; compact-router/reference checks; active-route scans that exclude legacy detector/fixture evidence and permit explicit prohibitions; helper/template contract checks; two named no-op-aware simulations; and git diff --check. Report unavailable platform/runtime checks rather than claiming them.

**Review gate: required.**

**Exact reason:** The instructions control user escalation, dispatch authority, destructive boundaries, and formal acceptance. A prose ambiguity can cause unauthorized decisions or false completion across every future run.

After mechanical verification, one independent reviewer—not a Phase 2 implementer—reviews the integrated range against design/master/decisions, this plan, P2-T08 evidence, and risk reason. Persist base/HEAD/report/findings/acceptance using Phase 1 tracker/findings contract. Apply D-005–D-006; never introduce task-level review or interactive finishing.

## Self-review and handoff

- [ ] Eight genuine stable-ID tasks (under 12) have exact paths, interfaces, dependencies, behavior, decisions, write scopes, batches, RED/GREEN sequencing, commands, and verification.
- [ ] Phase 1 helper/schema is consumed; Phase 3 validation/CI/mutation-harness and documentation/manifest scope remains untouched.
- [ ] Router, four references, Phase 1-owned progress/result template verification, Phase 2-owned decisions/findings/fix-plan templates, README, v1 deletions, and evidence all map to a task.
- [ ] RED precedes source edits; GREEN follows integration; real-agent and simulation evidence are distinct.
- [ ] The only Phase 2 formal review is the required integrated gate.

Execution uses only approved Pipeline v2 batches: P2-pressure order 1 RED, concurrently eligible P2-control-plane/P2-planning/P2-execution (maximum three tracked workers), P2-persistence/P2-review, P2-cleanup, then P2-pressure order 2 GREEN/mechanical verification and this required review. Do not use generated writing-plans SDD/executing-plans handoff or per-task formal reviews.
