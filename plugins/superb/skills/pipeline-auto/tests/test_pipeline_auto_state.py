"""Contract tests for the pipeline-auto/v1 state spine."""

from __future__ import annotations

import ast
import contextlib
import errno
import hashlib
import importlib.util
import multiprocessing
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

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
#: ``errno``, ``os``, ``time``, ``contextlib``, ``fcntl`` and ``msvcrt`` were
#: added, together and on purpose, for the run-local exclusive lock and for
#: nothing else. The lock is the one mechanism that makes "only the controller
#: writes progress.md" a fact rather than a convention, and it cannot be built
#: out of the three names above it: an OS-backed exclusive lock needs a real
#: file descriptor (``os.open``/``os.fstat``/``os.close``), the platform lock
#: call (``fcntl.flock``, or ``msvcrt.locking`` where there is no ``fcntl``),
#: the errno constants that separate "somebody else holds it" from "this lock
#: is broken" (``errno``), a monotonic deadline (``time``), and
#: ``contextlib.contextmanager`` so the release is in a ``finally``. The phase
#: plan's Tech Stack names exactly this set. ``re`` is still absent and stays
#: absent.
#:
#: ``os.open`` is not the banned bare builtin ``open``: ``FORBIDDEN_BUILTINS``
#: below is a ban on bare-NAME calls and is unchanged in strictness, and no
#: bare ``open`` is used anywhere in the module. The distinction is real —
#: ``os.open`` returns a descriptor the lock call needs and a file object
#: cannot supply — but it is a distinction, not a narrowing, and it is written
#: down here so that it stays a deliberate exception rather than a loophole.
#:
#: What this allowlist does NOT prove is that the module cannot write. ``pathlib``
#: is not a narrower capability than ``os`` or ``shutil``: ``Path.write_text``,
#: ``write_bytes``, ``unlink``, ``rename``, ``replace``, ``mkdir``, ``rmdir``,
#: ``touch``, ``chmod``, ``symlink_to`` and ``open(mode=...)`` all exist, and an
#: earlier revision of this file claimed otherwise. The read-only guarantee is
#: carried by ``write_capable_calls`` below, scoped to ``validate_run``, and
#: widening this allowlist to ``os`` does not touch it: ``validate_run``'s own
#: subtree is still checked call by call.
#: ``copy`` was added for ``locked_tracker_update``, which hands ``mutate`` a
#: DEEP copy of the tracker it read under the lock. That copy is not a
#: convenience: the identity guard and the frozen-brief guard both work by
#: comparing the proposal against the state it came from, and under a shallow
#: copy each would be comparing an object with itself and passing. The hand
#: -rolled alternative — one ``dict`` per section plus one per row — is exact
#: for the shape ``parse_tracker`` produces TODAY and silently aliases the day a
#: section nests one level deeper, which is the opposite of how ``re`` and
#: ``tempfile`` left this list: each of those was removed because the module
#: could state the same thing at the SAME strictness, and a two-level copy
#: states it at less. ``copy`` also adds no capability for this list to bound —
#: it opens nothing, runs nothing, and reaches no filesystem — which is what
#: separates it from every other candidate that has been argued for here. The
#: phase plan's Tech Stack names it.
#:
#: ``tempfile`` was admitted here for the atomic replace and has since been
#: taken back out, which is the outcome this list is supposed to make cheap.
#: The temp file must be created inside the run directory — a name anywhere
#: else makes ``os.replace`` a cross-device rename, which raises instead of
#: swapping — and it must be created without a window in which a second
#: writer's file could be opened or truncated. ``os.open(path, O_CREAT |
#: O_EXCL | O_WRONLY, mode)`` gives exactly that exclusivity, in the same call
#: the run lock two hundred lines above already uses, with NO import at all;
#: what ``mkstemp`` adds on top is an unguessable name and collision retry, and
#: neither buys anything inside a directory this one run owns — while it also
#: chooses the file's mode, silently, at 0600, and ``os.replace`` then carries
#: that onto ``progress.md``. This list is a capability boundary: a member kept
#: for convenience weakens it for everything admitted after. ``re`` is still
#: absent and stays absent, and so, now, is ``tempfile``.
ALLOWED_IMPORTS = frozenset({
    "__future__", "contextlib", "copy", "errno", "fcntl", "hashlib", "msvcrt",
    "os", "pathlib", "time",
})

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


def code_constants(source: str, name: str) -> frozenset[str]:
    """Every string constant in ONE function's body, its docstring excluded.

    A guard that asserts a name is absent from a function has to look at what
    the function DOES, not at what it says about itself: the prose explaining
    why a cell is never read contains that cell's name, so a dump of the whole
    subtree is satisfied only by a function that stays silent about its own
    reasoning.
    """
    node = function_node(source, name)
    body = node.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return frozenset(
        child.value for statement in body for child in ast.walk(statement)
        if isinstance(child, ast.Constant) and isinstance(child.value, str))


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

#: ``## Tasks``, ``## Phases`` and ``## Gates`` are addressed by column NAME
#: below. The header tuples come from the module rather than being retyped, so a
#: column added or moved reaches these helpers as a KeyError-shaped
#: ``AssertionError`` instead of silently shifting every cell one place left.
SECTION_HEADERS = {key: header for _, key, header in pas._SECTIONS[1:]}


def row_fields(key: str) -> tuple[str, ...]:
    return tuple(pas._field(column) for column in SECTION_HEADERS[key])


def with_row(key: str, row_id: str, cells: dict[str, str],
             text: str | None = None) -> str:
    """The fixture with named cells of ONE row of ONE section replaced.

    By column NAME, never by substring. ``## Tasks`` carries sixteen columns and
    ten of them read ``-`` in the rows these cases edit, so a substring pattern
    over a task row is either ambiguous inside the row or long enough that it
    stops matching the day a column is added — and a ``str.replace`` whose
    pattern is absent is a silent no-op that leaves the case asserting against
    the untouched, VALID fixture.

    That is not hypothetical here. The brief for this task carried four such
    patterns, each written one column short of the committed fixture's sixteen:
    the in-flight case, the completed-artifact case, the blocked-task case and
    the ``Provisional`` case all edited nothing at all. A rejection case built
    on a no-op merely fails; a POSITIVE control built on one passes while
    exercising nothing. Both are refused here.

    Row lookup is scoped to the section, because ``| P01-T01 | `` opens a row in
    ``## Tasks``, another in ``## Task Review`` and a third in ``## Fix Rounds``.
    """
    text = valid_text() if text is None else text
    old, new = rewritten_row(key, row_id, cells, text)
    return swap(old, new, text)


def rewritten_row(key: str, row_id: str, cells: dict[str, str],
                  text: str) -> tuple[str, str]:
    """``(the row as it stands, the same row with named cells replaced)``.

    Every check ``with_row`` makes lives here — the column names are real, the
    row is unique, the row is as wide as the section's header — because the
    rules of ``## Task Review`` and ``## Fix Rounds`` are about a SEQUENCE of
    rounds and a sequence cannot be built by replacing one row in place. Handing
    the caller the rendered row, rather than a whole tracker, is what lets a
    second and third round be built from the committed fixture's own cells
    instead of retyped: a hand-typed fourteen-cell literal is one column short
    the day a column is added, and a pattern that no longer matches is the
    silent no-op this file's helpers exist to make impossible.
    """
    fields = row_fields(key)
    unknown = sorted(set(cells) - set(fields))
    if unknown:
        raise AssertionError(f"{key!r} has no column(s) {unknown}")
    heading = next(head for head, name, _ in pas._SECTIONS if name == key)
    prefix = f"| {row_id} | "
    matches = [line for line in pas._sections(text)[heading]
               if line.startswith(prefix)]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one {heading} row starting {prefix!r}, "
            f"found {len(matches)}")
    old = matches[0]
    values = tuple(part.strip() for part in old[1:-1].split("|"))
    if len(values) != len(fields):
        raise AssertionError(
            f"{heading} row {row_id!r} is {len(values)} cells, not {len(fields)}")
    if text.count(old) != 1:
        raise AssertionError(f"{old!r} is not unique in the tracker")
    return old, pas._row(tuple(
        cells[name] if name in cells else value
        for name, value in zip(fields, values)))


#: ``## Task Review`` and ``## Fix Rounds`` are the only sections whose rows are
#: keyed by a PAIR — ``(Task, Round)`` and ``(Scope, Round)`` — because a task
#: has N review rounds and a scope has N fix rounds, and ``| P01-T01 | `` opens
#: two rows of the first section and one of the second. The pair is spelled as
#: the two cells that open the row, so ``with_row``'s width, uniqueness and
#: column-name checks apply unchanged.
def with_review(task: str, round_number: str, cells: dict[str, str],
                text: str | None = None) -> str:
    return with_row("task_review", f"{task} | {round_number}", cells, text)


def with_fix(scope: str, round_number: str, cells: dict[str, str],
             text: str | None = None) -> str:
    return with_row("fix_rounds", f"{scope} | {round_number}", cells, text)


def rounds_for(key: str, row_id: str, rows: tuple[dict[str, str], ...],
               text: str | None = None) -> str:
    """The fixture with ONE row of ``key`` replaced by a SEQUENCE of rows.

    Each dict is that same committed row with its named cells replaced, so a
    column added to the section reaches every round at once. This is the only
    way to state a rule about a sequence — the intensity ratchet, the bound of
    three, the round that resolved nothing — without a hand-typed row literal.
    """
    text = valid_text() if text is None else text
    old, _ = rewritten_row(key, row_id, {}, text)
    return swap(old, "\n".join(
        rewritten_row(key, row_id, cells, text)[1] for cells in rows), text)


#: Every lifecycle cell of ``## Tasks``, spelled out rather than imported from
#: ``pas._TASK_LIFECYCLE``. Importing it would make the subtest set move with
#: the constant, so dropping a name from the constant would drop the subtest
#: that catches the drop — a test that agrees with the mutation.
TASK_LIFECYCLE_CELLS = {
    "owner": "impl-9",
    "attempt": "attempt-001",
    "result": "scratch/x-result.md",
    "checkpoints": "red",
    "source_ref": "refs/heads/feat/pipeline-auto",
    "commits": "0123456789abcdef0123456789abcdef01234567",
    "artifacts": "scratch/x-notes.md",
    "integration": "fedcba9876543210fedcba9876543210fedcba98",
    "verification": "scratch/x-tests.txt",
    "question": "scratch/x-question.md",
}

#: P02-T01 wound all the way back: a task the plan names and nobody has picked
#: up. ``Decisions`` and ``Provisional`` are deliberately NOT cleared.
UNSTARTED_TASK = dict({key: "-" for key in TASK_LIFECYCLE_CELLS}, state="[ ]")

#: P02-T01 wound all the way forward, as a legally completed artifact task.
COMPLETED_ARTIFACT_TASK = {
    "state": "[x]",
    "result": "scratch/p02-t01-result.md",
    "artifacts": "scratch/p02-t01-notes.md",
    "integration": "N/A",
    "verification": "scratch/p02-t01-tests.txt",
}

#: ``P02-T01``'s review round wound forward to the one verdict that lets its
#: task stand at ``[x]``, and its fix round wound forward to closed. Winding the
#: TASK row forward is no longer enough on its own: a task may not reach ``[x]``
#: while the review round that speaks for it is still blocked at two open
#: findings, or while a fixer is still carrying them. A case that marked the
#: task complete and stopped there would raise about that bar rather than about
#: the one cell it changed — a test passing for the wrong reason.
ACCEPTED_REVIEW = {
    "state": "accepted", "critical": "0", "important": "0", "minor": "0",
    "open": "0",
}


def completed_artifact_task(**cells: str) -> str:
    """The fixture with ``P02-T01`` wound forward to a legally finished task.

    Three rows, not one: the task says the work is done, the review round says
    a reviewer accepted it at zero open findings, and the fix round says the
    fixer finished carrying what that review raised.
    """
    text = with_row("tasks", "P02-T01", dict(COMPLETED_ARTIFACT_TASK, **cells))
    text = with_review("P02-T01", "1", ACCEPTED_REVIEW, text)
    return with_fix("P02-T01", "1", completed_fix(1, "F-001,F-002", "none"), text)


RATCHET_RECORD = "accumulated-surface@scratch/p02-ratchet.md"

#: The ONLY three (Review Class, Class Source, Ratchet) triples the schema
#: admits. Everything else in the two-by-two-by-two cross product is refused,
#: and that is the whole of the one-way ratchet: there is no spelling of a
#: downward reclassification for a run to write down. ``plan`` means "this is
#: the class stage 04 fixed", so it carries no ratchet record; ``ratchet`` means
#: "this differs from plan metadata", so it must name its trigger and evidence
#: AND it must be the upward end.
LEGAL_CLASS_RECORDS = frozenset({
    ("required", "plan", "-"),
    ("final-only", "plan", "-"),
    ("required", "ratchet", RATCHET_RECORD),
})


