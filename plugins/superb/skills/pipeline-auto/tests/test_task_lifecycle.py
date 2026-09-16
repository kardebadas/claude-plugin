"""P04 task-lifecycle tests for pipeline-auto, and the shared P04 harness.

Standard library only: ``pytest`` is NOT installed on this machine. Run with

    python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v

Every assertion is a method on a ``unittest.TestCase``. A bare ``def test_*``
at module level is collected by nothing at all, which is the failure mode a
plan drafted against ``pytest`` walks straight into.

The module is imported through ``sys.path`` rather than through
``importlib.util.module_from_spec``, and the difference is not cosmetic.
``module_from_spec`` does not register in ``sys.modules``, so this file and
``test_pipeline_auto_state.py`` would hold TWO distinct module objects with two
distinct ``PlanMetadataError`` classes -- and a later P04 task that reached for
a fixture from the other file would find its ``assertRaises`` silently unable
to match. One path, one module, one exception hierarchy.
"""
from __future__ import annotations

import contextlib
import itertools
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import pipeline_auto_state as state  # noqa: E402


# --------------------------------------------------------------------------
# Shared harness. Every later P04 task reuses these.
# --------------------------------------------------------------------------

#: One valid value per pinned phase key. Kept as a mapping so a grammar test
#: can reorder, drop or rename exactly ONE thing and leave everything else
#: valid -- which is the only way a rejection proves what it claims. A fixture
#: that dropped ``review_class`` and also mangled ``deps`` would be refused for
#: either reason and would distinguish neither.
PHASE_VALUES = {
    "id": "P04",
    "deps": "none",
    "review_class": "required",
    "review_reason": "task lifecycle is security-relevant",
}

DEFAULT_COMMANDS = '["python3 -m unittest discover -s tests"]'


def phase_line(order=None, **overrides) -> str:
    """The phase metadata comment, with the key order under the caller's control.

    AN UNKNOWN OVERRIDE IS A ``KeyError``, not a silent no-op.
    ``dict(PHASE_VALUES, **overrides)`` accepts any keyword and then never
    reads one that is not a pinned key, so ``phase_line(review_gate="x")``
    returned the DEFAULT, entirely valid header: a test asserting a rejection
    would be asserting it about a header with nothing wrong with it, and one
    asserting an acceptance would go green having exercised nothing. That is
    the "helper one field short of the fixture" failure this build has already
    paid for three times. ``suite_line`` raises ``KeyError`` on the same
    mistake through its ``order`` lookup, so the two halves of the harness now
    agree. Tasks 2-12 inherit this helper.
    """
    unknown = sorted(set(overrides) - set(PHASE_VALUES))
    if unknown:
        raise KeyError(
            f"phase_line has no field {unknown}; the pinned phase keys are "
            f"{sorted(PHASE_VALUES)} and an override that names none of them "
            "would be accepted, dropped, and never noticed")
    values = dict(PHASE_VALUES, **overrides)
    keys = tuple(order) if order is not None else state._PHASE_KEYS
    fields = "; ".join(f"{key}={values[key]}" for key in keys)
    return f"<!-- pipeline-auto-phase: {fields} -->"


def suite_line(phase_id: str = "P04", commands: str = DEFAULT_COMMANDS,
               order=("id", "commands")) -> str:
    values = {"id": phase_id, "commands": commands}
    fields = "; ".join(f"{key}={values[key]}" for key in order)
    return f"<!-- pipeline-auto-phase-suite: {fields} -->"


def phase_header(
    *,
    phase_id: str = "P04",
    deps: str = "none",
    review_class: str = "required",
    review_reason: str = "task lifecycle is security-relevant",
    commands: str = DEFAULT_COMMANDS,
) -> str:
    """The two-comment document header, always in the pinned key order."""
    return (
        phase_line(id=phase_id, deps=deps, review_class=review_class,
                   review_reason=review_reason)
        + "\n" + suite_line(phase_id, commands) + "\n"
    )


#: One valid value per pinned TASK key, for ``PHASE_VALUES``' reason and with
#: ``PHASE_VALUES``' discipline: a grammar test reorders, drops or renames
#: exactly ONE thing and leaves everything else valid, because a fixture with
#: two things wrong is refused for either and distinguishes neither.
#:
#: Every value is a STRING, including ``order``. The metadata comment is text,
#: and rendering ``1`` through an f-string is what a plan author does anyway --
#: but a test that means to write ``order=01`` or ``order=chr(0x0661)`` has to be
#: able to say so without the harness normalising it into an int first.
TASK_VALUES = {
    "id": "T1",
    "deps": "none",
    "kind": "source",
    "batch": "b1",
    "order": "1",
    "write_scope": "file:src/a.py",
    "outputs": "none",
}


def task_line(keys=None, **overrides) -> str:
    """The task metadata comment, with the key order under the caller's control.

    ``keys``, NOT ``order``, and the difference is not cosmetic: ``order`` is
    itself one of the seven pinned task keys, so ``phase_line``'s parameter name
    would make ``task_line(order=2)`` mean two incompatible things -- "render
    the keys in this sequence" and "set the order field to 2". One of the two
    readings would win silently. ``phase_line`` keeps ``order`` because no phase
    key is called that.

    AN UNKNOWN OVERRIDE IS A ``KeyError``, exactly as in ``phase_line`` and for
    the reason recorded there: ``dict(TASK_VALUES, **overrides)`` accepts any
    keyword and then reads only the pinned keys, so ``task_line(kinds="source")``
    would return the DEFAULT, entirely valid comment and a test asserting a
    rejection about it would be asserting it about a line with nothing wrong.
    """
    unknown = sorted(set(overrides) - set(TASK_VALUES))
    if unknown:
        raise KeyError(
            f"task_line has no field {unknown}; the pinned task keys are "
            f"{sorted(TASK_VALUES)} and an override that names none of them "
            "would be accepted, dropped, and never noticed")
    values = dict(TASK_VALUES, **overrides)
    rendered = tuple(keys) if keys is not None else state._TASK_KEYS
    missing = sorted(set(rendered) - set(values))
    if missing:
        raise KeyError(
            f"task_line cannot render the key(s) {missing}; to build a RENAMED "
            "key, render the pinned line and replace exactly one 'key=' "
            "substring, so that everything else is provably untouched")
    fields = "; ".join(f"{key}={values[key]}" for key in rendered)
    return f"<!-- pipeline-auto-task: {fields} -->"


def task_suite_line(task_id: str = "T1", commands: str | None = None,
                    keys=("id", "commands")) -> str:
    """The task suite comment. ``keys`` is the rendered key order, pinned by
    default and reorderable so the suite's own order bar can be tested."""
    values = {"id": task_id,
              "commands": commands or f'["python3 -m unittest -k {task_id}"]'}
    fields = "; ".join(f"{key}={values[key]}" for key in keys)
    return f"<!-- pipeline-auto-task-suite: {fields} -->"


def task_block(
    task_id: str,
    *,
    deps: str = "none",
    kind: str = "source",
    batch: str = "b1",
    order: int = 1,
    write_scope: str = "file:src/a.py",
    outputs: str = "none",
    commands: str | None = None,
    heading: str | None = None,
) -> str:
    """A whole task section: heading, metadata, suite (if source), prose.

    Expressed through ``task_line``/``task_suite_line`` rather than repeating
    their format strings, so the harness has ONE spelling of the comment and a
    later edit to the grammar cannot leave the two halves disagreeing. The
    rendered bytes are unchanged from the form Task 1 committed.
    """
    text = (heading or f"## Task {task_id}") + "\n\n" + task_line(
        id=task_id, deps=deps, kind=kind, batch=batch, order=str(order),
        write_scope=write_scope, outputs=outputs) + "\n"
    if kind == "source":
        text += task_suite_line(task_id, commands) + "\n"
    return text + "\nProse describing the task.\n\n"


def write_phase_plan(directory, body: str, *, header: str | None = None,
                     name: str = "phase-04.md") -> Path:
    path = Path(directory) / name
    path.write_text(
        "# Phase 04 plan\n\n" + (header or phase_header()) + "\n" + body,
        encoding="utf-8",
    )
    return path


class TempDirTestCase(unittest.TestCase):
    """Give every test its own scratch directory without pytest fixtures."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)


class PlanGrammarTestCase(TempDirTestCase):
    """Accept/reject helpers that keep the two halves symmetrical.

    Every stricter bar below is paired with a case that must still be ACCEPTED.
    A suite of rejections alone is satisfied by a parser that refuses
    everything, and that parser passes.
    """

    def parse_lines(self, header: str, body: str = "") -> dict:
        text = "# Phase 04 plan\n\n" + header + "\n" + (body or task_block("T1"))
        return state._parse_phase_header(text.splitlines())

    def expect_rejection(self, header: str, body: str = "") -> None:
        text = "# Phase 04 plan\n\n" + header + "\n" + (body or task_block("T1"))
        lines = text.splitlines()
        snapshot = list(lines)
        with self.assertRaises(state.PlanMetadataError):
            state._parse_phase_header(lines)
        #: A refused parse changes nothing it was given. The grammar reads no
        #: file, so byte-identity of a plan on disk is vacuous here; the list
        #: it actually touches is not.
        self.assertEqual(lines, snapshot)

    def expect_file_rejection(self, plan: Path) -> None:
        before = plan.read_bytes()
        with self.assertRaises(state.PlanMetadataError):
            state._parse_phase_header(
                plan.read_text(encoding="utf-8").splitlines())
        self.assertEqual(plan.read_bytes(), before)


# --------------------------------------------------------------------------
# Task 1 tests -- fault F8: metadata keys reordered, renamed, or missing
# `review_class`.
# --------------------------------------------------------------------------

class PhaseHeaderKeyOrderTests(PlanGrammarTestCase):
    """F8's core. The keys are PINNED in order, not merely required to exist."""

    def test_the_pinned_order_is_not_the_alphabetical_one(self):
        """The guard that keeps every test below discriminating.

        If the pinned order happened to equal the alphabetical order, a parser
        that sorted its keys -- or one that used a dict and lost order
        entirely -- would pass every reordering test in this class while doing
        nothing the grammar claims. The pin is asserted here so the fixture
        cannot silently stop testing what it says it tests.
        """
        self.assertEqual(state._PHASE_KEYS,
                         ("id", "deps", "review_class", "review_reason"))
        self.assertNotEqual(list(state._PHASE_KEYS),
                            sorted(state._PHASE_KEYS))
        self.assertEqual(len(set(state._PHASE_KEYS)), 4)

    def test_parses_the_pinned_key_order(self):
        header = self.parse_lines(phase_header())
        self.assertEqual(set(header),
                         {"id", "deps", "review_class", "review_reason",
                          "commands"})
        self.assertEqual(header["id"], "P04")
        self.assertEqual(header["deps"], ())
        self.assertEqual(header["review_class"], "required")
        self.assertEqual(header["review_reason"],
                         "task lifecycle is security-relevant")
        self.assertEqual(header["commands"],
                         ("python3 -m unittest discover -s tests",))

    def test_rejects_every_other_permutation_of_the_same_four_keys(self):
        """The whole permutation group, not a sample.

        Each header below carries ALL FOUR keys with the SAME valid values --
        the only thing that varies is their order. So a rejection here cannot
        be a rejection of a missing key, an unknown key or a bad value: it is a
        rejection of the ORDER, which is the claim.
        """
        orders = list(itertools.permutations(state._PHASE_KEYS))
        self.assertEqual(len(orders), 24)
        accepted = []
        for order in orders:
            line = phase_line(order)
            for key in state._PHASE_KEYS:
                self.assertIn(f"{key}=", line)
            header = line + "\n" + suite_line() + "\n"
            with self.subTest(order=order):
                if order == state._PHASE_KEYS:
                    self.assertEqual(self.parse_lines(header)["id"], "P04")
                    accepted.append(order)
                else:
                    self.expect_rejection(header)
        self.assertEqual(accepted, [state._PHASE_KEYS])

    def test_rejects_the_alphabetical_key_order_by_name(self):
        """Named separately from the permutation sweep because it is the order
        a dict-based or a sorted implementation produces, so it is the one a
        diagnosis most often lands on."""
        order = tuple(sorted(state._PHASE_KEYS))
        self.assertEqual(order, ("deps", "id", "review_class", "review_reason"))
        self.expect_rejection(phase_line(order) + "\n" + suite_line() + "\n")

    def test_rejects_swapping_exactly_one_adjacent_pair(self):
        """The smallest possible reordering. A parser that only checked the
        first and last key would survive the sweep above on some inputs and
        dies here."""
        for first, second in ((0, 1), (1, 2), (2, 3)):
            order = list(state._PHASE_KEYS)
            order[first], order[second] = order[second], order[first]
            with self.subTest(swapped=(order[first], order[second])):
                self.assertNotEqual(tuple(order), state._PHASE_KEYS)
                self.expect_rejection(
                    phase_line(order) + "\n" + suite_line() + "\n")


class PhaseHeaderKeyPresenceTests(PlanGrammarTestCase):
    """F8's other half: a renamed, missing, or extra key."""

    def test_rejects_each_key_dropped_in_turn_with_the_other_three_intact(self):
        """`review_class` is the named case, and it is tested the only way that
        proves anything: the other three keys are PRESENT, VALID, and in their
        pinned order, so the refusal is a refusal of the one absence."""
        for dropped in state._PHASE_KEYS:
            order = tuple(k for k in state._PHASE_KEYS if k != dropped)
            line = phase_line(order)
            with self.subTest(dropped=dropped):
                self.assertNotIn(f"{dropped}=", line)
                for kept in order:
                    self.assertIn(f"{kept}=", line)
                self.assertEqual(len(order), 3)
                self.expect_rejection(line + "\n" + suite_line() + "\n")

    def test_rejects_a_plan_missing_only_review_class(self):
        """F8, stated on its own so a failure names the fault it belongs to."""
        line = phase_line(("id", "deps", "review_reason"))
        self.assertNotIn("review_class", line)
        self.assertIn("id=P04", line)
        self.assertIn("deps=none", line)
        self.assertIn("review_reason=task lifecycle is security-relevant", line)
        self.expect_rejection(line + "\n" + suite_line() + "\n")

    def test_rejects_the_v2_review_gate_key(self):
        """A renamed key, and only the name is changed: the position, the
        value and all three neighbours are the ones a valid header carries.
        `review_gate` is v2's boolean gate; there is no migration in either
        direction, so it is refused rather than translated."""
        line = phase_line().replace("review_class=", "review_gate=")
        self.assertIn("review_gate=required", line)
        self.assertNotIn("review_class", line)
        self.assertIn("deps=none; review_gate=required; review_reason=", line)
        self.expect_rejection(line + "\n" + suite_line() + "\n")

    def test_rejects_an_extra_key_appended_after_review_reason(self):
        """All four pinned keys are present, in the pinned order, with valid
        values; the header is refused for the fifth key alone. Without this a
        free-text tail absorbs anything appended to it and the plan carries a
        key nobody validates."""
        line = phase_line()[:-len(" -->")] + "; owner=nobody -->"
        for key in state._PHASE_KEYS:
            self.assertIn(f"{key}=", line)
        self.expect_rejection(line + "\n" + suite_line() + "\n")

    def test_rejects_an_extra_key_inserted_between_pinned_keys(self):
        line = phase_line().replace("deps=none; ", "deps=none; owner=nobody; ")
        for key in state._PHASE_KEYS:
            self.assertIn(f"{key}=", line)
        self.expect_rejection(line + "\n" + suite_line() + "\n")

    def test_rejects_a_duplicated_key(self):
        line = phase_line().replace("deps=none; ", "deps=none; deps=none; ")
        self.expect_rejection(line + "\n" + suite_line() + "\n")


class ReviewClassTests(PlanGrammarTestCase):
    """The dial value itself, both halves: what it admits and what it refuses."""

    def test_review_classes_is_p02s_vocabulary_and_not_a_second_copy(self):
        """P02 already judges the `Review Class` cell against
        `_REVIEW_CLASSES`. A second literal here would be a second, divergable
        source of truth for one enum -- the defect the 'no phase re-declares
        another phase's columns' rule exists to forbid. Identity, not equality:
        equality would still pass the day someone re-typed the tuple."""
        self.assertIs(state.REVIEW_CLASSES, state._REVIEW_CLASSES)
        self.assertEqual(set(state.REVIEW_CLASSES), {"required", "final-only"})

    def test_every_member_of_the_vocabulary_is_accepted(self):
        """The ACCEPT half, derived from the constant rather than from memory,
        so widening the enum without widening this test is impossible."""
        self.assertEqual(len(state.REVIEW_CLASSES), 2)
        for review_class in state.REVIEW_CLASSES:
            with self.subTest(review_class=review_class):
                header = self.parse_lines(
                    phase_header(review_class=review_class))
                self.assertEqual(header["review_class"], review_class)

    def test_rejects_a_review_class_outside_the_vocabulary(self):
        for review_class in ("medium", "Required", "REQUIRED", "final_only",
                             "requiredx", "none", "required,final-only"):
            with self.subTest(review_class=review_class):
                self.assertNotIn(review_class, state.REVIEW_CLASSES)
                self.expect_rejection(phase_header(review_class=review_class))

    def test_rejects_an_empty_review_class(self):
        self.expect_rejection(phase_header(review_class=""))


class ReviewReasonTests(PlanGrammarTestCase):

    def test_rejects_an_empty_or_blank_review_reason(self):
        for review_reason in ("", "   ", "\t"):
            with self.subTest(review_reason=repr(review_reason)):
                self.expect_rejection(phase_header(review_reason=review_reason))

    def test_accepts_a_reason_with_spaces_and_ordinary_punctuation(self):
        reason = "reserve/resume touch the run lock -- concurrency, per fault F8"
        header = self.parse_lines(phase_header(review_reason=reason))
        self.assertEqual(header["review_reason"], reason)
        self.assertIn(" ", header["review_reason"])

    def test_rejects_a_reason_a_tracker_cell_cannot_carry(self):
        """The reason is written into a `## Phases` cell. A `|` parses back as
        a different number of columns and a newline as a different number of
        rows, so neither is a formatting quibble."""
        for reason in ("a | b", "a\tb\x00c"):
            with self.subTest(reason=repr(reason)):
                self.expect_rejection(phase_header(review_reason=reason))

    def test_rejects_a_reason_carrying_a_row_break_no_ascii_list_contains(self):
        """`\x85`, `\u2028` and `\u2029` are LINE BREAKS to `str.splitlines`
        and all three sit outside `range(0x20)`, so a closed ASCII control list
        accepts them and the rendered `## Phases` row parses back as two rows
        of the wrong width -- the exact defect `_splits_the_section` exists to
        end, re-made one layer up.

        The lines are built as a LIST rather than by splitting a document,
        because splitting the document is the very thing these characters do: a
        `splitlines()`-built fixture is refused for its SHAPE and would prove
        nothing about the cell bar.
        """
        for character in ("\x85", "\u2028", "\u2029"):
            with self.subTest(character=repr(character)):
                self.assertTrue(state._splits_the_section(character))
                self.assertNotIn(character, state._CONTROL_CHARACTERS)
                line = phase_line(review_reason=f"why{character}not")
                self.assertEqual(len(line.splitlines()), 2)
                lines = ["# Phase 04 plan", "", line, suite_line(), ""]
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_phase_header(lines)

    def test_rejects_a_reason_the_utf8_encoder_refuses(self):
        """A lone surrogate is not writable at all: the `## Phases` render, and
        every later read of it, raises `UnicodeEncodeError` -- a `ValueError`,
        outside `TrackerError` -- from one layer past this parser."""
        for character in ("\ud800", "\udfff"):
            with self.subTest(character=repr(character)):
                with self.assertRaises(UnicodeEncodeError):
                    character.encode("utf-8")
                lines = ["# Phase 04 plan", "",
                         phase_line(review_reason=f"why{character}not"),
                         suite_line(), ""]
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_phase_header(lines)

    def test_rejects_a_reason_that_closes_or_reopens_the_comment(self):
        """One byte string, two readings. An HTML comment ends at the FIRST
        `-->`, so every markdown reader -- and the human auditor the reason
        exists for -- sees the comment end early and the rest as document text,
        while this parser alone reads the whole line as metadata."""
        for reason in ("a --> b", "a<!--b", "b -->", "<!-- a"):
            with self.subTest(reason=reason):
                self.expect_rejection(phase_header(review_reason=reason))

    def test_a_reason_may_carry_a_comma(self):
        """The ACCEPT half of the ruling that `_cell_safe` does NOT screen `,`.
        `_CELL_SEPARATORS` names the comma because it re-columns a MULTI-VALUED
        cell; `review_reason` is one free-text cell a human reads, and ordinary
        English prose carries commas. The bar belongs on the writer that knows
        a cell is list-valued, not on a value screen that cannot know."""
        self.assertIn(",", state._CELL_SEPARATORS)
        reason = "reserve, resume and integrate all touch the run lock"
        self.assertEqual(
            self.parse_lines(phase_header(review_reason=reason))["review_reason"],
            reason)

    def test_rejects_a_reason_carrying_the_field_separator(self):
        """Without this, `review_reason=x; extra=y` reads as a reason of
        'x; extra=y' and a fifth key enters the grammar unnoticed."""
        self.expect_rejection(phase_header(review_reason="first; second"))


