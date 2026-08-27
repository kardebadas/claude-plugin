import copy
import unittest

from schema import (
    CHOICE_TYPES,
    IMPORTANCES,
    TYPES,
    answer_state,
    count_answered,
    count_open,
    validate_round,
)


def question(**kw):
    base = {"id": "Q-001", "importance": "REQUIRED", "title": "Auth?", "type": "text"}
    base.update(kw)
    return base


def a_round(*questions):
    return {"round": 1, "questions": list(questions)}


class ValidateRoundTest(unittest.TestCase):
    def test_a_minimal_valid_round_has_no_errors(self):
        self.assertEqual(validate_round(a_round(question())), [])

    def test_a_choice_question_with_options_is_valid(self):
        q = question(type="single", options=[{"value": "email", "label": "Email"}])
        self.assertEqual(validate_round(a_round(q)), [])

    def test_a_non_object_round_is_rejected(self):
        self.assertEqual(validate_round([1, 2]), ["round must be a JSON object"])

    def test_a_missing_round_number_is_reported(self):
        obj = a_round(question())
        del obj["round"]
        self.assertIn("round: missing or not an integer", validate_round(obj))

    def test_missing_questions_list_is_reported(self):
        self.assertIn("questions: missing or not a list", validate_round({"round": 1}))

    def test_a_missing_id_is_reported(self):
        errors = validate_round(a_round(question(id="")))
        self.assertTrue(any("id missing" in e for e in errors))

    def test_a_duplicate_id_is_reported(self):
        errors = validate_round(a_round(question(), question()))
        self.assertTrue(any("duplicate id Q-001" in e for e in errors))

    def test_a_bad_importance_is_reported(self):
        errors = validate_round(a_round(question(importance="CRITICAL")))
        self.assertTrue(any("importance must be one of" in e for e in errors))

    def test_a_bad_type_is_reported(self):
        errors = validate_round(a_round(question(type="dropdown")))
        self.assertTrue(any("type must be one of" in e for e in errors))

    def test_single_without_options_is_reported(self):
        errors = validate_round(a_round(question(type="single")))
        self.assertTrue(any("requires a non-empty options list" in e for e in errors))

    def test_multi_with_a_valueless_option_is_reported(self):
        q = question(type="multi", options=[{"label": "Email"}])
        errors = validate_round(a_round(q))
        self.assertTrue(any("needs a string value" in e for e in errors))

    def test_text_ignores_options_entirely(self):
        self.assertEqual(validate_round(a_round(question(type="longtext"))), [])


class AnswerStateTest(unittest.TestCase):
    def test_absent_is_skipped(self):
        self.assertEqual(answer_state(None), "skipped")

    def test_explicit_skip_is_skipped(self):
        self.assertEqual(answer_state({"skipped": True}), "skipped")

    def test_delegated_is_delegated(self):
        self.assertEqual(answer_state({"delegated": True}), "delegated")

    def test_delegated_wins_over_a_stale_choice(self):
        self.assertEqual(answer_state({"delegated": True, "choice": ["a"]}), "delegated")

    def test_a_choice_is_answered(self):
        self.assertEqual(answer_state({"choice": ["email"]}), "answered")

    def test_an_empty_choice_list_is_skipped(self):
        self.assertEqual(answer_state({"choice": []}), "skipped")

    def test_text_is_answered(self):
        self.assertEqual(answer_state({"text": "yes"}), "answered")

    def test_whitespace_only_text_is_skipped(self):
        self.assertEqual(answer_state({"text": "   "}), "skipped")

    def test_other_alone_is_answered(self):
        self.assertEqual(answer_state({"choice": [], "other": "passkeys"}), "answered")

    def test_a_note_alone_is_not_an_answer(self):
        self.assertEqual(answer_state({"note": "thinking about it"}), "skipped")


class CountsTest(unittest.TestCase):
    def setUp(self):
        self.round = a_round(
            question(id="Q-1", importance="REQUIRED"),
            question(id="Q-2", importance="REQUIRED"),
            question(id="Q-3", importance="IMPORTANT"),
            question(id="Q-4", importance="OPTIONAL"),
        )

    def test_everything_open_when_there_are_no_answers(self):
        # The brief wrote OPTIONAL: 0 here, which contradicts both its own
        # implementation and this test's own name -- the fixture's Q-4 is an
        # unanswered OPTIONAL question, so it is open. Every consumer of
        # count_open treats the four levels uniformly, so the literal was the
        # slip, not the code. OpenAtItsOwnLevelTest below pins it properly.
        self.assertEqual(
            count_open(self.round, {}),
            {"REQUIRED": 2, "IMPORTANT": 1, "PREFERENCE": 0, "OPTIONAL": 1},
        )

    def test_delegated_questions_are_not_open(self):
        answers = {"Q-1": {"choice": ["a"]}, "Q-2": {"delegated": True}}
        self.assertEqual(count_open(self.round, answers)["REQUIRED"], 0)

    def test_skipped_questions_stay_open(self):
        self.assertEqual(count_open(self.round, {"Q-1": {"skipped": True}})["REQUIRED"], 2)

    def test_count_answered_includes_delegated(self):
        answers = {"Q-1": {"choice": ["a"]}, "Q-2": {"delegated": True}, "Q-3": {"skipped": True}}
        self.assertEqual(count_answered(self.round, answers), 2)


# ---------------------------------------------------------------------------
# Hardening. Everything above is the brief's own suite; everything below was
# added because a plausible one-line change to schema.py passed all of it.
# Each class names the mutation it exists to catch.
# ---------------------------------------------------------------------------


