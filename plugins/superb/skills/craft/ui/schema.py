"""Validation for the craft UI wire format.

Four answer states are kept deliberately distinct: answered, delegated
("I don't care, record it and stop asking"), skipped ("ask me again"), and
absent, which means the same as skipped.
"""
from __future__ import annotations

IMPORTANCES = ("REQUIRED", "IMPORTANT", "PREFERENCE", "OPTIONAL")
TYPES = ("single", "multi", "text", "longtext")
CHOICE_TYPES = ("single", "multi")

# The ledger's four sections, each a list of entries the page renders as its
# own kind of line. Anything else under `ledger` is left alone: this is a
# shape check, not a vocabulary.
LEDGER_SECTIONS = ("contradictions", "decisions", "delegated", "assumptions")
# The fields a ledger line puts on screen. Absent is fine -- a decision with
# no title is a bare id, which is legible -- but a dict or a list where a
# sentence belongs renders as "[object Object]" in the user's sidebar.
LEDGER_TEXT_FIELDS = ("text", "title", "summary")


def _validate_ledger(ledger, errors):
    """Append every problem in the round's `ledger` to `errors`.

    An absent ledger is valid and is the ordinary case: most rounds have
    nothing recorded yet. What is not valid is a section that is not a list.
    The page iterates all four of them, and a string iterates -- by character
    -- rather than raising, so `contradictions: "none"` renders four hundred
    empty boxes and a contradiction's `between: "Q-1"` throws outright.

    The page defends itself against all of this (renderLedger is total), and
    that is not a reason to stay quiet here: the page can only decline to
    draw what it was given, while the agent that wrote the round is the one
    who can fix it, and it only learns from this list.
    """
    if ledger is None:
        return
    if not isinstance(ledger, dict):
        errors.append("ledger: not an object")
        return

    for section in LEDGER_SECTIONS:
        entries = ledger.get(section)
        if entries is None:
            continue
        where = "ledger.{}".format(section)
        if not isinstance(entries, list):
            errors.append("{}: not a list".format(where))
            continue
        for index, entry in enumerate(entries):
            at = "{}[{}]".format(where, index)
            if not isinstance(entry, dict):
                errors.append("{}: not an object".format(at))
                continue

            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                errors.append("{}: id missing".format(at))
            for field in LEDGER_TEXT_FIELDS:
                if field in entry and not isinstance(entry[field], str):
                    errors.append("{}.{}: not a string".format(at, field))

            if section != "contradictions":
                continue
            # Only a contradiction is between anything, and each reference is
            # a question id the page turns into a jump link.
            between = entry.get("between")
            if between is None:
                continue
            if not isinstance(between, list):
                errors.append("{}.between: not a list".format(at))
                continue
            for j, ref in enumerate(between):
                if not isinstance(ref, str) or not ref:
                    errors.append("{}.between[{}]: not a question id".format(at, j))


def validate_round(obj, expected_round=None):
    """Return a list of human-readable problems. Empty list means valid.

    `expected_round`, when given, is the round number the CALLER knows this
    object to be -- for both callers in this tool, the number in the filename
    it was just read from. Nothing else ties the two together: the page picks
    a round by filename, so a `round-004.questions.json` carrying `"round": 2`
    is served as round 2, and every PATCH and POST the page then sends
    addresses round 2 -- overwriting an already-submitted `.answers.json`.

    It is optional and defaults to not checking, because a round number is a
    fact about a FILE and this function validates a wire object. Most callers
    -- every test here, and any future one holding a round that never came
    from a file -- have no filename to be consistent with, and a required
    parameter would make them invent one. The two callers that DO know it
    pass it, which is where the check has any meaning.
    """
    if not isinstance(obj, dict):
        return ["round must be a JSON object"]

    errors = []
    if not isinstance(obj.get("round"), int):
        errors.append("round: missing or not an integer")
    elif expected_round is not None and obj["round"] != expected_round:
        # Reported, not corrected. The agent that wrote the file is the one
        # who can fix it, and guessing which of the two numbers was meant
        # would serve the user a round nobody wrote.
        errors.append("round: says {}, but this is round {}".format(
            obj["round"], expected_round))

    questions = obj.get("questions")
    if not isinstance(questions, list):
        errors.append("questions: missing or not a list")
    else:
        _validate_questions(questions, errors)

    # The round's own voice, and the whole content of a closing round: an
    # empty `questions` list plus the note saying there is nothing left to
    # ask. Optional on every round, and null reads as absent -- the rule the
    # ledger already keeps -- because most rounds say everything they have to
    # say in their questions.
    #
    # What it may not be is a non-string. The page renders it as textContent,
    # where a dict or a list arrives as "[object Object]": the same failure
    # LEDGER_TEXT_FIELDS is checked for, in the one field a user reads as a
    # sentence addressed to them.
    note = obj.get("note")
    if note is not None and not isinstance(note, str):
        errors.append("note: not a string")

    # After the questions and outside their branch: a round whose questions
    # are unusable still has a ledger, and reporting one problem per fix is
    # how a round takes four attempts to land.
    _validate_ledger(obj.get("ledger"), errors)
    return errors


