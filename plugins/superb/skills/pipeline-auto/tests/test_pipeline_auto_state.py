"""Contract tests for the pipeline-auto/v1 state spine."""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = SKILL_DIR / "tests" / "fixtures"

#: The *real* fixtures of the *other* skill, read at their real path rather than
#: copied here. A copy would drift from the file `superb:pipeline` actually
#: writes, and the foreign-schema stop would then be proven against a stale
#: snapshot instead of against the skill that exists. These are read, never
#: written: `git diff --name-only -- plugins/superb/skills/pipeline/` must stay
#: empty. Derived from this file's own location, never an absolute path.
FOREIGN_FIXTURES = SKILL_DIR.parent / "pipeline" / "tests" / "fixtures"

#: ``superb:pipeline`` is a PREFIX of ``superb:pipeline-auto``, so asserting the
#: former as a plain substring can never fail — the diagnostic names this skill
#: in every sentence. The negative lookahead is the difference between "the
#: message mentions us" and "the message tells the user which OTHER skill owns
#: this directory", which is the whole point of the diagnostic.
NAMES_THE_OTHER_SKILL = re.compile(r"superb:pipeline(?!-auto)")

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
#: deliberately, and widening it is a decision to be argued for, never a step
#: taken incidentally to make a failing test pass. ``hashlib`` is listed for the
#: payload and context digests the quorum rows carry. ``pathlib`` is listed
#: because ``validate_run`` takes its run directory as a ``Path`` and READS
#: through it.
#:
#: What this allowlist does NOT prove is that the module cannot write. ``pathlib``
#: is not a narrower capability than ``os`` or ``shutil``: ``Path.write_text``,
#: ``write_bytes``, ``unlink``, ``rename``, ``replace``, ``mkdir``, ``rmdir``,
#: ``touch``, ``chmod``, ``symlink_to`` and ``open(mode=...)`` all exist, and an
#: earlier revision of this file claimed otherwise. The read-only guarantee is
#: carried by ``write_capable_calls`` below, scoped to ``validate_run``.
ALLOWED_IMPORTS = frozenset({"__future__", "hashlib", "pathlib"})

#: Builtins that open a file or run generated code. Called anywhere in the
#: module, by any function, they are refused — this half is module-wide.
FORBIDDEN_BUILTINS = ("open", "__import__", "eval", "exec", "compile")

#: ``pathlib.Path`` attributes that create, replace, remove or re-permission
#: something on disk. Any ``write*`` name is added to these by prefix, which
#: also covers ``write``, ``write_text``, ``write_bytes`` and ``writelines``.
#: ``open`` is judged separately: a bare ``.open()`` reads, so only a mode
#: argument makes it write-capable.
#:
#: The test is by attribute NAME, so it cannot tell ``Path.replace`` from
#: ``str.replace``. That over-strictness is deliberate and points the safe way:
#: a read-only function has no need to call anything named ``replace``, and the
#: alternative — inferring the receiver's type — is exactly the inference an
#: attacker of this guarantee would defeat first.
WRITE_CAPABLE = frozenset({
    "unlink", "rename", "replace", "mkdir", "rmdir", "touch", "chmod",
    "symlink_to",
})

sys.path.insert(0, str(SKILL_DIR / "scripts"))

import pipeline_auto_state as pas  # noqa: E402


def module_source() -> str:
    return Path(pas.__file__).read_text(encoding="utf-8")


def function_node(source: str, name: str) -> ast.FunctionDef:
    """The single ``def name`` node in ``source``, as an AST subtree."""
    found = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name == name]
    if len(found) != 1:
        raise AssertionError(f"expected exactly one def {name!r}, found {len(found)}")
    return found[0]


