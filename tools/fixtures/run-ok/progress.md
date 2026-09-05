# Pipeline — Progress Tracker

A fixture run directory, not a real one. It exists so `check-plugin.sh --run`
has a conforming input to prove itself against, and so the mutants in
tools/check-plugin-mutants.sh have something they can break. Both review
records below are closed and conforming; one names a single report file and
one names a brace-expanded set, because those are the two report-set forms the
grammar writes and the expansion is what makes the second one checkable.

## Current State
- **Phase:** done (fixture)
- **Next action:** none; this run directory is a linter fixture
- **Last updated:** 2026-09-05
- **Run directory:** tools/fixtures/run-ok/

## Phase 1 — fixture, single report file · deps: none
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, brace-expanded report set · deps: Phase 1
- [x] T2 — another task · W1 · deps T1 — `bbbbbbb`
- [x] RV — review fan-out · N=8 → 2 slice + 1 integration
      · reports p2-review-{a,b,int}.md · coverage p2-coverage.md → no findings
