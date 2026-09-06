# Pipeline Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply ten audited fixes to the `superb:pipeline` skill — two portability/functional bugs, one inert frontmatter field, and six review-loop contract changes — while keeping `./tools/check-plugin.sh` and `./tools/check-plugin-mutants.sh` green.

**Architecture:** The skill is prose plus three (soon four) templates; the enforcement surface is `tools/check-plugin.py`, a structural gate whose own falsifiability is proved by `tools/check-plugin-mutants.sh`. So every fix that *can* be mechanised gets a gate arm plus a mutant proving that arm can fail; fixes that are purely contractual prose get cross-file consistency sweeps instead. Wherever a gate arm exists, the task order is: add the arm first and watch the gate go RED against the un-fixed repo, then fix, then GREEN.

**Tech Stack:** Markdown (skill docs), Python 3 (`tools/check-plugin.py`, no third-party deps — PyYAML is deliberately not assumed), Bash (`tools/check-plugin-mutants.sh`), git.

**Spec:** the audit published at `https://claude.ai/code/artifact/c0dcf0c4-cbe3-4884-b96a-1c91905ce251` (findings P-01, P-02, P-03, P-06, L-01, L-02, L-04, L-05, L-06, L-07), with the measured evidence brief at `/tmp/claude-1000/-home-wp3-IntellijProjects-mdinteractive/267eecac-9b93-4f2d-a409-e74c4a89d8ec/scratchpad/rv-cost-evidence.md`.

## Global Constraints

- **Branch:** cut a new branch from `origin/main` (currently `b542720`). Do **not** build on `fix/check-brief-real-briefs` — mixing unrelated work in one branch is the drift this audit's R-01 finding was about.
- **The project's quality gates are the four in `.github/workflows/checks.yml`**, and CI is the authority on that list:

  ```bash
  ./tools/check-plugin.sh                                                     # structural gate
  ./tools/check-plugin-mutants.sh                                             # proves the gate can fail
  python3 -m unittest discover -s plugins/superb/skills/craft/tests -v        # craft check-brief
  ./tools/test-craftui.sh                                                     # craft UI suite
  ```

  Every task runs the **first two** (they are the gates this change moves) and reports their output. Task 10 runs all four. `pytest` is **not installed** on this machine — `unittest` discovery is the working invocation. `test-craftui.sh` skips its browser tests where no browser can render, which is expected locally.
- **Baseline to hold at every commit:** `check-plugin: PASS`, and `check-plugin-mutants.sh` reporting `survived=0` with `killed` at **40 or more** (40 is the count at `b542720`; tasks that add mutants raise it and none may lower it).
- **Scratch is namespaced to this run.** `.superpowers/sdd/` is shared across runs and already holds the **craft-ui** run's ledger and a `task-10-brief.md` — and this plan has a Task 10. So: this run's ledger is `.superpowers/sdd/pipeline-audit-progress.md`, and its briefs, reports and review packages are prefixed `pipeline-audit-`. Never read, write or overwrite an unprefixed file there; `progress.md` in that directory belongs to another run and its "Tasks 1–13 complete" refers to a different plan.
- **Never push.** Local commits only.
- **Never `git add` this plan** or anything else under `docs/superpowers/`.
- **The mutants harness seds on literal strings inside the skill's worked examples.** Any edit to an example that a mutant targets turns that mutant into a no-op, which the harness reports as SURVIVED and fails on. Mutant and example are edited in the same commit, always.
- **No third-party Python imports.** `check-plugin.py` uses only `json, pathlib, re, sys`.
- `tools/check-plugin.sh` already forwards `"$@"` to the Python — no wrapper change is needed for new arguments.
- **Scope boundary:** P-04 (consolidating the three overlapping rule lists), L-03 (re-anchoring the MIPS-7319 phase 6/7 plans, a different repo) and L-08 (widening the Stage 5 hand-off) are explicitly **out** of this plan.
- **P-06 IS WITHDRAWN — the finding was wrong.** `argument-hint` is a documented, honoured field in a plugin `SKILL.md`: it is in the official frontmatter reference (`code.claude.com/docs/en/skills.md`), which states that plugin skills support every field in that table, and it renders the hint in the `/` autocomplete picker. The audit had it backwards — custom commands were merged *into* skills, so `argument-hint` is a skill field that commands inherit, not a command field skills borrow. **Do not remove it from any skill.** (It is a Claude-Code-only extension, absent from the Agent Skills spec, so a skill carrying it cannot be pushed to claude.ai / the Skills API / Cowork. That is the trade-off this plugin already accepts by being a Claude Code plugin, and it is why the official `superpowers` skills use only `name` + `description`. It is not a defect.)
- **P-02's stated cause was also wrong, though its fix is right.** `$0` **is** substituted: it is the first positional argument, 0-based, and needs no `arguments:` frontmatter key (verified empirically against Claude Code 2.1.261 with a real `--plugin-dir` plugin, and documented under *Available string substitutions*). So the original `Dispatch on the argument (`$0`)` table **did** route `resume` and `status` correctly. The real defect is narrower: **an indexed placeholder with no argument at its position stays literal**, so a bare `/superb:pipeline` rendered a stray `$0` into the prompt in exactly the arm the table calls "no argument". `$ARGUMENTS` collapses to the empty string there, which is why it is the correct token for a dispatch table. Any prose or commit message claiming `$0` is never substituted is false and must not ship.

---

## File Structure

| File | Responsibility | Tasks |
| --- | --- | --- |
| `plugins/superb/skills/pipeline/SKILL.md` | The skill's contract: invocation, laws, stages, fan-out, red flags | 2, 3, 4, 5, 6, 7, 8 |
| `plugins/superb/skills/pipeline/references/fix-loop.md` | Stage 4 loop, guard rails, closure ledger, re-review math | 3, 4, 5 |
| `plugins/superb/skills/pipeline/references/run-state.md` | File formats, task-line grammar, resume, dispatch contract | 6, 7, 8 |
| `plugins/superb/skills/pipeline/references/parallel.md` | Waves, lanes, build gates, Brain-Agent mode | 1, 6 |
| `plugins/superb/skills/pipeline/README.md` | Human-facing summary; carries the invocation table and the fan-out math | 2, 5 |
| `plugins/superb/skills/pipeline/templates/findings.md` | Ledger template: severity table, counters, iteration log | 3, 4 |
| `plugins/superb/skills/pipeline/templates/kit.md` | **NEW** — run-level verification kit | 7 |
| `tools/check-plugin.py` | Structural gate; grows a leakage arm, a `$0` arm, a tier arm and a `--run` mode | 1, 2, 3, 9 |
| `tools/check-plugin-mutants.sh` | Proves each gate arm can fail; must track every edited example | 1, 2, 3, 5, 9 |

**Sequencing note.** Tasks 2, 3, 4, 6, 7 and 8 all modify `SKILL.md`, and 1, 2, 3, 5 and 9 all modify `check-plugin-mutants.sh`. File sets are therefore *not* disjoint and these tasks run **sequentially**, each on the previous one's head. Do not parallelise them.

---

### Task 1: Generic build gates, and a leakage arm that catches foreign project paths

**Files:**
- Modify: `plugins/superb/skills/pipeline/references/parallel.md` (the build-gate step under *Executing a wave*)
- Modify: `tools/check-plugin.py` (the `== no personal leakage ==` regex)
- Modify: `tools/check-plugin-mutants.sh` (add one mutant)

**Interfaces:**
- Consumes: nothing.
- Produces: a leakage regex that later tasks must not regress, whose scope
  (`plugins/` only) is load-bearing — the gate's own source and mutants contain the
  banned tokens, so widening the scan turns the gate red on itself.
- Produces: the *semantics* "the gates come from the repo, not from this skill" —
  in `parallel.md`'s own words, **`the gates the approved plan names`**. Task 6 and
  Task 7 refer to that idea; neither is held to a verbatim quote of it. (An earlier
  draft of this block invented a different phrasing than the Step 3 text it itself
  prescribes, which would have failed Task 6 for no real reason.)

- [ ] **Step 1: Add the failing gate arm first**

In `tools/check-plugin.py`, extend the leakage pattern. Current line:

```python
pat = re.compile(r"/home/[a-z0-9_-]+/|audio-chat-app|agent-memory|MIPS-[0-9X]|HIPAA", re.I)
```

Replace with:

```python
# Foreign project conventions leak the same way absolute home paths do: a build
# command or source tree from whichever repo the skill was last used in, frozen
# into prose that reads as universal. tools/build.sh and extension/src/ arrived
# that way and shipped in three releases.
pat = re.compile(
    r"/home/[a-z0-9_-]+/|audio-chat-app|agent-memory|MIPS-[0-9X]|HIPAA"
    r"|tools/build|extension/src",
    re.I,
)
```

- [ ] **Step 2: Run the gate and watch it go RED on the real leak**