class PhaseDepsTests(PlanGrammarTestCase):

    def test_deps_keep_the_order_the_plan_wrote_them_in(self):
        """Two dependencies, deliberately NOT in sorted order, so 'preserved'
        and 'sorted' are two different answers here."""
        header = self.parse_lines(phase_header(deps="P03,P01"))
        self.assertEqual(header["deps"], ("P03", "P01"))
        self.assertNotEqual(header["deps"], tuple(sorted(header["deps"])))
        self.assertIsInstance(header["deps"], tuple)

    def test_no_dependencies_is_spelled_none_and_parses_empty(self):
        self.assertEqual(self.parse_lines(phase_header(deps="none"))["deps"], ())

    def test_rejects_malformed_dependency_lists(self):
        for deps in ("", " ", "P01, P02", " P01", "P01,", ",P01", "P01,P01",
                     "none,P01", "P01,none", "P04", "P01|P02", "P01 P02"):
            with self.subTest(deps=repr(deps)):
                self.expect_rejection(phase_header(deps=deps))

    def test_rejects_a_phase_that_depends_on_itself(self):
        """Stated separately: the fixture's phase id and the dependency are the
        same string on purpose, and a run that accepted it would wait on a
        phase that can never start."""
        self.assertEqual(PHASE_VALUES["id"], "P04")
        self.expect_rejection(phase_header(phase_id="P04", deps="P04"))
        #: And the same dependency under a different phase id is fine, so the
        #: refusal above is about the self-reference and not about "P04".
        self.assertEqual(
            self.parse_lines(phase_header(phase_id="P05", deps="P04"))["deps"],
            ("P04",))

    def test_rejects_an_invalid_phase_id(self):
        for phase_id in ("", " P04", "P 04", "P04|x", "-P04", "P04\x00"):
            with self.subTest(phase_id=repr(phase_id)):
                self.expect_rejection(phase_header(phase_id=phase_id))


class PhaseSuitePlacementTests(PlanGrammarTestCase):

    def test_the_suite_must_immediately_follow_the_phase_metadata(self):
        header = phase_line() + "\n\n" + suite_line() + "\n"
        self.expect_rejection(header)

    def test_the_suite_may_not_precede_the_phase_metadata(self):
        self.expect_rejection(suite_line() + "\n" + phase_line() + "\n")

    def test_the_suite_must_occur_exactly_once(self):
        self.expect_rejection(
            phase_line() + "\n" + suite_line() + "\n" + suite_line() + "\n")
        self.expect_rejection(phase_line() + "\n")

    def test_the_suite_identity_must_match_the_phase_metadata(self):
        """The ids differ in exactly one character and everything else about
        both comments is valid."""
        header = phase_line(id="P04") + "\n" + suite_line("P05") + "\n"
        self.expect_rejection(header)
        self.assertEqual(
            self.parse_lines(phase_line(id="P04") + "\n"
                             + suite_line("P04") + "\n")["id"], "P04")

    def test_the_suite_key_order_is_pinned_too(self):
        self.assertEqual(state._PHASE_SUITE_KEYS, ("id", "commands"))
        header = (phase_line() + "\n"
                  + suite_line(order=("commands", "id")) + "\n")
        self.assertIn("commands=", header)
        self.assertIn("id=", header)
        self.expect_rejection(header)


class PhaseHeaderPlacementTests(PlanGrammarTestCase):

    def test_metadata_must_precede_the_first_section(self):
        self.expect_rejection("## Overview\n\n" + phase_header())

    def test_an_indented_first_section_still_precedes_the_metadata(self):
        """CommonMark allows up to three leading spaces on an ATX heading, so a
        detector written on the RAW line lets a plan clear the placement bar by
        adding two spaces -- while `_comment_indexes`, one line above, detects
        on the STRIPPED line precisely so the trick does not work on the other
        side of the same comparison. A defence that strips on one side and not
        the other is not a defence.
        """
        for indent in (" ", "  ", "   "):
            with self.subTest(indent=len(indent)):
                self.expect_rejection(indent + "## Overview\n\n"
                                      + phase_header())

    def test_a_section_heading_after_the_metadata_is_fine(self):
        """The ACCEPT half: the bar is about ORDER, not about headings."""
        header = self.parse_lines(phase_header(),
                                  body="  ## Overview\n\nProse.\n")
        self.assertEqual(header["id"], "P04")

    def test_metadata_must_occur_exactly_once(self):
        self.expect_rejection(phase_header() + phase_header())

    def test_a_missing_phase_comment_is_refused(self):
        self.expect_rejection(suite_line() + "\n")

    def test_an_indented_duplicate_is_counted_rather_than_overlooked(self):
        """A `startswith` detector on the RAW line cannot see an indented copy,
        so a second phase header hides behind two spaces: present in the file,
        invisible to the 'exactly once' count, and whichever of the two a later
        reader picks up is a coin toss."""
        header = phase_header() + "  " + phase_line(id="P99") + "\n"
        self.expect_rejection(header)

    def test_an_indented_phase_comment_is_refused_outright(self):
        self.expect_rejection("  " + phase_line() + "\n" + suite_line() + "\n")

    def test_an_indented_comment_is_diagnosed_as_a_shape_error(self):
        """The opening anchor's observable effect. Drop it and an indented
        comment is still refused -- the slice shifts and the first field stops
        matching -- but it is refused as a KEY ORDER violation, which sends a
        plan author looking for a reordered key in a header whose keys are in
        the right order. The anchor is what makes the diagnosis name the shape.
        """
        with self.assertRaises(state.PlanMetadataError) as caught:
            state._comment_fields("  " + phase_line(), state._PHASE_COMMENT,
                                  state._PHASE_KEYS, tail=False)
        self.assertIn("on a line of its own", str(caught.exception))
        self.assertNotIn("key order is PINNED", str(caught.exception))

    def test_a_well_formed_comment_reaches_the_key_check(self):
        """The ACCEPT half of the anchor: a correctly shaped comment whose
        keys are wrong is diagnosed by the KEY message, not the shape one."""
        with self.assertRaises(state.PlanMetadataError) as caught:
            state._comment_fields(phase_line(tuple(sorted(state._PHASE_KEYS))),
                                  state._PHASE_COMMENT, state._PHASE_KEYS,
                                  tail=False)
        self.assertIn("key order is PINNED", str(caught.exception))
        self.assertNotIn("on a line of its own", str(caught.exception))

    def test_trailing_whitespace_on_a_metadata_line_is_refused(self):
        self.expect_rejection(phase_line() + "  \n" + suite_line() + "\n")

    def test_a_plan_must_open_with_a_level_one_title(self):
        for first in ("", "Phase 04 plan", "## Phase 04 plan", "# ", "#  #"):
            with self.subTest(first=repr(first)):
                lines = ([first] if first else []) + [""] \
                    + phase_header().splitlines() + ["", "Prose."]
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_phase_header(lines)

    def test_the_title_may_be_preceded_by_blank_lines(self):
        lines = ["", "   ", "# Phase 04 plan", ""] + phase_header().splitlines()
        self.assertEqual(state._parse_phase_header(lines)["id"], "P04")


class PhaseHeaderArgumentTotalityTests(unittest.TestCase):
    """Nothing outside `TrackerError` escapes, for any argument.

    The case list is derived from what the function actually touches -- it
    indexes, iterates, and calls `.strip()`/`.startswith()` on each element --
    rather than from a remembered fixture.
    """

    def test_a_non_sequence_argument_is_a_plan_metadata_error(self):
        for argument in (None, 7, 3.5, b"# t", {"a": 1}, {"a"}, object(),
                         iter(["# t"])):
            with self.subTest(argument=type(argument).__name__):
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_phase_header(argument)

    def test_the_document_text_is_not_a_line_list(self):
        """A string is iterable by character, so passing the whole document
        would parse as a file of one-character lines and report 'no metadata'
        instead of naming the caller's mistake."""
        text = "# t\n\n" + phase_header()
        with self.assertRaises(state.PlanMetadataError):
            state._parse_phase_header(text)

    def test_a_non_string_line_is_a_plan_metadata_error(self):
        for bad in (None, 7, b"# t", ["# t"], {"a": 1}, {"a"}):
            with self.subTest(bad=type(bad).__name__):
                lines = ["# Phase 04 plan", "", bad] \
                    + phase_header().splitlines()
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_phase_header(lines)

    def test_an_empty_plan_is_a_plan_metadata_error(self):
        for lines in ([], (), [""], ["", "   "]):
            with self.subTest(lines=lines):
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_phase_header(lines)

    def test_a_tuple_of_lines_is_accepted(self):
        lines = tuple(("# Phase 04 plan\n\n" + phase_header()).splitlines())
        self.assertEqual(state._parse_phase_header(lines)["id"], "P04")

    def test_parsing_never_mutates_the_lines_it_was_handed(self):
        lines = ("# Phase 04 plan\n\n" + phase_header() + "\n"
                 + task_block("T1")).splitlines()
        snapshot = list(lines)
        state._parse_phase_header(lines)
        self.assertEqual(lines, snapshot)


class CommandSuiteTests(PlanGrammarTestCase):

    def test_accepts_a_multi_command_suite_in_the_order_the_plan_wrote_it(self):
        """Two commands whose plan order is NOT their sorted order, so a
        parser that sorted or set-ified them would be visible here."""
        commands = '["zz make check", "aa python3 -m unittest"]'
        header = self.parse_lines(phase_header(commands=commands))
        self.assertEqual(header["commands"],
                         ("zz make check", "aa python3 -m unittest"))
        self.assertNotEqual(header["commands"],
                            tuple(sorted(header["commands"])))

    def test_rejects_malformed_command_suites(self):
        for commands in ("[]", '["a","a"]', '["a",""]', '["a","   "]',
                         '["a|b"]', '"a"', '["a"', "[", "", "null", "{}",
                         '{"a": 1}', "[1]", "[true]", "[null]", '[" a"]',
                         '["a "]', '["a\\nb"]', '["a\\u0000b"]', "[[]]",
                         '["a\\u0085b"]', '["a\\u2028b"]', '["a\\u2029b"]',
                         '["a\\ud800b"]', '["a\\udfffb"]'):
            with self.subTest(commands=commands):
                self.expect_rejection(phase_header(commands=commands))

    def test_rejects_unhashable_elements_before_it_hashes_them(self):
        """`len(values) != len(set(values))` on `["a", ["b"]]` raises
        `TypeError: unhashable`, which is outside `TrackerError` and escapes
        every `except TrackerError` a controller has written. The element type
        check has to come first, and this is what pins that it does."""
        for commands in ('["a", ["b"]]', '["a", {"b": 1}]', '[["b"], "a"]',
                         '[{"b": 1}]'):
            with self.subTest(commands=commands):
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_command_suite(commands)

    def test_a_json_failure_never_escapes_as_a_value_error(self):
        for raw in ("", "{", "[1,", "nope", "[" * 4000, 7, None, b"[]"):
            with self.subTest(raw=repr(raw)[:24]):
                try:
                    state._parse_command_suite(raw)
                except state.PlanMetadataError:
                    pass
                except BaseException as exc:  # pragma: no cover - the failure
                    self.fail(f"{raw!r} escaped as {type(exc).__name__}: {exc}")
                else:  # pragma: no cover - the failure
                    self.fail(f"{raw!r} was accepted")

    def test_a_json_escape_mints_a_row_break_from_pure_ascii_bytes(self):
        """The plan file is ASCII on disk; the parsed command is not.

        `\\u0085`, `\\u2028` and `\\u2029` are line breaks to `str.splitlines`
        and none of them is in `range(0x20)`, so the closed ASCII control list
        never sees them -- and because the escape is ASCII, the document read
        that produced these lines could not have split them off either. The
        command reaches the suite whole and re-columns whatever cell holds it.
        """
        for escape, character in (("\\u0085", "\x85"),
                                  ("\\u2028", "\u2028"),
                                  ("\\u2029", "\u2029")):
            raw = f'["make {escape} check"]'
            with self.subTest(escape=escape):
                raw.encode("ascii")   # the plan file really is plain ASCII
                self.assertTrue(state._splits_the_section(character))
                self.assertNotIn(character, state._CONTROL_CHARACTERS)
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_command_suite(raw)

    def test_a_json_escape_mints_a_lone_surrogate_from_pure_ascii_bytes(self):
        """The escape this grammar's totality promise is defeated by.

        `commands=["make \\ud800 check"]` is a plain-ASCII plan file. The
        parse succeeds; the FAILURE lands a layer along, when the command is
        written to a utf-8 file or encoded for the subprocess, as
        `UnicodeEncodeError` -- a `ValueError`, outside `TrackerError`, exactly
        the family `_loads` exists to keep out.
        """
        for escape in ("\\ud800", "\\udbff", "\\udc00", "\\udfff"):
            raw = f'["make {escape} check"]'
            with self.subTest(escape=escape):
                raw.encode("ascii")
                with self.assertRaises(UnicodeEncodeError):
                    json.loads(raw)[0].encode("utf-8")
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_command_suite(raw)

    def test_rejects_a_command_that_closes_or_reopens_the_comment(self):
        """The suite comment is the same byte string with the same two
        readings; `commands` is the trailing free-text field, so nothing else
        would have stopped it."""
        for commands in ('["make --> check"]', '["make <!-- check"]'):
            with self.subTest(commands=commands):
                self.expect_rejection(phase_header(commands=commands))

    def test_accepts_a_single_command_and_returns_a_tuple(self):
        parsed = state._parse_command_suite('["python3 -m unittest"]')
        self.assertEqual(parsed, ("python3 -m unittest",))
        self.assertIsInstance(parsed, tuple)

    def test_a_command_may_carry_the_field_separator(self):
        """`commands` is the one value allowed to contain `'; '`: it is the
        trailing field, and a shell command legitimately carries a semicolon.
        The trailing-junk case is still refused, by JSON rather than by the
        splitter -- `commands=["a"]; extra=y` is not readable JSON."""
        header = self.parse_lines(phase_header(commands='["a; b"]'))
        self.assertEqual(header["commands"], ("a; b",))
        self.expect_rejection(phase_header(commands='["a"]; extra=y'))


