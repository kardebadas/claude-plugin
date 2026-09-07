# Migration re-review — round 7 (`3779add`), the cap-exempt regression correction

Reviewer: re-reviewer A, round 7. Scope: **`git diff 85edc1f..HEAD`** only — one
commit, `3779add` *"fix(pipeline): an affirmative line requires a comparison that
happened"*. Earlier rounds are not re-reviewed.

Tiers: **Critical / Major / Minor**.

Every probe ran in a `tar --exclude=.git` copy of the tree under `mktemp -d`, with a
`reset.sh` restoring `tools/check-plugin.py` and `tools/fixtures/` between probes.
Working tree untouched: `git status --porcelain` empty before and after.

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
  killed    run tracker Phase field resolves to nothing
  killed    run tracker hides a stale Phase field above the fresh one
  killed    run tracker ledger row id has a letter after the dash

killed=162 survived=0 no-op=0
check-plugin-mutants: PASS

$ python3 -m unittest discover -s plugins/superb/skills/craft/tests 2>&1 | tail -3
Ran 19 tests in 0.453s

OK
```

`killed=159 → 162`, `no-op=0`. The three new mutants are the three added by this
commit, and each is attributed by reversion below (§4b) — none is a co-kill.

---

## 1. Question 1 — are RR6-1…RR6-4 closed?

**4 of 4 closed.** Two verified by reversion as instructed, one by reversion of the
regex, one by hand.

| ID | Closed? | Evidence |
| -- | ------- | -------- |
| **RR6-1** Critical | **yes — reversion-verified** | Probe **P1**: `run-fixloop`, `- **Phase:** done — nothing left` + `- **Next action:** RV — review fan-out`, `F-002 Major open` against Phase 2. On `3779add`: `FAIL … Phase 2 has open blocking finding F-002 (major), and neither Current State field names a phase … the advancement invariant is uncheckable on this tracker`, `check-plugin: FAIL`. **Reversion R1** — the single expression at `check-plugin.py:2628` put back to `not (_ph_seen or _na_seen)`, nothing else touched — same input → `check-plugin: PASS`. The defect returns and nothing else covers it. |
| **RR6-2** Major | **yes — reversion-verified** | Probe **D1**: stale `- **Phase:** 2 — stale, left above` inserted above `- **Phase:** 3 — fresh`, both inside the block. On `3779add`: `FAIL … two or more \`**Phase:**\` fields inside the \`## Current State\` block, and this gate reads the first …`, `check-plugin: FAIL`. **Reversion R2** — the seven-line `bad()` at `:2548-2554` deleted, nothing else touched — same input → `check-plugin: PASS` with `ok Current State does not point past an unfinished phase`. Defect returns. |
| **RR6-3** Minor | **yes — reversion-verified, both directions** | `_isrow` at `:2437-2438` is now `[a-z]+[0-9a-z]*-[0-9a-z.]+`. Probe **C**: open blocking row keyed each of `F-002`, `F-002a`, `N-002`, `NEW-02`, **`NEW-F2`**, **`RR5-2`**, `F-2.1`, `BUG-7`, `bug-7`, `F-002.1a`, tracker advanced to Phase 3 → **10 / 10 FAIL and gated**. **Reversion R4** — `_isrow` restored to `[a-z]{1,6}-\d+[0-9a-z.]*` — the `NEW-F2` case → `check-plugin: PASS` (survives). The two named shapes are closed, and the widening was the cause. `templates/findings.md`'s claim (*"any `<letters>-<digits>` first cell"*) is now literally true, so the claim finding is closed by widening the match rather than narrowing the promise, as the commit intends. Off-grammar id in a **wrong-width** row is still reported, not dropped: `FAIL … row 'NEW-F2' has 8 cells but its header has 7`. |
| **RR6-4** Minor | **yes for the case it was raised for — by hand, no mutant** | Probe **P-C**: both fields name nonexistent phase 9, `F-002` open → **exactly two** `FAIL` lines (one per field) and **zero** `ok` lines from this arm. The `elif _phs and not _blockers:` guard at `:2637` does what it was asked to do. **But the guard is narrower than the comment that ships with it** — see RR7-3: with `_blockers` *empty*, a nonexistent-phase report is still followed by `ok no unfinished phase in the tracker` (probe **P-D**), and three further shapes print an affirmative after a report from the same arm. |

