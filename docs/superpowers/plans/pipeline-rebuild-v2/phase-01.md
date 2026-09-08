# Pipeline v2 Phase 1 — Durable State, Recovery, and Scheduling Foundation Implementation Plan

> **For agentic workers:** REQUIRED EXECUTION ROUTE: follow the rebuild-only bootstrap below until the named v2 helper capability has passed its tests; then use only the capabilities that exist. Neither the old Pipeline nor the unfinished v2 Pipeline orchestrates this rebuild. Do **not** invoke `superpowers:subagent-driven-development` or `superpowers:executing-plans`, and do not add per-task review. Every worker receives the zero-assumption contract, must not edit `progress.md`, and reports `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `PLAN_CONFLICT`, or `BLOCKED`.

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

## Rebuild-only bootstrap and adoption point

This section applies only to implementation of Pipeline v2 in run `2026-09-08-pipeline-rebuild-v2`. It is not installed as a future Pipeline path and is not legacy migration.

1. Before P1-04 is green, the coding-session controller reads the approved design, master plan, this phase plan, decisions, and the existing sole rebuild `progress.md`; it uses the individual Superpowers skills directly. The controller manually records `[~]`, owner/attempt, result path, Git commit, and test evidence in that same tracker before/after work. It never calls an unimplemented parser, transition, readiness, or result-import API.
2. P1-01 can therefore begin after its explicit plan dependencies are checked by the controller. The controller writes `[~]` in the existing tracker, performs the planned RED/GREEN cycle, commits the source, writes `agent-output/bootstrap-P1-01.md` with stable task/attempt/commit/test identity, verifies the commit and test output, and records `[x]`. P1-04/P1-05/P1-06 are not invoked.
3. P1-02 and P1-03 follow the same file-backed checkpoint procedure. P1-02 implements ordinary future-run initialization; it does not initialize or overwrite this existing bootstrap tracker.
4. After the P1-01 tracker/result and phase-plan parsers, P1-03 atomic replacement, and P1-04 task transitions pass their targeted tests, the controller commits P1-04, writes `agent-output/bootstrap-P1-04.md`, verifies its commit and test evidence, and manually records P1-04 `[x]` in the same bootstrap tracker. It then snapshots that tracker text as immutable `agent-output/bootstrap-progress-snapshot.md`, renders one canonical v2 state for the same run/checkpoints, validates it with `parse_tracker`, acquires `.pipeline-state.lock`, and atomically replaces the same `progress.md`. The snapshot is evidence, not an editable tracker. No P1-06 import API is called, no transitions/counters are replayed, and no second live tracker exists.
5. The controller admits P1-05 from the approved dependency graph and records its start with the now-tested transition API; readiness remains a manual plan check until P1-05 passes. P1-05 governs subsequent reservations, and P1-06 enables normal result import. Reconciliation verifies every adopted checkpoint against its immutable result, tests, and Git evidence.

Ordinary `initialize_run` may create a tracker in a pre-created run directory only when `progress.md` is absent, every existing entry is one of the explicitly supplied approved artifact paths, and no schema-like or recognized v1 tracker exists. It never overwrites a tracker or unrelated artifact. Existing valid v2 is resumed; existing invalid/legacy/unknown state is rejected unchanged. This rule lets a user deliberately create plans/decisions before initialization without weakening D-003.

## Phase-plan metadata contract

The helper must read only this fixed single-line comment immediately below every task heading; it must reject a duplicate, omitted, reordered, unknown key, or unsupported scope rather than treating arbitrary Markdown as metadata:

```markdown
&lt;!-- pipeline-v2-task: id=P1-01; deps=none; kind=source; batch=state-core; order=1; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py; outputs=none --&gt;
```

Every real task comment begins literally with `<!-- pipeline-v2-task:` and ends with `-->`; the fenced rendering above is escaped so a whole-file strict parser does not treat documentation as a second task. `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, and `outputs` are required in that order. `deps` is `none` or comma-separated stable IDs. `kind` is `source` or `artifact` and only the approved task definition may set it. Each scope is exactly `file:<repository-relative-file>` or `tree:<repository-relative-directory>`; absolute paths, `.`/`..`, empty segments, backslashes, symlink-dependent aliases, and glob syntax are rejected rather than normalized. File equality, tree ancestry, and file containment under a tree are conflicts. `outputs` is `none` for source tasks and a comma-separated exact repository-relative file list for artifact tasks; it cannot contain directories or patterns, and every output must fall within `write_scope`. These identities remain repository-relative across worktrees.

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

`state-core` is one coherent sequential multi-task batch: P1-01 → P1-02 → P1-03 → P1-04 → P1-05 → P1-06 → P1-07 → P1-08. All tasks share the parser, fixture vocabulary, helper, and test module, so parallel workers would create write conflicts and obscure red-green evidence. Checkpoints remain task-level. P1-01 through P1-04 use the documented manual bootstrap checkpoints and are seeded once during canonical adoption; they are not retroactively imported as if P1-06 had existed. P1-05 uses the tested transition primitive after controller dependency review; P1-06 and later use normal result import once available. Every Phase 1 source task requires targeted green evidence and verified implementation commits, with separate complete integration ancestry. Make a separate commit at each checkpoint. `worker_limit=3` is a ceiling, not a reason to split this batch. Before P1-05, the controller checks the approved dependency graph directly; after P1-05, helper reservation rules apply.

