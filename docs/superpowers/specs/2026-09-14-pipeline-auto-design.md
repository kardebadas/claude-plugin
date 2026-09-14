# Superb Pipeline Auto Design

**Date:** 2026-09-14
**Status:** Proposed for executable-plan approval
**Base commit:** `c8bddd610119f52b54bf077d284c7f5d8362ae77`
**Feature branch:** `feat/pipeline-auto`
**Skill directory:** `plugins/superb/skills/pipeline-auto/`
**Design record:** published artifact, approved 2026-09-14

## Purpose

Build `superb:pipeline-auto`: a standalone skill that takes a substantial feature
from an initial idea through implementation with exactly one guaranteed human
gate, resolving every later decision by a three-agent confidence quorum rather
than by stopping for the user.

It is a full rewrite in a new directory. `plugins/superb/skills/pipeline/` is not
modified. `superb:pipeline` works today; duplication is the accepted price for
ensuring a regression in the autonomous variant cannot reach it.

## The rule this skill reverses

`plugins/superb/skills/pipeline/references/planning.md:177-181` forbids adding to
the pipeline:

> retired lane/wave authority, reviewer arithmetic, per-task formal review,
> one-agent-per-task execution, recursive fix mode, **a Brain Agent that decides
> user requirements**, or another scheduler.

`superb:pipeline-auto` is that Brain Agent, built deliberately, with guardrails
the original author did not think were sufficient. The zero-assumption law
(`pipeline/SKILL.md:40-71`) held that another agent may investigate facts and
explain options but cannot decide an unresolved requirement. This skill inverts
that. Every mitigation in this document exists to answer the objection that
clause was making.

Maintainers changing a threshold, a budget, or an escalation route in this skill
are loosening that answer. The reversal is stated here so the trade is visible
rather than inherited.

## Governing invariants

1. **One guaranteed human gate.** Stage 03 asks at most four questions in a
   single `AskUserQuestion` call. Those answers are the only requirements the run
   may treat as unimpeachable.
2. **A quorum may decide an open question. It may never overrule a recorded
   one.** Any candidate answer contradicting a `Provenance: human` decision is
   rejected and escalated, at any confidence.
3. **Escalation is always available and never penalised.** Escalations do not
   consume the drift budget. Degrading a quorum to fit capacity or budget is
   forbidden; the run escalates or halts instead.
4. **Files are the authority.** Conversation memory is never authoritative. The
   run reconstructs its next action from the tracker, decisions, immutable worker
   results, evidence digests, and Git.
5. **Every quorum-adopted decision is labelled as such, forever**, and the
   terminal report leads with them, sorted by confidence ascending.
6. **The phase set is immutable after stage 06.** The run cannot create work for
   itself. Scope expansion is structurally impossible, not merely forbidden.
7. **No push, publish, PR, or merge into `main`/`master`.** Success leaves a
   clean committed feature branch.

## Composition

`superb:pipeline-auto` **inlines** the subagent-driven-development review
protocol rather than invoking it. `subagent-driven-development/SKILL.md:12`
states that the superpowers plugin-cache copy is a mirror and "a superpowers
plugin update will silently overwrite that mirror". A skill whose review
protocol can be replaced by an unrelated plugin update is not reproducible, and
stage 09 modifies the protocol anyway. This skill therefore carries its own
references, its own four prompt templates, and its own copies of the
`task-brief`, `review-package` and `sdd-workspace` scripts, citing SDD as
provenance.

Invoked as installed contracts:

| Responsibility | Required skill |
| --- | --- |
| Design investigation and gate classification | `superpowers:brainstorming` |
| Spec, master plan, phase plans | `superpowers:writing-plans` |
| Independent concurrent batches | `superpowers:dispatching-parallel-agents` |
| Isolated workspaces | `superpowers:using-git-worktrees` |
| Implementation and behaviour-changing fixes | `superpowers:test-driven-development` |
| Unexpected failures | `superpowers:systematic-debugging` |
| Master gate dispatch | `superpowers:requesting-code-review` |
| Fresh completion evidence | `superpowers:verification-before-completion` |
| Skill pressure testing | `superpowers:writing-skills` |

## Stages

| # | Stage | Mechanism | Human |
| --- | --- | --- | --- |
| 01 | Intent read | 3 × `intent-reader`, reconciled into one brief with conflicts flagged, never resolved | no |
| 02 | Question synthesis | 3 × brain agents propose open decisions; controller ranks by blast radius, dedupes, cuts to 4 | no |
| 03 | **The one gate** | one `AskUserQuestion` call, ≤4 questions, answers persisted with `Provenance: human` | **yes** |
| 04 | Design and gates | `superpowers:brainstorming`; fixes each phase's `review_class` before any plan exists | no |
| 05 | Spec | brain agent feeds it; `superpowers:writing-plans` writes it | no |
| 06 | Master plan | `superpowers:writing-plans`; **phase set becomes immutable on close** | no |
| 07 | Phase fan-out | N × `writing-plans` workers, capped by `worker_limit`; unresolved interfaces reported, never invented | no |
| 08 | RED | `superpowers:test-driven-development`; failing test committed before the change | no |
| 09 | GREEN | inlined SDD protocol in a worktree; intensity set by the dial | no |
| 10 | Debug | `superpowers:systematic-debugging`; traced cause before any fix | no |
| 11 | Review | two independent reviewers scoring against `decisions.md`, then a completeness critic | no |
| 12 | Verify | `superpowers:verification-before-completion` against accepted HEAD | no |

