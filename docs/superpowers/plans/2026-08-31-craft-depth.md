# craft depth, autonomy and measurable completion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `superb:craft` ask deep project-shaped questions, drive its own question rounds without user prompting, and finish on a measured condition instead of self-assessment.

**Architecture:** Three independent changes to one skill. A new executable check turns craft's completion criteria into a script anyone can run twice and get the same answer from. A new bundled agent supplies technical questions craft cannot generate alone. The rest is SKILL.md instruction changes — the wait loop, the technical-question depth, and the gate on `VISION CLEAR`.

**Tech Stack:** Markdown skill files, Python 3 standard library only (matching `craftui.py`, which takes no dependencies), bash for the gates.

**Spec:** `docs/superpowers/plans/../specs/2026-08-31-craft-depth-design.md`

## Global Constraints

- **Python 3 standard library only.** `craft` has no dependencies and must keep none. No pip, no PyYAML.
- **`craftui.py` is not modified.** BA-2 ruling 12: `wait` already blocks, is already bounded, and its exit codes already split every branch.
- **Craft's Strict Boundaries are unchanged.** It still stops before planning — no tasks, no phases, no code.
- **The plugin gate must pass after every task:** `./tools/check-plugin.sh` and `./tools/check-plugin-mutants.sh`.
- **Commit as `kardebadas <16806320+kardebadas@users.noreply.github.com>`. Never add a `Co-Authored-By` or any attribution trailer, and never put a session link, session id, or assistant-generated URL anywhere.**

---

### Task 1: The mechanical completion check

**Files:**
- Create: `plugins/superb/skills/craft/check-brief.py`
- Create: `plugins/superb/skills/craft/check-brief.sh`
- Create: `plugins/superb/skills/craft/tests/test_check_brief.py`

**Interfaces:**
- Produces: `check-brief.py <project-dir>` exiting `0` when every predicate passes, `1` when one fails, `2` when `CRAFT.md` is absent or unreadable. Prints one `PASS`/`FAIL` line per predicate with a reason.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

```python
# plugins/superb/skills/craft/tests/test_check_brief.py
import subprocess, sys, textwrap, unittest, pathlib, tempfile, os

CHECK = pathlib.Path(__file__).resolve().parent.parent / "check-brief.py"

def run(brief, rounds=None):
    d = tempfile.mkdtemp()
    pathlib.Path(d, "CRAFT.md").write_text(textwrap.dedent(brief))
    if rounds:
        os.makedirs(pathlib.Path(d, ".craft"), exist_ok=True)
        for name, body in rounds.items():
            pathlib.Path(d, ".craft", name).write_text(body)
    p = subprocess.run([sys.executable, str(CHECK), d], capture_output=True, text=True)
    return p.returncode, p.stdout

COMPLETE = """
    # CRAFT.md
    ## Confirmed Decisions
    | ID | Decision | Source |
    | -- | -------- | ------ |
    | DEC-001 | Postgres | User answer |
    ## Core Features
    - Upload a file: a signed-in user uploads a PDF and sees it listed.
    ## Domain Behaviour
    - Document: has an owner; a document may not be shared outside its team.
    ## User Types
    - Editor: appears in the upload journey; may create and delete own documents.
    ## Explicit Non-Goals
    - No mobile app.
    ## Technical Direction
    - Database: Postgres.
    - Frontend: No preference — planning skill may decide.
    ## Open Questions
    _(none)_
    ## Assumptions
    _(none)_
    ## Contradictions
    _(none)_
    """

class StructureTests(unittest.TestCase):
    def test_complete_brief_passes(self):
        rc, out = run(COMPLETE)
        self.assertEqual(rc, 0, out)

    def test_missing_brief_is_exit_2(self):
        d = tempfile.mkdtemp()
        p = subprocess.run([sys.executable, str(CHECK), d], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_tbd_fails_structure(self):
        rc, out = run(COMPLETE.replace("- No mobile app.", "- TBD"))
        self.assertEqual(rc, 1)
        self.assertIn("vagueness", out)

    def test_open_required_question_fails(self):
        rc, out = run(COMPLETE.replace("## Open Questions\n_(none)_",
                                       "## Open Questions\n- [REQUIRED] Which auth provider?"))
        self.assertEqual(rc, 1)
        self.assertIn("open", out.lower())

    def test_unresolved_contradiction_fails(self):
        rc, out = run(COMPLETE.replace("## Contradictions\n_(none)_",
                                       "## Contradictions\n- CON-001 unresolved: offline vs realtime"))
        self.assertEqual(rc, 1)
        self.assertIn("CON-001", out)

    def test_high_impact_unconfirmed_assumption_fails(self):
        rc, out = run(COMPLETE.replace("## Assumptions\n_(none)_",
                                       "## Assumptions\n- ASM-001 Impact: High Status: Unconfirmed"))
        self.assertEqual(rc, 1)

    def test_feature_without_acceptance_sentence_fails(self):
        rc, out = run(COMPLETE.replace(
            "- Upload a file: a signed-in user uploads a PDF and sees it listed.",
            "- Upload a file"))
        self.assertEqual(rc, 1)
        self.assertIn("acceptance", out.lower())

    def test_required_decision_sourced_from_recommendation_fails(self):
        rc, out = run(COMPLETE.replace("| DEC-001 | Postgres | User answer |",
                                       "| DEC-001 | Postgres | Accepted recommendation |"))
        self.assertEqual(rc, 1)
        self.assertIn("DEC-001", out)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/craft/tests -v`
