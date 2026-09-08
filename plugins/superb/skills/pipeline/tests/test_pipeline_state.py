from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path

from plugins.superb.skills.pipeline.scripts.pipeline_state import (
    PlanMetadataError,
    SchemaError,
    parse_phase_plan,
    parse_tracker,
    parse_worker_result,
    render_tracker,
)


REPOSITORY = Path(__file__).resolve().parents[5]
FIXTURES = Path(__file__).with_name("fixtures")


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


if __name__ == "__main__":
    unittest.main()