Stage 01 dispatches exactly three readers. Stages 02 and every quorum dispatch
exactly three brains. A count is never reduced to fit capacity.

Stage 01 conflicts that remain unresolved consume stage-03 question slots ahead
of any stage-02 synthesised question: an unresolved intent conflict is by
definition higher blast radius than anything downstream.

## The quorum contract

### Admissibility

A question is admissible only if all five hold. This gate is what stops the
quorum becoming a chat channel:

1. It **blocks** named work — a task id, gate id, or planning artifact. A
   question blocking nothing is an opinion and is discarded.
2. It is decidable from the repository, the spec, and `decisions.md` — not from
   knowledge only the user has (budget, deadline, who the users are, what the
   product is *for*).
3. It carries an **axis**: a stage-03 question id, or the literal `new`.
   It also carries a **blast radius** from the closed vocabulary
   `task | phase | run | contract` — `contract` meaning it changes a public
   interface or the spec. The vocabulary is closed because adoption checks it
   against the irreversible-axis list; an unenumerated value would pass that
   check by not matching anything, which fails open.
4. It passes the options test from `plugins/superb/agents/architecture-discovery.md:54-69`
   — blank the title, keep the options, and a reader can still tell what is being
   decided.
5. It is one decision, not several wearing one coat.

A worker never dispatches brains. It publishes its immutable result with status
`NEEDS_CONTEXT` or `PLAN_CONFLICT` and a question record file. `BLOCKED` still
means halt: three brains cannot conjure an API key.

`qid = sha256(normalize(question) || "\x00" || axis)`. The decisions digest is
**not** part of the qid — including it would give the same question a new
identity every time anything else was decided, and the run would re-litigate
itself. It is recorded separately as `context_digest` for audit.

### Confidence by grounding rung

**A brain never types a number.** It selects a grounding rung; the controller
derives the value and verifies the citation.

| Rung | Value | Must cite | Adoptable |
| --- | --- | --- | --- |
| `specified` | 0.95 | a spec, intent-brief, or human-decision line that resolves | yes |
| `code-evidenced` | 0.85 | repository `file:line` that actually contains the claim | yes |
| `convention-cited` | 0.70 | ≥2 `file:line` exemplars | **no** |
| `engineering-judgement` | 0.55 | none | no |
| `speculation` | 0.30 | none | no |

**These five values are schema constants, not run configuration.** Putting them
in `## Run` as tunables would let an autonomous controller lower its own adoption
bar — the same class of self-serving move as downward reclassification, and
structurally unavailable for the same reason.

**The adoption floor is `code-evidenced` (0.85).** Everything below it escalates
by arithmetic. This is the old law re-encoded rather than deleted:
`pipeline/SKILL.md:65-67` holds that "configurability, reversibility,
convention, a familiar codebase pattern, and documenting an assumption do not
authorize choosing an unanswered option." `convention-cited` therefore sits below
the floor. A machine may decide what the spec or the code entails. It may not
decide by imitation.

A citation that does not resolve, or that resolves to a line not containing the
claim, **demotes the response to `engineering-judgement` (0.55)** — demotion, not
rejection. Rejection discards information and hands a malformed brain a veto;
demotion prices the claim at what it turned out to be worth, and 0.55 is below
the floor, so an inflated claim is defeated arithmetically rather than argued
with.

A `rung` value outside the enum is **schema-invalid**: the response is not
clustered, not defaulted, and not repaired. That brain is re-dispatched once with
the identical payload under a new attempt; a second malformed response is a
non-response, the quorum is incomplete, and an incomplete quorum escalates. A
brain must not be able to force adoption by malforming — only to force a human
look.

Three further demotions to `engineering-judgement` (0.55):

- **No second-best.** Every response must name a rejected alternative with a real
  reason. An empty alternatives list is rejected outright, re-dispatched once,
  and a second empty counts as a non-response.
- **Second-best on the same rung as the top answer.** A brain that cannot
  separate its own top two must not drive an adoption.
- **Empty falsifier.** `what_would_change_my_mind` empty means the answer was not
  examined.

**Run-level inflation check:** after five or more adopted events, if the mean
effective value exceeds 0.90, the adoption floor rises one rung for the rest of
the run. Individual confidence claims are often unfalsifiable; the distribution
is not.

**How that is stored, because the obvious way is forbidden.** The rung values and
the base floor are schema constants and must never appear in `## Run` — a
controller that can write its own floor can lower it. So `## Run` carries
`floor_adjustment`, a non-negative integer count of rungs, default `0`, and the
effective floor is the base floor raised by that many rungs. The adjustment is
**monotonically non-decreasing**; a tracker write that lowers it is
schema-invalid, exactly as a downward review-intensity transition is. This keeps
the constants frozen while leaving the adjustment auditable, and it means the
floor actually applied by a past run is reconstructible from its tracker without
the run having been able to choose it.

