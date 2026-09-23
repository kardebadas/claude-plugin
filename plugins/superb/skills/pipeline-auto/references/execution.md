# Execution: stages 08–10

Load while selecting work, dispatching implementers, running the per-task gate,
integrating, verifying a phase, or debugging.

**Not enforced by code:** the adversarial trigger check, writers for
`## Task Review` and `## Fix Rounds` (their grammar is validated; write rows
through `locked_tracker_update`), phase verification and phase advance, and
counting and refusing dispatches against the agent-dispatch ceiling, and
whether the phase set sealed at stage 06 is the master plan's actual phase
list: the master plan is not machine-readable, so the seal is whatever ids
`close_phase_set` was given. The ratchet triggers `repeated-suite-failure`, `debug-locality` and
`accumulated-surface` are not verified against state: the tracker records no
suite-failure count or root cause, and the module never runs git to count
changed lines. These rules are yours to follow exactly.

**The module never executes git.** It emits argv and validates a transcript you
supply. Functions that need git take `run_command`: a callable that runs one
argv tuple and returns captured stdout as `str`, **raw** — never `.strip()`; the
leading NUL separator and trailing newline are part of the grammar.

## Required sub-skills

- `superpowers:test-driven-development` — every testable behaviour and every
  behaviour-changing fix. RED before GREEN, recorded in the implementer's report.
- `superpowers:systematic-debugging` — stage 10. Cause before fix.
- `superpowers:using-git-worktrees` — one worktree per concurrent implementer,
  merged `--no-ff` in task order.
- `superpowers:dispatching-parallel-agents` — only for ready independent batches.

## The review dial

You set each phase's `review_class` **once, at stage 04** — the classification
the plan then carries in its phase metadata, mirrored to `## Phases`. After that
it moves only through a ratchet whose trigger has already fired (below).
Writing the ratchet record is yours; the tracker refuses every other move.

| Class | Buys |
| --- | --- |
| `required` | Full per-task gate (below) |
| `final-only` | Mechanical verification only; stage 11 is the net |

**Never switched off at any class:** the adversarial trigger check; typed write
scopes and conflict detection; digest-bound PASS evidence; the
`baseline..source-head` range proof and integration ancestry; four-part result
identity (`run_id + task_id + attempt + owner`); TDD RED evidence; the
most-capable-model policy; the zero-open-findings bar. The dial decides whether a
reviewer runs, never what bar it applies.

### Adversarial triggers — any single one fires

`concurrency` · `authz` · `crypto` · `schema` · `migration` · `delete` ·
`regulated` · `public-api` · `large-surface` (> 300 changed source lines)

Independent of each other, of diff size, and of `review_class`. A 10-line auth
change fires. Record which trigger fired. A fired trigger dispatches the
adversarial reviewer before the task completes.

### The ratchet — `final-only → required`, upward only

| Trigger | Fires when |
| --- | --- |
| `adversarial-finding` | the adversarial reviewer returned CONFIRMED or unrefuted PLAUSIBLE |
| `repeated-suite-failure` | the phase suite failed twice or more |
| `debug-locality` | a stage-10 root cause is in a file inside this phase's scopes |
| `low-confidence-dependency` | a quorum adopted a decision in this phase below `specified` |
| `accumulated-surface` | cumulative changed source lines in the phase > 300 |

A ratchet record you write from your own reading of the diff is not a trigger.
Never downward, never by quorum. A ratchet gates every remaining task and adds a
phase-scoped review; it does not re-review completed tasks. `## Phases`
`Review Class` differing from the plan is legal only with a matching `Ratchet`
record (`Class Source: ratchet`).

**Enforced by `locked_tracker_update`** (write the ratchet through it, as
`Review Class: required`, `Class Source: ratchet`,
`Ratchet: <trigger>@<evidence>`):

- The only legal change to a phase's class is `(final-only, plan, -)` →
  `(required, ratchet, <trigger>@<evidence>)`, once. Lowering, withdrawing,
  re-labelling as `plan`, or rewriting the record is refused. So is removing,
  renaming or reordering an imported phase row, and recording or rewriting a
  `phase_plans` path except together with its new row: a phase row is born
  once, beside its plan path, so deleting it and re-adding it cannot reset its
  class, and editing the plan file afterwards changes nothing.