class SafeRelativeTests(unittest.TestCase):

    def test_accepts_a_canonical_repository_relative_path(self):
        self.assertEqual(state._safe_relative("src/pkg/a.py").as_posix(),
                         "src/pkg/a.py")
        self.assertIsInstance(state._safe_relative("src"), PurePosixPath)

    def test_rejects_unsupported_paths(self):
        for value in ("/abs/path", "../escape", "a/../b", "src/*.py", "",
                      "a\\b", "src/./a", "a//b", "src/a/", "/", ".", "..",
                      "src/a b/c.py|x", "src/[a].py", "src/{a}.py", "src/a?.py",
                      " src/a.py", "src/a.py ", "src/ a/b.py", "src/a /b.py",
                      "src/a\nb", "src/a\x00b", "src/a\tb",
                      "src/a\x85b", "src/a\u2028b", "src/a\u2029b",
                      "src/a\ud800b", "src/a\udfffb"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(state.PlanMetadataError):
                    state._safe_relative(value)

    def test_the_dot_segment_is_caught_only_because_the_raw_value_is_checked(self):
        """The defect this pins: `PurePosixPath` NORMALISES on construction, so
        a check written over `.parts` never sees the `.` or the empty segment
        it means to refuse. Both halves are asserted, so a rewrite back to
        `.parts` fails here with its reason on screen."""
        self.assertEqual(PurePosixPath("src/./a").parts, ("src", "a"))
        self.assertEqual(PurePosixPath("a//b").parts, ("a", "b"))
        self.assertEqual(PurePosixPath("src/a/").parts, ("src", "a"))
        self.assertNotIn(".", PurePosixPath("src/./a").parts)
        for value in ("src/./a", "a//b", "src/a/"):
            with self.subTest(value=value):
                with self.assertRaises(state.PlanMetadataError):
                    state._safe_relative(value)

    def test_the_comment_delimiter_bar_is_upstream_and_not_repeated_here(self):
        """`src/a-->b` is a legal path to this predicate ON PURPOSE.

        A path only ever reaches the module inside a metadata comment's
        `write_scope=` field, and `_comment_fields` refuses a body carrying
        `-->` or `<!--` for EVERY field value at once -- which is where the
        defect actually lives, since the damage is that a markdown reader ends
        the comment early. Repeating the bar here would be a second copy of one
        rule; asserting both halves is what keeps the upstream one honest.
        """
        self.assertEqual(state._safe_relative("src/a-->b").as_posix(),
                         "src/a-->b")
        with self.assertRaises(state.PlanMetadataError):
            state._comment_fields(
                "<!-- pipeline-auto-phase-suite: id=P04; "
                'commands=["cp src/a-->b /tmp"] -->',
                state._PHASE_SUITE_COMMENT, state._PHASE_SUITE_KEYS, tail=True)

    def test_rejects_non_string_arguments_without_leaving_the_family(self):
        for value in (None, 7, 3.5, b"src/a.py", ["src/a.py"], {"a": 1}, {"a"},
                      PurePosixPath("src/a.py")):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(state.PlanMetadataError):
                    state._safe_relative(value)

    def test_a_dotfile_and_a_dotted_segment_are_still_ordinary_paths(self):
        """The ACCEPT half of the `.`-segment bar: `..` and a bare `.` are
        traversal, `.github` and `a.b.py` are not, and a check written as
        'contains a dot' would lose the difference."""
        for value in (".github/workflows/ci.yml", "src/a.b.py", "src/.keep",
                      "a-b_c/d.py"):
            with self.subTest(value=value):
                self.assertEqual(state._safe_relative(value).as_posix(), value)


class CellSafetyTests(unittest.TestCase):
    """`_cell_safe`'s rule is a UNION of a derived half and a listed half.

    The whole class exists because the P04 fixtures that preceded it all lay
    inside `range(0x20)`, where a closed ASCII list and the module's own
    derived rule give identical answers -- so the suite pinned the weaker of
    the two by coincidence, and the module re-declared as a written-down list
    the very thing `_splits_the_section`'s docstring records as having been
    wrong when it was written down.
    """

    def test_every_character_the_section_reader_breaks_on_is_refused(self):
        """Derived from the READER, not from a fixture list.

        `str.splitlines` breaks on ten characters and five of them are outside
        `range(0x20)`. The corpus is swept out of `_splits_the_section` itself,
        so a Python that adds an eleventh widens this test the same day it
        widens the danger -- and restoring a closed ASCII list fails here with
        the missing characters named.
        """
        breakers = [chr(code) for code in range(0x2100)
                    if state._splits_the_section(chr(code))]
        self.assertEqual(len(breakers), 10)
        self.assertTrue(set(breakers) - state._CONTROL_CHARACTERS)
        for character in breakers:
            with self.subTest(character=repr(character)):
                self.assertFalse(state._cell_safe(f"a{character}b"))

    def test_the_listed_half_is_not_derivable_and_is_still_refused(self):
        """The other direction: `\x00` and `\t` break a subprocess and a
        cell's width without breaking a LINE, so no reader derives them. A
        rewrite to `_splits_the_section` ALONE loses both, which is why the fix
        is a union rather than a replacement."""
        for character in ("\x00", "\t", "\x7f", "\x01"):
            with self.subTest(character=repr(character)):
                self.assertFalse(state._splits_the_section(character))
                self.assertIn(character, state._CONTROL_CHARACTERS)
                self.assertFalse(state._cell_safe(f"a{character}b"))

    def test_nothing_the_utf8_encoder_refuses_is_cell_safe(self):
        for code in (0xD800, 0xDBFF, 0xDC00, 0xDFFF):
            character = chr(code)
            with self.subTest(code=hex(code)):
                self.assertFalse(state._survives_the_encoder(character))
                self.assertFalse(state._cell_safe(f"a{character}b"))

    def test_ordinary_text_is_still_cell_safe(self):
        """The ACCEPT half. A screen that refused everything would satisfy
        every assertion above."""
        for value in ("a b", "make check", "reserve, resume -- concurrency",
                      "src/pkg/a.py", "P04", "a\u00e9b", "a\u4e2db", "-"):
            with self.subTest(value=value):
                self.assertTrue(state._cell_safe(value))

    def test_the_comma_is_a_ruling_and_not_an_oversight(self):
        """`,` is named in `_CELL_SEPARATORS` and is deliberately NOT screened
        here: this predicate is shared by values that are not all multi-valued,
        and it cannot know which. Asserted so that adding a comma bar is a
        decision somebody makes on purpose rather than a tidy-up."""
        self.assertIn(",", state._CELL_SEPARATORS)
        self.assertTrue(state._cell_safe("a, b"))
        with self.assertRaises(state.QuorumSchemaInvalid):
            state._cell("a, b", "a list-valued cell")


class ModuleBoundaryTests(unittest.TestCase):
    """What P04 must NOT have done to the module it extends."""

    def test_token_is_still_p02s_hand_written_grammar(self):
        """`_TOKEN` is P02's, defined once and used at ~20 call sites. A P04
        block that rebound it to a compiled pattern would silently narrow every
        one of them -- `@`, `:` and `+` all leave the grammar -- so the pin is
        the type AND the characters."""
        self.assertIsInstance(state._TOKEN, state._CharClass)
        for value in ("P04", "feature/x", "a@b", "a:b", "a+b", "a.b", "a-b"):
            self.assertTrue(state._TOKEN.fullmatch(value), value)
        for value in ("", " a", "a b", "-a", "a|b"):
            self.assertFalse(state._TOKEN.fullmatch(value), value)

    def test_the_grammar_is_stated_without_a_regex_engine(self):
        """`re` left `ALLOWED_IMPORTS` on purpose; the allowlist is a
        capability boundary of exactly twelve. A P04 block that imported `re`
        would widen it for three patterns the module can state directly."""
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        self.assertNotIn("\nimport re\n", source)
        self.assertNotIn("\nimport re,", source)
        self.assertNotIn("re.compile(", source)
        self.assertIsNone(sys.modules["pipeline_auto_state"].__dict__.get("re"))

    def test_the_grammar_parses_json_through_the_wrapper_only(self):
        """`_loads` is the condition `json` entered the allowlist on, and its
        `QuorumSchemaInvalid` is re-raised here as the exception this grammar
        promises -- so a controller catching `PlanMetadataError` around a plan
        read does not also have to know the quorum family."""
        with self.assertRaises(state.PlanMetadataError) as caught:
            state._parse_command_suite("{")
        self.assertIsInstance(caught.exception.__cause__,
                              state.QuorumSchemaInvalid)
        self.assertIsInstance(caught.exception, state.TrackerError)


class HarnessTests(PlanGrammarTestCase):
    """The harness every later P04 task builds on, asserted rather than assumed."""

    def test_write_phase_plan_writes_a_parseable_plan(self):
        plan = write_phase_plan(self.tmp, task_block("T1"))
        self.assertTrue(plan.is_file())
        header = state._parse_phase_header(
            plan.read_text(encoding="utf-8").splitlines())
        self.assertEqual(header["id"], "P04")

    def test_write_phase_plan_honours_an_override_header_and_name(self):
        plan = write_phase_plan(self.tmp, task_block("T1"), name="other.md",
                                header=phase_header(phase_id="P05"))
        self.assertEqual(plan.name, "other.md")
        self.assertEqual(
            state._parse_phase_header(
                plan.read_text(encoding="utf-8").splitlines())["id"], "P05")

    def test_task_block_emits_a_suite_only_for_a_source_task(self):
        self.assertIn("pipeline-auto-task-suite", task_block("T1"))
        self.assertNotIn("pipeline-auto-task-suite",
                         task_block("T1", kind="artifact"))

    def test_a_plan_on_disk_is_byte_identical_after_a_refused_parse(self):
        """The read-only-stop property, exercised through the file helper the
        later tasks use. It is weaker here than it will be for them -- this
        grammar opens nothing -- and it is the same assertion they need."""
        plan = write_phase_plan(self.tmp, task_block("T1"), name="bad.md",
                                header=phase_header(review_class="medium"))
        self.expect_file_rejection(plan)

    def test_phase_line_refuses_an_override_it_would_never_read(self):
        """`dict(PHASE_VALUES, **overrides)` accepts any keyword and reads only
        the pinned keys, so a typo produced a VALID header and a green test
        that exercised nothing. Tasks 2-12 inherit this helper, so the silence
        would have been inherited too."""
        for bad in ({"review_gate": "required"}, {"nonsense": "x"},
                    {"Id": "P04"}, {"reviewclass": "required"},
                    {"review_class": "required", "nonsense": "x"}):
            with self.subTest(bad=sorted(bad)):
                with self.assertRaises(KeyError):
                    phase_line(**bad)

    def test_suite_line_was_already_loud_about_the_same_mistake(self):
        """Why the fix is 'make the two halves agree' rather than a new idea."""
        with self.assertRaises(KeyError):
            suite_line(order=("id", "commands", "bogus"))

    def test_phase_line_still_honours_every_pinned_override(self):
        """The ACCEPT half: each real field still reaches the rendered line."""
        for key, value in (("id", "P07"), ("deps", "P01,P02"),
                           ("review_class", "final-only"),
                           ("review_reason", "because")):
            with self.subTest(key=key):
                self.assertIn(f"{key}={value}", phase_line(**{key: value}))

    def test_each_test_gets_its_own_scratch_directory(self):
        self.assertTrue(self.tmp.is_dir())
        self.assertEqual(list(self.tmp.iterdir()), [])


# --------------------------------------------------------------------------
# Task 2 tests -- fault F8: a phase plan whose metadata keys are reordered,
# renamed or missing. Task 1 owns the PHASE header; everything below owns the
# TASK metadata and the file the two are read out of.
# --------------------------------------------------------------------------


class PlanFileTestCase(TempDirTestCase):
    """Accept/reject helpers for ``parse_plan_metadata``, which reads a FILE.

    Every stricter bar below is paired with a case that must still be
    ACCEPTED. A suite of rejections alone is satisfied by a parser that refuses
    everything, and that parser passes.
    """

    def parse(self, body: str, *, header: str | None = None,
              name: str = "phase-04.md") -> dict:
        plan = write_phase_plan(self.tmp, body, header=header, name=name)
        return state.parse_plan_metadata(plan)

    def _expect_rejection(self, body: str, *, header: str | None = None,
                          name: str = "reject.md") -> Exception:
        """Refuse this plan, and leave it byte-identical on disk.

        The bytes are re-read because ``parse_plan_metadata`` OPENS the file --
        which is the whole difference from Task 1's grammar, where the
        read-only-stop claim could only be made about a list of lines.
        """
        plan = write_phase_plan(self.tmp, body, header=header, name=name)
        before = plan.read_bytes()
        with self.assertRaises(state.PlanMetadataError) as caught:
            state.parse_plan_metadata(plan)
        self.assertEqual(plan.read_bytes(), before)
        return caught.exception


class TaskMetadataGrammarTests(PlanFileTestCase):
    """The behaviours the task brief names, one test each."""

    def test_parses_all_declared_fields(self):
        metadata = self.parse(
            task_block("T1", write_scope="file:src/a.py,tree:docs")
            + task_block("T2", deps="T1", kind="artifact", batch="b2", order=2,
                         write_scope="tree:docs", outputs="docs/report.md"))
        self.assertEqual(metadata["phase"]["review_class"], "required")
        tasks = metadata["tasks"]
        self.assertEqual([task["id"] for task in tasks], ["T1", "T2"])
        self.assertEqual(tasks[0]["kind"], "source")
        self.assertEqual(tasks[0]["write_scope"], ("file:src/a.py", "tree:docs"))
        self.assertEqual(tasks[0]["outputs"], ())
        self.assertEqual(tasks[0]["commands"], ("python3 -m unittest -k T1",))
        self.assertEqual(tasks[0]["batch"], "b1")
        self.assertEqual(tasks[0]["deps"], ())
        self.assertEqual(tasks[0]["order"], 1)
        self.assertEqual(tasks[1]["kind"], "artifact")
        self.assertEqual(tasks[1]["deps"], ("T1",))
        self.assertEqual(tasks[1]["order"], 2)
        self.assertEqual(tasks[1]["batch"], "b2")
        self.assertEqual(tasks[1]["outputs"], ("docs/report.md",))
        self.assertEqual(tasks[1]["commands"], ())

    def test_rejects_reordered_keys(self):
        self._expect_rejection(
            "## Task T1\n\n"
            + task_line(("id", "kind", "deps", "batch", "order", "write_scope",
                         "outputs"))
            + "\n" + task_suite_line() + "\n")

    def test_metadata_must_immediately_follow_its_heading(self):
        body = ("## Task T1\n\nSome prose first.\n\n" + task_line() + "\n"
                + task_suite_line() + "\n")
        #: THE FIXTURE PROPERTY, asserted rather than assumed: the heading IS
        #: present and the metadata IS well formed, so the rejection can only
        #: be about the prose between them.
        self.assertIn("## Task T1", body)
        self.assertEqual(self.parse(task_block("T1"))["tasks"][0]["id"], "T1")
        self._expect_rejection(body)

    def test_write_scope_must_be_typed_and_canonical(self):
        for scope in ("src/a.py", "glob:src/*.py", "file:/etc/passwd",
                      "file:../a.py", "tree:", "file:src/*.py"):
            with self.subTest(scope=scope):
                self._expect_rejection(task_block("T1", write_scope=scope))

    def test_duplicate_write_scope_entries_are_rejected(self):
        self._expect_rejection(
            task_block("T1", write_scope="file:src/a.py,file:src/a.py"))

    def test_source_task_may_not_declare_outputs(self):
        self._expect_rejection(task_block("T1", kind="source",
                                          outputs="src/a.py"))

    def test_artifact_task_must_declare_outputs(self):
        self._expect_rejection(task_block("T1", kind="artifact",
                                          outputs="none"))

    def test_artifact_output_outside_its_write_scope_is_rejected(self):
        self._expect_rejection(
            task_block("T1", kind="artifact", write_scope="tree:docs",
                       outputs="reports/out.md"))

    def test_source_task_requires_one_adjacent_verification_suite(self):
        self._expect_rejection("## Task T1\n\n" + task_line() + "\n")

    def test_artifact_task_may_not_carry_a_source_task_suite(self):
        """TWO CHECKS REFUSE THIS, so the assertion has to name one of them.
        The per-task rule at the artifact branch and the document-wide suite
        accounting both fire -- the accounting expects suites on the lines of
        the source tasks and there are none -- so deleting the per-task rule
        left every rejection intact and the suite green. What differs is the
        DIAGNOSIS: the per-task rule says a suite beside approved outputs is a
        second definition of done, while the accounting says only that the
        line numbers do not match, which sends the plan's author to count
        lines instead of to the contradiction."""
        exception = self._expect_rejection(
            "## Task T1\n\n"
            + task_line(kind="artifact", write_scope="tree:docs",
                        outputs="docs/a.md")
            + "\n" + task_suite_line() + "\n")
        self.assertIn("second definition of done", str(exception))
        self.assertNotIn("expected them on lines", str(exception))

    def test_duplicate_task_ids_are_rejected(self):
        self._expect_rejection(task_block("T1") + task_block("T1", order=2))

    def test_unknown_and_self_dependencies_are_rejected(self):
        """The two refusals are asserted BY DIAGNOSIS, because a self-loop is
        also a cycle: deleting the per-task self-dependency check leaves the
        graph walk refusing the same plan, so a rejection-only assertion could
        not tell the two apart and the check could be removed unnoticed. 'A
        task waiting on itself' is the thing the plan got wrong; 'the graph
        contains a cycle through T1' is true and unhelpfully general."""
        for deps, anchor in (("T9", "is depended on and never declared"),
                             ("T1", "lists itself")):
            with self.subTest(deps=deps):
                exception = self._expect_rejection(
                    task_block("T1", deps=deps), name=f"dep-{deps}.md")
                self.assertIn(anchor, str(exception))
        self.assertNotIn(
            "contains a cycle",
            str(self._expect_rejection(task_block("T1", deps="T1"),
                                       name="dep-self.md")))

    def test_cyclic_dependencies_are_rejected(self):
        self._expect_rejection(
            task_block("T1", deps="T2", write_scope="file:src/a.py")
            + task_block("T2", deps="T1", order=2, write_scope="file:src/b.py"))

    def test_task_count_is_bounded_and_the_boundary_itself_is_accepted(self):
        """The brief's version tested 0 and 13 and never 12 -- so an
        implementation written ``< MAX_TASKS_PER_PHASE`` passed it while
        refusing the largest plan the constant says is legal. The ceiling is
        the case an off-by-one lives on, so it is the case that is exercised."""
        self.assertEqual(state.MAX_TASKS_PER_PHASE, 12)
        full = "".join(
            task_block(f"T{index}", order=index,
                       write_scope=f"file:src/a{index}.py")
            for index in range(1, state.MAX_TASKS_PER_PHASE + 1))
        self.assertEqual(full.count("<!-- pipeline-auto-task:"),
                         state.MAX_TASKS_PER_PHASE)
        self.assertEqual(len(self.parse(full, name="full.md")["tasks"]),
                         state.MAX_TASKS_PER_PHASE)
        self._expect_rejection("\nNo tasks here.\n", name="empty.md")
        self._expect_rejection(
            "".join(
                task_block(f"T{index}", order=index,
                           write_scope=f"file:src/a{index}.py")
                for index in range(1, state.MAX_TASKS_PER_PHASE + 2)),
            name="overfull.md")

    def test_order_must_be_a_positive_integer(self):
        for order in ("0", "-1", "one"):
            with self.subTest(order=order):
                self._expect_rejection(
                    "## Task T1\n\n" + task_line(order=order) + "\n"
                    + task_suite_line() + "\n",
                    name=f"order-{order}.md")


class TaskKeyOrderTests(PlanFileTestCase):
    """F8's core, the task half. The keys are PINNED IN ORDER, not merely
    required to exist -- and every fixture here varies exactly one thing."""

    def test_the_pinned_task_order_is_not_the_alphabetical_one(self):
        """The guard that keeps every test below discriminating.

        If the pinned order happened to equal the alphabetical one, a parser
        that sorted its keys -- or one that used a dict and lost order entirely
        -- would pass every reordering test in this class while doing nothing
        the grammar claims.
        """
        self.assertEqual(
            state._TASK_KEYS,
            ("id", "deps", "kind", "batch", "order", "write_scope", "outputs"))
        self.assertIsInstance(state._TASK_KEYS, tuple)
        self.assertNotEqual(list(state._TASK_KEYS), sorted(state._TASK_KEYS))
        self.assertNotEqual(list(state._TASK_KEYS),
                            sorted(state._TASK_KEYS, reverse=True))
        self.assertEqual(len(set(state._TASK_KEYS)), 7)
        self.assertEqual(set(TASK_VALUES), set(state._TASK_KEYS))

    def test_rejects_every_adjacent_transposition_of_the_same_seven_keys(self):
        """Six fixtures, each carrying ALL SEVEN keys with the SAME valid
        values. Nothing varies but the position of one adjacent pair, so a
        rejection cannot be about a missing key, an unknown key or a bad
        value: it is about the ORDER, which is the claim."""
        pinned = state._TASK_KEYS
        swapped = 0
        for position in range(len(pinned) - 1):
            keys = list(pinned)
            keys[position], keys[position + 1] = keys[position + 1], keys[position]
            line = task_line(tuple(keys))
            for key in pinned:
                self.assertIn(f"{key}=", line)
            self.assertEqual(sorted(keys), sorted(pinned))
            self.assertNotEqual(tuple(keys), pinned)
            swapped += 1
            with self.subTest(pair=(pinned[position], pinned[position + 1])):
                self._expect_rejection(
                    "## Task T1\n\n" + line + "\n" + task_suite_line() + "\n",
                    name=f"swap-{position}.md")
        self.assertEqual(swapped, 6)

    def test_rejects_the_alphabetical_and_reversed_orders_by_name(self):
        """The two orders an implementation PRODUCES by accident -- a dict
        comprehension over sorted splits, and a reversed accumulation -- so
        they are the two a diagnosis most often lands on."""
        for label, keys in (("alphabetical", tuple(sorted(state._TASK_KEYS))),
                            ("reversed", tuple(reversed(state._TASK_KEYS)))):
            with self.subTest(order=label):
                self.assertNotEqual(keys, state._TASK_KEYS)
                self._expect_rejection(
                    "## Task T1\n\n" + task_line(keys) + "\n"
                    + task_suite_line() + "\n", name=f"{label}.md")

    def test_the_pinned_order_alone_is_accepted(self):
        """The ACCEPT half of the whole class. Without it every assertion above
        is satisfied by a parser that refuses all seven-key comments."""
        line = task_line()
        self.assertEqual(
            line,
            "<!-- pipeline-auto-task: id=T1; deps=none; kind=source; batch=b1; "
            "order=1; write_scope=file:src/a.py; outputs=none -->")
        metadata = self.parse("## Task T1\n\n" + line + "\n"
                              + task_suite_line() + "\n")
        self.assertEqual(metadata["tasks"][0]["id"], "T1")

    def test_rejects_each_key_dropped_in_turn_with_the_other_six_intact(self):
        """Drop exactly ONE key. The other six keep their pinned relative
        order and their valid values, so nothing but the absence can be the
        reason -- which is the confound a fixture that dropped two would have,
        and the reason the ``kind`` case below can be stated at all."""
        for dropped in state._TASK_KEYS:
            keys = tuple(key for key in state._TASK_KEYS if key != dropped)
            line = task_line(keys)
            self.assertEqual(len(keys), 6)
            self.assertNotIn(f"{dropped}=", line)
            for kept in keys:
                self.assertIn(f"{kept}=", line)
            with self.subTest(dropped=dropped):
                self._expect_rejection(
                    "## Task T1\n\n" + line + "\n" + task_suite_line() + "\n",
                    name=f"drop-{dropped}.md")

    def test_rejects_a_plan_missing_only_kind(self):
        """F8's task-side analogue of 'missing ``review_class``'. ``kind`` is
        the plan's claim about what proves the task -- a suite, or exact
        outputs -- so a plan without it leaves the worker to choose which of
        the two it will be judged by, which is the whole fault."""
        line = task_line(tuple(key for key in state._TASK_KEYS if key != "kind"))
        self.assertNotIn("kind=", line)
        for kept in ("id=", "deps=", "batch=", "order=", "write_scope=",
                     "outputs="):
            self.assertIn(kept, line)
        self._expect_rejection(
            "## Task T1\n\n" + line + "\n" + task_suite_line() + "\n")

    def test_rejects_a_renamed_key_at_its_own_position(self):
        """Built by replacing exactly one ``key=`` substring of the VALID
        line, so every other byte is provably untouched and the position of
        the renamed key is provably unchanged."""
        for original, renamed in (("id", "task_id"), ("kind", "type"),
                                  ("deps", "depends"), ("batch", "group"),
                                  ("order", "position"),
                                  ("write_scope", "scope"),
                                  ("outputs", "artifacts")):
            line = task_line()
            self.assertEqual(line.count(f"{original}="), 1)
            with self.subTest(renamed=f"{original}->{renamed}"):
                self._expect_rejection(
                    "## Task T1\n\n"
                    + line.replace(f"{original}=", f"{renamed}=") + "\n"
                    + task_suite_line() + "\n", name=f"rename-{original}.md")

    def test_rejects_an_extra_key_appended_after_outputs(self):
        """``outputs`` is the LAST key and is parsed with ``tail=False``, so an
        eighth key cannot be absorbed into it. A tail-parsed last field would
        swallow ``; owner=me`` into the outputs list silently."""
        self._expect_rejection(
            "## Task T1\n\n"
            + task_line().replace(" -->", "; owner=me -->") + "\n"
            + task_suite_line() + "\n")

    def test_rejects_an_extra_key_inserted_between_pinned_keys(self):
        self._expect_rejection(
            "## Task T1\n\n"
            + task_line().replace("kind=", "owner=me; kind=") + "\n"
            + task_suite_line() + "\n")

    def test_rejects_a_duplicated_key(self):
        self._expect_rejection(
            "## Task T1\n\n"
            + task_line().replace("batch=b1", "batch=b1; batch=b1") + "\n"
            + task_suite_line() + "\n")

    def test_the_comment_delimiter_bar_is_inherited_and_not_redeclared(self):
        """``_comment_fields`` refuses ``-->`` and ``<!--`` on the comment BODY,
        which covers every field of every metadata comment at once. This test
        asserts the task comment reaches that bar rather than carrying a
        second copy of it -- a second copy is a second thing to drift."""
        self._expect_rejection(
            "## Task T1\n\n"
            + task_line(batch="b1 --> b2") + "\n" + task_suite_line() + "\n")
        self.assertTrue(state._cell_safe("b1 --> b2"))

    def test_an_indented_task_comment_is_counted_and_then_refused(self):
        """Task 1's ruling, which the task grammar inherits or loses: DETECT on
        the stripped line, VALIDATE on the raw one.

        THE FIXTURE IS BUILT SO THAT INVISIBLE MEANS ACCEPTED. The indented
        task is an ARTIFACT -- it carries no suite, so the document-level suite
        accounting has nothing to notice -- and a second, entirely valid source
        task stands beside it. A raw ``startswith`` detector therefore sees a
        one-task plan with nothing wrong with it and returns it: a whole task
        silently dropped out of an approved plan, which is worse than any
        refusal. The unindented twin is parsed in the same test and must come
        back with BOTH tasks, so the rejection is provably about the two
        spaces and not about anything else in the fixture.
        """
        second = ("## Task T2\n\n" + task_line(
            id="T2", kind="artifact", order="2", write_scope="tree:docs",
            outputs="docs/a.md") + "\n\nProse.\n\n")
        self.assertNotIn("pipeline-auto-task-suite", second)
        accepted = self.parse(task_block("T1") + second, name="flat.md")
        self.assertEqual([task["id"] for task in accepted["tasks"]],
                         ["T1", "T2"])
        indented = second.replace("<!-- pipeline-auto-task:",
                                  "  <!-- pipeline-auto-task:")
        self.assertIn("\n  <!-- pipeline-auto-task:", indented)
        self._expect_rejection(task_block("T1") + indented)

class TaskFieldValueTests(PlanFileTestCase):
    """The value grammar behind each pinned key, and the ACCEPT half of each."""

    def test_task_kinds_is_a_pinned_pair(self):
        self.assertEqual(state.TASK_KINDS, ("source", "artifact"))
        self.assertIsInstance(state.TASK_KINDS, tuple)
        self.assertEqual(len(set(state.TASK_KINDS)), 2)

    def test_both_kinds_are_accepted_in_their_own_shape(self):
        metadata = self.parse(
            task_block("T1")
            + task_block("T2", kind="artifact", order=2,
                         write_scope="tree:docs", outputs="docs/a.md"))
        self.assertEqual([task["kind"] for task in metadata["tasks"]],
                         list(state.TASK_KINDS))

    def test_rejects_a_kind_outside_the_vocabulary(self):
        for kind in ("Source", "SOURCE", "artifacts", "doc", "", "source ",
                     "source,artifact"):
            with self.subTest(kind=kind):
                self._expect_rejection(
                    "## Task T1\n\n" + task_line(kind=kind) + "\n"
                    + task_suite_line() + "\n", name="kind.md")

    def test_an_unknown_kind_is_refused_by_the_vocabulary_and_not_by_luck(self):
        """WHAT THE CORPUS ABOVE CANNOT SEE. Every fixture there is rendered in
        the SOURCE shape -- ``outputs=none`` and a suite on the next line -- so
        the kind/outputs equivalence refuses all of them on its own, and a
        rejection-only assertion cannot tell the vocabulary check from the
        equivalence check. Deleting the vocabulary check left the whole suite
        green while ``kind='banana'`` parsed through.

        The ARTIFACT shape is what discriminates: outputs declared and no
        suite satisfies BOTH halves of the equivalence, so nothing else in the
        function has a reason to refuse it. The kind is the plan's claim about
        what proves the task, and this is the only test holding that claim.
        """
        exception = self._expect_rejection(
            "## Task T1\n\n" + task_line(kind="banana", write_scope="tree:docs",
                                         outputs="docs/a.md") + "\n",
            name="kind-art.md")
        #: The diagnosis must name the VOCABULARY, not the equivalence: the
        #: two refusals are indistinguishable to an assertRaises alone.
        self.assertIn("banana", str(exception))
        for known in state.TASK_KINDS:
            self.assertIn(known, str(exception))
        self.assertNotIn("proved by them existing", str(exception))
        #: The fixture's own property: with a KNOWN kind, this exact shape is
        #: accepted -- so the rejection above is about the kind and nothing
        #: else in the line.
        task = self.parse(
            "## Task T1\n\n" + task_line(kind="artifact",
                                         write_scope="tree:docs",
                                         outputs="docs/a.md") + "\n",
            name="kind-art-ok.md")["tasks"][0]
        self.assertEqual((task["kind"], task["outputs"], task["commands"]),
                         ("artifact", ("docs/a.md",), ()))

    def test_order_is_ascii_digits_and_not_whatever_int_accepts(self):
        """The defect a bare ``int(raw)`` leaves, and the module has written it
        down once already in ``_Numbered``: ``int(chr(0x0661))`` is 1 and
        ``int('1_0')`` is 10, so a plan can spell an order in Arabic-Indic
        digits or with a separator and the tracker records a number nobody
        wrote. Each is asserted to be a number Python WOULD have accepted, so
        the test says what it is discriminating against.

        AND THE CORPUS CARRIES A LENGTH FAMILY, because the twelve spellings
        above are every one of them one to three characters long -- they were
        drawn from "spellings ``int()`` mis-accepts", and the family that
        escapes is the opposite shape: a LONG run of perfectly ordinary ASCII
        digits, which ``isascii()`` and ``isdigit()`` both wave through. See
        ``test_a_long_run_of_ordinary_digits_never_reaches_int`` for the
        boundary and for what it used to escape as.
        """
        cap = sys.get_int_max_str_digits()
        long_family = ("1" * 3, "9" * 12, "1" * cap, "9" * (cap + 1))
        for order in (chr(0x0661), "1_0", "+1", " 1", "1 ", "01", "1.0", "",
                      "one", "-1", "0", chr(0x00B3)) + long_family:
            with self.subTest(order=order[:8], length=len(order)):
                self._expect_rejection(
                    "## Task T1\n\n" + task_line(order=order) + "\n"
                    + task_suite_line() + "\n", name="order.md")
        self.assertEqual([int(spelling) for spelling in
                          (chr(0x0661), "+1", " 1", "1 ", "01")], [1, 1, 1, 1, 1])
        self.assertEqual(int("1_0"), 10)
        #: The discriminating property of the length family: unlike every
        #: other member of the corpus, these are pure ASCII digits, so the
        #: isascii/isdigit pair is TRUE of them and only the length clause
        #: stands between the plan and ``int()``.
        for spelling in long_family:
            self.assertTrue(spelling.isascii() and spelling.isdigit())
        #: And the last of them is the one that used to escape as a bare
        #: ValueError out of the screen's own int() call.
        with self.assertRaises(ValueError):
            int(long_family[-1])

    def test_a_long_run_of_ordinary_digits_never_reaches_int(self):
        """C1. ``int(raw_order)`` WAS EVALUATED INSIDE THE SCREEN written to
        replace a bare ``int()``, and CPython caps integer<->string conversion
        at ``sys.int_max_str_digits`` -- so at 4301 digits the screen itself
        raised ``ValueError``, which is not an ``OSError``, not a
        ``UnicodeError`` and not a ``TrackerError``. Agent-authored plan
        content reached the controller as a raw ``ValueError``: the run died
        rather than stopping, against this function's own docstring.

        The fix is positional as much as it is a new clause -- ``or``
        short-circuits left to right, so the length bound must sit BEFORE the
        round trip. The assertions below are therefore about the BOUNDARY and
        about the exception TYPE, not merely that something was refused.
        """
        self.assertEqual(state._MAX_ORDER_DIGITS,
                         len(str(state.MAX_TASKS_PER_PHASE)))
        cap = sys.get_int_max_str_digits()
        self.assertLess(state._MAX_ORDER_DIGITS, cap)
        #: What used to escape, still escaping when asked directly: the raw
        #: conversion this screen now stands in front of.
        with self.assertRaises(ValueError) as caught:
            int("9" * (cap + 1))
        self.assertNotIsInstance(caught.exception, state.TrackerError)
        #: The boundary: one digit over the ceiling is refused, the ceiling
        #: itself is accepted, and neither answer is a ValueError escaping.
        over = "9" * (state._MAX_ORDER_DIGITS + 1)
        exception = self._expect_rejection(
            "## Task T1\n\n" + task_line(order=over) + "\n"
            + task_suite_line() + "\n", name="long-order.md")
        self.assertIn("ASCII digits", str(exception))
        task = self.parse(
            "## Task T1\n\n"
            + task_line(order="9" * state._MAX_ORDER_DIGITS) + "\n"
            + task_suite_line() + "\n", name="max-order.md")["tasks"][0]
        self.assertEqual(task["order"], int("9" * state._MAX_ORDER_DIGITS))

    def test_the_order_ceiling_is_a_spelling_bound_and_not_a_value_rule(self):
        """THE RULING, asserted rather than only written down. The bound could
        have been ``order <= MAX_TASKS_PER_PHASE``, and that would have made
        the task-count ceiling UNREACHABLE: thirteen tasks cannot carry
        thirteen strictly increasing orders all at most twelve, so the count
        check would become dead code and the ceiling would be enforced by the
        wrong diagnosis. The two assertions below are the two things the
        weaker, deliberate reading buys."""
        #: Orders above the task ceiling are still legal, so the count check
        #: keeps a fixture that reaches it.
        overfull = "".join(
            task_block(f"T{index}", order=index,
                       write_scope=f"file:src/a{index}.py")
            for index in range(1, state.MAX_TASKS_PER_PHASE + 2))
        self.assertIn(f"order={state.MAX_TASKS_PER_PHASE + 1}", overfull)
        exception = self._expect_rejection(overfull, name="ruling.md")
        self.assertIn("declares between 1 and", str(exception))
        #: And a single task may still be numbered above the ceiling, which is
        #: the status quo this fix deliberately did not change.
        task = self.parse(
            task_block("T1", order=state.MAX_TASKS_PER_PHASE + 1),
            name="thirteen.md")["tasks"][0]
        self.assertEqual(task["order"], state.MAX_TASKS_PER_PHASE + 1)

    def test_an_ordinary_order_is_still_an_int_in_the_result(self):
        task = self.parse(task_block("T1", order=7))["tasks"][0]
        self.assertEqual(task["order"], 7)
        self.assertIsInstance(task["order"], int)
        self.assertNotIsInstance(task["order"], bool)

    def test_a_task_id_and_a_batch_are_tokens(self):
        for field in ("id", "batch"):
            for value in ("", " T1", "T 1", "-T1", "T|1", "T1 ", "T,1"):
                with self.subTest(field=field, value=repr(value)):
                    self._expect_rejection(
                        f"## Task {value}\n\n"
                        + task_line(**{field: value}) + "\n"
                        + task_suite_line(value if field == "id" else "T1")
                        + "\n", name="token.md")

    def test_a_task_id_may_carry_every_character_the_token_grammar_allows(self):
        """The ACCEPT half, and a guard on ``_TOKEN`` itself: ``@``, ``:``,
        ``+``, ``/``, ``.`` and ``-`` are all inside P02's grammar, so a P04
        block that narrowed the token to ``[A-Za-z0-9-]`` would fail here."""
        for task_id in ("T1", "T-1", "T.1", "T_1", "p04/t2", "a@b", "a:b",
                        "a+b"):
            with self.subTest(task_id=task_id):
                metadata = self.parse(task_block(task_id), name="id.md")
                self.assertEqual(metadata["tasks"][0]["id"], task_id)

    def test_deps_keep_the_order_the_plan_wrote_them_in(self):
        """Non-alphabetical on purpose: ``T3,T2`` sorted is ``T2,T3``, so a
        parser that sorted or set-ified its dependencies fails here."""
        metadata = self.parse(
            task_block("T2", order=1, write_scope="file:src/b.py")
            + task_block("T3", order=2, write_scope="file:src/c.py")
            + task_block("T1", deps="T3,T2", order=3))
        self.assertEqual(metadata["tasks"][2]["deps"], ("T3", "T2"))
        self.assertNotEqual(list(metadata["tasks"][2]["deps"]),
                            sorted(metadata["tasks"][2]["deps"]))

    def test_no_dependencies_is_spelled_none_and_parses_empty(self):
        self.assertEqual(self.parse(task_block("T1"))["tasks"][0]["deps"], ())

    def test_rejects_malformed_dependency_lists(self):
        for deps in ("", ",", "T2,", ",T2", "T2,,T3", "T2 T3", "none,T2",
                     "T2,none", "T2,T2"):
            with self.subTest(deps=deps):
                self._expect_rejection(
                    task_block("T1", deps=deps, order=1)
                    + task_block("T2", order=2, write_scope="file:src/b.py")
                    + task_block("T3", order=3, write_scope="file:src/c.py"),
                    name="deps.md")

    def test_a_malformed_dependency_is_refused_as_malformed_not_as_unknown(self):
        """The ``_TOKEN`` check on each dependency has an overlap the corpus
        above hides: ``'T2 T3'`` is not a declared id EITHER, so the closure
        check in the graph walk refuses the same plan and deleting the token
        check changes no verdict. The diagnosis is the difference -- 'invalid
        task dependency id' points at the deps field's spelling, while 'is
        depended on and never declared' tells the author to go and add a task
        called ``T2 T3``, which is not something this grammar can express."""
        exception = self._expect_rejection(
            task_block("T1", deps="T2 T3", order=1)
            + task_block("T2", order=2, write_scope="file:src/b.py")
            + task_block("T3", order=3, write_scope="file:src/c.py"),
            name="dep-token.md")
        self.assertIn("invalid task dependency id", str(exception))
        self.assertNotIn("never declared", str(exception))

    def test_none_is_a_whole_value_and_never_a_member(self):
        """Task 1 wrote this guard for phase ``deps``; the task grammar needs it
        three times over. Without it ``outputs=none,docs/a.md`` reads as two
        members, the first a perfectly legal path spelled ``none`` -- so the
        artifact task declares 'no outputs, and also this one' and the run
        later looks for a file called ``none``. The accept half asserts that
        ``none`` alone still means empty."""
        self.assertEqual(state._safe_relative("none").as_posix(), "none")
        self._expect_rejection(
            task_block("T1", kind="artifact", write_scope="tree:docs",
                       outputs="none,docs/a.md"), name="mix-out.md")
        self.assertEqual(
            self.parse(task_block("T1"), name="none-ok.md")["tasks"][0]
            ["outputs"], ())

    def test_declared_members_is_directly_callable_and_total(self):
        self.assertEqual(state._declared_members("none", "probe"), ())
        self.assertEqual(state._declared_members("a,b", "probe"), ("a", "b"))
        self.assertEqual(state._declared_members("b,a", "probe"), ("b", "a"))
        for raw in ("", "a,", ",a", "a,,b", "none,a", "a,none", "a,a"):
            with self.subTest(raw=raw):
                with self.assertRaises(state.PlanMetadataError):
                    state._declared_members(raw, "probe")


class WriteScopeTests(PlanFileTestCase):
    """``_parse_write_scope``: typed, canonical, ordered, and non-repeating."""

    def test_write_scope_types_are_the_pinned_pair(self):
        self.assertEqual(state._WRITE_SCOPE_TYPES, ("file", "tree"))

    def test_canonical_scopes_keep_the_plan_order_and_carry_typed_paths(self):
        """Non-alphabetical on purpose: sorted, ``tree:docs`` precedes
        ``file:src/a.py``, so a parser that sorted its scopes fails here."""
        canonical, parsed = state._parse_write_scope("tree:docs,file:src/a.py")
        self.assertEqual(canonical, ("tree:docs", "file:src/a.py"))
        self.assertNotEqual(list(canonical), sorted(canonical))
        self.assertEqual(parsed, [("tree", PurePosixPath("docs")),
                                  ("file", PurePosixPath("src/a.py"))])

    def test_a_multi_scope_task_parses_every_scope(self):
        task = self.parse(
            task_block("T1",
                       write_scope="file:src/a.py,tree:docs,file:src/b.py")
        )["tasks"][0]
        self.assertEqual(task["write_scope"],
                         ("file:src/a.py", "tree:docs", "file:src/b.py"))

    def test_rejects_an_untyped_empty_or_repeated_scope(self):
        for scope in ("src/a.py", "none", "", ",", "file:src/a.py,",
                      "file:src/a.py,file:src/a.py", "tree:docs,tree:docs",
                      "file:src/a.py,,tree:docs", ":src/a.py", "FILE:src/a.py",
                      "Tree:docs", "dir:docs", "glob:src/*.py"):
            with self.subTest(scope=scope):
                self._expect_rejection(task_block("T1", write_scope=scope),
                                       name="scope.md")

    def test_a_comma_inside_a_path_is_unspellable_rather_than_unscreened(self):
        """THE RULING THIS TASK INHERITED AND IS NOW MAKING EXPLICIT.

        Task 1 left ``,`` deliberately unscreened in ``_cell_safe``, because
        that predicate is shared by values that are not all multi-valued, and
        it said the bar belongs on whoever KNOWS a cell is list-valued.
        ``write_scope`` and ``outputs`` are the first list-valued plan fields,
        so the ruling is this task's to make -- and the decision is that NO NEW
        COMMA SCREEN IS ADDED, because the comma is the separator: the split
        happens first, so a path containing one is not smuggled through, it is
        two members, and the second is then refused on its own merits. A screen
        would be a rule with no input that can reach it. Both halves are
        asserted so that adding one later is a decision somebody makes rather
        than a tidy-up.
        """
        self.assertTrue(state._cell_safe("src/a,b.py"))
        self.assertEqual(state._safe_relative("src/a,b.py").as_posix(),
                         "src/a,b.py")
        canonical, _ = state._parse_write_scope("file:src/a.py,tree:docs")
        self.assertEqual(len(canonical), 2)
        self._expect_rejection(task_block("T1", write_scope="file:src/a,b.py"),
                               name="comma.md")

    def test_the_scope_path_bar_is_safe_relatives_and_not_a_second_copy(self):
        corpus = ["/etc/passwd", "../a.py", "a/../b", "src/./a", "a//b",
                  "src/a/", "src/*.py", "src/[a].py", "a\\b", " src/a.py",
                  "src/a.py "]
        #: The character half is built with ``chr`` rather than written as
        #: escapes, so the families are visible as CODE POINTS rather than
        #: as a list somebody has to decode: NUL, a line feed and a tab out
        #: of ``range(0x20)``; then 0x85, 0x2028 and 0x2029, three row
        #: breaks no ASCII list contains; then two lone surrogates the UTF-8
        #: encoder refuses outright.
        corpus += [f"src/a{chr(code)}b" for code in
                   (0x00, 0x0A, 0x09, 0x85, 0x2028, 0x2029, 0xD800, 0xDFFF)]
        for path in corpus:
            with self.subTest(path=repr(path)):
                with self.assertRaises(state.PlanMetadataError):
                    state._parse_write_scope(f"file:{path}")

    def test_a_scope_may_name_a_dotfile_a_dotted_path_or_a_colon(self):
        """The ACCEPT half. ``:`` after the type separator is part of the path,
        because ``partition`` splits on the FIRST colon only -- a ``split(':')``
        without a maxsplit would throw the rest of the path away."""
        for scope, expected in (
                ("file:.github/workflows/ci.yml", "file:.github/workflows/ci.yml"),
                ("file:src/a.b.py", "file:src/a.b.py"),
                ("tree:docs/superpowers", "tree:docs/superpowers"),
                ("file:src/a:b.py", "file:src/a:b.py")):
            with self.subTest(scope=scope):
                canonical, _ = state._parse_write_scope(scope)
                self.assertEqual(canonical, (expected,))


class TaskOutputsTests(PlanFileTestCase):
    """``outputs`` is the artifact half of the kind equivalence, and it is
    bounded by the task's own declared write scope."""

    def test_a_source_task_declares_none_and_an_artifact_task_declares_paths(self):
        metadata = self.parse(
            task_block("T1")
            + task_block("T2", kind="artifact", order=2, write_scope="tree:docs",
                         outputs="docs/b.md,docs/a.md"))
        self.assertEqual(metadata["tasks"][0]["outputs"], ())
        #: Non-alphabetical on purpose: sorted, ``docs/a.md`` comes first.
        self.assertEqual(metadata["tasks"][1]["outputs"],
                         ("docs/b.md", "docs/a.md"))
        self.assertNotEqual(list(metadata["tasks"][1]["outputs"]),
                            sorted(metadata["tasks"][1]["outputs"]))

    def test_the_kind_equivalence_holds_in_both_directions(self):
        self._expect_rejection(task_block("T1", kind="source",
                                          outputs="src/a.py"), name="so.md")
        self._expect_rejection(task_block("T1", kind="artifact",
                                          write_scope="tree:docs",
                                          outputs="none"), name="ao.md")

    def test_a_tree_scope_contains_what_is_under_it_and_not_a_sibling(self):
        """THE PREFIX TRAP, asserted from both sides. ``tree:docs`` does not
        contain ``docsx/a.md``, and ``'docsx/a.md'.startswith('docs')`` is
        True -- so a containment test written as a string prefix hands the task
        a sibling directory it never declared, and the reservation algebra that
        keeps two implementers apart has been told the wrong thing."""
        self.assertTrue("docsx/a.md".startswith("docs"))
        accepted = self.parse(
            task_block("T1", kind="artifact", write_scope="tree:docs",
                       outputs="docs/a.md,docs/deep/b.md"), name="in.md")
        self.assertEqual(accepted["tasks"][0]["outputs"],
                         ("docs/a.md", "docs/deep/b.md"))
        for output in ("docsx/a.md", "reports/out.md", "docs", "a/docs/b.md"):
            with self.subTest(output=output):
                self._expect_rejection(
                    task_block("T1", kind="artifact", write_scope="tree:docs",
                               outputs=output), name="out.md")

    def test_a_file_scope_contains_exactly_itself(self):
        self.assertEqual(
            self.parse(task_block("T1", kind="artifact",
                                  write_scope="file:docs/a.md",
                                  outputs="docs/a.md"), name="fi.md"
                       )["tasks"][0]["outputs"], ("docs/a.md",))
        for output in ("docs/a.md.bak", "docs/b.md", "docs"):
            with self.subTest(output=output):
                self._expect_rejection(
                    task_block("T1", kind="artifact",
                               write_scope="file:docs/a.md", outputs=output),
                    name="fo.md")

    def test_an_output_must_be_inside_one_of_several_scopes_not_merely_one(self):
        """The ACCEPT half of a multi-scope task, paired with the reject: each
        output is checked against the union, so an output in the SECOND scope
        is accepted and one in neither is not."""
        task = self.parse(
            task_block("T1", kind="artifact",
                       write_scope="tree:docs,file:reports/out.md",
                       outputs="reports/out.md,docs/a.md"), name="mu.md"
        )["tasks"][0]
        self.assertEqual(task["outputs"], ("reports/out.md", "docs/a.md"))
        self._expect_rejection(
            task_block("T1", kind="artifact",
                       write_scope="tree:docs,file:reports/out.md",
                       outputs="reports/other.md"), name="mx.md")

    def test_a_repeated_or_malformed_output_is_rejected(self):
        for outputs in ("docs/a.md,docs/a.md", "docs/a.md,", ",docs/a.md",
                        "docs/../a.md", "/docs/a.md", "docs/*.md",
                        "none,docs/a.md", "docs/a.md,none"):
            with self.subTest(outputs=outputs):
                self._expect_rejection(
                    task_block("T1", kind="artifact", write_scope="tree:docs",
                               outputs=outputs), name="ro.md")


class TaskHeadingBindingTests(PlanFileTestCase):
    """A task's metadata belongs to the task whose heading it sits under."""

    def test_any_heading_level_two_to_six_may_carry_a_task(self):
        for hashes in range(2, 7):
            heading = "#" * hashes + " Task T1"
            with self.subTest(level=hashes):
                metadata = self.parse(
                    task_block("T1", heading=heading), name="lvl.md")
                self.assertEqual(metadata["tasks"][0]["id"], "T1")

    def test_an_indented_heading_still_binds_because_commonmark_says_so(self):
        """Task 1's ruling on the phase side, applied here: CommonMark allows up
        to three leading spaces on an ATX heading, so a raw ``startswith`` would
        refuse a heading markdown itself renders. Detection is on the stripped
        line on BOTH sides of the comparison or it is not a defence."""
        metadata = self.parse(task_block("T1", heading="   ## Task T1"),
                              name="ind.md")
        self.assertEqual(metadata["tasks"][0]["id"], "T1")

    def test_rejects_a_heading_that_is_not_one_or_names_another_task(self):
        #: NOT in this list: a heading indented up to three spaces. CommonMark
        #: renders that as a heading, so Task 1's phase grammar detects it on
        #: the stripped line and this one does too -- see the accept case
        #: above. Over-stripping is the conservative direction; under-stripping
        #: is the one that lets a plan hide structure behind two spaces.
        for heading in ("# Task T1", "####### Task T1", "##Task T1",
                        "## Task T2", "Task T1",
                        "## TaskT1", "## Task", "**Task T1**"):
            with self.subTest(heading=heading):
                self._expect_rejection(
                    task_block("T1", heading=heading), name="hd.md")

    def test_the_id_is_a_word_of_the_heading_and_not_a_substring_of_one(self):
        """The defect a substring test leaves: ``## Task T12`` would bind the
        metadata for ``T1``, and a plan whose tasks are ``T1`` and ``T12`` is
        not exotic. Both directions are asserted, so the accept half proves the
        word test is not simply refusing everything."""
        self.assertIn("T1", "## Task T12")
        self._expect_rejection(task_block("T1", heading="## Task T12"),
                               name="sub.md")
        self.assertEqual(
            self.parse(task_block("T12", order=1,
                                  heading="## Task T12 -- the second one"),
                       name="word.md")["tasks"][0]["id"], "T12")

    def test_prose_between_the_heading_and_the_metadata_breaks_the_binding(self):
        """Blank lines are markdown; a paragraph is a second thing claiming to
        live under that heading. The accept half is the blank-line case, which
        ``task_block`` writes by default."""
        self.assertIn("\n\n<!-- pipeline-auto-task:", task_block("T1"))
        self.assertEqual(self.parse(task_block("T1"), name="ok.md")
                         ["tasks"][0]["id"], "T1")
        for between in ("Some prose first.", "<!-- an unrelated comment -->",
                        "- a list item", "    indented code"):
            with self.subTest(between=between):
                self._expect_rejection(
                    "## Task T1\n\n" + between + "\n\n" + task_line() + "\n"
                    + task_suite_line() + "\n", name="pr.md")

    def test_a_task_comment_with_no_heading_above_it_at_all_is_refused(self):
        """The first task in the body has the phase header above it and nothing
        else, so ``lines[:index]`` holds no heading of the right level. The
        document title is level one and is deliberately not enough."""
        self._expect_rejection(task_line() + "\n" + task_suite_line() + "\n",
                               name="noh.md")


class TaskSuiteTests(PlanFileTestCase):
    """The task suite comment: adjacent, identified, key-order pinned, and
    accounted for document-wide rather than only where it is expected."""

    def test_the_suite_key_order_is_pinned_too(self):
        self.assertEqual(state._TASK_SUITE_KEYS, ("id", "commands"))
        self._expect_rejection(
            "## Task T1\n\n" + task_line() + "\n"
            + task_suite_line(keys=("commands", "id")) + "\n", name="sk.md")

    def test_the_suite_identity_must_match_the_task_metadata(self):
        """A suite belonging to another task would verify that task and report
        the result against this one -- which is a green task nobody ran
        anything for. The accept half pins that a matching id still passes."""
        self.assertEqual(
            self.parse("## Task T1\n\n" + task_line() + "\n"
                       + task_suite_line("T1") + "\n", name="si.md"
                       )["tasks"][0]["commands"],
            ("python3 -m unittest -k T1",))
        self._expect_rejection(
            "## Task T1\n\n" + task_line() + "\n"
            + task_suite_line("T2") + "\n", name="sm.md")

    def test_the_suite_must_be_on_the_very_next_line(self):
        for gap in ("\n", "\nProse.\n"):
            with self.subTest(gap=repr(gap)):
                self._expect_rejection(
                    "## Task T1\n\n" + task_line() + "\n" + gap
                    + task_suite_line() + "\n", name="sg.md")

    def test_an_orphan_suite_elsewhere_in_the_document_is_refused(self):
        """WHAT PER-TASK ADJACENCY ALONE CANNOT SEE. A suite comment left
        behind by an edit that moved its task sits in the plan claiming to
        verify something, verifies nothing, and reads to a human auditor as
        though it did. The accept half is the same plan without the orphan."""
        clean = task_block("T1") + task_block("T2", order=2,
                                              write_scope="file:src/b.py")
        self.assertEqual(clean.count("pipeline-auto-task-suite"), 2)
        self.assertEqual(len(self.parse(clean, name="cl.md")["tasks"]), 2)
        self._expect_rejection(clean + task_suite_line("T1") + "\n",
                               name="orph.md")
        self._expect_rejection(task_suite_line("T1") + "\n" + clean,
                               name="orph2.md")

    def test_a_second_suite_below_the_first_is_an_orphan_too(self):
        self._expect_rejection(
            "## Task T1\n\n" + task_line() + "\n" + task_suite_line() + "\n"
            + task_suite_line() + "\n", name="two.md")

    def test_an_indented_suite_beside_an_artifact_task_is_still_seen(self):
        """Detection on the stripped line, the suite half. An artifact task is
        proved by its exact approved outputs; a suite beside it is a second
        definition of done, and two spaces must not be enough to hide one."""
        body = ("## Task T1\n\n"
                + task_line(kind="artifact", write_scope="tree:docs",
                            outputs="docs/a.md") + "\n  "
                + task_suite_line() + "\n")
        self.assertIn("\n  <!-- pipeline-auto-task-suite:", body)
        self._expect_rejection(body, name="isu.md")

    def test_an_indented_suite_beside_a_source_task_is_diagnosed_as_indented(self):
        """WHAT THE DOCUMENT-WIDE ACCOUNTING CANNOT DISTINGUISH, and why the
        per-task detector strips too.

        For a SOURCE task the accounting is satisfied either way -- the suite
        IS on the line it belongs on -- so both a stripped and a raw detector
        end in a refusal, and a test that only asserted ``PlanMetadataError``
        would pass on both. What differs is the DIAGNOSIS: detecting on the
        stripped line reaches ``_comment_fields``, which quotes the offending
        line and says it carries leading whitespace, while a raw detector
        reports that the task has NO suite -- sending the author of the plan to
        look for a line that is sitting right there. So the assertion is that
        the message quotes the indented line.
        """
        body = ("## Task T1\n\n" + task_line() + "\n  "
                + task_suite_line() + "\n")
        exception = self._expect_rejection(body, name="isrc.md")
        self.assertIn("  <!-- pipeline-auto-task-suite:", str(exception))
        self.assertNotIn("needs exactly one", str(exception))

    def test_the_command_suite_grammar_is_the_one_task_one_inherits(self):
        """``_parse_command_suite`` is reused, not re-implemented: the empty
        array, the non-array, the unreadable JSON, the duplicate command and
        the pure-ASCII JSON escape that MINTS a lone surrogate are all its
        bars, and the task suite gets them by calling it."""
        for commands in ('[]', '"make check"', '{', '["a", "a"]', '[1]',
                         '["make ' + chr(92) + 'ud800 check"]',
                         '["a' + chr(92) + 'u2028b"]', '["  "]'):
            with self.subTest(commands=commands):
                self._expect_rejection(
                    "## Task T1\n\n" + task_line() + "\n"
                    + task_suite_line("T1", commands) + "\n", name="cmd.md")

    def test_a_multi_command_suite_keeps_the_order_the_plan_wrote_it_in(self):
        """Non-alphabetical on purpose, so a parser that sorted or set-ified
        the commands fails here rather than passing by coincidence."""
        commands = '["make test", "lint --fix", "coverage"]'
        task = self.parse("## Task T1\n\n" + task_line() + "\n"
                          + task_suite_line("T1", commands) + "\n",
                          name="mc.md")["tasks"][0]
        self.assertEqual(task["commands"],
                         ("make test", "lint --fix", "coverage"))
        self.assertNotEqual(list(task["commands"]), sorted(task["commands"]))

    def test_a_command_may_carry_the_field_separator(self):
        """``commands`` is the one task field parsed with ``tail=True``, because
        a shell command legitimately carries ``'; '``. Without the tail the
        second half would be read as an eighth key and refused."""
        commands = '["cd src; make check"]'
        self.assertIn("; ", commands)
        task = self.parse("## Task T1\n\n" + task_line() + "\n"
                          + task_suite_line("T1", commands) + "\n",
                          name="tail.md")["tasks"][0]
        self.assertEqual(task["commands"], ("cd src; make check",))


class TaskIdentityAndOrderTests(PlanFileTestCase):
    """Across the whole plan: ids are unique and orders are a total sequence."""

    def test_duplicate_ids_are_caught_before_a_mapping_collapses_them(self):
        """A dependency mapping built as ``{task['id']: task['deps']}`` silently
        keeps the LAST definition of a repeated id, so the duplicate check has
        to run before it. The fixture makes the two definitions differ, so a
        collapse would be a change of meaning and not merely of count."""
        body = (task_block("T1", write_scope="file:src/a.py")
                + task_block("T1", order=2, write_scope="tree:docs"))
        self.assertEqual(body.count("<!-- pipeline-auto-task: id=T1;"), 2)
        self._expect_rejection(body, name="dup.md")

    def test_orders_must_strictly_increase_down_the_document(self):
        """Worktrees are merged ``--no-ff`` IN TASK ORDER, so a repeated order
        leaves two tasks with equal claim to one position, and a document whose
        sequence disagrees with its own ``order`` fields is two answers to
        'which is integrated first' with nothing to choose between them."""
        for orders in ((1, 1), (2, 1), (3, 2), (1, 3, 2), (1, 2, 2)):
            with self.subTest(orders=orders):
                self._expect_rejection(
                    "".join(task_block(f"T{index}", order=order,
                                       write_scope=f"file:src/a{index}.py")
                            for index, order in enumerate(orders, start=1)),
                    name="ord.md")

    def test_orders_need_not_be_contiguous_only_increasing(self):
        """The ACCEPT half, and its fixture property is asserted: the gaps are
        real, so a check written as 'orders equal 1..N' fails here."""
        orders = (1, 5, 9)
        self.assertNotEqual(list(orders), list(range(1, len(orders) + 1)))
        metadata = self.parse(
            "".join(task_block(f"T{index}", order=order,
                               write_scope=f"file:src/a{index}.py")
                    for index, order in enumerate(orders, start=1)),
            name="gap.md")
        self.assertEqual([task["order"] for task in metadata["tasks"]],
                         list(orders))


class TaskDependencyTests(PlanFileTestCase):
    """``_validate_acyclic_dependencies`` and what the plan hands it."""

    def _plan(self, *specs: tuple) -> str:
        return "".join(
            task_block(task_id, deps=deps, order=order,
                       write_scope=f"file:src/{task_id}.py")
            for order, (task_id, deps) in enumerate(specs, start=1))

    def test_a_diamond_is_a_legal_dependency_graph(self):
        """The ACCEPT half, and the shape a naive cycle detector gets wrong:
        ``T4`` is reached twice, through ``T2`` and through ``T3``, so a walk
        that treats 'seen already' as 'cycle' rejects a perfectly fine plan."""
        metadata = self.parse(
            self._plan(("T1", "none"), ("T2", "T1"), ("T3", "T1"),
                       ("T4", "T2,T3")), name="dia.md")
        self.assertEqual([task["deps"] for task in metadata["tasks"]],
                         [(), ("T1",), ("T1",), ("T2", "T3")])

    def test_cycles_of_every_length_are_refused(self):
        for label, specs in (
                ("two", (("T1", "T2"), ("T2", "T1"))),
                ("three", (("T1", "T2"), ("T2", "T3"), ("T3", "T1"))),
                ("tail", (("T1", "none"), ("T2", "T3"), ("T3", "T2")))):
            with self.subTest(cycle=label):
                self._expect_rejection(self._plan(*specs), name=f"cy{label}.md")

    def test_an_unknown_dependency_is_refused_by_name(self):
        exception = self._expect_rejection(
            self._plan(("T1", "T9"), ("T2", "none")), name="unk.md")
        self.assertIn("T9", str(exception))

    def test_a_dependency_may_not_be_integrated_after_the_task_that_waits(self):
        """THE ROUTE THE STRICTLY-INCREASING RULE DOES NOT WATCH. Orders that
        strictly increase and a dependency graph that is acyclic and closed are
        each satisfiable while CONTRADICTING each other: the plan below is
        increasing, acyclic and closed, and it says both that T1 is integrated
        first and that T1 waits on T2.

        That matters because worktrees are merged ``--no-ff`` IN TASK ORDER,
        which is document order -- so accepting this plan is accepting two
        answers to 'which is integrated first', the very defect the
        strictly-increasing rule was written to close. It is also what makes
        'task order is a topological order' a true statement for the phases
        that consume this metadata rather than a hopeful one.
        """
        forward = (task_block("T1", deps="T2", order=1,
                              write_scope="file:src/a.py")
                   + task_block("T2", order=2, write_scope="file:src/b.py"))
        #: The fixture's discriminating property: it passes every OTHER rule.
        self.assertIn("order=1", forward)
        self.assertIn("order=2", forward)
        exception = self._expect_rejection(forward, name="fwd.md")
        self.assertIn("integrated BEFORE", str(exception))
        self.assertNotIn("strictly increase", str(exception))
        self.assertNotIn("contains a cycle", str(exception))

    def test_an_equal_order_dependency_is_unreachable_and_here_is_what_closes_it(self):
        """WHY THE RULE IS ``>=`` AND WHY THAT IS UNOBSERVABLE. The comparison
        is written as 'not strictly earlier' because that is the statement
        being made, but the EQUAL half cannot be reached: a dependency with the
        same order as its dependent is either a different task -- and two
        distinct tasks with equal orders are refused by the strictly-increasing
        rule -- or the task itself, refused by the self-dependency check. So
        weakening ``>=`` to ``>`` changes no verdict, and the honest record of
        that is this test, which asserts the two checks that close the case
        rather than leaving the reader to trust the claim.

        The half that IS reachable is the adjacent one: a dependency at the
        NEXT order, one step the wrong way, which nothing else sees.
        """
        #: Closer 1: equal orders between distinct tasks.
        equal = self._expect_rejection(
            task_block("T1", deps="T2", order=1, write_scope="file:src/a.py")
            + task_block("T2", order=1, write_scope="file:src/b.py"),
            name="equal.md")
        self.assertIn("strictly increase", str(equal))
        #: Closer 2: the only other way to spell an equal-order dependency.
        self.assertIn("lists itself",
                      str(self._expect_rejection(task_block("T1", deps="T1"),
                                                 name="equal-self.md")))
        #: And the reachable half of the rule.
        exception = self._expect_rejection(
            task_block("T1", order=1, write_scope="file:src/a.py")
            + task_block("T2", deps="T3", order=2, write_scope="file:src/b.py")
            + task_block("T3", order=3, write_scope="file:src/c.py"),
            name="fwd1.md")
        self.assertIn("integrated BEFORE", str(exception))
        self.assertIn("'T3'", str(exception))

    def test_every_dependency_pointing_backwards_is_still_accepted(self):
        """The ACCEPT half, and it is the shape every committed fixture
        already had -- the diamond and ``deps='T3,T2'`` both point backwards --
        so the rule above tightens the grammar without narrowing what the plan
        could already say. A rule that refused these would be refusing the
        plans this phase exists to run."""
        metadata = self.parse(
            self._plan(("T1", "none"), ("T2", "T1"), ("T3", "T1"),
                       ("T4", "T3,T2")), name="back.md")
        order_of = {task["id"]: task["order"] for task in metadata["tasks"]}
        for task in metadata["tasks"]:
            for dependency in task["deps"]:
                self.assertLess(order_of[dependency], task["order"])
        self.assertEqual(metadata["tasks"][3]["deps"], ("T3", "T2"))

    def test_the_rule_runs_after_the_walk_that_proves_the_graph_is_closed(self):
        """ORDERING INSIDE THE FUNCTION, asserted because getting it wrong is a
        ``KeyError``. The order rule indexes a mapping keyed by declared task
        id, so an edge to an id no task declares would index a missing key and
        leave the family -- which is why the closure walk runs first. The
        fixture is an OPEN graph whose unknown edge also points forward, so
        both rules have something to say and only the closure one may."""
        exception = self._expect_rejection(
            task_block("T1", deps="T9", order=1, write_scope="file:src/a.py")
            + task_block("T2", order=2, write_scope="file:src/b.py"),
            name="open-fwd.md")
        self.assertIn("is depended on and never declared", str(exception))
        self.assertNotIsInstance(exception, KeyError)

    def test_validate_acyclic_dependencies_is_total_and_parameterised(self):
        """THE ``KeyError`` THE HELPER MUST NOT RAISE. It is handed an
        ``error_type`` precisely so later phases can reuse it, and a later
        caller is exactly the one that will not have pre-filtered its edges --
        so an open graph has to come back as ``error_type`` and never as a
        ``KeyError`` escaping the family."""
        state._validate_acyclic_dependencies(
            {"a": ("b",), "b": ("c",), "c": (), "d": ("b", "c")},
            error_type=state.PlanMetadataError, subject="task")
        state._validate_acyclic_dependencies(
            {}, error_type=state.PlanMetadataError, subject="task")
        for graph in ({"a": ("b",)}, {"a": ("a",)}, {"a": ("b",), "b": ("a",)},
                      {"a": ("b",), "b": ("c",), "c": ("a",)}):
            with self.subTest(graph=sorted(graph.items())):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state._validate_acyclic_dependencies(
                        graph, error_type=state.TrackerValidationError,
                        subject="phase")
                self.assertIn("phase", str(caught.exception))
                self.assertNotIsInstance(caught.exception, KeyError)

    def test_the_helpers_totality_is_over_closed_graphs_of_hashable_ids(self):
        """THE CLAIM, NARROWED TO WHAT WAS MEASURED. 'Total' above means total
        for the OPEN GRAPH, which is the one shape a caller really does hand
        it, and the helper is parameterised for reuse -- so the boundary of the
        claim is owed to the reuser rather than left to be found. Measured
        outside a mapping of hashable ids with a path shorter than the
        recursion limit, the helper leaves the family three ways.

        This module's own callers never reach any of them: every id is a
        ``_TOKEN`` string, so every edge is hashable, and every graph is
        bounded by ``MAX_TASKS_PER_PHASE``, so no path is deep. A later caller
        that cannot promise the same owes itself a screen before the call --
        which is exactly what the docstring now says, and this test is what
        stops the docstring drifting back to 'any graph'."""
        deep = {str(node): (str(node + 1),) for node in range(sys.getrecursionlimit() + 100)}
        deep[str(sys.getrecursionlimit() + 100)] = ()
        for label, graph, escape in (
                ("a non-mapping", ["a"], AttributeError),
                ("an unhashable edge", {"a": (["b"],), "b": ()}, TypeError),
                ("a path deeper than the recursion limit", deep, RecursionError)):
            with self.subTest(outside=label):
                with self.assertRaises(escape) as caught:
                    state._validate_acyclic_dependencies(
                        graph, error_type=state.PlanMetadataError,
                        subject="task")
                self.assertNotIsInstance(caught.exception, state.TrackerError)
        #: And the domain the module's own callers stay inside, so the
        #: narrowing is a claim about reuse and not an excuse for a live bug.
        self.assertLess(state.MAX_TASKS_PER_PHASE, sys.getrecursionlimit())
        self.assertTrue(state._TOKEN.fullmatch("T1"))

    def test_the_helper_visits_every_component_not_only_the_first(self):
        """A walk seeded from one node finds only that node's component, so a
        cycle in a DISCONNECTED part of the graph escapes it. The fixture puts
        the cycle strictly after an acyclic component, in dict order."""
        graph = {"a": (), "b": ("a",), "c": ("d",), "d": ("c",)}
        self.assertEqual(list(graph)[:2], ["a", "b"])
        with self.assertRaises(state.PlanMetadataError):
            state._validate_acyclic_dependencies(
                graph, error_type=state.PlanMetadataError, subject="task")

class PlanPathTests(TempDirTestCase):
    """RULE 11. ``parse_plan_metadata`` is the first thing in the plan grammar
    that OPENS something, so every way a name can exist and not be readable is
    its problem.

    ``is_file()`` NEVER MEANS 'there is nothing here'. It is false for a
    directory, for a dangling symlink, for a symlink LOOP and for a FIFO, and
    all four are names that exist. Three of them fail an open loudly; the FIFO
    does not -- opening one for reading BLOCKS until a writer arrives, and on a
    plan path no writer is coming. That is a deadlock, not an error.

    AND THE PATH CORPUS IS NOT THE FIELD-VALUE CORPUS. Five families are owed
    and they fail in five different places, which is exactly why a corpus drawn
    from one of them proves nothing about the other four.
    """

    def _valid_plan(self, name: str = "phase-04.md"):
        return write_phase_plan(self.tmp, task_block("T1"), name=name)

    def _expect_path_rejection(self, path) -> Exception:
        with self.assertRaises(state.PlanMetadataError) as caught:
            state.parse_plan_metadata(path)
        return caught.exception

    def test_an_ordinary_plan_path_is_accepted_as_a_str_and_as_a_path(self):
        """The ACCEPT half of this whole class. Every rejection below is
        satisfied by a function that refuses all paths, and that function
        passes."""
        plan = self._valid_plan()
        for spelling in (plan, str(plan)):
            with self.subTest(kind=type(spelling).__name__):
                metadata = state.parse_plan_metadata(spelling)
                self.assertEqual(metadata["tasks"][0]["id"], "T1")

    # -- family 1: NUL and the rest of range(0x20) ------------------------

    def test_a_control_character_in_the_path_never_reaches_the_syscall(self):
        """MEASURED, and it is why the spelling is screened before the
        filesystem is asked: for a path holding NUL, ``is_file()`` is False AND
        ``os.path.lexists`` is False, so ``_require_regular_file`` is silent by
        design -- absence is not its question -- and the bare read then raises
        ``ValueError: embedded null byte``, from outside ``TrackerError``.

        The whole of ``range(0x20)`` is swept, plus DEL, because a corpus of
        one control character cannot tell a screen that asks from a screen
        that happens to list the one character somebody thought of.
        """
        nul = str(self.tmp / ("a" + chr(0) + "b.md"))
        self.assertFalse(Path(nul).is_file())
        self.assertFalse(os.path.lexists(nul))
        with self.assertRaises(ValueError) as caught:
            Path(nul).read_text(encoding="utf-8")
        #: THIS is the family the read's own ``except (OSError, UnicodeError)``
        #: does not catch -- a PLAIN ``ValueError``, no ``UnicodeError`` in its
        #: MRO -- so for NUL the spelling screen is the only thing standing
        #: between a controller and an exception outside ``TrackerError``.
        self.assertNotIsInstance(caught.exception, (OSError, UnicodeError))
        exception = self._expect_path_rejection(nul)
        self.assertIsNone(exception.__cause__)
        for code in list(range(0x20)) + [0x7F]:
            spelling = str(self.tmp / f"a{chr(code)}b.md")
            with self.subTest(code=hex(code)):
                self.assertIn(chr(code), state._CONTROL_CHARACTERS)
                self._expect_path_rejection(spelling)

    # -- family 2: the row breaks no ASCII list contains -------------------

    def test_a_row_breaking_path_is_refused_although_the_file_really_reads(self):
        """THE FAMILY A CLOSED ASCII LIST MISSES, and the one where the refusal
        is a judgement rather than a failure. ``chr(0x85)``, ``chr(0x2028)``
        and ``chr(0x2029)`` are legal POSIX filename bytes: the files below are
        created, exist, and read back correctly -- so this test asserts the
        file is readable FIRST, and only then that the parser refuses it.

        Refused because a plan path is recorded in ``## Run``'s ``phase_plans``
        cell, and ``str.splitlines`` breaks on all three: the row would come
        back as two rows of the wrong width. ``_cell_safe`` is the screen, and
        its derived half is the half that catches these.
        """
        for code in (0x85, 0x2028, 0x2029):
            character = chr(code)
            plan = write_phase_plan(self.tmp, task_block("T1"),
                                    name=f"a{character}b.md")
            with self.subTest(code=hex(code)):
                #: The discriminating assertions: the name is NOT in the listed
                #: half, and the file it names is genuinely readable.
                self.assertNotIn(character, state._CONTROL_CHARACTERS)
                self.assertTrue(state._splits_the_section(character))
                self.assertTrue(plan.is_file())
                self.assertIn("# Phase 04 plan",
                              plan.read_text(encoding="utf-8"))
                self._expect_path_rejection(plan)

    # -- family 3: lone surrogates ----------------------------------------

    def test_a_lone_surrogate_in_the_path_is_refused_before_the_encoder(self):
        """``is_file()`` and ``os.path.lexists`` are both False -- so the
        regular-file door is silent -- and the read then raises
        ``UnicodeEncodeError`` out of the encoder that turns the name into
        bytes.

        AND THE NAME HAD TO EARN ITS 'BEFORE'. ``UnicodeEncodeError``'s MRO is
        ``UnicodeEncodeError -> UnicodeError -> ValueError``, so the read's own
        ``except (OSError, UnicodeError)`` ALREADY catches it: without the
        spelling screen this family would still come back as a
        ``PlanMetadataError`` and a rejection-only assertion would pass either
        way. The screen is what makes the refusal happen before the open, and
        the observable difference is the ``__cause__`` -- absent when the
        spelling was screened, and the ``UnicodeEncodeError`` itself when the
        refusal came out of the read. That is the discriminating assertion, and
        it is the one that makes 'before the encoder' a measured claim.
        (NUL, family 1, is the family the read's clause genuinely does NOT
        catch: it arrives as a plain ``ValueError``.)
        """
        for code in (0xD800, 0xDBFF, 0xDC00, 0xDFFF):
            spelling = str(self.tmp / f"a{chr(code)}b.md")
            with self.subTest(code=hex(code)):
                self.assertFalse(state._survives_the_encoder(chr(code)))
                self.assertFalse(os.path.lexists(spelling))
                with self.assertRaises(UnicodeEncodeError) as caught:
                    Path(spelling).read_text(encoding="utf-8")
                #: The half that makes the screen invisible to a bare
                #: assertRaises, measured rather than assumed.
                self.assertIsInstance(caught.exception, UnicodeError)
                exception = self._expect_path_rejection(spelling)
                self.assertIsNone(exception.__cause__)
                self.assertIn("lone surrogate", str(exception))

    # -- family 4: the FIFO, which is a deadlock and not an error ----------

    def test_a_fifo_is_refused_before_the_open_that_would_block_forever(self):
        """THE DEADLOCK. ``open`` on a FIFO with no writer never returns, and a
        plan read happens under the run lock -- so a bare ``read_text`` here
        does not fail the run, it HANGS it, holding the lock, with no
        diagnostic and no timeout.

        A hang is not a test failure, it is a suite that never finishes and a
        CI job killed with nothing to read, so the call is fenced with
        ``SIGALRM`` where the platform has one. A regression then arrives as a
        named failure in this test rather than as a timeout somebody has to
        bisect.
        """
        fifo = self.tmp / "fifo.md"
        os.mkfifo(fifo)
        self.assertFalse(fifo.is_file())
        self.assertTrue(os.path.lexists(fifo))
        with self._deadline(5):
            exception = self._expect_path_rejection(fifo)
        self.assertIsInstance(exception.__cause__, state.QuorumError)

    # -- family 5: the symlink loop, whose RuntimeError is not a TrackerError

    def test_a_symlink_loop_is_refused_without_ever_calling_resolve(self):
        """``Path.resolve()`` raises ``RuntimeError`` on a loop -- from
        ``resolve`` itself, and with ``strict=False`` too -- and
        ``RuntimeError`` is not a ``TrackerError``. The assertion below proves
        the loop really is one by watching ``resolve`` raise, and then proves
        the parser answers inside the family anyway, which it can only do by
        not calling ``resolve``."""
        loop = self.tmp / "loop.md"
        os.symlink(loop, loop)
        self.assertFalse(loop.is_file())
        self.assertTrue(os.path.lexists(loop))
        with self.assertRaises(RuntimeError):
            loop.resolve()
        with self.assertRaises(RuntimeError):
            loop.resolve(strict=False)
        self._expect_path_rejection(loop)

    # -- the rest of the door ---------------------------------------------

    def test_a_directory_and_a_dangling_symlink_are_corruption_not_absence(self):
        directory = self.tmp / "plans"
        directory.mkdir()
        dangling = self.tmp / "dangling.md"
        os.symlink(self.tmp / "nowhere.md", dangling)
        for path in (directory, dangling, self.tmp):
            with self.subTest(path=path.name):
                self.assertFalse(path.is_file())
                self.assertTrue(os.path.lexists(path))
                self._expect_path_rejection(path)

    def test_a_missing_plan_is_a_plan_metadata_error_and_not_an_oserror(self):
        missing = self.tmp / "nowhere.md"
        self.assertFalse(os.path.lexists(missing))
        with self.assertRaises(FileNotFoundError):
            missing.read_text(encoding="utf-8")
        exception = self._expect_path_rejection(missing)
        self.assertIsInstance(exception.__cause__, FileNotFoundError)

    def test_a_plan_that_is_not_utf8_is_refused_inside_the_family(self):
        """The half of ``(OSError, UnicodeError)`` the spelling screen does NOT
        make unreachable: the bytes of the FILE, rather than of its name."""
        plan = self.tmp / "latin.md"
        plan.write_bytes(b"# Phase 04 plan\n\n\xff\xfe not utf-8\n")
        with self.assertRaises(UnicodeDecodeError):
            plan.read_text(encoding="utf-8")
        exception = self._expect_path_rejection(plan)
        self.assertIsInstance(exception.__cause__, UnicodeDecodeError)

    def test_a_pipe_in_the_path_is_refused_although_the_file_reads(self):
        """``|`` is the column separator, so a plan path carrying one cannot be
        recorded in ``phase_plans`` without re-columning that row. The file is
        asserted readable first, so the refusal is provably the cell bar."""
        plan = write_phase_plan(self.tmp, task_block("T1"), name="a|b.md")
        self.assertTrue(plan.is_file())
        self._expect_path_rejection(plan)

    def test_a_non_path_argument_never_leaves_the_family(self):
        for value in (None, 7, 3.5, b"/tmp/a.md", ["/tmp/a.md"], {"a": 1},
                      PurePosixPath("a.md"), object()):
            with self.subTest(value=type(value).__name__):
                self._expect_path_rejection(value)

    def test_an_empty_or_whitespace_padded_path_is_refused(self):
        plan = self._valid_plan()
        for spelling in ("", " ", str(plan) + " ", " " + str(plan)):
            with self.subTest(spelling=repr(spelling)):
                self._expect_path_rejection(spelling)

    def test_a_refused_plan_is_byte_identical_and_its_directory_untouched(self):
        """The read-only-stop rule, now stated about a real file rather than
        about a list of lines -- which is the whole difference Task 1's grammar
        could not make."""
        plan = write_phase_plan(self.tmp, task_block("T1", write_scope="oops"),
                                name="bad.md")
        before = plan.read_bytes()
        listing = sorted(entry.name for entry in self.tmp.iterdir())
        with self.assertRaises(state.PlanMetadataError):
            state.parse_plan_metadata(plan)
        self.assertEqual(plan.read_bytes(), before)
        self.assertEqual(sorted(entry.name for entry in self.tmp.iterdir()),
                         listing)

    @contextlib.contextmanager
    def _deadline(self, seconds: int):
        """Turn a hang into a named failure, where the platform allows it."""
        if not hasattr(signal, "SIGALRM"):  # pragma: no cover - POSIX only
            yield
            return

        def expire(signum, frame):
            raise AssertionError(
                "parse_plan_metadata blocked: the open reached a FIFO, which "
                "is the deadlock _require_regular_file exists to prevent")

        previous = signal.signal(signal.SIGALRM, expire)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)


