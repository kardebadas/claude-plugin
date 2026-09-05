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
# bullet in *Re-review fan-out* and the `M=0 → no round` condition on the fix
# loop's step 3. Deleting either reinstates the contradiction the rule removed —
# a fan-out demanding an owner for a diff the rule excluded, or a step 3
# mandating a round the rule says never happens — and before the CLAIM_EFFECT
# arm both deletions were green.
#
# Each mutant asserts the phrase it targets is present BEFORE (or it is a no-op
# on prose that already rotted) and gone AFTER, and that the OTHER consequence
# survived — so the kill is attributable to the phrase named in the mutant's own
# name and cannot be borrowed from its sibling. Backticks are built with
# chr(96): a literal one inside this double-quoted shell argument would be
# command substitution.
run_mutant "M-exclusion bullet deleted from fix-loop.md" "$J \"import pathlib
p=pathlib.Path('plugins/superb/skills/pipeline/references/fix-loop.md')
s=p.read_text(); nl=chr(10); bt=chr(96); key='not counted in '+bt+'M'+bt
assert key in s, 'mutant is a no-op: the M-exclusion bullet is already absent'
L=s.split(nl); at=[i for i,x in enumerate(L) if key in x]
assert len(at)==1, 'mutant is a no-op: the phrase is on more than one line, so deleting one bullet no longer removes it'
i=at[0]; j=i+1
while j<len(L) and L[j].startswith('  '): j+=1
del L[i:j]
out=nl.join(L)
assert key not in out, 'mutant is a no-op: the bullet deletion left the phrase behind'
assert 'M=0 ' in out, 'mutant is a no-op: it removed the no-round condition too, so a kill would not be attributable to the M-exclusion bullet'
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
