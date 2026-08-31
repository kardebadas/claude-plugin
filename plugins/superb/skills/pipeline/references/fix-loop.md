# Superpipeline: autonomous per-phase loop & recursive fix-mode

This file defines Stage 4's loop and the guard rails. Read it before running a
phase autonomously.

## Per-phase loop (each phase in dependency order; independent phases concurrently as lanes — `parallel.md`)

0. **Read the run state in full** — `progress.md`, then `findings.md`, then
   `register.md`, from `<PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/`,
   created at Stage 1. This is the first action of the phase: before dispatching
   any agent, before opening the sub-plan, before touching source. **Reconcile
   every `[~]` task against the actual code before continuing** (Run State Law,
   Rule 4 — procedure in `run-state.md`). The files name the phase, its first
   open task, and every finding still open; your memory does not get a vote.
1. **Implement** the phase **wave by wave** via
   `superpowers:subagent-driven-development`, following the wave table the user
   approved (Rule 6, `parallel.md`). A wave of one runs in the phase worktree;
   a wave of `k >= 2` dispatches all `k` implementers in one message, each in
   its own worktree and branch, and merges them in task order when all have
   passed task review. Around **each individual task**: mark it `[~]` with a
   timestamp (and its worktree branch) and save *before* dispatching; when it
   lands, mark it `[x]` with its commit hash, update the Current State block
   (phase, next action, `date` timestamp), save, then **re-read the file** to
   pick up the next open task or wave. Never carry task state in your head
   across two tasks. (Rule 2.) Independent phases run as concurrent **lanes**,
   each its own instance of this loop.
   Every dispatch prompt carries the ≤10-line return contract; long output goes
   to `agent-output/<label>.md` and comes back as a path. (Rule 5.)
   **After any dispatch, if you have no local work left, wait rather than end
   the turn** — on a mailbox harness a finished agent cannot wake you, and the
   turn-end is what makes a run stop after every task. See *Who wakes you after
   a dispatch* in `SKILL.md`.
2. **Review**:
   - Let `N` = number of tasks in this phase (from the expanded sub-plan).
   - Spawn `ceil(N/5)` **slice reviewers** in parallel. Assign each a
     contiguous slice of ~5 tasks **as an exact commit range**
     (`<first-hash>^..<last-hash>`, taken from the tracker); the agent reviews
     ONLY that range's diff, running the repo `/review` skill. Ranges, not task
     names — tasks that touch the same files make a name-based slice ambiguous.
   - Whenever there is more than one slice, spawn **one additional
     integration reviewer** in the same parallel batch. Its scope is the
     phase's combined diff, and it looks only for what single slices cannot
     see: cross-slice contract mismatches (producer in one slice, consumer in
     another), regressions the phase introduces into earlier phases' work,
     and duplicated or conflicting changes across slices.
   - **Run the repo test suite for the phase's changed code as part of this
     step.** Failing tests or a broken build on the phase's changes are
     **bug findings by definition**, whether or not any reviewer reported
     them — add them to the consolidated list with the failure output as
     evidence.
   - Consolidate findings from all reviewers **into `findings.md`**, dedup, and
     tag each by severity: **Critical**, **Major** (maps to `/review`
     "Warning"), **Minor**. When duplicate reports disagree on severity, **the
     highest severity wins**. **Assign every new finding the next free `F-NNN`
     ID**; a rediscovered finding keeps the ID it already has. Reviewers return
     ≤10 lines plus a `DETAIL:` path — read a full report only while
     consolidating, and never carry it forward in context.
3. **Decide**:
   - Any **Critical, Major, or bug** finding → go to **Fix loop**.
   - **Minor-only or none** → phase passes; **advance** to the next phase.
   - **If this phase is the last sibling of a Rule 3 split**, the joint
     integration review (below) runs before advancing past the split.
4. **Close out and advance.** In this order, no reordering:
   1. Write `progress.md`: every task in this phase `[x]` **with its commit
      hash**, Current State set to the next phase and its first open task,
      timestamp refreshed.
   2. Append every Minor finding to the deferred table in `findings.md`.
   3. Save both.
   4. *Only now* may the phase be called complete and the next phase begin.

   The phase is complete when the file says so — not when the reviewers went
   clean, and not when you believe the work is done. Starting the next phase
   before that write lands is the drift this loop exists to prevent.

   **And then start the next phase — in the same turn.** The close-out write,
   the re-read, and the next phase's first dispatch are one motion (the
   Continuation Law). A phase summary may be narrated inline, but if it ends
   your message with no guard-rail question attached, you have stopped the run
   without authorization. The only message that legitimately ends a turn
   between GATE 2 and Stage 5 is one that names a tripped guard rail and asks
   its question.

   Minor findings are **deferred, not discarded**: they live in `findings.md`'s
   deferred table, which Stage 5 MUST include in its hand-off message.

