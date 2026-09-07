# Pipeline Phase State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans —
> or equivalent direct execution of this approved plan — to implement it
> task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Do not execute this migration with `superpowers:subagent-driven-development`.**
> This plan exists to remove the `task → task review → fix → re-review` pattern
> from pipeline's Stage 4. Reproducing that same pattern in order to carry out
> the removal spends exactly the cost the work is about, and it is unnecessary
> here: every task below already carries a *mechanical* gate — its linter arm
> goes RED before the change and GREEN after, with a mutant proving the arm can
> fail — so the per-task verification is done by the gate, not by a reviewer
> agent. Execute the migration as one coherent change:
>
> ```
> approved plan
> → execute the planned work
> → mechanical RED/GREEN verification throughout
> → complete, coherent migration
> → whole-change review (Phase 5)
> → all reviewer reports return, then consolidate
> → migration fix plan → fixes → focused re-review
> → final verification → completion
> ```
>
> The single LLM review of this work is **Phase 5**, over the whole change. There
> is no per-task reviewer at any point in executing this plan.
>
> This paragraph governs **how this plan is executed only**. It does not touch
> the plan's own historical analysis of why pipeline's Stage 4 no longer
> delegates to `subagent-driven-development` — Task 2's
> `references/implement.md`, Task 3's composed-skills note and Task 10's linter
> comment keep that reasoning verbatim, because a future editor needs it to
> avoid re-adding the delegation.

**Goal:** Make `superb:pipeline` execute and accept work one phase at a time, so
completing an implementation task never dispatches a reviewer and no phase can
advance until its review and fix loop have closed.

**Architecture:** Stage 4 stops delegating implementation to
`superpowers:subagent-driven-development` — which has no implementation-only
mode, is phase-unaware, and adds an uncapped per-task review/fix/re-review loop
— and gains a pipeline-owned implementation-only executor. Stage 4 becomes an
explicit per-phase state machine (IMPLEMENT → REVIEW → DECIDE → FIX_PLAN →
FIX_IMPLEMENT → RE_REVIEW → PASS → NEXT) whose register is the run's
`progress.md`. Remediation gains a required fix-plan artifact. The integration
reviewer becomes conditional on a declared boundary. Every mechanisable rule
gets a `tools/check-plugin.py` arm plus a mutant proving that arm can fail.

**Tech Stack:** Markdown skill prose; Python 3 (`tools/check-plugin.py`, stdlib
only — no PyYAML); POSIX `sh`/`awk` (`scripts/task-brief`); Bash mutation
harness (`tools/check-plugin-mutants.sh`); GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-07-pipeline-phase-state-machine-design.md`

## Global Constraints

- **Never push, publish, merge, or open a PR.** Commit to the working branch only.
- **No unrelated changes.** Do not touch `superb:craft`, `superb:bug-investigate`,
  `superb:setup`, or `plugins/superb/skills/craft/ui/`. `superb:bug-fix` is edited
  only where this plan names it.
- **Never edit anything outside this repository.** In particular
  `~/.claude/skills/subagent-driven-development/` and the superpowers plugin
  cache are out of scope and must not be modified.
- `tools/check-plugin.py` is **stdlib-only**; PyYAML is not guaranteed present.
- **Every new linter arm cites its mutants by name** in a `# Mutants: "..."`
  comment, and every cited name must exist as a `run_mutant "<name>"` in
  `tools/check-plugin-mutants.sh` — `check-plugin.py:1858-1893` fails the build
  on a dangling citation.
- **New `run_mutant` blocks go immediately BEFORE the harness's summary block**
  — the `echo "killed=$PASS survived=$SURV"` lines and the `exit 1` under them,
  at the end of `tools/check-plugin-mutants.sh`. Appending to the end of the
  file instead puts them after the verdict: their kills go uncounted, and if any
  earlier mutant survived, the `exit 1` means they never run at all. Verify
  placement with
  `grep -n 'run_mutant \"<your name>\"\|killed=\$PASS' tools/check-plugin-mutants.sh`
  — every new name must have a lower line number than the summary — and run
  `bash -n tools/check-plugin-mutants.sh` before running the harness.
- **Re-wrapping prose can silently neuter a mutant.** Linter *arms* match
  whitespace-flattened text, so a reflow never breaks them — but the mutants in
  `tools/check-plugin-mutants.sh` match **raw** text, and several anchor on a
  whole sentence sitting on one line. Reflow such a sentence and its mutant
  degrades to a no-op, which the harness reports as `SURVIVED` (a red build)
  rather than as a hole in a gate. After editing any paragraph a mutant anchors
  on, run the harness and read its `SURVIVED` diagnostics — and **never pipe the
  harness through `tail`**, which is what hid the diagnostic the first time this
  happened. Measured: rewrapping the Overview's
  `` `templates/` holds the run-state file templates. `` sentence survived
  `"template count reintroduced into SKILL.md"`.
- **New linter arms that call `relpath` must sit after its definition**
  (`tools/check-plugin.py:1285`). The natural seam is immediately after the
  `== pipeline review-line examples ==` section's closing `ok(...)`, which is
  where Task 1 puts the first one; put later unconditional arms beside it.
  An arm placed above `def relpath` raises `NameError` on its first FAIL.
- **Arm before fix.** For every mechanisable rule: add the arm, watch
  `./tools/check-plugin.sh` go **FAIL** against the un-fixed repo, then make the
  change, then watch it **PASS**. Then add the mutant and watch it print
  `killed`.
- Run fixtures under `tools/fixtures/` must be **conforming** (green) on a clean
  copy; the mutant harness asserts that before every run-mode mutant.
- The plugin version is bumped **once**, in Task 11, in both
  `plugins/superb/.claude-plugin/plugin.json` and
  `plugins/superb/.codex-plugin/plugin.json`.
- Preserve every existing anti-regression rule: `RV` as a tracker line, its
  evidence fields, slice coverage of the whole phase diff, the convergence rule,
  the recursion depth cap (2) and the fix-loop iteration cap (5). Cost reduction
  comes from deleting the duplicated task layer, never from thinning the phase
  gate.
- Verification command for nearly every task: `./tools/check-plugin.sh` then
  `./tools/check-plugin.sh --run tools/fixtures/run-ok` then
  `./tools/check-plugin-mutants.sh`.
- **Model tiers are chosen per dispatch, never defaulted** — the policy is
  `references/implement.md`, *Choosing the model*. No file this plan writes may
  instruct an orchestrator to use "the most capable model available"
  unconditionally. Phase 5's reviewers are the deliberate top-tier exception.

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `plugins/superb/skills/pipeline/references/implement.md` | The implementation-only executor: how a phase's tasks are dispatched, waved, merged, and recorded — and the prohibition on dispatching a reviewer when a task completes. Replaces the SDD delegation. |
| `plugins/superb/skills/pipeline/templates/implementer-prompt.md` | The implementation-agent dispatch payload. TDD, quality gates, self-check, commit, thin return. Nothing about review. |
| `plugins/superb/skills/pipeline/templates/fix-plan.md` | The fix-plan artifact written before any fix dispatch. |
| `plugins/superb/skills/pipeline/scripts/task-brief` | Pipeline-owned extraction of one `Task N` block from a sub-plan, replacing bare relative citations of SDD's script. |
| `tools/fixtures/run-open-rv/` | Conforming run: all tasks `[x]`, `RV` `[ ]`. Proves resume-after-implementation and the review-not-early arm's happy path. |
| `tools/fixtures/run-fixloop/` | Conforming run: `RV` `[x]` round 1 with an open blocking F-ID and an existing fix plan. Proves resume-during-fix-loop and the fix-plan arm's happy path. |

**Modified**

| Path | Change |
|---|---|
| `plugins/superb/skills/pipeline/SKILL.md` | Stage 4 rewritten as the state machine (`:687-742`); stage digraph (`:518-547`); `RV` regime table + `i` rule (`:206-222`); fan-out section (`:870-908`); the "nothing substitutes" paragraph (`:979-981`); Rule 6 (`:461-486`); rationalization + red-flag rows; composed skills (`:1155-1160`) |
| `plugins/superb/skills/pipeline/references/fix-loop.md` | Per-phase loop steps 1–4 (`:6-148`); the re-tag rule (`:77-79`); the fix loop (`:300-419`); re-review fan-out (`:420-490`); invariants (`:525-593`) |
| `plugins/superb/skills/pipeline/references/parallel.md` | Wave execution (`:72-138`) — per-task review deleted; script citations corrected |
| `plugins/superb/skills/pipeline/references/run-state.md` | `RV` closure grammar gains `fixplan` (`:78-124`); resume precedence table (`:163-213`) |
| `plugins/superb/skills/pipeline/templates/progress.md` | Grammar comment: `RV` fields, conditional integration, fix-plan field |
| `plugins/superb/skills/pipeline/templates/findings.md` | Re-tag mirror generalised; Counters note |
| `plugins/superb/skills/pipeline/README.md` | Fan-out and loop description |
| `README.md` | The per-task review promise (`:143-147`); Stage→skill table (`:207`); dependency note (`:213`) |
| `plugins/superb/README.md` | Pipeline one-liner (`:10`) |
| `tools/check-plugin.py` | New arms: no-task-review sweep, no-SDD-implementation sweep, review-not-early, no-advance, fix-plan-precedes-fix, conditional integration; SDD attribution in the tier arm updated |
| `tools/check-plugin-mutants.sh` | `enable_run` parameterised; new mutants for each new arm |
| `.github/workflows/checks.yml` | `--run` over the two new fixtures |
| `plugins/superb/.claude-plugin/plugin.json`, `plugins/superb/.codex-plugin/plugin.json` | version `0.12.0` |

---

## Phase Overview

| Phase | Tasks | Deliverable |
|---|---|---|
| 1 — the implementation-only primitive | 1, 2, 3 | Pipeline dispatches implementers itself; SDD is gone from Stage 4; two sweeps prove it |
| 2 — the state machine | 4, 5, 6 | Stage 4 is explicit states; fix planning is required; the integration reviewer is conditional |
| 3 — mechanical enforcement | 7, 8, 9 | Arms + fixtures for review-not-early, no-advance, and both resume cases |
| 4 — cleanup and release | 10, 11 | Fix-agent sizing, re-tag generalisation, docs, version, final sweep |
| 5 — whole-change review | 12, 13 | One coherent LLM review of the finished migration, then its own consolidate → fix plan → fixes → focused re-review → acceptance |

---
# Phase 1 — The implementation-only primitive

Goal: pipeline dispatches its own implementers, and nothing in its files
delegates implementation to `subagent-driven-development` or asks for a review
when a task completes.

---

### Task 1: Pipeline-owned `task-brief` and implementer prompt

Pipeline has no `scripts/` directory today, and `references/parallel.md:93,126`
cite `scripts/task-brief` / `scripts/review-package` bare and relative — they
belong to SDD and never resolved from the file citing them. This task gives
pipeline the one script it actually needs. `review-package` is not replaced: it
existed only to feed the per-task reviewer, which Task 3 deletes.

**Files:**
- Create: `plugins/superb/skills/pipeline/scripts/task-brief`
- Create: `plugins/superb/skills/pipeline/templates/implementer-prompt.md`
- Modify: `tools/check-plugin.py` — add the "pipeline owns its dispatch scripts" arm
- Modify: `tools/check-plugin-mutants.sh` — add its mutants

**Interfaces:**
- Produces: `scripts/task-brief <plan-file> <task-number>` → the task block on
  stdout; exit `0` on success, `2` on usage/IO error, `3` when no such task
  heading exists. Task 2's `references/implement.md` cites it by this contract.
- Produces: `templates/implementer-prompt.md` — the payload Task 2's executor
  fills in per dispatch.

- [ ] **Step 1: Write the failing gate arm**

Insert into `tools/check-plugin.py` immediately before the
`print("\n== pipeline review-line examples ==")` line (currently `:1202`):

```python
# ---- pipeline dispatches implementation itself, so it owns the scripts ----
# The skill used to cite `scripts/task-brief` and `scripts/review-package` bare
# and relative while owning neither: they are `subagent-driven-development`
# internals, so the paths resolved from nothing the citing file could see, and
# an upstream rename would go unnoticed on a green build. Now that Stage 4
# dispatches implementers itself, the brief extractor is pipeline's own file and
# is checked like one: present, executable, and with a shebang, because a
# non-executable script fails at the first dispatch of a run.
# Mutants: "pipeline task-brief script is missing",
#          "pipeline task-brief script is not executable",
#          "pipeline task-brief script loses its shebang".
print("\n== pipeline dispatch scripts ==")
_tb = ROOT / "plugins/superb/skills/pipeline/scripts/task-brief"
if not _tb.is_file():
    bad(f"{relpath(_tb)} does not exist — Stage 4 dispatches implementers "
        "itself and cites this script for the task brief, so every dispatch of "
        "every run fails at its first step. REMEDY: add the script, or stop "
        "citing it")
else:
    _tbt, _tbe = read(_tb)
    if _tbe:
        bad(f"{relpath(_tb)} cannot be read: {_tbe}")
    elif not _tbt.startswith("#!"):
        bad(f"{relpath(_tb)} has no shebang — it is invoked as a command, not "
            "sourced, so without one the kernel's fallback decides which shell "
            "runs it. REMEDY: start the file with `#!/bin/sh`")
    elif not (_tb.stat().st_mode & 0o111):
        bad(f"{relpath(_tb)} is not executable — a dispatch citing it gets "
            "'permission denied' at the first task of the phase. REMEDY: "
            "`chmod +x` it and commit the mode bit")
    else:
        ok("pipeline owns an executable task-brief script")
```

- [ ] **Step 2: Run the gate to verify it fails**

Run: `./tools/check-plugin.sh 2>&1 | grep -A3 'dispatch scripts'`
Expected: `FAIL  plugins/superb/skills/pipeline/scripts/task-brief does not exist`
and the final line `check-plugin: FAIL`.

- [ ] **Step 3: Write the script**

Create `plugins/superb/skills/pipeline/scripts/task-brief`:

````sh
#!/bin/sh
# task-brief <plan-file> <task-number>
#
# Prints the `## Task <n>` block of a plan: its heading and everything under it,
# up to the next heading at the same or a shallower level. Fence-aware: a line
# starting with a hash inside a fenced code block is content, not a heading, and
# a fence closes only on a marker of its own character and at least its own
# length, so the nested fences a plan's task blocks carry do not end it early.
#
# Exit 0 with the block on stdout; 2 on a usage or IO error; 3 when the plan has
# no such task. 3 is separate on purpose: an empty brief on exit 0 is how an
# implementer gets dispatched with no requirements and invents its own.
set -eu

if [ $# -ne 2 ]; then
  echo "usage: task-brief <plan-file> <task-number>" >&2
  exit 2
fi
plan=$1
want=$2
if [ ! -f "$plan" ]; then
  echo "task-brief: not a file: $plan" >&2
  exit 2
fi
case $want in
  '' | *[!0-9]*)
    echo "task-brief: task number must be digits, got: $want" >&2
    exit 2
    ;;
esac

