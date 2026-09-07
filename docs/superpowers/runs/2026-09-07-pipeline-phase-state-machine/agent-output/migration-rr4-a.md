# Round-4 re-review — the strict-grammar fix

**Scope:** `git diff a104d78..HEAD` — one commit, `95009f7`
*"fix(pipeline): tighten the grammar so the parser can shrink"*.
6 files, +781/−74. Earlier rounds are **not** re-reviewed.

**Authorities used for "conforming":**
`plugins/superb/skills/pipeline/templates/progress.md` and
`plugins/superb/skills/pipeline/templates/findings.md` (both changed by this
commit), plus the three shipped run fixtures.

**Method.** Every probe ran on a `mktemp -d` tar-copy of the repo
(`$W = …/scratchpad/probe.24KP`) with the fixture tree reset from a pristine
copy before each probe. The working tree was never modified:
`git status --porcelain` is empty at the start and end of this review. Four of
the probes are *reversion tests*: the round-4 fix is undone in the copy and the
matching new mutant is applied, to establish whether the mutant kills through
its own arm or through a neighbour's.

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
  killed    run tracker boundary declares a bare dash
  killed    the conditional integration rule reverts in templates/progress.md
  killed    a pinned file becomes unreadable

killed=154 survived=0 no-op=0
check-plugin-mutants: PASS

$ python3 -m unittest discover -s plugins/superb/skills/craft/tests 2>&1 | tail -3
Ran 19 tests in 0.488s

OK
```

Every declared gate is green. The findings below are all things a green gate
does not see.

---

## 1. Question 1 — is each of NEW-01…NEW-07 closed?

| ID | Sev (r3) | Closed? | Evidence |
| -- | -------- | ------- | -------- |
| NEW-01 | Critical | **closed** | Probe I1 writes the exact reported shape `- **Phase:** 3 — moved on past the phase 2 fix loop` with `- **Next action:** RV — review fan-out`. Now `FAIL … Current State names a phase later than Phase 2, which still has open blocking finding F-002 (major)`. Reversion TEST 4 (restore the `re.search` → `re.match` fallback pair) makes the same input **PASS**, so the anchoring is the thing doing the work. |
| NEW-02 | Critical | **closed for the shipped shape; a narrower legitimate shape still slips** — see NEW-F3 | Probe E1 renames `Phase`→`Area` on the shipped 7-column table: `FAIL … holds 2 F- row(s) but no header row naming ID/Sev/Phase/State`. Probe E3 renames `State`→`Status`: same FAIL. Reversion TEST 3 (`_seen_fid` reads `_rows` again) makes E1 **PASS**, so the whole-file scan is load-bearing. But probe E2 (same rename on a 4-column blocking table) **PASSes** past an open Major. |
| NEW-03 | Major | **closed** | Probe F1 builds a second blocking table with a *different* (4-column) header holding `F-009 Critical … 1 … open`, with table 1 all-closed and Current State at Phase 2. Result: `FAIL … names a phase later than Phase 1, which still has open blocking finding F-009 (critical)`. The row was read through the **second** table's own `_ci`, so per-table header attribution is right. Its *mutant* is co-killed — NEW-F4. |
| NEW-04 | Minor | **closed, both directions** | Probe set H on `run-ok`: `boundary: -` FAIL, `boundary: —` FAIL, `boundary: none` FAIL, `boundary: n/a` FAIL, `boundary: not applicable` FAIL, `boundary: nothing crosses between the slices` FAIL; `boundary: seam` **PASS** (the one-word case the round-3 negative result said must pass), `boundary: notification queue drained in slice b` **PASS** (the `not`-prefixed word that a naive `\b` list would eat). Reversion TEST 5 (old regex) makes `boundary: -` PASS. |
| NEW-05 | Minor | **closed** | `chmod 000 plugins/superb/skills/pipeline/references/parallel.md` in the copy now yields the pin arm's own line: `FAIL  pipeline/references/parallel.md cannot be read ([Errno 13] …), so the pin on "only at a declared integration boundary" checked nothing there.` Its *mutant* is co-killed — NEW-F5. |
| NEW-06 | Minor | **closed** | `templates/progress.md` holds the pinned phrase once when flattened (`only at a DECLARED integration boundary`, `templates/progress.md:60-61`), and is in `_pinned`'s file list (`check-plugin.py:1906`). Reversion TEST 6 (drop the file from the list, then apply its mutation) → **PASS**, so the mutant is correctly attributed. |
| NEW-07 | Minor | **closed for the Current-State half only** — see NEW-F6 | Probe J1 (`## Phase ` → `## Stage `, Current State naming phase 3) no longer emits the two Current-State "matches no heading" lines; the unparseable-tracker arm owns the case. Probe J2 (parseable tracker, `**Phase:** 9`) emits exactly one report. Both dead flags are gone (`check-plugin.py:2476-2477` slices `[0::2]`). But J1 still emits a *second* diagnosis from the ledger half. |

