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
The tracker records the complete required reviewer set while capacity controls
which queued assignments are active. With `worker_limit=1`, run one assignment,
publish its immutable report, release that slot, and run the second assignment;
gate evaluation still requires both independent reports. Apply the same queue
lifecycle to re-review.
Free capacity never authorizes an early, duplicate, third, ordinary-phase, or
task reviewer.

Each published report preserves any technical narrative first and ends with
exactly one terminal helper report block using the exact assignment recorded by
the controller. Missing, duplicated, malformed, nonterminal, or trailing blocks
are rejected:

```markdown
<!-- pipeline-review-report/v2 -->
| Field | Value |
| --- | --- |
| gate | <gate-id> |
| assignment | <recorded-assignment-id> |
| base | <reviewed-base-commit> |
| head | <reviewed-head-commit> |
| findings | <stable-finding-ids-or-> |
| outcomes | {"<finding-id>":"Open-or-Resolved"} |
```

The `outcomes` value is one JSON object with unique finding keys; repeated keys
are invalid even when the repeated values agree. An initial report maps every
finding it introduces to `Open`; a clean initial report uses `findings=-` and
`{}`. Every re-review assignment maps every finding that existed before that
re-review exactly once to `Open` or `Resolved`, even when the report's main
discussion focuses on only a subset. It may additionally introduce a new
stable finding, which is bound to that re-review's digest as its immutable
origin and starts `Open` in the same gate and remediation history.
Any `Open` from a required reviewer blocks. Conflicting reviewer conclusions
block consolidation and require explicit resolution; silence is never evidence
that an earlier finding was resolved. Existing five-field reports remain
readable only when already content-digest sealed as historical lineage. Never
publish a new initial or re-review report in that historical format.

The phase reviewer reports against the phase's approved boundary through its
verified HEAD. For the first phase the boundary is the run base; for a later
phase it is the prior phase's applicable accepted/verified HEAD. A
source-changing phase cannot use a caller-selected empty or partial range; an
all-artifact phase may truthfully retain the same HEAD while its artifact
evidence remains required. Both master reports
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
On the first evaluated result, persist each initial report as a digest-bound
identity and each finding introduction as an identity bound to gate, stable ID,
severity, and its introducing report digest(s). Later remediation validates
those sealed bytes and identities before dispatch or acceptance; changing a
report, deleting an introduction, or rewriting its ID/severity fails closed.
`gate.head` may advance through reviewed remediation edges, but the sealed
initial reports retain their original reviewed HEAD.

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

- `Fixed`: a repository-changing fix cites applicable verification, its
  integrated fix commit, and the matching re-review report. An explicitly
  artifact-only remedy uses `Fix Commit: -` only with a digest-bound
  `pipeline-artifact-remediation/v2` record naming the exact finding, gate,
  round, immutable fix plan, nonempty digest-bound artifact set, and recorded
  remediation verification; its cited re-review must be the applicable report
  supplied for that round. The active immutable fix plan remains the authority
  for classifying the remedy as artifact-only. Its single
  `pipeline-remediation-scope/v2` table must cover the exact ordered targeted
  finding set: `source` rows use `none`, while `artifact` rows use a nonempty
  unique JSON array of exact repository-relative output paths. Artifact-remedy
  evidence must bind exactly those paths.
- `Deferred`: Minor only. Its digest-bound disposition artifact contains
  exactly one nonempty `Finding:`, `Impact:`, `Reason:`, and
  `Authority: D-<number>` field. That decision must be resolved, explicitly
  authorize deferring the same finding, name it in scope, and carry
  `Decision action: review.resolve-question`; unrelated, conflicting, generic,
  or stale authority cannot close the gate.
- `Rejected`: cite evidence with exactly `Finding: <ID>` and one nonempty
  `Rationale:` that demonstrates why the claim is invalid or inapplicable.

Rejecting an invalid claim is not deferring a valid suggestion. Every Minor
needs one recorded disposition. If finding validity, required behavior, or a
Minor disposition needs an unanswered choice, record and ask the user. Clear
the gate question only through an applicable resolved decision carrying
`Decision action: review.resolve-question`; generic approval or reviewer
preference is not authority.

An `Open` Minor is a valid pending disposition, not an invalid finding row. If
the user explicitly chooses `Fixed`, record a resolved
`review.resolve-question` decision scoped exactly to that finding. The same
gate's next remediation plan may then target that authorized Minor alone or
alongside the exact current blockers. Without that authority an open Minor is
not silently fixed, promoted, deferred, or rejected.