out=$(awk -v want="$want" '
  function level(s,   n) { n = 0; while (substr(s, n + 1, 1) == "#") n++; return n }
  /^[ \t]*(`{3,}|~{3,})/ {
    ln = $0; sub(/^[ \t]*/, "", ln)
    ch = substr(ln, 1, 1); n = 0
    while (substr(ln, n + 1, 1) == ch) n++
    if (!fence) { fence = 1; fch = ch; flen = n }
    else if (ch == fch && n >= flen) { fence = 0 }
    if (inblk) print
    next
  }
  !fence && /^#+[ \t]*[Tt]ask[ \t]+[0-9]+/ {
    num = $0
    sub(/^#+[ \t]*[Tt]ask[ \t]+/, "", num)
    sub(/[^0-9].*$/, "", num)
    if (num + 0 == want + 0) { inblk = 1; lvl = level($0); print; next }
    if (inblk && level($0) <= lvl) inblk = 0
    next
  }
  !fence && inblk && /^#+[ \t]/ { if (level($0) <= lvl) { inblk = 0; next } }
  inblk { print }
' "$plan")

if [ -z "$out" ]; then
  echo "task-brief: $plan has no 'Task $want' heading" >&2
  exit 3
fi
printf '%s\n' "$out"
````

Then: `chmod +x plugins/superb/skills/pipeline/scripts/task-brief`

- [ ] **Step 4: Run the gate to verify it passes**

Run: `./tools/check-plugin.sh 2>&1 | grep -A2 'dispatch scripts'`
Expected: `ok    pipeline owns an executable task-brief script`

- [ ] **Step 5: Smoke-test the script against this plan file**

```bash
S=plugins/superb/skills/pipeline/scripts/task-brief
P=docs/superpowers/plans/2026-09-07-pipeline-phase-state-machine.md
"$S" "$P" 1 | head -1                 # expect: ### Task 1: Pipeline-owned `task-brief` and implementer prompt
"$S" "$P" 1 | grep -c '^### Task 2'   # expect: 0  (the block stops at the next task)
"$S" "$P" 99 ; echo "exit=$?"         # expect: exit=3 and a message on stderr
"$S" "$P"    ; echo "exit=$?"         # expect: exit=2 usage
"$S" /nope 1 ; echo "exit=$?"         # expect: exit=2 not a file
```

All five expectations must hold before continuing. They were verified against
this plan file itself while it was written — `task-brief <this plan> 1` returns
Task 1's block, stops before `### Task 2`, and keeps the four-backtick template
block inside it intact — so a failure here is a transcription error in the
script, not an unknown.

- [ ] **Step 6: Write the implementer prompt template**

Create `plugins/superb/skills/pipeline/templates/implementer-prompt.md`:

````markdown
<!-- Template. Copy into a dispatch and fill every <angle-bracket> slot.
     This is an IMPLEMENTATION-ONLY payload: it never asks the agent to review
     anything, and completing it never causes a reviewer to be dispatched. The
     phase's review is a separate state (`RV`) that begins only once every task
     in the phase has landed. -->

Subagent: general-purpose
Model: <choose explicitly based on this task's complexity — see
       `references/implement.md`, *Choosing the model*. Name the tier and the
       reason in one clause; do not leave this slot on a default.>
Working directory: <the phase worktree, or this wave member's worktree>

## Your task

Read `<run-dir>/../plans/<sub-plan>.md` Task `<n>` first — it is your
requirements, and its exact values (names, signatures, magic strings, test
cases) are to be used verbatim. Get it with:

```
plugins/superb/skills/pipeline/scripts/task-brief <sub-plan-path> <n>
```

## Context

- Where this task fits: <one line>
- Interfaces and decisions from earlier tasks the brief cannot know: <list, or "none">
- Ambiguities in the brief and how they are resolved: <list, or "none">
- Ticket key for commit messages: <key, from kit.md>

## Quality gates

Run these; they are in `<run-dir>/kit.md`:

- Covering tests: `<command>`
- Full suite: `<command>`
- Build/lint: `<command>`

## How to work

1. **Test first.** Write the failing test, run it, watch it fail for the right
   reason, then write the minimum code that passes it. This holds whether or not
   the brief mentions TDD. The only exemption is pure config or glue with no
   logic to assert on — if you claim it, say so in your report.
2. Implement only this task. Do not start the next one, and do not refactor
   beyond what this task needs.
3. Run the covering tests and the build gates. Get them green.
4. **Self-check** before reporting: re-read the brief and confirm every
   requirement is met; re-read your own diff for debug leftovers, TODOs,
   commented-out code, and copy that contradicts the brief's exact values.
5. **Commit** your work with the ticket key in the message. One task, one commit
   where possible; if you need more than one, they must all be on this branch.
6. Write your detail to `<run-dir>/agent-output/<label>.md`.

## If you are stuck

Ask before guessing. If the brief does not decide something you need — a name,
a contract, a behaviour — stop and report `NEEDS_CONTEXT` with the exact
question. Inventing an answer creates a finding the phase review will raise and
a fix round that costs more than the question.

If the task is bigger than its brief says, or it cannot be done as specified,
report `BLOCKED` with what you found. Do not expand scope to force it through.

## What you are NOT responsible for

Formal acceptance. Your work is reviewed later, as part of the whole phase, by
reviewers who did not write it. Do not review your own work as a substitute,
do not dispatch anything, and do not mark anything complete in the tracker —
the orchestrator owns the tracker.

## Report back

ONLY this, under 15 lines — the detail belongs in your report file:

```
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
Commits: <short hashes>
Tests: <command> → <result line>
Gates: <command> → <result line>
Concerns: <one line each, or none>
DETAIL: <run-dir>/agent-output/<label>.md
```
````

- [ ] **Step 7: Add the mutants**

Insert into `tools/check-plugin-mutants.sh` immediately **before** the summary
block (see Global Constraints — appending to the end of the file puts them
after the verdict, where their kills go uncounted):

```bash
# Pipeline dispatches implementation itself now, so its brief extractor is a
# file this repo owns and can lose. Three ways it becomes useless at the first
# dispatch of a run, each killed by its own arm.
run_mutant "pipeline task-brief script is missing" '
f=plugins/superb/skills/pipeline/scripts/task-brief
if [ ! -f "$f" ]; then
  echo "mutant is a no-op: the script is already absent"
else
  rm -f "$f"
fi'
run_mutant "pipeline task-brief script is not executable" '
f=plugins/superb/skills/pipeline/scripts/task-brief
if [ ! -x "$f" ]; then
  echo "mutant is a no-op: the script is already non-executable"
else
  chmod -x "$f"
fi'
run_mutant "pipeline task-brief script loses its shebang" '
f=plugins/superb/skills/pipeline/scripts/task-brief
if ! head -1 "$f" | grep -q "^#!"; then
  echo "mutant is a no-op: the script has no shebang to remove"
else
  sed -i "1d" "$f"
  head -1 "$f" | grep -q "^#!" && echo "mutant is a no-op: a shebang is still on line 1"
fi'
```

- [ ] **Step 8: Verify the mutants kill**

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep 'task-brief script'`
Expected: three lines, each beginning `killed`. No `SURVIVED`, and no
`mutant is a no-op` diagnostic.

- [ ] **Step 9: Commit**

```bash
git add plugins/superb/skills/pipeline/scripts/task-brief \
        plugins/superb/skills/pipeline/templates/implementer-prompt.md \
        tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "feat(pipeline): own the brief extractor and the implementer payload

Stage 4 is about to dispatch implementers itself, so the two things a
dispatch needs are pipeline's own files rather than bare relative citations
of subagent-driven-development internals. The payload is implementation-only
by construction: nothing in it asks for a review, and nothing in it can
cause one to be dispatched."
```

---

### Task 2: `references/implement.md` — the implementation-only executor

**Files:**
- Create: `plugins/superb/skills/pipeline/references/implement.md`
- Modify: `tools/check-plugin.py` — extend the reference-file existence expectations if the skill lists its references (see Step 1)

**Interfaces:**
- Consumes: `scripts/task-brief` and `templates/implementer-prompt.md` from Task 1.
- Produces: the section names Task 3 and Task 4 cite —
  `## Dispatching one task`, `## Waves`, `## What an implementation agent owns`,
  `## The no-task-review rule`, `## Leaving IMPLEMENT`.

- [ ] **Step 1: Write the reference file**

Create `plugins/superb/skills/pipeline/references/implement.md`:

````markdown
# Stage 4 — IMPLEMENT: dispatching a phase's tasks

Read at every Stage 4 implementation dispatch. This file is the whole of how
pipeline gets code written. It replaces the previous delegation to
`superpowers:subagent-driven-development`, which had no implementation-only
mode: an implementer returning `DONE` there mechanically produced a reviewer
for that task, and a task completed only at zero open findings at any severity
through an uncapped fix/re-review loop. That is a second acceptance gate for
work this skill accepts at the phase, and running both reviewed everything
twice.

## The no-task-review rule

```
COMPLETING AN IMPLEMENTATION TASK DISPATCHES NO REVIEWER.
```

During IMPLEMENT the only transition is **task → next task**. Nothing reviews a
task: no task-scoped reviewer, no task-level fix loop, no task-level re-review,
and no adversarial pass. A task's report is recorded and the next task is dispatched.

An implementation agent fixing its own compile error, failing test, syntax
error or obvious mistake is **implementation**, not the fix loop. The fix loop
is a named state that begins only after the phase's review has closed
(`references/fix-loop.md`).

This is not a cost decision. Review moved *up*, not away: the phase's `RV`
fan-out reads the whole phase diff as one unit and is the gate that accepts the
work. What was deleted is the duplicate, not the review.

## What an implementation agent owns

| Owns | Does not own |
|---|---|
| implementing one task from its brief | formal acceptance |
| writing the covering tests, test-first | reviewing its own work as a substitute for review |
| running the covering tests and the build gates | dispatching anything |
| a self-check against the brief and its own diff | writing the tracker |
| committing, with the ticket key | deciding the phase is done |
| a ≤10-line return with `DETAIL:` pointing at its report file | carrying payloads back into the orchestrator's context |

## Choosing the model

**Pick the tier from the task, and say why.** Defaulting every implementer to
the strongest model available is the same mistake as reviewing every task: it
buys nothing on work that has one correct transcription, and it is paid on every
dispatch of every phase. Choose explicitly:

| Tier | Use for |
|---|---|
| **Cheap / fast** | mechanical prose edits; transcribing a brief that already contains the exact content; simple fixtures; small deterministic changes; straightforward single-file edits |
| **Standard capable** | multi-file implementation; non-trivial scripts; linter and mutation logic; moderate debugging; wiring together interfaces that already exist |
| **Strongest available** | architecture-sensitive reasoning; subtle debugging; difficult remediation planning; whole-change review; state-machine consistency review |

Two rules on top of the table:

- **The brief's own precision is the signal.** A task whose brief carries the
  literal text to write is a transcription; a task that says what to achieve and
  leaves the shape open is not.
- **A fix agent is sized by the finding, not by the phase.** A one-line
  correction with an exact `file:line` is a cheap-tier dispatch even in a phase
  whose implementation needed the strongest tier. Remediation *planning* is the
  opposite: it reasons across findings, so it stays at the top tier.

Record the tier in the dispatch. An unnamed choice is a default, and the default
is what this rule exists to stop.

## Dispatching one task

1. **Mark the task `[~]` in `progress.md` and save, before the dispatch**
   (Rule 2). A run that dies mid-dispatch must be able to tell "dispatched"
   from "never started".
2. Build the payload from `templates/implementer-prompt.md`. Fill every slot.
   The brief comes from `scripts/task-brief <sub-plan> <n>` — pass the **path**,
   never the brief's text (Rule 5: hold pointers, not payloads).
3. Dispatch one agent. Wait for it (`SKILL.md`, *Who wakes you after a
   dispatch*).
4. On return:
   - `DONE` / `DONE_WITH_CONCERNS` → record the commit hash against the task
     line, mark it `[x]`, save. File any concern as a note for the phase review
     to read; a concern is not a finding until a reviewer raises it.
   - `NEEDS_CONTEXT` → this is the Ambiguity guard. If the approved plan settles
     it, answer and re-dispatch. If it does not, **stop and ask the user**.
   - `BLOCKED` → stop and ask the user. Do not re-dispatch the same brief.
5. **Then dispatch the next task.** Do not dispatch a reviewer.

A task whose work produced no commit records `nocommit` with the reason, as the
task-line grammar requires (`references/run-state.md`).

## Waves

Waves are the approved plan's, never inferred here (Rule 6,
`references/parallel.md`). A wave of one runs in the phase worktree. A wave of
`k ≥ 2` dispatches all `k` implementers **in one message**, each in its own
worktree and branch cut from the phase branch head, each marked `[~]` before
its own dispatch and `[x]` with its hash as it lands.

When the last member of a wave lands:

1. Merge the member branches onto the phase branch **in task order**, one
   no-fast-forward merge each, the merge message naming the task.
2. Run the build gates. **A gate failing here means the implementation is not
   finished.** Repair it inside IMPLEMENT — dispatch the repair to the task's
   own implementer, or to a fresh implementation agent scoped to the failure —
   and re-run the gate until it is green. This opens **no** formal remediation
   round: no findings are raised, no F-ID is assigned, no fix plan is written,
   no Counters row is spent, and `RV` stays `[ ]`. The formal states
   (`FIX_PLAN` → `FIX_IMPLEMENT` → `RE_REVIEW`) exist only downstream of
   REVIEW, and a failure nobody has reviewed yet cannot enter them.
3. Re-read the tracker, then dispatch the next wave.

No member is reviewed before its merge. The merge gate is the build, not a
reviewer.

## Leaving IMPLEMENT

IMPLEMENT ends — and REVIEW may begin — only when **every** implementation task
line in the phase is `[x]` with a commit hash (or a justified `nocommit`), every
wave has been merged, and the build gates are green on the phase branch.

```
A PHASE'S REVIEW MAY NOT BEGIN WHILE ANY TASK IN THAT PHASE IS UNCHECKED.
```

**There is exactly one formal remediation state machine, and it starts after
REVIEW.** A compile error, a failing test, a syntax error, an obvious mistake or
a red build gate — at any point before `RV` opens — is unfinished
implementation, repaired here and re-gated here. It is not a finding, it gets no
F-ID, it needs no fix plan, and it spends no iteration budget. Nothing before
`RV` is a fix loop; there is no pre-`RV` fix loop to enter.

This does not soften the exit condition. IMPLEMENT still ends only when the work
has landed **and** the required build and test gates are green — a red gate
keeps the phase in IMPLEMENT rather than routing it somewhere else.

Reviewing early splits the phase into pieces and re-creates the task-scoped
gate by another name. If the phase is too big to review as a unit, that is
Rule 3's 12-task cap and a split at the *plan* level, not an early review.
````

- [ ] **Step 2: Verify the reference is reachable from the skill**

`SKILL.md`'s Overview (`:9-26`) carries the reference-file map. Add the new file
to it, replacing nothing else yet:

```bash
grep -n 'references/fix-loop.md' plugins/superb/skills/pipeline/SKILL.md | head -3
```

Then edit the Overview's reference list so it reads (keeping the existing
entries and their order, inserting `implement.md` before `fix-loop.md`):

```markdown
- `references/implement.md` — Stage 4's IMPLEMENT state: how a phase's tasks
  are dispatched, waved and merged, and why completing one dispatches no
  reviewer.
```

- [ ] **Step 3: Run the gate**

Run: `./tools/check-plugin.sh`
Expected: `check-plugin: PASS`. (The linter's cross-file phrase arms read the
pipeline directory's `*.md` recursively, so a new reference file must not break
the `RV`-grammar examples arm — confirm no new `FAIL` line mentions
`implement.md`.)

- [ ] **Step 4: Commit**

```bash
git add plugins/superb/skills/pipeline/references/implement.md \
        plugins/superb/skills/pipeline/SKILL.md
git commit -m "feat(pipeline): an implementation-only executor of its own

Stage 4's IMPLEMENT state now has a file that says what an implementation
dispatch is and, decisively, what it is not: completing a task dispatches no
reviewer, and review begins only when every task in the phase has landed."
```

---

### Task 3: Cut the SDD delegation and the per-task review, and prove it

This is the change that makes the invariant mechanical. Two sweeps go in first
and both go RED against the current repo.

**Files:**
- Modify: `plugins/superb/skills/pipeline/SKILL.md:693`, `:473-476`, `:979-981`, `:1155-1160`
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:15-25`
- Modify: `plugins/superb/skills/pipeline/references/parallel.md:72-138`
- Modify: `tools/check-plugin.py` — two new sweeps
- Modify: `tools/check-plugin-mutants.sh` — their mutants

**Interfaces:**
- Consumes: `references/implement.md`'s section names from Task 2.
- Produces: the two sweeps every later task must keep green.

- [ ] **Step 1: Write the two failing sweeps**

Insert into `tools/check-plugin.py` immediately after the
`== pipeline dispatch scripts ==` block from Task 1:

```python
# ---- pipeline never asks for a review when one task completes ----
# Pipeline's own review layer is the phase-level `RV` fan-out. It used also to
# delegate implementation to `subagent-driven-development`, whose process is
# implement -> task reviewer -> fix -> re-review per task with no
# implementation-only mode, and to import that loop explicitly into its wave
# path ("run its per-task review ... exactly as subagent-driven-development
# prescribes"). Two acceptance gates for one body of work reviewed everything
# twice and made a phase something other than the unit of acceptance. Both
# sweeps are text sweeps because the rule is contractual prose: the failure mode
# is a sentence coming back, and a sentence is what is checked.
#
# SCOPED to the pipeline skill. `bug-fix` may still prefer
# `superpowers:subagent-driven-development` at its own task scope, where SDD's
# per-task contract is the correct one; it has no phase gate to mis-gate.
# EXPIRY: revisit if another skill acquires a phase-advancement condition.
# Mutants: "pipeline delegates phase implementation to sdd",
#          "pipeline asks for a per-task review",
#          "pipeline gates a merge on passing task review".
print("\n== pipeline has no task-level review ==")
_pdir = ROOT / "plugins/superb/skills/pipeline"
_banned = [
    (re.compile(r"per-task review", re.I),
     "asks for a per-task review"),
    (re.compile(r"passed (?:its )?task review", re.I),
     "gates something on a task having passed review"),
    (re.compile(r"\btask reviewer\b", re.I),
     "names a task reviewer"),
    (re.compile(r"(?:[Ii]mplement|dispatch)[^.\n]{0,80}?\bvia\b[^.\n]{0,40}?"
                r"subagent-driven-development", re.I),
     "delegates implementation to subagent-driven-development"),
]
_hits = []
for _f in sorted(_pdir.rglob("*.md")):
    _t, _e = read(_f)
    if _e:
        continue
    _flat = " ".join(_t.split())
    for _rx, _why in _banned:
        _m = _rx.search(_flat)
        if _m:
            _hits.append(f"{relpath(_f)} {_why}: {_m.group(0)!r}")
if _hits:
    for _h in _hits:
        bad(_h + " — a task completing must dispatch no reviewer, and Stage 4's "
            "IMPLEMENT state must not hand implementation to a skill whose "
            "process reviews every task. REMEDY: state the rule the way "
            "references/implement.md does, and let the phase's `RV` fan-out be "
            "the only code review in the loop")