Expected: FAIL — every test errors because `check-brief.py` does not exist yet.

- [ ] **Step 3: Write `check-brief.py`**

Standard library only. Skeleton — fill each predicate to satisfy the tests above:

```python
#!/usr/bin/env python3
"""Mechanical completion check for a CRAFT.md.

Turns craft's completion criteria into something that gives the same answer
twice. Exit 0 = every predicate passed, 1 = one failed, 2 = no readable brief.
"""
import json, pathlib, re, sys

VAGUE = re.compile(r"\b(TBD|TODO|etc\.|as appropriate)\b", re.I)
NA    = re.compile(r"^Not applicable — .+", re.M)
REQUIRED_HEADINGS = ["Confirmed Decisions", "Core Features", "Domain Behaviour",
                     "User Types", "Explicit Non-Goals", "Technical Direction",
                     "Open Questions", "Assumptions", "Contradictions"]
FAILURES = []

def ok(p):        print(f"PASS {p}")
def fail(p, why): print(f"FAIL {p} — {why}"); FAILURES.append(p)
def skip(p, why): print(f"SKIP {p} — {why}")

def sections(text):
    """Map heading -> body, splitting on '## '."""
    out, cur = {}, None
    for line in text.split("\n"):
        m = re.match(r"^##\s+(.*)$", line)
        if m: cur = m.group(1).strip(); out[cur] = []
        elif cur: out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}

def bullets(body):
    return [l.strip()[2:].strip() for l in body.split("\n") if l.strip().startswith("- ")]

def predicate_structure(sec):
    for h in REQUIRED_HEADINGS:
        if h not in sec:                      return fail("structure", f"missing heading: {h}")
        if not sec[h]:                        return fail("structure", f"empty heading: {h}")
        if VAGUE.search(sec[h]) and not NA.search(sec[h]):
            return fail("structure", f"vagueness under {h}")
    ok("structure")

def predicate_nothing_open(sec):
    for line in sec.get("Open Questions", "").split("\n"):
        if "[REQUIRED]" in line or "[IMPORTANT]" in line:
            return fail("nothing-open", f"still open: {line.strip()[:60]}")
    for line in sec.get("Contradictions", "").split("\n"):
        if "CON-" in line and "unresolved" in line.lower():
            return fail("nothing-open", line.strip()[:60])
    for line in sec.get("Assumptions", "").split("\n"):
        if "Impact: High" in line and "Status: Unconfirmed" in line:
            return fail("nothing-open", f"high-impact unconfirmed: {line.strip()[:60]}")
    ok("nothing-open")

def predicate_traceability(sec, craft_dir, text):
    rounds = sorted(craft_dir.glob("round-*.questions.json")) if craft_dir.is_dir() else []
    if not rounds: return skip("traceability", "no round files; hand-written brief")
    for rf in rounds:
        try: obj = json.loads(rf.read_text())
        except Exception as e: return fail("traceability", f"{rf.name}: {e}")
        for q in obj.get("questions", []):
            if q.get("importance") not in ("required", "important"): continue
            qid = str(q.get("id"))
            hits = text.count(qid)
            if hits == 0:   return fail("traceability", f"{qid} resolves to nothing")
            if hits > 1:    return fail("traceability", f"{qid} appears {hits} times")
    for row in sec.get("Confirmed Decisions", "").split("\n"):
        cells = [c.strip() for c in row.split("|") if c.strip()]
        if len(cells) >= 3 and cells[0].startswith("DEC-") and cells[2] != "User answer":
            return fail("traceability", f"{cells[0]} sourced from {cells[2]!r}, not a user answer")
    ok("traceability")

def predicate_concreteness(sec):
    for b in bullets(sec.get("Core Features", "")):
        if ":" not in b or len(b.split(":", 1)[1].split()) < 5:
            return fail("concreteness", f"no acceptance sentence: {b[:50]}")
    for b in bullets(sec.get("Domain Behaviour", "")):
        if ";" not in b:
            return fail("concreteness", f"no rule beyond fields: {b[:50]}")
    if not bullets(sec.get("Explicit Non-Goals", "")):
        return fail("concreteness", "Explicit Non-Goals is empty")
    for line in sec.get("Technical Direction", "").split("\n"):
        if line.strip().startswith("- ") and ":" not in line:
            return fail("concreteness", f"axis neither chosen nor deferred: {line.strip()[:50]}")
    ok("concreteness")

def main(argv):
    root = pathlib.Path(argv[1] if len(argv) > 1 else ".")
    brief = root / "CRAFT.md"
    try: text = brief.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"FAIL brief — cannot read {brief}: {e}"); print("check-brief: FAIL"); return 2
    sec = sections(text)
    predicate_structure(sec)
    predicate_nothing_open(sec)
    predicate_traceability(sec, root / ".craft", text)
    predicate_concreteness(sec)
    print()
    print("check-brief: FAIL" if FAILURES else "check-brief: PASS")
    return 1 if FAILURES else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- **Structure:** every heading in `REQUIRED_HEADINGS` present and non-empty; reject a line matching `\b(TBD|TODO|etc\.|as appropriate)\b` unless the heading body is exactly `Not applicable — <reason>`.
- **Nothing open:** under `## Open Questions`, zero lines tagged `[REQUIRED]` or `[IMPORTANT]`; under `## Contradictions`, zero lines containing `CON-` and `unresolved`; under `## Assumptions`, zero lines with both `Impact: High` and `Status: Unconfirmed`.
- **Traceability:** for each `.craft/round-*.questions.json` present, every question whose `importance` is `required` or `important` must appear exactly once as a `DEC-` or `DELEGATED-` id in the brief, never both. Skip this predicate with a `SKIP` line when no round files exist, so the check still works on a hand-written brief.
- **Concreteness:** every `## Core Features` bullet contains `:` followed by ≥ 5 words (the actor-and-outcome sentence); every `## Domain Behaviour` bullet contains `;` (at least one rule beyond its fields); every `## User Types` entry name appears somewhere under a journey or permission line; `## Explicit Non-Goals` non-empty; every `## Technical Direction` line either names a value or is exactly `No preference — planning skill may decide.`
- Every `Source` cell for a decision answering a `required` question must be `User answer`.

