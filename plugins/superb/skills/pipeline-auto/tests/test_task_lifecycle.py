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

import itertools
import json
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
) -> str:
    text = (
        f"## Task {task_id}\n\n"
        f"<!-- pipeline-auto-task: id={task_id}; deps={deps}; kind={kind}; "
        f"batch={batch}; order={order}; write_scope={write_scope}; "
        f"outputs={outputs} -->\n"
    )
    if kind == "source":
        suite = commands or f'["python3 -m unittest -k {task_id}"]'
        text += f"<!-- pipeline-auto-task-suite: id={task_id}; commands={suite} -->\n"
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


if __name__ == "__main__":
    unittest.main()
