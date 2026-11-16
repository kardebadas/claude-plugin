---
description: Choose which agents do this session's work (Codex, Claude or DeepSeek) while the main session orchestrates. `on` asks at every session start until `off`.
argument-hint: "[on|off]"
---

# Agent mode

Arguments: `$ARGUMENTS`

The switch is the file `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.superb-agent-mode`.
While it exists, superb's SessionStart hook has you ask the question below at
every session start and after `/clear`. It stays on until the user turns it off.

Act on the arguments:

- `on`: run `touch "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.superb-agent-mode"`,
  tell the user "Agent mode is on: I'll ask at every session start until
  `/superb:agent-mode off`.", then ask the question.
- `off`: run `rm -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.superb-agent-mode"`,
  tell the user "Agent mode is off.", drop any mode chosen earlier in this
  session and work normally. Do not ask the question.
- nothing: ask the question.
- anything else: say the arguments are `on`, `off` or nothing, and stop.

The user saying "agent mode off" or "stop agent mode" counts as `off`.

## The question

Ask with one AskUserQuestion call holding these three questions, options in
this order:

1. Header `Code`, "Who writes the code this session?", single choice:
   - `Codex (Recommended)`: Codex CLI implements, one git worktree per task
   - `Claude`: Claude subagents (Opus) implement
   - `DeepSeek`: DeepSeek CLI implements
   - `No orchestrator`: Claude works directly; the other answers are ignored
2. Header `UI`, "Who does UI, graphics and Blender?", single choice:
   - `Claude (Recommended)`: Claude subagents (Opus); Blender MCP runs only on Claude
   - `Codex`: Codex CLI
   - `DeepSeek`: DeepSeek CLI
3. Header `Reviews`, "Who reviews each task before merge? (pick any)",
   multiSelect:
   - `DeepSeek (Recommended)`: read-only review at the branch tip
   - `Claude`: Claude review subagent
   - `Codex`: Codex read-only review

If no reviewer is picked, use DeepSeek. A free-text "Other" answer is used as
written.

Then confirm in one line, for example
`Mode: Codex code · Claude UI · DeepSeek reviews`, and keep that mode until the
session ends, `/clear`, or the user runs `/superb:agent-mode` again.

## Orchestrating

Unless the user picked `No orchestrator`, for the rest of the session you are
the orchestrator:

- Write the specs and plans yourself.
- Send every implementation, test and investigation to the agent picked for
  it. Each agent that edits files gets its own git worktree. Run independent
  tasks in parallel.
- Read every report critically: check its claims against the diff and the
  test output, and answer with precise follow-ups.
- Have the picked reviewers review each task before it merges; then merge, run
  the checks and report.
- Never write or edit project code yourself. Reading files, `git status` and
  running a check are fine, and so is anything the user explicitly tells you
  to do yourself.
- Run Codex and DeepSeek the way the project's instructions or your memory
  say. If neither says, and the CLI is not on `PATH`, tell the user instead of
  guessing.
