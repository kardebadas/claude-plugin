# Pipeline — Progress Tracker

A fixture run directory, not a real one. Its job is the state where **every box
is `[x]` and the phase is still not complete**: Phase 2's tasks are `[x]`, its
`RV` is `[x]` over two closed rounds, and `findings.md` holds `F-002` open.

The tracker's own "next unchecked line" rule points at Phase 3 from here, which
is exactly the bug the ledger precedence exists to stop — every gate phrased as
"no open blocking IDs" is vacuously true when review never ran, and every gate
phrased as "next unchecked line" walks straight past a fix loop interrupted
mid-round. So `Lane A` names Phase 2's fix loop instead, and the no-advance
arm reads the ledger to agree with it.

This is the run directory that exercises the **ledger half** of that arm. It is
the only fixture with a `findings.md`, which is why `tools/fixtures/run-ok`'s
pass line says the ledger half went unchecked there: an absent ledger must never
read as an empty one.

Round 3 is the fixture's `M=0 → no round` record, and its **outcome names an
F-ID rather than `no findings`** — `→ F-002 still open`, which is what the
iteration log records for that iteration too. That is the second legal outcome
form, and it is here because a closures parser that stops only at
`→ no findings` reads this one as a closure with no route: the round's own
result reported as a bad route. Both closure routes are explicit, and neither
names a commit.

Round 2 is a **planned** round — it names its `fixplan` file, present in
`agent-output/` — so the fix-plan arm has a second conforming input over a real
run, on a round that is not the one in `run-ok`.

## Current State
- **Lane A:** Phase 2 — fix loop round 4, write the round's fix plan for F-002
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-fixloop/

## Phase 1 — fixture, closed · deps: none · lane: A
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, implemented and reviewed, a finding still open · deps: Phase 1 · lane: A
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] T3 — a task · W1 · deps T1 — `ccccccc`
- [x] RV — review fan-out · N=2 → 1 slice + 0 integration
      · reports p2-review-a.md · coverage p2-coverage.md → F-001, F-002
      → round 2: M=2 C=1 → 1 slice + 0 integration · fixplan p2-fixplan-r2.md
        · reports p2-rr2-a.md · coverage p2-rr2-coverage.md → F-001 closed, F-004, F-005
      → round 3: M=0 → no round · closures: F-004 user-ruled false positive,
        F-005 withdrawn → malformed → F-002 still open

## Phase 3 — fixture, not started · deps: Phase 2 · lane: A
- [ ] T4 — a task · W1 · deps T3
- [ ] RV — review fan-out
