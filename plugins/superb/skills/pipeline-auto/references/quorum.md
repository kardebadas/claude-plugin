# Quorum: questions, brains, adoption, budget

Load when a worker raises a question, a quorum is open or being finalised, the
drift budget is read or extended, or an escalation is queued. `SKILL.md` states
the rules; this file adds the mechanics and the functions that back them.

A quorum decides an **open** question. It never overrules a **recorded** one.

**Not enforced by code:** queueing a *non-quorum* escalation and batching the
queue at a stage boundary (no function writes `asked`/`answered`); provisional
propagation to dependent tasks. These are yours to follow exactly.

## Rungs, strongest first

`specified` > `code-evidenced` > `convention-cited` > `engineering-judgement` > `speculation`

**Stronger means earlier in this list.** `RUNG_ORDER` is stored in this order, so
a smaller index is a stronger rung. Never reason from "higher position" or from
the numeric values.

| Rung | Value | Must cite (every citation must resolve) | Clears the starting floor |
| --- | --- | --- | --- |
| `specified` | 0.95 | ≥1 `spec`, `intent-brief` or `decision` line | yes |
| `code-evidenced` | 0.85 | ≥1 `repo` `file:line` containing the claim | yes |
| `convention-cited` | 0.70 | ≥2 `repo` exemplars | **no** |
| `engineering-judgement` | 0.55 | nothing | no |
| `speculation` | 0.30 | nothing | no |

A brain never types a number; it names a rung. The values are schema constants,
never run configuration, and never appear in a payload.

**The floor moves.** It starts at `code-evidenced` and rises one rung for the
rest of the run once five or more adoptions average above 0.90. It never falls.
Read it from `current_floor(run_dir)["floor_rung"]`; never assume it.

## Before opening a quorum, in this order

1. **Already answered?** The approved spec or an adopted decision answers it:
   cite the line on the question record and resume the worker. No quorum, no
   decision entry, no budget. This check exists **only before dispatch**.
2. **Budget.** `quorum_budget(run_dir, phase=...)`. Proceed only if
   `may_raise` is true. Otherwise escalate with the `adopted` list attached.
3. **Admissible**, all four:

| # | Criterion | Who checks |
| --- | --- | --- |
| 1 | Blocks named work (task, gate, or planning artifact) | `check_admissible`: `blocks-nothing` |
| 2 | Decidable from the repository, spec and `decisions.md` — not from what only the user knows (budget, deadline, users, purpose) | **you**; failing it means escalate |
| 3 | Carries an axis (stage-03 question id or `new`) and a blast radius from `task \| phase \| run \| contract` | axis: `check_admissible` (`missing-axis`), and `open_quorum` refuses any other axis; blast radius: **you** |
| 4 | Passes the options test (blank the title, keep the options, the decision is still clear; adjectives are not options) and is one decision | options: `check_admissible` (`fewer-than-two-options`, …); one-decision: **you** |

`check_admissible` returns a list of problem codes; `[]` admits. It also requires
three distinct owners.

**A reconciliation question takes the disputed decision's recorded axis:** the
axis its question was asked on, as its `## Quorum` row records it — a stage-03
question id or `new` — or a human decision's stage-03 id. Never the decision's
qid, even where the decision record's `Axis` field carries it: `open_quorum`
refuses that axis, because `finalize_quorum` could never record the row.

