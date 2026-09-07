# Phase 3 — fix plan, round 2 (fixture)

**Findings in scope:** F-001, F-002
**Out of scope, and why:** none

## Fixes

| # | F-IDs | Root cause | Files / components | Depends on | Verified by |
|---|-------|------------|--------------------|------------|-------------|
| 1 | F-001, F-002 | one fixture cause | `src/fixture.py` | — | `fixture test command` |

One row, so one fix agent: both findings sit in the same file cluster. This is a
fixture, not a run — it exists so the `fixplan` arm has a conforming input, and
so the mutants that remove or misname it have something to break.

## Parallelism

All sequential; there is one row.

## Tests required

- New or changed tests: none — the fixture's covering test stands in for them.
- Command that must be green before RE_REVIEW: `fixture test command`

## How RE_REVIEW will check this

One file cluster, so the round declares `C=1` and takes one slice reviewer.