**Count: 7 of 7 closed as written.** Two closures (NEW-02, NEW-07) are partial in
a way that matters and is reported below as new findings rather than as a
re-opened row, because the defect each now reaches is a different shape from the
one the row names.

---

## 2. Question 2 — BOTH DIRECTIONS: does the strict grammar reject legitimate input?

This was the priority, and it is the part of the round that came out **clean**.
Nothing the skill's own files prescribe now fails.

### 2a. `**Phase:**` — every form the template allows or a fixture writes

| Probe | Field value | Expected | Result |
| ----- | ----------- | -------- | ------ |
| A1 | `2 — fix loop, F-002 still open after round 2` (`run-fixloop`, verbatim) | PASS | **PASS** |
| A2 | `3 — fix loop, F-002 open` (the template's own worked example, `templates/progress.md:47-48`) placed on a tracker where Phase 2 is blocked | FAIL | **FAIL**, correctly, naming Phase 2 |
| A3 | `2` (bare id, no prose) | PASS | **PASS** |
| A4 | `Phase 2 — fix loop` (word-introduced) | PASS | **PASS** |
| A5 | `2 - fix loop` (ASCII hyphen instead of em dash) | PASS | **PASS** |
| A6 | `2: fix loop` (colon separator) | PASS | **PASS** |
| — | `done (fixture)` / `none; this run directory is a linter fixture` (`run-ok:109-110`) | PASS | **PASS** — both fields name no phase; `run-ok` has no blocker, so the arm reports `ok no unfinished phase in the tracker (this run's ledger contributed no readable blocking row …)`. See NEW-F7 for the template claim this falsifies. |
| — | `2 — implemented, unreviewed` + `Phase 2 RV — review fan-out over the phase branch` (`run-open-rv:30-31`) | PASS | **PASS** |

### 2b. `findings.md` with extra columns beyond the four pinned names

The template's new paragraph sanctions this explicitly: *"add columns if you need
them, and give every row the same width as the header."*

| Probe | Shape | Result |
| ----- | ----- | ------ |
| D1b | 8th column `Owner` appended to header, separator and every `F-` row | **PASS** |
| D2 | a column `Owner` **inserted between `ID` and `Sev`** (so every pinned column shifts) | **PASS** — header-driven `_ci` handles it |
| D3 | minimal 4-column table, exactly the four pinned names | **PASS** |
| D4 | the same 4-column table with `F-002 … open` and Current State at Phase 3 | **FAIL**, correctly, naming Phase 2 — so a 4-column table is not merely tolerated, it *gates* |

(An earlier attempt, D1, FAILed — mis-designed probe: my `sed` widened the header
without inserting the row separator, producing genuine 7-cells-under-an-8-cell-header
rows. The width arm reported it correctly. D1b is the corrected probe.)

### 2c. A split phase id (`4a`)

| Probe | Shape | Result |
| ----- | ----- | ------ |
| B1 | heading `## Phase 2a — …`, ledger `Phase` cells `2a`, `**Phase:** 2a — …`, `**Next action:** Phase 2a fix loop round 3 …` | **PASS** |
| B2 | same, but Current State advanced to Phase 3 | **FAIL**: `… names a phase later than Phase 2a, which still has open blocking finding F-002 (major)` |

Both the reader (`[0-9]+[0-9A-Za-z.]*`) and the ledger's `Phase` cell carry the
split id end-to-end.

### 2d. The `WAIVED` `RV` form

| Probe | Shape | Result |
| ----- | ----- | ------ |
| G1 | `run-fixloop` Phase 1's `RV` replaced by `- [x] RV — review fan-out · WAIVED by user: "we already reviewed this by hand"` (`templates/progress.md:81`), reports/coverage continuation dropped | **PASS** |

The narrowed `d is None` exemption (`check-plugin.py:1456`) is untouched by this
round and still admits exactly this form.

### 2e. A phase heading with unusual spacing

| Probe | Shape | Result |
| ----- | ----- | ------ |
| C1 | `##  Phase 2 — …` (two spaces after `##`) | **PASS** |
| C3 | `## Phase 2` (no em dash, no name) | **PASS** |
| C2 | `## Phase  2 — …` (two spaces **between** `Phase` and the id) | **FAIL**, 4 spurious reports — NEW-F9 |

### 2f. Verdict on question 2

**No shape that `templates/progress.md`, `templates/findings.md` or any of the
three fixtures prescribes now fails.** Round 2's mistake (over-correcting into a
false failure on conforming input) was not repeated. The one false rejection
found (C2 / NEW-F9) is a whitespace variant no template writes, it fails **loudly**
rather than silently, and it is pre-existing — `_idx` has never collapsed
internal whitespace in a heading label.