```bash
./tools/check-plugin.sh
```

Expected: `check-plugin: FAIL` with `personal paths or foreign conventions` naming **four** lines in `references/parallel.md`, not two — the build-gate step *and* the *Annotation grammar* worked `Files:` example, which uses the same foreign source tree (`extension/src/core/chunk_store.{h,cpp}`). This is the audit's P-01 finding, now mechanised, and it is wider than the audit judged: the audit called the `chunk_store` paths "fine, they're marked as examples", but the arm cannot distinguish an example from an instruction, and an example is what a reader copies.

**So Step 3 alone does not reach green.** Both sites must change in this task.

- [ ] **Step 3: Fix both leaks in `parallel.md`**

**3a — the annotation example.** Under *Annotation grammar*, the worked `Files:`
block names `extension/src/core/chunk_store.h`, `extension/src/core/chunk_store.cpp`
and `extension/tests/core/chunk_store_test.cpp`. Drop the foreign `extension/`
prefix so they read `src/core/…` and `tests/core/…`. Keep the example's shape —
a Modify/Modify/Test triple over one component — since that shape is what the
section teaches. Do the third line too even though the regex does not match it:
one prefixed path left beside two un-prefixed ones reads as a typo.

**3b — the build-gate step.** In *Executing a wave*, step 7 currently reads:

```markdown
7. Run the project's build gates on `P` after the last merge (this repo:
   `tools/build.sh`, plus `tools/build-physics.sh linux` when
   `extension/src/physics/` changed). A failure is a bug finding with an F-ID
   and goes through the fix loop before the next wave.
```

Replace with:

```markdown
7. Run **the project's build gates** on `P` after the last merge — the gates the
   approved plan names, or the ones the repo's own `AGENTS.md` / `CLAUDE.md`
   declares. This skill does not know what they are and must not guess: a gate
   invented here fails a repo that never had it, and a gate omitted here lets a
   broken wave merge. If the plan named none, that is an Ambiguity-guard stop,
   not a licence to skip the step. A failure is a bug finding with an F-ID and
   goes through the fix loop before the next wave.
```

- [ ] **Step 4: Run the gate to verify GREEN**

```bash
./tools/check-plugin.sh
```

Expected: `ok    no absolute home paths, private project names, or foreign ticket prefixes` and `check-plugin: PASS`.

- [ ] **Step 5: Add a mutant proving the new arm can fail**

In `tools/check-plugin-mutants.sh`, after the existing `"personal path hidden in a .py file"` mutant, add:

```bash
run_mutant "foreign build command reintroduced"   "echo 'run tools/build.sh after the merge' >> plugins/superb/skills/pipeline/references/parallel.md"
run_mutant "foreign source tree reintroduced"     "echo 'when extension/src/physics/ changed' >> plugins/superb/skills/pipeline/references/parallel.md"
```

- [ ] **Step 6: Run the mutants harness**

```bash
./tools/check-plugin-mutants.sh
```

Expected: both new mutants report `killed`, `survived=0`, `check-plugin-mutants: PASS`.

- [ ] **Step 7: Commit**

```bash
git add plugins/superb/skills/pipeline/references/parallel.md tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "fix(pipeline): build gates come from the repo, not from whichever repo came last"
```

---

### Task 2: Correct the argument dispatch and the command's own name

> **⚠️ THIS TASK'S RECIPE BELOW IS PARTLY SUPERSEDED — read the P-02 and P-06
> entries in *Global Constraints* first.** The steps as written rest on two claims
> since disproved empirically against Claude Code 2.1.261: that `$0` is never
> substituted (it is the first positional argument, 0-based), and that
> `argument-hint` is inert on skills (it is documented, honoured, and must stay in
> all five skills). The `$ARGUMENTS` dispatch change and the `/superb:pipeline`
> namespacing are correct and were kept; the `argument-hint` removal, its gate arm
> and its mutant were reverted. What actually shipped is `f0b8a24`. Do not
> re-derive this task from the steps below without applying both corrections.

**Files:**
- Modify: `plugins/superb/skills/pipeline/SKILL.md` (frontmatter; the Invocation table)
- Modify: `plugins/superb/skills/pipeline/README.md` (the invocation table)
- Modify: `plugins/superb/skills/pipeline/references/run-state.md` (the Resume Protocol heading)
- Modify: `tools/check-plugin.py` (new `== skill invocation ==` section)
- Modify: `tools/check-plugin-mutants.sh` (add two mutants)

**Interfaces:**
- Consumes: nothing.
- Produces: the namespaced form `/superb:pipeline` that Tasks 5 and 7 use in prose.

- [ ] **Step 1: Add the failing gate arm first**

In `tools/check-plugin.py`, insert a new section immediately before `print("== agents ==")`:

```python
print("== skill invocation ==")
# $0 is never substituted by the harness — $ARGUMENTS and $1..$9 are. A skill
# whose dispatch table matches $0 reads a literal token, so every argument routes
# to the fallback arm. Caught only by reading the table, never by running it.
#
# The check targets the DISPATCH INSTRUCTION, not any mention of $0: the corrected
# text has to stay free to explain why $0 is wrong, and a blanket ban on the
# characters would fail on the sentence documenting the fix.
_inv_before = len(FAIL)
skill_names = sorted(d.name for d in sdir.iterdir() if d.is_dir()) if sdir.is_dir() else []
_ns = re.compile(r"(?<![\w:/])/(" + "|".join(map(re.escape, skill_names)) + r")(?![\w-])") \
      if skill_names else None
for n in skill_names:
    t, e = read(sdir / n / "SKILL.md")
    if e: continue
    flat = " ".join(t.split())
    if re.search(r"[Dd]ispatch on [^.]{0,40}\$0", flat):
        bad(f"{n}/SKILL.md dispatches on $0, which is never substituted")
    head = t.split("---")[1] if t.count("---") >= 2 else ""
    if re.search(r"^argument-hint:", head, re.M):
        bad(f"{n}/SKILL.md has argument-hint in frontmatter (a command field, inert on skills)")
    for m in (_ns.finditer(t) if _ns else []):
        bad(f"{n}/SKILL.md writes {m.group(0)!r} un-namespaced; use /superb:{m.group(1)}")
if len(FAIL) == _inv_before:
    ok("no $0 dispatch, no inert argument-hint, invocations namespaced")
```

Two details that matter and are easy to get wrong:

- The section-local `_inv_before` guard, not `if not FAIL:`. `FAIL` is global, so a
  bare `not FAIL` reports this section's success or failure based on whether an
  *earlier* section failed. (The pre-existing `ci wiring` section has that shape;
  do not copy it.)
- `sdir` is defined by the `== skills ==` section above, so this block must sit
  after it — hence "immediately before `print("== agents ==")`".

- [ ] **Step 2: Run the gate and watch it go RED**

```bash
./tools/check-plugin.sh
```

Expected `FAIL` lines: `pipeline/SKILL.md dispatches on $0`, `pipeline/SKILL.md has argument-hint in frontmatter`, and four `writes '/pipeline' un-namespaced` lines.

- [ ] **Step 3: Fix the frontmatter (P-06)**

Delete line 4 of `SKILL.md` entirely:

```yaml
argument-hint: "[resume|status]"
```

The frontmatter becomes `---` / `name:` / `description:` / `---`.

- [ ] **Step 4: Fix the dispatch line and the table (P-02)**

`SKILL.md`, the Invocation section. Replace:

```markdown
Dispatch on the argument (`$0`) before doing anything else:

| Invocation | Behavior |
|------------|----------|
| `/pipeline` (no argument) | **Full mode** — current behavior: start at Stage 1, step 0. |
| `/pipeline resume` | Run the **Resume Protocol** in `references/run-state.md`. **Never start a new run in this mode** — if no run directory exists, say so and stop. |
| `/pipeline status` | **Strictly read-only report** (below). No writes, no dispatches, no fixes. |
| `/pipeline <anything else>` | **Ask the user what they meant.** Never guess a verb. `fix-mode` in particular is internal-only — set exclusively by this skill's own fix loop, never a user argument; if the user passes it, refuse and explain that. |
```

with:

```markdown
Dispatch on `$ARGUMENTS` before doing anything else — the whole argument string,
trimmed. It is empty when the skill was invoked with no argument. (`$0` is not an
argument token: it is never substituted, so a table matching it routes every
invocation to the fallback arm.)

| Invocation | Behavior |
|------------|----------|
| `/superb:pipeline` (empty `$ARGUMENTS`) | **Full mode** — start at Stage 1, step 0. |
| `/superb:pipeline resume` | Run the **Resume Protocol** in `references/run-state.md`. **Never start a new run in this mode** — if no run directory exists, say so and stop. |
| `/superb:pipeline status` | **Strictly read-only report** (below). No writes, no dispatches, no fixes. |
| `/superb:pipeline <anything else>` | **Ask the user what they meant.** Never guess a verb. `fix-mode` in particular is internal-only — set exclusively by this skill's own fix loop, never a user argument; if the user passes it, refuse and explain that. |
```