## Common commands

All commands run from `/tmp/claude-plugin-pipeline-rebuild-v2`.

```bash
python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state -v
python3.11 -m py_compile plugins/superb/skills/pipeline/scripts/pipeline_state.py
git diff --check
```

### P1-01 — Define the strict v2 tracker, result, and phase-plan contracts

<!-- pipeline-v2-task: id=P1-01; deps=none; kind=source; batch=state-core; order=1; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/templates/progress.md,file:plugins/superb/skills/pipeline/templates/worker-result.md,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py,tree:plugins/superb/skills/pipeline/tests/fixtures; outputs=none -->

**Objective / behavior:** Establish the deterministic tracker/result grammars and the pure strict parser for approved phase-plan metadata. The tracker has: marker, run identity (`run_id`, `base_commit`, `target_branch`, `worker_limit`, artifact paths), revision/last-transition identity, current phase/batch/next eligible action, task table, phase table, gate table, and remediation table. A worker result names the controller-assigned run/task/attempt/owner, plan-declared kind, status/checkpoints, source ref/commits or exact artifact paths, tests/evidence, and concerns-or-question. The phase-plan parser reads only the exact phase and task comments documented above. No parser accepts arbitrary Markdown, hidden fields, reordered/unknown metadata keys, or unknown states.

**Files:** Create the helper/test/fixture paths from the map; rewrite `templates/progress.md`; create `templates/worker-result.md`.

**Interfaces produced:**

```python
SCHEMA = "pipeline-run/v2"
class SchemaError(ValueError): ...
class PlanMetadataError(ValueError): ...
class Tracker: ...
class WorkerResult: ...
@dataclass(frozen=True)
class PlannedTask: id: str; deps: tuple[str, ...]; kind: str; batch: str; order: int; write_scope: tuple[str, ...]; outputs: tuple[str, ...]
def parse_tracker(text: str) -> Tracker: ...
def render_tracker(tracker: Tracker) -> str: ...
def parse_worker_result(text: str) -> WorkerResult: ...
def parse_phase_plan(path: Path) -> tuple[PlannedTask, ...]: ...
```

The tracker carries a monotonic revision and stable last-transition identity. The task implementation-status column is exactly one of `[ ]`, `[~]`, `[?]`, or `[x]`: respectively not dispatched, controller-persisted active attempt, an attempt carrying a question/block reference, and completion validated according to the plan-declared task kind. A `source` task records result/checkpoint, implementation commit(s), source ref, and tests; an `artifact` task records its expected artifact paths and validation evidence with integration `N/A`. Integration and verification are separate facts. Worker statuses are exactly the five vocabulary values in the execution-route header. The rendered tracker preserves the planned task/phase/gate/remediation rows and writes a terminal newline.

**Applicable decisions:** D-003, D-004, D-005, D-006, D-008.

**Acceptance:** A representative valid tracker and both source/artifact results parse, render, and parse identically. A valid phase plan yields immutable `PlannedTask` values with exact ordered `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, and `outputs`; duplicate/omitted/reordered/unknown keys, invalid dependency IDs, unsupported scope/kind/output combinations, or duplicate task IDs produce `PlanMetadataError`. Duplicate tracker IDs, unknown/mismatched task kind, unknown key, invalid revision/transition identity, a status other than `[ ]`/`[~]`/`[?]`/`[x]`, missing required row, or nonpositive `worker_limit` produces `SchemaError` with no write path invoked. The template itself is a valid minimally initialized v2 tracker after substituting its documented angle-bracket values. One integration test parses all four approved phase plans from their real repository paths with this parser so cross-file metadata drift fails Phase 1.

- [ ] **RED — add precise contract tests and fixtures.** Add `test_valid_v2_round_trip_preserves_all_authoritative_rows`, `test_tracker_rejects_unknown_or_missing_required_fields`, `test_worker_result_requires_plan_declared_kind_attempt_and_evidence`, `test_revision_and_last_transition_round_trip`, `test_valid_phase_plan_metadata_parses_in_fixed_order`, `test_phase_plan_metadata_rejects_missing_reordered_or_ambiguous_fields`, and `test_all_four_approved_phase_plans_parse_with_real_helper`. The last test resolves and parses `phase-01.md` through `phase-04.md` from the repository rather than copying their comments into synthetic fixtures. Use fixture names `valid-v2-progress.md`, `valid-source-worker-result.md`, `valid-artifact-worker-result.md`, `malformed-unknown-field.md`, `malformed-worker-result.md`, `phase-plan-valid.md`, and `phase-plan-invalid-metadata.md`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.TrackerContractTest plugins.superb.skills.pipeline.tests.test_pipeline_state.PlanMetadataContractTest -v`

  Expected: FAIL because `pipeline_state` and its tracker/result/phase-plan parser symbols do not exist.

