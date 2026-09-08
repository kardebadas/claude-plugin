<!-- Copy to <run-dir>/agent-output/p<phase>-fixplan-r<round>.md and fill in.
     Written BEFORE any fix agent is dispatched, and named on the round in
     progress.md. Much smaller than the implementation plan: ordinary fixes do
     not re-enter brainstorming or the master plan. What it exists for is that
     remediation is a plan someone can check, not a sequence of reactions to
     whichever finding was read last. -->

# Phase <id> — fix plan, round <r>

**Findings in scope:** <F-IDs, one per fix below; every blocking F-ID this
round targets and nothing else>
**Out of scope, and why:** <F-IDs deferred as Minor, or ruled false positive
with the user's answer; or "none">

## Fixes

| # | F-IDs | Root cause (or "unknown — diagnosis first") | Files / components | Depends on | Verified by |
|---|-------|---------------------------------------------|--------------------|------------|-------------|
| 1 | F-001, F-004 | <one line> | `src/x.php`, `src/y.php` | — | `<test command>` |
| 2 | F-002 | <one line> | `src/z.php` | fix 1 | `<test command>` |

One row per **fix agent**, not per finding: related findings in one file cluster
are one row. Five findings across two clusters are two rows, not five.

## Parallelism

<Which rows may run concurrently, and which must not because they touch the
same files or one depends on the other. "All sequential" is a valid answer.>

## Tests required

- New or changed tests: <list, or "none — the existing covering tests fail on
  these findings today", which must be true and checked>
- Command that must be green before RE_REVIEW: `<command>`

## How RE_REVIEW will check this

<The fix diff's file clusters, which is what sizes the re-review as `C=<n>`,
plus anything a reviewer should look at for regressions between fixes.>
