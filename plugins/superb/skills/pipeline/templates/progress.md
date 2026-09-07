<!--
TEMPLATE — read-only. Copy to the run directory, then delete this comment:
  <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/progress.md
Keep the Current State block at the very top at all times.
-->

# Pipeline — Progress Tracker

## Current State
- **Phase:** <phase id FIRST, then an em dash and whatever prose helps>
- **Next action:** <the single next unchecked line — task, RV, or RVJ. Lead with
  `Phase <id>` when the action belongs to a phase.>
- **Last updated:** <timestamp>
- **Run directory:** <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/

## Phase 1 — <name> · deps: none
- [x] T1 — <task name> · W1 · deps none — `a1b2c3d`
- [~] T2 — <task name> · W2 · deps T1 — started <timestamp> in wt/p1-t2
- [~] T3 — <task name> · W2 · deps T1 — started <timestamp> in wt/p1-t3
- [ ] T4 — <task name> · W3 · deps T2, T3
- [ ] RV — review fan-out

## Phase 2 — <name> · deps: Phase 1
- [ ] T1 — <task name> · W1 · deps none
- [ ] RV — review fan-out

## Phase 3a — <name> · deps: Phase 2
- [ ] T1 — <task name> · W1 · deps none
- [ ] RV — review fan-out

## Phase 3b — <name> · deps: Phase 2
- [ ] T1 — <task name> · W1 · deps none
- [ ] RV — review fan-out
- [ ] RVJ — joint integration review · split 3a+3b

<!--
Task states:
  [ ] not started
  [~] STARTED, outcome unknown — written before work begins; on cold start this
      MUST be verified against the code before anything else happens
  [x] done — followed by the commit hash that carries it, or `nocommit` with a
      one-line reason
  W<n> / deps — the task wave and in-phase dependencies from the GATE 2 plan
      (Rule 6). Members of one wave may be [~] together, each in its own
      wt/... worktree branch.

**The Phase field's id comes FIRST**, e.g. `- **Phase:** 3 — fix loop, F-002
open`. Everything after the em dash is prose for a human. That is not a style
preference: the advancement check reads the phase this line NAMES, and it reads
it as the leading token — so `**Phase:** 3 — moved on past the phase 2 fix loop`
names phase 3, and a phase mentioned later in the sentence is prose, not the
run's position. A field that does not begin with a phase id names no phase at
all — which is legitimate when nothing is unfinished (`Phase: done`), and is
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