## Joint integration review after a Rule 3 split

A phase split into `4a`/`4b`/… because of the 12-task cap is still one designed
unit, and each sibling's own integration reviewer only ever sees its own
sibling. **After the last sibling passes its own review**, and before the run
advances past the split:

- Spawn **one joint integration reviewer** over the **union of all siblings'
  commits**, reviewed as a single phase.
- Its scope is exactly what per-sibling reviewers structurally cannot see: a
  contract introduced in `4a` and consumed in `4b`, `4b` regressing `4a`,
  duplicated or conflicting work across the split boundary.
- Its findings get F-IDs in `findings.md` like any others. Blocking ones run the
  fix loop — attributed to the split group, using the group's iteration counter
  — before the run advances.
- Splitting exists to bound review scope per sibling, never to reduce total
  review coverage. Skipping this review means nobody ever reviewed the phase the
  plan actually described.

## Finding-closure ledger (`findings.md`)

The ledger is a **file** in the run directory, not a mental list — format in
`../templates/findings.md`. Every blocking (Critical/Major/bug) finding has a
stable `F-NNN` ID, assigned at first consolidation and never reused or
renumbered. A ledger entry is **closed** only by one of:

- **Fixed and verified**: the fix diff touched the code the finding names,
  AND a re-review whose slice assignment covered that fix diff reports it
  resolved. Record the fix commit hash in the ledger row, so "the fix diff
  touched the code the finding names" is a `git show` anyone can re-run rather
  than a claim. Re-review slice assignments MUST cover every fix diff — a clean
  round from reviewers who never looked at the fix closes nothing.
- **User-ruled false positive**: the user (not you) declared it not a bug.

Every open ID carries forward into the next consolidation **by construction** —
the ledger is read, not remembered. A finding that silently disappears from
review output stays `open` in the file until closed by one of the two paths
above.

## Convergence rule (checked before every fix-mode dispatch)

Before dispatching fix-mode at iteration 2 or later, compare the **set of open
blocking F-IDs** against every previous iteration's set, both read from
`findings.md`'s iteration-history table:

- **No-progress**: an ID is still `open` after a fix-mode run that targeted it
  → do NOT re-run fix-mode on the same spec. Stop, show the user the finding,
  each prior attempt and what its diff changed, and ask how to resolve it
  (concrete options allowed — the user picks).
