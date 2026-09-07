# Migration re-review — round 2, reviewer A

**Scope:** the fix diff only — `git diff 7699cc8..HEAD` (3 commits: `da34392`
plus two ledger-doc commits `ac8dbe3`/`f526c3b`; 16 files, ~1716 insertions).
`main..7699cc8` was round 1 and is not re-reviewed here.

**Tiers:** Critical / Major / Minor. No `Important` is emitted.

**Bottom line:** 21 of 24 findings are resolved and verified. Three are only
partially resolved — **F-007** and **F-002**, whose original defects are still
reachable on measured inputs, and **F-022**, whose negation list is not
exhaustive. Two of the fixes also introduced false failures against the
skill's own shipped templates.

---

## 1. Verification — the commands, and their real output

### `./tools/check-plugin.sh`

```
$ ./tools/check-plugin.sh | tail -3
  ok    96 cited mutant names all defined in check-plugin-mutants.sh

check-plugin: PASS
```

### The three run-mode fixtures

```
$ for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d | tail -1; done
check-plugin: PASS
check-plugin: PASS
check-plugin: PASS
```

### The mutation harness

```
$ ./tools/check-plugin-mutants.sh 2>&1 | tail -6
  killed    run tracker phase carries no RV line at all
  killed    run tracker ledger row bolds its severity
  killed    run tracker Current State phase advances while Next action does not

killed=144 survived=0 no-op=0
check-plugin-mutants: PASS
```

Exit code 0. `survived=0` and `no-op=0` verbatim.

### The craft unit tests

```
$ python3 -m unittest discover -s plugins/superb/skills/craft/tests 2>&1 | tail -3
Ran 19 tests in 0.547s

OK
```

Every required command is green. **The findings below are all things the green
harness does not see.**

---

## 2. My own probes

Method: each probe `tar`s the working tree into a fresh `mktemp -d`, applies one
named mutation inside the copy, and runs `./tools/check-plugin.sh --run <fixture>`
there. The working tree was never modified. Probe driver:
`$SCRATCH/probe.sh <name> <fixture> <script>`. Where a probe's mutation script
could itself be a no-op, I verified the mutated file's text before trusting the
result — one of my first attempts (P22, first run) *was* a silently-inapplied
no-op and reported a false PASS, which is worth recording as a reminder that
this is the exact failure class F-020 is about.