The parser genuinely did shrink: the phase reader is one anchored `re.match`
where it was a `search`-then-`match` pair, and the boundary arm lost a clause
that could never run.

---

## 3. Question 3 — is the strictness enforced where it is claimed?

### `templates/findings.md:24-31` — *"a renamed column turns into a build failure and not a silently ungated finding"*

**Only for some shapes, and the exception is a shape the same paragraph
sanctions.** The report is gated on `_seen_fid`, and `_seen_fid`
(`check-plugin.py:2382-2384`) only counts `F-` rows with
`_norm(ln).count("|") >= 6` — i.e. **5 or more cells**.

| Probe | Blocking table | Header renamed | Result |
| ----- | -------------- | -------------- | ------ |
| E1 | 7 columns (as shipped) | `Phase`→`Area` | **FAIL** — claim holds |
| E3 | 7 columns | `State`→`Status` | **FAIL** — claim holds |
| E4 | 5 columns | `Phase`→`Area` | **FAIL** — claim holds (this pins the threshold) |
| E2 | **4 columns** — the exact minimum the paragraph blesses | `Phase`→`Area` | **PASS**, over `F-002 … open` against Phase 2 with `**Phase:** 3` |

E2's full advancement-arm output:

```
  ok    Current State does not point past an unfinished phase (this run's ledger contributed no readable blocking row, so the ledger half of that established nothing)
check-plugin: PASS
```

So: the claim is true for a blocking table of 5+ columns and **false for a
4-column one**. That is NEW-F3.

### `templates/progress.md:47-53` — *"the advancement check reads the phase this line NAMES, and it reads it as the leading token"*

**True, and verified in both directions** (probe set A, plus reversion TEST 4).
The regex is anchored with `re.match`, the optional `Phase ` introducer is the
only thing allowed before the id, and a later mention in the same sentence is
ignored.

**But the sentence that follows it is not true:** *"A field that does not begin
with a phase id names no phase, and the gate reports that rather than guessing
which number was meant."* The gate does not report it. `_named_phase` returns
`None` and the only report path (`check-plugin.py:2490`) requires
`_id is not None`. `tools/fixtures/run-ok` ships exactly that shape in both
fields and passes with an affirmative `ok` line. That is NEW-F7.

### The un-anchored leg the round did not close

The round anchored the *value* of the field. It did not anchor the *location* of
the field: `check-plugin.py:2456` is `re.search(… , ttext)` over the **whole
tracker**, so the first `**Phase:**` anywhere in the file wins, and no arm
requires the `## Current State` block to be first (grepped: no such check
exists). That is NEW-F1, and it is the one finding here I would not merge over.

---

## 4. Question 4 — did anything regress?

### 4a. The re-indented row loop, `_ci` scoping, second-table attribution

**All three correct.**

* Nesting: `for _hdr, _rows in _tables:` (`:2394`) wraps `for _line in _rows:`
  (`:2396`), which wraps the width check, the `state`/`sev` filters and the
  phase lookup. The block is indented 2 spaces under a 12-space `else:` —
  inconsistent with the file's 4-space convention but syntactically and
  semantically correct.