Print `PASS <predicate>` or `FAIL <predicate> — <reason>` per predicate, then a final `check-brief: PASS|FAIL`. Exit `0`, `1`, or `2` as the interface says.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/craft/tests -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Add the shell wrapper and make both executable**

```bash
printf '#!/usr/bin/env bash\n# Mechanical completion check for a CRAFT.md. See check-brief.py.\nexec python3 "$(dirname "$0")/check-brief.py" "$@"\n' > plugins/superb/skills/craft/check-brief.sh
chmod +x plugins/superb/skills/craft/check-brief.sh plugins/superb/skills/craft/check-brief.py
./tools/check-plugin.sh
```

Expected: `check-plugin: PASS` (the gate requires shipped `.sh` files to be executable).

- [ ] **Step 6: Commit**

```bash
git add plugins/superb/skills/craft/check-brief.py plugins/superb/skills/craft/check-brief.sh plugins/superb/skills/craft/tests/
git commit -m "feat(craft): make the completion criteria an executable check"
```

---

### Task 2: The wait loop stops depending on the harness

**Files:**
- Modify: `plugins/superb/skills/craft/SKILL.md:224-231` (`## The loop`)

**Interfaces:**
- Consumes: nothing.
- Produces: the loop instruction Task 6's `VISION CLEAR` gate refers to.

