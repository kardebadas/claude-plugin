"""Durable state for superb:pipeline-auto. Python standard library only.

The tracker is the authority. Conversation memory never is. Every durable
transition in this run goes through this module.

This module does not interoperate with superb:pipeline. `pipeline-run/v1` and
`pipeline-run/v2` are foreign schemas and there is no migration in either
direction — not here, not later.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
#: For ``RUNGS`` alone, and it is a capability rather than a convenience:
#: nothing already imported here can make a mapping that refuses to be
#: written to. A ``dict`` subclass overriding ``__setitem__`` is bypassed by
#: ``dict.__setitem__(RUNGS, ...)``; a ``mappingproxy`` has no mutation API
#: to bypass at all. The adoption bar has to fail at the language level
#: rather than at review, because the party most motivated to raise its own
#: confidence is the controller running this module.
from types import MappingProxyType

#: Exactly one of these two is present on any platform this runs on, and the
#: lock refuses to proceed if neither is. They are imported here, guarded,
#: rather than inside the lock, so that "which primitive does this interpreter
#: have" is a fact established once at import and passed to
#: ``select_lock_impl`` as an argument — which is what lets a test drive the
#: selection without a second platform.
try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - only reachable on Windows
    fcntl = None

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - only reachable on POSIX
    msvcrt = None

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


class FilesystemSuitabilityError(TrackerError):
    """The run's filesystem is known unsupported, or cannot be classified.

    A read-only stop, and deliberately NOT a ``TrackerWriteError``: that family
    means "nothing happened, a retry is safe", and retrying an NFS mount
    produces the same answer forever. Nothing about this is transient — the
    answer changes when the run moves, not when it is tried again.
    """


#: ``repo_root`` sits with the four identity keys rather than with the
#: counters because it is the same kind of fact: what this run is anchored to.
#: It is RECORDED at init from an explicit argument and never derived — see
#: ``repo_root`` below, which is the only sanctioned way to read it back.
_RUN_KEYS = (
    "run_id", "schema", "base_commit", "target_branch", "repo_root",
    "worker_limit",
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

#: An absolute path, in the characters a pipe-delimited cell can carry back out
#: unchanged. ``_TOKEN`` is the wrong grammar here in one direction — its first
#: character must be alphanumeric, and the whole point of this one is that the
#: first character is ``/`` — and the right grammar in the other: a cell's
#: contents are stripped on the way in, so a root with a space at either end
#: parses back as different bytes, and a ``|`` anywhere in it parses back as a
#: different number of columns. A repository whose path contains a space is
#: therefore refused at ``initialize_run``, loudly and before the run starts,
#: rather than recorded into a cell that cannot hold it.
_ABS_PATH = _CharClass("/", _ALNUM + "._/@:+-")


def _field(column: str) -> str:
    """Map a column header to its dict key: 'Re-review' -> 're_review'."""
    return column.lower().replace(" ", "_").replace("-", "_")


#: The public column grammar: section name -> the ordered keys one row carries.
#:
#: P02 owns every section's columns, INCLUDING the sections whose rows P03 to
#: P06 write. The alternative is each of those phases re-declaring the shape
#: beside its own writer, where a copy drifts from the validator silently: the
#: tracker still parses, the cell is simply under the wrong header. This build
#: has already paid for that defect three times over, each time as a pattern
#: written one column short of the committed fixture.
#:
#: The values are DICT KEYS, not display headers, and the two are one rename
#: apart (``Re-review`` -> ``re_review``). A caller gets the names it will
#: actually write and read back — ``append_row`` takes these, ``parse_tracker``
#: produces these — so there is no translation step between the accessor and the
#: row for a caller to get wrong. The display headers stay private because
#: rendering is the only thing that needs them, and rendering is P02's.
#:
#: Frozen for the same reason ``RUNGS`` is, and over a dict nothing else holds:
#: a ``mappingproxy`` is a read-only VIEW rather than a copy, so a proxy over a
#: named module-level dict is editable by everything that can reach the name.
#: Five phases read this mapping; one of them editing it would re-shape another
#: phase's validation with nothing raised anywhere.
SECTIONS = MappingProxyType({
    key: tuple(_field(column) for column in header)
    for _, key, header in _SECTIONS[1:]
})


def section_columns(name: str) -> tuple[str, ...]:
    """The ordered dict keys of one section's rows.

    An unknown name RAISES. Answering with an empty tuple would be the quiet
    disaster: a caller zipping its values against one builds an empty row and
    appends it, and nothing downstream can tell that row from a section that
    genuinely has no columns.
    """
    if name == _SECTIONS[0][1]:
        raise TrackerValidationError(
            "the run section is a key/value table, not a row table: it has no "
            "column grammar to build a row against, and its fields are "
            "_RUN_KEYS")
    if name not in SECTIONS:
        raise TrackerValidationError(
            f"unknown tracker section {name!r}; the sections are "
            f"{', '.join(SECTIONS)}")
    return SECTIONS[name]


def append_row(tracker: dict, section: str, row: dict) -> dict:
    """Append one row to one section, built against that section's columns.

    The row is judged by NAME against the whole column set — every unknown key
    and every missing one is named back in the same message. Counting is not
    enough and is the specific failure this exists to refuse: a row copied from
    a stale column list has exactly the right number of keys and one of them
    spelled for a column the section has never had. ``zip`` would accept it,
    ``len`` would accept it, and ``render_tracker`` would then report the column
    that went missing rather than the one that was invented.

    The stored row is keyed in the section's own column order, so an appended
    row and a parsed one read identically.

    It mutates the tracker dict and returns it — ``mutate`` has to return what
    it edited — and it writes nothing. ``locked_tracker_update`` remains the
    sole writer of ``progress.md``; this is what a ``mutate`` callable uses
    inside one.
    """
    columns = section_columns(section)
    unknown = sorted(set(row) - set(columns))
    missing = sorted(set(columns) - set(row))
    if unknown or missing:
        raise TrackerValidationError(
            f"a {section!r} row does not match the section's columns: "
            f"unknown {unknown}, missing {missing}. Build it against "
            f"section_columns({section!r}), which is {list(columns)}")
    tracker[section].append({column: row[column] for column in columns})
    return tracker


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


def _is_count(value: str) -> bool:
    """A non-negative integer as this schema spells one.

    ``isdigit`` alone is true of ``'\u0663'`` and ``'\u00b2'``: the first parses as an
    integer and the second raises ``ValueError`` -- outside this module's
    exception family -- in whatever reads the cell next. ``isascii`` first is
    what keeps every counter in this schema readable by ``int``.
    """
    return bool(value) and value.isascii() and value.isdigit()


def _validate_run(tracker: dict) -> None:
    """``## Run`` as a state the run can be in, not merely as fifteen cells.

    Every other section gained a semantic validator; this one did not, and the
    gap had a shape. ``base_commit``, ``target_branch`` and ``worker_limit``
    were checked in exactly one place -- ``initialize_run`` -- and never again,
    so a later ``mutate`` could write anything at all into them. Only
    ``_IDENTITY_KEYS`` would object, and only to the four keys it guards.

    ``worker_limit`` is not one of those four, and it is the cell the run reads
    to decide how many brain slots to reserve: a run that quietly rewrote it
    would dispatch against a capacity nobody granted. ``revision`` and
    ``agent_dispatch_count`` are not either, and they are the counters other
    records cite themselves against -- a run that rewrote a counter buys itself
    standing it was never given, by a route no schema check was watching.

    ``schema`` is checked against ``SCHEMA`` here for the first time. The MARKER
    is what ``_sections`` judges; the FIELD was never compared to anything, so a
    tracker could carry the v1 marker and call itself v2 in its own table. There
    is no migration in either direction, so the two disagreeing is a stop.

    ``repo_root`` is the cell with the quietest failure in the whole table. It
    is what a ``file:line`` citation is resolved against, and a root that is
    relative, blank, or the absence sentinel resolves NOTHING — so every brain
    claiming ``specified`` or ``code-evidenced`` is demoted for citing evidence
    that "does not exist", every cluster falls below the adoption floor, and the
    run escalates every question it is ever asked while looking like a correctly
    cautious quorum. There is no exception and no failing test to find it by, so
    the check belongs here, on every read, rather than only at birth.

    It is checked as a STRING, never against the filesystem. A tracker read from
    a checkout that has since moved, or on another machine, must still parse: a
    validator that called ``exists()`` would turn a relocated clone into a
    foreign-schema-shaped stop, and "this path is not where it was" is a fact
    for the code resolving a citation to report, not for the parser to guess at.
    """
    run = tracker["run"]
    if run["schema"] != SCHEMA:
        raise TrackerValidationError(
            f"schema field {run['schema']!r} is not {SCHEMA!r}: the marker and "
            "the field disagree, and there is no migration in either direction")
    if not _RUN_ID.fullmatch(run["run_id"]):
        raise TrackerValidationError(
            f"run_id {run['run_id']!r} is not a legal run id; it is interpolated "
            f"into three artifact paths under {RUN_ARTIFACT_ROOT}/, so a "
            "separator or a leading dot in it addresses another run's records")
    if not _COMMIT.fullmatch(run["base_commit"]):
        raise TrackerValidationError(
            f"base_commit {run['base_commit']!r} is not a full 40-character "
            "object name: it is one end of every range proof this run makes")
    if not _TOKEN.fullmatch(run["target_branch"]):
        raise TrackerValidationError(
            f"target_branch {run['target_branch']!r} is not one token")
    if run["target_branch"] in ("main", "master"):
        raise TrackerValidationError(
            "target_branch may not be main or master: pipeline-auto leaves a "
            "clean committed feature branch and merges or pushes nothing")
    if not _ABS_PATH.fullmatch(run["repo_root"]):
        raise TrackerValidationError(
            f"repo_root {run['repo_root']!r} is not an absolute path: it is "
            "recorded at init and is what every file:line citation in this run "
            "is resolved against, so a relative or missing one resolves no "
            "evidence at all and silently demotes every grounded answer")
    #: ``initialize_run`` refuses a ``bool`` BY TYPE and then writes
    #: ``str(worker_limit)``. So the only spelling that can reach a tracker from
    #: anywhere else is the string ``'True'``, which no python-type check would
    #: ever see -- and which ``int()`` raises on, in the caller reserving slots.
    if not _is_count(run["worker_limit"]) or int(run["worker_limit"]) < 1:
        raise TrackerValidationError(
            f"worker_limit {run['worker_limit']!r} is not a positive integer in "
            "ASCII digits; it is what the run reads to reserve brain slots")
    for key in ("agent_dispatch_count", "revision"):
        if not _is_count(run[key]):
            raise TrackerValidationError(
                f"{key} {run[key]!r} is not a non-negative integer in ASCII "
                "digits; every record that cites it reads it as one")


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
#: The one axis token that is NOT a stage-03 question id: the axis a run
#: discovered after the gate closed. It is spelled once, here, because it is
#: read in two places that must not drift -- ``_validate_quorum``, which admits
#: it into the axis namespace, and ``_validate_questions``, which refuses it as
#: a question id so that the axis cell has exactly ONE reading.
_RESERVED_AXIS = "new"

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


#: Lowercase hex, and lowercase is not an accident of taste. A digest is
#: compared byte for byte against a recomputation and against the file names
#: the responses were written under, so a cell differing only in case matches
#: nothing while looking exactly like a match to a reader.
_HEX = "0123456789abcdef"

#: The ASCII lowercase letters, spelled out for the same reason ``_Numbered``
#: spells out its digits: ``str.islower`` is true of characters ``[a-z]`` is
#: not, and a rejection reason spelled in them renders back into the tracker
#: looking like a word nothing downstream can match.
_LOWER = "abcdefghijklmnopqrstuvwxyz"


class _Hex:
    """``<prefix>[0-9a-f]{width}``: a fixed-width lowercase hex digest.

    The third grammar shape this module states directly rather than compiling.
    Both halves are load-bearing and neither survives being written casually: a
    width check alone accepts sixty-four of anything, and a character class
    alone accepts a truncated digest that still looks like hex — and a
    truncated digest is the one failure that reads as a successful binding.
    """

    __slots__ = ("_prefix", "_width")

    def __init__(self, width: int, prefix: str = "") -> None:
        self._prefix = prefix
        self._width = width

    def fullmatch(self, value: str) -> bool:
        digits = value[len(self._prefix):]
        return (value.startswith(self._prefix) and len(digits) == self._width
                and all(character in _HEX for character in digits))


#: The payload and context digests a quorum row binds its three brains to.
_SHA256 = _Hex(64)
#: ``qid = sha256(normalize(question) || "\x00" || axis)``, truncated. It keys
#: the row, and every escalation and task decision in the run points back
#: through it, so a qid no derivation can reproduce is a question that can never
#: be found again.
_QID = _Hex(12)
#: ``Q-<qid>`` is a quorum's decision id and ``H-<n>`` is a human's. The prefix
#: is the entire difference between a decision a machine made and one the user
#: made, and it is what the contradiction check reads to tell them apart.
_QUORUM_DECISION = _Hex(12, "Q-")

#: A Git object name: forty lowercase hex characters. Task commits, a task's
#: integration commit and both ends of a gate edge are spelled this way and
#: nothing else is accepted for them. A symbolic name — ``HEAD~1``, a branch, a
#: tag — reads like an edge and is not one: it resolves somewhere else tomorrow,
#: which is precisely why the spec requires a review package to be generated
#: from the PERSISTED reservation baseline rather than from ``HEAD~1``. The
#: ``baseline..source-head`` range proof is a proof only between immutable ends.
_COMMIT = _Hex(40)


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
    #: A question id is also a quorum AXIS token, and the axis namespace is the
    #: question ids PLUS ``_RESERVED_AXIS``. Uniqueness within this section was
    #: the only check, so a question could itself be called ``new`` -- and then
    #: the axis cell ``new`` has two readings at once: the reserved literal, and
    #: a reference to that question. That is worse than either, because the
    #: contradiction check resolves the axis to decide what an adopted answer
    #: would contradict, and an axis with two meanings resolves to whichever the
    #: reader assumed. The question-id reading is the one closed, because the
    #: literal is load-bearing and ``new`` is a name no question needs.
    if any(row["id"] == _RESERVED_AXIS for row in rows):
        raise TrackerValidationError(
            f"{_RESERVED_AXIS!r} is the reserved quorum axis literal and is not "
            "available as a stage-03 question id: one axis cell cannot mean "
            "both 'an axis discovered after the gate closed' and 'the question "
            f"called {_RESERVED_AXIS}'")
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


class _QuorumOutcome:
    """``adopted``, ``escalated``, or ``rejected-<reason>``.

    P02 closes the SHAPE of an outcome and not the rejection vocabulary: naming
    the reasons is P03's contract, and an enum here would have to be edited in
    two places every time one is added — the kind of duplication that ends with
    a specified writer emitting a reason this module halts the run on.

    What is closed is that the two non-rejecting words are exact, and that
    anything else must both announce itself as a rejection and carry a reason.
    A bare ``rejected`` is the outcome recorded with the reason dropped, and the
    reason is the only part a human reading the run afterwards can act on.
    """

    __slots__ = ()

    _EXACT = ("adopted", "escalated")
    _PREFIX = "rejected-"
    _REASON = _CharClass(_LOWER, _LOWER + "-")

    def fullmatch(self, value: str) -> bool:
        return value in self._EXACT or (
            value.startswith(self._PREFIX)
            and self._REASON.fullmatch(value[len(self._PREFIX):]))


_QUORUM_OUTCOME = _QuorumOutcome()

#: Two states, and the pair is the whole recovery story for a quorum. A row is
#: either dispatched-and-undecided or finalized-and-decided; there is no third
#: state, because a third one would be a row an interrupted run cannot classify.
_QUORUM_STATES = ("in_flight", "finalized")

#: Exactly three brains, exactly three responses. Stated once, because the two
#: places it is checked below mean the same fact and a run that reduced either
#: to fit capacity has replaced a quorum with a straw poll.
_BRAINS = 3


def _validate_quorum(tracker: dict) -> None:
    """The three-phase quorum record, structurally.

    ``## Quorum`` is the only place a decision no human made is written down,
    so what this refuses is the whole of what stops the run from deciding
    something it had no authority to decide.

    The record has three phases and two of them are states: a row appears
    ``in_flight`` carrying its three owner ids and its payload digest **before**
    dispatch, and becomes ``finalized`` carrying the computed result. The digest
    is persisted first on purpose — a run that crashes mid-dispatch must still
    be able to prove which payload the responses on disk were answers to — and
    a row that is both in flight and decided is the one shape an interrupted
    controller cannot classify at all.

    One ``Payload Digest`` binds all three brains. The three get different
    reading assignments, but the assignment rule is a frozen constant, so brain
    n's payload is determined by the shared payload plus n; a digest per brain
    would be three copies of one fact, free to disagree.

    P02 checks that a row is a *possible state of the protocol*. Whether the
    adoption was *correct* — the ``code-evidenced`` floor, the strictly-higher
    winning rung, contradiction with a human decision, the depth cap, the drift
    budget — is P03's arithmetic over these same cells and is deliberately
    absent here. The one policy fact this module does hold is the rung ENUM,
    because a rung outside it is not a weak vote: it is a malformed response,
    and defaulting it to any legal value is how a malformed brain buys a vote.
    """
    rows = tracker["quorum"]
    #: The axis namespace is the stage-03 question id namespace, plus the
    #: literal ``new`` for an axis the run discovered after the gate closed.
    #: Closed for the reason ``_BLAST_RADII`` is closed: adoption checks the
    #: axis against the human decisions already recorded on it, so an axis
    #: matching no question contradicts nothing BY CONSTRUCTION and clears that
    #: check by being unrecognisable rather than by being compatible.
    #:
    #: ``new`` IS LEGAL HERE AND ILLEGAL IN ``parse_decisions``, DELIBERATELY.
    #: A row and the decision record it produced record different facts: this
    #: row records WHAT WAS ASKED, and a question raised after the stage-03 gate
    #: closed was asked on no stable axis, so the row keeps ``new`` for the life
    #: of the run. The record appended to ``decisions.md`` records THE AXIS THAT
    #: QUESTION OPENED, and ``parse_decisions`` refuses the placeholder there
    #: because every untagged decision would otherwise share one contradiction
    #: bucket; that record carries the question's own bare 12-hex qid instead.
    #: Because this namespace is closed to the stage-03 ids plus the literal, a
    #: minted qid axis could not be written into this cell anyway -- the two
    #: namespaces do not overlap and are not meant to. A ``new``-axis row whose
    #: ``Decision`` is ``Q-<qid>`` and whose record's ``Axis`` is that same bare
    #: ``<qid>`` is the INTENDED shape, and is pinned end to end in the suite.
    axes = {row["id"] for row in tracker["questions"]} | {_RESERVED_AXIS}
    phases = {row["id"] for row in tracker["phases"]}
    if len({row["qid"] for row in rows}) != len(rows):
        raise TrackerValidationError(
            "duplicate qid: there is one adopted answer per qid per run, and a "
            "second row on one qid is the run re-asking until it likes the answer")
    for row in rows:
        if not _QID.fullmatch(row["qid"]):
            raise TrackerValidationError(
                "a qid is twelve lowercase hex characters; a row keyed by "
                "anything else is one whose question cannot be found again")
        if row["axis"] not in axes:
            raise TrackerValidationError(
                f"quorum axis {row['axis']!r} is neither a stage-03 question id "
                f"nor the literal {_RESERVED_AXIS!r}")
        if row["phase"] != "-" and row["phase"] not in phases:
            raise TrackerValidationError(
                "quorum row refers to an unknown phase; the drift budget is "
                "counted by filtering these rows on Phase")
        #: Ahead of every rule that branches on the state, for the reason
        #: ``_validate_stages`` checks its enum first: an ``in_flight`` test
        #: with an ``else`` would judge an unclassifiable row by the rules for
        #: the one state it is certainly not in.
        if row["state"] not in _QUORUM_STATES:
            raise TrackerValidationError(f"unknown quorum state {row['state']!r}")
        owners = _csv(row["owners"])
        if len(owners) != _BRAINS or len(set(owners)) != _BRAINS:
            raise TrackerValidationError(
                f"a quorum dispatches exactly {_BRAINS} DISTINCT brains; a count "
                "is never reduced to fit capacity, and one brain dispatched "
                "twice is a majority manufactured from a single opinion")
        for key in ("payload_digest", "context_digest"):
            if not _SHA256.fullmatch(row[key]):
                raise TrackerValidationError(
                    f"{key} must be lowercase sha256 hex and is persisted before "
                    "dispatch, not written back with the responses")
        responses = _csv(row["responses"])
        if len(responses) > _BRAINS or len(set(responses)) != len(responses):
            raise TrackerValidationError(
                f"a quorum records at most {_BRAINS} distinct response files; one "
                "file cited twice is one brain's answer weighted double")
        if row["state"] == "in_flight":
            if any(row[key] != "-" for key in ("depth", "rung", "outcome", "decision")):
                raise TrackerValidationError(
                    "an in-flight quorum carries no computed result; the "
                    "three-phase record exists so an interruption is always "
                    "classifiable, and a row that is both in flight and decided "
                    "classifies as neither")
            continue
        if not _QUORUM_OUTCOME.fullmatch(row["outcome"]):
            raise TrackerValidationError(
                f"unknown quorum outcome {row['outcome']!r}: 'adopted', "
                "'escalated', or a 'rejected-<reason>' that states its reason")
        #: THE check this section exists for. A brain never types a number: it
        #: selects a grounding rung and the controller derives the value. A rung
        #: the enum does not contain is therefore a malformed response, and the
        #: obvious defence — ``RUNGS.get(rung, 0.55)``, where 0.55 is
        #: ``engineering-judgement`` and is already in P03 for the
        #: citation-demotion rule — silently converts every malformed response
        #: into a legal vote. The value that arrives is legal; the door it came
        #: through is not, which is precisely why nothing downstream can detect
        #: it. Schema-invalid means schema-invalid: re-dispatch that brain once,
        #: then escalate, and never default.
        if row["rung"] != "-" and row["rung"] not in RUNG_NAMES:
            raise TrackerValidationError(
                f"rung {row['rung']!r} is outside the enum; an out-of-enum rung "
                "is schema-invalid and is NEVER defaulted to a legal value")
        #: ``isdigit`` alone is true of ``'١'`` and ``'²'``. The first parses as
        #: an integer and the second raises ``ValueError`` — outside this
        #: module's exception family — when the depth cap finally reads it.
        if row["depth"] != "-" and not (
            row["depth"].isascii() and row["depth"].isdigit()
        ):
            raise TrackerValidationError(
                "decision depth must be a non-negative integer in ASCII digits")
        if row["outcome"] == "adopted":
            if len(responses) != _BRAINS:
                raise TrackerValidationError(
                    f"adoption requires {_BRAINS} valid responses on disk; fewer "
                    "cannot produce the strictly-higher winning rung it needs")
            if not _QUORUM_DECISION.fullmatch(row["decision"]):
                raise TrackerValidationError(
                    "an adopted quorum records its Q-<qid> decision, so its "
                    "provenance survives even if the Provenance field is lost "
                    "and so a machine decision never wears a human one's id")
            if row["rung"] == "-" or row["depth"] == "-":
                raise TrackerValidationError(
                    "an adopted quorum records its winning rung and decision "
                    "depth; an unrecorded rung cannot be checked against the "
                    "adoption floor and is indistinguishable from one below it")
        elif row["decision"] != "-":
            raise TrackerValidationError(
                "only an adopted quorum carries a decision")


_TASK_KINDS = ("source", "artifact")
#: Unstarted, running, blocked on a question, complete.
_TASK_STATES = ("[ ]", "[~]", "[?]", "[x]")
#: A task can be blocked on a question; a PHASE cannot. A phase blocked on a
#: question is a set of blocked tasks, and giving the phase its own ``[?]``
#: would be a second place to write a fact the task rows already hold.
_PHASE_STATES = ("[ ]", "[~]", "[x]")
#: The review-intensity dial, and nothing else. ``required`` buys the full
#: per-task gate; ``final-only`` buys mechanical verification only, with stage
#: 11 as the net. There is no middle value, because a middle value is a place
#: for a run to put itself when it wants less than it was given.
_REVIEW_CLASSES = ("final-only", "required")
#: Where the class in this tracker came from. ``plan`` means "the class stage 04
#: fixed, mirrored here". ``ratchet`` means "this DIFFERS from plan metadata",
#: which the spec permits only with a matching ratchet record. There is no third
#: source, and in particular none that means "lowered".
_CLASS_SOURCES = ("plan", "ratchet")
_GATE_TYPES = ("phase", "master")
_GATE_STATES = ("pending", "in_progress", "blocked", "accepted")
#: A gate that has been judged, either way. Both outcomes rest on the same two
#: artifacts, so both demand them: an acceptance with no reports is a verdict
#: with no basis, and a block with none is a halt nobody can answer.
_GATE_EVALUATED = ("blocked", "accepted")

#: Every ``## Tasks`` cell that records something a worker did. An unstarted
#: task has none of them. ``Decisions`` and ``Provisional`` are deliberately
#: absent: the decisions a task's plan rests on are known when the plan is
#: written, before anyone picks the task up, and that is exactly what lets taint
#: cross a phase boundary. Requiring a task to have STARTED before it could cite
#: the decision that taints it would leave the closure stopping at the phase
#: that raised the decision.
_TASK_LIFECYCLE = (
    "owner", "attempt", "result", "checkpoints", "source_ref", "commits",
    "artifacts", "integration", "verification", "question",
)
#: The cells that assert work is finished. A running or blocked task has none of
#: them: a row that is simultaneously in flight and integrated is one an
#: interrupted controller cannot classify, the same shape ``## Quorum`` refuses.
_TASK_COMPLETION = ("source_ref", "commits", "artifacts", "integration")

#: Completion and integration are SEPARATE FACTS, and ``held`` is the word that
#: keeps them apart. When the drift budget trips, running work still finishes,
#: publishes and imports to ``[x]``; only integration is held. Freezing the
#: import as well would discard a finished task's evidence and repeat the work
#: on resume. So ``held`` is a legal integration value — and an UNRECORDED one
#: never is, because "not written down" and "deliberately deferred" are the two
#: states a resuming controller must be able to tell apart.
_INTEGRATION_HELD = "held"
#: An artifact task produces no source range, so there is nothing to integrate
#: and nothing to prove ancestry over. It is not the same as ``held``: a task
#: marked ``held`` is one the budget freeze is still waiting on.
_INTEGRATION_NA = "N/A"


def _ratchet_record(value: str) -> bool:
    """``<trigger>@<evidence>``: what fired, and where the proof of it is.

    Both halves or neither. A bare trigger is a claim the run makes about its
    own review intensity with nothing behind it; a bare evidence path names no
    trigger to check the evidence against. The trigger is a TOKEN rather than a
    closed vocabulary for the reason an escalation's ``Blast`` column is: the
    spec lists five conditions but no canonical names for them, P05 owns the
    ratchet DECISION, and an enum invented here would halt a run on a value a
    conforming writer emits.
    """
    parts = value.split("@")
    return len(parts) == 2 and all(_TOKEN.fullmatch(part) for part in parts)


def _decision_id(value: str) -> bool:
    """``H-<n>`` or ``Q-<qid>``: a human's answer, or a quorum's.

    The prefix is the entire difference between a decision a machine made and
    one the user made, and it is what the contradiction routing reads to tell
    them apart — a plan-mandated finding tracing to a human decision HALTS to
    the escalation queue, while one tracing to a quorum decision re-opens that
    qid at a raised bar. A cited id in neither namespace routes as neither.

    Shape only. Whether the id RESOLVES is settled against ``decisions.md``,
    which is the decision index and is named by ``## Run``'s ``decisions``
    field; this module reads no file but the tracker, and a quorum row is not
    that index — a decision the run recorded and later escalated still has a
    task resting on it.
    """
    return _HUMAN_DECISION.fullmatch(value) or _QUORUM_DECISION.fullmatch(value)


def _validate_tasks(tracker: dict) -> None:
    """One row per task, and every row a state the task can actually be in.

    Two separations carry most of the weight here.

    **Completion is not integration.** A finished task is ``[x]`` with its
    integration ``held`` while the budget freeze holds. Collapsing the two —
    refusing to mark a task complete until it is integrated — would throw away
    the evidence of finished work every time the freeze trips and repeat that
    work on resume.

    **The plan's decisions are not lifecycle state.** ``Decisions`` names the
    decision ids a task rests on, and a task in a later phase rests on an
    earlier phase's decision before any worker touches it. That column is the
    edge the provisional closure walks — the decision's own scope stops at the
    phase that RAISED it — so each cited id is held to one of the two decision
    namespaces here, and resolved against ``decisions.md`` by the phase that
    reads that file.

    Nothing here reads ``Review Class``. These are the state machine's own
    integrity rules, not review, and the dial buys review only.
    """
    phases = {row["id"] for row in tracker["phases"]}
    seen: set[str] = set()
    for task in tracker["tasks"]:
        if task["id"] in seen:
            raise TrackerValidationError(
                f"duplicate task id {task['id']!r}: the lifecycle helpers locate "
                "a task by scanning for its single ID row, so a second row is a "
                "task whose state depends on which copy the scan reaches first")
        seen.add(task["id"])
        if task["phase"] not in phases:
            raise TrackerValidationError(
                f"task {task['id']!r} refers to unknown phase {task['phase']!r}; "
                "the per-phase drift budget is derived by filtering on Phase, so "
                "a task in no phase is work no budget counts")
        if task["kind"] not in _TASK_KINDS:
            raise TrackerValidationError(f"unknown task kind {task['kind']!r}")
        if task["state"] not in _TASK_STATES:
            raise TrackerValidationError(f"unknown task state {task['state']!r}")
        if task["provisional"] not in ("yes", "no"):
            raise TrackerValidationError(
                f"Provisional is 'yes' or 'no'; {task['provisional']!r} is neither")
        for decision in _csv(task["decisions"]):
            if not _decision_id(decision):
                raise TrackerValidationError(
                    f"task {task['id']!r} cites {decision!r} as a decision; a "
                    "cited decision is 'H-<n>' or 'Q-<qid>', and an id in "
                    "neither namespace cannot be looked up in decisions.md, "
                    "cannot be routed as human or machine, and cannot be copied "
                    "into a reviewer's constraints — so the taint is a label")
        if task["state"] == "[ ]":
            if any(task[key] != "-" for key in _TASK_LIFECYCLE):
                raise TrackerValidationError(
                    f"unstarted task {task['id']!r} carries lifecycle state; a "
                    "task nobody has picked up has no owner, no attempt and no "
                    "evidence, and a row claiming otherwise is a reservation "
                    "that was lost or a completion that was invented")
            continue
        if any(task[key] == "-" for key in ("owner", "attempt", "checkpoints")):
            raise TrackerValidationError(
                f"started task {task['id']!r} needs its owner, attempt and "
                "checkpoints; without all three a resuming controller cannot "
                "tell whose work is outstanding or which attempt to resume")
        if task["state"] in ("[~]", "[?]"):
            if any(task[key] != "-" for key in _TASK_COMPLETION):
                raise TrackerValidationError(
                    f"in-flight task {task['id']!r} claims completion or "
                    "integration; a row that is both running and finished is one "
                    "an interrupted controller cannot classify at all")
            if task["state"] == "[?]" and task["question"] == "-":
                raise TrackerValidationError(
                    f"blocked task {task['id']!r} names no question record; a "
                    "block with no question is a halt nobody can be asked about")
            continue
        if task["result"] == "-" or task["verification"] == "-":
            raise TrackerValidationError(
                f"completed task {task['id']!r} needs its immutable result and "
                "its verification evidence; the RED-before-GREEN record and the "
                "independent re-run live in those two documents, and the dial "
                "never switches either off")
        if task["kind"] == "source":
            if task["source_ref"] == "-" or task["commits"] == "-":
                raise TrackerValidationError(
                    f"completed source task {task['id']!r} needs its source ref "
                    "and commits; the baseline..source-head range proof has no "
                    "far end without them")
            for commit in _csv(task["commits"]):
                if not _COMMIT.fullmatch(commit):
                    raise TrackerValidationError(
                        f"task {task['id']!r} records {commit!r} as a commit; the "
                        "range proof is only a proof between immutable ends, and "
                        "a symbolic name resolves somewhere else tomorrow")
            if task["integration"] != _INTEGRATION_HELD and not _COMMIT.fullmatch(
                task["integration"]
            ):
                raise TrackerValidationError(
                    f"completed source task {task['id']!r} records neither an "
                    f"integration commit nor {_INTEGRATION_HELD!r}; 'deliberately "
                    "deferred' and 'never written down' are the two states a "
                    "resuming controller has to tell apart")
        elif task["artifacts"] == "-" or task["integration"] != _INTEGRATION_NA:
            raise TrackerValidationError(
                f"completed artifact task {task['id']!r} names its artifacts and "
                f"carries {_INTEGRATION_NA!r} integration; it produces no source "
                f"range, so recording it as {_INTEGRATION_HELD!r} would add a task "
                "that can never integrate to the set the budget freeze waits on")


def _validate_phases(tracker: dict) -> None:
    """The review-intensity dial, and why its downward move is unspellable.

    ``required`` buys the full per-task gate: a fresh implementer working from a
    brief, a reviewer returning three verdicts, and a fix loop to zero open
    findings at every severity. ``final-only`` buys mechanical verification
    only. Reclassifying a phase DOWNWARD is therefore the single cost
    optimization an autonomous controller is most motivated to make about
    itself, and a schema that merely discouraged it would be bought out by the
    first run under budget pressure.

    So it is not discouraged, it has no spelling. ``Class Source`` admits two
    values and neither means "lowered": ``plan`` is the class stage 04 fixed,
    which is why it may carry no ratchet record, and ``ratchet`` is the only way
    to record a class that DIFFERS from plan metadata — and it is pinned to
    ``required``. The three legal triples are (required, plan, -),
    (final-only, plan, -) and (required, ratchet, <trigger>@<evidence>). The
    other five are refused, including the two that matter: a ``final-only``
    class carrying a ratchet record, which is a downward move wearing a
    ratchet's clothes, and a ``plan`` class carrying one, which is a ratchet
    laundered into plan metadata.

    What this cannot see is the plan file itself. A phase claiming ``plan`` as
    its source while the phase plan says otherwise is caught where the metadata
    is read — ``PlanMetadataError`` exists for exactly that — and not here.
    P02 records; it does not fetch.
    """
    gates = {row["id"] for row in tracker["gates"]}
    seen: set[str] = set()
    for phase in tracker["phases"]:
        if phase["id"] in seen:
            raise TrackerValidationError(
                f"duplicate phase id {phase['id']!r}: two rows are two review "
                "classes for one phase, and the run would obey whichever it read")
        seen.add(phase["id"])
        if phase["state"] not in _PHASE_STATES:
            raise TrackerValidationError(f"unknown phase state {phase['state']!r}")
        if phase["review_class"] not in _REVIEW_CLASSES:
            raise TrackerValidationError(
                f"review class {phase['review_class']!r} is outside "
                f"{_REVIEW_CLASSES!r}; there is no partial dial setting")
        if phase["class_source"] not in _CLASS_SOURCES:
            raise TrackerValidationError(
                f"class source {phase['class_source']!r} is outside "
                f"{_CLASS_SOURCES!r}")
        if phase["class_source"] == "ratchet":
            if not _ratchet_record(phase["ratchet"]):
                raise TrackerValidationError(
                    f"phase {phase['id']!r} differs from its plan metadata, which "
                    "is legal only with a matching ratchet record naming its "
                    "trigger AND its evidence as '<trigger>@<evidence>'; "
                    f"{phase['ratchet']!r} is not one")
            if phase["review_class"] != "required":
                raise TrackerValidationError(
                    f"phase {phase['id']!r} records a ratchet onto "
                    f"{phase['review_class']!r}: the ratchet is UPWARD ONLY, "
                    "final-only -> required and never back. A downward "
                    "reclassification is a run buying its way out of its own "
                    "review, and it has no spelling in this schema")
        elif phase["ratchet"] != "-":
            raise TrackerValidationError(
                f"phase {phase['id']!r} is plan-sourced and carries a ratchet "
                "record; a class that came from the plan did not change, and a "
                "ratchet recorded against it is a class change hidden inside the "
                "one source that is never checked against the plan")
        if (phase["state"] == "[x]") != (phase["verification"] != "-"):
            raise TrackerValidationError(
                f"phase {phase['id']!r} is verified with evidence or is neither; "
                "evidence on an unfinished phase is a proof about a moving edge, "
                "and a finished phase without it was never mechanically checked")
        if phase["gate"] != "-" and phase["gate"] not in gates:
            raise TrackerValidationError(
                f"phase {phase['id']!r} points at unknown gate {phase['gate']!r}")


def _validate_gates(tracker: dict) -> None:
    """A gate is a review over an EDGE, and the edge is two immutable ends.

    ``Base`` and ``Head`` are commit shas and nothing else. The spec requires a
    review package generated from the persisted reservation baseline and never
    from ``HEAD~1``, and that requirement is empty if the tracker will accept a
    symbolic name here: a range whose ends move is not a range anything was
    proven over. Like every other rule in this module, it holds whatever the
    phase's review class says — ``final-only`` buys less review, never a softer
    record of what was reviewed.
    """
    phases = {row["id"] for row in tracker["phases"]}
    seen: set[str] = set()
    for gate in tracker["gates"]:
        if gate["id"] in seen:
            raise TrackerValidationError(f"duplicate gate id {gate['id']!r}")
        seen.add(gate["id"])
        if gate["type"] not in _GATE_TYPES:
            raise TrackerValidationError(f"unknown gate type {gate['type']!r}")
        if gate["type"] == "phase" and gate["phase"] not in phases:
            raise TrackerValidationError(
                f"phase gate {gate['id']!r} names {gate['phase']!r}, which is not "
                "a phase of this run")
        if gate["type"] == "master" and gate["phase"] != "-":
            raise TrackerValidationError(
                f"master gate {gate['id']!r} names phase {gate['phase']!r}; the "
                "master gate reviews the whole run, and scoping it to one phase "
                "is how the final net comes to cover a fraction of the branch")
        if gate["state"] not in _GATE_STATES:
            raise TrackerValidationError(f"unknown gate state {gate['state']!r}")
        for key in ("base", "head"):
            if gate[key] != "-" and not _COMMIT.fullmatch(gate[key]):
                raise TrackerValidationError(
                    f"gate {gate['id']!r} records {gate[key]!r} as its {key}; a "
                    "gate edge is a commit sha, because a symbolic end resolves "
                    "elsewhere tomorrow and the range proof then proves nothing")
        if gate["state"] != "pending" and any(
            gate[key] == "-" for key in ("base", "head", "assignments")
        ):
            raise TrackerValidationError(
                f"opened gate {gate['id']!r} needs its immutable edge and its "
                "assignments; an edge pinned after the review is an edge chosen "
                "to fit the result")
        if gate["state"] in _GATE_EVALUATED and any(
            gate[key] == "-" for key in ("reports", "verification")
        ):
            raise TrackerValidationError(
                f"evaluated gate {gate['id']!r} needs its reports and its "
                "verification evidence; a verdict with neither is a verdict with "
                "no basis, in whichever direction it went")


#: The review-intensity dial as it is recorded PER ROUND, lowest first. It is a
#: column of ``## Task Review`` and not only of ``## Phases`` because a task has
#: N review rounds and the ratchet fires BETWEEN two of them: recorded on the
#: phase alone, "this task was re-reviewed harder after round 1" is a fact with
#: nowhere to be written down. The tuple's ORDER is load-bearing — it is the
#: comparison below that makes the per-task ratchet one-way, for the same reason
#: ``## Phases`` has no spelling for a downward reclassification.
_REVIEW_INTENSITIES = ("standard", "adversarial")
#: Assigned, in flight, judged-and-failing, judged-and-passing.
_REVIEW_STATES = ("pending", "reviewing", "blocked", "accepted")
#: A review round that has been judged, either way. Both outcomes rest on the
#: same three artifacts, so both demand them, exactly as ``_GATE_EVALUATED``
#: does: a block with no report is a halt nobody can answer, and an acceptance
#: with no independent re-run is a verdict with no basis.
_REVIEW_EVALUATED = ("blocked", "accepted")
#: The three artifacts a verdict rests on. ``Evidence`` is the INDEPENDENT
#: re-run and is not a duplicate of the task's own ``Verification``: that cell
#: records the implementer's run, and a reviewer who reads it instead of
#: re-running has reviewed a claim rather than the code.
_REVIEW_EVIDENCE = ("package", "report", "evidence")
#: Every cell a reviewer fills in. A round nobody has opened carries none.
_REVIEW_LIFECYCLE = (
    "package", "report", "critical", "important", "minor", "open", "evidence",
)
#: The three severities, and the whole of them. ``Open`` must equal their sum,
#: which is what turns "zero open findings at EVERY severity" into a machine
#: check rather than a promise: a row carrying ``Minor 3`` beside ``Open 0`` is
#: a Minor deferral written down, and this project has no deferral category.
_SEVERITIES = ("critical", "important", "minor")
#: The adversarial pass either held or it did not. There is no third word,
#: because a third word is where "it mostly held" would go.
_ADVERSARIAL_VERDICTS = ("pass", "fail")

#: ASCII digits and nothing else. ``_Numbered`` with an empty prefix is exactly
#: that grammar, and reusing it is deliberate: ``str.isdigit`` alone is true of
#: ``'٣'`` and ``int()`` reads that back as 3, so a count checked by the sum
#: alone can render into the tracker looking like a number no downstream reader
#: can match. ``_Numbered`` carries the ``isascii`` conjunct that narrows it to
#: the ten characters intended.
_COUNT = _Numbered("")


def _validate_task_review(tracker: dict) -> None:
    """A task's review history, and the bar a task cannot reach ``[x]`` without.

    A reviewer returns three things: a verdict on spec, a verdict on quality,
    and verification evidence from an INDEPENDENT re-run. In this schema the
    first two are the severity counts — a review that found nothing wrong found
    nothing at either — and the third is the ``Evidence`` cell. A task may not
    stand at ``[x]`` while the review round that speaks for it says anything but
    ``accepted``, and ``accepted`` is pinned to ``Open 0``.

    ``Open`` is the count the round returned, not a cell later rounds rewrite.
    The committed fixture shows why that matters: ``P01-T01`` round 1 records
    the single Important finding it actually found and keeps recording it after
    the fix round resolved it, because the history of a review is not improved
    by editing it. The bar is therefore stated over the round that STANDS as the
    task's verdict, and every earlier round must have been evaluated rather than
    abandoned.

    Two things this deliberately does not do. It never reads ``Review Class``:
    the dial decides whether a reviewer runs, never what bar the reviewer
    applies, and a validator that relaxed under ``final-only`` would defeat the
    design it is here to hold. And it never requires a ``[x]`` task to HAVE a
    review row — that would be the same branch taken by the back door, since
    ``final-only`` buys no per-task reviewer at all. Whether a reviewer was owed
    is P06's contract; that a recorded one closed is this module's.
    """
    tasks = {row["id"]: row for row in tracker["tasks"]}
    by_task: dict[str, list[dict]] = {}
    for review in tracker["task_review"]:
        if review["task"] not in tasks:
            raise TrackerValidationError(
                f"review round {review['round']!r} names task "
                f"{review['task']!r}, which is not a task of this run; a verdict "
                "against nothing blocks nothing")
        by_task.setdefault(review["task"], []).append(review)
        if not _COUNT.fullmatch(review["round"]):
            raise TrackerValidationError(
                f"review round {review['round']!r} of task {review['task']!r} is "
                "not a round number")
        if not _TOKEN.fullmatch(review["reviewer"]):
            raise TrackerValidationError(
                f"review round {review['round']!r} of task {review['task']!r} "
                f"names {review['reviewer']!r} as its reviewer; ONE reviewer per "
                "round, because two reviewers on one row are two verdicts with "
                "no way to tell which one the State cell records")
        if review["reviewer"] == tasks[review["task"]]["owner"]:
            raise TrackerValidationError(
                f"task {review['task']!r} is reviewed by {review['reviewer']!r}, "
                "which is its own implementer; a task's implementer never "
                "reviews it, because self-review passes anything — and that is "
                "one of the things the review dial may never switch off")
        if review["intensity"] not in _REVIEW_INTENSITIES:
            raise TrackerValidationError(
                f"review intensity {review['intensity']!r} is outside "
                f"{_REVIEW_INTENSITIES!r}")
        if review["state"] not in _REVIEW_STATES:
            raise TrackerValidationError(
                f"unknown review state {review['state']!r}")
        adversarial = review["intensity"] == "adversarial"
        if adversarial != _TOKEN.fullmatch(review["adversarial"]):
            raise TrackerValidationError(
                f"review round {review['round']!r} of task {review['task']!r} "
                "must name the trigger that fired when, and only when, its "
                "intensity is adversarial; an adversarial round with no trigger "
                "is a raised bar with nothing behind it, and a standard round "
                "naming one is a trigger that fired and changed nothing")
        if review["state"] == "pending":
            if any(review[key] != "-" for key in _REVIEW_LIFECYCLE):
                raise TrackerValidationError(
                    f"review round {review['round']!r} of task "
                    f"{review['task']!r} is assigned and carries a verdict or "
                    "evidence; a round nobody has opened has neither")
        elif review["state"] == "reviewing":
            if review["package"] == "-":
                raise TrackerValidationError(
                    f"review round {review['round']!r} of task "
                    f"{review['task']!r} is in flight with no package; a "
                    "reviewer who was never handed one is a dispatch that was "
                    "lost")
            if any(review[key] != "-"
                   for key in _REVIEW_LIFECYCLE if key != "package"):
                raise TrackerValidationError(
                    f"review round {review['round']!r} of task "
                    f"{review['task']!r} is in flight and already reports a "
                    "result; a row that is both running and judged is one an "
                    "interrupted controller cannot classify")
        elif review["state"] in _REVIEW_EVALUATED:
            if any(review[key] == "-" for key in _REVIEW_EVIDENCE):
                raise TrackerValidationError(
                    f"review round {review['round']!r} of task "
                    f"{review['task']!r} returns a verdict without its package, "
                    "its report or its independent re-run evidence; all three "
                    "are owed in either direction, and the dial never switches "
                    "the re-run off")
            for key in (*_SEVERITIES, "open"):
                if not _COUNT.fullmatch(review[key]):
                    raise TrackerValidationError(
                        f"review round {review['round']!r} of task "
                        f"{review['task']!r} records {review[key]!r} as its "
                        f"{key} count; a finding count is ASCII digits, and a "
                        "number spelled otherwise renders back as one nothing "
                        "downstream can match")
            if int(review["open"]) != sum(int(review[key]) for key in _SEVERITIES):
                raise TrackerValidationError(
                    f"review round {review['round']!r} of task "
                    f"{review['task']!r} reports {review['open']!r} open against "
                    f"{tuple(review[key] for key in _SEVERITIES)!r} found; Open "
                    "is the three severities summed, because the bar is zero "
                    "open findings at EVERY severity and Minor is not a "
                    "deferral category")
            if (review["state"] == "accepted") != (int(review["open"]) == 0):
                raise TrackerValidationError(
                    f"review round {review['round']!r} of task "
                    f"{review['task']!r} is {review['state']!r} at "
                    f"{review['open']!r} open findings; a review closes when and "
                    "only when nothing is left open, and a block at zero is a "
                    "halt with nothing to fix")
        if review["state"] in _REVIEW_EVALUATED and adversarial:
            if review["adversarial_verdict"] not in _ADVERSARIAL_VERDICTS:
                raise TrackerValidationError(
                    f"adversarial verdict {review['adversarial_verdict']!r} is "
                    f"outside {_ADVERSARIAL_VERDICTS!r}; the pass either held or "
                    "it did not")
            if (review["state"] == "accepted"
                    and review["adversarial_verdict"] == "fail"):
                raise TrackerValidationError(
                    f"review round {review['round']!r} of task "
                    f"{review['task']!r} is accepted beside a failed adversarial "
                    "pass; that is the ratchet fired and then ignored")
        elif review["adversarial_verdict"] != "-":
            raise TrackerValidationError(
                f"review round {review['round']!r} of task {review['task']!r} "
                "records an adversarial verdict without having run, or having "
                "finished, an adversarial pass")
    for task_id, rounds in by_task.items():
        numbers = sorted(int(review["round"]) for review in rounds)
        if numbers != list(range(1, len(numbers) + 1)):
            raise TrackerValidationError(
                f"review rounds for task {task_id!r} are numbered {numbers!r}; "
                "they run 1..n with no gap and no repeat, and two rows sharing a "
                "number are two verdicts for one round with nothing to say which "
                "the run should obey")
        ordered = sorted(rounds, key=lambda review: int(review["round"]))
        for earlier, later in zip(ordered, ordered[1:]):
            if (_REVIEW_INTENSITIES.index(later["intensity"])
                    < _REVIEW_INTENSITIES.index(earlier["intensity"])):
                raise TrackerValidationError(
                    f"task {task_id!r} drops from {earlier['intensity']!r} to "
                    f"{later['intensity']!r} between rounds "
                    f"{earlier['round']} and {later['round']}; review intensity "
                    "ratchets UPWARD ONLY, and a re-review at a lower bar than "
                    "the one just applied is a run buying its way out of the bar "
                    "it raised")
            if earlier["state"] not in _REVIEW_EVALUATED:
                raise TrackerValidationError(
                    f"task {task_id!r} opened review round {later['round']} "
                    f"while round {earlier['round']} is still "
                    f"{earlier['state']!r}; a superseded round left in flight is "
                    "a reviewer holding a package nobody will read back")
        if tasks[task_id]["state"] == "[x]" and ordered[-1]["state"] != "accepted":
            raise TrackerValidationError(
                f"task {task_id!r} is complete while its last review round is "
                f"{ordered[-1]['state']!r}; a task may not reach '[x]' until the "
                "round that speaks for it is accepted at zero open findings, and "
                "no review class relaxes that")


#: Pending, being fixed, being re-reviewed, closed.
_FIX_ROUND_STATES = ("pending", "fixing", "re_reviewing", "complete")
#: Everything a fix round accumulates. A round nobody has opened carries none of
#: it; a completed one carries all of it.
_FIX_ROUND_LIFECYCLE = (
    "fixer", "findings", "commits", "verification", "re_review", "remaining",
)
#: What a round PRODUCES, as opposed to what it was handed. A round still fixing
#: has produced none of it, ``Remaining`` included: an outcome recorded against
#: work that has not finished is a result reported before the thing it reports
#: on happened.
_FIX_ROUND_PRODUCED = ("commits", "verification", "re_review", "remaining")
#: Three rounds, and a fourth halts to escalation rather than looping. A loop
#: that has spent three rounds without closing is not converging, and the answer
#: to that is a human, not another attempt.
_FIX_ROUND_LIMIT = 3
#: "Written down, and it is empty" — as distinct from ``-``, which is "not
#: written down". The fix loop closes on this word and on nothing else.
_NO_FINDINGS = "none"


def _unresolved(value: str) -> frozenset[str]:
    """The findings a completed round did NOT resolve. ``none`` is empty."""
    return frozenset() if value == _NO_FINDINGS else frozenset(_csv(value))


def _validate_fix_rounds(tracker: dict) -> None:
    """The fix loop: bounded at three, and closed only at zero.

    A fix round is scoped to a task, a phase or a gate — which is the reason
    there is no ``## Remediation`` section — and it carries its outcome
    directly. The loop closes on a round whose ``Remaining`` reads ``none``,
    which is the literal spelling of zero open findings at every severity.

    Three rounds is the bound, and the two ways a loop fails early are refused
    before the bound is even reached. A round that gives back every finding it
    was handed resolved nothing, and spending the next round on the identical
    list only delays the escalation. A round that re-raises a finding an earlier
    round resolved is oscillating, and the next round will undo it again. Both
    halt here rather than consuming the remainder.

    Note the order of the sequence rules below: a predecessor is required to be
    COMPLETE before its ``Remaining`` is read at all. Read off a round still
    fixing, that cell says ``-``, and ``-`` would measure as "nothing left",
    which is the exact opposite of what an unfinished round means.

    Nothing here reads ``Review Class`` either. The dial buys review; it never
    buys a shorter fix loop or a softer record of one.
    """
    scopes = {row["id"] for section in ("tasks", "phases", "gates")
              for row in tracker[section]}
    #: Tasks and phases both spell completion ``[x]``; a gate spells its own
    #: acceptance differently and is judged by ``_validate_gates``.
    finished = {row["id"] for section in ("tasks", "phases")
                for row in tracker[section] if row["state"] == "[x]"}
    by_scope: dict[str, list[dict]] = {}
    for fix in tracker["fix_rounds"]:
        if fix["scope"] not in scopes:
            raise TrackerValidationError(
                f"fix round {fix['round']!r} names scope {fix['scope']!r}, which "
                "is no task, phase or gate of this run")
        by_scope.setdefault(fix["scope"], []).append(fix)
        if not _COUNT.fullmatch(fix["round"]):
            raise TrackerValidationError(
                f"fix round {fix['round']!r} of {fix['scope']!r} is not a round "
                "number")
        if fix["state"] not in _FIX_ROUND_STATES:
            raise TrackerValidationError(
                f"unknown fix round state {fix['state']!r}")
        for commit in _csv(fix["commits"]):
            if not _COMMIT.fullmatch(commit):
                raise TrackerValidationError(
                    f"fix round {fix['round']!r} of {fix['scope']!r} records "
                    f"{commit!r} as a commit; a fix is the far end of the same "
                    "range proof the task rows carry, and a symbolic end "
                    "resolves somewhere else tomorrow")
        if fix["state"] == "pending":
            if any(fix[key] != "-" for key in _FIX_ROUND_LIFECYCLE):
                raise TrackerValidationError(
                    f"pending fix round {fix['round']!r} of {fix['scope']!r} "
                    "carries lifecycle state; a round nobody has opened has no "
                    "fixer, no findings and no result")
            continue
        if not _TOKEN.fullmatch(fix["fixer"]):
            raise TrackerValidationError(
                f"fix round {fix['round']!r} of {fix['scope']!r} names "
                f"{fix['fixer']!r} as its fixer; ONE fixer per round, carrying "
                "all of its findings, because two fixers on one round are two "
                "edits to one scope with no order between them and the second "
                "silently overwrites the first")
        if fix["findings"] == "-":
            raise TrackerValidationError(
                f"fix round {fix['round']!r} of {fix['scope']!r} names no "
                "findings; a round that is not carrying anything is a fixer "
                "dispatched against an empty list")
        if fix["state"] == "fixing":
            if any(fix[key] != "-" for key in _FIX_ROUND_PRODUCED):
                raise TrackerValidationError(
                    f"fix round {fix['round']!r} of {fix['scope']!r} is still "
                    "fixing and already reports commits, verification, a "
                    "re-review or an outcome; only a completed round records "
                    "what it produced")
        elif fix["state"] == "re_reviewing":
            if any(fix[key] == "-" for key in ("commits", "verification")):
                raise TrackerValidationError(
                    f"fix round {fix['round']!r} of {fix['scope']!r} is in "
                    "re-review without its commits and its verification "
                    "evidence; there is nothing for a re-reviewer to read")
            if any(fix[key] != "-" for key in ("re_review", "remaining")):
                raise TrackerValidationError(
                    f"fix round {fix['round']!r} of {fix['scope']!r} is in "
                    "re-review and already records its verdict")
        elif any(fix[key] == "-" for key in _FIX_ROUND_LIFECYCLE):
            raise TrackerValidationError(
                f"completed fix round {fix['round']!r} of {fix['scope']!r} is "
                "missing part of its lifecycle; a closed round records who "
                "fixed what, the commits, the verification, the re-review and "
                "what it left open")
    for scope, rounds in by_scope.items():
        numbers = sorted(int(fix["round"]) for fix in rounds)
        if numbers != list(range(1, len(numbers) + 1)):
            raise TrackerValidationError(
                f"fix rounds for {scope!r} are numbered {numbers!r}; they run "
                "1..n with no gap and no repeat")
        if len(rounds) > _FIX_ROUND_LIMIT:
            raise TrackerValidationError(
                f"{scope!r} records {len(rounds)} fix rounds; the loop is "
                f"bounded at {_FIX_ROUND_LIMIT}, and a round beyond it halts to "
                "escalation rather than looping again")
        ordered = sorted(rounds, key=lambda fix: int(fix["round"]))
        resolved: frozenset[str] = frozenset()
        for earlier, later in zip(ordered, ordered[1:]):
            if earlier["state"] != "complete":
                raise TrackerValidationError(
                    f"{scope!r} opened fix round {later['round']} while round "
                    f"{earlier['round']} is still {earlier['state']!r}; two "
                    "active rounds are two fixers editing one scope with no "
                    "order between them, and a finished round after an "
                    "unfinished one is a round that was skipped")
            just_resolved = frozenset(_csv(earlier["findings"])) - _unresolved(
                earlier["remaining"])
            if not just_resolved:
                raise TrackerValidationError(
                    f"fix round {earlier['round']} of {scope!r} gave back every "
                    f"finding it was handed and round {later['round']} follows "
                    "it; a round that resolves none of its targeted findings "
                    "halts to escalation immediately, without consuming the "
                    "remainder of the loop")
            resolved |= just_resolved
            re_raised = sorted(frozenset(_csv(later["findings"])) & resolved)
            if re_raised:
                raise TrackerValidationError(
                    f"fix round {later['round']} of {scope!r} carries "
                    f"{re_raised!r}, which an earlier round had already "
                    "resolved; fixes that oscillate halt immediately, because "
                    "the next round will undo them again")
        last = ordered[-1]
        if last["state"] == "complete" and _unresolved(last["remaining"]):
            raise TrackerValidationError(
                f"the fix loop for {scope!r} ends at round {last['round']} still "
                f"holding {last['remaining']!r}; it closes only on a round that "
                f"returns {_NO_FINDINGS!r} — zero open findings at every "
                "severity — and a remainder left standing is a loop that stopped "
                "early")
        if scope in finished and last["state"] != "complete":
            raise TrackerValidationError(
                f"{scope!r} is marked complete while its fix round "
                f"{last['round']} is still {last['state']!r}; work is not "
                "finished while a fixer is still carrying findings against it")


def _validate_tracker_semantics(tracker: dict) -> None:
    """Every per-section semantic rule, run as the last step of a parse.

    Structural parsing proves the bytes are a tracker; this proves they are a
    state the run can actually be in. Later phases extend the dispatcher rather
    than add a second entry point, so there is exactly one place a tracker is
    judged and no way to obtain an unvalidated one.
    """
    #: ``_validate_run`` leads because ``## Run`` is the only section the others
    #: read out of: the run id names the artifact paths, ``worker_limit`` bounds
    #: capacity, and the counters are what later records cite. A section table
    #: judged against a run header nobody has checked is judged against nothing.
    _validate_run(tracker)
    #: ``_validate_stages`` next because ``_validate_intent`` reads stage 03's
    #: state to decide whether the brief may be frozen, and a stage table that
    #: has not been proven to hold twelve known rows is not one to index into.
    _validate_stages(tracker)
    _validate_intent(tracker)
    _validate_questions(tracker)
    #: After both sections it spans, and never instead of either: it assumes the
    #: roster is four rows and the origins are in the enum, which is what the
    #: two validators above have just proven.
    _validate_intent_conflicts(tracker)
    #: Ahead of ``_validate_quorum``, ``_validate_tasks`` and ``_validate_gates``,
    #: all three of which resolve a ``Phase`` cell against this section. A phase
    #: roster that has not been proven to hold one row per id is not one to look
    #: a reference up in, and an unknown phase id is a fault to report against
    #: the phase table rather than against whichever row happened to cite it.
    _validate_phases(tracker)
    #: Before ``_validate_escalations``, which resolves an escalation's ``QID``
    #: against this section: a qid set that has not been proven well-formed is
    #: not one to look a reference up in.
    _validate_quorum(tracker)
    _validate_escalations(tracker)
    #: Last, and in this order. ``_validate_tasks`` checks a cited ``Decisions``
    #: id against its GRAMMAR only -- ``H-<n>`` or ``Q-<qid>``. It does NOT
    #: resolve the id to a decision: resolution is against ``decisions.md``,
    #: which this module never opens, and an in-tracker referential rule would
    #: reject ids that are valid but recorded elsewhere. The consumer that reads
    #: ``decisions.md`` owns existence; this module owns shape.
    #: ``_validate_gates`` closes the one reference ``_validate_phases`` had to
    #: make forward, from a phase to its gate.
    _validate_tasks(tracker)
    _validate_gates(tracker)
    #: After ``_validate_tasks``, which is what proves ``## Tasks`` holds one
    #: row per id: ``_validate_task_review`` resolves every ``Task`` cell into
    #: that roster and reads the owner out of it to refuse a self-review, and a
    #: roster with two rows for one task would hand it whichever owner the scan
    #: reached first.
    _validate_task_review(tracker)
    #: Last, because a fix round is scoped to a task, a phase OR a gate and it
    #: resolves its ``Scope`` against all three rosters at once. It also reads
    #: the ``[x]`` of a task or phase, which the two validators above have just
    #: proven to be a state in the enum.
    _validate_fix_rounds(tracker)


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


def repo_root(tracker: dict) -> str:
    """The repository this run was started against, as recorded at init.

    One statement, and it has to stay one statement. The alternative — deriving
    the root from where the run directory sits — is the single most dangerous
    line this schema could grow, because it fails invisibly: a run lives at
    ``docs/superpowers/runs/<run-id>/``, so directory arithmetic says
    ``parents[3]``, and a run kept anywhere else says something different, and
    NEITHER is a fact. A wrong root resolves no citation, so every brain that
    claimed ``specified`` or ``code-evidenced`` is demoted to
    ``engineering-judgement``, so every cluster lands below the adoption floor,
    so the run escalates every question it is ever asked — while looking like a
    correctly cautious quorum. No error, no exception, nothing goes red. The
    skill would appear to work and be useless.

    So the root is an ARGUMENT at ``initialize_run``, recorded once, validated
    on every read, and read back here verbatim. The function shares its name
    with the field it reads and with that argument, deliberately: all three are
    the interface the master plan pins, they live in three different namespaces,
    and a reader who follows the name from a caller to the cell finds no
    translation step to get wrong.
    """
    return tracker["run"]["repo_root"]


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


class LockUnavailableError(TrackerWriteError):
    """No usable OS lock primitive, or the lock resource changed underfoot.

    Distinct from ``LockBusyError`` on purpose, and a SIBLING of it rather than
    a parent: "wait and retry" is the right response to contention and exactly
    the wrong response to a primitive that cannot work, which would retry until
    the timeout and then retry again. A caller that does not care may catch
    ``TrackerWriteError`` and know only what that promises — nothing changed.
    """


class LockBusyError(TrackerWriteError):
    """Another holder has the run lock. Nothing was changed."""


#: The lock file is run-local and its name is stable. It is NOT ``progress.md``:
#: locking the tracker itself would mean holding a descriptor on the very inode
#: the atomic replace is about to swap out from under it.
LOCK_FILENAME = ".pipeline-auto.lock"

DEFAULT_LOCK_TIMEOUT_S = 10.0

#: Which ``flock`` failures mean "somebody else holds it". Deliberately narrow.
#: Everything outside this set is a broken primitive, not a competitor, and is
#: raised rather than retried: spinning out a timeout on ``ENOLCK`` would report
#: a contending holder that does not exist. ``flock`` performs no deadlock
#: detection, so ``EDEADLOCK`` is not in the POSIX set — it belongs only to the
#: Windows path, where ``msvcrt.locking`` does report it for contention.
_POSIX_CONTENTION = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}
_WINDOWS_CONTENTION = {errno.EACCES, errno.EDEADLOCK}


def select_lock_impl(fcntl_module, msvcrt_module):
    """Return ``(acquire, release, description)`` for the best primitive present.

    Takes the two modules as arguments rather than reading the globals so that
    the selection can be driven from a test without a second operating system.

    There is deliberately no third branch. A "no lock available, proceed
    anyway" fallback would turn every concurrency guarantee in this module into
    a comment: the tracker is the sole mutable state, many agents run at once,
    and two interleaved read-modify-writes each produce a well-formed file that
    no validator here can tell from a correct one. The loser's transition
    simply disappears. An explicit refusal is recoverable; that is not.

    The POSIX branch is preferred wherever it exists. The Windows branch is
    executable and follows the sibling skill's implementation, but it has never
    been run against a native Windows kernel, which its description says.
    """
    if fcntl_module is not None and hasattr(fcntl_module, "flock"):
        def acquire(descriptor: int) -> bool:
            try:
                fcntl_module.flock(descriptor,
                                   fcntl_module.LOCK_EX | fcntl_module.LOCK_NB)
            except OSError as exc:
                if exc.errno in _POSIX_CONTENTION:
                    return False
                raise
            return True

        def release(descriptor: int) -> None:
            fcntl_module.flock(descriptor, fcntl_module.LOCK_UN)

        return acquire, release, "POSIX flock"

    if msvcrt_module is not None and hasattr(msvcrt_module, "locking"):
        def acquire(descriptor: int) -> bool:
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt_module.locking(descriptor, msvcrt_module.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in _WINDOWS_CONTENTION:
                    return False
                raise
            return True

        def release(descriptor: int) -> None:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt_module.locking(descriptor, msvcrt_module.LK_UNLCK, 1)

        return acquire, release, "msvcrt locking; native Windows verification pending"

    raise LockUnavailableError(
        "no OS-backed lock primitive: fcntl.flock and msvcrt.locking are both "
        "unavailable, and this module never proceeds without a lock"
    )


@contextmanager
def _exclusive_lock(run_dir, *, timeout_s: float = DEFAULT_LOCK_TIMEOUT_S):
    """Hold the run-local exclusive lock, never unlinking its path.

    Unlinking a lock file on release is the classic way to hold a lock and
    still lose: a second holder opens the path, the first unlinks it, a third
    creates it afresh, and two holders end up locking two different inodes at
    one path while each believes it won. So the path is created once and kept
    forever, and the identity check after acquisition catches the case where
    somebody else removed and recreated it while this caller was waiting.

    ``timeout_s`` bounds the wait, not the attempt: zero means one honest,
    non-blocking try. A negative timeout is a caller bug rather than
    contention — its deadline is already past, so the loop would refuse a
    completely free lock and report a competitor that does not exist — and it
    is refused as ``LockUnavailableError`` because every non-contention lock
    failure here is that error. Both are ``TrackerWriteError``: nothing changed.
    """
    if timeout_s < 0:
        raise LockUnavailableError(
            f"lock timeout must be non-negative, not {timeout_s!r}")
    run_dir = Path(run_dir)
    lock_path = run_dir / LOCK_FILENAME
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise LockUnavailableError(
            f"cannot open run lock {lock_path}: {exc}") from exc
    acquired = False
    release = None
    try:
        acquire, release, _ = select_lock_impl(fcntl, msvcrt)
        #: One byte, because msvcrt.locking cannot lock a zero-length region.
        #: Written before acquisition, which is safe only because the content
        #: is meaningless: two racing creators write the same byte at the same
        #: offset of the same inode, and neither reads it back.
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                acquired = acquire(descriptor)
            except OSError as exc:
                raise LockUnavailableError(
                    f"cannot acquire run lock {lock_path}: {exc}") from exc
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise LockBusyError(
                    f"run lock {lock_path} busy after {timeout_s:.3f}s; "
                    "nothing changed")
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        try:
            held = os.fstat(descriptor)
            named = os.stat(lock_path)
        except OSError as exc:
            raise LockUnavailableError(
                f"cannot verify run lock identity {lock_path}: {exc}") from exc
        if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
            raise LockUnavailableError(
                f"the run lock resource changed while acquiring {lock_path}")
        yield
    finally:
        #: Releasing explicitly rather than relying on close, so that a release
        #: failure is separable from a close failure; the close then drops the
        #: lock regardless. Both run even when the body raised, or the run
        #: wedges on its own error path.
        if acquired and release is not None:
            try:
                release(descriptor)
            except OSError:
                pass
        os.close(descriptor)


def _sync_file(handle) -> None:
    """Push one file's buffered bytes past Python and past the OS cache.

    ``flush`` alone moves the bytes from Python's buffer into the kernel's,
    where a crash still loses them; ``fsync`` alone would sync a descriptor
    whose buffer has not been handed over yet. Both, in this order.
    """
    handle.flush()
    os.fsync(handle.fileno())


def _sync_directory(directory: Path) -> None:
    """Make a rename in ``directory`` durable, not merely visible.

    ``os.replace`` publishes the new name immediately, but the directory ENTRY
    is itself buffered: without this the swap can be lost by a crash that the
    file's own fsync did nothing to protect against. The ``nt`` early return is
    narrow on purpose — Windows has no directory descriptor to sync and its
    native semantics here remain unverified, so that platform is skipped rather
    than guessed at.
    """
    if os.name == "nt":  # native directory-sync semantics remain unverified
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


#: The mode ``progress.md`` is created with, before this process's umask is
#: applied. It is named here because ``os.replace`` carries the TEMP file's
#: mode onto the target: whatever the temp file is created with becomes the
#: tracker's mode on every single write, forever. Left to a helper it was
#: 0600, and each update silently narrowed a document a human reads.
#:
#: 0644 rather than ``open``'s 0666 default, and the cap is the point: the
#: tracker is the authority an autonomous controller obeys, so a second local
#: account being able to WRITE it is a different class of problem from being
#: able to read it. The run lock next door is 0600 because nothing but this
#: module ever opens it; the tracker is the opposite — it exists to be read.
TRACKER_MODE = 0o644


def _replace_tracker(run_dir, text: str, transition_id: str) -> None:
    """Replace ``progress.md`` atomically, and be exact about which of the
    three outcomes occurred.

    A write either did not happen, definitely happened, or MAY have happened.
    The third outcome is real rather than a hedge: after ``os.replace`` returns
    and before the directory fsync completes there is an interval in which a
    crash leaves a state no caller can tell from either neighbour. So there are
    two ``try`` blocks, not one.

    Everything up to and including ``os.replace`` is "nothing has happened
    yet" and fails as ``TrackerWriteError``: the old tracker is byte-intact and
    a retry is safe. The directory fsync afterwards is "it already happened,
    durably or not" and fails as ``UpdateOutcomeUncertain``: the caller must
    reconcile ``revision`` and ``last_transition`` before retrying.

    Collapsing the two into one ``except`` — even with a ``replaced`` flag
    deciding which exception to raise — is the edit that makes an autonomous
    retry double-apply, because every OSError raised after the replacement then
    has to be re-derived from a flag instead of from the block it came out of.
    Separating them structurally is what makes the claim checkable.

    The temp file is created inside ``run_dir`` so that it shares a filesystem
    with ``progress.md``. A temp file anywhere else makes ``os.replace`` a
    cross-device rename, which raises instead of swapping, and the atomicity
    this function exists for is gone. It is created with
    ``O_CREAT | O_EXCL | O_WRONLY``, which is the whole of the guarantee this
    needs: the open either creates that name or fails, so no file belonging to
    a second writer is ever opened, truncated, or unlinked by this call.
    """
    run_dir = Path(run_dir)
    progress = run_dir / "progress.md"
    descriptor = -1
    temporary: str | None = None
    try:
        #: pid and a nanosecond timestamp, not a random name: the exclusivity
        #: is carried by ``O_EXCL`` alone, and this only has to avoid colliding
        #: with a temp file a CRASHED earlier writer left behind. A collision
        #: is not a corruption — the open fails and the caller retries — so an
        #: unguessable name buys nothing inside a directory this run owns.
        candidate = run_dir / f".progress.{os.getpid()}.{time.time_ns()}.tmp"
        descriptor = os.open(
            candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, TRACKER_MODE)
        #: Assigned only AFTER the open succeeds. On EEXIST the path names a
        #: file this call did not create, and the cleanup below must not
        #: unlink another writer's work.
        temporary = str(candidate)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            #: The handle owns the descriptor from here, so the cleanup path
            #: below must not close it a second time.
            descriptor = -1
            handle.write(text)
            _sync_file(handle)
        os.replace(temporary, progress)
        #: The name is gone — it IS ``progress.md`` now — so this call no
        #: longer owns anything for the cleanup below to remove.
        temporary = None
    except OSError as exc:
        raise TrackerWriteError(
            f"tracker update {transition_id} failed before replacement; "
            f"the old tracker is intact and nothing changed: {exc}"
        ) from exc
    finally:
        #: Cleanup lives in ``finally`` rather than in the ``except OSError``
        #: because the two questions are different. What ESCAPES is a write
        #: outcome only for an OSError; anything else raised in this region —
        #: ``handle.write`` on text the encoder rejects, say — is a programming
        #: fault, and it propagates as itself rather than being laundered into
        #: a ``TrackerWriteError`` that would promise a caller a safe retry of
        #: a bug. What gets CLEANED UP is every one of them: nothing else ever
        #: removes this file, and a stranded ``.progress.*.tmp`` in a run
        #: directory is indistinguishable from one a live writer is holding.
        if descriptor >= 0:
            #: Only reachable when ``os.fdopen`` itself failed; past that the
            #: handle owns the descriptor and has closed it.
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass

    try:
        _sync_directory(run_dir)
    except OSError as exc:
        raise UpdateOutcomeUncertain(
            f"tracker update {transition_id} replaced progress.md, then the "
            "directory sync failed; the update may or may not survive a crash. "
            "Reconcile revision and last_transition before retrying — a blind "
            f"retry can double-apply: {exc}"
        ) from exc


#: The four ``## Run`` cells that say WHICH run this is. No transition changes
#: any of them: a run that can rename itself, restate its schema, move its base
#: commit or retarget its branch is one whose entire history can be reattributed
#: by a single mutation, and every artifact already written would still look
#: consistent with the new identity.
#: ``repo_root`` is one of these because "recorded at init" is a claim about
#: the whole run, not about its first revision. A transition that re-pointed it
#: would judge the citations resolved before it and the citations resolved after
#: it against two different repositories, and the quorum rows recording those
#: judgements say nothing about which root each was decided under.
_IDENTITY_KEYS = ("run_id", "schema", "base_commit", "target_branch",
                  "repo_root")

#: Every top-level key a tracker dict carries. ``mutate`` is free to rebuild the
#: dict rather than edit the one it was handed, and a rebuild that drops a
#: section is a real mistake — one that would otherwise surface as a ``KeyError``
#: from whichever guard happened to touch that section first, which tells the
#: caller nothing about what it did wrong.
_TRACKER_KEYS = frozenset(key for _, key, _ in _SECTIONS)


def _guard_frozen_intent(current: dict, proposed: dict) -> None:
    """The reconciled intent brief is immutable once stage 03 closes.

    A contradicting finding escalates and a human amends it; no transition
    rewrites it in place. Without this guard a later stage could quietly
    substitute a different brief and every downstream artifact would still
    look consistent — with the brief it now cites, rather than with the one the
    user actually approved at the gate.

    Scoped to a FROZEN brief on purpose. Stages 01 to 03 exist to write this
    row: the readers publish into it, the reconciliation names its result, and
    the gate freezes it. A guard that refused every ``## Intent`` edit would
    make the section unwritable by the only stages that ever write it.
    """
    frozen = [row for row in current["intent"]
              if row["id"] == "brief" and row["state"] == "frozen"]
    if not frozen:
        return
    after = [row for row in proposed["intent"] if row["id"] == "brief"]
    if len(after) != 1 or after[0] != frozen[0]:
        raise TrackerValidationError(
            "the intent brief is immutable once stage 03 closes; a contradicting "
            "finding escalates and the human amends it"
        )


def locked_tracker_update(run_dir: Path, *, transition_id: str, mutate,
                          timeout_s: float = DEFAULT_LOCK_TIMEOUT_S) -> dict:
    """Apply exactly one idempotent durable transition. The only way state changes.

    ``mutate`` is called with a deep copy of the current tracker and returns a
    tracker. ``transition_id`` names the transition and is its replay key.

    Order, and why each step is where it is:

    1. reject a malformed ``transition_id`` first. It is the replay key, so an
       id a resume cannot reproduce character for character is one whose replay
       would not be recognised as one;
    2. validate before locking, so a foreign or malformed run stops without
       ever creating a lock file inside somebody else's directory. Its result
       is deliberately discarded — see step 3;
    3. take the exclusive run lock, then **re-read and re-validate under it**.
       Anything read before the lock is stale by definition: the whole reason
       the lock exists is that another writer may land in the window between
       the preflight read and the acquisition, and a transaction that mutates
       the pre-lock snapshot overwrites whatever landed. It serialises nothing
       while looking exactly as though it does;
    4. replay check, against the state just read under the lock: the same
       ``transition_id`` returns current state and calls nothing, so a resume
       that re-issues its interrupted transition is inert. Checking the
       pre-lock snapshot instead would miss the case this contract is for — the
       resume racing the predecessor it is resuming;
    5. apply ``mutate`` to a DEEP copy. Shallow would alias ``current["run"]``
       and the ``## Intent`` rows into the proposal, and the two guards below
       would compare each object with itself and pass;
    6. refuse any change to run identity, and any rewrite of a frozen brief;
    7. stamp ``revision`` and ``last_transition``, so neither is the caller's to
       choose;
    8. render, then **reparse the render** — the canary. A mutation that would
       produce a tracker this module cannot read back is rejected before a
       single byte reaches disk. Re-running the validators on the proposed dict
       instead looks like the same check and is not: the dict is the input to
       the render, and it is the render that has to survive;
    9. replace atomically and return the REPARSED tracker, never the in-memory
       one, so a caller only ever sees state that survived a round trip.

    The three write outcomes cross this function unchanged. ``TrackerWriteError``
    (including ``LockBusyError`` and ``LockUnavailableError``) means nothing
    happened and a retry is safe; ``UpdateOutcomeUncertain`` means the
    replacement landed and only its durability is in doubt, and the right
    response to it is to re-issue this same ``transition_id`` and let the replay
    check settle which. Neither is caught here: collapsing them is what makes an
    autonomous retry double-apply.
    """
    if not _TOKEN.fullmatch(transition_id):
        raise TrackerValidationError(
            f"invalid transition identity {transition_id!r}: a transition id is "
            "one token, because it is the key a resume replays against")
    #: Read-only, outside the lock, and its result thrown away on purpose. It
    #: is the foreign-schema stop, not the read this transition applies to.
    validate_run(run_dir)
    with _exclusive_lock(run_dir, timeout_s=timeout_s):
        current = validate_run(run_dir)
        if current["run"]["last_transition"] == transition_id:
            return current
        proposed = mutate(copy.deepcopy(current))
        if not isinstance(proposed, dict) or frozenset(proposed) != _TRACKER_KEYS:
            raise TrackerValidationError(
                "mutate must return a tracker dict carrying every section; a "
                "mutate that edits in place still has to return what it edited")
        for key in _IDENTITY_KEYS:
            if proposed["run"].get(key) != current["run"][key]:
                raise TrackerValidationError(f"a transition cannot change {key}")
        _guard_frozen_intent(current, proposed)
        proposed["run"]["revision"] = str(int(current["run"]["revision"]) + 1)
        proposed["run"]["last_transition"] = transition_id
        canonical = render_tracker(proposed)
        reparsed = parse_tracker(canonical)
        _replace_tracker(run_dir, canonical, transition_id)
        return reparsed


#: A run id, and the whole grammar of one: an alphanumeric, then any number of
#: alphanumerics, dots, underscores and hyphens. No path separator, on purpose.
#: The id is interpolated into ``docs/superpowers/runs/<run_id>/decisions.md``,
#: so a ``/`` or a leading ``.`` in it addresses another run's audit trail — or
#: a repository file — while all three artifact cells still read as well-formed
#: paths afterwards. ``_TOKEN`` is the wrong grammar here for exactly that
#: reason: it admits ``/`` because the cells IT judges are paths.
_RUN_ID = _CharClass(_ALNUM, _ALNUM + "._-")

#: Where a run's own artifacts live. The spec: run artifacts under
#: ``docs/superpowers/runs/<run-id>/``, with large ephemera in a ``scratch/``
#: inside the run directory.
RUN_ARTIFACT_ROOT = "docs/superpowers/runs"

#: What an initialized run is waiting to do. Stage 01 dispatches exactly three
#: intent readers; the count is never reduced to fit capacity, and the action
#: names the dispatch rather than the stage so a resuming controller reads an
#: instruction instead of a label.
_FIRST_NEXT_ACTION = "dispatch-intent-readers"

#: The transition a run is born at. It occupies ``last_transition`` so that the
#: cell is never empty and so that the first real transition has a predecessor
#: to differ from; it is also a legal replay key, which is what keeps a second
#: identical initialization inert rather than ambiguous.
_INITIAL_TRANSITION = "initialized"


def _link_publish(path: Path, data: bytes, what: str, remedy: str) -> None:
    """Write bytes to a temp name, then LINK them into place so an existing
    file wins.

    ``os.replace`` — what ``_replace_tracker`` uses one screen up — overwrites
    whatever is at the target. That is right for an update, where the caller
    has read the current state under the lock and is replacing it deliberately,
    and it is wrong for both callers here. A first tracker must never overwrite
    a tracker a second controller already wrote, and an immutable artifact that
    can be overwritten is not immutable. ``os.link`` raises ``FileExistsError``
    rather than replacing, which is precisely that behaviour, and it is the
    atomic arbiter as well: two writers racing produce one winner and one
    ``FileExistsError``, with no window in which either sees a partial file.

    ``remedy`` is the one sentence appended when the conflict is refused, and
    it is a parameter rather than a constant because the two callers leave a
    human with genuinely different work to do: an occupied run directory is
    resumed, while two results published under one artifact identity have to be
    reconciled before either can be believed.

    Identical bytes are not a conflict. A controller that crashed between the
    link and recording that it had linked must find its own work on the retry,
    not a refusal it cannot act on, so the same content published twice is
    inert — and inert means the file is not rewritten, because an
    unlink-and-recreate would satisfy every content check while breaking each
    hard link and inode reference an audit trail holds to it.

    The temp file is created inside ``path``'s own directory, so ``os.link``
    stays within one filesystem — a cross-device link raises instead of
    linking, and the atomicity this exists for would be gone. It is created
    with ``O_CREAT | O_EXCL | O_WRONLY``: the open either creates that name or
    fails, so no file belonging to a second writer is ever opened or truncated.

    The two durability points are two blocks, for the same reason they are in
    ``_replace_tracker``. Everything up to and including the link is "nothing
    has happened yet" and fails as ``TrackerWriteError``. The directory fsync
    afterwards is "it already happened, durably or not" and fails as
    ``UpdateOutcomeUncertain``.
    """
    descriptor = -1
    temporary: str | None = None
    linked = False
    try:
        #: Inside the ``try``, not ahead of it. A parent that cannot be created
        #: — a plain file sitting where a directory is named — raises
        #: ``NotADirectoryError``, and an OSError that escapes as itself is a
        #: stop outside this module's exception family: a caller branching on
        #: ``TrackerError`` never sees it.
        path.parent.mkdir(parents=True, exist_ok=True)
        #: pid and a nanosecond timestamp, like ``_replace_tracker``'s: the
        #: exclusivity is carried by ``O_EXCL``, and this name only has to
        #: avoid colliding with what a CRASHED earlier writer left behind.
        candidate = path.parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
        #: ``TRACKER_MODE``, and the same reasoning reaches both callers: the
        #: link carries the temp file's mode onto the published name forever,
        #: and a run artifact created 0600 is an audit trail a human reading
        #: back what the run decided cannot open.
        descriptor = os.open(
            candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, TRACKER_MODE)
        #: Assigned only AFTER the open succeeds. On EEXIST the path names a
        #: file this call did not create, and the cleanup below must not
        #: unlink another writer's work.
        temporary = str(candidate)
        with os.fdopen(descriptor, "wb") as handle:
            #: The handle owns the descriptor from here, so the cleanup path
            #: below must not close it a second time.
            descriptor = -1
            handle.write(data)
            _sync_file(handle)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise TrackerWriteError(
                    f"{what} already exists at {path} with different content, "
                    "and is never overwritten: a second write under one "
                    f"identity is conflicting evidence, not an update. {remedy}"
                ) from None
        else:
            linked = True
    except OSError as exc:
        raise TrackerWriteError(
            f"cannot publish {what} at {path}; nothing was written: {exc}") from exc
    finally:
        #: In ``finally`` rather than in the ``except OSError``, for the reason
        #: ``_replace_tracker`` spells out: what ESCAPES is a write outcome
        #: only for an OSError, but what gets CLEANED UP is every path out of
        #: this block. The temp name is unlinked even when the link SUCCEEDED —
        #: the published file is a second link to the same inode, and the temp
        #: name is this call's own leftover either way.
        if descriptor >= 0:
            #: Only reachable when ``os.fdopen`` itself failed; past that the
            #: handle owns the descriptor and has closed it.
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
    if not linked:
        #: The identical-content case. This call created nothing, so there is
        #: no new directory entry for a sync to make durable, and claiming an
        #: uncertain outcome for it would be a lie in the safe direction.
        return
    try:
        _sync_directory(path.parent)
    except OSError as exc:
        raise UpdateOutcomeUncertain(
            f"{what} at {path} was created, then the directory sync failed; it "
            "may or may not survive a crash. Re-read it before binding a digest "
            f"to it — a blind republish is refused as conflicting evidence: {exc}"
        ) from exc


def publish_immutable(path: Path, content: str) -> str:
    """Publish content once, at a path that can never be rewritten.

    Returns the **sha256 hex digest of the published bytes**, not the path.
    That digest is the identity a later phase binds a worker result, a brain
    response or a quorum payload to, and it is the return value precisely
    because a path stays true when the contents change — which is the one thing
    this function exists to prevent.
    """
    data = content.encode("utf-8")
    _link_publish(
        path, data, "immutable artifact",
        "Publish the second result under its own identity; which of the two "
        "is the real one is a reconciliation, never an overwrite.")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Filesystem suitability
# ---------------------------------------------------------------------------
# Everything this module promises about writing rests on two filesystem
# semantics: POSIX advisory locking, which is what makes
# ``locked_tracker_update`` the sole writer, and a same-directory
# ``os.replace``, which is what makes a tracker update atomic. Several network
# filesystems honour neither, and honour neither QUIETLY — the lock is taken,
# the replace returns, and two controllers proceed believing they are alone.
#
# So the classification is a precondition of starting a run rather than a
# warning during one. `superb:pipeline` can ask a human to acknowledge an
# unknown mount; this skill runs unattended by definition, so there is nobody
# to ask and ``_filesystem_ack`` has no counterpart here.

#: The classifications, named so no caller has to retype a literal — the same
#: drift argument as ``SECTIONS``.
FILESYSTEM_SUPPORTED = "supported-local"
FILESYSTEM_UNSUPPORTED = "unsupported"
FILESYSTEM_UNKNOWN = "unknown"
FILESYSTEM_CLASSES = (FILESYSTEM_SUPPORTED, FILESYSTEM_UNSUPPORTED,
                      FILESYSTEM_UNKNOWN)

#: Local filesystems with working advisory locks and same-directory atomic
#: renames. Copied deliberately from `superb:pipeline`'s list rather than
#: re-derived: it is the same question about the same kernels.
_SUPPORTED_LOCAL_FILESYSTEMS = frozenset({
    "apfs", "btrfs", "ext2", "ext3", "ext4", "hfs", "hfsplus", "overlay",
    "tmpfs", "ufs", "xfs", "zfs",
})
#: Network and distributed filesystems, which the spec places outside the
#: guarantee outright.
_UNSUPPORTED_FILESYSTEMS = frozenset({
    "9p", "afs", "ceph", "cifs", "fuse.sshfs", "glusterfs", "lustre", "nfs",
    "nfs4", "remote", "smb", "smbfs",
})


def _system_name() -> str:
    """What this interpreter calls its platform, casefolded.

    A function rather than a module constant, and the one seam the platform
    dispatch below turns on — the same shape as ``select_lock_impl``'s
    arguments, and for the same reason: it is what lets a case exercise the
    macOS and Windows branches without a second machine.

    ``os.name`` is checked first because ``os.uname`` does not exist on
    Windows. Neither call needs an import this module does not already have,
    which is why ``platform`` is not in ``ALLOWED_IMPORTS``: it would buy a
    tidier spelling of a fact ``os`` already states.
    """
    if os.name == "nt":
        return "windows"
    return os.uname().sysname.casefold()


def _unescape_mount_point(value: str) -> str:
    """``mountinfo`` escapes space, tab, newline and backslash as ``\\0NN``.

    Hand-decoded rather than handed to ``re.sub`` — every grammar in this module
    states itself, and a three-digit octal escape is not a thing a regex engine
    says better. Compared raw instead, a mount point containing a space never
    matches the path under it and the run is judged against ``/``, which is the
    wrong answer in the safe direction exactly when it is not.
    """
    decoded = []
    index = 0
    while index < len(value):
        octal = value[index + 1:index + 4]
        if (value[index] == "\\" and len(octal) == 3
                and all(digit in "01234567" for digit in octal)):
            decoded.append(chr(int(octal, 8)))
            index += 4
        else:
            decoded.append(value[index])
            index += 1
    return "".join(decoded)


def _mountinfo_fs_type(mountinfo: str, resolved: Path) -> str:
    """The filesystem type of the DEEPEST mount containing ``resolved``.

    Deepest, not first and not the root: a repository on a local disk with its
    run directory on a network mount underneath is the arrangement this exists
    to catch, and both the first match and the root report ``ext4`` for it.

    A line this cannot read is skipped rather than believed. Raises when no
    line contains the path at all — the caller turns that into "unknown", which
    is the stop; there is no reading of an unanswerable probe that is safe to
    treat as an answer.
    """
    matches = []
    for line in mountinfo.splitlines():
        fields = line.split()
        try:
            separator = fields.index("-")
            mount_point = Path(_unescape_mount_point(fields[4]))
            fs_type = fields[separator + 1].casefold()
        except (ValueError, IndexError):
            continue
        if resolved == mount_point or mount_point in resolved.parents:
            matches.append((len(mount_point.parts), fs_type))
    if not matches:
        raise FilesystemSuitabilityError(
            f"no mount entry contains {resolved}")
    return max(matches)[1]


def _classify_fs_type(fs_type: str) -> str:
    """One filesystem type name to one classification.

    Unsupported is tested BEFORE supported, so a name that somehow reached both
    lists halts rather than proceeds. A name in neither is ``unknown`` — never
    "probably local", which is the default that makes the whole check
    decorative.
    """
    normalized = fs_type.casefold()
    if normalized in _UNSUPPORTED_FILESYSTEMS:
        return FILESYSTEM_UNSUPPORTED
    if normalized in _SUPPORTED_LOCAL_FILESYSTEMS:
        return FILESYSTEM_SUPPORTED
    return FILESYSTEM_UNKNOWN


def _existing_path(path: Path) -> Path:
    """The deepest ancestor of ``path`` that exists.

    A run directory is classified before it is created, so the thing to ask the
    kernel about is the nearest parent that is actually there.
    """
    candidate = path.resolve(strict=False)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.exists():
        raise FilesystemSuitabilityError(
            f"cannot identify an existing filesystem anchor for {path}")
    return candidate


def classify_filesystem(path: Path) -> str:
    """One of ``FILESYSTEM_CLASSES`` for the mount ``path`` lives on. Reads only.

    Linux answers from ``/proc/self/mountinfo``. Every other platform answers
    ``unknown``, and that is a statement about this module rather than about
    those platforms: macOS needs ``subprocess`` plus ``plistlib`` to reach
    ``diskutil`` and Windows needs ``ctypes``, and all three are capability
    widenings — the ability to execute another program, and the ability to call
    arbitrary native code — in a module whose import allowlist is a capability
    boundary. Unprobed is genuinely unknown, and unknown is a stop, so the
    consequence is stated rather than hidden: this halts a run started on
    macOS or Windows. Widening the allowlist to fix that is a decision for a
    human, not a convenience for this function.
    """
    if _system_name() != "linux":
        return FILESYSTEM_UNKNOWN
    try:
        resolved = _existing_path(path)
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        fs_type = _mountinfo_fs_type(mountinfo, resolved)
    except (OSError, UnicodeError, FilesystemSuitabilityError):
        #: A probe that failed is not evidence of a good filesystem. It takes
        #: the same exit an unlisted type does, and the run stops.
        return FILESYSTEM_UNKNOWN
    return _classify_fs_type(fs_type)


def initialize_run(run_dir: Path, *, run_id: str, base_commit: str,
                   target_branch: str, repo_root: str,
                   worker_limit: int) -> dict:
    """Create the first tracker for a run, or refuse and change nothing.

    This is the one write that does not go through ``locked_tracker_update``,
    and deliberately so in both directions. It *cannot* go through it: every
    step of that function reads, re-reads and replays against a tracker that has
    to be there already, and there is none. It does not *need* to: a run
    directory that does not exist yet cannot contend with anything, and the one
    race that remains — two controllers starting a run in the same directory —
    is arbitrated by ``os.link`` itself, atomically, with the loser told so.
    Taking the run lock here would also create ``.pipeline-auto.lock`` inside a
    directory before anything has established that it is this skill's to write
    in, which is the very thing ``locked_tracker_update`` validates first in
    order to avoid.

    Every argument is checked before the filesystem is touched, so a refusal is
    a read-only stop: a check that ran after the write would leave a tracker on
    disk for a run the caller was just told it could not start.

    The returned tracker is read back THROUGH the parser rather than being the
    dict that was rendered, so a caller only ever acts on state that survived a
    round trip.

    ``repo_root`` is REQUIRED and explicit, and this is the one place in the
    run where it is decided. It is not defaulted, not inferred from ``run_dir``,
    and not looked for by walking upward for a ``.git``: the caller knows which
    repository it is starting a run in, and every other way of finding out is a
    guess that fails silently later. Inside this body the parameter shadows the
    module-level ``repo_root`` accessor of the same name, which is harmless and
    deliberate — this function WRITES the cell and never reads one back, and
    keeping the three spellings identical is what makes the argument, the field
    and the accessor obviously the same fact.
    """
    if not _RUN_ID.fullmatch(run_id):
        raise TrackerValidationError(
            f"invalid run id {run_id!r}: an alphanumeric then alphanumerics, "
            "dots, underscores and hyphens. It names a directory under "
            f"{RUN_ARTIFACT_ROOT}/, so a separator or a leading dot in it "
            "addresses another run's artifacts")
    if not _COMMIT.fullmatch(base_commit):
        raise TrackerValidationError(
            f"base commit {base_commit!r} is not a full 40-character object "
            "name: it is one end of every range proof this run makes, and an "
            "abbreviation or a symbolic name resolves elsewhere tomorrow")
    if not _TOKEN.fullmatch(target_branch):
        raise TrackerValidationError(
            f"invalid target branch {target_branch!r}: a branch name is one "
            "token, because it is written into a table cell")
    if target_branch in ("main", "master"):
        raise TrackerValidationError(
            "pipeline-auto never targets main or master: success leaves a "
            "clean committed feature branch, and nothing is merged or pushed")
    #: The type is checked FIRST and separately, the way ``worker_limit``'s is.
    #: A ``Path`` is the argument a caller is likeliest to be holding, and the
    #: grammar below indexes its argument — so a ``Path`` reaching it raises
    #: ``TypeError``, outside this module's exception family, from a function
    #: whose whole contract is that a bad argument is a read-only stop.
    #: Coercing it instead would be the same lie the ``Path`` annotations were
    #: swept for: the interface says ``str`` and the caller spells ``str(...)``.
    if not isinstance(repo_root, str) or not _ABS_PATH.fullmatch(repo_root):
        raise TrackerValidationError(
            f"repo_root {repo_root!r} is not an absolute path string: it is "
            "recorded once, here, and is what every file:line citation this "
            "run makes is resolved against. A relative root resolves against "
            "whatever directory a controller happens to be standing in, which "
            "is a coincidence rather than a place, and a root that resolves "
            "nothing demotes every grounded answer below the adoption floor "
            "without raising anything")
    #: ``int(worker_limit)`` would be the shorter spelling and is the wrong
    #: one twice over: it raises ``ValueError`` on a string, which escapes this
    #: module's exception family, and it truncates a float into a limit the
    #: caller never asked for, in a cell nothing downstream re-derives.
    #:
    #: ``bool`` is excluded FIRST, and by type rather than by arithmetic,
    #: because it is a subclass of ``int``: a bare ``isinstance`` admits
    #: ``True``, ``True >= 1`` holds, and the cell is written as the string
    #: ``'True'``. ``## Run`` has no semantic validator — ``worker_limit`` is
    #: checked here and nowhere else — so that string is never caught again by
    #: anything that reads it to decide how many brain slots to reserve.
    #: ``False`` is already refused by ``< 1``, but only incidentally; naming
    #: both here makes the rule the type, so neither depends on the comparison.
    if (isinstance(worker_limit, bool)
            or not isinstance(worker_limit, int) or worker_limit < 1):
        raise TrackerValidationError(
            f"worker_limit {worker_limit!r} is not a positive integer; a run "
            "with no workers dispatches nothing and reports itself healthy")
    artifacts = f"{RUN_ARTIFACT_ROOT}/{run_id}"
    tracker = {
        "run": {
            "run_id": run_id,
            "schema": SCHEMA,
            "base_commit": base_commit,
            "target_branch": target_branch,
            #: The argument, verbatim. Not ``run_dir.parents[N]``, not a walk
            #: for ``.git``, not ``os.getcwd()`` — the caller was asked for
            #: this precisely so that nothing here has to guess at it.
            "repo_root": repo_root,
            "worker_limit": str(worker_limit),
            "agent_dispatch_count": "0",
            #: Absent, never predicted. Stages 05, 06 and 07 write these three.
            #: A path filled in now names a file that does not exist, and a
            #: resuming controller reading a cell cannot tell a promise from a
            #: product — it would skip the stage that was to produce it.
            "spec": "-",
            "master_plan": "-",
            "phase_plans": "-",
            "decisions": f"{artifacts}/decisions.md",
            "findings": f"{artifacts}/findings.md",
            "completeness_proposals": f"{artifacts}/completeness-proposals.md",
            #: Zero durable transitions so far, and the count is exact rather
            #: than decorative: ``locked_tracker_update`` derives the next
            #: revision by adding to what it reads, so a run born at 1 claims a
            #: transition that never happened and every later revision is off
            #: by one against the records that cite it.
            "revision": "0",
            "last_transition": _INITIAL_TRANSITION,
        },
        #: Stage 01 is ACTIVE, not pending. Twelve pending stages is monotone,
        #: so it would pass every ordering check — and then there is no row to
        #: read an action from, and no grounds to call the run complete. That
        #: shape once reported an untouched run as finished, ending it at stage
        #: 00 with every artifact unwritten and nothing erroring.
        "stages": [
            {
                "stage": stage,
                "stage_state": "active" if stage == STAGES[0] else "pending",
                "next_action": _FIRST_NEXT_ACTION if stage == STAGES[0] else "-",
            }
            for stage in STAGES
        ],
        #: Every other table starts empty, including ``## Intent``: its four
        #: rows are written together when stage 01 opens, and a partial roster
        #: is refused rather than read as "in progress".
        "intent": [],
        "questions": [],
        "quorum": [],
        "escalations": [],
        "tasks": [],
        "task_review": [],
        "fix_rounds": [],
        "phases": [],
        "gates": [],
    }
    canonical = render_tracker(tracker)
    #: The same canary ``locked_tracker_update`` runs, and for the same reason:
    #: a tracker this module cannot read back is rejected before a byte of it
    #: reaches disk. Re-validating the dict instead looks like the same check
    #: and is not — the dict is the INPUT to the render, and it is the render
    #: that has to survive.
    parse_tracker(canonical)
    #: The spec's stop, at the only place it can be a stop: BEFORE the run
    #: starts. It is the RUN DIRECTORY that is classified, not the repository —
    #: the tracker, the lock file and the atomic replace all live here, and a
    #: local checkout with its run directory on a network mount is the exact
    #: arrangement that passes a repository-level check and breaks every write
    #: guarantee anyway.
    #:
    #: Checking at the first transition instead would be worse than not
    #: checking: the tracker would already be on disk, and a controller
    #: resuming it reads a perfectly valid run and carries on.
    #:
    #: Not a quorum call either. Three brains know no more about this mount
    #: than the classifier does, and asking them produces three confident
    #: guesses about a fact.
    classification = classify_filesystem(run_dir)
    if classification != FILESYSTEM_SUPPORTED:
        raise FilesystemSuitabilityError(
            f"the filesystem at {run_dir} classifies as {classification!r}: "
            "this run cannot start there. The sole-writer guarantee is POSIX "
            "advisory locking and the tracker update is a same-directory "
            "os.replace; a filesystem that honours neither breaks both "
            "silently rather than loudly. Start the run on local storage. "
            "Nothing was written")
    _link_publish(
        run_dir / "progress.md", canonical.encode("utf-8"), "initial tracker",
        "Resume the existing run rather than initializing over it.")
    return validate_run(run_dir)


# ---------------------------------------------------------------------------
# Quorum contract (P03)
# ---------------------------------------------------------------------------
# A brain never types a number. It selects a grounding rung; the controller
# resolves that rung's evidence against the repository and derives the value
# from the ladder below. The ladder is a SCHEMA CONSTANT, frozen beside
# ``SCHEMA`` and absent from ``## Run``: a controller that can edit its own
# adoption bar has no adoption bar, and the freeze is what makes the
# self-serving move fail at the language level rather than at review.
#
# The adoption floor is ``code-evidenced``. ``convention-cited`` and everything
# below it cannot be adopted -- "the codebase does it this way" is not authority
# for a machine decision. That single rule is the pipeline's zero-assumption law
# re-encoded as arithmetic instead of prose.

#: The five numbers, written down once. Keyed by name rather than paired with
#: ``RUNG_NAMES`` by position, so that reordering P02's tuple cannot silently
#: remap the values; the comprehension below raises at import if the two sets
#: ever diverge. ``RUNGS`` wraps the comprehension's OWN dict and not this one:
#: a ``mappingproxy`` is a read-only view, not a copy, so a proxy over a named
#: module-level dict is editable by anything that can reach the name.
_RUNG_VALUES = {
    "specified": 0.95,
    "code-evidenced": 0.85,
    "convention-cited": 0.70,
    "engineering-judgement": 0.55,
    "speculation": 0.30,
}

#: Highest rung first. Every comparison between two rungs is an INDEX
#: comparison into this tuple and never a float margin: spread is "the winner's
#: rung is strictly higher than the runner-up's", full stop. There is no numeric
#: spread threshold anywhere in this phase, and a ``>= 0.15`` written between
#: two clusters would be the exact error the phase exists to prevent. The
#: substitution of index for value is only sound while the values fall strictly
#: along this order, which is asserted in the suite.
RUNG_ORDER = tuple(reversed(RUNG_NAMES))

#: Built OVER P02's names, never redefining them. A second list of the five
#: would pass every test the day it was written and drift the day either copy
#: was edited -- the same hole ``RUNG_NAMES`` was hoisted into P02 to close,
#: with an extra step.
RUNGS = MappingProxyType({name: _RUNG_VALUES[name] for name in RUNG_ORDER})

#: There is no ``RUNGS.get(rung, ...)`` in this module and there must never be.
#: ``RUNGS.get(rung_id, 0.55)`` reads as defensive -- 0.55 is
#: ``engineering-judgement``, and it is already here for the citation-demotion
#: rule below, so defaulting to it even looks principled -- and it silently
#: converts every malformed brain response into a legal vote. The value that
#: arrives is legal; the door it came through is not, which is precisely why
#: nothing downstream can detect it. An out-of-enum rung is SCHEMA-INVALID:
#: re-dispatch that brain once, then escalate, and never default.
ADOPTION_FLOOR = RUNGS["code-evidenced"]

#: Where a brain lands when its citation does not resolve. Strictly below the
#: floor, and that is load-bearing rather than incidental: a demotion target at
#: or above the floor would let an answer whose evidence could not be READ be
#: adopted anyway, through the very mechanism that exists to stop it.
DEMOTION_RUNG = "engineering-judgement"

#: Derived from the floor, never typed out, so the two cannot disagree.
ADOPTABLE = frozenset(
    name for name in RUNG_ORDER if RUNGS[name] >= ADOPTION_FLOOR)

#: Human decisions are depth 0. Depth 3 is three layers of inference away from
#: the last thing a human actually said, which is where a run stops building the
#: user's product and starts building its own.
DEPTH_CAP = 2

#: The drift budget caps DECISION AUTHORITY, not run cost: ``agent_dispatch_count``
#: is a separate counter and these never bound it. Checked before dispatch.
#: Escalations never count against it -- an escalation is the run asking for
#: help, and charging for it teaches the controller to stop asking.
BUDGET_PER_PHASE = 3
BUDGET_PER_RUN = 10

#: Two human-granted extensions per run, then the budget is terminal. A third
#: grant with no change to the underlying problem is not a budget problem.
MAX_EXTENSIONS = 2

#: Axes a machine may not settle at all, whatever its rung. A frozenset for the
#: same reason the ladder is frozen, and enumerated rather than inferred for the
#: reason ``_BLAST_RADII`` is closed: adoption checks a blast radius against
#: this list, so a member nobody wrote down matches nothing and the decision
#: that should have reached a human is adopted by three machines instead.
IRREVERSIBLE_AXES = frozenset({
    "product-scope", "destructive-data", "schema-migration", "external-service",
    "paid-dependency", "public-api", "wire-format", "authn-model", "authz-model",
    "runtime-cost", "licensing", "writes-outside-repo",
})


class QuorumError(TrackerError):
    """A quorum record is unusable.

    Under ``TrackerError`` so that a controller which already catches this
    module's root sees a quorum stop too: an exception outside the family
    escapes every ``except TrackerError`` already written, and an escaped stop
    is a run that carries on.
    """


class QuorumSchemaInvalid(QuorumError):
    """A brain response violates the response schema; it is never repaired.

    Distinct from ``QuorumIncomplete`` because the recoveries differ: this one
    re-dispatches that brain once and then escalates.
    """


class QuorumIncomplete(QuorumError):
    """The quorum cannot be finalised yet; the controller owes a dispatch."""


def _squash(text: str) -> str:
    """Question text as identity: whitespace runs collapsed, then case folded.

    ``casefold`` rather than ``lower`` because the same question retyped may
    arrive with any of the equivalences ``lower`` does not close.
    """
    return " ".join(text.split()).casefold()


def derive_qid(question: str, axis: str) -> str:
    """Stable identity for one question on one axis.

    WHAT THIS HASHES, exactly: the question text with runs of whitespace
    squashed to one space and case folded, then a NUL, then the axis token
    VERBATIM. Nothing else -- not the run id, not the phase, not the raiser,
    not the options, and above all not the decisions digest.

    The decisions digest is deliberately NOT an input. Including it would give
    the same question a new identity whenever anything else was decided, so a
    re-raise after a compaction would dispatch a second quorum and the run would
    re-litigate ground it had already settled -- with every record on disk
    looking well-formed. Context is recorded separately, as ``context_digest``,
    for audit.

    THE AXIS is the stage-03 question ``ID`` or ``_RESERVED_AXIS``. That column
    carries three roles -- intent-conflict id, axis token, and quorum axis
    namespace -- but they are three USES of one token, not three tokens: the
    ``ID`` column is a single identifier namespace and every role reads the same
    string. So hashing it is right, and it is hashed as it is written: the
    namespace is case-SENSITIVE (``_TOKEN`` admits upper case), so folding the
    axis would give two different questions one quorum. For the same reason the
    axis must already BE a legal token here -- a padded or spaced axis hashes to
    a qid the tracker's own cell can never be keyed by, and the disagreement
    would surface a phase later as a record nobody can look up.

    The NUL is a field separator and is therefore excluded from both fields.
    Without that refusal ``("a\\x00b", "c")`` and ``("a", "b\\x00c")`` produce the
    same bytes and so the same qid -- one quorum answering for two questions --
    and ``str.split`` does not treat NUL as whitespace, so squashing does not
    remove it.
    """
    if not isinstance(question, str):
        raise QuorumSchemaInvalid(
            f"question is {type(question).__name__}, not str; coercing it would "
            "hash a repr and mint a well-formed qid for a malformed record")
    if not isinstance(axis, str):
        raise QuorumSchemaInvalid(
            f"axis is {type(axis).__name__}, not str; an axis is a table cell "
            "before it is a hash input")
    if "\x00" in question:
        raise QuorumSchemaInvalid(
            "a question may not contain the field separator: it would let one "
            "question on one axis collide with another on another")
    if not _TOKEN.fullmatch(axis):
        raise QuorumSchemaInvalid(
            f"axis {axis!r} is not a legal question id: the axis namespace is "
            f"the stage-03 ids plus {_RESERVED_AXIS!r}, and a qid derived from "
            "anything else keys a row the tracker will not hold")
    squashed = _squash(question)
    if not squashed:
        raise QuorumSchemaInvalid(
            "a question that squashes to nothing has no identity; every blank "
            "question on an axis would share one qid and the first would answer "
            "for all the rest")
    payload = squashed.encode("utf-8") + b"\x00" + axis.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


# --- the brain-response schema -------------------------------------------
#
# A brain's response is the only thing standing between "three agents were
# asked" and "a decision was adopted", so the schema is strict in BOTH
# directions: every key must be present and no other key may be. Unknown-key
# rejection is not tidiness. ``confidence``, ``score`` and ``certainty`` are
# exactly the keys a brain that types a number invents, and a validator that
# ignores extras lets that number reach the arithmetic that exists so that no
# brain could type one. There is likewise no field through which a brain raises
# a question of its own -- the only exit is ``blocker`` -- and the unknown-key
# rule is what makes that unreachable rather than merely undocumented.
#
# What this validator does NOT do is judge grounding. An empty falsifier and a
# citation that will not resolve are both schema-VALID and are punished later,
# by demotion against the recorded ``repo_root``. The two verdicts have
# different recoveries -- re-dispatch against demote -- and collapsing them
# would re-ask a weak answer instead of demoting it, or demote a malformed one
# instead of re-asking it.
#
# A malformed response is not a low-confidence answer and not a blocker. It is
# NOT A RESPONSE: the brain is re-dispatched once, a second malformed reply
# leaves the quorum incomplete, and an incomplete quorum escalates. A quorum is
# never evaluated on fewer than three.

#: The twelve keys of a brain response, exhaustively. A key missing from this
#: set is a key a brain may omit and some later consumer will read anyway; a
#: key here that no prompt asks for rejects every real response.
_RESPONSE_KEYS = frozenset({
    "qid", "answer_key", "answer", "rung", "evidence", "consequences",
    "consistent_with", "forecloses", "blast", "alternatives",
    "what_would_change_my_mind", "blocker",
})

#: A ``decision`` citation carries ``decision`` where the others carry ``line``.
_EVIDENCE_KINDS = frozenset({"spec", "intent-brief", "decision", "repo"})

#: What an answer may be anchored to. ``decision_depth`` walks these, so an
#: answer anchored to nothing is depth-unbounded by construction.
_ANCHOR_KINDS = frozenset({"decision", "spec", "repo"})

#: A consequence is an assertion that would be verifiably TRUE of the
#: repository if the answer were adopted -- never a rationale. Free text here
#: is what makes an adopted decision unfalsifiable afterwards.
_CONSEQUENCE_KINDS = frozenset({"file-exists", "signature", "command-passes",
                                "config-value"})


def _text(value) -> bool:
    """A field that was actually filled in: a string with something in it.

    Whitespace is not an answer. A blank ``answer_key`` would cluster with
    every other blank one, so three brains that answered nothing would agree
    unanimously.
    """
    return isinstance(value, str) and bool(value.strip())


def _member(value, allowed) -> bool:
    """Enum membership for a value of ANY type, without raising on it.

    ``["code-evidenced"] in RUNGS`` raises ``TypeError``: unhashable. A
    validator that raises on a malformed response has not classified it, and
    the ``TypeError`` is outside this module's exception family, so it escapes
    every ``except TrackerError`` a controller has written -- the run dies on a
    brain's typo instead of re-dispatching it. Every shape a JSON document can
    carry has to come back as a violation string, so membership is tested only
    after the type is known.
    """
    return isinstance(value, str) and value in allowed


def _is_rung(value) -> bool:
    """Whether ``value`` is one of the five names, and nothing else.

    NO DEFAULT, here or anywhere else. ``RUNGS.get(rung, 0.55)`` reads as
    defensive -- 0.55 is ``engineering-judgement``, already in the module for
    the citation-demotion rule -- and it silently converts every malformed
    response into a legal vote. An out-of-enum rung is SCHEMA-INVALID: the
    brain is re-dispatched once and then the quorum escalates. The enum is
    consulted here, never re-typed: a second copy of the five names would pass
    on the day it was written and diverge the day either copy was edited.
    """
    return _member(value, RUNGS)


def _evidence_problems(evidence) -> list[str]:
    """Citations, checked against their own kind.

    ``line`` is an int and explicitly NOT a bool, for the reason
    ``initialize_run`` excludes bools from its counters: ``True == 1`` holds,
    so a flag that became a line number would pass every comparison and resolve
    against line 1 of whatever file was cited.
    """
    if not isinstance(evidence, list):
        #: Reported rather than iterated. ``for item in 12`` raises, and ``for
        #: item in "db/engine.py"`` walks the string character by character and
        #: reports one violation per letter.
        return ["evidence-not-a-list"]
    problems = []
    for item in evidence:
        if not isinstance(item, dict):
            problems.append("evidence-item-malformed")
            continue
        kind = item.get("kind")
        if not _member(kind, _EVIDENCE_KINDS):
            problems.append("evidence-item-malformed")
            continue
        if not _text(item.get("path")) or not _text(item.get("quote")):
            problems.append("evidence-item-malformed")
            continue
        if kind == "decision":
            if not _text(item.get("decision")):
                problems.append("evidence-item-malformed")
            continue
        line = item.get("line")
        if not isinstance(line, int) or isinstance(line, bool):
            problems.append("evidence-item-malformed")
    return problems


def _consequence_problems(consequences) -> list[str]:
    if not isinstance(consequences, list) or not consequences:
        return ["empty-consequences"]
    problems = []
    for item in consequences:
        if not isinstance(item, dict):
            problems.append("consequence-item-malformed")
            continue
        if (not _member(item.get("kind"), _CONSEQUENCE_KINDS)
                or not _text(item.get("subject"))
                or not _text(item.get("value"))):
            problems.append("consequence-item-malformed")
    return problems


def _anchor_problems(anchors) -> list[str]:
    if not isinstance(anchors, list) or not anchors:
        return ["empty-consistent-with"]
    problems = []
    for item in anchors:
        if (not isinstance(item, dict)
                or not _member(item.get("kind"), _ANCHOR_KINDS)):
            problems.append("consistent-with-item-malformed")
    return problems


def _blast_problems(blast) -> list[str]:
    """The blast radius is matched against ``IRREVERSIBLE_AXES`` before a
    machine may adopt, so a member that is not a token matches no axis: an
    answer whose blast radius is ``[12]`` clears the irreversibility check by
    being unrecognisable. That is the same fail-open shape ``_BLAST_RADII`` is
    closed against, arriving through the response instead of the tracker.
    """
    if not isinstance(blast, list):
        return ["blast-not-a-list"]
    return ["blast-item-malformed" for item in blast if not _text(item)]


def _alternative_is_stated(alternative) -> bool:
    """A second-best the brain actually considered: a key, a rung, a reason.

    The rung enum is not relaxed inside an alternative. An alternative's rung
    is read by the same arithmetic as the winner's, so free text there is the
    same number-from-nowhere with one level of nesting in front of it.
    """
    if not isinstance(alternative, dict):
        return False
    if not _text(alternative.get("answer_key")):
        return False
    if not _text(alternative.get("reason")):
        return False
    return _is_rung(alternative.get("rung"))


def validate_brain_response(payload: dict) -> list[str]:
    """Every schema violation in one response. An empty list means it is legal.

    Strict in both directions: an unknown key is a violation because a brain
    that types a number invents exactly ``confidence``, ``score`` or
    ``certainty``, and a validator that ignores extras lets that number reach
    the arithmetic. There is no field through which a brain can raise a
    question of its own; the only exit is ``blocker``, and a blocker does not
    suspend the schema -- if it did, every malformed reply could be relabelled
    as a legitimate exit, and an exit is recorded as an outcome while a
    malformed reply is a re-dispatch.

    An out-of-enum rung is SCHEMA-INVALID and is never defaulted: no violation
    returned here names a rung the brain could have meant, because naming one
    is the first half of substituting it.

    Grounding is NOT judged. An empty falsifier is legal and is punished later
    by demotion; an unresolvable citation is legal here for the same reason and
    is resolved elsewhere, against the recorded ``repo_root``. This function
    reads no file: resolving a citation against the process's working directory
    would demote every answer in a run whose repository is anywhere else, put
    everything below the floor and escalate the entire run while looking
    correctly cautious.

    Total by construction: any JSON value at all comes back as a list of
    violation strings. A raise here would be an unhandled failure outside this
    module's exception family, on the one path that exists to handle a brain
    getting it wrong.
    """
    if not isinstance(payload, dict):
        return ["response-not-an-object"]
    problems = []
    #: Sorted by ``str`` rather than naturally: a non-string key is malformed
    #: input too, and ``sorted`` over mixed types raises.
    for key in sorted(set(payload) - _RESPONSE_KEYS, key=str):
        problems.append(f"unknown-field:{key}")
    for key in sorted(_RESPONSE_KEYS - set(payload), key=str):
        problems.append(f"missing-field:{key}")

    for key in ("qid", "answer_key", "answer"):
        if not _text(payload.get(key)):
            problems.append(f"empty-field:{key}")

    #: Present-and-illegal and absent are the same fact -- this response has no
    #: legal rung -- and they take the same recovery.
    if "rung" in payload:
        if not _is_rung(payload["rung"]):
            problems.append("rung-not-in-enum")
    else:
        problems.append("rung-not-in-enum")

    problems.extend(_evidence_problems(payload.get("evidence")))
    problems.extend(_consequence_problems(payload.get("consequences")))
    problems.extend(_anchor_problems(payload.get("consistent_with")))

    forecloses = payload.get("forecloses")
    if not isinstance(forecloses, list) or not any(
            _text(entry) for entry in forecloses):
        problems.append("empty-forecloses")

    problems.extend(_blast_problems(payload.get("blast")))

    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        #: RESERVED CODE. This is the one violation that drives the single
        #: permitted re-dispatch, so an unstated second-best reports as the
        #: same fact as no second-best: a brain that offers neither has not
        #: considered one, and that is a re-ask rather than a lower rung.
        problems.append("empty-alternatives")
    elif not all(_alternative_is_stated(item) for item in alternatives):
        problems.append("empty-alternatives")

    #: Absent is not empty. An empty falsifier is a weak answer and legal;
    #: ``null`` is the field declined, and the field is required.
    if not isinstance(payload.get("what_would_change_my_mind"), str):
        problems.append("falsifier-not-a-string")

    #: ``null`` is the legal "no blocker". A blank one is an exit taken without
    #: a reason: the controller would have to escalate something it cannot
    #: describe.
    blocker = payload.get("blocker")
    if blocker is not None and not _text(blocker):
        problems.append("blocker-not-a-string")
    return problems


# --- pricing a claim: evidence resolution and rung demotion ---------------
#
# A declared rung is a CLAIM about where an answer came from, and every rung
# above ``engineering-judgement`` is a claim that something on disk says so.
# This is the only place that claim is ever checked against the disk. A brain
# claiming ``specified`` or ``code-evidenced`` must cite a place that resolves
# AND contains what it said was there; otherwise the answer is priced at
# ``engineering-judgement``, which is strictly below the adoption floor, so an
# inflated claim is defeated arithmetically rather than argued with.
#
# DEMOTION, NOT REJECTION. Rejecting a response discards the information in it
# and hands a malformed brain a veto over the quorum; demotion prices the claim
# at what it turned out to be worth and lets the floor do the rest. And
# demotion never PROMOTES: a ``speculation`` with a dangling citation stays at
# ``speculation``, because every rule here is a ceiling and a ceiling that
# raised a weak answer would be a floor.
#
# WHAT WOULD HAPPEN IF THE RESOLUTION WERE SKIPPED, or run against the wrong
# root: nothing visible. Every grounded answer falls to 0.55, every cluster
# lands below 0.85, and the run escalates every question it is ever asked while
# looking like a correctly cautious quorum. No error, no exception, no failing
# test. That is why the root is a ``## Run`` field read back through
# ``repo_root`` and is NEVER computed here -- not by ``parents[N]``, not by
# walking for ``.git``, not from ``__file__`` -- and why a root that is not a
# usable directory is a STOP rather than a demotion: it is the one wrong root
# this function can detect, and detecting it silently would be the invisible
# failure with a cause nobody could find.

#: What each rung must be able to SHOW, checked only against evidence that
#: resolved. Total over the five names on purpose: a rung absent from this
#: table would require no evidence at all, which is how a new top rung gets
#: added and quietly bypasses the only check that prices it. Keyed by name and
#: asserted in the suite to cover ``RUNGS`` exactly, so the two cannot drift.
#: ``convention-cited`` needs TWO exemplars because one occurrence is an
#: instance and a convention is a repetition.
_RUNG_EVIDENCE = MappingProxyType({
    "specified": (frozenset({"spec", "intent-brief", "decision"}), 1),
    "code-evidenced": (frozenset({"repo"}), 1),
    "convention-cited": (frozenset({"repo"}), 2),
    "engineering-judgement": (frozenset(), 0),
    "speculation": (frozenset(), 0),
})

#: An answer anchored only in what the code already does has nothing the user
#: actually said behind it. ``repo`` is a legal anchor kind and is deliberately
#: not enough on its own.
_INTENT_ANCHORS = frozenset({"decision", "spec"})


def _decision_section(text: str, decision_id: str) -> str | None:
    """One ``## <D-ID> — <title>`` record's own lines, or ``None``.

    Scoped to the record rather than searched across the document because
    ``decisions.md`` holds every decision the run has made: a quote looked up
    document-wide attributes one record's words to another, and depth and
    ``consistent_with`` are computed from exactly those attributions.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        if line[3:].split("—")[0].strip() != decision_id:
            continue
        end = index + 1
        while end < len(lines) and not lines[end].startswith("## "):
            end += 1
        return "\n".join(lines[index:end])
    return None


