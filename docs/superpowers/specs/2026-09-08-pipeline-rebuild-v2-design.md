# Superb Pipeline v2 Rebuild Design

**Date:** 2026-09-08
**Status:** Proposed for executable-plan approval
**Base commit:** `8348959d1b201a873c68512642a0eb8e5754eaa8`
**Feature branch:** `feat/pipeline-rebuild-v2`
**Runtime decision log:** `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/decisions.md`

## Purpose

Rebuild `superb:pipeline` as a compact orchestration layer around installed Superpowers skills. The controller must never decide an unresolved requirement for the user, and it must recover its roadmap and exact next action from durable files and Git evidence after compaction or interruption. V2 reduces redundant dispatch, repeated context loading, duplicated full-suite verification, and formal review volume without weakening TDD, mechanical phase verification, required high-risk reviews, or the mandatory final master review.

## Governing invariants

1. Explicit user instructions, recorded answers, approved design/plans, and repository rules are the only sources that can resolve a required choice. An unanswered or conflicting decision blocks affected work and reaches the user.
2. The approved design, master plan, every phase plan, `progress.md`, `decisions.md`, `findings.md`, fix plans, and evidence files live on disk. Conversation memory is never authoritative.
3. `progress.md` is the sole authoritative execution tracker. Plans define work; the tracker records state and references definitions without copying them.
4. A task is a planning/recovery checkpoint, a phase is a mechanical-verification boundary, a batch is an implementation-dispatch unit, and the project is the mandatory final formal-acceptance boundary.
5. Every testable behavior is implemented through red-green-refactor. Targeted checks run within batches, approved suites at integration/phase boundaries, and the full approved suite at final verification.
6. Every phase receives mechanical verification. Only phases explicitly classified high-risk receive a formal phase review. The integrated project always receives a formal master review.
7. No run pushes, publishes, creates a PR, or merges into `main`/`master`. Successful completion leaves a clean, committed feature branch.

## Composition and conflicts

Pipeline delegates responsibilities to the installed contracts:

| Responsibility | Required skill |
| --- | --- |
| Design investigation and user approval | `superpowers:brainstorming` |
| Master and phase planning | `superpowers:writing-plans` |
| Independent concurrent batches | `superpowers:dispatching-parallel-agents` |
| Isolated feature/batch workspaces | `superpowers:using-git-worktrees` |
| Implementation and behavior-changing fixes | `superpowers:test-driven-development` |
| Unexpected failures | `superpowers:systematic-debugging` |
| High-risk and master review dispatch | `superpowers:requesting-code-review` |
| Finding validation and response | `superpowers:receiving-code-review` |
| Fresh completion evidence | `superpowers:verification-before-completion` |
| Skill pressure testing | `superpowers:writing-skills` |

The generated `writing-plans` header and handoff normally recommend `superpowers:subagent-driven-development` or `superpowers:executing-plans`. V2 explicitly replaces that handoff with its approved batch scheduler. It must not invoke `superpowers:subagent-driven-development`, invent an implementation-only version of it, or inherit its per-task review workflow. It also must not use an interactive finishing menu. These are explicit user overrides, not silent contract omissions.

## Durable artifact layout

Each target project follows an explicit repository convention when one exists; otherwise:

```text
docs/superpowers/
├── specs/<feature>-design.md
├── plans/<feature>-master-plan.md
├── plans/<feature>/phase-01.md
└── runs/<run-id>/
    ├── progress.md
    ├── decisions.md
    ├── findings.md
    ├── fix-plan-<gate>-r<n>.md
    └── agent-output/<attempt-or-review>.md
```

The run stores resolved absolute/project-relative paths so a linked worktree can find the same artifacts. Runtime state remains local according to repository policy. V2 must state that ignored/untracked state survives compaction in the same workspace but not deletion, machine loss, or a fresh clone.

## Canonical tracker and helper

`plugins/superb/skills/pipeline/scripts/pipeline_state.py` is a Python 3.11+ standard-library CLI and importable module. It supports one documented Markdown tracker format rather than general Markdown. `plugins/superb/skills/pipeline/templates/progress.md` contains the schema.

The tracker has:

- `pipeline-run/v2` schema marker, run ID, base commit, target branch, worker limit, and artifact paths;
- current phase/batch and next eligible action;
- one row per task with `[ ]`, `[~]`, `[?]`, or `[x]` implementation state plus owner/attempt, result, commits, integration, verification, and question reference;
- one row per phase with phase verification state/evidence and `final-only` or required formal review classification/reason;
- gate rows for high-risk phase and master reviews, reviewed base/HEAD, reviewers/reports, acceptance state, and open findings;
- remediation rows with immutable gate/round identity, targeted findings, fix plan, commits, verification, and re-review outcome.

Dependencies, expected behavior, write scope, test commands, and planned batch membership remain in the referenced phase plan. The helper reads the phase plan's strict metadata when determining readiness; it does not duplicate those definitions into mutable state.