| # | Probe | Result | Reading |
|---|-------|--------|---------|
| P1 | conforming ledger with **reordered columns** (`State` moved before `Sev`), `Next action` advanced to Phase 3 | **FAIL** (correct) | header-driven lookup handles reordering |
| P2 | ledger header **recapitalised** (`\| id \| SEV \| Phase \| FILE:LINE \| finding \| State \| closed by \|`), tracker untouched | **PASS** (correct) | no false failure from casing |
| P2b | same recapitalised header **+** `Next action` advanced | **FAIL** (correct) | the row is still read through the odd header |
| P12 | ledger **bolds `Sev`** (`**Major**`), **capitalises `Open`**, writes **`Phase 2`** in the Phase cell; `Next action` advanced | **FAIL** (correct) | the three shapes F-001 named are caught |
| P13 | ledger gains an **extra column** in header *and* rows; `Next action` advanced | **FAIL** (correct) | width-consistent extra column is read fine |
| **P6** | the shipped `templates/findings.md` shape: a **Deferred-Minor row** `\| F-003 \| 2 \| \`src/c.py:5\` \| a deferred minor \|` appended under the 7-column blocking header | **FAIL** — *false failure* | **N-003** |
| **P9** | ledger header names **`Area`** instead of `Phase` (the shape this run's own `findings.md` uses) | **FAIL** (reported, not dropped) | correct behaviour; documentation gap only — see N-007 |
| P10 | **F-002**: Phase 2's `RV` line deleted outright, `Next action` advanced to Phase 3 | **FAIL** (correct) — `…still has no review line at all…` | the headline F-002 defect is closed |
| **P23** | **F-002 × F-004 interaction**: Phase 3 is a joining phase whose **only** review line is a **leading `RVJ`**; its own `RV` line deleted, `T6` `[x]`, Current State advanced | **PASS** — *defect reachable* | **N-002** |
| P22 | **F-004**: the leading `RVJ` block moved **below** `T6` (trailing `RVJ` over open work) | **FAIL** (correct) — `Phase 3's RVJ is [x] while 1 task line(s) … are not [x]` | placement rule works in both directions |
| P11 | **F-003**: phase headings demoted to `### Phase` | **FAIL** (correct), 2 arms fire | no-subject arm works |
| P4 | round keyed **`M` with `C=` absent** | **FAIL** (correct) | pre-existing arm intact |
| P5 | `Current State` names **`Phase 9`**, which does not exist | **FAIL** (correct, but by the *neither-field* arm) | see N-006 |
| P14 | **F-005**: appended fix round keyed `N=2` | **FAIL** (correct) | round-mark keying works |
| P15 | **F-006**: appended round written `→ round 2: C=1 → 1 slice + 0 integration` (no `N=`/`M=`) | **FAIL** (correct) | the `continue` bypass is closed |
| P16b | **F-021**: `M=0 → no round · fixplan p3-fixplan-r2.md · closures: …` | **FAIL** (correct) | arm works |
| P17 | **F-022**: `· boundary: none` with `i=1` | **FAIL** (correct) | |
| P18 | **F-022**: `· boundary: n/a` with `i=1` | **FAIL** (correct) | |
| **P19** | **F-022 escape**: `· boundary: nothing crosses between the slices` with `i=1` | **PASS** — *escape* | **N-005** |
| **P20** | **F-022 escape**: `· boundary: not applicable` with `i=1` | **PASS** — *escape* | **N-005** |
| P21 | **F-023**: CI step rewritten to `--run tools/fixtures/run-fixloop-2` | **FAIL** (correct) | exact-step match works |
| **P7** | **F-007**: `- **Phase:** 3 — moved on` (the form `templates/progress.md` prescribes) while `Next action` still names Phase 2's fix loop, Phase 2 holding `F-002` open | **PASS**, printing `ok Current State does not point past an unfinished phase` — *defect reachable* | **N-001** |
| P7b | the same tracker written `- **Phase:** Phase 3 — moved on` (the redundant form the new mutant writes) | **FAIL** | shows the arm only reads the redundant form — N-001 evidence |
| **P8** | both Current State fields written exactly as the template prescribes: `- **Phase:** 2 — fix loop` + `- **Next action:** RV — review fan-out` | **FAIL** — *false failure* | **N-004** |

Probes P7 / P7b are the decisive pair, and their real output was:

```
$ sed -i 's|^- \*\*Phase:\*\*.*|- **Phase:** 3 — moved on|' tools/fixtures/run-fixloop/progress.md
$ grep -n "Phase:\*\*\|Next action:\*\*" tools/fixtures/run-fixloop/progress.md
24:- **Phase:** 3 — moved on
25:- **Next action:** Phase 2 fix loop round 3 — write the round's fix plan for F-002
$ ./tools/check-plugin.sh --run tools/fixtures/run-fixloop | grep "Current State\|FAIL\|check-plugin:"
  ok    Current State does not point past an unfinished phase
check-plugin: PASS

$ sed -i 's|^- \*\*Phase:\*\*.*|- **Phase:** Phase 3 — moved on|' tools/fixtures/run-fixloop/progress.md
$ ./tools/check-plugin.sh --run tools/fixtures/run-fixloop | grep "Current State\|FAIL\|check-plugin:"
  FAIL  tools/fixtures/run-fixloop/progress.md: Current State names a phase later than Phase 2, which still has open blocking finding F-002 (major) — …
check-plugin: FAIL
```

And P23, the F-002 × F-004 interaction, verbatim:

```
## Phase 3 — fixture, a joining phase, not started · deps: Phase 2
- [x] RVJ — joint integration review · lanes A+B · N=5 → 0 slice + 1 integration
      · reports p3-rvj-int.md · coverage p3-rvj-coverage.md → no findings
- [x] T6 — a task · W1 · deps T4 — `fffffff`

  ok    3 phases (6 task lines), none with a review round opened while one of its own tasks was unchecked
check-plugin: PASS
```

Phase 3 is implemented, has no `RV` of its own, and is not a blocker.

---

## 3. Per-finding table

| F-ID | Sev (r1) | Verdict | Evidence |
|------|----------|---------|----------|
| F-001 | Critical | **resolved** | header-driven lookup at `tools/check-plugin.py:2260-2306`. All four measured shapes caught: bolded `Sev` + capital `Open` + `Phase 2` cell (P12), extra column (P13), reordered columns (P1), recapitalised header (P2b). Report-not-drop confirmed (P9). Mutant `run tracker ledger row bolds its severity` killed. **But see N-003** — the new width check false-fails the shipped template. |
| F-002 | Major | **partially resolved** | `tools/check-plugin.py:2240-2243` makes a phase with no review line a blocker — P10 FAILs correctly, mutant `run tracker phase carries no RV line at all` killed. **The test is "has any review line", so a leading `RVJ` satisfies it** and a joining phase with no `RV` still reads as complete (P23 PASS). → **N-002**. |
| F-003 | Major | **resolved** | `if not _phs: bad(...)` at `:2140-2145` — P11 FAILs, mutant `run tracker phases are demoted below the parser` killed. Bullet regex at `:2062` now accepts `**T5**` and `T2.1`. Minor cosmetic issue: N-008. |
| F-004 | Major | **resolved** | placement rule at `:2171-2180`. Leading `RVJ` passes (`run-open-rv` green), trailing `RVJ` over open work FAILs (P22). Mutant `run tracker opens a trailing RVJ over unfinished work` killed. F-024 supplies the conforming input. |
| F-005 | Major | **resolved** | `if kind == "round" and d.group("key") != "M"` at `:1657` — P14 FAILs; mutant `run tracker fix round is keyed N instead of M` present and killed. |
| F-006 | Major | **resolved** | exemption narrowed to `"WAIVED by user:" in rec` at `:1447`; P15 FAILs. I verified the waived grammar is spelled `WAIVED by user:` in all four sites that ship it (`SKILL.md:309`, `:1096`, `references/run-state.md:54`, `templates/progress.md:72`), so the narrowing raises no false failure. |
| F-007 | Major | **NOT resolved** | `_named_phase` at `:2335-2342` requires the literal word `phase` *inside the field value*. `templates/progress.md:10` prescribes `- **Phase:** <current phase number and name>` — a bare number — so the `**Phase:**` field is never read on a conforming tracker. **P7 reproduces reviewer B's P8 measurement exactly and still PASSes.** → **N-001**, and its mirror **N-004**. The new mutant only writes `**Phase:** Phase 3`, a shape no template produces → **N-009**. |
| F-008 | Major | **resolved** | `references/fix-loop.md:65-76` — the phase REVIEW bullet now reads "Add **one integration reviewer only at a declared integration boundary**", with the `i=0` / `no integration boundary` branches spelled out. |
| F-009 | Major | **resolved** | `SKILL.md:1032-1038` and `references/fix-loop.md:612-615` both now defer to `references/fix-loop.md`'s *Re-review fan-out* table as the authority. Prose is unpinned by any sweep — N-007. |
| F-010 | Major | **resolved** | `references/parallel.md:119-131`: step 7 now repairs inside IMPLEMENT ("raises no finding, takes no F-ID, needs no fix plan and spends no iteration budget"), and the conflict note records the bad `Files:` annotation as a note for the phase review instead of a ledger entry. |
| F-011 | Major | **resolved** (prose) | `SKILL.md:671-675` restated as "an implementer for every task of every phase, then that phase's review fan-out and any fix rounds it opens". Verified the retired sentence is gone. No sweep pattern pins the replacement — N-007. |
| F-012 | Major | **resolved** | one `<skill-dir>` form in all three sites (`templates/implementer-prompt.md:23`, `references/parallel.md:94-96`, `references/implement.md:74-86`), plus a declared `Skill directory:` payload slot at `templates/implementer-prompt.md:12-14` and an Ambiguity-guard stop if it cannot be resolved. The remaining repo-relative citations are in `tools/` only (`check-plugin.py:1877`, `check-plugin-mutants.sh:1636/1643/1650`), where they are correct. |
| F-013 | Minor | **resolved** | `references/run-state.md:227` adds the partially-implemented row, correctly placed **above** the `RV [ ]` row so precedence resolves it first. |
| F-014 | Minor | **resolved** | `SKILL.md:573` — `Stage 4b` now edges to `Stage 4 PASS` on `clean`; only GATE 2 and `PASS` reach `IMPLEMENT`. |
| F-015 | Minor | **resolved** | `references/fix-loop.md:336-337` names `FIX_PLAN → FIX_IMPLEMENT → RE_REVIEW`. |
| F-016 | Minor | **resolved** | `references/fix-loop.md:381-386` — "`M=0` is not 'a round that edited code and needs no plan': it is a round with **no ownable fix commit at all**". Content correct; the edit broke the list indentation — N-010. |
| F-017 | Minor | **resolved** | grepped `tools/check-plugin.py` for every inverted phrasing (`one additional integration`, `whenever there is more than one slice`, `integration reviewer once there is more than one`): zero hits. `:1993-1994` and `:1516` state the conditional form. |
| F-018 | Minor | **resolved** | `SKILL.md:984-990` states the reviewer tier at the fan-out. |
| F-019 | Minor | **resolved** | `tools/check-plugin-mutants.sh:1602-1618` now grows the report set to `{a,b,int,int2}`, writes the new report file, appends the coverage row and guards the boundary — so only the at-most-one-integration arm can object. Killed. |
| F-020 | Minor | **resolved** | `tools/check-plugin-mutants.sh:29-49`. Detection is sound: `out` captures **only the mutation script's own** stdout+stderr (`out="$( ( cd "$dir" && eval "$script" ) 2>&1 )"`), not `check-plugin.sh`'s, so a gate message can never trigger it. I audited every mutant body for a path by which legitimate output could contain the literal `mutant is a no-op`: only two mutants read `tools/check-plugin-mutants.sh` (`:992`, `:1293`) and both use `grep -q`/`grep -qF`, printing nothing. No mutant `cat`s, `diff`s or non-quiet-greps a file holding that string. A no-op that also survives is reported `SURVIVED` with its output, which still fails the harness. `no-op=0` observed. |
| F-021 | Minor | **resolved** | `:1402-1405`; P16b FAILs. |
| F-022 | Minor | **partially resolved** | `:1547-1554` catches `none`, `n/a`, `no <word>`, `-` (P17, P18). It does **not** catch `not applicable` (P20 PASS) or `nothing crosses …` (P19 PASS). → **N-005**. |
| F-023 | Minor | **resolved** | `:1151-1158`; P21 FAILs. |
| F-024 | Minor | **resolved** | `tools/fixtures/run-open-rv/progress.md:47-49` carries a leading `RVJ` with `p3-rvj-int.md` and `p3-rvj-coverage.md` in `agent-output/`; the fixture is green and is the input P22 mutates. |

**Totals: 21 resolved, 3 partially resolved (F-002, F-007, F-022), 0 unresolved.**

---

## 4. New findings

### N-001 — Critical — `**Phase:**` is unreadable in the form the template prescribes, so F-007's measured defect still passes

`tools/check-plugin.py:2339`

```python
g = re.search(r"[Pp]hase\s+([0-9A-Za-z.]+)", m.group(1))
```

`_named_phase(field)` locates `**<field>:**` and then requires the literal word
`phase` **inside the field's value**. For `**Next action:**` that is fine, since
a next action is normally written `Phase 2 RV — …`. For `**Phase:**` it never
holds: `templates/progress.md:10` prescribes
`- **Phase:** <current phase number and name>`, and all three fixtures write it
that way (`**Phase:** 2 — implemented, unreviewed`, `**Phase:** 2 — fix loop, …`,
`**Phase:** done (fixture)`). No conforming tracker writes `**Phase:** Phase 2`.

So the F-007 fix reads the `**Phase:**` field only when it redundantly repeats
the word — and reviewer B's measured P8 (`**Phase:** 3 — moved on` while Phase 2
holds `F-002` open) still passes, printing the affirmative
`ok Current State does not point past an unfinished phase` (P7 above). This is
the resume protocol's *first* field: an orchestrator that advances `Phase:` and
leaves a stale `Next action` behind advances with the gate green, which is the
defect F-007 named, verbatim, unchanged.

