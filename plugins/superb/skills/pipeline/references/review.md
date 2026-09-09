# Review gates and remediation

Read this reference only for a planned required high-risk phase gate, the
mandatory master gate, or remediation of either gate. Task completion and an
ordinary `final-only` phase do not open a formal review.

Use **superpowers:requesting-code-review** to dispatch the approved formal
reviewers. Use **superpowers:receiving-code-review** to validate their claims
against the code, tests, approved design/plans and recorded user decisions
before accepting, rejecting, or fixing anything.

## Open only the approved gate

| Gate | Preconditions | Reviewers |
| --- | --- | --- |
| Phase `final-only` | Mechanical phase verification passed | None. The controller may advance the phase when every other acceptance fact permits it. |
| Phase `required` | Every task is truthfully complete, source work is integrated, artifact work is validated, mechanical verification passed, and the tracker classification and reason exactly match that phase's approved metadata | Exactly one independent reviewer who did not implement the phase. Review the complete integrated phase and the specific risk named by its reason. |
| Master | Every phase is verified and every required phase gate is accepted. The base is the immutable tracker `base_commit`; the head is the last approved phase's recorded verified integrated HEAD and the current designated target-branch tip. | Exactly two independent reviewers over that same complete edge. Neither may be any persisted task implementation owner. Reviewer A covers requirements, behavior, error paths, assumptions, and user decisions. Reviewer B covers integration, architecture, persistence, recovery, concurrency, security where relevant, regressions, and test quality. |

Open the gate with the controller transition only after those preconditions are
true. Reviewer capacity consumes the same persisted global `worker_limit` as
task and fixer ownership. Run the two master reviewers concurrently only when
the global limit and detected runtime capacity permit; otherwise queue them.
Free capacity never authorizes an early, duplicate, third, ordinary-phase, or
task reviewer.

Each published report uses the helper's strict report contract and the exact
assignment recorded by the controller:

```markdown
<!-- pipeline-review-report/v2 -->
| Field | Value |
| --- | --- |
| gate | <gate-id> |
| assignment | <recorded-assignment-id> |
| base | <reviewed-base-commit> |
| head | <reviewed-head-commit> |
| findings | <stable-finding-ids-or-> |
```

The phase reviewer reports against the opened phase edge. Both master reports
must name their own recorded assignments and the identical gate/base/HEAD. The
controller rejects a caller-selected master base or HEAD and any master reviewer
whose identifier matches a persisted task implementation owner. Recheck the
target tip at acceptance: if it advanced after opening or report publication,
keep the gate unresolved and refresh the affected verification and review.
If a reviewer cannot assess the assigned scope, record the limitation and ask
the user; do not declare the scope covered or spawn another reviewer.

## Collect, validate, and consolidate

Wait for every required report before consolidation or fix dispatch. Verify
the report marker, gate, assignment, base, HEAD, and finding claims against the
actual reviewed state. Deduplicate overlapping claims under stable finding IDs
and write the authoritative `findings.md`; a rediscovered issue keeps its ID.
The controller must keep the report set consistent with those stable IDs.

Use exactly these severities, classified by demonstrated consequence:

- **Critical** — blocking security vulnerability, data loss, destructive
  behavior, or fundamental failure to meet an approved requirement.
- **Important** — blocking correctness defect, regression, missing approved
  behavior or required test, or unsafe recovery or integration.
- **Minor** — nonblocking only when the issue violates no approved requirement
  and creates no likely defect. Ease of fixing does not determine severity.

A missing approved requirement cannot be Minor. A reviewer claim is not true
merely because it was reported: confirm it from the code, tests, requirements,
and repository rules. Never downgrade a verified finding to pass a gate or
reject one because its fix is inconvenient.

Each finding is `Open` or `Resolved`. A resolved finding has one disposition:

- `Fixed`: cite applicable verification, the fix commit, and the matching
  re-review report.
- `Deferred`: Minor only; its evidence records the finding ID, impact, reason,
  and explicit authority for deferral.
- `Rejected`: cite evidence with exactly `Finding: <ID>` and one nonempty
  `Rationale:` that demonstrates why the claim is invalid or inapplicable.

Rejecting an invalid claim is not deferring a valid suggestion. Every Minor
needs one recorded disposition. If finding validity, required behavior, or a
Minor disposition needs an unanswered choice, record and ask the user. Clear
the gate question only through an applicable resolved decision carrying
`Decision action: review.resolve-question`; generic approval or reviewer
preference is not authority.

## Evidence-derived acceptance