Only the controller invokes transitions. Workers publish attempt-scoped result files atomically; results are evidence, not state. The controller validates the result, plan, Git commits, and required checks before accepting completion. Reimport is idempotent. Stale/conflicting attempts cannot regress state or increment counters twice.

Every mutation uses a stable run-local lock file and performs lock → read → validate → transition → validate → same-directory temporary write → flush/fsync → atomic replace → directory sync where supported → unlock. Lock contention is bounded and returns a busy diagnostic. The helper never falls back to unlocked writes, guesses after malformed input, deletes another process's lock, or truncates/reinitializes uncertain state.

Supported concurrency is cooperating processes on one host and a local filesystem with working OS locks and same-filesystem replacement. Linux and macOS use POSIX locking. The Windows standard-library path is adapted only after inspecting the existing repository implementation and remains labeled “Implemented; simulation-tested; native Windows verification pending” until native tests cover contention, replacement, interruption, and release. Network/distributed filesystems and cross-host synchronization are outside the guarantee. The helper distinguishes writer exclusion, atomic visibility, process-interruption recovery, and power-loss durability.

## Schema and resume behavior

Every v2 command validates the schema before writes or dispatch. Resume reads the spec, master plan, tracker, active phase plan, decisions/open questions, findings/fix plan when active, Git/worktree state, and worker results. It reconciles every `[~]` attempt before redispatch:

- verified accepted result and commit: import once and continue;
- running worker with consistent ownership: wait or continue independent local work;
- partial/missing evidence: preserve state and diagnose;
- unresolvable repository/state contradiction: ask the user.

Legacy v1 is recognized by the actual repository format: the legacy tracker heading/current-state lane grammar and RV/RVJ task-adjacent review records, not merely absence of the v2 marker. Recognized v1, missing markers, malformed schemas, and unknown/unsupported versions are read-only failures. A v1 diagnostic identifies the run path, says v2 cannot resume it, confirms no files changed, and directs the user to a compatible v1 or a separately approved fresh v2 run. Resume never migrates, overwrites, renames, deletes, reinitializes, or silently replaces incompatible state.

## Planning

The full master plan is written before implementation. It lists every phase, dependencies, phase-plan path, mechanical verification, and review classification. One planning agent expands each phase with `superpowers:writing-plans`; independent expansions run up to the global worker limit. The user-approved v2 execution header replaces the installed skill's incompatible SDD/executing-plans handoff.

Every phase plan contains at most 12 genuine tasks. Each stable task records objective/behavior, files, dependencies, acceptance criteria, test/verification commands, applicable decisions, write scope, and batch compatibility. Shared interfaces, coverage policy, resource limit, and high-risk gates are settled before executable-plan approval.

## Scheduling and batches

Each run requires an explicit positive `worker_limit`. If absent, invalid, above detected capacity, or based on unknown capacity, the controller asks the user before first dispatch. The approved value survives resume. It applies globally across phase planners, implementers, fixers, and reviewers; workers cannot spawn untracked helpers.

The scheduler validates dependencies, task state, approved decisions, planned batch ordering, file/write scope, active workers, and detected capacity. Compatible dependent tasks may stay with one executor in order. Independent, disjoint batches may run concurrently. Shared-file or prerequisite conflicts prevent parallel eligibility. Capacity is a ceiling, never a reason to dispatch unnecessary work or early/duplicate review.