---

## 2. Question 2 — is the generalisation actually complete?

**The central answer: it is complete for the Current-State *field* half, and it is
not complete for the ledger-*row* half.** The invariant the commit adopts — *the arm
must never print an affirmative line about a comparison it did not make* — is
enforced on the path from `**Phase:**`/`**Next action:**` to a phase index, and is
not enforced on the path from a `findings.md` row to `_blockers`.

### 2a. Every path to an `ok(...)` in this arm

There are exactly two, at `:2634` and `:2637`.

| # | Guard | What the line asserts | Did the comparison happen? |
| - | ----- | --------------------- | -------------------------- |
| **A** | `elif _named:` with `_blockers` non-empty and `max(_named) <= _blockers[0][0]` | "Current State does not point past an unfinished phase" | **Yes** — an index-to-index comparison ran. ✅ |
| **B** | `elif _named:` with `_blockers` empty | same line | **Yes for what it says** — no phase is unfinished, so nothing can be pointed past. Qualified by `_ledger_note` when the ledger contributed no readable row. ✅ |
| **C** | `elif _phs and not _blockers:` | "no unfinished phase in the tracker" | **Yes** — `_blockers` empty *is* the determination. `run-ok` is this path. ✅ |

Both guards are correct in their own terms. `_named` is built with `is not None`
(`:2586`), so index `0` is handled; `_ph_id`/`_na_id` are non-empty strings when set,
so the `or` in `:2628` cannot be fooled by a falsy id. **There is no path to an
affirmative on a green build where the Current-State field's comparison did not
happen.** RR6-1's class is closed structurally: the presence gate, the duplicate
gate and the resolver all share `_FIELDRE`, and the affirmative arms key off the
resolver's *result* rather than its *presence*.

### 2b. Where the generalisation stops: `_blockers` can be silently short

`_blockers` is the other operand of every comparison above, and the ledger half
builds it by `continue`-ing past anything it cannot read, in silence. Measured on
`run-fixloop` with the tracker openly advanced to Phase 3 and `F-002` the only thing
holding Phase 2 (`Major`, `open`, every box in Phase 2 `[x]`):

```
open row id  F–002 (en dash)          -> ok  Current State does not point past an unfinished phase / PASS
open row id  F—002 (em dash)          -> ok  … / PASS
open row id  F_002                    -> ok  … / PASS
open row id  2-F-001                  -> ok  … / PASS
open row id  "F - 002"                -> ok  … / PASS
open row id  "F-002 (rediscovered)"   -> ok  … / PASS
Sev cell  Blocker                     -> ok  … / PASS
Sev cell  Important                   -> ok  … / PASS
State cell  re-opened                 -> ok  … / PASS
State cell  "open (round 3)"          -> ok  … / PASS
control: State cell OPEN              -> FAIL  Current State names a phase later than Phase 2 …
```

Ten shapes, **green build**, affirmative line printed, an open `Major` gated
nothing, and `_ledger_note` is empty in each because the *other* row (`F-001`) was
read, so `_lrows == 1`. That is an `ok` about a comparison the arm did not make.
This is **RR7-1** below.

### 2c. The ledger half's own pass line and `_ledger_note`

There is no separate ledger pass line; the ledger half speaks only through
`_ledger_note` (`:2605`), appended to whichever affirmative fires. It is `""`
whenever `_lrows > 0` — i.e. whenever **at least one** row was read — so it says
nothing about rows that were *not* read. It is correct and useful for the case it
covers (no readable row at all: `run-ok`, `run-open-rv`, both of which have no
`findings.md`, both correctly qualified). It is not a completeness statement, and
nothing else supplies one: `_seen_fid` (`:2439`) is the "are there rows nobody
read?" population, and it is consulted **only** inside `if _hdr is None:` (`:2440`).
When a header *does* exist — the case every real run reaches — `_seen_fid` is
computed and discarded, and the per-row `if not _isrow(_line): continue` at `:2452`
is silent.