def _resolution_root(repo_root: str) -> Path:
    """The recorded root, checked for being usable. Nothing is derived here.

    ``_validate_run`` checks the ``## Run`` cell as a STRING and says why: a
    tracker read from a checkout that has since moved must still parse, and
    "this path is not where it was" is a fact for the code resolving a citation
    to report. This is that code. A root that is blank, not a string, or not a
    directory resolves NOTHING, so demoting on it would put every answer in the
    run at 0.55 and escalate everything with no exception anywhere to find it
    by. It is a stop, and it is ``QuorumError`` rather than
    ``QuorumSchemaInvalid`` because no brain did anything wrong: re-dispatching
    one would re-run the whole quorum against the same broken root.
    """
    if not isinstance(repo_root, str) or not repo_root.strip():
        raise QuorumError(
            f"repo_root {repo_root!r} is not a path: it is what every file:line "
            "citation in this run is resolved against, and an unusable one "
            "demotes every grounded answer in the run without raising")
    root = Path(repo_root)
    try:
        usable = root.is_dir()
    except OSError:
        usable = False
    if not usable:
        raise QuorumError(
            f"repo_root {repo_root!r} is not a directory this process can read; "
            "every citation would fail to resolve, every cluster would land "
            "below the adoption floor, and the run would escalate every "
            "question while looking like a correctly cautious quorum")
    return root.resolve()