else:
    ok("no file in the pipeline skill asks for a task-level review or "
       "delegates phase implementation to subagent-driven-development")
```

Note the deliberate asymmetry: the sweep bans *delegating implementation* to
SDD, not every mention of it. `references/implement.md` explains why the
delegation was removed and must be allowed to name the skill it replaced.

- [ ] **Step 2: Run the sweeps to verify they fail**

Run: `./tools/check-plugin.sh 2>&1 | grep -A4 'no task-level review'`
Expected: `FAIL` lines naming at least
`plugins/superb/skills/pipeline/references/parallel.md`,
`plugins/superb/skills/pipeline/references/fix-loop.md`, and
`plugins/superb/skills/pipeline/SKILL.md`, and `check-plugin: FAIL`.

Record the exact list — every one of them is edited below.

- [ ] **Step 3: Rewrite `parallel.md`'s wave execution**

In `plugins/superb/skills/pipeline/references/parallel.md`, replace the
per-task-review steps (currently steps 5 and 6 at `:98-104`) with:

```markdown
5. As each member returns, record it: commit hash against its task line, `[x]`,
   saved (Rule 2). A member returning `NEEDS_CONTEXT` or `BLOCKED` is a
   guard-rail stop, not a finding. **Dispatch no reviewer** — the phase's `RV`
   fan-out reviews all of this work as one unit once the phase's last task has
   landed (`references/implement.md`, *The no-task-review rule*).
6. When every member has landed, **merge in task order** onto `P`, one
   no-fast-forward merge per member, each merge message naming the task
   (`merge T4 — <task name>`). Then run the build gates. The merge gate is the
   build, not a reviewer; a gate failing here means this wave's implementation
   is not finished, so it is repaired inside IMPLEMENT and the gate re-run. It
   raises no finding and opens no remediation round.
```

Then fix the bare script citation at `:93` — replace `scripts/task-brief` with
`plugins/superb/skills/pipeline/scripts/task-brief`, and delete the
`scripts/review-package` citation at `:126` along with the per-task review
package it fed. Also update `:77-78`'s "Wave of one — dispatch in the phase
worktree exactly as `subagent-driven-development` describes. Nothing below
applies." to:

```markdown
**Wave of one** — dispatch in the phase worktree as
`references/implement.md`, *Dispatching one task*, describes. Nothing below
applies.
```

- [ ] **Step 4: Rewrite `fix-loop.md`'s step 1**

Replace `references/fix-loop.md:15-20` (the "Implement … via
`superpowers:subagent-driven-development` … merges them in task order when all
have passed task review" block) with:

```markdown
1. **Implement** the phase, wave by wave, per `references/implement.md`,
   following the wave table the user approved (Rule 6, `parallel.md`). A wave of
   one runs in the phase worktree; a wave of `k >= 2` dispatches all `k`
   implementers in one message, each in its own worktree and branch, and merges
   them in task order **when all have landed and the build gates are green**.
   Around **each individual task**: mark it `[~]` with a
```

(keep the remainder of the sentence as it stands.)

- [ ] **Step 5: Rewrite `SKILL.md`'s Stage 4 step 1 and Rule 6**

At `SKILL.md:693`, replace `1. **Implement wave by wave** via
`superpowers:subagent-driven-development`.` with:

```markdown
1. **Implement wave by wave** per `references/implement.md`. Completing a task
   dispatches no reviewer.
```

At `SKILL.md:473-476`, replace "members are reviewed per task exactly as
`subagent-driven-development` prescribes, then merged back in task order" with:

```markdown
  members land independently and are merged back in task order once all of them
  have landed and the build gates are green; no member is reviewed before its
  merge.
```

At `SKILL.md:979-981`, the "Nothing substitutes for the fan-out" list cites
"per-task review inside `subagent-driven-development`" as an evidence source
that no longer exists. Replace that list item with:

```markdown
implementer self-reports and their own mutation tests, a green suite, Stage 1b's
design pressure-test, an implementer's own self-check, your own read of the diff
```

- [ ] **Step 6: Update the composed-skills roster**

At `SKILL.md:1155-1160`, remove `superpowers:subagent-driven-development` from
the list and add a line recording why, so a future editor does not re-add it:

```markdown
`superpowers:subagent-driven-development` is deliberately **not** composed here.
It has no implementation-only mode — an implementer returning `DONE` dispatches
a reviewer for that task, and a task completes only at zero open findings at any
severity
through an uncapped fix/re-review loop — and it is phase-unaware. Stage 4's
IMPLEMENT state is `references/implement.md` instead.
```

- [ ] **Step 6b: Drop the banned phrase from the re-tag rule**

Two files outside this task's own edits still carry `task reviewer`, and the
sweep reads every `.md` in the skill — so they close here, or the gate stays red
from this commit until Task 10. Only the **phrase** moves now; Task 10 still
owns the rule's generalisation and its linter comment.

- `references/fix-loop.md:77-79` — replace the attribution clause so the rule
  stops naming a caller pipeline no longer invokes:

```markdown
     vocabulary is re-tagged here, never carried: a reviewer may emit
     **Important**, whose usual contract is "fix everything before this unit
     completes" — right for one task's diff, wrong for a phase, and it
```

  Keep the rest of the sentence and the predicate below it byte-identical: the
  linter holds this text across `fix-loop.md` and `templates/findings.md`.

- `templates/findings.md:35` — the mirror of the same rule. Replace
  ```Important` is the task reviewer's vocabulary, not a tier`` with
  ```Important` is another reviewer's vocabulary, not a tier``, leaving the rest
  of the sentence as it stands.

Both edits are the phrase only. The rule still holds, still re-tags, and still
has its predicate — a reviewer emitting `Important` is a real thing whoever
supplies it, which is why Task 10 keeps the rule rather than deleting it.

- [ ] **Step 7: Run the sweeps to verify they pass**

Run: `./tools/check-plugin.sh 2>&1 | grep -A2 'no task-level review'`
Expected: `ok    no file in the pipeline skill asks for a task-level review …`

Then the whole gate: `./tools/check-plugin.sh && ./tools/check-plugin.sh --run tools/fixtures/run-ok`
Expected: `check-plugin: PASS` twice.

- [ ] **Step 8: Add the mutants**

Insert into `tools/check-plugin-mutants.sh`, before the summary block:

```bash
# The three shapes the deleted per-task loop comes back in. Each re-introduces
# one sentence, which is exactly how it got in the first time.
run_mutant "pipeline delegates phase implementation to sdd" '
f=plugins/superb/skills/pipeline/references/fix-loop.md
if ! grep -qF "per \`references/implement.md\`" "$f"; then
  echo "mutant is a no-op: step 1 no longer points at references/implement.md"
else
  sed -i "s|per \`references/implement.md\`|via \`superpowers:subagent-driven-development\`|" "$f"
  grep -qF "via \`superpowers:subagent-driven-development\`" "$f" || echo "mutant is a no-op: the delegation was not re-introduced"
fi'
run_mutant "pipeline asks for a per-task review" '
f=plugins/superb/skills/pipeline/references/parallel.md
if ! grep -qF "Dispatch no reviewer" "$f"; then
  echo "mutant is a no-op: the no-reviewer sentence is already gone"
else
  sed -i "s|Dispatch no reviewer|Run its per-task review|" "$f"
  grep -qF "Run its per-task review" "$f" || echo "mutant is a no-op: the per-task review sentence was not re-introduced"
fi'
run_mutant "pipeline gates a merge on passing task review" '
f=plugins/superb/skills/pipeline/references/parallel.md
if ! grep -qF "when every member has landed" "$f" && ! grep -qF "When every member has landed" "$f"; then
  echo "mutant is a no-op: the landing-based merge gate is not phrased as expected"
else
  sed -i "s|[Ww]hen every member has landed|When every member has passed its task review|" "$f"
  grep -qF "passed its task review" "$f" || echo "mutant is a no-op: the task-review merge gate was not re-introduced"
fi'
```

- [ ] **Step 9: Verify the mutants kill**

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep -E 'sdd|per-task review|task review'`
Expected: every line begins `killed`; no `SURVIVED`, no `no-op` diagnostic.

- [ ] **Step 10: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "fix(pipeline): one code review in the loop, and it is the phase's

Stage 4 dispatched implementation through subagent-driven-development, whose
process is implement -> task reviewer -> fix -> re-review per task with no
implementation-only mode, and parallel.md imported that loop explicitly. So
every phase was accepted twice: once per task by a skill whose blocking
contract is task-scoped, once as a phase by the RV fan-out. The per-task layer
is gone, IMPLEMENT is pipeline's own, and a text sweep with three mutants
keeps the sentences from coming back."
```

---
# Phase 2 — The state machine

Goal: Stage 4 is written as named states with entry and exit conditions,
remediation is planned before it is implemented, and the integration reviewer is
spent only where there is an integration boundary to cover.

---

### Task 4: Rewrite Stage 4 as an explicit per-phase state machine

**Files:**
- Modify: `plugins/superb/skills/pipeline/SKILL.md:687-742` (Stage 4)
- Modify: `plugins/superb/skills/pipeline/SKILL.md:518-547` (stage digraph)
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:6-148` (per-phase loop headings)

**Interfaces:**
- Consumes: `references/implement.md`'s IMPLEMENT contract (Task 2).
- Produces: the state names every later task and gate cites —
  `IMPLEMENT`, `REVIEW`, `DECIDE`, `FIX_PLAN`, `FIX_IMPLEMENT`, `RE_REVIEW`,
  `PASS`, `NEXT_PHASE`.

- [ ] **Step 1: Replace Stage 4's body**

In `SKILL.md`, replace the whole of `### Stage 4 — Autonomous per-phase loop`
(currently `:687-742`, ending just before
`### The Continuation Law (no stopping without a question)`) with:

````markdown
### Stage 4 — Autonomous per-phase loop

For each phase — in dependency order, independent phases concurrently as lanes
— see `references/fix-loop.md`. **A phase is a transaction:** it is the unit of
execution and the unit of acceptance, and the run stays inside it until it
passes.

```
IMPLEMENT ─► REVIEW ─► DECIDE ─┬─ no blocking findings ──────────────► PASS ─► NEXT_PHASE
                               │                                        ▲
                               └─ blocking findings                     │
                                    ▼                                   │
                                  FIX_PLAN ─► FIX_IMPLEMENT ─► RE_REVIEW┤
                                    ▲                                   │
                                    └──────── blocking findings remain ─┘
```

**0. Read the tracker in full** — first action of the phase, before any dispatch
— and reconcile any `[~]` line (Rule 4). It, not your memory, names the phase,
its state, and its next open line.

**IMPLEMENT** — `references/implement.md`.
Dispatch every task in the phase, wave by wave per the approved wave table.
Mark each `[~]` before its dispatch and `[x]` with its commit hash as it lands
(Rule 2). Merge each wave in task order and run the build gates.
```
COMPLETING AN IMPLEMENTATION TASK DISPATCHES NO REVIEWER.
```
The only transition here is task → next task. An implementer fixing its own
compile error, failing test or obvious mistake is implementation, not the fix
loop — and so is a red build gate after a wave merge: it means the
implementation is not finished, so it is repaired here and re-gated here. **No
remediation round opens before `RV`.** No finding, no F-ID, no fix plan, no
Counters row; the formal states begin only where REVIEW leaves off.
*Exit:* every task line in the phase `[x]` with a hash (or a justified
`nocommit`), every wave merged, build gates green.

**REVIEW** — the phase's `RV` line.
Mark `RV` `[~]` **and save first** — it is a tracker line and Rule 2 governs it.
`N` = the phase's task count → dispatch the slice reviewers in parallel:
`ceil(N/5)` for an **unwaved** phase, one per wave or adjacent wave-pair for a
**waved** one (recorded as `waved` on the line, since a wave is never split
across two reviewers). Each owns an exact **commit range** from the tracker's
hashes, each runs the repo `/review` skill, each returns a report file even when
it finds nothing. Add an integration reviewer **only at a declared integration
boundary** (see *Reviewer fan-out*). Confirm the slices cover every commit on
the phase branch, including any you wrote inline yourself. Run the test suite —
failing tests are bug findings.
```
REVIEW MAY NOT BEGIN WHILE ANY TASK IN THIS PHASE IS UNCHECKED.
ALL REVIEWERS MUST RETURN BEFORE ANY FIX IS DISPATCHED.
```
A reviewer discovers problems; it never starts a fix. Do not dispatch a fixer
because the first report came back while others are still out.
*Exit:* every dispatched reviewer has returned.

**DECIDE.**
Consolidate + dedup every report into `findings.md`, **assigning each new
finding a stable `F-NNN` ID**. **Three tiers only** — Critical / Major (=
`/review` "Warning") / Minor; ties within them resolve upward; a rediscovered
finding keeps its old ID; a finding arriving in another vocabulary is
**re-tagged** by the predicate in `references/fix-loop.md` and never carried as
a tier. Close `RV` `[x]` with those F-IDs — or `no findings` — its
`agent-output/` paths and its coverage file.
- **No Critical/Major/bug** → `PASS`. Minor findings defer to the Stage 5
  hand-off; they are not blocking and not discarded.
- **Any Critical/Major/bug** → `FIX_PLAN`. **The phase does not advance.**

**FIX_PLAN** — `references/fix-loop.md`, and required.
Write the phase's fix plan for this round to
`agent-output/p<phase>-fixplan-r<round>.md` from `templates/fix-plan.md`, and
name it on the round. Findings → fix plan → fix implementation, in that order.
No fix is dispatched before its plan is on disk.

**FIX_IMPLEMENT.**
Execute the fix plan with the **minimum reasonable number of fix agents** — one
per independent file cluster the plan names, related findings batched together.
Fix agents run the tests covering their change. They do not review their own
fixes as a substitute for `RE_REVIEW`.

**RE_REVIEW.**
Reopen `RV` to `[~]` and append this round. Size it from the **fix diff** — one
slice per file cluster, recorded as `C=<n>` — never from the finding count. The
re-review reads: whether the blocking findings were actually resolved, the fix
diff, regressions the fixes introduced, interactions between fixes, and whether
the phase now satisfies its plan. It is not a rerun of the original per-slice
structure.
- Clean → `PASS`.
- Blocking findings remain → back to `FIX_PLAN` for the next round, subject to
  the convergence rule (an ID still open after a fix run that targeted it, or a
  repeated open-ID set, stops the run with a user question — **before** the
  caps).

**PASS.**
Only with all of this true and **written and saved**: every task `[x]` with its
hash; required tests and build gates green; the phase's `RV` `[x]` carrying
every round's F-IDs or `no findings`, its `agent-output/` paths and coverage;
every fix plan the rounds name present in `agent-output/`; no open blocking F-ID
scoped to this phase; Current State pointing at the **next unchecked line**.
The `RV` condition is listed first because it is the only one an unreviewed
phase fails — the others all pass vacuously when REVIEW never ran.

For the **last sibling of a Rule 3 split**, the next unchecked line is the
split's **`RVJ`**, not the next phase: the joint review over the siblings'
combined diff runs and closes `RVJ` `[x]`, its blocking findings going through
the same fix loop, before the run advances. The last sibling's own `RV` never
substitutes for it.

**NEXT_PHASE.**
```
PASS IS THE ONLY EDGE INTO THE NEXT PHASE.

Implementation complete is not phase complete.
All task lines [x] is not phase complete.
An empty ledger is not phase complete.
```
If the fix loop cannot converge, **stop and ask the user**. A cap firing or the
convergence rule firing never licenses the next phase — those are escape
hatches out of the run, not around the gate.

Stage 4 is autonomous about **execution**, not about **requirements**: the
Ambiguity guard (below) interrupts the run whenever the plan doesn't decide
something. "No user stops" means no routine check-ins — it has never meant
"guess instead of asking".
````

- [ ] **Step 2: Update the stage digraph**

In `SKILL.md`'s `## Stage flow` digraph (`:518-547`), replace the single
`Stage 4` node and its self-referencing edges with the phase states, keeping
every other node and edge byte-identical. Replace these three lines —

```
    "Stage 4: autonomous loop — lanes of phases, waves of tasks (ambiguity -> ask)" [shape=box];
```
```
    "GATE 2: approve expanded plan (register must be empty)" -> "Stage 4: autonomous loop — lanes of phases, waves of tasks (ambiguity -> ask)" [label="approved"];
    "Stage 4: autonomous loop — lanes of phases, waves of tasks (ambiguity -> ask)" -> "Stage 4b: joint integration review over a split's combined diff" [label="last sibling of a split"];
    "Stage 4b: joint integration review over a split's combined diff" -> "Stage 4: autonomous loop — lanes of phases, waves of tasks (ambiguity -> ask)" [label="findings / next phase"];
    "Stage 4: autonomous loop — lanes of phases, waves of tasks (ambiguity -> ask)" -> "Stage 5: finishing-a-development-branch" [label="all phases done"];
```

— with:

