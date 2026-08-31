#!/usr/bin/env bash
# Reports what superb's skills need and whether it is present.
#
# Machine-readable, one fact per line, so the skill reads it rather than parsing
# prose. Exits 0 when every REQUIRED dependency is satisfied, 1 otherwise.
#
#   HARNESS   <claude|codex|unknown>
#   REQUIRED  <name>  <OK|MISSING|DISABLED>  <detail>
#   OPTIONAL  <name>  <OK|MISSING>           <detail>
#   MARKET    <name>  <OK|MISSING>
#   ACTION    <a command that would fix the line above it>
set -uo pipefail
MISSING=0

# --- which harness are we on -------------------------------------------------
if command -v claude >/dev/null 2>&1; then HARNESS=claude
elif command -v codex >/dev/null 2>&1; then HARNESS=codex
else HARNESS=unknown; fi
echo "HARNESS $HARNESS"

# --- superpowers: required by superb:pipeline and superb:bug-fix -------------
if [ "$HARNESS" = claude ]; then
  LIST=$(claude plugin list 2>/dev/null)
  if ! printf '%s' "$LIST" | grep -q "^Configured\|superpowers@"; then :; fi
  if printf '%s' "$LIST" | grep -q "superpowers@"; then
    VER=$(printf '%s' "$LIST" | grep -A2 "superpowers@" | sed -n 's/ *Version: *//p' | head -1)
    if printf '%s' "$LIST" | grep -A3 "superpowers@" | grep -q "disabled"; then
      echo "REQUIRED superpowers DISABLED ${VER:-unknown}"
      echo "ACTION claude plugin enable superpowers"
      MISSING=1
    else
      echo "REQUIRED superpowers OK ${VER:-unknown}"
    fi
  else
    echo "REQUIRED superpowers MISSING not-installed"
    if claude plugin marketplace list 2>/dev/null | grep -q "claude-plugins-official"; then
      echo "MARKET claude-plugins-official OK"
    else
      echo "MARKET claude-plugins-official MISSING"
      echo "ACTION claude plugin marketplace add anthropics/claude-plugins-official"
    fi
    echo "ACTION claude plugin install superpowers@claude-plugins-official"
    MISSING=1
  fi
else
  # Codex installs interactively; nothing here can run it.
  echo "REQUIRED superpowers UNKNOWN cannot-check-on-$HARNESS"
  echo "ACTION manual: open /plugins, search superpowers, install"
fi

# --- python3: craft's browser UI. Optional — it falls back to file mode. -----
if command -v python3 >/dev/null 2>&1; then
  echo "OPTIONAL python3 OK $(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null)"
else
  echo "OPTIONAL python3 MISSING craft-ui-falls-back-to-file-mode"
fi

# --- git worktrees: pipeline's parallel waves need them ----------------------
if git rev-parse --git-dir >/dev/null 2>&1; then
  echo "OPTIONAL git-repo OK $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
else
  echo "OPTIONAL git-repo MISSING pipeline-waves-need-a-repo"
fi

exit $MISSING
