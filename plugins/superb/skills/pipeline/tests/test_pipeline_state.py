from __future__ import annotations

import dataclasses
import io
import multiprocessing
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import plugins.superb.skills.pipeline.scripts.pipeline_state as pipeline_state
from plugins.superb.skills.pipeline.scripts.pipeline_state import (
    Checkpoint,
    EvidenceError,
    LegacySchemaError,
    LockBusyError,
    LockUnavailableError,
    PlanMetadataError,
    SchemaError,
    TrackerWriteError,
    TransitionError,
    UpdateOutcomeUncertain,
    complete_task,
    initialize_run,
    import_worker_result,
    inspect_run,
    locked_tracker_update,
    next_eligible_actions,
    main,
    parse_phase_plan,
    parse_tracker,
    parse_worker_result,
    publish_worker_result,
    record_task_integration,
    record_task_question,
    render_tracker,
    resume_task,
    reserve_tasks,
    start_task,
    validate_run,
    WorkerResult,
)


REPOSITORY = Path(__file__).resolve().parents[5]
FIXTURES = Path(__file__).with_name("fixtures")


def _hold_pipeline_lock(run_dir: str, ready, release) -> None:
    with pipeline_state._exclusive_lock(Path(run_dir), timeout_s=2.0):
        ready.set()
        release.wait(10)


def _write_tracker_versions(run_dir: str, finished) -> None:
    for number in range(12):
        transition_id = f"reader-{number}"

        def change(tracker, value=transition_id):
            fields = tuple(
                (key, value if key == "next_action" else current)
                for key, current in tracker.current_fields
            )
            return dataclasses.replace(tracker, current_fields=fields)

        locked_tracker_update(Path(run_dir), transition_id, change, timeout_s=2.0)
    finished.set()


