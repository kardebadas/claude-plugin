#!/usr/bin/env bash
# Prove tools/check-plugin.sh rejects shared plugin breakage and the narrow
# Pipeline v2 release-contract mutations.
#
# Every mutation runs in a throwaway copy. The source working tree is never
# edited or restored by this harness.
set -uo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PASS=0
SURV=0
NOOP=0
SURVIVORS=()
NOOPS=()

tree_fingerprint() {
  python3 - "$1" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
    relative = path.relative_to(root).as_posix()
    if ".git" in path.parts or "__pycache__" in path.parts:
        continue
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        payload = b"L" + os.readlink(path).encode()
    elif stat.S_ISREG(mode):
        payload = b"F" + bytes(str(stat.S_IMODE(mode)), "ascii") + path.read_bytes()
    elif stat.S_ISDIR(mode):
        payload = b"D"
    else:
        payload = b"O" + bytes(str(mode), "ascii")
    digest.update(relative.encode() + b"\0" + payload + b"\0")
print(digest.hexdigest())
PY
}

run_mutant() { # name, shell applied inside the throwaway copy
  local name="$1" script="$2" dir="$WORK/m" out before after gate_rc
  rm -rf "$dir"
  mkdir -p "$dir"
  tar -C "$SRC" --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$dir" -xf -
  before="$(tree_fingerprint "$dir")"
  out="$( (cd "$dir" && eval "$script") 2>&1 )"
  after="$(tree_fingerprint "$dir")"
  if [ "$before" = "$after" ] && ! printf '%s' "$out" | grep -q "mutant is a no-op"; then
    out="${out}${out:+$'\n'}mutant is a no-op: repository snapshot did not change"
  fi

  (cd "$dir" && ./tools/check-plugin.sh) >/dev/null 2>&1
  gate_rc=$?
  if printf '%s' "$out" | grep -q "mutant is a no-op"; then
    printf '  NO-OP     %s\n' "$name"
    NOOP=$((NOOP + 1))
    NOOPS+=("$name")
    printf '%s\n' "$out" | sed 's/^/            | /'
  elif [ "$gate_rc" -eq 0 ]; then
    printf '  SURVIVED  %s\n' "$name"
    SURV=$((SURV + 1))
    SURVIVORS+=("$name")
    if [ -n "$out" ]; then printf '%s\n' "$out" | sed 's/^/            | /'; fi
  else
    printf '  killed    %s\n' "$name"
    PASS=$((PASS + 1))
  fi
}

echo "baseline (unmutated copy must PASS):"
BASE="$WORK/base"
mkdir -p "$BASE"
tar -C "$SRC" --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$BASE" -xf -
if (cd "$BASE" && ./tools/check-plugin.sh) >/dev/null 2>&1; then
  echo "  ok    clean copy passes"
else
  echo "  FAIL  clean copy does not pass — fix the repo before trusting mutations"
  (cd "$BASE" && ./tools/check-plugin.sh) | grep FAIL
  exit 1
fi

echo "mutants:"
J="python3 -c"

