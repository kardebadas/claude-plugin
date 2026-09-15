"""Durable state for superb:pipeline-auto. Python standard library only.

The tracker is the authority. Conversation memory never is. Every durable
transition in this run goes through this module.

This module does not interoperate with superb:pipeline. `pipeline-run/v1` and
`pipeline-run/v2` are foreign schemas and there is no migration in either
direction — not here, not later.
"""

from __future__ import annotations

from pathlib import Path

SCHEMA = "pipeline-auto/v1"
MARKER = f"<!-- {SCHEMA} -->"
TITLE = "# Pipeline Auto — Progress Tracker"

#: The grounding rungs, lowest first. These names are schema constants, not run
#: configuration: a controller that could edit the enum or the floor could lower
#: its own adoption bar. P03 builds its ``RUNGS`` value map over these exact
#: names and owns ``ADOPTION_FLOOR``; neither is redefined there.
RUNG_NAMES = (
    "speculation",
    "engineering-judgement",
    "convention-cited",
    "code-evidenced",
    "specified",
)


class TrackerError(Exception):
    """Root of every durable-state failure in pipeline-auto."""


class ForeignSchemaError(TrackerError):
    """Not a pipeline-auto/v1 tracker: read-only stop, nothing was changed."""


class TrackerValidationError(TrackerError):
    """A semantically impossible state: read-only stop, nothing was changed."""


class TrackerWriteError(TrackerError):
    """A write failed before it could take effect. Nothing changed."""


class UpdateOutcomeUncertain(TrackerError):
    """The tracker was replaced, then a durability step failed.

    The update may or may not survive a crash. A caller must reconcile
    ``revision`` and ``last_transition`` before retrying; a blind retry can
    double-apply.
    """


class PlanMetadataError(TrackerError):
    """A phase-plan metadata comment violates its grammar.

    Defined here so every phase raises one exception family. The phase-plan
    metadata reader itself belongs to the phase that consumes ``review_class``.
    """


_RUN_KEYS = (
    "run_id", "schema", "base_commit", "target_branch", "worker_limit",
    "agent_dispatch_count", "spec", "master_plan", "phase_plans", "decisions",
    "findings", "completeness_proposals", "revision", "last_transition",
)

_STAGE_HEADER = ("Stage", "Stage State", "Next Action")
_INTENT_HEADER = ("ID", "Kind", "State", "Owner", "Result", "Conflicts")
_QUESTION_HEADER = ("ID", "Origin", "Slot", "State", "Decision")
_QUORUM_HEADER = (
    "QID", "Axis", "Phase", "State", "Owners", "Payload Digest",
    "Context Digest", "Responses", "Depth", "Rung", "Outcome", "Decision",
)
_ESCALATION_HEADER = ("ID", "QID", "Blast", "State", "Batch", "Resolution")
#: ``Decisions`` carries the decision ids a task's plan cites. It is what lets
#: provisional taint cross a phase boundary: without it the closure stops at the
#: phase that raised the decision and a later task built on it goes unmarked.
_TASK_HEADER = (
    "ID", "Phase", "Kind", "State", "Owner", "Attempt", "Result", "Checkpoints",
    "Source Ref", "Commits", "Artifacts", "Integration", "Verification",
    "Question", "Decisions", "Provisional",
)
#: ``Intensity`` is per review ROW, not per task: an upward ratchet is then
#: visible in the review history itself rather than only in the phase record.
_TASK_REVIEW_HEADER = (
    "Task", "Round", "Intensity", "State", "Reviewer", "Package", "Report",
    "Critical", "Important", "Minor", "Adversarial", "Adversarial Verdict",
    "Open", "Evidence",
)
_FIX_ROUND_HEADER = (
    "Scope", "Round", "State", "Fixer", "Findings", "Commits", "Verification",
    "Re-review", "Remaining",
)
_PHASE_HEADER = (
    "ID", "State", "Verification", "Review Class", "Class Source", "Ratchet", "Gate",
)
_GATE_HEADER = (
    "ID", "Type", "Phase", "State", "Base", "Head", "Assignments", "Reports",
    "Verification", "Findings",
)

#: (heading, tracker key, column header). ``## Run`` is a key/value table rather
#: than a row table, so it carries no row header.
_SECTIONS = (
    ("## Run", "run", None),
    ("## Stage", "stages", _STAGE_HEADER),
    ("## Intent", "intent", _INTENT_HEADER),
    ("## Questions", "questions", _QUESTION_HEADER),
    ("## Quorum", "quorum", _QUORUM_HEADER),
    ("## Escalations", "escalations", _ESCALATION_HEADER),
    ("## Tasks", "tasks", _TASK_HEADER),
    ("## Task Review", "task_review", _TASK_REVIEW_HEADER),
    ("## Fix Rounds", "fix_rounds", _FIX_ROUND_HEADER),
    ("## Phases", "phases", _PHASE_HEADER),
    ("## Gates", "gates", _GATE_HEADER),
)

