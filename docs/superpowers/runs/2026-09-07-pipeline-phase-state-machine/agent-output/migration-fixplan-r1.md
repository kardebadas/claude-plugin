# Migration — fix plan, round 1

**Findings in scope:** F-001 … F-024 (all of them: 1 Critical, 11 Major, 12 Minor)
**Out of scope, and why:** none.

**Why the Minors are in scope rather than deferred.** The skill's rule is that
Minor findings are non-blocking and defer to the Stage 5 hand-off, and that
remains right for a *phase* whose next phase is waiting. Here there is no next
phase — this is the migration's own acceptance — and every Minor sits inside a
file cluster the blocking fixes already open. Batching them costs one extra
edit each and removes a whole second round, which is this plan's own
"batch compatible findings" principle applied to itself. F-024 is additionally a
prerequisite for verifying F-004.

## Fixes

One row per fix agent, not per finding.

| # | F-IDs | Root cause | Files | Depends on | Verified by |
|---|-------|-----------|-------|------------|-------------|
| 1 | F-001, F-002, F-003, F-004, F-005, F-006, F-007, F-017, F-021, F-022, F-023 | Every new run-mode arm was written to check what a tracker *has*, never to require that the subject exist or be parseable — so an empty, unmatched or malformed subject reads as a satisfied one. Plus three narrower gaps in `lint_review_lines` and two stale comments. | `tools/check-plugin.py` | — | `./tools/check-plugin.sh`; `--run` over all three fixtures; the reviewers' own probes replayed |
| 2 | F-008, F-009, F-010, F-011, F-012, F-013, F-014, F-015, F-016, F-018 | Task 6 mirrored the conditional-integration rule into four files but not into `fix-loop.md`'s phase-REVIEW prescription or the two re-review summaries; Task 3 rewrote `parallel.md` step 6 but not step 7; and three prose sites kept pre-migration claims no sweep pattern matches. | `plugins/superb/skills/pipeline/{SKILL.md,references/fix-loop.md,references/parallel.md,references/run-state.md,references/implement.md,templates/implementer-prompt.md}` | — | `./tools/check-plugin.sh`; the no-task-review sweep; a re-read of each cited line |
| 3 | F-019, F-020, F-024, plus a new mutant for every arm row 1 adds or changes | An arm with no mutant is an arm nobody has watched fail; row 1 adds several. F-019/F-020 are the harness's own attribution and reporting defects. F-024 gives the `RVJ` arms a conforming run-mode input, which row 1's F-004 fix needs. | `tools/check-plugin-mutants.sh`, `tools/fixtures/*` | **row 1** | `./tools/check-plugin-mutants.sh` — zero `SURVIVED`, zero no-op diagnostics, and every new mutant killed by its own arm |

## Parallelism

Rows 1 and 2 touch disjoint files and may run concurrently. **Row 3 must run
after row 1**, because its mutants target arms row 1 introduces and the harness
asserts every fixture green on a clean copy first.

## Tests required

- No new test framework. The gate and the mutation harness are the tests.
- Row 1 must additionally **replay the reviewers' measured probes** — the five
  ledger-row shapes (F-001), the deleted-`RV` phase (F-002), demoted headings
  and bolded task ids (F-003), the leading-`RVJ` phase (F-004), an `N=`-keyed
  fix round (F-005), a declaration-less round (F-006), and `Phase:`-only
  advancement (F-007) — and each must now FAIL where it previously PASSed.
- Command that must be green before RE_REVIEW:
  `./tools/check-plugin.sh && for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d; done && ./tools/check-plugin-mutants.sh`

## How RE_REVIEW will check this

Three file clusters, so the round declares `C=3`. The re-review reads the **fix
diff only**, and its questions are: was each F-ID actually resolved; did any fix
introduce a regression; do the fixes interact; and — the one that matters most
here, since eleven of these findings *are* this failure — does every new or
changed arm now fail on a conforming-but-wrong input, with a mutant that kills
through that arm and no other.