### Independence

Three instances of one model reading one payload are **not three independent
samples — they are one prior sampled three times.** Shared weights plus shared
prompt produce correlated error, so agreement is far weaker evidence than it
looks. Independence has to be manufactured.

All three receive the **identical verbatim question**, which fair comparison
requires. They receive **different reading assignments**: brain 1 grounds in the
spec and intent brief, brain 2 in repository code and tests, brain 3 in the
decisions record and phase plan. This biases each toward a *source*, never toward
an answer, which is what actually decorrelates them. It also makes the rung
distribution informative: three brains that each looked somewhere different and
none found grounding is the mechanical signature of drift.

Independence is a property of the payload, not of concurrency — at
`worker_limit < 3` the brains run sequentially with the same assignments.

Brains read `decisions-effective.md`, a generated read-only projection carrying
each resolved decision's question, adopted answer, and provenance — **and not its
value, and not its rejected alternatives.** Adopted answers must be included or
brains re-litigate settled ground and manufacture drift. Values must be excluded:
a brain reading "adopted at 0.85" treats the decision as soft and reverses it,
where a brain reading it as simply a decision treats it as binding. Provenance
must be included so a brain can recognise and refuse to contradict a human
decision.

The payload **must not** contain:

- any other brain's answer, or the fact that the others exist beyond "you are one
  of several"; a brain that knows it is competing on argmax has a dominant
  strategy of claiming a high rung;
- the controller's own leaning or hypothesis;
- **the adoption floor** — the numbers in this document must not appear in a
  brain's payload; a brain that knows the bar clears the bar;
- the identity or distress of the raising worker; pressure inflates confidence;
- any deadline, budget, elapsed time, or cost signal;
- the raiser's own candidate options or recommendation;
- prior rejected alternatives for this axis, except in a re-open, which carries
  the challenging evidence but never the original score or who chose it;
- conversation history of any kind.

### Comparing prose answers

Where the question supplied named options, comparison is string equality on
`answer_key`. Where it did not, two answers are the same answer iff their
`consequence` sets are mutually non-contradictory — a `consequence` being an
assertion that would be verifiably true of the repository if the answer were
adopted (a file that would exist, a signature, a command that would pass), never
a rationale. **When in doubt they are different answers**, which pushes toward
escalation, which is the safe direction.

Three answers that neither agree nor contradict because they describe different
things is a malformed question, not a split: escalate as
`question-not-decidable`. The controller never synthesises a fourth answer — that
would be an unreviewed decision with no confidence attached.

A cluster's rung is its **maximum** member rung, not the mean. Averaging lets one
weak agreer drag down a well-grounded answer and lets two weak agreers
manufacture a majority.

### Adoption

Adopt only if all hold:

- three valid responses returned, fewer than two carrying a blocker;
- the winning cluster's rung is at or above `code-evidenced` (0.85);
- **where more than one cluster exists**, the winning cluster's rung is
  **strictly higher than the runner-up cluster's**;
- no `blast` entry is on the irreversible-axis list;
- the adopted consequences contradict no `Provenance: human` decision on the axis;
- `decision_depth ≤ 2`;
- the drift budget is not exhausted.

Otherwise escalate. There is no third outcome and no controller override.

A cluster's rung is its **highest** member rung, never the mean. Averaging
punishes a correct lone expert and lets two weak agreers manufacture a majority.

**Two-of-three agreement is not sufficient on its own.** The bar is on rung, not
on headcount. This is the rule most likely to be "simplified" into majority
voting; it belongs in Red Flags.

**Equal rungs never adopt.** Two clusters both at `code-evidenced` escalate even
though both clear the floor: two brains reading the same code and reaching
different answers from evidence of the same quality is exactly where a numeric
margin would manufacture a winner out of noise. Rung strictness refuses to.

Unanimity is the one case with no runner-up, so the strictness test is vacuous
and the floor alone governs.

**Rung strictness subsumes the three-way-split rule, which is therefore not
implemented separately.** An earlier draft escalated every 1-1-1 split
unconditionally. That is wrong in one important case: one brain citing the spec
against two speculating *should* win, and the unconditional rule would discard
it. Where the three-way split genuinely signals underdetermination — three
answers resting on evidence of equal quality — rung strictness already escalates.
Two overlapping rules are worse than one correct one.

**There is only one tie-break, and it is escalation.** Higher rung already
decides every adoptable case, and equal rungs never adopt — so a second-level
tie-break among equal-rung clusters would have no case left to fire on. An
earlier draft added "prefer the answer whose consequence set is a strict subset"
as a tie-break; under rung strictness that rule is unreachable, and an
unreachable rule in a skill is worse than none, because a maintainer will
eventually make it reachable to "fix" it.

The subset heuristic survives only as **escalation-report ordering**: when a
question escalates, the candidate foreclosing least is presented first, because
*between answers the run could not separate, the one that forecloses less is the
cheaper thing for a human to approve*. That is presentation, not adoption.

