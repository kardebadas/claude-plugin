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
# `grep` here may be ugrep, which parses a PATTERN BEGINNING WITH `-` as an
# option and exits with a usage error — so `grep -qF "- [x] RV ..."` reports no
# match rather than searching, and the mutant guarding on it silently reports
# itself a no-op (measured: "run tracker advances past a phase with an open RV"
# survived that way). Any pattern that can start with a dash takes `--` before
# it, or anchors with `^-` as a regex instead of a fixed string.
run_mutant() { # name, shell applied inside the copy
  local name="$1" script="$2" dir="$WORK/m" out
  rm -rf "$dir"; mkdir -p "$dir"
  tar -C "$SRC" --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$dir" -xf -
  out="$( ( cd "$dir" && eval "$script" ) 2>&1 )"
  if ( cd "$dir" && ./tools/check-plugin.sh ) >/dev/null 2>&1; then
    printf '  SURVIVED  %s\n' "$name"; SURV=$((SURV+1)); SURVIVORS+=("$name")
    if [ -n "$out" ]; then printf '%s\n' "$out" | sed 's/^/            | /'; fi
  elif printf '%s' "$out" | grep -q "mutant is a no-op"; then
    # KILLED, BUT BY SOMETHING OTHER THAN ITSELF. A mutant whose own guard
    # reported a no-op did not apply the mutation it is named for, so the kill
    # says nothing about the arm this mutant exists to prove — and reporting it
    # as `killed` hides a rotted anchor behind a green harness. Discarding this
    # output on the kill path is how three anchors in one branch went stale
    # while every run read PASS.
    printf '  NO-OP     %s\n' "$name"; NOOP=$((NOOP+1)); NOOPS+=("$name")
    printf '%s\n' "$out" | sed 's/^/            | /'
  else
    printf '  killed    %s\n' "$name"; PASS=$((PASS+1))
  fi
}