class ParsePlanMetadataShapeTests(PlanFileTestCase):
    """What the entry point RETURNS, pinned so later P04 tasks can rely on it."""

    def test_the_result_carries_exactly_the_phase_and_the_tasks(self):
        metadata = self.parse(task_block("T1"))
        self.assertEqual(sorted(metadata), ["phase", "tasks"])
        self.assertEqual(sorted(metadata["phase"]),
                         ["commands", "deps", "id", "review_class",
                          "review_reason"])

    def test_every_task_carries_the_eight_keys_in_the_declared_order(self):
        """The key ORDER of the returned mapping is asserted, not just the key
        SET: the seven the plan declares, in the plan's order, then the
        ``commands`` the suite supplies. A later task reading a task dict --
        or rendering one into a row -- inherits this sequence."""
        metadata = self.parse(
            task_block("T1")
            + task_block("T2", kind="artifact", order=2, write_scope="tree:docs",
                         outputs="docs/a.md"))
        for task in metadata["tasks"]:
            with self.subTest(task=task["id"]):
                self.assertEqual(list(task),
                                 list(state._TASK_KEYS) + ["commands"])

    def test_every_multi_valued_field_comes_back_as_a_tuple(self):
        task = self.parse(
            task_block("T1", order=1, write_scope="file:src/a.py")
            + task_block("T2", deps="T1", order=2,
                         write_scope="file:src/b.py,tree:docs")
        )["tasks"][1]
        for key in ("deps", "write_scope", "outputs", "commands"):
            with self.subTest(key=key):
                self.assertIsInstance(task[key], tuple)

    def test_the_phase_half_is_parse_phase_headers_and_not_a_second_copy(self):
        """A bad phase header stops the whole plan, and the bad half is the ONLY
        thing wrong with the fixture -- the tasks below it are valid, and the
        same body with a good header parses."""
        body = task_block("T1")
        self.assertEqual(self.parse(body, name="good.md")["tasks"][0]["id"],
                         "T1")
        for header in (phase_header(review_class="medium"),
                       phase_header(review_reason=""),
                       phase_line(tuple(sorted(state._PHASE_KEYS))) + "\n"
                       + suite_line() + "\n"):
            with self.subTest(header=header.splitlines()[0][:48]):
                self._expect_rejection(body, header=header, name="ph.md")

    def test_the_public_names_this_task_produces_exist_and_are_pinned(self):
        self.assertEqual(state.TASK_KINDS, ("source", "artifact"))
        self.assertEqual(state.MAX_TASKS_PER_PHASE, 12)
        for name in ("TASK_KINDS", "MAX_TASKS_PER_PHASE",
                     "_validate_acyclic_dependencies", "_parse_write_scope",
                     "_parse_task_metadata", "parse_plan_metadata"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(state, name), name)

    def test_parse_task_metadata_is_callable_on_lines_without_a_file(self):
        """The pure half stays pure: only ``parse_plan_metadata`` opens
        anything, so the grammar underneath it can be exercised -- and can be
        reused by a later task -- with no filesystem at all."""
        lines = ["## Task T1", "", task_line(), task_suite_line()]
        task = state._parse_task_metadata(lines, 2)
        self.assertEqual(task["id"], "T1")
        self.assertEqual(task["commands"], ("python3 -m unittest -k T1",))


