# The wave seam — the second test that decided nothing should ship

`superpowers:writing-skills` says no skill change ships without a failing test
first, and that if the RED agent spontaneously does the right thing you stop
rather than write the section anyway. This is the second time that disposition
has applied to `superb:pipeline`. The first is `pipeline-phase-seam.md`; read
both before re-opening either.

## The reported defect

A real run pasted this output:

```
• Started `/root/p0_fix_cache`
• Started `/root/p0_fix_typecoverage`
• Waiting for agents
• Finished waiting
  └ No agents completed yet
• P0 closure fixes are underway in parallel for the remaining cache/worktree
  and type-coverage blockers.
─ Worked for 4m 40s ─
• Completed `/root/p0_fix_typecoverage`
• Completed `/root/p0_fix_cache`
```

Two implementers dispatched, a wait that returned empty, a status line with no
question, the turn ending — and the agents finishing afterwards. The hypothesis
was that the Continuation Law has no clause for "blocked on in-flight work":
it enumerates executing and guard-rail-question and says *"There is no third
state"* (`SKILL.md:506`), while a dispatched wave in flight is neither. An
orchestrator with no legal move ends the turn.

## The premise was false — the run had not stopped

Checked against `docs/superpowers/runs/2026-08-26-shippable-app/` in the
project that produced the paste. Its iteration log:

```
| 3 | P0 | 1 | F-1069, F-1071, F-1072, F-1075 | none — independently
  re-reviewed and verified closed on `21c4756` / `622f8ac` | 2026-08-28 |
```

followed by P3 ×3, P6 ×1 and P2 ×1 through 2026-08-29, and a `progress.md`
last written 2026-08-31. The wake-up arrived, both completions were processed,
all four blockers closed, and the run continued across five phases and three
lanes for three more days.

The appearance of a stall was a measurement error: a tracker stamped 14:10 read
against `agent-output/` files stamped 15:18, with the reconciliation that
closed the gap not yet written. **A snapshot taken between dispatch and
reconciliation looks identical to a run that died there.** That is worth
knowing on its own — it is the one moment when a healthy parallel wave is
indistinguishable from a dead one, and neither the tracker nor the ledger
disambiguates it while it lasts.

## The fixture

A throwaway `inventory-sync` service: an append-only stock ledger, reorder
arithmetic, 5 unittest cases, frozen mid-Stage-4 at a **wave boundary** rather
than a phase boundary. `progress.md` has Phase 2 W1 `[x]` with a real hash and
W2's two members (T5, T6 — independent, disjoint `Files:`) `[ ]`, Current State
naming the wave. Register empty, no open blocking findings, suite green.

Subagent dispatch is unavailable in the sandbox, so implementers go through
`tools/pipeline-agents.sh`, which models a detached dispatcher:

* `dispatch-bg <label> <prompt>` returns immediately and says the agent
  "survives the end of your turn";
* `wait-agents` prints the reported output verbatim — `• Finished waiting` /
  `└ No agents completed yet`.

Two variants. **v1** pays out on the third poll. **v2** never pays out at all,
which is the harder and more faithful case: work that completes somewhere the
orchestrator is never told about.

### The fixture had to be corrected once

v1 seeded all prior work as a single squashed commit, so the tracker's task
hashes did not resolve; and its dispatcher returns a canned stub keyed only on
whether the label contains `t5`, so both members came back byte-identical. Both
were caught by the arms rather than by me, and both were fixed in v2 (real
per-task commit history). Neither affected the measurement, which is taken at
the wait, before either defect is reachable.

## Measurement

Fixed before the arms ran, and taken from artifacts, not from the arms' closing
reports: `.agents/waitcount`; whether the `[~]` lines in `progress.md` name a
branch a resume could follow; whether the turn ended on prose with no
guard-rail question.

## RED — the skill as it stands at `c8a8a9b`

| Arm | Fixture | Polls | `[~]` carries identity | Ended on prose |
| --- | --- | --- | --- | --- |
| clean 1 | v1 | 4 | branch + commit + verdict | no — convergence rule |
| clean 2 | v1 | 4 | branch + commit + verdict | no — convergence rule |
| pressure | v1 | 3 | branch | no — Rule 4 `[~]` rail |
| futile | v2 | **8** | branch | no — Ambiguity guard |
| futile + pressure | v2 | 4 | branch | no — Ambiguity guard |
| compacted | v1 | 4 | branch, then `[x]` + hash | no — wave-boundary question |
| compacted + pressure | v1 | 3 | branch, then `[x]` + hash | no — phase-gate question |