class ValidateRoundShapeTest(unittest.TestCase):
    """The outer envelope: the round object itself, before any question."""

    def test_none_is_rejected_like_any_other_non_object(self):
        self.assertEqual(validate_round(None), ["round must be a JSON object"])

    def test_a_json_string_is_rejected(self):
        self.assertEqual(validate_round("{}"), ["round must be a JSON object"])

    def test_a_non_integer_round_number_is_reported(self):
        obj = a_round(question())
        obj["round"] = "1"
        self.assertEqual(validate_round(obj), ["round: missing or not an integer"])

    def test_the_round_number_error_survives_the_questions_early_return(self):
        """questions-not-a-list returns early. It must return the errors found
        before it, not just its own -- otherwise a round that is broken twice
        reports half its problems and the second surfaces only after a fix."""
        self.assertEqual(
            validate_round({"questions": "nope"}),
            ["round: missing or not an integer", "questions: missing or not a list"],
        )

    def test_an_empty_questions_list_is_a_valid_round(self):
        self.assertEqual(validate_round({"round": 1, "questions": []}), [])

    def test_validation_does_not_mutate_the_round_it_was_given(self):
        obj = a_round(question(), question(id="Q-002", type="single",
                                           options=[{"value": "a"}]))
        before = copy.deepcopy(obj)
        validate_round(obj)
        self.assertEqual(obj, before)


class ValidateRoundNoteTest(unittest.TestCase):
    """`note`: what a closing round is made of.

    *Ending* tells the agent to close a session with a round whose
    `questions` list is empty and whose note says why. Validation did not
    look at the field at all, so the note was accepted, written to disk and
    shown to nobody -- and the round carrying it rendered as a blank column.

    Optional, because most rounds have nothing to say outside their
    questions, and null reads as absent: the rule the ledger already keeps.
    What it may not be is a non-string. The page renders it as textContent,
    where an object arrives as "[object Object]" -- the same failure
    LEDGER_TEXT_FIELDS exists to report, in the one place a round speaks to
    the user in its own voice.
    """

    def closing(self, **kw):
        obj = {"round": 1, "questions": []}
        obj.update(kw)
        return validate_round(obj)

    def test_a_closing_round_with_a_note_is_valid(self):
        self.assertEqual(self.closing(note="Your vision is clear."), [])

    def test_a_note_on_a_round_that_still_has_questions_is_valid(self):
        obj = a_round(question())
        obj["note"] = "Three of these left, and then we are done."
        self.assertEqual(validate_round(obj), [])

    def test_an_absent_note_is_valid(self):
        self.assertEqual(self.closing(), [])

    def test_a_null_note_reads_as_an_absent_one(self):
        self.assertEqual(self.closing(note=None), [])

    def test_a_note_that_is_not_a_string_is_reported(self):
        for value in ({"text": "done"}, ["done"], 7, True):
            with self.subTest(note=value):
                self.assertEqual(self.closing(note=value), ["note: not a string"])

    def test_a_bad_note_is_reported_beside_the_rounds_other_problems(self):
        """Reporting one problem per fix is how a round takes four attempts
        to land -- the argument the ledger check is placed on, applied here."""
        self.assertEqual(
            validate_round({"questions": [], "note": 7}),
            ["round: missing or not an integer", "note: not a string"])

    def test_validation_does_not_mutate_a_round_carrying_a_note(self):
        obj = {"round": 1, "questions": [], "note": "done"}
        before = copy.deepcopy(obj)
        validate_round(obj)
        self.assertEqual(obj, before)


class ValidateRoundAgainstItsFilenameTest(unittest.TestCase):
    """`expected_round`: the one thing nothing else here ties together.

    The page selects a round by FILENAME and then addresses every PATCH and
    POST to the `round` field it was served. So `round-004.questions.json`
    carrying `"round": 2` -- an agent copying the previous round's envelope,
    which is how it happens -- is served to the page AS round 2, and the next
    autosave overwrites `round-002.draft.json` while the next Send overwrites
    an already-submitted `round-002.answers.json`. Nothing downstream can
    detect that, because by then the two numbers agree.
    """

    def test_a_round_that_agrees_with_its_filename_is_valid(self):
        self.assertEqual(validate_round(a_round(question()), 1), [])

    def test_a_round_that_disagrees_with_its_filename_is_rejected(self):
        obj = a_round(question())
        obj["round"] = 2
        self.assertEqual(validate_round(obj, 4),
                         ["round: says 2, but this is round 4"])

    def test_a_lower_round_number_is_the_case_that_overwrites_answers(self):
        obj = a_round(question())
        obj["round"] = 1
        self.assertEqual(validate_round(obj, 4),
                         ["round: says 1, but this is round 4"])

    def test_zero_is_checked_like_any_other_number(self):
        """`if expected_round:` would skip round 0 -- and 0 is below every
        round the page has seen, which is the direction that overwrites."""
        obj = a_round(question())
        obj["round"] = 0
        self.assertEqual(validate_round(obj, 4),
                         ["round: says 0, but this is round 4"])
        self.assertEqual(validate_round(obj, 0), [])

    def test_the_check_is_off_by_default(self):
        """The default is deliberate and is not an oversight. A round number
        is a fact about a FILE, and this function validates a wire object; a
        caller holding one that never came from a file has no filename to be
        consistent with. Every other caller here relies on that."""
        obj = a_round(question())
        obj["round"] = 2
        self.assertEqual(validate_round(obj), [])

    def test_a_non_integer_round_is_not_reported_twice(self):
        """"missing or not an integer" already says everything there is to
        say, and `"2" != 2` would add a second line naming the same field."""
        obj = a_round(question())
        obj["round"] = "2"
        self.assertEqual(validate_round(obj, 2),
                         ["round: missing or not an integer"])

    def test_every_problem_is_still_reported(self):
        """The mismatch does not short-circuit the rest. A round that is
        broken twice must report both, or it takes two attempts to land."""
        obj = a_round(question(importance="CRITICAL"))
        obj["round"] = 1
        errors = validate_round(obj, 3)
        self.assertIn("round: says 1, but this is round 3", errors)
        self.assertTrue(any("importance must be one of" in e for e in errors))

    def test_the_check_does_not_mutate_the_round(self):
        obj = a_round(question())
        obj["round"] = 9
        before = copy.deepcopy(obj)
        validate_round(obj, 1)
        self.assertEqual(obj, before)


