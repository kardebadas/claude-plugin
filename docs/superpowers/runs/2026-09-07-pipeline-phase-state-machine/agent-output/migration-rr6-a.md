# Migration re-review — round 6 (`85edc1f`)

Reviewer: re-reviewer A, round 6. Scope: **`git diff 89bb176..HEAD`** only — one
commit, `85edc1f` *"fix(pipeline): make an unlocatable Phase field loud, not a
fallback"*. Earlier rounds are not re-reviewed.

Tiers: **Critical / Major / Minor**.

All probes ran in `mktemp -d` copies (fixture-only copies, or a `tar --exclude=.git`
copy of the tree when `check-plugin.py` itself had to be patched). Working tree
untouched: `git status --porcelain` empty before and after.

---

## 0. Harness output, verbatim

```
$ ./tools/check-plugin.sh | tail -2

check-plugin: PASS

$ for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d | tail -1; done
check-plugin: PASS
check-plugin: PASS
check-plugin: PASS

$ ./tools/check-plugin-mutants.sh 2>&1 | tail -6
  killed    run tracker loses its Phase field
  killed    run tracker grows a second Current State block
  killed    run tracker ledger row id is not F-<n>

killed=159 survived=0 no-op=0
check-plugin-mutants: PASS

$ python3 -m unittest discover -s plugins/superb/skills/craft/tests 2>&1 | tail -3
Ran 19 tests in 0.490s

OK
```

Every declared harness is green. **That is the problem this report is about:** two
of the findings below are `check-plugin: PASS` over an open blocking finding, and
one of them is a regression this commit introduced.

---

## 1. Question 1 — are RR5-1…RR5-6 closed?

| ID | Closed? | Evidence |
| -- | ------- | -------- |
| **RR5-1** Major — bullet-form locator | **yes** | `_FIELDRE = r"^\s*(?:[-*+]\s+\|\d+[.)]\s+)?\*\*%s:\*\*"`. Probed all five marker forms with the field advanced to Phase 3 over `F-002 … open` against Phase 2: `- `, `* `, `+ `, `1. `, and **no marker** → all five `check-plugin: FAIL` *"Current State names a phase later than Phase 2"*. Same five with the field left at Phase 2 → all `PASS`. Round 5's three silent shapes are shut in both directions. |
| **RR5-2** Major — `F-<digits>`-only row-ness | **yes, as scoped** | `_isrow` is now `[a-z]{1,6}-\d+[0-9a-z.]*`. Probed an *open blocking row* keyed each id with the tracker advanced to Phase 3: `F-002`, `F-002a`, `N-002`, `NEW-02`, `F-2.1`, `BUG-7` → all six `FAIL` and gated. RR5-2's two named reachable shapes (`N-002`, `F-002a`) are closed. **A narrower residual remains** — see RR6-3. |
| **RR5-3** Minor — un-anchored block key | **yes** | `^##\s+Current State\s*$` under `re.M`. Probe: a preamble line reading ``Prose quoting `## Current State` inline.`` inserted into `run-fixloop` → `check-plugin: PASS`. No false failure. |
| **RR5-4** Minor — duplicated block unreported | **yes** | Probe: a second `## Current State` block appended → `FAIL` *"two or more `## Current State` blocks, and this gate reads the first"*. Mutant *"run tracker grows a second Current State block"* killed, and it is the **only** FAIL the mutation produces (see §4). |
| **RR5-5** Minor — decoy mutant pinned neither half | **yes** | Reversion test: with `_csblock = ttext` substituted for `_csblock = _csm.group(1) …` (block isolation removed, anchoring left intact), the rewritten decoy mutant → `check-plugin: PASS` — i.e. it **survives**, so its kill on the real code is attributable to block isolation alone. It also produces exactly one FAIL. |
| **RR5-6** Minor — three reports for one defect | **yes as written — and its fix caused a Critical** | Probe P3 (both fields naming nonexistent phase 9): now **two** FAILs, one per field; the false third *"neither Current State field names a phase"* is gone. But the guard chosen — `not (_ph_seen or _na_seen)` — keys off *"the field exists"* rather than *"the field named a phase"*, which opens **RR6-1**. |

**6 of 6 closed.** One of the six closures is the direct cause of a Critical.

---

## 2. Question 2 — is the fail-closed claim true?

### 2a. For the *locator*, yes — and it is structurally, not heuristically, true