```
    "Stage 4 IMPLEMENT: every task in the phase, waves of tasks (ambiguity -> ask)" [shape=box];
    "Stage 4 REVIEW: RV fan-out over the whole phase diff (all reviewers return first)" [shape=box];
    "Stage 4 DECIDE: consolidate, dedup, F-IDs, tiers" [shape=diamond];
    "Stage 4 FIX_PLAN: one scoped fix plan for this round's blocking findings" [shape=box];
    "Stage 4 FIX_IMPLEMENT: fix agents, one per file cluster" [shape=box];
    "Stage 4 RE_REVIEW: sized from the fix diff (C=<n>)" [shape=box];
    "Stage 4 PASS: RV [x], close-out written and saved" [shape=box];
```
```
    "GATE 2: approve expanded plan (register must be empty)" -> "Stage 4 IMPLEMENT: every task in the phase, waves of tasks (ambiguity -> ask)" [label="approved"];
    "Stage 4 IMPLEMENT: every task in the phase, waves of tasks (ambiguity -> ask)" -> "Stage 4 REVIEW: RV fan-out over the whole phase diff (all reviewers return first)" [label="every task [x] + gates green"];
    "Stage 4 REVIEW: RV fan-out over the whole phase diff (all reviewers return first)" -> "Stage 4 DECIDE: consolidate, dedup, F-IDs, tiers";
    "Stage 4 DECIDE: consolidate, dedup, F-IDs, tiers" -> "Stage 4 PASS: RV [x], close-out written and saved" [label="no blocking findings"];
    "Stage 4 DECIDE: consolidate, dedup, F-IDs, tiers" -> "Stage 4 FIX_PLAN: one scoped fix plan for this round's blocking findings" [label="blocking findings"];
    "Stage 4 FIX_PLAN: one scoped fix plan for this round's blocking findings" -> "Stage 4 FIX_IMPLEMENT: fix agents, one per file cluster";
    "Stage 4 FIX_IMPLEMENT: fix agents, one per file cluster" -> "Stage 4 RE_REVIEW: sized from the fix diff (C=<n>)";
    "Stage 4 RE_REVIEW: sized from the fix diff (C=<n>)" -> "Stage 4 FIX_PLAN: one scoped fix plan for this round's blocking findings" [label="blocking findings remain"];
    "Stage 4 RE_REVIEW: sized from the fix diff (C=<n>)" -> "Stage 4 PASS: RV [x], close-out written and saved" [label="clean"];
    "Stage 4 PASS: RV [x], close-out written and saved" -> "Stage 4b: joint integration review over a split's combined diff" [label="last sibling of a split"];
    "Stage 4b: joint integration review over a split's combined diff" -> "Stage 4 IMPLEMENT: every task in the phase, waves of tasks (ambiguity -> ask)" [label="findings / next phase"];
    "Stage 4 PASS: RV [x], close-out written and saved" -> "Stage 4 IMPLEMENT: every task in the phase, waves of tasks (ambiguity -> ask)" [label="next phase"];
    "Stage 4 PASS: RV [x], close-out written and saved" -> "Stage 5: finishing-a-development-branch" [label="all phases done"];
```

The graph now has **no edge from any state other than PASS into IMPLEMENT of a
later phase** — that is the invariant drawn.

- [ ] **Step 3: Name the states in `fix-loop.md`**

In `references/fix-loop.md`'s `## Per-phase loop` (`:6-148`), retitle the five
steps to carry the state names, changing headings only and leaving each step's
body text as it stands except where a later task edits it:

- step 0 → `0. Read state (state: entry)`
- step 1 → `1. IMPLEMENT`
- step 2 → `2. REVIEW`
- step 3 → `3. DECIDE`
- step 4 → `4. PASS — close out and advance`

- [ ] **Step 4: Run the gate**

Run: `./tools/check-plugin.sh && ./tools/check-plugin.sh --run tools/fixtures/run-ok`
Expected: `check-plugin: PASS` twice.

The linter's cross-file phrase arms hold several `RV` rules byte-identical
across `SKILL.md`, `references/fix-loop.md`, `references/run-state.md` and
`templates/progress.md`. If an arm fails naming a phrase you moved, restore the
phrase verbatim rather than paraphrasing it — the arm exists so a rule cannot be
deleted from one of the files that defines it.

- [ ] **Step 5: Verify the task-review sweep still passes**

Run: `./tools/check-plugin.sh 2>&1 | grep -A2 'no task-level review'`
Expected: `ok    …`. The new Stage 4 text says "dispatches no reviewer", which
the sweep's patterns must not match — confirm it does not.

- [ ] **Step 6: Commit**

```bash
git add plugins/superb/skills/pipeline/SKILL.md \
        plugins/superb/skills/pipeline/references/fix-loop.md
git commit -m "feat(pipeline): Stage 4 is a per-phase state machine

The loop had four numbered steps and a prose advance condition, which left
implementation, review, planning and remediation interleaving. It is now
named states with entry and exit conditions, and the digraph has no edge into
a later phase from anywhere but PASS."
```

---

### Task 5: The fix plan artifact, required before any fix

Today the standard path plans via `writing-plans` but the **direct-fix path
skips planning entirely** when there are ≤3 findings with exact file:line
(`references/fix-loop.md:327-329`). That is the "finding → random fix → next
finding" shape. Planning becomes unconditional; what varies is the plan's size.

**Files:**
- Create: `plugins/superb/skills/pipeline/templates/fix-plan.md`
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:300-419` (fix loop steps)
- Modify: `plugins/superb/skills/pipeline/references/run-state.md:78-124` (round grammar)
- Modify: `plugins/superb/skills/pipeline/SKILL.md:255-262` (the per-round append example)
- Modify: `plugins/superb/skills/pipeline/templates/progress.md` (grammar comment)
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:390-405`, `:564-565` (pre-`RV` round removed — Step 4b)
- Modify: `plugins/superb/skills/pipeline/templates/findings.md:84`, `:87-89`, `:95` (its Counters row and scope removed — Step 4b)
- Modify: `tools/check-plugin.py` — the fix-plan arm inside `lint_review_lines`; and `:550-560`, `:592`, `:663-667`, `:1086` (the pre-`RV` held-phrase arm, its citation and its summary clause removed — Step 4b)
- Modify: `tools/check-plugin-mutants.sh` — the fix-plan mutants added; `:1287`, `:1426`, `:1428` (the pre-`RV` mutant and the sibling assertion naming it removed — Step 4b)
- Modify: `tools/fixtures/run-ok/` — a round carrying a fix plan

**Interfaces:**
- Produces: the round field `fixplan <file>.md`, required on any round whose
  declaration is `M=<m>` with `m >= 1`. An `M=0 → no round` record carries none
  — no fix agent ran, so there was nothing to plan.
- Produces: `templates/fix-plan.md`, cited by `fix-loop.md`'s FIX_PLAN step.

- [ ] **Step 1: Write the failing arm**

In `tools/check-plugin.py`, inside `lint_review_lines`, alongside the existing
per-round field checks (the ones that read `rpt`, `cov`, `nor`), add the
compiled pattern next to the others near `:1207`:

```python
fixp  = re.compile(r"fixplan\s+(\S+\.md)")
```

and, in the per-round body where `cov` is checked, add:

```python
            # A round that dispatched fixes must name the plan those fixes were
            # written from. `M=<m>` with m >= 1 IS that round: `M` is the count
            # of blocking F-IDs the fix run targeted, less those closed by a
            # route that leaves no ownable commit, so m >= 1 means fix commits
            # exist. Findings -> fix plan -> fix implementation was prose only,
            # and the direct-fix path explicitly skipped the plan, which is how
            # a round became a sequence of unplanned single fixes.
            if d.group("key") == "M" and int(d.group("n")) >= 1:
                fp = fixp.search(rec)
                if not fp:
                    viol += 1
                    bad(f"{where}: round declaring `M={d.group('n')}` names no "
                        "`fixplan <file>.md` — fixes were dispatched with no plan on "
                        "disk for anyone to check them against. REMEDY: write the "
                        "round's fix plan to agent-output/ and name it on the round")
                elif agent_output is not None and not (agent_output / fp.group(1)).exists():
                    viol += 1
                    bad(f"{where}: round names fix plan {fp.group(1)!r}, which is "
                        "not in agent-output/ — a named-but-absent plan reads exactly "
                        "like a planned round. REMEDY: write the file, or correct the "
                        "name")
```

Add to that arm's `# Mutants:` citation block above
`print("\n== pipeline review-line examples ==")`:

```python
# Mutants: "run tracker fix round names no fix plan",
#          "run tracker cites a fix plan that is not in agent-output".
```

- [ ] **Step 2: Extend the fixture so the arm has a happy path, and watch it fail**

`tools/fixtures/run-ok` has no re-review round at all, so the new arm is
unexercised there. Add one to Phase 3, whose record is already the long-record
regression case. Append to Phase 3's `RV` record in
`tools/fixtures/run-ok/progress.md`, as continuation lines of the same bullet:

```
      → round 2: M=2 C=1 → 1 slice + 0 integration · reports p3-rr2-a.md
        · coverage p3-rr2-coverage.md → F-001 closed, F-002 closed
```

Change that phase's outcome from `→ no findings` to `→ F-001, F-002` so round 1
raising two findings and round 2 closing them is coherent.

Create the two files the round names, mirroring the existing stubs' shape:
`tools/fixtures/run-ok/agent-output/p3-rr2-a.md` and
`tools/fixtures/run-ok/agent-output/p3-rr2-coverage.md` (the coverage file
carrying a one-row assignment table above a `git log --oneline` line and ending
`COVERED: 1/1 commits`).

Run: `./tools/check-plugin.sh --run tools/fixtures/run-ok 2>&1 | grep FAIL`
Expected: a `FAIL` naming the round declaring `M=2` and no `fixplan`.

- [ ] **Step 3: Write the fix-plan template**

Create `plugins/superb/skills/pipeline/templates/fix-plan.md`:

```markdown
<!-- Copy to <run-dir>/agent-output/p<phase>-fixplan-r<round>.md and fill in.
     Written BEFORE any fix agent is dispatched, and named on the round in
     progress.md. Much smaller than the implementation plan: ordinary fixes do
     not re-enter brainstorming or the master plan. What it exists for is that
     remediation is a plan someone can check, not a sequence of reactions to
     whichever finding was read last. -->

# Phase <n> — fix plan, round <r>

**Findings in scope:** <F-IDs, one per fix below; every blocking F-ID this
round targets and nothing else>
**Out of scope, and why:** <F-IDs deferred as Minor, or ruled false positive
with the user's answer; or "none">

## Fixes

| # | F-IDs | Root cause (or "unknown — diagnosis first") | Files / components | Depends on | Verified by |
|---|-------|---------------------------------------------|--------------------|------------|-------------|
| 1 | F-001, F-004 | <one line> | `src/x.php`, `src/y.php` | — | `<test command>` |
| 2 | F-002 | <one line> | `src/z.php` | fix 1 | `<test command>` |

One row per **fix agent**, not per finding: related findings in one file cluster
are one row. Five findings across two clusters are two rows, not five.

## Parallelism

<Which rows may run concurrently, and which must not because they touch the
same files or one depends on the other. "All sequential" is a valid answer.>

## Tests required

- New or changed tests: <list, or "none — the existing covering tests fail on
  these findings today", which must be true and checked>
- Command that must be green before RE_REVIEW: `<command>`

## How RE_REVIEW will check this

<The fix diff's file clusters, which is what sizes the re-review as `C=<n>`,
plus anything a reviewer should look at for regressions between fixes.>
```

- [ ] **Step 4: Make planning unconditional in the fix loop**

In `references/fix-loop.md`'s `## Fix loop` (`:300-419`):

Replace the two-path text at `:325-331` (the `Standard path` /
`Direct-fix path` block) with:

```markdown
**Every round is planned.** In this order, no reordering:

```
FINDINGS → FIX PLAN → FIX IMPLEMENTATION
```

1. **Write the fix plan** for this round to
   `agent-output/p<phase>-fixplan-r<round>.md` from `templates/fix-plan.md`, and
   name it on the round in `progress.md`. It states the findings in scope, root
   cause where known, the files each fix touches, dependencies between fixes,
   the tests required, what may run in parallel, and how each fix is verified.
2. **Then dispatch the fixes** — one agent per independent file cluster the plan
   names, related findings batched into one agent. Five related findings take
   one or two agents, not five. Each fix agent runs the tests covering its
   change and reports them.

**Scale the plan, never skip it.** A round of two findings with exact
file:line is a plan of two rows written in a minute; it is not a
`writing-plans` run and it does not re-enter brainstorming or the master plan.
What the artifact buys is that the round's scope is fixed before the first edit
and checkable afterwards. The path that used to skip it — up to three findings
naming exact file and line — is the shape this rule exists to stop: a finding,
a reaction, then the next finding.
```

- [ ] **Step 4b: Delete the pre-`RV` round — prose, ledger, arm and mutant**

There is exactly one formal remediation state machine and it begins after
REVIEW, so the pre-`RV` round — a fix loop entered from step 1 when a wave's
build gates fail, carrying its own Counters row while `RV` stays `[ ]` — is
removed rather than kept alongside it. A red gate before any reviewer exists is
unfinished implementation (`references/implement.md`), and routing it into a
formal round gave it findings, a budget and a state it does not need.

**The concept is load-bearing in six places, and a partial removal red-builds.**
`tools/check-plugin.py` holds the pre-`RV` recording rule as a *cross-file
phrase* — an arm that fails when the sentence is missing from the file that
states it — and a mutant proves that arm can fail. Delete the prose alone and
the arm fires on the deletion. Delete the arm alone and the mutant citation
dangles, which `check-plugin.py`'s own citation check fails on. So all six move
together, and the gate is run once at the end rather than after each.

1. `references/fix-loop.md:390-405` — delete the pre-`RV` round paragraph: the
   sentences from `Such a round also gets **its own Counters row**` through
   `(`<phase> pre-RV`)`, and the whole `**A pre-`RV` round is recorded in
   `findings.md`, and nowhere else**` paragraph with its Counters/Iteration-log
   detail. Keep the surrounding text about a re-review over fix commits not
   being the phase review and `RV` staying `[ ]` — that rule is about
   re-reviews and is still true. Replace the deleted span with:

```markdown
   **Nothing before `RV` enters this loop.** A wave's build gates failing, a red
   test before any reviewer exists, a broken build on the phase branch — these
   are unfinished implementation, repaired inside IMPLEMENT and re-gated there
   (`references/implement.md`). They raise no finding, take no F-ID, need no fix
   plan and spend no iteration budget. This loop has one entry: REVIEW, or a
   re-review, returning blocking findings.
```

2. `references/fix-loop.md:564-565` (the Invariants bullet) — drop the pre-`RV`
   clause so it reads `with a separate row for an `RVJ`, so it does not spend
   the phase's review budget`. The `RVJ` half stays: a joint review is a real
   review with a real budget.
3. `templates/findings.md:84` — delete the `| Phase 3 pre-RV | 1 | 5 | 0 | 2 |`
   example row. Keep `Phase 2` and `RVJ split 4a+4b`.
4. `templates/findings.md:87-89` and `:95` — remove `a phase's pre-`RV` rounds
   (build-gate failures fixed before its review ever ran)` from the **Scope**
   definition and `its pre-`RV` rounds` from the "Open a new row" sentence. The
   scopes that remain are a phase, an `RVJ`, and `<phase> backfill`.
5. `tools/check-plugin.py` — remove the held-phrase entry
   `("the pre-`RV` round's recording rule", "a pre-`rv` round is recorded in
   `findings.md`, and nowhere else", AUTH, ...)` at `:663-667`; remove
   `"the pre-RV recording rule blurred in fix-loop.md"` from the `# Mutants:`
   citation list at `:592`; and remove `the `RV` evidence exception and the
   pre-`RV` recording rule present in the authority that the sites citing them
   read them from` from the summary `ok(...)` sentence at `:1086`, leaving the
   `RV` evidence exception clause intact and the sentence grammatical.
   Also update the explanatory comment at `:550-560`, which describes the
   pre-`RV` rule as one of "THE TWO CROSS-REFERENCED EXCEPTIONS": it becomes
   one, the Invariant's reviewer-evidence exception. Say in that comment that
   the second was removed with the pre-`RV` round itself, so a later reader does
   not restore it looking for a missing pair.
6. `tools/check-plugin-mutants.sh` — delete the
   `run_mutant "the pre-RV recording rule blurred in fix-loop.md"` block at
   `:1428` and the comment naming it at `:1287`. **And** delete the sibling
   assertion in the mutant immediately above it (`:1426`), which asserts the
   pre-`RV` phrase is still present after its own mutation — once the phrase is
   gone that assertion prints `mutant is a no-op` and the mutant it guards stops
   proving anything.

Then confirm the concept is gone and the gate is whole:

```bash
grep -rn 'pre-RV\|pre-`RV`' plugins/superb/skills/pipeline/ tools/ \
  && echo "STILL PRESENT — remove it" || echo "clean"
./tools/check-plugin.sh
./tools/check-plugin-mutants.sh 2>&1 | grep -E 'SURVIVED|no-op' || echo "no survivors, no no-ops"
```

