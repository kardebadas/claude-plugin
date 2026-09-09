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

## Rebuild-only bootstrap

This rebuild cannot invoke the old Pipeline or the unfinished v2 Pipeline to authorize their replacement. Until the tested v2 helper functions exist, the coding-session controller directly follows the approved files using the individual Superpowers skills named above. It keeps the existing rebuild `progress.md` as the only live tracker, writes task/attempt/commit/test checkpoints before and after work, and makes no call to a helper API that has not yet been implemented.

P1-01 through P1-04 use this bounded bootstrap. P1-01 provides the strict tracker/result and phase-plan metadata parsers; P1-03 provides atomic replacement; P1-04 consumes those tested contracts to provide task transitions. After all three capabilities pass their targeted tests and P1-04's commit/evidence is manually checkpointed, the controller creates an immutable bootstrap-evidence snapshot under `agent-output/`, renders one canonical v2 replacement for the same `progress.md`, validates it, acquires the new run lock, and atomically replaces that tracker in place. The canonical tracker seeds the already verified P1 checkpoints and their Git/test evidence; it does not replay transitions, call the not-yet-implemented P1-06 result import, or create another live tracker. P1-05 is admitted from the approved dependency graph by the controller, then the tested scheduler governs later reservations; P1-06 enables normal result import. This one-time procedure exists only for this rebuild and is not a v1 migration or a future-run code path.

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

- `pipeline-run/v2` protocol marker, required tracker-format revision, schema-adoption identity, run ID, base commit, target branch, worker limit, filesystem classification/type/fingerprint/acknowledgement, artifact paths, monotonic revision, and last transition identity;
- current phase/batch and next eligible action;
- one row per task with plan-declared `source` or `artifact` kind; `[ ]`, `[~]`, `[?]`, or `[x]` implementation state; owner/attempt; result; commits or artifact evidence; integration; verification; and question reference;
- one row per phase with phase verification state/evidence and `final-only` or required formal review classification/reason;
- gate rows for high-risk phase and master reviews, reviewed base/HEAD, reviewers/reports, acceptance state, and open findings;
- remediation rows with immutable gate/round identity, active and released fixer assignments, fixing/re-review lifecycle, targeted findings, fix plan, commits, verification, and re-review outcome.

Dependencies, expected behavior, task kind, write scope, exact ordered verification commands, planned batch membership, and exact artifact outputs remain in the referenced phase plan. One adjacent phase-suite comment is required after phase metadata, and one adjacent task-suite comment is required after each source-task comment; both use nonempty unique JSON string arrays. Artifact tasks have no source-task suite. Scope entries use only `file:<repository-relative-path>` and `tree:<repository-relative-directory>`; traversal, absolute paths, empty paths, and other forms are rejected. File/file equality, tree ancestry, and tree/file containment are conflicts. Source tasks declare `outputs=none`; artifact tasks declare an exact output-file list contained by their scopes. The same repository-relative identity is used across worktrees. The helper reads this strict metadata when determining readiness; it does not duplicate task definitions into mutable state.

Only the controller invokes transitions. Workers publish attempt-scoped result files atomically; results are evidence, not state. Each result carries the exact controller-assigned run/task/attempt/owner identity, and the shared import/reconciliation validator rejects missing, mismatched, superseded, or conflicting identity without changing tracker ownership. Every new source start/resume records the exact target-branch baseline under the locked assignment. For a plan-declared `source` task, completion requires the complete ordered nonempty baseline-to-source commit range, all changed paths inside its typed scope, and one digest-bound typed `task-test` PASS record matching the run/task/attempt/source HEAD and approved task suite; later integration remains separate. For a plan-declared `artifact` task, completion requires the named artifact(s) and validation evidence and records integration as `N/A`; it never fabricates an empty/unrelated commit. A worker cannot change the declared kind, and a source task with no required diff/commit fails. Exact accepted-result reimport is idempotent only when its persisted identity and content match. Stale/conflicting attempts cannot regress state or increment counters twice.

History-preserving integration is the single planned integration proof: every recorded implementation commit must be an ancestor of the recorded integration commit, that integration commit must be an ancestor of the designated target branch, and one digest-bound typed `task-integration` PASS record must name the exact run/task/integration commit. Rewritten-history equivalence (squash, rebase, or cherry-pick provenance) is unsupported unless the user later explicitly approves a mapping contract; reachability of an unrelated target commit or a SHA embedded in arbitrary prose is never enough. Dependency readiness, resume, and phase completion apply the same predicate. Artifact tasks satisfy their dependency only after verified completion and truthful `N/A` integration.