NOOP=0; NOOPS=()
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
#
# ENUMERATED FROM THE TREE, never from a list kept here by hand. A hard-coded
# set drifts the moment a fixture is added: the new fixture's conformance goes
# unchecked in this baseline while `check-plugin.py`'s own arm requires CI to
# lint it, so the two enumerations disagree and each looks complete on its own.
# A directory holding a `progress.md` IS a fixture run directory -- the same
# predicate that arm uses.
mapfile -t RUNFX < <(cd "$D" && for d in tools/fixtures/*/; do
  [ -f "$d/progress.md" ] && printf '%s\n' "${d%/}"
done)
if [ "${#RUNFX[@]}" -eq 0 ]; then
  echo "  FAIL  no fixture run directory found under tools/fixtures/ -- every run-mode mutant below would be a no-op"
  exit 1
fi
echo "  run fixtures: ${RUNFX[*]}"
for fx in "${RUNFX[@]}"; do
  if ( cd "$D" && ./tools/check-plugin.sh --run "$fx" ) >/dev/null 2>&1; then
    echo "  ok    clean copy passes with --run over $fx"
  else
    echo "  FAIL  $fx does not conform on a clean copy — every run-mode mutant over it would then kill for that reason instead of its own"
    ( cd "$D" && ./tools/check-plugin.sh --run "$fx" ) | grep FAIL
    exit 1
  fi
done

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
if [ "$(grep -cF -- "check-plugin.sh --run " "$f")" -lt 1 ]; then
  echo "mutant is a no-op: checks.yml no longer runs the gate in run mode at all, so there is no step to delete"
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
# `C` MOVES WITH `s`. The round now declares its cluster count, and an
# over-declaration that left `C=1` standing against `3 slice` would be killed by
# the cluster-count arm as well — a kill this mutant's name does not claim. So
# the replacement writes `C=3`, keeping the two numbers consistent, and the only
# arm that can fire is the one comparing the declared count against the one
# report file the round lists.
run_mutant "re-review round over-declares reviewers" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md'); s=p.read_text()
a='M=9 C=1 \u2192 1 slice + 0 integration'
assert s.count(a)==1, 'mutant is a no-op: the re-review round example is absent, reworded, or duplicated'
out=s.replace(a, 'M=9 C=3 \u2192 3 slice + 1 integration')
assert out!=s, 'mutant is a no-op: the over-declaration did not apply'
p.write_text(out)\""
run_mutant "every worked RV example deleted"       "sed -i '/· reports/d' plugins/superb/skills/pipeline/*.md plugins/superb/skills/pipeline/*/*.md"
# --- an `M=` round declares its cluster count, and `s` equals it ---
# `C=<n>` is the cluster count the re-review fan-out is sized by, written on the
# round beside `M`. TWO MUTANTS, because the arm makes two separable statements
# and each has its own failure mode: the field can be ABSENT, leaving `s` with
# nothing on the line to be checked against, or PRESENT AND CONTRADICTED, which
# is the arithmetic slip — three clusters counted, four reviewers dispatched.
# Holding them apart is what makes each kill attributable.
#
# Neither mutant touches the `reports` field or the counts the reviewer-count
# arm reads, and both assert as much, so a kill cannot be borrowed from it.
# What NEITHER can prove, because no gate can: that `C` is the right number.
# `C` is written by whoever chose `s`; the over-fan-out this branch's own
# fixture encoded is caught by the coverage-table arm, over recorded ranges,
# and not here.
run_mutant "re-review round loses its cluster count" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md'); s=p.read_text()
a='M=9 C=1 \u2192 1 slice + 0 integration'
assert s.count(a)==1, 'mutant is a no-op: the re-review round example no longer declares M=9 C=1 over one slice exactly once'
out=s.replace(a, 'M=9 \u2192 1 slice + 0 integration')
assert 'M=9 C=' not in out, 'mutant is a no-op: the cluster count was not removed'
assert '1 slice + 0 integration \u00b7 fixplan p3-fixplan-r2.md' in out, 'mutant is a no-op: it took the declared counts or the fixplan field too, so a kill could come from the reviewer-count or fix-plan arm instead'
p.write_text(out)\""
run_mutant "re-review round's cluster count disagrees with its slice count" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md'); s=p.read_text()
a='M=9 C=1 \u2192 1 slice + 0 integration'
assert s.count(a)==1, 'mutant is a no-op: the re-review round example no longer declares M=9 C=1 over one slice exactly once'
out=s.replace(a, 'M=9 C=2 \u2192 1 slice + 0 integration')
assert 'M=9 C=2 \u2192 1 slice + 0 integration \u00b7 fixplan p3-fixplan-r2.md' in out, 'mutant is a no-op: the disagreement did not apply, or it moved the slice count with it'
p.write_text(out)\""

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
enable_run_dir() { # inside the copy: make the wrapper pass --run <dir>
  local d="$1" f=tools/check-plugin.sh a='check-plugin.py" "$@"'
  if ! grep -qF "$a" "$f"; then
    echo "mutant is a no-op: the wrapper no longer invokes check-plugin.py with forwarded arguments, so --run cannot be reached"
    return 1
  fi
  sed -i "s|check-plugin.py\" \"\$@\"|check-plugin.py\" --run $d \"\$@\"|" "$f"
  if ! grep -qF -- "--run $d" "$f"; then
    echo "mutant is a no-op: --run was not injected into the wrapper, so the run mode was never entered"
    return 1
  fi
}
enable_run() { enable_run_dir tools/fixtures/run-ok; }
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
# THE DECLARATION IS LEFT ALONE AND THE LIST IS SHORTENED, which is a change
# from how this mutant used to over-declare. It raised Phase 1 from
# `1 slice + 0 integration` to `3 slice + 1 integration`, and once the two
# arithmetic arms landed that record broke two rules at once — `ceil(1/5)` is 1,
# so the sizing arm fires as well — and a kill by two arms is attributable to
# neither. Shrinking the brace set instead leaves every declared number
# conforming and only the reviewer COUNT disagreeing, which is what this mutant
# is named for. `p2-review-b.md` stays in `agent-output/` and keeps its coverage
# row, so no existence arm and no coverage-table arm can fire either: the round
# simply stops naming it.
# Anchored on ASCII, never on the arrow: the arrow is a multi-byte character an
# editor can re-encode, and a sed that matches nothing is a mutant that proves
# nothing. Both ends asserted.
run_mutant "run tracker over-declares reviewers" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -cF "reports p2-review-{a,b,int}.md" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer names the brace set p2-review-{a,b,int}.md exactly once"
else
  sed -i "s|reports p2-review-{a,b,int}.md|reports p2-review-{a,int}.md|" "$f"
  grep -qF "reports p2-review-{a,int}.md" "$f" || echo "mutant is a no-op: the report list was not shortened"
  grep -qF "N=8" "$f" || echo "mutant is a no-op: the task count went with the list, so a kill could come from the sizing arm instead"
  grep -qF "2 slice + 1 integration" "$f" || echo "mutant is a no-op: the declared counts moved with the list, so a kill could come from a sizing arm instead"
  [ -f tools/fixtures/run-ok/agent-output/p2-review-b.md ] || echo "mutant is a no-op: the dropped report file went too, so a kill could come from the report-existence arm instead"
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
# was reported as missing one. The fixture's Phase 3 is such a round — its
# `scope` and `note` prose push both fields well past any 400-character
# window — and the harness's own baseline `--run`
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
key=\"reports p3-review-{a,b,int}.md\"
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
if [ "$(grep -c "\[x\] RV" "$f")" != 4 ]; then
  echo "mutant is a no-op: the fixture no longer holds exactly four closed RV records"
else
  sed -i "/\[x\] RV/d" "$f"
  sed -i "/→ round /d" "$f"
  grep -q "\[x\] RV" "$f" && echo "mutant is a no-op: the closed records were not removed"
  grep -q "→ round " "$f" && echo "mutant is a no-op: an appended round survived, and a round record is itself a closed round the linter counts"
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

# --- THE COVERAGE TABLE'S RANGES: the over-wide fan-out the prose forbids ---
# The skill forbids two reviewers over one cluster in two places, and until now
# both gates passed a fixture that did it: Phase 3 declared three slice
# reviewers plus an integration reviewer over one commit, all four coverage rows
# carrying one byte-identical range. The four mutants below hold the arm that
# reads those ranges. Phase 3 has since been resized to `ceil(N/5)` — two
# slices, three distinct ranges — which is the smallest shape that still
# exercises distinctness on the happy path.
#
# All four work on Phase 3, whose round declares `2 slice + 1 integration` —
# the arm is scoped to `s >= 2`, so Phase 1's single-slice round cannot
# exercise it. NONE of them touches the tracker's `reports` field or its
# declared counts: three edit only the coverage file, and the fourth asserts
# that the round still names the report whose row it removed and that the
# report file itself is still there. So no kill here can be borrowed from the
# reviewer-count, report-existence or coverage-existence arms.
run_mutant "run tracker's coverage table repeats a slice range" '
enable_run || exit 0
'"$J"' "import pathlib
p=pathlib.Path(\"tools/fixtures/run-ok/agent-output/p3-coverage.md\")
s=p.read_text()
a=\"| p3-review-a.md | ccccccc^..ccccccc |\"
b=\"| p3-review-b.md | c0c0c0c^..c0c0c0c |\"
assert s.count(a)==1 and s.count(b)==1, \"mutant is a no-op: the two slice rows are no longer written as the fixture wrote them\"
out=s.replace(b, \"| p3-review-b.md | ccccccc^..ccccccc |\")
assert out.count(\"ccccccc^..ccccccc |\")==2, \"mutant is a no-op: the duplicate range did not land\"
assert \"| p3-review-int.md | ccccccc^..c0c0c0c |\" in out, \"mutant is a no-op: it took the integration row too, so a kill would not be attributable to two SLICE reviewers sharing a range\"
p.write_text(out)"'
# The row LOOKUP, not the comparison: the report is still named on the round and
# its file is still in agent-output/, so neither existence arm can fire. What
# goes is the row that would have carried its range — and a table read as
# conforming for being incomplete is how a duplicate hides.
run_mutant "run tracker's coverage table loses a slice's row" '
enable_run || exit 0
'"$J"' "import pathlib
p=pathlib.Path(\"tools/fixtures/run-ok/agent-output/p3-coverage.md\")
t=pathlib.Path(\"tools/fixtures/run-ok/progress.md\")
s=p.read_text(); nl=chr(10)
row=\"| p3-review-b.md | c0c0c0c^..c0c0c0c |\"
assert s.count(row)==1, \"mutant is a no-op: the second slice no longer has the row the fixture gave it\"
out=nl.join([x for x in s.split(nl) if x.strip()!=row])
assert \"p3-review-b.md\" not in out, \"mutant is a no-op: the row was not removed\"
assert \"p3-review-{a,b,int}.md\" in t.read_text(), \"mutant is a no-op: the round no longer names that report, so its missing row is not a missing row\"
assert pathlib.Path(\"tools/fixtures/run-ok/agent-output/p3-review-b.md\").exists(), \"mutant is a no-op: the report file went too, so a kill could come from the report-existence arm instead\"
p.write_text(out)"'
# THE DECISION NOT TO EXCLUDE THE INTEGRATION ROW, held. Its range is the union
# of the slices, so on a conforming round it is distinct from each of them and
# excluding it would change nothing; collapse it onto a slice and the round
# bought two reads of one diff and no integration review at all. An arm that
# excluded the row by name, by position or by the `<i>` count would pass this.
run_mutant "run tracker's integration range collapses onto a slice's" '
enable_run || exit 0
'"$J"' "import pathlib
p=pathlib.Path(\"tools/fixtures/run-ok/agent-output/p3-coverage.md\")
s=p.read_text()
a=\"| p3-review-int.md | ccccccc^..c0c0c0c |\"
assert s.count(a)==1, \"mutant is a no-op: the integration row no longer spans the slices the way the fixture wrote it\"
out=s.replace(a, \"| p3-review-int.md | ccccccc^..ccccccc |\")
assert out.count(\"ccccccc^..ccccccc |\")==2, \"mutant is a no-op: the collapse did not land\"
assert \"| p3-review-a.md | ccccccc^..ccccccc |\" in out and \"| p3-review-b.md | c0c0c0c^..c0c0c0c |\" in out, \"mutant is a no-op: a slice row went too, so a kill could come from the slice-distinctness reading instead\"
p.write_text(out)"'
# An UNREADABLE coverage file must report itself as unreadable, and this mutant
# asserts the MESSAGE rather than the verdict, on the `cited predicate file
# unreadable` precedent. Exit status alone cannot hold this branch: delete it
# and an unreadable file reaches the row lookup with no rows, which reports
# every named report as missing its row — a red build for a reason the gate
# invented, on a file that may hold a perfectly good table. So the mutation
# greps the output for the named reason and, when it is absent, puts the file
# back — leaving a clean copy that PASSES, so the harness reports SURVIVED with
# its reason printed. The file still EXISTS throughout, so the
# coverage-existence arm cannot be what fires.
# The held copy lives under `$WORK`, so the EXIT trap reclaims it on interrupt.
run_mutant "run tracker's coverage file is unreadable" '
enable_run || exit 0
f=tools/fixtures/run-ok/agent-output/p3-coverage.md
k="$WORK/held-p3-coverage.md"
if [ ! -f "$f" ]; then
  echo "mutant is a no-op: the fixture has no p3-coverage.md to corrupt"
elif ! grep -qF "coverage p3-coverage.md" tools/fixtures/run-ok/progress.md; then
  echo "mutant is a no-op: no round names that coverage file, so nothing reads it"
else
  cp "$f" "$k"
  printf "\xff\xfe" >> "$f"
  o="$(./tools/check-plugin.sh 2>&1)"
  if printf "%s\n" "$o" | grep -qF "exists but cannot be read"; then
    rm -f "$k"
  else
    echo "mutant is a no-op: the gate did not name the unreadable coverage file and its reason — most likely it reported the rows as missing instead, which is a reason it invented — so the file was restored and this mutant reports SURVIVED"
    cp "$k" "$f"; rm -f "$k"
  fi
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
# ONE PHRASE, NOT THE PARAGRAPH IT SITS IN. These two used to delete every
# blank-line-delimited paragraph naming the term, and that was ILLUSORY
# COVERAGE. Measured at `326ccdc`: with the CLAIM_RULE arm neutralised and
# nothing else changed, BOTH were still killed — the fix-loop.md one by the
# re-tag predicate arm and by two CLAIM_EFFECT entries whose phrases live in
# the same paragraphs, the findings.md one by the re-tag predicate arm. A
# mutant whose kill does not depend on the arm it is cited under proves that
# arm is present, not that it is load-bearing.
#
# So each blurs exactly one held phrase — `a rewrite is not a closure`, the
# non-closure half of the rule — and asserts that every OTHER CLAIM_RULE phrase
# survives in the same file, so the reported absence is the phrase this mutant
# named. Matched with `\s+` between words rather than as a literal: the gate
# reads the phrase out of FLATTENED text, so it may sit across a line break in
# the source, and a literal match would have been a silent no-op.
#
# Attribution is by the OTHER FILE too: the phrase is asserted to survive
# there, so a kill cannot be borrowed from the sibling entry. Measured both
# ways, per file: arm present -> killed; CLAIM_RULE neutralised -> PASS, i.e.
# SURVIVED.
run_mutant "claim-finding closure rule deleted from fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
o=pathlib.Path('plugins/superb/skills/pipeline/templates/findings.md')
s=p.read_text(); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join(['rewrite', 'is', 'not', 'a', 'closure']), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: fix-loop.md states the non-closure in other words, or more than once'
out=a.sub('rewrite closes it like any other route', s)
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
for q in ('claim finding', 'deleting the claim', 'pinning it with a test', 'deleting the claim is a repository change'):
    assert q in flat(out), 'mutant is a no-op: '+q+' went too, so a kill would not be attributable to the non-closure phrase'
assert len(a.findall(o.read_text()))==1, 'mutant is a no-op: the sibling text lost the phrase too, so a kill would not be attributable to this copy'
p.write_text(out)\""
# The same deletion against the copy. Held separately: the authority and the copy
# are edited independently, so a kill on one says nothing about the other — and
# the copy is the one the template says gets copied into the run directory.
run_mutant "claim-finding closure rule deleted from findings.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/templates/findings.md')
o=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join(['rewrite', 'is', 'not', 'a', 'closure']), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: findings.md states the non-closure in other words, or more than once'
out=a.sub('rewrite closes it like any other route', s)
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
for q in ('claim finding', 'deleting the claim', 'pinning it with a test', 'deleting the claim is a repository change'):
    assert q in flat(out), 'mutant is a no-op: '+q+' went too, so a kill would not be attributable to the non-closure phrase'
assert len(a.findall(o.read_text()))==1, 'mutant is a no-op: the sibling text lost the phrase too, so a kill would not be attributable to this copy'
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
run_mutant "M-inclusion phrase blurred in fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile('IS'+chr(92)+'s+counted'+chr(92)+'s+in'+chr(92)+'s+'+bt+'M'+bt)
u=re.compile('every'+chr(92)+'s+commit'+chr(92)+'s+the'+chr(92)+'s+fix-mode'+chr(92)+'s+run'+chr(92)+'s+produced')
assert len(a.findall(s))==1, 'mutant is a no-op: the M-inclusion phrase is absent, reworded or duplicated'
out=a.sub('sits outside the round tally', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(u.findall(out))==1, 'mutant is a no-op: the coverage-union phrase went too, so a kill would not be attributable to the M-inclusion phrase'
assert 'the number of blocking F-IDs this fix-mode run targeted' in out, 'mutant is a no-op: the definition went too, so a kill would not be attributable to the M-exclusion phrase'
assert 'm=0 → no round' in flat(out), 'mutant is a no-op: the no-round form went too, so a kill would not be attributable to the M-exclusion phrase'
p.write_text(out)\""
run_mutant "coverage-union phrase blurred in fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96)
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile('IS'+chr(92)+'s+counted'+chr(92)+'s+in'+chr(92)+'s+'+bt+'M'+bt)
u=re.compile('every'+chr(92)+'s+commit'+chr(92)+'s+the'+chr(92)+'s+fix-mode'+chr(92)+'s+run'+chr(92)+'s+produced')
assert len(u.findall(s))==1, 'mutant is a no-op: the coverage-union phrase is absent, reworded or duplicated'
out=u.sub('the commits it chooses', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==1, 'mutant is a no-op: the M-inclusion phrase went too, so a kill would not be attributable to the coverage-union phrase'
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
assert 'counted in '+bt+'M'+bt in out, 'mutant is a no-op: it removed the M-inclusion bullet too, so a kill would not be attributable to the no-round form'
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
assert 'counted in '+bt+'M'+bt in out, 'mutant is a no-op: it removed the M-inclusion bullet too, so a kill would not be attributable to the definition paragraph'
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
assert 'excluded exactly when its closure route **changed nothing in the repository**' in flat(out), 'mutant is a no-op: the exclusion-route list went too, so a kill would not be attributable to the definition'
assert 'IS counted in '+bt+'M'+bt in out, 'mutant is a no-op: the M-inclusion phrase went too, so a kill would not be attributable to the definition'
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
a='**changed\n   nothing in the repository**'
assert s.count(a)==1, 'mutant is a no-op: the closed exclusion-route list is absent, reworded or duplicated'
out=s.replace(a, 'is a withdrawal')
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
assert 'IS counted in '+bt+'M'+bt in out, 'mutant is a no-op: the M-inclusion phrase went too, so a kill would not be attributable to the sizing rule'
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
a=' '+mid+' closures: F-018 user-ruled false positive,'
assert s.count(a)==1, 'mutant is a no-op: the no-round worked round is absent, reworded or duplicated'
out=s.replace(a, ' '+mid+' reports p3-rr3-a.md '+mid+' coverage p3-rr3-coverage.md'+a)
assert out!=s, 'mutant is a no-op: the reviewer fields were not inserted'
assert 'M=0 \u2192 no round' in out, 'mutant is a no-op: the declaration itself went, so a kill would not be attributable to the reviewer fields'
p.write_text(out)\""
run_mutant "no-round round names no closure route" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96)
a='closures: F-018 user-ruled false positive,'
b='F-019 withdrawn \u2192 duplicate of F-011'
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
a='F-019 withdrawn \u2192 duplicate of F-011'
assert s.count(a)==1, 'mutant is a no-op: the worked no-round round no longer names a withdrawal route'
out=s.replace(a, 'F-019 pinned by '+bt+'tests/test_x.py::test_claim'+bt)
assert out!=s, 'mutant is a no-op: the pinned route was not injected'
assert 'M=0 → no round' in out, 'mutant is a no-op: the declaration itself went, so a kill would not be attributable to the pinned route'
assert 'closures: F-018 user-ruled false positive,' in out, 'mutant is a no-op: the legal route went too, so a kill could come from the missing-route branch instead'
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

# --- Stage 5 runs the `--run` linter, and says in the hand-off what came back ---
# `--run` used to be invoked from CI over this repo's own fixture and nowhere
# else: no run pointed it at its own tracker, so the mode was documentation.
# Stage 5 now runs it, and the rule has two halves the arm holds separately —
# the DUTY (run it over the run's own directory) and the ABSENCE STATEMENT (say
# so when there is no checkout to run it from, because `tools/` is a sibling of
# `plugins/` and the linter does not ship with the plugin). One mutant per half,
# so a kill names which half went.
#
# The duty phrase has TWO HOMES in SKILL.md — the Stage 5 body and the hand-off
# list — and the arm reads flattened text, so a mutation leaving one standing is
# a no-op that would report `killed` for no reason. Both blurs use `\s+` between
# words for the same reason, and build the apostrophe with chr(39): a literal
# one would close the python string this shell argument carries.
# Each asserts the OTHER half survives, so neither kill can be borrowed.
run_mutant "Stage 5's linter duty blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); ws=chr(92)+'s+'; ap=chr(39)
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join(['over', 'this', 'run'+ap+'s', 'own', 'directory']), re.I)
assert len(a.findall(s))>=2, 'mutant is a no-op: Stage 5 no longer states the duty in these words in both its homes'
out=a.sub('somewhere sensible', s)
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'the linter was unavailable, so the tracker'+ap+'s review lines went unchecked' in flat(out), 'mutant is a no-op: the absence statement went too, so a kill would not be attributable to the duty'
assert 'check-plugin.sh --run' in out, 'mutant is a no-op: the command went too, so a kill would not be attributable to the duty phrase'
p.write_text(out)\""
run_mutant "Stage 5's linter-unavailable duty blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); ws=chr(92)+'s+'; ap=chr(39)
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join(['the', 'linter', 'was', 'unavailable,', 'so', 'the', 'tracker'+ap+'s', 'review', 'lines', 'went', 'unchecked']), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: Stage 5 no longer states the absence statement in these words exactly once'
out=a.sub('the run did what it could', s)
assert len(a.findall(out))==0, 'mutant is a no-op: the absence statement was not blurred'
assert flat(out).count('over this run'+ap+'s own directory')>=2, 'mutant is a no-op: the duty phrase went too, so a kill would not be attributable to the absence statement'
p.write_text(out)\""

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


# --- the rules the last two rounds added, each measured deletable on green ---
# Nine rule statements reached this branch stated in prose and held by nothing:
# the `C=<n>` rule in all three files that state it, the coverage table's
# distinctness rule in both, the fix diff's slice distinctness in both, the
# Invariant's reviewer-evidence exception, the
# coverage table's row grammar, and Rule 5b's one `Files:` exception at both
# ends. Every one was removed individually and `check-plugin.sh` reported PASS.
# Two of them are worse than unheld: the gate hard-FAILs an `M=` round with no
# `C` and a multi-slice round repeating a range, so deleting the prose left the
# linter red on a rule no document stated.
#
# ONE SURGICAL MUTANT PER (PHRASE, FILE), on the pattern the mutants above
# established: the phrase is matched with `\s+` between its words, since the
# gate reads it out of FLATTENED text and several of these sit across a line
# break, and a literal match would be a silent no-op. Each asserts its anchor
# was present exactly once before, that no occurrence survived the blur, that
# the OTHER held phrases in the same file came through, and — where the phrase
# has a second home — that the other file still carries it, so no kill can be
# borrowed from a sibling entry. Backticks are built with chr(96) and
# apostrophes with chr(39): a literal backtick inside these double-quoted shell
# arguments would be command substitution, and a literal apostrophe would close
# the single-quoted python string it sits in.
run_mutant "the re-review C rule blurred in fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['The', 'cluster', 'count', 'rides', 'the', 'round', 'as', bt+'C=<n>'+bt]]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('The cluster count is left off the round', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'the number of blocking f-ids this fix-mode run targeted' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'm=0 \u2192 no round' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'one reviewer per file cluster' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'no two slices carry the same range' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""
run_mutant "the C rule blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['cluster', 'count', 'is', 'recorded', 'on', 'the', 'round', 'as', bt+'C=<n>'+bt, 'and', bt+'s'+bt, 'must', 'equal', 'it']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('cluster count is a matter for whoever ran the round', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'is the only declaration that licenses it' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'one reviewer per file cluster' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'no two rows carry the same range' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
assert 'the cluster count rides the round as '+bt+'c=<n>'+bt in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "the C clause blurred in run-state.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['writes', 'its', 'cluster', 'count', 'on', 'the', 'line', 'as', bt+'C=<n>'+bt, 'and', bt+'s'+bt, 'must', 'equal', 'it']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('sizes itself from the fix diff and writes no count', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'refuses the brief and says which fact' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'm=0 \u2192 no round' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'no two rows carry the same range' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
assert 'cluster count is recorded on the round as '+bt+'c=<n>'+bt+' and '+bt+'s'+bt+' must equal it' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "the coverage-row distinctness rule blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['no', 'two', 'rows', 'carry', 'the', 'same', 'range']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('rows may repeat a range', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'is the only declaration that licenses it' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'one reviewer per file cluster' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'no two slices carry the same range' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
assert 'no two rows carry the same range' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "the coverage-row distinctness rule blurred in run-state.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['No', 'two', 'rows', 'carry', 'the', 'same', 'range']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('Rows may repeat a range', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'refuses the brief and says which fact' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'm=0 \u2192 no round' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
assert 'no two rows carry the same range' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "the slice distinctness rule blurred in fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['No', 'two', 'slices', 'carry', 'the', 'same', 'range']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('Slices may repeat a range', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'the number of blocking f-ids this fix-mode run targeted' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'm=0 \u2192 no round' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'one reviewer per file cluster' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'the cluster count rides the round as '+bt+'c=<n>'+bt in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
assert 'no two slices carry the same range' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "the slice distinctness rule blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['no', 'two', 'slices', 'carry', 'the', 'same', 'range']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('slices may repeat a range', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'is the only declaration that licenses it' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'one reviewer per file cluster' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'no two rows carry the same range' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
assert 'no two slices carry the same range' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "the Invariant's reviewer-evidence exception blurred in fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['The', 'round', 'forms', 'that', 'carry', 'no', 'reviewer', 'evidence', 'are', 'the', 'whole', 'of', 'the', 'exception']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('Some rounds carry no reviewer evidence', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'the number of blocking f-ids this fix-mode run targeted' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'm=0 \u2192 no round' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'one reviewer per file cluster' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""
run_mutant "the coverage-row grammar blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['keyed', 'by', 'its', 'report', 'filename,', 'with', 'that', 'reviewer'+ap+'s', 'exact', 'range', 'in', 'the', 'row'+ap+'s', 'second', 'cell,', 'and', 'every', 'report', 'file', 'the', 'round', 'names', 'has', 'a', 'row', 'of', 'its', 'own']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('laid out however the round likes', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'is the only declaration that licenses it' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'one reviewer per file cluster' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'no two rows carry the same range' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
assert 'keyed by its report filename, with that reviewer'+ap+'s exact range in the row'+ap+'s second cell, and every report file the round names has a row of its own' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "the coverage-row grammar blurred in run-state.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['keyed', 'by', 'its', 'report', 'filename,', 'with', 'that', 'reviewer'+ap+'s', 'exact', 'range', 'in', 'the', 'row'+ap+'s', 'second', 'cell,', 'and', 'every', 'report', 'file', 'the', 'round', 'names', 'has', 'a', 'row', 'of', 'its', 'own']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('laid out however the round likes', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'refuses the brief and says which fact' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'm=0 \u2192 no round' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'no two rows carry the same range' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
assert 'keyed by its report filename, with that reviewer'+ap+'s exact range in the row'+ap+'s second cell, and every report file the round names has a row of its own' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "Rule 5b's Files: exception blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['A', 'task'+ap+'s', bt+'Files:'+bt, 'block', 'is', 'the', 'exception,', 'at', 'both', 'ends']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('A task file list is treated like every other stated fact', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'is the only declaration that licenses it' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'one reviewer per file cluster' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
assert 'the task'+ap+'s own '+bt+'files:'+bt+' block being the one exception that rule names' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "Rule 5b's Files: exception blurred in run-state.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/run-state.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['the', 'task'+ap+'s', 'own', bt+'Files:'+bt, 'block', 'being', 'the', 'one', 'exception', 'that', 'rule', 'names']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('with no exception to it', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'refuses the brief and says which fact' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'm=0 \u2192 no round' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
assert 'a task'+ap+'s '+bt+'files:'+bt+' block is the exception, at both ends' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "the fan-out sizing rule blurred in README.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/README.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in ['one', 'reviewer', 'per', 'file', 'cluster']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('reviewers as the round sees fit', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
o=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
assert 'one reviewer per file cluster' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
o=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
assert 'one reviewer per file cluster' in flat(o.read_text()), 'mutant is a no-op: the other file that holds this rule lost it too, so a kill would not be attributable to the copy this mutant names'
p.write_text(out)\""
run_mutant "Stage 5's linter-FAIL rule blurred in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
s=p.read_text(); bt=chr(96); ap=chr(39); ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(x) for x in [bt+'FAIL'+bt, 'on', 'any', 'check', 'the', 'by-hand', 'pass', 'also', 'owes', 'is', 'that', 'pass', 'failing']]), re.I)
assert len(a.findall(s))==1, 'mutant is a no-op: the phrase this mutant names is absent, reworded or duplicated in that file'
out=a.sub('result is noted in the hand-off and nothing more', s)
assert out!=s, 'mutant is a no-op: the phrase was not blurred'
assert len(a.findall(out))==0, 'mutant is a no-op: an occurrence survived, and the arm reads flattened text, so the phrase is still present'
assert 'never a count, a line number, a signature or a file list' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'is the only declaration that licenses it' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'one reviewer per file cluster' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
assert 'over this run'+ap+'s own directory' in flat(out), 'mutant is a no-op: a sibling phrase held in the same file went too, so a kill would not be attributable to the phrase this mutant names'
p.write_text(out)\""

# --- the two arithmetic arms: ceil(N/5) for every N= round, and i after s ---
# The declared slice count went unchecked against `ceil(N/5)` in the one regime
# two documents call re-derivable from the line, and this repo's own conforming
# fixture broke it: `N=9 → 3 slice + 1 integration` passed both gates. So did
# `N=1 → 2 slice + 1 integration`, and `N=9 → 4 slice + 0 integration`, which
# also breaks the integration rule — `i` is 0 at one slice, and above one slice
# is 1 only with a named `boundary:` or 0 with `no integration boundary`
# declared, stated in `SKILL.md` and in `references/run-state.md` and encoded a
# third time in the fan-out table.
#
# Each mutant below changes ONLY the numbers its arm reads, and asserts that
# the reviewer count, the cluster count and the report list all still agree, so
# no kill can be borrowed from the count arms. The first two edit the fixture's
# Phase 2 round, identified by the line it sits on rather than by a literal
# that occurs in the fixture's prose as well; the third edits a worked example,
# because the fixture has no one-slice round that could gain an integration
# reviewer without also gaining a report file.
run_mutant "run tracker's N= round departs from ceil(N/5)" '
enable_run || exit 0
'"$J"' "import pathlib
p=pathlib.Path(\"tools/fixtures/run-ok/progress.md\")
L=p.read_text().split(chr(10))
i=[n for n,x in enumerate(L) if x.lstrip().startswith(\"- [x] RV\") and \"N=8\" in x]
assert len(i)==1, \"mutant is a no-op: the fixture no longer has exactly one closed round declaring N=8\"
assert \"2 slice + 1 integration\" in L[i[0]], \"mutant is a no-op: that round no longer declares 2 slice + 1 integration\"
L[i[0]]=L[i[0]].replace(\"N=8\", \"N=11\")
out=chr(10).join(L)
assert \"N=11\" in out, \"mutant is a no-op: the task count was not raised\"
assert \"2 slice + 1 integration\" in out, \"mutant is a no-op: the declared counts moved with it, so a kill could come from the integration arm instead\"
assert \"reports p2-review-{a,b,int}.md\" in out, \"mutant is a no-op: the reports field went too, so a kill could come from the reviewer-count arm instead\"
p.write_text(out)"'
# The integration reviewer is conditional now, so what must not survive is
# SILENCE about it in either direction: a reviewer with no boundary named, and a
# multi-slice round that neither has one nor says it does not need one. Phase 2
# is the fixture's round WITH a boundary, Phase 3 the round declaring none, so
# each mutant has exactly one target and its kill is attributable.
run_mutant "run tracker declares an integration reviewer with no boundary" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "boundary: the T2 contract" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture round no longer names its boundary exactly once"
else
  sed -i "/· boundary: the T2 contract consumed by the orchestrator commit in slice b/d" "$f"
  grep -q "boundary: the T2 contract" "$f" && echo "mutant is a no-op: the boundary is still named on that round"
  grep -qF "2 slice + 1 integration" "$f" || echo "mutant is a no-op: the integration reviewer went with the boundary, so a kill could come from another arm"
  grep -qF "reports p2-review-{a,b,int}.md" "$f" || echo "mutant is a no-op: the report set went too, so a kill could come from the file-count arm"
fi'
run_mutant "run tracker multi-slice round is silent about its integration reviewer" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "^      · no integration boundary$" "$f")" != 1 ]; then
  echo "mutant is a no-op: no round declares the absence of a boundary on a line of its own exactly once (the fixture prose mentions the phrase too, which is why this anchors on the bullet form)"
else
  sed -i "/^      · no integration boundary$/d" "$f"
  grep -q "^      · no integration boundary$" "$f" && echo "mutant is a no-op: the declaration is still present"
  grep -qF "2 slice + 0 integration" "$f" || echo "mutant is a no-op: the declared counts went with it, so a kill could come from a sizing arm"
fi'
# ATTRIBUTABLE, which took more than doubling the number: a round declaring
# `2 slice + 2 integration` while listing three report files is also caught by
# the reviewer-count arm, so the kill said nothing about the at-most-one rule.
# The mutation now grows the report list and the coverage table to match, which
# leaves exactly one arm able to object.
run_mutant "run tracker declares two integration reviewers" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
c=tools/fixtures/run-ok/agent-output/p2-coverage.md
if ! grep -qF "2 slice + 1 integration" "$f"; then
  echo "mutant is a no-op: no round declares 1 integration reviewer to double"
elif ! grep -qF "reports p2-review-{a,b,int}.md" "$f"; then
  echo "mutant is a no-op: Phase 2s report set is not the brace form this mutant grows"
else
  sed -i "0,/2 slice + 1 integration/s|2 slice + 1 integration|2 slice + 2 integration|" "$f"
  sed -i "s|reports p2-review-{a,b,int}.md|reports p2-review-{a,b,int,int2}.md|" "$f"
  printf "fixture reviewer report - phase 2 second integration slice\n" > tools/fixtures/run-ok/agent-output/p2-review-int2.md
  printf "| p2-review-int2.md | bbbbbbb^..b2b2b2b |\n" >> "$c"
  grep -qF "2 slice + 2 integration" "$f" || echo "mutant is a no-op: the count was not doubled"
  grep -qF "reports p2-review-{a,b,int,int2}.md" "$f" || echo "mutant is a no-op: the report list did not grow, so the reviewer-count arm would kill this instead"
  grep -q "boundary: the T2 contract" "$f" || echo "mutant is a no-op: the boundary went too, so a kill could come from the unnamed-boundary arm"
fi'
run_mutant "worked one-slice round adds an integration reviewer" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); mid=chr(183)
a='M=1 C=1 → 1 slice + 0 integration'
assert s.count(a)==1, 'mutant is a no-op: the worked pin round is absent, reworded or duplicated'
out=s.replace(a, 'M=1 C=1 → 1 slice + 1 integration')
out=out.replace(mid + ' reports p3-rr4-a.md', mid + ' reports p3-rr4-{a,b}.md')
assert out!=s, 'mutant is a no-op: the integration reviewer was not added'
assert 'M=1 C=1' in out, 'mutant is a no-op: the cluster count went too, so a kill could come from the cluster-count arm instead'
assert 'reports p3-rr4-{a,b}.md' in out, 'mutant is a no-op: the report list did not grow with the reviewer count, so a kill could come from the file-count arm instead'
p.write_text(out)\""


# Pipeline dispatches implementation itself now, so its brief extractor is a
# file this repo owns and can lose. Three ways it becomes useless at the first
# dispatch of a run, each killed by its own arm.
run_mutant "pipeline task-brief script is missing" '
f=plugins/superb/skills/pipeline/scripts/task-brief
if [ ! -f "$f" ]; then
  echo "mutant is a no-op: the script is already absent"
else
  rm -f "$f"
fi'
run_mutant "pipeline task-brief script is not executable" '
f=plugins/superb/skills/pipeline/scripts/task-brief
if [ ! -x "$f" ]; then
  echo "mutant is a no-op: the script is already non-executable"
else
  chmod -x "$f"
fi'
run_mutant "pipeline task-brief script loses its shebang" '
f=plugins/superb/skills/pipeline/scripts/task-brief
if ! head -1 "$f" | grep -q "^#!"; then
  echo "mutant is a no-op: the script has no shebang to remove"
else
  sed -i "1d" "$f"
  head -1 "$f" | grep -q "^#!" && echo "mutant is a no-op: a shebang is still on line 1"
fi'

# The four shapes the deleted task-level loop comes back in. Each re-introduces
# one sentence, which is exactly how it got in the first time. Anchors carry no
# backticks: the mutant script is eval'd, so a backtick inside a double-quoted
# sed pattern would command-substitute instead of matching.
run_mutant "pipeline delegates phase implementation to sdd" '
f=plugins/superb/skills/pipeline/references/fix-loop.md
if [ "$(grep -cF "wave by wave, per" "$f")" != 1 ]; then
  echo "mutant is a no-op: step 1 no longer points at implement.md exactly once"
else
  sed -i "s|wave by wave, per|wave by wave via subagent-driven-development, per|" "$f"
  grep -qF "wave by wave via subagent-driven-development" "$f" || echo "mutant is a no-op: the delegation was not re-introduced"
  grep -qF "Completing a task dispatches no reviewer" "$f" || echo "mutant is a no-op: the no-reviewer sentence went too, so a kill could come from another pattern"
fi'
run_mutant "pipeline asks for a per-task review" '
f=plugins/superb/skills/pipeline/references/parallel.md
if ! grep -qF "Dispatch no reviewer" "$f"; then
  echo "mutant is a no-op: the no-reviewer sentence is already gone"
else
  sed -i "s|Dispatch no reviewer|Run its per-task review|" "$f"
  grep -qF "Run its per-task review" "$f" || echo "mutant is a no-op: the per-task review sentence was not re-introduced"
  grep -qF "When every member has landed" "$f" || echo "mutant is a no-op: the landing-based merge gate went too, so a kill could come from the merge-gate pattern"
fi'
run_mutant "pipeline gates a merge on passing task review" '
f=plugins/superb/skills/pipeline/references/parallel.md
if ! grep -qF "When every member has landed" "$f"; then
  echo "mutant is a no-op: the landing-based merge gate is not phrased as expected"
else
  sed -i "s|When every member has landed|When every member has passed its task review|" "$f"
  grep -qF "passed its task review" "$f" || echo "mutant is a no-op: the task-review merge gate was not re-introduced"
  grep -qF "Dispatch no reviewer" "$f" || echo "mutant is a no-op: the no-reviewer sentence went too, so a kill could come from the per-task-review pattern"
fi'
run_mutant "pipeline reviews wave members per task" '
f=plugins/superb/skills/pipeline/SKILL.md
if ! grep -qF "members land independently" "$f"; then
  echo "mutant is a no-op: Rule 6 no longer says members land independently"
else
  sed -i "s|members land independently|members are reviewed per task|" "$f"
  grep -qF "members are reviewed per task" "$f" || echo "mutant is a no-op: the per-task review of wave members was not re-introduced"
  grep -qF "reviewed before its merge" "$f" || echo "mutant is a no-op: the no-review-before-merge sentence went too"
fi'

# Fix planning precedes fixing, or the round is a sequence of reactions. Phase
# 3's round 2 is the fixture's only planned round, so both mutants are
# attributable: nothing else names a fixplan.
run_mutant "run tracker fix round names no fix plan" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "fixplan p3-fixplan-r2.md" "$f"; then
  echo "mutant is a no-op: the fixture round no longer names a fix plan"
else
  sed -i "s| · fixplan p3-fixplan-r2.md||" "$f"
  grep -qF "· fixplan" "$f" && echo "mutant is a no-op: a fixplan field is still on the round (the fixture prose names the field too, which is why this anchors on the middot form)"
  grep -qF "M=2 C=1" "$f" || echo "mutant is a no-op: the M= declaration went with it, so a kill could come from a sizing arm instead"
  grep -qF "reports p3-rr2-a.md" "$f" || echo "mutant is a no-op: the reports field went too, so a kill could come from the report arm instead"
fi'
run_mutant "run tracker cites a fix plan that is not in agent-output" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "fixplan p3-fixplan-r2.md" "$f"; then
  echo "mutant is a no-op: the fixture round no longer names p3-fixplan-r2.md"
elif [ -e tools/fixtures/run-ok/agent-output/p3-fixplan-r9.md ]; then
  echo "mutant is a no-op: p3-fixplan-r9.md exists, so the renamed plan would be found"
else
  sed -i "s|fixplan p3-fixplan-r2.md|fixplan p3-fixplan-r9.md|" "$f"
  grep -qF "fixplan p3-fixplan-r9.md" "$f" || echo "mutant is a no-op: the rename did not apply"
fi'

# Review before the phase finished, in both shapes a real run produces: a task
# never started, and a task dispatched and still out. Only the box character
# changes, so the kill is attributable to the review-not-early arm and not to a
# hash or field arm.
run_mutant "run tracker reviews a phase with an unchecked task" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "^- \[x\] T2 —" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture has no single closed T2 to reopen"
else
  sed -i "s|^- \[x\] T2 —|- [ ] T2 —|" "$f"
  grep -q "^- \[ \] T2 —" "$f" || echo "mutant is a no-op: T2 was not reopened"
  grep -q "^- \[x\] RV — review fan-out · N=8" "$f" || echo "mutant is a no-op: Phase 2s round is no longer closed, so there is no started review to be early"
fi'
run_mutant "run tracker reviews a phase with a task still in progress" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "^- \[x\] T3 —" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture has no single closed T3 to reopen"
else
  sed -i "s|^- \[x\] T3 —|- [~] T3 —|" "$f"
  grep -q "^- \[~\] T3 —" "$f" || echo "mutant is a no-op: T3 was not set in-progress"
  grep -q "^- \[x\] RV — review fan-out · N=9" "$f" || echo "mutant is a no-op: Phase 3s round is no longer closed, so there is no started review to be early"
fi'

# The advancement invariant, attacked three ways. The first two make a phase
# unfinished and leave Current State pointing past it; the third moves the
# pointer over a phase the boxes alone cannot show as unfinished.
run_mutant "run tracker advances past a phase with an open RV" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF -- "- [x] RV — review fan-out · N=1" "$f"; then
  echo "mutant is a no-op: Phase 1s RV is not in the expected closed form"
else
  sed -i "s|- \[x\] RV — review fan-out · N=1|- [ ] RV — review fan-out · N=1|" "$f"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T3|" "$f"
  grep -qF -- "- **Lane A:** Phase 3 — T3" "$f" || echo "mutant is a no-op: the lane was not moved past Phase 1"
  grep -qF -- "- [ ] RV — review fan-out · N=1" "$f" || echo "mutant is a no-op: Phase 1s RV was not reopened"
fi'
run_mutant "run tracker advances past a phase with an open blocking finding" '
enable_run || exit 0
d=tools/fixtures/run-ok
if [ -e "$d/findings.md" ]; then
  echo "mutant is a no-op: the fixture already has a findings.md, so a kill would not prove the ledger half runs"
else
  printf "%s\n" "| ID | Sev | Phase | File:line | Finding | State | Closed by |" \
                "| -- | --- | ----- | --------- | ------- | ----- | --------- |" \
                "| F-001 | Critical | 1 | src/x.php:1 | mutant | open | |" > "$d/findings.md"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T3|" "$d/progress.md"
  grep -qF -- "- **Lane A:** Phase 3 — T3" "$d/progress.md" || echo "mutant is a no-op: the lane was not moved past Phase 1"
  grep -qE "^\| F-001 .*\| open \|" "$d/findings.md" || echo "mutant is a no-op: the open blocking row was not written in the shape the arm reads"
fi'
run_mutant "run tracker next action names a later phase than its own state" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "^- \[x\] T2 —" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture has no single closed T2 to reopen"
else
  sed -i "s|^- \[x\] T2 —|- [ ] T2 —|" "$f"
  sed -i "s|- \[x\] RV — review fan-out · N=8|- [ ] RV — review fan-out · N=8|" "$f"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 4 — T5|" "$f"
  grep -qF -- "- **Lane A:** Phase 4 — T5" "$f" || echo "mutant is a no-op: the lane was not moved"
  grep -qF -- "- [ ] RV — review fan-out · N=8" "$f" || echo "mutant is a no-op: Phase 2s RV stayed closed, so the review-not-early arm would kill this instead"
fi'

# The two resume states, each attacked at the thing that makes it that state.
# run-open-rv is "implemented and entirely unreviewed"; run-fixloop is "every
# box [x] and only the ledger knows". Neither shape exists in run-ok, which is
# why they are separate fixtures rather than extra phases there.
run_mutant "implemented-unreviewed fixture opens its review early" '
enable_run_dir tools/fixtures/run-open-rv || exit 0
f=tools/fixtures/run-open-rv/progress.md
if [ "$(grep -c -- "- \[ \] RV — review fan-out$" "$f")" != 2 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly two bare open RV lines"
else
  sed -i "s|^- \[x\] T5 — a task · W2 · deps T3 — .eeeeeee.|- [ ] T5 — a task · W2 · deps T3|" "$f"
  grep -q -- "^- \[ \] T5 — a task" "$f" || echo "mutant is a no-op: T5 was not reopened"
  sed -i "0,/^- \[ \] RV — review fan-out$/s|^- \[ \] RV — review fan-out$|- [~] RV — review fan-out · N=4 → 1 slice + 0 integration · started 2026-09-07 10:00|" "$f"
  grep -q -- "^- \[~\] RV" "$f" || echo "mutant is a no-op: Phase 2s review was not opened"
fi'
run_mutant "implemented-unreviewed fixture advances to the next phase" '
enable_run_dir tools/fixtures/run-open-rv || exit 0
f=tools/fixtures/run-open-rv/progress.md
if ! grep -qF -- "- **Lane A:** Phase 2 — RV" "$f"; then
  echo "mutant is a no-op: Lane A no longer names Phase 2s RV"
else
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T6|" "$f"
  grep -qF -- "- **Lane A:** Phase 3 — T6" "$f" || echo "mutant is a no-op: the lane was not moved"
fi'
run_mutant "fix-loop fixture advances with a blocking finding open" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/progress.md
if ! grep -qF -- "- **Lane A:** Phase 2 — fix loop" "$f"; then
  echo "mutant is a no-op: Lane A no longer names Phase 2s fix loop"
elif ! grep -qE "^\| F-002 .*\| open \|" tools/fixtures/run-fixloop/findings.md; then
  echo "mutant is a no-op: F-002 is not open in the ledger, so the ledger arm is not what would fire"
else
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T4|" "$f"
  grep -qF -- "- **Lane A:** Phase 3 — T4" "$f" || echo "mutant is a no-op: the lane was not moved"
fi'
run_mutant "fix-loop fixture dispatches a round with no fix plan on disk" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
p=tools/fixtures/run-fixloop/agent-output/p2-fixplan-r2.md
if [ ! -f "$p" ]; then
  echo "mutant is a no-op: the fix plan is already absent"
else
  rm -f "$p"
  grep -qF "fixplan p2-fixplan-r2.md" tools/fixtures/run-fixloop/progress.md || echo "mutant is a no-op: the round no longer names that plan, so its absence is not a missing plan"
fi'

# One fixture going unrun, rather than all of them. The arm above used to accept
# a single `--run` step, which a repo with three fixtures satisfies while two go
# unlinted; this is the mutant that says so.
run_mutant "CI stops linting one of the fixture run directories" '
f=.github/workflows/checks.yml
if ! grep -qF -- "--run tools/fixtures/run-fixloop" "$f"; then
  echo "mutant is a no-op: checks.yml does not lint run-fixloop, so there is no step to delete"
else
  sed -i "/--run tools\/fixtures\/run-fixloop/d" "$f"
  grep -qF -- "--run tools/fixtures/run-fixloop" "$f" && echo "mutant is a no-op: the step was not deleted"
  grep -qF -- "--run tools/fixtures/run-ok" "$f" || echo "mutant is a no-op: it took the run-ok step too, so a kill could come from the at-least-one arm instead"
fi'

# --- the arms the migration review added, each with the shape it was measured
# --- passing before the fix
run_mutant "run tracker round loses its M= declaration" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "round 2: M=2 C=1" "$f"; then
  echo "mutant is a no-op: the fixture round no longer declares M=2 C=1"
else
  sed -i "s|round 2: M=2 C=1 → |round 2: |" "$f"
  grep -qF "round 2: M=2 C=1" "$f" && echo "mutant is a no-op: the declaration is still on the round line (the fixture prose quotes M=2 C=1 as well, which is why this anchors on the round line)"
  grep -qF "fixplan p3-fixplan-r2.md" "$f" || echo "mutant is a no-op: the fixplan field went too, so a kill could come from the fix-plan arm instead"
fi'
run_mutant "run tracker fix round is keyed N instead of M" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "round 2: M=2 C=1" "$f"; then
  echo "mutant is a no-op: the fixture round no longer declares M=2 C=1"
else
  sed -i "s|round 2: M=2 C=1|round 2: N=2 C=1|" "$f"
  grep -qF "round 2: N=2 C=1" "$f" || echo "mutant is a no-op: the round was not re-keyed"
  grep -qF "fixplan p3-fixplan-r2.md" "$f" || echo "mutant is a no-op: the fixplan field went too, so a kill could come from the fix-plan arm instead"
fi'
run_mutant "run tracker phases are demoted below the parser" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "^## Phase " "$f")" -lt 2 ]; then
  echo "mutant is a no-op: the fixture has fewer than two parseable phase headings"
else
  sed -i "s|^## Phase |### Phase |" "$f"
  grep -q "^## Phase " "$f" && echo "mutant is a no-op: a parseable heading survived"
  grep -q "^### Phase " "$f" || echo "mutant is a no-op: the headings were not demoted"
fi'
run_mutant "run tracker opens a trailing RVJ over unfinished work" '
enable_run_dir tools/fixtures/run-open-rv || exit 0
f=tools/fixtures/run-open-rv/progress.md
if ! grep -qF -- "- [x] RVJ — joint integration review · split 2a+2b" "$f"; then
  echo "mutant is a no-op: the fixture has no leading RVJ to move"
else
  python3 - "$f" <<"EOF"
import pathlib,sys
p=pathlib.Path(sys.argv[1]); t=p.read_text()
lead="""- [x] RVJ — joint integration review · split 2a+2b · N=5 → 0 slice + 1 integration
      · reports p3-rvj-int.md · coverage p3-rvj-coverage.md → no findings
- [ ] T6 — a task · W1 · deps T4"""
trail="""- [ ] T6 — a task · W1 · deps T4
- [x] RVJ — joint integration review · split 2a+2b · N=5 → 0 slice + 1 integration
      · reports p3-rvj-int.md · coverage p3-rvj-coverage.md → no findings"""
assert t.count(lead)==1, "mutant is a no-op: the leading RVJ block is not in the expected shape"
p.write_text(t.replace(lead,trail))
EOF
fi'
run_mutant "run tracker phase carries no RV line at all" '
enable_run_dir tools/fixtures/run-open-rv || exit 0
f=tools/fixtures/run-open-rv/progress.md
if [ "$(grep -c -- "^- \[ \] RV — review fan-out$" "$f")" != 2 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly two bare open RV lines"
else
  sed -i "0,/^- \[ \] RV — review fan-out$/{/^- \[ \] RV — review fan-out$/d}" "$f"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T6|" "$f"
  [ "$(grep -c -- "^- \[ \] RV — review fan-out$" "$f")" = 1 ] || echo "mutant is a no-op: Phase 2s RV line was not the one removed"
  grep -qF -- "- **Lane A:** Phase 3 — T6" "$f" || echo "mutant is a no-op: the lane was not moved past Phase 2"
fi'
run_mutant "run tracker ledger row bolds its severity" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
d=tools/fixtures/run-fixloop
if ! grep -qE "^\| F-002 \| Major \|" "$d/findings.md"; then
  echo "mutant is a no-op: F-002 is not an unbolded Major row"
else
  sed -i "s5| F-002 | Major |5| F-002 | **Major** |5" "$d/findings.md"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T4|" "$d/progress.md"
  grep -qF "**Major**" "$d/findings.md" || echo "mutant is a no-op: the severity was not bolded"
  grep -qE "^\| F-002 .*\| open \|" "$d/findings.md" || echo "mutant is a no-op: the row is no longer open, so the ledger arm is not what would fire"
  grep -qF -- "- **Lane A:** Phase 3 — T4" "$d/progress.md" || echo "mutant is a no-op: the lane was not moved"
fi'
run_mutant "run tracker Current State keeps the retired Phase field" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/progress.md
if ! grep -qF -- "- **Lane A:** Phase 2 — fix loop" "$f"; then
  echo "mutant is a no-op: Lane A no longer names Phase 2s fix loop"
else
  # THE RETIRED GRAMMAR MUST BE REFUSED, not silently ignored. A tracker
  # still writing `**Phase:**` is one this gate would read no lane position
  # from at all, and the old two-field grammar left as a tolerated alternative
  # is the mode switch the lane model exists to remove.
  sed -i "s|^- \*\*Lane A:\*\*|- **Phase:** 2 — stale grammar\n- **Lane A:**|" "$f"
  grep -qF -- "- **Phase:** 2 — stale grammar" "$f" || echo "mutant is a no-op: the retired field was not inserted"
  grep -qF -- "- **Lane A:** Phase 2 — fix loop" "$f" || echo "mutant is a no-op: the lane line went too, so a kill could come from the missing-lane arm"
fi'

# --- the migration-corrected rules must stay corrected ---
# WHITESPACE-FLEXIBLE, and that is not a style choice. Every phrase pinned here
# wraps across lines in the file that carries it, and the arm reads FLATTENED
# text — so a `grep -qF`/`sed` mutant on the raw file matches nothing, reports
# itself a no-op and proves the pin unwatched. All four of these were written
# that way first and all four failed (measured: three SURVIVED, one NO-OP).
run_mutant "the conditional integration rule reverts in fix-loop.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
q=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(w) for w in ['only','at','a','declared','integration','boundary']]), re.I)
s=p.read_text()
assert a.search(s), 'mutant is a no-op: the phrase is already absent from that file'
out=a.sub('whenever there is more than one slice', s)
assert out!=s, 'mutant is a no-op: the substitution did not apply'
assert 'only at a declared integration boundary' not in flat(out), 'mutant is a no-op: an occurrence survived in that file'
assert 'only at a declared integration boundary' in flat(q.read_text()), 'mutant is a no-op: the phrase is gone from SKILL.md too, so a kill is not attributable to this file'
p.write_text(out)\""
run_mutant "the pre-RV repair rule reverts in parallel.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/references/parallel.md')
q=pathlib.Path('plugins/superb/skills/pipeline/references/implement.md')
ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(w) for w in ['raises','no','finding,','takes','no','F-ID']]), re.I)
s=p.read_text()
assert a.search(s), 'mutant is a no-op: the phrase is already absent from that file'
out=a.sub('is a bug finding with an F-ID', s)
assert out!=s, 'mutant is a no-op: the substitution did not apply'
assert 'raises no finding, takes no f-id' not in flat(out), 'mutant is a no-op: an occurrence survived in that file'
assert 'raises no finding, takes no f-id' in flat(q.read_text()), 'mutant is a no-op: the phrase is gone from implement.md too, so a kill is not attributable to this file'
p.write_text(out)\""
run_mutant "the re-review boundary rule reverts in SKILL.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
q=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(w) for w in ['only','at','a','declared','integration','boundary']]), re.I)
s=p.read_text()
assert a.search(s), 'mutant is a no-op: the phrase is already absent from SKILL.md'
out=a.sub('once there is more than one', s)
assert out!=s, 'mutant is a no-op: the substitution did not apply'
assert 'only at a declared integration boundary' not in flat(out), 'mutant is a no-op: an occurrence survived in SKILL.md'
assert 'only at a declared integration boundary' in flat(q.read_text()), 'mutant is a no-op: the phrase is gone from fix-loop.md too, so a kill is not attributable to this file'
p.write_text(out)\""
run_mutant "SKILL.md restates the per-task cost model" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(w) for w in ['an','implementer','for','every','task','of','every','phase']]), re.I)
s=p.read_text()
assert a.search(s), 'mutant is a no-op: the corrected cost sentence is not in the expected shape'
out=a.sub('an implementer, a reviewer and usually a fix round or two', s)
assert out!=s, 'mutant is a no-op: the substitution did not apply'
assert 'an implementer, a reviewer' in flat(out), 'mutant is a no-op: the per-task cost claim was not reintroduced'
p.write_text(out)\""

