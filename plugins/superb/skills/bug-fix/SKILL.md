---
name: bug-fix
description: Use when a bug, regression, or unexpected behaviour is reported and the user wants it fixed end to end — "why is X broken", "this stopped working after Y", "fix this crash". Also use when a symptom is known but its cause is not. Not for building new behaviour, and not for a change whose cause is already proven.
---

# Bug Fix

## Overview

Carries a bug from report to validated fix by chaining specialists:
**investigate → decide → plan → implement**. You are the conductor. You do not
investigate, design the fix, or write implementation code yourself — each phase
goes to the right specialist and its result feeds the next.

**Core principle:** no fix is planned until the root cause is proven with
`file:line` evidence, and no plan is written until the open questions are
answered. **Do not guess.** A plausible fix for an unproven cause is worse than
no fix: it consumes the report, closes the ticket, and leaves the bug live.

## When NOT to use

- **Building new behaviour** — that is `superb:craft` then `superb:pipeline`.
- **A change whose cause is already proven** — skip to the fix; the
  investigation step exists to establish a cause, not to ceremonially confirm one.
- **A whole feature's worth of bugs** — that is a phase of `superb:pipeline`,
  which has the fix loop, the findings ledger and the convergence rule.

## Step 1 — Investigate

**Dispatch an investigator. Do not investigate yourself while one is available**
— a separate context is what keeps the conductor from reasoning about
implementation detail it will later have to judge.

Take the first of these that your harness supports:

| Condition | What to do |
| --------- | ---------- |
| A subagent mechanism **and** the bundled agent resolve | Dispatch **`superb:bug-investigator`**. |
| A subagent mechanism, but no bundled agent | Dispatch a general subagent, giving it `references/investigator.md` from this skill directory as its brief, verbatim. |
| No subagent mechanism at all | Investigate inline under **`superpowers:systematic-debugging`**, held to the same bar: the brief's report format, and `file:line` evidence for every claim. |

**Always name the agent with its `superb:` prefix.** A bare `bug-investigator`
resolves to whatever personal agent the user happens to have, which may be
written for a different stack entirely — and it will look like it worked.

Hand it the full report: symptom, repro steps, error text, affected surface, and
when it last worked.

**If it cannot pin the root cause**, relay what it ruled out and ask the user for
more repro detail. Do not proceed to planning on a hypothesis — that is the one
failure this skill exists to prevent.

## Step 2 — Decide what is the user's call

Read the report. Before planning, decide whether anything is genuinely theirs:

- More than one viable fix, with different trade-offs
- The intended behaviour is ambiguous — the code is wrong only if you know what
  right was
- The fix is broader than the symptom (a targeted patch versus a refactor)
- It touches regulated or personal data, a data migration, an external contract,
  a public API, or anything with a blast radius past this repo

If any apply, ask — with `AskUserQuestion` where the harness has it, as a plain
numbered question where it does not — and **lead with your recommendation.**
If the report is unambiguous and the fix is obvious, go straight to planning.
Do not manufacture questions.

## Step 3 — Plan

**REQUIRED SUB-SKILL:** use `superpowers:writing-plans`.

Hand it a spec built from the **proven root cause plus the agreed fix
direction**. It produces a file-path-exact, test-first plan.

The plan must include a **regression test that fails before the fix and passes
after**. Re-running the original reproduction by hand proves the symptom is gone
today; a committed failing-first test is what stops it coming back. If the bug
genuinely cannot be covered by a test, say so in the plan and why.

**Commit rules come from the repository, not from here.** Read its `CLAUDE.md`,
`AGENTS.md`, or contributing guide and follow its subject-line conventions,
ticket prefixes and sign-off rules. Two things hold regardless of what the repo
says, because they are the user's, not the project's:

- **Never add a `Co-Authored-By` or any attribution trailer.**
- **Never put a session link, session id, or assistant-generated URL anywhere**
  in a commit message, code, or documentation.

## Step 4 — Implement

Scale the mechanism to the fix:

| Size | How |
| ---- | --- |
| **≤ 3 files, and the plan names exact lines** | Implement directly, test first. |
| **Anything larger** | `superpowers:subagent-driven-development` — one subagent per task, reviewed per task. |

Then verify, in this order:

1. The regression test fails without the fix. If it passes without it, it is not
   testing the bug.
2. It passes with the fix.
3. The original reproduction no longer reproduces.
4. The repo's own gates — its full suite, linters and build — are green.

**The fix is not done until step 3 passes.** A green suite that never covered the
bug is the same false signal as a green gate over unchecked code.

## Red flags — STOP

- About to edit code before an investigator has reported → stop, dispatch one.
- About to plan on a "probably this" cause with no `file:line` evidence → stop,
  finish the investigation.
- Writing `bug-investigator` without the `superb:` prefix → you are about to
  dispatch someone else's agent and trust the result.
- Multiple viable fixes, or a blast radius past this repo, and you have not asked
  → stop, ask.
- About to call it done having only re-run the repro by hand → the regression
  test is the deliverable that outlives you.
- About to write a ticket prefix you did not read out of the repo's own rules →
  you are carrying another project's conventions into this one.
