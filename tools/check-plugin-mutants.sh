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

# The mutation script's own output is CAPTURED, and printed only when the mutant
# SURVIVES. Several mutants assert their own preconditions ("mutant is a no-op:
# the sentence has been reworded") precisely so that prose rot cannot turn them
# into silent no-ops — and discarding that message left the operator reading
# `SURVIVED  <name>` with no way to tell a rotted mutant from a real hole in the
# gate. A killed mutant still prints exactly one line, as before.
run_mutant() { # name, shell applied inside the copy
  local name="$1" script="$2" dir="$WORK/m" out
  rm -rf "$dir"; mkdir -p "$dir"
  tar -C "$SRC" --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$dir" -xf -
  out="$( ( cd "$dir" && eval "$script" ) 2>&1 )"
  if ( cd "$dir" && ./tools/check-plugin.sh ) >/dev/null 2>&1; then
    printf '  SURVIVED  %s\n' "$name"; SURV=$((SURV+1)); SURVIVORS+=("$name")
    if [ -n "$out" ]; then printf '%s\n' "$out" | sed 's/^/            | /'; fi
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
# The run-mode mutants below all start from tools/fixtures/run-ok CONFORMING:
# each one breaks it in a single named way, and a kill only means what its name
# says if everything else about the fixture was green first. Nothing else checks
# that — the default mode never reads tools/fixtures/ — so it is checked here,
# where the rest of the baseline is.
if ( cd "$D" && ./tools/check-plugin.sh --run tools/fixtures/run-ok ) >/dev/null 2>&1; then
  echo "  ok    clean copy passes with --run over tools/fixtures/run-ok"
else
  echo "  FAIL  tools/fixtures/run-ok does not conform on a clean copy — every run-mode mutant below would then kill for that reason instead of its own"
  ( cd "$D" && ./tools/check-plugin.sh --run tools/fixtures/run-ok ) | grep FAIL
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
# The run mode is a SEPARATE CI step, and deleting it is invisible to the arm
# that lists `./tools/` scripts — both invocations name the same script. So this
# deletes only that step and leaves the bare one: `refs` is unchanged, both
# required scripts are still run, and the only arm that can fire is the one
# reading the raw text for `--run`. Guarded at both ends.
run_mutant "CI stops running the gate in run mode" '
f=.github/workflows/checks.yml
if [ "$(grep -cF -- "check-plugin.sh --run " "$f")" != 1 ]; then
  echo "mutant is a no-op: checks.yml no longer runs the gate in run mode exactly once, so there is no step to delete"
else
  sed -i "/check-plugin.sh --run /d" "$f"
  grep -qF -- "check-plugin.sh --run " "$f" && echo "mutant is a no-op: the run-mode step was not deleted"
  grep -qF -- "./tools/check-plugin.sh" "$f" || echo "mutant is a no-op: it took the bare invocation too, so a kill could come from the script-list arm instead"
  grep -qF -- "./tools/check-plugin-mutants.sh" "$f" || echo "mutant is a no-op: it took the harness step too, so a kill could come from the script-list arm instead"
fi'

# --- the pipeline review-line linter must itself stay honest ---
run_mutant "RV example loses a report file"        "sed -i 's|p3-review-{a,b,int}.md|p3-review-{a,b}.md|' plugins/superb/skills/pipeline/references/run-state.md"
run_mutant "RVJ example declares slice reviewers"  "sed -i 's|N=17 → 0 slice + 1 integration · reports j-56-int.md|N=17 → 4 slice + 1 integration · reports j-56-{a,b,c,d,int}.md|' plugins/superb/skills/pipeline/references/run-state.md"
run_mutant "RV example loses its coverage file"    "sed -i 's| · coverage p3-coverage.md||' plugins/superb/skills/pipeline/references/run-state.md"
# Retargeted when the re-review fan-out stopped being sized off the finding
# count: the worked round went from `3 slice + 1 integration` over four report
# files to `1 slice + 0 integration` over one, so the old sed on
# `p3-rr2-{a,b,c,int}.md` now matches nothing. A sed on a string the docs no
# longer contain is a silent no-op, the harness reports SURVIVED, and a mutant
# that changes nothing proves nothing — two mutants here have already had to be
# retargeted for exactly that. So this one over-declares the reviewer count
# instead of shrinking the file list, and it ASSERTS both ends: the example is
# present exactly once before, and the replacement landed. Rot refuses loudly
# with its message printed instead of passing as a no-op.
# The arrow is built with \u2192 rather than written literally, like the
# no-round mutant below, so this line survives any editor that re-encodes it.
run_mutant "re-review round over-declares reviewers" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md'); s=p.read_text()
a='M=9 \u2192 1 slice + 0 integration'
assert s.count(a)==1, 'mutant is a no-op: the re-review round example is absent, reworded, or duplicated'
out=s.replace(a, 'M=9 \u2192 3 slice + 1 integration')
assert out!=s, 'mutant is a no-op: the over-declaration did not apply'
p.write_text(out)\""
run_mutant "every worked RV example deleted"       "sed -i '/· reports/d' plugins/superb/skills/pipeline/*.md plugins/superb/skills/pipeline/*/*.md"

# --- the linter must also be able to fail over a REAL run directory ---
# `--run <dir>` lints `<dir>/progress.md` with the same rules plus one the
# worked examples cannot support: the named report files either exist in
# `agent-output/` or they do not. tools/fixtures/run-ok/ is a conforming run
# directory that exists for these mutants to break.
#
# This harness only ever invokes `./tools/check-plugin.sh` with NO arguments,
# so every mutant below first has to make the mode reachable. `enable_run`
# injects `--run tools/fixtures/run-ok` into the copy's wrapper, and refuses
# loudly rather than silently if the wrapper stops forwarding its arguments —
# an unreachable mode would make each of these a no-op that reports SURVIVED
# for a reason that has nothing to do with what it set out to break. Injecting
# alone is deliberately NOT a mutation: the fixture conforms, so a copy with
# only `enable_run` applied must still PASS, which is what makes each fixture
# edit below the whole cause of its own kill.
enable_run() { # inside the copy: make the wrapper pass --run by default
  local f=tools/check-plugin.sh a='check-plugin.py" "$@"'
  if ! grep -qF "$a" "$f"; then
    echo "mutant is a no-op: the wrapper no longer invokes check-plugin.py with forwarded arguments, so --run cannot be reached"
    return 1
  fi
  sed -i 's|check-plugin.py" "$@"|check-plugin.py" --run tools/fixtures/run-ok "$@"|' "$f"
  if ! grep -qF -- '--run tools/fixtures/run-ok' "$f"; then
    echo "mutant is a no-op: --run was not injected into the wrapper, so the run mode was never entered"
    return 1
  fi
}
# An unrecognised argument must be REFUSED, not ignored. Ignored, `--rn` runs
# the default mode and prints PASS, which a caller reads as "the run directory
# conforms" when the run directory was never opened.
run_mutant "wrapper passes an unrecognised argument" '
f=tools/check-plugin.sh; a="check-plugin.py\" \""
if ! grep -qF "$a" "$f"; then
  echo "mutant is a no-op: the wrapper no longer invokes check-plugin.py with an argument list"
else
  sed -i "s|check-plugin.py\" \"|check-plugin.py\" --rn tools/fixtures/run-ok \"|" "$f"
  grep -qF -- "--rn tools/fixtures/run-ok" "$f" || echo "mutant is a no-op: the bad argument was not injected"
fi'
# `--run` with NO OPERAND must print the usage line, not index past the end of
# the argument list. Neutralise `if len(_argv) < 2` and `_argv[1]` raises
# `IndexError` — also a non-zero exit, so exit status alone cannot tell the
# named usage message from a traceback. Measured: with the guard deleted, this
# harness's own no-argument invocation exits 0 and the mutant reports SURVIVED,
# so the guard is not "killed either way" — it is not held at all unless the
# message is what is asserted.
# So this one asserts the MESSAGE, on the `cited predicate file unreadable`
# precedent: inject an operandless `--run` into the copy's wrapper, grep the
# captured output for the exact usage line, and if it is absent put the wrapper
# back — leaving a clean copy that PASSES, so the harness reports SURVIVED with
# its reason printed instead of passing on a traceback. Measured both ways:
# guard present -> killed; guard deleted -> SURVIVED.
# Output is captured before grepping rather than piped into it, since under
# `set -o pipefail` a failing left-hand side would mask a matching grep.
# The held copy lives under `$WORK`, so the EXIT trap reclaims it on interrupt.
run_mutant "wrapper passes --run with no operand" '
f=tools/check-plugin.sh; a="check-plugin.py\" \""
k="$WORK/held-wrapper.sh"
if ! grep -qF "$a" "$f"; then
  echo "mutant is a no-op: the wrapper no longer invokes check-plugin.py with an argument list, so an operandless --run cannot be injected"
else
  cp "$f" "$k"
  sed -i "s|check-plugin.py\" \"|check-plugin.py\" --run \"|" "$f"
  if ! grep -qF -- "--run \"" "$f"; then
    echo "mutant is a no-op: the operandless --run was not injected"
    cp "$k" "$f"; rm -f "$k"
  else
    o="$(./tools/check-plugin.sh 2>&1)"
    if printf "%s\n" "$o" | grep -qF "usage: check-plugin.py [--run <run-directory>]"; then
      rm -f "$k"
    else
      echo "mutant is a no-op: an operandless --run did not print the usage line, so the wrapper was restored and this mutant reports SURVIVED instead of passing on a traceback or a silent default-mode run"
      cp "$k" "$f"; rm -f "$k"
    fi
  fi
fi'
# Anchored on the ASCII half of the declaration, not on the arrow: the arrow is
# a multi-byte character an editor can re-encode, and a sed that matches
# nothing is a mutant that proves nothing. Both ends asserted.
run_mutant "run tracker over-declares reviewers" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -cF "1 slice + 0 integration" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer declares 1 slice + 0 integration exactly once"
else
  sed -i "s|1 slice + 0 integration|3 slice + 1 integration|" "$f"
  grep -qF "3 slice + 1 integration" "$f" || echo "mutant is a no-op: the over-declaration did not apply"
fi'
# The one check a run directory permits and the worked examples cannot: rename
# the report file the round names, leave the file itself in place. The declared
# count still matches the listed count, so this kill is attributable to the
# existence check and to nothing else.
run_mutant "run tracker cites a report file that is not in agent-output" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "reports p1-review-a.md" "$f"; then
  echo "mutant is a no-op: the fixture round no longer names p1-review-a.md"
elif [ -e tools/fixtures/run-ok/agent-output/p1-review-z.md ]; then
  echo "mutant is a no-op: p1-review-z.md exists in the fixture, so the renamed file would be found"
else
  sed -i "s|reports p1-review-a.md|reports p1-review-z.md|" "$f"
  grep -qF "reports p1-review-z.md" "$f" || echo "mutant is a no-op: the rename did not apply"
fi'
# The same check for the OTHER named artifact. The coverage test used to
# establish only that the FIELD was present, so a round naming a coverage file
# nobody wrote passed while the same round's report names were checked against
# the directory. This renames the coverage FILENAME and leaves the field, so
# neither the missing-field branch nor the reviewer-count arm can fire and the
# kill belongs to the existence check alone. Guarded at both ends, and the
# renamed target is verified absent from agent-output/ — otherwise the mutation
# would name a file that happens to exist and prove nothing.
run_mutant "run tracker cites a coverage file that is not in agent-output" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -cF "coverage p1-coverage.md" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer names coverage p1-coverage.md exactly once"
elif [ -e tools/fixtures/run-ok/agent-output/p1-coverage-z.md ]; then
  echo "mutant is a no-op: p1-coverage-z.md exists in the fixture, so the renamed file would be found"
else
  sed -i "s|coverage p1-coverage.md|coverage p1-coverage-z.md|" "$f"
  grep -qF "coverage p1-coverage-z.md" "$f" || echo "mutant is a no-op: the rename did not apply"
  grep -qF "reports p1-review-a.md" "$f" || echo "mutant is a no-op: it took the reports field too, so a kill could come from the reviewer-count arm instead"
fi'
# Renames the coverage FIELD rather than deleting the segment, so the kill is
# attributable to the coverage arm alone. Asserts the reports field survives.
run_mutant "run tracker round loses its coverage field" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -cF "coverage p1-coverage.md" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer names coverage p1-coverage.md exactly once"
else
  sed -i "s|coverage p1-coverage.md|notes p1-coverage.md|" "$f"
  grep -qF "notes p1-coverage.md" "$f" || echo "mutant is a no-op: the coverage field was not renamed"
  grep -qF "reports p1-review-a.md" "$f" || echo "mutant is a no-op: it took the reports field too, so a kill could come from the reviewer-count arm instead"
fi'
# THE RECORD BOUNDARY, and the one mutation that can see it. A run record used
# to end at 400 flattened characters — a window calibrated on the skill's terse
# worked examples — so a conforming round whose `coverage` field sat past that
# was reported as missing one. The fixture's Phase 3 is such a round (its
# fields sit at offsets 665 and 700), and the harness's own baseline `--run`
# check is what holds the window's removal: put a byte cap back and the clean
# copy stops passing, which aborts this run with that named message before any
# mutant is attempted.
#
# What the cap's replacement adds beyond "no cap" is the END: the record stops
# at the next `- [` bullet. Only text BETWEEN a round and the next bullet can
# distinguish the two, so the fixture puts some there on purpose — Phase 3's
# closing `T4` names a coverage file in its own subject. This mutant renames
# the coverage field on the ROUND, leaving `T4`'s intact: bounded at the
# bullet, the round has no coverage of its own and the gate says so; unbounded,
# it borrows `T4`'s and passes. Measured: with the boundary -> killed; with the
# boundary branch removed -> SURVIVED.
#
# Line-addressed and asserted at both ends, because the literal
# `coverage p3-coverage.md` appears TWICE in the fixture and renaming the wrong
# one proves nothing: the round's line is identified by its `reports` field,
# the rename is verified to have landed on it, and `T4`'s copy is verified to
# have survived — without which the kill would be the ordinary coverage arm
# firing rather than the boundary.
run_mutant "long run-tracker round loses its coverage field" '
enable_run || exit 0
'"$J"' "import pathlib
p=pathlib.Path(\"tools/fixtures/run-ok/progress.md\")
L=p.read_text().split(chr(10))
key=\"reports p3-review-{a,b,c,int}.md\"
i=[n for n,x in enumerate(L) if key in x]
assert len(i)==1, \"mutant is a no-op: the long round no longer names its brace-expanded report set exactly once\"
assert \"coverage p3-coverage.md\" in L[i[0]], \"mutant is a no-op: the long round no longer carries a coverage field on that line\"
L[i[0]]=L[i[0]].replace(\"coverage p3-coverage.md\", \"notes p3-coverage.md\")
out=chr(10).join(L)
assert \"notes p3-coverage.md\" in out, \"mutant is a no-op: the coverage field was not renamed\"
assert key in out, \"mutant is a no-op: it took the reports field too, so a kill could come from the reviewer-count arm instead\"
assert \"coverage p3-coverage.md\" in out, \"mutant is a no-op: the T4 bullet that carries the borrowable coverage field went too, so a kill would not be attributable to the record boundary\"
p.write_text(out)"'
# `p2-review-{a,b,int}.md` is one written name and three files. Deleting ONE
# member proves the existence check expands the brace set instead of testing
# the literal string — which the conforming fixture already proves it must,
# since a literal `p2-review-{a,b,int}.md` exists nowhere.
run_mutant "run tracker loses one brace-expanded report file" '
enable_run || exit 0
t=tools/fixtures/run-ok/agent-output/p2-review-b.md
if [ ! -f "$t" ]; then
  echo "mutant is a no-op: the brace-expanded member p2-review-b.md is already absent from the fixture"
else
  grep -qF "reports p2-review-{a,b,int}.md" tools/fixtures/run-ok/progress.md ||
    echo "mutant is a no-op: the fixture round no longer names a brace-expanded report set"
  rm -f "$t"
  [ ! -e "$t" ] || echo "mutant is a no-op: the report file was not removed"
fi'
# A `--run` over a tracker with nothing closed must not read as a clean review.
run_mutant "run tracker has no closed review round" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "\[x\] RV" "$f")" != 3 ]; then
  echo "mutant is a no-op: the fixture no longer holds exactly three closed RV records"
else
  sed -i "/\[x\] RV/d" "$f"
  grep -q "\[x\] RV" "$f" && echo "mutant is a no-op: the closed records were not removed"
fi'
# Both "missing" branches must report a NAMED failure of their own, and each
# mutant below is what says so: neutralise either branch and its mutant is the
# only one in the whole harness that survives.
run_mutant "run directory has no progress.md" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ ! -f "$f" ]; then
  echo "mutant is a no-op: the fixture has no progress.md to remove"
else
  rm -f "$f"
  [ ! -e "$f" ] || echo "mutant is a no-op: progress.md was not removed"
fi'
run_mutant "run directory has no agent-output" '
enable_run || exit 0
d=tools/fixtures/run-ok/agent-output
if [ ! -d "$d" ]; then
  echo "mutant is a no-op: the fixture has no agent-output/ to remove"
else
  rm -rf "$d"
  [ ! -e "$d" ] || echo "mutant is a no-op: agent-output/ was not removed"
fi'

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
# SKILL.md only POINTS at the re-tag predicate ("by the predicate in
# references/fix-loop.md"); the predicate itself lives in that file. Deleting it
# there used to leave SKILL.md with a dangling pointer and the gate green, so the
# whole routing rule was one edit from gone. This mutant deletes the predicate.
# Line-addressed and asserted, not sed'd on prose: a regex spanning the wrapped
# sentence would silently match nothing the next time the paragraph re-wrapped,
# and a mutation that changes nothing reports `killed` for the wrong reason.
#
# TWO assertions, not three. Anchors 1 (the predicate line) and 2 (the `visible.`
# terminator) fully determine the deletion range; trimming the opener stub off
# the preceding line only makes the throwaway copy read cleanly, so it is applied
# WHEN IT FITS and asserted never. Asserted, it pinned a line-break position
# inside a wrapped sentence — the most volatile property of prose — and two of
# four tested re-wraps tripped that anchor and nothing else. Deleting the range
# without the trim still kills.
# Anchor 2 tests `endswith('visible.')`, not equality, so the reflow that absorbs
# a one-word last line upward — what any fill-paragraph does — moves the
# terminator without tripping the anchor. Exactly one line ends there under
# either form, so the deletion range is identical; rot still refuses loudly.
run_mutant "cited re-tag predicate deleted from fix-loop.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
L=p.read_text().split(chr(10)); tick=chr(96)
head='So **an incoming '+tick+'Important'+tick+' is'
a=[i for i,x in enumerate(L) if 're-tagged** by consequence' in x]
b=[i for i,x in enumerate(L) if x.strip().endswith('visible.')]
assert len(a)==1, 'mutant is a no-op: the re-tag predicate has been reworded'
assert len(b)==1 and b[0]>a[0], 'mutant is a no-op: the predicate no longer ends at visible.'
i=a[0]
if L[i-1].endswith(head): L[i-1]=L[i-1][:-len(head)].rstrip()
del L[i:b[0]+1]
p.write_text(chr(10).join(L))\""
# The predicate exists TWICE — the authority in references/fix-loop.md and the
# copy in templates/findings.md, which is what gets copied into the run
# directory and is therefore the text the consolidating agent actually reads
# while writing ledger rows. Deleting the copy left both gates green, which is
# the same unheld-second-copy weakness the mutant above was added to fix. This
# one deletes the copy.
# Paragraph-scoped and whitespace-normalised, so it does not pin a line-break
# position: it finds the ONE blank-line-delimited paragraph whose flattened text
# carries the re-tag phrase and deletes the whole paragraph. If the phrase is
# reworded or duplicated, the assert raises, the mutation does not apply, and the
# mutant SURVIVES loudly with its message printed — never a silent no-op.
run_mutant "cited re-tag predicate deleted from findings.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/templates/findings.md')
s=p.read_text(); tick=chr(96); nl=chr(10)
key='an incoming '+tick+'Important'+tick+' is re-tagged'
paras=s.split(nl+nl)
hit=[i for i,x in enumerate(paras) if key in ' '.join(x.split())]
assert len(hit)==1, 'mutant is a no-op: findings.md has no single re-tag paragraph'
del paras[hit[0]]
p.write_text((nl+nl).join(paras))\""
# The `if pe:` arm — the one that reports a cited predicate file it cannot READ —
# cannot be proven by exit status. Delete that arm and the named FAIL becomes an
# AttributeError traceback one line down; both are red builds, so no pass/fail
# mutant separates them. This mutant asserts the MESSAGE instead: it removes the
# cited file, and if the gate does not name that file and reason, it puts the file
# back — leaving a clean copy that PASSES, so the harness reports SURVIVED. The
# signal still travels as pass/fail, so run_mutant's contract is untouched and
# every other mutant is unaffected.
# check-plugin.sh's output is captured before grepping rather than piped into it:
# under `set -o pipefail` a failing left-hand side would mask a matching grep and
# revert a mutation that had in fact been caught.
# The held copy lives under `$WORK`, not in a bare `$(mktemp)`, so the EXIT trap
# reclaims it on interrupt like everything else this harness creates.
run_mutant "cited predicate file unreadable" '
f=plugins/superb/skills/pipeline/references/fix-loop.md
k="$WORK/held-fix-loop.md"
cp "$f" "$k"
rm -f "$f"
o="$(./tools/check-plugin.sh 2>&1)"
if printf "%s\n" "$o" | grep -q "fix-loop.md must carry, but that file cannot be read"; then
  rm -f "$k"
else
  echo "mutant is a no-op: the gate no longer names the unreadable cited file and its reason, so the file was restored and this mutant reports SURVIVED instead of passing on a traceback"
  cp "$k" "$f"; rm -f "$k"
fi'

# The claim-finding closure rule is held BY PHRASE in the authority
# (references/fix-loop.md) and in the copy that ships into the run directory
# (templates/findings.md), where the closing agent actually reads it. A rule held
# in neither text is deletable on a green build — which is the failure the rule
# is itself about, so it does not get to be the one rule nothing holds.
#
# Paragraph-scoped and whitespace-normalised, so no line-break position is
# pinned: the mutation deletes every blank-line-delimited paragraph whose
# flattened text names the term.
#
# What the two asserts actually check, precisely: that at least one paragraph
# was removed, and that the flattened term is absent from the result. That kills
# the case this mutant exists for — a COMPLETE reword, after which no paragraph
# matches and the first assert fires loudly. It does NOT catch a partial reword:
# a line-based edit that misses a wrapped occurrence leaves the flattened term
# matching somewhere, so some paragraph is still deleted, the term is still gone
# afterwards, both asserts pass — and the paragraph deleted may not be the rule.
# That case mutates something other than intended and prints nothing. It is
# harmless only while the gate arm is live, since a rule the arm no longer finds
# fails the gate whichever paragraph went; the arm is the guarantee here, and
# these asserts only close the silent-no-op door on a full reword.
run_mutant "claim-finding closure rule deleted from fix-loop.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); nl=chr(10); key='claim finding'
paras=s.split(nl+nl)
keep=[x for x in paras if key not in ' '.join(x.split()).lower()]
assert len(keep)<len(paras), 'mutant is a no-op: fix-loop.md no longer names a claim finding'
out=(nl+nl).join(keep)
assert key not in ' '.join(out.split()).lower(), 'mutant is a no-op: the term survives the paragraph deletion'
p.write_text(out)\""
# The same deletion against the copy. Held separately: the authority and the copy
# are edited independently, so a kill on one says nothing about the other — and
# the copy is the one the template says gets copied into the run directory.
run_mutant "claim-finding closure rule deleted from findings.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/templates/findings.md')
s=p.read_text(); nl=chr(10); key='claim finding'
paras=s.split(nl+nl)
keep=[x for x in paras if key not in ' '.join(x.split()).lower()]
assert len(keep)<len(paras), 'mutant is a no-op: findings.md no longer names a claim finding'
out=(nl+nl).join(keep)
assert key not in ' '.join(out.split()).lower(), 'mutant is a no-op: the term survives the paragraph deletion'
p.write_text(out)\""

# The closure rule's consequences, held in the authority only: the `M`-exclusion
# and coverage-union phrases in the *Re-review fan-out* bullet, and the
# `M=0 → no round` condition on the fix loop's step 3. Deleting any of them
# reinstates the contradiction the rule removed — a fan-out demanding an owner
# for a diff the rule excluded, or a step 3 mandating a round the rule says
# never happens — and before the CLAIM_EFFECT arm all of those deletions were
# green.
#
# ONE SURGICAL MUTANT PER PHRASE, because the `M`-exclusion and coverage-union
# phrases now live in the SAME bullet. A mutant that deletes that bullet fires
# both arms, so it is killed by whichever one survives the other's removal and
# individually holds NEITHER: at the revision before the two phrases were
# deduplicated, removing the `M`-exclusion entry made the bullet-deletion mutant
# SURVIVE; after the dedup the same removal left `survived=0`. Blurring one
# phrase while asserting the other is untouched is what restores the
# attribution the bullet deletion lost.
#
# Each mutant asserts the phrase it targets is present exactly once BEFORE (or
# it is a no-op on prose that already rotted), that the blur landed, and that
# every OTHER held phrase survived — so the kill is attributable to the phrase
# named in the mutant's own name and cannot be borrowed from a sibling.
# Backticks are built with chr(96): a literal one inside this double-quoted
# shell argument would be command substitution.
# Both phrases are matched with `\s+` between words rather than as literals: the
# gate reads them out of FLATTENED text, so either can sit across a line break
# in the source — the coverage-union phrase does — and a literal match would
# have been a silent no-op rather than a mutation.
run_mutant "M-exclusion phrase blurred in fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile('is'+chr(92)+'s+not'+chr(92)+'s+counted'+chr(92)+'s+in'+chr(92)+'s+'+bt+'M'+bt)
u=re.compile('fix'+chr(92)+'s+commit'+chr(92)+'s+is'+chr(92)+'s+not'+chr(92)+'s+in'+chr(92)+'s+that'+chr(92)+'s+union')
assert len(a.findall(s))==1, 'mutant is a no-op: the M-exclusion phrase is absent, reworded or duplicated'
out=a.sub('sits outside the round tally', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(u.findall(out))==1, 'mutant is a no-op: the coverage-union phrase went too, so a kill would not be attributable to the M-exclusion phrase'
assert 'the number of blocking F-IDs this fix-mode run targeted' in out, 'mutant is a no-op: the definition went too, so a kill would not be attributable to the M-exclusion phrase'
assert 'm=0 → no round' in flat(out), 'mutant is a no-op: the no-round form went too, so a kill would not be attributable to the M-exclusion phrase'
p.write_text(out)\""
run_mutant "coverage-union phrase blurred in fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile('is'+chr(92)+'s+not'+chr(92)+'s+counted'+chr(92)+'s+in'+chr(92)+'s+'+bt+'M'+bt)
u=re.compile('fix'+chr(92)+'s+commit'+chr(92)+'s+is'+chr(92)+'s+not'+chr(92)+'s+in'+chr(92)+'s+that'+chr(92)+'s+union')
assert len(u.findall(s))==1, 'mutant is a no-op: the coverage-union phrase is absent, reworded or duplicated'
out=u.sub('fix commit stays outside it', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==1, 'mutant is a no-op: the M-exclusion phrase went too, so a kill would not be attributable to the coverage-union phrase'
assert 'the number of blocking F-IDs this fix-mode run targeted' in out, 'mutant is a no-op: the definition went too, so a kill would not be attributable to the coverage-union phrase'
assert 'm=0 → no round' in flat(out), 'mutant is a no-op: the no-round form went too, so a kill would not be attributable to the coverage-union phrase'
p.write_text(out)\""
run_mutant "no-round RV form deleted from fix-loop.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); nl=chr(10); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
key='m=0 \u2192 no round'
assert key in flat(s), 'mutant is a no-op: the no-round RV form is already absent or reworded'
paras=s.split(nl+nl)
keep=[x for x in paras if key not in flat(x)]
assert len(keep)<len(paras), 'mutant is a no-op: no paragraph carries the form'
out=(nl+nl).join(keep)
assert key not in flat(out), 'mutant is a no-op: the form survives the paragraph deletion'
assert 'not counted in '+bt+'M'+bt in out, 'mutant is a no-op: it removed the M-exclusion bullet too, so a kill would not be attributable to the no-round form'
p.write_text(out)\""
# The SAME deletion against the two OTHER files that define the `RV` grammar and
# now carry the form verbatim. Held separately for the reason the re-tag
# predicate's copy is: deleting every no-round paragraph from SKILL.md, and
# separately from references/run-state.md, left BOTH gates green — an unheld
# second and third copy of a rule that is then one edit from gone — the same
# shape the re-tag predicate's copy in templates/findings.md was held for.
#
# Each asserts the form is present before, that some paragraph went, and that
# the form is gone after, so a full reword refuses loudly instead of passing as
# a no-op. Attribution is by reading the AUTHORITY, which these two never touch:
# if fix-loop.md had lost the form as well then the tree was already broken and
# a kill here would not be attributable to the copy the mutant names.
run_mutant "no-round RV form deleted from SKILL.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
q=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); nl=chr(10)
flat=lambda x: ' '.join(x.split()).lower()
key='m=0 \u2192 no round'
assert key in flat(s), 'mutant is a no-op: SKILL.md no longer carries the no-round RV form'
paras=s.split(nl+nl)
keep=[x for x in paras if key not in flat(x)]
assert len(keep)<len(paras), 'mutant is a no-op: no SKILL.md paragraph carries the form'
out=(nl+nl).join(keep)
assert key not in flat(out), 'mutant is a no-op: the form survives the paragraph deletion'
assert key in flat(q.read_text()), 'mutant is a no-op: the authority lost the form too, so a kill would not be attributable to the SKILL.md copy'
p.write_text(out)\""
run_mutant "no-round RV form deleted from run-state.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
q=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); nl=chr(10)
flat=lambda x: ' '.join(x.split()).lower()
key='m=0 \u2192 no round'
assert key in flat(s), 'mutant is a no-op: run-state.md no longer carries the no-round RV form'
paras=s.split(nl+nl)
keep=[x for x in paras if key not in flat(x)]
assert len(keep)<len(paras), 'mutant is a no-op: no run-state.md paragraph carries the form'
out=(nl+nl).join(keep)
assert key not in flat(out), 'mutant is a no-op: the form survives the paragraph deletion'
assert key in flat(q.read_text()), 'mutant is a no-op: the authority lost the form too, so a kill would not be attributable to the run-state.md copy'
p.write_text(out)\""

# `M`'s DEFINITION, one level up from the condition the four mutants above
# hold. `CLAIM_EFFECT` held `m=0 → no round` in three files and the two
# exclusions in the authority, but nothing held the sentence that says what `M`
# IS: deleting the whole `**Unless `M=0`.**` paragraph — the definition and its
# closed exclusion-route list together — left `check-plugin: PASS` and every
# mutant killed, because the only place the no-round arm's phrase occurs in that
# file is a worked-example fence. A condition with an undefined subject is the
# same hole those three closed, moved up a level.
#
# Two mutants because the paragraph carries two separable claims. This first one
# reproduces the proven hole exactly — the whole paragraph goes — and so proves
# the paragraph is held at all; both new phrases live in it, so this kill says
# "the definition paragraph is held", not which half. Attribution against the
# OLDER arms is what it does assert: the `M`-exclusion bullet and the no-round
# form both survive, so the kill cannot be borrowed from any of the three
# entries that were already there. Which half is held is what the next mutant
# pins.
run_mutant "M's definition paragraph deleted from fix-loop.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); nl=chr(10); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
key='the number of blocking f-ids this fix-mode run targeted'
assert key in flat(s), 'mutant is a no-op: fix-loop.md no longer states what M is'
paras=s.split(nl+nl)
keep=[x for x in paras if key not in flat(x)]
assert len(keep)<len(paras), 'mutant is a no-op: no paragraph carries the definition'
out=(nl+nl).join(keep)
assert key not in flat(out), 'mutant is a no-op: the definition survives the paragraph deletion'
assert 'not counted in '+bt+'M'+bt in out, 'mutant is a no-op: it removed the M-exclusion bullet too, so a kill would not be attributable to the definition paragraph'
assert 'm=0 → no round' in flat(out), 'mutant is a no-op: it removed the no-round form too, so a kill would not be attributable to the definition paragraph'
p.write_text(out)\""
# The DEFINITION half, surgically. The paragraph mutant above kills through
# either phrase, so it holds neither on its own: with the `M`'s-definition entry
# removed from CLAIM_EFFECT the whole suite still reported `survived=0`, because
# the route-list entry killed the paragraph deletion by itself. This blurs the
# definition ALONE — the route list, the exclusion bullet and the no-round form
# all stay — so the only arm that can reject it is the one whose name it bears.
# The replacement keeps a count-shaped sentence on purpose: a gate that only
# noticed the sentence vanishing would miss the shorter gloss that is what
# actually happens to a definition.
run_mutant "M's definition blurred in fix-loop.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
a='**the number of blocking F-IDs this fix-mode run targeted**'
assert s.count(a)==1, 'mutant is a no-op: the definition is absent, reworded or duplicated'
out=s.replace(a, '**the count this round declares**')
assert out!=s, 'mutant is a no-op: the definition was not blurred'
assert 'excluded exactly when its closure route is a deletion or a user-ruled false positive' in flat(out), 'mutant is a no-op: the exclusion-route list went too, so a kill would not be attributable to the definition'
assert 'is not counted in '+bt+'M'+bt in out, 'mutant is a no-op: the M-exclusion phrase went too, so a kill would not be attributable to the definition'
assert 'm=0 → no round' in flat(out), 'mutant is a no-op: the no-round form went too, so a kill would not be attributable to the definition'
p.write_text(out)\""
# The other half, and the one that reproduces a defect that actually shipped:
# the exclusion-route list SHORTENED rather than deleted. `SKILL.md`'s
# *Re-review fan-out* glossed `M` with two of the three dispositions and lost
# `user-ruled false positive`, which makes a false-positive-only iteration
# `M=1` with a round owed over an empty diff. Here the same loss is injected
# into the authority.
#
# Surgical, so attribution is exact: the definition phrase is asserted to
# survive, so the kill comes from the route-list entry and not from the mutant
# above. Also asserts the anchor was there once and that the shortening landed,
# so a reword refuses loudly instead of passing as a no-op.
run_mutant "M's exclusion-route list loses a route" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text()
flat=lambda x: ' '.join(x.split()).lower()
a='is a deletion or a user-ruled false positive'
assert s.count(a)==1, 'mutant is a no-op: the closed exclusion-route list is absent, reworded or duplicated'
out=s.replace(a, 'is a deletion')
assert out!=s, 'mutant is a no-op: the route was not dropped'
assert 'the number of blocking f-ids this fix-mode run targeted' in flat(out), 'mutant is a no-op: the definition went too, so a kill would not be attributable to the route list'
p.write_text(out)\""

# --- the rule the exclusions qualify: one reviewer per file cluster ---
# `M`'s definition, its exclusions and the `M=0` licence were all held before
# this; the SIZING rule they qualify was not. Reverting the fan-out table's
# rows, the file-cluster bullet and the Invariant to a count over the findings
# left `check-plugin: PASS` with every mutant killed. These two mutants are the
# pin, one per file that states the rule.
#
# Each blurs EVERY occurrence in its own file — the phrase has two homes in the
# authority (the table row and the Invariant) and three in `SKILL.md`, and the
# arm reads flattened text, so a mutation that leaves one standing is a no-op
# that reports `killed` for no reason. Matched with `\s+` between words rather
# than as a literal, because the gate reads the phrase out of FLATTENED text
# and two of the homes sit across a line break.
#
# Attribution is by the OTHER FILE: the phrase is asserted to survive there, so
# a kill cannot be borrowed from the sibling entry. The authority's held
# neighbours are asserted intact as well, so a kill cannot be borrowed from the
# definition, the exclusions or the no-round form.
run_mutant "the fan-out sizing rule blurred in fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join(['one', 'reviewer', 'per', 'file', 'cluster']), re.I)
assert len(a.findall(s))>=1, 'mutant is a no-op: fix-loop.md no longer states the sizing rule in these words'
out=a.sub('reviewers as the round sees fit', s)
assert out!=s, 'mutant is a no-op: the sizing phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'the number of blocking f-ids this fix-mode run targeted' in flat(out), 'mutant is a no-op: the definition went too, so a kill would not be attributable to the sizing rule'
assert 'is not counted in '+bt+'M'+bt in out, 'mutant is a no-op: the M-exclusion phrase went too, so a kill would not be attributable to the sizing rule'
assert 'm=0 → no round' in flat(out), 'mutant is a no-op: the no-round form went too, so a kill would not be attributable to the sizing rule'
assert len(a.findall(o.read_text()))>=1, 'mutant is a no-op: SKILL.md lost the phrase too, so a kill would not be attributable to the fix-loop.md copy'
p.write_text(out)\""
run_mutant "the fan-out sizing rule blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
o=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join(['one', 'reviewer', 'per', 'file', 'cluster']), re.I)
assert len(a.findall(s))>=1, 'mutant is a no-op: SKILL.md no longer states the sizing rule in these words'
out=a.sub('reviewers as the round sees fit', s)
assert out!=s, 'mutant is a no-op: the sizing phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'm=0 → no round' in flat(out), 'mutant is a no-op: the no-round form went too, so a kill would not be attributable to the sizing rule'
assert 'is the only declaration that licenses it' in flat(out), 'mutant is a no-op: the M=0 licence rule went too, so a kill would not be attributable to the sizing rule'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: the Rule 5b prohibition went too, so a kill would not be attributable to the sizing rule'
assert len(a.findall(o.read_text()))>=1, 'mutant is a no-op: fix-loop.md lost the phrase too, so a kill would not be attributable to the SKILL.md copy'
p.write_text(out)\""

