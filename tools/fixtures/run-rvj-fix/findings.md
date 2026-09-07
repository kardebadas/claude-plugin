# Pipeline — Findings Ledger (fixture)

A fixture, not a run. `F-101` is the trailing `RVJ`'s own blocking finding,
closed through a round appended under that same `RVJ`. It is `closed`, not
`open`, on purpose: the gate-ownership arm asks a historical question — was
this gate's blocking finding closed under this gate? — and a closed row is
exactly the population it reads. The open-blocker population the no-advance arm
uses would never see it.

## Blocking ledger

| ID | Sev | Phase | File:line | Finding | State | Closed by |
| -- | --- | ----- | --------- | ------- | ----- | --------- |
| F-101 | Critical | 2 | `src/j.py:10` | a fixture finding raised by the joint review | closed | fix `1010101` + re-review round 2 under the RVJ covered it |

## Counters

| Scope | Fix-loop iteration | Cap | Deepest fix-mode depth this chain | Cap |
| ----- | ------------------ | --- | --------------------------------- | --- |
| Phase 2 RVJ | 1 | 5 | 1 | 2 |

## Iteration log (convergence rule input)

| Iter | Scope | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | Phase 2 RVJ | 1 | F-101 | none | 2026-09-07 11:00 |

## Deferred Minor findings

| ID | Phase | File:line | Finding |
| -- | ----- | --------- | ------- |
