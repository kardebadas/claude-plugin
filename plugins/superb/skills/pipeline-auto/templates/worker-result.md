<!-- pipeline-auto-worker-result/v1 -->
# Pipeline Auto — Worker Result

This file is the SHAPE of a worker result, not an input form. The controller
renders the real document from `render_worker_result`, which is the only writer,
and `parse_worker_result` refuses anything that is not byte-for-byte what that
renderer would have produced — including this file, placeholders and all. Fill
nothing in here; hand the controller the values.

- **Owner:** <controller_assigned_owner>

## Result
| Field | Value |
| --- | --- |
| run_id | <run_id> |
| task_id | <task_id> |
| attempt | <attempt-NNN> |
| owner | <controller_assigned_owner> |
| kind | <source_or_artifact> |
| status | <DONE_or_DONE_WITH_CONCERNS_or_NEEDS_CONTEXT_or_PLAN_CONFLICT_or_BLOCKED> |
| source_ref | <full_source_head_sha_or_dash> |
| commits | <ordered_full_shas_or_dash> |
| artifacts | <exact_approved_outputs_or_dash> |
| tests | <exact_ordered_task_suite_or_dash> |
| evidence | <path#sha256=digest_list_or_dash> |
| concerns | <concerns_or_dash> |
| question_record | <path#sha256=digest_or_dash> |
| blocking_reason | <blocking_reason_or_dash> |

## Checkpoints
| ID | Status | Evidence |
| --- | --- | --- |
| <checkpoint_id> | <complete_or_in_progress_or_blocked> | <path#sha256=digest> |

## What each status commits you to

The vocabulary is unchanged from `superb:pipeline`. The routing is reversed for
two of the five.

`NEEDS_CONTEXT` and `PLAN_CONFLICT` raise a QUORUM QUESTION rather than halting
the run, so `question_record` is REQUIRED for both and must be a resolvable,
digest-bound `<repository-relative-path>#sha256=<digest>`. A result that says "I
need a decision" and names no question record has raised nothing: the controller
is left holding a status it cannot act on. It is rejected exactly as a result
with a missing owner is rejected. Neither status may also carry a
`blocking_reason` — a result claiming both routes is one nobody can dispatch.

`BLOCKED` still HALTS, because three brains cannot conjure an API key or a
permission. It REQUIRES a `blocking_reason` and must NOT name a question record.

`DONE` and `DONE_WITH_CONCERNS` carry neither routing field, and they are claims
rather than acceptances. A completion must therefore carry the material an
importer can check it against: at least one digest-bound `evidence` reference
always; for a `source` task its `source_ref`, its `commits` and the exact
ordered `tests` it ran; for an `artifact` task its `artifacts`.
`DONE_WITH_CONCERNS` must record the concern it is named for.

## Why the owner is stated twice

The `- **Owner:**` line above the table is a CROSS-PHASE CONTRACT, not a
decoration. The master gate's reviewer-independence check parses every
published result in the run's results tree, owner line included, and refuses a
master reviewer who ever owned an attempt at any task — including a released or
superseded attempt whose only surviving record is its immutable result file.
The `owner` table cell is what the codec reads the owner out of; the line is a
projection of that cell, written by the same renderer and asserted equal on the
way back in, so a document can never state two owners. Neither may be removed:
without the cell the codec has no owner, and without the line the codec refuses
the document, so the check refuses the gate rather than skip the result.
Per-task reviewer independence is not checked by
code; the controller keeps it (`prompts/task-reviewer.md`).

Nothing here accepts anything. There is no field in this grammar that can say
"accepted", "approved" or "verified" — acceptance is a `## Tasks` state the
controller writes after it has checked this document, and this document can only
ever be the exhibit.