# --- round 4: the grammar is strict now, so these are the shapes it refuses ---
run_mutant "run tracker Current State names a mentioned phase" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/progress.md
if ! grep -qF -- "- **Lane A:** Phase 2 " "$f"; then
  echo "mutant is a no-op: the lane line does not lead with phase 2"
else
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** 3 — moved on past the phase 2 fix loop|" "$f"
  grep -qF -- "- **Lane A:** 3 — moved on past the phase 2" "$f" || echo "mutant is a no-op: the mentioned-phase shape was not written"
  grep -qE "^\| F-002 .*\| open \|" tools/fixtures/run-fixloop/findings.md || echo "mutant is a no-op: F-002 is not open, so nothing gates Phase 2"
fi'
run_mutant "run tracker ledger header renames its phase column" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/findings.md
if ! grep -qF "| ID | Sev | Phase |" "$f"; then
  echo "mutant is a no-op: the blocking header is not in the shipped shape"
else
  sed -i "s3| ID | Sev | Phase |3| ID | Sev | Area |3" "$f"
  grep -qF "| ID | Sev | Area |" "$f" || echo "mutant is a no-op: the column was not renamed"
  grep -qE "^\| F-002 .*\| open \|" "$f" || echo "mutant is a no-op: F-002 is not open, so an unread ledger gates nothing"
