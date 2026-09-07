# Pipeline — Findings Ledger (fixture)

A fixture, not a run. `F-201` is the LEADING `RVJ`'s own blocking finding,
closed through a round appended under that same `RVJ`. It is `closed`, which is
the population the gate-ownership arm reads — the open-blocker population the
no-advance arm uses would never see it.

Nothing is open, and that matters here: `Phase 4` is unfinished because its
tasks are unchecked and its `RV` is `[ ]`, not because a finding is open. The
leading `RVJ` closing let the phase start; it did not complete it.

## Blocking ledger

| ID | Sev | Phase | File:line | Finding | State | Closed by |
| -- | --- | ----- | --------- | ------- | ----- | --------- |
| F-201 | Critical | 4 | `src/join.py:12` | a fixture finding raised by the lane join's review | closed | fix `2020202` + re-review round 2 under the leading RVJ covered it |

## Counters

| Scope | Fix-loop iteration | Cap | Deepest fix-mode depth this chain | Cap |
| ----- | ------------------ | --- | --------------------------------- | --- |
| Phase 4 RVJ | 1 | 5 | 1 | 2 |

## Iteration log (convergence rule input)

| Iter | Scope | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | Phase 4 RVJ | 1 | F-201 | none | 2026-09-07 12:00 |

## Deferred Minor findings

| ID | Phase | File:line | Finding |
| -- | ----- | --------- | ------- |
