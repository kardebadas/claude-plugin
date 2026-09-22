# Worker report

The implementer's long-form report, written to the run's `scratch/` at the path
the controller supplied. It is **evidence, not acceptance**: the task reviewer
treats every line as an unverified claim and re-runs the tests itself.

The durable record is the immutable worker result (`templates/worker-result.md`).
This file exists so neither the diff nor the narrative passes through the
controller's context.

````markdown
# Report — <run-id> / <task-id> / attempt <n> / <owner>

## Status

DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | PLAN_CONFLICT | BLOCKED

## What I implemented

<What was built, or what was attempted before stopping.>

## TDD evidence — REQUIRED for every logic-bearing change

### RED
- Command: <exact command>
- Failing output: <relevant lines, before the implementation existed>
- Why this failure was the expected one: <...>

### GREEN
- Command: <exact command>
- Passing output: <relevant lines>

Config/glue exemption, if claimed: <what had no logic to assert on>

## Tests and suites run

| Command | Outcome | Notes |
| --- | --- | --- |

## Files changed

<repository-relative paths, each inside the declared write scope>

## Commits

<short SHA + subject, in order>

## Decisions this task relied on

<D-ID — how the implementation satisfies it. A provisional task names the
tainting decision.>

## Self-review findings

<What I found and what I changed.>

## Concerns

<Anything that makes DONE_WITH_CONCERNS the honest status.>

## Question record

<Path, for NEEDS_CONTEXT or PLAN_CONFLICT. Otherwise: none.>
````

## Rules

- **Never edit a report after a reviewer has read it.** Append a re-run section.
  A report that changes under a reviewer is indistinguishable from one that was
  wrong.
- A claim that disagrees with the reviewer's own re-run is **Critical**: the
  report has stopped being evidence.
- A report is never the completion record. `[x]` comes from the imported
  immutable result, the in-scope commit range, and digest-bound PASS evidence.
