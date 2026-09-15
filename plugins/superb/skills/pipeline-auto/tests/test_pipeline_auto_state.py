"""Contract tests for the pipeline-auto/v1 state spine."""

from __future__ import annotations

import ast
import contextlib
import errno
import hashlib
import importlib.util
import inspect
import json
import multiprocessing
import os
import re
import shutil
import subprocess
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
TEMPLATES = SKILL_DIR / "templates"
SCRIPTS = SKILL_DIR / "scripts"

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
#:
#: ``types`` was added by P03 for ``MappingProxyType`` and is the first member
#: admitted for a capability this module could NOT otherwise state. The rung
#: ladder is the controller's own adoption bar, so it has to refuse to be
#: written to -- and nothing among the ten can make a mapping that does. The
#: hand-rolled alternative is strictly weaker, not merely longer: a ``dict``
#: subclass overriding ``__setitem__`` is bypassed by
#: ``dict.__setitem__(RUNGS, ...)``, so the freeze is advisory, while a
#: ``mappingproxy`` has no mutation API to bypass. That is the opposite of how
#: ``re`` and ``tempfile`` left this list -- each of those was removed because
#: the module could state the same thing at the SAME strictness with no import
#: at all. ``types`` opens nothing, runs nothing and reaches no filesystem, so
#: it adds no capability for this list to bound. The phase plan's Tech Stack
#: names it.
#: ``json`` was admitted by a three-brain quorum before P03 Task 7, and the
#: reasoning is recorded at the head of that task in the phase plan. It passes
#: the same test ``types`` and ``copy`` passed: it opens nothing, runs nothing
#: and reaches no filesystem, so it adds no capability for this list to bound.
#:
#: What makes it NECESSARY rather than merely admissible is that the durable
#: form of a brain response cannot be stated without it. The alternative was
#: this module's own section grammar, and that grammar loses data: ``_csv``
#: splits a quote containing a comma into two values, and a response's
#: ``line`` (an ``int`` that must not be a ``bool``) and ``blocker`` (``None``,
#: distinct from ``""``) have no spelling in it at all. A flat round-trip turns
#: a valid response into six violations. Writing a grammar that survives the
#: round-trip means writing a nested, typed, escaping serialisation format --
#: which is the hand-rolled reader this module already refused as "strictly
#: weaker than the format it imitated".
#:
#: SCOPE, so this does not become a precedent for JSON everywhere. Markdown
#: still holds every durable form it already held: the tracker, ``decisions.md``,
#: the findings ledger, worker results and the question record. ``json`` is for
#: agent-authored values that are typed and nested -- brain responses and the
#: gate records -- and for JSON text embedded inside markdown fields, which the
#: section grammar cannot reach at all.
#:
#: AND IT MUST BE WRAPPED. ``json.loads`` on agent-supplied text raises
#: ``JSONDecodeError``, which is outside ``TrackerError`` and would escape every
#: handler a controller has written. A parse failure is a ``TrackerError``, the
#: same as every other malformed-input path in this module.
ALLOWED_IMPORTS = frozenset({
    "__future__", "contextlib", "copy", "errno", "fcntl", "hashlib", "json",
    "msvcrt", "os", "pathlib", "time", "types",
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


#: A repository root that is absolute, plausible, and nobody's home directory.
#: It is COMMITTED — it reaches ``NEW_RUN`` and, spelled the same way, the
#: fixture — so it may not be the checkout this file happens to sit in: a real
#: one bakes one machine's account name into every case that cites it. Cases
#: that need the root to exist on disk build one under ``tempfile`` instead and
#: pass it explicitly.
EXAMPLE_REPO_ROOT = "/srv/checkouts/claude-plugin"

#: The arguments a run is born with, in one place so a case that varies one of
#: them varies exactly one of them. Every value here is real: the base commit is
#: this repository's own, and the branch is the shape a run actually targets.
NEW_RUN = {
    "run_id": "2026-09-14-example",
    "base_commit": "c8bddd610119f52b54bf077d284c7f5d8362ae77",
    "target_branch": "feat/example",
    "repo_root": EXAMPLE_REPO_ROOT,
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

    def test_a_repo_root_that_is_not_an_absolute_path_is_refused(self):
        """The root is recorded here and checked nowhere else at birth.

        A relative root joined to a citation path resolves against whatever
        directory the controller happens to be standing in — which is not a
        place, it is a coincidence. The spellings below are the ones a caller
        reaches for: the sentinel other cells use for absence, a bare name, a
        relative path, and a ``~`` no one expands.
        """
        for value in ("", "-", "repo", "relative/path", "./repo", "../repo",
                      "~/repo", "/two words/repo"):
            with self.subTest(repo_root=value):
                self.assertIn("repo_root", str(
                    self.refusal(pas.TrackerValidationError, repo_root=value)))

    def test_a_repo_root_that_is_not_a_string_is_refused_by_type(self):
        """``Path('/srv/repo')`` is the argument a caller is most likely to
        hold, and the interface says ``str``. It must be refused rather than
        stringified: the grammar check indexes the value, so a ``Path`` reaching
        it raises ``TypeError`` — outside this module's exception family — and
        a coercion here would contradict the annotation the way the ``Path``
        sweep above exists to prevent.
        """
        for value in (Path("/srv/checkouts/claude-plugin"), 4, None, b"/srv"):
            with self.subTest(repo_root=value):
                self.assertIn("repo_root", str(
                    self.refusal(pas.TrackerValidationError, repo_root=value)))

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

#: The four cells a controller fills in when it copies `templates/progress.md`.
#: Spelled once, here, because two tests read them: the expansion check below
#: and the `validate_run` check after it. Every value is one the module's own
#: argument checks in `initialize_run` accept, so a template that expands into
#: something those checks reject fails loudly rather than being papered over by
#: a test that had quietly chosen laxer inputs than the real entry point takes.
TEMPLATE_RUN_ID = "2026-09-14-example"
TEMPLATE_BASE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
TEMPLATE_TARGET_BRANCH = "feat/example"
#: Absolute, because that is what the field means, and synthetic, because the
#: expanded template is compared byte for byte against a real run and this
#: constant would otherwise have to be one machine's checkout path.
TEMPLATE_REPO_ROOT = "/srv/checkouts/example"
TEMPLATE_WORKER_LIMIT = 4


def progress_template() -> str:
    return (TEMPLATES / "progress.md").read_text(encoding="utf-8")


def decisions_template() -> str:
    return (TEMPLATES / "decisions.md").read_text(encoding="utf-8")


def filled_progress_template() -> str:
    """`templates/progress.md` with its four placeholders filled in.

    Placeholder EXPANSION, which is what a controller copying the template
    does; not row surgery, which is what `with_row` and `rewritten_row` exist
    for and what a bare `str.replace` over a table row must never be. It still
    goes through `swap`, because the fault both share is the same one: a
    pattern that is no longer in the file makes `str.replace` a silent no-op,
    and an expansion test built on one compares the UNEXPANDED template against
    `initialize_run`'s output, fails, and sends the reader after the wrong bug
    — or, worse, passes if the template were ever committed pre-expanded.
    """
    text = progress_template()
    text = swap("<base_commit>", TEMPLATE_BASE_COMMIT, text)
    text = swap("<target_branch>", TEMPLATE_TARGET_BRANCH, text)
    text = swap("<repo_root>", TEMPLATE_REPO_ROOT, text)
    text = swap("<worker_limit>", str(TEMPLATE_WORKER_LIMIT), text)
    #: Last, and deliberately so: the run id also appears inside the three
    #: artifact paths, and expanding it first would leave nothing for the
    #: `swap` above to find only if one of the others were spelled with it.
    return swap("<run_id>", TEMPLATE_RUN_ID, text)


class ProgressTemplateTests(unittest.TestCase):
    """`templates/progress.md` is the shape every later phase writes into.

    The named fault is the template drifting from the renderer. A controller
    that copies a template whose headers no longer match `_SECTIONS` produces a
    tracker that fails validation on its FIRST read — at which point the run
    has already started, the failure surfaces as a foreign-schema stop, and the
    reader goes looking for a bug in whatever wrote the tracker rather than in
    the file it was copied from. A template that disagrees with the validators
    is worse than no template at all.
    """

    def test_the_template_round_trips_through_the_modules_own_parser(self):
        """parse -> render must return the template byte for byte.

        Of the EXPANDED template, and it can be nothing else now that ``## Run``
        has a semantic validator: ``| run_id | <run_id> |`` is a legal table
        cell and is not a state any run can be in, so a template that still
        parsed as a tracker would only prove the validator was not looking.
        Expansion substitutes inside cells and changes no structure, so every
        byte-level fact this assertion carries -- marker, title, section order,
        column headers, separator rows, cell spacing, run key order, terminal
        newline -- is the raw template's, unchanged.

        One assertion, and it subsumes the whole structural contract: marker,
        title, the single blank line under the title, section identity, section
        ORDER, every column header, every separator row, cell spacing, the
        twelve stage rows, the run key order and the terminal newline. A
        template that merely "looks right" fails here; only the canonical byte
        sequence passes.
        """
        text = filled_progress_template()
        self.assertEqual(pas.render_tracker(pas.parse_tracker(text)), text)

    def test_the_template_carries_the_placeholders_a_controller_fills_in(self):
        """It is a TEMPLATE, not a snapshot of somebody's run.

        Committing a real run's `progress.md` here would still round-trip and
        still validate — and would hand every later run another run's id, base
        commit and artifact paths. The five caller-supplied fields must be
        unfilled, and nothing else may be: a placeholder left in `revision` or
        `schema` is a cell no caller knows to fill.
        """
        #: Read STRUCTURALLY, not through ``parse_tracker``: this case is about
        #: which cells are unfilled, and an unfilled cell is exactly what the
        #: semantic validator refuses. Parsing here would make the case require
        #: the template to be valid in order to prove it is a template.
        run = pas._key_values(pas._sections(progress_template())["## Run"],
                              pas._RUN_KEYS)
        self.assertEqual(
            [key for key, value in run.items()
             if value.startswith("<") and value.endswith(">")],
            ["run_id", "base_commit", "target_branch", "repo_root",
             "worker_limit"])
        self.assertEqual(run["schema"], pas.SCHEMA)
        #: The run id is interpolated into three artifact paths as well as its
        #: own cell, so an expansion that filled the cell and left the paths
        #: would still look filled in. Stated as a count, against the file.
        self.assertEqual(progress_template().count("<run_id>"), 4)

    def test_the_expanded_template_is_byte_identical_to_initialize_run(self):
        """The anti-drift check with teeth.

        The other tests in this class prove the template is *a* valid tracker.
        This one proves it is *the* tracker this module writes for a new run —
        same defaults, same artifact paths, same starting revision, same first
        transition. Without it the template can quietly acquire a `revision` of
        1, a predicted `spec` path, or a stage 01 that is `pending`, and every
        structural test above still passes while a controller that copied the
        file starts its run one transition ahead of the record.
        """
        run_dir = empty_run(self)
        pas.initialize_run(run_dir, run_id=TEMPLATE_RUN_ID,
                           base_commit=TEMPLATE_BASE_COMMIT,
                           target_branch=TEMPLATE_TARGET_BRANCH,
                           repo_root=TEMPLATE_REPO_ROOT,
                           worker_limit=TEMPLATE_WORKER_LIMIT)
        self.assertEqual(filled_progress_template(),
                         (run_dir / "progress.md").read_text(encoding="utf-8"))

    def test_the_expanded_template_validates_and_names_the_first_action(self):
        """Through the public entry point, and then acted on.

        `validate_run` is the door every consumer uses, and `derive_next_action`
        is the first question asked through it. A template that parses but
        leaves no stage active is a tracker a resuming controller cannot act on
        — twelve pending stages are monotone, so every ordering check waves
        them through and the run has no next action at all.
        """
        run_dir = empty_run(self)
        (run_dir / "progress.md").write_text(filled_progress_template(),
                                             encoding="utf-8")
        tracker = pas.validate_run(run_dir)
        self.assertEqual(pas.derive_next_action(tracker),
                         "dispatch-intent-readers")

    def test_the_template_lists_twelve_stages_with_only_the_first_active(self):
        """Stated as the whole column, not as twelve membership checks.

        `assertIn(f"| {stage} | ", text)` passes on a template carrying twelve
        rows in the wrong ORDER, twelve `pending` rows, or two `active` ones.
        The order and the state sequence are the recovery story for stages
        01-07, whose outputs Git cannot reconstruct.
        """
        stages = pas.parse_tracker(filled_progress_template())["stages"]
        self.assertEqual(tuple(row["stage"] for row in stages), pas.STAGES)
        self.assertEqual([row["stage_state"] for row in stages],
                         ["active"] + ["pending"] * (len(pas.STAGES) - 1))
        self.assertEqual([row["next_action"] for row in stages[1:]],
                         ["-"] * (len(pas.STAGES) - 1))

    def test_the_template_carries_every_section_and_column_the_module_defines(self):
        """The drift this task exists to catch, stated against `_SECTIONS`.

        The round-trip test would also fail on a missing section, but it fails
        with a parse error that names one heading. This one names the whole
        disagreement — a section dropped, a section added, a column renamed —
        which is what a reader needs when `_SECTIONS` has just been edited.
        """
        lines = progress_template().splitlines()
        self.assertEqual(lines[0], pas.MARKER)
        self.assertEqual(lines[1], pas.TITLE)
        self.assertEqual([line for line in lines if line.startswith("## ")],
                         [heading for heading, _, _ in pas._SECTIONS])
        for _, _, header in pas._SECTIONS[1:]:
            self.assertIn(pas._row(header), lines)
        self.assertEqual(
            tuple(pas.parse_tracker(filled_progress_template())["run"]),
            pas._RUN_KEYS)

    def test_every_table_but_the_stage_table_starts_empty(self):
        """An empty `## Quorum` is the normal state of a healthy run.

        A template shipping an example row would be copied into every run and
        then have to be deleted by hand; the row that survives is a decision
        nobody made, recorded as though somebody had.
        """
        tracker = pas.parse_tracker(filled_progress_template())
        self.assertEqual(
            {key: tracker[key] for _, key, _ in pas._SECTIONS[2:]},
            {key: [] for _, key, _ in pas._SECTIONS[2:]})


class DecisionsTemplateTests(unittest.TestCase):
    """`templates/decisions.md` is the run's audit trail, in skeleton.

    It is not parsed by this module — `decisions.md` is named by `## Run` and
    read by the phase that owns decision resolution. What this module DOES own
    is the grammar of a decision id and the enum of grounding rungs, and a
    template spelling either of those in a way the module rejects teaches every
    later writer to spell it wrong.
    """

    def test_it_makes_provenance_grounding_and_status_mandatory(self):
        """Provenance is the entire difference between a decision a machine
        made and one the user made, and it is what contradiction routing reads
        to tell them apart. A field the template omits is a field the writer
        copying it never fills in.
        """
        text = decisions_template()
        for required in ("## Axis Index", "- Question:", "- Answer:", "- Axis:",
                         "- Provenance:", "- Action:", "- Scope:", "- Rung:",
                         "- Depth:", "- Status:", "Append-only"):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_it_shows_both_provenance_values(self):
        text = decisions_template()
        self.assertIn("- Provenance: human", text)
        self.assertIn("- Provenance: quorum", text)

    def test_every_decision_id_it_spells_is_one_the_module_accepts(self):
        """Through `_decision_id`, the module's own grammar, not by eye.

        A template showing `Q-<hash>` or `H-n` teaches the writer a spelling
        `_validate_tasks` refuses in a task's `Decisions` cell, and the run
        finds out at the first task that cites a decision. Both namespaces must
        appear, so a template that satisfied this by spelling no ids at all is
        refused too.
        """
        #: Every delimiter the template actually puts around an id: a
        #: table pipe, a backtick, a comma, a full stop, a closing
        #: paren, or whitespace. Anything left is the id itself.
        ids = re.findall(r"\b[HQ]-[^\s|,.)`]+", decisions_template())
        self.assertTrue(any(name.startswith("H-") for name in ids), ids)
        self.assertTrue(any(name.startswith("Q-") for name in ids), ids)
        for name in ids:
            with self.subTest(decision_id=name):
                self.assertTrue(pas._decision_id(name),
                                f"{name!r} is not a decision id this module accepts")

    def test_it_names_every_legal_action_and_no_foreign_one(self):
        """The closed vocabulary, asserted in BOTH directions.

        Checking only that the four legal actions appear is satisfied by a
        template that also lists `remediation.start-round` — the pipeline v2
        action this skill dropped — and a writer copying it records an action
        no validator in this run will ever honour. Two budgets mean two
        authorities, so `quorum.extend-budget` and `dispatch.extend-budget` are
        both named and neither substitutes for the other.
        """
        text = decisions_template()
        for action in ("task.resume", "quorum.adopt", "quorum.extend-budget",
                       "dispatch.extend-budget", "none"):
            with self.subTest(action=action):
                self.assertIn(action, text)
        for foreign in ("review.resolve-question", "filesystem.authorize",
                        "remediation.start-round"):
            with self.subTest(foreign=foreign):
                self.assertNotIn(foreign, text)

    def test_it_names_the_rung_enum_and_never_a_rung_value(self):
        """Names, never numbers.

        A brain never types a number, and the adoption floor must not be
        copyable: a `0.85` written into this template is a second source of
        truth for a constant P03 owns, sitting in a file a hand edits. The
        five names are here so an out-of-enum rung is recognisably wrong; the
        five values are not, so nobody can lower the bar by editing a template.
        """
        text = decisions_template()
        for rung in pas.RUNG_NAMES:
            with self.subTest(rung=rung):
                self.assertIn(rung, text)
        for value in ("0.95", "0.85", "0.70", "0.55", "0.30"):
            with self.subTest(value=value):
                self.assertNotIn(value, text)

    def test_it_states_the_one_legal_in_place_mutation(self):
        """Append-only is the whole reason the file is worth reading later.
        `Adopted -> Superseded` is the single exception, and a template that
        says "append-only" without naming it invites a writer to delete.
        """
        text = decisions_template()
        self.assertIn("Adopted", text)
        self.assertIn("Superseded", text)


class SddWorkspaceTests(unittest.TestCase):
    """`scripts/sdd-workspace` — the self-ignoring `scratch/` inside the run.

    Stage 12 gates completion on a clean `git status --short`, and stages 08-11
    write task briefs, implementer reports and review packages that must never
    reach a commit. If `scratch/` is not genuinely invisible to git, the final
    gate of the whole run fails for a reason that has nothing to do with the
    work — and the artifacts it holds are exactly the ones a reader needs to
    diagnose that.
    """

    def git(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, check=True)

    def workspace(self, *args: str) -> subprocess.CompletedProcess:
        """The script, run with the given arguments and NOT checked.

        The cwd is this process's, which is inside a git work tree — that is
        not incidental. The script this one descends from took no argument and
        derived its directory from `git rev-parse --show-toplevel`, so a
        re-point that forgot to delete the fallback would still succeed here
        and quietly write to `.superpowers/sdd` in whatever repository the
        controller happened to be standing in.
        """
        return subprocess.run([str(SCRIPTS / "sdd-workspace"), *args],
                              capture_output=True, text=True)

    def seeded_repo(self) -> tuple[Path, Path]:
        repo = Path(tempfile.mkdtemp(prefix="pipeline-auto-repo-"))
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True,
                       capture_output=True)
        run_dir = repo / "docs" / "superpowers" / "runs" / "2026-09-14-example"
        run_dir.mkdir(parents=True)
        (run_dir / "progress.md").write_text("tracked\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t",
                 "commit", "-qm", "seed")
        self.assertEqual(self.git(repo, "status", "--short").stdout, "")
        return repo, run_dir

    def test_scratch_is_created_inside_the_run_directory_and_ignores_itself(self):
        repo, run_dir = self.seeded_repo()
        result = self.workspace(str(run_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        printed = Path(result.stdout.strip())
        scratch = run_dir / "scratch"
        self.assertTrue(printed.is_absolute(), result.stdout)
        self.assertEqual(printed.resolve(), scratch.resolve())
        self.assertTrue((scratch / ".gitignore").is_file())
        (scratch / "task-brief-P02-T01.md").write_text("ephemeral\n",
                                                       encoding="utf-8")
        (scratch / "review-package.diff").write_text("ephemeral\n",
                                                     encoding="utf-8")
        (scratch / "reports").mkdir()
        (scratch / "reports" / "P02-T01.md").write_text("ephemeral\n",
                                                        encoding="utf-8")
        self.assertEqual(self.git(repo, "status", "--short").stdout, "")

    def test_the_ignore_is_scoped_to_scratch_and_hides_nothing_else(self):
        """A `.gitignore` written one level too high would pass every other
        case here and silently hide the run's own artifacts — `decisions.md`,
        `findings.md`, the phase plans — from the gate that is supposed to see
        them committed. The scope is asserted from the outside: a sibling of
        `scratch/` must still be reported.
        """
        repo, run_dir = self.seeded_repo()
        self.assertEqual(self.workspace(str(run_dir)).returncode, 0)
        (run_dir / "findings.md").write_text("durable\n", encoding="utf-8")
        self.assertIn("findings.md", self.git(repo, "status", "--short").stdout)

    def test_it_is_idempotent_and_keeps_what_is_already_in_scratch(self):
        """Run once per task brief, so re-running is the normal case. An
        implementation that clears the directory to guarantee the ignore file
        destroys a brief a worker is still reading.
        """
        repo, run_dir = self.seeded_repo()
        first = self.workspace(str(run_dir))
        self.assertEqual(first.returncode, 0, first.stderr)
        scratch = run_dir / "scratch"
        (scratch / "task-brief-P02-T01.md").write_text("ephemeral\n",
                                                       encoding="utf-8")
        second = self.workspace(str(run_dir))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual((scratch / "task-brief-P02-T01.md").read_text(
            encoding="utf-8"), "ephemeral\n")
        self.assertEqual(self.git(repo, "status", "--short").stdout, "")

    def test_it_refuses_a_run_directory_that_does_not_exist(self):
        """Creating it would be the wrong repair: the run directory is made by
        `initialize_run`, and a `scratch/` under a path that was mistyped is a
        worker writing its report where nothing will ever look for it.
        """
        repo, run_dir = self.seeded_repo()
        missing = run_dir.parent / "2026-09-14-typo"
        result = self.workspace(str(missing))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())
        self.assertIn("sdd-workspace:", result.stderr)
        self.assertIn(str(missing), result.stderr)

    def test_it_refuses_a_run_directory_that_is_not_a_directory(self):
        """Refused BY THE SCRIPT, with the script's own diagnostic.

        A non-zero exit is not enough to assert here and asserting only that
        was the first version of this case: with the guard deleted entirely,
        `mkdir -p` fails on a path whose parent is a file, `set -e` propagates,
        and the case passes while testing nothing the script does. What the
        guard buys is a message naming the run directory the caller got wrong,
        instead of a raw `mkdir` error about a path the caller never typed.
        """
        repo, run_dir = self.seeded_repo()
        result = self.workspace(str(run_dir / "progress.md"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((run_dir / "progress.md" / "scratch").exists())
        self.assertIn("sdd-workspace:", result.stderr)
        self.assertIn(str(run_dir / "progress.md"), result.stderr)

    def test_it_refuses_to_guess_when_given_no_run_directory(self):
        result = self.workspace()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())

    def test_it_refuses_more_than_one_run_directory(self):
        """Two run directories is a caller that has lost track of which run it
        is in, and silently taking the first would put one run's ephemera in
        the other's directory.
        """
        repo, run_dir = self.seeded_repo()
        result = self.workspace(str(run_dir), str(run_dir))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((run_dir / "scratch").exists())

    def test_the_script_is_executable(self):
        """Committed mode, not a local chmod: a subagent runs this by path."""
        self.assertTrue(os.access(SCRIPTS / "sdd-workspace", os.X_OK))

    def test_the_script_names_no_absolute_home_directory(self):
        """Repository-relative paths only. An absolute home path in a committed
        script breaks for everyone else and leaks the account name.
        """
        text = (SCRIPTS / "sdd-workspace").read_text(encoding="utf-8")
        self.assertNotIn("/home/", text)
        self.assertNotIn("/Users/", text)


#: The rung-enum names as they must appear in a rung-defaulting mistake. Used by
#: the AST detector below and by the test OF that detector, so the detector is
#: never proven against a pattern only it and nothing else uses.
#:
#: ``_RUNG_EVIDENCE`` is in the list because the evidence table is the SECOND
#: place a rung can acquire a fallback: ``_RUNG_EVIDENCE.get(declared,
#: (frozenset(), 0))`` gives an unlisted rung no evidence requirement at all,
#: which is the same fail-open door one table along. The table is total and
#: pinned by ``test_every_rung_states_its_own_evidence_requirement``, so the
#: fallback would be harmless TODAY — and would stop being harmless the moment
#: a sixth rung was added. The shape is refused as well as the data.
_RUNG_WORDS = ("RUNGS", "RUNG_ORDER", "RUNG_NAMES", "_RUNG_VALUES", "ADOPTABLE",
               "_RUNG_EVIDENCE")

#: The corpus the detector is proven against — one fallback per SHAPE it
#: refuses, and at least one per WORD in ``_RUNG_WORDS``. Both coverings are
#: asserted below, the words by
#: ``test_every_word_the_detector_refuses_is_a_word_the_corpus_spells``.
#:
#: The word covering is what stops the tuple drifting silently. A word no
#: spelling here uses can be deleted from ``_RUNG_WORDS``, or mistyped into it,
#: with the whole suite green and the comment above still claiming the detector
#: is proven against everything it refuses. ``_RUNG_EVIDENCE`` was found in
#: exactly that state: six spellings, every one of them saying ``RUNGS``.
_DEFAULTING_SPELLINGS = (
    "def f(rung):\n    return RUNGS.get(rung, 0.55)\n",
    "def f(rung):\n    return dict(RUNGS).get(rung, DEMOTION_RUNG)\n",
    "def f(rung):\n    return RUNGS.setdefault(rung, 0.55)\n",
    "def f(rung):\n    return RUNGS.get(rung) or 0.55\n",
    "def f(rung):\n    return RUNGS[rung] if rung in RUNGS else 0.55\n",
    "def f(rung):\n    try:\n        return RUNGS[rung]\n"
    "    except KeyError:\n        return 0.55\n",
    #: The evidence table is the second place a rung can acquire a fallback:
    #: an unlisted rung would be handed no evidence requirement at all.
    "def f(declared):\n"
    "    return _RUNG_EVIDENCE.get(declared, (frozenset(), 0))\n",
    #: A rung the order does not contain, scored as if it were the bottom one.
    "def f(rung):\n"
    "    return RUNG_ORDER.index(rung) if rung in RUNG_ORDER else 0\n",
    #: The value table behind the proxy, defaulted before the proxy sees it.
    "def f(rung):\n    return _RUNG_VALUES.get(rung, 0.55)\n",
    #: A name read positionally, with the last rung standing in past the end.
    "def f(i):\n"
    "    return RUNG_NAMES[i] if i < len(RUNG_NAMES) else RUNG_NAMES[-1]\n",
    #: An adoption test that answers yes when the rung is unrecognised. Each
    #: spelling above names exactly ONE of the words, so deleting any one of
    #: them from the tuple leaves that spelling undetected and fails the suite.
    "def f(rung):\n    return rung in ADOPTABLE or rung == \"specified\"\n",
)


def rung_defaulting_nodes(source: str) -> list[str]:
    """Every place the rung enum could acquire a fallback, by SHAPE not by name.

    ``RUNGS.get(rung_id, 0.55)`` is the sharpest single mistake available in
    this phase: 0.55 is ``engineering-judgement``, it is already in the module
    for the citation-demotion rule, so defaulting to it looks principled and
    reads as defensive — and it converts every malformed brain response into a
    legal engineering-judgement vote. The value that arrives is legal; the door
    it came through is not, which is exactly why nothing downstream can detect
    it.

    A module-wide ban on ``dict.get`` with a default is not available: P02 uses
    one for batch counting and two ``setdefault`` calls for grouping, and both
    are correct. So the detector is shaped instead — a lookup-with-fallback
    whose subtree names anything rung-related — which is what catches the four
    spellings of the same hole:

    * ``RUNGS.get(rung, 0.55)`` and ``dict(RUNGS).get(rung, 0.55)``
    * ``RUNGS.setdefault(rung, 0.55)``
    * ``RUNGS.get(rung) or 0.55`` and ``RUNGS[rung] if rung in RUNGS else 0.55``
    * ``try: RUNGS[rung] / except KeyError: return 0.55``
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        dump = ast.dump(node)
        if not any(word in dump for word in _RUNG_WORDS):
            continue
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "setdefault", "pop")
                and len(node.args) >= 2):
            found.append(f"{node.func.attr}-with-default at line {node.lineno}")
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            found.append(f"or-fallback at line {node.lineno}")
        elif isinstance(node, ast.IfExp):
            found.append(f"conditional fallback at line {node.lineno}")
        elif isinstance(node, ast.Try) and any(
            "KeyError" in ast.dump(handler) for handler in node.handlers
        ):
            found.append(f"KeyError fallback at line {node.lineno}")
    return found


def assignment_subtree(source: str, name: str) -> ast.AST:
    """The value expression of the one module-level assignment to ``name``."""
    matches = [node for node in ast.parse(source).body
               if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == name
                       for target in node.targets)]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one module-level assignment to {name}, "
            f"found {len(matches)}")
    return matches[0].value


def names_in(node: ast.AST) -> set[str]:
    return {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}


class QuorumRungLadderTests(unittest.TestCase):
    """The rung ladder, which is the whole of this skill's decision authority.

    A brain never types a number: it selects a grounding rung and the controller
    derives the value. Everything that can go wrong with that is a way for a
    number to arrive from somewhere other than this ladder — a run-configurable
    floor, a second definition of the names that drifts from P02's, a default
    for a rung the enum does not contain, or a demotion target that is itself
    adoptable. Each has a case below.
    """

    def test_the_ladder_is_built_over_p02s_rung_names_and_not_redefined(self):
        """P02 owns the five names and asserts membership against them directly.

        A second literal here is the same hole with an extra step: the two
        spellings pass every test on the day they are written and diverge the
        day either is edited, and the divergence shows up as a quorum whose
        rung the tracker refuses — or, worse, accepts under a different value.

        Asserted structurally as well as by value, because equal-today is what
        a re-typed literal looks like. The mutant this kills is
        ``RUNG_ORDER = ("specified", "code-evidenced", ...)``: it passes every
        value assertion in this class and dies here.
        """
        self.assertEqual(set(pas.RUNGS), set(pas.RUNG_NAMES))
        self.assertEqual(len(pas.RUNGS), len(pas.RUNG_NAMES))
        self.assertEqual(pas.RUNG_ORDER, tuple(reversed(pas.RUNG_NAMES)))
        source = module_source()
        self.assertIn("RUNG_NAMES", names_in(assignment_subtree(source, "RUNG_ORDER")),
                      "RUNG_ORDER must be derived from P02's RUNG_NAMES")
        self.assertTrue(
            {"RUNG_ORDER", "RUNG_NAMES"} & names_in(assignment_subtree(source, "RUNGS")),
            "RUNGS must be keyed by P02's rung names, not by a second literal")
        #: The value table is allowed to be a literal — the five numbers have to
        #: be written down somewhere — but it may not carry a key the enum does
        #: not have. A stray ``"unknown": 0.55`` sitting in it is a sink waiting
        #: for someone to wire a fallback up to.
        self.assertEqual(set(pas._RUNG_VALUES), set(pas.RUNG_NAMES))

    def test_the_five_values_are_the_spec_values(self):
        self.assertEqual(pas.RUNGS["specified"], 0.95)
        self.assertEqual(pas.RUNGS["code-evidenced"], 0.85)
        self.assertEqual(pas.RUNGS["convention-cited"], 0.70)
        self.assertEqual(pas.RUNGS["engineering-judgement"], 0.55)
        self.assertEqual(pas.RUNGS["speculation"], 0.30)

    def test_the_values_fall_strictly_along_rung_order(self):
        """What makes ``RUNG_ORDER.index`` a legitimate stand-in for the value.

        Spread is measured by rung: the winner's rung must be strictly HIGHER
        than the runner-up's, compared by index, never by a float margin. That
        substitution is only sound while the values are strictly decreasing
        along the order. Two rungs sharing a value, or an order that disagrees
        with the values, makes index comparison and value comparison give
        different answers on the same pair of clusters — silently, and in the
        direction of adopting.
        """
        values = [pas.RUNGS[name] for name in pas.RUNG_ORDER]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(len(set(values)), len(values),
                         "two rungs sharing a value make demotion indistinguishable "
                         "from the rung it demotes to")

    def test_the_floor_and_the_adoptable_set_are_derived_from_the_ladder(self):
        """``convention-cited`` cannot be adopted, and not by coincidence.

        "The codebase does it this way" is not authority for a machine
        decision. The bar is ``code-evidenced``; a typed ``ADOPTABLE`` literal
        would let the two drift, so the set is derived from the floor and the
        derivation is asserted structurally.
        """
        self.assertEqual(pas.ADOPTION_FLOOR, 0.85)
        self.assertEqual(pas.ADOPTION_FLOOR, pas.RUNGS["code-evidenced"])
        self.assertEqual(pas.ADOPTABLE, frozenset({"specified", "code-evidenced"}))
        self.assertEqual(
            pas.ADOPTABLE,
            frozenset(name for name in pas.RUNGS if pas.RUNGS[name] >= pas.ADOPTION_FLOOR))
        self.assertNotIn("convention-cited", pas.ADOPTABLE)
        self.assertIsInstance(pas.ADOPTABLE, frozenset)
        source = module_source()
        self.assertIn("ADOPTION_FLOOR", names_in(assignment_subtree(source, "ADOPTABLE")))
        self.assertIn("RUNGS", names_in(assignment_subtree(source, "ADOPTION_FLOOR")))

    def test_the_demotion_rung_is_below_the_floor(self):
        """The citation-demotion rule must not be able to adopt.

        A brain whose evidence does not resolve is demoted to
        ``engineering-judgement``. If the demotion target were at or above the
        floor, an answer whose citation could not be read would adopt anyway —
        which is the failure the demotion exists to prevent, reached through
        the demotion itself.
        """
        self.assertEqual(pas.DEMOTION_RUNG, "engineering-judgement")
        self.assertIn(pas.DEMOTION_RUNG, pas.RUNGS)
        self.assertLess(pas.RUNGS[pas.DEMOTION_RUNG], pas.ADOPTION_FLOOR)
        self.assertNotIn(pas.DEMOTION_RUNG, pas.ADOPTABLE)

    def test_the_ladder_is_frozen_at_the_language_level(self):
        """A controller that can edit its own adoption bar has no adoption bar.

        Freezing makes the self-serving move fail where it is made rather than
        at review, so the case asserts the refusal rather than the type: a
        subclass of ``dict`` that overrides ``__setitem__`` is bypassed by
        ``dict.__setitem__(RUNGS, ...)``, and a ``mappingproxy`` has no
        mutation API to bypass.
        """
        with self.assertRaises(TypeError):
            pas.RUNGS["specified"] = 0.99
        with self.assertRaises(TypeError):
            del pas.RUNGS["speculation"]
        self.assertIsInstance(pas.RUNGS, types.MappingProxyType)
        self.assertEqual(pas.RUNGS["specified"], 0.95)

    def test_no_module_attribute_is_a_live_handle_on_the_frozen_ladder(self):
        """``MappingProxyType(_RUNG_VALUES)`` is a proxy, and is not frozen.

        A ``mappingproxy`` is a read-only VIEW, not a copy: writing through the
        dict it wraps changes what the proxy reports. So a ladder built over a
        named module-level dict passes the freeze case above and is still
        editable by anything that can reach that name — which, in a module a
        controller imports, is everything. The ladder must wrap a dict nothing
        else holds.
        """
        sentinel = -1.0
        for name, value in sorted(vars(pas).items()):
            if not isinstance(value, dict) or not set(pas.RUNGS) <= set(value):
                continue
            with self.subTest(attribute=name):
                original = value["specified"]
                value["specified"] = sentinel
                try:
                    self.assertEqual(
                        pas.RUNGS["specified"], 0.95,
                        f"pipeline_auto_state.{name} is a live handle on RUNGS' "
                        "own storage; the freeze is cosmetic")
                finally:
                    value["specified"] = original

    def test_an_out_of_enum_rung_is_never_defaulted_to_a_legal_value(self):
        """The named fault, asserted at the only place it can be written.

        There is no runtime probe for this: the whole point is that a defaulted
        rung produces a legal value and raises nothing. It is detectable only
        in the source, so that is where it is refused.
        """
        self.assertEqual(rung_defaulting_nodes(module_source()), [])

    def test_the_rung_defaulting_detector_catches_the_fault_it_claims_to(self):
        """A test of the test. The guard above is an assertion that a pattern is
        ABSENT, which is the shape that passes when the detector is broken, when
        the file it reads is empty, and when the pattern was never findable in
        the first place. Each spelling of the hole is put in front of it here.
        """
        for spelling in _DEFAULTING_SPELLINGS:
            with self.subTest(spelling=spelling.splitlines()[-1].strip()):
                self.assertNotEqual(rung_defaulting_nodes(spelling), [])

    def test_every_word_the_detector_refuses_is_a_word_the_corpus_spells(self):
        """What makes the comment over ``_RUNG_WORDS`` true rather than aspirational.

        The tuple is the detector's whole notion of "rung-related", and a word
        no spelling in the corpus uses is a word whose deletion — or whose
        typo — leaves every case above green while quietly reopening the door
        it names. ``_RUNG_EVIDENCE`` was in exactly that state: the six
        spellings all said ``RUNGS``, so the newest entry was the one nothing
        proved. Enumerated from the tuple, so a seventh word fails here on the
        day it is added rather than sitting unproven.
        """
        for word in _RUNG_WORDS:
            with self.subTest(word=word):
                self.assertTrue(
                    any(word in spelling for spelling in _DEFAULTING_SPELLINGS),
                    f"{word} is refused by the detector but no spelling in "
                    "_DEFAULTING_SPELLINGS uses it, so nothing would notice if "
                    "it were deleted from _RUNG_WORDS or mistyped into it")

    def test_the_rung_values_are_not_run_configuration(self):
        """They are schema constants and never enter ``## Run``.

        The rendered half of this case is vacuous on its own — a fresh tracker
        has no floats in it whatever the module does — and it is kept only as
        the symptom. The half that dies under mutation is the second: a
        ``## Run`` field named for the floor, the budget, the depth cap or the
        ladder is a dial the controller can turn, and turning it is the one
        self-interested move this phase's arithmetic exists to forbid.
        """
        run_dir, _ = new_run(self)
        rendered = (run_dir / "progress.md").read_text(encoding="utf-8")
        for value in pas.RUNGS.values():
            self.assertNotIn(f"{value}", rendered)
        policy = {
            "rungs", "rung", "rung_order", "adoptable", "adoption_floor",
            "floor", "demotion_rung", "depth_cap", "budget_per_phase",
            "budget_per_run", "max_extensions", "irreversible_axes",
        }
        self.assertEqual(
            set(pas._RUN_KEYS) & policy, set(),
            "a policy constant has become a ## Run field: the controller can "
            "now edit its own adoption bar through an ordinary transition")

    def test_the_budget_depth_and_extension_caps_are_the_master_plans(self):
        """Three adoptions per phase, ten per run, depth cap 2, two extensions.

        ``bool`` is excluded by type rather than by arithmetic for the reason
        ``initialize_run`` excludes it: ``True == 1`` and ``True >= 1`` both
        hold, so a counter that became a flag would pass every comparison.
        """
        for name, expected in (("DEPTH_CAP", 2), ("BUDGET_PER_PHASE", 3),
                               ("BUDGET_PER_RUN", 10), ("MAX_EXTENSIONS", 2)):
            with self.subTest(constant=name):
                value = getattr(pas, name)
                self.assertEqual(value, expected)
                self.assertIsInstance(value, int)
                self.assertNotIsInstance(value, bool)
        self.assertLess(pas.BUDGET_PER_PHASE, pas.BUDGET_PER_RUN)

    def test_the_irreversible_axes_are_frozen_and_complete(self):
        """The list adoption checks a blast radius against, so a MISSING member
        fails open: an irreversible axis nobody enumerated matches nothing, and
        the decision that should have reached a human is adopted by three
        machines instead. Pinned by membership for that reason, and frozen for
        the same reason the ladder is.
        """
        self.assertEqual(pas.IRREVERSIBLE_AXES, frozenset({
            "product-scope", "destructive-data", "schema-migration",
            "external-service", "paid-dependency", "public-api", "wire-format",
            "authn-model", "authz-model", "runtime-cost", "licensing",
            "writes-outside-repo",
        }))
        self.assertIsInstance(pas.IRREVERSIBLE_AXES, frozenset)
        with self.assertRaises(AttributeError):
            pas.IRREVERSIBLE_AXES.add("whatever")


class QuorumErrorFamilyTests(unittest.TestCase):
    def test_every_quorum_failure_is_a_tracker_error(self):
        """One exception family per module, so a caller that catches this
        module's root sees a quorum stop too. A ``QuorumError(Exception)``
        escapes every ``except TrackerError`` the controller already writes,
        and an escaped stop is a run that carries on.
        """
        self.assertTrue(issubclass(pas.QuorumError, pas.TrackerError))
        for subclass in (pas.QuorumSchemaInvalid, pas.QuorumIncomplete):
            with self.subTest(exception=subclass.__name__):
                self.assertTrue(issubclass(subclass, pas.QuorumError))
                self.assertTrue(issubclass(subclass, pas.TrackerError))

    def test_the_two_quorum_stops_stay_distinguishable(self):
        """"This response is malformed" and "this quorum is not finished yet"
        are different facts with different recoveries — re-dispatch once then
        escalate, against wait for the outstanding brain. An alias makes a
        caller branching on the type take one of them for the other.
        """
        self.assertIsNot(pas.QuorumSchemaInvalid, pas.QuorumIncomplete)
        self.assertFalse(issubclass(pas.QuorumSchemaInvalid, pas.QuorumIncomplete))
        self.assertFalse(issubclass(pas.QuorumIncomplete, pas.QuorumSchemaInvalid))


class DeriveQidTests(unittest.TestCase):
    """``derive_qid(question, axis)`` — stable identity for one question.

    What it hashes, exactly: the question text with runs of whitespace squashed
    to one space and case folded, then a NUL, then the axis token VERBATIM.
    Nothing else. Not the run id, not the phase, not the raiser, not the
    options, and above all not the decisions digest.
    """

    QUESTION = "Which storage engine?"
    AXIS = "storage-engine"

    def test_the_question_is_normalised_for_whitespace_and_case(self):
        """The same question retyped is the same question. Re-raised after a
        compaction it arrives reflowed and recapitalised, and a qid that moved
        would open a second quorum on ground the run had already settled.
        """
        self.assertEqual(
            pas.derive_qid(self.QUESTION, self.AXIS),
            pas.derive_qid("  which   STORAGE\n engine? ", self.AXIS))

    def test_the_axis_is_hashed_verbatim(self):
        """The axis is a stage-03 question ``ID`` or the literal ``new``, and
        that namespace is case-SENSITIVE: ``_TOKEN`` admits upper case, so
        ``Storage-Engine`` and ``storage-engine`` are two different questions
        and folding them together would give two axes one quorum.
        """
        base = pas.derive_qid(self.QUESTION, self.AXIS)
        self.assertNotEqual(base, pas.derive_qid(self.QUESTION, "Storage-Engine"))
        self.assertNotEqual(base, pas.derive_qid(self.QUESTION, "new"))
        self.assertNotEqual(base, pas.derive_qid("Which cache layer?", self.AXIS))

    def test_a_qid_is_one_the_tracker_will_accept(self):
        """The seam. ``_validate_quorum`` judges a ``QID`` cell against
        ``_Hex(12)``, so a derivation that widened to sixteen characters or
        emitted upper case would make every row this phase writes unparseable —
        and would do it at the tracker, a phase later, not here.
        """
        qid = pas.derive_qid(self.QUESTION, self.AXIS)
        self.assertEqual(len(qid), 12)
        self.assertTrue(pas._QID.fullmatch(qid), qid)

    def test_the_qid_does_not_move_when_anything_else_is_decided(self):
        """THE COMPACTION-REPLAY SEED, pinned two ways.

        The digest of the decisions so far is deliberately not an input. With
        it, the same question acquires a new identity every time anything else
        is decided, so a re-raise after a compaction dispatches a second quorum
        and the run re-litigates ground it has already settled — while every
        record on disk looks well-formed.

        The arity assertion alone does not close it: a context argument added
        as KEYWORD-ONLY still raises ``TypeError`` positionally. So the
        signature itself is pinned, which is what kills that mutant.
        """
        with self.assertRaises(TypeError):
            pas.derive_qid(self.QUESTION, self.AXIS, "deadbeef")
        parameters = inspect.signature(pas.derive_qid).parameters
        self.assertEqual(list(parameters), ["question", "axis"])
        for name, parameter in parameters.items():
            with self.subTest(parameter=name):
                self.assertIs(parameter.default, inspect.Parameter.empty)
                self.assertEqual(parameter.kind,
                                 inspect.Parameter.POSITIONAL_OR_KEYWORD)
        expected = hashlib.sha256(
            b"which storage engine?\x00storage-engine").hexdigest()[:12]
        self.assertEqual(pas.derive_qid(self.QUESTION, self.AXIS), expected)

    def test_the_field_separator_cannot_be_forged(self):
        """Two fields joined by a delimiter either exclude the delimiter from
        the fields or are not an encoding at all. ``"a\\x00b" + NUL + "c"`` and
        ``"a" + NUL + "b\\x00c"`` are the same bytes, so without the refusal two
        different questions on two different axes share one qid — one quorum
        answering for both, with each record naming the other's question.

        ``str.split`` does not treat NUL as whitespace, so squashing does not
        remove it and the collision survives normalisation.
        """
        forged = "a\x00b"
        self.assertEqual(" ".join(forged.split()), forged)
        with self.assertRaises(pas.QuorumSchemaInvalid):
            pas.derive_qid(forged, "c")
        with self.assertRaises(pas.QuorumSchemaInvalid):
            pas.derive_qid("a", "b\x00c")

    def test_an_axis_outside_the_question_id_namespace_is_refused(self):
        """The axis is a table cell before it is a hash input.

        A padded or spaced axis hashes to a different qid from the token the
        tracker will hold, and the disagreement surfaces a phase later as a
        quorum record nobody can look up. The namespace is ``_TOKEN`` — the
        grammar the ``## Questions`` ``ID`` column is already judged against —
        so that is what is accepted here.
        """
        for axis in ("", " ", "storage-engine ", "storage engine", "-leading",
                     "Not A Token"):
            with self.subTest(axis=axis):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.derive_qid(self.QUESTION, axis)
        for axis in ("new", "axis-2", "C-001", "storage-engine"):
            with self.subTest(axis=axis):
                self.assertTrue(pas._QID.fullmatch(pas.derive_qid(self.QUESTION, axis)))

    def test_a_non_string_question_or_axis_is_refused_rather_than_coerced(self):
        """``str(text)`` is the short spelling and the wrong one: it hashes the
        REPR of whatever it is handed, so a question record whose ``question``
        arrived as a dict, a list or ``None`` gets a stable, well-formed,
        meaningless qid and no error anywhere. Coercion is the same fault as a
        defaulted rung: an illegal input arriving as a legal value.
        """
        for question in (None, 12, {"question": "which?"}, ["which?"], b"which?"):
            with self.subTest(question=question):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.derive_qid(question, self.AXIS)
        for axis in (None, 12, ["storage-engine"], b"storage-engine"):
            with self.subTest(axis=axis):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.derive_qid(self.QUESTION, axis)

    def test_a_question_that_squashes_to_nothing_is_refused(self):
        """Every blank question on an axis would otherwise share one qid, and
        the first of them would answer for all the rest.
        """
        for question in ("", "   ", "\n\t "):
            with self.subTest(question=question):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.derive_qid(question, self.AXIS)


def response(**overrides):
    """A valid, grounded brain response; override exactly the field under test.

    The canonical shape of the data contract, written once so a case can state
    ONE deviation and nothing else. It is also the seam where the contract and
    the module's ``_RESPONSE_KEYS`` are asserted to agree: a key the module
    forgot to require is a key a brain may omit, and a key the module requires
    that no brain is told to send rejects every real response.
    """
    base = {
        "qid": "0" * 12,
        "answer_key": "postgres",
        "answer": "Use the existing PostgreSQL instance.",
        "rung": "code-evidenced",
        "evidence": [{"kind": "repo", "path": "db/engine.py", "line": 1,
                      "quote": "PostgresEngine"}],
        "consequences": [{"kind": "file-exists", "subject": "db/session.sql",
                          "value": "present"}],
        "consistent_with": [{"kind": "decision", "id": "H-001"}],
        "forecloses": ["a filesystem-only deployment"],
        "blast": ["storage-engine"],
        "alternatives": [{"answer_key": "sqlite", "rung": "speculation",
                          "reason": "no concurrent writers"}],
        "what_would_change_my_mind": "A decision pinning the run to a single-file database.",
        "blocker": None,
    }
    base.update(overrides)
    return base


class ValidateBrainResponseTests(unittest.TestCase):
    """``validate_brain_response`` — the gate between "three agents were asked"
    and "a decision was adopted".

    Strict in BOTH directions: every known key must be present and no unknown
    key may be. Unknown-key rejection is not tidiness — ``confidence``,
    ``score`` and ``certainty`` are exactly the keys a brain that types a number
    invents, and a validator that ignores extras lets that number reach the
    arithmetic that was built so no brain could type one.

    Three distinctions the cases below hold apart, because collapsing any of
    them is how a malformed answer becomes a vote:

    * An out-of-enum rung is SCHEMA-INVALID. It is never defaulted, never
      demoted, and no violation this function returns ever names a rung the
      brain could have meant.
    * A malformed response is not a low-confidence answer and not a blocker.
      It is not a response at all: the brain is re-dispatched once and a second
      malformed reply leaves the quorum incomplete, which escalates.
    * Grounding is NOT judged here. An empty falsifier and a citation that will
      not resolve are both schema-valid, and both are punished later by
      demotion. Rejecting them here would put two different recoveries —
      re-dispatch and demote — behind one verdict.
    """

    def test_a_grounded_response_is_valid(self):
        """The canonical contract shape passes. Without this case every other
        case in the class is satisfied by ``return ["nope"]``."""
        self.assertEqual(pas.validate_brain_response(response()), [])

    def test_a_self_reported_number_is_rejected_as_an_unknown_key(self):
        """The named fault. A brain never types a number; it selects a rung and
        the controller derives the value. These three keys are what a brain
        that ignores that invents, and the only thing standing between them and
        the arithmetic is that an unknown key is a violation."""
        for field, value in (("confidence", 0.97), ("score", 9),
                             ("certainty", "high")):
            with self.subTest(field=field):
                payload = response()
                payload[field] = value
                problems = pas.validate_brain_response(payload)
                self.assertIn(f"unknown-field:{field}", problems)

    def test_a_rung_outside_the_enum_is_schema_invalid(self):
        """``RUNGS.get(rung, 0.55)`` is the single sharpest mistake available
        in this phase, and this is where it would be made. ``high`` is not a
        rung: it is not a demotion, not an engineering-judgement vote, and not
        a low-confidence answer. It is a response that does not exist."""
        problems = pas.validate_brain_response(response(rung="high"))
        self.assertIn("rung-not-in-enum", problems)

    def test_a_numeric_rung_is_schema_invalid(self):
        """Including the numbers that ARE legal rung values. A brain that types
        0.85 has typed a number, and accepting it because the number happens to
        be ``code-evidenced``'s value is the same hole reached from the other
        side."""
        for value in (0.95, 0.85, 0.55, 1, True):
            with self.subTest(rung=value):
                self.assertIn("rung-not-in-enum",
                              pas.validate_brain_response(response(rung=value)))

    def test_every_rung_name_in_the_frozen_ladder_is_accepted(self):
        """The enum is the ladder, all five of it. A validator that admitted
        only the adoptable two would reject every honest low-rung answer, and
        every rejection is a re-dispatch and then an escalation — a run that
        escalates everything while looking correctly strict."""
        for name in pas.RUNG_NAMES:
            with self.subTest(rung=name):
                self.assertEqual(pas.validate_brain_response(response(rung=name)), [])

    def test_a_rung_is_matched_exactly_and_never_normalised_or_widened(self):
        """Only the five names, spelled the way the ladder spells them.

        Two faults share this one case. Normalising — ``value.strip().lower()``
        — is the defaulting fault wearing a tidier name: it repairs a brain's
        output until it reaches a legal value, and the value that arrives is
        legal while the door it came through is not. Widening is the other
        half: one extra accepted token, an alias or a confidence word a brain
        is likely to type, and that token now carries whatever rung the
        arithmetic gives it.

        The variants are derived from the ladder rather than typed out, so a
        rung added or renamed in P02 is covered here the day it lands.
        """
        variants = set()
        for name in pas.RUNG_NAMES:
            variants.update({name.upper(), name.title(), name.capitalize(),
                             f" {name}", f"{name} ", f"{name}\n",
                             name.replace("-", "_"), name.replace("-", ""),
                             name.replace("-", " "), name[:-1], name + "s"})
        variants -= set(pas.RUNG_NAMES)
        #: Free text a brain reaches for when it has not read the ladder. None
        #: of these is a rung, and each would be a silent extra vote.
        variants.update({"high", "medium", "low", "certain", "uncertain",
                         "strong", "weak", "anything", "unknown", "default",
                         "rung", "-", "0.85", "n/a", "none"})
        for value in sorted(variants):
            with self.subTest(rung=value):
                self.assertIn("rung-not-in-enum",
                              pas.validate_brain_response(response(rung=value)))
                self.assertIn(
                    "empty-alternatives",
                    pas.validate_brain_response(response(alternatives=[
                        {"answer_key": "sqlite", "rung": value,
                         "reason": "no concurrent writers"}])),
                    "the enum is relaxed inside an alternative")

    def test_a_missing_rung_is_not_in_the_enum_either(self):
        """A response with no rung at all has no legal rung, which is the same
        fact as an illegal one and takes the same recovery. Reported as both,
        so a caller keying on either code sees it."""
        payload = response()
        del payload["rung"]
        problems = pas.validate_brain_response(payload)
        self.assertIn("rung-not-in-enum", problems)
        self.assertIn("missing-field:rung", problems)

    def test_an_unhashable_rung_is_reported_and_never_raised(self):
        """``["code-evidenced"] in RUNGS`` raises ``TypeError``: unhashable.

        A validator that raises on a malformed response has not classified it.
        The TypeError is not in this module's exception family, so it escapes
        every ``except TrackerError`` the controller has written — the run dies
        on a brain's typo instead of re-dispatching it. Every shape a JSON
        document can carry must come back as a violation string."""
        for value in (["code-evidenced"], {"name": "code-evidenced"},
                      {"code-evidenced"}, None):
            with self.subTest(rung=value):
                problems = pas.validate_brain_response(response(rung=value))
                self.assertIsInstance(problems, list)
                self.assertIn("rung-not-in-enum", problems)

    def test_no_violation_ever_names_a_rung_the_brain_could_have_meant(self):
        """The defaulting fault, asserted from the outside.

        A validator that answers "rung-not-in-enum, defaulted to
        engineering-judgement" has defaulted it; so has one that reports the
        nearest legal name or its value. The only legal output is that the
        response is invalid. This is the runtime companion to the AST detector,
        which catches the same fault where it would be written."""
        for rung in ("high", "very-high", 0.85, None):
            with self.subTest(rung=rung):
                problems = pas.validate_brain_response(response(rung=rung))
                for problem in problems:
                    for name in pas.RUNG_NAMES:
                        self.assertNotIn(name, problem)
                    for value in pas.RUNGS.values():
                        self.assertNotIn(str(value), problem)

    def test_the_rung_enum_is_the_frozen_ladder_and_not_a_second_literal(self):
        """Structural, because a re-typed enum is equal-today and divergent the
        day either copy is edited — the same hole ``RUNG_NAMES`` was hoisted
        into P02 to close. A rung name spelled out in this function's body is
        that second copy."""
        source = module_source()
        defined = {node.name for node in ast.parse(source).body
                   if isinstance(node, ast.FunctionDef)}
        called = {node.func.id
                  for node in ast.walk(function_node(source, "validate_brain_response"))
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        reachable = sorted({"validate_brain_response"} | (called & defined))
        literals = frozenset().union(
            *(code_constants(source, name) for name in reachable))
        self.assertEqual(
            literals & set(pas.RUNG_NAMES), frozenset(),
            "a rung name is written out where the response is judged; the enum "
            "must be consulted, never re-typed")
        names = set().union(*(names_in(function_node(source, name))
                              for name in reachable))
        self.assertIn("RUNGS", names,
                      "the rung check must reach the frozen ladder")

    def test_empty_alternatives_is_a_reserved_violation_not_a_demotion(self):
        """A brain that offers no second-best has not considered one, and the
        recovery is a re-dispatch rather than a lower rung. The code is
        reserved, so it is asserted exactly rather than by substring."""
        self.assertIn("empty-alternatives",
                      pas.validate_brain_response(response(alternatives=[])))

    def test_an_alternative_without_a_reason_is_empty_alternatives(self):
        """An alternative with a blank reason is a field filled to pass a
        validator. Whitespace is not a reason, and an unstated second-best is
        the same fact as no second-best."""
        payload = response(alternatives=[
            {"answer_key": "sqlite", "rung": "speculation", "reason": "   "}])
        self.assertIn("empty-alternatives", pas.validate_brain_response(payload))

    def test_an_alternative_carrying_an_illegal_rung_is_empty_alternatives(self):
        """The rung enum is not relaxed inside an alternative. An alternative
        rung is read by the same arithmetic as the winner's, so a free-text
        rung there is the same number-from-nowhere with one level of nesting
        in front of it."""
        for alt in ({"answer_key": "sqlite", "rung": "low", "reason": "no writers"},
                    {"answer_key": "sqlite", "rung": 0.3, "reason": "no writers"},
                    {"answer_key": "", "rung": "speculation", "reason": "no writers"},
                    "sqlite"):
            with self.subTest(alternative=alt):
                self.assertIn("empty-alternatives",
                              pas.validate_brain_response(response(alternatives=[alt])))

    def test_an_empty_falsifier_is_schema_valid_and_demoted_later_not_rejected(self):
        """Grounding is not judged here. An empty falsifier is a weak answer,
        not a malformed one, and the two have different recoveries: demotion
        against re-dispatch. Rejecting it here would put both behind one
        verdict and the weak answer would be re-asked instead of demoted."""
        self.assertEqual(
            pas.validate_brain_response(response(what_would_change_my_mind="")), [])

    def test_a_falsifier_that_is_not_a_string_is_a_violation(self):
        """Absent is not empty. ``null`` and ``false`` are a brain declining the
        field rather than answering it emptily, and the field is required."""
        for value in (None, False, ["a decision record"], 0):
            with self.subTest(falsifier=value):
                self.assertIn(
                    "falsifier-not-a-string",
                    pas.validate_brain_response(
                        response(what_would_change_my_mind=value)))

    def test_forecloses_is_required(self):
        """What an answer rules out is how a later contradiction is detected.
        An empty list, a list of blanks and a non-list are the three ways to
        supply nothing while appearing to have answered."""
        for value in ([], ["", "   "], "a filesystem-only deployment", None):
            with self.subTest(forecloses=value):
                self.assertIn("empty-forecloses",
                              pas.validate_brain_response(response(forecloses=value)))

    def test_a_brain_cannot_raise_a_question(self):
        """There is no field through which a brain raises a question of its
        own; the only exit is ``blocker``. A brain that could raise one would
        open a quorum on its own question — depth without a human anywhere in
        it — and the unknown-key rule is what makes that unreachable."""
        for field in ("raises", "question", "escalate", "needs"):
            with self.subTest(field=field):
                payload = response()
                payload[field] = {"question": "and what about caching?"}
                self.assertIn(f"unknown-field:{field}",
                              pas.validate_brain_response(payload))

    def test_every_contract_key_is_required_and_never_defaulted(self):
        """Each of the twelve, one at a time, rather than one representative.

        The mutant this kills is a ``_RESPONSE_KEYS`` missing a member: the
        response then validates without it, and whichever consumer reads that
        field downstream gets a ``KeyError`` at adoption time or, worse, a
        default nobody chose."""
        self.assertEqual(set(pas._RESPONSE_KEYS), set(response()),
                         "the module's required keys and the data contract have "
                         "drifted apart")
        for key in sorted(response()):
            with self.subTest(missing=key):
                payload = response()
                del payload[key]
                self.assertIn(f"missing-field:{key}",
                              pas.validate_brain_response(payload))

    def test_the_three_identity_fields_may_not_be_blank(self):
        """A blank ``answer_key`` clusters with every other blank one, so three
        brains that answered nothing agree unanimously."""
        for key in ("qid", "answer_key", "answer"):
            for value in ("", "   ", None, 7):
                with self.subTest(field=key, value=value):
                    self.assertIn(f"empty-field:{key}",
                                  pas.validate_brain_response(response(**{key: value})))

    def test_consequences_must_be_a_non_empty_list_of_checkable_assertions(self):
        """A consequence is something that would be verifiably TRUE of the
        repository if the answer were adopted — never a rationale. A free-text
        item is a rationale wearing a consequence's name, and it is what makes
        an adopted decision unfalsifiable afterwards."""
        self.assertIn("empty-consequences",
                      pas.validate_brain_response(response(consequences=[])))
        self.assertIn("empty-consequences",
                      pas.validate_brain_response(response(consequences="file-exists")))
        for item in ("because postgres is already running",
                     {"kind": "because", "subject": "db", "value": "x"},
                     {"kind": "file-exists", "subject": "", "value": "present"},
                     {"kind": "file-exists", "subject": "db/session.sql"}):
            with self.subTest(consequence=item):
                self.assertIn("consequence-item-malformed",
                              pas.validate_brain_response(response(consequences=[item])))

    def test_consistent_with_must_be_a_non_empty_list_of_anchors(self):
        """``consistent_with`` is what ``decision_depth`` walks. An answer
        anchored to nothing is depth-unbounded by construction: nothing ties it
        back to a thing a human said."""
        for value in ([], None, "H-001"):
            with self.subTest(consistent_with=value):
                self.assertIn("empty-consistent-with",
                              pas.validate_brain_response(response(consistent_with=value)))
        for item in ({"kind": "hunch", "id": "H-001"}, {"id": "H-001"}, "H-001"):
            with self.subTest(anchor=item):
                self.assertIn("consistent-with-item-malformed",
                              pas.validate_brain_response(response(consistent_with=[item])))

    def test_an_anchor_must_name_the_thing_it_stands_on(self):
        """An anchor declares grounding; without an id it names nothing.

        `decision_depth` resolves anchors BY ID, so `{"kind": "decision"}`
        alone is a schema-valid claim of grounding that resolves to no record —
        and an anchor that resolves to nothing contributes nothing to the
        depth walk, so the answer with the least grounding in the run comes
        back at the shallowest depth there is. That is the Task-2 hazard in its
        JSON spelling; `_decision_anchors` closed the markdown one.

        A `decision` id is held to the id GRAMMAR because it is the kind whose
        id is looked up. `spec` and `repo` ids are free text — a spec line, a
        `path:line` — and are held only to being text, which is the pair that
        stops this from being a rule that refuses every anchor.
        """
        for item in ({"kind": "decision"}, {"kind": "decision", "id": ""},
                     {"kind": "decision", "id": "   "},
                     {"kind": "decision", "id": None},
                     {"kind": "decision", "id": ["H-001"]},
                     {"kind": "decision", "id": "H-01x"},
                     {"kind": "decision", "id": "storage-engine"},
                     {"kind": "spec"}, {"kind": "repo", "id": 12}):
            with self.subTest(anchor=item):
                self.assertIn(
                    "consistent-with-item-malformed",
                    pas.validate_brain_response(response(consistent_with=[item])))
        for item in ({"kind": "decision", "id": "H-001"},
                     {"kind": "decision", "id": "Q-abc123def456"},
                     {"kind": "spec", "id": "docs/design.md:112"},
                     {"kind": "repo", "id": "db/engine.py:1"}):
            with self.subTest(accepted=item):
                self.assertEqual(
                    pas.validate_brain_response(response(consistent_with=[item])), [])

    def test_an_evidence_item_is_checked_against_its_own_kind(self):
        """A ``repo`` citation carries a line number and a ``decision`` citation
        carries the decision it cites. ``line`` is an int and NOT a bool, for
        the reason ``initialize_run`` excludes bools: ``True == 1`` holds, so a
        flag that became a line number would pass every comparison and resolve
        against line 1 of whatever file was cited."""
        cases = (
            {"kind": "rumour", "path": "db/engine.py", "line": 1, "quote": "x"},
            {"kind": "repo", "path": "", "line": 1, "quote": "x"},
            {"kind": "repo", "path": "db/engine.py", "line": 1, "quote": "  "},
            {"kind": "repo", "path": "db/engine.py", "quote": "x"},
            {"kind": "repo", "path": "db/engine.py", "line": "12", "quote": "x"},
            {"kind": "repo", "path": "db/engine.py", "line": True, "quote": "x"},
            {"kind": "decision", "path": "decisions.md", "quote": "x"},
            "db/engine.py:12",
        )
        for item in cases:
            with self.subTest(evidence=item):
                self.assertIn("evidence-item-malformed",
                              pas.validate_brain_response(response(evidence=[item])))
        good = {"kind": "decision", "path": "decisions.md", "quote": "postgres",
                "decision": "H-001"}
        self.assertEqual(pas.validate_brain_response(response(evidence=[good])), [])

    def test_an_unhashable_kind_is_a_violation_and_never_a_type_error(self):
        """All three enum fields, over the shapes that cannot be hashed.

        ``["repo"] in _EVIDENCE_KINDS`` raises ``TypeError: unhashable type``.
        A JSON array and a JSON object are both things a brain can put in
        ``kind``, and neither can be hashed — so a bare ``in`` against the
        frozenset does not classify the response, it kills the process. The
        ``TypeError`` is outside this module's exception family, so it escapes
        every ``except TrackerError`` a controller has written: the run dies on
        a brain's typo instead of that brain being re-dispatched once and the
        quorum escalating if it repeats.

        This is the same fault ``effective_rung`` was carrying one function
        along, and the same fix — ``_member``, which establishes the type
        before it tests membership. The case is here because nothing else in
        this class varies ``kind`` past a wrong STRING: every existing spelling
        (``"rumour"``, ``"because"``, ``"hunch"``, a missing key) is hashable,
        so reverting any of the three sites to a bare ``in`` passed the whole
        suite.
        """
        for kind in (["repo"], ["repo", "decision"], [], {"kind": "repo"}, {}):
            with self.subTest(kind=kind):
                self.assertIn(
                    "evidence-item-malformed",
                    pas.validate_brain_response(response(evidence=[
                        {"kind": kind, "path": "db/engine.py", "line": 1,
                         "quote": "PostgresEngine"}])),
                    "_evidence_problems hashed a brain-supplied kind")
                self.assertIn(
                    "consequence-item-malformed",
                    pas.validate_brain_response(response(consequences=[
                        {"kind": kind, "subject": "db/session.sql",
                         "value": "present"}])),
                    "_consequence_problems hashed a brain-supplied kind")
                self.assertIn(
                    "consistent-with-item-malformed",
                    pas.validate_brain_response(response(consistent_with=[
                        {"kind": kind, "id": "H-001"}])),
                    "_anchor_problems hashed a brain-supplied kind")

    def test_evidence_that_is_not_a_list_is_reported_not_iterated(self):
        """``for item in payload["evidence"]`` over an int raises TypeError, and
        over a string walks it character by character — a malformed response
        that crashes the controller, or one that reports eight violations for
        one bad field."""
        for value in (12, None, {"kind": "repo"}, True):
            with self.subTest(evidence=value):
                problems = pas.validate_brain_response(response(evidence=value))
                self.assertIn("evidence-not-a-list", problems)

    def test_blast_is_a_list_of_axis_tokens(self):
        """The blast radius is matched against ``IRREVERSIBLE_AXES`` before a
        machine may adopt. A member that is not a token matches no axis, so an
        answer whose blast radius is ``[12]`` clears the irreversibility check
        by being unrecognisable — the fail-open shape the axis list is frozen
        against."""
        for value in ("storage-engine", None, {"storage-engine": True}):
            with self.subTest(blast=value):
                self.assertIn("blast-not-a-list",
                              pas.validate_brain_response(response(blast=value)))
        for item in (12, "", "   ", None, ["storage-engine"]):
            with self.subTest(item=item):
                self.assertIn("blast-item-malformed",
                              pas.validate_brain_response(response(blast=[item])))
        self.assertEqual(pas.validate_brain_response(response(blast=[])), [])

    def test_a_blocker_is_a_reason_or_null_and_nothing_else(self):
        """``blocker`` is the only exit a brain has, so a blank one is an exit
        taken without a reason: the controller has to escalate something it
        cannot describe."""
        self.assertEqual(pas.validate_brain_response(
            response(blocker="the spec contradicts the intent brief")), [])
        for value in ("", "   ", 7, [], {"reason": "x"}):
            with self.subTest(blocker=value):
                self.assertIn("blocker-not-a-string",
                              pas.validate_brain_response(response(blocker=value)))

    def test_a_blocker_does_not_excuse_a_schema_violation(self):
        """A malformed response is not a blocker. If declaring one suspended
        the schema, every malformed reply could be relabelled as a legitimate
        exit — and an exit is recorded as a quorum outcome, while a malformed
        reply is a re-dispatch."""
        payload = response(rung="high", blocker="I cannot answer this")
        problems = pas.validate_brain_response(payload)
        self.assertIn("rung-not-in-enum", problems)

    def test_a_response_that_is_not_an_object_is_one_violation(self):
        """A brain that returns a list, a bare string or nothing at all. The
        single code says the whole response is unusable rather than emitting
        twelve missing-field lines about a thing that is not a record."""
        for payload in (None, [], ["postgres"], "postgres", 7, True):
            with self.subTest(payload=payload):
                self.assertEqual(pas.validate_brain_response(payload),
                                 ["response-not-an-object"])

    def test_the_validator_never_repairs_the_payload_it_judges(self):
        """A validator that fills in what it found missing has adopted an answer
        no brain gave. ``setdefault`` is the one-character version of that, and
        it would make the response file on disk disagree with the bytes the
        brain actually returned — while every later reader sees a clean record."""
        for payload, twin in ((response(), response()),
                              (response(rung="high"), response(rung="high"))):
            with self.subTest(rung=payload["rung"]):
                pas.validate_brain_response(payload)
                self.assertEqual(payload, twin)
        stripped = response()
        del stripped["alternatives"]
        pas.validate_brain_response(stripped)
        self.assertNotIn("alternatives", stripped)

    def test_the_validator_is_total_over_every_malformed_shape(self):
        """Every field replaced by every wrong kind of JSON, one at a time.

        The property is the whole contract of the return type: a list of
        violations, for any input, always. An exception here is not a strict
        validator — it is an unhandled failure outside this module's family,
        on the one path that exists to handle a brain getting it wrong."""
        for key in sorted(response()):
            for value in (None, 0, True, "x", [], {}, [None], {"a": None}):
                with self.subTest(field=key, value=value):
                    problems = pas.validate_brain_response(response(**{key: value}))
                    self.assertIsInstance(problems, list)
                    for problem in problems:
                        self.assertIsInstance(problem, str)

    def test_grounding_is_not_judged_and_no_file_is_read(self):
        """An unresolvable citation is schema-valid and demoted later.

        Resolution needs the repository root, which P03 reads from ``## Run``
        and never derives; a validator that quietly resolved a citation against
        the process's working directory would demote every answer in a run
        whose repository is anywhere else — every citation unresolved, every
        answer below the floor, every question escalated, and nothing red
        anywhere."""
        payload = response(evidence=[{"kind": "repo", "line": 4096,
                                      "path": "no/such/file/anywhere.py",
                                      "quote": "not in any repository"}])
        self.assertEqual(pas.validate_brain_response(payload), [])
        source = module_source()
        self.assertEqual(write_capable_calls(source, "validate_brain_response"), [])
        reads = {node.attr for node in ast.walk(function_node(source, "validate_brain_response"))
                 if isinstance(node, ast.Attribute)}
        self.assertEqual(
            reads & {"read_text", "read_bytes", "exists", "is_file", "iterdir",
                     "resolve", "glob"},
            set(),
            "validate_brain_response touches the filesystem; grounding is "
            "resolved elsewhere, against the recorded repo_root")


#: The decision record the committed fixture's adopted `new`-axis quorum row
#: produces. Its `Axis` is the question's own bare 12-hex qid and NOT the
#: literal `new`: the row records what was asked, the record records the axis
#: that question opened. The pair is asserted below rather than described.
QID_AXIS_DECISION = """<!-- pipeline-auto-decisions/v1 -->

## Q-3f2a1b0c9d8e — Cache layer

- **Question:** Which cache layer fronts the session table?
- **Axis:** 3f2a1b0c9d8e
- **Answer:** redis — Use the existing Redis instance.
- **Decision action:** quorum.adopt
- **Provenance:** quorum
- **Depth:** 1
- **Consequences:** file-exists:cache/redis.conf=present
- **Scope:** T04
- **Status:** Adopted
"""


class ReservedAxisLiteralTests(unittest.TestCase):
    """``new`` is the axis literal, and therefore not an available question id.

    ``_validate_quorum`` resolves a quorum ``Axis`` against the stage-03
    question ids PLUS the literal ``new``, for an axis the run discovered after
    the gate closed. ``_validate_questions`` checked question ids for uniqueness
    only, so a question could itself be called ``new`` — and then the axis cell
    ``new`` has two readings at once: the reserved literal, and a reference to
    that question. Both readings are live in the same cell, which is worse than
    either: the contradiction check resolves the axis to decide what an adopted
    answer would contradict, and an axis with two meanings resolves to whichever
    the reader assumed.

    One reading is closed here, and it is the question-id one: the literal is
    load-bearing in the committed fixture and in this phase's own records, and
    ``new`` is a name no stage-03 question needs.
    """

    def test_a_stage_03_question_may_not_be_called_new(self):
        text = with_row("questions", "axis-2", {"id": "new"})
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("new", str(caught.exception))

    def test_the_axis_literal_itself_stays_legal(self):
        """The other half, and the reason this is a reservation rather than a
        ban: the committed fixture's two quorum rows are both on axis ``new``,
        and a rule that refused the literal would fail CLOSED on a value a
        specified writer actually emits.
        """
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual({row["axis"] for row in tracker["quorum"]}, {"new"})
        self.assertNotIn("new", {row["id"] for row in tracker["questions"]})

    def test_a_bare_qid_is_a_legal_axis_and_is_not_the_reserved_literal(self):
        """The axis a ``new``-axis question opens is its own bare 12-hex qid.
        Legal as an axis token, reproducible from the question, unique to it,
        and — unlike ``new`` — a contradiction bucket it shares with nothing.
        """
        qid = pas.derive_qid("Which cache layer?", "new")
        self.assertTrue(pas._QID.fullmatch(qid))
        self.assertNotEqual(qid, pas._RESERVED_AXIS)
        self.assertTrue(pas._TOKEN.fullmatch(qid))
        record = QID_AXIS_DECISION.replace("3f2a1b0c9d8e", qid)
        parsed = pas.parse_decisions(record)
        self.assertEqual(parsed["decisions"][f"Q-{qid}"]["axis"], qid)
        #: And the placeholder itself is still refused in that same field, so
        #: this is a substitution and not a relaxation.
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_decisions(
                record.replace(f"- **Axis:** {qid}",
                               f"- **Axis:** {pas._RESERVED_AXIS}"))

    def test_a_new_axis_row_and_its_decision_record_are_read_together(self):
        """THE RECONCILIATION, end to end, rather than two comments coexisting.

        ``_validate_quorum`` accepts ``new`` in a ``## Quorum`` row's ``Axis``
        cell and ``parse_decisions`` refuses it in a decision record's ``Axis``
        field. That looks like two validators disagreeing and is not: the row
        records WHAT WAS ASKED — a question raised after the stage-03 gate closed
        was asked on no stable axis — and the record records THE AXIS THAT
        QUESTION OPENED, which is the question's own bare qid.

        The committed fixture's first quorum row is exactly this shape: axis
        ``new``, outcome ``adopted``, ``Decision`` ``Q-3f2a1b0c9d8e``. The
        matching record is parsed beside it here, so the pair either holds or
        this test fails — a comment alone could go on being true of nothing.
        """
        tracker = pas.parse_tracker(valid_text())
        row = next(r for r in tracker["quorum"] if r["qid"] == "3f2a1b0c9d8e")
        self.assertEqual(row["axis"], pas._RESERVED_AXIS)
        self.assertEqual(row["outcome"], "adopted")
        self.assertEqual(row["decision"], "Q-3f2a1b0c9d8e")

        parsed = pas.parse_decisions(QID_AXIS_DECISION)
        record = parsed["decisions"][row["decision"]]
        self.assertEqual(record["axis"], row["qid"])
        self.assertEqual(record["status"], "Adopted")
        self.assertEqual(record["provenance"], "quorum")
        #: The two cells differ, and that difference is the contract: the row
        #: keeps the literal, the record carries the qid.
        self.assertNotEqual(record["axis"], row["axis"])
        self.assertEqual(list(parsed["axis_index"]), [row["qid"]])

    def test_a_minted_qid_axis_could_not_be_written_into_a_quorum_row(self):
        """Why the row keeps ``new`` rather than being rewritten to the minted
        axis: ``_validate_quorum`` closes that cell to the stage-03 question ids
        plus the literal, so the two namespaces are disjoint by construction and
        the row has nowhere to put a minted axis even if a writer tried.
        """
        text = with_row("quorum", "3f2a1b0c9d8e", {"axis": "3f2a1b0c9d8e"})
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn("neither a stage-03 question id", str(caught.exception))

    def test_the_two_namespaces_are_now_disjoint_on_the_literal(self):
        """Stated as the invariant rather than as either symptom, so it holds
        for a fixture that stops using ``new`` and for one that adds a third
        question.
        """
        tracker = pas.parse_tracker(valid_text())
        self.assertNotIn("new", {row["id"] for row in tracker["questions"]})
        self.assertEqual(pas.derive_qid("Which cache layer?", "new"),
                         pas.derive_qid("Which cache layer?", "new"))


class RunSectionValidatorTests(unittest.TestCase):
    """``## Run`` gains the semantic validator every other section has.

    ``base_commit``, ``target_branch`` and ``worker_limit`` were checked in
    ``initialize_run`` and nowhere else, so a later ``mutate`` could write
    nonsense into any of them and only ``_IDENTITY_KEYS`` would object, and
    only to the four keys it guards. ``worker_limit`` is not one of them, and
    it is what the run reads to reserve brain slots; ``agent_dispatch_count``
    and ``revision`` are not either, and they are counters other records cite.
    """

    def refused(self, text: str, needle: str):
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.parse_tracker(text)
        self.assertIn(needle, str(caught.exception))

    def test_the_committed_fixture_still_parses(self):
        """The positive control. A validator this strict is one typo away from
        refusing every real tracker, and a suite of rejection cases alone
        passes perfectly when it does.
        """
        self.assertEqual(pas.parse_tracker(valid_text())["run"]["worker_limit"], "6")

    def test_a_worker_limit_that_is_not_a_positive_integer_is_refused(self):
        """The cell the run reads to decide how many brain slots to reserve.

        ``'True'`` is in the list because ``initialize_run`` refuses the ``bool``
        by type and then writes ``str(worker_limit)`` — so the only spelling
        that can reach the tracker from anywhere else is the STRING, and a
        check that tested the python type would never see it.
        """
        for value in ("0", "-1", "1.5", "abc", "-", "True", "٣", "²", "+4"):
            with self.subTest(worker_limit=value):
                self.refused(swap("| worker_limit | 6 |",
                                  f"| worker_limit | {value} |"), "worker_limit")

    def test_a_counter_that_is_not_a_non_negative_integer_is_refused(self):
        """``revision`` and ``agent_dispatch_count`` are both cited elsewhere —
        the first by every record that names the revision it was written at —
        and ``isdigit`` alone is true of ``'٣'`` and ``'²'``, one of which
        parses as an integer and the other of which raises ``ValueError``,
        outside this module's exception family, in whatever reads it next.
        """
        for cell, original in (("revision", "12"), ("agent_dispatch_count", "48")):
            for value in ("-1", "1.0", "x", "-", "٣", "²"):
                with self.subTest(cell=cell, value=value):
                    self.refused(swap(f"| {cell} | {original} |",
                                      f"| {cell} | {value} |"), cell)

    def test_a_rewritten_schema_field_is_refused(self):
        """The marker says ``pipeline-auto/v1`` and until now the FIELD was
        never compared to it, so a tracker could carry the v1 marker and call
        itself v2 in its own ``## Run`` table. There is no migration in either
        direction, so the two disagreeing is a stop, not a version.
        """
        self.refused(swap("| schema | pipeline-auto/v1 |",
                          "| schema | pipeline-auto/v2 |"), "schema")

    def test_a_base_commit_that_is_not_a_full_object_name_is_refused(self):
        """It is one end of every range proof the run makes; an abbreviation or
        a symbolic name resolves somewhere else tomorrow.
        """
        for value in ("c8bddd6", "HEAD", "-", "C" * 40, "c" * 39):
            with self.subTest(base_commit=value):
                self.refused(
                    swap("| base_commit | c8bddd610119f52b54bf077d284c7f5d8362ae77 |",
                         f"| base_commit | {value} |"), "base_commit")

    def test_a_target_branch_of_main_or_master_is_refused(self):
        """``initialize_run`` refuses to START a run against them. Nothing
        refused a transition that RE-POINTED one, and pipeline-auto never
        merges or pushes, so the branch cell is the whole of what says where
        the work lands.
        """
        for value in ("main", "master", "-", "two words", "feature branch"):
            with self.subTest(target_branch=value):
                self.refused(swap("| target_branch | feat/pipeline-auto |",
                                  f"| target_branch | {value} |"), "target_branch")

    def test_a_run_id_that_escapes_its_own_directory_is_refused_on_reparse(self):
        """``initialize_run`` checks it once, at birth. The id is interpolated
        into three artifact paths, and a transition that rewrote it would point
        them at another run's audit trail — which ``_IDENTITY_KEYS`` catches
        only while the tracker it compares against is the one on disk.
        """
        for value in ("../elsewhere", ".hidden", "with space", "-"):
            with self.subTest(run_id=value):
                self.refused(swap("| run_id | 2026-09-14-pipeline-auto |",
                                  f"| run_id | {value} |"), "run_id")

    def test_a_repo_root_that_is_not_an_absolute_path_is_refused(self):
        """``initialize_run`` checks the ARGUMENT, once, at birth. Nothing
        checked the CELL, and the cell is what citation resolution is handed on
        every later read. A transition that made it relative, or a hand-edit
        that replaced it with the absence sentinel, resolves no citation at
        all — so every ``specified`` and ``code-evidenced`` answer demotes to
        ``engineering-judgement``, everything lands below the adoption floor,
        and the run escalates every question while looking cautious.
        """
        for value in ("-", "repo", "relative/path", "./repo", "~/repo",
                      "/two words/repo"):
            with self.subTest(repo_root=value):
                self.refused(swap(f"| repo_root | {EXAMPLE_REPO_ROOT} |",
                                  f"| repo_root | {value} |"), "repo_root")

    def test_the_validator_is_wired_into_the_one_entry_point(self):
        """Pinned the way the other eleven are pinned. A validator that exists
        and is never called is the shape this file has shipped before: every
        case below it passes when it is invoked directly, and nothing at all
        runs on a real parse.
        """
        dispatcher = function_node(module_source(), "_validate_tracker_semantics")
        called = {node.func.id for node in ast.walk(dispatcher)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertIn("_validate_run", called)

    def test_a_transition_cannot_write_nonsense_into_the_worker_limit(self):
        """The end-to-end shape the gap was about: not a hand-edited file, but
        an ordinary ``locked_tracker_update`` whose ``mutate`` sets a cell
        nothing downstream re-derives. The write must be refused AND the
        tracker on disk left byte-identical.
        """
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(
                run_dir, transition_id="capacity-1",
                mutate=setting_run_field("worker_limit", "0"))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

#: Where a run directory really sits: ``docs/superpowers/runs/<run-id>/`` under
#: the repository root. Four levels down, which is the whole trap — a root
#: derived from depth is ``parents[3]`` for a run in this layout and
#: ``parents[0]`` for one somebody put beside the repository root, and BOTH
#: spellings are a guess about a fact the tracker already records.
PRODUCTION_RUN_LAYOUT = ("docs", "superpowers", "runs")

#: A cited file, its one line, and the claim a brain would make about it.
CITED_PATH = "db/engine.py"
CITED_TEXT = "class PostgresEngine:\n"
CITATION = f"{CITED_PATH}:1"
CLAIM = "PostgresEngine"


def resolves_citation(root: str, citation: str, claim: str) -> bool:
    """Resolve a ``path:line`` citation against a repository root.

    Resolution belongs to P03 Task 3 and lives HERE, in the test file, because
    ``effective_rung`` does not exist yet. It is spelled the way the phase plan
    spells it — join the root, read the file, look at that line — for one
    reason: the thing under test is the ROOT, and a resolver that differed from
    the real one would prove nothing about the root it was handed.
    """
    path, _, line = citation.rpartition(":")
    try:
        lines = (Path(root) / path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return False
    index = int(line) - 1
    return 0 <= index < len(lines) and claim in lines[index]


def repo_with_a_run(case: unittest.TestCase, *,
                    layout: tuple[str, ...] = PRODUCTION_RUN_LAYOUT,
                    ) -> tuple[Path, Path]:
    """A real repository holding a real cited file, with a real run inside it.

    The run is placed at its production depth by default, so a case that
    derived the root from directory arithmetic would be deriving it from the
    same shape a real run has. ``layout`` exists so one case can put a second
    run at a different depth and show that no single index is right for both.
    """
    root = Path(tempfile.mkdtemp(prefix="pipeline-auto-repo-"))
    case.addCleanup(shutil.rmtree, root, ignore_errors=True)
    (root / ".git").mkdir()
    cited = root / CITED_PATH
    cited.parent.mkdir(parents=True)
    cited.write_text(CITED_TEXT, encoding="utf-8")
    run_dir = root.joinpath(*layout, NEW_RUN["run_id"])
    run_dir.parent.mkdir(parents=True)
    pas.initialize_run(run_dir, **{**NEW_RUN, "repo_root": str(root)})
    return root, run_dir


class RepoRootIsRecordedNeverDerivedTests(unittest.TestCase):
    """The root every citation is resolved against — recorded, never computed.

    This is the invisible failure. P03 demotes a brain that claims ``specified``
    or ``code-evidenced`` but cites a ``file:line`` that does not resolve. Hand
    that resolution a wrong root and NOTHING resolves: every grounded answer
    falls to ``engineering-judgement`` at 0.55, every cluster lands below the
    0.85 adoption floor, and the run escalates every question it is ever asked
    while looking like a correctly cautious quorum. No error, no exception, no
    red test. The skill appears to work and is useless.

    The obvious wrong root is directory arithmetic, and the arithmetic looks
    reasonable right up to the moment it is written down: a run lives at
    ``docs/superpowers/runs/<run-id>/``, so the root is ``parents[3]`` — until a
    run sits somewhere else, when it is ``parents[0]``, or ``parents[1]``, and
    there is no index that is right for both. The tracker records the answer.

    **What P02 owes and what P03 Task 3 still owes.** P02 owes the root: an
    explicit ``initialize_run`` argument, a ``## Run`` cell, a validator, and
    ``repo_root(tracker)`` reading it back with no computation in its body.
    That half is pinned here, end to end, against a real repository and a real
    file. P03 Task 3 owes the other half — ``effective_rung(response,
    repo_root)``: parsing a response's evidence, resolving each citation
    against the root it is GIVEN, and demoting to ``engineering-judgement``
    when one does not resolve. ``resolves_citation`` above stands in for the
    resolving step only, so that this file can prove the root is right; it is
    not the demotion rule, and P03 must not treat it as already written.
    """

    def computed_body(self, source: str) -> list[str]:
        """``repo_root``'s own statements, its docstring excluded.

        The prose in that docstring is obliged to name the derivation it
        refuses, so a guard reading the whole subtree would be satisfied by a
        function that simply stayed quiet about its own reasoning.
        """
        body = function_node(source, "repo_root").body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        return [ast.unparse(statement) for statement in body]

    def test_a_root_derived_from_run_dir_depth_resolves_no_citation_and_would_demote_every_grounded_answer(self):
        """THE CASE BETWEEN THIS DESIGN AND A SILENT TOTAL FAILURE.

        A real repository, a real file, a real run at its real depth. The
        recorded root resolves the citation; the roots directory arithmetic
        would have produced do not. Stated in both directions on purpose — a
        positive assertion alone passes against a resolver that says yes to
        everything, and a negative alone passes against one that says no.
        """
        root, run_dir = repo_with_a_run(self)
        recorded = pas.repo_root(pas.validate_run(run_dir))
        self.assertTrue(
            resolves_citation(recorded, CITATION, CLAIM),
            "the RECORDED root does not resolve a citation to a file that is "
            "really there: every grounded answer in this run would demote to "
            "engineering-judgement and the run would escalate everything")
        for depth in range(3):
            with self.subTest(parents=depth):
                self.assertFalse(
                    resolves_citation(str(run_dir.parents[depth]), CITATION, CLAIM),
                    f"run_dir.parents[{depth}] resolved the citation, so this "
                    "case can no longer tell a recorded root from a derived one")
        #: ``parents[3]`` IS this layout's root, which is exactly why depth is
        #: not an answer: the same arithmetic against a run kept somewhere else
        #: resolves nothing, and neither run can tell which kind it is.
        self.assertEqual(Path(recorded).resolve(), run_dir.parents[3].resolve())
        _, shallow_run = repo_with_a_run(self, layout=("runs",))
        self.assertTrue(
            resolves_citation(pas.repo_root(pas.validate_run(shallow_run)),
                              CITATION, CLAIM),
            "a run kept outside docs/superpowers/runs/ recorded a root that "
            "resolves nothing")
        self.assertFalse(
            resolves_citation(str(shallow_run.parents[3]), CITATION, CLAIM),
            "parents[3] resolved for a run at a different depth too, so this "
            "case would pass against a module that derived the root")

    def test_the_recorded_root_is_the_one_the_caller_named_even_when_no_ancestor_matches(self):
        """The same claim with the filesystem taken out of it.

        The run directory here has no ancestor equal to the recorded root, so
        no ``parents[N]`` — for any N — could produce this cell. A derivation
        that happened to be right for the production layout is wrong here, and
        wrong by inspection rather than by whether a file could be read.
        """
        root = Path(tempfile.mkdtemp(prefix="pipeline-auto-elsewhere-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        run_dir, tracker = new_run(self, repo_root=str(root))
        self.assertEqual(pas.repo_root(tracker), str(root))
        self.assertNotIn(str(root), [str(parent) for parent in run_dir.parents])

    def test_the_accessor_reads_the_recorded_field_and_computes_nothing(self):
        """The property this file can state even though resolution is P03's.

        Not "the accessor returns something plausible" — that passes against a
        body that walks for ``.git`` and gets lucky in a checkout. The body is
        ONE statement, and it is a read of the cell. Anything else in it is a
        computation, and a computation is the defect.
        """
        self.assertEqual(
            self.computed_body(module_source()),
            ["return tracker['run']['repo_root']"],
            "repo_root does something other than read the recorded cell; a "
            "root it computes is a guess about where a run directory sits")

    def test_the_guard_names_an_accessor_that_computed_a_root(self):
        """A test of the test. The clean result above is a statement about the
        module only if the guard would have spoken up, so the derivation is
        spliced into the real function and must be named.
        """
        source = module_source()
        mutant = with_statement_in(
            source, "repo_root",
            "return str(Path(tracker['run']['decisions']).parents[3])")
        self.assertNotEqual(mutant, source)
        self.assertEqual(self.computed_body(mutant)[0],
                         "return str(Path(tracker['run']['decisions']).parents[3])")
        self.assertEqual(self.computed_body(source),
                         ["return tracker['run']['repo_root']"])

    def test_the_root_survives_an_ordinary_transition_and_still_resolves(self):
        """Recorded at init means recorded for the life of the run.

        A transition rewrites ``revision`` and ``last_transition`` and renders
        the whole table back; a root that were re-derived on write would drift
        the first time anything at all happened, long after the run started.
        """
        root, run_dir = repo_with_a_run(self)
        settled = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                            mutate=bump_dispatches)
        self.assertEqual(pas.repo_root(settled), str(root))
        self.assertTrue(resolves_citation(pas.repo_root(settled), CITATION, CLAIM))

    def test_a_transition_cannot_repoint_the_recorded_root(self):
        """Re-pointing it mid-run is the same defect with a later timestamp.

        Every citation resolved before the change and every one resolved after
        would be judged against different repositories, and the quorum rows
        recording those judgements say nothing about which. It is guarded the
        way ``run_id`` and ``base_commit`` are guarded — the write is refused
        and the tracker on disk is left byte-identical.
        """
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(
                run_dir, transition_id="repoint-1",
                mutate=setting_run_field("repo_root", "/srv/checkouts/elsewhere"))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)


#: The small repository a citation is resolved against. One line per file, so a
#: case can name the line it means without counting.
ENGINE_TEXT = "class PostgresEngine:\n    pass\n"
POOL_TEXT = "PostgresEngine pool\n"
SPEC_TEXT = "The session table is backed by PostgreSQL.\n"

#: Two decision records in one file. The second exists so that a resolver which
#: searched the WHOLE file instead of the cited record's own section would say
#: yes to a quote that lives under a different D-ID.
DECISIONS_TEXT = (
    "<!-- pipeline-auto-decisions/v1 -->\n"
    "\n"
    "## H-001 — Session storage\n"
    "\n"
    "- **Answer:** postgres — the existing PostgreSQL instance.\n"
    "\n"
    "## H-002 — Cache backend\n"
    "\n"
    "- **Answer:** redis — a separate Redis process.\n"
)


def write_repo(root, relpath, text):
    """One file inside a repository tree, parents created."""
    path = Path(root) / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def populate_repo(root):
    """The tree every evidence case in this file cites."""
    write_repo(root, CITED_PATH, ENGINE_TEXT)
    write_repo(root, "db/pool.py", POOL_TEXT)
    write_repo(root, "spec.md", SPEC_TEXT)
    write_repo(root, "decisions.md", DECISIONS_TEXT)
    return root


def spec_citation(quote: str) -> dict:
    return {"kind": "spec", "path": "spec.md", "line": 1, "quote": quote}


def decision_citation(decision: str, quote: str) -> dict:
    return {"kind": "decision", "path": "decisions.md", "decision": decision,
            "quote": quote}


class EffectiveRungTests(unittest.TestCase):
    """``effective_rung`` — where a brain's claim about its own grounding is
    PRICED, by reading the file it cited.

    A declared rung is a claim about where an answer came from, and every rung
    above ``engineering-judgement`` is a claim that something on disk says so.
    This is the only place that claim is checked against the disk. An
    implementation that confirms the rung is in the enum and the evidence list
    is non-empty — and never opens the file — returns ``specified`` for an
    answer nothing supports, and every test that merely builds a real path
    passes against it. So the cases below are stated in BOTH directions: a
    citation that resolves keeps its rung, and a citation that resolves to a
    real file at a real line whose text does not contain the claim demotes.

    Demotion rather than rejection, and to a rung strictly below the adoption
    floor: rejection discards the answer and hands a malformed brain a veto,
    while demotion prices the claim at what it turned out to be worth and lets
    the arithmetic defeat it. Demotion never PROMOTES — a ``speculation`` with
    a broken citation stays ``speculation``.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="pipeline-auto-evidence-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        populate_repo(self.root)

    def rung(self, payload, root=None):
        return pas.effective_rung(
            payload, str(self.root) if root is None else str(root))

    # --- the claim is read off the disk, not off the response ------------

    def test_a_resolving_quoted_citation_keeps_the_declared_rung(self):
        """The positive half. Without it every case below passes against an
        implementation that demotes unconditionally, which would put the whole
        run below the floor and escalate everything.
        """
        self.assertEqual(self.rung(response()), "code-evidenced")

    def test_a_path_that_exists_at_a_line_that_does_not_contain_the_claim_demotes(self):
        """THE NAMED FAULT of this task.

        ``spec.md`` is really there and line 1 is really a line, so every check
        short of reading the text says yes. The brain quoted something the line
        does not say. A checker that only confirms the file exists is a rubber
        stamp, and it passes every case that merely builds a real path.
        """
        payload = response(rung="specified",
                           evidence=[spec_citation("backed by MySQL")])
        self.assertEqual(self.rung(payload), "engineering-judgement")
        self.assertLess(pas.RUNGS[self.rung(payload)], pas.ADOPTION_FLOOR,
                        "an unquotable citation landed at or above the floor, "
                        "so an inflated claim can still be adopted")

    def test_the_same_citation_quoting_what_the_line_really_says_keeps_its_rung(self):
        """The other direction of the case above: only the QUOTE differs, so a
        difference in outcome can be attributed to the file's text and nothing
        else.
        """
        payload = response(rung="specified",
                           evidence=[spec_citation("backed by PostgreSQL")])
        self.assertEqual(self.rung(payload), "specified")

    def test_a_quote_differing_only_in_spacing_and_case_still_resolves(self):
        """A brain retyping a line is not a brain inventing one. Whitespace
        runs and case are normalised on both sides; the words are not.
        """
        payload = response(rung="specified",
                           evidence=[spec_citation("backed   by\tpostgresql")])
        self.assertEqual(self.rung(payload), "specified")

    def test_a_blank_quote_demotes(self):
        """The empty string is ``in`` every line. A citation whose quote is
        whitespace would resolve against any file at any line, which is the
        rubber stamp with the file read left in for appearances.
        """
        payload = response(evidence=[{"kind": "repo", "path": CITED_PATH,
                                      "line": 1, "quote": "   "}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_nonexistent_path_demotes(self):
        payload = response(rung="specified",
                           evidence=[{"kind": "spec", "path": "no/such/file.md",
                                      "line": 1, "quote": "anything"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_directory_cited_as_a_file_demotes(self):
        """``read_text`` on a directory raises ``IsADirectoryError`` — an
        ``OSError``, which is a demotion and never an escaped crash.
        """
        payload = response(evidence=[{"kind": "repo", "path": "db", "line": 1,
                                      "quote": "PostgresEngine"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_citation_outside_the_repository_root_demotes(self):
        """An absolute citation, or one that climbs out with ``..``, resolves
        identically against EVERY root — which is precisely the property the
        recorded root exists to deny. A brain that cited one would be graded
        against a file this run does not contain, and the wrong-root case below
        could no longer tell a recorded root from a derived one.
        """
        outside = Path(tempfile.mkdtemp(prefix="pipeline-auto-outside-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        write_repo(outside, "db/engine.py", ENGINE_TEXT)
        climbing = os.path.relpath(outside / "db/engine.py", self.root)
        for path in (str(outside / "db/engine.py"), climbing):
            with self.subTest(path=path):
                payload = response(evidence=[
                    {"kind": "repo", "path": path, "line": 1,
                     "quote": "PostgresEngine"}])
                self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_sibling_whose_name_extends_the_roots_name_demotes(self):
        """Containment is a PARENT relation and never a string prefix.

        ``<root>-evil`` starts with ``<root>``, so
        ``str(target).startswith(str(root))`` — the obvious simplification of
        the containment test — calls this citation contained and prices it at
        the top rung. The case above cannot see that: an absolute path and a
        climb into an unrelated directory are both rejected by a prefix check
        too. A brain naming ``../<root>-evil/engine.py`` would be graded
        against a tree this run does not contain.
        """
        evil = Path(str(self.root) + "-evil")
        self.addCleanup(shutil.rmtree, evil, ignore_errors=True)
        write_repo(evil, "engine.py", ENGINE_TEXT)
        self.assertTrue(
            str(evil.resolve()).startswith(str(self.root.resolve())),
            "the sibling no longer extends the root's name, so a prefix check "
            "would reject this citation for the wrong reason")
        climbing = os.path.relpath(evil / "engine.py", self.root)
        payload = response(evidence=[{"kind": "repo", "path": climbing,
                                      "line": 1, "quote": "PostgresEngine"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_line_number_past_the_end_of_the_file_demotes(self):
        payload = response(evidence=[{"kind": "repo", "path": CITED_PATH,
                                      "line": 900, "quote": "PostgresEngine"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_line_number_below_one_demotes(self):
        """Lines are 1-based. ``0`` and ``-1`` are the two indices that a
        ``0 <= n < len(lines)`` bound would silently accept, and ``-1`` would
        resolve against the LAST line of the file — a citation to a place the
        brain never named.
        """
        for number in (0, -1):
            with self.subTest(line=number):
                payload = response(evidence=[
                    {"kind": "repo", "path": "db/pool.py", "line": number,
                     "quote": "PostgresEngine"}])
                self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_boolean_line_number_demotes(self):
        """``True == 1``, so a flag that arrived where a line number belongs
        would resolve against line 1 of whatever file was cited and grant the
        top rung to a response that never named a line at all.
        """
        payload = response(evidence=[{"kind": "repo", "path": CITED_PATH,
                                      "line": True, "quote": "PostgresEngine"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_non_string_quote_demotes_because_of_its_TYPE(self):
        """``_squash(str(quote))`` is exactly the coercion already refused for
        ``what_would_change_my_mind``, and it is refused here for the same
        reason: ``"quote": true`` squashes to ``"true"`` and grounds against
        any line that happens to contain the word.

        The cited line is written to contain BOTH ``True`` and ``12``, so each
        case demotes because the type was rejected and NOT because the text
        failed to match — which is all that a quote of ``12`` against
        ``class PostgresEngine:`` would be measuring.
        """
        line = "retries = 12 if True else 0"
        write_repo(self.root, "db/flags.py", line + "\n")
        for quote in (True, 12):
            with self.subTest(quote=quote):
                self.assertIn(str(quote), line,
                              "the fixture line no longer contains the coerced "
                              "quote, so this case would demote for want of a "
                              "match rather than for the type")
                payload = response(evidence=[
                    {"kind": "repo", "path": "db/flags.py", "line": 1,
                     "quote": quote}])
                self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_non_string_decision_id_demotes_because_of_its_TYPE(self):
        """The same shape one field along. A record headed ``## 12 — ...`` is a
        legal decision file, so ``_decision_section(text, str(decision))``
        would find it for a citation whose ``decision`` arrived as the integer
        ``12`` and attribute that record's words to a brain that never named
        it. The second half proves the record is reachable at all, so the first
        half cannot be passing for want of a section.
        """
        write_repo(self.root, "numbered.md",
                   "## 12 — Retention window\n"
                   "\n"
                   "- **Answer:** ninety days of session rows.\n")

        def cite(decision):
            return response(rung="specified", evidence=[
                {"kind": "decision", "path": "numbered.md",
                 "decision": decision, "quote": "ninety days"}])

        self.assertEqual(self.rung(cite(12)), "engineering-judgement")
        self.assertEqual(self.rung(cite("12")), "specified")

    def test_a_non_string_path_demotes_because_of_its_TYPE(self):
        """And one field further along. ``(root / str(path)).resolve()`` would
        read a file really named ``12`` for a citation whose ``path`` arrived as
        the integer, which is a citation to a place the brain never named.
        """
        write_repo(self.root, "12", ENGINE_TEXT)

        def cite(path):
            return response(evidence=[{"kind": "repo", "path": path, "line": 1,
                                       "quote": "PostgresEngine"}])

        self.assertEqual(self.rung(cite(12)), "engineering-judgement")
        self.assertEqual(self.rung(cite("12")), "code-evidenced")

    def test_a_dangling_citation_alongside_a_resolving_one_demotes(self):
        """EVERY citation is resolved, not merely enough of them.

        The first item here satisfies ``code-evidenced`` on its own, so a rule
        that stopped once the rung's minimum was met would never look at the
        second — and a brain could pad one true citation with any number of
        invented ones and have them recorded as grounding nobody checked.
        """
        payload = response(evidence=[
            {"kind": "repo", "path": CITED_PATH, "line": 1,
             "quote": "PostgresEngine"},
            {"kind": "repo", "path": "db/nowhere.py", "line": 1,
             "quote": "PostgresEngine"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    # --- what each rung must be able to show -----------------------------

    def test_specified_cited_only_from_repository_code_demotes(self):
        """``specified`` means a human said so. The default response's evidence
        is ``repo`` kind and RESOLVES, so this case cannot be passed by a
        resolver alone: code is not a specification, however real the file is.
        """
        self.assertEqual(self.rung(response(rung="specified")),
                         "engineering-judgement")

    def test_code_evidenced_cited_only_from_a_specification_demotes(self):
        """The converse, so the kind check is not satisfied by "any kind at
        all": a spec citation is not evidence about the code.
        """
        payload = response(rung="code-evidenced",
                           evidence=[spec_citation("backed by PostgreSQL")])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_convention_cited_needs_two_exemplars(self):
        """One occurrence is an instance; two are a convention."""
        self.assertEqual(self.rung(response(rung="convention-cited")),
                         "engineering-judgement")
        two = response(rung="convention-cited", evidence=[
            {"kind": "repo", "path": CITED_PATH, "line": 1,
             "quote": "PostgresEngine"},
            {"kind": "repo", "path": "db/pool.py", "line": 1,
             "quote": "PostgresEngine"}])
        self.assertEqual(self.rung(two), "convention-cited")

    def test_the_second_exemplar_must_itself_resolve(self):
        """Counting entries instead of resolutions would let one real file and
        one invented one add up to a convention.
        """
        payload = response(rung="convention-cited", evidence=[
            {"kind": "repo", "path": CITED_PATH, "line": 1,
             "quote": "PostgresEngine"},
            {"kind": "repo", "path": "db/nowhere.py", "line": 1,
             "quote": "PostgresEngine"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_every_rung_states_its_own_evidence_requirement(self):
        """No rung acquires its requirement by being absent from the table.

        A rung missing from the mapping would need no evidence at all, and the
        rung most likely to be forgotten is a new one added at the top.
        """
        self.assertEqual(set(pas._RUNG_EVIDENCE), set(pas.RUNGS))

    def test_an_empty_evidence_list_demotes_a_grounded_rung(self):
        """``evidence: []`` is SCHEMA-VALID — the response validator judges
        shape and deliberately reads no file — so this function meets it, and
        must demote rather than assume the list holds an item. Indexing it
        would raise ``IndexError``, which is outside ``TrackerError`` and so
        escapes every handler a controller has written.
        """
        for rung in ("specified", "code-evidenced", "convention-cited"):
            with self.subTest(rung=rung):
                self.assertEqual(self.rung(response(rung=rung, evidence=[])),
                                 "engineering-judgement")

    # --- decision citations ----------------------------------------------

    def test_a_decision_citation_resolves_against_its_own_record(self):
        payload = response(rung="specified", evidence=[
            decision_citation("H-001", "the existing PostgreSQL instance")])
        self.assertEqual(self.rung(payload), "specified")

    def test_a_decision_citation_quoting_another_record_demotes(self):
        """The quote is in the file — under ``H-002``. A resolver that searched
        the whole document would attribute one record's words to another, and
        ``consistent_with``/depth are computed from those attributions.
        """
        payload = response(rung="specified", evidence=[
            decision_citation("H-002", "the existing PostgreSQL instance")])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_decision_id_that_is_not_in_the_file_demotes(self):
        payload = response(rung="specified", evidence=[
            decision_citation("H-404", "the existing PostgreSQL instance")])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    # --- looking grounded without being grounded --------------------------

    def test_a_second_best_in_the_same_rung_demotes(self):
        """Two answers the brain grounds equally well is not a decision; it is
        the brain reporting that it could not separate them.
        """
        payload = response(alternatives=[
            {"answer_key": "sqlite", "rung": "code-evidenced",
             "reason": "also in the tree"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_separable_second_best_keeps_the_rung(self):
        """Stated so the case above is about the alternative's RUNG and not
        about having alternatives at all.

        The alternatives are spelled out here rather than taken from the
        default response, so this case is not a byte-identical restatement of
        ``test_a_resolving_quoted_citation_keeps_the_declared_rung`` under a
        second name: two second-bests, neither of them at the declared rung,
        one of them adjacent to it on the ladder.
        """
        payload = response(alternatives=[
            {"answer_key": "sqlite", "rung": "speculation",
             "reason": "no concurrent writers"},
            {"answer_key": "mysql", "rung": "convention-cited",
             "reason": "the sibling service uses it"}])
        self.assertEqual(self.rung(payload), "code-evidenced")

    def test_an_empty_falsifier_demotes(self):
        """An answer nothing could change is not grounded; it is held."""
        self.assertEqual(self.rung(response(what_would_change_my_mind="   ")),
                         "engineering-judgement")

    def test_a_non_string_falsifier_demotes_rather_than_reading_as_a_repr(self):
        """``str(None).strip()`` is ``'None'`` — truthy. Coercing the field
        before testing it turns the declined field into the best-looking
        falsifier in the run.
        """
        for value in (None, 0, [], {"why": "x"}):
            with self.subTest(falsifier=value):
                self.assertEqual(
                    self.rung(response(what_would_change_my_mind=value)),
                    "engineering-judgement")

    def test_anchoring_in_repository_code_alone_demotes(self):
        """An answer anchored only in what the code already does is an answer
        with nothing the user actually said behind it.
        """
        payload = response(consistent_with=[{"kind": "repo",
                                             "id": "db/engine.py:1"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_an_anchor_in_the_specification_is_enough(self):
        """``spec`` as well as ``decision``, so the case above is about
        repository-only anchoring and not about the literal ``decision``.
        """
        payload = response(consistent_with=[{"kind": "spec", "id": "S-1"}])
        self.assertEqual(self.rung(payload), "code-evidenced")

    def test_demotion_never_promotes_a_speculation(self):
        """Every rule above is a demotion. ``_not_above`` takes the LOWER of
        the two rungs; taking the demotion rung outright would RAISE a
        speculation with no evidence and an empty falsifier to 0.55.
        """
        payload = response(rung="speculation", evidence=[],
                           what_would_change_my_mind="")
        self.assertEqual(self.rung(payload), "speculation")

    # --- the root ---------------------------------------------------------

    def test_a_wrong_repo_root_silently_demotes_every_grounded_answer(self):
        """THE CASE BETWEEN THIS DESIGN AND A SILENT TOTAL FAILURE.

        Both wrong roots below are real directories, so nothing raises. With
        the wrong one nothing resolves, every ``specified`` and
        ``code-evidenced`` answer falls to 0.55, every cluster lands below the
        0.85 floor, and the run escalates every question it is ever asked while
        looking like a correctly cautious quorum. The root is a ``## Run``
        field and is never computed — this case is why.
        """
        payload = response()
        self.assertEqual(self.rung(payload), "code-evidenced")
        for wrong in (self.root / "db", self.root.parent):
            with self.subTest(root=str(wrong)):
                self.assertTrue(wrong.is_dir())
                self.assertEqual(self.rung(payload, root=wrong),
                                 "engineering-judgement")

    def test_the_recorded_repo_root_is_the_one_citations_resolve_against(self):
        """The whole path, end to end: a real run at its production depth, the
        root read back out of its own tracker, and a citation priced against
        it. The run sits three directories deep, so the roots directory
        arithmetic would have produced resolve nothing.
        """
        root, run_dir = repo_with_a_run(self)
        populate_repo(root)
        recorded = pas.repo_root(pas.validate_run(run_dir))
        self.assertEqual(pas.effective_rung(response(), recorded),
                         "code-evidenced")
        for depth in range(3):
            with self.subTest(parents=depth):
                self.assertEqual(
                    pas.effective_rung(response(), str(run_dir.parents[depth])),
                    "engineering-judgement",
                    f"run_dir.parents[{depth}] priced a citation, so this case "
                    "can no longer tell a recorded root from a derived one")
        self.assertNotEqual(Path(recorded).resolve(), run_dir.resolve())

    def test_a_repo_root_reached_through_a_symlink_still_resolves_citations(self):
        """THIS PHASE'S NAMED INVISIBLE FAILURE, on any checkout whose path has
        a symlinked component.

        ``_resolution_root`` canonicalises the recorded root, and the citation
        is canonicalised on the way in. Drop either ``.resolve()`` and the two
        are compared in different namespaces: the symlinked root is never a
        parent of the real target, so EVERY citation fails containment, every
        grounded answer lands at 0.55, every cluster falls below the floor, and
        the run escalates every question while looking like a correctly
        cautious quorum. Nothing raises, and no other case in this file can see
        it — every other root here comes from ``tempfile.mkdtemp`` and is
        already canonical.
        """
        elsewhere = Path(tempfile.mkdtemp(prefix="pipeline-auto-linked-"))
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        link = elsewhere / "checkout"
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as error:
            self.skipTest(f"symlinks are not available here: {error}")
        self.assertNotEqual(str(link), str(self.root.resolve()),
                            "the link and its target are spelled the same, so "
                            "this case would pass without canonicalisation")
        self.assertEqual(self.rung(response(), root=link), "code-evidenced")

    def test_a_root_that_is_not_a_directory_is_a_stop_and_not_a_demotion(self):
        """The one wrong root this function CAN detect, made loud.

        ``_validate_run`` checks the cell as a string and says so: "this path
        is not where it was" is a fact for the code resolving a citation to
        report. Demoting instead would be the silent total failure with a
        cause nobody could find — every answer in the run at 0.55 and no
        exception anywhere.
        """
        for bad in (str(self.root / "missing"), str(self.root / "spec.md"),
                    "", None, 12):
            with self.subTest(root=bad):
                with self.assertRaises(pas.QuorumError) as caught:
                    pas.effective_rung(response(), bad)
                #: The EXACT class. ``QuorumSchemaInvalid`` is a SUBCLASS of
                #: ``QuorumError``, so the assertion above passes against
                #: either one — and the two carry different recoveries. A
                #: ``QuorumSchemaInvalid`` says "re-dispatch that brain once",
                #: which would re-run the whole quorum against the same broken
                #: root. No brain did anything wrong here; the recorded root
                #: did.
                self.assertNotIsInstance(caught.exception,
                                         pas.QuorumSchemaInvalid)

    # --- no value arrives through an illegal door -------------------------

    def test_an_unknown_rung_raises_and_is_never_defaulted(self):
        """Defeats ``RUNGS.get(rung, 0.55)``: 0.55 is a legal value arriving
        through an illegal door, and nothing downstream could tell it from a
        brain that honestly reported engineering judgement.
        """
        for declared in ("high", "", None, 0.95, ["code-evidenced"]):
            with self.subTest(rung=declared):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    self.rung(response(rung=declared))

    def test_a_malformed_response_never_escapes_the_tracker_error_family(self):
        """Any JSON value at all, in any of the fields this function reads.

        ``alt.get(...)`` on a string raises ``AttributeError``; ``list(12)``
        and ``for item in 12`` raise ``TypeError``; indexing an empty list
        raises ``IndexError``; and ``["repo"] in frozenset(...)`` raises
        ``TypeError``: unhashable — a JSON array or object is a perfectly legal
        thing for a brain to put in a string field, and every membership test in
        this function hashes what it is given. None of those is a
        ``TrackerError``, so each escapes every ``except TrackerError`` a
        controller has written and kills the run on a brain's typo instead of
        demoting it.

        The list below is enumerated from the function's READS and not from the
        author's imagination — every ``.get`` in ``effective_rung``,
        ``_demotion_reason``, ``_evidence_resolves`` and ``_cited_file``, each
        given an unhashable value as well as a wrong-scalar one. An earlier
        version of this case listed fourteen payloads and never varied ``kind``,
        which is the one field that reaches a ``frozenset``; it passed while the
        unhashable ``kind`` crashed the run.
        """
        unhashable = (["repo"], {"kind": "repo"})
        malformed = [
            response(evidence="db/engine.py"),
            response(evidence=12),
            response(evidence={"kind": "repo"}),
            response(evidence=["db/engine.py"]),
            response(evidence=[None]),
            response(evidence=[{"kind": "repo", "path": 12, "line": 1,
                                "quote": "PostgresEngine"}]),
            response(evidence=[{"kind": "repo", "path": ["db/engine.py"],
                                "line": 1, "quote": "PostgresEngine"}]),
            response(evidence=[{"kind": "repo", "path": CITED_PATH, "line": 1,
                                "quote": 12}]),
            response(evidence=[{"kind": "repo", "path": CITED_PATH, "line": 1,
                                "quote": ["PostgresEngine"]}]),
            response(evidence=[{"kind": "repo", "path": CITED_PATH,
                                "line": "1", "quote": "PostgresEngine"}]),
            response(evidence=[{"kind": "repo", "path": CITED_PATH,
                                "line": [1], "quote": "PostgresEngine"}]),
            response(evidence=[{"kind": "decision", "path": "decisions.md",
                                "decision": 12, "quote": "postgres"}]),
            response(evidence=[{"kind": "decision", "path": "decisions.md",
                                "decision": ["H-001"], "quote": "postgres"}]),
            response(alternatives="sqlite"),
            response(alternatives=12),
            response(alternatives=["sqlite"]),
            response(alternatives=[None]),
            response(alternatives=[{"answer_key": "sqlite",
                                    "rung": ["code-evidenced"]}]),
            response(consistent_with="H-001"),
            response(consistent_with=12),
            response(consistent_with=["H-001"]),
            response(consistent_with=[None]),
            response(what_would_change_my_mind=None),
            response(what_would_change_my_mind=["a decision"]),
            response(what_would_change_my_mind={"if": "a decision"}),
        ]
        #: ``kind`` in BOTH places it is tested for membership, as an array and
        #: as an object. The evidence item RESOLVES — ``_evidence_resolves``
        #: compares ``kind`` with ``==``, which is safe for any type — so the
        #: unhashable value really does reach the ``frozenset``.
        for value in unhashable:
            malformed.append(response(evidence=[
                {"kind": value, "path": CITED_PATH, "line": 1,
                 "quote": "PostgresEngine"}]))
            #: ``speculation`` needs no evidence at all, so its qualifying
            #: count is compared against zero — and the membership test is
            #: still evaluated on the way there.
            malformed.append(response(rung="speculation", evidence=[
                {"kind": value, "path": CITED_PATH, "line": 1,
                 "quote": "PostgresEngine"}]))
            malformed.append(response(
                consistent_with=[{"kind": value, "id": "H-001"}]))
        for payload in malformed:
            with self.subTest(payload=payload):
                try:
                    outcome = self.rung(payload)
                except pas.TrackerError:
                    continue
                self.assertIn(outcome, pas.RUNGS)

    def test_a_response_that_is_not_an_object_is_schema_invalid(self):
        for payload in (None, 12, "code-evidenced", ["code-evidenced"]):
            with self.subTest(payload=payload):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    self.rung(payload)


def fixture_columns() -> dict[str, tuple[str, ...]]:
    """``{markdown heading: ordered dict keys}``, read out of the committed
    fixture's own header rows with nothing from the module.

    Keyed by HEADING rather than by tracker key, because the two are not one
    rename apart — ``## Stage`` is ``stages`` — and inventing the pairing here
    would test the invention. The pairing comes from ``pas._SECTIONS`` at the
    call sites; the COLUMNS, which are what a stale tuple gets wrong, come from
    the fixture. A tracker key that drifted would take ``parse_tracker`` down on
    the fixture long before it reached here.

    ``SECTION_HEADERS`` above is built FROM ``pas._SECTIONS``, which makes it
    the right tool for addressing a cell and the wrong one for judging the
    public column grammar: a stale tuple inside the module would be compared
    with itself and agree. The phase plans name the committed fixture as the
    authority on the column contract in as many words, so the expectation here
    is read from its bytes and the header-to-key mapping is spelled out again
    rather than imported.
    """
    columns: dict[str, tuple[str, ...]] = {}
    heading: str | None = None
    for line in valid_text().splitlines():
        if line.startswith("## "):
            heading = line
        elif heading is not None and heading not in columns and line.startswith("|"):
            columns[heading] = tuple(
                cell.strip().lower().replace(" ", "_").replace("-", "_")
                for cell in line[1:-1].split("|"))
    #: ``## Run`` is a two-column key/value table, not a row table. Its "columns"
    #: are the literal words ``Field`` and ``Value``, which are not a grammar any
    #: caller appends against.
    del columns["## Run"]
    return columns


class SectionColumnGrammarTests(unittest.TestCase):
    """``SECTIONS`` and ``section_columns`` are the one place a section's shape
    is written down.

    The master plan gives P02 every section's column grammar, *including*
    sections whose rows later phases write, and tells P03 through P06 to build
    their rows against ``section_columns`` rather than a local tuple. The reason
    is a defect this build has already paid for three times: a column tuple
    copied into a caller and then one column short of the real thing. A copy
    that is merely stale does not raise — it writes a row of the wrong width, or
    the right width with a cell shifted, and the tracker goes on parsing.

    So these cases measure the accessor against the committed fixture, never
    against ``pas._SECTIONS``, which is the thing that would be stale.
    """

    def test_sections_maps_every_row_section_to_the_fixtures_own_columns(self):
        expected = fixture_columns()
        self.assertEqual(
            {key: expected[heading] for heading, key, _ in pas._SECTIONS[1:]},
            dict(pas.SECTIONS))
        self.assertEqual(len(pas.SECTIONS), len(expected))

    def test_section_columns_answers_with_what_sections_holds(self):
        for name, columns in pas.SECTIONS.items():
            with self.subTest(section=name):
                self.assertEqual(pas.section_columns(name), columns)

    def test_every_fixture_row_carries_exactly_those_keys_in_that_order(self):
        """The accessor and the parser have to agree, or a row built against
        ``section_columns`` renders a cell under the wrong header."""
        tracker = pas.parse_tracker(valid_text())
        for name in pas.SECTIONS:
            for index, row in enumerate(tracker[name]):
                with self.subTest(section=name, row=index):
                    self.assertEqual(tuple(row), pas.section_columns(name))

    def test_an_unknown_section_name_raises_rather_than_answering_empty(self):
        """An empty tuple is the dangerous answer: a caller zipping values
        against it builds an empty row and appends it without complaint."""
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.section_columns("quorums")
        self.assertIn("quorums", str(caught.exception))

    def test_the_run_section_is_refused_by_name_rather_than_absent_silently(self):
        """``## Run`` is a key/value table. A caller that asks it for columns has
        made a category mistake and is told which one, not handed a KeyError
        from outside this module's exception family."""
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.section_columns("run")
        self.assertIn("run", str(caught.exception))

    def test_the_column_grammar_is_frozen_at_the_language_level(self):
        """Five phases read this mapping. One of them editing it re-shapes
        another phase's validation with nothing raised anywhere."""
        with self.assertRaises(TypeError):
            pas.SECTIONS["quorum"] = ()
        with self.assertRaises(TypeError):
            del pas.SECTIONS["quorum"]
        self.assertIsInstance(pas.SECTIONS, types.MappingProxyType)

    def test_no_module_attribute_is_a_live_handle_on_the_column_grammar(self):
        """A ``mappingproxy`` is a read-only VIEW, not a copy: a proxy over a
        named module-level dict is editable by anything that can reach the name,
        and the freeze above would be cosmetic. Same lesson as ``RUNGS``."""
        for name, value in sorted(vars(pas).items()):
            if not isinstance(value, dict) or set(pas.SECTIONS) - set(value):
                continue
            with self.subTest(attribute=name):
                original = value["quorum"]
                value["quorum"] = ()
                try:
                    self.assertNotEqual(
                        pas.SECTIONS["quorum"], (),
                        f"pipeline_auto_state.{name} is a live handle on "
                        "SECTIONS' own storage; the freeze is cosmetic")
                finally:
                    value["quorum"] = original


NEW_ESCALATION = {
    "id": "E-3", "qid": "-", "blast": "task", "state": "queued",
    "batch": "-", "resolution": "-",
}


class AppendRowTests(unittest.TestCase):
    """``append_row`` is the only sanctioned way a later phase adds a row.

    It exists to refuse the row a hand-built dict produces when its author
    worked from a copy of the column list: the right number of keys, one of them
    named something the section has never had. That row is the dangerous one —
    ``render_tracker`` reads cells by name, so a mistyped key surfaces as a
    ``KeyError`` from deep inside the renderer if it surfaces at all, and the
    missing column is reported instead of the invented one.

    It mutates a tracker dict and writes nothing. ``locked_tracker_update``
    stays the sole writer of ``progress.md``; this is what a ``mutate`` callable
    uses inside it.
    """

    def tracker(self) -> dict:
        return pas.parse_tracker(valid_text())

    def test_a_row_appended_to_a_section_survives_a_full_round_trip(self):
        """The positive control every refusal below is measured against."""
        tracker = self.tracker()
        before = len(tracker["escalations"])
        pas.append_row(tracker, "escalations", dict(NEW_ESCALATION))
        settled = pas.parse_tracker(pas.render_tracker(tracker))
        self.assertEqual(len(settled["escalations"]), before + 1)
        self.assertEqual(settled["escalations"][-1], NEW_ESCALATION)

    def test_the_tracker_handed_in_is_the_tracker_returned(self):
        """``mutate`` has to return what it edited, so ``append_row`` composes
        as one: ``mutate=lambda t: append_row(t, ...)``."""
        tracker = self.tracker()
        self.assertIs(
            pas.append_row(tracker, "escalations", dict(NEW_ESCALATION)), tracker)

    def test_a_key_of_the_right_arity_but_the_wrong_name_is_refused(self):
        """The whole reason this function exists.

        Six keys where six are wanted, one of them spelled for a column the
        section does not have. Counting would accept it; so would ``zip``. The
        invented name has to be named back, because "a row is wrong" sends its
        author to re-read all six.
        """
        for section, row, wrong, right in (
            ("escalations", dict(NEW_ESCALATION), "blasts", "blast"),
            ("quorum", dict(self.tracker()["quorum"][0]), "rungs", "rung"),
        ):
            with self.subTest(section=section, wrong=wrong):
                row[wrong] = row.pop(right)
                self.assertEqual(len(row), len(pas.section_columns(section)))
                tracker = self.tracker()
                before = list(tracker[section])
                with self.assertRaises(pas.TrackerValidationError) as caught:
                    pas.append_row(tracker, section, row)
                message = str(caught.exception)
                self.assertIn(wrong, message)
                self.assertIn(right, message)
                self.assertEqual(tracker[section], before,
                                 "a refused row still reached the section")

    def test_a_missing_column_is_named(self):
        row = dict(NEW_ESCALATION)
        del row["resolution"]
        tracker = self.tracker()
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.append_row(tracker, "escalations", row)
        self.assertIn("resolution", str(caught.exception))

    def test_an_extra_column_is_named(self):
        row = dict(NEW_ESCALATION)
        row["severity"] = "critical"
        tracker = self.tracker()
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.append_row(tracker, "escalations", row)
        self.assertIn("severity", str(caught.exception))

    def test_an_unknown_section_is_refused_by_name(self):
        tracker = self.tracker()
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.append_row(tracker, "escalationz", dict(NEW_ESCALATION))
        self.assertIn("escalationz", str(caught.exception))

    def test_the_run_section_cannot_be_appended_to(self):
        tracker = self.tracker()
        with self.assertRaises(pas.TrackerValidationError):
            pas.append_row(tracker, "run", dict(NEW_ESCALATION))
        self.assertEqual(tracker["run"], self.tracker()["run"])

    def test_every_section_accepts_a_row_built_from_its_own_columns(self):
        """Generic over all ten row sections, so a section added to the grammar
        without a place to append to it fails here rather than in the phase that
        first tries."""
        for name in pas.SECTIONS:
            with self.subTest(section=name):
                tracker = self.tracker()
                row = {column: "-" for column in pas.section_columns(name)}
                pas.append_row(tracker, name, row)
                self.assertEqual(tracker[name][-1], row)

    def test_the_stored_row_is_keyed_in_the_sections_own_column_order(self):
        """So ``tuple(row)`` reads the same for an appended row as for a parsed
        one — the invariant ``SectionColumnGrammarTests`` asserts of the fixture.

        Handed a row in a different order, and the cells asserted as well as
        the keys: reordering by ``zip`` over the row's VALUES produces exactly
        the right key order with every cell under the wrong one.
        """
        tracker = self.tracker()
        shuffled = dict(reversed(list(NEW_ESCALATION.items())))
        pas.append_row(tracker, "escalations", shuffled)
        stored = tracker["escalations"][-1]
        self.assertEqual(tuple(stored), pas.section_columns("escalations"))
        self.assertEqual(stored, NEW_ESCALATION)

    def test_append_row_touches_no_file(self):
        """``locked_tracker_update`` is the sole writer of ``progress.md``. A
        row appender that wrote would be a second one."""
        self.assertEqual(write_capable_calls(module_source(), "append_row"), [])


#: One synthetic ``/proc/self/mountinfo``. Four mounts, chosen for what each
#: proves: a root to fall back to, a deeper mount that must win over it, a mount
#: point carrying an octal-escaped space, and an unlisted type.
MOUNTINFO = (
    "23 28 0:21 / / rw,relatime shared:1 - ext4 /dev/root rw\n"
    "31 23 0:29 / /srv rw,relatime - nfs4 fileserver:/export rw\n"
    "35 23 0:30 / /srv/local\\040copy rw,relatime - xfs /dev/sdb1 rw\n"
    "37 23 0:31 / /mnt/experimental rw,relatime - bcachefs /dev/sdc1 rw\n"
)


class FilesystemClassificationTests(unittest.TestCase):
    """The classifier behind the spec's read-only stop.

    The lock is POSIX advisory locking and the tracker write is a
    same-directory ``os.replace``. Both are filesystem semantics, and several
    network filesystems honour neither. Starting a run on one does not fail: it
    succeeds while the sole-writer guarantee and the three write outcomes are
    quietly false. So an unsupported or unclassifiable filesystem is a stop
    before the run starts, not a warning during it — there is no human mid-run
    to authorise proceeding, which is why `superb:pipeline`'s acknowledgement
    plumbing has no counterpart here.

    **What these cases cover and what they cannot.** The classification logic is
    exercised against constructed ``mountinfo`` text and constructed type names,
    which is portable and is where the decisions actually live. What runs only
    on this machine is the probe itself: the Linux branch is executed for real
    exactly once below, and asserted only to return one of the three
    classifications. The macOS and Windows branches are reached here by naming
    the platform, never by running on it.
    """

    def test_a_known_local_type_is_supported(self):
        for fs_type in ("ext4", "xfs", "btrfs", "zfs", "apfs", "tmpfs", "overlay"):
            with self.subTest(fs_type=fs_type):
                self.assertEqual(pas._classify_fs_type(fs_type),
                                 pas.FILESYSTEM_SUPPORTED)

    def test_a_known_network_type_is_unsupported_and_says_so_distinctly(self):
        for fs_type in ("nfs", "nfs4", "cifs", "smbfs", "9p", "fuse.sshfs",
                        "ceph", "glusterfs", "lustre"):
            with self.subTest(fs_type=fs_type):
                self.assertEqual(pas._classify_fs_type(fs_type),
                                 pas.FILESYSTEM_UNSUPPORTED)

    def test_a_type_in_neither_list_is_unknown_rather_than_assumed_local(self):
        """The dangerous default is "probably fine". A type nobody has judged
        is one nobody has judged."""
        for fs_type in ("bcachefs", "exfat", "probe-failed", ""):
            with self.subTest(fs_type=fs_type):
                self.assertEqual(pas._classify_fs_type(fs_type),
                                 pas.FILESYSTEM_UNKNOWN)

    def test_the_three_classifications_are_distinct(self):
        self.assertEqual(len(set(pas.FILESYSTEM_CLASSES)), 3)
        self.assertEqual(
            set(pas.FILESYSTEM_CLASSES),
            {pas.FILESYSTEM_SUPPORTED, pas.FILESYSTEM_UNSUPPORTED,
             pas.FILESYSTEM_UNKNOWN})

    def test_a_type_name_is_matched_case_insensitively(self):
        self.assertEqual(pas._classify_fs_type("NFS4"), pas.FILESYSTEM_UNSUPPORTED)
        self.assertEqual(pas._classify_fs_type("EXT4"), pas.FILESYSTEM_SUPPORTED)

    def test_the_deepest_mount_containing_the_path_wins(self):
        """A run directory under ``/srv/...`` is on ``nfs4`` even though ``/``
        is ``ext4``. Taking the first match, or the root, reports the safe answer
        for the unsafe mount."""
        self.assertEqual(
            pas._mountinfo_fs_type(MOUNTINFO, Path("/srv/checkouts/repo/run")),
            "nfs4")
        self.assertEqual(
            pas._mountinfo_fs_type(MOUNTINFO, Path("/var/tmp/run")), "ext4")

    def test_a_mount_point_is_read_through_its_octal_escapes(self):
        """``mountinfo`` writes a space as ``\\040``. Compared raw, the deeper
        mount never matches and the run is judged against ``/``."""
        self.assertEqual(
            pas._mountinfo_fs_type(MOUNTINFO, Path("/srv/local copy/run")), "xfs")

    def test_a_path_on_no_listed_mount_is_a_probe_failure(self):
        with self.assertRaises(pas.FilesystemSuitabilityError):
            pas._mountinfo_fs_type("garbage\n", Path("/srv/run"))

    def test_an_unparsable_mountinfo_line_is_skipped_not_believed(self):
        self.assertEqual(
            pas._mountinfo_fs_type("not a mount line\n" + MOUNTINFO, Path("/x")),
            "ext4")

    def test_a_platform_with_no_probe_classifies_as_unknown(self):
        """macOS needs ``subprocess`` plus ``plistlib`` and Windows needs
        ``ctypes`` to answer this question; none of the three is in
        ``ALLOWED_IMPORTS`` and each is a real capability widening. Unprobed is
        therefore genuinely unknown, and unknown is the stop."""
        for system in ("darwin", "windows", "sunos"):
            with self.subTest(system=system):
                with mock.patch.object(pas, "_system_name", lambda: system):
                    self.assertEqual(pas.classify_filesystem(Path(__file__)),
                                     pas.FILESYSTEM_UNKNOWN)

    def test_classifying_a_real_path_answers_with_one_of_the_three(self):
        """The only case that touches this machine's actual filesystem, and it
        asserts nothing about which one this machine has."""
        self.assertIn(pas.classify_filesystem(Path(__file__).parent),
                      pas.FILESYSTEM_CLASSES)

    def test_a_path_that_does_not_exist_yet_is_classified_by_its_nearest_parent(self):
        """A run directory is classified BEFORE it is created, so the answer has
        to come from the deepest ancestor that does exist."""
        root = Path(tempfile.mkdtemp(prefix="pipeline-auto-fs-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.assertEqual(pas.classify_filesystem(root / "run" / "deeper"),
                         pas.classify_filesystem(root))

    def test_a_failed_probe_is_unknown_rather_than_assumed_supported(self):
        """"The probe broke" is not evidence about the filesystem.

        Read as "carry on", it is worse than having no check at all: the run
        starts on whatever it started on, and the classification cell says the
        mount was examined and approved.
        """
        for failure in (pas.FilesystemSuitabilityError("no mount entry"),
                        OSError("/proc/self/mountinfo is not readable")):
            with self.subTest(failure=type(failure).__name__):
                with mock.patch.object(pas, "_system_name", lambda: "linux"), \
                        mock.patch.object(pas, "_mountinfo_fs_type",
                                          side_effect=failure):
                    self.assertEqual(pas.classify_filesystem(Path(__file__)),
                                     pas.FILESYSTEM_UNKNOWN)

    def test_classify_filesystem_touches_no_file(self):
        self.assertEqual(write_capable_calls(module_source(), "classify_filesystem"), [])

    def test_the_suitability_stop_is_its_own_error_in_the_one_family(self):
        """It is not a write failure. A caller that retried it — which is the
        right response to ``TrackerWriteError`` — would retry forever."""
        self.assertTrue(issubclass(pas.FilesystemSuitabilityError, pas.TrackerError))
        self.assertFalse(issubclass(pas.FilesystemSuitabilityError,
                                    pas.TrackerWriteError))
        self.assertFalse(issubclass(pas.FilesystemSuitabilityError,
                                    pas.UpdateOutcomeUncertain))


class FilesystemStopBeforeTheRunStartsTests(unittest.TestCase):
    """Where the spec puts the stop: before a run starts.

    ``initialize_run`` is the one function that brings a run into existence, so
    it is the one place a refusal costs nothing and prevents everything. A check
    at the first transition instead would leave a tracker on disk for a run that
    was never allowed to begin, and a controller resuming it would read a valid
    tracker and carry on.
    """

    def refused(self, classification: str):
        run_dir = unborn_run(self)
        with mock.patch.object(pas, "classify_filesystem",
                               lambda path: classification):
            with self.assertRaises(pas.FilesystemSuitabilityError) as caught:
                pas.initialize_run(run_dir, **NEW_RUN)
        self.assertFalse((run_dir / "progress.md").exists(),
                         "a refused initialization still left a tracker on disk")
        self.assertFalse(run_dir.exists(),
                         "a refused initialization still created the run directory")
        return caught.exception

    def test_an_unsupported_filesystem_stops_the_run_before_it_starts(self):
        self.assertIn("unsupported", str(self.refused(pas.FILESYSTEM_UNSUPPORTED)))

    def test_an_unclassified_filesystem_stops_the_run_before_it_starts(self):
        """The spec makes this a halt rather than a warning, and explicitly not
        a quorum call: three brains know no more about the filesystem than the
        classifier does."""
        self.assertIn("unknown", str(self.refused(pas.FILESYSTEM_UNKNOWN)))

    def test_the_stop_fires_through_the_real_classifier_not_only_a_stub(self):
        """Wiring, end to end: name a platform this module cannot probe and the
        run must refuse to start, with nothing stubbed between them."""
        run_dir = unborn_run(self)
        with mock.patch.object(pas, "_system_name", lambda: "darwin"):
            with self.assertRaises(pas.FilesystemSuitabilityError):
                pas.initialize_run(run_dir, **NEW_RUN)
        self.assertFalse(run_dir.exists())

    def test_a_supported_filesystem_starts_the_run(self):
        """The positive control. Without it both cases above would pass against
        an ``initialize_run`` that refused everything."""
        run_dir, tracker = new_run(self)
        self.assertTrue((run_dir / "progress.md").exists())
        self.assertEqual(tracker["run"]["revision"], "0")

    def test_the_run_directory_is_classified_rather_than_the_repository(self):
        """The tracker, the lock and the atomic replace all live in the run
        directory. A repository on a local disk with its run directory on a
        network mount is the exact arrangement this must catch."""
        seen = []
        run_dir = unborn_run(self)

        def record(path):
            seen.append(Path(path))
            return pas.FILESYSTEM_SUPPORTED

        with mock.patch.object(pas, "classify_filesystem", record):
            pas.initialize_run(run_dir, **NEW_RUN)
        self.assertEqual(seen, [run_dir])


# --- the decisions contract ------------------------------------------------

#: One human decision, in the EMPHASISED field spelling this phase's record
#: grammar states. Every case below is this fixture with exactly one thing
#: changed, through ``swap``, so no case can be built on a pattern the fixture
#: no longer contains.
DECISION_HUMAN = """<!-- pipeline-auto-decisions/v1 -->

## H-001 — Session storage

- **Question:** Which storage engine backs the session table?
- **Axis:** storage-engine
- **Answer:** postgres — Use the existing PostgreSQL instance.
- **Decision action:** none
- **Provenance:** human
- **Depth:** 0
- **Consequences:** file-exists:db/session.sql=present
- **Scope:** T04
- **Status:** Adopted
"""

#: The SAME record in the plain spelling `templates/decisions.md` ships, which
#: also renames `Decision action` to `Action`. Derived from the emphasised
#: fixture rather than typed out, so the two cannot drift into being different
#: records and the equality assertion below stay true for the wrong reason.
DECISION_HUMAN_PLAIN = DECISION_HUMAN.replace("**", "").replace(
    "Decision action:", "Action:")

#: A second, quorum-provenance record on the SAME axis, agreeing with the first
#: in both its answer key and its consequences. This is the positive control
#: the contradiction stop needs: an implementation that refused every second
#: record on an axis would pass every rejection case below and stop every real
#: run on its first quorum adoption.
DECISION_QUORUM = """
## Q-abc123def456 — Session storage, confirmed by quorum

- **Question:** Which storage engine backs the session table?
- **Axis:** storage-engine
- **Answer:** postgres — Use the existing PostgreSQL instance.
- **Decision action:** quorum.adopt
- **Provenance:** quorum
- **Depth:** 1
- **Consistent with:** H-001
- **Consequences:** file-exists:db/session.sql=present
- **Scope:** T04
- **Status:** Adopted
"""

#: The same quorum record with its own `Supersedes` line, which is what
#: `templates/decisions.md` requires of the record performing the one legal
#: in-place mutation: `H-001` flips to `Superseded` and the record that replaces
#: it is appended NAMING it. A `Superseded` row with nothing superseding it
#: records a decision being withdrawn and not what took its place.
DECISION_SUPERSEDING = DECISION_QUORUM.replace(
    "- **Status:** Adopted", "- **Supersedes:** H-001\n- **Status:** Adopted")

#: A second adopted record on a DIFFERENT axis. The positive control for the
#: one-Adopted-per-axis rule: an implementation that refused every second
#: adopted record outright would satisfy that rule's rejection cases and stop
#: every real run the moment it decided two things.
DECISION_QUORUM_SECOND_AXIS = (
    DECISION_QUORUM
    .replace("- **Axis:** storage-engine", "- **Axis:** cache-layer")
    .replace("Which storage engine backs the session table?",
             "Which cache layer fronts the session table?")
    .replace("postgres — Use the existing PostgreSQL instance.",
             "redis — Use the existing Redis instance.")
    .replace("file-exists:db/session.sql=present",
             "file-exists:cache/redis.conf=present"))


#: The two PROJECTED free-text fields, and the exact strings they carry in the
#: fixture, so a content-screen case plants into the thing the projection
#: actually reads rather than into a field the whitelist already withholds.
#: Keyed by the record key the stop message capitalises.
PLANTED_IN = {
    "answer": "postgres — Use the existing PostgreSQL instance.",
    "question": "Which storage engine backs the session table?",
}

#: A three-generation succession: ``H-001`` retired by ``H-002``, itself retired
#: by the live ``H-003``. The positive control the cycle rule needs — a rule
#: that refused every chain longer than one step would satisfy both cycle cases
#: below and forbid the second time a run ever changes its mind. Each record is
#: on its own axis so the one-Adopted-per-axis rule is not what is under test.
def succession_chain() -> str:
    first = DECISION_HUMAN.replace("- **Status:** Adopted",
                                   "- **Status:** Superseded")
    second = (DECISION_HUMAN
              .replace("## H-001", "## H-002")
              .replace("<!-- pipeline-auto-decisions/v1 -->\n", "")
              .replace("- **Axis:** storage-engine", "- **Axis:** cache-layer")
              .replace("- **Status:** Adopted",
                       "- **Supersedes:** H-001\n- **Status:** Superseded"))
    third = (DECISION_HUMAN
             .replace("## H-001", "## H-003")
             .replace("<!-- pipeline-auto-decisions/v1 -->\n", "")
             .replace("- **Axis:** storage-engine", "- **Axis:** queue-broker")
             .replace("- **Status:** Adopted",
                      "- **Supersedes:** H-002\n- **Status:** Adopted"))
    return first + second + third


def retired_and_replaced() -> str:
    """``H-001`` retired, beside the record that retires it.

    Both halves, because the mutation is both halves: `templates/decisions.md`
    states that `Adopted -> Superseded` is performed by appending the
    superseding record with its own `Supersedes` line, so a lone `Superseded`
    record is no longer a parseable file and a fixture built out of one would be
    testing an illegal shape.
    """
    retired = DECISION_HUMAN.replace(
        "postgres — Use the existing PostgreSQL instance.",
        "sqlite — Ship a single-file database.").replace(
        "- **Status:** Adopted", "- **Status:** Superseded")
    return retired + DECISION_SUPERSEDING


#: The axis index a real `decisions.md` opens with, copied in shape from the
#: shipped template. It is a `##` heading that is not a decision, which is the
#: thing a reader treating every heading as a record gets wrong.
AXIS_INDEX = """
## Axis Index

| Axis | Decision | Provenance | Status |
| --- | --- | --- | --- |
| storage-engine | H-001 | human | Adopted |
"""

#: Values a field is varied with when the claim is TOTALITY. Both halves of the
#: standing rule are here: wrong-typed scalars a markdown cell can actually
#: carry (`0.85`, `True`, `٣`), the absence sentinel, the field separator the
#: record grammar uses, and the shapes that would derail a parser written with
#: `split` or `int` and no guard.
HOSTILE_DECISION_VALUES = (
    "", "   ", "-", "0.85", "True", "٣", "²", "1.0", "-1", "none", "null",
    "a: b", "**", "|", "\x00", "—", "— —", "a, b", "[1]", "{}", "x" * 300,
    "file-exists", "file-exists:", ":=", "H-001", "Adopted", "storage engine",
)


def findings_template() -> str:
    return (TEMPLATES / "findings.md").read_text(encoding="utf-8")


def decision_field_lines(text: str) -> list[str]:
    """Every line of ``text`` the module itself reads as a field.

    Enumerated through ``pas._decision_field`` rather than by eye, so a case
    list claiming to cover "every field" is derived from the parser's own call
    tree and cannot fall behind a field the fixture gains.
    """
    return [line for line in text.splitlines()
            if pas._decision_field(line) is not None]


def decision_fields_the_parser_reads() -> set[str]:
    """Every record field ``parse_decisions`` actually reads, from its own AST.

    FROM THE CALL TREE AND NOT FROM THE FIXTURE, which is the whole point. The
    previous version of this list came from ``decision_field_lines(
    DECISION_HUMAN)`` while claiming to be derived from the parser, and the two
    are not the same set: the parser read ``consistent_with``, the fixture never
    stated it, and the field went from unvaried to entirely unvalidated without
    anything noticing. A field the parser gains and the fixture omits must widen
    this list by itself, or the totality claim is a claim about a fixture.

    BOTH RECEIVERS, and that is the second half of the same lesson. The parser
    reads a field through the raw ``fields`` mapping while the record is being
    built -- ``fields["x"]``, ``fields.get("x", ...)`` -- and through the
    already-built record afterwards, ``decisions[did].get("supersedes", "")``.
    The first version of this walk matched only the ``fields`` receiver, so the
    ``Supersedes`` validator's field was invisible to it and ``supersedes``
    dropped out of a set whose docstring claimed to be the call tree's: the
    MINOR-4 defect, reintroduced by the change that closed MINOR 4.
    ``_REQUIRED_DECISION_FIELDS`` is unioned in on top, because the parser
    iterates it through a loop variable no literal scan can see.
    """
    def reads_a_record(node) -> bool:
        """The two receivers a decision field is read through."""
        if isinstance(node, ast.Name) and node.id == "fields":
            return True
        return (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "decisions")

    node = function_node(module_source(), "parse_decisions")
    names = set(pas._REQUIRED_DECISION_FIELDS)
    for child in ast.walk(node):
        if (isinstance(child, ast.Subscript)
                and reads_a_record(child.value)
                and isinstance(child.slice, ast.Constant)
                and isinstance(child.slice.value, str)):
            names.add(child.slice.value)
        if (isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "get"
                and reads_a_record(child.func.value)
                and child.args
                and isinstance(child.args[0], ast.Constant)
                and isinstance(child.args[0].value, str)):
            names.add(child.args[0].value)
    return names


def decision_field_label(key: str) -> str:
    """The record label a field key is written with: ``consistent_with`` ->
    ``Consistent with``. Asserted to round-trip through ``_decision_field``
    wherever it is used, so a key whose label this guesses wrong is caught
    rather than silently varied under a name the parser never reads.
    """
    return key.replace("_", " ").capitalize()


class DecisionContractCase(unittest.TestCase):
    """Shared assertions for the two halves of the decisions contract."""

    def refused(self, text: str, *, because: str = ""):
        """``parse_decisions`` stops read-only, naming what it refused."""
        with self.assertRaises(pas.TrackerValidationError) as raised:
            pas.parse_decisions(text)
        if because:
            self.assertIn(because.casefold(), str(raised.exception).casefold())
        return raised.exception

    def only_a_tracker_error(self, text: str):
        """Either a usable parse, or a stop inside this module's family.

        ``TypeError``, ``ValueError``, ``KeyError``, ``AttributeError`` and
        ``IndexError`` from a malformed audit trail are defects, not acceptable
        behaviour: each is outside ``TrackerError``, so it escapes every
        ``except TrackerError`` a controller has written and kills the run on a
        typo in a file a human is invited to edit.
        """
        try:
            parsed = pas.parse_decisions(text)
        except pas.TrackerError:
            return None
        except Exception as escaped:          # noqa: BLE001 - that is the claim
            raise AssertionError(
                f"{type(escaped).__name__}({escaped}) escaped parse_decisions; "
                "nothing outside TrackerError may leave this module") from escaped
        self.assertIsInstance(parsed, dict)
        try:
            pas.project_decisions(parsed)
        except pas.TrackerError:
            return parsed
        except Exception as escaped:          # noqa: BLE001
            raise AssertionError(
                f"{type(escaped).__name__}({escaped}) escaped project_decisions "
                "on a record parse_decisions had accepted") from escaped
        return parsed


class ParseDecisionsTests(DecisionContractCase):
    """``decisions.md`` is the run's audit trail, read strictly.

    Two adopted decisions contradicting each other on one axis is a read-only
    stop of the same severity as a foreign schema: every later reader — the
    contradiction check, the depth walk, the terminal report — would pick one
    of the two by accident of iteration order, and every pick is defensible, so
    nothing downstream could detect it.

    The rejection cases are each paired with a case that must still be
    ACCEPTED. A parser that refused everything would satisfy every stop in this
    class and stop every real run on its first decision.
    """

    def test_parses_records_and_builds_the_axis_index(self):
        parsed = pas.parse_decisions(DECISION_HUMAN)
        self.assertEqual(parsed["decisions"]["H-001"]["provenance"], "human")
        self.assertEqual(parsed["decisions"]["H-001"]["answer_key"], "postgres")
        self.assertEqual(parsed["decisions"]["H-001"]["depth"], 0)
        self.assertEqual(parsed["decisions"]["H-001"]["status"], "Adopted")
        self.assertEqual(parsed["decisions"]["H-001"]["action"], "none")
        self.assertEqual(
            parsed["decisions"]["H-001"]["consequences"],
            {("file-exists", "db/session.sql"): "present"})
        self.assertEqual(parsed["axis_index"]["storage-engine"], ["H-001"])

    def test_the_plain_spelling_the_shipped_template_teaches_parses_identically(self):
        """The template in this repository writes ``- Provenance: human`` and
        ``- Action:``; this phase's record grammar writes ``- **Provenance:**``
        and ``- **Decision action:**``. Both are already committed, so a parser
        that took only one of them would read a file copied from the shipped
        template as a file with no fields at all — every record missing every
        required field, and an ordinary run a read-only stop on its first
        decision.

        The fixture property is asserted here rather than assumed: if the
        template stopped using the plain spelling this test would be comparing
        two copies of the same grammar and would pass while proving nothing.
        """
        template = decisions_template()
        self.assertIn("- Provenance: human", template)
        self.assertIn("- Action: ", template)
        self.assertNotIn("- **Provenance:**", template)
        self.assertIn("- Provenance: human", DECISION_HUMAN_PLAIN)
        self.assertIn("- Action: none", DECISION_HUMAN_PLAIN)
        self.assertEqual(pas.parse_decisions(DECISION_HUMAN_PLAIN),
                         pas.parse_decisions(DECISION_HUMAN))

    def test_missing_provenance_is_invalid(self):
        self.refused(swap("- **Provenance:** human\n", "", DECISION_HUMAN),
                     because="provenance")

    def test_provenance_must_agree_with_the_id_prefix(self):
        """Provenance is recorded twice — in the id and in the field — so that
        it survives one of the two being lost, not so that a record can claim
        both. Routing reads the prefix: a finding tracing to a human decision
        halts to the escalation queue, one tracing to a quorum decision re-opens
        that qid.
        """
        self.refused(swap("Provenance:** human", "Provenance:** quorum",
                          DECISION_HUMAN), because="prefix")
        self.refused(swap("## H-001 —", "## Q-abc123def456 —", DECISION_HUMAN),
                     because="prefix")

    def test_both_namespaces_are_accepted_with_their_own_provenance(self):
        """Over the retired pair rather than two adopted records, because an
        axis holds at most one Adopted decision. The axis index still groups
        both ids on the one axis — the superseded record keeps its row.
        """
        parsed = pas.parse_decisions(retired_and_replaced())
        self.assertEqual(parsed["decisions"]["Q-abc123def456"]["provenance"],
                         "quorum")
        self.assertEqual(parsed["decisions"]["H-001"]["provenance"], "human")
        self.assertEqual(parsed["axis_index"]["storage-engine"],
                         ["H-001", "Q-abc123def456"])

    def test_a_heading_outside_both_namespaces_is_refused_not_skipped(self):
        """A record whose id is mistyped must not vanish. ``H-01x`` starts with
        ``H-`` and is not a decision id — ``_validate_tasks`` refuses it in a
        task's ``Decisions`` cell — so a parser matching on the prefix alone
        would accept a decision no task in the run can ever cite, and one that
        silently skipped unknown headings would drop a record out of an
        append-only file without a word.
        """
        for heading in ("## H-01x — Session storage", "## h-001 — Session storage",
                        "## Q-ABC123DEF456 — Session storage",
                        "## Q-abc123 — Session storage", "## Session storage",
                        "## "):
            with self.subTest(heading=heading):
                self.refused(swap("## H-001 — Session storage", heading,
                                  DECISION_HUMAN), because="decision id")

    def test_the_axis_index_a_real_file_opens_with_is_not_read_as_a_decision(self):
        """A real ``decisions.md`` opens with prose and an ``## Axis Index``
        table. A reader treating every heading as a record reports the axis
        index as a decision missing every field, which stops a healthy run.
        """
        self.assertIn("## Axis Index", decisions_template())
        parsed = pas.parse_decisions(AXIS_INDEX + DECISION_HUMAN)
        self.assertEqual(list(parsed["decisions"]), ["H-001"])

    def test_two_adopted_contradicting_answers_on_one_axis_are_a_read_only_stop(self):
        clash = DECISION_HUMAN + swap(
            "Answer:** postgres — Use the existing PostgreSQL instance.",
            "Answer:** sqlite — Ship a single-file database.", DECISION_QUORUM)
        message = str(self.refused(clash, because="read-only stop"))
        self.assertIn("H-001", message)
        self.assertIn("Q-abc123def456", message)
        #: The REASON, not a boolean rendered as one. "these two contradict"
        #: sends a human to read both records and guess, and the guess is
        #: between an answer key and a consequence. Reducing `_contradiction`'s
        #: answer-key branch to a bare "differ" fails here.
        self.assertIn("answer keys", message)
        self.assertIn("'postgres'", message)
        self.assertIn("'sqlite'", message)

    def test_the_contradiction_reason_distinguishes_its_two_branches(self):
        """``_contradiction`` returns the reason and never a bool, and BOTH of
        its branches are pinned. The consequence branch was already exercised
        through the stop message; the answer-key branch was not, so half of
        "returns the reason, not a bool" was unproven and a bare ``"differ"``
        survived.
        """
        left = pas.parse_decisions(DECISION_HUMAN)["decisions"]["H-001"]
        right = dict(left, id="Q-abc123def456",
                     answer_key="sqlite", answer="sqlite — one file")
        self.assertEqual(pas._contradiction(left, right),
                         "answer keys 'postgres' and 'sqlite' differ")
        self.assertIsNone(pas._contradiction(left, dict(left, id="Q-abc123def456")))
        same_key = dict(left, id="Q-abc123def456",
                        consequences={("file-exists", "db/session.sql"): "absent"})
        self.assertEqual(pas._contradiction(left, same_key),
                         "file-exists:db/session.sql is asserted 'present' and "
                         "'absent'")

    def test_a_second_adopted_record_on_one_axis_is_refused_even_when_it_agrees(self):
        """``templates/decisions.md`` line 63: "an axis holds at most one
        ``Adopted`` decision". This test previously asserted the OPPOSITE — that
        two adopted records agreeing on one axis are accepted — and that reading
        is overruled by the same authority that settled the three field-grammar
        defects this contract was built from.

        Agreement today is not the point. The axis index has one ``Decision``
        column and can name only one of two records; every later reader picks by
        accident of iteration order; and the pair becomes a real contradiction
        the first time either is amended. The mutation that IS legal is
        supersession, which is pinned below.
        """
        message = str(self.refused(DECISION_HUMAN + DECISION_QUORUM,
                                   because="at most one"))
        self.assertIn("storage-engine", message)
        self.assertIn("H-001", message)
        self.assertIn("Q-abc123def456", message)

    def test_two_adopted_records_on_different_axes_are_accepted(self):
        """The positive control the rule above needs. An implementation that
        refused every second adopted record outright would satisfy that stop and
        stop a real run the moment it decided two things.
        """
        parsed = pas.parse_decisions(DECISION_HUMAN + DECISION_QUORUM_SECOND_AXIS)
        self.assertEqual(sorted(parsed["decisions"]), ["H-001", "Q-abc123def456"])
        self.assertEqual(sorted(parsed["axis_index"]),
                         ["cache-layer", "storage-engine"])

    def test_supersession_is_how_an_axis_takes_a_second_answer(self):
        """The constraint above binds the adoption path: a later adoption on an
        axis that already carries an Adopted record flips that record to
        ``Superseded`` and appends the new one naming it, and never appends a
        second Adopted record beside it.
        """
        parsed = pas.parse_decisions(retired_and_replaced())
        self.assertEqual(parsed["decisions"]["H-001"]["status"], "Superseded")
        self.assertEqual(parsed["decisions"]["Q-abc123def456"]["status"], "Adopted")
        self.assertEqual(parsed["decisions"]["Q-abc123def456"]["supersedes"],
                         "H-001")

    def test_consequences_that_contradict_stop_the_run_even_when_the_key_agrees(self):
        """Where the question supplied no named options, two answers are the
        same answer only if their consequences are mutually non-contradictory.
        Comparing answer keys alone passes a pair that names one thing and
        asserts opposite facts about the repository.
        """
        clash = DECISION_HUMAN + swap("file-exists:db/session.sql=present",
                                      "file-exists:db/session.sql=absent",
                                      DECISION_QUORUM)
        self.assertIn("db/session.sql", str(self.refused(clash)))

    def test_a_superseded_record_cannot_contradict_an_adopted_one(self):
        """The one legal in-place mutation is ``Adopted -> Superseded``, and the
        superseded record keeps its row. A stop that counted it would make that
        mutation unusable: every replacement decision would clash with the
        record it replaced, so the file could never record a change of mind.
        """
        parsed = pas.parse_decisions(retired_and_replaced())
        self.assertEqual(parsed["decisions"]["H-001"]["status"], "Superseded")
        self.assertEqual(parsed["decisions"]["Q-abc123def456"]["status"], "Adopted")
        self.assertEqual(parsed["decisions"]["H-001"]["answer_key"], "sqlite")

    def test_a_generic_approval_is_not_an_answer(self):
        """A generic approval is as empty from a quorum as from a human. The
        accepted case is stated beside them: a rule matching every answer would
        satisfy this list and refuse every real decision.
        """
        for empty in ("approved", "proceed", "continue", "yes", "ok", "Approved.",
                      "LGTM", "sounds good", "pending user response"):
            with self.subTest(answer=empty):
                self.refused(
                    swap("postgres — Use the existing PostgreSQL instance.",
                         empty, DECISION_HUMAN), because="generic approval")
        self.assertEqual(
            pas.parse_decisions(DECISION_HUMAN)["decisions"]["H-001"]["answer_key"],
            "postgres")

    def test_a_generic_answer_key_is_refused_however_much_prose_follows_it(self):
        """``answer_key`` is what clustering and contradiction compare. An
        answer of ``yes — because we already run it`` reads as reasoned and
        keys on ``yes``, which agrees with every other ``yes`` in the run.
        """
        self.refused(swap("postgres — Use the existing PostgreSQL instance.",
                          "yes — because we already run it", DECISION_HUMAN),
                     because="generic approval")

    def test_every_action_the_schema_honours_is_accepted_and_no_other(self):
        """The closed vocabulary, in BOTH directions and against the template.

        ``dispatch.extend-budget`` is in the set because two budgets mean two
        authorities: the drift budget caps decision authority and the dispatch
        budget caps run cost. Dropping it would make the one record that
        unblocks a hard-ceilinged run unparseable — the grant the human signed
        would read as an unknown action, which is a read-only stop, which is a
        run that cannot be restarted by the very grant that exists to restart
        it.
        """
        template = decisions_template()
        for action in sorted(pas._DECISION_ACTIONS):
            with self.subTest(action=action):
                self.assertIn(action, template)
                text = swap("Decision action:** none", f"Decision action:** {action}",
                            DECISION_HUMAN)
                parsed = pas.parse_decisions(text)
                self.assertEqual(parsed["decisions"]["H-001"]["action"], action)
        for foreign in ("remediation.start-round", "review.resolve-question",
                        "filesystem.authorize", "adopt", "", "None"):
            with self.subTest(foreign=foreign):
                self.refused(swap("Decision action:** none",
                                  f"Decision action:** {foreign}", DECISION_HUMAN),
                             because="decision")

    def test_a_budget_extension_is_never_grantable_by_quorum(self):
        for action in sorted(pas._EXTENSION_ACTIONS):
            with self.subTest(action=action):
                granted = swap("Decision action:** quorum.adopt",
                               f"Decision action:** {action}",
                               DECISION_HUMAN + DECISION_QUORUM)
                self.assertIn("Provenance: human", str(self.refused(granted)))
                #: The same action on the human record is accepted, so the rule
                #: is about provenance and not about the action's name.
                human = swap("Decision action:** none", f"Decision action:** {action}",
                             DECISION_HUMAN)
                self.assertEqual(
                    pas.parse_decisions(human)["decisions"]["H-001"]["action"],
                    action)

    def test_status_must_be_one_the_schema_spells(self):
        for status in ("Adopted", "adopted", "SUPERSEDED", "Open", "open"):
            with self.subTest(status=status):
                text = swap("Status:** Adopted", f"Status:** {status}", DECISION_HUMAN)
                if status.casefold() == "open":
                    text = swap("postgres — Use the existing PostgreSQL instance.",
                                "pending user response", text)
                if status.casefold() == "superseded":
                    #: A retirement needs the record that performs it; the
                    #: template makes the `Supersedes` line half of the one legal
                    #: in-place mutation.
                    text = text + DECISION_SUPERSEDING
                self.assertEqual(
                    pas.parse_decisions(text)["decisions"]["H-001"]["status"],
                    status.capitalize())
        for status in ("Closed", "Adopted!", "Accepted", "Rejected", "-", "Draft"):
            with self.subTest(status=status):
                self.refused(swap("Status:** Adopted", f"Status:** {status}",
                                  DECISION_HUMAN), because="Status")

    def test_an_unanswered_question_is_recorded_now_and_binds_nothing(self):
        """The shipped template requires the question be written down BEFORE it
        has an answer — a question recorded only once answered is a question the
        run can silently drop. So ``Open`` is a status this parser must accept,
        and it must bind nothing: two Open records on one axis are two questions
        pending, not two answers in conflict.
        """
        self.assertIn("pending user response", decisions_template())
        pending = swap("postgres — Use the existing PostgreSQL instance.",
                       "pending user response",
                       swap("Status:** Adopted", "Status:** Open", DECISION_HUMAN))
        second = swap("## H-001 —", "## H-002 —", pending)
        second = swap("Which storage engine backs the session table?",
                      "Which cache backs the session table?", second)
        parsed = pas.parse_decisions(pending + second)
        self.assertEqual(parsed["decisions"]["H-001"]["status"], "Open")
        self.assertEqual(sorted(parsed["decisions"]), ["H-001", "H-002"])

    def test_an_open_record_may_carry_neither_an_answer_nor_an_authority(self):
        opened = swap("Status:** Adopted", "Status:** Open", DECISION_HUMAN)
        self.refused(opened, because="pending user response")
        answered = swap("postgres — Use the existing PostgreSQL instance.",
                        "pending user response", opened)
        self.refused(swap("Decision action:** none",
                          "Decision action:** task.resume", answered),
                     because="'none'")

    def test_depth_is_an_ascii_integer_and_a_bad_one_is_never_a_valueerror(self):
        """``int('two')`` raises ``ValueError``, outside this module's family.
        ``isdigit`` alone is true of ``'٣'``, which ``int`` reads back as 3 —
        a depth no downstream reader can match, arriving through a check that
        looked like one.
        """
        for depth in ("two", "-1", "0.5", "٣", "²", "+1", " ", "-", "1 2"):
            with self.subTest(depth=depth):
                self.refused(swap("Depth:** 0", f"Depth:** {depth}",
                                  DECISION_HUMAN), because="Depth")
        self.assertEqual(
            pas.parse_decisions(swap("Depth:** 0", "Depth:** 2",
                                     swap("Provenance:** human", "Provenance:** quorum",
                                          swap("## H-001 —", "## Q-abc123def456 —",
                                               DECISION_HUMAN))),
            )["decisions"]["Q-abc123def456"]["depth"], 2)

    def test_a_human_decision_is_depth_zero(self):
        self.refused(swap("Depth:** 0", "Depth:** 1", DECISION_HUMAN),
                     because="depth 0")

    def test_a_missing_depth_is_not_read_as_zero(self):
        """Carried from Task 2: treating an absent anchor as depth 0 by accident
        would let a machine claim its answer stands exactly where a human's
        does, which is the one distance the depth cap exists to measure.
        """
        self.refused(swap("- **Depth:** 0\n", "", DECISION_HUMAN),
                     because="depth")

    def test_a_repeated_heading_is_refused_rather_than_overwritten(self):
        """A dict keyed by id lets the second ``## H-001`` overwrite the first:
        an append-only file losing a decision through the parser.
        """
        self.refused(DECISION_HUMAN + DECISION_HUMAN.split("\n\n", 1)[1],
                     because="two ## H-001")

    def test_a_field_stated_twice_is_refused_in_either_spelling(self):
        """Including the two spellings of one field. ``Action`` and ``Decision
        action`` are one field, so a record stating both states one field twice
        and nothing says which value every later reader will use.
        """
        self.refused(swap("- **Depth:** 0\n", "- **Depth:** 0\n- **Depth:** 1\n",
                          DECISION_HUMAN), because="twice")
        self.refused(swap("- **Decision action:** none\n",
                          "- **Decision action:** none\n- **Action:** quorum.adopt\n",
                          DECISION_HUMAN), because="twice")

    def test_a_consequence_that_asserts_nothing_about_the_repository(self):
        """A free-text consequence is the fail-open shape ``_BLAST_RADII`` is
        closed against: it matches no other record's consequences, so two
        adopted decisions that genuinely conflict are compared on an empty
        intersection and pass.
        """
        for broken in ("we should use postgres", "file-exists:db/session.sql",
                       "file-exists=present", ":db/session.sql=present",
                       "file-exists:=present", "file-exists:db/session.sql=",
                       "made-up:db/session.sql=present",
                       "file-exists:db/session.sql=present, "
                       "file-exists:db/session.sql=absent"):
            with self.subTest(consequences=broken):
                self.refused(swap("file-exists:db/session.sql=present", broken,
                                  DECISION_HUMAN), because="consequence")
        for good in ("file-exists:db/session.sql=present",
                     "signature:db.session.open=(url: str) -> Session",
                     "command-passes:pytest tests=true",
                     "config-value:app.storage=postgres",
                     "file-exists:db/a.sql=present, config-value:app.db=postgres"):
            with self.subTest(consequences=good):
                parsed = pas.parse_decisions(
                    swap("file-exists:db/session.sql=present", good, DECISION_HUMAN))
                self.assertTrue(parsed["decisions"]["H-001"]["consequences"])

    def test_the_reserved_axis_literal_is_not_an_axis(self):
        """``new`` is the reserved literal for a question not yet tagged to a
        stable axis. Two unrelated decisions recorded against it share one
        bucket, and the run stops on a contradiction that does not exist.
        """
        self.refused(swap("Axis:** storage-engine", f"Axis:** {pas._RESERVED_AXIS}",
                          DECISION_HUMAN), because="reserved literal")

    def test_an_axis_that_is_no_legal_token_is_refused(self):
        for axis in ("storage engine", "", "-", "!engine", "engine|two", "*"):
            with self.subTest(axis=axis):
                self.refused(swap("Axis:** storage-engine", f"Axis:** {axis}",
                                  DECISION_HUMAN), because="axis")

    def test_a_prose_bullet_inside_a_record_is_not_read_as_a_field(self):
        """The label guard — no ``*`` and no ``:`` inside a label — is what the
        parser's own docstring calls "what stops a prose bullet inside a record
        from being read as a field", and nothing demonstrated it. A record is a
        hand-edited markdown section: a writer explaining a decision in a bullet
        underneath it is the ordinary case, not the exotic one.
        """
        for prose in ("- Use **postgres** for now: it is already running",
                      "- **Answer: postgres:** repeated in prose",
                      "- see db/session.sql **and** db/cache.sql: both exist"):
            with self.subTest(prose=prose):
                self.assertIsNone(pas._decision_field(prose))
        #: The positive controls, so the guard is a guard and not a ban.
        self.assertEqual(pas._decision_field("- **Answer:** postgres"),
                         ("answer", "postgres"))
        self.assertEqual(pas._decision_field("- Answer: postgres"),
                         ("answer", "postgres"))
        #: End to end: the prose bullet lands inside the record and the record
        #: parses with no field for it.
        parsed = pas.parse_decisions(swap(
            "- **Status:** Adopted",
            "- Use **postgres** for now: it is already running\n"
            "- **Status:** Adopted", DECISION_HUMAN))
        record = parsed["decisions"]["H-001"]
        self.assertNotIn("use_**postgres**_for_now", record)
        self.assertEqual(record["answer_key"], "postgres")

    def test_every_raw_field_is_carried_into_the_record(self):
        """A record is the computed keys PLUS every raw field, lowercased with
        spaces underscored — the contract P05 and P06 read it by. Nothing read
        the raw half, so ``record = dict(fields)`` could become ``record = {}``
        and the suite stayed green while ``scope``, ``rung`` and ``sources``
        vanished from every record in the run.
        """
        source = swap("- **Status:** Adopted",
                      "- **Rung:** -\n- **Sources:** spec.md:41\n"
                      "- **Grounding rung:** specified\n- **Status:** Adopted",
                      DECISION_HUMAN)
        record = pas.parse_decisions(source)["decisions"]["H-001"]
        self.assertEqual(record["scope"], "T04")
        self.assertEqual(record["rung"], "-")
        self.assertEqual(record["sources"], "spec.md:41")
        self.assertEqual(record["grounding_rung"], "specified")
        #: And the computed keys are still computed, so this is not satisfied by
        #: a record that is only its raw fields either.
        self.assertEqual(record["depth"], 0)
        self.assertEqual(record["answer_key"], "postgres")

    def test_a_provenance_outside_the_enum_names_the_two_legal_values(self):
        """The enum check cannot change accept/reject — by the time it runs,
        ``provenance_by_id`` is one of the two, so anything outside the enum is
        caught two lines later by the disagreement check regardless. It is kept
        for the MESSAGE, and the message is therefore pinned: "must be human or
        quorum" tells a writer what the vocabulary IS, where "id prefix says
        human and Provenance says banana" assumes both sides are legal and names
        neither. Deleting the branch fails here.
        """
        message = str(self.refused(
            swap("Provenance:** human", "Provenance:** banana", DECISION_HUMAN)))
        self.assertIn("human or quorum", message)
        self.assertNotIn("prefix", message)

    def test_a_refusal_is_a_real_answer_and_is_never_a_generic_approval(self):
        """``no`` is not a rubber stamp and must not be treated as one. A rubber
        stamp is always affirmative — it is the reflex of waving something
        through — and a refusal is the one thing a reflex never produces. "no"
        to "should we add a second datastore?" settles the axis, and refusing it
        would make a human's legitimate rejection of a yes/no question
        unwritable.
        """
        self.assertNotIn("no", pas._GENERIC_ANSWERS)
        for answer in ("no", "no — we will not add a second datastore",
                       "No.", "no, keep one datastore"):
            with self.subTest(answer=answer):
                parsed = pas.parse_decisions(
                    swap("postgres — Use the existing PostgreSQL instance.",
                         answer, DECISION_HUMAN))
                self.assertEqual(parsed["decisions"]["H-001"]["status"], "Adopted")
        #: The affirmative rubber stamps stay refused, so this is not a hole.
        for stamp in ("yes", "ok", "sure", "do it", "agreed"):
            with self.subTest(stamp=stamp):
                self.refused(swap("postgres — Use the existing PostgreSQL "
                                  "instance.", stamp, DECISION_HUMAN),
                             because="generic approval")

    def test_go_is_a_language_and_not_a_rubber_stamp(self):
        """``go`` is removed for the same shape as ``no`` and a different reason.

        The generic-approval rule is applied to the derived ``answer_key`` as
        well as to the whole answer, which is what closed the hole where
        ``yes — because we already run it`` read as reasoned while keying on
        ``yes``. That same reach is what makes ``go`` dangerous: it is a
        language, so refusing it makes a legal adopted answer unrecordable.

        **``go`` and ``yes`` were BOTH inherited members**, which is why the
        difference has to be argued rather than asserted. The rule this one
        carries over from tests the WHOLE answer
        (``plugins/superb/skills/pipeline/scripts/pipeline_state.py:1926``) and
        contains ``go``. This module added the ``answer_key`` reach, and that
        reach is what turned "go — it compiles fast" from passing into refused.
        So every inherited member that could be a legitimate KEY needed
        re-examining under the new reach. ``go`` is the one that could, and
        removing it restores the inherited behaviour for that case rather than
        departing from it.

        ``yes`` has no such carrier, and the rule does not vary by provenance:
        the spec states the uniformity at lines 752-753 ("a quorum answer of
        ``proceed`` is as empty as a human's") and names ``yes`` as the reflex
        at line 427 ("the reflex answer to 'may I continue?' is yes"). An
        earlier version of this docstring argued it from the options test
        instead. That was the wrong reason for a right conclusion, and it is
        worth naming because it is the reason a reader would reach for again:
        a human gate question failing admissibility is dropped BEFORE the gate,
        so the options test governs human questions too, and a quorum question
        with no options tells the brain to answer in prose — so the two are not
        split the way they appear to be.
        """
        self.assertNotIn("go", pas._GENERIC_ANSWERS)
        for answer in ("go — it compiles fast and the team knows it",
                       "go", "Go."):
            with self.subTest(answer=answer):
                parsed = pas.parse_decisions(
                    swap("postgres — Use the existing PostgreSQL instance.",
                         answer, DECISION_HUMAN))
                self.assertEqual(parsed["decisions"]["H-001"]["status"], "Adopted")

    def test_an_anchor_that_names_no_decision_is_refused(self):
        """``Consistent with`` is read, split and carried into every record, and
        was validated by nothing: ``\x00``, ``|``, ``0.85``, an em dash and
        three hundred commas all parsed into a live anchor list. That is the
        Task-2 hazard verbatim — an anchor without an id lets a record claim
        grounding in a decision it never names.
        """
        def cited(anchors: str) -> str:
            return swap("- **Status:** Adopted",
                        f"- **Consistent with:** {anchors}\n"
                        "- **Status:** Adopted", DECISION_HUMAN)

        #: The GRAMMAR, named as such. Each of these is refused for not being a
        #: decision id and not merely for naming a record the file lacks, so
        #: dropping the id check is not covered by the existence check below.
        for broken in ("\x00", "|", "0.85", "—", "spec.md:41", "H-01x",
                       "h-001", "Q-abc123", "Adopted", "storage engine",
                       "H-002, 0.85"):
            with self.subTest(anchor=broken):
                self.refused(cited(broken), because="not a decision id")
        #: One citation is one claim of grounding; a repeat weights it double.
        self.refused(cited("H-002, H-002"), because="twice")
        #: 300 commas parse to an EMPTY list rather than to 300 blank anchors,
        #: which is the shape the separator alone would have produced.
        parsed = pas.parse_decisions(swap(
            "- **Status:** Adopted", "- **Consistent with:** " + "," * 300 +
            "\n- **Status:** Adopted", DECISION_HUMAN))
        self.assertEqual(parsed["decisions"]["H-001"]["consistent_with"], [])
        #: The positive control: a real anchor resolves and is carried.
        parsed = pas.parse_decisions(DECISION_HUMAN + DECISION_QUORUM_SECOND_AXIS)
        self.assertEqual(
            parsed["decisions"]["Q-abc123def456"]["consistent_with"], ["H-001"])

    def test_an_anchor_naming_a_decision_this_file_does_not_hold_is_refused(self):
        for text, because in (
                (DECISION_HUMAN + DECISION_QUORUM_SECOND_AXIS.replace(
                    "Consistent with:** H-001", "Consistent with:** H-999"),
                 "does not hold"),
                (swap("- **Status:** Adopted",
                      "- **Consistent with:** H-001\n- **Status:** Adopted",
                      DECISION_HUMAN), "the record itself")):
            with self.subTest(because=because):
                self.refused(text, because=because)

    def test_a_retirement_names_the_record_that_replaces_it(self):
        """``templates/decisions.md`` lines 4-6 make the ``Supersedes`` line half
        of the one legal in-place mutation. It was neither required nor
        validated, so a ``Superseded`` status could be written with nothing
        superseding it — an audit trail that records a decision being withdrawn
        and not what took its place, which is the one question a reader of a
        retired record has.
        """
        retired = DECISION_HUMAN.replace("- **Status:** Adopted",
                                         "- **Status:** Superseded")
        self.refused(retired, because="nothing supersedes them")
        self.refused(retired + DECISION_QUORUM, because="nothing supersedes them")
        #: The positive control, and it must stay parseable or the mutation the
        #: template mandates is one the parser forbids.
        parsed = pas.parse_decisions(retired_and_replaced())
        self.assertEqual(parsed["decisions"]["H-001"]["status"], "Superseded")

    def test_a_supersedes_line_that_retires_nothing_is_refused(self):
        """Built on the retired pair so the one-Adopted-per-axis rule is already
        satisfied and each case is refused for the reason under test rather than
        for the count.
        """
        for value, because in (("H-999", "does not hold"),
                               ("Q-abc123def456", "the record itself"),
                               ("storage-engine", "not a decision id"),
                               ("0.85", "not a decision id")):
            with self.subTest(supersedes=value):
                self.refused(retired_and_replaced().replace(
                    "Supersedes:** H-001", f"Supersedes:** {value}"),
                    because=because)
        #: A target that exists and is still Adopted: the mutation is both
        #: halves or neither, and half of it leaves two live records where one
        #: was retired. On a second axis, so the count rule is not what fires.
        self.refused(DECISION_HUMAN + DECISION_QUORUM_SECOND_AXIS.replace(
            "- **Status:** Adopted", "- **Supersedes:** H-001\n"
            "- **Status:** Adopted"), because="not 'Superseded'")

    def test_one_retired_decision_has_one_successor(self):
        second = DECISION_SUPERSEDING.replace(
            "## Q-abc123def456", "## Q-abc123def457").replace(
            "- **Axis:** storage-engine", "- **Axis:** cache-layer")
        text = (DECISION_HUMAN.replace("- **Status:** Adopted",
                                       "- **Status:** Superseded")
                + DECISION_SUPERSEDING + second)
        self.refused(text, because="both supersede")

    def test_a_supersedes_cycle_is_refused(self):
        """Every syntactic check the retirement rules state passes on a cycle:
        each target exists, each is ``Superseded``, each is claimed exactly
        once, none is orphaned. And the successor chain never reaches a live
        record, so "what took its place" — the one question a reader of a
        retired record has, and the stated purpose of the orphan rule — has no
        answer. A cycle defeats that rule while satisfying every check it makes.
        """
        def retired(did, axis, supersedes):
            return (DECISION_HUMAN
                    .replace("<!-- pipeline-auto-decisions/v1 -->\n", "")
                    .replace("## H-001", f"## {did}")
                    .replace("- **Axis:** storage-engine", f"- **Axis:** {axis}")
                    .replace("- **Status:** Adopted",
                             f"- **Supersedes:** {supersedes}\n"
                             "- **Status:** Superseded"))

        two = (retired("H-001", "storage-engine", "H-002")
               + retired("H-002", "cache-layer", "H-001"))
        three = (retired("H-001", "storage-engine", "H-002")
                 + retired("H-002", "cache-layer", "H-003")
                 + retired("H-003", "queue-broker", "H-001"))
        for length, text in (("2-cycle", two), ("3-cycle", three)):
            with self.subTest(cycle=length):
                self.refused(text, because="Supersedes cycle")
        #: The positive control. A rule that simply forbade a chain longer than
        #: one step would refuse both cases above and forbid the second time a
        #: run ever changes its mind about the same thing.
        parsed = pas.parse_decisions(succession_chain())
        self.assertEqual(parsed["decisions"]["H-001"]["status"], "Superseded")
        self.assertEqual(parsed["decisions"]["H-002"]["status"], "Superseded")
        self.assertEqual(parsed["decisions"]["H-003"]["status"], "Adopted")
        self.assertEqual(parsed["decisions"]["H-003"]["supersedes"], "H-002")

    def test_a_cycle_is_still_found_after_a_valid_chain_has_been_walked(self):
        """The walk remembers which records are already PROVEN to reach a live
        decision, so each is walked once instead of the whole downstream chain
        being re-walked from every retired record — cubic on input with no cycle
        in it, and ``decisions.md`` only grows.

        What that memory can get wrong is marking a record as terminating before
        its walk proved that it does, which would let a cycle sorted AFTER a
        valid succession be skipped entirely. So the file below holds both: a
        three-generation chain that terminates, and a two-cycle whose ids sort
        after it. The cycle must still be named.
        """
        def retired(did, axis, supersedes=None):
            line = ("- **Status:** Superseded" if supersedes is None
                    else f"- **Supersedes:** {supersedes}\n"
                          "- **Status:** Superseded")
            return (DECISION_HUMAN
                    .replace("<!-- pipeline-auto-decisions/v1 -->\n", "")
                    .replace("## H-001", f"## {did}")
                    .replace("- **Axis:** storage-engine", f"- **Axis:** {axis}")
                    .replace("- **Status:** Adopted", line))

        live = (DECISION_HUMAN
                .replace("<!-- pipeline-auto-decisions/v1 -->\n", "")
                .replace("## H-001", "## H-003")
                .replace("- **Axis:** storage-engine", "- **Axis:** queue-broker")
                .replace("- **Status:** Adopted",
                         "- **Supersedes:** H-002\n- **Status:** Adopted"))
        text = ("<!-- pipeline-auto-decisions/v1 -->\n"
                + retired("H-001", "storage-engine")
                + retired("H-002", "cache-layer", "H-001")
                + live
                + retired("H-004", "retry-policy", "H-005")
                + retired("H-005", "log-sink", "H-004"))
        message = str(self.refused(text, because="Supersedes cycle"))
        self.assertIn("H-004", message)
        self.assertIn("H-005", message)

    def test_a_record_quoting_the_ladder_is_refused_when_it_is_written(self):
        """The content screen runs HERE and not only in the projection.

        Run only in ``project_decisions``, it fires on a record that is already
        in the audit trail — and the remedy it prescribes is to reword a
        sentence, which by then means editing a file ``_decision_sections``
        refuses to let lose a record. Refused at write time, nothing has been
        written and rewording is free. The projection keeps the same screen as a
        backstop, pinned separately over records handed to it directly.
        """
        for field, original in PLANTED_IN.items():
            for leak in ("postgres — adopted at 0.85, code-evidenced, "
                         "runner-up speculation",
                         "adopted at 0.85.", "adopted at 0.70",
                         "adopted at 0.30", "rung=0.85", "(0.55)",
                         "code-evidenced", "convention-cited",
                         "engineering-judgement"):
                with self.subTest(field=field, leak=leak):
                    self.refused(swap(original, f"{original} {leak}",
                                      DECISION_HUMAN),
                                 because=field.capitalize())

    def test_the_content_screen_reads_a_rung_value_as_a_value_and_not_a_substring(self):
        """``str(0.70)`` is ``'0.7'`` and ``str(0.30)`` is ``'0.3'``, and a
        substring test matched them inside ANY decimal: a vendor quote of
        ``$10.85``, a p99 of ``10.3 seconds``. The four records below are
        realistic decision prose and every one of them was stopped.

        Each is paired with the stop it must not have taken away — the same
        number written as a rung still stops — so this pins the narrowing and
        not merely the absence of a screen.
        """
        accepted = {
            "answer": ("batch — the vendor quote is $10.85 per million tokens",
                       "redis — avoids speculation about disk contention",
                       "use the schema specified in the RFC"),
            "question": ("Do we cap the p99 at 10.3 seconds or 20.7 seconds?",
                         "Which schema is specified in the RFC?",
                         "Is 20.95 seconds an acceptable p99?"),
        }
        for field, original in PLANTED_IN.items():
            for prose in accepted[field]:
                with self.subTest(field=field, prose=prose):
                    parsed = pas.parse_decisions(
                        swap(original, prose, DECISION_HUMAN))
                    self.assertEqual(parsed["decisions"]["H-001"][field], prose)
            #: The paired stop: the same decimals, written as the rung.
            for leak in ("0.85", "0.3", "0.30", "0.7", "0.70", "0.95"):
                with self.subTest(field=field, leak=leak):
                    self.refused(swap(original, f"adopted at {leak} — x",
                                      DECISION_HUMAN),
                                 because=field.capitalize())

    def test_the_audit_trail_is_read_as_text_and_never_coerced(self):
        for value in (None, 12, b"## H-001\n", ["## H-001"], {"text": "x"},
                      Path("decisions.md")):
            with self.subTest(text=value):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.parse_decisions(value)

    def test_no_value_of_any_field_lets_anything_but_a_trackererror_escape(self):
        """Totality, over the fields the PARSER'S CALL TREE reads.

        Derived from ``parse_decisions``' own AST and not from the fixture, and
        the distinction is not pedantic: the previous version of this test said
        "derived from the parser's own call tree" while enumerating
        ``decision_field_lines(DECISION_HUMAN)``, and the two sets differed by
        ``consistent_with`` — read, split and carried into every record, stated
        by no fixture, and therefore varied by nothing and validated by nothing.

        A field the parser reads and the fixture omits is varied by INSERTING
        it, so omitting it from the fixture is no longer a way out of this list.
        Each field is varied with wrong-typed scalars a markdown cell can carry,
        the absence sentinel, the record grammar's own separators, and deletion.
        """
        lines = decision_field_lines(DECISION_HUMAN)
        stated = {pas._decision_field(line)[0]: line for line in lines}
        read = decision_fields_the_parser_reads()
        self.assertIn("consistent_with", read,
                      "the parser stopped reading consistent_with; this test's "
                      "own cautionary case is gone and the claim is weaker")
        #: The second field the derivation had lost, and it was lost the same
        #: way: ``supersedes`` is read as ``decisions[did].get(...)`` rather than
        #: off ``fields``, and a walk that matched only the ``fields`` receiver
        #: could not see it. Neither field is in ``_REQUIRED_DECISION_FIELDS``,
        #: so neither has any other way into this list.
        self.assertIn("supersedes", read,
                      "the parser stopped reading supersedes, or this walk "
                      "stopped seeing a field read off a record rather than "
                      "off fields — the defect this widening closed")
        for key in sorted(read):
            label = decision_field_label(key)
            probe = pas._decision_field(f"- **{label}:** x")
            self.assertEqual(probe and probe[0], key,
                             f"{label!r} is not how {key!r} is written in a "
                             "record, so varying it varies nothing")
            for value in HOSTILE_DECISION_VALUES:
                with self.subTest(field=key, value=value):
                    if key in stated:
                        text = swap(stated[key], f"- **{label}:** {value}",
                                    DECISION_HUMAN)
                    else:
                        text = swap("- **Status:** Adopted",
                                    f"- **{label}:** {value}\n"
                                    "- **Status:** Adopted", DECISION_HUMAN)
                    self.only_a_tracker_error(text)
            if key in stated:
                with self.subTest(field=key, value="<deleted>"):
                    self.only_a_tracker_error(
                        swap(stated[key] + "\n", "", DECISION_HUMAN))

    def test_no_heading_shape_lets_anything_but_a_trackererror_escape(self):
        for heading in ("## ", "## —", "##  — ", "## H-001", "## H-001 — — —",
                        "## Q-abc123def456", "## Axis Index", "## |", "## \x00",
                        "## " + "x" * 300, "##H-001", "### H-001 — t"):
            with self.subTest(heading=heading):
                self.only_a_tracker_error(
                    swap("## H-001 — Session storage", heading, DECISION_HUMAN))


class ProjectDecisionsTests(DecisionContractCase):
    """``decisions-effective.md`` — the only decision material a brain sees.

    What it omits is as load-bearing as what it carries. Adopted answers must be
    included or brains re-litigate settled ground and manufacture the very drift
    the quorum exists to bound. Values must be excluded: a brain reading
    "adopted at 0.85" treats the decision as soft and reverses it, where a brain
    reading it as simply a decision treats it as binding. Provenance must be
    included so a brain can recognise a human decision and refuse to contradict
    it.
    """

    def projected(self, text: str) -> str:
        return pas.project_decisions(pas.parse_decisions(text))

    def test_the_projection_carries_question_answer_and_provenance_only(self):
        source = swap("- **Status:** Adopted",
                      "- **Grounding rung:** specified\n"
                      "- **Runner-up rung:** convention-cited\n"
                      "- **Rejected alternatives:** sqlite — no concurrent writers\n"
                      "- **Context digest:** " + "a" * 64 + "\n"
                      "- **Status:** Adopted", DECISION_HUMAN)
        projection = self.projected(source)
        self.assertIn("Which storage engine backs the session table?", projection)
        self.assertIn("postgres", projection)
        self.assertIn("human", projection)
        for leak in ("0.95", "0.85", "0.70", "0.55", "0.30", "specified",
                     "Rejected alternatives", "sqlite", "Grounding rung",
                     "Runner-up", "convention-cited", "Context digest",
                     "a" * 64, "T04", "file-exists", "Depth", "Scope"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, projection)

    def test_every_rung_value_and_every_compound_rung_name_is_refused(self):
        """Derived from the ladder rather than typed out, and planted in the two
        fields that are actually PROJECTED.

        The name is the claim, and it is deliberately not "no rung name reaches
        a brain": ``specified`` and ``speculation`` do, by the narrowing
        ``_RUNG_NAME_STRINGS`` argues and the test below pins. What this covers
        is every rung VALUE and every COMPOUND rung name — the set the screen
        actually undertakes to catch, derived from the module so it cannot fall
        behind the ladder.

        The previous version planted the rung in ``Grounding rung`` — a field
        the whitelist already withholds — so it proved the whitelist and said
        nothing about ``question`` and ``answer``, which a human or a brain
        writes as free text and which the projection carries verbatim.
        ``Answer: postgres — adopted at 0.85, code-evidenced, runner-up
        speculation`` carries a value and a compound name through a field the
        whitelist approved, and is refused twice over; strike those two and the
        surviving ``runner-up speculation`` projects.

        A STOP rather than a strip: a decision record whose prose quotes the
        ladder is a record that should never have been written, and silently
        editing the audit trail on its way to a brain would leave the file and
        what the brain read disagreeing about what was decided.
        """
        for field, original in PLANTED_IN.items():
            #: EVERY rung value, in four spellings of the same number, because
            #: ``str(0.70)`` is ``'0.7'`` and a screen built on ``str`` alone
            #: accepts ``adopted at 0.70`` — the leak written the way the ladder
            #: writes it — while one built on ``str`` and ``f"{v:.2f}"`` accepts
            #: ``adopted at 0.850``, the same hole one digit further out.
            leaks = [str(value) for value in pas.RUNGS.values()]
            leaks += [f"{value:.2f}" for value in pas.RUNGS.values()]
            leaks += [f"{value:.3f}" for value in pas.RUNGS.values()]
            leaks += [str(value).lstrip("0") for value in pas.RUNGS.values()]
            #: And every rung name the screen still looks for. Derived from the
            #: module's own tuple, so a ladder that gains a compound name gains
            #: a case here on the same day.
            leaks += list(pas._RUNG_NAME_STRINGS)
            for leak in leaks:
                with self.subTest(field=field, leak=leak):
                    source = swap(original, f"{original} ({leak})",
                                  DECISION_HUMAN)
                    with self.assertRaises(pas.TrackerValidationError) as raised:
                        self.projected(source)
                    message = str(raised.exception)
                    self.assertIn(leak, message)
                    self.assertIn(field.capitalize(), message)
        #: The positive control: prose that quotes no rung projects unchanged,
        #: so this is a screen and not a refusal of every free-text field.
        projection = self.projected(DECISION_HUMAN)
        for name, value in pas.RUNGS.items():
            with self.subTest(rung=name):
                self.assertNotIn(name, projection)
                self.assertNotIn(str(value), projection)

    def test_a_compound_rung_name_is_matched_as_a_word_and_not_a_substring(self):
        """The name half of the screen is a TOKEN rule, stated rather than
        assumed. No compound rung name is a substring of an English word today,
        so this is defensive for the ladder as it stands — and the set is
        DERIVED (``name for name in RUNGS if "-" in name``), so the day it gains
        a name that is, the screen is already right instead of already wrong.
        That is the exact shape of the defect this round was filed for.
        """
        for token in pas._RUNG_NAME_STRINGS:
            with self.subTest(token=token):
                self.assertEqual(pas._rung_leak(f"adopted {token}, then"), token)
                self.assertEqual(pas._rung_leak(f"{token}-first"), token)
                self.assertEqual(pas._rung_leak(token), token)
                self.assertIsNone(pas._rung_leak(f"{token}ness of the claim"))
                self.assertIsNone(pas._rung_leak(f"pre{token}"))

    def test_the_two_rung_names_that_are_english_words_are_not_screened(self):
        """The narrowing, pinned as a DELIBERATE give-up rather than left to be
        rediscovered as a regression.

        ``specified`` and ``speculation`` are ordinary English words before they
        are rungs, and the screen that caught them caught "use the schema
        specified in the RFC" and "redis — avoids speculation about disk
        contention" — real answers, stopped for saying ordinary things, in a
        file whose prescribed remedy is to reword a sentence. They are no longer
        screened, so a bare one of them now reaches a brain; the compound names
        and every rung VALUE still do not, which is what keeps the leak this
        screen exists for refused.
        """
        unscreened = sorted(set(pas.RUNGS) - set(pas._RUNG_NAME_STRINGS))
        self.assertEqual(unscreened, ["specified", "speculation"],
                         "the ladder's single-word names changed; the screen's "
                         "documented give-up has to change with them")
        for field, original in PLANTED_IN.items():
            for name in unscreened:
                with self.subTest(field=field, name=name):
                    projection = self.projected(
                        swap(original, f"{original} ({name})", DECISION_HUMAN))
                    self.assertIn(f"({name})", projection)
                    #: And its VALUE is still screened, so no rung loses its
                    #: number to this narrowing.
                    self.refused(swap(original,
                                      f"{original} ({pas.RUNGS[name]})",
                                      DECISION_HUMAN))

    def test_a_rung_value_is_screened_in_every_spelling_of_the_same_number(self):
        """The screen matches a NUMBER, not a list of spellings.

        A list of spellings is always one digit behind whoever writes the
        record: the first version held ``str(value)`` and accepted ``adopted at
        0.70``; the second added ``f"{value:.2f}"`` and accepted ``adopted at
        0.850``. Trailing zeros are unbounded and a bare leading ``.`` is a
        third form, so the spellings are DERIVED here — zero to five trailing
        zeros, with and without the leading zero — and the screen has to parse
        rather than enumerate to pass.
        """
        for name, value in pas.RUNGS.items():
            for places in range(1, 6):
                for spelling in (f"{value:.{places}f}",
                                 f"{value:.{places}f}".lstrip("0")):
                    if spelling.rstrip("0").rstrip(".") not in ("", "."):
                        #: Only spellings that still denote the value; a
                        #: one-place rendering of 0.85 is 0.8 and is a
                        #: different number.
                        if float(spelling) != value:
                            continue
                    with self.subTest(rung=name, spelling=spelling):
                        self.assertEqual(pas._rung_leak(f"adopted at {spelling}"),
                                         spelling)
        #: And through the parser, in the fields that are projected.
        for field, original in PLANTED_IN.items():
            for spelling in ("0.850", "0.8500", "0.85000", ".85", ".70",
                             "0.950", "0.300", ".55"):
                with self.subTest(field=field, spelling=spelling):
                    self.refused(swap(original, f"{original} adopted at {spelling}",
                                      DECISION_HUMAN),
                                 because=field.capitalize())

    def test_a_decimal_a_separator_split_is_not_a_rung(self):
        """The narrowing that the trailing-zero fix could have taken away.

        Parsing every digit run rather than searching for a spelling makes
        ``$1,000.85`` two runs, and the second of them — ``000.85`` — parses to
        exactly 0.85. A grouped number is the one place a legitimate digit run
        starts with redundant zeros, so a leading zero the integer part does not
        need means the run is a FRAGMENT and not the rung.
        """
        for prose in ("the vendor quote is $1,000.85 a month",
                      "a budget of 1,000.70 units", "000.85", "0000.30"):
            with self.subTest(prose=prose):
                self.assertIsNone(pas._rung_leak(prose))
        #: The paired stop, so this pins the narrowing and not the absence of a
        #: screen: the same number written the way a rung is written.
        self.assertEqual(pas._rung_leak("adopted at 0.85"), "0.85")

    def test_a_percentage_and_an_exponent_are_deliberately_not_screened(self):
        """Stated as a DECISION, so a later reader finds an argument rather than
        an omission and a gap it might close by accident.

        ``85%`` is not 0.85, and the five rungs times a hundred are 95, 85, 70,
        55 and 30 — bare integers ordinary decision prose is full of. Screening
        them would stop "a 30 second timeout" and "a 70 GB index" to catch a
        spelling this module never writes. Scientific notation is out for the
        mirror reason: nothing writes a rung as ``8.5e-1``, and admitting
        exponents admits every ``1e-3`` in a config discussion.

        The percentage being out is also the workaround the unit collision below
        depends on, so it is load-bearing and not merely tolerated.
        """
        for prose in ("a 85% cache hit rate", "95% availability", "a 30 second "
                      "timeout", "a 70 GB index", "55 open connections",
                      "8.5e-1", "adopted at 8.5e-1", "7e-1", "3.0e-1"):
            with self.subTest(prose=prose):
                self.assertIsNone(pas._rung_leak(prose))
        for field, original in PLANTED_IN.items():
            for prose in ("we target an 85% hit rate", "a 30 second timeout"):
                with self.subTest(field=field, prose=prose):
                    parsed = pas.parse_decisions(
                        swap(original, prose, DECISION_HUMAN))
                    self.assertEqual(parsed["decisions"]["H-001"][field], prose)

    def test_a_trailing_dot_is_punctuation_and_an_interior_one_is_not(self):
        """The one asymmetry in the decimal rule, and the clause that carries it.

        ``adopted at 0.85.`` ends a sentence and is exactly the leak, so the
        trailing ``.`` is stripped before the run is parsed. ``0.85.1`` and
        ``v1.0.85`` continue a version string and are not, so the strip is
        TRAILING ONLY and the surviving two-dot run reads as no number at all.
        Both halves, because a rule that dropped the strip would let the
        sentence-ending leak through and a rule that stripped dots anywhere
        would stop every version string in the repository.
        """
        for leak, token in (("adopted at 0.85.", "0.85"),
                            ("adopted at 0.85..", "0.85"),
                            ("adopted at 0.70.", "0.70"),
                            ("adopted at .85.", ".85"),
                            ("it was adopted at 0.85. Then we moved on", "0.85")):
            with self.subTest(leak=leak):
                self.assertEqual(pas._rung_leak(leak), token)
        for prose in ("pinned at v1.0.85", "pinned at v1.0.85.",
                      "bumped 0.85.1 to 0.85.2", "^0.30.0", "the 0.70.3 release",
                      "0.85.1"):
            with self.subTest(prose=prose):
                self.assertIsNone(pas._rung_leak(prose))
        for field, original in PLANTED_IN.items():
            with self.subTest(field=field):
                self.refused(swap(original, f"{original} adopted at 0.85.",
                                  DECISION_HUMAN),
                             because=field.capitalize())
                parsed = pas.parse_decisions(
                    swap(original, "pinned to v0.85.1 of the driver",
                         DECISION_HUMAN))
                self.assertEqual(parsed["decisions"]["H-001"][field],
                                 "pinned to v0.85.1 of the driver")

    def test_a_decimal_that_is_a_unit_and_not_a_rung_is_refused_too(self):
        """The cost of the value screen, pinned so it is DISCLOSED rather than
        discovered by whoever first tries to record a hit-rate axis.

        The screen cannot tell a rung from a unit — nothing in the text
        distinguishes 0.85-the-hit-rate from 0.85-the-rung — so an innocent
        decimal that happens to equal a rung value is stopped. This is believed
        irreducible: guessing from the surrounding words would make the screen a
        heuristic exactly where it is relied on to be total.

        What makes it liveable is that the stop SAYS SO and names the way out,
        which is what this asserts: rescale the number, or use the percentage
        spelling, which is deliberately not screened.
        """
        for prose in ("the price is $0.30 per request",
                      "timeout of 0.7 seconds",
                      "a 0.55 ratio of reads to writes",
                      "the hit rate is 0.85 of requests"):
            with self.subTest(prose=prose):
                self.assertIsNotNone(pas._rung_leak(prose))
        #: The stop a writer meets has to carry the disclosure and the remedy,
        #: or the collision is a mystery at the one moment it can be worked
        #: around for free.
        message = str(self.refused(
            swap(PLANTED_IN["answer"], "redis — the hit rate is 0.85 of requests",
                 DECISION_HUMAN)))
        for hint in ("unit", "0.7 seconds", "700ms", "85%"):
            with self.subTest(hint=hint):
                self.assertIn(hint, message.casefold())
        #: And the workarounds the message names actually work.
        for reworded in ("redis — a 85% hit rate", "redis — 700ms of timeout",
                         "redis — 30 cents per request"):
            with self.subTest(reworded=reworded):
                parsed = pas.parse_decisions(
                    swap(PLANTED_IN["answer"], reworded, DECISION_HUMAN))
                self.assertEqual(parsed["decisions"]["H-001"]["answer"], reworded)

    def test_provenance_is_screened_before_the_presence_check_that_would_hide_it(self):
        """WHERE the enum screen sits, asserted as behaviour and not as source
        order.

        ``_text`` below it refuses every non-string, so an enum screen placed
        AFTER it is handed nothing but strings — and ``_member``'s whole reason
        for existing, that ``["human"] in frozenset(...)`` raises ``TypeError``
        outside ``TrackerError``, becomes unobservable. Moved down, a bare ``in``
        written here passes the suite, and the record is refused for the wrong
        reason: "cannot be projected without ['provenance']", a MISSING-field
        message for a field that is present and holds a list.

        So this pins the message rather than the position: the screen must have
        SEEN the unhashable value and named it as an enum violation. Move the
        block below ``_text`` and this fails; leave it and replace ``_member``
        with ``in`` and this fails too.
        """
        parsed = pas.parse_decisions(DECISION_HUMAN)
        for value in (["human"], {"human"}, {"a": 1}, ("human",), 0.85, 12,
                      None, True, b"human"):
            with self.subTest(provenance=value):
                record = dict(parsed["decisions"]["H-001"])
                record["provenance"] = value
                with self.assertRaises(pas.TrackerValidationError) as raised:
                    pas.project_decisions({"decisions": {"H-001": record}})
                message = str(raised.exception)
                self.assertIn(f"provenance {value!r} is not one of", message)
                self.assertNotIn("cannot be projected without", message)

    def test_the_projection_contract_discloses_what_the_screen_does_not_catch(self):
        """``project_decisions``' docstring IS the contract, and a reader trusts
        the entry point over a module-level comment two thousand lines away.

        Three times in this task a docstring here has claimed more than its code
        — most recently "no rung name ... and that claim holds for all three
        fields", written by the same commit that stopped screening ``specified``
        and ``speculation``. So the claim is no longer prose alone: the two
        names the screen gives up are DERIVED from the module and have to appear
        in the contract that a reader trusts, and so do the three it catches. A
        ladder that gains a single-word name gains a disclosure obligation on
        the same day, and an edit that tidies the give-up back out of the
        headline fails here.
        """
        doc = pas.project_decisions.__doc__

        def bullet(marker):
            """The one bullet, and not the rest of the docstring around it.

            Presence anywhere is not the check this needs: ``specified``
            already appears in the docstring inside "use the schema specified in
            the RFC", so a contract that had dropped the disclosure entirely
            would still contain the word. The claim has to be in the bullet that
            makes it.
            """
            self.assertIn(marker, doc,
                          f"the entry-point contract no longer states {marker!r}; "
                          "the split between what the content screen catches and "
                          "what it gives up IS the contract")
            start = doc.index(marker)
            rest = doc[start + len(marker):]
            ends = [end for end in (rest.find("\n    * "), rest.find("\n\n"))
                    if end != -1]
            return marker + (rest if not ends else rest[:min(ends)])

        unscreened = sorted(set(pas.RUNGS) - set(pas._RUNG_NAME_STRINGS))
        self.assertEqual(unscreened, ["specified", "speculation"])
        caught = bullet("* CAUGHT:")
        given_up = bullet("* NOT CAUGHT")
        for name in pas._RUNG_NAME_STRINGS:
            with self.subTest(screened=name):
                self.assertIn(name, caught,
                              "a rung name the screen catches is not listed as "
                              "caught")
                self.assertNotIn(name, given_up)
        for name in unscreened:
            with self.subTest(unscreened=name):
                self.assertIn(name, given_up,
                              "a rung name the screen lets through is not "
                              "disclosed by the contract a reader trusts")
                self.assertNotIn(name, caught)
        #: The exact shape of the three recurrences: a sentence that sweeps the
        #: give-up back under a claim about "all three fields".
        self.assertNotIn("holds for all three fields", doc)
        #: And ``_rung_leak`` states the same pair, because the two documents
        #: disagreeing is the defect itself.
        for name in unscreened:
            with self.subTest(unscreened=name, doc="_rung_leak"):
                self.assertIn(name, pas._rung_leak.__doc__)

    def test_the_projection_screens_its_content_again_on_what_it_is_handed(self):
        """The backstop half. ``parse_decisions`` refuses a leaking record at
        write time, so every file-level case above now stops there — and a
        projection that had dropped its own screen would pass all of them.
        ``project_decisions`` declares its input untrusted and is handed records
        directly, so it screens what it is given.
        """
        parsed = pas.parse_decisions(DECISION_HUMAN)
        for field in ("question", "answer"):
            for leak in ("adopted at 0.85", "code-evidenced"):
                with self.subTest(field=field, leak=leak):
                    record = dict(parsed["decisions"]["H-001"])
                    record[field] = f"{record[field]} — {leak}"
                    with self.assertRaises(pas.TrackerValidationError) as raised:
                        pas.project_decisions({"decisions": {"H-001": record}})
                    self.assertIn(field.capitalize(), str(raised.exception))

    def test_provenance_is_screened_against_its_enum_before_it_is_projected(self):
        """The third projected field, and the one the key screen's own argument
        had not reached.

        ``status`` and ``action`` are re-checked against their enums here
        because this function declares its input untrusted; ``question`` and
        ``answer`` are screened as content for the same reason. ``provenance``
        was screened by neither, so ``human — adopted at 0.85, code-evidenced``
        projected a rung value AND a rung name verbatim into the one file a
        brain reads. Membership rather than a content screen, because
        provenance is an enum and an enum check is strictly narrower.
        """
        parsed = pas.parse_decisions(DECISION_HUMAN)
        for value in ("human — adopted at 0.85, code-evidenced",
                      "human, code-evidenced", "Human", "HUMAN", "human ",
                      "humanquorum", "", "   ", "machine", None, 12, 0.85,
                      ["human"], {"human"}, {"a": 1}):
            with self.subTest(provenance=value):
                record = dict(parsed["decisions"]["H-001"])
                record["provenance"] = value
                with self.assertRaises(pas.TrackerValidationError):
                    pas.project_decisions({"decisions": {"H-001": record}})
        #: Both members project, or the screen is a refusal of every record.
        for value in sorted(pas._PROVENANCES):
            with self.subTest(provenance=value):
                record = dict(parsed["decisions"]["H-001"])
                record["provenance"] = value
                self.assertIn(f"- **Provenance:** {value}",
                              pas.project_decisions({"decisions": {"H-001": record}}))

    def test_every_field_outside_the_whitelist_stays_out(self):
        """Totality, by construction: a sentinel is written into one extra field
        at a time and the projection must not contain it. A blacklist passes the
        named cases above and ships the next field somebody adds.
        """
        for field in ("Sources", "Forecloses", "Authorized through",
                      "Granted against", "Runner-up rung", "Grounding rung",
                      "Context digest", "Rung", "Notes"):
            with self.subTest(field=field):
                sentinel = "zzsentinelzz"
                source = swap("- **Status:** Adopted",
                              f"- **{field}:** {sentinel}\n- **Status:** Adopted",
                              DECISION_HUMAN)
                self.assertNotIn(sentinel, self.projected(source))

    def test_the_validated_anchor_fields_stay_out_of_the_projection_too(self):
        """``Supersedes`` and ``Consistent with`` are probed with their LEGAL
        values rather than with a sentinel: both are validated as decision ids
        now, so a sentinel in either is refused before the projection is reached
        and a test built on one would pass without projecting anything.
        """
        projection = self.projected(retired_and_replaced())
        self.assertIn("## Q-abc123def456", projection)
        for field in ("Supersedes", "Consistent with", "supersedes",
                      "consistent_with", "H-001"):
            with self.subTest(field=field):
                self.assertNotIn(field, projection)

    def test_superseded_decisions_are_not_projected(self):
        """Over the retired PAIR, because a `Superseded` record with nothing
        superseding it is no longer a parseable file: the template makes the
        `Supersedes` line half of the one legal in-place mutation.
        """
        projection = self.projected(retired_and_replaced())
        self.assertNotIn("sqlite", projection)
        self.assertNotIn("## H-001", projection)
        self.assertIn("## Q-abc123def456", projection)

    def test_open_decisions_are_not_projected(self):
        opened = swap("postgres — Use the existing PostgreSQL instance.",
                      "pending user response",
                      swap("Status:** Adopted", "Status:** Open", DECISION_HUMAN))
        projection = self.projected(opened)
        self.assertNotIn("pending user response", projection)
        self.assertNotIn("H-001", projection)

    def test_an_adopted_decision_is_projected(self):
        """The positive control for the three exclusions above. A projection
        that emitted nothing at all would satisfy every one of them, and brains
        would re-litigate every decision the run has made.
        """
        projection = self.projected(DECISION_HUMAN)
        self.assertIn("## H-001", projection)
        self.assertIn("- **Question:** Which storage engine backs the session "
                      "table?", projection)
        self.assertIn("- **Answer:** postgres — Use the existing PostgreSQL "
                      "instance.", projection)
        self.assertIn("- **Provenance:** human", projection)

    def test_a_budget_extension_is_not_projected(self):
        """Its answer carries a ceiling, and a ceiling is a number in a brain's
        payload. Both grants, because two budgets mean two authorities.
        """
        for action in sorted(pas._EXTENSION_ACTIONS):
            with self.subTest(action=action):
                granted = swap("Decision action:** none",
                               f"Decision action:** {action}", DECISION_HUMAN)
                granted = swap("- **Status:** Adopted",
                               "- **Authorized through:** 14 adoptions\n"
                               "- **Status:** Adopted", granted)
                projection = self.projected(granted)
                self.assertNotIn("14 adoptions", projection)
                self.assertNotIn("postgres", projection)

    def test_the_projection_is_ordered_and_deterministic(self):
        """The fixture is assembled ``Q`` FIRST, so insertion order and id order
        disagree. Built the other way round the two coincide, and dropping the
        ``sorted`` changes nothing about the output — which is how a projection
        whose order is an accident of dict insertion would ship: deterministic
        for one file and reordered the day a record is appended above another.
        """
        source = DECISION_QUORUM_SECOND_AXIS + DECISION_HUMAN
        self.assertLess(source.index("## Q-abc123def456"), source.index("## H-001"))
        both = pas.parse_decisions(source)
        self.assertEqual(list(both["decisions"]), ["Q-abc123def456", "H-001"])
        projection = pas.project_decisions(both)
        self.assertEqual(projection, pas.project_decisions(both))
        self.assertLess(projection.index("## H-001"),
                        projection.index("## Q-abc123def456"))

    def test_a_record_with_no_question_is_refused_rather_than_a_keyerror(self):
        """``record['question']`` on a record that never stated one raises
        ``KeyError`` — outside ``TrackerError``, on the one path whose output a
        brain reads.
        """
        parsed = pas.parse_decisions(DECISION_HUMAN)
        for field in ("question", "answer", "provenance"):
            for value in (None, "", "   ", 12, ["x"], {"a": 1}):
                with self.subTest(field=field, value=value):
                    record = dict(parsed["decisions"]["H-001"])
                    record[field] = value
                    with self.assertRaises(pas.TrackerValidationError):
                        pas.project_decisions({"decisions": {"H-001": record}})
            with self.subTest(field=field, value="<absent>"):
                record = dict(parsed["decisions"]["H-001"])
                del record[field]
                with self.assertRaises(pas.TrackerValidationError):
                    pas.project_decisions({"decisions": {"H-001": record}})

    def test_an_unhashable_status_or_action_is_a_stop_and_never_a_typeerror(self):
        """Standing rule: never test membership of a supplied value with a bare
        ``in`` against a set. ``["Adopted"] in frozenset(...)`` raises
        ``TypeError`` — outside ``TrackerError``, so it escapes every handler a
        controller has written. Reverting either call site to a bare ``in``
        fails this test.
        """
        parsed = pas.parse_decisions(DECISION_HUMAN)
        for field in ("status", "action"):
            for value in (["Adopted"], {"a": 1}, {"Adopted"}, None, 3, 0.85):
                with self.subTest(field=field, value=value):
                    record = dict(parsed["decisions"]["H-001"])
                    record[field] = value
                    with self.assertRaises(pas.TrackerValidationError):
                        pas.project_decisions({"decisions": {"H-001": record}})

    def test_a_shape_the_projection_cannot_read_is_a_stop_not_an_empty_file(self):
        """An empty projection is indistinguishable from a run that has decided
        nothing, and a brain handed one re-litigates everything.
        """
        record = pas.parse_decisions(DECISION_HUMAN)["decisions"]["H-001"]
        for shape in (None, [], "decisions", {}, {"decisions": []},
                      {"decisions": "H-001"}, {"axis_index": {}},
                      {"decisions": {"H-001": "adopted"}},
                      {"decisions": {"H-001": None}},
                      #: A key the SORT cannot order against another. Nine bad
                      #: shapes and not one of them had a non-str key, so
                      #: ``sorted(decisions["decisions"])`` raised ``TypeError``
                      #: — outside ``TrackerError`` — on a dict mixing them.
                      {"decisions": {1: record, "H-001": record}},
                      {"decisions": {("a",): record, "H-001": record}},
                      #: And with ONE non-str key nothing raised at all: the
                      #: projection emitted ``## 1`` as a decision heading, a
                      #: "decision" no ``_id_provenance`` would accept, in the
                      #: one file a brain reads.
                      {"decisions": {1: record}},
                      {"decisions": {("a",): record}},
                      {"decisions": {None: record}},
                      {"decisions": {0.85: record}},
                      #: A str key that is no decision id is the same defect
                      #: wearing the right type.
                      {"decisions": {"H-01x": record}},
                      {"decisions": {"h-001": record}},
                      {"decisions": {"Axis Index": record}},
                      {"decisions": {"": record}}):
            with self.subTest(shape=shape):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.project_decisions(shape)

    def test_the_projection_declares_itself_generated_and_read_only(self):
        projection = self.projected(DECISION_HUMAN)
        self.assertTrue(projection.startswith(
            "<!-- pipeline-auto-decisions-effective/v1 -->"))
        self.assertIn("Read-only", projection)
        self.assertTrue(projection.endswith("\n"))


class FindingsLedgerTemplateTests(unittest.TestCase):
    """``templates/findings.md`` — where a fixer's dispute is adjudicated.

    The ledger is P03's because the adjudication lands there and never in
    ``decisions.md``: an adjudication is a factual question about a finding, not
    a requirement decision, and filing it as a decision would let a dispute
    about whether code is broken masquerade as a statement about what the user
    wants.
    """

    def test_the_ledger_carries_an_adjudication_column(self):
        header = findings_template().splitlines()
        self.assertEqual(header[0], "<!-- pipeline-auto-findings/v1 -->")
        self.assertIn("Adjudication", header[1])
        self.assertIn("Severity", header[1])

    def test_its_columns_are_named_and_its_rows_match_them(self):
        """A template one column short of its own header teaches every writer to
        file a row the ledger cannot hold — the defect this build has already
        paid for three times.
        """
        lines = [line for line in findings_template().splitlines()
                 if line.startswith("|")]
        header = [cell.strip() for cell in lines[0].strip("|").split("|")]
        self.assertEqual(header, ["ID", "Scope", "Severity", "Status",
                                  "Disposition", "Evidence", "Adjudication",
                                  "Fix Round", "Re-review"])
        self.assertGreater(len(lines), 2, "the template shows no example row")
        for line in lines[1:]:
            with self.subTest(row=line):
                self.assertEqual(len(line.strip("|").split("|")), len(header))

    def test_it_names_the_module_severities_and_no_foreign_one(self):
        """Through ``pas._SEVERITIES``, the module's own enum, not by eye. A
        template teaching ``major`` teaches every reviewer to file a severity
        ``_validate_task_review`` refuses, and the run finds out at its first
        review row.
        """
        text = findings_template()
        for severity in pas._SEVERITIES:
            with self.subTest(severity=severity):
                self.assertIn(severity, text)
        for foreign in ("major", "blocker", "trivial", "nit", "wontfix",
                        "deferred"):
            with self.subTest(foreign=foreign):
                self.assertNotIn(foreign, text)

    def test_it_states_the_zero_open_findings_bar(self):
        text = findings_template()
        self.assertIn("ZERO OPEN FINDINGS AT EVERY SEVERITY", text)

    def test_it_routes_a_dispute_to_one_adjudicator_and_never_to_a_quorum(self):
        """"Can line 41 be null" is a FACT, settled by reading code or running
        an experiment, not by a confidence-weighted vote. Routing facts to the
        quorum is the mechanism by which a quorum degrades into a
        general-purpose "ask three models when unsure" reflex.
        """
        text = findings_template()
        self.assertIn("ONE adjudicator settles it, not three", text)
        for verdict in ("confirmed", "refuted", "plausible"):
            with self.subTest(verdict=verdict):
                self.assertIn(verdict, text)
        self.assertIn("only then does it become a quorum", text)

    def test_it_states_that_a_bare_disagreement_is_inadmissible(self):
        text = findings_template()
        self.assertIn("file:line", text)
        self.assertIn("bare disagreement is inadmissible", text)
        self.assertIn("the finding STANDS", text)

    def test_it_states_that_an_adjudication_never_enters_the_decisions_file(self):
        self.assertIn("AN ADJUDICATION NEVER ENTERS `decisions.md`",
                      findings_template())

    def test_it_never_spells_a_rung_value_or_the_adoption_floor(self):
        """The same rule the decisions template is held to: the numbers are
        schema constants the controller owns, and a copy in a file a hand can
        edit is a second source of truth for the adoption bar.
        """
        text = findings_template()
        for value in pas.RUNGS.values():
            with self.subTest(value=value):
                self.assertNotIn(str(value), text)

# --- contradiction and depth ----------------------------------------------

#: A human budget grant. `dispatch.extend-budget` specifically, and not the
#: quorum one: an implementation that excluded extensions by writing
#: `action == "quorum.extend-budget"` — which is what the brief for this task
#: proposed — passes every case built on the quorum spelling and fails this one.
#: Its `Answer` carries a CEILING, which is what makes it not an option on an
#: axis and not grounding for anything.
DECISION_BUDGET_GRANT = """
## H-009 — More quorum adoptions in this phase

- **Question:** May the run adopt beyond its per-phase drift budget?
- **Axis:** drift-budget
- **Answer:** 3 more adoptions in P04 — the remaining tasks all turn on one unanswered choice.
- **Decision action:** dispatch.extend-budget
- **Provenance:** human
- **Depth:** 0
- **Consequences:** file-exists:quorum/extensions.json=present
- **Scope:** P04
- **Status:** Adopted
"""

#: An OPEN record: the question written down before it has an answer, which
#: `templates/decisions.md` requires so a question cannot be silently dropped.
#: It binds nothing and can be anchored to nothing.
DECISION_OPEN = """
## H-020 — Queue broker

- **Question:** Which broker carries the work queue?
- **Axis:** queue-broker
- **Answer:** pending user response
- **Decision action:** none
- **Provenance:** human
- **Depth:** 0
- **Scope:** T07
- **Status:** Open
"""


def derived_decision(did: str, depth: int, *, axis: str | None = None,
                     anchors: str = "") -> str:
    """One quorum record on its own axis, at a stated depth.

    Each on its own axis so that the one-Adopted-per-axis rule is never what a
    depth case is testing, and every field is spelled the way the record
    grammar states it so the fixture is parsed rather than assumed.
    """
    anchor_line = f"- **Consistent with:** {anchors}\n" if anchors else ""
    return (f"\n## {did} — derived at depth {depth}\n\n"
            f"- **Question:** What follows from the decision above?\n"
            f"- **Axis:** {axis or ('axis-' + did)}\n"
            f"- **Answer:** option-{did} — the answer derived at that distance.\n"
            f"- **Decision action:** quorum.adopt\n"
            f"- **Provenance:** quorum\n"
            f"- **Depth:** {depth}\n"
            f"{anchor_line}"
            f"- **Consequences:** file-exists:build/{did}.txt=present\n"
            f"- **Scope:** T05\n- **Status:** Adopted\n")


def a_ladder_of_depths() -> str:
    """`H-001` at depth 0, then quorum records at depth 1 and depth 2.

    The depth-2 record anchors to the depth-1 record and that one to `H-001`,
    so the chain the fixture states is the chain `decision_depth` walks — a
    fixture whose depths were free-standing numbers would let the walk agree
    with it for the wrong reason.
    """
    return (DECISION_HUMAN
            + derived_decision("Q-aaaaaaaaaaaa", 1, anchors="H-001")
            + derived_decision("Q-bbbbbbbbbbbb", 2, anchors="Q-aaaaaaaaaaaa"))


def candidate(**overrides):
    """A well-formed candidate answer on the decided axis; override one field.

    It AGREES with `H-001` as it stands — same option, same consequence — so
    every rejection case below is this candidate with exactly one thing changed
    and cannot pass because the base was already a contradiction.
    """
    base = {
        "axis": "storage-engine",
        "answer_key": "postgres",
        "consequences": [{"kind": "file-exists", "subject": "db/session.sql",
                          "value": "present"}],
    }
    base.update(overrides)
    return base


def keys_read_from(source: str, function: str, receiver: str) -> set[str]:
    """Every string key ``function`` reads off ``receiver``, from its own AST.

    Derived from the call tree and not from a fixture, which is the standing
    rule a totality claim in this suite is held to. A field the function starts
    reading widens the case list by itself; a field it stops reading drops out,
    and the test that uses this asserts the set it got so that a rename cannot
    empty it silently.
    """
    node = function_node(source, function)
    names = set()
    for child in ast.walk(node):
        if (isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in ("get", "pop")
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == receiver
                and child.args
                and isinstance(child.args[0], ast.Constant)
                and isinstance(child.args[0].value, str)):
            names.add(child.args[0].value)
        if (isinstance(child, ast.Subscript)
                and isinstance(child.value, ast.Name)
                and child.value.id == receiver
                and isinstance(child.slice, ast.Constant)
                and isinstance(child.slice.value, str)):
            names.add(child.slice.value)
    return names


#: Hostile JSON values, for the claim that a malformed candidate or a malformed
#: anchor never escapes the exception family. Both halves of the standing rule
#: are here for every field it is applied to: UNHASHABLE values (`[]`, `{}`,
#: and the populated forms of each), which a bare `in` against a frozenset
#: raises `TypeError` on, and WRONG-TYPED SCALARS (`None`, `True`, `0`, `0.85`)
#: which hash fine and then break whatever reads them as text.
HOSTILE_JSON_VALUES = (
    None, True, False, 0, 1, -1, 0.85, "", "   ", "postgres", "new", "H-001",
    "storage-engine", "\x00", "a b", "x" * 300, [], ["postgres"],
    [{"kind": "file-exists"}], {}, {"kind": "file-exists"}, ("postgres",),
)


def parsed_records(text: str) -> dict:
    """`{D-ID: record}` for one decisions file, as mutable copies.

    Copies, so a case that moves a record onto another axis cannot leak that
    change into the next case through a shared parse.
    """
    parsed = pas.parse_decisions(text)
    return {did: dict(record) for did, record in parsed["decisions"].items()}


def index_over(records: dict, order: list) -> dict:
    """A `parse_decisions`-shaped result whose axis index states `order`.

    Assembled rather than parsed on purpose, and only where the file grammar
    cannot state the shape under test. Every record in it is genuine parser
    output; the only thing built by hand is the index.
    """
    index: dict = {}
    for did in order:
        index.setdefault(records[did]["axis"], []).append(did)
    return {"decisions": records, "axis_index": index}


class CheckContradictionTests(DecisionContractCase):
    """Does this candidate disagree with something the run is already bound by.

    Structural and never semantic: same axis, then a different option or a
    different value asserted for the same subject. Nothing here reads an
    answer for meaning.

    THE FAILURE THIS CLASS IS SHAPED AROUND is `None` arriving because the
    check could not work the answer out. `None` is the clear verdict — it says
    the candidate was compared and is compatible — so every case that cannot be
    compared is asserted to STOP rather than to come back clear. Each rejection
    is paired with a case that must still be ACCEPTED: an implementation that
    refused every candidate would satisfy every stop below and adopt nothing
    for the rest of the run.
    """

    def setUp(self):
        self.decisions = pas.parse_decisions(DECISION_HUMAN)
        self.record = self.decisions["decisions"]["H-001"]
        #: The fixture properties every case below depends on, asserted here so
        #: the fixture cannot quietly stop satisfying them.
        self.assertEqual(self.record["status"], "Adopted")
        self.assertEqual(self.record["provenance"], "human")
        self.assertEqual(self.record["answer_key"], "postgres")
        self.assertEqual(self.record["consequences"],
                         {("file-exists", "db/session.sql"): "present"})

    def test_an_agreeing_candidate_is_not_a_contradiction(self):
        """The positive control the whole class rests on. Same option, same
        assertion about the repository: nothing disagrees, and the answer is
        the clear one rather than the absence of a verdict."""
        self.assertIsNone(pas.check_contradiction(self.decisions, candidate()))

    def test_an_unhashable_d_id_in_the_index_is_a_stop_and_never_a_type_error(self):
        """Standing rule 9, at the one call site a mutation pass found unpinned.

        ``if did not in records`` HASHES ``did``. The D-IDs this walks come
        from ``axis_index``, and ``check_contradiction`` takes a MAPPING rather
        than a file -- its own docstring says so, because a caller that
        assembles one (a projection, a merge of two runs, a test) can hand it
        shapes the file grammar refuses. So an unhashable D-ID is reachable,
        and a bare ``in`` would raise ``TypeError`` from inside the walk:
        outside ``TrackerError``, past every handler a controller has written,
        on the one check whose whole job is to not fail open.

        Reverting ``_member(did, records)`` to a bare ``in`` must fail this.
        """
        for did in (["H-001"], {"id": "H-001"}, frozenset({"H-001"})):
            with self.subTest(did=did):
                assembled = {"decisions": dict(self.decisions["decisions"]),
                             "axis_index": {"storage-engine": [did]}}
                with self.assertRaises(pas.TrackerValidationError):
                    pas.check_contradiction(assembled, candidate())

    def test_a_hashable_d_id_the_records_lack_is_the_same_stop(self):
        """The twin, so the case above cannot pass merely by refusing everything.

        A D-ID that is a perfectly good string but names no record is the same
        disagreement between the index and the records, and must stop for the
        same reason -- while the unmodified fixture still returns its clear
        verdict.
        """
        assembled = {"decisions": dict(self.decisions["decisions"]),
                     "axis_index": {"storage-engine": ["H-001", "H-999"]}}
        with self.assertRaises(pas.TrackerValidationError):
            pas.check_contradiction(assembled, candidate())
        #: And the unbroken index still answers.
        self.assertIsNone(pas.check_contradiction(self.decisions, candidate()))

    def test_a_different_option_on_a_decided_axis_names_the_decision(self):
        """The D-ID and not a boolean: the rejection status and the terminal
        report both key off WHICH decision was contradicted."""
        self.assertEqual(
            pas.check_contradiction(self.decisions, candidate(
                answer_key="sqlite",
                consequences=[{"kind": "file-exists",
                               "subject": "db/session.sql", "value": "absent"}])),
            "H-001")

    def test_the_same_option_asserting_an_opposite_consequence_is_caught(self):
        """The consequence branch, reached on its own.

        The brief's version of this case gave the candidate a BLANK answer key
        and claimed the consequence was what caught it. It was not: a blank key
        differs from `postgres`, so the answer-key branch returned first and the
        case passed without the consequence comparison ever running. Here the
        two keys are asserted EQUAL, so the only thing left to disagree is the
        consequence.
        """
        probe = candidate(consequences=[{"kind": "file-exists",
                                         "subject": "db/session.sql",
                                         "value": "absent"}])
        self.assertEqual(probe["answer_key"], self.record["answer_key"],
                         "this case is about the consequence branch; equal "
                         "answer keys are what make it reachable")
        self.assertEqual(pas.check_contradiction(self.decisions, probe), "H-001")

    def test_a_consequence_about_something_else_is_not_a_contradiction(self):
        """The pair for the case above. Consequences are compared on the
        subjects both sides assert, so an assertion the record never made is
        new information and not a disagreement — and an implementation that
        called every differing consequence a clash would fail here."""
        probe = candidate(consequences=[{"kind": "file-exists",
                                         "subject": "db/pool.sql",
                                         "value": "absent"}])
        self.assertNotIn(("file-exists", "db/pool.sql"),
                         self.record["consequences"])
        self.assertIsNone(pas.check_contradiction(self.decisions, probe))

    def test_an_axis_nothing_has_decided_is_not_a_contradiction(self):
        """A candidate on an axis the run has never decided contradicts
        nothing. This is the one legitimate `None`-with-no-comparison, and it
        is legitimate because there is nothing on the axis to compare to."""
        probe = candidate(axis="log-format", answer_key="sqlite")
        self.assertNotIn("log-format", self.decisions["axis_index"])
        self.assertIsNone(pas.check_contradiction(self.decisions, probe))

    def test_a_blank_answer_key_stops_rather_than_returning_a_verdict(self):
        """A candidate that names no option cannot be compared as one.

        Under the brief's implementation this returned `H-001` — the blank key
        differs from `postgres` — so a candidate whose consequences AGREE with
        the record in every particular was reported as contradicting a human
        decision and routed to `rejected-contradicts-human`. The agreeing form
        is the case below: it is a stop, and it is emphatically not a verdict.
        """
        for value in ("", "   ", None):
            with self.subTest(answer_key=value):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.check_contradiction(self.decisions,
                                            candidate(answer_key=value))

    def test_a_generic_approval_is_not_an_option_on_an_axis(self):
        """`yes` names nothing, so it differs from every real answer key and
        would be reported as contradicting whatever the axis had decided. The
        rule does not vary by provenance, which is what `parse_decisions` says
        about the same string in a record."""
        for value in ("yes", "proceed", "LGTM", "ok."):
            with self.subTest(answer_key=value):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.check_contradiction(self.decisions,
                                            candidate(answer_key=value))
        #: The pair. `go` is a language and `no` is a refusal, and both are
        #: real answers a candidate may name.
        for value in ("go", "no"):
            with self.subTest(accepted=value):
                self.assertEqual(
                    pas.check_contradiction(self.decisions,
                                            candidate(answer_key=value)),
                    "H-001")

    def test_a_candidate_with_no_consequences_cannot_be_compared(self):
        """The fail-open this section exists to close.

        With no consequences the intersection with every record is empty, so
        the comparison collapses to the answer key alone and two genuinely
        incompatible answers that happen to name the same option pass. The
        response schema requires consequences for that reason; accepting a
        candidate without them here would reopen the hole one layer down.
        """
        for value in ([], None, "file-exists:db/session.sql=present",
                      [{"kind": "file-exists", "subject": "db/session.sql"}],
                      [{"kind": "invented", "subject": "x", "value": "y"}]):
            with self.subTest(consequences=value):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.check_contradiction(self.decisions,
                                            candidate(consequences=value))
        self.assertIsNone(pas.check_contradiction(self.decisions, candidate()))

    def test_a_candidate_that_asserts_one_subject_twice_is_a_stop(self):
        """A candidate holding both values for one subject agrees with an
        adopted record through whichever of the two survives into the map."""
        with self.assertRaises(pas.QuorumSchemaInvalid):
            pas.check_contradiction(self.decisions, candidate(consequences=[
                {"kind": "file-exists", "subject": "db/session.sql",
                 "value": "present"},
                {"kind": "file-exists", "subject": "db/session.sql",
                 "value": "absent"}]))

    def test_the_reserved_axis_literal_is_refused_rather_than_passed(self):
        """`new` clears the check by being unrecognisable, which is exactly the
        fail-open shape the master plan carries forward.

        The second assertion is why it has to be refused HERE: a decision
        record may not carry `new` as its axis, so the index can never hold it
        and a candidate arriving on it would find no records, be compared with
        nothing, and come back clear.
        """
        with self.assertRaises(pas.QuorumSchemaInvalid):
            pas.check_contradiction(self.decisions,
                                    candidate(axis=pas._RESERVED_AXIS))
        self.refused(
            DECISION_HUMAN.replace("- **Axis:** storage-engine",
                                   f"- **Axis:** {pas._RESERVED_AXIS}"),
            because="reserved literal")

    def test_the_axis_is_screened_before_it_is_used_as_a_lookup_key(self):
        """An unhashable axis raises `TypeError` inside `dict.get` and a
        non-string one raises it inside the token grammar, which indexes its
        argument. Both are outside `TrackerError`, and both arrive before
        anything has established what the axis is."""
        for value in (["storage-engine"], {"axis": "storage-engine"}, 12, None,
                      True, "", "storage engine", "-leading-hyphen"):
            with self.subTest(axis=value):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.check_contradiction(self.decisions,
                                            candidate(axis=value))

    def test_a_superseded_decision_binds_nothing_and_the_live_one_does(self):
        """Both halves, because only the pair distinguishes "retired records
        are skipped" from "the first record on the axis is used".

        `H-001` is retired holding `sqlite`; the record that replaced it holds
        `postgres`. A candidate naming `postgres` agrees with what binds and
        must come back clear even though it contradicts the retired answer, and
        a candidate naming `sqlite` must be rejected against the SUCCESSOR and
        never against the record that was withdrawn.
        """
        decisions = pas.parse_decisions(retired_and_replaced())
        self.assertEqual(decisions["decisions"]["H-001"]["status"], "Superseded")
        self.assertEqual(decisions["decisions"]["H-001"]["answer_key"], "sqlite")
        live = decisions["decisions"]["Q-abc123def456"]
        self.assertEqual((live["status"], live["answer_key"]),
                         ("Adopted", "postgres"))
        self.assertIsNone(pas.check_contradiction(decisions, candidate()))
        self.assertEqual(
            pas.check_contradiction(decisions, candidate(
                answer_key="sqlite",
                consequences=[{"kind": "file-exists",
                               "subject": "db/session.sql", "value": "absent"}])),
            "Q-abc123def456")

    def test_an_open_decision_binds_nothing(self):
        """An `Open` record is the question written down before it has an
        answer. Its placeholder differs from every real answer key, so counting
        it would reject every candidate on the axis it is holding open."""
        decisions = pas.parse_decisions(DECISION_HUMAN + DECISION_OPEN)
        self.assertEqual(decisions["decisions"]["H-020"]["status"], "Open")
        self.assertEqual(decisions["decisions"]["H-020"]["axis"], "queue-broker")
        self.assertIsNone(pas.check_contradiction(
            decisions, candidate(axis="queue-broker", answer_key="redis")))

    def test_a_budget_grant_is_not_an_answer_on_an_axis(self):
        """BOTH extension actions, which is what the brief's `action ==
        "quorum.extend-budget"` missed.

        A grant's answer is a ceiling rather than an option, so compared as an
        answer key it disagrees with every real answer and would reject the
        first candidate ever raised on the axis it was recorded against.
        """
        decisions = pas.parse_decisions(DECISION_HUMAN + DECISION_BUDGET_GRANT)
        grant = decisions["decisions"]["H-009"]
        self.assertEqual((grant["status"], grant["action"]),
                         ("Adopted", "dispatch.extend-budget"))
        self.assertIn(grant["action"], pas._EXTENSION_ACTIONS)
        self.assertNotEqual(grant["action"], "quorum.extend-budget",
                            "this case exists to catch an exclusion written "
                            "against the quorum spelling alone")
        self.assertIsNone(pas.check_contradiction(
            decisions, candidate(axis="drift-budget", answer_key="no more")))

    def test_human_decisions_are_reported_ahead_of_quorum_ones(self):
        """Which D-ID comes back decides the rejection status.

        ASSEMBLED RATHER THAN PARSED, and the second assertion says why: an
        axis holds at most one Adopted decision, so no legal `decisions.md` can
        state a human and a quorum decision both binding on one axis — a later
        adoption supersedes the record standing there. The ordering is
        therefore a backstop for a caller that assembles a mapping, and every
        record in this one is still genuine parser output.

        Both index orders are asserted. One alone would pass on a function that
        simply returned the first id it was handed.
        """
        self.refused(DECISION_HUMAN + DECISION_QUORUM,
                     because="Adopted decisions")
        records = parsed_records(DECISION_HUMAN + DECISION_QUORUM_SECOND_AXIS)
        for record in records.values():
            record["axis"] = "storage-engine"
        clash = candidate(answer_key="sqlite",
                          consequences=[{"kind": "file-exists",
                                         "subject": "db/session.sql",
                                         "value": "absent"}])
        #: Each record contradicts the candidate ON ITS OWN, so the case is
        #: about which id is REPORTED and not about which one disagrees.
        for did in ("H-001", "Q-abc123def456"):
            with self.subTest(alone=did):
                self.assertEqual(
                    pas.check_contradiction(
                        index_over({did: records[did]}, [did]), clash), did)
        for order in (["H-001", "Q-abc123def456"], ["Q-abc123def456", "H-001"]):
            with self.subTest(order=order):
                self.assertEqual(
                    pas.check_contradiction(index_over(records, order), clash),
                    "H-001")

    def test_a_record_enum_is_screened_by_membership_and_not_by_a_bare_in(self):
        """`["Adopted"] in frozenset(...)` raises `TypeError`, which is outside
        this module's family and escapes every handler a controller has
        written. The three enum fields are read before anything has established
        a type, so this is where an unhashable value actually arrives."""
        for field in ("status", "action", "provenance"):
            for value in (["Adopted"], {"status": "Adopted"}, 12, None):
                with self.subTest(field=field, value=value):
                    records = parsed_records(DECISION_HUMAN)
                    records["H-001"][field] = value
                    with self.assertRaises(pas.TrackerValidationError):
                        pas.check_contradiction(
                            index_over(records, ["H-001"]), candidate())

    def test_a_record_the_comparison_cannot_read_stops_rather_than_deciding(self):
        """A record whose answer key or consequence map is not the shape
        `parse_decisions` builds would report a difference that is a fact about
        the record rather than about the answer — under the candidate's name."""
        for field, value in (("answer_key", None), ("answer_key", 12),
                             ("answer_key", ["postgres"]), ("answer_key", ""),
                             ("consequences", None), ("consequences", 12),
                             ("consequences", "file-exists:x=present"),
                             ("consequences", [("file-exists", "x")]),
                             ("consequences", {"file-exists": "present"}),
                             ("consequences", {("file-exists", 1): "present"}),
                             ("consequences", {("file-exists", "x"): 1})):
            with self.subTest(field=field, value=value):
                records = parsed_records(DECISION_HUMAN)
                records["H-001"][field] = value
                with self.assertRaises(pas.TrackerValidationError):
                    pas.check_contradiction(
                        index_over(records, ["H-001"]), candidate())

    def test_an_index_and_the_records_that_disagree_are_a_stop(self):
        """An index naming a record the run does not hold would compare the
        candidate against whichever records survived the disagreement."""
        records = parsed_records(DECISION_HUMAN)
        with self.assertRaises(pas.TrackerValidationError):
            pas.check_contradiction(
                {"decisions": records,
                 "axis_index": {"storage-engine": ["H-001", "H-777"]}},
                candidate())
        for value in ("H-001", 12, None, {"H-001": 1}):
            with self.subTest(ids=value):
                with self.assertRaises(pas.TrackerValidationError):
                    pas.check_contradiction(
                        {"decisions": records,
                         "axis_index": {"storage-engine": value}}, candidate())

    def test_the_whole_parse_result_is_required_and_not_the_records_alone(self):
        """A shape this cannot read reports every candidate as contradicting
        nothing, which is indistinguishable from a run that has decided
        nothing and is the most permissive answer available."""
        for value in (parsed_records(DECISION_HUMAN), None, [], "decisions",
                      {"decisions": None}, {"decisions": {}}):
            with self.subTest(decisions=value):
                with self.assertRaises(pas.TrackerError):
                    pas.check_contradiction(value, candidate())
        #: `{"decisions": {}}` is readable and simply holds nothing; it fails
        #: above only for its missing index, so the pair is asserted here.
        self.assertIsNone(pas.check_contradiction(
            {"decisions": {}, "axis_index": {}}, candidate()))

    def test_no_candidate_shape_escapes_the_tracker_error_family(self):
        """TOTALITY, over the fields this function actually reads.

        The case list is derived from `check_contradiction`'s own AST and from
        the consequence screen it delegates to, not from the fixture and not
        from memory — a field either function starts reading widens it by
        itself. Every field is varied with an unhashable value and with a
        wrong-typed scalar, and the whole candidate is varied too.
        """
        source = module_source()
        fields = keys_read_from(source, "check_contradiction", "candidate")
        self.assertEqual(fields, {"axis", "answer_key", "consequences"},
                         "the fields check_contradiction reads have changed; "
                         "this claim is about the call tree, so widen the case "
                         "list rather than this assertion")
        item_fields = (keys_read_from(source, "_candidate_consequences", "item")
                       | keys_read_from(source, "_consequence_problems", "item"))
        self.assertTrue(item_fields, "the consequence screen reads no field; "
                                     "this totality claim has gone hollow")
        probes = [value for value in HOSTILE_JSON_VALUES]
        for field in sorted(fields):
            for value in HOSTILE_JSON_VALUES:
                probes.append(candidate(**{field: value}))
        for field in sorted(item_fields):
            for value in HOSTILE_JSON_VALUES:
                item = {"kind": "file-exists", "subject": "db/session.sql",
                        "value": "present"}
                item[field] = value
                probes.append(candidate(consequences=[item]))
        for probe in probes:
            with self.subTest(candidate=repr(probe)[:70]):
                try:
                    result = pas.check_contradiction(self.decisions, probe)
                except pas.TrackerError:
                    continue
                except Exception as escaped:    # noqa: BLE001 - that is the claim
                    raise AssertionError(
                        f"{type(escaped).__name__}({escaped}) escaped "
                        "check_contradiction; nothing outside TrackerError may "
                        "leave this module") from escaped
                self.assertTrue(result is None or isinstance(result, str))


class DecisionDepthTests(DecisionContractCase):
    """How far from the last thing a human actually said this answer stands.

    Human is 0, an answer citing only depth-0 material is 1, and `DEPTH_CAP` is
    2 — depth 3 is where a run stops building the user's product and starts
    building its own.

    EVERY ANCHOR EITHER COUNTS OR STOPS. An anchor that is skipped contributes
    0, and an answer whose anchors are all skipped comes back at depth 1: the
    shallowest and most adoptable depth there is, handed to the response with
    the least grounding behind it. Every case below that asserts a stop is
    asserting that the alternative was that number.
    """

    def setUp(self):
        self.decisions = pas.parse_decisions(DECISION_HUMAN)
        self.assertEqual(self.decisions["decisions"]["H-001"]["depth"], 0,
                         "a human decision is depth 0; every count below is "
                         "measured from it")

    def test_an_answer_citing_only_a_human_decision_is_depth_one(self):
        self.assertEqual(
            pas.decision_depth(self.decisions,
                               [{"kind": "decision", "id": "H-001"}]), 1)

    def test_an_answer_citing_only_the_spec_is_depth_one(self):
        """The specification and the repository are facts rather than
        inferences: they are where the run started, not somewhere it reasoned
        its way to, so they contribute 0."""
        for anchor in ({"kind": "spec", "id": "spec.md:12"},
                       {"kind": "repo", "id": "db/engine.py:1"}):
            with self.subTest(anchor=anchor):
                self.assertEqual(pas.decision_depth(self.decisions, [anchor]), 1)

    def test_depth_accumulates_and_three_exceeds_the_cap(self):
        decisions = pas.parse_decisions(a_ladder_of_depths())
        self.assertEqual(decisions["decisions"]["Q-aaaaaaaaaaaa"]["depth"], 1)
        self.assertEqual(decisions["decisions"]["Q-bbbbbbbbbbbb"]["depth"], 2)
        self.assertEqual(
            pas.decision_depth(decisions,
                               [{"kind": "decision", "id": "Q-aaaaaaaaaaaa"}]), 2)
        self.assertEqual(
            pas.decision_depth(decisions,
                               [{"kind": "decision", "id": "Q-bbbbbbbbbbbb"}]), 3)
        self.assertGreater(3, pas.DEPTH_CAP)

    def test_the_deepest_anchor_sets_the_depth(self):
        """The MAXIMUM and never a mean, a sum or a count. Asserted in both
        orders so a walk that simply kept the last one it saw fails."""
        decisions = pas.parse_decisions(a_ladder_of_depths())
        deep = {"kind": "decision", "id": "Q-bbbbbbbbbbbb"}
        shallow = {"kind": "decision", "id": "H-001"}
        spec = {"kind": "spec", "id": "spec.md:12"}
        for anchors in ([deep, shallow, spec], [spec, shallow, deep]):
            with self.subTest(anchors=[a["id"] for a in anchors]):
                self.assertEqual(pas.decision_depth(decisions, anchors), 3)

    def test_an_anchor_that_names_no_decision_is_a_stop(self):
        """THE CARRIED-FORWARD QUESTION, ruled here.

        Task 4 closed the markdown half — `Consistent with` in `decisions.md`
        is ids only, each resolving to a record the file holds. The JSON half
        reached this function still open: an anchor is what a brain SENDS, and
        the response schema checked its `kind` and nothing else, so
        `{"kind": "decision"}` was a schema-valid claim of grounding that names
        no decision. Resolved to nothing and skipped it contributes 0, and the
        answer with the least grounding in the run comes back at depth 1.

        Both layers are now closed and both are asserted here, because this
        function is also called with mappings that never went through the
        response validator.
        """
        for anchor in ({"kind": "decision"},
                       {"kind": "decision", "id": ""},
                       {"kind": "decision", "id": "   "},
                       {"kind": "decision", "id": None},
                       {"kind": "decision", "id": ["H-001"]},
                       {"kind": "decision", "id": "H-01x"},
                       {"kind": "decision", "id": "db/engine.py:1"},
                       {"kind": "decision", "id": "storage-engine"}):
            with self.subTest(anchor=anchor):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.decision_depth(self.decisions, [anchor])
                self.assertIn(
                    "consistent-with-item-malformed",
                    pas.validate_brain_response(response(consistent_with=[anchor])),
                    "the response schema lets this anchor through; the stop "
                    "above is then the only thing between it and a depth of 1")
        #: The pair. A decision anchor that DOES name a live record resolves,
        #: and the response carrying it is schema-valid.
        live = {"kind": "decision", "id": "H-001"}
        self.assertEqual(pas.decision_depth(self.decisions, [live]), 1)
        self.assertEqual(pas.validate_brain_response(response(consistent_with=[live])), [])

    def test_an_anchor_naming_a_decision_the_run_does_not_hold_is_a_stop(self):
        """Grounding the audit trail cannot produce is grounding nothing can
        check. Counting it as absent counts it as costless."""
        with self.assertRaises(pas.QuorumSchemaInvalid):
            pas.decision_depth(self.decisions,
                               [{"kind": "decision", "id": "H-777"}])

    def test_an_unknown_anchor_kind_is_a_stop_and_the_kind_is_screened(self):
        """An unrecognised kind contributes 0, so an answer anchored entirely
        to kinds nobody defined comes back at depth 1. The unhashable cases are
        the membership pin: `["decision"] in frozenset(...)` raises
        `TypeError`, outside this module's family, and `kind` is the first
        field read off an anchor so it is where such a value arrives."""
        for value in ("hunch", "", None, 12, True, ["decision"],
                      {"kind": "decision"}, "Decision"):
            with self.subTest(kind=value):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.decision_depth(self.decisions,
                                       [{"kind": value, "id": "H-001"}])
        for value in sorted(pas._ANCHOR_KINDS):
            with self.subTest(accepted=value):
                self.assertEqual(
                    pas.decision_depth(self.decisions,
                                       [{"kind": value, "id": "H-001"}]), 1)

    def test_an_answer_anchored_to_nothing_is_a_stop(self):
        """Depth measures distance from something a human said. With no anchor
        there is nothing to measure from, so the distance is unbounded by
        construction — and the permissive reading of unbounded is 1."""
        for value in ([], None, "H-001", 12, {}, ({"kind": "spec", "id": "s"},)):
            with self.subTest(consistent_with=value):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.decision_depth(self.decisions, value)

    def test_a_retired_or_unanswered_anchor_is_a_stop(self):
        """A `Superseded` record was retired, an `Open` one has no answer, and
        a budget grant's answer is a ceiling. None of the three is ever
        projected to a brain, so an answer standing on one is standing on
        something it could not have read: counted it prices that claim at the
        retired record's depth, skipped it prices it at zero.
        """
        decisions = pas.parse_decisions(
            retired_and_replaced() + DECISION_OPEN + DECISION_BUDGET_GRANT)
        for did, why in (("H-001", "Superseded"), ("H-020", "Open"),
                         ("H-009", "a budget grant")):
            with self.subTest(anchor=did, why=why):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.decision_depth(
                        decisions, [{"kind": "decision", "id": did}])
        #: The pair: the record that REPLACED the retired one is anchorable.
        self.assertEqual(
            decisions["decisions"]["Q-abc123def456"]["status"], "Adopted")
        self.assertEqual(
            pas.decision_depth(
                decisions, [{"kind": "decision", "id": "Q-abc123def456"}]), 2)

    def test_a_depth_that_is_not_a_count_is_a_stop(self):
        """`True` is not a depth of 1 and `"1"` cannot be added to. A depth
        that cannot be read would otherwise be compared against `DEPTH_CAP`
        by whatever `max` made of it."""
        for value in (True, "1", 1.0, None, -1, ["1"], {}):
            with self.subTest(depth=value):
                records = parsed_records(DECISION_HUMAN)
                records["H-001"]["depth"] = value
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.decision_depth(index_over(records, ["H-001"]),
                                       [{"kind": "decision", "id": "H-001"}])

    def test_the_whole_parse_result_is_required_and_not_the_records_alone(self):
        for value in (parsed_records(DECISION_HUMAN), None, [], "decisions",
                      {"decisions": None}):
            with self.subTest(decisions=value):
                with self.assertRaises(pas.TrackerError):
                    pas.decision_depth(value,
                                       [{"kind": "decision", "id": "H-001"}])

    def test_no_anchor_shape_escapes_the_tracker_error_family(self):
        """TOTALITY, over the fields this function actually reads.

        Derived from `decision_depth`'s own AST rather than from memory, with
        every field varied by an unhashable value and by a wrong-typed scalar,
        and with the container itself varied too.
        """
        fields = keys_read_from(module_source(), "decision_depth", "entry")
        self.assertEqual(fields, {"kind", "id"},
                         "the fields decision_depth reads off an anchor have "
                         "changed; this claim is about the call tree, so widen "
                         "the case list rather than this assertion")
        probes = [value for value in HOSTILE_JSON_VALUES]
        probes.extend([value] for value in HOSTILE_JSON_VALUES)
        for field in sorted(fields):
            for value in HOSTILE_JSON_VALUES:
                anchor = {"kind": "decision", "id": "H-001"}
                anchor[field] = value
                probes.append([anchor])
                probes.append([{"kind": "spec", "id": "spec.md:1"}, anchor])
        for probe in probes:
            with self.subTest(consistent_with=repr(probe)[:70]):
                try:
                    depth = pas.decision_depth(self.decisions, probe)
                except pas.TrackerError:
                    continue
                except Exception as escaped:    # noqa: BLE001 - that is the claim
                    raise AssertionError(
                        f"{type(escaped).__name__}({escaped}) escaped "
                        "decision_depth; nothing outside TrackerError may "
                        "leave this module") from escaped
                self.assertIsInstance(depth, int)
                self.assertGreaterEqual(depth, 1)

# --- admissibility and the per-brain payload ------------------------------

#: The published question record, read at its real path. The in-memory
#: ``QUESTION`` below is asserted to be exactly what this file parses to, so
#: the fixture and the dict every case reasons about cannot drift apart.
QUESTION_RECORD = FIXTURES / "quorum" / "question-record.md"

#: The qid the canonical question and axis derive to. Written out rather than
#: computed so that a change to ``derive_qid`` shows up here as a failure
#: instead of silently re-keying every case in this section.
QID = "ee1433c675a3"

#: The record's fields, in file order, as ``(label, value)``. ``question_text``
#: renders these; a case that needs one field wrong overrides exactly it.
QUESTION_FIELDS = (
    ("Question", "Which storage engine backs the session table?"),
    ("Axis", "storage-engine"),
    ("Phase", "P04"),
    ("Blocks", "T04"),
    ("Raiser", "worker-7"),
    ("Options supplied", "yes"),
    ("Options", "postgres, sqlite"),
    ("Candidate answers", "postgres because we already run it"),
    ("Recommendation", "postgres"),
    ("Reading roots",
     "spec=docs/superpowers/specs/design.md, "
     "intent-brief=docs/superpowers/runs/R/intent-brief.md, "
     "repo=., tests=tests, "
     "phase-plan=docs/superpowers/plans/phase-04.md"),
    ("Owners", "brain-a, brain-b, brain-c"),
)

#: The record as ``parse_question`` produces it. Stated literally, not derived
#: from the parser: a dict built by the code under test agrees with that code
#: by construction and would keep agreeing with it while both were wrong.
QUESTION = {
    "question": "Which storage engine backs the session table?",
    "axis": "storage-engine",
    "phase": "P04",
    "blocks": ["T04"],
    "raiser": "worker-7",
    "options_supplied": True,
    "options": [{"key": "postgres"}, {"key": "sqlite"}],
    "candidate_answers": ["postgres because we already run it"],
    "recommendation": "postgres",
    "reading_roots": {
        "spec": "docs/superpowers/specs/design.md",
        "intent-brief": "docs/superpowers/runs/R/intent-brief.md",
        "repo": ".",
        "tests": "tests",
        "phase-plan": "docs/superpowers/plans/phase-04.md",
    },
    "owners": ["brain-a", "brain-b", "brain-c"],
    "challenge": [],
}

#: Every JSON value a field may legally hold that is NOT the shape the reader
#: expects. The two unhashable entries are the ones ``x in frozenset(...)``
#: raises ``TypeError`` on; the scalars are the ones a coercing reader turns
#: into a legal-looking value.
HOSTILE_VALUES = ([], ["modern"], {}, {"modern": 1}, 0, 1, 1.5, True, None, "",
                  "  ", "modern")


def question_text(*, heading=f"## Q-{QID} — Session storage", drop=(),
                  extra=(), **overrides) -> str:
    """The question record's markdown, with named fields changed or removed.

    Keyed by the dict key the field parses to (``options_supplied``), not by
    its display label, so a case names the thing the module reads.
    """
    lines = ["<!-- pipeline-auto/v1 -->", "", heading, ""]
    for label, value in QUESTION_FIELDS:
        key = label.lower().replace(" ", "_")
        if key in drop:
            continue
        lines.append(f"- **{label}:** {overrides.get(key, value)}")
    lines.extend(extra)
    return "\n".join(lines) + "\n"


class CheckAdmissible(unittest.TestCase):
    """Admissibility, at exactly the three criteria a machine can settle.

    Criterion 2 ("decidable from the repository") and criterion 5 ("one
    decision, not several") are judgment calls and stay with P07's prose. What
    is here is criterion 1 (it blocks something), criterion 3 (it names an
    axis) and criterion 4 (the options test) — plus the shape rules the quorum
    row will be held to anyway, caught at the question rather than at the row.
    """

    def test_the_fixture_on_disk_is_the_record_these_cases_reason_about(self):
        """The two halves of every case below, pinned to each other.

        Without this the dict is one author's memory of the file and the file
        is nobody's. It is also where a case that "depends on a fixture
        property" states the property: ``QUESTION`` carries the raiser and a
        candidate answer, which is the whole of what the payload cases prove
        is dropped.
        """
        self.assertEqual(pas.parse_question(QUESTION_RECORD.read_text(encoding="utf-8")),
                         QUESTION)
        self.assertEqual(pas.parse_question(question_text()), QUESTION)
        self.assertEqual(QUESTION["raiser"], "worker-7")
        self.assertEqual(QUESTION["candidate_answers"],
                         ["postgres because we already run it"])
        self.assertEqual(QUESTION["recommendation"], "postgres")

    def test_a_well_formed_question_is_admissible(self):
        """THE ACCEPT CASE. Every stricter bar below is paired with this one:
        an implementation that refused everything would satisfy all of them and
        dispatch nothing for the life of the run.
        """
        self.assertEqual(pas.check_admissible(QUESTION), [])

    def test_a_question_that_supplies_no_options_is_still_admissible(self):
        """The second accept case, and the one a blanket ``options`` rule
        breaks: criterion 4 judges the options a record SUPPLIES, and a record
        that supplies none is judged by P07's prose instead.
        """
        self.assertEqual(
            pas.check_admissible(dict(QUESTION, options_supplied=False, options=[])),
            [])

    def test_a_question_blocking_nothing_is_an_opinion(self):
        self.assertIn("blocks-nothing",
                      pas.check_admissible(dict(QUESTION, blocks=[])))

    def test_a_bare_string_is_not_a_list_of_blockers(self):
        """``"T04"`` iterates as three ``_text``-true characters.

        A reader that simply iterated would read one mistyped cell as three
        blockers and admit a question that blocks nothing on the strength of
        a typo.
        """
        self.assertIn("blocks-nothing",
                      pas.check_admissible(dict(QUESTION, blocks="T04")))

    def test_an_axis_is_required(self):
        self.assertIn("missing-axis", pas.check_admissible(dict(QUESTION, axis="")))

    def test_a_question_is_required(self):
        self.assertIn("missing-question",
                      pas.check_admissible(dict(QUESTION, question="   ")))

    def test_adjectives_are_not_options(self):
        bad = dict(QUESTION, options=[{"key": "modern"}, {"key": "pragmatic"}])
        self.assertIn("options-fail-the-options-test", pas.check_admissible(bad))

    def test_the_options_test_folds_before_it_asks(self):
        """``Modern`` is the same non-option as ``modern``.

        ``_NON_OPTIONS`` holds folded spellings only, so a screen that forgot
        to fold would admit every capitalised adjective — which is how they are
        actually typed at the head of an option list.
        """
        bad = dict(QUESTION, options=[{"key": "Modern"}, {"key": "PRAGMATIC"}])
        self.assertIn("options-fail-the-options-test", pas.check_admissible(bad))

    def test_an_unhashable_option_key_is_judged_and_never_raises(self):
        """RULE 9, at the one call site in this function that can see one.

        ``["modern"] in frozenset(...)`` HASHES its left operand and raises
        ``TypeError`` — outside ``TrackerError``, so it escapes every handler a
        controller has written and kills the run on a raiser's typo. The screen
        is placed ABOVE the ``_text`` guard for exactly this reason: below it,
        no unhashable value could ever arrive and this case would pass against
        a bare ``in``.
        """
        for hostile in ([], ["modern"], {}, {"modern": 1}):
            with self.subTest(key=repr(hostile)):
                problems = pas.check_admissible(
                    dict(QUESTION, options=[{"key": hostile}, {"key": "sqlite"}]))
                self.assertIn("option-key-is-not-text", problems)
                self.assertIn("fewer-than-two-options", problems)

    def test_an_option_key_is_not_coerced_into_a_legal_option(self):
        """``str(["modern"])`` is ``"['modern']"``: non-empty, and an option.

        A reader that coerced would count it toward the two options criterion 4
        requires, so a record with one real option and one list would pass the
        test criterion 4 exists to apply.
        """
        self.assertIn("fewer-than-two-options", pas.check_admissible(
            dict(QUESTION, options=[{"key": "postgres"}, {"key": ["sqlite"]}])))

    def test_a_single_option_is_not_a_question(self):
        self.assertIn("fewer-than-two-options", pas.check_admissible(
            dict(QUESTION, options=[{"key": "postgres"}])))

    def test_two_spellings_of_one_option_are_one_option(self):
        self.assertIn("duplicate-options", pas.check_admissible(
            dict(QUESTION, options=[{"key": "postgres"}, {"key": "postgres"}])))

    def test_exactly_three_owners_are_required(self):
        for owners in (["brain-a", "brain-b"],
                       ["brain-a", "brain-b", "brain-c", "brain-d"],
                       "abc", (), None):
            with self.subTest(owners=repr(owners)):
                self.assertIn("owner-count-is-not-three",
                              pas.check_admissible(dict(QUESTION, owners=owners)))

    def test_one_brain_dispatched_twice_is_not_three_brains(self):
        """``_validate_quorum`` refuses the ROW; this refuses the QUESTION.

        One brain dispatched twice is a majority manufactured from a single
        opinion, and catching it here costs nothing while catching it at the
        row costs three dispatches.
        """
        self.assertIn("duplicate-owners", pas.check_admissible(
            dict(QUESTION, owners=["brain-a", "brain-a", "brain-c"])))

    def test_options_supplied_is_a_boolean_and_not_a_spelling_of_one(self):
        for supplied in ("yes", "true", 1, "false", None):
            with self.subTest(options_supplied=repr(supplied)):
                self.assertIn("options-supplied-is-not-a-boolean",
                              pas.check_admissible(
                                  dict(QUESTION, options_supplied=supplied)))

    def test_a_record_that_is_not_an_object_is_refused_by_type(self):
        for record in ("", [], None, 0, ["question"]):
            with self.subTest(record=repr(record)):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.check_admissible(record)

    def record_fields_read(self) -> set:
        """Every record field ``check_admissible`` reads, FROM ITS OWN BODY.

        Rule 10: a totality claim derives its case list from the call tree, not
        from what the author remembers writing. Every ``record.get("X")`` and
        ``record["X"]`` in the function is collected here, so a field added to
        the reader and not to the corpus below fails this file.
        """
        node = function_node(module_source(), "check_admissible")
        fields = set()
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "get"
                    and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == "record"
                    and inner.args
                    and isinstance(inner.args[0], ast.Constant)):
                fields.add(inner.args[0].value)
            if (isinstance(inner, ast.Subscript)
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id == "record"
                    and isinstance(inner.slice, ast.Constant)):
                fields.add(inner.slice.value)
        return fields

    def test_the_field_sweep_finds_the_fields_this_file_claims_it_does(self):
        """A test of the test. The sweep below is only a totality claim if the
        extractor actually finds fields; against a broken one it would return
        an empty set and every case would pass by covering nothing.
        """
        self.assertEqual(
            self.record_fields_read(),
            {"blocks", "axis", "question", "owners", "options_supplied", "options"})

    def test_no_value_in_any_field_it_reads_escapes_the_tracker_error_family(self):
        """Every field from the sweep above, crossed with every hostile value.

        ``check_admissible`` is handed agent-authored data, and every field may
        legally hold any JSON value. A validator that raises has not classified
        the record, and anything outside ``TrackerError`` escapes every handler
        a controller has written.
        """
        fields = sorted(self.record_fields_read())
        self.assertTrue(fields, "the field sweep found nothing to vary")
        probes = [dict(QUESTION, **{field: value})
                  for field in fields for value in HOSTILE_VALUES]
        #: The option list's own members, which the sweep above cannot see:
        #: the field is ``options`` and the hostile value is one level in.
        probes.extend(dict(QUESTION, options=[value]) for value in HOSTILE_VALUES)
        probes.extend(dict(QUESTION, options=[{"key": value}])
                      for value in HOSTILE_VALUES)
        probes.extend(dict(QUESTION, options=[{"key": "postgres"}, value])
                      for value in HOSTILE_VALUES)
        #: Two options that fail the same way. The de-duplication claim below
        #: is only a claim if some probe can actually produce a repeat.
        probes.append(dict(QUESTION, options=[{"key": "modern"}, {"key": "pragmatic"}]))
        probes.append(dict(QUESTION, options=[{"key": []}, {"key": {}}]))
        for probe in probes:
            with self.subTest(probe=repr(probe)[:90]):
                try:
                    problems = pas.check_admissible(probe)
                except pas.TrackerError:
                    continue
                except Exception as escaped:    # noqa: BLE001 - that is the claim
                    raise AssertionError(
                        f"{type(escaped).__name__}({escaped}) escaped "
                        "check_admissible; nothing outside TrackerError may "
                        "leave this module") from escaped
                self.assertIsInstance(problems, list)
                self.assertEqual(len(set(problems)), len(problems),
                                 "a fault was reported twice; the list is a set "
                                 "of faults and a repeat reads as two problems")
                for problem in problems:
                    self.assertIsInstance(problem, str)


class ReadingAssignments(unittest.TestCase):
    """The rule that manufactures independence, and its frozenness.

    Three instances of one model reading one payload are not three independent
    samples — they are one prior sampled three times. What decorrelates them is
    a different PLACE TO LOOK, never a different question and never a hint
    about an answer.
    """

    def test_there_is_one_assignment_per_brain_and_it_is_index_addressed(self):
        self.assertEqual(len(pas.READING_ASSIGNMENTS), 3)
        self.assertEqual(len(pas.READING_ASSIGNMENTS), pas._BRAINS)
        for index, assignment in enumerate(pas.READING_ASSIGNMENTS):
            with self.subTest(index=index):
                self.assertEqual(assignment["index"], index)

    def test_each_assignment_names_a_source_and_never_an_answer(self):
        self.assertEqual(
            [assignment["label"] for assignment in pas.READING_ASSIGNMENTS],
            ["spec-and-intent", "code-and-tests", "decisions-and-plan"])
        self.assertEqual(
            [tuple(assignment["read"]) for assignment in pas.READING_ASSIGNMENTS],
            [("spec", "intent-brief"), ("repo", "tests"),
             ("decisions-effective", "phase-plan")])

    def test_no_two_brains_are_sent_to_the_same_shelf(self):
        """The whole mechanism. Two brains reading one source are two samples
        of one prior again, and the rung distribution stops being the drift
        signature it is read as.
        """
        sources = [source for assignment in pas.READING_ASSIGNMENTS
                   for source in assignment["read"]]
        self.assertEqual(len(sources), len(set(sources)))

    def test_the_assignment_rule_is_frozen(self):
        """A controller that can write its own assignment rule can change what
        a brain was asked after the fact. Frozen at the language level, both
        ways: the mapping refuses a write and the tuple refuses a swap.
        """
        with self.assertRaises(TypeError):
            pas.READING_ASSIGNMENTS[0]["read"] = ("repo",)
        with self.assertRaises(TypeError):
            pas.READING_ASSIGNMENTS[0] = {"index": 0, "label": "x", "read": ()}


class BuildPayload(unittest.TestCase):
    """The exact material one brain receives.

    Everything here is a statement about ONE function's purity, because the
    partial-quorum recovery path rests on it: a re-dispatch of brain n must be
    reproducible from ``(payload_digest, n)``, and that holds only while the
    assignment is a frozen constant and nothing about the payload is read from
    the tracker or from run state.
    """

    def setUp(self):
        self.root, self.run_dir = repo_with_a_run(self)
        self.qid = pas.derive_qid(QUESTION["question"], QUESTION["axis"])
        self.assertEqual(self.qid, QID)
        self.write_record()
        self.payloads = [pas.build_payload(self.qid, index, run_dir=str(self.run_dir))
                         for index in range(3)]

    def write_record(self, text=None, qid=None):
        directory = self.run_dir / "quorum" / (qid or self.qid)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "question.md").write_text(
            question_text() if text is None else text, encoding="utf-8")
        return directory

    def rebuild(self, text=None, qid=None, index=0):
        self.write_record(text=text, qid=qid)
        return pas.build_payload(qid or self.qid, index, run_dir=str(self.run_dir))

    def test_the_question_is_identical_across_all_three_brains(self):
        """Fair comparison requires it. Three brains asked three paraphrases
        have not disagreed about an answer; they have answered three questions.
        """
        questions = {payload["question"] for payload in self.payloads}
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions.pop(), QUESTION["question"])

    def test_the_reading_assignments_differ(self):
        labels = [payload["reading_assignment"]["label"] for payload in self.payloads]
        self.assertEqual(len(set(labels)), 3)
        self.assertEqual(labels, ["spec-and-intent", "code-and-tests",
                                  "decisions-and-plan"])

    def test_each_assignment_is_the_frozen_rule_applied_to_the_records_roots(self):
        """The purity claim, stated as an equation rather than as a shape.

        Computed here from the frozen constant and the payload's own roots, so
        a ``build_payload`` that consulted the tracker, the clock or the
        dispatch history to choose an assignment fails — which is the only
        thing standing between the recovery path and re-sending a brain a
        payload it never received.
        """
        for index, payload in enumerate(self.payloads):
            with self.subTest(index=index):
                assignment = pas.READING_ASSIGNMENTS[index]
                self.assertEqual(payload["reading_assignment"], {
                    "label": assignment["label"],
                    "read": [{"source": source,
                              "root": payload["reading_roots"][source]}
                             for source in assignment["read"]],
                })

    def test_every_assigned_brain_is_sent_somewhere_real(self):
        """A root that came back empty would send that brain nowhere, and a
        brain that read nowhere reports exactly what a brain that looked and
        found nothing reports — which is the signature the rung distribution is
        read for.
        """
        for payload in self.payloads:
            for item in payload["reading_assignment"]["read"]:
                with self.subTest(source=item["source"]):
                    self.assertTrue(item["root"].strip())

    def test_the_payload_never_carries_the_raisers_candidates(self):
        """The whitelist, proved against a record that really carries them."""
        record = QUESTION_RECORD.read_text(encoding="utf-8")
        for secret in ("worker-7", "because we already run it", "Recommendation"):
            self.assertIn(secret, record,
                          "the fixture does not carry the material these "
                          "assertions claim is dropped, so they prove nothing")
        for payload in self.payloads:
            rendered = json.dumps(payload)
            self.assertNotIn("worker-7", rendered)
            self.assertNotIn("because we already run it", rendered)
            self.assertNotIn("recommendation", rendered.casefold())
            self.assertNotIn("candidate", rendered.casefold())

    def test_the_payload_never_carries_the_floor_or_any_rung_value(self):
        """A brain that knows the bar clears the bar.

        The values are read off ``RUNGS`` rather than typed out, so a ladder
        that gains a rung gains the screen for it on the same day.
        """
        leaks = [str(value) for value in pas.RUNGS.values()]
        leaks.extend(("adoption_floor", "floor", "budget", "elapsed", "deadline",
                      "cost"))
        self.assertIn("0.85", leaks)
        for payload in self.payloads:
            rendered = json.dumps(payload).casefold()
            for leak in leaks:
                with self.subTest(leak=leak):
                    self.assertNotIn(leak.casefold(), rendered)

    def test_a_question_quoting_the_ladder_is_refused_rather_than_stripped(self):
        """The hole the field whitelist cannot close.

        ``question`` is projected verbatim — it has to be — so a raiser who
        writes the bar into it hands the bar to all three brains through a
        field the whitelist has already approved. Screened at parse time, with
        exactly the screen ``parse_decisions`` runs over ``decisions.md``, and
        a hit is a STOP: editing the question silently would leave the record
        and what the brains were asked disagreeing.
        """
        for spelling in ("Which engine? we need 0.85 grounding",
                         "Which engine? code-evidenced at least",
                         "Which engine, at .85 or better?"):
            with self.subTest(question=spelling):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.parse_question(question_text(question=spelling))
        with self.subTest(option="a rung name as an option key"):
            with self.assertRaises(pas.QuorumSchemaInvalid):
                pas.parse_question(
                    question_text(options="postgres, convention-cited"))
        #: The accept half: ordinary prose that merely resembles the ladder.
        self.assertEqual(
            pas.parse_question(question_text(
                question="Which engine handles 85 open connections?"))["question"],
            "Which engine handles 85 open connections?")

    def test_the_payload_offers_rung_names_so_a_brain_can_select_one(self):
        for payload in self.payloads:
            self.assertEqual(tuple(payload["rungs"]), pas.RUNG_ORDER)

    def test_a_brain_index_outside_the_three_is_refused(self):
        """Including the indices that are integers only by accident. ``True``
        is ``1`` in every comparison Python makes, so a flag that reached here
        would silently be dispatched as brain 1.
        """
        for index in (3, -1, 4, True, False, "0", 1.0, None, [0], 1.5):
            with self.subTest(brain_index=repr(index)):
                with self.assertRaises(pas.QuorumError):
                    pas.build_payload(self.qid, index, run_dir=str(self.run_dir))

    def test_the_three_payloads_differ_only_in_the_assignment_block(self):
        shared = []
        for payload in self.payloads:
            stripped = dict(payload)
            stripped.pop("reading_assignment")
            shared.append(json.dumps(stripped, indent=2, sort_keys=True))
        self.assertEqual(len(set(shared)), 1)
        #: And the block that was stripped really did differ, or the case above
        #: is satisfied by three identical payloads.
        self.assertEqual(
            len({json.dumps(payload["reading_assignment"], sort_keys=True)
                 for payload in self.payloads}), 3)

    def test_one_digest_binds_all_three_and_rebuilds_each_byte_for_byte(self):
        """THE ASSERTION THE PARTIAL-RECOVERY RULE RESTS ON.

        Nothing else in the design checks it: a re-dispatch of brain n must be
        reproducible from ``(payload_digest, n)``. It stops holding the moment
        ``build_payload`` reads anything from the tracker or from run state.
        """
        digest = pas.payload_digest(self.qid, run_dir=str(self.run_dir))
        rendered = [json.dumps(payload, indent=2, sort_keys=True)
                    for payload in self.payloads]
        for index in range(3):
            rebuilt = pas.build_payload(self.qid, index, run_dir=str(self.run_dir))
            self.assertEqual(json.dumps(rebuilt, indent=2, sort_keys=True),
                             rendered[index])
        self.assertEqual(pas.payload_digest(self.qid, run_dir=str(self.run_dir)),
                         digest)

    def test_the_digest_is_the_one_spelling_the_quorum_row_accepts(self):
        """``_validate_quorum`` refuses a ``Payload Digest`` cell that is not
        lowercase sha256 hex, so a digest of any other width is a value this
        module computes and its own tracker will not hold.
        """
        digest = pas.payload_digest(self.qid, run_dir=str(self.run_dir))
        self.assertTrue(pas._SHA256.fullmatch(digest), digest)

    def test_the_digest_covers_the_decisions_projection(self):
        """A projection whose text changed is a different context, and the
        responses on disk were answers to the old one. The payload itself does
        NOT change with it — the projection is context, not question — so both
        halves are stated.
        """
        before = pas.payload_digest(self.qid, run_dir=str(self.run_dir))
        projection = self.run_dir / "decisions-effective.md"
        self.assertFalse(projection.exists())
        projection.write_text("## H-001\n\n- **Answer:** postgres\n", encoding="utf-8")
        after = pas.payload_digest(self.qid, run_dir=str(self.run_dir))
        self.assertNotEqual(before, after)
        self.assertEqual(
            json.dumps(pas.build_payload(self.qid, 0, run_dir=str(self.run_dir)),
                       sort_keys=True),
            json.dumps(self.payloads[0], sort_keys=True))

    def test_the_digest_moves_when_the_question_does(self):
        """The accept half of the case above: a digest that never moved would
        satisfy "one digest binds all three" by binding nothing.
        """
        before = pas.payload_digest(self.qid, run_dir=str(self.run_dir))
        self.write_record(text=question_text(
            options="postgres, sqlite, mysql",
            reading_roots=QUESTION_FIELDS[9][1].replace("tests=tests", "tests=t")))
        self.assertNotEqual(
            pas.payload_digest(self.qid, run_dir=str(self.run_dir)), before)

    def test_a_field_nobody_whitelisted_is_unreachable_rather_than_filtered(self):
        """WHY IT IS A WHITELIST. A filter can be defeated by a new field.

        The record grows a field that carries the adoption floor, the budget and
        the raiser's preference. The payload is byte-identical to the payload
        built before the field existed, at two layers: ``parse_question`` names
        the fields it reads and ``_shared_payload`` names the keys it emits.
        """
        grown = question_text(extra=(
            "- **Adoption floor:** 0.85",
            "- **Drift budget remaining:** 2",
            "- **Raiser prefers:** postgres, obviously",
            "- **Elapsed:** 41 minutes",
        ))
        self.assertIn("0.85", grown)
        rebuilt = self.rebuild(text=grown)
        self.assertEqual(json.dumps(rebuilt, sort_keys=True),
                         json.dumps(self.payloads[0], sort_keys=True))

    def test_the_projection_is_cited_the_way_effective_rung_resolves_it(self):
        """THE TASK 3 CORRECTION, and the failure it prevents is invisible.

        ``effective_rung`` resolves ``evidence[].path`` against the RECORDED
        repository root. Hand a brain the bare ``decisions-effective.md`` and
        every decision citation resolves to ``<repo_root>/decisions-effective.md``,
        which does not exist — and a citation that does not resolve demotes
        silently. Since ``specified`` requires a spec, intent-brief or decision
        anchor, the top rung becomes unreachable and the run escalates every
        question it is ever asked while looking correctly cautious.
        """
        cited = self.payloads[0]["decisions_effective"]
        self.assertNotEqual(cited, "decisions-effective.md")
        self.assertFalse(Path(cited).is_absolute())
        self.assertEqual((self.root / cited).resolve(),
                         (self.run_dir / "decisions-effective.md").resolve())
        #: And brain 2, the one actually sent to read it, is sent to the same
        #: place — one spelling, so the two cannot disagree.
        self.assertEqual(self.payloads[2]["reading_roots"]["decisions-effective"],
                         cited)
        self.assertEqual(
            self.payloads[2]["reading_assignment"]["read"][0],
            {"source": "decisions-effective", "root": cited})

    def test_the_raiser_may_not_state_where_the_projection_lives(self):
        """Two spellings of one path is one path too many: the raiser's copy is
        where brain 2 would be sent while the payload cites the other, and the
        disagreement surfaces only as citations that will not resolve.
        """
        with self.assertRaises(pas.QuorumSchemaInvalid):
            pas.parse_question(question_text(
                reading_roots=QUESTION_FIELDS[9][1]
                + ", decisions-effective=decisions-effective.md"))

    def test_a_reading_root_a_brain_is_assigned_to_must_exist(self):
        """A missing root is the silent case: the brain is handed nothing,
        reports no grounding, and the rung distribution reads as drift.
        """
        for source in ("spec", "intent-brief", "repo", "tests", "phase-plan"):
            with self.subTest(source=source):
                roots = ", ".join(
                    f"{name}={path}"
                    for name, path in QUESTION["reading_roots"].items()
                    if name != source)
                with self.assertRaises(pas.QuorumSchemaInvalid) as caught:
                    pas.parse_question(question_text(reading_roots=roots))
                self.assertIn(source, str(caught.exception))

    def test_a_reading_root_that_escapes_the_repository_is_refused(self):
        """A brain sent outside the recorded root produces citations
        ``effective_rung`` must refuse, and a refused citation demotes without
        raising.
        """
        for path in ("/etc", "../outside", "docs/../../elsewhere", "C:\\repo"):
            with self.subTest(root=path):
                with self.assertRaises(pas.QuorumSchemaInvalid):
                    pas.parse_question(question_text(
                        reading_roots=QUESTION_FIELDS[9][1].replace(
                            "repo=.", f"repo={path}")))
        #: The accept half: the repository itself, and a nested directory.
        self.assertEqual(
            pas.parse_question(question_text(
                reading_roots=QUESTION_FIELDS[9][1].replace(
                    "repo=.", "repo=src/app")))["reading_roots"]["repo"],
            "src/app")

    def test_a_record_filed_under_another_questions_identity_is_refused(self):
        """A directory can be copied, renamed, or half-restored from a backup.
        A record whose own question and axis do not hash to the qid it is filed
        under produces responses, digests and a decision that all look
        well-formed and all belong to a question nobody asked.
        """
        other = pas.derive_qid("Which cache backend?", "cache-backend")
        self.assertNotEqual(other, self.qid)
        self.write_record(text=question_text(), qid=other)
        with self.assertRaises(pas.QuorumSchemaInvalid) as caught:
            pas.build_payload(other, 0, run_dir=str(self.run_dir))
        self.assertIn(self.qid, str(caught.exception))

    def test_an_inadmissible_record_never_becomes_a_payload(self):
        """A payload is a dispatch. Building one for a question the run has
        already decided it may not ask spends three brains and a decision
        record on it anyway.
        """
        with self.assertRaises(pas.QuorumSchemaInvalid) as caught:
            self.rebuild(text=question_text(owners="brain-a, brain-b"))
        self.assertIn("owner-count-is-not-three", str(caught.exception))

    def test_a_missing_or_unreadable_record_stops_inside_the_family(self):
        directory = self.run_dir / "quorum" / self.qid
        (directory / "question.md").unlink()
        with self.assertRaises(pas.QuorumError):
            pas.build_payload(self.qid, 0, run_dir=str(self.run_dir))
        with self.assertRaises(pas.QuorumError):
            pas.payload_digest(self.qid, run_dir=str(self.run_dir))
        (directory / "question.md").write_bytes(b"\xff\xfe not utf-8 \xff")
        with self.assertRaises(pas.QuorumError):
            pas.build_payload(self.qid, 0, run_dir=str(self.run_dir))

    def test_a_record_with_no_single_question_in_it_is_refused(self):
        """A file holding two questions has no single identity, and a file
        holding none states a question nothing can be keyed by.

        The two-section case uses DISTINCT headings deliberately: two identical
        headings are already refused by ``_decision_sections``, so a case built
        from them would pass against a reader that accepted any number of
        sections above zero.
        """
        for text, why in (("", "no section at all"),
                          (question_text()
                           + question_text(heading="## Q-other — Cache backend"),
                           "two sections"),
                          ("- **Question:** orphaned field\n", "no heading")):
            with self.subTest(record=why):
                with self.assertRaises(pas.TrackerError):
                    pas.parse_question(text)

    def test_one_source_may_not_name_two_places_to_look(self):
        """One of the two is where that brain is sent and nothing says which."""
        with self.assertRaises(pas.QuorumSchemaInvalid):
            pas.parse_question(question_text(
                reading_roots=QUESTION_FIELDS[9][1] + ", repo=src"))

    def test_a_brain_assigned_to_an_unstated_root_is_refused_not_sent_nowhere(self):
        """The second guard on the same fact, at the seam that outlives the first.

        ``parse_question`` refuses a record that omits a root some brain is
        assigned to, so this can only be reached by widening the assignment
        rule — which is exactly the day it matters. The failure it prevents is
        silent twice over: ``roots.get(source, "")`` dispatches a brain to
        nowhere, and its empty-handed answer is indistinguishable from a brain
        that looked and found nothing.
        """
        thinner = tuple(source for source in pas._DECLARED_ROOTS
                        if source != "tests")
        self.assertNotIn("tests", thinner)
        roots = ", ".join(f"{name}={path}"
                          for name, path in QUESTION["reading_roots"].items()
                          if name != "tests")
        with mock.patch.object(pas, "_DECLARED_ROOTS", thinner):
            self.write_record(text=question_text(reading_roots=roots))
            with self.assertRaises(pas.QuorumError) as caught:
                pas.build_payload(self.qid, 1, run_dir=str(self.run_dir))
            self.assertIn("tests", str(caught.exception))
            #: The brains that were not assigned to it are unaffected.
            self.assertEqual(
                pas.build_payload(self.qid, 0, run_dir=str(self.run_dir))
                ["reading_assignment"]["label"], "spec-and-intent")

    def test_nothing_outside_the_tracker_error_family_escapes_the_payload_builders(self):
        """``run_dir`` and ``qid`` are the two arguments a caller most often
        loses track of, and ``Path(5)`` raises ``TypeError`` — outside this
        module's family, so it escapes every handler a controller has written.
        """
        for run_dir in (5, None, [], {}, True, b"bytes"):
            for call in (lambda value: pas.build_payload(self.qid, 0, run_dir=value),
                         lambda value: pas.payload_digest(self.qid, run_dir=value)):
                with self.subTest(run_dir=repr(run_dir), call=call):
                    with self.assertRaises(pas.TrackerError):
                        call(run_dir)
        for qid in (None, 5, [], {}, "", "   ", True):
            with self.subTest(qid=repr(qid)):
                with self.assertRaises(pas.TrackerError):
                    pas.build_payload(qid, 0, run_dir=str(self.run_dir))

    def test_a_run_outside_its_recorded_repository_cannot_cite_its_own_files(self):
        """``_run_relative`` reads the root back and refuses to guess.

        A run directory that does not lie inside the recorded root has no
        repo-root-relative spelling at all, and inventing one would hand every
        brain a path whose citations can only be refused.
        """
        elsewhere = Path(tempfile.mkdtemp(prefix="pipeline-auto-outside-"))
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        run_dir = elsewhere / "run"
        run_dir.mkdir()
        pas.initialize_run(run_dir, **{**NEW_RUN, "repo_root": str(self.root)})
        directory = run_dir / "quorum" / self.qid
        directory.mkdir(parents=True)
        (directory / "question.md").write_text(question_text(), encoding="utf-8")
        with self.assertRaises(pas.QuorumError) as caught:
            pas.build_payload(self.qid, 0, run_dir=str(run_dir))
        self.assertIn("repo_root", str(caught.exception))

    def test_the_payload_serialization_is_injective_over_what_it_carries(self):
        """The digest binds nothing that two different payloads can share.

        Concatenation is the whole failure mode: ``["ab", "c"]`` and
        ``["a", "bc"]`` are one string apart under a naive join, and a digest
        that cannot tell them apart binds a brain to the wrong question.
        """
        pairs = (
            (["ab", "c"], ["a", "bc"]),
            #: The pair a TAG without a LENGTH cannot tell apart: "s"+"a" then
            #: "s"+"sb" is the same run of characters as "s"+"as" then "s"+"b".
            (["a", "sb"], ["as", "b"]),
            ({"a": "bc"}, {"ab": "c"}),
            ({"a": ""}, {"a": [], "": ""}),
            ([1, 2], ["1", "2"]),
            ([True], [1]),
            ([None], ["null"]),
            ({"a": {"b": "c"}}, {"a": {"b": "c", "": ""}}),
        )
        for left, right in pairs:
            with self.subTest(left=repr(left), right=repr(right)):
                self.assertNotEqual(pas._canonical(left), pas._canonical(right))
        self.assertEqual(pas._canonical({"b": 1, "a": 2}),
                         pas._canonical({"a": 2, "b": 1}))


if __name__ == "__main__":
    unittest.main()