class TaskHarnessTests(PlanFileTestCase):
    """The Task 2 additions to the shared harness, asserted rather than assumed."""

    def test_task_line_refuses_an_override_it_would_never_read(self):
        for bad in ({"kinds": "source"}, {"Id": "T1"}, {"write-scope": "x"},
                    {"nonsense": "x"}, {"kind": "source", "nonsense": "x"}):
            with self.subTest(bad=sorted(bad)):
                with self.assertRaises(KeyError):
                    task_line(**bad)

    def test_task_line_refuses_to_render_a_key_it_has_no_value_for(self):
        """A renamed key is built by replacing one ``key=`` substring of the
        valid line, never by asking the harness for a key it does not know --
        so a typo in a ``keys`` tuple is loud instead of silently rendering
        six keys and testing the drop case by accident."""
        with self.assertRaises(KeyError):
            task_line(("id", "deps", "kind", "batch", "order", "write_scope",
                       "bogus"))

    def test_task_line_honours_every_pinned_override(self):
        for key, value in (("id", "T7"), ("deps", "T1,T2"),
                           ("kind", "artifact"), ("batch", "b9"),
                           ("order", "4"), ("write_scope", "tree:docs"),
                           ("outputs", "docs/a.md")):
            with self.subTest(key=key):
                self.assertIn(f"{key}={value}", task_line(**{key: value}))

    def test_task_block_still_renders_the_bytes_task_one_committed(self):
        """``task_block`` is now expressed through ``task_line``, and every
        Task 1 test that reads its output depends on the bytes being the same."""
        self.assertEqual(
            task_block("T1"),
            "## Task T1\n\n"
            "<!-- pipeline-auto-task: id=T1; deps=none; kind=source; "
            "batch=b1; order=1; write_scope=file:src/a.py; outputs=none -->\n"
            '<!-- pipeline-auto-task-suite: id=T1; commands='
            '["python3 -m unittest -k T1"] -->\n'
            "\nProse describing the task.\n\n")
        self.assertNotIn("pipeline-auto-task-suite",
                         task_block("T1", kind="artifact"))

    def test_task_values_is_one_valid_value_per_pinned_key(self):
        """The property every reorder/drop/rename fixture leans on: change one
        thing and the rest stays valid. Asserted by parsing the default."""
        self.assertEqual(sorted(TASK_VALUES), sorted(state._TASK_KEYS))
        self.assertTrue(all(isinstance(value, str)
                            for value in TASK_VALUES.values()))
        self.assertEqual(
            self.parse("## Task T1\n\n" + task_line() + "\n"
                       + task_suite_line() + "\n", name="tv.md")["tasks"][0]["id"],
            "T1")