def write_capable_calls(source: str, name: str) -> list[str]:
    """Every write-capable call inside ONE function's own subtree.

    Scoped to a function rather than to the module on purpose. The module is
    allowed to grow a writer — a later phase lands the atomic tracker write —
    and a module-wide ban would have to be deleted the day that arrives, taking
    the guarantee with it. Scoped here, the writer lands beside ``validate_run``
    and ``validate_run`` still cannot write.

    Calls that ``validate_run`` makes into OTHER module functions are outside
    the subtree and unchecked; the claim is about this function's own body.
    """
    calls = []
    for node in ast.walk(function_node(source, name)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        if attr.startswith("write") or attr in WRITE_CAPABLE:
            calls.append(attr)
        elif attr == "open" and (
            node.args or any(word.arg == "mode" for word in node.keywords)
        ):
            calls.append("open(mode)")
    return calls


def with_statement_in(source: str, name: str, statement: str) -> str:
    """The real module source with one statement spliced into ``name``'s body.

    Structural rather than textual: the statement is placed immediately before
    the function's last top-level statement, at that statement's own indent, so
    it lands inside the body no matter how the body is later reshaped.
    """
    last = function_node(source, name).body[-1]
    lines = source.splitlines(keepends=True)
    lines.insert(last.lineno - 1, " " * last.col_offset + statement + "\n")
    return "".join(lines)


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

    def test_a_rejection_is_read_only_because_validate_run_cannot_write(self):
        """Pins the property that actually makes every rejection read-only.

        Three separate claims, each stated as narrowly as it is checked:

        1. The module imports nothing outside ``ALLOWED_IMPORTS``. That bounds
           what is reachable; it does NOT bound writing, because ``pathlib``
           alone can write, unlink, rename and mkdir. An earlier revision of
           this docstring promised the allowlist's members "open no file for
           writing", which was false of ``pathlib`` the day it was added.
        2. No ``FORBIDDEN_BUILTINS`` call appears anywhere in the module — the
           whole file, every function, unchanged in strictness.
        3. ``validate_run``'s own body contains no write-capable call. This is
           the read-only stop the exception docstrings claim, and it is scoped
           to the one function that claims it, so the atomic tracker writer a
           later phase adds elsewhere in this module does not have to weaken it.

        The separate read-only-directory test below is the runtime companion:
        this one pins what ``validate_run`` *can* do, that one pins what it
        *does* when the filesystem refuses.
        """
        source = module_source()
        tree = ast.parse(source)
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
        for builtin in FORBIDDEN_BUILTINS:
            self.assertNotIn(builtin, called)
        self.assertEqual(
            write_capable_calls(source, "validate_run"), [],
            "validate_run must stay read-only; it may not create, replace, "
            "remove or re-permission anything on disk")

    def test_the_read_only_check_fails_on_a_write_inside_validate_run(self):
        """A test of the test: the guarantee above must be falsifiable.

        The previous check was scoped to the whole module and looked only at
        imports and bare-name builtins. A review spliced a function calling
        ``write_text``, ``unlink``, ``rename`` and ``mkdir`` into the module and
        the suite stayed green; splicing ``unlink`` into ``validate_run``
        itself also stayed green, because a no-op unlink leaves the bytes and
        the directory listing alone and nothing else was watching.

        So each write-capable call is spliced into the REAL module source, one
        at a time, and must be detected. Failing this means the read-only claim
        above has quietly stopped being a claim.
        """
        source = module_source()
        for statement in (
            '(run_dir / "progress.md").write_text("owned", encoding="utf-8")',
            '(run_dir / "progress.md").write_bytes(b"owned")',
            '(run_dir / "stale.md").unlink(missing_ok=True)',
            '(run_dir / "progress.md").rename(run_dir / "progress.bak")',
            '(run_dir / "staged.md").replace(run_dir / "progress.md")',
            '(run_dir / "scratch").mkdir(exist_ok=True)',
            '(run_dir / "scratch").rmdir()',
            '(run_dir / "progress.md").touch()',
            '(run_dir / "progress.md").chmod(0o644)',
            '(run_dir / "link.md").symlink_to(run_dir / "progress.md")',
            '(run_dir / "note.md").open("w").close()',
            '(run_dir / "note.md").open(mode="w").close()',
        ):
            mutant = with_statement_in(source, "validate_run", statement)
            with self.subTest(statement=statement):
                self.assertNotEqual(mutant, source)
                self.assertNotEqual(
                    write_capable_calls(mutant, "validate_run"), [],
                    "a write-capable call inside validate_run went undetected")

    def test_the_read_only_check_leaves_the_rest_of_the_module_free_to_write(self):
        """The scope is a promise in both directions.

        A later phase lands an atomic tracker writer in this same module. It
        must not have to argue with this test, or the test gets deleted and the
        guarantee goes with it. The same calls that are refused inside
        ``validate_run`` are unremarkable outside it — and a bare, read-mode
        ``.open()`` stays legal inside it, since it is the mode that writes.
        """
        source = module_source()
        writer = source + (
            '\n\ndef _atomic_write(run_dir: Path, text: str) -> None:\n'
            '    staged = run_dir / "progress.md.tmp"\n'
            '    staged.write_text(text, encoding="utf-8")\n'
            '    staged.replace(run_dir / "progress.md")\n'
            '    (run_dir / "progress.md").chmod(0o644)\n'
        )
        self.assertEqual(write_capable_calls(writer, "validate_run"), [])
        self.assertNotEqual(write_capable_calls(writer, "_atomic_write"), [])
        for reading in ('(run_dir / "progress.md").open().close()',
                        '(run_dir / "progress.md").open(encoding="utf-8").close()'):
            with self.subTest(statement=reading):
                mutant = with_statement_in(source, "validate_run", reading)
                self.assertEqual(write_capable_calls(mutant, "validate_run"), [])

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


def make_run(case: unittest.TestCase, text: str | None = None) -> Path:
    """A temp run directory holding one progress.md. Removed when the case ends."""
    run_dir = Path(tempfile.mkdtemp(prefix="pipeline-auto-"))
    case.addCleanup(shutil.rmtree, run_dir, ignore_errors=True)
    (run_dir / "progress.md").write_text(
        valid_text() if text is None else text, encoding="utf-8"
    )
    return run_dir


def empty_run(case: unittest.TestCase) -> Path:
    run_dir = Path(tempfile.mkdtemp(prefix="pipeline-auto-"))
    case.addCleanup(shutil.rmtree, run_dir, ignore_errors=True)
    return run_dir


class ForeignSchemaStopTests(unittest.TestCase):
    """Every rejection path leaves the run directory exactly as it was found.

    `superb:pipeline` works today. A `pipeline-auto` controller that parsed one
    of its trackers would rewrite it into `pipeline-auto/v1` shape on the first
    transition, destroying a live run of the other skill. The marker check is
    the only thing standing between the two, so each case here asserts the
    exception AND the bytes AND that no file was added to the directory.
    """

    def assert_untouched(self, run_dir: Path, names: list[str]) -> None:
        self.assertEqual(sorted(entry.name for entry in run_dir.iterdir()), names)

    def test_a_pipeline_run_v2_tracker_is_rejected_and_left_byte_identical(self):
        """The named fault: delete the marker check and a v2 run is parsed,
        then rewritten into pipeline-auto shape by the first transition."""
        foreign = (FOREIGN_FIXTURES / "valid-v2-progress.md").read_bytes()
        self.assertIn(b"pipeline-run/v2", foreign)
        run_dir = make_run(self, foreign.decode("utf-8"))
        progress = run_dir / "progress.md"
        with self.assertRaises(pas.ForeignSchemaError) as caught:
            pas.validate_run(run_dir)
        self.assertEqual(progress.read_bytes(), foreign)
        self.assert_untouched(run_dir, ["progress.md"])
        self.assertRegex(str(caught.exception), NAMES_THE_OTHER_SKILL)
        self.assertIn("pipeline-run/v2", str(caught.exception))
        self.assertIn("no files were changed", str(caught.exception))

    def test_a_legacy_v1_tracker_is_rejected_and_left_byte_identical(self):
        """The other skill's pre-marker format: no marker line at all."""
        legacy = (FOREIGN_FIXTURES / "legacy-v1-progress.md").read_bytes()
        run_dir = make_run(self, legacy.decode("utf-8"))
        with self.assertRaises(pas.ForeignSchemaError) as caught:
            pas.validate_run(run_dir)
        self.assertEqual((run_dir / "progress.md").read_bytes(), legacy)
        self.assert_untouched(run_dir, ["progress.md"])
        self.assertRegex(str(caught.exception), NAMES_THE_OTHER_SKILL)
        self.assertIn("pipeline-run/v1", str(caught.exception))

    def test_an_unknown_marker_is_rejected(self):
        """The dangerous one: exactly what a FUTURE version of this same skill
        would write. Accepting it is how a newer run's state gets mangled by an
        older controller, so an unrecognised marker stops just as hard as a
        foreign one."""
        text = "<!-- pipeline-auto/v9 -->\n# Whatever\n"
        run_dir = make_run(self, text)
        with self.assertRaises(pas.ForeignSchemaError):
            pas.validate_run(run_dir)
        self.assertEqual((run_dir / "progress.md").read_text(encoding="utf-8"), text)
        self.assert_untouched(run_dir, ["progress.md"])

    def test_a_missing_progress_file_is_a_read_only_stop(self):
        run_dir = empty_run(self)
        with self.assertRaises(pas.ForeignSchemaError):
            pas.validate_run(run_dir)
        self.assertEqual(list(run_dir.iterdir()), [])

    def test_an_empty_progress_file_is_a_read_only_stop(self):
        """Zero bytes has no marker to check, and must not be mistaken for a
        fresh run this module may initialise over the top of."""
        run_dir = make_run(self, "")
        with self.assertRaises(pas.ForeignSchemaError):
            pas.validate_run(run_dir)
        self.assertEqual((run_dir / "progress.md").read_bytes(), b"")
        self.assert_untouched(run_dir, ["progress.md"])

    def test_each_read_only_stop_has_a_distinguishable_diagnostic(self):
        """A user who ran both skills in one repository has to learn WHICH
        skill owns this directory, not just that a schema did not match. Four
        different faults, four different sentences."""
        details = []
        for text in (None, "", "# Pipeline — Progress Tracker\n",
                     "<!-- pipeline-auto/v2 -->\n"):
            run_dir = empty_run(self) if text is None else make_run(self, text)
            with self.assertRaises(pas.ForeignSchemaError) as caught:
                pas.validate_run(run_dir)
            details.append(str(caught.exception).replace(str(run_dir), "<run>"))
        self.assertEqual(len(set(details)), 4, details)
        for detail in details:
            self.assertRegex(detail, NAMES_THE_OTHER_SKILL)
            self.assertIn("no files were changed", detail)

    def test_a_malformed_but_correctly_marked_tracker_raises_validation_not_foreign(self):
        """Ours-but-broken is a different fault from not-ours, and telling a
        user the wrong one sends them to the wrong skill."""
        broken = valid_text().replace("| worker_limit | 6 |", "| worker_limit | 6 | 6 |")
        self.assertNotEqual(broken, valid_text())
        run_dir = make_run(self, broken)
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.validate_run(run_dir)
        self.assertNotIsInstance(caught.exception, pas.ForeignSchemaError)
        self.assertEqual((run_dir / "progress.md").read_text(encoding="utf-8"), broken)
        self.assert_untouched(run_dir, ["progress.md"])

    def test_a_valid_run_returns_its_tracker(self):
        run_dir = make_run(self)
        tracker = pas.validate_run(run_dir)
        self.assertEqual(tracker["run"]["schema"], pas.SCHEMA)
        self.assertEqual(len(tracker["stages"]), 12)
        self.assert_untouched(run_dir, ["progress.md"])

    def test_a_valid_run_is_not_rewritten_by_being_validated(self):
        """Validation is a read. An implementation that normalised on read
        would pass every rejection test above and still corrupt a live run."""
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()
        pas.validate_run(run_dir)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)
        self.assert_untouched(run_dir, ["progress.md"])

    def test_validating_a_read_only_tracker_succeeds(self):
        """The byte check above cannot see a normalising read.

        ``render_tracker(parse_tracker(valid))`` is byte-identical to ``valid``
        by construction, so a validator that helpfully rewrote what it read
        would leave the same bytes behind and every assertion above would still
        pass. Taking write permission away makes the capability itself the
        thing under test: a validator that writes raises PermissionError here,
        whatever bytes it intended to write. It also pins the real case —
        a tracker on a read-only checkout must still be *readable*.

        The DIRECTORY is read-only too, not just the file, because ``0o444`` on
        ``progress.md`` alone stops only the naive writer. An atomic writer —
        stage a sibling temp file, then rename it over the target — never opens
        ``progress.md`` for writing at all, and a rename obeys the permissions
        of the containing directory, not of the file being replaced. ``0o555``
        on the run directory denies both the create and the rename; the
        ``assert_untouched`` then catches the staged file a writer that got
        half-way would leave lying beside the tracker.
        """
        run_dir = make_run(self)
        progress = run_dir / "progress.md"
        # LIFO: the file is re-permissioned first, then the directory, then
        # `make_run`'s rmtree — which needs the directory writable again.
        self.addCleanup(run_dir.chmod, 0o755)
        self.addCleanup(progress.chmod, 0o644)
        progress.chmod(0o444)
        run_dir.chmod(0o555)
        # Running as root, or on a filesystem that ignores the mode: chmod
        # proves nothing, and a green assertion here would be a false one.
        if os.access(progress, os.W_OK) or os.access(run_dir, os.W_OK):
            self.skipTest("cannot drop write permission for this user")
        tracker = pas.validate_run(run_dir)
        self.assertEqual(tracker["run"]["schema"], pas.SCHEMA)
        self.assert_untouched(run_dir, ["progress.md"])


