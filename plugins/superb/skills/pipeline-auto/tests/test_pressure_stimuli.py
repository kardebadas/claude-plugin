"""Stimuli are worker-visible input. Oracles and records are not.

The plan drafted these assertions against ``pytest``. ``pytest`` is not
installed and this repository's suites are ``unittest``, so the same
assertions are expressed here as ``unittest.TestCase`` methods, with the two
parametrized families generated one method per scenario rather than collapsed
into ``subTest`` -- a ``subTest`` loop would report ten scenarios as one test
and lose the per-scenario granularity the plan's "23 passed" count is counting.
"""

from __future__ import annotations

import unittest
from pathlib import Path

PRESSURE = Path(__file__).resolve().parent / "pressure"
STIMULI = PRESSURE / "stimuli"
SUFFIX = PRESSURE / "PRESSURE-SUFFIX.md"
GITIGNORE = PRESSURE / ".gitignore"

STIMULUS_IDS = (
    "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10",
)

#: Vocabulary that only ever appears in the oracle. A stimulus carrying any of
#: it has told the agent what the graded answer is, and the dispatch then
#: measures the repository instead of the agent.
ORACLE_TOKENS = (
    "Correct behaviour:",
    "Fail predicate:",
    "Rationalization watchlist:",
    "GREEN predicate:",
    "ORACLE:",
    "expected-result:",
    "controller-only",
)
#: A stimulus is dispatched as-is. An unfilled marker reaches a real agent.
PLACEHOLDERS = ("TBD", "TODO", "<fill", "XXX")
#: Naming the skill under test, or its prose, hands the agent the very thing
#: this baseline exists to establish the absence of.
CONTAMINANTS = ("pipeline-auto", "SKILL.md", "superpowers:", "the correct")
FORBIDDEN = ORACLE_TOKENS + PLACEHOLDERS + CONTAMINANTS


class PressureStimuli(unittest.TestCase):
    """Every declared scenario exists, is substantive, and leaks nothing."""

    def _assert_stimulus_file_exists_and_is_headed_by_its_id(self, stimulus_id):
        path = STIMULI / f"{stimulus_id}.md"
        self.assertTrue(path.is_file(), f"{path} is missing")
        text = path.read_text(encoding="utf-8")
        self.assertTrue(
            text.startswith(f"# {stimulus_id}\n"),
            f"{stimulus_id} must open with its own id as an H1")
        self.assertGreater(
            len(text), 400,
            f"{stimulus_id} is too thin to be a pressure scenario")

    def _assert_stimulus_leaks_nothing_an_agent_must_not_see(self, stimulus_id):
        text = (STIMULI / f"{stimulus_id}.md").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(
                token, text, f"{stimulus_id}: {token!r} must not reach an agent")

    def test_stimuli_directory_holds_exactly_the_declared_scenarios(self):
        self.assertEqual(
            sorted(path.name for path in STIMULI.iterdir()),
            [f"{stimulus_id}.md" for stimulus_id in STIMULUS_IDS])

    def test_pressure_suffix_exists_and_is_clean(self):
        text = SUFFIX.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Pressure suffix\n"))
        for token in FORBIDDEN:
            self.assertNotIn(
                token, text, f"PRESSURE-SUFFIX: {token!r} must not reach an agent")

    def test_gitignore_always_keeps_raw_records_out_of_the_repository(self):
        lines = [
            line.strip()
            for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        #: ``records/`` is ignored forever. ``oracles.md`` is deliberately NOT
        #: pinned here: its rule is temporary, and P01's final task removes it
        #: when it publishes the oracle. A test pinning it would fail the very
        #: commit the design requires.
        self.assertIn("records/", lines)


def _bind(name_template, helper):
    for stimulus_id in STIMULUS_IDS:
        def method(self, stimulus_id=stimulus_id, helper=helper):
            helper(self, stimulus_id)
        method.__name__ = name_template.format(stimulus_id.lower())
        setattr(PressureStimuli, method.__name__, method)


_bind(
    "test_stimulus_file_exists_and_is_headed_by_its_id_{}",
    PressureStimuli._assert_stimulus_file_exists_and_is_headed_by_its_id)
_bind(
    "test_stimulus_leaks_nothing_an_agent_must_not_see_{}",
    PressureStimuli._assert_stimulus_leaks_nothing_an_agent_must_not_see)


if __name__ == "__main__":
    unittest.main()