The presence gate and the resolver **share one regex** (`_FIELDRE`). That is the
mechanism that ends the locator family: any future narrowing of `_FIELDRE` that
loses the field also fails the presence check, so it cannot degrade to a fallback.

**Decisive measurement.** I reintroduced round 5's exact locator bug —
`_FIELDRE = r"^\s*[-*]\s+\*\*%s:\*\*"` — and fed it RR5-1's own probe (`+ **Phase:** 3`
advanced over `F-002` open):

```
FAIL  tools/fixtures/run-fixloop/progress.md: no `**Phase:**` field inside a `## Current State` block — …
check-plugin: FAIL
```

Round 5's silent pass is now a red build. The claim holds where it was made.

### 2b. Enumeration — 18 shapes, `run-fixloop`, field advanced to Phase 3, `F-002` open against Phase 2

| Shape | Result | Correct? |
| ----- | ------ | -------- |
| field outside any `## Current State` block (above the heading) | **FAIL** — fail-closed report | ✅ loud |
| field inside a fenced block **inside** Current State (only field) | **FAIL** — read, advancement report | ✅ compared |
| heading at `### Current State` | **FAIL** — fail-closed report | ✅ loud |
| heading with trailing whitespace (`## Current State   `) | **FAIL** — advancement report | ✅ read |
| `**Phase :**` (space before colon) | **FAIL** — fail-closed report | ✅ loud |
| `**phase:**` lowercase | **FAIL** — fail-closed report | ✅ loud |
| single-line HTML comment `<!-- - **Phase:** 3 -->` | **FAIL** — fail-closed report | ✅ loud |
| multi-line HTML comment wrapping the field line | **FAIL** — read, advancement report | ✅ compared |
| nested list (`  - **Phase:** 3`) | **FAIL** — advancement report | ✅ read |
| after a horizontal rule inside the block | **FAIL** — advancement report | ✅ read |
| `+ ` / `* ` / `1. ` / no marker | **FAIL** ×4 — advancement report | ✅ read (RR5-1) |
| Current State block is the **last thing in the file** | **FAIL** — advancement report | ✅ read (`\Z` alternative works) |
| duplicated `## Current State` block | **FAIL** — duplicate-block report | ✅ loud (RR5-4) |
| heading with a suffix (`## Current State (round 6)`) | **FAIL** — fail-closed report | ✅ loud |
| preamble prose quoting `` `## Current State` `` | **PASS** | ✅ correct — must not false-fail (RR5-3) |

**No locator shape reaches a silent pass.** Fifteen loss/read shapes are loud, and
the one shape that must pass, does.

### 2c. Two shapes DO reach a silent pass — and neither is a locator bug

The family is not fully closed, because the fail-closed check answers only *"can
the field be located?"* — not *"was the located field the right one?"* and not
*"did the located field resolve to a phase?"*

1. **Field located, resolves to no phase** → `ok no unfinished phase in the
   tracker` over an open Major. **RR6-1, Critical.**
2. **A second `**Phase:**`-shaped line-start item earlier in the block shadows the
   real field** (`re.search` = first match wins, unreported). **RR6-2, Major.**

Both measured below.

---

## 3. Question 3 — both directions

Nothing the templates or the three fixtures prescribe now fails.

| Conforming shape | Result |
| ---------------- | ------ |
| `./tools/check-plugin.sh` (whole tree) | `PASS` |
| `run-ok`, incl. its phase-less `- **Phase:** done (fixture)` with nothing unfinished | `PASS` |
| `run-open-rv` (leading `RVJ`) | `PASS` |
| `run-fixloop` (open `F-002`, Current State inside Phase 2) | `PASS` |
| Current State block moved to be the **last** thing in the file, field at Phase 2 | `PASS` |
| the field as `  - `, bare, `1. `, `+ ` at Phase 2 | `PASS` ×4 |
| `templates/progress.md`'s split-phase form `- **Phase:** 3a` | correctly `FAIL` — 3a *is* later than an open Phase 2; not a false failure |
| ledger ids `F-001`, `F-002a`, `N-002`, `NEW-02`, `F-2.1`, `BUG-7` as the open blocking row | all `FAIL`/gated ✅ |
| `templates/progress.md`'s own literal `**Phase:**` example (an HTML comment far below the block) | harmless — outside `_csblock`; the NEW-F1 decoy is no longer plantable by the shipped template |
| `templates/findings.md`'s narrow *Deferred Minor findings* table under the widened `_isrow` | `PASS` — rows are collected only from a blocking header, so the widening cannot mis-scope it |

