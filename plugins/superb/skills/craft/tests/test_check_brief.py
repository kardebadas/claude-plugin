import subprocess, sys, textwrap, unittest, pathlib, tempfile, os

CHECK = pathlib.Path(__file__).resolve().parent.parent / "check-brief.py"

def run(brief, rounds=None):
    d = tempfile.mkdtemp()
    pathlib.Path(d, "CRAFT.md").write_text(textwrap.dedent(brief))
    if rounds:
        os.makedirs(pathlib.Path(d, ".craft"), exist_ok=True)
        for name, body in rounds.items():
            pathlib.Path(d, ".craft", name).write_text(body)
    p = subprocess.run([sys.executable, str(CHECK), d], capture_output=True, text=True)
    return p.returncode, p.stdout

COMPLETE = """
    # CRAFT.md
    ## Confirmed Decisions
    | ID | Decision | Source |
    | -- | -------- | ------ |
    | DEC-001 | Postgres | User answer |
    ## Core Features
    - Upload a file: a signed-in user uploads a PDF and sees it listed.
    ## Domain Behaviour
    - Document: has an owner; a document may not be shared outside its team.
    ## User Types
    - Editor: appears in the upload journey; may create and delete own documents.
    ## Explicit Non-Goals
    - No mobile app.
    ## Technical Direction
    - Database: Postgres.
    - Frontend: No preference — planning skill may decide.
    ## Open Questions
    _(none)_
    ## Assumptions
    _(none)_
    ## Contradictions
    _(none)_
    """

class StructureTests(unittest.TestCase):
    def test_complete_brief_passes(self):
        rc, out = run(COMPLETE)
        self.assertEqual(rc, 0, out)

    def test_missing_brief_is_exit_2(self):
        d = tempfile.mkdtemp()
        p = subprocess.run([sys.executable, str(CHECK), d], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_tbd_fails_structure(self):
        rc, out = run(COMPLETE.replace("- No mobile app.", "- TBD"))
        self.assertEqual(rc, 1)
        self.assertIn("vagueness", out)

    def test_open_required_question_fails(self):
        rc, out = run(COMPLETE.replace("## Open Questions\n    _(none)_",
                                       "## Open Questions\n    - [REQUIRED] Which auth provider?"))
        self.assertEqual(rc, 1)
        self.assertIn("open", out.lower())

    def test_unresolved_contradiction_fails(self):
        rc, out = run(COMPLETE.replace("## Contradictions\n    _(none)_",
                                       "## Contradictions\n    - CON-001 unresolved: offline vs realtime"))
        self.assertEqual(rc, 1)
        self.assertIn("CON-001", out)

    def test_high_impact_unconfirmed_assumption_fails(self):
        rc, out = run(COMPLETE.replace("## Assumptions\n    _(none)_",
                                       "## Assumptions\n    - ASM-001 Impact: High Status: Unconfirmed"))
        self.assertEqual(rc, 1)

    def test_feature_without_acceptance_sentence_fails(self):
        rc, out = run(COMPLETE.replace(
            "- Upload a file: a signed-in user uploads a PDF and sees it listed.",
            "- Upload a file"))
        self.assertEqual(rc, 1)
        self.assertIn("acceptance", out.lower())

    def test_required_decision_sourced_from_recommendation_fails(self):
        rc, out = run(COMPLETE.replace("| DEC-001 | Postgres | User answer |",
                                       "| DEC-001 | Postgres | Accepted recommendation |"))
        self.assertEqual(rc, 1)
        self.assertIn("DEC-001", out)

if __name__ == "__main__":
    unittest.main()
