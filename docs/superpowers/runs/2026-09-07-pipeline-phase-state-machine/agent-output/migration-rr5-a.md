# Round-5 re-review — the field's location, the unnormalised comparison, six Minors

Scope: `git diff 95009f7..HEAD` — one commit, `89bb176`. Earlier rounds are not
re-reviewed. Tiers are this skill's three: Critical / Major / Minor.

All probes ran in a `mktemp -d` tar copy of the repo, fixtures reset from a
pristine snapshot before every probe and `tools/check-plugin.py` restored from a
pristine snapshot before every probe. The working tree was untouched:
`git status --porcelain` was empty before and after.

---

## 0. The required gate/harness run, verbatim

```
$ ./tools/check-plugin.sh | tail -2
check-plugin: PASS

$ for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d | tail -1; done
check-plugin: PASS
check-plugin: PASS
check-plugin: PASS

$ ./tools/check-plugin-mutants.sh 2>&1 | tail -6
  killed    run tracker Current State is shadowed by a prose decoy
  killed    run tracker ledger row id is bolded
  killed    run tracker four-column ledger renames its phase column

killed=156 survived=0 no-op=0
check-plugin-mutants: PASS

$ python3 -m unittest discover -s plugins/superb/skills/craft/tests 2>&1 | tail -3
Ran 19 tests in 0.608s

OK
```

`python3 -m py_compile tools/check-plugin.py` → clean.

---

## 1. Question 1 — is each of NEW-F1…NEW-F9 closed?

Every mechanical row was verified **by reversion**: the fix was reverted on a
throwaway copy and the round-4 defect had to come back. Reverts used were
`revert_f1.py` (field located by a whole-tracker search again), `revert_f2.py`
(`_isrow` un-normalised), `revert_f3.py` (`count("|") >= 6` restored on
`_seen_fid`), `revert_f9.py` (label keeps the whitespace it matched),
`revert_multitable.py` (`_tables = _tables[:1]`).

| ID | Closed? | Evidence |
| -- | ------- | -------- |
| NEW-F1 | **yes** | Probe **A1** — line-start decoy `- **Phase:** 2` above the block, real field `- **Phase:** 3`, `F-002` open against Phase 2 → `check-plugin: FAIL` (advancement report). **A1r**, same input with the fix reverted → `check-plugin: PASS`. **A3** (decoy inside the block, *below* the real field) → FAIL. **A4** = round-4's K1 mirror (prose `Phase 3` above a real `Phase 2`) → PASS, so the spurious-FAIL half is gone too. |
| NEW-F2 | **yes** | **B1** `| **F-002** |` advanced to Phase 3 → FAIL; **B1r** reverted → PASS. **B2** `` | `F-002` | `` advanced → FAIL; **B2r** reverted → PASS. **R1/R2** (same decorated ids, *not* advanced) → PASS, so the fix did not turn decoration into a failure. |
| NEW-F3 | **yes** | **E1** 4-column blocking table with `Phase` renamed to `Area`, `F-002` open → FAIL: *"holds 1 `F-` row(s) but no header row naming ID/Sev/Phase/State"*. **E1r** reverted → PASS. Renames also FAIL at 5 (**E2** `State`→`Status`), 7 (**E3** `Phase`→`Area`) and 8 columns (**E4** `Sev`→`Severity`). |
| NEW-F4 | **yes** | Attribution matrix below: `revert_multitable.py` is the *only* revert under which *"run tracker second blocking table gates nothing"* SURVIVES, and it survives under no other. Probe **R4** (table 1 clean, a 4-column second table holding `F-009` open against Phase 2, tracker advanced) → FAIL naming **F-009**; **R5** same ledger not advanced → PASS. |
| NEW-F5 | **yes** | `grep -c "a pinned file becomes unreadable"` → `0` in both `tools/check-plugin.py` and `tools/check-plugin-mutants.sh`, and the `== mutant citations ==` arm is green, so no citation dangles. The comment's hand-verification claim was checked and is **true**: `chmod 000 plugins/superb/skills/pipeline/references/parallel.md` on a copy yields `check-plugin: FAIL` with the pin arm's own line *"pipeline/references/parallel.md cannot be read (…)"* — and, as the comment says, the generic read arm fires as well (2 reports), which is exactly why no mutation isolates it. |
| NEW-F6 | **yes** | **J1** unparseable tracker (`## Phase` → `## Stage` everywhere) with `F-002` open → **exactly 1** run-file FAIL report (round 4 measured 2). **J2a** = round-4's J2 shape (only `**Phase:**` names phase 9) → 1 report, unchanged. |
| NEW-F7 | **yes** | `templates/progress.md:52-56` now says a phase-less field is *"legitimate when nothing is unfinished … reported as uncheckable when something is"*. Measured both legs: **I2** `run-ok` (`- **Phase:** done (fixture)`, nothing unfinished) → PASS; **I1** the same phase-less field on `run-fixloop` (F-002 open) → FAIL *"…the advancement invariant is uncheckable on this tracker"*. Claim matches behaviour. |
| NEW-F8 | **yes** | `_rows += _tbl` is gone; `grep -n '_rows'` shows `_rows` only as the loop variable at `check-plugin.py:2419`/`:2421`. `py_compile` clean; nothing else reads it. |
| NEW-F9 | **yes** | **F1** `## Phase  2` (two spaces) → PASS, **0** reports. **F1r** reverted → FAIL with **4** reports, matching round 4's measurement exactly. Also PASS at `## Phase   2` (**F2**) and `##  Phase 2` (**F3**), and **F4** shows the double-space heading still *gates* when Current State advances. |

