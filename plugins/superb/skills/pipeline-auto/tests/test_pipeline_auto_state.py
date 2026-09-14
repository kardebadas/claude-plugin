"""Contract tests for the pipeline-auto/v1 state spine."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = SKILL_DIR / "tests" / "fixtures"

#: A fixture row a blank line can be inserted ahead of, inside a table body.
BLANK_TARGET = "| 10 | pending | - |\n"

sys.path.insert(0, str(SKILL_DIR / "scripts"))

import pipeline_auto_state as pas  # noqa: E402


def valid_text() -> str:
    return (FIXTURES / "valid-progress.md").read_text(encoding="utf-8")


class SchemaIdentityTests(unittest.TestCase):
    def test_schema_and_marker_are_the_exact_agreed_strings(self):
        self.assertEqual(pas.SCHEMA, "pipeline-auto/v1")
        self.assertEqual(pas.MARKER, "<!-- pipeline-auto/v1 -->")
        self.assertEqual(pas.TITLE, "# Pipeline Auto — Progress Tracker")

    def test_every_tracker_error_shares_one_root(self):
        for error in (pas.ForeignSchemaError, pas.TrackerValidationError,
                      pas.TrackerWriteError, pas.UpdateOutcomeUncertain,
                      pas.PlanMetadataError):
            self.assertTrue(issubclass(error, pas.TrackerError), error.__name__)

    def test_the_rung_enum_is_the_five_spec_names_lowest_first(self):
        self.assertEqual(
            pas.RUNG_NAMES,
            ("speculation", "engineering-judgement", "convention-cited",
             "code-evidenced", "specified"),
        )

    def test_no_run_field_carries_a_rung_value_or_an_adoption_floor(self):
        """Rungs are schema constants. A tunable floor in ## Run would let an
        autonomous controller lower its own adoption bar."""
        self.assertNotIn("adoption_floor", pas._RUN_KEYS)
        for key in pas._RUN_KEYS:
            self.assertNotIn(key, pas.RUNG_NAMES)


class RoundTripTests(unittest.TestCase):
    def test_render_of_a_parse_is_byte_identical_to_the_fixture(self):
        """Catches a renderer that drops a column the parser still tolerates.

        The fixture, not the module, holds the full column set. If a header
        constant loses a column, either the parse rejects the wider fixture or
        the render emits a narrower table; both fail this assertion.
        """
        text = valid_text()
        self.assertEqual(pas.render_tracker(pas.parse_tracker(text)), text)

    def test_the_parse_exposes_every_section_the_schema_names(self):
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual(
            sorted(tracker),
            sorted(["run", "stages", "intent", "questions", "quorum", "escalations",
                    "tasks", "task_review", "fix_rounds", "phases", "gates"]),
        )
        self.assertEqual(len(tracker["stages"]), 12)
        self.assertEqual(len(tracker["tasks"][0]), 16)
        self.assertEqual(tracker["tasks"][0]["provisional"], "no")
        self.assertEqual(tracker["tasks"][0]["decisions"], "H-1")
        self.assertEqual(len(tracker["task_review"][0]), 14)
        self.assertEqual(tracker["task_review"][0]["intensity"], "standard")
        self.assertEqual(tracker["task_review"][1]["intensity"], "adversarial")
        self.assertEqual(tracker["task_review"][2]["adversarial_verdict"], "-")
        self.assertEqual(tracker["fix_rounds"][0]["re_review"],
                         "scratch/p01-t01-r1-review.md")
        self.assertEqual(tracker["quorum"][0]["qid"], "3f2a1b0c9d8e")
        self.assertEqual(tracker["quorum"][0]["rung"], "specified")

    def test_a_remediation_section_is_rejected_rather_than_ignored(self):
        text = valid_text() + "\n## Remediation\n| Gate | Round |\n| --- | --- |\n"
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_reordered_or_renamed_sections_are_rejected(self):
        text = valid_text().replace("## Questions", "## ZZQuestions")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_renamed_run_field_is_rejected(self):
        text = valid_text().replace("| worker_limit |", "| workers |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_empty_cell_is_rejected_because_absence_is_spelled_dash(self):
        text = valid_text().replace("| E-1 | 7c6b5a4938d2 |", "| E-1 |  |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_missing_terminal_newline_is_rejected(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(valid_text().rstrip("\n"))

    def test_a_table_with_no_data_rows_parses_to_an_empty_list(self):
        text = valid_text()
        for row in ("| E-1 | 7c6b5a4938d2 | phase | queued | - | - |\n",
                    "| E-2 | - | run | answered | batch-1 | H-3 |\n"):
            text = text.replace(row, "")
        tracker = pas.parse_tracker(text)
        self.assertEqual(tracker["escalations"], [])
        self.assertEqual(pas.render_tracker(tracker), text)

    def test_a_blank_line_inside_a_table_is_rejected(self):
        """Parse must not accept bytes the renderer cannot reproduce.

        Absorbing the blank line would let a tracker parse and then render
        differently — an asymmetry in the byte stability this module exists
        to hold. The blank line is noise, so it is rejected, not preserved.
        """
        text = valid_text().replace(BLANK_TARGET, "\n" + BLANK_TARGET)
        self.assertNotEqual(text, valid_text())
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_rejection_is_read_only_because_the_module_cannot_write(self):
        """Pins the property that actually makes every rejection read-only.

        This assertion used to write a temp file, parse its text, and check the
        bytes were unchanged. It could not fail: ``parse_tracker`` takes a
        ``str`` and returns a dict, so no parse — accepted or rejected — can
        reach that file. Nor is "the input string is unmutated" worth asserting:
        ``str`` is immutable, so that holds of Python, not of this module.

        What is falsifiable is the capability itself. The module reads and
        writes nothing: its only import is ``__future__`` and it calls no
        builtin that opens a file or runs generated code. Add an ``import os``
        or an ``open()`` and this fails — which is what "read-only stop" in the
        exception docstrings is actually claiming.
        """
        tree = ast.parse(Path(pas.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"__future__"})
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        for builtin in ("open", "__import__", "eval", "exec", "compile"):
            self.assertNotIn(builtin, called)

    def test_a_trailing_blank_line_at_end_of_tracker_is_rejected(self):
        """The same asymmetry at the other end of the file.

        A blank line after the last row is equally unreproducible by the
        renderer. The final section keeps its separator line rather than having
        one taken off it, so the blank reaches the table rule and is refused
        there — one enforcement point for every blank line in the file.
        """
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(valid_text() + "\n")

    def test_no_blank_line_between_the_title_and_the_first_section_is_rejected(self):
        """The same asymmetry at the head of the file.

        The gap before the first heading was checked for content but never for
        width, so a tracker with no gap parsed and then rendered with one.
        """
        text = valid_text().replace(f"{pas.TITLE}\n\n## Run", f"{pas.TITLE}\n## Run")
        self.assertNotEqual(text, valid_text())
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_two_blank_lines_between_the_title_and_the_first_section_is_rejected(self):
        text = valid_text().replace(f"{pas.TITLE}\n\n## Run", f"{pas.TITLE}\n\n\n## Run")
        self.assertNotEqual(text, valid_text())
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_the_title_gap_the_parser_accepts_is_the_one_the_renderer_emits(self):
        """The byte-identity half: accepting a gap the renderer cannot emit is
        the defect, not the gap itself."""
        rendered = pas.render_tracker(pas.parse_tracker(valid_text()))
        self.assertIn(f"{pas.TITLE}\n\n## Run", rendered)
        self.assertNotIn(f"{pas.TITLE}\n\n\n", rendered)
        self.assertNotIn(f"{pas.TITLE}\n## Run", rendered)

    def test_render_rejects_a_row_missing_a_field(self):
        tracker = pas.parse_tracker(valid_text())
        del tracker["tasks"][0]["provisional"]
        with self.assertRaises(pas.TrackerValidationError):
            pas.render_tracker(tracker)


if __name__ == "__main__":
    unittest.main()