fi'
run_mutant "run tracker second blocking table gates nothing" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
d=tools/fixtures/run-fixloop
if ! grep -qF "| ID | Sev | Phase |" "$d/findings.md"; then
  echo "mutant is a no-op: the fixture has no blocking table to duplicate"
else
  # ATTRIBUTABLE: the first table own open row is closed first, so the only
  # thing that can gate Phase 2 is the SECOND table row. Left open, F-002
  # co-killed this and it proved nothing about walking more than one table.
  # (No apostrophes here on purpose: this script is single-quoted in the
  # harness, so one would terminate it.)
  sed -i "s@a fixture finding still open | open @a fixture finding still open | closed @" "$d/findings.md"
  grep -qE "^\| F-002 .*\| open \|" "$d/findings.md" && echo "mutant is a no-op: F-002 is still open, so it co-kills this and the second table proves nothing"
  printf "\n## A second blocking table\n\n| ID | Sev | Phase | File:line | Finding | State | Closed by |\n| -- | --- | ----- | --------- | ------- | ----- | --------- |\n| F-009 | Critical | 2 | \`z:1\` | a second-table finding | open | |\n" >> "$d/findings.md"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T4|" "$d/progress.md"
  grep -qF "F-009" "$d/findings.md" || echo "mutant is a no-op: the second table was not appended"
  grep -qF -- "- **Lane A:** Phase 3 — T4" "$d/progress.md" || echo "mutant is a no-op: the lane was not advanced past Phase 2"
