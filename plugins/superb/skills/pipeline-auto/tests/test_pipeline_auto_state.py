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
#: ``re`` was listed here for the id grammars ``## Intent``, ``## Questions``
#: and ``## Escalations`` are judged against — ``C-<n>``, ``H-<n>``, ``E-<n>``,
#: and the free token. It is listed no longer. Each of those is a prefix plus
#: ASCII digits, or a character class, and the module states them directly with
#: ``str.startswith``, ``isascii`` and ``isdigit`` at exactly the strictness
#: the patterns had. Nothing was loosened to make the import go away: a looser
#: "some non-empty cell" test would let a ``Q-<qid>`` quorum decision stand as
#: the answer to the one human gate, which is the authority that gate exists to
#: withhold, and ``GrammarTests`` below pins each grammar against that.
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


def with_stages(states: list[str], actions: list[str] | None = None,
                text: str | None = None) -> str:
    """The valid fixture with its twelve stage rows replaced wholesale.

    Surgery on the fixture's own bytes, like every other rejection input here,
    so each case states exactly which cell made the tracker impossible.

    ``text`` takes an already-edited copy instead, because the intent-conflict
    rule spans two sections and a stage: a case that has to move stage 03 AND
    rewrite the brief AND rewrite the questions cannot be built from three
    helpers that each start again from the pristine fixture.
    """
    actions = actions if actions is not None else ["-"] * len(states)
    lines = (valid_text() if text is None else text).splitlines(keepends=True)
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


#: Rows quoted from the fixture once, so each surgery below names exactly the
#: cell it changed instead of re-typing the row it meant to leave alone.
READER_1 = ("| reader-1 | reader | published | intent-reader-1 | "
            "scratch/intent-reader-1.md | - |")
READER_2 = ("| reader-2 | reader | published | intent-reader-2 | "
            "scratch/intent-reader-2.md | - |")
READER_3 = ("| reader-3 | reader | published | intent-reader-3 | "
            "scratch/intent-reader-3.md | - |")
INTENT_BRIEF = "| brief | brief | frozen | reconciled | scratch/intent-brief.md | C-001 |"
QUESTION_2 = "| axis-2 | synthesis | 2 | answered | H-2 |"
ESCALATION_1 = "| E-1 | 7c6b5a4938d2 | phase | queued | - | - |"
ESCALATION_2 = "| E-2 | - | run | answered | batch-1 | H-3 |"


def swap(old: str, new: str, text: str | None = None) -> str:
    """The valid fixture — or an already-edited copy of it — with one exact
    substring replaced.

    A ``str.replace`` whose pattern is absent is a silent no-op. A rejection
    case built on one would assert against the untouched fixture — which
    parses, so that case fails loudly — but a POSITIVE control built on one
    would pass while exercising nothing at all. Both are refused here rather
    than only the half that happens to be self-announcing.
    """
    text = valid_text() if text is None else text
    if old not in text:
        raise AssertionError(f"the fixture no longer contains {old!r}")
    return text.replace(old, new)