The findings row for F-007 says "both Current State fields read; naming no phase
now fails". Half of that is not true on any conforming input.

**Fix:** make the phase reference optional in `_named_phase`, and try the bare
form when the keyed form is absent:

```python
def _named_phase(field):
    m = re.search(r"\*\*" + field + r":\*\*\s*(.+)", ttext)
    if not m:
        return None, False
    val = m.group(1)
    g = (re.search(r"[Pp]hase\s+([0-9A-Za-z.]+)", val)
         or re.match(r"\s*([0-9]+[0-9A-Za-z.]*)\b", val))
    if not g:
        return None, True
    return _idx.get(f"phase {g.group(1)}".lower()), True
```

Then **retarget the mutant**: `run tracker Current State phase advances while
Next action does not` at `tools/check-plugin-mutants.sh:1928` must write
`- **Phase:** 3 — moved on`, not `- **Phase:** Phase 3 — moved on`, and must
guard that the bare form landed. The arm is worth nothing until a mutant fails
through it on the shape a real tracker holds.

---

### N-002 — Critical — a leading `RVJ` satisfies F-002's "has a review line" test, so a joining phase with no `RV` still reads as reviewed

`tools/check-plugin.py:2240-2243`

```python
if not _ph["reviews"]:
    _why.append("no review line at all — …")
```