_HEADINGS = tuple(heading for heading, _, _ in _SECTIONS)


#: Every id grammar in this module states itself, rather than being compiled by
#: ``re``. The import allowlist the test suite holds is a capability boundary,
#: not a convenience list, and a regex engine bought nothing these two shapes
#: cannot say directly: a leading character class plus a trailing one, and a
#: fixed prefix plus ASCII digits. Both grammars keep ``.fullmatch`` as their
#: one method, so a caller — including the later P02 tasks that already spell
#: ``_TOKEN.fullmatch(value)`` — cannot tell the difference at the call site.
class _CharClass:
    """``[<head>][<tail>]*``: one leading character, then any number more."""

    __slots__ = ("_head", "_tail")

    def __init__(self, head: str, tail: str) -> None:
        self._head = frozenset(head)
        self._tail = frozenset(tail)

    def fullmatch(self, value: str) -> bool:
        return (bool(value) and value[0] in self._head
                and all(character in self._tail for character in value[1:]))


class _Numbered:
    """``<prefix><digits>``: ``H-3``, ``E-12``, ``C-001``.

    ``isdigit`` alone is not the ``[0-9]`` the grammar means — it is true of
    ``'٣'`` and ``'³'`` too, and an id spelled with those renders back into the
    tracker looking like a decision id that nothing downstream can match. The
    ``isascii`` conjunct is what narrows it to the ten characters intended.
    """

    __slots__ = ("_prefix",)

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def fullmatch(self, value: str) -> bool:
        digits = value[len(self._prefix):]
        return (value.startswith(self._prefix) and bool(digits)
                and digits.isascii() and digits.isdigit())


_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

#: The general free-token grammar: a descriptive cell nothing branches on, held
#: to "a word, not prose" so a token list stays a token list. It is deliberately
#: wide — an axis name, a path fragment, a version — and deliberately excludes
#: the space, which is what separates a token from a sentence.
_TOKEN = _CharClass(_ALNUM, _ALNUM + "._/@:+-")


def _field(column: str) -> str:
    """Map a column header to its dict key: 'Re-review' -> 're_review'."""
    return column.lower().replace(" ", "_").replace("-", "_")


def _csv(value: str) -> tuple[str, ...]:
    return () if value == "-" else tuple(part.strip() for part in value.split(","))


def _cells(line: str) -> tuple[str, ...]:
    if not line.startswith("|") or not line.endswith("|"):
        raise TrackerValidationError("a table row must start and end with '|'")
    values = tuple(part.strip() for part in line[1:-1].split("|"))
    if any(not value for value in values):
        raise TrackerValidationError("a table cell is empty; absence is spelled '-'")
    return values


