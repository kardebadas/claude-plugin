# Independent correction re-review: Superb Pipeline v2

**Verdict: materially improved, but request targeted changes before unconditional approval.**

- Repository: `kardebadas/claude-plugin`
- Reviewed published commit: `868381ed45d459cc2d0de91ae87c78502d124263`
- Previously reviewed commit: `b477cea6501e05a218a7571ece0b3d71a0ae26ec`
- Rebuild base: `8348959d1b201a873c68512642a0eb8e5754eaa8`
- Date: 2026-09-10

The published branch matched the reported corrected HEAD. The correction comprises three commits and nine changed files relative to the previous review. It is not merely a revised completion report: the relevant production predicates, tests, documentation, and a controller example changed.

## Method and evidence boundaries

I used the skill-creator, code-review, and writing-skills guidance to compare the actual published implementation with the approved design and prior AUD-01 through AUD-10 findings. I inspected the correction commits, current helper paths, relevant tests, stage instructions, and the installed-path example. Requirements came from the supplied design and plans; implementation claims came from pinned source reads, not the older plan snippets.

GitHub connector reads succeeded. Direct Git cloning failed because the host could not be resolved. Raw downloading and connector-to-container materialization were also unavailable. Therefore I could not execute the complete repository or independently rerun the reported 140 tests and 52-mutant campaign. This is an important limitation, not a passing result.

I executed ten diagnostic probes against selected transcribed production-function bodies with explicit fixture boundaries. These include positive controls, malformed-input checks, real temporary Git histories, and local initial-publication fault injection. The probe interpreter was Python 3.13.5 on Linux, not the reported Python 3.11 runtime. The macOS probe simulates Apple's documented stat output; no native macOS or Windows run occurred. No live LLM workers were dispatched.

The probe runner's OK result means its observations were reproduced, including undesirable behavior. It does not mean the branch passed acceptance. The bundle includes the exact probe source, JSON observations, and an optional runner that imports a complete locally available helper. That alternate mode still uses the documented fixtures for unrelated transaction/planning/evidence preconditions.

I could not read Codex's ignored local decision, finding, review, and final-verification records. The claimed six follow-up findings did not come with their complete texts/IDs, so I checked their visible implementation consequences rather than certifying an unseen six-item ledger.

## What improved

The correction contains real fixes:

- Duplicate JSON finding outcomes are rejected during decoding, before a dictionary can discard contradictory keys.
- Re-review reports may introduce new Open findings while preserving earlier finding introductions and round history.
- An accepted final high-risk phase can route to master review.
- The parser enforces the 12-task cap and task cycles, and initialization rejects forward/cyclic phase dependencies.
- Initial tracker publication now uses a complete synchronized temporary file and no-clobber hard linking.
- Phase review bases are bound to the phase boundary rather than arbitrary caller-selected ancestors.
- Exact decision-scope matching replaces the master '-' substring problem.
- Minor dispositions have an explicit question/authorized-fix route.
- Final verification has a durable recording operation and a discoverable terminal action with target-tip and clean-worktree checks.

These changes should be preserved. The four findings below do not justify another rebuild.

## Prior finding disposition

| Prior item | Current assessment | Validation performed here |
| --- | --- | --- |
| AUD-01: duplicate outcomes | Fixed at the reported boundary | Unique Open accepted; contradictory and identical duplicate keys rejected by the production decoder excerpt. |
| AUD-02: newly discovered re-review finding | Corrective logic present | Inspected superset acceptance, new-Open requirement, origin binding, and historical lookup; no full multi-round run here. |
| AUD-03: final required phase routing | Original defect fixed | Accepted required final phase derives `open-gate-master` with valid plan/evidence fixtures. |
| AUD-04: worker_limit=1 review | Original admission failure addressed; lifecycle remains incomplete | One-slot admission succeeds. The queue/dispatch ambiguity below remains. |
| AUD-05: '-' decision-scope collision | Corrective logic present | Caller omits the absent phase sentinel and resolver uses token-bound matching; no new full authority campaign here. |
| AUD-06: task cap/dependency cycle | Fixed at the reported parser boundary | Twelve tasks accepted; thirteen and a two-node cycle rejected. Phase dependency checks also inspected. |
| AUD-07: partial initialization | Fixed at the initial-publication primitive | Real local publication/no-clobber checks and pre/post-publication failure injection. Not a full concurrent initializer certification. |
| AUD-08: empty phase-review range | Corrective boundary check present | Inspected `_phase_review_boundary` and equality check at opening; artifact-only equal edges remain possible. |
| AUD-09: Minor fix route | Corrective lifecycle present | Inspected explicit Minor question handling, user-authorized fix targeting, and mixed-remediation handling; no complete live review run. |
| AUD-10: macOS filesystem query | **Still incorrect** | Current query checked against Apple stat documentation; realistic-output simulation fails and the erroneous mocked-output control passes. |

## R-QUEUE: review state cannot distinguish queued from already running

**Priority: Important.** This directly affects agent duplication and compaction recovery.

**Locations:** `scripts/pipeline_state.py`, `_active_worker_ids` (around 2036-2062), `_gate_next_action` (around 2182-2210), and `record_review_report` (around 4550 onward); `references/review.md`, reviewer queue description.