Expected: `clean`; `check-plugin: PASS`; and no survivors or no-op diagnostics.
A `FAIL` naming a dangling mutant citation means step 5 and step 6 were not done
together — finish both, then re-run.

- [ ] **Step 5: Add the field to the round grammar in all four places**

The linter holds `RV` grammar phrases byte-identical across files, so add the
field consistently:

- `references/run-state.md:78-124` — add `fixplan <file>` to the round field
  list, described as: *required on any round declaring `M=<m>` with `m >= 1`;
  absent from an `M=0 → no round` record, which dispatched no fix.*
- `SKILL.md:255-262` — update the worked per-round append to carry it:

```
      → round 2: M=9 C=1 → 1 slice + 0 integration · fixplan p3-fixplan-r2.md
        · reports p3-rr2-a.md · coverage p3-rr2-coverage.md
        → F-012 closed, F-014 raised
```

- `SKILL.md:204-213` — add a `fixplan <file>` row to the four-field closure
  table, scoped to fix rounds.
- `templates/progress.md` — add the field to the grammar comment's `RV` worked
  forms.

- [ ] **Step 6: Fix the fixture and verify the arm passes**

Add `· fixplan p3-fixplan-r2.md` to the fixture's round-2 record and create
`tools/fixtures/run-ok/agent-output/p3-fixplan-r2.md` from the template with
plausible content.

Run: `./tools/check-plugin.sh --run tools/fixtures/run-ok`
Expected: `check-plugin: PASS`, and the summary line reporting one more closed
round than before.

Run: `./tools/check-plugin.sh`
Expected: `check-plugin: PASS` — the skill's own worked examples must obey the
grammar they teach, so `SKILL.md`'s updated round example is linted too.

- [ ] **Step 7: Add the mutants**

```bash
# Fix planning precedes fixing, or the round is a sequence of reactions.
run_mutant "run tracker fix round names no fix plan" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "fixplan p3-fixplan-r2.md" "$f"; then
  echo "mutant is a no-op: the fixture round no longer names a fix plan"
else
  sed -i "s| · fixplan p3-fixplan-r2.md||" "$f"
  grep -qF "fixplan" "$f" && echo "mutant is a no-op: a fixplan field is still on the round"
  grep -qF "M=2 C=1" "$f" || echo "mutant is a no-op: the M= declaration went with it, so a kill could come from a sizing arm instead"
fi'
run_mutant "run tracker cites a fix plan that is not in agent-output" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "fixplan p3-fixplan-r2.md" "$f"; then
  echo "mutant is a no-op: the fixture round no longer names p3-fixplan-r2.md"
elif [ -e tools/fixtures/run-ok/agent-output/p3-fixplan-r9.md ]; then
  echo "mutant is a no-op: p3-fixplan-r9.md exists, so the renamed plan would be found"
else
  sed -i "s|fixplan p3-fixplan-r2.md|fixplan p3-fixplan-r9.md|" "$f"
  grep -qF "fixplan p3-fixplan-r9.md" "$f" || echo "mutant is a no-op: the rename did not apply"
fi'
```

- [ ] **Step 8: Verify the mutants kill**

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep 'fix plan'`
Expected: both lines begin `killed`.

- [ ] **Step 9: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py \
        tools/check-plugin-mutants.sh tools/fixtures/run-ok
git commit -m "feat(pipeline): remediation is planned before it is implemented

The direct-fix path skipped planning for up to three findings with exact
file:line, which is the finding-reaction-finding shape. Every round now writes
a scoped fix plan to agent-output/ and names it on the round, and the review
line linter fails a round that dispatched fixes without one."
```

---

### Task 6: The integration reviewer becomes conditional

`i` is currently 1 whenever `s > 1` (`SKILL.md:208`), so every ordinary
multi-slice phase spends a third reviewer whether or not there is a boundary
only it can see. It becomes conditional — and, because silence is what let the
review fan-out be skipped for seven phases once, the *absence* of a boundary is
declared rather than implied.

**Files:**
- Modify: `plugins/superb/skills/pipeline/SKILL.md:208` (the `i` rule), `:870-908` (fan-out section)
- Modify: `plugins/superb/skills/pipeline/references/run-state.md:82-90`
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:420-490` (re-review table)
- Modify: `plugins/superb/skills/pipeline/templates/progress.md`, `plugins/superb/skills/pipeline/README.md:52-57`
- Modify: `tools/check-plugin.py` — the integration arm in `lint_review_lines`
- Modify: `tools/check-plugin-mutants.sh` — replace the "drops its integration reviewer" mutant (`:1563`)
- Modify: `tools/fixtures/run-ok/progress.md` — Phase 2 and Phase 3 rounds

**Interfaces:**
- Consumes: the round grammar from Task 5.
- Produces: two new round forms — `i=1` requires `· boundary: <named>`;
  `i=0` with `s > 1` requires `· no integration boundary`. `RVJ` is unchanged
  and still always `0 slice + 1 integration`.

- [ ] **Step 1: Write the failing arm**

In `lint_review_lines`, replace the existing check that `i` follows `s` with:

```python
            # The integration reviewer used to be automatic at s > 1, which
            # spent a third reviewer on every ordinary multi-slice phase. It is
            # now conditional on a boundary no single slice's range covers —
            # siblings of a split joining, two lanes joining, or a contract
            # introduced in one slice and consumed in another. Silence is what
            # this file exists to prevent, so the ABSENCE of a boundary is
            # declared too: a multi-slice round with no integration reviewer
            # says so, and a reader can tell the judgement from the omission.
            # `RVJ` keeps its fixed form and is exempt.
            if kind != "RVJ":
                if nint not in (0, 1):
                    viol += 1
                    bad(f"{where}: round declares {nint} integration reviewers — the "
                        "integration slice is the whole diff, so there is at most "
                        "one. REMEDY: declare 0 or 1")
                elif nint == 1 and not re.search(r"boundary:\s*\S", rec):
                    viol += 1
                    bad(f"{where}: round declares an integration reviewer but names "
                        "no `boundary: <what>` — an unnamed boundary is the automatic "
                        "third reviewer this rule replaced. REMEDY: name the boundary "
                        "it covers, or declare `no integration boundary` and drop it")
                elif nint == 0 and nslice > 1 and "no integration boundary" not in rec:
                    viol += 1
                    bad(f"{where}: round of {nslice} slices declares no integration "
                        "reviewer and does not say why — an omission and a judgement "
                        "read identically, which is how a skipped review stays "
                        "invisible. REMEDY: add `· no integration boundary`, or add "
                        "the reviewer with its `boundary:`")
```

`is_rvj` is already available in the round loop from the `start` pattern's first
group; if it is not bound in this scope, derive it there rather than re-parsing.

Add to the `# Mutants:` citations:

```python
# Mutants: "run tracker declares an integration reviewer with no boundary",
#          "run tracker multi-slice round is silent about its integration reviewer",
#          "run tracker declares two integration reviewers".
```

- [ ] **Step 2: Run the gate to verify it fails**

Run: `./tools/check-plugin.sh --run tools/fixtures/run-ok 2>&1 | grep FAIL`
Expected: `FAIL` on the fixture's Phase 2 and Phase 3 rounds, which declare
`2 slice + 1 integration` and name no boundary.

Run: `./tools/check-plugin.sh 2>&1 | grep FAIL`
Expected: `FAIL` on the skill's own worked examples that declare
`1 integration` without a boundary.

- [ ] **Step 3: Change the rule in `SKILL.md`**

At `SKILL.md:208`, replace "**`i` is 1 whenever `s > 1`**, and 0 when `s` is 1,
because one slice already sees the whole diff." with:

```markdown
**`i` is 1 only at a declared integration boundary** — a Rule 3 split's siblings
joining, two lanes joining, or a contract introduced in one slice and consumed
in another that no single slice's range covers — and the round names it
(`· boundary: <what>`). At one slice `i` is 0, because that slice already sees
the whole diff. At two or more slices with no such boundary `i` is 0 and the
round says so (`· no integration boundary`): an omission and a judgement read
identically otherwise, and that is how a review goes missing.
```

At `SKILL.md:870-877`, replace the fan-out table with:

```markdown
| Tasks in phase (N) | Slice reviewers | Integration reviewer | Total |
|--------------------|-----------------|----------------------|-------|
| 1–5                | 1               | 0 (one slice sees all) | 1   |
| 6–10               | 2               | 0, or 1 at a declared boundary | 2–3 |
| 11–12              | 3               | 0, or 1 at a declared boundary | 3–4 |
```

And add below it:

```markdown
**The integration reviewer is spent on a boundary, not on a slice count.** Three
reviewers over an 8-task phase whose slices share no contract read the same code
twice; the third one's value is entirely in what crosses between slices. So it
is dispatched where something crosses — and where something does, it is not
optional. The two mandatory cases keep their own line and their own mandate: a
Rule 3 split's `RVJ` and a lane join's `RVJ` are `0 slice + 1 integration`
always, because there the boundary *is* the unit nobody else saw.

Slice coverage does not change: every commit on the phase branch still falls
inside some slice's range, and that is still a check you run.
```

- [ ] **Step 4: Mirror the rule in the other three files**

- `references/run-state.md:82-90` — the `i` rule and the two new round fields.
- `references/fix-loop.md:420-490` — the re-review table's `Two or more disjoint
  file clusters → one reviewer per file cluster, 1 integration` row becomes
  `0, or 1 at a declared boundary`, with the same declaration requirement.
- `templates/progress.md` — the worked `RV` forms gain one carrying
  `· no integration boundary` and one carrying `· boundary: <what>`.
- `plugins/superb/skills/pipeline/README.md:52-57` — the prose description.

- [ ] **Step 5: Update the fixture**

In `tools/fixtures/run-ok/progress.md`, make the two multi-slice rounds
demonstrate both arms — one of each, since the fixture's job is to exercise the
grammar:

- Phase 2's round keeps its integration reviewer and gains a boundary:
  `· boundary: the T2 contract consumed by the orchestrator commit in slice b`
- Phase 3's round drops to `2 slice + 0 integration`, gains
  `· no integration boundary`, and its `reports` set loses `int`
  (`p3-review-{a,b}.md`). Delete
  `tools/fixtures/run-ok/agent-output/p3-review-int.md` and remove its row from
  `p3-coverage.md`, keeping the remaining two rows' ranges distinct.

Update the fixture's own explanatory prose at the top of `progress.md` to
describe what the two rounds now establish — that file documents its own
purpose, and leaving it stale is the failure it warns about.

- [ ] **Step 6: Run the gate to verify it passes**

Run: `./tools/check-plugin.sh && ./tools/check-plugin.sh --run tools/fixtures/run-ok`
Expected: `check-plugin: PASS` twice.

- [ ] **Step 7: Replace the stale mutant and add the new ones**

The existing mutant `"run tracker's multi-slice round drops its integration
reviewer"` (`tools/check-plugin-mutants.sh:1563`) asserts the rule this task
inverts. Replace it with:

```bash
# The integration reviewer is conditional now, so what must not survive is
# SILENCE about it in either direction: a reviewer with no boundary named, and
# a multi-slice round that neither has one nor says it does not need one.
run_mutant "run tracker declares an integration reviewer with no boundary" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -q "boundary: the T2 contract" "$f"; then
  echo "mutant is a no-op: the fixture round no longer names its boundary"
else
  sed -i "s| · boundary: the T2 contract consumed by the orchestrator commit in slice b||" "$f"
  grep -q "boundary:" "$f" && echo "mutant is a no-op: a boundary is still named on that round"
  grep -qF "2 slice + 1 integration" "$f" || echo "mutant is a no-op: the integration reviewer went with the boundary, so a kill could come from another arm"
fi'
run_mutant "run tracker multi-slice round is silent about its integration reviewer" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "no integration boundary" "$f"; then
  echo "mutant is a no-op: no round declares the absence of a boundary"
else
  sed -i "s| · no integration boundary||" "$f"
  grep -qF "no integration boundary" "$f" && echo "mutant is a no-op: the declaration is still present"
fi'
run_mutant "run tracker declares two integration reviewers" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "2 slice + 1 integration" "$f"; then
  echo "mutant is a no-op: no round declares 1 integration reviewer to double"
else
  sed -i "0,/2 slice + 1 integration/s|2 slice + 1 integration|2 slice + 2 integration|" "$f"
  grep -qF "2 slice + 2 integration" "$f" || echo "mutant is a no-op: the count was not doubled"
fi'
```

- [ ] **Step 8: Verify the mutants kill and nothing regressed**

```bash
./tools/check-plugin-mutants.sh 2>&1 | tail -20
```
Expected: no `SURVIVED` anywhere in the run, and the three new mutant names
each printing `killed`. If the harness reports the baseline failing over
`tools/fixtures/run-ok`, the fixture edits in Step 5 are incomplete — fix those
before reading any mutant result.

- [ ] **Step 9: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py \
        tools/check-plugin-mutants.sh tools/fixtures/run-ok
git commit -m "fix(pipeline): spend the integration reviewer on a boundary, not a slice count

i was 1 whenever s was above 1, so every ordinary multi-slice phase paid for a
third reviewer whose value is entirely in what crosses between slices. It is
now conditional on a named boundary — and because an omission and a judgement
read identically, a multi-slice round with no boundary declares that too. The
two mandatory cases, a split's RVJ and a lane join's RVJ, are untouched."
```

---
# Phase 3 — Mechanical enforcement

Goal: the invariants are checked against a real tracker, not only asserted in
prose. Three arms and two fixtures.

---

### Task 7: The review-not-early arm

Proves the spec's *no per-task review* test mechanically: for an 8-task phase,
review cannot have started while T8 is unchecked.

**Files:**
- Modify: `tools/check-plugin.py` — `parse_tracker_phases` helper + the arm
- Modify: `tools/check-plugin-mutants.sh` — its mutants

**Interfaces:**
- Produces: `parse_tracker_phases(text) -> list[dict]`, with keys `label`,
  `line`, `tasks` (list of `(state, name, lineno)`), `reviews` (list of
  `(kind, state, lineno)`), `state` ∈ `" "`, `"~"`, `"x"`. Tasks 8 consumes it.

- [ ] **Step 1: Write the helper and the failing arm**

Add to `tools/check-plugin.py`, immediately above the `if RUN_DIR is not None:`
block (currently `:1789`):

```python
def parse_tracker_phases(text):
    """Split a tracker into phases with their task and RV/RVJ bullet states.

    A phase is a `## Phase <x>` heading; its bullets are the `- [ ] T<n>` and
    `- [ ] RV`/`RVJ` lines under it, until the next such heading. Returned in
    file order, because that order is what "a later phase" means. Only the box
    character is read — the fields after it are `lint_review_lines`' business.
    """
    phases, cur = [], None
    for n, line in enumerate(text.split("\n"), 1):
        mh = re.match(r"##\s+(Phase\s+[^\s—·]+)", line)
        if mh:
            cur = {"label": mh.group(1).strip(), "line": n, "tasks": [], "reviews": []}
            phases.append(cur)
            continue
        if cur is None:
            continue
        mb = re.match(r"\s*-\s*\[([ x~])\]\s*(RVJ|RV|T[0-9A-Za-z.]+)", line)
        if mb:
            st, what = mb.group(1), mb.group(2)
            (cur["reviews"] if what in ("RV", "RVJ") else cur["tasks"]).append(
                (what, st, n) if what in ("RV", "RVJ") else (st, what, n))
    return phases
```

Then, inside the `--run` block after the `lint_review_lines` call, add:

```python
        # ---- review may not begin while a task in the phase is unchecked ----
        # The failure this catches is the old per-task shape wearing the new
        # vocabulary: reviewers dispatched over T1..T3 while T4..T8 are still
        # out, which is per-task review at a coarser grain and re-splits the
        # phase into pieces nobody reviewed as a unit. It is checkable from the
        # tracker alone, because a started round and an unchecked task line
        # cannot both be true of a phase reviewed as a whole.
        # Mutants: "run tracker reviews a phase with an unchecked task",
        #          "run tracker reviews a phase with a task still in progress".
        _phs = parse_tracker_phases(ttext)
        _early = []
        for _ph in _phs:
            _opent = [t for t in _ph["tasks"] if t[0] != "x"]
            _startedr = [r for r in _ph["reviews"] if r[1] in ("~", "x")]
            if _opent and _startedr:
                _early.append(
                    f"{relpath(tracker)}:{_startedr[0][2]}: {_ph['label']}'s "
                    f"{_startedr[0][0]} is `[{_startedr[0][1]}]` while "
                    f"{len(_opent)} task line(s) in that phase are not `[x]` "
                    f"(first at line {_opent[0][2]}, {_opent[0][1]})")
        if _early:
            for _e in _early:
                bad(_e + " — a phase is reviewed as one unit once all of its "
                    "tasks have landed; a round opened earlier reviews part of a "
                    "phase, which is per-task review at a coarser grain. REMEDY: "
                    "finish the phase's tasks, then open its review; if the round "
                    "did cover everything, the unchecked task lines are the thing "
                    "that is wrong and Rule 4 reconciliation is the fix")
        elif _phs:
            ok(f"{len(_phs)} phases, none with a review round opened while one of "
               "its own tasks was unchecked")
