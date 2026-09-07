# Stage 4 — IMPLEMENT: dispatching a phase's tasks

Read at every Stage 4 implementation dispatch. This file is the whole of how
pipeline gets code written. It replaces the previous delegation to
`superpowers:subagent-driven-development`, which had no implementation-only
mode: an implementer returning `DONE` there mechanically produced a reviewer
for that task, and a task completed only at zero open findings at any severity
through an uncapped fix/re-review loop. That is a second acceptance gate for
work this skill accepts at the phase, and running both reviewed everything
twice.

## The no-task-review rule

```
COMPLETING AN IMPLEMENTATION TASK DISPATCHES NO REVIEWER.
```

During IMPLEMENT the only transition is **task → next task**. Nothing reviews a
task: no task-scoped reviewer, no task-level fix loop, no task-level re-review,
and no adversarial pass. A task's report is recorded and the next task is dispatched.

An implementation agent fixing its own compile error, failing test, syntax
error or obvious mistake is **implementation**, not the fix loop. The fix loop
is a named state that begins only after the phase's review has closed
(`references/fix-loop.md`).

This is not a cost decision. Review moved *up*, not away: the phase's `RV`
fan-out reads the whole phase diff as one unit and is the gate that accepts the
work. What was deleted is the duplicate, not the review.

## What an implementation agent owns

| Owns | Does not own |
|---|---|
| implementing one task from its brief | formal acceptance |
| writing the covering tests, test-first | reviewing its own work as a substitute for review |
| running the covering tests and the build gates | dispatching anything |
| a self-check against the brief and its own diff | writing the tracker |
| committing, with the ticket key | deciding the phase is done |
| a ≤10-line return with `DETAIL:` pointing at its report file | carrying payloads back into the orchestrator's context |

## Choosing the model

**Pick the tier from the task, and say why.** Defaulting every implementer to
the strongest model available is the same mistake as reviewing every task: it
buys nothing on work that has one correct transcription, and it is paid on every
dispatch of every phase. Choose explicitly:

| Tier | Use for |
|---|---|
| **Cheap / fast** | mechanical prose edits; transcribing a brief that already contains the exact content; simple fixtures; small deterministic changes; straightforward single-file edits |
| **Standard capable** | multi-file implementation; non-trivial scripts; linter and mutation logic; moderate debugging; wiring together interfaces that already exist |
| **Strongest available** | architecture-sensitive reasoning; subtle debugging; difficult remediation planning; whole-change review; state-machine consistency review |

Two rules on top of the table:

- **The brief's own precision is the signal.** A task whose brief carries the
  literal text to write is a transcription; a task that says what to achieve and
  leaves the shape open is not.
- **A fix agent is sized by the finding, not by the phase.** A one-line
  correction with an exact `file:line` is a cheap-tier dispatch even in a phase
  whose implementation needed the strongest tier. Remediation *planning* is the
  opposite: it reasons across findings, so it stays at the top tier.

Record the tier in the dispatch. An unnamed choice is a default, and the default
is what this rule exists to stop.

## Dispatching one task

1. **Mark the task `[~]` in `progress.md` and save, before the dispatch**
   (Rule 2). A run that dies mid-dispatch must be able to tell "dispatched"
   from "never started".
2. Build the payload from `templates/implementer-prompt.md`. Fill every slot.
   The brief comes from `scripts/task-brief <sub-plan> <n>` — pass the **path**,
   never the brief's text (Rule 5: hold pointers, not payloads).
3. Dispatch one agent. Wait for it (`SKILL.md`, *Who wakes you after a
   dispatch*).
4. On return:
   - `DONE` / `DONE_WITH_CONCERNS` → record the commit hash against the task
     line, mark it `[x]`, save. File any concern as a note for the phase review
     to read; a concern is not a finding until a reviewer raises it.
   - `NEEDS_CONTEXT` → this is the Ambiguity guard. If the approved plan settles
     it, answer and re-dispatch. If it does not, **stop and ask the user**.
   - `BLOCKED` → stop and ask the user. Do not re-dispatch the same brief.
5. **Then dispatch the next task.** Do not dispatch a reviewer.

A task whose work produced no commit records `nocommit` with the reason, as the
task-line grammar requires (`references/run-state.md`).

## Waves

Waves are the approved plan's, never inferred here (Rule 6,
`references/parallel.md`). A wave of one runs in the phase worktree. A wave of
`k ≥ 2` dispatches all `k` implementers **in one message**, each in its own
worktree and branch cut from the phase branch head, each marked `[~]` before
its own dispatch and `[x]` with its hash as it lands.

When the last member of a wave lands:

1. Merge the member branches onto the phase branch **in task order**, one
   no-fast-forward merge each, the merge message naming the task.
2. Run the build gates. **A gate failing here means the implementation is not
   finished.** Repair it inside IMPLEMENT — dispatch the repair to the task's
   own implementer, or to a fresh implementation agent scoped to the failure —
   and re-run the gate until it is green. This opens **no** formal remediation
   round: no findings are raised, no F-ID is assigned, no fix plan is written,
   no Counters row is spent, and `RV` stays `[ ]`. The formal states
   (`FIX_PLAN` → `FIX_IMPLEMENT` → `RE_REVIEW`) exist only downstream of
   REVIEW, and a failure nobody has reviewed yet cannot enter them.
3. Re-read the tracker, then dispatch the next wave.

No member is reviewed before its merge. The merge gate is the build, not a
reviewer.

## Leaving IMPLEMENT

IMPLEMENT ends — and REVIEW may begin — only when **every** implementation task
line in the phase is `[x]` with a commit hash (or a justified `nocommit`), every
wave has been merged, and the build gates are green on the phase branch.

```
A PHASE'S REVIEW MAY NOT BEGIN WHILE ANY TASK IN THAT PHASE IS UNCHECKED.
```

**There is exactly one formal remediation state machine, and it starts after
REVIEW.** A compile error, a failing test, a syntax error, an obvious mistake or
a red build gate — at any point before `RV` opens — is unfinished
implementation, repaired here and re-gated here. It is not a finding, it gets no
F-ID, it needs no fix plan, and it spends no iteration budget. Nothing before
`RV` is a fix loop; there is no pre-`RV` fix loop to enter.

This does not soften the exit condition. IMPLEMENT still ends only when the work
has landed **and** the required build and test gates are green — a red gate
keeps the phase in IMPLEMENT rather than routing it somewhere else.

Reviewing early splits the phase into pieces and re-creates the task-scoped
gate by another name. If the phase is too big to review as a unit, that is
Rule 3's 12-task cap and a split at the *plan* level, not an early review.