I found **no** conforming shape that this diff newly fails. The over-correction
mistake of round 2 was not repeated.

---

## 4. Question 4 — regressions, and the mutants

### 4a. The `elif` chain, all four combinations

`_ph_seen`/`_na_seen` are now read, in `elif _blockers and not _named and not
(_ph_seen or _na_seen):`. Measured on `run-fixloop` (`F-002` `Major` `open`
against Phase 2, whose every box is `[x]`):

| Field present? | Phase resolvable? | Behaviour | Verdict |
| -------------- | ----------------- | --------- | ------- |
| yes | yes | branch 1/3 — advancement compared | ✅ |
| **no** | — | fail-closed `bad()` | ✅ loud |
| yes | no, but **names an id** (`Phase: 9`) | per-field `bad()` ×2, then a **false** `ok no unfinished phase` | ⚠️ **RR6-4** (Minor — build is red, so not silent) |
| yes | no, and **names nothing** (`Phase: done`, or an empty value) | **`ok no unfinished phase in the tracker` — `check-plugin: PASS`** | ❌ **RR6-1** (Critical) |

The fourth row is a **regression introduced by this commit**, and round 5 measured
its opposite. `migration-rr5-a.md:59` records NEW-F7's verification leg verbatim:

> **I1** the same phase-less field on `run-fixloop` (F-002 open) → FAIL *"…the
> advancement invariant is uncheckable on this tracker"*.

It no longer does.

### 4b. The three new mutants and the rewritten decoy — attributability

Each mutation applied by hand to a fixture copy; the table lists **every** `FAIL`
line the mutation produces, so a co-kill would show.

| Mutant | FAIL lines produced | Attributable? |
| ------ | ------------------- | ------------- |
| *run tracker loses its Phase field* | exactly 1 — the fail-closed report | ✅ its own arm (the only new code path that can produce it) |
| *run tracker grows a second Current State block* | exactly 1 — the duplicate-block report | ✅ its own arm; the first block still reads Phase 2, so nothing else objects |
| *run tracker ledger row id is not `F-<n>`* | exactly 1 — the advancement report | ✅ **reversion-verified**: with `_isrow` restored to `f-\d+`, the mutant → `check-plugin: PASS` (survives) |
| *run tracker Current State is shadowed by a prose decoy* (rewritten) | exactly 1 — the advancement report | ✅ **reversion-verified**: with `_csblock = ttext` (block isolation removed), the mutant → `check-plugin: PASS` (survives). It pins block isolation alone, as RR5-5 required. |

The `killed=159 survived=0 no-op=0` line is real and, after F-020's fix, a no-op
would have been reported and failed. Nothing rotted.

### 4c. No other regression found in this diff

`_isrow`'s widening cannot produce a false failure that I could construct: it
still requires a leading `[a-z]`, so date cells (`2026-09`), separator rows and
the `Counters`/`Iteration log` first cells do not match; `_seen_fid` is only
consulted when no blocking header exists at all. The `templates/findings.md`
addition is prose in a template and changes no gate.

---

## 5. Question 5 — the spec's four invariants

| Invariant | Holds? |
| --------- | ------ |
| **1. Advancement** — `PASS` is the only edge into `NEXT PHASE`; implementation complete is not phase complete; an empty ledger is not phase complete | **No.** The *locator* leg now holds for every shape I could construct, including all three RR5-1 shapes and fifteen loss shapes, and a future locator bug is loud (§2a, measured). But the invariant is defeated by **RR6-1** (a located field naming no phase → `check-plugin: PASS` with `ok no unfinished phase in the tracker` over `F-002 Major open`) and by **RR6-2** (an in-block decoy field shadows the real one, silently). RR6-1 is new this round; RR6-2 is a gap RR5-4 closed at block level and not at field level. |
| **2. Review ownership** (no task-level review) | **Yes.** Untouched by this diff; `== pipeline has no task-level review ==` green, its mutants killed. |
| **3. Completing an implementation task dispatches no reviewer** | **Yes.** Untouched; sweep and mutants green. |
| **4. Integration reviewer conditional on a declared boundary** | **Yes.** Untouched by this diff; boundary and conditional-integration mutants killed. |

Invariant 1's *tracker* legs (open task, open `RV`/`RVJ`, no `RV` at all, missing
fix plan) and its *ledger* leg (row-ness, width, header, multiple tables) all hold
for every shape I probed. What fails is the **Current State comparison** — the
last stage of the same arm.