fi'
run_mutant "run tracker boundary declares a bare dash" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -q "boundary: the T2 contract" "$f"; then
  echo "mutant is a no-op: the fixture round no longer names its boundary"
else
  sed -i "s|boundary: the T2 contract consumed by the orchestrator commit in slice b|boundary: -|" "$f"
  grep -qF "boundary: -" "$f" || echo "mutant is a no-op: the bare dash was not written"
  grep -qF "2 slice + 1 integration" "$f" || echo "mutant is a no-op: the integration reviewer went too, so a kill could come from another arm"
fi'
run_mutant "the conditional integration rule reverts in templates/progress.md" "$J \"import pathlib,re
p=pathlib.Path('plugins/superb/skills/pipeline/templates/progress.md')
q=pathlib.Path('plugins/superb/skills/pipeline/SKILL.md')
ws=chr(92)+'s+'
flat=lambda x: ' '.join(x.split()).lower()
a=re.compile(ws.join([re.escape(w) for w in ['only','at','a','declared','integration','boundary']]), re.I)
s=p.read_text()
assert a.search(s), 'mutant is a no-op: the phrase is already absent from the template'
out=a.sub('whenever there is more than one slice', s)
assert 'only at a declared integration boundary' not in flat(out), 'mutant is a no-op: an occurrence survived in the template'
assert 'only at a declared integration boundary' in flat(q.read_text()), 'mutant is a no-op: the phrase is gone from SKILL.md too, so a kill is not attributable to this file'
p.write_text(out)\""
# --- round 5: the field's LOCATION, and the one comparison that skipped _norm
run_mutant "run tracker Current State is shadowed by a prose decoy" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/progress.md
if ! grep -qF -- "- **Lane A:** Phase 2 " "$f"; then
  echo "mutant is a no-op: the lane line does not lead with phase 2"
else
  python3 - "$f" <<"EOF"
import pathlib,sys,re
p=pathlib.Path(sys.argv[1]); t=p.read_text()
assert t.count("## Current State")==1, "mutant is a no-op: Current State heading is absent or duplicated"
# ORDER MATTERS, and the first version of this mutant got it wrong: inserting
# the decoy first made the count=1 substitution below advance the DECOY, so the
# real field stayed at phase 2 and the tracker was correct. Advance the REAL
# field first, THEN put a decoy naming the earlier phase above the heading. The
# decoy is a genuine line-start list item, so this pins the BLOCK ISOLATION
# alone: read the decoy and the gate sees phase 2 and passes; read the real
# field and it sees phase 3 over an open finding against phase 2 and fails.
head, sep, body = t.partition("## Current State")
assert sep, "mutant is a no-op: no Current State heading to split on"
body2, n = re.subn(r"^- \*\*Lane A:\*\*.*$", "- **Lane A:** Phase 3 — moved on", body, count=1, flags=re.M)
assert n == 1, "mutant is a no-op: the real lane line inside the block was not advanced"
out = head + "Reminder:\n- **Lane A:** Phase 2 — fix loop, F-002 open\n\n" + sep + body2
assert "- **Lane A:** Phase 2 — fix loop, F-002 open" in out.split("## Current State")[0], "mutant is a no-op: the decoy did not land above the heading"
assert "- **Lane A:** Phase 3 — moved on" in out.split("## Current State")[1], "mutant is a no-op: the real line is not the advanced one"
p.write_text(out)
EOF
  grep -qE "^\| F-002 .*\| open \|" tools/fixtures/run-fixloop/findings.md || echo "mutant is a no-op: F-002 is not open, so nothing gates Phase 2"
fi'
run_mutant "run tracker ledger row id is bolded" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/findings.md
if ! grep -qE "^\| F-002 \| Major \|" "$f"; then
  echo "mutant is a no-op: F-002 is not an unbolded Major row"
else
  sed -i "s3| F-002 | Major |3| **F-002** | Major |3" "$f"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T4|" tools/fixtures/run-fixloop/progress.md
  grep -qF "| **F-002** |" "$f" || echo "mutant is a no-op: the row id was not bolded"
  grep -qF "| ID | Sev | Phase |" "$f" || echo "mutant is a no-op: the header changed too, so a kill could come from the header arm"
fi'
run_mutant "run tracker four-column ledger renames its phase column" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
d=tools/fixtures/run-fixloop
if ! grep -qE "^\| F-002 .*\| open \|" "$d/findings.md"; then
  echo "mutant is a no-op: F-002 is not open, so an unread ledger gates nothing"
else
  printf "# fixture\n\n## Blocking ledger\n\n| ID | Sev | Area | State |\n| -- | --- | ---- | ----- |\n| F-002 | Major | 2 | open |\n" > "$d/findings.md"
  grep -qF "| ID | Sev | Area | State |" "$d/findings.md" || echo "mutant is a no-op: the narrow renamed table was not written"
fi'

