# Phase 2 — fix plan, round 2 (fixture)

**Findings in scope:** F-001, F-002
**Out of scope, and why:** none

## Fixes

| # | F-IDs | Root cause | Files / components | Depends on | Verified by |
|---|-------|------------|--------------------|------------|-------------|
| 1 | F-001, F-002 | one fixture cause | `src/a.py`, `src/b.py` | — | `fixture test command` |

One row, so one fix agent: both findings sit in one file cluster, which is why
the round declares `C=1`.

## Parallelism

All sequential; there is one row.

## Tests required

- New or changed tests: none — this is a fixture.
- Command that must be green before RE_REVIEW: `fixture test command`

## How RE_REVIEW will check this

One file cluster, so the round takes one slice reviewer. Round 2 closed F-001;
F-002 stayed open, which is why the ledger still holds it and why a round 3 is
owed a fix plan of its own.
