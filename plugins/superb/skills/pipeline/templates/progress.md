<!--
TEMPLATE — read-only. Copy to the run directory, then delete this comment:
  <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/progress.md
Keep the Current State block at the very top at all times.
-->

# Pipeline — Progress Tracker

## Current State
- **Lane A:** <phase id FIRST, then an em dash and that lane's next unchecked
  line — task, RV, or RVJ>
- **Lane B:** <the second branch, if this run forked; delete this line for a
  sequential run, which has exactly one lane>
- **Last updated:** <timestamp>
- **Run directory:** <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/

## Phase 1 — <name> · deps: none · lane: A
- [x] T1 — <task name> · W1 · deps none — `a1b2c3d`
- [~] T2 — <task name> · W2 · deps T1 — started <timestamp> in wt/p1-t2
- [~] T3 — <task name> · W2 · deps T1 — started <timestamp> in wt/p1-t3
- [ ] T4 — <task name> · W3 · deps T2, T3
- [ ] RV — review fan-out

## Phase 2 — <name> · deps: Phase 1 · lane: A
- [ ] T1 — <task name> · W1 · deps none
- [ ] RV — review fan-out

## Phase 3a — <name> · deps: Phase 2 · lane: A
- [ ] T1 — <task name> · W1 · deps none
- [ ] RV — review fan-out

## Phase 3b — <name> · deps: Phase 2 · lane: B
- [ ] T1 — <task name> · W1 · deps none
- [ ] RV — review fan-out
- [ ] RVJ — joint integration review · split 3a+3b

<!--
Current State grammar:
  ONE LINE PER ACTIVE LANE, and a sequential run has exactly one: `Lane A`.
  `**Lane <id>:**` where <id> matches [A-Z][A-Za-z0-9]*. The value is
  `Phase <phase-id> — <that lane's next unchecked line>`, phase id first.
  Two phase-less values are legal, and both are CLAIMS the gate checks:
    done                        — that lane owns no unfinished task, no open
                                  RV, no unresolved fix loop, no open blocking
                                  finding, and is not a contributor to an
                                  unresolved join
    waiting at join Phase <id>  — this lane's own branch has passed and the
                                  join it feeds has not opened yet. It stays
                                  this while the other contributors finish AND
                                  while the leading RVJ runs -- the whole
                                  window up to CLOSE(leading RVJ). Only the
                                  SURVIVING lane leaves it earlier, to name
                                  `Phase <join> — RVJ` once every contributor
                                  has passed, because running that gate is the
                                  surviving lane's job.
  There is no **Phase:** field and no **Next action:** field. One grammar, no
  mode switch.
  An ACTIVE lane -- one owning unfinished work, or waiting at an unresolved
  join -- has exactly one line. A lane retired by a closed leading RVJ has none.

Phase headings:
  ## Phase <n> — <name> · deps: <phases, or none> · lane: <id>
  `· deps:` says whether a phase MAY execute; `· lane:` says which concurrent
  execution branch executes it. The mapping is written at GATE 2 and never
  recomputed, so `phase -> lane` survives compaction and resume without
  depending on anything the orchestrator remembers.
  A lane is an ACTIVE EXECUTION BRANCH BETWEEN A FORK AND A JOIN, never a
  maximal dependency chain: in a diamond A -> B,C -> D, both A and D sit on two
  maximal chains, so chain membership cannot say which lane owns a phase.
    fork  — the successor FIRST in approved-plan order keeps the forking
            phase's lane; every further successor takes the next unused id
    join  — the joining phase carries the lane of its FIRST CONTRIBUTING
            PREDECESSOR in approved-plan order. That lane survives; the others
            retire when the leading RVJ closes, and a retired id is never reused
  A clean leading RVJ lets the joining phase START. It never marks it PASS --
  the phase still owes IMPLEMENT -> RV -> CLOSE(RV) -> PASS on its own tasks.
  A Rule 3 split forks: its siblings take their own lanes and its TRAILING RVJ
  reviews them as a unit. What happens to those lanes depends on what follows.
  If a later phase depends on two or more of the siblings, that phase IS a lane
  join -- it carries a LEADING RVJ of its own and collapses the lanes onto the
  surviving one, exactly as any join does; the trailing RVJ reviewed the split,
  the leading one reviews the merge into the phase that consumes it. If nothing
  consumes them together, the lanes simply end at `done` when their work is
  finished.

