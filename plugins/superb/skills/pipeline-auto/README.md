# pipeline-auto

Part of the `superb` plugin, invoked as **`superb:pipeline-auto`**.

Pipeline-auto takes a substantial feature from an initial idea to a clean,
committed local feature branch with **one guaranteed human gate**. After the
stage-03 questions, every open decision goes to a quorum of three independent
brain agents instead of stopping for the user. It is a standalone rewrite of
`superb:pipeline`, which it does not modify. Use `superb:pipeline` when every
unanswered choice should reach you; use this skill when a run should keep moving
and bring you only the decisions a machine may not make.

## Modes

| Command | Behavior |
| --- | --- |
| `/superb:pipeline-auto` | Start a full run: discovery, the stage-03 gate, planning, execution. |
| `/superb:pipeline-auto resume` | Resume one compatible `pipeline-auto/v1` run from its files and Git. Never creates or replaces a run. |
| `/superb:pipeline-auto status` | Read-only inspection. |

## What a machine may and may not decide

A quorum may **decide an open question**. It may never overrule a recorded one.

- Each of the three brains reads a different source (spec and intent, code and
  tests, decisions and plan) and names an evidence rung. It never types a
  confidence number.
- An answer is adopted only when three valid responses exist and the winning
  answer's rung is **strictly stronger** than the runner-up's and at or above
  the adoption floor. Equal rungs never adopt.
- An answer that contradicts a `Provenance: human` decision is rejected at any
  confidence and escalated.
- A drift budget caps how many decisions a run may make without asking:
  3 per phase, 10 per run. Escalating never spends it.
- The phase set is sealed after planning, so the run cannot create work for
  itself. A completeness gap the critic finds becomes a frozen proposal for you
  to decide, not a task.

Escalated questions are batched at stage boundaries. The run waits on them
instead of guessing, and resumes from its files when you answer.

## Files are the authority

A run keeps its design, plans, tracker, decisions, quorum records, worker
results and evidence on disk. Conversation memory is never authoritative, so a
compacted or restarted session reconstructs the next action from files and Git.
The tracker's state machine enforces the rules the skill cannot leave to the
controller's restraint: the phase-set seal, the review-class ratchet, the rung
cap on tainted premises, reviewer independence at the master gate, and the
terminal action.

## The end of a run

Success is a clean, committed feature branch. The skill never pushes, publishes,
opens a pull request or merges into `main`/`master`. The terminal report leads
with every decision the run made without asking, weakest first, followed by any
frozen completeness proposals.

## Layout

| Path | Contents |
| --- | --- |
| `SKILL.md` | The controller's rules, rationalizations and routing |
| `references/` | Stage mechanics: planning, execution, quorum, review, persistence |
| `prompts/`, `templates/` | Worker, brain and reviewer prompts; run file templates |
| `scripts/pipeline_auto_state.py` | The tracker's state machine |
| `examples/controller_walkthrough.py` | A whole run driven end to end in a throwaway repository |
| `tests/` | The suite, and the RED/GREEN pressure records under `tests/pressure/` |