def with_stages(states: list[str], actions: list[str] | None = None) -> str:
    """The valid fixture with its twelve stage rows replaced wholesale.

    Surgery on the fixture's own bytes, like every other rejection input here,
    so each case states exactly which cell made the tracker impossible.
    """
    actions = actions if actions is not None else ["-"] * len(states)
    lines = valid_text().splitlines(keepends=True)
    start = next(index for index, line in enumerate(lines)
                 if line.startswith("| 01 | "))
    rows = [f"| {stage} | {state} | {action} |\n"
            for stage, state, action in zip(pas.STAGES, states, actions)]
    return "".join(lines[:start] + rows + lines[start + 12:])


class StageSectionTests(unittest.TestCase):
    """``## Stage`` is the only record that stages 01-07 ever ran.

    Their outputs — the reconciled intent brief, the four human answers, the
    design, the spec, the plans — are not in Git and are never named by the
    task table. A controller resuming after a compaction reads this section or
    it reads nothing, so every impossible shape of it has to be refused here.
    """

    def test_the_fixture_is_stages_01_through_12_in_order(self):
        """Catches a mis-built enum: ``range(12)`` (00..11), an off-by-one
        upper bound (01..11, so stage 12 has no row to be pending in), or an
        unpadded ``f"{index}"`` that spells stage 01 as ``1`` and stops
        matching the tracker's own rows."""
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual(pas.STAGES, tuple(f"{n:02d}" for n in range(1, 13)))
        self.assertEqual(tuple(row["stage"] for row in tracker["stages"]), pas.STAGES)

    def test_a_pending_stage_before_an_active_one_is_rejected(self):
        """The compaction fault itself: stage 02 is running, stage 01 reads
        unstarted, and a resuming controller re-dispatches the three intent
        readers, producing a different brief and forking the run from its own
        history. Catches an implementation that validates each row in isolation
        and never compares one row's state against its neighbours'."""
        states = ["pending", "active"] + ["pending"] * 10
        actions = ["-", "synthesise-questions"] + ["-"] * 10
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))

    def test_a_stage_completing_before_an_earlier_one_started_is_rejected(self):
        """Stage 02 is finished while stage 01 reads unstarted, and no stage is
        active. Catches the narrower guard someone reaches for first — 'nothing
        pending may precede the ACTIVE stage' — which has no active row to
        anchor on here and waves the whole tracker through, leaving a run that
        skipped stage 01 outright looking resumable."""
        states = ["pending", "complete"] + ["pending"] * 10
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states))

    def test_two_active_stages_are_rejected(self):
        """Two actives are monotone by state order, so the ordering check alone
        passes them. Catches dropping the separate cardinality guard: with two
        actives ``derive_next_action`` silently returns whichever comes first
        and the run works on a stage it never recorded as started."""
        states = ["active", "active"] + ["pending"] * 10
        actions = ["read-intent", "synthesise-questions"] + ["-"] * 10
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))

    def test_a_missing_stage_row_is_rejected(self):
        """Catches validating only the rows that are present. Eleven rows are
        internally consistent; the twelfth stage has simply vanished, and a run
        that never records stage 12 can never be resumed into it."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(valid_text().replace("| 12 | pending | - |\n", ""))

    def test_a_duplicated_stage_row_is_rejected(self):
        """Catches a length check standing in for an identity check: twelve
        rows are present, but stage 10 appears twice and stage 11 not at all.
        Membership tests (``in STAGES``, ``set(...)``) miss it the same way."""
        text = valid_text().replace("| 11 | pending | - |\n",
                                    "| 10 | pending | - |\n")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_the_active_stage_must_name_its_next_action(self):
        """An active stage with ``-`` for an action is a run that knows it is
        mid-stage and not what to do next. Catches omitting the pairing check:
        ``derive_next_action`` would then hand the controller the literal
        ``-`` as its instruction."""
        states = ["complete"] * 8 + ["active"] + ["pending"] * 3
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states))

    def test_a_pending_stage_cannot_carry_a_next_action(self):
        """A leftover action on a non-active row is a stale instruction that
        outlives the stage that wrote it. Catches checking only the active
        direction of the pairing and leaving the other half unenforced."""
        states = ["complete"] * 8 + ["active"] + ["pending"] * 3
        actions = ["-"] * 8 + ["run-task-gate-P02-T01", "debug-later"] + ["-", "-"]
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))

    def test_no_active_stage_with_work_still_pending_is_rejected(self):
        """The validator and the dispatcher must not hold different opinions
        about the same tracker. All-pending is monotone and carries at most one
        active, so every other check waves it through — and then
        ``derive_next_action`` has no row to read an action from and no grounds
        to report the run complete, leaving a tracker that passes
        ``validate_run`` with no derivable next action. Catches omitting the
        guard and leaving that disagreement in place; the shape is illegal
        because a stage closes only as its successor opens, in one transition."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(["pending"] * 12))

    def test_a_half_finished_run_with_nothing_active_is_rejected(self):
        """The same rule where it is easy to get wrong: stages 01-08 complete,
        09-12 pending, nothing active. Catches a guard written as 'reject
        all-pending', which reads the one obvious instance of the shape instead
        of the shape, and passes the tracker a run stranded mid-flight leaves
        behind. Only the terminal table — all twelve ``complete`` — may have no
        active stage."""
        states = ["complete"] * 8 + ["pending"] * 4
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states))

    def test_an_unknown_stage_state_is_rejected(self):
        """Catches letting an out-of-enum state reach the ordering comparison,
        where it surfaces as a bare ``ValueError`` from the sort key rather
        than as this module's own read-only-stop exception family — so the
        caller that branches on ``TrackerError`` never sees it."""
        states = ["complete"] * 8 + ["paused"] + ["pending"] * 3
        actions = ["-"] * 8 + ["run-task-gate-P02-T01"] + ["-"] * 3
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))