- `<trigger>` is one of the five names above (`RATCHET_TRIGGERS`).
- `adversarial-finding` needs an adversarial round on one of the phase's tasks
  with verdict `fail`. `low-confidence-dependency` needs a `## Quorum` row in
  the phase adopted below `specified`. Both facts are read from the tracker
  as it stood **before** the ratchet's transition, so write the fact first and
  ratchet in a later transition. The other three rest on the evidence you
  cite.
- A phase row a transition adds must carry its plan's class as `plan`.
  `import_phase_plan` does this for you.

Never degrade a quorum, review or class to fit capacity or budget. Escalate or
halt.

### The dispatch budget

Before every dispatch, compare `agent_dispatch_count` with the frozen
`dispatch_soft_ceiling` and `dispatch_hard_ceiling` in `## Run` (frozen at the
close of stage 07). At soft: dispatch anyway, enqueue exactly one non-blocking
`dispatch-overrun` escalation, and lead `status` and the terminal report with
the overrun. At hard: refuse the dispatch, let in-flight workers finish,
publish and import to `[x]` while holding only integration, set
`next_action = await-dispatch-budget`, and stop resumably until a
`dispatch.extend-budget` decision with `Provenance: human` raises it — at most
twice, then terminal. The one exemption over hard, recorded `over-hard`:
re-dispatching the missing brains of an already `in_flight` quorum. The
ceilings themselves never change; counting and refusing is yours.

## Stage 08 — RED

The failing test is written and committed before the change. The report records
the RED command, the failing output, why that failure was expected, then the
GREEN command and output. GREEN with no RED is unevidenced.

Run the runner the plan recorded. If it is not installed: `PLAN_CONFLICT`. Never
substitute a runner.

## Stage 09 — GREEN

### Starting a task

| Transition | Function | Requires |
| --- | --- | --- |
| `[ ] → [~]` | `reserve_task(run_dir, task_id=, owner=, attempt=)` | deps done, no overlapping active scope, slot under `implementation_slot_cap`. Records `baseline:<attempt>@<target-sha>` for a `source` task |
| `[?] → [~]` | `resume_task(run_dir, task_id=, prior_attempt=, new_owner=, new_attempt=, decision_ref=)` | the grant for the block: on `quorum:<qid>`, the `quorum.adopt` decision `Q-<qid>` that answers it (or the adoption of a re-ask of that qid), or a human `task.resume` `H-<n>` that an `answered` `## Escalations` row for that qid names as its `Resolution`, either not already used to resume this task; on `halt:<reason>`, a human `task.resume` repeating the blocker and naming the attempt. A new unused attempt; a fresh baseline (the old one is kept) |

Persist before dispatch. Several individually ready tasks are not jointly
authorised: check pairwise `scopes_overlap` across the whole batch. Context
compaction is not a retry — reconcile first; a consistent `[~]` stays the same
attempt.

Dispatch each implementer with its task brief file —
`scripts/task-brief RUN_DIR PLAN_FILE TASK_NUMBER [OUTFILE]`, never pasted plan
text — plus its governing decisions, write scope, task suite and four-part
identity.

### Worker statuses

| Status | Route |
| --- | --- |
| `DONE`, `DONE_WITH_CONCERNS` | Evidence, not acceptance. Import validates it. |
| `NEEDS_CONTEXT`, `PLAN_CONFLICT` | `[?]` with a question record → `quorum.md`. `Question` cell: `quorum:<qid>@<path>#sha256=<digest>`. |
| `BLOCKED` | Halt. `Question` cell: `halt:<reason>`. Never sent to a quorum. |

**You publish every worker result, not the worker.** The worker commits,
writes its report and ends with the values in its final message; it makes no
state call and never dispatches anyone, edits `progress.md`, integrates, or
accepts a phase. Then, in this order:

1. For `DONE` / `DONE_WITH_CONCERNS`, **re-run the task's exact ordered suite
   yourself** against the worker's head commit (an `artifact` task: the target
   tip) and record the result: a `task-test` PASS record from
   `render_verification_evidence` (run, subject `task/<id>`, attempt, that
   commit as `code_state`, the suite), written with
   `publish_immutable` under the run directory. The worker's "tests pass" is a
   claim; this record is the evidence. A failing suite leaves no record — the
   task is unfinished work, not a completion.
