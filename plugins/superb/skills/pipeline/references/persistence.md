# Pipeline v2 persistence and recovery

Read this reference before creating, inspecting, updating, or resuming a run. `progress.md` is the single authoritative execution tracker. Plans define work; `decisions.md`, `findings.md`, fix plans, verification records, and worker results are referenced evidence, not alternate state.

Use `scripts/pipeline_state.py` as the strict Python 3.11+ standard-library helper. It supports one documented `pipeline-run/v2` Markdown format. Do not edit tracker tables by hand, infer missing fields, or introduce a second editable state file.

The CLI names are exact: `validate <run_dir>` validates v2 state, `inspect <run_dir>` returns a read-only summary, `next <run_dir> --phase-plan <path> --capacity <n>` returns advisory readiness, and `init` creates only an explicitly selected new run. Controller code uses the importable APIs such as `validate_run`, `reconcile_run`, and `import_worker_result`; do not invent a prose-only substitute transition. Worker result publication is the sole helper-call exception described below.

For a minimal executable integration from a different target repository, run
`examples/controller_walkthrough.py <installed-skill-dir> <empty-project-dir>`.
It imports the helper from the installed skill path, binds runtime capacity,
initializes a one-phase run, reserves work, publishes/imports task evidence,
verifies the phase, performs the mandatory two-report master gate, records
final verification, and proves a fresh file-backed read derives `complete`.
The example executes the commands named by its evidence, keeps local run state
under the target repository's ignore policy, and finishes only with an empty
`git status --short` result.

## Before any update or dispatch

1. Run the helper's read-only schema and filesystem-suitability validation before creating or opening the run lock.
2. Reject recognized v1, the pre-release v2 format, missing/malformed markers, unknown versions, unreadable state, known network/distributed filesystems, and changed filesystem fingerprints. Change nothing and dispatch nothing.
3. For an unknown filesystem classification, require a resolved `filesystem.authorize` decision bound to the exact run, filesystem type, and recorded fingerprint. A warning, generic approval, or prose that lacks that action grants no authority.
4. Require the run's positive persisted `worker_limit` and a fresh controller-bound runtime-capacity observation before a worker start. Capacity is global across active task owners, gate reviewers, and remediation fixers; the same owner on compatible batched tasks counts once.

Never create a replacement run during resume. A new v2 run is a separate explicit user choice in a separate directory. `initialize_run` may create `progress.md` in an existing directory only when the tracker is absent and the directory exactly matches the supplied approved artifacts; it never overwrites tracker-like or unrelated contents.
It validates the complete tracker first, publishes through a same-directory
temporary file and a no-clobber atomic link, and then synchronizes the run
directory. A failure before publication leaves no authoritative partial
tracker; a failure after publication is an uncertain outcome that must be
reconciled by run identity and tracker contents. A competing initializer's
`progress.md` is never replaced.

## Controller-owned transitions

Only the controller invokes tracker transitions. For each mutation, the helper performs this single transaction:

1. validate before lock creation;
2. acquire the stable run-local OS lock with a bounded wait;
3. re-read and revalidate state and filesystem identity;
4. validate transition preconditions and evidence;
5. derive `next_action` from authoritative facts when the transition affects it;
6. render and validate the complete new tracker;
7. write a same-directory temporary file, flush and synchronize it, atomically replace `progress.md`, then synchronize the directory where supported;
8. release the lock.

Do not fall back to an unlocked write, delete a lock because it appears stale, hold the lock while agents or tests run, truncate/reinitialize state, or update prose with find-and-replace.

Lock acquisition failures, write failures, and replacement/synchronization failures are different outcomes. Before replacement, report the actual failure, preserve the old tracker, and remove only this invocation's known temporary file. After replacement, a later synchronization failure means the update **may have applied**: do not claim unchanged state, roll back, or blindly retry. Re-read under the lock and reconcile the stable revision/transition, result, attempt, or round identity so the operation cannot apply twice.

`inspect` and status/next reads are strictly read-only. They may derive the correct action and report a stale persisted summary, but they do not repair or rewrite it.

## Tasks and worker results

Persist `[~]`, controller-assigned owner, and attempt before dispatch. `start_task` handles only the first `[ ]` to `[~]` start. After a blocked `[?]` attempt receives an applicable explicit answer, `resume_task` requires the matching prior attempt, a distinct unused new attempt, its assigned owner, and the resolved `task.resume` decision reference. Context/session recovery alone does not create another attempt.

Workers never edit `progress.md`. A worker may invoke only `publish_worker_result` for its own assigned immutable result. Only the controller performs tracker transitions and result import. Workers atomically publish immutable attempt-scoped result files using `templates/worker-result.md`. Every result copies the assigned `run_id`, `task_id`, `attempt`, and `owner`; import validates all four together under the lock for every status and both task kinds. Never infer a missing owner or rewrite tracker ownership to fit incoming evidence. A superseded-attempt result is stale even when the owner is unchanged. An exact accepted-result replay is a no-op only when its persisted identity and content digest match; changed content or identity is conflicting evidence.