def _cited_file(item: dict, root: Path) -> str | None:
    """The text of the file a citation names, or ``None`` if it is unreadable.

    The resolved path must lie INSIDE the root. An absolute citation, or one
    that climbs out with ``..``, reads the same file against every root, which
    is exactly the property the recorded root exists to deny: such a citation
    would be graded against a file this run does not contain and would resolve
    identically no matter which repository the run was started against.
    """
    path = item.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    try:
        target = (root / path).resolve()
        if target != root and root not in target.parents:
            return None
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        #: ``OSError`` covers the missing file, the directory cited as a file,
        #: and the unreadable one; ``UnicodeError`` the binary one;
        #: ``ValueError`` an embedded NUL. Each is a demotion, and none of them
        #: may leave this module as an exception outside ``TrackerError``.
        return None


def _evidence_resolves(item, root: Path) -> bool:
    """True only if the cited place exists AND says what the brain said it says.

    THE WHOLE POINT IS THE SECOND HALF. A checker that confirms the file exists
    is a rubber stamp: it passes every response that merely names a real path,
    which is every response a brain could produce by guessing. The quote is
    compared with whitespace runs squashed and case folded, because a brain
    retyping a line is not a brain inventing one -- but the words themselves
    are not relaxed, and a quote that squashes to nothing is refused outright
    since the empty string is contained in every line of every file.

    Total over any JSON value. A malformed citation is a citation that does not
    resolve, never an exception: ``AttributeError`` from ``.get`` on a string
    and ``TypeError`` from indexing an int are both outside ``TrackerError`` and
    would kill the run on a brain's typo instead of demoting it.
    """
    if not isinstance(item, dict):
        return False
    quote = item.get("quote")
    if not isinstance(quote, str):
        return False
    claim = _squash(quote)
    if not claim:
        return False
    text = _cited_file(item, root)
    if text is None:
        return False
    if item.get("kind") == "decision":
        #: A decision citation carries ``decision`` where the others carry
        #: ``line``: a record moves down the file every time another is
        #: appended, so a line number into an append-only ledger is a citation
        #: that rots.
        decision = item.get("decision")
        if not isinstance(decision, str):
            return False
        section = _decision_section(text, decision)
        if section is None:
            return False
        return claim in _squash(section)
    number = item.get("line")
    #: ``True == 1`` holds, so a flag arriving where a line number belongs
    #: would resolve against line 1 of whatever file was cited.
    if not isinstance(number, int) or isinstance(number, bool):
        return False
    lines = text.splitlines()
    #: One-based, and bounded at BOTH ends. ``0 <= number < len(lines)`` would
    #: accept ``-1`` and read the last line of the file -- a citation to a place
    #: the brain never named.
    if not 1 <= number <= len(lines):
        return False
    return claim in _squash(lines[number - 1])


