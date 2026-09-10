# Pipeline v2 — Decisions

<!--
Copy one section per question. The `## D-<number>` heading is the Stable ID.
Record the user's exact answer; never replace it with an agent's interpretation.

Every decision has exactly one Decision action from this closed vocabulary:
task.resume | review.resolve-question | filesystem.authorize |
remediation.start-round | none

Use `none` unless the explicit answer authorizes that exact controller action.
The action never replaces its applicable identity/scope fields:

- task.resume: Scope names the exact blocked task; its current Question must be
  this D-ID, and Status must be Resolved.
- review.resolve-question: Scope names the affected gate, phase, or finding.
- filesystem.authorize: Scope names the exact run ID, filesystem type, and
  fingerprint; the tracker acknowledgement is D-<number>@<fingerprint>.
- remediation.start-round: add exactly one of every field below:
  Authorized run, Source revision, Authorized gate, Required state,
  Required question, Predecessor decision, Authorized through round,
  Authorized findings, and Authority marker. These values must describe the
  current blocked gate and requested finite round exactly.

Open questions use Answer `pending user response`, Decision action `none`, and
Status `Open`. A generic "approved", "continue", or plan approval is not an
answer to an unresolved choice and must not be recorded as one.
-->

## D-001 — <decision title>

- **Question:** <exact unresolved question>
- **Answer:** pending user response
- **Decision action:** none
- **Scope:** <affected run, phase, gate, task, finding, or artifact>
- **Sources:** <explicit sources inspected>
- **Status:** Open

<!--
For Decision action `remediation.start-round`, insert these fields before
Scope, replacing every placeholder with the approved exact value:

- **Authorized run:** <run_id>
- **Source revision:** <current_tracker_revision>
- **Authorized gate:** <gate_id>
- **Required state:** blocked
- **Required question:** <current_gate_question>
- **Predecessor decision:** <D-ID>
- **Authorized through round:** <round_number>
- **Authorized findings:** <comma-separated_exact_finding_IDs>
- **Authority marker:** remediation-extension:<gate_id>:through-round-<round_number>
-->