---

## 3. Question 3 — both directions

Nothing the templates or the three fixtures prescribe now fails. **57 conforming
probes, all PASS.**

| Conforming shape | Result |
| ---------------- | ------ |
| `./tools/check-plugin.sh` whole tree | `PASS` |
| `run-ok`, `run-open-rv`, `run-fixloop` verbatim | `PASS` ×3 |
| **`run-ok`'s `- **Phase:** done (fixture)` with no blockers** | **`PASS`** — `ok no unfinished phase in the tracker (…ledger contributed no readable blocking row…)` |
| **`**Phase:** done` on `run-fixloop` *with* `F-002` open** | **`FAIL`** — *"…and neither Current State field names a phase … uncheckable on this tracker"* |
| the same with `F-002` closed but Phase 3 still open | `FAIL`, correctly, naming **Phase 3** — the discrimination is on *blockers*, not on the word `done` |
| Phase-field marker forms at conforming Phase 2: `- `, `* `, `+ `, `1. `, none, `  - ` | `PASS` ×6 |
| ledger: 4-column blocking table (the template minimum) | `PASS` |
| ledger: `\| **F-002** \|` bolded id / `Open` state / `Phase 2` phase cell / `F-2.1` dotted id | `PASS` ×4 |
| ledger: the shipped narrow *Deferred Minor findings* table under the widened `_isrow` | `PASS` |
| ledger: a **second** blocking table with a closed row | `PASS` |
| ledger: a hyphenated-first-cell prose table (`\| run-ok \| PASS \|`) **alongside** the blocking header | `PASS` |
| `run-open-rv`'s leading `RVJ` | `PASS` |

**The `**Phase:** done` discrimination is confirmed in both directions**, and it is
the right discrimination: it turns on whether any phase is unfinished, not on the
literal value. `run-ok` (no blockers) passes; `run-fixloop` (one open `Major`) fails;
closing that finding while Phase 3 is still open still fails, and names Phase 3.

**One shape that newly fails, and it is not a regression.** The unfilled
`plugins/superb/skills/pipeline/templates/` directory, run as a run dir, gains a
second `FAIL` (its placeholder `**Phase:** <phase id FIRST…>` names no phase while
Phase 1 is open). Measured under the reverted RR6-1 guard, that directory was
**already** `check-plugin: FAIL` (`templates/agent-output does not exist`), and the
gate never visits it as a run dir (`check-plugin.sh` whole-tree is `PASS`). The new
line is also correct: an unfilled placeholder is exactly an uncheckable position.

---

## 4. Question 4 — regressions

### 4a. The widened `_isrow` — one measured false failure, one miscount

`_isrow` went from `[a-z]{1,6}-\d+[0-9a-z.]*` to `[a-z]+[0-9a-z]*-[0-9a-z.]+`.
Swept over every `*.md` in the repo, the widening newly matches **53 lines**, none
of them finding rows: `| Re-reviewer | …`, `| BASE0-2 | …`, `| A1-A18 | …`,
`| RED-B | …`, `| F-ID | Sev (r1) | …`, and the `NEW-F*`/`RR5-*`/`RR6-*` rows it was
widened *for*.

It still cannot match a **table separator** (`| -- | --- |` — no leading letter), a
**heading**, or a **prose line inside a table** (the first cell must be exactly one
hyphenated token followed by `|`; `| fail-closed reporting | …` does not match). So
no false failure arises inside a blocking table, and none of the 8 conforming ledger
probes in §3 regressed.

**The one place it bites is `_seen_fid`.** Probe **P-G1** — `findings.md` with **no
blocking header and no findings at all**, plus a probe-index table:

```
| Probe | Result |
| ----- | ------ |
| run-ok | PASS |
| re-reviewer | none dispatched |
```