# --- round 6: the structural half, and the id grammar ---
# These three exist because five rounds produced five ways to lose the Phase
# field, every one of them SILENT. The arm now reports what it cannot locate, so
# these mutants prove the loudness, not just the parse.
run_mutant "run tracker loses its lane line" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/progress.md
if [ "$(grep -c -- "^- \*\*Lane A:\*\*" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture does not have exactly one lane line"
else
  sed -i "/^- \*\*Lane A:\*\*/d" "$f"
  grep -q -- "^- \*\*Lane A:\*\*" "$f" && echo "mutant is a no-op: a lane line survived"
  grep -qF "## Current State" "$f" || echo "mutant is a no-op: the Current State block went too, so a kill could come from another arm"
fi'
run_mutant "run tracker grows a second Current State block" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/progress.md
if [ "$(grep -c "^## Current State$" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture does not have exactly one Current State block"
else
  printf "\n## Current State\n- **Lane A:** Phase 3 — a stale appended duplicate\n" >> "$f"
  [ "$(grep -c "^## Current State$" "$f")" = 2 ] || echo "mutant is a no-op: the second block was not appended"
fi'
run_mutant "run tracker ledger row id is not F-<n>" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
d=tools/fixtures/run-fixloop
if ! grep -qE "^\| F-002 .*\| open \|" "$d/findings.md"; then
  echo "mutant is a no-op: F-002 is not the open blocking row"
else
  sed -i "s3| F-002 |3| N-002 |3" "$d/findings.md"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T4|" "$d/progress.md"
  grep -qE "^\| N-002 .*\| open \|" "$d/findings.md" || echo "mutant is a no-op: the row id was not changed"
  grep -qF "| ID | Sev | Phase |" "$d/findings.md" || echo "mutant is a no-op: the header changed too, so a kill could come from the header arm"
fi'

# --- the regression correction: an affirmative line needs a real comparison ---
run_mutant "run tracker lane line resolves to nothing" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qxF -- "- **Lane A:** waiting at join Phase 4" "$f"; then
  echo "mutant is a no-op: Lane A is not waiting at the join"
else
  # NEITHER A PHASE ID NOR A BLESSED PHASE-LESS FORM, and it must not start with
  # a word either: a leading alphanumeric token resolves as a phase id and kills
  # through the missing-phase arm instead. Lane B still names a phase, so the
  # fail-closed backstop stays quiet.
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane A:** (waiting)|" "$f"
  grep -qxF -- "- **Lane A:** (waiting)" "$f" || echo "mutant is a no-op: the lane line was not made non-naming"
  grep -qxF -- "- **Lane B:** Phase 3 — T3" "$f" || echo "mutant is a no-op: Lane B stopped naming a phase, so a kill could come from the fail-closed arm"
fi'

run_mutant "run tracker hides a stale lane line above the fresh one" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/progress.md
if [ "$(grep -c -- "^- \*\*Lane A:\*\*" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture does not have exactly one lane line"
else
  python3 - "$f" <<"EOF"
import pathlib,sys,re
p=pathlib.Path(sys.argv[1]); t=p.read_text()
out,n = re.subn(r"^- \*\*Lane A:\*\*.*$", "- **Lane A:** Phase 2 — stale, left above\n- **Lane A:** Phase 3 — fresh", t, count=1, flags=re.M)
assert n == 1, "mutant is a no-op: the lane line was not duplicated"
p.write_text(out)
EOF
  [ "$(grep -c -- "^- \*\*Lane A:\*\*" "$f")" = 2 ] || echo "mutant is a no-op: there are not exactly two lane lines now"
fi'
run_mutant "run tracker ledger row id has a letter after the dash" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
d=tools/fixtures/run-fixloop
if ! grep -qE "^\| F-002 .*\| open \|" "$d/findings.md"; then
  echo "mutant is a no-op: F-002 is not the open blocking row"
else
  sed -i "s3| F-002 |3| NEW-F2 |3" "$d/findings.md"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T4|" "$d/progress.md"
  grep -qE "^\| NEW-F2 .*\| open \|" "$d/findings.md" || echo "mutant is a no-op: the row id was not changed to the letter-after-dash shape"
  grep -qF "| ID | Sev | Phase |" "$d/findings.md" || echo "mutant is a no-op: the header changed too, so a kill could come from the header arm"
fi'

run_mutant "run tracker buys a smaller review by declaring one wave" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c -- "N=8 → 2 slice + 1 integration" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one N=8 round declaring 2 slice"
else
  # W=1 with a task count whose ceil(N/5) is 3 while the round still declares
  # 2 slice: legal under the old waved regime, and the whole point of removing
  # it. The declared reviewer TOTAL is left at 3 (2 slice + 1 integration) and
  # the reports field is untouched, so a kill cannot come from the
  # reviewer-count arm; the boundary stays named, so it cannot come from either
  # integration arm either.
  sed -i "s|N=8 → 2 slice + 1 integration|N=13 W=1 → 2 slice + 1 integration|" "$f"
  grep -qF -- "N=13 W=1 → 2 slice + 1 integration" "$f" || echo "mutant is a no-op: the declaration was not rewritten"
  grep -qF -- "reports p2-review-{a,b,int}.md" "$f" || echo "mutant is a no-op: the reports field went too, so a kill could come from the reviewer-count arm instead"
  grep -qF -- "boundary: the T2 contract" "$f" || echo "mutant is a no-op: the boundary declaration went too, so a kill could come from an integration arm instead"
fi'

# ---- a fix round belongs to the gate that raised its findings ----
# The RVJ in run-rvj-fix raised F-101 (Critical, now closed) and carries its own
# appended round. Both directions of that are mutated: file the round under the
# phase's RV instead, and remove it altogether. A third case needs no mutant --
# an OPEN blocking finding owes no completed round, and run-fixloop's F-002 is
# the standing conforming input for it.
run_mutant "run tracker RVJ round is filed under the phase RV" '
enable_run_dir tools/fixtures/run-rvj-fix || exit 0
f=tools/fixtures/run-rvj-fix/progress.md
if [ "$(grep -c -- "→ round 2: M=1 C=1" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one appended round"
else
  python3 - "$f" <<"EOF"
import pathlib, re, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text()
m = re.search(r"(?m)^      → round 2: M=1 C=1.*(?:\n        .*)*\n", t)
assert m, "mutant is a no-op: the round block is not in the expected shape"
blk = m.group(0)
t = t[:m.start()] + t[m.end():]
# Re-file it under the PHASE RV -- the wrong gate. The RV line is the one
# declaring N=2 -> 1 slice; insert directly after its continuation line.
i = t.index("      · reports p2-review-a.md · coverage p2-coverage.md → no findings\n")
j = i + len("      · reports p2-review-a.md · coverage p2-coverage.md → no findings\n")
p.write_text(t[:j] + blk + t[j:])
EOF
  grep -qF -- "→ round 2: M=1 C=1" "$f" || echo "mutant is a no-op: the round block was lost rather than moved"
  grep -qF -- "→ F-101" "$f" || echo "mutant is a no-op: the RVJ outcome went too, so a kill could come from another arm"
fi'

run_mutant "run tracker RVJ closes a blocking finding with no round" '
enable_run_dir tools/fixtures/run-rvj-fix || exit 0
f=tools/fixtures/run-rvj-fix/progress.md
if [ "$(grep -c -- "→ round 2: M=1 C=1" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one appended round"
else
  python3 - "$f" <<"EOF"
import pathlib, re, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text()
m = re.search(r"(?m)^      → round 2: M=1 C=1.*(?:\n        .*)*\n", t)
assert m, "mutant is a no-op: the round block is not in the expected shape"
p.write_text(t[:m.start()] + t[m.end():])
EOF
  grep -qF -- "→ round 2:" "$f" && echo "mutant is a no-op: the round survived"
  grep -qF -- "→ F-101" "$f" || echo "mutant is a no-op: the RVJ outcome went too, so a kill could come from another arm"
fi'

# ---- every F-ID in an M=0 record is validated independently ----
# The old check was one `route.search(body)`: "is there at least one legal route
# anywhere in this record". A valid FIRST closure then masked every invalid one
# after it, which is what these three mutants target -- each leaves the first
# closure legal and corrupts only the second.
run_mutant "M=0 second closure is a bare withdrawn" '
f=plugins/superb/skills/pipeline/references/fix-loop.md
if ! grep -qF -- "F-019 withdrawn → duplicate of F-011" "$f"; then
  echo "mutant is a no-op: the worked M=0 record is not in the expected shape"
else
  perl -0pi -e "s/F-019 withdrawn[^,]*duplicate of F-011/F-019 withdrawn/" "$f"
  grep -qF -- "F-018 user-ruled false positive" "$f" || echo "mutant is a no-op: the legal first closure went too, so a kill could come from the no-route branch instead"
  grep -qF -- "duplicate of F-011" "$f" && echo "mutant is a no-op: the reason survived"
fi'

run_mutant "M=0 second closure is a deletion" '
f=plugins/superb/skills/pipeline/references/fix-loop.md
if ! grep -qF -- "F-019 withdrawn → duplicate of F-011" "$f"; then
  echo "mutant is a no-op: the worked M=0 record is not in the expected shape"
else
  perl -0pi -e "s/F-019 withdrawn[^,]*duplicate of F-011/F-019 deleted/" "$f"
  grep -qF -- "F-018 user-ruled false positive" "$f" || echo "mutant is a no-op: the legal first closure went too, so a kill could come from the no-route branch instead"
  grep -qF -- "F-019 deleted" "$f" || echo "mutant is a no-op: the deletion route was not written"
fi'

run_mutant "M=0 second closure names no route at all" '
f=plugins/superb/skills/pipeline/references/fix-loop.md
if ! grep -qF -- "F-019 withdrawn → duplicate of F-011" "$f"; then
  echo "mutant is a no-op: the worked M=0 record is not in the expected shape"
else
  perl -0pi -e "s/F-019 withdrawn[^,]*duplicate of F-011/F-019/" "$f"
  grep -qF -- "F-018 user-ruled false positive" "$f" || echo "mutant is a no-op: the legal first closure went too, so a kill could come from the no-route branch instead"
  grep -qF -- "F-019 withdrawn" "$f" && echo "mutant is a no-op: the route survived"
fi'

run_mutant "run ledger withdrawn row names a fix commit" '
enable_run_dir tools/fixtures/run-fixloop || exit 0
f=tools/fixtures/run-fixloop/findings.md
if [ "$(grep -c -- "| withdrawn | withdrawn → duplicate of F-002 |" "$f")" != 1 ]; then
  echo "mutant is a no-op: the withdrawn row is not in the expected shape"
else
  sed -i "s#| withdrawn | withdrawn → duplicate of F-002 |#| withdrawn | fix \`9c3a1f7\` |#" "$f"
  grep -qF -- "9c3a1f7" "$f" || echo "mutant is a no-op: the hash was not written"
fi'

# ---- the persisted lane mapping ----
run_mutant "run tracker phase heading carries no lane" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "^## Phase 2 .* · lane: A$" "$f")" != 1 ]; then
  echo "mutant is a no-op: Phase 2s heading is not in the expected shape"
else
  sed -i "s|^\(## Phase 2 .*\) · lane: A$|\1|" "$f"
  grep -q "^## Phase 2 .* · lane:" "$f" && echo "mutant is a no-op: the lane field survived"
fi'

run_mutant "run tracker phase heading carries two lanes" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "^## Phase 3 .* · lane: A$" "$f")" != 1 ]; then
  echo "mutant is a no-op: Phase 3s heading is not in the expected shape"
else
  sed -i "s|^\(## Phase 3 .* · lane: A\)$|\1 · lane: B|" "$f"
  grep -q "^## Phase 3 .* · lane: A · lane: B$" "$f" || echo "mutant is a no-op: the second lane field was not added"
fi'

# ---- fork allocation ----
run_mutant "fork first successor does not continue the lane" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if [ "$(grep -c "^## Phase 2 .* · lane: A$" "$f")" != 1 ]; then
  echo "mutant is a no-op: Phase 2s heading is not in the expected shape"
else
  # Rename Lane A to C on the BRANCH and on the join it survives into, and in
  # Current State. The join survivor then still matches its first contributing
  # predecessor and Lane A owns only the finished Phase 1, so the ONLY thing
  # wrong is that the fork first successor stopped continuing the forking
  # phases lane -- which is what this pins.
  sed -i "s|^\(## Phase 2 .*\) · lane: A$|\1 · lane: C|" "$f"
  sed -i "s|^\(## Phase 4 .*\) · lane: A$|\1 · lane: C|" "$f"
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane C:** waiting at join Phase 4|" "$f"
  grep -q "^## Phase 2 .* · lane: C$" "$f" || echo "mutant is a no-op: the first branch lane was not changed"
  grep -q "^## Phase 4 .* · lane: C$" "$f" || echo "mutant is a no-op: the join kept lane A, so a kill could come from the survivor arm"
  grep -q "^## Phase 1 .* · lane: A$" "$f" || echo "mutant is a no-op: the forking phase lost lane A, so there is no rule left to break"
fi'

run_mutant "fork further branch reuses an existing lane" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if [ "$(grep -c "^## Phase 3 .* · lane: B$" "$f")" != 1 ]; then
  echo "mutant is a no-op: Phase 3s heading is not in the expected shape"
else
  # The second branch takes lane A, which Phase 1 and Phase 2 already carry.
  # Phase 4 then has one contributing lane and is no longer a join, so Current
  # State drops the waiting form and Lane B with it -- leaving the reused-id
  # report as the only one standing.
  sed -i "s|^\(## Phase 3 .*\) · lane: B$|\1 · lane: A|" "$f"
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane A:** Phase 3 — T3|" "$f"
  sed -i "\|^- \*\*Lane B:\*\* Phase 3 — T3$|d" "$f"
  grep -q "^## Phase 3 .* · lane: A$" "$f" || echo "mutant is a no-op: the further branch lane was not changed"
  grep -q "^## Phase 2 .* · lane: A$" "$f" || echo "mutant is a no-op: the earlier carrier of lane A went too, so the id would be fresh"
  grep -qF -- "- **Lane B:**" "$f" && echo "mutant is a no-op: Lane B survived in Current State and no phase carries it"
fi'

# ---- join survivor and retirement ----
run_mutant "join phase takes the wrong contributors lane" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if [ "$(grep -c "^## Phase 4 .* · lane: A$" "$f")" != 1 ]; then
  echo "mutant is a no-op: Phase 4s heading is not in the expected shape"
else
  sed -i "s|^\(## Phase 4 .*\) · lane: A$|\1 · lane: B|" "$f"
  grep -q "^## Phase 4 .* · lane: B$" "$f" || echo "mutant is a no-op: the survivor lane was not swapped"
fi'

# ---- LANE X MAY NAME PHASE P IFF PHASE P CARRIES `· lane: X` ----
run_mutant "run tracker lane names another lanes phase" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- **Lane A:** waiting at join Phase 4" "$f"; then
  echo "mutant is a no-op: Lane A is not waiting at the join"
else
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane A:** Phase 3 — T3|" "$f"
  grep -qF -- "- **Lane A:** Phase 3 — T3" "$f" || echo "mutant is a no-op: Lane A was not pointed at Lane Bs phase"
  grep -q "^## Phase 3 .* · lane: B$" "$f" || echo "mutant is a no-op: Phase 3 no longer belongs to Lane B, so the kill would not be about ownership"
fi'

run_mutant "non-surviving lane runs the joining phases leading RVJ" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- **Lane B:** Phase 3 — T3" "$f"; then
  echo "mutant is a no-op: Lane B is not at Phase 3"
else
  # Lane B is a contributor, not the survivor: Phase 4 carries · lane: A.
  sed -i "s|^- \*\*Lane B:\*\* Phase 3 — T3$|- **Lane B:** Phase 4 — RVJ|" "$f"
  grep -qF -- "- **Lane B:** Phase 4 — RVJ" "$f" || echo "mutant is a no-op: Lane B was not pointed at the join"
  grep -q "^## Phase 4 .* · lane: A$" "$f" || echo "mutant is a no-op: Phase 4 no longer belongs to Lane A, so the kill would not be about ownership"
fi'

# ---- `done` and `waiting at join` are claims, not strings ----
run_mutant "unfinished lane says done" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qxF -- "- **Lane A:** waiting at join Phase 4" "$f"; then
  echo "mutant is a no-op: Lane A is not waiting at the join"
else
  # ON run-lanes, so Lane B keeps naming a real phase: the fail-closed backstop
  # ("blockers exist and no lane names a phase") then stays quiet and the
  # done-over-open-work report is the only one left. Lane A owns Phase 4, which
  # is unfinished, so `done` is a false claim.
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane A:** done|" "$f"
  grep -qxF -- "- **Lane A:** done" "$f" || echo "mutant is a no-op: the lane was not set to done"
  grep -qxF -- "- **Lane B:** Phase 3 — T3" "$f" || echo "mutant is a no-op: Lane B stopped naming a phase, so a kill could come from the fail-closed arm"
fi'

run_mutant "lane waits at a join that does not exist" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- **Lane A:** waiting at join Phase 4" "$f"; then
  echo "mutant is a no-op: Lane A is not waiting at the join"
else
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane A:** waiting at join Phase 9|" "$f"
  grep -qF -- "waiting at join Phase 9" "$f" || echo "mutant is a no-op: the join id was not changed"
fi'

run_mutant "lane waits at a phase that is not a join" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- **Lane A:** waiting at join Phase 4" "$f"; then
  echo "mutant is a no-op: Lane A is not waiting at the join"
else
  # Phase 2 has one dependency and one contributing lane: not a join at all.
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane A:** waiting at join Phase 2|" "$f"
  grep -qF -- "waiting at join Phase 2" "$f" || echo "mutant is a no-op: the join id was not changed"
  grep -q "^## Phase 4 .* · lane: A$" "$f" || echo "mutant is a no-op: the real join changed too"
fi'

run_mutant "lane waits while its own branch is unfinished" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- **Lane B:** Phase 3 — T3" "$f"; then
  echo "mutant is a no-op: Lane B is not at Phase 3"
else
  # Lane Bs own Phase 3 is still open, so it cannot be waiting at the join.
  sed -i "s|^- \*\*Lane B:\*\* Phase 3 — T3$|- **Lane B:** waiting at join Phase 4|" "$f"
  grep -qF -- "- **Lane B:** waiting at join Phase 4" "$f" || echo "mutant is a no-op: Lane B was not put into the waiting state"
  grep -qF -- "- [ ] T3 — a task" "$f" || echo "mutant is a no-op: Phase 3 closed too, so waiting would be legitimate"
fi'

# ---- Current State must account for every active lane, and no retired one ----
run_mutant "an active lane vanishes from Current State" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- **Lane B:** Phase 3 — T3" "$f"; then
  echo "mutant is a no-op: Lane B is not at Phase 3"
else
  sed -i "\|^- \*\*Lane B:\*\* Phase 3 — T3$|d" "$f"
  grep -qF -- "- **Lane B:**" "$f" && echo "mutant is a no-op: a Lane B line survived"
  grep -q "^## Phase 3 .* · lane: B$" "$f" || echo "mutant is a no-op: Phase 3 stopped belonging to Lane B, so Lane B would not be active"
fi'

run_mutant "a retired lane is left in Current State" '
enable_run_dir tools/fixtures/run-leading-rvj-fix || exit 0
f=tools/fixtures/run-leading-rvj-fix/progress.md
if ! grep -qF -- "- **Lane A:** Phase 4 — T4" "$f"; then
  echo "mutant is a no-op: Lane A is not inside the joining phase"
else
  sed -i "s|^- \*\*Lane A:\*\* Phase 4 — T4$|- **Lane A:** Phase 4 — T4\n- **Lane B:** done|" "$f"
  grep -qF -- "- **Lane B:** done" "$f" || echo "mutant is a no-op: the retired lane line was not added"
  grep -qF -- "- **Lane A:** Phase 4 — T4" "$f" || echo "mutant is a no-op: the surviving lanes line went too"
fi'

run_mutant "Current State names a lane no phase carries" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF -- "- **Lane A:** done (fixture)" "$f"; then
  echo "mutant is a no-op: run-ok is not in the expected done state"
else
  sed -i "s|^- \*\*Lane A:\*\* done (fixture)$|- **Lane Z:** done (fixture)|" "$f"
  grep -qF -- "- **Lane Z:**" "$f" || echo "mutant is a no-op: the lane id was not changed"
fi'

# ---- the leading RVJ owns its own remediation round ----
run_mutant "leading RVJ round is filed under the joining phase RV" '
enable_run_dir tools/fixtures/run-leading-rvj-fix || exit 0
f=tools/fixtures/run-leading-rvj-fix/progress.md
if [ "$(grep -c -- "→ round 2: M=1 C=1" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one appended round"
else
  python3 - "$f" <<"EOF"
import pathlib, re, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text()
m = re.search(r"(?m)^      → round 2: M=1 C=1.*(?:\n        .*)*\n", t)
assert m, "mutant is a no-op: the round block is not in the expected shape"
blk = m.group(0)
t = t[:m.start()] + t[m.end():]
# Re-file it under Phase 3s CLOSED RV -- a different gate. Phase 4s own RV
# is `[ ]`, and an open gate is not a mark at all, so a round placed under it
# would still be attributed to the RVJ above and the mutant would prove
# nothing.
k = "      · reports p3-review-a.md · coverage p3-coverage.md \u2192 no findings\n"
i = t.index(k) + len(k)
p.write_text(t[:i] + blk + t[i:])
EOF
  grep -qF -- "→ round 2: M=1 C=1" "$f" || echo "mutant is a no-op: the round block was lost rather than moved"
  grep -qF -- "→ F-201" "$f" || echo "mutant is a no-op: the RVJ outcome went too, so a kill could come from another arm"
fi'

run_mutant "joining phase is entered before its leading RVJ closes" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- [ ] T3 — a task · W1 · deps T1" "$f"; then
  echo "mutant is a no-op: Phase 3 is not open to begin with"
else
  # BUILT ON run-lanes, not run-leading-rvj-fix. Reopening a closed RVJ there
  # also detaches its appended round, which then attributes to the previous
  # gate and kills through the round-ownership arm instead -- certifying
  # nothing about join entry. Here every contributor passes, the leading RVJ
  # stays `[ ]`, and the ONLY thing wrong is that Lane A names a task inside
  # the join.
  # PHASE 3s RV ONLY. A global sed matched Phase 4s identical `- [ ] RV` line
  # too, which closed a review over unchecked tasks and killed through the
  # review-not-early arm instead.
  python3 - "$f" <<"EOF"
import pathlib, sys
p = pathlib.Path(sys.argv[1]); L = p.read_text().split("\n")
i = L.index("- [ ] T3 — a task \u00b7 W1 \u00b7 deps T1")
L[i] = "- [x] T3 — a task \u00b7 W1 \u00b7 deps T1 \u2014 `ccccccc`"
j = L.index("- [ ] RV \u2014 review fan-out", i)
L[j:j+1] = ["- [x] RV \u2014 review fan-out \u00b7 N=1 \u2192 1 slice + 0 integration",
            "      \u00b7 reports p3-review-a.md \u00b7 coverage p3-coverage.md \u2192 no findings"]
p.write_text("\n".join(L))
EOF
  printf "fixture\n" > tools/fixtures/run-lanes/agent-output/p3-review-a.md
  printf "| report | range |\n| --- | --- |\n| p3-review-a.md | ccccccc^..ccccccc |\n\nCOVERED: 1/1 commits\n" > tools/fixtures/run-lanes/agent-output/p3-coverage.md
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane A:** Phase 4 — T4|" "$f"
  sed -i "s|^- \*\*Lane B:\*\* Phase 3 — T3$|- **Lane B:** waiting at join Phase 4|" "$f"
  grep -qF -- "- **Lane A:** Phase 4 — T4" "$f" || echo "mutant is a no-op: Lane A did not name a task inside the join"
  grep -qF -- "- [ ] RVJ — joint integration review" "$f" || echo "mutant is a no-op: the leading RVJ is no longer open, so entry would be legal"
  grep -qF -- "- [x] T3 — a task" "$f" || echo "mutant is a no-op: Phase 3 did not close, so a kill could come from the contributors-unfinished branch"
fi'

run_mutant "gitignore drops the run-directory rule" '
if ! grep -qxF -- "docs/superpowers/runs/*/" .gitignore; then
  echo "mutant is a no-op: the ignore rule is not present to remove"
else
  sed -i "\|^docs/superpowers/runs/\*/$|d" .gitignore
  grep -qxF -- "docs/superpowers/runs/*/" .gitignore && echo "mutant is a no-op: the rule survived"
fi'

run_mutant "gitignore hides curated documentation too" '
if ! grep -qxF -- "docs/superpowers/runs/*/" .gitignore; then
  echo "mutant is a no-op: the ignore rule is not present to widen"
else
  # APPENDED, not substituted. Replacing the narrow rule also trips the
  # "no run-directory rule" arm, so the kill said nothing about the width check
  # -- which could then be deleted on a green harness.
  printf "docs/superpowers/\n" >> .gitignore
  grep -qxF -- "docs/superpowers/" .gitignore || echo "mutant is a no-op: the wide rule was not added"
  grep -qxF -- "docs/superpowers/runs/*/" .gitignore || echo "mutant is a no-op: the narrow rule went too, so a kill could come from the missing-rule arm"
fi'

# ---- CLOSE(review_gate) is not PASS, and the reopen rule is gate-neutral ----
# perl -0pi rather than sed: each phrase can wrap across lines, the pin arm
# reads whitespace-flattened text, and sed is line-oriented -- the reflow hazard
# that made four earlier pin mutants survive.
run_mutant "the leading-RVJ successor is collapsed into PASS" '
f=plugins/superb/skills/pipeline/SKILL.md
if ! grep -qF -- "CLOSE(leading RVJ)     → IMPLEMENT JOINING PHASE" "$f"; then
  echo "mutant is a no-op: the successor table is not in the expected shape"
else
  perl -0pi -e "s/CLOSE\(leading RVJ\)\s+\S+ IMPLEMENT JOINING PHASE/CLOSE(leading RVJ)     -> phase PASS/" "$f"
  grep -qF -- "IMPLEMENT JOINING PHASE" "$f" && echo "mutant is a no-op: the successor survived"
  grep -qF -- "CLOSE(RV)              → phase PASS" "$f" || echo "mutant is a no-op: the other successors went too"
fi'

run_mutant "the leading-RVJ invariant is deleted" '
f=plugins/superb/skills/pipeline/SKILL.md
if ! grep -qF -- "A CLEAN LEADING RVJ MUST NEVER MARK THE JOINING PHASE PASS." "$f"; then
  echo "mutant is a no-op: the invariant is not present to remove"
else
  perl -0pi -e "s/A CLEAN LEADING RVJ MUST NEVER MARK THE JOINING PHASE PASS\.\n//" "$f"
  grep -qF -- "A CLEAN LEADING RVJ MUST NEVER" "$f" && echo "mutant is a no-op: the invariant survived"
fi'

run_mutant "the reopen rule names RV alone again" '
f=plugins/superb/skills/pipeline/references/fix-loop.md
if ! grep -qF -- "A re-review reopens the gate that raised the findings" "$f"; then
  echo "mutant is a no-op: the gate-neutral reopen rule is not present"
else
  perl -0pi -e "s/A re-review reopens the gate that raised the findings, and\s+no other\./A re-review reopens the phase RV./s" "$f"
  grep -qF -- "reopens the gate that raised" "$f" && echo "mutant is a no-op: the rule survived"
fi'

# ---- arms a whole-change review found deletable on a green harness ----
# Each of these pins one report that no earlier mutant reached, and each is
# built to leave exactly ONE report standing: a kill through a neighbouring arm
# certifies nothing about its own target.

run_mutant "join phase carries no leading RVJ" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if [ "$(grep -c -- "- \[ \] RVJ — joint integration review · lanes A+B" "$f")" != 1 ]; then
  echo "mutant is a no-op: the leading RVJ is not in the expected shape"
else
  # Lane A is `waiting at join Phase 4`, so nothing names Phase 4: this is the
  # structural check, not the per-position one.
  sed -i "/^- \[ \] RVJ — joint integration review · lanes A+B/d" "$f"
  grep -qF -- "RVJ — joint integration review" "$f" && echo "mutant is a no-op: the leading RVJ survived"
  grep -q "^## Phase 4 .* deps: Phase 2, Phase 3 · lane: A$" "$f" || echo "mutant is a no-op: Phase 4 stopped being a join"
fi'

# The shared mutation for both: reopen the contributor on lane B, close the
# joining phase, and move Lane A past it to Phase 5. Lane A then names no join,
# so the join-entry arm stays quiet and the reports left are the ones this pair
# exists to pin.
_reopen_contributor() { python3 - <<"PYE"
import pathlib
p = pathlib.Path("tools/fixtures/run-leading-rvj-fix/progress.md")
L = p.read_text().split("\n")
i = L.index("- [x] T3 \u2014 a task \u00b7 W1 \u00b7 deps T1 \u2014 `ccccccc`")
L[i] = "- [ ] T3 \u2014 a task \u00b7 W1 \u00b7 deps T1"
j = next((k for k in range(i, len(L))
          if L[k].startswith("- [x] RV \u2014 review fan-out")), None)
assert j is not None, "mutant is a no-op: Phase 3s closed RV is not where this mutation indexes"
del L[j:j+2]
L.insert(j, "- [ ] RV \u2014 review fan-out")
k = L.index("- [ ] T4 \u2014 a task \u00b7 W1 \u00b7 deps T2, T3")
L[k] = "- [x] T4 \u2014 a task \u00b7 W1 \u00b7 deps T2, T3 \u2014 `ddddddd`"
m = next((n for n in range(k, len(L))
          if L[n] == "- [ ] RV \u2014 review fan-out"), None)
assert m is not None, "mutant is a no-op: Phase 4s open RV is not where this mutation indexes"
L[m:m+1] = ["- [x] RV \u2014 review fan-out \u00b7 N=1 \u2192 1 slice + 0 integration",
            "      \u00b7 reports p4-review-a.md \u00b7 coverage p4-coverage.md \u2192 no findings"]
L[L.index("- **Lane A:** Phase 4 \u2014 T4")] = "- **Lane A:** Phase 5 \u2014 T5"
p.write_text("\n".join(L))
PYE
  printf "fixture\n" > tools/fixtures/run-leading-rvj-fix/agent-output/p4-review-a.md
  printf "| report | range |\n| --- | --- |\n| p4-review-a.md | ddddddd^..ddddddd |\n\nCOVERED: 1/1 commits\n" > tools/fixtures/run-leading-rvj-fix/agent-output/p4-coverage.md
}

run_mutant "a leading RVJ closes over an unfinished contributor" '
enable_run_dir tools/fixtures/run-leading-rvj-fix || exit 0
f=tools/fixtures/run-leading-rvj-fix/progress.md
if ! grep -qF -- "- [x] T3 — a task · W1 · deps T1 — \`ccccccc\`" "$f"; then
  echo "mutant is a no-op: Phase 3 is not closed to begin with"
else
  grep -qxF -- "- [ ] T4 — a task · W1 · deps T2, T3" "$f" || { echo "mutant is a no-op: Phase 4s task line moved, so the shared mutation cannot run"; exit 0; }
  grep -qxF -- "- **Lane A:** Phase 4 — T4" "$f" || { echo "mutant is a no-op: Lane As line moved, so the shared mutation cannot run"; exit 0; }
  _reopen_contributor
  # Lane B keeps a line naming its own open phase, so the missing-lane arm stays
  # quiet and the premature-review report is the ONLY one left.
  sed -i "s|^- \*\*Lane A:\*\* Phase 5 — T5$|- **Lane A:** Phase 5 — T5\n- **Lane B:** Phase 3 — T3|" "$f"
  grep -qF -- "- [ ] T3 — a task" "$f" || echo "mutant is a no-op: Phase 3 was not reopened"
  grep -qF -- "- **Lane B:** Phase 3 — T3" "$f" || echo "mutant is a no-op: Lane B got no line, so a kill could come from the missing-lane arm"
  grep -qF -- "- [x] RVJ — joint integration review" "$f" || echo "mutant is a no-op: the leading RVJ is no longer closed"
fi'

run_mutant "a closed leading RVJ retires a lane whose branch is unfinished" '
enable_run_dir tools/fixtures/run-leading-rvj-fix || exit 0
f=tools/fixtures/run-leading-rvj-fix/progress.md
if ! grep -qF -- "- [x] T3 — a task · W1 · deps T1 — \`ccccccc\`" "$f"; then
  echo "mutant is a no-op: Phase 3 is not closed to begin with"
else
  # THE SHAPE THAT USED TO PASS OUTRIGHT: no line for Lane B at all. Retirement
  # keyed on the tick alone dropped it out of every advancement check, so a
  # phase never implemented and never reviewed read as done. Revert the
  # `not _unfin` guard and this mutant survives.
  grep -qxF -- "- [ ] T4 — a task · W1 · deps T2, T3" "$f" || { echo "mutant is a no-op: Phase 4s task line moved, so the shared mutation cannot run"; exit 0; }
  grep -qxF -- "- **Lane A:** Phase 4 — T4" "$f" || { echo "mutant is a no-op: Lane As line moved, so the shared mutation cannot run"; exit 0; }
  _reopen_contributor
  grep -qF -- "- [ ] T3 — a task" "$f" || echo "mutant is a no-op: Phase 3 was not reopened"
  grep -qF -- "- **Lane B:**" "$f" && echo "mutant is a no-op: Lane B has a line, so this is not the vanishing-lane shape"
  grep -qF -- "- [x] RVJ — joint integration review" "$f" || echo "mutant is a no-op: the leading RVJ is no longer closed"
fi'

run_mutant "a closed gate names no outcome" '
enable_run_dir tools/fixtures/run-rvj-fix || exit 0
f=tools/fixtures/run-rvj-fix/progress.md
if ! grep -qF -- "· reports p2-review-a.md · coverage p2-coverage.md → no findings" "$f"; then
  echo "mutant is a no-op: Phase 2s RV is not in the expected shape"
else
  sed -i "s|· reports p2-review-a.md · coverage p2-coverage.md → no findings|· reports p2-review-a.md · coverage p2-coverage.md|" "$f"
  grep -qF -- "· coverage p2-coverage.md → no findings" "$f" && echo "mutant is a no-op: the outcome survived"
  grep -qF -- "· reports p2-review-a.md" "$f" || echo "mutant is a no-op: the reports field went too, so a kill could come from the evidence arm"
fi'

run_mutant "a fix round is filed under a gate that raised nothing" '
enable_run_dir tools/fixtures/run-rvj-fix || exit 0
f=tools/fixtures/run-rvj-fix/progress.md
if [ "$(grep -c -- "→ round 2: M=1 C=1" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one appended round"
else
  # The RECEIVING end of a misfile: a round under Phase 2s clean RV. The RVJ
  # keeps a round of its own, so the source-side arm stays quiet and only the
  # destination-side arm can kill this.
  python3 - "$f" <<"EOF"
import pathlib, re, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text()
m = re.search(r"(?m)^      → round 2: M=1 C=1.*(?:\n        .*)*\n", t)
assert m, "mutant is a no-op: the round block is not in the expected shape"
k = "      · reports p2-review-a.md · coverage p2-coverage.md → no findings\n"
i = t.index(k) + len(k)
p.write_text(t[:i] + m.group(0) + t[i:])
EOF
  [ "$(grep -c -- "→ round 2: M=1 C=1" "$f")" = 2 ] || echo "mutant is a no-op: the round was moved rather than copied, so the RVJ lost its own"
fi'

run_mutant "a dep names a phase the tracker does not have" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -q "^## Phase 2 .* · deps: Phase 1 · lane: A$" "$f"; then
  echo "mutant is a no-op: Phase 2s heading is not in the expected shape"
else
  # A typo on a NON-join edge: nothing else about the tracker changes, so only
  # the unresolvable-dep report can kill this.
  sed -i "s|^\(## Phase 2 .*\) · deps: Phase 1 · lane: A$|\1 · deps: Phase 11 · lane: A|" "$f"
  grep -q "^## Phase 2 .* · deps: Phase 11 · lane: A$" "$f" || echo "mutant is a no-op: the dep was not misspelled"
fi'

run_mutant "a bolded gate id hides the gate from the round linter" '
enable_run_dir tools/fixtures/run-rvj-fix || exit 0
f=tools/fixtures/run-rvj-fix/progress.md
if ! grep -qF -- "- [x] RVJ — joint integration review · split 2a+2b" "$f"; then
  echo "mutant is a no-op: the RVJ is not in the expected shape"
else
  python3 - "$f" <<"EOF"
import pathlib, re, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text()
# Bold the id AND drop the round: if `start` stops matching the gate, the
# ownership arm sees no gate at all and the tracker passes.
t = t.replace("- [x] RVJ — joint integration review", "- [x] **RVJ** — joint integration review")
m = re.search(r"(?m)^      → round 2: M=1 C=1.*(?:\n        .*)*\n", t)
assert m, "mutant is a no-op: the round block is not in the expected shape"
p.write_text(t[:m.start()] + t[m.end():])
EOF
  grep -qF -- "- [x] **RVJ** — joint integration review" "$f" || echo "mutant is a no-op: the id was not bolded"
  grep -qF -- "→ round 2:" "$f" && echo "mutant is a no-op: the round survived, so the gate still carries one"
fi'

run_mutant "Current State keeps the retired Next action field" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF -- "- **Lane A:** done (fixture)" "$f"; then
  echo "mutant is a no-op: run-ok is not in the expected done state"
else
  sed -i "s|^- \*\*Lane A:\*\* done (fixture)$|- **Lane A:** done (fixture)\n- **Next action:** none; this run directory is a linter fixture|" "$f"
  grep -qF -- "- **Next action:**" "$f" || echo "mutant is a no-op: the retired field was not inserted"
  grep -qF -- "- **Lane A:** done (fixture)" "$f" || echo "mutant is a no-op: the lane line went too"
fi'

run_mutant "a lane says done while it still contributes to an open join" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- [ ] T3 — a task · W1 · deps T1" "$f"; then
  echo "mutant is a no-op: Phase 3 is not open to begin with"
else
  # LANE B, not Lane A. Lane A owns the joining phase, so `done` there trips the
  # unfinished-own-phase branch instead. Close Lane Bs branch, then say `done`:
  # its own work IS finished, and the only thing wrong is the join it still
  # contributes to.
  python3 - "$f" <<"EOF"
import pathlib, sys
p = pathlib.Path(sys.argv[1]); L = p.read_text().split("\n")
i = L.index("- [ ] T3 — a task · W1 · deps T1")
L[i] = "- [x] T3 — a task · W1 · deps T1 — `ccccccc`"
j = L.index("- [ ] RV — review fan-out", i)
L[j:j+1] = ["- [x] RV — review fan-out · N=1 → 1 slice + 0 integration",
            "      · reports p3-review-a.md · coverage p3-coverage.md → no findings"]
k = L.index("- **Lane B:** Phase 3 — T3")
L[k] = "- **Lane B:** done"
# Lane A is the SURVIVOR and every contributor has now passed, so its own
# legal value stops being `waiting at join` and becomes the gate it owes.
# Without this the mutant kills through the Lane A line instead of the Lane B one.
L[L.index("- **Lane A:** waiting at join Phase 4")] = "- **Lane A:** Phase 4 \u2014 RVJ"
p.write_text("\n".join(L))
EOF
  printf "fixture\n" > tools/fixtures/run-lanes/agent-output/p3-review-a.md
  printf "| report | range |\n| --- | --- |\n| p3-review-a.md | ccccccc^..ccccccc |\n\nCOVERED: 1/1 commits\n" > tools/fixtures/run-lanes/agent-output/p3-coverage.md
  grep -qxF -- "- **Lane A:** Phase 4 — RVJ" "$f" || echo "mutant is a no-op: the surviving lane was not moved to the gate, so a kill could come from its own line"
  grep -qxF -- "- **Lane B:** done" "$f" || echo "mutant is a no-op: Lane B was not set to done"
  grep -qF -- "- [ ] RVJ — joint integration review" "$f" || echo "mutant is a no-op: the leading RVJ closed, so the join is resolved"
fi'

run_mutant "a lane names a phase the tracker does not have" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qxF -- "- **Lane A:** waiting at join Phase 4" "$f"; then
  echo "mutant is a no-op: Lane A is not waiting at the join"
else
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane A:** Phase 41 — T4|" "$f"
  grep -qxF -- "- **Lane A:** Phase 41 — T4" "$f" || echo "mutant is a no-op: the phase id was not changed"
  grep -qxF -- "- **Lane B:** Phase 3 — T3" "$f" || echo "mutant is a no-op: Lane B stopped naming a phase, so a kill could come from the fail-closed arm"
fi'

run_mutant "gitignore hides curated records behind a double star" '
if ! grep -qxF -- "docs/superpowers/runs/*/" .gitignore; then
  echo "mutant is a no-op: the ignore rule is not present to widen"
else
  # `runs/**` matches FILES as well as directories -- measured with
  # git check-ignore -- so it hides the loose curated records while looking
  # like the narrow rule. It must be refused, not blessed.
  # APPENDED, not substituted: replacing the narrow line also trips the
  # missing-rule arm, and the kill would then say nothing about the width
  # check -- which could go on being deleted on a green harness.
  printf "docs/superpowers/runs/**\n" >> .gitignore
  grep -qxF -- "docs/superpowers/runs/**" .gitignore || echo "mutant is a no-op: the wide pattern was not added"
  grep -qxF -- "docs/superpowers/runs/*/" .gitignore || echo "mutant is a no-op: the narrow rule went too, so a kill could come from the missing-rule arm"
fi'

run_mutant "gitignore hides curated records behind a double-star glob" '
if ! grep -qxF -- "docs/superpowers/runs/*/" .gitignore; then
  echo "mutant is a no-op: the ignore rule is not present to widen"
else
  # APPENDED, not substituted: replacing the narrow line also trips the
  # missing-rule arm, and the kill would then say nothing about the width
  # check -- which could go on being deleted on a green harness.
  printf "docs/superpowers/runs/**/*\n" >> .gitignore
  grep -qxF -- "docs/superpowers/runs/**/*" .gitignore || echo "mutant is a no-op: the wide pattern was not added"
  grep -qxF -- "docs/superpowers/runs/*/" .gitignore || echo "mutant is a no-op: the narrow rule went too, so a kill could come from the missing-rule arm"
fi'

run_mutant "gitignore narrows to a single star with no slash" '
if ! grep -qxF -- "docs/superpowers/runs/*/" .gitignore; then
  echo "mutant is a no-op: the ignore rule is not present to change"
else
  # `runs/*` matches FILES too -- git ignores the curated records under it --
  # and the width arm does not name this spelling, so only the accept arm can
  # refuse it. Substituted deliberately: this pins the ACCEPT regex.
  sed -i "s|^docs/superpowers/runs/\*/$|docs/superpowers/runs/*|" .gitignore
  grep -qxF -- "docs/superpowers/runs/*" .gitignore || echo "mutant is a no-op: the pattern was not narrowed"
fi'

# ---- arms the whole-change review found unreached by any mutant ----
run_mutant "run tracker round precedes any review gate" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c -- "→ round 2: M=2 C=1" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one appended round"
else
  python3 - "$f" <<"PYE"
import pathlib, re, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text()
m = re.search(r"(?m)^      \u2192 round 2: M=2 C=1.*(?:\n        .*)*\n", t)
assert m, "mutant is a no-op: the round block is not in the expected shape"
blk = m.group(0)
t = t[:m.start()] + t[m.end():]
i = t.index("## Phase 1")
p.write_text(t[:i] + blk + t[i:])
PYE
  grep -qF -- "→ round 2: M=2 C=1" "$f" || echo "mutant is a no-op: the round block was lost rather than moved"
fi'

run_mutant "run tracker Current State has no lane line at all" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qxF -- "- **Lane A:** done (fixture)" "$f"; then
  echo "mutant is a no-op: run-ok is not in the expected done state"
else
  # ON run-ok, which has no unfinished phase: the fail-closed backstop needs a
  # blocker, so with none the missing-lane-line report stands alone.
  sed -i "\|^- \*\*Lane A:\*\* done (fixture)$|d" "$f"
  grep -qF -- "- **Lane A:**" "$f" && echo "mutant is a no-op: a lane line survived"
  grep -qF -- "## Current State" "$f" || echo "mutant is a no-op: the Current State block went too"
fi'

run_mutant "retired lane id is reused after the join that consumed it" '
enable_run_dir tools/fixtures/run-leading-rvj-fix || exit 0
f=tools/fixtures/run-leading-rvj-fix/progress.md
if ! grep -q "^## Phase 5 .* · lane: A$" "$f"; then
  echo "mutant is a no-op: Phase 5 is not in the expected shape"
else
  # ONE successor, so no fork report; lane B retired at Phase 4 and reappears
  # after it. The reuse report is the only one this can produce.
  printf "\n## Phase 6 — fixture, a resurrected lane · deps: Phase 5 · lane: B\n- [ ] T6 — a task · W1 · deps T5\n- [ ] RV — review fan-out\n" >> "$f"
  grep -q "^## Phase 6 .* · lane: B$" "$f" || echo "mutant is a no-op: the resurrected phase was not appended"
fi'

run_mutant "a join is entered while a contributor still has open work" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qxF -- "- **Lane A:** waiting at join Phase 4" "$f"; then
  echo "mutant is a no-op: Lane A is not waiting at the join"
else
  # Phase 3 stays OPEN and Lane A names the join anyway. Lane B keeps its line,
  # so the contributors-unfinished report is the only one left.
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4$|- **Lane A:** Phase 4 — T4|" "$f"
  grep -qxF -- "- **Lane A:** Phase 4 — T4" "$f" || echo "mutant is a no-op: Lane A did not enter the join"
  grep -qxF -- "- [ ] T3 — a task · W1 · deps T1" "$f" || echo "mutant is a no-op: Phase 3 closed, so the contributor is finished"
fi'

run_mutant "a dep item strips down to nothing" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -q "^## Phase 2 .* · deps: Phase 1 · lane: A$" "$f"; then
  echo "mutant is a no-op: Phase 2s heading is not in the expected shape"
else
  # A NON-JOIN edge, so nothing downstream changes shape: only the
  # unresolvable-dep report can fire. `*` is emphasis markup with no id inside
  # it, and dropping it silently is how a typo disables the join machinery.
  sed -i "s|^\(## Phase 2 .*\) · deps: Phase 1 · lane: A$|\1 · deps: * · lane: A|" "$f"
  grep -q "^## Phase 2 .* · deps: \* · lane: A$" "$f" || echo "mutant is a no-op: the dep was not replaced"
fi'

echo
echo "killed=$PASS survived=$SURV no-op=$NOOP"
if [ "$SURV" -ne 0 ]; then
  printf 'survivors:\n'; printf '  - %s\n' "${SURVIVORS[@]}"
fi
if [ "$NOOP" -ne 0 ]; then
  printf 'no-ops (killed by another arm, so they prove nothing about their own):\n'
  printf '  - %s\n' "${NOOPS[@]}"
fi
if [ "$SURV" -ne 0 ] || [ "$NOOP" -ne 0 ]; then
  echo "check-plugin-mutants: FAIL"; exit 1
fi
echo "check-plugin-mutants: PASS"
