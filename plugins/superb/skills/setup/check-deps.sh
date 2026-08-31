#!/usr/bin/env bash
# Reports what superb's skills need and whether it is present.
#
# One fact per line, so the skill reads a report rather than parsing prose.
#
#   HARNESS   <claude|codex|unknown>
#   REQUIRED  <name>  <OK|MISSING|DISABLED|ERROR|UNKNOWN>  <detail>
#   OPTIONAL  <name>  <OK|MISSING>                         <detail>
#   MARKET    <name>  <OK|MISSING>
#   ACTION    <a command that would fix the line above it>
#   NOTE      <something the reader needs that is not actionable>
#
# Exit codes are distinct on purpose:
#   0  every required dependency satisfied
#   1  a required dependency is MISSING or DISABLED — the ACTION lines apply
#   2  could not determine — DO NOT act on this; acting on an unknown state is
#      how a present dependency gets reinstalled over the top of itself
set -uo pipefail
STATUS=0
note_worse() { [ "$1" -gt "$STATUS" ] && STATUS=$1; return 0; }

if command -v claude >/dev/null 2>&1; then HARNESS=claude
elif command -v codex >/dev/null 2>&1; then HARNESS=codex
else HARNESS=unknown; fi
echo "HARNESS $HARNESS"

# --- superpowers: required by superb:pipeline and superb:bug-fix -------------
if [ "$HARNESS" = claude ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "REQUIRED superpowers ERROR cannot-parse-plugin-list-without-python3"
    echo "NOTE run 'claude plugin list' yourself and check for superpowers"
    note_worse 2
  else
    JSON=$(timeout 30 claude plugin list --json 2>/dev/null); RC=$?
    if [ "$RC" -ne 0 ] || [ -z "$JSON" ]; then
      # A failed or empty query is NOT evidence of absence. Saying MISSING here
      # would tell the skill to install something that may already be present.
      echo "REQUIRED superpowers ERROR plugin-list-failed-rc$RC"
      echo "NOTE the query failed; this says nothing about whether it is installed"
      note_worse 2
    else
      REPORT=$(printf '%s' "$JSON" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception as e:
    print(f"ERROR unparseable-json:{type(e).__name__}"); sys.exit(0)
items = d if isinstance(d, list) else (d.get("plugins") or [])
# Match the plugin name exactly — the part before @ — so a differently named
# plugin that merely contains the string cannot be mistaken for this one.
hits = [p for p in items if str(p.get("id","")).split("@")[0] == "superpowers"]
if not hits:
    print("MISSING not-installed")
elif len(hits) > 1:
    ids = ",".join(sorted(str(p.get("id")) for p in hits))
    en  = [p for p in hits if p.get("enabled")]
    if len(en) == 1:
        print("OK {} (also-installed:{})".format(en[0].get("version") or "unknown", ids))
    else:
        print(f"UNKNOWN multiple-installs:{ids}")
else:
    p = hits[0]
    v = p.get("version") or "unknown"
    print((f"OK {v}") if p.get("enabled") else (f"DISABLED {v}"))
')
      set -- $REPORT; STATE=${1:-ERROR}
      echo "REQUIRED superpowers $REPORT"
      case "$STATE" in
        OK)       : ;;
        DISABLED) echo "ACTION claude plugin enable superpowers"; note_worse 1 ;;
        MISSING)
          if timeout 30 claude plugin marketplace list 2>/dev/null | grep -q "claude-plugins-official"; then
            echo "MARKET claude-plugins-official OK"
          else
            echo "MARKET claude-plugins-official MISSING"
            echo "ACTION claude plugin marketplace add anthropics/claude-plugins-official"
          fi
          echo "ACTION claude plugin install superpowers@claude-plugins-official"
          note_worse 1 ;;
        UNKNOWN)  echo "NOTE more than one superpowers is installed; resolve by hand before acting"; note_worse 2 ;;
        *)        note_worse 2 ;;
      esac
    fi
  fi
else
  # Codex installs through an interactive picker; nothing here can run it, and
  # nothing here can inspect it either. UNKNOWN, not MISSING.
  echo "REQUIRED superpowers UNKNOWN cannot-check-on-$HARNESS"
  echo "NOTE manual route: open /plugins, search superpowers, select Install Plugin"
  note_worse 2
fi

# --- python3: craft's browser UI. Genuinely optional. -----------------------
if command -v python3 >/dev/null 2>&1; then
  echo "OPTIONAL python3 OK $(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null || echo unknown)"
else
  echo "OPTIONAL python3 MISSING craft-ui-falls-back-to-file-mode"
fi

# Deliberately NOT checked: whether the user's project is a git repository.
# This script runs from the plugin's install directory, so $PWD is never the
# project, and a check that always describes the wrong directory is worse than
# no check. superb:pipeline establishes that itself, where it can see the repo.
echo "NOTE git-repo not checked here — this runs from the plugin directory, not your project"

exit $STATUS