Never coin-flip, never take the first response, never take the longest answer,
and never dispatch a fourth brain: that is a retry-until-you-like-it loop wearing
a quorum's clothes.

### Drift budget

**Three adoptions per phase, ten per run.** On exhaustion the run escalates the
next question with the full adopted list attached. Escalations never count
against it; only adoptions do.

A run needing fifteen autonomous decisions did not have an adequate stage-03
round, and the repair is a second human gate rather than more quorum.

**The drift budget is the decision-cost cap, not the run-cost cap.** Ten
adoptions is at most thirty brain dispatches. The dominant spend is elsewhere: at
full review intensity a task costs an implementer, a reviewer, up to two fix
rounds of fixer-plus-re-review, and sometimes an adversarial pass — four to seven
agents. Forty tasks is 160–280 agents for implementation alone, and that number
is entirely unrelated to how many questions were raised. Two counters, two
failure modes:

| Counter | Caps | Failure it prevents |
| --- | --- | --- |
| `adoptions_phase` / `adoptions_run` | accumulated machine authority | building something nobody asked for |
| `agent_dispatch_count` | review spend | a run costing more than it is worth |

A soft threshold on the second escalates *reporting* the overrun; a hard one
stops the run resumably. Never a silent intensity downgrade — the dial is
upward-only.

### Dispatch budget, adopted by quorum

Recorded as `Q-dispatch-budget` in the run's decisions file. Unanimous on shape,
all three brains at `engineering-judgement` — below the floor, so the quorum
escalated and the decision was taken under controller delegation, not adopted on
its own evidence. It is a first estimate and is labelled as one.

At the close of stage 07, when phase plans exist and task counts are real,
compute and **freeze** into `## Run`:

```
dispatch_projection   = 7 × total_tasks + 3 × drift_budget_run + 5
dispatch_soft_ceiling = ceil(1.25 × dispatch_projection)
dispatch_hard_ceiling = 2 × dispatch_projection
```

**Every phase is priced at the `required`-plus-adversarial ceiling of 7
regardless of its recorded review class.** That is what makes the projection
frozen rather than recomputed: an upward ratchet can never consume budget it was
not granted, so a safety mechanism can never push a run into its own stop.

Check before every dispatch. At soft: dispatch anyway, enqueue exactly one
non-blocking `dispatch-overrun` escalation, and make `status` and the terminal
report lead with the overrun. At hard: refuse that dispatch, let in-flight
workers finish, publish and import to `[x]` while holding only integration, set
`next_action = await-dispatch-budget`, and stop resumably until a
`dispatch.extend-budget` decision with `Provenance: human` raises it — at most
twice, then terminal.

**One enumerated exemption proceeds over the hard ceiling**, recorded
`over-hard`: re-dispatching the missing brain indices of an already `in_flight`
quorum. Refusing it strands a partial quorum, and a partial quorum is never
evaluated — so the refusal would deadlock the run permanently rather than stop it
resumably. This is the same shape as the `worker_limit` deadlock and was found
the same way.

**The budget trips at raise time, before dispatch.** The triggering question is
never sent to brains.

Work in flight then follows the freeze semantics of an open quorum at that blast
radius — with one distinction the obvious implementation gets wrong. Running work
**finishes, publishes, and is imported** to `[x]`; only *integration* is held.
Freezing the import too loses a finished task's evidence and repeats the work on
resume. Completion and integration are already separate facts in this schema;
this is where that separation earns its keep.

**The freeze on raising is run-wide, not radius-wide.** Once the budget is
exhausted no worker anywhere may open a new quorum; a second worker hitting a
question attaches it to the same escalation. Otherwise N workers produce N
escalations and the human is handed a queue instead of a decision.

### Budget extension

A human answering the escalation grants an **explicit finite extension**, never a
reset. A budget that refills whenever a human glances at it is a speed bump, and
the reflex answer to "may I continue?" is yes. But permanent exhaustion is also
wrong: it lets one unlucky early question kill a healthy run, which teaches the
controller to avoid raising questions at all — the exact opposite of the design's
intent.

The extension reuses the existing pipeline's remediation-extension decision
contract, re-pointed from remediation rounds to the drift budget. That contract
was listed as dropped on the grounds that no human is present mid-run; a human
answering an escalation **is** present, so the reasoning did not apply here. Its
field discipline is proven and it fails closed on stale or generic authority.

`Decision action: quorum.extend-budget` requires all of: `Authorized run` (exact
run id); `Source revision` (the tracker revision at grant time); `Authorized
through` (a **finite** new ceiling, never "unlimited"); `Granted against` (the
**verbatim adopted list** the human was shown); and `Provenance: human`.

`Granted against` is the anti-reflex mechanism: the human is on record as having
seen the specific decisions they are waving through, so a bare "continue" cannot
become an extension.

**Extensions are capped at two per run.** After the second the budget is terminal
and the run stops resumably. Three grants with no change to the underlying
problem is not a budget problem — it means stage 02 selected the wrong four
questions, and the repair is a new run with better ones, not a third tranche of
machine authority.

`quorum.extend-budget` is never grantable by quorum: the action requires
`Provenance: human` and the validator rejects it on any quorum-provenance
decision.

### Escalation