---

## 6. New findings

### RR6-1 — **Critical** — `tools/check-plugin.py:2594` (the `elif` chain)

```python
        elif _blockers and not _named and not (_ph_seen or _na_seen):
```

RR5-6's guard keys off `_*_seen` — *"the field exists"* — where the branch's own
predicate is about *"the field named a phase"*. Since round 6 now **requires**
`**Phase:**` to exist, and `**Next action:**` almost always does, this branch is
close to dead code: the case *"a field is present but names no phase, and a
blocking finding is open"* falls through to `elif _phs: ok(...)`.

Measured on `run-fixloop` (`F-002` `Major` `open` against Phase 2, every box `[x]`):

```
### P1: '- **Phase:** done — nothing left' + '- **Next action:** RV — review fan-out'
      ok    no unfinished phase in the tracker
    check-plugin: PASS

### P4: '- **Phase:**' (empty value) + '- **Next action:** RV — review fan-out'
      ok    no unfinished phase in the tracker
    check-plugin: PASS
```

The affirmative line is not merely permissive, it is **false**: Phase 2 *is*
unfinished.

**This is a regression of this commit**, proven by reversion — restoring only the
pre-round-6 predicate `elif _blockers and not _named:` on an otherwise-unmodified
tree:

```
FAIL  tools/fixtures/run-fixloop/progress.md: Phase 2 has open blocking finding F-002 (major),
      and neither Current State field names a phase — … REMEDY: name the phase in `**Phase:**`
check-plugin: FAIL
```

**It also falsifies a shipped template claim**, re-opening NEW-F7.
`templates/progress.md:52-56` still says a phase-less field *"is reported as
uncheckable when something is [unfinished]: the gate cannot compare a position it
cannot locate, and it says so rather than guessing"*. It does not say so any more.

