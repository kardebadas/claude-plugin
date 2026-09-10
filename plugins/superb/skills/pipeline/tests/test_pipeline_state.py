from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import multiprocessing
import plistlib
import re
import subprocess
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
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
    record_phase_verification as _record_phase_verification,
    reconcile_run,
    open_review_gate as _open_review_gate,
    start_remediation_round as _start_remediation_round,
    evaluate_and_close_review_gate,
    render_tracker,
    resume_task as _resume_task,
    reserve_tasks as _reserve_tasks,
    ReconciliationReport,
    start_task as _start_task,
    validate_run,
    WorkerResult,
)


REPOSITORY = Path(__file__).resolve().parents[5]
FIXTURES = Path(__file__).with_name("fixtures")


def start_task(run_dir: Path, **kwargs):
    """Exercise ordinary starts with an explicit controller capacity binding."""
    with pipeline_state.bind_runtime_capacity_provider(
        run_dir, lambda _run, tracker: tracker.worker_limit
    ):
        return _start_task(run_dir, **kwargs)


def resume_task(run_dir: Path, **kwargs):
    """Exercise ordinary resumes with an explicit controller capacity binding."""
    with pipeline_state.bind_runtime_capacity_provider(
        run_dir, lambda _run, tracker: tracker.worker_limit
    ):
        return _resume_task(run_dir, **kwargs)


def open_review_gate(run_dir: Path, **kwargs):
    """Exercise review reservations with an explicit controller capacity binding."""
    with pipeline_state.bind_runtime_capacity_provider(
        run_dir, lambda _run, tracker: tracker.worker_limit
    ):
        return _open_review_gate(run_dir, **kwargs)


def start_remediation_round(run_dir: Path, **kwargs):
    """Exercise fixer reservations with an explicit controller capacity binding."""
    with pipeline_state.bind_runtime_capacity_provider(
        run_dir, lambda _run, tracker: tracker.worker_limit
    ):
        return _start_remediation_round(run_dir, **kwargs)


def reserve_tasks(run_dir: Path, *args, **kwargs):
    """Exercise batch reservations with an explicit controller capacity binding."""
    with pipeline_state.bind_runtime_capacity_provider(
        run_dir, lambda _run, tracker: tracker.worker_limit
    ):
        return _reserve_tasks(run_dir, *args, **kwargs)


def record_phase_verification(run_dir: Path, **kwargs):
    """Use the approved synthetic phase suite in legacy test setup calls."""
    if kwargs.get("commands") in {("suite",), ("full suite",)}:
        tracker = parse_tracker((Path(run_dir) / "progress.md").read_text(encoding="utf-8"))
        metadata, _ = pipeline_state._phase_document_for(
            tracker, Path(run_dir), kwargs["phase_id"]
        )
        kwargs["commands"] = metadata.verification_commands
    return _record_phase_verification(run_dir, **kwargs)


def record_remediation_fixes(run_dir: Path, **kwargs):
    """Exercise fixer release with an explicit controller capacity binding."""
    with pipeline_state.bind_runtime_capacity_provider(
        run_dir, lambda _run, tracker: tracker.worker_limit
    ):
        return pipeline_state.record_remediation_fixes(run_dir, **kwargs)


