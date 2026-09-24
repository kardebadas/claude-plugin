"""The controller-only working files must not be able to reach the repository.

Task 3 puts three things inside the skill tree that are deliberately never
committed: ``oracles.md``, ``RECORD-TEMPLATE.md`` and the ``records/`` tree.
Two of the three were already covered by Task 1's ``.gitignore``. The record
template was not, and an uncovered file is not "uncommitted" -- it is one
``git add -A`` away from being committed, and it shows up in the
``git status --short`` that this phase requires to be empty at every task
boundary.

These assertions are behavioural on purpose. A string sitting in a
``.gitignore`` is not the same claim as git actually ignoring the path: a
negation in an outer ``.gitignore``, a differently-rooted pattern, or an
already-tracked file all break the second without touching the first. So the
static check and the ``git check-ignore`` check are separate tests.

``oracles.md`` is deliberately NOT pinned here. Its ignore rule is temporary
and P01's final task removes it when it publishes the oracle; a test pinning
it would fail the very commit the design requires. ``RECORD-TEMPLATE.md`` has
no such expiry -- it is a workspace scaffold that no phase ever commits -- so
pinning it is safe.

``pytest`` is not installed on this machine. These are ``unittest.TestCase``
methods, one bound method per claim, matching the other suites in this tree so
per-claim results stay visible in ``-v`` output.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PRESSURE = TESTS / "pressure"
GITIGNORE = PRESSURE / ".gitignore"
#: tests -> pipeline-auto -> skills -> superb -> plugins -> repository root.
#: Derived, never spelled out: an absolute home path in a committed file
#: hardcodes one machine and one account name into shared work.
REPO_ROOT = TESTS.parents[4]

RECORD_TEMPLATE = PRESSURE / "RECORD-TEMPLATE.md"
#: A path inside the records tree. It need not exist: ``git check-ignore``
#: answers about the path, not about the file.
A_RECORD = PRESSURE / "records" / "actual-agent" / "p01-S01-baseline-01.md"


def _ignore_rules() -> list[str]:
    return [
        line.strip()
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _git_available() -> bool:
    return shutil.which("git") is not None and (REPO_ROOT / ".git").exists()


class RecordTemplateIsIgnored(unittest.TestCase):
    """The record template is covered by the committed ignore rule."""

    def _assert_git_ignores(self, path: Path) -> None:
        completed = subprocess.run(
            ["git", "check-ignore", "-v", "--", str(path)],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(
            completed.returncode, 0,
            f"git does not ignore {path.relative_to(REPO_ROOT)}; "
            f"check-ignore said: {completed.stdout.strip()!r} "
            f"{completed.stderr.strip()!r}")
        self.assertIn(
            ".gitignore", completed.stdout,
            "the ignore must come from a committed .gitignore, not from "
            "an exclude file that only exists in this workspace")

    def test_gitignore_names_the_record_template(self):
        self.assertIn("RECORD-TEMPLATE.md", _ignore_rules())

    @unittest.skipUnless(_git_available(), "not a git working tree")
    def test_git_actually_ignores_the_record_template(self):
        self._assert_git_ignores(RECORD_TEMPLATE)

    @unittest.skipUnless(_git_available(), "not a git working tree")
    def test_git_actually_ignores_a_raw_record(self):
        self._assert_git_ignores(A_RECORD)


if __name__ == "__main__":
    unittest.main()
