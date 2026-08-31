#!/usr/bin/env bash
# Structural checks for the superb plugin.
#
# `claude plugin validate --strict` is not a safety net for any of this: it
# passes on a plugin containing a deliberately malformed agent file. These are
# the invariants nothing else enforces.
set -uo pipefail
cd "$(dirname "$0")/.."
FAIL=0
ok(){ printf '  ok    %s\n' "$1"; }
bad(){ printf '  FAIL  %s\n' "$1"; FAIL=1; }

echo "== shared brief =="
# agents/bug-investigator.md and skills/bug-fix/references/investigator.md ship
# the same body. One is the Claude Code agent; the other is the brief handed to
# a generic subagent where no bundled agent loads. They must not drift.
extract(){ sed -n '/<!-- SHARED BRIEF: begin -->/,/<!-- SHARED BRIEF: end -->/p' "$1"; }
A=plugins/superb/agents/bug-investigator.md
B=plugins/superb/skills/bug-fix/references/investigator.md
if [ ! -f "$A" ] || [ ! -f "$B" ]; then
  bad "shared-brief files missing ($A / $B)"
elif [ -z "$(extract "$A")" ]; then
  bad "no SHARED BRIEF markers in $A"
elif diff <(extract "$A") <(extract "$B") >/dev/null; then
  ok "brief identical in agent and skill reference"
else
  bad "brief has drifted between $A and $B"
  diff <(extract "$A") <(extract "$B") | head -20
fi

echo "== manifest versions =="
CV=$(python3 -c "import json;print(json.load(open('plugins/superb/.claude-plugin/plugin.json'))['version'])" 2>/dev/null)
XV=$(python3 -c "import json;print(json.load(open('plugins/superb/.codex-plugin/plugin.json'))['version'])" 2>/dev/null)
[ -n "$CV" ] && [ "$CV" = "$XV" ] && ok "both manifests at $CV" || bad "version drift: claude=$CV codex=$XV"
CN=$(python3 -c "import json;print(json.load(open('plugins/superb/.claude-plugin/plugin.json'))['name'])" 2>/dev/null)
XN=$(python3 -c "import json;print(json.load(open('plugins/superb/.codex-plugin/plugin.json'))['name'])" 2>/dev/null)
[ "$CN" = "$XN" ] && ok "both manifests name '$CN' (the namespace prefix)" || bad "name drift: claude=$CN codex=$XN"

echo "== json parses =="
for f in .claude-plugin/marketplace.json .agents/plugins/marketplace.json \
         plugins/superb/.claude-plugin/plugin.json plugins/superb/.codex-plugin/plugin.json; do
  python3 -c "import json,sys;json.load(open('$f'))" 2>/dev/null && ok "$f" || bad "$f does not parse"
done

echo "== skills =="
for d in plugins/superb/skills/*/; do
  n=$(basename "$d")
  [ -f "$d/SKILL.md" ] || { bad "$n has no SKILL.md"; continue; }
  [ -f "$d/README.md" ] || bad "$n has no README.md"
  fn=$(sed -n 's/^name: *//p' "$d/SKILL.md" | head -1)
  [ "$fn" = "$n" ] && ok "$n: frontmatter name matches directory" \
    || bad "$n: frontmatter name '$fn' != directory '$n' (namespace would be superb:$fn)"
  grep -q "superb:$n" README.md || bad "$n missing from the root README"
done

echo "== agents =="
for f in plugins/superb/agents/*.md; do
  [ -e "$f" ] || { ok "no bundled agents"; break; }
  n=$(basename "$f" .md)
  head -1 "$f" | grep -q '^---$' && ok "$n has frontmatter" || bad "$n has no YAML frontmatter"
  sed -n 's/^name: *//p' "$f" | head -1 | grep -qx "$n" && ok "$n: name matches filename" || bad "$n: frontmatter name != filename"
done

echo "== no personal leakage =="
if grep -rniE "/home/[a-z0-9_-]+/|audio-chat-app|agent-memory|MIPS-[0-9X]|HIPAA" \
     plugins/superb --include=*.md --include=*.json -l 2>/dev/null | grep -q .; then
  bad "personal paths or another project's conventions found:"
  grep -rniE "/home/[a-z0-9_-]+/|audio-chat-app|agent-memory|MIPS-[0-9X]|HIPAA" \
    plugins/superb --include=*.md --include=*.json | head -10
else
  ok "no absolute home paths, private project names, or foreign ticket prefixes"
fi

echo
[ "$FAIL" = 0 ] && echo "check-plugin: PASS" || echo "check-plugin: FAIL"
exit $FAIL