def _not_above(rung: str, limit: str) -> str:
    """The LOWER of two rungs, by index into the ladder and never by value.

    Every rule in ``effective_rung`` is a ceiling. Returning the limit outright
    would make it a floor, and a floor raises a ``speculation`` that cited
    nothing to 0.55 -- the demotion rule promoting the answers it exists to
    catch. Index, not float: a value comparison here would be the numeric
    threshold this phase forbids.
    """
    return RUNG_ORDER[max(RUNG_ORDER.index(rung), RUNG_ORDER.index(limit))]


def _demotion_reason(response: dict) -> str | None:
    """Why this response only LOOKS grounded, or ``None`` if it does not.

    Three ways to cite real files and still be ungrounded: an answer nothing
    could change, a second-best the brain grounds exactly as well as its answer
    (which is the brain reporting that it could not separate them), and an
    answer anchored only in what the code already does.
    """
    falsifier = response.get("what_would_change_my_mind")
    #: Tested as a string, never coerced: ``str(None).strip()`` is ``'None'``
    #: and truthy, so coercion turns the declined field into the best-looking
    #: falsifier in the run.
    if not isinstance(falsifier, str) or not falsifier.strip():
        return "empty-falsifier"
    declared = response.get("rung")
    alternatives = response.get("alternatives")
    if not isinstance(alternatives, list):
        alternatives = []
    for alternative in alternatives:
        if isinstance(alternative, dict) and alternative.get("rung") == declared:
            return "second-best-in-the-same-rung"
    anchors = response.get("consistent_with")
    if not isinstance(anchors, list):
        anchors = []
    #: ``_member``, never ``in`` directly: ``kind`` is brain-supplied JSON and
    #: ``["decision"] in _INTENT_ANCHORS`` raises ``TypeError``: unhashable.
    #: That is outside ``TrackerError``, so it escapes every handler a
    #: controller has written and kills the run on a brain's typo.
    if not any(isinstance(anchor, dict)
               and _member(anchor.get("kind"), _INTENT_ANCHORS)
               for anchor in anchors):
        return "anchored-only-in-repository-code"
    return None


