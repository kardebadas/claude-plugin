# Pipeline — Progress Tracker

A fixture run directory, not a real one. Its job is the one state no other
fixture can hold: **two concurrent lanes at different legal positions.** Before
it existed every per-lane arm was exercised by mutants alone and the conforming
shape had no input at all — which is how an arm that fails legal input ships.

The graph is the canonical diamond, `Phase 1 → Phase 2, Phase 3 → Phase 4`.
`Phase 1` forks: `Phase 2` is first in approved-plan order so it keeps `Lane A`,
and `Phase 3` takes the newly allocated `Lane B`. `Phase 4` joins, and it
carries `Lane A` because `Phase 2` is its **first contributing predecessor in
approved-plan order** — the survivor is decided at GATE 2 and written down,
never picked at runtime.

`Phase 2` is `PASS` while `Phase 3` is still open, which is exactly the state
the old global comparison hard-failed: it compared the latest named position
against the earliest unfinished phase anywhere, so `Lane B` legitimately at
`Phase 3` while `Lane A` had nothing of its own unfinished made it fire.

`Lane A` writes `waiting at join Phase 4` rather than naming `Phase 4` — a
waiting contributor never names the joining phase, which is what keeps "two
active lanes never execute the same phase" true. `Phase 4`'s leading `RVJ` is
`[ ]`, so `Lane A` is a contributor waiting, not retired, and its line must be
present.

## Current State
- **Lane A:** waiting at join Phase 4
- **Lane B:** Phase 3 — T3
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-lanes/

## Phase 1 — fixture, the fork · deps: none · lane: A
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, the first branch, keeps the forking lane · deps: Phase 1 · lane: A
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p2-review-a.md · coverage p2-coverage.md → no findings

## Phase 3 — fixture, the second branch, still open · deps: Phase 1 · lane: B
- [ ] T3 — a task · W1 · deps T1
- [ ] RV — review fan-out

## Phase 4 — fixture, the join · deps: Phase 2, Phase 3 · lane: A
- [ ] RVJ — joint integration review · lanes A+B
- [ ] T4 — a task · W1 · deps T2, T3
- [ ] RV — review fan-out
