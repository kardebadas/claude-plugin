<!--
TEMPLATE — read-only. Copy to the run directory, then delete this comment:
  <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/progress.md
Keep the Current State block at the very top at all times.
-->

# Pipeline — Progress Tracker

## Current State
- **Phase:** <current phase number and name>
- **Next action:** <the single next unchecked task>
- **Last updated:** <timestamp>
- **Run directory:** <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/

## Phase 1 — <name> · deps: none
- [x] T1 — <task name> · W1 · deps none — `a1b2c3d`
- [~] T2 — <task name> · W2 · deps T1 — started <timestamp> in wt/p1-t2
- [~] T3 — <task name> · W2 · deps T1 — started <timestamp> in wt/p1-t3
- [ ] T4 — <task name> · W3 · deps T2, T3

## Phase 2 — <name> · deps: Phase 1
- [ ] T1 — <task name> · W1 · deps none

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
-->
