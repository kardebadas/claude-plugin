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
    # Crafted Product Definition
    ## Vision
    A document store for small teams.
    ## Scope
    In scope: upload, list, delete.
    ## Confirmed Decisions
    | ID | Decision | Source |
    | -- | -------- | ------ |
    | DEC-001 | Postgres | User answer |
    ## Core Features
    - Upload a file: a signed-in user uploads a PDF and sees it listed.
    ## Domain Behaviour
    - Document: has an owner; a document may not be shared outside its team.
    ## Target Users
    - Editor: appears in the upload journey; may create and delete own documents.
    ## Explicit Non-Goals
    - No mobile app.
    ## Technical Preferences
    - Database: Postgres.
    - Frontend: No preference — planning skill may decide.
    ## Open Questions
    _(none)_
    ## Remaining Assumptions
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
        rc, out = run(COMPLETE.replace("## Open Questions\n    _(none)_",
                                       "## Open Questions\n    - CON-001 unresolved: offline vs realtime"))
        self.assertEqual(rc, 1)
        self.assertIn("CON-001", out)

    def test_high_impact_unconfirmed_assumption_fails(self):
        rc, out = run(COMPLETE.replace("## Remaining Assumptions\n    _(none)_",
                                       "## Remaining Assumptions\n    - ASM-001 Impact: High Status: Unconfirmed"))
        self.assertEqual(rc, 1)

    def test_feature_without_acceptance_sentence_fails(self):
        rc, out = run(COMPLETE.replace(
            "- Upload a file: a signed-in user uploads a PDF and sees it listed.",
            "- Upload a file"))
        self.assertEqual(rc, 1)
        self.assertIn("acceptance", out.lower())

    def test_every_required_heading_exists_in_the_skills_own_template(self):
        """The check must require headings craft actually writes.

        The first version invented names — User Types, Technical Direction,
        Contradictions — none of which the output template emits, so every real
        brief failed for reasons unrelated to its quality. The unit tests missed
        it because the fixture was written to match the script.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location("cb", CHECK)
        cb = importlib.util.module_from_spec(spec); spec.loader.exec_module(cb)
        skill = (CHECK.parent / "SKILL.md").read_text(encoding="utf-8")
        missing = [h for h in cb.REQUIRED_HEADINGS if ("## " + h) not in skill]
        self.assertEqual(missing, [], "check-brief requires headings the skill never writes: %s" % missing)

    def test_required_decision_sourced_from_recommendation_fails(self):
        rc, out = run(COMPLETE.replace("| DEC-001 | Postgres | User answer |",
                                       "| DEC-001 | Postgres | Accepted recommendation |"))
        self.assertEqual(rc, 1)
        self.assertIn("DEC-001", out)

class HarnessTests(unittest.TestCase):
    """Tests about the tests. A mutation that changes nothing proves nothing."""

    def test_no_replace_target_is_a_no_op(self):
        """Every COMPLETE.replace() target must exist in COMPLETE.

        Two regression tests silently passed because they replaced
        "- Database: PostgreSQL." while the fixture said "Postgres." — the
        replace was a no-op, so the test asserted against an unmodified brief.
        """
        import re
        src = pathlib.Path(__file__).read_text(encoding="utf-8")
        targets = re.findall(r'COMPLETE\.replace\(\s*\n?\s*"((?:[^"\\]|\\.)*)"', src)
        self.assertTrue(targets, "found no replace targets to check")
        missing = [t for t in targets
                   if t.encode().decode("unicode_escape") not in COMPLETE]
        self.assertEqual(missing, [], "replace targets absent from COMPLETE: %s" % missing)


class ReviewRegressions(unittest.TestCase):
    """One test per defect an adversarial review found in the first version."""

    def test_not_applicable_does_not_whitelist_the_whole_section(self):
        rc, out = run(COMPLETE.replace(
            "- Database: Postgres.",
            "- Not applicable — no database.\n    - Hosting: TODO"))
        self.assertEqual(rc, 1, out)
        self.assertIn("vagueness", out)

    def test_etc_is_caught(self):
        rc, out = run(COMPLETE.replace("- No mobile app.", "- No mobile app, no tablet, etc."))
        self.assertEqual(rc, 1, out)

    def test_url_colon_is_not_an_acceptance_sentence(self):
        rc, out = run(COMPLETE.replace(
            "- Upload a file: a signed-in user uploads a PDF and sees it listed.",
            "- See https://example.com/spec"))
        self.assertEqual(rc, 1, out)
        self.assertIn("acceptance", out.lower())

    def test_empty_technical_axis_fails(self):
        rc, out = run(COMPLETE.replace("- Database: Postgres.", "- Database:"))
        self.assertEqual(rc, 1, out)
        self.assertIn("neither chosen nor deferred", out)

    def test_core_features_with_no_bullets_fails(self):
        rc, out = run(COMPLETE.replace(
            "- Upload a file: a signed-in user uploads a PDF and sees it listed.",
            "Some prose about features."))
        self.assertEqual(rc, 1, out)
        self.assertIn("no features", out)

    def test_duplicate_heading_fails(self):
        rc, out = run(COMPLETE + "\n    ## Core Features\n    - Another: this one is different entirely.\n")
        self.assertEqual(rc, 1, out)
        self.assertIn("more than once", out)

    def test_fenced_code_is_not_parsed_as_content(self):
        rc, out = run(COMPLETE.replace(
            "## Open Questions\n    _(none)_",
            "## Open Questions\n    ```\n    ## Core Features\n    - TBD\n    ```\n    _(none)_"))
        self.assertEqual(rc, 0, out)

    def test_q1_does_not_collide_with_q10(self):
        import json, tempfile, os, pathlib as pl
        d = tempfile.mkdtemp()
        pl.Path(d, "CRAFT.md").write_text(textwrap.dedent(COMPLETE) +
            "\n- Q1 settled here.\n- Q10 settled there.\n")
        os.makedirs(pl.Path(d, ".craft"))
        pl.Path(d, ".craft", "round-001.questions.json").write_text(json.dumps({
            "round": 1, "questions": [
                {"id": "Q1", "importance": "REQUIRED", "title": "a", "type": "text"},
                {"id": "Q10", "importance": "REQUIRED", "title": "b", "type": "text"}]}))
        p = subprocess.run([sys.executable, str(CHECK), d], capture_output=True, text=True)
        self.assertNotIn("appears 2 times", p.stdout)

    def test_uppercase_importance_is_actually_checked(self):
        import json, tempfile, os, pathlib as pl
        d = tempfile.mkdtemp()
        pl.Path(d, "CRAFT.md").write_text(textwrap.dedent(COMPLETE))
        os.makedirs(pl.Path(d, ".craft"))
        pl.Path(d, ".craft", "round-001.questions.json").write_text(json.dumps({
            "round": 1, "questions": [
                {"id": "QZ", "importance": "REQUIRED", "title": "never mentioned", "type": "text"}]}))
        p = subprocess.run([sys.executable, str(CHECK), d], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("QZ", p.stdout)


if __name__ == "__main__":
    unittest.main()
