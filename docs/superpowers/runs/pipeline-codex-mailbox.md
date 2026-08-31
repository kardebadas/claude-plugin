# Stopping after every task on Codex — the defect that was real

Companion to `pipeline-phase-seam.md` and `pipeline-wave-seam.md`. Those two
investigated reported stops and shipped nothing, because the skill already
covered the seam and 7/7 arms crossed it. This one shipped, because the failure
is not a discipline failure at all — it is a harness property the skill never
knew about.

## The report

> The codex was reporting the status of the task and was finishing. Basically,
> it was stopping after every task, I had to say continue, continue, continue
> after every task. […] It's not every time. It depends on the sessions.

Three facts in that, and only one hypothesis fits all three: **per task**
(not per phase), **Codex** (never reproduced on Claude Code), and
**intermittent**.

## The mechanism

From Codex's own platform notes, `superpowers:using-superpowers`'s
`references/codex-tools.md`:

> Completion mail cannot wake an idle controller (it is delivered without
> triggering a turn); covering that idle window is `wait_agent`'s only job.
> […] A completed child's final answer is pushed into your mailbox and arrives
> **with your next turn**.

So on Codex the loop is: dispatch a task's implementer → no local work left →
turn ends → the child finishes into a mailbox nobody is draining → **only a
user message starts the next turn.** The user types `continue`, the mail lands,
the task closes, the next task dispatches, and it parks again. Once per task,
exactly as reported.

On Claude Code the identical turn-end is harmless: a finishing child re-invokes
the orchestrator. That is why ten arms across three investigations never
reproduced it.

The intermittency follows too: reaching for `wait_agent` was discretionary. It
depended on whether `codex-tools.md` was read that session, whether multi-agent
was enabled and at which version, and whether compaction had since dropped it.
Nothing made it mandatory, so it varied by session.

## The gap

`pipeline/SKILL.md` contained **zero** platform adaptation — no Codex, no
`wait_agent`, no turn mechanics, nothing about who wakes an orchestrator.
Meanwhile the two rules that should have caught it are both phrased as
discipline:

* `subagent-driven-development`: *"Do not pause to check in with your human
  partner between tasks."* An orchestrator that dispatched a child and has
  nothing to do is not checking in — it is out of work. The rule does not
  reach it.
* The Continuation Law: *"either you are executing, or your message ends in a
  guard-rail question […] There is no third state."* An orchestrator waiting on
  a dispatched child is neither, so it reached for the only exit it could see.

Adding a sixth "do not stop" would not have helped. The agent was not
rationalising its way out of a rule; it had no legal move and no idea the exit
was expensive.

## Why no behavioural RED

There isn't one, and the absence is structural rather than an omission.

The failure mode is *"ending the turn is survivable, so it is tempting."*
Inside a Claude subagent, ending the turn is **terminal** — the arm returns and
is gone. The property under test cannot be expressed in the harness available,
so a passing simulation proves nothing about Codex.

It was tried anyway, to be sure. A Codex-shaped fixture (`spawn_agent`,
`wait_agent`, `list_agents`; completions delivered only on a wait) was run in
two conditions — arms with only the pipeline skill, and one additionally given
`codex-tools.md`:

| Arm | Platform notes | `wait_agent` calls |
| --- | --- | --- |
| A1 | no | 1 |
| A2 | no | 3 |
| B1 | yes | 5 |

All three waited, including both without the notes. The simulation cannot
distinguish the hypotheses, and no number of further arms would.

What stands in its place is a reproduction on the real harness (the user's
sessions, repeatedly), a documented mechanism that predicts all three observed
properties, and a confirmed absence in the skill. That is an observed failure
with an explained cause, which is what the Iron Law protects against skipping.

## What shipped

Three edits, all **conditionals keyed to an observable predicate** rather than
prohibitions — per `writing-skills`' form-matching rule, a prohibition is for an
agent that knows the rule and skips it, which is not this.

1. **`SKILL.md` — "Who wakes you after a dispatch"**, a new section before
   Stage 5, naming the two harness families and stating the rule mechanically:
   dispatched agents outstanding and no local work left → the next action is a
   **bounded wait**, not the end of the turn. Carries the Codex `timeout_ms`
   range (300000–600000) and why stacking short polls is strictly worse than
   one long stretch.
2. **`SKILL.md` — one line inside the Continuation Law**: *"Waiting on a
   dispatched agent is executing, not stopping."* This closes the hole that
   made the turn-end feel legal.
3. **Point-of-use pointers** in `parallel.md` step 4 (wave dispatch) and
   `fix-loop.md` step 1 (per-phase loop), so the rule is present where dispatch
   happens rather than only in a section read once at the start.

The unknown-harness default is **treat it as a mailbox**: waiting on a
re-invoking harness is harmless, while ending the turn on a mailbox harness
costs the user a `continue` per task.

## The regression check

The danger of "wait, do not end the turn" is an agent that waits forever where
it used to stop. Tested on the fixture whose dispatcher **never** pays out —
the same fixture where the pre-change arm stopped after 8 polls.

| Skill | Polls | Outcome |
| --- | --- | --- |
| before | 8 | Ambiguity guard, named, with a question |
| after | 6 | Ambiguity guard, named, with a question |

No regression, and the arm used the new text's own reasoning to decide when
waiting had stopped being useful:

> The last wait returned in 8 ms. It is not a blocking event subscription, so
> stacking more waits cannot produce a completion — which is why I stopped
> waiting rather than looping.

It also declined the two shortcuts, as every skilled arm in these
investigations has:

> I did not fabricate the returns, did not write T5/T6 myself, and did not
> serialise the wave onto the phase branch.

## Open

Unverified on the real harness. The reproduction is the user's Codex sessions,
and confirmation has to come from there — if a Codex run still stops per task
with this text in place, the mechanism above is wrong and this should be
re-opened rather than patched over.
