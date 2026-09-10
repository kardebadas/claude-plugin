# Pipeline v2 Focused Correction Plan

**Scope:** Correct only R-QUEUE, R-BATCH, R-ADVANCE, and R-MAC on `feat/pipeline-rebuild-v2`, preserving the approved Pipeline v2 architecture and remediation history. This pass is executed directly by the controller with individual Superpowers skills; neither the installed `superb:pipeline` nor subagent-driven development orchestrates its own correction.

**Verified starting point:** `868381ed45d459cc2d0de91ae87c78502d124263`. Complete-helper lifecycle probes reproduced all four findings before this plan was written. The attached evidence bundle was not present in the shared filesystem; `fix-scope.md`, `review.md`, the current helper, and actual-helper reproductions are the available evidence.

## Task 1 — Persist reviewer dispatch state (R-QUEUE)

Files:
- Modify `plugins/superb/skills/pipeline/scripts/pipeline_state.py`
- Modify `plugins/superb/skills/pipeline/tests/test_pipeline_state.py`
- Modify only directly affected review/execution references and templates if their contract changes

Red: reproduce through a real initialized run that, after reviewer A reports while reviewer B is already dispatched, recovery says to dispatch B again. Cover worker limits 1 and 3, out-of-order reports, interruption/replay, and re-review.

Green: add the smallest controller-owned transition that persists each reviewer start before dispatch. Keep the complete required reviewer set separate from active reservations. Derive capacity and next action from persisted undispatched/active/reported states; never infer dispatch from report count. Preserve independent assignments, report binding, idempotency, and the existing global worker limit.

## Task 2 — Stagger same-owner source work (R-BATCH)

Files:
- Modify `plugins/superb/skills/pipeline/scripts/pipeline_state.py`
- Modify `plugins/superb/skills/pipeline/tests/test_pipeline_state.py`
- Modify only directly affected execution documentation

Red: reserve two source tasks for one owner on one branch, then prove the second task cannot truthfully satisfy both its baseline provenance and write scope after the first task's commit. Retain controls for independent owners and artifact work.

Green: reject simultaneous same-owner source reservations. The same compatible executor may be retained, but each later source task starts only after the prior task checkpoint/integration, so it receives a fresh baseline. Do not relax provenance or write-scope validation.

## Task 3 — Enforce post-remediation verification at advancement (R-ADVANCE)

Files:
- Modify `plugins/superb/skills/pipeline/scripts/pipeline_state.py`
- Modify `plugins/superb/skills/pipeline/tests/test_pipeline_state.py`

Red: build a real two-phase lifecycle whose accepted required gate has a post-remediation HEAD newer than the phase verification evidence; confirm `derive_next_action` requires verification while `advance_phase` incorrectly advances.

Green: make `advance_phase` enforce the same applicable-code-state predicate as derivation. Reuse applicable evidence; reject without byte changes until verification is recorded for the gate HEAD.

## Task 4 — Use real macOS filesystem metadata (R-MAC)

Files:
- Modify `plugins/superb/skills/pipeline/scripts/pipeline_state.py`
- Modify `plugins/superb/skills/pipeline/tests/test_pipeline_state.py`
- Modify directly affected platform documentation

Red: use realistic macOS `stat -f %m` output and show that the helper passes a modification-time value to `diskutil`; replace the misleading mount-point mock.

Green: use documented standard-library/subprocess-compatible filesystem metadata for the containing filesystem (a parsed `/bin/df -P <path>` mount point followed by existing `diskutil info -plist` validation). Reject malformed/ambiguous output. Keep macOS native verification explicitly pending.

## Consolidated verification and review

1. Run the focused test methods/modules while each correction is developed.
2. Run the complete Pipeline v2 unit suite, plugin validation, mutation campaign, compilation, and `git diff --check` on the integrated patch. Record commands, elapsed times, environment, and reviewed commit.
3. Commit the bounded correction with explicit paths.
4. Request one independent, focused re-review of this four-finding diff and applicable evidence. Address any verified blocker under the existing remediation policy; do not create a new review layer.
5. Run fresh final applicable checks if review changes the patch. Leave the feature branch committed and unpushed.