class ValidateQuestionTest(unittest.TestCase):
    """Every per-question rule, one test each, asserting the whole error list.

    Asserting equality rather than `any(... in e)` is deliberate: a substring
    match cannot tell "the right rule fired" from "some other rule fired and
    happened to contain the words", and it cannot see a lost `questions[i]`
    prefix at all.
    """

    def test_a_non_object_question_is_reported_and_nothing_else_is(self):
        self.assertEqual(validate_round(a_round("not a question")),
                         ["questions[0]: not an object"])

    def test_a_second_bad_question_is_reported_alongside_the_first(self):
        """The per-question mirror of the round-level early-return test: the
        loop skips a bad question, it does not stop at one. Fail-fast here
        would halve the report and surface the second problem only after the
        first was fixed."""
        self.assertEqual(validate_round(a_round("not a question", 7)),
                         ["questions[0]: not an object",
                          "questions[1]: not an object"])

    def test_a_missing_title_is_reported(self):
        self.assertEqual(validate_round(a_round(question(title=""))),
                         ["questions[0]: title missing"])

    def test_a_non_string_title_is_reported(self):
        self.assertEqual(validate_round(a_round(question(title=42))),
                         ["questions[0]: title missing"])

    def test_a_non_string_id_is_reported(self):
        self.assertEqual(validate_round(a_round(question(id=7))),
                         ["questions[0]: id missing"])

    def test_the_importance_error_names_the_whole_vocabulary(self):
        self.assertEqual(
            validate_round(a_round(question(importance="CRITICAL"))),
            ["questions[0]: importance must be one of "
             "REQUIRED/IMPORTANT/PREFERENCE/OPTIONAL"],
        )

    def test_a_missing_importance_is_reported(self):
        q = question()
        del q["importance"]
        self.assertEqual(
            validate_round(a_round(q)),
            ["questions[0]: importance must be one of "
             "REQUIRED/IMPORTANT/PREFERENCE/OPTIONAL"],
        )

    def test_the_type_error_names_the_whole_vocabulary(self):
        self.assertEqual(
            validate_round(a_round(question(type="dropdown"))),
            ["questions[0]: type must be one of single/multi/text/longtext"],
        )

    def test_a_missing_type_is_reported(self):
        q = question()
        del q["type"]
        self.assertEqual(
            validate_round(a_round(q)),
            ["questions[0]: type must be one of single/multi/text/longtext"],
        )

    def test_every_problem_in_one_question_is_reported_not_just_the_first(self):
        q = {"id": "", "importance": "CRITICAL", "title": "", "type": "dropdown"}
        self.assertEqual(
            sorted(validate_round(a_round(q))),
            sorted([
                "questions[0]: id missing",
                "questions[0]: importance must be one of "
                "REQUIRED/IMPORTANT/PREFERENCE/OPTIONAL",
                "questions[0]: title missing",
                "questions[0]: type must be one of single/multi/text/longtext",
            ]),
        )

    def test_a_message_names_the_position_of_the_question_it_is_about(self):
        errors = validate_round(a_round(question(id="Q-1"),
                                        question(id="Q-2", title="")))
        self.assertEqual(errors, ["questions[1]: title missing"])


class DuplicateIdTest(unittest.TestCase):
    def test_distinct_ids_are_not_duplicates(self):
        self.assertEqual(validate_round(a_round(question(id="Q-1"),
                                                question(id="Q-2"))), [])

    def test_empty_ids_are_missing_rather_than_duplicates(self):
        """Two blank ids are two missing ids. Reporting the second as a
        duplicate of the first would send the author looking for a collision
        that does not exist."""
        self.assertEqual(
            validate_round(a_round(question(id=""), question(id=""))),
            ["questions[0]: id missing", "questions[1]: id missing"],
        )

    def test_a_third_occurrence_is_reported_too(self):
        errors = validate_round(a_round(question(), question(), question()))
        self.assertEqual(errors, ["questions[1]: duplicate id Q-001",
                                  "questions[2]: duplicate id Q-001"])

    def test_the_duplicate_message_names_the_offending_id(self):
        errors = validate_round(a_round(question(id="Q-auth"),
                                        question(id="Q-auth")))
        self.assertEqual(errors, ["questions[1]: duplicate id Q-auth"])