The implementation derives active review workers from the number of reports already recorded and the remaining capacity. It does not persist whether an individual unreported assignment has actually been dispatched.

With worker limit three and reviewers A and B, both can legitimately be running concurrently. Once A's report is recorded:

```text
active worker identities: {reviewer-b}
next action: dispatch-review-reviewer-b
```

The helper's own active accounting includes B, yet its derived action instructs dispatching B. The same state with limit one describes B waiting for its first dispatch. After B is launched, another resume before its report has no persisted fact distinguishing that launch from the pre-dispatch state.

The probes reproduced the contradictory active/action pair and repeated dispatch action. They did not launch actual duplicate LLM agents; the demonstrated defect is the missing state distinction and the instruction it produces.

**Smallest correction:** represent queued, dispatched/active, and reported review assignment status unambiguously within the existing tracker. Record start before dispatch. Derive wait/liveness-check for an already-started assignment and dispatch only for an unstarted one. Preserve the required reviewer set, immutable reports, global budget, and same gate. Do not add another scheduler.

**Regression:** two concurrent reviewers, A reports while B remains active; recover twice without a B report and never request a second B launch. Repeat with worker limit one, where B must be launched once after A releases its slot. Apply to re-review too.

## R-BATCH: a same-worker source batch can be admitted but cannot complete

**Priority: Important.** This directly affects the promised multi-task batching benefit.

**Locations:** `reserve_tasks` (around 2360-2440), `_validate_source_provenance` (around 2612-2641), and execution reference's same-executor batch contract.

`reserve_tasks` permits two independent, disjoint source tasks assigned to the same owner. It records the current target commit as the baseline for each. Consider one compatible executor working sequentially in its assigned branch:

```text
H0 -- A: T1 changes a.py -- B: T2 changes b.py
```

Both tasks were reserved at H0. T1 completes normally. For T2:

- Reporting only commit B fails because the validator expects the entire H0..B range, which includes A.
- Reporting A and B fails because a.py is outside T2's declared b.py scope.

The probe exercised the actual reservation transition with valid contextual fixtures, then made real Git commits and exercised the production provenance predicate. Both rejection paths were observed. A control with T2 starting after T1 integration, and therefore baseline A, succeeds.

This does **not** mean every form of batching is broken. Staggered task starts with the same executor are viable. The defect is an admitted simultaneous reservation whose shared-branch execution cannot meet its individual completion contracts.

**Smallest correction:** make the admitted reservation model and worker workspace contract agree. A compatible same-executor sequential batch can keep its context while reserving/starting each task only when its predecessor checkpoint/integration establishes the correct baseline. Alternatively reject the unsupported pre-reservation shape. Do not fix it by relaxing scopes, accepting unrelated commits, or forcing a fresh agent per task.

**Regression:** one executor, two source tasks, one shared branch, exact disjoint scopes, truthful separate checkpoints, and successful completion without fabricated commits. Also retain the separate-independent-worktree path.

## R-ADVANCE: the phase transition bypasses the newly documented re-verification requirement

**Priority: Important.** This is a divergence between advisory next-action logic and the mutation API.

**Locations:** `derive_next_action` (around 2260-2285), `advance_phase` (around 3084-3180), and `references/execution.md` around 215-221.

The updated instructions say that if accepted phase-review fixes advanced the code from H1 to H2, phase verification at H2 must be recorded before advancement. `derive_next_action` accordingly returns `verify-phase-01` when the old phase-verification HEAD is H1 and the accepted gate HEAD is H2.

However, `advance_phase` accepts H1 merely being an ancestor of H2, provided H2 is the target tip. It does not require the current phase-verification record to represent H2.

The probe used a real Git history containing an implementation commit H1 and later review-fix commit H2, with independently satisfied plan/task/gate fixtures:

```text
derived next action: verify-phase-01
explicit advance_phase result: current phase becomes 02
```

This is not proof that an entirely untested fix was accepted: remediation has its own evidence. The precise defect is that the mutation API does not enforce the phase-level condition the new documentation and next-action selector require.

**Smallest correction:** use the same acceptance predicate for derivation and advancement. Preserve the newest applicable verification evidence. If the required suite has already run on the same inputs/state, reuse valid evidence rather than introduce another automatic expensive test run just to move a cursor. Do not treat the advisory action as the only enforcement mechanism.

## R-MAC: AUD-10 was changed, not fixed

**Priority: Important for the advertised macOS path; not a claim of a Linux failure.**

**Locations:** `_macos_filesystem`, approximately 943-980; `test_macos_probe_reads_filesystem_metadata_not_stat_file_type`, approximately 5840 onward; README platform contract.

The previous implementation used Apple's `stat -f %T`, which reports file type. The correction now uses:

```sh
/usr/bin/stat -f %m <path>
/usr/sbin/diskutil info -plist <the-stat-output>
```

Apple's own `file_cmds/stat/stat.1` defines `m` as the modification timestamp (`st_mtime`), not the mount point. Passing a numeric timestamp to diskutil does not identify the target filesystem.