class TaskSectionTests(unittest.TestCase):
    """``## Tasks`` is the only record of what was built and what it rests on.

    Two facts this section keeps apart are worth naming because collapsing
    either loses work. Completion and integration are separate: a finished task
    is ``[x]`` with its integration ``held`` while the budget freeze holds, and
    freezing the import too would discard a finished task's evidence and repeat
    the work on resume. And ``Decisions`` is separate from the lifecycle: the
    decisions a task's plan rests on are known before anyone picks the task up,
    which is exactly what lets taint cross a phase boundary.
    """

    def test_an_unstarted_task_cannot_carry_lifecycle_state(self):
        """One subtest per lifecycle cell, so dropping a single name from the
        constant leaves its own case failing rather than being covered by a
        neighbour."""
        for column, value in TASK_LIFECYCLE_CELLS.items():
            with self.subTest(column=column):
                text = with_row("tasks", "P02-T01",
                                dict(UNSTARTED_TASK, **{column: value}))
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_an_unstarted_task_may_still_cite_the_decisions_its_plan_rests_on(self):
        """The positive control the case above needs, and the reason
        ``Decisions`` is not a lifecycle cell. A task in a later phase is named
        by the plan — and tainted by a decision an earlier phase adopted —
        before any worker touches it. If citing that decision required the task
        to have started, the taint would have nowhere to be written down until
        the work was already under way, and the closure would stop at the phase
        that raised the decision."""
        tracker = pas.parse_tracker(
            with_row("tasks", "P02-T01", UNSTARTED_TASK))
        unstarted = next(row for row in tracker["tasks"] if row["id"] == "P02-T01")
        self.assertEqual(unstarted["state"], "[ ]")
        self.assertEqual(unstarted["decisions"], "Q-3f2a1b0c9d8e")

    def test_a_started_task_needs_owner_attempt_and_checkpoints(self):
        for column in ("owner", "attempt", "checkpoints"):
            with self.subTest(column=column):
                text = with_row("tasks", "P02-T01", {column: "-"})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_an_in_flight_task_cannot_claim_completion_or_integration(self):
        for column in ("source_ref", "commits", "artifacts", "integration"):
            with self.subTest(column=column):
                text = with_row("tasks", "P02-T01",
                                {column: TASK_LIFECYCLE_CELLS[column]})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_blocked_task_names_its_question(self):
        text = with_row("tasks", "P02-T02", {"question": "-"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_completed_source_task_may_hold_its_integration(self):
        """Completion and integration are separate facts. When the drift budget
        trips, running work finishes, publishes and imports to ``[x]``; only
        integration is held. Freezing the import too would lose a finished
        task's evidence and repeat the work on resume."""
        tracker = pas.parse_tracker(valid_text())
        held = next(row for row in tracker["tasks"] if row["id"] == "P01-T02")
        self.assertEqual(held["state"], "[x]")
        self.assertEqual(held["integration"], "held")

    def test_a_completed_source_task_records_its_integration_or_the_hold(self):
        """``held`` is the one word that may stand in for the commit, and it
        says a specific thing: finished, not yet integrated. ``-`` says nothing
        at all, ``N/A`` borrows the artifact task's marker to claim integration
        does not apply to source, and a branch name is not an immutable edge."""
        for integration in ("-", "N/A", "merged", "refs/heads/feat/pipeline-auto",
                            "FEDCBA9876543210FEDCBA9876543210FEDCBA98",
                            "fedcba9876543210fedcba9876543210fedcba9"):
            with self.subTest(integration=integration):
                text = with_row("tasks", "P01-T02", {"integration": integration})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_completed_source_task_needs_its_source_ref_and_commits(self):
        for column in ("source_ref", "commits"):
            with self.subTest(column=column):
                text = with_row("tasks", "P01-T02", {column: "-"})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_task_commit_list_is_commit_shas(self):
        """``Commits`` is what the ``baseline..source-head`` range proof is run
        over. A symbolic name resolves differently tomorrow, so a range built on
        one proves nothing about what was reviewed."""
        for commits in ("HEAD~1", "0123456789abcdef0123456789abcdef0123456",
                        "0123456789abcdef0123456789abcdef01234567,HEAD"):
            with self.subTest(commits=commits):
                text = with_row("tasks", "P01-T02", {"commits": commits})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_completed_task_needs_its_result_and_verification(self):
        for column in ("result", "verification"):
            with self.subTest(column=column):
                text = with_row("tasks", "P01-T01", {column: "-"})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_completed_artifact_task_parses_with_na_integration(self):
        """The positive control for the two cases below: this exact row is
        legal, so their raises are caused by the one cell each changes and not
        by winding P02-T01 forward to ``[x]``."""
        tracker = pas.parse_tracker(completed_artifact_task())
        done = next(row for row in tracker["tasks"] if row["id"] == "P02-T01")
        self.assertEqual((done["state"], done["integration"]), ("[x]", "N/A"))

    def test_a_completed_artifact_task_carries_na_integration(self):
        """An artifact task produces no source range to integrate. Letting it
        record ``held`` would put a task that can never be integrated into the
        set the budget freeze is waiting on."""
        text = completed_artifact_task(integration="held")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_completed_artifact_task_names_its_artifacts(self):
        text = completed_artifact_task(artifacts="-")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_provisional_is_yes_or_no(self):
        text = with_row("tasks", "P01-T01", {"provisional": "maybe"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_task_kind_is_source_or_artifact(self):
        text = with_row("tasks", "P02-T01", {"kind": "docs"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_task_state_is_a_known_checkbox(self):
        """Built on the row that is otherwise LEGALLY COMPLETE, so the enum is
        the only thing left to refuse it. Spelling this on the in-flight row
        instead would raise either way — an unknown state falls past the
        in-flight branch into the completion rules and trips those — and the
        case would then pass against an enum quietly widened to admit ``[X]``,
        which is the mutation it exists to catch."""
        for state in ("[X]", "[-]", "[ x]", "x"):
            with self.subTest(state=state):
                text = completed_artifact_task(state=state)
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_task_cannot_belong_to_an_unknown_phase(self):
        text = with_row("tasks", "P01-T01", {"phase": "P99"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_duplicate_task_id_is_refused(self):
        """Every task helper in the later phases locates a task by scanning for
        its single ``ID`` row, so a second row on one id is a task whose state
        depends on which copy the scan reaches first."""
        row = next(line for line in valid_text().splitlines()
                   if line.startswith("| P02-T01 | "))
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(swap(row + "\n", row + "\n" + row + "\n"))

    def test_a_cited_decision_lies_in_one_of_the_two_id_namespaces(self):
        """``Decisions`` is the edge the provisional closure walks, and the
        prefix on each id is what the contradiction routing reads: a finding
        tracing to a human decision HALTS to the escalation queue, one tracing
        to a quorum decision re-opens that qid at a raised bar. An id in
        neither namespace routes as neither, and the task carries a taint no
        reviewer can be handed the answer to.

        Every value below is a near miss rather than obvious rubbish, because
        the mistake is not someone typing prose into the cell — it is a
        truncated qid, a case-folded one, or a decision id borrowed from
        another document's scheme, each of which reads like a match."""
        for decisions in ("H1", "h-1", "H-", "D-001", "scratch/p01-notes.md",
                          "Q-3f2a1b0c9d8", "Q-3F2A1B0C9D8E",
                          "H-1,Q-3f2a1b0c9d8"):
            with self.subTest(decisions=decisions):
                text = with_row("tasks", "P01-T02", {"decisions": decisions})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_task_cites_human_and_quorum_decisions_side_by_side(self):
        """The positive control: both id shapes in one cell, and a third task
        citing none. Whether an id RESOLVES is settled against ``decisions.md``,
        which this module never opens — so a well-formed id stands here even
        when no row of this tracker happens to hold it, and the quorum cases
        above stay free to rewrite a quorum's own Decision cell."""
        tracker = pas.parse_tracker(valid_text())
        cited = {row["id"]: row["decisions"] for row in tracker["tasks"]}
        self.assertEqual(cited["P01-T02"], "H-1,Q-3f2a1b0c9d8e")
        self.assertEqual(cited["P02-T02"], "-")
        pas.parse_tracker(with_row("tasks", "P01-T02", {"decisions": "H-9"}))


class PhaseSectionTests(unittest.TestCase):
    """``## Phases`` holds the review-intensity dial, and the dial is the one
    cost optimization an autonomous controller is most motivated to make about
    ITSELF: ``required`` buys the full per-task gate, ``final-only`` buys
    mechanical verification only. So the downward move is not discouraged here,
    it is unspellable.
    """

    def test_the_ratchet_is_one_way(self):
        """``final-only -> required`` only. A ratchet record paired with a
        ``final-only`` class is a downward reclassification wearing a ratchet's
        clothes, and the schema refuses it."""
        text = with_row("phases", "P02", {"review_class": "final-only"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_no_spelling_of_a_downward_reclassification_parses(self):
        """The whole cross product, asserted exhaustively rather than as three
        separate rules. Structural impossibility is a claim about what the
        schema admits, and only enumerating the alternatives proves it: five of
        these eight triples are refused, and the two that would let a run buy
        its way out of its own review — a ``final-only`` class carrying a
        ratchet record, and a ``plan`` class carrying one — are among them."""
        for review_class in ("required", "final-only"):
            for class_source in ("plan", "ratchet"):
                for ratchet in ("-", RATCHET_RECORD):
                    combination = (review_class, class_source, ratchet)
                    text = with_row("phases", "P02", {
                        "review_class": review_class,
                        "class_source": class_source,
                        "ratchet": ratchet,
                    })
                    with self.subTest(combination=combination):
                        if combination in LEGAL_CLASS_RECORDS:
                            pas.parse_tracker(text)
                        else:
                            with self.assertRaises(pas.TrackerValidationError):
                                pas.parse_tracker(text)

    def test_a_ratcheted_class_must_name_its_trigger_and_evidence(self):
        """``<trigger>@<evidence>``: what fired, and where the proof is. A bare
        trigger is an assertion the run makes about itself with nothing behind
        it, and a bare evidence path names no trigger to check it against —
        either one lets a class change be recorded that nothing can audit."""
        for ratchet in ("accumulated-surface", "@scratch/p02-ratchet.md",
                        "accumulated-surface@", "a@b@c",
                        "accumulated surface@scratch/p02-ratchet.md"):
            with self.subTest(ratchet=ratchet):
                text = with_row("phases", "P02", {"ratchet": ratchet})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_review_class_is_final_only_or_required(self):
        text = with_row("phases", "P01", {"review_class": "medium"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_class_source_is_plan_or_ratchet(self):
        text = with_row("phases", "P01", {"class_source": "controller"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_phase_state_is_a_known_checkbox(self):
        """``[?]`` is a TASK state and is the near miss that matters: a phase
        blocked on a question is a set of blocked tasks, and a phase-level
        ``[?]`` would be a second place to write a fact the task rows hold. P02
        is unverified with no evidence, so every other phase rule is satisfied
        and only the enum stands between this row and a parse."""
        for state in ("[?]", "[X]", "done"):
            with self.subTest(state=state):
                text = with_row("phases", "P02", {"state": state})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_verification_evidence_and_the_verified_state_stand_together(self):
        """Both directions, under BOTH review classes. The dial controls whether
        a reviewer runs, never what the state machine records, so a
        ``final-only`` phase is held to this exactly as a ``required`` one is."""
        for review_class in ("required", "final-only"):
            base = with_row("phases", "P02", {
                "review_class": review_class, "class_source": "plan",
                "ratchet": "-"})
            for phase_id, verification in (("P02", "scratch/x.txt"), ("P01", "-")):
                with self.subTest(review_class=review_class, phase=phase_id):
                    text = with_row("phases", phase_id,
                                    {"verification": verification}, base)
                    with self.assertRaises(pas.TrackerValidationError):
                        pas.parse_tracker(text)

    def test_a_phase_cannot_point_at_an_unknown_gate(self):
        text = with_row("phases", "P01", {"gate": "gate-p99"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_duplicate_phase_id_is_refused(self):
        row = next(line for line in valid_text().splitlines()
                   if line.startswith("| P02 | "))
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(swap(row + "\n", row + "\n" + row + "\n"))

    def test_a_final_only_phase_keeps_every_task_and_gate_rule(self):
        """The defect this class exists to prevent: a validator a phase's own
        class can switch off. The dial buys review, never integrity, so the
        tracker rules below have to fire identically on a ``final-only`` phase —
        including the ones a run under budget pressure would most like to skip,
        the immutable gate edge and the recorded integration."""
        relaxed = with_row("phases", "P02", {
            "review_class": "final-only", "class_source": "plan", "ratchet": "-"})
        pas.parse_tracker(relaxed)
        for key, row_id, cells in (
            ("tasks", "P02-T01", {"kind": "docs"}),
            ("tasks", "P02-T01", {"owner": "-"}),
            ("tasks", "P02-T01", {"phase": "P99"}),
            ("gates", "gate-p02", {"base": "-"}),
            ("gates", "gate-p02", {"head": "HEAD~1"}),
            ("gates", "gate-p02", {"assignments": "-"}),
        ):
            with self.subTest(section=key, row=row_id, cells=cells):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(with_row(key, row_id, cells, relaxed))


class GateSectionTests(unittest.TestCase):
    """``## Gates`` records the edge a review was actually run over.

    The edge is the reviewable unit. Its two ends are commit shas because the
    ``baseline..source-head`` range proof is only a proof if both ends are
    immutable — the spec is explicit that a review package comes from the
    persisted reservation baseline and never from ``HEAD~1``.
    """

    def test_a_master_gate_cannot_name_a_phase(self):
        text = with_row("gates", "gate-master", {"phase": "P02"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_phase_gate_must_name_a_known_phase(self):
        for phase in ("P99", "-"):
            with self.subTest(phase=phase):
                text = with_row("gates", "gate-p01", {"phase": phase})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_gate_type_is_phase_or_master(self):
        text = with_row("gates", "gate-p01", {"type": "task"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_gate_state_is_known(self):
        text = with_row("gates", "gate-p02", {"state": "open"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_opened_gate_needs_its_immutable_edge(self):
        for column in ("base", "head", "assignments"):
            with self.subTest(column=column):
                text = with_row("gates", "gate-p02", {column: "-"})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_gate_edge_is_spelled_as_commit_shas(self):
        for column in ("base", "head"):
            for value in ("HEAD~1", "feat/pipeline-auto",
                          "111111111111111111111111111111111111111",
                          "C8BDDD610119F52B54BF077D284C7F5D8362AE77"):
                with self.subTest(column=column, value=value):
                    text = with_row("gates", "gate-p02", {column: value})
                    with self.assertRaises(pas.TrackerValidationError):
                        pas.parse_tracker(text)

    def test_an_evaluated_gate_needs_reports_and_verification(self):
        for state in ("accepted", "blocked"):
            for column in ("reports", "verification"):
                with self.subTest(state=state, column=column):
                    text = with_row("gates", "gate-p01",
                                    {"state": state, column: "-"})
                    with self.assertRaises(pas.TrackerValidationError):
                        pas.parse_tracker(text)

    def test_a_duplicate_gate_id_is_refused(self):
        row = next(line for line in valid_text().splitlines()
                   if line.startswith("| gate-p02 | "))
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(swap(row + "\n", row + "\n" + row + "\n"))


#: Every ``## Task Review`` cell a reviewer fills in. A round nobody has started
#: carries none of them. Spelled out rather than imported from the module's own
#: constant, so dropping a name there leaves the subtest that catches the drop
#: standing rather than deleting it along with the rule.
REVIEW_LIFECYCLE_CELLS = {
    "package": "scratch/review-package.md",
    "report": "scratch/review-report.md",
    "critical": "1",
    "important": "1",
    "minor": "0",
    "open": "2",
    "evidence": "scratch/review-rerun.txt",
}

#: A review round that has been assigned and nothing more.
PENDING_REVIEW = dict({key: "-" for key in REVIEW_LIFECYCLE_CELLS}, state="pending")
#: A review round in flight: the reviewer holds the package and has returned
#: nothing yet.
REVIEWING_REVIEW = dict(PENDING_REVIEW, state="reviewing",
                        package=REVIEW_LIFECYCLE_CELLS["package"])

FIX_COMMIT = "abcdef0123456789abcdef0123456789abcdef01"


def completed_fix(number: int, findings: str, remaining: str) -> dict[str, str]:
    """One legally completed ``## Fix Rounds`` row, as named cells."""
    return {
        "round": str(number),
        "state": "complete",
        "fixer": f"fixer-{number}",
        "findings": findings,
        "commits": FIX_COMMIT[:-1] + str(number),
        "verification": f"scratch/fix-r{number}-tests.txt",
        "re_review": f"scratch/fix-r{number}-review.md",
        "remaining": remaining,
    }


def fixing_fix(number: int, findings: str) -> dict[str, str]:
    """One legally in-flight ``## Fix Rounds`` row, as named cells."""
    return {
        "round": str(number), "state": "fixing", "fixer": f"fixer-{number}",
        "findings": findings, "commits": "-", "verification": "-",
        "re_review": "-", "remaining": "-",
    }


class TaskReviewSectionTests(unittest.TestCase):
    """``## Task Review`` is what makes "zero open findings" checkable.

    It is a SECTION rather than columns on ``## Tasks`` because a task has N
    review rounds, not one. Columns would force either a second row per task —
    breaking the one-row-per-task invariant every task helper assumes — or a
    comma-packed history cell, which is how the previous pipeline's
    ``Checkpoints`` column became unparseable.

    Two rules carry most of the weight. ``Open`` must equal the three severity
    counts summed, so a row cannot record ``Minor 3`` and ``Open 0``: Minor is
    not a deferral category in this project and the schema is where that stops
    being a promise. And a task cannot stand at ``[x]`` while its last review
    round says anything but ``accepted``.

    What is deliberately NOT here is a rule that a ``[x]`` task must HAVE a
    review round. Requiring one would be this module branching on the review
    dial by the back door — ``final-only`` buys no per-task reviewer, and a
    schema that demanded a review row anyway would make the dial unusable. The
    committed fixture pins that: ``P01-T02`` is ``[x]`` in a ``required`` phase
    with no review row at all, and it parses.
    """

    def test_a_tasks_own_implementer_cannot_review_it(self):
        """Non-implementer review is one of the things the dial may never
        switch off, because self-review passes anything. ``P02-T01`` is owned by
        ``impl-2``; naming ``impl-2`` as its reviewer is the whole mistake, and
        the row is otherwise exactly the committed one."""
        text = with_review("P02-T01", "1", {"reviewer": "impl-2"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_one_reviewer_per_round(self):
        """Two reviewers on one row are two verdicts with no way to tell which
        one the ``State`` cell records."""
        text = with_review("P02-T01", "1", {"reviewer": "reviewer-2,reviewer-9"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_review_cannot_name_an_unknown_task(self):
        text = with_review("P02-T01", "1", {"task": "P09-T09"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unknown_review_state_is_rejected(self):
        """The row is otherwise a legal evaluated review, so nothing downstream
        can raise on it: only the enum can. Catches replacing the membership
        assertion with a default, which turns a malformed state into a legal one
        through an illegal door."""
        text = with_review("P02-T01", "1", {"state": "judged"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unknown_review_intensity_is_rejected(self):
        text = with_review("P02-T01", "1", {"intensity": "light"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_review_intensity_never_ratchets_down_across_rounds(self):
        """``Intensity`` is recorded per ROW so the ratchet is visible in the
        review history itself and not only in the phase record. That is worth
        nothing if the history may go back down: a round re-run at ``standard``
        after an ``adversarial`` round is a run buying its way out of the bar it
        just raised, which is the same move ``## Phases`` has no spelling for.
        Both rows here are individually legal; only the sequence is not."""
        text = with_review("P01-T01", "1", {
            "intensity": "adversarial",
            "adversarial": "accumulated-surface",
            "adversarial_verdict": "fail"})
        text = with_review("P01-T01", "2", {
            "intensity": "standard", "adversarial": "-",
            "adversarial_verdict": "-"}, text)
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_repeated_intensity_is_legal_because_only_the_downward_move_is_not(self):
        """The positive control the case above needs. Catches an implementation
        that forbids any CHANGE of intensity rather than the downward one, which
        would make the ratchet unrecordable in the one direction it exists for.
        """
        tracker = pas.parse_tracker(with_review("P01-T01", "1", {
            "intensity": "adversarial",
            "adversarial": "accumulated-surface",
            "adversarial_verdict": "fail"}))
        self.assertEqual([row["intensity"] for row in tracker["task_review"]],
                         ["adversarial", "adversarial", "standard"])

    def test_open_is_the_sum_of_the_three_severities(self):
        """The rule that makes "zero open findings at EVERY severity" a machine
        check. ``Minor 3`` beside ``Open 2`` is a Minor deferral written down,
        and this project has no deferral category. The row stays ``blocked``
        with two open findings, so no other rule can be what raises."""
        text = with_review("P02-T01", "1", {"minor": "3"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_finding_count_is_ascii_digits(self):
        """``isdigit`` alone is true of ``'٣'`` and ``int()`` reads it back as
        3, so a sum check on its own accepts a count that renders into the
        tracker looking like a number nothing downstream can match. The second
        case is chosen so the SUM still balances: only the grammar can reject
        it."""
        for column, cells in (
            ("critical", {"critical": "three"}),
            ("minor", {"minor": "٣", "open": "5"}),
            ("open", {"open": "٢"}),
        ):
            with self.subTest(column=column):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(with_review("P02-T01", "1", cells))

    def test_an_accepted_review_closes_at_zero_open_findings(self):
        """``P02-T01``'s round is ``[~]``-scoped, so the completion bar below
        cannot be what raises here — only the acceptance bar can."""
        text = with_review("P02-T01", "1", {"state": "accepted"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_blocked_review_must_have_open_findings(self):
        """The other half. A block at zero open findings is a halt with nothing
        to fix, and it is how a fix loop comes to run against an empty list."""
        text = with_review("P02-T01", "1",
                           {"critical": "0", "important": "0", "open": "0"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_evaluated_review_needs_package_report_and_independent_rerun(self):
        """The three artifacts a verdict rests on, in either direction. The
        ``Evidence`` cell is the INDEPENDENT re-run and is not a duplicate of
        the task's own ``Verification``: that cell records the implementer's
        run, and a reviewer who reads it instead of re-running has reviewed a
        claim rather than the code."""
        for column in ("package", "report", "evidence"):
            with self.subTest(column=column):
                text = with_review("P02-T01", "1", {column: "-"})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_pending_review_carries_no_verdict_and_no_evidence(self):
        """One subtest per cell, so dropping a single name from the constant
        leaves its own case failing rather than being covered by a neighbour."""
        for column, value in REVIEW_LIFECYCLE_CELLS.items():
            with self.subTest(column=column):
                text = with_review("P02-T01", "1",
                                   dict(PENDING_REVIEW, **{column: value}))
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_review_round_may_stand_assigned_and_unstarted(self):
        """The positive control the case above needs: a round the controller has
        assigned and no reviewer has opened is a legal state, not an error."""
        tracker = pas.parse_tracker(with_review("P02-T01", "1", PENDING_REVIEW))
        self.assertEqual(tracker["task_review"][2]["state"], "pending")
        self.assertEqual(tracker["task_review"][2]["open"], "-")

    def test_a_review_in_flight_holds_its_package_and_nothing_more(self):
        for column, value in REVIEW_LIFECYCLE_CELLS.items():
            if column == "package":
                continue
            with self.subTest(column=column):
                text = with_review("P02-T01", "1",
                                   dict(REVIEWING_REVIEW, **{column: value}))
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_review_in_flight_without_its_package_is_refused(self):
        """A reviewer who was never handed a package is a dispatch that was lost
        — and the positive control for the case above is the same row WITH it,
        which must parse."""
        self.assertEqual(
            pas.parse_tracker(
                with_review("P02-T01", "1", REVIEWING_REVIEW)
            )["task_review"][2]["state"], "reviewing")
        text = with_review("P02-T01", "1", dict(REVIEWING_REVIEW, package="-"))
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_adversarial_round_names_the_trigger_that_fired(self):
        """Both directions. An ``adversarial`` round with no trigger is a raised
        bar with nothing behind it, the same emptiness a bare ``Ratchet`` cell
        is; a ``standard`` round naming one is a trigger that fired and changed
        nothing."""
        for cells in ({"intensity": "adversarial"},
                      {"adversarial": "large-surface"}):
            with self.subTest(cells=cells):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(with_review("P02-T01", "1", cells))

    def test_an_adversarial_verdict_is_pass_or_fail(self):
        text = with_review("P01-T01", "2", {"adversarial_verdict": "ok"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_round_that_ran_no_adversarial_pass_records_no_verdict(self):
        text = with_review("P02-T01", "1", {"adversarial_verdict": "pass"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_accepted_review_cannot_stand_on_a_failed_adversarial_pass(self):
        """An acceptance recorded beside a failed adversarial pass is the
        ratchet fired and then ignored."""
        text = with_review("P01-T01", "2", {"adversarial_verdict": "fail"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_review_rounds_are_numbered_one_through_n_per_task(self):
        """Duplicates are the same fault as a gap: two rows numbered 1 are two
        verdicts for one round, and the run obeys whichever it read first."""
        for label, text in (
            ("gap", with_review("P02-T01", "1", {"round": "3"})),
            ("zero", with_review("P02-T01", "1", {"round": "0"})),
            ("not a number", with_review("P02-T01", "1", {"round": "one"})),
            ("duplicate", rounds_for("task_review", "P02-T01 | 1", ({}, {}))),
        ):
            with self.subTest(label=label):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_superseded_review_round_cannot_be_left_in_flight(self):
        """Round 1 abandoned mid-review while round 2 returned a verdict is a
        reviewer still holding a package nobody will read back."""
        text = with_review("P01-T01", "1", REVIEWING_REVIEW)
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_task_cannot_reach_complete_unless_its_last_round_is_accepted(self):
        """THE rule this section exists for. ``P01-T01`` is ``[x]``; winding its
        last review round back to anything but ``accepted`` must refuse the
        tracker, whatever the phase's review class says.

        Note what is NOT asserted: that round 1 also reads ``Open 0``. It does
        not — it records the single Important finding that round actually found,
        and the fix round below resolved it. ``Open`` is the count that round
        returned, not a cell later rounds rewrite, so the bar is stated over the
        round that stands as the task's verdict."""
        for cells in (
            {"state": "blocked", "important": "1", "open": "1"},
            dict(REVIEWING_REVIEW, adversarial_verdict="-"),
            dict(PENDING_REVIEW, adversarial="-", adversarial_verdict="-"),
        ):
            with self.subTest(state=cells["state"]):
                text = with_review("P01-T01", "2", cells)
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_completed_task_with_no_review_round_is_legal(self):
        """The dial decides WHETHER a reviewer runs; this module never reads it.
        A rule that every ``[x]`` task carry a review row would be this
        validator branching on ``Review Class`` by the back door, and would make
        ``final-only`` unusable. ``P01-T02`` is that case, committed."""
        tracker = pas.parse_tracker(valid_text())
        reviewed = {row["task"] for row in tracker["task_review"]}
        complete = {row["id"] for row in tracker["tasks"] if row["state"] == "[x]"}
        self.assertEqual(sorted(complete - reviewed), ["P01-T02"])

    def test_no_review_validator_reads_the_review_class_dial(self):
        """The dial decides whether a reviewer runs, never what bar it applies.
        A validator that relaxed under ``final-only`` would defeat the design it
        is there to hold, so the cells that spell the dial are asserted absent
        from both subtrees outright.

        Asserted over the CODE's own string constants, with the docstring
        dropped first. Dumping the whole subtree would match the prose that
        explains why the dial is not read — the guard would then be satisfied
        only by a function that never explains itself, and broken by one that
        does."""
        source = module_source()
        for name in ("_validate_task_review", "_validate_fix_rounds"):
            for cell in ("review_class", "class_source", "final-only"):
                with self.subTest(function=name, cell=cell):
                    self.assertNotIn(cell, code_constants(source, name))
        #: ``_validate_fix_rounds`` resolves a Scope against ``## Phases`` and so
        #: names that section; ``_validate_task_review`` has no business there at
        #: all, and not naming it is the stronger claim of the two.
        self.assertNotIn("phases", code_constants(source, "_validate_task_review"))


class FixRoundSectionTests(unittest.TestCase):
    """``## Fix Rounds`` bounds the loop and records that it actually closed.

    Three rounds, and a fourth halts to escalation rather than looping. A round
    that resolves none of the findings it was handed halts immediately without
    consuming the remainder, and so does one whose fixes re-raise something an
    earlier round had already resolved — both are a loop that will not converge,
    and spending the remaining rounds on it only delays the escalation.

    The loop closes on ``Remaining`` reading ``none``, which is the literal
    spelling of zero open findings at every severity. ``-`` and ``none`` are
    different facts here, as everywhere in this schema: ``-`` is "not written
    down", ``none`` is "written down, and it is empty".
    """

    def test_the_loop_closes_only_on_a_round_with_zero_remaining_findings(self):
        """A final round that still lists findings is a fix loop that stopped
        early, and the task above it is already ``[x]``."""
        text = with_fix("P01-T01", "1", {"remaining": "F-003"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_round_with_a_remainder_is_legal_when_a_later_round_carries_it(self):
        """The positive control. Round 1 resolves one of the two findings it was
        handed and passes the other on; round 2 closes at zero."""
        text = rounds_for("fix_rounds", "P01-T01 | 1", (
            completed_fix(1, "F-003,F-004", "F-003"),
            completed_fix(2, "F-003", "none")))
        tracker = pas.parse_tracker(text)
        self.assertEqual(len(tracker["fix_rounds"]), 3)
        self.assertEqual(tracker["fix_rounds"][1]["remaining"], "none")

    def test_the_fix_loop_is_bounded_at_three_rounds(self):
        """Every round here makes progress and re-raises nothing, so no other
        rule can be what refuses the fourth: only the bound can. A loop that has
        spent three rounds without closing is not converging, and the spec's
        answer is escalation, not a fourth attempt."""
        text = rounds_for("fix_rounds", "P01-T01 | 1", (
            completed_fix(1, "F-001,F-002,F-003,F-004", "F-002,F-003,F-004"),
            completed_fix(2, "F-002,F-003,F-004", "F-003,F-004"),
            completed_fix(3, "F-003,F-004", "F-004"),
            completed_fix(4, "F-004", "none")))
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_three_rounds_are_legal_because_the_bound_is_three_not_two(self):
        text = rounds_for("fix_rounds", "P01-T01 | 1", (
            completed_fix(1, "F-001,F-002,F-003", "F-002,F-003"),
            completed_fix(2, "F-002,F-003", "F-003"),
            completed_fix(3, "F-003", "none")))
        self.assertEqual(len(pas.parse_tracker(text)["fix_rounds"]), 4)

    def test_a_round_that_resolved_nothing_cannot_be_followed_by_another(self):
        """Round 1 was handed F-003 and gave back F-003. Spending round 2 on the
        identical list is the loop that does not converge, and it halts here
        rather than consuming the remainder of its budget first."""
        text = rounds_for("fix_rounds", "P01-T01 | 1", (
            completed_fix(1, "F-003", "F-003"),
            completed_fix(2, "F-003", "none")))
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_later_round_cannot_re_raise_a_finding_an_earlier_round_resolved(self):
        """Oscillation: round 1 resolved F-004 and round 2 is carrying it again.
        Round 1 made progress and round 2 closes at zero, so every other rule
        here is satisfied — only the re-raise is the fault."""
        text = rounds_for("fix_rounds", "P01-T01 | 1", (
            completed_fix(1, "F-003,F-004", "F-003"),
            completed_fix(2, "F-003,F-004", "none")))
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_only_the_last_round_of_a_scope_may_be_unfinished(self):
        """Two active rounds are two fixers editing one scope with no order
        between them; a finished round after an unfinished one is a round that
        was skipped. Both are the same fault and it is stated once. ``P02-T01``
        is ``[~]``, so the completion bar below cannot be what raises."""
        for label, second in (("two active", fixing_fix(2, "F-009")),
                              ("skipped", completed_fix(2, "F-009", "none"))):
            with self.subTest(label=label):
                text = rounds_for("fix_rounds", "P02-T01 | 1",
                                  ({}, dict(second, scope="P02-T01")))
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_scope_cannot_be_complete_with_an_unfinished_fix_round(self):
        """Scoped to a task and to a phase, because ``## Fix Rounds`` is scoped
        to either. A scope marked done while a fixer is still working is the
        same missing bar as an unaccepted review round under a ``[x]`` task."""
        with self.subTest(scope="task"):
            text = with_fix("P01-T01", "1", {
                "state": "fixing", "commits": "-", "verification": "-",
                "re_review": "-", "remaining": "-"})
            with self.assertRaises(pas.TrackerValidationError):
                pas.parse_tracker(text)
        with self.subTest(scope="phase"):
            text = rounds_for("fix_rounds", "P02-T01 | 1", (
                {}, dict(fixing_fix(1, "F-007"), scope="P01")))
            with self.assertRaises(pas.TrackerValidationError):
                pas.parse_tracker(text)

    def test_a_round_cannot_name_an_unknown_scope(self):
        text = with_fix("P02-T01", "1", {"scope": "P09-T09"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_fix_round_may_be_scoped_to_a_phase_or_a_gate(self):
        """The positive control: a fix round is scoped to a task, a phase OR a
        gate, which is why there is no ``## Remediation`` section."""
        for scope in ("P02", "gate-p02"):
            with self.subTest(scope=scope):
                tracker = pas.parse_tracker(
                    with_fix("P02-T01", "1", {"scope": scope}))
                self.assertEqual(tracker["fix_rounds"][1]["scope"], scope)

    def test_an_unknown_fix_round_state_is_rejected(self):
        """Stated on a row that is otherwise a legal completed round of a ``[~]``
        scope, so nothing downstream can raise on it: only the enum can."""
        text = with_fix("P02-T01", "1",
                        dict(completed_fix(1, "F-001,F-002", "none"),
                             state="done"))
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_rounds_are_numbered_one_through_n_per_scope(self):
        for label, cells in (("gap", {"round": "3"}),
                             ("zero", {"round": "0"}),
                             ("not a number", {"round": "one"})):
            with self.subTest(label=label):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(with_fix("P02-T01", "1", cells))

    def test_one_fixer_per_round_carrying_all_of_its_findings(self):
        """Two fixers on one round are two edits to one scope with no order
        between them, and the second silently overwrites the first."""
        text = with_fix("P02-T01", "1", {"fixer": "fixer-1,fixer-9"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_started_round_names_the_findings_it_is_carrying(self):
        text = with_fix("P02-T01", "1", {"findings": "-"})
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_fixing_round_has_produced_nothing_yet(self):
        """Including ``Remaining``: only a completed round records an outcome,
        because an outcome on a round still running is a result reported before
        the work it reports on finished."""
        for column, value in (("commits", FIX_COMMIT),
                              ("verification", "scratch/x-tests.txt"),
                              ("re_review", "scratch/x-review.md"),
                              ("remaining", "none")):
            with self.subTest(column=column):
                text = with_fix("P02-T01", "1", {column: value})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_pending_round_carries_no_lifecycle_state(self):
        pending = {"state": "pending", "fixer": "-", "findings": "-",
                   "commits": "-", "verification": "-", "re_review": "-",
                   "remaining": "-"}
        self.assertEqual(
            pas.parse_tracker(with_fix("P02-T01", "1", pending)
                              )["fix_rounds"][1]["state"], "pending")
        for column, value in (("fixer", "fixer-1"), ("findings", "F-001"),
                              ("commits", FIX_COMMIT),
                              ("verification", "scratch/x-tests.txt"),
                              ("re_review", "scratch/x-review.md"),
                              ("remaining", "none")):
            with self.subTest(column=column):
                text = with_fix("P02-T01", "1", dict(pending, **{column: value}))
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_re_reviewing_round_carries_its_commits_and_verification(self):
        """The state between the fix and its verdict: the work landed and was
        re-run, and the re-review has not reported back. The positive control
        comes first so the rejections below cannot be passing on a row that was
        never legal to begin with."""
        base = {"state": "re_reviewing", "commits": FIX_COMMIT,
                "verification": "scratch/x-tests.txt"}
        self.assertEqual(
            pas.parse_tracker(with_fix("P02-T01", "1", base)
                              )["fix_rounds"][1]["state"], "re_reviewing")
        for column, value in (("commits", "-"), ("verification", "-"),
                              ("re_review", "scratch/x-review.md"),
                              ("remaining", "none")):
            with self.subTest(column=column):
                text = with_fix("P02-T01", "1", dict(base, **{column: value}))
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_completed_round_records_its_full_lifecycle(self):
        for column in ("fixer", "findings", "commits", "verification",
                       "re_review", "remaining"):
            with self.subTest(column=column):
                text = with_fix("P01-T01", "1", {column: "-"})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)

    def test_a_fix_commit_is_a_commit_sha(self):
        """A fix round's commits are the far end of the same range proof the
        task rows carry, and a symbolic end resolves somewhere else tomorrow."""
        for value in ("HEAD~1", "feat/pipeline-auto",
                      "ABCDEF0123456789ABCDEF0123456789ABCDEF01"):
            with self.subTest(value=value):
                text = with_fix("P01-T01", "1", {"commits": value})
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_tracker(text)


#: How long the holder process keeps the lock if nobody ever releases it. It is
#: a backstop, not a wait: every case sets the release event itself. A holder
#: that blocked forever would wedge the whole suite behind a process this
#: interpreter cannot kill from a failed assertion.
LOCK_HOLD_SECONDS = 20.0

#: Where the holder records the pid of the interpreter that took the lock.
HOLDER_PID_FILE = "holder.pid"

#: How long a case waits on another process. Generous, because a spawned
#: interpreter has to import this module from cold, and bounded, because an
#: unbounded wait is the deadlock this constant exists to refuse.
HOLDER_WAIT_SECONDS = 30.0

#: The timeout the waiter in the inode-swap case gives itself. Long enough that
#: it is still spinning in the retry loop while the swap happens, and short
#: enough that it gives up on its own if the swap never comes — so no join in
#: that case can outlast it.
SWAP_WAITER_SECONDS = 5.0

#: How long that case polls for the waiter to reach the retry loop, in seconds
#: per pass. Short, because the barrier it polls for is an effect the waiter
#: produces before its first attempt, not a guess about scheduling.
SWAP_POLL_SECONDS = 0.005


def hold_lock(run_dir: str, ready, release) -> None:
    """Take the run lock in a SEPARATE process and hold it until told to stop.

    Top-level and importable by name because the ``spawn`` start method
    re-imports this module in the child rather than cloning this interpreter.
    ``spawn`` is chosen deliberately, not for portability: a ``fork``ed child
    inherits this process's open file descriptors, and a ``flock`` lock belongs
    to the open file DESCRIPTION rather than to the process, so a forked holder
    could be sharing the parent's own lock instead of competing for it. The
    contention test would then pass while proving nothing at all.
    """
    import pipeline_auto_state as module
    with module._exclusive_lock(Path(run_dir), timeout_s=5.0):
        #: Written by the code that actually holds the lock, so the caller can
        #: check WHICH interpreter that was rather than take it on trust.
        (Path(run_dir) / HOLDER_PID_FILE).write_text(str(os.getpid()),
                                                     encoding="utf-8")
        ready.set()
        release.wait(LOCK_HOLD_SECONDS)


def reap_holder(case: unittest.TestCase, holder) -> None:
    """Never leave a child behind, whatever the case did or failed to do."""
    holder.join(HOLDER_WAIT_SECONDS)
    if holder.is_alive():  # pragma: no cover - only on a wedged holder
        holder.terminate()
        holder.join(HOLDER_WAIT_SECONDS)


def start_holder(case: unittest.TestCase, run_dir: Path):
    """A second OS process, already holding the lock when this returns.

    Module-level rather than a ``LockTests`` method because ``LockedUpdateTests``
    below has to prove the same cross-process refusal one layer up: that
    ``locked_tracker_update`` is actually wired to this lock. Copying ten lines
    of process choreography into a second class is how one copy quietly
    degrades to ``fork`` and starts proving nothing.
    """
    context = multiprocessing.get_context("spawn")
    case.assertEqual(
        context.get_start_method(), "spawn",
        "a forked holder inherits this interpreter's descriptors, and a "
        "flock belongs to the open file description, not the process")
    ready, release = context.Event(), context.Event()
    holder = context.Process(target=hold_lock,
                             args=(str(run_dir), ready, release),
                             daemon=True)
    holder.start()
    case.addCleanup(reap_holder, case, holder)
    case.addCleanup(release.set)
    case.assertTrue(
        ready.wait(HOLDER_WAIT_SECONDS),
        "the holder process never signalled that it acquired the lock")
    return holder, release


class FakeFlock:
    """A stand-in for ``fcntl`` whose ``flock`` always fails with one errno.

    The real ``flock`` on this platform returns either success or ``EWOULDBLOCK``
    and nothing else, so the branch that decides which errnos mean "somebody
    else holds it" and which mean "this primitive is broken" is unreachable
    from a real filesystem. It is reachable from here.
    """

    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def __init__(self, number: int | None = None) -> None:
        self.number = number
        self.operations: list[int] = []

    def flock(self, descriptor: int, operation: int) -> None:
        self.operations.append(operation)
        if operation == self.LOCK_UN or self.number is None:
            return
        raise OSError(self.number, os.strerror(self.number))


class FakeLocking:
    """A stand-in for ``msvcrt``, recording whether it was reached at all."""

    LK_NBLCK = 1
    LK_UNLCK = 0

    def __init__(self) -> None:
        self.operations: list[int] = []

    def locking(self, descriptor: int, mode: int, length: int) -> None:
        self.operations.append(mode)


class LockTests(unittest.TestCase):
    """The run lock, which is what turns "only the controller writes" into a
    mechanism instead of a sentence in a skill file.

    This module runs under many concurrent agents. Every rule the validators
    above enforce is defeated by two writers interleaving a read-modify-write
    on ``progress.md``, and no validator can see that happen: both writes are
    individually well-formed and the loser's simply vanishes.
    """

    def test_lock_errors_are_write_errors_so_callers_know_nothing_changed(self):
        """A caller that cannot take the lock has changed nothing, which is
        exactly what ``TrackerWriteError`` means. Raising something outside that
        family would make a contended controller look like an uncertain one and
        invite the reconciliation a clean refusal does not need."""
        self.assertTrue(issubclass(pas.LockUnavailableError, pas.TrackerWriteError))
        self.assertTrue(issubclass(pas.LockBusyError, pas.TrackerWriteError))
        self.assertFalse(issubclass(pas.LockBusyError, pas.UpdateOutcomeUncertain))
        self.assertFalse(issubclass(pas.LockBusyError, pas.LockUnavailableError))
        self.assertFalse(issubclass(pas.LockUnavailableError, pas.LockBusyError))

    def test_a_second_process_is_refused_while_the_first_still_holds_the_lock(self):
        """The mistake: a lock that is really a re-entrancy guard.

        Acquiring twice inside ONE interpreter can be refused by a flag, a
        thread lock, or a set of held paths — none of which stops the OTHER
        agent, in the other process, that this module actually has to survive.
        So the first holder is a separate spawned interpreter, and the refusal
        is asserted against it.

        The second failure this guards against is a refusal that proves nothing
        because the holder had already finished: the holder cannot leave its
        ``with`` block until ``release`` is set or ``LOCK_HOLD_SECONDS`` elapse,
        neither of which has happened inside a 0.2 s timeout, so asserting it is
        still alive after the refusal pins that the lock was genuinely held at
        that moment.

        The pid the holder writes from INSIDE its ``with`` block is compared
        against this interpreter's own, so "another process" is asserted rather
        than assumed: a rewrite to a thread, or to a same-process second
        acquire, fails here instead of quietly proving something weaker.

        The third is a refusal that is not contention at all — an acquire that
        can never succeed would also raise here — so the holder is then released
        and the same directory is locked successfully by this process.
        """
        run_dir = make_run(self)
        holder, release = start_holder(self, run_dir)
        holder_pid = int((run_dir / HOLDER_PID_FILE).read_text(encoding="utf-8"))
        self.assertEqual(holder_pid, holder.pid)
        self.assertNotEqual(
            holder_pid, os.getpid(),
            "the lock was taken inside this interpreter, so whatever the "
            "refusal below proves, it is not cross-process contention")
        with self.assertRaises(pas.LockBusyError):
            with pas._exclusive_lock(run_dir, timeout_s=0.2):
                pass
        self.assertTrue(
            holder.is_alive(),
            "the holder exited before the refusal, so the refusal is not "
            "evidence of contention")
        release.set()
        holder.join(HOLDER_WAIT_SECONDS)
        self.assertEqual(
            holder.exitcode, 0,
            "the holder did not exit cleanly, so what it was doing with the "
            "lock is unknown")
        with pas._exclusive_lock(run_dir, timeout_s=5.0):
            pass

    def test_the_lock_is_reacquirable_once_released(self):
        """A lock that is never released is indistinguishable from a deadlock
        one run later. ``flock`` binds to the open file description, so the
        second ``os.open`` here is a genuinely different contender even within
        one process."""
        run_dir = make_run(self)
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            pass
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            pass

    def test_the_lock_survives_an_exception_raised_while_it_is_held(self):
        """A mutation that dies mid-write must not strand the lock, or the run
        wedges on its own error path rather than reporting it."""
        run_dir = make_run(self)
        with self.assertRaises(ZeroDivisionError):
            with pas._exclusive_lock(run_dir, timeout_s=1.0):
                raise ZeroDivisionError("a mutation blew up under the lock")
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            pass

    def test_the_lock_is_handed_back_explicitly_and_not_only_by_closing(self):
        """The two cases above cannot see the release call, and that is a real
        hole rather than a pedantic one.

        A POSIX ``flock`` is dropped when the last descriptor on the open file
        description closes, so "can I lock it again" stays green even if
        ``release`` is deleted outright — a mutation replacing the release with
        ``return None`` left both of those cases passing. What they actually
        pin is the ``finally``: remove release AND close and they fail. So the
        release is pinned here instead, as the operation the module issues, on
        the real ``_exclusive_lock`` against a recording stand-in for the
        primitive. It matters beyond tidiness: ``msvcrt`` byte-range locks are
        not guaranteed to be dropped by a close, and a later caller that holds
        the descriptor open across two mutations would keep the lock forever.
        """
        run_dir = make_run(self)
        fake = FakeFlock()
        self.addCleanup(setattr, pas, "fcntl", pas.fcntl)
        pas.fcntl = fake
        expected = [fake.LOCK_EX | fake.LOCK_NB, fake.LOCK_UN]
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            self.assertEqual(fake.operations, expected[:1],
                             "released while the body was still running")
        self.assertEqual(fake.operations, expected)
        fake.operations.clear()
        with self.assertRaises(ZeroDivisionError):
            with pas._exclusive_lock(run_dir, timeout_s=1.0):
                raise ZeroDivisionError("a mutation blew up under the lock")
        self.assertEqual(fake.operations, expected,
                         "a body that raised left the lock unreleased")

    def test_the_lock_file_lives_in_the_run_directory_and_is_never_unlinked(self):
        """Unlinking a lock file is the classic way to hold a lock and still
        lose: two holders open two different inodes at the same path, each locks
        its own, and both believe they won. So the path is created once and
        kept, and its inode is the same one after a second acquisition."""
        run_dir = make_run(self)
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            pass
        lock_path = run_dir / ".pipeline-auto.lock"
        self.assertTrue(lock_path.is_file(), sorted(p.name for p in run_dir.iterdir()))
        inode = lock_path.stat().st_ino
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            pass
        self.assertEqual(lock_path.stat().st_ino, inode)

    def test_a_lock_held_on_a_replaced_inode_is_refused_not_reported_as_held(self):
        """The post-acquire ``(st_dev, st_ino)`` identity check, falsified.

        The case above pins that THIS module never unlinks the lock file. That
        is not the same guarantee: ``os.open`` and the lock call are two
        syscalls, and anything else on the machine — a stray ``rm``, a cleanup
        script, an older build that did unlink on release — can replace the
        inode at that path in between. The descriptor then holds a perfectly
        real lock on an inode nobody will ever contend for again, while the
        next caller opens the NEW inode, finds it free, and wins. Two holders,
        one path, both certain. Reporting success there is worse than failing:
        the lock is the only thing standing between two controllers and an
        interleaved read-modify-write of ``progress.md``.

        The window is reached through the module's own API, not by patching:

        1. This interpreter takes the lock directly, on the original inode,
           using the primitive the module itself selects.
        2. A waiter thread calls ``_exclusive_lock`` on the same directory. It
           opens that same original inode — the path still points at it — and
           then spins in the retry loop.
        3. The barrier is an effect only the waiter produces: ``_exclusive_lock``
           writes its one byte before its first attempt, and this case watches
           the size through the HOLDER's descriptor, so observing 1 proves the
           waiter opened the inode this case is about to unlink rather than a
           later one. Without that, a slow waiter would open the replacement,
           acquire it cleanly, and the case would prove nothing while passing.
        4. The lock file is unlinked and recreated, and only then is the
           original lock released. The waiter's next attempt therefore succeeds
           — on an inode that is no longer the lock file.

        A thread rather than a process because the waiter's exception is the
        evidence, and because ``flock`` binds to the open file description: a
        second ``os.open`` in this interpreter contends exactly as another
        process would. The waiter is a daemon, bounds its own wait, and its
        body only sets a flag, so nothing here can outlive the case.
        """
        run_dir = make_run(self)
        lock_path = run_dir / pas.LOCK_FILENAME
        acquire, release, _ = pas.select_lock_impl(pas.fcntl, pas.msvcrt)
        holder = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        state = {"locked": False, "open": True}

        def let_go() -> None:
            """Release and close once, whether the case reached that point."""
            if state["locked"]:
                release(holder)
                state["locked"] = False
            if state["open"]:
                os.close(holder)
                state["open"] = False

        self.addCleanup(let_go)
        self.assertTrue(acquire(holder), "the fresh lock file was already held")
        state["locked"] = True
        outcome: dict[str, object] = {}

        def wait_for_the_lock() -> None:
            try:
                with pas._exclusive_lock(run_dir, timeout_s=SWAP_WAITER_SECONDS):
                    outcome["entered"] = True
            except BaseException as exc:  # reported to the case, not swallowed
                outcome["error"] = exc

        waiter = threading.Thread(target=wait_for_the_lock, daemon=True)
        waiter.start()
        self.addCleanup(waiter.join, HOLDER_WAIT_SECONDS)
        deadline = time.monotonic() + HOLDER_WAIT_SECONDS
        while time.monotonic() < deadline and os.fstat(holder).st_size == 0:
            time.sleep(SWAP_POLL_SECONDS)
        self.assertEqual(
            os.fstat(holder).st_size, 1,
            "the waiter never opened the original lock inode, so replacing it "
            "below would not be the race this case is about")
        original = os.fstat(holder).st_ino
        os.unlink(lock_path)
        os.close(os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600))
        self.assertNotEqual(lock_path.stat().st_ino, original,
                            "the replacement reused the original inode")
        let_go()
        waiter.join(HOLDER_WAIT_SECONDS)
        self.assertFalse(waiter.is_alive(),
                         "the waiter never finished; the lock may still be held")
        self.assertNotIn(
            "entered", outcome,
            "the caller was told it holds the run lock while its lock is on an "
            "inode that is no longer the lock file, so a second controller can "
            "take the real one and both will write")
        self.assertIsInstance(outcome.get("error"), pas.LockUnavailableError)
        self.assertIn(str(lock_path), str(outcome["error"]))

    def test_no_os_lock_primitive_is_an_explicit_failure_not_a_silent_no_lock(self):
        """Falling back to "no lock" would turn every concurrency guarantee in
        this module into a comment, and the failure would only ever surface as
        corrupted state long after the run that caused it. A module present but
        lacking the call is the same case as a module that is absent."""
        with self.assertRaises(pas.LockUnavailableError):
            pas.select_lock_impl(None, None)
        with self.assertRaises(pas.LockUnavailableError):
            pas.select_lock_impl(types.SimpleNamespace(), types.SimpleNamespace())

    def test_the_posix_primitive_is_preferred_over_the_unverified_windows_one(self):
        """``msvcrt.locking`` is executable here but has never been run against
        a native Windows kernel; ``fcntl.flock`` is what this platform actually
        proves. Reaching for the unverified path while the proven one is present
        would ship an untested lock everywhere."""
        posix, windows = FakeFlock(errno.EWOULDBLOCK), FakeLocking()
        acquire, _, description = pas.select_lock_impl(posix, windows)
        self.assertFalse(acquire(0))
        self.assertEqual(posix.operations, [posix.LOCK_EX | posix.LOCK_NB])
        self.assertEqual(windows.operations, [])
        self.assertIn("flock", description)

    def test_only_a_contention_errno_is_reported_as_busy(self):
        """The one judgement ``select_lock_impl`` makes, and the one a real
        filesystem cannot exercise: which failures mean "wait your turn".

        Widening the set is the dangerous direction. ``ENOLCK`` — the kernel is
        out of lock records — and ``EDEADLOCK`` are not contention: swallowing
        them as "busy" makes the loop spin out its timeout and then report a
        competing holder that does not exist, sending a controller to retry a
        lock that will never be grantable. ``flock`` performs no deadlock
        detection, so ``EDEADLOCK`` from it means something is badly wrong.
        """
        for number in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
            with self.subTest(contention=errno.errorcode[number]):
                acquire, _, _ = pas.select_lock_impl(FakeFlock(number), None)
                self.assertFalse(acquire(0))
        for number in (errno.EPERM, errno.EIO, errno.ENOLCK, errno.EDEADLOCK,
                       errno.EBADF):
            with self.subTest(fault=errno.errorcode[number]):
                acquire, _, _ = pas.select_lock_impl(FakeFlock(number), None)
                with self.assertRaises(OSError) as caught:
                    acquire(0)
                self.assertEqual(caught.exception.errno, number)

    def test_a_broken_lock_primitive_is_unavailable_rather_than_busy(self):
        """``LockBusyError`` tells a caller to wait and retry. Reporting a
        primitive that cannot work as "busy" would make the controller retry
        forever; the two are siblings so that assertion cannot pass by
        inheritance."""
        run_dir = make_run(self)
        self.addCleanup(setattr, pas, "fcntl", pas.fcntl)
        pas.fcntl = FakeFlock(errno.ENOLCK)
        with self.assertRaises(pas.LockUnavailableError) as caught:
            with pas._exclusive_lock(run_dir, timeout_s=0.2):
                pass
        self.assertNotIsInstance(caught.exception, pas.LockBusyError)

    def test_a_negative_timeout_is_rejected(self):
        """A negative deadline is already past, so the loop would refuse a free
        lock on its first pass and report contention that never existed."""
        run_dir = make_run(self)
        with self.assertRaises(pas.LockUnavailableError):
            with pas._exclusive_lock(run_dir, timeout_s=-1.0):
                pass

    def test_a_zero_timeout_still_gets_one_honest_attempt(self):
        """``timeout_s=0`` means "do not wait", not "do not try". A caller that
        polls with zero would otherwise never acquire an uncontended lock.

        Reaching the body is not enough to show an attempt was made, and that
        gap is exactly how this case used to pass while proving nothing: change
        the retry loop to ``while time.monotonic() < deadline`` and a zero
        timeout skips the loop ENTIRELY — no acquire is ever issued, ``acquired``
        stays false, and the caller is handed a body it runs holding no lock at
        all. The free lock below makes that indistinguishable from success. So
        the attempt itself is counted, on the recording stand-in for the
        primitive: exactly one acquire before the body, and the matching
        release after it.
        """
        run_dir = make_run(self)
        with pas._exclusive_lock(run_dir, timeout_s=0.0):
            pass
        fake = FakeFlock()
        self.addCleanup(setattr, pas, "fcntl", pas.fcntl)
        pas.fcntl = fake
        attempt = [fake.LOCK_EX | fake.LOCK_NB]
        with pas._exclusive_lock(run_dir, timeout_s=0.0):
            self.assertEqual(
                fake.operations, attempt,
                "the body runs on a zero timeout without a single acquire "
                "having been issued: the attempt was skipped, not made")
        self.assertEqual(fake.operations, attempt + [fake.LOCK_UN])


class ReplaceTrackerTests(unittest.TestCase):
    """``_replace_tracker`` and the THREE outcomes a write can have.

    A write either did not happen, definitely happened, or **may** have
    happened. The third is not a hedge: between ``os.replace`` returning and
    the directory fsync completing there is a real interval in which a crash
    leaves a state the caller cannot tell from either neighbour. Reporting it
    as failure makes an autonomous retry apply the same transition twice;
    reporting it as success loses a write that never became durable. So the
    module raises ``TrackerWriteError`` for the first and
    ``UpdateOutcomeUncertain`` for the third, and they are siblings rather
    than parent and child so that a caller's ``except TrackerWriteError``
    cannot quietly absorb the one it must not retry.
    """

    def test_the_file_being_renamed_lives_in_the_run_directory(self):
        """A temp file in the system temp directory makes ``os.replace`` a
        cross-device rename: it raises instead of swapping, and the atomicity
        this whole function exists for is gone. Both the location and the
        device are asserted, because this suite's run directories are
        THEMSELVES under the system temp directory — so on this machine the two
        share a device and only the location check can fail, while on a machine
        where the repository and /tmp are separate filesystems the device check
        is the one that catches it first.
        """
        run_dir = make_run(self)
        seen = {}
        real_replace = os.replace

        def spy(source, destination):
            seen["source"] = Path(source)
            seen["device"] = os.stat(source).st_dev
            return real_replace(source, destination)

        with mock.patch.object(pas.os, "replace", side_effect=spy):
            pas._replace_tracker(run_dir, valid_text(), "transition-1")
        self.assertEqual(
            seen["source"].parent.resolve(), run_dir.resolve(),
            "the renamed file is not in the run directory; os.replace is a "
            "cross-device rename and no longer atomic")
        self.assertEqual(
            seen["device"], os.stat(run_dir / "progress.md").st_dev,
            "the temp file is on a different filesystem from progress.md")
        self.assertEqual((run_dir / "progress.md").read_text(encoding="utf-8"),
                         valid_text())

    def test_a_pre_replace_failure_leaves_the_old_tracker_intact(self):
        """Everything up to and including ``os.replace`` is 'nothing has
        happened yet'. The file fsync is inside that region, so its failure
        must leave progress.md byte-identical and must not strand the temp
        file: this run directory is listed by later phases, and a half-written
        ``.progress.*.tmp`` nothing ever removes is indistinguishable from one
        a live writer is using.
        """
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()
        replacement = swap("| revision | 12 |", "| revision | 99 |")
        with mock.patch.object(
                pas, "_sync_file",
                side_effect=OSError(errno.EIO, "simulated fsync failure")):
            with self.assertRaises(pas.TrackerWriteError) as caught:
                pas._replace_tracker(run_dir, replacement, "transition-2")
        self.assertNotIsInstance(caught.exception, pas.UpdateOutcomeUncertain)
        self.assertEqual(
            (run_dir / "progress.md").read_bytes(), before,
            "the tracker changed on a failure reported as 'nothing happened'")
        #: No lock file is expected: ``_replace_tracker`` takes no lock — its
        #: caller does — and ``make_run`` creates none. A later task that routes
        #: this through ``_exclusive_lock`` adds ``.pipeline-auto.lock`` here.
        self.assertEqual(
            sorted(p.name for p in run_dir.iterdir()), ["progress.md"],
            "a temp file survived the failure and nothing will clean it up")

    def test_a_post_replace_failure_raises_update_outcome_uncertain(self):
        """The replacement already landed; only its durability is in doubt.
        Reporting ``TrackerWriteError`` here tells an autonomous retry that
        nothing happened, and it re-applies a transition that did apply.
        """
        run_dir = make_run(self)
        replacement = swap("| revision | 12 |", "| revision | 13 |")
        with mock.patch.object(
                pas, "_sync_directory",
                side_effect=OSError(errno.EIO, "simulated dirsync failure")):
            with self.assertRaises(pas.UpdateOutcomeUncertain):
                pas._replace_tracker(run_dir, replacement, "transition-3")
        self.assertEqual(
            (run_dir / "progress.md").read_text(encoding="utf-8"), replacement,
            "the replacement is not on disk, so the directory sync ran before "
            "os.replace and the outcome was never uncertain to begin with")

    def test_update_outcome_uncertain_is_not_a_kind_of_tracker_write_error(self):
        """The static half of the distinction. ``TrackerWriteError`` promises
        nothing changed; ``UpdateOutcomeUncertain`` promises the opposite is
        possible. Making the second a subclass of the first would be a one-word
        edit that silently re-classifies every uncertain outcome as a safe
        retry, and both would still be raised from the right places.
        """
        self.assertFalse(issubclass(pas.UpdateOutcomeUncertain,
                                    pas.TrackerWriteError))
        self.assertFalse(issubclass(pas.TrackerWriteError,
                                    pas.UpdateOutcomeUncertain))
        self.assertTrue(issubclass(pas.UpdateOutcomeUncertain, pas.TrackerError))

    def bump_revision(self, run_dir) -> str:
        """The current tracker with ``revision`` incremented by one."""
        text = (run_dir / "progress.md").read_text(encoding="utf-8")
        revision = pas.parse_tracker(text)["run"]["revision"]
        return swap(f"| revision | {revision} |",
                    f"| revision | {int(revision) + 1} |", text)

    def apply_with_one_retry(self, run_dir, transition_id: str) -> str:
        """A retry loop in the shape a controller actually writes one.

        ``TrackerWriteError`` promises nothing changed, so retrying is safe and
        the loop retries. Every other ``TrackerError`` — ``UpdateOutcomeUncertain``
        above all — is left to propagate, because retrying it blindly is the
        double-apply this whole distinction exists to prevent.
        """
        for _ in range(2):
            try:
                pas._replace_tracker(run_dir, self.bump_revision(run_dir),
                                     transition_id)
            except pas.TrackerWriteError:
                continue
            return "applied"
        return "gave-up"

    def revision_of(self, run_dir) -> str:
        return pas.parse_tracker(
            (run_dir / "progress.md").read_text(encoding="utf-8"))["run"]["revision"]

    def test_a_retrying_caller_retries_a_write_that_did_not_happen(self):
        """The 'nothing happened' half, proven through a caller rather than
        through an isinstance check: the transition is applied exactly once
        across a failed attempt and its retry, so revision moves 12 -> 13, not
        12 -> 14 and not 12 -> 12.
        """
        run_dir = make_run(self)
        real_sync_file = pas._sync_file
        faults = [OSError(errno.EIO, "simulated fsync failure"), None]

        def flaky(handle):
            problem = faults.pop(0) if faults else None
            if problem is not None:
                raise problem
            return real_sync_file(handle)

        with mock.patch.object(pas, "_sync_file", side_effect=flaky):
            self.assertEqual(self.apply_with_one_retry(run_dir, "transition-5"),
                             "applied")
        self.assertEqual(self.revision_of(run_dir), "13")

    def test_a_retrying_caller_does_not_retry_a_write_that_may_have_applied(self):
        """The 'may have applied' half, through the SAME caller. This is the
        assertion the class-hierarchy check cannot make: make
        ``UpdateOutcomeUncertain`` a subclass of ``TrackerWriteError`` and the
        loop above swallows it, retries a transition that already landed, and
        revision reaches 14 for one logical transition. Here the exception must
        reach the caller and the tracker must show exactly one application.
        """
        run_dir = make_run(self)
        with mock.patch.object(
                pas, "_sync_directory",
                side_effect=OSError(errno.EIO, "simulated dirsync failure")):
            with self.assertRaises(pas.UpdateOutcomeUncertain):
                self.apply_with_one_retry(run_dir, "transition-6")
        self.assertEqual(
            self.revision_of(run_dir), "13",
            "the transition was applied more than once: the retry loop treated "
            "'it may have applied' as 'nothing happened'")

    def test_a_successful_replace_leaves_no_temp_file_behind(self):
        run_dir = make_run(self)
        pas._replace_tracker(run_dir, valid_text(), "transition-4")
        self.assertEqual(
            sorted(p.name for p in run_dir.iterdir()), ["progress.md"],
            "the temp file is still there: it was copied over progress.md "
            "rather than renamed onto it, so the write was never atomic")

    def test_sync_file_pushes_the_buffered_write_out_to_the_operating_system(self):
        """The only case that runs the real ``_sync_file``: the two fault cases
        above replace it, so a body reduced to ``pass`` keeps them both green.
        Flush is asserted by reading the path while the handle is still open —
        under a missing flush the file is empty — and the fsync is asserted by
        the descriptor it is handed.
        """
        run_dir = empty_run(self)
        target = run_dir / "buffered.txt"
        synced = []
        real_fsync = os.fsync

        def spy(descriptor):
            synced.append(descriptor)
            return real_fsync(descriptor)

        with open(target, "w", encoding="utf-8") as handle:
            handle.write("x" * 8)
            self.assertEqual(
                target.read_text(encoding="utf-8"), "",
                "the write reached the file on its own; this case cannot tell "
                "a flush from no flush")
            with mock.patch.object(pas.os, "fsync", side_effect=spy):
                pas._sync_file(handle)
            self.assertEqual(target.read_text(encoding="utf-8"), "x" * 8)
            self.assertEqual(synced, [handle.fileno()])

    @unittest.skipIf(os.name == "nt", "the nt branch returns without syncing")
    def test_sync_directory_fsyncs_the_directory_itself(self):
        """A rename is not durable until the DIRECTORY entry is synced, and
        syncing only the file is the classic version of this bug. The early
        return belongs to ``os.name == "nt"`` alone: made unconditional it
        would drop durability here too, and every other case in this class
        would stay green because none of them survives a power cut.
        """
        run_dir = empty_run(self)
        synced = []
        real_fsync = os.fsync

        def spy(descriptor):
            synced.append(os.fstat(descriptor))
            return real_fsync(descriptor)

        with mock.patch.object(pas.os, "fsync", side_effect=spy):
            pas._sync_directory(run_dir)
        expected = os.stat(run_dir)
        self.assertEqual(
            [(status.st_dev, status.st_ino) for status in synced],
            [(expected.st_dev, expected.st_ino)],
            "_sync_directory did not fsync the run directory itself")

    @unittest.skipIf(os.name == "nt", "the nt branch opens no descriptor")
    def test_sync_directory_closes_the_descriptor_it_opened(self):
        """Every durable write in this run calls this function. A descriptor
        left open on each one exhausts the process's file-descriptor limit part
        way through a long run, and the failure surfaces somewhere else
        entirely as ``EMFILE``.
        """
        run_dir = empty_run(self)
        opened = []
        real_fsync = os.fsync

        def spy(descriptor):
            opened.append(descriptor)
            return real_fsync(descriptor)

        with mock.patch.object(pas.os, "fsync", side_effect=spy):
            pas._sync_directory(run_dir)
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError) as leaked:
            os.fstat(opened[0])
        self.assertEqual(
            leaked.exception.errno, errno.EBADF,
            "the directory descriptor is still open after _sync_directory "
            "returned; this leaks one descriptor per tracker write")

    def test_a_non_oserror_in_the_write_region_strands_no_temp_file(self):
        """The cleanup is about the temp file, the ``except`` is about what
        escapes, and they are not the same question.

        Text carrying a lone surrogate cannot be encoded, so ``handle.write``
        raises ``UnicodeEncodeError`` — a ``ValueError``, not an ``OSError``.
        With the unlink living in ``except OSError`` that exception walked
        straight out of the region and left a ``.progress.*.tmp`` behind, in
        the one function whose own comment says nothing else ever removes it.
        Two separate claims are asserted here: the temp file is gone, and the
        exception arrives as ITSELF. A programming fault laundered into
        ``TrackerWriteError`` would tell an autonomous retry loop that a bug is
        a transient write failure, and it would spin on it.
        """
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(UnicodeEncodeError) as caught:
            pas._replace_tracker(run_dir, valid_text() + "\ud800", "transition-7")
        self.assertNotIsInstance(
            caught.exception, pas.TrackerError,
            "an encoding fault was re-raised as a tracker write outcome; a "
            "retry loop will treat a bug as a transient failure")
        self.assertEqual(
            (run_dir / "progress.md").read_bytes(), before,
            "the tracker changed although the replacement never ran")
        self.assertEqual(
            sorted(p.name for p in run_dir.iterdir()), ["progress.md"],
            "a temp file survived a non-OSError and nothing will clean it up")

    def test_a_replacement_leaves_the_tracker_at_the_declared_mode(self):
        """``os.replace`` carries the TEMP file's mode onto the target, so
        whatever the temp file is created with becomes ``progress.md``'s mode
        on every write, forever. Under ``tempfile.mkstemp`` that was 0600 —
        chosen by the helper, not by anyone here — and each update quietly
        narrowed a document a human reads from 0644 down to owner-only.

        The umask is pinned for the duration so this asserts the module's
        declared mode rather than the machine's default, and restored in a
        ``finally`` so the setting does not leak into any later case.
        """
        run_dir = make_run(self)
        progress = run_dir / "progress.md"
        previous = os.umask(0o022)
        try:
            pas._replace_tracker(run_dir, valid_text(), "transition-8")
        finally:
            os.umask(previous)
        self.assertEqual(
            os.stat(progress).st_mode & 0o777, 0o644,
            "the atomic replace re-permissioned progress.md: the temp file's "
            "mode is the tracker's mode, so this is what the next change to "
            "the temp-file mechanism must not move without saying so")
        self.assertEqual(
            pas.TRACKER_MODE & 0o022, 0,
            "the tracker is group- or world-WRITABLE: a second local account "
            "can rewrite the state an autonomous controller obeys")

    def test_a_failure_before_the_handle_takes_over_closes_the_descriptor(self):
        """There is exactly one window in which the raw descriptor is this
        function's to close: between ``os.open`` returning it and ``os.fdopen``
        taking ownership. If ``os.fdopen`` raises in that window and the
        cleanup skips the close, every such failure leaks a descriptor, and the
        run dies much later and somewhere else as ``EMFILE``.

        The mirror-image mistake is closing it twice: past ``os.fdopen`` the
        handle owns it, so the cleanup is guarded by ``descriptor >= 0`` and
        that guard is reset the moment ownership moves.
        """
        run_dir = make_run(self)
        opened = []
        real_open = os.open

        def spy(path, flags, mode=0o777):
            descriptor = real_open(path, flags, mode)
            if str(path).endswith(".tmp"):
                opened.append(descriptor)
            return descriptor

        with mock.patch.object(pas.os, "open", side_effect=spy):
            with mock.patch.object(
                    pas.os, "fdopen",
                    side_effect=OSError(errno.ENOMEM, "simulated fdopen failure")):
                with self.assertRaises(pas.TrackerWriteError):
                    pas._replace_tracker(run_dir, valid_text(), "transition-10")
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError) as leaked:
            os.fstat(opened[0])
        self.assertEqual(
            leaked.exception.errno, errno.EBADF,
            "the temp file's descriptor is still open after the failure; this "
            "leaks one descriptor per failed tracker write")
        self.assertEqual(
            sorted(p.name for p in run_dir.iterdir()), ["progress.md"],
            "a temp file survived the failure and nothing will clean it up")

    def test_the_temp_file_is_created_exclusively_and_spares_a_foreign_one(self):
        """``O_CREAT | O_EXCL`` is the whole of the guarantee ``mkstemp`` was
        carrying, so it is asserted directly. The spy creates the exact name
        the module picked in the instant before the real open runs — the race
        itself, not an imitation of it — so the open must fail with ``EEXIST``
        rather than truncate what it found.

        The second half matters as much: the failed create must not unlink
        that file. The cleanup is driven by ``temporary``, which is assigned
        only after the open succeeds; hoist that assignment above the open and
        this call deletes a file it never created.
        """
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()
        foreign = "another writer is using this name\n"
        squatted = []
        real_open = os.open

        def squat(path, flags, mode=0o777):
            if str(path).endswith(".tmp") and not squatted:
                squatted.append(Path(path))
                Path(path).write_text(foreign, encoding="utf-8")
            return real_open(path, flags, mode)

        with mock.patch.object(pas.os, "open", side_effect=squat):
            with self.assertRaises(pas.TrackerWriteError) as caught:
                pas._replace_tracker(run_dir, valid_text(), "transition-9")
        self.assertEqual(len(squatted), 1)
        self.assertEqual(
            caught.exception.__cause__.errno, errno.EEXIST,
            "the create did not fail on an existing name, so O_EXCL is gone "
            "and a second writer's file was opened for writing")
        self.assertEqual(
            squatted[0].read_text(encoding="utf-8"), foreign,
            "the failed create clobbered or unlinked a file this call never "
            "created")
        self.assertEqual(
            (run_dir / "progress.md").read_bytes(), before,
            "the tracker changed although the temp file was never written")



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


#: A contended update must be refused on the caller's deadline, not on the
#: module's default. The bound sits between the two: comfortably above the
#: 0.25 s a case asks for, and well below ``DEFAULT_LOCK_TIMEOUT_S``, so an
#: implementation that drops ``timeout_s`` on the floor fails here instead of
#: passing forty times slower.
CONTENDED_UPDATE_BOUND_S = 5.0


def bump_dispatches(tracker: dict) -> dict:
    """The smallest real transition: one ``## Run`` counter, one cell."""
    tracker["run"]["agent_dispatch_count"] = str(
        int(tracker["run"]["agent_dispatch_count"]) + 1)
    return tracker


def setting_run_field(key: str, value: str):
    """A mutate that writes one ``## Run`` cell and returns the tracker."""
    def mutate(tracker: dict) -> dict:
        tracker["run"][key] = value
        return tracker
    return mutate


class Recorder:
    """A mutate that records the tracker it was handed, every time.

    "Was the callback invoked" is asserted directly rather than inferred from a
    revision that stayed put. A revision can stay put because the mutation was
    skipped, because the write failed, because the guard refused it, or because
    the caller rolled it back — four different stories with one symptom, and
    only one of them is the replay contract this class exists to pin.
    """

    def __init__(self, inner=bump_dispatches) -> None:
        self.calls: list[dict] = []
        self._inner = inner

    def __call__(self, tracker: dict) -> dict:
        self.calls.append(tracker)
        return self._inner(tracker)


def lock_wrapping(text: str):
    """The real run lock, with ``progress.md`` rewritten to ``text`` INSIDE it.

    This is how "re-read under the lock" is made falsifiable without a second
    process: the tracker on disk moves on in the window between the preflight
    read and the moment the lock is held, which is precisely the window a
    contending writer occupies. An implementation that mutates its pre-lock
    snapshot serialises nothing, and the only way to see that is to make the
    two reads disagree.

    The real lock is still taken, so the wrapper cannot pass by removing the
    mechanism it is testing.
    """
    real = pas._exclusive_lock

    @contextlib.contextmanager
    def advancing_lock(run_dir, *, timeout_s=pas.DEFAULT_LOCK_TIMEOUT_S):
        with real(run_dir, timeout_s=timeout_s):
            (Path(run_dir) / "progress.md").write_text(text, encoding="utf-8")
            yield

    return mock.patch.object(pas, "_exclusive_lock", advancing_lock)


class LockedUpdateTests(unittest.TestCase):
    """``locked_tracker_update`` — the only way state ever changes.

    Everything above this class is defeated by two writers interleaving a
    read-modify-write on ``progress.md``: both halves of the interleaving are
    individually well-formed, every validator in this file passes on each, and
    the loser's transition simply disappears. The lock existed before this
    class and had no caller, which made "only the controller writes
    progress.md" a convention rather than a mechanism. These cases are what
    make it a mechanism.
    """

    def tracker_bytes(self, run_dir: Path) -> bytes:
        return (run_dir / "progress.md").read_bytes()

    def test_a_successful_update_bumps_revision_and_records_the_transition(self):
        run_dir = make_run(self)
        result = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                           mutate=bump_dispatches)
        self.assertEqual(result["run"]["revision"], "13")
        self.assertEqual(result["run"]["last_transition"], "dispatch-1")
        self.assertEqual(result["run"]["agent_dispatch_count"], "49")
        self.assertEqual(pas.validate_run(run_dir), result)

    def test_an_update_takes_the_run_lock_and_strands_no_temp_file(self):
        """The directory listing after one update, stated deliberately.

        ``.pipeline-auto.lock`` is created by the lock and never unlinked, by
        design — removing it races a second acquirer onto a second inode at one
        path. Every directory-content assertion written before this task
        expected ``["progress.md"]`` alone and was correct, because nothing
        called the lock. This is the one that records the change rather than
        loosening the others: the listing is pinned exactly, so a stranded
        ``.progress.*.tmp`` still fails here.
        """
        run_dir = make_run(self)
        pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                  mutate=bump_dispatches)
        self.assertEqual(
            sorted(path.name for path in run_dir.iterdir()),
            [pas.LOCK_FILENAME, "progress.md"],
            "either the update never took the run lock, or it left a temp file")

    def test_an_update_is_refused_while_another_process_holds_the_run_lock(self):
        """The named fault of this whole task: a transaction with no lock.

        Every case in this class except this one passes against an
        implementation that deletes the ``with _exclusive_lock(...)`` line —
        they run one at a time in one interpreter, which is exactly the
        condition a lock is not needed for. So the holder is a separate spawned
        interpreter, the refusal is asserted against it, and the holder is
        checked to be still alive afterwards so the refusal is evidence of
        contention rather than of a holder that had already finished.

        ``mutate`` is asserted un-called: a lock taken AFTER the caller's
        mutation has already run serialises the write and not the
        read-modify-write, which is the interleaving that loses a transition.

        The elapsed bound pins that ``timeout_s`` reached the lock. Dropped, the
        refusal still arrives — ten seconds later, on the module default — and
        every other assertion here is satisfied.
        """
        run_dir = make_run(self)
        before = self.tracker_bytes(run_dir)
        holder, release = start_holder(self, run_dir)
        self.assertNotEqual(
            int((run_dir / HOLDER_PID_FILE).read_text(encoding="utf-8")), os.getpid(),
            "the lock was taken inside this interpreter, so the refusal below "
            "is not evidence of cross-process contention")
        mutate = Recorder()
        started = time.monotonic()
        with self.assertRaises(pas.LockBusyError):
            pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                      mutate=mutate, timeout_s=0.25)
        elapsed = time.monotonic() - started
        self.assertTrue(
            holder.is_alive(),
            "the holder exited before the refusal, so the refusal is not "
            "evidence of contention")
        self.assertEqual(
            mutate.calls, [],
            "the caller's mutation ran before the lock was held; the lock then "
            "serialises the write alone and the read-modify-write still races")
        self.assertLess(
            elapsed, CONTENDED_UPDATE_BOUND_S,
            "timeout_s never reached the lock: the refusal waited out the "
            "module default instead of the caller's deadline")
        self.assertEqual(self.tracker_bytes(run_dir), before)
        release.set()
        holder.join(HOLDER_WAIT_SECONDS)
        self.assertEqual(
            holder.exitcode, 0,
            "the holder did not exit cleanly, so what it did with the lock is "
            "unknown")
        result = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                           mutate=bump_dispatches)
        self.assertEqual(
            result["run"]["revision"], "13",
            "the same directory could not be updated once the lock was free, "
            "so the refusal above was never contention")

    def test_the_tracker_is_re_read_under_the_lock_not_before_it(self):
        """Anything read before the lock is stale by definition.

        The preflight ``validate_run`` runs unlocked on purpose — it is what
        stops a foreign directory before a lock file is created in it. Reusing
        its result as the state to mutate is the mistake: the whole point of
        the lock is that another writer may land between that read and the
        acquisition, and a transaction that applies to the pre-lock snapshot
        overwrites whatever landed. It serialises nothing while looking exactly
        like it does.

        Here the tracker moves from revision 12 to 20 and from 48 dispatches to
        60 inside that window. Under the fault the result reads 13 and 49.
        """
        run_dir = make_run(self)
        moved_on = swap(
            "| revision | 12 |", "| revision | 20 |",
            swap("| agent_dispatch_count | 48 |", "| agent_dispatch_count | 60 |"))
        with lock_wrapping(moved_on):
            result = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                               mutate=bump_dispatches)
        self.assertEqual(
            result["run"]["revision"], "21",
            "the revision was derived from the pre-lock read, so a transition "
            "that landed while this one waited has just been overwritten")
        self.assertEqual(result["run"]["agent_dispatch_count"], "61")
        self.assertEqual(pas.validate_run(run_dir), result)

    def test_a_replay_is_judged_against_the_state_read_under_the_lock(self):
        """The replay check is only as fresh as the read it consults.

        A resume races its own predecessor: the transition it is re-issuing may
        land, from the process it is resuming, in the window between this
        caller's preflight read and its acquisition. Checking the pre-lock
        snapshot's ``last_transition`` then sees the OLD value, applies a second
        time, and doubles exactly what the replay contract exists to protect.
        """
        run_dir = make_run(self)
        already_applied = swap(
            "| last_transition | ratchet-P02-accumulated-surface |",
            "| last_transition | dispatch-1 |")
        mutate = Recorder()
        with lock_wrapping(already_applied):
            result = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                               mutate=mutate)
        self.assertEqual(
            mutate.calls, [],
            "the replay check consulted the pre-lock snapshot, so a transition "
            "that had already landed was applied a second time")
        self.assertEqual(result["run"]["revision"], "12")
        self.assertEqual(
            (run_dir / "progress.md").read_text(encoding="utf-8"), already_applied,
            "a replay wrote to the tracker")

    def test_a_replayed_transition_returns_current_state_without_mutating(self):
        """Every resume path re-issues the transition it was interrupted in. If
        replay applies a second time, a resumed run silently doubles whatever
        that transition recorded."""
        run_dir = make_run(self)
        pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                  mutate=bump_dispatches)
        after_first = self.tracker_bytes(run_dir)
        mutate = Recorder()
        replayed = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                             mutate=mutate)
        self.assertEqual(
            mutate.calls, [],
            "the mutate callback ran on a replay; a callback with any effect "
            "of its own has now run twice for one transition")
        self.assertEqual(self.tracker_bytes(run_dir), after_first)
        self.assertEqual(replayed["run"]["revision"], "13")
        self.assertEqual(replayed["run"]["agent_dispatch_count"], "49")

    def test_a_distinct_transition_after_one_applies_is_not_treated_as_a_replay(self):
        """The positive control the case above needs. An implementation that
        refuses every second transition is idempotent in the most useless
        possible way, and nothing else in this class catches it."""
        run_dir = make_run(self)
        pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                  mutate=bump_dispatches)
        second = pas.locked_tracker_update(run_dir, transition_id="dispatch-2",
                                           mutate=bump_dispatches)
        self.assertEqual(second["run"]["revision"], "14")
        self.assertEqual(second["run"]["agent_dispatch_count"], "50")
        self.assertEqual(second["run"]["last_transition"], "dispatch-2")

    def test_the_reparse_canary_rejects_a_mutation_that_renders_invalid_state(self):
        run_dir = make_run(self)
        before = self.tracker_bytes(run_dir)

        def regress_stage(tracker):
            tracker["stages"][0]["stage_state"] = "pending"
            return tracker

        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(run_dir, transition_id="regress-1",
                                      mutate=regress_stage)
        self.assertEqual(self.tracker_bytes(run_dir), before)

    def test_the_canary_reparses_the_render_rather_than_re_checking_the_dict(self):
        """The canary is a ROUND TRIP, and only a round trip catches this.

        ``a | b`` in a free cell is a perfectly good Python string: every
        semantic validator in this module accepts the dict that holds it. It is
        the RENDER that is unreadable — the cell becomes a column separator and
        the row comes back one cell too wide. Re-running the validators on the
        proposed dict, which looks like the same check and is cheaper, writes
        this tracker to disk and the corruption is discovered on the next load,
        by a different process, with nothing left to attribute it to.
        """
        run_dir = make_run(self)
        before = self.tracker_bytes(run_dir)

        def smuggle_a_separator(tracker):
            tracker["gates"][2]["findings"] = "a | b"
            return tracker

        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(run_dir, transition_id="smuggle-1",
                                      mutate=smuggle_a_separator)
        self.assertEqual(self.tracker_bytes(run_dir), before)

    def test_the_returned_tracker_is_the_reparsed_one_not_the_in_memory_dict(self):
        """Callers only ever see state that survived a round trip.

        A cell handed in with surrounding whitespace renders wide and parses
        back trimmed, so the dict written and the dict proposed are not the
        same dict. Returning the in-memory one hands the caller a value that is
        not what any later reader of this tracker will see — and a controller
        that branches on it branches on a value that exists nowhere on disk.
        """
        run_dir = make_run(self)
        result = pas.locked_tracker_update(
            run_dir, transition_id="pad-1",
            mutate=setting_run_field("agent_dispatch_count", " 60 "))
        self.assertEqual(result["run"]["agent_dispatch_count"], "60")
        self.assertEqual(pas.validate_run(run_dir), result)

    def test_a_transition_cannot_change_run_identity(self):
        """Also the case that kills a shallow copy.

        ``mutate`` is handed a DEEP copy. Under a shallow one, ``proposed["run"]``
        and ``current["run"]`` are one dict, so a mutation to ``run_id`` changes
        both, the comparison below finds them equal, and the rebranded tracker
        is written. The guard would still be there, still be executed, and
        catch nothing.
        """
        run_dir = make_run(self)
        before = self.tracker_bytes(run_dir)
        for key, value in (("run_id", "2026-09-14-somebody-elses-run"),
                           ("schema", "pipeline-auto/v2"),
                           ("base_commit", "1" * 40),
                           ("target_branch", "main")):
            with self.subTest(key=key):
                with self.assertRaises(pas.TrackerValidationError) as caught:
                    pas.locked_tracker_update(run_dir, transition_id="rebrand-1",
                                              mutate=setting_run_field(key, value))
                self.assertIn(key, str(caught.exception))
                self.assertEqual(self.tracker_bytes(run_dir), before)

    def test_the_intent_brief_is_immutable_once_stage_03_closes(self):
        """A contradicting finding escalates and a human amends the brief; no
        transition rewrites it in place. Without the guard a later stage
        substitutes a different brief and every downstream artifact still looks
        consistent with the one it now cites."""
        run_dir = make_run(self)
        before = self.tracker_bytes(run_dir)

        def rewrite_brief(tracker):
            brief = next(row for row in tracker["intent"] if row["id"] == "brief")
            brief["result"] = "scratch/intent-brief-v2.md"
            return tracker

        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(run_dir, transition_id="brief-2",
                                      mutate=rewrite_brief)
        self.assertEqual(self.tracker_bytes(run_dir), before)

    def test_the_brief_is_still_writable_while_it_is_unfrozen(self):
        """The positive control. A guard that refused every ``## Intent`` edit
        would also pass the case above, while making stages 01-03 unable to
        record the readings and the reconciliation they exist to produce."""
        run_dir = make_run(self, with_row("intent", "brief", {"state": "published"}))

        def publish_brief(tracker):
            brief = next(row for row in tracker["intent"] if row["id"] == "brief")
            brief["result"] = "scratch/intent-brief-v2.md"
            return tracker

        result = pas.locked_tracker_update(run_dir, transition_id="brief-1",
                                           mutate=publish_brief)
        self.assertEqual(
            next(row for row in result["intent"] if row["id"] == "brief")["result"],
            "scratch/intent-brief-v2.md")

    def test_a_foreign_tracker_is_refused_before_mutate_is_ever_called(self):
        """And before a lock file is created in somebody else's directory.

        This is the whole reason the preflight validation is outside the lock.
        ``superb:pipeline`` runs in directories that look exactly like this one;
        dropping ``.pipeline-auto.lock`` into a live run of the other skill is a
        write, in a read-only stop that promises none.
        """
        foreign = (FOREIGN_FIXTURES / "valid-v2-progress.md").read_bytes()
        run_dir = make_run(self, foreign.decode("utf-8"))
        mutate = Recorder()
        with self.assertRaises(pas.ForeignSchemaError):
            pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                      mutate=mutate)
        self.assertEqual(mutate.calls, [])
        self.assertEqual(self.tracker_bytes(run_dir), foreign)
        self.assertEqual(
            sorted(path.name for path in run_dir.iterdir()), ["progress.md"],
            "a lock file was created inside a directory this skill does not own")

    def test_mutate_must_return_a_tracker_dict(self):
        """``None`` is the common shape of this bug — a mutate that edits in
        place and forgets to return — but it is not the only one, and the other
        two reach further into the transaction before anything notices."""
        run_dir = make_run(self)
        before = self.tracker_bytes(run_dir)
        for description, returns in (
            ("None, from a mutate that edited in place", lambda tracker: None),
            ("a list of sections", lambda tracker: list(tracker.items())),
            ("a dict with ## Intent dropped",
             lambda tracker: {key: value for key, value in tracker.items()
                              if key != "intent"}),
        ):
            with self.subTest(returns=description):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.locked_tracker_update(run_dir, transition_id="bad-1",
                                              mutate=returns)
                self.assertEqual(self.tracker_bytes(run_dir), before)

    def test_an_invalid_transition_identity_is_rejected(self):
        """Before the lock and before ``mutate``. The id is the replay key: an
        id carrying a space is one a later resume cannot reproduce exactly, so
        its replay would not be recognised as one."""
        run_dir = make_run(self)
        before = self.tracker_bytes(run_dir)
        mutate = Recorder()
        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(run_dir, transition_id="not a token",
                                      mutate=mutate)
        self.assertEqual(mutate.calls, [])
        self.assertEqual(self.tracker_bytes(run_dir), before)
        self.assertEqual(
            sorted(path.name for path in run_dir.iterdir()), ["progress.md"],
            "a malformed transition id still created a lock file")

    def test_the_transition_arguments_are_keyword_only(self):
        """Every call site in the master plan names them. A positional
        signature accepts ``(run_dir, mutate, transition_id)`` in the wrong
        order just as happily, and the tracker then records the mutate
        function's repr as the transition that ran."""
        run_dir = make_run(self)
        with self.assertRaises(TypeError):
            pas.locked_tracker_update(run_dir, "dispatch-1", bump_dispatches)

    def test_a_mutate_that_raises_partway_changes_nothing_on_disk(self):
        """mutate gets a deep copy, so a worker that dies halfway through a
        transition cannot leave a half-applied tracker behind — and the lock is
        released on that path, which the update afterwards is what proves."""
        run_dir = make_run(self)
        before = self.tracker_bytes(run_dir)

        def half_apply(tracker):
            tracker["run"]["agent_dispatch_count"] = "999"
            raise RuntimeError("worker died mid-transition")

        with self.assertRaises(RuntimeError):
            pas.locked_tracker_update(run_dir, transition_id="half-1",
                                      mutate=half_apply)
        self.assertEqual(self.tracker_bytes(run_dir), before)
        self.assertEqual(pas.validate_run(run_dir)["run"]["agent_dispatch_count"], "48")
        recovered = pas.locked_tracker_update(run_dir, transition_id="half-2",
                                              mutate=bump_dispatches)
        self.assertEqual(
            recovered["run"]["agent_dispatch_count"], "49",
            "the run lock was never released, so one exception from a caller's "
            "mutate wedges the whole run")

    def test_a_pre_replace_failure_reaches_the_caller_as_nothing_happened(self):
        """The three write outcomes must stay distinguishable THROUGH this
        function. Swallowing ``TrackerWriteError`` here — or re-raising it as
        the uncertain one — makes a retrying controller reconcile a transition
        that provably did not happen, or, the other way round, blindly retry
        one that did."""
        run_dir = make_run(self)
        before = self.tracker_bytes(run_dir)
        with mock.patch.object(pas, "_sync_file",
                               side_effect=OSError(errno.EIO, "simulated fsync")):
            with self.assertRaises(pas.TrackerWriteError) as caught:
                pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                          mutate=bump_dispatches)
        self.assertNotIsInstance(caught.exception, pas.UpdateOutcomeUncertain)
        self.assertEqual(self.tracker_bytes(run_dir), before)
        retried = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                            mutate=bump_dispatches)
        self.assertEqual(
            retried["run"]["agent_dispatch_count"], "49",
            "either the lock outlived the failure or the retry double-applied")

    def test_a_post_replace_failure_is_uncertain_and_its_replay_settles_it(self):
        """The compaction story, end to end.

        The replacement landed; only its durability is in doubt, and the
        exception says so. The caller cannot know which, so it re-issues the
        same transition — and the replay check, reading what is actually on
        disk, tells it the transition is already recorded and refuses to apply
        it again. Report this as ``TrackerWriteError`` instead and the caller
        is told nothing happened; the replay check is then the only thing
        between it and a doubled dispatch count.
        """
        run_dir = make_run(self)
        with mock.patch.object(pas, "_sync_directory",
                               side_effect=OSError(errno.EIO, "simulated dirsync")):
            with self.assertRaises(pas.UpdateOutcomeUncertain):
                pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                          mutate=bump_dispatches)
        self.assertEqual(pas.validate_run(run_dir)["run"]["agent_dispatch_count"], "49")
        mutate = Recorder()
        settled = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                            mutate=mutate)
        self.assertEqual(mutate.calls, [])
        self.assertEqual(settled["run"]["agent_dispatch_count"], "49")
        self.assertEqual(settled["run"]["revision"], "13")


#: The arguments a run is born with, in one place so a case that varies one of
#: them varies exactly one of them. Every value here is real: the base commit is
#: this repository's own, and the branch is the shape a run actually targets.
NEW_RUN = {
    "run_id": "2026-09-14-example",
    "base_commit": "c8bddd610119f52b54bf077d284c7f5d8362ae77",
    "target_branch": "feat/example",
    "worker_limit": 6,
}


def unborn_run(case: unittest.TestCase) -> Path:
    """A path a run directory does NOT exist at yet. Removed when the case ends.

    ``make_run`` and ``empty_run`` both create the directory, and neither can
    stand in here: initialization has to create the directory it writes into,
    and a case handed an existing one would never exercise that.
    """
    root = Path(tempfile.mkdtemp(prefix="pipeline-auto-init-"))
    case.addCleanup(shutil.rmtree, root, ignore_errors=True)
    return root / "run"


def new_run(case: unittest.TestCase, **overrides) -> tuple[Path, dict]:
    run_dir = unborn_run(case)
    return run_dir, pas.initialize_run(run_dir, **{**NEW_RUN, **overrides})


class InitializeRunTests(unittest.TestCase):
    """The first write of a run — the one write that does not go through the lock.

    ``locked_tracker_update`` is the sole writer of an EXISTING tracker, and it
    cannot create one: every step of it reads and re-reads a tracker that has to
    be there already. Creation is the other operation, and it is bounded by a
    different mechanism — ``os.link``, which fails rather than replaces, so two
    controllers racing to start a run in one directory produce one winner and
    one refusal instead of one silent clobber.
    """

    def refusal(self, error, **overrides):
        """Initialize with one argument changed, and require a read-only stop.

        "Raises" is half the contract. The other half is that the directory is
        untouched: an argument check that runs AFTER the write leaves a tracker
        on disk for a run the caller was just told it could not start.
        """
        run_dir = unborn_run(self)
        with self.assertRaises(error) as caught:
            pas.initialize_run(run_dir, **{**NEW_RUN, **overrides})
        self.assertFalse(
            (run_dir / "progress.md").exists(),
            "a refused initialization still left a tracker on disk")
        return caught.exception

    def test_a_new_run_opens_stage_01_and_leaves_the_other_eleven_pending(self):
        """Twelve pending stages is the shape that reported an untouched run as
        ``complete``: the run would end at stage 00 with every artifact
        unwritten and nothing erroring. ``derive_next_action`` now raises on it
        instead, so a fresh tracker that opens no stage cannot be acted on at
        all — which makes this the one assertion initialization cannot omit.
        """
        _, tracker = new_run(self)
        self.assertEqual([row["stage_state"] for row in tracker["stages"]],
                         ["active"] + ["pending"] * 11)
        self.assertEqual([row["next_action"] for row in tracker["stages"][1:]],
                         ["-"] * 11)
        opening = tracker["stages"][0]["next_action"]
        self.assertNotEqual(opening, "-")
        self.assertEqual(pas.derive_next_action(tracker), opening)
        self.assertNotEqual(pas.derive_next_action(tracker), "complete")

    def test_a_new_run_starts_at_revision_zero_with_every_table_empty(self):
        _, tracker = new_run(self)
        self.assertEqual(tracker["run"]["revision"], "0")
        self.assertEqual(tracker["run"]["last_transition"], "initialized")
        self.assertEqual(tracker["run"]["agent_dispatch_count"], "0")
        self.assertEqual(tracker["run"]["schema"], pas.SCHEMA)
        for key in ("intent", "questions", "quorum", "escalations", "tasks",
                    "task_review", "fix_rounds", "phases", "gates"):
            self.assertEqual(tracker[key], [], key)

    def test_the_first_transition_of_a_new_run_lands_at_revision_one(self):
        """What makes ``revision`` 0 mean something rather than look tidy.

        ``revision`` counts durable transitions, and ``locked_tracker_update``
        derives the next one by adding to what it reads. A run born at 1 claims
        a transition that never happened and every later revision is off by one
        against the decisions and findings that cite it.
        """
        run_dir, _ = new_run(self)
        after = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                          mutate=bump_dispatches)
        self.assertEqual(after["run"]["revision"], "1")
        self.assertEqual(after["run"]["agent_dispatch_count"], "1")

    def test_run_artifacts_are_addressed_under_the_run_id_convention(self):
        """The spec puts a run's artifacts under
        ``docs/superpowers/runs/<run-id>/``. Two runs sharing an artifact path
        append into one another's audit trail, and the decision record is
        append-only, so nothing later can separate them again.
        """
        _, tracker = new_run(self)
        base = "docs/superpowers/runs/2026-09-14-example"
        self.assertEqual(tracker["run"]["decisions"], f"{base}/decisions.md")
        self.assertEqual(tracker["run"]["findings"], f"{base}/findings.md")
        self.assertEqual(tracker["run"]["completeness_proposals"],
                         f"{base}/completeness-proposals.md")

    def test_an_artifact_a_new_run_has_not_written_is_absent_not_predicted(self):
        """``spec``, ``master_plan`` and ``phase_plans`` are produced by stages
        05, 06 and 07. Pre-filling the paths they will eventually take makes the
        tracker name three files that do not exist, and a resuming controller
        reading a cell cannot tell a promise from a product — it would skip the
        stage that was supposed to write it.
        """
        _, tracker = new_run(self)
        for key in ("spec", "master_plan", "phase_plans"):
            self.assertEqual(tracker["run"][key], "-", key)

    def test_run_identity_is_recorded_exactly_as_it_was_given(self):
        """These four cells are the ones no transition may ever change, so a
        value mistyped here is not correctable later by any legal write — the
        run has to be thrown away and started again.
        """
        _, tracker = new_run(self)
        self.assertEqual(tracker["run"]["run_id"], NEW_RUN["run_id"])
        self.assertEqual(tracker["run"]["base_commit"], NEW_RUN["base_commit"])
        self.assertEqual(tracker["run"]["target_branch"], NEW_RUN["target_branch"])
        self.assertEqual(tracker["run"]["worker_limit"], "6")

    def test_the_bytes_on_disk_are_the_canonical_render_of_what_is_returned(self):
        """Initialization returns state read back THROUGH the parser, never the
        dict it rendered. A caller acting on the in-memory dict acts on
        something no later read reproduces, and the first byte-level
        disagreement between the two surfaces as a foreign-schema stop halfway
        through the run.
        """
        run_dir, tracker = new_run(self)
        text = (run_dir / "progress.md").read_text(encoding="utf-8")
        self.assertEqual(text, pas.render_tracker(tracker))
        self.assertEqual(pas.validate_run(run_dir), tracker)

    def test_a_run_never_targets_main_or_master(self):
        """Success leaves a clean, committed feature branch and nothing is
        merged or pushed. A run whose target IS the default branch commits
        straight onto it, and ``target_branch`` is an identity cell no later
        transition can correct.
        """
        for branch in ("main", "master"):
            with self.subTest(branch=branch):
                self.refusal(pas.TrackerValidationError, target_branch=branch)

    def test_a_target_branch_that_is_not_one_token_is_rejected(self):
        """A ``|`` in a branch name renders as a cell boundary and a space
        renders as a two-word cell. Both reach the parser as a malformed table,
        so the message a human gets describes the table instead of the argument
        that was actually wrong — and the canary catches it one layer too late
        to say what to fix.
        """
        for branch in ("feat/a|b", "feat/a b", "", "-"):
            with self.subTest(target_branch=branch):
                self.refusal(pas.TrackerValidationError, target_branch=branch)

    def test_a_base_commit_that_is_not_a_full_object_name_is_rejected(self):
        """``base_commit`` is one end of every range proof the run makes. An
        abbreviation names a different object as the repository grows and a
        symbolic name resolves somewhere else tomorrow: neither is an end a
        proof can be made between, and both read like one.
        """
        for value in ("c8bddd61", "HEAD", "HEAD~1", "feat/example", "",
                      "C8BDDD610119F52B54BF077D284C7F5D8362AE77",
                      "c8bddd610119f52b54bf077d284c7f5d8362ae7z",
                      "c8bddd610119f52b54bf077d284c7f5d8362ae771"):
            with self.subTest(base_commit=value):
                self.refusal(pas.TrackerValidationError, base_commit=value)

    def test_a_worker_limit_below_one_is_rejected(self):
        """A run with no workers dispatches nothing, completes nothing, and
        reports itself healthy the whole time.
        """
        for limit in (0, -1):
            with self.subTest(worker_limit=limit):
                self.refusal(pas.TrackerValidationError, worker_limit=limit)

    def test_a_worker_limit_that_is_not_an_integer_stays_inside_the_family(self):
        """``int('six')`` raises ValueError and ``int(6.5)`` silently truncates.
        The first escapes this module's exception family, so a caller branching
        on ``TrackerError`` never sees the stop; the second records a limit the
        caller never asked for, in a cell nothing later re-derives.
        """
        for limit in ("6", 6.5, None):
            with self.subTest(worker_limit=limit):
                self.refusal(pas.TrackerValidationError, worker_limit=limit)

    def test_a_boolean_worker_limit_is_rejected_like_any_other_non_integer(self):
        """``bool`` subclasses ``int``, so ``isinstance(x, int)`` alone admits
        ``True`` — and ``True >= 1`` holds, so the cell is written as the
        string ``'True'``. ``## Run`` has no semantic validator: this argument
        is checked here and nowhere else, so that string is never caught again
        by whatever reads ``worker_limit`` to decide how many brain slots to
        reserve, and the guard's own message calls ``True`` a positive integer.

        ``False`` is pinned deliberately rather than left to ``< 1``. It is
        refused today for the wrong reason — by the comparison, not by the
        type — and a rule that only one of the two values obeys is one rewrite
        of the bound away from not holding at all.

        The diagnostic must be the one every other non-integer gets, so the
        message is compared against the string case rather than merely searched
        for a phrase: a bespoke sentence for booleans would tell a caller this
        is a special case when it is the ordinary one.
        """
        ordinary = str(self.refusal(pas.TrackerValidationError,
                                    worker_limit="6"))
        for limit in (True, False):
            with self.subTest(worker_limit=limit):
                message = str(self.refusal(pas.TrackerValidationError,
                                           worker_limit=limit))
                head, found, tail = message.partition(repr(limit))
                self.assertEqual(head, "worker_limit ")
                self.assertTrue(found, message)
                self.assertEqual(tail, ordinary.partition(repr("6"))[2])

    def test_a_worker_limit_below_four_is_legal_and_serialises(self):
        """``worker_limit >= 4`` is required for CONCURRENCY, not for legality:
        below it tasks serialise so the three brain slots stay free. Refusing it
        here would make a single-worker run impossible to start at all, which is
        a different rule from the one the spec states.
        """
        _, tracker = new_run(self, worker_limit=2)
        self.assertEqual(tracker["run"]["worker_limit"], "2")

    def test_a_run_id_that_escapes_its_own_run_directory_is_rejected(self):
        """The run id is interpolated into three artifact paths. A separator or
        a leading dot in it addresses ``decisions.md`` outside the run directory
        — over another run's audit trail, or over a repository file — and all
        three cells still read as well-formed paths afterwards.
        """
        for value in ("../2026-09-14-other", "2026/09/14", "", ".hidden",
                      "a b", "-leading", "run|id"):
            with self.subTest(run_id=value):
                self.refusal(pas.TrackerValidationError, run_id=value)

    def test_initializing_over_an_existing_tracker_is_refused_and_changes_nothing(self):
        """A second controller starting a run in an occupied directory must
        LOSE, not clobber. ``os.replace`` would overwrite the first controller's
        tracker, and that controller would carry on against state it still
        believes it wrote — the one failure no later read can detect, because
        the replacement is itself a valid tracker.
        """
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(pas.TrackerWriteError) as caught:
            pas.initialize_run(run_dir, **NEW_RUN)
        self.assertNotIsInstance(caught.exception, pas.UpdateOutcomeUncertain)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)
        self.assertIn("resume the existing run", str(caught.exception).lower(),
                      "the refusal does not say what to do instead")

    def test_a_second_controller_starting_a_different_run_loses(self):
        run_dir, _ = new_run(self)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(pas.TrackerWriteError):
            pas.initialize_run(run_dir, **{**NEW_RUN, "run_id": "2026-09-14-other"})
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)
        self.assertEqual(pas.validate_run(run_dir)["run"]["run_id"],
                         NEW_RUN["run_id"])

    def test_re_initializing_the_identical_untouched_run_is_inert(self):
        """The no-clobber rule is about CONTENT, not about the call count. A
        controller that crashed between writing its tracker and recording that
        it had one must find its run on the retry, not a refusal it has no way
        to act on. Identical bytes are the same fact written twice, and the
        file is not rewritten to say so.
        """
        run_dir, first = new_run(self)
        inode = (run_dir / "progress.md").stat().st_ino
        second = pas.initialize_run(run_dir, **NEW_RUN)
        self.assertEqual(second, first)
        self.assertEqual((run_dir / "progress.md").stat().st_ino, inode)

    def test_a_tracker_that_cannot_be_read_back_never_reaches_the_disk(self):
        """The canary, and what it is worth.

        Every argument is checked before the render, so a render this module
        cannot read back can only come from a bug in this module — which is
        exactly the case the canary is for. Remove it and the bad bytes land,
        and the read-back at the end reports the same fault having already left
        an unparseable tracker in the directory: still a stop, no longer a
        READ-ONLY one, and the next controller to look finds a run it can
        neither start nor resume. The exception is the same either way, so the
        assertion that discriminates is the one about the disk.
        """
        run_dir = unborn_run(self)
        with mock.patch.object(pas, "render_tracker",
                               return_value=f"{pas.MARKER}\nnot a tracker\n"):
            with self.assertRaises(pas.TrackerValidationError):
                pas.initialize_run(run_dir, **NEW_RUN)
        self.assertFalse(
            (run_dir / "progress.md").exists(),
            "a tracker that failed its own canary was written anyway")

    def test_the_run_directory_holds_the_tracker_and_then_its_lock(self):
        """Two facts one enumeration proves.

        Initialization takes no lock: a directory that does not exist yet cannot
        contend with anything, and creating a lock file to find out whether a
        directory is a run is exactly what ``locked_tracker_update`` refuses to
        do inside somebody else's directory. So a fresh run holds one file.

        The first real transition creates ``.pipeline-auto.lock`` and never
        removes it — unlinking it races a second acquirer onto a lock file
        nobody else can still see. Any later assertion that enumerates a run
        directory has to expect it, and one that does not fails for a reason
        unrelated to what it is testing.
        """
        run_dir, _ = new_run(self)
        self.assertEqual(sorted(path.name for path in run_dir.iterdir()),
                         ["progress.md"])
        pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                  mutate=bump_dispatches)
        self.assertEqual(sorted(path.name for path in run_dir.iterdir()),
                         sorted(["progress.md", pas.LOCK_FILENAME]))


class AnnotatedPathIsNotCoercedTests(unittest.TestCase):
    """An annotation in this module tells the truth about what it accepts.

    Three tasks in a row landed the same shape: a parameter annotated ``Path``
    whose body passes it back through ``Path()``. In ``validate_run`` and in
    ``initialize_run`` the rebinding was a defect as well as a contradiction.
    In ``publish_immutable`` it was idempotent and harmless — and still a lie,
    because a reader who trusts the signature is told the argument must already
    be a ``Path`` while the body says it need not be. A third instance in three
    tasks is a pattern, so it is swept rather than patched one site at a time.

    Deliberately unannotated parameters are untouched by this.
    ``_exclusive_lock`` and ``_replace_tracker`` both take ``run_dir`` with no
    annotation and normalise it on purpose: they promise nothing, so they
    contradict nothing.
    """

    def coerced_path_parameters(self, source: str) -> list[str]:
        """``function:parameter`` for every ``Path``-annotated parameter that
        its own function passes back through ``Path()``."""
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            spec = node.args
            annotated = {
                arg.arg
                for arg in spec.posonlyargs + spec.args + spec.kwonlyargs
                if arg.annotation is not None
                and "Path" in ast.unparse(arg.annotation)}
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "Path"
                        and inner.args
                        and isinstance(inner.args[0], ast.Name)
                        and inner.args[0].id in annotated):
                    found.append(f"{node.name}:{inner.args[0].id}")
        return sorted(found)

    def test_no_path_annotated_parameter_is_coerced_in_its_own_body(self):
        self.assertEqual(
            self.coerced_path_parameters(module_source()), [],
            "a parameter annotated Path is passed back through Path() in its "
            "own body; drop the coercion, or widen the annotation to whatever "
            "the function really accepts")

    def test_the_sweep_names_a_reintroduced_coercion(self):
        """A test of the test. The clean result above is a statement about the
        module only if the detector would have said so; so the pattern is
        spliced back into a real signature and must be named.
        """
        source = module_source()
        mutant = with_statement_in(source, "publish_immutable",
                                   "path = Path(path)")
        self.assertNotEqual(mutant, source)
        self.assertEqual(self.coerced_path_parameters(mutant),
                         ["publish_immutable:path"])
        self.assertEqual(self.coerced_path_parameters(source), [])


class PublishImmutableTests(unittest.TestCase):
    """Write-once artifacts, and the digest that binds a row to one.

    Everything the run later reasons about — a brain's response, a worker's
    result, a review package — is bound into the tracker by a digest rather than
    carried in anyone's context. A file that can be rewritten under a digest
    already recorded makes every one of those bindings a claim about bytes that
    are no longer there, and nothing in the tracker can notice.
    """

    def scratch(self, name: str) -> Path:
        """A path inside a run's ``scratch/``, which does not exist yet."""
        return make_run(self) / "scratch" / name

    def test_publishing_returns_the_sha256_of_the_bytes_written(self):
        """The digest, not the path. A publisher returning where it put the
        file hands the caller something that stays true when the contents
        change, which is the one thing the return value exists to prevent.
        """
        path = self.scratch("q1-brain-1.json")
        digest = pas.publish_immutable(path, '{"rung": "specified"}')
        self.assertEqual(digest,
                         hashlib.sha256(b'{"rung": "specified"}').hexdigest())
        self.assertEqual(path.read_text(encoding="utf-8"), '{"rung": "specified"}')

    def test_the_digest_is_over_the_utf8_bytes_that_reached_the_disk(self):
        """A payload digest that does not reproduce from the published file
        proves nothing about what the three brains were given. Non-ASCII is the
        case that separates "digested the bytes written" from "digested
        something adjacent to them": another encoding produces a digest that is
        still 64 hex characters and still looks like a binding.
        """
        path = self.scratch("payload.md")
        content = "rationale: la décision — naïve, résumé\n"
        digest = pas.publish_immutable(path, content)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(path.read_bytes(), content.encode("utf-8"))

    def test_republishing_identical_content_is_inert(self):
        """Not merely "does not raise": the file is not rewritten. An artifact
        republished by unlink-and-recreate satisfies every content assertion
        while breaking each hard link and inode reference an audit trail holds
        to it — and it resets the timestamps a human reads to order the run.
        """
        path = self.scratch("result.md")
        first = pas.publish_immutable(path, "same\n")
        inode = path.stat().st_ino
        second = pas.publish_immutable(path, "same\n")
        self.assertEqual(first, second)
        self.assertEqual(path.read_text(encoding="utf-8"), "same\n")
        self.assertEqual(path.stat().st_ino, inode)

    def test_republishing_different_content_is_refused_and_changes_nothing(self):
        """An immutable artifact that can be overwritten is not immutable, and
        an audit trail built on overwritable files informs nobody. A second
        publish of different bytes under one identity is conflicting evidence,
        not an update, and the original is what survives it.
        """
        path = self.scratch("result.md")
        first = pas.publish_immutable(path, "original\n")
        with self.assertRaises(pas.TrackerWriteError) as caught:
            pas.publish_immutable(path, "tampered\n")
        self.assertNotIsInstance(caught.exception, pas.UpdateOutcomeUncertain)
        self.assertIn(str(path), str(caught.exception))
        #: The remedy is the publisher's, not the initializer's. One shared
        #: sentence would tell whoever published a second worker result under
        #: one identity to "resume the run", which is neither the question they
        #: face nor an action that resolves it.
        self.assertIn("reconcil", str(caught.exception).lower())
        self.assertNotIn("resume", str(caught.exception).lower())
        self.assertEqual(path.read_text(encoding="utf-8"), "original\n")
        self.assertEqual(pas.publish_immutable(path, "original\n"), first)

    def test_publishing_leaves_no_temp_file_behind_whether_it_lands_or_is_refused(self):
        """Both paths, because their cleanups differ and only one of them is on
        the happy path. Nothing else ever removes this file, and a stranded
        ``.result.md.*.tmp`` in a run directory is indistinguishable from one a
        live writer is holding open right now.
        """
        path = self.scratch("result.md")
        pas.publish_immutable(path, "original\n")
        self.assertEqual([entry.name for entry in path.parent.iterdir()],
                         ["result.md"])
        with self.assertRaises(pas.TrackerWriteError):
            pas.publish_immutable(path, "tampered\n")
        self.assertEqual([entry.name for entry in path.parent.iterdir()],
                         ["result.md"])

    def test_publishing_creates_the_directories_its_path_names(self):
        """``scratch/`` is per-run ephemera the spec places INSIDE the run
        directory, and it does not exist until the first thing is published into
        it. A publisher that required its parent to be there would make every
        caller create directories for it, and each of them would guess a mode.
        """
        run_dir = make_run(self)
        path = run_dir / "scratch" / "quorum" / "q1" / "brain-1.json"
        pas.publish_immutable(path, '{"rung": "code-evidenced"}\n')
        self.assertTrue(path.is_file())

    def test_a_publish_that_cannot_be_created_reports_that_nothing_happened(self):
        """An OSError escaping as itself is a stop outside this module's
        exception family: a caller branching on ``TrackerError`` never sees it.
        A read-only stop that escapes its own family is not one.
        """
        run_dir = make_run(self)
        (run_dir / "scratch").write_text("not a directory", encoding="utf-8")
        with self.assertRaises(pas.TrackerWriteError) as caught:
            pas.publish_immutable(run_dir / "scratch" / "result.md", "x\n")
        self.assertNotIsInstance(caught.exception, pas.UpdateOutcomeUncertain)
        self.assertEqual((run_dir / "scratch").read_text(encoding="utf-8"),
                         "not a directory")

    def test_a_publish_whose_directory_sync_fails_is_uncertain_not_failed(self):
        """The third outcome, kept distinguishable here too. The file is already
        visible and only its durability is in doubt. Reporting
        ``TrackerWriteError`` would tell the caller nothing happened, and a
        caller that believes that republishes — and is then refused by its own
        first write as conflicting evidence, with no way to tell which write
        was the tampering.
        """
        run_dir = make_run(self)
        path = run_dir / "scratch" / "result.md"
        with mock.patch.object(pas, "_sync_directory",
                               side_effect=OSError(errno.EIO, "simulated dirsync")):
            with self.assertRaises(pas.UpdateOutcomeUncertain):
                pas.publish_immutable(path, "content\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "content\n")

    def test_a_published_artifact_carries_the_mode_the_module_names(self):
        """``mkstemp`` picks 0600 silently and the link carries that mode onto
        the artifact forever. An audit trail a second account cannot open is not
        one, and the cap at 0644 is the other half: the tracker and its
        artifacts exist to be read, never rewritten from outside this module.

        The umask is pinned for the duration, so this asserts the module's
        choice rather than the environment's.
        """
        run_dir = make_run(self)
        path = run_dir / "scratch" / "result.md"
        previous = os.umask(0o022)
        try:
            pas.publish_immutable(path, "content\n")
        finally:
            os.umask(previous)
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(pas.TRACKER_MODE & 0o022, 0)

if __name__ == "__main__":
    unittest.main()
