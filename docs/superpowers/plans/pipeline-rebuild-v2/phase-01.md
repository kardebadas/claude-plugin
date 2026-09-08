# Pipeline v2 Phase 1 — Durable State, Recovery, and Scheduling Foundation Implementation Plan

> **For agentic workers:** REQUIRED EXECUTION ROUTE: use the approved Pipeline v2 controller and its multi-task batches. Do **not** invoke `superpowers:subagent-driven-development` or `superpowers:executing-plans`, and do not add per-task review. Every worker receives the zero-assumption contract, must not edit `progress.md`, and reports `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `PLAN_CONFLICT`, or `BLOCKED`. The controller owns all state transitions and runs the required phase review only after mechanical verification.

**Goal:** Deliver the tested Python 3.11+ v2 state helper that safely owns strict tracker state, planned-task readiness, worker-result import, recovery reconciliation, and phase/gate/remediation transitions.

**Architecture:** `pipeline_state.py` is a standard-library-only module plus CLI. It parses only the documented v2 tracker, phase-plan metadata comments, and worker-result format; malformed, legacy, missing, unknown, or unsupported data stays read-only. Each mutation is serialized by a separate run-local OS lock and replaces only `progress.md` through a flushed same-directory temporary file.

**Tech Stack:** Python 3.11+ standard library, `unittest`, Markdown templates/fixtures, Git subprocess calls, POSIX `fcntl` and the existing repository’s inspected `msvcrt` adaptation.

**Spec:** `docs/superpowers/specs/2026-09-08-pipeline-rebuild-v2-design.md`

<!-- pipeline-v2-phase: id=01; deps=none; review_gate=required; review_reason=This is the single source of execution truth and concurrency/recovery foundation consumed by every later phase; state corruption or unsafe readiness would repeat/skip work and invalidate all downstream gates. -->

## Global constraints

- Design/master-plan decisions D-001 through D-010 in `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/decisions.md` are binding; there are no open decisions at plan time.
- `progress.md` is the sole mutable authority. Plans, decisions, findings, fix plans, worker results, Git state, and reviewer reports are evidence/references, never a second tracker.
- The schema marker is exactly `pipeline-run/v2`; v1 recognition uses its legacy heading/current-state/RV/RVJ grammar, not marker absence alone, and every incompatible schema failure is read-only.
- Python helper support is Python 3.11+, cooperating local processes on one host and local filesystems. Do not claim native Windows proof before it exists; label its path exactly as D-009 requires.
- Worker limit for this rebuild is the persisted positive integer `3`; capacity, dependency, state, planned ordering, and write-scope conflicts all constrain eligibility.
- All testable behavior follows red-green-refactor. Preserve existing gates and add no numeric coverage target.
- Runtime run directories remain ignored/untracked: they survive compaction in their workspace, not deletion, machine loss, or a fresh clone.
- Execution uses approved Pipeline v2 multi-task batches and no per-task review. Phase 1 is a required high-risk review only after its integrated mechanical verification succeeds.

## Phase-plan metadata contract

The helper must read only this fixed single-line comment immediately below every task heading; it must reject a duplicate, omitted, reordered, or unknown key rather than treating arbitrary Markdown as metadata:

```markdown
&lt;!-- pipeline-v2-task: id=P1-01; deps=none; batch=state-core; order=1; write_scope=plugins/superb/skills/pipeline/scripts/pipeline_state.py,plugins/superb/skills/pipeline/tests/test_pipeline_state.py --&gt;
```

Every real task comment begins literally with `<!-- pipeline-v2-task:` and ends with `-->`; the fenced rendering above is escaped so a whole-file strict parser does not treat documentation as a second task. `id`, `deps`, `batch`, `order`, and `write_scope` are required in that order. `deps` is `none` or comma-separated stable IDs; `write_scope` is a comma-separated repository-relative allow-list. Task prose below the comment owns objective, behavior, decisions, acceptance criteria, and test commands. This phase’s metadata is deliberately parser-compatible with later phase plans.

The phase comment immediately after the plan header is also strict: its four keys must occur in the shown order. It provides the phase dependency and review classification/reason that initialize the tracker. The exact RED/GREEN and integrated verification commands remain adjacent to each task so the executor can run them verbatim; the helper uses the task comment only for readiness, dispatch conflict, and recovery decisions.

## File structure map

| Path | Responsibility | Phase 1 action |
| --- | --- | --- |
| `plugins/superb/skills/pipeline/scripts/pipeline_state.py` | Strict data model/parser, CLI, locks, atomic tracker writes, transitions, readiness/import/reconciliation | Create |
| `plugins/superb/skills/pipeline/templates/progress.md` | Canonical `pipeline-run/v2` tracker schema and field/table grammar | Rewrite |
| `plugins/superb/skills/pipeline/templates/worker-result.md` | Attempt-scoped immutable worker result/checkpoint grammar | Create |
| `plugins/superb/skills/pipeline/tests/test_pipeline_state.py` | Unit, integration, CLI, Git, process-lock, recovery, and mutation-target tests | Create |
| `plugins/superb/skills/pipeline/tests/fixtures/*.md` | Minimal valid v2 and named malformed/legacy/result/recovery inputs | Create |
| `plugins/superb/skills/pipeline/tests/fixtures/README.md` | Fixture ownership and byte-preservation expectations | Create |

Phase 1 owns only the two state-contract templates above. Phase 2 owns the prose control plane and the decisions/findings/fix-plan templates, and must consume—not redefine—the interfaces fixed here. No Phase 1 task edits `SKILL.md`, current v1 references, shared validators, CI, manifests, setup, or README.

## Batch policy and dependency graph

`state-core` is one coherent sequential multi-task batch: P1-01 → P1-02 → P1-03 → P1-04 → P1-05 → P1-06 → P1-07 → P1-08. All tasks share the parser, fixture vocabulary, helper, and test module, so parallel workers would create write conflicts and obscure red-green evidence. Checkpoints remain task-level and each successful task is imported individually, but the same executor may retain the batch in order. Before a task’s implementation marker becomes `[x]`, its result/checkpoint must identify the targeted green evidence and one or more verified implementation commits. Make a separate commit at each task checkpoint; a later narrow correction may append its commit to that already-complete task’s commit-evidence field, but no task may wait for a final batch commit to become recoverable. `worker_limit=3` is a ceiling, not a reason to split this batch. No task is eligible for dispatch until its listed dependencies, decision state, and write scope pass the helper’s readiness rules.

## Common commands

All commands run from `/tmp/claude-plugin-pipeline-rebuild-v2`.

```bash
python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state -v
python3.11 -m py_compile plugins/superb/skills/pipeline/scripts/pipeline_state.py
git diff --check
```

### P1-01 — Define the strict v2 tracker and result contracts

<!-- pipeline-v2-task: id=P1-01; deps=none; batch=state-core; order=1; write_scope=plugins/superb/skills/pipeline/scripts/pipeline_state.py,plugins/superb/skills/pipeline/templates/progress.md,plugins/superb/skills/pipeline/templates/worker-result.md,plugins/superb/skills/pipeline/tests/test_pipeline_state.py,plugins/superb/skills/pipeline/tests/fixtures -->

**Objective / behavior:** Establish one human-readable, deterministic grammar that can round-trip without losing data. The tracker has: marker, run identity (`run_id`, `base_commit`, `target_branch`, `worker_limit`, artifact paths), current phase/batch/next eligible action, task table, phase table, gate table, and remediation table. A worker result names run/task/attempt/status/checkpoints/commits/tests/evidence/concerns-or-question. No parser accepts arbitrary Markdown, hidden fields, or unknown states.

**Files:** Create the helper/test/fixture paths from the map; rewrite `templates/progress.md`; create `templates/worker-result.md`.

**Interfaces produced:**

```python
SCHEMA = "pipeline-run/v2"
class SchemaError(ValueError): ...
class Tracker: ...
class WorkerResult: ...
def parse_tracker(text: str) -> Tracker: ...
def render_tracker(tracker: Tracker) -> str: ...
def parse_worker_result(text: str) -> WorkerResult: ...
```

The task implementation-status column is exactly one of `[ ]`, `[~]`, `[?]`, or `[x]`: respectively not dispatched, controller-persisted active attempt, an attempt carrying a question/block reference, and implementation completed with validated checkpoint/result and commit evidence. Integration and verification are separate task-row facts, not implementation statuses. Worker statuses are exactly the five vocabulary values in the execution-route header. The rendered tracker must preserve the planned task/phase/gate/remediation rows and write a terminal newline.

**Applicable decisions:** D-003, D-004, D-005, D-006, D-008.

**Acceptance:** A representative valid tracker and result parse, render, and parse identically; duplicate IDs, an unknown key, a status other than `[ ]`/`[~]`/`[?]`/`[x]`, missing required row, or nonpositive `worker_limit` produce `SchemaError` with no write path invoked. The template itself is a valid minimally initialized v2 tracker after substituting its documented angle-bracket values.

- [ ] **RED — add precise contract tests and fixtures.** Add `test_valid_v2_round_trip_preserves_all_authoritative_rows`, `test_tracker_rejects_unknown_or_missing_required_fields`, and `test_worker_result_requires_attempt_scoped_status_and_evidence`. Use fixture names `valid-v2-progress.md`, `valid-worker-result.md`, `malformed-unknown-field.md`, and `malformed-worker-result.md`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.TrackerContractTest -v`

  Expected: FAIL because `pipeline_state` and its parser/contract symbols do not exist.

- [ ] **GREEN — implement the smallest strict parser and renderer.** Make the first non-comment schema line exactly `<!-- pipeline-run/v2 -->`; parse exact headings and pipe-table headers with fixed column names; refuse duplicate/extra/missing fields; use `dataclasses` and immutable parsed collections where practical. Add the two templates with a field legend that matches, rather than restates differently, the parser grammar.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.TrackerContractTest -v`

  Expected: PASS; all malformed fixtures are rejected in-memory and the valid fixture round-trips byte-for-byte through canonical rendering.

- [ ] **Refactor / task checkpoint.** Keep parsing helpers private unless named above; add a fixture README that says fixture bytes are input evidence and rejection tests compare them before/after. After targeted green evidence, create P1-01’s implementation commit, publish its result/checkpoint with that commit and evidence, and have the controller record `[x]`; do not ask for a task review.

### P1-02 — Make initialization and incompatible-schema failures safe

<!-- pipeline-v2-task: id=P1-02; deps=P1-01; batch=state-core; order=2; write_scope=plugins/superb/skills/pipeline/scripts/pipeline_state.py,plugins/superb/skills/pipeline/tests/test_pipeline_state.py,plugins/superb/skills/pipeline/tests/fixtures -->

**Objective / behavior:** Add explicit initialization and read-only validation. Initialization creates a new run directory only when it does not exist. `validate`, `inspect`, and `next` never mutate. A recognized v1 fixture is identified from `# Pipeline — Progress Tracker`, `## Current State`, and legacy task/RV/RVJ line grammar; missing marker, malformed v2, unknown marker/version, and v1 must report the run path and “no files changed.”

**Files:** Modify helper/tests; create `legacy-v1-progress.md`, `missing-marker.md`, `unknown-schema.md`, and `malformed-v2-progress.md` fixtures.

**Consumes:** P1-01 `parse_tracker`, `render_tracker`, `SchemaError`.

**Interfaces produced:**

```python
class LegacySchemaError(SchemaError): ...
def initialize_run(run_dir: Path, *, run_id: str, base_commit: str,
                   target_branch: str, worker_limit: int, artifacts: dict[str, str]) -> Tracker: ...
def validate_run(run_dir: Path) -> Tracker: ...
def inspect_run(run_dir: Path) -> dict[str, object]: ...
```

CLI forms are `init RUN_DIR --run-id ID --base-commit SHA --target-branch BRANCH --worker-limit N --spec PATH --master-plan PATH --phase-plan PATH`, `validate RUN_DIR`, `inspect RUN_DIR`, and `next RUN_DIR --phase-plan PATH`. All diagnostics have a stable error code and mention the affected path.

**Applicable decisions:** D-001, D-003, D-004, D-008.

**Acceptance:** Existing run directories are refused without byte changes; valid initialization writes only the canonical tracker; every incompatible fixture and every read-only command leaves sentinel files and tracker bytes unchanged; `next` cannot issue dispatch readiness for invalid state.

- [ ] **RED — add initialization/read-only tests.** Assert `test_initialize_refuses_existing_directory`, `test_legacy_v1_is_recognized_and_left_byte_identical`, and a table-driven test over missing/malformed/unknown schema inputs. Each test records the full directory tree and tracker bytes before invoking the command.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.InitializationAndSchemaSafetyTest -v`

  Expected: FAIL because initialization and v1-specific diagnostics are unimplemented.

- [ ] **GREEN — implement initialization and read-only CLI routing.** Use `argparse`; make error exits nonzero without tracebacks for expected schema errors. Detect legacy by the specified structural combination, never by “v2 marker absent.” Do not create a lock, temporary file, result directory, or replacement file before a read-only command has successfully parsed v2.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.InitializationAndSchemaSafetyTest -v`

  Expected: PASS; all rejected paths preserve their recorded bytes/tree and output a named v2-incompatible or schema diagnostic.

- [ ] **Task checkpoint.** Verify the CLI’s `validate`, `inspect`, and `next` use no mutation function by injecting a failing writer in their tests; retain no per-task review.

### P1-03 — Serialize mutations and atomically replace the tracker

<!-- pipeline-v2-task: id=P1-03; deps=P1-02; batch=state-core; order=3; write_scope=plugins/superb/skills/pipeline/scripts/pipeline_state.py,plugins/superb/skills/pipeline/tests/test_pipeline_state.py -->

**Objective / behavior:** Protect every mutation with a stable separate run-local lock, then read → validate → transition → validate → same-directory temporary write → flush/fsync → atomic replace → directory sync where supported → unlock. Never unlock by deleting the lock path; never fall back to an unlocked write. Reuse the repository’s Craft `session.py` distinction between POSIX `flock` and `msvcrt.locking`, adapting it rather than copying an unexamined platform assumption.

**Files:** Modify helper/tests only.

**Consumes:** P1-02 initialization/validation functions.

**Interfaces produced:**

```python
class LockBusyError(RuntimeError): ...
class LockUnavailableError(RuntimeError): ...
def locked_tracker_update(run_dir: Path, transition: Callable[[Tracker], Tracker], *, timeout_s: float) -> Tracker: ...
```

The lock path is `<run-dir>/.pipeline-state.lock`; it is distinct from `progress.md`. Contention waits only to the supplied bounded deadline and reports busy. The Windows branch is included only after using the inspected Craft implementation’s primitive selection and is documented/tested as “Implemented; simulation-tested; native Windows verification pending” until native evidence exists.

**Applicable decisions:** D-008, D-009.

**Acceptance:** Real separate processes serialize competing updates; a terminated holder releases the OS lock; a forced replacement failure leaves a complete old tracker; a reader sees a complete old or new document, never a partial one; missing primitives fail diagnostically with no write; no test removes another process’s lock file.

- [ ] **RED — add real-process and fault-injection tests.** Add `test_second_process_times_out_busy_without_writing`, `test_terminated_holder_releases_lock`, `test_replace_failure_preserves_old_tracker_bytes`, and `test_atomic_reader_observes_only_complete_versions`. Coordinate children with `multiprocessing` events/queues and a deadline, never fixed sleeps.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.AtomicMutationTest -v`

  Expected: FAIL because no lock/update primitive exists.

- [ ] **GREEN — implement lock and atomic-write primitives.** Open/create but never unlink the lock file; check that the locked descriptor still names the lock path before mutation; fsync the temporary file before `os.replace`; fsync the directory where the platform supports it; clean only this process’s known temporary file after failure. Convert primitive failure to `LockUnavailableError` and preserve tracker bytes.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.AtomicMutationTest -v`

  Expected: PASS on Linux with real contention/release/replacement evidence; simulated Windows selection test passes and native Windows remains explicitly unclaimed.

- [ ] **Task checkpoint.** Run `python3.11 -m py_compile plugins/superb/skills/pipeline/scripts/pipeline_state.py`; record the platform/evidence classification in test names or assertions, not a success claim beyond the local platform.

### P1-04 — Enforce task-level state transitions and controller ownership

<!-- pipeline-v2-task: id=P1-04; deps=P1-03; batch=state-core; order=4; write_scope=plugins/superb/skills/pipeline/scripts/pipeline_state.py,plugins/superb/skills/pipeline/tests/test_pipeline_state.py,plugins/superb/skills/pipeline/tests/fixtures -->

**Objective / behavior:** Model legal implementation-marker transitions: `[ ] → [~] → [x]`, `[~] → [?] → [~]` after an explicit answer/retry, and `[~] → [?]` for a blocked outcome. `[x]` never regresses. A controller persists `[~]`, owner, and immutable attempt before dispatch. Only a controller records `[x]` or separate integration facts; workers write result artifacts and cannot mutate the tracker.

**Files:** Modify helper/tests; add `valid-active-attempt-task.md` and `illegal-transition.md` fixtures.

**Consumes:** P1-03 `locked_tracker_update`.

**Interfaces produced:**

```python
class TransitionError(ValueError): ...
def start_task(run_dir: Path, *, task_id: str, owner: str, attempt: str) -> Tracker: ...
def record_task_question(run_dir: Path, *, task_id: str, attempt: str,
                         question_or_block_ref: str, reason: str) -> Tracker: ...
def complete_task(run_dir: Path, *, task_id: str, attempt: str,
                  worker_ref: str, commits: tuple[str, ...],
                  evidence: tuple[str, ...], repo_dir: Path) -> Tracker: ...
def record_task_integration(run_dir: Path, *, task_id: str, integration_commit: str,
                            verification: tuple[str, ...], repo_dir: Path) -> Tracker: ...
```

**Applicable decisions:** D-004, D-008.

**Acceptance:** Starting writes owner/attempt and `[~]` before a caller can observe dispatch eligibility; duplicate start, an owner/attempt mismatch, illegal completion without commit/evidence/recorded worker ref, or stale result cannot alter bytes. `[x]` requires a valid implementation commit object reachable from the recorded worker execution ref, but that commit need not yet be reachable from `target_branch`; `[x]` implementation completion is not sufficient for dependent dispatch until separate integration evidence records an integration commit reachable from `target_branch` and its verification.

- [ ] **RED — add legal/illegal transition tests.** Assert the exact row before/after `[ ] → [~] → [x]` and `[~] → [?] → [~]`, plus `test_completion_requires_commit_checkpoint_and_worker_ref`, `test_result_commit_need_not_reach_target_before_integration`, `test_integration_requires_target_branch_reachability_before_unlocking_dependents`, `test_illegal_transition_leaves_bytes_unchanged`, `test_stale_attempt_cannot_regress_or_increment`, and `test_start_persists_attempt_before_dispatch_callback`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.TaskTransitionTest -v`

  Expected: FAIL because controller task-transition APIs and provenance fields are absent.

- [ ] **GREEN — add transition validation inside the lock.** Validate identity, current marker, immutable attempt, and recorded worker execution ref before constructing a new tracker, then validate the new tracker before calling the atomic writer. Require verified checkpoint/result plus at least one valid implementation commit reachable from that worker ref before writing `[x]`; do not require target-branch reachability at this point. Store implementation commit/worker-ref/evidence and integration commit/verification in distinct columns. Only `record_task_integration` may verify that its integration commit is reachable from the tracker’s `target_branch`, record that fact, and unlock dependents.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.TaskTransitionTest -v`

  Expected: PASS; all named illegal/stale paths leave exact original bytes.

- [ ] **Task checkpoint.** After its targeted green test, commit P1-04 changes; publish/import P1-04’s checkpoint with the commit and evidence before `[x]`. Confirm task status vocabulary is not a review workflow: this task records task recovery checkpoints only, never a reviewer or a per-task gate.

### P1-05 — Parse phase metadata and calculate safe batch readiness

<!-- pipeline-v2-task: id=P1-05; deps=P1-04; batch=state-core; order=5; write_scope=plugins/superb/skills/pipeline/scripts/pipeline_state.py,plugins/superb/skills/pipeline/tests/test_pipeline_state.py,plugins/superb/skills/pipeline/tests/fixtures -->

**Objective / behavior:** Parse the fixed metadata contract at this plan’s top and return only tasks eligible for a batch. Eligibility requires: v2 state valid; phase-plan metadata valid; every dependency integrated; no unanswered decision/question; matching planned batch/order; disjoint write scope from active tasks; active workers below persisted `worker_limit`; and no active phase/gate conflict. Tasks may be sequential in one batch even where dependencies exist; a task is never automatically a worker boundary.

**Files:** Modify helper/tests; add `phase-plan-valid.md`, `phase-plan-invalid-metadata.md`, `phase-plan-write-conflict.md`, and `phase-plan-dependency-blocked.md` fixtures.

**Consumes:** P1-04 tracker state APIs and phase-plan comment grammar.

**Interfaces produced:**

```python
class PlanMetadataError(ValueError): ...
@dataclass(frozen=True)
class PlannedTask: id: str; deps: tuple[str, ...]; batch: str; order: int; write_scope: tuple[str, ...]
def parse_phase_plan(path: Path) -> tuple[PlannedTask, ...]: ...
def next_eligible_actions(run_dir: Path, phase_plan: Path, *, capacity: int | None) -> tuple[PlannedTask, ...]: ...
```

`capacity=None` is uncertainty, not permission: it returns a blocking diagnostic. `next` prints eligible stable IDs and named reasons for every withheld task without mutating tracker state.

**Applicable decisions:** D-004, D-008.

**Acceptance:** Duplicated/reordered metadata, dangling dependencies, nonpositive order, repeated task ID, an active write collision, missing limit, limit over capacity, and unresolved question all block dispatch. A recorded compatible limit queues work above the ceiling and makes a dependent task eligible only after its predecessor is integrated.

- [ ] **RED — add readiness matrix tests.** Include `test_worker_limit_is_global_across_roles`, `test_write_scope_conflict_blocks_parallel_eligibility`, `test_sequential_same_batch_dependency_becomes_eligible_after_integration`, and `test_unknown_capacity_returns_question_not_default`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.SchedulerReadinessTest -v`

  Expected: FAIL because phase-plan metadata parsing and readiness calculation are absent.

- [ ] **GREEN — implement the strict comment parser and pure readiness calculation.** Read only the fixed comment, reject any format variation, and compare repository-relative write-scope strings exactly before any later path-expansion policy is approved. Keep controller state mutation out of `next_eligible_actions`.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.SchedulerReadinessTest -v`

  Expected: PASS; each withheld task has its own dependency/capacity/question/write-conflict diagnostic.

- [ ] **Task checkpoint.** Exercise the real `next` CLI with the valid fixture; it reports P1-01-style metadata only and creates no lock/temp/tracker write.

### P1-06 — Validate and import immutable worker results idempotently

<!-- pipeline-v2-task: id=P1-06; deps=P1-04,P1-05; batch=state-core; order=6; write_scope=plugins/superb/skills/pipeline/scripts/pipeline_state.py,plugins/superb/skills/pipeline/templates/worker-result.md,plugins/superb/skills/pipeline/tests/test_pipeline_state.py,plugins/superb/skills/pipeline/tests/fixtures -->

**Objective / behavior:** Workers atomically publish attempt-scoped result files beside their final `agent-output/` location; the controller reads them, validates task/run/attempt/implementation marker/plan evidence, recorded worker execution ref, and Git commits, then imports once. A duplicate valid result is a no-op; a stale, conflicting, missing-evidence, wrong-owner, or wrong-worker-ref result is rejected with tracker bytes unchanged.

**Files:** Modify helper/result template/tests; add `valid-result-done.md`, `valid-result-needs-context.md`, `stale-result.md`, and `conflicting-result.md` fixtures.

**Consumes:** P1-01 result parser, P1-03 atomic support, P1-04 transitions, P1-05 plan metadata.

**Interfaces produced:**

```python
class EvidenceError(ValueError): ...
def publish_worker_result(path: Path, result: WorkerResult) -> None: ...
def import_worker_result(run_dir: Path, *, result_path: Path, phase_plan: Path,
                         repo_dir: Path) -> Tracker: ...
```

`DONE` and `DONE_WITH_CONCERNS` require the recorded worker execution ref plus commit/test/evidence fields and can lead only to `[x]` after controller validation. At import, every implementation commit must be a valid commit object and reachable from that recorded worker branch/worktree/ref; it need not yet be on `target_branch`. `NEEDS_CONTEXT`, `PLAN_CONFLICT`, and `BLOCKED` each require a stable question/block reference and lead to `[?]`; the latter also requires its blocking reason. Worker result import never treats a worker report as proof without controller validation.

**Applicable decisions:** D-003, D-004, D-008.

**Acceptance:** Duplicate import neither changes version/counters nor re-completes a task; a stale attempt/result/worker-ref conflict never regresses it; a correct post-commit result imports exactly once to `[x]` with its checkpoint, worker ref, and commit evidence even before target-branch integration; each of `NEEDS_CONTEXT`, `PLAN_CONFLICT`, and `BLOCKED` imports only to `[?]` with its required question/block reference; result publication never writes `progress.md`. A later integration record must prove its integration commit reaches `target_branch` before a dependent becomes eligible.

- [ ] **RED — add result-import tests with a temporary Git repository.** Assert `test_duplicate_result_import_is_idempotent`, `test_stale_or_conflicting_result_preserves_tracker`, `test_worker_result_commit_must_reach_recorded_worker_ref`, `test_worker_result_commit_can_precede_target_branch_integration`, `test_needs_context_stops_dependents_and_records_question`, `test_plan_conflict_and_blocked_results_record_question_marker_and_reference`, and `test_result_publish_is_atomic_and_never_touches_tracker`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.WorkerResultImportTest -v`

  Expected: FAIL because result publication/import and Git evidence checking are absent.

- [ ] **GREEN — implement result publication/import.** Verify each referenced commit with `git cat-file -e <sha>^{commit}` and `git merge-base --is-ancestor <sha> <worker-ref>` after resolving the result’s recorded branch/worktree/ref. Do not test `target_branch` reachability during import. Use the P1-03 atomic path for result publication and tracker import; compare imported attempt, result identity, and worker ref before transitioning so stale/conflicting evidence cannot regress or duplicate state.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.WorkerResultImportTest -v`

  Expected: PASS; result artifacts remain evidence and only controller import updates the authoritative tracker.

- [ ] **Task checkpoint.** Commit P1-06 changes before publishing/importing the P1-06 result with its targeted green evidence. Confirm a `NEEDS_CONTEXT` result changes the affected task to `[?]`, blocks affected dispatch, and does not cancel already-running independent work in the readiness model.

### P1-07 — Record integration, mechanical verification, and gate/remediation state

<!-- pipeline-v2-task: id=P1-07; deps=P1-05,P1-06; batch=state-core; order=7; write_scope=plugins/superb/skills/pipeline/scripts/pipeline_state.py,plugins/superb/skills/pipeline/tests/test_pipeline_state.py,plugins/superb/skills/pipeline/tests/fixtures -->

**Objective / behavior:** Make phase completion mechanical before formal review. A phase may be verified only when every planned task is integrated and its planned suite passed freshly on the integrated HEAD. Persist a `final-only` or `required` review classification/reason from the tracker, gate base/HEAD/reports/acceptance/open findings, and immutable remediation round identity. Required review starts only after mechanical verification; remediation starts at round one after initial round zero and cannot exceed three rounds.

**Files:** Modify helper/tests; add `valid-required-gate.md`, `valid-final-only-gate.md`, and `remediation-round-three.md` fixtures.

**Consumes:** P1-04/P1-06 task integration evidence and P1-05 phase metadata.

**Interfaces produced:**

```python
def record_phase_verification(run_dir: Path, *, phase_id: str, head: str,
                              commands: tuple[str, ...], evidence: tuple[str, ...]) -> Tracker: ...
def open_review_gate(run_dir: Path, *, gate_id: str, base: str, head: str,
                     reports: tuple[str, ...]) -> Tracker: ...
def start_remediation_round(run_dir: Path, *, gate_id: str, round_number: int,
                            finding_ids: tuple[str, ...], fix_plan: str) -> Tracker: ...
def close_review_gate(run_dir: Path, *, gate_id: str, accepted: bool,
                      open_findings: tuple[str, ...]) -> Tracker: ...
```

**Applicable decisions:** D-005, D-006, D-007, D-008.

**Acceptance:** Failed/missing fresh verification cannot open a gate; `final-only` cannot dispatch a phase reviewer; required Phase 1 stores its exact master-plan reason; round zero costs no remediation allowance; parallel fixes share one round; no-progress/oscillation/unresolved question/round-three blockers retain an unresolved gate and signal escalation rather than creating a fourth round.

- [ ] **RED — add gate/remediation transition tests.** Include `test_phase_verification_requires_all_integrated_tasks_and_fresh_commands`, `test_required_gate_carries_phase_one_master_plan_reason`, `test_initial_review_is_round_zero`, `test_parallel_fix_results_share_one_round`, and `test_round_three_blocker_refuses_acceptance`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.PhaseGateAndRemediationTest -v`

  Expected: FAIL because phase/gate/remediation APIs and persisted rows are absent.

- [ ] **GREEN — implement gate transitions under the tracker lock.** Require the configured `required` reason to equal: “This is the single source of execution truth and concurrency/recovery foundation consumed by every later phase; state corruption or unsafe readiness would repeat/skip work and invalidate all downstream gates.” Store report/fix-plan paths as references, not copied content; validate round sequence and finding identity before dispatch state changes.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.PhaseGateAndRemediationTest -v`

  Expected: PASS; phase review is impossible before mechanical verification and no unapproved fourth remediation round can be recorded.

- [ ] **Task checkpoint.** Verify this phase’s gate data records one independent reviewer only; do not conflate it with the mandatory two-reviewer master gate.

### P1-08 — Reconcile interrupted work against durable evidence and Git

<!-- pipeline-v2-task: id=P1-08; deps=P1-06,P1-07; batch=state-core; order=8; write_scope=plugins/superb/skills/pipeline/scripts/pipeline_state.py,plugins/superb/skills/pipeline/tests/test_pipeline_state.py,plugins/superb/skills/pipeline/tests/fixtures -->

**Objective / behavior:** Provide a deterministic resume/reconciliation report. It reads spec/master plan/tracker/active phase plan/decisions/findings-or-fix-plan/Git/worktree/results in that order of authority, then reconciles every `[~]` task: a validated result plus commit reachable from its recorded worker execution ref imports once to `[x]`, even before integration; consistent live owner remains `[~]`; partial/missing evidence is preserved and diagnosed; tracker/Git contradiction becomes a user question and `[?]` reference where a controller can record one. Resume separately verifies the recorded integration commit reaches `target_branch` before treating a completed task as dependency-ready. Resume never migrates/reinitializes incompatible state or redispatches `[x]` work.

**Files:** Modify helper/tests; add `interrupted-post-commit.md`, `active-attempt-consistent-owner.md`, `partial-evidence.md`, and `git-contradiction.md` fixtures.

**Consumes:** P1-02 compatibility safety, P1-05 readiness, P1-06 import, P1-07 gate state.

**Interfaces produced:**

```python
@dataclass(frozen=True)
class ReconciliationReport: actions: tuple[str, ...]; questions: tuple[str, ...]; diagnostics: tuple[str, ...]
def reconcile_run(run_dir: Path, *, phase_plan: Path, repo_dir: Path) -> ReconciliationReport: ...
```

The report is read-only except for an idempotent controller import of a fully validated result; it names each `[~]` task/attempt and its evidence path. `resume` is a controller policy consumer of this report, not a hidden migration command.

**Applicable decisions:** D-003, D-006, D-008.

**Acceptance:** An interrupted post-commit result is completed to `[x]` once with its checkpoint/worker-ref/commit evidence even when the commit is not yet on `target_branch`; a consistent live worker remains `[~]` and is not duplicated; a task without separately proven target-branch integration remains dependency-ineligible; partial/missing evidence remains intact; unaccounted/reconciled Git contradiction produces a stable user-question diagnostic; legacy/malformed input creates no artifacts; fix round identity survives interruption.

- [ ] **RED — add reconciliation fixtures and temporary-Git tests.** Add `test_post_commit_worker_ref_result_reconciles_once_before_integration`, `test_consistent_running_owner_is_not_redispatched`, `test_unintegrated_completed_task_is_not_dependency_ready`, `test_partial_evidence_is_preserved_and_diagnosed`, `test_git_state_contradiction_requires_user_question`, and `test_interrupted_remediation_keeps_same_round_number`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.ReconciliationTest -v`

  Expected: FAIL because no reconciliation report or Git/result comparison exists.

- [ ] **GREEN — implement explicit reconciliation classifications.** Build the report from files/Git each time; never infer a task outcome from memory, result filename, or a diff alone. Route only the fully validated result/worker-ref/commit/checkpoint case through P1-06’s idempotent `[x]` import; separately verify target-branch reachability only for recorded integration commits before releasing dependents. All uncertain cases preserve state and name the exact user decision needed.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.ReconciliationTest -v`

  Expected: PASS; no uncertain recovery path writes/restarts/migrates state and all known evidence classes have an explicit diagnostic.

- [ ] **Phase integration verification.** Run:

  ```bash
  python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state -v
  python3.11 -m py_compile plugins/superb/skills/pipeline/scripts/pipeline_state.py
  git diff --check
  ```

  Expected: all Phase 1 helper tests pass, syntax compiles, and whitespace check is clean. Run named fault tests once more after the whole module is integrated. Do not squash or defer recovery evidence into one final batch commit: every P1 task has already been committed and its `[x]` row names its own verified checkpoint/result and implementation commit(s); any integration-only follow-up is recorded separately in the integration field.

## Mechanical verification gate

Before the formal gate, run the Phase 1 unit/integration suite above, each valid/invalid CLI fixture command, real-process lock contention/release tests, the Python 3.11 compilation check, named replacement/read-only/idempotency mutation tests, and `git diff --check` on integrated HEAD. A failed command keeps the phase in implementation/repair; it must not be sent to formal review.

## Review gate: required

**Exact master-plan reason:** “This is the single source of execution truth and concurrency/recovery foundation consumed by every later phase; state corruption or unsafe readiness would repeat/skip work and invalidate all downstream gates.”

After the mechanical gate is green, dispatch exactly one independent reviewer over the integrated Phase 1 range. The reviewer checks strict state ownership, unsafe recovery/locking/atomic behavior, readiness/worker-limit correctness, test quality, the tracker/template contract, and D-003 through D-009. They may not review their own implementation. Critical or Important findings block, every Minor gets a persisted disposition, and remediation follows D-005/D-006 with at most three shared rounds. No later phase is eligible until this required gate is accepted.

## Phase acceptance checklist

- [ ] `pipeline_state.py` has no third-party dependencies and requires Python 3.11+ only.
- [ ] Tracker, phase plan, and worker result parsers reject uncertainty and preserve bytes on every rejected mutation path.
- [ ] Worker results, task checkpoints, scheduler readiness, integration, phase verification, review gates, and recovery reconcile through the sole tracker authority.
- [ ] Real local process evidence demonstrates locking/atomic visibility/release; unsupported/native-unverified platform claims are labeled accurately.
- [ ] The integrated Phase 1 suite and mechanical commands are fresh and green, then the required review gate is accepted.

## Execution handoff

This plan intentionally overrides the installed writing-plans SDD/executing-plans handoff. Execute P1-01 through P1-08 in the approved `state-core` Pipeline v2 multi-task batch with individual durable task checkpoints, controller-owned transitions, phase mechanical verification, and the required Phase 1 review gate. There is no per-task review and no interactive finishing menu.