Every mutation first reads and validates the schema and filesystem suitability without creating the lock, then performs lock → re-read/revalidate → transition → validate → same-directory temporary write → flush/fsync → atomic replace → directory sync where supported → unlock. Lock acquisition/unavailability, pre-replacement write failures, replacement failures, and post-replacement synchronization uncertainty are distinct outcomes. Before replacement, the old tracker remains authoritative and only this invocation's temporary file may be cleaned. After replacement, a later failure is reported as `update may have applied`; the helper does not claim unchanged bytes, roll back, or blindly retry. It re-reads under the lock and reconciles the stable transition identity/revision so retries cannot duplicate completion or remediation increments. Lock contention is bounded and returns a busy diagnostic. The helper never falls back to unlocked writes, guesses after malformed input, creates a lock beside incompatible state, deletes another process's lock, or truncates/reinitializes uncertain state.

For a new ordinary v2 run, initialization may create `progress.md` inside an already-created run directory only when `progress.md` is absent, the directory contains only the explicitly supplied approved artifact paths, and no schema-like or legacy tracker is present. It never overwrites an existing tracker or unrelated file. Existing v2 is resumed; recognized v1 and missing/malformed/unknown tracker state are rejected unchanged. The rebuild-only in-place bootstrap conversion above is a controller procedure, not this initialization API.

Supported concurrency is cooperating processes on one host and a local filesystem with working OS locks and same-filesystem replacement. Before mutation, a standard-library tri-state probe records the mount/volume type and fingerprint: known network/distributed types are rejected, supported local types proceed, and unknown types require an explicit decision reference bound to that fingerprint. A changed fingerprint requires reconciliation. Linux reads `/proc/self/mountinfo`; macOS uses fixed `/usr/bin/stat` filesystem-type output; Windows uses `ctypes` volume APIs and rejects UNC/remote drives. Linux and macOS use POSIX locking. The Windows standard-library path remains labeled “Implemented; simulation-tested; native Windows verification pending” until native tests cover contention, replacement, interruption, and release. Network/distributed filesystems and cross-host synchronization are outside the guarantee. The helper distinguishes writer exclusion, atomic visibility, process-interruption recovery, and power-loss durability.

The active pre-release rebuild alone may use D-017's explicit one-time format adoption after copied-fixture tests pass. It requires the exact run ID, source revision and SHA-256, unique adoption identity, quiescent task/reviewer state, verified active fixer mapping, the ordinary lock, complete old-format validation, complete new-format validation, and atomic replacement of the same `progress.md`. Its snapshot/receipt are immutable evidence, not live trackers. Ordinary validate/resume/mutation accepts only the new strict format; adoption is not invoked by resume and adds no v1 or general migration support.

## Schema and resume behavior

Every v2 command validates the schema before writes or dispatch. Resume reads the spec, master plan, tracker, active phase plan, decisions/open questions, findings/fix plan when active, Git/worktree state, and worker results. It reconciles every `[~]` attempt before redispatch:

- verified accepted result and commit: import once and continue;
- running worker with consistent ownership: wait or continue independent local work;
- partial/missing evidence: preserve state and diagnose;
- unresolvable repository/state contradiction: ask the user.

Legacy v1 is recognized by the actual repository format: the legacy tracker heading/current-state lane grammar and RV/RVJ task-adjacent review records, not merely absence of the v2 marker. Recognized v1, missing markers, malformed schemas, and unknown/unsupported versions are read-only failures. A v1 diagnostic identifies the run path, says v2 cannot resume it, confirms no files changed, and directs the user to a compatible v1 or a separately approved fresh v2 run. Resume never migrates, overwrites, renames, deletes, reinitializes, or silently replaces incompatible state.

`next_action` is a persisted derived summary, never independent authority. One shared derivation reads approved phase/task definitions and authoritative task, integration, question, verification, review, remediation, and scheduling facts after every relevant successful transition; the fact change and refreshed summary are one locked atomic update. Read-only commands may diagnose stale summaries but never rewrite them. The explicit controller-only `advance_phase(run_dir, *, completed_phase_id, next_phase_id)` validates all completed-phase acceptance facts and the approved immediate successor/dependencies before advancing. The last phase derives the mandatory master-review action rather than completion.

## Planning

The full master plan is written before implementation. It lists every phase, dependencies, phase-plan path, mechanical verification, and review classification. One planning agent expands each phase with `superpowers:writing-plans`; independent expansions run up to the global worker limit. The user-approved v2 execution header replaces the installed skill's incompatible SDD/executing-plans handoff.