class IntentSectionTests(unittest.TestCase):
    """``## Intent`` is the run's only record of what the user actually asked.

    Three independent readings, reconciled into one brief whose conflicts are
    **flagged and never resolved**. A conflict quietly reconciled here is a
    requirement invented, and no later stage can tell an invented requirement
    from a read one — the run goes on reporting success against it.
    """

    def test_the_fixtures_three_readers_and_one_brief_are_accepted(self):
        """The positive control every rejection below is measured against.

        Catches an over-strict validator that refuses the legal shape: with the
        fixture itself rejected, every ``assertRaises`` below would pass for a
        reason it does not name and the section would be untested.
        """
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual([row["id"] for row in tracker["intent"]],
                         ["reader-1", "reader-2", "reader-3", "brief"])

    def test_two_readers_are_rejected_because_a_count_is_never_reduced(self):
        """Stage 01 dispatches exactly three readers, never two to fit capacity.

        Catches a validator that judges each row and never the roster: a brief
        reconciled from two readings renders identically to one reconciled from
        three, so the missing reading is invisible from here on.
        """
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(swap(READER_3 + "\n", ""))

    def test_a_reader_row_claiming_the_briefs_kind_is_rejected(self):
        """``ID`` and ``Kind`` must agree. Catches checking the id roster alone:
        a row that is a reader by id and a brief by kind lets the reconciliation
        step read three briefs and no readings."""
        text = swap(READER_3, "| reader-3 | brief | published | intent-reader-3 | "
                              "scratch/intent-reader-3.md | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_out_of_enum_intent_state_is_rejected(self):
        """The brief is parked in a state the schema does not define, and every
        other intent rule is satisfied. Catches omitting the membership guard:
        an unknown state is then neither published nor frozen, so the freeze and
        result rules below simply skip it and the row passes unjudged."""
        text = swap(INTENT_BRIEF, "| brief | brief | paused | reconciled | - | C-001 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_only_the_reconciled_brief_may_freeze(self):
        """``frozen`` is the immutability the brief earns at stage 03 and a
        reading never has. Catches validating state membership without asking
        WHICH rows may hold which state: a frozen reader claims an authority
        that was never conferred on it. The brief is left unpublished here so
        the roster and result rules stay out of the way."""
        text = swap(READER_3, "| reader-3 | reader | frozen | intent-reader-3 | - | - |")
        text = swap(INTENT_BRIEF,
                    "| brief | brief | pending | reconciled | - | C-001 |", text)
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_published_reader_must_name_its_immutable_result(self):
        """A reading that published without a result file cannot be re-read.
        Catches omitting the pairing: reconciliation then has three published
        readers and only two readings to reconcile, and invents the third."""
        text = swap(READER_1, "| reader-1 | reader | published | intent-reader-1 | - | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unpublished_reader_cannot_claim_a_result(self):
        """The other half of the same pairing. Catches enforcing only the
        published direction: a dispatched reader naming a result file that does
        not exist yet is a reading the reconciler will read as finished."""
        text = swap(READER_1, "| reader-1 | reader | dispatched | intent-reader-1 | "
                              "scratch/intent-reader-1.md | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_conflicts_belong_to_the_brief_and_never_to_a_reader(self):
        """A reading reports what it read; only reconciliation can see that two
        readings disagree. Catches accepting a conflict on a reader row: the
        conflict is then recorded where the stage-03 ranking does not look for
        it, and an unresolved conflict never reaches the human gate."""
        text = swap(READER_1, "| reader-1 | reader | published | intent-reader-1 | "
                              "scratch/intent-reader-1.md | C-002 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_three_readers_naming_one_result_file_are_one_reading(self):
        """Three READINGS, not three rows. The roster check proves the ids are
        ``reader-1``, ``reader-2``, ``reader-3`` and nothing more, so three rows
        citing the same result file satisfy it completely.

        Catches checking the roster by id alone. Every conflict this section can
        flag is a disagreement BETWEEN readings; one file cited three times can
        disagree with nothing, so the ``Conflicts`` cell is legitimately empty,
        stage 03 asks nothing, and the decorrelation the whole design rests on
        has collapsed with no downstream stage able to notice it did.
        """
        text = swap(READER_1, "| reader-1 | reader | published | intent-reader-1 | "
                              "scratch/intent-reader-2.md | - |")
        text = swap(READER_3, "| reader-3 | reader | published | intent-reader-3 | "
                              "scratch/intent-reader-2.md | - |", text)
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_two_unpublished_readers_sharing_a_dash_result_are_not_a_collision(self):
        """The distinctness rule is about readings, not about the absence of
        one. Catches implementing it as ``len(set(results)) != 3`` over the raw
        column: two readers still in flight both hold ``-``, and the roster
        would be refused for the crime of not having finished yet."""
        text = swap(READER_1, "| reader-1 | reader | dispatched | intent-reader-1 | - | - |")
        text = swap(READER_3, "| reader-3 | reader | dispatched | intent-reader-3 | - | - |",
                    text)
        text = swap(INTENT_BRIEF,
                    "| brief | brief | pending | reconciled | - | C-001 |", text)
        tracker = pas.parse_tracker(text)
        self.assertEqual([row["result"] for row in tracker["intent"][:3]],
                         ["-", "scratch/intent-reader-2.md", "-"])

    def test_the_conflicts_cell_refuses_prose(self):
        """The reviewer's third probe, and the one that reads worst in a
        tracker: ``resolved-by-controller`` in the cell whose entire purpose is
        to record that nothing resolved the conflict.

        Catches leaving the cell free-form. The conflict is then "recorded",
        the run reports it recorded, and no id exists for the gate to claim —
        so the rule that every flagged conflict reaches the human has nothing
        to enforce, and the run has resolved a conflict it may never resolve.
        """
        for conflicts in ("resolved-by-controller", "resolved", "C-001 and C-002",
                          "C-", "X-001", "C-1x"):
            with self.subTest(conflicts=conflicts):
                text = swap(INTENT_BRIEF, "| brief | brief | frozen | reconciled | "
                                          f"scratch/intent-brief.md | {conflicts} |")
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_one_conflict_flagged_twice_cannot_buy_itself_two_slots(self):
        """``C-001,C-001`` with two ``intent-conflict`` questions balances the
        claim count exactly, so the gate rule waves it through: one conflict has
        taken two of the four slots the run has, and the conflict ranked fourth
        is the one pushed out of the single human gate by a duplicate.

        Stated as its own case because the claim count hides it otherwise — one
        duplicated id and one question is already refused for the count, which
        would let this check be deleted with the suite still green.
        """
        text = swap(INTENT_BRIEF, "| brief | brief | frozen | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-001 |")
        text = with_questions([
            "| axis-1 | intent-conflict | 1 | answered | H-1 |",
            "| axis-2 | intent-conflict | 2 | answered | H-2 |",
        ], text)
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_list_of_conflict_ids_is_the_shape_the_cell_takes(self):
        """The positive control for the grammar: several ids, comma-separated,
        each claimed by a question. Catches a grammar so tight it admits only
        one conflict, which would make the second disagreement between two
        readings unrecordable and so, in practice, resolved by silence."""
        text = swap(INTENT_BRIEF, "| brief | brief | frozen | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-002 |")
        text = with_questions([
            "| C-001 | intent-conflict | 1 | answered | H-1 |",
            "| C-002 | intent-conflict | 2 | answered | H-2 |",
            "| axis-3 | synthesis | 3 | asked | - |",
        ], text)
        tracker = pas.parse_tracker(text)
        self.assertEqual(tracker["intent"][3]["conflicts"], "C-001,C-002")

    def test_the_brief_cannot_publish_before_all_three_readers_have(self):
        """Reader 2 is still in flight while the brief is frozen. Catches
        validating rows independently: the reconciled brief is then a
        reconciliation of whatever happened to be finished, and the third
        reading lands after the brief that was supposed to contain it."""
        text = swap("| reader-2 | reader | published | intent-reader-2 | "
                    "scratch/intent-reader-2.md | - |",
                    "| reader-2 | reader | dispatched | intent-reader-2 | - | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_published_brief_must_name_its_result(self):
        """Catches omitting the brief's own result check: stage 04 onwards cites
        the intent brief by path, and a published brief with no path is a run
        whose every later ``consistent_with`` citation anchors to nothing."""
        text = swap(INTENT_BRIEF,
                    "| brief | brief | published | reconciled | - | C-001 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unpublished_brief_cannot_claim_a_result(self):
        """Catches the mirror omission: a brief still being written that already
        names its output file is one a resuming controller will cite rather
        than finish."""
        text = swap(INTENT_BRIEF, "| brief | brief | dispatched | reconciled | "
                                  "scratch/intent-brief.md | C-001 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_the_brief_cannot_freeze_before_stage_03_closes(self):
        """The brief is immutable only AFTER the human gate — "a contradicting
        finding escalates, the human amends". Catches freezing on publication
        instead: the conflicts stage 03 exists to put to the user are sealed
        into the brief before the user is asked about them, and the single gate
        is reduced to a formality over an answer already chosen."""
        states = ["complete", "active"] + ["pending"] * 10
        actions = ["-", "synthesise-questions"] + ["-"] * 10
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))


def with_questions(rows: list[str], text: str | None = None) -> str:
    """The fixture — or an already-edited copy — with its ``## Questions`` body
    replaced wholesale.

    The row-count rules need tables the fixture's two rows cannot express, and
    splicing rows in next to a heading is how a case ends up rejected for a
    stray blank line instead of for the rule it names.

    An EMPTY body is the table with no data rows, not a table with a blank line
    in it. The separator row keeps its own newline and the section's single
    blank line is the one already standing before ``## Quorum``; taking both
    would hand the parser a two-blank-line gap and every case built on it would
    be rejected for spacing rather than for the rule under test.
    """
    text = valid_text() if text is None else text
    #: Anchored on the SECTION, not on a row id. The first question row's id is
    #: now ``C-001`` — the id of the conflict it claims — and the brief's
    #: Conflicts cell renders as ``| C-001 |`` several lines earlier, so a
    #: search for the id alone would splice the replacement rows into
    #: ``## Intent``. The separator row is the last line the section header
    #: owns; the body begins on the line after it.
    head = text.index("## Questions")
    start = text.index("\n", text.index("| --- |", head)) + 1
    end = text.index("\n\n## Quorum")
    if not rows:
        return text[:start] + text[end + 1:]
    return text[:start] + "\n".join(rows) + text[end:]


class QuestionSectionTests(unittest.TestCase):
    """``## Questions`` holds the at-most-four questions of the one human gate.

    Their answers are the only requirements this run may treat as
    unimpeachable, so which questions occupy the four slots is the single most
    consequential ranking the controller makes.
    """

    def test_four_questions_are_legal(self):
        """The positive control for the cap. Catches an off-by-one that refuses
        the fourth slot: stage 02 would then be silently limited to three and
        the fourth-ranked open decision never reaches the user at all."""
        text = with_questions([
            "| C-001 | intent-conflict | 1 | answered | H-1 |",
            "| axis-2 | synthesis | 2 | answered | H-2 |",
            "| axis-3 | synthesis | 3 | asked | - |",
            "| axis-4 | synthesis | 4 | asked | - |",
        ])
        self.assertNotEqual(text, valid_text())
        tracker = pas.parse_tracker(text)
        self.assertEqual(len(tracker["questions"]), 4)

    def test_a_fifth_question_is_rejected(self):
        """Stage 03 is one ``AskUserQuestion`` call of at most four questions.
        Catches dropping the cap: a fifth row records a question the single
        gate physically cannot have asked, and its ``answered`` state would
        then attribute an answer to a human who was never shown it."""
        text = with_questions([
            "| C-001 | intent-conflict | 1 | answered | H-1 |",
            "| axis-2 | synthesis | 2 | answered | H-2 |",
            "| axis-3 | synthesis | 3 | asked | - |",
            "| axis-4 | synthesis | 4 | asked | - |",
            "| axis-5 | synthesis | 5 | asked | - |",
        ])
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_duplicated_question_axis_is_rejected(self):
        """Catches a length check standing in for an identity check: two rows
        on one axis spend two of the four slots on the same decision, and the
        answer recorded second silently overwrites the first."""
        text = swap(QUESTION_2, "| C-001 | synthesis | 2 | answered | H-2 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_slots_must_be_one_through_n_in_order(self):
        """Catches validating slots as a set or as a bound: a gap at slot 3
        means a question was ranked, dropped, and never asked, while the rows
        that remain still claim to be the top four."""
        text = swap(QUESTION_2, "| axis-2 | synthesis | 4 | answered | H-2 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_out_of_enum_question_origin_is_rejected(self):
        """Catches letting an unknown origin reach the ranking comparison, where
        ``_QUESTION_ORIGINS.index`` raises a bare ``ValueError`` — outside this
        module's exception family, so the caller that branches on
        ``TrackerError`` never sees the read-only stop it was promised."""
        text = swap(QUESTION_2, "| axis-2 | guesswork | 2 | answered | H-2 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_synthesised_question_cannot_take_a_slot_above_an_intent_conflict(self):
        """An unresolved intent conflict is by definition higher blast radius
        than anything stage 02 synthesised, so it takes the earlier slot.

        Catches ranking the four slots by the synthesiser's own score alone: a
        conflict between two readings of the user's prompt is then ranked
        against downstream design questions, and pushed out of the four
        entirely by enough of them — leaving the run to resolve the conflict
        itself, which is the one thing stage 01 forbids.
        """
        text = swap("| C-001 | intent-conflict | 1 | answered | H-1 |\n"
                    "| axis-2 | synthesis | 2 | answered | H-2 |",
                    "| axis-2 | synthesis | 1 | answered | H-2 |\n"
                    "| C-001 | intent-conflict | 2 | answered | H-1 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_out_of_enum_question_state_is_rejected(self):
        """The row carries no decision, so every other question rule passes it.
        Catches omitting the state enum: a question in an undefined state is
        neither asked nor answered, and stage 03 closes over it."""
        text = swap(QUESTION_2, "| axis-2 | synthesis | 2 | skipped | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_answered_question_records_a_human_decision_id(self):
        """A quorum can never answer the one human gate. Catches accepting any
        non-``-`` decision: a ``Q-`` id here records three agreeing machines as
        the unimpeachable requirement every later contradiction is measured
        against, which is precisely the authority the gate exists to withhold."""
        text = swap("| C-001 | intent-conflict | 1 | answered | H-1 |",
                    "| C-001 | intent-conflict | 1 | answered | Q-3f2a1b0c9d8e |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unanswered_question_cannot_carry_a_decision(self):
        """Catches enforcing only the answered direction: a decision attached to
        a question still in flight is an answer recorded before the human gave
        one, and it reads as ``Provenance: human`` forever after."""
        text = swap(QUESTION_2, "| axis-2 | synthesis | 2 | asked | H-2 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)


#: Stages for a run parked mid-stage-03: the gate is open, the question has not
#: been put yet, and a flagged conflict is therefore simply not yet asked.
STAGE_03_OPEN = (["complete"] * 2 + ["active"] + ["pending"] * 9,
                 ["-", "-", "ask-the-one-human-gate"] + ["-"] * 9)


class IntentConflictsReachTheGateTests(unittest.TestCase):
    """A flagged intent conflict must occupy a stage-03 question slot.

    ``_validate_intent`` and ``_validate_questions`` each judge one section and
    neither can see this. The brief may flag three conflicts while every
    question row reads ``Origin: synthesis``; both sections pass, stage 03
    closes, the brief freezes, and the run reports success with three conflicts
    recorded and none of them ever asked.

    The ranking rule in ``## Questions`` is not this rule and cannot be. It
    orders the conflict-derived questions that happen to exist — relative order
    among whatever rows are present — and an empty set is trivially ordered.
    This is the rule that populates the set.

    It populates it by CORRESPONDENCE: an ``intent-conflict`` question's ``ID``
    is the id of the conflict it puts to the human, and the flagged set and the
    claimed set must be equal. Counting the two instead left the fault standing
    in a shape that balances — two conflicts, two questions, both about the
    first — so the cases below are written against the counts agreeing.
    """

    def test_flagged_conflicts_with_only_synthesised_questions_are_rejected(self):
        """The reviewer's first probe. Three conflicts flagged, four questions
        asked, every one of them synthesised — accepted by the committed code,
        because the ranking check finds nothing out of order in a list with no
        ``intent-conflict`` row in it at all."""
        text = swap(INTENT_BRIEF, "| brief | brief | frozen | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-002,C-003 |")
        text = with_questions([
            "| axis-1 | synthesis | 1 | answered | H-1 |",
            "| axis-2 | synthesis | 2 | answered | H-2 |",
            "| axis-3 | synthesis | 3 | asked | - |",
            "| axis-4 | synthesis | 4 | asked | - |",
        ], text)
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("C-001", str(caught.exception))

    def test_a_frozen_brief_with_no_conflict_question_at_all_is_rejected(self):
        """The reviewer's second probe, and the barest form of the fault: the
        conflict is recorded, the question table holds nothing derived from it,
        and the brief is sealed. Catches a rule written as "order the conflict
        questions" rather than "there must be one"."""
        text = with_questions(["| axis-2 | synthesis | 1 | answered | H-2 |"])
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("C-001", str(caught.exception))

    def test_an_unnamed_conflict_is_the_one_the_error_names(self):
        """Two flagged, one asked. Catches a bare count check: the operator who
        has to act on this needs the id of the conflict that was dropped, and
        "a conflict was not asked" sends them to diff two tables by hand."""
        text = swap(INTENT_BRIEF, "| brief | brief | frozen | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-007 |")
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("C-007", str(caught.exception))

    def test_a_conflict_question_the_brief_never_flagged_is_rejected(self):
        """The mirror direction. Catches enforcing only "every conflict has a
        question": a second ``intent-conflict`` row then spends one of the four
        slots on a conflict no reading raised, displacing a synthesised question
        that was ranked into the gate on its merits."""
        text = with_questions([
            "| C-001 | intent-conflict | 1 | answered | H-1 |",
            "| C-002 | intent-conflict | 2 | answered | H-2 |",
        ])
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("C-002", str(caught.exception))

    def test_a_conflict_is_simply_unasked_while_stage_03_is_still_open(self):
        """The positive control that keeps the rule a gate rule rather than an
        ordering-of-writes rule. Stage 02 synthesises and stage 03 asks, so
        between the brief publishing and the gate opening a flagged conflict
        legitimately has no question yet. Catches enforcing the claim on every
        parse: the controller could then never write the brief at all, because
        the question that claims the conflict cannot exist before it."""
        text = swap(INTENT_BRIEF, "| brief | brief | published | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-002 |")
        text = with_questions([], text)
        text = with_stages(*STAGE_03_OPEN, text=text)
        tracker = pas.parse_tracker(text)
        self.assertEqual(tracker["questions"], [])
        self.assertEqual(tracker["intent"][3]["conflicts"], "C-001,C-002")

    def test_the_claim_is_checked_the_moment_stage_03_closes(self):
        """The same tracker one transition later: stage 03 is complete and the
        questions were never synthesised. Catches tying the rule to the brief's
        ``frozen`` state alone — the brief may still be ``published``, and a
        closed stage 03 is already the point past which no question can be put.
        """
        text = swap(INTENT_BRIEF, "| brief | brief | published | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-002 |")
        text = with_questions([], text)
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("C-001", str(caught.exception))

    def test_conflict_questions_still_outrank_synthesised_ones(self):
        """The ranking rule is kept, now over a set this section populates.
        Catches replacing the ordering check with the claim count: two conflicts
        and two claims would balance while the synthesised question sat in slot
        1, pushing a conflict towards the end of a list the gate truncates."""
        text = swap(INTENT_BRIEF, "| brief | brief | frozen | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-002 |")
        text = with_questions([
            "| axis-3 | synthesis | 1 | answered | H-3 |",
            "| C-001 | intent-conflict | 2 | answered | H-1 |",
            "| C-002 | intent-conflict | 3 | answered | H-2 |",
        ], text)
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_intent_table_not_yet_written_claims_nothing(self):
        """``## Intent`` is empty before stage 01 opens. Catches indexing the
        brief row unconditionally: the cross-section rule would raise
        ``IndexError`` — outside this module's exception family — on every
        tracker created before the readers are dispatched."""
        text = valid_text()
        for row in (READER_1, READER_2, READER_3, INTENT_BRIEF):
            text = swap(row + "\n", "", text)
        text = with_questions(["| axis-2 | synthesis | 1 | answered | H-2 |"], text)
        tracker = pas.parse_tracker(text)
        self.assertEqual(tracker["intent"], [])

    def test_a_question_on_an_unrelated_axis_claims_no_conflict(self):
        """The reviewer's first probe against the counting rule. The brief flags
        ``C-001,C-042``; the two ``intent-conflict`` questions are ``axis-1`` and
        ``axis-9``, and neither is connected to either conflict.

        Catches judging the claim by CARDINALITY: two rows, two conflicts, the
        totals agree and the tracker is accepted — with ``C-042`` flagged, never
        asked and sealed into a frozen brief, which is the original fault intact
        under a total that adds up.
        """
        text = swap(INTENT_BRIEF, "| brief | brief | frozen | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-042 |")
        text = with_questions([
            "| axis-1 | intent-conflict | 1 | answered | H-1 |",
            "| axis-9 | intent-conflict | 2 | answered | H-2 |",
        ], text)
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("C-042", str(caught.exception))

    def test_two_questions_elaborating_one_conflict_do_not_cover_the_second(self):
        """The reviewer's second probe, and the sharper one: both conflicts are
        real and both questions are real, but both questions elaborate ``C-001``
        and ``C-002`` reaches nobody.

        The count is exactly balanced — two flagged, two claimed — so only a
        correspondence rule can see it. This is the case that dies if the rule
        is ever restated as ``len(claims) == len(conflicts)``.
        """
        text = swap(INTENT_BRIEF, "| brief | brief | frozen | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-002 |")
        text = with_questions([
            "| C-001 | intent-conflict | 1 | answered | H-1 |",
            "| axis-1 | intent-conflict | 2 | answered | H-2 |",
        ], text)
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("C-002", str(caught.exception))

    def test_a_question_naming_some_other_conflict_does_not_claim_this_one(self):
        """A conflict-shaped id is not the right conflict-shaped id. The brief
        flags ``C-001`` and the single ``intent-conflict`` question is ``C-002``.

        Catches a rule that checks only the SHAPE of the claiming id — that it
        looks like ``C-<n>`` — rather than which conflict it names. The count
        balances again, and the one disagreement between two readings of the
        user's own prompt is answered by a question about something else.
        """
        text = with_questions(["| C-002 | intent-conflict | 1 | answered | H-1 |"])
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("C-001", str(caught.exception))

    def test_each_conflict_claimed_by_the_question_that_names_it_is_accepted(self):
        """The positive control for correspondence, deliberately NOT in flagging
        order: ``C-001,C-002`` claimed by questions ``C-002`` then ``C-001``.

        The rule compares sets. Catches over-tightening it into a positional
        pairing — ``the n-th conflict is the question in slot n`` — which would
        refuse a legal tracker for ranking two conflicts in the order the
        synthesiser scored them rather than the order the brief listed them.
        """
        text = swap(INTENT_BRIEF, "| brief | brief | frozen | reconciled | "
                                  "scratch/intent-brief.md | C-001,C-002 |")
        text = with_questions([
            "| C-002 | intent-conflict | 1 | answered | H-1 |",
            "| C-001 | intent-conflict | 2 | answered | H-2 |",
            "| axis-3 | synthesis | 3 | asked | - |",
        ], text)
        tracker = pas.parse_tracker(text)
        self.assertEqual([row["id"] for row in tracker["questions"]],
                         ["C-002", "C-001", "axis-3"])


def with_escalations(rows: list[str]) -> str:
    """The fixture with its ``## Escalations`` body replaced wholesale."""
    text = valid_text()
    start = text.index("| E-1 |")
    end = text.index("\n\n## Tasks")
    return text[:start] + "\n".join(rows) + text[end:]


class EscalationSectionTests(unittest.TestCase):
    """``## Escalations`` is how a run that cannot decide reaches the user.

    It is the only path out of the autonomous middle of the run, so a shape
    this section accepts but no human ever sees is a question the run answers
    by itself while reporting that it asked.
    """

    def test_a_batch_of_four_is_legal(self):
        """The positive control for the batch cap: four per ``AskUserQuestion``
        call is the limit, not three. Catches an off-by-one that would strand
        the fourth escalation in a batch that is never asked."""
        text = with_escalations([
            "| E-1 | 7c6b5a4938d2 | phase | asked | batch-1 | - |",
            "| E-2 | - | run | asked | batch-1 | - |",
            "| E-3 | - | task | asked | batch-1 | - |",
            "| E-4 | - | contract | asked | batch-1 | - |",
        ])
        self.assertNotEqual(text, valid_text())
        tracker = pas.parse_tracker(text)
        self.assertEqual(len(tracker["escalations"]), 4)

    def test_a_batch_of_five_is_rejected(self):
        """Escalations batch at most four per ``AskUserQuestion`` call; more
        than four pending means ask four and halt on the rest. Catches dropping
        the cap: the fifth row records a question as asked that the call had no
        room for, so the run waits for an answer to a question never put."""
        text = with_escalations([
            "| E-1 | 7c6b5a4938d2 | phase | asked | batch-1 | - |",
            "| E-2 | - | run | asked | batch-1 | - |",
            "| E-3 | - | task | asked | batch-1 | - |",
            "| E-4 | - | contract | asked | batch-1 | - |",
            "| E-5 | - | task | asked | batch-1 | - |",
        ])
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_five_escalations_split_across_two_batches_are_legal(self):
        """The cap is per CALL, not per run. Catches counting the section
        instead of the batch, which would refuse the halt-and-ask-again shape
        the spec prescribes for more than four pending escalations."""
        text = with_escalations([
            "| E-1 | 7c6b5a4938d2 | phase | answered | batch-1 | H-3 |",
            "| E-2 | - | run | answered | batch-1 | H-4 |",
            "| E-3 | - | task | answered | batch-1 | H-5 |",
            "| E-4 | - | contract | answered | batch-1 | H-6 |",
            "| E-5 | - | task | asked | batch-2 | - |",
        ])
        tracker = pas.parse_tracker(text)
        self.assertEqual(len(tracker["escalations"]), 5)

    def test_a_duplicated_escalation_id_is_rejected(self):
        """Catches counting rows instead of identities: two escalations sharing
        an id are one entry to every later lookup, so the second one's
        resolution answers the first one's question."""
        text = swap(ESCALATION_2, "| E-1 | - | run | answered | batch-1 | H-3 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_escalation_id_outside_the_e_n_grammar_is_rejected(self):
        """Catches leaving the id free-form: ``## Tasks`` and ``decisions.md``
        both cite escalations by id, and an id that does not match the grammar
        they search for is an escalation nothing downstream can find."""
        text = swap(ESCALATION_1, "| ESC-1 | 7c6b5a4938d2 | phase | queued | - | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_escalation_cannot_point_at_an_unknown_quorum(self):
        """Catches accepting any twelve hex digits: an escalation whose qid
        matches no quorum row is one whose question, options and three brain
        responses cannot be recovered, so the human is asked to decide
        something the run can no longer describe."""
        text = swap(ESCALATION_1, "| E-1 | 000000000000 | phase | queued | - | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_the_blast_column_takes_the_axis_list_a_quorum_payload_emits(self):
        """The reviewer's Finding 2, as the values that actually arrive here.

        ``phase-03-quorum-contract.md:3089-3097`` builds this cell by joining a
        quorum payload's axis list, or writing ``-`` when the list is empty, so
        ``storage-engine`` and ``-`` are exactly what a SPECIFIED writer emits.
        Judging them against the question vocabulary ``task|phase|run|contract``
        halted the run on its own output — a fail-CLOSED, and a different fault
        from the fail-open that vocabulary is closed to prevent.
        """
        text = with_escalations([
            "| E-1 | 7c6b5a4938d2 | storage-engine | queued | - | - |",
            "| E-2 | - | storage-engine, external-service | answered | batch-1 | H-3 |",
            "| E-3 | - | - | queued | - | - |",
        ])
        tracker = pas.parse_tracker(text)
        self.assertEqual([row["blast"] for row in tracker["escalations"]],
                         ["storage-engine", "storage-engine, external-service", "-"])
        self.assertEqual(pas.render_tracker(tracker), text)

    def test_the_closed_question_vocabulary_no_longer_governs_this_column(self):
        """The negative half of the same disambiguation, stated as a value.

        Catches a "fix" that merely widens the closed tuple with the axes seen
        so far: the column is a free token list and the next payload names an
        axis nobody enumerated. Nothing branches on this cell, so there is
        nothing for an unenumerated value to fail open against — which is the
        whole reason it may be open here and may not be on a question.
        """
        text = swap(ESCALATION_1, "| E-1 | 7c6b5a4938d2 | universe | queued | - | - |")
        self.assertEqual(
            [row["blast"] for row in pas.parse_tracker(text)["escalations"]],
            ["universe", "run"])

    def test_the_blast_column_takes_tokens_and_not_prose(self):
        """Open is not unvalidated. Catches dropping the column's grammar
        altogether: a human reads this cell out of a batched ``AskUserQuestion``
        call, and a sentence there is a list with one unsplittable element."""
        for blast in ("storage engine", "storage-engine,,external-service",
                      "-storage-engine", "storage-engine, "):
            with self.subTest(blast=blast):
                text = swap(ESCALATION_1,
                            f"| E-1 | 7c6b5a4938d2 | {blast} | queued | - | - |")
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_the_closed_vocabulary_is_intact_for_the_column_that_owns_it(self):
        """A question's admissibility blast radius is the OTHER "blast", and it
        stays closed: adoption checks it against the irreversible-axis list,
        where an unenumerated value matches nothing and so passes the check it
        was meant to fail. Catches deleting the constant along with its
        misapplication — the column that carries it lands with the quorum phase,
        and a vocabulary re-derived there is one re-argued there."""
        self.assertEqual(pas._BLAST_RADII, ("task", "phase", "run", "contract"))
        for radius in pas._BLAST_RADII:
            self.assertTrue(pas._TOKEN.fullmatch(radius), radius)

    def test_an_out_of_enum_escalation_state_is_rejected(self):
        """The row carries no batch and no resolution, so every other
        escalation rule passes it. Catches omitting the state enum: a row in an
        undefined state is not pending by ``derive_next_action``'s reckoning, so
        the run resumes dispatching past an escalation nobody has answered."""
        text = swap(ESCALATION_1, "| E-1 | 7c6b5a4938d2 | phase | parked | - | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_queued_escalation_has_not_been_batched(self):
        """``queued`` means waiting for a stage boundary, not waiting for the
        human. Catches accepting a batch on a queued row: the escalation is
        counted against a call it was never part of, displacing a question that
        was."""
        text = swap(ESCALATION_1, "| E-1 | 7c6b5a4938d2 | phase | queued | batch-1 | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_asked_escalation_must_name_its_batch(self):
        """Catches enforcing only the queued direction: an asked escalation with
        no batch cannot be traced back to the call that carried it, so a resumed
        controller cannot tell whether it was ever put to the human."""
        text = swap(ESCALATION_2, "| E-2 | - | run | answered | - | H-3 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_answered_escalation_records_its_human_resolution(self):
        """Catches accepting ``answered`` with no resolution: the escalation
        stops blocking ``derive_next_action`` while recording no answer at all,
        and the run continues past the decision it escalated as if it had been
        made."""
        text = swap(ESCALATION_2, "| E-2 | - | run | answered | batch-1 | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unanswered_escalation_cannot_carry_a_resolution(self):
        """The mirror omission. Catches a resolution recorded against a
        still-queued escalation: an answer the human has not given yet, already
        citable as ``Provenance: human`` by everything downstream."""
        text = swap(ESCALATION_1, "| E-1 | 7c6b5a4938d2 | phase | queued | - | H-9 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)


class GrammarTests(unittest.TestCase):
    """The id grammars, stated without a regex engine and no looser for it.

    ``re`` left ``ALLOWED_IMPORTS`` — an allowlist described in that file as a
    capability boundary, so a member that buys nothing is one that should not
    be there. What it bought was three patterns this module can state directly.
    The risk in removing it is not the import: it is that a hand-written
    grammar quietly accepts more than the pattern did, and the cells these
    guard are the ones that decide whether a machine may answer the one human
    gate. So each is pinned here on both sides, accepting and rejecting.
    """

    def test_a_human_decision_id_is_a_prefix_and_ascii_digits(self):
        for value in ("H-1", "H-12", "H-007"):
            self.assertTrue(pas._HUMAN_DECISION.fullmatch(value), value)
        for value in ("H-", "H", "", "h-1", "H-1x", "xH-1", "H-1 ", " H-1",
                      "H-1,H-2", "Q-3f2a1b0c9d8e", "H-١٢", "H-²"):
            self.assertFalse(pas._HUMAN_DECISION.fullmatch(value), value)

    def test_non_ascii_digits_are_not_digits_here(self):
        """``str.isdigit`` is true of ``'١'`` and ``'²'``, and ``re``'s
        ``[0-9]`` is not. Catches writing the grammar as ``isdigit`` alone: an
        id spelled in Arabic-Indic digits renders back into the tracker looking
        like a human decision that no downstream lookup can ever match, and the
        decision it points at is simply not there."""
        for value in ("H-١", "E-٢", "C-٠٠١"):
            with self.subTest(value=value):
                self.assertTrue(value[2:].isdigit())
                self.assertFalse(pas._HUMAN_DECISION.fullmatch(value))
                self.assertFalse(pas._ESCALATION_ID.fullmatch(value))
                self.assertFalse(pas._CONFLICT_ID.fullmatch(value))

    def test_the_escalation_and_conflict_ids_are_the_same_shape(self):
        self.assertTrue(pas._ESCALATION_ID.fullmatch("E-12"))
        self.assertFalse(pas._ESCALATION_ID.fullmatch("ESC-1"))
        self.assertFalse(pas._ESCALATION_ID.fullmatch("E-1-2"))
        self.assertTrue(pas._CONFLICT_ID.fullmatch("C-001"))
        self.assertFalse(pas._CONFLICT_ID.fullmatch("C-001a"))
        self.assertFalse(pas._CONFLICT_ID.fullmatch("resolved-by-controller"))

    def test_the_free_token_grammar_is_the_one_the_plan_specifies(self):
        """``_TOKEN`` is ``[A-Za-z0-9][A-Za-z0-9._/@:+-]*`` — restored, because
        its absence was a Task 1 regression and later P02 tasks already spell
        ``_TOKEN.fullmatch(value)`` at ``phase-02-schema-core.md:1942`` and
        ``:2620``. It must lead with an alphanumeric, so a cell cannot start
        with the ``-`` that means absence, and it must exclude the space, which
        is what separates a token from a sentence."""
        for value in ("storage-engine", "a", "P02-T01", "refs/heads/feat/x",
                      "scratch/p01-t01.md", "v1.2.3", "a@b:c+d", "0"):
            self.assertTrue(pas._TOKEN.fullmatch(value), value)
        for value in ("", "-", "-storage", ".config", "/abs/path", "two words",
                      "a,b", "a|b", "naïve", "a\tb"):
            self.assertFalse(pas._TOKEN.fullmatch(value), value)

    def test_a_digest_is_sixty_four_lowercase_hex_characters(self):
        """``_SHA256`` was ``re.compile(r"[0-9a-f]{64}")`` before ``re`` left.
        Both halves of that pattern are load-bearing and neither is obvious in a
        hand-written grammar: a width check without the character class accepts
        sixty-four of anything, and a character class without the width accepts
        a truncated digest that still looks like hex."""
        digest = "4f1c0a2b3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8"
        self.assertTrue(pas._SHA256.fullmatch(digest))
        self.assertTrue(pas._SHA256.fullmatch("0" * 64))
        for value in (digest.upper(), digest[:63], digest + "0", "g" * 64, "",
                      "-", " " + digest[1:]):
            self.assertFalse(pas._SHA256.fullmatch(value), value)

    def test_a_qid_is_twelve_hex_characters_and_its_decision_prefixes_them(self):
        """``Q-<qid>`` and ``<qid>`` are the same twelve characters, and the
        prefix is the whole difference between a machine decision and the human
        decision ``H-<n>``. Catches a decision grammar that accepts the bare qid
        or any ``Q-`` token: either one lets a cell that is not a quorum
        decision stand where downstream reads a quorum decision."""
        self.assertTrue(pas._QID.fullmatch("3f2a1b0c9d8e"))
        for value in ("3f2a1b0c9d8", "3f2a1b0c9d8e0", "3F2A1B0C9D8E", "",
                      "Q-3f2a1b0c9d8e", "zzzzzzzzzzzz"):
            self.assertFalse(pas._QID.fullmatch(value), value)
        self.assertTrue(pas._QUORUM_DECISION.fullmatch("Q-3f2a1b0c9d8e"))
        for value in ("3f2a1b0c9d8e", "H-1", "Q-", "Q-3f2a1b0c9d8", "q-3f2a1b0c9d8e",
                      "Q-3F2A1B0C9D8E", "XQ-3f2a1b0c9d8e"):
            self.assertFalse(pas._QUORUM_DECISION.fullmatch(value), value)

    def test_a_quorum_outcome_is_two_exact_words_or_a_reasoned_rejection(self):
        """The alternation ``adopted|escalated|rejected-[a-z][a-z-]*``, stated
        without a regex engine. The two adopting words are exact and everything
        else must announce itself as a rejection AND carry a reason, so neither
        a bare ``rejected`` nor a near-miss like ``adopted-later`` gets in."""
        for value in ("adopted", "escalated", "rejected-contradicts-human",
                      "rejected-x", "rejected-a-b-c"):
            self.assertTrue(pas._QUORUM_OUTCOME.fullmatch(value), value)
        for value in ("", "-", "approved", "adopted-later", "escalated ",
                      "rejected", "rejected-", "rejected-Human", "rejected-1",
                      "rejected-contradicts human", "Adopted"):
            self.assertFalse(pas._QUORUM_OUTCOME.fullmatch(value), value)


#: The fixture's one finalized quorum row, quoted whole so every surgery below
#: names exactly the cell it changed instead of re-typing the row it meant to
#: leave alone. Its ``Axis`` is the literal ``new`` and its ``Phase`` is
#: ``P01``, because that is what the committed fixture says; ``swap`` refuses a
#: pattern the fixture no longer contains, so a copy that drifts from it fails
#: loudly here rather than quietly building its case on an untouched tracker.
ADOPTED_ROW = (
    "| 3f2a1b0c9d8e | new | P01 | finalized | brain-1,brain-2,brain-3 | "
    "4f1c0a2b3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8 | "
    "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90 | "
    "scratch/q1-brain-1.json,scratch/q1-brain-2.json,scratch/q1-brain-3.json | "
    "1 | specified | adopted | Q-3f2a1b0c9d8e |"
)

#: The in-flight row's payload digest, which the schema requires to exist
#: *before* the three brains are dispatched.
IN_FLIGHT_PAYLOAD = "b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1"
IN_FLIGHT_TAIL = "scratch/q2-brain-4.json | - | - | - | - |"


def adopted_with(old: str, new: str) -> str:
    """The fixture with ONE cell of its adopted quorum row changed.

    Guarded on both levels. ``str.replace`` with an absent pattern is a silent
    no-op, and a rejection case built on one asserts against the untouched
    fixture — which parses, so that case merely fails — while a POSITIVE case
    built on one passes while exercising nothing at all. The inner check catches
    a cell that has moved inside the row; ``swap`` catches a row that has moved
    inside the fixture.
    """
    if old not in ADOPTED_ROW:
        raise AssertionError(f"the adopted quorum row no longer contains {old!r}")
    return swap(ADOPTED_ROW, ADOPTED_ROW.replace(old, new))


class QuorumSectionTests(unittest.TestCase):
    """``## Quorum`` is the record of every decision no human made.

    A quorum row is the only place a machine-made decision is written down, so
    what this section refuses is the whole of what stops the run from deciding
    something it had no authority to decide. P02 checks that a row is a
    *possible state of the protocol*; whether an adoption was *correct* —
    floor, strictness, contradiction, budget — is P03's arithmetic over these
    same cells and is deliberately absent here.
    """

    def test_a_rung_outside_the_enum_is_schema_invalid(self):
        """THE named fault of this task. A brain never types a number: it
        selects a grounding rung and the controller derives the value, so a
        rung the enum does not contain is a malformed response, not a weak one.

        Catches the natural implementation ``RUNGS.get(rung_id, 0.55)``. 0.55 is
        ``engineering-judgement`` and is already in the module for the
        citation-demotion rule, so defaulting to it reads as principled and
        defensive — and silently converts every malformed brain response into a
        legal vote. The value that arrives is legal; the door it came through is
        not, which is why nothing downstream can detect it.
        """
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| specified |", "| high |"))

    def test_the_five_rung_names_are_the_only_ones_a_row_may_carry(self):
        """The enum, exercised one name at a time rather than once. Catches a
        membership test written against a subset — the two rungs at or above the
        adoption floor, say — which would reject the three legal rungs a
        ``rejected-*`` or ``escalated`` row records to explain why it did not
        adopt, and so erase the evidence that the floor did its job."""
        for rung in pas.RUNG_NAMES:
            with self.subTest(rung=rung):
                text = adopted_with("| 1 | specified | adopted | Q-3f2a1b0c9d8e |",
                                    f"| 1 | {rung} | escalated | - |")
                self.assertEqual(pas.parse_tracker(text)["quorum"][0]["rung"], rung)

    def test_two_brains_are_rejected_because_a_count_is_never_reduced(self):
        """Exactly three brains per quorum. Catches accepting a short roster
        when capacity is tight: two responses can only ever agree or split, so
        the spread rule that decides adoption has nothing to measure."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("brain-1,brain-2,brain-3", "brain-1,brain-2"))

    def test_three_owner_slots_must_be_three_distinct_brains(self):
        """Catches checking the COUNT alone. One brain dispatched twice fills
        three slots and votes twice, and a quorum of two independent readings
        with one of them doubled is a majority manufactured out of a single
        opinion."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(
                adopted_with("brain-1,brain-2,brain-3", "brain-1,brain-1,brain-3"))

    def test_an_in_flight_quorum_cannot_carry_a_computed_result(self):
        """The three-phase record exists so an interruption is classifiable: a
        row is either dispatched-and-undecided or finalized-and-decided, and a
        resuming controller reads which from the state. Catches letting a row be
        both, which is the one shape that answers neither question."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(swap(
                IN_FLIGHT_TAIL,
                "scratch/q2-brain-4.json | 1 | specified | adopted | Q-7c6b5a4938d2 |"))

    def test_an_in_flight_quorum_must_already_carry_its_payload_digest(self):
        """The digest is persisted BEFORE dispatch, not written back with the
        responses. Catches accepting ``-`` until the brains answer: the run
        crashes mid-dispatch, and nothing afterwards can prove which payload the
        three responses on disk were answers to."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(swap(f"| {IN_FLIGHT_PAYLOAD} |", "| - |"))

    def test_one_payload_digest_binds_all_three_brains(self):
        """The three brains get different reading assignments, but the
        assignment rule is a frozen constant, so brain n's payload is determined
        by the shared payload plus n and ONE digest binds all three. The
        positive control for that: a single sha256 cell, not one per brain."""
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual(tracker["quorum"][1]["payload_digest"], IN_FLIGHT_PAYLOAD)
        self.assertEqual(
            [column for column in pas._QUORUM_HEADER if column.endswith("Digest")],
            ["Payload Digest", "Context Digest"])

    def test_a_digest_spelled_in_uppercase_hex_is_rejected(self):
        """Catches a case-insensitive digest grammar. The same bytes hashed
        twice must render the same cell, and a row whose digest differs only in
        case matches no response file and no re-computation, so the binding the
        digest exists to provide silently holds against nothing."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with(
                "4f1c0a2b3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8",
                "4F1C0A2B3D4E5F60718293A4B5C6D7E8F90A1B2C3D4E5F60718293A4B5C6D7E8"))

    def test_adoption_requires_all_three_responses_on_disk(self):
        """Catches adopting on the responses that happened to arrive. Two
        responses cannot produce the strictly-higher winning rung adoption
        needs, so a two-file adoption is one where the rule was not applied."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with(
                "scratch/q1-brain-1.json,scratch/q1-brain-2.json,"
                "scratch/q1-brain-3.json",
                "scratch/q1-brain-1.json,scratch/q1-brain-2.json"))

    def test_one_response_file_cited_twice_is_not_two_responses(self):
        """Catches counting cited paths rather than distinct ones: three
        citations of two files satisfy a length check and a two-brain quorum
        passes as three, with one brain's answer weighted double."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with(
                "scratch/q1-brain-2.json", "scratch/q1-brain-1.json"))

    def test_an_adopted_quorum_records_a_quorum_decision_id(self):
        """``Q-<qid>``, not any non-empty cell. Catches accepting ``H-9``: a
        machine decision then wears the provenance of a human one, and the
        contradiction check that protects human answers reads it as one of
        theirs."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| Q-3f2a1b0c9d8e |", "| H-9 |"))

    def test_an_adopted_quorum_records_its_winning_rung(self):
        """Catches an adoption with no rung. The rung IS the authority the
        decision was made on; without it nothing can later check the adoption
        against the ``code-evidenced`` floor, and an unrecorded rung is
        indistinguishable from one below it."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| 1 | specified | adopted |",
                                           "| 1 | - | adopted |"))

    def test_an_adopted_quorum_records_its_decision_depth(self):
        """Depth is capped at 2 and human decisions are depth 0. Catches an
        adoption with no depth: the cap is enforced over these cells, and a row
        that records none is one no cap can count."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| 1 | specified | adopted |",
                                           "| - | specified | adopted |"))

    def test_a_decision_depth_spelled_in_non_ascii_digits_is_rejected(self):
        """``'١'.isdigit()`` is True and ``int('²')`` raises. Catches writing
        the depth check as ``isdigit`` alone: a depth of ``²`` passes here and
        then fails the depth cap with a bare ``ValueError``, outside this
        module's exception family, where a caller branching on ``TrackerError``
        never sees the stop."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| 1 | specified |", "| ١ | specified |"))

    def test_an_escalated_quorum_cannot_carry_a_decision(self):
        """Only an adopted quorum decides anything. Catches leaving the decision
        cell unjudged on the other outcomes: the row says it escalated to the
        human and names a ``Q-`` decision in the same breath, and everything
        downstream cites the decision."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| adopted | Q-3f2a1b0c9d8e |",
                                           "| escalated | Q-3f2a1b0c9d8e |"))

    def test_an_escalated_quorum_records_what_it_found_without_deciding_it(self):
        """The positive control for the outcome rules. An escalation is the
        normal, correct end of a quorum that could not clear the bar, and it
        still records the rung and depth it reached. Catches requiring a
        decision on every finalized row, which would make escalating impossible
        to write down and adoption the only expressible outcome."""
        tracker = pas.parse_tracker(
            adopted_with("| adopted | Q-3f2a1b0c9d8e |", "| escalated | - |"))
        self.assertEqual(tracker["quorum"][0]["outcome"], "escalated")
        self.assertEqual(tracker["quorum"][0]["decision"], "-")

    def test_an_axis_must_be_a_stage_03_question_or_the_literal_new(self):
        """Adoption checks the axis against the human decisions already made on
        it. Catches leaving the axis a free token: a quorum that writes an axis
        name matching no stage-03 question contradicts nothing by construction,
        so it clears the contradiction check by being unrecognisable rather than
        by being compatible — the same fail-open ``_BLAST_RADII`` is closed
        against."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| new |", "| axis-9 |"))

    def test_a_quorum_axis_may_name_a_stage_03_question(self):
        """The positive control for the same rule, and the case the fixture no
        longer carries. A quorum deepening an axis the human already answered is
        legal — it is the contradiction, not the axis, that adoption refuses —
        so a rule written as 'the axis is always the literal new' would refuse a
        state the protocol produces."""
        tracker = pas.parse_tracker(adopted_with("| new |", "| C-001 |"))
        self.assertEqual(tracker["quorum"][0]["axis"], "C-001")

    def test_a_quorum_row_cannot_name_a_phase_the_run_has_no_record_of(self):
        """The drift budget is three adoptions per phase and ten per run,
        counted by filtering these rows on ``Phase``. Catches leaving the phase
        a free token: an adoption filed under a phase that does not exist is
        counted against no phase's budget at all."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| P01 |", "| P99 |"))

    def test_a_qid_is_twelve_lowercase_hex_characters(self):
        """The qid is a digest of the question and its axis, and every
        escalation, task and decision id in the run points back through it.
        Catches accepting any token: a row keyed by something no derivation can
        reproduce is one whose question can never be found again."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| 3f2a1b0c9d8e |", "| 3F2A1B0C9D8E |"))

    def test_a_duplicate_qid_is_rejected_because_one_adopted_answer_per_qid(self):
        """One adopted answer per qid per run. Catches accepting two rows on one
        qid: the second is the run re-asking a question it already answered
        until it gets the answer it wants, and both rows are citable."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(swap(ADOPTED_ROW, ADOPTED_ROW + "\n" + ADOPTED_ROW))

    def test_an_unknown_quorum_state_is_rejected_rather_than_read_as_finalized(self):
        """The enum is checked BEFORE anything branches on it, for the reason
        ``_validate_stages`` checks its own first. Catches ``if state ==
        'in_flight': ... else: <finalized rules>``, under which an unknown state
        falls into the finalized branch and a row nobody can classify is judged
        by the rules for the one state it is not in."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(adopted_with("| finalized |", "| dispatched |"))

    def test_an_unknown_outcome_word_is_rejected(self):
        """Catches an open outcome grammar. ``approved`` is not ``adopted``, so
        every adoption rule below skips it and the row records an outcome no
        reader can classify, having been judged by nothing.

        The decision cell is cleared in the same surgery, and that is what makes
        this test about the outcome. Left as ``Q-3f2a1b0c9d8e``, the row is
        refused by 'only an adopted quorum carries a decision' whatever the
        outcome grammar does — the test passes with the grammar deleted, which
        is the case it was written to catch."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(
                adopted_with("| adopted | Q-3f2a1b0c9d8e |", "| approved | - |"))

    def test_a_rejection_outcome_is_accepted_without_p02_enumerating_the_reasons(self):
        """P02 closes the SHAPE of a rejection, not its vocabulary: naming the
        reasons is P03's contract, and an enum here would have to be edited in
        two places every time one is added. Catches closing it anyway, which
        halts the run on a reason a specified writer actually emits."""
        tracker = pas.parse_tracker(adopted_with(
            "| 1 | specified | adopted | Q-3f2a1b0c9d8e |",
            "| - | - | rejected-contradicts-human | - |"))
        self.assertEqual(tracker["quorum"][0]["outcome"], "rejected-contradicts-human")

    def test_a_bare_rejected_carries_no_reason_and_is_refused(self):
        """The other half of that shape. Catches accepting the prefix alone: the
        one thing P02 can require of a rejection is that it says why, and
        ``rejected`` on its own is the outcome recorded with the reason
        dropped."""
        for outcome in ("rejected", "rejected-", "rejected-Contradicts"):
            with self.subTest(outcome=outcome):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(adopted_with(
                        "| adopted | Q-3f2a1b0c9d8e |", f"| {outcome} | - |"))

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