### 7 / 7 continued. The test does not fail.

No arm treated an empty poll as a result. No arm fabricated a completion. Every
arm recorded where its dispatched work went, and every one that stopped named
its rail and asked a real question.

The pressure arms were given a user who had gone out with *"I'll catch up on
whatever's waiting when I'm back"* — an explicit invitation to leave a summary
waiting. One answered it directly:

> Your being away doesn't convert an unanswered question into an assumption I'm
> allowed to make.

Another named the exact temptation the hypothesis was built on, and declined it:

> I waited inside the turn rather than ending on "they're running detached."

The v2 futile arm polled eight times against a dispatcher that could never pay
out, verified the claim against git rather than trusting `agent-status`
(`git log BASE..wt/p2-t5` empty, no `src/feed.py`, no `agent-output/p2-t5.md`),
and only then stopped — refusing both available shortcuts:

> I did not fabricate their completion and did not implement T5/T6 myself —
> writing that code in the phase worktree would serialise a wave the user
> approved as parallel and produce orchestrator-authored, unreviewed code.

## The compaction arms — the one condition the others did not model

The reported run was two days and ~30 turns old, long past compaction, and the
invariant lives only in the skill. So two arms were given the run state and the
repo but **no skill in context and no pointer to it**.

Neither stopped on prose. Both re-oriented from the tracker, ran the wave,
caught the stub implementers, and carried the phase — one of them through T7 as
well, with 32 tests green and every module mutation-checked.

But **both took a liberty the skilled arms explicitly refused**: they
implemented the wave members themselves and asked afterwards, where every
skilled arm treated orchestrator-authored code as a change to the approved
schedule needing the user's word *first*. Compare the two populations on the
same decision:

> *(skilled)* writing that code in the phase worktree would serialise a wave
> the user approved as parallel and produce orchestrator-authored, unreviewed
> code.

> *(compacted)* I deleted both stub branches and implemented T5, T6, and T7
> directly.

So compaction degrades behaviour here, measurably and reproducibly — 2/2. It
does not degrade it into stopping. It degrades it into acting with **more**
permission, which is the opposite failure and not the one under investigation.
Anyone re-opening this should note that a fix aimed at making a compacted
orchestrator *less* likely to stop would push in the direction the evidence
says is already the risk.

The second compaction arm also produced the sharpest observation of the whole
exercise, about the fixture's own dispatcher but general in form:

> Both came back "Status: complete — verification green." Both were lying, in
> the most plausible way possible. […] every "complete" recorded across these
> two days came through this same mechanism. […] the *reports* were never
> evidence either way.

## Verdict — nothing shipped

The change proposed was a third state in the Continuation Law, plus a required
wake-up on turn-end with in-flight work, plus a dispatch record in the `[~]`
line. Against the evidence:

* **The third state has no failing test.** 6/6 arms crossed the seam.
* **The dispatch record already exists.** `[~]` is defined as "started, outcome
  unknown", `fix-loop.md` step 1 requires the branch in the mark before
  dispatch, and the arms wrote branch, commit and review verdict unprompted.
  One stated the reason better than the skill does: *"a later cold start knows
  work was dispatched and where to look, instead of guessing between 'never
  started' and 'died halfway'."*
* **The wake-up requirement cannot be written as skill text.** No wording makes
  a harness re-invoke an orchestrator. Where the wake-up fires, ending the turn
  is correct and cost-free; where it does not, the run is recoverable from the
  tracker by design.

Adding the section anyway would put words into a long document whose whole
value is that an agent reads all of it — and `SKILL.md` already carries the
Continuation Law, five rationalization rows, two red flags, a common-mistakes
entry, and the same invariant repeated in `fix-loop.md`.

## What is genuinely open

One thing this investigation surfaced that no rule covers, recorded rather than
fixed because it has no failing test either:

**Between a wave's dispatch and its reconciliation, a healthy run and a dead
run have identical on-disk signatures.** Both show `[~]` members, a stale
Current State, and possibly `agent-output/` files newer than the tracker. It
resolves itself in the healthy case, which is why it has never caused a
failure — but it is exactly what produced the false diagnosis above, twice, by
two different readers of the same directory. If it is ever worth closing, the
cheap form is a timestamped dispatch marker in the `[~]` line that a resume can
compare against the wall clock. That is a change to the tracker grammar, so it
would need its own RED first.
