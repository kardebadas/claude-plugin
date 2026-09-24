"""The P09 controller walkthrough, run as part of the suite.

`examples/controller_walkthrough.py` drives one whole run against a foreign
repository and exits non-zero if the machinery cannot complete it. It is run
as a separate process from an unrelated working directory, so a module that
resolved anything against the process's cwd (this checkout) fails here.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
WALKTHROUGH = SKILL / "examples" / "controller_walkthrough.py"


def fingerprint() -> dict:
    return {str(path.relative_to(SKILL)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(SKILL.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts}


class WalkthroughSourceTests(unittest.TestCase):

    def test_the_walkthrough_exists_and_names_no_home_directory(self):
        self.assertTrue(WALKTHROUGH.is_file(), f"missing: {WALKTHROUGH}")
        self.assertNotIn("/home/", WALKTHROUGH.read_text(encoding="utf-8"))


@unittest.skipUnless(sys.platform == "linux",
                     "pipeline-auto is Linux-only: classify_filesystem answers "
                     "'unknown' elsewhere and the run would halt")
class WalkthroughRunTests(unittest.TestCase):

    def test_a_whole_run_reaches_complete_with_proposals_and_stays_confined(self):
        before = fingerprint()
        with tempfile.TemporaryDirectory() as cwd:
            done = subprocess.run((sys.executable, str(WALKTHROUGH)), cwd=cwd,
                                  capture_output=True, text=True, timeout=600)
        output = done.stdout + done.stderr
        self.assertEqual(done.returncode, 0, output[-4000:])
        self.assertIn("'complete-with-proposals' once CP-1", done.stdout)
        self.assertIn("OK: confinement:", done.stdout)
        self.assertEqual(fingerprint(), before,
                         "the walkthrough changed a file inside the skill")


if __name__ == "__main__":
    unittest.main()
