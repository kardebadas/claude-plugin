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
Skill directory: <absolute path to this skill, resolved by the orchestrator —
       the `<skill-dir>` used below. A run's cwd is the user's project, which
       holds no copy of this plugin, so a relative path resolves nowhere.>

## Your task

Read `<run-dir>/../plans/<sub-plan>.md` Task `<n>` first — it is your
requirements, and its exact values (names, signatures, magic strings, test
cases) are to be used verbatim. Get it with:

```
<skill-dir>/scripts/task-brief <sub-plan-path> <n>
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