**9 of 9 closed.** No row marked closed has a reachable defect.

---

## 2. Question 2 — both directions: the shape battery

Everything the template or the three fixtures write must pass; every advance
past an unfinished phase must fail.

### `**Phase:**` / `**Next action:**` forms

| Probe | Shape | Result |
| ----- | ----- | ------ |
| BASE0-2 | the three fixtures verbatim | 3 × PASS |
| A2 | `- **Phase:** 3 — advanced past the open F-002` over `F-002` open on Phase 2 | correct FAIL |
| A4 | prose `Phase 3` above the block, real field `2` | PASS (no spurious FAIL) |
| G1 | split id: `## Phase 2a`, ledger cell `2a`, `- **Phase:** 2a` | PASS |
| G2 | same, Current State advanced to `3` | correct FAIL (*"later than Phase 2a"*) |
| G3 | `- **Next action:** Phase 2a RV — review fan-out` (`Phase <id>` lead form) | PASS |
| I1 | `- **Phase:** done` with an unfinished phase | correct FAIL (uncheckable) |
| I2 | `- **Phase:** done` with nothing unfinished (`run-ok`) | PASS |
| P4 | fields indented 4 spaces / tab, `*` marker | PASS |
| P7 | `* **Phase:** …` | PASS |
| **Q2** | `**Phase:** 3` with **no bullet**, advanced past open `F-002` | **PASS — new Major RR5-1** |
| **Q3** | `+ **Phase:** 3`, advanced | **PASS — new Major RR5-1** |
| **Q4** | `1. **Phase:** 3`, advanced | **PASS — new Major RR5-1** |
| Q1 | control: `- **Phase:** 3`, advanced | correct FAIL |
| F1-F4 | heading spacing `## Phase  2` / `   2` / `##  Phase 2` | PASS, PASS, PASS; still gates (F4) |
| H1 | `- [x] RV — review fan-out · WAIVED by user: "skip it"` closing Phase 3 | PASS |

### Ledger widths, names and row ids