class TrackerContractTest(unittest.TestCase):
    def fixture(self, name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_valid_v2_round_trip_preserves_all_authoritative_rows(self):
        source = self.fixture("valid-v2-progress.md")

        tracker = parse_tracker(source)

        self.assertEqual(render_tracker(tracker), source)
        self.assertEqual(tuple(task.id for task in tracker.tasks), ("P1-01", "P2-T01"))
        self.assertEqual(tuple(phase.id for phase in tracker.phases), ("01", "02"))
        self.assertEqual(tuple(gate.id for gate in tracker.gates), ("phase-01", "master"))
        self.assertEqual(
            tuple((round_.gate, round_.round_number) for round_ in tracker.remediation),
            (("phase-01", 1),),
        )
        template = (
            REPOSITORY / "plugins/superb/skills/pipeline/templates/progress.md"
        ).read_text(encoding="utf-8")
        substitutions = {
            "<run_id>": "2026-09-08-template-test",
            "<base_commit>": "8348959d1b201a873c68512642a0eb8e5754eaa8",
            "<target_branch>": "feat/template-test",
            "<worker_limit>": "3",
            "<spec_path>": "docs/spec.md",
            "<master_plan_path>": "docs/master.md",
            "<phase_plan_paths>": "docs/phase-01.md",
            "<decisions_path>": "docs/decisions.md",
            "<findings_path>": "docs/findings.md",
            "<phase_id>": "01",
            "<batch_id>": "state-core",
            "<next_action>": "P1-01",
            "<task_id>": "P1-01",
            "<review_gate>": "required",
            "<review_reason>": "State safety requires independent review.",
            "<gate_id>": "phase-01",
        }
        for placeholder, value in substitutions.items():
            template = template.replace(placeholder, value)
        self.assertNotIn("<", template.removeprefix("<!--"))
        parse_tracker(template)
        with self.assertRaises((dataclasses.FrozenInstanceError, AttributeError)):
            tracker.revision = 8

    def test_tracker_rejects_unknown_or_missing_required_fields(self):
        valid = self.fixture("valid-v2-progress.md")
        cases = {
            "unknown field": self.fixture("malformed-unknown-field.md"),
            "missing field": valid.replace("| worker_limit | 3 |\n", ""),
            "duplicate task id": valid.replace(
                "| P2-T01 | artifact |",
                "| P1-01 | artifact |",
            ),
            "unknown task kind": valid.replace(
                "| P1-01 | source |",
                "| P1-01 | documentation |",
            ),
            "invalid task state": valid.replace("| [x] |", "| [!] |", 1),
            "invalid revision": valid.replace("| revision | 7 |", "| revision | -1 |"),
            "invalid transition": valid.replace(
                "| last_transition | transition-007 |",
                "| last_transition | contains spaces |",
            ),
            "nonpositive worker limit": valid.replace(
                "| worker_limit | 3 |",
                "| worker_limit | 0 |",
            ),
            "missing required row": valid.replace(
                "## Tasks\n| ID | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n| P1-01 | source | [x] | worker-1 | attempt-001 | agent-output/p1-01.md | red,green | refs/heads/feat/example | 0123456789abcdef0123456789abcdef01234567 | - | fedcba9876543210fedcba9876543210fedcba98 | tests/p1-01.txt | - |\n| P2-T01 | artifact | [x] | worker-2 | attempt-002 | agent-output/p2-t01.md | control,green | - | - | docs/evidence.md | N/A | artifact-check.txt | - |\n\n",
                "",
            ),
        }
        for label, source in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(SchemaError):
                    parse_tracker(source)

    def test_worker_result_requires_plan_declared_kind_attempt_and_evidence(self):
        source_result = parse_worker_result(
            self.fixture("valid-source-worker-result.md")
        )
        artifact_result = parse_worker_result(
            self.fixture("valid-artifact-worker-result.md")
        )

        self.assertEqual(source_result.kind, "source")
        self.assertEqual(source_result.owner, "worker-1")
        self.assertEqual(source_result.commits, ("0123456789abcdef0123456789abcdef01234567",))
        self.assertEqual(source_result.artifacts, ())
        self.assertEqual(artifact_result.kind, "artifact")
        self.assertEqual(artifact_result.commits, ())
        self.assertEqual(artifact_result.artifacts, ("docs/evidence.md",))

        malformed = self.fixture("malformed-worker-result.md")
        source = self.fixture("valid-source-worker-result.md")
        for label, text in {
            "malformed fixture": malformed,
            "missing kind": source.replace("| kind | source |\n", ""),
            "missing attempt": source.replace("| attempt | attempt-001 |", "| attempt | - |"),
            "missing owner": source.replace("| owner | worker-1 |\n", ""),
            "missing evidence": source.replace("| evidence | red.log,green.log |", "| evidence | - |"),
            "source missing commit": source.replace(
                "| commits | 0123456789abcdef0123456789abcdef01234567 |",
                "| commits | - |",
            ),
        }.items():
            with self.subTest(label=label):
                with self.assertRaises(SchemaError):
                    parse_worker_result(text)

    def test_revision_and_last_transition_round_trip(self):
        tracker = parse_tracker(self.fixture("valid-v2-progress.md"))

        self.assertEqual(tracker.revision, 7)
        self.assertEqual(tracker.last_transition, "transition-007")
        reparsed = parse_tracker(render_tracker(tracker))
        self.assertEqual(reparsed.revision, 7)
        self.assertEqual(reparsed.last_transition, "transition-007")


class PlanMetadataContractTest(unittest.TestCase):
    def fixture_path(self, name: str) -> Path:
        return FIXTURES / name

    def test_valid_phase_plan_metadata_parses_in_fixed_order(self):
        tasks = parse_phase_plan(self.fixture_path("phase-plan-valid.md"))

        self.assertEqual(len(tasks), 2)
        source, artifact = tasks
        self.assertEqual(
            (
                source.id,
                source.deps,
                source.kind,
                source.batch,
                source.order,
                source.write_scope,
                source.outputs,
            ),
            (
                "PX-01",
                (),
                "source",
                "state-core",
                1,
                ("file:src/state.py", "tree:tests/fixtures"),
                (),
            ),
        )
        self.assertEqual(artifact.id, "PX-02")
        self.assertEqual(artifact.deps, ("PX-01",))
        self.assertEqual(artifact.kind, "artifact")
        self.assertEqual(artifact.outputs, ("docs/evidence/result.md",))

    def test_phase_plan_metadata_rejects_missing_reordered_or_ambiguous_fields(self):
        valid = self.fixture_path("phase-plan-valid.md").read_text(encoding="utf-8")
        invalid_fixture = self.fixture_path("phase-plan-invalid-metadata.md")
        cases: dict[str, str] = {
            "invalid fixture": invalid_fixture.read_text(encoding="utf-8"),
            "missing field": valid.replace("; outputs=none -->", " -->", 1),
            "reordered fields": valid.replace(
                "deps=none; kind=source",
                "kind=source; deps=none",
                1,
            ),
            "unknown field": valid.replace("; outputs=none -->", "; owner=worker; outputs=none -->", 1),
            "duplicate metadata": valid.replace(
                "<!-- pipeline-v2-task: id=PX-01;",
                "<!-- pipeline-v2-task: id=PX-01; deps=none; kind=source; batch=state-core; order=1; write_scope=file:src/state.py; outputs=none -->\n<!-- pipeline-v2-task: id=PX-01;",
                1,
            ),
            "invalid dependency": valid.replace("deps=PX-01", "deps=PX-99", 1),
            "unsupported scope": valid.replace("file:src/state.py", "file:../state.py", 1),
            "invalid kind/output combination": valid.replace("outputs=none -->", "outputs=docs/output.md -->", 1),
        }
        for label, source in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "phase.md"
                    path.write_text(source, encoding="utf-8")
                    with self.assertRaises(PlanMetadataError):
                        parse_phase_plan(path)

    def test_all_four_approved_phase_plans_parse_with_real_helper(self):
        plan_dir = REPOSITORY / "docs/superpowers/plans/pipeline-rebuild-v2"

        parsed = tuple(
            parse_phase_plan(plan_dir / f"phase-{number:02d}.md")
            for number in range(1, 5)
        )

        self.assertEqual(tuple(len(tasks) for tasks in parsed), (8, 8, 6, 8))
        self.assertEqual(parsed[0][0].id, "P1-01")
        self.assertEqual(parsed[3][-1].id, "P4-08")


class InitializationAndSchemaSafetyTest(unittest.TestCase):
    def snapshot(self, root: Path) -> dict[str, bytes]:
        if not root.exists():
            return {}
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def inputs(self, root: Path) -> tuple[dict[str, str], tuple[Path, ...]]:
        phase = root / "phase.md"
        phase.write_text((FIXTURES / "phase-plan-valid.md").read_text(), encoding="utf-8")
        artifacts = {
            "spec": "docs/spec.md",
            "master_plan": "docs/master.md",
            "phase_plans": str(phase),
            "decisions": "docs/decisions.md",
            "findings": "docs/findings.md",
        }
        return artifacts, ()

    def initialize(self, run_dir: Path, artifacts: dict[str, str], approved: tuple[Path, ...] = ()):
        return initialize_run(
            run_dir,
            run_id="2026-09-08-init-test",
            base_commit="8348959d1b201a873c68512642a0eb8e5754eaa8",
            target_branch="feat/init-test",
            worker_limit=3,
            artifacts=artifacts,
            approved_existing=approved,
        )

    def test_initialize_new_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts, _ = self.inputs(root)
            run_dir = root / "new-run"

            tracker = self.initialize(run_dir, artifacts)

            self.assertEqual(tracker.run_id, "2026-09-08-init-test")
            self.assertEqual(validate_run(run_dir), tracker)
            self.assertEqual(tuple(task.id for task in tracker.tasks), ("PX-01", "PX-02"))

    def test_initialize_existing_approved_artifact_only_directory_preserves_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts, _ = self.inputs(root)
            run_dir = root / "existing-run"
            run_dir.mkdir()
            decisions = run_dir / "decisions.md"
            findings = run_dir / "findings.md"
            decisions.write_text("decisions sentinel\n", encoding="utf-8")
            findings.write_text("findings sentinel\n", encoding="utf-8")
            before = {decisions: decisions.read_bytes(), findings: findings.read_bytes()}

            self.initialize(run_dir, artifacts, (decisions, findings))

            self.assertEqual({path: path.read_bytes() for path in before}, before)
            self.assertTrue((run_dir / "progress.md").is_file())

    def test_initialize_refuses_existing_tracker_or_unapproved_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts, _ = self.inputs(root)
            for label, prepare in {
                "tracker": lambda run: (run / "progress.md").write_text(
                    (FIXTURES / "valid-v2-progress.md").read_text(), encoding="utf-8"
                ),
                "unapproved": lambda run: (run / "surprise.txt").write_text("sentinel", encoding="utf-8"),
            }.items():
                with self.subTest(label=label):
                    run_dir = root / label
                    run_dir.mkdir()
                    prepare(run_dir)
                    before = self.snapshot(run_dir)
                    with self.assertRaises(SchemaError):
                        self.initialize(run_dir, artifacts)
                    self.assertEqual(self.snapshot(run_dir), before)

    def test_legacy_v1_is_recognized_and_left_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "legacy-run"
            run_dir.mkdir()
            progress = run_dir / "progress.md"
            progress.write_bytes((FIXTURES / "legacy-v1-progress.md").read_bytes())
            before = self.snapshot(run_dir)

            with self.assertRaises(LegacySchemaError) as caught:
                validate_run(run_dir)

            message = str(caught.exception)
            self.assertIn(str(run_dir), message)
            self.assertIn("v2 cannot resume this legacy format", message)
            self.assertIn("no files were changed", message)
            self.assertEqual(self.snapshot(run_dir), before)

    def test_missing_malformed_and_unknown_schema_are_rejected_unchanged(self):
        fixtures = ("missing-marker.md", "malformed-v2-progress.md", "unknown-schema.md")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for fixture in fixtures:
                with self.subTest(fixture=fixture):
                    run_dir = root / fixture
                    run_dir.mkdir()
                    (run_dir / "progress.md").write_bytes((FIXTURES / fixture).read_bytes())
                    before = self.snapshot(run_dir)
                    with self.assertRaises(SchemaError) as caught:
                        validate_run(run_dir)
                    self.assertIn("no files were changed", str(caught.exception))
                    self.assertEqual(self.snapshot(run_dir), before)

    def test_validate_inspect_and_next_cli_never_invoke_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            (run_dir / "progress.md").write_bytes((FIXTURES / "valid-v2-progress.md").read_bytes())
            before = self.snapshot(run_dir)
            with mock.patch.object(pipeline_state, "_write_initial_tracker", side_effect=AssertionError("writer called")):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["validate", str(run_dir)]), 0)
                    self.assertEqual(main(["inspect", str(run_dir)]), 0)
                    self.assertNotEqual(main(["next", str(run_dir), "--phase-plan", str(FIXTURES / "phase-plan-valid.md")]), 0)
            self.assertEqual(self.snapshot(run_dir), before)
            self.assertEqual(inspect_run(run_dir)["run_id"], "2026-09-08-example")


