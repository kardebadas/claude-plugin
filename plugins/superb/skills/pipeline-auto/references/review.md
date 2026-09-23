# Review and completion: stages 11–12

Load for the master gate, contradiction routing, a fixer dispute, the
completeness critic, final verification, or the terminal report.

**Not enforced by code:** contradiction routing, the proposals writer, the
terminal action `complete-with-proposals`, the terminal report, and writers for
the master gate's reports, verdict, fix rounds and stage 12. `findings.md` has a
validated grammar but no writer. These rules are yours to follow exactly. The
completeness freeze rests on the phase-set seal (`planning.md`): no phase can
be created after stage 06.

**REQUIRED SUB-SKILLS:** `superpowers:requesting-code-review` (stage 11),
`superpowers:verification-before-completion` (stage 12).

## Stage 11 — The master gate

**Exactly two independent reviewers** over the whole edge: tracker
`base_commit` → the last phase's verified integrated HEAD, which must still equal
the target-branch tip. Neither may be a persisted task implementation owner.

Open the gate with `open_master_gate(run_dir, reviewers={"A": ..., "B": ...})`
once stage 11 is active and every phase is `[x]`. It records the edge itself
(`base_commit` → the last source task's integration merge; you do not pass
either end) and writes the two reviewers into the master row's `Assignments`,
A first. The tracker enforces the rest, for this call and for any raw write:
exactly two distinct reviewers, neither a task `Owner`, a `Fixer`, nor the
owner of any published worker result (superseded attempts included), and no
reviewer may later become a task owner or fixer. An unreadable result under
`agent-output/` refuses the gate rather than being skipped. Reopening with the
same reviewers is inert; swapping them raises. Checking that the head is still
the target-branch tip is yours. Record the stage-12 run as `final` evidence and
the gate's own re-run as `branch-review`.

| Reviewer | Covers |
| --- | --- |
| A | Requirements, behaviour, error paths, assumptions, recorded decisions. **Names and scores every `provisional` task**; each tainting decision's ID and adopted answer are copied verbatim into A's global constraints. |
| B | Integration, architecture, persistence, recovery, concurrency, security, regressions, test quality. |

Collect both reports before consolidating or dispatching any fix. Then run the
completeness critic.

| Severity | Meaning |
| --- | --- |
| Critical | Security, data loss, destructive behaviour, fundamental failure to meet an approved requirement |
| Important | Correctness defect, regression, missing approved behaviour or test, unsafe recovery or integration |
| Minor | Violates no approved requirement and creates no likely defect |

Ease of fixing never sets severity; a missing approved requirement is never
Minor. The bar is **zero open findings at every severity**, same as per-task.
Confirm each claim against code, tests, spec and `decisions.md` before acting;
never downgrade a verified finding and never reject one because its fix is
inconvenient. Findings go to `findings.md` (`critical | important | minor`, never
deleted; closed with a disposition).

## Contradiction routing — you route, never decide

| Situation | Route |
| --- | --- |
| Code does not comply with a decision | Ordinary finding, fix loop |
| Plan-mandated finding tracing to a **human** decision | Halt to the escalation queue |
| Plan-mandated finding tracing to a **quorum** decision | Re-open that qid at a raised bar |
| Plan-mandated finding `writing-plans` invented | Ordinary quorum |
| `DECISION-CHALLENGE` against a human decision | Halt, always |
| `DECISION-CHALLENGE` against a quorum decision | One re-open at a raised bar |
| Second challenge to the same D-ID | Automatic halt |
| Fixer disputes a finding | One adjudicator (below) |

A re-open must beat the challenged decision's rung strictly (`quorum.md`). It
carries the challenging evidence, never the original rung or who chose it.

### Fixer disputes go to one adjudicator, not a quorum

A dispute is about a **fact** ("can line 41 be null"), settled by reading code or
running an experiment. A quorum is for choices. Admissible only with a
refutation citing `file:line`, or a command and its output; a bare disagreement
is inadmissible and the finding stands.

One read-only adjudicator gets the finding, the rebuttal and the review package:

| Verdict | Result |
| --- | --- |
| CONFIRMED | Finding stands; fixer fixes |
| REFUTED | Closed on the adjudicator's citation |
| PLAUSIBLE | Only this becomes a quorum question, framed neutrally |

An adjudication goes in `findings.md` (`Adjudication` column), never in
`decisions.md`.

### The one exception to zero open findings

A finding prevails automatically only if it is Critical or Important **and** its
verdict part is spec compliance or verification evidence. A Minor or
quality-part finding that would reverse a recorded decision goes to unbiased
reconciliation; if the decision survives, the finding closes
`REFUTED — governed by <D-ID>`. Do not widen this.

## Completeness critic items

The critic classifies each item. Its classification is not yours to change.

| Class | Route |
| --- | --- |
| `SPEC-NOT-MET` | A finding. Fix loop, zero-open-findings bar. |
| `MISSING-FROM-SPEC` | Frozen. A proposal, nothing else. |

For each `MISSING-FROM-SPEC` item:

1. Append a section to the run's `completeness-proposals.md`
   (shape: `templates/completeness-proposals.md`) headed with the **next unused
   number**: `## CP-1` if the file has none, else one more than the highest.
   Write the concrete ID, never `<n>`.
2. List that ID in the terminal report.
3. Once every other item is finished — an open fix round completes first —
   `next_action: complete-with-proposals`.

Never: a task, phase, fix-round finding, quorum, backlog or handover note; never
a disposition (`deferred`, `out-of-scope`, `declined`, `closed` are all
reclassifications). The phase set has been immutable since stage 06, so the run
cannot build it anyway. Quorum is biased toward "yes, also cover X"; the user
decides.

## Stage 12 — Final verification

Record digest-bound `final` PASS evidence for the accepted master HEAD. The
module does not run git; you supply the transcript.

Completion requires all of:

- master gate accepted;
- final verification recorded;
- all work committed and integrated on the designated feature branch;
- `git status --short` prints nothing (`scratch/` self-ignores);
- a fresh session derives `complete` from files and Git, not from a message.

**Never push, publish, open a pull request, or merge into `main`/`master`.**

## The terminal report

Leads with quorum-adopted decisions, **weakest rung first**. Every one is
labelled `Provenance: quorum` here, in `decisions.md`, and in the tracker. Also:

- every `provisional` task and its tainting decision;
- counts of `rejected-contradicts-human` and `rejected-contradicts-quorum`;
- every `CP-<number>` proposal, by its concrete ID;
- the adoption floor applied (`current_floor`) and any inflation rise;
- drift budget used and extensions granted (`quorum_budget`);
- every escalation, answered or outstanding;
- completions whose range proof is `attested`.
