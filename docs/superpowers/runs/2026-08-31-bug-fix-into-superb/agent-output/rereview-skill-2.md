# Re-review 2 — `superb:bug-fix` skill surface

Verified against the **working tree** at `feat/bug-fix-into-superb`
(HEAD `b0bddc5`, tree clean apart from this run directory). Composition claims
were judged by reading
`~/.claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/skills/{writing-plans,subagent-driven-development,executing-plans,systematic-debugging}/SKILL.md`,
not by accepting the skill's description of them.

Files read in full:

- `plugins/superb/skills/bug-fix/SKILL.md` (155 lines)
- `plugins/superb/skills/bug-fix/references/investigator.md` (99 lines)
- `plugins/superb/agents/bug-investigator.md` (96 lines)

`tools/check-plugin.sh` runs green, and the two `SHARED BRIEF` blocks are
byte-identical (`md5 32c13a02…`, 88 lines each).

---

## Part 1 — the ten findings

### F-001 (Critical) — CLOSED

`SKILL.md:53-59` is now a three-branch table and branch 3 reads *"Follow that
same bracketed brief **yourself, inline**, including its 'modify no files' rule,
and produce its report format before continuing."* The referent is branch 2's
"text between the `SHARED BRIEF` markers in `references/investigator.md`".
`systematic-debugging` appears nowhere as an investigator; it is explicitly
excluded twice, at `SKILL.md:68-70` and as a red flag at `SKILL.md:148-149`,
and the stated reason matches the skill as written — its Phase 3 step 2 tests a
hypothesis by making "the SMALLEST possible change" to code
(`systematic-debugging/SKILL.md:152-156`) and Phase 4 creates the failing test
and implements the fix (`:168-189`). The composition claim is accurate.

Residual, cosmetic: branch 3 calls it the "bracketed brief" while branch 2 calls
it the `SHARED BRIEF` markers, and the markers are HTML comments, not brackets.
Unambiguous by position, but the two rows should use one name.

### F-002 (Major) — CLOSED

"Implement directly" is gone — `grep -i "implement directly\|directly"` over
`SKILL.md` returns nothing. `SKILL.md:118-126` now says the plan carries an
executor header and *"Follow the plan's header"*, taking
`superpowers:subagent-driven-development` where a subagent mechanism exists and
`superpowers:executing-plans` where none does. That resolves against a real
artifact: `writing-plans/SKILL.md:61` mandates the header line *"REQUIRED
SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
superpowers:executing-plans"* in **every** plan, so "where the header offers the
choice" is always true and the instruction is never undefined.

The Overview no longer claims the conductor writes nothing —
`SKILL.md:11-14` says investigation and implementation go to a specialist
*"wherever one is available"*, which is consistent with the no-subagent branch
where the conductor executes inline. The skill is internally consistent about
who writes implementation code.

### F-003 (Major) — CLOSED

The undecidable predicate is deleted outright, not restated: no "≤3", no "three
files", no "exact lines" anywhere in `SKILL.md`. Step 4 now routes on a single
decidable fact (is a subagent mechanism available) plus the plan header. Nothing
in the file asks anyone to count files or to guarantee line ranges that
`writing-plans` only emits on `Modify:` entries.

### F-004 (Major) — CLOSED (but see N-003)

`SKILL.md:78-83` requires persisting the investigation report to a file before
planning, and `SKILL.md:100-101` hands `writing-plans` *"the Step 2 file as its
`Spec:` path"*. That matches `writing-plans/SKILL.md:69-70`, which requires a
**path** for `Spec:`. The text closes the finding as written. The delivery
mechanism has a new hole — N-003.

### F-005 (Major) — CLOSED (but see N-001)

Two things were missing and both are now present. Enforcement:
`SKILL.md:128-139` makes "The regression test fails without the fix" verification
item 1 and adds *"The fix is not done until step 1 has actually been run"*, plus
the red flag at `:152-153`. Template correctness: `SKILL.md:103-107` says to
state the expected failure explicitly and that for a bug in existing code it is
a wrong value or a raised error, *"**not** 'function not defined', which is what
the plan template's own example assumes"* — verified against
`writing-plans/SKILL.md:106-109`, which does literally read
`Expected: FAIL with "function not defined"`.

The enforcement step is mechanically broken, however; that is N-001, a defect
the fix introduced rather than one it failed to close.

### F-006 (Major) — CLOSED

`investigator.md:37-42` (and the identical `bug-investigator.md:34-39`) now
bounds the read: *"Read the **complete** content of changed files … but **bound
this by relevance, not by the commit**. A merge or a squash can touch hundreds
of files. Read in full only those on the execution path you are tracing in Step
3."* It also adds the last-known-good alternative
(`git log --oneline <good>..HEAD`) and states plainly that *"The last commit is a
suspect, not a verdict"* — which resolves the self-contradiction the finding
named.

