# BA-3 — Craft's completion condition, and how it knows it got there

Question: what is craft's completion condition, and how does it know it has
reached it? The user's bar is that questioning continues "until the craft idea
is concrete or more objective … convert a generic idea into something concrete
and doable by the LLM."

---

## 1. What craft uses today

Three places state a stopping condition, and all three are the same claim.

**`skills/craft/SKILL.md` §"Completion criteria" (lines 1333–1354)** — the
substantive one:

> Crafting is complete when another capable LLM can read `CRAFT.md` and
> confidently understand:
> * what I want to build; * why I want it; * who it is for; * how the important
> workflows should behave; * what the application should look and feel like;
> * what functionality belongs in scope; * what functionality does not belong in
> scope; * what product rules must be respected; * which technical choices I care
> about; * which technical choices I do not care about; * what constraints exist;
> * what decisions have been delegated; * what assumptions remain; * whether any
> important contradictions remain.
>
> The downstream LLM should still need to decide **how to implement the
> product**. It should not need to guess **what product I wanted**.

**§"Final status" (lines 1391–1415)** — the emitted token:

> Then give one status:
> `CRAFT STATUS: VISION CLEAR` / `CRAFT STATUS: MORE CLARIFICATION NEEDED` /
> `CRAFT STATUS: BLOCKED BY CONTRADICTION`
>
> A status of `VISION CLEAR` means the product vision is sufficiently well
> defined for another skill to begin architecture or implementation planning.

**§"Ending" (lines 334–345)** — the only place a hard test appears:

> `FINISHED` means **I have stopped answering.** It does not mean the vision is
> clear. Do the final fold, then judge the brief on its merits: if REQUIRED
> questions are still unanswered, name them and report
> `CRAFT STATUS: MORE CLARIFICATION NEEDED`. Only a genuinely complete brief
> gets `VISION CLEAR`.

Nothing else in the skill gates the status. There is a decision ledger
(§Decisions, `## Confirmed Decisions`, DEC-014 shape), an assumptions register
(§Assumptions, ASSUMPTION-003 shape with `**Status:** Unconfirmed`), a
contradictions section (§Contradictions, CON-002 shape), and a delegated section
(§"Delegated decisions"). **All four are write-only.** No rule anywhere says
`VISION CLEAR` requires the assumptions list to be empty, the contradictions
list to be empty, or every REQUIRED question to have a DEC entry. The nearest
thing is §Ending's "if REQUIRED questions are still unanswered" — and that is
scoped to unanswered *round questions*, not to the brief's `## Open Questions`
section.

**Is the condition measurable?** No. Every clause is a predicate about a
hypothetical reader's confidence ("another capable LLM can … confidently
understand"), evaluated by the agent that wrote the document, from inside the
conversation that produced it. "Genuinely complete" and "sufficiently well
defined" carry no threshold. Two runs on the same `CRAFT.md` may disagree, and
nothing in the skill would catch it.

### The one number in the system does not measure the brief

`ui/schema.py:211` `count_open(round_obj, answers)`:

```python
for question in (round_obj or {}).get("questions", []):
    importance = question.get("importance")
    if importance not in counts: continue
    if answer_state(answers.get(question.get("id"))) == "skipped":
        counts[importance] += 1
```

Three properties matter for convergence:

1. **It is scoped to one round.** `craftui.py:1147` feeds it
   `session.current_round()`'s questions only. It is "how many of the questions
   on screen right now has the user not filled in" — a UI progress indicator. It
   knows nothing of rounds 1..N-1, and nothing of `CRAFT.md`.
2. **Delegated counts as settled**, correctly: `count_answered` (`schema.py:227`)
   treats `answered` and `delegated` alike, and `answer_state` returns
   `"delegated"` before it looks at any content. So a round of fifteen "you
   decide" clicks reports `open: {REQUIRED: 0, …}` — a fully converged round by
   the only metric craft has, and a brief with fifteen undecided decisions in it.
3. **Absent == skipped** (`answer_state` returns `"skipped"` for a non-dict), so
   the count is honest about silence. That part is right and should be kept in
   any successor metric.

