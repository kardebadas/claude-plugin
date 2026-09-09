# Pipeline v2 Recovery Completion Implementation Plan

> **For agentic workers:** REQUIRED EXECUTION ROUTE: controller-led Pipeline v2 task batches using individual Superpowers skills. Do **not** invoke `superb:pipeline`, `superpowers:subagent-driven-development`, or `superpowers:executing-plans`. Workers never edit `progress.md` or spawn untracked helpers.

**Goal:** Complete and freshly verify the Pipeline v2 feature branch after loss of its prior local-only run directory, without fabricating historical task transitions or repeating already committed implementation.

**Architecture:** Treat commit `038dc667cdd4cb9d75898496b5c8180d7cf840c0` as inspected existing feature work, not as newly completed recovery tasks. One recovery phase implements the approved remaining review-evidence contract, updates its direct documentation, and captures fresh verification evidence; the normal mandatory two-reviewer master gate then reviews the complete original base-to-current-HEAD change.

**Tech Stack:** Python 3.11 standard library, `unittest`, Markdown skill/reference files, shell validation, Git.

**Spec:** `docs/superpowers/specs/2026-09-08-pipeline-rebuild-v2-design.md`

## Global Constraints

- Original rebuild base: `8348959d1b201a873c68512642a0eb8e5754eaa8`; target branch: `feat/pipeline-rebuild-v2`; global `worker_limit=3`.
- The missing 2026-09-08 local run is not reconstructed, migrated, or treated as recovered. This separate v2 run records only new recovery transitions and fresh evidence.
- Preserve zero-assumption escalation, one authoritative `progress.md`, source/artifact completion distinctions, typed scopes, review severity/acceptance rules, three-round remediation limit, v2-only resume, and local-only branch policy.
- Use behavior-focused tests without adding a numeric coverage threshold; retain existing repository gates.
- Use targeted RED/GREEN checks during implementation, one applicable integrated phase suite, two independent complementary master reviewers, and fresh final verification.
- No push, publish, PR, or merge into `main`/`master`.

## Phase map

| Phase | Plan | Depends on | Verification | Review gate |
| --- | --- | --- | --- | --- |
| recovery-01 | `docs/superpowers/plans/pipeline-rebuild-v2-recovery/phase-01.md` | none | Pipeline unit tests, plugin check, mutation check, diff/status checks | final-only; mandatory master gate follows |

## Execution order

1. Initialize and validate `docs/superpowers/runs/2026-09-09-pipeline-rebuild-v2-recovery/progress.md` from the saved phase plan and decisions.
2. Execute REC-01 with TDD, then REC-02, preserving separate source completion and integration evidence.
3. Execute REC-03 and REC-04 as artifact-only evidence tasks; neither creates an empty commit.
4. Record phase verification only after every recovery task is truthfully complete and source work is integrated.
5. Advance the final phase to the mandatory master gate. Dispatch exactly two independent complementary reviewers over base `8348959d1b201a873c68512642a0eb8e5754eaa8` and the current target-branch tip.
6. Consolidate all reports before fixes. Apply Critical/Important/Minor policy and at most three remediation rounds; unresolved choices reach the user.
7. Run fresh final verification and leave the feature branch committed and clean.