## Evidence-derived acceptance

Gate acceptance is derived by `evaluate_and_close_review_gate`; a caller's
`accepted=True`, an empty open-findings list, a bare `Resolved`, or a reviewer
silently omitting an earlier finding proves nothing. Acceptance requires all
of the following:

1. Every required report belongs to the recorded gate, assignment, and reviewed
   code-state edge, and its explicit outcome mapping covers the required finding
   set. Re-review outcomes must agree with the consolidated authoritative status;
   conflicting or missing conclusions cannot close the gate.
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
   relevant integration consequences. An approved artifact-only fix fabricates
   no commit; it instead satisfies the immutable artifact-remediation evidence
   contract above and still requires the applicable re-review.

An evidence-backed rejection that changes no repository file needs no invented
fix commit or empty-diff re-review. Report acceptance as “Passed with no
blocking findings; listed Minors deferred” when valid Minors remain deferred;
reserve “No findings remain” for the literal case.

The initial `gate.base` and initial report paths are immutable. During
remediation, `gate.head` advances only after a validated contiguous edge from
the prior reviewed HEAD to the verified fix HEAD. Re-review reports use that
prior HEAD as their base. Validate the complete initial-plus-remediation
lineage; never reinterpret an initial report as if it reviewed a later HEAD.
A completed all-artifact edge truthfully records `commits=N/A` and may retain
the prior HEAD only when its immutable scope is entirely artifact-kind. Its
Fixed evidence remains bound to that historical round's scope, verification,
and re-review during later rounds. Source and mixed edges retain strict commit
and newer-HEAD ancestry.

## One bounded remediation loop

The initial review is **round zero** and consumes no remediation round. When
confirmed Critical or Important findings remain:

1. Wait for all reports, validate and consolidate them, and resolve required
   user questions.
2. Write one scoped `fix-plan.md` for exactly the current blockers; compatible
   Minor dispositions may share it without expanding scope silently.
3. Before dispatch, call `start_remediation_round`. It validates any present
   machine-readable remedy authority against the exact target set before it
   persists the gate, round, digest-bound fix-plan path, active fixer
   assignments, and any finite-extension authority. Invalid or ambiguous scope
   reserves nothing; the same authority is revalidated during fix recording,
   evaluation, and recovery. A source-only plan without the table retains the
   strict source-remediation default. Parallel fix batches still consume one
   round.
4. Use compatible batches rather than one fixer per finding. Respect
   dependencies, typed write scopes, and the global worker limit. Apply
   **superpowers:test-driven-development** to behavior changes and
   **superpowers:systematic-debugging** to unexpected failures.
5. Run focused regressions while fixing. After source changes are committed and
   integrated and artifact outputs are complete, run the required phase suite
   once on that state and record command, outcome, digest-bound evidence,
   code-state identity, relevant environment, and elapsed time.
6. Call `record_remediation_fixes` with one digest-bound typed `remediation`
   PASS record matching the run, gate, round, and fix HEAD. Mixed/source rounds
   require strict post-review fix commits and a newer integrated HEAD. A
   machine-authorized all-artifact round records commits as `N/A` and retains
   the unchanged reviewed target tip. Both paths revalidate the immutable fix
   plan, release fixer ownership, and reserve the recorded reviewers using a
   fresh controller-bound capacity observation inside the tracker lock.
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

Reviewer independence means independent evaluation, not automatic
duplication of an applicable full suite. Reviewers inspect the diff and
requirements, validate supplied evidence, and run focused adversarial checks.
Reuse evidence only when its recorded code state and relevant working-tree
snapshot, tests, fixtures, configuration, dependencies, inputs, and
environment remain applicable. Rerun affected checks after a relevant change;
do not call stale evidence fresh. A reviewer may run broader checks when
evidence is missing, inconsistent, inapplicable, explicitly required, or a
focused probe exposes wider risk, and records why.

The mandatory final verification still follows an accepted master gate. Record
its digest-bound `final` PASS evidence for the accepted master HEAD through the
controller transition. Only then may the derived next action become
`complete`; a fresh session must revalidate that evidence and the target tip.
No
formal gate authorizes push, publish, PR creation, or merge to `main`/`master`.