# --------------------------------------------------------------------------
# Task 3 tests -- fault F1: `scopes_overlap` implemented as plain equality, so
# `tree:src` and `file:src/a.py` reserve together and two implementers write
# the same file.
#
# THE CORPUS IS A TABLE OF REASONS, NOT A LIST OF BOOLEANS, and that is the
# whole design. `scopes_overlap` returns a bool, so two different rules can
# agree on every fixture anybody thought to write down -- which is exactly how
# F1 survives: an equality rule and an ancestor rule both say True for
# `tree:src` against `tree:src`, so a test that only asserts True cannot tell
# them apart. Every row below therefore carries the REASON it holds, each
# reason family carries a structural assertion that a rival rule provably
# fails, and `RivalRuleTests` runs the rivals over the table and demands a
# disagreement with a named witness. A corpus that stopped discriminating would
# fail there rather than pass quietly.
# --------------------------------------------------------------------------

#: A path segment spelled with one precomposed code point, and the same
#: grapheme spelled as base + combining accent. Built with `chr` because a
#: \uXXXX escape in a tool argument is decoded before it reaches disk, so the
#: two spellings would silently become one file.
_PRECOMPOSED = "caf" + chr(0xE9)
_DECOMPOSED = "caf" + "e" + chr(0x301)

#: (left, right, expected, reason). Read the reasons before the booleans.
#:
#: * `same-path`      - the two scopes name the same path. TRUE, and it is the
#:                      one family a plain equality rule also gets right.
#: * `ancestor`       - the paths DIFFER and one contains the other. TRUE, and
#:                      an equality rule cannot produce it. This is F1.
#: * `prefix`         - one path string is a strict PREFIX of the other without
#:                      being a path ancestor. FALSE, and a `startswith`
#:                      spelling cannot produce it. This is the trap one level
#:                      up from F1.
#: * `file-ancestor`  - one path IS a proper ancestor of the other, but the
#:                      containing scope is a `file:`. FALSE, and a type-blind
#:                      ancestry rule cannot produce it.
#: * `case`           - segments differing only in case. FALSE; POSIX paths are
#:                      case-sensitive and the tracker records bytes.
#: * `normalisation`  - the same grapheme in two Unicode spellings. FALSE;
#:                      `PurePosixPath` does not normalise, so these are two
#:                      paths, and nobody writes this fixture down by accident.
#: * `unrelated`      - no relation at all.
SCOPE_PAIRS = (
    ("file:src/a.py", "file:src/a.py", True, "same-path"),
    ("tree:src", "tree:src", True, "same-path"),
    ("tree:src", "file:src", True, "same-path"),
    ("file:src/a:b.py", "file:src/a:b.py", True, "same-path"),
    ("tree:.github/workflows", "file:.github/workflows", True, "same-path"),
    ("tree:" + _PRECOMPOSED, "tree:" + _PRECOMPOSED, True, "same-path"),

    ("tree:src", "file:src/a.py", True, "ancestor"),
    ("tree:src", "tree:src/deep/nested", True, "ancestor"),
    ("tree:src/pkg", "file:src/pkg/mod/a.py", True, "ancestor"),
    ("tree:.github", "file:.github/workflows/ci.yml", True, "ancestor"),
    ("tree:a", "file:a/b/c/d/e/f/g/h/i/j/k.py", True, "ancestor"),
    ("tree:a-b", "file:a-b/c.py", True, "ancestor"),
    ("file:a/b/c.py", "tree:a/b", True, "ancestor"),
    ("tree:src", "file:src/a:b.py", True, "ancestor"),
    ("tree:" + _PRECOMPOSED, "file:" + _PRECOMPOSED + "/a.py", True, "ancestor"),

    ("tree:src", "file:srcx/a.py", False, "prefix"),
    ("tree:docs", "tree:docsx", False, "prefix"),
    ("tree:src/pkg", "file:src/pkgx/a.py", False, "prefix"),
    ("tree:.git", "file:.github/workflows/ci.yml", False, "prefix"),
    ("tree:v1", "file:v10/a.py", False, "prefix"),
    ("tree:a-b", "file:a-b-c/x.py", False, "prefix"),
    ("file:src/a.py", "file:src/a.pyc", False, "prefix"),
    ("tree:a/b", "tree:a/bc/d", False, "prefix"),

    ("file:src/a.py", "tree:src/a.py/deep", False, "file-ancestor"),
    ("file:a", "file:a/b", False, "file-ancestor"),
    ("file:docs", "file:docs/index.md", False, "file-ancestor"),

    ("tree:src", "file:SRC/a.py", False, "case"),
    ("tree:Docs", "tree:docs", False, "case"),

    ("tree:" + _PRECOMPOSED, "file:" + _DECOMPOSED + "/a.py", False,
     "normalisation"),
    ("file:" + _PRECOMPOSED, "file:" + _DECOMPOSED, False, "normalisation"),

    ("file:src/a.py", "file:src/b.py", False, "unrelated"),
    ("tree:src", "tree:docs", False, "unrelated"),
    ("tree:src", "file:docs/a.md", False, "unrelated"),
    ("tree:source", "file:src/a.py", False, "unrelated"),
    ("file:a/b/c.py", "tree:a/b/d", False, "unrelated"),
)


def scope_path(scope: str) -> str:
    """The path half of a typed scope, split the way the module splits it.

    `partition` and not `split(":")`: `file:src/a:b.py` is a legal scope whose
    PATH carries a colon, and a maxsplit-free split would throw `b.py` away and
    quietly turn a fixture into a different fixture.
    """
    return scope.partition(":")[2]


def scope_type(scope: str) -> str:
    return scope.partition(":")[0]


def is_ancestor(outer: str, inner: str) -> bool:
    """Proper path ancestry, asked the way the module asks it."""
    return PurePosixPath(outer) in PurePosixPath(inner).parents


def claims(kind: str, scope: str, path: str) -> bool:
    """Does the typed scope `kind:scope` claim `path`? THE INDEPENDENT ORACLE.

    Written out of raw `"/"`-separated segments and importing NOTHING from the
    module -- not `_scope_claims`, not `_path_in_scope`, not `PurePosixPath`.
    That is the whole point of it. The cross-product tests used to compute
    their witness sets with `state._path_in_scope`, which is built on
    `_scope_claims`, which is what `scopes_overlap` is built on: mutate the
    containment predicate and BOTH sides of the "oracle" move together, so the
    witness logic agrees with itself and the only thing left to fail is a
    coverage counter. Measured under the F1 mutant before this was written: 40
    pairs with a shared witness, ZERO logical contradictions, and all three
    kills came from `assertGreater(checked, 60)`.

    A segment list is the definition rather than a re-implementation: `file:`
    claims one path, `tree:` claims its own path and every path whose segments
    START with the scope's segments. Comparing SEGMENTS and not characters is
    what keeps `tree:src` off `srcx/a.py`, and it is arrived at here from the
    meaning of a directory rather than from the module's spelling of it.
    """
    scope_segments = scope.split("/")
    path_segments = path.split("/")
    if path_segments == scope_segments:
        return True
    return (kind == "tree"
            and len(path_segments) > len(scope_segments)
            and path_segments[:len(scope_segments)] == scope_segments)


def scope_claims_path(scope: str, path: str) -> bool:
    """`claims`, addressed by a whole scope string. The corpus is written in
    scopes and the oracle is written in parts; this is the join, and it is one
    line so the oracle stays as short as it is legible."""
    return claims(scope_type(scope), scope_path(scope), path)


