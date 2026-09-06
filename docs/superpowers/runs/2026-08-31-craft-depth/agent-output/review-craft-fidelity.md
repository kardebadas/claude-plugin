# Fidelity review — `feat/craft-depth` against its spec, plan and brain-agent rulings

Adversarial verification. Every claim below cites the **current working tree**,
not a commit message. Seven commits, `main..HEAD`, 10 files, +498/−28.

Gates run during this review, all green:
`./tools/check-plugin.sh` → `check-plugin: PASS`;
`./tools/check-plugin-mutants.sh` → `killed=35 survived=0`;
`python3 -m unittest discover -s plugins/superb/skills/craft/tests` → `Ran 8 tests … OK`.

The gates passing is not evidence the feature works. Section 3 below shows the
central artifact of D6 fails on the only input it will ever be given in real use,
and no gate notices, because the tests validate it against a fixture format that
craft does not produce.

---

## 1. D1–D7, one at a time

### D1 — One architecture-discovery agent, once per session — **PARTIAL**

Present and well-written:

- `plugins/superb/agents/architecture-discovery.md:1-81` — frontmatter
  `name: architecture-discovery`, `model: sonnet`, `color: cyan`, no `memory:` key,
  matching the plan's Task 4 Step 1 constraints exactly.
- The dispatch is wired at `plugins/superb/skills/craft/SKILL.md:223-245`
  (`## Before the first round: technical discovery`), correctly placed after the
  idea and before round 1, with the `superb:` prefix rule (`:231-233`), the
  once-per-session rule (`:235-236`), the three skip conditions (`:238-242`), and
  the inline fallback so its absence never blocks a round (`:241-242`).
- BA-1's structural guardrail — "the wire format has no field a design decision
  could go in" — is carried at `architecture-discovery.md:25-26, 46-61`.

**Why not full.** Three defects, one of them substantive.

1. **The documented wire format is invalid against craft's own validator.**
   `architecture-discovery.md:35` returns `"options": ["PostgreSQL", "MySQL", …]`
   — bare strings. `plugins/superb/skills/craft/ui/schema.py:173-176` requires each
   option to be a **dict with a non-blank string `value`**:
   ```python
   if not isinstance(option, dict) or not isinstance(option.get("value"), str):
       errors.append("{}.options[{}]: needs a string value".format(where, j))
   ```
   `SKILL.md:349` states the same contract. An agent that follows its own file
   verbatim returns a round fragment `validate_round` rejects.
2. **Importance vocabulary mismatch.** `architecture-discovery.md:41` says
   `importance` is "`required`, `important` or `nice`". `schema.py:9` is
   `IMPORTANCES = ("REQUIRED", "IMPORTANT", "PREFERENCE", "OPTIONAL")` and
   `SKILL.md:345` agrees. Lowercase is wrong, and **`nice` is not a value at all**.
3. **BA-1's validation ruling was softened.** BA-1 §2 required the return be
   "schema-validate[d] … the same way `schema.py:validate_round` validates a
   round — reject anything that isn't a well-formed question list". The plan
   dropped this (Task 4 never mentions validation), and the implementation
   substitutes a judgement call at `SKILL.md:244-245`: *"If it returns prose, a
   recommendation, or a chosen stack rather than questions, discard that part."*
   That is a prose instruction where a ruling asked for a mechanical reject. Note
   the irony: `validate_round` already exists and would have caught defects 1 and 2.

### D2 — Technical questions branch on project shape — **IMPLEMENTED**

`SKILL.md:973-1017`. The eight-noun flat list is gone. What replaced it:

- `:975-984` a `Platform answer → layers present` table, six rows
  (web / API only / CLI / mobile / desktop / browser extension).
- `:986-989` the shape question itself, marked REQUIRED, ordered first — this is
  precisely the user's *"if it's just a back end application, if it's a full stack
  application"* complaint.
- `:994-1006` a worked full-stack example drilling six layers, matching
  `## Domain behaviour`'s Spotify-style depth that BA-1 named as the asymmetry.
