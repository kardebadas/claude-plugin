<!-- pipeline-auto-verification-evidence/v1 -->
# Pipeline Auto — Verification Evidence

This file is the SHAPE of a verification-evidence record, not an input form.
`render_verification_evidence` is the only writer, and
`parse_verification_evidence` refuses anything that is not byte-for-byte what
that renderer would have produced — including this file, placeholders and all.
Fill nothing in here; hand the controller the values.

| Field | Value |
| --- | --- |
| purpose | <task-test_task-integration_phase_branch-review_or_final> |
| run_id | <run_id> |
| subject | <task_or_phase>/<stable-id> |
| attempt | <attempt-NNN_or_N/A> |
| code_state | <full_tested_commit> |
| outcome | PASS |
| commands | ["<exact-command>", "<next-command>"] |
| environment | <applicable_environment_identity> |
| inputs | <JSON_array_of_path#sha256=digest_references_or_dash> |

## `outcome` has exactly one legal value

A record that is not a PASS is not evidence, so it is never written. There is no
`FAIL`, no `SKIP` and no lower-case `pass`: a suite that did not pass leaves no
record at all, and the absence is the signal. Nothing in this grammar can say
"accepted", "approved" or "waived" either — this document is the exhibit, and
acceptance is a `## Tasks` state the controller writes after it has checked it.

## What each field commits you to

`purpose` is one of the REGISTERED purposes. Each phase adds the purpose it
needs — P04 ships `task-test`, `task-integration` and `phase`, and P06 adds
`branch-review` and `final` for the master gate and stage 12 — because a
purpose nobody declared is a record nobody validates.

`subject` is `<kind>/<stable-id>` and the kind is `task` or `phase`. It is what
a later phase joins this record to a task row or a phase row on, so a subject
with no kind, or with a kind nothing registers, files the record where nothing
will look for it.

`attempt` is the canonical `attempt-NNN` the controller rendered, or `N/A` for a
record no attempt owns — a phase suite belongs to the phase. `attempt-0001` is
refused as hard as `later`: this record's identity is the sha256 of its bytes,
so an attempt has exactly one spelling.

`code_state` is the FULL tested commit, forty lowercase hex characters. A
symbolic name resolves somewhere else tomorrow, so a record bound to one proves
a suite passed at no particular state. For `task-integration` it is the `--no-ff`
merge commit, not the task branch tip.

`commands` is the exact ordered command tuple, as a JSON array — ordered because
a suite is a sequence, exact because a paraphrase is not the thing that ran, and
JSON because a shell command legitimately carries the comma a comma-separated
cell would split on.

`environment` is the applicable environment identity. A PASS that does not say
what it passed on is a PASS nobody can reproduce, so the empty-cell marker `-`
is refused here.

`inputs` is `-`, or a JSON array of `<repository-relative-path>#sha256=<digest>`
references naming the exact artifacts the suite consumed. An unbound path names
a file whose contents may have changed since, which is the one failure a
digest-bound record exists to prevent.
