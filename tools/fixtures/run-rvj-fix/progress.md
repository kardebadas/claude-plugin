# Pipeline — Progress Tracker

A fixture run directory, not a real one. Its job is the state no other fixture
holds: **a TRAILING `RVJ` that raised a blocking finding and carries its own
appended fix round.**

`references/fix-loop.md` requires an `RVJ`'s blocking findings to run the fix
loop under the `RVJ`'s own Counters row, while the reopen rule was written for
`RV` alone — so an `RVJ` fix round had a budget with no defined home, and a run
following the letter of that rule appended it to a phase's `RV`. That is the
wrong gate's evidence, and until rounds were attributed to their owning gate
nothing could see the difference: `kind` is `round` for every appended record.

Phase 2 is a Rule 3 split's last sibling, so its `RVJ` sits **below** the tasks
— a trailing `RVJ`, which reviews the split as a unit and whose clean closure
advances the run to the next phase. It named `F-101`, a Critical, and the fix
round is appended **under the `RVJ` itself**. Move that round under Phase 2's
`RV` and the gate-ownership arm fires; delete it and the arm fires too.

Phase 2's own `RV` is closed with no findings, which is what makes this fixture
precise: the `RVJ`'s round cannot be mistaken for the `RV`'s.

## Current State
- **Lane A:** done (fixture)
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-rvj-fix/

## Phase 1 — fixture, closed · deps: none · lane: A
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, a split's last sibling with a trailing RVJ · deps: Phase 1 · lane: A
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] T3 — a task · W1 · deps T1 — `ccccccc`
- [x] RV — review fan-out · N=2 → 1 slice + 0 integration
      · reports p2-review-a.md · coverage p2-coverage.md → no findings
- [x] RVJ — joint integration review · split 2a+2b · N=2 → 0 slice + 1 integration
      · reports j2-int.md · coverage j2-coverage.md → F-101
      → round 2: M=1 C=1 → 1 slice + 0 integration · fixplan j2-fixplan-r2.md
        · reports j2-rr2-a.md · coverage j2-rr2-coverage.md → F-101 closed

## Phase 3 — fixture, the last phase, its RV the final record · deps: Phase 2 · lane: A
- [x] T4 — a task · W1 · deps T3 — `ddddddd`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p3-review-a.md · coverage p3-coverage.md → no findings

## Notes

**Prose after the last record, deliberately.** A record is bounded by the next
bullet **or the next heading**; the final record of a tracker has no following
bullet, so without the heading boundary it runs to end-of-file and swallows
whatever follows. This section ends with an outcome-shaped phrase naming a
finding the ledger records as closed and blocking → F-101 — so absorbing it
would rewrite Phase 3's `RV` outcome and demand a fix round of a gate that
raised nothing.