Escalations queue and surface **at stage boundaries only**, batched up to four
per `AskUserQuestion` call, ranked by blast radius. More than four pending means
ask four and halt on the rest. Independent work continues while the queue fills.
`next_action` shows `await-escalation-batch` — never a generic block.

### Replay and idempotency

- **One adopted answer per qid per run.** A re-raise returns the recorded answer
  and dispatches nothing.
- The quorum transition is written through the tracker lock with
  `transition_id = "quorum-" + qid`, inheriting replay-is-inert semantics.
- **Payload identity is per brain, and deterministic.** Because the three brains
  receive different reading assignments, there is no single payload digest.
  `build_payload(qid, brain_index)` is a pure function of the question record,
  the projection, and the index, so brain *n*'s payload is reproducible byte-for-
  byte on any later attempt. The `in_flight` record persists **three** digests,
  one per brain index. "Identical payload" throughout this document means
  identical to that brain index's own payload, never identical across brains.
- **Three-phase record**, so an interruption is always classifiable: `in_flight`
  persisted with the three owner ids and their three payload digests **before**
  dispatch; responses landing as individual immutable files; the finalised status
  persisted with the computed result.
- `in_flight` with three response files: compute and finalise, do not
  re-dispatch. With zero to two and no live owners: **re-dispatch only the
  missing brain indices**, each rebuilt from its own `(qid, brain_index)` and
  checked against its persisted digest. Never re-dispatch a brain that already
  answered, and never discard an existing answer to obtain a tidier set — a
  partial quorum is never evaluated. A finalised record is never recomputed.
- A qid whose `context_digest` no longer matches current `decisions.md` is **not**
  re-opened; it is flagged to stage 11 as `stale-context`. Re-deciding on resume
  is precisely the silent-divergence failure.
- **Never re-run a quorum to check.** A second run with different brains produces
  a different answer roughly as often as the rung gap is narrow, and the
  controller has no principled way to prefer either.

## Review-intensity dial

`review_class ∈ {final-only, required}`, fixed at stage 04, carried in phase-plan
metadata, mirrored into the tracker.

`required` buys the full per-task gate: fresh implementer dispatched with a task
**brief file** rather than the plan; review package generated from the persisted
reservation baseline, never `HEAD~1`; a task reviewer returning three verdicts
(spec, quality, and verification evidence from an independent re-run); a fix loop
to **zero open findings at every severity**, one fixer per round carrying all
findings; completion only after a round returns zero.

`final-only` buys mechanical verification only. Stage 11 is the net.

**The dial may never switch off**, at any class: the adversarial trigger check;
typed write-scope declaration and conflict detection; digest-bound typed PASS
evidence; the `baseline..source-head` range proof and integration ancestry
predicate; immutable four-part worker result identity; TDD RED-before-GREEN
evidence recorded in the implementer report; the most-capable-model policy; and
the zero-open-findings bar itself. The dial controls *whether a reviewer runs*,
never *what bar that reviewer applies*.

Adversarial triggers are independent — any single one fires: concurrency,
authn/authz, crypto, persistence schema, migrations, deletes, regulated data,
public API or wire format, or more than 300 changed source lines. **A 10-line
auth change is high-risk.** Collapsing this into "300 lines AND a risky path" is
the obvious and wrong reading.

**Upward ratchet only**, `final-only → required`, mechanically triggered, never
downward and never by quorum:

| Trigger | Condition |
| --- | --- |
| (a) | any task produced a CONFIRMED or unrefuted PLAUSIBLE adversarial finding |
| (b) | the phase suite has failed twice or more |
| (c) | a stage-10 root cause traced into a file inside this phase's write scopes |
| (d) | a quorum adopted a decision in this phase at `code-evidenced` rather than `specified` |
| (e) | cumulative changed source lines in the phase exceed 300 |

A ratchet does not retroactively review complete tasks. It gates every remaining
task and adds a phase-scoped review over the phase's whole edge at the
zero-open-findings bar. A tracker `review_class` differing from plan metadata is
legal **only** with a matching ratchet record.

## Contradiction routing

| Situation | Route |
| --- | --- |
| Code does not comply with a decision | ordinary finding, ordinary fix loop |
| Plan-mandated finding tracing to a **human** decision | **halt** to the escalation queue, never quorum |
| Plan-mandated finding tracing to a **quorum** decision | re-open that qid at a raised bar |
| Plan-mandated finding `writing-plans` invented | ordinary quorum |
| `DECISION-CHALLENGE` against a **human** decision | **halt**, always |
| `DECISION-CHALLENGE` against a **quorum** decision | one re-open at a raised bar |
| Second challenge to the same D-ID | **automatic halt** |
| Fixer disputes a reviewer finding | **one adjudicator**, quorum only on PLAUSIBLE |

The controller's only power here is routing. It may not decide which of the
reviewer and the decision record is right.

**A fixer's dispute is not a quorum call, because it is not a decision.** "Can
line 41 be null" is a *fact*, settled by reading code and running an experiment,
not by a confidence-weighted vote. Three models agreeing that line 41 cannot be
null is far weaker evidence than one model running the test. Routing facts to the
quorum is a category error, and it is the mechanism by which a quorum degrades
into a general-purpose "ask three models when unsure" reflex — which is itself a
drift vector.