# --- the `M=0` licence rule, held by a phrase the worked example cannot carry ---
# `m=0 → no round` occurs in `SKILL.md` in the rule prose and again inside the
# fence. So the rule prose could be deleted with the fence left standing, and
# the gate stayed green (measured). This
# mutant reproduces that: it deletes every paragraph carrying the licence
# sentence and ASSERTS THE FENCE SURVIVES, which is what makes the kill
# attributable to the new entry rather than to the `M=0 → no round` one.
# Paragraph-scoped and whitespace-normalised, so no line-break position is
# pinned; a full reword refuses loudly instead of passing as a no-op.
run_mutant "the M=0 licence rule deleted from SKILL.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); nl=chr(10)
flat=lambda x: ' '.join(x.split()).lower()
key='is the only declaration that licenses it'
assert key in flat(s), 'mutant is a no-op: SKILL.md no longer carries the M=0 licence rule'
paras=s.split(nl+nl)
keep=[x for x in paras if key not in flat(x)]
assert len(keep)<len(paras), 'mutant is a no-op: no SKILL.md paragraph carries the licence rule'
out=(nl+nl).join(keep)
assert key not in flat(out), 'mutant is a no-op: the licence rule survives the paragraph deletion'
assert 'm=0 → no round' in flat(out), 'mutant is a no-op: the fenced no-round example went too, so a kill would not be attributable to the licence rule'
p.write_text(out)\""