| Probe | Shape | Result |
| ----- | ----- | ------ |
| C1 | 4 columns, correct names, `F-002` open, not advanced | PASS, ledger half live (no `_ledger_note`) |
| C2 / C3 / C4 | 5 / 7 (template) / 8 columns (extra column inserted before `Sev`) | PASS, PASS, PASS |
| D1 / D2 / D3 | the same 4 / 7 / 8-column tables with Current State advanced | correct FAIL ×3 |
| E1 / E2 / E3 / E4 | a renamed column at 4 / 5 / 7 / 8 columns | correct FAIL ×4 (unparseable-header report) |
| R1 / R2 | `| **F-002** |` and `` | `F-002` | ``, not advanced | PASS, PASS |
| B1 / B2 | the same two, advanced | correct FAIL ×2 |
| R3 | bolded `**Major**` + capitalised `Open` + `Phase 2` cell, advanced | correct FAIL |
| R4 / R5 | second blocking table (4-col) holding `F-009` open; advanced / not | correct FAIL / PASS |
| R6 | a row one cell **wider** than its 7-column header | correct FAIL (*"row 'F-002' has 8 cells but its header has 7"*) |
| **S1** | open row with id `N-002` (non-`F-` prefix), advanced | **PASS — new Major RR5-2** |
| **S2** | open row with id `F-002a` (split-suffixed), advanced | **PASS — new Major RR5-2** |

Every shape the template or a fixture prescribes passes, and every one of them
still gates. Two shapes that are *not* template-prescribed produce a silent
PASS over an open blocking finding — RR5-1 and RR5-2 below.

---

## 3. Question 3 — probing the new Current State block isolation

`_cs = ttext.split("## Current State", 1)`, bounded by `re.split(r"^##\s", …)`,
then `re.search(r"^\s*[-*]\s*\*\*<field>:\*\*\s*(.+)", _csblock, re.M)`.

| Probe | Input | Result |
| ----- | ----- | ------ |
| P1 | **no `## Current State` heading at all**, fields kept, `F-002` open | FAIL — but through *"neither Current State field names a phase"*, whose REMEDY (*"name the phase in `**Phase:**`"*) is wrong: the field exists and names phase 2. Misdiagnosis. |
| P1b | same, fields advanced to `3` | FAIL, same misdiagnosis (the advance itself is never named) |
| P1c | same, nothing unfinished (`run-ok`) | **PASS, silently** — a tracker with no Current State block at all draws no report |
| P2 | **two** `## Current State` headings, first a decoy naming `3` | correct FAIL — the first block wins, which is the top-of-file block the template mandates |
| P2b | two headings, real block first, a second one **appended** naming `3` | **PASS** — the later block is ignored and its existence unreported (**new Minor RR5-4**) |
| P3 / P3b | `### Current State` (h3) — the split key is a substring of it | PASS, and still gates when advanced (P3b FAIL). Lenient but sound. |
| P4 | fields indented differently (4 spaces, tab, `*`) | PASS |
| P6 | decoy `- **Phase:** 3` **inside** the block, above the real `2` | FAIL — first match inside the block wins; template puts `Phase` first |
| A3 | decoy `- **Phase:** 2` inside the block, **below** the real `3` | correct FAIL |
| **P5** | prose above the heading quoting `` `## Current State` `` inline | **FAIL on an otherwise conforming tracker** — the un-anchored split key steals the block (**new Minor RR5-3**) |
| P5b | the same inline mention with Current State advanced | FAIL, but via the misdiagnosis branch, not the advancement branch |

---

## 4. Question 4 — regressions and dead ends

### `parse_tracker_phases`' new label form

`cur["label"] = f"Phase {mh.group(1).strip()}"` is normalised at capture. Every
consumer was checked: `_idx` (`:2321`), the ledger lookup `_idx.get(f"phase {_phl}")`
(`:2450`), `_named_phase`'s `_idx.get(f"phase {…}".lower())` (`:2522`), and two
message-only uses (`:2261`, `:2344`). All build `phase <id>` with one space and
lowercase, so all four agree. The heading regex `r"##\s+Phase\s+([^\s—·]+)"`
still refuses `### Phase 2` (`\s+` cannot match `#`), and `parse_tracker_phases`
has exactly one call site (`:2207`). No stale consumer.