Every phase plan contains at most 12 genuine tasks. Each stable task records objective/behavior, files, dependencies, acceptance criteria, test/verification commands, applicable decisions, write scope, and batch compatibility. Shared interfaces, coverage policy, resource limit, and high-risk gates are settled before executable-plan approval.

## Scheduling and batches

Each run requires an explicit positive `worker_limit`. If absent, invalid, above detected capacity, or based on unknown capacity, the controller asks the user before first dispatch. The approved value survives resume. It applies globally across phase planners, implementers, fixers, and reviewers; workers cannot spawn untracked helpers.

The scheduler validates the authoritative current phase, dependencies, task state, approved decisions, planned batch ordering, typed file/tree scope, active workers, open gates/remediation, and detected capacity. Readiness is advisory: actual reservations/starts are serialized under the tracker lock and revalidate questions, dependencies, pairwise candidate scopes, current ownership, and capacity. One shared count uses unique active task owners, active gate reviewers, and active remediation fixers; role-specific rows preserve released ownership history without a generic registry. Several individually ready candidates cannot all reserve if they conflict with one another or a prior reservation consumes capacity. Compatible dependent tasks may stay with one executor in order. Independent, disjoint batches may run concurrently. Capacity is a ceiling, never a reason to dispatch unnecessary work or early/duplicate review.

The controller binds one fast, side-effect-free runtime-capacity provider to the canonical run directory. Task starts/reservations, phase/master review starts, remediation starts, and re-review reservations query it inside the same tracker lock as the assignment transition, so a stale readiness observation or caller number is never dispatch authority. Missing, unknown, failed, malformed, or insufficient capacity fails without mutation; recovery rebinds/re-detects capacity before new work and never persists a transient observation as continuing authority. The shared active-owner guard remains the one capacity rule for task, reviewer, and fixer reservations.