The dispute is admissible only with a refutation citing `file:line` or a command
and its output; a bare disagreement is inadmissible and the finding stands.

One **adjudicator** — most capable model, read-only — receives the finding, the
rebuttal, and the review package, and settles the fact by citation or focused
experiment, returning CONFIRMED, REFUTED, or PLAUSIBLE. CONFIRMED means the
finding stands and the fixer fixes. REFUTED closes it with the adjudicator's
citation. **Only PLAUSIBLE** — genuinely irreducible — becomes a quorum question,
and by then it honestly is a judgment call rather than a fact. Its candidates are
framed neutrally, not loaded toward fixing.

One agent instead of three, more accurate, and it preserves what the quorum is
for: **choices, not facts.**

An adjudication never enters `decisions.md` as a requirement decision. It belongs
in the findings ledger.

**A reviewer finding may not reverse a decision on a styling preference.** Under
zero-open-findings every Minor must be fixed — so if a quality-rubric Minor
requires reversing a quorum decision, an automatic reviewer win lets a naming
opinion silently overturn architecture. The reviewer's finding therefore prevails
**only** when it is Critical or Important *and* its verdict part is
spec-compliance or verification-evidence. A Minor, or any quality-part finding,
that would require reversal goes to an unbiased reconciliation; if the decision
survives, the finding is recorded `REFUTED — governed by <D-ID>` and does not
block completion. That is the one principled exception to zero-open-findings, and
it is narrow and recorded rather than discretionary.

**The fix loop does not stall during reconciliation.** The task moves to `[?]`
with a reconciliation question reference, its owner slot releases, and
independent work continues. The fix-round counter **does not increment** — a
decision dispute must not burn the three-round budget and escalate for the wrong
reason.

## Completeness proposals

The stage-11 critic classifies every item as `SPEC-NOT-MET` or
`MISSING-FROM-SPEC`.

`SPEC-NOT-MET` is not a proposal — it is a finding, and it enters the fix loop at
the zero-open-findings bar.

`MISSING-FROM-SPEC` is **frozen**: written to the run's
`completeness-proposals.md`, given an ID, surfaced in the terminal report, and
never converted into a task, dispatched, or quorum'd. `next_action` becomes
`complete-with-proposals`.

This is not merely forbidden, it is impossible: phase creation is a stage-06
transition, and after stage 06 closes the phase set is immutable. The state
machine enforces it rather than the controller's restraint.

The reasoning belongs in the skill so future maintainers can defend the rule
rather than assert it: every other quorum answers a question that *blocks* work,
and quorum exists to unblock, not to enlarge. "Should we also handle X" has no
natural ceiling — three brains asked whether an adjacent case is worth covering
will say yes, confidently, because yes is always defensible. It is the one
question class where quorum has a systematic rather than a random bias.

## Failure modes and mitigations

**Quorum drift — three agents confidently agreeing on something the user never
wanted.** All three read the same brief; if the brief is wrong, unanimity is
*guaranteed*. Unanimity is a failure mode of this design, not its safety
property, and the mechanism looks strongest exactly when it is most dangerous.

- **The irreversible-axis list**, closed and enumerated, which no confidence can
  buy past: product scope; destructive data operations and schema migrations;
  adding an external service or paid dependency; public API or wire-format
  contract; the authn/authz model; anything that costs money to run; licensing;
  anything writing outside the repository.
- **Anchoring.** Every response must cite at least one stage-03 decision or spec
  line in `consistent_with`. An answer citing only repository code is capped at
  `convention-cited` and therefore auto-escalates. Every adopted answer traces to
  something the user actually said.
- **Negative space.** `forecloses` is required, and the union of the three lists
  is checked against the irreversible-axis list before adoption. Asking what an
  answer *destroys* surfaces risk that asking what it *achieves* never does.

**Confidence inflation.** Covered by the rung table, citation verification, the
second-best and falsifier caps, the run-level distribution check, and the floor's
absence from the payload. Additionally: the controller must **never** ask a brain
to reconsider its confidence. That is a pressure signal; it moves the number
without moving the evidence.

**Contradicting a human answer.** Detection is structural, not semantic. Every
stage-03 question has a stable axis id; every later question is tagged to one.
Before adoption the controller checks whether the adopted consequences require a
different option on an axis a human already decided. Rejected attempts are
**recorded, not discarded** — a run with several `rejected-contradicts-*` events
is a run whose brains keep pulling away from what the user asked for, and that
count belongs in the terminal report as the earliest available warning.

**Contradicting an earlier quorum answer.** One adopted answer per qid. The axis
index in `decisions.md` is validated on every write, and a file holding two
adopted contradicting answers on one axis **fails validation and is a read-only
stop** — the same severity as a foreign schema. A contradicting question becomes
a **re-open at a raised bar, at most once per D-ID per run**; a second challenge
halts. This is the anti-oscillation rule that stops a run spending its budget
arguing with itself.