- [ ] **GREEN — implement the smallest strict parsers and renderer.** Make the first non-comment schema line exactly `<!-- pipeline-run/v2 -->`; parse exact headings and pipe-table headers with fixed column names; refuse duplicate/extra/missing fields; use `dataclasses` and immutable parsed collections where practical. Implement `parse_phase_plan` against only the fixed phase/task comment forms and metadata grammar above, including dependency and task-ID validation, without readiness/capacity evaluation. Add the two templates with a field legend that matches, rather than restates differently, the parser grammar.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.TrackerContractTest plugins.superb.skills.pipeline.tests.test_pipeline_state.PlanMetadataContractTest -v`

  Expected: PASS; malformed tracker/result/plan fixtures are rejected in-memory, the valid tracker round-trips byte-for-byte through canonical rendering, and all four real approved phase plans parse under the same metadata contract.

- [ ] **Refactor / bootstrap checkpoint.** Keep parsing helpers private unless named above; add a fixture README that says fixture bytes are input evidence and rejection tests compare them before/after. Follow the explicit P1-01 bootstrap walkthrough above: commit the source, write `agent-output/bootstrap-P1-01.md`, verify it, and manually checkpoint the sole bootstrap tracker. Do not call P1-04/P1-05/P1-06 before they exist and do not ask for a task review.

### P1-02 — Make initialization and incompatible-schema failures safe

<!-- pipeline-v2-task: id=P1-02; deps=P1-01; kind=source; batch=state-core; order=2; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py,tree:plugins/superb/skills/pipeline/tests/fixtures; outputs=none -->

**Objective / behavior:** Add explicit initialization and read-only validation. Initialization creates a new run directory, or creates only `progress.md` in a pre-created directory whose existing entries exactly match explicitly approved artifact paths and contain no tracker/schema-like file. It never overwrites. `validate`, `inspect`, and `next` never mutate. A recognized v1 fixture is identified from `# Pipeline — Progress Tracker`, `## Current State`, and legacy task/RV/RVJ line grammar; missing marker, malformed v2, unknown marker/version, and v1 must report the run path and “no files changed.” This ordinary API is not used to convert the rebuild bootstrap tracker.

**Files:** Modify helper/tests; create `legacy-v1-progress.md`, `missing-marker.md`, `unknown-schema.md`, and `malformed-v2-progress.md` fixtures.

**Consumes:** P1-01 `parse_tracker`, `render_tracker`, `SchemaError`.

**Interfaces produced:**

```python
class LegacySchemaError(SchemaError): ...
def initialize_run(run_dir: Path, *, run_id: str, base_commit: str,
                   target_branch: str, worker_limit: int,
                   artifacts: dict[str, str], approved_existing: tuple[Path, ...]) -> Tracker: ...
def validate_run(run_dir: Path) -> Tracker: ...
def inspect_run(run_dir: Path) -> dict[str, object]: ...
```

CLI forms are `init RUN_DIR --run-id ID --base-commit SHA --target-branch BRANCH --worker-limit N --spec PATH --master-plan PATH --phase-plan PATH`, `validate RUN_DIR`, `inspect RUN_DIR`, and `next RUN_DIR --phase-plan PATH`. All diagnostics have a stable error code and mention the affected path.

**Applicable decisions:** D-001, D-003, D-004, D-008.

**Acceptance:** A new empty directory and an existing directory containing only the explicitly approved design/plan/decisions artifacts can receive a new tracker without changing those artifacts. Any existing `progress.md`, unapproved entry, schema-like file, recognized v1 state, or ambiguous path is refused byte-for-byte. Every incompatible fixture and every read-only command leaves sentinel files/tracker bytes unchanged; `next` cannot issue dispatch readiness for invalid state.

- [ ] **RED — add initialization/read-only tests.** Assert `test_initialize_new_directory`, `test_initialize_existing_approved_artifact_only_directory_preserves_artifacts`, `test_initialize_refuses_existing_tracker_or_unapproved_entry`, `test_legacy_v1_is_recognized_and_left_byte_identical`, and a table-driven test over missing/malformed/unknown schema inputs. Each rejection test records the full directory tree and bytes before invoking the command.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.InitializationAndSchemaSafetyTest -v`

  Expected: FAIL because initialization and v1-specific diagnostics are unimplemented.

- [ ] **GREEN — implement initialization and read-only CLI routing.** Use `argparse`; make error exits nonzero without tracebacks for expected schema errors. Detect legacy by the specified structural combination, never by “v2 marker absent.” Do not create a lock, temporary file, result directory, or replacement file before a read-only command has successfully parsed v2.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.InitializationAndSchemaSafetyTest -v`

  Expected: PASS; all rejected paths preserve their recorded bytes/tree and output a named v2-incompatible or schema diagnostic.

- [ ] **Task checkpoint.** Verify the CLI’s `validate`, `inspect`, and `next` use no mutation function by injecting a failing writer in their tests; retain no per-task review.

### P1-03 — Serialize mutations and atomically replace the tracker

<!-- pipeline-v2-task: id=P1-03; deps=P1-02; kind=source; batch=state-core; order=3; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py; outputs=none -->

**Objective / behavior:** Protect every mutation with a stable separate run-local lock, then read → validate → transition → validate → same-directory temporary write → flush/fsync → atomic replace → directory sync where supported → unlock. Never unlock by deleting the lock path; never fall back to an unlocked write. Reuse the repository’s Craft `session.py` distinction between POSIX `flock` and `msvcrt.locking`, adapting it rather than copying an unexamined platform assumption.

**Files:** Modify helper/tests only.

**Consumes:** P1-02 initialization/validation functions.

**Interfaces produced:**