A plan-declared `source` task records its exact target-branch baseline at each
start/resume, then requires the complete nonempty baseline-to-source commit
range, in-scope changed paths, and digest-bound typed task-suite PASS evidence
before `[x]`; integration remains separate. A plan-declared `artifact` task
requires exactly its approved output paths plus validation evidence, records
integration `N/A`, and never invents an empty or unrelated commit. Workers
cannot choose task kind from whether a diff exists. Keep every task's
checkpoints recoverable inside a multi-task batch.

For history-preserving source integration, every recorded implementation commit
must be an ancestor of the integration commit, the integration commit must be
an ancestor of the designated target branch, and one digest-bound typed
`task-integration` PASS record must identify that exact integrated state. An
unrelated reachable target commit or a SHA embedded in arbitrary prose is not
integration proof. No squash/rebase/cherry-pick equivalence is assumed.

## File-first resume and reconciliation

On compaction, restart, interruption, or uncertainty:

1. validate the run identity/schema and filesystem contract;
2. read the approved design, master plan, `progress.md`, active phase plan, and applicable `decisions.md` entries;
3. read `findings.md` and the active fix plan when review remediation is active;
4. inspect Git branch, worktrees, commits, and immutable worker-result/evidence files;
5. reconcile every `[~]` assignment before starting new work;
6. derive the next permitted action from task, integration, question, phase-verification, gate, and remediation facts.

If a valid result and Git/evidence satisfy the contract, import it once. If an owner is still active consistently, preserve the attempt and wait or perform independent permitted work. A commit without its result/checkpoint is neither automatic completion nor grounds to repeat the task: inspect the recorded attempt, content, ancestry, and applicable tests, then reconstruct/import only independently validated evidence. Partial, conflicting, or unverifiable state remains blocked and reaches the user. Completed work is not rerun; unfinished work is not skipped.

An active formal review is recovered the same way: validate every digest-bound
checkpointed report in recorded assignment order, retain the complete required
reviewer set, and derive the first unreported assignment. A completed report
releases that reviewer's global worker slot; it is not discarded merely because
the remaining assignment must run later. Do not infer a completed reviewer from
conversation memory or a mutable uncheckpointed report.

The master plan is the exact ordered authority for its phase-plan paths.
Initialization rejects missing, extra, duplicate, or reordered phase
references, phases with more than 12 tasks, cyclic task dependencies, and
unknown, cyclic, or forward phase dependencies. Every reservation/start
rechecks the current phase's declared phase dependencies and required
predecessor gates.

When a remediation round starts, store the fix plan as its repository-relative
path plus SHA-256 digest. Recovery resolves and revalidates that immutable
identity before returning `resume-remediation`; a missing, unreadable,
outside-workspace, ambiguous, or changed plan is a blocking contradiction, not
an empty scope or permission to redispatch.

## Decisions and authority

Use `templates/decisions.md`. The heading supplies the stable decision ID. Preserve the exact question, explicit answer, sources, scope, and status. Every entry has exactly one `Decision action`: `task.resume`, `review.resolve-question`, `filesystem.authorize`, `remediation.start-round`, or `none`. Match that exact action plus the helper's action-specific scope/state/identity fields. Never derive transition authority from answer wording, generic plan approval, another agent's preference, or a fieldless historical entry.

An unresolved or conflicting required choice blocks only dependent work: record it, ask the user, preserve independent results, then resume only after the applicable answer is recorded. Preserve prior attempts, results, questions, commits, review history, and remediation counters.

## Supported platform contract

The supported contract is cooperating processes on one host over a local filesystem with working OS-backed locks, hard links for no-clobber initial publication, and same-filesystem atomic replacement semantics. Linux and macOS use POSIX locking. On macOS, determine the containing mount with `stat -f %m` and obtain the filesystem type from `diskutil info -plist`; a file-type format token is not filesystem metadata. Linux is the native platform exercised by this rebuild; do not report macOS as natively tested without a macOS run. The Windows standard-library path is **Implemented; simulation-tested; native Windows verification pending** until a native Windows runner proves process contention, replacement, interruption/recovery, and lock release.

Network/distributed filesystems and cross-host synchronization are outside the guarantee. Do not claim the helper can recognize every unusual filesystem or provide universal crash/power-loss durability. Distinguish cooperative-writer exclusion, atomic visibility of a complete old or new tracker, process-interruption reconciliation, and durability across OS crash or power loss.

Ignored local run files survive context compaction in the same workspace, not deletion, machine loss, or a fresh clone.
Terminal `complete` is also conditional on the designated target repository
remaining at the accepted master HEAD with a clean working tree, including no
unexpected untracked files. The final-verification transition is bound to the
run's derived project root; a different repository path cannot supply the Git
proof. A fresh inspect reports inconsistent state instead of trusting a stale
persisted `complete` summary when those facts no longer hold.