# Shared plugin structure and metadata coverage retained from the existing
# harness. The snapshot check in run_mutant makes every stale edit a NO-OP.
run_mutant "agent frontmatter: malformed key"      "sed -i '3s/^description: /description = /' plugins/superb/agents/bug-investigator.md"
run_mutant "agent frontmatter: tab indentation"    "sed -i '3s/^/\t/' plugins/superb/agents/bug-investigator.md"
run_mutant "agent frontmatter: undefined alias"    "sed -i 's/^color: magenta/color: *nope/' plugins/superb/agents/bug-investigator.md"
run_mutant "agent frontmatter: duplicate key"      "sed -i '3a name: other' plugins/superb/agents/bug-investigator.md"
run_mutant "agent frontmatter: unclosed"           "$J \"import pathlib; p=pathlib.Path('plugins/superb/agents/bug-investigator.md'); lines=p.read_text().split(chr(10)); indexes=[i for i,line in enumerate(lines) if line.strip()=='---']; assert len(indexes)>=2, 'mutant is a no-op: closing frontmatter marker absent'; lines[indexes[1]]=''; p.write_text(chr(10).join(lines))\""
run_mutant "agent description removed"             "sed -i '/^description:/d' plugins/superb/agents/bug-investigator.md"
run_mutant "skill SKILL.md line 1 deleted"         "sed -i '1d' plugins/superb/skills/bug-fix/SKILL.md"
run_mutant "skill description removed"             "sed -i '/^description:/d' plugins/superb/skills/bug-fix/SKILL.md"
run_mutant "skill frontmatter name != directory"   "sed -i 's/^name: bug-fix$/name: bugfix/' plugins/superb/skills/bug-fix/SKILL.md"
run_mutant "skill script loses +x"                 "chmod -x plugins/superb/skills/setup/check-deps.sh"
run_mutant "craft check-brief loses +x"            "chmod -x plugins/superb/skills/craft/check-brief.sh"
run_mutant "skill README gutted"                   "printf '# x\n' > plugins/superb/skills/bug-fix/README.md"
run_mutant "skill README padded with filler"       "printf 'x %.0s' {1..200} > plugins/superb/skills/bug-fix/README.md"
run_mutant "skill dropped from plugin README"      "sed -i '/superb:bug-fix/d' plugins/superb/README.md"
run_mutant "skill dropped from root README"        "sed -i 's/superb:bug-fix/superb:removed/g' README.md"
run_mutant "skill dropped from marketplace desc"   "$J \"import pathlib; p=pathlib.Path('.claude-plugin/marketplace.json'); s=p.read_text(); assert 'bug-fix' in s, 'mutant is a no-op: bug-fix absent'; p.write_text(s.replace('bug-fix',''))\""
run_mutant "keywords stripped"                     "$J \"import json; p='plugins/superb/.claude-plugin/plugin.json'; d=json.load(open(p)); assert d.get('keywords') != ['x'], 'mutant is a no-op: keywords already stripped'; d['keywords']=['x']; json.dump(d,open(p,'w'),indent=2)\""
run_mutant "claude description blanked"            "$J \"import json; p='plugins/superb/.claude-plugin/plugin.json'; d=json.load(open(p)); assert d.get('description'), 'mutant is a no-op: description already blank'; d['description']=''; json.dump(d,open(p,'w'),indent=2)\""
run_mutant "codex longDescription blanked"         "$J \"import json; p='plugins/superb/.codex-plugin/plugin.json'; d=json.load(open(p)); assert d.get('interface',{}).get('longDescription'), 'mutant is a no-op: longDescription already blank'; d['interface']['longDescription']=''; json.dump(d,open(p,'w'),indent=2)\""
run_mutant "codex skills key removed"              "$J \"import json; p='plugins/superb/.codex-plugin/plugin.json'; d=json.load(open(p)); assert 'skills' in d, 'mutant is a no-op: skills key absent'; d.pop('skills'); json.dump(d,open(p,'w'),indent=2)\""
run_mutant "codex skills path bogus"               "$J \"import json; p='plugins/superb/.codex-plugin/plugin.json'; d=json.load(open(p)); assert d.get('skills') != './nope/', 'mutant is a no-op: path already bogus'; d['skills']='./nope/'; json.dump(d,open(p,'w'),indent=2)\""
run_mutant "namespace renamed in both manifests"   "$J \"import json; paths=['plugins/superb/.claude-plugin/plugin.json','plugins/superb/.codex-plugin/plugin.json']; data=[json.load(open(p)) for p in paths]; assert all(d.get('name')=='superb' for d in data), 'mutant is a no-op: manifest namespace baseline changed'; [(d.update(name='superbb'),json.dump(d,open(p,'w'),indent=2)) for p,d in zip(paths,data)]\""
run_mutant "codex marketplace name drifts"         "sed -i 's/\"name\": \"superb\"/\"name\": \"superbz\"/' .agents/plugins/marketplace.json"
run_mutant "codex marketplace source path bogus"   "sed -i 's|\"path\": \"./plugins/superb\"|\"path\": \"./plugins/nope\"|' .agents/plugins/marketplace.json"
run_mutant "undocumented plugin directory added"   "test ! -e plugins/evil || echo 'mutant is a no-op: plugins/evil already exists'; mkdir -p plugins/evil; printf '{}\n' > plugins/evil/x.json"
run_mutant "brief drifts between the two copies"   "sed -i 's/You are a bug investigation specialist\./& DRIFT./' plugins/superb/skills/bug-fix/references/investigator.md"
run_mutant "SHARED BRIEF markers deleted in both"  "sed -i '/SHARED BRIEF/d' plugins/superb/agents/bug-investigator.md plugins/superb/skills/bug-fix/references/investigator.md"
run_mutant "personal path reintroduced"            "printf '\nsee /home/someone/.claude/agent-memory/\n' >> plugins/superb/agents/bug-investigator.md"
run_mutant "personal path hidden in a .py file"    "printf '\n# /home/someone/audio-chat-app\n' >> plugins/superb/skills/craft/ui/server.py"
run_mutant "foreign build command reintroduced"    "printf '\nrun tools/build.sh after the merge\n' >> plugins/superb/skills/pipeline/references/execution.md"
run_mutant "foreign source tree reintroduced"      "printf '\nwhen extension/src/physics/ changed\n' >> plugins/superb/skills/pipeline/references/execution.md"
run_mutant "manifest JSON corrupted"               "printf '{\n' >> .claude-plugin/marketplace.json"
run_mutant "non-UTF8 byte in a checked file"       "printf '\\xff\\xfe' >> plugins/superb/skills/bug-fix/SKILL.md"
run_mutant "skills directory deleted"              "test -d plugins/superb/skills || echo 'mutant is a no-op: skills directory absent'; rm -rf plugins/superb/skills"
run_mutant "CI workflow deleted"                   "test -f .github/workflows/checks.yml || echo 'mutant is a no-op: workflow absent'; rm -f .github/workflows/checks.yml"
run_mutant "CI stops running the gate"             "sed -i 's|./tools/check-plugin.sh|./tools/nothing.sh|' .github/workflows/checks.yml"
run_mutant "wrapper passes an unrecognised argument" "sed -i 's|\"\$@\"|--bogus \"\$@\"|' tools/check-plugin.sh"
run_mutant "skill dispatches on an indexed placeholder" "printf '\nDispatch on \$0.\n' >> plugins/superb/skills/pipeline/SKILL.md"
run_mutant "invocation loses its namespace"        "sed -i '0,/\\/superb:pipeline/s//\\/pipeline/' plugins/superb/skills/pipeline/README.md"
run_mutant "namespace lost in a references page"   "printf '\nResume with /pipeline resume.\n' >> plugins/superb/skills/pipeline/references/execution.md"

