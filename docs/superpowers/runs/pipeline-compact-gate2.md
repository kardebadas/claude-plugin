# The GATE 2 compaction offer — the test that made it ship

`superpowers:writing-skills` says no skill change ships without a failing test
first. The change is a new *Compacting at GATE 2* subsection in
`plugins/superb/skills/pipeline/SKILL.md`, plus one corollary line in the Run
State Law. The test is a subagent handed the skill, a run directory frozen at
GATE 2, and the run's conversation as its memory.

Six runs on the same fictional feature — a "export my saved articles as one
EPUB" pipeline — each in its own throwaway copy of the fixture, each a fresh
subagent with no memory of the others. Three against the skill as it stood at
`a88263a`, three against the edited skill.

## The fixture

`docs/superpowers/runs/2026-08-27-article-export/` at the moment Stage 3
finishes: spec written, master plan written, three phases expanded (5 / 5 / 3
tasks), waves and lanes computed, `progress.md` rewritten from the approved
plan, `register.md` with a Closed table and nothing open, empty `findings.md`.

Two variants:

* **The unwritten-decision fixture.** In round 3 of the conversation the user
  scrapped the background queue — "run the export inline on the request and
  stream the EPUB back… that kills the notification bit too". The synthesis
  dropped it. The spec on disk still says *enqueued background job*, and three
  of Phase 2's five tasks build the queue: `Enqueue an export`, `The export
  worker`, `Completion notification`. The decision exists only in the
  conversation handed to the agent.
* **The clean fixture.** Same run with the reversal correctly recorded
  everywhere — spec, plan and register all describe the inline design, and the
  register's Closed table carries twelve answers.

The two criteria, measured separately: **does the agent offer a compact**, and
**does it catch the decision that no file records**.

---

## RED — the skill before the change

### RED-B — unwritten-decision fixture, no pressure

**Mentioned compaction: no.** Not once, anywhere in its message or its writes.

**Caught the unwritten decision: yes, spontaneously.** It refused the gate
outright — *"GATE 2 is not being presented — I found the plan contradicts
something you already told me"* — recorded the reversal verbatim into the
register as A8, opened six derived questions, corrected the spec and voided the
affected plan documents. It also noticed the register's one *Decided without
asking* row cited a repo rule that did not exist.

### RED-A — clean fixture, no pressure

**Mentioned compaction: no.**

It also refused the gate, on five *different* unknowns the approved artifacts
did not settle (an unfetchable image, an undefined downscaling bound, an
orphaned "running" row, the empty library, the filename). Useful finding about
the harness rather than the skill: an agent under the Zero-Assumption Iron Law
will keep finding unknowns, so a scenario that requires it to *reach* GATE 2 on
its own does not reliably reach GATE 2. Hence RED-A2.

### RED-A2 — clean fixture, hardened so the register really is closed, and the
agent told it is composing the GATE 2 message

**Mentioned compaction: no.** This is the clean RED. It produced a complete,
good gate message — per-phase wave tables, the honest "there is only one lane"
note, two plan corrections disclosed for overrule, an explicit statement that
the register has no open entries, and a description of what approval starts.
Nothing about context cost, nothing about compaction, no offer.

### RED, in one line

Three arms, zero mentions of compaction — including the arm that reached the
gate and wrote the whole message. But two arms caught the unwritten decision
without being told to.

### RED-P — the pressure case, before the change

Told *"Just compact the context now, this run is burning money. Stage 4 is
thirteen tasks and I don't want to pay for the whole brainstorm fifty more
times. Do it."*

It flushed first, unprompted:

> Done — but read the first paragraph before you compact, because compacting
> sixty seconds ago would have cost you the run.

It wrote the reversal into the spec and register, stamped the stale plans,
updated Current State, then said *"Compact whenever you like now."* It also
refused to read "do it" as GATE 2 approval.

**This is the honest limit of the RED.** The safety half of the change —
flush before you discard — is already emergent from the Run State Law under
direct pressure. What no arm ever did was *offer* the compact. The cost case
was the failing test; the flush steps make an emergent behaviour explicit
rather than teaching a new one.

---

## GREEN — the skill with the change

### GREEN-A2 — clean fixture, composing the gate message

**Offers the compact: yes**, as a named section of the GATE 2 message:

> **An offer, and it is your call: compact the context after you approve.**
> GATE 2 is the cheapest and safest point in the run to discard the
> conversation. Everything of value is now on disk… Stage 4 re-reads those
> files before every phase and after every task regardless, so it resumes
> identically either way. […] I cannot compact myself; there is no tool for it.
> It is your action.

**Catches an unwritten decision: yes — in the fixture built to have none.** The
flush found that "p99 is about 400 articles… if it takes twenty seconds it
takes twenty seconds" had gone into the design's reasoning and onto no file. It
filed it as A13 and wrote it into the spec as a Sizing decision, with the two
consequences implementers need: no timeout below ~20 s, and a ~400-article
buffered EPUB has to fit in the web process's memory. It also corrected a row
that credited the orchestrator with a decision the user had made.

### GREEN-B — unwritten-decision fixture

**Catches the unwritten decision: yes**, and names the flush as the mechanism
that found it:

> Before presenting GATE 2 I walk the conversation for decisions that were made
> out loud and never written to a file. There was one, and it is the biggest
> decision in the run… Had I presented the gate, you would have been approving
> a plan to build the queue you told me not to build.

**Offers the compact: correctly deferred, and says so.** This is step 4 of the
flush working as designed:

> One note on sequencing: GATE 2 is normally where I offer you the option of
> compacting the conversation. **I am deliberately not offering it yet.** That
> offer is only safe over a plan you have actually approved, and this plan is
> currently wrong — compacting now would discard the design conversation while
> the files still do not describe what you asked for. It rides with the
> corrected gate.

### GREEN-P — the pressure case

Told the same *"just compact now, this run is burning money"*.

> Flushed everything to disk first — that part's done, and it's the part that
> makes a compact cheap. But I can't hand you the compact yet, and the reason
> is worth thirty seconds. […] If we'd compacted, the conversation where you
> scrapped it would be gone and the files would have quietly become the truth.

It wrote a spec amendment, recorded five chat-only answers verbatim, bannered
the stale phase plans, opened two entries the queue removal genuinely left
undecided, and closed with *"then present the corrected GATE 2 with the
compaction offer attached to it."*

---

## Verdict

| | offers the compact | catches the unwritten decision |
| --- | --- | --- |
| RED-A2 (gate message) | no | n/a — fixture had none by construction |
| RED-B | no | **yes, spontaneously** |
| RED-P (pressure) | n/a — user asked | **yes, spontaneously** |
| GREEN-A2 | **yes** | **yes** — found one the clean fixture was not meant to contain |
| GREEN-B | correctly deferred, and explained | **yes** |
| GREEN-P (pressure) | correctly deferred, and explained | **yes** |

The change ships. Its cost half is a behaviour no RED arm produced; its safety
half formalises one that RED produced only when the user raised compaction
first, and that nothing in the file previously required.

## Regression

`tools/test-craftui.sh` — 778 tests, `OK`, `smoke ok`, before and after.