The F-004 fix established, correctly and in the linter's own comment at `:2158`,
that a **leading** `RVJ`'s subject "is the lanes that merged into this phase,
not this phase's own tasks". The F-002 fix then counts that same leading `RVJ`
as *this phase's* review. The two fixes read the same `parse_tracker_phases`
output and disagree about what a leading `RVJ` covers.

Measured (P23): `tools/fixtures/run-open-rv` Phase 3 with `T6` marked `[x]` and
its own `- [ ] RV` line deleted — a joining phase implemented and never
reviewed — produces
`ok 3 phases (6 task lines), none with a review round opened …` and
`check-plugin: PASS`. Phase 3 is not in `_blockers` at all, so Current State may
advance past it freely.

This violates the spec's advancement invariant directly
(`docs/superpowers/specs/2026-09-07-pipeline-phase-state-machine-design.md:168-180`:
a phase reaches `PASS` only when "its `RV` line is `[x]` carrying its per-round
evidence"). And it is the exact vacuity class F-002 was raised for — narrowed
from "any phase" to "any joining phase", which the fix plan's own standard
("a fix that merely narrows such a hole is not a fix") rejects.

**Fix:** require an `RV` specifically, and let a *trailing* `RVJ` stand in for
it — which is consistent with F-004's placement semantics:

```python
_first_task = min((x[2] for x in _ph["tasks"]), default=None)
_own = [r for r in _ph["reviews"]
        if r[0] == "RV" or (_first_task is not None and r[2] > _first_task)]
if not _own:
    _why.append("no review line of its own — an implementation phase ends "
                "with an `RV` (or a trailing `RVJ`); a leading `RVJ` reviews "
                "the lanes that merged in, not this phase's tasks, so it "
                "cannot close this phase")
if any(r[1] != "x" for r in _own):
    _why.append("an open RV/RVJ line")
```

Add a mutant: `run tracker joining phase closes on its leading RVJ alone` —
`run-open-rv` Phase 3 with `T6` `[x]` and its own `RV` deleted — guarded so a
kill can only come from this arm.

---

### N-003 — Major — F-001's row-width check false-fails the shipped `templates/findings.md`

`tools/check-plugin.py:2298-2306`

The width check requires every line matching `^\s*\|\s*F-\d+\s*\|` to have
exactly the blocking header's cell count. But `templates/findings.md` ships a
**second** table whose rows begin with an F-ID and are deliberately narrower —
the *Deferred Minor findings (Stage 5 hand-off)* table:

```
| ID | Phase | File:line | Finding |
| -- | ----- | --------- | ------- |
| F-004 | 2 | `src/z.php:88` | <one line> |
```

Four cells against the blocking header's seven. Measured (P6):

```
  FAIL  tools/fixtures/run-fixloop/findings.md: row 'F-003' has 4 cells but its
        header has 7 — …
```

`tools/fixtures/run-fixloop/findings.md` happens to ship that table **empty**,
which is the only reason the fixture is green. Every real run that defers a
single Minor finding — the normal outcome of any review — now fails the gate,
with a message that tells the author to widen a row the template says should be
narrow. Reviewer B's *"an unreadable row must not read as a closed one"* is
right; the row is simply not part of the blocking ledger.

**Fix:** bound the scan to the blocking table rather than the whole file. Track
the header's line index, and stop at the next blank-line-terminated table or the
next `##` heading:

```python
_lines = _ltext.split("\n")
_hi = next((i for i, ln in enumerate(_lines)
            if {"id", "sev", "phase", "state"}
            <= set(_norm(c) for c in ln.strip().strip("|").split("|"))), None)
...
for _line in _lines[_hi + 1:]:
    if _line.strip().startswith("#") or not _line.strip().startswith("|"):
        break            # the blocking table ended
    ...
```

Then add the deferred row to `tools/fixtures/run-fixloop/findings.md` so the
happy path actually carries the shape, and a mutant that widens/narrows a row
**inside** the blocking table so the width arm still has its own kill.

---

### N-004 — Major — F-007's fix fails a template-conforming Current State whenever any phase is unfinished

`tools/check-plugin.py:2352-2358` (the `elif _blockers and not _named:` arm),
same root cause as N-001

Because `**Phase:**` can never resolve (N-001), the whole arm rests on
`**Next action:**`. `templates/progress.md:11` defines that field as
`<the single next unchecked line — task, RV, or RVJ>` — a form that need not
name a phase at all. Write both fields exactly as the template prescribes and
the gate fails (P8):

```
- **Phase:** 2 — fix loop
- **Next action:** RV — review fan-out

  FAIL  tools/fixtures/run-fixloop/progress.md: Phase 2 has open blocking
        finding F-002 (major), and neither Current State field names a phase —
        so there is nothing to compare it against …
```

Mid-run there is always an unfinished phase, so this fires on the ordinary case.
It is the same failure mode as F-004 — an arm failing the legal shape the
skill's own templates prescribe — and it pressures a real run into rewriting its
tracker to satisfy the linter rather than the grammar.

**Fix:** N-001's patch resolves it (the bare `**Phase:** 2` then resolves and
`_named` is non-empty). If the `not _named` arm is kept, it must additionally
demand that `templates/progress.md` prescribe a phase-naming `Next action` —
otherwise the linter and the template disagree, and the template is authority.

