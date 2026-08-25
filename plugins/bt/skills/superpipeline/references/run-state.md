# Superpipeline: run state on disk

Everything the run knows lives in the run directory. The orchestrator's context
is a cache of these files, never the other way round.

```
<PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/
  progress.md        # the tracker — phases, tasks, Current State
  register.md        # Assumptions Register
  findings.md        # blocking ledger (F-IDs), iteration history, deferred Minors
  agent-output/      # one file per dispatch; long subagent output lands here
```

Templates for the three files ship with the skill in `templates/`. They are
**read-only** — copy, never edit in place.

Nothing under `docs/superpowers/` is ever `git add`ed — run state, specs and
plans are deliberately local-only. **So the guard-rail counters belong on disk
too:** `findings.md` carries the fix-loop iteration count and recursion depth,
because a cap compared against a remembered number stops capping the moment the
context is compacted. And anything that must outlive the run goes into the
Stage 5 hand-off, not a run-directory file.

## Creating the run directory (Stage 1, step 0)

1. Compute the path from today's date (`date +%F`) and the topic slug.
2. **If the directory already exists**, do not touch it. Read `progress.md`,
   then **ask the user**: resume this run, start a fresh one (a new suffixed
   directory), or abort. Show them the tracker's Current State block so the
   choice is informed. Silent resume and silent overwrite are both forbidden —
   an unfinished run is exactly the state the Iron Law protects.
3. Otherwise create it, copy the three templates in, strip their comments, and
   state the full directory path in your first message to the user.

Fix-mode recursions **inherit** the enclosing run's directory. They never create
one.

## progress.md — task line grammar

```
- [ ] T3 — <task name> · W2 · deps T1
- [~] T3 — <task name> · W2 · deps T1 — started 2026-08-05 14:02 in `wt/p2-t3`
- [x] T3 — <task name> · W2 · deps T1 — `a1b2c3d`
- [x] T4 — <task name> · W3 · deps T3 — `nocommit` (docs only, folded into T5's commit)
```

`W<n>` is the task's wave and `deps` its in-phase dependencies, both copied
from the GATE 2 plan (Rule 6, `parallel.md`). A `[~]` line in a multi-member
wave also names the worktree branch the member runs in, so a cold start knows
where to look for its commits. Phase headings carry `· deps: <phases>`.

| Marker | Meaning |
|--------|---------|
| `[ ]` | Not started. Nothing was dispatched for it. |
| `[~]` | **Started, outcome unknown.** Written *before* the work begins. |
| `[x]` | Done, followed by the commit hash that carries it. |

**Write `[~]` before dispatching the task, not after.** That single write is
what makes a dead session recoverable: without it, a half-applied task is
indistinguishable from an untouched one.

**Every `[x]` carries a hash.** Record the short hash of the commit containing
that task's work. If a task genuinely produced no commit, write `` `nocommit` ``
with a one-line reason — never leave the field blank, because a blank field is
unverifiable and that is the whole point of recording it.

Hashes buy three things: resume verification becomes `git cat-file -e <hash>`
rather than a judgment call; a reviewer slice becomes an exact commit range
instead of a fuzzy "contiguous ~5 tasks"; and the ledger's "the fix diff
touched the code the finding names" test becomes a diff anyone can re-run.

## Cold-start resume protocol

A cold start is any of: a new session, a context compaction, a resumed run, or
your own uncertainty about what just happened. Run this **before any other
action** — before dispatching, before reading a plan doc, before writing code.

1. Read `progress.md` in full, then `findings.md`, then `register.md`.
2. **Scan for `[~]` tasks. Every one is a reconciliation obligation.** For each:
   - `git log`/`git status`/`git diff` for the work the task names, and run the
     tests that cover it. If the line names a `wt/…` branch, look there
     (`git log P..wt/…`, `git worktree list`) — a wave member's work is not on
     the phase branch until the wave merge.
   - **Fully applied and green** → mark `[x]` with the hash it landed in.
   - **Partially applied** → this is the dangerous case. Revert the partial work
     or complete it deliberately; do not build on top of it. If which of those
     is correct is not obvious from the plan, that is an Ambiguity-guard stop —
     ask the user.
   - **Nothing applied** → reset to `[ ]`.
