# Migration review — findings ledger

Consolidated from `agent-output/migration-review-a.md` (state machine and prose)
and `agent-output/migration-review-b.md` (gates and evidence). Both reviewers
returned before any fix was dispatched.

**Dedup:** A's *"the no-advance arm's ledger half maps by exact label and drops
what it cannot match"* and B's `C1` are the same defect; B's is broader (four
measured shapes rather than one), so they merge into **F-001** and A's probe is
recorded as a fifth shape.

**Tiers are this skill's three:** Critical / Major / Minor. Neither reviewer
emitted `Important`.

## Blocking ledger

| ID | Sev | Area | File:line | Finding | State | Closed by |
| -- | --- | ---- | --------- | ------- | ----- | --------- |
| F-001 | Critical | gate | `tools/check-plugin.py:2126-2137` | Ledger row parse drops any row with a bolded `Sev`, a capitalised `Open`, a `Phase 2`-style cell, an extra column, or a heading whose label differs — and the arm then prints `ok` over a tracker that advanced past an open blocking finding | open | |
| F-002 | Major | gate | `tools/check-plugin.py:2110-2115` | A phase with **no** `RV` line at all is not a blocker: `any()` over an empty list is `False`, so an implementation phase that was never given a review line reads exactly like a reviewed one | open | |
| F-003 | Major | gate | `tools/check-plugin.py:1988`, `:1996`, `:2062` | `parse_tracker_phases` returning `[]` makes both new arms vacuous — review-not-early is guarded by `elif _phs:` and no-advance falls through to an affirmative pass | open | |
| F-004 | Major | gate | `tools/check-plugin.py:2062-2080` | The review-not-early arm FAILs the **legal** leading-`RVJ` joining-phase shape the skill's own templates prescribe | open | |
| F-005 | Major | gate | `tools/check-plugin.py:1608` | The fix-plan requirement is scoped to `key == "M"`, so writing `N=` on a fix round removes it entirely | open | |
| F-006 | Major | gate | `tools/check-plugin.py:1425` | A closed or appended round with no parseable declaration is `continue`d past, bypassing six arms including the two this branch added | open | |
| F-007 | Major | gate | `tools/check-plugin.py:2139-2144` | Only `**Next action:**` is read; `**Phase:**` is never checked, and a `Next action` naming no phase passes every branch | open | |
| F-008 | Major | prose | `references/fix-loop.md:65-70` | The phase REVIEW state still prescribes an integration reviewer whenever `s > 1` — the retired rule, verbatim, in the file the executor is sent to | open | |
| F-009 | Major | prose | `SKILL.md:1028`, `references/fix-loop.md:598-599` | The re-review fan-out is summarised with the retired unconditional rule, contradicting the table at `fix-loop.md:457` | open | |
| F-010 | Major | prose | `references/parallel.md:122-123` | A pre-`RV` build-gate failure is still given an F-ID and the fix loop, contradicting step 6 five lines above and four other files | open | |
| F-011 | Major | prose | `SKILL.md:672-674` | "every task takes an implementer, a reviewer and usually a fix round or two" — the retired architecture stated as fact, and no sweep pattern matches it | open | |
| F-012 | Major | prose | `templates/implementer-prompt.md:20`, `references/parallel.md:94`, `references/implement.md:74` | The `task-brief` citation appears in three forms, two of which resolve only inside this repository, while a run executes in the user's project | open | |
| F-013 | Minor | prose | `references/run-state.md:216-228` | The resume precedence table, introduced as exhaustive, has no row for a partially implemented phase | open | |
| F-014 | Minor | prose | `SKILL.md` digraph | `Stage 4b` carries a `clean / next phase` edge into `IMPLEMENT`, so a state other than `PASS` reaches the next phase | open | |
| F-015 | Minor | prose | `references/fix-loop.md` | The file that owns the fix loop never names `FIX_PLAN`, `FIX_IMPLEMENT`, `RE_REVIEW` | open | |
| F-016 | Minor | prose | `references/fix-loop.md` | The `M=0 → no round` justification is inaccurate about what such an iteration may edit | open | |
| F-017 | Minor | gate | `tools/check-plugin.py` | A linter comment still states the integration rule in its inverted (pre-migration) form | open | |
| F-018 | Minor | prose | `SKILL.md` fan-out | The reviewer fan-out — the largest dispatch class — carries no model-tier instruction | open | |
| F-019 | Minor | gate | `tools/check-plugin-mutants.sh:1585-1594` | `"run tracker declares two integration reviewers"` is co-killed by the report-count arm, so it proves nothing about its own | open | |
| F-020 | Minor | gate | `tools/check-plugin-mutants.sh` | `run_mutant` discards a mutant's own no-op diagnostics whenever the mutant is killed, hiding a rotted anchor behind a green result | open | |
| F-021 | Minor | gate | `tools/check-plugin.py` | An `M=0 → no round` record may carry a `fixplan` field and nothing objects | open | |
| F-022 | Minor | gate | `tools/check-plugin.py:1489` | The boundary test accepts any `boundary:` in the record, including one declaring an absence | open | |
| F-023 | Minor | gate | `tools/check-plugin.py` CI arm | The fixture-coverage check matches by substring, so one fixture's step can satisfy another's requirement | open | |
| F-024 | Minor | fixture | `tools/fixtures/*` | No run-mode fixture contains an `RVJ`, so the `RVJ` arms have no conforming run-mode input | open | |

## Counters

| Scope | Fix-loop iteration | Cap | Deepest fix-mode depth this chain | Cap |
| ----- | ------------------ | --- | --------------------------------- | --- |
| Migration (Phase 5) | 1 | 5 | 0 | 2 |

## Iteration log (convergence rule input)

| Iter | Scope | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | Migration | 0 | F-001..F-024 | <pending re-review> | 2026-09-07 |