**Cascading on a low-confidence answer.** Provisionality propagates: any task
whose dependency closure contains a decision adopted at `code-evidenced` rather
than `specified` is `provisional`, which ratchets its phase to `required`,
obliges stage-11 reviewer A to score and name it, and lists it in the terminal
report. The tainting decision's ID and adopted answer are copied **verbatim into
the reviewer's global-constraints block** — that second half is what makes it
more than a label.

**Rungs inherit downward.** A quorum raised *by* a tainted task inherits the
taint, and its adopted rung is capped at the minimum of its own and the tainting
decision's. A `specified` answer resting on a `code-evidenced` premise is not a
`specified` answer. Without this the argmax will happily build a tower on a weak
root, laundering a soft premise into confident descendants.

**Depth cap of 2**: human is depth 0, an answer citing only depth-0 is depth 1,
and depth 3 is not quorum-eligible whatever its rung. Three layers of inference
from the last thing a human actually said is where the run stops building the
user's product and starts building its own.

**Unbounded quorum depth.** Brains cannot raise questions — the response schema
has no field for one; the only exit is a blocker. Brains cannot spawn: the
`pipeline-auto-brain` agent is restricted to **`Read`, `Grep` and `Glob` only** —
no `Bash`, no `Agent`, no `Write`, no `Edit`.

**`Bash` is excluded deliberately, and the reason is that "read-only Bash" is not
a thing the platform can give us.** Agent frontmatter allowlists *tools*, not
*commands*: a brain holding `Bash` can run `echo > decisions.md` as easily as
`git log`, so the restriction would be prose a brain could ignore rather than a
boundary a validator can assert. The entire justification for restricting brains
is that one with write access can edit the audit trail and make the whole record
worthless; a rule that cannot be enforced does not deliver that. `Read`, `Grep`
and `Glob` cover everything grounding actually needs — resolving a citation to a
file and a line, and searching for exemplars — so the capability is not missed.

**The same restriction binds `pipeline-auto-intent-reader`, for the same
reason.** It reads and reports and never designs, and what it produces is the
intent brief that every later `consistent_with` citation anchors to — so a shell
there rewrites the anchor rather than the record, which is worse, not better.
Both agents declare exactly `{Read, Grep, Glob}`.

Assert the tool set as an **exact set**, never as a blacklist. An exact-set
assertion fails on a tool nobody thought to forbid; a blacklist only fails on the
ones somebody remembered.

This makes every leg of the boundary mechanically testable, which is the point:
`tests/test_skill_structure.py` asserts the agent's `tools:` set is exactly
`{Read, Grep, Glob}`. Today's `brainstorm-architect` runs
with all tools, and a brain with Write can edit `decisions.md`, which makes the
entire audit trail worthless. At most one quorum is in flight per run, which
makes "a quorum cannot trigger a quorum" true by construction.

**Cost blowup.** The drift budget is the cap. Brains consume `worker_limit` as
three unique owners, and implementation tasks may occupy at most
`worker_limit - 3` slots — otherwise a blocked task holds the slot needed to
unblock it and the run deadlocks permanently. `worker_limit >= 4` is required for
concurrency; below it, tasks serialise so the brain slots stay free. File
handoffs everywhere: brains receive paths, never contents, and the controller
never reads a review package or diff into its own context.

## State schema

**`pipeline-auto/v1`.** A new family name, not `pipeline-run/v3` — a shared
family name is an invitation to write a migration, and there must never be one.

No migration from `pipeline-run/v1` or `/v2`, in either direction, ever.
Recognised-but-foreign, missing, malformed, or unknown is a **read-only stop**:
preserve the directory, change no files, dispatch nothing, and emit a diagnostic
naming the other skill and saying the two do not interoperate.

Run artifacts live under `docs/superpowers/runs/<run-id>/`, with large ephemera
(briefs, reports, review packages) in a self-ignoring `scratch/` **inside the run
directory** — never under `.superpowers/sdd`, whose durability hole is exactly
what this hybrid exists to close.

New tracker sections: `## Stage` (stages 01–12 are otherwise unrecoverable — a
compaction during stage 02 silently re-runs stage 01 and the run forks from its
own history); `## Intent`; `## Questions`; `## Quorum`; `## Escalations`;
`## Task Review`; `## Fix Rounds`. `## Remediation` is dropped entirely.
`## Tasks` gains `Provisional`; `## Phases` gains `Review Class`, `Class Source`
and `Ratchet`.

`decisions.md` gains a validated axis index and a required `Provenance` field
(`human` | `quorum`). Human answers are `H-<n>`, quorum answers `Q-<hash>`, so
provenance stays legible even if a field is lost. The file is **append-only**;
the only legal in-place mutation is `Adopted → Superseded`.

Decision actions narrow to
`task.resume | quorum.adopt | quorum.extend-budget | dispatch.extend-budget |
none`. Two budgets mean two authorities; sharing one action would let a grant
against one refill the other. The
generic-approval rejection carries over unchanged: a quorum answer of "proceed"
is as empty as a human's.

Provenance must be visible in three places — the decision record, the tracker
index, and the terminal report. A provenance field read only by a validator has
informed nobody.

## Phase breakdown