---

### N-005 — Minor — F-022's negation list is not exhaustive

`tools/check-plugin.py:1552-1553`

```python
not re.search(r"boundary:\s*(?!(?:none|n/?a|no\b|-\s*$))\S", rec, re.I)
```

`none`, `n/a`, `no <word>` and `-` are caught (P17, P18). Two natural spellings
of the same declared absence are not:

- `· boundary: not applicable` → **PASS** (P20) — `no\b` needs a word boundary
  after `no`, and `n/?a` cannot match `not`.
- `· boundary: nothing crosses between the slices` → **PASS** (P19).

Either lets one round license the integration reviewer *and* declare there is
nothing for it to cover — F-022's defect exactly.

**Fix:** invert the test. Require a boundary to *look like a boundary* rather
than enumerating negations:

```python
_b = re.search(r"boundary:\s*(.+)", rec, re.I)
_named_b = bool(_b) and not re.match(
    r"(?:none|n/?a|no\b|not\s+applicable|nothing\b|-\s*$)", _b.group(1).strip(),
    re.I)
```

and add a mutant per rejected spelling (`not applicable`, `nothing crosses`).

---

### N-006 — Minor — two dead flags, and a nonexistent phase in Current State is caught only by accident

`tools/check-plugin.py:2344-2345`