- `:1008-1010` the negative rule ("A CLI has no frontend framework, and asking
  about one tells me you did not read my answer").
- `:1012-1017` `No preference — planning skill may decide.` retained, and
  strengthened: silence and "no preference" are now named as different states.

This is the one decision implemented at full strength with nothing softened.

### D3 — Objectivity as a testable predicate — **IMPLEMENTED**

`SKILL.md:295-314` (`### Every question must be objective`) states the blank-the-title
test and a three-row fails/passes table. Duplicated for the agent at
`architecture-discovery.md:50-61`. BA-1 §3's two extra rules also landed:
"One decision per question" (`SKILL.md:311-312`) and "Every question earns its
place" (`:314-315`).

Caveat, and it is inherent rather than a shortfall: BA-1 §3 itself concedes
"nothing in the wire-format validator can catch a vague-but-well-formed option",
so this predicate can only ever be a prompt. Nothing runs it. See §6.

### D4 — Wait in the parent's own turn; no watcher subagent — **IMPLEMENTED**

`SKILL.md:250-271`. `--timeout 600` is on the command line at `:250`. `:251-252`
forbids both failure modes BA-2 named — "Do not end your turn on it, and do not
background it with `&`". `:255-265` records the harness reasoning and the
"sometimes" explanation. `:267-268` "Waiting is executing, not stopping."
`:269-271` frames 600 s as a heartbeat that drains terminal input. `:272-274`
requires the fold and the next round **in the same turn**. No watcher subagent
anywhere. `craftui.py` untouched, per BA-2 ruling 12.

One note on the plan's own verification step: Task 2 Step 3 said run
`grep -n "background command\|end your turn"` and expect **no output**. It
returns two hits — `SKILL.md:251` ("Do **not** end your turn on it") and `:262`
(quoting the old phrase to explain it). Both are the new text, and a wider grep
(`end your turn|end the turn|ending your turn`) finds no surviving instruction to
stop. The intent holds; the plan's stated check was written wrong, not the code.

### D5 — Four named termination conditions — **IMPLEMENTED**

`SKILL.md:275-293`. All four rows present with the right signals: Finish/exit 0
`FINISHED`; Converged/zero open REQUIRED+IMPORTANT → closing round with empty
`questions` and a real `note`; Unrecoverable/exit 1 or 64 → never re-arm; No
progress/two consecutive zero-yield rounds. `TIMEOUT` (exit 2) explicitly named
as "none of these … the heartbeat: re-arm in the same turn" (`:287`). The exit-3
`NOSERVER` split is at `:289-291`. The 12-round cap as bug detector, `:292-293`.

### D6 — `VISION CLEAR` requires two independent passes — **PARTIAL, and this is the serious one**

The instruction landed. `SKILL.md:437-460`: "earned, not judged", the mechanical
check with its exit codes, "Report its output, not your impression of it", the
fresh-context reviewer with BA-3 §4's precondition argument verbatim ("You have
the transcript. You fail that precondition by construction"), remaining questions
become round N+1, and either failure ⇒ `MORE CLARIFICATION NEEDED`.
`SKILL.md:1501-1508` points the completion criteria at the check and names the
`count_answered` folding defect.

**But the mechanical check is broken against real input, and three of BA-3's
four predicate groups are dead or missing.** All four proofs below were executed.

**(a) Structure can never pass.** `check-brief.py:14-16`:
```python
REQUIRED_HEADINGS = ["Confirmed Decisions", "Core Features", "Domain Behaviour",
                     "User Types", "Explicit Non-Goals", "Technical Direction",
                     "Open Questions", "Assumptions", "Contradictions"]
```
Craft's own output template (`SKILL.md:1382-1450`) writes `## Target Users`,
`## Technical Preferences`, `## Remaining Assumptions`, and **no Contradictions
heading at all** — contradictions are per-item `## Contradiction: CON-002`
(`SKILL.md:1266`). Four of the nine required headings are names craft never emits:

```
  MISSING User Types            (template says "Target Users")
  MISSING Technical Direction   (template says "Technical Preferences")
  MISSING Assumptions           (template says "Remaining Assumptions")
  MISSING Contradictions        (template has no such heading)
```

I built a CRAFT.md conforming exactly to `SKILL.md:1382-1450` and ran the check:
```
FAIL structure — missing heading: User Types
PASS nothing-open
SKIP traceability — no round files; hand-written brief
PASS concreteness
check-brief: FAIL   (exit 1)
```
`predicate_structure` short-circuits on the first miss, so a real user would fix
"User Types" and hit "Technical Direction", then "Assumptions", then
"Contradictions". Since `SKILL.md:442-447` makes exit 0 the only pass, **no brief
craft writes can ever reach `VISION CLEAR`** without the agent renaming its own
output headings against its own template. The eight tests pass only because
`tests/test_check_brief.py`'s `COMPLETE` fixture invents headings to match the
script rather than matching the skill.

**(b) Traceability is dead code.** `check-brief.py:68`:
```python
if q.get("importance") not in ("required", "important"):
    continue
```
Lowercase. Real round files carry uppercase — `schema.py:9`, `SKILL.md:345`. Every
question is therefore skipped and `ok("traceability")` prints regardless. Proof
with a round file whose REQUIRED question id appears nowhere in the brief:
```
PASS traceability
FAILURES: []   <- q-auth is never mentioned in the brief
```
BA-3's C1 (every REQUIRED/IMPORTANT id resolves to exactly one Confirmed **or**
Delegated entry, never both) is additionally weaker than specified even if the
casing were fixed: `check-brief.py:71` uses `text.count(qid)` over the whole
document, so an id sitting in `## Open Questions` counts as resolved, and the
"never both" clause is approximated by an occurrence count.