- [ ] **Step 1: Replace the step-2 instruction**

Replace lines 224-231's step 2 and 3 with:

````markdown
2. Run `python3 "$SKILL/ui/craftui.py" wait --project-dir . --round NNN --timeout 600`
   **and wait for it inside this turn.** Do not end your turn on it, and do not
   background it with `&`.

   **Why this wording is exact.** `wait` is an ordinary blocking process. Whether
   ending your turn works at all is a property of the harness you are running on,
   which this skill cannot see: where a finished background task starts a new turn
   you would be woken, and where completion only lands in a mailbox nothing drains,
   the session parks until the user types something. That is the reported failure —
   "I had to go to the CLI and say *already replied, next wave*." Waiting in your
   own turn behaves the same on both.

   **Waiting is executing, not stopping.** A wait is a tool call; your turn has not
   ended and no question is owed.

   The 600-second bound is not a timeout you are avoiding — it is a heartbeat. The
   user's terminal input is theirs and stays theirs, so surface every ten minutes,
   read anything they typed, fold it in like any other answer, and re-arm.
3. Act on the one line it prints. Fold the answers into `CRAFT.md`, then write
   the next round **in the same turn**. The questionnaire gets **smaller** every
   pass, exactly as *Second pass* says.
````

- [ ] **Step 2: Add the termination conditions immediately after**

````markdown
### When the loop ends

Four conditions, and nothing else:

| Condition | Signal | What you do |
| --------- | ------ | ----------- |
| The user pressed Finish | exit `0` `FINISHED` | Final fold, run the merits test in *Ending*, `stop`. |
| Converged | zero open REQUIRED and zero IMPORTANT | Write the closing round — empty `questions`, a real `note` — then `stop`. |
| Unrecoverable | exit `1` `ERROR`, or `64` | **Never re-arm.** Fix it, or fall back to file mode. |
| No progress | two consecutive rounds yielding no new confirmed or delegated decision | Stop and say so. A third ask is arguing with someone who has decided not to answer. |

`TIMEOUT` (exit `2`) is none of these. It is the heartbeat: re-arm in the same turn.

Exit `3` `NOSERVER` splits. If the user is plainly present — they just typed —
re-`serve` and re-arm. If this round already timed out once, the four-hour idle
shutdown has fired: stop, and tell them how to restart.

**A hard cap of 12 rounds exists as a bug detector, not a budget.** Reaching it
means the shrink rule is not working; say so rather than starting round 13.
````

- [ ] **Step 3: Verify no contradiction remains**

Run: `grep -n "background command\|end your turn" plugins/superb/skills/craft/SKILL.md`
Expected: no output. Any hit is the old instruction surviving somewhere else.

- [ ] **Step 4: Commit**

```bash
git add plugins/superb/skills/craft/SKILL.md
git commit -m "fix(craft): wait inside the turn so the round loop cannot park"
```

---

### Task 3: Technical questions branch on project shape

**Files:**
- Modify: `plugins/superb/skills/craft/SKILL.md:852-872` (`## Preferred technologies`)

**Interfaces:**
- Consumes: the `## Platform` answer (SKILL.md:838-850).
- Produces: the layer classification Task 4's agent is briefed against.

- [ ] **Step 1: Replace the flat list with a layered drill-down**

The current section is eight nouns with no worked example and no branch on
`## Platform`. Give it the depth `## Domain behaviour` already has. Replace
lines 852-872 with:

````markdown
## Preferred technologies

**Classify before you ask.** The `## Platform` answer determines which layers
exist, and a layer that does not exist must not be asked about:

| Platform answer | Layers present |
| --------------- | -------------- |
| web | frontend, backend, data, hosting |
| API only | backend, data, hosting |
| CLI | runtime, packaging, distribution |
| mobile | client, backend, data, hosting |
| desktop | client, local storage, packaging |
| browser extension | client, permissions, store distribution |

**If the shape is not yet known, that is the first question**, and it is
REQUIRED: is this a frontend, a backend, or a full-stack build? Everything below
depends on the answer, so ask it before the rest of this section.

**Then drill each present layer.** One decision per question — never "what's
your stack?".

*Worked example, a full-stack web app:*