`superpowers:writing-skills` is TDD for documentation: the pressure scenario is
the test and it runs before the prose exists. The baseline phase is therefore
first, not last.

| # | Phase | Review class |
| --- | --- | --- |
| P01 | Pressure baselines (RED) — agents failing with no skill present, rationalisations recorded verbatim, real-agent evidence labelled separately from simulation | HIGH |
| P02 | Schema and helper core — parse/render round-trip, semantic validation, foreign-schema stop, locking, atomic replace, three failure outcomes | HIGH |
| P03 | Quorum record and decisions contract — qid derivation, three-phase record, replay idempotency, rung recomputation, contradiction detection, depth, budget | HIGH |
| P04 | Task lifecycle carry-over — reserve/start/resume, typed scopes, result identity, baseline range proof, integration ancestry, reconciliation | HIGH |
| P05 | Dial and per-task gate bookkeeping — adversarial trigger evaluation, fix-round cap, the one-way ratchet, provisional propagation | HIGH |
| P06 | Stage 11/12 gate — two reviewers with non-implementer enforcement, `DECISION-CHALLENGE` routing, completeness freeze, phase-set immutability | HIGH |
| P07 | SKILL.md, references, agents, templates, inlined SDD scripts | MEDIUM |
| P08 | Pressure GREEN + loophole refactor | MEDIUM |
| P09 | Executable walkthrough in a foreign empty repo, ending on a clean `git status --short` | MEDIUM |

P01's scenarios seed from `pipeline/tests/fixtures/pressure/`, whose R01 is ideal
because **its correct answer inverts**: v2 says block and ask, pipeline-auto says
quorum. New scenarios required: a quorum-versus-human contradiction; a brain
trying to raise its own question; a completeness proposal the controller wants to
implement; a `final-only` phase whose diff touches auth; a compaction mid-quorum
with two of three responses on disk; a run at budget with a question outstanding.

**Two honest concessions, recorded so nobody plans a test for them later.**

P07's prose cannot be unit-tested. A grep-for-a-sentence test passes the moment
the sentence exists and catches no mistake anyone would plausibly make. Its real
gate is P08's transcripts. The one genuine mechanical test P07 carries is a
**structure validator** — every reference named in the routing table exists on
disk, every agent named exists as a file, every prompt template resolves. Its
named fault: renaming a reference without updating the routing table produces a
dead route at runtime, silently, mid-run.

The *quality* of a quorum answer is not testable in process. The design can test
that a quorum ran, that rungs were recomputed, that contradictions were rejected,
that replay is idempotent, and that the audit record is complete. It cannot test
that three brains gave a good answer. The only instruments are the pressure
scenarios and the stage-11 review of adopted decisions.

## Deliverables

```text
plugins/superb/skills/pipeline-auto/
├── SKILL.md
├── references/{planning,execution,persistence,review,quorum}.md
├── scripts/{pipeline_auto_state.py,task-brief,review-package,sdd-workspace}
├── templates/{progress,decisions,findings,worker-result,
│              verification-evidence,task-brief,worker-report,
│              completeness-proposals}.md
├── prompts/{implementer,task-reviewer,adversarial-reviewer,brain}.md
├── examples/controller_walkthrough.py
└── tests/{test_pipeline_auto_state.py,fixtures/}

plugins/superb/agents/
├── pipeline-auto-brain.md      (tools: Read, Grep, Glob — nothing else)
└── pipeline-auto-intent-reader.md  (same three tools, same reason)
```

`plugins/superb/skills/pipeline/` is not modified.

## Recorded defaults

Taken as defaults rather than spending the user's four questions. Each is
reversible before implementation begins.

| Item | Default |
| --- | --- |
| Stage-01 reader agent | new narrow `intent-reader`, not `brainstorm-architect`, which is too design-inclined and will start proposing |
| Intent brief after stage 03 | immutable; a contradicting finding escalates, the human amends |
| Clustering of prose answers | controller-performed, conservative, frozen to a file at first computation and never recomputed |
| Zero-open-findings at the master gate | yes, same bar as per-task; a gate that can defer while task gates cannot is incoherent |
| Unclassified filesystem | read-only stop; not a quorum call, since brains know no more than the classifier |
| Worktree granularity | one per concurrently dispatched implementer, merged `--no-ff` in task order; `--no-ff` preserves ancestry so the no-squash rule holds |
| Merge conflict at integration | **hard stop.** Under typed write-scope validation a conflict should be impossible, so it is evidence the scopes were wrong — not something to auto-redo past |
| `git status --short` cleanliness at stage 12 | still gates completion; `scratch/` must be covered by a self-ignoring `.gitignore` |

## Unknowns, flagged rather than hidden

The rung values are frozen schema constants rather than run configuration, so a
controller cannot lower its own bar — but the *calibration* behind them is still
uncalibrated. The floor actually applied must be **persisted per run** so a later
session knows what bar governed, and neither floor nor values may ever appear in
a brain's payload. Log every event's rung, runner-up rung, and outcome, and
revisit after three real runs.

The drift budget of three per phase and ten per run is likewise a first estimate.
Its *existence* is principled; its exact value is not. Say both in the skill.
