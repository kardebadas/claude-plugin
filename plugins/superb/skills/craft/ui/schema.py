"""Validation for the craft UI wire format.

Four answer states are kept deliberately distinct: answered, delegated
("I don't care, record it and stop asking"), skipped ("ask me again"), and
absent, which means the same as skipped.
"""
from __future__ import annotations

IMPORTANCES = ("REQUIRED", "IMPORTANT", "PREFERENCE", "OPTIONAL")
TYPES = ("single", "multi", "text", "longtext")
CHOICE_TYPES = ("single", "multi")


def validate_round(obj):
    """Return a list of human-readable problems. Empty list means valid."""
    if not isinstance(obj, dict):
        return ["round must be a JSON object"]

    errors = []
    if not isinstance(obj.get("round"), int):
        errors.append("round: missing or not an integer")

    questions = obj.get("questions")
    if not isinstance(questions, list):
        errors.append("questions: missing or not a list")
        return errors

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

    return errors


def answer_state(ans):
    """One of "answered", "delegated", "skipped"."""
    if not isinstance(ans, dict):
        return "skipped"
    if ans.get("delegated") is True:
        return "delegated"
    if ans.get("skipped") is True:
        return "skipped"
    choice = ans.get("choice")
    if isinstance(choice, list) and choice:
        return "answered"
    if isinstance(choice, str) and choice.strip():
        return "answered"
    for key in ("text", "other"):
        value = ans.get(key)
        if isinstance(value, str) and value.strip():
            return "answered"
    return "skipped"


def count_open(round_obj, answers):
    """How many questions of each importance are still waiting for the user."""
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
    """Answered or deliberately delegated — both are settled."""
    answers = answers or {}
    settled = 0
    for question in (round_obj or {}).get("questions", []):
        if answer_state(answers.get(question.get("id"))) in ("answered", "delegated"):
            settled += 1
    return settled