- [ ] **Step 5: Namespace the remaining occurrences**

`README.md` — the four rows in its invocation table and the sentence beneath:

```bash
cd plugins/superb/skills/pipeline
sed -i 's|`/pipeline`|`/superb:pipeline`|g; s|`/pipeline resume`|`/superb:pipeline resume`|g; s|`/pipeline status`|`/superb:pipeline status`|g' README.md
sed -i 's|## Resume Protocol (`/pipeline resume`)|## Resume Protocol (`/superb:pipeline resume`)|' references/run-state.md
```

Then read `README.md`'s table and the `typing /superb:pipeline is enough` sentence to confirm the substitution did not double-namespace anything.

- [ ] **Step 6: Run the gate to verify GREEN**

```bash
./tools/check-plugin.sh
```

Expected: `ok    no $0 dispatch, no inert argument-hint, invocations namespaced` and `check-plugin: PASS`.

- [ ] **Step 7: Add mutants proving the new arm can fail**

```bash
run_mutant "skill dispatches on \$0 again"         "sed -i 's|Dispatch on \`\$ARGUMENTS\`|Dispatch on the argument (\`\$0\`)|' plugins/superb/skills/pipeline/SKILL.md"
run_mutant "argument-hint reintroduced"            "sed -i '3a argument-hint: \"[resume|status]\"' plugins/superb/skills/pipeline/SKILL.md"
run_mutant "invocation loses its namespace"        "sed -i 's|/superb:pipeline|/pipeline|g' plugins/superb/skills/pipeline/SKILL.md"
```

- [ ] **Step 8: Run both gates**

```bash
./tools/check-plugin.sh && ./tools/check-plugin-mutants.sh
```

Expected: `check-plugin: PASS`, then all three new mutants `killed` and `check-plugin-mutants: PASS`.

- [ ] **Step 9: Commit**

```bash
git add plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/README.md plugins/superb/skills/pipeline/references/run-state.md tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "fix(pipeline): dispatch on \$ARGUMENTS, and call the command by its real name"
```

---

### Task 3: Reject the fourth severity tier at consolidation

**Files:**
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md` (the consolidation bullet in the per-phase loop, step 2)
- Modify: `plugins/superb/skills/pipeline/SKILL.md` (Stage 4 step 2's consolidation sentence)
- Modify: `plugins/superb/skills/pipeline/templates/findings.md` (severity table preamble)
- Modify: `tools/check-plugin.py` (extend the `== skill invocation ==` section from Task 2 into a tier check, or add a sibling arm)
- Modify: `tools/check-plugin-mutants.sh` (add one mutant)

**Interfaces:**
- Consumes: the gate section added in Task 2.
- Produces: the three-tier vocabulary that Task 4's closure rule is written against.

**Why this is an addition, not a deletion.** `Important` occurs **zero** times in this skill. It reached the MIPS-7319 ledger 120 times from `subagent-driven-development/task-reviewer-prompt.md`, whose contract is "dispatch fix subagent for ALL findings (Critical, Important, Minor)" — correct for one task's diff, wrong for a phase, because pipeline's blocking list is closed and different. The fix is an explicit re-tag at the seam, not a removal.

- [ ] **Step 1: Add the failing gate arm**

In `tools/check-plugin.py`, inside the `== skill invocation ==` loop body, add:

```python
    if re.search(r"\bImportant\b", t) and not re.search(
            r"an incoming `?Important`? is\s+re-tagged", flat):
        bad(f"{n}/SKILL.md names a fourth severity tier without a re-tag rule")
```

Match against `flat` — the whitespace-normalised copy Task 2's loop already builds
— not against `t`. The re-tag phrase Task 3 writes into `SKILL.md` is prose and
will line-wrap; a regex run against the raw text would miss it the moment the
sentence reflows, and the arm would then fail on the very rule it exists to
require. This is the same class of defect as Task 2's `$0` ban.

- [ ] **Step 2: Run the gate and confirm it is GREEN (nothing to catch yet)**

```bash
./tools/check-plugin.sh
```

Expected: PASS. The arm exists but the skill does not yet mention `Important` at all — this arm's job is to stop a future edit naming the tier without handling it. Its falsifiability is proved by the mutant in step 6, not by a red run here.

- [ ] **Step 3: Write the re-tag rule into `fix-loop.md`**

In the per-phase loop, step 2, replace the consolidation bullet's severity sentence:

```markdown
   - Consolidate findings from all reviewers **into `findings.md`**, dedup, and
     tag each by severity: **Critical**, **Major** (maps to `/review`
     "Warning"), **Minor**. When duplicate reports disagree on severity, **the
     highest severity wins**.