class NextActionTests(unittest.TestCase):
    def test_a_queued_escalation_outranks_the_active_stage(self):
        """The fixture is mid-stage-09 with escalation E-1 queued. Catches
        reading the stage first: the controller would dispatch stage 09 work
        while a question it raised is still waiting on a human."""
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual(pas.derive_next_action(tracker), "await-escalation-batch")

    def test_an_asked_escalation_also_holds_the_run(self):
        """Catches treating only ``queued`` as blocking. ``asked`` is the state
        an escalation is in once its batch has gone to the human — the longest
        window in the run — and a controller that resumes dispatching during it
        answers the question itself instead of waiting."""
        tracker = pas.parse_tracker(valid_text())
        for row in tracker["escalations"]:
            if row["state"] == "queued":
                row["state"] = "asked"
        self.assertEqual(pas.derive_next_action(tracker), "await-escalation-batch")

    def test_without_a_pending_escalation_the_active_stage_supplies_the_action(self):
        """The fixture still holds an ``answered`` escalation. Catches testing
        the list for emptiness rather than for pending members, which would
        park the run forever on escalations that are already resolved."""
        tracker = pas.parse_tracker(valid_text())
        tracker["escalations"] = [row for row in tracker["escalations"]
                                  if row["state"] == "answered"]
        self.assertEqual(pas.derive_next_action(tracker), "run-task-gate-P02-T01")

    def test_a_run_whose_stages_are_all_complete_is_complete(self):
        """Catches a fallthrough that returns the last row's ``-``, or ``None``,
        instead of the terminal verdict the controller stops on."""
        tracker = pas.parse_tracker(with_stages(["complete"] * 12))
        tracker["escalations"] = []
        self.assertEqual(pas.derive_next_action(tracker), "complete")

    def test_a_hand_mutated_tracker_with_no_active_stage_still_refuses_to_report_complete(self):
        """The dispatcher's defensive backstop, pinned on the one path that can
        still reach it. ``_validate_stages`` refuses this shape, so no parsed
        tracker arrives here holding it — but ``derive_next_action`` takes a
        plain ``dict`` and callers edit trackers in place between parsing and
        dispatching, exactly as this test does. Catches deleting the raise as
        'unreachable': an edited tracker would then be reported ``complete``,
        ending the run at stage 09 with stages 10-12 unwritten."""
        tracker = pas.parse_tracker(valid_text())
        tracker["escalations"] = []
        for row in tracker["stages"]:
            if row["stage_state"] == "active":
                row["stage_state"] = "pending"
                row["next_action"] = "-"
        with self.assertRaises(pas.TrackerValidationError):
            pas.derive_next_action(tracker)


