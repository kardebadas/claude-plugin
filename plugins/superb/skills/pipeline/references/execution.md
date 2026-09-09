# Execution: batches, task evidence, and phase verification

Read this reference while selecting implementation batches, starting or resuming
tasks, accepting worker evidence, integrating work, or mechanically verifying a
phase. The approved phase plan defines the work; `progress.md` and the state
helper govern whether an action is currently permitted.

## Required execution skills

- **REQUIRED SUB-SKILL:** Use `superpowers:test-driven-development` for every
  testable behavior and behavior-changing repair: write a meaningful failing
  test, confirm the intended failure, implement the minimum approved behavior,
  and keep the focused test green while refactoring.
- **REQUIRED SUB-SKILL:** Use `superpowers:systematic-debugging` when a test,
  build, integration, or recovery check fails unexpectedly. Establish the cause
  before changing behavior.
- Use `superpowers:dispatching-parallel-agents` only for ready batches that are
  independent under the rules below. Use `superpowers:using-git-worktrees` for
  isolated concurrent writes according to the repository's approved workspace
  convention.

Mechanical failures are unfinished implementation. Repair and rerun the
affected checks; do not manufacture a formal finding or remediation round for
work that has not reached its planned review gate.

## Select work from authoritative facts

Before selecting work, read the approved phase plan, current `progress.md`, and
applicable decisions. A task definition must declare:

- `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, and `outputs` in the
  strict phase-plan metadata;
- objective, expected behavior, acceptance criteria, tests, verification
  commands, and applicable recorded decisions in its task prose.

`kind` is either `source` or `artifact`. A source task has `outputs=none`; an
artifact task names every exact approved output. A worker cannot change the
kind because its implementation happens to produce no diff.

Write scopes use only canonical repository-relative
`file:<path>` and `tree:<directory>` entries. Reject absolute paths, traversal,
globs, empty paths, and unsupported forms rather than deriving ownership. Two
scopes conflict for equal file paths, equal/ancestor tree paths, or a tree path
equal to or containing a file path. Spare capacity never overrides a conflict.

The helper's readiness result is advisory. Immediately before work starts, the
controller serializes the reservation through the state helper and revalidates:

1. the current phase and task state;
2. complete dependency evidence;
3. unresolved questions and review/remediation obligations;
4. active ownership and pairwise overlap among all candidates in the proposed
   reservation;
5. the persisted global `worker_limit` and a fresh, established runtime-capacity
   observation.

Several candidates that were individually ready are not jointly authorized.
If another reservation consumes capacity, a question opens, or ownership
changes, queue the stale candidate and calculate readiness again. The global
limit counts unique active owners across implementation, review, and fix roles;
the same compatible executor may own multiple ordered tasks in one batch
without creating another worker. Workers must not spawn untracked helpers.

## Persist assignment before dispatch

Only the controller changes `progress.md`.

- `start_task(run_dir, *, task_id, owner, attempt)` handles the first start only:
  `[ ]` to `[~]`. It rejects active, blocked, and completed tasks.
- `resume_task(run_dir, *, task_id, prior_attempt, new_owner, new_attempt,
  decision_ref)` handles an answered blocked task only: `[?]` to `[~]`. The
  prior attempt must match, the new attempt must be distinct and unused, and
  `decision_ref` must resolve to an explicit applicable answer with
  `Decision action: task.resume`. Any other unresolved question still blocks
  the task.

Both operations apply the same dependency, capacity, ownership, and typed-scope
guards under the tracker lock and persist `[~]`, owner, and attempt before the
worker is dispatched. An exact transition replay is inert; stale or conflicting
requests fail without mutation. A new attempt does not require a new executor.

Context compaction or a restarted controller is not a blocked-task retry. First
reconcile the existing assignment. A consistent active `[~]` attempt stays the
same attempt.

## Worker assignment and checkpoints

Give every worker the phase-plan path, assigned task IDs and order, workspace
and branch, repository verification rules, and the zero-assumption contract.
The worker may implement multiple compatible tasks sequentially, but each task
remains its own recovery checkpoint. Publish each task's checkpoint/result when
it is available; do not withhold recoverable task state until the whole batch
finishes.

Workers never edit `progress.md`, dispatch other agents, integrate their own
work, or declare a phase accepted. Their only terminal statuses are:

- `DONE`
- `DONE_WITH_CONCERNS`
- `NEEDS_CONTEXT`
- `PLAN_CONFLICT`
- `BLOCKED`

An unresolved question names the affected task, exact question, explicit
sources inspected, work that cannot safely proceed, and useful options and
implications. The controller may cite an existing explicit answer. Otherwise it
records the question, asks the user, leaves affected work blocked, and permits
only demonstrably independent running work to finish.

Publish worker results atomically as immutable attempt evidence. Every result
copies its controller assignment exactly:

```text
run_id + task_id + attempt + owner
```

It also records the planned kind, terminal status, task-level checkpoints,
tests and evidence, source ref/commits or artifact paths, concerns, and any
question/blocking reason. All statuses and both kinds undergo the same four-part
assignment check. Missing/mismatched ownership, a superseded attempt, changed
content under an accepted result identity, or a late result from the prior
attempt is rejected without changing tracker ownership or state. An identical
accepted-result replay is an idempotent no-op.

A worker saying `DONE` is not completion evidence. The controller imports a
result only after validating its immutable identity, approved task definition,
required files, Git facts, and checks. `NEEDS_CONTEXT`, `PLAN_CONFLICT`, and
`BLOCKED` move the current attempt to `[?]`; they do not authorize a guess or an
automatic new attempt.

## Completion and integration are separate facts

### Source tasks

A source start/resume records `baseline:<attempt>@<full-target-SHA>` inside the
same locked assignment transition. A source task completes implementation only
when its resolved source head contains exactly the complete, ordered, nonempty
`baseline..source-head` commit range; every changed path is inside its approved
typed write scope; and one digest-bound `task-test` PASS record matches the run,
task, attempt, source head, and exact ordered task suite. A pre-baseline,
omitted, extra, unrelated, empty, or out-of-scope change fails completion. No
diff or missing commit is an artifact completion or reason for an empty commit.

Integration is recorded separately. For the supported history-preserving path:

1. every recorded implementation commit is an ancestor of the recorded
   integration commit;
2. the integration commit is an ancestor of the designated target branch;
3. one digest-bound `task-integration` PASS record names the run/task and exact
   integration commit.

An unrelated commit that happens to be reachable from the target branch proves
nothing about the task. Squash, rebase, and cherry-pick equivalence are not
supported without a separately approved provenance contract. Downstream work,
recovery, and phase completion all apply the full ancestry predicate.

### Artifact tasks

An artifact task completes only with every exact plan-declared output, stable
task/attempt/owner identity, and applicable validation evidence. Its integration
is truthfully `N/A`; it needs no source commit and must not use an empty commit,
unrelated historical commit, or staged ignored report. Missing or invalid
evidence keeps the task unfinished.

## Reconcile interruption before redispatch

After interruption, validate the run and reconcile the active attempt against
the tracker, immutable worker results, workspace, Git history, and applicable
test evidence before dispatching anything dependent on it.

- A matching, complete worker result is imported once through the normal
  run/task/attempt/owner validator.
- A consistent active owner with no final result remains `[~]`; wait or inspect
  its liveness using the runtime's supported mechanism.
- A commit that appeared immediately before interruption is neither automatic
  success nor grounds to repeat five hours of work. Validate the recorded
  attempt, commit contents and ancestry, and applicable tests; import or
  reconstruct only independently validated evidence that satisfies the normal
  result and completion contracts. Do not infer an absent required result
  field.
- Partial, missing, stale, or contradictory evidence preserves the current
  state and produces a diagnostic or user question. Never interpret it as an
  empty result, mark it complete from a commit message, or blindly redispatch.

Importing recovered evidence uses the same validation as ordinary execution.
Recovery cannot weaken ownership, task kind, artifact, commit, integration, or
idempotency checks.

## Mechanical phase boundary

Every phase receives mechanical verification at the integrated HEAD named by
its plan. Before recording phase verification, confirm:

1. every task has verified `[x]` implementation evidence;
2. every source task satisfies the complete implementation-to-integration-to-
   target ancestry rule;
3. every artifact task has its exact validated outputs and `N/A` integration;
4. every command in the plan's exact ordered phase suite passes on the
   applicable integrated code state; and
5. one digest-bound typed `phase` PASS record matches the run, phase, full
   code-state identity, exact command tuple, applicable inputs, and environment.

Caller-provided command text is checked against the approved tuple; it is not
authority and cannot substitute, omit, duplicate, add, or reorder a command.

A failing planned suite keeps the phase unfinished. Use TDD and systematic
debugging for the smallest approved repair, run targeted checks while working,
then rerun the affected integration and phase checks. Do not advance dependent
work from stale or failed evidence.

Task start, block, resume, result import, and integration transitions refresh
the helper-derived `next_action` in the same locked update; that summary never
overrides the underlying facts. Completing the last task does not advance the
phase. After phase verification and any required phase gate have satisfied the
approved predicates, the controller uses the explicit `advance_phase` helper
transition. Advancing the last phase routes to the mandatory master gate, not
project completion.

Do not dispatch formal reviewers at task boundaries. A `final-only` phase
continues after mechanical acceptance with no phase reviewer. A phase whose
approved metadata says `required` may enter its one formal phase gate only
after the whole phase is implemented, integrated, and mechanically verified.
Formal phase and master-gate behavior belongs to `review.md`; task completion
does not open it.