**Reachability is high, not theoretical.** `**Phase:** done` is a form the
template blesses and `run-ok` ships — and an executor writes it exactly when it
believes the run is over, which is precisely the moment it may be wrong about an
open finding. `**Next action:** RV — review fan-out` names no phase either, and
the template says it need not (that is N-004's whole point), so both fields are
routinely non-naming.

**Remedy (measured, both directions).** One expression — key the guard off what
the branch is about:

```python
        elif _blockers and not _named and not (_ph_id or _na_id):
```

Measured on an otherwise-unmodified tree: P1 → `FAIL`, P4 → `FAIL`, P3
(nonexistent phase 9) → still exactly two FAILs, so RR5-6 stays closed;
`check-plugin.sh` and all three fixtures → `PASS`; the conforming
`- **Phase:** 2` control → `PASS`.

### RR6-2 — **Major** — `tools/check-plugin.py:2531`, `:2559` (`_csblock`, `_named_phase`)

Both the presence check and `_named_phase` use `re.search` — **first match wins**,
and a second `**Phase:**`-shaped line-start item *earlier in the block* silently
becomes the field the gate reads. RR5-4 added a duplicate report at **block**
level; there is no **field**-level counterpart.

Measured on `run-fixloop`, real field advanced to `- **Phase:** 3 — advanced`, a
decoy `- **Phase:** 2 — example` inserted above it **inside** the block:

```
### plain decoy above the real advanced field   ->  ok  Current State does not point past…  / PASS
### fenced decoy (``` … ```)  above it          ->  ok  Current State does not point past…  / PASS
### HTML-comment decoy (<!-- … -->) above it    ->  ok  Current State does not point past…  / PASS
```

Silent pass over `F-002 Major open`, three ways. Note the fence and the comment
give the decoy plausible cover — a run's tracker that shows an example of the
field, or comments the previous value out instead of deleting it, plants one.

**Reachability.** This is the same executor behaviour RR5-4 exists for: appending
a fresh line rather than replacing the old one. RR5-4's own rationale — *"an
executor appending a fresh block leaves the stale one authoritative"* — applies
verbatim one level down, where a **stale** `**Phase:**` above a fresh one leaves
the stale one authoritative.

**Remedy (measured, both directions).** Symmetrical with RR5-4 — report more than
one `**Phase:**` field in the block:

```python
        if _phs and len(re.findall(_FIELDRE % "Phase", _csblock, re.M)) > 1:
            bad(f"{relpath(tracker)}: two or more `**Phase:**` fields inside "
                "the `## Current State` block, and this gate reads the first")
```

Measured with RR6-1's remedy applied on the same tree: the decoy probe → `FAIL`;
`check-plugin.sh` and all three fixtures → `PASS`; the conforming control → `PASS`.

### RR6-3 — **Minor** — `tools/check-plugin.py:2421` and `templates/findings.md:33-38`

`_isrow`'s `[a-z]{1,6}-\d+[0-9a-z.]*` requires a digit immediately after the dash
and letters only before it, so two id shapes are **still silently dropped** —
from the table walk *and* from `_seen_fid`, so nothing prints:

```
### open *Critical* row keyed NEW-F2, tracker advanced to Phase 3
      ok    Current State does not point past an unfinished phase
    check-plugin: PASS
### same, keyed RR5-2
    check-plugin: PASS
```

`NEW-F2` (letter after the dash) and `RR5-2` (digit before the dash) — **the exact
id shapes this branch's own ledger uses for rounds 4 and 5**, and the shapes the
new code comment cites as its reachability argument (*"this migration's own
ledgers use `N-`, `NEW-` and `NEW-F` ids"*): `NEW-F` is the one it does not match.

This makes the new `templates/findings.md` paragraph's claim false as written —
*"The check treats any `<letters>-<digits>` first cell as a row so an off-grammar
id is read or reported rather than silently skipped"*. It is a **claim finding** by
this skill's own rule, in a shipped template.

Minor rather than Major because the same paragraph now pins the grammar to
`F-NNN`, so a template-conforming run cannot reach it — but the honest fix is one
of: widen row-ness to `[a-z]+[0-9a-z]*-[0-9a-z.]+`, or reword the claim to promise
only what `_isrow` delivers.

### RR6-4 — **Minor** — `tools/check-plugin.py:2600-2604` (the affirmative arms)

A field naming a nonexistent phase draws its per-field `bad()` and then a **false**
affirmative:

```
FAIL  … Current State's `**Phase:**` names phase '9', which matches no `## Phase` heading …
FAIL  … Current State's `**Next action:**` names phase '9', … 
ok    no unfinished phase in the tracker        <-- false; Phase 2 has F-002 open
check-plugin: FAIL
```

The `elif _phs: ok("no unfinished phase in the tracker")` arm fires whenever no
field resolved, regardless of `_blockers`. Same class as N-008 and NEW-F6 — an
affirmative line about a comparison that did not happen — and the last remaining
one. Minor only because the build is red, so it misleads a reader rather than a
gate. The obvious guard is `elif _phs and not _blockers:`, with the `_blockers`
case owned by the branch RR6-1 repairs.

---

## 7. Was round 6's premise right?

**Yes, and it is the first change on this branch that removed a *class* rather
than an instance.** Sharing one `_FIELDRE` between the presence gate and the
resolver means the locator's exact regex has stopped being load-bearing: I
reintroduced round 5's precise bug and got a red build instead of an `ok` line.
Fifteen distinct loss shapes are loud. Rounds 1-5's five locator bugs would all be
loud today.

**But the premise was applied one layer too narrowly.** The five rounds of
locator bugs were instances of a bigger invariant: *the arm must never print an
affirmative line about a comparison it did not make*. Round 6 fail-closes on
"could not **locate** the field" and leaves two neighbouring cases open —
"located it, but it **resolved to nothing**" (RR6-1) and "located **a** field, but
not the **right** one" (RR6-2) — and in the first case the commit actively
*removed* the report that had been covering it. The generalisation that ends the
family is a single guard on the affirmative arms: `ok(...)` only when a phase was
resolved *or* `_blockers` is empty. RR6-1's and RR6-4's remedies together are that
guard.

The ledger half, for the record, has converged: six id shapes, four widths, both
decorations, two tables, and the narrow deferred table all land on the intended
side, and RR6-3 is a documented-grammar edge, not a parse gap.

---

## 8. Verdict and ship/hold recommendation

**VERDICT: FINDINGS MUST BE FIXED**

**Would I ship this branch as-is? No.**

The single reason is **RR6-1**. It is a `check-plugin: PASS` printing
`ok no unfinished phase in the tracker` over an open `Major` blocking finding —
the exact failure the whole branch exists to prevent — it is **newly introduced by
this commit**, round 5 measured the same input FAILing, and it is reachable through
a value form (`**Phase:** done`) that the shipped template blesses and a fixture
ships. Merging it would leave the branch's headline invariant weaker on this axis
than it was one commit ago, behind a green build and a template that claims
otherwise. That is the precise pattern the ledger's own preamble is a record of.

**Can each open finding gate a real run?**

| ID | Sev | Can it gate a real run? |
| -- | --- | ----------------------- |
| **RR6-1** | Critical | **No — it does the opposite, and that is worse.** It lets a run through: a run advancing past an unfinished phase gets an affirmative pass. It causes no false failure, so nothing blocks; the cost is that the gate stops being one. |
| **RR6-2** | Major | **No.** Also a let-through, never a false failure. |
| **RR6-3** | Minor | **No.** Let-through, and only for off-grammar ids the template now forbids. |
| **RR6-4** | Minor | **No.** Cosmetic on an already-red build; it weakens a reader's trust in the output, not a check. |

**None of the four can block a real run.** Every one of them only weakens a check.
That matters for the disposition: there is no operational urgency and no risk of a
false failure in the field — but it also means nothing will *surface* these except
a review, which is the argument for fixing them now rather than deferring them.

**Recommended disposition, given round 6 is the cap.** The three code remedies are
each a one-expression change, and I measured all three on a throwaway copy in both
directions (`check-plugin.sh` + all three fixtures + the conforming control still
`PASS`; all four silent paths become loud). There is no design question left open:

1. **RR6-1** — `not (_ph_id or _na_id)` in place of `not (_ph_seen or _na_seen)`. **Must fix before merge.**
2. **RR6-2** — the four-line duplicate-field report above the presence check, plus a mutant. **Should fix before merge**; it is the same class and the same commit.
3. **RR6-4** — guard the affirmative arms with `not _blockers`. Cheap; belongs in the same pass, and with (1) it completes the generalisation §7 describes.
4. **RR6-3** — either widen `_isrow` or reword `templates/findings.md`'s new paragraph so the template does not claim more than the check delivers. Deferrable as a Minor **only if the template wording is corrected in the same pass**; shipping the false claim is not acceptable, shipping the narrow grammar is.

If the cap forbids a seventh iteration, my recommendation is: apply (1), (2) and
(3) as a cap-exempt correction of a regression this commit introduced — a fix that
restores behaviour round 5 measured as working is not a new iteration of the
convergence loop — and carry (4) as a deferred Minor with the template reworded.
Hold the merge until (1) is in.

---

## 9. Probe index

| # | What | Result |
| - | ---- | ------ |
| A1-A18 | 18 locator shapes, field advanced, `F-002` open (§2b) | 15 loud FAIL, 2 read-and-FAIL, 1 correct PASS |
| B1-B6 | conforming marker forms at Phase 2 + block-last-in-file + split id | all PASS |
| C1-C8 | ledger id row-ness, open blocking row, tracker advanced | `F-002`/`F-002a`/`N-002`/`NEW-02`/`F-2.1`/`BUG-7` FAIL; `NEW-F2`/`RR5-2` PASS (RR6-3) |
| P1 | `**Phase:** done` + non-naming Next action + `F-002` open | **PASS** (RR6-1) |
| P2 | Phase field deleted | FAIL, fail-closed report |
| P3 | both fields name phase 9 | FAIL ×2 + false `ok` (RR6-4) |
| P4 | `**Phase:**` empty value + non-naming Next action | **PASS** (RR6-1) |
| R1 | revert only `not (_ph_seen or _na_seen)` → `not _named`, rerun P1 | FAIL — RR6-1 proven a round-6 regression |
| R2 | apply `not (_ph_id or _na_id)`; rerun P1/P3/P4/control/gate/3 fixtures | FAIL/FAIL(×2)/FAIL/PASS/PASS/PASS — remedy verified |
| R3 | re-narrow `_FIELDRE` to round 5's form, rerun RR5-1's `+`-bullet probe | FAIL — fail-closed guarantee verified |
| R4 | revert `_isrow` to `f-\d+`, rerun the `N-002` mutant | PASS (survives) — mutant attributable |
| R5 | `_csblock = ttext`, rerun the rewritten decoy mutant | PASS (survives) — mutant attributable |
| D1-D3 | plain / fenced / HTML-comment decoy field above the real field, in-block | **PASS** ×3 (RR6-2) |
| D4 | apply the duplicate-field report, rerun D1 + gate + 3 fixtures + control | FAIL / PASS ×5 — remedy verified |