```

Note `ttext` — the tracker text. The current code reads the tracker only inside
`read(tracker)[1]` for its error. Bind it once:

```python
    elif (_tr := read(tracker))[1]:
        terr = _tr[1]
        <the existing bad(...) call, unchanged>
    else:
        ttext = _tr[0]
        <the existing else-body, unchanged, then the new arms below>
```

The existing code reads `elif (terr := read(tracker)[1]):`, which keeps the
error string and throws the text away. Rebinding as above leaves the `bad(...)`
f-string **byte-identical** — `terr` still names the same value — and makes the
text available as `ttext`. Do not reword the message: the linter's cross-file
phrase arms and its own mutant citations are matched by name.

- [ ] **Step 2: Run the arm — it passes on `run-ok`, which is the point**

Run: `./tools/check-plugin.sh --run tools/fixtures/run-ok 2>&1 | grep -E 'phases,|FAIL'`
Expected: `ok    3 phases, none with a review round opened while …`.

The arm's RED comes from its mutants, not from the conforming fixture. Do not
skip Step 3 — an arm never seen to fail is an arm that cannot.

- [ ] **Step 3: Add the mutants and watch them kill**

```bash
# Review before the phase finished, in both shapes a real run produces: a task
# never started, and a task dispatched and still out.
run_mutant "run tracker reviews a phase with an unchecked task" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "- [x] T2 —" "$f"; then
  echo "mutant is a no-op: the fixture has no closed T2 to reopen"
else
  sed -i "s|- \[x\] T2 —|- [ ] T2 —|" "$f"
  grep -qF "- [ ] T2 —" "$f" || echo "mutant is a no-op: T2 was not reopened"
fi'
run_mutant "run tracker reviews a phase with a task still in progress" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "- [x] T3 —" "$f"; then
  echo "mutant is a no-op: the fixture has no closed T3 to reopen"
else
  sed -i "s|- \[x\] T3 —|- [~] T3 —|" "$f"
  grep -qF "- [~] T3 —" "$f" || echo "mutant is a no-op: T3 was not set in-progress"
fi'
```

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep 'reviews a phase'`
Expected: both `killed`.

- [ ] **Step 4: Commit**

```bash
git add tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "test(tools): a phase's review may not open while its tasks are out

Per-task review comes back at a coarser grain if a round can open over three
of eight landed tasks. A started RV beside an unchecked task line in the same
phase is now a FAIL, with mutants for both shapes."
```

---

### Task 8: The no-advance arm

Proves the spec's *phase cannot advance after failed review*, *failed re-review
loops inside the same phase*, and *clean re-review advances* tests.

**Files:**
- Modify: `tools/check-plugin.py` — Current State parsing, findings ledger
  parsing, the arm
- Modify: `tools/check-plugin-mutants.sh` — its mutants

**Interfaces:**
- Consumes: `parse_tracker_phases` from Task 7.
- Produces: nothing later tasks consume; this is a terminal gate.

- [ ] **Step 1: Write the failing arm**

Add to the `--run` block after Task 7's arm:

```python
        # ---- Current State may not point past an unfinished phase ----
        # This is the invariant, checked. Three ways a phase is unfinished, and
        # the tracker's own "next unchecked line" rule can only see the first:
        #   1. a bullet in it is not `[x]` — an open task, or an open RV/RVJ;
        #   2. a blocking finding scoped to it is still `open` in findings.md —
        #      a fix loop interrupted mid-round leaves every box `[x]`, so the
        #      next unchecked line points PAST the phase that owns the finding;
        #   3. a round names a fix plan that is not on disk (checked above).
        # The history this exists for: a real run skipped the review fan-out for
        # seven consecutive phases because every gate read "no open blocking
        # IDs", which is vacuously true when review never ran.
        # findings.md is read only if present — `tools/fixtures/run-ok` has none,
        # and the PASS line must not claim a ledger check that did not happen.
        # Mutants: "run tracker advances past a phase with an open RV",
        #          "run tracker advances past a phase with an open blocking finding",
        #          "run tracker next action names a later phase than its own state".
        _idx = {p["label"].lower(): i for i, p in enumerate(_phs)}
        _unfinished = []
        for _i, _ph in enumerate(_phs):
            _why = []
            if any(t[0] != "x" for t in _ph["tasks"]):
                _why.append("an open task line")
            if any(r[1] != "x" for r in _ph["reviews"]):
                _why.append("an open RV/RVJ line")
            if _why:
                _unfinished.append((_i, _ph, _why))

        _ledger = RUN_DIR / "findings.md"
        _ltext = None
        if _ledger.is_file():
            _ltext, _lerr = read(_ledger)
            if _lerr:
                bad(f"{relpath(_ledger)} cannot be read: {_lerr} — it may hold "
                    "open blocking findings, so nothing here says this run has "
                    "none. REMEDY: make the file readable and run again")
                _ltext = None
        _openf = []
        if _ltext:
            for _row in re.finditer(
                    r"^\|\s*(F-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|"
                    r"[^|]*\|[^|]*\|\s*(open)\s*\|", _ltext, re.M):
                _fid, _sev, _phl = _row.group(1), _row.group(2).strip(), _row.group(3).strip()
                if _sev.lower() in ("critical", "major", "bug"):
                    _openf.append((_fid, _sev, _phl))

        _ns = re.search(r"\*\*Next action:\*\*\s*(.+)", ttext)
        _named = None
        if _ns:
            _m = re.search(r"[Pp]hase\s+([0-9A-Za-z.]+)", _ns.group(1))
            if _m:
                _named = _idx.get(f"phase {_m.group(1)}".lower())

        _blockers = []
        if _unfinished:
            _blockers.append((_unfinished[0][0], _unfinished[0][1]["label"],
                              ", ".join(_unfinished[0][2])))
        for _fid, _sev, _phl in _openf:
            _pi = _idx.get(f"phase {_phl}".lower())
            if _pi is not None:
                _blockers.append((_pi, f"Phase {_phl}",
                                  f"open blocking finding {_fid} ({_sev})"))
        _blockers.sort(key=lambda b: b[0])

        if _blockers and _named is not None and _named > _blockers[0][0]:
            bad(f"{relpath(tracker)}: Next action names a phase later than "
                f"{_blockers[0][1]}, which still has {_blockers[0][2]} — a phase "
                "is complete only when its tasks are `[x]`, its RV is `[x]` and "
                "every blocking finding scoped to it is closed. Advancing here is "
                "the orchestration failure this gate exists for. REMEDY: point "
                "Next action at that phase's own next action — its review, or its "
                "fix loop")
        elif _blockers and _named is None and _ns:
            ok(f"Next action names no phase; earliest unfinished is "
               f"{_blockers[0][1]} ({_blockers[0][2]})")
        elif _named is not None or _ns:
            ok("Next action does not point past an unfinished phase"
               + ("" if _ltext else " (no findings.md in this run, so the ledger "
                  "half of that was not checked)"))
```

- [ ] **Step 2: Run it against `run-ok` and verify it passes**

Run: `./tools/check-plugin.sh --run tools/fixtures/run-ok 2>&1 | grep -E 'Next action|FAIL'`
Expected: an `ok` line. `run-ok`'s Current State says `Phase: done (fixture)`
and `Next action: none`, so no phase is named and nothing is unfinished.

- [ ] **Step 3: Add the mutants and watch them kill**

```bash
# The invariant, attacked three ways. The first two make a phase unfinished and
# leave Current State pointing past it; the third moves only the pointer.
run_mutant "run tracker advances past a phase with an open RV" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "- [x] RV — review fan-out · N=1" "$f"; then
  echo "mutant is a no-op: Phase 1s RV is not in the expected closed form"
else
  sed -i "s|- \[x\] RV — review fan-out · N=1|- [ ] RV — review fan-out · N=1|" "$f"
  sed -i "s|^- \*\*Next action:\*\*.*|- **Next action:** Phase 3 T3|" "$f"
  grep -qF "Next action:** Phase 3" "$f" || echo "mutant is a no-op: Next action was not moved past Phase 1"
fi'
run_mutant "run tracker advances past a phase with an open blocking finding" '
enable_run || exit 0
d=tools/fixtures/run-ok
if [ -e "$d/findings.md" ]; then
  echo "mutant is a no-op: the fixture already has a findings.md, so this would not be the ledger arm firing"
else
  printf "%s\n" "| ID | Sev | Phase | File:line | Finding | State | Closed by |" \
                "| -- | --- | ----- | --------- | ------- | ----- | --------- |" \
                "| F-001 | Critical | 1 | \`src/x.php:1\` | mutant | open | |" > "$d/findings.md"
  sed -i "s|^- \*\*Next action:\*\*.*|- **Next action:** Phase 3 T3|" "$d/progress.md"
  grep -qF "Next action:** Phase 3" "$d/progress.md" || echo "mutant is a no-op: Next action was not moved past Phase 1"
fi'
run_mutant "run tracker next action names a later phase than its own state" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "- [x] T2 —" "$f"; then
  echo "mutant is a no-op: the fixture has no closed T2 to reopen"
else
  sed -i "s|- \[x\] T2 —|- [ ] T2 —|" "$f"
  sed -i "s|- \[x\] RV — review fan-out · N=8|- [ ] RV — review fan-out · N=8|" "$f"
  sed -i "s|^- \*\*Next action:\*\*.*|- **Next action:** Phase 3 T3|" "$f"
  grep -qF "Next action:** Phase 3" "$f" || echo "mutant is a no-op: Next action was not moved"
fi'
```

The second mutant writes a `findings.md` the fixture does not have, which is
also what proves the ledger half runs when the file exists.

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep -E 'advances past|later phase'`
Expected: all three `killed`.

- [ ] **Step 4: Commit**

```bash
git add tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "test(tools): Current State may not point past an unfinished phase

The invariant was prose in four files and checkable in none. A tracker whose
Next action names a phase later than the earliest one holding an open task, an
open RV, or an open blocking finding in findings.md is now a FAIL — including
the case every box is [x] and only the ledger knows, which is what a fix loop
interrupted mid-round looks like."
```

---

### Task 9: Resume precedence, and the two resume fixtures

Proves the spec's *resume after implementation* and *resume during fix loop*
tests.

**Files:**
- Modify: `plugins/superb/skills/pipeline/references/run-state.md:163-213`
- Create: `tools/fixtures/run-open-rv/progress.md` + `agent-output/`
- Create: `tools/fixtures/run-fixloop/progress.md`, `findings.md` + `agent-output/`
- Modify: `tools/check-plugin-mutants.sh` — `enable_run_dir`, new baselines, mutants
- Modify: `.github/workflows/checks.yml`

**Interfaces:**
- Consumes: every arm from Tasks 5, 6, 7, 8 — the fixtures are their happy paths
  for the two states `run-ok` cannot express.
- Produces: `enable_run_dir <dir>` in the mutant harness; `enable_run` becomes a
  one-line wrapper for `tools/fixtures/run-ok` so existing mutants are untouched.

- [ ] **Step 1: Write the resume precedence table**

In `references/run-state.md`'s `## Resume Protocol` (`:163-213`), replace the
prose precedence at `:206-213` with a table that names the state, keeping the
existing sentences about the register and the open blocking F-ID as the rows'
justification:

```markdown
**Resume derives the state from disk, in this precedence.** Read down; the first
row that matches is the state, and its action is the only valid next action.

| On disk | State | The only valid next action |
| --- | --- | --- |
| any `[~]` line | unreconciled | Rule 4 reconciliation — an `[~]` `RV`/`RVJ` against `agent-output/`, never against the code; an `[~]` task against the tree |
| `register.md` has open entries | blocked on the user | ask them, before any implementation |
| a blocking F-ID is `open` in `findings.md` | `FIX_PLAN` / `FIX_IMPLEMENT` / `RE_REVIEW` of **the phase that owns it** | continue that phase's fix loop from the Iteration log's last incomplete row — write the round's fix plan if it is missing, dispatch the fixes if it is not, re-review if they landed |
| a round names a `fixplan` not in `agent-output/` | `FIX_PLAN` | write that round's fix plan |
| every task of a phase `[x]`, its `RV` `[ ]` | `REVIEW` | **review that phase.** Not the next phase — this is the most important run there is to resume: fully implemented and entirely unreviewed |
| every task `[x]`, `RV` `[x]`, no open blocking F-ID | `PASS` | close out, then the next phase's first task |

**An open blocking F-ID outranks the tracker's next unchecked line.** A fix loop
interrupted mid-round leaves `RV` `[x]` and every task `[x]`, so the next
unchecked line points past the phase that owns the finding. Read the ledger's
open IDs and the Iteration log's last incomplete row before taking any line from
the tracker.

**Resume never re-runs a completed implementation task, and never advances.**
A task line `[x]` with a hash is done; re-dispatching it is how a resumed run
duplicates work. And no row above has "start the next phase" as its action
except the last.
```

- [ ] **Step 2: Build the `run-open-rv` fixture**

Create `tools/fixtures/run-open-rv/progress.md`. It needs a **closed** round
(the `--run` mode fails a tracker with none) *and* the resume state, so it has
two phases:

```markdown
# Pipeline — Progress Tracker

A fixture run directory, not a real one. Its job is the one state
`tools/fixtures/run-ok` cannot hold: **a phase fully implemented and entirely
unreviewed.** Phase 2's tasks are all `[x]` with hashes and its `RV` is `[ ]`,
so the only valid next action is Phase 2's review — never Phase 3, and never
re-running T3..T5. Phase 1 is closed so the tracker has a conforming round for
the review-line linter to read; without one, `--run` reports that nothing in
the run has been reviewed and a PASS here would mean nothing.

`Next action` names Phase 2's `RV`, which is what the no-advance arm reads:
point it at a later phase and that arm fires.

## Current State
- **Phase:** 2 — implemented, unreviewed
- **Next action:** Phase 2 RV — review fan-out over the phase branch
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-open-rv/

## Phase 1 — fixture, closed · deps: none
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, implemented and unreviewed · deps: Phase 1
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] T3 — a task · W1 · deps T1 — `ccccccc`
- [x] T4 — a task · W2 · deps T2 — `ddddddd`
- [x] T5 — a task · W2 · deps T3 — `eeeeeee`
- [ ] RV — review fan-out

## Phase 3 — fixture, not started · deps: Phase 2
- [ ] T6 — a task · W1 · deps T4
- [ ] RV — review fan-out
```

Create `tools/fixtures/run-open-rv/agent-output/p1-review-a.md` and
`p1-coverage.md`, the coverage file in the fixed shape (assignment table above
`git log --oneline`, ending `COVERED: 1/1 commits`).

Run: `./tools/check-plugin.sh --run tools/fixtures/run-open-rv`
Expected: `check-plugin: PASS`, with the review-not-early arm reporting 3 phases
clean — Phase 2 has open work but no started round, and Phase 3 has neither.

- [ ] **Step 3: Build the `run-fixloop` fixture**

Create `tools/fixtures/run-fixloop/progress.md` — Phase 2 with every box `[x]`,
`RV` closed on round 1 that raised two findings, one still open, and round 2's
fix plan already written but its fixes not yet landed:

```markdown
# Pipeline — Progress Tracker

A fixture run directory, not a real one. Its job is the state where **every box
is `[x]` and the phase is still not complete**: Phase 2's tasks are `[x]`, its
`RV` is `[x]`, and `findings.md` holds `F-002` open. The tracker's own "next
unchecked line" rule points at Phase 3 from here — which is exactly the bug the
ledger precedence exists to stop — so `Next action` names Phase 2's fix loop
instead, and the no-advance arm reads the ledger to agree.

Round 2's fix plan is on disk and its fixes have not landed, so this is also the
`FIX_PLAN`-written / `FIX_IMPLEMENT`-pending resume case: the plan is not
rewritten and the round is not re-planned.

## Current State
- **Phase:** 2 — fix loop, round 2 planned, fixes pending
- **Next action:** Phase 2 fix loop round 2 — dispatch the fixes in p2-fixplan-r2.md
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-fixloop/

## Phase 1 — fixture, closed · deps: none
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, implemented and reviewed, findings open · deps: Phase 1
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] T3 — a task · W1 · deps T1 — `ccccccc`
- [x] RV — review fan-out · N=2 → 1 slice + 0 integration
      · reports p2-review-a.md · coverage p2-coverage.md → F-001, F-002
      → round 2: M=2 C=1 → 1 slice + 0 integration · fixplan p2-fixplan-r2.md
        · reports p2-rr2-a.md · coverage p2-rr2-coverage.md → F-001 closed

## Phase 3 — fixture, not started · deps: Phase 2
- [ ] T4 — a task · W1 · deps T3
- [ ] RV — review fan-out
```

Create `tools/fixtures/run-fixloop/findings.md` with a ledger holding `F-001`
closed and `F-002` open at `Major`, `Phase` = `2`, plus the Counters and
Iteration-log tables from `templates/findings.md` so the fixture is a plausible
ledger and not just one row.

Create the five files the rounds name under
`tools/fixtures/run-fixloop/agent-output/`: `p1-review-a.md`, `p1-coverage.md`,
`p2-review-a.md`, `p2-coverage.md`, `p2-fixplan-r2.md`, `p2-rr2-a.md`,
`p2-rr2-coverage.md`.