The new unit test mocks the first command's stdout as `/Volumes/Data` and asserts that `%m` was used. That mock gives the command an output it does not have on the documented platform; consequently the test certifies the wrong external-tool contract.

A simulation using a documented-form timestamp, `1789030000`, sends that timestamp to diskutil and fails. The implausible mount-path mock passes. Native macOS testing was not possible in this review.

**Smallest correction:** query actual mount/filesystem metadata using a documented macOS mechanism, with realistic fixtures. Keep native support honestly marked pending until exercised. Do not use an unknown-filesystem approval to disguise the incorrectly implemented probe.

**Primary external source:** Apple's `apple-oss-distributions/file_cmds`, `stat/stat.1`, datum definitions around lines 370-420; the fetched blob was `19291a85f335925cd67d5773d31394d640f5cac8`.

## Does the branch meet the original goal?

### Direction: yes

The skill remains a compact router with shallow stage references. It explicitly preserves user escalation, file-backed plans/progress, target-project state, selective review boundaries, two complementary master reviewers, ordinary TDD/debug repair, and bounded formal remediation rather than recursive pipeline restarts.

The correction strengthens failure handling and acceptance semantics instead of simply deleting tests. No remaining issue found here requires replacing the approved hybrid design or relaxing the zero-assumption rule.

The new final-verification transition is particularly relevant to the original compaction problem: completion now has a durable reference that can be checked against the target tip and working-tree cleanliness, rather than living only in the prior completion message.

### Reliability and efficiency: not yet demonstrated end to end

The review-dispatch ambiguity and source-batch reservation problem can recreate duplicate work and corrective state surgery. They affect the actual efficiency goal more directly than reducing a few prose lines.

The entrypoint is now approximately 225 lines, compared with the original 1,452-line router. That is a meaningful instruction-loading improvement. But the helper now exceeds 5,500 lines and the test module exceeds 6,400 lines. Those numbers do not prove poor performance or justify deleting protections; they show why router size alone is not a measurement of runtime simplicity, tokens, or elapsed time.

The added installed-path walkthrough is useful integration scaffolding. It uses one artifact-only task and synthetic review reports. It does not exercise a real source-feature implementation, same-worker source batching, parallel reviewer interruption, or actual LLM planning/review behavior. Its presence must not be described as measured end-to-end speedup.

The reported 140 tests and 52 mutants remain useful implementer evidence. The unchanged mutation harness targets shared/plugin release structure; it is not a comprehensive mutation score for every state-machine branch. No new actual-agent pressure campaign was reported after these instruction/lifecycle changes, and no comparable end-to-end performance baseline was supplied.

## What should not become another blocker

The explicitly deferred D-019/D-027 historical utilities remain a maintainability issue, not a newly discovered release blocker in this review. Preserve the recorded disposition and avoid reopening their cleanup as part of this correction.

Native Windows/macOS verification, coverage tooling availability, and the unrun Craft UI suite must remain accurately disclosed. Do not silently treat unavailable checks as passes. Whether an unavailable platform check is release-blocking follows the approved support/release policy, not an invented requirement in this report.

## Recommended bounded next step

Keep the branch and the current architecture. Make one scoped correction pass for the four items above, using focused regressions before changing production behavior. Use existing applicable verification evidence and perform the required integrated checks at the consolidated boundary, not after every tiny edit.

Then exercise one small source-project walkthrough with two sequential source tasks on the same retained executor, an explicit question/answer/resume, and a master-review queue tested at limits one and three with an interruption. Test ordinary API paths and persisted state; do not add one-off recovery exceptions just to make that scenario pass.

The result is substantially closer to the requested pipeline, but an unconditional 'all previous and lifecycle findings resolved' verdict is not supported by the current source and counterexamples.

## Source references

All repository source URLs below are pinned to the reviewed commit:

- https://github.com/kardebadas/claude-plugin/blob/868381ed45d459cc2d0de91ae87c78502d124263/plugins/superb/skills/pipeline/scripts/pipeline_state.py
- https://github.com/kardebadas/claude-plugin/blob/868381ed45d459cc2d0de91ae87c78502d124263/plugins/superb/skills/pipeline/tests/test_pipeline_state.py
- https://github.com/kardebadas/claude-plugin/blob/868381ed45d459cc2d0de91ae87c78502d124263/plugins/superb/skills/pipeline/references/execution.md
- https://github.com/kardebadas/claude-plugin/blob/868381ed45d459cc2d0de91ae87c78502d124263/plugins/superb/skills/pipeline/references/review.md
- https://github.com/kardebadas/claude-plugin/blob/868381ed45d459cc2d0de91ae87c78502d124263/plugins/superb/skills/pipeline/references/persistence.md
- https://github.com/kardebadas/claude-plugin/blob/868381ed45d459cc2d0de91ae87c78502d124263/plugins/superb/skills/pipeline/examples/controller_walkthrough.py
- https://github.com/apple-oss-distributions/file_cmds/blob/main/stat/stat.1

The source manifest records exact blob identifiers where retrieved. The report's approximate line ranges are navigation aids; function names and pinned source are authoritative.