def _validate_questions(questions, errors):
    """Append every problem in the round's questions to `errors`."""
    seen = set()
    for index, question in enumerate(questions):
        where = "questions[{}]".format(index)
        if not isinstance(question, dict):
            errors.append("{}: not an object".format(where))
            continue

        qid = question.get("id")
        if not isinstance(qid, str) or not qid:
            errors.append("{}: id missing".format(where))
        elif qid in seen:
            errors.append("{}: duplicate id {}".format(where, qid))
        else:
            seen.add(qid)

        if question.get("importance") not in IMPORTANCES:
            errors.append(
                "{}: importance must be one of {}".format(where, "/".join(IMPORTANCES))
            )

        title = question.get("title")
        if not isinstance(title, str) or not title:
            errors.append("{}: title missing".format(where))

        qtype = question.get("type")
        if qtype not in TYPES:
            errors.append("{}: type must be one of {}".format(where, "/".join(TYPES)))
        elif qtype in CHOICE_TYPES:
            options = question.get("options")
            if not isinstance(options, list) or not options:
                errors.append(
                    "{}: type {} requires a non-empty options list".format(where, qtype)
                )
            else:
                for j, option in enumerate(options):
                    if not isinstance(option, dict) or not isinstance(option.get("value"), str):
                        errors.append("{}.options[{}]: needs a string value".format(where, j))
                    elif not option["value"].strip():
                        errors.append("{}.options[{}]: needs a non-blank value".format(where, j))


def _choice_has_content(entry):
    """Whether one entry of a `choice` list carries something to record.

    An empty or whitespace-only entry is nothing at all. Counting it as an
    answer would settle a question with no content in it, and the fold-in step
    would then write that emptiness into the brief as a real decision.
    """
    if isinstance(entry, str):
        return bool(entry.strip())
    return entry is not None


def answer_state(ans):
    """One of "answered", "delegated", "skipped"."""
    if not isinstance(ans, dict):
        return "skipped"
    if ans.get("delegated") is True:
        return "delegated"
    if ans.get("skipped") is True:
        return "skipped"
    choice = ans.get("choice")
    if isinstance(choice, list) and any(_choice_has_content(e) for e in choice):
        return "answered"
    if isinstance(choice, str) and choice.strip():
        return "answered"
    for key in ("text", "other"):
        value = ans.get(key)
        if isinstance(value, str) and value.strip():
            return "answered"
    return "skipped"


def count_open(round_obj, answers):
    """How many questions of each importance are still waiting for the user.

    Precondition: the round must be one `validate_round` accepted.
    """
    answers = answers or {}
    counts = dict((level, 0) for level in IMPORTANCES)
    for question in (round_obj or {}).get("questions", []):
        importance = question.get("importance")
        if importance not in counts:
            continue
        if answer_state(answers.get(question.get("id"))) == "skipped":
            counts[importance] += 1
    return counts


def count_answered(round_obj, answers):
    """Answered or deliberately delegated — both are settled.

    Precondition: the round must be one `validate_round` accepted.
    """
    answers = answers or {}
    settled = 0
    for question in (round_obj or {}).get("questions", []):
        if answer_state(answers.get(question.get("id"))) in ("answered", "delegated"):
            settled += 1
    return settled
