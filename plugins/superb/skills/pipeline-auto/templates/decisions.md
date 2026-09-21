# Pipeline Auto — Decisions

Append-only. A decision is never edited and never deleted. The one legal
in-place mutation is `Status: Adopted` to `Status: Superseded`; the superseding
record is appended below with its own id and its own `Supersedes` line. A file
that loses a decision loses the only evidence that anything was decided rather
than assumed.

A decision id says who decided. A human answer's id is the letter `H`, a hyphen
and a decimal number (`H-1`, `H-2`), in the order the one human gate produced
them. A quorum answer's id is the letter `Q`, a hyphen and the twelve-character
qid of the question it settled (`Q-0123456789ab`). The prefix is the entire
difference between a decision a machine made and one the user made, and it is
what contradiction routing reads to tell them apart: a finding tracing to a
human decision halts to the escalation queue, while one tracing to a quorum
decision re-opens that qid at a raised bar.

`Provenance` is `human` or `quorum`, and it is recorded even though the id
already implies it. Provenance has to be visible in the decision record, in the
tracker index and in the terminal report, because a provenance field read only
by a validator has informed nobody.

`Action` is one of exactly five, and nothing else is honoured:

    task.resume | quorum.adopt | quorum.extend-budget |
    dispatch.extend-budget | none

Use `none` unless the answer authorises that exact controller action. A generic
"approved", "continue", or a plan approval is not an answer to an unresolved
choice and must never be recorded as one — this holds for a quorum answer of
"proceed" exactly as it holds for a human's.

`task.resume` names the exact blocked task in `Scope`, names the attempt it
releases in `Attempt`, and its `Status` must be `Adopted`. The action never
replaces the identity fields; it is granted on top of them.

A grant is spent on ONE ATTEMPT of one task. `Attempt` holds the attempt token
the task is blocked at (`attempt-001`); a grant that named only the task would
authorise every resume of that task for ever, which is not a grant but a
standing permission.

A grant must also name THE BLOCK, and how it does that depends on which arm the
task's `Question` cell takes:

- `quorum:<qid>@<path>#sha256=<digest>` — the DERIVED arm. A quorum decision's
  id is `Q-` followed by the qid of the question it settles, so the grant binds
  to the block by construction: the id must be `Q-` followed by the very qid in
  that cell. A re-open derives a different qid, so a stale answer cannot resume
  a re-asked block.
- `halt:<reason>` — the ASSERTED arm. Nothing opened a quorum, so no qid exists
  and there is no question record to derive one from. The grant repeats the
  reason verbatim in a `Blocker` field and must carry `Provenance: human`.
  **This arm is an assertion by whoever writes the record, not a derivation.**
  Nothing here can tell a correctly copied blocker string from a carelessly
  copied one; the field makes a mismatch visible to a reader, and that is the
  whole of what it buys.

One arm or the other, never neither. A `Question` cell in neither form binds a
grant to nothing at all.

`decisions.md` is unsigned and hand-editable, so every binding above is
TAMPER-EVIDENT BY CROSS-REFERENCE and none of it is tamper-proof: a writer with
this file open can author a record that satisfies all of it. What the bindings
remove is the grant that clears a block by ACCIDENT — a stale answer, another
question's answer, or a second resume spending a grant that was already spent.

`quorum.extend-budget` and `dispatch.extend-budget` are separate actions
because they are separate authorities: the drift budget caps decision authority
and the dispatch budget caps run cost, and one action shared between them would
let a grant against either refill the other. Both require `Provenance: human`;
neither is grantable by quorum.

`Rung` names the grounding of a quorum answer, from the five schema constants,
lowest first:

    speculation | engineering-judgement | convention-cited |
    code-evidenced | specified

It is `-` on a human decision: a human decides, and grounding is a machine's
problem. The numeric value of a rung and the adoption floor are deliberately
absent from this file. They are schema constants the controller owns, and a
copy of them here would be a second source of truth sitting in a file a hand
can edit — which is how an autonomous controller would come to lower its own
adoption bar.

`Depth` counts inference from the last thing a human actually said. A human
decision is depth 0; an answer citing only depth-0 decisions is depth 1. Depth
3 is not quorum-eligible whatever its rung.

## Axis Index

One row per axis, and an axis holds at most one `Adopted` decision. A file
holding two adopted contradicting answers on one axis fails validation and is a
read-only stop — the same severity as a foreign schema. A superseded decision
keeps its row; the superseding one is appended beneath it.

| Axis | Decision | Provenance | Status |
| --- | --- | --- | --- |
| axis-id-of-the-human-decision | H-1 | human | Adopted |
| axis-id-of-the-quorum-decision | Q-0123456789ab | quorum | Adopted |

## H-1 — decision title

- Question: the exact question the user was asked, verbatim
- Answer: the user's exact words; never an agent's interpretation of them
- Axis: the stable axis id this question was tagged to
- Provenance: human
- Action: none
- Scope: the run, phase, gate, task, finding or artifact this binds
- Rung: -
- Depth: 0
- Sources: the intent-brief or spec lines this question was drawn from
- Status: Adopted

An unanswered question is recorded now, not later: `Answer` reads
`pending user response`, `Action` reads `none`, and `Status` reads `Open`.

## Q-0123456789ab — decision title

- Question: the exact question the brains were asked, verbatim
- Answer: the adopted answer, verbatim from the winning cluster
- Axis: the stable axis id this question was tagged to
- Provenance: quorum
- Action: quorum.adopt
- Scope: the run, phase, gate, task, finding or artifact this binds
- Rung: code-evidenced
- Depth: 1
- Consequences: assertions that would be verifiably true of the repository if
  this answer were adopted — a file, a signature, a command that passes; never
  a rationale
- Sources: the file:line citations each winning response resolved to
- Status: Adopted

A quorum decision adopted below `specified` taints every task whose dependency
closure contains it. Record the rung honestly: the taint is what obliges the
stage-11 reviewer to score it and name it, and a rung written up to avoid the
label removes the one signal that the run is resting on something soft.

## H-2 — budget extension title

A budget extension is an explicit finite grant, never a reset, and it carries
its own field discipline so that a reflex "yes" cannot become one. Replace
`quorum.extend-budget` with `dispatch.extend-budget` for the dispatch ceiling;
the fields are the same and the two grants never substitute for each other.

- Question: the escalation the human was answering, verbatim
- Answer: the user's exact words
- Axis: the stable axis id this escalation was tagged to
- Provenance: human
- Action: quorum.extend-budget
- Scope: the **phase** whose ceiling this grant raises (`P04`), not the run —
  `Authorized run` already names the run, and a grant that names no phase of
  this run raises no ceiling while still spending one of the two extensions
- Rung: -
- Depth: 0
- Authorized run: the exact run id
- Source revision: the tracker revision at grant time
- Authorized through: a finite new ceiling; never "unlimited"
- Granted against: the verbatim list of adopted decisions the human was shown
- Sources: the escalation batch this answers
- Status: Adopted

`Granted against` is the anti-reflex mechanism: the human is on record as having
seen the specific decisions they waved through. Extensions are capped at two per
run; after the second the budget is terminal and the run stops resumably.
