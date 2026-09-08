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

**Phase 3 carries a LEADING `RVJ`** — above its first task, which is where the
skill's templates put a joining phase's line — and that is the only conforming
`RVJ` in this fixture, and the shape arms read it over a real tracker here as
well as in `run-rvj-fix` and `run-leading-rvj-fix`. It is also the shape that must NOT trip the review-not-early
arm: an `RVJ` above the first task reviews the lanes that merged into this phase,
not this phase's own tasks, so Phase 3 legitimately has a closed review line and
five unchecked tasks at once. Move it below the tasks and it becomes a trailing
`RVJ`, which does review this phase and must then fail.

`Lane A` names Phase 2's `RV`, which is what the no-advance arm reads: point
it at a later phase and that arm fires. Every heading carries `· lane: A` — a
sequential run is exactly one lane. And Phase 2 has a `[ ]` `RV` above
open work in Phase 3, so the review-not-early arm sees a phase with open tasks
and **no** started round — the legal shape, and the one that arm must not
report.

## Current State
- **Lane A:** Phase 2 — RV
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-open-rv/

## Phase 1 — fixture, closed · deps: none · lane: A
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, implemented and unreviewed · deps: Phase 1 · lane: A
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] T3 — a task · W1 · deps T1 — `ccccccc`
- [x] T4 — a task · W2 · deps T2 — `ddddddd`
- [x] T5 — a task · W2 · deps T3 — `eeeeeee`
- [ ] RV — review fan-out

## Phase 3 — fixture, a phase carrying a leading RVJ, not started · deps: Phase 2 · lane: A
- [x] RVJ — joint integration review · split 2a+2b · N=5 → 0 slice + 1 integration
      · reports p3-rvj-int.md · coverage p3-rvj-coverage.md → no findings
- [ ] T6 — a task · W1 · deps T4
- [ ] RV — review fan-out