# --- `M` is defined once, and no shorter gloss of it survives ---
# `SKILL.md` asserts that `M` "is defined **once**" in the authority, and warns
# that a second copy "can drift into being a shorter one". Nothing held that: a
# gloss that dropped every exclusion sat 18 lines above the warning in
# `SKILL.md` and again inside the authority itself, both gates green, reading
# `M=1` on a deletion-only iteration — a round mandated over an empty diff. The
# two mutants below are the two halves of the pin that now holds it, kept apart
# for attribution: the first reintroduces the exact gloss that shipped, the
# second duplicates the definition verbatim.
#
# The duplicate carries `leaves no ownable commit` deliberately. That is what
# the gloss half tests for, so a duplicate that includes it can only be caught
# by the uniqueness half — the kill is attributable, and the mutant proves the
# claim is "defined ONCE" rather than merely "not glossed".
run_mutant "short \`M\` gloss reintroduced into SKILL.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
q=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
g=bt+'M'+bt+' records the count of targeted F-IDs for the convergence check.'
a='The fan-out is **one reviewer per file cluster in the fix diff**'
assert s.count(a)==1, 'mutant is a no-op: the re-review fan-out sentence is absent, reworded or duplicated'
assert g not in s, 'mutant is a no-op: the gloss is already there, so the tree was broken before the mutation'
out=s.replace(a, g+' '+a)
assert g in out, 'mutant is a no-op: the gloss was not inserted'
assert 'the number of blocking F-IDs this fix-mode run targeted' in q.read_text(), 'mutant is a no-op: the authority lost the definition too, so a kill would not be attributable to the gloss'
p.write_text(out)\""
run_mutant "M's definition duplicated into a second file" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
q=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); nl=chr(10); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
d=bt+'M'+bt+' is **the number of blocking F-IDs this fix-mode run targeted**, less every one the ledger closed by a route that leaves no ownable commit.'
key='the number of blocking f-ids this fix-mode run targeted'
assert flat(s).count(key)==0, 'mutant is a no-op: run-state.md already carries the definition, so the tree was broken before the mutation'
assert flat(q.read_text()).count(key)==1, 'mutant is a no-op: the authority does not hold exactly one definition, so a second copy proves nothing'
out=s.rstrip(nl)+nl+nl+d+nl
assert flat(out).count(key)==1, 'mutant is a no-op: the copy did not land'
assert 'leaves no ownable commit' in d, 'mutant is a no-op: the copy drops the exclusion, so the gloss arm could kill it instead of the uniqueness arm'
p.write_text(out)\""

