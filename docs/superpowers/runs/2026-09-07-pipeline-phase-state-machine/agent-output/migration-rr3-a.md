# Migration — re-review, round 3 (slice a)

**Scope:** `git diff f526c3b..HEAD` — one commit, `a104d78`
("fix(pipeline): close the re-review's 10 findings, two of them Critical").
Rounds 1 and 2 are not re-reviewed. 7 files, +817/−29.

**Questions answered, in order:** (1) is each of N-001…N-010 closed;
(2) **both directions** — does every touched arm still catch the wrong shape
*and* accept every shape `templates/progress.md` / `templates/findings.md`
prescribe; (3) do the round-3 fixes interact or regress anything;
(4) do the spec's invariants still hold.

**Tiers:** Critical / Major / Minor. No `Important` emitted.

---

## 1. Gate and harness output (real, verbatim)

```
$ cd /home/wp3/IntellijProjects/claude-plugin
$ ./tools/check-plugin.sh | tail -2
check-plugin: PASS

$ for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d | tail -1; done
check-plugin: PASS
check-plugin: PASS
check-plugin: PASS

$ ./tools/check-plugin-mutants.sh 2>&1 | tail -6
  killed    SKILL.md restates the per-task cost model

killed=148 survived=0 no-op=0
check-plugin-mutants: PASS

$ python3 -m unittest discover -s plugins/superb/skills/craft/tests 2>&1 | tail -3
Ran 19 tests in 0.458s

OK
```

