#!/usr/bin/env bash
# Proves tools/check-plugin.sh can actually fail.
#
# A gate that passes everything is indistinguishable from a gate that checks
# nothing. Each mutant below is a deliberate breakage the gate must reject.
#
# Every mutation is applied to a THROWAWAY COPY of the repository. This script
# never writes to, and never runs git against, your working tree — an earlier
# version of this harness restored the tree mid-run and silently destroyed
# uncommitted work twice.
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PASS=0; SURV=0; SURVIVORS=()

run_mutant() { # name, shell applied inside the copy
  local name="$1" script="$2" dir="$WORK/m"
  rm -rf "$dir"; mkdir -p "$dir"
  tar -C "$SRC" --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$dir" -xf -
  ( cd "$dir" && eval "$script" ) >/dev/null 2>&1
  if ( cd "$dir" && ./tools/check-plugin.sh ) >/dev/null 2>&1; then
    printf '  SURVIVED  %s\n' "$name"; SURV=$((SURV+1)); SURVIVORS+=("$name")
  else
    printf '  killed    %s\n' "$name"; PASS=$((PASS+1))
  fi
}

echo "baseline (unmutated copy must PASS):"
D="$WORK/base"; mkdir -p "$D"
tar -C "$SRC" --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$D" -xf -
if ( cd "$D" && ./tools/check-plugin.sh ) >/dev/null 2>&1; then
  echo "  ok    clean copy passes"
else
  echo "  FAIL  clean copy does not pass — fix the repo before trusting any result below"
  ( cd "$D" && ./tools/check-plugin.sh ) | grep FAIL
  exit 1
fi

echo "mutants:"
J="python3 -c"
run_mutant "agent frontmatter: malformed key"      "sed -i '3s/^description: /description = /' plugins/superb/agents/bug-investigator.md"
run_mutant "agent frontmatter: tab indentation"    "sed -i '3s/^/\t/' plugins/superb/agents/bug-investigator.md"
run_mutant "agent frontmatter: undefined alias"    "sed -i 's/^color: magenta/color: *nope/' plugins/superb/agents/bug-investigator.md"
run_mutant "agent frontmatter: duplicate key"      "sed -i '3a name: other' plugins/superb/agents/bug-investigator.md"
run_mutant "agent frontmatter: unclosed"           "$J \"import pathlib;f=pathlib.Path('plugins/superb/agents/bug-investigator.md');L=f.read_text().split(chr(10));i=[n for n,x in enumerate(L) if x.strip()=='---'][1];L[i]='';f.write_text(chr(10).join(L))\""
run_mutant "agent description removed"             "sed -i '/^description:/d' plugins/superb/agents/bug-investigator.md"
run_mutant "skill SKILL.md line 1 deleted"         "sed -i '1d' plugins/superb/skills/bug-fix/SKILL.md"
run_mutant "skill description removed"             "sed -i '3d' plugins/superb/skills/bug-fix/SKILL.md"
run_mutant "skill frontmatter name != directory"   "sed -i 's/^name: bug-fix\$/name: bugfix/' plugins/superb/skills/bug-fix/SKILL.md"
run_mutant "skill script loses +x"                 "chmod -x plugins/superb/skills/setup/check-deps.sh"
run_mutant "craft check-brief loses +x"           "chmod -x plugins/superb/skills/craft/check-brief.sh"
run_mutant "skill README gutted"                   "printf '# x\n' > plugins/superb/skills/bug-fix/README.md"
run_mutant "skill README padded with filler"       "$J \"open('plugins/superb/skills/bug-fix/README.md','w').write('x '*200)\""
run_mutant "skill dropped from plugin README"      "sed -i '/superb:bug-fix/d' plugins/superb/README.md"
run_mutant "skill dropped from root README"        "sed -i 's/superb:bug-fix/superb:removed/g' README.md"
# Wording-independent: strip a skill's NAME from the description rather than a
# phrase. A sed on prose silently becomes a no-op the next time the prose is
# edited, and a mutant that changes nothing proves nothing.
run_mutant "skill dropped from marketplace desc"   "$J \"import json,pathlib
p=pathlib.Path('.claude-plugin/marketplace.json'); s=p.read_text()
assert 'bug-fix' in s, 'mutant is a no-op: bug-fix absent from the marketplace description'
p.write_text(s.replace('bug-fix','')) \""
run_mutant "keywords stripped"                     "$J \"import json;p='plugins/superb/.claude-plugin/plugin.json';d=json.load(open(p));d['keywords']=['x'];json.dump(d,open(p,'w'),indent=2)\""
run_mutant "claude description blanked"            "$J \"import json;p='plugins/superb/.claude-plugin/plugin.json';d=json.load(open(p));d['description']='';json.dump(d,open(p,'w'),indent=2)\""
run_mutant "codex longDescription blanked"         "$J \"import json;p='plugins/superb/.codex-plugin/plugin.json';d=json.load(open(p));d['interface']['longDescription']='';json.dump(d,open(p,'w'),indent=2)\""
run_mutant "codex skills key removed"              "$J \"import json;p='plugins/superb/.codex-plugin/plugin.json';d=json.load(open(p));d.pop('skills');json.dump(d,open(p,'w'),indent=2)\""
run_mutant "codex skills path bogus"               "$J \"import json;p='plugins/superb/.codex-plugin/plugin.json';d=json.load(open(p));d['skills']='./nope/';json.dump(d,open(p,'w'),indent=2)\""
run_mutant "version drift between manifests"       "$J \"import json;p='plugins/superb/.codex-plugin/plugin.json';d=json.load(open(p));d['version']='9.9.9';json.dump(d,open(p,'w'),indent=2)\""
run_mutant "namespace renamed in both manifests"   "$J \"import json
for p in ['plugins/superb/.claude-plugin/plugin.json','plugins/superb/.codex-plugin/plugin.json']:
    d=json.load(open(p)); d['name']='superbb'; json.dump(d,open(p,'w'),indent=2)\""
