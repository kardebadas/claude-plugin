# Pipeline — Progress Tracker

A fixture run directory, not a real one. Its job is the complete **leading-RVJ
remediation and collapse** path, which no other fixture holds:

```
Phase 2 PASS
Phase 3 PASS
→ leading RVJ (above Phase 4's first task)
→ blocking finding F-201
→ FIX PLAN → FIX → RE-REVIEW UNDER THE SAME LEADING RVJ
→ CLOSE(leading RVJ)
→ retire Lane B
→ Lane A enters Phase 4's IMPLEMENT
```

The graph is the canonical diamond, `Phase 1 → Phase 2, Phase 3 → Phase 4`.
`Phase 2` is first in approved-plan order so it keeps `Lane A`; `Phase 3` takes
the newly allocated `Lane B`; `Phase 4` carries `Lane A` because `Phase 2` is
its first contributing predecessor in approved-plan order. The survivor was
decided at GATE 2, not at runtime.

**`Phase 4` is NOT `PASS`.** Its leading `RVJ` is closed, which is what let the
phase START — it reviewed the lanes that merged here, not this phase's own
tasks. `T4` is unchecked and `RV` is `[ ]`, so `Phase 4` still owes
`IMPLEMENT → RV → CLOSE(RV) → PASS`. A clean leading `RVJ` must never mark the
joining phase `PASS`, and this fixture is what proves the gate agrees.

**`Lane B` is retired and carries no Current State line.** The leading `RVJ`
closing is what retires it; leaving the line would say a branch is still
executing that the run has already folded in. Its id is never allocated again.

The `RVJ`'s fix round is appended **under the `RVJ` itself**, not under
`Phase 4`'s `RV`. Move it and the gate-ownership arm fires: a blocking finding
closed under another gate's line leaves this gate's evidence claiming a clean
review it never got.

## Current State
- **Lane A:** Phase 4 — T4
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-leading-rvj-fix/

## Phase 1 — fixture, the fork · deps: none · lane: A
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, the first branch, keeps the forking lane · deps: Phase 1 · lane: A
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p2-review-a.md · coverage p2-coverage.md → no findings

## Phase 3 — fixture, the second branch, a newly allocated lane · deps: Phase 1 · lane: B
- [x] T3 — a task · W1 · deps T1 — `ccccccc`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p3-review-a.md · coverage p3-coverage.md → no findings

## Phase 4 — fixture, the join, entered but not passed · deps: Phase 2, Phase 3 · lane: A
- [x] RVJ — joint integration review · lanes A+B · N=2 → 0 slice + 1 integration
      · reports j4-int.md · coverage j4-coverage.md → F-201
      → round 2: M=1 C=1 → 1 slice + 0 integration · fixplan j4-fixplan-r2.md
        · reports j4-rr2-a.md · coverage j4-rr2-coverage.md → F-201 closed
- [ ] T4 — a task · W1 · deps T2, T3
- [ ] RV — review fan-out