**(c) The `Source: User answer` check is dead.** `check-brief.py:74-77` splits
rows on `|` and needs ≥3 cells — a markdown **table**. Craft's decision template
(`SKILL.md:1215-1225`) is a field block:
```
### DEC-014 — Playlist visibility
**Decision:** …
**Source:** User answer
**Status:** Confirmed
```
Run against a real DEC entry sourced from `Accepted recommendation`, the predicate
records nothing (`FAILURES: []`). BA-3's C2 also required each entry to carry
`**Decision:**`, `**Source:**` and `**Status:** Confirmed` — never implemented in
any form. Conversely, where the table form *is* used the check is over-strict:
it demands `User answer` on **every** `DEC-` row, not only REQUIRED ones as
BA-3 C2 and spec D6 both scope it.

**(d) One concreteness clause was silently dropped.** BA-3 D3 and spec D6 both
require "every user type appears in a journey and a permission rule".
`check-brief.py:81-93` checks Core Features, Domain Behaviour, Explicit Non-Goals
and Technical Direction — there is no user-type check. The plan's prose bullet
listed it ("every `## User Types` entry name appears somewhere under a journey or
permission line") but the plan's own code skeleton omitted it, and the
implementation copied the skeleton rather than the prose.

**(e) Vagueness list truncated.** BA-3 A1 named six markers: `TBD`, `to be
decided`, `etc.`, `as appropriate`, `we'll see`, `something like`. Spec D6 names
three. `check-brief.py:12` implements four (`TBD|TODO|etc.|as appropriate`) —
`to be decided`, `we'll see` and `something like` all pass.

**(f) `BLOCKED BY CONTRADICTION` is still uncomputed.** BA-3 B2 said an unresolved
contradiction makes the status `BLOCKED BY CONTRADICTION`, "today nothing computes
it". `check-brief.py:49-51` folds it into a generic `nothing-open` failure and
requires the literal word `unresolved` on the line; the third status remains
self-assessed. Also, `## Contradictions` is one of the headings craft never writes
(see (a)), so in practice this branch never sees data.

**(g) D6's retrospective measure is absent entirely.** The spec's last D6
paragraph retains BA-3 §3 "in restricted form as a retrospective measure: a
craft-class register entry at pipeline's Stage 1 is a craft defect". BA-3 §3 spelt
out the cost: "Pipeline must carry the class tag in `register.md` /
`templates/register.md`". The plan has no task for it and the diff touches no
pipeline file (`git diff --stat main..HEAD` lists none). The only end-to-end
outcome measure of craft's depth that BA-3 identified does not exist, so §2's
static predicate has nothing to be tuned against.

### D7 — Delegation must carry its cost — **PARTIAL**

Both halves are stated:
- `SKILL.md:316-327` — the four required contents (options on the table, craft's
  recommendation as default, constraints, what goes wrong if chosen badly).
- `SKILL.md:329-332` and the round-file table row at `SKILL.md:351` —
  `delegable` "**default true — except on a `required` question, where it defaults
  to `false`**", with the scope-reduction framing.

Weakened in three ways:
1. **Nothing checks it.** `check-brief.py` never reads `## Delegated Decisions`.
   A delegated entry with none of the four fields passes the gate. Given D6's
   whole premise is that self-assessment does not work, leaving D7 as pure prose
   reproduces the defect one section down.
2. **BA-3 §5's confirmed-scope-reduction record is not implemented.** BA-3 required
   a delegated REQUIRED be written into `## Confirmed Decisions` with
   `Source: User delegated REQUIRED <id>` so C1 can distinguish "handed off" from
   "never established". `SKILL.md:329-332` offers a choice — "Either lower its
   importance honestly, or record the answer in Confirmed Decisions" — and the
   specific `Source:` string is gone. The first branch (lower the importance) is a
   loophole the ruling did not grant: it lets a REQUIRED question be reclassified
   to stay delegable.
3. **BA-3 §5's three-number counting rule is absent.** "Any successor to
   `count_open` … must report **three** numbers — answered, delegated, open."
   `check-brief.py` reports none of them; `SKILL.md:1503-1508` explains the folding
   defect in prose instead. The spec did not carry this ruling forward either.
4. Cosmetic: `SKILL.md:351` writes the importance as lowercase `` `required` ``
   where `:345` defines the value as `REQUIRED`.

---

## 2. The three complaints, from the user's chair

### Complaint 1 — "still missing a lot of questions … generic … more objective" — **FIXED, in the technical section**

I held this to the highest bar and it survives. Trace a *"build me a full-stack web
app"* request:

**Before** (`main`, `SKILL.md:852-872`): `## Preferred technologies` was the
instruction "Ask whether I have preferences for:" followed by eight nouns —
programming language, frontend framework, backend framework, database, hosting,
authentication provider, storage, package manager, component library. No branch on
`## Platform`, no worked example, no drill-down. BA-1 §1 documented the asymmetry
against `## Domain behaviour`, which had a full Spotify worked example with named
sub-entities. Eight axes, identical for a CLI and a full-stack app.

**After** (`SKILL.md:973-1017`), the same request produces:
1. A REQUIRED shape question first — frontend / backend / full stack (`:986-989`).
   This is literally the question the user said was missing.
2. Layer selection from the Platform answer (`:977-984`): web ⇒ frontend, backend,
   data, hosting.
3. Per-layer drill-down (`:994-1006`) — roughly **22 named axes** where there were
   eight: frontend framework, rendering (SPA/SSR/static), styling, component
   library, state management; backend language, framework, API style
   (REST/GraphQL/RPC), background jobs; database engine, relational-or-document,
   migrations, caching; auth provider-or-self-hosted, session-or-token, social
   logins; hosting platform, containerised, CI; package manager, language version
   floor, test framework.
4. A once-per-session `superb:architecture-discovery` dispatch (`:223-245`) adding
   idea-specific candidates on top.
5. Every one of those questions run through the objectivity table (`:295-314`),
   which is the "more objective" half of the complaint answered directly.

And the reverse case works: a CLI request now yields `runtime, packaging,
distribution` and is explicitly barred from frontend-framework questions
(`:982, :1008-1009`).

This is a genuine structural change, not reorganised prose — the old section had
no branch to reorganise. The honest caveats: the depth is confined to the
technical section (§3 "Tailor the questions to the product" at `SKILL.md:354-393`
still tailors only the domain half, which BA-1 §1 flagged and nobody fixed), and
nothing measures whether the drill-down actually happened at runtime.

### Complaint 2 — "I have to say 'already reply, next wave'" — **FIXED**

The root cause BA-2 identified was one instruction: `SKILL.md:226-227` on `main`
said run `wait` "**as a background command**, and end your turn". That text is
gone. `SKILL.md:250-252` now runs `wait --timeout 600` and says "wait for it
inside this turn. Do not end your turn on it, and do not background it with `&`."
A wider grep (`end your turn|end the turn|ending your turn`) finds only the new
negation at `:251` and the explanatory quote at `:256`. `craftui.py` unchanged, as
BA-2 ruling 12 and the spec's Out-of-scope both demand.

Two things to be honest about. This is a prompt fix for a prompt bug, so its
effectiveness is exactly the agent's compliance — there is no test, and none is
possible without a harness. And an in-turn wait means terminal input is queued for
up to ten minutes; the skill acknowledges this at `:269-271` and turns it into the
drain-and-re-arm cadence, which is BA-2 §2's accepted trade-off rather than an
oversight.

### Complaint 3 — "convert a generic idea into something concrete and doable" — **PARTIAL**

The instruction side is real: the objectivity predicate, the layered technical
depth, the delegation-must-carry-its-cost rule, the fresh-context reviewer, and
the removal of "genuinely complete" as the bar. All of that pushes toward concrete.

The measurement side does not work. `check-brief.sh` — the one artifact that was
supposed to make "concrete" objective rather than felt — **fails on every brief
craft can produce** (§1 D6(a), proven), and two of its four predicates are dead
code on real input (D6(b), (c)). `SKILL.md:442-447` makes exit 0 the only pass, so
in the field the agent faces a script that always says FAIL for a reason that is
not about the brief's quality. The two likely outcomes are both bad: it reports
`MORE CLARIFICATION NEEDED` forever, or it does the thing `:444-445` explicitly
forbids and reports its impression instead of the output. The gate is currently
worse than no gate, because it will teach the agent to disregard it.

---

## 3. Spec → plan → implementation: what got dropped where

**Spec → plan.**
- D6's retrospective register-class measure (spec `:129-131`) has no task. Nothing
  in the diff touches pipeline's `register.md` or `templates/register.md`.
- BA-3 §5's three-number convergence count (answered / delegated / open) appears in
  neither spec nor plan.
- BA-1's "schema-validate its return" is in the spec's D1 evidence chain but the
  plan's Task 4 has no validation step.

**Plan → implementation.**
- Plan Task 1 Step 3 prose required "every `## User Types` entry name appears
  somewhere under a journey or permission line". Absent from
  `check-brief.py:81-93`. The plan's own skeleton omitted it, so the implementer
  followed the code and not the requirement — a plan defect the implementation
  inherited rather than caught.
- Plan Task 7 Step 1 said "**Both** craft's own README and the root README's craft
  section". `plugins/superb/skills/craft/README.md` gained 32 lines and the root
  `README.md` gained a two-sentence clause; but Task 7's **Files** list also names
  `plugins/superb/README.md` and `.claude-plugin/marketplace.json`, and neither is
  in the diff. `marketplace.json:12` still describes craft in its pre-change terms.
- Plan Task 7 Step 4 listed `claude plugin validate .` among the gates; I could not
  confirm it was run. `check-plugin.sh`, `check-plugin-mutants.sh` and the unittest
  suite I ran myself and all pass. Task 7 Step 3's mutant was added
  (`tools/check-plugin-mutants.sh`, +1 line) and `killed=35 survived=0` matches the
  plan's expected count.
- Plan Task 1 said 8 tests; 8 exist and pass. They test the script against a
  fixture that does not match craft's output template, which is how (a) survived.

**Not dropped, verified present:** the `--timeout 600` flag, all four termination
rows, the exit-3 split, the 12-round cap, the layer table, the worked example, the
objectivity table in both SKILL.md and the agent, the `delegable` inversion in both
the prose and the round-file table, the two-pass ending, and the version bump to
`0.8.0` in both `plugin.json` files.

---

## 4. Rulings implemented in weakened form

| Ruling | Weakening |
| ------ | --------- |
| BA-3 4 (structure) | Heading list invented rather than taken from the Output template; 4/9 names craft never writes. Vagueness list 4 of 6 markers. |
| BA-3 5 (nothing open) | Only predicate that works. `BLOCKED BY CONTRADICTION` still uncomputed; the contradiction test needs the literal word `unresolved`. |
| BA-3 6 (traceability) | Dead — lowercase importance vs uppercase schema. Even alive: whole-document `text.count`, so an id in Open Questions counts as resolved; "never both" not checked; `Source` parser is table-only against a field-block template; `User answer` demanded of every DEC, not just REQUIRED ones. |
| BA-3 7 (concreteness) | User-type ↔ journey ↔ permission clause absent. The others are shallow proxies — a Core Feature passes on "`:` plus five words", a Domain Behaviour rule passes on containing a `;`. |
| BA-3 12 (delegation cost) | Stated, never checked. The mandated `Source: User delegated REQUIRED <id>` record is replaced by an either/or whose first branch (lower the importance) reopens the hole. Three-number count absent. |
| BA-1 2 (agent contract) | Schema validation → "discard that part". The agent's own documented format is invalid against `schema.py`. |

BA-2's rulings are the exception: 3, 4, 5, 7-11 and 12 all landed at full strength.

---

## 5. Self-consistency

- **`craftui.py` unchanged — confirmed.** `git diff --stat main..HEAD -- plugins/superb/skills/craft/ui/` is empty. The whole `ui/` tree is untouched, honouring spec Out-of-scope and BA-2 ruling 12.
- **Strict Boundaries unchanged — confirmed.** `SKILL.md:250-278` (`# Strict boundaries`) is byte-identical to `main`; the SKILL.md diff contains no hunk in that range. `DO NOT` still lists implement, write application code, create an implementation plan, produce coding phases, produce task lists, sequence development work, estimate development time, create tickets. Craft still refuses to plan.
- **Nothing else contradicts.** The new `## Before the first round` section sits before `## The loop` without duplicating it; the agent proposes and craft disposes (`:244-245`), preserving the boundary; `check-brief.sh` is a *verification* script, not a planning step.
- **One internal inconsistency worth naming**, already covered: the script's heading vocabulary contradicts the skill's own output template in the same skill directory. That is a self-consistency failure of the branch even though the two files individually are coherent.
- File permissions correct: both `check-brief.py` and `check-brief.sh` are `0755`, which the plugin gate requires and the new mutant guards.

---

## 6. What this missed

1. **The gate does not run on real briefs.** Top of the list. Fix is four string
   edits in `check-brief.py:14-16` (`Target Users`, `Technical Preferences`,
   `Remaining Assumptions`, and either add a `## Contradictions` heading to
   `SKILL.md:1382-1450` or teach the script the `## Contradiction: CON-*` form) and
   one at `:68` (uppercase importances). Then re-derive the test fixture from the
   template instead of the other way round.
2. **Nothing tests the script against the skill.** The absent test is: parse
   `REQUIRED_HEADINGS` and assert every entry appears in SKILL.md's output template
   block. It would have failed on commit one. Same shape for the agent's wire format
   versus `schema.py:validate_round` — an available validator that nothing calls.
3. **Question depth is entirely unmeasured.** The user's complaint was volume and
   depth; the check counts headings, not questions. Nothing verifies the layer
   drill-down happened, that a full-stack run asked more than a CLI run, or that a
   layer in play produced any question at all. BA-1 §4's two axes (breadth, depth)
   are prose with no counter behind either.
4. **Objectivity is self-assessed.** D3 is a good predicate and the same agent that
   wrote the question applies it — the exact failure BA-3 §4 diagnosed for the
   completion status, left in place one level down. A cheap fix exists and is not
   taken: `check-brief.py` could reject an adjective-only option list in
   `.craft/round-*.questions.json` against a small stop-list.
5. **The fresh-context reviewer is unspecified.** `SKILL.md:448-456` says "Dispatch
   an agent" — no bundled reviewer (contrast D1, which got one), no output contract,
   no rule that the reviewer must be handed the file rather than the transcript by
   construction rather than by instruction. On a harness where the parent
   inadvertently passes context, the pass silently becomes self-assessment again.
6. **Concreteness proxies are gameable.** "`:` plus five words" and "contains a
   `;`" are satisfied by `- Login: the user does the login thing properly here` and
   `- Order: has fields; exists`. The predicate is deterministic, which was the
   goal, but it measures punctuation.
7. **No end-to-end evidence.** Nobody ran craft with these changes. The branch's
   whole claim — deeper questions, an unattended loop, an earned status — rests on
   instruction text plus one script, and the script demonstrably fails its first
   real input. A single recorded craft session against a full-stack idea, with the
   round files kept, would be the cheapest possible proof and does not exist.
8. **Storage dropped from the technical axes.** The old eight-noun list included
   `storage`; the new layer table and worked example (`:994-1006`) do not mention
   file/blob storage anywhere. Small, but it is a real axis lost in the rewrite.