```python
class LockBusyError(RuntimeError): ...
class LockUnavailableError(RuntimeError): ...
class TrackerWriteError(RuntimeError): ...
class UpdateOutcomeUncertain(RuntimeError): ...
def locked_tracker_update(run_dir: Path, transition_id: str,
                          transition: Callable[[Tracker], Tracker], *, timeout_s: float) -> Tracker: ...
```

The lock path is `<run-dir>/.pipeline-state.lock`; it is distinct from `progress.md`. Contention waits only to the supplied bounded deadline and reports busy. The Windows branch is included only after using the inspected Craft implementation’s primitive selection and is documented/tested as “Implemented; simulation-tested; native Windows verification pending” until native evidence exists.

**Applicable decisions:** D-008, D-009.

**Acceptance:** Real separate processes serialize competing updates; a terminated holder releases the OS lock; lock acquisition failure is distinct from write failure. Temporary-write/fsync/replacement failures before successful replacement preserve the complete old tracker. A directory-sync or later failure after successful replacement reports `UpdateOutcomeUncertain`, never claims unchanged state, and re-reads the tracker by transition ID/revision. Retry returns the already-applied state or safely applies once; it never completes a task or increments a remediation round twice. A reader sees a complete old or new document, never a partial one; missing primitives fail diagnostically with no unlocked write; no test removes another process’s lock file.

- [ ] **RED — add real-process and stage-aware fault-injection tests.** Add `test_second_process_times_out_busy_without_writing`, `test_terminated_holder_releases_lock`, `test_temp_fsync_failure_preserves_old_tracker_bytes`, `test_replace_failure_preserves_old_tracker_bytes`, `test_directory_sync_failure_reports_may_have_applied`, `test_retry_after_post_replace_failure_does_not_duplicate_completion_or_round`, and `test_atomic_reader_observes_only_complete_versions`. Coordinate children with `multiprocessing` events/queues and a deadline, never fixed sleeps.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.AtomicMutationTest -v`

  Expected: FAIL because no lock/update primitive exists.

- [ ] **GREEN — implement lock and stage-aware atomic-write primitives.** Open/create but never unlink the lock file; check that the locked descriptor still names the lock path before mutation. Put the caller's stable transition ID and incremented revision into the constructed tracker before writing. Before `os.replace`, clean only this invocation's known temporary file and raise `TrackerWriteError` while preserving the old tracker. After `os.replace`, a directory-sync/later failure raises `UpdateOutcomeUncertain`; while still locked, re-read and validate `last_transition_id`/revision, but do not roll back or blindly replay. Convert only locking primitive failures to `LockUnavailableError`.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.AtomicMutationTest -v`

  Expected: PASS on Linux with real contention/release/replacement evidence; simulated Windows selection test passes and native Windows remains explicitly unclaimed.

- [ ] **Task checkpoint.** Run `python3.11 -m py_compile plugins/superb/skills/pipeline/scripts/pipeline_state.py`; record the platform/evidence classification in test names or assertions, not a success claim beyond the local platform.

### P1-04 — Enforce task-level state transitions and controller ownership

<!-- pipeline-v2-task: id=P1-04; deps=P1-03; kind=source; batch=state-core; order=4; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py,tree:plugins/superb/skills/pipeline/tests/fixtures; outputs=none -->

**Objective / behavior:** Model legal implementation-marker transitions: `[ ] → [~] → [x]`, `[~] → [?] → [~]` after an explicit answer/retry, and `[~] → [?]` for a blocked outcome. `[x]` never regresses. A controller persists `[~]`, owner, and immutable attempt before dispatch. Only a controller records `[x]` or separate integration facts; workers write result artifacts and cannot mutate the tracker. Completion derives `source`/`artifact` from the approved phase metadata, never from a worker request or an empty diff.

**Files:** Modify helper/tests; add `valid-active-attempt-task.md` and `illegal-transition.md` fixtures.

**Consumes:** P1-01 `parse_phase_plan`/`PlannedTask` and P1-03 `locked_tracker_update`.

**Interfaces produced:**

```python
class TransitionError(ValueError): ...
def start_task(run_dir: Path, *, task_id: str, owner: str, attempt: str) -> Tracker: ...
def resume_task(run_dir: Path, *, task_id: str, prior_attempt: str,
                new_owner: str, new_attempt: str, decision_ref: str) -> Tracker: ...
def record_task_question(run_dir: Path, *, task_id: str, attempt: str,
                         question_or_block_ref: str, reason: str) -> Tracker: ...
def complete_task(run_dir: Path, *, task_id: str, attempt: str,
                  phase_plan: Path, source_ref: str | None,
                  commits: tuple[str, ...], artifacts: tuple[Path, ...],
                  evidence: tuple[str, ...], repo_dir: Path) -> Tracker: ...
def record_task_integration(run_dir: Path, *, task_id: str, integration_commit: str,
                            verification: tuple[str, ...], repo_dir: Path) -> Tracker: ...
```

`start_task` is first-start only. `resume_task` validates that the task is `[?]`, the blocked attempt matches, the new attempt is distinct and unused, and `decision_ref` resolves in the recorded decisions artifact to an explicit resolved answer applicable to this task/current blocker. Missing, pending, unrelated, duplicated/conflicting, or generic plan-approval evidence fails unchanged. The shared narrow start guard checks current dependency integration/completion, global capacity, ownership, and typed-scope conflicts before either transition; P1-05 later adds candidate calculation and multi-task reservation, not a second start policy. Resume appends stable prior-attempt/result/question/checkpoint references before replacing the current owner/attempt, and the identical already-applied resume is idempotent. Session recovery never calls `resume_task` merely because context was lost.

