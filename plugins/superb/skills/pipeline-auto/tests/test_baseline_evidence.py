"""Real-agent evidence and simulated evidence must not be able to mix.

The plan drafted these assertions against ``pytest`` (module-level ``test_*``
functions taking a ``tmp_path`` fixture, bare ``assert``). ``pytest`` is not
installed and this repository's suites are ``unittest``, so the same
assertions are expressed here as ``unittest.TestCase`` methods over a
per-test ``tempfile.TemporaryDirectory``, one method per scenario so the
runner reports each rejection separately.

Two assertions the plan did not draft are added at the end: the plan's
*Produces* contract is a **command** -- "exit 0 and an ``OK:`` line, or exit 1
with one error per line on stderr" -- and nothing in the drafted list ever
runs it. A ``main()`` that printed the errors and then returned 0 would have
satisfied every drafted test while making the validator a no-op in the
phase's verification tuple.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from check_baseline_evidence import (  # noqa: E402
    ACTUAL_CLASS,
    SIMULATED_CLASS,
    STIMULUS_IDS,
    check_tree,
)

VALIDATOR = TESTS_DIR / "check_baseline_evidence.py"

#: Long enough to clear the substantive-body floor, so that a test asserting
#: the floor fires is asserting the floor and not the fixture.
RAW_BODY = "The controller opens a quorum on this question. " * 8


def record(stimulus_id, evidence_class, **overrides):
    fields = {
        "Evidence class": evidence_class,
        "Stimulus ID": stimulus_id,
        "Stimulus SHA-256": "0" * 64,
        "Skill present": "none",
        "Dispatch": "Agent(subagent_type=general-purpose, model=opus)",
        "Agent id": "agent_0123456789abcdef",
        "Agent model": "opus",
        "Recorded UTC": "2026-09-14T18:00:00Z",
    }
    fields.update(overrides)
    header = "\n".join(f"- {key}: {value}" for key, value in fields.items())
    return (
        f"# P01 {stimulus_id} baseline\n\n{header}\n\n"
        f"## Raw response\n\n{RAW_BODY}\n"
    )


def build(root, *, actual=(), simulated=()):
    for name in ("actual-agent", "simulated"):
        (root / name).mkdir(parents=True, exist_ok=True)
    for stimulus_id, text in actual:
        (root / "actual-agent" / f"p01-{stimulus_id}-baseline-01.md").write_text(
            text, encoding="utf-8")
    for stimulus_id, text in simulated:
        (root / "simulated" / f"p01-{stimulus_id}-baseline-01.md").write_text(
            text, encoding="utf-8")


def all_actual():
    return [(sid, record(sid, ACTUAL_CLASS)) for sid in STIMULUS_IDS]


class BaselineEvidence(unittest.TestCase):
    """A records tree is evidence only if every claim in it is checkable."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp_path = Path(holder.name)

    def assertAnyError(self, errors, fragment):
        self.assertTrue(
            any(fragment in error for error in errors),
            f"no error contained {fragment!r}; got {errors!r}")

    # -- the separation itself -------------------------------------------

    def test_complete_actual_tree_passes(self):
        """Catches a validator so strict it rejects the evidence it exists
        to certify -- a rule that over-fires reads as 'no evidence yet' and
        stalls the phase exactly as a rule that never fires corrupts it."""
        build(self.tmp_path, actual=all_actual())
        self.assertEqual(check_tree(self.tmp_path), [])

    def test_simulated_record_in_the_actual_directory_is_rejected(self):
        """Catches hand-written or replayed output being filed as a real
        dispatch: the label says SIMULATED, the directory claims otherwise,
        and the scenario must also lose its ACTUAL_AGENT coverage."""
        records = all_actual()
        records[2] = ("S03", record("S03", SIMULATED_CLASS))
        build(self.tmp_path, actual=records)
        errors = check_tree(self.tmp_path)
        self.assertAnyError(errors, "directory requires 'ACTUAL_AGENT'")
        self.assertAnyError(errors, "missing valid ACTUAL_AGENT baseline for: S03")

    def test_real_agent_record_in_the_simulated_directory_is_rejected(self):
        """Catches the mirror mistake: a real transcript filed as simulated,
        which silently discards the only evidence the phase can spend."""
        build(
            self.tmp_path,
            actual=all_actual(),
            simulated=[("S01", record("S01", ACTUAL_CLASS))])
        errors = check_tree(self.tmp_path)
        self.assertAnyError(errors, "directory requires 'SIMULATED'")
        self.assertAnyError(errors, "foreign class label")

    # -- coverage ---------------------------------------------------------

    def test_missing_scenario_is_named(self):
        """Catches a gap reported as a bare count: the controller has to know
        which scenario is still undispatched, by id, not that 'one' is."""
        build(self.tmp_path, actual=all_actual()[:-1])
        self.assertEqual(
            check_tree(self.tmp_path),
            ["missing valid ACTUAL_AGENT baseline for: S10"])

    def test_missing_directory_is_reported(self):
        """Catches a tree validated against half of itself: an absent
        ``simulated/`` must be named, not skipped as 'nothing to check'."""
        (self.tmp_path / "actual-agent").mkdir(parents=True)
        errors = check_tree(self.tmp_path)
        self.assertAnyError(errors, str(self.tmp_path / "simulated"))

    # -- substance --------------------------------------------------------

    def test_truncated_raw_response_is_rejected(self):
        """Catches a record whose transcript was summarised away; a stub body
        cannot support the verbatim rationalization P08 reads back."""
        records = all_actual()
        records[4] = ("S05", record("S05", ACTUAL_CLASS).replace(RAW_BODY, "too short"))
        build(self.tmp_path, actual=records)
        self.assertAnyError(check_tree(self.tmp_path), "under 200 characters")

    def test_red_baselines_must_declare_no_skill_present(self):
        """Catches a baseline captured with the skill under test loaded --
        a RED measurement of the thing whose absence it is measuring."""
        records = all_actual()
        records[0] = (
            "S01", record("S01", ACTUAL_CLASS, **{"Skill present": "pipeline-auto"}))
        build(self.tmp_path, actual=records)
        self.assertAnyError(check_tree(self.tmp_path), "Skill present: none")

    def test_missing_header_field_is_named(self):
        """Catches an unreproducible record: without the model, the dispatch
        cannot be re-run and the transcript is an anecdote."""
        records = all_actual()
        stripped = "\n".join(
            line
            for line in record("S06", ACTUAL_CLASS).splitlines()
            if not line.startswith("- Agent model:"))
        records[5] = ("S06", stripped + "\n")
        build(self.tmp_path, actual=records)
        self.assertAnyError(
            check_tree(self.tmp_path), "missing required header field 'Agent model'")

    def test_placeholder_is_rejected(self):
        """Catches a template committed as a finding: an unfilled marker means
        the field was never observed."""
        records = all_actual()
        records[9] = ("S10", record("S10", ACTUAL_CLASS, **{"Agent id": "TBD"}))
        build(self.tmp_path, actual=records)
        self.assertAnyError(check_tree(self.tmp_path), "placeholder 'TBD'")

    def test_oracle_vocabulary_in_evidence_is_rejected(self):
        """Catches the controller's own grading leaking into the record, which
        would make the transcript unusable as an unaided baseline."""
        records = all_actual()
        leaked = record("S02", ACTUAL_CLASS) + "\nFail predicate: adopts an answer.\n"
        records[1] = ("S02", leaked)
        build(self.tmp_path, actual=records)
        self.assertAnyError(check_tree(self.tmp_path), "oracle vocabulary")

    def test_filename_must_match_the_stimulus_id(self):
        """Catches a record filed under the wrong scenario, which would report
        one stimulus as covered twice and another as never dispatched."""
        build(self.tmp_path, actual=all_actual())
        stray = self.tmp_path / "actual-agent" / "p01-S01-baseline-01.md"
        stray.rename(self.tmp_path / "actual-agent" / "p01-S02-baseline-02.md")
        self.assertAnyError(
            check_tree(self.tmp_path), "Stimulus ID does not match the filename")

    # -- the command contract --------------------------------------------

    def _run_validator(self, root):
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(root)],
            capture_output=True, text=True, check=False)

    def test_command_exits_zero_on_a_clean_tree(self):
        """Catches a validator that reports failure on good evidence, which
        would make the phase's verification tuple unpassable."""
        build(self.tmp_path, actual=all_actual())
        result = self._run_validator(self.tmp_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK:", result.stdout)

    def test_command_exits_non_zero_when_a_class_label_disagrees(self):
        """Catches the failure mode that makes the whole mechanism cosmetic:
        errors printed, exit status 0, and the gate passes anyway."""
        records = all_actual()
        records[2] = ("S03", record("S03", SIMULATED_CLASS))
        build(self.tmp_path, actual=records)
        result = self._run_validator(self.tmp_path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("directory requires 'ACTUAL_AGENT'", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