- **Oscillation**: the current open-ID set equals any earlier iteration's set
  (fixes are reintroducing each other's findings) → same stop, showing the
  cycle.

This is a **set comparison over IDs**, deliberately not a judgment about whether
two descriptions mean the same thing — that judgment would be made by the same
memory this skill declines to trust. Record each iteration's set in the file as
it is consolidated, or the comparison has nothing to compare against.

These stops are Ambiguity-guard stops: uncapped, and they don't consume
iterations. The iteration cap is a **backstop for slow progress, not the
designed surfacing point** — the convergence rule stops at the first
evidenced wasted iteration, which is always earlier than the cap.

## Ambiguity guard (applies throughout Stage 4 and at every fix-mode depth)

**Predicate:** does the approved spec, the expanded plan, or a written repo
rule state the answer?

- **Yes** → follow it and continue autonomously.
- **No** → **STOP. Ask the user. Wait for the answer. Then resume** exactly
  where the run stopped, treating the answer as if it had been in the plan.
  In **Brain-Agent mode** (`register.md` carries the user's verbatim
  declaration — `parallel.md`) the question goes to a dedicated Brain Agent
  instead, and its ruling is recorded in the register the same way.

This is a guard rail, not a violation of autonomy: post-GATE 2 autonomy covers
*execution* of decided work, never *deciding requirements or user-visible
behavior* the user was never asked about. Typical triggers: the plan says
"notify the user" without a channel; two implementations differ in anything the
user could observe; a reviewer finding can be "fixed" two materially different
ways; a failing test can be made green by changing the code or by changing the
test's expected behavior.

**Forbidden resolutions** (all observed in testing — none of them is consent):
resolving by codebase precedent, picking the "cheapest-to-reverse" or
"lower-blast-radius" option, logging the decision for later review, or
deferring to the review fan-out. Precedent and reversibility may shape the
options you *offer in the question* — they never replace the question.

Ambiguity stops are **uncapped** and do **not** increment the fix-loop
iteration counter or recursion depth. Record each ambiguity **as a register
entry in `register.md`** when it is asked, and record the user's verbatim answer
there when it arrives, so later agents — and the run after the next compaction —
inherit the answer instead of re-asking or guessing.

## Fix loop (recursive `pipeline` in fix-mode)

When blocking findings exist (and the convergence rule permits another run):

1. **Increment this phase's fix-loop iteration counter in `findings.md`, and
   save, before dispatching anything** — bump the Counters row, and open an
   Iteration-log row recording the iteration number, the phase, the depth, and
   the F-IDs this run targets. The counters live in the file for the same reason
   the tracker does: a compaction empties your context but not the table, and a
   cap you re-derive from memory resets to zero and stops capping anything.
   Never trust a remembered iteration number — read the row.
2. Recurse `pipeline` in **fix-mode** on the open ledger entries, **named
   by F-ID** so the convergence check can tell what this run targeted:
   - Fix-mode **skips Stage 1 (brainstorming)** entirely — no interactive Q&A,
     no 2-agent pressure-test.
   - Fix-mode writes **no new top-level spec**; the findings ARE the spec.
   - Fix-mode **inherits the enclosing run's directory** and never creates one.
     It **never initializes or rewrites `progress.md`'s phase lists** —
     initialization belongs to Stage 1 and the GATE 2 rewrite only. It reads the
     run state and leaves the enclosing phase's task list intact; re-opening a
     task it had to redo (`[x]` → `[~]`, then `[x]` with the new hash) is the
     only edit it may make.
   - **Standard path**: plan (`writing-plans`) → implement
     (`subagent-driven-development`) → review the fixes.
   - **Direct-fix path** (skips only the `writing-plans` step): allowed when
     the open blocking findings number **≤ 3** AND every finding names the
     exact file and line. Implement directly via
     `subagent-driven-development` with the findings as the task list; the
     review step is unchanged. If any fix grows beyond the files the findings
     name, or trips the Ambiguity guard, **abort the direct path and restart
     this fix-mode run on the standard path**.
   - The **Ambiguity guard applies at every depth**: a finding that can be
     fixed two materially different ways is a question, not a coin flip.
3. After the recursive run returns, **re-review** using the re-review fan-out
   below (NOT `ceil(N/5)` — fix diffs are not task-shaped), ensuring slice
   assignments cover every fix diff. Update the ledger, and complete the
   Iteration-log row with the set of F-IDs still open after the re-review.
4. Repeat until no Critical/Major/bug findings remain (green test suite
   included), subject to the convergence rule and the caps below.

## Re-review fan-out (fix-mode returns)

The Stage 4 rule `ceil(N/5)` is defined over **tasks**. A fix-mode run produces
fix commits, not tasks, so re-reviews get their own math. Let `M` = the number
of blocking F-IDs this fix-mode run targeted:

| Targeted F-IDs (M) | Slice reviewers | Integration reviewer | Total |
|--------------------|-----------------|----------------------|-------|
| 1–3                | 1               | 0 (one slice sees all) | 1   |
| 4–6                | 2               | 1                    | 3     |
| 7–9                | 3               | 1                    | 4     |
| 10+                | `ceil(M/3)`     | 1                    | —     |

- **~3 F-IDs per reviewer, not 5.** Each one has to be verified against the
  specific code it names, which is denser work than reading a task's diff.
- **Slice boundaries are the fix commits' ranges**, taken from the ledger's
  recorded fix hashes — the same range discipline as Stage 4 slices.
- **Assignments MUST cover every fix diff.** Union the assigned ranges and
  compare against the full set of commits the fix-mode run produced; if any
  commit is unassigned, extend a slice to include it. A fix that strayed outside
  the files its findings named still needs an owner. **A clean round from
  reviewers who never looked at a fix closes nothing** — that is the ledger's
  closure condition, and this is how you satisfy it.
- The integration reviewer's scope is the union of all fix commits, hunting
  interactions between fixes and regressions the fixes introduced elsewhere.
- Re-reviews also re-run the test suite; failures are bug findings as always,
  and get F-IDs like anything else.

## Guard rails

**Depth counts fix-mode nesting only.** The initial Stage 4 run of a phase is
**depth 0**; the first recursive fix-mode run is depth 1, and so on.

**Both counters are read from `findings.md`'s Counters table, never from
memory.** A cap enforced against a remembered number is not a cap: a compaction
mid-fix-loop silently resets it to zero and the loop runs forever. Read the row,
increment it in the file before dispatching, then compare against the cap.

| Guard rail | Default | Trips when | Action |
|------------|---------|-----------|--------|
| Ambiguity guard | uncapped | Any decision is not answered by the approved spec, expanded plan, or a written repo rule | **Stop. Ask the user. Wait. Resume.** |
| Convergence rule | uncapped | An open F-ID survives a fix-mode run that targeted it, or the open-ID set repeats an earlier iteration's | **Stop. Show attempts. Ask the user.** |
| Existing run directory | uncapped | Stage 1 finds a run directory already at the computed path | **Stop. Show its Current State. Ask: resume, fresh, or abort.** |
| Unreconciled `[~]` task | uncapped | A cold start finds a started-but-unverified task whose real state the plan doesn't settle | **Stop. Show the evidence. Ask the user.** |
| Recursion depth cap | 2 | A fix-mode run is itself about to recurse (its own fixes produced blocking findings) past depth 2 | **Stop. Surface to user.** |
| Fix-loop iteration cap | 5 | A single phase's fix loop runs 5 times without going clean | **Stop. Surface to user.** |

**At either cap:** halt the autonomous run, present the unresolved blocking
findings, the phase, the iteration/depth reached, and what was tried. Ask the
user how to proceed.

**The tripped guard rails above are the only user interruptions after GATE 2**
— and the Ambiguity guard and Convergence rule are two of them. "No user
stops" forbids routine check-ins and progress confirmations; it has never
authorized guessing at an unanswered requirement or re-running a fix that
demonstrably isn't converging.

The test cuts both ways and is mechanical (the Continuation Law): a message
that ends your turn mid-run **must contain a guard-rail question**, and a
message that contains no question **must not end your turn**. A summary,
however complete, authorizes nothing.

## Invariants
- **The run state is read in full before a phase starts and written before a
  phase is called complete** — no phase boundary is crossed in either
  direction without touching the files.
- **The tracker is updated around every individual task** — `[~]` before,
  `[x]` + hash after — never batched to the end of a phase.
- **No `[~]` task is stepped over.** A cold start reconciles every one of them
  against the code before the run does anything else.
- **Every `[x]` carries a commit hash** (or `` `nocommit` `` + reason). Slice
  ranges, resume verification and fix-diff checks all read those hashes.
- **The register and the findings ledger are files**, not context. An open
  register entry or open F-ID survives a compaction because it is on disk.
- **F-IDs are stable**: assigned once, never reused, never renumbered; a
  rediscovered finding keeps its ID.
- **The orchestrator holds pointers, not payloads** — ≤10-line subagent returns,
  long output in `agent-output/`, detail files read only when a decision needs
  them.
- **A Rule 3 split gets a joint integration review** over its siblings' combined
  diff before the run advances past it.
- **No turn ends between GATE 2 and Stage 5 without a guard-rail question in
  it.** Phase close-out and next-phase start are one motion in one turn.
- **All run state lives under
  `<PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/`** — never in the
  skill directory, and never `git add`ed.
- Where a run-state file and your recollection disagree, **the file is right**.
- No phase carries more than 12 tasks; an oversized phase was split at Stage 3,
  before GATE 2 and before any implementation.
- Counters are **per phase** (iteration) and **per recursion chain** (depth),
  and both live in `findings.md` — incremented in the file **before** each
  dispatch, read from the file before each cap check, never carried in context.
  Reset the iteration counter by opening a new phase row.
- **Re-reviews use the re-review fan-out (`ceil(M/3)` over targeted F-IDs), not
  `ceil(N/5)`**, and their assigned ranges must union to cover every fix commit.
- Ambiguity and convergence stops never count toward either cap.
- Never resolve a requirements or user-visible-behavior ambiguity by
  precedent, defaults, reversibility, or decision logs — ask the user.
- Never dispatch fix-mode on a spec that already failed unchanged — the
  convergence rule stop comes first.
- A blocking finding is closed only via the finding-closure ledger (fixed and
  verified, or user-ruled false positive) — never by a review round that
  didn't cover its fix.
- Never advance a phase with an open Critical/Major/bug ledger entry.
- Never advance a phase with failing tests or a broken build on its changes.
- Never advance a phase with an unanswered ambiguity question.
- Never block a phase on Minor-only findings — but carry every Minor finding
  to the Stage 5 hand-off; they are deferred, never discarded.
- Fix-mode is set **only** by this loop, never by the user.