class OptionsTest(unittest.TestCase):
    """Options are required for choice types, forbidden from mattering for the
    text types, and validated one by one."""

    def test_an_empty_options_list_is_as_bad_as_no_options(self):
        self.assertEqual(
            validate_round(a_round(question(type="single", options=[]))),
            ["questions[0]: type single requires a non-empty options list"],
        )

    def test_options_that_are_not_a_list_are_reported(self):
        self.assertEqual(
            validate_round(a_round(question(type="multi", options={"a": 1}))),
            ["questions[0]: type multi requires a non-empty options list"],
        )

    def test_the_missing_options_message_names_the_offending_type(self):
        """Not a hardcoded "single" -- a multi must say multi."""
        self.assertEqual(
            validate_round(a_round(question(type="multi"))),
            ["questions[0]: type multi requires a non-empty options list"],
        )

    def test_a_non_string_option_value_is_reported(self):
        self.assertEqual(
            validate_round(a_round(question(type="single",
                                            options=[{"value": 1}]))),
            ["questions[0].options[0]: needs a string value"],
        )

    def test_an_option_that_is_not_an_object_is_reported(self):
        self.assertEqual(
            validate_round(a_round(question(type="single", options=["email"]))),
            ["questions[0].options[0]: needs a string value"],
        )

    def test_each_bad_option_is_reported_at_its_own_index(self):
        q = question(type="multi",
                     options=[{"value": "a"}, {"label": "b"}, "email"])
        self.assertEqual(
            validate_round(a_round(q)),
            ["questions[0].options[1]: needs a string value",
             "questions[0].options[2]: needs a string value"],
        )

    def test_an_option_needs_no_label_only_a_value(self):
        self.assertEqual(
            validate_round(a_round(question(type="single",
                                            options=[{"value": "a"}]))),
            [],
        )

    def test_a_text_question_never_looks_at_its_options(self):
        """The brief's test of this name passed no options at all, so it could
        not tell "ignored" from "absent". These pass options that would be
        fatal on a choice type."""
        self.assertEqual(
            validate_round(a_round(question(type="text",
                                            options=[{"label": "broken"}]))),
            [],
        )
        self.assertEqual(
            validate_round(a_round(question(type="text", options="nonsense"))), [])
        self.assertEqual(
            validate_round(a_round(question(type="text", options=[]))), [])

    def test_a_longtext_question_never_looks_at_its_options(self):
        self.assertEqual(
            validate_round(a_round(question(type="longtext",
                                            options=[{"label": "broken"}]))),
            [],
        )
        self.assertEqual(
            validate_round(a_round(question(type="longtext", options=[]))), [])

    def test_an_empty_option_value_is_reported(self):
        """An option carrying no value is a phantom answer waiting to happen:
        selecting it would settle the question with nothing in it, and the
        fold-in step would write that nothing into the brief as a decision."""
        self.assertEqual(
            validate_round(a_round(question(type="single",
                                            options=[{"value": ""}]))),
            ["questions[0].options[0]: needs a non-blank value"],
        )

    def test_a_whitespace_only_option_value_is_reported(self):
        self.assertEqual(
            validate_round(a_round(question(type="multi",
                                            options=[{"value": "  \t\n "}]))),
            ["questions[0].options[0]: needs a non-blank value"],
        )

    def test_a_blank_option_beside_a_good_one_is_reported_at_its_own_index(self):
        q = question(type="multi", options=[{"value": "email"},
                                            {"value": ""},
                                            {"value": "sms"}])
        self.assertEqual(
            validate_round(a_round(q)),
            ["questions[0].options[1]: needs a non-blank value"],
        )

    def test_a_blank_value_is_a_different_complaint_from_a_missing_one(self):
        """Two mistakes, two messages: an author who left the value out is
        looking for something different from one who left it empty."""
        blank = validate_round(a_round(question(type="single",
                                                options=[{"value": ""}])))
        absent = validate_round(a_round(question(type="single",
                                                 options=[{"label": "Email"}])))
        self.assertNotEqual(blank, absent)