# --- the no-round record is the one round that closes with no reviewer evidence ---
# It had no gate coverage at all, and both contradictions below PASSED when
# injected: a record declaring the form while ALSO listing `reports` and
# `coverage`, and one naming no closure route — which the prose itself calls "a
# skipped review wearing this form". Those two injections are kept here.
#
# Both work on fix-loop.md's worked round, and both assert their anchor is
# present exactly once before and that the replacement landed, so a reflow or a
# reword refuses loudly rather than passing as a silent no-op. Both also assert
# the DECLARATION survives the mutation: without that, a kill could come from
# the CLAIM_EFFECT arm missing a phrase rather than from the no-round arm
# rejecting a contradictory record, and the mutant would prove the wrong thing.
run_mutant "no-round round declares a reports field" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); mid=chr(183)
a=' '+mid+' closures: F-018 deleted,'
assert s.count(a)==1, 'mutant is a no-op: the no-round worked round is absent, reworded or duplicated'
out=s.replace(a, ' '+mid+' reports p3-rr3-a.md '+mid+' coverage p3-rr3-coverage.md'+a)
assert out!=s, 'mutant is a no-op: the reviewer fields were not inserted'
assert 'M=0 \u2192 no round' in out, 'mutant is a no-op: the declaration itself went, so a kill would not be attributable to the reviewer fields'
p.write_text(out)\""
run_mutant "no-round round names no closure route" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96)
a='closures: F-018 deleted,'
b='F-019 user-ruled false positive'
assert s.count(a)==1 and s.count(b)==1, 'mutant is a no-op: the worked round no longer names its two routes in the form this strips'
out=s.replace(a, 'closures: F-018,').replace(b, 'F-019')
assert out!=s, 'mutant is a no-op: the routes were not stripped'
assert 'M=0 \u2192 no round' in out, 'mutant is a no-op: the declaration itself went, so a kill would not be attributable to the missing routes'
assert '\u2192 no findings' in out, 'mutant is a no-op: the outcome slot went too, so a kill would not be attributable to the missing routes'
p.write_text(out)\""