class AtomicMutationTest(unittest.TestCase):
    def make_run(self, root: Path) -> Path:
        run_dir = root / "run"
        run_dir.mkdir()
        (run_dir / "progress.md").write_bytes((FIXTURES / "valid-v2-progress.md").read_bytes())
        return run_dir

    def unchanged(self, tracker):
        return tracker

    def test_second_process_times_out_busy_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(Path(directory))
            original = (run_dir / "progress.md").read_bytes()
            context = multiprocessing.get_context("spawn")
            ready, release = context.Event(), context.Event()
            holder = context.Process(target=_hold_pipeline_lock, args=(str(run_dir), ready, release))
            holder.start()
            self.assertTrue(ready.wait(5), "lock holder did not become ready")
            try:
                with self.assertRaises(LockBusyError):
                    locked_tracker_update(run_dir, "busy-attempt", self.unchanged, timeout_s=0.05)
            finally:
                release.set()
                holder.join(5)
            self.assertEqual(holder.exitcode, 0)
            self.assertEqual((run_dir / "progress.md").read_bytes(), original)

    def test_terminated_holder_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(Path(directory))
            context = multiprocessing.get_context("spawn")
            ready, release = context.Event(), context.Event()
            holder = context.Process(target=_hold_pipeline_lock, args=(str(run_dir), ready, release))
            holder.start()
            self.assertTrue(ready.wait(5), "lock holder did not become ready")
            holder.terminate()
            holder.join(5)
            tracker = locked_tracker_update(run_dir, "after-termination", self.unchanged, timeout_s=1.0)
            self.assertEqual(tracker.last_transition, "after-termination")

    def test_temp_fsync_failure_preserves_old_tracker_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(Path(directory))
            before = (run_dir / "progress.md").read_bytes()
            with mock.patch.object(pipeline_state, "_sync_file", side_effect=OSError("fsync failed")):
                with self.assertRaises(TrackerWriteError):
                    locked_tracker_update(run_dir, "fsync-failure", self.unchanged, timeout_s=1.0)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            self.assertEqual(list(run_dir.glob(".progress.*.tmp")), [])

    def test_replace_failure_preserves_old_tracker_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(Path(directory))
            before = (run_dir / "progress.md").read_bytes()
            with mock.patch.object(pipeline_state.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(TrackerWriteError):
                    locked_tracker_update(run_dir, "replace-failure", self.unchanged, timeout_s=1.0)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_directory_sync_failure_reports_may_have_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(Path(directory))
            with mock.patch.object(pipeline_state, "_sync_directory", side_effect=OSError("directory sync failed")):
                with self.assertRaises(UpdateOutcomeUncertain) as caught:
                    locked_tracker_update(run_dir, "post-replace", self.unchanged, timeout_s=1.0)
            self.assertIn("may have applied", str(caught.exception))
            self.assertEqual(validate_run(run_dir).last_transition, "post-replace")

    def test_retry_after_post_replace_failure_does_not_duplicate_completion_or_round(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(Path(directory))
            calls = []

            def change(tracker):
                calls.append(tracker.revision)
                return tracker

            with mock.patch.object(pipeline_state, "_sync_directory", side_effect=OSError("directory sync failed")):
                with self.assertRaises(UpdateOutcomeUncertain):
                    locked_tracker_update(run_dir, "stable-operation-1", change, timeout_s=1.0)
            result = locked_tracker_update(run_dir, "stable-operation-1", change, timeout_s=1.0)
            self.assertEqual(calls, [7])
            self.assertEqual(result.revision, 8)
            self.assertEqual(result.last_transition, "stable-operation-1")

    def test_atomic_reader_observes_only_complete_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(Path(directory))
            context = multiprocessing.get_context("spawn")
            finished = context.Event()
            writer = context.Process(target=_write_tracker_versions, args=(str(run_dir), finished))
            writer.start()
            observations = 0
            while not finished.wait(0.001):
                parse_tracker((run_dir / "progress.md").read_text(encoding="utf-8"))
                observations += 1
            writer.join(5)
            self.assertEqual(writer.exitcode, 0)
            self.assertGreater(observations, 0)
            self.assertEqual(validate_run(run_dir).revision, 19)

    def test_missing_primitives_fail_without_unlocked_write(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(Path(directory))
            before = (run_dir / "progress.md").read_bytes()
            with mock.patch.object(pipeline_state, "fcntl", None), mock.patch.object(pipeline_state, "msvcrt", None):
                with self.assertRaises(LockUnavailableError):
                    locked_tracker_update(run_dir, "no-lock", self.unchanged, timeout_s=1.0)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_windows_lock_selection_is_simulated_not_native_claim(self):
        fake = type("FakeMsvcrt", (), {"LK_NBLCK": 1, "LK_UNLCK": 2, "locking": staticmethod(lambda *args: None)})
        selected = pipeline_state.select_lock_impl(None, fake)
        self.assertEqual(selected[2], "Implemented; simulation-tested; native Windows verification pending.")


class TaskTransitionTest(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ("git", *args), cwd=repo, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()

    def make_git_repo(self, root: Path) -> tuple[Path, str]:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "pipeline@example.invalid")
        self.git(repo, "config", "user.name", "Pipeline Test")
        (repo / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(repo, "add", "base.txt")
        self.git(repo, "commit", "-qm", "base")
        base = self.git(repo, "rev-parse", "HEAD")
        self.git(repo, "branch", "target")
        return repo, base

    def write_plan(self, root: Path, body: str) -> Path:
        path = root / "phase.md"
        path.write_text(body, encoding="utf-8")
        return path

    def source_plan(self, root: Path) -> Path:
        return self.write_plan(
            root,
            """# Transition phase

<!-- pipeline-v2-phase: id=99; deps=none; review_gate=final-only; review_reason=Mechanical verification only. -->

### PX-01 — Source
<!-- pipeline-v2-task: id=PX-01; deps=none; kind=source; batch=one; order=1; write_scope=file:src.txt; outputs=none -->

### PX-02 — Dependent
<!-- pipeline-v2-task: id=PX-02; deps=PX-01; kind=source; batch=two; order=1; write_scope=file:dep.txt; outputs=none -->
""",
        )

    def artifact_plan(self, root: Path) -> Path:
        return self.write_plan(
            root,
            """# Artifact phase

<!-- pipeline-v2-phase: id=99; deps=none; review_gate=final-only; review_reason=Mechanical verification only. -->

### PA-01 — Evidence
<!-- pipeline-v2-task: id=PA-01; deps=none; kind=artifact; batch=evidence; order=1; write_scope=tree:evidence; outputs=evidence/result.md -->
""",
        )

    def decisions(self, root: Path, text: str) -> Path:
        path = root / "decisions.md"
        path.write_text(text, encoding="utf-8")
        return path

    def initialize(self, root: Path, plan: Path, decisions: Path, base: str, target: str = "target") -> Path:
        run_dir = root / "run"
        initialize_run(
            run_dir,
            run_id="transition-test",
            base_commit=base,
            target_branch=target,
            worker_limit=3,
            artifacts={
                "spec": "spec.md", "master_plan": "master.md",
                "phase_plans": str(plan), "decisions": str(decisions),
                "findings": "findings.md",
            },
            approved_existing=(),
        )
        return run_dir

    def resolved_decision(self, task: str = "PX-01", answer: str = "Use the recorded interface.") -> str:
        return f"""# Decisions

## D-100 — Resume

- **Question:** Which interface applies?
- **Answer:** {answer}
- **Scope:** {task} and its current blocker.
- **Status:** Resolved.
"""

    def block(self, run_dir: Path, attempt: str = "attempt-1"):
        start_task(run_dir, task_id="PX-01", owner="worker-a", attempt=attempt)
        return record_task_question(
            run_dir, task_id="PX-01", attempt=attempt,
            question_or_block_ref="D-100", reason="answer required",
        )

    def task(self, run_dir: Path, task_id: str = "PX-01"):
        return next(task for task in validate_run(run_dir).tasks if task.id == task_id)

    def test_start_task_accepts_initial_and_rejects_blocked_active_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = self.make_git_repo(root)
            plan = self.source_plan(root)
            decisions = self.decisions(root, self.resolved_decision())
            run_dir = self.initialize(root, plan, decisions, base)

            started = start_task(run_dir, task_id="PX-01", owner="worker-a", attempt="attempt-1")
            self.assertEqual(next(task for task in started.tasks if task.id == "PX-01").state, "[~]")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                start_task(run_dir, task_id="PX-01", owner="worker-a", attempt="attempt-1")
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            with self.assertRaises(TransitionError):
                start_task(run_dir, task_id="PX-01", owner="worker-b", attempt="attempt-2")
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_source_task_without_implementation_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = self.make_git_repo(root)
            plan = self.source_plan(root)
            run_dir = self.initialize(root, plan, self.decisions(root, self.resolved_decision()), base)
            start_task(run_dir, task_id="PX-01", owner="worker", attempt="attempt-1")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                complete_task(
                    run_dir, task_id="PX-01", attempt="attempt-1", phase_plan=plan,
                    source_ref="HEAD", commits=(), artifacts=(), evidence=("tests.log",), repo_dir=repo,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            record_task_question(run_dir, task_id="PX-01", attempt="attempt-1", question_or_block_ref="D-100", reason="blocked")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                start_task(run_dir, task_id="PX-01", owner="worker-b", attempt="attempt-2")
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_resume_task_accepts_matching_blocked_attempt_and_applicable_resolved_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, base = self.make_git_repo(root)
            run_dir = self.initialize(root, self.source_plan(root), self.decisions(root, self.resolved_decision()), base)
            self.block(run_dir)

            resumed = resume_task(
                run_dir, task_id="PX-01", prior_attempt="attempt-1",
                new_owner="worker-a", new_attempt="attempt-2", decision_ref="D-100",
            )

            task = next(task for task in resumed.tasks if task.id == "PX-01")
            self.assertEqual((task.state, task.owner, task.attempt), ("[~]", "worker-a", "attempt-2"))
            self.assertIn("attempt-1->attempt-2@D-100", task.checkpoints)
            self.assertEqual(task.question, "resolved:D-100")

    def test_resume_rejects_missing_unresolved_unrelated_or_conflicting_decision_unchanged(self):
        cases = {
            "missing": "# Decisions\n",
            "unresolved": self.resolved_decision().replace("Resolved.", "Open."),
            "unrelated": self.resolved_decision(task="PX-99"),
            "conflicting": self.resolved_decision() + "\n- **Answer:** A conflicting answer.\n",
            "generic approval": self.resolved_decision(answer="approved"),
        }
        for label, decision_text in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, base = self.make_git_repo(root)
                decisions = self.decisions(root, self.resolved_decision())
                run_dir = self.initialize(root, self.source_plan(root), decisions, base)
                self.block(run_dir)
                decisions.write_text(decision_text, encoding="utf-8")
                before = (run_dir / "progress.md").read_bytes()
                with self.assertRaises(TransitionError):
                    resume_task(run_dir, task_id="PX-01", prior_attempt="attempt-1", new_owner="worker", new_attempt="attempt-2", decision_ref="D-100")
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_identical_resume_replay_has_no_additional_effect_and_stale_request_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, base = self.make_git_repo(root)
            run_dir = self.initialize(root, self.source_plan(root), self.decisions(root, self.resolved_decision()), base)
            self.block(run_dir)
            first = resume_task(run_dir, task_id="PX-01", prior_attempt="attempt-1", new_owner="worker", new_attempt="attempt-2", decision_ref="D-100")
            first_bytes = (run_dir / "progress.md").read_bytes()
            replay = resume_task(run_dir, task_id="PX-01", prior_attempt="attempt-1", new_owner="worker", new_attempt="attempt-2", decision_ref="D-100")
            self.assertEqual(replay.revision, first.revision)
            self.assertEqual((run_dir / "progress.md").read_bytes(), first_bytes)
            with self.assertRaises(TransitionError):
                resume_task(run_dir, task_id="PX-01", prior_attempt="attempt-1", new_owner="worker", new_attempt="attempt-3", decision_ref="D-100")
            self.assertEqual((run_dir / "progress.md").read_bytes(), first_bytes)

    def test_resume_rejects_completed_task_and_other_unresolved_task_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = self.make_git_repo(root)
            plan = self.source_plan(root)
            decisions = self.decisions(root, self.resolved_decision())
            run_dir = self.initialize(root, plan, decisions, base)
            self.block(run_dir)
            decisions.write_text(
                self.resolved_decision()
                + "\n## D-101 — Other blocker\n\n"
                + "- **Question:** Which behavior applies?\n"
                + "- **Answer:** pending user response\n"
                + "- **Scope:** PX-01 and its current blocker.\n"
                + "- **Status:** Open.\n",
                encoding="utf-8",
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                resume_task(
                    run_dir, task_id="PX-01", prior_attempt="attempt-1",
                    new_owner="worker", new_attempt="attempt-2", decision_ref="D-100",
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            decisions.write_text(self.resolved_decision(), encoding="utf-8")
            resume_task(
                run_dir, task_id="PX-01", prior_attempt="attempt-1",
                new_owner="worker", new_attempt="attempt-2", decision_ref="D-100",
            )
            completed = complete_task(
                run_dir, task_id="PX-01", attempt="attempt-2", phase_plan=plan,
                source_ref="HEAD", commits=(base,), artifacts=(), evidence=("tests.log",), repo_dir=repo,
            )
            self.assertEqual(next(task for task in completed.tasks if task.id == "PX-01").state, "[x]")
            completed_bytes = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                resume_task(
                    run_dir, task_id="PX-01", prior_attempt="attempt-2",
                    new_owner="worker", new_attempt="attempt-3", decision_ref="D-100",
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), completed_bytes)

    def test_late_prior_attempt_result_cannot_complete_resumed_task_and_recovery_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = self.make_git_repo(root)
            run_dir = self.initialize(root, self.source_plan(root), self.decisions(root, self.resolved_decision()), base)
            self.block(run_dir)
            resume_task(run_dir, task_id="PX-01", prior_attempt="attempt-1", new_owner="worker", new_attempt="attempt-2", decision_ref="D-100")
            revision = validate_run(run_dir).revision
            self.assertEqual(validate_run(run_dir).revision, revision)
            self.assertEqual(self.task(run_dir).attempt, "attempt-2")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                complete_task(run_dir, task_id="PX-01", attempt="attempt-1", phase_plan=self.source_plan(root), source_ref="HEAD", commits=(base,), artifacts=(), evidence=("tests.log",), repo_dir=repo)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_source_completion_and_complete_integration_ancestry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = self.make_git_repo(root)
            plan = self.source_plan(root)
            run_dir = self.initialize(repo, plan, self.decisions(root, self.resolved_decision()), base)
            self.git(repo, "checkout", "-qb", "worker")
            (repo / "src.txt").write_text("worker\n", encoding="utf-8")
            self.git(repo, "add", "src.txt")
            self.git(repo, "commit", "-qm", "worker")
            worker_commit = self.git(repo, "rev-parse", "HEAD")
            start_task(run_dir, task_id="PX-01", owner="worker", attempt="attempt-1")
            completed = complete_task(run_dir, task_id="PX-01", attempt="attempt-1", phase_plan=plan, source_ref="worker", commits=(worker_commit,), artifacts=(), evidence=("tests.log",), repo_dir=repo)
            task = next(task for task in completed.tasks if task.id == "PX-01")
            self.assertEqual((task.state, task.integration), ("[x]", "-"))
            with self.assertRaises(TransitionError):
                start_task(run_dir, task_id="PX-02", owner="dependent", attempt="dep-1")
            self.git(repo, "checkout", "-q", "target")
            (repo / "unrelated.txt").write_text("target only\n", encoding="utf-8")
            self.git(repo, "add", "unrelated.txt")
            self.git(repo, "commit", "-qm", "unrelated target")
            unrelated = self.git(repo, "rev-parse", "HEAD")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                record_task_integration(run_dir, task_id="PX-01", integration_commit=unrelated, verification=("integrated-tests.log",), repo_dir=repo)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            self.git(repo, "merge", "--no-ff", "-qm", "integrate worker", "worker")
            integrated = self.git(repo, "rev-parse", "HEAD")
            record_task_integration(run_dir, task_id="PX-01", integration_commit=integrated, verification=("integrated-tests.log",), repo_dir=repo)
            started_dep = start_task(run_dir, task_id="PX-02", owner="dependent", attempt="dep-1")
            self.assertEqual(next(task for task in started_dep.tasks if task.id == "PX-02").state, "[~]")

    def test_artifact_task_requires_exact_outputs_and_evidence_without_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = self.make_git_repo(root)
            plan = self.artifact_plan(root)
            run_dir = self.initialize(root, plan, self.decisions(root, self.resolved_decision(task="PA-01")), base)
            start_task(run_dir, task_id="PA-01", owner="controller", attempt="artifact-1")
            (repo / "evidence").mkdir()
            output = repo / "evidence/result.md"
            output.write_text("evidence\n", encoding="utf-8")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                complete_task(run_dir, task_id="PA-01", attempt="artifact-1", phase_plan=plan, source_ref=None, commits=(), artifacts=(Path("evidence/result.md"),), evidence=(), repo_dir=repo)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            completed = complete_task(run_dir, task_id="PA-01", attempt="artifact-1", phase_plan=plan, source_ref=None, commits=(), artifacts=(Path("evidence/result.md"),), evidence=("artifact-validation.log",), repo_dir=repo)
            task = next(task for task in completed.tasks if task.id == "PA-01")
            self.assertEqual((task.state, task.commits, task.integration), ("[x]", "-", "N/A"))


class SchedulerReadinessTest(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ("git", *args), cwd=repo, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()

    def write_plan(self, root: Path, tasks: tuple[str, ...]) -> Path:
        path = root / "phase.md"
        body = [
            "# Scheduler phase",
            "",
            "<!-- pipeline-v2-phase: id=77; deps=none; review_gate=final-only; review_reason=Mechanical verification only. -->",
            "",
        ]
        for heading, metadata in zip((f"### PS-{i:02d} — Task" for i in range(1, len(tasks) + 1)), tasks):
            body.extend((heading, metadata, ""))
        path.write_text("\n".join(body), encoding="utf-8")
        return path

    def task(self, task_id: str, *, deps: str = "none", batch: str = "batch", order: int = 1, scope: str | None = None) -> str:
        scope = scope or f"file:{task_id.lower()}.txt"
        return (
            f"<!-- pipeline-v2-task: id={task_id}; deps={deps}; kind=source; "
            f"batch={batch}; order={order}; write_scope={scope}; outputs=none -->"
        )

    def initialize(self, root: Path, plan: Path, *, worker_limit: int = 3) -> Path:
        decisions = root / "decisions.md"
        decisions.write_text("# Decisions\n", encoding="utf-8")
        run_dir = root / "run"
        initialize_run(
            run_dir,
            run_id="scheduler-test",
            base_commit="a" * 40,
            target_branch="target",
            worker_limit=worker_limit,
            artifacts={
                "spec": "spec.md", "master_plan": "master.md",
                "phase_plans": str(plan), "decisions": str(decisions), "findings": "findings.md",
            },
            approved_existing=(),
        )
        return run_dir

    def test_independent_exact_file_scopes_can_reserve_together_and_limit_is_global(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.write_plan(root, tuple(self.task(f"PS-{i:02d}", batch=f"b{i}") for i in range(1, 4)))
            run_dir = self.initialize(root, plan, worker_limit=2)
            ready = next_eligible_actions(run_dir, plan, capacity=2)
            self.assertEqual(tuple(task.id for task in ready), ("PS-01", "PS-02"))
            reserved = reserve_tasks(
                run_dir, plan, task_ids=("PS-01", "PS-02"), owners=("worker-1", "worker-2"),
                attempts=("attempt-1", "attempt-2"), capacity=2,
            )
            self.assertEqual(sum(task.state == "[~]" for task in reserved.tasks), 2)
            self.assertEqual(next_eligible_actions(run_dir, plan, capacity=2), ())
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                reserve_tasks(
                    run_dir, plan, task_ids=("PS-03",), owners=("worker-3",),
                    attempts=("attempt-3",), capacity=2,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_identical_and_tree_child_scopes_conflict(self):
        cases = (
            ("file:shared.txt", "file:shared.txt"),
            ("tree:shared", "file:shared/child.txt"),
            ("tree:shared", "tree:shared/nested"),
        )
        for left, right in cases:
            with self.subTest(left=left, right=right), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self.write_plan(
                    root,
                    (
                        self.task("PS-01", batch="a", scope=left),
                        self.task("PS-02", batch="b", scope=right),
                    ),
                )
                run_dir = self.initialize(root, plan)
                self.assertEqual(tuple(task.id for task in next_eligible_actions(run_dir, plan, capacity=3)), ("PS-01",))
                before = (run_dir / "progress.md").read_bytes()
                with self.assertRaises(TransitionError):
                    reserve_tasks(
                        run_dir, plan, task_ids=("PS-01", "PS-02"),
                        owners=("worker-1", "worker-2"), attempts=("a-1", "a-2"), capacity=3,
                    )
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_stale_readiness_is_revalidated_for_state_and_consumed_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.write_plan(root, tuple(self.task(f"PS-{i:02d}", batch=f"b{i}") for i in range(1, 4)))
            run_dir = self.initialize(root, plan, worker_limit=2)
            stale = next_eligible_actions(run_dir, plan, capacity=2)
            self.assertEqual(tuple(task.id for task in stale), ("PS-01", "PS-02"))
            start_task(run_dir, task_id="PS-03", owner="worker-3", attempt="attempt-3")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                reserve_tasks(
                    run_dir, plan, task_ids=tuple(task.id for task in stale),
                    owners=("worker-1", "worker-2"), attempts=("attempt-1", "attempt-2"), capacity=2,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            start_task(run_dir, task_id="PS-01", owner="worker-1", attempt="attempt-1")
            record_task_question(
                run_dir, task_id="PS-01", attempt="attempt-1",
                question_or_block_ref="D-200", reason="needs user decision",
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                reserve_tasks(
                    run_dir, plan, task_ids=("PS-01",), owners=("worker-1",),
                    attempts=("attempt-4",), capacity=2,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_dependency_and_unknown_capacity_block_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.write_plan(
                root,
                (
                    self.task("PS-01", batch="a"),
                    self.task("PS-02", deps="PS-01", batch="b"),
                ),
            )
            run_dir = self.initialize(root, plan)
            with self.assertRaisesRegex(TransitionError, "capacity"):
                next_eligible_actions(run_dir, plan, capacity=None)
            with self.assertRaisesRegex(TransitionError, "capacity"):
                next_eligible_actions(run_dir, plan, capacity=2)
            self.assertEqual(tuple(task.id for task in next_eligible_actions(run_dir, plan, capacity=3)), ("PS-01",))

    def test_queued_dependency_becomes_eligible_after_capacity_and_integration_are_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.git(root, "init", "-q")
            self.git(root, "config", "user.email", "pipeline@example.invalid")
            self.git(root, "config", "user.name", "Pipeline Test")
            (root / "base.txt").write_text("base\n", encoding="utf-8")
            self.git(root, "add", "base.txt")
            self.git(root, "commit", "-qm", "base")
            self.git(root, "branch", "target")
            plan = self.write_plan(
                root,
                (
                    self.task("PS-01", batch="a", scope="file:ps-01.txt"),
                    self.task("PS-02", deps="PS-01", batch="b", scope="file:ps-02.txt"),
                ),
            )
            run_dir = self.initialize(root, plan, worker_limit=1)
            reserve_tasks(
                run_dir, plan, task_ids=("PS-01",), owners=("worker-1",),
                attempts=("attempt-1",), capacity=1,
            )
            self.assertEqual(next_eligible_actions(run_dir, plan, capacity=1), ())
            self.git(root, "checkout", "-q", "target")
            (root / "ps-01.txt").write_text("implemented\n", encoding="utf-8")
            self.git(root, "add", "ps-01.txt")
            self.git(root, "commit", "-qm", "implement PS-01")
            commit = self.git(root, "rev-parse", "HEAD")
            complete_task(
                run_dir, task_id="PS-01", attempt="attempt-1", phase_plan=plan,
                source_ref="target", commits=(commit,), artifacts=(), evidence=("task-tests",), repo_dir=root,
            )
            record_task_integration(
                run_dir, task_id="PS-01", integration_commit=commit,
                verification=(f"integrated:{commit}",), repo_dir=root,
            )
            self.assertEqual(
                tuple(task.id for task in next_eligible_actions(run_dir, plan, capacity=1)),
                ("PS-02",),
            )

    def test_reservation_rejects_unknown_duplicate_or_partial_identity_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.write_plan(root, (self.task("PS-01"), self.task("PS-02", batch="two")))
            run_dir = self.initialize(root, plan)
            cases = (
                (("PS-99",), ("worker",), ("attempt",)),
                (("PS-01", "PS-01"), ("worker-1", "worker-2"), ("a-1", "a-2")),
                (("PS-01", "PS-02"), ("worker",), ("a-1", "a-2")),
                (("PS-01", "PS-02"), ("worker-1", "worker-2"), ("same", "same")),
            )
            for task_ids, owners, attempts in cases:
                with self.subTest(task_ids=task_ids, owners=owners, attempts=attempts):
                    before = (run_dir / "progress.md").read_bytes()
                    with self.assertRaises(TransitionError):
                        reserve_tasks(
                            run_dir, plan, task_ids=task_ids, owners=owners,
                            attempts=attempts, capacity=3,
                        )
                    self.assertEqual((run_dir / "progress.md").read_bytes(), before)


class WorkerResultImportTest(unittest.TestCase):
    def test_named_result_fixtures_have_strict_owner_and_status_contract(self):
        done = parse_worker_result((FIXTURES / "valid-result-done.md").read_text(encoding="utf-8"))
        blocked = parse_worker_result((FIXTURES / "valid-result-needs-context.md").read_text(encoding="utf-8"))
        stale = parse_worker_result((FIXTURES / "stale-result.md").read_text(encoding="utf-8"))
        conflicting = parse_worker_result((FIXTURES / "conflicting-result.md").read_text(encoding="utf-8"))
        self.assertEqual((done.owner, done.status), ("worker-1", "DONE"))
        self.assertEqual((blocked.owner, blocked.status, blocked.question), ("worker-1", "NEEDS_CONTEXT", "D-900"))
        self.assertNotEqual(stale.attempt, done.attempt)
        self.assertNotEqual(conflicting.owner, done.owner)

    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ("git", *args), cwd=repo, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()

    def make_run(self, root: Path) -> tuple[Path, Path, str]:
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "pipeline@example.invalid")
        self.git(root, "config", "user.name", "Pipeline Test")
        (root / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(root, "add", "base.txt")
        self.git(root, "commit", "-qm", "base")
        base = self.git(root, "rev-parse", "HEAD")
        self.git(root, "branch", "target")
        plan = root / "phase.md"
        plan.write_text(
            """# Result phase

<!-- pipeline-v2-phase: id=88; deps=none; review_gate=final-only; review_reason=Mechanical verification only. -->

### PR-01 — Source
<!-- pipeline-v2-task: id=PR-01; deps=none; kind=source; batch=source; order=1; write_scope=file:source.txt; outputs=none -->

### PR-02 — Artifact
<!-- pipeline-v2-task: id=PR-02; deps=none; kind=artifact; batch=artifact; order=2; write_scope=tree:evidence; outputs=evidence/artifact.md -->
""",
            encoding="utf-8",
        )
        decisions = root / "decisions.md"
        decisions.write_text("# Decisions\n", encoding="utf-8")
        run_dir = root / "run"
        initialize_run(
            run_dir, run_id="result-test", base_commit=base, target_branch="target", worker_limit=3,
            artifacts={
                "spec": "spec.md", "master_plan": "master.md", "phase_plans": str(plan),
                "decisions": str(decisions), "findings": "findings.md",
            },
            approved_existing=(),
        )
        (run_dir / "agent-output").mkdir()
        (run_dir / "agent-output/test.log").write_text("targeted tests passed\n", encoding="utf-8")
        return run_dir, plan, base

    def commit_source(self, root: Path) -> str:
        self.git(root, "checkout", "-qb", "worker")
        (root / "source.txt").write_text("implemented\n", encoding="utf-8")
        self.git(root, "add", "source.txt")
        self.git(root, "commit", "-qm", "source result")
        return self.git(root, "rev-parse", "HEAD")

    def result_text(
        self, *, task_id: str, attempt: str, owner: str, kind: str = "source",
        status: str = "DONE", source_ref: str = "-", commits: str = "-",
        artifacts: str = "-", question: str = "-", blocking_reason: str = "-",
    ) -> str:
        return f"""<!-- pipeline-worker-result/v2 -->
# Pipeline v2 — Worker Result

## Result
| Field | Value |
| --- | --- |
| run_id | result-test |
| task_id | {task_id} |
| attempt | {attempt} |
| owner | {owner} |
| kind | {kind} |
| status | {status} |
| source_ref | {source_ref} |
| commits | {commits} |
| artifacts | {artifacts} |
| tests | targeted tests |
| evidence | agent-output/test.log |
| concerns | - |
| question | {question} |
| blocking_reason | {blocking_reason} |

## Checkpoints
| ID | Status | Evidence |
| --- | --- | --- |
| tested | complete | agent-output/test.log |
"""

    def write_result(self, run_dir: Path, name: str, text: str) -> Path:
        path = run_dir / "agent-output" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_matching_source_and_artifact_result_owner_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plan, _ = self.make_run(root)
            commit = self.commit_source(root)
            start_task(run_dir, task_id="PR-01", owner="worker-a", attempt="source-1")
            source_path = self.write_result(
                run_dir, "source.md",
                self.result_text(
                    task_id="PR-01", attempt="source-1", owner="worker-a",
                    source_ref="worker", commits=commit,
                ),
            )
            imported = import_worker_result(run_dir, result_path=source_path, phase_plan=plan, repo_dir=root)
            source = next(task for task in imported.tasks if task.id == "PR-01")
            self.assertEqual((source.state, source.owner, source.commits), ("[x]", "worker-a", commit))

            (root / "evidence").mkdir()
            (root / "evidence/artifact.md").write_text("evidence\n", encoding="utf-8")
            start_task(run_dir, task_id="PR-02", owner="worker-a", attempt="artifact-1")
            artifact_path = self.write_result(
                run_dir, "artifact.md",
                self.result_text(
                    task_id="PR-02", attempt="artifact-1", owner="worker-a", kind="artifact",
                    artifacts="evidence/artifact.md",
                ),
            )
            imported = import_worker_result(run_dir, result_path=artifact_path, phase_plan=plan, repo_dir=root)
            artifact = next(task for task in imported.tasks if task.id == "PR-02")
            self.assertEqual((artifact.state, artifact.owner, artifact.integration), ("[x]", "worker-a", "N/A"))

    def test_matching_needs_context_and_blocked_result_owner_imports(self):
        for status in ("NEEDS_CONTEXT", "PLAN_CONFLICT", "BLOCKED"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir, plan, _ = self.make_run(root)
                start_task(run_dir, task_id="PR-01", owner="worker-a", attempt="attempt-1")
                result_path = self.write_result(
                    run_dir, f"{status.lower()}.md",
                    self.result_text(
                        task_id="PR-01", attempt="attempt-1", owner="worker-a", status=status,
                        question="D-301", blocking_reason="blocked by user choice" if status == "BLOCKED" else "-",
                    ),
                )
                imported = import_worker_result(run_dir, result_path=result_path, phase_plan=plan, repo_dir=root)
                task = next(task for task in imported.tasks if task.id == "PR-01")
                self.assertEqual((task.state, task.owner, task.attempt, task.question), ("[?]", "worker-a", "attempt-1", "D-301"))

    def test_kind_commit_artifact_and_evidence_conflicts_are_rejected_unchanged(self):
        cases = ("kind", "source-ref", "artifact", "evidence")
        for label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir, plan, _ = self.make_run(root)
                if label == "artifact":
                    start_task(run_dir, task_id="PR-02", owner="worker-a", attempt="attempt-1")
                    text = self.result_text(
                        task_id="PR-02", attempt="attempt-1", owner="worker-a", kind="artifact",
                        artifacts="evidence/artifact.md",
                    )
                else:
                    commit = self.commit_source(root)
                    start_task(run_dir, task_id="PR-01", owner="worker-a", attempt="attempt-1")
                    text = self.result_text(
                        task_id="PR-01", attempt="attempt-1", owner="worker-a",
                        source_ref="target" if label == "source-ref" else "worker", commits=commit,
                    )
                    if label == "kind":
                        text = text.replace("| kind | source |", "| kind | artifact |").replace(
                            f"| source_ref | worker |\n| commits | {commit} |\n| artifacts | - |",
                            "| source_ref | - |\n| commits | - |\n| artifacts | evidence/artifact.md |",
                        )
                if label == "evidence":
                    text = text.replace("agent-output/test.log", "agent-output/missing.log")
                result_path = self.write_result(run_dir, f"{label}.md", text)
                before = (run_dir / "progress.md").read_bytes()
                with self.assertRaises((EvidenceError, SchemaError)):
                    import_worker_result(run_dir, result_path=result_path, phase_plan=plan, repo_dir=root)
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_missing_empty_or_wrong_owner_rejects_without_tracker_change(self):
        cases = {
            "missing": lambda text: text.replace("| owner | worker-a |\n", ""),
            "empty": lambda text: text.replace("| owner | worker-a |", "| owner | - |"),
            "wrong": lambda text: text.replace("| owner | worker-a |", "| owner | worker-b |"),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir, plan, _ = self.make_run(root)
                commit = self.commit_source(root)
                start_task(run_dir, task_id="PR-01", owner="worker-a", attempt="attempt-1")
                text = self.result_text(
                    task_id="PR-01", attempt="attempt-1", owner="worker-a",
                    source_ref="worker", commits=commit,
                )
                result_path = self.write_result(run_dir, "result.md", mutate(text))
                before = (run_dir / "progress.md").read_bytes()
                with self.assertRaises((SchemaError, EvidenceError)):
                    import_worker_result(run_dir, result_path=result_path, phase_plan=plan, repo_dir=root)
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_same_owner_superseded_attempt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plan, _ = self.make_run(root)
            commit = self.commit_source(root)
            start_task(run_dir, task_id="PR-01", owner="worker-a", attempt="attempt-1")
            record_task_question(
                run_dir, task_id="PR-01", attempt="attempt-1",
                question_or_block_ref="D-300", reason="requires answer",
            )
            (root / "decisions.md").write_text(
                """# Decisions

## D-300 — Answer

- **Question:** Which behavior?
- **Answer:** Use the explicitly recorded behavior.
- **Scope:** PR-01 current blocker.
- **Status:** Resolved.
""",
                encoding="utf-8",
            )
            resume_task(
                run_dir, task_id="PR-01", prior_attempt="attempt-1",
                new_owner="worker-a", new_attempt="attempt-2", decision_ref="D-300",
            )
            stale_path = self.write_result(
                run_dir, "stale.md",
                self.result_text(
                    task_id="PR-01", attempt="attempt-1", owner="worker-a",
                    source_ref="worker", commits=commit,
                ),
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(EvidenceError):
                import_worker_result(run_dir, result_path=stale_path, phase_plan=plan, repo_dir=root)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_identical_accepted_replay_is_noop_but_altered_owner_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plan, _ = self.make_run(root)
            commit = self.commit_source(root)
            start_task(run_dir, task_id="PR-01", owner="worker-a", attempt="attempt-1")
            text = self.result_text(
                task_id="PR-01", attempt="attempt-1", owner="worker-a",
                source_ref="worker", commits=commit,
            )
            result_path = self.write_result(run_dir, "result.md", text)
            first = import_worker_result(run_dir, result_path=result_path, phase_plan=plan, repo_dir=root)
            accepted = (run_dir / "progress.md").read_bytes()
            replay = import_worker_result(run_dir, result_path=result_path, phase_plan=plan, repo_dir=root)
            self.assertEqual((replay.revision, (run_dir / "progress.md").read_bytes()), (first.revision, accepted))
            result_path.write_text(text.replace("| owner | worker-a |", "| owner | worker-b |"), encoding="utf-8")
            with self.assertRaises(EvidenceError):
                import_worker_result(run_dir, result_path=result_path, phase_plan=plan, repo_dir=root)
            self.assertEqual((run_dir / "progress.md").read_bytes(), accepted)

    def test_publish_is_atomic_immutable_and_never_touches_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, _ = self.make_run(root)
            result_path = run_dir / "agent-output/result.md"
            result = WorkerResult(
                run_id="result-test", task_id="PR-01", attempt="attempt-1", owner="worker-a",
                kind="source", status="DONE", source_ref="worker", commits=("a" * 40,), artifacts=(),
                tests="targeted tests", evidence=("agent-output/test.log",), concerns="-", question="-",
                blocking_reason="-", checkpoints=(Checkpoint("tested", "complete", "agent-output/test.log"),),
            )
            tracker_before = (run_dir / "progress.md").read_bytes()
            publish_worker_result(result_path, result)
            published = result_path.read_bytes()
            self.assertEqual(parse_worker_result(published.decode("utf-8")), result)
            self.assertEqual((run_dir / "progress.md").read_bytes(), tracker_before)
            publish_worker_result(result_path, result)
            self.assertEqual(result_path.read_bytes(), published)
            changed = dataclasses.replace(result, owner="worker-b")
            with self.assertRaises(EvidenceError):
                publish_worker_result(result_path, changed)
            self.assertEqual(result_path.read_bytes(), published)


if __name__ == "__main__":
    unittest.main()
