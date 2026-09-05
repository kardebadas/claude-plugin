# Superpipeline: run state on disk

Everything the run knows lives in the run directory. The orchestrator's context
is a cache of these files, never the other way round.

```
<PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/
  progress.md        # the tracker — phases, tasks, Current State
  register.md        # Assumptions Register
  findings.md        # blocking ledger (F-IDs), iteration history, deferred Minors
  kit.md             # the run's shared verification apparatus (written at GATE 2)
  agent-output/      # one file per dispatch; long subagent output lands here
```

`templates/` ships a template for each of these files. They are **read-only** —
copy, never edit in place. `kit.md` alone is filled in later, at GATE 2 from the
approved plan, because it cannot name a run's gates before the plan does.

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
3. Otherwise create it, copy the templates in — all but `kit.md`, which GATE 2
   writes — strip their comments, and state the full directory path in your
   first message to the user.

Fix-mode recursions **inherit** the enclosing run's directory. They never create
one.

## progress.md — task line grammar

```
- [ ] T3 — <task name> · W2 · deps T1
- [~] T3 — <task name> · W2 · deps T1 — started 2026-08-05 14:02 in `wt/p2-t3`
- [x] T3 — <task name> · W2 · deps T1 — `a1b2c3d`
- [x] T4 — <task name> · W3 · deps T3 — `nocommit` (docs only, folded into T5's commit)
- [ ] RV — review fan-out
- [~] RV — review fan-out · N=8 → 2 slice + 1 integration · started 2026-09-01 14:31
- [x] RV — review fan-out · N=8 → 2 slice + 1 integration · reports p3-review-{a,b,int}.md · coverage p3-coverage.md → F-012, F-013
- [x] RV — review fan-out · N=3 → 1 slice + 0 integration · reports p2-review-a.md · coverage p2-coverage.md → no findings
- [x] RV — review fan-out · N=12 waved → 2 slice + 1 integration · reports p4-review-{a,b,int}.md · coverage p4-coverage.md → F-021
- [x] RV — review fan-out · WAIVED by user: "skip the code review on this one"
- [ ] RVJ — joint integration review · split 4a+4b
- [x] RVJ — joint integration review · lanes A+B (phases 5, 6) · N=17 → 0 slice + 1 integration · reports j-56-int.md · coverage j-56-coverage.md → no findings
```

`W<n>` is the task's wave and `deps` its in-phase dependencies, both copied
from the GATE 2 plan (Rule 6, `parallel.md`). A `[~]` line in a multi-member
wave also names the worktree branch the member runs in, so a cold start knows
where to look for its commits. Phase headings carry `· deps: <phases>`.

| Marker | Meaning |
|--------|---------|
| `[ ]` | Not started. Nothing was dispatched for it. |
| `[~]` | **Started, outcome unknown.** Written *before* the work begins. |
| `[x]` | Done, followed by the commit hash that carries it — except `RV`/`RVJ`, which close on reviewer evidence (see below). |

**Write `[~]` before dispatching the task, not after.** That single write is
what makes a dead session recoverable: without it, a half-applied task is
indistinguishable from an untouched one.

**Every `[x]` task carries a hash.** Record the short hash of the commit
containing that task's work. If a task genuinely produced no commit, write
`` `nocommit` `` with a one-line reason — never leave the field blank, because a
blank field is unverifiable and that is the whole point of recording it.

**`RV`/`RVJ` are the exception in what they carry, not in whether they are
checkable.** They produced review, not code, so instead of a hash they close on
four fields, all paths relative to `agent-output/`:

