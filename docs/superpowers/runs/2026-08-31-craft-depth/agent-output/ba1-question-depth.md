# Brain Agent ruling — craft question depth

## Evidence read

- `plugins/superb/skills/craft/SKILL.md` (1414 lines, full read)
- `plugins/superb/skills/craft/ui/schema.py` (238 lines, full read)
- `plugins/superb/skills/craft/README.md` (93 lines, full read)
- `plugins/superb/skills/pipeline/SKILL.md` (811 lines, full read — Stage 1/1b, reviewer
  fan-out, and the composition principle)

## 1. Cause: missing structure, specifically in "Technical direction", not the whole prompt and not absent expertise

The skill's product-domain instructions and its technical-direction instructions are
asymmetric, and the asymmetry is visible in the text itself, not inferred:

- **`## Domain behaviour` (SKILL.md:572-618)** is *worked* — it gives a full example
  (Spotify) broken into named sub-entities (Tracks, Albums, Artists, Playlists, Queue),
  each with 3-6 concrete sub-questions ("Does shuffle operate on the current queue or
  regenerate it?"). The instruction "go deep enough that important product behaviour
  does not have to be invented later" (line 617) has a worked example to imitate.
- **`## Preferred technologies` (SKILL.md:852-872)** is *flat* — it is a single list of
  eight nouns ("programming language; frontend framework; backend framework; database;
  hosting; authentication provider; storage; package manager; component library") with
  no worked example, no branching, and no instruction to go deep once a category is
  named. There is no equivalent of "for a Spotify-like product, this might include..."
  for "for a full-stack web product, this might include...".
- **`## Platform` (SKILL.md:838-848)** asks whether the target is web/mobile/desktop/
  API/CLI/extension/combination, but nothing tells the agent to *use that answer* to
  select which later technical questions to ask. The category the user complained
  about — "if it's just a back end application... if it's a full stack application, it
  should do more questions" — is exactly this missing branch: Platform is asked but its
  answer is never wired to depth.
- **§3 "Tailor the questions to the product" (SKILL.md:354-393)** only tailors the
  *domain* section (Spotify → tracks/playlists/queue; Airbnb → bookings/pricing/
  cancellation). It says nothing about tailoring the *technical* section by project
  shape (frontend-only vs backend-only vs full-stack vs CLI). The taxonomy for product
  domains exists in the prompt; the taxonomy for technical decision-by-project-shape
  does not.

This is a structure gap, not a prompt-tone gap: the prompt already tells the agent
"go deep" and gives it a template for what deep looks like — it just never applies that
template to the technical section. It is also not an absent-expertise problem in the
narrow sense: nothing here requires knowledge a generalist coding LLM lacks (it can
enumerate REST-vs-GraphQL-vs-tRPC trade-offs, SSR-vs-SPA consequences, ORM choices,
etc., unprompted, if asked to). The gap is that craft's own instructions never ask it
to. §2 evidence: the skill is a single continuous document executed by one agent per
round with no per-domain specialist step anywhere — contrast with pipeline (below).

## 2. Should craft dispatch specialist agents? Yes, once, narrowly — not pipeline's ≥2-agent pressure-test

Pipeline's Stage 1b (`SKILL.md:337-364`) dispatches **≥2 agents in parallel to
pressure-test the already-agreed design** — it runs *after* the interactive Q&A
converges, turns every gap into a *new question* (never a self-filled default, line
358), and exists inside a heavyweight gated pipeline (GATE 1/GATE 2, register.md,
findings.md) built for end-to-end autonomous execution. Copying that mechanism
wholesale into craft is the wrong shape for three reasons visible in the files:

- Craft explicitly warns against overhead the pressure-test model would add: "Do not
  turn crafting into hundreds of low-value questions" (line 474), "avoid filling this
  section with implementation trivia" (line 1101), and the whole point of §"Second
  pass" is that rounds get **smaller**, not bigger, over time. A per-round 2-agent
  fan-out inverts that trend on every round.
- Pipeline's pressure-test operates over a finished design (post-Q&A). Craft has no
  such artifact at round 1 — there is nothing yet to red-team.
- Cost: pipeline pays this cost once, at a single stage boundary, for a run whose
  scope is "idea to merged branch." Craft is meant to be lighter and runs many rounds;
  paying a 2-agent dispatch on every round is disproportionate to a skill whose output
  is a brief, not code.

What *does* transfer cleanly is the narrower idea underneath Stage 1b: **turn analysis
into questions, never into decisions.** Apply it once, early, scoped only to the
technical-direction section, not the whole skill:

**Ruling: dispatch one specialist "architecture-discovery" agent, once per craft
session, immediately after §1 (Understand the initial idea) and before the first
questionnaire is written — but only when the idea implies non-trivial technical
ambiguity** (i.e., it's software with an unstated stack; skip it for "a spreadsheet to
track my chores" style asks with no real Preferred-technologies section).

- **Receives:** the raw idea statement, the product category identified in §1, the
  repository inspection result (existing stack, if any — §"Existing technology
  constraints"), and the SKILL.md's own `## Platform` / `## Preferred technologies` /
  `## Data expectations` / `## Real-time behaviour` / `## Integrations` category list
  as its checklist to instantiate.
- **Returns:** a list of *candidate questions only*, each already shaped to the
  `round-NNN.questions.json` schema (`id`, `importance`, `title`, `type`, `options`,
  `why`) — never prose architecture, never a chosen stack, never a file/module layout.
  This is the same contract §"Recommendations" (lines 997-1023) already enforces on
  the main skill ("recommendations must remain separate from my decisions"); the agent
  is bound by the same rule.
- **What stops it designing instead of asking:** the deliverable format IS the
  guardrail — a wire-format question list has no field for "chosen architecture," so
  there is nothing to put a design answer into even if the agent wanted to. Additionally:
  forbid free-form prose output entirely (schema-validate its return the same way
  `schema.py:validate_round` validates a round — reject anything that isn't a
  well-formed question list); and explicitly instruct it, in its dispatch prompt, that
  each option in a `single`/`multi` question must be a *named alternative*, never a
  *conclusion* (e.g. option text is "PostgreSQL" or "MongoDB", never "use a relational
  database because it fits your relational data" — that sentence belongs in `why`, not
  in the option list, exactly as §4's worked examples already format it).
- The craft orchestrator still owns merging this agent's questions into the round file,
  deduping against ones it already planned to ask, and applying importance/volume
  judgment (§3 below) — the agent proposes, craft disposes.

This is strictly additive to the existing skill and costs one extra dispatch at session
start, not one per round — proportionate to the actual complaint (first-round technical
questions are too shallow), not to pipeline's higher-stakes end-to-end guarantee.

## 3. Testable predicate for "objective" vs "vague"

A question is **objective** iff, given only the question text and its options — with no
access to the conversation that produced it — an independent reviewer can do both of the
following and a second independent reviewer would produce the *same* answer:

1. **Name the exact decision being closed.** ("Which backend web framework" is a
   decision; "what backend do you want" is a topic, not a decision — it has no natural
   stopping point.)
2. **Map every option to a distinct, concrete, real-world artifact** (a named
   technology, library, or specific behavior) such that building against any one option
   produces a verifiably different result than building against any other. Adjective-only
   options ("modern", "scalable", "good practices", "simple") fail this test because two
   reviewers building against "modern" will not converge on the same artifact.

Mechanical check a reviewer can run without domain judgment calls: **blank out the
question's `title`, keep only `options`. Can you still guess what decision is being
made from the options alone?** If yes, the options are concrete enough (this is what
"Which backend framework: Express/Fastify (Node), Django/FastAPI (Python), Rails
(Ruby), Spring Boot (Java), Other" passes and "What's your tech stack preference:
Modern, Traditional, Flexible, Other" fails — the second set of options could belong to
almost any question in the document).

`schema.py`'s existing validation (`options[j]` needs a non-blank string `value`,
`_validate_questions`) checks *shape*, not *content* — it will happily accept
"Modern"/"Traditional" as valid options. The objectivity predicate above is a content
check that has to run in the question-authoring step (main skill or the specialist
agent), because nothing in the wire-format validator can catch a vague-but-well-formed
option.

## 4. Volume scaling: two axes, both already licensed by the existing text — the fix is depth, not a cap

SKILL.md never sets a numeric cap; it explicitly avoids one ("Do not turn crafting
into hundreds of low-value questions", line 474; "Use only the areas relevant to the
application", line 480). The user's complaint is under-asking on technical depth, so
the fix must not introduce a volume ceiling — it must let volume scale on the two axes
the skill already implies but doesn't wire together:

- **Breadth** — how many of the listed areas are *triggered* by the idea at all. A
  backend-only API doesn't get `## Visual direction` or `## Navigation` questions; a
  no-payments app skips `## Payments and monetisation`. This axis already works today
  (§"Areas to explore": "Use only the areas relevant to the application", line 480).
- **Depth** — once an area is triggered, how many sub-decisions get asked inside it.
  This axis works today for Domain Behaviour (Tracks/Albums/Artists/Playlists/Queue,
  each separately drilled) but not for Technical direction (flat list, no drill-down).
  The fix in Ruling 2 — classify the app's layers first (frontend-only / backend-only /
  full-stack / CLI / etc., from the existing `## Platform` question), then drill each
  present layer with layer-specific sub-questions the same way Domain Behaviour drills
  named entities — is what makes a from-scratch full-stack app get proportionally more
  technical questions than a backend-only one, without any new cap or knob.

What already stops interrogation, and should stay exactly as-is (no new mechanism
needed): the REQUIRED/IMPORTANT/PREFERENCE/OPTIONAL tagging (prioritise the first two,
line 472), the mandatory shrink-per-round rule (§"Second pass": "The questionnaire
should become smaller and more precise with every pass", line 1150), the `delegable`
default-true escape hatch on every question (schema.py:249-250, "I don't care" closes
it permanently), and the explicit scope fence ("do not ask pointless questions about
implementation details that another agent can safely decide later", line 64). These
four mechanisms already regulate volume; adding a numeric question cap on top of them
would fight the user's actual request (more, not fewer, questions for a from-scratch
app) rather than serve it.