```
FAIL  tools/fixtures/run-fixloop/findings.md holds 2 `F-` row(s) but no header row
      naming ID/Sev/Phase/State — …
check-plugin: FAIL
```

It holds **zero** `F-` rows. Control **P-G0** (same file, `runok`/`reviewer` without
hyphens) → `PASS`. Reversion **R4** (old `_isrow`, same file) → `PASS`. So the
widening both **causes a false failure** and **prints a false count**. This is
**RR7-2** below. It is confined to `_hdr is None`; with the blocking header present
the same prose table passes (§3).

### 4b. The three new mutants — attributability

Each mutation applied by hand to a fixture copy; the count is **every** `FAIL` line
the mutation produces, so a co-kill would show.

| Mutant | FAIL lines | Attributable? |
| ------ | ---------- | ------------- |
| *run tracker Phase field resolves to nothing* | exactly 1 — the "neither field names a phase" report | ✅ **reversion R1**: with `not (_ph_seen or _na_seen)` restored → `PASS` (survives) |
| *run tracker hides a stale Phase field above the fresh one* | exactly 1 — the duplicate-field report | ✅ **reversion R2**: with the `bad()` deleted → `PASS` (survives) |
| *run tracker ledger row id has a letter after the dash* | exactly 1 — the advancement report | ✅ **reversion R4**: with `_isrow` restored → `PASS` (survives) |

All three guards are real, single-FAIL and independently pinned. `no-op=0` is
meaningful after F-020's fix. The commit's decision to leave RR6-4 **unpinned and
say so** in the comment at `:2320-2325` is the right call and is honestly recorded —
the harness reads only pass/fail, and the guard changes nothing about pass/fail.

### 4c. No other regression

`_seen_fid` is otherwise unchanged in role. The RR6-2 duplicate-field count uses
`_FIELDRE % "Phase"`, which requires the literal `**Phase:**` — `**Phases
complete:**` does not match it — and `templates/progress.md` keeps its second
literal `**Phase:**` example inside an HTML comment *below* `## Phase 1`, outside
`_csblock`, so the shipped template cannot trip it (measured: all three fixtures and
all six marker forms `PASS`). The `docs/` additions change no gate.

---

## 5. Question 5 — the spec's four invariants

| Invariant | Holds? |
| --------- | ------ |
| **1. Advancement** — `PASS` is the only edge into `NEXT PHASE`; implementation complete is not phase complete; an empty ledger is not phase complete | **Its Current-State leg: yes, and now structurally.** RR6-1 and RR6-2 are closed by reversion; no affirmative is reachable on a green build without the field comparison; all 18 of round 6's locator shapes plus the two neighbours it missed are now loud. **Its open-blocking-F-ID leg: only for prescribed shapes.** See below. |
| **2. Review ownership** (no task-level review) | **Yes.** Untouched by this diff; sweep green, mutants killed. |
| **3. Completing an implementation task dispatches no reviewer** | **Yes.** Untouched; sweep and mutants green. |
| **4. Integration reviewer conditional on a declared boundary** | **Yes.** Untouched; boundary and conditional-integration mutants killed. |

**Invariant 1's open-blocking-F-ID leg — stated plainly.** It holds **only for
prescribed shapes**, not universally. It requires *all* of: a first cell matching
`<letters>[digits]-<alnum/dot>` with an ASCII hyphen and no trailing qualifier; a
cell count equal to the header's; a `Sev` cell normalising to exactly `critical`,
`major` or `bug`; a `State` cell normalising to exactly `open`; and a `Phase` cell
matching a `## Phase` heading. Of those five, **two are enforced loudly** (width
mismatch → reported; unmatched phase → reported) and **three fail silently** (row-ness,
`Sev` vocabulary, `State` vocabulary) — ten measured green-build let-throughs in §2b.
`templates/findings.md` pins all three vocabularies as grammar, so a
template-conforming run cannot reach them, and no ledger in this repository does
(swept: zero unread rows in every `findings.md` in the tree). The invariant is
therefore true of conforming ledgers and not true of arbitrary ones.

---

## 6. New findings