run_mutant "codex marketplace name drifts"         "sed -i 's/\"name\": \"superb\"/\"name\": \"superbz\"/' .agents/plugins/marketplace.json"
run_mutant "codex marketplace source path bogus"   "sed -i 's|\"path\": \"./plugins/superb\"|\"path\": \"./plugins/nope\"|' .agents/plugins/marketplace.json"
run_mutant "undocumented plugin directory added"   "mkdir -p plugins/evil && echo '{}' > plugins/evil/x.json"
run_mutant "brief drifts between the two copies"   "sed -i 's/You are a bug investigation specialist\./& DRIFT./' plugins/superb/skills/bug-fix/references/investigator.md"
run_mutant "SHARED BRIEF markers deleted in both"  "sed -i '/SHARED BRIEF/d' plugins/superb/agents/bug-investigator.md plugins/superb/skills/bug-fix/references/investigator.md"
run_mutant "personal path reintroduced"            "echo 'see /home/someone/.claude/agent-memory/' >> plugins/superb/agents/bug-investigator.md"
run_mutant "personal path hidden in a .py file"    "echo '# /home/someone/audio-chat-app' >> plugins/superb/skills/craft/ui/server.py"
run_mutant "foreign build command reintroduced"    "echo 'run tools/build.sh after the merge' >> plugins/superb/skills/pipeline/references/parallel.md"
run_mutant "foreign source tree reintroduced"      "echo 'when extension/src/physics/ changed' >> plugins/superb/skills/pipeline/references/parallel.md"
run_mutant "manifest JSON corrupted"               "echo '{' >> .claude-plugin/marketplace.json"
run_mutant "non-UTF8 byte in a checked file"       "printf '\\xff\\xfe' >> plugins/superb/skills/bug-fix/SKILL.md"
run_mutant "skills directory deleted"              "rm -rf plugins/superb/skills"
run_mutant "CI workflow deleted"                   "rm -f .github/workflows/checks.yml"
run_mutant "CI stops running the gate"             "sed -i 's|./tools/check-plugin.sh|./tools/nothing.sh|' .github/workflows/checks.yml"