### F-007 (Major) — CLOSED

All three legs are present. `argument-hint: "[the bug report]"` at
`SKILL.md:4`, matching both siblings (`craft/SKILL.md:4`, `pipeline/SKILL.md:4`).
The invocation argument is handled at `SKILL.md:31-32` (*"The invocation argument
usually supplies one or two"*). Ask-before-dispatch is mandatory at
`SKILL.md:42-45`, with `unknown` explicitly allowed as a recorded value and a
stop condition when the symptom itself is unclear.

### F-008 (Minor) — CLOSED

`SKILL.md:58` hands over *"the text **between the `SHARED BRIEF` markers**"* and
names the reason (*"those markers exist to keep this skill's packaging notes out
of the brief"*). The markers exist and bracket the packaging preamble correctly:
`investigator.md:1-9` is the preamble, `:11` and `:99` are the markers;
`bug-investigator.md:8` and `:96` are the pair. `tools/check-plugin.sh` reports
them identical.

### F-009 (Minor) — CLOSED

`investigator.md:23-30` now gives the list, the ordering and the null branch:
*"in this order, taking the first that exists: `CLAUDE.md`, `AGENTS.md`,
`CONTRIBUTING.md`, `README.md` … **If none exists, say so in your report and
continue**"*, with the rationale that a silently invented context is the
failure mode. Residual: the session-notes clause at `:32-33` still has no search
list (*"If the project keeps per-task notes or session summaries"*), though it
does now carry an ordering rule — most recent by modification time. Weaker than
the clause above it, but no longer the unbounded "whatever the project uses"
the finding named.

### F-010 (Minor) — CLOSED

The probe exists: `SKILL.md:57` gates branch 1 on *"`superb:bug-investigator`
appears in your available agent types"*, and `:61-62` adds *"Check your actual
agent list rather than assuming. On harnesses with no bundled-agent support the
second branch is the normal path, not a failure."* The two absolute commit rules
(`SKILL.md:114-116`) are now verified by `SKILL.md:135`, verification item 5:
*"The commit carries no attribution trailer and no session link."*

---

## Part 2 — defects the fix introduced

### N-001 (Major) — verification item 1 cannot be run as written, and fails safe in the wrong direction

`SKILL.md:129-131`: *"**The regression test fails without the fix.** Stash or
revert the fix and run it. If it passes, it is not testing the bug — go back to
Step 3."*

By the time Step 4 reaches this item, the fix is **committed**, not sitting in
the working tree. `writing-plans/SKILL.md:98-128` makes every task a five-step
Red-Green-Commit cycle whose Step 5 is `git commit`, and both executors follow
the plan's steps exactly (`executing-plans/SKILL.md:29`; sdd commits per task
and reports commit hashes). So:

- `git stash` on a clean tree stashes nothing and prints "No local changes to
  save". The regression test then runs **with the fix present**, passes, and the
  skill's own rule fires: *"If it passes, it is not testing the bug — go back to
  Step 3."* A correct, properly-tested fix is sent back into planning.
- "revert the fix" is undefined against a multi-commit task series — nothing
  tells the conductor which commits, and `git revert` would itself need
  reverting afterwards.

Worse, the evidence the item actually wants was already produced and thrown
away: `writing-plans/SKILL.md:106-109` makes "Run test to verify it fails" Step 2
of every task, and Step 4 never asks anyone to capture or relay that output.

Fix direction: make item 1 *"the plan's own red step was run and its failure
output recorded"* — obtained from the implementer's report — or, where it must
be re-derived, `git stash` is the wrong tool and the instruction should name
running the test at the pre-fix commit (`git worktree add` at the merge base, or
`git checkout <base> -- <src paths>`), explicitly excluding the test file.

### N-002 (Major) — Step 4's verification is scheduled after the executor has already finished the branch

`SKILL.md:118-135` puts the five verification items *after* the executor runs.
But both executors terminate in branch completion, unprompted:

- `executing-plans/SKILL.md:33-38` — Step 3 "Complete Development" is
  **REQUIRED SUB-SKILL: `superpowers:finishing-a-development-branch`**.
- `subagent-driven-development/SKILL.md:346-359` — "Finishing the Branch" runs
  the full suite and every quality gate, dispatches a whole-branch review and a
  completeness critic, then item 4 is
  `superpowers:finishing-a-development-branch`.

And `finishing-a-development-branch/SKILL.md:14-40` runs the full suite, detects
the environment, **presents merge/PR options and executes the choice, then
cleans up the worktree**. So bug-fix's items 1–5 are reached after the work may
already be merged and the workspace deleted — item 1 in particular needs a
workspace that Step 6 of that skill may have removed. Item 4 ("the repo's own
gates — full suite, linters, build") is also a duplicate of a gate that has by
then run twice.

Step 4 needs to say the executor stops **before** `finishing-a-development-branch`
and hands control back, or that these five items are collected from the
executor's own reports rather than re-run afterwards.

### N-003 (Major) — the persisted report is never committed, so it does not survive into the executor's worktree

`SKILL.md:78-83` writes the investigation report to a file (default
`docs/bug-fix/`) and justifies it precisely by durability: *"the implementers
read the file and your context will not survive to reach them."* Nothing tells
anyone to **commit** it.

Both executors begin by ensuring an isolated workspace —
`executing-plans/SKILL.md:19` ("use superpowers:using-git-worktrees to create one
or verify the existing one") and `subagent-driven-development/SKILL.md:504`,
with sdd cutting *"its own git worktree and branch"* per parallel member
(`:283-285`). `git worktree add` populates from the commit; **untracked files do
not come along**. An untracked `docs/bug-fix/<name>.md` therefore does not exist
at the `Spec:` path inside the executor's worktree, and the plan header points
at a file that is not there — for exactly the fresh-context implementers the fix
was written to reach.

Two smaller points in the same area:

- The `docs/bug-fix/` default is safe to *create* in a repo with no `docs/`
  (`mkdir -p`), and `SKILL.md:80-82` is right that one directory is not a
  structural decision. The hazard is not creation, it is that the directory is
  untracked and unmentioned in `.gitignore` decisions — it silently becomes part
  of the user's next `git add -A`. It also invents a second convention beside
  `writing-plans`' own `docs/superpowers/plans/`.
- `SKILL.md:81-83` claims "the implementers read the file". Under sdd that is
  not literally true: `subagent-driven-development/SKILL.md:297-326` hands each
  implementer a **task brief file** extracted by `scripts/task-brief`, and the
  six things the dispatch must contain do not include the spec path. The
  conductor and the reviewers read the spec; per-task implementers read the
  brief. The persistence is still worth doing — it survives compaction and the
  reviewers do consume it — but the stated reason overclaims.

### N-004 (Minor) — verification item 3 has no branch for the case Step 0 explicitly permits

`SKILL.md:133`: *"The original reproduction from Step 0 no longer reproduces."*
But `SKILL.md:38` lists Reproduction as *"the steps, or `unknown`"* and
`SKILL.md:43` says *"`unknown` is a fine answer and belongs in the brief"*. When
the repro is `unknown` there is nothing to re-run, and the numbered list — which
`SKILL.md:128` says to work through "in this order, recording each result" —
gives no way to record that. Needs an explicit "n/a, and here is what stands in
for it" branch, otherwise it will be silently ticked.

### N-005 (Minor) — two required sub-skills give opposite instructions about who picks the executor

`writing-plans/SKILL.md:153-163` ends with an "Execution Handoff" that puts the
choice to the user: *"Two execution options … **Which approach?**"*.
`SKILL.md:123-126` tells the conductor to decide it unilaterally on subagent
availability. Both are invoked in the same run, one immediately after the other.
The rule bug-fix wants is fine; it should be phrased as *answering*
`writing-plans`' handoff question rather than as an independent decision, or
`writing-plans` will stop and ask and the conductor will have no stated
authority to answer on the user's behalf.

---

## Part 3 — the two consistency questions that came back clean

**Step 0's batched question vs Step 2's "do not manufacture questions"** — no
conflict. The two govern disjoint sets. `SKILL.md:42-45` asks for *missing facts
about the report* (symptom, repro, error text, surface, last-known-good) and
caps it at one batched question. `SKILL.md:85-96` asks for *decisions that are
genuinely the user's* — competing fixes, ambiguous intended behaviour, scope
beyond the symptom, blast radius past the repo — and `"Do not manufacture
questions"` closes that list, not Step 0's. Read together they are a single
coherent policy: ask once for facts you cannot derive, then ask only for
judgments you are not entitled to make.

The one thing neither covers is a **non-interactive run**. Both asks are
unconditional, and `pipeline/SKILL.md:295` points single bug fixes at this skill
from a flow whose standing instruction is to run without user questions. Not a
defect in what was fixed; worth a branch if bug-fix is ever dispatched
autonomously.

**"Follow the plan's header" resolving to something real** — it does.
`writing-plans/SKILL.md:56` says *"Every plan MUST start with this header"* and
`:61` is the executor line naming both skills by their prefixed names. There is
no generated plan in which the header is absent or in which it fails to offer
the choice.