def effective_rung(response: dict, repo_root: str) -> str:
    """The rung this response actually EARNED, as a name.

    Order is load-bearing: evidence is resolved from disk BEFORE any comparison
    between responses. Resolving after the comparison lets a top-rung response
    with a dangling citation win on a claim no file supports, and the winner is
    then recorded as the rung it declared rather than the rung it earned.

    An out-of-enum rung RAISES and is never defaulted. ``RUNGS.get(rung, 0.55)``
    reads as defensive -- 0.55 is ``engineering-judgement``, already in this
    module for the demotion rule -- and converts every malformed response into a
    legal vote. The value that arrives is legal; the door it came through is
    not, which is exactly why nothing downstream could detect it.
    """
    if not isinstance(response, dict):
        raise QuorumSchemaInvalid(
            f"a brain response is {type(response).__name__}, not an object; "
            "there is no rung to price and none is supplied")
    declared = response.get("rung")
    if not _is_rung(declared):
        raise QuorumSchemaInvalid(
            f"rung {declared!r} is outside the enum and is never defaulted: a "
            "substituted rung is a number arriving through an illegal door")
    root = _resolution_root(repo_root)
    evidence = response.get("evidence")
    if not isinstance(evidence, list):
        return _not_above(declared, DEMOTION_RUNG)
    #: EVERY citation must resolve, not merely the ones that happen to. A
    #: response that cites one real file and one invented one has shown the
    #: invented one is not checked.
    resolved = [item for item in evidence if _evidence_resolves(item, root)]
    if len(resolved) != len(evidence):
        return _not_above(declared, DEMOTION_RUNG)
    #: Subscript, not a lookup with a fallback. The rung is already known to be
    #: in the enum, and the table covers the enum exactly.
    kinds, minimum = _RUNG_EVIDENCE[declared]
    #: ``evidence: []`` is SCHEMA-VALID -- the response validator judges shape
    #: and deliberately reads no file -- so counting is what meets it here.
    #: Indexing the list instead would raise ``IndexError``, outside
    #: ``TrackerError``, on the one path that exists to price a weak answer.
    #: ``_member`` for the reason ``_demotion_reason`` uses it: a ``kind`` that
    #: arrived as a list or an object is unhashable, and a bare ``in`` against
    #: the frozenset would raise outside ``TrackerError``. A citation may resolve
    #: with such a ``kind`` -- ``_evidence_resolves`` compares it with ``==`` --
    #: so this membership test really is reached.
    qualifying = sum(1 for item in resolved
                     if _member(item.get("kind"), kinds))
    if qualifying < minimum:
        return _not_above(declared, DEMOTION_RUNG)
    if _demotion_reason(response) is not None:
        return _not_above(declared, DEMOTION_RUNG)
    return declared