### Removing `_rows`

`_rows` now exists only as the `for _hdr, _rows in _tables` loop variable.
`py_compile` clean; no other reader; the shadowing NEW-F8 named is gone.

### Do the six newest mutants each kill through their own arm?

Baseline, the six newest filtered out of the harness on a clean copy:
`killed=6 survived=0 no-op=0`. Then one fix reverted at a time, all six run:

| Revert applied | Survivor | Cross-kills |
| -------------- | -------- | ----------- |
| `revert_f1.py` (field location) | *run tracker Current State is shadowed by a prose decoy* | none (`killed=5 survived=1`) |
| `revert_f2.py` (`_isrow` un-normalised) | *run tracker ledger row id is bolded* | none |
| `revert_f3.py` (width filter on `_seen_fid`) | *run tracker four-column ledger renames its phase column* | none |
| `revert_multitable.py` (first table only) | *run tracker second blocking table gates nothing* | none |

Exactly one survivor per revert, no co-kills. NEW-F4's co-kill is genuinely
closed, and the two new ledger mutants are attributable.

**But the decoy mutant pins a conjunction, not either leg.** Measured with
partial reverts: dropping **only** the block isolation (`_csblock` → `ttext`,
line-start bullet kept) → mutant **killed**; dropping **only** the line-start
bullet requirement (block isolation kept) → mutant **killed**. Either half of
the NEW-F1 fix can be deleted and the harness stays green. That is **new Minor
RR5-5**, the same class as NEW-F4/NEW-F5. Its cause is the decoy's shape: the
mutant writes `A prose line mentioning - **Phase:** 2 above the block.`, which
is not a line-start list item, so the line-start rule alone suffices to reject
it.

### The round-5 mutant guards

The repaired second-table mutant closes table 1's own row first with
`sed -i "s@a fixture finding still open | open @… | closed @"` and then guards
`grep -qE "^\| F-002 .*\| open \|"` — the guard reports a no-op if the close did
not take. All three new mutants carry preconditions; `no-op=0` on the full run,
so none is silently inert.

---

## 5. Question 5 — the spec's four invariants

| Invariant | Status |
| --------- | ------ |
| **1. Advancement** — `PASS` is the only edge into `NEXT PHASE`; implementation complete is not phase complete; an empty ledger is not phase complete | **The open-blocking-F-ID leg now holds for every shape the templates and fixtures prescribe** — which is the leg round 4 said did not hold. All three of round 4's defeats (NEW-F1 unanchored field, NEW-F2 decorated row id, NEW-F3 4-column rename) are shut and each is pinned by an attributable mutant; the tracker legs (open task, open `RV`/`RVJ`, no `RV`, missing fix plan) continue to hold. It is **still defeated by two off-grammar shapes**: a `**Phase:**` field written without a `-`/`*` bullet (RR5-1, a round-5 regression) and a blocking row whose ID cell is not exactly `F-<digits>` (RR5-2, pre-existing). Both were measured as `check-plugin: PASS` with `ok Current State does not point past an unfinished phase` over `F-002 … open` against Phase 2. |
| **2. Review ownership** | **Holds.** Untouched this round; `== pipeline has no task-level review ==` green, mutants killed. |
| **3. Completing an implementation task dispatches no reviewer** | **Holds.** Untouched; sweep and mutants green. |
| **4. Integration reviewer conditional on a declared boundary** | **Holds.** Untouched by this diff except the pin comment; *run tracker boundary declares a bare dash* and *the conditional integration rule reverts in templates/progress.md* both killed and attributable. |

**Answering directly: invariant 1's open-blocking-F-ID leg holds for the
prescribed grammar, and round 4's three named defeats are gone.** It does not
hold universally: two off-grammar shapes still reach a silent PASS, and one of
them is new this round.

---

## 6. New findings