* `_ci` is recomputed per table from that table's own header (`:2395`), so a
  narrow second table is not read with a wide first header's offsets.
* Attribution measured: probe **F1** put `F-009 | Critical | 1 | open` in a
  4-column second table under a 7-column first table, closed `F-002`, and left
  Current State at Phase 2. Result:
  `FAIL … Current State names a phase later than Phase 1, which still has open
  blocking finding F-009 (critical)`. Correct severity, correct phase, read
  through the second header.
* `_lrows` accumulates across all tables, which is what `_ledger_note` wants.
* One real regression-adjacent nit: `_rows += _tbl` (`:2380`) is now a **dead
  assignment** — `_rows` is rebound by the loop at `:2394` before any read, and
  the accumulated value is never used. It also shadows the loop variable.
  NEW-F8.

### 4b. Do the six new mutants each kill through their own arm?

Measured by reverting each fix in a copy and re-applying that mutant's mutation.
A properly attributed mutant **survives** (gate PASSes) once its own fix is gone.

| New mutant | Fix reverted | Gate after reversion + mutation | Attributed? |
| ---------- | ------------ | ------------------------------- | ----------- |
| `run tracker Current State names a mentioned phase` | NEW-01 anchoring | **PASS** | **yes** |
| `run tracker ledger header renames its phase column` | NEW-02 `_seen_fid` whole-file scan | **PASS** | **yes** |
| `run tracker second blocking table gates nothing` | NEW-03 multi-table walk (`break` restored) | **FAIL** — `… later than Phase 2, which still has open blocking finding F-002 (major)` | **no** — co-killed by the *first* table |
| `run tracker boundary declares a bare dash` | NEW-04 boundary regex | **PASS** | **yes** |
| `the conditional integration rule reverts in templates/progress.md` | NEW-06 pin file list | **PASS** | **yes** |
| `a pinned file becomes unreadable` | NEW-05 report-not-`continue` | **FAIL** — `plugins/…/parallel.md: [Errno 13] Permission denied` from a *different* arm | **no** — co-killed by the generic read arm |

Four of six are sound. Two are F-019's exact defect class (a mutant co-killed by
a neighbouring arm proves nothing about its own): NEW-F4 and NEW-F5.

*Housekeeping check on the `chmod 000` mutant:* it runs last, mutates only the
`$WORK/m` tar-copy, and the real tree's mode bits are unaffected —
`-rw-r--r-- … references/parallel.md` after the full harness run, and
`git status --porcelain` empty.

### 4c. Two holes the round's own claims say should be closed, and are not

Both are silent affirmatives past an open blocking finding, i.e. the single
outcome this migration exists to make impossible.

* **NEW-F1** — the `**Phase:**` field is read from anywhere in the file.
* **NEW-F2** — the ledger's *row-detection* regex is the one place `_norm` is
  not applied, so a `| **F-002** |` or `` | `F-002` | `` row is silently skipped
  and is not counted by `_seen_fid` either.

---

## 5. Question 5 — do the spec's four invariants hold?

| Invariant | Status |
| --------- | ------ |
| **1. Advancement** — `PASS` is the only edge into `NEXT PHASE`; implementation complete is not phase complete; an empty ledger is not phase complete | **Still not fully gated.** The tracker legs (open task, open `RV`/`RVJ`, no `RV` at all, missing fix plan) hold. The **open-blocking-F-ID leg** is materially better than round 3 — all three of round 3's holes (NEW-01/02/03) are shut and two of them are properly pinned — but it is **still defeated three ways**: NEW-F1 (the field read is not anchored to the Current State block), NEW-F2 (a markup-decorated row id is dropped in silence), NEW-F3 (a renamed column on a 4-column blocking table is dropped in silence). Each was measured as a `check-plugin: PASS` with `ok Current State does not point past an unfinished phase` over `F-002 … open` against Phase 2 and `**Phase:** 3`. |
| **2. Review ownership** — no agent plans, implements, reviews and fixes at once | **Holds.** Untouched this round; `== pipeline has no task-level review ==` green, its mutants killed. |
| **3. Completing an implementation task dispatches no reviewer** | **Holds.** Untouched this round; sweep and mutants green. |
| **4. The integration reviewer is conditional on a declared boundary** | **Holds, and now stated where it is enforced.** NEW-04 shuts `boundary: -`/`—` (probe H) without breaking the one-word case; NEW-06 pins `templates/progress.md`'s statement of the rule with an attributable mutant. Round 3's two Minor gaps on this invariant are gone. |