class ScopeAlgebraTests(unittest.TestCase):
    """The plain read of the contract, kept as the brief wrote it."""

    def test_overlapping_scopes_conflict(self):
        cases = (
            ("file:src/a.py", "file:src/a.py"),
            ("tree:src", "file:src/a.py"),          # the pair plain equality misses
            ("tree:src", "tree:src/deep/nested"),
            ("tree:src", "tree:src"),
            ("tree:src/pkg", "file:src/pkg/mod/a.py"),
            ("tree:src/a.py", "file:src/a.py"),     # a tree naming exactly one file
        )
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertTrue(state.scopes_overlap(left, right))
                self.assertTrue(state.scopes_overlap(right, left))

    def test_disjoint_scopes_do_not_conflict(self):
        cases = (
            ("file:src/a.py", "file:src/b.py"),
            ("tree:src", "tree:docs"),
            ("tree:src", "file:docs/a.md"),
            ("tree:source", "file:src/a.py"),       # a name prefix is not ancestry
            ("tree:src/pkg", "file:src/pkgx/a.py"),
            ("file:src/a.py", "tree:src/a.py/deep"),
        )
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertFalse(state.scopes_overlap(left, right))
                self.assertFalse(state.scopes_overlap(right, left))

    def test_rejects_untyped_or_unsafe_scopes(self):
        for scope in ("src/a.py", "glob:src", "file:../a", "file:"):
            with self.subTest(scope=scope):
                with self.assertRaises(state.PlanMetadataError):
                    state.scopes_overlap(scope, "file:src/a.py")

    def test_scope_sets_find_a_single_conflicting_pair(self):
        left = ("file:src/a.py", "tree:docs")
        self.assertTrue(
            state._scope_sets_overlap(left, ("file:src/b.py", "file:docs/index.md"))
        )
        self.assertFalse(
            state._scope_sets_overlap(left, ("file:src/b.py", "tree:reports"))
        )

    def test_path_in_scope(self):
        cases = (
            ("src/a.py", "file:src/a.py", True),
            ("src/a.py", "file:src/b.py", False),
            ("src/a.py", "tree:src", True),
            ("src/deep/a.py", "tree:src", True),
            ("srcx/a.py", "tree:src", False),
            ("src", "tree:src", True),
        )
        for path, scope, expected in cases:
            with self.subTest(path=path, scope=scope):
                self.assertIs(state._path_in_scope(path, scope), expected)


class ScopeReasonTableTests(unittest.TestCase):
    """Every row of `SCOPE_PAIRS`, with the reason asserted structurally.

    The boolean alone is what let F1 hide. Each family below also asserts the
    PROPERTY that makes the row discriminating, so a fixture cannot be quietly
    edited into a row that no longer separates the rules it was written to
    separate.
    """

    def test_every_pair_answers_as_the_table_says(self):
        for left, right, expected, reason in SCOPE_PAIRS:
            with self.subTest(left=left, right=right, reason=reason):
                self.assertIs(state.scopes_overlap(left, right), expected)

    def test_the_answer_is_symmetric_for_every_pair(self):
        """Symmetry is a property of the EXPRESSION in the module -- "does
        either scope claim the other's root" -- and it is asserted here so that
        a rewrite into a type-pair case analysis, which is where the ancestor
        branch went missing the first time, cannot reintroduce an asymmetric
        arm unnoticed."""
        for left, right, expected, _ in SCOPE_PAIRS:
            with self.subTest(left=left, right=right):
                self.assertIs(state.scopes_overlap(right, left), expected)

    def test_the_answer_is_a_bool_and_not_a_truthy_object(self):
        """`assertTrue` accepts a `PurePosixPath`; a caller writing the answer
        into a tracker cell does not."""
        for left, right, _, _ in SCOPE_PAIRS:
            with self.subTest(left=left, right=right):
                self.assertIsInstance(state.scopes_overlap(left, right), bool)

    def test_the_ancestor_family_is_unreachable_by_equality(self):
        """F1, stated as a property of the corpus rather than of one fixture.

        Every `ancestor` row has UNEQUAL paths and a real containment, so a
        plain equality rule provably cannot answer True for any of them -- and
        each of them is True."""
        rows = [row for row in SCOPE_PAIRS if row[3] == "ancestor"]
        self.assertGreaterEqual(len(rows), 9)
        for left, right, expected, _ in rows:
            with self.subTest(left=left, right=right):
                self.assertTrue(expected)
                self.assertNotEqual(scope_path(left), scope_path(right))
                self.assertTrue(
                    is_ancestor(scope_path(left), scope_path(right))
                    or is_ancestor(scope_path(right), scope_path(left)))
                self.assertIn("tree", (scope_type(left), scope_type(right)))

    def test_the_prefix_family_is_reachable_by_startswith_and_is_false(self):
        """The trap one level up from equality: `"docsx/a.md".startswith(
        "docs")` is True. Every `prefix` row really is a string prefix, so a
        `startswith` spelling provably answers True for all of them -- and the
        right answer for all of them is False."""
        rows = [row for row in SCOPE_PAIRS if row[3] == "prefix"]
        self.assertGreaterEqual(len(rows), 8)
        for left, right, expected, _ in rows:
            with self.subTest(left=left, right=right):
                self.assertFalse(expected)
                one, two = scope_path(left), scope_path(right)
                self.assertTrue(one.startswith(two) or two.startswith(one))
                self.assertFalse(is_ancestor(one, two) or is_ancestor(two, one))

    def test_the_file_ancestor_family_is_ancestry_the_type_forbids(self):
        """A `file:` scope claims ONE path. `file:src/a.py` against
        `tree:src/a.py/deep` is genuine path ancestry and still no conflict,
        so a rule that dropped the type and asked only about containment
        provably answers True for all of them."""
        rows = [row for row in SCOPE_PAIRS if row[3] == "file-ancestor"]
        self.assertGreaterEqual(len(rows), 3)
        for left, right, expected, _ in rows:
            with self.subTest(left=left, right=right):
                self.assertFalse(expected)
                one, two = scope_path(left), scope_path(right)
                self.assertTrue(is_ancestor(one, two) or is_ancestor(two, one))
                outer = left if is_ancestor(one, two) else right
                self.assertEqual(scope_type(outer), "file")

    def test_the_same_path_family_is_the_one_equality_also_gets_right(self):
        rows = [row for row in SCOPE_PAIRS if row[3] == "same-path"]
        self.assertGreaterEqual(len(rows), 6)
        for left, right, expected, _ in rows:
            with self.subTest(left=left, right=right):
                self.assertTrue(expected)
                self.assertEqual(scope_path(left), scope_path(right))

    def test_a_differing_type_over_an_equal_path_still_conflicts(self):
        """`tree:src` and `file:src` are different STRINGS naming the same
        path. A rule that compared the whole scope string -- `return a == b` --
        would answer False, and the two tasks would both be dispatched onto
        `src`."""
        self.assertNotEqual("tree:src", "file:src")
        self.assertIs(state.scopes_overlap("tree:src", "file:src"), True)
        self.assertIs(state.scopes_overlap("file:src", "tree:src"), True)

    def test_case_and_unicode_spelling_are_two_paths_and_not_one(self):
        """Two families nobody writes down by hand. `PurePosixPath` neither
        case-folds nor normalises, so `caf` + U+00E9 and `cafe` + U+0301 are
        two distinct scopes -- and a future implementation that reached for
        `str.lower()` or `unicodedata.normalize` would be widening
        `ALLOWED_IMPORTS` to make two tracker cells that differ in bytes
        compare equal."""
        self.assertNotEqual(_PRECOMPOSED, _DECOMPOSED)
        self.assertEqual(_PRECOMPOSED.casefold(), _PRECOMPOSED)
        for left, right, expected, reason in SCOPE_PAIRS:
            if reason in ("case", "normalisation"):
                with self.subTest(left=left, right=right, reason=reason):
                    self.assertIs(state.scopes_overlap(left, right), expected)
                    self.assertNotEqual(scope_path(left), scope_path(right))

    def test_the_table_covers_every_named_reason(self):
        """A row deleted or a family silently emptied is a corpus that stopped
        discriminating; the count is the alarm."""
        reasons = {row[3] for row in SCOPE_PAIRS}
        self.assertEqual(
            reasons,
            {"same-path", "ancestor", "prefix", "file-ancestor", "case",
             "normalisation", "unrelated"})
        self.assertGreaterEqual(len(SCOPE_PAIRS), 35)


class RivalRuleTests(unittest.TestCase):
    """The corpus is only worth what it REFUTES, so the rivals are run here.

    Each rival below is a plausible wrong implementation -- three of them are
    named faults or one step from one -- and each is required to disagree with
    the real answers on a witness row the test names. This is the assertion
    that a fixture list drawn from "the defects that were thought of" cannot
    make: it fails the moment the corpus stops separating two rules, instead of
    passing quietly while a mutant survives.

    EVERY RIVAL IS RUN IN BOTH ORDERS, and that is not tidiness. A rival is a
    function of two arguments; running it only as `rule(left, right)` asks it
    about the twelve (type_a, type_b, relation) cells `SCOPE_PAIRS` happens to
    spell in that order and leaves four -- `(file,file,b<a)`, `(file,tree,eq)`,
    `(tree,file,b<a)`, `(tree,tree,b<a)` -- never asked. Measured: over the
    complete space of boolean functions of that cell, fifteen rivals agreed
    with the one-direction answers everywhere and still differed from the real
    rule, and one of them -- `test_a_one_armed_tree_branch_is_refuted` below --
    is F1's own omission moved one cell over. Reversing each row closes all
    four; `test_the_corpus_pins_every_type_pair_cell` is the standing proof.
    """

    def rows(self) -> tuple:
        """Every pair in BOTH orders. The expected answer is the same in each,
        because overlap is symmetric -- which the module is separately required
        to be, so this is not the symmetry test wearing a disguise: it is what
        makes an ASYMMETRIC rival visible at all."""
        return SCOPE_PAIRS + tuple(
            (right, left, expected, reason)
            for left, right, expected, reason in SCOPE_PAIRS)

    def answers(self, rule) -> tuple:
        return tuple(rule(left, right) for left, right, _, _ in self.rows())

    def truth(self) -> tuple:
        return tuple(expected for _, _, expected, _ in self.rows())

    def assert_refuted(self, name, rule):
        mine, theirs = self.truth(), self.answers(rule)
        self.assertIsNone(
            None if mine != theirs else name,
            f"{name} agrees with the real rule on every row of SCOPE_PAIRS; "
            "the corpus no longer discriminates")
        rows = self.rows()
        witnesses = [rows[index] for index in range(len(mine))
                     if mine[index] != theirs[index]]
        self.assertTrue(witnesses)
        return witnesses

    def test_the_real_rule_answers_the_table(self):
        self.assertEqual(
            self.answers(state.scopes_overlap), self.truth())

    def test_plain_equality_is_refuted_and_this_is_fault_f1(self):
        def equality(left, right):
            return scope_path(left) == scope_path(right)
        witnesses = self.assert_refuted("plain path equality", equality)
        self.assertIn(("tree:src", "file:src/a.py", True, "ancestor"), witnesses)
        for _, _, expected, reason in witnesses:
            self.assertTrue(expected)
            self.assertEqual(reason, "ancestor")

    def test_whole_scope_string_equality_is_refuted(self):
        witnesses = self.assert_refuted(
            "whole scope string equality", lambda left, right: left == right)
        self.assertIn(("tree:src", "file:src", True, "same-path"), witnesses)

    def test_a_string_prefix_containment_is_refuted(self):
        def claims(path, kind, scope):
            return path == scope or (kind == "tree" and path.startswith(scope))

        def prefix(left, right):
            return (claims(scope_path(right), scope_type(left), scope_path(left))
                    or claims(scope_path(left), scope_type(right),
                              scope_path(right)))
        witnesses = self.assert_refuted("a startswith containment", prefix)
        self.assertIn(("tree:src", "file:srcx/a.py", False, "prefix"), witnesses)
        for _, _, expected, reason in witnesses:
            self.assertFalse(expected)
            self.assertEqual(reason, "prefix")

    def test_a_type_blind_ancestry_is_refuted(self):
        def blind(left, right):
            one, two = scope_path(left), scope_path(right)
            return one == two or is_ancestor(one, two) or is_ancestor(two, one)
        witnesses = self.assert_refuted("type-blind ancestry", blind)
        self.assertIn(("file:src/a.py", "tree:src/a.py/deep", False,
                       "file-ancestor"), witnesses)

    def test_a_tree_that_does_not_contain_itself_is_refuted(self):
        """`_within_scope`'s asymmetry, transplanted. This is the rival a Task
        3 written by calling `_within_scope` would actually be."""
        def claims(path, kind, scope):
            return ((kind == "file" and path == scope)
                    or (kind == "tree"
                        and PurePosixPath(scope) in PurePosixPath(path).parents))

        def transplanted(left, right):
            return (claims(scope_path(right), scope_type(left), scope_path(left))
                    or claims(scope_path(left), scope_type(right),
                              scope_path(right)))
        witnesses = self.assert_refuted("_within_scope's predicate",
                                        transplanted)
        self.assertIn(("tree:src", "tree:src", True, "same-path"), witnesses)

    def test_a_one_armed_tree_branch_is_refuted(self):
        """F1's omission, moved one cell over: a `tree:` contains a `tree:`
        below it only when the SHALLOWER one is written first. It is a
        type-pair case analysis with one arm missing, which is the shape the
        real fault had, and it survived this class until every rival was run
        reversed -- it agrees with the real rule on all 35 forward rows,
        because `SCOPE_PAIRS` spells its `tree`/`tree` ancestor pair outer
        first. `assert_refuted`'s own "the corpus no longer discriminates"
        alarm fired, and nothing caught it.
        """
        def one_armed(left, right):
            kind_a, kind_b = scope_type(left), scope_type(right)
            path_a, path_b = scope_path(left), scope_path(right)
            if path_a == path_b:
                return True
            if kind_a == "tree" and is_ancestor(path_a, path_b):
                return True
            return (kind_b == "tree" and kind_a != "tree"
                    and is_ancestor(path_b, path_a))
        witnesses = self.assert_refuted("a one-armed tree/tree branch",
                                        one_armed)
        self.assertIn(("tree:src/deep/nested", "tree:src", True, "ancestor"),
                      witnesses)
        for _, _, expected, reason in witnesses:
            self.assertTrue(expected)
            self.assertEqual(reason, "ancestor")

    def test_the_corpus_pins_every_type_pair_cell(self):
        """WHY THE REVERSED HALF IS ENOUGH, stated as a count rather than as a
        hope.

        A "type-pair case analysis" -- the family the real fault belonged to --
        is exactly a boolean function of `(type_a, type_b, relation)`, where
        the relation is one of equal / a contains b / b contains a / neither.
        That is 16 cells, so 2**16 such rivals. A rival is refuted by this
        class iff it differs from the real rule on a cell some row exercises,
        so the number that SURVIVE is `2 ** (uncovered cells) - 1`: every
        assignment that is free on the uncovered cells and forced on the rest,
        minus the real rule itself.

        Forward only, that was 2**4 - 1 = 15 survivors. With both orders every
        cell is covered and the count is 2**0 - 1 = 0. The assertions below
        measure the covered set and the agreement, which is what the arithmetic
        rests on; `RivalRuleTests`' named rivals are then the readable
        witnesses rather than the whole argument.
        """
        def relation(one, two):
            if PurePosixPath(one) == PurePosixPath(two):
                return "eq"
            if is_ancestor(one, two):
                return "a<b"
            if is_ancestor(two, one):
                return "b<a"
            return "none"

        def cell(left, right):
            return (scope_type(left), scope_type(right),
                    relation(scope_path(left), scope_path(right)))

        def real(one_cell):
            kind_a, kind_b, rel = one_cell
            return (rel == "eq"
                    or (rel == "a<b" and kind_a == "tree")
                    or (rel == "b<a" and kind_b == "tree"))

        every_cell = {(kind_a, kind_b, rel)
                      for kind_a in ("file", "tree")
                      for kind_b in ("file", "tree")
                      for rel in ("eq", "a<b", "b<a", "none")}
        self.assertEqual(len(every_cell), 16)

        forward = {cell(left, right) for left, right, _, _ in SCOPE_PAIRS}
        self.assertEqual(len(forward), 12)
        self.assertEqual(
            sorted(every_cell - forward),
            [("file", "file", "b<a"), ("file", "tree", "eq"),
             ("tree", "file", "b<a"), ("tree", "tree", "b<a")])

        covered = {cell(left, right) for left, right, _, _ in self.rows()}
        self.assertEqual(covered, every_cell)

        #: Every row agrees with the cell model, so a row really does constrain
        #: its cell -- otherwise "covered" would mean nothing. A cell carrying
        #: two different expected answers would make the corpus contradictory
        #: and is caught here rather than by an arbitrary rival.
        answer_for = {}
        for left, right, expected, _ in self.rows():
            here = cell(left, right)
            self.assertIs(real(here), expected, (left, right))
            self.assertIs(answer_for.setdefault(here, expected), expected)

        survivors = 2 ** len(every_cell - covered) - 1
        self.assertEqual(survivors, 0)

    def test_always_true_and_always_false_are_both_refuted(self):
        """The corpus has both answers in it, which a list of conflicts alone
        would not."""
        self.assert_refuted("always True", lambda left, right: True)
        self.assert_refuted("always False", lambda left, right: False)


class ScopeClaimedSetTests(unittest.TestCase):
    """The DERIVED rule, checked against a generated corpus rather than a list.

    `scopes_overlap` claims to answer "do these two scopes claim a common
    repository path". That claim has a witness form, and both directions of it
    are checked here over a cross product nobody hand-wrote:

    * COMPLETENESS -- if some path is claimed by both scopes, they overlap.
      Plain equality fails this at (`tree:src`, `file:src/a.py`, `src/a.py`)
      without anybody having had to think of that pair.
    * SOUNDNESS -- if they overlap, one of the two SCOPE ROOTS is a path both
      claim. A rule that said True for two genuinely disjoint scopes has to
      produce a witness and cannot.

    THE WITNESS SETS ARE COMPUTED BY `claims`, NOT BY `_path_in_scope`. This
    class asked the module for its own witnesses until P04 Task 3's review
    measured what that was worth: `_path_in_scope` is `_scope_claims` with a
    `_safe_relative` in front of it, and `scopes_overlap` is `_scope_claims`
    twice, so under a mutation to that one predicate both sides of the
    comparison moved together -- 40 shared-witness pairs, zero logical
    contradictions, and every kill coming from `assertGreater(checked, 60)`, a
    coverage counter rather than the witness logic. Worse,
    `_path_in_scope(scope_path(x), x)` is `True` by construction, so the
    soundness assertion reduced algebraically to the definition of
    `scopes_overlap` and no implementation written in terms of `_scope_claims`
    could fail it. `claims` is twelve lines of segment arithmetic that import
    nothing from the module, so the two sides can now disagree -- which is the
    only state in which an oracle has said anything.
    """

    ROOTS = ("src", "srcx", "src/pkg", "src/pkgx", "docs", "docsx",
             "docs/api", "a/b/c", "a/b", "a")
    SCOPES = tuple(f"{kind}:{root}"
                   for root in ROOTS for kind in state._WRITE_SCOPE_TYPES)
    #: The witness corpus: every root, every root's children and grandchildren,
    #: and a sibling whose name is a string prefix of one of them.
    PATHS = tuple(dict.fromkeys(
        list(ROOTS)
        + [f"{root}/a.py" for root in ROOTS]
        + [f"{root}/deep/nested/a.py" for root in ROOTS]
        + [f"{root}x/a.py" for root in ROOTS]))

    def test_the_corpus_is_big_enough_to_be_worth_running(self):
        """40 spellings collapse to 37 paths, and the three collisions are the
        point rather than an accident: `srcx/a.py` is reached both as the root
        `srcx` and as the string-prefix sibling of `src`, so the corpus
        contains the prefix trap under two different descriptions."""
        self.assertEqual(len(self.SCOPES), 20)
        self.assertEqual(len(self.PATHS), 37)
        for collision in ("srcx/a.py", "docsx/a.py", "src/pkgx/a.py"):
            self.assertIn(collision, self.PATHS)

    def test_the_oracle_is_not_the_module_wearing_a_hat(self):
        """`claims` has to be checked against something before it can check
        anything, and the something is the hand-written reason table -- which
        was drawn up before either was written and whose rows carry their
        reasons. If the oracle agreed with `_scope_claims` because it WAS
        `_scope_claims`, this would still pass; what makes it evidence is that
        `claims` never calls the module, so the two agreeing is two independent
        derivations of one rule meeting.
        """
        for left, right, expected, reason in SCOPE_PAIRS:
            with self.subTest(left=left, right=right, reason=reason):
                by_oracle = (scope_claims_path(left, scope_path(right))
                             or scope_claims_path(right, scope_path(left)))
                self.assertIs(by_oracle, expected)

    def test_path_in_scope_answers_the_oracle_over_the_whole_corpus(self):
        """The witness form, pinned against the independent oracle rather than
        against itself. Every scope against every path: 20 x 37 = 740 answers,
        none of them hand-written."""
        checked = 0
        for scope, path in itertools.product(self.SCOPES, self.PATHS):
            checked += 1
            with self.subTest(scope=scope, path=path):
                self.assertIs(state._path_in_scope(path, scope),
                              scope_claims_path(scope, path))
        self.assertEqual(checked, 740)

    def test_a_path_claimed_by_both_scopes_forces_an_overlap(self):
        checked = 0
        for left, right in itertools.product(self.SCOPES, repeat=2):
            shared = [path for path in self.PATHS
                      if scope_claims_path(left, path)
                      and scope_claims_path(right, path)]
            if not shared:
                continue
            checked += 1
            with self.subTest(left=left, right=right, witness=shared[0]):
                self.assertIs(state.scopes_overlap(left, right), True)
        self.assertGreater(checked, 60)

    def test_an_overlap_always_names_one_of_the_two_roots_as_its_witness(self):
        checked = 0
        for left, right in itertools.product(self.SCOPES, repeat=2):
            if not state.scopes_overlap(left, right):
                continue
            checked += 1
            with self.subTest(left=left, right=right):
                self.assertTrue(
                    (scope_claims_path(right, scope_path(left))
                     and scope_claims_path(left, scope_path(left)))
                    or (scope_claims_path(left, scope_path(right))
                        and scope_claims_path(right, scope_path(right))),
                    "an overlap with no witness path is a rule that answered "
                    "True about nothing")
        self.assertGreater(checked, 60)

    def test_no_pair_is_disjoint_and_sharing_a_path_at_the_same_time(self):
        """The two directions above, joined into a BICONDITIONAL: over the
        whole cross product the module's boolean and the oracle's witness
        search agree exactly, in both directions.

        The `if shared:` this used to carry made it the completeness half a
        second time -- a rule that answered True for a pair sharing nothing
        walked straight through it. The corpus makes the other half exact:
        every scope root is in PATHS, so if two scopes overlap at all they
        overlap at a root the search examines, and "no shared path here" really
        does mean "disjoint".
        """
        for left, right in itertools.product(self.SCOPES, repeat=2):
            shared = any(scope_claims_path(left, path)
                         and scope_claims_path(right, path)
                         for path in self.PATHS)
            with self.subTest(left=left, right=right):
                self.assertIs(state.scopes_overlap(left, right), shared)

    def test_overlap_is_reflexive_and_symmetric_over_the_whole_corpus(self):
        for scope in self.SCOPES:
            with self.subTest(scope=scope):
                self.assertIs(state.scopes_overlap(scope, scope), True)
        for left, right in itertools.product(self.SCOPES, repeat=2):
            with self.subTest(left=left, right=right):
                self.assertIs(state.scopes_overlap(left, right),
                              state.scopes_overlap(right, left))

    def test_a_file_scope_conflicts_with_exactly_one_other_file_scope(self):
        """Derived rather than listed: across the generated corpus, a `file:`
        scope's conflicts with other `file:` scopes are exactly itself, because
        two one-path sets intersect only when the paths are equal."""
        files = [scope for scope in self.SCOPES if scope_type(scope) == "file"]
        for left in files:
            with self.subTest(left=left):
                self.assertEqual(
                    [right for right in files
                     if state.scopes_overlap(left, right)],
                    [left])

    def test_a_tree_scope_conflicts_with_strictly_more_than_itself(self):
        """The half a plain equality rule cannot produce: for a root that has
        descendants in the corpus, `tree:` conflicts with scopes it is not
        equal to."""
        trees = [scope for scope in self.SCOPES if scope_type(scope) == "tree"]
        widened = [scope for scope in trees
                   if len([other for other in self.SCOPES
                           if state.scopes_overlap(scope, other)]) > 2]
        self.assertGreaterEqual(len(widened), 6)