### RR5-1 — Major — `tools/check-plugin.py:2499-2504` (`_named_phase`)

```python
            m = re.search(r"^\s*[-*]\s*\*\*" + field + r":\*\*\s*(.+)",
                          _csblock, re.M)
```

Round 5 narrowed the field locator from "anywhere in the tracker" to "a `-` or
`*` list item inside the Current State block". Three markdown-legal forms of the
same field are now **silently unreadable**, and the arm falls back to
`**Next action:**` alone with no report — so a `**Phase:**` field that openly
names a later phase gates nothing whenever `**Next action:**` still names the
earlier one, which is exactly the state the existing mutant *"run tracker
Current State phase advances while Next action does not"* exists to prove.

Measured on `run-fixloop` (`F-002` `Major` `open` against Phase 2,
`**Next action:**` left naming Phase 2's fix loop):

```
### Q2 '**Phase:** 3' NO BULLET advanced, Next action still Phase 2  -> check-plugin: PASS
     ok    Current State does not point past an unfinished phase
### Q3 '+ **Phase:** 3' plus-bullet advanced                        -> check-plugin: PASS
### Q4 '1. **Phase:** 3' numbered-list advanced                     -> check-plugin: PASS
### Q1 CONTROL '- **Phase:** 3' advanced                            -> check-plugin: FAIL
```

**This is a regression introduced by this commit.** The pre-round-5 locator read
all three: probes **T1** (no bullet) and **T2** (`+` bullet) with
`revert_f1.py` applied both come back `check-plugin: FAIL`. Round 5 traded
NEW-F1's decoy hole for a bullet-form hole — the pattern the ledger's own round-3
note describes ("each fix added a heuristic with a new gap").

**Fix (measured, both directions).** Keep the line anchor, make the marker
optional, and — the structural half — *report* a `**Phase:**` field the arm
cannot locate, so the next locator bug is a loud failure instead of a silent
pass:

```python
        _csm = re.search(r"^##\s+Current State\s*$(.*?)(?=^##\s|\Z)",
                         ttext, re.M | re.S)
        _csblock = _csm.group(1) if _csm else ""
        _fieldre = r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?\*\*%s:\*\*"
        if _phs and not re.search(_fieldre % "Phase", _csblock, re.M):
            bad(f"{relpath(tracker)}: no `**Phase:**` field inside a "
                "`## Current State` block — that field is where the "
                "advancement check reads the run's position, so it read "
                "nothing and compared nothing. REMEDY: keep the Current State "
                "block at the top, as `templates/progress.md` ships it")