The four new mutants this round adds (`the conditional integration rule reverts
in fix-loop.md`, `the pre-RV repair rule reverts in parallel.md`, `the
re-review boundary rule reverts in SKILL.md`, `SKILL.md restates the per-task
cost model`) are all in the `killed` set, and `no-op=0` — so the whitespace-
flexible rewrite of them (the round's own "sixth reflow casualty" note) is
sound. The green harness is real; every finding below is a hole the harness has
no mutant for.

## 2. Method

Two comparison trees, neither of them the working tree:

```
$ git archive f526c3b | tar -x -C $S/before     # the pre-round-3 gate
$ git archive HEAD     | tar -x -C $S/after     # the round-3 gate, for file-removal probes
$ cp -r tools/fixtures/{run-ok,run-open-rv,run-fixloop} $S/probes/   # probe bases
$ git status --porcelain                        # (empty — working tree untouched)
```

Every probe below was run as `./tools/check-plugin.sh --run <a mktemp copy>`
against **both** trees, so "the fix closed it" is a measured
BEFORE-FAIL/AFTER-PASS (or BEFORE-PASS/AFTER-FAIL) transition rather than an
assertion.

`templates/progress.md` and `templates/findings.md` were read first and used as
the authority on shape. The shapes they prescribe and that this review treated
as **must-PASS**: `**Phase:** <current phase number and name>` (bare id, no
literal word "phase"); `**Next action:** <the single next unchecked line —
task, RV, or RVJ>` (names no phase at all); phase ids like `3a`/`4a`; a
*Deferred Minor findings* table with four columns; a joining phase's `RVJ`
**above** its first task; `boundary: <what>`.

---

## 3. Probes and results

### Probe set A — `**Phase:**` written every way the template allows

| # | `**Phase:**` value | Result | Expected |
|---|---|---|---|
| A1 | `Phase 2 — fix loop` (doubled) | PASS | PASS ✓ |
| A2 | `2` (bare number alone) | PASS | PASS ✓ |
| A3 | `**2 — fix loop**` (value bolded) | PASS | PASS ✓ (passes on `Next action`; see §5 NEW-07) |
| A4 | `<current phase number and name>` (unfilled placeholder) | FAIL — *"names phase 'number', which matches no `## Phase` heading"* | acceptable |

### Probe set B — `**Next action:**` that names no phase (the N-004 class)

Base `run-fixloop`: `F-002` **open** at Major against Phase 2, Current State at
Phase 2.

| # | Shape | Result | Expected |
|---|---|---|---|
| B1 | `Phase: 2 — …` + `Next action: T4 — a task` | PASS | PASS ✓ |
| B2 | `Phase: 2 — …` + `Next action: RV — review fan-out` | PASS | PASS ✓ |
| B3 | `Phase: 2 — …` + `Next action: RVJ — joint integration review · split 3a+3b` | PASS | PASS ✓ |
| B4 | `Phase: **2 — fix loop**` (bolded) + `Next action: T4 — a task` | FAIL — *"neither Current State field names a phase"* | see NEW-07 |
| B5 | `Phase: 3 — moved on` + `Next action: T4 — a task` | **FAIL** — *"names a phase later than Phase 2, which still has open blocking finding F-002 (major)"* | FAIL ✓ |
| B6 | `Next action: Phase 3 T4 — a task` | **FAIL** — same arm | FAIL ✓ |

Both directions hold. B5 is the decisive one: it is the exact state
`**Phase:**` was unreadable on before this round, and it now fails.

### Probe set C — `findings.md` with a populated *Deferred Minor findings* table (N-003)

| # | Mutation to `run-fixloop/findings.md` | AFTER(r3) | BEFORE(r2) |
|---|---|---|---|
| C1 | append `\| F-003 \| 2 \| \`src/c.py:5\` \| a deferred minor \|` (4 cells) | **PASS** | **FAIL** — *"row 'F-003' has 4 cells but its header has 7"* |
| C2 | same + trailing prose | PASS | (same as C1) |
| C3b | first table's rows all `closed`; a **second** 7-column blocking table further down carrying `F-004 Critical / Phase 2 / open`; Current State advanced to `3 — moved on` | **PASS** | **FAIL** |

C1 is N-003 closed, measured in both directions. **C3b is a new hole** — see
§5 NEW-03.

### Probe set D — `RVJ` placement (N-002 / F-004)

Built a probe run directory from `run-open-rv`'s `agent-output/`:

| # | Shape | AFTER(r3) | BEFORE(r2) |
|---|---|---|---|
| D1 | Phase 2 is a **joining** phase: leading `RVJ` `[x]`, `T6` `[x]`, **no `RV` of its own**; Current State at Phase 3 | **FAIL** — *"Current State names a phase later than Phase 2, which still has **no `RV` line**"* | FAIL, but for the **wrong reason**: *"neither Current State field names a phase"* (the N-004 false-fail) |
| D2 | same, plus Phase 2's own closed `RV` | **PASS** | — |
| D3 | shipped `run-open-rv` (leading `RVJ` `[x]` above open tasks, own `RV` `[ ]`) | PASS | PASS |
| D4 | trailing `RVJ` over unfinished work (harness mutant `run tracker opens a trailing RVJ over unfinished work`) | killed | — |

N-002 is closed and the closure is **attributable**: the new failure text names
the missing `RV`, and the conforming leading-`RVJ` shape (D2/D3) still passes.

### Probe set E — `boundary:` with a legitimate short description (N-005)

Mutating `run-ok` Phase 2's `· boundary: …` field:

| # | value | Result | Expected |
|---|---|---|---|
| E1 | `the T2 contract consumed by T7` | PASS | PASS ✓ |
| E2 | `the auth seam` (3 words) | PASS | PASS ✓ |
| E3 | `shared cache` (2 words) | PASS | PASS ✓ (no false-fail) |
| E4 | `T3->T7` (one token) | PASS | PASS ✓ (no false-fail) |
| E5 | `none` | FAIL | FAIL ✓ |
| E6 | `not applicable` | **FAIL** | FAIL ✓ (N-005 case A) |
| E7 | `nothing crosses between the slices` | **FAIL** | FAIL ✓ (N-005 case B) |
| E8 | `n/a` | FAIL | FAIL ✓ |
| E9 | `-` | **PASS** | should FAIL — see NEW-04 |
| E10 | `no boundary of any consequence here` | FAIL | FAIL ✓ |
| E11 | `seam`, written as the record's **last** field | PASS | — (the 3-word rule is inert; see NEW-04) |

N-005's measured defects (E6, E7) are closed and no legitimate short
description false-fails. The *stated* mechanism is not the one that operates —
NEW-04.

### Probe set F — a phase id that is not a plain integer (`4a`)

| # | Shape | Result |
|---|---|---|
| F1 | heading `## Phase 4a — …`, Current State at Phase 2 | PASS ✓ |
| F2 | `**Phase:** 4a — the split sibling` while `F-002` is open against Phase 2 | **FAIL** ✓ (advancement caught; `4a` resolved) |
| F3 | ledger `Phase` cell `4a`, Current State at Phase 2 | PASS ✓ (no spurious *"matches no `## Phase` heading"*) |

`4a` works on both the tracker side and the ledger side, in both directions.

Regex trace of the new `_named_phase` on the shapes that matter:

```
$ python3 -c "... (re.search(r'[Pp]hase\s+([0-9A-Za-z.]+)', v) or re.match(r'\s*([0-9]+[0-9A-Za-z.]*)\b', v)) ..."
'3 — moved on past the phase 2 fix loop' -> 2      <-- NEW-01
'3 — rework of the Phase 2 helper'       -> 2      <-- NEW-01
'T4 — a task'                            -> None   (question 3: safe)
'RV — review fan-out'                    -> None   (question 3: safe)
'4a — split sibling'                     -> 4a
'2'                                      -> 2
```

### Probe set X — `_named_phase`'s alternation ordering

Base `run-fixloop`, `F-002` **open** against Phase 2. Advancing to Phase 3
must fail.

| # | `**Phase:**` value | `**Next action:**` | AFTER(r3) | BEFORE(r2) |
|---|---|---|---|---|
| ctl | `3 — moved on` | `T4 — a task` | **FAIL** ✓ | — |
| X1 | `3 — moved on past the phase 2 fix loop` | `T4 — a task` | **PASS** ✗ | PASS |
| X2 | `3 — rework of the Phase 2 helper` | `T4 — a task` | **PASS** ✗ | — |
| X3 | `3 — after phase 2` | `Phase 3 T4 — a task` | FAIL ✓ | — |
| X4 | `3 — split the phase 9 work` | `T4 — a task` | FAIL, with two contradictory messages | — |

X1/X2 are NEW-01. X4 is NEW-07.

### Probe set I — a blocking header the gate cannot locate (F-001's report-not-drop)

| # | Mutation to `run-fixloop/findings.md` (`F-002` **open**, `F-001` Critical) | AFTER(r3) | BEFORE(r2) |
|---|---|---|---|
| I1 | header `\| ID \| Sev \| **Area** \| File:line \| Finding \| State \| Closed by \|` | **PASS** ✗ | **FAIL** — *"holds 2 `F-` row(s) but no header row naming ID/Sev/Phase/State … An unparseable ledger must not read as an empty one"* |
| I2 | the blocking header row deleted outright | **PASS** ✗ | **FAIL** — same |

AFTER's affirmative line on I1, verbatim:

```
  ok    Current State does not point past an unfinished phase (this run's ledger
        contributed no readable blocking row, so the ledger half of that established nothing)
```

This is NEW-02. `Area` is not a hypothetical column name: this very run's
`findings.md` uses `| ID | Sev | Area | File:line | Finding | State | Closed by |`.

### Probe set H — the new held-phrase pin arm

| # | Probe | Result |
|---|---|---|
| H1 | reword the phrase in one file only (the four new mutants) | killed ✓ — the pin fires, and each kill is attributable (each mutant asserts the phrase survives in the *other* file) |
| H2 | `mv references/implement.md implement.md.bak` in the `$S/after` tree, then `./tools/check-plugin.sh` | **`check-plugin: PASS`**, and the pin still printed `ok 2 migration-corrected rules present in every file that states them` — NEW-05 |
| H3 | which files' flattened text actually carries each pinned phrase | `only at a declared integration boundary`: `SKILL.md` (×2), `references/fix-loop.md`, **`templates/progress.md`** (unpinned) — NEW-06. `raises no finding, takes no f-id`: `references/implement.md`, `references/parallel.md` — list complete ✓ |

On question 3's "can it fire on a legitimate rewording": yes, by construction —
that is what a pin is for, and the `bad()` text says so ("restore the phrase,
or, if the rule genuinely changed, change it in every file that states it and
retire this pin"). That is this repo's established pattern and is not a
finding. The `bad()` fires on a rewording *of the pinned words*, not on
unrelated edits to those files, so the blast radius is correct.

### Probe set N — the remaining ledger rows

| # | Probe | Result |
|---|---|---|
| N6a | `**Phase:** 9 — a phase this tracker does not have`, no earlier blocker | **FAIL** on its own arm ✓ (though it reports `'this'`, not `'9'` — NEW-01) |
| N8a | demote every `## Phase` to `### Phase` | FAIL, and **no** affirmative `Current State …` / `no unfinished phase …` line printed ✓ |
| N10a | re-read `references/fix-loop.md:381-390` | the `**Unless \`M=0\`.**` block is indented 3 spaces inside its list item and the sentence rejoins as "…the proof that you should not. `M` does not size the fan-out — the fix diff does" ✓ |

---

## 4. Per-finding table — is each of N-001…N-010 closed?

| N-ID | Sev | Verdict | Evidence |
|---|---|---|---|
| N-001 | Critical | **closed** (with a residual hole → NEW-01) | `check-plugin.py:2422-2423` adds `or re.match(r"\s*([0-9]+[0-9A-Za-z.]*)\b", val)`. Probe A2 (`**Phase:** 2` alone) is now read; probe B5 FAILs on the bare `3 — moved on` where BEFORE it passed. The bare form is readable. **But** the bare-id branch is only reached when the *first* alternative misses, and that alternative searches for `phase <token>` anywhere in the value — X1/X2. |
| N-002 | Critical | **closed** | `check-plugin.py:2296` — `if not any(r[0] == "RV" for r in _ph["reviews"])`. Probe D1: AFTER FAILs naming *"still has no `RV` line"*; the conforming leading-`RVJ` shapes D2/D3 still PASS. The two arms now agree about what an `RVJ` covers. |
| N-003 | Major | **closed** (with a new hole → NEW-02, NEW-03) | `check-plugin.py:2335-2345` scopes rows to the header's own table. Probe C1: AFTER PASS / BEFORE FAIL on a populated 4-column *Deferred Minor* row. Both directions verified — the 7-column width check still fires (harness mutant `run tracker ledger row bolds its severity` killed). |
| N-004 | Major | **closed** | Probes B1/B2/B3: `**Next action:**` naming no phase (`T4 — a task`, `RV — review fan-out`, `RVJ — …`) now PASSes with a readable `**Phase:**`. Probe D1 BEFORE failed with exactly *"neither Current State field names a phase"*; AFTER does not. |
| N-005 | Minor | **closed** (mechanism misdescribed → NEW-04) | `check-plugin.py:1560-1562`. Probes E6 (`not applicable`) and E7 (`nothing crosses between the slices`) both FAIL now; E1–E4 (legitimate descriptions, including 2-word and 1-token ones) all PASS, so the inversion did not over-correct. |
| N-006 | Minor | **closed** | `check-plugin.py:2436-2444` reports a Current-State field naming a phase the tracker lacks on its own arm. Probe N6a FAILs with no blocker at a lower index. (`_na_present`/`_ph_present` are still assigned and never read — NEW-07.) |
| N-007 | Minor | **closed** (coverage gap → NEW-05, NEW-06) | `check-plugin.py:1884-1920` adds the `== migration-corrected rules stay corrected ==` arm; `check-plugin-mutants.sh` adds four mutants, all `killed`, all `no-op=0`. Probe H1 confirms each kill is attributable to its own file. |
| N-008 | Minor | **closed** | `check-plugin.py:2467` — the second affirmative is now `elif _phs:`. Probe N8a: an unparseable tracker prints no affirmative line about its contents. |
| N-009 | Minor | **closed** | `check-plugin-mutants.sh:1928-1936` writes `**Phase:** 3 — moved on` (bare) and `**Next action:** RV — review fan-out`, and adds a no-op guard rejecting the doubled `Phase:** Phase` form. Mutant `run tracker Current State phase advances while Next action does not` is `killed` with `no-op=0`, so it now certifies the arm against the shape the template actually writes. |
| N-010 | Minor | **closed** | `references/fix-loop.md:381-390` re-read (probe N10a): the block is indented into its list item and the dangling sentence is rejoined. |

**10 of 10 closed.** No row marked closed has its measured defect still
reachable by the shape the row named.

---

## 5. New findings

### NEW-01 — Critical — `_named_phase` reads a *mentioned* phase in preference to the phase the field names

`tools/check-plugin.py:2422-2423`

```python
g = (re.search(r"[Pp]hase\s+([0-9A-Za-z.]+)", val)
     or re.match(r"\s*([0-9]+[0-9A-Za-z.]*)\b", val))
```

`re.search` for `phase <token>` runs over the **whole value** and wins over the
bare-leading-id fallback. So any `**Phase:**` whose name or trailing prose
mentions an earlier phase resolves to *that* phase, and the advancement arm then
compares Current State against a position the run has already left:

```
run-fixloop, F-002 open at Major against Phase 2
  **Phase:** 3 — moved on                              -> FAIL  (correct)
  **Phase:** 3 — moved on past the phase 2 fix loop    -> PASS  (X1)
  **Phase:** 3 — rework of the Phase 2 helper          -> PASS  (X2)
```

Both X1 and X2 are template-conforming `<current phase number and name>`
values. This is F-007's and N-001's own measured defect — *the gate reports `ok`
over a tracker that advanced past an open blocking finding* — reachable through
the function this round rewrote, and the ledger closes N-001 on the claim that
the field is now read. It is also reachable in the *noisy* direction: with a
nonexistent id mentioned (X4, `3 — split the phase 9 work`) the arm reports
phase `'9'` and then declares that *neither* field names a phase.

It is not a round-3 regression — BEFORE(r2) also passed X1 — but it is in scope,
because this round owns `_named_phase` and the whole point of N-001's fix was to
make the field readable, and it is only readable for values without a later
`phase <token>`.

**Fix.** Anchor the field to its own leading id and stop searching the prose:

```python
g = re.match(r"\s*(?:[Pp]hase\s+)?([0-9]+[0-9A-Za-z.]*)\b", val)
```

That accepts `2`, `3 — moved on`, `4a — split sibling`, `Phase 2 — fix loop`
and the doubled form; rejects `T4 — a task` and `RV — review fan-out`; and
ignores any later mention. Add a mutant `run tracker Current State names a
later phase whose name mentions an earlier one` writing exactly X1's value over
`run-fixloop`, so the hole cannot reopen.

### NEW-02 — Critical — the unparseable-ledger report is now unreachable; an unreadable `findings.md` reads as a clean one again

`tools/check-plugin.py:2335-2352`

`_seen_fid` is computed **from `_rows`**, and `_rows` is populated only inside
the `if {"id","sev","phase","state"} <= set(_cells)` branch. So when `_hdr is
None`, `_rows == []`, `_seen_fid == []`, and the `if _seen_fid: bad(...)` body
at `:2349-2354` is dead code. Measured:

```
header `| ID | Sev | Area | File:line | Finding | State | Closed by |`
  AFTER(r3)  : check-plugin: PASS
  BEFORE(r2) : check-plugin: FAIL  "…holds 2 `F-` row(s) but no header row naming
                ID/Sev/Phase/State … An unparseable ledger must not read as an empty one"

blocking header row deleted outright
  AFTER(r3)  : check-plugin: PASS      BEFORE(r2) : check-plugin: FAIL
```

This directly regresses F-001's `report-not-drop` property — the Critical whose
own comment at `:2318-2326` still stands three lines above the dead branch — and
it is reachable on a plausible ledger: **this run's own `findings.md` uses
`Area` where the template uses `Phase`.** No mutant covers it (`grep 'run_mutant
"run tracker'` lists none for a missing or renamed ledger header), which is why
`killed=148 survived=0` did not see it.

**Fix.** Keep the whole-file scan for the *report*, and the table scope only for
the *rows*:

```python
_all_fid = [ln for ln in _lines if re.match(r"\s*\|\s*F-\d+\s*\|", ln)]
_seen_fid = [ln for ln in _rows if re.match(r"\s*\|\s*F-\d+\s*\|", ln)]
if _hdr is None:
    if _all_fid:
        bad(... f"holds {len(_all_fid)} `F-` row(s) but no header row …")
```

and add a mutant that renames the blocking header's `Phase` column while
leaving `F-002` open.

### NEW-03 — Major — only the *first* matching table's rows are read, so a second blocking ledger gates nothing

`tools/check-plugin.py:2336-2344`

The header loop `break`s on the first match and row collection stops at that
table's end. A `findings.md` with a second blocking-shaped table — again, the
shape **this run's own `findings.md` ships** (`## Blocking ledger` plus
`## Round 2 ledger`, both `| ID | Sev | … | State | …`) — has that table's rows
dropped in silence:

```
first table all `closed`; second table carries `| F-004 | Critical | 2 | … | open | |`
Current State advanced to `3 — moved on`
  AFTER(r3)  : check-plugin: PASS
  BEFORE(r2) : check-plugin: FAIL
```

Before this round the row scan iterated the whole file, so a second table with
the same width was read. N-003's fix traded a false-failure for a
false-affirmative on a shape the run directory itself demonstrates.

**Fix.** Do not `break`. Collect `(header, rows)` for **every** header row that
satisfies the column predicate, run the existing width/state/sev/phase logic per
pair, and count `_lrows` across all of them. Any `F-` row belonging to none of
those tables and none of the four-column deferred shape is what NEW-02's report
should name.

### NEW-04 — Minor — the boundary arm's stated mechanism is not the one that runs, and `-` is still accepted

`tools/check-plugin.py:1556-1563`

The new comment claims a boundary must be "three or more words of substantive
text that does not open with a negation", and the pattern
`\S+(?:\s+\S+){2,}` looks like it enforces that. It does not: `rec` is a
**flattened 400-character window** (`check-plugin.py:1376`, `:1392`), so the
words after a one-word boundary are supplied by whatever follows on the record —
`· reports …`, the next task line, the next `## Phase` heading. Measured: `E4
boundary: T3->T7` PASSes, and `E11 boundary: seam` written as the record's last
field PASSes. Two consequences:

- Good news, and worth recording: **there is no false-failure** on a short
  legitimate description (E2, E3, E4), so N-005 did not repeat round 1's
  mistake. The arm's real content is the negation lookahead.
- The `-` and `—` entries in that lookahead are dead. `(?:…|-|—)\b` needs a
  word character immediately after the dash, and `boundary: -` is followed by
  a space, so the alternative never matches and `boundary: -` PASSes (E9).
  BEFORE(r2) passed it too, so this is a pre-existing hole the rewrite
  advertised as fixed rather than one it created.

**Fix.** Split the character alternatives out of the `\b` group and drop the
inoperative word count from both the pattern and the comment:

```python
and not re.search(r"boundary:\s*(?![-—]\s|(?:none|no|not|nothing|n/?a)\b)\S",
                  rec, re.I)
```

Then add a mutant writing `· boundary: -` over `run-ok` Phase 2.

### NEW-05 — Minor — the pin arm exempts a pinned file it cannot read, and its pass line claims otherwise

`tools/check-plugin.py:1910-1920`

```python
_pt, _pe = read(_pf)
if _pe:
    continue
```

An unreadable or absent pinned file is skipped in silence, and `ok(f"{len(_pinned)} …")`
then reports the *configured* count regardless of how many files were actually
inspected. Measured on a `git archive HEAD` copy:

```
$ mv .../references/implement.md .../implement.md.bak && ./tools/check-plugin.sh
== migration-corrected rules stay corrected ==
  ok    2 migration-corrected rules present in every file that states them
check-plugin: PASS
```

This is the mistake the same diff refuses three arms away ("an unreadable ledger
row is reported, never assumed clean", `:2367`), in the arm whose entire purpose
is that a corrected rule cannot rot back on a green build.

**Fix.** `bad(...)` on `_pe` naming the file and the phrase it was supposed to
carry, set `_pin_bad`, and make the pass line count `(phrase, file)` pairs
actually checked rather than `len(_pinned)`.

### NEW-06 — Minor — the pin's file list omits `templates/progress.md`, which states the same rule

`tools/check-plugin.py:1895-1897`

`only at a declared integration boundary` is pinned to `references/fix-loop.md`
and `SKILL.md`. Its flattened text is present in a third file:

```
only at a declared integration boundary
    SKILL.md x2
    references/fix-loop.md x1
    templates/progress.md x1        <-- not pinned

$ git log --oneline -3 -- plugins/superb/skills/pipeline/templates/progress.md
1557ca6 fix(pipeline): spend the integration reviewer on a boundary, not a slice count
```

So it is a migration-corrected site, it states the pinned rule, and it is the
file a run **copies into its own run directory** — a revert there reaches every
future run's tracker while the gate says `2 migration-corrected rules present in
every file that states them`. The `raises no finding, takes no f-id` pin's list
(`parallel.md`, `implement.md`) is complete; only this one is short.

**Fix.** Add `"templates/progress.md"` to the first entry's file list and a
mutant `the conditional integration rule reverts in templates/progress.md`
modelled on the three that exist.

### NEW-07 — Minor — leftovers and noise in the rewritten Current-State arm

`tools/check-plugin.py:2428-2444`

Three small things, all introduced or left by this round:

1. `_na_present` and `_ph_present` are assigned at `:2428-2429` and read
   nowhere (`grep -n "_na_present\|_ph_present"` returns only those two lines).
   This is N-006's own literal complaint — "computed and never read" — carried
   forward into its replacement. Either drop the second tuple element or use it
   to distinguish "the field is absent" from "the field is present but names no
   phase".
2. The new nonexistent-phase `bad(...)` at `:2436-2444` is not guarded by
   `_phs`. On an unparseable tracker `_idx` is empty, so every readable field
   "matches no `## Phase` heading" and the operator gets three diagnoses for one
   defect (probe N8a: two of these plus the real "no `## Phase <x>` heading this
   gate can parse"). Guard it with `if _phs and _id is not None and _i2 is
   None`.
3. Where `_ph_id` resolves to something but `_ph_i` is `None`, the arm both
   reports the unmatched id and then falls into the `elif _blockers and not
   _named` branch saying *neither field names a phase* — contradictory on the
   same file (probe X4). Suppress the second when the first fired.

A note, not a finding: a `**Phase:**` whose *value* is bolded (`**2 — fix
loop**`) is unreadable to both alternatives, so it relies on `**Next action:**`
to carry the position (A3 PASS, B4 FAIL). `templates/progress.md` does not
prescribe bolding the value, so this is out of the both-directions contract; the
suggested `re.match` in NEW-01 could tolerate it with a `[*\s]*` prefix if
wanted.

---

## 6. Do the round-3 fixes interact or regress anything?

- **The pin arm** (`== migration-corrected rules stay corrected ==`) does not
  false-fire on unrelated edits; it fires on a rewording of the pinned words,
  which is its contract, and its `bad()` text names the legitimate escape
  (change the rule everywhere and retire the pin). Its four mutants are killed
  with `no-op=0`, and each asserts the phrase survives in its sibling file, so
  the kills are attributable. Its defects are coverage, not false alarms:
  NEW-05 (unreadable file exempted) and NEW-06 (`templates/progress.md`
  missing).
- **The `an implementer,\s*a reviewer` banned pattern** (`:1982`) is scoped to
  the pipeline skill's own files, so this run's records — which quote F-011's
  retired sentence verbatim in `findings.md` — do not trip it. Its mutant
  `SKILL.md restates the per-task cost model` is killed. No interaction found.
- **`_named_phase`'s bare-id fallback**, on question 3's exact wording: it
  cannot mis-read `T4 — a task` or `RV — review fan-out`, because
  `re.match(r"\s*([0-9]+…)")` is anchored and requires a leading digit (traced
  above: both yield `None`). The mis-reading risk is in the *first* alternative,
  not the fallback — NEW-01.
- **N-003's row scoping interacts with F-001's two properties** and damages
  both: the report-not-drop branch (NEW-02) and the whole-file row scan
  (NEW-03). These are the round's real regressions and they share one fix.
- No interaction found between the `RVJ` change (N-002) and the review-not-early
  arm: D1 FAILs on the missing `RV` while D2/D3 pass on the leading-`RVJ`
  shape, so the two arms now read one list and agree.

## 7. Does the migration still satisfy its spec's four invariants?

| Invariant (`…-design.md`) | Status |
|---|---|
| **Advancement** — `PASS` is the only edge into `NEXT PHASE`; implementation complete is not phase complete; an empty ledger is not phase complete (`:168-181`) | **Not fully gated.** The prose and the state machine hold, and the tracker legs (open task, open `RV`/`RVJ`, no `RV` at all, missing fix plan) are all enforced — probes B5, D1, F2 and the harness mutants. The **open-blocking-F-ID leg is defeated three ways**: NEW-01 (Current State compared against a phase merely mentioned in its own name), NEW-02 (a ledger header the gate cannot locate reads as an empty ledger), NEW-03 (a second blocking table's rows dropped). The spec's own gate row *"no-advance-on-open-findings arm"* is the one that no longer covers what it claims. |
| **Review ownership** — no agent plans, implements, reviews and fixes at once (`:183-193`) | **Holds.** `== pipeline has no task-level review ==` passes with the new `an implementer, a reviewer` pattern added; four `killed` mutants back it; the fan-out tables and the `RVJ` grammar are unchanged by this round. |
| **Completing an implementation task dispatches no reviewer** (`:204`) | **Holds.** Untouched this round; the sweep and its mutants are green. `references/implement.md`'s edit *strengthens* it by restating the pre-`RV` repair rule in `parallel.md`'s exact words, which the new pin now holds in both files. |
| **The integration reviewer is conditional on a declared boundary** (`:243-256`) | **Holds, weakly stated.** `boundary: not applicable` and `boundary: nothing crosses …` now fail (E6, E7) and legitimate descriptions pass (E1–E4); `boundary: -` still passes (E9, NEW-04) and `templates/progress.md`'s statement of the rule is unpinned (NEW-06). |

Invariants 2 and 3 are satisfied. Invariant 4 is satisfied with two Minor gaps.
**Invariant 1's ledger leg is not**, and two of the three holes are new this
round.

---

## 8. Summary

- **N-001…N-010: 10 of 10 closed**, each verified by a BEFORE/AFTER transition
  on a `mktemp` copy, and each closure checked in **both** directions against
  `templates/progress.md` and `templates/findings.md`. The specific
  both-directions probes this round was asked for — every `**Phase:**` form, a
  phase-less `**Next action:**`, a populated *Deferred Minor* table, leading and
  trailing `RVJ`, a short `boundary:`, a `4a` phase id — all land on the
  intended side.
- **New: 2 Critical, 1 Major, 4 Minor.**
- Round 2's lesson was applied successfully in the direction it was learned
  (nothing this round false-fails a template-prescribed shape). The failure this
  round made is the *other* one: NEW-02 and NEW-03 traded N-003's false failure
  for a false affirmative, re-opening F-001's Critical `report-not-drop`
  property on a ledger shape the run directory itself ships.
- NEW-01, NEW-02 and NEW-03 all end in the same place — the advancement arm
  prints `ok` over a tracker that has advanced past an open blocking finding —
  which is the single defect this whole migration exists to make impossible.

VERDICT: FINDINGS MUST BE FIXED