**Applicable decisions:** D-004, D-008, D-011.

**Acceptance:** Starting writes owner/attempt and `[~]` before a caller can observe dispatch eligibility; duplicate start, owner/attempt mismatch, kind mismatch, stale result, or missing required evidence cannot alter bytes. A `source` task reaches `[x]` only with valid implementation commits reachable from its recorded source ref; an `artifact` task reaches `[x]` only when every plan-declared artifact exists and applicable validation evidence matches its task/attempt, then records integration `N/A`. Source tasks cannot use `N/A`, and artifact tasks cannot use unrelated/empty commits. Source completion remains dependency-ineligible until integration proves every implementation commit is an ancestor of `integration_commit`, that commit is an ancestor of `target_branch`, and verification names the integrated code state.

- [ ] **RED — add legal/illegal transition tests.** Assert the exact row before/after `[ ] → [~] → [x]` and `[~] → [?] → [~]`, plus `test_start_task_accepts_initial_and_rejects_blocked_active_completed`, `test_resume_task_accepts_matching_blocked_attempt_and_applicable_resolved_decision`, `test_resume_rejects_missing_unresolved_unrelated_or_conflicting_decision_unchanged`, `test_resume_rejects_reused_stale_attempt_and_completed_task`, `test_identical_resume_replay_has_no_additional_effect`, `test_late_prior_attempt_result_cannot_complete_resumed_task`, `test_context_recovery_does_not_create_new_attempt`, `test_valid_artifact_task_completes_without_source_commit`, `test_artifact_task_missing_expected_evidence_is_rejected`, `test_source_task_without_implementation_commit_is_rejected`, `test_result_commit_need_not_reach_target_before_integration`, `test_proper_worker_commit_ancestry_allows_integration`, `test_unrelated_target_commit_does_not_integrate_worker_commit`, `test_missing_or_conflicting_integration_evidence_blocks_dependents`, `test_illegal_transition_leaves_bytes_unchanged`, `test_stale_attempt_cannot_regress_or_increment`, and `test_start_persists_attempt_before_dispatch_callback`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.TaskTransitionTest -v`

  Expected: FAIL because controller task-transition APIs and provenance fields are absent.

- [ ] **GREEN — add D-011 start/resume, kind-aware completion, and complete integration proof inside the lock.** Resolve task metadata from the approved phase plan. Share one narrow start-guard/update core, while keeping `start_task` first-start only and `resume_task` answered-block only. Resolve the tracker decisions path, parse the referenced stable decision section, require one applicable explicit answer and `Resolved` status, reject any other unresolved task-scoped decision, append prior attempt/evidence linkage, and persist the distinct new attempt before dispatch. For `source`, require verified checkpoint/result and at least one valid implementation commit reachable from `source_ref` before `[x]`; for `artifact`, require the exact planned artifacts and validation evidence, set source fields `N/A`, and record integration `N/A`. Only `record_task_integration` may integrate a source task, and it must verify both `git merge-base --is-ancestor <each-implementation-commit> <integration_commit>` and `git merge-base --is-ancestor <integration_commit> <target_branch>`, then bind verification evidence to that integrated commit. Rewritten-history equivalence is unsupported unless later explicitly approved.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.TaskTransitionTest -v`

  Expected: PASS; all named illegal/stale paths leave exact original bytes.

- [ ] **Task checkpoint and canonical adoption.** After its targeted green test, commit the P1-04 changes; write `agent-output/bootstrap-P1-04.md` with stable run/task/attempt/commit/test identity; verify the commit and test evidence; and manually checkpoint P1-04 `[x]` in the same authoritative bootstrap tracker. Then perform bootstrap step 4's validated, locked, atomic adoption of that tracker. Do not call P1-06's not-yet-implemented import API. Confirm task status vocabulary is not a review workflow: this task records task recovery checkpoints only, never a reviewer or a per-task gate.

### P1-05 — Calculate safe batch readiness from parsed phase metadata

<!-- pipeline-v2-task: id=P1-05; deps=P1-04; kind=source; batch=state-core; order=5; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py,tree:plugins/superb/skills/pipeline/tests/fixtures; outputs=none -->

**Objective / behavior:** Consume P1-01's parsed metadata and return candidate tasks eligible for a batch. Eligibility requires: v2 state valid; phase-plan metadata valid; source dependencies proven integrated and artifact dependencies verified complete; no unanswered decision/question; matching planned batch/order; no typed-scope overlap with active/reserved work or another selected candidate; active workers below persisted `worker_limit`; and no active phase/gate conflict. Readiness output is advisory. Actual starts are serialized under the tracker lock and revalidate all conditions so stale output cannot authorize a dispatch.

**Files:** Modify helper/tests; add `phase-plan-write-conflict.md` and `phase-plan-dependency-blocked.md` fixtures. P1-01 owns the valid/invalid phase-plan parser fixtures and contract tests.

**Consumes:** P1-01 `parse_phase_plan`/`PlannedTask`; P1-04 tracker state APIs.

**Interfaces produced:**