# --- the decisions contract: what this run has already settled ------------
#
# ``decisions.md`` is the run's audit trail. It is append-only, it is the only
# evidence that anything was DECIDED rather than assumed, and the two things
# this section does to it are read it strictly and project it narrowly.
#
# STRICTLY, because two adopted decisions contradicting each other on one axis
# is a read-only stop of the same severity as a foreign schema. A trail holding
# both answers has already failed: every later reader -- the contradiction
# check, the depth walk, the terminal report -- picks one of the two by
# accident of iteration order, and whichever it picks is defensible, so nothing
# downstream can notice. The file is not repaired and no answer is preferred;
# the run stops and a human is told which two records disagree.
#
# NARROWLY, because ``decisions-effective.md`` is the only decision material a
# brain ever sees, and what it omits is as load-bearing as what it carries. See
# ``project_decisions``.

#: The two provenances, and the whole of them. ``Provenance`` is recorded even
#: though the id already implies it, because a provenance read only by a
#: validator has informed nobody -- it has to be visible in the record, in the
#: tracker index and in the terminal report.
_PROVENANCES = frozenset({"human", "quorum"})

#: The five decision actions, and nothing else is honoured. ``dispatch``'s
#: extension is here beside ``quorum``'s because TWO BUDGETS MEAN TWO
#: AUTHORITIES: the drift budget caps decision authority and the dispatch
#: budget caps run cost, and one action shared between them would let a grant
#: against either refill the other. A set of four that dropped
#: ``dispatch.extend-budget`` would make the one action that unblocks a
#: hard-ceilinged run unwritable -- the record the human signed would parse as
#: an unknown action, which is a read-only stop, which is a run that cannot be
#: restarted by the very grant that exists to restart it.
_DECISION_ACTIONS = frozenset({
    "task.resume", "quorum.adopt", "quorum.extend-budget",
    "dispatch.extend-budget", "none",
})

