"""``oracles.md`` may be published only after the RED measurement is complete.

Secrecy has an expiry date. Before it expires, a committed oracle contaminates
every baseline still to be captured -- an agent that can read the pass
predicates is measuring the repository rather than itself. After it expires, an
uncommitted oracle strands P08, which asserts against the ``GREEN predicate:``
lines verbatim. Both mistakes are silent: a maintainer tidying
``tests/pressure/.gitignore`` early destroys the measurement and nothing
complains, and one who never tidies it strands P08 and nothing complains then
either. So the ordering is asserted here rather than remembered.

What is asserted is the **ordering**, never the permanent presence of any
ignore line. ``records/``, ``RECORD-TEMPLATE.md`` and ``scoring.md`` are
permanently ignored and are pinned by ``test_record_template_ignored.py``;
``oracles.md`` is the one rule with an expiry, so every assertion below is
conditioned on which side of that expiry the repository is currently on.

The plan drafted these as ``pytest`` module-level functions. ``pytest`` is not
installed on this machine and this tree's suites are discovered with
``python3 -m unittest discover``, which collects ``TestCase`` methods and
ignores bare ``test_*`` functions -- drafted verbatim the guard would have been
silently collected by nothing at all, which is precisely the failure mode it
exists to prevent. The assertions are therefore expressed as ``TestCase``
methods, one method per claim so ``-v`` reports each separately.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from check_baseline_evidence import STIMULUS_IDS, check_tree  # noqa: E402

#: tests -> pipeline-auto -> skills -> superb -> plugins -> repository root.
#: Derived, never spelled out: an absolute home path in a committed file
#: hardcodes one machine and one account name into shared work.
REPO_ROOT = TESTS_DIR.parents[4]
PRESSURE = TESTS_DIR / "pressure"
ORACLES = PRESSURE / "oracles.md"
RECORDS = PRESSURE / "records"
RED_BASELINE = PRESSURE / "RED-baseline.md"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _git_available() -> bool:
    return shutil.which("git") is not None and (REPO_ROOT / ".git").exists()


def is_tracked(path: Path) -> bool:
    return _git("ls-files", "--error-unmatch", "--", str(path)).returncode == 0


def is_ignored(path: Path) -> bool:
    """Does .gitignore cover this path, regardless of whether git is tracking it?

    ``--no-index`` is load-bearing. Without it ``git check-ignore`` consults the
    index first and reports a **tracked** file as not ignored whatever
    ``.gitignore`` says -- so the both-tracked-and-ignored state, which is the
    exact result of ``git add -f`` on the oracle without touching
    ``.gitignore``, would be undetectable and the guard below would silently
    never fire. An earlier draft of this file omitted the flag and passed
    against precisely the repository state it was written to reject. Do not
    "simplify" it away.
    """
    return _git("check-ignore", "--no-index", "-q", "--", str(path)).returncode == 0


def is_committed(path: Path) -> bool:
    """Is this path in HEAD's tree, as opposed to merely staged?

    Distinct from :func:`is_tracked`, which answers about the index. A staged
    oracle is not yet published -- nothing has entered the history, so the
    ancestry claims below have nothing to say about it. The tracked-and-ignored
    claim above still fires on that state, which is the one that matters before
    the commit lands.
    """
    return _git("ls-tree", "--name-only", "HEAD", "--", str(path)).stdout.strip() != ""


def _commits_touching(path: Path) -> list[str]:
    completed = _git("rev-list", "HEAD", "--", str(path))
    return completed.stdout.split()


@unittest.skipUnless(_git_available(), "not a git working tree")
class OracleDisclosureOrder(unittest.TestCase):
    """The oracle is published after the measurement, and never before it."""

    def test_oracle_is_published_only_after_the_red_measurement_is_complete(self):
        if not is_tracked(ORACLES):
            # P01 is still measuring. Secrecy is doing its job; nothing to
            # assert on this side of the expiry.
            self.skipTest("oracles.md is not published yet")

        self.assertTrue(
            is_tracked(RED_BASELINE),
            "oracles.md is tracked but RED-baseline.md is not: the pass "
            "predicates were published before the baseline that justifies them")
        baseline_text = RED_BASELINE.read_text(encoding="utf-8")
        for stimulus_id in STIMULUS_IDS:
            self.assertIn(
                stimulus_id, baseline_text,
                f"oracles.md is tracked but RED-baseline.md records no outcome "
                f"for {stimulus_id}")

        # In the workspace that ran P01 the records tree is still on disk, and
        # it is the stronger check: every scenario must hold a validated
        # ACTUAL_AGENT record. In a fresh clone the tree is absent -- records/
        # is ignored and never published -- and RED-baseline.md above is the
        # proof that survives.
        if RECORDS.is_dir():
            self.assertEqual(
                check_tree(RECORDS), [],
                "oracles.md is tracked but the records tree does not hold a "
                "validated ACTUAL_AGENT baseline for every scenario")

    def test_oracle_is_ignored_while_it_is_unpublished(self):
        if is_tracked(ORACLES):
            self.skipTest("oracles.md is published; the ignore rule is retired")
        if not ORACLES.exists():
            self.skipTest("oracles.md is not present in this workspace")
        self.assertTrue(
            is_ignored(ORACLES),
            "oracles.md is neither tracked nor ignored: it is one 'git add -A' "
            "away from contaminating every baseline not yet captured")

    def test_oracle_is_never_both_tracked_and_ignored(self):
        self.assertFalse(
            is_tracked(ORACLES) and is_ignored(ORACLES),
            "oracles.md is both tracked and ignored: remove its line from "
            "tests/pressure/.gitignore in the same commit that publishes it "
            "-- and remove only that line, the other rules there are permanent")

    def test_raw_records_are_never_published(self):
        tracked = _git("ls-files", "--", str(RECORDS)).stdout.strip()
        self.assertEqual(
            tracked, "", f"raw transcripts must never be committed: {tracked}")


@unittest.skipUnless(_git_available(), "not a git working tree")
class OracleDisclosureAncestry(unittest.TestCase):
    """The ordering is asserted against the commit graph, not only the tree.

    A working tree records the *result* of the ordering, not the ordering
    itself. A test can be bypassed with ``--no-verify`` and commits can be
    reordered by a rebase, and neither leaves a trace in the tree the classes
    above inspect -- afterwards the repository looks exactly as it should.
    Ancestry cannot be faked after the fact: if the commit publishing the
    oracle does not descend from the commit publishing ``RED-baseline.md``,
    then at the moment the answers were published the baseline that justifies
    them was not yet in the history.
    """

    def setUp(self):
        if not is_committed(ORACLES):
            self.skipTest("oracles.md has not entered the history yet")

    def test_oracle_was_published_in_exactly_one_commit(self):
        commits = _commits_touching(ORACLES)
        self.assertEqual(
            len(commits), 1,
            "oracles.md should have exactly one commit in its history: the "
            "single publishing commit P01 makes on its way out. More than one "
            f"means it was published and then rewritten ({commits}), which is "
            "the shape an early disclosure leaves behind once it is tidied up; "
            "fewer means the history was rewritten under it. If a later phase "
            "genuinely needs to amend the oracle, amend this assertion "
            "deliberately -- do not delete it.")

    def test_oracle_commit_descends_from_the_red_baseline_commit(self):
        oracle_commits = _commits_touching(ORACLES)
        baseline_commits = _commits_touching(RED_BASELINE)
        self.assertTrue(oracle_commits, "no commit in HEAD's history adds oracles.md")
        self.assertTrue(
            baseline_commits,
            "oracles.md is committed but no commit in HEAD's history adds "
            "RED-baseline.md")

        # Oldest commit touching each path: when each was introduced.
        oracle_commit = oracle_commits[-1]
        baseline_commit = baseline_commits[-1]
        self.assertNotEqual(
            oracle_commit, baseline_commit,
            "oracles.md and RED-baseline.md were published in the same commit: "
            "the oracle must follow the baseline, not accompany it")
        self.assertEqual(
            _git("merge-base", "--is-ancestor",
                 baseline_commit, oracle_commit).returncode, 0,
            f"the commit publishing oracles.md ({oracle_commit[:12]}) does not "
            f"descend from the commit publishing RED-baseline.md "
            f"({baseline_commit[:12]}): the pass predicates entered the history "
            f"before the baseline that justifies them")


if __name__ == "__main__":
    unittest.main()