**Answering the question asked directly: invariant 1's open-blocking-F-ID leg
does *not* yet hold.** It is much closer than it was — round 3's three holes are
genuinely fixed and the arm is smaller — but the same silent-PASS outcome is
still reachable from three shapes, and two of the three (NEW-F1, NEW-F2) sit in
code this commit either rewrote or newly made claims about.

---

## 6. New findings

### NEW-F1 — Critical — `tools/check-plugin.py:2456`

`_named_phase` locates its field with `re.search(r"\*\*" + field + r":\*\*\s*(.+)", ttext)`
over the **entire tracker**, so the first `**Phase:**` anywhere in the file is
taken as the run's position. Nothing requires the `## Current State` block to be
the first `##` heading (no such arm exists — grepped). The round anchored the
*token inside the value* and left the *field's location* unanchored, which is the
same class of defect NEW-01 was.

This commit raises the exposure: it added a literal
`` `- **Phase:** 3 — fix loop, F-002 open` `` example into
`templates/progress.md:47-48` — the file a run copies into its own run
directory. In the shipped template that example sits *below* Current State, so
first-match-wins keeps it benign there; nothing keeps it below.

**Measured (probe K2):** a `run-fixloop` copy with one prose line above the
block — `Reminder from the template: the id comes first, e.g. `- **Phase:** 2 — fix loop, F-002 open`.` —
a real `- **Phase:** 3 — advanced past the open F-002`, `- **Next action:** T4 — start phase 3`,
and `F-002 | Major | 2 | … | open`:

```
### K2 … [run-fixloop]
  check-plugin: PASS
```

The gate read the *example's* `2`, so `max(_named) > _blockers[0][0]` was
`1 > 1`, false, and it printed `ok`. Probe K1 shows the mirror (a `3` in prose
over a real `2`) produces a spurious FAIL, so the defect cuts both ways.

**Fix.** Read both fields out of the Current State block only, and require the
block to exist and lead the file:

```python
        _cs = re.search(r"^##\s+Current State\s*$(.*?)(?=^##\s|\Z)",
                        ttext, re.M | re.S)
        if _cs is None:
            bad(f"{relpath(tracker)}: no `## Current State` block — the "
                "advancement check reads the run's position from that block "
                "and has nothing to read. REMEDY: keep the Current State "
                "block at the very top, as `templates/progress.md` ships it")
        _cstext = _cs.group(1) if _cs else ""
```

then `re.search(…, _cstext)` at `:2456`. Add a mutant
`"run tracker Phase field is shadowed by an earlier mention"` that writes K2's
shape; verify it SURVIVES with the fix reverted.

### NEW-F2 — Critical — `tools/check-plugin.py:2383` and `:2397`

Row detection is `re.match(r"\s*\|\s*F-\d+\s*\|", …)` — the one comparison in
this arm that does **not** go through `_norm`. A row whose `ID` cell carries
markdown is silently `continue`d at `:2397`, and because `_seen_fid` at `:2383`
uses the identical regex, the "unparseable ledger" report cannot fire for it
either. Nothing is printed at all. This is F-001's original complaint
(*"drops any row with a bolded `Sev`"*) surviving on the `ID` cell, and it
falsifies `templates/findings.md:27-29`'s *"It reports that rather than treating
it as closed."*

**Measured**, on `run-fixloop` with `**Phase:** 3` / `**Next action:** Phase 3 T4`
(i.e. openly advanced past Phase 2):

```
### L1 ledger row with a BOLDED id: '| **F-002** | Major | 2 | ... | open | |' + advance to Phase 3
  check-plugin: PASS
### L2 ledger row with a BACKTICKED id + advance to Phase 3
  check-plugin: PASS
```

The regex predates this commit, but this commit rewrote both call sites and
`templates/findings.md` now claims the behaviour it does not have.

**Fix.** Normalise before matching, in both places — one shared predicate:

```python
        _F_ROW = re.compile(r"\|\s*f-\d+\s*\|")
        def _is_fid_row(ln):
            return bool(_F_ROW.match(_norm(ln).lstrip()))