class ValidateLedgerTest(unittest.TestCase):
    """The ledger, which validation did not look at at all.

    Four shapes passed with `errors: []` and then threw inside the page's
    renderLedger, taking the counter and the importance filter down with them
    while the question cards rendered and looked fine. The page defends itself
    now, and that is not a substitute for this: the page can only decline to
    draw what it was handed, while the agent that wrote the round is the one
    who can fix it, and it learns from nothing but this list.
    """

    LEDGER = {
        "contradictions": [{"id": "CON-002", "between": ["Q-1", "Q-2"],
                            "text": "Offline-first conflicts with streaming."}],
        "decisions": [{"id": "DEC-014", "title": "Playlists are private"}],
        "delegated": [{"id": "DEL-003", "title": "Retry backoff"}],
        "assumptions": [{"id": "ASM-007", "text": "One user per account"}],
    }

    def with_ledger(self, ledger):
        obj = a_round(question())
        obj["ledger"] = ledger
        return validate_round(obj)

    def test_a_full_ledger_is_valid(self):
        self.assertEqual(self.with_ledger(self.LEDGER), [])

    def test_an_absent_ledger_is_valid(self):
        """The ordinary case, and the one every session opens in: nothing has
        been recorded yet."""
        self.assertEqual(validate_round(a_round(question())), [])

    def test_an_empty_ledger_is_valid(self):
        self.assertEqual(self.with_ledger({}), [])

    def test_a_null_ledger_is_valid(self):
        """JSON null reads the same as the key not being there, and the page
        renders it the same way."""
        self.assertEqual(self.with_ledger(None), [])

    def test_a_ledger_that_is_not_an_object_is_reported(self):
        self.assertEqual(self.with_ledger("none yet"), ["ledger: not an object"])
        self.assertEqual(self.with_ledger([]), ["ledger: not an object"])
        self.assertEqual(self.with_ledger(7), ["ledger: not an object"])

    # The four shapes a review reproduced against a real server in a real
    # browser. Each one rendered its cards and then blanked the counter.

    def test_contradictions_as_a_string_is_reported(self):
        self.assertEqual(self.with_ledger({"contradictions": "CON-002"}),
                         ["ledger.contradictions: not a list"])

    def test_decisions_as_a_string_is_reported(self):
        self.assertEqual(self.with_ledger({"decisions": "DEC-014"}),
                         ["ledger.decisions: not a list"])

    def test_assumptions_as_a_dict_is_reported(self):
        self.assertEqual(self.with_ledger({"assumptions": {"ASM-1": "guessed"}}),
                         ["ledger.assumptions: not a list"])

    def test_a_contradictions_between_as_a_string_is_reported(self):
        """A bare question id where a list of them belongs. It iterates by
        character in the page and throws outright in the forEach, and it is
        the easiest of the four to write by hand."""
        self.assertEqual(
            self.with_ledger({"contradictions": [{"id": "CON-1", "between": "Q-1"}]}),
            ["ledger.contradictions[0].between: not a list"])

    def test_delegated_as_a_string_is_reported_like_the_others(self):
        """No section is special-cased; all four are iterated by the page."""
        self.assertEqual(self.with_ledger({"delegated": "DEL-003"}),
                         ["ledger.delegated: not a list"])

    def test_an_entry_that_is_not_an_object_is_reported_at_its_index(self):
        self.assertEqual(
            self.with_ledger({"decisions": [{"id": "DEC-1"}, "DEC-2"]}),
            ["ledger.decisions[1]: not an object"])

    def test_an_entry_without_an_id_is_reported(self):
        """The id is what the line is called on screen and what the user says
        back to Claude. A line with none is a line nobody can refer to."""
        self.assertEqual(self.with_ledger({"assumptions": [{"text": "guessed"}]}),
                         ["ledger.assumptions[0]: id missing"])
        self.assertEqual(self.with_ledger({"assumptions": [{"id": "", "text": "x"}]}),
                         ["ledger.assumptions[0]: id missing"])
        self.assertEqual(self.with_ledger({"assumptions": [{"id": 7}]}),
                         ["ledger.assumptions[0]: id missing"])

    def test_a_field_that_should_be_a_sentence_is_reported(self):
        self.assertEqual(
            self.with_ledger({"decisions": [{"id": "DEC-1", "title": {"a": 1}}]}),
            ["ledger.decisions[0].title: not a string"])
        self.assertEqual(
            self.with_ledger({"assumptions": [{"id": "ASM-1", "text": ["x"]}]}),
            ["ledger.assumptions[0].text: not a string"])
        self.assertEqual(
            self.with_ledger({"decisions": [{"id": "DEC-1", "summary": 3}]}),
            ["ledger.decisions[0].summary: not a string"])

    def test_a_line_needs_no_words_only_an_id(self):
        """A bare id renders as a bare id, which is legible. Absent is not the
        same complaint as present-and-the-wrong-type."""
        self.assertEqual(self.with_ledger({"decisions": [{"id": "DEC-1"}]}), [])

    def test_a_bad_reference_inside_between_is_reported_at_its_index(self):
        self.assertEqual(
            self.with_ledger({"contradictions": [
                {"id": "CON-1", "between": ["Q-1", 7, ""]}]}),
            ["ledger.contradictions[0].between[1]: not a question id",
             "ledger.contradictions[0].between[2]: not a question id"])

    def test_between_is_optional(self):
        self.assertEqual(
            self.with_ledger({"contradictions": [{"id": "CON-1", "text": "x"}]}), [])

    def test_only_a_contradiction_is_between_anything(self):
        """A decision carrying a `between` is not a shape the page reads, and
        complaining about it would send the author to fix a line that works."""
        self.assertEqual(
            self.with_ledger({"decisions": [{"id": "DEC-1", "between": "Q-1"}]}), [])

    def test_a_key_the_ledger_does_not_define_is_left_alone(self):
        """A shape check, not a vocabulary: the four sections are what the
        page draws, and rejecting everything else would make any addition to
        the wire format a breaking change."""
        self.assertEqual(self.with_ledger({"notes": "anything at all"}), [])

    def test_every_problem_is_reported_not_just_the_first(self):
        """The same rule the question loop keeps. One problem per attempt is
        how a round takes four attempts to land."""
        self.assertEqual(
            sorted(self.with_ledger({"contradictions": "no",
                                     "decisions": [7],
                                     "assumptions": [{"text": "guessed"}]})),
            sorted(["ledger.contradictions: not a list",
                    "ledger.decisions[0]: not an object",
                    "ledger.assumptions[0]: id missing"]))

    def test_a_ledger_problem_is_reported_beside_a_question_problem(self):
        obj = a_round(question(title=""))
        obj["ledger"] = {"decisions": "DEC-014"}
        self.assertEqual(validate_round(obj),
                         ["questions[0]: title missing",
                          "ledger.decisions: not a list"])

    def test_a_ledger_problem_survives_the_questions_early_return(self):
        """questions-not-a-list used to return before anything else ran. A
        round broken in both places must report both, or fixing the questions
        reveals the ledger and the round takes two attempts instead of one."""
        self.assertEqual(
            validate_round({"round": 1, "questions": "nope",
                            "ledger": {"decisions": "DEC-014"}}),
            ["questions: missing or not a list", "ledger.decisions: not a list"])

    def test_validation_does_not_mutate_the_ledger_it_was_given(self):
        obj = a_round(question())
        obj["ledger"] = copy.deepcopy(self.LEDGER)
        before = copy.deepcopy(obj)
        validate_round(obj)
        self.assertEqual(obj, before)


class VocabularyTest(unittest.TestCase):
    """The constants are a wire contract shared with the browser and with the
    agent writing rounds. Reordering them silently rewrites error messages."""

    def test_importances_are_exactly_the_four_in_descending_order(self):
        self.assertEqual(IMPORTANCES,
                         ("REQUIRED", "IMPORTANT", "PREFERENCE", "OPTIONAL"))

    def test_types_are_exactly_the_four(self):
        self.assertEqual(TYPES, ("single", "multi", "text", "longtext"))

    def test_choice_types_are_exactly_the_two_that_carry_options(self):
        self.assertEqual(CHOICE_TYPES, ("single", "multi"))

    def test_choice_types_are_a_subset_of_types(self):
        for name in CHOICE_TYPES:
            self.assertIn(name, TYPES)