class WithinScopeIsNotOverlapTests(unittest.TestCase):
    """The measured divergence, pinned so the reuse stays refused.

    `_within_scope` is the containment predicate P04 Task 2 wrote for OUTPUTS,
    and it deliberately says a `tree:` scope does not contain itself. Reusing
    it here would make two tasks that both declare `tree:docs` look disjoint --
    which is F1 arriving from the one direction that looks like good reuse.
    """

    def test_within_scope_still_refuses_a_trees_own_root(self):
        self.assertIs(
            state._within_scope(PurePosixPath("docs"),
                                [("tree", PurePosixPath("docs"))]),
            False)

    def test_overlap_accepts_the_very_path_within_scope_refuses(self):
        self.assertIs(state.scopes_overlap("tree:docs", "tree:docs"), True)
        self.assertIs(state.scopes_overlap("tree:docs", "file:docs"), True)
        self.assertIs(state._path_in_scope("docs", "tree:docs"), True)

    def test_the_two_agree_everywhere_except_a_trees_own_root(self):
        """The divergence is exactly one row wide, and that is the point: the
        SHAPE is inherited, the predicate is not."""
        paths = ("docs", "docs/a.md", "docs/deep/a.md", "docsx/a.md", "src")
        scopes = ("tree:docs", "file:docs", "tree:docs/deep")
        for path, scope in itertools.product(paths, scopes):
            kind, root = scope_type(scope), PurePosixPath(scope_path(scope))
            within = state._within_scope(PurePosixPath(path), [(kind, root)])
            claimed = state._path_in_scope(path, scope)
            with self.subTest(path=path, scope=scope):
                if kind == "tree" and PurePosixPath(path) == root:
                    self.assertTrue(claimed and not within)
                else:
                    self.assertIs(claimed, within)


class ScopeSetOverlapTests(unittest.TestCase):
    """`_scope_sets_overlap`: the form a reservation actually asks in."""

    def test_one_conflicting_pair_anywhere_is_a_conflict(self):
        for left, right in (
                (("file:src/a.py",), ("file:src/a.py",)),
                (("tree:docs", "file:src/a.py"), ("file:docs/index.md",)),
                (("file:src/a.py", "file:src/b.py"), ("tree:src",)),
                (("file:z/1", "file:z/2", "tree:docs"),
                 ("file:y/1", "file:y/2", "file:docs/deep/a.md"))):
            with self.subTest(left=left, right=right):
                self.assertIs(state._scope_sets_overlap(left, right), True)
                self.assertIs(state._scope_sets_overlap(right, left), True)

    def test_disjoint_sets_are_disjoint(self):
        for left, right in (
                (("file:src/a.py", "tree:docs"), ("file:src/b.py", "tree:reports")),
                (("tree:src",), ("tree:srcx", "file:srcx/a.py")),
                (("tree:a/b",), ("tree:a/bc", "file:a/bc/d.py"))):
            with self.subTest(left=left, right=right):
                self.assertIs(state._scope_sets_overlap(left, right), False)
                self.assertIs(state._scope_sets_overlap(right, left), False)

    def test_an_empty_right_is_nothing_in_flight_and_conflicts_with_nothing(self):
        """The ordinary first dispatch of a run: the asking task has scopes,
        nothing is running yet, and `False` is the TRUE answer rather than an
        absence of information."""
        self.assertIs(state._scope_sets_overlap(("tree:src",), ()), False)
        self.assertIs(state._scope_sets_overlap(("tree:src",), []), False)
        self.assertIs(
            state._scope_sets_overlap(("tree:src", "file:docs/a.md"), ()), False)

    def test_an_empty_left_is_refused_because_it_is_a_lookup_that_missed(self):
        """The asymmetry, and the reason for it. The left is "these are MY
        scopes", and `_parse_write_scope` already refuses a task that declares
        none -- so an empty left never came from a plan. It came from a `-`
        cell, a task id that did not match, or a split that yielded nothing,
        and answering `False` would report that a task whose own scopes could
        not be found collides with nothing. That is the same false `False` the
        bare-string screen exists to refuse, and the two were treated
        inconsistently until this refusal was added: the bare string `""` was
        rejected while `()` -- which reaches the same zero comparisons by a
        shorter route -- was pinned as correct.
        """
        for right in ((), [], ("tree:src",), ["tree:src", "file:docs/a.md"]):
            for left in ((), []):
                with self.subTest(left=left, right=right):
                    with self.assertRaises(state.PlanMetadataError) as caught:
                        state._scope_sets_overlap(left, right)
                    self.assertIn("left", str(caught.exception))

    def test_zero_comparisons_never_answer_false(self):
        """The property the two tests above are two halves of, stated once: the
        function returns `False` only after it has actually compared a pair.
        Every input that would reach the nested walk with nothing to walk is
        refused instead -- a bare string (iterable of characters, never a
        scope), a one-shot iterator, and now an empty left.
        """
        for left, right in (((), ("tree:src",)),
                            ([], []),
                            ("tree:src", ("tree:src",)),
                            (iter(("tree:src",)), ("tree:src",))):
            with self.subTest(left=left, right=right):
                with self.assertRaises(state.PlanMetadataError):
                    state._scope_sets_overlap(left, right)
        #: and the one shape that legitimately compares nothing keeps its
        #: answer, because "nothing is in flight" is information and not a
        #: failure to look.
        self.assertIs(state._scope_sets_overlap(("tree:src",), ()), False)

    def test_a_list_is_accepted_as_well_as_a_tuple(self):
        self.assertIs(
            state._scope_sets_overlap(["tree:src"], ["file:src/a.py"]), True)

    def test_a_bare_string_is_refused_rather_than_iterated(self):
        """The failure is not that the characters fail to parse -- it is that
        with an empty opposing set they are never reached, and the answer is a
        confident False that dispatches two implementers onto one file."""
        for left, right in (("file:src/a.py", ("file:src/a.py",)),
                            (("file:src/a.py",), "file:src/a.py"),
                            ("file:src/a.py", ()),
                            ((), "file:src/a.py")):
            with self.subTest(left=left, right=right):
                with self.assertRaises(state.PlanMetadataError):
                    state._scope_sets_overlap(left, right)

    def test_a_one_shot_iterator_is_refused_rather_than_silently_exhausted(self):
        """A generator would be consumed by the first row of the nested walk,
        so every later comparison would see an empty set -- a false False that
        only appears when the left-hand set has more than one member."""
        with self.assertRaises(state.PlanMetadataError):
            state._scope_sets_overlap(("file:a", "tree:docs"),
                                      iter(("file:docs/index.md",)))

    def test_every_scope_is_parsed_even_when_an_earlier_pair_collides(self):
        """Short-circuiting the parse would make "is this list well formed"
        depend on which pair happened to collide first, so a run could adopt a
        scope list that the very same list rejects tomorrow. The first pair
        here conflicts; the malformed member is still refused."""
        for left, right in (
                (("file:src/a.py", "glob:src"), ("file:src/a.py",)),
                (("file:src/a.py",), ("file:src/a.py", "src/b.py")),
                (("file:src/a.py",), ("file:src/a.py", "file:../b"))):
            with self.subTest(left=left, right=right):
                with self.assertRaises(state.PlanMetadataError):
                    state._scope_sets_overlap(left, right)

    def test_a_set_member_that_is_two_scopes_is_refused(self):
        """A comma-separated FIELD is not a scope set member; it is the raw
        text a set is parsed out of. Accepting it would compare against the
        first member alone."""
        with self.assertRaises(state.PlanMetadataError):
            state._scope_sets_overlap(("file:src/a.py,tree:docs",),
                                      ("tree:docs",))


class ScopePartsTotalityTests(unittest.TestCase):
    """Every refusal is a `PlanMetadataError`, for every input, on both sides.

    A scope reaches these functions from a plan an agent wrote and from a
    tracker cell a previous run recorded. `TypeError`, `AttributeError` and
    `ValueError` all live outside `TrackerError`, so a controller wrapping this
    in `except TrackerError` would DIE on a bad scope rather than refuse it.
    """

    BAD_SCOPES = (
        None, 42, 4.5, True, b"file:src/a.py", ["file:src/a.py"],
        ("file:src/a.py",), {"file": "src/a.py"}, PurePosixPath("src/a.py"),
        "", " ", "\t", "none", "src/a.py", ":src/a.py", "file", "file:",
        "tree:", "FILE:src/a.py", "Tree:docs", "dir:docs", "glob:src/*.py",
        " file:src/a.py", "file:src/a.py ", "file:/etc/passwd", "file:../a",
        "file:a/../b", "file:src/./a", "file:a//b", "file:src/a/",
        "file:src/*.py", "file:src/[a].py", "file:a\\b",
        "file:src/a.py,tree:docs", "file:a,b.py", "file:src/a.py,",
    )

    def test_a_bad_scope_is_refused_on_either_side_of_the_comparison(self):
        for scope in self.BAD_SCOPES:
            with self.subTest(scope=repr(scope)):
                with self.assertRaises(state.PlanMetadataError):
                    state.scopes_overlap(scope, "file:src/a.py")
                with self.assertRaises(state.PlanMetadataError):
                    state.scopes_overlap("file:src/a.py", scope)
                with self.assertRaises(state.PlanMetadataError):
                    state._scope_parts(scope)

    def test_a_blank_scope_is_refused_by_this_screen_and_not_merely_downstream(self):
        """The `strip` half of `_text` pinned, because behaviour alone does not
        pin it.

        `""`, `" "` and `"\\t"` are all refused downstream anyway -- `""` as
        "has an empty member" out of the comma split, `" "` and `"\\t"` as
        "untyped" out of the partition -- so narrowing `_scope_parts`'s screen
        to `isinstance` survives the whole suite on refusals alone. What it
        loses is the DIAGNOSIS: a blank tracker cell would be reported as a
        dangling comma or as a missing type, neither of which is what happened,
        and both of which send whoever reads the error looking for the wrong
        thing. So the message is the assertion here. The `isinstance` half is a
        different matter and is pinned by exception FAMILY above: without it a
        non-string leaves `TrackerError` altogether.
        """
        for scope in ("", " ", "\t", "\n", "  \t "):
            with self.subTest(scope=repr(scope)):
                with self.assertRaises(state.PlanMetadataError) as caught:
                    state._scope_parts(scope)
                self.assertIn("nonempty string", str(caught.exception))
                self.assertIn(repr(scope), str(caught.exception))

    def test_a_refusal_is_inside_the_modules_exception_family(self):
        for scope in self.BAD_SCOPES:
            with self.subTest(scope=repr(scope)):
                with self.assertRaises(state.TrackerError):
                    state._scope_parts(scope)

    def test_a_character_family_no_ascii_list_contains_is_refused(self):
        """Built with `chr` so the families read as CODE POINTS: NUL, a line
        feed and a tab out of `range(0x20)`; then 0x85, 0x2028 and 0x2029,
        three row breaks `str.splitlines` honours and no ASCII control list
        holds; then two lone surrogates the UTF-8 encoder refuses outright.
        The screen is `_safe_relative`'s, and it is asserted through this
        block's own door so a future short cut past that door is visible."""
        for code in (0x00, 0x0A, 0x0D, 0x09, 0x1F, 0x7F, 0x85, 0x2028, 0x2029,
                     0xD800, 0xDFFF):
            scope = "file:src/a" + chr(code) + "b.py"
            with self.subTest(code=hex(code)):
                with self.assertRaises(state.PlanMetadataError):
                    state.scopes_overlap(scope, "file:src/a.py")
                with self.assertRaises(state.PlanMetadataError):
                    state._path_in_scope("src/a.py", scope)

    def test_the_empty_and_root_spellings_are_refused_rather_than_universal(self):
        """`file:` and `tree:` have no path at all, and `tree:/` and `tree:.`
        are the two ways of spelling "the repository root" -- a scope that
        would conflict with EVERY other scope and silence the whole algebra."""
        for scope in ("file:", "tree:", "file:/", "tree:/", "file:.", "tree:.",
                      "tree:..", "file: "):
            with self.subTest(scope=scope):
                with self.assertRaises(state.PlanMetadataError):
                    state.scopes_overlap(scope, "file:src/a.py")

    def test_a_multi_member_field_is_refused_and_says_how_many_it_found(self):
        with self.assertRaises(state.PlanMetadataError) as caught:
            state._scope_parts("file:src/a.py,tree:docs")
        self.assertIn("2 write scopes", str(caught.exception))

    def test_the_zero_member_half_of_the_arity_check_is_unreachable(self):
        """`!= 1` states the rule; only the `> 1` half can be spelled, because
        `_parse_write_scope` already refuses an empty list and `none` with it.
        Both closures are asserted so that removing either one is visible here
        rather than in a scope that compares against nothing."""
        with self.assertRaises(state.PlanMetadataError) as empty:
            state._parse_write_scope("none")
        self.assertIn("at least one write scope", str(empty.exception))
        with self.assertRaises(state.PlanMetadataError):
            state._parse_write_scope("")
        with self.assertRaises(state.PlanMetadataError) as through:
            state._scope_parts("none")
        self.assertIn("at least one write scope", str(through.exception))

    def test_the_vocabulary_is_p02s_tuple_and_not_a_second_copy(self):
        """A re-typed `{"file", "tree"}` inside this block would be a second
        statement of the scope grammar that can drift from the plan parser's,
        and the two disagreeing is a scope the plan accepts and the reservation
        algebra refuses -- or the other way round, which is worse.

        PINNED BEHAVIOURALLY RATHER THAN BY GREPPING THE SOURCE. A textual
        assertion cannot tell a re-typed literal from the same literal quoted
        in a docstring, and it is satisfied by a copy spelled `["file",
        "tree"]`. Rebinding the module's tuple is the measurement: if this
        block reads it, the vocabulary moves with it; if it holds its own copy,
        `tree:` stays accepted here after the module stopped knowing the word.
        """
        self.assertEqual(state._WRITE_SCOPE_TYPES, ("file", "tree"))
        original = state._WRITE_SCOPE_TYPES
        try:
            state._WRITE_SCOPE_TYPES = ("file", "branch")
            with self.assertRaises(state.PlanMetadataError):
                state._scope_parts("tree:docs")
            with self.assertRaises(state.PlanMetadataError):
                state.scopes_overlap("tree:docs", "file:docs/a.md")
            self.assertEqual(state._scope_parts("branch:docs"),
                             ("branch", PurePosixPath("docs")))
            #: And the CONTAINMENT half moves with it too: index 1 of the tuple
            #: is what `_scope_claims` calls the subtree type, so the renamed
            #: word inherits the subtree behaviour rather than losing it.
            self.assertIs(
                state.scopes_overlap("branch:docs", "file:docs/a.md"), True)
            #: AND THE MODULE'S OTHER READER OF THE VOCABULARY MOVES TOO.
            #: `_within_scope` (P04 Task 2) held its own `"file"` and `"tree"`
            #: until this assertion was added, so the module really did carry
            #: two statements of the grammar: after the rebind above it went on
            #: answering about `tree:` -- a type the plan parser had stopped
            #: accepting -- and answered NOTHING about `branch:`, which is the
            #: fail-open direction. Every declared output would then have
            #: fallen outside every declared scope.
            self.assertIs(
                state._within_scope(PurePosixPath("docs/a.md"),
                                    [("branch", PurePosixPath("docs"))]),
                True)
            self.assertIs(
                state._within_scope(PurePosixPath("docs/a.md"),
                                    [("tree", PurePosixPath("docs"))]),
                False)
        finally:
            state._WRITE_SCOPE_TYPES = original
        self.assertEqual(state._WRITE_SCOPE_TYPES, ("file", "tree"))
        self.assertIs(state.scopes_overlap("tree:docs", "file:docs/a.md"), True)
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        self.assertEqual(source.count('_WRITE_SCOPE_TYPES = ("file", "tree")'), 1)

    def test_the_algebra_still_needs_no_regex_engine(self):
        """F1's fix is a path predicate, not a pattern. Two of P04's briefs
        reached for `re.compile`; the allowlist is twelve and `re` is not in
        it."""
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        self.assertNotIn("re.compile(", source)
        self.assertIsNone(sys.modules["pipeline_auto_state"].__dict__.get("re"))


class PathInScopeTests(unittest.TestCase):
    """The witness predicate on its own, including the families that only show
    up when a path is compared against a scope rather than a scope against a
    scope."""

    def test_a_path_is_claimed_by_its_own_tree_and_every_ancestor_tree(self):
        path = "a/b/c/d.py"
        for root in ("a", "a/b", "a/b/c"):
            with self.subTest(root=root):
                self.assertIs(state._path_in_scope(path, f"tree:{root}"), True)
                self.assertIs(state._path_in_scope(path, f"file:{root}"), False)
        self.assertIs(state._path_in_scope(path, f"file:{path}"), True)
        self.assertIs(state._path_in_scope(path, f"tree:{path}"), True)

    def test_a_sibling_whose_name_is_a_prefix_is_not_claimed(self):
        for path, root in (("srcx/a.py", "src"), ("docsx/a.md", "docs"),
                           (".github/ci.yml", ".git"), ("v10/a.py", "v1"),
                           ("a/bc/d.py", "a/b"), ("a-b-c/x.py", "a-b")):
            with self.subTest(path=path, root=root):
                self.assertIs(state._path_in_scope(path, f"tree:{root}"), False)
                self.assertTrue(path.startswith(root))

    def test_the_path_side_goes_through_the_same_bar_as_the_scope_side(self):
        for path in (None, 42, ["src/a.py"], PurePosixPath("src/a.py"), "",
                     "/etc/passwd", "../a", "a/../b", "src/./a", "a//b",
                     "src/a/", "src/*.py", "a\\b", " src/a.py", "src/a.py "):
            with self.subTest(path=repr(path)):
                with self.assertRaises(state.PlanMetadataError):
                    state._path_in_scope(path, "tree:src")

    def test_a_deeply_nested_path_is_claimed_by_its_top_level_tree(self):
        """`.parents` is walked, not a fixed depth: 40 segments deep is still
        inside `tree:a`."""
        path = "a/" + "/".join(f"s{index}" for index in range(39)) + "/z.py"
        self.assertEqual(len(PurePosixPath(path).parts), 41)
        self.assertIs(state._path_in_scope(path, "tree:a"), True)
        self.assertIs(state._path_in_scope(path, "tree:ax"), False)
        self.assertIs(state._path_in_scope(path, "file:a"), False)
        self.assertIs(state.scopes_overlap("tree:a", f"file:{path}"), True)

    def test_a_path_is_never_claimed_by_a_scope_in_a_different_case(self):
        self.assertIs(state._path_in_scope("src/a.py", "tree:SRC"), False)
        self.assertIs(state._path_in_scope("SRC/a.py", "tree:src"), False)
        self.assertIs(state._path_in_scope("src/A.py", "file:src/a.py"), False)

    def test_the_answer_is_a_bool(self):
        self.assertIsInstance(state._path_in_scope("src/a.py", "tree:src"), bool)
        self.assertIsInstance(state._path_in_scope("x/a.py", "tree:src"), bool)


if __name__ == "__main__":
    unittest.main()