Run: `./tools/check-plugin.sh --run tools/fixtures/run-fixloop`
Expected: `check-plugin: PASS`. In particular the no-advance arm must report
`ok`, because `Next action` names Phase 2 and the earliest blocker is Phase 2.

- [ ] **Step 4: Parameterise `enable_run` and add the baselines**

In `tools/check-plugin-mutants.sh`, replace the `enable_run()` definition
(`:197-208`) with:

```bash
enable_run_dir() { # inside the copy: make the wrapper pass --run <dir>
  local d="$1" f=tools/check-plugin.sh a='check-plugin.py" "$@"'
  if ! grep -qF "$a" "$f"; then
    echo "mutant is a no-op: the wrapper no longer invokes check-plugin.py with forwarded arguments, so --run cannot be reached"
    return 1
  fi
  sed -i "s|check-plugin.py\" \"\$@\"|check-plugin.py\" --run $d \"\$@\"|" "$f"
  if ! grep -qF -- "--run $d" "$f"; then
    echo "mutant is a no-op: --run was not injected into the wrapper, so the run mode was never entered"
    return 1
  fi
}
enable_run() { enable_run_dir tools/fixtures/run-ok; }
```

Every existing mutant calling `enable_run` is unchanged.

Then extend the baseline block (after the existing `--run tools/fixtures/run-ok`
assertion at `:52-59`) with the same assertion for each new fixture:

```bash
for fx in tools/fixtures/run-open-rv tools/fixtures/run-fixloop; do
  if ( cd "$D" && ./tools/check-plugin.sh --run "$fx" ) >/dev/null 2>&1; then
    echo "  ok    clean copy passes with --run over $fx"
  else
    echo "  FAIL  $fx does not conform on a clean copy — every mutant over it would then kill for that reason instead of its own"
    ( cd "$D" && ./tools/check-plugin.sh --run "$fx" ) | grep FAIL
    exit 1
  fi
done
```

- [ ] **Step 5: Add the resume-state mutants**

```bash
# The two resume states, each attacked at the thing that makes it that state.
run_mutant "implemented-unreviewed fixture opens its review early" '
enable_run_dir tools/fixtures/run-open-rv || exit 0
f=tools/fixtures/run-open-rv/progress.md
if ! grep -qF "- [ ] RV — review fan-out" "$f"; then
  echo "mutant is a no-op: no open RV to start"
else
  sed -i "s|- \[x\] T5 — a task · W2 · deps T3 — \`eeeeeee\`|- [ ] T5 — a task · W2 · deps T3|" "$f"
  sed -i "0,/- \[ \] RV — review fan-out$/s|- \[ \] RV — review fan-out$|- [~] RV — review fan-out · N=4 → 1 slice + 0 integration · started 2026-09-07 10:00|" "$f"
  grep -qF "[~] RV" "$f" || echo "mutant is a no-op: the RV was not opened"
fi'
run_mutant "implemented-unreviewed fixture advances to the next phase" '
enable_run_dir tools/fixtures/run-open-rv || exit 0
f=tools/fixtures/run-open-rv/progress.md
if ! grep -qF "Next action:** Phase 2 RV" "$f"; then
  echo "mutant is a no-op: Next action no longer names Phase 2 RV"
else
  sed -i "s|^- \*\*Next action:\*\*.*|- **Next action:** Phase 3 T6|" "$f"
  grep -qF "Next action:** Phase 3" "$f" || echo "mutant is a no-op: Next action was not moved"
fi'
run_mutant "fix-loop fixture advances with a blocking finding open" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/progress.md
if ! grep -qF "Next action:** Phase 2 fix loop" "$f"; then
  echo "mutant is a no-op: Next action no longer names Phase 2s fix loop"
elif ! grep -qE "^\| F-002 .*\| open \|" tools/fixtures/run-fixloop/findings.md; then
  echo "mutant is a no-op: F-002 is not open in the ledger, so the ledger arm would not be what fires"
else
  sed -i "s|^- \*\*Next action:\*\*.*|- **Next action:** Phase 3 T4|" "$f"
  grep -qF "Next action:** Phase 3" "$f" || echo "mutant is a no-op: Next action was not moved"
fi'
run_mutant "fix-loop fixture dispatches a round with no fix plan on disk" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
p=tools/fixtures/run-fixloop/agent-output/p2-fixplan-r2.md
if [ ! -f "$p" ]; then
  echo "mutant is a no-op: the fix plan is already absent"
else
  rm -f "$p"
fi'
```

- [ ] **Step 6: Wire the fixtures into CI**

In `.github/workflows/checks.yml`, after the existing
`- run: ./tools/check-plugin.sh --run tools/fixtures/run-ok`, add:

```yaml
      # The two run states run-ok cannot hold: a phase implemented and
      # unreviewed, and a phase whose boxes are all [x] while its ledger still
      # holds an open blocking finding. The arms that read them have no other
      # conforming input, so without these lines their happy paths run only
      # inside the mutant harness's baseline.
      - run: ./tools/check-plugin.sh --run tools/fixtures/run-open-rv
      - run: ./tools/check-plugin.sh --run tools/fixtures/run-fixloop
```

- [ ] **Step 7: Verify everything**

```bash
./tools/check-plugin.sh
./tools/check-plugin.sh --run tools/fixtures/run-ok
./tools/check-plugin.sh --run tools/fixtures/run-open-rv
./tools/check-plugin.sh --run tools/fixtures/run-fixloop
./tools/check-plugin-mutants.sh
```
Expected: four `check-plugin: PASS`, and the harness ending with no `SURVIVED`
and no `no-op` diagnostics.

- [ ] **Step 8: Commit**

```bash
git add plugins/superb/skills/pipeline/references/run-state.md \
        tools/fixtures/run-open-rv tools/fixtures/run-fixloop \
        tools/check-plugin-mutants.sh .github/workflows/checks.yml
git commit -m "test(tools): fixtures for the two resume states, and a precedence table

Resume had its precedence as prose and no conforming input for the two states
that matter: implemented-and-unreviewed, and every-box-[x]-with-an-open-finding.
Both are fixtures now, both are in CI, and the precedence is a table whose
first matching row is the state."
```

---

# Phase 4 — Cleanup and release

---

### Task 10: Fix-agent sizing, and the re-tag rule without its old source

**Files:**
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:77-79` (re-tag), `:420-490`
- Modify: `plugins/superb/skills/pipeline/templates/findings.md:35-51`
- Modify: `tools/check-plugin.py:250-300` (the tier arm's SDD attribution)

**Interfaces:**
- Consumes: Task 3's sweeps (the re-tag text must not re-introduce a banned phrase).

- [ ] **Step 1: Confirm the re-tag rule reads as generalised**

The wording moved in **Task 3, Step 6b** — it had to, because the sweep that
task installs reads every `.md` in the skill and the old clause named a
`task reviewer`. Confirm it landed and still carries its predicate:

```bash
sed -n '74,82p' plugins/superb/skills/pipeline/references/fix-loop.md
sed -n '33,38p' plugins/superb/skills/pipeline/templates/findings.md
grep -rn 'task reviewer' plugins/superb/skills/pipeline/ && echo "STILL PRESENT" || echo "clean"
```

Expected: the rule reads "a reviewer may emit **Important**, whose usual
contract is …", the predicate below it is intact, and the grep is `clean`.

The rule is **kept, not deleted**: the repo `/review` skill and any reviewer a
project supplies may report in another vocabulary, so the seam still needs its
re-tag. What changed is that it no longer attributes the tier to a caller
pipeline does not invoke. This task's remaining work is the linter comment that
explains that scope, and the fix-agent sizing rule below.

- [ ] **Step 2: Update the linter's tier arm comment and keep its scope**

`tools/check-plugin.py:253-300`'s comment explains the scope with SDD as the
source of the leak. Update the explanation to record what changed without losing
the reason the arm is scoped to `pipeline`:

```python
        # A FOURTH severity tier reaches the ledger from OUTSIDE this skill.
        # It used to arrive from `subagent-driven-development`'s task reviewer,
        # which pipeline invoked per task until Stage 4 became
        # `references/implement.md`; in one 141-finding run, 50 findings gated
        # phase advancement under a tier that appeared NOWHERE in the skill.
        # Removing that caller does not close the hole: the repo `/review` skill
        # and any reviewer a project supplies can emit `Important` too, and its
        # usual contract — "fix everything before this unit completes" — is
        # still wrong for a phase, because this skill's blocking list is closed
        # and different. So the rule stands: the skill may name the tier only
        # alongside the sentence that re-tags it.
```

Leave the `n == "pipeline"` scope and its EXPIRY note as they are — the reason
they give ("pipeline is the only skill with a phase gate a task-scoped tier can
mis-gate") is unchanged by this work.

- [ ] **Step 3: Size fix agents by cluster in the fix loop**

In `references/fix-loop.md`, add to the FIX_IMPLEMENT text from Task 5:

```markdown
**Fix agents are sized like re-reviewers: by file cluster, not by finding
count.** One agent per independent cluster the fix plan names. Findings that
share a cluster share an agent — they touch the same code and two agents on it
conflict. `M` sizes nothing here either, for the same reason it stopped sizing
the re-review: six comment corrections in one file are one small diff, and six
agents over it spend six dispatches to produce one.
```

- [ ] **Step 4: Run the gate**

Run: `./tools/check-plugin.sh && ./tools/check-plugin.sh --run tools/fixtures/run-ok`
Expected: `check-plugin: PASS` twice, and the task-review sweep still `ok` — the
new text names `subagent-driven-development` in the linter comment (not a skill
file) and in `references/implement.md` (allowed), but must not re-introduce a
banned phrase into a skill `.md`.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py
git commit -m "fix(pipeline): size fix agents by cluster, and keep the re-tag without its old caller

The Important re-tag existed because pipeline invoked a task reviewer that
emits it. It no longer does, but the rule is not the caller's: /review and any
project-supplied reviewer can emit it, and its unit-scoped contract is still
wrong for a phase. Generalised, kept, and its arm's reasoning updated. Fix
agents are now sized the way re-reviewers already were."
```

---

### Task 11: Documentation, version, and the final contradiction sweep

**Files:**
- Modify: `README.md:32`, `:143-147`, `:207`, `:213`
- Modify: `plugins/superb/README.md:10`
- Modify: `plugins/superb/skills/pipeline/README.md`
- Modify: `plugins/superb/.claude-plugin/plugin.json:3`, `plugins/superb/.codex-plugin/plugin.json:3`
- Modify: `.claude-plugin/marketplace.json:12` (the description naming the loop)

- [ ] **Step 1: Fix the user-facing per-task review promise**

`README.md:143-147` currently promises per-task review. Replace it with:

```markdown
After that it runs on its own: implement, review, fix, next phase — stopping
only for a genuine unknown, a blocked subagent, or the finished branch. Every
**phase** is reviewed as a unit by agents that did not write it, over exact
commit ranges that cover the whole phase diff, and no phase advances until its
review and any fix rounds have closed. Completing a task dispatches no
reviewer: implementation runs to the end of the phase, and review is the phase
boundary.
```

- [ ] **Step 2: Fix the Stage→skill mapping**

`README.md:207` maps stage 4 to `superpowers:subagent-driven-development`.
Replace that row's skill with pipeline's own reference, and adjust `:213`'s
dependency sentence so it no longer claims pipeline needs SDD:

```markdown
| 4 — the autonomous per-phase implement/review/fix loop | pipeline's own `references/implement.md` and `references/fix-loop.md` |
```

Check what `superb:setup` claims about dependencies:

```bash
grep -rn 'subagent-driven-development' plugins/superb/skills/setup/ README.md plugins/superb/README.md
```

`superb:bug-fix` still uses SDD legitimately, so the dependency stays declared
where `bug-fix` needs it — but every sentence saying **pipeline** needs it must
go. Update `plugins/superb/skills/pipeline/README.md:91-97`'s Requires section
accordingly.

- [ ] **Step 3: Update the two one-liners and the marketplace description**

- `plugins/superb/README.md:10` and `README.md:32` — pipeline's one-line
  description; keep the wording but make the loop per-phase explicit.
- `.claude-plugin/marketplace.json:12` — the description names "reviewer
  fan-out, a recursive fix loop, and dependency waves for parallel
  implementers". Add the phase gate:
  `a per-phase review gate, planned fix rounds, and dependency waves for parallel implementers`.
  Do not touch `.agents/plugins/marketplace.json` unless it carries the same
  sentence — check it.

- [ ] **Step 4: Bump the version in both manifests**

```bash
sed -i 's/"version": "0.11.0"/"version": "0.12.0"/' \
  plugins/superb/.claude-plugin/plugin.json \
  plugins/superb/.codex-plugin/plugin.json
grep -n '"version"' plugins/superb/.claude-plugin/plugin.json plugins/superb/.codex-plugin/plugin.json
```
Expected: both report `0.12.0`. The linter asserts the two manifests agree.

- [ ] **Step 5: Run the final contradiction sweep by hand**

The spec requires searching the whole plugin for anything that could reintroduce
the old behaviour. The automated sweeps cover the banned phrases; this step
covers the ones a human has to judge.

```bash
grep -rniE 'subagent-driven-development|task review|re-?review|fix round|passed task|reviewer after|phase complete|\bRV\b|pre-RV|most capable model|next phase|advance' \
  plugins/superb README.md .claude-plugin .agents \
  | grep -v '^plugins/superb/skills/craft/' \
  > /tmp/sweep.txt
wc -l /tmp/sweep.txt
```

Read every line. For each, confirm it is one of:
- a phase-level rule (correct),
- `references/implement.md` or a linter comment explaining what was removed
  (correct),
- `superb:bug-fix` using SDD at its own task scope (correct, out of scope),
- an `RV`/advance rule that now names the fix-plan and ledger conditions
  (correct).

Any line that **requires a reviewer after an individual task**, or that lets the
next phase begin because task lines are `[x]`, is a defect — fix it and note it
in the commit. Specifically re-read:

```bash
sed -n '80,90p' plugins/superb/skills/pipeline/references/parallel.md
sed -n '465,475p' plugins/superb/skills/pipeline/SKILL.md
sed -n '108,118p' plugins/superb/skills/pipeline/references/fix-loop.md
```

`parallel.md:82-84` and `SKILL.md:471` gate **wave** `k` on wave `k-1` being
`[x]` and merged. That is correct and must stay: waves are intra-phase, and
gating a wave on commits rather than on a review is the whole point. Do not
"fix" those two.

`fix-loop.md:113`'s `- **Minor-only or none** → phase passes; **advance** to the
next phase.` reads standalone as a findings-only predicate. Make it name the
gate:

```markdown
   - **Minor-only or none** → the phase passes **once its `RV` is `[x]` and the
     close-out write below has landed**; then advance. Findings alone never
     license the advance — an empty ledger is what an unreviewed phase looks
     like too.
```

- [ ] **Step 6: Full verification**

```bash
./tools/check-plugin.sh
./tools/check-plugin.sh --run tools/fixtures/run-ok
./tools/check-plugin.sh --run tools/fixtures/run-open-rv
./tools/check-plugin.sh --run tools/fixtures/run-fixloop
./tools/check-plugin-mutants.sh
python3 -m unittest discover -s plugins/superb/skills/craft/tests
```
Expected: four `check-plugin: PASS`; the mutant harness with zero `SURVIVED`;
the craft suite unchanged and green (it must be — nothing here touches craft).

Confirm the git state is clean of anything unintended:

```bash
git status --short
git log --oneline main..HEAD
```

- [ ] **Step 7: Commit**

```bash
git add README.md plugins/superb .claude-plugin .agents
git commit -m "docs(superb): the promise is per-phase review, and superb 0.12.0

README promised that every task is reviewed by an agent that did not write it,
which was true and was the cost. The promise is now what the skill does:
every phase is reviewed as a unit over ranges covering its whole diff, and no
phase advances until its review and fix rounds close. Stage 4's entry in the
composed-skills table is pipeline's own implement.md."
```

---

# Phase 5 — Whole-change migration review

Tasks 1–11 are mechanically gated: every arm goes RED before its change and
GREEN after, and every arm has a mutant proving it can fail. That establishes
that each rule is *enforced*. It does not establish that the rules are
*coherent with each other*, that no path advances early, or that an arm proves
what its name claims. That is what this phase is for.

**This is one review of the completed migration — not a review per task.** It
runs after all implementation is complete and all mechanical gates are green,
and its outcome is the release acceptance for this work. Task 11's version bump
names the version this migration will ship as; it is not the acceptance. If
Phase 5 raises blocking findings, the migration is not accepted until Task 13
closes them.

The phase is itself an instance of the state machine this plan installs, which
is the cheapest available proof that the machine is workable:

```
implementation complete + gates green
  → REVIEW      (Task 12: 1–2 independent strong reviewers, all return first)
  → DECIDE      (Task 13: consolidate, dedup, stable IDs, severity)
  → FIX_PLAN    (Task 13: one migration fix plan)
  → FIX_IMPLEMENT
  → RE_REVIEW   (Task 13: focused on the fix diff)
  → PASS        (Task 13: final verification, acceptance)
