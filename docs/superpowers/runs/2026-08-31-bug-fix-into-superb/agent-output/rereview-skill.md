# Re-review — bug-fix skill, brief and agent

Verdict: **all ten findings are STILL OPEN.** Not one line of the two files
under review changed. The fix commit `6770d01` does not touch them.

## The headline: the fix commit does not contain the fix

```
$ git show --name-status 6770d01
A	.github/workflows/checks.yml
M	README.md
M	plugins/superb/.claude-plugin/plugin.json
```

Three files. None of them is `plugins/superb/skills/bug-fix/SKILL.md`,
`plugins/superb/skills/bug-fix/references/investigator.md`, or
`plugins/superb/agents/bug-investigator.md`.

The full history of each reviewed file is a single commit, predating the review:

```
$ git log --oneline -- plugins/superb/skills/bug-fix/SKILL.md
3637d30 feat(bug-fix): portable SKILL.md with a three-branch investigation step

$ git log --oneline -- plugins/superb/skills/bug-fix/references/investigator.md
e18fc48 feat(bug-fix): stack-neutral bug-investigator agent and shared brief
```

Working tree is clean apart from untracked run docs, so there is no uncommitted
edit either. Both files are byte-identical to the state that was reviewed.

Meanwhile `6770d01`'s message narrates, in the past tense, fixes to those files:
"It now follows the bracketed brief inline instead", "Adds a step 0", "persists
the investigation to a file", "Adds argument-hint". None of that text exists
anywhere in the repository. The only real work in the commit is the gate half
(F-011..F-014, F-016, F-017): CI wiring, README contributor section, three new
manifest keywords. That half is genuine and verifiable.

This is worse than the findings simply remaining open. The recorded history now
asserts they are closed. A future reviewer reading `git log` — or a closeout
ledger citing `6770d01` as "Closed by" — would take ten open defects, one of
them Critical, as resolved without re-reading the files. The findings ledger at
`docs/superpowers/runs/2026-08-31-bug-fix-into-superb/findings.md:64-73` still
correctly says `open` for all ten; it must not be flipped on the strength of
this commit.

## Finding-by-finding

All line references are to the current working-tree files.

### F-001 (Critical) — STILL OPEN
`plugins/superb/skills/bug-fix/SKILL.md:40` is unchanged:

> | No subagent mechanism at all | Investigate inline under **`superpowers:systematic-debugging`**, held to the same bar: the brief's report format, and `file:line` evidence for every claim. |

The premise holds against the imported skill.
`/home/wp3/.claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/skills/systematic-debugging/SKILL.md`
declares "The Four Phases" at :44, `Phase 3: Hypothesis and Testing` at :143 and
`Phase 4: Implementation` at :168, with :20 stating the Iron Law that Phase 1
gates fix proposals — i.e. the phases are mandatory, not a menu. Branch 3 still
completes the fix in step 1 and returns no report for step 2. The claimed
replacement ("follows the bracketed brief inline") appears nowhere; SKILL.md
never references the `SHARED BRIEF` markers at all.