`_na_present` and `_ph_present` are computed and never read. The information
they carry — "the field exists but names nothing this gate can resolve" — is
exactly what would distinguish *no field* from *a field naming `Phase 9`*. As
written, `Current State` naming a phase that does not exist (P5) fails only
because `_named` ends up empty **and** a blocker happens to exist; with every
phase complete the same tracker passes in silence.

**Fix:** use them. When a field is present, names something, and does not
resolve through `_idx`, `bad(...)` on that fact — the ledger arm already does
precisely this for an unmatched Phase cell at `:2318-2325`, so the two halves of
this arm would then agree.

---

### N-007 — Minor — the four prose corrections are unpinned, so F-008…F-011 can silently rot back

`tools/check-plugin.py:1926-1938`

Round 1's F-011 observed that "no sweep pattern matches it". The fix corrected
the sentence but added **no pattern**. I checked the `_banned` list: it holds
five patterns (`per-task review`, `passed task review`, `task reviewer`,
`reviewed per task`, `implement … via subagent-driven-development`) and none of
them matches the phrasings F-008…F-011 were about — `"every task takes an
implementer, a reviewer"`, `"one additional integration reviewer"`,
`"integration reviewer once there is more than one"`. Grepping the linter for
those phrasings returns nothing, so nothing outside the worked *examples* (which
`lint_review_lines` does read) keeps the retired rule from being re-written in
prose. By the skill's own rule in `templates/findings.md` — "**A rewrite is not
a closure**: the corrected sentence is still unexecuted" — these four close by
deletion of the wrong claim but leave the failure mode reachable.