- **Frontend** — framework; rendering (SPA / SSR / static); styling; component
  library; state management if the framework does not settle it.
- **Backend** — language; framework; API style (REST / GraphQL / RPC);
  background jobs if any feature implies them.
- **Data** — database engine; relational or document; migrations; caching if a
  feature implies it.
- **Auth** — provider or self-hosted; session or token; social logins.
- **Hosting** — platform; containerised or not; CI.
- **Cross-cutting** — package manager; language version floor; test framework.

Ask only about layers the platform answer put in play, and only where the answer
would change what gets built.

If I do not care about an axis, record it exactly:

`No preference — planning skill may decide.`

That is a real answer, not a gap. Do not force technical decisions I deliberately
want another skill to make — but do not leave an axis unrecorded either, because
silence and "no preference" are different states downstream.
````

- [ ] **Step 2: Verify the section grew and still ends cleanly**

Run: `sed -n '/^## Preferred technologies/,/^---$/p' plugins/superb/skills/craft/SKILL.md | tail -5`
Expected: ends with the "no preference" paragraph then `---`.

- [ ] **Step 3: Commit**

```bash
git add plugins/superb/skills/craft/SKILL.md
git commit -m "feat(craft): technical questions branch on the platform answer"
```

---

### Task 4: The architecture-discovery agent

**Files:**
- Create: `plugins/superb/agents/architecture-discovery.md`
- Modify: `plugins/superb/skills/craft/SKILL.md` — insert a dispatch step before round 1

**Interfaces:**
- Consumes: Task 3's layer table.
- Produces: `superb:architecture-discovery`, returning a JSON array of schema-shaped question objects.

- [ ] **Step 1: Write the agent**

Frontmatter `name: architecture-discovery`, `description:` stating when it is used, `model: sonnet`, `color: cyan`. No `memory:` key (0 of 33 shipped plugin agents use one) and no colour outside the documented set.

Body must state:
- It receives the idea, the product category, the repo-inspection result, and craft's technical category list.
- It returns **only** a JSON array of question objects: `id`, `importance`, `title`, `type`, `options`, `why`. Nothing else — no prose, no chosen stack, no architecture.
- **Options are named alternatives, never conclusions.** `["Postgres", "MySQL", "SQLite"]` is a question; `["Postgres, because it fits the relational model"]` is a decision wearing a question's clothes.
- The objectivity test it must apply to its own output: blank the `title` and keep only the `options` — if a reader can still infer what is being decided, the options are concrete. Adjective-only options (`modern`, `scalable`, `robust`) fail and must be rewritten.
- It never asks about implementation trivia craft's scope fence excludes.

- [ ] **Step 2: Wire the dispatch into SKILL.md**

Insert before the first round, stating: dispatch `superb:architecture-discovery` **once per session**, after the idea is stated and before round 1, and **only** when the project is software whose stack is unstated. Always name it with the `superb:` prefix. If it is unavailable, generate the technical questions inline against Task 3's layer table — its absence must not block a round.

- [ ] **Step 3: Verify the gate accepts the new agent**

Run: `./tools/check-plugin.sh`
Expected: `check-plugin: PASS`, including `architecture-discovery: frontmatter valid`.

- [ ] **Step 4: Commit**

```bash
git add plugins/superb/agents/architecture-discovery.md plugins/superb/skills/craft/SKILL.md
git commit -m "feat(craft): bundled architecture-discovery agent for technical questions"
```

---

### Task 5: Objectivity and the cost of delegation

**Files:**
- Modify: `plugins/superb/skills/craft/SKILL.md` — the question-authoring rules and the delegation section

**Interfaces:**
- Consumes: nothing.
- Produces: the rules Task 7's reviewer checks against.

- [ ] **Step 1: Add the objectivity rule to question authoring**

````markdown
### Every question must be objective

**The test:** blank the `title` and keep only the `options`. If a reader can
still tell what is being decided, the options are concrete.

| Fails | Passes |
| ----- | ------ |
| `["modern", "traditional"]` | `["React", "Vue", "Svelte", "no framework"]` |
| `["scalable", "simple"]` | `["Postgres", "SQLite", "DynamoDB"]` |
| `["good UX", "fast"]` | `["one page per step", "one long form", "a wizard modal"]` |