class AnswerStateNonObjectTest(unittest.TestCase):
    def test_a_bare_string_is_skipped(self):
        self.assertEqual(answer_state("yes"), "skipped")

    def test_a_bare_list_is_skipped(self):
        self.assertEqual(answer_state(["email"]), "skipped")

    def test_an_empty_dict_is_skipped(self):
        self.assertEqual(answer_state({}), "skipped")

    def test_zero_is_skipped(self):
        self.assertEqual(answer_state(0), "skipped")

    def test_false_is_skipped(self):
        self.assertEqual(answer_state(False), "skipped")


class AnswerStateContentTest(unittest.TestCase):
    """Where the line between answered and skipped actually falls."""

    def test_a_single_choice_sent_as_a_string_is_answered(self):
        """The browser may send one radio value as a string rather than a
        one-element list. The brief's suite never exercised this branch."""
        self.assertEqual(answer_state({"choice": "email"}), "answered")

    def test_a_whitespace_only_string_choice_is_skipped(self):
        self.assertEqual(answer_state({"choice": "   "}), "skipped")

    def test_an_empty_string_choice_is_skipped(self):
        self.assertEqual(answer_state({"choice": ""}), "skipped")

    def test_a_choice_list_holding_one_empty_string_is_skipped(self):
        """The second half of the phantom answer. Validation now keeps blank
        option values off the wire, but a hand-posted round could still send
        one, and a selection with nothing in it settles nothing."""
        self.assertEqual(answer_state({"choice": [""]}), "skipped")

    def test_a_choice_list_of_nothing_but_blanks_is_skipped(self):
        self.assertEqual(answer_state({"choice": ["", "   ", "\n\t"]}),
                         "skipped")

    def test_a_real_entry_among_blanks_is_still_an_answer(self):
        """The over-correction to guard against: dropping a selection the user
        really made because a blank rode along beside it."""
        self.assertEqual(answer_state({"choice": ["", "email"]}), "answered")
        self.assertEqual(answer_state({"choice": ["email", ""]}), "answered")

    def test_a_blank_choice_list_does_not_hide_a_real_other(self):
        self.assertEqual(answer_state({"choice": [""], "other": "passkeys"}),
                         "answered")

    def test_a_choice_that_is_neither_list_nor_string_is_skipped(self):
        self.assertEqual(answer_state({"choice": 0}), "skipped")
        self.assertEqual(answer_state({"choice": {"value": "email"}}), "skipped")

    def test_whitespace_only_other_is_skipped(self):
        self.assertEqual(answer_state({"other": "   "}), "skipped")

    def test_an_empty_text_is_skipped(self):
        self.assertEqual(answer_state({"text": ""}), "skipped")

    def test_a_zero_typed_into_a_text_box_is_an_answer(self):
        """"0" is a real answer to "how many?". Anything testing truthiness of
        a parsed value rather than of the string would lose it."""
        self.assertEqual(answer_state({"text": "0"}), "answered")

    def test_a_non_string_text_is_not_an_answer(self):
        for value in (0, False, True, 1, ["yes"], {"a": 1}):
            self.assertEqual(answer_state({"text": value}), "skipped")

    def test_a_note_alongside_a_real_answer_does_not_change_it(self):
        self.assertEqual(answer_state({"note": "x", "choice": ["a"]}), "answered")

    def test_a_whitespace_only_note_is_still_not_an_answer(self):
        self.assertEqual(answer_state({"note": "   "}), "skipped")


class BlankIsWhatStripCallsBlankTest(unittest.TestCase):
    """Which codepoints count as nothing at all, named rather than assumed.

    `str.strip()` is the definition and this module is where the definition
    lives: count_open is what the agent is told, and the page's answerState
    mirrors THIS rather than the other way round. Six codepoints separate
    str.strip() from JavaScript's trim(), and each of them is a question one
    side would call answered while the other left it open -- so each is
    written down here, where the definition is, rather than left to whichever
    runtime happened to read the draft.
    """

    # Python strips these; JavaScript's trim() leaves them.
    STRIPPED_NOT_TRIMMED = ("\x1c", "\x1d", "\x1e", "\x1f", "\x85")
    # ...and the reverse: trim() removes the byte-order mark, strip() does not.
    BOM = "﻿"

    def test_the_separators_python_strips_are_blank_everywhere(self):
        for blank in self.STRIPPED_NOT_TRIMMED:
            for key in ("text", "other"):
                self.assertEqual(answer_state({key: blank}), "skipped", repr(blank))
            self.assertEqual(answer_state({"choice": blank}), "skipped", repr(blank))
            self.assertEqual(answer_state({"choice": [blank]}), "skipped", repr(blank))

    def test_a_byte_order_mark_is_content_because_strip_leaves_it(self):
        """Not obviously desirable read on its own -- a lone BOM is nobody's
        answer. It is what str.strip() does, and one side has to define blank:
        a page calling this question answered while count_open called it open
        is a question the user answered and Claude asks again."""
        self.assertEqual(answer_state({"text": self.BOM}), "answered")
        self.assertEqual(answer_state({"other": self.BOM}), "answered")
        self.assertEqual(answer_state({"choice": self.BOM}), "answered")
        self.assertEqual(answer_state({"choice": [self.BOM]}), "answered")

    def test_a_real_answer_wearing_one_of_them_is_still_an_answer(self):
        """The over-correction to guard against: none of the six may swallow
        the answer it is sitting beside."""
        for odd in self.STRIPPED_NOT_TRIMMED + (self.BOM,):
            self.assertEqual(answer_state({"text": odd + "email" + odd}),
                             "answered", repr(odd))
            self.assertEqual(answer_state({"choice": [odd, "email"]}),
                             "answered", repr(odd))

    def test_blank_is_exactly_what_strip_removes(self):
        """Teeth, and the reason the page can mirror this at all: the rule is
        `str.strip()` and nothing hand-written beside it, so a codepoint list
        in the page can be checked against the language rather than against
        somebody's memory of it."""
        for text in ("", "﻿", " \t\n", "\x1c", "\x85", "email", "0", " "):
            self.assertEqual(answer_state({"text": text}) == "answered",
                             bool(text.strip()), repr(text))