The controller persists `[~]`, owner, and attempt before dispatch. Every worker result copies the assigned run, task, attempt, and owner identities; import validates all four together under the tracker lock for every status and task kind and never rewrites tracker ownership from incoming evidence. Workers receive the zero-assumption contract and return `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `PLAN_CONFLICT`, or `BLOCKED`, with task-level checkpoints inside a multi-task batch. A worker report alone never proves completion.

When a worker raises a question, the controller either cites an existing explicit answer or records/asks the user. Dependent dispatch/integration stops; independent running work may finish. The answer is persisted and affected plans are updated transparently before resume. A decision that authorizes a controller transition has exactly one closed-vocabulary `Decision action`: `task.resume`, `review.resolve-question`, `filesystem.authorize`, `remediation.start-round`, or `none`. The helper matches the exact action required by the transition plus its existing scope/state/identity metadata; it never infers authority from words in the human-readable answer. Missing, duplicated, unknown, wrong-purpose, or fieldless historical actions grant no new authority.

`start_task` is first-start only (`[ ] → [~]`). An answered blocked task uses the distinct D-011 `resume_task` transition (`[?] → [~]`) with its blocked prior attempt, a distinct unused new attempt, new owner, and a decision reference that the helper verifies as resolved and applicable. Both paths share dependency, capacity, ownership, and typed-scope start guards and persist before dispatch. Resume preserves prior attempt/result/question/evidence references, rejects late prior-attempt results, and is idempotent for an identical already-applied transition. Session/context recovery reconciles the existing attempt and does not itself create a new one.

## Verification, review, and remediation

Target projects retain explicit repository coverage requirements. If no coverage policy exists, planning asks whether the user wants a numeric threshold and its scope or behavior-focused tests without a number. Coverage never substitutes for meaningful assertions.

Phase completion requires every source task implemented with typed task evidence and proven integrated, every artifact task completed with validated artifacts and `N/A` integration, and the plan's exact ordered phase suite passing on the recorded integrated HEAD. Phase proof is one digest-bound typed `phase` PASS record matching run, phase, HEAD, command tuple, inputs, and environment; caller command text is checked but is not authority. Failed verification keeps the phase unfinished and triggers TDD/systematic repair, not formal review.

An ordinary phase uses `Review gate: final-only`. A required high-risk phase uses `Review gate: required` plus a specific consequence-based reason. One independent reviewer examines the fully integrated, mechanically verified phase. Dependent phases wait until the gate passes.

The final master gate always reviews the complete integrated feature against the approved design and plan at a recorded base/HEAD. Exactly two independent reviewers share that range: Reviewer A emphasizes requirements/behavior/user decisions; Reviewer B emphasizes integration/reliability/recovery/concurrency/security/test quality. Both reports finish before consolidation.

Both gate types use `Critical`, `Important`, and `Minor`. Verified Critical/Important findings block. A missing approved requirement cannot be Minor. Every Minor is Fixed, Deferred with authority/impact, or Rejected with evidence. Under D-029 (recorded for the recovery run as D-002), every newly published strict report adds an `outcomes` JSON object mapping its finding IDs to exactly `Open` or `Resolved`; initial findings are `Open`, while every active re-review assignment must conclude every existing gate finding exactly once. Any `Open`, missing conclusion, or disagreement blocks. Already digest-sealed historical five-field reports remain lineage-only and cannot be submitted as new evidence. Gate closure reads only the tracker-referenced authoritative findings ledger and is derived from evidence, never a caller-supplied boolean or bare `Resolved`: required reports must name the correct gate and reviewed code-state edge; the initial reports are persisted by content digest and each finding introduction is bound to its gate/ID/severity and introducing report digest(s); verification references must resolve to typed digest-bound PASS artifacts that record the exact code state and match the verification already recorded by the phase or active remediation round; confirmed blockers need evidence-backed Fixed or Rejected dispositions; Rejected evidence must resolve to an artifact with an exact structured `Finding: <ID>` field and one nonempty `Rationale:` field; no unresolved acceptance question may remain; every Minor needs a disposition; and every repository-changing fix must be bound to the exact targeted remediation round that actually resolved it, strict post-review commit, integrated fix HEAD, and applicable re-review. Prefix/substring identity is never evidence. A finding listed in that round's persisted `remaining-blockers` outcome cannot be claimed Fixed by that historical round. `gate.base` and the sealed initial `gate.reports` remain the immutable initial review anchor, while `gate.head` is the latest fully evaluated reviewed HEAD. Re-review validates the complete contiguous chain through prior completed remediation rows before accepting the active edge; it never rewrites or reinterprets the initial reports against the rolling HEAD. Evidence-changing replays are rejected. A final-only phase cannot open a phase-review gate; the master gate separately enforces its two reviewer assignments. Reviewers validate applicable supplied full-suite evidence and run focused adversarial probes; independent evaluation does not require automatic duplication of an applicable full suite.

Remediation is one non-recursive shared loop per gate. The initial review is round zero. Up to three fix/re-review rounds may run. Each targets exactly the current open Critical/Important findings (Minors may be dispositioned in the same fix plan but cannot manufacture blocker progress), persists its identity and scope before dispatch, consolidates all reports, resolves questions, writes one fix plan, implements compatible batches, verifies, and re-reviews the same gate. Parallel fix workers share one round. Each completed round records exactly one remaining-blocker outcome for comparison: `none` or unique known finding IDs, never empty, duplicated, unknown, or mixed with the sentinel. Missing or ambiguous outcomes invalidate ordinary resume/evaluation rather than being guessed. The exact active rebuild's pre-contract Round 1 omission is reconciled once under D-019 from its immutable report package, without creating automatic future-run repair or migration. Stop early on acceptance, no re-review-confirmed targeted blocker progress, a previously resolved blocker reappearing/oscillating, conflicts, or an unresolved question. Round three with blockers remains failed and asks the user; a finite extension requires the exact `remediation.start-round` action bound to the run, source revision, gate state/question, predecessor authority, round, and finding set, and never erases history. D-021, D-022, D-023, and D-025 authorize exactly Rounds 4, 5, 6, and 7 of this rebuild's existing `phase-01` gate; none authorizes the following round or alters the three-round default for any future gate. Under D-024, each remediation uses targeted regressions during the fix, then one required full phase suite on the committed integrated batch; a later relevant change invalidates only affected evidence.

## Test and evidence strategy

This rebuild uses behavior-focused tests with no new numeric coverage threshold. Existing quality gates remain. Where existing coverage tooling is available, line/branch results are diagnostic only and uncovered critical paths are inspected.

Automated Python unit/integration/regression tests cover strict parse/round trip, malformed input, both task kinds, legal transitions, lock contention across real processes, failures before and after replacement, idempotent retry after uncertain replacement, Git integration ancestry/reconciliation, schema rejection, typed-scope overlap, stale readiness/reservations, global worker limits, task-level batch checkpoints, phase verification, phase-specific review reasons, evidence-derived review acceptance, review/remediation gates, and final completion policy. Every mechanical rule includes passing and intended failing cases; mutations assert that they changed the target and were killed for the named reason.

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