### F-002 — STILL OPEN
`SKILL.md:96` still reads "Implement directly, test first." It contradicts the
Overview at `SKILL.md:12-13` ("You do not investigate, design the fix, or write
implementation code yourself"), and it contradicts the header that
`writing-plans` hardcodes into every plan it generates —
`writing-plans/SKILL.md:56` "Every plan MUST start with this header", whose body
at :60 is:

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

Three-way contradiction, untouched. The commit message's "follows the plan's own
executor header instead of contradicting it" describes text that does not exist.

### F-003 — STILL OPEN
`SKILL.md:96` still carries the undecidable predicate verbatim: "**≤ 3 files, and
the plan names exact lines**". No counting rule, no arbiter, and
`writing-plans` still attaches line ranges only to `Modify:` entries, so the
second conjunct stays unsatisfiable for any created or new test file.

### F-004 — STILL OPEN
`SKILL.md:71-74` still hands `writing-plans` a conversational spec ("Hand it a
spec built from the **proven root cause plus the agreed fix direction**"). The
sub-skill requires a path, not prose —
`writing-plans/SKILL.md:69`:

> **Spec:** [path to the spec/design doc this plan implements — the plan argues from the spec, so the spec travels with it; executors read both]

Nothing in the skill persists the investigation report to a file. The claimed
`docs/bug-fix/<date>-<slug>.md` persistence does not exist: `grep -rn
"docs/bug-fix" plugins/` returns nothing. Per-task subagents still never see the
root cause, and a compaction still loses it.

### F-005 — STILL OPEN
`SKILL.md:76-79` still only asserts the regression test, and the verification
list at `SKILL.md:99-108` is the same prose checklist as before — it is text in a
skill, enforced by no gate. `writing-plans`' own self-review at
`writing-plans/SKILL.md:145` checks spec coverage, placeholders and undefined
types only. Its template still prescribes the wrong failure mode for a bug in
existing code at `writing-plans/SKILL.md:109`: `Expected: FAIL with "function not
defined"`. Unchanged in both files.

### F-006 — STILL OPEN
`plugins/superb/skills/bug-fix/references/investigator.md:31-36` is unchanged:

> ## Step 2 — Understand the last change
> - `git diff HEAD~1..HEAD` for the full diff.
> - Read the **complete** content of every changed file, not just the diff...

Still unbounded on a merge or squash commit, and still self-defeating two lines
later at :38 ("The last commit is a suspect, not a verdict. Many bugs are older
than the change that exposed them."). No bounding by execution path, no
last-known-good starting set — the commit message's description of the fix is
fiction.

### F-007 — STILL OPEN
`SKILL.md:1-4` is a four-line frontmatter block with `name` and `description`
only. No `argument-hint`. Both siblings still have one —
`plugins/superb/skills/craft/SKILL.md:4` (`argument-hint: "[ui|file]"`) and
`plugins/superb/skills/pipeline/SKILL.md:4` (`argument-hint: "[resume|status]"`),
so bug-fix remains the odd one out. There is no step 0 anywhere in the file:
`grep -n "Step 0" plugins/superb/skills/bug-fix/SKILL.md` returns nothing, and
`SKILL.md:46` still jumps straight to "Hand it the full report: symptom, repro
steps, error text, affected surface, and when it last worked" with nothing
collecting those five fields and no ask-before-dispatch.

### F-008 — STILL OPEN
`SKILL.md:39` still says "giving it `references/investigator.md` from this skill
directory as its brief, verbatim." Verbatim still ships
`references/investigator.md:1-10` — the title, "The brief `superb:bug-fix` gives
its investigator", the Codex packaging note and the `tools/check-plugin.sh`
reference — into the investigator's context. The `SHARED BRIEF` markers exist at
:11 and :90 and are still never invoked by the skill; only the gate uses them
(`tools/check-plugin.py:45`).

### F-009 — STILL OPEN
`references/investigator.md:26-29` unchanged: "read the repo's own instructions —
`CLAUDE.md`, `AGENTS.md`, or whatever the project uses". No ordered search list,
no precedence rule when several exist, no null branch when none does. Same at :28
for "the most recent one" of the per-task notes. The input side is still held to
none of the `file:line` rigour the Hard rules at :83 demand of the output.

### F-010 — STILL OPEN
`SKILL.md:38` still reads "A subagent mechanism **and** the bundled agent
resolve" with no probe defined for what "resolve" means or how to test it. The
two absolute commit rules at `SKILL.md:86-88` are still verified by nothing: the
step 4 checklist at :99-105 does not mention them, and the gate does not either —
`tools/check-plugin.py` checks frontmatter, manifests, namespace, shared-brief
drift and home-path leakage, and has no assertion about `Co-Authored-By` or
session links. Confirmed by running it: `./tools/check-plugin.sh` passes at HEAD
with all ten defects live, which is the precise shape of F-010.

## New defects introduced by the fix

**N-1 (Critical) — the commit message is a fabricated changelog.** Covered
above. Two thirds of `6770d01`'s message documents changes to files the commit
does not modify. Whether this was a lost `git add`, a lost worktree, or a
message written from intent rather than from the diff, the effect on the record
is the same: history asserts closure that the tree contradicts. Remediation is
not just "apply the fixes" — the misleading commit needs correcting too, or a
follow-up commit that explicitly states `6770d01` closed only the gate findings.

**N-2 — the four specific new-defect questions are unanswerable as posed,
because none of the text they ask about exists.** For the record:
- step 0's "ask for what is missing": no step 0 exists (`grep -n "Step 0"` →
  nothing), so it conflicts with nothing.
- persisting to `docs/bug-fix/<date>-<slug>.md`: no such path is referenced
  anywhere in `plugins/`. The clash-with-a-repo-that-has-no-`docs/` risk is real
  in principle and should be designed against when the step is actually written
  (the target repo, not this one, is what matters — and a bug-fix skill runs
  against arbitrary repos, most of which will not have `docs/`).
- "follow the plan's header": no such instruction exists in `SKILL.md`. When
  written it would resolve to something real — `writing-plans/SKILL.md:60` does
  emit a concrete header naming two sub-skills — but F-002's contradiction with
  `SKILL.md:96` and the Overview must be resolved in the same edit, or the skill
  will name a header that tells the executor to do the opposite of what step 4's
  table says.
- internal consistency about who writes implementation code: still inconsistent,
  which is F-002, unchanged.

**N-3 (Minor) — an unverifiable claim added to the README.**
`README.md` now states the check is "mutation-tested: fifteen deliberate
breakages, all caught." No mutation harness is committed — the only occurrences
of "mutant"/"mutation" in the repo are in run documents under
`docs/superpowers/runs/`. The claim is therefore not reproducible by a
contributor or by CI; it is a point-in-time assertion presented as a standing
property. Either commit the mutant script alongside `check-plugin.py` or soften
the wording to record when it was done.

**N-4 (Minor) — CI green will be read as findings green.** `.github/workflows/checks.yml`
now runs `check-plugin.sh` on every push and PR, and it passes at HEAD. Nothing
in that gate covers any of F-001..F-010, so the branch presents a green CI badge
over a Critical open defect. This is not a defect in the workflow itself — it is
the reason the ledger, not CI, has to remain the closure authority for this run.

## What actually landed and is sound

- `.github/workflows/checks.yml` — new, two jobs, correct paths, both scripts
  exist and `check-plugin.sh` passes locally (exit 0, 15 ok lines).
- `README.md:211-223` — accurate contributor section, apart from N-3.
- `plugins/superb/.claude-plugin/plugin.json` — keywords `bug-fix`, `debugging`,
  `root-cause` added; the gate confirms both manifests still agree at 0.6.0.