class AnswerStateFlagTest(unittest.TestCase):
    """The flags, their precedence, and their strictness.

    Delegation is the state the whole UI exists to record: it must be produced
    only by an explicit JSON `true`, and it must never be produced by accident.
    """

    def test_delegation_beats_an_explicit_skip(self):
        self.assertEqual(answer_state({"delegated": True, "skipped": True}),
                         "delegated")

    def test_delegation_beats_text_typed_before_the_button_was_pressed(self):
        self.assertEqual(answer_state({"delegated": True, "text": "maybe email"}),
                         "delegated")

    def test_an_explicit_skip_discards_a_stale_answer(self):
        """Pressing skip after typing means skip. If the content checks ran
        first, the stale text would win and the question would never be asked
        again."""
        self.assertEqual(answer_state({"skipped": True, "text": "old draft"}),
                         "skipped")
        self.assertEqual(answer_state({"skipped": True, "choice": ["a"]}),
                         "skipped")

    def test_a_false_delegation_flag_does_not_delegate(self):
        self.assertEqual(answer_state({"delegated": False, "text": "yes"}),
                         "answered")

    def test_a_false_skip_flag_does_not_skip(self):
        self.assertEqual(answer_state({"skipped": False, "choice": ["a"]}),
                         "answered")

    def test_a_truthy_non_boolean_delegation_flag_does_not_delegate(self):
        """Fail-safe direction: a malformed flag must not manufacture a
        Delegated Decision the user never made. Ask again instead."""
        self.assertEqual(answer_state({"delegated": "yes", "text": "email"}),
                         "answered")
        self.assertEqual(answer_state({"delegated": 1}), "skipped")

    def test_a_truthy_non_boolean_skip_flag_does_not_discard_an_answer(self):
        self.assertEqual(answer_state({"skipped": "true", "text": "email"}),
                         "answered")


class FourStatesTest(unittest.TestCase):
    """The distinction this module exists for: a markdown file could not tell
    delegated from skipped, and conflating them either nags the user about a
    decision they handed over or silently drops one they expected recorded."""

    def test_delegated_is_not_the_same_state_as_skipped(self):
        self.assertNotEqual(answer_state({"delegated": True}),
                            answer_state({"skipped": True}))

    def test_delegated_is_not_the_same_state_as_answered(self):
        self.assertNotEqual(answer_state({"delegated": True}),
                            answer_state({"text": "email"}))

    def test_absent_and_explicitly_skipped_collapse_to_one_state(self):
        """Four states in, three names out: absent means the same thing as
        skipped, and callers must not have to tell them apart."""
        self.assertEqual(answer_state(None), answer_state({"skipped": True}))

    def test_no_input_ever_produces_a_fourth_name(self):
        inputs = [None, {}, "x", ["x"], 0, {"note": "n"}, {"text": "t"},
                  {"choice": []}, {"choice": ["a"]}, {"choice": "a"},
                  {"other": "o"}, {"skipped": True}, {"delegated": True},
                  {"delegated": True, "skipped": True, "text": "t"}]
        for ans in inputs:
            self.assertIn(answer_state(ans),
                          ("answered", "delegated", "skipped"))


class OpenAtItsOwnLevelTest(unittest.TestCase):
    """Each importance is counted at its own level. No level is special-cased,
    and none is silently zeroed -- which is what the brief's own literal did to
    OPTIONAL."""

    def setUp(self):
        self.round = a_round(
            question(id="Q-r", importance="REQUIRED"),
            question(id="Q-i", importance="IMPORTANT"),
            question(id="Q-p", importance="PREFERENCE"),
            question(id="Q-o", importance="OPTIONAL"),
        )

    def test_one_unanswered_question_per_level_is_one_open_per_level(self):
        self.assertEqual(count_open(self.round, {}),
                         {"REQUIRED": 1, "IMPORTANT": 1,
                          "PREFERENCE": 1, "OPTIONAL": 1})

    def test_an_unanswered_optional_question_is_open(self):
        self.assertEqual(count_open(self.round, {})["OPTIONAL"], 1)

    def test_an_unanswered_preference_question_is_open(self):
        self.assertEqual(count_open(self.round, {})["PREFERENCE"], 1)

    def test_answering_one_level_leaves_the_others_alone(self):
        counts = count_open(self.round, {"Q-r": {"text": "yes"}})
        self.assertEqual(counts, {"REQUIRED": 0, "IMPORTANT": 1,
                                  "PREFERENCE": 1, "OPTIONAL": 1})

    def test_answering_everything_closes_every_level(self):
        answers = dict((q["id"], {"text": "yes"})
                       for q in self.round["questions"])
        self.assertEqual(count_open(self.round, answers),
                         {"REQUIRED": 0, "IMPORTANT": 0,
                          "PREFERENCE": 0, "OPTIONAL": 0})