3. Only when zero `[~]` tasks remain may the run continue. Take the next action
   from the Current State block, not from what you remember doing.

**A `[~]` task is never assumed done because it looks done, and never assumed
untouched because you don't remember it.** Verify against the code.

## Resume Protocol (`/superpipeline resume`)

The user-invoked path back into an interrupted run. It wraps the cold-start
protocol above with candidate selection and a reporting step. **This mode never
starts a new run** — if step 1 finds nothing, report that and stop.

1. **Find candidate run directories** under `<PROJECT_DIR>/docs/superpowers/runs/`.
   - **Exactly one with unfinished work** (any `[ ]` or `[~]` task, open
     register entry, or open blocking F-ID) → use it.
   - **Multiple candidates, or none obviously active** → show each one's
     Current State block and **ask the user which to resume**. Recency is not
     consent: the newest directory is a guess about someone's unfinished work,
     not an answer.
   - **Zero** → report "no run to resume" and stop. Starting a fresh run from
     `resume` is forbidden — that's what the bare invocation is for.
2. **Read, in order and in full:** this file (if not already in context), then
   the run's `progress.md`, `register.md`, `findings.md`.
3. **Read the plan documents the current position needs** — the spec, the
   master plan, and the sub-plan doc for the **current phase only**.
   Pointers-not-payloads applies to plans too: don't load all 20 phase docs to
   resume one.
4. **Reconcile against ground truth:**
   - Run the cold-start `[~]` verification (above) on every `[~]` task.
   - Cross-check the last few `[x]` hashes against `git log` on the branch —
     they must exist and be on the branch.
   - Run the test suite.
   - **Commits on the branch newer than the last tracker hash that no task
     accounts for → surface to the user before proceeding.** Someone or
     something worked outside the tracker; whether to absorb, revert, or
     investigate those commits is their call, not yours.
5. **Report a short resume summary** to the user: run directory, current phase,
   next task, open F-IDs, open register entries, and anything reconciliation
   surfaced. If reconciliation raised questions — partial `[~]` work whose
   disposition the plan doesn't settle, unexplained commits — these are **user
   questions; wait for the answers**.
6. **If the register has open entries, ask them before resuming
   implementation.** Otherwise continue the Stage 4 loop from the tracker's
   next task, under all normal rules — this protocol changes how a run is
   re-entered, never what the run is allowed to do.

## Orchestrator context hygiene

The tracker fixes drift *within* the orchestrator's reasoning; this rule stops
the orchestrator's context filling with material that causes the drift.

**Every dispatched subagent returns at most ~10 lines, in this shape:**

```
TASK:    T4
STATUS:  done | blocked | needs-decision
COMMIT:  a1b2c3d | nocommit
BRANCH:  wt/p2-t4 | <phase branch>   (the branch the commit is on)
FILES:   src/x.php, src/y.php
TESTS:   pass | fail — <one line>
NOTES:   <≤2 lines: only what changes the orchestrator's next move>
DETAIL:  agent-output/<label>.md   (omit if there is nothing longer)
```

Anything longer — diffs, full `/review` reports, test logs, exploration notes —
the subagent **writes to `agent-output/<label>.md`** and references by path.
Include that instruction in every dispatch prompt.

**The orchestrator holds pointers, not payloads.** It reads a detail file only
when a decision actually depends on its contents (consolidating findings,
answering an Ambiguity question, preparing a user-facing summary) — and then it
reads the file, not a remembered version of it. Reviewers' full reports in
particular never enter orchestrator context wholesale; the consolidated finding
list in `findings.md` is what the run reasons over.

## Findings: stable IDs

At the **first** consolidation that surfaces a finding, assign it the next free
`F-NNN` in `findings.md`. From then on:

- The ID travels with the finding through fix-mode dispatches, re-reviews, and
  the convergence check.
- Dedup maps a rediscovered finding onto its **existing** ID. Never mint a
  second ID for the same defect.
- IDs are never renumbered or retired, including for closed and false-positive
  entries — the iteration history depends on them staying stable.
- The convergence rule compares **ID sets** between iterations. "Is this the
  same finding as last time?" is a lookup, not an act of judgment by the same
  memory the rest of this skill declines to trust.