```

---

### Task 12: Review the whole migration

**Files:**
- Create: `docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine/agent-output/migration-review-a.md`
- Create: `docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine/agent-output/migration-review-b.md` (only if two reviewers are dispatched)
- Create: `docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine/findings.md`

**Interfaces:**
- Consumes: the complete diff of Tasks 1–11.
- Produces: the reviewer report files Task 13 consolidates, and the findings
  ledger it works from.

- [ ] **Step 1: Establish the review range and confirm the gates are green**

```bash
git log --oneline main..HEAD
git diff --stat main..HEAD
./tools/check-plugin.sh
./tools/check-plugin.sh --run tools/fixtures/run-ok
./tools/check-plugin.sh --run tools/fixtures/run-open-rv
./tools/check-plugin.sh --run tools/fixtures/run-fixloop
./tools/check-plugin-mutants.sh
```

Expected: eleven commits (Tasks 1–11), four `check-plugin: PASS`, and the
mutant harness with zero `SURVIVED`. **Do not dispatch reviewers over a red
gate** — they would spend their attention on something a command already found.

- [ ] **Step 2: Size the fan-out**

**1–2 reviewers, at the strongest available model.** Not one per task, and not
one per file. Two is the normal choice here because the change has two
genuinely different failure surfaces, and one reviewer holding both tends to
read the prose and skim the Python:

- **Reviewer A — the state machine and its prose:** `SKILL.md`,
  `references/implement.md`, `references/fix-loop.md`, `references/parallel.md`,
  `references/run-state.md`, `templates/*`, and the three READMEs.
- **Reviewer B — the gates and their evidence:** `tools/check-plugin.py`,
  `tools/check-plugin-mutants.sh`, `tools/fixtures/*`,
  `.github/workflows/checks.yml`, and the manifests.

Each reads the **whole** `main..HEAD` diff; the split assigns *ownership of the
verdict*, not the reading. One reviewer is acceptable only if the diff came in
materially smaller than planned — say the fixtures were folded into an existing
one — and the reason is recorded on the round.

Do not add a third "integration" reviewer by reflex: the boundary between the
two surfaces is exactly what the checklist's *prose ↔ linter ↔ fixture ↔ mutant*
item makes both of them responsible for. That is the rule Task 6 installs,
applied to this review.

- [ ] **Step 3: Dispatch, with this checklist in each prompt**

Each reviewer returns a report file and nothing long in its reply. Both prompts
carry the spec path, the plan path, the `main..HEAD` range, and this list:

1. **Accidental reintroduction of task-level review** — any instruction, in any
   file, that dispatches a reviewer, a fix, or a re-review on the completion of
   an individual task.
2. **Any path that advances before `RV` passes** — including a close-out
   ordering that writes `Current State` forward before the `RV` condition is
   checked, and any predicate phrased so that an empty ledger satisfies it.
3. **State-machine contradictions** — a state named in one file with different
   entry or exit conditions in another; the digraph disagreeing with the prose;
   an edge into a later phase from anywhere but `PASS`.
4. **Resume behaviour** — does the precedence table give exactly one valid next
   action for each on-disk state, and does any row permit re-running a
   completed implementation task or advancing?
5. **Open-findings precedence** — a blocking F-ID must outrank the tracker's
   next unchecked line. Check the case where every box is `[x]`.
6. **Fix-plan bypasses** — any route from findings to a fix dispatch that does
   not pass through a fix plan on disk, including a round form the linter's
   regex does not reach.
7. **Pre-`RV` implementation repair becoming a second fix loop** — the repair
   path must raise no finding, take no F-ID, need no plan and spend no budget.
   Flag any wording that gives it a round, a counter or a state.
8. **Unnecessary integration reviewer spawning** — anything that makes `i=1`
   automatic again, or that lets a multi-slice round omit the boundary
   declaration silently.
9. **Stale SDD delegation** — any surviving instruction that pipeline's
   implementation runs through `subagent-driven-development`. Historical
   explanations of why it does not are correct and must be left alone; so is
   `superb:bug-fix`'s own use of it.
10. **Model-selection instructions that force expensive models unnecessarily** —
    any dispatch template or prose that defaults to the strongest tier instead
    of choosing one.
11. **Mismatches between prose, tracker grammar, linter rules, fixtures and
    mutants** — the four must describe the same grammar. A field required in
    prose but unreachable by the regex, or a fixture conforming to a rule no
    file states, is a finding.
12. **Tests that appear to enforce an invariant but can pass without proving
    it** — for each new arm, ask what a conforming-but-wrong input looks like
    and whether the arm catches it. Check that each mutant fails for *its own*
    reason: a mutant that also breaks a second rule is killed by whichever arm
    fires first and proves nothing about its own.

Also require of each reviewer: **re-run the gates yourself.** A report that
takes `check-plugin: PASS` from this plan rather than from its own terminal has
verified nothing.

- [ ] **Step 4: Wait for every reviewer to return**

```
ALL REVIEWER REPORTS MUST BE IN HAND BEFORE ANY FIX IS DISPATCHED.
```

Reviewer A returning a finding while Reviewer B is still out does **not** start
a fix. This is the same rule the migration installs at `REVIEW` (Task 4), and
breaking it here would be the plan contradicting itself on its own change.

- [ ] **Step 5: Record the round**

Write the review round into the run's tracker (or, if no run directory was
created for this migration, into `findings.md`'s header) in the same grammar
this plan installs, so the round is auditable by the linter it ships:

```
- [x] RV — migration review · N=11 → 2 slice + 0 integration · no integration boundary
      · reports migration-review-{a,b}.md · coverage migration-coverage.md → F-001, F-002
```

Adjust `N`, the counts and the outcome to what actually happened. If a single
reviewer was used, the form is `N=11 → 1 slice + 0 integration`.

---

### Task 13: Consolidate, remediate, re-review, accept

**Files:**
- Create: `docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine/agent-output/migration-fixplan-r1.md`
- Modify: whatever the findings name
- Modify: the run's `findings.md`

**Interfaces:**
- Consumes: Task 12's reports.
- Produces: the acceptance for this migration.

- [ ] **Step 1: Consolidate and decide**

Dedup the reports into one ledger with stable IDs and three tiers — Critical /
Major / Minor, ties resolving upward — exactly as the phase machinery this
migration installs requires.

- **No Critical/Major** → skip to Step 5. Minor findings are recorded and
  carried, not fixed here.
- **Any Critical/Major** → Step 2. **The migration is not accepted.**

- [ ] **Step 2: Write one migration fix plan**

Write it to `agent-output/migration-fixplan-r1.md` from
`templates/fix-plan.md` — the template this migration adds, used on itself.
One row per fix agent, not per finding: findings sharing a file cluster share an
agent.

No fix is dispatched before this file exists.

- [ ] **Step 3: Implement the fixes**

One agent per independent file cluster the plan names; related findings batched.
Tier each dispatch by the fix's own complexity (a one-line correction with an
exact `file:line` is a cheap-tier dispatch), not by the size of the migration.

Each fix agent re-runs the gates its change touches and reports the output.

- [ ] **Step 4: Focused re-review**

One reviewer over the **fix diff**, sized by its file clusters — not a rerun of
Task 12. It answers: were the blocking findings actually resolved; did the fixes
introduce a regression; do the fixes interact; does the migration still satisfy
the spec.

If blocking findings remain, return to Step 2 for round 2. **The migration stays
in Phase 5** — there is no next phase to advance into, which is the invariant
holding in its simplest form.

- [ ] **Step 5: Final verification and acceptance**

```bash
./tools/check-plugin.sh
./tools/check-plugin.sh --run tools/fixtures/run-ok
./tools/check-plugin.sh --run tools/fixtures/run-open-rv
./tools/check-plugin.sh --run tools/fixtures/run-fixloop
./tools/check-plugin-mutants.sh
python3 -m unittest discover -s plugins/superb/skills/craft/tests
git status --short
git log --oneline main..HEAD
```

Expected: four `check-plugin: PASS`; zero `SURVIVED` and zero `no-op`
diagnostics from the harness; the craft suite green and untouched; a clean
worktree; and no commit in the range that this plan did not ask for.

Then the stale-concept sweep, which must come back empty of *operative* uses:

```bash
grep -rniE 'per-task review|passed task review|task reviewer|pre-RV|most capable model available' \
  plugins/superb README.md .claude-plugin .agents \
  | grep -v '^plugins/superb/skills/craft/'
```

The only acceptable hits are historical explanations of why Stage 4 no longer
delegates to `subagent-driven-development`, and `superb:bug-fix`'s own use of
it at task scope. Anything else is a finding — go back to Step 2.

- [ ] **Step 6: Commit the remediation, if any**

```bash
git add -A
git commit -m "fix(pipeline): close the whole-change review's blocking findings

<one line per finding closed, with its ID>"
```

Do not push, publish, merge, or open a PR — the plan's global constraint holds
through acceptance.

---

## Self-Review Notes

Checked against the spec after writing:

**Spec coverage.** Every numbered requirement maps to a task: an
implementation-only primitive → Tasks 1–3; Stage 4 as a state machine → Task 4;
the required fix plan → Task 5; the conditional integration reviewer → Task 6;
fix agents sized by cluster → Task 10; tracker and resume → Tasks 5, 9;
deleting what the graft required → Tasks 3, 5, 10; documentation → Task 11;
acceptance of the migration itself → Tasks 12, 13. Every gate in the spec's gate
table maps to an arm: no-task-review and no-SDD sweeps → Task 3;
review-not-early → Task 7; no-advance → Task 8; fix-plan-precedes-fix → Task 5;
conditional-integration → Task 6; resume fixtures → Task 9.

**Three things the plan deliberately does not do.**

1. **It does not delete the fix-mode recursion.** The spec asks for
   simplification, and collapsing fix-mode into a plain in-phase loop is
   tempting, but the recursion carries the depth cap, the Counters rows and the
   convergence rule that stop a phase looping forever. Task 5 inserts the
   required plan *into* that machinery rather than replacing it. If the
   recursion should go, that is a follow-up with its own spec — removing a
   termination guarantee is not a simplification to do in passing.
2. **It does not touch `superb:bug-fix`'s use of SDD.** SDD's per-task contract
   is correct at task scope, and `bug-fix` has no phase gate to mis-gate — which
   is the linter's own recorded reason for scoping the tier arm to pipeline.
3. **It does not review this migration task by task.** The header requires
   `superpowers:executing-plans`, and the one LLM review is Phase 5 over the
   whole change. Each task's verification is its linter arm going RED then
   GREEN, which is mechanical and needs no reviewer agent. Using SDD to execute
   a plan whose purpose is to delete per-task review would pay the exact cost
   the work removes.

**One concept the plan removes rather than keeps.** The pre-`RV` fix loop — a
formal remediation round entered when a wave's build gates failed, with its own
Counters row while `RV` stayed `[ ]` — is deleted in Task 5, Step 4b. There is
now exactly one formal remediation state machine
(`REVIEW → FIX_PLAN → FIX_IMPLEMENT → RE_REVIEW`), and it has one entry: a
review returning blocking findings. A red gate before any reviewer exists is
unfinished implementation, repaired inside IMPLEMENT and re-gated there. This
does **not** relax IMPLEMENT's exit condition — the work must have landed and
the gates must be green — it only stops a pre-review failure from acquiring
findings, a budget and a state it does not need.

**Known risk, and where it bites.** Tasks 4, 5 and 6 edit prose that
`tools/check-plugin.py` holds **byte-identical across four files**
(`SKILL.md`, `references/fix-loop.md`, `references/run-state.md`,
`templates/progress.md`). A paraphrase in one file fails an arm naming a phrase,
not a concept, and the remedy is always to restore the phrase verbatim rather
than to weaken the arm. Every one of those tasks runs the full gate before its
commit for exactly this reason.

**Ordering constraint.** Task 7's `parse_tracker_phases` is consumed by Task 8,
and Task 9's fixtures are the happy paths for the arms in Tasks 5, 6, 7 and 8 —
so Phase 3's tasks are sequential, not a wave. Phase 1's Tasks 1 and 2 are
independent of each other; Task 3 depends on both. Phase 5 is strictly last:
Task 12 may not dispatch over a red gate, and Task 13 is the acceptance, so
Task 11's version bump names the version this ships as rather than closing the
work.

---

## Execution log — deviations from the plan as written

Kept here rather than by rewriting the task text, so Phase 5 reviews the plan
that was approved plus an honest record of where reality differed. Each entry
says what changed and why.

### Task 1

- **Arm placement moved.** The plan said insert immediately before
  `print("\n== pipeline review-line examples ==")` (then line 1202).
  `relpath` is defined at `tools/check-plugin.py:1285`, *below* that point, so
  the arm raised `NameError` on its first FAIL. Both Task 1's and Task 3's
  sections now sit immediately after that section's closing `ok(...)`, which is
  below every helper they use. Recorded as a Global Constraint.
- **Mutant placement moved.** "Append to `tools/check-plugin-mutants.sh`" was
  read literally as append-to-EOF, which put the new `run_mutant` calls after
  the harness's `killed=…` summary and its `exit 1` — uncounted, and unreachable
  whenever an earlier mutant survives. They now sit immediately before the
  summary. Recorded as a Global Constraint.

### Task 2

- **The Overview's composition claim had to change.** Not in the plan. The
  Overview asserted pipeline "never reimplements brainstorming, planning,
  implementation, or review"; owning the dispatch makes the third false. It now
  claims the other three and records implementation dispatch as the one
  deliberate exception, with the reason (every available implementation skill
  accepts a task only against a review it dispatches for that task, which is a
  second acceptance gate for work accepted at the phase).

### Task 3

- **A fifth sweep pattern was added:** `reviewed per task`. The four patterns
  the plan specified did not catch `SKILL.md:475` — "members are **reviewed per
  task** exactly as `subagent-driven-development` prescribes" — because that
  sentence has no `via`, so the SDD-delegation pattern missed it and no other
  pattern matched. A fourth mutant, `"pipeline reviews wave members per task"`,
  proves the new arm can fail.
- **Two extra sites had to be fixed for the sweep to go green**, both outside
  the plan's list for this task:
  - `SKILL.md:18` — the Overview carve-out written in Task 2 itself said "a
    per-task review it dispatches itself", tripping the sweep it exists to
    explain. Reworded to "a review it dispatches for that task".
  - `references/fix-loop.md:326-334` — the fix-mode implementation paths
    delegated to `subagent-driven-development` ("Standard path: plan
    (`writing-plans`) → implement (`subagent-driven-development`)" and
    "Direct-fix path … Implement directly via `subagent-driven-development`").
    The plan deferred this text to Task 5, but the sweep reads the whole skill,
    so leaving it would have kept the gate red from this commit through Task 4.
    Both paths now implement per `references/implement.md`, and the
    "Direct-fix path" is renamed **"Small-round path"** with its planning
    exemption already removed — which is Correction 2's requirement arriving one
    task earlier than planned. **Task 5 Step 4 must therefore replace the
    renamed text, not the original.**

### Task 5 (adjustment required by the above)

- Step 4's anchor is no longer the `Standard path` / `Direct-fix path` block as
  quoted. The block now reads `Standard path` / `Small-round path`, already
  pointing at `references/implement.md` and already requiring a plan. Step 4's
  job narrows to: replace it with the ordered
  `FINDINGS → FIX PLAN → FIX IMPLEMENTATION` block and the "scale the plan,
  never skip it" paragraph, and keep the ≤3-findings case as a *small plan*
  rather than a second path.

### Task 4

- **The digraph's `RVJ` edge was split.** The plan gave `Stage 4b` one outgoing
  edge labelled `findings / next phase`, which conflates two outcomes: a joint
  review with blocking findings must enter `FIX_PLAN`, not the next phase's
  `IMPLEMENT`. It is now two edges — `blocking findings → FIX_PLAN` and
  `clean / next phase → IMPLEMENT`. As written it was a state-machine
  contradiction of the kind Task 12's checklist item 3 hunts for.
- **The Stage 4 rewrite silently disarmed an existing arm, and the mutation
  harness is what caught it.** The plan's replacement text said "a finding
  arriving in another vocabulary is **re-tagged** by the predicate in
  `references/fix-loop.md`", dropping the phrase
  ``an incoming `Important` is re-tagged`` from `SKILL.md` altogether. Two
  consequences, neither visible on a green `check-plugin.sh`:
  1. the fourth-severity-tier arm passed **trivially** — with no `Important`
     mention left in the skill, an arm that requires the tier to be named only
     alongside its re-tag rule has nothing to check;
  2. the mutant proving that arm can fail
     (`"fourth severity tier named without its re-tag rule"`) became a no-op,
     which the harness reports as `SURVIVED`.

  Fixed by restoring the phrase verbatim in `DECIDE` rather than by retargeting
  the mutant: the doc is better for saying what happens to an incoming
  `Important` at the point where consolidation happens, and the arm keeps its
  subject. **General lesson for Tasks 5, 6 and 10, which all rewrite held
  prose:** an arm whose subject vanishes from the docs does not fail — it starts
  checking nothing. Only the harness sees that. Run it after every prose rewrite
  and read the `SURVIVED` diagnostics.
