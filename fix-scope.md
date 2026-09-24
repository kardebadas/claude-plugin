# Bounded correction scope - do not redesign v2

Review target: `868381ed45d459cc2d0de91ae87c78502d124263`.

This is a proposed correction scope for user approval, not permission to alter the branch.

1. **R-QUEUE:** Distinguish a required-but-undispatched reviewer from a dispatched/unreported reviewer. Persist start before dispatch. After reviewer A finishes while B is already running, derive wait/check-liveness, not another B dispatch. Cover worker limits one and three, interruption, replay, and re-review. Retain the same gate and global budget.
2. **R-BATCH:** Align same-executor source batch reservation with per-task Git baselines. Prefer staggered starts/checkpoints/integration while retaining the executor. Do not admit two source reservations on one shared branch that require incompatible complete-baseline ranges. Preserve exact scopes/provenance; do not force a fresh agent per task.
3. **R-ADVANCE:** Make the phase advancement API enforce the same post-remediation phase-verification condition as next-action derivation and documentation. Reuse valid applicable test evidence rather than add duplicate expensive suites.
4. **R-MAC / AUD-10:** Replace the incorrect `stat -f %m` mount query. Apple's stat uses `%m` for modification time. Correct the mock to model the real external command. Keep native-platform claims bounded to actual tests.

Verify these cases against the complete checkout before editing. The included probes use selected function bodies and explicitly described fixtures; they assert observed bugs, not expected-correct final behavior. Convert them into focused repository regressions.

Do not reopen fixed AUD-01/02/03/05/06/07/08/09 without new evidence. Do not reopen the explicitly deferred historical-utility cleanup. Preserve persistent state, zero-assumption escalation, selective formal reviews, bounded remediation, and no remote/main mutation.

One consolidated fix plan, targeted red/green checks, required integrated verification, then a consolidated review. No new brainstorm-voting campaign and no recursive pipeline restart.