def _verification_evidence(
    root: Path,
    head: str,
    label: str = "suite",
    *,
    purpose: str = "phase",
    run_id: str = "gate-test",
    subject: str = "phase/01",
    attempt: str = "N/A",
    commands: tuple[str, ...] | None = None,
    inputs: str = "test-fixture",
) -> str:
    command_values = commands or ("suite", "full suite")
    path = root / f"verification-{label}-{head[:12]}.md"
    path.write_text(
        "<!-- pipeline-verification-evidence/v2 -->\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        f"| purpose | {purpose} |\n"
        f"| run_id | {run_id} |\n"
        f"| subject | {subject} |\n"
        f"| attempt | {attempt} |\n"
        f"| code_state | {head} |\n"
        "| outcome | PASS |\n"
        f"| commands | {pipeline_state.json.dumps(command_values, separators=(',', ':'))} |\n"
        "| environment | test-local |\n"
        f"| inputs | {inputs} |\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path.name}#sha256={digest}@{head}"


def _artifact_validation_evidence(
    root: Path,
    head: str,
    *,
    run_id: str,
    task_id: str,
    attempt: str,
    outputs: tuple[str, ...],
    label: str = "artifact-validation",
) -> str:
    identities = []
    for output in outputs:
        path = root / output
        identities.append(f"{output}#sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")
    return _verification_evidence(
        root, head, label, purpose="task-test", run_id=run_id,
        subject=f"task/{task_id}", attempt=attempt,
        commands=("artifact-validation",),
        inputs=json.dumps(identities, separators=(",", ":")),
    )


def _remediation_evidence(
    root: Path,
    head: str,
    gate_id: str,
    round_number: int,
    label: str,
    *,
    run_id: str = "gate-test",
) -> str:
    return _verification_evidence(
        root, head, label, purpose="remediation", run_id=run_id,
        subject=f"gate/{gate_id}", attempt=f"round-{round_number}",
        commands=("fix-suite",),
    )


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
            "<filesystem_class>": "supported-local",
            "<filesystem_type>": "ext4",
            "<filesystem_fingerprint>": "a" * 64,
            "<filesystem_ack>": "N/A",
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
            "empty blocker outcome": valid.replace(
                "remaining-blockers=F-001", "remaining-blockers="
            ),
            "duplicate blocker id": valid.replace(
                "remaining-blockers=F-001", "remaining-blockers=F-001+F-001"
            ),
            "unknown blocker id": valid.replace(
                "remaining-blockers=F-001", "remaining-blockers=F-999"
            ),
            "mixed none blocker outcome": valid.replace(
                "remaining-blockers=F-001", "remaining-blockers=none+F-001"
            ),
            "duplicate blocker outcome field": valid.replace(
                "remaining-blockers=F-001", "remaining-blockers=F-001,remaining-blockers=F-001"
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

    def test_phase_and_task_metadata_must_be_adjacent_to_their_headings(self):
        valid = self.fixture_path("phase-plan-valid.md").read_text(encoding="utf-8")
        cases = {
            "detached phase": valid.replace(
                "<!-- pipeline-v2-phase: id=99; deps=none; review_gate=final-only; review_reason=Mechanical verification is sufficient before the master gate. -->",
                "## Detached metadata\n\n<!-- pipeline-v2-phase: id=99; deps=none; review_gate=final-only; review_reason=Mechanical verification is sufficient before the master gate. -->",
            ),
            "detached task": valid.replace(
                "### PX-01 — Source task\n<!-- pipeline-v2-task:",
                "### PX-01 — Source task\nIntervening prose.\n<!-- pipeline-v2-task:",
            ),
        }
        for label, source in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
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

    def test_phase_plan_rejects_more_than_twelve_tasks_and_dependency_cycles(self):
        def document(task_count: int, dependencies: dict[int, str] | None = None) -> str:
            dependencies = dependencies or {}
            tasks = []
            for number in range(1, task_count + 1):
                task_id = f"PX-{number:02d}"
                tasks.append(
                    f"### {task_id} — Source\n"
                    f"<!-- pipeline-v2-task: id={task_id}; deps={dependencies.get(number, 'none')}; kind=source; batch=core; order={number}; write_scope=file:src/{number}.py; outputs=none -->\n"
                    f"<!-- pipeline-v2-task-suite: id={task_id}; commands=[\"test-{number}\"] -->\n"
                )
            return (
                "# Phase\n\n"
                "<!-- pipeline-v2-phase: id=99; deps=none; review_gate=final-only; review_reason=Mechanical verification is sufficient. -->\n"
                "<!-- pipeline-v2-phase-suite: id=99; commands=[\"phase-suite\"] -->\n\n"
                + "\n".join(tasks)
            )

        invalid = {
            "thirteen tasks": document(13),
            "two-node cycle": document(2, {1: "PX-02", 2: "PX-01"}),
        }
        for label, source in invalid.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "phase.md"
                path.write_text(source, encoding="utf-8")
                with self.assertRaises(PlanMetadataError):
                    parse_phase_plan(path)


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
        docs = root / "docs"
        docs.mkdir(exist_ok=True)
        master = docs / "master.md"
        master.write_text(
            f"# Master\n\n- **Detailed plan:** `{phase}`\n", encoding="utf-8"
        )
        artifacts = {
            "spec": str(docs / "spec.md"),
            "master_plan": str(master),
            "phase_plans": str(phase),
            "decisions": str(docs / "decisions.md"),
            "findings": str(docs / "findings.md"),
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

    def test_initialize_rejects_non_executable_phase_dependency_order(self):
        """A known dependency that appears later must fail at ingestion, not deadlock readiness."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plans = []
            for phase_id, deps in (("01", "none"), ("02", "03"), ("03", "02")):
                task_id = f"P{phase_id}-01"
                path = root / f"phase-{phase_id}.md"
                path.write_text(
                    f"# Phase {phase_id}\n\n"
                    f"<!-- pipeline-v2-phase: id={phase_id}; deps={deps}; review_gate=final-only; review_reason=Mechanical verification is sufficient. -->\n"
                    f"<!-- pipeline-v2-phase-suite: id={phase_id}; commands=[\"phase-{phase_id}\"] -->\n\n"
                    f"### {task_id} — Source\n"
                    f"<!-- pipeline-v2-task: id={task_id}; deps=none; kind=source; batch=core; order=1; write_scope=file:src/{phase_id}.py; outputs=none -->\n"
                    f"<!-- pipeline-v2-task-suite: id={task_id}; commands=[\"test-{phase_id}\"] -->\n",
                    encoding="utf-8",
                )
                plans.append(path)
            master = root / "master.md"
            master.write_text(
                "# Master\n\n" + "\n".join(f"- **Detailed plan:** `{path}`" for path in plans),
                encoding="utf-8",
            )
            artifacts = {
                "spec": str(root / "spec.md"),
                "master_plan": str(master),
                "phase_plans": ",".join(str(path) for path in plans),
                "decisions": str(root / "decisions.md"),
                "findings": str(root / "findings.md"),
            }
            run_dir = root / "run"
            before = self.snapshot(root)
            with self.assertRaises(SchemaError):
                self.initialize(run_dir, artifacts)
            self.assertEqual(self.snapshot(root), before)

    def test_initial_tracker_publication_is_atomic_no_clobber_and_stage_aware(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts, _ = self.inputs(root)
            run_dir = root / "pre-publication"
            with mock.patch.object(
                pipeline_state, "_sync_file", side_effect=OSError("injected temp sync failure")
            ):
                with self.assertRaises(TrackerWriteError):
                    self.initialize(run_dir, artifacts)
            self.assertFalse((run_dir / "progress.md").exists())
            self.assertFalse(any(run_dir.glob(".progress.*.tmp")))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts, _ = self.inputs(root)
            run_dir = root / "competing"
            run_dir.mkdir()
            sentinel = b"competing initializer won\n"

            def competing_link(_source, destination):
                Path(destination).write_bytes(sentinel)
                raise FileExistsError("injected competing publication")

            with mock.patch.object(pipeline_state.os, "link", side_effect=competing_link):
                with self.assertRaises(TrackerWriteError):
                    self.initialize(run_dir, artifacts)
            self.assertEqual((run_dir / "progress.md").read_bytes(), sentinel)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts, _ = self.inputs(root)
            run_dir = root / "post-publication"
            with mock.patch.object(
                pipeline_state, "_sync_directory", side_effect=OSError("injected directory sync failure")
            ):
                with self.assertRaises(UpdateOutcomeUncertain) as caught:
                    self.initialize(run_dir, artifacts)
            self.assertIsNotNone(caught.exception.tracker)
            self.assertEqual(validate_run(run_dir), caught.exception.tracker)

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

    def test_mutation_preflight_rejects_malformed_state_without_creating_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "malformed"
            run_dir.mkdir()
            (run_dir / "progress.md").write_bytes((FIXTURES / "malformed-v2-progress.md").read_bytes())
            before = self.snapshot(run_dir)
            with self.assertRaises(SchemaError):
                start_task(run_dir, task_id="P1-01", owner="worker", attempt="attempt-1")
            self.assertEqual(self.snapshot(run_dir), before)
            self.assertFalse((run_dir / ".pipeline-state.lock").exists())

    def test_validate_inspect_and_next_cli_never_invoke_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "2026-09-08-pipeline-rebuild-v2"
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
        info = pipeline_state.classify_filesystem(run_dir)
        text = (FIXTURES / "valid-v2-progress.md").read_text(encoding="utf-8")
        text = text.replace("a" * 64, info.fingerprint, 1)
        (run_dir / "progress.md").write_text(text, encoding="utf-8")
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
<!-- pipeline-v2-phase-suite: id=99; commands=["phase-suite"] -->

### PX-01 — Source
<!-- pipeline-v2-task: id=PX-01; deps=none; kind=source; batch=one; order=1; write_scope=file:src.txt; outputs=none -->
<!-- pipeline-v2-task-suite: id=PX-01; commands=["task-suite"] -->

### PX-02 — Dependent
<!-- pipeline-v2-task: id=PX-02; deps=PX-01; kind=source; batch=two; order=1; write_scope=file:dep.txt; outputs=none -->
<!-- pipeline-v2-task-suite: id=PX-02; commands=["dependent-suite"] -->
""",
        )

    def artifact_plan(self, root: Path) -> Path:
        return self.write_plan(
            root,
            """# Artifact phase

<!-- pipeline-v2-phase: id=99; deps=none; review_gate=final-only; review_reason=Mechanical verification only. -->
<!-- pipeline-v2-phase-suite: id=99; commands=["phase-suite"] -->

### PA-01 — Evidence
<!-- pipeline-v2-task: id=PA-01; deps=none; kind=artifact; batch=evidence; order=1; write_scope=tree:evidence; outputs=evidence/result.md -->
""",
        )

    def decisions(self, root: Path, text: str) -> Path:
        path = root / "decisions.md"
        path.write_text(text, encoding="utf-8")
        return path

    def initialize(self, root: Path, plan: Path, decisions: Path, base: str, target: str = "target") -> Path:
        project_root = root / "repo" if (root / "repo" / ".git").exists() else root
        run_dir = project_root / "run"
        (project_root / "master.md").write_text(
            f"# Master\n\n- **Detailed plan:** `{plan}`\n", encoding="utf-8"
        )
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

    def resolved_decision(
        self,
        task: str = "PX-01",
        answer: str = "Use the recorded interface.",
        action: str = "task.resume",
    ) -> str:
        return f"""# Decisions

## D-100 — Resume

- **Question:** Which interface applies?
- **Answer:** {answer}
- **Decision action:** {action}
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

    def task_evidence(self, repo: Path, head: str, task_id: str, attempt: str) -> str:
        return _verification_evidence(
            repo, head, f"task-{task_id}-{attempt}", purpose="task-test",
            run_id="transition-test", subject=f"task/{task_id}", attempt=attempt,
            commands=(("task-suite" if task_id == "PX-01" else "dependent-suite"),),
        )

    def integration_evidence(self, repo: Path, head: str, task_id: str) -> str:
        return _verification_evidence(
            repo, head, f"integration-{task_id}", purpose="task-integration",
            run_id="transition-test", subject=f"task/{task_id}", attempt="N/A",
            commands=("integration-suite",),
        )

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
            "missing action": self.resolved_decision().replace("- **Decision action:** task.resume\n", ""),
            "empty action": self.resolved_decision(action=""),
            "unknown action": self.resolved_decision(action="task.retry"),
            "wrong action": self.resolved_decision(action="review.resolve-question"),
            "duplicate action": self.resolved_decision()
            + "\n- **Decision action:** task.resume\n",
            "reviewer counterexample without action": self.resolved_decision(
                answer="Refuse this task; use the recorded interface."
            ).replace("- **Decision action:** task.resume\n", ""),
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
            (repo / "src.txt").write_text("implemented after answer\n", encoding="utf-8")
            self.git(repo, "add", "src.txt")
            self.git(repo, "commit", "-qm", "implement answered task")
            completed_head = self.git(repo, "rev-parse", "HEAD")
            completed = complete_task(
                run_dir, task_id="PX-01", attempt="attempt-2", phase_plan=plan,
                source_ref=completed_head, commits=(completed_head,), artifacts=(),
                evidence=(self.task_evidence(repo, completed_head, "PX-01", "attempt-2"),),
                repo_dir=repo,
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
            completed = complete_task(
                run_dir, task_id="PX-01", attempt="attempt-1", phase_plan=plan,
                source_ref="worker", commits=(worker_commit,), artifacts=(),
                evidence=(self.task_evidence(repo, worker_commit, "PX-01", "attempt-1"),),
                repo_dir=repo,
            )
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
            with self.assertRaises(TransitionError):
                record_task_integration(run_dir, task_id="PX-01", integration_commit=integrated, verification=("integrated-tests.log",), repo_dir=repo)
            record_task_integration(
                run_dir, task_id="PX-01", integration_commit=integrated,
                verification=(self.integration_evidence(repo, integrated, "PX-01"),),
                repo_dir=repo,
            )
            started_dep = start_task(run_dir, task_id="PX-02", owner="dependent", attempt="dep-1")
            self.assertEqual(next(task for task in started_dep.tasks if task.id == "PX-02").state, "[~]")

    def test_completion_rejects_unapproved_alternate_phase_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = self.make_git_repo(root)
            approved = self.source_plan(root)
            run_dir = self.initialize(root, approved, self.decisions(root, self.resolved_decision()), base)
            start_task(run_dir, task_id="PX-01", owner="worker", attempt="attempt-1")
            forged = root / "forged.md"
            forged.write_text(approved.read_text(encoding="utf-8"), encoding="utf-8")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                complete_task(
                    run_dir, task_id="PX-01", attempt="attempt-1", phase_plan=forged,
                    source_ref="target", commits=(base,), artifacts=(),
                    evidence=(f"tests:{base}",), repo_dir=repo,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

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
            evidence = _artifact_validation_evidence(
                repo, base, run_id="transition-test", task_id="PA-01",
                attempt="artifact-1", outputs=("evidence/result.md",),
            )
            completed = complete_task(run_dir, task_id="PA-01", attempt="artifact-1", phase_plan=plan, source_ref=None, commits=(), artifacts=(Path("evidence/result.md"),), evidence=(evidence,), repo_dir=repo)
            task = next(task for task in completed.tasks if task.id == "PA-01")
            self.assertEqual((task.state, task.commits, task.integration), ("[x]", "-", "N/A"))

    def test_artifact_completion_requires_attempt_bound_digest_evidence_and_revalidates_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = self.make_git_repo(root)
            plan = self.artifact_plan(root)
            run_dir = self.initialize(
                root, plan, self.decisions(root, self.resolved_decision(task="PA-01")), base
            )
            (repo / "evidence").mkdir()
            output = repo / "evidence/result.md"
            output.write_text("validated evidence\n", encoding="utf-8")
            start_task(run_dir, task_id="PA-01", owner="controller", attempt="artifact-1")
            valid = _artifact_validation_evidence(
                repo, base, run_id="transition-test", task_id="PA-01",
                attempt="artifact-1", outputs=("evidence/result.md",),
            )
            valid_path = repo / valid.split("#sha256=", 1)[0]
            valid_text = valid_path.read_text(encoding="utf-8")
            output_identity = "evidence/result.md#sha256=" + hashlib.sha256(output.read_bytes()).hexdigest()
            malformed_path = repo / "verification-malformed-artifact.md"
            malformed_path.write_text(
                valid_text.replace(f"| inputs | [\"{output_identity}\"] |", "| inputs | not-json |"),
                encoding="utf-8",
            )
            invalid = {
                "missing": "missing.md#sha256=" + "0" * 64 + f"@{base}",
                "false digest": valid.replace("#sha256=", "#sha256=" + "0" * 64, 1),
                "wrong task": _verification_evidence(
                    repo, base, "wrong-artifact-task", purpose="task-test",
                    run_id="transition-test", subject="task/OTHER", attempt="artifact-1",
                    commands=("artifact-validation",),
                    inputs=json.dumps([output_identity], separators=(",", ":")),
                ),
                "malformed": (
                    f"{malformed_path.name}#sha256={hashlib.sha256(malformed_path.read_bytes()).hexdigest()}@{base}"
                ),
            }
            for label, reference in invalid.items():
                with self.subTest(label=label):
                    before = (run_dir / "progress.md").read_bytes()
                    with self.assertRaises(TransitionError):
                        complete_task(
                            run_dir, task_id="PA-01", attempt="artifact-1",
                            phase_plan=plan, source_ref=None, commits=(),
                            artifacts=(Path("evidence/result.md"),), evidence=(reference,),
                            repo_dir=repo,
                        )
                    self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            completed = complete_task(
                run_dir, task_id="PA-01", attempt="artifact-1", phase_plan=plan,
                source_ref=None, commits=(), artifacts=(Path("evidence/result.md"),),
                evidence=(valid,), repo_dir=repo,
            )
            task = next(item for item in completed.tasks if item.id == "PA-01")
            self.assertTrue(pipeline_state._dependency_ready(run_dir, completed, task))
            output.write_text("mutated evidence\n", encoding="utf-8")
            self.assertFalse(pipeline_state._dependency_ready(run_dir, completed, task))
            output.write_text("validated evidence\n", encoding="utf-8")
            self.assertTrue(pipeline_state._dependency_ready(run_dir, completed, task))
            output.unlink()
            self.assertFalse(pipeline_state._dependency_ready(run_dir, completed, task))
            report = reconcile_run(run_dir, phase_plan=plan, repo_dir=repo)
            self.assertTrue(any("artifact-evidence-contradiction:PA-01" in item for item in report.questions))


class MasterProofIntegrityRegressionTest(unittest.TestCase):
    def test_phase_verification_rejects_substituted_omitted_duplicate_extra_and_reordered_commands(self):
        helper = PhaseGateAndRemediationTest()
        cases = {
            "substituted": ("only-smoke",),
            "omitted": ("suite",),
            "duplicate": ("suite", "suite", "full suite"),
            "extra": ("suite", "full suite", "optional"),
            "reordered": ("full suite", "suite"),
        }
        for label, evidence_commands in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir, _, head = helper.make_run(root)
                reference = _verification_evidence(
                    root,
                    head,
                    label,
                    commands=evidence_commands,
                )
                before = (run_dir / "progress.md").read_bytes()
                with self.assertRaises(TransitionError):
                    pipeline_state.record_phase_verification(
                        run_dir,
                        phase_id="01",
                        head=head,
                        commands=("suite", "full suite"),
                        evidence=(reference,),
                    )
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_source_attempt_requires_recorded_baseline_exact_nonempty_in_scope_range_and_pass_evidence(self):
        helper = TaskTransitionTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = helper.make_git_repo(root)
            plan = helper.source_plan(repo)
            run_dir = helper.initialize(
                repo, plan, helper.decisions(repo, helper.resolved_decision()), base
            )
            started = start_task(
                run_dir, task_id="PX-01", owner="worker-a", attempt="attempt-1"
            )
            task = next(item for item in started.tasks if item.id == "PX-01")
            self.assertIn(f"baseline:attempt-1@{base}", task.checkpoints)

            preexisting = _verification_evidence(
                repo,
                base,
                "preexisting",
                purpose="task-test",
                run_id="transition-test",
                subject="task/PX-01",
                attempt="attempt-1",
                commands=("task-suite",),
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                complete_task(
                    run_dir,
                    task_id="PX-01",
                    attempt="attempt-1",
                    phase_plan=plan,
                    source_ref=base,
                    commits=(base,),
                    artifacts=(),
                    evidence=(preexisting,),
                    repo_dir=repo,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            (repo / "outside.txt").write_text("outside\n", encoding="utf-8")
            helper.git(repo, "add", "outside.txt")
            helper.git(repo, "commit", "-qm", "outside scope")
            outside_head = helper.git(repo, "rev-parse", "HEAD")
            outside = _verification_evidence(
                repo,
                outside_head,
                "outside",
                purpose="task-test",
                run_id="transition-test",
                subject="task/PX-01",
                attempt="attempt-1",
                commands=("task-suite",),
            )
            with self.assertRaises(TransitionError):
                complete_task(
                    run_dir,
                    task_id="PX-01",
                    attempt="attempt-1",
                    phase_plan=plan,
                    source_ref=outside_head,
                    commits=(outside_head,),
                    artifacts=(),
                    evidence=(outside,),
                    repo_dir=repo,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_integration_evidence_requires_exact_typed_code_state_not_substring(self):
        helper = TaskTransitionTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = helper.make_git_repo(root)
            plan = helper.source_plan(repo)
            run_dir = helper.initialize(
                repo, plan, helper.decisions(repo, helper.resolved_decision()), base
            )
            start_task(run_dir, task_id="PX-01", owner="worker-a", attempt="attempt-1")
            (repo / "src.txt").write_text("implemented\n", encoding="utf-8")
            helper.git(repo, "add", "src.txt")
            helper.git(repo, "commit", "-qm", "implement source")
            head = helper.git(repo, "rev-parse", "HEAD")
            helper.git(repo, "branch", "-f", "target", head)
            task_evidence = _verification_evidence(
                repo,
                head,
                "task",
                purpose="task-test",
                run_id="transition-test",
                subject="task/PX-01",
                attempt="attempt-1",
                commands=("task-suite",),
            )
            complete_task(
                run_dir,
                task_id="PX-01",
                attempt="attempt-1",
                phase_plan=plan,
                source_ref=head,
                commits=(head,),
                artifacts=(),
                evidence=(task_evidence,),
                repo_dir=repo,
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                record_task_integration(
                    run_dir,
                    task_id="PX-01",
                    integration_commit=head,
                    verification=(f"not-the-tested-head-{head}-suffix",),
                    repo_dir=repo,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_worker_reserving_review_transition_uses_fresh_bound_capacity(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(root)
            record_phase_verification(
                run_dir,
                phase_id="01",
                head=head,
                commands=("suite", "full suite"),
                evidence=(
                    _verification_evidence(
                        root, head, "phase", commands=("suite", "full suite")
                    ),
                ),
            )
            before = (run_dir / "progress.md").read_bytes()
            with pipeline_state.bind_runtime_capacity_provider(
                run_dir, lambda _run, _tracker: 0
            ), self.assertRaises(TransitionError):
                pipeline_state.open_review_gate(
                    run_dir,
                    gate_id="phase-01",
                    base=head,
                    head=head,
                    reviewer_assignments=("reviewer-1",),
                    capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_fixer_reservation_fails_closed_for_missing_zero_or_failed_capacity(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(root)
            helper.prepare_blocked_phase_gate(root, run_dir, head)
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text("# Fix plan\n", encoding="utf-8")

            providers = (
                ("missing", None),
                ("zero", lambda _run, _tracker: 0),
                (
                    "failed",
                    lambda _run, _tracker: (_ for _ in ()).throw(
                        RuntimeError("capacity unavailable")
                    ),
                ),
            )
            for label, provider in providers:
                with self.subTest(label=label):
                    before = (run_dir / "progress.md").read_bytes()
                    context = (
                        nullcontext()
                        if provider is None
                        else pipeline_state.bind_runtime_capacity_provider(run_dir, provider)
                    )
                    with context, self.assertRaises(TransitionError):
                        pipeline_state.start_remediation_round(
                            run_dir, gate_id="phase-01", round_number=1,
                            finding_ids=("F-001",), fix_plan=str(fix_plan),
                            fixer_assignments=("fixer-1",), capacity=3,
                        )
                    self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_rereview_reservation_fails_closed_for_missing_zero_or_failed_capacity(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(root)
            helper.prepare_blocked_phase_gate(root, run_dir, head)
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text("# Fix plan\n", encoding="utf-8")
            start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-001",), fix_plan=str(fix_plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            (root / "fix.txt").write_text("fixed\n", encoding="utf-8")
            helper.git(root, "add", "fix.txt")
            helper.git(root, "commit", "-qm", "fix finding")
            fix_head = helper.git(root, "rev-parse", "HEAD")
            helper.git(root, "branch", "-f", "target", fix_head)
            verification = _remediation_evidence(
                root, fix_head, "phase-01", 1, "capacity",
            )

            providers = (
                ("missing", None),
                ("zero", lambda _run, _tracker: 0),
                (
                    "failed",
                    lambda _run, _tracker: (_ for _ in ()).throw(
                        RuntimeError("capacity unavailable")
                    ),
                ),
            )
            for label, provider in providers:
                with self.subTest(label=label):
                    before = (run_dir / "progress.md").read_bytes()
                    context = (
                        nullcontext()
                        if provider is None
                        else pipeline_state.bind_runtime_capacity_provider(run_dir, provider)
                    )
                    with context, self.assertRaises(TransitionError):
                        pipeline_state.record_remediation_fixes(
                            run_dir, gate_id="phase-01", round_number=1,
                            fix_head=fix_head, commits=(fix_head,),
                            verification=(verification,), capacity=3, repo_dir=root,
                        )
                    self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_semantically_impossible_tracker_states_are_rejected(self):
        valid = parse_tracker((FIXTURES / "valid-v2-progress.md").read_text(encoding="utf-8"))
        completed_source = next(task for task in valid.tasks if task.kind == "source")
        verified_phase = next(phase for phase in valid.phases if phase.state == "[x]")
        accepted_gate = next(gate for gate in valid.gates if gate.state == "accepted")
        cases = {
            "completed source without result": dataclasses.replace(
                valid,
                tasks=tuple(
                    dataclasses.replace(task, result="-") if task is completed_source else task
                    for task in valid.tasks
                ),
            ),
            "verified phase without evidence": dataclasses.replace(
                valid,
                phases=tuple(
                    dataclasses.replace(phase, verification="-") if phase is verified_phase else phase
                    for phase in valid.phases
                ),
            ),
            "accepted gate without proof": dataclasses.replace(
                valid,
                gates=tuple(
                    dataclasses.replace(
                        gate, base="-", head="-", assignments="-", reports="-", verification="-"
                    ) if gate is accepted_gate else gate
                    for gate in valid.gates
                ),
            ),
            "blocked task carrying completion authority": dataclasses.replace(
                valid,
                tasks=tuple(
                    dataclasses.replace(
                        task,
                        state="[?]",
                        checkpoints=(
                            f"baseline:attempt-001@{valid.base_commit},"
                            "blocked:attempt-001@D-900"
                        ),
                        question="D-900",
                    ) if task is completed_source else task
                    for task in valid.tasks
                ),
            ),
            "re-reviewing gate without matching round": dataclasses.replace(
                valid,
                gates=tuple(
                    dataclasses.replace(gate, state="re_reviewing")
                    if gate is accepted_gate else gate
                    for gate in valid.gates
                ),
            ),
            "multiple active remediation rounds": dataclasses.replace(
                valid,
                remediation=(
                    dataclasses.replace(
                        valid.remediation[0], state="fixing", fixers="fixer-a",
                        released_fixers="-", findings="F-001", fix_plan="fix-one.md",
                        commits="-", verification="-", re_review="-",
                    ),
                    dataclasses.replace(
                        valid.remediation[0], round_number=2, state="fixing",
                        fixers="fixer-b", released_fixers="-", findings="F-001",
                        fix_plan="fix-two.md", commits="-", verification="-", re_review="-",
                    ),
                ),
            ),
        }
        canonical = render_tracker(valid)
        for label, tracker in cases.items():
            text = render_tracker(tracker)
            self.assertNotEqual(text, canonical)
            with self.subTest(label=label), self.assertRaises(SchemaError):
                parse_tracker(text)

    def test_round_verification_separates_one_valid_seal_from_typed_evidence(self):
        evidence = "evidence.md#sha256=" + "b" * 64 + "@" + "c" * 40
        seal = "master-initial-seal:" + "a" * 64
        row = pipeline_state.RemediationRecord(
            "master", 1, "re_reviewing", "-", "fixer", "F-001",
            "fix-plan.md", "d" * 40, f"{seal},{evidence}", "-",
        )
        self.assertEqual(pipeline_state._round_verification_items(row), (evidence,))

        for invalid in (
            "master-initial-seal:not-a-digest",
            f"{seal},master-initial-seal:{'e' * 64},{evidence}",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(TransitionError):
                pipeline_state._round_verification_items(
                    dataclasses.replace(row, verification=invalid)
                )

        unknown = dataclasses.replace(
            row, verification=f"{seal},unknown-metadata,{evidence}"
        )
        self.assertEqual(
            pipeline_state._round_verification_items(unknown),
            ("unknown-metadata", evidence),
        )

    def test_blocked_gate_persists_digest_bound_reports_and_finding_origins(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(root)
            evidence = _verification_evidence(
                root, head, "phase", commands=("suite", "full suite")
            )
            record_phase_verification(
                run_dir,
                phase_id="01",
                head=head,
                commands=("suite", "full suite"),
                evidence=(evidence,),
            )
            with pipeline_state.bind_runtime_capacity_provider(
                run_dir, lambda _run, _tracker: 3
            ):
                pipeline_state.open_review_gate(
                    run_dir,
                    gate_id="phase-01",
                    base=head,
                    head=head,
                    reviewer_assignments=("reviewer-1",),
                    capacity=3,
                )
            report = helper.write_report(
                root,
                "review.md",
                gate="phase-01",
                assignment="reviewer-1",
                base=head,
                head=head,
                findings="F-001",
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | phase-01 | Important | Open | - | review.md | - | - |\n",
                encoding="utf-8",
            )
            blocked = evaluate_and_close_review_gate(
                run_dir,
                gate_id="phase-01",
                findings_path=findings,
                report_paths=(report,),
                verification=(evidence,),
                rereview_paths=(),
            )
            gate = next(item for item in blocked.gates if item.id == "phase-01")
            self.assertIn("#sha256=", gate.reports)
            self.assertRegex(gate.findings, r"^F-001@Important@sha256=[0-9a-f]{64}$")

            report.write_text(
                report.read_text(encoding="utf-8").replace(
                    "| findings | F-001 |", "| findings | - |"
                ),
                encoding="utf-8",
            )
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text("# Fix plan\n", encoding="utf-8")
            before = (run_dir / "progress.md").read_bytes()
            with pipeline_state.bind_runtime_capacity_provider(
                run_dir, lambda _run, _tracker: 3
            ), self.assertRaises(TransitionError):
                start_remediation_round(
                    run_dir,
                    gate_id="phase-01",
                    round_number=1,
                    finding_ids=("F-001",),
                    fix_plan=str(fix_plan),
                    fixer_assignments=("fixer-1",),
                    capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_exact_master_bootstrap_seal_is_validated_atomic_and_idempotent(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(
                root, phase_id="04", review_gate="final-only", reason="Final only."
            )
            phase_evidence = _verification_evidence(
                root, head, "seal-phase", subject="phase/04"
            )
            record_phase_verification(
                run_dir, phase_id="04", head=head,
                commands=("suite",), evidence=(phase_evidence,),
            )
            open_review_gate(
                run_dir, gate_id="master", base=head, head=head,
                reviewer_assignments=("reviewer-a", "reviewer-b"), capacity=3,
            )
            finding_ids = tuple(f"MASTER-{number:03d}" for number in range(1, 7))
            report_a = helper.write_report(
                root, "master-a.md", gate="master", assignment="reviewer-a",
                base=head, head=head, findings=",".join(finding_ids[:3]),
            )
            report_b = helper.write_report(
                root, "master-b.md", gate="master", assignment="reviewer-b",
                base=head, head=head, findings=",".join(finding_ids[3:]),
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                + "".join(
                    f"| {finding} | master | Important | Open | - | "
                    f"{'master-a.md' if index < 3 else 'master-b.md'} | - | - |\n"
                    for index, finding in enumerate(finding_ids)
                ),
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="master", findings_path=findings,
                report_paths=(report_a, report_b), verification=(phase_evidence,),
                rereview_paths=(),
            )
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text("# Master fix plan\n", encoding="utf-8")
            started = start_remediation_round(
                run_dir, gate_id="master", round_number=1,
                finding_ids=finding_ids, fix_plan=str(fix_plan),
                fixer_assignments=("master-fixer-controller",), capacity=3,
            )
            gate = next(item for item in started.gates if item.id == "master")
            row = next(
                item for item in started.remediation
                if item.gate == "master" and item.round_number == 1
            )
            unsealed = dataclasses.replace(
                started,
                gates=tuple(
                    dataclasses.replace(
                        item, reports=f"{report_a},{report_b}",
                        findings=",".join(finding_ids),
                    ) if item is gate else item
                    for item in started.gates
                ),
                remediation=tuple(
                    dataclasses.replace(item, verification="-") if item is row else item
                    for item in started.remediation
                ),
            )
            preseal = render_tracker(unsealed).encode("utf-8")
            (run_dir / "progress.md").write_bytes(preseal)
            constants = {
                "_MASTER_ROUND_ONE_SEAL_RUN": unsealed.run_id,
                "_MASTER_ROUND_ONE_SEAL_REVISION": unsealed.revision,
                "_MASTER_ROUND_ONE_SEAL_TRACKER_DIGEST": hashlib.sha256(preseal).hexdigest(),
                "_MASTER_ROUND_ONE_SEAL_FINDINGS": finding_ids,
                "_MASTER_ROUND_ONE_SEAL_REPORT_DIGESTS": tuple(
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (report_a, report_b)
                ),
                "_MASTER_ROUND_ONE_SEAL_FINDINGS_DIGEST": hashlib.sha256(findings.read_bytes()).hexdigest(),
            }
            with mock.patch.multiple(pipeline_state, **constants):
                sealed = pipeline_state.seal_active_master_round_one(run_dir)
                self.assertEqual(sealed.revision, unsealed.revision + 1)
                sealed_gate = next(item for item in sealed.gates if item.id == "master")
                sealed_row = next(
                    item for item in sealed.remediation
                    if item.gate == "master" and item.round_number == 1
                )
                self.assertTrue(all("#sha256=" in item for item in sealed_gate.reports.split(",")))
                self.assertTrue(all("@Important@sha256=" in item for item in sealed_gate.findings.split(",")))
                self.assertIn("master-initial-seal:", sealed_row.verification)
                accepted_bytes = (run_dir / "progress.md").read_bytes()
                replayed = pipeline_state.seal_active_master_round_one(run_dir)
                self.assertEqual(replayed.revision, sealed.revision)
                self.assertEqual((run_dir / "progress.md").read_bytes(), accepted_bytes)

                tampered = preseal + b"\n"
                (run_dir / "progress.md").write_bytes(tampered)
                with self.assertRaises(TransitionError):
                    pipeline_state.seal_active_master_round_one(run_dir)
                self.assertEqual((run_dir / "progress.md").read_bytes(), tampered)


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
            "<!-- pipeline-v2-phase-suite: id=77; commands=[\"phase-suite\"] -->",
            "",
        ]
        for heading, metadata in zip((f"### PS-{i:02d} — Task" for i in range(1, len(tasks) + 1)), tasks):
            task_id = re.search(r"id=([^;]+)", metadata).group(1)
            body.extend((heading, metadata, f"<!-- pipeline-v2-task-suite: id={task_id}; commands=[\"task-suite-{task_id}\"] -->", ""))
        path.write_text("\n".join(body), encoding="utf-8")
        return path

    def task(self, task_id: str, *, deps: str = "none", batch: str = "batch", order: int = 1, scope: str | None = None) -> str:
        scope = scope or f"file:{task_id.lower()}.txt"
        return (
            f"<!-- pipeline-v2-task: id={task_id}; deps={deps}; kind=source; "
            f"batch={batch}; order={order}; write_scope={scope}; outputs=none -->"
        )

    def initialize(self, root: Path, plan: Path, *, worker_limit: int = 3) -> Path:
        if not (root / ".git").exists():
            self.git(root, "init", "-q")
            self.git(root, "config", "user.email", "pipeline@example.invalid")
            self.git(root, "config", "user.name", "Pipeline Test")
            (root / "base.txt").write_text("base\n", encoding="utf-8")
            self.git(root, "add", "base.txt")
            self.git(root, "commit", "-qm", "base")
            self.git(root, "branch", "target")
        base = self.git(root, "rev-parse", "HEAD")
        (root / "master.md").write_text(
            f"# Master plan\n\n{plan}\n", encoding="utf-8",
        )
        decisions = root / "decisions.md"
        decisions.write_text("# Decisions\n", encoding="utf-8")
        run_dir = root / "run"
        initialize_run(
            run_dir,
            run_id="scheduler-test",
            base_commit=base,
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
            task_evidence = _verification_evidence(
                root, commit, "ps-01-task", purpose="task-test",
                run_id="scheduler-test", subject="task/PS-01",
                attempt="attempt-1", commands=("task-suite-PS-01",),
            )
            complete_task(
                run_dir, task_id="PS-01", attempt="attempt-1", phase_plan=plan,
                source_ref="target", commits=(commit,), artifacts=(),
                evidence=(task_evidence,), repo_dir=root,
            )
            integration_evidence = _verification_evidence(
                root, commit, "ps-01-integration", purpose="task-integration",
                run_id="scheduler-test", subject="task/PS-01",
                attempt="N/A", commands=("integration-check",),
            )
            record_task_integration(
                run_dir, task_id="PS-01", integration_commit=commit,
                verification=(integration_evidence,), repo_dir=root,
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
<!-- pipeline-v2-phase-suite: id=88; commands=["phase-suite"] -->

### PR-01 — Source
<!-- pipeline-v2-task: id=PR-01; deps=none; kind=source; batch=source; order=1; write_scope=file:source.txt; outputs=none -->
<!-- pipeline-v2-task-suite: id=PR-01; commands=["task-suite-PR-01"] -->

### PR-02 — Artifact
<!-- pipeline-v2-task: id=PR-02; deps=none; kind=artifact; batch=artifact; order=2; write_scope=tree:evidence; outputs=evidence/artifact.md -->
""",
            encoding="utf-8",
        )
        (root / "master.md").write_text(
            f"# Master\n\n- **Detailed plan:** `{plan}`\n", encoding="utf-8"
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
        evidence: str = "agent-output/test.log",
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
| evidence | {evidence} |
| concerns | - |
| question | {question} |
| blocking_reason | {blocking_reason} |

## Checkpoints
| ID | Status | Evidence |
| --- | --- | --- |
| tested | complete | {evidence} |
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
                    evidence=_verification_evidence(
                        root, commit, "source-result", purpose="task-test",
                        run_id="result-test", subject="task/PR-01",
                        attempt="source-1", commands=("task-suite-PR-01",),
                    ),
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
                    evidence=_artifact_validation_evidence(
                        root, self.git(root, "rev-parse", "target"),
                        run_id="result-test", task_id="PR-02", attempt="artifact-1",
                        outputs=("evidence/artifact.md",),
                    ),
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

    def test_needs_context_result_history_survives_answered_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plan, _ = self.make_run(root)
            start_task(run_dir, task_id="PR-01", owner="worker-a", attempt="attempt-1")
            result_path = self.write_result(
                run_dir,
                "needs-context.md",
                self.result_text(
                    task_id="PR-01", attempt="attempt-1", owner="worker-a",
                    status="NEEDS_CONTEXT", question="D-301",
                ),
            )
            blocked = import_worker_result(
                run_dir, result_path=result_path, phase_plan=plan, repo_dir=root,
            )
            prior_result = next(task for task in blocked.tasks if task.id == "PR-01").result
            (root / "decisions.md").write_text(
                "# Decisions\n\n"
                "## D-301 — Answer\n\n"
                "- **Question:** Which behavior?\n"
                "- **Answer:** Use the explicitly recorded behavior.\n"
                "- **Decision action:** task.resume\n"
                "- **Scope:** PR-01 current blocker.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            resumed = resume_task(
                run_dir, task_id="PR-01", prior_attempt="attempt-1",
                new_owner="worker-a", new_attempt="attempt-2", decision_ref="D-301",
            )
            task = next(task for task in resumed.tasks if task.id == "PR-01")
            self.assertEqual(
                (task.state, task.attempt, task.result),
                ("[~]", "attempt-2", prior_result),
            )

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
- **Decision action:** task.resume
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
                evidence=_verification_evidence(
                    root, commit, "source-replay", purpose="task-test",
                    run_id="result-test", subject="task/PR-01",
                    attempt="attempt-1", commands=("task-suite-PR-01",),
                ),
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


class PhaseGateAndRemediationTest(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(("git", *args), cwd=repo, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def make_run(
        self, root: Path, *, phase_id: str = "01", review_gate: str = "required",
        reason: str = "Phase-specific risk.", worker_limit: int = 3,
    ) -> tuple[Path, Path, str]:
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "pipeline@example.invalid")
        self.git(root, "config", "user.name", "Pipeline Test")
        (root / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(root, "add", "base.txt")
        self.git(root, "commit", "-qm", "base")
        head = self.git(root, "rev-parse", "HEAD")
        self.git(root, "branch", "target")
        plan = root / f"phase-{phase_id}.md"
        plan.write_text(
            f"""# Gate phase

<!-- pipeline-v2-phase: id={phase_id}; deps=none; review_gate={review_gate}; review_reason={reason} -->
<!-- pipeline-v2-phase-suite: id={phase_id}; commands=["suite","full suite"] -->

### PG-01 — Source
<!-- pipeline-v2-task: id=PG-01; deps=none; kind=source; batch=gate; order=1; write_scope=file:source.txt; outputs=none -->
<!-- pipeline-v2-task-suite: id=PG-01; commands=["task-suite"] -->

### PG-02 — Evidence
<!-- pipeline-v2-task: id=PG-02; deps=none; kind=artifact; batch=evidence; order=2; write_scope=tree:evidence; outputs=evidence/report.md -->
""",
            encoding="utf-8",
        )
        (root / "master.md").write_text(f"# Master\n\n{plan}\n", encoding="utf-8")
        decisions = root / "decisions.md"
        decisions.write_text("# Decisions\n", encoding="utf-8")
        findings = root / "findings.md"
        findings.write_text("<!-- pipeline-findings/v2 -->\n| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n", encoding="utf-8")
        run_dir = root / "run"
        initialize_run(
            run_dir, run_id="gate-test", base_commit=head, target_branch="target", worker_limit=worker_limit,
            artifacts={"spec": "spec.md", "master_plan": "master.md", "phase_plans": str(plan), "decisions": str(decisions), "findings": str(findings)},
            approved_existing=(),
        )
        (root / "evidence").mkdir()
        (root / "evidence/report.md").write_text("verified\n", encoding="utf-8")
        artifact_evidence = _artifact_validation_evidence(
            root, head, run_id="gate-test", task_id="PG-02",
            attempt="fixture-artifact-a1", outputs=("evidence/report.md",),
            label=f"gate-artifact-{phase_id}",
        )

        def complete_rows(tracker):
            rows = []
            for task in tracker.tasks:
                if task.kind == "source":
                    rows.append(dataclasses.replace(
                        task, state="[x]", owner="fixture-source", attempt="fixture-source-a1",
                        result="result:fixture-source-a1",
                        checkpoints="started:fixture-source-a1,completed:fixture-source-a1",
                        commits=head, source_ref="target", integration=head,
                        verification=f"reconciled-existing-integration:{head}",
                    ))
                else:
                    rows.append(dataclasses.replace(
                        task, state="[x]", owner="fixture-artifact", attempt="fixture-artifact-a1",
                        result="result:fixture-artifact-a1",
                        checkpoints="started:fixture-artifact-a1,completed:fixture-artifact-a1",
                        artifacts="evidence/report.md", integration="N/A",
                        verification=artifact_evidence,
                    ))
            return dataclasses.replace(tracker, tasks=tuple(rows), phases=tuple(dataclasses.replace(phase, state="[~]") for phase in tracker.phases))

        locked_tracker_update(run_dir, "fixture-complete", complete_rows, timeout_s=1.0)
        return run_dir, plan, head

    def make_changed_master_run(self, root: Path, *, worker_limit: int = 3) -> tuple[Path, str, str, str]:
        run_dir, _, base = self.make_run(
            root, phase_id="04", review_gate="final-only", reason="Final only.",
            worker_limit=worker_limit,
        )
        (root / "source.txt").write_text("implemented\n", encoding="utf-8")
        self.git(root, "add", "source.txt")
        self.git(root, "commit", "-qm", "implement feature")
        implementation = self.git(root, "rev-parse", "HEAD")
        (root / "release.txt").write_text("verified input\n", encoding="utf-8")
        self.git(root, "add", "release.txt")
        self.git(root, "commit", "-qm", "prepare verified integration")
        verified_head = self.git(root, "rev-parse", "HEAD")
        self.git(root, "branch", "-f", "target", verified_head)

        def integrate_source(tracker):
            rows = tuple(
                dataclasses.replace(
                    task,
                    owner="phase-implementer",
                    commits=implementation,
                    source_ref="target",
                    integration=implementation,
                    verification=f"reconciled-existing-integration:{implementation}",
                )
                if task.kind == "source"
                else task
                for task in tracker.tasks
            )
            return dataclasses.replace(tracker, tasks=rows)

        locked_tracker_update(
            run_dir, "fixture-source-change", integrate_source, timeout_s=1.0
        )
        record_phase_verification(
            run_dir,
            phase_id="04",
            head=verified_head,
            commands=("full suite",),
            evidence=(_verification_evidence(root, verified_head, subject="phase/04"),),
        )
        return run_dir, base, implementation, verified_head

    def advance_target_after_verification(self, root: Path) -> str:
        (root / "post-verification.txt").write_text(
            "unreviewed target change\n", encoding="utf-8"
        )
        self.git(root, "add", "post-verification.txt")
        self.git(root, "commit", "-qm", "advance target after verification")
        target_tip = self.git(root, "rev-parse", "HEAD")
        self.git(root, "branch", "-f", "target", target_tip)
        return target_tip

    def write_report(
        self,
        root: Path,
        name: str,
        *,
        gate: str,
        assignment: str,
        base: str,
        head: str,
        findings: str = "-",
        outcomes: dict[str, str] | None = None,
    ) -> Path:
        outcome_values = (
            outcomes
            if outcomes is not None
            else {finding: "Open" for finding in findings.split(",") if finding != "-"}
        )
        path = root / name
        path.write_text(
            f"""<!-- pipeline-review-report/v2 -->
| Field | Value |
| --- | --- |
| gate | {gate} |
| assignment | {assignment} |
| base | {base} |
| head | {head} |
| findings | {findings} |
| outcomes | {json.dumps(outcome_values, sort_keys=True, separators=(",", ":"))} |
""",
            encoding="utf-8",
        )
        return path

    def prepare_blocked_phase_gate(
        self, root: Path, run_dir: Path, head: str, *, finding_id: str = "F-001"
    ) -> None:
        """Build a truthful reviewed blocker before tests add a decision question."""
        evidence = _verification_evidence(root, head)
        record_phase_verification(
            run_dir, phase_id="01", head=head,
            commands=("suite",), evidence=(evidence,),
        )
        open_review_gate(
            run_dir, gate_id="phase-01", base=head, head=head,
            reviewer_assignments=("reviewer-1",), capacity=3,
        )
        report = self.write_report(
            root, "review-question.md", gate="phase-01", assignment="reviewer-1",
            base=head, head=head, findings=finding_id,
        )
        findings = root / "findings.md"
        findings.write_text(
            "<!-- pipeline-findings/v2 -->\n"
            "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            f"| {finding_id} | phase-01 | Important | Open | - | review-question.md | - | - |\n",
            encoding="utf-8",
        )
        evaluate_and_close_review_gate(
            run_dir, gate_id="phase-01", findings_path=findings,
            report_paths=(report,), verification=(evidence,), rereview_paths=(),
        )

    def test_mixed_phase_verification_uses_its_own_required_reason(self):
        for phase_id, reason in (("01", "Phase one risk."), ("02", "Different phase two risk.")):
            with self.subTest(phase=phase_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir, _, head = self.make_run(root, phase_id=phase_id, reason=reason)
                verified = record_phase_verification(
                    run_dir, phase_id=phase_id, head=head, commands=("full suite",),
                    evidence=(_verification_evidence(root, head, subject=f"phase/{phase_id}"),),
                )
                phase = next(item for item in verified.phases if item.id == phase_id)
                self.assertEqual((phase.state, phase.review_reason), ("[x]", reason))
                opened = open_review_gate(run_dir, gate_id=f"phase-{phase_id}", base=head, head=head, reviewer_assignments=("reviewer-1",), capacity=3)
                self.assertEqual(next(gate.state for gate in opened.gates if gate.id == f"phase-{phase_id}"), "in_progress")

    def test_mismatched_reason_and_final_only_phase_cannot_open_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root, reason="Approved reason.")
            locked_tracker_update(
                run_dir, "corrupt-reason",
                lambda tracker: dataclasses.replace(tracker, phases=tuple(dataclasses.replace(phase, review_reason="Different reason.") for phase in tracker.phases)),
                timeout_s=1.0,
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                record_phase_verification(run_dir, phase_id="01", head=head, commands=("suite",), evidence=(_verification_evidence(root, head),))
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)


        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root, phase_id="03", review_gate="final-only", reason="Final only.")
            record_phase_verification(
                run_dir, phase_id="03", head=head, commands=("suite",),
                evidence=(_verification_evidence(root, head, subject="phase/03"),),
            )
            with self.assertRaises(TransitionError):
                open_review_gate(run_dir, gate_id="phase-03", base=head, head=head, reviewer_assignments=("reviewer-1",), capacity=3)

    def test_required_phase_gate_stays_bound_to_the_designated_target_tip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            target_tip = self.advance_target_after_verification(root)
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                record_phase_verification(
                    run_dir, phase_id="01", head=head, commands=("suite",),
                    evidence=(_verification_evidence(root, head),),
                )
            self.assertNotEqual(target_tip, head)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_source_changing_phase_review_uses_the_approved_phase_boundary(self):
        """A caller-selected verified-head..verified-head edge must not omit phase work."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, phase_base = self.make_run(root)
            (root / "source.txt").write_text("phase implementation\n", encoding="utf-8")
            self.git(root, "add", "source.txt")
            self.git(root, "commit", "-qm", "phase implementation")
            implementation = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", implementation)

            def record_source_change(tracker):
                return dataclasses.replace(
                    tracker,
                    tasks=tuple(
                        dataclasses.replace(
                            task,
                            commits=implementation,
                            integration=implementation,
                            verification=f"reconciled-existing-integration:{implementation}",
                        ) if task.kind == "source" else task
                        for task in tracker.tasks
                    ),
                )

            locked_tracker_update(
                run_dir, "fixture-phase-source-change", record_source_change,
                timeout_s=1.0,
            )
            evidence = _verification_evidence(root, implementation)
            record_phase_verification(
                run_dir, phase_id="01", head=implementation,
                commands=("suite",), evidence=(evidence,),
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                open_review_gate(
                    run_dir, gate_id="phase-01", base=implementation,
                    head=implementation, reviewer_assignments=("reviewer-1",),
                    capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            opened = open_review_gate(
                run_dir, gate_id="phase-01", base=phase_base,
                head=implementation, reviewer_assignments=("reviewer-1",),
                capacity=3,
            )
            self.assertEqual(
                next(gate.base for gate in opened.gates if gate.id == "phase-01"),
                phase_base,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            evidence = _verification_evidence(root, head)
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(evidence,),
            )
            self.advance_target_after_verification(root)
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                open_review_gate(
                    run_dir, gate_id="phase-01", base=head, head=head,
                    reviewer_assignments=("reviewer-1",), capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            evidence = _verification_evidence(root, head)
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(evidence,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=head, head=head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            report = self.write_report(
                root, "stale-phase-report.md", gate="phase-01",
                assignment="reviewer-1", base=head, head=head,
            )
            self.advance_target_after_verification(root)
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=root / "findings.md",
                    report_paths=(report,), verification=(evidence,), rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_master_gate_requires_two_reviewers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root, phase_id="03", review_gate="final-only", reason="Final only.")
            record_phase_verification(
                run_dir, phase_id="03", head=head, commands=("suite",),
                evidence=(_verification_evidence(root, head, subject="phase/03"),),
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                open_review_gate(run_dir, gate_id="master", base=head, head=head, reviewer_assignments=("reviewer-a",), capacity=3)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            opened = open_review_gate(run_dir, gate_id="master", base=head, head=head, reviewer_assignments=("reviewer-a", "reviewer-b"), capacity=3)
            self.assertEqual(next(gate.assignments for gate in opened.gates if gate.id == "master"), "reviewer-a,reviewer-b")
            report_a = self.write_report(
                root, "master-a.md", gate="master", assignment="reviewer-a",
                base=head, head=head,
            )
            report_b = self.write_report(
                root, "master-b.md", gate="master", assignment="reviewer-b",
                base=head, head=head,
            )
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="master", findings_path=root / "findings.md",
                report_paths=(report_a, report_b),
                verification=(_verification_evidence(root, head, subject="phase/03"),),
                rereview_paths=(),
            )
            self.assertEqual(next(gate.state for gate in accepted.gates if gate.id == "master"), "accepted")

    def test_master_review_pair_can_be_queued_under_worker_limit_one(self):
        """The required reviewer set is not a claim that both run concurrently."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, run_base, _, head = self.make_changed_master_run(root, worker_limit=1)
            opened = open_review_gate(
                run_dir, gate_id="master", base=run_base, head=head,
                reviewer_assignments=("reviewer-a", "reviewer-b"), capacity=3,
            )
            self.assertEqual(
                next(gate.assignments for gate in opened.gates if gate.id == "master"),
                "reviewer-a,reviewer-b",
            )
            reports = tuple(
                self.write_report(
                    root, f"queued-{suffix}.md", gate="master",
                    assignment=f"reviewer-{suffix}", base=run_base, head=head,
                )
                for suffix in ("a", "b")
            )
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="master", findings_path=root / "findings.md",
                report_paths=reports,
                verification=(_verification_evidence(root, head, subject="phase/04"),),
                rereview_paths=(),
            )
            self.assertEqual(
                next(gate.state for gate in accepted.gates if gate.id == "master"),
                "accepted",
            )

    def test_final_verification_is_persisted_and_second_resume_derives_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, run_base, _, head = self.make_changed_master_run(root)
            open_review_gate(
                run_dir, gate_id="master", base=run_base, head=head,
                reviewer_assignments=("reviewer-a", "reviewer-b"), capacity=3,
            )
            reports = tuple(
                self.write_report(
                    root, f"terminal-{suffix}.md", gate="master",
                    assignment=f"reviewer-{suffix}", base=run_base, head=head,
                )
                for suffix in ("a", "b")
            )
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="master", findings_path=root / "findings.md",
                report_paths=reports,
                verification=(_verification_evidence(root, head, subject="phase/04"),),
                rereview_paths=(),
            )
            self.assertEqual(dict(accepted.current_fields)["next_action"], "final-verification")
            final_evidence = _verification_evidence(
                root, head, "final", purpose="final", run_id="gate-test",
                subject="project", commands=("canonical-final",), inputs="clean-target-snapshot",
            )
            completed = pipeline_state.record_final_verification(
                run_dir, head=head, commands=("canonical-final",),
                evidence=(final_evidence,), repo_dir=root,
            )
            self.assertEqual(dict(completed.current_fields)["next_action"], "complete")
            revision = completed.revision
            replay = pipeline_state.record_final_verification(
                run_dir, head=head, commands=("canonical-final",),
                evidence=(final_evidence,), repo_dir=root,
            )
            self.assertEqual(replay.revision, revision)
            self.assertEqual(inspect_run(run_dir)["derived_next_action"], "complete")

    def test_master_rereview_pair_can_be_queued_under_worker_limit_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, run_base, _, reviewed_head = self.make_changed_master_run(root, worker_limit=1)
            open_review_gate(
                run_dir, gate_id="master", base=run_base, head=reviewed_head,
                reviewer_assignments=("reviewer-a", "reviewer-b"), capacity=3,
            )
            reports = tuple(
                self.write_report(
                    root, f"initial-{suffix}.md", gate="master",
                    assignment=f"reviewer-{suffix}", base=run_base, head=reviewed_head,
                    findings="F-001",
                )
                for suffix in ("a", "b")
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | master | Important | Open | - | initial-a.md,initial-b.md | - | - |\n",
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="master", findings_path=findings,
                report_paths=reports,
                verification=(_verification_evidence(root, reviewed_head, subject="phase/04"),),
                rereview_paths=(),
            )
            fix_plan = root / "master-fix.md"
            fix_plan.write_text(
                "# Fix\n\n<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-001 | source | none |\n",
                encoding="utf-8",
            )
            start_remediation_round(
                run_dir, gate_id="master", round_number=1,
                finding_ids=("F-001",), fix_plan=str(fix_plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            (root / "master-fix.txt").write_text("fixed\n", encoding="utf-8")
            self.git(root, "add", "master-fix.txt")
            self.git(root, "commit", "-qm", "master fix")
            fix_head = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", fix_head)
            verification = _remediation_evidence(root, fix_head, "master", 1, "queued-rereview")
            queued = record_remediation_fixes(
                run_dir, gate_id="master", round_number=1, fix_head=fix_head,
                commits=(fix_head,), verification=(verification,), capacity=3,
                repo_dir=root,
            )
            self.assertEqual(
                next(gate.state for gate in queued.gates if gate.id == "master"),
                "re_reviewing",
            )

    def test_new_reports_require_complete_explicit_finding_outcomes(self):
        invalid_outcomes = (
            ("missing", {}),
            ("extra", {"F-001": "Open", "F-002": "Open"}),
            ("invalid", {"F-001": "Maybe"}),
        )
        for label, outcomes in invalid_outcomes:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir, _, head = self.make_run(root)
                evidence = _verification_evidence(root, head)
                record_phase_verification(
                    run_dir, phase_id="01", head=head,
                    commands=("suite",), evidence=(evidence,),
                )
                open_review_gate(
                    run_dir, gate_id="phase-01", base=head, head=head,
                    reviewer_assignments=("reviewer-1",), capacity=3,
                )
                report = self.write_report(
                    root, f"review-{label}.md", gate="phase-01",
                    assignment="reviewer-1", base=head, head=head,
                    findings="F-001", outcomes=outcomes,
                )
                findings = root / "findings.md"
                findings.write_text(
                    "<!-- pipeline-findings/v2 -->\n"
                    "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                    f"| F-001 | phase-01 | Important | Open | - | {report} | - | - |\n",
                    encoding="utf-8",
                )
                before = (run_dir / "progress.md").read_bytes()
                with self.assertRaises(TransitionError):
                    evaluate_and_close_review_gate(
                        run_dir, gate_id="phase-01", findings_path=findings,
                        report_paths=(report,), verification=(evidence,), rereview_paths=(),
                    )
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            evidence = _verification_evidence(root, head)
            record_phase_verification(
                run_dir, phase_id="01", head=head,
                commands=("suite",), evidence=(evidence,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=head, head=head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            legacy = root / "legacy-unsealed.md"
            legacy.write_text(
                "<!-- pipeline-review-report/v2 -->\n"
                "| Field | Value |\n| --- | --- |\n"
                f"| gate | phase-01 |\n| assignment | reviewer-1 |\n"
                f"| base | {head} |\n| head | {head} |\n| findings | - |\n",
                encoding="utf-8",
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=root / "findings.md",
                    report_paths=(legacy,), verification=(evidence,), rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_review_outcomes_reject_duplicate_json_keys_before_mapping(self):
        """Last-key-wins JSON parsing must not erase an earlier reviewer outcome."""
        self.assertEqual(
            pipeline_state._review_outcomes(
                {"outcomes": '{"F-001":"Open","F-002":"Resolved"}'}
            ),
            {"F-001": "Open", "F-002": "Resolved"},
        )
        for raw in (
            '{"F-001":"Open","F-001":"Resolved"}',
            '{"F-001":"Open","F-001":"Open"}',
        ):
            with self.subTest(raw=raw), self.assertRaises(TransitionError):
                pipeline_state._review_outcomes({"outcomes": raw})

    def test_review_report_accepts_one_terminal_block_after_narrative_only(self):
        block = (
            "<!-- pipeline-review-report/v2 -->\n"
            "| Field | Value |\n"
            "| --- | --- |\n"
            "| gate | master |\n"
            "| assignment | reviewer-a |\n"
            f"| base | {'a' * 40} |\n"
            f"| head | {'b' * 40} |\n"
            "| findings | F-001 |\n"
            '| outcomes | {"F-001":"Open"} |\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            narrative = root / "narrative.md"
            narrative.write_text(
                "# Review\n\nTechnical analysis remains durable here.\n\n" + block,
                encoding="utf-8",
            )
            parsed = pipeline_state._parse_review_report(narrative)
            self.assertEqual(parsed["findings"], "F-001")

            invalid = {
                "duplicate": block + "\n" + block,
                "nonterminal": block + "Trailing technical text.\n",
                "missing": "# Review\n\nNo terminal machine block.\n",
            }
            for label, text in invalid.items():
                with self.subTest(label=label):
                    path = root / f"{label}.md"
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises(TransitionError):
                        pipeline_state._parse_review_report(path)

    def test_conflicting_reviewer_outcomes_cannot_close_master_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, run_base, _, reviewed_head = self.make_changed_master_run(root)
            open_review_gate(
                run_dir, gate_id="master", base=run_base, head=reviewed_head,
                reviewer_assignments=("reviewer-a", "reviewer-b"), capacity=3,
            )
            report_a = self.write_report(
                root, "master-a.md", gate="master", assignment="reviewer-a",
                base=run_base, head=reviewed_head, findings="F-001",
                outcomes={"F-001": "Open"},
            )
            report_b = self.write_report(
                root, "master-b.md", gate="master", assignment="reviewer-b",
                base=run_base, head=reviewed_head, findings="F-001",
                outcomes={"F-001": "Resolved"},
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | master | Important | Open | - | master-a.md,master-b.md | - | - |\n",
                encoding="utf-8",
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="master", findings_path=findings,
                    report_paths=(report_a, report_b),
                    verification=(_verification_evidence(
                        root, reviewed_head, subject="phase/04",
                    ),),
                    rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_master_gate_requires_run_base_and_last_verified_phase_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, run_base, implementation, verified_head = self.make_changed_master_run(root)
            invalid_edges = (
                ("empty-after-change", verified_head, verified_head),
                ("later-than-run-base", implementation, verified_head),
                ("stale-head", run_base, implementation),
            )
            for label, base, head in invalid_edges:
                with self.subTest(label=label):
                    before = (run_dir / "progress.md").read_bytes()
                    with self.assertRaises(TransitionError):
                        open_review_gate(
                            run_dir,
                            gate_id="master",
                            base=base,
                            head=head,
                            reviewer_assignments=("reviewer-a", "reviewer-b"),
                            capacity=3,
                        )
                    self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            opened = open_review_gate(
                run_dir,
                gate_id="master",
                base=run_base,
                head=verified_head,
                reviewer_assignments=("reviewer-a", "reviewer-b"),
                capacity=3,
            )
            gate = next(item for item in opened.gates if item.id == "master")
            self.assertEqual((gate.base, gate.head), (run_base, verified_head))

    def test_master_gate_rejects_post_verification_target_commit_on_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, run_base, _, verified_head = self.make_changed_master_run(root)
            target_tip = self.advance_target_after_verification(root)
            self.assertNotEqual(target_tip, verified_head)
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                open_review_gate(
                    run_dir,
                    gate_id="master",
                    base=run_base,
                    head=verified_head,
                    reviewer_assignments=("reviewer-a", "reviewer-b"),
                    capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_master_gate_rejects_target_advance_before_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, run_base, _, verified_head = self.make_changed_master_run(root)
            open_review_gate(
                run_dir,
                gate_id="master",
                base=run_base,
                head=verified_head,
                reviewer_assignments=("reviewer-a", "reviewer-b"),
                capacity=3,
            )
            report_a = self.write_report(
                root,
                "master-a.md",
                gate="master",
                assignment="reviewer-a",
                base=run_base,
                head=verified_head,
            )
            report_b = self.write_report(
                root,
                "master-b.md",
                gate="master",
                assignment="reviewer-b",
                base=run_base,
                head=verified_head,
            )
            target_tip = self.advance_target_after_verification(root)
            self.assertNotEqual(target_tip, verified_head)
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir,
                    gate_id="master",
                    findings_path=root / "findings.md",
                    report_paths=(report_a, report_b),
                    verification=(_verification_evidence(root, verified_head, subject="phase/04"),),
                    rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_master_reviewers_cannot_be_persisted_task_implementation_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, run_base, _, verified_head = self.make_changed_master_run(root)
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                open_review_gate(
                    run_dir,
                    gate_id="master",
                    base=run_base,
                    head=verified_head,
                    reviewer_assignments=("phase-implementer", "reviewer-b"),
                    capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_worker_publication_contract_reserves_state_import_for_controller(self):
        skill = (REPOSITORY / "plugins/superb/skills/pipeline/SKILL.md").read_text(
            encoding="utf-8"
        )
        persistence = (
            REPOSITORY / "plugins/superb/skills/pipeline/references/persistence.md"
        ).read_text(encoding="utf-8")
        review = (
            REPOSITORY / "plugins/superb/skills/pipeline/references/review.md"
        ).read_text(encoding="utf-8")

        for instructions in (skill, persistence):
            normalized = " ".join(instructions.split())
            self.assertIn(
                "A worker may invoke only `publish_worker_result` for its own assigned immutable result.",
                normalized,
            )
            self.assertIn(
                "Only the controller performs tracker transitions and result import.",
                normalized,
            )
        self.assertIn("immutable tracker `base_commit`", review)
        self.assertIn("last approved phase's recorded verified integrated HEAD", review)
        self.assertIn("persisted task implementation owner", review)

    def test_gate_acceptance_requires_matching_reports_verification_and_no_blockers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            record_phase_verification(run_dir, phase_id="01", head=head, commands=("suite",), evidence=(_verification_evidence(root, head),))
            open_review_gate(run_dir, gate_id="phase-01", base=head, head=head, reviewer_assignments=("reviewer-1",), capacity=3)
            report = self.write_report(root, "review.md", gate="phase-01", assignment="reviewer-1", base=head, head=head)
            findings = root / "findings.md"
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(run_dir, gate_id="phase-01", findings_path=findings, report_paths=(report,), verification=(), rereview_paths=())
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            wrong_report = self.write_report(root, "wrong.md", gate="phase-01", assignment="reviewer-1", base=head, head="f" * 40)
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(run_dir, gate_id="phase-01", findings_path=findings, report_paths=(wrong_report,), verification=(_verification_evidence(root, head),), rereview_paths=())
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            accepted = evaluate_and_close_review_gate(run_dir, gate_id="phase-01", findings_path=findings, report_paths=(report,), verification=(_verification_evidence(root, head),), rereview_paths=())
            self.assertEqual(next(gate.state for gate in accepted.gates if gate.id == "phase-01"), "accepted")
            accepted_bytes = (run_dir / "progress.md").read_bytes()
            report.write_text(report.read_text(encoding="utf-8").replace("| findings | - |", "| findings | F-ALTERED |"), encoding="utf-8")
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=findings,
                    report_paths=(report,), verification=(_verification_evidence(root, head),),
                    rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), accepted_bytes)

    def test_gate_rejects_alternate_ledger_and_bare_resolved_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            record_phase_verification(run_dir, phase_id="01", head=head, commands=("suite",), evidence=(_verification_evidence(root, head),))
            open_review_gate(run_dir, gate_id="phase-01", base=head, head=head, reviewer_assignments=("reviewer-1",), capacity=3)
            report = self.write_report(root, "review.md", gate="phase-01", assignment="reviewer-1", base=head, head=head, findings="F-001")
            alternate = root / "alternate-findings.md"
            alternate.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | phase-01 | Critical | Resolved | - | - | - | - |\n",
                encoding="utf-8",
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=alternate,
                    report_paths=(report,), verification=(_verification_evidence(root, head),), rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            authoritative = root / "findings.md"
            authoritative.write_bytes(alternate.read_bytes())
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=authoritative,
                    report_paths=(report,), verification=(_verification_evidence(root, head),), rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            authoritative.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | phase-01 | Critical | Resolved | Rejected | trust-me | - | - |\n",
                encoding="utf-8",
            )
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=authoritative,
                    report_paths=(report,), verification=(_verification_evidence(root, head),), rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            prefix_collision = root / "prefix-collision.md"
            prefix_collision.write_text(
                "Finding: F-0010\nRationale: this is a different finding.\n",
                encoding="utf-8",
            )
            authoritative.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-001 | phase-01 | Critical | Resolved | Rejected | {prefix_collision} | - | - |\n",
                encoding="utf-8",
            )
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=authoritative,
                    report_paths=(report,), verification=(_verification_evidence(root, head),), rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_evidence_backed_rejection_can_close_a_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            evidence = _verification_evidence(root, head)
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",), evidence=(evidence,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=head, head=head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            report = self.write_report(
                root, "review.md", gate="phase-01", assignment="reviewer-1",
                base=head, head=head, findings="F-001",
            )
            rejection_evidence = root / "rejection-evidence.md"
            rejection_evidence.write_text(
                "Finding: F-001\nRationale: the report contradicts the approved fixture behavior.\n",
                encoding="utf-8",
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-001 | phase-01 | Critical | Resolved | Rejected | {rejection_evidence} | - | - |\n",
                encoding="utf-8",
            )
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(report,), verification=(evidence,), rereview_paths=(),
            )
            self.assertEqual(next(gate.state for gate in accepted.gates if gate.id == "phase-01"), "accepted")

    def test_minor_deferral_requires_digest_bound_impact_reason_and_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            verification = _verification_evidence(root, head)
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(verification,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=head, head=head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            report = self.write_report(
                root, "minor-review.md", gate="phase-01", assignment="reviewer-1",
                base=head, head=head, findings="F-MINOR",
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-MINOR | phase-01 | Minor | Resolved | Deferred | arbitrary-text | - | - |\n",
                encoding="utf-8",
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=findings,
                    report_paths=(report,), verification=(verification,), rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            (root / "decisions.md").write_text(
                "# Decisions\n\n## D-200 — Defer optional cleanup\n\n"
                "- **Question:** Should F-MINOR be fixed in this scope?\n"
                "- **Answer:** Defer F-MINOR; the documented impact is accepted.\n"
                "- **Decision action:** review.resolve-question\n"
                "- **Scope:** phase-01 finding F-MINOR only.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            disposition = root / "minor-disposition.md"
            disposition.write_text(
                "Finding: F-MINOR\n"
                "Impact: Optional readability cleanup remains.\n"
                "Reason: It does not violate an approved requirement.\n"
                "Authority: D-200\n",
                encoding="utf-8",
            )
            identity = pipeline_state._digest_bound_reference(run_dir, disposition)
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-MINOR | phase-01 | Minor | Resolved | Deferred | {identity} | - | - |\n",
                encoding="utf-8",
            )
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(report,), verification=(verification,), rereview_paths=(),
            )
            self.assertEqual(
                next(gate.state for gate in accepted.gates if gate.id == "phase-01"),
                "accepted",
            )

    def test_blockers_rounds_and_rereview_requirements_prevent_false_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            record_phase_verification(run_dir, phase_id="01", head=head, commands=("suite",), evidence=(_verification_evidence(root, head),))
            open_review_gate(run_dir, gate_id="phase-01", base=head, head=head, reviewer_assignments=("reviewer-1",), capacity=3)
            report = self.write_report(root, "review.md", gate="phase-01", assignment="reviewer-1", base=head, head=head, findings="F-001")
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| F-001 | phase-01 | Important | Open | - | review.md | - | - |\n",
                encoding="utf-8",
            )
            blocked = evaluate_and_close_review_gate(run_dir, gate_id="phase-01", findings_path=findings, report_paths=(report,), verification=(_verification_evidence(root, head),), rereview_paths=())
            self.assertEqual(next(gate.state for gate in blocked.gates if gate.id == "phase-01"), "blocked")
            pending = next(row for row in blocked.remediation if row.gate == "phase-01" and row.round_number == 1)
            self.assertEqual(pending.state, "pending")
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text("# Fix plan\n", encoding="utf-8")
            round_one = start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1, finding_ids=("F-001",),
                fix_plan=str(fix_plan), fixer_assignments=("fixer-1",), capacity=3,
            )
            row = next(row for row in round_one.remediation if row.gate == "phase-01" and row.round_number == 1)
            self.assertEqual((row.state, row.findings), ("fixing", "F-001"))
            (root / "attempt.txt").write_text("attempted fix\n", encoding="utf-8")
            self.git(root, "add", "attempt.txt")
            self.git(root, "commit", "-qm", "attempt review fix")
            fix_head = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", fix_head)
            record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=1, fix_head=fix_head,
                commits=(fix_head,), verification=(_remediation_evidence(root, fix_head, "phase-01", 1, "fix"),),
                capacity=3, repo_dir=root,
            )
            rereview = self.write_report(root, "rereview.md", gate="phase-01", assignment="reviewer-1", base=head, head=fix_head, findings="F-001")
            stopped = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings, report_paths=(report,),
                verification=(_remediation_evidence(root, fix_head, "phase-01", 1, "fix"),), rereview_paths=(rereview,),
            )
            stopped_gate = next(gate for gate in stopped.gates if gate.id == "phase-01")
            stopped_round = next(row for row in stopped.remediation if row.gate == "phase-01" and row.round_number == 1)
            self.assertEqual((stopped_gate.state, stopped_gate.questions, stopped_round.state), ("blocked", "remediation-no-progress-round-1", "complete"))
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                start_remediation_round(
                    run_dir, gate_id="phase-01", round_number=2, finding_ids=("F-001",),
                    fix_plan=str(fix_plan), fixer_assignments=("fixer-1",), capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            with self.assertRaises(TransitionError):
                start_remediation_round(
                    run_dir, gate_id="phase-01", round_number=4, finding_ids=("F-001",),
                    fix_plan=str(fix_plan), fixer_assignments=("fixer-1",), capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_fixed_blocker_requires_fix_release_and_matching_clean_rereview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, reviewed_head = self.make_run(root)
            record_phase_verification(
                run_dir, phase_id="01", head=reviewed_head,
                commands=("suite",), evidence=(_verification_evidence(root, reviewed_head),),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=reviewed_head, head=reviewed_head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            initial = self.write_report(
                root, "review.md", gate="phase-01", assignment="reviewer-1",
                base=reviewed_head, head=reviewed_head, findings="F-001",
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | phase-01 | Important | Open | - | review.md | - | - |\n",
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(_verification_evidence(root, reviewed_head),), rereview_paths=(),
            )
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text("# Fix plan\n", encoding="utf-8")
            started = start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1, finding_ids=("F-001",),
                fix_plan=str(fix_plan), fixer_assignments=("fixer-1",), capacity=3,
            )
            self.assertEqual(pipeline_state._active_worker_ids(started), {"fixer-1"})
            (root / "fix.txt").write_text("fixed\n", encoding="utf-8")
            self.git(root, "add", "fix.txt")
            self.git(root, "commit", "-qm", "fix finding")
            fix_head = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", fix_head)
            released = record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=1, fix_head=fix_head,
                commits=(fix_head,), verification=(_remediation_evidence(root, fix_head, "phase-01", 1, "fix"),),
                capacity=3, repo_dir=root,
            )
            round_row = next(row for row in released.remediation if row.gate == "phase-01" and row.round_number == 1)
            self.assertEqual((round_row.state, round_row.fixers, round_row.released_fixers), ("re_reviewing", "-", "fixer-1"))
            self.assertEqual(pipeline_state._active_worker_ids(released), {"reviewer-1"})
            rereview = self.write_report(
                root, "rereview.md", gate="phase-01", assignment="reviewer-1",
                base=reviewed_head, head=fix_head, findings="F-001",
                outcomes={"F-001": "Resolved"},
            )
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-001 | phase-01 | Important | Resolved | Fixed | fix-suite:{fix_head} | {fix_head} | {rereview} |\n",
                encoding="utf-8",
            )
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(_remediation_evidence(root, fix_head, "phase-01", 1, "fix"),),
                rereview_paths=(rereview,),
            )
            self.assertEqual(next(gate.state for gate in accepted.gates if gate.id == "phase-01"), "accepted")
            self.assertEqual(pipeline_state._active_worker_ids(accepted), set())

    def test_artifact_only_fixed_blocker_uses_immutable_remedy_without_fabricated_commit(self):
        """Dropping artifact proof validation would accept an unapproved no-commit fix."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, reviewed_head = self.make_run(root)
            phase_evidence = _verification_evidence(root, reviewed_head)
            record_phase_verification(
                run_dir, phase_id="01", head=reviewed_head,
                commands=("suite",), evidence=(phase_evidence,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=reviewed_head, head=reviewed_head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            finding_ids = "F-SOURCE,F-ARTIFACT"
            initial = self.write_report(
                root, "review.md", gate="phase-01", assignment="reviewer-1",
                base=reviewed_head, head=reviewed_head, findings=finding_ids,
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-SOURCE | phase-01 | Important | Open | - | review.md | - | - |\n"
                "| F-ARTIFACT | phase-01 | Important | Open | - | review.md | - | - |\n",
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(phase_evidence,), rereview_paths=(),
            )
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text(
                "# Approved mixed source/artifact fix plan\n\n"
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n"
                "| --- | --- | --- |\n"
                "| F-SOURCE | source | none |\n"
                '| F-ARTIFACT | artifact | ["agent-output/rebuilt-acceptance.md"] |\n',
                encoding="utf-8",
            )
            started = start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-SOURCE", "F-ARTIFACT"), fix_plan=str(fix_plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            round_row = next(row for row in started.remediation if row.gate == "phase-01")
            (root / "source-fix.txt").write_text("source fix\n", encoding="utf-8")
            self.git(root, "add", "source-fix.txt")
            self.git(root, "commit", "-qm", "source remediation")
            fix_head = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", fix_head)
            remediation_evidence = _remediation_evidence(
                root, fix_head, "phase-01", 1, "mixed-remediation"
            )
            record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=1, fix_head=fix_head,
                commits=(fix_head,), verification=(remediation_evidence,),
                capacity=3, repo_dir=root,
            )
            rereview = self.write_report(
                root, "rereview.md", gate="phase-01", assignment="reviewer-1",
                base=reviewed_head, head=fix_head, findings=finding_ids,
                outcomes={"F-SOURCE": "Resolved", "F-ARTIFACT": "Resolved"},
            )
            artifact = root / "agent-output/rebuilt-acceptance.md"
            artifact.parent.mkdir()
            artifact.write_text("replacement acceptance evidence\n", encoding="utf-8")
            artifact_identity = pipeline_state._digest_bound_reference(run_dir, artifact)
            proof = root / "artifact-remedy.md"
            proof.write_text(
                "<!-- pipeline-artifact-remediation/v2 -->\n"
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| finding | F-ARTIFACT |\n"
                "| gate | phase-01 |\n"
                "| round | 1 |\n"
                f"| fix_plan | {round_row.fix_plan} |\n"
                f"| artifacts | {json.dumps([artifact_identity], separators=(',', ':'))} |\n"
                f"| verification | {remediation_evidence} |\n",
                encoding="utf-8",
            )
            proof_identity = pipeline_state._digest_bound_reference(run_dir, proof)
            rogue = root / "agent-output/rogue.md"
            rogue.write_text("not an approved output\n", encoding="utf-8")
            rogue_identity = pipeline_state._digest_bound_reference(run_dir, rogue)
            rogue_proof = root / "rogue-artifact-remedy.md"
            rogue_proof.write_text(
                proof.read_text(encoding="utf-8").replace(artifact_identity, rogue_identity),
                encoding="utf-8",
            )
            rogue_proof_identity = pipeline_state._digest_bound_reference(run_dir, rogue_proof)

            def write_resolved(
                *, source_commit: str, artifact_evidence: str,
                artifact_rereview: Path = rereview,
            ) -> None:
                findings.write_text(
                    "<!-- pipeline-findings/v2 -->\n"
                    "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                    f"| F-SOURCE | phase-01 | Important | Resolved | Fixed | {remediation_evidence} | {source_commit} | {rereview} |\n"
                    f"| F-ARTIFACT | phase-01 | Important | Resolved | Fixed | {artifact_evidence} | - | {artifact_rereview} |\n",
                    encoding="utf-8",
                )

            write_resolved(source_commit=fix_head, artifact_evidence=rogue_proof_identity)
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=findings,
                    report_paths=(initial,), verification=(remediation_evidence,),
                    rereview_paths=(rereview,),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            write_resolved(source_commit=fix_head, artifact_evidence=proof_identity)
            artifact.write_text("mutated evidence\n", encoding="utf-8")
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=findings,
                    report_paths=(initial,), verification=(remediation_evidence,),
                    rereview_paths=(rereview,),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            artifact.write_text("replacement acceptance evidence\n", encoding="utf-8")
            original_fix_plan = fix_plan.read_text(encoding="utf-8")
            fix_plan.write_text("# Mutated plan\n", encoding="utf-8")
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=findings,
                    report_paths=(initial,), verification=(remediation_evidence,),
                    rereview_paths=(rereview,),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            fix_plan.write_text(original_fix_plan, encoding="utf-8")

            write_resolved(
                source_commit=fix_head, artifact_evidence=proof_identity,
                artifact_rereview=initial,
            )
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=findings,
                    report_paths=(initial,), verification=(remediation_evidence,),
                    rereview_paths=(rereview,),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            write_resolved(source_commit="-", artifact_evidence=proof_identity)
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=findings,
                    report_paths=(initial,), verification=(remediation_evidence,),
                    rereview_paths=(rereview,),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            write_resolved(source_commit=fix_head, artifact_evidence=proof_identity)
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(remediation_evidence,),
                rereview_paths=(rereview,),
            )
            self.assertEqual(
                next(gate.state for gate in accepted.gates if gate.id == "phase-01"),
                "accepted",
            )

    def test_all_artifact_round_releases_without_commit_and_replay_is_idempotent(self):
        """Requiring a new commit for artifact-only work fabricates source provenance."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, reviewed_head = self.make_run(root)
            self.prepare_blocked_phase_gate(root, run_dir, reviewed_head)
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text(
                "# Artifact-only fix plan\n\n"
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n"
                "| --- | --- | --- |\n"
                '| F-001 | artifact | ["agent-output/rebuilt.md"] |\n',
                encoding="utf-8",
            )
            start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-001",), fix_plan=str(fix_plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            verification = _remediation_evidence(
                root, reviewed_head, "phase-01", 1, "artifact-only"
            )
            released = record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=1,
                fix_head=reviewed_head, commits=(), verification=(verification,),
                capacity=3, repo_dir=root,
            )
            row = next(item for item in released.remediation if item.gate == "phase-01")
            self.assertEqual((row.state, row.commits), ("re_reviewing", "N/A"))
            self.assertEqual(
                next(gate.state for gate in released.gates if gate.id == "phase-01"),
                "re_reviewing",
            )
            after = (run_dir / "progress.md").read_bytes()
            replayed = record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=1,
                fix_head=reviewed_head, commits=(), verification=(verification,),
                capacity=3, repo_dir=root,
            )
            self.assertEqual(replayed, released)
            self.assertEqual((run_dir / "progress.md").read_bytes(), after)

    def test_remediation_scope_is_validated_before_round_reservation(self):
        """Persisting before scope validation can reserve malformed fixer authority."""
        invalid_tables = {
            "malformed-kind": (
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-001 | guessed | none |\n"
            ),
            "duplicate-authority": (
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-001 | source | none |\n\n"
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-001 | source | none |\n"
            ),
            "mismatched-finding": (
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-OTHER | source | none |\n"
            ),
            "incomplete-artifacts": (
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-001 | artifact | [] |\n"
            ),
        }
        for label, table in invalid_tables.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir, _, head = self.make_run(root)
                self.prepare_blocked_phase_gate(root, run_dir, head)
                fix_plan = root / "fix-plan.md"
                fix_plan.write_text("# Fix plan\n\n" + table, encoding="utf-8")
                before = (run_dir / "progress.md").read_bytes()
                with self.assertRaises(TransitionError):
                    start_remediation_round(
                        run_dir, gate_id="phase-01", round_number=1,
                        finding_ids=("F-001",), fix_plan=str(fix_plan),
                        fixer_assignments=("fixer-1",), capacity=3,
                    )
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            self.prepare_blocked_phase_gate(root, run_dir, head)
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text(
                "# Fix plan\n\n"
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-001 | source | none |\n",
                encoding="utf-8",
            )
            reserved = start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-001",), fix_plan=str(fix_plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            after = (run_dir / "progress.md").read_bytes()
            replayed = start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-001",), fix_plan=str(fix_plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            self.assertEqual(replayed, reserved)
            self.assertEqual((run_dir / "progress.md").read_bytes(), after)

    def test_later_round_preserves_fixed_artifact_from_completed_artifact_round(self):
        """Treating N/A as malformed loses a valid artifact resolution on the next round."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, reviewed_head = self.make_run(root)
            phase_evidence = _verification_evidence(root, reviewed_head)
            record_phase_verification(
                run_dir, phase_id="01", head=reviewed_head,
                commands=("suite",), evidence=(phase_evidence,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=reviewed_head, head=reviewed_head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            finding_ids = "F-ARTIFACT,F-REMAINING"
            initial = self.write_report(
                root, "review.md", gate="phase-01", assignment="reviewer-1",
                base=reviewed_head, head=reviewed_head, findings=finding_ids,
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-ARTIFACT | phase-01 | Important | Open | - | review.md | - | - |\n"
                "| F-REMAINING | phase-01 | Important | Open | - | review.md | - | - |\n",
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(phase_evidence,), rereview_paths=(),
            )
            round_one_plan = root / "round-one.md"
            round_one_plan.write_text(
                "# Artifact round\n\n"
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n"
                "| --- | --- | --- |\n"
                '| F-ARTIFACT | artifact | ["agent-output/fixed.md"] |\n'
                '| F-REMAINING | artifact | ["agent-output/attempt.md"] |\n',
                encoding="utf-8",
            )
            round_one = start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-ARTIFACT", "F-REMAINING"),
                fix_plan=str(round_one_plan), fixer_assignments=("fixer-1",), capacity=3,
            )
            round_one_row = next(row for row in round_one.remediation if row.gate == "phase-01")
            output = root / "agent-output/fixed.md"
            output.parent.mkdir()
            output.write_text("fixed artifact\n", encoding="utf-8")
            (root / "agent-output/attempt.md").write_text("incomplete attempt\n", encoding="utf-8")
            output_identity = pipeline_state._digest_bound_reference(run_dir, output)
            verification_one = _remediation_evidence(
                root, reviewed_head, "phase-01", 1, "artifact-round"
            )
            record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=1,
                fix_head=reviewed_head, commits=(), verification=(verification_one,),
                capacity=3, repo_dir=root,
            )
            rereview_one = self.write_report(
                root, "rereview-one.md", gate="phase-01", assignment="reviewer-1",
                base=reviewed_head, head=reviewed_head, findings=finding_ids,
                outcomes={"F-ARTIFACT": "Resolved", "F-REMAINING": "Open"},
            )
            proof = root / "artifact-proof.md"
            proof.write_text(
                "<!-- pipeline-artifact-remediation/v2 -->\n"
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| finding | F-ARTIFACT |\n"
                "| gate | phase-01 |\n"
                "| round | 1 |\n"
                f"| fix_plan | {round_one_row.fix_plan} |\n"
                f"| artifacts | {json.dumps([output_identity], separators=(',', ':'))} |\n"
                f"| verification | {verification_one} |\n",
                encoding="utf-8",
            )
            proof_identity = pipeline_state._digest_bound_reference(run_dir, proof)
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-ARTIFACT | phase-01 | Important | Resolved | Fixed | {proof_identity} | - | {rereview_one} |\n"
                "| F-REMAINING | phase-01 | Important | Open | - | review.md | - | - |\n",
                encoding="utf-8",
            )
            after_one = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(verification_one,),
                rereview_paths=(rereview_one,),
            )
            self.assertEqual(
                next(row.commits for row in after_one.remediation if row.gate == "phase-01"),
                "N/A",
            )

            round_two_plan = root / "round-two.md"
            round_two_plan.write_text(
                "# Source round\n\n"
                "<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n"
                "| --- | --- | --- |\n"
                "| F-REMAINING | source | none |\n",
                encoding="utf-8",
            )
            start_remediation_round(
                run_dir, gate_id="phase-01", round_number=2,
                finding_ids=("F-REMAINING",), fix_plan=str(round_two_plan),
                fixer_assignments=("fixer-2",), capacity=3,
            )
            (root / "source-fix.txt").write_text("source fix\n", encoding="utf-8")
            self.git(root, "add", "source-fix.txt")
            self.git(root, "commit", "-qm", "source round")
            fix_head = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", fix_head)
            verification_two = _remediation_evidence(
                root, fix_head, "phase-01", 2, "source-round"
            )
            record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=2,
                fix_head=fix_head, commits=(fix_head,), verification=(verification_two,),
                capacity=3, repo_dir=root,
            )
            rereview_two = self.write_report(
                root, "rereview-two.md", gate="phase-01", assignment="reviewer-1",
                base=reviewed_head, head=fix_head, findings=finding_ids,
                outcomes={"F-ARTIFACT": "Resolved", "F-REMAINING": "Resolved"},
            )
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-ARTIFACT | phase-01 | Important | Resolved | Fixed | {proof_identity} | - | {rereview_one} |\n"
                f"| F-REMAINING | phase-01 | Important | Resolved | Fixed | {verification_two} | {fix_head} | {rereview_two} |\n",
                encoding="utf-8",
            )
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(verification_two,),
                rereview_paths=(rereview_two,),
            )
            self.assertEqual(
                next(gate.state for gate in accepted.gates if gate.id == "phase-01"),
                "accepted",
            )

    def test_rereview_can_introduce_a_new_finding_without_rewriting_initial_lineage(self):
        """A regression discovered during remediation stays in the same gate and round history."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, initial_head = self.make_run(root)
            phase_evidence = _verification_evidence(root, initial_head)
            record_phase_verification(
                run_dir, phase_id="01", head=initial_head,
                commands=("suite",), evidence=(phase_evidence,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=initial_head, head=initial_head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            initial = self.write_report(
                root, "initial.md", gate="phase-01", assignment="reviewer-1",
                base=initial_head, head=initial_head, findings="F-001",
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | phase-01 | Important | Open | - | initial.md | - | - |\n",
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(phase_evidence,), rereview_paths=(),
            )

            plan_one = root / "round-one.md"
            plan_one.write_text(
                "# Round one\n\n<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-001 | source | none |\n",
                encoding="utf-8",
            )
            start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-001",), fix_plan=str(plan_one),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            (root / "fix-one.txt").write_text("fix one\n", encoding="utf-8")
            self.git(root, "add", "fix-one.txt")
            self.git(root, "commit", "-qm", "fix one")
            fix_one = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", fix_one)
            verification_one = _remediation_evidence(root, fix_one, "phase-01", 1, "new-finding-one")
            record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=1, fix_head=fix_one,
                commits=(fix_one,), verification=(verification_one,), capacity=3,
                repo_dir=root,
            )
            rereview_one = self.write_report(
                root, "rereview-one.md", gate="phase-01", assignment="reviewer-1",
                base=initial_head, head=fix_one, findings="F-001,F-002",
                outcomes={"F-001": "Resolved", "F-002": "Open"},
            )
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-001 | phase-01 | Important | Resolved | Fixed | {verification_one} | {fix_one} | {rereview_one} |\n"
                "| F-002 | phase-01 | Important | Open | - | rereview-one.md | - | - |\n",
                encoding="utf-8",
            )
            blocked = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(verification_one,),
                rereview_paths=(rereview_one,),
            )
            gate = next(item for item in blocked.gates if item.id == "phase-01")
            self.assertEqual(gate.state, "blocked")
            self.assertEqual(set(pipeline_state._gate_finding_ids(gate)), {"F-001", "F-002"})

            plan_two = root / "round-two.md"
            plan_two.write_text(
                "# Round two\n\n<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-002 | source | none |\n",
                encoding="utf-8",
            )
            start_remediation_round(
                run_dir, gate_id="phase-01", round_number=2,
                finding_ids=("F-002",), fix_plan=str(plan_two),
                fixer_assignments=("fixer-2",), capacity=3,
            )
            (root / "fix-two.txt").write_text("fix two\n", encoding="utf-8")
            self.git(root, "add", "fix-two.txt")
            self.git(root, "commit", "-qm", "fix two")
            fix_two = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", fix_two)
            verification_two = _remediation_evidence(root, fix_two, "phase-01", 2, "new-finding-two")
            record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=2, fix_head=fix_two,
                commits=(fix_two,), verification=(verification_two,), capacity=3,
                repo_dir=root,
            )
            rereview_two = self.write_report(
                root, "rereview-two.md", gate="phase-01", assignment="reviewer-1",
                base=fix_one, head=fix_two, findings="F-001,F-002",
                outcomes={"F-001": "Resolved", "F-002": "Resolved"},
            )
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-001 | phase-01 | Important | Resolved | Fixed | {verification_one} | {fix_one} | {rereview_one} |\n"
                f"| F-002 | phase-01 | Important | Resolved | Fixed | {verification_two} | {fix_two} | {rereview_two} |\n",
                encoding="utf-8",
            )
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(verification_two,),
                rereview_paths=(rereview_two,),
            )
            self.assertEqual(
                next(item.state for item in accepted.gates if item.id == "phase-01"),
                "accepted",
            )

    def test_open_minor_can_follow_explicit_fix_decision_through_same_gate(self):
        """A valid Minor selected for fixing must not be forced into defer/reject."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            phase_evidence = _verification_evidence(root, head)
            record_phase_verification(
                run_dir, phase_id="01", head=head,
                commands=("suite",), evidence=(phase_evidence,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=head, head=head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            initial = self.write_report(
                root, "minor-review.md", gate="phase-01", assignment="reviewer-1",
                base=head, head=head, findings="F-MINOR",
            )
            (root / "decisions.md").write_text(
                "# Decisions\n\n## D-100 — Minor disposition\n\n"
                "- **Question:** What disposition should F-MINOR receive?\n"
                "- **Answer:** Fix it in the next remediation round.\n"
                "- **Decision action:** review.resolve-question\n"
                "- **Scope:** F-MINOR in phase-01.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-MINOR | phase-01 | Minor | Open | - | D-100 | - | - |\n",
                encoding="utf-8",
            )
            blocked = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(phase_evidence,), rereview_paths=(),
            )
            gate = next(item for item in blocked.gates if item.id == "phase-01")
            self.assertEqual((gate.state, gate.questions), ("blocked", "-"))

            fix_plan = root / "minor-fix-plan.md"
            fix_plan.write_text(
                "# Minor fix\n\n<!-- pipeline-remediation-scope/v2 -->\n"
                "| Finding | Kind | Artifacts |\n| --- | --- | --- |\n"
                "| F-MINOR | source | none |\n",
                encoding="utf-8",
            )
            start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-MINOR",), fix_plan=str(fix_plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            (root / "minor-fix.txt").write_text("minor fix\n", encoding="utf-8")
            self.git(root, "add", "minor-fix.txt")
            self.git(root, "commit", "-qm", "fix minor")
            fix_head = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", fix_head)
            verification = _remediation_evidence(root, fix_head, "phase-01", 1, "minor-fix")
            record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=1,
                fix_head=fix_head, commits=(fix_head,), verification=(verification,),
                capacity=3, repo_dir=root,
            )
            rereview = self.write_report(
                root, "minor-rereview.md", gate="phase-01", assignment="reviewer-1",
                base=head, head=fix_head, findings="F-MINOR",
                outcomes={"F-MINOR": "Resolved"},
            )
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-MINOR | phase-01 | Minor | Resolved | Fixed | {verification} | {fix_head} | {rereview} |\n",
                encoding="utf-8",
            )
            accepted = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(verification,),
                rereview_paths=(rereview,),
            )
            self.assertEqual(
                next(item.state for item in accepted.gates if item.id == "phase-01"),
                "accepted",
            )

    def test_resolving_only_a_minor_does_not_count_as_blocker_progress(self):
        rows = (
            ("F-BLOCK", "phase-01", "Important", "Open", "-", "-", "-", "-"),
            ("F-MINOR", "phase-01", "Minor", "Resolved", "Fixed", "proof", "a" * 40, "review"),
        )
        self.assertFalse(
            pipeline_state._blocking_remediation_progress(
                rows, {"F-BLOCK", "F-MINOR"}, {"F-BLOCK"},
            )
        )
        resolved_rows = (
            ("F-BLOCK", "phase-01", "Important", "Resolved", "Fixed", "proof", "b" * 40, "review"),
            rows[1],
        )
        self.assertTrue(
            pipeline_state._blocking_remediation_progress(
                resolved_rows, {"F-BLOCK", "F-MINOR"}, set(),
            )
        )

    def test_gate_questions_clear_only_from_applicable_resolved_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            self.prepare_blocked_phase_gate(root, run_dir, head)
            locked_tracker_update(
                run_dir, "fixture-gate-question",
                lambda tracker: dataclasses.replace(
                    tracker,
                    gates=tuple(
                        dataclasses.replace(gate, questions="D-100")
                        if gate.id == "phase-01" else gate
                        for gate in tracker.gates
                    ),
                ),
                timeout_s=1.0,
            )
            decisions = root / "decisions.md"
            decisions.write_text(
                "# Decisions\n\n## D-100 — Gate answer\n\n"
                "- **Question:** Which remediation behavior applies?\n"
                "- **Answer:** Use the explicit reviewed fix contract.\n"
                "- **Decision action:** review.resolve-question\n"
                "- **Affected work:** F-001 in phase-01.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            resolved = pipeline_state.resolve_gate_questions(
                run_dir, gate_id="phase-01", decision_refs=("D-100",),
            )
            self.assertEqual(next(gate.questions for gate in resolved.gates if gate.id == "phase-01"), "-")

    def test_master_question_scope_ignores_sentinel_and_requires_exact_identity(self):
        """A '-' phase sentinel or finding-ID prefix must not authorize another gate."""
        def blocked_master(root: Path) -> Path:
            run_dir, run_base, _, reviewed_head = self.make_changed_master_run(root)
            open_review_gate(
                run_dir, gate_id="master", base=run_base, head=reviewed_head,
                reviewer_assignments=("reviewer-a", "reviewer-b"), capacity=3,
            )
            reports = tuple(
                self.write_report(
                    root, f"master-{suffix}.md", gate="master", assignment=f"reviewer-{suffix}",
                    base=run_base, head=reviewed_head, findings="F-001",
                )
                for suffix in ("a", "b")
            )
            (root / "findings.md").write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | master | Important | Open | - | master-a.md,master-b.md | - | - |\n",
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="master", findings_path=root / "findings.md",
                report_paths=reports,
                verification=(_verification_evidence(root, reviewed_head, subject="phase/04"),),
                rereview_paths=(),
            )
            return run_dir

        invalid_scopes = ("phase-99 only.", "master-extra only.", "F-001-extra only.")
        for index, scope in enumerate(invalid_scopes, start=1):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run_dir = blocked_master(root)
                decision_ref = f"D-{200 + index}"
                locked_tracker_update(
                    run_dir, f"fixture-master-question-{index}",
                    lambda tracker: dataclasses.replace(
                        tracker,
                        gates=tuple(
                            dataclasses.replace(
                                gate, state="blocked",
                                findings="F-001@Important@sha256=" + "a" * 64,
                                questions=decision_ref,
                            ) if gate.id == "master" else gate
                            for gate in tracker.gates
                        ),
                    ),
                    timeout_s=1.0,
                )
                (root / "decisions.md").write_text(
                    "# Decisions\n\n"
                    f"## {decision_ref} — Review answer\n\n"
                    "- **Question:** Which review behavior applies?\n"
                    "- **Answer:** Use the explicitly selected behavior.\n"
                    "- **Decision action:** review.resolve-question\n"
                    f"- **Scope:** {scope}\n"
                    "- **Status:** Resolved.\n",
                    encoding="utf-8",
                )
                before = (run_dir / "progress.md").read_bytes()
                with self.assertRaises(TransitionError):
                    pipeline_state.resolve_gate_questions(
                        run_dir, gate_id="master", decision_refs=(decision_ref,),
                    )
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = blocked_master(root)
            locked_tracker_update(
                run_dir, "fixture-master-question-valid",
                lambda tracker: dataclasses.replace(
                    tracker,
                    gates=tuple(
                        dataclasses.replace(gate, state="blocked", questions="D-299")
                        if gate.id == "master" else gate
                        for gate in tracker.gates
                    ),
                ),
                timeout_s=1.0,
            )
            (root / "decisions.md").write_text(
                "# Decisions\n\n## D-299 — Master answer\n\n"
                "- **Question:** Which review behavior applies?\n"
                "- **Answer:** Use the explicitly selected behavior.\n"
                "- **Decision action:** review.resolve-question\n"
                "- **Scope:** master gate.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            resolved = pipeline_state.resolve_gate_questions(
                run_dir, gate_id="master", decision_refs=("D-299",),
            )
            self.assertEqual(next(gate.questions for gate in resolved.gates if gate.id == "master"), "-")

    def test_missing_wrong_or_conflicting_gate_actions_are_rejected_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = self.make_run(root)
            self.prepare_blocked_phase_gate(root, run_dir, head)
            locked_tracker_update(
                run_dir,
                "fixture-gate-question-negative",
                lambda tracker: dataclasses.replace(
                    tracker,
                    gates=tuple(
                        dataclasses.replace(gate, questions="D-100")
                        if gate.id == "phase-01" else gate
                        for gate in tracker.gates
                    ),
                ),
                timeout_s=1.0,
            )
            decisions = root / "decisions.md"
            decisions.write_text(
                "# Decisions\n\n## D-100 — Gate answer\n\n"
                "- **Question:** Which remediation behavior applies?\n"
                "- **Answer:** Reject the reviewed fix contract.\n"
                "- **Affected work:** F-001 in phase-01.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                pipeline_state.resolve_gate_questions(
                    run_dir, gate_id="phase-01", decision_refs=("D-100",),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            decisions.write_text(
                "# Decisions\n\n## D-100 — Gate answer\n\n"
                "- **Question:** Which remediation behavior applies?\n"
                "- **Answer:** Use the reviewed fix contract.\n"
                "- **Decision action:** task.resume\n"
                "- **Affected work:** F-001 in phase-01.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            with self.assertRaises(TransitionError):
                pipeline_state.resolve_gate_questions(
                    run_dir, gate_id="phase-01", decision_refs=("D-100",),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            decisions.write_text(
                "# Decisions\n\n## D-100 — Gate answer\n\n"
                "- **Question:** Which remediation behavior applies?\n"
                "- **Answer:** Use the reviewed fix contract.\n"
                "- **Decision action:** review.resolve-question\n"
                "- **Affected work:** F-001 in phase-01.\n"
                "- **Status:** Resolved.\n\n"
                "## D-101 — Conflicting gate answer\n\n"
                "- **Question:** Which remediation behavior applies?\n"
                "- **Answer:** Use the incompatible alternate contract.\n"
                "- **Decision action:** review.resolve-question\n"
                "- **Affected work:** F-001 in phase-01.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            with self.assertRaises(TransitionError):
                pipeline_state.resolve_gate_questions(
                    run_dir, gate_id="phase-01", decision_refs=("D-100",),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)


class PhaseAdvancementTest(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ("git", *args), cwd=repo, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()

    def make_run(
        self,
        root: Path,
        *,
        first_gate: str = "required",
        second_gate: str = "final-only",
        phase_two_deps: str = "01",
        phase_count: int = 2,
    ) -> tuple[Path, tuple[Path, ...], str]:
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "pipeline@example.invalid")
        self.git(root, "config", "user.name", "Pipeline Test")
        (root / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(root, "add", "base.txt")
        self.git(root, "commit", "-qm", "base")
        head = self.git(root, "rev-parse", "HEAD")
        self.git(root, "branch", "target")
        plans = []
        phase_specs = [
            ("01", "none", first_gate, "Foundational state risk.", "P1-A", "source", "file:source.txt", "none"),
            (
                "02", phase_two_deps, second_gate,
                "Downstream recovery risk." if second_gate == "required" else "Mechanical verification only.",
                "P2-A", "artifact", "file:evidence/two.md", "evidence/two.md",
            ),
            ("03", "01,02", "final-only", "Mechanical verification only.", "P3-A", "artifact", "file:evidence/three.md", "evidence/three.md"),
        ]
        for phase_id, deps, gate, reason, task_id, kind, scope, outputs in phase_specs[:phase_count]:
            plan = root / f"phase-{phase_id}.md"
            plan.write_text(
                f"""# Phase {phase_id}