#: Both grants, named once. They are the two actions whose ANSWER carries a
#: ceiling, which is why ``project_decisions`` withholds them from brains.
_EXTENSION_ACTIONS = frozenset({"quorum.extend-budget", "dispatch.extend-budget"})

#: A generic approval is not an answer to an unresolved choice, and this holds
#: for a quorum answer of "proceed" exactly as it holds for a human's. The
#: empty string is a member so that a present-but-blank ``Answer`` is caught by
#: the same rule rather than by the absence of one.
#:
#: WIDER THAN THE FOUR THE BRIEF NAMED, ON PURPOSE, and the widening is declared
#: here rather than left to be inferred from the set. Every member past
#: ``approved``/``yes``/``continue``/``proceed`` is a RUBBER STAMP: a token that
#: signals assent to whatever was proposed and carries no content of its own, so
#: two of them recorded on one axis key identically and "agree" without either
#: having said anything. ``ok``/``okay``/``lgtm``/``sure``/``agreed``/``sounds
#: good`` are assent to a proposal; ``do it`` is assent to an action;
#: ``pending user response`` is the placeholder standing where an answer will
#: go. None of them names the thing chosen.
#:
#: ``no`` IS NOT A MEMBER, and its absence is the boundary of the rule. A rubber
#: stamp is always affirmative -- it is the reflex of waving something through --
#: and a refusal is the one thing a reflex never produces. "no" to "should we add
#: a second datastore?" is a human's legitimate rejection: it settles the axis,
#: it is what the user actually said, and the record must be able to hold it.
#: Refusing it would make the one answer a generic-approval rule exists to
#: protect unwritable.
#: ``go`` IS NOT A MEMBER EITHER, for a different reason: it is a language, and
#: this rule is applied to the derived ``answer_key`` as well as to the whole
#: answer. "go" answering "which language backs the worker pool?" is a real
#: choice, and refusing it would make a legal adopted answer unrecordable.
#:
#: ``yes`` STAYS, in every record, and the rule does not vary by provenance.
#: The spec settles both halves outright. On uniformity, lines 752-753: "The
#: generic-approval rejection carries over unchanged: a quorum answer of
#: ``proceed`` is as empty as a human's" -- stated with the human case as the
#: baseline the quorum case is measured against, so relaxing it for human
#: records inverts the sentence. On ``yes`` specifically, line 427 names it as
#: THE reflex: "the reflex answer to 'may I continue?' is yes."
#:
#: An earlier draft of this comment argued from the options test instead, and
#: that argument was wrong -- not because the conclusion was wrong, but because
#: the options test is an admissibility criterion and the reasoning ran the
#: wrong way through it. It is recorded here because the wrong reason is the
#: one a future reader would reach for again: a human gate question that fails
#: admissibility is dropped BEFORE the gate, so the test governs human
#: questions too; and a quorum question with no options tells the brain to
#: answer in prose, so prose-without-options is a quorum shape, not a
#: human-only one. The two are not split the way they look.
#:
#: ``yes`` is also not UNRECORDABLE, only unkeyable. ``answer_key`` is the text
#: before the em dash, so "proceed with the destructive migration -- the backup
#: is verified" parses today. Only the spellings where ``yes`` is the KEY are
#: refused, which is exactly where ``yes`` is doing a decision key's job.
#:
#: Two things would break if this were relaxed for human records.
#: ``_contradiction`` compares ``answer_key`` with no provenance test, so a
#: string legal in an ``H-`` record and illegal in a ``Q-`` record on one axis
#: is a disagreement nothing checks. And the relaxed branch would admit
#: "pending user response -- awaiting the user" into an ADOPTED record: the
#: Open-status exact match never sees that spelling, so ``_PENDING_ANSWER``
#: would lose its only guard and an unanswered question would be recorded as a
#: settled decision.
#:
#: Why ``go`` differs from ``yes``, since both were inherited members. The
#: rule this one carries over from tests the WHOLE answer
#: (``plugins/superb/skills/pipeline/scripts/pipeline_state.py:1926``) and does
#: contain ``go``. This module added the ``answer_key`` reach, and that reach is
#: what turned "go -- it compiles fast" from passing into refused. So every
#: inherited member that could be a legitimate KEY had to be re-examined under
#: the new reach; ``go`` is the one that could, and removing it restores the
#: inherited behaviour for that case rather than departing from it. ``yes`` has
#: no such carrier.
_GENERIC_ANSWERS = frozenset({
    "", "approved", "yes", "continue", "proceed", "ok", "okay",
    "agreed", "sounds good", "lgtm", "sure", "do it", "pending user response",
})

#: The exact placeholder an UNANSWERED question is recorded with. The template
#: requires the question be written down now rather than later -- a question
#: recorded only once it has an answer is a question the run can silently drop
#: -- so ``Open`` is a status this parser must accept, and the placeholder is
#: the one string that may stand where an answer will go.
_PENDING_ANSWER = "pending user response"

#: ``Open`` is neither adopted nor superseded: it binds nothing, contradicts
#: nothing, and is never projected. Ordered canonical spellings; the lookup
#: below folds case so that ``ADOPTED`` and ``adopted`` are the same status and
#: ``Adopted!`` is not a status at all.
_DECISION_STATUSES = ("Adopted", "Superseded", "Open")
_STATUS_SPELLINGS = MappingProxyType(
    {status.casefold(): status for status in _DECISION_STATUSES})
#: The same three as a SET, for the one membership test whose value does not
#: come from this parser. ``_member`` over a frozenset is the pinnable
#: spelling: a bare ``in`` against it raises ``TypeError`` on an unhashable
#: value, which is outside ``TrackerError``, so reverting the call site fails
#: the suite instead of passing quietly the way a tuple would.
_DECISION_STATUS_NAMES = frozenset(_DECISION_STATUSES)

#: Every record must carry all seven. ``depth`` is required rather than
#: defaulted, and that is the whole of why it is in this tuple: a missing
#: ``Depth`` read as 0 would let a quorum answer claim it stands exactly where
#: a human's does, which is the one distance the depth cap exists to measure.
_REQUIRED_DECISION_FIELDS = ("question", "axis", "answer", "provenance",
                             "decision_action", "depth", "status")

#: The template writes ``Action``; the P03 contract writes ``Decision action``.
#: They are one field, so they are normalised to one key here rather than read
#: as two -- two keys would let a record spell one of them, satisfy neither
#: validator, and record an action nothing honours.
_DECISION_FIELD_ALIASES = MappingProxyType({"action": "decision_action"})

#: The three fields a brain is shown, and the whole of them. A whitelist rather
#: than a blacklist because ``decisions.md`` is hand-editable: a new field
#: added to a record by a human, a later phase, or a template revision must
#: reach no brain until somebody decides it may, and a blacklist grants the
#: opposite default.
_PROJECTED_FIELDS = ("question", "answer", "provenance")

#: The two free-text fields the CONTENT screen below is run over, named once so
#: that ``parse_decisions`` and ``project_decisions`` cannot come to screen
#: different sets. They are the two members of ``_PROJECTED_FIELDS`` a human or
#: a brain writes as prose; ``provenance`` is the third and is an ENUM, so it is
#: screened by membership against ``_PROVENANCES`` instead -- strictly narrower
#: than any content rule, and the reason it is absent from this tuple rather
#: than forgotten from it.
_SCREENED_FIELDS = ("question", "answer")

#: The whitelist above is a FIELD screen and what follows is a CONTENT screen,
#: and the field screen alone is not the guarantee the docstring claims:
#: ``Answer: postgres -- adopted at 0.85, code-evidenced, runner-up
#: speculation`` is carried by ``answer``, which is projected, so every value
#: the whitelist withholds arrives anyway inside a field it cannot inspect.
#:
#: Every rung VALUE, in BOTH spellings a writer reaches for: ``str`` gives the
#: shortest one (``0.7``) and the two-decimal form is how the ladder itself is
#: written down (``0.70``). Both, because the screen requires a match to be a
#: WHOLE number and ``0.7`` inside ``0.70`` is not one -- screening only
#: ``str(value)`` would accept ``adopted at 0.70``, which is the leak spelled
#: the way the ladder spells it.
_RUNG_VALUE_STRINGS = tuple(sorted(
    {str(value) for value in RUNGS.values()}
    | {f"{value:.2f}" for value in RUNGS.values()}))

#: The rung NAMES the content screen looks for, and deliberately NOT all five.
#: A rung name that is an ordinary English word -- ``specified``,
#: ``speculation`` -- is a word a decision record legitimately uses: "use the
#: schema specified in the RFC" and "redis -- avoids speculation about disk
#: contention" are real answers, and a screen that stops them stops real records
#: for saying ordinary things, in a file whose prescribed remedy is to reword a
#: sentence. A HYPHENATED rung name is coined by this ladder and appears in
#: prose only when the ladder is being quoted, so the hyphen is the property
#: this derives on: a ladder that gains a compound name gains the screen for it
#: on the same day, and one that gains a bare English word does not.
#:
#: WHAT THIS GIVES UP, stated here rather than left to be discovered: a bare
#: ``speculation`` or ``specified`` standing alone in an Answer now reaches a
#: brain. What it does not give up is the leak the screen exists for --
#: ``Answer: postgres -- adopted at 0.85, code-evidenced, runner-up
#: speculation`` is still refused twice over, by the value ``0.85`` and by the
#: compound ``code-evidenced``.
_RUNG_NAME_STRINGS = tuple(sorted(name for name in RUNGS if "-" in name))


def _wordish(char: str) -> bool:
    """Whether ``char`` continues a word, so a match beside it is not one.

    The empty string is not: it is what the slice either end of the string
    yields, and a rung name at the very start or end of a field is quoted as
    much as one in the middle. ``-`` is not either, which is what lets
    ``code-evidenced`` be found at all.
    """
    return char.isalnum() or char == "_"


def _rung_leak(value: str) -> str | None:
    """The first rung VALUE or compound rung NAME quoted inside ``value``.

    EXACTLY WHAT IS SCREENED, and exactly what is not:

    * Every rung value, in both the ``0.7`` and ``0.70`` spellings, matched as a
      WHOLE number. ``adopted at 0.85``, ``(0.85)``, ``rung=0.85`` and ``adopted
      at 0.85.`` all hit. ``$10.85 per million tokens`` and ``a p99 of 10.3
      seconds`` do not: a neighbouring digit -- or a ``.`` that a digit follows
      -- means the match is a fragment of some other decimal and not the rung. A
      plain substring test called all of those a leak, and ``str(0.70)`` being
      ``'0.7'`` made every decimal containing ``.7`` one.
    * Every HYPHENATED rung name, as a whole word: ``code-evidenced``,
      ``convention-cited``, ``engineering-judgement``.

    NOT SCREENED: ``specified`` and ``speculation``, the two rung names that are
    also ordinary English words. See ``_RUNG_NAME_STRINGS`` for why, and for
    what that costs.

    A trailing ``.`` is punctuation unless a digit follows it, which is the one
    asymmetry here and is deliberate: ``adopted at 0.85.`` ends a sentence and is
    exactly the leak, while ``1.0.85`` continues a version string and is not.

    RUN AT BOTH ENDS. ``parse_decisions`` runs it as the record is written,
    which is the only moment the prescribed remedy -- reword one sentence -- is
    available: by projection time the record is already in an append-only file
    that ``_decision_sections`` refuses to let lose a record. ``project_decisions``
    runs it again on whatever it is handed, because it declares its input
    untrusted and is the last thing standing between a record and a brain.
    """
    lowered = value.casefold()
    for token in _RUNG_VALUE_STRINGS:
        start = lowered.find(token)
        while start != -1:
            end = start + len(token)
            before = lowered[start - 1:start]
            after = lowered[end:end + 1]
            if not (before.isdigit() or before == "." or after.isdigit()
                    or (after == "." and lowered[end + 1:end + 2].isdigit())):
                return token
            start = lowered.find(token, start + 1)
    for token in _RUNG_NAME_STRINGS:
        start = lowered.find(token)
        while start != -1:
            end = start + len(token)
            if not (_wordish(lowered[start - 1:start])
                    or _wordish(lowered[end:end + 1])):
                return token
            start = lowered.find(token, start + 1)
    return None


def _id_provenance(did: str) -> str | None:
    """Which namespace a decision id is in -- ``human``, ``quorum`` or neither.

    Grammar, not prefix. ``H-01x`` starts with ``H-`` and is not a human
    decision id: ``_validate_tasks`` refuses it in a task's ``Decisions`` cell,
    so a record headed with it is a decision no task in the run can ever cite.
    Checking the prefix alone would accept it here and lose it there, which is
    the shape where an audit trail and the tracker disagree about what exists.
    """
    if _HUMAN_DECISION.fullmatch(did):
        return "human"
    if _QUORUM_DECISION.fullmatch(did):
        return "quorum"
    return None


def _decision_field(line: str) -> tuple[str, str] | None:
    """One ``- **Field:** value`` or ``- Field: value`` line, or ``None``.

    BOTH SPELLINGS, because both are already in the repository: the shipped
    ``templates/decisions.md`` writes the plain form and this phase's record
    grammar writes the emphasised one. A parser that took only one of them
    would read a file copied from the shipped template as a file with no
    fields at all -- so every record would be missing every required field,
    and an ordinary run would be a read-only stop on its first decision.

    Stated without ``re``: the module's import allowlist is a capability
    boundary, and a field line is ``-``, a label, a colon and the rest. The
    label may not contain an asterisk or a colon, which is what stops a prose
    bullet inside a record from being read as a field.
    """
    if not line.startswith("- "):
        return None
    body = line[2:].strip()
    if body.startswith("**"):
        label, closer, value = body[2:].partition(":**")
    else:
        label, closer, value = body.partition(":")
    if not closer:
        return None
    label = label.strip()
    if not label or "*" in label or ":" in label:
        return None
    return _field(label), value.strip()


def _decision_sections(text: str) -> list[tuple[str, dict]]:
    """Every ``## <heading>`` section of ``decisions.md``, with its fields.

    Sections, not decisions: a real ``decisions.md`` opens with prose and an
    ``## Axis Index`` table before the first record, and a reader that treated
    every heading as a decision would report the axis index as a decision
    missing every field it needs. Which sections are decisions is settled by
    the caller, by id -- and a section that is not one but carries decision
    FIELDS is refused there rather than skipped, so a record whose heading was
    mistyped cannot vanish out of the audit trail silently.

    Duplicate headings raise. A dict keyed by id would let the second ``##
    H-001`` overwrite the first, which is an append-only file losing a decision
    through the parser rather than through an edit.
    """
    if not isinstance(text, str):
        raise TrackerValidationError(
            f"decisions.md is {type(text).__name__}, not str: the audit trail "
            "is read as text and is never coerced into one")
    sections: list[tuple[str, dict]] = []
    seen: set[str] = set()
    fields: dict | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].split("—")[0].strip()
            if heading in seen:
                raise TrackerValidationError(
                    f"decisions.md holds two ## {heading} sections; the file is "
                    "append-only and a repeated heading loses whichever record "
                    "is read second")
            seen.add(heading)
            fields = {}
            sections.append((heading, fields))
            continue
        if fields is None:
            continue
        parsed = _decision_field(line)
        if parsed is None:
            continue
        key, value = parsed
        if key in _DECISION_FIELD_ALIASES:
            key = _DECISION_FIELD_ALIASES[key]
        if key in fields:
            raise TrackerValidationError(
                f"section {sections[-1][0]!r} states {key!r} twice; one of the "
                "two is the value every later reader will use and nothing says "
                "which")
        fields[key] = value
    return sections


def _consequence_map(raw: str, did: str) -> dict:
    """``kind:subject=value`` entries, as a mapping contradiction can compare.

    Every part is required and the kind is checked against the enum. A
    free-text consequence is the fail-open shape ``_BLAST_RADII`` is closed
    against: it matches no other record's consequences, so two adopted
    decisions that genuinely conflict are compared on an empty intersection and
    pass. A consequence is an assertion that would be verifiably TRUE of the
    repository if the answer were adopted -- never a rationale -- and the enum
    is what holds it to that.
    """
    mapping = {}
    for entry in (part.strip() for part in raw.split(",") if part.strip()):
        head, assigned, value = entry.partition("=")
        kind, marked, subject = head.partition(":")
        kind, subject, value = kind.strip(), subject.strip(), value.strip()
        if not assigned or not marked or not subject or not value:
            raise TrackerValidationError(
                f"{did}: consequence {entry!r} is not kind:subject=value; a "
                "consequence with no subject or no value asserts nothing about "
                "the repository and can contradict nothing")
        if not _member(kind, _CONSEQUENCE_KINDS):
            raise TrackerValidationError(
                f"{did}: consequence kind {kind!r} is not one of "
                f"{sorted(_CONSEQUENCE_KINDS)}; an unrecognised kind matches no "
                "other record, so the contradiction check passes by failing to "
                "understand either side")
        if (kind, subject) in mapping:
            raise TrackerValidationError(
                f"{did}: consequence {kind}:{subject} is asserted twice; a "
                "record that contradicts itself is an audit trail holding both "
                "answers in one decision")
        mapping[(kind, subject)] = value
    return mapping


def _decision_anchors(raw: str, did: str) -> list[str]:
    """``Consistent with`` as a list of decision ids, or a stop.

    READ BY EVERY LATER PHASE AND, UNTIL NOW, VALIDATED BY NOTHING: ``\x00``,
    ``|``, ``0.85``, an em dash and three hundred commas all parsed straight
    through into a live anchor list. That is the Task-2 carry-forward hazard
    verbatim -- an anchor without an id lets a brain claim grounding in a
    decision it never names, and the claim reads as checked because a list came
    back.

    DECISION IDS ONLY, because ``decisions.md`` already has a field for the
    other kind of anchor: the template gives ``Sources`` the spec lines and
    ``file:line`` citations a record rests on, and ``Consistent with`` the
    decisions it stands beside. One field taking both would make an entry that
    resolves to neither indistinguishable from one that simply has the other
    shape.
    """
    anchors = []
    for entry in (part.strip() for part in raw.split(",") if part.strip()):
        if _id_provenance(entry) is None:
            raise TrackerValidationError(
                f"{did}: Consistent with entry {entry!r} is not a decision id "
                "(H-<n> or Q-<qid>); an anchor without an id lets a record claim "
                "grounding in a decision it never names")
        if entry in anchors:
            raise TrackerValidationError(
                f"{did}: Consistent with cites {entry!r} twice; one citation is "
                "one claim of grounding and a repeat weights it double")
        anchors.append(entry)
    return anchors