def _table(section: list[str], header: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    #: This is the one place a blank line is judged. ``_sections`` has already
    #: taken the single separator line off every section that is followed by a
    #: heading; every blank line still standing — inside a table, or left at
    #: end of file where the last section has no separator to give up — is
    #: refused here. Absorbing one would let a tracker parse and then render to
    #: different bytes, the exact asymmetry this format exists to exclude. The
    #: check leads ``_cells`` on purpose: ``_cells`` would also reject a blank
    #: line, but as a row missing its pipes, which is not what went wrong.
    content = section
    if any(not line for line in content):
        #: The words, not the verdict: a section made only of blank lines has
        #: no table for a blank line to be inside of, and naming one sends the
        #: reader looking for a table that was never there. This is not the
        #: deleted end-of-file guard coming back — no input's fate changes, the
        #: same raise fires on the same line and only chooses its own wording.
        raise TrackerValidationError(
            "a blank line inside a table" if any(content) else "a section with no table")
    if len(content) < 2 or _cells(content[0]) != header:
        raise TrackerValidationError(f"expected table header {header!r}")
    separator = _cells(content[1])
    if len(separator) != len(header) or any(value != "---" for value in separator):
        raise TrackerValidationError("invalid table separator")
    rows = tuple(_cells(line) for line in content[2:])
    if any(len(row) != len(header) for row in rows):
        raise TrackerValidationError("a table row does not match the header width")
    return rows


def _sections(text: str) -> dict[str, list[str]]:
    lines = text.splitlines()
    if not text.endswith("\n") or lines[:2] != [MARKER, TITLE]:
        raise TrackerValidationError("invalid marker, title, or missing terminal newline")
    positions = []
    for heading in _HEADINGS:
        matches = [index for index, line in enumerate(lines) if line == heading]
        if len(matches) != 1:
            raise TrackerValidationError(f"expected exactly one {heading!r} section")
        positions.append(matches[0])
    if positions != sorted(positions) or [
        line for line in lines if line.startswith("## ")
    ] != list(_HEADINGS):
        raise TrackerValidationError("unknown, missing, or reordered section")
    #: The head of the file obeys the same rule as every other section break:
    #: exactly one blank line, no content. Checking only for content would let
    #: a no-gap or a two-gap tracker parse and then render to different bytes.
    if lines[2:positions[0]] != [""]:
        raise TrackerValidationError(
            "expected exactly one blank line between the title and the first section")
    sections = {}
    for index, heading in enumerate(_HEADINGS):
        last = index + 1 == len(positions)
        body = lines[positions[index] + 1:(
            len(lines) if last else positions[index + 1]
        )]
        # Exactly one blank line separates a section from the next heading.
        # Taking that one line here — rather than filtering blanks in `_table` —
        # is what lets a table reject every remaining blank line. The final
        # section has no following heading, so nothing is taken off it and a
        # stray blank at end of file reaches `_table` like any other: there is
        # no separate end-of-file guard, because a second one could only
        # disagree with the first.
        if not last:
            if not body or body[-1]:
                raise TrackerValidationError(
                    f"expected one blank line at the end of {heading!r}")
            body = body[:-1]
        sections[heading] = body
    return sections


def _key_values(section: list[str], keys: tuple[str, ...]) -> dict[str, str]:
    rows = _table(section, ("Field", "Value"))
    if tuple(row[0] for row in rows) != keys:
        raise TrackerValidationError("run field missing, duplicated, unknown, or reordered")
    return {row[0]: row[1] for row in rows}


def parse_tracker(text: str) -> dict:
    """Parse the one supported tracker format into plain dicts of plain strings."""
    sections = _sections(text)
    tracker: dict = {"run": _key_values(sections["## Run"], _RUN_KEYS)}
    for heading, key, header in _SECTIONS[1:]:
        fields = tuple(_field(column) for column in header)
        tracker[key] = [
            dict(zip(fields, row)) for row in _table(sections[heading], header)
        ]
    _validate_tracker_semantics(tracker)
    return tracker


#: The twelve stages of a run, in order. Every tracker carries all twelve rows
#: at all times: a stage that has no row has no state, and a state nobody wrote
#: down is one a resuming controller cannot read back.
STAGES = tuple(f"{index:02d}" for index in range(1, 13))

#: The only stage states, in the order a stage moves through them. The tuple is
#: also the sort key that defines "monotone", so its ORDER is load-bearing and
#: not merely a membership set.
_STAGE_STATES = ("complete", "active", "pending")


def _validate_stages(tracker: dict) -> None:
    """Stages run complete*, then at most one active, then pending*.

    This ordering is the whole recovery story for stages 01-07, whose outputs
    Git cannot reconstruct and the task table never mentions. A tracker showing
    stage 01 pending while stage 02 is active would let a resuming controller
    re-dispatch the intent readers, produce a different brief, and fork the run
    from its own history with nothing downstream able to notice.
    """
    stages = tracker["stages"]
    if tuple(row["stage"] for row in stages) != STAGES:
        raise TrackerValidationError(
            "## Stage must list stages 01..12 exactly once, in order")
    states = [row["stage_state"] for row in stages]
    #: Ahead of every check that sorts or counts by state, because an
    #: out-of-enum value reaches ``_STAGE_STATES.index`` as a bare ValueError:
    #: a caller branching on TrackerError would never see it, and a read-only
    #: stop that escapes its own exception family is not one.
    unknown = [state for state in states if state not in _STAGE_STATES]
    if unknown:
        raise TrackerValidationError(f"unknown stage state {unknown[0]!r}")
    #: Two actives are monotone under the sort below, so the ordering check
    #: alone accepts them. Cardinality is a separate fact and needs its own say.
    if states.count("active") > 1:
        raise TrackerValidationError("at most one stage may be active")
    if states != sorted(states, key=_STAGE_STATES.index):
        raise TrackerValidationError(
            "stage states must run complete*, then at most one active, then pending*"
        )
    #: A stage table with nothing active and work still pending is monotone, so
    #: every check above waves it through — and then ``derive_next_action`` has
    #: no row to read an action from and no grounds to report the run complete.
    #: The tracker must not be able to hold a shape the controller cannot act
    #: on, so the shape is refused here rather than diagnosed one layer later:
    #: a transition is the unit at which state is legal, and every specified
    #: writer closes one stage and opens the next in a single ``mutate``, so no
    #: legal run ever passes through this window. The one table with nothing
    #: active is the terminal one, in which all twelve rows read ``complete``.
    if "active" not in states and states.count("complete") != len(STAGES):
        raise TrackerValidationError(
            "no stage is active and stages remain pending: a stage closes only as "
            "its successor opens, in the same transition")
    for row in stages:
        if row["stage_state"] == "active" and row["next_action"] == "-":
            raise TrackerValidationError("the active stage must name its next action")
        if row["stage_state"] != "active" and row["next_action"] != "-":
            raise TrackerValidationError("only the active stage carries a next action")


#: ``## Intent`` is a fixed roster, not a list: three independent readings then
#: the one brief that reconciles them. Stage 01 dispatches exactly three
#: readers, and a count is never reduced to fit capacity, so the ORDER here is
#: the check — a membership test would pass two readers and a duplicate.
_INTENT_IDS = ("reader-1", "reader-2", "reader-3", "brief")
_INTENT_STATES = ("pending", "dispatched", "published", "frozen")

#: Ordered by rank, and the order is the rule. An unresolved intent conflict is
#: by definition higher blast radius than anything stage 02 synthesised, so it
#: takes the earlier of the four stage-03 slots.
_QUESTION_ORIGINS = ("intent-conflict", "synthesis")
_QUESTION_STATES = ("proposed", "asked", "answered")

_ESCALATION_STATES = ("queued", "asked", "answered", "halted")

#: A QUESTION's admissibility blast radius, and nothing else. The spec's closed
#: vocabulary, closed **because** adoption checks a blast radius against the
#: irreversible-axis list: an unenumerated value matches nothing on that list
#: and so passes the check by failing to be recognised. An open grammar there
#: would be a fail-open one layer down.
#:
#: Two different things are called "blast" and they must not share a validator.
#: An ESCALATION row's ``Blast`` column is the other one: a free token list of
#: the axes that escalation touches, joined from a quorum payload by
#: ``phase-03-quorum-contract.md:3089-3097`` and carrying values like
#: ``storage-engine`` or ``-``. It is descriptive, nothing branches on it, and
#: it is validated with ``_TOKEN`` below. Judging it with the closed vocabulary
#: fails CLOSED — a loud halt on a value a specified writer actually emits —
#: which is a different fault from the fail-open this tuple exists to prevent,
#: and not one this tuple can fix. The column that carries an admissibility
#: blast radius arrives with the quorum phase that owns it; this constant is a
#: schema constant meanwhile, like ``RUNG_NAMES``, and is not redefined there.
_BLAST_RADII = ("task", "phase", "run", "contract")

#: The one human gate is one ``AskUserQuestion`` call, and escalations batch
#: into the same call shape. Four is the platform's limit, not a policy dial.
_MAX_QUESTIONS = 4
_MAX_BATCH = 4

#: ``H-<n>`` is a human decision; ``Q-<qid>`` is a quorum's. Only the first may
#: answer a stage-03 question or an escalation, so the grammar — not merely
#: "some non-empty cell" — is what these sections are judged against.
_HUMAN_DECISION = _Numbered("H-")
_ESCALATION_ID = _Numbered("E-")
#: The id of one flagged, unresolved intent conflict. The ``Conflicts`` cell is
#: ``-`` or a comma-separated list of these and NOTHING else: a cell that took
#: prose would take ``resolved-by-controller``, which records a conflict the
#: run settled by itself in the one place the schema promises it never does.
_CONFLICT_ID = _Numbered("C-")


def _stage_state(tracker: dict, stage: str) -> str:
    """The state of one stage row.

    ``_validate_stages`` has already proven the twelve rows are exactly
    ``STAGES``, once each, in order, so this indexes rather than searches. A
    search that found nothing would raise ``StopIteration``, which inside a
    generator expression degrades into an unrelated ``RuntimeError`` — an
    escape from this module's exception family, which is what a read-only stop
    may never do.
    """
    return tracker["stages"][STAGES.index(stage)]["stage_state"]


def _conflict_ids(row: dict) -> tuple[str, ...]:
    """The conflict ids one ``Conflicts`` cell flags, grammar proven.

    ``-`` or a comma-separated list of ``C-<n>``. Nothing else, and in
    particular no prose: the cell is the only record that a disagreement
    between two readings of the user's own prompt is still open, and a writer
    able to put ``resolved`` or ``resolved-by-controller`` there records the
    run resolving a conflict it is forbidden to resolve — in the very cell that
    was supposed to make that impossible.
    """
    ids = _csv(row["conflicts"])
    for value in ids:
        if not _CONFLICT_ID.fullmatch(value):
            raise TrackerValidationError(
                f"a Conflicts cell is '-' or a comma-separated list of C-<n> ids; "
                f"{value!r} is neither — a conflict is flagged, never narrated")
    if len(set(ids)) != len(ids):
        raise TrackerValidationError(
            "the same conflict id is flagged twice in one Conflicts cell")
    return ids


def _validate_intent(tracker: dict) -> None:
    """Three readings, one reconciled brief, and a brief that freezes after 03.

    This section is the run's only record of what the user actually asked for.
    The three readings are independent on purpose and their conflicts are
    **flagged, never resolved**: a conflict quietly reconciled here is a
    requirement invented, and nothing downstream can tell an invented
    requirement from a read one.

    The table is fixed-shape like ``## Stage`` — empty before stage 01 opens,
    then all four rows at once, the brief sitting ``pending`` while the readers
    run. A partial roster is refused rather than read as "in progress", because
    a roster that may shrink is one a reconciler can satisfy with two readings.
    """
    rows = tracker["intent"]
    if not rows:
        return
    if tuple(row["id"] for row in rows) != _INTENT_IDS:
        raise TrackerValidationError(
            "## Intent carries exactly three readers then one brief; a count is "
            "never reduced to fit capacity")
    readers, brief = rows[:3], rows[3]
    if any(row["kind"] != "reader" for row in readers) or brief["kind"] != "brief":
        raise TrackerValidationError("an intent row's kind must match its identity")
    #: Ahead of every rule that branches on a state, for the same reason
    #: ``_validate_stages`` checks its enum first: an unknown state is neither
    #: published nor frozen, so each rule below would skip it in turn and the
    #: row would pass having been judged by nothing.
    unknown = [row["state"] for row in rows if row["state"] not in _INTENT_STATES]
    if unknown:
        raise TrackerValidationError(f"unknown intent state {unknown[0]!r}")
    if any(row["state"] == "frozen" for row in readers):
        raise TrackerValidationError(
            "only the reconciled brief freezes; a reading never earns immutability")
    for row in readers:
        if (row["state"] == "published") != (row["result"] != "-"):
            raise TrackerValidationError(
                "a reader publishes with its immutable result, or neither")
        if row["conflicts"] != "-":
            raise TrackerValidationError(
                "conflicts are flagged on the reconciled brief, never on a reader")
    #: Three readers, three READINGS. The roster check above proves the three
    #: ids are distinct and nothing else, so three rows citing one result file
    #: satisfy it — and that is one reading counted three times. Every conflict
    #: this section can flag is a disagreement BETWEEN readings; a roster that
    #: may collapse onto a single file can raise none, and the decorrelation
    #: the whole design rests on is gone with nothing downstream able to see it.
    results = [row["result"] for row in readers if row["result"] != "-"]
    if len(set(results)) != len(results):
        raise TrackerValidationError(
            "the three intent readings must be three distinct results; a result "
            "cited twice is one reading counted twice")
    #: Flagged, never resolved — so the cell that carries the flags is a list of
    #: ids, never prose. See ``_validate_intent_conflicts`` for the other half:
    #: an id flagged here and never asked at the gate.
    _conflict_ids(brief)
    if brief["state"] in ("published", "frozen"):
        if any(row["state"] != "published" for row in readers):
            raise TrackerValidationError(
                "the intent brief cannot publish before all three readers have")
        if brief["result"] == "-":
            raise TrackerValidationError("a published intent brief names its result")
    elif brief["result"] != "-":
        raise TrackerValidationError("an unpublished intent brief cannot claim a result")
    #: The brief is immutable *after* the gate, not on publication. Freezing it
    #: earlier seals the conflicts stage 03 exists to put to the user into the
    #: brief before the user is asked, reducing the one gate to a formality
    #: over an answer already chosen.
    if brief["state"] == "frozen" and _stage_state(tracker, "03") != "complete":
        raise TrackerValidationError(
            "the intent brief freezes only once stage 03 closes")


def _validate_questions(tracker: dict) -> None:
    """At most four stage-03 questions; intent conflicts take the earlier slots.

    These four answers are the only requirements the run may ever treat as
    unimpeachable, so which questions occupy the slots — and that a machine
    never supplies one of the answers — is what this section protects.
    """
    rows = tracker["questions"]
    if len(rows) > _MAX_QUESTIONS:
        raise TrackerValidationError(
            f"stage 03 asks at most {_MAX_QUESTIONS} questions in one call")
    if len({row["id"] for row in rows}) != len(rows):
        raise TrackerValidationError("duplicate question axis id")
    if [row["slot"] for row in rows] != [str(n) for n in range(1, len(rows) + 1)]:
        raise TrackerValidationError("question slots must be 1..n, in order")
    origins = [row["origin"] for row in rows]
    #: Before the ranking comparison below, which would otherwise hand an
    #: unknown origin to ``_QUESTION_ORIGINS.index`` and raise a bare
    #: ``ValueError`` — outside ``TrackerError``, so a caller branching on this
    #: module's own family never sees the stop.
    unknown = [origin for origin in origins if origin not in _QUESTION_ORIGINS]
    if unknown:
        raise TrackerValidationError(f"unknown question origin {unknown[0]!r}")
    if origins != sorted(origins, key=_QUESTION_ORIGINS.index):
        raise TrackerValidationError(
            "an unresolved intent conflict outranks any synthesised question and "
            "takes the earlier slot")
    for row in rows:
        if row["state"] not in _QUESTION_STATES:
            raise TrackerValidationError(f"unknown question state {row['state']!r}")
        if row["state"] == "answered":
            if not _HUMAN_DECISION.fullmatch(row["decision"]):
                raise TrackerValidationError(
                    "an answered stage-03 question records an H-<n> decision; a "
                    "quorum can never answer the one human gate")
        elif row["decision"] != "-":
            raise TrackerValidationError("only an answered question carries a decision")


def _validate_intent_conflicts(tracker: dict) -> None:
    """Every flagged intent conflict holds a stage-03 question slot.

    ``_validate_intent`` and ``_validate_questions`` each judge their own
    section and neither can see this: the brief may flag ``C-001, C-002,
    C-003`` while every question row reads ``Origin: synthesis``, and both
    sections pass. Stage 03 then closes, the brief freezes, and the run reports
    success with three conflicts recorded and none of them ever asked — a
    requirement invented, which is the exact failure ``## Intent`` exists to
    prevent.

    The ranking rule in ``_validate_questions`` is not this rule. It orders the
    conflict-derived questions that happen to exist; it cannot notice that none
    do. Here the set is POPULATED instead.

    CORRESPONDENCE, not cardinality. An ``intent-conflict`` question's ``ID`` IS
    the id of the conflict it puts to the human, and the two SETS — the ids
    flagged on the brief, the ids claimed by the conflict-derived questions —
    must be equal. Counting them was the hole: a brief flagging ``C-001,C-002``
    with two questions that both elaborate ``C-001`` balances exactly, and
    ``C-002`` is never asked. A matching total is not an answered conflict, and
    that shape is the original failure wearing a total that adds up — a flagged
    conflict the run settles by silence, which is a requirement invented.

    Naming the conflict costs ``## Questions`` nothing it was using. A question
    id is a free token there; no validator ties it to the ``Axis`` column of
    ``## Quorum`` or to anything else, so the id is available to carry the one
    correspondence the gate depends on.

    Timing is the whole of the gate. Stage 02 synthesises and stage 03 asks, so
    a conflict flagged while stage 03 is still open is simply one not yet
    asked. The moment stage 03 closes it is one that never will be, and that is
    where this refuses. A brief cannot freeze earlier than that either —
    ``_validate_intent`` already ties freezing to stage 03 closing — so this
    single trigger covers both halves of the brief's immutability.

    More than four conflicts is unsatisfiable rather than merely tight: the one
    human gate is one ``AskUserQuestion`` call of at most four questions, so a
    run holding five unresolved readings of the user's own prompt cannot legally
    close stage 03 at all. Halting loudly there is correct. The alternative is
    choosing which conflict to drop, and nothing in this run has the authority.
    """
    rows = tracker["intent"]
    if not rows:
        return
    conflicts = _csv(rows[3]["conflicts"])
    if _stage_state(tracker, "03") != "complete":
        return
    claims = [row["id"] for row in tracker["questions"]
              if row["origin"] == "intent-conflict"]
    #: Both directions are stated over the ids themselves. ``_conflict_ids`` has
    #: already refused a conflict flagged twice and ``_validate_questions`` a
    #: duplicated question id, so these two lists carry no repeats and membership
    #: is set equality — ordered here only so the diagnostic names the offending
    #: ids in the order the tracker records them, which is the order the operator
    #: reads them in.
    unasked = [conflict for conflict in conflicts if conflict not in claims]
    if unasked:
        raise TrackerValidationError(
            f"intent conflict(s) {', '.join(unasked)} flagged and never asked; "
            "stage 03 closes only once every unresolved conflict is claimed by "
            "the question whose ID names it")
    unflagged = [claim for claim in claims if claim not in conflicts]
    if unflagged:
        raise TrackerValidationError(
            f"stage-03 question(s) {', '.join(unflagged)} claim an intent "
            "conflict the brief never flagged; a conflict the brief did not "
            "record is one no reading raised")


def _validate_escalations(tracker: dict) -> None:
    """The only path out of the autonomous middle of a run.

    Escalations queue, surface at stage boundaries batched at most four per
    ``AskUserQuestion`` call, and are answered by a human or by nobody. A shape
    this accepts but no human ever sees is a question the run answers itself
    while recording that it asked.
    """
    rows = tracker["escalations"]
    qids = {row["qid"] for row in tracker["quorum"]}
    if len({row["id"] for row in rows}) != len(rows):
        raise TrackerValidationError("duplicate escalation id")
    batches: dict[str, int] = {}
    for row in rows:
        if not _ESCALATION_ID.fullmatch(row["id"]):
            raise TrackerValidationError("escalation ids are E-<n>")
        if row["qid"] != "-" and row["qid"] not in qids:
            raise TrackerValidationError(
                "an escalation refers to an unknown qid; its question, options "
                "and brain responses can no longer be recovered")
        #: TOKENS, not the closed question vocabulary. This column carries the
        #: axes an escalation touches, joined from a quorum payload, so its
        #: legal values include ``storage-engine`` and ``-``. Judging it with
        #: ``_BLAST_RADII`` halted the run on values a specified writer emits;
        #: nothing branches on this cell, so tokens are the whole requirement
        #: and P06 owns any enumeration it later needs.
        for axis in _csv(row["blast"]):
            if not _TOKEN.fullmatch(axis):
                raise TrackerValidationError(
                    f"an escalation's Blast column is '-' or a comma-separated list "
                    f"of axis tokens; {axis!r} is not a token")
        if row["state"] not in _ESCALATION_STATES:
            raise TrackerValidationError(f"unknown escalation state {row['state']!r}")
        if row["state"] == "queued" and row["batch"] != "-":
            raise TrackerValidationError("a queued escalation has not been batched yet")
        if row["state"] in ("asked", "answered") and row["batch"] == "-":
            raise TrackerValidationError("an asked escalation names its batch")
        if row["state"] == "answered":
            if not _HUMAN_DECISION.fullmatch(row["resolution"]):
                raise TrackerValidationError(
                    "an answered escalation records an H-<n> resolution")
        elif row["resolution"] != "-":
            raise TrackerValidationError(
                "only an answered escalation carries a resolution")
        if row["batch"] != "-":
            batches[row["batch"]] = batches.get(row["batch"], 0) + 1
    #: Per BATCH, not per section. More than four pending escalations means ask
    #: four and halt on the rest, so a run legitimately carries any number of
    #: them across several calls; it is one call that cannot carry five.
    over = [batch for batch, count in batches.items() if count > _MAX_BATCH]
    if over:
        raise TrackerValidationError(
            f"escalation batch {over[0]!r} asks more than {_MAX_BATCH} questions in "
            "one AskUserQuestion call")


def _validate_tracker_semantics(tracker: dict) -> None:
    """Every per-section semantic rule, run as the last step of a parse.

    Structural parsing proves the bytes are a tracker; this proves they are a
    state the run can actually be in. Later phases extend the dispatcher rather
    than add a second entry point, so there is exactly one place a tracker is
    judged and no way to obtain an unvalidated one.
    """
    #: ``_validate_stages`` leads because ``_validate_intent`` reads stage 03's
    #: state to decide whether the brief may be frozen, and a stage table that
    #: has not been proven to hold twelve known rows is not one to index into.
    _validate_stages(tracker)
    _validate_intent(tracker)
    _validate_questions(tracker)
    #: After both sections it spans, and never instead of either: it assumes the
    #: roster is four rows and the origins are in the enum, which is what the
    #: two validators above have just proven.
    _validate_intent_conflicts(tracker)
    _validate_escalations(tracker)


def derive_next_action(tracker: dict) -> str:
    """The single next action, derived from files rather than remembered.

    A pending escalation outranks the stage: the spec requires ``next_action``
    to read ``await-escalation-batch`` rather than any generic block, so a
    resuming controller and the terminal report both see why the run is waiting.
    ``asked`` counts as pending alongside ``queued`` — the window after a batch
    has gone to the human is the longest wait in the run, and it is exactly the
    window in which a controller must not answer the question itself.

    The terminal verdict is guarded rather than a fallthrough. A tracker with no
    active stage and work still pending is not finished, and returning
    ``complete`` for it would end the run with its artifacts unwritten — the
    silent fork ``## Stage`` exists to prevent, arriving from the other end.

    ``_validate_stages`` now refuses that shape outright, so a tracker obtained
    through ``parse_tracker`` can no longer reach the raise below. It stays as a
    defensive backstop for the one remaining way in: this function takes a plain
    ``dict``, and callers mutate trackers in place between parsing and
    dispatching. A dict edited past the validator is still refused rather than
    silently reported complete.
    """
    if any(row["state"] in ("queued", "asked") for row in tracker["escalations"]):
        return "await-escalation-batch"
    for row in tracker["stages"]:
        if row["stage_state"] == "active":
            return row["next_action"]
    if all(row["stage_state"] == "complete" for row in tracker["stages"]):
        return "complete"
    raise TrackerValidationError(
        "no stage is active and stages remain pending: the run has no next "
        "action to derive and is not complete")


def _row(values: tuple[str, ...]) -> str:
    return "| " + " | ".join(values) + " |"


def _render_table(header: tuple[str, ...],
                  rows: tuple[tuple[str, ...], ...]) -> list[str]:
    return [_row(header), _row(tuple("---" for _ in header)), *[_row(row) for row in rows]]


def render_tracker(tracker: dict) -> str:
    """Render the one canonical byte sequence for a tracker."""
    run = tracker.get("run", {})
    if tuple(run) != _RUN_KEYS:
        raise TrackerValidationError("run fields missing, unknown, or reordered")
    blocks = [
        [MARKER, TITLE],
        ["## Run", *_render_table(("Field", "Value"),
                                  tuple((key, str(run[key])) for key in _RUN_KEYS))],
    ]
    for heading, key, header in _SECTIONS[1:]:
        fields = tuple(_field(column) for column in header)
        try:
            rows = tuple(tuple(str(row[name]) for name in fields) for row in tracker[key])
        except KeyError as exc:
            raise TrackerValidationError(f"{heading} row is missing field {exc}") from exc
        blocks.append([heading, *_render_table(header, rows)])
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"


def _diagnostic(run_dir: Path, detail: str) -> str:
    """One sentence a human can act on, plus the ownership fact behind it.

    Naming ``superb:pipeline`` matters more than it looks: the user who hits
    this has run both skills in one repository, and a bare "schema mismatch"
    tells them nothing about which skill owns which run directory.
    """
    return (
        f"{run_dir}: {detail}; no files were changed. "
        f"superb:pipeline-auto reads only {SCHEMA}. It does not interoperate "
        "with superb:pipeline (pipeline-run/v1, pipeline-run/v2) and there is "
        "no migration in either direction."
    )


def validate_run(run_dir: Path) -> dict:
    """Read and validate a run without mutating anything on disk.

    Every rejection path leaves the directory exactly as it was found. That is
    the whole contract: a foreign, missing, empty or malformed tracker stops
    the run rather than being repaired into a guess.

    An unrecognised *pipeline-auto* marker is refused as hard as a foreign one.
    That case is the dangerous one, because it is what a future version of this
    same skill would write: accepting it on the grounds that the prefix matches
    is how a newer run's state gets mangled by an older controller.

    ``run_dir`` is a ``Path``, and that is the whole of it. This annotation
    said ``str`` while the first statement of the body rebound the name to a
    ``Path``, so the signature described a type no caller passed and the body
    immediately discarded. Coercing here would also have hidden a caller that
    had lost track of what it was holding; ``superb:pipeline`` types the same
    entry point the same way.
    """
    progress = run_dir / "progress.md"
    if not progress.is_file():
        raise ForeignSchemaError(_diagnostic(run_dir, "missing progress.md"))
    try:
        text = progress.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ForeignSchemaError(
            _diagnostic(run_dir, f"unreadable progress.md ({exc})")) from exc
    if not text:
        raise ForeignSchemaError(_diagnostic(run_dir, "progress.md is empty"))
    lines = text.splitlines()
    first = lines[0] if lines else ""
    if first != MARKER:
        raise ForeignSchemaError(
            _diagnostic(run_dir, f"schema marker is {first!r}, not {MARKER!r}"))
    #: Marked as ours and still unparseable is a *different* fault from not
    #: ours, and conflating them sends the user to the wrong skill. The
    #: subclass, not just the message, is what the caller branches on.
    try:
        return parse_tracker(text)
    except TrackerValidationError as exc:
        raise TrackerValidationError(
            _diagnostic(run_dir, f"malformed {SCHEMA} tracker ({exc})")) from exc