<!-- pipeline-v2-phase: id={phase_id}; deps={deps}; review_gate={gate}; review_reason={reason} -->
<!-- pipeline-v2-phase-suite: id={phase_id}; commands=["suite"] -->

### {task_id} — Work
<!-- pipeline-v2-task: id={task_id}; deps=none; kind={kind}; batch=phase-{phase_id}; order=1; write_scope={scope}; outputs={outputs} -->
{f'<!-- pipeline-v2-task-suite: id={task_id}; commands=["task-suite-{task_id}"] -->' if kind == 'source' else ''}
""",
                encoding="utf-8",
            )
            plans.append(plan)
        master = root / "master.md"
        master.write_text(
            "# Master\n\n" + "\n".join(f"- **Detailed plan:** `{plan}`" for plan in plans) + "\n",
            encoding="utf-8",
        )
        (root / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
        (root / "findings.md").write_text(
            "<!-- pipeline-findings/v2 -->\n"
            "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n",
            encoding="utf-8",
        )
        run_dir = root / "run"
        initialize_run(
            run_dir,
            run_id="advance-test",
            base_commit=head,
            target_branch="target",
            worker_limit=3,
            artifacts={
                "spec": "spec.md",
                "master_plan": str(master),
                "phase_plans": ",".join(str(plan) for plan in plans),
                "decisions": str(root / "decisions.md"),
                "findings": str(root / "findings.md"),
            },
            approved_existing=(),
        )
        return run_dir, tuple(plans), head

    def complete_first_source(self, root: Path, run_dir: Path, plan: Path) -> str:
        started = start_task(run_dir, task_id="P1-A", owner="worker-a", attempt="attempt-1")
        self.assertEqual(dict(started.current_fields)["next_action"], "continue-P1-A")
        (root / "source.txt").write_text("implemented\n", encoding="utf-8")
        self.git(root, "add", "source.txt")
        self.git(root, "commit", "-qm", "implement source")
        commit = self.git(root, "rev-parse", "HEAD")
        task_evidence = _verification_evidence(
            root, commit, "advance-task", purpose="task-test",
            run_id="advance-test", subject="task/P1-A", attempt="attempt-1",
            commands=("task-suite-P1-A",),
        )
        completed = complete_task(
            run_dir, task_id="P1-A", attempt="attempt-1", phase_plan=plan,
            source_ref="HEAD", commits=(commit,), artifacts=(), evidence=(task_evidence,),
            repo_dir=root,
        )
        self.assertEqual(dict(completed.current_fields)["next_action"], "integrate-P1-A")
        self.git(root, "branch", "-f", "target", commit)
        integration_evidence = _verification_evidence(
            root, commit, "advance-integration", purpose="task-integration",
            run_id="advance-test", subject="task/P1-A", attempt="N/A",
            commands=("integration-check",),
        )
        integrated = record_task_integration(
            run_dir, task_id="P1-A", integration_commit=commit,
            verification=(integration_evidence,), repo_dir=root,
        )
        self.assertEqual(dict(integrated.current_fields)["next_action"], "verify-phase-01")
        return commit

    def accept_phase_gate(
        self, root: Path, run_dir: Path, head: str, *, phase_id: str = "01",
        phase_base: str | None = None,
    ) -> None:
        phase_base = phase_base or validate_run(run_dir).base_commit
        gate_id = f"phase-{phase_id}"
        report_name = f"review-{phase_id}.md"
        opened = open_review_gate(
            run_dir, gate_id=gate_id, base=phase_base, head=head,
            reviewer_assignments=("reviewer-1",), capacity=3,
        )
        self.assertEqual(dict(opened.current_fields)["next_action"], f"await-review-{gate_id}")
        report = root / report_name
        report.write_text(
            "<!-- pipeline-review-report/v2 -->\n"
            "| Field | Value |\n| --- | --- |\n"
            f"| gate | {gate_id} |\n| assignment | reviewer-1 |\n| base | {phase_base} |\n"
            f"| head | {head} |\n| findings | - |\n| outcomes | {{}} |\n",
            encoding="utf-8",
        )
        phase = next(item for item in opened.phases if item.id == phase_id)
        evaluate_and_close_review_gate(
            run_dir, gate_id=gate_id, findings_path=root / "findings.md",
            report_paths=(report,),
            verification=pipeline_state._phase_verification_evidence(phase),
            rereview_paths=(),
        )

    def test_last_task_completion_derives_integration_then_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(root)
            self.complete_first_source(root, run_dir, plans[0])

    def test_accepted_required_last_phase_routes_to_master_gate(self):
        """A required review on the last phase must not derive a nonexistent successor."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(root, phase_count=1)
            head = self.complete_first_source(root, run_dir, plans[0])
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(_verification_evidence(
                    root, head, run_id="advance-test", commands=("suite",)
                ),),
            )
            self.accept_phase_gate(root, run_dir, head)
            tracker = validate_run(run_dir)
            self.assertEqual(
                pipeline_state.derive_next_action(run_dir, tracker),
                "open-gate-master",
            )

    def test_required_last_phase_after_ordinary_phase_routes_to_master_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(
                root, first_gate="final-only", second_gate="required",
            )
            head = self.complete_first_source(root, run_dir, plans[0])
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(_verification_evidence(
                    root, head, run_id="advance-test", commands=("suite",)
                ),),
            )
            pipeline_state.advance_phase(
                run_dir, completed_phase_id="01", next_phase_id="02",
            )
            output = root / "evidence/two.md"
            output.parent.mkdir()
            output.write_text("validated artifact\n", encoding="utf-8")
            start_task(run_dir, task_id="P2-A", owner="worker-b", attempt="attempt-2")
            complete_task(
                run_dir, task_id="P2-A", attempt="attempt-2", phase_plan=plans[1],
                source_ref=None, commits=(), artifacts=(Path("evidence/two.md"),),
                evidence=(_artifact_validation_evidence(
                    root, head, run_id="advance-test", task_id="P2-A",
                    attempt="attempt-2", outputs=("evidence/two.md",),
                ),),
                repo_dir=root,
            )
            record_phase_verification(
                run_dir, phase_id="02", head=head, commands=("suite",),
                evidence=(_verification_evidence(
                    root, head, label="phase-02-suite", run_id="advance-test",
                    subject="phase/02", commands=("suite",),
                ),),
            )
            self.accept_phase_gate(
                root, run_dir, head, phase_id="02", phase_base=head,
            )
            self.assertEqual(
                pipeline_state.derive_next_action(run_dir, validate_run(run_dir)),
                "open-gate-master",
            )

    def test_direct_start_cannot_bypass_the_current_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, _ = self.make_run(root, first_gate="final-only")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                start_task(run_dir, task_id="P2-A", owner="worker", attempt="future-1")
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_initialization_rejects_phase_plan_order_that_conflicts_with_master(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, head = self.make_run(root, first_gate="final-only")
            extra = root / "phase-extra.md"
            cases = {
                "reordered": (
                    root / "master.md", f"{plans[1]},{plans[0]}"
                ),
                "missing": (
                    root / "missing-master.md", f"{plans[0]},{plans[1]}"
                ),
                "duplicate": (
                    root / "duplicate-master.md", f"{plans[0]},{plans[1]}"
                ),
                "extra": (
                    root / "extra-master.md", f"{plans[0]},{plans[1]}"
                ),
            }
            cases["missing"][0].write_text(f"# Master\n\n`{plans[0]}`\n", encoding="utf-8")
            cases["duplicate"][0].write_text(
                f"# Master\n\n`{plans[0]}`\n`{plans[0]}`\n`{plans[1]}`\n",
                encoding="utf-8",
            )
            cases["extra"][0].write_text(
                f"# Master\n\n`{plans[0]}`\n`{plans[1]}`\n`{extra}`\n",
                encoding="utf-8",
            )
            for label, (master, phase_paths) in cases.items():
                with self.subTest(label=label):
                    other_run = root / f"{label}-run"
                    with self.assertRaises(SchemaError):
                        initialize_run(
                            other_run,
                            run_id=f"{label}-test",
                            base_commit=head,
                            target_branch="target",
                            worker_limit=3,
                            artifacts={
                                "spec": "spec.md",
                                "master_plan": str(master),
                                "phase_plans": phase_paths,
                                "decisions": str(root / "decisions.md"),
                                "findings": str(root / "findings.md"),
                            },
                            approved_existing=(),
                        )
                    self.assertFalse((other_run / "progress.md").exists())

    def test_task_start_rechecks_current_phase_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, _ = self.make_run(root, first_gate="final-only")

            def select_unmet_phase(tracker):
                return dataclasses.replace(
                    tracker,
                    current_fields=tuple(
                        (key, "02" if key == "phase" else value)
                        for key, value in tracker.current_fields
                    ),
                    phases=tuple(
                        dataclasses.replace(phase, state="[~]")
                        if phase.id == "02" else phase
                        for phase in tracker.phases
                    ),
                )

            locked_tracker_update(
                run_dir, "fixture-unmet-current-phase", select_unmet_phase,
                timeout_s=1.0,
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                start_task(
                    run_dir, task_id="P2-A", owner="worker", attempt="future-1"
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_block_and_answered_resume_refresh_the_derived_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, _ = self.make_run(root, first_gate="final-only")
            start_task(run_dir, task_id="P1-A", owner="worker-a", attempt="attempt-1")
            blocked = record_task_question(
                run_dir, task_id="P1-A", attempt="attempt-1",
                question_or_block_ref="D-100", reason="answer required",
            )
            self.assertEqual(dict(blocked.current_fields)["next_action"], "await-user-decision-P1-A")
            (root / "decisions.md").write_text(
                "# Decisions\n\n## D-100 — Answer\n\n"
                "- **Question:** Which behavior applies?\n"
                "- **Answer:** Use the explicitly recorded behavior.\n"
                "- **Decision action:** task.resume\n"
                "- **Scope:** P1-A current blocker.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            resumed = resume_task(
                run_dir, task_id="P1-A", prior_attempt="attempt-1",
                new_owner="worker-a", new_attempt="attempt-2", decision_ref="D-100",
            )
            self.assertEqual(dict(resumed.current_fields)["next_action"], "continue-P1-A")

    def test_failed_phase_verification_derives_repair_before_another_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(root, first_gate="final-only")
            head = self.complete_first_source(root, run_dir, plans[0])

            def fail_verification(tracker):
                return dataclasses.replace(
                    tracker,
                    phases=tuple(
                        dataclasses.replace(
                            phase,
                            state="[?]",
                            verification=f"failed:phase-suite;head:{head}",
                        ) if phase.id == "01" else phase
                        for phase in tracker.phases
                    ),
                )

            failed = locked_tracker_update(
                run_dir, "fixture-failed-verification", fail_verification,
                timeout_s=1.0, refresh_next_action=True,
            )
            self.assertEqual(dict(failed.current_fields)["next_action"], "repair-phase-01")

    def test_required_review_blocks_then_accepted_gate_advances_and_replay_is_inert(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(root)
            head = self.complete_first_source(root, run_dir, plans[0])
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(_verification_evidence(
                    root, head, run_id="advance-test", commands=("suite",)
                ),),
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                pipeline_state.advance_phase(run_dir, completed_phase_id="01", next_phase_id="02")
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            self.accept_phase_gate(root, run_dir, head)
            advanced = pipeline_state.advance_phase(run_dir, completed_phase_id="01", next_phase_id="02")
            self.assertEqual((dict(advanced.current_fields)["phase"], dict(advanced.current_fields)["next_action"]), ("02", "P2-A"))
            accepted = (run_dir / "progress.md").read_bytes()
            revision = advanced.revision
            replayed = pipeline_state.advance_phase(run_dir, completed_phase_id="01", next_phase_id="02")
            self.assertEqual((replayed.revision, (run_dir / "progress.md").read_bytes()), (revision, accepted))

    def test_required_phase_cannot_advance_after_target_tip_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(root)
            head = self.complete_first_source(root, run_dir, plans[0])
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(_verification_evidence(
                    root, head, run_id="advance-test", commands=("suite",)
                ),),
            )
            self.accept_phase_gate(root, run_dir, head)
            (root / "after-review.txt").write_text("new target work\n", encoding="utf-8")
            self.git(root, "add", "after-review.txt")
            self.git(root, "commit", "-qm", "advance after phase acceptance")
            tip = self.git(root, "rev-parse", "HEAD")
            self.git(root, "branch", "-f", "target", tip)
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                pipeline_state.advance_phase(
                    run_dir, completed_phase_id="01", next_phase_id="02"
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_verified_final_only_phase_advances_without_phase_reviewer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(root, first_gate="final-only")
            head = self.complete_first_source(root, run_dir, plans[0])
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(_verification_evidence(
                    root, head, run_id="advance-test", commands=("suite",)
                ),),
            )
            advanced = pipeline_state.advance_phase(run_dir, completed_phase_id="01", next_phase_id="02")
            self.assertEqual(dict(advanced.current_fields)["phase"], "02")
            self.assertFalse(any(gate.id == "phase-01" for gate in advanced.gates))

    def test_wrong_skipped_dependency_and_unresolved_question_fail_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(root, first_gate="final-only", phase_count=3)
            head = self.complete_first_source(root, run_dir, plans[0])
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(_verification_evidence(
                    root, head, run_id="advance-test", commands=("suite",)
                ),),
            )
            for completed, successor in (("02", "03"), ("01", "03"), ("01", "99")):
                with self.subTest(completed=completed, successor=successor):
                    before = (run_dir / "progress.md").read_bytes()
                    with self.assertRaises(TransitionError):
                        pipeline_state.advance_phase(run_dir, completed_phase_id=completed, next_phase_id=successor)
                    self.assertEqual((run_dir / "progress.md").read_bytes(), before)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(root, first_gate="final-only")
            head = self.complete_first_source(root, run_dir, plans[0])
            record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(_verification_evidence(
                    root, head, run_id="advance-test", commands=("suite",)
                ),),
            )
            locked_tracker_update(
                run_dir, "fixture-question",
                lambda tracker: dataclasses.replace(
                    tracker,
                    tasks=tuple(dataclasses.replace(task, question="D-900") if task.id == "P1-A" else task for task in tracker.tasks),
                ),
                timeout_s=1.0,
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                pipeline_state.advance_phase(run_dir, completed_phase_id="01", next_phase_id="02")
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_last_phase_routes_to_master_and_read_only_inspection_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, plans, _ = self.make_run(root, first_gate="final-only", phase_count=1)
            head = self.complete_first_source(root, run_dir, plans[0])
            verified = record_phase_verification(
                run_dir, phase_id="01", head=head, commands=("suite",),
                evidence=(_verification_evidence(
                    root, head, run_id="advance-test", commands=("suite",)
                ),),
            )
            self.assertEqual(dict(verified.current_fields)["next_action"], "open-gate-master")
            locked_tracker_update(
                run_dir, "fixture-stale-action",
                lambda tracker: dataclasses.replace(
                    tracker,
                    current_fields=tuple(
                        (key, "P1-A" if key == "next_action" else value)
                        for key, value in tracker.current_fields
                    ),
                ),
                timeout_s=1.0,
            )
            before = (run_dir / "progress.md").read_bytes()
            summary = inspect_run(run_dir)
            self.assertEqual(summary["persisted_next_action"], "P1-A")
            self.assertEqual(summary["derived_next_action"], "open-gate-master")
            self.assertFalse(summary["next_action_consistent"])
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)


class ReconciliationTest(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[WorkerResultImportTest, Path, Path]:
        helper = WorkerResultImportTest()
        run_dir, plan, _ = helper.make_run(root)
        (root / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (root / "findings.md").write_text("# Findings\n", encoding="utf-8")
        return helper, run_dir, plan

    def test_post_commit_source_result_reconciles_once_before_integration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper, run_dir, plan = self.prepare(root)
            commit = helper.commit_source(root)
            start_task(run_dir, task_id="PR-01", owner="worker-a", attempt="attempt-1")
            evidence = _verification_evidence(
                root, commit, "reconcile-source", purpose="task-test",
                run_id="result-test", subject="task/PR-01", attempt="attempt-1",
                commands=("task-suite-PR-01",),
            )
            helper.write_result(
                run_dir, "interrupted.md",
                helper.result_text(
                    task_id="PR-01", attempt="attempt-1", owner="worker-a",
                    source_ref="worker", commits=commit, evidence=evidence,
                ),
            )
            first = reconcile_run(run_dir, phase_plan=plan, repo_dir=root)
            self.assertIsInstance(first, ReconciliationReport)
            self.assertIn("imported:PR-01:attempt-1", first.actions)
            revision = validate_run(run_dir).revision
            second = reconcile_run(run_dir, phase_plan=plan, repo_dir=root)
            self.assertEqual(validate_run(run_dir).revision, revision)
            self.assertIn("integration-pending:PR-01", second.actions)

    def test_artifact_result_reconciles_without_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper, run_dir, plan = self.prepare(root)
            (root / "evidence").mkdir()
            (root / "evidence/artifact.md").write_text("artifact\n", encoding="utf-8")
            start_task(run_dir, task_id="PR-02", owner="worker-a", attempt="artifact-1")
            evidence = _artifact_validation_evidence(
                root, helper.git(root, "rev-parse", "target"), run_id="result-test",
                task_id="PR-02", attempt="artifact-1", outputs=("evidence/artifact.md",),
            )
            helper.write_result(run_dir, "artifact-interrupted.md", helper.result_text(task_id="PR-02", attempt="artifact-1", owner="worker-a", kind="artifact", artifacts="evidence/artifact.md", evidence=evidence))
            report = reconcile_run(run_dir, phase_plan=plan, repo_dir=root)
            task = next(task for task in validate_run(run_dir).tasks if task.id == "PR-02")
            self.assertIn("imported:PR-02:artifact-1", report.actions)
            self.assertEqual((task.state, task.integration, task.commits), ("[x]", "N/A", "-"))

    def test_consistent_active_and_partial_evidence_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, run_dir, plan = self.prepare(root)
            start_task(run_dir, task_id="PR-01", owner="worker-a", attempt="attempt-1")
            partial = run_dir / "agent-output/partial.md"
            partial.write_text("<!-- pipeline-worker-result/v2 -->\npartial", encoding="utf-8")
            before = (run_dir / "progress.md").read_bytes()
            report = reconcile_run(run_dir, phase_plan=plan, repo_dir=root)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            self.assertIn("await-or-check-live-owner:PR-01:attempt-1:worker-a", report.actions)
            self.assertTrue(any("partial.md" in item for item in report.diagnostics))

    def test_git_contradiction_and_interrupted_round_are_reported_without_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper, run_dir, plan = self.prepare(root)
            commit = helper.commit_source(root)

            def contradict(tracker):
                task = next(task for task in tracker.tasks if task.id == "PR-01")
                changed = dataclasses.replace(
                    task, state="[x]", owner="worker-a", attempt="attempt-1",
                    result="result:attempt-1", checkpoints="started:attempt-1,completed:attempt-1",
                    source_ref="worker", commits=commit, integration=tracker.base_commit,
                    verification=f"reconciled-existing-integration:{tracker.base_commit}",
                )
                gate = next(gate for gate in tracker.gates if gate.id == "master")
                origin = "F-001@Important@sha256=" + "a" * 64
                blocked_gate = dataclasses.replace(
                    gate, state="blocked", head=tracker.base_commit,
                    assignments="reviewer-a,reviewer-b", reports="review-a.md,review-b.md",
                    verification="phase-evidence.md", findings=origin,
                )
                round_row = next(row for row in tracker.remediation if row.gate == "master")
                active_round = dataclasses.replace(round_row, state="fixing", fixers="fixer-1", findings="F-001", fix_plan="fix.md")
                return dataclasses.replace(tracker, tasks=tuple(changed if item.id == "PR-01" else item for item in tracker.tasks), gates=tuple(blocked_gate if item.id == "master" else item for item in tracker.gates), remediation=tuple(active_round if item.gate == "master" else item for item in tracker.remediation))

            locked_tracker_update(run_dir, "contradict", contradict, timeout_s=1.0)
            before = (run_dir / "progress.md").read_bytes()
            report = reconcile_run(run_dir, phase_plan=plan, repo_dir=root)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            self.assertTrue(any("integration-contradiction:PR-01" in item for item in report.questions))
            self.assertNotIn("resume-remediation:master:1", report.actions)
            self.assertTrue(any("fix-plan-contradiction:master:1" in item for item in report.questions))

    def test_reconciliation_requires_immutable_active_fix_plan_identity(self):
        for label, mutate in (("unchanged", False), ("changed", True)):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, run_dir, plan = self.prepare(root)
                fix_plan = root / "fix.md"
                fix_plan.write_text("# Scoped fix\n", encoding="utf-8")
                identity = pipeline_state._digest_bound_reference(run_dir, fix_plan)

                def activate(tracker):
                    gate = next(gate for gate in tracker.gates if gate.id == "master")
                    origin = "F-001@Important@sha256=" + "a" * 64
                    blocked_gate = dataclasses.replace(
                        gate, state="blocked", head=tracker.base_commit,
                        assignments="reviewer-a,reviewer-b",
                        reports="review-a.md,review-b.md",
                        verification="phase-evidence.md", findings=origin,
                    )
                    row = next(item for item in tracker.remediation if item.gate == "master")
                    active = dataclasses.replace(
                        row, state="fixing", fixers="fixer-1", findings="F-001",
                        fix_plan=identity,
                    )
                    return dataclasses.replace(
                        tracker,
                        gates=tuple(blocked_gate if item.id == "master" else item for item in tracker.gates),
                        remediation=tuple(active if item.gate == "master" else item for item in tracker.remediation),
                    )

                locked_tracker_update(run_dir, "fixture-active-fix", activate, timeout_s=1.0)
                if mutate:
                    fix_plan.write_text("# Changed scope\n", encoding="utf-8")
                before = (run_dir / "progress.md").read_bytes()
                report = reconcile_run(run_dir, phase_plan=plan, repo_dir=root)
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)
                if mutate:
                    self.assertNotIn("resume-remediation:master:1", report.actions)
                    self.assertTrue(any("fix-plan-contradiction:master:1" in item for item in report.questions))
                else:
                    self.assertIn("resume-remediation:master:1", report.actions)


class InstalledControllerWalkthroughTest(unittest.TestCase):
    def test_walkthrough_imports_installed_helper_from_an_unrelated_project(self):
        script = REPOSITORY / "plugins/superb/skills/pipeline/examples/controller_walkthrough.py"
        skill_dir = REPOSITORY / "plugins/superb/skills/pipeline"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "target-project"
            completed = subprocess.run(
                ("python3.11", str(script), str(skill_dir), str(project)),
                cwd=Path(directory), text=True, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["next_action"], "complete")
        self.assertEqual(summary["current_phase"], "01")
        self.assertEqual(summary["master_gate"], "accepted")


class PhaseOneReviewRegressionTest(unittest.TestCase):
    def test_known_unsupported_filesystem_rejects_mutation_before_lock_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            (run_dir / "progress.md").write_bytes((FIXTURES / "valid-v2-progress.md").read_bytes())
            before = {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()}
            unsupported = pipeline_state.FilesystemInfo(
                classification="unsupported", fs_type="nfs", fingerprint="f" * 64,
            )
            with mock.patch.object(pipeline_state, "classify_filesystem", return_value=unsupported):
                with self.assertRaises(pipeline_state.FilesystemSuitabilityError):
                    locked_tracker_update(run_dir, "unsupported-fs", lambda tracker: tracker, timeout_s=1.0)
            self.assertEqual(
                {path.name: path.read_bytes() for path in run_dir.iterdir() if path.is_file()},
                before,
            )
            self.assertFalse((run_dir / ".pipeline-state.lock").exists())

    def test_explicit_pre_release_adoption_is_strict_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "2026-09-08-pipeline-rebuild-v2"
            run_dir.mkdir()
            source = (FIXTURES / "pre-adoption-v2-progress.md").read_bytes()
            (run_dir / "progress.md").write_bytes(source)
            digest = hashlib.sha256(source).hexdigest()
            supported = pipeline_state.FilesystemInfo(
                classification="supported-local", fs_type="ext4", fingerprint="a" * 64,
            )
            with mock.patch.object(pipeline_state, "classify_filesystem", return_value=supported):
                adopted = pipeline_state.adopt_pre_release_tracker(
                    run_dir,
                    expected_run_id="2026-09-08-pipeline-rebuild-v2",
                    expected_revision=7,
                    expected_sha256=digest,
                    adoption_id="adopt-example-r2",
                    active_fixers={},
                )
                first = (run_dir / "progress.md").read_bytes()
                replay = pipeline_state.adopt_pre_release_tracker(
                    run_dir,
                    expected_run_id="2026-09-08-pipeline-rebuild-v2",
                    expected_revision=7,
                    expected_sha256=digest,
                    adoption_id="adopt-example-r2",
                    active_fixers={},
                )
            self.assertEqual(adopted.revision, 8)
            self.assertEqual(dict(adopted.run_fields)["tracker_format"], "2")
            self.assertEqual(replay, adopted)
            self.assertEqual((run_dir / "progress.md").read_bytes(), first)
            self.assertTrue((run_dir / "agent-output/adopt-example-r2-receipt.md").is_file())
            with self.assertRaises((SchemaError, TransitionError)):
                pipeline_state.adopt_pre_release_tracker(
                    run_dir,
                    expected_run_id="2026-09-08-pipeline-rebuild-v2",
                    expected_revision=7,
                    expected_sha256="b" * 64,
                    adoption_id="conflicting-adoption",
                    active_fixers={},
                )

    def test_adoption_pre_replacement_failure_preserves_old_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "2026-09-08-pipeline-rebuild-v2"
            run_dir.mkdir()
            source = (FIXTURES / "pre-adoption-v2-progress.md").read_bytes()
            (run_dir / "progress.md").write_bytes(source)
            supported = pipeline_state.FilesystemInfo("supported-local", "ext4", "a" * 64)
            with mock.patch.object(pipeline_state, "classify_filesystem", return_value=supported), mock.patch.object(
                pipeline_state, "_sync_file", side_effect=OSError("injected before replace")
            ):
                with self.assertRaises(TrackerWriteError):
                    pipeline_state.adopt_pre_release_tracker(
                        run_dir,
                        expected_run_id="2026-09-08-pipeline-rebuild-v2",
                        expected_revision=7,
                        expected_sha256=hashlib.sha256(source).hexdigest(),
                        adoption_id="adopt-failure",
                        active_fixers={},
                    )
            self.assertEqual((run_dir / "progress.md").read_bytes(), source)

    def test_adoption_post_replace_uncertainty_reconciles_without_second_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "2026-09-08-pipeline-rebuild-v2"
            run_dir.mkdir()
            source = (FIXTURES / "pre-adoption-v2-progress.md").read_bytes()
            (run_dir / "progress.md").write_bytes(source)
            digest = hashlib.sha256(source).hexdigest()
            supported = pipeline_state.FilesystemInfo("supported-local", "ext4", "a" * 64)
            with mock.patch.object(pipeline_state, "classify_filesystem", return_value=supported), mock.patch.object(
                pipeline_state, "_sync_directory", side_effect=[None, OSError("after replace")]
            ):
                with self.assertRaises(UpdateOutcomeUncertain) as caught:
                    pipeline_state.adopt_pre_release_tracker(
                        run_dir,
                        expected_run_id="2026-09-08-pipeline-rebuild-v2", expected_revision=7,
                        expected_sha256=digest, adoption_id="adopt-uncertain",
                        active_fixers={},
                    )
            applied = caught.exception.tracker
            self.assertIsNotNone(applied)
            self.assertEqual(applied.revision, 8)
            first = (run_dir / "progress.md").read_bytes()
            with mock.patch.object(pipeline_state, "classify_filesystem", return_value=supported):
                replay = pipeline_state.adopt_pre_release_tracker(
                    run_dir,
                    expected_run_id="2026-09-08-pipeline-rebuild-v2", expected_revision=7,
                    expected_sha256=digest, adoption_id="adopt-uncertain",
                    active_fixers={},
                )
            self.assertEqual(replay.revision, 8)
            self.assertEqual((run_dir / "progress.md").read_bytes(), first)

    def test_old_pre_adoption_format_is_not_accepted_by_ordinary_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            run_dir.mkdir()
            source = (FIXTURES / "pre-adoption-v2-progress.md").read_bytes()
            (run_dir / "progress.md").write_bytes(source)
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(SchemaError):
                validate_run(run_dir)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_unknown_filesystem_requires_fingerprint_bound_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = InitializationAndSchemaSafetyTest()
            artifacts, _ = helper.inputs(root)
            decisions = root / "decisions.md"
            artifacts["decisions"] = str(decisions)
            unknown = pipeline_state.FilesystemInfo("unknown", "mysteryfs", "c" * 64)
            run_dir = root / "unknown-run"
            with mock.patch.object(pipeline_state, "classify_filesystem", return_value=unknown):
                with self.assertRaises(pipeline_state.FilesystemSuitabilityError):
                    helper.initialize(run_dir, artifacts)
                self.assertFalse(run_dir.exists())
                before = decisions.read_bytes() if decisions.exists() else None
                with self.assertRaises(pipeline_state.FilesystemSuitabilityError):
                    initialize_run(
                        run_dir,
                        run_id="2026-09-08-init-test",
                        base_commit="8348959d1b201a873c68512642a0eb8e5754eaa8",
                        target_branch="feat/init-test", worker_limit=3, artifacts=artifacts,
                        approved_existing=(), filesystem_acknowledgement="D-900@" + "c" * 64,
                    )
                self.assertFalse(run_dir.exists())
                self.assertEqual(decisions.read_bytes() if decisions.exists() else None, before)
                decisions.write_text(
                    "# Decisions\n\n## D-900 — Filesystem authority\n\n"
                    "- **Question:** May this run use the detected unknown filesystem?\n"
                    "- **Answer:** Do not authorize use of mysteryfs for fingerprint " + "c" * 64 + ".\n"
                    "- **Scope:** Run 2026-09-08-init-test on fingerprint " + "c" * 64 + ".\n"
                    "- **Status:** Resolved.\n",
                    encoding="utf-8",
                )
                with self.assertRaises(pipeline_state.FilesystemSuitabilityError):
                    initialize_run(
                        run_dir, run_id="2026-09-08-init-test",
                        base_commit="8348959d1b201a873c68512642a0eb8e5754eaa8",
                        target_branch="feat/init-test", worker_limit=3, artifacts=artifacts,
                        approved_existing=(), filesystem_acknowledgement="D-900@" + "c" * 64,
                    )
                self.assertFalse(run_dir.exists())
                decisions.write_text(
                    "# Decisions\n\n## D-900 — Filesystem authority\n\n"
                    "- **Question:** May this run use the detected unknown filesystem?\n"
                    "- **Answer:** Refuse this filesystem; use the existing configuration for mysteryfs.\n"
                    "- **Scope:** Run 2026-09-08-init-test on fingerprint " + "c" * 64 + ".\n"
                    "- **Status:** Resolved.\n",
                    encoding="utf-8",
                )
                counterexample_bytes = decisions.read_bytes()
                with self.assertRaises(pipeline_state.FilesystemSuitabilityError):
                    initialize_run(
                        run_dir, run_id="2026-09-08-init-test",
                        base_commit="8348959d1b201a873c68512642a0eb8e5754eaa8",
                        target_branch="feat/init-test", worker_limit=3, artifacts=artifacts,
                        approved_existing=(), filesystem_acknowledgement="D-900@" + "c" * 64,
                    )
                self.assertFalse(run_dir.exists())
                self.assertEqual(decisions.read_bytes(), counterexample_bytes)
                decisions.write_text(
                    "# Decisions\n\n## D-900 — Filesystem authority\n\n"
                    "- **Question:** May this run use the detected unknown filesystem?\n"
                    "- **Answer:** Do not authorize mysteryfs; use the recorded refusal for fingerprint " + "c" * 64 + ".\n"
                    "- **Scope:** Run 2026-09-08-init-test on fingerprint " + "c" * 64 + ".\n"
                    "- **Status:** Resolved.\n",
                    encoding="utf-8",
                )
                with self.assertRaises(pipeline_state.FilesystemSuitabilityError):
                    initialize_run(
                        run_dir, run_id="2026-09-08-init-test",
                        base_commit="8348959d1b201a873c68512642a0eb8e5754eaa8",
                        target_branch="feat/init-test", worker_limit=3, artifacts=artifacts,
                        approved_existing=(), filesystem_acknowledgement="D-900@" + "c" * 64,
                    )
                self.assertFalse(run_dir.exists())
                decisions.write_text(
                    "# Decisions\n\n## D-900 — Filesystem authority\n\n"
                    "- **Question:** May this run use the detected unknown filesystem?\n"
                    "- **Answer:** Authorize mysteryfs for fingerprint " + "c" * 64 + ".\n"
                    "- **Decision action:** filesystem.authorize\n"
                    "- **Scope:** Run 2026-09-08-init-test on fingerprint " + "c" * 64 + ".\n"
                    "- **Status:** Resolved.\n\n"
                    "## D-901 — Conflicting filesystem authority\n\n"
                    "- **Question:** May this run use the detected unknown filesystem?\n"
                    "- **Answer:** Reject mysteryfs for fingerprint " + "c" * 64 + ".\n"
                    "- **Scope:** Fingerprint " + "c" * 64 + " for run 2026-09-08-init-test.\n"
                    "- **Status:** Resolved.\n",
                    encoding="utf-8",
                )
                with self.assertRaises(pipeline_state.FilesystemSuitabilityError):
                    initialize_run(
                        run_dir, run_id="2026-09-08-init-test",
                        base_commit="8348959d1b201a873c68512642a0eb8e5754eaa8",
                        target_branch="feat/init-test", worker_limit=3, artifacts=artifacts,
                        approved_existing=(), filesystem_acknowledgement="D-900@" + "c" * 64,
                    )
                self.assertFalse(run_dir.exists())
                decisions.write_text(
                    "# Decisions\n\n## D-900 — Filesystem authority\n\n"
                    "- **Question:** May this run use the detected unknown filesystem?\n"
                    "- **Answer:** Authorize mysteryfs for fingerprint " + "c" * 64 + ".\n"
                    "- **Decision action:** filesystem.authorize\n"
                    "- **Scope:** Run 2026-09-08-init-test on fingerprint " + "c" * 64 + ".\n"
                    "- **Status:** Resolved.\n",
                    encoding="utf-8",
                )
                initialized = initialize_run(
                    run_dir,
                    run_id="2026-09-08-init-test",
                    base_commit="8348959d1b201a873c68512642a0eb8e5754eaa8",
                    target_branch="feat/init-test", worker_limit=3, artifacts=artifacts,
                    approved_existing=(), filesystem_acknowledgement="D-900@" + "c" * 64,
                )
            self.assertEqual(dict(initialized.run_fields)["filesystem_ack"], "D-900@" + "c" * 64)

    def test_direct_task_start_requires_fresh_bound_runtime_capacity(self):
        helper = TaskTransitionTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = helper.make_git_repo(root)
            plan = helper.source_plan(repo)
            decisions = helper.decisions(repo, "# Decisions\n")
            run_dir = helper.initialize(repo, plan, decisions, base)
            before = (run_dir / "progress.md").read_bytes()

            with self.assertRaises(TransitionError):
                pipeline_state.start_task(
                    run_dir, task_id="PX-01", owner="worker-a", attempt="attempt-1",
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            with pipeline_state.bind_runtime_capacity_provider(run_dir, lambda _run, _tracker: 3):
                started = pipeline_state.start_task(
                    run_dir, task_id="PX-01", owner="worker-a", attempt="attempt-1",
                )
            self.assertEqual(next(task.state for task in started.tasks if task.id == "PX-01"), "[~]")

    def test_stale_readiness_and_invalid_capacity_provider_cannot_authorize_start(self):
        helper = SchedulerReadinessTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = helper.write_plan(
                root,
                (helper.task("PS-01", batch="a"), helper.task("PS-02", batch="b")),
            )
            run_dir = helper.initialize(root, plan, worker_limit=3)
            self.assertEqual(
                tuple(task.id for task in next_eligible_actions(run_dir, plan, capacity=3)),
                ("PS-01", "PS-02"),
            )
            for provider in (
                lambda _run, _tracker: 2,
                lambda _run, _tracker: None,
                lambda _run, _tracker: (_ for _ in ()).throw(RuntimeError("probe failed")),
            ):
                before = (run_dir / "progress.md").read_bytes()
                with pipeline_state.bind_runtime_capacity_provider(run_dir, provider):
                    with self.assertRaises(TransitionError):
                        pipeline_state.start_task(
                            run_dir, task_id="PS-01", owner="worker-a", attempt="attempt-1",
                        )
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            with pipeline_state.bind_runtime_capacity_provider(run_dir, lambda _run, _tracker: 3):
                first = pipeline_state.start_task(
                    run_dir, task_id="PS-01", owner="worker-a", attempt="attempt-1",
                )
                second = pipeline_state.start_task(
                    run_dir, task_id="PS-02", owner="worker-a", attempt="attempt-2",
                )
            self.assertEqual(pipeline_state._active_worker_ids(first), {"worker-a"})
            self.assertEqual(pipeline_state._active_worker_ids(second), {"worker-a"})

    def test_direct_blocked_resume_requires_capacity_but_exact_replay_does_not(self):
        helper = TaskTransitionTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, base = helper.make_git_repo(root)
            plan = helper.source_plan(repo)
            decisions = helper.decisions(repo, helper.resolved_decision())
            run_dir = helper.initialize(repo, plan, decisions, base)
            with pipeline_state.bind_runtime_capacity_provider(run_dir, lambda _run, _tracker: 3):
                pipeline_state.start_task(
                    run_dir, task_id="PX-01", owner="worker-a", attempt="attempt-1",
                )
            record_task_question(
                run_dir, task_id="PX-01", attempt="attempt-1",
                question_or_block_ref="D-100", reason="needs decision",
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                pipeline_state.resume_task(
                    run_dir, task_id="PX-01", prior_attempt="attempt-1",
                    new_owner="worker-a", new_attempt="attempt-2", decision_ref="D-100",
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)
            with pipeline_state.bind_runtime_capacity_provider(run_dir, lambda _run, _tracker: 3):
                resumed = pipeline_state.resume_task(
                    run_dir, task_id="PX-01", prior_attempt="attempt-1",
                    new_owner="worker-a", new_attempt="attempt-2", decision_ref="D-100",
                )
            revision = resumed.revision
            replay = pipeline_state.resume_task(
                run_dir, task_id="PX-01", prior_attempt="attempt-1",
                new_owner="worker-a", new_attempt="attempt-2", decision_ref="D-100",
            )
            self.assertEqual(replay.revision, revision)

    def test_gate_evaluation_rejects_nonexistent_verification_evidence(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(root)
            record_phase_verification(
                run_dir, phase_id="01", head=head,
                commands=("suite",), evidence=(_verification_evidence(root, head),),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=head, head=head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            report = helper.write_report(
                root, "review.md", gate="phase-01", assignment="reviewer-1",
                base=head, head=head,
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=root / "findings.md",
                    report_paths=(report,),
                    verification=(f"missing-verification.md@{head}",),
                    rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_verification_digest_and_authoritative_record_must_match(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(root)
            evidence = _verification_evidence(root, head)
            evidence_path = root / evidence.split("#sha256=", 1)[0]
            evidence_path.write_text("tampered\n", encoding="utf-8")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                record_phase_verification(
                    run_dir, phase_id="01", head=head,
                    commands=("suite",), evidence=(evidence,),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            recorded = _verification_evidence(root, head, "recorded")
            record_phase_verification(
                run_dir, phase_id="01", head=head,
                commands=("suite",), evidence=(recorded,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=head, head=head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            report = helper.write_report(
                root, "review.md", gate="phase-01", assignment="reviewer-1",
                base=head, head=head,
            )
            alternate = _verification_evidence(root, head, "alternate")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=root / "findings.md",
                    report_paths=(report,), verification=(alternate,), rereview_paths=(),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_remediation_release_rejects_unchanged_review_head(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(root)
            record_phase_verification(
                run_dir, phase_id="01", head=head,
                commands=("suite",), evidence=(_verification_evidence(root, head),),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=head, head=head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            report = helper.write_report(
                root, "review.md", gate="phase-01", assignment="reviewer-1",
                base=head, head=head, findings="F-001",
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | phase-01 | Critical | Open | - | review.md | - | - |\n",
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(report,), verification=(_verification_evidence(root, head),),
                rereview_paths=(),
            )
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text("# Fix plan\n", encoding="utf-8")
            start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-001",), fix_plan=str(fix_plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                record_remediation_fixes(
                    run_dir, gate_id="phase-01", round_number=1,
                    fix_head=head, commits=(head,),
                    verification=(_remediation_evidence(
                        root, head, "phase-01", 1, "unchanged-head"
                    ),), capacity=3, repo_dir=root,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_remediation_targets_only_current_blocking_findings(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(root)
            record_phase_verification(
                run_dir, phase_id="01", head=head,
                commands=("suite",), evidence=(_verification_evidence(root, head),),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=head, head=head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            report = helper.write_report(
                root, "review.md", gate="phase-01", assignment="reviewer-1",
                base=head, head=head, findings="F-001,F-002",
            )
            (root / "decisions.md").write_text(
                "# Decisions\n\n## D-200 — Defer F-002\n\n"
                "- **Question:** Should F-002 be fixed in this phase?\n"
                "- **Answer:** Defer F-002 with its recorded impact.\n"
                "- **Decision action:** review.resolve-question\n"
                "- **Scope:** phase-01 finding F-002 only.\n"
                "- **Status:** Resolved.\n",
                encoding="utf-8",
            )
            disposition = root / "minor-f-002.md"
            disposition.write_text(
                "Finding: F-002\nImpact: Optional cleanup remains.\n"
                "Reason: No approved requirement is affected.\nAuthority: D-200\n",
                encoding="utf-8",
            )
            disposition_ref = pipeline_state._digest_bound_reference(run_dir, disposition)
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | phase-01 | Important | Open | - | review.md | - | - |\n"
                f"| F-002 | phase-01 | Minor | Resolved | Deferred | {disposition_ref} | - | - |\n",
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(report,), verification=(_verification_evidence(root, head),),
                rereview_paths=(),
            )
            fix_plan = root / "fix-plan.md"
            fix_plan.write_text("# Fix plan\n", encoding="utf-8")
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                start_remediation_round(
                    run_dir, gate_id="phase-01", round_number=1,
                    finding_ids=("F-001", "F-002"), fix_plan=str(fix_plan),
                    fixer_assignments=("fixer-1",), capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_reintroduced_blocker_stops_the_same_gate_as_oscillation(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, original_head = helper.make_run(root)
            (root / "implementation.txt").write_text("implemented\n", encoding="utf-8")
            helper.git(root, "add", "implementation.txt")
            helper.git(root, "commit", "-qm", "initial implementation")
            reviewed_head = helper.git(root, "rev-parse", "HEAD")
            helper.git(root, "branch", "-f", "target", reviewed_head)
            phase_evidence = _verification_evidence(root, reviewed_head)
            record_phase_verification(
                run_dir, phase_id="01", head=reviewed_head,
                commands=("suite",), evidence=(phase_evidence,),
            )
            open_review_gate(
                run_dir, gate_id="phase-01", base=original_head, head=reviewed_head,
                reviewer_assignments=("reviewer-1",), capacity=3,
            )
            initial = helper.write_report(
                root, "review.md", gate="phase-01", assignment="reviewer-1",
                base=original_head, head=reviewed_head, findings="F-001,F-002",
            )
            findings = root / "findings.md"
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | phase-01 | Important | Open | - | review.md | - | - |\n"
                "| F-002 | phase-01 | Important | Open | - | review.md | - | - |\n",
                encoding="utf-8",
            )
            evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(phase_evidence,), rereview_paths=(),
            )
            plan = root / "fix-plan.md"
            plan.write_text("# Fix plan\n", encoding="utf-8")
            start_remediation_round(
                run_dir, gate_id="phase-01", round_number=1,
                finding_ids=("F-001", "F-002"), fix_plan=str(plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            (root / "fix-one.txt").write_text("fix one\n", encoding="utf-8")
            helper.git(root, "add", "fix-one.txt")
            helper.git(root, "commit", "-qm", "fix one")
            fix_one = helper.git(root, "rev-parse", "HEAD")
            helper.git(root, "branch", "-f", "target", fix_one)
            fix_one_evidence = _remediation_evidence(
                root, fix_one, "phase-01", 1, "fix-one"
            )
            record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=1, fix_head=fix_one,
                commits=(fix_one,), verification=(fix_one_evidence,),
                capacity=3, repo_dir=root,
            )
            rereview_one = helper.write_report(
                root, "rereview-one.md", gate="phase-01", assignment="reviewer-1",
                base=reviewed_head, head=fix_one, findings="F-001,F-002",
                outcomes={"F-001": "Resolved", "F-002": "Open"},
            )
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-001 | phase-01 | Important | Resolved | Fixed | {fix_one_evidence} | {fix_one} | {rereview_one} |\n"
                "| F-002 | phase-01 | Important | Open | - | review.md | - | - |\n",
                encoding="utf-8",
            )
            first = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(fix_one_evidence,),
                rereview_paths=(rereview_one,),
            )
            first_round = next(row for row in first.remediation if row.gate == "phase-01" and row.round_number == 1)
            self.assertIn("remaining-blockers=F-002", first_round.verification)
            self.assertEqual(next(gate.questions for gate in first.gates if gate.id == "phase-01"), "-")

            start_remediation_round(
                run_dir, gate_id="phase-01", round_number=2,
                finding_ids=("F-002",), fix_plan=str(plan),
                fixer_assignments=("fixer-1",), capacity=3,
            )
            (root / "fix-two.txt").write_text("fix two\n", encoding="utf-8")
            helper.git(root, "add", "fix-two.txt")
            helper.git(root, "commit", "-qm", "fix two")
            fix_two = helper.git(root, "rev-parse", "HEAD")
            helper.git(root, "branch", "-f", "target", fix_two)
            fix_two_evidence = _remediation_evidence(
                root, fix_two, "phase-01", 2, "fix-two"
            )
            record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=2, fix_head=fix_two,
                commits=(fix_two,), verification=(fix_two_evidence,),
                capacity=3, repo_dir=root,
            )
            rereview_two = helper.write_report(
                root, "rereview-two.md", gate="phase-01", assignment="reviewer-1",
                base=fix_one, head=fix_two, findings="F-001,F-002",
                outcomes={"F-001": "Resolved", "F-002": "Resolved"},
            )
            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-001 | phase-01 | Important | Resolved | Fixed | {fix_one_evidence} | {fix_one} | {rereview_one} |\n"
                f"| F-002 | phase-01 | Important | Resolved | Fixed | {fix_one_evidence} | {fix_one} | {rereview_one} |\n",
                encoding="utf-8",
            )
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=findings,
                    report_paths=(initial,), verification=(fix_two_evidence,),
                    rereview_paths=(rereview_two,),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                f"| F-001 | phase-01 | Important | Resolved | Fixed | {fix_one_evidence} | {fix_one} | {rereview_one} |\n"
                f"| F-002 | phase-01 | Important | Resolved | Fixed | {fix_two_evidence} | {fix_one} | {rereview_two} |\n",
                encoding="utf-8",
            )
            with self.assertRaises(TransitionError):
                evaluate_and_close_review_gate(
                    run_dir, gate_id="phase-01", findings_path=findings,
                    report_paths=(initial,), verification=(fix_two_evidence,),
                    rereview_paths=(rereview_two,),
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            findings.write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| F-001 | phase-01 | Important | Open | - | rereview-two.md | - | - |\n"
                f"| F-002 | phase-01 | Important | Resolved | Fixed | {fix_two_evidence} | {fix_two} | {rereview_two} |\n",
                encoding="utf-8",
            )
            rereview_two = helper.write_report(
                root, "rereview-two.md", gate="phase-01", assignment="reviewer-1",
                base=fix_one, head=fix_two, findings="F-001,F-002",
                outcomes={"F-001": "Open", "F-002": "Resolved"},
            )
            stopped = evaluate_and_close_review_gate(
                run_dir, gate_id="phase-01", findings_path=findings,
                report_paths=(initial,), verification=(fix_two_evidence,),
                rereview_paths=(rereview_two,),
            )
            gate = next(gate for gate in stopped.gates if gate.id == "phase-01")
            self.assertEqual((gate.state, gate.questions), ("blocked", "remediation-oscillation-round-2"))
            self.assertEqual(gate.base, original_head)
            self.assertEqual(
                gate.reports,
                pipeline_state._digest_bound_reference(run_dir, initial),
            )

    def test_platform_classifier_paths_are_explicitly_selected_in_simulation(self):
        for system, helper_name, fs_type in (
            ("Darwin", "_macos_filesystem", "apfs"),
            ("Windows", "_windows_filesystem", "ntfs"),
        ):
            with self.subTest(system=system), mock.patch.object(pipeline_state.platform, "system", return_value=system), mock.patch.object(
                pipeline_state, helper_name, return_value=(fs_type, "d" * 64)
            ):
                info = pipeline_state.classify_filesystem(Path("/tmp"))
                self.assertEqual((info.classification, info.fs_type), ("supported-local", fs_type))

    def test_macos_probe_reads_filesystem_metadata_not_stat_file_type(self):
        """The macOS probe must parse disk metadata rather than stat's %T file kind."""
        mount = subprocess.CompletedProcess(
            args=(), returncode=0, stdout="/Volumes/Data\n", stderr=""
        )
        disk = subprocess.CompletedProcess(
            args=(), returncode=0,
            stdout=plistlib.dumps({
                "FilesystemType": "apfs",
                "MountPoint": "/Volumes/Data",
                "DeviceIdentifier": "disk3s1",
            }),
            stderr=b"",
        )
        with mock.patch.object(pipeline_state, "_existing_path", return_value=Path("/Volumes/Data/project")), mock.patch.object(
            pipeline_state.subprocess, "run", side_effect=(mount, disk)
        ) as run, mock.patch.object(
            pipeline_state.os, "stat", return_value=mock.Mock(st_dev=42)
        ):
            fs_type, fingerprint = pipeline_state._macos_filesystem(Path("/project"))
        self.assertEqual(fs_type, "apfs")
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][:3], ("/usr/bin/stat", "-f", "%m"))
        self.assertEqual(run.call_args_list[1].args[0], ("/usr/sbin/diskutil", "info", "-plist", "/Volumes/Data"))

    def test_gate_and_fixer_reservations_share_the_global_worker_ceiling(self):
        helper = PhaseGateAndRemediationTest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _, head = helper.make_run(root)
            record_phase_verification(run_dir, phase_id="01", head=head, commands=("suite",), evidence=(_verification_evidence(root, head),))
            before = (run_dir / "progress.md").read_bytes()
            with pipeline_state.bind_runtime_capacity_provider(
                run_dir, lambda _run, _tracker: 0
            ), self.assertRaises(TransitionError):
                pipeline_state.open_review_gate(
                    run_dir, gate_id="phase-01", base=head, head=head,
                    reviewer_assignments=("reviewer-1",), capacity=0,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)


class ActiveRoundOutcomeReconciliationTest(unittest.TestCase):
    REMAINING = (
        "P1-GATE-002",
        "P1-GATE-004",
        "P1-GATE-007",
        "P1-GATE-008",
    )

    def make_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        helper = PhaseGateAndRemediationTest()
        helper.git(root, "init", "-q")
        helper.git(root, "config", "user.email", "pipeline@example.invalid")
        helper.git(root, "config", "user.name", "Pipeline Test")
        (root / "base.txt").write_text("base\n", encoding="utf-8")
        helper.git(root, "add", "base.txt")
        helper.git(root, "commit", "-qm", "base")
        head = helper.git(root, "rev-parse", "HEAD")
        helper.git(root, "branch", "target")
        plan = root / "phase-01.md"
        plan.write_text(
            "# Phase 1\n\n"
            "<!-- pipeline-v2-phase: id=01; deps=none; review_gate=required; review_reason=State risk. -->\n"
            "<!-- pipeline-v2-phase-suite: id=01; commands=[\"suite\"] -->\n\n"
            "### P1-01 — State\n"
            "<!-- pipeline-v2-task: id=P1-01; deps=none; kind=source; batch=state; order=1; write_scope=file:state.py; outputs=none -->\n"
            "<!-- pipeline-v2-task-suite: id=P1-01; commands=[\"task-suite-P1-01\"] -->\n",
            encoding="utf-8",
        )
        (root / "master.md").write_text(
            f"# Master\n\n- **Detailed plan:** `{plan}`\n", encoding="utf-8"
        )
        decisions = root / "decisions.md"
        decisions.write_text(
            "# Decisions\n\n"
            "## D-019 — Exact active-run reconciliation\n\n"
            "- **Answer:** Authorize the exact run 2026-09-08-pipeline-rebuild-v2, gate phase-01, Round 1 repair with blockers P1-GATE-002, P1-GATE-004, P1-GATE-007, and P1-GATE-008.\n"
            "- **Scope:** Exactly run 2026-09-08-pipeline-rebuild-v2 gate phase-01 Round 1.\n"
            "- **Status:** Resolved.\n",
            encoding="utf-8",
        )
        findings = root / "findings.md"
        findings.write_text(
            "<!-- pipeline-findings/v2 -->\n"
            "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n",
            encoding="utf-8",
        )
        run_dir = root / "2026-09-08-pipeline-rebuild-v2"
        initialize_run(
            run_dir,
            run_id="2026-09-08-pipeline-rebuild-v2",
            base_commit=head,
            target_branch="target",
            worker_limit=3,
            artifacts={
                "spec": "spec.md",
                "master_plan": "master.md",
                "phase_plans": str(plan),
                "decisions": str(decisions),
                "findings": str(findings),
            },
            approved_existing=(),
        )
        report = root / "round-one-rereview.md"
        report.write_text(
            "<!-- pipeline-review-report/v2 -->\n"
            "| Field | Value |\n"
            "| --- | --- |\n"
            "| gate | phase-01 |\n"
            "| assignment | reviewer-1 |\n"
            f"| base | {head} |\n"
            f"| head | {head} |\n"
            "| findings | P1-GATE-001,P1-GATE-002,P1-GATE-003,P1-GATE-004,P1-GATE-005,P1-GATE-006,P1-GATE-007,P1-GATE-008,P1-GATE-009 |\n",
            encoding="utf-8",
        )
        notes = root / "round-one-rereview-notes.md"
        notes.write_text(
            "# Round one\n\n## Finding results\n\n"
            "| Finding | Result | Evidence |\n"
            "| --- | --- | --- |\n"
            "| P1-GATE-001 | Resolved | evidence |\n"
            "| P1-GATE-002 | Open — Critical | evidence |\n"
            "| P1-GATE-003 | Resolved | evidence |\n"
            "| P1-GATE-004 | Open — Important | evidence |\n"
            "| P1-GATE-005 | Resolved | evidence |\n"
            "| P1-GATE-006 | Resolved | evidence |\n"
            "| P1-GATE-007 | Open — Important | evidence |\n"
            "| P1-GATE-008 | Open — Important | evidence |\n"
            "| P1-GATE-009 | Resolved | evidence |\n",
            encoding="utf-8",
        )
        tracker = parse_tracker((run_dir / "progress.md").read_text(encoding="utf-8"))
        round_one = dataclasses.replace(
            next(row for row in tracker.remediation if row.gate == "phase-01"),
            state="complete",
            released_fixers="fixer-1",
            findings=",".join(f"P1-GATE-{number:03d}" for number in range(1, 10)),
            fix_plan="fix-plan-one.md",
            commits=head,
            verification="verification-one.md",
            re_review=str(report),
        )
        round_two = dataclasses.replace(
            round_one,
            round_number=2,
            state="re_reviewing",
            findings=",".join(self.REMAINING),
            fix_plan="fix-plan-two.md",
            commits="b" * 40,
            verification="verification-two.md",
            re_review="-",
        )
        gate = next(gate for gate in tracker.gates if gate.id == "phase-01")
        report_digest = hashlib.sha256(report.read_bytes()).hexdigest()
        sealed_findings = ",".join(
            f"P1-GATE-{number:03d}@Important@sha256={report_digest}"
            for number in range(1, 10)
        )
        tracker = dataclasses.replace(
            tracker,
            run_fields=tuple(
                (key, "32" if key == "revision" else "fixture-round-two" if key == "last_transition" else value)
                for key, value in tracker.run_fields
            ),
            gates=tuple(
                dataclasses.replace(
                    gate,
                    state="re_reviewing",
                    base=head,
                    head=head,
                    assignments="reviewer-1",
                    findings=sealed_findings,
                )
                if gate.id == "phase-01" else gate
                for gate in tracker.gates
            ),
            remediation=(round_one, *tuple(row for row in tracker.remediation if row.gate != "phase-01"), round_two),
        )
        (run_dir / "progress.md").write_text(render_tracker(tracker), encoding="utf-8")
        return run_dir, report, notes

    def reconcile(self, run_dir: Path, report: Path, notes: Path, *, digest: str | None = None):
        progress = run_dir / "progress.md"
        return pipeline_state.reconcile_active_rebuild_round_one_outcome(
            run_dir,
            expected_revision=32,
            expected_tracker_sha256=digest or hashlib.sha256(progress.read_bytes()).hexdigest(),
            decision_ref="D-019",
            report_path=report,
            notes_path=notes,
        )

    def test_exact_evidence_backfills_only_round_one_and_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, report, notes = self.make_fixture(Path(directory))
            before = pipeline_state._parse_tracker_for_exact_reconciliation(
                (run_dir / "progress.md").read_text(encoding="utf-8")
            )
            source_digest = hashlib.sha256((run_dir / "progress.md").read_bytes()).hexdigest()

            reconciled = self.reconcile(run_dir, report, notes, digest=source_digest)

            round_one = next(row for row in reconciled.remediation if row.gate == "phase-01" and row.round_number == 1)
            self.assertIn("remaining-blockers=" + "+".join(self.REMAINING), round_one.verification)
            self.assertIn("round-outcome-reconciliation=D-019@", round_one.verification)
            self.assertEqual(reconciled.revision, 33)
            self.assertEqual(reconciled.tasks, before.tasks)
            self.assertEqual(reconciled.gates, before.gates)
            self.assertEqual(
                next(row for row in reconciled.remediation if row.gate == "phase-01" and row.round_number == 2),
                next(row for row in before.remediation if row.gate == "phase-01" and row.round_number == 2),
            )
            after = (run_dir / "progress.md").read_bytes()
            replayed = self.reconcile(run_dir, report, notes, digest=source_digest)
            self.assertEqual(replayed, reconciled)
            self.assertEqual((run_dir / "progress.md").read_bytes(), after)

    def test_changed_evidence_or_stale_predecessor_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, report, notes = self.make_fixture(Path(directory))
            before = (run_dir / "progress.md").read_bytes()
            notes.write_text(notes.read_text(encoding="utf-8").replace("P1-GATE-008 | Open", "P1-GATE-008 | Resolved"), encoding="utf-8")
            with self.assertRaises(TransitionError):
                self.reconcile(run_dir, report, notes)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            notes.write_text(notes.read_text(encoding="utf-8").replace("P1-GATE-008 | Resolved", "P1-GATE-008 | Open"), encoding="utf-8")
            with self.assertRaises(TransitionError):
                pipeline_state.reconcile_active_rebuild_round_one_outcome(
                    run_dir,
                    expected_revision=31,
                    expected_tracker_sha256=hashlib.sha256(before).hexdigest(),
                    decision_ref="D-019",
                    report_path=report,
                    notes_path=notes,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_ordinary_validation_rejects_missing_completed_round_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir, _, _ = self.make_fixture(Path(directory))
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(SchemaError):
                validate_run(run_dir)
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)


class RemediationExtensionTest(unittest.TestCase):
    RUN_ID = "2026-09-08-pipeline-rebuild-v2"
    FINDINGS = ("P1-GATE-002", "P1-GATE-004", "P1-GATE-008", "P1-GATE-010")
    ROUND_FIVE_FINDINGS = ("P1-GATE-002", "P1-GATE-008", "P1-GATE-010", "P1-GATE-011")

    def make_fixture(self, root: Path) -> tuple[Path, Path]:
        helper = PhaseGateAndRemediationTest()
        run_dir, _, head = helper.make_run(root)
        phase_evidence = _verification_evidence(root, head)
        record_phase_verification(
            run_dir, phase_id="01", head=head,
            commands=("suite",), evidence=(phase_evidence,),
        )
        open_review_gate(
            run_dir, gate_id="phase-01", base=head, head=head,
            reviewer_assignments=("reviewer-1",), capacity=3,
        )
        report = helper.write_report(
            root, "review.md", gate="phase-01", assignment="reviewer-1",
            base=head, head=head, findings=",".join(self.FINDINGS),
        )
        (root / "findings.md").write_text(
            "<!-- pipeline-findings/v2 -->\n"
            "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            + "".join(
                f"| {finding} | phase-01 | {'Critical' if finding in {'P1-GATE-002', 'P1-GATE-010'} else 'Important'} | Open | - | review.md | - | - |\n"
                for finding in self.FINDINGS
            ),
            encoding="utf-8",
        )
        tracker = evaluate_and_close_review_gate(
            run_dir, gate_id="phase-01", findings_path=root / "findings.md",
            report_paths=(report,), verification=(phase_evidence,), rereview_paths=(),
        )
        tracker = dataclasses.replace(
            tracker,
            run_fields=tuple(
                (key, self.RUN_ID if key == "run_id" else "37" if key == "revision" else value)
                for key, value in tracker.run_fields
            ),
        )
        (root / "decisions.md").write_text(
            "# Decisions\n\n## D-021 — One finite extension\n\n"
            "- **Question:** May phase-01 receive one finite extension?\n"
            "- **Answer:** Authorize Round 4 only for phase-01 targeting P1-GATE-002, P1-GATE-004, P1-GATE-008, and P1-GATE-010.\n"
            "- **Decision action:** remediation.start-round\n"
            f"- **Authorized run:** {self.RUN_ID}\n"
            "- **Source revision:** 37\n"
            "- **Authorized gate:** phase-01\n"
            "- **Required state:** blocked\n"
            "- **Required question:** remediation-no-progress-round-3\n"
            "- **Predecessor decision:** D-006\n"
            "- **Authorized through round:** 4\n"
            "- **Authorized findings:** P1-GATE-002,P1-GATE-004,P1-GATE-008,P1-GATE-010\n"
            "- **Authority marker:** remediation-extension:phase-01:through-round-4\n"
            "- **Scope:** This run's phase-01 Round 4 only.\n"
            "- **Status:** Resolved.\n",
            encoding="utf-8",
        )
        first = next(row for row in tracker.remediation if row.gate == "phase-01")
        completed = tuple(
            dataclasses.replace(
                first,
                round_number=number,
                state="complete",
                released_fixers=f"fixer-{number}",
                findings=",".join(self.FINDINGS),
                fix_plan=f"fix-plan-{number}.md",
                commits=head,
                verification=f"verification-{number}@{head},remaining-blockers=" + "+".join(self.FINDINGS),
                re_review=f"rereview-{number}.md",
            )
            for number in range(1, 4)
        )
        tracker = dataclasses.replace(
            tracker,
            gates=tuple(
                dataclasses.replace(
                    gate,
                    state="blocked",
                    base=head,
                    head=head,
                    assignments="reviewer-1",
                    questions="remediation-no-progress-round-3",
                ) if gate.id == "phase-01" else gate
                for gate in tracker.gates
            ),
            remediation=completed + tuple(row for row in tracker.remediation if row.gate != "phase-01"),
        )
        (run_dir / "progress.md").write_text(render_tracker(tracker), encoding="utf-8")
        fix_plan = root / "fix-plan-4.md"
        fix_plan.write_text("# Round 4\n", encoding="utf-8")
        return run_dir, fix_plan

    def test_round_four_requires_exact_finite_authority_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, fix_plan = self.make_fixture(root)
            before = validate_run(run_dir)
            before_bytes = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                start_remediation_round(
                    run_dir, gate_id="phase-01", round_number=4,
                    finding_ids=self.FINDINGS, fix_plan=str(fix_plan),
                    fixer_assignments=("fixer-4",), capacity=3,
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before_bytes)

            decisions = root / "decisions.md"
            exact_decision = decisions.read_text(encoding="utf-8")
            decisions.write_text(
                exact_decision.replace(
                    f"- **Authorized run:** {self.RUN_ID}",
                    "- **Authorized run:** another-run",
                ),
                encoding="utf-8",
            )
            with self.assertRaises(TransitionError):
                start_remediation_round(
                    run_dir, gate_id="phase-01", round_number=4,
                    finding_ids=self.FINDINGS, fix_plan=str(fix_plan),
                    fixer_assignments=("fixer-4",), capacity=3,
                    extension_decision_ref="D-021",
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before_bytes)
            decisions.write_text(exact_decision, encoding="utf-8")

            started = start_remediation_round(
                run_dir, gate_id="phase-01", round_number=4,
                finding_ids=self.FINDINGS, fix_plan=str(fix_plan),
                fixer_assignments=("fixer-4",), capacity=3,
                extension_decision_ref="D-021",
            )
            row = next(row for row in started.remediation if row.gate == "phase-01" and row.round_number == 4)
            self.assertEqual((row.state, row.verification), ("fixing", "extension-authority=D-021"))
            self.assertEqual(
                tuple(row for row in started.remediation if row.gate == "phase-01" and row.round_number < 4),
                tuple(row for row in before.remediation if row.gate == "phase-01"),
            )
            self.assertEqual(next(gate.questions for gate in started.gates if gate.id == "phase-01"), "-")
            after = (run_dir / "progress.md").read_bytes()
            replay = start_remediation_round(
                run_dir, gate_id="phase-01", round_number=4,
                finding_ids=self.FINDINGS, fix_plan=str(fix_plan),
                fixer_assignments=("fixer-4",), capacity=3,
                extension_decision_ref="D-021",
            )
            self.assertEqual(replay.revision, started.revision)
            self.assertEqual((run_dir / "progress.md").read_bytes(), after)
            with self.assertRaises(TransitionError):
                start_remediation_round(
                    run_dir, gate_id="phase-01", round_number=5,
                    finding_ids=self.FINDINGS, fix_plan=str(fix_plan),
                    fixer_assignments=("fixer-5",), capacity=3,
                    extension_decision_ref="D-021",
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), after)

            (root / "round-four-fix.txt").write_text("fixed\n", encoding="utf-8")
            helper = PhaseGateAndRemediationTest()
            helper.git(root, "add", "round-four-fix.txt")
            helper.git(root, "commit", "-qm", "round four fix")
            fix_head = helper.git(root, "rev-parse", "HEAD")
            helper.git(root, "branch", "-f", "target", fix_head)
            released = record_remediation_fixes(
                run_dir, gate_id="phase-01", round_number=4, fix_head=fix_head,
                commits=(fix_head,), verification=(_remediation_evidence(
                    root, fix_head, "phase-01", 4, "round-four", run_id=self.RUN_ID
                ),),
                capacity=3, repo_dir=root,
            )
            row = next(row for row in released.remediation if row.gate == "phase-01" and row.round_number == 4)
            self.assertEqual(row.state, "re_reviewing")
            self.assertIn("extension-authority=D-021", row.verification)

    def test_round_five_authority_is_bound_to_exact_run_revision_and_predecessor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir, _ = self.make_fixture(root)
            tracker = validate_run(run_dir)
            first = next(row for row in tracker.remediation if row.gate == "phase-01")
            gate = next(gate for gate in tracker.gates if gate.id == "phase-01")
            review_five = PhaseGateAndRemediationTest().write_report(
                root, "review-five.md", gate="phase-01", assignment="reviewer-1",
                base=gate.base, head=gate.head, findings=",".join(self.ROUND_FIVE_FINDINGS),
            )
            (root / "findings.md").write_text(
                "<!-- pipeline-findings/v2 -->\n"
                "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                + "".join(
                    f"| {finding} | phase-01 | {'Critical' if finding in {'P1-GATE-002', 'P1-GATE-010'} else 'Important'} | Open | - | review-five.md | - | - |\n"
                    for finding in self.ROUND_FIVE_FINDINGS
                ),
                encoding="utf-8",
            )
            rows = tuple(
                row for row in pipeline_state._parse_findings(root / "findings.md")
                if row[1] == "phase-01"
            )
            report_identities, origins = pipeline_state._sealed_review_package(
                run_dir, gate, (review_five,), rows,
            )
            rounds = tuple(
                dataclasses.replace(
                    first,
                    round_number=number,
                    state="complete",
                    released_fixers=f"fixer-{number}",
                    findings=",".join(self.ROUND_FIVE_FINDINGS),
                    fix_plan=f"fix-plan-{number}.md",
                    commits=next(gate.head for gate in tracker.gates if gate.id == "phase-01"),
                    verification=(
                        ("extension-authority=D-021," if number == 4 else "")
                        + f"verification-{number}@{next(gate.head for gate in tracker.gates if gate.id == 'phase-01')},"
                        + "remaining-blockers=" + "+".join(self.ROUND_FIVE_FINDINGS)
                    ),
                    re_review=f"rereview-{number}.md",
                )
                for number in range(1, 5)
            )
            tracker = dataclasses.replace(
                tracker,
                run_fields=tuple(
                    (key, "40" if key == "revision" else value)
                    for key, value in tracker.run_fields
                ),
                gates=tuple(
                    dataclasses.replace(
                        item,
                        state="blocked",
                        reports=",".join(report_identities),
                        findings=",".join(origins),
                        questions="remediation-limit-reached-round-4",
                    ) if item.id == "phase-01" else item
                    for item in tracker.gates
                ),
                remediation=rounds + tuple(row for row in tracker.remediation if row.gate != "phase-01"),
            )
            (run_dir / "progress.md").write_text(render_tracker(tracker), encoding="utf-8")
            decision = (
                "# Decisions\n\n## D-022 — Exact Round 5\n\n"
                "- **Question:** May the exact active gate receive Round 5?\n"
                "- **Answer:** Authorize Round 5 for phase-01 targeting P1-GATE-002, P1-GATE-008, P1-GATE-010, and P1-GATE-011.\n"
                "- **Decision action:** remediation.start-round\n"
                f"- **Authorized run:** {self.RUN_ID}\n"
                "- **Source revision:** 40\n"
                "- **Authorized gate:** phase-01\n"
                "- **Required state:** blocked\n"
                "- **Required question:** remediation-limit-reached-round-4\n"
                "- **Predecessor decision:** D-021\n"
                "- **Authorized through round:** 5\n"
                "- **Authorized findings:** P1-GATE-002,P1-GATE-008,P1-GATE-010,P1-GATE-011\n"
                "- **Authority marker:** remediation-extension:phase-01:through-round-5\n"
                "- **Scope:** Exact active run and phase-01 Round 5 only.\n"
                "- **Status:** Resolved.\n"
            )
            decisions = root / "decisions.md"
            fix_plan = root / "fix-plan-5.md"
            fix_plan.write_text("# Round 5\n", encoding="utf-8")
            before = (run_dir / "progress.md").read_bytes()
            invalid_decisions = {
                "wrong run": decision.replace(
                    "- **Authorized run:** " + self.RUN_ID, "- **Authorized run:** another-run"
                ),
                "stale revision": decision.replace("- **Source revision:** 40", "- **Source revision:** 39"),
                "wrong state": decision.replace("- **Required state:** blocked", "- **Required state:** accepted"),
                "wrong question": decision.replace(
                    "- **Required question:** remediation-limit-reached-round-4",
                    "- **Required question:** remediation-no-progress-round-4",
                ),
                "wrong predecessor": decision.replace(
                    "- **Predecessor decision:** D-021", "- **Predecessor decision:** D-020"
                ),
                "missing action with refusal-bearing prose": decision.replace(
                    "- **Decision action:** remediation.start-round\n", ""
                ).replace(
                    "- **Answer:** Authorize Round 5 for phase-01 targeting P1-GATE-002, P1-GATE-008, P1-GATE-010, and P1-GATE-011.",
                    "- **Answer:** Decline this extension; authorize it according to the recorded metadata for P1-GATE-002, P1-GATE-008, P1-GATE-010, and P1-GATE-011.",
                ),
                "quoted authority without action": decision.replace(
                    "- **Decision action:** remediation.start-round\n", ""
                ).replace(
                    "- **Answer:** Authorize Round 5 for phase-01 targeting P1-GATE-002, P1-GATE-008, P1-GATE-010, and P1-GATE-011.",
                    "- **Answer:** The note says \"authorize Round 5\" for P1-GATE-002, P1-GATE-008, P1-GATE-010, and P1-GATE-011.",
                ),
                "wrong action": decision.replace(
                    "- **Decision action:** remediation.start-round",
                    "- **Decision action:** review.resolve-question",
                ),
                "duplicate action": decision.replace(
                    "- **Decision action:** remediation.start-round\n",
                    "- **Decision action:** remediation.start-round\n"
                    "- **Decision action:** remediation.start-round\n",
                ),
            }
            for label, invalid in invalid_decisions.items():
                with self.subTest(label=label):
                    decisions.write_text(invalid, encoding="utf-8")
                    with self.assertRaises(TransitionError):
                        start_remediation_round(
                            run_dir, gate_id="phase-01", round_number=5,
                            finding_ids=self.ROUND_FIVE_FINDINGS, fix_plan=str(fix_plan),
                            fixer_assignments=("fixer-5",), capacity=3,
                            extension_decision_ref="D-022",
                        )
                    self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            decisions.write_text(decision, encoding="utf-8")
            with self.assertRaises(TransitionError):
                start_remediation_round(
                    run_dir, gate_id="phase-01", round_number=5,
                    finding_ids=self.ROUND_FIVE_FINDINGS, fix_plan=str(fix_plan),
                    fixer_assignments=("fixer-5",), capacity=3,
                    extension_decision_ref="D-021",
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

            started = start_remediation_round(
                run_dir, gate_id="phase-01", round_number=5,
                finding_ids=self.ROUND_FIVE_FINDINGS, fix_plan=str(fix_plan),
                fixer_assignments=("fixer-5",), capacity=3,
                extension_decision_ref="D-022",
            )
            self.assertEqual(started.revision, 41)
            row = next(row for row in started.remediation if row.gate == "phase-01" and row.round_number == 5)
            self.assertEqual((row.state, row.verification), ("fixing", "extension-authority=D-022"))
            after = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(TransitionError):
                start_remediation_round(
                    run_dir, gate_id="phase-01", round_number=6,
                    finding_ids=self.ROUND_FIVE_FINDINGS, fix_plan=str(fix_plan),
                    fixer_assignments=("fixer-6",), capacity=3,
                    extension_decision_ref="D-022",
                )
            self.assertEqual((run_dir / "progress.md").read_bytes(), after)



if __name__ == "__main__":
    unittest.main()