### RR7-1 — **Major** — `tools/check-plugin.py:2429`, `:2439`, `:2452`

**The generalisation is not applied to the ledger half: a row the arm cannot read is
`continue`d in silence, and then an affirmative is printed about `_blockers` as if it
were complete.** Ten measured shapes (§2b) produce `check-plugin: PASS` with
`ok Current State does not point past an unfinished phase` over an open `Major`
blocking finding, on a tracker openly advanced past the phase that owns it.

**Not a regression of this diff — pre-existing, and strictly narrowed by it.** Under
the old `_isrow` all six id shapes were dropped too, plus `NEW-F2` and `RR5-2`; this
commit removed two of the eight. I raise it because question 2 asks whether the
generalisation is complete, and this is the answer: the commit's own governing
sentence — *"never print an affirmative line about a comparison that did not
happen"* (`:2617`) — is enforced on one operand of the comparison and not the other.

**It also falsifies two claims in the gate's own comments**, which by
`templates/findings.md`'s rule is a **claim finding**:

- `:2427-2429` — *"Liberal in what counts as a row, strict in what a row must then
  satisfy: an off-grammar id is now read or reported, never dropped."* Measured
  false for `F–002`, `F—002`, `F_002`, `2-F-001`, `F - 002`,
  `F-002 (rediscovered)`, and for any off-vocabulary `Sev` or `State`. (This
  sentence is pre-existing context, not added by `3779add`.)
- `:2639-2644` — *"NO AFFIRMATIVE IN THE REMAINING CASES, and each is already
  reported"*. See RR7-3; this sentence **is** added by `3779add`.

**Can it gate a real run?** No — it is a let-through in every shape, never a false
failure.

**Remedy, in the shape the file already has.** `_seen_fid` is already the "rows
nobody read" population; it is simply switched off when a header exists. Report the
unread rows of a blocking table instead of `continue`-ing:

```python
                      if not _isrow(_line):
                          if not re.match(r"^\s*\|[\s\-:|]+\|?\s*$", _line):
                              bad(f"{relpath(_ledger)}: a row of the blocking "
                                  f"table this check could not read: {_line.strip()!r} "
                                  "— its first cell is not a finding id, so the "
                                  "row was not read and an unread row must not "
                                  "read as a closed one. REMEDY: key the row "
                                  "`F-NNN`, as `templates/findings.md` ships it")
                          continue
```
plus the same treatment for an `open` row whose `Sev` is outside the blessed set.
The claim-finding half closes by **deleting the two claims** — which, by this
skill's own rule, opens no re-review round.

### RR7-2 — **Minor** — `tools/check-plugin.py:2437-2442`

The widened `_isrow`, fed to `_seen_fid`, **newly false-fails** a `findings.md` that
has no blocking header and no findings but does contain a table with a hyphenated
first cell, and reports a **false count** while doing it (`holds 2 \`F-\` row(s)`
over zero). Measured P-G1 → `FAIL`; control P-G0 → `PASS`; reversion R4 → `PASS`
(§4a).

Minor, not Major, because the shape is not conforming — `templates/findings.md`
calls the header row *"a grammar, not a suggestion"* — and because the message's own
REMEDY (*"keep the blocking ledger's header row"*) does resolve it. **It can gate a
real run**, though: a run that writes "no blocking findings" prose instead of an
empty table, and any hyphenated first cell anywhere in the file, now goes red.

Remedy: keep `_seen_fid` on the narrow grammar (an `F-`/`<letters>-<digits>` first
cell) and count only what it can name, or scope `_seen_fid` to lines that sit under
some pipe-table header, and say `row(s) that look like finding ids` rather than
`` `F-` row(s) ``.

### RR7-3 — **Minor** — `tools/check-plugin.py:2637`, `:2639-2644`

**Four measured shapes print an affirmative after the same arm has just reported
that it cannot trust the subject it compared** — and the comment added by this
commit says there are none.

```
P-A  duplicate `**Phase:**` (stale 2 above fresh 3), F-002 open
     FAIL  … two or more `**Phase:**` fields inside the `## Current State` block …
     ok    Current State does not point past an unfinished phase     <-- FALSE: the run is at 3
