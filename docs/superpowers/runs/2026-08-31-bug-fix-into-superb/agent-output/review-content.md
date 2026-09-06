# Content & runtime review — `superb:bug-fix`

Branch `feat/bug-fix-into-superb` (4 commits), repo `/home/wp3/IntellijProjects/claude-plugin`.
Scope: `plugins/superb/skills/bug-fix/SKILL.md`, `plugins/superb/skills/bug-fix/references/investigator.md`,
`plugins/superb/agents/bug-investigator.md`.

Method: walked the skill as an executor against a concrete report —
*"uploads over ~5MB fail silently since Tuesday"* (the README's own example) —
running each Step-1 branch, then handing the result forward through Steps 2–4.
Sub-skills read in full from
`/home/wp3/.claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/skills/`:
`systematic-debugging`, `writing-plans`, `writing-skills`. Siblings read:
`plugins/superb/skills/{craft,pipeline}/SKILL.md`. Also read `tools/check-plugin.sh`
and the README/manifest diffs for corroboration.

---

## 1. Critical — branch 3 imports a skill that fixes the bug, and emits no report

`SKILL.md:40`

> | No subagent mechanism at all | Investigate inline under **`superpowers:systematic-debugging`**, held to the same bar: the brief's report format, and `file:line` evidence for every claim. |

`systematic-debugging` is not an investigation skill. It is a **four-phase
end-to-end debugging process** and it is emphatic that all four phases run:

- `systematic-debugging/SKILL.md:46` — *"You MUST complete each phase before proceeding to the next."*
- Phase 3, `:152-155` — *"**Test Minimally** — Make the SMALLEST possible change to test hypothesis"* — i.e. **edit the code** to confirm the cause.
- Phase 4, `:168-189` — *"Fix the root cause"*: create a failing test case (*"MUST have before fixing"*), implement the fix, verify it.

Three concrete collisions, all reproducible by simply following the two documents:

**(a) It completes Steps 2–4 before they run.** An executor who takes branch 3
and obeys `:46` arrives at the end of Step 1 with the failing test written, the
fix applied and the suite green. Step 2 (`SKILL.md:53-66`, "decide what is the
user's call — more than one viable fix…") is then asked *after* one fix has
already been chosen and shipped, and Step 3's plan (`:69`) documents work already
done. The one thing branch 3 is supposed to preserve — the conductor/specialist
split asserted at `SKILL.md:11-13` — is exactly what it destroys.

**(b) It violates this skill's own red flag and its own brief.**
`SKILL.md:112` — *"About to edit code before an investigator has reported → stop"*.
`investigator.md:88` / `bug-investigator.md:85` — *"Do NOT apply fixes. Do NOT modify any files."*
Phase 3's minimal-change hypothesis test and Phase 4's implementation are both
code edits performed *as part of the investigation*. Branch 3 says it is "held to
the same bar" as the brief; the brief forbids the thing the imported skill
mandates. An executor cannot satisfy both.

**(c) The output shape does not match what Step 2 needs.** Step 2 opens
*"Read the report"* (`SKILL.md:55`). `systematic-debugging` has **no report
section and no output format anywhere in its 283 lines** — its Quick Reference
(`:257-264`) lists success criteria ("Understand WHAT and WHY", "Bug resolved,
tests pass"), not an artefact. Branch 3 gestures at *"the brief's report format"*
but — unlike branch 2 at `SKILL.md:39`, which names `references/investigator.md`
explicitly and says *"verbatim"* — it never tells the executor to open that file.
The `## BUG INVESTIGATION` block (`investigator.md:64-79`) is Step 5 of a
five-step brief that branch 3 is not running.

**Net:** branch 3 does not terminate with a usable investigation report. It
terminates with either a finished fix (if `systematic-debugging` is obeyed) or an
undefined truncation at Phase 1 (if it is not). Branches 1 and 2 do terminate
correctly — both dispatch an agent carrying the brief, whose Step 5 produces the
exact block Step 2 reads.

**Fix direction:** scope the import explicitly — "run **Phase 1 and Phase 2 only**
of `superpowers:systematic-debugging`; do not enter Phase 3 or 4, which apply
fixes — then write up the result in the report format in
`references/investigator.md`, which you must read first."

---

## 2. Major — Step 4's "implement directly" branch contradicts the Overview *and* the plan writing-plans is required to emit

`SKILL.md:96` vs `SKILL.md:12` vs `writing-plans/SKILL.md:61`

Overview, `SKILL.md:11-13`:
> You are the conductor. **You do not investigate, design the fix, or write implementation code yourself** — each phase goes to the right specialist.

Step 4, `SKILL.md:96`:
> | **≤ 3 files, and the plan names exact lines** | Implement directly, test first. |

The Overview states a rule the very next section revokes for the majority case
(most bug fixes are ≤ 3 files). This is not a nuance the reader can resolve —
one of the two is wrong.

Worse, the small branch is unreachable in compliance terms. `writing-plans:56`
says *"**Every plan MUST start with this header**"*, and that header's first line
(`writing-plans:61`) is:

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

So every plan `superb:bug-fix` produces carries, in its mandatory header, an
instruction that the conductor must **not** implement directly. Step 4's ≤3-file
row tells the conductor to disobey the artefact Step 3 just made it produce.

And `writing-plans:153-163` ends with an interactive handoff —
*"After saving the plan, offer execution choice… **Which approach?**"* — offering
subagent-driven vs `executing-plans`. Step 3 gives no instruction to suppress
that question, so the run either stalls on a question Step 4 has already answered
by its own table, or answers with an option Step 4's table does not contain
(`executing-plans` appears nowhere in `SKILL.md`).

---

## 3. Major — Step 4's size predicate is not decidable at that point in the run

`SKILL.md:94-97`

> | **≤ 3 files, and the plan names exact lines** | Implement directly, test first. |
> | **Anything larger** | `superpowers:subagent-driven-development` |

Both conjuncts are unowned:

**Who counts, and against what?** No step assigns the count. The plan is on disk
by then (`writing-plans:18`), and each task carries a `**Files:**` block
(`writing-plans:87-90`) with `Create:` / `Modify:` / `Test:` lines, so a union is
*mechanically* possible — but the skill never says to compute it, and never says
whether `Test:` and `Create:` entries count. A one-line fix to `api/upload.ts`
with a new test file and a touched `.env.example` is 1, 2, or 3 files depending
on a rule that does not exist. The boundary case (exactly 3, plus a test) is the
common case for bug fixes, so this is not a rare edge.

**"the plan names exact lines" is unsatisfiable for part of any plan.**
`writing-plans:87-90` shows line ranges on `Modify:` only:

```
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test:   `tests/exact/path/to/test.py`
```

`Create:` and `Test:` entries have no line ranges and cannot have them — the
files do not exist yet. Since Step 3 *requires* a regression test
(`SKILL.md:76-78`), every bug-fix plan contains at least one `Test:` entry
without lines. Read strictly, "the plan names exact lines" is therefore **never**
true and the small branch is dead code. Read loosely ("the `Modify:` entries have
lines"), it depends on whether the plan author happened to follow an example that
`writing-plans` presents as a template rather than a requirement — nothing in
`writing-plans` mandates line ranges, so a fully compliant plan can lack them and
force a one-line fix through the full subagent-driven machinery.

There is no stated default for the ambiguous case, so two executors given the
same plan route differently.

---

## 4. Major — Step 3 hands writing-plans a spec that does not exist on disk

`SKILL.md:73` vs `writing-plans/SKILL.md:69-70`

> Hand it a spec built from the **proven root cause plus the agreed fix direction**. — `SKILL.md:73-74`

`writing-plans`' mandatory header (`writing-plans:56`, field at `:69-70`) requires:

> **Spec:** [path to the spec/design doc this plan implements — **the plan argues from the spec, so the spec travels with it; executors read both**]

`superb:bug-fix` never writes a spec, a design doc, or the investigation report
to a file. Nothing in Steps 1–3 persists anything. The investigator's report is
subagent output — it exists in the conductor's context and nowhere else. So:

- the plan's required `Spec:` field has no path to point at (an executor filling
  it in truthfully must write "n/a", which `writing-plans:133-138` "No
  Placeholders" arguably forbids);
- more damaging, the ≥4-file branch of Step 4 dispatches `subagent-driven-development`,
  which runs **fresh subagents per task** — those implementers read the plan and
  the spec, and there is no spec, so the *proven root cause*, the single artefact
  this whole skill exists to produce, never reaches the people writing the fix;
- a compaction or a session boundary between Step 1 and Step 3 loses the root
  cause entirely, with no recovery path. Contrast the sibling `pipeline`, whose
  "Run State Law" (`pipeline/SKILL.md:90`) exists precisely because *"a compaction
  or a crash cannot lose the run"* (README:116-117). `bug-fix` has the same
  multi-stage shape and none of the durability.

**Fix direction:** have Step 2 write the investigation report + agreed fix
direction to a small file (e.g. `docs/.../bug-<slug>.md`) and pass that path as
`Spec:`.

---

## 5. Major — the regression-test guarantee is asserted, and nothing verifies it

`SKILL.md:76-79`

> The plan **must** include a **regression test that fails before the fix and passes after**.

Two problems.

**(a) Nothing checks it.** `writing-plans`' Self-Review (`writing-plans:141-151`)
has exactly three checks — spec coverage, placeholder scan, type consistency —
none of which asks whether a regression test is present. `bug-fix` adds no gate
of its own: there is no step between Step 3 and Step 4 that re-reads the plan.
The requirement is prose in a skill that is not the one writing the plan. This is
the clearest instance of the category asked about in brief item 5.

Partial mitigation, worth stating fairly: `writing-plans`' task template is
test-first by construction (`writing-plans:98-121`: write failing test → run to
verify it fails → implement → run to verify it passes), so a compliant plan will
*usually* contain one anyway. The guarantee is likely-in-practice but not
enforced, and `SKILL.md` states it as a hard "must".

**(b) The template's failure mode is the wrong one for a bug fix.**
`writing-plans:106-109`:

```
- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"
```

That is greenfield TDD — the test fails because the symbol does not exist. A
regression test for a *bug* runs against code that already exists and must fail
on a **wrong value / wrong behaviour** assertion. An executor copying the
template's `Expected:` line will write an expectation that never matches, and
`SKILL.md:101-102` ("The regression test fails without the fix. If it passes
without it, it is not testing the bug") gives no guidance on distinguishing
"fails for the right reason" from "fails because I named something wrong" — which
is precisely the trap `writing-plans` was not written to cover.

---

## 6. Major — the investigator brief hardwires `HEAD~1` as "the last change"

`investigator.md:21,30,33` (identical at `bug-investigator.md:18,27,30`)

```
- `git diff HEAD~1..HEAD --stat` — what it touched
...
## Step 2 — Understand the last change
- `git diff HEAD~1..HEAD` for the full diff.
- Read the **complete** content of every changed file, not just the diff
```

`HEAD~1..HEAD` is a mandatory, unconditional step, and it is wrong or unbounded
in the common cases:

- **On a merge commit** `HEAD~1..HEAD` is the diff against the *first parent*,
  i.e. the entire merged branch — potentially hundreds of files, every one of
  which Step 2 orders read **in full**. The example bug ("since Tuesday") on a
  repo that merges PRs lands exactly here.
- **On a squashed branch** it is the whole feature.
- **When the bug is older than the last commit** — which the brief itself
  concedes two lines later (`investigator.md:38-39`: *"The last commit is a
  suspect, not a verdict. Many bugs are older than the change that exposed
  them"*) — the work is entirely wasted, yet it is still mandatory.

There is no budget, no "if the diff exceeds N files, sample it", and no
alternative anchor (a date, a "last known good" commit, `git log --since`), even
though the report the skill collects explicitly includes *"when it last worked"*
(`SKILL.md:46`) — the one field that *would* anchor the search is gathered and
then never used by the brief.

---

## 7. Minor — "verbatim" hands the investigator the plugin's own maintenance notes

`SKILL.md:39` vs `investigator.md:1-10`

> Dispatch a general subagent, giving it `references/investigator.md` from this skill directory as its brief, **verbatim**.

`references/investigator.md:1-9` is meta-commentary addressed to the *maintainer*:

```
# Investigator brief
The brief `superb:bug-fix` gives its investigator.
On Claude Code this ships as a real agent at `agents/bug-investigator.md` ...
The two must stay identical between the SHARED BRIEF markers;
`tools/check-plugin.sh` enforces that.
```

Handed verbatim, the subagent receives instructions about this plugin's packaging
and its own CI script as though they were part of its task — while investigating
an unrelated repo. The `<!-- SHARED BRIEF: begin -->` / `end` markers
(`investigator.md:11`, `:90`) exist and are exactly the right delimiters, but
`SKILL.md:39` never says to take only the content between them.

**Fix:** *"giving it the content of `references/investigator.md` between the
`SHARED BRIEF` markers as its brief, verbatim."*

---

## 8. Minor — "whatever the project uses" is not actionable

`investigator.md:26-30` / `bug-investigator.md:23-27`

> Then read the repo's own instructions — `CLAUDE.md`, `AGENTS.md`, or whatever the project uses — for its conventions, known gotchas, and testing rules. If the project keeps per-task notes or session summaries, read the most recent one.

Asked directly by the brief: yes, this is hand-waving, and it will produce
inconsistent investigations. Three unbounded terms in two sentences:

- **"whatever the project uses"** — no search list, no glob, no depth. One run
  reads `CLAUDE.md`; another finds `.cursorrules`, `.github/copilot-instructions.md`,
  `docs/CONTRIBUTING.md` and a `.windsurfrules`; a third reads none and reports
  nothing, with no way to tell it did less.
- **No "if none exists" branch.** Most repos have none of these files. The
  instruction is phrased as unconditional (*"Then read"*), so the agent has no
  sanctioned exit and will keep hunting.
- **"the most recent one"** — by mtime, by filename date, by git history?
  Recursive from root or a named directory? Unspecified. This project's own
  convention (`docs/superpowers/runs/YYYY-MM-DD-.../`) is date-in-filename and
  would sort differently under each reading.

The two named files are fine; the escape hatch is what makes it non-deterministic.
Contrast the *precision* the same brief demands of its output (`investigator.md:83`:
*"Every claim MUST cite a `file:line` you actually read"*) — the input side is held
to no comparable standard.

**Fix:** name a concrete ordered list, cap it, and give the null branch —
"read the first of `CLAUDE.md`, `AGENTS.md`, `.cursorrules`,
`.github/copilot-instructions.md`, `CONTRIBUTING.md` that exists at the repo root;
if none does, say so and continue."

---

## 9. Minor — two branch conditions and two absolute rules with no check behind them

**(a) "the bundled agent resolve"** — `SKILL.md:38`

> | A subagent mechanism **and** the bundled agent resolve | Dispatch **`superb:bug-investigator`**. |

Nothing tells the executor *how* to determine that. There is no probe, no "check
your available agent list for `superb:bug-investigator`", and no failure
behaviour if the dispatch comes back "unknown agent". The red flag at
`SKILL.md:115-116` warns sharply about the adjacent failure (*"you are about to
dispatch someone else's agent and trust the result"*) but supplies no test — and
that failure is silent by construction, since a personal `bug-investigator`
written for another stack returns a plausible-looking report. The warning names a
risk the skill gives no instrument to detect.

**(b) The two user-level commit rules** — `SKILL.md:86-88`

> - **Never add a `Co-Authored-By` or any attribution trailer.**
> - **Never put a session link, session id, or assistant-generated URL anywhere**

Correct rules, stated in Step 3 (planning), where no commit is written. Step 4's
verification list (`SKILL.md:99-105`) checks four things — test fails without fix,
passes with fix, repro gone, repo gates green — and **none of them looks at a
commit message**. Nothing re-reads the commits at any point. `tools/check-plugin.sh:64-72`
greps for personal leakage but only inside `plugins/superb/`, i.e. this plugin's
own source, never the repo being fixed. Same category as finding 5: prose with no
verifier. (Related: the repo has no `.github/workflows/`, so `check-plugin.sh`
runs only when a human remembers to run it.)

---

## 10. Major — the "full report" Step 1 hands over is never collected

`SKILL.md:46`

> Hand it the full report: symptom, repro steps, error text, affected surface, and when it last worked.

No step gathers those five fields. The skill has no `argument-hint` (contrast
`craft:4`, `pipeline:4`), never references `$0` or `$ARGUMENTS` (contrast
`pipeline:29`), and has no "if the report is thin, ask before dispatching" step.
The invocation the README advertises (`README.md:123`) supplies a single clause —
*"uploads over ~5MB fail silently since Tuesday"* — which is symptom + a vague
"when it last worked" and **nothing** for repro steps, error text, or affected
surface. Walking it: the conductor dispatches immediately, the investigator gets
one sentence, and `investigator.md:56` (*"Find the exact `file:line`"*) is
attempted with no reproduction to anchor it.

The skill's own dependency notices this and looks the other way:
`systematic-debugging:58-62` makes *"Reproduce Consistently… If not reproducible
→ gather more data, don't guess"* a Phase 1 requirement. `bug-fix` defers that
question until **after** a failed investigation (`SKILL.md:49-51`), spending a
full investigator context to learn what one question up front would have
established. Note also that `SKILL.md:49-51` is the *only* handler for a thin
report, and it is reached only via failure.

**Fix:** add `argument-hint: "[bug report]"`, and a pre-dispatch step: if any of
the five fields is missing and the user can supply it, ask once, in one round,
before spending an investigator.

---

## Items checked that came back clean

Stated explicitly rather than padded into findings.

**Brief item 7 — frontmatter description vs `writing-skills`: compliant, no finding.**
`SKILL.md:3`:

> Use when a bug, regression, or unexpected behaviour is reported and the user wants it fixed end to end — "why is X broken", "this stopped working after Y", "fix this crash". Also use when a symptom is known but its cause is not. Not for building new behaviour, and not for a change whose cause is already proven.

Measured against `writing-skills/SKILL.md:99-103` and `:150-172`: third person ✓,
starts with "Use when" ✓, concrete triggers and quoted user phrasings ✓, negative
triggers ✓, **no workflow summary** — it never mentions investigate → decide →
plan → implement, the investigator agent, `file:line` evidence, or the regression
test. 361 characters, inside the ≤500 guidance. This is a better description than
its own sibling's: `pipeline/SKILL.md:3` ends *"Triggers when they want brainstorm
→ plan → implement → review → fix chained"*, which is the workflow summary
`writing-skills:161-165` marks ❌. `agents/bug-investigator.md:3` is also clean
(triggering conditions plus two scope limits).

**Branches 1 and 2 of Step 1 terminate correctly.** Both dispatch an agent
carrying the shared brief, whose Step 5 (`investigator.md:62-79`) emits the
`## BUG INVESTIGATION` block, and Step 2 (`SKILL.md:55`) consumes exactly that.
The not-found path (`investigator.md:84-87` → `SKILL.md:49-51`) is properly
closed on both sides — the brief tells the agent to report what it ruled out, and
the skill tells the conductor to relay it and stop. That reciprocity is the best
seam in the skill.

**The shared-brief duplication is genuinely enforced.** `investigator.md:8-9`
claims *"`tools/check-plugin.sh` enforces that"*; `tools/check-plugin.sh:17-29`
does exactly that (marker extraction + `diff`). Verified by running it — the two
bodies are byte-identical. A true claim with a real check behind it, and the only
one in the diff.

**Sibling conventions (brief item 6).** Compared against
`plugins/superb/skills/{craft,pipeline}/SKILL.md`. Structure matches house style
(`## Overview` → core principle → `## When NOT to use` → numbered steps →
`## Red flags — STOP`, mirroring `pipeline:9/288/688`). `README.md` present as
`check-plugin.sh:47` requires; registered in the root README, both manifests, and
`pipeline:295`; both manifests bumped to 0.6.0 in step. The one divergence is
`argument-hint`, folded into finding 10 below rather than raised separately —
both siblings declare it (`craft:4`, `pipeline:4`) and `pipeline:29` dispatches on
`$0`; `bug-fix` declares none and references no argument anywhere, yet
`README.md:123` documents the invocation as
`/superb:bug-fix uploads over ~5MB fail silently since Tuesday`.
