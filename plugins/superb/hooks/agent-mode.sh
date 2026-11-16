#!/bin/sh
# superb agent mode, Claude Code only. superb's SessionStart hook runs this as
# `agent-mode.sh start` or `agent-mode.sh compact`; its stdout reaches Claude.
#
# Two switch files; the project one, when it exists, wins:
#   project: .claude/superb-agent-mode in the repo's main checkout, so every git
#            worktree of the repo shares it (the current directory outside git)
#   global:  ${CLAUDE_CONFIG_DIR:-~/.claude}/.superb-agent-mode
# Content: empty = ask every session, `off` = off, anything else = saved picks.
dir=${CLAUDE_PROJECT_DIR:-$PWD}
common=$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) && dir=${common%/.git}
project="$dir/.claude/superb-agent-mode"
global="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.superb-agent-mode"

if [ -f "$project" ]; then f=$project scope=project
elif [ -f "$global" ]; then f=$global scope=global
else exit 0
fi
picks=
read -r picks < "$f"
[ "$picks" = off ] && exit 0
# The text reaches Claude as an instruction, and a cloned repo can ship this
# file: accept only the picks shape, letters only, and ask on anything else.
printf '%s\n' "$picks" | grep -Eqx '[A-Za-z]+ code · [A-Za-z]+ UI · [A-Za-z]+( \+ [A-Za-z]+)* reviews' || picks=

run=/superb:agent-mode
[ -n "$picks" ] && run="/superb:agent-mode use $picks"
if [ "$1" = compact ]; then
  echo "superb agent mode is ON ($scope setting). Keep the agent mode chosen earlier in this session. If the summary no longer says which mode was chosen, run $run and follow it."
else
  echo "superb agent mode is ON ($scope setting). Before any other work in this session, run $run and follow it."
fi