# Narrow Pipeline v2 release contract. Every mutation explicitly checks the
# approved baseline anchor before changing it; run_mutant also proves the copy's
# complete snapshot changed before a kill can count.
run_mutant "v2 state helper is missing" '
f=plugins/superb/skills/pipeline/scripts/pipeline_state.py
[ -f "$f" ] || { echo "mutant is a no-op: pipeline_state.py already absent"; exit 0; }
rm "$f"
[ ! -e "$f" ] || echo "mutant is a no-op: pipeline_state.py was not removed"
'

run_mutant "v2 template loses schema marker" '
f=plugins/superb/skills/pipeline/templates/progress.md
grep -qF -- "pipeline-run/v2" "$f" || { echo "mutant is a no-op: v2 marker absent"; exit 0; }
sed -i "s/pipeline-run\/v2/pipeline-run\/broken/" "$f"
grep -qF -- "pipeline-run/broken" "$f" || echo "mutant is a no-op: marker replacement did not apply"
'

run_mutant "v2 execution reference is missing" '
f=plugins/superb/skills/pipeline/references/execution.md
[ -f "$f" ] || { echo "mutant is a no-op: execution reference already absent"; exit 0; }
rm "$f"
[ ! -e "$f" ] || echo "mutant is a no-op: execution reference was not removed"
'