```python
def next_eligible_actions(run_dir: Path, phase_plan: Path, *, capacity: int | None) -> tuple[PlannedTask, ...]: ...
def reserve_tasks(run_dir: Path, phase_plan: Path, *, task_ids: tuple[str, ...],
                  owners: tuple[str, ...], attempts: tuple[str, ...], capacity: int | None) -> Tracker: ...
```

`capacity=None` is uncertainty, not permission: it returns a blocking diagnostic. `next` prints eligible stable IDs and named reasons for every withheld task without mutating tracker state.

**Applicable decisions:** D-004, D-008.

**Acceptance:** Duplicated/reordered metadata, unsupported kind/scope, dangling dependencies, nonpositive order, repeated task ID, active or pairwise-candidate scope overlap, missing limit, limit over capacity, and unresolved question all block dispatch. Exact independent files may reserve together; identical files conflict; a tree conflicts with every child file/tree. A recorded compatible limit queues work above the ceiling. A source-dependent task becomes eligible only after complete integration ancestry; an artifact-dependent task only after verified completion. A new question, consumed slot, changed dependency, or new reservation between `next` and `reserve_tasks` makes reservation fail without partial starts.

- [ ] **RED — add readiness/reservation matrix tests.** Include `test_worker_limit_is_global_across_roles`, `test_independent_exact_file_scopes_can_reserve_together`, `test_identical_file_scopes_conflict`, `test_tree_and_child_file_overlap_conflicts`, `test_two_conflicting_ready_candidates_cannot_both_reserve`, `test_new_question_or_consumed_capacity_invalidates_stale_readiness`, `test_source_dependency_needs_complete_integration_ancestry`, `test_artifact_dependency_needs_verified_completion`, and `test_unknown_capacity_returns_question_not_default`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.SchedulerReadinessTest -v`

  Expected: FAIL because readiness calculation and serialized reservation are absent; P1-01's phase-plan parser is already green.

- [ ] **GREEN — implement advisory readiness and serialized reservation over P1-01 metadata.** Reuse `PlannedTask` without reparsing or accepting an alternate grammar. Compare validated `file:` equality, `tree:` ancestry, and tree/file containment over repository-relative POSIX components. Keep `next_eligible_actions` read-only. Under one lock, `reserve_tasks` re-reads state and rechecks questions, dependency evidence, pairwise selected scopes, active reservations, global capacity, owners, and attempts before atomically starting all or none.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.SchedulerReadinessTest -v`

  Expected: PASS; each withheld task has its own dependency/capacity/question/write-conflict diagnostic.

- [ ] **Task checkpoint.** Exercise the real `next` CLI with the valid fixture; it reports P1-01-style metadata only and creates no lock/temp/tracker write.

### P1-06 — Validate and import immutable worker results idempotently

<!-- pipeline-v2-task: id=P1-06; deps=P1-04,P1-05; kind=source; batch=state-core; order=6; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/templates/worker-result.md,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py,tree:plugins/superb/skills/pipeline/tests/fixtures; outputs=none -->

**Objective / behavior:** Workers atomically publish attempt-scoped result files beside their final `agent-output/` location; the controller reads them and, under the tracker lock, validates run/task/attempt/owner together, plan-declared kind, expected evidence, and—only for source tasks—source ref/Git commits, then imports once. `owner` is the exact controller-assigned identifier already persisted for the attempt; it is never inferred and an incoming result never changes tracker ownership. An exact accepted result replay is a no-op only when its persisted result identity and content match; a stale, conflicting, kind-mismatched, missing-evidence, wrong-owner, or wrong-source-ref result is rejected with tracker bytes unchanged.

**Files:** Modify helper/result template/tests; add `valid-result-done.md`, `valid-result-needs-context.md`, `stale-result.md`, and `conflicting-result.md` fixtures.

**Consumes:** P1-01 result/phase-plan parsers, P1-03 atomic support, P1-04 transitions, and P1-05 readiness/reservation state.

**Interfaces produced:**

```python
class EvidenceError(ValueError): ...
def publish_worker_result(path: Path, result: WorkerResult) -> None: ...
def import_worker_result(run_dir: Path, *, result_path: Path, phase_plan: Path,
                         repo_dir: Path) -> Tracker: ...
```

`DONE` and `DONE_WITH_CONCERNS` can lead only to `[x]` after controller validation. Every status and both task kinds require a nonempty result owner exactly matching the current attempt's recorded owner. A plan-declared `source` result requires source ref, commit, test, and evidence fields; every commit must be a valid object reachable from that ref but need not yet be on `target_branch`. A plan-declared `artifact` result requires the exact expected artifact paths plus validation evidence and no fabricated commit; integration is `N/A`. `NEEDS_CONTEXT`, `PLAN_CONFLICT`, and `BLOCKED` each require a stable question/block reference and lead to `[?]`; the latter also requires its blocking reason. Worker result import never treats a worker report or a no-diff claim as proof and never lets the worker select task kind.

**Applicable decisions:** D-003, D-004, D-008.

**Acceptance:** Duplicate import neither changes revision/counters nor re-completes a task; stale attempt/result/source-ref or kind conflict never regresses it. A correct source result imports exactly once before later integration. A valid artifact-only result completes with expected artifacts/validation and no source commit; missing artifact evidence fails; a source task without its required commit fails. Each blocked vocabulary result imports only to `[?]` with its required reference. Result publication never writes `progress.md`. Later source integration must prove implementation-commit ancestry into the target-branch integration commit before a dependent becomes eligible.

