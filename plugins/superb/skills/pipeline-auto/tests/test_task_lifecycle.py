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

import ast
import contextlib
import errno
import hashlib
import inspect
import itertools
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

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

    def test_a_task_id_is_held_to_the_task_id_grammar_and_not_to_the_token(self):
        """THE RULING. A task id is written into a branch name and into the
        directory its results are published in, so it is held to ``_TASK_ID``
        -- ``_PATH_SEGMENT`` narrowed to what ``git check-ref-format``
        accepts -- and not to ``_TOKEN``.

        This test used to assert the opposite, and the case it asserted was a
        DEADLOCK: ``_TOKEN`` admits ``p04/t2``, ``reserve_task`` accepted it,
        so the slot was held against the ``worker_limit - 3`` cap -- and then
        ``publish_worker_result`` refused the id and git refuses the branch,
        so nothing could ever release it. The refusal belongs here, at import,
        where nothing is reserved yet.
        """
        for task_id in ("T1", "T-1", "T.1", "T_1", "a.b.c", "a" * 64,
                        "T1.locker"):
            with self.subTest(accepted=task_id):
                metadata = self.parse(task_block(task_id), name="id.md")
                self.assertEqual(metadata["tasks"][0]["id"], task_id)
        for task_id in ("p04/t2", "a@b", "a:b", "a+b", "T1.", "a..b",
                        "T1.lock", "a" * 65):
            with self.subTest(refused=task_id):
                exception = self._expect_rejection(
                    task_block(task_id), name="id-bad.md")
                self.assertIn("invalid task id", str(exception))

    def test_a_batch_still_carries_every_character_the_token_grammar_allows(self):
        """The guard on ``_TOKEN`` ITSELF, moved to the field that still asks
        for it. ``@``, ``:``, ``+``, ``/``, ``.`` and ``-`` are all inside
        P02's grammar, so a P04 block that narrowed the token to
        ``[A-Za-z0-9-]`` fails here -- and narrowing ``_TOKEN`` is exactly
        what the task-id ruling forbids, because it is shared with
        ``target_branch``, ``phase_id``, ``axis``, ``reviewer`` and ``dep``,
        several of which legitimately carry ``/``."""
        for batch in ("b1", "p04/b2", "a@b", "a:b", "a+b", "b.1", "b-1",
                      "b" * 65):
            with self.subTest(batch=batch):
                metadata = self.parse(
                    task_block("T1", batch=batch), name="batch.md")
                self.assertEqual(metadata["tasks"][0]["batch"], batch)

    def test_a_dependency_is_held_to_the_task_id_grammar_too(self):
        """A dependency NAMES a task, so it is the same kind of name. Held to
        ``_TOKEN`` it would be a second grammar for one id, and a plan could
        declare a dependency on an id no task in it could legally carry."""
        exception = self._expect_rejection(
            task_block("T1", deps="p04/t2", order=1)
            + task_block("T2", order=2, write_scope="file:src/b.py"),
            name="dep-segment.md")
        self.assertIn("invalid task dependency id", str(exception))
        self.assertNotIn("never declared", str(exception))

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


# --------------------------------------------------------------------------
# Task 4 tests -- fault F5
#
# F5 is "a quorum-raising result with no question record reference". The
# brief's own test for it is one `assertRaises` per quorum status over one
# fixture, which is a rejection-only assertion over two rows: it cannot tell
# the F5 rule from any other screen that happens to refuse the same fixture,
# and it says nothing at all about the 38 other (status, routing-field)
# combinations the vocabulary admits. `RoutingAgreementTests` replaces it with
# the whole cross product answered against a table oracle, and
# `QuestionRecordDiagnosisTests` asserts the DIAGNOSIS rather than the refusal.
# --------------------------------------------------------------------------

DIGEST = "a" * 64
COMMIT = "b" * 40
QUESTION_RECORD = f"docs/superpowers/runs/run-1/questions/q1.md#sha256={DIGEST}"
EVIDENCE_REF = f"docs/superpowers/runs/run-1/evidence/T1.md#sha256={DIGEST}"

#: THE ROUTING REVERSAL, WRITTEN DOWN A SECOND TIME AS LITERALS. `_status_route`
#: derives it from three tuples; an oracle that asks `_status_route` which route
#: a status takes is asking the implementation under test, so a mutation inside
#: the mapping moves both sides of the comparison together and the cross product
#: says nothing. Measured: swapping `(QUORUM_STATUSES, _ROUTE_QUORUM)` for
#: `(QUORUM_STATUSES, _ROUTE_COMPLETION)` -- which RESTORES `superb:pipeline`'s
#: semantics and is the whole point of this phase -- was killed by ten tests and
#: by neither cross-product test. The five entries are spelled by hand; the
#: totality assertion below is what stops a sixth status from being routed by
#: this table's silence.
STATUS_ROUTE = {
    "DONE": state._ROUTE_COMPLETION,
    "DONE_WITH_CONCERNS": state._ROUTE_COMPLETION,
    "NEEDS_CONTEXT": state._ROUTE_QUORUM,
    "PLAN_CONFLICT": state._ROUTE_QUORUM,
    "BLOCKED": state._ROUTE_HALT,
}

#: P06's reviewer-independence scan, COPIED FROM `phase-06-master-gate.md` rather
#: than re-derived from what P04 happens to render. The master plan pins
#: `- **Owner:** <id>` as a binding cross-phase contract: P06 walks the run's
#: results tree with this pattern and refuses to hand a task to anyone who ever
#: owned an attempt at it. If P04's renderer and this pattern disagree, the scan
#: harvests the empty set and the check passes vacuously -- the fail-open
#: direction of the property P06 names.
P06_OWNER_LINE = re.compile(r"^-\s+\*\*Owner:\*\*\s*(\S+)\s*$", re.MULTILINE)


def worker_result(**overrides) -> dict:
    result = {
        "run_id": "run-1",
        "task_id": "T1",
        "attempt": 1,
        "owner": "impl-1",
        "kind": "source",
        "status": "DONE",
        "source_ref": COMMIT,
        "commits": (COMMIT,),
        "artifacts": (),
        "tests": ("python3 -m unittest -k T1",),
        "evidence": (EVIDENCE_REF,),
        "concerns": "-",
        "question_record": "-",
        "blocking_reason": "-",
        "checkpoints": (),
    }
    result.update(overrides)
    return result


def quorum_result(status: str, **overrides) -> dict:
    """A quorum-raising result, with the caller's overrides applied LAST.

    THE BRIEF SPELLED THIS AS ``worker_result(question_record=..., **overrides)``
    AND ITS OWN F5 TEST COULD NOT RUN. ``quorum_result(status,
    question_record="-")`` -- the flagship
    ``test_quorum_status_without_a_question_record_is_rejected`` -- raises
    ``TypeError: got multiple values for keyword argument 'question_record'``
    from the HELPER, before the codec is ever called. ``assertRaises`` is
    looking for ``TrackerValidationError``, so the test errors rather than
    asserting anything, and the one field F5 is about is the one field the
    helper could not override. Merging into a dict makes the override win,
    which is what every caller here means.
    """
    return worker_result(**{
        "status": status, "source_ref": "-", "commits": (), "evidence": (),
        "question_record": QUESTION_RECORD, **overrides,
    })


def artifact_result(**overrides) -> dict:
    """An artifact-kind completion. Overrides last, for the reason above:
    ``artifact_result(artifacts=())`` is the whole point of one of the tests."""
    return worker_result(**{
        "kind": "artifact", "source_ref": "-", "commits": (), "tests": (),
        "artifacts": ("docs/superpowers/runs/run-1/brief.md",), **overrides,
    })


def rendered_lines(result: dict) -> list:
    return state.render_worker_result(result).splitlines()


def refuse(case, result: dict) -> str:
    """Render `result`, require a `TrackerValidationError`, return its text."""
    with case.assertRaises(state.TrackerValidationError) as caught:
        state.render_worker_result(result)
    return str(caught.exception)


class WorkerResultCodecTests(unittest.TestCase):
    """The brief's own thirteen, kept verbatim."""

    def test_round_trips(self):
        original = worker_result(checkpoints=(
            {"id": "c1", "status": "complete", "evidence": EVIDENCE_REF},
        ))
        text = state.render_worker_result(original)
        self.assertTrue(text.startswith(state.WORKER_RESULT_MARKER))
        self.assertEqual(state.parse_worker_result(text), original)

    def test_field_order_is_pinned_in_the_rendered_document(self):
        text = state.render_worker_result(worker_result())
        rendered = [
            line.split("|")[1].strip()
            for line in text.splitlines()
            if line.startswith("| ") and line.count("|") == 3
        ]
        self.assertEqual(
            [name for name in rendered if name in state.WORKER_RESULT_FIELDS],
            list(state.WORKER_RESULT_FIELDS),
        )

    def test_rejects_a_foreign_marker(self):
        text = state.render_worker_result(worker_result()).replace(
            state.WORKER_RESULT_MARKER, "<!-- pipeline-worker-result/v2 -->"
        )
        with self.assertRaises(state.TrackerValidationError):
            state.parse_worker_result(text)

    def test_rejects_reordered_fields(self):
        lines = state.render_worker_result(worker_result()).splitlines()
        index = next(i for i, line in enumerate(lines)
                     if line.startswith("| owner "))
        lines[index], lines[index - 1] = lines[index - 1], lines[index]
        with self.assertRaises(state.TrackerValidationError):
            state.parse_worker_result("\n".join(lines) + "\n")

    def test_quorum_status_without_a_question_record_is_rejected(self):
        """F5: a quorum-raising result missing its question record is rejected,
        exactly as a result with a missing owner is rejected."""
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(
                        quorum_result(status, question_record="-")
                    )

    def test_quorum_status_with_a_digest_bound_question_record_is_accepted(self):
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                result = quorum_result(status)
                self.assertEqual(
                    state.parse_worker_result(state.render_worker_result(result)),
                    result,
                )

    def test_quorum_question_record_must_be_digest_bound(self):
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(quorum_result(
                        status,
                        question_record="docs/superpowers/runs/run-1/questions/q1.md",
                    ))

    def test_quorum_status_may_not_also_carry_a_blocking_reason(self):
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(
                        quorum_result(status, blocking_reason="also blocked")
                    )

    def test_blocked_requires_a_blocking_reason_and_no_question_record(self):
        base = dict(source_ref="-", commits=(), evidence=())
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(
                worker_result(status="BLOCKED", blocking_reason="-", **base)
            )
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(worker_result(
                status="BLOCKED", blocking_reason="no staging credential",
                question_record=f"docs/q.md#sha256={DIGEST}", **base,
            ))
        accepted = worker_result(
            status="BLOCKED", blocking_reason="no staging credential", **base
        )
        self.assertEqual(
            state.parse_worker_result(state.render_worker_result(accepted)),
            accepted,
        )

    def test_completion_status_carries_neither_routing_field(self):
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(
                worker_result(question_record=f"docs/q.md#sha256={DIGEST}")
            )
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(worker_result(blocking_reason="why"))

    def test_status_vocabulary_is_exactly_five_values(self):
        self.assertEqual(state.WORKER_STATUSES, (
            "DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "PLAN_CONFLICT",
            "BLOCKED",
        ))
        self.assertEqual(state.QUORUM_STATUSES,
                         ("NEEDS_CONTEXT", "PLAN_CONFLICT"))
        self.assertEqual(state.HALT_STATUSES, ("BLOCKED",))
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(worker_result(status="OK"))

    def test_rejects_unsafe_scalars(self):
        for override in ({"owner": "impl|1"}, {"concerns": "a|b"},
                         {"attempt": 0}, {"attempt": "1"}, {"kind": "binary"},
                         {"run_id": ""}, {"commits": ("short",)},
                         {"source_ref": "nope"}):
            with self.subTest(override=override):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(worker_result(**override))

    def test_template_matches_the_codec_fields(self):
        template = (
            Path(state.__file__).resolve().parents[1] / "templates"
            / "worker-result.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(template.startswith(state.WORKER_RESULT_MARKER))
        for field in state.WORKER_RESULT_FIELDS:
            with self.subTest(field=field):
                self.assertIn(f"| {field} | ", template)


class StatusPartitionTests(unittest.TestCase):
    """The three route tuples ARE the vocabulary, not a commentary on it."""

    def test_the_vocabulary_is_the_concatenation_of_the_three_routes(self):
        self.assertEqual(
            state.WORKER_STATUSES,
            state.COMPLETION_STATUSES + state.QUORUM_STATUSES
            + state.HALT_STATUSES,
        )

    def test_the_three_routes_are_pairwise_disjoint(self):
        groups = (state.COMPLETION_STATUSES, state.QUORUM_STATUSES,
                  state.HALT_STATUSES)
        for one, two in itertools.combinations(groups, 2):
            with self.subTest(one=one, two=two):
                self.assertEqual(set(one) & set(two), set())

    def test_status_route_is_total_over_the_vocabulary(self):
        """No default arm and no unrouted status. A sixth status that reached
        `WORKER_STATUSES` without reaching one of the three tuples would be a
        status the codec accepts and the controller cannot dispatch."""
        for status in state.WORKER_STATUSES:
            with self.subTest(status=status):
                self.assertIn(
                    state._status_route(status),
                    (state._ROUTE_COMPLETION, state._ROUTE_QUORUM,
                     state._ROUTE_HALT),
                )

    def test_the_route_of_every_status_is_the_one_the_table_names(self):
        """The literal half of the oracle, and the only place in this file that
        states the reversal without asking the code that implements it.

        `test_status_route_is_total_over_the_vocabulary` above says every status
        routes SOMEWHERE; this says WHICH, and the key-set assertion is what
        makes the pair total: a sixth status added to `WORKER_STATUSES` fails
        here rather than being routed by this table's silence."""
        self.assertEqual(sorted(STATUS_ROUTE), sorted(state.WORKER_STATUSES))
        for status, route in STATUS_ROUTE.items():
            with self.subTest(status=status):
                self.assertEqual(state._status_route(status), route)

    def test_every_status_has_at_least_one_renderable_result(self):
        """A vocabulary entry no document can carry is a lie in the template.
        Measured by CONSTRUCTION -- one body per route -- rather than asserted."""
        bodies = {
            state._ROUTE_COMPLETION: lambda status: worker_result(
                status=status,
                concerns="-" if status == "DONE" else "a rough edge"),
            state._ROUTE_QUORUM: quorum_result,
            state._ROUTE_HALT: lambda status: worker_result(
                status=status, source_ref="-", commits=(), evidence=(),
                blocking_reason="no staging credential"),
        }
        for status in state.WORKER_STATUSES:
            with self.subTest(status=status):
                result = bodies[STATUS_ROUTE[status]](status)
                self.assertEqual(
                    state.parse_worker_result(
                        state.render_worker_result(result)),
                    result,
                )

    def test_an_unrouted_status_is_refused_by_the_route_lookup_itself(self):
        for status in ("OK", "done", "", "BLOCKED ", None, ["DONE"], 3):
            with self.subTest(status=status):
                with self.assertRaises(state.TrackerValidationError):
                    state._status_route(status)


# --------------------------------------------------------------------------
# F5, answered over the whole cross product instead of one fixture.
# --------------------------------------------------------------------------

#: The routing half of a result, as the four states the two fields can be in.
#: This is the ORACLE and it is written as a table, not as a copy of the
#: implementation: a result's two routing cells say which route the body is on,
#: the status word says which route the status is on, and a document is legal
#: exactly when the two say the same thing. Every arm is spelled, including the
#: "both set" arm that belongs to no route at all.
def body_route(question_record: str, blocking_reason: str):
    named_question = question_record != "-"
    named_reason = blocking_reason != "-"
    if named_question and named_reason:
        return None                      # claims two routes; belongs to neither
    if named_question:
        return state._ROUTE_QUORUM
    if named_reason:
        return state._ROUTE_HALT
    return state._ROUTE_COMPLETION


ROUTING_CELLS = (
    ("-", "-"),
    (QUESTION_RECORD, "-"),
    ("-", "no staging credential"),
    (QUESTION_RECORD, "no staging credential"),
)


def routed_body(status: str, question_record: str, blocking_reason: str,
                kind: str = "source") -> dict:
    """A result whose COMPLETION material is always complete for its kind, so
    the only thing that can be wrong with it is the routing pair."""
    base = artifact_result() if kind == "artifact" else worker_result()
    base.update(status=status, question_record=question_record,
                blocking_reason=blocking_reason,
                concerns="a rough edge" if status == "DONE_WITH_CONCERNS"
                else "-")
    return base


class RoutingAgreementTests(unittest.TestCase):
    """The status word and the routing cells are two statements of one fact.

    This is what makes "DONE is evidence, not acceptance" mechanical rather
    than prose: no status is acted on for the strength of the word. Forty
    combinations -- five statuses, four routing pairs, two kinds -- are each
    answered against `body_route`, an independently written table. The brief
    asserted two of the forty.
    """

    def test_a_result_is_accepted_exactly_when_the_two_agree(self):
        checked = 0
        for status, (question_record, blocking_reason), kind in itertools.product(
            state.WORKER_STATUSES, ROUTING_CELLS, state.TASK_KINDS
        ):
            expected = (body_route(question_record, blocking_reason)
                        == STATUS_ROUTE[status])
            with self.subTest(status=status, question_record=question_record,
                              blocking_reason=blocking_reason, kind=kind):
                result = routed_body(status, question_record, blocking_reason,
                                     kind)
                try:
                    state.render_worker_result(result)
                    accepted = True
                except state.TrackerValidationError:
                    accepted = False
                self.assertEqual(accepted, expected)
                checked += 1
        self.assertEqual(checked, 40)

    def test_no_body_is_legal_under_two_statuses_from_different_routes(self):
        """The bodies of the three routes are disjoint, so a worker cannot
        relabel a result from one route to another and have it still render."""
        for (question_record, blocking_reason), kind in itertools.product(
            ROUTING_CELLS, state.TASK_KINDS
        ):
            accepting = set()
            for status in state.WORKER_STATUSES:
                try:
                    state.render_worker_result(
                        routed_body(status, question_record, blocking_reason,
                                    kind))
                except state.TrackerValidationError:
                    continue
                accepting.add(STATUS_ROUTE[status])
            with self.subTest(question_record=question_record,
                              blocking_reason=blocking_reason, kind=kind):
                self.assertLessEqual(len(accepting), 1, accepting)

    def test_relabelling_a_quorum_result_as_done_is_refused_both_ways(self):
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                relabelled = quorum_result(status)
                relabelled["status"] = "DONE"
                refuse(self, relabelled)
                demoted = worker_result()
                demoted["status"] = status
                refuse(self, demoted)


class QuestionRecordDiagnosisTests(unittest.TestCase):
    """F5 with the diagnosis asserted, not just the refusal.

    Two screens that refuse the same input are indistinguishable to an
    `assertRaises`: the quorum fixture has an empty `evidence` and an empty
    `commits` too, so a codec that had lost the question-record rule entirely
    and gained a "completion needs evidence" rule would still raise. Every
    assertion here names the rule that must have fired AND the rules that must
    not have.
    """

    OTHER_WORDINGS = ("blocking", "evidence", "commits", "artifacts",
                      "source ref")

    def test_the_refusal_names_the_question_record_and_the_status(self):
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                message = refuse(self, quorum_result(status,
                                                     question_record="-"))
                self.assertIn("question record", message)
                self.assertIn(status, message)
                for wording in self.OTHER_WORDINGS:
                    self.assertNotIn(wording, message)

    def test_the_rule_survives_every_other_field_being_present(self):
        """The fixture the brief used has empty commits, evidence and tests, so
        its refusal is over-determined. This one is a fully populated result
        whose ONLY defect is the missing question record."""
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                populated = worker_result(status=status, question_record="-")
                message = refuse(self, populated)
                self.assertIn("question record", message)
                for wording in self.OTHER_WORDINGS:
                    self.assertNotIn(wording, message)

    def test_an_unbound_question_record_is_a_different_diagnosis(self):
        """'named no record' and 'named one nobody can resolve' are different
        facts, and a single message for both would hide whichever the codec
        stopped checking."""
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                unbound = refuse(self, quorum_result(
                    status, question_record="docs/q.md"))
                self.assertIn("question_record", unbound)
                self.assertNotIn("raises a quorum question and must name",
                                 unbound)

    def test_a_question_record_bound_to_a_short_digest_is_refused(self):
        for length in (0, 1, 63, 65, 128):
            with self.subTest(length=length):
                refuse(self, quorum_result(
                    "NEEDS_CONTEXT",
                    question_record=f"docs/q.md#sha256={'a' * length}"))

    def test_an_upper_case_digest_is_refused(self):
        refuse(self, quorum_result("NEEDS_CONTEXT",
                                   question_record=f"docs/q.md#sha256={'A' * 64}"))

    def test_the_question_record_path_is_held_to_the_plan_path_bar(self):
        for path in ("/abs/q.md", "../q.md", "docs/./q.md", "docs//q.md",
                     "docs\\q.md", "docs/q*.md", "docs/", "", "docs/ q.md"):
            with self.subTest(path=path):
                refuse(self, quorum_result(
                    "NEEDS_CONTEXT",
                    question_record=f"{path}#sha256={DIGEST}"))

    def test_a_plan_metadata_error_is_re_raised_as_a_tracker_error(self):
        """`_safe_relative` belongs to the plan grammar. A controller importing
        a worker result catches `TrackerValidationError`, so an unwrapped
        `PlanMetadataError` is an escape from the family it was promised."""
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._digest_reference(f"../q.md#sha256={DIGEST}", field="q")
        self.assertIsInstance(caught.exception.__cause__, state.PlanMetadataError)
        self.assertNotIsInstance(caught.exception, state.PlanMetadataError)


class BlockedRouteTests(unittest.TestCase):
    """BLOCKED is the one status whose meaning did NOT reverse."""

    def test_a_halt_with_no_stated_reason_is_refused_and_says_so(self):
        message = refuse(self, worker_result(
            status="BLOCKED", source_ref="-", commits=(), evidence=()))
        self.assertIn("halts the run", message)
        self.assertNotIn("question record", message)

    def test_a_halt_naming_a_question_record_is_refused_and_says_so(self):
        message = refuse(self, worker_result(
            status="BLOCKED", source_ref="-", commits=(), evidence=(),
            blocking_reason="no staging credential",
            question_record=QUESTION_RECORD))
        self.assertIn("question record", message)
        self.assertIn("quorum", message)

    def test_a_halt_carries_no_completion_bar(self):
        """A blocked worker has no evidence to name, and requiring some would
        make the one status that means 'I could not do the work' unrenderable."""
        result = worker_result(status="BLOCKED", source_ref="-", commits=(),
                               evidence=(), tests=(),
                               blocking_reason="no staging credential")
        self.assertEqual(
            state.parse_worker_result(state.render_worker_result(result)),
            result,
        )


class CompletionIsAClaimTests(unittest.TestCase):
    """DONE is evidence, not acceptance: a completion must carry the material
    an importer checks it against, or it can only be believed."""

    def test_a_source_completion_needs_its_range_its_suite_and_its_evidence(self):
        for override, wording in (
            ({"evidence": ()}, "names no evidence"),
            ({"source_ref": "-"}, "no source ref or no commits"),
            ({"commits": ()}, "no source ref or no commits"),
            ({"tests": ()}, "names no tests"),
        ):
            for status in state.COMPLETION_STATUSES:
                with self.subTest(override=override, status=status):
                    result = worker_result(status=status, **override)
                    if status == "DONE_WITH_CONCERNS":
                        result["concerns"] = "a rough edge"
                    self.assertIn(wording, refuse(self, result))

    def test_an_artifact_completion_needs_its_artifacts_and_its_evidence(self):
        for override, wording in (
            ({"artifacts": ()}, "names no artifacts"),
            ({"evidence": ()}, "names no evidence"),
        ):
            with self.subTest(override=override):
                self.assertIn(wording, refuse(self, artifact_result(**override)))

    def test_an_artifact_completion_is_not_held_to_the_source_bar(self):
        """P02's `_validate_tasks` asks a completed artifact row for its
        artifacts and nothing about a source range; a codec that asked for
        commits too would make every artifact task unpublishable."""
        result = artifact_result()
        self.assertEqual(
            state.parse_worker_result(state.render_worker_result(result)),
            result,
        )

    def test_done_with_concerns_must_record_the_concern_it_is_named_for(self):
        message = refuse(self, worker_result(status="DONE_WITH_CONCERNS"))
        self.assertIn("states a concern in its own name", message)
        accepted = worker_result(status="DONE_WITH_CONCERNS",
                                 concerns="the retry loop is untested")
        self.assertEqual(
            state.parse_worker_result(state.render_worker_result(accepted)),
            accepted,
        )

    def test_the_grammar_has_no_field_that_can_say_accepted(self):
        """There is nowhere in a worker result to record acceptance, and that is
        the structural half of the ruling. Acceptance is a `## Tasks` state the
        controller writes after checking this document."""
        banned = ("accepted", "approved", "verified", "verdict", "gate",
                  "reviewed", "signoff", "sign_off")
        for field in state.WORKER_RESULT_FIELDS:
            for word in banned:
                with self.subTest(field=field, word=word):
                    self.assertNotIn(word, field)
        self.assertEqual(
            set(state.parse_worker_result(
                state.render_worker_result(worker_result()))),
            set(state.WORKER_RESULT_FIELDS) | {"checkpoints"},
        )

    def test_a_field_the_codec_does_not_render_is_refused_rather_than_dropped(self):
        message = refuse(self, worker_result(verdict="accepted"))
        self.assertIn("unknown fields", message)
        self.assertIn("verdict", message)


# --------------------------------------------------------------------------
# The cell screen: derived families, not a remembered list.
# --------------------------------------------------------------------------

#: Every character below U+3000 that `str.splitlines` -- the reader every
#: section and this codec both use -- treats as a line break. DERIVED by asking
#: the reader, over a range nobody hand-wrote, which is the only way the corpus
#: contains the eight characters an earlier closed list of "the newline
#: characters" did not.
ROW_BREAKERS = tuple(
    chr(code) for code in range(0x3000)
    if len(f"a{chr(code)}b".splitlines()) > 1
)

#: The ASCII control characters, which break a cell's width and a subprocess
#: without breaking a line, so no reader derives them.
CONTROL_CHARACTERS = tuple(chr(code) for code in range(0x20)) + ("\x7f",)


class DerivedCellScreenTests(unittest.TestCase):
    """`_table_safe` is `_cell_safe`'s union, and the union is the rule.

    The failure this replaces has now cost four tasks: a screen written from the
    defects somebody thought of. The brief's `_table_safe` screened `"|"` and
    `"\\n"` and nothing else.
    """

    def test_the_derived_row_break_family_is_larger_than_any_written_list(self):
        self.assertGreaterEqual(len(ROW_BREAKERS), 8)
        self.assertIn(chr(0x0A), ROW_BREAKERS)
        for code in (0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029):
            with self.subTest(code=code):
                self.assertIn(chr(code), ROW_BREAKERS)

    def test_a_closed_list_of_pipe_and_newline_would_pass_almost_all_of_them(self):
        """Measured, so the claim is not rhetorical: of the derived family, a
        `"|" in value or "\\n" in value` screen refuses exactly one."""
        survivors = [char for char in ROW_BREAKERS
                     if "|" not in char and "\n" not in char]
        self.assertEqual(len(survivors), len(ROW_BREAKERS) - 1)

    def test_every_derived_row_breaker_is_refused_in_every_free_text_field(self):
        for char, field in itertools.product(ROW_BREAKERS,
                                             ("concerns", "blocking_reason")):
            with self.subTest(code=ord(char), field=field):
                with self.assertRaises(state.TrackerValidationError):
                    state._table_safe(f"a{char}b", field=field)

    def test_a_row_breaker_would_have_split_the_rendered_row_in_half(self):
        """Why the screen is load-bearing, shown rather than asserted: the row a
        codec without it renders comes back as TWO lines, and the first of them
        still parses as a well-formed two-cell field row holding HALF the value.
        Nothing raises; the result is simply different."""
        for char in ROW_BREAKERS:
            with self.subTest(code=ord(char)):
                row = state._row(("concerns", f"first{char}second"))
                halves = row.splitlines()
                self.assertEqual(len(halves), 2)
                self.assertEqual(state._split_row(halves[0]),
                                 ["concerns", "first"])

    def test_every_ascii_control_character_is_refused(self):
        for char in CONTROL_CHARACTERS:
            with self.subTest(code=ord(char)):
                with self.assertRaises(state.TrackerValidationError):
                    state._table_safe(f"a{char}b", field="concerns")

    def test_a_lone_surrogate_is_refused_by_asking_the_encoder(self):
        """It is pure ASCII on disk as a JSON escape and cannot be encoded at
        all. The failure would otherwise be a `UnicodeEncodeError` -- a
        `ValueError`, outside `TrackerError` -- out of the publish, not the
        render."""
        for code in (0xD800, 0xDBFF, 0xDC00, 0xDFFF):
            with self.subTest(code=code):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(
                        worker_result(concerns=f"a{chr(code)}b"))

    def test_surrounding_whitespace_is_refused_because_cells_are_stripped(self):
        for value in (" a", "a ", "\ta", "a\t", " "):
            with self.subTest(value=value):
                with self.assertRaises(state.TrackerValidationError):
                    state._table_safe(value, field="concerns")

    def test_a_pipe_is_refused_in_every_field_that_takes_free_text(self):
        for field in ("concerns", "blocking_reason"):
            with self.subTest(field=field):
                with self.assertRaises(state.TrackerValidationError):
                    state._table_safe("a|b", field=field)

    def test_an_empty_or_non_string_cell_is_refused(self):
        for value in ("", None, 3, True, (), ["a"], b"a"):
            with self.subTest(value=value):
                with self.assertRaises(state.TrackerValidationError):
                    state._table_safe(value, field="concerns")

    def test_a_comma_is_free_text_in_a_scalar_and_poison_in_a_list_member(self):
        """`_cell_safe` admits a comma on purpose -- English prose has commas
        and `concerns` is prose. The bar belongs on the writer that KNOWS the
        cell is comma-separated, which is the list half and nothing else."""
        self.assertEqual(
            state._table_safe("slow, but correct", field="concerns"),
            "slow, but correct",
        )
        with self.assertRaises(state.TrackerValidationError):
            state._table_safe("a,b", field="tests", list_valued=True)


class ListCellRoundTripTests(unittest.TestCase):
    """A list-valued cell is comma-joined, so its members are held to the bar
    that survives being split back apart. The oracle is the round trip."""

    def test_a_member_carrying_a_comma_is_refused_before_it_can_become_two(self):
        message = refuse(self, worker_result(
            tests=("python3 -m unittest -k T1,T2",)))
        self.assertIn("would parse back as two members", message)

    def test_a_member_spelled_as_the_empty_marker_is_refused(self):
        for field in state._WORKER_LIST_FIELDS:
            with self.subTest(field=field):
                with self.assertRaises(state.TrackerValidationError):
                    state._table_safe("-", field=field, list_valued=True)

    def test_a_single_dash_member_would_have_parsed_back_as_no_members(self):
        """Why that rule exists, measured: a one-member list spelled `-`
        renders the empty-cell marker, and a suite of one becomes a suite of
        none with nothing raised."""
        self.assertEqual(state._result_cell(("-",)), "-")
        self.assertEqual(state._result_cell(()), "-")

    def test_a_duplicate_member_is_refused(self):
        for field, member in (("commits", COMMIT), ("evidence", EVIDENCE_REF),
                              ("tests", "python3 -m unittest"),
                              ("artifacts", "docs/a.md")):
            with self.subTest(field=field):
                with self.assertRaises(state.TrackerValidationError):
                    state._result_list((member, member), field=field)

    def test_a_bare_string_is_refused_rather_than_read_as_characters(self):
        for field in state._WORKER_LIST_FIELDS:
            with self.subTest(field=field):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state._result_list(COMMIT, field=field)
                self.assertIn("iterable of characters", str(caught.exception))

    def test_a_generator_is_refused_rather_than_silently_exhausted(self):
        """Read once by the validator and empty for every later reader: the
        commits would be counted, then rendered as an empty cell, and the result
        would carry a completion claim whose commits nobody ever checked."""
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.render_worker_result(worker_result(commits=iter((COMMIT,))))
        self.assertIn("generator", str(caught.exception))

    def test_a_list_is_accepted_and_normalised_to_a_tuple(self):
        result = worker_result(commits=[COMMIT])
        rendered = state.render_worker_result(result)
        self.assertEqual(state.parse_worker_result(rendered)["commits"],
                         (COMMIT,))

    def test_multi_member_cells_round_trip_through_the_comma(self):
        commits = tuple(f"{index:040x}" for index in range(1, 6))
        tests = tuple(f"python3 -m unittest -k T{index}" for index in range(5))
        evidence = tuple(
            f"docs/superpowers/runs/run-1/evidence/e{index}.md#sha256="
            f"{index:064x}" for index in range(4)
        )
        result = worker_result(commits=commits, tests=tests, evidence=evidence,
                               source_ref=commits[-1])
        self.assertEqual(
            state.parse_worker_result(state.render_worker_result(result)),
            result,
        )

    def test_an_empty_list_cell_round_trips_as_an_empty_tuple(self):
        result = worker_result(status="BLOCKED", source_ref="-", commits=(),
                               artifacts=(), tests=(), evidence=(),
                               blocking_reason="no staging credential")
        parsed = state.parse_worker_result(state.render_worker_result(result))
        for field in state._WORKER_LIST_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(parsed[field], ())


class AttemptTokenTests(unittest.TestCase):
    """`attempt-001` is the tracker's spelling and `1` is every signature's
    value. One conversion point, and its inverse is the renderer itself."""

    def test_the_token_is_three_digit_zero_padded(self):
        for attempt, token in ((1, "attempt-001"), (9, "attempt-009"),
                               (12, "attempt-012"), (100, "attempt-100"),
                               (1000, "attempt-1000")):
            with self.subTest(attempt=attempt):
                self.assertEqual(state._attempt_token(attempt), token)

    def test_the_round_trip_is_the_identity_over_a_wide_range(self):
        for attempt in itertools.chain(range(1, 40), (99, 100, 999, 1000,
                                                      10 ** 8)):
            with self.subTest(attempt=attempt):
                self.assertEqual(
                    state._parse_attempt_token(state._attempt_token(attempt)),
                    attempt,
                )

    def test_only_the_canonical_spelling_parses(self):
        """`attempt-1`, `attempt-01` and `attempt-0001` all read as attempt one
        under a digit-count rule, and all three would give one attempt several
        documents -- in a record whose identity is the sha256 of its bytes."""
        for token in ("attempt-1", "attempt-01", "attempt-0001",
                      "attempt-00001", "attempt-000", "attempt-00",
                      "attempt-0"):
            with self.subTest(token=token):
                self.assertFalse(state._ATTEMPT_TOKEN.fullmatch(token))
                with self.assertRaises(state.TrackerValidationError):
                    state._parse_attempt_token(token)

    def test_a_bool_is_not_an_attempt(self):
        with self.assertRaises(state.TrackerValidationError):
            state._attempt_token(True)

    def test_a_non_positive_or_non_integer_attempt_is_refused(self):
        for attempt in (0, -1, 1.0, "1", None, (1,)):
            with self.subTest(attempt=attempt):
                with self.assertRaises(state.TrackerValidationError):
                    state._attempt_token(attempt)

    def test_non_ascii_digits_do_not_convert(self):
        """`'٣'.isdigit()` is True and `int('٣')` is 3, so the ascii clause is
        the one that narrows this to the ten characters the renderer writes."""
        arabic_indic = "".join(chr(0x0660 + digit) for digit in (0, 0, 3))
        self.assertTrue(arabic_indic.isdigit())
        self.assertEqual(int(arabic_indic), 3)
        self.assertFalse(
            state._ATTEMPT_TOKEN.fullmatch(f"attempt-{arabic_indic}"))
        self.assertFalse(state._ATTEMPT_TOKEN.fullmatch("attempt-" + chr(0x00B3)))

    def test_a_very_long_run_of_digits_is_refused_before_int_is_reached(self):
        """`int()` raises `ValueError` -- not a `TrackerError` -- above
        `sys.int_max_str_digits`. The bound has to be in front of the
        conversion, which is the escape the P04 Task 2 `order` screen was
        rewritten for and is repeated here rather than rediscovered."""
        for digits in (10, 4300, 4301, 9000):
            with self.subTest(digits=digits):
                token = "attempt-" + "9" * digits
                with self.assertRaises(state.TrackerValidationError):
                    state._parse_attempt_token(token)
                self.assertFalse(state._ATTEMPT_TOKEN.fullmatch(token))

    def test_the_prefix_is_required(self):
        for token in ("001", "ATTEMPT-001", "attempt_001", "attempt-001 ",
                      " attempt-001", "", None, 1):
            with self.subTest(token=token):
                self.assertFalse(state._ATTEMPT_TOKEN.fullmatch(token))

    def test_the_document_carries_the_token_and_the_dict_carries_the_int(self):
        text = state.render_worker_result(worker_result(attempt=7))
        self.assertIn("| attempt | attempt-007 |", text)
        self.assertEqual(state.parse_worker_result(text)["attempt"], 7)


class DigestReferenceTests(unittest.TestCase):

    def test_a_reference_splits_into_a_normalised_path_and_a_digest(self):
        self.assertEqual(
            state._digest_reference(EVIDENCE_REF),
            ("docs/superpowers/runs/run-1/evidence/T1.md", DIGEST),
        )

    def test_the_digest_grammar_is_p02s_sha256_and_not_a_second_copy(self):
        """A rebind proves the screen READS `_SHA256` rather than re-typing
        `[0-9a-f]{64}` beside it; a grep cannot tell a second copy from the
        same constant quoted in a docstring."""
        original = state._SHA256
        try:
            state._SHA256 = state._Hex(8)
            self.assertEqual(
                state._digest_reference(f"docs/q.md#sha256={'a' * 8}"),
                ("docs/q.md", "a" * 8),
            )
        finally:
            state._SHA256 = original
        self.assertEqual(state._digest_reference(f"docs/q.md#sha256={DIGEST}"),
                         ("docs/q.md", DIGEST))

    def test_a_hash_inside_the_path_is_refused_rather_than_guessed_at(self):
        """`_cell_safe` admits `#`, so `docs/a#sha256=<64 hex>.md` is a legal
        path and a reference built from it has two readings. Counting the
        delimiter removes the ambiguity instead of picking a side."""
        with self.assertRaises(state.TrackerValidationError):
            state._digest_reference(f"docs/a#b.md#sha256={DIGEST}")

    def test_a_missing_delimiter_is_refused(self):
        for value in ("docs/q.md", f"docs/q.md#{DIGEST}",
                      f"docs/q.md#sha1={DIGEST}", f"#sha256={DIGEST}",
                      f"docs/q.md#SHA256={DIGEST}"):
            with self.subTest(value=value):
                with self.assertRaises(state.TrackerValidationError):
                    state._digest_reference(value)

    def test_every_evidence_reference_is_bound_not_just_the_first(self):
        refuse(self, worker_result(evidence=(EVIDENCE_REF, "docs/second.md")))


class CanonicalFormTests(unittest.TestCase):
    """A worker result is an immutable document whose identity is the sha256 of
    its bytes, so two byte sequences that parse to one result would give one
    result two identities. `parse` therefore finishes by re-rendering what it
    read and demanding the bytes back.

    Every case here is one the field-order screen and the marker screen both
    MISS, so each asserts the canonical diagnosis and asserts the other two
    screens' wordings are absent -- the Task 2 ruling about two checks that
    refuse the same input.
    """

    def setUp(self):
        self.text = state.render_worker_result(worker_result(checkpoints=(
            {"id": "c1", "status": "complete", "evidence": EVIDENCE_REF},
        )))

    def assert_not_canonical(self, text: str) -> None:
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.parse_worker_result(text)
        message = str(caught.exception)
        self.assertIn("not canonical", message)
        self.assertNotIn("missing, unknown, or reordered", message)
        self.assertNotIn("marker is missing or foreign", message)

    def test_the_rendered_document_is_canonical(self):
        self.assertEqual(
            state.render_worker_result(state.parse_worker_result(self.text)),
            self.text,
        )

    def test_a_paragraph_appended_under_the_table_is_refused(self):
        self.assert_not_canonical(
            self.text + "\nThe task is accepted and needs no review.\n")

    def test_a_second_marker_is_refused(self):
        self.assert_not_canonical(self.text + state.WORKER_RESULT_MARKER + "\n")

    def test_a_checkpoint_row_outside_its_section_is_refused(self):
        lines = self.text.splitlines()
        moved = lines.pop()
        lines.insert(1, moved)
        self.assert_not_canonical("\n".join(lines) + "\n")

    def test_an_extra_space_inside_a_cell_is_refused(self):
        self.assert_not_canonical(
            self.text.replace("| owner | impl-1 |", "| owner |  impl-1 |"))

    def test_a_crlf_copy_is_refused(self):
        self.assert_not_canonical(self.text.replace("\n", "\r\n"))

    def test_a_missing_trailing_newline_is_refused(self):
        self.assert_not_canonical(self.text.rstrip("\n"))

    def test_a_trailing_blank_line_is_refused(self):
        self.assert_not_canonical(self.text + "\n")

    def test_a_dropped_section_heading_is_refused(self):
        self.assert_not_canonical(self.text.replace("## Checkpoints\n", ""))

    def test_a_dropped_title_is_refused(self):
        self.assert_not_canonical(
            self.text.replace(state.WORKER_RESULT_TITLE + "\n", ""))

    def test_a_row_written_without_the_leading_space_is_invisible_to_the_scan(self):
        """`| owner | x |` spelled `|owner|x|` is not seen by the row scan at
        all, so this one belongs to the FIELD-ORDER screen and not to the
        canonical one -- which is the distinction an assertRaises alone cannot
        make, and the reason each screen's wording is asserted absent."""
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.parse_worker_result(
                self.text.replace("| owner | impl-1 |", "|owner|impl-1|"))
        self.assertIn("missing, unknown, or reordered", str(caught.exception))

    def test_checkpoint_order_is_preserved_rather_than_normalised(self):
        """Two documents differing only in checkpoint order are two different
        results, not one result spelled twice -- so this is NOT a canonical
        violation, and asserting it were would make the canonical screen claim
        something it does not do."""
        checkpoints = (
            {"id": "c1", "status": "complete", "evidence": EVIDENCE_REF},
            {"id": "c2", "status": "blocked", "evidence": EVIDENCE_REF},
        )
        text = state.render_worker_result(worker_result(checkpoints=checkpoints))
        lines = text.splitlines()
        lines[-1], lines[-2] = lines[-2], lines[-1]
        swapped = "\n".join(lines) + "\n"
        self.assertEqual(
            state.parse_worker_result(swapped)["checkpoints"],
            checkpoints[::-1],
        )
        self.assertNotEqual(swapped, text)

    def test_the_marker_screen_still_owns_a_foreign_document(self):
        """Proof the three screens are distinguishable rather than one screen
        wearing three messages."""
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.parse_worker_result("<!-- pipeline-run/v2 -->\n")
        self.assertIn("marker is missing or foreign", str(caught.exception))
        self.assertNotIn("not canonical", str(caught.exception))

    def test_the_field_order_screen_still_owns_a_reordered_table(self):
        lines = self.text.splitlines()
        index = next(i for i, line in enumerate(lines)
                     if line.startswith("| owner "))
        lines[index], lines[index - 1] = lines[index - 1], lines[index]
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.parse_worker_result("\n".join(lines) + "\n")
        self.assertIn("missing, unknown, or reordered", str(caught.exception))
        self.assertNotIn("not canonical", str(caught.exception))

    def test_a_dropped_field_row_is_refused_by_the_field_order_screen(self):
        for field in state.WORKER_RESULT_FIELDS:
            with self.subTest(field=field):
                lines = [line for line in self.text.splitlines()
                         if not line.startswith(f"| {field} |")]
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.parse_worker_result("\n".join(lines) + "\n")
                self.assertIn("missing, unknown, or reordered",
                              str(caught.exception))

    def test_a_duplicated_field_row_is_refused(self):
        lines = self.text.splitlines()
        index = next(i for i, line in enumerate(lines)
                     if line.startswith("| owner "))
        lines.insert(index, lines[index])
        with self.assertRaises(state.TrackerValidationError):
            state.parse_worker_result("\n".join(lines) + "\n")

    def test_parse_refuses_a_non_string_and_an_empty_document(self):
        for text in ("", "\n", None, b"", state.WORKER_RESULT_MARKER):
            with self.subTest(text=text):
                with self.assertRaises(state.TrackerValidationError):
                    state.parse_worker_result(text)


class CheckpointTableTests(unittest.TestCase):

    def test_checkpoints_round_trip_in_order(self):
        checkpoints = tuple(
            {"id": f"c{index}", "status": status, "evidence": EVIDENCE_REF}
            for index, status in enumerate(state._CHECKPOINT_STATES)
        )
        result = worker_result(checkpoints=checkpoints)
        self.assertEqual(
            state.parse_worker_result(state.render_worker_result(result)),
            result,
        )

    def test_an_unknown_checkpoint_state_is_refused(self):
        for status in ("done", "complete ", "", None, ["complete"]):
            with self.subTest(status=status):
                refuse(self, worker_result(checkpoints=(
                    {"id": "c1", "status": status, "evidence": EVIDENCE_REF},)))

    def test_a_checkpoint_list_with_the_right_words_is_not_a_checkpoint(self):
        """`set(["id", "status", "evidence"])` is exactly the key set, so a
        screen written only as a set comparison admits the LIST and the next
        line indexes it by name: `TypeError`, outside `TrackerError`."""
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(worker_result(
                checkpoints=(list(state._CHECKPOINT_KEYS),)))

    def test_a_checkpoint_missing_or_carrying_an_extra_key_is_refused(self):
        for checkpoint in ({"id": "c1", "status": "complete"},
                           {"id": "c1", "status": "complete",
                            "evidence": EVIDENCE_REF, "extra": "x"},
                           {}):
            with self.subTest(checkpoint=checkpoint):
                refuse(self, worker_result(checkpoints=(checkpoint,)))

    def test_a_repeated_checkpoint_id_is_refused(self):
        message = refuse(self, worker_result(checkpoints=(
            {"id": "c1", "status": "complete", "evidence": EVIDENCE_REF},
            {"id": "c1", "status": "blocked", "evidence": EVIDENCE_REF},
        )))
        self.assertIn("appears twice", message)

    def test_checkpoint_evidence_is_digest_bound(self):
        refuse(self, worker_result(checkpoints=(
            {"id": "c1", "status": "complete", "evidence": "docs/e.md"},)))

    def test_the_checkpoints_collection_is_refused_by_type(self):
        for checkpoints in ("c1", None, {"id": "c1"}, iter(())):
            with self.subTest(checkpoints=checkpoints):
                refuse(self, worker_result(checkpoints=checkpoints))


class WorkerResultShapeTests(unittest.TestCase):

    def test_a_missing_field_is_named(self):
        for field in (*state.WORKER_RESULT_FIELDS, "checkpoints"):
            with self.subTest(field=field):
                result = worker_result()
                del result[field]
                message = refuse(self, result)
                self.assertIn("missing fields", message)
                self.assertIn(field, message)

    def test_a_non_mapping_is_refused(self):
        for result in (None, "DONE", [], ()):
            with self.subTest(result=result):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(result)

    def test_the_identity_fields_are_held_to_their_own_grammars(self):
        for override in ({"run_id": "run 1"}, {"run_id": "run/1"},
                         {"run_id": "-"}, {"task_id": "-"},
                         {"task_id": "a b"}, {"owner": "-"},
                         {"owner": "impl 1"}, {"owner": ""}):
            with self.subTest(override=override):
                refuse(self, worker_result(**override))

    def test_source_ref_is_a_full_commit_or_the_empty_marker(self):
        for value in ("HEAD~1", "b" * 39, "b" * 41, "B" * 40, "main", 5, None):
            with self.subTest(value=value):
                refuse(self, worker_result(source_ref=value))

    def test_a_non_string_source_ref_stays_inside_the_tracker_family(self):
        """`_COMMIT.fullmatch(5)` is an `AttributeError`; the cell screen has to
        come first or the escape is out of the exception family entirely."""
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(worker_result(source_ref=5))

    def test_every_commit_is_checked_not_just_the_first(self):
        refuse(self, worker_result(commits=(COMMIT, "HEAD")))

    def test_both_kinds_render(self):
        for kind in state.TASK_KINDS:
            with self.subTest(kind=kind):
                result = artifact_result() if kind == "artifact" \
                    else worker_result()
                self.assertEqual(result["kind"], kind)
                state.render_worker_result(result)


class WorkerResultTemplateTests(unittest.TestCase):

    def setUp(self):
        self.template = (
            Path(state.__file__).resolve().parents[1] / "templates"
            / "worker-result.md"
        ).read_text(encoding="utf-8")

    def template_rows(self, width: int) -> list:
        return [state._split_row(line) for line in self.template.splitlines()
                if line.startswith("| ")
                and len(state._split_row(line)) == width]

    def test_the_result_table_names_exactly_the_codec_fields_in_order(self):
        """`assertIn(f"| {field} | ", template)` -- the brief's check -- is
        satisfied by a template that also carries three fields the codec does
        not have, and by one whose rows are in any order at all."""
        names = [row[0] for row in self.template_rows(2)
                 if row[0] not in (state._RESULT_HEADER[0], state._TABLE_RULE)]
        self.assertEqual(names, list(state.WORKER_RESULT_FIELDS))

    def test_the_checkpoint_table_header_matches_the_renderer(self):
        headers = [row for row in self.template_rows(3)]
        self.assertIn(list(state._CHECKPOINT_HEADER), headers)

    def test_every_status_and_every_checkpoint_state_is_named(self):
        for value in (*state.WORKER_STATUSES, *state._CHECKPOINT_STATES,
                      *state.TASK_KINDS):
            with self.subTest(value=value):
                self.assertIn(value, self.template)

    def test_the_reversal_and_the_halt_are_both_stated(self):
        for phrase in ("question_record", "blocking_reason", "REQUIRED",
                       "QUORUM QUESTION", "HALTS"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.template)

    def test_the_template_is_not_itself_a_parseable_result(self):
        """A template that validated would be a result claiming a task nobody
        ran, sitting in the repository with a digest."""
        with self.assertRaises(state.TrackerValidationError):
            state.parse_worker_result(self.template)

    def test_the_template_carries_no_absolute_home_path(self):
        self.assertNotIn("/home/", self.template)


# --------------------------------------------------------------------------
# The owner grammar P06 parses out of a published result.
#
# The master plan pins `- **Owner:** <id>` as a BINDING CROSS-PHASE CONTRACT.
# The first version of this codec rendered the owner as a table cell and
# nothing else, so P06's `owner_history` scan over the results tree harvested
# the EMPTY SET and reviewer independence was checked against nothing -- the
# fail-open direction of the property P06 names, which is that a worker
# released after finishing a task can be assigned to review it.
#
# The line can be added by no route but the renderer: `parse_worker_result`'s
# last screen is a byte comparison against a re-render, so a hand-added or
# Task-9-added line makes the document non-canonical and unimportable.
# --------------------------------------------------------------------------


class OwnerLineContractTests(unittest.TestCase):

    def setUp(self):
        self.text = state.render_worker_result(worker_result())

    def test_the_rendered_result_carries_the_line_p06_actually_scans_for(self):
        """Asked with P06's own pattern, not with a pattern re-derived from
        what P04 renders -- the whole defect was that the two disagreed."""
        self.assertEqual(P06_OWNER_LINE.findall(self.text), ["impl-1"])

    def test_the_line_states_every_owner_the_grammar_admits(self):
        """`_TOKEN` is the owner grammar and it admits dots, slashes, colons
        and plus signs; P06's `(\\S+)` must capture all of them whole."""
        for owner in ("impl-1", "a", "impl.1", "impl/1", "impl:1", "impl+1",
                      "IMPL_1", "z9"):
            with self.subTest(owner=owner):
                text = state.render_worker_result(worker_result(owner=owner))
                self.assertEqual(P06_OWNER_LINE.findall(text), [owner])
                self.assertEqual(state.parse_worker_result(text)["owner"],
                                 owner)

    def test_p06s_results_tree_scan_finds_every_owner_of_every_attempt(self):
        """The contract end to end: P06 walks the results tree, reads owner
        history out of the immutable files, and must see the superseded
        attempts as well as the surviving one."""
        owners = ("impl-1", "impl-2", "impl-3")
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "results"
            (results / "T1").mkdir(parents=True)
            for attempt, owner in enumerate(owners, start=1):
                (results / "T1" / f"attempt-{attempt}.md").write_text(
                    state.render_worker_result(
                        worker_result(owner=owner, attempt=attempt)),
                    encoding="utf-8")
            harvested = set()
            for path in sorted(results.rglob("*.md")):
                harvested.update(
                    P06_OWNER_LINE.findall(path.read_text(encoding="utf-8")))
        self.assertEqual(harvested, set(owners))

    def test_a_result_without_the_owner_line_is_refused_by_its_own_screen(self):
        lines = [line for line in self.text.splitlines()
                 if not line.startswith(state._OWNER_LINE_PREFIX)]
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.parse_worker_result("\n".join(lines) + "\n")
        self.assertIn("reviewer-independence", str(caught.exception))
        self.assertNotIn("not canonical", str(caught.exception))

    def test_a_second_owner_line_is_refused_rather_than_read_once(self):
        lines = self.text.splitlines()
        index = next(i for i, line in enumerate(lines)
                     if line.startswith(state._OWNER_LINE_PREFIX))
        lines.insert(index, lines[index])
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.parse_worker_result("\n".join(lines) + "\n")
        self.assertIn("exactly once", str(caught.exception))

    def test_a_line_disagreeing_with_the_cell_names_the_disagreement(self):
        """The canonical screen would refuse this anyway -- for `not
        canonical`, which names the bytes rather than the fact. A document
        stating two owners deserves the diagnosis of the rule it breaks."""
        forged = self.text.replace(state._owner_line("impl-1"),
                                   state._owner_line("reviewer-9"))
        self.assertNotEqual(forged, self.text)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.parse_worker_result(forged)
        self.assertIn("two owners", str(caught.exception))
        self.assertNotIn("not canonical", str(caught.exception))

    def test_the_line_and_the_cell_are_one_conversion_point(self):
        """A second spelling of the owner grammar would be a second answer to
        `who owned this attempt`, which is the question P06 decides reviewer
        independence on."""
        self.assertEqual(state._owner_line("impl-1"), "- **Owner:** impl-1")
        self.assertIn(state._owner_line("impl-1"), self.text.splitlines())

    def test_the_owner_line_is_inside_the_canonical_comparison(self):
        """Not merely present: moved, it is still refused -- so no later task
        can relocate it and keep the document importable."""
        lines = self.text.splitlines()
        index = next(i for i, line in enumerate(lines)
                     if line.startswith(state._OWNER_LINE_PREFIX))
        moved = lines[:index] + lines[index + 1:] + [lines[index]]
        with self.assertRaises(state.TrackerValidationError):
            state.parse_worker_result("\n".join(moved) + "\n")

    def test_the_template_mirrors_the_owner_grammar(self):
        template = (SKILL_DIR / "templates" / "worker-result.md").read_text(
            encoding="utf-8")
        self.assertEqual(len(P06_OWNER_LINE.findall(template)), 1)
        self.assertIn(state._OWNER_LINE_PREFIX, template)

    def test_the_template_still_does_not_parse_as_a_result(self):
        """Mirroring the line must not have turned the template into a result
        claiming a task nobody ran."""
        template = (SKILL_DIR / "templates" / "worker-result.md").read_text(
            encoding="utf-8")
        with self.assertRaises(state.TrackerValidationError):
            state.parse_worker_result(template)


# --------------------------------------------------------------------------
# render and parse are asked the SAME question, over a DERIVED corpus.
#
# The module promises this twice -- "the two directions cannot disagree about
# what a legal result is", and "`_attempt_token` -- THE SINGLE CONVERSION
# POINT, in both directions". The first version had two families where they
# did disagree, and every corpus in this file answered accept/reject rather
# than round-trip, so neither was reachable by any of them.
#
# A disagreement is not a cosmetic defect here: Task 9 renders THEN writes
# immutably, so a result that renders and does not parse is published, bound
# to a digest, unreadable by Task 10 and uncorrectable by anyone.
# --------------------------------------------------------------------------


def identity_vocabulary() -> list:
    """Every word this codec writes into a document or reads structurally out
    of one, DERIVED from the module's own constants rather than guessed.

    `ID` is in here because `_CHECKPOINT_HEADER[0]` is, and `_TOKEN` admits it:
    a checkpoint so named rendered as an ordinary row, parsed as the table
    header, and vanished. Deriving the corpus from the constants is what makes
    the next such word appear in it the moment it is written down.
    """
    words = set(state._RESULT_HEADER) | set(state._CHECKPOINT_HEADER)
    words.add(state._TABLE_RULE)
    words.add(state._ABSENT_CELL)
    words.add(state._ATTEMPT_PREFIX)
    words.add(state._WORKER_CHECKPOINTS)
    words.update(state.WORKER_RESULT_FIELDS)
    words.update(state._CHECKPOINT_STATES)
    words.update(state.WORKER_STATUSES)
    words.update(state.TASK_KINDS)
    words.update(state.WORKER_RESULT_TITLE.split())
    words.update(state._OWNER_LINE_PREFIX.split())
    words.update(state.WORKER_RESULT_MARKER.split())
    return sorted(words)


#: The digit boundary `_MAX_ATTEMPT_DIGITS` names, from both sides, plus one
#: value past `sys.int_max_str_digits` -- which is not a spelling question but
#: an escape: `f"{attempt:d}"` over it raises `ValueError`, outside the family
#: a controller catches. Measured: it did.
ATTEMPT_BOUNDARY = (
    1, 9, 10, 99, 100, 999, 1000,
    10 ** (state._MAX_ATTEMPT_DIGITS - 1),
    10 ** state._MAX_ATTEMPT_DIGITS - 1,
    10 ** state._MAX_ATTEMPT_DIGITS,
    10 ** state._MAX_ATTEMPT_DIGITS + 1,
    10 ** 5000,
)


class RenderParseAgreementTests(unittest.TestCase):
    """For every document in the corpus: either `render` refuses it, or `parse`
    reads its bytes back unchanged. There is no third outcome."""

    def agree(self, result: dict) -> str:
        try:
            text = state.render_worker_result(result)
        except state.TrackerValidationError:
            return "refused"
        try:
            back = state.parse_worker_result(text)
        except state.TrackerValidationError as exc:
            self.fail(f"render published what parse refuses: {exc}")
        self.assertEqual(back, state._validate_worker_result(result))
        return "rendered"

    def test_identity_tokens_from_the_rendered_vocabulary_agree(self):
        checked = 0
        rendered = 0
        for word in identity_vocabulary():
            cases = {
                "task_id": worker_result(task_id=word),
                "owner": worker_result(owner=word),
                "concerns": worker_result(concerns=word),
                "checkpoint id": worker_result(checkpoints=(
                    {"id": word, "status": "complete",
                     "evidence": EVIDENCE_REF},)),
            }
            for position, result in cases.items():
                with self.subTest(word=word, position=position):
                    rendered += self.agree(result) == "rendered"
                    checked += 1
        self.assertEqual(checked, len(identity_vocabulary()) * 4)
        self.assertGreater(rendered, 0)
        self.assertGreater(checked, rendered)   # the corpus is not all-accept

    def test_the_attempt_boundary_agrees_in_both_directions(self):
        for attempt in ATTEMPT_BOUNDARY:
            with self.subTest(attempt=attempt.bit_length()):
                self.agree(worker_result(attempt=attempt))

    def test_the_ceiling_is_the_same_number_on_both_sides(self):
        """One digit under renders and parses; the ceiling itself is refused by
        the renderer rather than published and refused by the parser."""
        last = 10 ** state._MAX_ATTEMPT_DIGITS - 1
        text = state.render_worker_result(worker_result(attempt=last))
        self.assertEqual(state.parse_worker_result(text)["attempt"], last)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.render_worker_result(
                worker_result(attempt=10 ** state._MAX_ATTEMPT_DIGITS))
        self.assertIn(str(state._MAX_ATTEMPT_DIGITS), str(caught.exception))

    def test_an_attempt_past_the_int_conversion_limit_stays_in_the_family(self):
        """`f"{attempt:d}"` raises `ValueError` -- not a `TrackerError` -- once
        the integer needs more than `sys.int_max_str_digits` digits, and it
        raised it INSIDE the renderer before the ceiling was asked of both
        directions. A controller catching `TrackerValidationError` saw nothing."""
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(worker_result(attempt=10 ** 5000))
        self.assertFalse(state._ATTEMPT_TOKEN.fullmatch("attempt-" + "9" * 5000))

    def test_every_checkpoint_state_and_cardinality_agrees(self):
        checkpoint = lambda index, status: {
            "id": f"c{index}", "status": status, "evidence": EVIDENCE_REF}
        checked = 0
        for count in (0, 1, 2):
            for states in itertools.product(state._CHECKPOINT_STATES,
                                            repeat=count):
                with self.subTest(count=count, states=states):
                    self.assertEqual(self.agree(worker_result(checkpoints=tuple(
                        checkpoint(index, status)
                        for index, status in enumerate(states)))), "rendered")
                    checked += 1
        self.assertEqual(checked, 1 + 3 + 9)

    def test_list_cardinalities_agree_in_both_directions(self):
        """0, 1 and 2 members: the empty cell is the `-` marker and re-reads as
        no members, one member is the cell with no comma in it, two is the
        comma that `_result_list` screens its members against."""
        members = {
            "commits": (COMMIT, "c" * 40),
            "tests": ("python3 -m unittest -k T1", "python3 -m unittest -k T2"),
            "evidence": (EVIDENCE_REF,
                         f"docs/superpowers/runs/run-1/evidence/T2.md"
                         f"#sha256={DIGEST}"),
            "artifacts": ("docs/a.md", "docs/b.md"),
        }
        checked = 0
        for field, pair in members.items():
            for count in (0, 1, 2):
                base = artifact_result() if field == "artifacts" else worker_result()
                if field == "commits" and count == 0:
                    base["source_ref"] = state._ABSENT_CELL
                base[field] = pair[:count]
                with self.subTest(field=field, count=count):
                    self.agree(base)
                    checked += 1
        self.assertEqual(checked, 12)

    def test_a_checkpoint_named_after_a_structural_row_word_is_refused(self):
        """With its own diagnosis. Before this, `id="ID"` rendered, the
        checkpoint vanished at parse, and the canonical screen refused the
        document for `not canonical` -- naming the bytes rather than the cause."""
        for word in state._RESERVED_ROW_WORDS:
            with self.subTest(word=word):
                message = refuse(self, worker_result(checkpoints=(
                    {"id": word, "status": "complete",
                     "evidence": EVIDENCE_REF},)))
                self.assertNotIn("not canonical", message)
        self.assertIn("structurally in column one", refuse(self, worker_result(
            checkpoints=({"id": state._CHECKPOINT_HEADER[0],
                          "status": "complete",
                          "evidence": EVIDENCE_REF},))))

    def test_the_reserved_words_are_the_ones_the_parser_actually_filters(self):
        """Derived, not a fresh closed list: these are exactly the column-one
        words `parse_worker_result` reads structurally."""
        self.assertEqual(
            sorted(state._RESERVED_ROW_WORDS),
            sorted({state._RESULT_HEADER[0], state._CHECKPOINT_HEADER[0],
                    state._TABLE_RULE}))


def target_names(target) -> list:
    """Every name one assignment target binds. `ast.Name` is the case the first
    version of the guard handled; `Tuple`, `List` and `Starred` are the ones it
    walked past, and `Attribute`/`Subscript` bind no module-level name at all."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts
                for name in target_names(element)]
    return []


def alternative_bindings(branches: list):
    """The bindings of a set of MUTUALLY EXCLUSIVE branches, counted once.

    `try: import fcntl / except ImportError: fcntl = None` binds `fcntl` twice
    syntactically and once at runtime. Summing the arms would make the module's
    own platform switch a duplicate, and a guard that has to be switched off is
    a guard that catches nothing -- so each name is counted at its MAXIMUM over
    the arms, which still sees a duplicate that sits inside a single arm.
    """
    merged = {}
    for branch in branches:
        for name, count in module_bindings(branch).items():
            merged[name] = max(merged.get(name, 0), count)
    return merged


def module_bindings(body: list):
    """How many times each name is bound at module level, over EVERY binding
    form -- `def`, `class`, `=`, `x: T = ...`, tuple and starred targets,
    `import`, `from ... import`, and the same again inside a module-level `if`,
    `try`, `for` or `with`.

    `AugAssign` is deliberately absent: `x += 1` rebinds a name that must
    already exist, which is not a second definition of it.
    """
    counts = {}

    def add(names):
        for name in names:
            counts[name] = counts.get(name, 0) + 1

    def merge(other):
        for name, count in other.items():
            counts[name] = counts.get(name, 0) + count

    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            add([node.name])
        elif isinstance(node, ast.Assign):
            add([name for target in node.targets
                 for name in target_names(target)])
        elif isinstance(node, ast.AnnAssign):
            add(target_names(node.target) if node.value is not None else [])
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            add([alias.asname or alias.name.split(".")[0]
                 for alias in node.names])
        elif isinstance(node, ast.If):
            merge(alternative_bindings([node.body, node.orelse]))
        elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            merge(alternative_bindings(
                [node.body + node.orelse]
                + [handler.body for handler in node.handlers]))
            merge(module_bindings(node.finalbody))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            add(target_names(node.target))
            merge(alternative_bindings([node.body, node.orelse]))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            add([name for item in node.items
                 if item.optional_vars is not None
                 for name in target_names(item.optional_vars)])
            merge(module_bindings(node.body))
    return counts


class WorkerResultModuleBoundaryTests(unittest.TestCase):
    """What Task 4 must NOT have done to the module it extends."""

    def test_p03s_two_argument_cell_writer_is_untouched(self):
        """The brief named `_cell(value) -> str` as a Task 4 product. `_cell`
        already exists as P03's `_cell(value, what)` and is called at eleven
        sites; a module-level redefinition rebinds the global and every one of
        them becomes a `TypeError`."""
        self.assertEqual(state._cell("run-1", "a qid"), "run-1")
        with self.assertRaises(state.QuorumSchemaInvalid):
            state._cell("a|b", "a qid")

    def test_the_commit_grammar_is_still_p02s_fixed_width_hex(self):
        """`_COMMIT` was named as a Task 4 product too. It is P02's, read at
        seven sites, and a redefinition would move every one of them."""
        self.assertIsInstance(state._COMMIT, state._Hex)
        self.assertTrue(state._COMMIT.fullmatch("b" * 40))
        self.assertFalse(state._COMMIT.fullmatch("b" * 39))
        self.assertFalse(state._COMMIT.fullmatch("B" * 40))

    def test_no_name_in_the_module_is_defined_twice(self):
        """The general form of both defects above, asked of the whole module
        rather than of the two names that happened to be noticed.

        THE FIRST VERSION OF THIS GUARD ENFORCED THREE BINDING FORMS, NOT ALL.
        Measured against four injected duplicates of `_ABSENT_CELL`, it caught
        `def`/`class`/plain `x = ...` and MISSED the annotated assignment, the
        tuple target and the one inside a module-level `try`, and it ignored
        `import` bindings entirely. The module happens to contain no annotated
        assignment, no tuple target and only the `fcntl`/`msvcrt` platform
        `try`, so it did enforce the `_cell`/`_field`/`_csv`/`_COMMIT` shape --
        but "catches the next one without anyone remembering to look" is a
        claim about every binding form, and `module_bindings` is what makes it
        true. See the constraint paragraph in the master plan, which was
        amended in the same commit as this test.
        """
        counts = module_bindings(ast.parse(
            (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
                encoding="utf-8")).body)
        self.assertEqual(
            sorted(name for name, count in counts.items() if count > 1), [])

    def test_the_binding_guard_sees_every_form_a_duplicate_can_take(self):
        """The guard asked of itself. Each snippet binds `_ABSENT_CELL` a
        second time in a different syntactic form; a guard that misses one is a
        guard that is not looking for duplicates but for `def` statements."""
        forms = {
            "function": 'def _ABSENT_CELL(value):\n    return "~"\n',
            "class": 'class _ABSENT_CELL:\n    pass\n',
            "assign": '_ABSENT_CELL = "~"\n',
            "annassign": '_ABSENT_CELL: str = "~"\n',
            "tuple-target": '_ABSENT_CELL, _UNUSED = "~", 1\n',
            "starred-target": '*_ABSENT_CELL, _UNUSED = "~", 1\n',
            "list-target": '[_ABSENT_CELL, _UNUSED] = "~", 1\n',
            "import-as": 'import json as _ABSENT_CELL\n',
            "from-import-as": 'from json import dumps as _ABSENT_CELL\n',
            "in-try": 'try:\n    _ABSENT_CELL = "~"\nexcept Exception:\n    pass\n',
            "in-except": 'try:\n    pass\nexcept Exception:\n    _ABSENT_CELL = "~"\n',
            "in-finally": 'try:\n    pass\nfinally:\n    _ABSENT_CELL = "~"\n',
            "in-if": 'if True:\n    _ABSENT_CELL = "~"\n',
            "in-else": 'if True:\n    pass\nelse:\n    _ABSENT_CELL = "~"\n',
            "in-for": 'for _ABSENT_CELL in "~":\n    pass\n',
            "in-for-body": 'for _UNUSED in "~":\n    _ABSENT_CELL = "~"\n',
            "in-with": 'with open("x") as _ABSENT_CELL:\n    pass\n',
            "nested": 'if True:\n    try:\n        _ABSENT_CELL: str = "~"\n'
                      '    except Exception:\n        pass\n',
        }
        for name, snippet in forms.items():
            with self.subTest(form=name):
                counts = module_bindings(
                    ast.parse('_ABSENT_CELL = "-"\n' + snippet).body)
                self.assertEqual(counts["_ABSENT_CELL"], 2)

    def test_the_binding_guard_does_not_call_a_platform_switch_a_duplicate(self):
        """The two arms of an `if`/`else` or a `try`/`except` are ALTERNATIVES:
        one of them runs. The module's own `try: import fcntl / except
        ImportError: fcntl = None` binds the name twice syntactically and once
        at runtime, and a guard that counted it would have to be switched off
        -- which is how a guard stops catching anything."""
        for source in (
            'try:\n    import fcntl\nexcept ImportError:\n    fcntl = None\n',
            'if True:\n    fcntl = 1\nelse:\n    fcntl = 2\n',
            'try:\n    fcntl = 1\nexcept ImportError:\n    fcntl = 2\n'
            'finally:\n    pass\n',
        ):
            with self.subTest(source=source.splitlines()[0]):
                self.assertEqual(
                    module_bindings(ast.parse(source).body)["fcntl"], 1)
        nested = module_bindings(ast.parse(
            'try:\n    fcntl = 1\n    fcntl = 2\nexcept ImportError:\n'
            '    fcntl = 3\n').body)
        self.assertEqual(nested["fcntl"], 2,
                         "a duplicate INSIDE one arm is still a duplicate")

    def test_the_codec_still_states_its_grammars_without_a_regex_engine(self):
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        self.assertNotIn("re.compile(", source)
        self.assertIsNone(sys.modules["pipeline_auto_state"].__dict__.get("re"))

    def test_the_renderer_uses_p02s_row_and_table_writers(self):
        """A second `"| " + " | ".join(...)` beside `_row` is a second answer to
        what a rendered row looks like, and the canonical check compares bytes."""
        self.assertEqual(state._row(("a", "b")), "| a | b |")
        self.assertEqual(
            state._render_table(("Field", "Value"), (("a", "b"),)),
            ["| Field | Value |", "| --- | --- |", "| a | b |"],
        )

    def test_the_codec_raises_only_tracker_validation_errors(self):
        """Every malformed shape this codec can be handed comes back inside the
        family a controller catches. A `TypeError` or an `AttributeError` here
        is a run that dies on a worker's typo instead of refusing it."""
        hostile = (
            None, [], "DONE", 3,
            worker_result(commits=COMMIT),
            worker_result(commits=iter((COMMIT,))),
            worker_result(checkpoints="c1"),
            worker_result(checkpoints=(["id", "status", "evidence"],)),
            worker_result(source_ref=5),
            worker_result(status=["DONE"]),
            worker_result(kind=None),
            worker_result(attempt=1.0),
            worker_result(concerns=None),
            worker_result(evidence=(None,)),
            worker_result(question_record=object()),
        )
        for result in hostile:
            with self.subTest(result=type(result).__name__):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(result)
        for text in (None, b"", 7, [], state.WORKER_RESULT_MARKER + "\n| a |\n"):
            with self.subTest(text=type(text).__name__):
                with self.assertRaises(state.TrackerValidationError):
                    state.parse_worker_result(text)


# --------------------------------------------------------------------------
# Task 5 tests: the digest-bound typed PASS record.
#
# THE BRIEF SHIPPED SIX TESTS AND NO RENDERER TO TEST AGAINST. Five of the six
# are kept below, corrected where they asserted something the module does not
# do; the rest of this block is the two families the brief had no way to write.
#
# The first is the ROUND-TRIP SWEEP. Task 4 shipped a codec with no
# render->parse family and two shapes escaped in which the renderer accepted
# what the parser refused -- and because a result is published immutably, that
# is a file the run can never read and can never correct. The sweep below is a
# cartesian product over generated legal values, answered against a builder
# written IN THIS FILE that calls neither `render_verification_evidence` nor
# `parse_verification_evidence`: the table layout, the field order and the JSON
# escaping are all spelled out here a second time, so a mutation inside the
# module moves one side of every comparison and not both. Task 3 and Task 4
# each shipped an oracle that asked the implementation for half its answer.
#
# The second is the AGREEMENT EQUIVALENCE. "render and parse agree" is not
# "a legal record round-trips"; it is "the renderer accepts a value if and only
# if the parser accepts that value's canonical cell", asserted over candidates
# per field rather than over one fixture. That is the shape the two Task 4
# escapes would have been caught by.
# --------------------------------------------------------------------------

EVIDENCE_COMMAND = "python3 -m unittest -k T1"
INPUT_REF = f"docs/superpowers/runs/run-1/artifacts/brief.md#sha256={DIGEST}"
SECOND_INPUT_REF = f"src/a.py#sha256={'1' * 64}"


#: Python's `json` encoder uses a SHORT escape for seven characters and
#: `\uXXXX` for everything else outside `\x20`-`\x7e`. Spelled out here
#: because the oracle below is only an independent answer while it is a correct
#: one, and `"a\tb"` renders as `"a\\tb"` and never as `"a\\u0009b"`.
JSON_SHORT_ESCAPES = {
    '"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t",
    "\b": "\\b", "\f": "\\f",
}


def json_string(value: str) -> str:
    r"""`json.dumps` of ONE string, written out rather than called.

    This is the half of the independent oracle that would otherwise have been
    `json.dumps` on both sides of the comparison. Python's encoder escapes `"`
    and `\` and everything outside `\x20`-`\x7e` as `\uXXXX`, and puts `", "`
    between array members; all three are restated here so a change to the
    module's cell writer shows up as a difference rather than as two sides
    moving together. Sweep data stays inside the BMP: a non-BMP character is a
    surrogate pair in `\uXXXX` form and this does not spell that.
    """
    out = ['"']
    for character in value:
        if character in JSON_SHORT_ESCAPES:
            out.append(JSON_SHORT_ESCAPES[character])
        elif not 0x20 <= ord(character) <= 0x7E:
            out.append(f"\\u{ord(character):04x}")
        else:
            out.append(character)
    return "".join(out) + '"'


def json_array(values) -> str:
    return "[" + ", ".join(json_string(value) for value in values) + "]"


def evidence_cell(field: str, value) -> str:
    """The canonical CELL for one field's in-memory value. `-` for an empty
    array is the module's rule and is restated here, not imported."""
    if field in ("commands", "inputs"):
        return json_array(value) if value else "-"
    return value


#: The nine in-memory field values of one legal record.
EVIDENCE_VALUES = {
    "purpose": "task-test",
    "run_id": "run-1",
    "subject": "task/T1",
    "attempt": "attempt-001",
    "code_state": COMMIT,
    "outcome": "PASS",
    "commands": (EVIDENCE_COMMAND,),
    "environment": "python3.11-linux",
    "inputs": (),
}


def _known(overrides) -> None:
    """An unknown override is a `KeyError`, for `phase_line`'s reason: a helper
    that accepts `evidence_record(purposes=...)` and returns the untouched
    default makes a rejection test assert a rejection of nothing."""
    unknown = sorted(set(overrides) - set(EVIDENCE_VALUES))
    if unknown:
        raise KeyError(
            f"an evidence record has no field {unknown}; the fields are "
            f"{sorted(EVIDENCE_VALUES)}")


def evidence_record(**overrides) -> dict:
    """The in-memory record `render_verification_evidence` takes."""
    _known(overrides)
    return dict(EVIDENCE_VALUES, **overrides)


def evidence_text(order=None, **overrides) -> str:
    """The canonical DOCUMENT, built here rather than by the renderer.

    Overrides are CELLS, so a test can write a cell no in-memory value renders
    to -- ` task-test`, `[]`, `attempt-0001` -- which is most of what the
    rejection half is about.
    """
    _known(overrides)
    cells = {field: evidence_cell(field, value)
             for field, value in EVIDENCE_VALUES.items()}
    cells.update(overrides)
    keys = tuple(order) if order is not None else tuple(EVIDENCE_VALUES)
    rows = "\n".join(f"| {key} | {cells[key]} |" for key in keys)
    return (f"{state.EVIDENCE_MARKER}\n{state.EVIDENCE_TITLE}\n\n"
            f"| Field | Value |\n| --- | --- |\n{rows}\n")


def write_evidence(directory, name: str = "T1.md", **overrides) -> str:
    """Write one evidence file and return its sha256 hex digest."""
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    content = evidence_text(**overrides)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def refuse_evidence(case, text) -> str:
    """Parse `text`, require a `TrackerValidationError`, return its message."""
    with case.assertRaises(state.TrackerValidationError) as caught:
        state.parse_verification_evidence(text)
    return str(caught.exception)


class VerificationEvidenceCodecTests(TempDirTestCase):
    """The brief's six, corrected where the brief asserted something else."""

    def test_round_trips(self):
        record = state.parse_verification_evidence(evidence_text())
        self.assertEqual(record["purpose"], "task-test")
        self.assertEqual(record["subject"], "task/T1")
        self.assertEqual(record["attempt"], "attempt-001")
        self.assertEqual(record["code_state"], COMMIT)
        self.assertEqual(record["commands"], (EVIDENCE_COMMAND,))

    def test_rejects_a_foreign_marker(self):
        text = evidence_text().replace(
            state.EVIDENCE_MARKER, "<!-- pipeline-verification-evidence/v2 -->"
        )
        with self.assertRaises(state.TrackerValidationError):
            state.parse_verification_evidence(text)

    def test_rejects_invalid_records(self):
        """The brief's twelve cases, as CELLS.

        `{"commands": "[]"}` and `{"commands": "not-json"}` were the two the
        brief's own implementation could not pass: `_parse_command_suite`
        raises `PlanMetadataError`, which is a SIBLING of
        `TrackerValidationError` and not a subclass, so both cases escaped the
        family the test asserts and the family a controller catches.
        """
        cases = (
            {"outcome": "FAIL"}, {"outcome": "pass"}, {"purpose": "remediation"},
            {"purpose": "anything"}, {"code_state": "short"}, {"commands": "[]"},
            {"commands": "not-json"}, {"environment": "-"}, {"subject": "T1"},
            {"attempt": "0"}, {"attempt": "later"}, {"attempt": "1"},
        )
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(state.TrackerValidationError):
                    state.parse_verification_evidence(evidence_text(**override))

    def test_rejects_reordered_fields(self):
        order = list(state.EVIDENCE_FIELDS)
        index = order.index("outcome")
        order[index], order[index - 1] = order[index - 1], order[index]
        with self.assertRaises(state.TrackerValidationError):
            state.parse_verification_evidence(evidence_text(order=order))

    def test_resolve_evidence_verifies_the_digest(self):
        run_dir = self.tmp / "run"
        digest = write_evidence(run_dir / "evidence")
        record = state.resolve_evidence(
            run_dir, self.tmp, f"evidence/T1.md#sha256={digest}"
        )
        self.assertEqual(record["subject"], "task/T1")
        with self.assertRaises(state.TrackerValidationError):
            state.resolve_evidence(
                run_dir, self.tmp, f"evidence/T1.md#sha256={'c' * 64}"
            )
        with self.assertRaises(state.TrackerValidationError):
            state.resolve_evidence(
                run_dir, self.tmp, f"evidence/absent.md#sha256={digest}"
            )

    def test_template_matches_the_codec_fields(self):
        template = (
            Path(state.__file__).resolve().parents[1]
            / "templates" / "verification-evidence.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(template.startswith(state.EVIDENCE_MARKER))
        for field in state.EVIDENCE_FIELDS:
            with self.subTest(field=field):
                self.assertIn(f"| {field} | ", template)


#: Attempt cells SPELLED OUT rather than produced by `_attempt_token`. A sweep
#: whose data came from the module's own converter would accept whatever the
#: converter did, including a converter that stopped zero-padding.
#: `test_the_swept_attempt_cells_are_the_renderers_own_spelling` pins the list
#: back to the conversion point, so the two cannot drift apart silently.
SWEEP_ATTEMPTS = (
    "N/A", "attempt-001", "attempt-009", "attempt-010", "attempt-099",
    "attempt-100", "attempt-999", "attempt-1000", "attempt-123456",
)

#: Command suites chosen to exercise the cell writer rather than the happy
#: path: a quote, a backslash, a comma, a `#`, a `:`, a `+`, a non-ASCII
#: character and a two- and three-member suite. `chr(0x…)` rather than a
#: `\uXXXX` escape, because an escape in a tool argument is decoded before it
#: reaches disk and the file would then hold the character itself.
SWEEP_COMMANDS = (
    ("make check",),
    ("python3 -m unittest discover -s tests", "git status --short"),
    ("printf 'a,b' > out", "make check", "./tools/check-plugin.sh"),
    ('grep -n "a b" src', "echo a#b", "echo a:b+c"),
    ("echo back\\slash",),
    (f"echo {chr(0x00E9)}{chr(0x4E2D)}",),
)

SWEEP_INPUTS = ((), (INPUT_REF,), (INPUT_REF, SECOND_INPUT_REF))


class EvidenceRoundTripSweepTests(unittest.TestCase):
    """`render` and `parse` agree, asked of generated values and not fixtures."""

    def test_the_swept_attempt_cells_are_the_renderers_own_spelling(self):
        """The hand-written list above, pinned to `_attempt_token` -- THE single
        conversion point. Without this the sweep would go green against a
        renderer that had stopped agreeing with the worker-result codec, and
        the two documents would spell one attempt two ways."""
        self.assertEqual(
            [cell for cell in SWEEP_ATTEMPTS if cell != state.EVIDENCE_NO_ATTEMPT],
            [state._attempt_token(number)
             for number in (1, 9, 10, 99, 100, 999, 1000, 123456)])

    def test_the_hand_written_json_encoder_agrees_with_the_library(self):
        """The oracle, audited. It is only an independent answer while it is a
        CORRECT one, and every difference from `json.dumps` would otherwise
        show up as a module defect."""
        corpus = [command for suite in SWEEP_COMMANDS for command in suite]
        corpus += ['a"b', "a\\b", "a,b", "-", "", "a b", "a\tb", "a\nb",
                   "a\rb", "a\bb", "a\fb", chr(0x00), chr(0x1F), chr(0x7F),
                   chr(0x2028), chr(0x2029), chr(0x0085), chr(0x00E9),
                   chr(0x4E2D), chr(0xFFFD), chr(0x0661)]
        for value in corpus:
            with self.subTest(value=value):
                self.assertEqual(json_string(value), json.dumps(value))
        self.assertEqual(json_array(corpus), json.dumps(corpus))

    def test_render_and_parse_agree_over_every_generated_legal_record(self):
        """The cartesian product, both directions, against this file's builder.

        Neither side of either assertion calls the other function: the expected
        document comes from `evidence_text` and the expected record from
        `evidence_record`, both written here. A mutation in the module moves
        exactly one side.
        """
        identifiers = {"task": "T1", "phase": "P04"}
        for purpose, kind, attempt, commands, inputs in itertools.product(
                state.EVIDENCE_PURPOSES, state.EVIDENCE_SUBJECT_KINDS,
                SWEEP_ATTEMPTS, SWEEP_COMMANDS, SWEEP_INPUTS):
            subject = f"{kind}/{identifiers[kind]}"
            record = evidence_record(purpose=purpose, subject=subject,
                                     attempt=attempt, commands=commands,
                                     inputs=inputs)
            text = evidence_text(
                purpose=purpose, subject=subject, attempt=attempt,
                commands=evidence_cell("commands", commands),
                inputs=evidence_cell("inputs", inputs))
            with self.subTest(purpose=purpose, subject=subject,
                              attempt=attempt, commands=commands,
                              inputs=len(inputs)):
                self.assertEqual(
                    state.render_verification_evidence(record), text)
                self.assertEqual(
                    state.parse_verification_evidence(text), record)

    def test_a_parsed_record_renders_back_to_the_bytes_it_was_read_from(self):
        """The third leg. `parse(render(r)) == r` and `render(parse(t)) == t`
        are different claims, and only the second is what makes a published
        digest the digest of a record a validator saw."""
        for inputs in SWEEP_INPUTS:
            for commands in SWEEP_COMMANDS:
                text = evidence_text(
                    commands=evidence_cell("commands", commands),
                    inputs=evidence_cell("inputs", inputs))
                with self.subTest(commands=commands, inputs=len(inputs)):
                    record = state.parse_verification_evidence(text)
                    self.assertEqual(
                        state.render_verification_evidence(record), text)


#: THE TWO ARMS, SPLIT AND EACH GIVEN ITS VERDICT.
#:
#: They were one table and the only assertion over it was "render and parse
#: agree". That relation is SYMMETRIC: a screen deleted from the validator is
#: gone from both directions at once, so the two sides still agree and the
#: sweep stays green. Measured -- three mutants survived it: a subject whose
#: stable id is not a token, an unchecked `run_id`, and an `inputs` array that
#: names one artifact twice. The equivalence is still asserted below, because
#: it is the property Task 4 shipped two violations of; it is simply not
#: sufficient on its own, and a sweep that cannot fail is not a sweep.
EVIDENCE_LEGAL = {
    "purpose": ("task-test", "task-integration", "phase"),
    "run_id": ("run-1", "run.1", "run_1", "RUN-1", "1run"),
    "subject": ("task/T1", "phase/P04", "task/T1/a"),
    "attempt": ("attempt-001", "attempt-999", "N/A"),
    "code_state": (COMMIT,),
    "outcome": ("PASS",),
    "commands": ((EVIDENCE_COMMAND,), ("a", "b")),
    "environment": ("python3.11-linux", "python 3.11 linux"),
    "inputs": ((), (INPUT_REF,), (INPUT_REF, SECOND_INPUT_REF)),
}

EVIDENCE_ILLEGAL = {
    "purpose": ("remediation", "task-review", "TASK-TEST", "", "-",
                " task-test", "task-test ", "task test"),
    "run_id": ("", "-", "run 1", "run/1", "run@1"),
    "subject": ("T1", "/T1", "task/", "anything/x", "TASK/T1", "task/T 1",
                "task/-T1", "task//T1", "", "-"),
    "attempt": ("attempt-0001", "attempt-1", "attempt-01", "attempt-000",
                "0", "1", "later", "n/a", "", "-",
                "attempt-" + chr(0x0661) * 3),
    "code_state": ("short", "b" * 39, "b" * 41, "B" * 40, "HEAD~1", "main",
                   "", "-"),
    "outcome": ("FAIL", "pass", "Pass", "PASSED", "", "-"),
    "commands": ((), ("a", "a"), ("",), ("a|b",), (" a",), ("a\tb",),
                 ("a" + chr(0x2028) + "b",)),
    "environment": ("-", "", "a|b", "a\tb"),
    "inputs": ((INPUT_REF, INPUT_REF), ("docs/a.md",), ("",),
               (f"../a.md#sha256={DIGEST}",), (f"docs/a.md#sha256={'a' * 8}",),
               (f"docs/a.md#sha256={'A' * 64}",)),
}


class EvidenceAgreementEquivalenceTests(unittest.TestCase):
    """Each candidate gets its verdict, and the two directions agree on it.

    `render` accepting a value the parser refuses is the failure Task 4 shipped
    twice, and it is published immutably -- a file the run can never read and
    can never correct. `render` and `parse` both accepting something neither
    should is the failure the equivalence alone cannot see.
    """

    def accepted_by_render(self, field, value) -> bool:
        try:
            state.render_verification_evidence(evidence_record(**{field: value}))
        except state.TrackerValidationError:
            return False
        return True

    def accepted_by_parse(self, field, value) -> bool:
        try:
            state.parse_verification_evidence(
                evidence_text(**{field: evidence_cell(field, value)}))
        except state.TrackerValidationError:
            return False
        return True

    def test_every_legal_candidate_is_accepted_in_both_directions(self):
        for field, candidates in EVIDENCE_LEGAL.items():
            for value in candidates:
                with self.subTest(field=field, value=value):
                    self.assertTrue(self.accepted_by_render(field, value))
                    self.assertTrue(self.accepted_by_parse(field, value))

    def test_every_illegal_candidate_is_refused_in_both_directions(self):
        for field, candidates in EVIDENCE_ILLEGAL.items():
            for value in candidates:
                with self.subTest(field=field, value=value):
                    self.assertFalse(self.accepted_by_render(field, value))
                    self.assertFalse(self.accepted_by_parse(field, value))

    def test_the_two_directions_agree_on_every_candidate(self):
        for table in (EVIDENCE_LEGAL, EVIDENCE_ILLEGAL):
            for field, candidates in table.items():
                for value in candidates:
                    with self.subTest(field=field, value=value):
                        self.assertEqual(self.accepted_by_render(field, value),
                                         self.accepted_by_parse(field, value))

    def test_every_field_has_both_arms(self):
        """A field with an empty illegal arm has no screen this suite pins, and
        a field with an empty legal arm would be satisfied by one that refuses
        everything."""
        for field in state.EVIDENCE_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(EVIDENCE_LEGAL[field])
                self.assertTrue(EVIDENCE_ILLEGAL[field])


#: THE OUTER BOUNDARY, WHICH NEITHER THE SWEEP NOR THE CANDIDATE TABLE VARIES.
#: Every document in both of those is built by `evidence_text`, which always
#: emits one leading marker line and exactly one trailing `\n` -- so the whole
#: of the coverage above is over CELLS, and the ENVELOPE around them was pinned
#: by nothing. Measured: two mutants of the byte comparison in
#: `parse_verification_evidence` -- `.rstrip("\n") != text.rstrip("\n")` and
#: `.strip() != text.strip()` -- accepted the canonical document, the same
#: document with no trailing newline, and the same document with three, for
#: THREE different sha256s, with the full suite green. One record, three legal
#: spellings, three identities, in a codec whose whole purpose is that a record
#: has exactly one of each.
#:
#: This is the generalisation of the master plan's symmetric-property rule: a
#: candidate table of VALUES does not reach a screen whose subject is the
#: DOCUMENT. Each entry below differs from the canonical bytes only outside the
#: field cells.
def evidence_envelopes() -> tuple:
    """`(label, document)` for every non-canonical spelling of one record."""
    canonical = evidence_text()
    body = canonical.rstrip("\n")
    return (
        ("no trailing newline", body),
        ("two trailing newlines", body + "\n\n"),
        ("three trailing newlines", body + "\n\n\n"),
        ("a leading blank line", "\n" + canonical),
        ("a leading space before the marker", " " + canonical),
        ("a blank line after the marker",
         canonical.replace(state.EVIDENCE_MARKER,
                           state.EVIDENCE_MARKER + "\n", 1)),
        ("a trailing space on the last row", body + " \n"),
        ("a trailing space on the marker line",
         canonical.replace(state.EVIDENCE_MARKER,
                           state.EVIDENCE_MARKER + " ", 1)),
        ("a line of spaces after the table", canonical + "   \n"),
        ("a CRLF copy", canonical.replace("\n", "\r\n")),
        ("a BOM in front of the marker", "﻿" + canonical),
        ("the table indented by one space",
         canonical.replace("\n| ", "\n | ")),
        #: THE LINE SEPARATORS `str.splitlines()` BREAKS ON AND `"\n".join`
        #: DOES NOT PUT BACK. The parse reads `text.splitlines()` and the
        #: comparison is against a document the renderer joined with `\n`, so
        #: these three are the only characters that are a LINE BREAK to one
        #: side of the comparison and ordinary text to the other. A compare
        #: blind to them accepts a document with a stray U+2028 after the
        #: table, under a second sha256, with every field cell untouched.
        ("a line separator after the table", canonical + "\u2028"),
        ("a paragraph separator after the table", canonical + "\u2029"),
        ("a next-line after the table", canonical + "\u0085"),
        #: THE TWO THE BYTE COMPARISON'S OWN DOCSTRING NAMES, neither of which
        #: the whitespace-only corpus reached. "a paragraph under the table
        #: claiming the suite actually failed, a second marker" is the sentence
        #: in `parse_verification_evidence`, and a docstring claiming a
        #: property no test pins is a claim nobody checked.
        ("a second marker line", canonical + state.EVIDENCE_MARKER + "\n"),
        ("a prose paragraph under the table",
         canonical + "The suite actually FAILED; PASS recorded to unblock "
                     "the run.\n"),
        #: NON-ROW CONTENT THAT IS NOT WHITESPACE AND NOT A ROW. The title is
        #: rendered and never read back, so every screen above the byte
        #: comparison is blind to it by construction.
        ("the title line rewritten",
         canonical.replace(state.EVIDENCE_TITLE, "# A Different Heading", 1)),
        ("a tab on the blank line", canonical.replace("\n\n", "\n\t\n", 1)),
        #: DELETIONS, because every entry above this point ADDS or SUBSTITUTES.
        #: A comparison normalised by DROPPING a structural line -- the blank
        #: line, the table rule -- is blind in the other direction, and neither
        #: line is read by anything above the byte comparison: the rule row is
        #: explicitly skipped by the field-row filter.
        ("the blank line after the title removed",
         canonical.replace("\n\n", "\n", 1)),
        ("the table rule row removed",
         canonical.replace("| --- | --- |\n", "", 1)),
        #: AND ONE THAT IS NOT ASCII AND NOT A SEPARATOR, so the corpus is not
        #: closed under Unicode normalisation either: NFKC maps U+00A0 to a
        #: space, so a comparison that normalised both sides would accept this
        #: document as the canonical one.
        ("a no-break space in the title",
         canonical.replace("Auto \u2014", "Auto\u00a0\u2014", 1)),
    ) + _value_repeat_envelopes(canonical)


#: A CORPUS BUILT FROM KNOWN MUTANTS PROVES ONLY THAT THOSE MUTANTS DIE, and
#: this arm is the worked example: three revisions of it, each believed
#: complete, each closed against exactly the defects that motivated it, each
#: followed by a survivor in a direction nobody had been bitten in yet. The
#: whitespace entries were built from the two `.rstrip`/`.strip` mutants; the
#: separator, non-row and deletion entries from the four that survived those;
#: and the comment that used to stand here asserted -- correctly -- that every
#: document above is one perturbation of ONE record's bytes, so a blindness
#: keyed to a VALUE is invisible to them, and then asserted -- falsely, and
#: without measuring it -- that `EVIDENCE_LEGAL`/`EVIDENCE_ILLEGAL` covered
#: that case. They do not. Those tables drive both directions through one
#: fixture, so they vary what a CELL can spell; they never produce a document
#: in which a value appears anywhere a cell is not. Measured: four mutants of
#: the byte comparison, made blind to `run_id`, `outcome`, `code_state` and
#: `subject`, passed all 1472 tests while accepting a document under a second
#: sha256 that parses to this same record.
#:
#: SO DERIVE THE CASE LIST FROM THE STRUCTURE BEING SCREENED, NOT FROM THE
#: DEFECTS YOU REMEMBER -- and read that as an instruction for the NEXT corpus
#: in this file, not as a note about this one. The structure here is a fixed
#: envelope around nine named cells, so the list is one document per ENVELOPE
#: DIMENSION (the block above: trailing bytes, leading bytes, line endings,
#: line separators, non-row content, deletions, normalisation) PLUS one
#: document per FIELD THE SCREEN RANGES OVER, which is what the function below
#: generates. Two of the seven it generates were needed by no mutant anyone had
#: seen; they are the part a mutant-shaped corpus would not have contained, and
#: they are the reason the list is generated from the record rather than typed
#: out from a table of survivors.
def _value_repeat_envelopes(canonical: str) -> tuple:
    """One document per string-valued field: the canonical bytes with that
    field's own value repeated once outside the table.

    WHY THAT IS THE SHAPE, and it is forced rather than chosen. A comparison
    blind to a VALUE is one that normalises that value out of both sides --
    `render(validated).replace(v, "") != text.replace(v, "")` is the whole
    mutant -- so the only document it cannot see is one differing from the
    canonical bytes by extra occurrences of `v` AND BY NOTHING ELSE. Appending
    the bare value adds no line, no separator and no space, so after the
    mutant's normalisation the two sides are byte-identical: the mutant ACCEPTS,
    the refusal this arm asserts does not happen, and the test fails -- which
    is the mutant dying. Append the value as its own LINE instead and the
    newline survives the normalisation, the mutant refuses the document too,
    the test passes, and the mutant lives: a corpus entry that looks like it
    varies the value and pins nothing.

    ONE PER FIELD, AND THE PER-FIELD PART IS MEASURED RATHER THAN ASSUMED. The
    first shape tried was two documents on the theory that any inserted value
    is a value; run against the seven mutants it killed `run_id` and `outcome`
    and left `code_state` and `subject` alive through the whole suite. The
    blindness is keyed to ONE field's spelling, so the corpus needs one
    document per field the screen ranges over and no fewer.

    `commands` and `inputs` are excluded because they are not strings. Their
    cells are JSON arrays and the in-memory value such a comparison could key
    on is a tuple, which has no spelling to repeat; a blindness that reached
    them would be keyed to the cell TEXT, which is `EVIDENCE_LEGAL`'s half.
    The `isinstance` filter is the honest boundary rather than a hand-typed
    list of seven names -- seven of the nine qualify today, and a tenth field
    arrives with its document already made.
    """
    return tuple(
        (f"the {field} value repeated outside the table", canonical + value)
        for field, value in EVIDENCE_VALUES.items()
        if isinstance(value, str)
    )


class EvidenceEnvelopeTests(unittest.TestCase):
    """One record, ONE spelling -- asserted over the document, not the cells."""

    def test_the_canonical_document_is_exactly_these_bytes(self):
        """THE SPECIMEN, and it is deliberately a literal rather than a call.

        There was no valid example record anywhere: the template is
        intentionally unparseable, so a later task wiring `publish_immutable`
        to this codec had nothing to copy and nothing to diff against. Writing
        the bytes out means the envelope -- one marker line, the title, one
        blank line, the header, the rule, nine rows, one trailing newline --
        is pinned by a comparison a reader can check by eye, and a renderer
        that grew a second blank line fails HERE rather than in an unrelated
        round-trip assertion three classes away.
        """
        specimen = (
            "<!-- pipeline-auto-verification-evidence/v1 -->\n"
            "# Pipeline Auto — Verification Evidence\n"
            "\n"
            "| Field | Value |\n"
            "| --- | --- |\n"
            "| purpose | task-test |\n"
            "| run_id | run-1 |\n"
            "| subject | task/T1 |\n"
            "| attempt | attempt-001 |\n"
            f"| code_state | {COMMIT} |\n"
            "| outcome | PASS |\n"
            f"| commands | [\"{EVIDENCE_COMMAND}\"] |\n"
            "| environment | python3.11-linux |\n"
            "| inputs | - |\n"
        )
        self.assertEqual(
            state.render_verification_evidence(evidence_record()), specimen)
        self.assertEqual(state.parse_verification_evidence(specimen),
                         evidence_record())
        self.assertEqual(evidence_text(), specimen)

    def test_every_other_spelling_of_the_same_record_is_refused(self):
        """Refused, and refused by one of the three STRUCTURAL screens -- the
        marker line, the field-name sequence, or the byte comparison against
        the renderer. Those are the only three that can see a document rather
        than a cell. A refusal carrying a FIELD screen's diagnosis would mean
        the fixture had mangled a value as well, and would pin nothing about
        the boundary; the indented-table case is here because it lands on the
        second of the three, an indented row being invisible to the row reader
        rather than a differently spelled one."""
        structural = (CANONICAL_DIAGNOSIS, REORDER_DIAGNOSIS, MARKER_DIAGNOSIS)
        for label, document in evidence_envelopes():
            with self.subTest(envelope=label):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.parse_verification_evidence(document)
                message = str(caught.exception)
                self.assertTrue(
                    any(phrase in message for phrase in structural),
                    f"{label} was refused by a field screen: {message}")

    def test_each_refused_envelope_would_have_been_a_second_identity(self):
        """Why the refusals matter rather than merely being tidy. Each document
        above carries the same nine field values and hashes to something else,
        so a parser that accepted any of them would let one record be published
        under two digests -- and a digest-bound reference names one of them."""
        canonical = evidence_text()
        digests = {hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
        for label, document in evidence_envelopes():
            with self.subTest(envelope=label):
                self.assertNotEqual(document, canonical)
                digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
                self.assertNotIn(digest, digests)
                digests.add(digest)
        self.assertEqual(len(digests), len(evidence_envelopes()) + 1)

    def test_the_envelope_arm_is_not_empty(self):
        """An arm that generated nothing would make the two tests above pass by
        iterating over no cases at all."""
        self.assertGreaterEqual(len(evidence_envelopes()), 10)

    def test_the_arm_carries_one_document_per_string_valued_field(self):
        """The generated half, pinned by its DERIVATION and not by a size.

        Dropping `_value_repeat_envelopes` from the corpus removes seven
        documents and NO other test in this file notices: the two assertions
        above iterate over whatever they are given, and the size check is a
        `>=` that twenty-two documents already satisfy. So the rule that the
        case list is derived from the record rather than from remembered
        mutants is asserted here, or it is advisory prose that the next
        revision of this corpus is free to lose.
        """
        labels = {label for label, _ in evidence_envelopes()}
        expected = {f"the {field} value repeated outside the table"
                    for field, value in EVIDENCE_VALUES.items()
                    if isinstance(value, str)}
        self.assertEqual(len(expected), 7)
        self.assertEqual(expected - labels, set())


class EvidenceRenderOnlyScreenTests(unittest.TestCase):
    """The screens only the RENDER direction can reach, because the parse
    direction hands `_validate_verification_evidence` values a reader built.

    A candidate table drives both directions, so by construction it can only
    carry values a cell can spell. These are the ones it cannot: an `inputs`
    that is not a sequence at all, and a `commands` member that `json` will
    happily write and RFC 8259 has no literal for.
    """

    def render(self, **overrides):
        return state.render_verification_evidence(evidence_record(**overrides))

    def test_an_inputs_that_is_not_a_sequence_stays_inside_the_family(self):
        """`_evidence_inputs`'s `isinstance` guard, which review read as the
        unreachable pattern removed from `_json_array_cell`. Measured with it
        bypassed: `inputs=5` raises `TypeError: 'int' object is not iterable`
        from `tuple()`, OUTSIDE `TrackerError` -- so a controller that wrapped
        an evidence render in `except TrackerError` dies on it -- and
        `inputs=iter(())` is ACCEPTED, rendering `-` for a record whose author
        handed over an iterator that a retry would find empty."""
        for value in (5, None, object(), 3.5, True, {"a": 1}.keys()):
            with self.subTest(inputs=type(value).__name__):
                with self.assertRaises(state.TrackerValidationError):
                    self.render(inputs=value)
        for label, value in (("an exhausted iterator", iter(())),
                             ("a generator", (x for x in (INPUT_REF,))),
                             ("a bare string", INPUT_REF),
                             ("a set", {INPUT_REF})):
            with self.subTest(inputs=label):
                with self.assertRaises(state.TrackerValidationError):
                    self.render(inputs=value)

    def test_a_commands_that_is_not_a_sequence_stays_inside_the_family(self):
        """The same guard on the sibling field, for the same two reasons."""
        for value in (5, None, object(), "make check", iter(()),
                      (x for x in ("a",))):
            with self.subTest(commands=type(value).__name__):
                with self.assertRaises(state.TrackerValidationError):
                    self.render(commands=value)

    def test_the_json_array_cell_never_writes_a_token_rfc_8259_lacks(self):
        """`json.dumps` emits `NaN`, `Infinity` and `-Infinity` as BARE TOKENS
        by default, and RFC 8259 has no literal for any of them: a cell holding
        one is a document only Python can read back, bound by a digest, in an
        audit trail a human's `jq` cannot open. `_dumps` was spelled out for
        exactly this and cannot be called here -- it writes an indented,
        newline-terminated FILE and a cell is one line -- so the default is
        corrected in place. No AST guard covers `json.dumps`, only `json.loads`.
        """
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(member=repr(value)):
                with self.assertRaises(state.TrackerValidationError):
                    self.render(commands=(value,))
                with self.assertRaises(ValueError):
                    state._json_array_cell((value,))
        self.assertEqual(state._json_array_cell(("a", "b")), '["a", "b"]')


def module_function_source(name: str) -> str:
    """The source text of one module-level function, by name."""
    source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
        encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"pipeline_auto_state has no function {name!r}")


#: THE SIGNATURE PHRASE OF EACH STRUCTURAL SCREEN, not a bare word out of it.
#: The first version of the tests below asserted `assertNotIn("canonical", ...)`
#: and `assertNotIn("marker", ...)`, and both fired on diagnoses that were
#: entirely correct: the canonical screen's own message lists "a second marker"
#: among the things it catches, and the attempt screen says "the canonical
#: spelling". A discriminator that appears inside the message it is supposed to
#: rule out discriminates nothing.
CANONICAL_DIAGNOSIS = "is not canonical"
REORDER_DIAGNOSIS = "missing, unknown, or reordered"
MARKER_DIAGNOSIS = "marker is missing or foreign"


class EvidenceDiagnosisTests(unittest.TestCase):
    """Two screens that refuse the same document are indistinguishable to an
    `assertRaises`. Each test below names the screen it means and asserts the
    other screen's signature phrase is ABSENT."""

    def test_each_signature_phrase_belongs_to_exactly_one_screen(self):
        """The discriminators, audited against the source of the function that
        raises them. A phrase two screens share cannot tell them apart, and a
        phrase no screen carries makes every `assertNotIn` below vacuously
        true. The counts are taken inside `parse_verification_evidence` rather
        than over the module, because Task 4's worker-result codec says the
        same three things about its own document and a module-wide count would
        be measuring that codec too.
        """
        parser = module_function_source("parse_verification_evidence")
        validator = module_function_source("_validate_verification_evidence")
        for phrase in (CANONICAL_DIAGNOSIS, REORDER_DIAGNOSIS,
                       MARKER_DIAGNOSIS):
            with self.subTest(phrase=phrase):
                self.assertEqual(parser.count(phrase), 1)
                self.assertNotIn(phrase, validator)
        self.assertEqual(
            len({CANONICAL_DIAGNOSIS, REORDER_DIAGNOSIS, MARKER_DIAGNOSIS}), 3)

    def test_a_reordered_document_is_diagnosed_as_reordered_not_as_bytes(self):
        """The field-order screen and the canonical screen both refuse a
        reordered record, and the canonical one names bytes rather than the
        rule that was broken. `test_rejects_reordered_fields` above cannot tell
        them apart; deleting the field-order screen leaves it green."""
        order = list(state.EVIDENCE_FIELDS)
        order[0], order[1] = order[1], order[0]
        message = refuse_evidence(self, evidence_text(order=order))
        self.assertIn(REORDER_DIAGNOSIS, message)
        self.assertNotIn(CANONICAL_DIAGNOSIS, message)

    def test_a_foreign_marker_is_diagnosed_as_the_marker_not_as_bytes(self):
        message = refuse_evidence(self, evidence_text().replace(
            state.EVIDENCE_MARKER, "<!-- pipeline-auto-worker-result/v1 -->"))
        self.assertIn(MARKER_DIAGNOSIS, message)
        self.assertNotIn(CANONICAL_DIAGNOSIS, message)

    def test_a_paragraph_contradicting_the_table_is_refused_as_not_canonical(self):
        """THE DEFECT THE BRIEF'S PARSER HAD NO SCREEN FOR, stated as the thing
        it lets through rather than as an abstraction.

        Every one of the nine fields reads back clean -- the field-order screen
        is satisfied, every value validates, the record says PASS -- and the
        document also says, in prose a search never looks at, that the suite
        failed. The diagnosis must be the canonical one, because that is the
        only screen standing between this file and a digest.
        """
        text = evidence_text() + (
            "\nThe suite actually failed. PASS was recorded to unblock the "
            "run.\n")
        message = refuse_evidence(self, text)
        self.assertIn(CANONICAL_DIAGNOSIS, message)
        self.assertNotIn(REORDER_DIAGNOSIS, message)
        self.assertNotIn(MARKER_DIAGNOSIS, message)

    def test_an_unknown_purpose_names_the_registered_purposes(self):
        """`remediation` and `anything` are refused by one screen, so the
        brief's two cases are one case. What distinguishes the purpose screen
        from every other is what it SAYS."""
        message = refuse_evidence(self, evidence_text(purpose="remediation"))
        self.assertIn("remediation", message)
        for purpose in state.EVIDENCE_PURPOSES:
            with self.subTest(purpose=purpose):
                self.assertIn(purpose, message)

    def test_a_non_pass_outcome_is_diagnosed_as_the_outcome_rule(self):
        for outcome in ("FAIL", "pass", "PASSED"):
            with self.subTest(outcome=outcome):
                message = refuse_evidence(self, evidence_text(outcome=outcome))
                self.assertIn("PASS", message)
                self.assertNotIn(CANONICAL_DIAGNOSIS, message)

    def test_a_subject_with_no_kind_is_diagnosed_as_the_kind_rule(self):
        """`/T1` satisfies the brief's check -- the delimiter is there and the
        tail is nonempty -- so a subject with no kind at all was legal."""
        message = refuse_evidence(self, evidence_text(subject="/T1"))
        self.assertIn("kind", message)
        for kind in state.EVIDENCE_SUBJECT_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(kind, message)

    def test_a_second_spelling_of_an_attempt_is_diagnosed_as_the_spelling(self):
        """`attempt-0001` matches the brief's `attempt-[0-9]{3,}` and is a
        second spelling of attempt one, in a record whose identity is the
        sha256 of its bytes."""
        message = refuse_evidence(self, evidence_text(attempt="attempt-0001"))
        self.assertIn("attempt-0001", message)
        self.assertNotIn(CANONICAL_DIAGNOSIS, message)

    def test_an_unbound_input_is_diagnosed_as_the_binding_rule(self):
        message = refuse_evidence(self, evidence_text(
            inputs=json_array(["docs/a.md"])))
        self.assertIn("inputs", message)
        self.assertIn(state._DIGEST_DELIMITER, message)

    def test_an_empty_inputs_array_is_refused_as_a_second_spelling_of_dash(self):
        message = refuse_evidence(self, evidence_text(inputs="[]"))
        self.assertIn("NONEMPTY", message)

    def test_a_malformed_command_suite_stays_inside_the_tracker_family(self):
        """`_parse_command_suite` raises `PlanMetadataError`, a SIBLING of
        `TrackerValidationError`. Unwrapped, a controller catching the tracker
        family around an evidence read sees nothing at all."""
        for cell in ("[]", "not-json", '["a", "a"]', '[1]', '{"a": 1}', '"a"'):
            with self.subTest(cell=cell):
                with self.assertRaises(state.TrackerValidationError):
                    state.parse_verification_evidence(evidence_text(commands=cell))
                with self.assertRaises(state.TrackerValidationError):
                    state.parse_verification_evidence(evidence_text(inputs=cell))


class EvidenceResolutionTests(TempDirTestCase):
    """`resolve_evidence`: one reference, one document, inside one family."""

    def setUp(self):
        super().setUp()
        self.run_dir = self.tmp / "run"
        self.repo_dir = self.tmp / "repo"
        self.repo_dir.mkdir()

    def resolve(self, reference):
        return state.resolve_evidence(self.run_dir, self.repo_dir, reference)

    def refusal(self, reference):
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.resolve(reference)
        return caught.exception

    def test_the_run_directory_is_searched_before_the_repository(self):
        run_digest = write_evidence(self.run_dir / "evidence", subject="task/T1")
        write_evidence(self.repo_dir / "evidence", subject="task/T2")
        record = self.resolve(f"evidence/T1.md#sha256={run_digest}")
        self.assertEqual(record["subject"], "task/T1")

    def test_the_repository_copy_is_used_when_the_run_has_none(self):
        digest = write_evidence(self.repo_dir / "evidence", subject="task/T2")
        self.assertEqual(
            self.resolve(f"evidence/T1.md#sha256={digest}")["subject"],
            "task/T2")

    def test_a_mismatching_run_copy_is_not_rescued_by_a_matching_repo_copy(self):
        """THE FAIL-OPEN A `continue` ON MISMATCH WOULD OPEN. Treating a digest
        mismatch as "not the file I meant" reads as trying harder, and it lets
        whoever can write the repository copy choose which record replaces a
        run copy that does not hash right. One reference names one document."""
        write_evidence(self.run_dir / "evidence", subject="task/T1")
        digest = write_evidence(self.repo_dir / "evidence", subject="task/T2")
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.resolve(f"evidence/T1.md#sha256={digest}")
        self.assertIn("digest", str(caught.exception))

    def test_a_digest_mismatch_names_the_reference_and_changes_nothing(self):
        write_evidence(self.run_dir / "evidence")
        path = self.run_dir / "evidence" / "T1.md"
        before = path.read_bytes()
        with self.assertRaises(state.TrackerValidationError):
            self.resolve(f"evidence/T1.md#sha256={'c' * 64}")
        self.assertEqual(path.read_bytes(), before)

    # -- the door, and the split between absence and corruption -----------

    @contextlib.contextmanager
    def _deadline(self, seconds: int):
        """Turn a hang into a NAMED failure, where the platform allows it.

        A hang is not a test failure. It is a suite that never finishes and a
        CI job killed with nothing to read, so a regression in the door below
        has to arrive as this assertion and not as a timeout somebody bisects.
        """
        if not hasattr(signal, "SIGALRM"):  # pragma: no cover - POSIX only
            yield
            return

        def expire(signum, frame):
            raise AssertionError(
                "resolve_evidence blocked: the read reached a FIFO, which is "
                "the deadlock _require_regular_file exists to prevent -- and "
                "it happens under the run lock, so the run does not fail, it "
                "stops")

        previous = signal.signal(signal.SIGALRM, expire)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs only")
    def test_a_fifo_under_a_search_root_is_refused_before_the_open(self):
        """THE DEADLOCK, AND IT IS WORSE THAN THE BRIEF'S FORM. `is_file()` is
        false for a FIFO, so the brief's `is_file()`-then-read merely SKIPPED
        one; a bare `read_bytes` inside `except OSError: continue` BLOCKS in
        `open` until a writer that is never coming. Measured before the fix, on
        a daemon thread with a five-second join: still alive, holding whatever
        lock the caller holds, with no diagnostic and no timeout.

        The repository copy below is valid and its digest is the one asked for,
        so this also pins the second half: a FIFO is corruption, and corruption
        does not fall through to the other root.
        """
        (self.run_dir / "evidence").mkdir(parents=True)
        os.mkfifo(self.run_dir / "evidence" / "T1.md")
        self.assertFalse((self.run_dir / "evidence" / "T1.md").is_file())
        self.assertTrue(os.path.lexists(self.run_dir / "evidence" / "T1.md"))
        digest = write_evidence(self.repo_dir / "evidence")
        with self._deadline(5):
            exception = self.refusal(f"evidence/T1.md#sha256={digest}")
        self.assertIn("carries and cannot be read", str(exception))
        self.assertIsInstance(exception.__cause__, state.QuorumError)
        self.assertNotIsInstance(exception, state.EvidenceMissing)

    def test_a_name_that_is_not_a_regular_file_is_corruption_never_absence(self):
        """`is_file()` NEVER means "there is nothing here". Each shape below
        exists under the run directory and cannot be read, and for each one the
        repository copy is VALID and hashes to the digest being asked for -- so
        a run that folded these into absence would resolve the repository copy
        and report a clean PASS. That is the fail-open, and it is the same one
        `_require_regular_file` was written for two tasks earlier."""
        shapes = [
            ("a directory", lambda p: p.mkdir(parents=True)),
            ("a dangling symlink",
             lambda p: p.symlink_to(self.tmp / "nowhere-at-all")),
            ("a symlink loop", lambda p: os.symlink(p, p)),
        ]
        digest = write_evidence(self.repo_dir / "evidence")
        for label, make in shapes:
            with self.subTest(shape=label):
                run = self.run_dir / label.replace(" ", "-")
                (run / "evidence").mkdir(parents=True)
                make(run / "evidence" / "T1.md")
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.resolve_evidence(run, self.repo_dir,
                                           f"evidence/T1.md#sha256={digest}")
                self.assertIn("carries and cannot be read",
                              str(caught.exception))
                self.assertNotIsInstance(caught.exception,
                                         state.EvidenceMissing)

    def test_an_unreadable_run_copy_is_corruption_never_absence(self):
        """THE CASE THE DOOR ALONE DOES NOT CLOSE, and the reason the residual
        `OSError` is split rather than swallowed. `is_file()` is TRUE for a
        mode-000 regular file -- `stat` needs `+x` on the parent, not `+r` on
        the file -- so `_require_regular_file` passes it and the read raises
        `PermissionError`. Measured against an undifferentiated
        `except OSError: continue`: the run copy went unread and the REPOSITORY
        copy was resolved silently, which defeats "the run directory is
        searched first and a mismatch stops there" by making the run copy
        unreadable instead of mismatching."""
        run_digest = write_evidence(self.run_dir / "evidence", subject="task/T1")
        repo_digest = write_evidence(self.repo_dir / "evidence",
                                     subject="task/T2")
        self.assertNotEqual(run_digest, repo_digest)
        path = self.run_dir / "evidence" / "T1.md"
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o644)
        if os.access(path, os.R_OK):  # pragma: no cover - root reads anything
            self.skipTest("this user can read a mode-000 file")
        self.assertTrue(path.is_file())
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.resolve(f"evidence/T1.md#sha256={repo_digest}")
        self.assertIn("cannot read", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, OSError)

    #: `is_file()` ANSWERS "NOT A REGULAR FILE" AND IT ALSO RAISES, and the
    #: three tests below are about the second half. CPython swallows only
    #: `pathlib._IGNORED_ERRNOS` -- measured on this interpreter as
    #: `(ENOENT, ENOTDIR, EBADF, ELOOP)` -- and re-raises every other `OSError`
    #: out of `_require_regular_file`. Adding the door to `resolve_evidence`
    #: under an `except QuorumError` therefore opened a NEW escape in the
    #: commit that closed the FIFO one: measured at that commit, a 312-character
    #: reference left the family as `OSError [Errno 36] File name too long` and
    #: a `run_dir/evidence` at mode 000 as a raw `PermissionError`, and BOTH
    #: were in-family one commit earlier. Neither needs a permissions trick to
    #: be interesting: the first is a pure argument that `_cell_safe` accepts.
    def _door_inputs(self):
        """`(label, make)` for the two spellings `is_file()` raises on.

        `make` prepares one run directory and returns the REFERENCE to ask for,
        so the two cases can be driven through `resolve_evidence`, through
        `_require_regular_file` directly, and through `_plan_text` without
        three copies of the setup.
        """
        def a_name_past_name_max(run):
            (run / "evidence").mkdir(parents=True)
            relative = "evidence/" + "n" * 300 + ".md"
            self.assertTrue(state._cell_safe(relative),
                            "the spelling screen accepts this reference, so it "
                            "is the door and nothing else that meets it")
            return relative

        def a_parent_this_run_may_not_search(run):
            (run / "evidence").mkdir(parents=True)
            (run / "evidence" / "T1.md").write_text("x", encoding="utf-8")
            os.chmod(run / "evidence", 0o000)
            self.addCleanup(os.chmod, run / "evidence", 0o755)
            return "evidence/T1.md"

        return (("a name past NAME_MAX", a_name_past_name_max),
                ("a parent this run may not search",
                 a_parent_this_run_may_not_search))

    def test_a_name_the_door_cannot_examine_stays_inside_the_family(self):
        """THE ESCAPE THE DOOR ITSELF OPENED, asked through `resolve_evidence`.

        The repository copy below is VALID and hashes to the digest asked for,
        so a run that folded either of these into absence would resolve it and
        report a clean PASS -- and what actually happened before the split was
        worse than that: the `OSError` left `TrackerError` altogether, so a
        controller holding `except TrackerError` around an evidence read died
        on a reference nobody would look at twice.
        """
        digest = write_evidence(self.repo_dir / "evidence")
        for label, make in self._door_inputs():
            with self.subTest(door=label):
                run = self.run_dir / label.replace(" ", "-")
                relative = make(run)
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.resolve_evidence(run, self.repo_dir,
                                           f"{relative}#sha256={digest}")
                self.assertIn("cannot examine", str(caught.exception))
                self.assertNotIsInstance(caught.exception,
                                         state.EvidenceMissing)
                cause = caught.exception.__cause__
                self.assertIsInstance(cause, state.QuorumError)
                self.assertIsInstance(cause.__cause__, OSError)

    def test_the_door_itself_keeps_every_caller_inside_the_family(self):
        """PINNED WHERE THE DEFECT LIVES, not where it was found.

        `_require_regular_file` has EIGHT call sites -- counted from the AST,
        not remembered: `_question_record`, `payload_digest`, `_read_json`,
        `_response_record`, `_plan_text`, `resolve_evidence`, `_ref_text` and
        `_published_result_bytes` -- and every one of them inherited this
        hole. It was six when this test was written, seven when `_ref_text`
        arrived and eight when Task 9 added `_published_result_bytes`, each
        inheriting the wrap without asking for it: the count is re-enumerated
        rather than carried forward, because a remembered count is the reason
        the door was nearly wrapped at one caller instead of at itself. A test that only drove `resolve_evidence`
        would license a fix scoped to `resolve_evidence`, which is the shape of
        defect this build has already been bitten by. So the door is asked
        directly, and `_plan_text` is asked alongside it as the second caller
        that was measurably escaping.
        """
        for label, make in self._door_inputs():
            with self.subTest(door=label):
                run = self.tmp / ("door-" + label.replace(" ", "-"))
                relative = make(run)
                path = run / relative
                with self.assertRaises(state.QuorumSchemaInvalid) as caught:
                    state._require_regular_file(path, "a probe")
                self.assertIsInstance(caught.exception.__cause__, OSError)
                with self.assertRaises(state.PlanMetadataError) as plan:
                    state._plan_text(str(path))
                self.assertIsInstance(plan.exception, state.TrackerError)

    def test_the_door_refuses_a_nul_bearing_name_instead_of_reporting_it_absent(self):
        """THE SECOND THING `is_file()` ANSWERS FALSELY, and the standing rule
        names this function as where it is refused.

        A NUL byte is not an errno. `os.stat('\x00x')` raises `ValueError`,
        which is not an `OSError` -- but `pathlib` swallows it, so measured on
        this interpreter `Path('\x00x')` answers `False` to `is_file`,
        `is_dir`, `exists`, `is_symlink` and `is_fifo`, and
        `os.path.lexists` -- this door's own fall-through -- answers `False`
        too. Both halves of the door therefore said ABSENT for a name that
        had not been examined at all, and the caller's own read then raised a
        bare `ValueError` outside the family. Measured before the screen:
        `_read_json` and `payload_digest` both escaped that way.

        An `except ValueError` here would have been an UNREACHABLE screen --
        the same shape this module already reverted at `_git_store` -- so the
        door asks the question instead.
        """
        probe = pathlib.Path("\x00x")
        self.assertFalse(probe.is_file())
        self.assertFalse(probe.is_dir())
        self.assertFalse(os.path.lexists(probe))
        with self.assertRaises(state.QuorumSchemaInvalid) as caught:
            state._require_regular_file(probe, "a probe")
        self.assertIn("NUL byte", str(caught.exception))
        self.assertIsInstance(caught.exception, state.TrackerError)

    def test_every_door_caller_is_enumerated_and_none_escapes_on_a_nul(self):
        """THE CALLER SWEEP, and the count comes out of the AST.

        "Widened at the single door" is only true if the door is the door, so
        the eight callers are enumerated from the module's own syntax tree and
        then each is DRIVEN with a NUL-bearing name. `_question_record`,
        `_response_record`, `resolve_evidence` and `_published_result_bytes`
        are reached through the run directory or the result they build their
        path from -- the last is driven through its public caller
        `publish_worker_result`, which is the only way a worker reaches it --
        and the other four take the name more directly. Every one stays
        inside `TrackerError`.
        """
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        callers = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "_require_regular_file"):
                    callers.add(node.name)
        self.assertEqual(callers, {
            "_question_record", "payload_digest", "_read_json",
            "_response_record", "_plan_text", "resolve_evidence",
            "_ref_text", "_published_result_bytes"})

        nul = "\x00rd"
        probe = pathlib.Path("\x00x")
        result = {"run_id": "run-1", "task_id": "T1", "attempt": 1,
                  "owner": "w-1", "kind": "source", "status": "complete"}
        drives = {
            "_question_record": lambda: state._question_record(nul, "q1"),
            "payload_digest": lambda: state.payload_digest("q1", run_dir=nul),
            "_read_json": lambda: state._read_json(probe, "a probe"),
            "_response_record": lambda: state._response_record(
                probe, "q1", "w-1", 1),
            "_plan_text": lambda: state._plan_text("\x00plan.md"),
            "resolve_evidence": lambda: state.resolve_evidence(
                nul, nul, f"evidence/T1.md#sha256={'a' * 64}"),
            "_ref_text": lambda: state._ref_text(probe, "a probe"),
            "_published_result_bytes": lambda: state.publish_worker_result(
                nul, result=result),
        }
        self.assertEqual(set(drives), callers)
        for name, drive in sorted(drives.items()):
            with self.subTest(caller=name):
                with self.assertRaises(state.TrackerError):
                    drive()

    def test_a_name_that_is_not_there_is_still_answered_by_falling_through(self):
        """THE HALF THE SPLIT MUST NOT BREAK. `FileNotFoundError` and
        `NotADirectoryError` are the two spellings of "not there", and the door
        answers neither -- it returns silently and lets the caller's own read
        report absence as that caller has always reported it. A door that
        raised on them would turn every missing run copy into corruption and
        stop the search at the first root."""
        for label, prepare in (
                ("nothing at this name", lambda run: None),
                ("a regular file where the directory should be",
                 lambda run: (run.mkdir(parents=True),
                              (run / "evidence").write_text("x", "utf-8")))):
            with self.subTest(absence=label):
                run = self.tmp / ("absent-" + label.replace(" ", "-"))
                prepare(run)
                self.assertIsNone(
                    state._require_regular_file(run / "evidence" / "T1.md",
                                                "a probe"))

    def test_the_doors_absence_arm_fires_if_the_stdlib_stops_swallowing(self):
        """THE ARM MUTATION PROVES EQUIVALENT, VISITED IN THE WORLD WHERE IT
        MATTERS -- and this test exists because the one the door's docstring
        used to cite does not discriminate.

        `except (FileNotFoundError, NotADirectoryError): return` is unreachable
        while `pathlib._IGNORED_ERRNOS` holds ENOENT and ENOTDIR, and it is
        unreachable BY CONSTRUCTION rather than by coincidence: CPython selects
        those two classes FROM those two errnos, so any such exception `os.stat`
        can raise is already one `is_file()` swallows, on every platform
        including Windows, where the winerror is translated to an errno before
        the subclass is chosen. Delete the arm and the whole suite stays green
        -- which is why `test_a_name_that_is_not_there_is_still_answered_by_
        falling_through` cannot be the arm's guarantee: it drives REAL absence,
        `is_file()` answers `False`, and the arm is never entered.

        So the suite visits the hedged world instead. With the ignore set
        narrowed, absence reaches the arm as a raise; the arm answers it by
        falling through, exactly as `False` did. Delete the arm and this fails,
        because the `except OSError` below it turns every absent file under a
        run directory into corruption at all seven call sites at once.
        """
        with mock.patch.object(pathlib, "_IGNORED_ERRNOS",
                               (errno.EBADF, errno.ELOOP)):
            self.assertIsNone(state._require_regular_file(
                self.tmp / "nowhere" / "T1.md", "a probe"))

    def test_a_file_that_vanishes_after_the_door_is_still_absence(self):
        """THE RESIDUAL RACE, AND THE ONE `OSError` THAT STILL KEEPS LOOKING.
        Asking the shape before the open re-opens the time-of-check/time-of-use
        gap the shipped code had closed by not checking at all, and the loser
        is a `FileNotFoundError` out of the read. That is absence -- the run
        copy is not there any more -- so the repository copy answers, exactly
        as it does for a run copy that was never written.

        The race is not hoped for, it is CAUSED: the door is wrapped so the run
        copy is unlinked between the `stat` and the `open`. A test that merely
        omitted the file would pin the door's own `FileNotFoundError` and not
        the read's, and the two arrive from different lines.
        """
        write_evidence(self.run_dir / "evidence", subject="task/T1")
        digest = write_evidence(self.repo_dir / "evidence", subject="task/T2")
        original = state._require_regular_file
        raced = []

        def unlink_between_the_stat_and_the_open(path, what):
            original(path, what)
            if path.is_file() and not raced:
                raced.append(path)
                path.unlink()

        state._require_regular_file = unlink_between_the_stat_and_the_open
        self.addCleanup(setattr, state, "_require_regular_file", original)
        record = self.resolve(f"evidence/T1.md#sha256={digest}")
        self.assertEqual(raced, [self.run_dir / "evidence" / "T1.md"])
        self.assertEqual(record["subject"], "task/T2")

    def test_a_matching_file_that_is_not_utf8_stays_inside_the_family(self):
        """`UnicodeDecodeError` is a `ValueError`, outside `TrackerError`. The
        brief decoded the bytes bare."""
        path = self.run_dir / "evidence" / "T1.md"
        path.parent.mkdir(parents=True)
        content = state.EVIDENCE_MARKER.encode("utf-8") + b"\n\xff\xfe\n"
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.resolve(f"evidence/T1.md#sha256={digest}")
        self.assertIn("UTF-8", str(caught.exception))

    def test_a_missing_file_names_what_it_looked_for(self):
        digest = write_evidence(self.run_dir / "evidence")
        message = str(self.refusal(
            f"evidence/absent.md#sha256={digest}"))
        self.assertIn("evidence/absent.md", message)

    def test_absence_has_its_own_class_and_corruption_does_not(self):
        """THREE OUTCOMES, AND A CALLER MUST BE ABLE TO TELL THEM APART.

        `resolve_evidence` resolves, or reports ABSENT, or reports CORRUPT, and
        the three shipped as one class with `__cause__` absent on the two that
        matter -- so the only thing left to branch on was a substring of a
        diagnostic, which is prose the next task is free to reword. The task
        that consumes this codec has to branch on it: "no evidence was ever
        published" is work still to do, and "the evidence that was published
        cannot be read" is damaged durable state.
        """
        repo_digest = write_evidence(self.repo_dir / "evidence")
        with self.assertRaises(state.EvidenceMissing):
            self.resolve(f"evidence/absent.md#sha256={repo_digest}")

        path = self.run_dir / "evidence" / "T1.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not the bytes that hash to that")
        corruptions = {
            "a digest mismatch": f"evidence/T1.md#sha256={repo_digest}",
        }
        content = state.EVIDENCE_MARKER.encode("utf-8") + b"\n\xff\xfe\n"
        (self.run_dir / "evidence" / "T2.md").write_bytes(content)
        corruptions["bytes that are not UTF-8"] = (
            f"evidence/T2.md#sha256={hashlib.sha256(content).hexdigest()}")
        for label, reference in corruptions.items():
            with self.subTest(corruption=label):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    self.resolve(reference)
                self.assertNotIsInstance(caught.exception,
                                         state.EvidenceMissing)

    def test_the_new_class_is_caught_by_every_handler_already_written(self):
        """THE POINT OF SUBCLASSING RATHER THAN ADDING A SIBLING. `EvidenceMissing`
        ADDS a distinction; it must not move a stop out of the reach of code
        that already catches this module's families. Asserted by CATCHING it,
        not by reading the class statement: an `__mro__` assertion would still
        pass if the raise site had been given some other class."""
        digest = write_evidence(self.repo_dir / "evidence")
        reference = f"evidence/absent.md#sha256={digest}"
        for family in (state.TrackerError, state.TrackerValidationError):
            with self.subTest(handler=family.__name__):
                try:
                    self.resolve(reference)
                except family as caught:
                    self.assertIsInstance(caught, state.EvidenceMissing)
                else:  # pragma: no cover - the raise above is unconditional
                    self.fail(f"{family.__name__} did not catch it")
        self.assertTrue(issubclass(state.EvidenceMissing,
                                   state.TrackerValidationError))

    def test_an_unbound_or_short_reference_is_refused_before_any_read(self):
        write_evidence(self.run_dir / "evidence")
        for reference in ("evidence/T1.md", f"evidence/T1.md#sha256={'a' * 8}",
                          f"evidence/T1.md#sha256={'A' * 64}",
                          f"../T1.md#sha256={DIGEST}",
                          f"/abs/T1.md#sha256={DIGEST}",
                          f"evidence/../T1.md#sha256={DIGEST}", "", 5, None):
            with self.subTest(reference=reference):
                with self.assertRaises(state.TrackerValidationError):
                    self.resolve(reference)

    def test_a_search_root_that_is_not_a_path_stays_inside_the_family(self):
        """`Path(None)` is a `TypeError`, and a controller that wrapped an
        evidence read in `except TrackerError` would not catch it."""
        for run_dir, repo_dir in ((None, self.repo_dir), (self.run_dir, 5),
                                  (object(), self.repo_dir),
                                  (b"/tmp", self.repo_dir)):
            with self.subTest(run_dir=type(run_dir).__name__,
                              repo_dir=type(repo_dir).__name__):
                with self.assertRaises(state.TrackerValidationError):
                    state.resolve_evidence(
                        run_dir, repo_dir, f"evidence/T1.md#sha256={DIGEST}")

    def test_a_search_root_whose_SPELLING_is_unusable_stays_in_the_family(self):
        """A PATH CORPUS IS NOT A TYPE CORPUS, and the type check is where the
        first version of this test stopped. Measured against the type-check-only
        form, on this Python: a NUL in either root reached the syscall as
        `ValueError: embedded null byte`, from outside `TrackerError`, and it
        got there SILENTLY -- `is_file()` and `os.path.lexists` are both False
        for that spelling, so no door upstream could have seen it. `_cell_safe`
        before `Path()` is the same screen `_plan_text` puts on a plan path.

        THE TWO SURROGATES ARE HERE FOR OPPOSITE REASONS, and an earlier
        revision of this test carried only the first of them -- the one
        surrogate that cannot falsify the claim the docstring made. Measured at
        the `read_bytes` call site, filesystem encoding `utf-8`, error handler
        `surrogateescape`:

        * `\udcff` is INSIDE `U+DC80`-`U+DCFF`, the window `surrogateescape`
          uses to spell a real filename byte. It reaches the syscall as an
          ordinary `FileNotFoundError` -- a file that can exist and merely does
          not -- so it does NOT escape the family even with no screen at all.
          It is here to show the screen refuses a spelling that is harmless,
          which is the screen's cost and is stated rather than hidden.
        * `\ud800` is OUTSIDE that window. The encoder refuses it and raises
          `UnicodeEncodeError`, a `ValueError`, from outside `TrackerError` --
          measured against the type-check-only form, and so do `\udc00` and
          `\udfff`. It is here because it is the half that escapes, and a test
          carrying only `\udcff` pinned a claim about surrogates from the one
          surrogate that supports it.

        That asymmetry is exactly why the ENCODER is asked per spelling
        (`_survives_the_encoder`) instead of a range being remembered.
        """
        roots = (str(self.tmp) + "/\x00run", str(self.tmp) + "/\udcffrun",
                 str(self.tmp) + "/\ud800run", str(self.tmp) + "/a|b",
                 str(self.tmp) + "/run ", "")
        reference = f"evidence/T1.md#sha256={DIGEST}"
        for spelling in roots:
            with self.subTest(spelling=spelling.encode(
                    "utf-8", "backslashreplace")):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.resolve_evidence(spelling, self.repo_dir, reference)
                self.assertIn("run_dir", str(caught.exception))
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.resolve_evidence(self.run_dir, spelling, reference)
                self.assertIn("repo_dir", str(caught.exception))

    def test_a_resolved_record_is_the_whole_validated_record(self):
        digest = write_evidence(self.run_dir / "evidence")
        record = self.resolve(f"evidence/T1.md#sha256={digest}")
        self.assertEqual(sorted(record), sorted(state.EVIDENCE_FIELDS))
        self.assertEqual(record, evidence_record())

    def test_a_file_that_hashes_right_and_is_not_canonical_is_still_refused(self):
        """The digest binds the bytes; it says nothing about what they mean. A
        forged PASS with a paragraph under the table hashes perfectly."""
        path = self.run_dir / "evidence" / "T1.md"
        path.parent.mkdir(parents=True)
        content = evidence_text() + "\nThe suite actually failed.\n"
        path.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        message = str(self.refusal(
            f"evidence/T1.md#sha256={digest}"))
        self.assertIn("canonical", message)


class VerificationEvidenceTemplateTests(unittest.TestCase):

    def setUp(self):
        self.template = (
            Path(state.__file__).resolve().parents[1] / "templates"
            / "verification-evidence.md"
        ).read_text(encoding="utf-8")

    def template_rows(self) -> list:
        return [state._split_row(line) for line in self.template.splitlines()
                if line.startswith("| ")
                and len(state._split_row(line)) == 2]

    def test_the_table_names_exactly_the_codec_fields_in_order(self):
        """`assertIn(f"| {field} | ", template)` -- the brief's check -- is
        satisfied by a template carrying three fields the codec does not have,
        and by one whose rows are in any order at all."""
        names = [row[0] for row in self.template_rows()
                 if row[0] not in (state._RESULT_HEADER[0], state._TABLE_RULE)]
        self.assertEqual(names, list(state.EVIDENCE_FIELDS))

    def test_the_first_two_lines_are_the_marker_and_the_title(self):
        self.assertEqual(self.template.splitlines()[:2],
                         [state.EVIDENCE_MARKER, state.EVIDENCE_TITLE])

    def test_the_marker_appears_exactly_once(self):
        self.assertEqual(self.template.count(state.EVIDENCE_MARKER), 1)

    def test_every_purpose_and_every_subject_kind_is_named(self):
        for value in (*state.EVIDENCE_PURPOSES, *state.EVIDENCE_SUBJECT_KINDS,
                      state.EVIDENCE_OUTCOME, state.EVIDENCE_NO_ATTEMPT):
            with self.subTest(value=value):
                self.assertIn(value, self.template)

    def test_the_one_legal_outcome_and_the_binding_rule_are_both_stated(self):
        for phrase in ("exactly one legal value", "sha256", "--no-ff",
                       "REGISTERED"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.template)

    def test_the_template_is_not_itself_a_parseable_record(self):
        """A template that validated would be a PASS for a suite nobody ran,
        sitting in the repository with a digest anything could cite."""
        with self.assertRaises(state.TrackerValidationError):
            state.parse_verification_evidence(self.template)

    def test_the_template_carries_no_absolute_home_path(self):
        self.assertNotIn("/home/", self.template)


class EvidenceModuleBoundaryTests(unittest.TestCase):
    """What Task 5 must NOT have done to the module it extends."""

    def test_the_attempt_grammar_is_still_task_fours_round_trip(self):
        """The brief redefined `_ATTEMPT_TOKEN` as `re.compile(r"attempt-[0-9]
        {3,}\\Z")`. It already exists, so the module-level assignment would have
        rebound the global for every existing caller -- and the pattern is
        WEAKER: it accepts `attempt-0001`, a second spelling of attempt one."""
        self.assertIsInstance(state._ATTEMPT_TOKEN, state._AttemptToken)
        self.assertTrue(state._ATTEMPT_TOKEN.fullmatch("attempt-001"))
        for token in ("attempt-0001", "attempt-000", "attempt-01",
                      "attempt-" + "9" * 5000):
            with self.subTest(token=token):
                self.assertFalse(state._ATTEMPT_TOKEN.fullmatch(token))

    def test_hashlib_is_imported_once_and_nothing_new_was_imported(self):
        """The brief appended `import hashlib` beside the new code. It is
        already imported at the top of the module, and a second module-level
        `import` is a second binding of the name."""
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        counts = module_bindings(ast.parse(source).body)
        self.assertEqual(counts["hashlib"], 1)
        self.assertEqual(
            sorted(name for name, count in counts.items() if count > 1), [])
        self.assertNotIn("re.compile(", source)
        self.assertIsNone(sys.modules["pipeline_auto_state"].__dict__.get("re"))

    def test_the_pinned_constants_are_the_master_plans_own(self):
        self.assertEqual(state.EVIDENCE_MARKER,
                         "<!-- pipeline-auto-verification-evidence/v1 -->")
        self.assertEqual(state.EVIDENCE_PURPOSES,
                         ("task-test", "task-integration", "phase"))
        self.assertEqual(state.EVIDENCE_FIELDS, (
            "purpose", "run_id", "subject", "attempt", "code_state", "outcome",
            "commands", "environment", "inputs"))

    def test_the_two_record_codecs_do_not_share_a_marker(self):
        """A worker result and an evidence record are both `| Field | Value |`
        tables. The marker is the whole of what tells them apart, so each codec
        must refuse the other's document."""
        result_text = state.render_worker_result(worker_result())
        with self.assertRaises(state.TrackerValidationError):
            state.parse_verification_evidence(result_text)
        with self.assertRaises(state.TrackerValidationError):
            state.parse_worker_result(evidence_text())

    def test_the_renderer_uses_p02s_table_writer(self):
        """A second `"| " + " | ".join(...)` beside `_render_table` is a second
        answer to what a rendered row looks like, and the canonical screen
        compares bytes."""
        self.assertEqual(
            state.render_verification_evidence(evidence_record()).splitlines()[3:5],
            state._render_table(state._RESULT_HEADER, ())[:2])

    def test_the_codec_raises_only_tracker_validation_errors(self):
        """Every malformed shape this codec can be handed comes back inside the
        family a controller catches. A `TypeError` or an `AttributeError` here
        is a run that dies on a worker's typo instead of refusing it."""
        hostile = (
            None, [], "PASS", 3, (),
            evidence_record(commands=EVIDENCE_COMMAND),
            evidence_record(commands=iter((EVIDENCE_COMMAND,))),
            evidence_record(commands=(1,)),
            evidence_record(commands=({"a": 1},)),
            evidence_record(inputs=INPUT_REF),
            evidence_record(inputs=(5,)),
            evidence_record(inputs=([INPUT_REF],)),
            evidence_record(code_state=5),
            evidence_record(purpose=None),
            evidence_record(subject=object()),
            evidence_record(attempt=1),
            evidence_record(outcome=True),
            evidence_record(run_id=b"run-1"),
            evidence_record(environment=None),
            dict(evidence_record(), extra="x"),
            {field: EVIDENCE_VALUES[field]
             for field in state.EVIDENCE_FIELDS[:-1]},
        )
        for record in hostile:
            with self.subTest(record=type(record).__name__):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_verification_evidence(record)
        for text in (None, b"", 7, [], "", state.EVIDENCE_MARKER,
                     state.EVIDENCE_MARKER + "\n| a |\n",
                     state.EVIDENCE_MARKER + "\n| purpose | task-test |\n"):
            with self.subTest(text=repr(text)[:40]):
                with self.assertRaises(state.TrackerValidationError):
                    state.parse_verification_evidence(text)



# --------------------------------------------------------------------------
# Task 6: the run harness -- reused by tasks 6 through 12.
#
# `subprocess` is imported HERE and not in the module. The tests drive a real
# git repository because a fake one would prove nothing about the ref store
# the module reads; the module itself may not import `subprocess` at all --
# `ALLOWED_IMPORTS` is twelve names and command execution is the single
# capability that boundary most exists to withhold.
# --------------------------------------------------------------------------

#: A legal payload/context digest for a quorum row. Sixty-four lowercase hex
#: characters, and deliberately NOT a digest of anything: `_validate_quorum`
#: checks the SHAPE, and a value computed by the module under test would let
#: the fixture agree with the code by construction.
FAKE_DIGEST = "5e" * 32
OTHER_DIGEST = "a7" * 32
# --- the block a `[?]` row names, and it is REAL ---------------------------
#
# The constant this replaces was `quorum:docs/q.md#sha256=3c...`: a path no
# fixture ever wrote and a digest of nothing. `_validate_tasks` asks only that
# the cell is not `-`, so it passed -- and the consequence was that NO FIXTURE
# IN THE SUITE HELD A REAL QID, so a qid comparison that was subtly wrong could
# not have been caught by anything here. Everything below is derived: the qid
# by the committed `derive_qid`, the digest over the bytes actually written,
# and the path is where `_question_record` looks.

#: The question a blocked task is blocked on, and the axis it opens.
BLOCK_QUESTION = "Which serialiser does T1 use for its checkpoint payload?"
BLOCK_AXIS = "checkpoint-serialiser"
#: DERIVED, never typed. `settle_quorum` mints a quorum decision id as
#: `"Q-" + qid`, so this one string is what binds a grant to this block.
BLOCK_QID = state.derive_qid(BLOCK_QUESTION, BLOCK_AXIS)
QUORUM_GRANT = f"Q-{BLOCK_QID}"


def question_record_text(qid: str, question: str, axis: str,
                         *, blocks: str = "T1") -> str:
    """One publishable question record, in the grammar `parse_question` reads.

    Modelled on `tests/fixtures/quorum/question-record.md` rather than reading
    it: that fixture is pinned byte-for-byte by P03's suite as the record ITS
    cases reason about, and a second reader of it here would couple two
    unrelated sets of cases through one file.
    """
    return "\n".join((
        "<!-- pipeline-auto/v1 -->",
        "",
        f"## Q-{qid} — the checkpoint serialiser",
        "",
        f"- **Question:** {question}",
        f"- **Axis:** {axis}",
        "- **Phase:** P04",
        f"- **Blocks:** {blocks}",
        "- **Raiser:** impl-1",
        "- **Options supplied:** yes",
        "- **Options:** json, msgpack",
        "- **Candidate answers:** json, because it is already imported",
        "- **Recommendation:** json",
        "- **Reading roots:** spec=docs/superpowers/specs/design.md, "
        "intent-brief=docs/superpowers/runs/run-1/intent-brief.md, repo=., "
        "tests=tests, phase-plan=docs/superpowers/plans/phase-04.md",
        "- **Owners:** brain-1, brain-2, brain-3",
    )) + "\n"


QUESTION_RECORD_TEXT = question_record_text(BLOCK_QID, BLOCK_QUESTION, BLOCK_AXIS)
#: Every run this harness builds lives at `docs/superpowers/runs/run-1`, so the
#: repo-root-relative path of the published record is a constant and the digest
#: over its bytes is one too.
QUESTION_RECORD_PATH = (
    f"docs/superpowers/runs/run-1/quorum/{BLOCK_QID}/question.md")
#: Task 10's ruled form, which this harness is now the specification of:
#: `quorum:<qid>@<path>#sha256=<digest>` -- the qid for the binding, the
#: digest-bound path for the audit trail.
QUESTION_REF = (
    f"quorum:{BLOCK_QID}@{QUESTION_RECORD_PATH}"
    f"#sha256={hashlib.sha256(QUESTION_RECORD_TEXT.encode('utf-8')).hexdigest()}")

#: The OTHER arm. A halt opened no quorum, so there is no question record and
#: no qid; the grant asserts this string back and must be a human's.
HALT_BLOCKER = "the release host is unreachable and no machine can settle it"
HALT_REF = f"halt:{HALT_BLOCKER}"
HALT_GRANT = "H-001"


def publish_question_record(run_dir, *, text: str = QUESTION_RECORD_TEXT,
                            qid: str = BLOCK_QID) -> str:
    """Write the record where `_question_record` reads it; return its cell."""
    path = Path(run_dir) / "quorum" / qid / "question.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return QUESTION_REF


def _alarm(signum, frame):
    """SIGALRM handler for the bounded FIFO probes: blocking is a failure."""
    raise AssertionError("the call blocked on a FIFO under the run lock")


def git(repo, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *args),
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def make_repo(root) -> Path:
    repo = Path(root) / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    (repo / "src").mkdir()
    (repo / "src" / "seed.py").write_text("seed = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "seed")
    #: `target` is moved ONE COMMIT PAST the run's base_commit on purpose. The
    #: reservation baseline is the tip of the target branch AT RESERVATION, and
    #: a fixture where the two coincide cannot tell that rule from
    #: "the baseline is base_commit" -- which is the F3 shape arriving through
    #: a fixture rather than through the code.
    (repo / "src" / "seed.py").write_text("seed = 2\n", encoding="utf-8")
    git(repo, "commit", "-qam", "second")
    git(repo, "branch", "-f", "target", "HEAD")
    git(repo, "checkout", "-q", "main")
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    return repo


def make_run(root, tasks_body: str, *, worker_limit: int = 4, import_plan: bool = True):
    """Return (repo, run_dir, phase_plan).

    `initialize_run` is P02's and takes no artifact-reference arguments: it
    writes `decisions`, `findings` and `repo_root` itself and leaves
    `phase_plans` at `-`, because stage 07 is what discovers a phase plan.
    `import_phase_plan` -- P04's -- is what records the path, in the same
    transition that appends the phase row it indexes against.
    """
    repo = make_repo(root)
    run_dir = repo / "docs" / "superpowers" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    plan = write_phase_plan(run_dir, tasks_body)
    state.initialize_run(
        run_dir, run_id="run-1", base_commit=git(repo, "rev-parse", "HEAD"),
        target_branch="target", worker_limit=worker_limit, repo_root=str(repo),
    )
    if import_plan:
        state.import_phase_plan(run_dir, phase_plan=plan)
    return repo, run_dir, plan


def three_disjoint_tasks() -> str:
    return n_disjoint_tasks(3)


def n_disjoint_tasks(count: int) -> str:
    return "".join(
        task_block(f"T{index}", order=index, batch=f"b{index}",
                   write_scope=f"file:src/a{index}.py")
        for index in range(1, count + 1)
    )


def blank_row(section: str) -> dict:
    """An all-'-' row with exactly P02's committed columns for that section."""
    return {state._key(column): "-" for column in state.section_columns(section)}


def bump(run_dir, transition: str = "test-bump") -> dict:
    """One durable transition that changes nothing.

    It exists so a test can ask for a SECOND call of a transition rather than a
    REPLAY of the first: `locked_tracker_update` recognises a replay by
    comparing against `last_transition`, so only the most recent transition
    replays, and the two behaviours are otherwise impossible to tell apart.
    """
    return state.locked_tracker_update(
        run_dir, transition_id=transition, mutate=lambda tracker: tracker)


def open_quorum_row(run_dir, owners=("brain-1", "brain-2", "brain-3"),
                    *, qid="3f2a1b0c9d8e", quorum_state="in_flight",
                    transition="test-open-quorum") -> None:
    """Stand in for P03's `open_quorum`: one record with three owners."""
    def mutate(tracker: dict) -> dict:
        row = blank_row("quorum")
        row.update(qid=qid, axis="new", phase="P04", state=quorum_state,
                   owners=",".join(owners), payload_digest=FAKE_DIGEST,
                   context_digest=OTHER_DIGEST)
        if quorum_state == "finalized":
            row.update(outcome="escalated", depth="1")
        return state.append_row(tracker, "quorum", row)

    state.locked_tracker_update(run_dir, transition_id=transition, mutate=mutate)


def task_row(tracker: dict, task_id: str) -> dict:
    return next(row for row in tracker["tasks"] if row["id"] == task_id)


def set_task_state(run_dir, task_id: str, transition: str, **fields) -> None:
    def mutate(tracker: dict) -> dict:
        task_row(tracker, task_id).update(fields)
        return tracker

    state.locked_tracker_update(
        run_dir, transition_id=transition, mutate=mutate)


# --------------------------------------------------------------------------
# Task 6 tests -- the tracker accessors.
#
# The first two are the Produces-block check, executable. The brief named
# `_field` and `_csv` as Task 6 products; both are P02's, and a module-level
# redefinition rebinds the global for every existing caller.
# --------------------------------------------------------------------------

class TrackerAccessorTests(unittest.TestCase):

    def test_field_is_still_p02s_one_argument_header_to_key_map(self):
        """`_field` was named as a Task 6 product with the signature
        `_field(row, column)`. It is P02's `_field(column)`, read at every
        section-column site in the module, and a two-argument redefinition
        would move all of them at once."""
        self.assertEqual(state._field("Source Ref"), "source_ref")
        self.assertEqual(state._field("Payload Digest"), "payload_digest")
        self.assertEqual(state._field("Re-review"), "re_review")
        with self.assertRaises(TypeError):
            state._field({"id": "T1"}, "ID")

    def test_key_is_p02s_map_under_a_second_name_not_a_second_copy(self):
        """A copy would be a second answer to 'what is this column called',
        free to drift from the one `parse_tracker` and `append_row` use."""
        self.assertIs(state._key, state._field)

    def test_key_is_idempotent_over_an_already_keyed_column(self):
        """`section_columns` returns KEYS, not display headers, so every
        caller below applies `_key` to something already keyed."""
        for section in state.SECTIONS:
            for column in state.section_columns(section):
                with self.subTest(section=section, column=column):
                    self.assertEqual(state._key(column), column)

    def test_csv_is_still_p02s_cell_reader(self):
        """`_csv` was named as a Task 6 product too, with `-` and `''` folded
        together. P02's distinguishes them, and `_cell_list` relies on it:
        `-` is an empty cell and `''` is one nameless member."""
        self.assertEqual(state._csv("-"), ())
        self.assertEqual(state._csv("a,b"), ("a", "b"))
        self.assertEqual(state._csv(" a , b "), ("a", "b"))
        self.assertEqual(state._csv(""), ("",))

    def test_attempt_token_is_still_task_4s_single_conversion_point(self):
        self.assertEqual(state._attempt_token(1), "attempt-001")
        self.assertEqual(state._attempt_token(1000), "attempt-1000")
        with self.assertRaises(state.TrackerValidationError):
            state._attempt_token(10 ** state._MAX_ATTEMPT_DIGITS)

    def test_run_field_reads_a_field_and_names_a_missing_one(self):
        tracker = {"run": {"worker_limit": "6"}}
        self.assertEqual(state._run_field(tracker, "worker_limit"), "6")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._run_field(tracker, "phase_plans")
        self.assertIn("phase_plans", str(caught.exception))

    def test_run_field_refuses_a_tracker_with_no_run_section(self):
        """A `KeyError`/`TypeError` here would leave this module's exception
        family, which is what every controller handler is written against."""
        for tracker in ({}, {"run": None}, {"run": ["worker_limit"]}):
            with self.subTest(tracker=tracker):
                with self.assertRaises(state.TrackerValidationError):
                    state._run_field(tracker, "worker_limit")

    def test_task_row_finds_by_id_and_names_an_unknown_task(self):
        tracker = {"tasks": [{"id": "T1"}, {"id": "T2"}]}
        self.assertIs(state._task_row(tracker, "T2"), tracker["tasks"][1])
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._task_row(tracker, "T9")
        self.assertIn("T9", str(caught.exception))

    def test_replace_task_swaps_exactly_one_row_and_keeps_the_order(self):
        tracker = {"tasks": [{"id": "T1", "state": "[ ]"},
                             {"id": "T2", "state": "[ ]"},
                             {"id": "T3", "state": "[ ]"}]}
        state._replace_task(tracker, {"id": "T2", "state": "[~]"})
        self.assertEqual([row["id"] for row in tracker["tasks"]],
                         ["T1", "T2", "T3"])
        self.assertEqual([row["state"] for row in tracker["tasks"]],
                         ["[ ]", "[~]", "[ ]"])

    def test_replace_task_refuses_a_replacement_for_no_row(self):
        """Silently appending nothing would leave the caller's edit lost and
        the transition reported as applied."""
        tracker = {"tasks": [{"id": "T1", "state": "[ ]"}]}
        with self.assertRaises(state.TrackerValidationError):
            state._replace_task(tracker, {"id": "T9", "state": "[~]"})

    def test_append_history_starts_an_empty_cell_and_extends_a_full_one(self):
        self.assertEqual(state._append_history("-", "started:attempt-001"),
                         "started:attempt-001")
        self.assertEqual(state._append_history("", "a"), "a")
        self.assertEqual(state._append_history("a", "b"), "a,b")

    def test_quorum_owners_counts_only_the_in_flight_rows(self):
        tracker = {"quorum": [
            {"state": "in_flight", "owners": "brain-1,brain-2,brain-3"},
            {"state": "finalized", "owners": "brain-7,brain-8,brain-9"},
        ]}
        self.assertEqual(state._quorum_owners(tracker),
                         {"brain-1", "brain-2", "brain-3"})

    def test_quorum_owners_skips_the_absence_marker_and_an_empty_cell(self):
        """The filter is over MEMBERS, not over the whole cell. `_csv` already
        answers `()` for a cell spelled `-`, so a test that only passes `-` as
        the whole cell cannot see the filter at all -- `a,-,b` and `a,,b` are
        the spellings that would otherwise enter the set as owner names."""
        self.assertEqual(
            state._quorum_owners({"quorum": [{"state": "in_flight",
                                              "owners": "-"}]}),
            set())
        self.assertEqual(
            state._quorum_owners({"quorum": [{"state": "in_flight",
                                              "owners": "brain-1,-,brain-2"}]}),
            {"brain-1", "brain-2"})
        self.assertEqual(
            state._quorum_owners({"quorum": [{"state": "in_flight",
                                              "owners": "brain-1,,brain-2"}]}),
            {"brain-1", "brain-2"})

    def test_quorum_owners_answers_an_empty_and_an_absent_section(self):
        self.assertEqual(state._quorum_owners({"quorum": []}), set())
        self.assertEqual(state._quorum_owners({}), set())

    def test_implementation_owners_counts_running_and_blocked_alike(self):
        """A blocked `[?]` task still occupies its implementation slot: the
        worker holding it has not been released, which is the whole reason
        three slots are held back for the quorum that would unblock it."""
        tracker = {"tasks": [
            {"id": "T1", "state": "[~]", "owner": "impl-1"},
            {"id": "T2", "state": "[?]", "owner": "impl-2"},
            {"id": "T3", "state": "[x]", "owner": "impl-3"},
            {"id": "T4", "state": "[ ]", "owner": "-"},
        ]}
        self.assertEqual(state._implementation_owners(tracker),
                         {"impl-1", "impl-2"})

    def test_implementation_owners_never_counts_the_absence_marker(self):
        """P02's `_validate_tasks` refuses a started row with no owner, so a
        VALIDATED tracker cannot produce this -- the screen is a hedge over an
        unvalidated caller, and the hedge is pinned here so that deleting it is
        a failing test rather than a silent widening. `-` counted as an owner
        would consume a slot for a worker that does not exist."""
        tracker = {"tasks": [{"id": "T1", "state": "[~]", "owner": "-"},
                             {"id": "T2", "state": "[?]", "owner": "impl-2"}]}
        self.assertEqual(state._implementation_owners(tracker), {"impl-2"})

    def test_active_owners_is_the_union_of_both_populations(self):
        tracker = {
            "tasks": [{"id": "T1", "state": "[~]", "owner": "impl-1"}],
            "quorum": [{"state": "in_flight",
                        "owners": "brain-1,brain-2,brain-3"}],
        }
        self.assertEqual(
            state._active_owners(tracker),
            {"impl-1", "brain-1", "brain-2", "brain-3"})


# --------------------------------------------------------------------------
# Task 6 tests -- fault F2: the slot cap.
# --------------------------------------------------------------------------

class SlotCapTests(unittest.TestCase):

    def test_cap_holds_three_slots_for_a_quorum(self):
        self.assertEqual(state.QUORUM_SLOT_RESERVE, 3)
        self.assertEqual(state.implementation_slot_cap(4), 1)
        self.assertEqual(state.implementation_slot_cap(6), 3)
        self.assertEqual(state.implementation_slot_cap(10), 7)

    def test_cap_floors_at_one_so_tasks_serialise_rather_than_stall(self):
        # Below four the cap floors at ONE, not zero: tasks serialise and the
        # brain slots stay free. Flooring at zero would stop the run instead.
        self.assertEqual(state.implementation_slot_cap(3), 1)
        self.assertEqual(state.implementation_slot_cap(1), 1)

    def test_the_cap_is_never_the_limit_itself_above_the_floor(self):
        """The F2 shape stated as a property rather than as three remembered
        numbers: above the point where the floor binds, the cap is strictly
        below `worker_limit` by exactly the reserve."""
        for limit in range(4, 40):
            with self.subTest(limit=limit):
                cap = state.implementation_slot_cap(limit)
                self.assertEqual(limit - cap, state.QUORUM_SLOT_RESERVE)
                self.assertLess(cap, limit)

    def test_cap_rejects_a_nonpositive_or_wrong_typed_limit(self):
        for value in (0, -1, True, False, "4", 4.0, None, [4], {"a": 1}):
            with self.subTest(value=value):
                with self.assertRaises(state.TrackerValidationError):
                    state.implementation_slot_cap(value)


# --------------------------------------------------------------------------
# Task 6 tests -- resolving a ref without `subprocess`.
#
# `_git` and `_git_out` were named as Task 6 products as `subprocess` wrappers.
# `subprocess` is not in `ALLOWED_IMPORTS` and the master plan refuses it by
# name, so the ref store is read directly -- the same translation the plans'
# `re.compile` screens get, for the same reason.
# --------------------------------------------------------------------------

class GitRefResolutionTests(TempDirTestCase):

    def repo(self) -> Path:
        return make_repo(self.tmp)

    def test_a_loose_branch_ref_resolves_to_its_commit(self):
        repo = self.repo()
        self.assertEqual(state._resolved_commit(repo, "target"),
                         git(repo, "rev-parse", "target"))

    def test_a_packed_branch_ref_resolves_to_the_same_commit(self):
        """`git pack-refs` deletes the loose file. A resolver that only read
        `refs/heads/<name>` would report a perfectly ordinary repository as
        having no target branch."""
        repo = self.repo()
        expected = git(repo, "rev-parse", "target")
        git(repo, "pack-refs", "--all")
        self.assertFalse((repo / ".git" / "refs" / "heads" / "target").exists())
        self.assertEqual(state._resolved_commit(repo, "target"), expected)

    def test_a_fully_qualified_ref_resolves(self):
        repo = self.repo()
        self.assertEqual(state._resolved_commit(repo, "refs/heads/target"),
                         git(repo, "rev-parse", "target"))

    def test_head_is_chased_through_its_symref(self):
        repo = self.repo()
        self.assertEqual(state._resolved_commit(repo, "HEAD"),
                         git(repo, "rev-parse", "HEAD"))

    def test_a_full_object_name_resolves_to_itself(self):
        repo = self.repo()
        commit = git(repo, "rev-parse", "target")
        self.assertEqual(state._resolved_commit(repo, commit), commit)

    def test_an_unknown_ref_is_a_stop_that_names_it(self):
        repo = self.repo()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._resolved_commit(repo, "no-such-branch")
        self.assertIn("no-such-branch", str(caught.exception))

    def test_a_repository_with_no_git_directory_is_a_stop(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        with self.assertRaises(state.TrackerValidationError):
            state._resolved_commit(plain, "target")

    def test_a_dot_git_FILE_is_followed_to_the_real_git_directory(self):
        """A per-implementer worktree is the whole integration topology of this
        phase, and in one `.git` is a FILE holding `gitdir: <path>`. A resolver
        that required a directory would refuse every worktree the run makes."""
        repo = self.repo()
        expected = git(repo, "rev-parse", "target")
        worktree = self.tmp / "wt"
        git(repo, "worktree", "add", "-q", "--detach", str(worktree), "target")
        self.addCleanup(git, repo, "worktree", "remove", "--force", str(worktree))
        self.assertTrue((worktree / ".git").is_file())
        self.assertEqual(state._resolved_commit(worktree, "target"), expected)

    def test_a_packed_tag_beats_a_loose_head_because_the_CANDIDATE_is_earlier(self):
        """Loose-before-packed is PER CANDIDATE, and the nesting is the rule.

        `_ref_candidates` is gitrevisions' order, so `refs/tags/x` is tried
        before `refs/heads/x`; storage breaks a tie only between two spellings
        of ONE candidate. On a store carrying a packed `refs/tags/x` and a loose
        `refs/heads/x` the TAG therefore wins.

        Hoisting the packed lookup into a second loop -- loose-for-all before
        packed-for-all, which is what the docstring here used to describe as the
        code's behaviour -- finds the loose head first and resolves the other
        commit. That mutant survived the whole suite, because every ref test
        until this one exercised loose, packed, symref, peel and worktree
        SEPARATELY and never made two of them compete.

        The expectation is taken from real `git rev-parse` on the same store
        rather than from a reading of this module, so the test disagrees with
        git or with the code, never with the author's model of either.
        """
        repo = self.repo()
        head_commit = git(repo, "rev-parse", "HEAD")
        tag_commit = git(repo, "rev-parse", "target")
        self.assertNotEqual(head_commit, tag_commit)
        (repo / ".git" / "refs" / "heads" / "x").write_text(
            head_commit + "\n", encoding="utf-8")
        (repo / ".git" / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted \n"
            f"{tag_commit} refs/tags/x\n", encoding="utf-8")
        #: Both spellings really are present, or the assertion below is about
        #: a store with only one answer in it.
        self.assertTrue((repo / ".git" / "refs" / "heads" / "x").is_file())
        self.assertEqual(state._lookup_ref(*state._git_store(repo),
                                           "refs/heads/x"), head_commit)
        self.assertEqual(state._packed_ref(state._git_store(repo)[1],
                                           "refs/tags/x"), tag_commit)
        self.assertEqual(git(repo, "rev-parse", "x"), tag_commit)
        self.assertEqual(state._resolved_commit(repo, "x"),
                         git(repo, "rev-parse", "x"))
        self.assertEqual(state._resolved_commit(repo, "x"), tag_commit)

    def test_a_linked_worktrees_own_gitdir_outranks_the_shared_commondir(self):
        """`(gitdir, common)` is an ORDER, and this is the ref that sees it.

        A linked worktree carries `HEAD` in BOTH stores: its own detached
        `HEAD` in the per-worktree gitdir, and the main checkout's
        `ref: refs/heads/main` in the shared commondir. They name different
        commits, which is the entire reason per-worktree state exists.

        The existing worktree test resolves `target` -- a branch, which lives
        only in commondir -- so it proves commondir is READ and cannot see which
        store is read FIRST. Swapping the pair survived the suite on that test
        alone. Here the swap resolves the main worktree's `HEAD` instead, which
        is the wrong commit for this checkout and, worse, a silently plausible
        one.

        `HEAD` is reachable as a `target_branch`: `_ref_name` admits it and
        `_PSEUDO_REFS` lists it.
        """
        repo = self.repo()
        worktree = self.tmp / "wt"
        git(repo, "worktree", "add", "-q", "--detach", str(worktree), "target")
        self.addCleanup(git, repo, "worktree", "remove", "--force",
                        str(worktree))
        gitdir, common = state._git_store(worktree)
        self.assertNotEqual(gitdir.resolve(), common.resolve())
        own = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        shared = (common / "HEAD").read_text(encoding="utf-8").strip()
        #: The same NAME in both stores, holding different things -- without
        #: this the order is unobservable and the test is the old one again.
        self.assertTrue((gitdir / "HEAD").is_file())
        self.assertTrue((common / "HEAD").is_file())
        self.assertNotEqual(own, shared)
        resolved = state._resolved_commit(worktree, "HEAD")
        self.assertEqual(resolved, git(worktree, "rev-parse", "HEAD"))
        self.assertEqual(resolved, own)
        #: And it is NOT the commit commondir-first would have produced, which
        #: is the assertion the swapped pair fails.
        self.assertNotEqual(resolved, git(repo, "rev-parse", "HEAD"))

    def test_an_acyclic_symref_chain_is_refused_at_the_bound_itself(self):
        """`_SYMREF_LIMIT` is a real bound, and it was pinned by nothing.

        The cycle detector terminates every CYCLE, so loosening 8 to 200 broke
        no test: with the cycle check present a longer chain still ends. What
        the bound defends against is a deep ACYCLIC chain -- work proportional
        to a number an agent-supplied ref store chooses -- and that is only
        visible at the boundary.

        So both sides are walked: the deepest chain that resolves, and the
        first that does not. A test that only asserted the refusal would pass
        with the limit set to 1, and one that only asserted the success would
        pass with it set to 200.
        """
        repo = self.repo()
        commit = git(repo, "rev-parse", "target")
        heads = repo / ".git" / "refs" / "heads"

        def chain(hops: int) -> str:
            """`hops` symbolic links ending at a real object name."""
            names = [f"c{hops}x{index}" for index in range(hops + 1)]
            for index, name in enumerate(names[:-1]):
                (heads / name).write_text(
                    f"ref: refs/heads/{names[index + 1]}\n", encoding="utf-8")
            (heads / names[-1]).write_text(commit + "\n", encoding="utf-8")
            return names[0]

        self.assertEqual(state._SYMREF_LIMIT, 8)
        #: Seven hops plus the object name is exactly eight lookups.
        #:
        #: NO `git rev-parse` CROSS-CHECK HERE, deliberately: git's own symref
        #: bound is FIVE, so it refuses this chain at a depth the module still
        #: accepts. The looser bound is `_SYMREF_LIMIT`'s documented choice, not
        #: a disagreement to resolve, and calling git would pin git's number.
        self.assertEqual(state._resolved_commit(repo, chain(7)), commit)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._resolved_commit(repo, chain(8))
        #: THE DIAGNOSIS, not the family: an unreadable file and a missing ref
        #: both raise here too, and only the sentence tells the bound apart.
        self.assertIn("chain deeper than 8", str(caught.exception))
        self.assertNotIn("names no reference", str(caught.exception))
        self.assertNotIn("cycle", str(caught.exception))

    def test_a_ref_name_that_traverses_out_of_the_store_is_refused(self):
        """`_TOKEN` admits `/`, so `target_branch` could be spelled
        `a/../../../../etc/passwd` and still pass every cell grammar; the ref
        lookup is what has to refuse it."""
        repo = self.repo()
        for name in ("a/../../config", "a//b", "a/./b", "a/ b", ".hidden/x",
                     "refs/../config", "a/..", ".."):
            with self.subTest(name=name):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state._resolved_commit(repo, name)
                #: THE DIAGNOSIS, not the family. Without the screen
                #: `refs/a/../../config` normalises onto `.git/config`, which
                #: is a real readable file whose contents are not an object
                #: name -- so the resolver still raises, from one function
                #: further on, having read a file outside the ref store.
                self.assertIn("unusable git reference", str(caught.exception))
                self.assertNotIn("names no reference", str(caught.exception))
                self.assertNotIn("40-character object name",
                                 str(caught.exception))

    def test_a_ref_whose_file_is_a_directory_reads_as_an_ABSENT_ref(self):
        """The one shape `is_file()` is false for that IS "nothing here".

        This test used to be named `..._is_corruption_not_absence` and
        asserted only `TrackerError`. A directory at the ONLY candidate
        resolves to nothing either way, so raising and falling through are
        indistinguishable from here -- the assertion was true of both the
        behaviour and the defect, which is how the defect shipped past two
        reviews. `test_a_directory_at_an_earlier_candidate_...` below is the
        case that separates them; this one now pins WHICH stop is reached, so
        the two cannot drift apart again.

        A ref namespace IS a directory, and git walks past it.
        """
        repo = self.repo()
        (repo / ".git" / "refs" / "heads" / "shaped").mkdir()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._resolved_commit(repo, "shaped")
        self.assertIn("names no reference", str(caught.exception))
        self.assertNotIn("cannot read", str(caught.exception))

    def test_a_ref_whose_file_is_a_fifo_does_not_hang_the_run(self):
        """A FIFO opened for reading BLOCKS until a writer arrives, and under
        the run lock no writer is coming. The shape is asked before the open."""
        repo = self.repo()
        os.mkfifo(repo / ".git" / "refs" / "heads" / "piped")

        def alarm(signum, frame):
            raise AssertionError("_resolved_commit blocked on a FIFO")

        previous = signal.signal(signal.SIGALRM, alarm)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        signal.alarm(5)
        try:
            with self.assertRaises(state.TrackerError):
                state._resolved_commit(repo, "piped")
        finally:
            signal.alarm(0)

    def test_a_symref_cycle_is_bounded_rather_than_looping(self):
        repo = self.repo()
        (repo / ".git" / "refs" / "heads" / "ping").write_text(
            "ref: refs/heads/pong\n", encoding="utf-8")
        (repo / ".git" / "refs" / "heads" / "pong").write_text(
            "ref: refs/heads/ping\n", encoding="utf-8")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._resolved_commit(repo, "ping")
        #: The depth bound refuses this input too, so the family alone proves
        #: nothing: a cycle must be named a cycle, or the bound is doing the
        #: work and the check that names the loop can be deleted unnoticed.
        self.assertIn("cycle", str(caught.exception))
        self.assertNotIn("deeper than", str(caught.exception))

    def test_a_ref_holding_something_that_is_not_an_object_name_is_refused(self):
        repo = self.repo()
        (repo / ".git" / "refs" / "heads" / "junk").write_text(
            "not a commit\n", encoding="utf-8")
        with self.assertRaises(state.TrackerValidationError):
            state._resolved_commit(repo, "junk")

    def test_a_ref_under_a_branch_that_is_a_file_is_absent_not_corruption(self):
        """`refs/heads/target` is a FILE, so `refs/heads/target/sub` raises
        `ENOTDIR` -- which `is_file()` swallows and `lexists` answers False to,
        so `_require_regular_file` stays silent and the read is what meets it.

        `NotADirectoryError` is one of the two spellings of "not there", the
        same ruling `_require_regular_file`'s own split records. Dropping it
        from the absence arm turns every ref whose parent is a branch name into
        repository corruption, and a controller asking for a branch that simply
        does not exist gets told its repository is damaged."""
        repo = self.repo()
        self.assertTrue((repo / ".git" / "refs" / "heads" / "target").is_file())
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._resolved_commit(repo, "target/sub")
        self.assertIn("names no reference", str(caught.exception))
        self.assertNotIn("cannot read", str(caught.exception))
        self.assertNotIn("unreadable", str(caught.exception))

    def test_a_ref_that_is_not_utf8_is_unreadable_rather_than_absent(self):
        """`_require_regular_file` lets a regular file through, so the read is
        where a non-UTF-8 ref surfaces. Reporting it as absent would say the
        branch does not exist, and a run would start a task against a baseline
        it had silently failed to read."""
        repo = self.repo()
        (repo / ".git" / "refs" / "heads" / "mojibake").write_bytes(b"\xff\xfe\n")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._resolved_commit(repo, "mojibake")
        self.assertIn("unreadable", str(caught.exception))
        self.assertNotIn("names no reference", str(caught.exception))

    def test_an_annotated_tag_peels_to_its_commit(self):
        repo = self.repo()
        git(repo, "tag", "-a", "v1", "-m", "release", "target")
        git(repo, "pack-refs", "--all")
        self.assertEqual(state._resolved_commit(repo, "v1"),
                         git(repo, "rev-parse", "v1^{commit}"))

    def test_the_search_order_prefers_a_branch_over_a_remote(self):
        """gitrevisions searches `refs/heads/<name>` before
        `refs/remotes/<name>`; a resolver that reversed them would silently
        review a stale fetched tip."""
        repo = self.repo()
        branch = git(repo, "rev-parse", "target")
        remote = repo / ".git" / "refs" / "remotes" / "target"
        remote.parent.mkdir(parents=True, exist_ok=True)
        remote.write_text(git(repo, "rev-parse", "main") + "\n", encoding="utf-8")
        self.assertNotEqual(branch, git(repo, "rev-parse", "main"))
        self.assertEqual(state._resolved_commit(repo, "target"), branch)

    # ----------------------------------------------------------------------
    # The candidate-order x candidate-shape cross-product.
    #
    # Three passes over `_lookup_ref` each drew their cases from the previous
    # pass's defects and each found more of the same class. These are
    # generated from the CROSS-PRODUCT instead -- gitrevisions' five
    # candidates for an unqualified name, against every shape a name can have
    # at one of them (absent, a valid file, an EMPTY file, a directory, a
    # FIFO, a dangling symlink, a symlink loop, a name this process may not
    # read), in the single-occupant, hostile-earlier and hostile-later
    # arrangements. Every expectation below is read off a real `git rev-parse`
    # on the same store, never off a reading of the module.
    #
    # What the product found that three hand-built passes did not: a
    # DIRECTORY at an earlier candidate aborted the whole search, and the ref
    # namespaces ARE directories.
    # ----------------------------------------------------------------------

    def test_a_directory_at_an_earlier_candidate_is_absence_not_corruption(self):
        """An unrelated tag `target/rc1` broke every run against `target`.

        `refs/tags/<name>` precedes `refs/heads/<name>` in gitrevisions'
        order. `git tag target/rc1` creates the DIRECTORY
        `refs/tags/target/`, which sits at the earlier candidate; the branch
        the run wants is the perfectly ordinary file at the later one. The
        resolver refused the directory as corruption and the run died on a
        store `git rev-parse` answers without complaint.

        The earlier review tested a directory at the ONLY candidate, where
        raising and returning `None` are indistinguishable, which is why two
        passes called this covered.
        """
        repo = self.repo()
        git(repo, "tag", "target/rc1", "main")
        directory = repo / ".git" / "refs" / "tags" / "target"
        self.assertTrue(directory.is_dir())
        self.assertTrue((repo / ".git" / "refs" / "heads" / "target").is_file())
        self.assertEqual(state._resolved_commit(repo, "target"),
                         git(repo, "rev-parse", "target"))

    def test_the_remotes_head_candidate_is_reachable_through_its_directory(self):
        """`refs/remotes/<name>/HEAD` can ONLY be reached through a directory.

        The candidate is appended by `_ref_candidates` for exactly the case of
        a remote named like the ref -- and `refs/remotes/<name>/` is a
        directory, which the resolver refused one candidate earlier. The
        candidate was unreachable by construction, so the mutant deleting it
        survived: nothing could reach it either way.
        """
        repo = self.repo()
        head = repo / ".git" / "refs" / "remotes" / "origin" / "HEAD"
        head.parent.mkdir(parents=True)
        head.write_text(git(repo, "rev-parse", "target") + "\n",
                        encoding="utf-8")
        self.assertTrue(head.parent.is_dir())
        self.assertEqual(git(repo, "rev-parse", "origin"),
                         git(repo, "rev-parse", "target"))
        self.assertEqual(state._resolved_commit(repo, "origin"),
                         git(repo, "rev-parse", "origin"))

    def test_a_symbolic_remotes_head_is_followed_through_the_same_directory(self):
        """The same candidate carrying git's own spelling of it: `HEAD` under
        a remote is normally `ref: refs/remotes/origin/main`, not a sha."""
        repo = self.repo()
        tip = repo / ".git" / "refs" / "remotes" / "origin" / "main"
        tip.parent.mkdir(parents=True)
        tip.write_text(git(repo, "rev-parse", "target") + "\n",
                       encoding="utf-8")
        (tip.parent / "HEAD").write_text(
            "ref: refs/remotes/origin/main\n", encoding="utf-8")
        self.assertEqual(state._resolved_commit(repo, "origin"),
                         git(repo, "rev-parse", "origin"))

    def test_the_other_hostile_shapes_at_an_earlier_candidate_still_stop(self):
        """The directory carve-out is not a weakening of the standing rule.

        A directory means "this name has children and no value of its own",
        which is what a ref namespace IS. A FIFO, a dangling link, a symlink
        loop and a name this process cannot read mean "something is here and
        this run cannot establish what", and that is never folded into
        absence -- even though the later candidate holds a perfectly good
        branch and even though git itself warns and carries on. A baseline is
        one end of a range proof.

        The FIFO is probed for BLOCKING as well as for raising: the whole
        reason the shape is asked before the open is that a reader on a FIFO
        waits under the run lock for a writer that never comes.
        """
        repo = self.repo()
        good = git(repo, "rev-parse", "target")
        self.assertEqual(state._resolved_commit(repo, "target"), good)
        tags = repo / ".git" / "refs" / "tags"
        tags.mkdir(parents=True, exist_ok=True)
        hostile = tags / "target"

        def clear():
            if hostile.is_symlink() or hostile.exists():
                hostile.chmod(0o644) if hostile.is_file() else None
                hostile.unlink()

        cases = {
            "fifo": lambda: os.mkfifo(hostile),
            "dangling": lambda: hostile.symlink_to(tags / "nowhere"),
            "unreadable": lambda: (hostile.write_text(good, encoding="utf-8"),
                                   hostile.chmod(0o000)),
        }
        for label, build in cases.items():
            with self.subTest(shape=label):
                build()
                self.addCleanup(clear)
                #: BOUNDED: the FIFO case must RETURN rather than block, and
                #: an assertion that never runs is not an assertion.
                previous = signal.signal(signal.SIGALRM, _alarm)
                self.addCleanup(signal.signal, signal.SIGALRM, previous)
                signal.alarm(5)
                try:
                    with self.assertRaises(state.TrackerValidationError):
                        state._resolved_commit(repo, "target")
                finally:
                    signal.alarm(0)
                clear()
        #: The symlink loop needs two names, so it is built separately.
        other = tags / "target.loop"
        hostile.symlink_to(other)
        other.symlink_to(hostile)
        self.addCleanup(other.unlink)
        self.addCleanup(clear)
        with self.assertRaises(state.TrackerValidationError):
            state._resolved_commit(repo, "target")

    def test_an_empty_loose_ref_shadows_its_own_packed_entry_like_git(self):
        """git calls an empty loose ref BROKEN and refuses the whole name.

        Measured, not read: with an empty `refs/heads/target` AND a packed
        `refs/heads/target`, `git rev-parse` prints `warning: ignoring broken
        ref refs/heads/target` and exits non-zero. The loose file shadows the
        packed entry even though it carries nothing.

        The module used to treat emptiness as plain absence and fall through
        to the packed entry, resolving a store git itself will not name -- the
        worse of the two directions, because the run would then proceed on a
        baseline nobody can reproduce with git.
        """
        repo = self.repo()
        packed = git(repo, "rev-parse", "main")
        (repo / ".git" / "refs" / "heads" / "target").write_text(
            "", encoding="utf-8")
        (repo / ".git" / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted \n"
            f"{packed} refs/heads/target\n", encoding="utf-8")
        #: git's own answer, taken directly: the name does not resolve.
        probe = subprocess.run(
            ("git", "-C", str(repo), "rev-parse", "--verify", "-q",
             "target^{commit}"), capture_output=True, text=True)
        self.assertNotEqual(probe.returncode, 0, probe.stdout)
        with self.assertRaises(state.TrackerValidationError):
            state._resolved_commit(repo, "target")

    def test_an_empty_loose_ref_cancels_its_candidate_and_not_the_search(self):
        """...and emptiness cancels THAT CANDIDATE only.

        The same measurement, one candidate earlier: an empty
        `refs/tags/target` beside a valid loose `refs/heads/target` makes git
        warn and answer the head. So "broken" is not "stop"; it is "this
        candidate yields nothing, including from packed-refs".
        """
        repo = self.repo()
        tags = repo / ".git" / "refs" / "tags"
        tags.mkdir(parents=True, exist_ok=True)
        (tags / "target").write_text("", encoding="utf-8")
        self.assertEqual(state._resolved_commit(repo, "target"),
                         git(repo, "rev-parse", "target"))

    def test_a_whitespace_only_loose_ref_is_broken_for_the_same_reason(self):
        """`text.strip()` is the emptiness test, so a file of spaces is the
        same broken ref -- and git agrees, which is what makes the two one
        case rather than two guesses."""
        repo = self.repo()
        packed = git(repo, "rev-parse", "main")
        (repo / ".git" / "refs" / "heads" / "target").write_text(
            "   \n", encoding="utf-8")
        (repo / ".git" / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted \n"
            f"{packed} refs/heads/target\n", encoding="utf-8")
        probe = subprocess.run(
            ("git", "-C", str(repo), "rev-parse", "--verify", "-q",
             "target^{commit}"), capture_output=True, text=True)
        self.assertNotEqual(probe.returncode, 0, probe.stdout)
        with self.assertRaises(state.TrackerValidationError):
            state._resolved_commit(repo, "target")

    def test_packed_refs_is_read_from_the_common_dir_not_the_worktree(self):
        """`git pack-refs` writes ONE file, in the common directory.

        A linked worktree's own gitdir has no `packed-refs` at all, so a
        resolver reading it from `gitdir` loses EVERY packed ref in EVERY
        linked worktree -- and packing is what git does on its own during
        `gc`, so this is an ordinary repository, not a contrived one.

        The existing packed-ref test runs in the MAIN checkout, where
        `gitdir == common` and the two spellings are the same file; the
        existing worktree test resolves a LOOSE ref. Neither can see the
        difference, which is why the mutant swapping `common` for `gitdir`
        here survived both.
        """
        repo = self.repo()
        expected = git(repo, "rev-parse", "target")
        worktree = self.tmp / "packed-wt"
        git(repo, "worktree", "add", "-q", "--detach", str(worktree), "main")
        self.addCleanup(git, repo, "worktree", "remove", "--force",
                        str(worktree))
        git(repo, "pack-refs", "--all")
        gitdir, common = state._git_store(worktree)
        self.assertNotEqual(gitdir, common)
        self.assertFalse((gitdir / "packed-refs").exists())
        self.assertTrue((common / "packed-refs").is_file())
        self.assertFalse((common / "refs" / "heads" / "target").exists())
        self.assertEqual(state._resolved_commit(worktree, "target"), expected)
        self.assertEqual(state._resolved_commit(worktree, "target"),
                         git(worktree, "rev-parse", "target"))

    def test_a_candidate_the_dir_test_cannot_examine_is_not_made_absent(self):
        """The directory carve-out must not reopen the door's own escape.

        `is_dir()` raises for exactly the errnos `is_file()` raises for --
        CPython swallows only `pathlib._IGNORED_ERRNOS` and re-raises the
        rest -- so a carve-out spelled `except OSError: return None` would
        fold "this run cannot establish anything about this name" into "there
        is nothing here", at the one call site the door cannot see into. It
        is spelled `except OSError: pass` instead, so the name falls through
        to `_require_regular_file` and is reported ONCE, in the door's words.

        The two inputs are `_door_inputs`' two, re-spelled as REFERENCES:
        neither needs a permissions trick to be interesting and the first is
        a pure argument `_cell_safe` accepts. A mutant swapping the `pass`
        for a `return None` survives every other ref test in this class,
        because every one of them asks about a name this process can stat.
        """
        repo = self.repo()
        #: 1. A name past NAME_MAX. ENAMETOOLONG is not swallowed.
        long_name = "n" * 300
        self.assertTrue(state._cell_safe(long_name))
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._resolved_commit(repo, long_name)
        self.assertIn("cannot examine", str(caught.exception))
        self.assertNotIn("names no reference", str(caught.exception))
        #: 2. A candidate under a directory this run may not search. EACCES
        #:    is not swallowed either, and the candidate is `refs/heads/` --
        #:    reached only after two earlier candidates answer absent, so the
        #:    hostile shape is genuinely mid-search.
        heads = repo / ".git" / "refs" / "heads"
        os.chmod(heads, 0o000)
        self.addCleanup(os.chmod, heads, 0o755)
        if os.access(heads / "target", os.F_OK):  # pragma: no cover - root
            self.skipTest("this user can search a mode-000 directory")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._resolved_commit(repo, "target")
        self.assertIn("cannot examine", str(caught.exception))
        self.assertNotIn("names no reference", str(caught.exception))


# --------------------------------------------------------------------------
# Task 6 tests -- importing one approved phase plan.
# --------------------------------------------------------------------------

class ImportPhasePlanTests(TempDirTestCase):

    def test_appends_one_row_per_planned_task_with_the_committed_columns(self):
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        tracker = state.validate_run(run_dir)
        self.assertEqual([row["id"] for row in tracker["tasks"]],
                         ["T1", "T2", "T3"])
        expected = set(state.section_columns("tasks"))
        for row in tracker["tasks"]:
            with self.subTest(task=row["id"]):
                self.assertEqual(set(row), expected)
                self.assertEqual(row["state"], "[ ]")
                self.assertEqual(row["phase"], "P04")
                self.assertEqual(row["kind"], "source")
                self.assertEqual(row["owner"], "-")
                self.assertEqual(row["attempt"], "-")
                self.assertEqual(row["provisional"], "no")

    def test_an_artifact_task_keeps_its_declared_kind(self):
        """A fixture of three source tasks cannot tell `row["kind"] = kind`
        from `row["kind"] = "source"`."""
        body = (task_block("T1", order=1, batch="b1", write_scope="file:src/a.py")
                + task_block("T2", order=2, batch="b2", kind="artifact",
                             write_scope="tree:docs", outputs="docs/out.md"))
        repo, run_dir, plan = make_run(self.tmp, body, worker_limit=6)
        tracker = state.validate_run(run_dir)
        self.assertEqual([row["kind"] for row in tracker["tasks"]],
                         ["source", "artifact"])

    def test_task_rows_carry_no_dependency_column(self):
        """Dependencies live in the phase plan and nowhere else; a second copy
        on the row would be a divergable source of truth."""
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        tracker = state.validate_run(run_dir)
        self.assertNotIn("deps", tracker["tasks"][0])
        self.assertNotIn("dependencies", tracker["tasks"][0])

    def test_records_the_phase_with_its_plan_declared_review_class(self):
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        tracker = state.validate_run(run_dir)
        phase = next(row for row in tracker["phases"] if row["id"] == "P04")
        self.assertEqual(phase["review_class"], "required")
        self.assertEqual(phase["class_source"], "plan")
        self.assertEqual(phase["ratchet"], "-")
        self.assertEqual(phase["state"], "[ ]")

    def test_a_final_only_plan_is_mirrored_rather_than_defaulted(self):
        """With every fixture declaring `required`, `row[...] = "required"`
        passes -- and the dial would then be a constant."""
        repo = make_repo(self.tmp)
        run_dir = repo / "docs" / "superpowers" / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        plan = write_phase_plan(run_dir, task_block("T1"),
                                header=phase_header(review_class="final-only"))
        state.initialize_run(
            run_dir, run_id="run-1", base_commit=git(repo, "rev-parse", "HEAD"),
            target_branch="target", worker_limit=6, repo_root=str(repo))
        state.import_phase_plan(run_dir, phase_plan=plan)
        phase = state.validate_run(run_dir)["phases"][0]
        self.assertEqual(phase["review_class"], "final-only")
        self.assertEqual(phase["class_source"], "plan")

    def test_records_the_plan_path_against_the_phase_it_imported(self):
        """`_phase_plan_path` reads the `phase_plans` entry at the phase's own
        index, so the two lists are written in one transition or they drift."""
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        tracker = state.validate_run(run_dir)
        self.assertEqual(state._run_field(tracker, "phase_plans"),
                         plan.relative_to(repo).as_posix())
        self.assertEqual(state._phase_plan_path(tracker, "P04"),
                         plan.resolve())

    def test_a_second_phase_appends_and_stays_index_aligned(self):
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        second = write_phase_plan(
            run_dir, task_block("U1", write_scope="file:src/u.py"),
            header=phase_header(phase_id="P05", deps="P04"), name="phase-05.md")
        state.import_phase_plan(run_dir, phase_plan=second)
        tracker = state.validate_run(run_dir)
        self.assertEqual([row["id"] for row in tracker["phases"]],
                         ["P04", "P05"])
        self.assertEqual(state._csv(state._run_field(tracker, "phase_plans")),
                         (plan.relative_to(repo).as_posix(),
                          second.relative_to(repo).as_posix()))
        self.assertEqual(state._phase_plan_path(tracker, "P04"), plan.resolve())
        self.assertEqual(state._phase_plan_path(tracker, "P05"), second.resolve())

    def test_refuses_to_import_the_same_phase_twice(self):
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        #: A durable transition in between, so the second import is a SECOND
        #: CALL and not a REPLAY of the first -- the two are distinguished by
        #: `last_transition` alone, and only the replay is inert.
        bump(run_dir)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.import_phase_plan(run_dir, phase_plan=plan)
        self.assertIn("P04", str(caught.exception))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_an_immediate_re_import_replays_and_changes_nothing(self):
        """The interrupted-controller case, and the one the duplicate refusal
        above must not be mistaken for: re-issuing the transition that may or
        may not have landed is how `UpdateOutcomeUncertain` is settled."""
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        before = (run_dir / "progress.md").read_bytes()
        tracker = state.import_phase_plan(run_dir, phase_plan=plan)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)
        self.assertEqual([row["id"] for row in tracker["tasks"]],
                         ["T1", "T2", "T3"])

    def test_a_malformed_plan_imports_nothing(self):
        repo = make_repo(self.tmp)
        run_dir = repo / "docs" / "superpowers" / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        plan = write_phase_plan(run_dir, task_block("T1"),
                                header=phase_header(review_class="medium"))
        state.initialize_run(
            run_dir, run_id="run-1", base_commit=git(repo, "rev-parse", "HEAD"),
            target_branch="target", worker_limit=6, repo_root=str(repo))
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.PlanMetadataError):
            state.import_phase_plan(run_dir, phase_plan=plan)
        self.assertEqual(state.validate_run(run_dir)["tasks"], [])
        self.assertEqual(state.validate_run(run_dir)["phases"], [])
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_a_plan_outside_the_recorded_repository_is_refused(self):
        """The plan path is recorded as a REPOSITORY-RELATIVE cell, so a plan
        that is not under the recorded root has no such spelling; guessing one
        would bind the run to a file nothing else can find again."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(),
                                    import_plan=False)
        outside = write_phase_plan(self.tmp, task_block("T1"), name="outside.md")
        with self.assertRaises(state.TrackerValidationError):
            state.import_phase_plan(run_dir, phase_plan=outside)
        self.assertEqual(state.validate_run(run_dir)["tasks"], [])

    def test_the_phase_plan_path_is_resolved_against_the_recorded_root(self):
        """Not against the process working directory, and not by walking up
        from `run_dir`: a run directory at an unexpected depth would otherwise
        bind silently to another repository."""
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        tracker = state.validate_run(run_dir)
        self.assertEqual(state._repo_dir(tracker), repo.resolve())
        self.assertTrue(
            str(state._phase_plan_path(tracker, "P04")).startswith(
                str(repo.resolve())))

    def test_a_phase_list_longer_than_the_plan_list_is_a_stop_not_an_IndexError(self):
        """`import_phase_plan` writes both lists in one transition, so only a
        hand-edited tracker can put them out of step -- and then
        `paths[phase_ids.index(...)]` raises `IndexError`, which is outside
        this module's exception family and escapes every controller handler."""
        tracker = {"run": {"phase_plans": "docs/p04.md"},
                   "phases": [{"id": "P04"}, {"id": "P05"}]}
        for phase_id in ("P04", "P05"):
            with self.subTest(phase_id=phase_id):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state._phase_plan_path(tracker, phase_id)
                self.assertIn("approved", str(caught.exception))

    def test_two_phase_plans_may_not_claim_one_task_id(self):
        """Caught HERE and not only by P02's reparse canary, which refuses the
        duplicate row for its own reason and says nothing about the plans."""
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        second = write_phase_plan(
            run_dir, task_block("T2", write_scope="file:src/z.py"),
            header=phase_header(phase_id="P05", deps="P04"), name="phase-05.md")
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.import_phase_plan(run_dir, phase_plan=second)
        self.assertIn("which phase owns it", str(caught.exception))
        #: P02's own duplicate-row refusal, which fires at the reparse canary
        #: if this one is deleted. Its wording must be ABSENT here.
        self.assertNotIn("which copy the scan reaches first",
                         str(caught.exception))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_an_unknown_phase_has_no_approved_plan(self):
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        tracker = state.validate_run(run_dir)
        with self.assertRaises(state.TrackerValidationError):
            state._phase_plan_path(tracker, "P09")


# --------------------------------------------------------------------------
# Task 6 tests -- faults F1 and F2: reserving a task.
# --------------------------------------------------------------------------

class ReserveTaskTests(TempDirTestCase):

    def test_worker_limit_four_reserves_one_task_and_a_quorum_still_fits(self):
        """F2: reserving up to worker_limit deadlocks the run permanently --
        the blocked task holds the slot needed to dispatch the brains that
        would unblock it."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=4)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)

        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        self.assertIn("quorum", str(caught.exception))
        #: The OTHER refusal's wording must be absent, or this passes on a
        #: scope conflict between two provably disjoint files.
        self.assertNotIn("write scope", str(caught.exception))

        tracker = state.validate_run(run_dir)
        self.assertEqual(
            [row["id"] for row in tracker["tasks"] if row["state"] == "[~]"], ["T1"]
        )
        self.assertEqual(state._implementation_owners(tracker), {"impl-1"})

        # The three held slots are really available: a quorum opened afterwards
        # takes them and the run sits AT its limit, not over it.
        open_quorum_row(run_dir)
        tracker = state.validate_run(run_dir)
        self.assertEqual(
            state._quorum_owners(tracker), {"brain-1", "brain-2", "brain-3"}
        )
        self.assertEqual(len(state._active_owners(tracker)), 4)
        self.assertEqual(int(tracker["run"]["worker_limit"]), 4)

        with self.assertRaises(state.TrackerValidationError):
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)

    def test_worker_limit_six_reserves_three_tasks_then_refuses_a_fourth(self):
        body = three_disjoint_tasks() + task_block(
            "T4", order=4, batch="b4", write_scope="file:src/a4.py"
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=6)
        for index in range(1, 4):
            state.reserve_task(
                run_dir, task_id=f"T{index}", owner=f"impl-{index}", attempt=1
            )
        tracker = state.validate_run(run_dir)
        self.assertEqual(len(state._implementation_owners(tracker)), 3)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T4", owner="impl-4", attempt=1)
        self.assertIn("quorum", str(caught.exception))

    def test_a_blocked_task_still_occupies_its_implementation_slot(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=4)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        set_task_state(run_dir, "T1", "test-block-T1", state="[?]",
                       question=QUESTION_REF)
        tracker = state.validate_run(run_dir)
        self.assertEqual(state._implementation_owners(tracker), {"impl-1"})
        with self.assertRaises(state.TrackerValidationError):
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)

    def test_a_completed_task_releases_its_slot(self):
        """The mirror of the test above, and what stops `_OCCUPYING_STATES`
        from being satisfied by 'every state that is not unstarted'."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=4)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        set_task_state(
            run_dir, "T1", "test-finish-T1", state="[x]",
            result=f"docs/r.md#sha256={'1a' * 32}",
            verification=f"docs/v.md#sha256={'2b' * 32}",
            source_ref="b" * 40, commits="b" * 40, integration="held")
        tracker = state.validate_run(run_dir)
        self.assertEqual(state._implementation_owners(tracker), set())
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        tracker = state.validate_run(run_dir)
        self.assertEqual(task_row(tracker, "T2")["state"], "[~]")

    def test_overlapping_scopes_never_reserve_together_despite_spare_capacity(self):
        """F1: tree:src and file:src/a.py must never both be active."""
        body = (
            task_block("T1", order=1, batch="b1", write_scope="tree:src")
            + task_block("T2", order=2, batch="b2", write_scope="file:src/a.py")
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=12)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        self.assertIn("write scope", str(caught.exception))
        #: Capacity is spare -- twelve workers, one in use -- so the capacity
        #: refusal's wording must be absent or this test proves nothing about
        #: scopes at all.
        self.assertNotIn("quorum", str(caught.exception))
        self.assertIn("T1", str(caught.exception))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_disjoint_scopes_do_reserve_together(self):
        """The accepting half. A suite of refusals alone is satisfied by a
        `_require_no_scope_conflict` that refuses everything."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=8)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        tracker = state.validate_run(run_dir)
        self.assertEqual(
            [row["id"] for row in tracker["tasks"] if row["state"] == "[~]"],
            ["T1", "T2"])

    def test_a_scope_conflict_with_a_FINISHED_task_is_not_a_conflict(self):
        """`_OCCUPYING_STATES` again, from the scope side: a completed task
        holds no scope, or the second half of every run would be unreservable."""
        body = (
            task_block("T1", order=1, batch="b1", write_scope="tree:src")
            + task_block("T2", order=2, batch="b2", write_scope="file:src/a.py")
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=12)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        set_task_state(
            run_dir, "T1", "test-finish-T1", state="[x]",
            result=f"docs/r.md#sha256={'1a' * 32}",
            verification=f"docs/v.md#sha256={'2b' * 32}",
            source_ref="b" * 40, commits="b" * 40, integration="held")
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        self.assertEqual(
            task_row(state.validate_run(run_dir), "T2")["state"], "[~]")

    def test_reservation_persists_the_baseline_for_a_source_task(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        target = git(repo, "rev-parse", "target")
        tracker = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        row = task_row(tracker, "T1")
        self.assertEqual(row["state"], "[~]")
        self.assertEqual(row["owner"], "impl-1")
        self.assertEqual(row["attempt"], "attempt-001")
        self.assertIn("started:attempt-001", row["checkpoints"])
        self.assertIn(f"baseline:attempt-001@{target}", row["checkpoints"])

    def test_the_baseline_is_the_target_tip_and_not_the_runs_base_commit(self):
        """F3's shape, one task earlier than the task that proves it: the
        review baseline is the one persisted at reservation. `make_repo` puts
        `target` one commit ahead of `base_commit` precisely so the two cannot
        be confused by a fixture where they coincide."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        tracker = state.validate_run(run_dir)
        base = tracker["run"]["base_commit"]
        target = git(repo, "rev-parse", "target")
        self.assertNotEqual(base, target)
        checkpoints = task_row(
            state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1),
            "T1")["checkpoints"]
        self.assertIn(f"baseline:attempt-001@{target}", checkpoints)
        self.assertNotIn(base, checkpoints)

    def test_artifact_task_reservation_records_no_baseline(self):
        body = task_block("T1", kind="artifact", write_scope="tree:docs",
                          outputs="docs/out.md")
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=6)
        tracker = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        row = task_row(tracker, "T1")
        self.assertNotIn("baseline:", row["checkpoints"])
        self.assertIn("started:attempt-001", row["checkpoints"])

    def test_handles_the_first_start_only(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T1", owner="impl-9", attempt=2)
        self.assertIn("first start", str(caught.exception))

    def test_refuses_an_incomplete_dependency(self):
        body = (
            task_block("T1", order=1, batch="b1", write_scope="file:src/a1.py")
            + task_block("T2", deps="T1", order=2, batch="b2",
                         write_scope="file:src/a2.py")
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=8)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        self.assertIn("dependency", str(caught.exception))
        self.assertIn("T1", str(caught.exception))

    def test_a_completed_dependency_unblocks_the_task(self):
        body = (
            task_block("T1", order=1, batch="b1", write_scope="file:src/a1.py")
            + task_block("T2", deps="T1", order=2, batch="b2",
                         write_scope="file:src/a2.py")
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=8)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        set_task_state(
            run_dir, "T1", "test-finish-T1", state="[x]",
            result=f"docs/r.md#sha256={'1a' * 32}",
            verification=f"docs/v.md#sha256={'2b' * 32}",
            source_ref="b" * 40, commits="b" * 40, integration="held")
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        self.assertEqual(
            task_row(state.validate_run(run_dir), "T2")["state"], "[~]")

    def test_a_row_whose_kind_disagrees_with_the_approved_plan_is_refused(self):
        """The row and the plan are two records of one fact, and the plan is
        the authority. A row edited to `artifact` would otherwise skip the
        baseline the range proof needs."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        set_task_state(run_dir, "T1", "test-retype-T1", kind="artifact")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        self.assertIn("kind", str(caught.exception))

    def test_a_row_the_approved_plan_does_not_define_is_refused(self):
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks(),
                                       worker_limit=6)
        plan.write_text(
            "# Phase 04 plan\n\n" + phase_header() + "\n"
            + task_block("T9", write_scope="file:src/a9.py"),
            encoding="utf-8")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        self.assertIn("approved phase plan", str(caught.exception))

    def test_a_task_id_outside_the_token_grammar_is_named_as_such(self):
        """The transition id is built from the task id, so `_TOKEN` refuses a
        malformed one a second time inside `locked_tracker_update` -- with a
        message about replay keys. Asserting only the exception family lets the
        screen here be deleted and the test still pass."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        before = (run_dir / "progress.md").read_bytes()
        for task_id in ("T 1", "T|1", "T,1", "-T1", "", ["T1"], None, 7, b"T1"):
            with self.subTest(task_id=task_id):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.reserve_task(run_dir, task_id=task_id,
                                       owner="impl-1", attempt=1)
                self.assertIn("invalid task id", str(caught.exception))
                self.assertNotIn("invalid transition identity",
                                 str(caught.exception))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_an_owner_is_held_to_the_pinned_owner_grammar_not_to_TOKEN(self):
        """`_TOKEN` admits `/`, `:`, `@`, `+` and a trailing dot, and has no
        length bound. An owner id becomes a RESPONSE FILENAME in P03, so those
        are the exact characters `_OWNER` exists to keep out -- and a test
        whose only bad owners are `impl|1` and `impl 1` cannot tell the two
        grammars apart, because both refuse those."""
        repo, run_dir, _ = make_run(self.tmp, n_disjoint_tasks(4), worker_limit=8)
        before = (run_dir / "progress.md").read_bytes()
        rejected = ("impl|1", "impl,1", "impl 1", "", None, ["impl-1"], 7,
                    "impl/1", "impl:1", "impl@1", "impl+1", "impl.",
                    "i" * (state._OWNER_MAX + 1), ".impl")
        for owner in rejected:
            with self.subTest(owner=owner):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.reserve_task(run_dir, task_id="T1", owner=owner,
                                       attempt=1)
                self.assertIn("invalid owner", str(caught.exception))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)
        #: The accepting half. A suite of refusals alone is satisfied by a
        #: screen that refuses everything, and that screen passes.
        for index, owner in enumerate(("impl-1", "impl_2", "impl.3",
                                       "i" * state._OWNER_MAX), start=1):
            with self.subTest(accepted=owner):
                state.reserve_task(run_dir, task_id=f"T{index}", owner=owner,
                                   attempt=1)
                self.assertEqual(
                    task_row(state.validate_run(run_dir), f"T{index}")["owner"],
                    owner)

    def test_an_attempt_outside_the_positive_integers_is_named_as_such(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        before = (run_dir / "progress.md").read_bytes()
        for attempt in (0, -1, "1", True, False, 1.0, None, [1],
                        10 ** state._MAX_ATTEMPT_DIGITS):
            with self.subTest(attempt=attempt):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.reserve_task(run_dir, task_id="T1", owner="impl-1",
                                       attempt=attempt)
                self.assertIn("attempt", str(caught.exception))
                self.assertNotIn("invalid transition identity",
                                 str(caught.exception))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_a_task_the_tracker_does_not_carry_is_named_as_unknown(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="TX", owner="impl-1", attempt=1)
        self.assertIn("unknown task", str(caught.exception))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_replay_of_the_same_transition_is_inert(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        first = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        snapshot = (run_dir / "progress.md").read_bytes()
        replay = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        self.assertEqual((run_dir / "progress.md").read_bytes(), snapshot)
        self.assertEqual(
            task_row(replay, "T1")["attempt"], task_row(first, "T1")["attempt"]
        )

    def test_repository_root_comes_from_the_tracker_not_from_run_dir_depth(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        tracker = state.validate_run(run_dir)
        self.assertEqual(state._repo_dir(tracker), repo.resolve())

    def test_an_owner_already_counted_is_not_charged_a_second_slot(self):
        """`_require_capacity` counts OWNERS, not rows, so a task reserved
        under an owner the cap has already counted costs nothing more. The cap
        is full here -- worker_limit 4, cap 1 -- and the reservation still
        lands, which is the whole of what `owner not in owners` buys."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=4)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        tracker = state.validate_run(run_dir)
        self.assertEqual(state.implementation_slot_cap(
            int(tracker["run"]["worker_limit"])), 1)
        state.reserve_task(run_dir, task_id="T2", owner="impl-1", attempt=1)
        tracker = state.validate_run(run_dir)
        self.assertEqual(
            [row["id"] for row in tracker["tasks"] if row["state"] == "[~]"],
            ["T1", "T2"])
        self.assertEqual(state._implementation_owners(tracker), {"impl-1"})

    def test_the_global_limit_counts_quorum_owners_too(self):
        """The cap is not the only bound, and the second bound is REACHABLE.

        TWO in-flight quorums separate the bounds ABOVE THE FLOOR -- six brain
        owners against a cap computed from three -- which is the configuration
        this test builds.

        This docstring used to add that one quorum could never reach the second
        clause, because `i + 1 <= L - 3` and `i + 3 + 1 > L` have no common
        solution. THAT IS FALSE: the cap is `max(1, L - 3)`, so for `L <= 3` it
        is `1` and `i = 0` passes the first bound while one quorum's three
        owners already exceed `L`. The companion test below pins that regime,
        and the case list there came from a search of the integer space rather
        than from algebra re-derived by hand -- which is how this claim came to
        read as verified without being true.
        """
        repo, run_dir, _ = make_run(self.tmp, n_disjoint_tasks(6), worker_limit=10)
        self.assertEqual(state.implementation_slot_cap(10), 7)
        open_quorum_row(run_dir, owners=("brain-1", "brain-2", "brain-3"),
                        qid="3f2a1b0c9d8e", transition="test-quorum-one")
        open_quorum_row(run_dir, owners=("brain-4", "brain-5", "brain-6"),
                        qid="7d6c5b4a3e2f", transition="test-quorum-two")
        for index in range(1, 5):
            state.reserve_task(run_dir, task_id=f"T{index}",
                               owner=f"impl-{index}", attempt=1)
        tracker = state.validate_run(run_dir)
        self.assertEqual(len(state._implementation_owners(tracker)), 4)
        self.assertEqual(len(state._active_owners(tracker)), 10)
        #: Under the implementation cap -- four of seven -- and at the global
        #: limit, so only the second clause can refuse this.
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T5", owner="impl-5", attempt=1)
        self.assertIn("worker_limit", str(caught.exception))
        self.assertNotIn("implementation slots exhausted", str(caught.exception))

    def test_one_quorum_reaches_the_global_clause_wherever_the_floor_binds(self):
        """The SIMPLE reachable case, and the one the algebra above missed.

        `implementation_slot_cap` floors at one, so at `worker_limit` 1, 2 or 3
        the cap is `1` while the limit is below the four workers a quorum plus
        one implementer needs. `i = 0` therefore passes the first bound and the
        SECOND refuses -- with one quorum, not two.

        THE CASE LIST IS SEARCHED, NOT DERIVED. Enumerating every
        `(worker_limit, |impl owners|, quorum rows, |quorum owners|)` shape over
        `worker_limit` 1..12 and evaluating the two clauses exactly as the
        module writes them, the one-quorum regime is EXACTLY
        `worker_limit in {1, 2, 3}` with no implementation owner in flight --
        three shapes, no more. That is the boundary this test walks, and it
        walks `worker_limit=4` as well, the first limit at which the same
        configuration is ACCEPTED, because a test that only shows refusals
        cannot tell a bound from a blanket refusal.
        """
        refused = {}
        for limit in (1, 2, 3, 4):
            with self.subTest(worker_limit=limit):
                tmp = Path(tempfile.mkdtemp(dir=self.tmp))
                repo, run_dir, _ = make_run(tmp, three_disjoint_tasks(),
                                            worker_limit=limit)
                #: The floor, at every limit here -- so the first clause admits
                #: exactly one implementation owner and `i = 0` passes it.
                self.assertEqual(state.implementation_slot_cap(limit), 1)
                open_quorum_row(run_dir,
                                owners=("brain-1", "brain-2", "brain-3"))
                tracker = state.validate_run(run_dir)
                self.assertEqual(
                    len([row for row in tracker["quorum"]
                         if row["state"] == "in_flight"]), 1)
                self.assertEqual(state._implementation_owners(tracker), set())
                if limit == 4:
                    #: One quorum plus one implementer is exactly four, so the
                    #: second clause does not fire and the reservation stands.
                    state.reserve_task(run_dir, task_id="T1", owner="impl-1",
                                       attempt=1)
                    self.assertEqual(
                        task_row(state.validate_run(run_dir), "T1")["state"],
                        "[~]")
                    continue
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.reserve_task(run_dir, task_id="T1", owner="impl-1",
                                       attempt=1)
                #: THE DIAGNOSIS, not the family: the first clause would refuse
                #: this too if the cap were wrong, and the two are told apart
                #: only by which sentence comes back.
                self.assertIn("worker_limit", str(caught.exception))
                self.assertNotIn("implementation slots exhausted",
                                 str(caught.exception))
                refused[limit] = str(caught.exception)
        self.assertEqual(sorted(refused), [1, 2, 3])

    def test_a_finalized_quorum_holds_no_slots(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=4)
        open_quorum_row(run_dir, quorum_state="finalized")
        tracker = state.validate_run(run_dir)
        self.assertEqual(state._quorum_owners(tracker), set())
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        self.assertEqual(
            task_row(state.validate_run(run_dir), "T1")["state"], "[~]")


class ReserveTaskUnreachableScreenTests(TempDirTestCase):
    """`_require_fresh_attempt` was named as a Task 6 product. It cannot fire
    from `reserve_task`, and this is the pair of checks that closes it -- stated
    as a test rather than left for a reviewer to rediscover by mutating a screen
    that is not there. It belongs to `resume_task` (Task 7), whose row really
    does carry an attempt history.
    """

    def test_reserve_only_ever_sees_an_unstarted_row(self):
        """The first half of the closure: a row that carries any history is
        no longer `[ ]`, and `reserve_task` refuses it before an attempt is
        ever compared against that history."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=2)
        self.assertIn("first start", str(caught.exception))
        self.assertNotIn("already been used", str(caught.exception))

    def test_an_unstarted_row_may_carry_no_attempt_history_at_all(self):
        """P02's `_validate_tasks` is the half that makes the screen
        unreachable: a `[ ]` row carrying any lifecycle cell does not parse."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        tracker = state.validate_run(run_dir)
        row = task_row(tracker, "T1")
        for key in ("attempt", "checkpoints", "result"):
            with self.subTest(key=key):
                self.assertEqual(row[key], "-")
        for key in ("attempt", "checkpoints", "result"):
            with self.subTest(forbidden=key):
                with self.assertRaises(state.TrackerValidationError):
                    set_task_state(run_dir, "T1", f"test-poke-{key}",
                                   **{key: "attempt-001"})


class Task6ModuleBoundaryTests(unittest.TestCase):
    """What Task 6 must NOT have done to the module it extends."""

    def test_the_module_still_imports_nothing_outside_the_twelve(self):
        """`_git` and `_git_out` were named as Task 6 products, as
        `subprocess.run` wrappers. `subprocess` grants arbitrary command
        execution -- the single capability `ALLOWED_IMPORTS` most exists to
        withhold -- and the master plan refuses it by name."""
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {
            "__future__", "contextlib", "copy", "errno", "fcntl", "hashlib",
            "json", "msvcrt", "os", "pathlib", "time", "types"})
        self.assertNotIn("subprocess", imported)
        self.assertNotIn("re", imported)

    def test_no_module_level_name_is_bound_twice(self):
        """The mechanical form of 'a name that exists is consumed, never
        re-declared'. Task 6's brief named `_field` and `_csv`, both P02's."""
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        counts = module_bindings(ast.parse(source).body)
        self.assertEqual(
            sorted(name for name, count in counts.items() if count > 1), [])

    def test_the_task_kind_vocabulary_is_still_one_tuple(self):
        """`TASK_KINDS` (Task 2's, public) and `_TASK_KINDS` (P02's) are the
        same three words in two namespaces; Task 6 reads the plan's."""
        self.assertEqual(tuple(state.TASK_KINDS), tuple(state._TASK_KINDS))

    def test_the_occupying_states_are_a_subset_of_p02s_task_states(self):
        for value in state._OCCUPYING_STATES:
            with self.subTest(value=value):
                self.assertIn(value, state._TASK_STATES)
        self.assertNotIn("[x]", state._OCCUPYING_STATES)
        self.assertNotIn("[ ]", state._OCCUPYING_STATES)

# --------------------------------------------------------------------------
# Task 7 -- resuming an answered block.
#
# The brief's fixture wrote a decision record as a `| Field | Value |` TABLE
# and named `_decision_fields(lines)` as a product that parses one. Neither is
# this repository's grammar: `templates/decisions.md` writes `- Field: value`
# bullets, the emphasised `- **Field:** value` spelling is what P03's record
# grammar emits, and `_decision_field` reads BOTH. So the fixtures below are in
# the shipped grammar and the table spelling is pinned as a REJECTION -- a
# second field reader would have been a second answer to "what is a decision
# record", in the one file whose whole job is to be the audit trail.
# --------------------------------------------------------------------------

DECISION_FILE_HEADER = "# Pipeline Auto — Decisions\n"

#: One adopted `task.resume` record, field by field, so a case can change
#: exactly ONE thing and leave everything else valid. A fixture that broke two
#: screens at once would be refused for either reason and would distinguish
#: neither.
#:
#: The answer deliberately carries no rung name and no decimal: `parse_decisions`
#: refuses both in `Question` and `Answer`, and a fixture that tripped that
#: screen would make every case below pass for the wrong reason.
RESUME_DECISION_FIELDS = {
    "Question": BLOCK_QUESTION,
    "Axis": BLOCK_AXIS,
    "Answer": "the standard-library json module — nothing new is imported.",
    "Provenance": "quorum",
    "Decision action": "task.resume",
    "Depth": "1",
    "Scope": "T1",
    #: THE ATTEMPT THE GRANT RELEASES. Without it one adopted record authorises
    #: unlimited resumes of its task for ever: `_require_fresh_attempt` bounds
    #: the attempts a task may mint, not the grants one record may be read as.
    "Attempt": "attempt-001",
    "Status": "Adopted",
}

#: The halt arm's grant. A `halt:` block opened no quorum, so no qid exists to
#: derive an id from: the record ASSERTS the blocker string back and must be a
#: human's. Its axis differs from the quorum grant's on purpose -- an axis
#: holds at most one Adopted decision, so a file holding both would be refused
#: by `parse_decisions` before any screen under test was reached.
HALT_DECISION_FIELDS = dict(
    RESUME_DECISION_FIELDS,
    **{
        "Question": "Does T1 wait for the release host or change targets?",
        "Axis": "release-host",
        "Answer": "wait for the host — the target is not negotiable here.",
        "Provenance": "human",
        "Depth": "0",
        "Blocker": HALT_BLOCKER,
    })


def decision_record(did: str = QUORUM_GRANT, overrides=None, *, drop=(),
                    fields=None) -> str:
    """One `decisions.md` record in the shipped emphasised bullet grammar."""
    fields = dict(RESUME_DECISION_FIELDS if fields is None else fields)
    fields.update(overrides or {})
    lines = [f"\n## {did} — the answer that unblocks a blocked task\n"]
    lines += [f"- **{name}:** {value}" for name, value in fields.items()
              if name not in drop]
    return "\n".join(lines) + "\n"


def decisions_file(*records: str) -> str:
    return DECISION_FILE_HEADER + "".join(records or (decision_record(),))


RESUME_DECISION = decisions_file()


def halt_decision_record(did: str = HALT_GRANT, overrides=None, *,
                         drop=()) -> str:
    return decision_record(did, overrides, drop=drop,
                           fields=HALT_DECISION_FIELDS)


def retired_resume_decision() -> str:
    """The grant retired, beside the record that retires it.

    Both halves, because `parse_decisions` refuses a lone `Superseded` record
    as an orphan -- and a fixture built out of one would be refused before the
    Status screen under test was ever reached, which is this build's dominant
    defect wearing a passing test as a disguise.
    """
    return decisions_file(
        decision_record(QUORUM_GRANT, {"Status": "Superseded"}),
        decision_record("H-002", {"Supersedes": QUORUM_GRANT,
                                  "Provenance": "human", "Depth": "0"}),
    )


def write_decisions(run_dir, text: str) -> None:
    """Write the run's audit trail where `_decisions_text` looks for it.

    `initialize_run` already records `decisions` as
    `docs/superpowers/runs/<run-id>/decisions.md`, and `_decisions_text` is the
    ONE door onto that file. Nothing here rewrites the `## Run` cell: a helper
    that pointed the tracker somewhere else would be testing a second reader
    that does not exist.
    """
    (Path(run_dir) / "decisions.md").write_text(text, encoding="utf-8")


#: The brief's spelling, kept as the thing that must NOT parse.
TABLE_SPELLED_DECISION = """# Pipeline Auto — Decisions

## H-001 — the answer that unblocks a blocked task

| Field | Value |
| --- | --- |
| Question | Which serialiser does T1 use? |
| Answer | the standard-library json module |
| Axis | checkpoint-serialiser |
| Provenance | human |
| Decision action | task.resume |
| Depth | 0 |
| Scope | T1 |
| Status | Adopted |
"""


def blocked_run(case, *, worker_limit: int = 6, tasks=None, decisions=None,
                task_id: str = "T1", question=None):
    """One task reserved, then blocked on a question, with an adopted
    `task.resume` decision sitting in the run's audit trail.

    THE QUESTION RECORD IS PUBLISHED FOR REAL and the `Question` cell is the
    ruled `quorum:<qid>@<path>#sha256=<digest>` form over it, with the qid
    derived by the committed `derive_qid`. The harness constant this replaced
    named a file no fixture ever wrote, so no fixture in the suite held a real
    qid and nothing here could have caught a wrong qid comparison.

    Module level rather than a method, because two test classes need the same
    starting state and a helper inherited from one of them would tie the
    reachability proof to the class that happens to define it.
    """
    repo, run_dir, _ = make_run(
        case.tmp, tasks if tasks is not None else three_disjoint_tasks(),
        worker_limit=worker_limit)
    publish_question_record(run_dir)
    state.reserve_task(run_dir, task_id=task_id, owner="impl-1", attempt=1)
    set_task_state(run_dir, task_id, f"test-block-{task_id}", state="[?]",
                   question=QUESTION_REF if question is None else question)
    write_decisions(run_dir, RESUME_DECISION if decisions is None else decisions)
    return repo, run_dir


class ResumeProducesBlockTests(unittest.TestCase):
    """The Produces-block check, executable.

    The brief named `RESUME_ACTION`, `_decision_sections`, `_decision_fields`,
    `_validate_decision` and `resume_task`. Two of the five are claims about
    names the module already answers, and a module-level redefinition rebinds
    the global for every existing caller.
    """

    def test_decision_sections_is_still_p03s_section_reader(self):
        """`_decision_sections` exists at module level already: it is P03's,
        it takes the whole TEXT of `decisions.md` and it returns an ORDERED
        LIST of `(heading, fields)` pairs. The brief's version took the same
        name for a `dict` keyed by heading.

        TWO REASONS ONCE GIVEN HERE FOR REFUSING IT WERE FALSE ABOUT THE BRIEF
        and are corrected rather than dropped: the brief's dict version DOES
        raise on a repeated heading (`if current in sections: raise ...` is in
        its quoted body), and iterating a dict under `for did, fields in ...`
        unpacks each heading character-wise, so the failure is a `ValueError`
        and not a `TypeError`. Both halves are measured below. The reasons that
        hold are structural: the return type breaks every existing caller, and
        a module-level redefinition rebinds the global for all of them.
        """
        sections = state._decision_sections(RESUME_DECISION)
        self.assertIsInstance(sections, list)
        self.assertEqual([heading for heading, _ in sections], [QUORUM_GRANT])
        headings, fields = sections[0]
        self.assertEqual(headings, QUORUM_GRANT)
        self.assertEqual(fields["decision_action"], "task.resume")
        #: And the caller that would break still works over the same bytes.
        self.assertEqual(
            sorted(state.parse_decisions(RESUME_DECISION)["decisions"]),
            [QUORUM_GRANT])

    def test_the_duplicate_heading_guard_is_the_modules_and_raises_value_error(self):
        """The measured half of the correction above.

        The module's own duplicate guard fires -- so the security-relevant
        property holds here whatever the brief did -- and the brief's dict
        shape fails inside `parse_decisions` with a `ValueError`, which is what
        `for did, fields in <dict>` does to a heading that is not exactly two
        characters long. A two-character heading would unpack SILENTLY, which
        is why naming the exception correctly is not pedantry.
        """
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.parse_decisions(decisions_file(decision_record(),
                                                 decision_record()))
        self.assertIn("two ##", str(caught.exception))
        with self.assertRaises(ValueError) as unpack:
            for _did, _fields in {"H-001": {}}:
                pass
        self.assertNotIsInstance(unpack.exception, TypeError)

    def test_no_second_decision_field_reader_was_added(self):
        """`_decision_fields(lines)` was named as a Task 7 product. The module
        already reads a record's fields, through `_decision_field` per line and
        `_decision_sections` per section, and the grammar it reads is the one
        `templates/decisions.md` ships. A second reader over a `| Field |
        Value |` table would be a second answer to "what is a decision record"
        in the file whose entire job is to be the audit trail.
        """
        self.assertFalse(hasattr(state, "_decision_fields"))
        self.assertEqual(
            state._decision_field("- **Decision action:** task.resume"),
            ("decision_action", "task.resume"))
        #: The plain spelling `templates/decisions.md` ships, which also names
        #: the field `Action`. `_decision_sections` folds the two to one key
        #: through `_DECISION_FIELD_ALIASES`, so both records read alike.
        self.assertEqual(
            state._decision_field("- Action: task.resume"),
            ("action", "task.resume"))
        plain = RESUME_DECISION.replace("**", "").replace(
            "Decision action:", "Action:")
        self.assertEqual(
            state._decision_sections(plain)[0][1]["decision_action"],
            "task.resume")

    def test_the_table_spelling_is_not_a_decision_record(self):
        """The rejection half of the rule above, over the brief's own fixture:
        a table-bodied record states no field the module can read, so it is
        refused as a record missing every field -- never read as one."""
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.parse_decisions(TABLE_SPELLED_DECISION)
        self.assertIn("missing", str(caught.exception))

    def test_resume_action_is_one_of_p03s_five_decision_actions(self):
        """`RESUME_ACTION` is a new name and a value that already existed.
        A sixth action nothing else honours would be an authority no validator
        in this run would ever act on, so the constant is pinned to the set
        `parse_decisions` screens against and to the shipped template."""
        self.assertEqual(state.RESUME_ACTION, "task.resume")
        self.assertTrue(state._member(state.RESUME_ACTION,
                                      state._DECISION_ACTIONS))
        template = (SKILL_DIR / "templates" / "decisions.md").read_text(
            encoding="utf-8")
        self.assertIn(state.RESUME_ACTION, template)


class FreshAttemptReachabilityTests(TempDirTestCase):
    """`_require_fresh_attempt` is Task 7's, and Task 6 proved why.

    `ReserveTaskUnreachableScreenTests` closed it out of `reserve_task` with
    two halves: a `[ ]` row is the only row `reserve_task` accepts, and P02's
    `_validate_tasks` refuses a `[ ]` row that carries any lifecycle cell at
    all. Both halves of the OPPOSITE claim are pinned here: a `[?]` row really
    does carry an attempt history, and the screen really does fire on it.
    """

    def blocked(self, **kwargs):
        return blocked_run(self, **kwargs)

    def test_a_blocked_row_really_carries_an_attempt_history(self):
        """Half one: reachability of the INPUT. Unlike the `[ ]` row Task 6
        measured, a `[?]` row carries an owner, an attempt and checkpoints --
        P02's `_validate_tasks` requires all three of a started row -- so
        there is an attempt history for a fresh-attempt screen to consult."""
        repo, run_dir = self.blocked()
        row = task_row(state.validate_run(run_dir), "T1")
        self.assertEqual(row["state"], "[?]")
        self.assertEqual(row["attempt"], "attempt-001")
        self.assertIn("started:attempt-001", row["checkpoints"])
        self.assertEqual(state._recorded_attempts(row), {"attempt-001"})

    def test_the_screen_refuses_an_attempt_the_history_already_records(self):
        """Half two: reachability of the REFUSAL, with every other screen
        passing. The prior attempt matches, the decision is adopted and
        scoped, the scopes are disjoint and capacity is spare -- so the only
        thing that can refuse this is the fresh-attempt screen."""
        repo, run_dir = self.blocked()
        state.resume_task(run_dir, task_id="T1", prior_attempt=1,
                          new_owner="impl-2", new_attempt=2,
                          decision_ref=QUORUM_GRANT)
        set_task_state(run_dir, "T1", "test-block-T1-again", state="[?]",
                       question=QUESTION_REF)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(run_dir, task_id="T1", prior_attempt=2,
                              new_owner="impl-3", new_attempt=1,
                              decision_ref=QUORUM_GRANT)
        message = str(caught.exception)
        self.assertIn("already been used", message)
        self.assertIn("attempt-001", message)
        for other in ("blocked attempt", "does not resolve", "write scope",
                      "quorum", "dependency"):
            with self.subTest(other=other):
                self.assertNotIn(other, message)

    def test_the_used_set_comes_from_the_history_not_from_the_attempt_cell(self):
        """What separates the screen from `row['attempt'] != token`. After one
        resume the row's `Attempt` cell is `attempt-002`; `attempt-001` exists
        ONLY inside the checkpoint history, and it is still spent."""
        repo, run_dir = self.blocked()
        tracker = state.resume_task(run_dir, task_id="T1", prior_attempt=1,
                                    new_owner="impl-2", new_attempt=2,
                                    decision_ref=QUORUM_GRANT)
        row = task_row(tracker, "T1")
        self.assertEqual(row["attempt"], "attempt-002")
        self.assertIn("attempt-001", row["checkpoints"])
        self.assertEqual(state._recorded_attempts(row),
                         {"attempt-001", "attempt-002"})

    def test_reusing_the_prior_attempt_is_the_same_screen(self):
        """`new_attempt == prior_attempt` is not a second rule. The prior
        attempt is in the history by construction, so one screen with one
        diagnosis answers it -- two would be two checks refusing one input
        where only the wording differs, and the second could be deleted
        without a test noticing."""
        repo, run_dir = self.blocked()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(run_dir, task_id="T1", prior_attempt=1,
                              new_owner="impl-2", new_attempt=1,
                              decision_ref=QUORUM_GRANT)
        self.assertIn("already been used", str(caught.exception))

    def test_a_fresh_attempt_need_not_be_the_next_integer(self):
        """The accepting half. A screen that demanded `prior + 1` would refuse
        every case above and prove nothing; attempts are identities, not a
        counter the module owns."""
        repo, run_dir = self.blocked()
        tracker = state.resume_task(run_dir, task_id="T1", prior_attempt=1,
                                    new_owner="impl-2", new_attempt=7,
                                    decision_ref=QUORUM_GRANT)
        self.assertEqual(task_row(tracker, "T1")["attempt"], "attempt-007")

    def test_the_recorded_set_reads_every_side_of_a_resume_marker(self):
        """`resumed:attempt-001->attempt-002@H-001` names two attempts inside
        one checkpoint entry, and a scan that split on `:` and `@` alone would
        see the pair as one unrecognisable token and spend neither.

        THE `->` HALF IS THE ONLY HALF THIS FIXTURE PROVES, and the name once
        claimed both. Every token here is reachable by a SECOND route --
        `attempt-001` through `started:`, `attempt-002` left of the second
        `->`, `attempt-004` from the `Attempt` cell -- so dropping `"@"` from
        `_CHECKPOINT_DELIMITERS` leaves this assertion green. The case below
        is the missing half.
        """
        row = {
            "attempt": "attempt-004",
            "checkpoints": ("started:attempt-001,baseline:attempt-001@" + "a" * 40
                            + ",resumed:attempt-001->attempt-002@H-001"
                            + ",resumed:attempt-002->attempt-004@Q-abc123def456"),
        }
        self.assertEqual(
            state._recorded_attempts(row),
            {"attempt-001", "attempt-002", "attempt-004"})

    def test_an_attempt_reachable_only_left_of_an_at_sign_is_still_spent(self):
        """`"@"`'s own half, and it is the M17 argument mirrored.

        `_recorded_attempts`'s domain is every row `_validate_tasks` admits,
        not only the rows this module writes -- which is exactly why the
        `Attempt` cell is seeded into the candidate list. `_validate_tasks`
        nowhere requires `Checkpoints` to mention the `Attempt` cell, so a row
        whose only record of a spent attempt is a `baseline:<token>@<sha>`
        entry is admissible; here `attempt-003` is reachable through nothing
        but the left side of that `@`. Dropping `"@"` from
        `_CHECKPOINT_DELIMITERS` hands `attempt-003` out a second time, which
        is fault F6 -- two pieces of work under one identity.
        """
        row = {"attempt": "attempt-009",
               "checkpoints": "baseline:attempt-003@" + "a" * 40}
        self.assertEqual(state._recorded_attempts(row),
                         {"attempt-003", "attempt-009"})
        #: And the refusal the set exists to produce, on the same row.
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._require_fresh_attempt(dict(row, id="T1"), "attempt-003")
        self.assertIn("already been used", str(caught.exception))

    def test_the_attempt_cell_counts_even_when_the_history_omits_it(self):
        """The two cells are not guaranteed to agree. P02's `_validate_tasks`
        requires a started row to carry BOTH an `Attempt` and `Checkpoints`
        and never requires the second to mention the first, so a row whose
        `Attempt` cell is the only record of an attempt has still spent it --
        and a scan that read the history alone would hand that token out
        again."""
        self.assertEqual(
            state._recorded_attempts(
                {"attempt": "attempt-002", "checkpoints": "started:attempt-001"}),
            {"attempt-001", "attempt-002"})

    def test_an_unstarted_row_records_no_attempt_at_all(self):
        """The empty case, which is what makes the screen inert on the row
        `reserve_task` handles -- Task 6's closure, restated from this side."""
        self.assertEqual(
            state._recorded_attempts({"attempt": "-", "checkpoints": "-"}),
            set())


class ResumeTaskTests(TempDirTestCase):

    def blocked(self, **kwargs):
        return blocked_run(self, **kwargs)

    def test_moves_an_answered_block_back_to_active(self):
        repo, run_dir = self.blocked()
        tracker = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref=QUORUM_GRANT)
        row = task_row(tracker, "T1")
        self.assertEqual(row["state"], "[~]")
        self.assertEqual(row["owner"], "impl-2")
        self.assertEqual(row["attempt"], "attempt-002")
        self.assertIn(f"resumed:attempt-001->attempt-002@{QUORUM_GRANT}",
                      row["checkpoints"])
        #: AND THE QUESTION CELL SURVIVES UNTOUCHED. It was once overwritten
        #: with `resolved:<ref>`, which destroyed the tracker's only pointer
        #: to what was asked in the same write that acted on the answer -- so
        #: a grant bound to the wrong block could not be audited afterwards.
        #: The resume is recorded where a record belongs: the append-only
        #: `Checkpoints` cell, asserted one line above.
        self.assertEqual(row["question"], QUESTION_REF)

    def test_the_prior_attempts_history_survives_the_resume(self):
        """`_append_history`, not a rewrite: the reservation's own baseline is
        one end of the range proof for the work attempt one already did, and a
        resume that dropped it would erase the evidence rather than add to it.
        """
        repo, run_dir = self.blocked()
        first = git(repo, "rev-parse", "target")
        tracker = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref=QUORUM_GRANT)
        checkpoints = task_row(tracker, "T1")["checkpoints"]
        self.assertIn("started:attempt-001", checkpoints)
        self.assertIn(f"baseline:attempt-001@{first}", checkpoints)

    def test_records_a_fresh_baseline_for_a_source_task(self):
        """The target tip AT THE RESUME, not the one attempt one was given.
        The fixture moves `target` on purpose: where the two coincide, "the
        baseline is re-derived" and "the baseline is copied forward" are the
        same bytes and the test distinguishes neither."""
        repo, run_dir = self.blocked()
        before = git(repo, "rev-parse", "target")
        (repo / "src" / "later.py").write_text("later = 1\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "target moved")
        git(repo, "branch", "-f", "target", "HEAD")
        moved = git(repo, "rev-parse", "target")
        self.assertNotEqual(before, moved)
        tracker = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref=QUORUM_GRANT)
        checkpoints = task_row(tracker, "T1")["checkpoints"]
        self.assertIn(f"baseline:attempt-002@{moved}", checkpoints)
        self.assertNotIn(f"baseline:attempt-002@{before}", checkpoints)

    def test_an_artifact_task_resume_records_no_baseline(self):
        """An artifact task produces no source range, so a baseline would be
        one end of a proof that is never drawn -- the same ruling
        `reserve_task` makes, asked again at the transition that could quietly
        stop making it."""
        repo, run_dir = self.blocked(tasks=task_block(
            "T1", kind="artifact", write_scope="tree:docs", outputs="docs/out.md"))
        tracker = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref=QUORUM_GRANT)
        checkpoints = task_row(tracker, "T1")["checkpoints"]
        self.assertIn(f"resumed:attempt-001->attempt-002@{QUORUM_GRANT}", checkpoints)
        self.assertNotIn("baseline:", checkpoints)

    def test_requires_the_matching_blocked_attempt(self):
        repo, run_dir = self.blocked()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=9, new_owner="impl-2",
                new_attempt=2, decision_ref=QUORUM_GRANT)
        self.assertIn("blocked attempt", str(caught.exception))
        self.assertIn("attempt-009", str(caught.exception))

    def test_refuses_an_active_task(self):
        """Context compaction and a restarted controller are not a blocked-task
        retry. A `[~]` row has nothing to answer, so resuming it would mint a
        second attempt and a second owner for work already in flight."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(),
                                    worker_limit=6)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        write_decisions(run_dir, RESUME_DECISION)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref=QUORUM_GRANT)
        self.assertIn("blocked attempt", str(caught.exception))
        self.assertIn("[~]", str(caught.exception))

    def test_refuses_an_unstarted_task(self):
        repo, run_dir = self.blocked()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(
                run_dir, task_id="T2", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref=QUORUM_GRANT)
        self.assertIn("blocked attempt", str(caught.exception))

    def test_refuses_a_completed_task(self):
        repo, run_dir = self.blocked()
        set_task_state(
            run_dir, "T1", "test-finish-T1", state="[x]",
            result=f"docs/r.md#sha256={'1a' * 32}",
            verification=f"docs/v.md#sha256={'2b' * 32}",
            source_ref="b" * 40, commits="b" * 40, integration="held",
            question="-")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref=QUORUM_GRANT)
        self.assertIn("blocked attempt", str(caught.exception))

    def test_an_unknown_task_is_a_stop(self):
        repo, run_dir = self.blocked()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(
                run_dir, task_id="T9", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref=QUORUM_GRANT)
        self.assertIn("unknown task", str(caught.exception))

    def test_the_decision_ref_must_be_a_decision_id(self):
        """Screened BEFORE the lock and before `locked_tracker_update` sees it.
        The ref is interpolated into the replay key, so a malformed one would
        otherwise come back as `invalid transition identity` -- a diagnosis
        about a transition name, for a caller that named a decision wrongly."""
        repo, run_dir = self.blocked()
        for ref in ("", "-", "task.resume", "H", "H-", "Q-0001", "H-٣",
                    "H-001|x", "resolved:H-001", None, ["H-001"]):
            with self.subTest(ref=ref):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.resume_task(
                        run_dir, task_id="T1", prior_attempt=1,
                        new_owner="impl-2", new_attempt=2, decision_ref=ref)
                message = str(caught.exception)
                self.assertIn("decision", message)
                self.assertNotIn("invalid transition identity", message)

    def test_a_human_grant_answers_a_halt_arm_block(self):
        """The OTHER arm, and the other namespace with it.

        A `halt:` block opened no quorum, so no qid exists and the `Q-<qid>`
        binding has nothing to compare; the grant asserts the blocker string
        back and must be a human's. The quorum arm is the default fixture
        everywhere else in this class, so this is where `H-<n>` is shown to
        still resume something -- a screen that admitted only one of the two
        namespaces would make half the blocks in a run unresumable.
        """
        repo, run_dir = self.blocked(
            question=HALT_REF,
            decisions=decisions_file(halt_decision_record()))
        tracker = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref=HALT_GRANT)
        row = task_row(tracker, "T1")
        self.assertEqual(row["state"], "[~]")
        self.assertIn(f"resumed:attempt-001->attempt-002@{HALT_GRANT}",
                      row["checkpoints"])
        self.assertEqual(row["question"], HALT_REF)

    def test_the_replay_key_carries_the_decision_ref(self):
        """A re-issue citing a DIFFERENT decision is a different transition.

        `resume_task`'s docstring argues that `decision_ref` is interpolated
        into the replay key, and nothing asserted it: with the ref dropped
        from the key, the call below collides with the one above it, is
        recognised as a replay, and returns SUCCESS -- having never resolved
        `H-002`, never checked it was Adopted, never checked its action, its
        scope, its attempt or its binding. An inert replay that validates
        nothing and reports success is the worst of the two failure modes.

        The existing replay case re-issues the SAME ref and passes identically
        either way, which is why it could not catch this.
        """
        repo, run_dir = self.blocked(decisions=decisions_file(
            decision_record(),
            decision_record("H-002", {"Provenance": "human", "Depth": "0",
                                      "Axis": "second-axis"})))
        state.resume_task(run_dir, task_id="T1", prior_attempt=1,
                          new_owner="impl-2", new_attempt=2,
                          decision_ref=QUORUM_GRANT)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(run_dir, task_id="T1", prior_attempt=1,
                              new_owner="impl-9", new_attempt=2,
                              decision_ref="H-002")
        self.assertIn("blocked attempt", str(caught.exception))

    def test_a_refused_resume_leaves_the_tracker_byte_identical(self):
        repo, run_dir = self.blocked()
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref="H-404")
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_a_reissued_resume_replays_and_is_inert(self):
        """A controller interrupted mid-transition re-issues the same id; the
        replay must return current state rather than mint a third attempt."""
        repo, run_dir = self.blocked()
        first = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref=QUORUM_GRANT)
        again = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref=QUORUM_GRANT)
        self.assertEqual(again["run"]["revision"], first["run"]["revision"])
        self.assertEqual(task_row(again, "T1")["checkpoints"],
                         task_row(first, "T1")["checkpoints"])

    def test_still_honours_the_implementation_slot_cap(self):
        """F2 again, at the transition that could quietly stop asking. An
        answered block buys no capacity: the run waits rather than
        over-subscribing the slots the next quorum needs."""
        repo, run_dir = self.blocked(worker_limit=6)
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        state.reserve_task(run_dir, task_id="T3", owner="impl-3", attempt=1)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-4",
                new_attempt=2, decision_ref=QUORUM_GRANT)
        message = str(caught.exception)
        self.assertIn("quorum", message)
        self.assertNotIn("write scope", message)

    def test_resuming_with_the_same_owner_at_a_full_cap_is_allowed(self):
        """The accepting half. The blocked worker already holds the slot, so
        handing the task back to it adds nobody -- and a cap that refused this
        would make a full run permanently unable to answer its own block."""
        repo, run_dir = self.blocked(worker_limit=6)
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        state.reserve_task(run_dir, task_id="T3", owner="impl-3", attempt=1)
        tracker = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-1",
            new_attempt=2, decision_ref=QUORUM_GRANT)
        self.assertEqual(task_row(tracker, "T1")["owner"], "impl-1")
        self.assertEqual(len(state._implementation_owners(tracker)), 3)

    def test_still_honours_the_scope_conflict_rule(self):
        """F1 at the resume. Capacity is spare -- twelve workers, two in use --
        so the capacity wording must be absent or this proves nothing."""
        body = (
            task_block("T1", order=1, batch="b1", write_scope="tree:src")
            + task_block("T2", order=2, batch="b2", write_scope="file:src/a.py")
        )
        repo, run_dir = self.blocked(worker_limit=12, tasks=body)
        #: T2 is forced active rather than reserved, and it has to be:
        #: `reserve_task` refuses it precisely because blocked T1 still holds
        #: `tree:src`. Which is the point -- the only way into this state is
        #: around the module, so the resume asks again rather than inheriting
        #: a verdict the reservation once reached.
        set_task_state(run_dir, "T2", "test-force-T2", state="[~]",
                       owner="impl-2", attempt="attempt-001",
                       checkpoints="started:attempt-001")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-3",
                new_attempt=2, decision_ref=QUORUM_GRANT)
        message = str(caught.exception)
        self.assertIn("write scope", message)
        self.assertIn("T2", message)
        self.assertNotIn("quorum", message)

    def test_still_honours_an_incomplete_dependency(self):
        """A dependency can regress between the block and the answer -- the
        answer may be exactly "T1 was wrong, redo it" -- so the resume asks
        again rather than trusting the check the reservation once passed."""
        body = (
            task_block("T1", order=1, batch="b1", write_scope="file:src/a1.py")
            + task_block("T2", deps="T1", order=2, batch="b2",
                         write_scope="file:src/a2.py")
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=8)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        set_task_state(
            run_dir, "T1", "test-finish-T1", state="[x]",
            result=f"docs/r.md#sha256={'1a' * 32}",
            verification=f"docs/v.md#sha256={'2b' * 32}",
            source_ref="b" * 40, commits="b" * 40, integration="held")
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        publish_question_record(run_dir)
        set_task_state(run_dir, "T2", "test-block-T2", state="[?]",
                       question=QUESTION_REF)
        write_decisions(run_dir, decisions_file(
            decision_record(QUORUM_GRANT, {"Scope": "T2"})))
        set_task_state(run_dir, "T1", "test-unstart-T1", state="[ ]",
                       **{key: "-" for key in state._TASK_LIFECYCLE})
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(
                run_dir, task_id="T2", prior_attempt=1, new_owner="impl-3",
                new_attempt=2, decision_ref=QUORUM_GRANT)
        message = str(caught.exception)
        self.assertIn("dependency", message)
        self.assertIn("T1", message)
        self.assertNotIn("quorum", message)
        self.assertNotIn("write scope", message)


class ResumeDecisionValidationTests(TempDirTestCase):
    """Transition authority comes from an explicit adopted `task.resume`
    decision scoped to this task, never from the wording of an answer.

    Every case below changes exactly ONE field of the same record, so a
    rejection names the screen it came from; and each asserts the other
    screens' wordings are ABSENT, because two checks refusing one input where
    only the diagnosis differs is a check that can be deleted silently.
    """

    #: One distinctive phrase per screen. They are phrases rather than words
    #: because a bare "answer" occurs in the prose of half the other
    #: diagnoses, and an absence assertion that trips on incidental wording
    #: tests the sentences rather than the screens.
    OTHER_DIAGNOSES = ("does not resolve", "and not Adopted",
                       "rather than 'task.resume'", "not scoped to task",
                       "where its answer belongs", "grants the resume of",
                       "does not answer what task", "states Blocker",
                       "halted rather than in quorum", "which is neither",
                       "which states no blocker", "which names no qid")

    def resume(self, decisions=None, *, decision_ref: str = QUORUM_GRANT,
               write: bool = True, question: str = QUESTION_REF):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(),
                                    worker_limit=6)
        publish_question_record(run_dir)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        set_task_state(run_dir, "T1", "test-block-T1", state="[?]",
                       question=question)
        if write:
            write_decisions(run_dir,
                            RESUME_DECISION if decisions is None else decisions)
        return run_dir, lambda: state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref=decision_ref)

    def refuse(self, expected: str, **kwargs) -> str:
        run_dir, call = self.resume(**kwargs)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.TrackerValidationError) as caught:
            call()
        message = str(caught.exception)
        self.assertIn(expected, message)
        for other in self.OTHER_DIAGNOSES:
            if other == expected:
                continue
            with self.subTest(absent=other):
                self.assertNotIn(other, message)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)
        return message

    def test_the_accepting_case(self):
        """A suite of refusals alone is satisfied by a validator that refuses
        everything, and that validator would make every block permanent."""
        run_dir, call = self.resume()
        self.assertEqual(task_row(call(), "T1")["state"], "[~]")

    def test_rejects_a_decision_that_does_not_resolve(self):
        self.refuse("does not resolve", decision_ref="H-404")

    def test_rejects_a_missing_decisions_file(self):
        """An absent audit trail resolves nothing; it never reads as an
        unrestricted grant."""
        self.refuse("does not resolve", write=False)

    def test_rejects_a_superseded_decision(self):
        """The grant is retired beside the record that retires it, so the file
        parses and the Status screen is the only thing left to refuse it."""
        self.refuse("and not Adopted", decisions=retired_resume_decision())

    def test_rejects_a_decision_without_the_task_resume_action(self):
        self.refuse("rather than 'task.resume'",
                    decisions=decisions_file(
                        decision_record(QUORUM_GRANT, {"Decision action": "none"})))

    def test_rejects_a_quorum_adopt_action_as_a_resume_grant(self):
        """`quorum.adopt` is an adopted decision with a real answer in it, and
        it still authorises no task transition. The action is the authority."""
        self.refuse("rather than 'task.resume'",
                    decisions=decisions_file(decision_record(
                        QUORUM_GRANT, {"Decision action": "quorum.adopt"})))

    def test_rejects_a_decision_scoped_to_another_task(self):
        self.refuse("not scoped to task",
                    decisions=decisions_file(
                        decision_record(QUORUM_GRANT, {"Scope": "T3"})))

    def test_rejects_a_decision_with_no_scope_at_all(self):
        self.refuse("not scoped to task",
                    decisions=decisions_file(
                        decision_record(QUORUM_GRANT, drop=("Scope",))))

    def test_a_scope_naming_several_tasks_includes_this_one(self):
        """The accepting half of the scope rule: `Scope` is a multi-valued
        cell, so an answer that unblocks two tasks unblocks each of them."""
        run_dir, call = self.resume(decisions=decisions_file(
            decision_record(QUORUM_GRANT, {"Scope": "T3,T1"})))
        self.assertEqual(task_row(call(), "T1")["state"], "[~]")

    def test_a_scope_that_merely_contains_the_task_id_is_not_a_scope(self):
        """Membership, not substring. `T10` names another task, and a
        containment test would let it resume this one."""
        self.refuse("not scoped to task",
                    decisions=decisions_file(
                        decision_record(QUORUM_GRANT, {"Scope": "T10"})))

    def test_rejects_the_absence_marker_as_an_answer(self):
        """`-` is this schema's empty cell. An adopted record carrying it has
        recorded that a question was asked and nothing that answers it."""
        self.refuse("where its answer belongs",
                    decisions=decisions_file(
                        decision_record(QUORUM_GRANT, {"Answer": "-"})))

    def test_a_generic_approval_is_refused_upstream_by_parse_decisions(self):
        """Not a screen of this task's: `parse_decisions` already refuses a
        rubber stamp as an answer to an unresolved choice, at the moment the
        record is read. Asserting the upstream diagnosis is what keeps a
        duplicate out of `_validate_decision`, where it would be a second
        check nothing could delete visibly."""
        run_dir, call = self.resume(decisions=decisions_file(
            decision_record(QUORUM_GRANT, {"Answer": "approved"})))
        with self.assertRaises(state.TrackerValidationError) as caught:
            call()
        self.assertIn("generic approval", str(caught.exception))


    # --- the grant is bound to the BLOCK and to the ATTEMPT ---------------
    #
    # Everything above binds the grant to the TASK. A decision answering an
    # entirely different question, scoped to T1 with action `task.resume`,
    # satisfied every one of those screens and resumed T1 -- with no quorum,
    # no escalation and no unit of the drift budget that exists to cap machine
    # decision authority. No code in this module ever writes a `task.resume`
    # record, so every such grant is hand-authored into an unsigned,
    # hand-editable file.

    def test_the_grant_must_name_the_attempt_it_releases(self):
        """A grant is SPENT, not standing. `_require_fresh_attempt` bounds the
        attempts a task may mint, not the number of times one adopted record
        may be read as authority -- so without this screen a single grant
        resumes its task for ever."""
        message = self.refuse("grants the resume of", decisions=decisions_file(
            decision_record(QUORUM_GRANT, {"Attempt": "attempt-007"})))
        self.assertIn("attempt-007", message)
        self.assertIn("attempt-001", message)

    # --- THREE INPUTS, NOT ONE. A field can be absent, present and empty,
    # or present and wrong, and only the third is what a naive screen tests.
    # The first two are where a `.get` DEFAULT decides the answer: read as
    # `record.get("attempt", row["attempt"])` the absent field compares equal
    # to itself and the screen passes, which is the whole hole wearing the
    # screen that closes it as a disguise. Each input gets its own case.

    def test_a_grant_that_names_no_attempt_at_all_is_refused(self):
        """Input one: the field is ABSENT. This is the case a default of
        `row["attempt"]` would silently accept -- and the comparison below it
        would still read as correct, so no mutant aimed at the `if` finds
        it."""
        message = self.refuse("grants the resume of", decisions=decisions_file(
            decision_record(QUORUM_GRANT, drop=("Attempt",))))
        self.assertIn(repr(state._ABSENT_CELL), message)

    def test_a_grant_whose_attempt_is_the_absence_marker_is_refused(self):
        """Input two: the field is PRESENT and holds `-`, this schema's empty
        cell. A record that wrote the field down and left it empty has
        recorded that a grant names an attempt and named none."""
        self.refuse("grants the resume of", decisions=decisions_file(
            decision_record(QUORUM_GRANT, {"Attempt": state._ABSENT_CELL})))

    def test_a_grant_answering_another_question_is_refused(self):
        """THE CRITICAL CASE. The record resolves, is Adopted, carries
        `task.resume`, is scoped to T1 and names the blocked attempt -- and it
        settles a DIFFERENT question. `settle_quorum` mints a quorum decision
        id as `"Q-" + qid`, so the id carries the identity of the question it
        answers and the comparison is arithmetic rather than trust."""
        other = state.derive_qid("Does T1 retry on a transport timeout?",
                                 "transport-retry")
        self.assertNotEqual(other, BLOCK_QID)
        message = self.refuse("does not answer what task", decisions=decisions_file(
            decision_record(f"Q-{other}", {"Axis": "transport-retry"})),
            decision_ref=f"Q-{other}")
        self.assertIn(BLOCK_QID, message)

    def test_a_qid_differing_in_one_character_is_another_question(self):
        """THE WHOLE COMPARISON, NOT MOST OF IT.

        A qid is twelve hex characters and `derive_qid` is a truncated
        sha256, so two questions' qids differ in whatever characters they
        differ in -- there is no prefix that identifies a question. A
        comparison that dropped ONE character from each side (`[:-1]`)
        survived the whole suite, because every other case here names a qid
        that differs from the block's in many places at once. This one
        differs in exactly the last character, which is the near-miss a hand
        edit of an unsigned `decisions.md` actually produces.
        """
        near = BLOCK_QID[:-1] + ("0" if BLOCK_QID[-1] != "0" else "1")
        self.assertNotEqual(near, BLOCK_QID)
        self.assertEqual(near[:-1], BLOCK_QID[:-1])
        self.assertTrue(state._decision_id(f"Q-{near}"))
        message = self.refuse("does not answer what task",
                              decisions=decisions_file(decision_record(
                                  f"Q-{near}", {"Axis": "near-miss-axis"})),
                              decision_ref=f"Q-{near}")
        self.assertIn(BLOCK_QID, message)

    def test_a_reopen_of_the_same_question_is_a_different_block(self):
        """Re-opens close for free. `derive_reopen_qid` mints a DIFFERENT qid
        for a re-ask of the very same question on the very same axis, so the
        answer adopted the first time round cannot resume the re-asked block
        -- which is the whole of what separates "this was settled" from "a run
        asking again until it likes the answer"."""
        reopened = state.derive_reopen_qid(BLOCK_QUESTION, BLOCK_AXIS,
                                           QUORUM_GRANT)
        self.assertNotEqual(reopened, BLOCK_QID)
        message = self.refuse(
            "does not answer what task",
            question=f"quorum:{reopened}@{QUESTION_RECORD_PATH}#sha256={'0a' * 32}")
        self.assertIn(reopened, message)

    def test_a_human_grant_cannot_resume_a_quorum_arm_block(self):
        """The sharp end stated from the other side: a hand-authored `H-<n>`
        record can never name a qid, so it can never clear a block that a
        quorum was opened for. That is the escalation route being preserved
        rather than a spelling rule."""
        self.refuse("does not answer what task", decisions=decisions_file(
            decision_record("H-001", {"Provenance": "human", "Depth": "0"})),
            decision_ref="H-001")

    def test_a_halt_arm_grant_must_repeat_the_blocker_verbatim(self):
        """The asserted arm. No quorum was opened, so no qid exists and there
        is nothing to derive from: the record states the blocker back and the
        two strings agreeing is the whole of the binding. The docstring and
        `templates/decisions.md` both say so in those words -- nothing here
        can tell a correctly copied blocker from a carelessly copied one."""
        self.refuse("states Blocker", question=HALT_REF,
                    decisions=decisions_file(halt_decision_record(
                        overrides={"Blocker": "the release host is fine"})),
                    decision_ref=HALT_GRANT)

    def test_a_halt_arm_grant_with_no_blocker_field_is_refused(self):
        """Input one for the asserted arm: the field is ABSENT."""
        self.refuse("states Blocker", question=HALT_REF,
                    decisions=decisions_file(
                        halt_decision_record(drop=("Blocker",))),
                    decision_ref=HALT_GRANT)

    def test_a_halt_arm_grant_whose_blocker_is_the_absence_marker_is_refused(self):
        """Input two for the asserted arm: PRESENT and empty."""
        self.refuse("states Blocker", question=HALT_REF,
                    decisions=decisions_file(halt_decision_record(
                        overrides={"Blocker": state._ABSENT_CELL})),
                    decision_ref=HALT_GRANT)

    def test_a_halt_on_nothing_is_not_a_blocker_a_grant_can_repeat(self):
        """THE FAIL-OPEN THE TWO ABOVE WOULD OTHERWISE HIDE, and the reason
        `_ABSENT_CELL` is refused explicitly rather than left to lose the
        comparison.

        `_validate_tasks` requires a `[?]` row's `Question` cell to not BE
        `-`; it says nothing about `halt:-`, which is legal and states a halt
        on nothing. The reason split out of that cell is then `-` -- exactly
        the value `record.get("blocker", _ABSENT_CELL)` returns for a record
        with NO `Blocker` field. So the two sides matched, and a grant
        asserting nothing cleared a halt asserting nothing, through a screen
        whose comparison was perfectly correct.
        """
        message = self.refuse(
            "which states no blocker",
            question=f"{state._QUESTION_HALT_ARM}{state._ABSENT_CELL}",
            decisions=decisions_file(halt_decision_record(drop=("Blocker",))),
            decision_ref=HALT_GRANT)
        self.assertIn("nothing here to repeat", message)

    def test_a_halt_naming_no_reason_at_all_is_refused(self):
        """The same hole reached with an empty reason rather than the marker."""
        self.refuse("which states no blocker",
                    question=state._QUESTION_HALT_ARM,
                    decisions=decisions_file(halt_decision_record()),
                    decision_ref=HALT_GRANT)

    def test_a_quorum_arm_cell_naming_no_qid_is_refused(self):
        """The third default of the same shape. An empty qid made the screen
        compare `decision_ref` against the literal `'Q-'`, which only
        `_decision_id` two functions away refuses -- an unreachability this
        screen should not rest on, and a diagnosis naming `qid ''`."""
        self.refuse("which names no qid",
                    question=state._QUESTION_QUORUM_ARM)

    def test_a_machine_answer_cannot_settle_a_halt(self):
        """`Provenance: human` on the asserted arm. A halt opened no question,
        so there is no qid a quorum answer could be bound to it by -- and a
        machine answer accepted here would clear a halt with the one thing a
        halt exists to require absent."""
        self.refuse("halted rather than in quorum", question=HALT_REF,
                    decisions=decisions_file(
                        decision_record(QUORUM_GRANT,
                                        {"Blocker": HALT_BLOCKER})))

    def test_a_question_cell_in_neither_arm_binds_nothing(self):
        """One arm or the other, never neither. The cell below is exactly what
        this transition USED to overwrite the question with -- which is the
        second reason that overwrite was wrong: it turned a bound block into
        an unbindable one while destroying the pointer to what was asked."""
        message = self.refuse("which is neither",
                              question=f"resolved:{QUORUM_GRANT}")
        self.assertIn("resolved:", message)

    def test_the_published_question_record_is_a_real_one(self):
        """What makes every case above capable of failing.

        The harness constant these fixtures replaced pointed at `docs/q.md`,
        a file nothing ever wrote, so no fixture held a real qid at all. Here
        the record is on disk where `_question_record` reads it, the module
        re-derives the qid from the record's own question and axis and agrees
        with the cell, and the digest in the cell is over the bytes written.
        """
        run_dir, _call = self.resume()
        record = state._question_record(run_dir, BLOCK_QID)
        self.assertEqual(record["question"], BLOCK_QUESTION)
        self.assertEqual(record["axis"], BLOCK_AXIS)
        self.assertEqual(state.derive_qid(record["question"], record["axis"]),
                         BLOCK_QID)
        written = (Path(run_dir) / "quorum" / BLOCK_QID / "question.md"
                   ).read_bytes()
        self.assertTrue(QUESTION_REF.endswith(
            hashlib.sha256(written).hexdigest()))
        self.assertIn(f"quorum:{BLOCK_QID}@", QUESTION_REF)

    def test_the_grant_is_read_from_the_file_the_run_says_is_its_trail(self):
        """M2. `_decisions_text` reads `<run_dir>/decisions.md` and the `##
        Run` table separately records a `decisions` pointer; nothing checked
        they agree. They always do today, because `initialize_run` writes the
        constant -- but this transition is the first to rest a GRANT on that
        file, and a pointer written elsewhere would have authority read out of
        a document the run does not treat as its audit trail."""
        run_dir, call = self.resume()

        def repoint(tracker: dict) -> dict:
            tracker["run"]["decisions"] = "docs/superpowers/runs/run-1/other.md"
            return tracker

        state.locked_tracker_update(run_dir, transition_id="test-repoint",
                                    mutate=repoint)
        with self.assertRaises(state.TrackerValidationError) as caught:
            call()
        self.assertIn("audit trail", str(caught.exception))
        self.assertIn("other.md", str(caught.exception))

    def test_the_audit_trail_is_read_through_its_one_door(self):
        """`_decisions_text` is the one reader of `decisions.md`, and it
        separates "this run has decided nothing" from "this name exists and
        cannot be read". A second resolver here would have folded a directory
        back into "no decisions yet" -- a fail-open grant."""
        run_dir, call = self.resume(write=False)
        (Path(run_dir) / "decisions.md").mkdir()
        with self.assertRaises(state.TrackerValidationError) as caught:
            call()
        self.assertIn("not a regular file", str(caught.exception))


# THE RUNNER GOES LAST, and it has to. `unittest.main()` calls `sys.exit()`, so
# this block sat at what was once the end of the file and became its MIDDLE the
# moment the Task 4 block was appended after it: `python3 test_task_lifecycle.py`
# exited at that line and never defined -- let alone ran -- a single Task 4
# test. Discovery collected 386 and direct execution 252, both green, and the
# 134 tests the difference names were the whole of the F5 work.

# --------------------------------------------------------------------------
# Task 8 -- the baseline-anchored source-range proof, faults F3 and F4.
#
# THE BRIEF IS STALE BY DESIGN AND ITS PRODUCES BLOCK DOES NOT SURVIVE CONTACT.
# It called `_git_out` three times and `_git` once. Both are `subprocess.run`
# wrappers, `subprocess` is the single capability `ALLOWED_IMPORTS` most exists
# to withhold, and the master plan's quorum ruled the module never executes
# git: it EMITS THE ARGV, the controller runs it, and the module VALIDATES THE
# TRANSCRIPT. The tests below play the controller -- they shell out to git,
# because a test is not the module -- and hand the module only what a
# controller could hand it.
#
# THREE OF THE BRIEF'S CALLS WERE ALSO A SECURITY DEFECT INDEPENDENT OF THAT.
# `git diff --name-only` does rename detection by default and then prints only
# the DESTINATION, so a task declared to `mine/` can `git mv theirs/victim.py
# mine/victim.py`, have every printed path inside its own scope, and pass the
# scope check while having deleted another task's file.
# `RenameHidesTheVictimTests` measures both halves on a real repository.
# --------------------------------------------------------------------------


def commit_file(repo, relative: str, text: str, message: str) -> str:
    path = Path(repo) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def commit_only(repo, relative: str, text: str, message: str) -> str:
    """Commit ONE path, by name.

    `commit_file`'s `git add -A` sweeps the run directory -- which is
    UNTRACKED inside the fixture repository -- into whatever branch is
    checked out, and the next `git checkout` of a branch without it then
    DELETES `progress.md`. Measured: three tests died with
    `ForeignSchemaError: missing progress.md` before this existed.
    """
    path = Path(repo) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", "--", relative)
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def run_commands(commands) -> str:
    """Play the controller: run the argv the MODULE emitted, RAW stdout.

    The `git` harness above strips, which would eat both the leading record
    separator and the trailing newline the transcript grammar is built on --
    so a transcript is never taken through it.
    """
    return "".join(
        subprocess.run(argv, capture_output=True, text=True, check=True).stdout
        for argv in commands)


def range_transcript(repo, baseline: str, head: str,
                     head_ref: str = "task/T1") -> str:
    """The module's own argv, run. `head_ref` defaults to the branch every
    fixture below commits on -- the head of a proved range is read out of the
    ref store, so there is no spelling of this helper that does not name a
    reference."""
    return run_commands(state.source_range_commands(
        repo, baseline=baseline, head=head, head_ref=head_ref))


def transcript_records(text: str) -> list:
    """Split a transcript the way THIS FILE understands it, never through the
    module's own parser: a corpus checked with the code under test measures
    agreement with itself."""
    return ["\x00" + chunk for chunk in text.split("\x00")[1:]]


OTHER_SHA = "9" * 40


class SourceRangeProducesBlockTests(unittest.TestCase):
    """The Produces-block check, executable, name by name.

    Consumes: `_resolved_commit`, `_path_in_scope`, `_scope_parts` -- and
    `_git` / `_git_out`, which CANNOT EXIST.
    Produces: `source_range_commands`, `_parse_range_transcript`,
    `verify_source_range`; `_commit_parents` is explicitly NOT produced.
    Added beyond the block: `reserved_baseline`, argued below.

    THE BLOCK'S SIGNATURE GAINED ONE KEYWORD AND THE DIVERGENCE IS RECORDED
    RATHER THAN QUIET. The plan wrote `verify_source_range(repo, *, baseline,
    head, scopes, transcript)`, and with that signature the function could
    not do the one thing the plan said it did -- "both endpoints stay
    module-derived, so a transcript rooted elsewhere fails at the first
    link". Both production endpoints are object names, `_resolved_commit`
    answered an object name without opening anything, and a full `attested`
    proof was obtainable over a directory that is not a repository.
    `head_ref` is required so the head comes out of the ref store; the master
    plan's P04 block and this phase plan were amended in the same change.
    """

    def test_the_two_subprocess_wrappers_the_brief_called_do_not_exist(self):
        """`_git_out` was called three times and `_git` once. Neither is a name
        this module may hold: both were `subprocess.run` wrappers."""
        self.assertFalse(hasattr(state, "_git"))
        self.assertFalse(hasattr(state, "_git_out"))

    def test_commit_parents_is_not_produced_because_parents_come_from_the_transcript(self):
        """The brief's own Produces block already said so, and it is the whole
        reason the chain is checked from the transcript's internal structure
        instead of read off it as an assertion."""
        self.assertFalse(hasattr(state, "_commit_parents"))

    def test_the_module_still_imports_nothing_outside_the_twelve(self):
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {
            "__future__", "contextlib", "copy", "errno", "fcntl", "hashlib",
            "json", "msvcrt", "os", "pathlib", "time", "types"})
        self.assertNotIn("subprocess", imported)
        self.assertNotIn("re", imported)
        self.assertNotIn("zlib", imported)

    def test_no_os_command_execution_name_is_reachable_by_ast(self):
        """`subprocess` off the allowlist is NOMINAL on its own: `os` is ON it
        and carries `popen`, `system`, `execv`, `posix_spawn`, `spawnv` and
        `fork`. The family is enumerated from `dir(os)` rather than from a
        remembered list, so a spelling nobody here thought of is still caught,
        and the PRIVATE spellings (`os._exit`-shaped names) are in the sweep.
        """
        family = tuple(sorted(
            name for name in dir(os)
            if name.lstrip("_").startswith(
                ("popen", "system", "exec", "spawn", "fork", "posix_spawn"))))
        self.assertIn("popen", family)
        self.assertIn("system", family)
        self.assertIn("execv", family)
        self.assertIn("fork", family)
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        reached = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute) and node.attr in family:
                reached.append(node.attr)
            if isinstance(node, ast.Name) and node.id in family:
                reached.append(node.id)
        self.assertEqual(reached, [])

    def test_the_three_produced_names_are_each_bound_exactly_once(self):
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        counts = module_bindings(ast.parse(source).body)
        for name in ("source_range_commands", "_parse_range_transcript",
                     "verify_source_range", "reserved_baseline"):
            with self.subTest(name=name):
                self.assertEqual(counts.get(name), 1)
        self.assertEqual(
            sorted(name for name, count in counts.items() if count > 1), [])

    def test_the_consumed_names_are_still_the_ones_this_module_already_had(self):
        """A module-level redefinition rebinds the global for every caller.
        Each consumed name is exercised on its own committed behaviour."""
        self.assertIs(state._path_in_scope("src/a.py", "tree:src"), True)
        self.assertIs(state._path_in_scope("srcx/a.py", "tree:src"), False)
        self.assertEqual(state._scope_parts("file:src/a.py"),
                         ("file", PurePosixPath("src/a.py")))
        with self.assertRaises(state.PlanMetadataError):
            state._scope_parts("src/a.py")
        self.assertTrue(state._COMMIT.fullmatch("a" * 40))
        self.assertFalse(state._COMMIT.fullmatch("A" * 40))
        self.assertEqual(state._digest(""), hashlib.sha256(b"").hexdigest())

    def test_reserved_baseline_is_the_one_name_added_beyond_the_block(self):
        """The block names three functions and none of them can reach the
        persisted baseline, which is the fact the whole proof is anchored on
        and which Task 7 made AMBIGUOUS: a resumed task carries TWO
        `baseline:` checkpoints with DIFFERENT shas. A caller left to scan the
        cell itself would scan it five different ways in five places.
        """
        self.assertTrue(callable(state.reserved_baseline))

    def test_the_proof_mode_vocabulary_is_the_master_plans_own_word(self):
        self.assertEqual(state.PROOF_ATTESTED, "attested")

    def test_the_head_reference_is_a_required_keyword_on_both_public_names(self):
        """Required rather than defaulted, and keyword-only rather than
        positional: a default would be a head nobody named, and a positional
        would let a caller pass the sha twice by accident."""
        for name in ("source_range_commands", "verify_source_range"):
            with self.subTest(name=name):
                parameters = inspect.signature(
                    getattr(state, name)).parameters
                head_ref = parameters["head_ref"]
                self.assertEqual(head_ref.kind,
                                 inspect.Parameter.KEYWORD_ONLY)
                self.assertIs(head_ref.default, inspect.Parameter.empty)
                self.assertEqual(
                    [p for p in parameters
                     if parameters[p].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD],
                    ["repo"])


class ReservedBaselineTests(TempDirTestCase):
    """Task 7's inheritance, and the highest-stakes read in this task.

    A resumed task carries two `baseline:` checkpoints with different shas.
    Reading the wrong one charges a task that was BLOCKED with every commit
    that landed in the target branch while it waited -- a loud failure on
    innocent work, which erodes trust in the gate faster than a silent pass.
    """

    def blocked_and_resumed(self):
        """A real reserve -> block -> (target moves) -> resume, so the two
        baselines are produced by the shipped transitions and not by a fixture
        that merely looks like them. `blocked_run` is Task 7's own harness."""
        repo, run_dir = blocked_run(self)
        first = state.reserved_baseline(
            task_row(state.validate_run(run_dir), "T1"), attempt=1)
        #: The target branch MOVES while the task is blocked. This is the whole
        #: of the hazard: those commits belong to whoever integrated them.
        git(repo, "checkout", "-q", "target")
        intervening = commit_only(repo, "src/other.py", "other = 1\n",
                                  "another task integrates")
        git(repo, "checkout", "-q", "main")
        state.resume_task(run_dir, task_id="T1", prior_attempt=1,
                          new_owner="impl-2", new_attempt=2,
                          decision_ref=QUORUM_GRANT)
        row = task_row(state.validate_run(run_dir), "T1")
        second = state.reserved_baseline(row, attempt=2)
        return repo, row, first, second, intervening

    def test_each_attempt_reads_its_own_baseline_and_they_differ(self):
        _repo, row, first, second, intervening = self.blocked_and_resumed()
        self.assertNotEqual(first, second)
        self.assertEqual(second, intervening)
        self.assertEqual(state.reserved_baseline(row, attempt=1), first)
        self.assertEqual(state.reserved_baseline(row, attempt=2), second)

    def test_the_row_really_carries_two_baselines_and_the_resumed_marker(self):
        """The fixture is only evidence if the ambiguity is actually present.
        `resumed:<prior>-><new>@<ref>` carries TWO attempt tokens in one entry
        and must not derail the scan."""
        _repo, row, first, second, _ = self.blocked_and_resumed()
        entries = state._csv(row["checkpoints"])
        self.assertIn(f"baseline:attempt-001@{first}", entries)
        self.assertIn(f"baseline:attempt-002@{second}", entries)
        self.assertEqual(
            len([entry for entry in entries if entry.startswith("baseline:")]),
            2)
        self.assertTrue(any(entry.startswith("resumed:attempt-001->attempt-002@")
                            for entry in entries))

    def test_reading_the_wrong_attempts_baseline_charges_innocent_work(self):
        """F3 in its Task-7 form. Attempt two's range proved against attempt
        ONE's baseline swallows the commit another task integrated while this
        one was blocked -- and every one of those paths is then measured
        against THIS task's write scope."""
        repo, _row, first, second, intervening = self.blocked_and_resumed()
        git(repo, "checkout", "-q", "-b", "task/T1", second)
        head = commit_only(repo, "src/a1.py", "mine = 1\n", "my only commit")
        honest = state.verify_source_range(
            repo, baseline=second, head=head, head_ref="task/T1",
            scopes=["file:src/a1.py"],
            transcript=range_transcript(repo, second, head))
        self.assertEqual(honest["commits"], (head,))
        self.assertEqual(honest["changed_paths"], ("src/a1.py",))
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=first, head=head, head_ref="task/T1",
                scopes=["file:src/a1.py"],
                transcript=range_transcript(repo, first, head))
        self.assertIn("src/other.py", str(caught.exception))
        #: and the innocent commit really is the one that was charged
        self.assertIn(intervening, [
            entry["commit"] for entry in state._parse_range_transcript(
                range_transcript(repo, first, head))])

    def test_a_question_cell_spelled_resolved_does_not_derail_the_scan(self):
        """`resolved:<ref>` is in the Question vocabulary Task 7 left behind.
        It is not a checkpoint and this scan never reads that cell."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks())
        state.reserve_task(run_dir, task_id="T1", owner="w-1", attempt=1)
        set_task_state(run_dir, "T1", "odd-question", state="[?]",
                       question=f"resolved:{QUORUM_GRANT}")
        row = task_row(state.validate_run(run_dir), "T1")
        self.assertEqual(state.reserved_baseline(row, attempt=1),
                         git(repo, "rev-parse", "target"))

    def test_an_artifact_task_records_no_baseline_and_the_refusal_says_so(self):
        _repo, run_dir, _ = make_run(
            self.tmp, task_block("T1", kind="artifact", outputs="docs/a.md",
                                 write_scope="file:docs/a.md"))
        state.reserve_task(run_dir, task_id="T1", owner="w-1", attempt=1)
        row = task_row(state.validate_run(run_dir), "T1")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserved_baseline(row, attempt=1)
        self.assertIn("attempt-001", str(caught.exception))
        self.assertIn("0", str(caught.exception))

    def test_an_attempt_with_no_checkpoint_of_its_own_is_refused(self):
        _repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks())
        state.reserve_task(run_dir, task_id="T1", owner="w-1", attempt=1)
        row = task_row(state.validate_run(run_dir), "T1")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserved_baseline(row, attempt=2)
        self.assertIn("attempt-002", str(caught.exception))

    def test_two_baselines_for_one_attempt_are_refused_rather_than_picked_from(self):
        row = {"id": "T1",
               "checkpoints": f"baseline:attempt-001@{'a' * 40},"
                              f"baseline:attempt-001@{'b' * 40}"}
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserved_baseline(row, attempt=1)
        self.assertIn("2", str(caught.exception))

    def test_a_baseline_payload_that_is_not_an_object_name_is_refused(self):
        for payload in ("HEAD~1", "target", "A" * 40, "a" * 39, "a" * 41, ""):
            with self.subTest(payload=payload):
                row = {"id": "T1",
                       "checkpoints": f"baseline:attempt-001@{payload}"}
                with self.assertRaises(state.TrackerValidationError):
                    state.reserved_baseline(row, attempt=1)

    def test_the_marker_is_anchored_at_the_start_of_the_entry(self):
        """M-R13. `entry.startswith(marker)` weakened to `marker in entry`
        kills nothing in the shipped vocabulary, because nothing shipped puts
        `baseline:attempt-NNN@` anywhere but at the start of a `_csv` entry.
        That is hardening rather than a live hole, and hardening nobody
        exercises is hardening nobody can rely on: one entry spelled with a
        prefix closes it."""
        row = {"id": "T1",
               "checkpoints": f"started:attempt-001,"
                              f"x-baseline:attempt-001@{'a' * 40}"}
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserved_baseline(row, attempt=1)
        self.assertIn("records 0 baselines", str(caught.exception))
        row["checkpoints"] += f",baseline:attempt-001@{'b' * 40}"
        self.assertEqual(state.reserved_baseline(row, attempt=1), "b" * 40)

    def test_a_row_that_is_not_a_row_is_refused_inside_the_family(self):
        for row in (None, "checkpoints", 3, [], {"id": "T1"},
                    {"checkpoints": "-"}, {"id": "T1", "checkpoints": None},
                    {"id": "T1", "checkpoints": 7}):
            with self.subTest(row=row):
                with self.assertRaises(state.TrackerError):
                    state.reserved_baseline(row, attempt=1)

    def test_the_attempt_goes_through_the_single_conversion_point(self):
        row = {"id": "T1", "checkpoints": f"baseline:attempt-001@{'a' * 40}"}
        self.assertEqual(state.reserved_baseline(row, attempt=1), "a" * 40)
        for attempt in ("1", "attempt-001", None, -1, 0, 1.0, True):
            with self.subTest(attempt=attempt):
                with self.assertRaises(state.TrackerError):
                    state.reserved_baseline(row, attempt=attempt)


class SourceRangeCommandTests(TempDirTestCase):
    """The module dictates the question; the controller executes it."""

    def test_the_emitted_argv_is_pinned_exactly(self):
        repo = make_repo(self.tmp)
        base = git(repo, "rev-parse", "target")
        head = git(repo, "rev-parse", "HEAD")
        self.assertEqual(
            state.source_range_commands(repo, baseline=base, head=head,
                                        head_ref="main"),
            ((
                "git", "-C", str(repo), "-c", "core.quotePath=true", "log",
                "--reverse", "--no-renames", "--no-relative",
                "--ignore-submodules=none", "--name-only", "--no-color",
                "--format=%x00%H %P", f"{base}..{head}", "--",
            ),))

    def test_every_changed_path_command_carries_no_renames(self):
        """Load-bearing, not stylistic. Measured in
        `RenameHidesTheVictimTests`: without it a `git mv` out of another
        task's tree prints only the destination and the scope check passes."""
        repo = make_repo(self.tmp)
        commands = state.source_range_commands(
            repo, baseline=git(repo, "rev-parse", "target"),
            head=git(repo, "rev-parse", "HEAD"), head_ref="main")
        self.assertTrue(commands)
        for argv in commands:
            with self.subTest(argv=argv):
                self.assertIn("--name-only", argv)
                self.assertIn("--no-renames", argv)

    def test_both_endpoints_are_resolved_by_the_module_not_passed_through(self):
        """A symbolic end resolves somewhere else tomorrow. The controller is
        handed object names, so the range it runs is the range the module
        meant."""
        repo = make_repo(self.tmp)
        argv = state.source_range_commands(
            repo, baseline="target", head="main", head_ref="main")[0]
        self.assertIn(f"{git(repo, 'rev-parse', 'target')}.."
                      f"{git(repo, 'rev-parse', 'main')}", argv)
        self.assertNotIn("target..main", argv)

    def test_an_end_that_names_no_reference_is_a_stop(self):
        repo = make_repo(self.tmp)
        with self.assertRaises(state.TrackerValidationError):
            state.source_range_commands(repo, baseline="no-such-branch",
                                        head="target", head_ref="target")

    def test_a_repository_argument_that_cannot_be_an_argv_element_is_refused(self):
        for repo in (None, 3, "", "   ", "a\x00b", b"/tmp"):
            with self.subTest(repo=repo):
                with self.assertRaises(state.TrackerError):
                    state.source_range_commands(repo, baseline="a" * 40,
                                                head="b" * 40,
                                                head_ref="target")

    def test_the_nul_screen_is_asserted_by_its_diagnosis_at_every_offset(self):
        """M-R14, and the reason "it refused" was never a strong enough claim.

        `if _RANGE_SEPARATOR in repo:` weakened to `repo[1:]` SURVIVES every
        test that only asks whether the call refused. It refuses anyway --
        `_git_store` walks a NUL-bearing path down to `_require_regular_file`,
        which screens the byte at the door and raises inside the family -- so
        the mutant's answer and the shipped answer have the same SHAPE and a
        different SENTENCE. What is lost is the screen that fires BEFORE any
        filesystem work and whose diagnosis is the one the caller needs: no
        argv element may carry a NUL, so this location can never be handed to
        a controller at all. Measured: `subprocess.run(('git', '-C',
        '\x00repo', 'log'))` raises `ValueError: embedded null byte`, which is
        not an `OSError` and is outside this module's exception family.

        The corpus that missed this had the NUL mid-string in every case, so
        the offset is swept here rather than assumed.
        """
        for repo in ("\x00", "\x00repo", "a\x00b", "repo\x00", "a\x00b\x00c"):
            with self.subTest(repo=repo):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.source_range_commands(
                        repo, baseline="a" * 40, head="b" * 40,
                        head_ref="target")
                self.assertIn("the repository location carries a NUL byte",
                              str(caught.exception))

    def test_the_command_runs_and_its_output_is_what_the_parser_reads(self):
        repo = make_repo(self.tmp)
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        head = commit_file(repo, "src/a1.py", "one = 1\n", "one")
        entries = state._parse_range_transcript(
            range_transcript(repo, base, head))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["commit"], head)
        self.assertEqual(entries[0]["parents"], (base,))
        self.assertEqual(entries[0]["paths"], ("src/a1.py",))


class RenameHidesTheVictimTests(TempDirTestCase):
    """The measured scope-check bypass the brief's three `--name-only` calls
    would have shipped."""

    def moved_victim(self):
        repo = make_repo(self.tmp)
        git(repo, "checkout", "-q", "target")
        (repo / "theirs").mkdir()
        (repo / "theirs" / "victim.py").write_text("victim = 1\n" * 40,
                                                   encoding="utf-8")
        (repo / "mine").mkdir()
        (repo / "mine" / "own.py").write_text("own = 1\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "two tasks' trees")
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        git(repo, "mv", "theirs/victim.py", "mine/victim.py")
        git(repo, "commit", "-qm", "steal it")
        return repo, base, git(repo, "rev-parse", "HEAD")

    def test_rename_detection_prints_only_the_destination(self):
        """The defect, measured rather than recalled. Rename detection is ON
        by default."""
        repo, base, head = self.moved_victim()
        hidden = subprocess.run(
            ("git", "-C", str(repo), "diff", "--name-only", f"{base}..{head}"),
            capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(hidden, ["mine/victim.py"])
        self.assertTrue(all(state._path_in_scope(path, "tree:mine")
                            for path in hidden))

    def test_the_modules_own_command_prints_both_sides_and_the_check_refuses(self):
        repo, base, head = self.moved_victim()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=base, head=head, head_ref="task/T1",
                scopes=["tree:mine"],
                transcript=range_transcript(repo, base, head))
        self.assertIn("theirs/victim.py", str(caught.exception))

    def test_deleting_the_no_renames_flag_from_the_transcript_reopens_it(self):
        """The flag is what refuses, and nothing else is. With the flag
        removed from the argv the module emitted, the same repository produces
        a transcript every path of which is inside the declared scope."""
        repo, base, head = self.moved_victim()
        argv = state.source_range_commands(repo, baseline=base, head=head,
                                           head_ref="task/T1")[0]
        weakened = tuple(part for part in argv if part != "--no-renames")
        proof = state.verify_source_range(
            repo, baseline=base, head=head, head_ref="task/T1",
            scopes=["tree:mine"], transcript=run_commands((weakened,)))
        self.assertEqual(proof["changed_paths"], ("mine/victim.py",))


class PathSpellingConfigTests(TempDirTestCase):
    """The rename bypass was not one bug, it was the first of a family.

    The master plan's rule after the second instance: A CHANGED-PATH COMMAND
    PINS EVERY GIT CONFIG THAT CAN CHANGE HOW A PATH IS SPELLED OR WHETHER IT
    APPEARS AT ALL. This class is that rule applied to the emitted argv, one
    config at a time, each measured against REAL git in both directions --
    the module's own command, and the module's own command with exactly that
    one token removed.

    A third instance was found by applying the rule rather than by waiting
    for a bug: `diff.ignoreSubmodules`. Unlike `diff.relative` it needs no
    unusual `-C`, so it is live rather than latent.
    """

    def touch_both(self):
        """One commit touching an in-scope file and an out-of-scope one."""
        repo = make_repo(self.tmp)
        git(repo, "checkout", "-q", "target")
        for directory in ("mine", "theirs"):
            (repo / directory).mkdir()
            (repo / directory / "f.py").write_text("x = 1\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "two trees")
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        for directory in ("mine", "theirs"):
            (repo / directory / "f.py").write_text("x = 2\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "touch both")
        return repo, base, git(repo, "rev-parse", "HEAD")

    def argv(self, repo, base, head):
        return state.source_range_commands(
            repo, baseline=base, head=head, head_ref="task/T1")[0]

    @staticmethod
    def without(argv, token):
        weakened = tuple(part for part in argv if part != token)
        assert len(weakened) == len(argv) - 1, token
        return weakened

    def test_ignore_submodules_hides_a_changed_gitlink_and_the_flag_stops_it(self):
        """LIVE, not latent: `diff.ignoreSubmodules=all` is an ordinary
        repository-level config and the worker owns the repository. A commit
        that changes one in-scope file and bumps one out-of-scope submodule
        prints the gitlink by default and prints NOTHING for it under that
        config, so the scope check passes on a commit that moved another
        task's submodule. The gitlink is written straight into the index
        rather than through `git submodule add`, because the mode is what
        `--name-only` reports on and a checked-out submodule is not needed to
        have one."""
        repo = make_repo(self.tmp)
        git(repo, "checkout", "-q", "target")
        (repo / "mine").mkdir()
        (repo / "mine" / "f.py").write_text("x = 1\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "mine")
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        git(repo, "update-index", "--add", "--cacheinfo",
            f"160000,{'1' * 40},theirs/sub")
        (repo / "mine" / "f.py").write_text("x = 2\n", encoding="utf-8")
        git(repo, "add", "--", "mine/f.py")
        git(repo, "commit", "-qm", "mine, and another task's submodule")
        head = git(repo, "rev-parse", "HEAD")
        git(repo, "config", "diff.ignoreSubmodules", "all")

        argv = self.argv(repo, base, head)
        self.assertIn("--ignore-submodules=none", argv)
        honest = run_commands((argv,))
        self.assertIn("theirs/sub", honest)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=base, head=head, head_ref="task/T1",
                scopes=["tree:mine"], transcript=honest)
        self.assertIn("theirs/sub", str(caught.exception))

        hidden = run_commands(
            (self.without(argv, "--ignore-submodules=none"),))
        self.assertNotIn("theirs/sub", hidden)
        proof = state.verify_source_range(
            repo, baseline=base, head=head, head_ref="task/T1",
            scopes=["tree:mine"], transcript=hidden)
        self.assertEqual(proof["changed_paths"], ("mine/f.py",))

    def test_relative_paths_respell_one_side_and_delete_the_other(self):
        """`diff.relative` reports paths relative to the command's working
        directory. Measured: with `-C <repo>/mine` the in-scope
        `mine/deep/x.py` is respelled `deep/x.py` -- which a `tree:deep`
        scope then CLAIMS -- and the out-of-scope `theirs/f.py` does not
        appear at all.

        NOT REACHABLE THROUGH THE MODULE TODAY, and the `-C` is rewritten
        here to show the flag doing its job: `_repo_dir` yields the
        repository root and `_git_store` requires a `.git` there. That is
        exactly the reachability argument that was made for `--no-renames`
        and that turned out to be wrong, so the token is on the argv and this
        test measures it rather than the argument.
        """
        repo = make_repo(self.tmp)
        git(repo, "checkout", "-q", "target")
        (repo / "mine" / "deep").mkdir(parents=True)
        (repo / "theirs").mkdir()
        (repo / "mine" / "deep" / "x.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "theirs" / "f.py").write_text("x = 1\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "two trees")
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        (repo / "mine" / "deep" / "x.py").write_text("x = 2\n", encoding="utf-8")
        (repo / "theirs" / "f.py").write_text("x = 2\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "touch both")
        head = git(repo, "rev-parse", "HEAD")
        git(repo, "config", "diff.relative", "true")

        argv = self.argv(repo, base, head)
        self.assertIn("--no-relative", argv)
        from_subdir = tuple(str(repo / "mine") if part == str(repo) else part
                            for part in argv)
        self.assertIn(str(repo / "mine"), from_subdir)
        honest = run_commands((from_subdir,))
        self.assertIn("mine/deep/x.py", honest)
        self.assertIn("theirs/f.py", honest)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=base, head=head, head_ref="task/T1",
                scopes=["tree:deep"], transcript=honest)
        self.assertIn("theirs/f.py", str(caught.exception))

        respelled = run_commands((self.without(from_subdir, "--no-relative"),))
        self.assertNotIn("theirs/f.py", respelled)
        self.assertNotIn("mine/deep/x.py", respelled)
        self.assertIn("deep/x.py", respelled)
        proof = state.verify_source_range(
            repo, baseline=base, head=head, head_ref="task/T1",
            scopes=["tree:deep"], transcript=respelled)
        self.assertEqual(proof["changed_paths"], ("deep/x.py",))

    def test_quote_path_is_pinned_so_the_spelling_is_not_the_default(self):
        """`core.quotePath` decides whether a non-ASCII path is C-quoted or
        printed raw. It is pinned to `true` -- git's own default -- so the
        transcript is always pure ASCII and always decodable by whatever
        captured it, and so the spelling does not depend on a config the
        worker owns. Fail closed DETERMINISTICALLY rather than fail closed by
        default: a C-quoted path begins with `"` and is claimed by no scope.
        """
        repo = make_repo(self.tmp)
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        head = commit_file(repo, "src/caf\u00e9.py", "x = 1\n", "accented")
        git(repo, "config", "core.quotePath", "false")

        argv = self.argv(repo, base, head)
        self.assertIn("core.quotePath=true", argv)
        pinned = run_commands((argv,))
        self.assertIn('"src/caf\\303\\251.py"', pinned)
        self.assertNotIn("src/caf\u00e9.py", pinned)
        self.assertTrue(pinned.replace("\x00", "").isascii())
        with self.assertRaises(state.TrackerError):
            state.verify_source_range(
                repo, baseline=base, head=head, head_ref="task/T1",
                scopes=["tree:src"], transcript=pinned)

        unpinned = run_commands(
            (self.without(self.without(argv, "core.quotePath=true"), "-c"),))
        self.assertIn("src/caf\u00e9.py", unpinned)
        self.assertFalse(unpinned.isascii())

    def test_every_pinned_token_is_on_the_one_argv_builder(self):
        """One builder, so the emitter and the diagnostic cannot disagree,
        and the pins are asserted as a set rather than by reading the
        source."""
        repo, base, head = self.touch_both()
        argv = self.argv(repo, base, head)
        for token in ("--no-renames", "--no-relative",
                      "--ignore-submodules=none", "--no-color",
                      "core.quotePath=true"):
            with self.subTest(token=token):
                self.assertEqual(argv.count(token), 1)
        self.assertEqual(argv.index("-c"), 3)
        self.assertEqual(argv[4], "core.quotePath=true")
        self.assertEqual(argv[5], "log")


class SourceRangeTests(TempDirTestCase):
    """The nine the brief named, re-aimed at the transcript."""

    def three_commit_branch(self):
        repo = make_repo(self.tmp)
        baseline = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        commits = tuple(
            commit_file(repo, "src/a1.py", f"value = {index}\n", f"step {index}")
            for index in range(1, 4))
        return repo, baseline, commits

    def prove(self, repo, baseline, head, scopes, head_ref="task/T1"):
        return state.verify_source_range(
            repo, baseline=baseline, head=head, head_ref=head_ref,
            scopes=scopes,
            transcript=range_transcript(repo, baseline, head, head_ref))

    def test_accepts_the_complete_ordered_range(self):
        repo, baseline, commits = self.three_commit_branch()
        proof = self.prove(repo, baseline, commits[-1], ["file:src/a1.py"])
        self.assertEqual(proof["baseline"], baseline)
        self.assertEqual(proof["head"], commits[-1])
        self.assertEqual(proof["commits"], commits)
        self.assertEqual(proof["changed_paths"], ("src/a1.py",))

    def test_head_tilde_one_baseline_truncates_a_multi_commit_task(self):
        """F3: `HEAD~1` is not the review baseline. It silently drops the
        earlier commits, which then escape every scope and range check."""
        repo, baseline, commits = self.three_commit_branch()
        persisted = self.prove(repo, baseline, commits[-1], ["file:src/a1.py"])
        truncated = self.prove(repo, commits[-2], commits[-1],
                               ["file:src/a1.py"])
        self.assertEqual(len(persisted["commits"]), 3)
        self.assertEqual(len(truncated["commits"]), 1)
        self.assertNotEqual(truncated["commits"], persisted["commits"])
        self.assertLess(set(truncated["commits"]), set(persisted["commits"]))

    def test_rejects_an_empty_commit(self):
        """F4: no diff is not an artifact completion and not a reason for an
        empty commit."""
        repo, baseline, _ = self.three_commit_branch()
        git(repo, "commit", "-q", "--allow-empty", "-m", "nothing happened")
        head = git(repo, "rev-parse", "HEAD")
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.prove(repo, baseline, head, ["file:src/a1.py"])
        self.assertIn("empty commit", str(caught.exception))
        self.assertIn(head, str(caught.exception))

    def test_rejects_an_empty_range(self):
        repo, baseline, _ = self.three_commit_branch()
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.prove(repo, baseline, baseline, ["file:src/a1.py"],
                       head_ref="target")
        self.assertIn("empty", str(caught.exception))

    def test_rejects_a_head_that_does_not_descend_the_baseline(self):
        """F4: an unrelated commit proves nothing about this task."""
        repo, baseline, _ = self.three_commit_branch()
        git(repo, "checkout", "-q", "--orphan", "unrelated")
        git(repo, "rm", "-rqf", ".")
        unrelated = commit_file(repo, "other.py", "x = 1\n", "unrelated history")
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.prove(repo, baseline, unrelated, ["file:other.py"],
                       head_ref="unrelated")
        self.assertIn("ancestor", str(caught.exception))

    def test_rejects_a_head_that_is_behind_the_baseline(self):
        """The other half of descent, and it arrives as an EMPTY transcript
        rather than as a broken chain -- so the refusal has to be written for
        it rather than fall out of the chain walk."""
        repo, baseline, commits = self.three_commit_branch()
        git(repo, "branch", "-f", "target", commits[-1])
        #: The head of a proved range is a REFERENCE the ref store carries, so
        #: "behind the baseline" has to be expressed as a branch rather than
        #: as a loose object name -- which is the point of the anchor, not a
        #: concession to it.
        git(repo, "branch", "behind", commits[0])
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.prove(repo, commits[-1], commits[0], ["file:src/a1.py"],
                       head_ref="behind")
        self.assertIn("descend", str(caught.exception))

    def test_rejects_a_merge_inside_the_implementation_range(self):
        """One worktree per implementer means the implementation range is
        linear. A merge inside it belongs to integration, not to the task."""
        repo, baseline, _ = self.three_commit_branch()
        git(repo, "checkout", "-q", "-b", "side", baseline)
        commit_file(repo, "src/side.py", "side = 1\n", "side work")
        git(repo, "checkout", "-q", "task/T1")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
        head = git(repo, "rev-parse", "HEAD")
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.prove(repo, baseline, head,
                       ["file:src/a1.py", "file:src/side.py"])
        self.assertIn("linear", str(caught.exception))

    def test_rejects_an_out_of_scope_path(self):
        repo, baseline, _ = self.three_commit_branch()
        head = commit_file(repo, "src/escaped.py", "escaped = 1\n", "out of scope")
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.prove(repo, baseline, head, ["file:src/a1.py"])
        self.assertIn("src/escaped.py", str(caught.exception))

    def test_accepts_a_tree_scope_covering_every_changed_path(self):
        repo, baseline, _ = self.three_commit_branch()
        head = commit_file(repo, "src/deep/nested.py", "nested = 1\n", "in a tree")
        proof = self.prove(repo, baseline, head, ["tree:src"])
        self.assertIn("src/deep/nested.py", proof["changed_paths"])

    def test_rejects_untyped_or_absent_scopes(self):
        repo, baseline, commits = self.three_commit_branch()
        transcript = range_transcript(repo, baseline, commits[-1])
        with self.assertRaises(state.PlanMetadataError):
            state.verify_source_range(repo, baseline=baseline, head=commits[-1],
                                      head_ref="task/T1", scopes=["src/a1.py"],
                                      transcript=transcript)
        with self.assertRaises(state.TrackerValidationError):
            state.verify_source_range(repo, baseline=baseline, head=commits[-1],
                                      head_ref="task/T1", scopes=[],
                                      transcript=transcript)

    def test_the_empty_scope_refusal_is_not_an_out_of_scope_report(self):
        """M23. With the screen deleted the call still refuses -- `any()` over
        no scopes is False, so every changed path reads as an escape -- and
        the DIAGNOSIS is then exactly backwards: "this task wrote outside its
        scope" for a task that was never given one. The screen buys the right
        answer to "what is wrong here", which is the whole of what it is for.
        """
        repo, baseline, commits = self.three_commit_branch()
        transcript = range_transcript(repo, baseline, commits[-1])
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(repo, baseline=baseline, head=commits[-1],
                                      head_ref="task/T1", scopes=[],
                                      transcript=transcript)
        message = str(caught.exception)
        self.assertIn("at least one approved write scope", message)
        self.assertNotIn("src/a1.py", message)

    def test_an_untyped_scope_is_refused_even_when_another_scope_covers(self):
        """M24. The typing loop is EAGER, and that is not decoration: the
        membership test below short-circuits on the first scope that claims a
        path, so a declared scope that is not a scope at all is never
        evaluated when an earlier one covers everything -- and the task is
        accepted holding a write-scope declaration nothing validated."""
        repo, baseline, _ = self.three_commit_branch()
        head = commit_file(repo, "src/deep/nested.py", "n = 1\n", "nested")
        transcript = range_transcript(repo, baseline, head)
        self.assertEqual(
            state.verify_source_range(
                repo, baseline=baseline, head=head, head_ref="task/T1",
                scopes=["tree:src"], transcript=transcript)["changed_paths"],
            ("src/a1.py", "src/deep/nested.py"))
        with self.assertRaises(state.PlanMetadataError):
            state.verify_source_range(
                repo, baseline=baseline, head=head, head_ref="task/T1",
                scopes=["tree:src", "src/escaped.py"], transcript=transcript)

    def test_the_empty_range_screen_is_not_the_empty_transcript_screen(self):
        """M25. Both refuse on the HONEST transcript for `base..base`, which
        is empty -- so only a FORGED one can tell them apart. A record whose
        commit IS its own parent chains from the baseline and ends at the
        head when the two are the same commit, and with the screen deleted it
        is accepted: a task that moved the branch nowhere, proved."""
        repo, baseline, _ = self.three_commit_branch()
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.prove(repo, baseline, baseline, ["file:src/a1.py"],
                       head_ref="target")
        self.assertIn("equals the recorded baseline", str(caught.exception))
        forged = f"\x00{baseline} {baseline}\n\nsrc/a1.py\n"
        with self.assertRaises(state.TrackerValidationError) as forgery:
            state.verify_source_range(
                repo, baseline=baseline, head=baseline, head_ref="target",
                scopes=["file:src/a1.py"], transcript=forged)
        self.assertIn("equals the recorded baseline", str(forgery.exception))

    def test_a_path_needs_ONE_scope_that_claims_it_and_not_every_scope(self):
        """M35. With one declared scope `any` and `all` are the same function,
        and every accepting test above declares one. Two disjoint scopes, each
        claiming one of the two changed paths, is the smallest case that tells
        them apart -- and `all` would refuse every honest multi-scope task."""
        repo, baseline, _ = self.three_commit_branch()
        (repo / "src" / "b1.py").write_text("b = 1\n", encoding="utf-8")
        git(repo, "add", "--", "src/b1.py")
        git(repo, "commit", "-qm", "a second declared file")
        head = git(repo, "rev-parse", "HEAD")
        proof = self.prove(repo, baseline, head,
                           ["file:src/a1.py", "file:src/b1.py"])
        self.assertEqual(proof["changed_paths"], ("src/a1.py", "src/b1.py"))

    def test_a_scopes_argument_that_is_not_a_sequence_is_refused(self):
        """A bare string is the plausible caller error and the dangerous one:
        `tuple("file:src/a.py")` is a tuple of CHARACTERS."""
        repo, baseline, commits = self.three_commit_branch()
        transcript = range_transcript(repo, baseline, commits[-1])
        for scopes in ("file:src/a1.py", None, 3, {"file:src/a1.py"},
                       {"file:src/a1.py": 1}, iter(["file:src/a1.py"])):
            with self.subTest(scopes=scopes):
                with self.assertRaises(state.TrackerError):
                    state.verify_source_range(
                        repo, baseline=baseline, head=commits[-1],
                        head_ref="task/T1", scopes=scopes,
                        transcript=transcript)
        #: M-R16. `str` added to the `isinstance` tuple kills nothing above:
        #: the call still refuses, because the character `'f'` fails
        #: `_scope_parts` -- so the mutant is DIAGNOSIS-equivalent, not
        #: behaviour-equivalent, and the diagnosis is the whole point of
        #: writing the screen. The message must name the SEQUENCE TYPE, not a
        #: scope, or the screen the code chose to write is unexercised.
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=baseline, head=commits[-1], head_ref="task/T1",
                scopes="file:src/a1.py", transcript=transcript)
        message = str(caught.exception)
        self.assertIn("got str", message)
        self.assertIn("CHARACTERS", message)
        self.assertNotIn("file:src/a1.py", message)

    def test_changed_paths_is_sorted_and_the_witness_is_seed_independent(self):
        """M-R10. `tuple(sorted(...))` weakened to `tuple({...})` is an
        ORDER-SENSITIVE mutant: `str` hashes are randomised per process, so a
        two-element set comes out in the asserted order about half the time
        and a single green run calls the mutant dead or alive by a coin flip
        -- measured by the review at 6 kills in 12 seeds. NINE paths make the
        coincidence one in 9!, so the witness is a named test rather than a
        lucky seed.

        The order is load-bearing rather than cosmetic: `changed_paths` is
        carried into a record whose identity is a digest, so two readings of
        one range have to produce one tuple.
        """
        repo, baseline, _ = self.three_commit_branch()
        names = ("zeta", "alpha", "mu", "beta", "omega", "kappa", "delta",
                 "gamma")
        for name in names:
            (repo / "src" / f"{name}.py").write_text("x = 1\n",
                                                     encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "eight more")
        head = git(repo, "rev-parse", "HEAD")
        changed = self.prove(repo, baseline, head,
                             ["tree:src"])["changed_paths"]
        self.assertEqual(len(changed), 9)
        self.assertEqual(changed, tuple(sorted(changed)))

    def test_the_returned_dict_carries_exactly_the_five_named_keys(self):
        repo, baseline, commits = self.three_commit_branch()
        proof = self.prove(repo, baseline, commits[-1], ["file:src/a1.py"])
        self.assertEqual(sorted(proof), ["baseline", "changed_paths",
                                         "commits", "head", "proof_mode"])

    def test_changed_paths_is_the_union_over_the_range_not_the_endpoint_diff(self):
        """A path added and then removed inside the range never appears in
        `baseline..head`, and it still escaped the write scope."""
        repo, baseline, _ = self.three_commit_branch()
        commit_file(repo, "src/transient.py", "t = 1\n", "add it")
        (repo / "src" / "transient.py").unlink()
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "and remove it")
        head = git(repo, "rev-parse", "HEAD")
        endpoint = subprocess.run(
            ("git", "-C", str(repo), "diff", "--no-renames", "--name-only",
             f"{baseline}..{head}"),
            capture_output=True, text=True, check=True).stdout.split()
        self.assertNotIn("src/transient.py", endpoint)
        with self.assertRaises(state.TrackerValidationError) as caught:
            self.prove(repo, baseline, head, ["file:src/a1.py"])
        self.assertIn("src/transient.py", str(caught.exception))


class TranscriptChainTests(TempDirTestCase):
    """The chain is verified from the transcript's OWN internal structure and
    never read off it as an assertion."""

    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)
        self.base = git(self.repo, "rev-parse", "target")
        git(self.repo, "checkout", "-q", "-b", "task/T1", "target")
        self.commits = tuple(
            commit_file(self.repo, "src/a1.py", f"v = {index}\n", f"s{index}")
            for index in range(1, 4))
        self.head = self.commits[-1]
        self.text = range_transcript(self.repo, self.base, self.head)

    def refuse(self, text, scopes=("file:src/a1.py",)):
        with self.assertRaises(state.TrackerError) as caught:
            state.verify_source_range(
                self.repo, baseline=self.base, head=self.head,
                head_ref="task/T1", scopes=list(scopes), transcript=text)
        return str(caught.exception)

    def test_the_pristine_transcript_is_accepted(self):
        proof = state.verify_source_range(
            self.repo, baseline=self.base, head=self.head,
            head_ref="task/T1", scopes=["file:src/a1.py"],
            transcript=self.text)
        self.assertEqual(proof["commits"], self.commits)

    def test_a_transcript_rooted_at_another_baseline_fails_at_the_first_link(self):
        """The whole reason this is not self-certification: the module derives
        both ends itself, so evidence gathered about a different range is
        refused by the first comparison it meets."""
        elsewhere = range_transcript(self.repo, self.commits[0], self.head)
        self.assertIn("ancestor", self.refuse(elsewhere))

    def test_a_transcript_that_stops_short_of_the_head_is_refused(self):
        records = transcript_records(self.text)
        self.assertIn("head", self.refuse("".join(records[:-1])))

    def test_a_transcript_whose_entries_are_reordered_is_refused(self):
        """Later links, so the FIRST-link diagnosis (which is the baseline's,
        and has its own test above) cannot be what fires."""
        records = transcript_records(self.text)
        records[1], records[2] = records[2], records[1]
        self.assertIn("chain", self.refuse("".join(records)))

    @staticmethod
    def record(commit, parent, paths=("src/a1.py",)):
        """One well-formed record, so a forgery is built rather than edited."""
        return ("\x00" + commit + " " + parent + "\n\n"
                + "".join(path + "\n" for path in paths))

    def test_a_duplicated_entry_is_refused(self):
        """THE NAIVE DUPLICATE PROVES LESS THAN THIS NAME CLAIMS, which is why
        the two tests below exist. Appending `records[-1:]` verbatim keeps the
        duplicate's ORIGINAL parent, so what refuses it is the chain walk --
        the duplicate names the commit before the tip as its parent when the
        commit before it is now the tip. Nothing here is a statement about
        duplicates at all."""
        records = transcript_records(self.text)
        message = self.refuse("".join(records + records[-1:]))
        self.assertIn("more than once", message)
        self.assertIn(self.head, message)

    def test_a_self_parented_duplicate_is_refused(self):
        """Re-parent the duplicate to ITSELF and the chain is intact: nothing
        in git forbids a commit being its own parent, every link matches the
        one before it, and the last record is the head. Before the
        distinctness screen this was ACCEPTED, with `commits` carrying the tip
        twice -- and Task 10 compares the worker's `commits` list against that
        tuple as the range in order."""
        text = "".join(transcript_records(self.text)
                       + [self.record(self.head, self.head)])
        message = self.refuse(text)
        self.assertIn("more than once", message)
        self.assertIn(self.head, message)

    def test_a_repeat_with_no_self_parent_anywhere_is_refused_too(self):
        """WHY THE SCREEN IS DISTINCTNESS AND NOT "never its own parent".
        `A(base) B(A) C(B) B(C) C(B)` chains from the baseline, ends at the
        head, has exactly one parent per record and no record is its own
        parent -- and it names B and C twice each. A self-parent screen would
        pass it."""
        first, second, third = self.commits
        text = (self.record(first, self.base) + self.record(second, first)
                + self.record(third, second) + self.record(second, third)
                + self.record(third, second))
        entries = state._parse_range_transcript(text)
        self.assertEqual(len(entries), 5)
        self.assertTrue(all(entry["parents"][0] != entry["commit"]
                            for entry in entries))
        message = self.refuse(text)
        self.assertIn("more than once", message)
        for commit in (second, third):
            self.assertIn(commit, message)

    def test_a_forged_parent_is_refused(self):
        records = transcript_records(self.text)
        records[1] = records[1].replace(self.commits[0], OTHER_SHA, 1)
        self.assertIn("chain", self.refuse("".join(records)))

    def test_the_chain_is_searched_over_the_integer_space_not_re_derived(self):
        """Every break position in every range length, rather than an argument
        about where the loop's indices meet."""
        repo = make_repo(self.tmp / "grid")
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/G", "target")
        commits = [commit_file(repo, "src/a1.py", f"g = {index}\n", f"g{index}")
                   for index in range(1, 7)]
        #: One reference per prefix length, because the head of a proved range
        #: is read out of the ref store and a mid-branch object name is
        #: exactly what this task stopped accepting.
        for length in range(1, 7):
            git(repo, "branch", f"task/G{length}", commits[length - 1])
        for length in range(1, 7):
            head = commits[length - 1]
            text = range_transcript(repo, base, head, f"task/G{length}")
            records = transcript_records(text)
            self.assertEqual(len(records), length)
            self.assertEqual(
                state.verify_source_range(
                    repo, baseline=base, head=head, head_ref=f"task/G{length}",
                    scopes=["file:src/a1.py"], transcript=text)["commits"],
                tuple(commits[:length]))
            for position in range(length):
                with self.subTest(length=length, position=position):
                    broken = list(records)
                    del broken[position]
                    with self.assertRaises(state.TrackerError):
                        state.verify_source_range(
                            repo, baseline=base, head=head,
                            head_ref=f"task/G{length}",
                            scopes=["file:src/a1.py"],
                            transcript="".join(broken))

    def test_the_parent_count_is_searched_over_the_integer_space(self):
        for count in range(0, 6):
            with self.subTest(parents=count):
                records = transcript_records(self.text)
                header, _, rest = records[0].partition("\n")
                commit = header[1:].split(" ")[0]
                forged = "\x00" + " ".join(
                    [commit] + [self.base] + [OTHER_SHA] * (count - 1)
                ) if count else "\x00" + commit + " "
                text = "".join([forged + "\n" + rest] + records[1:])
                if count == 1:
                    self.assertEqual(
                        state.verify_source_range(
                            self.repo, baseline=self.base, head=self.head,
                            head_ref="task/T1", scopes=["file:src/a1.py"],
                            transcript=text)["commits"], self.commits)
                    continue
                message = self.refuse(text)
                self.assertIn("root commit" if count == 0 else "linear", message)


class RangeTranscriptGrammarTests(unittest.TestCase):
    """`_parse_range_transcript` on its own. The grammar is the module's whole
    reading of an external process's stdout, so it is strict by construction:
    what it cannot account for it refuses rather than skips."""

    HEADER = "\x00" + "a" * 40 + " " + "b" * 40

    def test_an_empty_transcript_parses_to_no_entries(self):
        self.assertEqual(state._parse_range_transcript(""), ())

    def test_one_entry_with_paths(self):
        entries = state._parse_range_transcript(
            self.HEADER + "\n\nsrc/a.py\nsrc/b.py\n")
        self.assertEqual(entries, ({"commit": "a" * 40,
                                    "parents": ("b" * 40,),
                                    "paths": ("src/a.py", "src/b.py")},))

    def test_one_entry_with_no_paths(self):
        entries = state._parse_range_transcript(self.HEADER + "\n")
        self.assertEqual(entries[0]["paths"], ())

    def test_a_root_commit_header_parses_to_no_parents(self):
        entries = state._parse_range_transcript("\x00" + "a" * 40 + " \n")
        self.assertEqual(entries[0]["parents"], ())

    def test_a_merge_header_parses_to_two_parents(self):
        entries = state._parse_range_transcript(
            "\x00" + " ".join(("a" * 40, "b" * 40, "c" * 40)) + "\n")
        self.assertEqual(entries[0]["parents"], ("b" * 40, "c" * 40))

    def test_every_malformation_of_the_grammar_is_refused(self):
        sha = "a" * 40
        parent = "b" * 40
        for text in (
            "no separator at all\n",
            " \x00" + sha + " " + parent + "\n",
            "\x00" + sha + " " + parent,                       # no terminator
            "\x00" + sha + " " + parent + "\nsrc/a.py\n",      # no blank line
            #: TWO paths and no blank line. The one-path spelling above is
            #: refused by the `len(body) > 1` clause alone, so it could not
            #: tell the blank-separator clause from its neighbour -- a mutant
            #: deleting `body[0] == ""` survived the whole suite on it, and
            #: silently DROPPED the first path of every such record.
            "\x00" + sha + " " + parent + "\nsrc/a.py\nsrc/b.py\n",
            #: No space at all between commit and parents. git always prints
            #: `%H %P` with the separator, so a bare object name is not output
            #: of the emitted command even though it reads like a root commit.
            "\x00" + sha + "\n",
            "\x00" + sha + " " + parent + "\n\n",              # blank, no path
            "\x00" + sha + " " + parent + "\n\n\nsrc/a.py\n",  # two blanks
            "\x00" + sha + " " + parent + "\n\nsrc/a.py\n\n",  # blank after
            "\x00" + sha + "  " + parent + "\n",               # double space
            "\x00" + sha.upper() + " " + parent + "\n",
            "\x00" + sha[:39] + " " + parent + "\n",
            "\x00" + sha + " " + parent[:39] + "\n",
            "\x00" + sha + "\t" + parent + "\n",
            "\x00\n",
            "\x00 " + parent + "\n",
        ):
            with self.subTest(text=text):
                with self.assertRaises(state.TrackerValidationError):
                    state._parse_range_transcript(text)

    def test_a_transcript_that_is_not_a_string_is_refused_inside_the_family(self):
        for text in (None, 3, b"\x00", ["\x00"], object()):
            with self.subTest(text=text):
                with self.assertRaises(state.TrackerValidationError):
                    state._parse_range_transcript(text)


class SourceRangeDegradedModeTests(TempDirTestCase):
    """Absent evidence is a refusal that NAMES WHAT IS MISSING, never a weaker
    check passed silently."""

    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)
        self.base = git(self.repo, "rev-parse", "target")
        git(self.repo, "checkout", "-q", "-b", "task/T1", "target")
        self.head = commit_file(self.repo, "src/a1.py", "v = 1\n", "one")

    def refuse(self, transcript):
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                self.repo, baseline=self.base, head=self.head,
                head_ref="task/T1", scopes=["file:src/a1.py"],
                transcript=transcript)
        return str(caught.exception)

    def test_a_missing_transcript_names_the_command_that_produces_it(self):
        printable = " ".join(state.source_range_commands(
            self.repo, baseline=self.base, head=self.head,
            head_ref="task/T1")[0])
        for transcript in (None, 3, b"", ["\x00"]):
            with self.subTest(transcript=transcript):
                message = self.refuse(transcript)
                self.assertIn(printable, message)
                self.assertIn("no range transcript", message)

    def test_an_empty_transcript_is_refused_and_not_read_as_a_clean_range(self):
        message = self.refuse("")
        self.assertIn("descend", message)

    def test_nothing_about_the_refusal_depends_on_the_scope_being_wrong(self):
        """The degraded refusal fires with a scope that would have passed."""
        self.assertIn("no range transcript", self.refuse(None))


class ProofModeTests(TempDirTestCase):
    """`attested` with the transcript digest. Appearing to verify is the
    failure mode to avoid, so the returned dict says what kind of proof this
    is and binds the exact bytes it was given."""

    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)
        self.base = git(self.repo, "rev-parse", "target")
        git(self.repo, "checkout", "-q", "-b", "task/T1", "target")
        self.head = commit_file(self.repo, "src/a1.py", "v = 1\n", "one")
        self.text = range_transcript(self.repo, self.base, self.head)

    def prove(self, transcript):
        return state.verify_source_range(
            self.repo, baseline=self.base, head=self.head,
            head_ref="task/T1", scopes=["file:src/a1.py"],
            transcript=transcript)

    def test_the_proof_mode_is_attested_bound_to_the_transcript_digest(self):
        proof = self.prove(self.text)
        self.assertEqual(
            proof["proof_mode"],
            f"attested{state._DIGEST_DELIMITER}{state._digest(self.text)}")
        self.assertTrue(proof["proof_mode"].startswith(state.PROOF_ATTESTED))

    def test_two_transcripts_with_one_conclusion_carry_two_digests(self):
        """The digest binds the EVIDENCE, not the verdict. Two transcripts
        that differ only in the order git listed one commit's paths reach the
        SAME conclusion -- `changed_paths` is a set, ordered by this module --
        and are still two different attestations."""
        (self.repo / "src" / "a1.py").write_text("v = 2\n", encoding="utf-8")
        (self.repo / "src" / "b1.py").write_text("b = 1\n", encoding="utf-8")
        git(self.repo, "add", "--", "src/a1.py", "src/b1.py")
        git(self.repo, "commit", "-qm", "both")
        head = git(self.repo, "rev-parse", "HEAD")
        text = range_transcript(self.repo, self.base, head)
        records = transcript_records(text)
        last = records[-1].rstrip("\n").split("\n")
        self.assertEqual(last[2:], ["src/a1.py", "src/b1.py"])
        swapped = "".join(records[:-1]
                          + ["\n".join(last[:2] + last[:1:-1]) + "\n"])
        self.assertNotEqual(swapped, text)
        scopes = ["tree:src"]
        first_proof = state.verify_source_range(
            self.repo, baseline=self.base, head=head, head_ref="task/T1",
            scopes=scopes, transcript=text)
        second_proof = state.verify_source_range(
            self.repo, baseline=self.base, head=head, head_ref="task/T1",
            scopes=scopes, transcript=swapped)
        self.assertEqual(first_proof["changed_paths"],
                         second_proof["changed_paths"])
        self.assertEqual(first_proof["commits"], second_proof["commits"])
        self.assertNotEqual(first_proof["proof_mode"],
                            second_proof["proof_mode"])
        self.assertEqual(first_proof["commits"], (self.head, head))

    def test_the_proof_mode_is_one_table_safe_cell(self):
        proof = self.prove(self.text)
        self.assertEqual(
            state._table_safe(proof["proof_mode"], field="proof_mode"),
            proof["proof_mode"])


class RangeCrossProductTests(TempDirTestCase):
    """The cross-product of RANGE SHAPES by TRANSCRIPT MALFORMATIONS.

    A corpus built from known mutants proves only that those mutants die. The
    cases here are generated from the structure being screened -- every shape a
    range can have, against every way the transcript reporting it can be
    wrong -- and the expectation is derived mechanically: a call is accepted
    if and only if the shape is sound AND the transcript is untouched.
    """

    @staticmethod
    def shape_single(tmp):
        repo = make_repo(tmp)
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "t", "target")
        head = commit_file(repo, "src/a1.py", "v = 1\n", "one")
        return repo, base, head, "t", ["file:src/a1.py"], True

    @staticmethod
    def shape_linear_three(tmp):
        repo = make_repo(tmp)
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "t", "target")
        for index in range(3):
            head = commit_file(repo, "src/a1.py", f"v = {index}\n", f"s{index}")
        return repo, base, head, "t", ["file:src/a1.py"], True

    @staticmethod
    def shape_nested_tree(tmp):
        repo = make_repo(tmp)
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "t", "target")
        commit_file(repo, "src/a1.py", "v = 1\n", "one")
        head = commit_file(repo, "src/deep/nested.py", "n = 1\n", "two")
        return repo, base, head, "t", ["tree:src"], True

    @staticmethod
    def shape_rename_out_of_scope(tmp):
        repo = make_repo(tmp)
        git(repo, "checkout", "-q", "target")
        for directory, name in (("theirs", "victim.py"), ("mine", "own.py")):
            (repo / directory).mkdir()
            (repo / directory / name).write_text("x = 1\n" * 40,
                                                 encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "two trees")
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "t", "target")
        git(repo, "mv", "theirs/victim.py", "mine/victim.py")
        git(repo, "commit", "-qm", "steal")
        return (repo, base, git(repo, "rev-parse", "HEAD"), "t",
                ["tree:mine"], False)

    @staticmethod
    def shape_empty_commit(tmp):
        repo = make_repo(tmp)
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "t", "target")
        commit_file(repo, "src/a1.py", "v = 1\n", "one")
        git(repo, "commit", "-q", "--allow-empty", "-m", "nothing")
        return (repo, base, git(repo, "rev-parse", "HEAD"), "t",
                ["file:src/a1.py"], False)

    @staticmethod
    def shape_merge(tmp):
        repo = make_repo(tmp)
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "t", "target")
        commit_file(repo, "src/a1.py", "v = 1\n", "one")
        git(repo, "checkout", "-q", "-b", "side", base)
        commit_file(repo, "src/side.py", "s = 1\n", "side")
        git(repo, "checkout", "-q", "t")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge", "side")
        return (repo, base, git(repo, "rev-parse", "HEAD"), "t",
                ["file:src/a1.py", "file:src/side.py"], False)

    @staticmethod
    def shape_orphan(tmp):
        repo = make_repo(tmp)
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "--orphan", "unrelated")
        git(repo, "rm", "-rqf", ".")
        head = commit_file(repo, "other.py", "x = 1\n", "unrelated")
        return repo, base, head, "unrelated", ["file:other.py"], False

    @staticmethod
    def shape_behind(tmp):
        repo = make_repo(tmp)
        git(repo, "checkout", "-q", "-b", "t", "target")
        first = commit_file(repo, "src/a1.py", "v = 1\n", "one")
        second = commit_file(repo, "src/a1.py", "v = 2\n", "two")
        git(repo, "branch", "behind", first)
        return repo, second, first, "behind", ["file:src/a1.py"], False

    SHAPES = ("shape_single", "shape_linear_three", "shape_nested_tree",
              "shape_rename_out_of_scope", "shape_empty_commit", "shape_merge",
              "shape_orphan", "shape_behind")

    @staticmethod
    def malformations():
        """Each returns the mutated transcript, or `None` when it cannot apply
        to this transcript -- a skip that is counted, never a silent pass."""
        def needs(count):
            def decorate(function):
                def wrapped(text):
                    records = transcript_records(text)
                    return None if len(records) < count else function(records)
                return wrapped
            return decorate

        def with_paths(function):
            def wrapped(text):
                records = transcript_records(text)
                index = next((position for position, record in enumerate(records)
                              if "\n\n" in record), None)
                return None if index is None else function(records, index)
            return wrapped

        return {
            "empty": lambda text: "" if text else None,
            "whitespace": lambda text: "   \n",
            "prose": lambda text: "fatal: bad revision\n",
            "drop_first": needs(1)(lambda r: "".join(r[1:])),
            "drop_last": needs(1)(lambda r: "".join(r[:-1])),
            "swap_two": needs(2)(lambda r: "".join([r[1], r[0]] + r[2:])),
            "duplicate_last": needs(1)(lambda r: "".join(r + r[-1:])),
            "reverse_all": needs(2)(lambda r: "".join(reversed(r))),
            "forge_parent": needs(1)(
                lambda r: "".join([r[0].replace(r[0].split(" ")[1].split("\n")[0],
                                                OTHER_SHA, 1)] + r[1:])),
            "forge_commit": needs(1)(
                lambda r: "".join([r[0].replace(r[0][1:41], OTHER_SHA, 1)] + r[1:])),
            "second_parent": needs(1)(
                lambda r: "".join([r[0].split("\n")[0] + " " + OTHER_SHA + "\n"
                                   + r[0].partition("\n")[2]] + r[1:])),
            "no_parent": needs(1)(
                lambda r: "".join(["\x00" + r[0][1:41] + " \n"
                                   + r[0].partition("\n")[2]] + r[1:])),
            "uppercase_sha": needs(1)(
                lambda r: "".join([r[0][:1] + r[0][1:41].upper() + r[0][41:]]
                                  + r[1:])),
            "short_sha": needs(1)(
                lambda r: "".join([r[0][:1] + r[0][2:]] + r[1:])),
            "drop_separator_byte": needs(1)(lambda r: "".join(r[:-1] + [r[-1][1:]])),
            "trailing_junk": lambda text: text + "and one more thing\n",
            "no_terminator": lambda text: text.rstrip("\n") or None,
            "drop_blank_line": with_paths(
                lambda r, i: "".join(r[:i] + [r[i].replace("\n\n", "\n", 1)]
                                     + r[i + 1:])),
            "drop_all_paths": with_paths(
                lambda r, i: "".join(r[:i] + [r[i].partition("\n")[0] + "\n"]
                                     + r[i + 1:])),
            "inject_escaped_path": with_paths(
                lambda r, i: "".join(r[:i] + [r[i].rstrip("\n")
                                              + '\n"a\\nb"\n'] + r[i + 1:])),
            "inject_absolute_path": with_paths(
                lambda r, i: "".join(r[:i] + [r[i].rstrip("\n")
                                              + "\n/etc/passwd\n"] + r[i + 1:])),
            "inject_traversal_path": with_paths(
                lambda r, i: "".join(r[:i] + [r[i].rstrip("\n")
                                              + "\n../escape.py\n"] + r[i + 1:])),
            "inject_out_of_scope_path": with_paths(
                lambda r, i: "".join(r[:i] + [r[i].rstrip("\n")
                                              + "\nelsewhere/x.py\n"] + r[i + 1:])),
        }

    def test_the_cross_product_of_range_shapes_and_transcript_malformations(self):
        malformations = self.malformations()
        applied = 0
        skipped = []
        accepted = []
        for index, shape_name in enumerate(self.SHAPES):
            root = self.tmp / f"s{index}"
            root.mkdir()
            repo, base, head, head_ref, scopes, sound = getattr(
                self, shape_name)(root)
            pristine = range_transcript(repo, base, head, head_ref)

            def call(text, head_ref=head_ref):
                return state.verify_source_range(
                    repo, baseline=base, head=head, head_ref=head_ref,
                    scopes=list(scopes), transcript=text)

            with self.subTest(shape=shape_name, transcript="pristine"):
                if sound:
                    accepted.append((shape_name, "pristine"))
                    proof = call(pristine)
                    self.assertEqual(proof["head"], head)
                    self.assertEqual(proof["baseline"], base)
                else:
                    with self.assertRaises(state.TrackerError):
                        call(pristine)
            for name, mutate in sorted(malformations.items()):
                text = mutate(pristine)
                if text is None or text == pristine:
                    skipped.append((shape_name, name))
                    continue
                applied += 1
                with self.subTest(shape=shape_name, transcript=name):
                    with self.assertRaises(state.TrackerError):
                        call(text)
        #: THE CORPUS IS ONLY EVIDENCE IF IT WAS ACTUALLY GENERATED, and a
        #: count alone cannot say that a skip was legitimate. Every skipped
        #: cell is named, with the structural reason it cannot apply -- a
        #: malformation that quietly became a no-op would otherwise read as a
        #: case that passed.
        self.assertEqual(len(self.SHAPES), 8)
        self.assertEqual(len(malformations), 23)
        self.assertEqual(applied + len(skipped), 8 * 23)
        self.assertEqual(applied, 157)
        #: `shape_behind` is the only shape whose transcript is EMPTY, so
        #: every record-level malformation and `empty` itself are no-ops on
        #: it; `swap_two`/`reverse_all` need two records and three shapes have
        #: one; and `shape_orphan`'s single record is ALREADY parentless.
        self.assertEqual(sorted(skipped), sorted(
            [("shape_behind", name) for name in sorted(malformations)
             if name not in ("whitespace", "prose", "trailing_junk")]
            + [(shape, name)
               for shape in ("shape_single", "shape_rename_out_of_scope",
                             "shape_orphan")
               for name in ("swap_two", "reverse_all")]
            + [("shape_orphan", "no_parent")]))
        self.assertEqual(len(skipped), 27)
        self.assertEqual(
            accepted,
            [("shape_single", "pristine"), ("shape_linear_three", "pristine"),
             ("shape_nested_tree", "pristine")])


class SourceRangeTotalityTests(TempDirTestCase):
    """No input leaves this module's exception family.

    The case list is derived from the CALL TREE -- `verify_source_range` ->
    `_repo_argument`, `_resolved_commit` (which now opens `_git_store` BEFORE
    it forks on whether the end is already an object name, so every end walks
    the ref store and a 40-hex end no longer answers itself for free),
    `_parse_range_transcript`, `_scope_parts` -> `_parse_write_scope` ->
    `_safe_relative`, `_path_in_scope` -> the same -- and not from the
    fixtures above. Path arguments carry a NUL and a lone surrogate because
    both are strings Python will hand straight to a syscall.

    `head_ref` IS IN THE SWEEP because it is an argument, and the argument
    this task added is exactly the one a totality claim written before it
    would silently not cover.
    """

    NUL_SCREENED = ("repo", "baseline", "head", "head_ref")

    HOSTILE = (
        None, 0, 1, -1, 3.5, True, b"bytes", [], (), {}, set(), object(),
        ["file:src/a1.py"], {"scope": "file:src/a1.py"},
        "", " ", "\t", "\n", "-", "\x00", "a\x00b", "\x00repo", "\udc80",
        "a\udc80b",
        "x" * 5000, "../escape", "/abs/path", "a\\b", "src/*.py", ".",
        "..", "a/../b", "HEAD~1", "refs/heads/target", "target",
        "A" * 40, "a" * 39, "a" * 41, "a" * 40, "\x00" + "a" * 40 + "\n",
    )

    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)
        self.base = git(self.repo, "rev-parse", "target")
        git(self.repo, "checkout", "-q", "-b", "task/T1", "target")
        self.head = commit_file(self.repo, "src/a1.py", "v = 1\n", "one")
        self.text = range_transcript(self.repo, self.base, self.head)

    def sound(self, symbolic: bool) -> dict:
        return {
            "repo": self.repo,
            "baseline": "target" if symbolic else self.base,
            "head": self.head,
            "head_ref": "task/T1",
            "scopes": ["file:src/a1.py"],
            "transcript": self.text,
        }

    def test_no_argument_of_any_type_escapes_the_exception_family(self):
        checked = 0
        for symbolic in (False, True):
            for name in ("repo", "baseline", "head", "head_ref", "scopes",
                         "transcript"):
                for value in self.HOSTILE:
                    arguments = self.sound(symbolic)
                    arguments[name] = value
                    checked += 1
                    with self.subTest(argument=name, value=repr(value)[:40],
                                      symbolic=symbolic):
                        try:
                            outcome = state.verify_source_range(
                                arguments.pop("repo"), **arguments)
                        except state.TrackerError:
                            continue
                        except BaseException as escaped:  # noqa: BLE001
                            self.fail(
                                f"{name}={value!r} raised "
                                f"{type(escaped).__name__}: {escaped}")
                        self.assertIsInstance(outcome, dict)
        self.assertEqual(checked, 2 * 6 * len(self.HOSTILE))

    def test_every_nul_bearing_argument_the_module_screens_is_refused(self):
        """M-R14, and the reason the test above could not see it.

        `if _RANGE_SEPARATOR in repo:` weakened to `repo[1:]` SURVIVES the
        totality sweep: `"\x00"` and `"\x00repo"` are in the corpus and are
        genuinely driven through `verify_source_range`, but the assertion
        there is "a `TrackerError` or a dict" -- and with a LEADING NUL the
        mutant screens nothing, git is never run, the transcript still
        chains, and the call returns a dict. The case was in the corpus and
        the assertion could not tell whether the screen had fired.

        So the arguments whose NUL screen IS the point get the stronger
        claim: for them a NUL is a refusal, not merely a non-escape. The
        other two are deliberately left out rather than folded in -- a NUL in
        `scopes` or `transcript` is refused by the scope grammar and by the
        record grammar for reasons that have nothing to do with a NUL, and
        asserting it here would pin an accident.

        Why it matters beyond the mutant: `subprocess.run(('git', '-C',
        '\x00repo', ...))` raises `ValueError: embedded null byte`, which is
        not an `OSError` and is outside this module's exception family, so an
        unscreened location kills the controller rather than refusing the
        cell.
        """
        bearing = tuple(value for value in self.HOSTILE
                        if isinstance(value, str) and "\x00" in value)
        self.assertEqual(
            bearing, ("\x00", "a\x00b", "\x00repo", "\x00" + "a" * 40 + "\n"))
        self.assertTrue(any(value.startswith("\x00") for value in bearing))
        self.assertTrue(any(not value.startswith("\x00") for value in bearing))
        checked = 0
        for symbolic in (False, True):
            for name in self.NUL_SCREENED:
                for value in bearing:
                    arguments = self.sound(symbolic)
                    arguments[name] = value
                    checked += 1
                    with self.subTest(argument=name, value=repr(value),
                                      symbolic=symbolic):
                        with self.assertRaises(state.TrackerError):
                            state.verify_source_range(
                                arguments.pop("repo"), **arguments)
        self.assertEqual(checked, 2 * 4 * 4)

    def test_source_range_commands_is_total_over_the_same_corpus(self):
        for name in ("repo", "baseline", "head", "head_ref"):
            for value in self.HOSTILE:
                arguments = {"repo": self.repo, "baseline": self.base,
                             "head": self.head, "head_ref": "task/T1"}
                arguments[name] = value
                with self.subTest(argument=name, value=repr(value)[:40]):
                    try:
                        outcome = state.source_range_commands(
                            arguments.pop("repo"), **arguments)
                    except state.TrackerError:
                        continue
                    except BaseException as escaped:  # noqa: BLE001
                        self.fail(f"{name}={value!r} raised "
                                  f"{type(escaped).__name__}: {escaped}")
                    self.assertIsInstance(outcome, tuple)

    def test_reserved_baseline_is_total_over_the_same_corpus(self):
        """`attempt=1` and `attempt=True` are the two members of the corpus
        this function ACCEPTS -- `True == 1` in Python and `_attempt_token`
        is where that is decided, not here -- so the claim is the same one as
        above: every outcome is either an answer or a `TrackerError`."""
        row = {"id": "T1", "checkpoints": f"baseline:attempt-001@{'a' * 40}"}
        for value in self.HOSTILE:
            with self.subTest(row=repr(value)[:40]):
                with self.assertRaises(state.TrackerError):
                    state.reserved_baseline(value, attempt=1)
            with self.subTest(attempt=repr(value)[:40]):
                try:
                    outcome = state.reserved_baseline(row, attempt=value)
                except state.TrackerError:
                    continue
                except BaseException as escaped:  # noqa: BLE001
                    self.fail(f"attempt={value!r} raised "
                              f"{type(escaped).__name__}: {escaped}")
                self.assertEqual(outcome, "a" * 40)
                self.assertEqual(int(value), 1)


class RefStoreNullByteTests(TempDirTestCase):
    """Two escapes from the exception family, found by the totality corpus
    above and fixed where they live.

    A NUL in a path is a `ValueError`, NOT an `OSError`, and neither
    `_git_store`'s probe nor the `.git` pointer payload was screened for one.
    Both are reachable with input the WORKER controls -- it owns the
    repository this proof is taken over -- so a `ValueError` escaping
    `except TrackerError` kills an unattended run instead of refusing a
    repository.
    """

    def test_a_repository_path_carrying_a_null_byte_is_refused_in_family(self):
        with self.assertRaises(state.TrackerValidationError):
            state._resolved_commit("\x00", "target")

    def test_a_git_pointer_payload_carrying_a_null_byte_is_refused_in_family(self):
        root = self.tmp / "linked"
        root.mkdir()
        (root / ".git").write_bytes(b"gitdir: \x00evil")
        with self.assertRaises(state.TrackerValidationError):
            state._resolved_commit(root, "target")

    def test_a_commondir_payload_carrying_a_null_byte_is_refused_in_family(self):
        repo = make_repo(self.tmp)
        gitdir = repo / ".git"
        (gitdir / "commondir").write_bytes(b"\x00evil")
        with self.assertRaises(state.TrackerValidationError):
            state._resolved_commit(repo, "target")

    def test_an_ordinary_linked_worktree_pointer_still_resolves(self):
        """The screen refuses a NUL and nothing else: the pointer file is the
        whole integration topology of this phase."""
        repo = make_repo(self.tmp)
        git(repo, "worktree", "add", "-q", "-b", "wt",
            str(self.tmp / "wt"), "target")
        self.assertEqual(state._resolved_commit(self.tmp / "wt", "target"),
                         git(repo, "rev-parse", "target"))


class SourceRangeAnchorTests(TempDirTestCase):
    """The clause the whole design rests on, asserted rather than narrated.

    THIS CLASS REPLACES ONE THAT ASSERTED THE DEFECT AS A FEATURE.
    `test_object_name_ends_never_touch_the_filesystem` drove a directory that
    was not a repository through `verify_source_range` and asserted a
    complete `attested#sha256=` proof came back -- on the reasoning that
    touching no file made `_require_regular_file` irrelevant to this task.
    The reasoning was backwards in two ways. The FIFO hazard is a reason to
    go THROUGH the module's door, not a reason never to open one; and both
    ends of the PRODUCTION call are forty hex characters, so "when both ends
    are object names" was not an edge case being documented, it was the only
    case that ships. A test that locks in a hole is worse than no test,
    because it is quoted as coverage.

    The inverse of each of that test's assertions is below.
    """

    def worked_branch(self):
        repo = make_repo(self.tmp)
        base = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        head = commit_file(repo, "src/a1.py", "v = 1\n", "one")
        return repo, base, head, range_transcript(repo, base, head)

    def test_a_directory_that_is_not_a_repository_is_a_stop(self):
        """The reproduction, inverted. Before: a full `attested` proof over
        commits that do not exist, in a directory that does not exist."""
        _repo, base, head, text = self.worked_branch()
        absent = self.tmp / "no-such-repository"
        self.assertFalse(absent.exists())
        #: Two shapes of "not a repository": a name that is not there at
        #: all, and a directory that IS there and holds no `.git`.
        for location in (absent, self.tmp):
            with self.subTest(location=str(location)):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.verify_source_range(
                        location, baseline=base, head=head,
                        head_ref="task/T1", scopes=["file:src/a1.py"],
                        transcript=text)
                self.assertIn("not a git repository", str(caught.exception))

    def test_the_fabricated_range_over_a_fabricated_repository_is_refused(self):
        """The review's exact failing input, byte for byte."""
        with self.assertRaises(state.TrackerError):
            state.verify_source_range(
                "/nonexistent/not-a-repo", baseline="a" * 40, head="b" * 40,
                head_ref="task/T1", scopes=["file:src/a1.py"],
                transcript="\x00" + "c" * 40 + " " + "a" * 40
                           + "\n\nsrc/a1.py\n"
                           + "\x00" + "b" * 40 + " " + "c" * 40
                           + "\n\nsrc/a1.py\n")

    def test_an_object_name_no_longer_answers_itself_without_a_ref_store(self):
        """`_resolved_commit`'s short-circuit was BEFORE the store read, so a
        forty-hex ref came back unchanged from a path that was not a
        repository at all. The short-circuit is still there -- an object name
        is its own answer -- but it is now conditional on the store."""
        repo = make_repo(self.tmp)
        self.assertEqual(state._resolved_commit(repo, "a" * 40), "a" * 40)
        with self.assertRaises(state.TrackerValidationError):
            state._resolved_commit(self.tmp / "no-such-repository", "a" * 40)

    def test_the_head_is_the_tip_the_ref_store_holds_not_the_claim(self):
        repo, base, head, text = self.worked_branch()
        elsewhere = git(repo, "rev-parse", "target")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=base, head=elsewhere, head_ref="task/T1",
                scopes=["file:src/a1.py"], transcript=text)
        message = str(caught.exception)
        self.assertIn("is not the tip of 'task/T1'", message)
        self.assertIn(head, message)

    def test_a_head_reference_the_store_does_not_carry_is_a_stop(self):
        repo, base, head, text = self.worked_branch()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=base, head=head, head_ref="task/T404",
                scopes=["file:src/a1.py"], transcript=text)
        self.assertIn("names no reference", str(caught.exception))

    def test_an_object_name_is_refused_as_the_head_reference(self):
        """Accepting one would restore the hole: an object name answers
        itself, so the store would go unread again."""
        repo, base, head, text = self.worked_branch()
        for head_ref in (head, "a" * 40, "", "   ", None, 3):
            with self.subTest(head_ref=head_ref):
                with self.assertRaises(state.TrackerError):
                    state.verify_source_range(
                        repo, baseline=base, head=head, head_ref=head_ref,
                        scopes=["file:src/a1.py"], transcript=text)

    def test_deleting_the_branch_after_the_work_refuses_rather_than_attests(self):
        """The honest transcript still parses and still chains. What is gone
        is the reference, and with it the module's only tie between the
        claimed head and this repository."""
        repo, base, head, text = self.worked_branch()
        self.assertEqual(
            state.verify_source_range(
                repo, baseline=base, head=head, head_ref="task/T1",
                scopes=["file:src/a1.py"], transcript=text)["head"], head)
        git(repo, "checkout", "-q", "target")
        git(repo, "branch", "-qD", "task/T1")
        with self.assertRaises(state.TrackerValidationError):
            state.verify_source_range(
                repo, baseline=base, head=head, head_ref="task/T1",
                scopes=["file:src/a1.py"], transcript=text)

    def test_the_emitter_anchors_exactly_as_the_verifier_does(self):
        """Two anchors would be one anchor and one hole."""
        _repo, base, head, _text = self.worked_branch()
        absent = self.tmp / "no-such-repository"
        with self.assertRaises(state.TrackerValidationError):
            state.source_range_commands(absent, baseline=base, head=head,
                                        head_ref="task/T1")

    def test_no_new_door_onto_the_filesystem_was_opened(self):
        """`_require_regular_file` stays the module's single door; Task 8 adds
        no `open`, `read_text` or `is_file` of its own."""
        source = module_function_source("verify_source_range")
        source += module_function_source("source_range_commands")
        source += module_function_source("_parse_range_transcript")
        source += module_function_source("reserved_baseline")
        for forbidden in ("open(", "read_text", "read_bytes", "is_file",
                          "is_dir", "iterdir", "stat("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class RangeGrammarDivergenceTests(unittest.TestCase):
    """Every grammar this task reads a transcript with is hand-rolled, and
    each is MEASURED against the `re` pattern it replaces IN BOTH DIRECTIONS.

    `re` is not importable by the module. It is importable here, and a
    divergence nobody measured is a divergence nobody chose.
    """

    CORPUS = (
        "", " ", "a" * 40, "A" * 40, "a" * 39, "a" * 41, "0" * 40,
        "abcdef0123456789" * 2 + "abcdefgh", "g" * 40,
        "a" * 40 + "\n", "\n" + "a" * 40, "a" * 40 + " ",
        "٠" * 40, "³" * 40, "ａ" * 40, "à" * 40,
        "a" * 39 + "٠", "a" * 20 + "\n" + "a" * 19,
        "\x00" + "a" * 40, "a" * 40 + "\x00", "a" * 40 + "\x00" + "b" * 40,
        "\udc80" * 40, "a" * 39 + "\udc80",
    )

    def test_the_commit_grammar_agrees_with_its_ascii_pattern_everywhere(self):
        """`_COMMIT` is P02's `_Hex(40)` and it is consumed, not re-declared.
        `[0-9a-f]{40}` under `fullmatch` is its exact `re` equivalent; the
        divergences below are against the patterns a careless hand reaches
        for, and every one of them is a TIGHTENING."""
        exact = re.compile(r"[0-9a-f]{40}")
        loose_case = re.compile(r"[0-9a-fA-F]{40}")
        word_class = re.compile(r"\w{40}")
        digit_class = re.compile(r"[\da-f]{40}")
        dollar_anchored = re.compile(r"^[0-9a-f]{40}$")
        divergences = {"loose_case": [], "word_class": [], "digit_class": [],
                       "dollar_anchored": []}
        for value in self.CORPUS:
            ours = state._COMMIT.fullmatch(value)
            self.assertIs(ours, exact.fullmatch(value) is not None,
                          f"exact pattern disagrees on {value!r}")
            if ours is not (loose_case.fullmatch(value) is not None):
                divergences["loose_case"].append(value)
            if ours is not (word_class.fullmatch(value) is not None):
                divergences["word_class"].append(value)
            if ours is not (digit_class.fullmatch(value) is not None):
                divergences["digit_class"].append(value)
            if ours is not (dollar_anchored.match(value) is not None):
                divergences["dollar_anchored"].append(value)
        #: Measured, in both directions, and every one is the pattern being
        #: LOOSER than the hand-rolled grammar. Written down with its reason:
        #:  * loose_case  -- accepts an uppercase object name git never prints
        #:  * word_class  -- `\w` is UNICODE: Arabic-Indic digits, fullwidth
        #:                   latin and combining sequences all match
        #:  * digit_class -- `\d` is UNICODE for the same reason
        #:  * dollar_anchored -- `$` matches before a TRAILING NEWLINE, so a
        #:                   sha with `\n` glued to it reads as a clean sha,
        #:                   which is exactly the transcript-splicing case
        self.assertEqual(divergences["loose_case"], ["A" * 40])
        self.assertEqual(divergences["word_class"], [
            "A" * 40,                             # uppercase hex
            "abcdef0123456789" * 2 + "abcdefgh",  # g/h are word chars
            "g" * 40,                             # and are not hex digits
            "\u0660" * 40,                        # ARABIC-INDIC DIGIT ZERO
            "\u00b3" * 40,                        # SUPERSCRIPT THREE
            "\uff41" * 40,                        # FULLWIDTH LATIN SMALL A
            "a" * 39 + "\u0660",                  # ONE non-ASCII digit is
        ])                                        # enough to flip it
        self.assertEqual(divergences["digit_class"],
                         ["\u0660" * 40, "a" * 39 + "\u0660"])
        self.assertEqual(divergences["dollar_anchored"], ["a" * 40 + "\n"])
        for family, values in divergences.items():
            for value in values:
                with self.subTest(family=family, value=value):
                    self.assertFalse(state._COMMIT.fullmatch(value))

    def test_fullmatch_search_and_multiline_are_three_different_questions(self):
        """The header grammar is a `fullmatch` on a line the splitter already
        produced -- never a `search`, and never a MULTILINE `^...$`. On a
        transcript the three answer differently, and only one of them is the
        question being asked."""
        spliced = "\x00" + "a" * 40 + " " + "b" * 40 + "\nsrc/" + "c" * 40 + "\n"
        pattern = r"[0-9a-f]{40}"
        self.assertIsNone(re.compile(pattern).fullmatch(spliced))
        self.assertIsNotNone(re.compile(pattern).search(spliced))
        self.assertEqual(
            len(re.compile(r"^[0-9a-f]{40}$", re.MULTILINE).findall(spliced)), 0)
        #: and the module asks the fullmatch question, per line, after the
        #: record separator has already cut the transcript into records
        entries = state._parse_range_transcript(
            "\x00" + "a" * 40 + " " + "b" * 40 + "\n\nsrc/" + "c" * 40 + "\n")
        self.assertEqual(entries[0]["paths"], ("src/" + "c" * 40,))

    def test_the_module_still_compiles_no_pattern(self):
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        self.assertNotIn("re.compile(", source)
        self.assertIsNone(sys.modules["pipeline_auto_state"].__dict__.get("re"))


# --------------------------------------------------------------------------
# Task 9 -- immutable worker-result publication.
#
# THE TREE IS `agent-output/`, AND THAT IS A CROSS-PHASE CONTRACT rather than
# a local naming choice. P06's `owner_history` scans this tree for owners the
# tracker no longer names and decides master-reviewer independence on what it
# finds; P07 publishes the same tree in `SKILL.md` as the run layout a user
# reads. A scan pointed at a directory nobody writes contributes the EMPTY SET
# and `owner_history` returns only the owners it already had from tracker rows
# -- a fail-open in the one direction this check exists to close, because a
# worker released after finishing a task can then be drawn to review its own
# work. So the directory name is pinned as a module constant here and cited
# there, exactly as the owner LINE is pinned as `_OWNER_LINE_PREFIX` and cited
# there, and for the same reason: one spelling, in one place.
#
# THE OWNER GRAMMAR IS NOT RESTATED BY THIS TASK. `render_worker_result`
# already emits `_owner_line`, whose docstring names itself the single
# conversion point in both directions; Task 9 renders THROUGH it and adds no
# second spelling. The tests below assert the absence of one.
# --------------------------------------------------------------------------

#: `st_mode` type bits, spelled here rather than by importing `stat`, whose
#: name is one character from this file's `state` alias.
_IFMT = 0o170000
_IFIFO = 0o010000
_IFDIR = 0o040000
_IFREG = 0o100000
_IFLNK = 0o120000


@contextlib.contextmanager
def publication_deadline(seconds: int, what: str):
    """Turn a hang into a named failure, where the platform allows it.

    A FIFO under `agent-output/` is the C1 shape: `is_file()` is False for it,
    so an existence test reads it as absence, and the `read` that follows
    BLOCKS until a writer arrives. Under the run lock no writer is coming, so
    the run stops dead with no diagnostic and no timeout. An `assertRaises`
    that never returns is not an assertion, which is why every call in the
    cross-product below is bounded.
    """
    if not hasattr(signal, "SIGALRM"):  # pragma: no cover - POSIX only
        yield
        return

    def expire(signum, frame):
        raise AssertionError(
            f"{what} blocked: the open reached a name that never answers, "
            "which is the deadlock `_require_regular_file` exists to prevent")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def name_state(path) -> tuple:
    """Everything observable about whatever is at `path`, FIFO included.

    `read_bytes` alone cannot express "unchanged" for the shapes this task has
    to refuse -- a FIFO cannot be read at all, a dangling symlink has no
    contents, and a directory's contents are its entries. The snapshot is taken
    with `lstat`, so a symlink is compared as a symlink rather than as the file
    it points at, and a refusal that quietly replaced the link with a regular
    file of the right bytes would be caught.

    `st_ino` IS IN EVERY BRANCH, AND IT WAS IN TWO. The two regular-file
    branches carried it and the symlink, FIFO and directory branches did not,
    so 14 of the cross-product's 34 cells compared type, mode, target and
    entries but NOT identity -- and a refusal that unlinked a symlink and
    recreated it pointing at the same place, or replaced a FIFO with an
    identical one, read as "unchanged". It costs nothing: the number is
    already in the `lstat` that every branch has done.
    """
    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        #: NotADirectoryError is the other spelling of "not there": it is what
        #: `lstat` reports when a PARENT component is a regular file, and
        #: `_require_regular_file` folds exactly these two into absence.
        return ("absent",)
    kind = info.st_mode & _IFMT
    mode = info.st_mode & 0o7777
    if kind == _IFLNK:
        return ("symlink", os.readlink(path), mode, info.st_ino)
    if kind == _IFIFO:
        return ("fifo", mode, info.st_ino)
    if kind == _IFDIR:
        return ("directory", tuple(sorted(os.listdir(path))), mode, info.st_ino)
    try:
        return ("regular", Path(path).read_bytes(), mode, info.st_ino)
    except OSError as exc:
        return ("regular-unreadable", type(exc).__name__, mode, info.st_ino)


def make_run_in(repo, relative: str, *, worker_limit: int = 6,
                import_plan: bool = True, repo_root=None, run_id: str = "run-1"):
    """A run at `repo / relative`, so a test can choose the run directory's own
    spelling -- which is precisely what ends up inside the repository-relative
    path `publish_worker_result` returns and Task 10 must be able to cite.

    `make_run` hardcodes `docs/superpowers/runs/run-1`, which is the layout and
    is exactly the thing these tests must be able to vary.
    """
    run_dir = Path(repo) / relative
    run_dir.mkdir(parents=True)
    plan = write_phase_plan(run_dir, three_disjoint_tasks())
    state.initialize_run(
        run_dir, run_id=run_id, base_commit=git(repo, "rev-parse", "HEAD"),
        target_branch="target", worker_limit=worker_limit,
        repo_root=repo_root if repo_root is not None else str(repo))
    if import_plan:
        state.import_phase_plan(run_dir, phase_plan=plan)
    return run_dir


def module_function_code(name: str) -> str:
    """One module-level function's EXECUTABLE source: no docstring, no comments.

    `module_function_source` returns the text, and the text of a function that
    explains at length why it does NOT re-spell a grammar contains the grammar
    it is refusing to re-spell. A discriminator that fires on the function's
    own argument against the defect discriminates nothing -- the ruling
    `CANONICAL_DIAGNOSIS` already records, arriving through source text rather
    than through a diagnosis string. `ast.unparse` drops comments too, so what
    is left is exactly what runs.
    """
    source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
        encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]
            return "\n".join(ast.unparse(statement) for statement in body)
    raise AssertionError(f"pipeline_auto_state has no function {name!r}")


class Task9ProducesBlockTests(unittest.TestCase):
    """The brief's Produces block is a claim to CHECK, not a list to implement.

    Two of its names are new; every other name the Step-3 code touches already
    exists, and a module-level redefinition of any of them rebinds the global
    for every existing caller. Task 6 found three such names and Task 7 two
    more, so this is the fifth task to have to run the check.
    """

    def test_the_names_this_task_defines_are_exactly_these_five(self):
        """The name this test used to carry claimed "only" and "two" and the
        body asserted neither -- two `callable` checks that pass for any
        module defining those two names, however many others it also defines.
        The task's own section in fact defines FIVE module-level names, and a
        sixth appearing later is a rebinding nobody declared.

        Located by the section banner rather than by a diff against a parent
        commit, so the claim survives a rebase and reads as what it is: what
        lives under `P04 Task 9:` in the module.
        """
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        banner = next(
            index for index, line in enumerate(source.splitlines(), start=1)
            if line.startswith("# P04 Task 9:"))
        tree = ast.parse(source)
        defined = sorted(
            name for node in tree.body if node.lineno > banner
            for name in module_bindings([node]))
        self.assertEqual(defined, [
            "AGENT_OUTPUT_DIRNAME",
            "_citable_repo_relative",
            "_published_result_bytes",
            "publish_worker_result",
            "worker_result_path",
        ])
        #: Three of the five are public and exactly two of those three are
        #: CALLABLE: the third, `AGENT_OUTPUT_DIRNAME`, is the cross-phase
        #: constant P06 and P07 cite. "The two new names" was always a claim
        #: about the entry points and never about the module surface.
        self.assertEqual(
            [name for name in defined if not name.startswith("_")],
            ["AGENT_OUTPUT_DIRNAME", "publish_worker_result",
             "worker_result_path"])
        self.assertEqual(
            [name for name in defined
             if not name.startswith("_") and callable(getattr(state, name))],
            ["publish_worker_result", "worker_result_path"])
        self.assertTrue(callable(state.worker_result_path))
        self.assertTrue(callable(state.publish_worker_result))

    def test_no_module_level_name_is_bound_twice(self):
        """The mechanical form. `Task6ModuleBoundaryTests` asserts this for the
        whole module; repeating it here is what makes a Task 9 rebinding fail
        in Task 9's own sub-suite rather than only in somebody else's."""
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        counts = module_bindings(ast.parse(source).body)
        self.assertEqual(
            sorted(name for name, count in counts.items() if count > 1), [])

    def test_the_attempt_grammar_is_still_task_4s_single_conversion_point(self):
        """The brief's Step-3 code spells the attempt as `attempt-{attempt}.md`,
        which is a SECOND spelling of a conversion `_attempt_token` documents
        itself as the single point of -- and the two disagree on every input:
        `attempt-1` against `attempt-001`. The plan pins `attempt-%03d` for
        'every tracker cell, checkpoint marker, and result document'.
        """
        for name in ("worker_result_path", "publish_worker_result"):
            with self.subTest(function=name):
                self.assertNotIn("attempt-", module_function_code(name))
        self.assertEqual(state._attempt_token(1), "attempt-001")
        self.assertTrue(
            state.worker_result_path(
                "/run", task_id="T1", attempt=1).name.startswith(
                    state._attempt_token(1)))

    def test_the_owner_grammar_is_not_respelled_by_this_task(self):
        """P06 reads the owner line through P04's own `_OWNER_LINE_PREFIX`. A
        second spelling here would be the two-answers defect `_owner_line` was
        written to prevent, and it would silently change the
        reviewer-independence check in another phase."""
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        self.assertEqual(source.count('_OWNER_LINE_PREFIX = '), 1)
        for name in ("worker_result_path", "publish_worker_result"):
            with self.subTest(function=name):
                self.assertNotIn("Owner", module_function_code(name))

    def test_the_directory_name_has_exactly_one_spelling_in_the_module(self):
        """P06 and P07 both name this tree. A literal written at the use site
        is a second definition of a cross-phase contract."""
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        self.assertEqual(state.AGENT_OUTPUT_DIRNAME, "agent-output")
        self.assertEqual(source.count('"agent-output"'), 1)
        self.assertEqual(source.count("'agent-output'"), 0)
        self.assertNotIn('"results"', source)

    def test_the_path_segment_grammar_is_p03s_owner_grammar_aliased(self):
        """`_OWNER` is this module's pinned 'identifier that becomes a name on
        a filesystem' grammar -- bounded, no trailing dot, and no `/`, `:`,
        `@` or `+`. `_validate_assignment` already states that argument for the
        owner; a task id that becomes a DIRECTORY name raises exactly it. An
        alias keeps one definition; a second `_CharClass` would be two."""
        self.assertIs(state._PATH_SEGMENT, state._OWNER)

    def test_the_module_still_imports_nothing_outside_the_twelve(self):
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {
            "__future__", "contextlib", "copy", "errno", "fcntl", "hashlib",
            "json", "msvcrt", "os", "pathlib", "time", "types"})
        self.assertNotIn("re", imported)
        self.assertNotIn("subprocess", imported)
        self.assertNotIn("zlib", imported)
        self.assertNotIn("tempfile", imported)


class WorkerResultPathTests(unittest.TestCase):
    """The path is an IDENTITY, so it is pinned shape by shape."""

    def test_the_shape_is_agent_output_task_attempt(self):
        path = state.worker_result_path("/runs/r", task_id="T1", attempt=7)
        self.assertEqual(path.name, "attempt-007.md")
        self.assertEqual(path.parent.name, "T1")
        self.assertEqual(path.parent.parent.name, state.AGENT_OUTPUT_DIRNAME)
        self.assertEqual(path.parent.parent.parent, Path("/runs/r"))

    def test_the_attempt_is_rendered_by_the_single_conversion_point(self):
        """`attempt-1.md` and `attempt-001.md` are one attempt with two
        identities, in a record whose identity is the sha256 of its bytes."""
        for attempt in (1, 2, 12, 999999999):
            with self.subTest(attempt=attempt):
                self.assertEqual(
                    state.worker_result_path(
                        "/r", task_id="T1", attempt=attempt).name,
                    f"{state._attempt_token(attempt)}.md")

    def test_result_path_is_attempt_scoped(self):
        """The brief's own test: a resumed task's second attempt is a second
        immutable record, not an overwrite of the first."""
        first = state.worker_result_path("/r", task_id="T1", attempt=1)
        second = state.worker_result_path("/r", task_id="T1", attempt=2)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, second.parent)

    def test_the_map_from_a_task_id_to_a_directory_is_injective(self):
        """THE BRIEF'S `task_id.replace("/", "-")` IS NOT. `T/1` and `T-1` are
        two tasks and one directory under it, so the second task to publish is
        refused as 'conflicting evidence' about the first -- or, if the two
        rendered the same bytes, accepted as an idempotent replay of a result
        it never wrote. A mangling is the wrong answer for an identity; a
        refusal is the right one, and the screen below is what makes it one."""
        seen = {}
        for task_id in ("T1", "T-1", "T.1", "T_1", "t1", "T11"):
            path = state.worker_result_path("/r", task_id=task_id, attempt=1)
            self.assertNotIn(path, seen, f"{task_id} collides with {seen.get(path)}")
            seen[path] = task_id
        with self.assertRaises(state.TrackerValidationError):
            state.worker_result_path("/r", task_id="T/1", attempt=1)

    def test_the_run_directory_is_never_coerced_from_a_repr(self):
        for run_dir in ("/r", Path("/r")):
            with self.subTest(run_dir=run_dir):
                self.assertEqual(
                    state.worker_result_path(run_dir, task_id="T1", attempt=1),
                    Path("/r") / state.AGENT_OUTPUT_DIRNAME / "T1"
                    / "attempt-001.md")


#: THE ARGUMENT CORPUS, DERIVED FROM THE CALL TREE rather than from a fixture.
#: `worker_result_path` reaches exactly three screens -- `_run_path` over
#: `run_dir`, an `isinstance` plus `_PATH_SEGMENT` over `task_id`, and
#: `_attempt_token` over `attempt` -- so the corpus is the union of what each
#: of those three can be handed. Every path-shaped argument carries a NUL and a
#: lone surrogate, the two values that leave the exception family by a route
#: `pathlib` hides.
RUN_DIR_CASES = (
    ("str", "/runs/r", True),
    ("path", Path("/runs/r"), True),
    ("none", None, False),
    ("int", 5, False),
    ("bytes", b"/runs/r", False),
    ("list", ["/runs/r"], False),
    #: A NUL and a lone surrogate are LEGAL to spell as a `Path` and illegal to
    #: resolve. `worker_result_path` builds a name and opens nothing, so it
    #: answers; `publish_worker_result` is where they have to be refused.
    ("nul", "/runs/r\x00x", True),
    ("surrogate", "/runs/r\ud800", True),
)

TASK_ID_CASES = (
    ("plain", "T1", True),
    ("dotted", "T.1", True),
    ("underscored", "T_1", True),
    ("hyphenated", "T-1", True),
    ("at-the-length-bound", "a" * 64, True),
    ("past-the-length-bound", "a" * 65, False),
    ("slash", "a/b", False),
    ("leading-slash", "/abs", False),
    ("colon", "T:1", False),
    ("at", "T@1", False),
    ("plus", "T+1", False),
    ("trailing-dot", "T1.", False),
    ("dot", ".", False),
    ("dotdot", "..", False),
    ("empty", "", False),
    ("leading-hyphen", "-T1", False),
    ("nul", "T\x001", False),
    ("surrogate", "T\ud800", False),
    ("arabic-indic-digit", "T١", False),
    ("space", "T 1", False),
    ("newline", "T\n1", False),
    ("none", None, False),
    ("int", 1, False),
    ("bytes", b"T1", False),
    ("path", Path("T1"), False),
)

ATTEMPT_CASES = (
    ("one", 1, True),
    ("two", 2, True),
    ("at-the-ceiling-minus-one", 999999999, True),
    ("at-the-ceiling", 1000000000, False),
    ("zero", 0, False),
    ("negative", -1, False),
    ("true", True, False),
    ("false", False, False),
    ("float", 1.0, False),
    ("str", "1", False),
    ("token", "attempt-001", False),
    ("none", None, False),
)


class WorkerResultPathTotalityTests(unittest.TestCase):
    """Every argument the call tree admits, answered or refused IN FAMILY.

    The claim is totality, so the case list comes from the three screens the
    function reaches and not from the shapes that happened to break it.
    """

    def _answer(self, run_dir, task_id, attempt):
        try:
            return ("path", state.worker_result_path(
                run_dir, task_id=task_id, attempt=attempt))
        except state.TrackerError as exc:
            return ("refused", type(exc).__name__)

    def test_every_run_directory_shape_is_answered_or_refused_in_family(self):
        for label, run_dir, accepted in RUN_DIR_CASES:
            with self.subTest(run_dir=label):
                kind, value = self._answer(run_dir, "T1", 1)
                self.assertEqual(kind, "path" if accepted else "refused")
                if accepted:
                    self.assertEqual(value.name, "attempt-001.md")

    def test_every_task_id_shape_is_answered_or_refused_in_family(self):
        for label, task_id, accepted in TASK_ID_CASES:
            with self.subTest(task_id=label):
                kind, value = self._answer("/r", task_id, 1)
                self.assertEqual(kind, "path" if accepted else "refused")
                if accepted:
                    #: One segment, spelled exactly as it was handed in. A
                    #: mangling would make the map non-injective.
                    self.assertEqual(value.parent.name, task_id)
                    self.assertEqual(
                        value.parent.parent.name, state.AGENT_OUTPUT_DIRNAME)

    def test_every_attempt_shape_is_answered_or_refused_in_family(self):
        for label, attempt, accepted in ATTEMPT_CASES:
            with self.subTest(attempt=label):
                kind, value = self._answer("/r", "T1", attempt)
                self.assertEqual(kind, "path" if accepted else "refused")
                if accepted:
                    self.assertEqual(
                        value.name, f"{state._attempt_token(attempt)}.md")

    def test_the_cross_product_never_leaves_the_exception_family(self):
        """The three screens compose, and a screen hidden behind a short
        circuit is a screen nobody runs. 8 x 25 x 12 = 2400 calls, of which
        4 x 5 x 3 = 60 are the ones every screen admits."""
        accepted = 0
        for _, run_dir, run_ok in RUN_DIR_CASES:
            for _, task_id, task_ok in TASK_ID_CASES:
                for _, attempt, attempt_ok in ATTEMPT_CASES:
                    kind, _value = self._answer(run_dir, task_id, attempt)
                    expected = run_ok and task_ok and attempt_ok
                    self.assertEqual(kind, "path" if expected else "refused")
                    accepted += expected
        self.assertEqual(accepted, 4 * 5 * 3)

    def test_a_bool_attempt_is_refused_although_it_is_an_int(self):
        """`isinstance(True, int)` is true and `True` renders as `attempt-001`,
        so a controller that lost an attempt number and passed a flag would
        publish attempt one under a name nothing reserved."""
        with self.assertRaises(state.TrackerValidationError):
            state.worker_result_path("/r", task_id="T1", attempt=True)


#: AXIS ONE OF THE PUBLICATION CROSS-PRODUCT: THE SPELLINGS OF A RUN
#: DIRECTORY, derived from the CALL TREE and not from a fixture.
#: `publish_worker_result` puts `run_dir` through exactly two screens --
#: `_run_path`, which admits `str` and `Path` and refuses everything else
#: inside the family, and `home.resolve()`, which is where a NUL and a lone
#: surrogate stop -- so the corpus is the union of what those two can be
#: handed, which is the same union `RUN_DIR_CASES` states for
#: `worker_result_path`.
#:
#: IT EXISTS BECAUSE THE `str` CELL WAS MISSING AND `str` WAS THE ONLY SHAPE
#: THAT ESCAPED. `publish_worker_result` normalised `run_dir` into `home` and
#: then handed the RAW value to `validate_run`, which deliberately does not
#: coerce; `None`, an `int`, `bytes` and a `list` were all stopped earlier by
#: `_run_path`, so the one shape that reached the uncoerced call was the one
#: shape `RUN_DIR_CASES` pins as legal and a worker subprocess is likeliest to
#: hold. It raised `TypeError`, outside `TrackerError`, from a function whose
#: whole contract is that a refusal is in-family and read-only.
#:
#: Each entry is (label, build, refusal), where `refusal` is `None` for a
#: spelling that must be ACCEPTED and otherwise the exception class and a
#: fragment of the diagnosis. A family assertion alone would let any refusal
#: stand in for any other -- Task 8's NUL is the precedent.
def publication_run_dir_cases(run_dir) -> tuple:
    spelling = str(run_dir)
    not_a_path = (state.QuorumError, "not a path")
    unresolvable = (state.TrackerValidationError, "cannot be resolved")
    return (
        ("str", spelling, None),
        ("path", Path(spelling), None),
        ("none", None, not_a_path),
        ("int", 5, not_a_path),
        ("bytes", spelling.encode("utf-8"), not_a_path),
        ("list", [spelling], not_a_path),
        ("nul", spelling + "\x00x", unresolvable),
        ("surrogate", spelling + "\ud800", unresolvable),
    )


#: AXIS TWO: the three relations a publication can stand in to its own name.
#: `publish_worker_result` branches on exactly these -- nothing published, the
#: same bytes published, other bytes published -- so a run-directory spelling
#: has to be answered the same way on all three, and a `str` that works only
#: when the record happens to be absent is not fixed.
PUBLICATION_RELATIONS = ("fresh", "replay", "conflict")


class PublishedRunDirectorySpellingTests(TempDirTestCase):
    """AXIS ONE x AXIS TWO, in family on every cell.

    `worker_result_path` already carries this claim and
    `publish_worker_result` did not, which is how one spelling of one
    argument left the exception family unnoticed through a whole task.
    """

    def setUp(self) -> None:
        super().setUp()
        self.repo, self.run_dir, _ = make_run(
            self.tmp, three_disjoint_tasks(), worker_limit=6)
        self.cases = publication_run_dir_cases(self.run_dir)

    def _prepare(self, task_id: str, relation: str):
        """The name, as the relation requires it, and its `lstat` snapshot."""
        requested = worker_result(task_id=task_id)
        rendered = state.render_worker_result(requested).encode("utf-8")
        path = state.worker_result_path(
            self.run_dir, task_id=task_id, attempt=1)
        if relation != "fresh":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                rendered if relation == "replay" else b"another answer\n")
        return requested, rendered, path

    def test_every_run_directory_spelling_crossed_with_every_relation(self):
        cells = 0
        for index, (label, run_dir, refusal) in enumerate(self.cases):
            for offset, relation in enumerate(PUBLICATION_RELATIONS):
                task_id = f"s{index:02d}{offset}"
                requested, rendered, path = self._prepare(task_id, relation)
                before = name_state(path)
                with self.subTest(run_dir=label, relation=relation):
                    cells += 1
                    self._assert_cell(
                        run_dir, refusal, relation, requested, rendered, path,
                        before)
        self.assertEqual(
            tuple(label for label, _value, _refusal in self.cases),
            ("str", "path", "none", "int", "bytes", "list", "nul",
             "surrogate"))
        self.assertEqual(cells, 8 * 3)
        self.assertEqual(cells, 24)

    def _assert_cell(self, run_dir, refusal, relation, requested, rendered,
                     path, before):
        if refusal is not None:
            error, diagnosis = refusal
            with publication_deadline(10, "publish_worker_result"):
                with self.assertRaises(error) as caught:
                    state.publish_worker_result(run_dir, result=requested)
            #: THE DIAGNOSIS, not merely the family. `QuorumError` is also
            #: what a malformed qid raises.
            self.assertIn(diagnosis, str(caught.exception))
            self.assertEqual(name_state(path), before)
            return
        if relation == "conflict":
            with publication_deadline(10, "publish_worker_result"):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.publish_worker_result(run_dir, result=requested)
            self.assertIn("conflicting immutable result", str(caught.exception))
            self.assertEqual(name_state(path), before)
            return
        with publication_deadline(10, "publish_worker_result"):
            relative = state.publish_worker_result(run_dir, result=requested)
        self.assertEqual((self.repo / relative).read_bytes(), rendered)
        if relation == "replay":
            #: Byte-identical republication is inert, inode included, however
            #: the run directory was spelled.
            self.assertEqual(name_state(path), before)

    def test_a_str_run_directory_reaches_validate_run_as_a_path(self):
        """THE REGRESSION, on its own and named. `validate_run`'s first
        statement is `run_dir / "progress.md"`, so a `str` reaching it
        uncoerced raises `TypeError` -- and `TypeError` is not a
        `TrackerError`, so the controller handler this whole phase is built
        around does not catch it."""
        self.assertEqual(
            state.publish_worker_result(
                str(self.run_dir), result=worker_result()),
            state.publish_worker_result(self.run_dir, result=worker_result()))

    def test_a_str_run_directory_still_reports_a_foreign_tracker_in_family(self):
        """The coercion must not swallow what `validate_run` is FOR. A `str`
        run directory whose tracker is not ours takes the foreign-schema stop,
        which is the diagnosis the raw-argument crash used to hide."""
        foreign = self.repo / "docs" / "superpowers" / "runs" / "foreign"
        foreign.mkdir(parents=True)
        (foreign / "progress.md").write_text(
            "<!-- pipeline-run/v2 -->\n", encoding="utf-8")
        with self.assertRaises(state.ForeignSchemaError):
            state.publish_worker_result(str(foreign), result=worker_result())
        self.assertEqual(
            sorted(entry.name for entry in foreign.iterdir()), ["progress.md"])


#: EVERY PUBLIC ENTRY POINT THAT TAKES A RUN DIRECTORY, listed from the
#: module's own AST rather than by hand, so a later phase adding one is
#: measured here instead of being remembered.
#:
#: `validate_run` and `locked_tracker_update` are deliberately NOT on it and
#: are named as exclusions: both are typed `Path` and both argue the
#: no-coercion rule in their own docstrings -- "coercing here would also have
#: hidden a caller that had lost track of what it was holding". The rule is
#: that the ENTRY POINTS normalise and the contract functions do not, and the
#: defect was five entry points that did not.
RUN_DIR_ENTRY_POINTS = (
    "initialize_run", "import_phase_plan", "reserve_task", "resume_task",
    "publish_worker_result",
)
RUN_DIR_CONTRACT_FUNCTIONS = ("validate_run", "locked_tracker_update")


class RunDirectoryCoercionSweepTests(TempDirTestCase):
    """The pattern, not the instance.

    `publish_worker_result` and `reserve_task` had the same shape, and the
    review's own note is the reason this class exists rather than two fixes:
    "the two are one line each and leaving one of them is how the pattern
    survives". So the sweep is mechanical and it is a test.
    """

    def setUp(self) -> None:
        super().setUp()
        self.repo, self.run_dir, self.plan = make_run(
            self.tmp, three_disjoint_tasks(), worker_limit=6)

    def test_every_public_entry_point_taking_a_run_directory_is_listed(self):
        """The roster is checked against the module, so a sixth entry point
        added by a later phase fails here rather than silently escaping the
        sweep below."""
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        found = []
        for node in ast.parse(source).body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            names = [arg.arg for arg in node.args.args]
            if names[:1] == ["run_dir"]:
                found.append(node.name)
        self.assertEqual(
            sorted(found),
            sorted(RUN_DIR_ENTRY_POINTS + RUN_DIR_CONTRACT_FUNCTIONS
                   + ("quorum_events", "quorum_budget", "current_floor",
                      "quorum_tracker_rows", "open_quorum",
                      "record_brain_response", "quorum_needs_redispatch",
                      "classify_quorum", "finalize_quorum",
                      "resolve_evidence", "worker_result_path")))

    def test_every_entry_point_normalises_its_run_directory(self):
        """The mechanical half: each of the five puts the argument through
        `_run_path` somewhere in its body."""
        for name in RUN_DIR_ENTRY_POINTS:
            with self.subTest(function=name):
                self.assertIn("_run_path(run_dir)",
                              module_function_code(name))

    def test_no_entry_point_hands_a_raw_run_directory_to_a_path_typed_callee(self):
        """THE DEFECT, STATED STRUCTURALLY. Normalising and then passing the
        raw name anyway is what `publish_worker_result` did -- `home =
        _run_path(run_dir)` two lines above `validate_run(run_dir)` -- so
        "it calls `_run_path` somewhere" is not the property that matters.

        The sinks are read off the module: a function whose FIRST parameter is
        annotated `Path` has declared that it will not coerce, and handing one
        a `str` is a `TypeError` waiting at its first `/`. The list is
        therefore derived, so a later phase adding another `Path`-typed
        helper is covered without anybody remembering to add it here.
        """
        source = (SKILL_DIR / "scripts" / "pipeline_auto_state.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        sinks = {
            node.name for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.args.args
            and isinstance(node.args.args[0].annotation, ast.Name)
            and node.args.args[0].annotation.id == "Path"}
        #: The two the defect actually reached, named so a refactor that
        #: dropped every annotation would empty `sinks` and pass vacuously.
        self.assertLessEqual({"validate_run", "classify_filesystem"}, sinks)
        offenders = []
        for node in tree.body:
            if (not isinstance(node, ast.FunctionDef)
                    or node.name not in RUN_DIR_ENTRY_POINTS):
                continue
            #: A REBINDING IS WHAT MAKES THE NAME SAFE, so the line it happens
            #: on is the boundary: after `run_dir = _run_path(run_dir)` the
            #: name IS the normalised value and passing it on is correct.
            #: Before it -- or with no rebinding at all, which is
            #: `publish_worker_result`, where the normalised value is called
            #: `home` -- the name is still whatever the caller handed in.
            rebound = min(
                (inner.lineno for inner in ast.walk(node)
                 if isinstance(inner, ast.Assign)
                 and any(isinstance(target, ast.Name)
                         and target.id == "run_dir"
                         for target in inner.targets)),
                default=None)
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id in sinks
                        and (rebound is None or inner.lineno <= rebound)
                        and any(isinstance(argument, ast.Name)
                                and argument.id == "run_dir"
                                for argument in inner.args)):
                    offenders.append(f"{node.name} -> {inner.func.id}")
        self.assertEqual(offenders, [])

    def test_the_two_contract_functions_deliberately_do_not(self):
        """The exclusion, asserted rather than assumed. Coercing here is what
        would hide the caller that lost track of what it was holding."""
        for name in RUN_DIR_CONTRACT_FUNCTIONS:
            with self.subTest(function=name):
                self.assertNotIn("_run_path", module_function_code(name))

    def test_no_entry_point_leaves_the_family_on_any_run_directory_shape(self):
        """The behavioural half, over the same shapes `_run_path` screens.
        Every call is made with otherwise-valid arguments, so the only thing
        that can be wrong is the run directory."""
        calls = {
            "initialize_run": lambda value: state.initialize_run(
                value, run_id="run-2", base_commit=git(self.repo, "rev-parse", "HEAD"),
                target_branch="target", worker_limit=4, repo_root=str(self.repo)),
            "import_phase_plan": lambda value: state.import_phase_plan(
                value, phase_plan=str(self.plan)),
            "reserve_task": lambda value: state.reserve_task(
                value, task_id="T1", owner="impl-1", attempt=1),
            "resume_task": lambda value: state.resume_task(
                value, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref="H-1"),
            "publish_worker_result": lambda value: state.publish_worker_result(
                value, result=worker_result()),
        }
        self.assertEqual(sorted(calls), sorted(RUN_DIR_ENTRY_POINTS))
        shapes = (None, 5, b"/runs/r", ["/runs/r"], str(self.run_dir))
        for name in RUN_DIR_ENTRY_POINTS:
            for shape in shapes:
                with self.subTest(function=name, shape=type(shape).__name__):
                    try:
                        calls[name](shape)
                    except state.TrackerError:
                        pass
                    except Exception as exc:  # noqa: BLE001 - the whole point
                        self.fail(
                            f"{name} left TrackerError on a "
                            f"{type(shape).__name__} run_dir: "
                            f"{type(exc).__name__}: {exc}")


class PublishWorkerResultTests(TempDirTestCase):
    """The brief's six, kept verbatim in intent."""

    def setUp(self) -> None:
        super().setUp()
        self.repo, self.run_dir, _ = make_run(
            self.tmp, three_disjoint_tasks(), worker_limit=6)

    def test_writes_a_canonical_immutable_file(self):
        relative = state.publish_worker_result(
            self.run_dir, result=worker_result())
        self.assertFalse(Path(relative).is_absolute())
        self.assertIn(state.AGENT_OUTPUT_DIRNAME, relative)
        published = self.repo / relative
        self.assertTrue(published.is_file())
        self.assertEqual(
            state.parse_worker_result(published.read_text(encoding="utf-8")),
            worker_result())

    def test_content_digest_matches_what_publish_immutable_reported(self):
        relative = state.publish_worker_result(
            self.run_dir, result=worker_result())
        expected = hashlib.sha256(
            (self.repo / relative).read_bytes()).hexdigest()
        rendered = state.render_worker_result(worker_result())
        self.assertEqual(
            hashlib.sha256(rendered.encode("utf-8")).hexdigest(), expected)

    def test_is_idempotent_for_identical_content(self):
        first = state.publish_worker_result(self.run_dir, result=worker_result())
        before = name_state(self.repo / first)
        second = state.publish_worker_result(self.run_dir, result=worker_result())
        self.assertEqual(second, first)
        #: The INODE is compared, not only the bytes. An unlink-and-recreate
        #: satisfies every content check while breaking each hard link an audit
        #: trail holds to the record.
        self.assertEqual(name_state(self.repo / first), before)

    def test_a_replay_into_a_directory_that_has_become_read_only_succeeds(self):
        """A REPLAY READS; IT DOES NOT WRITE, and the early return is what
        makes that true rather than incidental.

        `_link_publish` states the requirement itself: "a controller that
        crashed between the link and recording that it had linked must find its
        own work on the retry, not a refusal it cannot act on". Falling through
        to `publish_immutable` on a replay looks harmless -- it is inert for
        identical bytes -- but it first CREATES a temporary file in the
        record's own directory, so the retry needs write permission on a
        directory the publication is not going to change. This is the one
        observable that separates the early return from its removal, and
        without it that mutant is equivalent.
        """
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root writes into a read-only directory")
        first = state.publish_worker_result(self.run_dir, result=worker_result())
        directory = (self.repo / first).parent
        before = name_state(self.repo / first)
        directory.chmod(0o555)
        self.addCleanup(directory.chmod, 0o755)
        self.assertEqual(
            state.publish_worker_result(self.run_dir, result=worker_result()),
            first)
        self.assertEqual(name_state(self.repo / first), before)

    def test_refuses_to_overwrite_conflicting_content(self):
        relative = state.publish_worker_result(
            self.run_dir, result=worker_result())
        before = name_state(self.repo / relative)
        with self.assertRaises(state.TrackerValidationError):
            state.publish_worker_result(
                self.run_dir, result=worker_result(concerns="changed my mind"))
        self.assertEqual(name_state(self.repo / relative), before)

    def test_validates_before_writing_anything(self):
        with self.assertRaises(state.TrackerValidationError):
            state.publish_worker_result(
                self.run_dir,
                result=quorum_result("NEEDS_CONTEXT", question_record="-"))
        self.assertFalse(
            (self.run_dir / state.AGENT_OUTPUT_DIRNAME).exists())

    def test_a_second_attempt_is_a_second_record_not_an_overwrite(self):
        first = state.publish_worker_result(
            self.run_dir, result=worker_result(attempt=1))
        second = state.publish_worker_result(
            self.run_dir, result=worker_result(attempt=2))
        self.assertNotEqual(first, second)
        self.assertTrue((self.repo / first).is_file())
        self.assertTrue((self.repo / second).is_file())

    def test_a_result_naming_a_task_id_no_directory_can_hold_is_refused(self):
        """`_TOKEN` admits `/`, `:`, `@` and `+`, so a plan may legally declare
        a task id that cannot be one directory name. The refusal is loud and
        happens before any write."""
        with self.assertRaises(state.TrackerValidationError):
            state.publish_worker_result(
                self.run_dir, result=worker_result(task_id="T/1"))
        self.assertFalse((self.run_dir / state.AGENT_OUTPUT_DIRNAME).exists())

    def test_a_run_whose_tracker_is_not_ours_publishes_nothing(self):
        """A read-only stop: an immutable record must not appear inside a
        directory this skill has not established is its own."""
        foreign = self.repo / "docs" / "superpowers" / "runs" / "foreign"
        foreign.mkdir(parents=True)
        (foreign / "progress.md").write_text(
            "<!-- pipeline-run/v2 -->\n", encoding="utf-8")
        with self.assertRaises(state.ForeignSchemaError):
            state.publish_worker_result(foreign, result=worker_result())
        self.assertEqual(
            sorted(entry.name for entry in foreign.iterdir()), ["progress.md"])


#: AXIS ONE OF THE CROSS-PRODUCT: every shape a name under `agent-output/` can
#: have when publication reaches it. It is derived from the SCREEN, not from a
#: list of mutants: `_require_regular_file` splits every name into "absent",
#: "a regular file" and "corruption", and each of those three has more than one
#: spelling on a POSIX filesystem. `is_file()` alone answers False for four of
#: them and one of the four -- the FIFO -- does not fail an open, it blocks it.
#:
#: Each entry is (label, class, build). `build` is handed the target path and
#: the two candidate documents' bytes.
#:
#: THE ROSTER IS WRITTEN OUT, and that is the assertion. `assertEqual(cells,
#: len(self.shapes) * 2)` was a tautology -- `cells` is incremented once per
#: iteration of a loop that runs exactly that many times -- so the FIFO shape
#: and then four more could be deleted from the builder below and the suite
#: stayed green. A count that is a measurement of the corpus cannot pin the
#: corpus; a literal list of the labels can, and it fails by NAMING whichever
#: shape went missing.
PUBLICATION_SHAPE_LABELS = (
    "absent", "identical-regular", "the-other-result", "foreign-bytes",
    "empty-regular", "truncated", "one-byte-longer", "invalid-utf8",
    "symlink-to-identical", "symlink-to-differing", "directory",
    "nonempty-directory", "dangling-symlink", "symlink-loop",
    "parent-is-a-file", "fifo", "unreadable-regular",
)


def expected_publication_shape_labels() -> tuple:
    """The roster, minus whichever shapes THIS platform cannot build.

    The two predicates are the only things allowed to vary the corpus, and
    naming them here is what lets the count below be a literal instead of a
    restatement of the loop bound.
    """
    withheld = set()
    if not hasattr(os, "mkfifo"):  # pragma: no cover - POSIX only
        withheld.add("fifo")
    if hasattr(os, "geteuid") and os.geteuid() == 0:  # pragma: no cover
        withheld.add("unreadable-regular")
    return tuple(label for label in PUBLICATION_SHAPE_LABELS
                 if label not in withheld)


def _publication_shapes(euid_is_root: bool) -> tuple:
    def regular(payload):
        def build(path, first, second):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload(first, second))
        return build

    def link_to(payload):
        def build(path, first, second):
            path.parent.mkdir(parents=True, exist_ok=True)
            target = path.parent / "elsewhere.md"
            target.write_bytes(payload(first, second))
            path.symlink_to(target)
        return build

    def directory(entries):
        def build(path, first, second):
            path.mkdir(parents=True)
            for name in entries:
                (path / name).write_text("x", encoding="utf-8")
        return build

    def dangling(path, first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(path.parent / "nowhere.md")

    def loop(path, first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        other = path.parent / "other.md"
        path.symlink_to(other)
        other.symlink_to(path)

    def fifo(path, first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)

    def unreadable(path, first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(first)
        path.chmod(0o000)

    def parent_is_a_file(path, first, second):
        path.parent.parent.mkdir(parents=True, exist_ok=True)
        path.parent.write_text("not a directory\n", encoding="utf-8")

    shapes = [
        ("absent", "absent", lambda path, first, second: None),
        ("identical-regular", "content", regular(lambda a, b: a)),
        ("the-other-result", "content", regular(lambda a, b: b)),
        ("foreign-bytes", "content", regular(lambda a, b: b"nothing to do\n")),
        ("empty-regular", "content", regular(lambda a, b: b"")),
        ("truncated", "content", regular(lambda a, b: a[:-1])),
        ("one-byte-longer", "content", regular(lambda a, b: a + b"\n")),
        #: A `read_text(encoding="utf-8")` pre-check raises `UnicodeDecodeError`
        #: here, which is not a `TrackerError`, so the comparison is made on
        #: BYTES.
        ("invalid-utf8", "content", regular(lambda a, b: b"\xff\xfe\x00bad")),
        ("symlink-to-identical", "content", link_to(lambda a, b: a)),
        ("symlink-to-differing", "content", link_to(lambda a, b: b)),
        ("directory", "corrupt", directory(())),
        ("nonempty-directory", "corrupt", directory(("inside.md",))),
        ("dangling-symlink", "corrupt", dangling),
        ("symlink-loop", "corrupt", loop),
        ("parent-is-a-file", "parent", parent_is_a_file),
    ]
    if hasattr(os, "mkfifo"):
        shapes.append(("fifo", "corrupt", fifo))
    if not euid_is_root:
        shapes.append(("unreadable-regular", "unreadable", unreadable))
    return tuple(shapes)


class PublishedNameCrossProductTests(TempDirTestCase):
    """AXIS ONE x AXIS TWO: every shape a name can have, crossed with the two
    relations a request can stand in to it -- a replay of what is there, and
    conflicting evidence about it.

    A corpus built from known mutants proves only that those mutants die. This
    one is generated from the structure being screened: the three answers
    `_require_regular_file` can give, spelled out over the filesystem, crossed
    with the two answers the byte comparison can give.
    """

    def setUp(self) -> None:
        super().setUp()
        self.repo, self.run_dir, _ = make_run(
            self.tmp, three_disjoint_tasks(), worker_limit=6)
        self.shapes = _publication_shapes(
            hasattr(os, "geteuid") and os.geteuid() == 0)

    def test_the_corpus_is_the_roster_and_not_its_own_length(self):
        """The count that looked like a pin was `len(self.shapes) * 2`, which
        is the loop bound restated. The roster is the pin."""
        self.assertEqual(
            tuple(label for label, _kind, _build in self.shapes),
            expected_publication_shape_labels())
        self.assertEqual(len(PUBLICATION_SHAPE_LABELS), 17)

    def test_every_shape_crossed_with_every_request(self):
        cells = 0
        for index, (label, kind, build) in enumerate(self.shapes):
            for offset, concerns in enumerate(("-", "changed my mind")):
                task_id = f"c{index:02d}{offset}"
                first = state.render_worker_result(
                    worker_result(task_id=task_id)).encode("utf-8")
                second = state.render_worker_result(
                    worker_result(task_id=task_id,
                                  concerns="changed my mind")).encode("utf-8")
                requested = worker_result(task_id=task_id, concerns=concerns)
                rendered = state.render_worker_result(requested).encode("utf-8")
                path = state.worker_result_path(
                    self.run_dir, task_id=task_id, attempt=1)
                build(path, first, second)
                before = name_state(path)
                #: THE PARENT IS SNAPSHOTTED TOO, because for the
                #: `parent-is-a-file` shape `name_state(path)` is `('absent',)`
                #: on both sides -- `lstat` raises `NotADirectoryError` when a
                #: parent component is a regular file -- so those two cells
                #: compared nothing and would have passed had the refusal
                #: clobbered the parent file it walked through.
                before_parent = name_state(path.parent)
                with self.subTest(shape=label, concerns=concerns):
                    cells += 1
                    self._assert_cell(kind, path, requested, rendered, before,
                                      before_parent)
        #: THE LITERAL COUNT, guarded by the two platform predicates that are
        #: allowed to vary it. On a POSIX machine that is not root it is 34.
        self.assertEqual(
            tuple(label for label, _kind, _build in self.shapes),
            expected_publication_shape_labels())
        self.assertEqual(cells, 2 * len(expected_publication_shape_labels()))
        if len(self.shapes) == len(PUBLICATION_SHAPE_LABELS):
            self.assertEqual(cells, 34)

    def _assert_cell(self, kind, path, requested, rendered, before,
                     before_parent):
        expected = kind
        if kind == "content":
            #: The bytes THE NAME RESOLVES TO decide it, which is how the two
            #: symlink shapes are covered without a rule of their own.
            expected = ("replay" if path.read_bytes() == rendered
                        else "conflict")
        if expected == "absent":
            with publication_deadline(10, "publish_worker_result"):
                relative = state.publish_worker_result(
                    self.run_dir, result=requested)
            self.assertEqual((self.repo / relative).read_bytes(), rendered)
            return
        if expected == "replay":
            with publication_deadline(10, "publish_worker_result"):
                relative = state.publish_worker_result(
                    self.run_dir, result=requested)
            self.assertEqual((self.repo / relative).read_bytes(), rendered)
            self.assertEqual(name_state(path), before)
            self.assertEqual(name_state(path.parent), before_parent)
            return
        error = {
            "conflict": state.TrackerValidationError,
            "corrupt": state.QuorumSchemaInvalid,
            "unreadable": state.TrackerValidationError,
            "parent": state.TrackerWriteError,
        }[expected]
        with publication_deadline(10, "publish_worker_result"):
            with self.assertRaises(error):
                state.publish_worker_result(self.run_dir, result=requested)
        self.assertEqual(name_state(path), before)
        self.assertEqual(name_state(path.parent), before_parent)

    def test_a_fifo_under_the_tree_does_not_hang_the_run(self):
        """The C1 shape, on its own, with its own deadline. `is_file()` is
        False for a FIFO, so an existence test reads it as absence; the read
        that follows blocks for ever under the run lock."""
        if not hasattr(os, "mkfifo"):
            self.skipTest("no mkfifo on this platform")
        path = state.worker_result_path(self.run_dir, task_id="T1", attempt=1)
        path.parent.mkdir(parents=True)
        os.mkfifo(path)
        with publication_deadline(10, "publish_worker_result"):
            with self.assertRaises(state.QuorumSchemaInvalid):
                state.publish_worker_result(self.run_dir, result=worker_result())

    def test_an_invalid_utf8_neighbour_is_refused_inside_the_family(self):
        """A `read_text` pre-check raises `UnicodeDecodeError`, which is a
        `ValueError` and not a `TrackerError`, so a controller branching on the
        family never sees it."""
        path = state.worker_result_path(self.run_dir, task_id="T1", attempt=1)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xff\xfe\x00not utf 8")
        with self.assertRaises(state.TrackerValidationError):
            state.publish_worker_result(self.run_dir, result=worker_result())
        self.assertEqual(path.read_bytes(), b"\xff\xfe\x00not utf 8")


class PublishedPathCitabilityTests(TempDirTestCase):
    """What Task 10 must be able to DO with the string this returns.

    `_digest_reference` is the grammar every bound reference in this module is
    held to: `<repository-relative-path>#sha256=<64 lowercase hex>`, with the
    path through `_safe_relative` and `#` refused inside it. So the returned
    spelling is screened against exactly that, BEFORE anything is written --
    a run directory that cannot be cited must not gain an immutable record
    nothing can bind a digest to.
    """

    def setUp(self) -> None:
        super().setUp()
        self.repo = make_repo(self.tmp)

    def test_the_returned_path_is_a_legal_digest_reference_subject(self):
        run_dir = make_run_in(self.repo, "docs/superpowers/runs/run-1")
        relative = state.publish_worker_result(run_dir, result=worker_result())
        digest = hashlib.sha256((self.repo / relative).read_bytes()).hexdigest()
        self.assertEqual(
            state._digest_reference(f"{relative}#sha256={digest}",
                                    field="result"),
            (relative, digest))

    def test_a_run_directory_carrying_a_hash_is_refused_before_any_write(self):
        """`#` is the delimiter of a bound reference. A path carrying one gives
        `docs/a#sha256=<64 hex>.md#sha256=<64 hex>` two plausible readings, and
        `_digest_reference` refuses it rather than picking a side."""
        run_dir = make_run_in(self.repo, "runs/run#1")
        with self.assertRaises(state.TrackerValidationError):
            state.publish_worker_result(run_dir, result=worker_result())
        self.assertFalse((run_dir / state.AGENT_OUTPUT_DIRNAME).exists())

    def test_a_run_directory_carrying_a_glob_is_refused_before_any_write(self):
        run_dir = make_run_in(self.repo, "runs/run*1", import_plan=False)
        with self.assertRaises(state.TrackerValidationError):
            state.publish_worker_result(run_dir, result=worker_result())
        self.assertFalse((run_dir / state.AGENT_OUTPUT_DIRNAME).exists())

    def test_a_run_outside_the_recorded_repository_root_is_refused(self):
        """The root is the one RECORDED AT INIT and read back with
        `repo_root(tracker)`; it is never derived from `run_dir` depth. A run
        directory outside it has no repository-relative spelling, so there is
        nothing a later phase could cite."""
        outside = self.tmp / "outside" / "run-1"
        outside.mkdir(parents=True)
        state.initialize_run(
            outside, run_id="run-1",
            base_commit=git(self.repo, "rev-parse", "HEAD"),
            target_branch="target", worker_limit=6, repo_root=str(self.repo))
        with self.assertRaises(state.TrackerValidationError):
            state.publish_worker_result(outside, result=worker_result())
        self.assertFalse((outside / state.AGENT_OUTPUT_DIRNAME).exists())

    def test_a_run_directory_that_cannot_be_resolved_is_refused_in_family(self):
        """A NUL and a lone surrogate both raise out of `Path.resolve` --
        `ValueError` and `UnicodeEncodeError`, the second a `ValueError`
        subclass -- and `pathlib` swallows neither. An unresolvable name is
        never reported as a name outside the repository; it is its own stop."""
        run_dir = make_run_in(self.repo, "docs/superpowers/runs/run-1")
        for label, spelling in (("nul", f"{run_dir}\x00x"),
                                ("surrogate", f"{run_dir}\ud800")):
            with self.subTest(spelling=label):
                with self.assertRaises(state.TrackerValidationError):
                    state.publish_worker_result(
                        spelling, result=worker_result())

    def test_a_run_directory_with_a_space_still_publishes(self):
        """A space is legal in a tracker cell -- `_cell_safe` refuses only
        SURROUNDING whitespace -- so it must not be swept up by the screens
        above. A refusal here would be a screen wider than the grammar it
        claims to enforce."""
        run_dir = make_run_in(self.repo, "runs/with a space/run-1")
        relative = state.publish_worker_result(run_dir, result=worker_result())
        self.assertEqual(
            relative,
            f"runs/with a space/run-1/{state.AGENT_OUTPUT_DIRNAME}"
            "/T1/attempt-001.md")
        self.assertTrue((self.repo / relative).is_file())


class PublishedDigestBindingTests(TempDirTestCase):
    """The digest is the identity, so it is compared against the BYTES ON DISK.

    THE BRIEF'S STEP-3 CHECK IS VACUOUS. It compares `publish_immutable`'s
    return value against `sha256(content)`, and `publish_immutable`'s whole
    body is `return sha256(content)` -- the two are equal for every input, in
    every branch, so the screen can never fire and the prose above it ('the
    digest comparison proves the bytes on disk are the bytes that were
    validated') describes a comparison the code does not make. The bytes on
    disk are the other operand.
    """

    def setUp(self) -> None:
        super().setUp()
        self.repo, self.run_dir, _ = make_run(
            self.tmp, three_disjoint_tasks(), worker_limit=6)

    def test_the_bytes_on_disk_are_the_bytes_that_were_validated(self):
        relative = state.publish_worker_result(
            self.run_dir, result=worker_result())
        on_disk = (self.repo / relative).read_bytes()
        self.assertEqual(
            on_disk,
            state.render_worker_result(worker_result()).encode("utf-8"))
        self.assertEqual(state.parse_worker_result(on_disk.decode("utf-8")),
                         worker_result())

    def test_a_publisher_that_wrote_other_bytes_is_caught(self):
        """The screen's own domain. `publish_immutable` is P02's and may be
        changed by P02; what this function promises is that the record it
        returns a path to holds the document it validated."""
        real = state.publish_immutable

        def wrong(path, content):
            return real(path, content + "a line nobody validated\n")

        with mock.patch.object(state, "publish_immutable", wrong):
            with self.assertRaises(state.TrackerValidationError):
                state.publish_worker_result(
                    self.run_dir, result=worker_result())

    def test_a_publisher_that_reported_a_digest_for_other_bytes_is_caught(self):
        """The digest is the record's identity. One that does not hash the
        bytes on disk binds every later phase to a comparison that can only
        fail, and it fails at the phase that CITES the record rather than at
        the one that wrote it."""
        real = state.publish_immutable

        def lying(path, content):
            real(path, content)
            return "0" * 64

        with mock.patch.object(state, "publish_immutable", lying):
            with self.assertRaises(state.TrackerValidationError):
                state.publish_worker_result(
                    self.run_dir, result=worker_result())

    def test_a_publisher_that_wrote_nothing_is_caught(self):
        """A digest returned for a record that is not there binds a later
        phase to a file it can never read."""
        with mock.patch.object(
                state, "publish_immutable",
                lambda path, content: hashlib.sha256(
                    content.encode("utf-8")).hexdigest()):
            with self.assertRaises(state.TrackerValidationError):
                state.publish_worker_result(
                    self.run_dir, result=worker_result())

    def test_the_owner_line_p06_scans_for_survives_publication(self):
        """The cross-phase contract, end to end: what is written into
        `agent-output/` carries the line P06's `owner_history` reads with
        `startswith(_OWNER_LINE_PREFIX)`, and it names the owner cell."""
        relative = state.publish_worker_result(
            self.run_dir, result=worker_result(owner="impl-7"))
        lines = (self.repo / relative).read_text(
            encoding="utf-8").splitlines()
        owners = [line[len(state._OWNER_LINE_PREFIX):] for line in lines
                  if line.startswith(state._OWNER_LINE_PREFIX)]
        self.assertEqual(owners, ["impl-7"])

    def test_the_published_tree_is_the_one_p06_scans(self):
        """`rglob("*.md")` from `<run_dir>/agent-output` finds every published
        result, which is what makes the released-worker case visible at all."""
        for attempt, owner in ((1, "impl-1"), (2, "impl-2")):
            state.publish_worker_result(
                self.run_dir,
                result=worker_result(attempt=attempt, owner=owner))
        found = sorted(
            path.relative_to(self.run_dir / state.AGENT_OUTPUT_DIRNAME).as_posix()
            for path in (self.run_dir / state.AGENT_OUTPUT_DIRNAME).rglob("*.md"))
        self.assertEqual(found, ["T1/attempt-001.md", "T1/attempt-002.md"])

#: THE ALPHABET THE DIVERGENCE IS MEASURED OVER, chosen so every character
#: class either screen can disagree about is represented: ASCII alphanumerics,
#: every character `_TOKEN` admits beyond them, the separators a cell breaks
#: on, a NUL, a lone surrogate, a non-ASCII decimal digit (`isdigit` is true of
#: it and `int()` accepts it), a superscript, a Latin letter with an accent,
#: and two glob characters.
DIVERGENCE_ALPHABET = (
    "a", "Z", "0", ".", "_", "-", "/", "@", ":", "+",
    " ", "\t", "\n", " ", "\x00", "\ud800",
    "١", "³", "é", "#", "*",
)

#: `_TOKEN` and `_PATH_SEGMENT` as PATTERNS, so the hand-rolled screens can be
#: measured against the thing the plans were written in. The module may not
#: import `re`; this file may, and that asymmetry is the only way the
#: translation can be checked rather than asserted.
TOKEN_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._/@:+\-]*"
SEGMENT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._\-]*"


def divergence_corpus() -> tuple:
    """Every string of length 1..3 over the alphabet, plus the length cases.

    EXHAUSTIVE OVER SHORT STRINGS rather than randomly sampled: the screens
    are character classes with a head rule, so every disagreement either shows
    up within three characters or is a length or trailing-character rule, and
    those are added by name.
    """
    cases = []
    for width in (1, 2, 3):
        cases.extend("".join(combination) for combination
                     in itertools.product(DIVERGENCE_ALPHABET, repeat=width))
    cases.extend(("", "a" * 63, "a" * 64, "a" * 65, "a" * 200,
                  "a" * 63 + ".", "a" * 64 + "."))
    return tuple(cases)


class PathSegmentGrammarDivergenceTests(unittest.TestCase):
    """The hand-rolled screens against the patterns the plans were written in.

    The module may not import `re`, so every grammar in it is a translation,
    and a translation is a claim to MEASURE in both directions rather than a
    transcription. Task 9 introduces no new pattern: it reuses P02's `_TOKEN`
    and aliases P03's `_OWNER`. What it does introduce is a deliberate
    TIGHTENING -- a task id that reaches a path is held to the narrower of the
    two -- and the divergence between them is the thing this class writes down.
    """

    def test_p02s_token_agrees_with_the_pattern_in_both_directions(self):
        pattern = re.compile(TOKEN_PATTERN)
        disagreements = [
            value for value in divergence_corpus()
            if bool(pattern.fullmatch(value)) != bool(state._TOKEN.fullmatch(value))]
        self.assertEqual(disagreements, [])

    def test_the_segment_screen_agrees_with_its_pattern_plus_two_rules(self):
        """`_OWNER` is a `_CharClass` with two rules bolted on, so the pattern
        it is measured against carries them: a 64-character bound, because an
        unbounded id passes every check here and fails inside
        `publish_immutable` with ENAMETOOLONG; and no trailing dot, because
        the name becomes a filename on a filesystem this module may not be
        running on."""
        pattern = re.compile(SEGMENT_PATTERN)
        disagreements = [
            value for value in divergence_corpus()
            if (bool(pattern.fullmatch(value)) and len(value) <= 64
                and not value.endswith("."))
            != bool(state._PATH_SEGMENT.fullmatch(value))]
        self.assertEqual(disagreements, [])

    def test_the_tightening_is_one_directional(self):
        """Every id that may become a directory name is an id a plan may
        declare. The reverse is what this task refuses, and a screen that
        admitted something `_TOKEN` does not would be a widening nobody asked
        for."""
        widenings = [value for value in divergence_corpus()
                     if state._PATH_SEGMENT.fullmatch(value)
                     and not state._TOKEN.fullmatch(value)]
        self.assertEqual(widenings, [])

    def test_every_disagreement_has_exactly_one_of_three_named_reasons(self):
        """The divergence table, executable. A disagreement with no reason on
        this list is a screen doing something nobody wrote down."""
        def reason(value: str) -> str:
            if any(character in value for character in "/@:+"):
                return "carries a separator a path or a Windows filename cannot hold"
            if value.endswith("."):
                return "a trailing dot is dropped by some filesystems"
            if len(value) > 64:
                return "past the bound that keeps ENAMETOOLONG out of reach"
            return "UNEXPLAINED"

        reasons = {}
        for value in divergence_corpus():
            if bool(state._TOKEN.fullmatch(value)) != bool(
                    state._PATH_SEGMENT.fullmatch(value)):
                reasons.setdefault(reason(value), []).append(value)
        self.assertNotIn("UNEXPLAINED", reasons)
        self.assertEqual(
            sorted(reasons),
            ["a trailing dot is dropped by some filesystems",
             "carries a separator a path or a Windows filename cannot hold",
             "past the bound that keeps ENAMETOOLONG out of reach"])
        #: The counts are the table. They are asserted so a later widening of
        #: either grammar shows up here as a number rather than as silence.
        self.assertEqual(
            {name: len(values) for name, values in reasons.items()},
            {"carries a separator a path or a Windows filename cannot hold": 204,
             "a trailing dot is dropped by some filesystems": 23,
             "past the bound that keeps ENAMETOOLONG out of reach": 2})

    def test_the_ascii_reading_is_the_tightening_both_screens_intend(self):
        """`\\d` and `\\w` are Unicode by default and `str.isdigit` is wider
        still: `int('\\u0661')` is 1. Both screens are ASCII character sets, so
        an id spelled in Arabic-Indic digits is refused by both -- which is the
        intended reading and is measured rather than assumed."""
        for value in ("١", "T١", "³", "Té", "é"):
            with self.subTest(value=value):
                self.assertFalse(state._TOKEN.fullmatch(value))
                self.assertFalse(state._PATH_SEGMENT.fullmatch(value))
                self.assertTrue(re.compile(r"\w+").fullmatch(value)
                                or not value.isalnum())



#: THE NAMES THE 1..3 CORPUS CANNOT REACH. `_TASK_ID`'s two extra rules are
#: about a `..` in the MIDDLE of an id and a `.lock` at the end of one, and
#: neither fits in three characters that also start with an alphanumeric and
#: do not end in a dot. They are added by name, exactly as the length cases
#: are, and each is paired with the answer real git gives.
#: The two length cases are deliberately NOT repeated here: `divergence_corpus`
#: already carries them, and a duplicate would inflate a count this file
#: asserts as a literal.
REF_RESIDUE_CASES = (
    "T..1", "a..b", "T...1", "T..", "..T", "T.lock", "T1.lock", "T.locker",
    "T1.LOCK", "lock", ".lock", "a.b.c", "T1",
)


def git_accepts_as_a_branch(value: str) -> bool:
    """What `git check-ref-format` says about `refs/heads/<value>`.

    THE REAL PROGRAM, not a transcription of its rules. The plan grammar's
    own refusal message says a task id "is written into a tracker cell, A
    BRANCH NAME and a checkpoint marker", so the authority on what a task id
    may be is git, and a second-hand list of git's rules in this file would
    be the same two-answers defect the module keeps refusing.
    """
    return subprocess.run(
        ("git", "check-ref-format", "refs/heads/" + value),
        capture_output=True).returncode == 0


class TaskIdIsABranchNameTests(unittest.TestCase):
    """`_TASK_ID` against `git check-ref-format`, in both directions.

    THE RULING THIS PINS. A task id carrying `/`, `:`, `@`, `+`, a trailing
    dot, a `..`, a `.lock` ending or a 65th character was accepted by the plan
    grammar and by `_validate_assignment`, and refused at publication --
    and `reserve_task` accepted it, so the slot was held against the
    `worker_limit - 3` implementation cap and could never be released. The
    grammar is tightened at plan import instead, and the authority for HOW
    tight is the program that will be handed the branch name.
    """

    def _probed(self) -> tuple:
        """Every string either grammar accepts, plus the named residue.

        `_TOKEN`'s accepts are a superset of `_PATH_SEGMENT`'s and of
        `_TASK_ID`'s, so probing them covers the no-widening direction
        exhaustively over the corpus at a few hundred subprocesses rather
        than nine thousand.
        """
        values = [value for value in divergence_corpus()
                  if state._TOKEN.fullmatch(value)]
        values.extend(value for value in REF_RESIDUE_CASES
                      if value not in values)
        return tuple(values)

    def test_every_task_id_the_grammar_accepts_is_a_legal_branch_name(self):
        """THE NO-WIDENING DIRECTION, exhaustive over the corpus. A task id
        this module admits and git refuses is the deadlock again, one layer
        further down: the plan imports, the slot is taken, and the phase that
        creates the branch is where it dies."""
        widenings = [value for value in self._probed()
                     if state._TASK_ID.fullmatch(value)
                     and not git_accepts_as_a_branch(value)]
        self.assertEqual(widenings, [])

    def test_the_two_rules_git_adds_to_the_path_grammar_are_exactly_these(self):
        """`_PATH_SEGMENT` alone is NOT enough, and this is the measurement
        that says so. `T..1` and `T.lock` are perfectly good filenames -- one
        directory component each, traversing nothing -- so the path grammar
        has no reason to refuse them, and git refuses both."""
        residue = sorted(
            value for value in self._probed()
            if state._PATH_SEGMENT.fullmatch(value)
            and not git_accepts_as_a_branch(value))
        self.assertEqual(residue, ["T...1", "T..1", "T.lock", "T1.lock",
                                   "a..b"])
        for value in residue:
            with self.subTest(value=value):
                self.assertFalse(state._TASK_ID.fullmatch(value))
                self.assertTrue(".." in value
                                or value.endswith(state._REF_LOCK_SUFFIX))
        #: The near misses, so the rules are rules and not a blocklist.
        for value in ("T.locker", "T1.LOCK", "a.b.c", "T1"):
            with self.subTest(accepted=value):
                self.assertTrue(state._TASK_ID.fullmatch(value))
                self.assertTrue(git_accepts_as_a_branch(value))

    def test_the_task_id_grammar_is_a_tightening_of_both_its_parents(self):
        """Pure grammar, over the whole corpus and with no subprocess: every
        id `_TASK_ID` admits is one `_PATH_SEGMENT` admits, and every one of
        those is one `_TOKEN` admits. A widening in either step would be a
        grammar nobody asked for."""
        corpus = divergence_corpus() + REF_RESIDUE_CASES
        self.assertEqual(
            [value for value in corpus if state._TASK_ID.fullmatch(value)
             and not state._PATH_SEGMENT.fullmatch(value)], [])
        self.assertEqual(
            [value for value in corpus if state._PATH_SEGMENT.fullmatch(value)
             and not state._TOKEN.fullmatch(value)], [])

    def test_TOKEN_itself_is_not_narrowed_by_the_ruling(self):
        """THE EXPLICIT NON-FIX. `_TOKEN` is shared with `target_branch`,
        `transition_id`, `axis`, `phase_id`, `reviewer`, `batch` and `dep`,
        and a branch name is a ref of SEVERAL components -- `feat/x` is one
        legal branch and one illegal task id. Narrowing `_TOKEN` to fix the
        task id would refuse every one of those."""
        for value in ("feat/x", "a@b", "a:b", "a+b", "x" * 200, "T1."):
            with self.subTest(value=value):
                self.assertTrue(state._TOKEN.fullmatch(value))
                self.assertFalse(state._TASK_ID.fullmatch(value))
        self.assertTrue(git_accepts_as_a_branch("feat/x"))

    def test_every_disagreement_with_the_token_has_a_named_reason(self):
        """The divergence table for the grammar that now screens a task id.
        The three `_PATH_SEGMENT` reasons plus the two git adds, with counts,
        so a later widening of either shows up as a number rather than as
        silence."""
        def reason(value: str) -> str:
            if any(character in value for character in "/@:+"):
                return "carries a separator a path or a Windows filename cannot hold"
            if value.endswith("."):
                return "a trailing dot is dropped by some filesystems"
            if len(value) > 64:
                return "past the bound that keeps ENAMETOOLONG out of reach"
            if ".." in value:
                return "git refuses '..' anywhere in a ref"
            if value.endswith(state._REF_LOCK_SUFFIX):
                return "git reserves the '.lock' suffix for its own lock file"
            return "UNEXPLAINED"

        reasons: dict = {}
        for value in divergence_corpus() + REF_RESIDUE_CASES:
            if bool(state._TOKEN.fullmatch(value)) != bool(
                    state._TASK_ID.fullmatch(value)):
                reasons.setdefault(reason(value), []).append(value)
        self.assertNotIn("UNEXPLAINED", reasons)
        self.assertEqual(
            {name: len(values) for name, values in reasons.items()},
            {"carries a separator a path or a Windows filename cannot hold": 204,
             #: 23 + `T..`, which the trailing-dot rule reaches before the
             #: `..` rule does. The order of the arms is the order of the
             #: rules, so a value is counted once and by its FIRST reason.
             "a trailing dot is dropped by some filesystems": 24,
             "past the bound that keeps ENAMETOOLONG out of reach": 2,
             "git refuses '..' anywhere in a ref": 3,
             "git reserves the '.lock' suffix for its own lock file": 2})


class TaskIdDeadlockIsClosedTests(TempDirTestCase):
    """END TO END: the route the review walked, now stopped at the first door.

    "It is worse than 'cannot publish': the slot is consumed." A task id git
    will not accept as a branch used to import, reserve, reach `[~]`, hold an
    implementation slot against the `worker_limit - 3` cap and never
    terminate. Each of those steps is asserted here to be unreachable.
    """

    #: Every shape the review named, one per rule, so a partial tightening
    #: fails on the rule it missed rather than passing on the rules it kept.
    WEDGING_IDS = ("T/1", "T:1", "T@1", "T+1", "T1.", "T..1", "T1.lock",
                   "a" * 65)

    def setUp(self) -> None:
        super().setUp()
        self.repo, self.run_dir, _ = make_run(
            self.tmp, three_disjoint_tasks(), worker_limit=6)

    def test_a_phase_plan_declaring_one_is_refused_at_import(self):
        """The loud stop, at the only place where nothing is reserved yet."""
        for task_id in self.WEDGING_IDS:
            with self.subTest(task_id=task_id):
                plan = write_phase_plan(
                    self.tmp, task_block(task_id),
                    name=f"wedge-{len(task_id)}-{abs(hash(task_id))}.md")
                before = (self.run_dir / "progress.md").read_bytes()
                with self.assertRaises(state.PlanMetadataError) as caught:
                    state.import_phase_plan(self.run_dir, phase_plan=plan)
                self.assertIn("invalid task id", str(caught.exception))
                self.assertEqual(
                    (self.run_dir / "progress.md").read_bytes(), before)

    def test_reserve_task_no_longer_takes_a_slot_it_cannot_release(self):
        """The defence in depth. A tracker row can also arrive from a run
        whose plan an older build imported, so the reservation screen is not
        redundant with the import screen."""
        for task_id in self.WEDGING_IDS:
            with self.subTest(task_id=task_id):
                before = (self.run_dir / "progress.md").read_bytes()
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.reserve_task(self.run_dir, task_id=task_id,
                                       owner="impl-1", attempt=1)
                self.assertIn("invalid task id", str(caught.exception))
                self.assertEqual(
                    (self.run_dir / "progress.md").read_bytes(), before)

    def test_resume_task_refuses_the_same_ids(self):
        for task_id in self.WEDGING_IDS:
            with self.subTest(task_id=task_id):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.resume_task(
                        self.run_dir, task_id=task_id, prior_attempt=1,
                        new_owner="impl-2", new_attempt=2, decision_ref="H-1")
                self.assertIn("invalid task id", str(caught.exception))

    def test_publication_still_refuses_them_and_that_is_now_unreachable(self):
        """Task 9's screen stays. After the tightening no legal plan can reach
        it, which is the correct end state for a defence-in-depth screen and
        not a reason to delete it -- the ruling `_require_regular_file`'s
        absence arm already records."""
        for task_id in self.WEDGING_IDS:
            with self.subTest(task_id=task_id):
                with self.assertRaises(state.TrackerValidationError):
                    state.worker_result_path(
                        self.run_dir, task_id=task_id, attempt=1)

    def test_every_id_the_token_admits_and_the_task_grammar_does_not_is_stopped_at_import(self):
        """The 229 divergence strings, put through the door that used to let
        them in. Sampling would not do: the whole point of the defect is that
        one of them reaching a reservation is a wedged run."""
        refused = 0
        for value in divergence_corpus() + REF_RESIDUE_CASES:
            if not state._TOKEN.fullmatch(value) or state._TASK_ID.fullmatch(value):
                continue
            refused += 1
            with self.subTest(task_id=value):
                with self.assertRaises(state.TrackerValidationError) as caught:
                    state.reserve_task(self.run_dir, task_id=value,
                                       owner="impl-1", attempt=1)
                self.assertIn("invalid task id", str(caught.exception))
        self.assertEqual(refused, 204 + 24 + 2 + 3 + 2)
        self.assertEqual(refused, 235)


if __name__ == "__main__":
    unittest.main()
