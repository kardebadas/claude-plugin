# Migration — fix plan, round 2

**Findings in scope:** N-001 … N-010 (2 Critical, 2 Major, 6 Minor), all raised
by the round-1 fix's own re-review.
**Out of scope, and why:** none. F-001…F-024 stay closed — the re-review
confirmed 21 outright and the three it called partial (F-002, F-007, F-022) are
re-opened here as N-002, N-001/N-004 and N-005 rather than reworded, so the
round that closed them keeps its record and this round owns the remainder.

**The shape of this round is different from round 1, and worth naming.** Round 1
fixed eleven "a gate reports success while the invariant is violated" defects.
Two of its fixes over-corrected into the opposite failure — **a gate that fails
a conforming input** (N-003, N-004) — which is worse operationally: a missed
hole is latent, a false failure blocks every real run and pressures the run into
rewriting its tracker to satisfy the linter rather than the grammar. The
template is the authority on shape; an arm that disagrees with it is wrong.

## Fixes

| # | F-IDs | Root cause | Files | Depends on | Verified by |
|---|-------|-----------|-------|------------|-------------|
| 1 | N-001, N-004, N-006, N-008 | `_named_phase` required the literal word "phase" *inside* the field value, which `**Phase:** <number and name>` never contains — so the field was unreadable on every conforming tracker, the arm rested entirely on `**Next action:**`, and its "neither field names a phase" branch then fired on the ordinary mid-run case. Plus two computed-and-unread flags that carry exactly the distinction the arm lacks, and a pass line printed after a `bad(...)`. | `tools/check-plugin.py` | — | the re-reviewer's P5/P7/P8/P11 probes, replayed |
| 2 | N-002 | F-002 asked whether a phase has *any* review line; a joining phase's leading `RVJ` satisfies that while covering the joined lanes rather than this phase, so a phase with all tasks `[x]` and no `RV` of its own is not a blocker. F-004 and F-002 read the same list and disagreed about what an `RVJ` means. | `tools/check-plugin.py` | — | a phase with a leading `RVJ` and no `RV` must FAIL |
| 3 | N-003 | The row-width check applied the blocking header's width to **every** `F-` row in the file, including the deliberately narrower *Deferred Minor findings* table the template ships. Any run that defers one Minor — the normal outcome of a review — failed the gate. | `tools/check-plugin.py` | — | the shipped `templates/findings.md` shape, and a `run-fixloop` with a deferred Minor row, must both PASS |
| 4 | N-005 | The boundary test enumerated negations, which cannot be exhaustive (`not applicable`, `nothing crosses …` both passed). Inverted: a boundary must look like a boundary. | `tools/check-plugin.py` | — | P19/P20 replayed |
| 5 | N-007 | F-008…F-011 corrected four prose sites and pinned none, so each can rot back on a green build — the failure mode this repo answers with held phrases and mutants everywhere else. | `tools/check-plugin.py`, `tools/check-plugin-mutants.sh` | rows 1–4 | a mutant per pinned phrase, each killed by its own arm |
| 6 | N-009, N-010 | The Current-State mutant wrote a shape no template produces, so it certified an arm that did nothing on the real shape; and F-016's insert broke the numbered list it sits in. | `tools/check-plugin-mutants.sh`, `references/fix-loop.md` | row 1 | harness; a re-read of the list |

## Parallelism

Rows 1–4 all edit `tools/check-plugin.py` and must run as **one** agent, in that
order. Rows 5 and 6 follow, because their mutants target arms rows 1–4 change.

## Tests required

- Replay every re-reviewer probe P1–P20; each must land on the intended side.
- **Both directions, explicitly:** every conforming shape the templates
  prescribe must PASS, and every wrong shape must FAIL. Round 1 verified only
  the second, which is how N-003 and N-004 shipped.
- Green before RE_REVIEW:
  `./tools/check-plugin.sh && for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d; done && ./tools/check-plugin-mutants.sh`

## How RE_REVIEW will check this

One file cluster carries rows 1–4 (`check-plugin.py`), so `C=1`, and the round
takes one slice reviewer. Its questions: does each N-ID close; and — the lesson
of this round — does any fix fail a shape the skill's own templates prescribe.