run_mutant "one manifest reverts to 0.13.0" "$J \"import json; p='plugins/superb/.claude-plugin/plugin.json'; d=json.load(open(p)); assert d.get('version')=='0.14.0', 'mutant is a no-op: Claude manifest is not at the approved baseline'; d['version']='0.13.0'; json.dump(d,open(p,'w'),indent=2); assert json.load(open(p))['version']=='0.13.0', 'mutant is a no-op: version replacement did not apply'\""

run_mutant "CI loses setup-python@v5" '
f=.github/workflows/checks.yml
[ "$(grep -cF -- "uses: actions/setup-python@v5" "$f")" -eq 1 ] || { echo "mutant is a no-op: setup-python anchor is absent or ambiguous"; exit 0; }
sed -i "/uses: actions\/setup-python@v5/d" "$f"
! grep -qF -- "uses: actions/setup-python@v5" "$f" || echo "mutant is a no-op: setup-python line remains"
'

run_mutant "CI loses exact Pipeline test command" '
f=.github/workflows/checks.yml
command="python -m unittest discover -s plugins/superb/skills/pipeline/tests -v"
[ "$(grep -cF -- "$command" "$f")" -eq 1 ] || { echo "mutant is a no-op: Pipeline CI command anchor is absent or ambiguous"; exit 0; }
sed -i "s|$command|python -m unittest discover -s plugins/superb/skills/pipeline/tests -q|" "$f"
! grep -qF -- "$command" "$f" || echo "mutant is a no-op: Pipeline CI command remains"
'

run_mutant "CI reintroduces retired --run route" '
f=.github/workflows/checks.yml
retired="./tools/check-plugin.sh --run tools/fixtures/run-ok"
! grep -qF -- "$retired" "$f" || { echo "mutant is a no-op: retired route already present"; exit 0; }
[ "$(grep -cF -- "      - run: ./tools/check-plugin.sh" "$f")" -eq 1 ] || { echo "mutant is a no-op: bare gate anchor is absent or ambiguous"; exit 0; }
sed -i "/      - run: \.\/tools\/check-plugin\.sh$/a\\      - run: $retired" "$f"
grep -qF -- "$retired" "$f" || echo "mutant is a no-op: retired route insertion did not apply"
'

# Shared run-directory ignore policy retained with changed-target protection.
run_mutant "gitignore drops the run-directory rule" "sed -i '/^docs\\/superpowers\\/runs\\/\\*\\/$/d' .gitignore"
run_mutant "gitignore hides curated documentation too" "printf '\ndocs/superpowers/\n' >> .gitignore"
run_mutant "gitignore hides curated records behind a double star" "sed -i 's|^docs/superpowers/runs/\*/$|docs/superpowers/runs/**|' .gitignore"
run_mutant "gitignore hides curated records behind a double-star glob" "sed -i 's|^docs/superpowers/runs/\*/$|docs/superpowers/runs/**/*|' .gitignore"
run_mutant "gitignore narrows to a single star with no slash" "sed -i 's|^docs/superpowers/runs/\*/$|docs/superpowers/runs/*|' .gitignore"

echo
printf '%s killed; %s survived; %s no-op\n' "$PASS" "$SURV" "$NOOP"
if [ "$SURV" -ne 0 ]; then
  printf 'survivors:\n'
  printf '  %s\n' "${SURVIVORS[@]}"
fi
if [ "$NOOP" -ne 0 ]; then
  printf 'no-op mutants:\n'
  printf '  %s\n' "${NOOPS[@]}"
fi
if [ "$SURV" -ne 0 ] || [ "$NOOP" -ne 0 ]; then
  echo "check-plugin-mutants: FAIL"
  exit 1
fi
echo "check-plugin-mutants: PASS"