2. For `NEEDS_CONTEXT` / `PLAN_CONFLICT`, open the quorum on your completed
   copy of the question record (`quorum.md`) so `quorum/<qid>/question.md`
   exists.
3. `publish_worker_result(run_dir, result=...)` — rendered by
   `render_worker_result`, fields as in `templates/worker-result.md`, the
   four-part identity copied from the reservation — citing the evidence record
   from step 1 or the published question record from step 2. It returns the
   result's repository-relative path. A completion must cite its evidence when
   it is published, which is why the evidence comes first.

### Import, completion, integration — three separate facts

1. **Import:** `import_worker_result(run_dir, result_path=, run_command=)`.
   Validates identity, task definition, files, and the range: every commit in
   `baseline..source-head` for **this attempt's** baseline (`reserved_baseline`,
   never `HEAD~1`), every changed path inside scope, and one `task-test` PASS
   record matching run, task, attempt, head and exact suite. The range proof is
   reported `attested`: the transcript is yours, the anchors are the module's.
2. **Integration:** merge `--no-ff`, then
   `integrate_task(run_dir, task_id=, merge_commit=, run_command=)`. Every
   implementation commit must be an ancestor of the merge, the merge an ancestor
   of the target branch, with one `task-integration` PASS record for the merge
   commit. No squash, rebase or cherry-pick equivalence.
3. **A merge conflict is a hard stop.** Typed scopes make it impossible, so a
   conflict proves the scopes were wrong. Never auto-resolve.

An `artifact` task needs exactly its declared outputs, integration `N/A`, and no
invented commit.

Evidence records are written only by `render_verification_evidence`; purposes
are `task-test`, `task-integration`, `phase`. Outcome is only `PASS` — a failure
leaves no record.

### The per-task gate (`required`, or any fired trigger)

1. Build the review package from the persisted baseline:
   `scripts/review-package RUN_DIR BASE HEAD [OUTFILE]`, with `BASE` the
   attempt's `reserved_baseline`. It prints a path; the package never enters
   your context.
2. Dispatch the task reviewer with brief, report, package, decisions and test
   commands. The reviewer is never the implementer. It returns three verdicts:
   spec, quality, independent verification.
3. Resolve every "cannot verify from diff" item yourself; a confirmed gap fails
   spec review.
4. On a fired trigger, dispatch the adversarial reviewer on the same package.
   CONFIRMED → Critical; unrefuted PLAUSIBLE → Important.
5. Fix to **zero open findings at every severity**: one fixer per round with all
   findings, re-review after each, at most three rounds, then escalate.
6. Complete only after a round returns zero.

Minor findings are fixed, not deferred. One recorded exception: a Minor or
quality-part finding that would reverse a recorded decision goes to
reconciliation (`review.md`). The reconciliation is a quorum question on the
disputed decision's recorded axis — its stage-03 id, or `new` — never the
decision's qid (`quorum.md`), with the task in its `blocks`. Neither the controller nor the
reviewer settles it. The fix loop does not stall while it runs:

- the task moves to `[?]`, with a reference to the reconciliation question in
  its `Question` cell;
- its owner slot releases, and independent work continues;
- the fix-round counter does not increment: no `## Fix Rounds` round carries
  the disputed finding, so a decision dispute never spends one of the three
  rounds or escalates for the wrong reason.

If the decision survives, the finding closes `REFUTED — governed by <D-ID>`
and does not block completion.

## Stage 10 — Debug

Cause before behaviour change. Mechanical failures are unfinished work: repair
and rerun — do not open a formal finding for work that has not reached its gate.
A root cause inside this phase's scopes is ratchet trigger `debug-locality`:
record it.

## The phase boundary

Before recording phase verification:

- every task `[x]` with verified evidence;
- every `source` task has implementation → integration → target ancestry;
- every `artifact` task has validated outputs and integration `N/A`;
- every command of the plan's **exact ordered** phase suite passes on the
  integrated state; one `phase` PASS record binds run, phase, code state,
  command tuple, inputs and environment.

Your command text is checked against the approved tuple; it cannot substitute,
omit, add or reorder a command. A failing suite keeps the phase open. Finishing
the last task does not advance the phase; the last phase advances to stage 11,
not to completion.
