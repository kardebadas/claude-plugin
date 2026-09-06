# Findings Ledger

IDs are assigned once at first consolidation and **never reused, renumbered or
retired**. A rediscovered finding keeps its original ID. The convergence rule
compares **ID sets**, not prose.

- **Open blocking IDs:** (none)
- **Last updated:** <timestamp>

## Blocking ledger (Critical / Major / bug)

| ID | Sev | Phase | File:line | Finding | State | Closed by |
| -- | --- | ----- | --------- | ------- | ----- | --------- |
| F-001 | Critical | 2 | `src/x.php:41` | <one line> | open | |
| F-002 | Major | 2 | `src/y.php:12` | <one line> | closed | fix `a1b2c3d` + re-review R3 covered it |

**State** is one of `open`, `closed`, `false-positive`. Closing requires either:
the fix diff touched the code the finding names **AND** a re-review whose slice
covered that fix diff reports it resolved; or the **user** ruled it a false
positive. A finding that merely stops appearing in review output stays `open`.

## Counters — the caps are enforced from HERE, not from memory

A compaction empties your context; it does not empty this table. Read these
values before every fix-mode dispatch, and write the increment **before**
dispatching, never after.

| Phase | Fix-loop iteration | Cap | Deepest fix-mode depth this chain | Cap |
| ----- | ------------------ | --- | --------------------------------- | --- |
| 2 | 2 | 5 | 1 | 2 |

Iteration counters are **per phase** (a split's siblings share the split group's
counter); depth is **per recursion chain** — Stage 4's own run of a phase is
depth 0, its first fix-mode recursion is depth 1. Reset the iteration counter by
adding a new row when a new phase starts; never edit another phase's row.

## Iteration log (convergence rule input)

One row per fix-loop iteration, written before the dispatch and completed after
the re-review.

| Iter | Phase | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | 2 | 1 | F-001, F-002 | F-001 | <timestamp> |
| 2 | 2 | 1 | F-001 | F-001 → **stop: no-progress** | <timestamp> |

**No-progress:** an ID appears in `Targeted` and again in that row's `Open
after` → stop, ask the user. **Oscillation:** a row's `Open after` set equals
any earlier row's → stop, ask the user. Neither consumes an iteration, and
neither is a judgment call — both are set comparisons over this table.

## Deferred Minor findings (Stage 5 hand-off)

Never discarded, never blocking. Stage 5 MUST present this table to the user.

| ID | Phase | File:line | Finding |
| -- | ----- | --------- | ------- |
| F-004 | 2 | `src/z.php:88` | <one line> |

## Open blocking

| ID | Sev | Finding | File | Status |
| -- | --- | ------- | ---- | ------ |
| F-001 | **Critical** | Branch 3 composes `systematic-debugging`, which mandates all four of its phases — Phase 3 edits code to test a hypothesis and Phase 4 writes the test and applies the fix. So Step 1 finishes the whole job, breaks "investigate only", and emits no report for Step 2 to read. | `bug-fix/SKILL.md:40` | open |
| F-002 | Major | "Implement directly" contradicts the Overview's "you do not write implementation code", and `writing-plans` hardcodes "REQUIRED SUB-SKILL: subagent-driven-development or executing-plans" into every plan header it generates. | `bug-fix/SKILL.md:96` | open |
| F-003 | Major | The "<=3 files and names exact lines" predicate is undecidable: nobody counts the files, and `writing-plans` puts line ranges on `Modify:` entries only, so it is unsatisfiable for created/test files. | `bug-fix/SKILL.md:96` | open |
| F-004 | Major | Step 3 hands `writing-plans` a conversational spec, but it requires a `Spec:` **path** because executors read both. Nothing persists the root cause, so per-task subagents never see it and a compaction loses it. | `bug-fix/SKILL.md:73` | open |
| F-005 | Major | The failing-first regression test is asserted but enforced by nothing — `writing-plans`' self-review checks only coverage/placeholders/types, and its template expects "function not defined", the wrong failure mode for a bug in existing code. | `bug-fix/SKILL.md:78` | open |
| F-006 | Major | The brief mandates `git diff HEAD~1..HEAD` and reading every changed file **in full** — unbounded on a merge or squash commit, and wasted whenever the bug predates that commit, which the brief itself concedes two lines later. | `bug-fix/references/investigator.md:30` | open |
| F-007 | Major | Step 1 demands a five-field report nothing collects: no `argument-hint` (both siblings have one), no handling of the invocation argument, no ask-before-dispatch. The README's own example supplies two of the five. | `bug-fix/SKILL.md:46` | open |
| F-008 | Minor | Handing `references/investigator.md` over "verbatim" ships its packaging preamble — plugin notes and a reference to `check-plugin.sh` — into the investigator's brief. The `SHARED BRIEF` markers exist for exactly this and are never invoked. | `bug-fix/SKILL.md:39` | open |
| F-009 | Minor | "whatever the project uses" / "the most recent one" has no search list, no ordering rule and no null branch — the input side is held to none of the `file:line` rigour the output side demands. | `bug-fix/references/investigator.md:26` | open |
| F-010 | Minor | "the bundled agent resolve" has no probe behind it, and the two absolute commit rules are verified by nothing in Step 4's checklist. | `bug-fix/SKILL.md:38,86` | open |

| F-011 | **Critical** | The gate passes a plugin whose agent has malformed frontmatter YAML — the agent then loads with "Agent from superb plugin" instead of its real description. `head -1 \| grep '^---$'` reads exactly one line. | `tools/check-plugin.sh:60` | open |
| F-012 | Major | Name checks scan the whole file rather than the frontmatter block, so deleting `SKILL.md` line 1 — leaving no frontmatter at all, so the skill can never trigger — still reports ok. | `tools/check-plugin.sh:50,61` | open |
| F-013 | Major | The namespace prefix is unguarded: renaming `superb`->`superbb` in both manifests passes, because they are only compared to each other, never to the marketplace entry or the directory. | `tools/check-plugin.sh:37` | open |
| F-014 | Major | The gate is wired to nothing — no CI, no git hook, and neither README mentions it. Its only pointer is inside a file that ships to users. | `tools/check-plugin.sh` | open |
| F-015 | Major | Three dangling references outside this repo: `~/.claude/skills/execute-plan-phases/SKILL.md:24` and `block-combat-game/CLAUDE.md:91` point at the deleted personal `bug-fix`; `block-combat-game/CLAUDE.md:61,63` make the also-deleted `/superpipeline` mandatory. | out of repo | open |
| F-016 | Minor | Nine further mutants survive: empty skill README, a skill missing from the *plugin* README, marketplace description drift, version drift vs README, a bogus Codex `skills` path, and reverting either `superb:` prefix fix. | `tools/check-plugin.sh` | open |
| F-017 | Minor | `keywords` in the Claude manifest is the real fifth surface and was never updated — no `bug-fix`, `debugging` or `root-cause`. | `plugins/superb/.claude-plugin/plugin.json` | open |
| F-018 | Minor | The personal `~/.claude/agents/bug-investigator.md` still resolves alongside the bundled one; nothing warns the user it is now orphaned. | out of repo | open |

## Iteration log

| Iter | Phase | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | P1 | 0 | F-001..F-014, F-016, F-017 (F-015 and F-018 are out-of-repo, deferred to hand-off) | pending | 2026-08-31 |