def parse_decisions(text: str) -> dict:
    """Parse ``decisions.md`` into records plus a validated axis index.

    Returns ``{"decisions": {D-ID: record}, "axis_index": {axis: [D-ID, ...]}}``.

    PROVENANCE IS REQUIRED AND MUST AGREE WITH THE ID PREFIX, so provenance
    survives even if the field is lost. The prefix is the entire difference
    between a decision a machine made and one the user made, and it is what
    contradiction routing reads to tell them apart: a finding tracing to a
    human decision halts to the escalation queue, while one tracing to a quorum
    decision re-opens that qid at a raised bar. Two records that disagree with
    their own ids would route by whichever of the two a given reader consulted.

    THE LADDER NEVER ENTERS THE AUDIT TRAIL, and that is refused HERE rather
    than only at the projection. ``project_decisions`` keeps the same content
    screen as a backstop, but it runs on a record that is already written, and
    the remedy the stop prescribes -- reword one sentence -- would then mean
    editing a file ``_decision_sections`` refuses to let lose a record. Refused
    as the record is parsed, nothing has been appended and rewording is free.

    A ``Supersedes`` CHAIN MUST TERMINATE IN A LIVE RECORD. Two records that
    supersede each other satisfy every other retirement rule -- each target
    exists, each is Superseded, each is claimed once, none is orphaned -- and
    answer nothing about what replaced either.

    TWO ADOPTED DECISIONS CONTRADICTING EACH OTHER ON ONE AXIS IS A READ-ONLY
    STOP of the same severity as a foreign schema. The file IS the audit trail,
    and a trail holding both answers has already failed -- every later reader
    picks one by accident of iteration order and every pick is defensible, so
    nothing downstream can detect it. Nothing is repaired and neither answer is
    preferred.

    Nothing outside ``TrackerError`` leaves here. A malformed decisions.md is
    input, not a bug: an ``int('two')`` or a ``KeyError`` escaping this function
    would kill the run through a handler no controller has written, instead of
    stopping it read-only with the record named.
    """
    decisions: dict = {}
    axis_index: dict = {}
    for did, fields in _decision_sections(text):
        provenance_by_id = _id_provenance(did)
        if provenance_by_id is None:
            #: Not a decision section. ``## Axis Index`` is one, and so is any
            #: prose heading a writer adds. It is skipped only if it carries no
            #: decision field: a section that states a Question and an Answer
            #: under a mistyped id IS a decision, and skipping it would drop a
            #: record out of an append-only file without a word.
            stated = sorted(set(fields) & set(_REQUIRED_DECISION_FIELDS))
            if stated:
                raise TrackerValidationError(
                    f"section {did!r} states decision fields {stated} but is "
                    "not a decision id (H-<n> or Q-<qid>); a record no task can "
                    "cite is a decision the run cannot act on")
            continue
        missing = [name for name in _REQUIRED_DECISION_FIELDS
                   if not fields.get(name, "").strip()]
        if missing:
            raise TrackerValidationError(
                f"{did}: decision record is missing {missing}; every one of "
                "them is read by something that routes on it")
        provenance = fields["provenance"].strip().casefold()
        if not _member(provenance, _PROVENANCES):
            raise TrackerValidationError(
                f"{did}: Provenance must be human or quorum, not "
                f"{fields['provenance']!r}")
        if provenance != provenance_by_id:
            raise TrackerValidationError(
                f"{did}: id prefix says {provenance_by_id} and Provenance says "
                f"{provenance}; provenance is recorded twice so that it survives "
                "one of the two being lost, not so that a record can claim both")
        action = fields["decision_action"].strip()
        if not _member(action, _DECISION_ACTIONS):
            raise TrackerValidationError(
                f"{did}: unknown decision action {action!r}; the actions are "
                f"{sorted(_DECISION_ACTIONS)} and an unrecognised one is an "
                "authority no validator in this run will ever honour")
        if _member(action, _EXTENSION_ACTIONS) and provenance != "human":
            raise TrackerValidationError(
                f"{did}: {action} requires Provenance: human; a budget a quorum "
                "can extend is not a budget")
        status_raw = fields["status"].strip()
        if not _member(status_raw.casefold(), _STATUS_SPELLINGS):
            raise TrackerValidationError(
                f"{did}: Status must be one of {list(_DECISION_STATUSES)}, not "
                f"{status_raw!r}")
        status = _STATUS_SPELLINGS[status_raw.casefold()]
        answer = fields["answer"].strip()
        answer_key = answer.split("—")[0].strip()
        if status == "Open":
            #: An unanswered question is recorded NOW. The placeholder is the
            #: only string that may stand where an answer will go, and the
            #: action must be ``none``: an Open record granting an authority
            #: would be a grant nobody made.
            if answer.casefold() != _PENDING_ANSWER:
                raise TrackerValidationError(
                    f"{did}: an Open decision's Answer is exactly "
                    f"{_PENDING_ANSWER!r}, not {answer!r}; an Open record with "
                    "an answer in it is an answer nothing has adopted")
            if action != "none":
                raise TrackerValidationError(
                    f"{did}: an Open decision's action is 'none', not {action!r}")
        else:
            for candidate in (answer, answer_key):
                if candidate.rstrip(".").casefold() in _GENERIC_ANSWERS:
                    raise TrackerValidationError(
                        f"{did}: {candidate!r} is a generic approval, not an "
                        "answer to an unresolved choice; this holds for a quorum "
                        "answer of 'proceed' exactly as it holds for a human's")
        axis = fields["axis"].strip()
        if not _TOKEN.fullmatch(axis):
            raise TrackerValidationError(
                f"{did}: Axis {axis!r} is not a legal axis token; the axis is "
                "the key the contradiction check groups by, and one that cannot "
                "be written into the tracker's own cell groups with nothing")
        if axis == _RESERVED_AXIS:
            #: ``new`` is the RESERVED LITERAL for a question that has not been
            #: tagged to a stable axis yet. Two unrelated decisions both
            #: recorded against it would be compared as though they answered one
            #: question, and the run would stop on a contradiction that does not
            #: exist. Whoever writes the record assigns the stable axis; the
            #: placeholder never reaches the audit trail.
            #:
            #: THIS IS THE OTHER HALF OF ``_validate_quorum``'s AXIS NAMESPACE,
            #: AND THE DIFFERENCE IS DELIBERATE. ``_validate_quorum`` ACCEPTS
            #: ``new`` in a ``## Quorum`` row's ``Axis`` cell; this function
            #: REFUSES it in a decision record's ``Axis`` field. The two are not
            #: in conflict because they record different facts about the same
            #: adoption:
            #:
            #: * the tracker row records WHAT WAS ASKED. A question raised after
            #:   the stage-03 gate closed was asked on no stable axis, and the
            #:   row keeps saying so forever. ``_validate_quorum`` closes that
            #:   cell to the stage-03 question ids plus this literal, so a freshly
            #:   minted axis could not be written there even if a writer tried.
            #: * the decision record records THE AXIS THAT QUESTION OPENED. A
            #:   question whose axis is ``new`` is adopted like any other, and
            #:   the record appended here carries the question's own bare 12-hex
            #:   qid as its ``Axis``: reproducible from the question, unique to
            #:   it, and -- unlike ``new`` -- a bucket shared with nothing.
            #:
            #: So an adopted ``new``-axis row and its decision record legally
            #: disagree about the word in that cell, and the pair is pinned end
            #: to end in the suite rather than left as two comments that happen
            #: to coexist. The minting itself belongs to the adoption path, not
            #: here; this function only refuses the placeholder.
            raise TrackerValidationError(
                f"{did}: Axis {_RESERVED_AXIS!r} is the reserved literal for an "
                "untagged question, not an axis; a decision recorded against it "
                "shares one axis bucket with every other untagged decision. The "
                "## Quorum row keeps " f"{_RESERVED_AXIS!r}" "; the record "
                "carries the question's own qid as its axis")
        depth_raw = fields["depth"].strip()
        if not _is_count(depth_raw):
            raise TrackerValidationError(
                f"{did}: Depth {depth_raw!r} is not a non-negative integer; "
                "isdigit alone is true of '٣', which int() reads back as 3 "
                "and no downstream reader can match")
        depth = int(depth_raw)
        if provenance == "human" and depth != 0:
            raise TrackerValidationError(
                f"{did}: a human decision is depth 0, not {depth}; depth counts "
                "inference from the last thing a human actually said, and a "
                "human saying it is that thing")
        #: THE CONTENT SCREEN, AT WRITE TIME. ``project_decisions`` runs the
        #: same screen over the same two fields as a backstop, but it runs it on
        #: a record that is already sitting in the audit trail -- and the remedy
        #: this stop prescribes is to reword one sentence, which by then means
        #: editing a file ``_decision_sections`` refuses to let lose a record.
        #: Refused here, nothing has been written yet and rewording is free.
        for name in _SCREENED_FIELDS:
            leaked = _rung_leak(fields[name].strip())
            if leaked is not None:
                raise TrackerValidationError(
                    f"{did}: {name.capitalize()} quotes {leaked!r}, a rung name "
                    "or a rung value; a brain reading 'adopted at 0.85' treats "
                    "the decision as soft and reverses it, so the ladder never "
                    "enters the audit trail -- reword the sentence now, while "
                    "the record is still being written")
        record = dict(fields)
        record.update({
            "id": did,
            "axis": axis,
            "provenance": provenance,
            "action": action,
            "decision_action": action,
            "answer": answer,
            "answer_key": answer_key,
            "status": status,
            "depth": depth,
            "question": fields["question"].strip(),
            "consequences": _consequence_map(fields.get("consequences", ""), did),
            "consistent_with": _decision_anchors(
                fields.get("consistent_with", ""), did),
        })
        decisions[did] = record
        axis_index.setdefault(axis, []).append(did)

    for axis, ids in sorted(axis_index.items()):
        adopted = [decisions[did] for did in ids
                   if decisions[did]["status"] == "Adopted"]
        #: The contradiction check runs FIRST even though the count rule below
        #: subsumes it. Both stop the same files; only one of them says what
        #: actually disagreed, and "these two assert opposite things about
        #: db/session.sql" is the message that tells a human which record to
        #: retire. Ordered the other way, the specific diagnosis would be
        #: unreachable and ``_contradiction`` would be dead code.
        for index, left in enumerate(adopted):
            for right in adopted[index + 1:]:
                clash = _contradiction(left, right)
                if clash is not None:
                    raise TrackerValidationError(
                        f"axis {axis} holds two adopted contradicting answers, "
                        f"{left['id']} and {right['id']} ({clash}); this run is "
                        "a read-only stop -- the audit trail holds both answers "
                        "and no reader can tell which one the run is bound by")
        if len(adopted) > 1:
            #: ONE ADOPTED DECISION PER AXIS, which is what
            #: ``templates/decisions.md`` states and the template is the
            #: authority this contract was built against. Two that merely AGREE
            #: today are still two records standing on one axis: the axis index
            #: has one ``Decision`` column and can name only one of them, every
            #: later reader picks by accident of iteration order, and the pair
            #: becomes a contradiction the first time either is amended.
            #:
            #: THIS BINDS THE ADOPTION PATH. A later adoption on an axis that
            #: already carries an Adopted record SUPERSEDES that record -- flips
            #: it to ``Superseded`` and appends the new one with a ``Supersedes``
            #: line -- and never appends a second Adopted one.
            raise TrackerValidationError(
                f"axis {axis} holds {len(adopted)} Adopted decisions "
                f"({[record['id'] for record in adopted]}); an axis holds at "
                "most one, and a later adoption supersedes the record standing "
                "there rather than appending beside it -- the axis index names "
                "one decision per axis and cannot say which of two is binding")

    #: ``Supersedes`` is the other half of the one legal in-place mutation.
    #: ``templates/decisions.md`` states that ``Adopted -> Superseded`` is
    #: performed by appending the superseding record WITH ITS OWN
    #: ``Supersedes`` LINE, so a record retired with nothing naming it is an
    #: audit trail that records a decision being withdrawn and not what replaced
    #: it -- which is the one question a reader of a retired record has.
    claimed: dict = {}
    for did in sorted(decisions):
        target = decisions[did].get("supersedes", "").strip()
        if not target:
            continue
        if _id_provenance(target) is None:
            raise TrackerValidationError(
                f"{did}: Supersedes {target!r} is not a decision id (H-<n> or "
                "Q-<qid>); a record that names no id supersedes nothing")
        if target == did:
            raise TrackerValidationError(
                f"{did}: Supersedes names the record itself; a decision cannot "
                "replace the thing it is")
        if target not in decisions:
            raise TrackerValidationError(
                f"{did}: Supersedes {target!r}, which this file does not hold; "
                "the audit trail is append-only, so the record being replaced is "
                "still in it and a name that resolves to nothing retires nothing")
        if decisions[target]["status"] != "Superseded":
            raise TrackerValidationError(
                f"{did}: Supersedes {target!r}, whose Status is "
                f"{decisions[target]['status']!r} and not 'Superseded'; the "
                "mutation is both halves or neither, and half of it leaves two "
                "live records where one was retired")
        if target in claimed:
            raise TrackerValidationError(
                f"{did} and {claimed[target]} both supersede {target!r}; one "
                "retired decision has one successor, and two make the axis index "
                "unable to say which record replaced it")
        claimed[target] = did
    orphaned = sorted(did for did in decisions
                      if decisions[did]["status"] == "Superseded"
                      and did not in claimed)
    if orphaned:
        raise TrackerValidationError(
            f"{orphaned} are Superseded and nothing supersedes them; the one "
            "legal in-place mutation appends the superseding record with its own "
            "Supersedes line, and a retirement with no successor is a decision "
            "withdrawn without recording what took its place")

    #: AND THE CHAIN MUST TERMINATE. Every check above is satisfied by two
    #: records that supersede each other: each target exists, each is
    #: ``Superseded``, each is claimed exactly once, none is orphaned -- and the
    #: successor chain is a closed loop that never reaches a live decision, so
    #: "what took its place" has no answer. That is the very question the orphan
    #: rule above exists to keep answerable, so a cycle defeats it while passing
    #: every syntactic check it states. Walked from each retired record rather
    #: than asserted structurally, because the message has to name the loop.
    for did in sorted(decisions):
        if decisions[did]["status"] != "Superseded":
            continue
        chain = [did]
        successor = claimed[did]
        while decisions[successor]["status"] == "Superseded":
            if successor in chain:
                raise TrackerValidationError(
                    f"{chain} form a Supersedes cycle; every record in it is "
                    "Superseded and each is replaced by another record in the "
                    "same loop, so the chain never terminates in a live "
                    "decision and no reader can say what replaced any of them "
                    "-- which is the one question a reader of a retired record "
                    "has")
            chain.append(successor)
            successor = claimed[successor]

    #: Anchors resolve, or the grounding they claim is unverifiable. A
    #: ``Consistent with`` naming a record this file does not hold is the
    #: carried-forward Task-2 hazard in its markdown spelling: a brain claims
    #: grounding in a decision the audit trail cannot produce, and every reader
    #: downstream of it inherits a citation that looks checked and is not.
    for did in sorted(decisions):
        for anchor in decisions[did]["consistent_with"]:
            if anchor == did:
                raise TrackerValidationError(
                    f"{did}: Consistent with names the record itself; a decision "
                    "is not evidence that it is consistent with anything")
            if anchor not in decisions:
                raise TrackerValidationError(
                    f"{did}: Consistent with cites {anchor!r}, which this file "
                    "does not hold; an anchor naming a decision the audit trail "
                    "cannot produce is grounding nothing can check")
    return {"decisions": decisions, "axis_index": axis_index}


def _contradiction(left: dict, right: dict) -> str | None:
    """How two adopted records on one axis disagree, or ``None``.

    The reason rather than a boolean, because the stop has to name what
    disagreed: "these two contradict" sends a human to read both records and
    guess, and the guess is between an answer key and a consequence.

    Two answers on one axis are the same answer only if they name the same key
    AND assert nothing incompatible. When in doubt they are DIFFERENT answers,
    which pushes toward the stop, which is the safe direction.
    """
    if left["answer_key"] != right["answer_key"]:
        return (f"answer keys {left['answer_key']!r} and "
                f"{right['answer_key']!r} differ")
    shared = set(left["consequences"]) & set(right["consequences"])
    for key in sorted(shared):
        if left["consequences"][key] != right["consequences"][key]:
            kind, subject = key
            return (f"{kind}:{subject} is asserted "
                    f"{left['consequences'][key]!r} and "
                    f"{right['consequences'][key]!r}")
    return None


def project_decisions(decisions: dict) -> str:
    """Render ``decisions-effective.md``: the only decision material a brain sees.

    QUESTION, ANSWER AND PROVENANCE. No value, no rung name, no rejected
    alternatives, no consequences, no depth, no scope -- and that claim holds
    for all three fields, not two of them. ``question`` and ``answer`` are free
    text and are screened as CONTENT; ``provenance`` is an ENUM and is screened
    by membership against ``_PROVENANCES``, which is strictly narrower than any
    content rule and is what an enum field should get. LEFT UNSCREENED it would
    project ``human -- adopted at 0.85, code-evidenced`` verbatim into the one
    file a brain reads, through the one projected field the screen missed.

    * Adopted answers must be INCLUDED, or brains re-litigate settled ground
      and manufacture the very drift the quorum exists to bound.
    * Values must be EXCLUDED: a brain reading "adopted at 0.85" treats the
      decision as soft and reverses it, where a brain reading it as simply a
      decision treats it as binding. The rung NAME goes with the value, because
      a name whose ladder the brain also knows is the value.
    * Provenance must be INCLUDED so a brain can recognise a human decision and
      refuse to contradict it.

    Superseded and Open records are not projected: the first is no longer in
    effect and the second has no answer to be in effect. Budget extensions are
    not projected either -- their answer carries a ceiling, and a ceiling is a
    number in a brain's payload.

    The three fields are whitelisted rather than the others blacklisted.
    ``decisions.md`` is hand-editable and grows fields; a blacklist ships every
    new one to a brain until somebody remembers to add it.

    THE WHITELIST IS A FIELD SCREEN AND IS NOT THE WHOLE CLAIM. Two of the three
    projected fields are free text a human or a brain wrote, so a rung name or a
    rung value quoted INSIDE one of them reaches a brain through a field the
    whitelist has already approved -- ``Answer: postgres -- adopted at 0.85,
    code-evidenced, runner-up speculation`` leaks all three. ``question`` and
    ``answer`` are therefore screened for rung names and rung values as CONTENT,
    and a hit is a STOP rather than a strip: a decision record whose prose quotes
    the ladder is a record that should never have been written, and silently
    editing the audit trail on its way to a brain would leave the file and what
    the brain read disagreeing about what was decided.

    Record KEYS are screened too, before anything is sorted. A key that is not a
    decision id is projected as ``## 1`` or ``## ('a',)`` -- a heading no
    ``_id_provenance`` would accept, in the one file a brain reads -- and a
    mixture of key types raises ``TypeError`` out of ``sorted`` itself, which is
    outside ``TrackerError``.
    """
    if not isinstance(decisions, dict) or not isinstance(
            decisions.get("decisions"), dict):
        raise TrackerValidationError(
            "project_decisions takes the whole parse_decisions result, not the "
            "records alone: it is handed what a brain will read, and a shape "
            "it cannot read would project an empty file that looks like a run "
            "with no decisions in it")
    unreadable = [key for key in decisions["decisions"]
                  if not isinstance(key, str) or _id_provenance(key) is None]
    if unreadable:
        #: BEFORE ``sorted``, not after. A dict mixing ``1`` and ``"H-001"``
        #: raises ``TypeError`` out of the sort -- outside ``TrackerError``, so
        #: it escapes every handler a controller has written -- and a dict
        #: holding only ``1`` does not raise at all: it emits ``## 1`` as a
        #: decision heading. ``repr`` on the way into the message because the
        #: keys are not necessarily comparable with each other.
        raise TrackerValidationError(
            f"decision keys {sorted(map(repr, unreadable))} are not decision ids "
            "(H-<n> or Q-<qid>); a projection heading no id grammar accepts is a "
            "decision no task in the run can cite, written into the one file a "
            "brain reads")
    lines = ["<!-- pipeline-auto-decisions-effective/v1 -->", "",
             "# Decisions in effect", "",
             "Read-only and generated. Do not cite a value; there is none here.",
             ""]
    for did in sorted(decisions["decisions"]):
        record = decisions["decisions"][did]
        if not isinstance(record, dict):
            raise TrackerValidationError(
                f"{did}: a decision record is {type(record).__name__}, not an "
                "object")
        if not _member(record.get("status"), _DECISION_STATUS_NAMES):
            raise TrackerValidationError(
                f"{did}: status {record.get('status')!r} is not one of "
                f"{list(_DECISION_STATUSES)}; a record whose status cannot be "
                "read is a record that cannot be shown to be in effect")
        if not _member(record.get("action"), _DECISION_ACTIONS):
            raise TrackerValidationError(
                f"{did}: action {record.get('action')!r} is not a decision "
                "action; the extension actions are withheld from brains by "
                "name, and an unreadable action is withheld from nothing")
        if record["status"] != "Adopted":
            continue
        if _member(record["action"], _EXTENSION_ACTIONS):
            continue
        #: ``provenance`` is the third projected field and the only one of the
        #: three that is an enum. Membership, not a content screen: this
        #: function declares its input untrusted -- it already re-checks
        #: ``status`` and ``action`` against their enums for exactly that reason
        #: -- and a record handed here directly can carry anything in it.
        #:
        #: FIRST, and that ordering is load-bearing. ``_text`` below already
        #: refuses every non-string, so an enum screen placed after it would
        #: never be handed one, and ``_member``'s whole reason for existing --
        #: that ``["human"] in frozenset(...)`` raises ``TypeError``, outside
        #: ``TrackerError`` -- would be unobservable: a bare ``in`` written here
        #: would pass the suite.
        if not _member(record.get("provenance"), _PROVENANCES):
            raise TrackerValidationError(
                f"{did}: provenance {record.get('provenance')!r} is not one of "
                f"{sorted(_PROVENANCES)}; provenance is projected verbatim, so "
                "anything but the enum is arbitrary text written into the one "
                "file a brain reads")
        missing = [name for name in _PROJECTED_FIELDS if not _text(record.get(name))]
        if missing:
            raise TrackerValidationError(
                f"{did}: cannot be projected without {missing}; a decision shown "
                "to a brain without its question is an answer to nothing")
        for name in _SCREENED_FIELDS:
            leaked = _rung_leak(record[name])
            if leaked is not None:
                raise TrackerValidationError(
                    f"{did}: {name.capitalize()} quotes {leaked!r}, a rung name "
                    "or a rung value; a brain reading 'adopted at 0.85' treats "
                    "the decision as soft and reverses it, and a record whose "
                    "prose carries the ladder is a record that should never have "
                    "been written -- so this is a stop and never a silent strip")
        lines.append(f"## {did}")
        lines.append("")
        lines.extend(f"- **{name.capitalize()}:** {record[name].strip()}"
                     for name in _PROJECTED_FIELDS)
        lines.append("")
    return "\n".join(lines) + "\n"