P-E  duplicate `## Current State` block (second names Phase 3)
     FAIL  … two or more `## Current State` blocks …
     ok    Current State does not point past an unfinished phase     <-- FALSE
P-B  `**Phase:** 9` (nonexistent) + `**Next action:** Phase 2 …`, F-002 open
     FAIL  … `**Phase:**` names phase '9' … compared nothing
     ok    Current State does not point past an unfinished phase     <-- rests on one field only
P-D  `**Phase:** 9` on run-ok (no blockers)
     FAIL  … `**Phase:**` names phase '9' … compared nothing
     ok    no unfinished phase in the tracker                        <-- the case :2641 says is silent
```

P-A and P-E are the sharper two: the affirmative is not merely unwarranted, it is
**false about the run's actual position**, because the comparison used the stale
field / stale block the arm had just declared ambiguous. P-D is the one the new
comment names explicitly (*"a field naming a phase the tracker lacks (the per-field
arm above)"*) — the `elif _phs and not _blockers:` guard only suppresses that
affirmative when `_blockers` is non-empty.

Minor, and this is RR6-4's own tiering applied consistently: **every one of the four
is on a build that is already red**, so it misleads a reader rather than a gate.

Remedy: one flag. Set `_untrusted = True` wherever this arm `bad()`s about its own
subject (duplicate block, duplicate field, a field naming a phase the tracker
lacks), and guard both `ok(...)` calls with `not _untrusted`. That is the same
one-expression move RR6-1 made, applied to the remaining three reports, and it makes
`:2639-2644`'s sentence true as written.

---

## 7. Was the generalisation the right call?

**Yes, and on the Current-State axis it is finished.** RR6-1's remedy is not a sixth
heuristic: the presence gate, the duplicate gate and the resolver share one
`_FIELDRE`, and the affirmative arms now key off the resolver's *result*. I could
not construct a green-build affirmative that skipped the field comparison, in any of
the 24 field shapes probed. Round 5's locator bug, reintroduced, is a red build;
RR6-2's decoy, reintroduced, is a red build. Six rounds of the same defect class end
here.

**And the generalisation as *stated* is broader than the generalisation as
*shipped*.** *"The arm must never print an affirmative line about a comparison it did
not make"* has three operands, not one: the field, the tracker's phase list, and the
ledger's rows. The commit closes the first. The third still drops what it cannot
read in silence (RR7-1), and the affirmative arms still fire after the arm's own
reports about the first (RR7-3). Both are one guard each, in the file's existing
idiom, and neither needs a new parse.

The ledger half's *readable* legs — six id shapes now ten, four widths, both
decorations, two tables, the narrow deferred table, `Phase 2` cells, `Open` states —
have converged and land on the intended side in every direction I probed.

---

## 8. Verdict and ship/hold call

**VERDICT: FINDINGS MUST BE FIXED**

One Major (RR7-1) and two Minors (RR7-2, RR7-3). **No Critical.**

**Would I ship this branch now? Yes — hold only for a claims-and-guards pass, not for
a seventh parser iteration.**

The reason round 6 was held is gone. RR6-1 — `check-plugin: PASS` over an open
`Major` through a value form the template blesses — is closed and reversion-proven,
as are RR6-2, RR6-3 and RR6-4's own case. On every axis this commit is measurably
better than `85edc1f` and no conforming shape regressed. Holding the branch would
keep a proven Critical fix out of main over a gap that predates round 1.

What I would put in before merge, because it is cheap and because two of the three
items are the branch's own claim-finding rule applied to itself:

1. **RR7-3's `_untrusted` flag** (one flag, two guards) — this is what actually
   completes the sentence at `:2639-2644`, and without it that sentence is false in
   a shipped gate.
2. **Delete or reword the two false claims** named in RR7-1 (`:2429`, `:2639-2644`).
   By `templates/findings.md`'s own rule, deleting a claim opens no re-review round —
   so this does not restart the loop.
3. **RR7-2's `_seen_fid` narrowing** — it is the only item that can turn a real run
   red, and it is a two-line change.
4. **RR7-1's unread-row report** — carry as a deferred **Major** if the cap is the
   binding constraint. It is pre-existing, template-unreachable, and unreached by
   every ledger in this repository.

**Can each open finding gate a real run?**

| ID | Sev | Can it gate a real run? |
| -- | --- | ----------------------- |
| **RR7-1** | Major | **No.** Let-through only — it weakens the check, never blocks. Ten measured green-build passes over an open `Major`, all on ledger shapes the template forbids. |
| **RR7-2** | Minor | **Yes — the only one that can.** A false failure on a `findings.md` with no blocking header plus any hyphenated first cell. Off-template, and the printed REMEDY resolves it. |
| **RR7-3** | Minor | **No.** Every shape is on an already-red build; it misleads a reader, not a gate. |

---

## 9. Probe index

| # | What | Result |
| - | ---- | ------ |
| P1 | `**Phase:** done` + non-naming `Next action`, `F-002` open | **FAIL** — RR6-1 closed |
| R1 | revert `:2628` to `not (_ph_seen or _na_seen)`, rerun P1 | **PASS** — RR6-1 reversion-verified |
| D1 | stale `**Phase:** 2` above fresh `**Phase:** 3`, in-block | **FAIL** — RR6-2 closed |
| R2 | delete the `:2548` `bad()`, rerun D1 | **PASS** — RR6-2 reversion-verified |
| C1-C10 | open blocking row keyed `F-002`/`F-002a`/`N-002`/`NEW-02`/`NEW-F2`/`RR5-2`/`F-2.1`/`BUG-7`/`bug-7`/`F-002.1a`, advanced | **10 × FAIL** — RR6-3 closed |
| R4 | revert `_isrow`, rerun `NEW-F2` | **PASS** (survives) — mutant attributable |
| C11 | `NEW-F2` in a wrong-width row | **FAIL** *"row 'NEW-F2' has 8 cells…"* — reported, not dropped |
| P-C | both fields name phase 9, `F-002` open | 2 × FAIL, **0** `ok` — RR6-4's case closed |
| P-B / P-D / P-A / P-E | affirmative after a same-arm report | 4 × (FAIL + `ok`) — **RR7-3** |
| Z1-Z10 | `F–002`/`F—002`/`F_002`/`2-F-001`/`F - 002`/`F-002 (rediscovered)`/`Sev=Blocker`/`Sev=Important`/`State=re-opened`/`State=open (round 3)`, advanced | **10 × PASS** with an affirmative — **RR7-1** |
| Z11 | control `State=OPEN` | **FAIL** — the arm does work when it can read the row |
| P-G1 / P-G0 / P-G2 | no-header `findings.md` with / without hyphenated first cells / under old `_isrow` | **FAIL** / PASS / PASS — **RR7-2** |
| B1-B8 | conforming ledgers: 4-column, bolded id, `Open`, `Phase 2` cell, `F-2.1`, deferred table, prose table, second table | 8 × PASS |
| B9-B14 | Phase-field markers `- `/`* `/`+ `/`1. `/none/`  - ` at conforming Phase 2 | 6 × PASS |
| B15-B17 | the three fixtures verbatim, incl. `run-ok`'s `**Phase:** done (fixture)` | 3 × PASS |
| B18-B19 | `**Phase:** done` + `F-002` closed (Phase 3 open) / `**Phase:** done` + `F-002` open | FAIL naming Phase 3 / FAIL — discrimination confirmed |
| T1-T2 | unfilled `templates/` as a run dir, fixed vs. reverted guard | 2 FAIL / 1 FAIL — already red, not a regression |
| S1 | sweep: `_isrow` old-vs-new over every `*.md` in the tree | 53 newly matched lines, none a finding row, none inside a blocking table |
| S2 | sweep: unread rows in every `findings.md` in the tree | **0** — RR7-1 unreached in-repo |

VERDICT: FINDINGS MUST BE FIXED