class CountsShapeTest(unittest.TestCase):
    def test_the_counts_always_carry_all_four_levels(self):
        self.assertEqual(set(count_open({"round": 1, "questions": []}, {})),
                         set(IMPORTANCES))

    def test_each_call_returns_a_fresh_dict(self):
        """A module-level counts dict would accumulate across calls and be
        wrong from the second round onward."""
        round_obj = a_round(question(id="Q-1"))
        first = count_open(round_obj, {})
        first["REQUIRED"] = 99
        self.assertEqual(count_open(round_obj, {})["REQUIRED"], 1)

    def test_a_missing_round_and_missing_answers_count_nothing(self):
        self.assertEqual(count_open(None, None),
                         dict((level, 0) for level in IMPORTANCES))
        self.assertEqual(count_answered(None, None), 0)

    def test_answers_of_none_are_treated_as_no_answers(self):
        """Not the same as `count_open(None, None)`: an empty round never
        reaches the answers lookup at all, so that call cannot tell whether
        the None default exists. This one has questions to look up."""
        round_obj = a_round(question(id="Q-1"), question(id="Q-2"))
        self.assertEqual(count_open(round_obj, None)["REQUIRED"], 2)
        self.assertEqual(count_answered(round_obj, None), 0)

    def test_a_round_without_a_questions_key_counts_nothing(self):
        self.assertEqual(count_open({"round": 1}, {}),
                         dict((level, 0) for level in IMPORTANCES))
        self.assertEqual(count_answered({"round": 1}, {}), 0)


class MalformedQuestionCountsTest(unittest.TestCase):
    """Counting runs on rounds that validation may not have blessed."""

    def test_an_unknown_importance_is_ignored_rather_than_crashing(self):
        round_obj = a_round(question(id="Q-1", importance="CRITICAL"))
        self.assertEqual(count_open(round_obj, {}),
                         dict((level, 0) for level in IMPORTANCES))

    def test_a_missing_importance_is_ignored_rather_than_crashing(self):
        q = question(id="Q-1")
        del q["importance"]
        self.assertEqual(count_open(a_round(q), {}),
                         dict((level, 0) for level in IMPORTANCES))

    def test_an_unknown_importance_never_adds_a_fifth_key(self):
        round_obj = a_round(question(id="Q-1", importance="CRITICAL"))
        self.assertEqual(set(count_open(round_obj, {})), set(IMPORTANCES))

    def test_a_question_with_no_id_can_never_be_settled(self):
        """It cannot be looked up, so it stays open rather than matching some
        other question's answer."""
        q = {"importance": "REQUIRED", "title": "Auth?", "type": "text"}
        round_obj = a_round(q)
        answers = {"Q-1": {"text": "yes"}, "": {"text": "yes"}}
        self.assertEqual(count_open(round_obj, answers)["REQUIRED"], 1)
        self.assertEqual(count_answered(round_obj, answers), 0)

    def test_a_duplicated_id_settles_both_entries(self):
        """Counting trusts validate_round to have rejected the duplicate; this
        pins what happens if it is ever called anyway."""
        round_obj = a_round(question(id="Q-1"), question(id="Q-1"))
        answers = {"Q-1": {"text": "yes"}}
        self.assertEqual(count_answered(round_obj, answers), 2)
        self.assertEqual(count_open(round_obj, answers)["REQUIRED"], 0)


class CountsUseAnswerStateTest(unittest.TestCase):
    """Both counters must ask answer_state, not merely whether a key exists in
    the answers dict. The browser posts a record for every question it renders,
    including the ones left blank."""

    def setUp(self):
        self.round = a_round(question(id="Q-1"), question(id="Q-2"))

    def test_an_empty_answer_record_leaves_the_question_open(self):
        answers = {"Q-1": {}, "Q-2": {"choice": [], "note": "later"}}
        self.assertEqual(count_open(self.round, answers)["REQUIRED"], 2)
        self.assertEqual(count_answered(self.round, answers), 0)

    def test_a_whitespace_only_answer_leaves_the_question_open(self):
        answers = {"Q-1": {"text": "   "}, "Q-2": {"text": "\n\t"}}
        self.assertEqual(count_open(self.round, answers)["REQUIRED"], 2)
        self.assertEqual(count_answered(self.round, answers), 0)

    def test_an_explicit_skip_leaves_the_question_open(self):
        answers = {"Q-1": {"skipped": True}, "Q-2": {"skipped": True}}
        self.assertEqual(count_open(self.round, answers)["REQUIRED"], 2)
        self.assertEqual(count_answered(self.round, answers), 0)

    def test_delegation_settles_a_question_for_both_counters(self):
        answers = {"Q-1": {"delegated": True}}
        self.assertEqual(count_open(self.round, answers)["REQUIRED"], 1)
        self.assertEqual(count_answered(self.round, answers), 1)

    def test_count_answered_ignores_importance_entirely(self):
        round_obj = a_round(question(id="Q-1", importance="OPTIONAL"),
                            question(id="Q-2", importance="CRITICAL"))
        answers = {"Q-1": {"text": "y"}, "Q-2": {"text": "y"}}
        self.assertEqual(count_answered(round_obj, answers), 2)

    def test_answered_plus_open_accounts_for_every_question(self):
        """The invariant the UI's progress display rests on: with every
        importance recognised, nothing is counted twice and nothing vanishes."""
        round_obj = a_round(
            question(id="Q-1", importance="REQUIRED"),
            question(id="Q-2", importance="IMPORTANT"),
            question(id="Q-3", importance="PREFERENCE"),
            question(id="Q-4", importance="OPTIONAL"),
            question(id="Q-5", importance="REQUIRED"),
        )
        answers = {"Q-1": {"text": "yes"}, "Q-2": {"delegated": True},
                   "Q-3": {"skipped": True}}
        total = len(round_obj["questions"])
        self.assertEqual(
            count_answered(round_obj, answers)
            + sum(count_open(round_obj, answers).values()),
            total,
        )


if __name__ == "__main__":
    unittest.main()