# --- the pipeline review-line linter must itself stay honest ---
run_mutant "RV example loses a report file"        "sed -i 's|p3-review-{a,b,int}.md|p3-review-{a,b}.md|' plugins/superb/skills/pipeline/references/run-state.md"
run_mutant "RVJ example declares slice reviewers"  "sed -i 's|N=17 → 0 slice + 1 integration · reports j-56-int.md|N=17 → 4 slice + 1 integration · reports j-56-{a,b,c,d,int}.md|' plugins/superb/skills/pipeline/references/run-state.md"
run_mutant "RV example loses its coverage file"    "sed -i 's| · coverage p3-coverage.md||' plugins/superb/skills/pipeline/references/run-state.md"
run_mutant "re-review round loses report files"    "sed -i 's|p3-rr2-{a,b,c,int}.md|p3-rr2-{a,int}.md|' plugins/superb/skills/pipeline/SKILL.md"
run_mutant "every worked RV example deleted"       "sed -i '/· reports/d' plugins/superb/skills/pipeline/*.md plugins/superb/skills/pipeline/*/*.md"

# --- the skill-invocation arm must itself stay honest ---
run_mutant "skill dispatches on \$0 again"         "sed -i 's|Dispatch on the argument below|Dispatch on the argument (\`\$0\`)|' plugins/superb/skills/pipeline/SKILL.md"
# A doubled backslash escapes NOTHING — both backslashes stay and $0 still expands.
# So the arm's exemption must be odd-count, not one-character; nothing else here
# reaches that input, and without this mutant the odd/even fix is untested.
run_mutant "skill dispatches on a doubled-backslash \$0" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md'); s=p.read_text()
a='Dispatch on the argument below'
assert a in s, 'mutant is a no-op: the dispatch sentence has been reworded'
tick=chr(96); ph=chr(92)*2+chr(36)+'0'
p.write_text(s.replace(a, 'Dispatch on the argument ('+tick+ph+tick+')'))\""
run_mutant "invocation loses its namespace"        "sed -i 's|/superb:pipeline|/pipeline|g' plugins/superb/skills/pipeline/SKILL.md"
# The namespace arm reads every *.md in a skill directory, not just SKILL.md —
# the two files that regressed last time were README.md and references/. Append
# rather than sed on prose: an appended line cannot become a silent no-op.
run_mutant "namespace lost outside SKILL.md"       "echo 'start a run with /pipeline' >> plugins/superb/skills/pipeline/README.md"
run_mutant "namespace lost in a references page"   "echo 'resume with /pipeline resume' >> plugins/superb/skills/pipeline/references/run-state.md"
# The fourth-tier arm fires on `Important` NAMED WITHOUT the re-tag rule, so a
# mutant has to keep the word and break the rule. Renaming "Three tiers only" to
# "Important findings also block" — the obvious mutation — SURVIVES: it leaves
# the re-tag sentence standing, so the arm is satisfied and proves nothing.
# Asserted rather than sed'd on prose, because a mutation that matches nothing
# reports `killed` for the wrong reason; two mutants here have already had to be
# retargeted for exactly that.
run_mutant "fourth severity tier named without its re-tag rule" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md'); s=p.read_text()
tick=chr(96); a='an incoming '+tick+'Important'+tick+' is re-tagged'
assert a in s, 'mutant is a no-op: the re-tag sentence has been reworded'
p.write_text(s.replace(a, 'an incoming '+tick+'Important'+tick+' is honoured as a fourth tier'))\""

echo
echo "killed=$PASS survived=$SURV"
if [ "$SURV" -ne 0 ]; then
  printf 'survivors:\n'; printf '  - %s\n' "${SURVIVORS[@]}"
  echo "check-plugin-mutants: FAIL"; exit 1
fi
echo "check-plugin-mutants: PASS"