`schema.py`'s own docstring names the four states and their intent: answered,
delegated ("I don't care, record it and stop asking"), skipped ("ask me again"),
absent. The distinction craft needs at completion time — *decided by the user*
vs *decided by nobody yet* — is present in the data and simply never aggregated
across rounds.

### The README states the contract craft does not enforce

`README.md:35–39`:

> `craft` and `pipeline` are meant to run in order … Crafting reaching
> `CRAFT STATUS: VISION CLEAR` is the signal that the pipeline has enough to
> work from — it is not an instruction to start building.

and `README.md:101–110`: the user is "left with `CRAFT.md` — vision, scope,
confirmed decisions, delegated decisions, open questions, contradictions — and a
status line". So `VISION CLEAR` is load-bearing across a skill boundary: it is
the handshake token pipeline consumes. A handshake token produced by
unverifiable self-assessment is the same defect class as an untested gate.

---

## 2. "Concrete and doable by the LLM" as a checkable predicate

The predicate must be evaluable twice with the same verdict, by a script over
`CRAFT.md` plus the round files in `.craft/`. Proposed exit contract — craft is
complete when **all** hold:

**A. Structural completeness**
- A1. Every applicable heading from §"Output of the crafting process" (lines
  1235–1297) is present. *Applicable* is decided once, early, and recorded: a
  CLI with no monetisation writes `## Monetisation` → `Not applicable — <reason>`.
  Absent heading = fail; heading with an empty body = fail; body matching the
  vagueness list (`TBD`, `to be decided`, `etc.`, `as appropriate`, `we'll see`,
  `something like`) = fail.

**B. Nothing important left open**
- B1. `## Open Questions` contains zero entries under REQUIRED and zero under
  IMPORTANT. PREFERENCE/OPTIONAL entries are permitted and must be listed.
- B2. `## Contradictions` (or the CON-* entries) contains zero unresolved
  entries. One or more → the status is `BLOCKED BY CONTRADICTION`, not
  `VISION CLEAR`. This is already the third status in §"Final status"; today
  nothing computes it.
- B3. `## Remaining Assumptions` contains zero entries with
  `**Impact if incorrect:** High` and `**Status:** Unconfirmed`. A high-impact
  unconfirmed assumption is a question that was never asked; it is the exact
  thing §Assumptions says must never silently become a requirement.

**C. Traceability — every asked question is accounted for**
- C1. Union the question ids across `.craft/round-*.questions.json` (file mode:
  the `### [LEVEL]` headings). Every id of importance REQUIRED or IMPORTANT
  appears exactly once in `## Confirmed Decisions` or `## Delegated Decisions`,
  cross-referenced by id. No id appears in both, and no id appears in both a
  closed section and `## Open Questions`.
- C2. Each `## Confirmed Decisions` entry carries `**Decision:**`, `**Source:**`
  and `**Status:** Confirmed`, per the DEC-014 template. A REQUIRED decision's
  `Source` must be `User answer` — not `Recommendation accepted`, not
  `Inferred`. §Recommendations already forbids the substitution
  ("Do not silently turn your recommendation into a requirement"); this makes it
  checkable.

**D. Concreteness — the part that answers "doable by the LLM"**
- D1. Every entry under `## Core Features` has an **observable acceptance
  sentence**: what a named user type does, and what the system does back. A
  feature line with no actor and no outcome is a category, not a requirement.