class SuiteIsWhollyCollectedTests(unittest.TestCase):
    """``if __name__ == "__main__": unittest.main()`` must be the LAST statement.

    The mistake this guards against was made in this very file: fourteen new
    tests were appended *after* the main block. Python executes a module top to
    bottom, so a direct ``python3 test_pipeline_auto_state.py`` reached
    ``unittest.main()`` before those classes existed and collected only the 35
    tests defined above it — printing ``Ran 35 tests ... OK``, a green run that
    silently omitted the entire commit under test. Discovery imports the module
    without executing ``__main__`` and so found all 49, which is exactly why the
    hole survived: CI was green, and only someone running the file directly got
    the false all-clear — with no signal that anything was missing.
    """

    def module_source(self) -> str:
        return Path(__file__).resolve().read_text(encoding="utf-8")

    def test_nothing_is_defined_after_the_main_block(self):
        """Catches re-introducing the fault by appending below the main block.
        Asserts the structural fact rather than a symptom: the guard holds for a
        helper, a constant or a whole ``TestCase``, and it holds whether or not
        anyone happens to run the file directly afterwards."""
        body = ast.parse(self.module_source()).body
        guards = [index for index, node in enumerate(body)
                  if isinstance(node, ast.If) and "__main__" in ast.dump(node.test)]
        self.assertEqual(len(guards), 1, "expected exactly one __main__ guard")
        trailing = [type(node).__name__ for node in body[guards[0] + 1:]]
        self.assertEqual(
            trailing, [],
            "definitions follow the __main__ guard; a direct run of this file "
            f"will silently skip them: {trailing}")

    def test_a_direct_run_collects_the_same_tests_as_discovery(self):
        """The symptom itself, asserted as a count. Loads a second, complete
        copy of this file and compares its test count against what the loader
        can see in the module object this process is actually executing. Under
        the fault the running module is still mid-body — the classes below the
        guard do not exist yet — and the two counts diverge."""
        spec = importlib.util.spec_from_file_location(
            "_pipeline_auto_state_suite_probe", Path(__file__).resolve())
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        loader = unittest.TestLoader()
        running = loader.loadTestsFromModule(sys.modules[__name__]).countTestCases()
        complete = loader.loadTestsFromModule(probe).countTestCases()
        self.assertEqual(
            running, complete,
            f"this process collects {running} tests but the file defines "
            f"{complete}: part of the suite is not being run")


if __name__ == "__main__":
    unittest.main()