Separately, the header-label requirement N-003 touches is now load-bearing and
undocumented: the arm demands the exact labels `ID`/`Sev`/`Phase`/`State`, and
this run's own `docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine/findings.md`
uses `Area` in place of `Phase`, which the arm would report (P9).

**Fix:** add two `_banned` patterns —
`re.compile(r"one additional integration reviewer", re.I)` and
`re.compile(r"integration reviewer once there is more than one", re.I)` — plus
one that matches the retired cost model (`r"every task takes an implementer,\s*a reviewer"`),
each with a mutant that re-inserts the retired sentence. And state the required
ledger header labels in `templates/findings.md` beside the table.

---

### N-008 — Minor — the no-subject arm still prints an affirmative pass line

`tools/check-plugin.py:2140-2145` then `:2360-2361`

When `_phs` is empty the arm correctly `bad(...)`s, but execution continues:
`_blockers` stays empty, `_named` stays empty, and the final `else` prints
`ok no unfinished phase in the tracker` — an affirmative claim about a file the
gate just said it could not parse. P11's output carries both lines. The run
fails overall, so this is cosmetic, but it is the same "pass line asserting what
was not checked" pattern that the same comment block warns against at `:2136`.

**Fix:** guard the two arms — `if _phs:` around the blockers/Current-State
block, or `elif not _phs: pass` before the final `else`.

---

### N-009 — Minor — the new Current-State mutant proves the arm over a shape no template writes

`tools/check-plugin-mutants.sh:1928`

```bash
sed -i "s|^- \*\*Phase:\*\*.*|- **Phase:** Phase 3 — moved on|" "$f"
```

The mutant is killed, and the ledger cites that kill as evidence F-007 is
closed. But it writes the doubled form `**Phase:** Phase 3`, which is the only
form the arm can read (N-001) and which no template or fixture produces. So the
kill is attributable to a shape that cannot occur, and the arm it certifies does
nothing on the shape that can. Covered by N-001's fix; recorded separately
because the *mutant* is the thing that made a hole look watched.

