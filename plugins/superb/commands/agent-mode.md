---
description: Choose which agents do this session's work (Codex, Claude or DeepSeek) while the main session orchestrates. `on` asks at every session start until `off`, globally or for one project, and the picks can be saved so it stops asking.
argument-hint: "[on|off] [project] | use <picks>"
---

# Agent mode

Arguments: `$ARGUMENTS`

superb's SessionStart hook reads two switch files at every session start, after
`/clear` and after compaction:

- **Global:** `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.superb-agent-mode`, for
  every project.
- **Project:** `.claude/superb-agent-mode` in the repo's main checkout, so
  every git worktree of the repo shares it. The main checkout is the directory
  that holds the path `git rev-parse --path-format=absolute --git-common-dir`
  prints (strip the trailing `/.git`); outside a git repo, use the current
  directory.

When the project file exists it wins, whatever the global file says. A file's
first line decides what happens:

- empty: ask the question below at every session start;
- `off`: agent mode is off (only meaningful in the project file; turning the
  global one off deletes it);
- anything else: saved picks such as `Codex code · Claude UI · DeepSeek
  reviews`; the hook then has you run `use` with them and nothing is asked.

Whenever you write the project file inside a git repo, keep it out of git:
append the line `.claude/superb-agent-mode` to `info/exclude` in the git common
directory, unless that file already has it. Create `.claude/` and `info/` if
missing.

Act on the arguments:

- `on`: create the global file if missing, keeping any saved picks in it. Tell
  the user "Agent mode is on for every project until `/superb:agent-mode off`."
  If the project file says `off`, add that it stays off in this repo until
  `/superb:agent-mode on project`. Otherwise continue as for the file that wins:
  `use` its saved picks, or ask the question.
- `on project`: create the project file empty, unless it already holds saved
  picks (a file that says `off` is emptied). Tell the user "Agent mode is on
  for this project until `/superb:agent-mode off project`.", then `use` its
  saved picks or ask the question.
- `off`: delete the global file. Tell the user "Agent mode is off." If the
  project file exists and is not `off`, add that it stays on in this repo until
  `/superb:agent-mode off project`, and keep the current mode. Otherwise drop
  any mode chosen earlier in this session and work normally.
- `off project`: write `off` to the project file. Tell the user "Agent mode is
  off for this project. Delete `<project file>` to follow the global setting
  again." Drop any mode chosen earlier in this session and work normally.
- `use <picks>`: do not ask. Take the picks as this session's mode, confirm in
  one line (`Mode: <picks>`) and orchestrate.
- nothing: ask the question.
- anything else: say the arguments are `on`, `off`, `on project`,
  `off project`, `use <picks>` or nothing, and stop.

The user saying "agent mode off" or "stop agent mode" counts as `off`, and
"for this project" adds `project`.

## The question

Ask with one AskUserQuestion call holding these four questions, options in
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
4. Header `Save`, "Remember these picks?", single choice:
   - `This project (Recommended)`: sessions in this repo stop asking
   - `All projects`: every project without its own setting stops asking
   - `Just this session`: ask again next session

If no reviewer is picked, use DeepSeek. A free-text "Other" answer is used as
written.

The picks are one line: `<Code> code · <UI> UI · <reviewers joined by " + ">
reviews`, for example `Codex code · Claude UI · DeepSeek + Claude reviews`.
Save them as the Save answer says: write the line to the project file or to the
global file, or write nothing. If the user picked `No orchestrator`, saving
means `off` for the project, or deleting the global file for all projects.

Then confirm in one line, for example
`Mode: Codex code · Claude UI · DeepSeek reviews (saved for this project)`, and
keep that mode until the session ends, `/clear`, or the user runs
`/superb:agent-mode` again.

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