# A pin is NOT a no-round route: it commits a test, so it stays in `M`, and an
# iteration that produced one is owed a round over that commit. Before the rule
# was stated this way a pin could be named inside an `M=0 → no round` record and
# the gate agreed, which is how a test commit could close a claim with no
# reviewer ever reading it. This injects exactly that record.
#
# It keeps the record's OTHER route (`F-018 deleted`) intact on purpose: with a
# legal route still present the "names no closure route" branch cannot fire, so
# a kill here is attributable to the pinned-route rejection and to nothing else.
# Asserts its anchor is present exactly once before, that the swap landed, and
# that the declaration and the outcome slot both survive.
run_mutant "no-round round names a pinned route" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96)
a='F-019 user-ruled false positive'
assert s.count(a)==1, 'mutant is a no-op: the worked no-round round no longer names a user-ruled false positive route'
out=s.replace(a, 'F-019 pinned by '+bt+'tests/test_x.py::test_claim'+bt)
assert out!=s, 'mutant is a no-op: the pinned route was not injected'
assert 'M=0 → no round' in out, 'mutant is a no-op: the declaration itself went, so a kill would not be attributable to the pinned route'
assert 'closures: F-018 deleted,' in out, 'mutant is a no-op: the legal route went too, so a kill could come from the missing-route branch instead'
assert '→ no findings' in out, 'mutant is a no-op: the outcome slot went too'
p.write_text(out)\""

