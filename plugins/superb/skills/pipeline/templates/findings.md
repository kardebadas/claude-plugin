<!--
TEMPLATE — read-only. Copy to the run directory, then delete this comment:
  <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/findings.md
-->

# Findings Ledger

IDs are assigned once at first consolidation and **never reused, renumbered or
retired**. A rediscovered finding keeps its original ID. The convergence rule
compares **ID sets**, not prose.

- **Open blocking IDs:** (none)
- **Last updated:** <timestamp>

> **An empty ledger is not a clean run.** A phase that was never reviewed leaves
> this file looking exactly like a phase that was reviewed and found nothing, so
> no check phrased as "no open blocking IDs" can tell them apart — it passes
> vacuously when the fan-out never ran. Whether review happened is recorded on
> each phase's **`RV` line in `progress.md`**, which names the F-IDs raised (or
> `no findings`) and the `agent-output/` paths. Read that, then believe this.

## Blocking ledger (Critical / Major / bug)

**The header row below is a grammar, not a suggestion.** The advancement check
locates `Sev`, `Phase` and `State` by name in this header and reads every row
beneath it until the table ends — so a header that renames `Phase` to something
else, or a row whose cell count differs from its header's, is a row the check
cannot read. It reports that rather than treating it as closed, which means a
renamed column turns into a build failure and not a silently ungated finding.
Keep the four names `ID`, `Sev`, `Phase` and `State`; add columns if you need
them, and give every row the same width as the header.

**IDs are `F-NNN`.** The check treats any `<letters>-<digits>` first cell as a
row so an off-grammar id is read or reported rather than silently skipped — but
the grammar is `F-` plus digits, and a row keyed anything else is a row whose
findings nobody guaranteed to be gated by ID. Use `F-001`, `F-002`, and keep a
rediscovered finding's original ID.

| ID | Sev | Phase | File:line | Finding | State | Closed by |
| -- | --- | ----- | --------- | ------- | ----- | --------- |
| F-001 | Critical | 2 | `src/x.php:41` | <one line> | open | |
| F-002 | Major | 2 | `src/y.php:12` | <one line> | closed | fix `a1b2c3d` + re-review R3 covered it |

**Three tiers, and no fourth.** `Sev` is `Critical`, `Major` or `Minor`. `bug`
— in this heading and in the skill's blocking list — is a **category, not a
tier**: a bug finding (a failing or vacuous test, a broken build gate, a crash)
is recorded as `Critical` or `Major` like any other blocking row, never as a
bare `bug`, because this table has no such `Sev`.

`Important` is another reviewer's vocabulary, not a tier: **an incoming
`Important` is re-tagged** on the way in. The branches below are also the
severity decider wherever this ledger has to set a tier itself — a **claim
finding** included, whatever tier it arrived under.

- **Major** if it names any of:
  - a measured behavioural defect;
  - **a requirement the plan, spec or brief mandated that the phase did not
    implement**;
  - a failing or vacuous test;
  - a broken build gate;
  - a security/PHI/data-loss reachability;
  - a fragility whose failure mode is **reachable in the code as written** (an
    unhandled empty or null case, an ordering or race dependency).
- **Minor** otherwise — where maintainability damage and merely hypothetical
  fragility ("this could break under load" with nothing shown that reaches it)
  land deliberately.

A missed requirement is Major, not deferred: nothing else in the run catches it.
Write the re-tag in the row, so a tier nobody decided cannot end up gating a
phase.

**State** is one of `open`, `closed`, `false-positive`, `withdrawn`.

`withdrawn` is **not a closure** — it is a removal, and it is narrow. A finding
is `withdrawn` when consolidation or reconciliation removes it because it is an
exact **duplicate** of another stable F-ID, **malformed** or not actually a
finding, or **superseded** by another finding that fully represents the same
issue — **and no repository change has been made for it.** It may be marked
`withdrawn` only *before* any fix commit for it exists, and `Closed by` records
which reason and **never a commit hash**:

```
withdrawn → duplicate of F-NNN | withdrawn → superseded by F-NNN | withdrawn → malformed
```

It does **not** mean the orchestrator disagrees, the finding seems low value,
ignoring it is easiest, text or code was deleted, code or tests or docs were
changed, the finding was partly fixed, or a reviewer stopped mentioning it.
Every one of those is a route *into* the fix loop. A deletion is a fix, not a
withdrawal.

Closing requires either:
the fix diff touched the code the finding names **AND** a re-review whose slice
covered that fix diff reports it resolved; or the **user** ruled it a false
positive. A finding that merely stops appearing in review output stays `open`.
A **claim finding** — one whose defect is an assertion rather than a behaviour:
a false count, a stale `file:line` citation, a wrong sole-writer claim, in
source, in a gate's own comments or in this run's reports — closes
**differently**: neither route above is open to it. It closes only by
**deleting the claim** or by **pinning it with a test** that fails when the
claim stops being true. **A rewrite is not a closure**: the corrected sentence
is still unexecuted, so nothing keeps it true as the code under it changes,
which is how a fix round raises its own successor. **Deleting the claim is a repository change and opens a
re-review round like any other fix**; a **pin** opens one too — over the test it commits, never
over the claim, because a test is a commit a reviewer can own. Its `Sev` comes
from the re-tag predicate above — `Minor` unless a branch there applies, and **a
mandated requirement the phase did not implement** is the branch a false "that
work is done" claim usually reaches.

## Counters — the caps are enforced from HERE, not from memory

A compaction empties your context; it does not empty this table. Read these
values before every fix-mode dispatch, and write the increment **before**
dispatching, never after.

| Scope | Fix-loop iteration | Cap | Deepest fix-mode depth this chain | Cap |
| ----- | ------------------ | --- | --------------------------------- | --- |
| Phase 2 | 2 | 5 | 1 | 2 |
| RVJ split 4a+4b | 1 | 5 | 0 | 2 |

**Scope** is a phase or an `RVJ` (a split or lane join). Each gets its own row
so no review arrives at a spent budget. A build-gate failure before the phase's
review has run is not a scope here at all: it is unfinished implementation,
repaired inside IMPLEMENT, and it opens no round and spends no budget.

Iteration counters are **per phase** (a split's siblings share the split group's
counter; an `RVJ` gets its **own** row, so a joint review's fix loop is not
spending a budget three siblings already used); depth is **per recursion
chain** — Stage 4's own run of a phase is
depth 0, its first fix-mode recursion is depth 1. Open a new row the moment a new **scope** starts — a phase or an `RVJ` — and
never edit another scope's row. A backfilled review opens its
own `<phase> backfill` row rather than reusing the phase's spent one.

## Iteration log (convergence rule input)

One row per fix-loop iteration, written before the dispatch and completed after
the re-review.

| Iter | Scope | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | Phase 2 | 1 | F-001, F-002 | F-001 | <timestamp> |
| 2 | Phase 2 | 1 | F-001 | F-001 → **stop: no-progress** | <timestamp> |

**No-progress:** an ID appears in `Targeted` and again in that row's `Open
after` → stop, ask the user. **Oscillation:** a row's `Open after` set equals
any earlier row's → stop, ask the user. Neither consumes an iteration, and
neither is a judgment call — both are set comparisons over this table.

## Deferred Minor findings (Stage 5 hand-off)

Never discarded, never blocking. Stage 5 MUST present this table to the user.

| ID | Phase | File:line | Finding |
| -- | ----- | --------- | ------- |
| F-004 | 2 | `src/z.php:88` | <one line> |
