# Quorum: questions, brains, adoption, budget

Load when a worker raises a question, a quorum is open or being finalised, the
drift budget is read or extended, or an escalation is queued. `SKILL.md` states
the rules; this file adds the mechanics and the functions that back them.

A quorum decides an **open** question. It never overrules a **recorded** one.

**Not yet enforced by code:** queueing a *non-quorum* escalation and batching the
queue at a stage boundary (no function writes `asked`/`answered`); provisional
propagation to dependent tasks. These are the controller's job until P05/P06.

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
| 3 | Carries an axis (stage-03 question id or `new`) and a blast radius from `task \| phase \| run \| contract` | axis: `check_admissible` (`missing-axis`); blast radius: **you** |
| 4 | Passes the options test (blank the title, keep the options, the decision is still clear; adjectives are not options) and is one decision | options: `check_admissible` (`fewer-than-two-options`, …); one-decision: **you** |

`check_admissible` returns a list of problem codes; `[]` admits. It also requires
three distinct owners.

4. `open_quorum(run_dir, question_record=...)` persists `open.json` (owners,
   payload digest, context digest) **before** dispatch. It returns `in_flight`,
   or `escalated` when the budget tripped — then nothing is dispatched. With
   `replay` true it returns the settled outcome of an earlier raise of the same
   qid; act on that, dispatch nothing.
5. Dispatch **exactly three** `pipeline-auto-brain` agents, one per index. Never
   fewer to fit capacity (run them sequentially), never a fourth.

`qid = derive_qid(question, axis)`. The decisions digest is not part of it, so
the same question keeps its identity; a re-open gets
`derive_reopen_qid(question, axis, original_decision_id)`.

## The payload

`build_payload(qid, index, run_dir=...)` is a whitelist constructor: it emits
`qid`, `question`, `axis`, `options`, `reading_assignment`,
`decisions_effective`, `rungs`, `response_schema`, `you_are_one_of_several`, and
nothing else. Never add to it by hand.

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
(`finalize_quorum` returns `blocked`) — two brains unable to proceed means the
question is the problem. **One** blocker does not by itself stop an adoption:
one brain unable to proceed is a brain, not the question. The spec states this
threshold (adoption requires "fewer than two carrying a blocker"), and the code
enforces it. A `finalize_quorum` adoption with one blocker present is legitimate
— do not override it.

An adoption records the answer, winning rung, runner-up rung, depth, and
`Provenance: quorum` as `Q-<qid>`; the blocked task resumes via `task.resume`.

Every other outcome is an escalation, with a reason token in `final.json`:
`incomplete-quorum`, `blocked`, `below-floor`, `equal-or-inverted-rung`,
`raised-bar-not-cleared`, `irreversible-axis`, `depth-exceeded`,
`phase-budget-exhausted`, `run-budget-exhausted`, `stale-context`,
`uncomparable-answer`, `unresolvable-anchor`, `unrecordable-decision`. There is
no third outcome and no controller override.

## Recorded decisions

- Contradicts a `Provenance: human` decision → `rejected-contradicts-human`,
  naming it. That decision stays `Adopted`. No budget spent. Escalate. Every task
  on that axis stays blocked. No rung and no unanimity outranks a human.
- Contradicts a `Provenance: quorum` decision → `rejected-contradicts-quorum`.
  A challenge becomes **one** re-open at a raised bar per D-ID per run; a second
  challenge halts.
- Rejections are recorded, never discarded; their count goes in the terminal
  report.
- Two adopted contradicting answers on one axis in `decisions.md` fail validation:
  read-only stop.

**Provisional taint (prose only):** a task whose dependency closure holds a
decision adopted below `specified` is `provisional` (tracker `Provisional`
column). A quorum raised by a tainted task is capped at the tainting decision's
rung. Reviewer A at stage 11 names every provisional task.

## The drift budget

`quorum_budget(run_dir, phase=...)` returns `phase_adoptions`, `phase_ceiling`,
`phase_remaining`, `run_adoptions`, `run_ceiling`, `run_remaining`, `adopted`,
`may_raise`, `reason`. **Never compute remaining authority yourself.**

- Ceilings: `BUDGET_PER_PHASE` 3, `BUDGET_PER_RUN` 10. Only adoptions count;
  escalations and rejections never do.
- Checked **before dispatch**. Exhausted → no quorum of any size, escalate with
  the adopted list; dispatch nothing new and integrate nothing. In-flight work
  finishes, publishes and is imported; only integration is held.
- Once exhausted, no worker anywhere opens a quorum; later questions attach to
  the same escalation.
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
`## Escalations` for quorum outcomes; any other escalation you record yourself.
Batches: up to four per `AskUserQuestion`, ranked by blast radius. Escalating
costs no budget and is never the discouraged path. `unresolved`, `deferred` or
"carry to handover" is not escalating.

While escalated, nothing is dispatched on that axis — no trace, fact-finding,
fresh quorum, or "safe" subset — until a human answers.

## Resume

`classify_quorum(run_dir, qid=..., live_owners=[...])`:

| State | Do |
| --- | --- |
| `finalised` | Nothing. A finalised record is never recomputed. |
| `stale-context` | Do not re-open or finalise. Flag to stage 11. |
| `ready-to-finalise` | `finalize_quorum`. No dispatch. The outcome may be an escalation. |
| `redispatch` | `owed`: the single invalid-answer retry. `unanswered`: recovery re-send (no retry used). Only the listed owners, in the listed order. |
| `awaiting-responses` | Wait for the live owners. |

Never re-run a quorum to check it. One adopted answer per qid per run; a re-raise
returns the recorded outcome and dispatches nothing.
