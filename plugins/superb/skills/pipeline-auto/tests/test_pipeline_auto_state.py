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

#: A section boundary in the fixture: the last row of ``## Stage``, the single
#: blank line, the next heading. Between sections is the one seam where the
#: blank-line rule lives in ``_sections`` instead of ``_table``, so it needs its
#: own inputs. ``NO_GAP`` and ``WIDE_GAP`` are the two ways to get it wrong.
SECTION_BREAK = "| 12 | pending | - |\n\n## Intent\n"
NO_GAP = "| 12 | pending | - |\n## Intent\n"
WIDE_GAP = "| 12 | pending | - |\n\n\n## Intent\n"

#: Modules ``pipeline_auto_state`` is permitted to import. This is an
#: ALLOWLIST, not a snapshot of what it imports today: each name was put here
#: deliberately, after checking it opens no file and runs no generated code.
#: ``hashlib`` is listed for the payload and context digests the quorum rows
#: carry. Widening this set is a decision to be argued for, never a step taken
#: incidentally to make a failing test pass.
ALLOWED_IMPORTS = frozenset({"__future__", "hashlib"})

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
        writes nothing: it imports only from the reviewed ``ALLOWED_IMPORTS``
        allowlist and calls no builtin that opens a file or runs generated
        code. Add an ``import os``, an ``open()`` or an ``eval()`` and this
        fails — which is what "read-only stop" in the exception docstrings is
        actually claiming. The allowlist, not an exact import set, is the
        property worth pinning: the module is allowed to grow an import, it is
        not allowed to grow a capability.
        """
        tree = ast.parse(Path(pas.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(
            imported - ALLOWED_IMPORTS, set(),
            "module imports outside ALLOWED_IMPORTS; widen it on purpose only")
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

    def test_no_blank_line_between_two_sections_is_rejected(self):
        """The same asymmetry between sections — the seam left unswept.

        Every section owes exactly one blank line to the break that follows it.
        A parser that merely stripped whatever trailing blanks it found would
        take this gapless input and render it back with a gap.
        """
        text = valid_text().replace(SECTION_BREAK, NO_GAP)
        self.assertNotEqual(text, valid_text())
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_two_blank_lines_between_two_sections_is_rejected(self):
        """One blank line is required, so two is as wrong as none."""
        text = valid_text().replace(SECTION_BREAK, WIDE_GAP)
        self.assertNotEqual(text, valid_text())
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_section_gap_the_parser_accepts_renders_back_to_itself(self):
        """The byte-identity companion: no rejected gap is quietly normalised.

        The rule under test is not "reject these two inputs", it is "anything
        accepted renders to the bytes it came from". Both variants are expected
        to be refused; should either ever be accepted, this insists it round
        trips, which neither can — the renderer emits exactly one blank line
        between sections.
        """
        rendered = pas.render_tracker(pas.parse_tracker(valid_text()))
        self.assertIn(SECTION_BREAK, rendered)
        self.assertNotIn(NO_GAP, rendered)
        self.assertNotIn(WIDE_GAP, rendered)
        for variant in (NO_GAP, WIDE_GAP):
            text = valid_text().replace(SECTION_BREAK, variant)
            try:
                round_tripped = pas.render_tracker(pas.parse_tracker(text))
            except pas.TrackerValidationError:
                continue
            self.assertEqual(round_tripped, text,
                             "accepted bytes must render back unchanged")

    def test_an_empty_last_section_is_not_blamed_on_a_table_it_has_not_got(self):
        """The rejection is right; the words have to be right too.

        A last section holding nothing but its blank line has no table for a
        blank line to be inside of, and saying otherwise sends the reader
        hunting for a table that was never there.
        """
        text = valid_text()
        empty_last = text[:text.index("## Gates")] + "## Gates\n\n"
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(empty_last)
        self.assertNotIn("inside a table", str(caught.exception))
        self.assertIn("no table", str(caught.exception))
        # The same rule still names the table when there is one to name.
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text.replace(BLANK_TARGET, "\n" + BLANK_TARGET))
        self.assertIn("inside a table", str(caught.exception))

    def test_render_rejects_a_row_missing_a_field(self):
        tracker = pas.parse_tracker(valid_text())
        del tracker["tasks"][0]["provisional"]
        with self.assertRaises(pas.TrackerValidationError):
            pas.render_tracker(tracker)


if __name__ == "__main__":
    unittest.main()