```

with:

```markdown
   - Consolidate findings from all reviewers **into `findings.md`**, dedup, and
     tag each by severity. **There are exactly three tiers: Critical, Major
     (= `/review`'s "Warning"), Minor.** A reviewer that reports in another
     vocabulary is re-tagged here, never carried: `subagent-driven-development`'s
     task reviewer emits **Important**, whose contract is "fix everything before
     this task completes" — right for one task's diff, wrong for a phase, and it
     is not in this skill's blocking list. So **an incoming `Important` is
     re-tagged** by consequence: it becomes **Major** if it names a measured
     behavioural defect, a failing or vacuous test, a broken build gate, or a
     security/PHI/data-loss reachability, and **Minor** otherwise. Record the
     re-tag in the ledger row so the call is visible.
     When duplicate reports disagree within the three tiers, **the highest wins**.
```

- [ ] **Step 4: Mirror the closed list into `SKILL.md`**

In Stage 4 step 2, replace:

```markdown
   Consolidate + dedup into `findings.md`, **assigning each new finding a
   stable `F-NNN` ID** (Critical / Major (= `/review` "Warning") / Minor;
   severity ties resolve upward; a rediscovered finding keeps its old ID), then
```

with:

```markdown
   Consolidate + dedup into `findings.md`, **assigning each new finding a
   stable `F-NNN` ID**. **Three tiers only** — Critical / Major (= `/review`
   "Warning") / Minor; ties within them resolve upward; a rediscovered finding
   keeps its old ID; **an incoming `Important` is re-tagged** to Major or Minor
   by the predicate in `references/fix-loop.md` and never carried as a tier. Then
```

- [ ] **Step 5: Add the note to the ledger template**

In `templates/findings.md`, immediately below the `## Blocking ledger (Critical / Major / bug)` heading's table, add:

```markdown
**Three tiers, and no fourth.** `Sev` is `Critical`, `Major` or `Minor`. A
reviewer reporting `Important` (the task-reviewer vocabulary) is re-tagged on the
way in — Major if the finding names a measured behavioural defect, a failing or
vacuous test, a broken build gate, or a security/PHI/data-loss reachability;
Minor otherwise. Write the re-tag in the row, so a tier nobody decided cannot
end up gating a phase.
```

- [ ] **Step 6: Add a mutant proving the tier arm can fail**

```bash
# WRONG — this mutant SURVIVES. The arm fires only when `Important` is present
# AND the re-tag phrase is absent; this mutation ADDS a mention while leaving the
# re-tag sentence intact, so the arm is satisfied and the gate passes. Since this
# task's red run is green by design, that mutant is the arm's ONLY falsibility
# proof, so shipping it ends the run at survived=1.
# Mutate the RULE, not the mention, and assert the mutation applied:
run_mutant "fourth severity tier named without its re-tag rule" "<rewrite the 'an incoming \`Important\` is re-tagged' sentence so the rule is gone while the word stays; guard with assert ... in s>"
```

- [ ] **Step 7: Run both gates**

```bash
./tools/check-plugin.sh && ./tools/check-plugin-mutants.sh
```

Expected: `check-plugin: PASS`; new mutant `killed`; `check-plugin-mutants: PASS`.

- [ ] **Step 8: Commit**

```bash
git add plugins/superb/skills/pipeline/references/fix-loop.md plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/templates/findings.md tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "fix(pipeline): three severity tiers, and a re-tag for the fourth that arrives anyway"
```

---

### Task 4: A claim finding closes by deletion or by a test, never by a rewrite

**Files:**
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md` (the *Finding-closure ledger* section)
- Modify: `plugins/superb/skills/pipeline/SKILL.md` (Common mistakes; the rationalization table)
- Modify: `plugins/superb/skills/pipeline/templates/findings.md` (the closure sentence under the blocking ledger)

**Interfaces:**
- Consumes: Task 3's three-tier vocabulary.
- Produces: the term **claim finding**, which Task 6's derive-don't-restate rule refers to.

**The defect being closed.** Three of five completed review lines had a fix round that raised *new* blocking findings, all of one species: F-142 is "the fix for a false count contained a false count"; F-159 "invalidated 6 citations correct at its parent and half-fixed a 7th"; F-111/112/113 were "3 NEW unexecuted claims introduced BY the fixes". A prose assertion is closed by rewriting the prose, and the rewrite is a fresh unexecuted assertion. The loop has no fixed point.

- [ ] **Step 1: Add the closure rule to `fix-loop.md`**

In *Finding-closure ledger (`findings.md`)*, after the two existing closure bullets ("Fixed and verified" and "User-ruled false positive"), add:

```markdown
**A claim finding closes differently, and this is the one closure rule with a
termination argument behind it.** A *claim finding* is one whose defect is an
assertion rather than a behaviour: a comment, docblock or commit message that
states a count, a `file:line` citation, a sole-writer or sole-caller claim, or
"X is what protects Y". **Enforcement code is not exempt.** A comment in a
gate, a linter or a test harness that asserts undocumented or re-derivable
behaviour is a claim finding like any other — the exemption "it is rationale, not
model-facing prose" is exactly the carve-out that would let the rule's own
enforcement code keep the claims the rule exists to remove. It closes by exactly one of:

- **Deleting the claim.** Always available, always terminating.
- **Pinning it with a test** that fails when the claim stops being true, or
  re-anchoring it to a symbol that moves with the code.

**Rewriting the sentence is not a closure.** A corrected assertion is still an
unexecuted assertion, and the next commit under it makes it false again — which
is why fixing one produced the next in three of five review rounds observed.
So: a claim finding closed by deletion or by a pin **opens no re-review round** —
there is no behaviour to re-review, and the pin, if any, is a test the suite
already runs. A claim finding whose fix rewrote prose is **not closed**; send it
back for deletion or a pin.

This also means a claim finding is never Critical or Major on its own. It becomes
Major only through Task-3's predicate — when the false claim is load-bearing for
another task, which is the case the MIPS-7319 run kept hitting (a docblock that
"would have told Tasks 6 and 9 their work was done").
```

- [ ] **Step 2: Add the matching row to the rationalization table in `SKILL.md`**

After the row beginning `| "These two findings are basically the same one from last round"`, add:

```markdown
| "The comment was wrong, I corrected it — finding closed" | A corrected assertion is still unexecuted, and the next commit falsifies it again. A claim finding closes by deleting the claim or pinning it with a test. Nothing else. |
| "I'll re-review the fix to the docblock to be safe" | There is no behaviour to re-review. A claim finding closed by deletion or a pin opens no round; one closed by a rewrite is not closed. |
```

- [ ] **Step 3: Add the matching entry to Common mistakes in `SKILL.md`**

After the bullet beginning `- **Minting a new F-ID for a rediscovered finding**`, add:

```markdown
- **Closing a claim finding by rewriting the sentence** — the rewrite is the next
  round's finding. Delete the claim, or pin it with a test. Observed three times
  in five review lines; it is the loop's only non-terminating cycle.
```

- [ ] **Step 4: Update the template's closure sentence**

In `templates/findings.md`, the paragraph beginning `**State** is one of ...` — after "or the **user** ruled it a false positive.", append:

```markdown
A **claim finding** (a false count, a stale citation, a wrong sole-writer claim)
closes only by **deleting the claim** or **pinning it with a test** — never by
rewriting the prose, which is how a fix round raises its own successor. Such a
closure opens no re-review round.
```

- [ ] **Step 5: Verify internal consistency**

```bash
cd plugins/superb/skills/pipeline
grep -rn 'claim finding' . | sort
```

Expected: at least one hit each in `references/fix-loop.md`, `SKILL.md` and `templates/findings.md`, with no contradicting statement that a rewrite closes anything.

- [ ] **Step 6: Run both gates**

```bash
cd /home/wp3/IntellijProjects/claude-plugin
./tools/check-plugin.sh && ./tools/check-plugin-mutants.sh
```

Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add plugins/superb/skills/pipeline/references/fix-loop.md plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/templates/findings.md
git commit -m "fix(pipeline): a claim closes by deletion or a test, so the fix loop terminates"
```

---

### Task 5: Re-spec the re-review fan-out to the fix diff

**Files:**
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md` (the *Re-review fan-out* section and its table; the step-3 grammar; the Invariants bullet)
- Modify: `plugins/superb/skills/pipeline/SKILL.md` (the `RV` line's per-round grammar; *Re-review fan-out (different math)*; the rationalization row; the red flag; the Common-mistakes bullet)
- Modify: `plugins/superb/skills/pipeline/README.md` (the fan-out sentence)
- Modify: `tools/check-plugin-mutants.sh` (**required** — retarget the mutant that seds the changed example)

**Interfaces:**
- Consumes: Task 2's namespaced command form.
- Produces: the per-round grammar `M=<n> → 1 slice + 0 integration` that Task 9's `--run` linter validates against a real tracker.

**The evidence.** `ceil(M/3)` was applied four times and overridden four times, every time downward, each logged as "DEVIATION, recorded": M=7→1+0, M=6→1+0, M=7→2+0, M=4→no fan-out. The skill's own author had already reached the same conclusion for the sibling rule — `tools/check-plugin.py` declines to check `ceil(N/5)` because "a waved phase legitimately departs from it."

**The landmine.** `p3-rr2-{a,b,c,int}.md` appears in `SKILL.md` and `references/fix-loop.md`, and `check-plugin-mutants.sh` seds that literal in `SKILL.md` (mutant `"re-review round loses report files"`). Changing the example without retargeting the mutant makes the mutant a no-op, which the harness reports as SURVIVED and fails on. Both change in this commit.

- [ ] **Step 1: Replace the re-review table in `fix-loop.md`**

Replace the section body under `## Re-review fan-out (fix-mode returns)` — the paragraph and the four-row table — with:

```markdown
The Stage 4 rule `ceil(N/5)` is defined over **tasks**. A fix-mode run produces
fix commits, not tasks, so re-reviews get their own rule — and it is a rule about
**diff surface**, not about how many findings were named:

| Fix diff | Slice reviewers | Integration reviewer |
|----------|-----------------|----------------------|
| One commit, or one file cluster | 1 | 0 (the one slice sees all) |
| Two or more disjoint file clusters | 1 per cluster | 1 |

**Why not `ceil(M/3)`.** `M` counts findings; a round of six comment corrections
in one file is one small diff, and three reviewers over it re-read the same hunks
and duplicate each other's findings. The earlier `ceil(M/3)` rule was applied
four times in testing and overridden downward all four, each override recorded as
a deviation — a rule with a 100% deviation rate is a rule that was already
rejected in practice. `M` is still **recorded** on the round, because the
convergence check compares ID sets; it just no longer sizes the fan-out.

- **A file cluster** is the set of fix commits touching files that a single
  reviewer must hold together to judge them — the same producer/consumer test the
  integration reviewer uses. When in doubt, one reviewer.
- **Slice boundaries are the fix commits' ranges**, taken from the ledger's
  recorded fix hashes — the same range discipline as Stage 4 slices.
- **Assignments MUST cover every fix diff**, unchanged: union the assigned ranges
  and compare against the full set of commits the fix-mode run produced; if any
  commit is unassigned, extend a slice. **A clean round from reviewers who never
  looked at a fix closes nothing.**
- **A claim finding closed by deletion or a pin gets no reviewer at all** — see
  the closure rule in *Finding-closure ledger*. Only behavioural fixes are
  re-reviewed. **KEEP THE `M` HALF:** the closure rule cross-references this
  bullet for *both* exclusions — from `M` and from the coverage union. Dropping
  the `M` half here leaves that cross-reference dangling and silently reverts
  the fan-out to its unqualified "Assignments MUST cover every fix diff",
  reinstating the contradiction Task 4 fixed.
- The integration reviewer's scope is the union of all fix commits, hunting
  interactions between fixes and regressions the fixes introduced elsewhere.
- Re-reviews also re-run the test suite; failures are bug findings as always.
```

- [ ] **Step 2: Update the per-round grammar in `fix-loop.md` step 3**

In the fix loop's step 3, replace the worked round string:

```markdown
   per-round grammar — `→ round 2: M=9 → 3 slice + 1 integration · reports
   p3-rr2-{a,b,c,int}.md · coverage p3-rr2-coverage.md → F-012 closed, F-014
   raised` — so every round has a declared number its file count is checked
   against, not only the first. `M` is the targeted F-ID count and the fan-out
   is `ceil(M/3)`. Whoever ran the round writes it, at whatever depth.
```

with:

```markdown
   per-round grammar — `→ round 2: M=9 → 1 slice + 0 integration · reports
   p3-rr2-a.md · coverage p3-rr2-coverage.md → F-012 closed, F-014 raised` — so
   every round has a declared number its file count is checked against, not only
   the first. `M` records the targeted F-ID count for the convergence check; the
   fan-out comes from the fix diff's clusters. Whoever ran the round writes it,
   at whatever depth.
```

- [ ] **Step 3: Update the same grammar in `SKILL.md`**

In *The RV line*, replace:

```markdown
      → round 2: M=9 → 3 slice + 1 integration · reports p3-rr2-{a,b,c,int}.md
        · coverage p3-rr2-coverage.md → F-012 closed, F-014 raised
```

with:

```markdown
      → round 2: M=9 → 1 slice + 0 integration · reports p3-rr2-a.md
        · coverage p3-rr2-coverage.md → F-012 closed, F-014 raised
```

and the sentence beneath it:

```markdown
`M` is the count of targeted F-IDs and the fan-out is `ceil(M/3)` (not
`ceil(N/5)` — fix diffs are not task-shaped), with coverage over the fix commits.
```

with:

```markdown
`M` records the count of targeted F-IDs for the convergence check. The fan-out is
**one reviewer per file cluster in the fix diff**, integration only above one
reviewer (not `ceil(N/5)` — fix diffs are not task-shaped, and not `ceil(M/3)` —
findings are not diff surface), with coverage over the fix commits.
```

- [ ] **Step 4: Update `SKILL.md`'s *Re-review fan-out (different math)* section**

Replace its body with:

```markdown
`ceil(N/5)` is defined over **tasks**. Fix-mode returns produce fix commits, so a
re-review is sized from the **fix diff**: **one slice reviewer per file cluster**,
plus an integration reviewer once there is more than one. `M`, the count of
targeted F-IDs, is still recorded on the round for the convergence check — it no
longer sizes the fan-out, because six comment corrections in one file are one
small diff and three reviewers over it duplicate each other. Slice boundaries are
the fix commits' ranges, and **the assigned ranges must union to cover every fix
commit** — a clean round from reviewers who never looked at a fix closes nothing.
A claim finding closed by deletion or a pin is re-reviewed by nobody; there is no
behaviour to review. Table in `references/fix-loop.md`.
```

- [ ] **Step 5: Fix the three remaining `ceil(M/3)` references**

```bash
cd plugins/superb/skills/pipeline
grep -n 'ceil(M/3)' SKILL.md README.md references/fix-loop.md
```

Rewrite each hit found:
- `SKILL.md` rationalization row `| "The fix was small, one reviewer over the whole thing is fine" |` → answer becomes: `One reviewer per file cluster in the fix diff, and the ranges must cover every fix commit. "Small" is a judgement about clusters, not a licence to skip coverage.`
- `SKILL.md` red flag `- You are sizing a re-review fan-out off task count instead of targeted F-IDs.` → `- You are sizing a re-review fan-out off task count, or off the number of findings, instead of the fix diff's file clusters.`
- `SKILL.md` Common mistakes `- **Sizing a re-review with `ceil(N/5)`** ...` → `- **Sizing a re-review off task count or off finding count** — fix diffs aren't task-shaped and findings aren't diff surface; one reviewer per file cluster, with ranges covering every fix commit.`
- `README.md` line beginning `math — `ceil(M/3)` over the findings the fix targeted` → `math — one reviewer per file cluster in the fix diff — and the assigned ranges`
- `references/fix-loop.md` Invariants bullet `- **Re-reviews use the re-review fan-out (`ceil(M/3)` over targeted F-IDs), not `ceil(N/5)`**, ...` → `- **Re-reviews are sized from the fix diff** — one reviewer per file cluster, integration above one — **not** from task count or finding count, and their assigned ranges must union to cover every fix commit.`

Then confirm none remain:

```bash
grep -rn 'ceil(M/3)\|M/3' . ; echo "exit=$?  (1 = clean)"
```

- [ ] **Step 6: Retarget the mutant whose literal this task changed**

In `tools/check-plugin-mutants.sh`, replace:

```bash
run_mutant "re-review round loses report files"   "sed -i 's|p3-rr2-{a,b,c,int}.md|p3-rr2-{a,int}.md|' plugins/superb/skills/pipeline/SKILL.md"
```

with a mutant that bites the new example — it must make the declared count and the listed files disagree:

```bash
# Retargeted when the re-review fan-out moved off ceil(M/3) (the example went
# from 3 slice + 1 int to 1 slice + 0 int). A sed on a string the docs no longer
# contain is a no-op, and a mutant that changes nothing proves nothing.
run_mutant "re-review round over-declares reviewers" "sed -i 's|M=9 → 1 slice + 0 integration|M=9 → 3 slice + 1 integration|' plugins/superb/skills/pipeline/SKILL.md"
```

- [ ] **Step 7: Run both gates**

```bash
cd /home/wp3/IntellijProjects/claude-plugin
./tools/check-plugin.sh && ./tools/check-plugin-mutants.sh
```

Expected: `check-plugin: PASS`; the retargeted mutant `killed`; `survived=0`; `check-plugin-mutants: PASS`. **If it reports SURVIVED, the sed did not match — read the example's exact bytes and retarget, do not weaken the gate.**

- [ ] **Step 8: Commit**

```bash
git add plugins/superb/skills/pipeline/references/fix-loop.md plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/README.md tools/check-plugin-mutants.sh
git commit -m "fix(pipeline): size a re-review from the fix diff, not from the finding count"
```

---

### Task 6: Derive, don't restate

**Files:**
- Modify: `plugins/superb/skills/pipeline/references/run-state.md` (the dispatch contract; the two "three templates" counts)
- Modify: `plugins/superb/skills/pipeline/SKILL.md` (Rule 5's neighbourhood; three "three templates" counts; a rationalization row; a red flag)
- Modify: `plugins/superb/skills/pipeline/references/parallel.md` (the annotation-grammar note)

**Interfaces:**
- Consumes: Task 4's term *claim finding*.
- Produces: the phrase "state a code fact" used by Task 7's kit and Task 8's dispatch contract.

**The evidence.** Around ten orchestrator-brief errors in one run, every one caught by an agent rather than the orchestrator: a function placed in the wrong file, helpers that were `private` and unreachable from the named test class, 10 call sites where there were 12, a `bool` return type read as an argument. The tracker's own line: "CONTROLLER ERRORS THIS PHASE (5), all caught by agents."

- [ ] **Step 1: Add the rule as a new sub-section of the Run State Law in `SKILL.md`**

Immediately after Rule 5's block (*Hold pointers, not payloads*), insert:

```markdown
### Rule 5b — Derive, don't restate

A brief, a plan or a comment **may not state a code fact.** No counts ("the four
reachable states"), no line numbers, no method or field names presented as
existing, no type or signature, no file list. State the fact's **source** instead:
the symbol it lives on, or the command that regenerates it.

The reason is mechanical: a restated fact is correct at the moment it is written
and at no moment after. The orchestrator writes briefs from a tree that moves
under them, so a restated fact is wrong at a rate the run cannot absorb — and
because the agent receiving it treats the brief as authority, the error is only
caught when the agent happens to look. In testing every such error *was* caught,
by the agent, after it had already shaped the work.

- **Writing a brief:** name the symbol (`Store::saveTicketOutcome`), not the
  location (`Store.php:571`). Give the command (`grep -rn 'setDuplicateOverride'`),
  not its output ("12 call sites").
- **Receiving a brief:** a brief that states a code fact is **refused** — send it
  back rather than reconciling it. You cannot tell a stale fact from a current one
  without deriving it, and if you are deriving it the brief's copy was worthless.
- **Writing a comment:** anchor to a symbol or delete the claim. A comment that
  asserts a re-derivable fact is a **claim finding** waiting to happen — see the
  closure rule in `references/fix-loop.md`.

This rule applies to this skill's own prose. Where these documents once counted
their own templates, they now name the directory.
```

- [ ] **Step 2: Apply the rule to this skill's own restated counts**

Five prose counts become derivations:

```bash
cd plugins/superb/skills/pipeline
sed -i 's|`templates/` holds the three run-state file templates.|`templates/` holds the run-state file templates.|' SKILL.md
sed -i 's|the three files ship in `templates/` and are \*\*read-only\*\* — copy them, never|the templates ship in `templates/` and are **read-only** — copy them, never|' SKILL.md
sed -i 's|copy in the three|copy in the|' SKILL.md
sed -i 's|Templates for the three files ship with the skill in `templates/`|Templates for these files ship with the skill in `templates/`|' references/run-state.md
sed -i 's|copy the three templates in, strip their comments, and|copy the templates in, strip their comments, and|' references/run-state.md
grep -rn 'three templates\|three files\|the three run-state' . ; echo "exit=$?  (1 = clean)"
```

- [ ] **Step 3: Put the rule in the dispatch contract**

In `references/run-state.md`, under *Orchestrator context hygiene*, after the ≤10-line return block, add:

```markdown
**Every dispatch prompt carries Rule 5b: derive, don't restate.** The brief names
symbols and the commands that regenerate facts; it does not state counts, line
numbers, signatures or file lists. An agent that receives a stated code fact
**refuses the brief and says which fact** — that refusal is correct behaviour and
costs one round trip, where acting on a stale fact costs the task.
```

- [ ] **Step 4: Add the rationalization row and red flag to `SKILL.md`**

Rationalization table — after the `"Codebase precedent is the strongest non-user disambiguator"` row:

```markdown
| "I'll put the line numbers in the brief so the agent finds it faster" | A line number is correct when you write it and at no moment after. Name the symbol, or the command that finds it. |
| "The brief says 12 call sites; close enough to act on" | It said 10 last time and there were 12. A stated code fact is refused, not reconciled. |
```

Red flags — *STOP and re-read the run state* list, after the `DETAIL:` bullet:

```markdown
- You are writing a count, a line number, a signature or a file list into a
  brief, a plan or a comment instead of the symbol or the command that derives it.
```

- [ ] **Step 5: Add the matching note to `parallel.md`'s annotation grammar**

After the paragraph beginning `` `Depends on:` lists task IDs in the same phase ``, add:

```markdown
`Files:` names paths, which are the one code fact a plan must state — the wave
computation is a set-disjointness test over exactly those paths. Everything else
about a task's code is named by symbol or by the command that finds it (Rule 5b).
A `Files:` block with a glob, a directory or "various" in it is still incomplete.
```

- [ ] **Step 6: Run both gates**

```bash
cd /home/wp3/IntellijProjects/claude-plugin
./tools/check-plugin.sh && ./tools/check-plugin-mutants.sh
```

Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/references/run-state.md plugins/superb/skills/pipeline/references/parallel.md
git commit -m "feat(pipeline): derive, don't restate — briefs name symbols, not stale facts"
```

---

### Task 7: A run-level verification kit, written once at GATE 2

**Files:**
- Create: `plugins/superb/skills/pipeline/templates/kit.md`
- Modify: `plugins/superb/skills/pipeline/SKILL.md` (the run-directory tree; Stage 1 step 0; the GATE 2 flush list)
- Modify: `plugins/superb/skills/pipeline/references/run-state.md` (the run-directory tree; the dispatch contract)

**Interfaces:**
- Consumes: Task 6's "state a code fact" phrasing (the kit records commands, not outputs).
- Produces: `agent-output/kit.md` as a path every later dispatch cites.

**The evidence.** Across 48 tasks, roughly 190 hand re-derivations of the same apparatus — write-free mutation harness, identity control, DB-free in-memory store, skip census, full-suite failing-name diff. Two agents also mutated the same file in the main tree concurrently and produced a phantom failure a third had to chase; the plugin's own `check-plugin-mutants.sh` header records the same hazard biting it twice.

- [ ] **Step 1: Create the template**

Create `plugins/superb/skills/pipeline/templates/kit.md`:

```markdown
<!--
TEMPLATE — read-only. Copy to the run directory, then delete this comment:
  <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/kit.md
Written at GATE 2, once, from the approved plan. Every dispatch cites it by path
instead of re-deriving it. Records COMMANDS, never their output (Rule 5b).
-->

# Verification Kit

The apparatus every task in this run shares. A dispatch that needs a harness
cites this file; it does not invent one. When a task discovers the kit is wrong
or incomplete, it **fixes the kit in the same commit** — the next task reads this
file, not that task's report.

## Commands

| What | Command |
| ---- | ------- |
| Full suite | `<the project's full test command>` |
| Changed-line coverage | `<the project's coverage command, scoped to the diff>` |
| Build gates | `<the gates the approved plan names — see parallel.md step 7>` |
| Lint / style | `<command>` |

## Baseline discipline

Record the baseline by **command**, not by number: a count pasted here is a
claim finding waiting to happen. Before and after any change, compare:

- the suite's pass/fail/skip triple,
- the **set of failing test names** (a diff of the sets, not a count — two
  different failures can hold a count still),
- the **skip count, which may never rise**: a new test that lands as a skip is a
  test that certifies nothing, and a whole suite behind an unmet precondition
  reads exactly like a suite that passes.

## Mutation harness

Every load-bearing assertion is proved by a mutant that the assertion kills, plus
an **identity control** — a mutation that changes nothing observable and must
therefore SURVIVE. A harness whose controls die is broken and its kills mean
nothing; a harness that reports FAIL for everything including the baseline is the
failure mode to check for first.

- Mutate a **throwaway copy**, never the working tree.
- Restore by byte snapshot with a checksum, never by `git checkout --`.
- A mutant that matches nothing is a no-op, and a no-op proves nothing: assert
  the mutation actually applied before trusting a kill.

## Worktree hygiene

- **Never mutate, patch or `git`-operate on a shared file in the main tree.**
  Concurrent agents doing this produce phantom failures that another agent then
  spends a round chasing. Each wave member works in its own worktree
  (`parallel.md`); anything else copies first.
- Concurrent reviewers read; they do not write to the tree they read.

## Project specifics

<!-- Anything this run's repo requires that a fresh agent cannot infer: a ticket
key in every commit subject, a coverage floor, a provisioning step, a template
directory that must be copied by hand. Name the rule and where it is written. -->
```

- [ ] **Step 2: Add the file to both run-directory trees**

In `SKILL.md`'s run-directory block and `references/run-state.md`'s identical block, add the line after `findings.md`:

```
  kit.md             # the run's shared verification apparatus (GATE 2)
```

- [ ] **Step 3: Wire it into Stage 1 step 0 and the GATE 2 flush**

`SKILL.md` Stage 1 step 0 — the templates copied at creation are the tracker, register and ledger; `kit.md` is written at GATE 2 when the plan is known. Add to step 0, after "copy in the templates":

```markdown
   (`kit.md` is written later, at GATE 2, from the approved plan — it cannot be
   filled in before the plan names the gates.)
```

In *Compacting at GATE 2*, add a numbered item after item 2:

```markdown
3. **`kit.md` is written** — the suite, coverage and build-gate commands the
   approved plan names, the baseline discipline, the mutation harness and the
   worktree rule. It is written once, here, because every dispatch after this
   point cites it instead of re-deriving it; 48 tasks re-deriving one harness is
   the cost this file exists to delete. Commands only, never their output.
```

Renumber the two items that followed (the old 3 and 4 become 4 and 5).

- [ ] **Step 4: Make every dispatch cite it**

In `references/run-state.md`'s *Orchestrator context hygiene*, immediately after the Rule 5b paragraph added in Task 6, add:

```markdown
**Every dispatch prompt also cites `kit.md` by path.** The agent reads the
harness, the baseline discipline and the worktree rule from that one file. A
dispatch that describes a harness inline instead is how one run rebuilt the same
apparatus in every task; a dispatch that omits it is how two agents came to
mutate the same file in the main tree at once.
```

- [ ] **Step 5: Confirm the new template does not break the gate**

`check-plugin.py` requires each skill directory to have a `SKILL.md` and a
`README.md`, and requires every `*.sh` under a skill to be executable. A new
`templates/*.md` adds no such obligation.

```bash
cd /home/wp3/IntellijProjects/claude-plugin
./tools/check-plugin.sh && ./tools/check-plugin-mutants.sh
```

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/superb/skills/pipeline/templates/kit.md plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/references/run-state.md
git commit -m "feat(pipeline): one run-level kit instead of 48 hand-rolled harnesses"
```

---

### Task 8: The ticket key becomes a Stage 1 question and a dispatch field

**Files:**
- Modify: `plugins/superb/skills/pipeline/SKILL.md` (Stage 1 step 2's neighbourhood; Stage 1 step 0)
- Modify: `plugins/superb/skills/pipeline/references/run-state.md` (the ≤10-line return contract)
- Modify: `plugins/superb/skills/pipeline/templates/register.md` (a seeded entry)

**Interfaces:**
- Consumes: Task 7's `kit.md` *Project specifics* section, where the repo rule is recorded.
- Produces: nothing later tasks depend on.

**Why.** The skill has zero mentions of a ticket or issue key across all its files. Repos that require one — "no commit without `MIPS-XXXX` in the subject" — get a run whose every per-task implementer commit violates the rule, and the skill's only hook is the phrase "the project quality gates".

- [ ] **Step 1: Seed the register template with the question**

In `templates/register.md`'s **Open** table, replace the single example row with two:

```markdown
| A1 | Does this repo require a ticket/issue key in every commit subject, and if so which one for this run? | A commit convention is a written repo rule this skill cannot infer, and every task in the run commits. Getting it wrong is unfixable without a rewrite. | Stage 1 |
| A2 | <the unknown, stated as the question it will become> | <why no default is legitimate> | <stage/phase> |
```

- [ ] **Step 2: Make Stage 1 ask it**

In `SKILL.md`, Stage 1, after step 2 ("Run as many question rounds as it takes…"), insert:

```markdown
2b. **Ask the repo's commit and verification conventions in the first round** —
   the ticket/issue key required in a commit subject (and this run's value for
   it), any coverage floor on changed lines, and any pre-push gate. These are
   written repo rules, so the predicate says follow them — but the skill cannot
   *find* them by inference, and every task in the run commits. Seed them as
   register entries; record the answers in `kit.md`'s *Project specifics* at
   GATE 2. A run that discovers its commit convention at Stage 5 cannot apply it
   without rewriting history.
```

- [ ] **Step 3: Put the key in the dispatch contract**

In `references/run-state.md`, the ≤10-line return block, extend the shape:

```
TASK:    T4
STATUS:  done | blocked | needs-decision
COMMIT:  a1b2c3d | nocommit
BRANCH:  wt/p2-t4 | <phase branch>   (the branch the commit is on)
FILES:   src/x.php, src/y.php
TESTS:   pass | fail — <one line>
NOTES:   <≤2 lines: only what changes the orchestrator's next move>
DETAIL:  agent-output/<label>.md   (omit if there is nothing longer)
```

and add beneath it:

```markdown
**Where the repo requires a ticket key in the commit subject, every dispatch
prompt states it and the implementer puts it there.** It is recorded once in
`kit.md`'s *Project specifics*, answered at Stage 1, and it is not the
implementer's to infer from a branch name. A `COMMIT:` hash whose subject is
missing the key is a task that has to be redone, not a bookkeeping lapse.
```

- [ ] **Step 4: Verify**

```bash
cd plugins/superb/skills/pipeline
grep -rn 'ticket/issue key\|ticket key' . | sort
cd /home/wp3/IntellijProjects/claude-plugin
./tools/check-plugin.sh && ./tools/check-plugin-mutants.sh
```

Expected: hits in `SKILL.md`, `references/run-state.md`, `templates/register.md`; both gates PASS. Note `check-plugin.py`'s leakage arm rejects a literal `MIPS-` in plugin files — so the docs must say "ticket/issue key" generically and never name a real project's prefix. If the gate reports a leakage FAIL here, that is the arm working: remove the concrete prefix.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline/SKILL.md plugins/superb/skills/pipeline/references/run-state.md plugins/superb/skills/pipeline/templates/register.md
git commit -m "feat(pipeline): ask the commit convention at Stage 1, not at Stage 5"
```

---

### Task 9: Point the review-line linter at a real run directory

**Files:**
- Modify: `tools/check-plugin.py` (wrap the review-line linter in a function; add `--run` handling)
- Modify: `tools/check-plugin-mutants.sh` (add a fixture-based mutant set)
- Create: `tools/fixtures/run-ok/progress.md`, `tools/fixtures/run-ok/agent-output/p1-review-a.md`, `tools/fixtures/run-ok/agent-output/p1-coverage.md`

**Interfaces:**
- Consumes: Task 5's per-round grammar (`M=<n> → <s> slice + <i> integration`).
- Produces: `./tools/check-plugin.sh --run <dir>`.

**Why.** The linter already validates every closed `RV`/`RVJ` example in the skill's own markdown — declared reviewer count against listed report files, `RVJ` shape, coverage file present — and reports "10 closed review rounds … conform". Nothing runs it against a real tracker, so all four `ceil(M/3)` deviations were recorded as prose instead of caught. A real run also permits one check the examples cannot support: the named report files either exist in `agent-output/` or they do not.

- [ ] **Step 1: Extract the linter into a reusable function**

In `tools/check-plugin.py`, the review-line block currently walks `pdir.rglob("*.md")` inline. Refactor to:

```python
def lint_review_lines(paths, label, agent_output=None):
    """Check every closed RV/RVJ round declares as many report files as it lists.

    paths: iterable of .md files to scan.
    agent_output: when given, a directory each named report file must exist in —
        available for a real run, never for the skill's worked examples, whose
        filenames are illustrative.
    Returns (rounds_seen, violations).
    """
    seen = viol = 0
    for f in sorted(paths):
        t, e = read(f)
        if e: continue
        flat, starts, off = [], [], 0
        for ln in t.split("\n"):
            starts.append(off); flat.append(ln.strip()); off += len(ln.strip()) + 1
        flat = " ".join(flat)
        def lineno(pos):
            n = 1
            for k, st in enumerate(starts, 1):
                if st <= pos: n = k
                else: break
            return n
        marks = [(m.start(), (m.group(1) or m.group(2))) for m in start.finditer(flat)]
        for idx, (pos, kind) in enumerate(marks):
            end = marks[idx + 1][0] if idx + 1 < len(marks) else len(flat)
            rec = flat[pos:min(end, pos + 400)]
            d = decl.search(rec)
            if not d: continue
            seen += 1
            want = int(d.group(1)) + int(d.group(2))
            where = f"{f}:{lineno(pos)}"
            if kind == "RVJ" and (int(d.group(1)), int(d.group(2))) != (0, 1):
                viol += 1; bad(f"{where}: RVJ must be 0 slice + 1 integration, declares {d.group(1)}+{d.group(2)}")
            r = rpt.search(rec)
            names = [x.strip() for x in re.split(r"[,\s]+", r.group(1))] if r else []
            got = nfiles(r.group(1)) if r else 0
            if got != want:
                viol += 1; bad(f"{where}: declares {want} reviewers, lists {got} report files")
            if not cov.search(rec):
                viol += 1; bad(f"{where}: closed review round with no coverage file")
            if agent_output is not None and r:
                for nm in expand_braces(r.group(1)):
                    if not (agent_output / nm).exists():
                        viol += 1; bad(f"{where}: report file {nm!r} is not in {agent_output.name}/")
    return seen, viol
```

Add the brace expander beside `nfiles`:

```python
def expand_braces(spec):
    """'p3-review-{a,b,int}.md' -> ['p3-review-a.md', ...]; a plain name passes through."""
    spec = spec.strip()
    m = re.search(r"\{([^}]*)\}", spec)
    if not m:
        return [s for s in re.split(r"[,\s]+", spec) if s.endswith(".md")]
    pre, post = spec[:m.start()], spec[m.end():]
    return [f"{pre}{p.strip()}{post}" for p in m.group(1).split(",") if p.strip()]
```

- [ ] **Step 2: Add the `--run` mode**

At the top of `check-plugin.py`, after `ROOT = ...`:

```python
RUN_DIR = None
_argv = sys.argv[1:]
if _argv and _argv[0] == "--run":
    if len(_argv) < 2:
        print("usage: check-plugin.py [--run <run-directory>]"); sys.exit(2)
    RUN_DIR = pathlib.Path(_argv[1]).expanduser().resolve()
elif _argv:
    print(f"unknown argument {_argv[0]!r}; usage: check-plugin.py [--run <run-directory>]"); sys.exit(2)
```

Replace the inline review-line block's driver with:

```python
print("\n== pipeline review-line examples ==")
pdir = ROOT / "plugins" / "superb" / "skills" / "pipeline"
seen, viol = lint_review_lines(pdir.rglob("*.md"), "skill docs")
if not seen: bad("no closed RV/RVJ examples found — the grammar lost its worked instances")
elif not viol: ok(f"{seen} closed review rounds: reviewer counts, RVJ shape and coverage all conform")

if RUN_DIR is not None:
    print(f"\n== run tracker: {RUN_DIR} ==")
    tracker = RUN_DIR / "progress.md"
    if not tracker.exists():
        bad(f"{tracker} does not exist — not a pipeline run directory")
    else:
        ao = RUN_DIR / "agent-output"
        if not ao.is_dir():
            bad(f"{ao} does not exist — a closed review round has nowhere to have written its reports")
            ao = None
        rseen, rviol = lint_review_lines([tracker], "run tracker", agent_output=ao)
        if not rseen: bad(f"{tracker.name}: no closed RV/RVJ round — nothing has been reviewed yet")
        elif not rviol: ok(f"{rseen} closed review rounds in the tracker, every declared report file present")
```

- [ ] **Step 3: Create a conforming fixture run**

```bash
mkdir -p tools/fixtures/run-ok/agent-output
cat > tools/fixtures/run-ok/progress.md <<'EOF'
# Pipeline — Progress Tracker

## Current State
- **Phase:** Phase 1 — fixture
- **Next action:** none; this is a linter fixture
- **Last updated:** 2026-09-04
- **Run directory:** tools/fixtures/run-ok/

## Phase 1 — fixture · deps: none
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings
EOF
printf 'fixture reviewer report\n' > tools/fixtures/run-ok/agent-output/p1-review-a.md
printf '| report | range |\n| --- | --- |\n| p1-review-a.md | aaaaaaa^..aaaaaaa |\n\nCOVERED: 1/1 commits\n' > tools/fixtures/run-ok/agent-output/p1-coverage.md
```

- [ ] **Step 4: Run the new mode and verify GREEN**

```bash
./tools/check-plugin.sh --run tools/fixtures/run-ok
```

Expected: the usual sections, then `== run tracker: .../run-ok ==` and `ok    1 closed review rounds in the tracker, every declared report file present`, `check-plugin: PASS`.

- [ ] **Step 5: Verify the default mode is unchanged**

```bash
./tools/check-plugin.sh
```

Expected: `check-plugin: PASS`, no `== run tracker ==` section, and still `ok    10 closed review rounds` from the skill docs.

- [ ] **Step 6: Add mutants proving the run mode can fail**

```bash
run_mutant "run tracker over-declares reviewers"  "sed -i 's|N=1 → 1 slice + 0 integration|N=1 → 3 slice + 1 integration|' tools/fixtures/run-ok/progress.md && sed -i 's|check-plugin.py\"|check-plugin.py\" --run tools/fixtures/run-ok|' tools/check-plugin.sh"
run_mutant "run tracker cites a missing report"   "sed -i 's|reports p1-review-a.md|reports p1-review-z.md|' tools/fixtures/run-ok/progress.md && sed -i 's|check-plugin.py\"|check-plugin.py\" --run tools/fixtures/run-ok|' tools/check-plugin.sh"
run_mutant "run tracker loses its coverage file"  "sed -i 's| · coverage p1-coverage.md||' tools/fixtures/run-ok/progress.md && sed -i 's|check-plugin.py\"|check-plugin.py\" --run tools/fixtures/run-ok|' tools/check-plugin.sh"
```

Each mutant makes the wrapper pass `--run` by default inside the throwaway copy, so the harness's plain `./tools/check-plugin.sh` invocation exercises the new mode. If that proves brittle, add `tools/check-run-fixture.sh` (executable) invoking the mode directly and have the mutants edit that instead.

- [ ] **Step 7: Run both gates**

```bash
./tools/check-plugin.sh && ./tools/check-plugin-mutants.sh
```

Expected: `check-plugin: PASS`; the three new mutants `killed`; `survived=0`.

- [ ] **Step 8: Commit**

```bash
git add tools/check-plugin.py tools/check-plugin-mutants.sh tools/fixtures/
git commit -m "feat(tools): lint a real run's review lines, not only the worked examples"
```

---

### Task 10: Whole-change verification

**Files:** none modified — this task only measures.

**Interfaces:**
- Consumes: every prior task.
- Produces: the verdict.

- [ ] **Step 1: Both gates, from a clean tree**

```bash
cd /home/wp3/IntellijProjects/claude-plugin
git status --porcelain          # expect only untracked docs/superpowers/**
./tools/check-plugin.sh
./tools/check-plugin-mutants.sh
```

Expected: `check-plugin: PASS`; `survived=0` and `check-plugin-mutants: PASS`.

- [ ] **Step 2: The other two CI gates — the ones this change does not touch**

```bash
python3 -m unittest discover -s plugins/superb/skills/craft/tests -v
./tools/test-craftui.sh
```

Expected: `OK` from the first. The craft UI suite reports its own total and skips
browser-dependent tests where no browser can render — that skip is expected
locally and asserted separately in CI, so a local skip is not a failure. Neither
gate covers any file this change touches; they are here to prove that.

- [ ] **Step 3: Confirm each of the ten findings is actually addressed**

```bash
cd plugins/superb/skills/pipeline
echo "P-01"; grep -rc 'tools/build\|extension/src' . || echo "  clean"
echo "P-02"; grep -c 'Dispatch on the argument below' SKILL.md   # 1 = dispatch keys on $ARGUMENTS
grep -c 'never substituted\|fallback arm' SKILL.md || echo "  no false claim about \$0"
echo "P-03"; grep -rlc 'ticket/issue key' . | tr '\n' ' '; echo
echo "P-06 WITHDRAWN — argument-hint is documented and honoured; it MUST be present:"
grep -c 'argument-hint' ../*/SKILL.md | tr '\n' ' '   # expect 1 for all five skills
echo "L-01"; grep -rl 'claim finding' . | tr '\n' ' '; echo
echo "L-02"; grep -rl 're-tagged' . | tr '\n' ' '; echo
echo "L-04"; grep -rc 'ceil(M/3)' . || echo "  clean"; grep -rl 'file cluster' . | tr '\n' ' '; echo
echo "L-05"; grep -rl 'Derive, don' . | tr '\n' ' '; echo
echo "L-06"; ls templates/kit.md
echo "L-07"; cd /home/wp3/IntellijProjects/claude-plugin && ./tools/check-plugin.sh --run tools/fixtures/run-ok | grep 'run tracker'
```

Expected: P-01 and L-04's `ceil(M/3)` report clean; P-02 shows `$ARGUMENTS` and no `$0`; P-06 removed; the rest name the files that carry each rule.

- [ ] **Step 4: Read the diff once, whole**

```bash
git log --oneline origin/main..HEAD
git diff origin/main..HEAD --stat
```

Expected: nine commits, touching the nine files in the File Structure table plus `tools/fixtures/`.

- [ ] **Step 5: Hand off for review**

Do **not** commit anything here. Proceed to `superpowers:requesting-code-review` against `origin/main..HEAD`, then `superpowers:receiving-code-review` for the findings.

---

## Self-Review

**1. Spec coverage.** All ten in-scope findings map to a task: P-01→1, P-02→2, P-06→2, L-02→3, L-01→4, L-04→5, L-05→6, L-06→7, P-03→8, L-07→9, with 10 as the gate. The three out-of-scope items (P-04, L-03, L-08) are named in Global Constraints so an executor does not drift into them.

**2. Placeholder scan.** The one deliberate `<...>` set is inside `templates/kit.md`, where placeholders are the artifact's *content* — a template's fields are filled per run. Task 9 step 6 carries a named fallback rather than a vague one. No "TBD", no "add error handling", no "similar to Task N".

**3. Type consistency.** `lint_review_lines(paths, label, agent_output=None)` is defined in Task 9 step 1 and called twice in step 2 with matching arity. `expand_braces(spec)` is defined in step 1 and used in step 1. `nfiles`, `start`, `decl`, `rpt`, `cov`, `read`, `ok`, `bad` are pre-existing in `check-plugin.py`. Task 2's gate loop introduces `sdir`, which is pre-existing, and Task 3 extends that same loop body — Task 3 therefore depends on Task 2 having landed, which the sequencing note states.

**One correction found during review and fixed inline:** Task 3 was originally written as "delete the `Important` tier". Verification showed `Important` occurs **zero** times in the skill — it arrives from `subagent-driven-development`'s task reviewer. The task is now an *addition* (a re-tag rule at the consolidation seam), and its gate arm is green-on-arrival with its falsifiability proved by a mutant rather than by a red run. A plan that said "delete" would have sent an implementer looking for text that does not exist.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-04-pipeline-audit-fixes.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration. Suits this change: ten small tasks, each with its own gate cycle, and several carrying a mutant that must be seen to fail.

**2. Inline Execution** — execute in this session using `superpowers:executing-plans`, batching with checkpoints.

---

## RE-CUT, approved after Task 5: Tasks 6, 7 and 8 merge into one task

**Why.** Their insertion points are not independent and cannot be made so. Task 6
adds Rule 5b to `references/run-state.md`'s *Orchestrator context hygiene*; Task 7's
kit citation is specified to land **immediately after Task 6's paragraph**; Task 8
extends the return-contract block in the same section. Task 7 depends on Task 6 by
construction, and Task 8 contends with both. Worktrees do not help — Rule 6 and the
sdd skill both require disjoint `Files:` sets, and a conflict's own remedy is
"abort, redo that task alone on the merged head".

**But the real finding is that they are one change.** All three add a requirement to
the same object — **what a dispatch brief must carry**:

- L-05: derive, don't restate — name the symbol or the regenerating command, never
  a count, a line number, a signature or a file list.
- L-06: cite `kit.md` by path, so 48 tasks stop rebuilding one harness.
- P-03: carry the ticket/issue key, because every task in a run commits.

They were three tasks only because the audit listed three findings. One agent, one
commit, one review round — and the contract stays coherent instead of being
assembled by three authors who cannot see each other's edits.

**Task count 10 → 8.** Removes two file-contention pairs and two review rounds.

**Scope of the merged task (was 6, 7, 8):**
- Create `templates/kit.md`; add it to the run-directory tree in both
  `SKILL.md` and `references/run-state.md`; write it at GATE 2, not at Stage 1
  (it cannot be filled before the plan names the gates).
- Add Rule 5b beside Rule 5 in `SKILL.md`, and apply it to this skill's own
  restated counts.
- Add the ticket/issue-key question to Stage 1's first round, seed it in
  `templates/register.md`, and put the key in the return contract.
- One dispatch-contract paragraph in *Orchestrator context hygiene* carrying all
  three requirements, rather than three paragraphs appended in sequence.
- Hold whatever is holdable with an arm and a mutant, per the precedent Tasks 3-5
  set: a rule this skill states but no arm holds is deletable with green gates.
