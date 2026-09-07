# Pipeline — Findings Ledger (fixture)

A fixture, not a run. **An empty ledger is not a clean run**, and this file
exists so the no-advance arm's ledger half has a conforming input: `F-002` is
`open` at `Major` against `Phase 2`, which is what holds the run inside Phase 2
while every box in that phase is `[x]`.

## Blocking ledger

| ID | Sev | Phase | File:line | Finding | State | Closed by |
| -- | --- | ----- | --------- | ------- | ----- | --------- |
| F-001 | Critical | 2 | `src/a.py:10` | a fixture finding | closed | fix `f1f1f1f` + re-review round 2 covered it |
| F-002 | Major | 2 | `src/b.py:20` | a fixture finding still open | open | |

## Counters

| Scope | Fix-loop iteration | Cap | Deepest fix-mode depth this chain | Cap |
| ----- | ------------------ | --- | --------------------------------- | --- |
| Phase 2 | 1 | 5 | 1 | 2 |

## Iteration log (convergence rule input)

| Iter | Scope | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | Phase 2 | 1 | F-001, F-002 | F-002 | 2026-09-07 10:00 |

## Deferred Minor findings

| ID | Phase | File:line | Finding |
| -- | ----- | --------- | ------- |