- [ ] **RED — add result-import tests with a temporary Git repository.** Assert `test_matching_source_and_artifact_result_owner_imports`, `test_matching_needs_context_and_blocked_owner_imports`, `test_missing_or_empty_owner_is_rejected`, `test_wrong_owner_preserves_tracker_bytes`, `test_same_owner_superseded_attempt_is_rejected`, `test_duplicate_result_import_is_idempotent`, `test_reused_result_path_with_altered_owner_is_rejected`, `test_stale_or_conflicting_result_preserves_tracker`, `test_worker_result_kind_must_match_plan`, `test_valid_artifact_result_needs_no_commit`, `test_artifact_result_missing_evidence_is_rejected`, `test_source_result_without_commit_is_rejected`, `test_worker_result_commit_must_reach_recorded_source_ref`, `test_worker_result_commit_can_precede_target_branch_integration`, `test_needs_context_stops_dependents_and_records_question`, `test_plan_conflict_and_blocked_results_record_question_marker_and_reference`, and `test_result_publish_is_atomic_and_never_touches_tracker`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.WorkerResultImportTest -v`

  Expected: FAIL because result publication/import and Git evidence checking are absent.

- [ ] **GREEN — implement owner- and kind-aware result publication/import.** Resolve kind and expected artifacts from the approved phase plan. Under the existing tracker lock, validate result run/task/attempt/owner as one assignment identity before any status transition, requiring exact owner equality and never copying an incoming owner into the tracker. For source results, verify each commit with `git cat-file -e <sha>^{commit}` and `git merge-base --is-ancestor <sha> <source-ref>`; do not test target reachability at import. For artifact results, verify exact path existence plus named validation evidence and reject source-commit substitutes. Persist an accepted result identity and content digest so an exact replay remains a no-op after completion, while same-path changed content and superseded attempts fail. Use the P1-03 transition identity path so stale/conflicting/uncertain retries cannot regress or duplicate state; P1-08 reconciliation must call this same importer rather than a weaker recovery validator.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.WorkerResultImportTest -v`

  Expected: PASS; result artifacts remain evidence and only controller import updates the authoritative tracker.

- [ ] **Task checkpoint.** Commit P1-06 changes before publishing/importing the P1-06 result with its targeted green evidence. Confirm a `NEEDS_CONTEXT` result changes the affected task to `[?]`, blocks affected dispatch, and does not cancel already-running independent work in the readiness model.

### P1-07 — Record integration, mechanical verification, and gate/remediation state

<!-- pipeline-v2-task: id=P1-07; deps=P1-05,P1-06; kind=source; batch=state-core; order=7; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py,tree:plugins/superb/skills/pipeline/tests/fixtures; outputs=none -->

**Objective / behavior:** Make phase completion mechanical before formal review. A phase may be verified only when every source task satisfies complete integration ancestry, every artifact task has verified completion and truthful `N/A` integration, and its planned suite passed on the recorded integrated HEAD. Validate each phase's `final-only`/`required` classification and reason against that phase's own approved metadata. Persist gate base/HEAD, assignments/reports, evidence-derived acceptance state, open findings/questions, and immutable remediation identity. Required review starts only after mechanical verification; remediation starts at round one after initial round zero and cannot exceed three rounds.

**Files:** Modify helper/tests; add `valid-required-gate.md`, `valid-final-only-gate.md`, and `remediation-round-three.md` fixtures.

**Consumes:** P1-01 phase metadata, P1-04/P1-06 task integration evidence, and P1-05 readiness/reservation state.

**Interfaces produced:**

```python
def record_phase_verification(run_dir: Path, *, phase_id: str, head: str,
                              commands: tuple[str, ...], evidence: tuple[str, ...]) -> Tracker: ...
def open_review_gate(run_dir: Path, *, gate_id: str, base: str, head: str,
                     reviewer_assignments: tuple[str, ...]) -> Tracker: ...
def start_remediation_round(run_dir: Path, *, gate_id: str, round_number: int,
                            finding_ids: tuple[str, ...], fix_plan: str) -> Tracker: ...
def evaluate_and_close_review_gate(run_dir: Path, *, gate_id: str,
                                   findings_path: Path, report_paths: tuple[Path, ...],
                                   verification: tuple[str, ...],
                                   rereview_paths: tuple[Path, ...]) -> Tracker: ...
```

**Applicable decisions:** D-005, D-006, D-007, D-008.

**Acceptance:** Failed/missing verification cannot open a gate; `final-only` cannot dispatch a phase reviewer; Phase 1 and Phase 2 each accept their different approved required reasons while missing/mismatched reasons fail; the master gate uses its own type and exactly two assignments. Closure is derived from reports/findings/evidence, not `accepted=True` or an empty list: reports must identify the correct gate/base/HEAD and required scope, verification must cover that state, confirmed Critical/Important and unresolved acceptance questions block, every Minor has a valid disposition, and every repository-changing fix has matching re-review evidence. Round zero costs no allowance; parallel fixes share one round; D-006 stop rules remain.