```

`_norm` already strips `*`, backtick and `_`, so this covers bolded, italic and
backticked ids in one step. Add a mutant
`"run tracker ledger row bolds its ID"` alongside the existing
`"run tracker ledger row bolds its severity"`.

### NEW-F3 — Major — `tools/check-plugin.py:2384`; `templates/findings.md:24-31`

`_seen_fid`'s `and _norm(ln).count("|") >= 6` filter exists to keep the shipped
4-column *Deferred Minor* table out of the population (N-003's lesson), but it
is expressed as a width threshold, and it therefore also excludes a **blocking**
table of 4 columns — the exact minimum `templates/findings.md:30-31` blesses
(*"Keep the four names `ID`, `Sev`, `Phase` and `State`; add columns if you need
them"*), and a shape the gate otherwise reads and gates on (probes D3, D4).

On that shape a renamed column is not a build failure; it is a silent pass.

**Measured (probe E2)** — 4-column blocking table, `Phase`→`Area`, `F-002 … open`
against Phase 2, `**Phase:** 3 — advanced past the open F-002`:

```
  ok    Current State does not point past an unfinished phase (this run's ledger contributed no readable blocking row, so the ledger half of that established nothing)
check-plugin: PASS
```

Threshold pinned by probe E4: at 5 columns the same rename FAILs.

**Fix.** Lower the threshold to the narrowest blocking row the grammar allows —
four cells, five pipes — so the covered set matches the sanctioned set:

```python
            _seen_fid = [ln for ln in _lines
                         if _is_fid_row(ln)
                         and _norm(ln).count("|") >= 5]
```

This makes a `findings.md` that has a *Deferred Minor* table and **no** blocking
header report as unparseable, which is the correct reading of the pinned
grammar; if that is not wanted, exclude the Deferred Minor rows by heading
instead of by width. Either way, add a mutant
`"run tracker narrow ledger header renames its phase column"`.

### NEW-F4 — Minor — `tools/check-plugin-mutants.sh`, mutant *"run tracker second blocking table gates nothing"*

The mutant appends a second blocking table holding `F-009 Critical … 2 … open`
and advances `**Next action:**` to `Phase 3` — but `run-fixloop`'s **first**
table already holds `F-002 … Major … 2 … open` (its own no-op guard even asserts
this), so advancing to Phase 3 fails on the first table alone. Reversion TEST 2
restored the `break` that made the walk first-table-only and re-applied the
mutation:

```
--- with NEW-03 reverted, does the mutant still kill? ---
check-plugin: FAIL
  FAIL  tools/fixtures/run-fixloop/progress.md: Current State names a phase later than Phase 2, which still has open blocking finding F-002 (major) …
```

The kill is attributable to the first table, so **NEW-03's multi-table walk is
unpinned** and can rot back on a green harness. This is exactly F-019's class.

**Fix.** Close `F-002` in the mutation before appending the second table, and
have the second table's row target a phase the first table does not:

```
  sed -i "s3| F-002 | Major | 2 |3| F-002 | Major | 2 |3;s3| open | |3| closed | fix |3" "$d/findings.md"
```
(or, cleaner, mutate a copy where table 1 is all-`closed` and table 2 holds
`F-009 | Critical | 1 | … | open`, which is probe F1's shape — verified to FAIL
naming Phase 1 with the fix and to PASS without it).

### NEW-F5 — Minor — `tools/check-plugin-mutants.sh`, mutant *"a pinned file becomes unreadable"*

`chmod 000` on `references/parallel.md` trips a generic file-readability arm as
well as the pin arm. Reversion TEST 1 restored the bare `continue` at
`check-plugin.py:1927` and re-applied the mutation:

```
===== TEST 1: revert NEW-05 fix (restore bare continue), then apply the mutant =====
NEW-05 fix reverted
check-plugin: FAIL
  FAIL  plugins/superb/skills/pipeline/references/parallel.md: [Errno 13] Permission denied: …
```

**NEW-05's fix is unpinned.** (The fix itself works — with it in place the pin
arm's own line is emitted, verified separately.)

**Fix.** Pick a pinned file that no other arm reads, or assert the pin arm's own
message. The harness's kill test is `./tools/check-plugin.sh` exit status only,
so the cheapest sound change is to make the mutant target a file whose only
reader is the pin — otherwise grep the output for
`so the pin on … checked nothing there` inside the mutant script and echo a
`mutant is a no-op:` line when it is absent, which routes a co-kill into the
NO-OP bucket F-020 built.

### NEW-F6 — Minor — `tools/check-plugin.py:2426-2434`

NEW-07 guarded the Current-State half's "matches no `## Phase` heading" report
with `_phs`, but left the **ledger half's** identical report unguarded, so on an
unparseable tracker the operator still gets a second, actively misleading
diagnosis — the comment at `:2481-2484` says the two halves "should agree", and
they now do not.

**Measured (probe J1)** — `## Phase ` → `## Stage `:

```
  FAIL  …/progress.md: no `## Phase <x>` heading this gate can parse, yet the file holds closed review rounds …
  FAIL  …/findings.md: F-002 (major) is open against phase '2', which matches no `## Phase` heading in the tracker … REMEDY: make the ledger's Phase cell match the tracker's phase heading
```

The ledger is fine; the remedy points at the wrong file.

**Fix.** Gate the ledger report the same way — at `:2426`, `if _pi is None and _phs:`
(and `continue` regardless, so an unscoped row never becomes a blocker).

### NEW-F7 — Minor — `plugins/superb/skills/pipeline/templates/progress.md:52-53`

*"A field that does not begin with a phase id names no phase, and the gate
reports that rather than guessing which number was meant."* The gate reports
nothing in that case: the only report path (`check-plugin.py:2490`) requires
`_id is not None`, and a phase-less field is simply absent from `_named`. It
surfaces only indirectly, via `elif _blockers and not _named`, and only when a
blocker happens to exist. `tools/fixtures/run-ok:109-110` ships exactly that
shape in **both** fields and the gate prints an affirmative:

```
  ok    no unfinished phase in the tracker (this run's ledger contributed no readable blocking row, so the ledger half of that established nothing)
```

A claim finding by this skill's own rule, in a file this commit wrote.

**Fix.** Either restate it accurately — *"…names no phase, and the gate then has
nothing to compare, so it reports the missing subject the moment any phase is
unfinished"* — or make the claim true and update `run-ok`'s Current State to
`**Phase:** 4 — fixture, complete` so the fixture conforms to the grammar the
template now pins.

### NEW-F8 — Minor — `tools/check-plugin.py:2380`

`_rows += _tbl` is a dead assignment: `_rows` is rebound by
`for _hdr, _rows in _tables:` at `:2394` before anything reads it, and the
accumulated value is never used. It also shadows the loop variable, which is the
kind of thing that reads as intentional to the next editor.

**Fix.** Delete the line (and drop `_rows` from the `_tables, _rows = [], []`
initialiser at `:2369`).

### NEW-F9 — Minor — `tools/check-plugin.py:2120` and `:2309`

`parse_tracker_phases`' heading regex captures `Phase\s+<id>` **including the
matched whitespace**, and `_idx` keys on that label verbatim
(`{ph["label"].lower(): i}`), while every lookup builds `f"phase {id}"` with a
single space. A heading written `## Phase  2 — …` therefore matches nothing.

**Measured (probe C2)** — four reports for one stray space, and the remedy
(*"name a phase the tracker has"*) is wrong, because the tracker does have it:

```
  FAIL  …/findings.md: F-002 (major) is open against phase '2', which matches no `## Phase` heading in the tracker …
  FAIL  …/progress.md: Current State's `**Phase:**` names phase '2', which matches no `## Phase` heading in this tracker …
  FAIL  …/progress.md: Current State's `**Next action:**` names phase '2', which matches no `## Phase` heading in this tracker …
  FAIL  …/progress.md: Phase 3 has an open task line and an open RV/RVJ line, and neither Current State field names a phase …
```

Pre-existing, and it fails loudly rather than silently, so it is not a hole —
but it is the "unusual spacing" leg, and it is one `re.sub` from gone.

**Fix.** Collapse the label at `:2122`:
`"label": re.sub(r"\s+", " ", mh.group(1)).strip()`.

**Tally: 2 Critical, 1 Major, 6 Minor.**

---

## 7. Assessment of the round's premise

The premise — *tighten the grammar so the parser can shrink* — was the right
call and it worked where it was applied:

* The phase reader is one anchored `re.match`, down from a `search`-or-`match`
  pair, and it is correct on **every** form the templates and the three fixtures
  write (probe set A, B, plus `run-ok` and `run-open-rv` verbatim).
* The boundary arm lost a clause that could never execute and gained the two
  dash alternatives, and it is now correct in both directions across ten probes.
* Four of the six new mutants are properly attributable — a better ratio than
  round 3 managed.
* **Nothing conforming regressed.** Round 2's failure mode did not recur.

What the round did not do is finish the job of anchoring. The three remaining
holes in invariant 1 are all the same shape as each other: a comparison that
reads *unnormalised or unscoped* text.

* the field is read from the whole file, not from the block that owns it (NEW-F1);
* the row is matched on raw markdown, not on `_norm`'d text (NEW-F2);
* the row population is bounded by a **width heuristic** rather than by the
  grammar's own minimum (NEW-F3).

All three are one to four lines, and the round's own strategy is the right one to
apply to them: anchor the read, normalise before comparing, and let the pinned
grammar — not a heuristic — set the bounds. Note also that the two Criticals are
each reachable through code this commit rewrote or newly documented, so this is
not a request to reopen an earlier round: `templates/findings.md` and
`templates/progress.md` now make claims that measurement contradicts.

The convergence-rule input matters here: rounds 1→4 have each produced at least
one Critical from this one arm, and NEW-F1/NEW-F2 land in the same place round
3's NEW-01/NEW-02 did. No F-ID has repeated, so the letter of the rule is still
untripped, but a fifth iteration on the same arm should be entered
deliberately — with the anchoring made total in one pass (Current-State-block
scoping **and** `_norm`-before-match **and** the grammar-derived width bound
together), not one shape at a time.

---

## 8. Probe index

All probes ran in `…/scratchpad/probe.24KP`, fixtures reset from a pristine copy
before each. Working tree untouched (`git status --porcelain` empty, before and
after).

| Probe | What | Result |
| ----- | ---- | ------ |
| A1–A6 | `**Phase:**` forms: fixture verbatim, template example, bare id, `Phase <id>`, hyphen, colon | 5 PASS, A2 correctly FAIL |
| B1, B2 | split id `2a` end-to-end; then advanced past it | PASS / correct FAIL |
| C1, C2, C3 | heading spacing variants | PASS / **FAIL (NEW-F9)** / PASS |
| D1 | 8th column, mis-designed (rows left narrow) | correct FAIL — probe defect, not gate defect |
| D1b, D2, D3, D4 | extra column appended; extra column inserted before `Sev`; minimal 4-column; 4-column gating | PASS, PASS, PASS, correct FAIL |
| E1, E2, E3, E4 | header rename at 7 / **4** / 7 (`State`) / 5 columns | FAIL, **PASS (NEW-F3)**, FAIL, FAIL |
| F1 | second blocking table, narrower header, row against Phase 1 | correct FAIL, correct attribution |
| G1 | `WAIVED by user:` `RV` form | PASS |
| H ×10 | `boundary:` values `-`, `—`, `seam`, `not applicable`, `nothing crosses …`, `notification queue …`, `— the T2 contract`, `-shaped seam at T2`, `none`, `n/a` | 6 FAIL, 4 PASS — all on the intended side |
| I1 | NEW-01's exact reported shape | correct FAIL |
| J1, J2 | unparseable tracker; nonexistent phase 9 | 2 reports (**NEW-F6**) / 1 report |
| K1, K2 | prose `**Phase:**` above the block, both directions | spurious FAIL / **PASS (NEW-F1)** |
| L1, L2 | bolded / backticked ledger row id, advanced past the finding | **PASS, PASS (NEW-F2)** |
| TEST 1–6 | reversion tests for mutant attribution (NEW-05, NEW-03, NEW-02, NEW-01, NEW-04, NEW-06) | 4 attributed, 2 co-killed (**NEW-F4, NEW-F5**) |

---

VERDICT: FINDINGS MUST BE FIXED
