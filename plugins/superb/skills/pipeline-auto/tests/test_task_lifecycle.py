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
        self._expect_rejection(
            "## Task T1\n\n"
            + task_line(kind="artifact", write_scope="tree:docs",
                        outputs="docs/a.md")
            + "\n" + task_suite_line() + "\n")

    def test_duplicate_task_ids_are_rejected(self):
        self._expect_rejection(task_block("T1") + task_block("T1", order=2))

    def test_unknown_and_self_dependencies_are_rejected(self):
        for deps in ("T9", "T1"):
            with self.subTest(deps=deps):
                self._expect_rejection(task_block("T1", deps=deps),
                                       name=f"dep-{deps}.md")

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

    def test_order_is_ascii_digits_and_not_whatever_int_accepts(self):
        """The defect a bare ``int(raw)`` leaves, and the module has written it
        down once already in ``_Numbered``: ``int(chr(0x0661))`` is 1 and
        ``int('1_0')`` is 10, so a plan can spell an order in Arabic-Indic
        digits or with a separator and the tracker records a number nobody
        wrote. Each is asserted to be a number Python WOULD have accepted, so
        the test says what it is discriminating against."""
        for order in (chr(0x0661), "1_0", "+1", " 1", "1 ", "01", "1.0", "",
                      "one", "-1", "0", chr(0x00B3)):
            with self.subTest(order=order):
                self._expect_rejection(
                    "## Task T1\n\n" + task_line(order=order) + "\n"
                    + task_suite_line() + "\n", name="order.md")
        self.assertEqual([int(spelling) for spelling in
                          (chr(0x0661), "+1", " 1", "1 ", "01")], [1, 1, 1, 1, 1])
        self.assertEqual(int("1_0"), 10)

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
        with self.assertRaises(ValueError):
            Path(nul).read_text(encoding="utf-8")
        self._expect_path_rejection(nul)
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
        """The other way a path escapes the family: ``is_file()`` and
        ``os.path.lexists`` are both False -- so the regular-file door is
        silent -- and the read then raises ``UnicodeEncodeError`` out of the
        encoder that turns the name into bytes."""
        for code in (0xD800, 0xDBFF, 0xDC00, 0xDFFF):
            spelling = str(self.tmp / f"a{chr(code)}b.md")
            with self.subTest(code=hex(code)):
                self.assertFalse(state._survives_the_encoder(chr(code)))
                self.assertFalse(os.path.lexists(spelling))
                with self.assertRaises(UnicodeEncodeError):
                    Path(spelling).read_text(encoding="utf-8")
                self._expect_path_rejection(spelling)

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


if __name__ == "__main__":
    unittest.main()