# --- the dispatch contract's three requirements must each stay held ---
# Rule 5b (derive, don't restate), the `kit.md` citation and the ticket/issue
# key are one contract in `references/run-state.md`, and each has a second end
# in `SKILL.md` — the Law that states Rule 5b, the GATE 2 step that writes
# `kit.md`, the Stage 1 round that asks the key. Every one of those was
# deletable on a green build before the DISPATCH_CONTRACT arm.
#
# ONE SURGICAL MUTANT PER (PHRASE, FILE). Every phrase held in
# `references/run-state.md` sits in the SAME paragraph there, so a paragraph
# deletion fires several arms at once and is attributable to none — the defect that split the
# `M`-exclusion bullet's mutants in two. Each mutant below blurs its own phrase
# and asserts that every sibling phrase, in this file and in the other, came
# through untouched, so the kill belongs to the arm whose name it bears.
#
# Every phrase is matched with `\s+` between its words, never as a literal: the
# gate reads them out of FLATTENED text, so any of them may sit across a line
# break in the source — several do — and a literal match would be a silent
# no-op rather than a mutation. Each asserts its anchor was present exactly
# once before and that the blur landed. Backticks are built with chr(96): a
# literal one inside these double-quoted shell arguments would be command
# substitution, and no assertion message may contain an apostrophe, which would
# close the single-quoted Python string it sits in.
run_mutant "Rule 5b's prohibition blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
o=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
s=p.read_text(); bt=chr(96); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
F1='never a count, a line number, a signature or a file list'
F2='refuses the brief and says which fact'
F3=bt+'kit.md'+bt+', cited by path'
F4='the prompt states it, the implementer puts it in the subject'
F5='written once, here, from the approved plan'
F6='the ticket/issue key required in a commit subject'
a=re.compile(ws.join(['never', 'a', 'count,', 'a', 'line', 'number,', 'a', 'signature', 'or', 'a', 'file', 'list']))
assert len(a.findall(s))==1, 'mutant is a no-op: the Rule 5b prohibition is absent, reworded or duplicated in SKILL.md'
out=a.sub('and states its source instead', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert F5 in flat(out), 'mutant is a no-op: [' + F5 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F6 in flat(out), 'mutant is a no-op: [' + F6 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F1 in flat(o.read_text()), 'mutant is a no-op: [' + F1 + '] went too in the other file, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""
run_mutant "Rule 5b's prohibition blurred in run-state.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
F1='never a count, a line number, a signature or a file list'
F2='refuses the brief and says which fact'
F3=bt+'kit.md'+bt+', cited by path'
F4='the prompt states it, the implementer puts it in the subject'
F5='written once, here, from the approved plan'
F6='the ticket/issue key required in a commit subject'
a=re.compile(ws.join(['never', 'a', 'count,', 'a', 'line', 'number,', 'a', 'signature', 'or', 'a', 'file', 'list']))
assert len(a.findall(s))==1, 'mutant is a no-op: the dispatch contract no longer carries the prohibition exactly once'
out=a.sub('and states its source instead', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert F2 in flat(out), 'mutant is a no-op: [' + F2 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F3 in flat(out), 'mutant is a no-op: [' + F3 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F4 in flat(out), 'mutant is a no-op: [' + F4 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F1 in flat(o.read_text()), 'mutant is a no-op: [' + F1 + '] went too in the other file, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""
run_mutant "the brief-refusal duty blurred in run-state.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
F1='never a count, a line number, a signature or a file list'
F2='refuses the brief and says which fact'
F3=bt+'kit.md'+bt+', cited by path'
F4='the prompt states it, the implementer puts it in the subject'
F5='written once, here, from the approved plan'
F6='the ticket/issue key required in a commit subject'
a=re.compile(ws.join(['refuses', 'the', 'brief', 'and', 'says', 'which', 'fact']))
assert len(a.findall(s))==1, 'mutant is a no-op: the refusal duty is absent, reworded or duplicated'
out=a.sub('takes the brief as it stands', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert F1 in flat(out), 'mutant is a no-op: [' + F1 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F3 in flat(out), 'mutant is a no-op: [' + F3 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F4 in flat(out), 'mutant is a no-op: [' + F4 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F1 in flat(o.read_text()), 'mutant is a no-op: [' + F1 + '] went too in the other file, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""
run_mutant "the kit.md citation blurred in run-state.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
F1='never a count, a line number, a signature or a file list'
F2='refuses the brief and says which fact'
F3=bt+'kit.md'+bt+', cited by path'
F4='the prompt states it, the implementer puts it in the subject'
F5='written once, here, from the approved plan'
F6='the ticket/issue key required in a commit subject'
a=re.compile(ws.join(['cited', 'by', 'path']))
assert len(a.findall(s))==1, 'mutant is a no-op: the kit citation is absent, reworded or duplicated'
out=a.sub('described in the prompt', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert F1 in flat(out), 'mutant is a no-op: [' + F1 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F2 in flat(out), 'mutant is a no-op: [' + F2 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F4 in flat(out), 'mutant is a no-op: [' + F4 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F5 in flat(o.read_text()), 'mutant is a no-op: [' + F5 + '] went too in the other file, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""
run_mutant "kit.md's GATE 2 writing point blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
o=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
s=p.read_text(); bt=chr(96); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
F1='never a count, a line number, a signature or a file list'
F2='refuses the brief and says which fact'
F3=bt+'kit.md'+bt+', cited by path'
F4='the prompt states it, the implementer puts it in the subject'
F5='written once, here, from the approved plan'
F6='the ticket/issue key required in a commit subject'
a=re.compile(ws.join(['written', 'once,', 'here,', 'from', 'the', 'approved', 'plan']))
assert len(a.findall(s))==1, 'mutant is a no-op: the GATE 2 writing point is absent, reworded or duplicated'
out=a.sub('put together whenever a task first needs it', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert F1 in flat(out), 'mutant is a no-op: [' + F1 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F6 in flat(out), 'mutant is a no-op: [' + F6 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F3 in flat(o.read_text()), 'mutant is a no-op: [' + F3 + '] went too in the other file, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""
run_mutant "the ticket-key question blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
o=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
s=p.read_text(); bt=chr(96); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
F1='never a count, a line number, a signature or a file list'
F2='refuses the brief and says which fact'
F3=bt+'kit.md'+bt+', cited by path'
F4='the prompt states it, the implementer puts it in the subject'
F5='written once, here, from the approved plan'
F6='the ticket/issue key required in a commit subject'
a=re.compile(ws.join(['the', 'ticket/issue', 'key', 'required', 'in', 'a', 'commit', 'subject']))
assert len(a.findall(s))==1, 'mutant is a no-op: the Stage 1 ticket-key question is absent, reworded or duplicated'
out=a.sub('the conventions of the repo', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert F1 in flat(out), 'mutant is a no-op: [' + F1 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F5 in flat(out), 'mutant is a no-op: [' + F5 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F4 in flat(o.read_text()), 'mutant is a no-op: [' + F4 + '] went too in the other file, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""
run_mutant "the ticket key's dispatch field blurred in run-state.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
F1='never a count, a line number, a signature or a file list'
F2='refuses the brief and says which fact'
F3=bt+'kit.md'+bt+', cited by path'
F4='the prompt states it, the implementer puts it in the subject'
F5='written once, here, from the approved plan'
F6='the ticket/issue key required in a commit subject'
a=re.compile(ws.join(['the', 'prompt', 'states', 'it,', 'the', 'implementer', 'puts', 'it', 'in', 'the', 'subject']))
assert len(a.findall(s))==1, 'mutant is a no-op: the dispatch field is absent, reworded or duplicated'
out=a.sub('the implementer works it out', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert F1 in flat(out), 'mutant is a no-op: [' + F1 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F2 in flat(out), 'mutant is a no-op: [' + F2 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F3 in flat(out), 'mutant is a no-op: [' + F3 + '] went too in the same file, so a kill would not be attributable to the phrase this mutant names'
assert F6 in flat(o.read_text()), 'mutant is a no-op: [' + F6 + '] went too in the other file, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""

# --- and the skill may not count its own templates again ---
# The counts this arm replaced were true when written and false the moment
# `templates/kit.md` landed. Nothing read that directory's cardinality, so they
# would have stayed wrong on a green build. This mutant puts one back, in the
# exact sentence that carried it. It asserts the count is NOT already present
# (or the tree was broken before the mutation), that the insertion landed, and
# that the dispatch-contract phrases in the same file are untouched, so the kill
# belongs to the template-count arm and cannot be borrowed from a neighbour.
run_mutant "template count reintroduced into SKILL.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
a=bt+'templates/'+bt+' holds the run-state file templates.'
g=bt+'templates/'+bt+' holds the three run-state file templates.'
assert s.count(a)==1, 'mutant is a no-op: the sentence that named the directory is absent, reworded or duplicated'
assert g not in s, 'mutant is a no-op: the count is already there, so the tree was broken before the mutation'
out=s.replace(a, g)
assert g in out, 'mutant is a no-op: the count was not reintroduced'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: the Rule 5b prohibition went too, so a kill would not be attributable to the template count'
assert 'written once, here, from the approved plan' in flat(out), 'mutant is a no-op: the GATE 2 writing point went too, so a kill would not be attributable to the template count'
p.write_text(out)\""

# --- and a file the run-directory tree names must still ship a template ---
# `references/run-state.md` draws the run directory and says a template ships
# for each of its files. Nothing held that: removing `templates/kit.md` — the
# file that arrival added — left the gate green and the sentence false. This
# mutant removes it again.
#
# Asserted at both ends, and the tree is asserted to still NAME the file: with
# the name gone the arm has nothing to look up, the deletion is legitimate, and
# a kill would mean something else. The other templates are asserted present,
# so the kill is attributable to this one file rather than to a directory that
# emptied.
run_mutant "a run-state file the tree names loses its template" '
d=plugins/superb/skills/pipeline/templates
f=$d/kit.md
if [ ! -f "$f" ]; then
  echo "mutant is a no-op: templates/kit.md is already absent, so the tree was broken before the mutation"
else
  grep -qF "kit.md" plugins/superb/skills/pipeline/references/run-state.md ||
    echo "mutant is a no-op: run-state.md no longer names kit.md, so the arm has nothing to look up and a kill would not be attributable to the missing template"
  rm -f "$f"
  [ ! -e "$f" ] || echo "mutant is a no-op: the template was not removed"
  for o in progress.md register.md findings.md; do
    [ -f "$d/$o" ] || echo "mutant is a no-op: $o went too, so a kill would not be attributable to kit.md"
  done
fi'

# check-plugin.py cites its mutants BY NAME, and nothing kept those names true
# until the citation check was added. The real-world failure is a rename in this
# file, so that is what this mutant does: it renames a cited mutant and leaves
# the citation pointing at a name that no longer exists. The gate must notice.
# Guarded both ways — if the old name is not here the mutation is a no-op and
# says so, and the rename is verified to have landed.
run_mutant "cited mutant renamed out from under its citation" '
f=tools/check-plugin-mutants.sh
old="run_mutant \"cited predicate file unreadable\""
new="run_mutant \"cited predicate file cannot be read\""
if grep -qF "$old" "$f"; then
  sed -i "s|$old|$new|" "$f"
  grep -qF "$new" "$f" || echo "mutant is a no-op: the rename did not apply, so no citation was orphaned"
else
  echo "mutant is a no-op: this harness no longer defines the mutant whose name the gate cites, so the citation under test is not the one renamed"
fi'

echo
echo "killed=$PASS survived=$SURV"
if [ "$SURV" -ne 0 ]; then
  printf 'survivors:\n'; printf '  - %s\n' "${SURVIVORS[@]}"
  echo "check-plugin-mutants: FAIL"; exit 1
fi
echo "check-plugin-mutants: PASS"