4. **Complete the record, then open.** The worker's question record has no
   reading roots, owners or blast radius: owners are the brain ids you assign
   before dispatch, so the worker cannot know them. Write a **completed copy**
   (for example beside it under the run's `scratch/`) that adds
   `- **Reading roots:** spec=…, intent-brief=…, repo=…, tests=…, phase-plan=…`
   (all five, repository-root-relative; `parse_question` refuses a record
   missing one), `- **Owners:**` with three distinct brain ids, and
   `- **Blast radius:**` from `task | phase | run | contract` (the code does not
   read this line; it records the value you checked for criterion 3). **Never
   edit the worker's file** — its digest is what the worker's report cites.
   This is safe because the qid depends only on question and axis, which you
   copy unchanged.
5. `open_quorum(run_dir, question_record=<the completed copy>)` publishes that
   text as `quorum/<qid>/question.md` and persists `open.json` (owners,
   payload digest, context digest) **before** dispatch. The worker result you
   publish cites that published record, `quorum/<qid>/question.md#sha256=…`,
   because import binds the task's `Question` cell to it. It returns `in_flight`,
   or `escalated` when the budget tripped — then nothing is dispatched. With
   `replay` true it returns the settled outcome of an earlier raise of the same
   qid; act on that, dispatch nothing.
6. Dispatch **exactly three** `pipeline-auto-brain` agents, one per index. Never
   fewer to fit capacity (run them sequentially), never a fourth.

`qid = derive_qid(question, axis)`. The decisions digest is not part of it, so
the same question keeps its identity; a re-open gets
`derive_reopen_qid(question, axis, original_decision_id)`.

## The payload

`build_payload(qid, index, run_dir=...)` is a whitelist constructor: it emits
`qid`, `question`, `axis`, `options`, `reading_roots`, `challenge`,
`reading_assignment`, `decisions_effective`, `rungs`, `response_schema`,
`you_are_one_of_several`, and nothing else. Never add to it by hand.
`challenge` is empty except on a re-open, where it carries the challenging
evidence; `prompts/brain.md` renders it as `[CHALLENGE]`, so a re-open's brains
see why the question was asked again.

| Index | Assignment | Reads |
| --- | --- | --- |
| 0 | `spec-and-intent` | spec, intent brief |
| 1 | `code-and-tests` | repository code and tests |
| 2 | `decisions-and-plan` | `decisions-effective.md`, phase plan |

Same verbatim question to all three; different sources. Three samples of one
model on one payload are one prior sampled three times.

Never put in a payload: another brain's answer; your leaning; the floor or any
rung value; the raiser's identity, distress, or preferred answer; deadline,
budget, time or cost; conversation history; prior rejected alternatives (a
re-open carries the challenging evidence, never the original rung or who chose
it). The question's named options are part of the question and do belong.

`decisions-effective.md` (`project_decisions`) carries each decision's question,
answer and provenance — never its value, never its rejected alternatives.

## Responses

`record_brain_response(run_dir, qid=..., owner=..., payload=...)` stores every
response, valid or not, as an immutable file. `validate_brain_response` lists
schema problems (`rung-not-in-enum`, `empty-alternatives`, `unknown-field:…`).

**Missing and invalid are different rules.** Do not merge them.

| Situation | Rule |
| --- | --- |
| **Missing** — the brain died or context was lost, nothing on record | **Recovery.** Re-send only that index's own persisted payload (`payload-<owner>.json`), checked against `open.json`'s `payload_digest`. Never rebuild it from current state. Recovery uses **no** retry: the brain has no answer on record yet. |
| **Schema-invalid** — first recorded answer fails validation | **One retry**, same full payload for that index — never "fix that field", never its answer pinned. `quorum_needs_redispatch` names who is owed it. The quorum waits on it. |
| Second invalid answer from the same brain | Non-response. Quorum incomplete: escalate. |
| A brain that answered legally | Never re-dispatched. `record_brain_response` refuses a second answer. |
| A response raising its own question | Non-response (`blocker` is the only exit). Do not open a quorum on the premise, answer it, or re-dispatch with it supplied. Escalate the original question, naming the premise. |

Never map, default, or demote an out-of-enum rung. Never discard an answer to get
a tidier set. Never ask a brain to reconsider.

## Pricing each response

`effective_rung(response, repo_root)` runs on every response **before any
comparison**. A response falls to `engineering-judgement` (never rises) when:

- any citation does not resolve, or resolves to a line that does not contain the
  quoted claim;
- it has fewer qualifying citations than its rung requires;
- `what_would_change_my_mind` is empty;
- an alternative is at the same rung as the answer (it cannot separate them);
- `consistent_with` holds no `spec` or `decision` anchor (only repository code).

Demotion prices the claim; it does not reject it. It is recorded, not re-derived.

## Clustering

`group_responses(responses, options_supplied=...)`: with named options, equality
on `answer_key`; without, answers agree only if their `consequences` are mutually
non-contradictory. **When in doubt they are different answers.** A response joins
a cluster only if it agrees with every member.

Answers that describe different things entirely are `question-not-decidable`:
escalate. Never synthesise a fourth answer.

**A cluster's rung is its strongest member's effective rung** (`cluster_rung`) —
never the mean, never headcount.

## Adoption

`finalize_quorum(run_dir, qid=...)` computes and records the outcome once, under
the tracker lock. Never call it from inside a held lock. Adopt only if all hold:

- three valid responses (a precondition, never a strength);
- fewer than two responses carry a blocker;
- winner at or above `current_floor`;
- **more than one cluster:** winner strictly stronger than the runner-up;
- a re-open: winner strictly stronger than the challenged decision's rung;
- no `blast` entry in `IRREVERSIBLE_AXES`;
- `check_contradiction` finds no adopted decision it contradicts;
- `decision_depth` ≤ `DEPTH_CAP` (2; human is 0);
- `quorum_budget` still allows it.

| Case | Outcome |
| --- | --- |
| One cluster (unanimity) | No runner-up. The floor alone decides. |
| Equal rungs, at the floor or at the top | Escalate (`equal-or-inverted-rung`). No tie-break of any kind: not headcount, subset consequences, citations, recency, length, "least foreclosing". |
| Three clusters, one strictly stronger than the rest | Adopt. Different answers alone are no reason to escalate. |
| Winner adopted at `specified` | An ordinary adoption: `Provenance: quorum`, one phase and one run adoption charged. Never retroactively re-resolved by citation. |

**Blockers:** two or more responses carrying a blocker escalate automatically
(`finalize_quorum` returns `status: escalated` with `reason: blocked`) — two
brains unable to proceed means the question is the problem. **One** blocker does not by itself stop an adoption:
one brain unable to proceed is a brain, not the question. The spec states this
threshold (adoption requires "fewer than two carrying a blocker"), and the code
enforces it. A `finalize_quorum` adoption with one blocker present is legitimate
— do not override it.

An adoption records the answer, winning rung, runner-up rung, depth, and
`Provenance: quorum` as `Q-<qid>` with `Decision action: quorum.adopt`. **That
adoption is the grant**: resume each blocked task named in its `Scope` with
`resume_task(run_dir, task_id=..., prior_attempt=..., new_owner=...,
new_attempt=..., decision_ref="Q-<qid>")`. No `task.resume` record is written
for an adopted quorum. `resume_task` refuses an adoption answering a different
qid, and refuses one this task has already resumed on. A resumed attempt that
re-raises the same question is caught at "Already answered?" above, before any
result is published; if it reaches `[?]` anyway, the old adoption cannot
release it — escalate. A `halt:` block is different: only a human `task.resume`
naming the blocker and the attempt releases it.

**A re-asked question keeps its task's block.** A re-raise after a budget grant
or a challenge re-open gets a new qid, but the blocked task's `Question` cell
still names the original one and nothing rewrites it. Pass the re-ask's
adoption `Q-<new qid>` to `resume_task` anyway. It is accepted because the
re-ask's own question record, re-derived, has the blocked qid as its lineage
root. Once a re-open adopts, the original adoption is `Superseded` and resumes
nothing.

Every outcome other than an adoption or a rejection (below) is an escalation.
`finalize_quorum` returns `status: escalated` with one of these reason tokens in
`final.json` — the complete list, as the code emits them:
`incomplete-quorum`, `blocked`, `below-floor`, `equal-or-inverted-rung`,
`raised-bar-not-cleared`, `irreversible-axis`, `depth-exceeded`,
`phase-budget-exhausted`, `run-budget-exhausted`, `stale-context`,
`uncomparable-answer`, `unresolvable-anchor`, `unrecordable-decision`,
`unmintable-axis`, and — from `open_quorum`, on a second challenge to one
decision — `second-challenge`. Answers that describe different things return
the separate status `question-not-decidable` (reason
`answers-describe-different-things`), which is also escalated. There is no
third outcome and no controller override.

## Recorded decisions

- Contradicts a `Provenance: human` decision → `rejected-contradicts-human`,
  naming it. That decision stays `Adopted`. No budget spent. It is escalated:
  `finalize_quorum` queues the escalation row itself. No `Q-<qid>` is written,
  so every task blocked on it stays blocked until a human answers. No rung and
  no unanimity outranks a human.
- Agrees with every decision on its axis → adopted, and recorded on the axis
  its question was asked on (a `new` question's record carries its own qid).
  It supersedes nothing: a human decision on that axis stays `Adopted` beside
  it, and every later answer on the axis is judged against both. Several
  `Adopted` decisions may share an axis while they agree.
- Contradicts a `Provenance: quorum` decision → `rejected-contradicts-quorum`,
  naming it, even when it agrees with a human decision on the same axis. No
  escalation row is queued for it. A challenge becomes **one** re-open at a
  raised bar per D-ID per run; a second challenge naming that D-ID escalates
  as `second-challenge`, however it is worded.
- Only a re-open supersedes, and only the quorum decision it names. Ask it on
  the axis that decision's question was asked on (its `## Quorum` row's
  `Axis`: a stage-03 id or `new`); `finalize_quorum` records the successor on
  the decision's own recorded axis, so a `new`-axis decision is re-openable
  too. `open_quorum` refuses a re-open naming a human decision, and the
  decision writer refuses to retire one.
- Rejections are recorded, never discarded; their count goes in the terminal
  report.
- Two adopted contradicting answers on one axis in `decisions.md` fail validation:
  read-only stop.

**Provisional taint:** a task whose dependency closure holds a decision
adopted below `specified` is `provisional`. Marking it — the tracker
`Provisional` column, and the decision ids in its `Decisions` column — is yours.
Those two cells carry the taint everywhere it acts:

- `finalize_quorum` reads them for the rung cap below, so a quorum the task
  raises adopts no stronger than its weakest premise;
- the task reviewer receives the provisional block
  (`prompts/task-reviewer.md`): each tainting decision's ID and adopted answer,
  copied verbatim into its global constraints;
- reviewer A at stage 11 receives the same block, and names and scores every
  provisional task (`review.md`).

**Rungs inherit downward — enforced by `finalize_quorum`.** A quorum raised by
a tainted task (a task in the question's `blocks`) adopts at no stronger than
its weakest premise. The premises are `Provisional: yes`, which counts as
`code-evidenced`, and every `Q-<qid>` in the task's `Decisions` cell, at the
`Grounding rung` `decisions.md` records for it. A cited quorum decision whose
rung cannot be read (absent from the trail, or no rung on the ladder) stops the
finalisation with `QuorumError`; nothing is published, and the fix is the trail
or the `Decisions` cell. A `specified` answer resting on a `code-evidenced`
premise is not a `specified` answer, so the capped rung is what every adoption
check judges: the floor, the raised bar and the spread. The cap is applied to
every cluster before the spread, so a cap that brings the winner level with the
runner-up escalates (`equal-or-inverted-rung`). The capped rungs are what
`final.json` (`winner_rung` and `runner_up_rung`, with `own_rung` and
`rung_cap` beside them), the `## Quorum` row and `decisions.md` record. Leaving
`Provisional` at `no` does not lift a cap a cited decision imposes.

**`blocks` is validated**, because the cap finds the raisers through it:

- `finalize_quorum` refuses (`QuorumSchemaInvalid`) a question whose `blocks`
  names anything but a `## Tasks` row, a `## Gates` row, or a planning artifact
  `## Run` records (`spec`, `master_plan`, a `phase_plans` entry).
- `import_worker_result` refuses to park a task on a quorum question whose
  `blocks` does not name that task. So when a worker raises a question, put its
  own task in `blocks`.

## The drift budget

`quorum_budget(run_dir, phase=...)` returns `phase_adoptions`, `phase_ceiling`,
`phase_remaining`, `run_adoptions`, `run_ceiling`, `run_remaining`, `adopted`,
`may_raise`, `reason`. **Never compute remaining authority yourself.**

- Ceilings: `BUDGET_PER_PHASE` 3, `BUDGET_PER_RUN` 10. Only adoptions count;
  escalations and rejections never do.
- Checked **before dispatch**. Exhausted → the triggering question goes to no
  quorum of any size; escalate it with the adopted list attached.
- **The freeze on raising is run-wide.** Once exhausted, no worker anywhere
  opens a quorum; later questions attach to the same escalation.
- **The hold on work is by blast radius.** Work within the triggering
  question's blast radius follows the freeze of an open quorum there: dispatch
  nothing new on it; work already in flight finishes, publishes and is imported
  to `[x]`, and only its integration is held. Independent work continues.
- **Terminal** (the second extension already spent): no extension remains to
  grant, and the run stops resumably — in-flight work finishes, publishes and
  is imported, integration is held, and nothing new is dispatched.
- A grant is `Decision action: quorum.extend-budget`, `Provenance: human` only,
  with `Authorized run`, `Source revision`, a finite `Authorized through`, and
  `Granted against` (the verbatim adopted list the human saw). It raises **only
  the phase it names**. At most `MAX_EXTENSIONS` (2) per run; then terminal.
- You never grant yourself an extension. A quorum can never grant one.
- `dispatch.extend-budget` raises the agent-dispatch ceiling, a different
  authority. Neither grant substitutes for the other.

## Escalating

Finalise as `escalated`, queue for the next stage boundary (even mid-phase),
`next_action: await-escalation-batch`. `finalize_quorum` writes a `queued` row to
`## Escalations` for every `escalated`, `question-not-decidable` and
`rejected-contradicts-human` outcome; it writes none for an adoption or a
`rejected-contradicts-quorum`. Any other escalation — including a question
refused before `open_quorum` and a halt to the escalation queue — you record
yourself, through `locked_tracker_update`, as one `## Escalations` row:

| Column | Value |
| --- | --- |
| `ID` | `E-` and one more than the highest number the section holds |
| `QID` | the qid when `## Quorum` holds its row; otherwise `-` (a halt against a human decision, a `second-challenge`, a budget refusal, a fix loop's round-cap halt) |
| `Blast` | the axis tokens it touches, comma-separated, or `-` |
| `State` | `queued` |
| `Batch` | `-` |
| `Resolution` | `-` |

Batching sets `asked` and the batch id; with more than four pending, ask four
and set the rest `halted`. The human's answer sets `answered` and `Resolution`
to that answer's `H-` id.

Batches: up to four per `AskUserQuestion`, ranked by blast radius. Escalating
costs no budget and is never the discouraged path. `unresolved`, `deferred` or
"carry to handover" is not escalating.

While escalated, nothing is dispatched on that axis — no trace, fact-finding,
fresh quorum, or "safe" subset — until a human answers.

**Resuming on a human answer.** Record the answer as `H-<n>` with
`Provenance: human`, `Decision action: task.resume` and every blocked task in
`Scope`. Mark the `## Escalations` row `answered` with `Resolution: H-<n>`. Then
call `resume_task(..., decision_ref="H-<n>")`. It resumes a `quorum:<qid>` block
only if an answered row's `QID` is that qid (or a re-ask of it) and its
`Resolution` is this `H-<n>`. The binding is the tracker row, because an
`H-<n>` names no qid. One `H-<n>` resumes each task once. An answer that grants
only budget (`quorum.extend-budget`) resumes nothing: re-raise the question and
resume on its adoption. A budget refusal is never mirrored into `## Quorum`, so
its escalation row cannot name the qid. A human answer to a budget-refused
question therefore goes through a re-raise too.

## Resume

`classify_quorum(run_dir, qid=..., live_owners=[...])`:

| State | Do |
| --- | --- |
| `finalised` | Nothing. A finalised record is never recomputed. |
| `stale-context` | Do not re-open or re-dispatch. `finalize_quorum`: it returns `escalated`, reason `stale-context`, without reading an answer. That escalation is the flag to stage 11, and a human answer resumes the task (see "Resuming on a human answer"). |
| `ready-to-finalise` | `finalize_quorum`. No dispatch. The outcome may be an escalation. |
| `redispatch` | `owed`: the single invalid-answer retry. `unanswered`: recovery re-send (no retry used). Only the listed owners, in the listed order. |
| `awaiting-responses` | Wait for the live owners. |

Never re-run a quorum to check it. One adopted answer per qid per run; a re-raise
returns the recorded outcome and dispatches nothing.
