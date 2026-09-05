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
# flattened text names the term. It asserts the mutation rather than the prose's
# shape — the deletion must remove a paragraph, and the term must be gone
# afterwards. Reword the rule and the mutant refuses loudly with its message
# printed instead of turning into a silent no-op.
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

echo
echo "killed=$PASS survived=$SURV"
if [ "$SURV" -ne 0 ]; then
  printf 'survivors:\n'; printf '  - %s\n' "${SURVIVORS[@]}"
  echo "check-plugin-mutants: FAIL"; exit 1
fi
echo "check-plugin-mutants: PASS"
