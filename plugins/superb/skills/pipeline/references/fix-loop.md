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
   pick up the next open line or wave — and after a phase's last task that is
   the phase's `RV`, never the next phase. Never carry task state in your head
   across two tasks. (Rule 2.) Independent phases run as concurrent **lanes**,
   each its own instance of this loop.
   Every dispatch prompt carries the ≤10-line return contract; long output goes
   to `agent-output/<label>.md` and comes back as a path. (Rule 5.)
   **After any dispatch, if you have no local work left, wait rather than end
   the turn** — on a mailbox harness a finished agent cannot wake you, and the
   turn-end is what makes a run stop after every task. See *Who wakes you after
   a dispatch* in `SKILL.md`.
2. **Review**: *(this step is a tracker line — the phase's `RV`. Mark it `[~]`
   with a timestamp and save **before** dispatching any reviewer, exactly as
   Rule 2 requires of a task. A run that dies here must be able to tell
   "reviewers were dispatched" from "review never started".)*
   - Let `N` = number of **tasks** in this phase (from the expanded sub-plan).
     The `RV`/`RVJ` lines are not tasks and never count toward `N`.
   - Spawn the slice reviewers in parallel. **How many depends on the regime**,
     and the `RV` line must record which: an **unwaved** phase takes
     `ceil(N/5)`; a **waved** phase (Rule 6) takes one slice per wave or per
     adjacent pair of small waves — which may be more or fewer than `ceil(N/5)`
     — and writes `waved` after `N`, because splitting a wave's members across
     two reviewers is forbidden. Assign each an exact commit range
     (`<first-hash>^..<last-hash>`, taken from the tracker); the agent reviews
     ONLY that range's diff, running the repo `/review` skill. Ranges, not task
     names — tasks that touch the same files make a name-based slice ambiguous.
     **Every reviewer returns a report file even when it finds nothing**, since
     the `RV` closes on one file per reviewer; the general "omit `DETAIL:` if
     nothing is longer" licence does not reach reviewers.
   - **Check the slices cover the phase.** Let `PB` = the phase branch's base
     (the commit it was cut from — *not* `parallel.md`'s per-wave `BASE`) and
     `PH` = its head. Run `git log --oneline PB..PH`, confirm every commit falls
     inside some slice's range, and **write that output to
     `agent-output/p<phase>-coverage.md` below the slice assignment table**
     (each row keyed by its report filename, with that reviewer's exact range),
     ending `COVERED: <n>/<n> commits`, and cite the file on the `RV` line. Commits you wrote yourself between tasks have no task
     hash, so nothing covers them until you widen a slice. Mind the exclusive
     `^` base: a commit sitting immediately before a slice's first task falls
     into no slice at all, so derive `PB` with `git merge-base` rather than
     assuming `<first-task-hash>^`. Being their author is not a review.
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
     tag each by severity. **There are exactly three tiers: Critical, Major
     (= `/review`'s "Warning"), Minor.** A reviewer that reports in another
     vocabulary is re-tagged here, never carried: `subagent-driven-development`'s
     task reviewer emits **Important**, whose contract is "fix everything before
     this task completes" — right for one task's diff, wrong for a phase, and it
     is not in this skill's blocking list. So **an incoming `Important` is
     re-tagged** by consequence: it becomes **Major** if it names a measured
     behavioural defect, **a requirement the plan, spec or brief mandated that
     the phase did not implement**, a failing or vacuous test, a broken build
     gate, a security/PHI/data-loss reachability, or a fragility whose failure
     mode is **reachable in the code as written** (an unhandled empty or null
     case, an ordering or race dependency) — and **Minor** otherwise. Minor is
     the total catch-all, and two things land there deliberately:
     maintainability damage, and fragility that is only hypothetical ("this
     could break under load" with nothing shown that reaches it). A missed
     requirement is **not** deferrable — "the plan mandated X and the phase does
     not do X" is the phase not being done, and no other check in this skill
     catches it, so demoting it to Minor would let a spec gap ride out the run
     as a deferred note. Record the re-tag in the ledger row so the call is
     visible.
     **These branches are the severity decider, not only a re-tag rule.** The
     predicate is stated over an incoming `Important` because that is the
     vocabulary it was written to convert, but it decides severity wherever
     this skill has to set a tier itself — a **claim finding** below is one such
     place, whatever tier it arrived under — and it decides it on these same
     branches' own terms. The tier a finding arrived under is not evidence of
     which branch it reaches.
     When duplicate reports disagree within the three tiers, **the highest
     wins**. **Assign every new finding the next free `F-NNN`
     ID**; a rediscovered finding keeps the ID it already has. Reviewers return
     ≤10 lines plus a `DETAIL:` path — read a full report only while
     consolidating, and never carry it forward in context.
   - **Close the `RV` line** `[x]` with all four fields the grammar requires —
     `N=<tasks> → <s> slice + <i> integration`, exactly `s + i` report files,
     the coverage file, and the F-IDs or `no findings` (`SKILL.md`, *The RV
     line*). Fewer report files than declared reviewers does not close it.
3. **Decide**:
   - Any **Critical, Major, or bug** finding → go to **Fix loop**.
   - **Minor-only or none** → phase passes; **advance** to the next phase.
   - **If this phase is the last sibling of a Rule 3 split**, the joint
     integration review (below) runs before advancing past the split.
4. **Close out and advance.** In this order, no reordering:
   0. Confirm this phase's **`RV` — and, for a split's last sibling, its
      `RVJ` — is `[x]`** with every round's report files present and counted and
      each coverage file ending `COVERED: <n>/<n>`. If the line is `[ ]`, or is
      `[x]` but fails that count, **set it back to `[ ]`** — an unbacked closure
      is not a partial review — and go to step 2.
   1. Write `progress.md`: every task in this phase `[x]` **with its commit
      hash**, Current State set to the **next unchecked line** — a joining
      phase's `RVJ` sits above its first task — timestamp refreshed.
   2. Append every Minor finding to the deferred table in `findings.md`.
   3. Save both.
   4. *Only now* may the phase be called complete and the next phase begin.

   The phase is complete when the file says so — and the file says so only once
   the `RV` line is `[x]` beside the task lines. Reviewers going clean is not
   completion until it is written down; believing the work is done was never
   completion at all. Starting the next phase before that write lands is the
   drift this loop exists to prevent.

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
sibling. It has its own tracker line — **`RVJ`**, written at GATE 2 under the last
sibling — because a review recorded nowhere is the failure the `RV` line exists
to prevent, and this is the review most easily forgotten. **After the last
sibling passes its own review**, and before the run advances past the split:

- Spawn **one joint integration reviewer** over the **union of all siblings'
  commits**, reviewed as a single phase.
- Its scope is exactly what per-sibling reviewers structurally cannot see: a
  contract introduced in `4a` and consumed in `4b`, `4b` regressing `4a`,
  duplicated or conflicting work across the split boundary.
- Its findings get F-IDs in `findings.md` like any others. Blocking ones run the
  fix loop under the **`RVJ`'s own Counters row** — not the siblings' shared
  row, which they may already have spent; a joint review that trips the cap on
  its first finding because three siblings used the budget is a cap doing the
  opposite of its job.
- Close **`RVJ` `[x]`** with the same evidence an `RV` carries. The last
  sibling's own `RV` going `[x]` never stands in for it: that reviewer saw one
  sibling, and the whole point is that nobody has seen the unit.
- Splitting exists to bound review scope per sibling, never to reduce total
  review coverage. Skipping this review means nobody ever reviewed the phase the
  plan actually described.

## Backfilling a review found open late

An `RV`/`RVJ` discovered open after its phase merged — at a resume, or at
Stage 5 — is run against the **merged history**, not the deleted phase branch:
the slice ranges are the phase's commits as they sit on the run branch, which
`git log` still resolves. Its fixes land on the current branch as ordinary fix
commits. Open a **`<phase> backfill` Counters row** — never reuse the phase's
original row, which may already be spent — run the fix loop normally, and close
the line with the round recorded. Stage 5 does not proceed while one is open.

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

**A claim finding closes differently, and the difference is a termination
argument.** A *claim finding* is one whose defect is an assertion rather than a
behaviour: a comment, a docblock, a commit message or a run report that states a
count, a `file:line` citation, a sole-writer or sole-caller claim, or "X is what
protects Y". **Neither enforcement code nor a run's own records is exempt.** A
comment in a gate, a linter or a test harness is prose the same way — "it is
rationale, not model-facing text" is exactly the carve-out that lets a rule's own
enforcement keep the claims the rule exists to remove — and a run's own records,
its reports and its ledger rows, are prose the same way. Such a finding closes by
exactly one of:

- **Deleting the claim.** Always available, always terminating.
- **Pinning it with a test** that fails when the claim stops being true, or
  re-anchoring it to a symbol that moves with the code.

**A rewrite is not a closure.** A corrected assertion is still an unexecuted
assertion: nothing keeps it true as the code under it changes, so the fix round
raises its own successor and the loop has no fixed point. So a claim finding
closed by deletion or by a pin **opens no re-review round** — there is no
behaviour to re-review, and the pin, if any, is a test the suite already runs,
so `M` and the fix-diff coverage union both exclude it. A claim finding whose
fix rewrote the prose is **not closed**: send it back for a deletion or a pin.

Severity is decided by the re-tag predicate above, not by this rule: a claim
finding is **Minor** unless one of that predicate's branches applies to it on
its own terms. The branch such a finding usually reaches is **a requirement the
plan, spec or brief mandated that the phase did not implement** — a claim that
another task's work is already done is how that requirement comes to be skipped
— and there it is **Major**, not a cosmetic note.

Every open ID carries forward into the next consolidation **by construction** —
the ledger is read, not remembered. A finding that silently disappears from
review output stays `open` in the file until closed by one of the routes
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
     only edit it may make **to a task line**. `RV`/`RVJ` are written by
     whoever actually ran a review round, at whatever depth — a depth-1 run that
     re-reviews its own fixes records that round on the line itself. What is
     forbidden is closing an `RV` no phase-wide fan-out ever produced.
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
   assignments cover every fix diff. Update the ledger and complete the
   Iteration-log row with the set of F-IDs still open after the re-review.

   **Unless `M=0`.** `M` counts the targeted F-IDs a re-review could cover, and
   a claim finding closed by deletion or by a pin is not one of them (*Re-review
   fan-out*, below). An iteration whose every targeted finding closed that way
   therefore has `M=0`, falls off the first row of the fan-out table, and **runs
   no round**: there is no behaviour to review, and no fix diff for an
   assignment to own. `M=0` licenses skipping this step and nothing else does —
   one behavioural fix in the same iteration puts `M` back above zero and the
   round is owed in full, over every fix diff including the claim closures'
   neighbours. The ledger update and the Iteration-log row still happen; only
   the fan-out is skipped.

   **A round correctly not run is recorded, not omitted.** An absent round and a
   skipped review read identically on the `RV` line, which is the failure that
   line exists to catch, so the iteration writes itself in the same per-round
   grammar with `no round` where the reviewer counts would go:

   ```markdown
         → round 3: M=0 → no round · claim closures: F-018 deleted,
           F-019 pinned by `tests/test_x.py::test_claim` → no findings
   ```

   The ordinal is the round that iteration owed, so the sequence has no gap a
   reader has to interpret. `M=0` is the only declaration that licenses `no
   round`, and the round closes on the F-IDs plus each one's route — `deleted`,
   or `pinned by <test>` naming the test — each of which must match that F-ID's
   `Closed by` cell in the ledger. There is no `reports` field and no `coverage`
   field, because there were no reviewers to file either; those two fields are
   what a round of nobody can carry in their place. A `no round` whose routes
   are unnamed, or that names an F-ID the ledger closed some other way, is a
   skipped review wearing this form.

   **What this does to the `RV` line depends on whether the fan-out has run.**
   A fix loop can be entered from step 1 — a wave's build gates failing is a bug
   finding before any reviewer exists (`parallel.md`). In that case `RV` is
   still `[ ]` and **stays `[ ]`**: a re-review over fix commits is not the
   phase review, and closing `RV` on it would tick the box with no slice
   reviewer having seen the phase diff — the exact failure the line exists to
   catch, wearing a green tick. Such a round also gets **its own Counters row**
   (`<phase> pre-RV`), never the phase's review budget: gates failing three
   times during implementation must not leave the real review two iterations.

   Only when `RV` is already `[x]` from a completed step 2 does a re-review
   reopen it to `[~]` and reclose it with the round appended in the full
   per-round grammar — `→ round 2: M=9 → 3 slice + 1 integration · reports
   p3-rr2-{a,b,c,int}.md · coverage p3-rr2-coverage.md → F-012 closed, F-014
   raised` — so every round has a declared number its file count is checked
   against, not only the first. `M` is the targeted F-ID count and the fan-out
   is `ceil(M/3)`. Whoever ran the round writes it, at whatever depth.
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
- **A claim finding closed by deletion or by a pin is not counted in `M`, and
  its fix commit is not in that union.** It opens no re-review round at all
  (*Finding-closure ledger*, above), so counting it would size a round nobody
  needs and demand an owner for a diff with no behaviour in it. Every other
  commit the fix-mode run produced still needs one.
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
- **Every `[x]` task carries a commit hash** (or `` `nocommit` `` + reason).
  Slice ranges, resume verification and fix-diff checks all read those hashes.
- **Every `[x]` `RV`/`RVJ` round carries its evidence** — one `agent-output/`
  file per reviewer, counted against the reviewers *that round* declares, plus a
  coverage file ending `COVERED: <n>/<n>`, and the F-IDs or `no findings` — or
  the quoted user waiver. A phase is never advanced, and Stage 5
  never entered, with an `RV`/`RVJ` still open: that state means implemented and
  unreviewed, and no other check in this file detects it, because they all read
  a ledger that an unrun review leaves empty.
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
- Counters are **per phase** (iteration) — with separate rows for an `RVJ` and
  for any pre-`RV` fix loop, so neither spends the phase's review budget — and
  **per recursion chain** (depth),
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
- A blocking finding is closed only via one of the finding-closure ledger's
  routes — fixed and verified, user-ruled false positive, or, for a claim
  finding, the claim deleted or pinned with a test. Which route forbids what
  differs: a **fixed-and-verified** closure is never granted by a review round
  that didn't cover its fix, while a **deletion-or-pin** closure opens no round
  for any review to cover and is not made suspect by that.
- Never advance a phase with an open Critical/Major/bug ledger entry.
- Never advance a phase with failing tests or a broken build on its changes.
- Never advance a phase with an unanswered ambiguity question.
- Never block a phase on Minor-only findings — but carry every Minor finding
  to the Stage 5 hand-off; they are deferred, never discarded.
- Fix-mode is set **only** by this loop, never by the user.