---

### N-010 — Minor — F-016's edit breaks the numbered list it sits in

`plugins/superb/skills/pipeline/references/fix-loop.md:381-387`

The inserted paragraph is written flush-left inside a 3-space-indented list
item, and the original sentence then resumes on a line beginning with a single
space:

```
   **Unless `M=0`.** `M=0` is not "a round that edited code and needs no plan":
it is a round with **no ownable fix commit at all**, …
that you should not.
 `M` does not size the fan-out — the fix diff does
   (*Re-review fan-out*, below) — but it still decides …
```

The dedent terminates list item 3's paragraph, so the correction renders as an
orphan block and ` \`M\` does not size the fan-out` reads as a dangling
fragment. Content is right; the file the executor is sent to now renders wrong.

**Fix:** indent the inserted paragraph to 3 spaces and rejoin
`` `M` does not size the fan-out `` to the sentence it belongs to.

---

## 5. Spec conformance and the two retired rules

- **Advancement invariant** (`…-design.md:168-180`): **violated** by N-002 — a
  joining phase reaches `NEXT PHASE` without an `RV` line of its own. The other
  clauses hold: open task (P10-adjacent), open `RV`/`RVJ`, open blocking F-ID
  (P12/P13), and named-but-missing fix plan all block.
- **`PASS` is the only edge into `NEXT PHASE`**: held — `SKILL.md:573` now
  routes `Stage 4b` through `PASS` (F-014).
- **Completing an implementation task dispatches no reviewer**: held — the
  no-task-review sweep (`tools/check-plugin.py:1925-1958`) is green, and I
  confirmed the fix diff touched none of its patterns. Nothing in the diff
  reintroduces task-level review; `references/parallel.md` step 6/7 now both
  repair build-gate failures inside IMPLEMENT.
- **No unconditional integration reviewer**: held in the linter (`:1516`,
  `:1547-1554`, `:1993-1994`) and now in the four prose sites too (F-008, F-009,
  F-017). Grep for every retired phrasing returns zero hits. The prose is
  unpinned — N-007.
- **`Current State` gate as the spec's table states it** (`…-design.md:302`):
  **only half held** — N-001. The spec says "`Current State` naming a later
  phase … fails"; on a conforming tracker only `Next action` is ever read.

### Fix interaction summary (question 3)

| Combination | Behaviour | Correct? |
|---|---|---|
| leading `RVJ`, phase has open tasks | F-004 exempts, no early-review report | yes |
| trailing `RVJ`, phase has open tasks | F-004 fires | yes |
| leading `RVJ` **and** a closed `RV`, all `[x]` | no blocker | yes |
| **leading `RVJ` only, no `RV`, all `[x]`** | **no blocker** | **no — N-002** |
| no review line at all, tasks `[x]` | blocker | yes |
| `_phs` empty (demoted headings) | `bad`, but a stray `ok` follows | mostly — N-008 |
| ledger row unmatched to a phase | `bad` (`:2318`) | yes |
| ledger header unmatched | `bad` (`:2278`) | yes |
| ledger row narrower than header (deferred table) | `bad` | **no — N-003** |

---

## 6. Recommended round-2 fix scope

Two clusters, `C=2`:

1. `tools/check-plugin.py` — N-001, N-002, N-003, N-004, N-005, N-006, N-008
   (all in the run-mode block plus `:1552`), with `tools/fixtures/run-fixloop/findings.md`
   gaining a deferred-Minor row.
2. `tools/check-plugin-mutants.sh` — N-009 (retarget), plus the four new mutants
   N-001/N-002/N-003/N-005 require, and `plugins/superb/skills/pipeline/references/fix-loop.md`
   + `tools/check-plugin.py:1926` for N-007/N-010.

Every one of the seven arms above must fail on a conforming-but-wrong input
before it is believed — which is what this round's own findings show the first
attempt did not establish.

---

VERDICT: FINDINGS MUST BE FIXED