- `N=<tasks> → <s> slice + <i> integration` — `N` is on the line so the fan-out
  is re-derivable at closure rather than trusted from the step most likely to
  have been skipped. An **unwaved** phase takes `s = ceil(N/5)`; a **waved** one
  takes a slice per wave or adjacent wave-pair (write `waved` after `N`), which
  may be more or fewer; an **`M=`** re-review writes its cluster count on the
  line as `C=<n>` — `M=9 C=3 → 3 slice + 1 integration` — and `s` must equal
  `C` (the cluster rule, and what declaring `C` does and does not establish, is
  in `fix-loop.md`'s *Re-review fan-out*); an **`RVJ`** is always
  `0 slice + 1 integration` with `N` informational. `i` is 1 whenever `s > 1`.
- `reports <files>` — **exactly `s + i` files, one per reviewer**, each the
  `DETAIL:` path that reviewer returned. A review dispatch always requires its
  report file, clean or not — the "omit `DETAIL:` if nothing is longer" licence
  below does not reach reviewers, or a clean phase could never close. The
  coverage file is never counted here.
- `coverage <file>` — the slice assignment table, **each row keyed by its report
  filename**, above the `git log --oneline PB..PH`, ending `COVERED: <n>/<n>
  commits`. Record slices individually: one union range reads as complete even
  when two slices leave a gap between them, and that gap is the defect being
  hunted. **No two rows carry the same range** — two reviewers over one range
  read the same diff, and the integration reviewer's row is the union of the
  slices, so it is not equal to any one of them either. Derive `PB` with
  `git merge-base`, never `<first-task-hash>^`.
- `→ <F-IDs>` or `→ no findings`.

Every field is **per round**; re-review rounds append their own `M=… → …`,
`reports` and `coverage`, and the counts are read against their own round.

The one round that carries neither `reports` nor `coverage` is **`M=0 → no
round`**, written when a fix iteration's every targeted F-ID was closed by a
route that leaves no ownable commit, so no reviewer was ever owed a fix diff
(`fix-loop.md`, fix loop step 3, which holds the closed list of those routes).
`no round` stands where the reviewer counts would, `M=0` is the only
declaration that licenses it, and it closes on the F-IDs plus each one's route,
matching those rows' `Closed by` cells. **A pin is not a route this form can
carry**: it commits a test, so it stays in `M` and that commit is owed a
reviewer. It is **recorded, never omitted**: a round nobody had to run and a
round somebody skipped are otherwise the same absence on this line.

The `[ ]` form carries none of it — at GATE 2 no task has a hash and the slice
count is not yet knowable. Both are filled in at dispatch.

Hashes buy three things: resume verification becomes `git cat-file -e <hash>`
rather than a judgment call; a reviewer slice becomes an exact commit range
instead of a fuzzy "contiguous ~5 tasks"; and the ledger's "the fix diff
touched the code the finding names" test becomes a diff anyone can re-run.

## Cold-start resume protocol

A cold start is any of: a new session, a context compaction, a resumed run, or
your own uncertainty about what just happened. Run this **before any other
action** — before dispatching, before reading a plan doc, before writing code.

1. Read `progress.md` in full, then `findings.md`, then `register.md`.
2. **Scan for `[~]` lines. Every one is a reconciliation obligation.** An
   `[~]` **`RV`/`RVJ`** reconciles against `agent-output/`, never against the
   code: reviewer reports present and consolidated into `findings.md` → `[x]`
   with its evidence; present but never consolidated → consolidate them now;
   nothing there → back to `[ ]` and run the fan-out. Never resolve one by
   reading the diff yourself — you would be reviewing it, which is the thing
   the line records someone else doing. For each `[~]` **task**:
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
3. Only when zero `[~]` lines remain may the run continue. Take the next action
   from the phase lists — **the first unchecked line, which may be an `RV` or
   `RVJ`** — and correct the Current State block if it names anything later.
   Not from what you remember doing.

**A `[~]` task is never assumed done because it looks done, and never assumed
untouched because you don't remember it.** Verify against the code.

## Resume Protocol (`/superb:pipeline resume`)

The user-invoked path back into an interrupted run. It wraps the cold-start
protocol above with candidate selection and a reporting step. **This mode never
starts a new run** — if step 1 finds nothing, report that and stop.

1. **Find candidate run directories** under `<PROJECT_DIR>/docs/superpowers/runs/`.
   - **Exactly one with unfinished work** (any `[ ]` or `[~]` line — task,
     `RV`, or `RVJ` — open register entry, or open blocking F-ID) → use it.
     **`RV` counts.** A run whose every task is `[x]` but whose `RV` lines are
     open is the most important run there is to resume: it is fully implemented
     and entirely unreviewed, and a predicate that looked only at tasks would
     report "no run to resume" over exactly that state.
   - **Multiple candidates, or none obviously active** → show each one's
     Current State block and **ask the user which to resume**. Recency is not
     consent: the newest directory is a guess about someone's unfinished work,
     not an answer.
   - **Zero** → report "no run to resume" and stop. Starting a fresh run from
     `resume` is forbidden — that's what the bare invocation is for. (`status`
     shares this candidate logic but not this outcome: a run with nothing
     unfinished is still a run to *report on*, so `status` names the most recent
     directory and reports it as complete rather than claiming none exists.)
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
   next line, **any phase whose tasks are all `[x]` with `RV` still open**,
   open F-IDs, open register entries, and anything reconciliation
   surfaced. If reconciliation raised questions — partial `[~]` work whose
   disposition the plan doesn't settle, unexplained commits — these are **user
   questions; wait for the answers**.
6. **If the register has open entries, ask them before resuming
   implementation.** Otherwise continue the Stage 4 loop from the tracker's
   next unchecked line — an open `RV` before any task of a later phase — under
   all normal rules. **An open blocking F-ID outranks that line**: a fix loop
   interrupted mid-round leaves `RV` `[x]` and every task `[x]`, so the tracker's
   next unchecked line points past it. Read the ledger's open IDs and the
   Iteration log's last incomplete row first, and resume the fix loop — this protocol changes how a run is
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

**Every dispatch prompt carries three things besides that return shape, and not
one of them is the agent's to infer.** First, **Rule 5b — derive, don't
restate** (`SKILL.md`): the brief names symbols and the commands that regenerate
facts, and never a count, a line number, a signature or a file list — the
task's own `Files:` block being the one exception that rule names; an agent
handed a stated code fact **refuses the brief and says which fact**, and that
refusal is correct behaviour costing one round trip, where acting on a stale
fact costs the task. Second, **`kit.md`, cited by path** — the agent reads the
suite, coverage and build-gate commands, the baseline discipline, the mutation
harness and the worktree rule out of that one file, because a dispatch that
describes a harness inline is how a run comes to rebuild the same apparatus in
every task, and a dispatch that omits the worktree rule is how two agents come
to mutate the same file in the main tree at once and leave a third chasing the
phantom failure. Third, **the ticket/issue key**, wherever the repo requires one
in a commit subject: the prompt states it, the implementer puts it in the
subject, and it is not theirs to infer from a branch name — it is answered at
Stage 1 and recorded once in `kit.md`'s *Project specifics*, and a `COMMIT:`
hash whose subject is missing the key is a task that has to be redone rather
than a bookkeeping lapse.

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