- [ ] **RED — add positive/negative gate/remediation tests.** Include `test_mixed_source_and_artifact_phase_can_verify_without_fabricated_commit`, `test_phase_one_accepts_its_approved_reason`, `test_phase_two_accepts_its_different_approved_reason`, `test_missing_or_mismatched_required_reason_fails`, `test_final_only_phase_cannot_open_phase_review`, `test_master_gate_requires_two_matching_reviewers`, `test_caller_boolean_or_empty_findings_cannot_prove_acceptance`, `test_wrong_gate_or_reviewed_head_report_is_rejected`, `test_missing_verification_or_unresolved_question_blocks_closure`, `test_confirmed_blocker_blocks_closure`, `test_repository_fix_without_matching_rereview_blocks_closure`, `test_initial_review_is_round_zero`, `test_parallel_fix_results_share_one_round`, and `test_round_three_blocker_refuses_acceptance`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.PhaseGateAndRemediationTest -v`

  Expected: FAIL because phase/gate/remediation APIs and persisted rows are absent.

- [ ] **GREEN — implement phase-specific gate and evidence-derived acceptance under the tracker lock.** Read classification/reason from the applicable approved phase metadata and compare the tracker to that phase; keep the literal Phase 1 reason only in its fixture. Reject a phase gate for `final-only`; separately enforce the master gate type and two D-007 assignments. Parse only the small documented reviewer-result header needed to bind report/gate/base/HEAD/assignment, then derive closure from required reports, code-state verification, validated findings/dispositions/questions, fix commits, and applicable re-review paths. Store paths as references; validate round/finding identity before dispatch changes.

- [ ] **GREEN check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.PhaseGateAndRemediationTest -v`

  Expected: PASS; phase review is impossible before mechanical verification and no unapproved fourth remediation round can be recorded.

- [ ] **Task checkpoint.** Verify this phase’s gate data records one independent reviewer only; do not conflate it with the mandatory two-reviewer master gate.

### P1-08 — Reconcile interrupted work against durable evidence and Git

<!-- pipeline-v2-task: id=P1-08; deps=P1-06,P1-07; kind=source; batch=state-core; order=8; write_scope=file:plugins/superb/skills/pipeline/scripts/pipeline_state.py,file:plugins/superb/skills/pipeline/tests/test_pipeline_state.py,tree:plugins/superb/skills/pipeline/tests/fixtures; outputs=none -->

**Objective / behavior:** Provide a deterministic resume/reconciliation report. It reads spec/master plan/tracker/active phase plan/decisions/findings-or-fix-plan/Git/worktree/results in that order of authority, then reconciles every `[~]` task according to its approved kind. A validated source result imports once before integration; a validated artifact result imports once with artifact evidence and `N/A`; consistent live ownership remains `[~]`; partial/missing evidence is preserved and diagnosed. Resume rechecks the same complete source-integration ancestry as normal execution. It also resolves post-replacement uncertainty by revision/last-transition identity without blindly repeating completion or round increments. Resume never migrates/reinitializes incompatible state or redispatches `[x]` work.

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

**Acceptance:** An interrupted source result and an interrupted artifact result each import exactly once using their own evidence contract; a consistent live worker remains `[~]`; a source task is dependency-ineligible unless each implementation commit is included in the recorded integration commit and that commit reaches `target_branch`; unrelated target commits fail. Missing/conflicting integration evidence blocks. Post-replacement uncertain retry reads transition identity and never duplicates task completion or remediation counters. Partial evidence remains intact; contradictions become stable questions; legacy/malformed input creates no artifacts; fix round identity survives interruption.

- [ ] **RED — add reconciliation fixtures and temporary-Git tests.** Add `test_post_commit_source_result_reconciles_once_before_integration`, `test_artifact_result_reconciles_without_commit`, `test_consistent_running_owner_is_not_redispatched`, `test_resume_accepts_worker_commit_in_integration_history`, `test_resume_rejects_unrelated_target_commit_as_integration`, `test_resume_rejects_missing_or_conflicting_integration_evidence`, `test_post_replace_uncertain_completion_retry_is_idempotent`, `test_post_replace_uncertain_round_retry_keeps_counter`, `test_partial_evidence_is_preserved_and_diagnosed`, `test_git_state_contradiction_requires_user_question`, and `test_interrupted_remediation_keeps_same_round_number`.

- [ ] **RED check.**

  Run: `python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.ReconciliationTest -v`

  Expected: FAIL because no reconciliation report or Git/result comparison exists.

- [ ] **GREEN — implement explicit reconciliation classifications.** Build the report from files/Git each time; never infer a task outcome from memory, result filename, diff, or target reachability alone. Route only kind-correct validated results through P1-06's idempotent import. For source integration, require every implementation commit ancestor of the integration commit and that commit ancestor of `target_branch`; apply the same predicate as normal execution. Reconcile `UpdateOutcomeUncertain` from revision/transition identity. All unresolved cases preserve state and name the exact user decision needed.

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

This plan intentionally overrides the installed writing-plans SDD/executing-plans handoff. Keep one coherent `state-core` executor, but use the rebuild-only controller procedure for P1-01 through P1-04, adopt the same tracker, then activate tested transition/readiness/import capabilities at the stated points for P1-05 through P1-08. Preserve individual durable checkpoints, complete source integration proof, phase mechanical verification, and the required Phase 1 gate. There is no per-task review and no interactive finishing menu.