Gate acceptance is derived by `evaluate_and_close_review_gate`; a caller's
`accepted=True`, an empty open-findings list, a bare `Resolved`, or a reviewer
silently omitting an earlier finding proves nothing. Acceptance requires all
of the following:

1. Every required report belongs to the recorded gate, assignment, and reviewed
   code-state edge.
   For the master gate, that reviewed HEAD must still equal the designated
   target-branch tip.
2. Digest-bound required verification records `PASS` for the exact applicable
   integrated HEAD and matches the phase or active remediation evidence already
   recorded in `progress.md`.
3. No confirmed Critical or Important finding remains open.
4. Every Minor has a valid disposition and evidence.
5. No unresolved acceptance question remains.
6. Every repository-changing review fix, including a deletion or test-only
   change, has strict commit/integration provenance, applicable verification,
   and a re-review from the recorded gate assignments that covers the fix and
   relevant integration consequences.

An evidence-backed rejection that changes no repository file needs no invented
fix commit or empty-diff re-review. Report acceptance as “Passed with no
blocking findings; listed Minors deferred” when valid Minors remain deferred;
reserve “No findings remain” for the literal case.

The initial `gate.base` and initial report paths are immutable. During
remediation, `gate.head` advances only after a validated contiguous edge from
the prior reviewed HEAD to the verified fix HEAD. Re-review reports use that
prior HEAD as their base. Validate the complete initial-plus-remediation
lineage; never reinterpret an initial report as if it reviewed a later HEAD.

## One bounded remediation loop

The initial review is **round zero** and consumes no remediation round. When
confirmed Critical or Important findings remain:

1. Wait for all reports, validate and consolidate them, and resolve required
   user questions.
2. Write one scoped `fix-plan.md` for exactly the current blockers; compatible
   Minor dispositions may share it without expanding scope silently.
3. Before dispatch, call `start_remediation_round` to persist the gate, round,
   targeted finding IDs, fix-plan path, active fixer assignments, and any exact
   finite-extension authority. Parallel fix batches still consume one round.
4. Use compatible batches rather than one fixer per finding. Respect
   dependencies, typed write scopes, and the global worker limit. Apply
   **superpowers:test-driven-development** to behavior changes and
   **superpowers:systematic-debugging** to unexpected failures.
5. Run focused regressions while fixing. After the consolidated fix batch is
   committed and integrated, run the required phase suite once on that state
   and record command, outcome, digest-bound evidence, code-state identity,
   relevant environment, and elapsed time.
6. Call `record_remediation_fixes` only with strict post-review fix commits,
   the integrated fix HEAD, and applicable verification. This releases fixer
   ownership and reserves the gate's recorded reviewer assignments.
7. Re-review the same gate. Check targeted findings, the fix diff, introduced
   regressions, and relevant integration consequences; then record exactly one
   `remaining-blockers` outcome and evaluate the gate.

The default maximum is three fix/re-review rounds per gate. Resume an
interrupted round under its existing number; compaction, worker replacement,
parallel fixers, or new findings never reset or split the counter. A round past
three requires a finite, explicit, persisted `remediation.start-round`
decision that exactly matches the run, gate, current tracker state/revision,
predecessor authority, next round, and current blocker set. It does not change
the default or authorize the following round.

Stop as soon as acceptance passes. Stop earlier and ask the user when a
completed round resolves none of its targeted Critical/Important findings,
fixes oscillate or reintroduce a resolved blocker, requirements conflict, or a
fixer has an unresolved required question. Commits, renamed findings, or a
claimed improvement are not progress. If some targeted blocker is confirmed
resolved, another round may address the remainder within the available limit.
After the authorized limit, preserve the same unresolved gate and all history,
block dependent advancement/final completion, report every attempt and its
evidence, and ask; never waive, downgrade, defer, or silently close a blocker.
This is one non-recursive loop for the gate: do not invoke Pipeline recursively,
open a loop per finding, or introduce task-level formal review.

## Verification evidence during review

Under D-024, reviewer independence means independent evaluation, not automatic
duplication of an applicable full suite. Reviewers inspect the diff and
requirements, validate supplied evidence, and run focused adversarial checks.
Reuse evidence only when its recorded code state and relevant working-tree
snapshot, tests, fixtures, configuration, dependencies, inputs, and
environment remain applicable. Rerun affected checks after a relevant change;
do not call stale evidence fresh. A reviewer may run broader checks when
evidence is missing, inconsistent, inapplicable, explicitly required, or a
focused probe exposes wider risk, and records why.

The mandatory final verification still follows an accepted master gate. No
formal gate authorizes push, publish, PR creation, or merge to `main`/`master`.