The controller persists `[~]`, owner, and attempt before dispatch. Workers receive the zero-assumption contract and return `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `PLAN_CONFLICT`, or `BLOCKED`, with task-level checkpoints inside a multi-task batch. A worker report alone never proves completion.

When a worker raises a question, the controller either cites an existing explicit answer or records/asks the user. Dependent dispatch/integration stops; independent running work may finish. The answer is persisted and affected plans are updated transparently before resume.

## Verification, review, and remediation

Target projects retain explicit repository coverage requirements. If no coverage policy exists, planning asks whether the user wants a numeric threshold and its scope or behavior-focused tests without a number. Coverage never substitutes for meaningful assertions.

Phase completion requires every task implemented with evidence, integrated, and the planned phase suite freshly passing on the integrated HEAD. Failed verification keeps the phase unfinished and triggers TDD/systematic repair, not formal review.

An ordinary phase uses `Review gate: final-only`. A required high-risk phase uses `Review gate: required` plus a specific consequence-based reason. One independent reviewer examines the fully integrated, mechanically verified phase. Dependent phases wait until the gate passes.

The final master gate always reviews the complete integrated feature against the approved design and plan at a recorded base/HEAD. Exactly two independent reviewers share that range: Reviewer A emphasizes requirements/behavior/user decisions; Reviewer B emphasizes integration/reliability/recovery/concurrency/security/test quality. Both reports finish before consolidation.

Both gate types use `Critical`, `Important`, and `Minor`. Verified Critical/Important findings block. A missing approved requirement cannot be Minor. Every Minor is Fixed, Deferred with authority/impact, or Rejected with evidence. A gate passes only with no unresolved blockers/questions, all repository-changing fixes verified and re-reviewed, all Minors disposed, and required checks green.

Remediation is one non-recursive shared loop per gate. The initial review is round zero. Up to three fix/re-review rounds may run. Each persists its identity and scope before dispatch, consolidates all reports, resolves questions, writes one fix plan, implements compatible batches, verifies, and re-reviews the same gate. Parallel fix workers share one round. Stop early on acceptance, no confirmed blocker progress, oscillation, conflicts, or an unresolved question. Round three with blockers remains failed and asks the user; a finite extension requires explicit authorization and never erases history.

## Test and evidence strategy

This rebuild uses behavior-focused tests with no new numeric coverage threshold. Existing quality gates remain. Where existing coverage tooling is available, line/branch results are diagnostic only and uncovered critical paths are inspected.

Automated Python unit/integration/regression tests cover strict parse/round trip, malformed input, legal transitions, lock contention across real processes, interruption, replacement failure, idempotent/stale result import, Git reconciliation, schema rejection, scheduling/dependency/write conflicts, global worker limits, task-level batch checkpoints, phase verification, review/remediation gates, and final completion policy. Every mechanical rule includes passing and intended failing cases; mutations assert that they changed the target and were killed for the named reason.

`superpowers:writing-skills` supplies RED/GREEN pressure testing: representative fresh-context controls run without v2 instructions, then the same scenarios run with v2. Scenarios exercise user escalation, file-first recovery, post-commit reconciliation, batching/conflict safety, review/remediation gates, and no-push completion. Actual agent runs are distinguished from deterministic simulations. The full 20-scenario acceptance matrix maps each required behavior to automated or real-agent evidence and discloses unavailable native/runtime tests.

Performance reporting compares like-for-like measurements where possible: helper/test elapsed time, mutation-suite runs, dispatch counts in pressure scenarios, heavy verification counts, orchestrator turns, and instruction word/line size. Historical v1 evidence is labeled historical; waiting for user answers is separated. No speed claim is made without comparable evidence.

## Skill structure

Target shape:

```text
plugins/superb/skills/pipeline/
├── SKILL.md                    # compact control plane, target under 500 lines
├── README.md
├── references/
│   ├── planning.md
│   ├── execution.md
│   ├── persistence.md
│   └── review.md
├── scripts/
│   └── pipeline_state.py
├── templates/
│   ├── progress.md
│   ├── decisions.md
│   ├── findings.md
│   ├── fix-plan.md
│   └── worker-result.md
└── tests/
    ├── test_pipeline_state.py
    └── fixtures/
```

Exact file names may be refined only in the approved executable plan before implementation. Active instructions keep one authority per rule and load stage-specific references only when active. Historical debugging narrative stays in history, not the skill.

## Migration map

### KEEP

- namespace/frontmatter/manifest/marketplace/UTF-8 validation;
- zero-assumption escalation and explicit decision persistence;
- project-local run state and ignore policy;
- write-before-dispatch and Git-backed recovery;
- status as strictly read-only;
- no task-level formal review;
- worker status vocabulary and focused result artifacts;
- clean-copy, no-op-aware mutation methodology;
- protection against indexed invocation placeholders and leaked project-specific paths;
- mailbox wait behavior when workers remain outstanding.

### ADAPT

- v1 assumptions register → `decisions.md` questions/answers with stable IDs;
- prose tracker and lane grammar → strict v2 tracker plus deterministic transitions;
- one-worker-per-task waves → planned multi-task batches with task checkpoints;
- task-brief extractor → batch/phase-plan evidence contract or removal if direct plan references suffice;
- universal phase review → mechanical verification plus selected high-risk review;
- recursive fix mode/counters → one bounded per-gate remediation state;
- review artifacts/coverage tables → exact reviewer assignments/base/HEAD/reports and finding dispositions without reviewer arithmetic;
- v1 fixtures and linter sections → v2 schema/transition/scheduler/recovery/gate fixtures and unit tests;
- README/setup/manifests/CI → Python 3.11 Pipeline dependency and v2 workflow/version.

### DELETE

- mandatory RV/RVJ line machinery and `ceil(N/5)`/M/C reviewer arithmetic;
- mandatory formal review after every phase;
- recursive `fix-mode` invocation and per-finding loop escape routes;
- Brain Agent decision-making;
- lane/state layers retained only to support old reviewer joins;
- one fresh implementation agent per task;
- old semantic tests/mutants that only enforce abandoned mechanisms;
- external `/review` dependency and interactive finishing workflow.

Valid regression coverage is rewritten around the preserved safety property rather than discarded solely because its old representation changed.

## Completion contract

Fresh plugin validation, unit/integration/fixture/mutation suites, pressure scenarios, relevant build/lint checks, resume/recovery checks, requirements audit, and Git/worktree checks must pass on the final HEAD. Intended changes are committed on `feat/pipeline-rebuild-v2`; the branch is clean and integrated. Runtime artifacts remain saved locally and consistent. Remote, PR state, and `main` remain unchanged.
