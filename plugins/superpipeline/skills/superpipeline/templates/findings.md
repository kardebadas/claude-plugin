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

## Blocking ledger (Critical / Major / bug)

| ID | Sev | Phase | File:line | Finding | State | Closed by |
| -- | --- | ----- | --------- | ------- | ----- | --------- |
| F-001 | Critical | 2 | `src/x.php:41` | <one line> | open | |
| F-002 | Major | 2 | `src/y.php:12` | <one line> | closed | fix `a1b2c3d` + re-review R3 covered it |

**State** is one of `open`, `closed`, `false-positive`. Closing requires either:
the fix diff touched the code the finding names **AND** a re-review whose slice
covered that fix diff reports it resolved; or the **user** ruled it a false
positive. A finding that merely stops appearing in review output stays `open`.

## Counters — the caps are enforced from HERE, not from memory

A compaction empties your context; it does not empty this table. Read these
values before every fix-mode dispatch, and write the increment **before**
dispatching, never after.

| Phase | Fix-loop iteration | Cap | Deepest fix-mode depth this chain | Cap |
| ----- | ------------------ | --- | --------------------------------- | --- |
| 2 | 2 | 5 | 1 | 2 |

Iteration counters are **per phase** (a split's siblings share the split group's
counter); depth is **per recursion chain** — Stage 4's own run of a phase is
depth 0, its first fix-mode recursion is depth 1. Reset the iteration counter by
adding a new row when a new phase starts; never edit another phase's row.

## Iteration log (convergence rule input)

One row per fix-loop iteration, written before the dispatch and completed after
the re-review.

| Iter | Phase | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | 2 | 1 | F-001, F-002 | F-001 | <timestamp> |
| 2 | 2 | 1 | F-001 | F-001 → **stop: no-progress** | <timestamp> |

**No-progress:** an ID appears in `Targeted` and again in that row's `Open
after` → stop, ask the user. **Oscillation:** a row's `Open after` set equals
any earlier row's → stop, ask the user. Neither consumes an iteration, and
neither is a judgment call — both are set comparisons over this table.

## Deferred Minor findings (Stage 5 hand-off)

Never discarded, never blocking. Stage 5 MUST present this table to the user.

| ID | Phase | File:line | Finding |
| -- | ----- | --------- | ------- |
| F-004 | 2 | `src/z.php:88` | <one line> |
