# Pipeline — Progress Tracker

A fixture run directory, not a real one. Its job is the one state
`tools/fixtures/run-ok` cannot hold: **a phase fully implemented and entirely
unreviewed.** Phase 2's tasks are all `[x]` with hashes and its `RV` is `[ ]`,
so the only valid next action is Phase 2's review — never Phase 3, and never
re-running T2..T5.

Phase 1 is closed so the tracker has a conforming round for the review-line
linter to read. Without one, `--run` reports that nothing in this run has been
reviewed and a PASS here would mean nothing — which is itself the arm that
makes this fixture safe to add.

`Next action` names Phase 2's `RV`, which is what the no-advance arm reads:
point it at a later phase and that arm fires. And Phase 2 has a `[ ]` `RV` above
open work in Phase 3, so the review-not-early arm sees a phase with open tasks
and **no** started round — the legal shape, and the one that arm must not
report.

## Current State
- **Phase:** 2 — implemented, unreviewed
- **Next action:** Phase 2 RV — review fan-out over the phase branch
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-open-rv/

## Phase 1 — fixture, closed · deps: none
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, implemented and unreviewed · deps: Phase 1
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] T3 — a task · W1 · deps T1 — `ccccccc`
- [x] T4 — a task · W2 · deps T2 — `ddddddd`
- [x] T5 — a task · W2 · deps T3 — `eeeeeee`
- [ ] RV — review fan-out

## Phase 3 — fixture, not started · deps: Phase 2
- [ ] T6 — a task · W1 · deps T4
- [ ] RV — review fan-out