Task states:
  [ ] not started
  [~] STARTED, outcome unknown — written before work begins; on cold start this
      MUST be verified against the code before anything else happens
  [x] done — followed by the commit hash that carries it, or `nocommit` with a
      one-line reason
  W<n> / deps — the task wave and in-phase dependencies from the GATE 2 plan
      (Rule 6). Members of one wave may be [~] together, each in its own
      wt/... worktree branch.

**A lane line's phase id comes FIRST**, e.g. `- **Lane A:** 3 — fix loop, F-002
open`. Everything after the em dash is prose for a human. That is not a style
preference: the advancement check reads the phase this line NAMES, and it reads
it as the leading token — so `**Lane A:** 3 — moved on past the phase 2 fix loop`
names phase 3, and a phase mentioned later in the sentence is prose, not the
lane's position. A line that does not begin with a phase id names no phase at
all — which is legitimate in the two phase-less forms above, and is
reported as uncheckable when something is: the gate cannot compare a position it
cannot locate, and it says so rather than guessing which number was meant.

RV — the review line. Every IMPLEMENTATION phase has exactly one, last among
     its own task lines. (A split's RVJ trails it; a joining phase's RVJ leads,
     sitting above that phase's first task.) Stages 1-5 seeded at
     Stage 1 are scaffolding; no RV. Not a task: excluded from Rule 3's 12-cap
     and from N in ceil(N/5).
     i is 0 at one slice. Above one slice i is 1 only at a DECLARED
     integration boundary - a split's siblings joining, two lanes joining, or
     a contract introduced in one slice and consumed in another - named as
     `boundary: <what>`; otherwise i is 0 and the round carries
     `no integration boundary`, so an omission and a judgement never read
     the same.
     A fix round (M=<m>, m>=1) also names its fixplan file: the round's fix
     plan, written before its first fix was dispatched. An M=0 -> no round
     record carries none - no fix ran, so there was nothing to plan.

  [ ] RV — review fan-out
  [~] RV — review fan-out · N=8 -> 2 slice + 1 integration · started <ts>
  [x] RV — review fan-out · N=8 -> 2 slice + 1 integration · boundary: the T3 contract consumed by T7
      · reports p3-review-{a,b,int}.md · coverage p3-coverage.md -> F-012, F-013
  [x] RV — review fan-out · N=8 -> 2 slice + 0 integration · no integration boundary
      · reports p5-review-{a,b}.md · coverage p5-coverage.md -> no findings
  [x] RV — review fan-out · N=8 -> 2 slice + 1 integration · boundary: the T3 contract consumed by T7
      · reports p3-review-{a,b,int}.md · coverage p3-coverage.md -> F-012
      -> round 2: M=1 C=1 -> 1 slice + 0 integration
         · fixplan p3-fixplan-r2.md · reports p3-rr2-a.md
         · coverage p3-rr2-coverage.md -> F-012 closed
  [x] RV — review fan-out · WAIVED by user: "<their exact words>"

RVJ — joint integration review of a unit no single RV covers: a Rule 3 split,
     or a phase whose deps span two or more lanes. Always 0 slice +
     1 integration. Its OWN Counters row. Placed AFTER a split's last sibling,
     or ABOVE the first task of a joining phase.

  [ ] RVJ — joint integration review · split 3a+3b
  [x] RVJ — joint integration review · lanes A+B (phases 5, 6) · N=17 -> 0 slice + 1 integration
      · reports j-56-int.md · coverage j-56-coverage.md -> no findings

A phase whose RV (or a split's RVJ) is not [x] is NOT complete, however many
of its tasks are. Never write a Current State that skips one.

Full grammar and closure conditions -- what `reports` and `coverage` must
contain, and why an [x] with fewer files than declared reviewers does not
close -- are in references/run-state.md, "progress.md — task line grammar".
-->