- D2. Every entity named in `## Domain Behaviour` carries at least one stated
  rule beyond its field list — lifecycle, permission, ordering, or availability.
  §"Domain behaviour" already demands this depth ("Go deep enough that important
  product behaviour does not have to be invented later"); D2 makes it countable.
- D3. Every user type in `## Target Users` appears in at least one journey under
  `## User Journeys` and in at least one rule under `## Permissions and Privacy`.
  A user type nobody can do anything as is an unfinished thought.
- D4. `## Explicit Non-Goals` is non-empty. A brief that has excluded nothing has
  not been scoped; §Scope asks for "things that definitely should not exist" and
  a bounded scope is what makes the build finite.
- D5. `## Technical Preferences` states, for each axis in §"Preferred
  technologies", either a choice or the literal
  `No preference — planning skill may decide.` string the skill already
  mandates (line 868). Silence on an axis is neither.

Every clause above is a grep, a count, or a section-shape check. A script
returns the same verdict twice; a reviewer working the same list reaches it too.
That is the difference from today's "another capable LLM would confidently
understand".

---

## 3. Should the bar be "pipeline would open zero register entries"?

**Against, as stated. For, restricted to the classes craft owns.**

Pipeline's law (`skills/pipeline/SKILL.md:53–90`):

> `NEVER ASSUME. EVERY UNKNOWN BECOMES A USER QUESTION.` … From Stage 1 onward,
> every unknown and every default you were tempted to pick is a numbered entry
> in **`register.md`** … **No gate may be presented while any register entry is
> open.**

The register's scope is *everything pipeline must decide to build the thing*,
including what craft is explicitly forbidden to touch. §"Avoid premature
implementation thinking" (lines 1194–1221) bars database tables, API endpoints,
files, sequencing; §"Strict boundaries" bars plans, phases, task lists,
estimates. Meanwhile Stage 2 opens register entries for phase `deps:`, Stage 3
for per-task `Depends on:` and `Files:` lines, wave assignment, and the 12-task
split. **A craft run that closed those would have to become pipeline**, and
would never terminate — the register also absorbs unknowns that only exist once
a plan exists, so the target is not merely distant, it is not reachable from
craft's position at all.

The usable form: **zero register entries of craft's classes.** Tag every
register entry with a class on creation — `product`, `ux`, `domain`, `scope`,
`tech-preference`, `constraint` (craft's), versus `architecture`, `sequencing`,
`test-strategy`, `infra` (pipeline's). Craft's bar becomes: *pipeline Stage 1
opens zero entries in the first six classes.*

What that implies, and each of these is a real cost to accept:
- Pipeline must carry the class tag in `register.md` / `templates/register.md`.
  Small change, and it makes the metric exist at all.
- A craft-class entry opened at Stage 1 is a **craft defect**, and its count is
  the one true outcome measure of craft's depth — the only end-to-end evidence
  that a `VISION CLEAR` was earned. Log it; it is how the predicate in §2 gets
  tuned against reality rather than against taste.
- The metric is retrospective. It cannot gate the status at craft time, which is
  precisely why §2's static predicate and §4's independent reviewer are needed as
  the shipping gate, with this as the feedback loop behind them.
- It must not become a demand that craft answer architecture questions to
  suppress the count. The class tag is what protects the boundary: an
  `architecture` entry at Stage 1 is pipeline working as designed and must never
  be counted against craft.

---

## 4. Should a different agent judge completion?

**Yes — and the skill's own criterion already implies it.** Line 1299:

> The final document should be understandable by another LLM without needing
> access to the original conversation.

That property is *only* testable by an LLM that does not have access to the
conversation. The asking agent fails the test's own precondition: it holds every
answer in context, so it reads the brief's gaps through what it already knows,
and every ellipsis looks filled. It also has the questionnaire author's
optimism — it has spent the session shrinking the round ("The questionnaire
should become smaller and more precise with every pass", line 1150) and shrinkage
feels like convergence whether or not the brief converged.

Ruling: `CRAFT STATUS: VISION CLEAR` requires **two independent passes**, and
either failing means `MORE CLARIFICATION NEEDED`:

1. **The static check** of §2, run mechanically. Cheap, deterministic, catches
   omission.
2. **A fresh-context reviewer agent**, given `CRAFT.md` **and nothing else** —
   no transcript, no round files — and asked to produce the questions it would
   still have to ask the user before it could plan. Its output maps onto the
   fourteen clauses of §"Completion criteria". Any question it raises in a
   craft-owned class (§3) becomes a round-N+1 question, not a note. Zero such
   questions is the pass.

The reviewer is the structural analogue of pipeline's Stage 1b, which dispatches
"**≥2 agents in parallel** to independently pressure-test / expand the agreed
design" *before* GATE 1, on exactly this reasoning — line 5 of that stage:
"Every gap the pressure-test surfaces becomes either a design change the user
explicitly confirms or a **new register question** — never a self-filled
default." Craft has the same gate and no such agent. One reviewer is the minimum;
the transcript-blindness matters more than the count.

Note the failure mode this closes: today, §Ending has the agent judge the brief
immediately after `FINISHED`, i.e. at the moment its context is most saturated
with answers and most likely to mistake recall for documentation.

---

## 5. Delegated decisions

A `"delegated": true` answer is, in `schema.py`'s words, *"I don't care, record
it and stop asking"*. SKILL.md (lines 322–327) says: "Record it under *Delegated
Decisions* and never ask it again", and §"Delegated decisions" gives the reason
it must appear in the brief at all: "This prevents downstream agents from
mistaking an unanswered question for an omission."

**Ruling: delegation does not block completion, but an under-specified delegated
entry does.** It is closed for asking and open for deciding; the brief's job is
to hand the decision on with enough that the receiver can make it without coming
back. Otherwise every "you decide" click converts one-for-one into a pipeline
register entry — the exact leak §3 measures — and the user answers the same
question later in a worse context.

Required contents of every `## Delegated Decisions` entry, extending the
template at lines 1319–1327 (`Status` / `Guidance` / `Constraints`):
- **`Status: Delegated`** and **who to** — planning, architecture, or
  implementation. Different receivers, different timing.
- **`Options considered`** — the option list craft was going to offer. This is
  free (it is already in the round file) and it is the difference between a
  delegation and an erasure: the receiver inherits craft's framing rather than
  re-deriving it.
- **`Recommendation`** — craft's own pick with its reason. §Recommendations
  permits recommending and forbids it becoming a requirement; in a delegated
  entry the recommendation is the default the receiver may take silently, which
  is the one place that is safe.
- **`Constraints`** — what any choice must respect (already in the template, and
  the load-bearing field: "easy to run locally and inexpensive").
- **`If this goes wrong`** — the failure the user would notice. This is what
  lets the receiver tell a reversible choice from a one-way door, and it is what
  a delegation that should never have been offered looks like when written down.

Two guards on which questions may be delegated at all:
- SKILL.md's `delegable` field (line 250) already carries the principle —
  "Set it `false` on the questions only I can answer: my budget, my users, what
  the product is for. … offering that on a question you cannot actually decide is
  worse than not offering it" — but its **default is `true`**, so a REQUIRED
  question is delegable unless the agent remembers to say otherwise. Invert it
  for REQUIRED: `delegable` defaults to `false` at importance REQUIRED, and
  setting it `true` there is a deliberate act.
- A REQUIRED question that is nonetheless delegated must be recorded as a
  **confirmed scope reduction**, not a delegation — the user has said the product
  does not need that decision made by them, which is itself a product decision
  and belongs in `## Confirmed Decisions` with `Source: User delegated REQUIRED
  <id>`. Otherwise §2's clause C1 cannot distinguish "the user handed this off"
  from "the product identity was never established".

And the counting rule that follows: any successor to `count_open` that reports
convergence across the brief must report **three** numbers, not two — answered,
delegated, open — because `count_answered` folding delegated into settled is
right for the UI's progress bar and wrong for a completion gate.

---

## Summary of the twelve-line ruling

1. Today: §"Completion criteria" + `CRAFT STATUS: VISION CLEAR`, self-assessed.
2. Not measurable; the only metric, `count_open`, is one round of UI progress.
3. Replace with the static predicate in §2 — structure, nothing open, full
   traceability, concreteness.
4. Not "pipeline opens zero register entries" — that crosses craft's own
   boundary and is unreachable; use zero entries *in craft's classes*, tagged.
5. A second, transcript-blind agent must pass the brief before `VISION CLEAR`.
6. Delegated is closed for asking, open for deciding — it passes only with
   options, recommendation, constraints and failure mode written down.