Adjectives are not options. They describe how someone feels about a choice
rather than naming the choice, and an answer to them cannot be written down as
a decision.
````

- [ ] **Step 2: Add the delegation rules**

````markdown
### A delegated decision still has to be written down

"You decide" closes the question, not the decision. A bare delegation loses the
reasoning permanently — nobody downstream can tell what was considered.

Every delegated entry carries four things: the options that were on the table,
craft's recommendation as the default, the constraints the choice must respect,
and what goes wrong if it is chosen badly.

**`delegable` defaults to `false` on a REQUIRED question.** A delegated REQUIRED
is not a delegation, it is a scope reduction — if it can be delegated it was not
required, so either lower its importance or record it in Confirmed Decisions.
````

- [ ] **Step 3: Verify both sections are present**

Run: `grep -c "blank the \`title\`\|delegable\` defaults to \`false\`" plugins/superb/skills/craft/SKILL.md`
Expected: `2`

- [ ] **Step 4: Commit**

```bash
git add plugins/superb/skills/craft/SKILL.md
git commit -m "feat(craft): objectivity test for questions, and delegation must carry its cost"
```

---

### Task 6: `VISION CLEAR` requires two independent passes

**Files:**
- Modify: `plugins/superb/skills/craft/SKILL.md:333-345` (`## Ending`) and `:1333+` (`# Completion criteria`)

**Interfaces:**
- Consumes: Task 1's `check-brief.sh`.
- Produces: the gate Task 7 verifies.

- [ ] **Step 1: Replace the self-assessed ending**

````markdown
## Ending

`CRAFT STATUS: VISION CLEAR` is **earned, not judged.** Two independent passes,
both required:

**1. The mechanical check.** Run `./check-brief.sh <project-dir>` from this
skill's directory. Exit `0` is the only pass. Report its output rather than your
impression of it — the point of a script is that it gives the same answer twice.

**2. A fresh-context reviewer.** Dispatch an agent, hand it `CRAFT.md` **and
nothing else**, and ask what it still could not build from. Craft's own criterion
is that the brief be understandable by another LLM *without access to the
original conversation* — which only an agent that lacks the transcript can test.
You have the transcript, so you fail that precondition by construction and cannot
be the judge.

Its remaining questions become round N+1. They are not footnotes on a finished
brief.

If either pass fails, the status is `CRAFT STATUS: MORE CLARIFICATION NEEDED`,
and you say which pass failed and why.
````

- [ ] **Step 2: Point the completion criteria at the check**

Under `# Completion criteria`, after the existing bullet list, add: the list is
what the brief must *contain*; `check-brief.sh` is how that is *verified*. Note
explicitly that a brief scoring `count_answered` as fully settled may still fail
the check, because that counter folds `delegated` into settled — fifteen "you
decide" clicks report a converged round and an incomplete brief.

- [ ] **Step 3: Verify**

Run: `grep -n "earned, not judged\|fresh-context reviewer" plugins/superb/skills/craft/SKILL.md`
Expected: both present.

- [ ] **Step 4: Commit**

```bash
git add plugins/superb/skills/craft/SKILL.md
git commit -m "feat(craft): VISION CLEAR earned by a script and a fresh reader"
```

---

### Task 7: Register everything and bump

**Files:**
- Modify: `plugins/superb/skills/craft/README.md`, `README.md`, `plugins/superb/README.md`, both `plugin.json`, `.claude-plugin/marketplace.json`, `tools/check-plugin-mutants.sh`

- [ ] **Step 1: Document the new behaviour in the craft READMEs**

Both craft's own README and the root README's craft section gain: the layered technical questions, the bundled agent, the in-turn wait, and the two-pass ending.

- [ ] **Step 2: Bump both manifests to `0.8.0`**

- [ ] **Step 3: Add a mutant proving the new check is guarded**

```bash
run_mutant "craft check-brief loses +x"  "chmod -x plugins/superb/skills/craft/check-brief.sh"
```

- [ ] **Step 4: Run every gate**

```bash
./tools/check-plugin.sh
./tools/check-plugin-mutants.sh
./tools/test-craftui.sh
python3 -m unittest discover -s plugins/superb/skills/craft/tests
claude plugin validate .
```

Expected: all pass; mutants `killed=35 survived=0`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs(superb): register craft's new depth, agent and completion gate (0.8.0)"
```