```
and `re.search(_fieldre % field + r"\s*(.+)", _csblock, re.M)` in
`_named_phase`. Suppress the `elif _blockers and not _named` branch when that
new report fires, so one defect draws one diagnosis.

I applied exactly this on a throwaway copy and measured it:

```
### U0  fixloop unmodified   -> PASS      ### U1 no-bullet advanced      -> FAIL
### U0b run-ok unmodified    -> PASS      ### U2 numbered advanced       -> FAIL
### U0c run-open-rv unmod.   -> PASS      ### U3 NEW-F1 decoy above blk  -> FAIL
### U5 inline-mention prose  -> PASS      ### U4 no Current State block  -> FAIL
                                              (named: "no `**Phase:**` field inside a
                                               `## Current State` block")
```

so it closes RR5-1, RR5-3 and the P1 misdiagnosis without reopening NEW-F1 and
without failing any prescribed shape. Add a mutant *"run tracker Current State
Phase field loses its bullet"* over Q2's shape.

### RR5-2 — Major — `tools/check-plugin.py:2407-2409` (`_isrow`)

```python
            _isrow = lambda ln: bool(
                re.match(r"\|?\s*f-\d+\s*\|", _norm(ln)))
```

Row-ness requires the id to be exactly `F-` plus digits. An open blocking row
whose ID cell is anything else is dropped from the table walk **and** from
`_seen_fid`, so — precisely NEW-F2's failure mode on a different decoration of
the same cell — nothing is printed at all:

```
### S1 open blocking row with id 'N-002', advanced to Phase 3   -> check-plugin: PASS
     ok    Current State does not point past an unfinished phase
### S2 open blocking row with id 'F-002a', advanced to Phase 3  -> check-plugin: PASS
```

Reachability is not hypothetical: **this run's own `findings.md` uses `N-001…`,
`NEW-01…` and `NEW-F1…` ids across three of its four ledgers**, and the
template ships split *phase* ids (`3a`, `4a`), which invite `F-002a` for a
finding raised against one. Every such row is ungated, silently. It also makes
the round-5 comment's own claim — *"Row-ness is 'the first cell is an F-id'"* —
narrower than it reads.

This one is **pre-existing** (the `F-\d+` shape predates round 5), so it is not
a regression; it is reported here because round 5 rewrote this exact expression
and restated its contract.

**Fix.** Make row-ness "the first cell looks like a finding id", so an
off-grammar id is *read or reported*, never dropped:

```python
            _isrow = lambda ln: bool(
                re.match(r"\|?\s*[a-z]{1,6}-\d+[0-9a-z.]*\s*\|", _norm(ln)))
```
and state the id grammar in `templates/findings.md` beside the header grammar it
already pins. Add a mutant *"run tracker ledger row id is not `F-<n>`"* over
S1's shape.

### RR5-3 — Minor — `tools/check-plugin.py:2496`

`ttext.split("## Current State", 1)` is a plain substring split, not
line-anchored. Any prose **above** the heading that quotes the heading text
inline captures the block, and `_csblock` becomes the text between that mention
and the real heading — which holds no fields. Measured on an otherwise
conforming `run-fixloop`:

```
### P5 prose above the heading quoting '`## Current State`'  -> check-plugin: FAIL
     FAIL  …/progress.md: Phase 2 has open blocking finding F-002 (major), and neither
           Current State field names a phase … REMEDY: name the phase in `**Phase:**`
```

This is a **false failure**, the direction the ledger's round-2 lesson calls
worse operationally than a missed hole — it can gate a real run whose tracker
preamble merely quotes the heading it is describing (all three fixtures carry
such preamble prose). No template writes the string inline today, which is why
this is Minor rather than Major.

**Fix.** The anchored `re.search(r"^##\s+Current State\s*$(.*?)(?=^##\s|\Z)", ttext, re.M | re.S)`
in RR5-1's patch; measured as **U5 → PASS**. Note it also drops the `###`
leniency P3 exercised, which is a tightening, not a loss.

### RR5-4 — Minor — `tools/check-plugin.py:2496`

A **duplicated** `## Current State` heading is unreported. First-match-wins is
the right precedence (the template mandates the block at the very top), but an
executor that *appends* a fresh block instead of editing the top one leaves the
gate reading a stale position and printing `ok`:

```
### P2b TWO headings, real first, second naming Phase 3  -> check-plugin: PASS
     ok    Current State does not point past an unfinished phase
```

**Fix.** After locating the block, count line-start headings and report more
than one: `if len(re.findall(r"^##\s+Current State\s*$", ttext, re.M)) > 1: bad(…)`
— "two Current State blocks, and the gate reads the first; the run's position
must live in exactly one place." Pin with a mutant that appends the second block.

### RR5-5 — Minor — `tools/check-plugin-mutants.sh:2060` (*"run tracker Current State is shadowed by a prose decoy"*)

The mutant kills under either half of the NEW-F1 fix being present, so neither
half is individually held. Measured with partial reverts:

```
=== PARTIAL REVERT: block isolation only removed  ===  killed  (…prose decoy)
=== PARTIAL REVERT: bullet requirement only removed === killed  (…prose decoy)
=== FULL REVERT (both) ===                              SURVIVED (…prose decoy)
```

Cause: the decoy is written as `A prose line mentioning - **Phase:** 2 above the block.`,
which is not a line-start list item, so the line-start rule alone rejects it and
the block-scoping is never exercised. Same class as NEW-F4/NEW-F5: a mutant that
certifies a conjunction and pins neither term.

**Fix.** Write the decoy as a genuine line-start list item above the heading
(`Reminder:\n- **Phase:** 2 — fix loop, F-002 open\n`), which pins the block
isolation alone — verified: probe **A1** is exactly that shape and it FAILs with
the fix and PASSes under `revert_f1.py`. If RR5-1's fix drops the bullet
requirement, that single mutant is then sufficient and correctly attributed.

### RR5-6 — Minor — `tools/check-plugin.py:2545-2565`

When **both** Current State fields name a phase the tracker does not have, one
defect draws three reports and the third is false — it says *"neither Current
State field names a phase"* when both do, and its REMEDY sends the author to
`**Phase:**`, which is already filled in:

```
### J2 both fields name nonexistent phase 9 -> run-file FAIL reports: 3
     FAIL  … Current State's `**Phase:**` names phase '9', which matches no `## Phase` heading …
     FAIL  … Current State's `**Next action:**` names phase '9', which matches no `## Phase` heading …
     FAIL  … Phase 2 has open blocking finding F-002 (major), and neither Current State field names a phase …
```

(Round 4's J2 changed one field only and measured 1 report — probe **J2a**
reproduces that, so this is a shape round 4 did not reach, not a regression.)
This is NEW-07/NEW-F6's complaint on its third site.

**Fix.** Gate the `elif _blockers and not _named` branch on neither field having
been *readable*: track `_ph_seen`/`_na_seen` (the second tuple element
`_named_phase` already returns and the round-3 fix dropped as unused) and skip
the branch when a field was read but named a phase the tracker lacks — that case
is already reported on its own.

---

## 7. Convergence assessment

**The ledger half has converged.** Rounds 1-5 hammered it; round 5's changes to
it (`_isrow` normalised, width filter removed) introduced **no** new gap of
their own — I probed 4/5/7/8-column tables, correct and renamed names at each
width, bolded/backticked/plain ids in both directions, a wider-than-header row,
and two blocking tables, and every result landed on the intended side. RR5-2 is
pre-existing, one line, and mechanically fixable. Both new ledger mutants are
attributable with no co-kills. I would ship this half.

**The Current State field reader has not converged.** Five rounds, five
different ways the *locator* has been wrong: N-001 required the literal word
"phase" in the value; NEW-01 searched the value instead of anchoring it; NEW-F1
anchored the token but not the field; round 5 anchored the field and over-fitted
its bullet (RR5-1). Every fix tightened the locator and every tightening opened
a new blind spot, for one structural reason: **the arm has no "I could not read
this field" report**, so any locator mistake degrades into a silent pass rather
than a loud failure. Round 5's own `_csblock` addition is the fourth locator
heuristic in four rounds, and RR5-3/RR5-4 are two more shapes it does not
handle.

So the honest answer to "did this converge, or will these arms keep producing
findings": **the arm will keep producing findings for as long as an unreadable
field is silent.** The fix that ends it is not another locator tweak — it is the
five-line report in RR5-1, which I measured closing RR5-1, RR5-3 and the P1
misdiagnosis at once while leaving every prescribed shape passing. After that
change the locator's exact regex stops being load-bearing: a future mistake in
it produces a build failure naming the field, not an `ok` line.

**Would I ship it?** Not as it stands: RR5-1 is a silent pass over an open
blocking finding that this commit created, in the arm the whole branch exists to
build, and the cap allows one more iteration. Ship it after iteration 5 makes
the one structural change plus RR5-2's one-line widening; the four Minors are
cheap and belong in the same pass. Of the six new findings, **RR5-3 is the only
one that can gate a real run** (a false FAIL on a tracker whose preamble quotes
the heading); RR5-1 and RR5-2 are the opposite failure — they let a run through.

**A note for iteration 5, given the cap.** Both new Majors are one-expression
changes and I have measured the fix for each, in both directions, on a throwaway
copy. There is no design question left open here — which is the difference
between this round and rounds 1-3.

---

## 8. Probe index

Probes ran in a `mktemp -d` copy; `tools/check-plugin.py` and all three fixtures
were restored from a pristine snapshot before each probe. Working tree untouched
(`git status --porcelain` empty before and after).

| Probe | What | Result |
| ----- | ---- | ------ |
| BASE0-2 | the three fixtures, unmodified | 3 × PASS |
| A1, A1r | NEW-F1 line-start decoy above the block, with / without the fix | FAIL / PASS |
| A2, A3, A4 | advance control; decoy below the real field; round-4 K1 mirror | FAIL, FAIL, PASS |
| B1, B1r, B2, B2r | bolded / backticked row id, with / without the NEW-F2 fix | FAIL/PASS, FAIL/PASS |
| C1-C4 | conforming ledgers at 4, 5, 7, 8 columns | 4 × PASS, ledger half live |
| D1-D3 | the same at 4, 7, 8 columns, advanced | 3 × correct FAIL |
| E1, E1r, E2-E4 | renamed column at 4 (± NEW-F3 fix), 5, 7, 8 columns | FAIL/PASS, 3 × FAIL |
| F1, F1r, F2-F4 | `## Phase  2` / `   2` / `##  Phase 2`, and gating | PASS (0 reports) / FAIL (4 reports), PASS, PASS, FAIL |
| G1-G3 | split id `2a` end-to-end, advanced, `Next action` lead form | PASS, FAIL, PASS |
| H1 | `WAIVED by user:` `RV` form | PASS |
| I1, I2 | phase-less field with / without an unfinished phase | correct FAIL / PASS |
| J1, J2, J2a | unparseable tracker; both fields name phase 9; one field does | 1 report / **3 reports (RR5-6)** / 1 report |
| P1, P1b, P1c | no `## Current State` heading: fields kept, advanced, nothing unfinished | FAIL (misdiagnosed), FAIL (misdiagnosed), **PASS** |
| P2, P2b | two headings, decoy first / real first | correct FAIL / **PASS (RR5-4)** |
| P3, P3b | `### Current State`, and gating | PASS / correct FAIL |
| P4, P6, P7, P8 | indented fields; in-block decoy above; `*` marker; no marker | PASS, FAIL, PASS, PASS |
| P5, P5b | inline `## Current State` in prose above the heading | **FAIL (RR5-3)** / FAIL (misdiagnosed) |
| Q1-Q4 | `- ` control; no bullet; `+ `; `1. ` — all advanced | FAIL, **PASS, PASS, PASS (RR5-1)** |
| R1-R6 | decorated ids not advanced; bold/`Open`/`Phase 2` cell; second table ±; over-wide row | PASS, PASS, FAIL, FAIL, PASS, FAIL |
| S1, S2 | open row with id `N-002` / `F-002a`, advanced | **PASS, PASS (RR5-2)** |
| T1, T2 | Q2/Q3 shapes against the **pre-round-5** locator | FAIL, FAIL (regression proven) |
| T3-T5 | block-isolation-only variant: no bullet, numbered, NEW-F1 decoy | FAIL, FAIL, FAIL |
| U0-U5 | the candidate RR5-1 fix over 3 fixtures + 5 shapes | 3 PASS + 1 PASS, 4 correct FAIL |
| ATTR ×4 | one fix reverted at a time, six newest mutants run | 1 survivor each, no co-kills |
| ATTR-P ×2 | partial reverts of the NEW-F1 fix | both **killed (RR5-5)** |
| CHMOD | `chmod 000 references/parallel.md` (the deliberately-unpinned branch) | FAIL, branch reports, 2 arms fire — comment's claim true |

---

VERDICT: FINDINGS MUST BE FIXED
