from __future__ import annotations

import dataclasses
import io
import multiprocessing
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import plugins.superb.skills.pipeline.scripts.pipeline_state as pipeline_state
from plugins.superb.skills.pipeline.scripts.pipeline_state import (
    LegacySchemaError,
    LockBusyError,
    LockUnavailableError,
    PlanMetadataError,
    SchemaError,
    TrackerWriteError,
    UpdateOutcomeUncertain,
    initialize_run,
    inspect_run,
    locked_tracker_update,
    main,
    parse_phase_plan,
    parse_tracker,
    parse_worker_result,
    render_tracker,
    validate_run,
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


if __name__ == "__main__":
    unittest.main()
