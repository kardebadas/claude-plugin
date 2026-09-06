# craft: depth, autonomy and a measurable finish

Spec for improving `superb:craft`, from three Brain Agent rulings recorded in
`docs/superpowers/runs/2026-08-31-craft-depth/agent-output/`. Every claim below
is one of their rulings; the file:line evidence is in those reports.

## The three reported problems

1. **Questions are generic.** Craft asks the same shallow technical questions
   whatever the project is. For an app from scratch it should establish whether
   it is frontend, backend or full stack, and then drill into each layer.
2. **Replies are not picked up automatically.** The user has to return to the
   terminal and say "already replied, next wave" before craft continues.
3. **No objective finish.** Craft stops when it decides it is done, rather than
   when the brief measurably is.

## Root causes (BA-1, BA-2, BA-3)

**Generic questions are a missing-structure defect, not a weak prompt.**
`## Domain behaviour` (SKILL.md:572-618) has worked per-entity drill-down;
`## Preferred technologies` (852-872) is a flat list of eight nouns with no
worked example and no branch on the `## Platform` answer. §3 tailors *domain*
questions per product and never tailors *technical* questions per project shape.

**The stall is the harness defect fixed in `pipeline` this morning.**
SKILL.md:227 says run `wait` "as a background command, and end your turn", but
`cmd_wait` (craftui.py:937-1005) is an ordinary blocking process. The wake-up is
a harness capability the skill never verifies. It is *intermittent* because
"background command" is ambiguous between the harness's background-task
mechanism and a shell `&`: a `&` returns instantly and nothing ever wakes the
agent.

**The finish is unmeasurable self-assessment.** `VISION CLEAR` is gated on
"genuinely complete". The ledger, assumptions and contradictions sections are
write-only — nothing gates the status on them. `count_open` (schema.py:211)
scores one round's unfilled questions, never the brief, and `count_answered`
folds `delegated` into settled, so fifteen "you decide" clicks report a fully
converged round.

## Decisions

### D1 — One architecture-discovery agent, once per session (BA-1 4-8)

Dispatched after the idea is stated and before round 1, **only** when the
project is software with an unstated stack. It receives the idea, the product
category, the repo-inspection result, and craft's own technical category list as
a checklist. It returns **schema-shaped candidate questions only** — id,
importance, title, type, options, why. No prose architecture, no chosen stack.

The guardrail is structural: the wire format has no field a design decision
could go in. An explicit rule states that options must be named alternatives,
never conclusions.

Rejected: pipeline's ≥2-agent per-round pressure-test — disproportionate for a
skill whose rounds are meant to shrink.

### D2 — Technical questions branch on project shape (BA-1 10-11)

Give `## Preferred technologies` the depth `## Domain behaviour` already has:
classify the layers present from the `## Platform` answer, then drill each
present layer. Not a new numeric cap — volume already scales on breadth and
depth, and the anti-interrogation machinery (importance tags, mandatory
per-round shrink, `delegable`) already exists.

### D3 — Objectivity is a testable predicate (BA-1 9)

Blank a question's `title` and keep only its `options`. If a reviewer can still
infer what is being decided, the options are concrete. Adjective-only options
("modern", "scalable") fail.

### D4 — Wait in the parent's own turn; no watcher subagent (BA-2 3-5)

The user proposed a watcher subagent. Ruled against, for two reasons: a watcher
has no brief and can only courier `SUBMITTED`, while folding answers and
shrinking the round need the parent's context; and a finished subagent is
exactly what cannot wake an idle controller, so it inherits the bug one layer
deeper.

Instead the parent waits in its own turn, bounded at `--timeout 600`, so it
surfaces every ten minutes, drains anything typed in the terminal, folds it in,
and re-arms. The bound exists because a 15-minute blocking call would swallow
terminal input the skill promises stays the user's (SKILL.md:151-155).

`TIMEOUT` (exit 2) is a heartbeat, not a termination: re-arm **in the same
turn**. The loop is executing, not stopping.

### D5 — Four named termination conditions (BA-2 7-11)

- **Finish pressed** — exit 0 `FINISHED`: final fold, merits test, `stop`.
- **Convergence** — zero open REQUIRED/IMPORTANT: write the closing round with
  empty `questions` and a real `note`, then `stop`.
- **Unrecoverable** — exit 1 or 64: never re-arm. Exit 3 `NOSERVER` splits —
  re-`serve` and re-arm if the user is plainly present, stop and ask if the
  round already timed out once.
- **No progress** — two consecutive rounds yielding no new confirmed or
  delegated decision. Re-asking a third time is arguing with a human who has
  decided not to answer.

Backstop: a hard cap of 12 rounds, treated as a bug detector rather than a
budget.

### D6 — `VISION CLEAR` requires two independent passes (BA-3 4-7, 10-11)

**Mechanical check**, all four predicates:

- **Structure** — every applicable Output heading present, non-empty, free of
  `TBD`/`etc.`/`as appropriate`; inapplicable ones written `Not applicable — <reason>`.
- **Nothing open** — zero REQUIRED and zero IMPORTANT in Open Questions, zero
  unresolved `CON-*`, zero `Impact: High` + `Status: Unconfirmed` assumptions.
- **Traceability** — every REQUIRED/IMPORTANT question id across
  `.craft/round-*.questions.json` resolves to exactly one Confirmed **or**
  Delegated entry, never both; a REQUIRED decision's `Source` must be
  `User answer`, not an accepted recommendation.
- **Concreteness** — every Core Feature has an actor-and-outcome acceptance
  sentence; every Domain Behaviour entity at least one rule beyond its fields;
  every user type appears in a journey and a permission rule; `Explicit
  Non-Goals` non-empty; each tech axis either chosen or the literal
  `No preference — planning skill may decide.`

**Fresh-context reviewer**, given `CRAFT.md` alone. Craft's own criterion is
"understandable by another LLM without access to the original conversation",
which only an agent without the transcript can test — the asker fails that
precondition by construction. Its remaining craft-class questions become round
N+1, not footnotes.

Rejected: "pipeline would open zero register entries" as the bar. The register
absorbs `deps:`, `Files:`, waves and the 12-task split, which craft's Strict
Boundaries forbid it to decide; the target is unreachable and would turn craft
into pipeline. Retained in restricted form as a retrospective measure: a
craft-class register entry at pipeline's Stage 1 is a craft defect, and tunes
the predicate rather than gating it.

### D7 — Delegation must carry its cost (BA-3 12)

Delegated does not block completion, but a bare delegation does. Each needs
options considered, craft's recommendation as the default, the constraints, and
what happens if it goes wrong.

`delegable` inverts to default **false** at REQUIRED importance: a delegated
REQUIRED is a scope reduction and belongs in Confirmed Decisions.

## Out of scope

- `craftui.py` needs no change for D4 (BA-2 12): `wait` already blocks, is
  already bounded, and its exit codes already split every branch.
- Any change to craft's Strict Boundaries. It still stops before planning.
