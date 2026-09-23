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
#: ADMITTED BY QUORUM, and the twelfth member of a boundary that stood at
#: eleven. The rule the allowlist states is CAPABILITY, NOT CONVENIENCE --
#: "does this let the module do something it previously could not?" -- and for
#: ``json`` the answer is no: it opens nothing, execs nothing and reaches no
#: filesystem. It is the ``copy`` case, kept despite a hand-rolled version
#: passing every test, not the ``subprocess`` case.
#:
#: WHAT IT IS FOR, and what it is NOT. Markdown keeps every durable form it
#: already had -- the tracker, ``decisions.md``, the findings ledger, worker
#: results and the question record. ``json`` is for the agent-authored values
#: that are TYPED AND NESTED: brain responses, the finalised quorum records,
#: and the pinned grants beside them. The alternative was to convert those into
#: this module's section grammar, and run against a real response that grammar
#: corrupts and rejects it -- ``_csv`` splits a quote containing a comma into
#: two values, ``line`` as an int distinct from a bool and ``blocker`` as null
#: distinct from the empty string cannot be expressed at all -- so the
#: replacement would be a new nested, typed, escaping serialization format,
#: which is the hand-rolled option in markdown clothing.
#:
#: AND IT MUST BE WRAPPED. ``json.loads`` raises ``JSONDecodeError``, which is a
#: ``ValueError`` and so outside ``TrackerError``: unwrapped it escapes every
#: handler a controller has written. ``_loads`` is the only spelling in this
#: module and a parse failure is a ``TrackerError`` like every other
#: malformed-input path here.
import json
import os
import time
from contextlib import contextmanager
#: ``PurePosixPath`` for the phase-plan grammar's repository-relative
#: paths. It is the PURE half of a module already on the allowlist, so it
#: buys no capability at all -- it touches no filesystem by construction,
#: which is the whole reason a plan-declared path is normalised with it
#: rather than with ``Path``.
from pathlib import Path, PurePosixPath
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

#: NUL AS A SCREEN AND AS A RECORD SEPARATOR, SPELLED ONCE, AND DEFINED AT THE
#: TOP OF THE MODULE BECAUSE ITS EARLIEST USE IS NEAR THE TOP. It is the one
#: byte a POSIX path cannot carry and the one byte an argv element cannot
#: carry, which is what makes it safe to use as the range transcript's record
#: separator and what makes "does this value carry one" the right question to
#: ask of a path, an argv element and a qid field. Those are uses of ONE fact,
#: so they are one constant.
#:
#: THE EARLIER CLAIM WAS "THE MODULE'S SINGLE SPELLING OF THE BYTE" AND IT WAS
#: FALSE -- the constant sat two thousand lines BELOW `derive_qid`, whose
#: field-separator screen therefore carried its own `"\x00"` literal and could
#: have been relaxed without this one noticing. Hoisting it is the fix; the
#: sentence is narrowed at the same time, because four NUL constants remain
#: and they are deliberately NOT this one:
#:
#: * three `b"\x00"` and one `"\x00"` FIELD SEPARATORS inside `hashlib` digest
#:   inputs. They separate fields of a hash input rather than screening
#:   anything, and a digest's wire format must not move because a validation
#:   rule did, nor the reverse -- changing either would silently re-key every
#:   record already written under the old one.
#: * the lock file's `b"\x00"` PROBE BYTE, which is a write to test a
#:   descriptor and has nothing to do with the byte's meaning here.
#:
#: `test_the_nul_constants_are_exactly_the_screen_and_the_separators` asserts
#: that set from the AST, so neither half of this can rot unnoticed.
_NUL = "\x00"

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
#: Spelled once because it is MINTED as well as matched: the quorum row
#: writer numbers a new escalation off the ids already in the section, and a
#: prefix written a second time at the mint is a prefix free to disagree with
#: the grammar that judges it -- an id this module writes and then refuses.
_ESCALATION_PREFIX = "E-"
_ESCALATION_ID = _Numbered(_ESCALATION_PREFIX)
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
#: Spelled ONCE, because the drift budget rebuilds a quorum's own decision id
#: from its qid to check that an adopted record claims no other decision, and a
#: second spelling of the prefix is a second answer to "which id is this
#: quorum's own".
_QUORUM_PREFIX = "Q-"
_QUORUM_DECISION = _Hex(12, _QUORUM_PREFIX)

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


#: THE THIRD EXACT OUTCOME WORD, and P02's because the ``Outcome`` cell is
#: P02's. A quorum whose three answers were not about one question decided
#: nothing, escalated nothing and REJECTED NOTHING -- no candidate was refused,
#: because no two candidates ever addressed the same thing. Spelling it
#: ``rejected-<reason>`` to fit the old two-word grammar would file "there was
#: nothing here to decide between" as "the run turned an answer down", and the
#: terminal report keys off exactly that difference: a rejection is a brain
#: pulling away from what the user asked for and is the earliest drift warning
#: this design has, while an undecidable question is a question that was never
#: answerable as asked. Coercing it to ``escalated`` was refused for the same
#: reason one rung up -- ``open_quorum`` already refuses to project a settled
#: rejection down to ``escalated`` -- and dropping it is the one outcome the
#: brief forbids, because the row IS the audit trail.
#:
#: WIDENED HERE RATHER THAN BESIDE P03'S FINALISER. The vocabulary of this
#: column belongs to the section that renders and validates it; a P03-local
#: widening would be P03 re-declaring P02's grammar, which is the duplication
#: ``section_columns`` exists to prevent. P03 reads this name back rather than
#: respelling the literal, so the writer and the validator cannot drift.
_UNDECIDABLE = "question-not-decidable"


class _QuorumOutcome:
    """``adopted``, ``escalated``, ``question-not-decidable``, or ``rejected-<reason>``.

    P02 closes the SHAPE of an outcome and not the rejection vocabulary: naming
    the reasons is P03's contract, and an enum here would have to be edited in
    two places every time one is added — the kind of duplication that ends with
    a specified writer emitting a reason this module halts the run on.

    What is closed is that the three non-rejecting words are exact, and that
    anything else must both announce itself as a rejection and carry a reason.
    A bare ``rejected`` is the outcome recorded with the reason dropped, and the
    reason is the only part a human reading the run afterwards can act on.

    THE THIRD WORD IS NOT A RELAXATION OF THAT RULE. ``question-not-decidable``
    is exact, closed, and named above with the argument for it; what stays
    refused is an open vocabulary of bare words, which is what would let a
    rejection be recorded without its reason.
    """

    __slots__ = ()

    _EXACT = ("adopted", "escalated", _UNDECIDABLE)
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


#: ``os.O_DIRECTORY`` is POSIX-only and absent on some platforms, so it is
#: resolved ONCE here rather than at each call. Spelled as a ``try``/``except
#: AttributeError`` rather than ``getattr(os, "O_DIRECTORY", 0)`` because
#: ``getattr`` is a reflective route from a module object to any attribute of
#: it, and ``command_execution_names`` refuses it module-wide: a screen that
#: bans ``os.system`` and permits ``getattr(os, "sys" + "tem")`` bans the
#: spelling and not the capability. This was the module's only ``getattr``.
try:
    _O_DIRECTORY = os.O_DIRECTORY
except AttributeError:  # pragma: no cover - POSIX-only constant
    _O_DIRECTORY = 0


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
    flags = os.O_RDONLY | _O_DIRECTORY
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
    #: NORMALISED FIRST, for the reason ``worker_limit``'s type is checked
    #: first: a ``str`` run directory reaches ``classify_filesystem`` -- typed
    #: ``Path``, like ``validate_run`` -- and raises ``AttributeError`` there,
    #: outside ``TrackerError``, from a function whose whole contract is that a
    #: bad argument is a read-only stop. ``_run_path`` reads nothing, so the
    #: stop stays read-only, and it refuses ``None``, an ``int`` and a
    #: ``bytes`` inside the family rather than building a run directory named
    #: by a repr.
    run_dir = _run_path(run_dir)
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
    if _NUL in question:
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


#: The tag that separates the two halves of a re-open's identity input. A
#: constant rather than a literal because ``_reopen_lineage_root`` below
#: reproduces the same derivation and the two must not drift.
_REOPEN_TAG = b"reopen"


def derive_reopen_qid(question: str, axis: str, original_decision_id: str) -> str:
    """Stable identity for a RE-ASK of one question, namespaced by its authority.

    A RE-OPEN NEEDS ITS OWN IDENTITY OR IT HAS NO DOOR. ``final.json`` is a
    single-assignment cell and ``_open_under_lock`` returns it for ever, so a
    re-ask filed under the original qid is not a second quorum -- it is the
    first one's outcome handed back. That is the correct answer to a question
    being asked twice and the wrong answer to a question a human has since
    authorized to be asked again, and the two cannot be told apart from one
    identity.

    SO THE AUTHORITY IS IN THE HASH. ``original_decision_id`` is the D-ID of
    the fact that licenses this re-ask -- the quorum decision being challenged,
    or the human budget grant that restored the headroom the first raise was
    refused for. A re-ask with no such fact cannot mint an identity at all, and
    a re-ask against a DIFFERENT fact is a different quorum. That is the whole
    of what distinguishes a legitimate re-ask from a run asking again until it
    likes the answer: the second has nothing new to name.

    DERIVED FROM ``derive_qid`` RATHER THAN BESIDE IT. The original qid is the
    first field, so every rule that identity rests on -- the squash, the NUL
    refusal, the axis grammar, the exclusion of the decisions digest -- holds
    here unchanged and is not restated. It also makes the LINEAGE recoverable:
    the qid this re-ask hangs off is literally an input, so
    ``_reopen_lineage_root`` recomputes it rather than walking a chain of
    records that may have been compacted away.

    THE AXIS IS NOT NAMESPACED WITH THE D-ID, which was the obvious spelling
    and does not work: ``derive_qid`` requires its axis to satisfy ``_TOKEN``,
    which admits no ``#``, so ``derive_qid(question, f"{axis}#reopen:{did}")``
    raises rather than deriving anything.
    """
    if not isinstance(original_decision_id, str):
        raise QuorumSchemaInvalid(
            f"original_decision_id is {type(original_decision_id).__name__}, "
            "not str; a re-ask is identified by the record that authorizes it, "
            "and a repr names no record")
    challenged = original_decision_id.strip()
    if _id_provenance(challenged) is None:
        raise QuorumSchemaInvalid(
            f"original_decision_id {original_decision_id!r} is not a decision "
            "id (H-<n> or Q-<qid>); a re-ask namespaced by something the audit "
            "trail cannot hold is a re-ask whose authority nothing can be "
            "asked to produce")
    payload = (derive_qid(question, axis).encode("utf-8") + b"\x00"
               + _REOPEN_TAG + b"\x00" + challenged.encode("utf-8"))
    return hashlib.sha256(payload).hexdigest()[:12]


def _record_qid(record: dict) -> str:
    """WHICH identity one question record has, said in ONE place.

    ``open_quorum`` files the record under this and ``_question_record``
    re-derives it from the record's own fields and compares. Two spellings of
    that rule is one too many: the comparison exists to catch a directory that
    was copied, renamed or half-restored, and a reader that derived the
    identity a different way from the writer would report every re-open as
    exactly that corruption -- with the run lock held, inside the open.
    """
    challenged = record.get("reopen_of") or ""
    if challenged:
        return derive_reopen_qid(record["question"], record["axis"], challenged)
    return derive_qid(record["question"], record["axis"])


def _reopen_lineage_root(record: dict) -> str:
    """The qid a re-ask hangs off: the ORIGINAL question's own identity.

    THE LINEAGE IS THE QUESTION, NEVER THE AUTHORITY. Keyed on the authorizing
    D-ID instead, two unrelated questions refused by one budget grant would
    share a lineage and the second would be halted as an oscillation it had no
    part in. Keyed on the question, a re-ask of one question is bounded however
    it was authorized, which is the rule the anti-oscillation cap is for.

    RECOMPUTED, NEVER WALKED BACK THROUGH THE RECORDS. A chain walk over
    finalised quorums answers nothing after a compaction has removed the middle
    of the chain, and it is the shape that made the anti-oscillation rule a
    silent no-op in the first place -- ``quorum_events`` is a four-cell budget
    projection and carries no lineage at all.
    """
    return derive_qid(record["question"], record["axis"])


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
    """What an answer says it stands on, checked as an anchor and not a shape.

    THE ID IS REQUIRED, and for a ``decision`` it must BE a decision id. An
    anchor of ``{"kind": "decision"}`` alone was schema-valid until this line
    existed: it declares grounding, names nothing, and reaches ``decision_depth``
    -- which resolves anchors BY ID -- as an anchor that resolves to no record.
    Skipped there it contributes 0 and the answer comes back at depth 1, the
    shallowest and most adoptable depth there is, awarded to the response with
    the least grounding behind it. That is the Task-2 hazard in its JSON
    spelling; Task 4 closed the markdown one in ``_decision_anchors``, which
    this mirrors field for field.

    ``spec`` and ``repo`` ids are free text -- a spec line, a ``path:line`` --
    so they are held only to being text. A ``decision`` id is held to the
    grammar, because that is the kind whose id is looked UP.
    """
    if not isinstance(anchors, list) or not anchors:
        return ["empty-consistent-with"]
    problems = []
    for item in anchors:
        if (not isinstance(item, dict)
                or not _member(item.get("kind"), _ANCHOR_KINDS)):
            problems.append("consistent-with-item-malformed")
            continue
        anchor = item.get("id")
        if not _text(anchor):
            problems.append("consistent-with-item-malformed")
            continue
        if item["kind"] == "decision" and _id_provenance(anchor.strip()) is None:
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

    THE SHAPE IS ASKED BEFORE THE OPEN, for ``_require_regular_file``'s reason
    and with this path's own aggravation: ``path`` is BRAIN-SUPPLIED. A
    directory, a dangling link and a symlink loop all fail the open loudly and
    demote; a FIFO does not, and ``open`` on one blocks until a writer that
    never comes. Grading a brain's evidence is not a place a run may stop for
    ever with no diagnostic, and a brain naming a FIFO is a brain choosing
    where the run stops. It costs nothing in meaning: an unreadable citation
    already demotes, so ``None`` here is the same verdict the blocked read
    would have reached if it could ever return.
    """
    path = item.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    try:
        target = (root / path).resolve()
        if target != root and root not in target.parents:
            return None
        if not target.is_file():
            return None
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError, RuntimeError):
        #: ``OSError`` covers the missing file, the directory cited as a file,
        #: and the unreadable one; ``UnicodeError`` the binary one;
        #: ``ValueError`` an embedded NUL. Each is a demotion, and none of them
        #: may leave this module as an exception outside ``TrackerError``.
        #:
        #: ``RuntimeError`` IS THE SYMLINK LOOP, and it is raised by
        #: ``resolve`` rather than by the read: CPython's non-strict resolver
        #: reports ELOOP as ``RuntimeError("Symlink loop from ...")`` on the
        #: interpreters this module targets, which is outside ``TrackerError``
        #: and outside every other name in this tuple. So a brain citing a
        #: looped symlink -- the path is BRAIN-SUPPLIED -- would kill the run
        #: from inside the function whose whole job is to price that citation
        #: at what it turned out to be worth.
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
#: Every rung VALUE as a NUMBER, because the leak is a number and a list of
#: spellings only ever catches the spellings somebody thought of. ``0.85``,
#: ``0.850``, ``0.8500``, ``0.85000`` and ``.85`` are one value written five
#: ways; the screen that enumerated ``str(value)`` and ``f"{value:.2f}"``
#: caught two of them and let ``adopted at 0.850`` through -- the same hole the
#: two-decimal fix closed, one digit further out, which is what an enumeration
#: of spellings is always one digit away from. ``_rung_leak`` finds each
#: decimal in the prose and PARSES it instead, so any spelling that denotes a
#: rung value is that rung value and the set below never has to grow.
#:
#: TWO SPELLINGS ARE DELIBERATELY OUT, decided here rather than silently
#: omitted:
#:
#: * ``85%``. A percentage is not the number -- 85 is not 0.85 -- and the five
#:   rungs times a hundred are 95, 85, 70, 55 and 30: bare integers that
#:   ordinary decision prose is full of ("30 seconds", "a 70 GB index", "55
#:   open connections"). Screening them would stop real records by the dozen to
#:   catch a spelling nothing in this module ever writes, in a file whose only
#:   prescribed remedy is to reword a sentence.
#: * ``8.5e-1``. Nothing here writes a rung in scientific notation, a brain
#:   reading it does not read the ladder, and admitting exponents admits every
#:   ``1e-3`` in a config discussion to the same parse. The cost of missing it
#:   is a leak nobody writes; the cost of catching it is stops on prose people
#:   do write.
_RUNG_VALUE_NUMBERS = frozenset(RUNGS.values())

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


def _quotes_word(lowered: str, token: str) -> bool:
    """Whether ``token`` stands in ``lowered`` as a WHOLE word.

    Two screens ask this question of agent-authored prose -- the ladder screen
    below, which refuses a hyphenated rung name, and the challenge screen in
    ``_open_under_lock``, which refuses a re-open that names one of the brains
    whose answer it is challenging. A whole-word test rather than a substring
    one for the same reason in both: ``code-evidenced`` inside
    ``code-evidenced-ish`` is one word, and ``brain-a`` inside ``brain-ab`` is
    another brain. Both arguments are already casefolded by the caller, which
    is stated here because a caller that forgets makes this screen silently
    case-sensitive.

    An EMPTY token matches nothing. It would otherwise match at every position
    and refuse every string, which on the owner screen is a corrupt owner list
    closing the challenge door for the whole run.
    """
    if not token:
        return False
    start = lowered.find(token)
    while start != -1:
        end = start + len(token)
        #: ``lowered[start - 1:start]`` is the EMPTY STRING at the very start
        #: of the value -- a slice, not an index -- and ``_wordish("")`` is
        #: false, so a token at either end is quoted as much as one in the
        #: middle.
        if not (_wordish(lowered[start - 1:start])
                or _wordish(lowered[end:end + 1])):
            return True
        start = lowered.find(token, start + 1)
    return False


def _decimal_leak(lowered: str) -> str | None:
    """The first decimal in ``lowered`` that DENOTES a rung value, as written.

    A NUMBER IS PARSED, NOT A SPELLING MATCHED, which is the whole of why this
    is a scan and not a ``find``. Every decimal in the prose is taken whole and
    handed to ``float``, so ``0.85``, ``0.850``, ``0.8500``, ``0.85000`` and
    ``.85`` are one leak and the screen cannot be one trailing zero behind the
    writer.

    A DECIMAL IS A MAXIMAL RUN of digits and dots, and taking the run whole is
    what keeps the fragments out without a boundary rule: ``$10.85 per million
    tokens`` yields ``10.85`` and ``a p99 of 10.3 seconds`` yields ``10.3``,
    numbers that are not rungs, where a substring search found ``0.85`` and
    ``0.3`` inside them.

    THREE RUNS ARE PASSED OVER, each because it is not a single decimal:

    * One ``float`` cannot read. ``1.0.85`` and ``0.30.0`` are version strings
      and ``..`` is punctuation; a run with two dots in it denotes no number.
    * One whose integer part carries a leading zero it does not need --
      ``000.85``, the tail of ``$1,000.85`` after the comma ends the run. A
      grouped number is the one place a digit run legitimately starts with
      redundant zeros, and the rung is never written that way.
    * A trailing ``.``, which is stripped first because it is punctuation:
      ``adopted at 0.85.`` ends a sentence and is exactly the leak. It is only
      punctuation at the END of the run -- ``0.85.1`` keeps both dots, reads as
      no number, and passes. That asymmetry is the one judgement call in here
      and it is deliberate.
    """
    index = 0
    length = len(lowered)
    while index < length:
        if not (lowered[index].isdigit() or lowered[index] == "."):
            index += 1
            continue
        start = index
        while index < length and (lowered[index].isdigit()
                                  or lowered[index] == "."):
            index += 1
        token = lowered[start:index].rstrip(".")
        whole = token.split(".", 1)[0]
        if whole.startswith("0") and whole != "0":
            continue
        try:
            number = float(token)
        except ValueError:
            continue
        if number in _RUNG_VALUE_NUMBERS:
            return token
    return None


def _rung_leak(value: str) -> str | None:
    """The first rung VALUE or compound rung NAME quoted inside ``value``.

    EXACTLY WHAT IS SCREENED, and exactly what is not:

    * Every rung value, in ANY spelling that denotes the number: ``0.85``,
      ``0.850``, ``0.8500`` and ``.85`` are one leak, because the decimal is
      parsed rather than matched against a list of spellings. ``adopted at
      0.85``, ``(0.85)``, ``rung=0.85`` and ``adopted at 0.85.`` all hit.
      ``$10.85 per million tokens``, ``a p99 of 10.3 seconds``, ``v1.0.85`` and
      ``^0.30.0`` do not. See ``_decimal_leak`` for how a decimal is bounded,
      and ``_RUNG_VALUE_NUMBERS`` for why ``85%`` and ``8.5e-1`` are out.
    * Every HYPHENATED rung name, as a whole word: ``code-evidenced``,
      ``convention-cited``, ``engineering-judgement``.

    NOT SCREENED: ``specified`` and ``speculation``, the two rung names that are
    also ordinary English words. See ``_RUNG_NAME_STRINGS`` for why, and for
    what that costs.

    WHAT IT COSTS ON THE OTHER SIDE, stated here because a writer meets it as a
    stop and nowhere else tells them why: the screen cannot tell a rung from a
    UNIT. A decimal that happens to equal a rung value is refused however
    innocent it is -- ``timeout of 0.7 seconds``, ``the price is $0.30 per
    request``, ``a 0.55 ratio of reads to writes``, ``the hit rate is 0.85 of
    requests`` -- so an axis like "what cache hit rate do we target?" cannot be
    recorded in those words. This is believed irreducible: nothing in the text
    distinguishes 0.85-the-hit-rate from 0.85-the-rung, and guessing from the
    surrounding words would make the screen a heuristic exactly where it is
    relied on to be total. THE REMEDY IS TO REWORD OR RESCALE: ``700ms``, ``30
    cents per request``, ``11 reads per 20 writes``, ``a hit rate of 85%`` --
    the percentage spelling is deliberately not screened, so it is always
    available.

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
    leaked = _decimal_leak(lowered)
    if leaked is not None:
        return leaked
    for token in _RUNG_NAME_STRINGS:
        if _quotes_word(lowered, token):
            return token
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
                    "the record is still being written. The screen cannot tell "
                    "a rung from a UNIT, so an innocent decimal that equals one "
                    "-- 'timeout of 0.7 seconds', 'the hit rate is 0.85 of "
                    "requests' -- is refused too; rescale it ('700ms', 'a hit "
                    "rate of 85%') or say it in words")
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
    #:
    #: LINEAR, and that is not a micro-optimisation. ``decisions.md`` is
    #: append-only and only grows, and the walk this replaced re-walked the
    #: whole downstream chain from every retired record with ``in`` over a LIST:
    #: cubic on a perfectly legal succession, 12s at 2000 records against 0.03s
    #: here, on input with no cycle in it at all. ``terminates`` remembers every
    #: record already PROVEN to reach a live decision, so each is walked once;
    #: ``in_chain`` is the same membership test as ``chain`` and is a set. A
    #: record only enters ``terminates`` after its walk completed without
    #: raising, so no member of a cycle can ever be in it, and reaching one is
    #: proof this chain terminates too.
    terminates: set = set()
    for did in sorted(decisions):
        if decisions[did]["status"] != "Superseded" or did in terminates:
            continue
        chain = [did]
        in_chain = {did}
        successor = claimed[did]
        while decisions[successor]["status"] == "Superseded":
            if successor in in_chain:
                raise TrackerValidationError(
                    f"{chain} form a Supersedes cycle; every record in it is "
                    "Superseded and each is replaced by another record in the "
                    "same loop, so the chain never terminates in a live "
                    "decision and no reader can say what replaced any of them "
                    "-- which is the one question a reader of a retired record "
                    "has")
            if successor in terminates:
                break
            chain.append(successor)
            in_chain.add(successor)
            successor = claimed[successor]
        terminates |= in_chain

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

    QUESTION, ANSWER AND PROVENANCE, and no fourth field: no rejected
    alternatives, no consequences, no depth, no scope, and no ``Grounding
    rung`` or ``Runner-up rung``. That is the FIELD whitelist and it is exact.

    WHAT THE FIELD WHITELIST DOES NOT BUY is a claim about the text inside the
    three fields it admits, and the two are stated apart here because
    collapsing them is how this docstring has over-claimed three times running.
    A ladder quoted inside ``question`` or ``answer`` arrives through a field
    the whitelist has already approved, so those two get a CONTENT screen on
    top -- and that screen is narrower than the whitelist, deliberately, in a
    way a reader of this contract has to be told rather than left to find:

    * CAUGHT: every rung VALUE in any spelling that denotes the number
      (``0.85``, ``0.850``, ``.85``), and the three HYPHENATED rung names
      ``code-evidenced``, ``convention-cited`` and ``engineering-judgement``.
    * NOT CAUGHT, and never will be: ``specified`` and ``speculation``, the two
      rung names that are also ordinary English words. ``Answer: postgres --
      adopted on speculation, runner-up sqlite`` projects VERBATIM. No rule can
      refuse those two words and still admit "use the schema specified in the
      RFC" and "redis -- avoids speculation about disk contention", which are
      real answers in a file whose only prescribed remedy is to reword a
      sentence. ``_RUNG_NAME_STRINGS`` derives the screen on the hyphen for
      that reason and ``_rung_leak`` repeats the cost; it is repeated a third
      time HERE because this is the entry point, and the entry point is the
      contract a reader trusts.
    * ALSO NOT CAUGHT, by the same argument one level down: a rung value
      written ``85%`` or ``8.5e-1``. See ``_RUNG_VALUE_NUMBERS``.

    Read the bullets as the whole of the content claim. "No rung name reaches a
    brain" is not true, has never been true since the hyphen narrowing, and any
    future sentence in this docstring that says it is has to be measured
    against them.

    ``provenance`` is the third projected field and the only one that is an
    ENUM, so it is screened by membership against ``_PROVENANCES`` instead --
    strictly narrower than any content rule, and what an enum field should get.
    LEFT UNSCREENED it would project ``human -- adopted at 0.85,
    code-evidenced`` verbatim into the one file a brain reads, through the one
    projected field the screen missed.

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

    A CONTENT HIT IS A STOP AND NEVER A STRIP. ``Answer: postgres -- adopted at
    0.85, code-evidenced, runner-up speculation`` is refused twice over, by the
    value and by the compound name -- not edited down to ``postgres``. A
    decision record whose prose quotes the ladder is a record that should never
    have been written, and silently editing the audit trail on its way to a
    brain would leave the file and what the brain read disagreeing about what
    was decided. (The same sentence also shows the give-up: strike ``0.85`` and
    ``code-evidenced`` from it and the surviving ``runner-up speculation``
    projects.)

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


# --- contradiction and depth ----------------------------------------------
#
# The two questions asked of a candidate answer before a quorum may adopt it:
# does it disagree with something already decided, and how far from the last
# thing a human said does it stand.
#
# BOTH ARE EXPOSED TO THE SAME FAILURE, and it is the failure this section is
# shaped around: "I could not work it out" coming back as "no". A contradiction
# check that cannot compare two answers and returns ``None`` reports the
# candidate as compatible with a decision it was never measured against; a
# depth walk that cannot resolve an anchor and skips it reports the candidate
# at the shallowest -- most adoptable -- depth there is. Neither raises,
# neither logs, and both look exactly like the healthy answer. So every input
# either decides or STOPS, and nothing in here treats undetermined as clear.
#
# The stop class is ``QuorumSchemaInvalid`` wherever the unusable thing is the
# CANDIDATE, because that is the one the controller already knows how to
# recover from: re-dispatch that brain once, then escalate. It is
# ``TrackerValidationError`` wherever the unusable thing is the DECISIONS
# STRUCTURE, because a malformed audit trail is a read-only stop and no
# re-dispatch repairs it.


def _decision_records(decisions) -> dict:
    """The record mapping out of a ``parse_decisions`` result, or a stop.

    Handed the whole result rather than the records alone, for the reason
    ``project_decisions`` states: the shape it cannot read would come back as
    "this run has decided nothing", which is indistinguishable from a run that
    genuinely has and is the most permissive answer either function can give.
    """
    if not isinstance(decisions, dict) or not isinstance(
            decisions.get("decisions"), dict):
        raise TrackerValidationError(
            "check_contradiction and decision_depth take the whole "
            "parse_decisions result, not the records alone; a shape neither "
            "can read would report every candidate as contradicting nothing "
            "and standing one step from a human, which is the answer that "
            "adopts")
    return decisions["decisions"]


def _decision_binds(record, did: str) -> bool:
    """Whether one record is a decision this run is bound by RIGHT NOW.

    One predicate for both callers, because they ask the same question for the
    same reason. ``check_contradiction`` compares a candidate only against
    decisions in effect -- a Superseded record was retired and an Open one has
    no answer -- and ``decision_depth`` measures distance only from decisions
    in effect, because an answer anchored to a retired record is grounded in
    something the run has already stopped believing.

    BOTH EXTENSION ACTIONS ARE EXCLUDED, not just the quorum one. A budget
    grant's answer is a CEILING, not an option on an axis: compared as an
    answer key it disagrees with every real answer, and anchored to as
    grounding it prices a ceiling as a decision. ``project_decisions`` already
    withholds both from brains for the same reason, and one of the two being
    named here and not the other would make the pair disagree about what a
    decision is.

    The three enum fields are screened by ``_member`` and screened FIRST, ahead
    of every text read below them. That ordering is the whole of why the screen
    is observable: this function is handed records a caller may have built, and
    ``["Adopted"] in frozenset(...)`` raises ``TypeError`` -- outside
    ``TrackerError``, so it escapes every ``except TrackerError`` a controller
    has written. Placed after a ``_text`` check no unhashable value could ever
    reach it, and a bare ``in`` written here would pass the suite.
    """
    if not isinstance(record, dict):
        raise TrackerValidationError(
            f"{did}: a decision record is {type(record).__name__}, not an "
            "object; a record that cannot be read cannot be shown not to bind")
    if not _member(record.get("status"), _DECISION_STATUS_NAMES):
        raise TrackerValidationError(
            f"{did}: status {record.get('status')!r} is not one of "
            f"{list(_DECISION_STATUSES)}; a record whose status cannot be read "
            "is a record that cannot be shown to be out of effect, and the "
            "permissive reading of that is the one that adopts")
    if not _member(record.get("action"), _DECISION_ACTIONS):
        raise TrackerValidationError(
            f"{did}: action {record.get('action')!r} is not a decision action; "
            "the extension actions are excluded by name, and an unreadable "
            "action is excluded from nothing")
    if not _member(record.get("provenance"), _PROVENANCES):
        raise TrackerValidationError(
            f"{did}: provenance {record.get('provenance')!r} is not one of "
            f"{sorted(_PROVENANCES)}; provenance is what routes a rejection to "
            "the escalation queue rather than back to a re-opened qid, and an "
            "unreadable one routes by accident")
    if record["status"] != "Adopted":
        return False
    return not _member(record["action"], _EXTENSION_ACTIONS)


def _comparable_record(record: dict, did: str) -> dict:
    """The two fields ``_contradiction`` compares, screened before it reads them.

    ``_contradiction`` is written against ``parse_decisions`` output and is
    total over it. It is NOT total over an arbitrary mapping, and each half of
    this screen closes one way for an unreadable record to come back as a
    VERDICT instead of as a stop:

    * a non-string ``answer_key`` compares unequal to every candidate key, so a
      malformed record is reported as a contradiction the candidate never had
      -- and ``.strip()`` on it raises ``AttributeError``, outside
      ``TrackerError``.
    * ``consequences`` that are not a mapping raise ``TypeError`` out of
      ``set(...)`` on an ``int``, and walk one character at a time on a ``str``
      -- which shares no key with any candidate, so every clash is compared on
      an empty intersection and passes.
    * a key or value inside it that is not the ``(kind, subject) -> value``
      shape ``_consequence_map`` builds is compared as something it is not: the
      difference that comes back is a fact about the record rather than about
      the answer, reported under the answer's name.
    """
    if not _text(record.get("answer_key")):
        raise TrackerValidationError(
            f"{did}: answer_key {record.get('answer_key')!r} is not an answer; "
            "an unreadable key differs from every candidate key, so the record "
            "would contradict everything and name itself as the reason")
    consequences = record.get("consequences")
    if not isinstance(consequences, dict):
        raise TrackerValidationError(
            f"{did}: consequences are {type(consequences).__name__}, not the "
            "kind:subject -> value mapping parse_decisions builds; a shape the "
            "comparison cannot read shares no key with any candidate, so every "
            "clash is compared on an empty intersection and passes")
    for key, value in consequences.items():
        if (not isinstance(key, tuple) or len(key) != 2
                or not all(isinstance(part, str) for part in key)
                or not isinstance(value, str)):
            raise TrackerValidationError(
                f"{did}: consequence key {key!r} is not a (kind, subject) pair "
                "of strings; keys of mixed type raise out of the sort that "
                "orders the shared ones, which is an exception outside this "
                "module's family thrown by the check that stops the run")
    return {"answer_key": record["answer_key"].strip(),
            "consequences": consequences}


def _candidate_consequences(consequences) -> dict:
    """A candidate's consequence list as the mapping ``_contradiction`` compares.

    Screened through ``_consequence_problems`` -- the same gate
    ``validate_brain_response`` puts a real response through -- rather than
    read defensively item by item, so a consequence legal in a response and
    illegal here cannot exist.

    THE EMPTY LIST IS A STOP, and that is the fail-open this whole section is
    built around. A candidate with no consequences shares no key with any
    record, so every comparison falls back to the answer key alone: two
    genuinely incompatible answers that happen to name the same option are
    compared on an empty intersection and pass. The response schema requires
    consequences for exactly this reason, and accepting a candidate without
    them here would reopen the hole one layer down.
    """
    problems = sorted(set(_consequence_problems(consequences)))
    if problems:
        raise QuorumSchemaInvalid(
            f"candidate consequences are unusable {problems}; a consequence is "
            "an assertion that would be verifiably true of the repository if "
            "the answer were adopted, and one that is not matches no record, "
            "so the clash it should have caught is compared on an empty "
            "intersection and passes")
    mapping: dict = {}
    for item in consequences:
        key = (item["kind"], item["subject"].strip())
        if key in mapping:
            raise QuorumSchemaInvalid(
                f"candidate asserts {key[0]}:{key[1]} twice; a candidate that "
                "contradicts itself agrees with whichever adopted record is "
                "compared against whichever of its two values is kept")
        mapping[key] = item["value"].strip()
    return mapping


def check_contradiction(decisions: dict, candidate: dict) -> str | None:
    """The D-ID this candidate contradicts on its axis, or ``None``.

    STRUCTURAL, NEVER SEMANTIC. Every stage-03 question has a stable axis id
    and every later question is tagged to one, so the whole of the check is:
    on this axis, does the candidate name a different option, or assert a
    different value for something an adopted decision already asserted. No
    text is compared for meaning and no answer is interpreted.

    ``None`` MEANS COMPARED AND COMPATIBLE. It never means "could not
    compare": every input that cannot be measured against the axis is a stop,
    because a check that returns its clear answer when it has no answer is a
    check whose failures all fall the way that adopts. So the candidate must
    carry a legal axis, an answer key that is an answer, and at least one
    well-formed consequence, and every record on the axis must be readable.

    THE RESERVED AXIS IS REFUSED OUTRIGHT. ``new`` is the placeholder for a
    question that was never tagged, and ``parse_decisions`` refuses it as a
    record's axis, so the index can never hold it: a candidate arriving on
    ``new`` would find no records, clear the check by being unrecognisable, and
    be adopted against an axis nobody had ever looked at. That is the same
    fail-open shape ``_BLAST_RADII`` is closed against, and the caller's fix is
    to mint the question's own qid as the axis -- which is what the adoption
    path does -- not to let the placeholder through.

    A GENERIC APPROVAL IS REFUSED for the same reason ``parse_decisions``
    refuses one, and the rule does not vary by provenance: ``yes`` is not an
    option on an axis, so comparing it as one reports a contradiction with
    every record that ever named a real option -- routing a candidate that said
    nothing to ``rejected-contradicts-human``.

    HUMAN-PROVENANCE DECISIONS ARE SCANNED FIRST so that the D-ID that comes
    back names the human decision whenever one is contradicted; the rejection
    status (``rejected-contradicts-human`` against
    ``rejected-contradicts-quorum``) and the terminal report both key off which
    one it is.

    That ordering is now a BACKSTOP rather than a live discriminator, and
    saying so is the point: ``parse_decisions`` enforces at most one Adopted
    decision per axis, so a file cannot present a human and a quorum decision
    both binding on one axis -- a later adoption supersedes the record standing
    there. The ordering is kept because this function does not take a file, it
    takes a mapping, and a caller that assembles one (a projection, a merge of
    two runs, a test) can hand it the pair the file grammar refuses. Deleted,
    the D-ID would then come back by dict iteration order and the rejection
    status would be right by luck.
    """
    records = _decision_records(decisions)
    index = decisions.get("axis_index")
    if not isinstance(index, dict):
        raise TrackerValidationError(
            f"axis_index is {type(index).__name__}, not the axis -> [D-ID] "
            "mapping parse_decisions builds; an index that cannot be read "
            "produces no records on any axis, so every candidate contradicts "
            "nothing")
    if not isinstance(candidate, dict):
        raise QuorumSchemaInvalid(
            f"candidate is {type(candidate).__name__}, not an object; there is "
            "no axis to check it on and no answer to check")
    axis = candidate.get("axis")
    #: ``isinstance`` BEFORE the grammar, and before the lookup. ``_TOKEN``
    #: indexes its argument, so an ``int`` axis raises ``TypeError`` inside the
    #: grammar; an unhashable one raises it inside ``index.get``. Both are
    #: outside ``TrackerError``.
    if not isinstance(axis, str) or not _TOKEN.fullmatch(axis):
        raise QuorumSchemaInvalid(
            f"candidate axis {axis!r} is not a legal axis token; the axis is "
            "the key this check groups by, and one that cannot be a key groups "
            "with nothing and contradicts nothing")
    if axis == _RESERVED_AXIS:
        raise QuorumSchemaInvalid(
            f"candidate axis is the reserved literal {_RESERVED_AXIS!r}, which "
            "no decision record may carry, so it indexes nothing and every "
            "candidate on it passes by being unrecognisable; the adoption path "
            "mints the question's own qid as the axis")
    answer_key = candidate.get("answer_key")
    if not _text(answer_key):
        raise QuorumSchemaInvalid(
            f"candidate answer_key {answer_key!r} is not an answer; a blank key "
            "names no option, so it differs from every adopted key and would be "
            "reported as contradicting a decision it never disagreed with")
    if answer_key.strip().rstrip(".").casefold() in _GENERIC_ANSWERS:
        raise QuorumSchemaInvalid(
            f"candidate answer_key {answer_key!r} is a generic approval, not an "
            "answer to an unresolved choice; it names no option on this axis, "
            "so comparing it as one reports a contradiction with whatever was "
            "decided rather than with anything this candidate actually said")
    probe = {"answer_key": answer_key.strip(),
             "consequences": _candidate_consequences(
                 candidate.get("consequences"))}
    ids = index.get(axis, ())
    if isinstance(ids, str) or not isinstance(ids, (list, tuple)):
        raise TrackerValidationError(
            f"axis {axis} indexes {type(ids).__name__}, not a list of D-IDs; a "
            "string walks one character at a time and anything else walks not "
            "at all, and a walk over nothing contradicts nothing")
    #: Human first, then the file's own order within each group. ``enumerate``
    #: is in the key so the sort is stable on a mapping whose iteration order
    #: is not the file's.
    ranked = []
    for position, did in enumerate(ids):
        if not _member(did, records):
            raise TrackerValidationError(
                f"axis {axis} indexes {did!r}, which the decision records do "
                "not hold; the index and the records disagree about what was "
                "decided, and the candidate would be compared against the "
                "records that happen to survive the disagreement")
        record = records[did]
        if not _decision_binds(record, did):
            continue
        ranked.append((0 if record["provenance"] == "human" else 1,
                       position, did))
    for _rank, _position, did in sorted(ranked):
        if _contradiction(_comparable_record(records[did], did), probe) is not None:
            return did
    return None


def decision_depth(decisions: dict, consistent_with: list) -> int:
    """Layers of inference away from the last thing a human actually said.

    A human decision is depth 0, so an answer citing only depth-0 material is
    depth 1. ``spec`` and ``repo`` anchors are FACTS rather than inferences and
    contribute 0: the specification and the repository are not something the
    run reasoned its way to. Depth 3 is past ``DEPTH_CAP`` and is not
    quorum-eligible -- three layers out is where a run stops building the
    user's product and starts building its own.

    EVERY ANCHOR EITHER COUNTS OR STOPS. Nothing is skipped, and that is the
    ruling this function owes.

    THE ID-LESS ANCHOR, decided here. Task 4 validated ``Consistent with`` in
    ``decisions.md`` -- ids only, no repeat, no self-reference, every anchor
    resolving to a record the file holds -- and that closed the MARKDOWN half
    of the hazard only. The JSON half was still open when this was written:
    ``_anchor_problems`` checked a brain response's ``consistent_with`` items
    for ``kind`` and for nothing else, so ``[{"kind": "decision"}]`` was a
    SCHEMA-VALID response carrying an anchor that names no decision -- and it
    is a response, not a file, that this function walks. Skipping it would
    resolve to no record, contribute 0, and return 1: the shallowest and most
    adoptable depth there is, handed to the answer with the least grounding.
    So an anchor of kind ``decision`` that does not name a record in effect is
    a stop, ``_anchor_problems`` now requires the id as well, and the two
    layers are deliberately redundant -- this function is called with mappings
    that never went through that validator.

    An anchor NAMING A RECORD THAT DOES NOT BIND is a stop too. A Superseded
    decision was retired and an Open one has no answer, and neither is ever
    projected to a brain, so an answer claiming to stand on one is claiming to
    stand on something it could not have read. Counted, it would price that
    claim at the retired record's depth; skipped, at zero.

    An unknown anchor KIND is a stop for the same reason: contributing 0 makes
    an answer anchored entirely to kinds nobody defined come back at depth 1.
    """
    records = _decision_records(decisions)
    if not isinstance(consistent_with, list) or not consistent_with:
        raise QuorumSchemaInvalid(
            f"consistent_with is {consistent_with!r}; an answer anchored to "
            "nothing has no measurable distance from anything a human said, so "
            "its depth is unbounded by construction -- this is a stop and never "
            "a depth of 1")
    deepest = 0
    for entry in consistent_with:
        if not isinstance(entry, dict):
            raise QuorumSchemaInvalid(
                f"anchor {entry!r} is {type(entry).__name__}, not an object; an "
                "anchor with no readable kind contributes nothing to the walk, "
                "and a walk that contributes nothing returns the shallowest "
                "depth there is")
        #: FIRST, and by ``_member``. An anchor's ``kind`` is the one field
        #: read before anything has established a type, so this is where an
        #: unhashable value actually arrives: ``["decision"] in frozenset(...)``
        #: raises ``TypeError``, outside ``TrackerError``. A bare ``in`` here
        #: fails the suite; placed below a ``_text`` guard it could not.
        kind = entry.get("kind")
        if not _member(kind, _ANCHOR_KINDS):
            raise QuorumSchemaInvalid(
                f"anchor kind {kind!r} is not one of {sorted(_ANCHOR_KINDS)}; an "
                "unrecognised kind contributes 0 to the walk, so an answer "
                "anchored entirely to kinds nobody defined would come back at "
                "the shallowest depth there is")
        if kind != "decision":
            #: A fact, not an inference. The specification and the repository
            #: are where the run started, not somewhere it reasoned to.
            continue
        anchor = entry.get("id")
        if not _text(anchor) or _id_provenance(anchor.strip()) is None:
            raise QuorumSchemaInvalid(
                f"anchor {anchor!r} is not a decision id (H-<n> or Q-<qid>); an "
                "anchor without an id lets an answer claim grounding in a "
                "decision it never names, and resolving it to nothing prices "
                "that claim at the shallowest depth there is")
        anchor = anchor.strip()
        if not _member(anchor, records):
            raise QuorumSchemaInvalid(
                f"anchor {anchor} names a decision this run does not hold; "
                "grounding nothing can produce is grounding nothing can check, "
                "and counting it as absent counts it as costless")
        if not _decision_binds(records[anchor], anchor):
            raise QuorumSchemaInvalid(
                f"anchor {anchor} is not a decision in effect; a Superseded "
                "record was retired, an Open one has no answer, and a budget "
                "grant's answer is a ceiling -- none of the three is ever shown "
                "to a brain, so an answer standing on one is standing on "
                "something it could not have read")
        depth = records[anchor].get("depth")
        if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
            raise QuorumSchemaInvalid(
                f"{anchor}: depth {depth!r} is not a non-negative integer; "
                "``True`` is not a depth of 1 and a depth that cannot be read "
                "cannot be added to")
        if depth > deepest:
            deepest = depth
    return deepest + 1


# --- admissibility and the per-brain payload ------------------------------
#
# Three instances of one model reading one payload are NOT three independent
# samples. They are one prior sampled three times: shared weights plus a shared
# prompt produce correlated error, so agreement between them is far weaker
# evidence than a headcount makes it look. Independence is MANUFACTURED here,
# and by exactly two moves.
#
#   * Every brain gets the IDENTICAL VERBATIM question. That is what makes the
#     three answers comparable at all -- three brains asked three paraphrases
#     have not disagreed about an answer, they have answered three questions.
#   * Every brain gets a DIFFERENT READING ASSIGNMENT, which biases it toward a
#     SOURCE and never toward an answer. A bias toward a source is the only
#     kind that decorrelates without also deciding.
#
# The second move is also what makes the rung distribution informative: three
# brains that each looked somewhere different and none of them found grounding
# is the mechanical signature of drift, and that signature is unavailable if
# all three read the same shelf.


#: Three assignments, each biased toward a SOURCE and never toward an answer.
#:
#: A constant RULE rather than data, frozen beside ``RUNGS`` for the same
#: reason those are: a controller that can write its own assignment rule can
#: change what a brain was asked after the fact. Because the rule is constant
#: and ``build_payload`` is pure with respect to the index, brain n's payload is
#: determined entirely by ``(shared payload, n)``. That is what lets ONE digest
#: bind all three, and it is what makes a re-dispatch of brain n reproducible
#: from ``(payload_digest, n)``. It stops being true the moment anything about
#: the assignment is read from the tracker or from run state, at which point the
#: partial-quorum recovery path would silently re-send a brain a payload it had
#: never received and compare the answer against the wrong question.
READING_ASSIGNMENTS = (
    MappingProxyType({"index": 0, "label": "spec-and-intent",
                      "read": ("spec", "intent-brief")}),
    MappingProxyType({"index": 1, "label": "code-and-tests",
                      "read": ("repo", "tests")}),
    MappingProxyType({"index": 2, "label": "decisions-and-plan",
                      "read": ("decisions-effective", "phase-plan")}),
)

#: Every source some brain is sent to, in assignment order. Derived, never
#: retyped: a second list of the six names would pass on the day it was written
#: and send a brain to an unstated root the day either copy was edited.
_ASSIGNED_SOURCES = tuple(
    source for assignment in READING_ASSIGNMENTS for source in assignment["read"]
)

#: The one reading root the RUN states and the raiser may not. Where the
#: effective decisions projection lives is a fact about this run, not a claim
#: the raising worker gets to make, and two spellings of one path is one path
#: too many: the raiser's copy is what brain 2 would be sent to read while the
#: payload's ``decisions_effective`` says somewhere else, and the disagreement
#: surfaces only as citations that do not resolve.
_DERIVED_ROOT = "decisions-effective"

#: The roots the question record must state, because nothing else knows them.
_DECLARED_ROOTS = tuple(
    source for source in _ASSIGNED_SOURCES if source != _DERIVED_ROOT
)

#: Adjectives describe how someone feels about a choice instead of naming it,
#: and an answer to them cannot be written down as a decision. This is the
#: options test from ``plugins/superb/agents/architecture-discovery.md:54-73``,
#: stated mechanically: blank the title, keep the options, and a reader can
#: still tell what is being decided -- which is false of every word below.
#:
#: Folded spellings only. ``check_admissible`` folds the candidate before it
#: asks, so a capitalised ``Modern`` is caught and an entry typed here with a
#: capital would be unreachable.
_NON_OPTIONS = frozenset({
    "modern", "traditional", "scalable", "simple", "pragmatic", "robust",
    "clean", "flexible", "best-practice", "best practice", "standard",
    "idiomatic", "lightweight",
})

#: What a brain is told to send back. It names the response keys and it names
#: the prohibition that makes the whole ladder work -- select a rung BY NAME,
#: never write a number -- and it carries no number of its own for a brain to
#: read a bar off.
_RESPONSE_SCHEMA_DOC = (
    "Return one JSON object and nothing else. Required keys: qid, answer_key, "
    "answer, rung, evidence, consequences, consistent_with, forecloses, blast, "
    "alternatives, what_would_change_my_mind, blocker. Any other key is "
    "rejected. Select a rung by name from `rungs`; never write a number "
    "anywhere in the response. Every evidence item must quote text that is "
    "actually at the place it cites. `alternatives` must name a rejected "
    "second-best with a real reason. If you cannot answer, set `blocker`."
)


def _entries(value) -> list:
    """The non-blank strings in a JSON list, or ``[]`` for anything else.

    A BARE STRING IS NOT A LIST OF ONE. ``"T04"`` iterates as three characters,
    each of them ``_text``-true, so a caller that simply iterated would read a
    single mistyped cell as three blockers -- and a question that blocks
    nothing would be admitted on the strength of a typo. A number does not
    iterate at all and raises ``TypeError``, outside ``TrackerError``, from a
    function whose whole job is to return a list of problems.
    """
    if not isinstance(value, (list, tuple)):
        return []
    return [entry.strip() for entry in value if _text(entry)]


def _option_keys(options) -> tuple[list, list]:
    """``(stated keys, problems)`` for a record's options.

    Returns the raw key of EVERY option, folded where folding is possible, so
    that the options test below sees values a bare ``in`` would have raised on.
    """
    problems: list[str] = []
    keys: list[str] = []
    if not isinstance(options, (list, tuple)):
        return keys, ["options-are-not-a-list"]
    for option in options:
        #: An option is ``{"key": ...}``; a bare string is read as its own key
        #: so that a record which skipped the wrapper is still judged rather
        #: than waved through as "no options at all".
        key = option.get("key") if isinstance(option, dict) else option
        #: FOLD ONLY WHAT CAN BE FOLDED, and let ``_member`` judge the rest.
        #: This is the call site rule 9 exists for and it is placed ABOVE the
        #: ``_text`` screen deliberately: a JSON option key may legally be
        #: ``["modern"]`` or ``{"modern": 1}``, both unhashable, and
        #: ``value in frozenset(...)`` HASHES its left operand. Reverting this
        #: to a bare ``in`` raises ``TypeError`` -- outside ``TrackerError``,
        #: so it escapes every handler a controller has written -- on a
        #: raiser's typo. Below a ``_text`` guard no unhashable value could
        #: ever reach it and the pin would be unobservable.
        folded = key.casefold() if isinstance(key, str) else key
        if _member(folded, _NON_OPTIONS):
            problems.append("options-fail-the-options-test")
        if _text(key):
            keys.append(key.strip())
        else:
            problems.append("option-key-is-not-text")
    return keys, problems


def check_admissible(record: dict) -> list[str]:
    """Mechanical admissibility, as a list of problem codes; ``[]`` admits.

    ONLY the criteria that can be enforced mechanically. Criterion 2
    ("decidable from the repository") and criterion 5 ("one decision, not
    several") are judgment calls carried by P07's prose and by the raiser's own
    declaration; criteria 1, 3 and 4 are checked here:

    * **1 -- it blocks something.** A question that blocks no task is an
      opinion, and a quorum spent on an opinion is three dispatches and a
      decision record for something nothing was waiting on.
    * **3 -- it names an axis.** The axis is the contradiction bucket. A
      question with no axis contradicts nothing BY CONSTRUCTION and clears the
      contradiction check by being unrecognisable rather than by being
      compatible -- the same fail-open shape ``_BLAST_RADII`` is closed
      against.
    * **4 -- the options test.** Blank the title, keep the options, and a
      reader can still tell what is being decided. Mechanically: adjectives are
      not options, and fewer than two options is not a question.

    Every problem is reported, not just the first, because a raiser fixing one
    at a time pays a dispatch round per fix. Codes are de-duplicated: the list
    is a set of faults, and a record with four adjectives has one fault.

    NOTHING HERE RAISES ON CONTENT. The record is agent-supplied JSON-shaped
    data and every field may legally hold any JSON value; a validator that
    raises on a malformed record has not classified it.
    """
    if not isinstance(record, dict):
        raise QuorumSchemaInvalid(
            f"a question record is {type(record).__name__}, not an object; "
            "admissibility is a judgement about fields, and a record with no "
            "fields is not an inadmissible question, it is not a question")
    problems: list[str] = []
    if not _entries(record.get("blocks")):
        problems.append("blocks-nothing")
    if not _text(record.get("axis")):
        problems.append("missing-axis")
    if not _text(record.get("question")):
        problems.append("missing-question")
    owners = _entries(record.get("owners"))
    if (not isinstance(record.get("owners"), (list, tuple))
            or len(record["owners"]) != _BRAINS or len(owners) != _BRAINS):
        problems.append("owner-count-is-not-three")
    elif len(set(owners)) != _BRAINS:
        #: ``_validate_quorum`` refuses a row whose three owners are not
        #: distinct, for the reason it states there: one brain dispatched twice
        #: is a majority manufactured from a single opinion. Catching it here
        #: refuses the question instead of the row it would have produced.
        problems.append("duplicate-owners")
    supplied = record.get("options_supplied")
    if not isinstance(supplied, bool):
        problems.append("options-supplied-is-not-a-boolean")
    #: CRITERION 4 IS JUDGED OVER WHAT TRAVELS, never over what the raiser
    #: DECLARES. ``options`` is projected into all three payloads verbatim and
    #: unconditionally, so a record that states options has stated them to
    #: every brain whatever ``options_supplied`` says -- and gating the test on
    #: the flag handed the raiser a switch that turned criterion 4 off while
    #: the options it was meant to judge went out anyway. ``Options supplied:
    #: no`` beside ``Options: modern`` was admitted, and omitting the flag line
    #: entirely did the same, because it defaults to ``False``.
    #:
    #: The genuine no-options question stays admissible, which is the half a
    #: blanket rule breaks: a record that states none is judged by P07's prose,
    #: and there is nothing here for criterion 4 to be applied to.
    if supplied is True or record.get("options"):
        keys, option_problems = _option_keys(record.get("options"))
        problems.extend(option_problems)
        if len(keys) < 2:
            problems.append("fewer-than-two-options")
        if len(set(keys)) != len(keys):
            problems.append("duplicate-options")
    #: CRITERION 6 -- A RE-ASK NAMES WHAT IS NEW. This is the whole mechanical
    #: difference between a legitimate re-open and a run asking the same
    #: question again until it likes the answer: the re-ask must name the
    #: record that authorizes it AND carry the evidence that was not in front
    #: of the first three brains. A ``Reopen of`` with an empty ``Challenge``
    #: is the same question, the same context and a second roll of the dice;
    #: a ``Challenge`` with no ``Reopen of`` is evidence aimed at nothing,
    #: which would travel into three payloads while the bar stayed where it
    #: was.
    #:
    #: WHETHER A CHALLENGE IS OWED IS NOT DECIDED HERE, and that is the one
    #: half this function cannot do: it takes a record and no run, so it cannot
    #: tell a CHALLENGE (which must carry evidence) from a POST-EXTENSION
    #: RE-RAISE (which must carry none -- nothing was ever answered, so there
    #: is nothing to argue with, and what a raiser would write there at that
    #: moment is the budget, which no brain may see). ``_open_under_lock``
    #: asks it once the authority has named which kind this is.
    #:
    #: WHAT NOTHING HERE CAN CHECK is whether the evidence is any good. That is
    #: what the RAISED BAR is for, two gates further on: the re-open adopts
    #: only on a rung strictly better than the decision it challenges, so
    #: challenging evidence that changes nothing changes nothing.
    challenged = record.get("reopen_of")
    if challenged is not None and not isinstance(challenged, str):
        problems.append("reopen-of-is-not-a-decision-id")
    elif _text(challenged):
        if _id_provenance(challenged.strip()) is None:
            problems.append("reopen-of-is-not-a-decision-id")
    elif _entries(record.get("challenge")):
        problems.append("challenge-without-reopen")
    deduped: list[str] = []
    for problem in problems:
        if problem not in deduped:
            deduped.append(problem)
    return deduped


# --- the question record on disk ------------------------------------------

#: The quorum tree, and the one file in it this task reads.
_QUORUM_DIRNAME = "quorum"
_QUESTION_FILE = "question.md"

#: The projection handed to brains, by both of its names: the file inside the
#: run, and the path a brain must CITE it as.
_PROJECTION_FILE = "decisions-effective.md"

#: Record fields that are one string.
#:
#: ``reopen_of`` IS HERE AND IS NOT IN ``_record_projection``. It is the D-ID
#: of the fact that authorizes this re-ask, and it is read by the admission
#: check and by the identity derivation -- never by a payload. A brain told
#: WHICH decision is under challenge is a brain told that the ground is soft;
#: what it gets instead is the challenging evidence and the question, and it
#: prices both on their merits.
_QUESTION_TEXT_FIELDS = ("question", "axis", "phase", "raiser",
                         "recommendation", "reopen_of")

#: Record fields that are a comma-separated list of strings.
_QUESTION_LIST_FIELDS = ("blocks", "owners", "candidate_answers", "challenge")


def _record_projection(record: dict) -> dict:
    """The record's WHOLE contribution to a payload, stated in ONE place.

    ``_shared_payload`` emits exactly this, and the content screen in
    ``parse_question`` walks exactly this. Named once for the reason
    ``_SCREENED_FIELDS`` is named once one section up -- so that the projection
    and the screen cannot come to disagree about what travels.

    THE RESTATED LIST THIS REPLACES IS WHY. It named ``question`` and ``axis``
    and said of itself that those were "exactly the record's free text that
    reaches a payload"; meanwhile ``challenge`` and every reading root were
    projected verbatim to all three brains and screened by nothing. A second
    list is right on the day it is written and silently wrong afterwards.

    ``raiser``, ``recommendation`` and ``candidate_answers`` are absent, and
    their absence IS the whitelist: they are recorded for audit and have no
    route into a payload at all, so there is nothing about them to screen.
    """
    return {
        #: Identical, verbatim, for all three. Fair comparison requires it.
        "question": record["question"],
        "axis": record["axis"],
        "options": [{"key": option["key"]} for option in record["options"]],
        #: Raiser-authored paths, projected here and a second time inside
        #: ``build_payload``'s reading assignment.
        "reading_roots": dict(record["reading_roots"]),
        #: Empty except on a re-open, which carries the challenging evidence
        #: but never the challenged answer's rung or its owner. It is
        #: agent-authored free text written at the one moment a rung is being
        #: argued about, which is when the ladder is nearest to hand.
        "challenge": list(record["challenge"]),
    }


def _projected_strings(value, label: str) -> list:
    """``(where, text)`` for every string inside a projected value.

    MAPPING KEYS ARE WALKED TOO, not only their values: a reading root's source
    name is written by the raiser and travels in ``reading_roots`` beside the
    path it names.

    The walk is over the projection rather than over the record, so a field
    added to ``_record_projection`` is screened on the day it starts
    travelling, and a field the record grows that is NOT projected costs a
    raiser nothing.
    """
    if isinstance(value, str):
        return [(label, value)]
    found: list = []
    if isinstance(value, dict):
        for key in sorted(value):
            found.extend(_projected_strings(key, f"{label}/{key}"))
            found.extend(_projected_strings(value[key], f"{label}/{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_projected_strings(item, f"{label}[{index}]"))
    return found


#: ``yes``/``no``, and nothing else. A record is hand-editable, and ``true``,
#: ``1`` and ``Y`` each read as a boolean to somebody; admitting them all means
#: the empty string is the only thing that is not true.
_QUESTION_FLAGS = MappingProxyType({"yes": True, "no": False})


def _question_flag(raw: str, field: str) -> bool:
    if raw.strip().casefold() not in _QUESTION_FLAGS:
        raise QuorumSchemaInvalid(
            f"{field} is {raw.strip()!r}, not {sorted(_QUESTION_FLAGS)}; a flag "
            "whose spelling nobody agreed on is read as true by whichever "
            "reader is least careful")
    return _QUESTION_FLAGS[raw.strip().casefold()]


def _reading_roots(raw: str) -> dict:
    """``source=path`` entries, as the mapping a brain is sent to read.

    EVERY PATH HERE IS REPO-ROOT-RELATIVE, and that is checked rather than
    documented. ``effective_rung`` resolves a brain's ``evidence[].path``
    against the recorded repository root and refuses a result that escapes it,
    so a root that is absolute, or that climbs out with ``..``, sends a brain
    to a place whose citations can only be refused -- and a citation that does
    not resolve DEMOTES SILENTLY. Every grounded answer then falls to
    ``engineering-judgement``, every cluster lands under the floor, and the run
    escalates every question it is ever asked while looking correctly cautious.
    """
    roots: dict = {}
    for entry in (part.strip() for part in raw.split(",") if part.strip()):
        source, assigned, path = entry.partition("=")
        source, path = source.strip(), path.strip()
        if not assigned or not source or not path:
            raise QuorumSchemaInvalid(
                f"reading root {entry!r} is not source=path; a source with no "
                "path sends a brain nowhere, and a brain that read nowhere "
                "reports the same empty hands as a brain that looked and found "
                "nothing")
        if source in roots:
            raise QuorumSchemaInvalid(
                f"reading root {source!r} is stated twice; one of the two is "
                "the place that brain will be sent and nothing says which")
        parts = path.split("/")
        if path.startswith("/") or ".." in parts or "\\" in path:
            raise QuorumSchemaInvalid(
                f"reading root {source}={path!r} is not repo-root-relative; a "
                "brain sent outside the recorded repository root produces "
                "citations effective_rung must refuse, and a refused citation "
                "demotes without raising")
        roots[source] = path
    return roots


def parse_question(text: str) -> dict:
    """One question record's markdown, as the record dict the payload reads.

    A WHITELIST, exactly like ``project_decisions``' field whitelist and for
    the same reason: the record is hand-editable and will grow fields, and a
    reader that carried every field it found would ship each new one onward
    until somebody remembered to stop it. Only the fields named above are read;
    anything else in the file is data for a human and is unreachable from here.

    The record's durable form is markdown, not JSON, because this module's
    import allowlist is a capability boundary that holds no JSON parser and a
    hand-rolled one would be strictly weaker than the format it imitated. The
    field grammar is the one ``decisions.md`` already uses, read by the same
    ``_decision_sections``, so a record and a decision are one grammar apart
    from a reader instead of two.
    """
    sections = _decision_sections(text)
    if len(sections) != 1:
        raise QuorumSchemaInvalid(
            f"a question record holds exactly one ## section, not {len(sections)}; "
            "a file holding two questions has no single identity, and a file "
            "holding none states a question nothing can be keyed by")
    _heading, fields = sections[0]
    record: dict = {}
    for key in _QUESTION_TEXT_FIELDS:
        record[key] = fields[key].strip() if key in fields else ""
    for key in _QUESTION_LIST_FIELDS:
        record[key] = [entry for entry in _csv(fields[key]) if entry] if key in fields else []
    record["options_supplied"] = (
        _question_flag(fields["options_supplied"], "Options supplied")
        if "options_supplied" in fields else False)
    record["options"] = [
        {"key": key} for key in (_csv(fields["options"]) if "options" in fields else ())
        if key
    ]
    roots = _reading_roots(fields["reading_roots"]) if "reading_roots" in fields else {}
    if _DERIVED_ROOT in roots:
        raise QuorumSchemaInvalid(
            f"the question record states a {_DERIVED_ROOT!r} reading root; where "
            "this run's decisions projection lives is a fact about the run and "
            "not a claim the raiser makes, and a second spelling of it is the "
            "one brain 2 is sent to read while the payload cites the other")
    missing = [source for source in _DECLARED_ROOTS if source not in roots]
    if missing:
        raise QuorumSchemaInvalid(
            f"the question record states no reading root for {missing}; every "
            "source some brain is assigned to must have one, because a brain "
            "sent to an empty root reports exactly what a brain that looked and "
            "found nothing reports -- and that is the signature the rung "
            "distribution is read for")
    record["reading_roots"] = roots
    #: THE CONTENT SCREEN, run at parse time exactly as ``parse_decisions``
    #: runs it over ``decisions.md``: a rung value or a hyphenated rung name
    #: quoted anywhere the record is projected from reaches a brain through a
    #: field the payload whitelist has already approved. A HIT IS A STOP AND
    #: NEVER A STRIP -- silently editing the record would leave it and what the
    #: brains were asked disagreeing about the question.
    #:
    #: DERIVED FROM THE PROJECTION, never restated beside it. Screening a list
    #: somebody typed out is how ``challenge`` and the reading roots came to
    #: travel unscreened under a comment claiming the opposite.
    projected = _record_projection(record)
    for name in sorted(projected):
        for where, quoted in _projected_strings(projected[name], name):
            leaked = _rung_leak(quoted)
            if leaked is not None:
                raise QuorumSchemaInvalid(
                    f"the question record's {where} quotes the grounding "
                    f"ladder ({leaked}); it is projected into every brain's "
                    "payload verbatim, and a brain that knows the bar clears "
                    "the bar")
    return record


def _question_record(run_dir, qid: str) -> dict:
    """The record for one qid, read from the run and bound to its own identity.

    THE QID IS RE-DERIVED AND COMPARED. A record is addressed by the directory
    it sits in, and a directory can be copied, renamed or half-restored from a
    backup; a record whose own question and axis do not hash to the qid it is
    filed under is a question answered under another question's identity, and
    every response, digest and decision keyed by that qid would look
    well-formed.
    """
    if not _text(qid):
        raise QuorumSchemaInvalid(
            f"qid {qid!r} is not a question id; a payload keyed by nothing is a "
            "payload no response can be matched back to")
    path = _run_path(run_dir) / _QUORUM_DIRNAME / qid.strip() / _QUESTION_FILE
    #: THE SHAPE IS ASKED BEFORE THE OPEN, for ``_require_regular_file``'s
    #: reason: this read is reached from ``_open_under_lock`` through
    #: ``build_payload`` and ``payload_digest``, so it runs WITH THE RUN LOCK
    #: HELD, and a FIFO under this name answers the open by waiting for a
    #: writer that never comes -- an unattended run wedged for ever, holding
    #: the lock, with nothing in any log to say why.
    _require_regular_file(path, f"the question record for {qid}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        #: ``ValueError`` IS THE EMBEDDED NUL, and it is the spelling
        #: ``_cited_file`` and ``open_quorum`` already carry and this one did
        #: not. ``qid`` reaches here from ``payload_digest`` and
        #: ``build_payload``, both public and both taking any string a caller
        #: reassembled from a tracker cell; ``Path`` accepts ``"a\x00b"`` and
        #: ``open`` then refuses it with ``ValueError``, which is outside
        #: ``TrackerError`` and outside the ``(OSError, UnicodeError)`` a read
        #: is usually written for, so it escaped every handler a controller
        #: has written.
        raise QuorumError(
            f"no readable question record for {qid}: {exc}; a payload cannot be "
            "built from a question nobody wrote down") from exc
    record = parse_question(text)
    problems = check_admissible(record)
    if problems:
        raise QuorumSchemaInvalid(
            f"the question record for {qid} is inadmissible ({problems}); a "
            "payload built from it would dispatch brains at a question the run "
            "had already decided it may not ask")
    derived = _record_qid(record)
    if derived != qid.strip():
        raise QuorumSchemaInvalid(
            f"the question record filed under {qid} derives {derived}; a record "
            "answering under another question's identity produces responses, "
            "digests and a decision that all look well-formed and all belong to "
            "a question nobody asked")
    return record


def _run_path(run_dir) -> Path:
    """``run_dir`` as a ``Path``, with anything else refused rather than coerced.

    ``Path(5)`` raises ``TypeError``, which is outside ``TrackerError`` and so
    escapes every handler a controller has written. The run directory is the
    one argument every function in this section takes and the one most likely
    to arrive as ``None`` from a caller that lost it.
    """
    if not isinstance(run_dir, (str, Path)):
        raise QuorumError(
            f"run_dir is {type(run_dir).__name__}, not a path; coercing it "
            "would build a payload against a directory named by a repr")
    return Path(run_dir)


def _run_relative(run_dir, name: str) -> str:
    """A file inside the run, expressed the way a brain must CITE it.

    REPO-ROOT-RELATIVE, because ``effective_rung`` resolves every citation
    against the recorded repository root and refuses one that escapes it. Hand
    a brain the bare ``decisions-effective.md`` and every decision citation it
    makes resolves to ``<repo_root>/decisions-effective.md``, which does not
    exist -- and a citation that does not resolve demotes silently. Since
    ``specified`` requires a spec, intent-brief or decision anchor, the top rung
    becomes unreachable, everything lands under the floor, and the run escalates
    every question it is ever asked while looking correctly cautious.

    The root is READ BACK here, never derived. A run lives at
    ``docs/superpowers/runs/<id>/``, so the arithmetic says ``parents[3]`` --
    until a run sits somewhere else, and there is no index right for both.
    """
    path = _run_path(run_dir)
    root = Path(repo_root(validate_run(path))).resolve()
    try:
        inside = path.resolve().relative_to(root)
    except ValueError:
        raise QuorumError(
            f"run_dir {str(path)!r} is not inside the recorded repo_root "
            f"{str(root)!r}; a brain handed a path it cannot cite produces "
            "evidence that never resolves, and evidence that never resolves "
            "demotes without raising") from None
    return (inside / name).as_posix()


def _shared_payload(qid: str, run_dir) -> dict:
    """The index-INDEPENDENT half of every brain's payload.

    A WHITELIST CONSTRUCTOR. Every key it emits is named here or in
    ``_record_projection``, so the prohibited material is not filtered out --
    it is never reachable. The raiser's identity, the raiser's candidate
    answers and recommendation, the adoption floor, the drift budget, every
    rung VALUE, and any elapsed-time or cost signal have no route through this
    function. A filter can be defeated by a field somebody adds later; a
    whitelist cannot.

    The record's half is named in ``_record_projection`` rather than inline,
    and that is the point of it: the content screen ``parse_question`` runs is
    derived from the same function, so a key added to the projection is
    screened the day it starts travelling instead of the day somebody
    remembers to add it to a second list.

    Rung NAMES travel and rung VALUES do not. A brain that knows the bar clears
    the bar, so it selects a name and the controller derives the value.

    ``options`` are whitelisted while ``candidate_answers`` are excluded, and
    the distinction is load-bearing rather than fussy: the prohibition is on the
    raiser's preferred ANSWERS, and the named options are part of the QUESTION
    -- admissibility criterion 4 requires them and ``answer_key`` comparison is
    defined against them.
    """
    record = _question_record(run_dir, qid)
    #: ONE spelling of the projection's location, derived from the run.
    #: ``reading_roots`` carries it so brain 2 is sent somewhere, and
    #: ``decisions_effective`` carries it so any brain may cite it; both are
    #: this value, so they cannot disagree.
    projection = _run_relative(run_dir, _PROJECTION_FILE)
    projected = _record_projection(record)
    projected["reading_roots"][_DERIVED_ROOT] = projection
    return {
        "qid": qid.strip(),
        #: The record's half, whitelisted and screened in one place.
        **projected,
        "decisions_effective": projection,
        #: NAMES only, never values.
        "rungs": list(RUNG_ORDER),
        "response_schema": _RESPONSE_SCHEMA_DOC,
        "you_are_one_of_several": True,
    }


def _canonical(value) -> str:
    """One serialization of the payload, byte-stable across processes.

    Not JSON. This module states its own durable formats and holds no JSON
    writer; what a digest needs is not JSON but INJECTIVITY, so strings are
    length-prefixed and every type carries a tag. Two different payloads
    therefore cannot serialize to one string, which is the only property the
    digest rests on.

    Mapping keys are sorted, so a payload built twice from one record digests
    the same however the dicts were assembled.
    """
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return f"s{len(value)}:{value}"
    if isinstance(value, int):
        return f"i{value};"
    if isinstance(value, (list, tuple)):
        return "[" + "".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value)
        if any(not isinstance(key, str) for key in keys):
            raise QuorumSchemaInvalid(
                "a payload mapping is keyed by something other than a string; "
                "sorting a mixture raises out of this module's family and one "
                "key type answering for another digests two payloads alike")
        return "{" + "".join(f"{_canonical(key)}{_canonical(value[key])}"
                             for key in keys) + "}"
    raise QuorumSchemaInvalid(
        f"a payload carries {type(value).__name__}, which has no stable "
        "serialization; a digest over a repr binds the object's address")


def _digest(text: str) -> str:
    """Lowercase sha256 hex, the one spelling ``## Quorum`` will accept."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def payload_digest(qid: str, *, run_dir: str) -> str:
    """ONE digest binding all three brains' payloads.

    It covers the shared payload and the decisions projection, and that is
    sufficient rather than a shortcut: the reading assignment is a constant rule
    rather than data, and ``build_payload`` is pure with respect to the index,
    so a re-dispatch of brain n is reproducible from ``(payload_digest, n)``.
    It stops binding the moment anything about the assignment is read from the
    tracker or from run state, at which point the partial-quorum recovery path
    would silently re-send a brain a different payload than it first received.

    The projection is read from the RUN directory and cited to a brain as a
    repo-root-relative path. Those are two names for one file, and the one that
    belongs in a digest is the CONTENT: a projection whose text changed is a
    different context, and the responses on disk were answers to the old one.
    """
    projection = _run_path(run_dir) / _PROJECTION_FILE
    #: ASKED BEFORE THE OPEN, and the branch below is exactly why it has to be.
    #: A missing projection is answered with ``""`` two lines down, so without
    #: this the four names that are NOT a readable file would have to be told
    #: apart by the open itself -- and a FIFO tells nobody anything: it BLOCKS,
    #: and this read is reached from ``_open_under_lock`` with the run lock
    #: held. ``_require_regular_file`` is silent for a name that is not there,
    #: which leaves the empty-projection branch exactly as it was.
    _require_regular_file(projection, f"the decisions projection for {qid}")
    try:
        text = projection.read_text(encoding="utf-8")
    except FileNotFoundError:
        #: A run with no decisions yet has an empty projection, not a missing
        #: context. Every other read failure is a real one and is not swallowed
        #: into "there was nothing to read".
        text = ""
    except (OSError, UnicodeError) as exc:
        raise QuorumError(
            f"unreadable decisions projection for {qid}: {exc}; a digest that "
            "quietly treated it as empty would bind the responses to a context "
            "nobody saw") from exc
    return _digest(_canonical(_shared_payload(qid, run_dir)) + "\x00" + text)


def build_payload(qid: str, brain_index: int, *, run_dir: str) -> dict:
    """The exact material one brain receives: the shared payload plus its rule.

    PURE WITH RESPECT TO ``brain_index``, and pure with respect to run state
    beyond the question record, the projection and the recorded repository root.
    Nothing here consults the tracker's quorum rows, the drift budget, the clock
    or the dispatch history -- which is what makes the three payloads one digest
    apart and a re-dispatch reproducible.

    The assignment names a source and hands over its root. It is a BIAS toward a
    place to look, never a hint about an answer, and the other roots travel too:
    a brain is steered, not fenced, because a fenced brain that finds nothing
    cannot tell the difference between absence and a wall.
    """
    if (isinstance(brain_index, bool) or not isinstance(brain_index, int)
            or not 0 <= brain_index < len(READING_ASSIGNMENTS)):
        raise QuorumError(
            f"brain_index {brain_index!r} is outside the {_BRAINS}-brain quorum; "
            "a count is never reduced to fit capacity and a fourth brain is "
            "never dispatched, so there is no index here to fall back to")
    assignment = READING_ASSIGNMENTS[brain_index]
    payload = _shared_payload(qid, run_dir)
    roots = payload["reading_roots"]
    #: STATED HERE TOO, though ``parse_question`` already refuses a record that
    #: omits one. The two guards answer different questions -- "is this record
    #: complete?" against "is THIS BRAIN being sent somewhere?" -- and this is
    #: the one that stays right the day the assignment rule gains a source.
    #: The alternative spellings are both wrong in the silent direction:
    #: ``roots[source]`` raises ``KeyError``, outside ``TrackerError``, and
    #: ``roots.get(source, "")`` dispatches a brain to nowhere, which reports
    #: exactly what a brain that looked and found nothing reports.
    unstated = [source for source in assignment["read"]
                if not _text(roots.get(source))]
    if unstated:
        raise QuorumError(
            f"brain {brain_index} is assigned to {unstated}, which this "
            "question states no reading root for; a brain sent nowhere reports "
            "the same empty hands as a brain that looked and found nothing, "
            "and that is the signature the rung distribution is read for")
    payload["reading_assignment"] = {
        "label": assignment["label"],
        "read": [{"source": source, "root": roots[source]}
                 for source in assignment["read"]],
    }
    return payload


# --- the drift budget ------------------------------------------------------

#: The audit trail and the two quorum files this section reads and writes.
#: ``decisions.md`` is markdown and stays markdown -- it is durable state a
#: human edits. ``final.json`` and ``extensions.json`` are JSON because the
#: phase layout says so and because what they hold is typed and nested: a
#: finalised outcome carries a winner object, and a pinned grant carries a
#: LIST of decision ids that would have to be re-escaped to survive ``_csv``.
_DECISIONS_FILE = "decisions.md"
_FINAL_FILE = "final.json"
_EXTENSIONS_FILE = "extensions.json"

#: Every status a finalised quorum may carry, and the whole of them. ALL FIVE
#: are writable into a ``## Quorum`` row's ``Outcome`` cell, and that is a
#: RESOLVED seam rather than a coincidence: ``_QuorumOutcome`` admitted only
#: ``adopted``, ``escalated`` and ``rejected-<reason>`` until the row writer
#: needed to record a question the quorum could not decide, and the word was
#: added to THAT grammar -- see ``_UNDECIDABLE`` -- rather than coerced here.
#: The suite pins the two sets against each other, so neither side can drift
#: without the seam going red.
_FINAL_STATUSES = frozenset({
    "adopted", "escalated", "rejected-contradicts-human",
    "rejected-contradicts-quorum", _UNDECIDABLE,
})

#: THE ONE STATUS THAT CHARGES THE BUDGET. Escalations never count -- an
#: escalation is the run asking for help, and charging for it teaches the
#: controller to stop asking, which is the exact opposite of the design's
#: intent. Rejections do not count either: a rejected quorum adopted nothing,
#: so there is no decision authority to have spent. Named once, so a counter
#: incremented on finalisation rather than on adoption has no spelling here.
_CHARGED_STATUS = "adopted"

#: The action that extends THE DRIFT BUDGET, and only it.
#: ``dispatch.extend-budget`` is the other member of ``_EXTENSION_ACTIONS`` and
#: it is deliberately absent: two budgets mean two authorities, the drift budget
#: caps decision authority and the dispatch budget caps run cost, and a grant
#: against either refilling the other is the one thing the two-action split
#: exists to prevent. This is the mirror image of the mistake Task 5 found --
#: there a check that named only the quorum action was too NARROW, because it
#: was asking "is this record a grant?"; here the same name is the whole
#: question, because this one asks "does this grant refill THIS budget?".
_DRIFT_EXTENSION_ACTION = "quorum.extend-budget"

#: The four fields the spec requires of a budget grant, verbatim.
_GRANT_FIELDS = ("authorized_run", "source_revision", "authorized_through",
                 "granted_against")

#: What a PINNED grant carries, and the whole of it. A pin is re-read on every
#: budget check and never re-derived, so it is validated as strictly as the
#: record it came from: a hand-edited ``extensions.json`` is otherwise the one
#: route by which a run grants itself authority nobody signed.
_PINNED_GRANT_KEYS = ("decision_id", "phase", "authorized_through",
                      "granted_against")


def _loads(text, what: str):
    """``json.loads``, with every escape re-raised inside ``TrackerError``.

    ``JSONDecodeError`` is a ``ValueError`` and ``ValueError`` is outside this
    module's exception family, so an unwrapped parse escapes every ``except
    TrackerError`` a controller has written and kills the run on a malformed
    file -- which is input, not a bug. ``RecursionError`` is here for the same
    reason and is not theoretical: ``json`` parses nesting recursively, so a few
    thousand open brackets in an agent-authored file raise it, and it is not a
    ``ValueError``. ``TypeError`` covers a caller that hands this bytes.

    This wrapper is the whole of the condition on which ``json`` entered
    ``ALLOWED_IMPORTS``.
    """
    try:
        return json.loads(text)
    except (ValueError, TypeError, RecursionError) as exc:
        raise QuorumSchemaInvalid(
            f"{what} is not readable JSON ({type(exc).__name__}: {exc}); a "
            "malformed record is input and stops the run inside this module's "
            "exception family, never outside it") from exc


def _require_regular_file(path: Path, what: str) -> None:
    """The blocking half of ``_decisions_text``'s split, spelled once.

    THE OPEN IS THE HAZARD, not the bytes. ``is_file()`` is false for a
    DIRECTORY, for a dangling symlink, for a symlink LOOP and for a FIFO, and
    the first three fail an open loudly and promptly. A FIFO does not: opening
    one for reading BLOCKS until a writer arrives, and on a name inside a run
    directory no writer is ever coming. Every reader below runs under the run
    lock or inside a critical section that holds it, so that open does not fail
    the run -- it hangs the run, holding the lock, with no diagnostic and no
    timeout, and an unattended pipeline stops dead.

    So the shape is asked BEFORE the open rather than discovered by it, and a
    name that exists and is not a regular file is corruption -- never absence.
    ``stat`` on a FIFO returns immediately; only ``open`` waits.

    ABSENCE IS DELIBERATELY NOT ANSWERED HERE. Every caller has already decided
    what a missing name means for it -- "never opened", "not finalised", "this
    brain has not answered" -- and those three are not one state. A name that
    is not there falls through to the caller's own read, which reports it as
    the caller has always reported it.

    ``QuorumSchemaInvalid`` RATHER THAN A BARE ``QuorumError``, and the class is
    load-bearing rather than decorative: "was never opened" is a plain
    ``QuorumError`` too, so a caller -- and a test -- that could only see the
    family could not tell a quorum nobody dispatched from a quorum whose record
    is a directory. Corruption is what this is, and corruption is what it says.

    ``is_file()`` ITSELF RAISES, which is why the call below is wrapped rather
    than written bare -- and it is the reason this split lives HERE rather than
    at whichever call site happens to notice. CPython swallows only
    ``pathlib._IGNORED_ERRNOS``, measured on this interpreter as
    ``(ENOENT, ENOTDIR, EBADF, ELOOP)``, and re-raises every other ``OSError``.
    Two reachable inputs land outside that set with no permissions trick
    between them: a name longer than ``NAME_MAX`` -- measured, a 312-character
    reference, ``ENAMETOOLONG`` -- and a name under a directory this run may not
    search -- measured, a parent at mode ``000``, ``EACCES``. Both escaped this
    function raw, so every call site it then had inherited the escape; a local
    ``except OSError`` at the one that found it would have been a rule scoped
    to where it was learned, and the others would have stayed open.
    THE CALLERS ARE ENUMERATED FROM THIS MODULE'S AST RATHER THAN REMEMBERED,
    and they are named here rather than counted, because a count moves with the
    module and a stale count reads as a checked one:
    ``_question_record``, ``payload_digest``, ``_read_json``,
    ``_response_record``, ``_plan_text``, ``resolve_evidence``, ``_ref_text``,
    ``_published_result_bytes``, ``_resolve_question_record``,
    ``_require_artifact_outputs`` and ``_result_candidates``. The authority is
    ``test_every_door_caller_is_enumerated_and_none_escapes_on_a_nul``, which
    derives the set from the syntax tree; this list is its copy. Every caller
    added after the wrap inherited it without knowing it existed, which is the
    argument for wrapping the door rather than the call site. Five callers
    (``_plan_text``, ``resolve_evidence``, ``_ref_text``,
    ``_resolve_question_record``, ``_require_artifact_outputs``) catch the
    refusal and re-raise it as another ``TrackerError``; ``_result_candidates``
    is the only one that catches it and does NOT re-raise, turning it into a
    diagnostic; the rest let it propagate.

    A NUL BYTE IS SCREENED RATHER THAN CAUGHT, and the difference is measured
    rather than assumed. ``os.stat('\x00x')`` raises ``ValueError`` -- not an
    ``OSError``, so the arm below would not have caught it anyway -- but
    ``pathlib`` SWALLOWS that ``ValueError`` itself: measured on this
    interpreter, ``Path('\x00x')`` answers ``False`` to ``is_file``,
    ``is_dir``, ``exists``, ``is_symlink`` and ``is_fifo``, and
    ``os.path.lexists`` -- this door's own fall-through two lines down --
    answers ``False`` too. So an ``except ValueError`` here would be an
    UNREACHABLE screen of exactly the kind this module reverted at
    ``_git_store``, and the door instead asks the question it can actually
    answer: is this a name the filesystem could even be asked about.

    Without the screen the door said "nothing is here" for a name it had not
    examined at all, and the caller's own read then raised the bare
    ``ValueError`` OUTSIDE this module's exception family -- measured on
    ``_read_json`` and ``payload_digest``. The standing rule names THIS
    function as the place a NUL is refused, and it is refused here rather than
    at every call site enumerated above, for the reason given there.

    THE SPLIT IS THE READ ARM'S SPLIT, SPELLED ONE LEVEL EARLIER.
    ``FileNotFoundError`` and ``NotADirectoryError`` are the two spellings of
    "not there" and fall through silently, exactly as a ``False`` from
    ``is_file()`` on a name that does not exist already does -- so the callers
    that answer absence themselves keep answering it. Every other ``OSError``
    is a name this run cannot establish anything about, and an unestablished
    name is never reported as an absent one. ``ENAMETOOLONG`` is arguably
    absence -- a name past ``NAME_MAX`` cannot exist -- and is deliberately NOT
    special-cased: this module does not guess at the meaning of an errno, and
    the conservative direction is a stop that names the name rather than a
    silent fall-through to some other root.

    THE ABSENCE ARM IS UNREACHABLE BY CONSTRUCTION AND STAYS ANYWAY, and it is
    the one screen in this file that mutation proved equivalent and that is
    kept. "By construction" corrects an earlier reading of this paragraph,
    which called it unreachable "on this interpreter" and so invited the next
    reader to look for a platform where it fires. There is none. CPython
    SELECTS the two classes this arm catches FROM the two errnos
    ``_IGNORED_ERRNOS`` swallows -- ENOENT gives ``FileNotFoundError``, ENOTDIR
    gives ``NotADirectoryError``, and every other errno ``os.stat`` can report
    here gives a class this arm does not name -- so any ``FileNotFoundError``
    or ``NotADirectoryError`` ``stat`` can raise is already one ``is_file()``
    answers ``False`` for. That containment holds on every platform, Windows
    included, where the ``winerror`` is translated to an errno before the
    subclass is chosen. The arm is dead against the whole of ``os``, not
    against one constant's current contents.

    THE DISTINCTION FROM THE SCREENS THIS CODEC DELETED IS STILL REAL, which is
    why an unreachable arm is kept here and two were removed there. ``_table_safe``
    on ``purpose`` and on ``outcome`` were dominated by a total check on the
    line below them, IN THIS FILE, permanently; nothing about this module could
    ever make them fire. This arm is dominated by a relation between two things
    in the standard library, and both can move. Measured over
    ``test_task_lifecycle.py``'s 536 tests, with ``_IGNORED_ERRNOS`` simulated
    NARROW (only EBADF and ELOOP, the direction that makes the arm live): 3
    loud failures with the arm, 41 without. The 38 in between are one outcome
    with one shape -- every absent file under a run directory becoming
    corruption at every call site the door then had, at once -- which is the fail-open this
    door exists to refuse, arriving by the one route the door cannot see. The
    arm does not make the module correct under a narrowing (a dangling symlink
    stops being corruption and becomes absence, which is wrong in the other
    direction, and fails loudly); it bounds the blast radius to something a
    reader can diagnose.

    AND THE LIKELIER DIRECTION IS THE OTHER ONE, which the first version of
    this paragraph did not consider: if the ignore set WIDENS -- an existence
    predicate rewritten to swallow more -- the arm is irrelevant and the C1
    inputs silently revert to being folded into absence. Measured, with every
    errno 1..199 ignored: 4 loud failures, arm or no arm, from
    ``test_a_name_the_door_cannot_examine_stays_inside_the_family`` and
    ``test_the_door_itself_keeps_every_caller_inside_the_family``. That future
    is already pinned, by tests rather than by this arm.

    THE ARM'S OWN TEST IS
    ``test_the_doors_absence_arm_fires_if_the_stdlib_stops_swallowing``, which
    narrows the ignore set and asserts the door still falls through. Delete the
    arm and it fails; it is the only test that does. The sentence this replaces
    named ``test_a_name_that_is_not_there_is_still_answered_by_falling_through``
    as the guarantee, and that test cannot be it: it drives REAL absence,
    ``is_file()`` answers ``False``, the arm is never entered, and the test
    passes with the arm deleted. Naming a test that cannot fail for the arm's
    reason is how an equivalent mutant acquires a defence nobody ran.
    """
    if _NUL in str(path):
        raise QuorumSchemaInvalid(
            f"{what} at {str(path)!r} carries a NUL byte, which is a name no "
            "syscall will accept and which every existence predicate answers "
            "False for WITHOUT asking the filesystem anything; reported as "
            "absent it would fall through to the caller's own read, and that "
            "read raises a bare ValueError outside this module's exception "
            "family -- measured on _read_json and payload_digest")
    try:
        regular = path.is_file()
    except (FileNotFoundError, NotADirectoryError):
        return
    except OSError as exc:
        raise QuorumSchemaInvalid(
            f"{what} at {str(path)!r} is a name this run cannot examine "
            f"({type(exc).__name__} errno {exc.errno}: {exc}); asking its "
            "shape failed, so nothing is known about it -- and a name nothing "
            "is known about is not a name known to be absent, which is the "
            "only answer this door lets fall through") from exc
    if not regular and os.path.lexists(path):
        raise QuorumSchemaInvalid(
            f"{what} at {str(path)!r} is a name this run directory carries and "
            "cannot be read; a directory, a dangling link, a symlink loop or a "
            "FIFO is corruption and never an absent record -- and the FIFO is "
            "why the shape is asked before the open rather than by it, because "
            "that open blocks under the run lock until a writer that never "
            "comes")


def _read_json(path: Path, what: str):
    """One JSON file from the run, read and parsed, or a stop that names it."""
    _require_regular_file(path, what)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise QuorumError(
            f"unreadable {what} at {str(path)!r}: {exc}") from exc
    return _loads(text, what)


def _dumps(value) -> str:
    """The one spelling this module writes JSON in: sorted, indented, newline.

    Sorted keys so a file rewritten from equal content is byte-identical, which
    is what lets the pin writer below skip a write instead of churning the
    directory on every budget check.

    ``allow_nan=False``, which is NOT the default and is the whole reason this
    call is spelled out. Python's ``json`` emits ``NaN``, ``Infinity`` and
    ``-Infinity`` as bare tokens; RFC 8259 has no such literals, so a record
    holding one is a file only Python can read back. That was tolerable while
    this module serialized only records it had built itself, and it stopped
    being tolerable when ARBITRARY AGENT-SUPPLIED CONTENT started passing
    through here as a brain's ``response``: the immutable record is the audit
    trail a human reads, and a trail a human's ``jq`` cannot open is a weaker
    one. ``ValueError`` is what refuses it, which is already caught below, so
    the refusal lands inside this module's exception family and -- at the one
    caller that matters -- ahead of the attempt being counted.
    """
    try:
        return json.dumps(value, indent=2, sort_keys=True,
                          allow_nan=False) + "\n"
    except (TypeError, ValueError) as exc:
        raise QuorumError(
            f"a record carries {type(exc).__name__}-unserializable content and "
            "cannot be written") from exc


def _final_event(path: Path, qid: str) -> tuple[dict, dict]:
    """One ``final.json``, validated down to the three fields the budget reads.

    RETURNS THE EVENT AND THE RECORD IT WAS PROJECTED OUT OF, FROM ONE READ,
    and the pair is why the signature is a tuple rather than the event alone.
    Two callers want both halves -- ``classify_quorum`` reports the ``status``
    and ``decision_id`` this validated beside the whole ``result`` the caller
    is told not to re-litigate, and ``_open_under_lock`` hands back the same
    record as a ``replay``. Each of them used to read the file a SECOND time
    for the record, which means the fields the verdict was validated against
    and the fields it hands over came from two different reads of a name a
    human may be editing or restoring: the verdict could report ``adopted``
    about bytes that no longer say so, or an outcome could be handed back under
    a qid the second read no longer agrees with. One read, one record, one
    verdict about it.

    THE QID IS RE-DERIVED FROM THE DIRECTORY AND COMPARED, for the reason
    ``_question_record`` compares it: a record is addressed by the directory it
    sits in, and a directory can be copied, renamed or half-restored. A final
    record filed under another question's qid would be counted against that
    question's budget and cited in that question's audit trail.

    ``status`` is tested with ``_member`` and NOT behind a ``_text`` guard, and
    the order is the point. ``status`` arrives from a JSON file an agent wrote,
    so it may legally be a list or an object; ``["adopted"] in _FINAL_STATUSES``
    raises ``TypeError``, which is outside ``TrackerError``. A ``_text`` check
    in front of it would make the membership test unreachable for exactly the
    values that need it, and the pin below would pass against a bare ``in``.

    An ``adopted`` event MUST name its decision record, AND MUST NAME ITS OWN.
    Dropping an adoption with no id out of the adopted list while still charging
    it to the budget puts an adoption in the count that is missing from the list
    a human is shown and signs against -- the anti-reflex mechanism reporting a
    set the run does not hold. Letting it name SOME OTHER record is the same
    fault from the other side: ``H-900`` in an adopted record's ``decision_id``
    puts the human's own grant into the set their ``Granted against`` is checked
    against, so the grant is required to have been signed against itself.
    """
    record = _read_json(path, f"the final record for {qid}")
    if not isinstance(record, dict):
        raise QuorumSchemaInvalid(
            f"the final record for {qid} is a "
            f"{type(record).__name__}, not an object; a finalised quorum is a "
            "record with a status in it and a bare value classifies nothing")
    stated = record.get("qid")
    if not _text(stated) or stated.strip() != qid:
        raise QuorumSchemaInvalid(
            f"the final record filed under {qid} states qid {stated!r}; a "
            "record answering under another question's identity is counted "
            "against that question's budget and cited in its audit trail")
    status = record.get("status")
    if not _member(status, _FINAL_STATUSES):
        raise QuorumSchemaInvalid(
            f"{qid}: final status {status!r} is not one of "
            f"{sorted(_FINAL_STATUSES)}; an unrecognised status is neither an "
            "adoption nor an escalation, so the budget cannot say whether it "
            "was charged")
    phase = record.get("phase")
    if not _text(phase) or not _TOKEN.fullmatch(phase.strip()):
        raise QuorumSchemaInvalid(
            f"{qid}: final phase {phase!r} is not one token; the per-phase "
            "budget groups by it, and an event that groups with nothing is an "
            "adoption charged to no phase at all")
    decision_id = record.get("decision_id")
    named = _text(decision_id) and _id_provenance(decision_id.strip()) is not None
    if status == _CHARGED_STATUS and not named:
        raise QuorumSchemaInvalid(
            f"{qid}: an adopted quorum states decision_id {decision_id!r}, "
            "which is not a decision id; the adopted list a human is shown "
            "before granting an extension is built from these, so an adoption "
            "missing from it is one they were never shown")
    if status == _CHARGED_STATUS and decision_id.strip() != _QUORUM_PREFIX + qid:
        #: RE-DERIVED FROM THE DIRECTORY AND COMPARED, exactly as the qid above
        #: is, and for a sharper reason. ``_id_provenance`` is satisfied by any
        #: well-formed id, so without this an adoption may name ANOTHER
        #: quorum's decision -- or a HUMAN's. The adopted list is what a budget
        #: grant's ``Granted against`` is checked against, so an adoption
        #: claiming ``H-900`` puts the grant's own id into the set the human
        #: must be on record as having been shown: they are required to have
        #: signed against their own grant, which no honest record can satisfy,
        #: and the run stops with an extension it can never spend.
        raise QuorumSchemaInvalid(
            f"{qid}: an adopted quorum states decision_id {decision_id!r} and "
            f"an adoption writes {_QUORUM_PREFIX + qid}; a record naming "
            "another decision puts that decision into the adopted set a human "
            "is shown, and signs them against something this quorum never "
            "decided")
    if decision_id is not None and not named:
        raise QuorumSchemaInvalid(
            f"{qid}: decision_id {decision_id!r} is neither null nor a decision "
            "id (H-<n> or Q-<qid>); a record naming an id the audit trail "
            "cannot hold is a citation nothing can resolve")
    return {
        "qid": qid,
        "status": status,
        "phase": phase.strip(),
        "decision_id": decision_id.strip() if named else None,
    }, record


def quorum_events(run_dir: str) -> list[dict]:
    """Every FINALISED quorum in this run, ordered by qid, AS THE BUDGET SEES IT.

    A BUDGET PROJECTION AND NOT THE RECORD. Four keys come back -- ``qid``,
    ``status``, ``phase``, ``decision_id`` -- and they are exactly the cells the
    two ceilings are computed from: what charges, which phase it charges, and
    which decision record the human is shown before they are asked to raise the
    ceiling. Every one of them is validated here, which is the same statement:
    this function screens everything it projects, and a field it returned
    unscreened would be a field the totality sweep over its reads does not
    cover.

    WHOEVER WRITES THE ``## Quorum`` ROW READS THE REST, and that is not this
    function widened. ``section_columns("quorum")`` is twelve cells and eight of
    them -- ``axis``, ``state``, ``owners``, ``payload_digest``,
    ``context_digest``, ``responses``, ``depth``, and the row's own state
    machine -- are not in ``final.json`` at all: they belong to the question
    record and to the dispatch that carried it. So ``quorum_tracker_rows``, the
    row writer P03 still owes, needs a second source whatever this returns, and
    widening this reader would buy it four cells it already has while making the
    budget's screening claim cover fields the budget has no stake in. What that
    writer must NOT do is open the file itself: ``_read_json`` and ``_loads``
    are the one door, and the suite asserts ``_loads`` is the module's only
    caller of ``json``, so a second reader that grew its own ``json.loads``
    would be a second way out of this module's exception family.

    Derived from the ``final.json`` files rather than from a separate log, so
    there is one place a record can exist and no way for a counter to disagree
    with the evidence. A counter is the thing an autonomous controller is most
    motivated to be wrong about in its own favour, and a counter kept beside the
    files it counts can be edited without touching any of them.

    Rejections are events too: a run with several ``rejected-contradicts-*``
    events is a run whose brains keep pulling away from what the user asked for,
    and that count is the earliest drift warning available. They do not charge
    the budget -- a rejected quorum adopted nothing -- but they are recorded.

    A qid directory with no ``final.json`` is in flight, not broken, and is
    skipped. Every other read failure raises.
    """
    root = _run_path(run_dir) / _QUORUM_DIRNAME
    if not root.is_dir():
        #: A run that has never opened a quorum has no budget spent, which is
        #: not the same as a run whose records are unreadable. Only the absence
        #: of the whole tree is treated as "nothing yet".
        return []
    events = []
    seen: dict = {}
    for final in sorted(root.glob("*/" + _FINAL_FILE)):
        #: NOT GUARDED BY ``is_file``. A qid directory with no ``final.json``
        #: is in flight and this glob never yields it, so the only thing such a
        #: guard could skip is a ``final.json`` that is a DIRECTORY -- which is
        #: corruption, not an undecided quorum, and is a stop rather than a
        #: record silently missing from the run's own count of itself.
        event, _ = _final_event(final, final.parent.name)
        did = event["decision_id"]
        if did is not None:
            if did in seen:
                #: STILL REACHABLE, and by a narrower route than it once was.
                #: ``_final_event`` now makes an adopted record name its OWN
                #: ``Q-<qid>``, and a qid is the directory name, so two
                #: ADOPTIONS can no longer collide here. What still can is a
                #: record that adopted nothing citing a decision some other
                #: quorum wrote -- an escalation or a rejection pointing at an
                #: adoption's record, which would charge one decision to the
                #: budget and then cite it again from a quorum that bought no
                #: authority at all.
                raise QuorumSchemaInvalid(
                    f"{event['qid']} and {seen[did]} both record decision "
                    f"{did}; one decision record belongs to one quorum, and two "
                    "quorums claiming it report one grant of authority twice")
            seen[did] = event["qid"]
        events.append(event)
    return events


def _pinned_grant(entry, where: str, *, phases: frozenset) -> dict:
    """One entry of ``extensions.json``, validated as strictly as its record.

    A PIN IS NEVER RE-DERIVED, which is the whole of why it is re-validated:
    once a grant is pinned this function's output is the authority, and a
    hand-edited or half-written ``extensions.json`` is otherwise the one route
    by which a run hands itself a ceiling nobody signed.

    Human ids only. A pinned ``Q-`` grant is a quorum that extended its own
    budget, which is the move ``parse_decisions`` refuses at the record and
    which must not become reachable by writing the pin directly.
    """
    if not isinstance(entry, dict):
        raise QuorumSchemaInvalid(
            f"{where} is a {type(entry).__name__}, not a grant object")
    missing = [key for key in _PINNED_GRANT_KEYS if key not in entry]
    if missing:
        raise QuorumSchemaInvalid(
            f"{where} is missing {missing}; a pin the run reads instead of the "
            "record has to carry everything the record was checked for")
    extra = sorted(set(entry) - set(_PINNED_GRANT_KEYS))
    if extra:
        raise QuorumSchemaInvalid(
            f"{where} carries unknown keys {extra}; a pin is written by this "
            "module and a field it does not write is a field somebody added")
    did = entry["decision_id"]
    if not _text(did) or _id_provenance(did.strip()) != "human":
        raise QuorumSchemaInvalid(
            f"{where}: decision_id {did!r} is not a human decision id; a budget "
            "a quorum can extend is not a budget")
    phase = entry["phase"]
    #: HELD TO THE RUN'S PHASE REGISTRY, not merely to the token grammar, for
    #: the reason ``_live_grant`` is: a pin is never re-derived, so a pin whose
    #: phase is no phase of this run is a grant that raises NO ceiling and
    #: still counts against ``MAX_EXTENSIONS`` -- the same defect as the record
    #: it was written from, reachable by one hand edit of this file.
    #:
    #: SCREENED BY ``_member`` AND NOT BEHIND A ``_text`` GUARD, which is rule
    #: 9 at the site where it bites: this value comes out of JSON, so
    #: ``["P04"] in phases`` is a ``TypeError`` that escapes the exception
    #: family, and a guard in front of the membership test would make it
    #: unreachable for exactly the values that need it.
    if not _member(phase, phases):
        raise QuorumSchemaInvalid(
            f"{where}: phase {phase!r} is no phase of this run "
            f"{sorted(phases)}; a grant scoped to nothing raises no phase "
            "ceiling and is authority spent on nothing")
    through = entry["authorized_through"]
    #: THE ``bool`` CONJUNCT CANNOT BE PINNED BY A TEST, and saying so is
    #: cheaper than the next reader re-deriving it. ``True`` and ``False`` ARE
    #: ``int``s -- 1 and 0 -- so with this conjunct removed both fall through to
    #: the ceiling comparison below and are refused there anyway, and no input
    #: distinguishes the two spellings by VERDICT. What it changes is the
    #: diagnostic (a ``bool`` is not a ceiling stated badly, it is not a ceiling)
    #: and what it guards is the constant: were ``BUDGET_PER_PHASE`` ever 0,
    #: ``True`` would be 1, would exceed it, and a pin carrying ``true`` would
    #: become a ceiling of one. Belt and braces, deliberately, and kept.
    if isinstance(through, bool) or not isinstance(through, int):
        raise QuorumSchemaInvalid(
            f"{where}: authorized_through {through!r} is not a whole number; a "
            "ceiling that is not finite is the 'unlimited' grant the spec "
            "refuses, wearing another type")
    if through <= BUDGET_PER_PHASE:
        raise QuorumSchemaInvalid(
            f"{where}: authorized_through {through} does not exceed the "
            "standing per-phase ceiling; a grant that grants nothing still "
            "consumes one of the run's two extensions")
    shown = entry["granted_against"]
    if not isinstance(shown, list):
        raise QuorumSchemaInvalid(
            f"{where}: granted_against is a {type(shown).__name__}, not a list "
            "of the decision ids the human was shown")
    ids = []
    for item in shown:
        if not _text(item) or _id_provenance(item.strip()) is None:
            raise QuorumSchemaInvalid(
                f"{where}: granted_against holds {item!r}, which is not a "
                "decision id; the anti-reflex mechanism is the list of records "
                "the human is on record as having seen")
        ids.append(item.strip())
    #: ``phase`` is NOT stripped, and that is the membership test's doing: a
    #: registered phase id carries no surrounding whitespace, so `` P04 `` is
    #: refused above rather than quietly repaired into a phase nobody wrote.
    return {"decision_id": did.strip(), "phase": phase,
            "authorized_through": through, "granted_against": ids}


def _live_grant(did: str, record: dict, *, run_id: str, revision: int,
                adopted_ids: list, phases: frozenset) -> dict:
    """One ``quorum.extend-budget`` record, checked once before it is pinned.

    ``Granted against`` IS THE ANTI-REFLEX MECHANISM and is why this is checked
    against the run's own evidence rather than merely parsed: the human is on
    record as having seen the specific decisions they are waving through, so a
    bare "continue" cannot become an extension. Compared as SORTED SETS rather
    than verbatim order -- the order of a set of ids carries no information, a
    human retyping them in another order is not a reflex, and duplicates are
    refused by ``_decision_anchors`` before the comparison.

    ``Source revision`` IS BOUNDED, NOT EQUATED, and that is a deliberate
    departure from the pipeline contract this borrows. There the field is
    compared with ``==`` against the current revision, because the grant is
    consumed at the single transition it authorizes. Here it is pinned and then
    read on every budget check, and the tracker's revision advances every time
    anything is written -- appending the escalation row that carried the
    question to the human is enough -- so equality would brick the run on the
    ordinary flow it exists to unblock. What it still catches is the grant
    citing a revision this run has never reached, which is authority dated into
    the future.
    """
    for field in _GRANT_FIELDS:
        if not record.get(field, "").strip():
            raise TrackerValidationError(
                f"{did}: {_DRIFT_EXTENSION_ACTION} requires {field}; the field "
                "discipline is what makes a grant specific, and a grant missing "
                "one of them is a generic authority")
    scope = record.get("scope", "").strip()
    #: CHECKED AGAINST THE RUN'S PHASES, not against the token grammar, and
    #: this is the one place in the budget where the registry is available and
    #: populated. ``_TOKEN`` admits ``p04``, ``T04`` and ``banana``: each is a
    #: plausible human spelling, each raises NO phase ceiling, and each still
    #: burns one of the run's two extensions -- authority spent on nothing, by
    #: a check whose own message already says so.
    #:
    #: WHY THE REGISTRY IS POPULATED HERE AND NOT AT THE ``phase`` ARGUMENT.
    #: ``## Phases`` is empty on a freshly initialised run, which is why
    #: ``quorum_budget`` holds its argument to the grammar alone. A GRANT is a
    #: different moment: it exists only after some phase has exhausted its
    #: three adoptions, so that phase has been executing, and the phase set is
    #: written by a stage-06 transition and sealed at its close -- every phase
    #: this module will ever see is registered before the first phase-scoped
    #: question is raised. The same check is spelled twice already, against
    #: ``tracker["phases"]`` for a quorum row's phase and against the run's
    #: tasks, phases and gates for a fix round's scope; this is the third
    #: reader of the same roster, not a third grammar.
    if not _member(scope, phases):
        raise TrackerValidationError(
            f"{did}: Scope {scope!r} is no phase of this run {sorted(phases)}; "
            "a grant names the phase whose ceiling it raises, and one scoped "
            "to nothing raises no ceiling while still consuming an extension")
    if record["authorized_run"].strip() != run_id:
        raise TrackerValidationError(
            f"{did}: Authorized run is {record['authorized_run'].strip()!r} and "
            f"this run is {run_id!r}; a grant signed for another run is "
            "authority borrowed from a conversation this run's human never had")
    source_revision = record["source_revision"].strip()
    if not _is_count(source_revision):
        raise TrackerValidationError(
            f"{did}: Source revision {source_revision!r} is not a tracker "
            "revision in ASCII digits")
    if int(source_revision) > revision:
        raise TrackerValidationError(
            f"{did}: Source revision {source_revision} is ahead of this run's "
            f"revision {revision}; a grant cannot have been written against a "
            "state the run has never been in")
    through_raw = record["authorized_through"].strip()
    if not _is_count(through_raw):
        raise TrackerValidationError(
            f"{did}: Authorized through {through_raw!r} is not a finite ceiling "
            "in ASCII digits; 'unlimited' is the one answer this field may "
            "never carry, because a budget that refills on request is a speed "
            "bump")
    through = int(through_raw)
    if through <= BUDGET_PER_PHASE:
        raise TrackerValidationError(
            f"{did}: Authorized through {through} does not exceed the standing "
            f"per-phase ceiling of {BUDGET_PER_PHASE}; a grant that grants "
            "nothing still consumes one of the run's two extensions")
    shown = sorted(_decision_anchors(record["granted_against"], did))
    if shown != sorted(adopted_ids):
        raise TrackerValidationError(
            f"{did}: Granted against names {shown} and this run has adopted "
            f"{sorted(adopted_ids)}; the grant records which decisions the human "
            "was shown before waving them through, so a list that is not the "
            "adopted set is a human on record as having reviewed something else")
    return {"decision_id": did, "phase": scope, "authorized_through": through,
            "granted_against": shown}


def _pin_extensions(path: Path, grants: list) -> None:
    """Write the pins ATOMICALLY, and only when they would change.

    ``quorum_budget`` is checked before every dispatch, so an unconditional
    write would rewrite this file on every question the run ever raises. The
    content is canonically ordered, so "would change" is a byte comparison.

    WRITTEN THROUGH A TEMP SIBLING AND ``os.replace``, for the reason
    ``_replace_tracker`` is, and the reason is sharper here than durability.
    ``Path.write_text`` opens with ``O_TRUNC``, so a process killed between the
    truncate and the write leaves a ZERO-BYTE pin -- and a zero-byte pin is not
    a lost ceiling that the next check re-derives. It parses as nothing, so
    every later budget check stops; and DELETING it does not recover the run,
    because once one further adoption has landed the grant behind it no longer
    names the adopted set it was signed against, and ``_live_grant`` can never
    re-derive it. One interrupt in that window strands the run with a human
    grant on record that can never be honoured, and state that cannot be
    classified from disk alone is the one thing the interruption model refuses.
    ``os.replace`` has no such window: the pin on disk is either the whole of
    the old content or the whole of the new.

    THE FILE IS SYNCED AND THE DIRECTORY IS NOT, which is deliberate and is not
    the tracker's rule. Syncing the bytes before the rename is what stops the
    crash from publishing a name that points at nothing -- the failure above,
    rebuilt out of a buffer. Syncing the directory would add the tracker's
    third outcome, "the write MAY have happened", and there is nothing here for
    that outcome to mean: a rename lost by a crash leaves the PREVIOUS pin, or
    no pin, and both are states this reader already handles by re-deriving.

    CORRECTING A GRANT COSTS BOTH EXTENSIONS, and that follows from the pin
    rather than from a bug. An axis holds at most one Adopted decision, so the
    only way to restate a grant -- a mistyped ``Authorized through``, a
    ``Scope`` naming the wrong phase -- is to supersede it; and a pinned grant
    counts even after the record behind it is superseded, deliberately, so that
    a later adoption cannot retire a ceiling the run has already spent against.
    The two together mean a human who corrects one typo has spent both of the
    run's two extensions and the budget is then terminal. That is the safe
    direction for the rule to fail in, and it is a trap for whoever signs the
    grant, so it is not a defect to be fixed here but guidance P07 owes its
    template: ``Authorized through`` and ``Scope`` get one draft each.
    """
    if not grants:
        return
    content = _dumps(grants)
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == content:
                return
        except (OSError, UnicodeError):
            #: Unreadable is not equal. The write below replaces it and
            #: surfaces the real failure if the directory itself is the problem.
            pass
    descriptor = -1
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        #: ``O_EXCL``: the open either creates this name or fails, so no file
        #: belonging to another writer is ever opened, truncated or unlinked.
        candidate = path.parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
        descriptor = os.open(
            candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, TRACKER_MODE)
        #: Assigned only AFTER the open succeeds, so the cleanup below never
        #: removes a file this call did not create.
        temporary = str(candidate)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            #: The handle owns the descriptor from here.
            descriptor = -1
            handle.write(content)
            _sync_file(handle)
        os.replace(temporary, path)
        #: The name IS the pin now, so this call no longer owns anything to
        #: clean up.
        temporary = None
    except (OSError, UnicodeError) as exc:
        raise TrackerWriteError(
            f"cannot pin budget extensions to {str(path)!r}: {exc}; an unpinned "
            "grant is re-checked against a moving adopted set and stops the run "
            "the first time it moves") from exc
    finally:
        #: In ``finally`` rather than in the ``except`` for ``_replace_tracker``'s
        #: reason: what ESCAPES is a write outcome only for the two families
        #: named above, but what gets CLEANED UP is every one of them, because
        #: nothing else ever removes this file and a stranded temp beside the
        #: pin is indistinguishable from one a live writer is holding.
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


def _decisions_text(run_dir: Path) -> str:
    """``decisions.md`` as text, or ``""`` where the run has decided nothing.

    ONE DOOR ONTO THE AUDIT TRAIL, for the reason ``_loads`` is the one door
    onto ``json``. Three callers read this file for three different reasons --
    the budget reads it for grants, the projection reads it for what a brain
    may see, and ``open_quorum`` digests it as the context a quorum was opened
    against -- and a second reader that spelled "there is no file yet"
    differently would let those three disagree about whether the run has
    decided anything.

    A MISSING FILE AND AN EMPTY ONE ARE ONE STATE and that is deliberate: a run
    that has decided nothing has decided nothing, whichever way its directory
    records it. ``parse_decisions("")`` returns the empty audit trail, so the
    caller needs no second branch. An UNREADABLE file is a third state and is
    never folded into the first: a decisions file that exists and cannot be
    read is a run whose grants and whose context digest would both be computed
    from nothing while looking like a run that had simply not decided yet.

    THAT THIRD STATE IS NOT "UNREADABLE BYTES", IT IS "NOT A READABLE FILE",
    and a bare ``is_file()`` gate in front of the read answered the wrong
    question. ``is_file()`` is false for a DIRECTORY, for a symlink to nothing,
    for a symlink LOOP and for a FIFO, and every one of those is a name this
    run's directory carries and cannot be read; returning ``""`` for them is
    the fail-open direction of exactly the fold this docstring forbids --
    ``parse_decisions("")`` finds no human decision, so ``check_contradiction``
    later has nothing to contradict, the grants are derived from nothing and
    the context digest is taken over nothing, on a run that looks like it had
    simply not decided yet.

    So EXISTENCE IS ASKED OF THE NAME and readability of what it resolves to:
    ``lexists`` is satisfied by a dangling link and by a loop, which is the
    distinction ``exists()`` cannot make, and ``read_text`` is reached only for
    a regular file. That last part is also what keeps a FIFO from BLOCKING this
    call -- which is made under the run lock -- until a writer that never
    comes.
    """
    path = run_dir / _DECISIONS_FILE
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            #: Unlinked between the check and the open. Missing is missing at
            #: whichever moment it became so, and this is the ONE narrow
            #: demotion: every other ``OSError`` is the third state, for
            #: ``payload_digest``'s reason one door over.
            return ""
        except (OSError, UnicodeError) as exc:
            raise TrackerValidationError(
                f"unreadable {_DECISIONS_FILE}: {exc}; the audit trail is what "
                "a grant is read from and a run cannot proceed without it"
            ) from exc
    if os.path.lexists(path):
        raise TrackerValidationError(
            f"{_DECISIONS_FILE} is not a regular file; the audit trail is what "
            "a grant is read from and a run cannot proceed without it, and a "
            "name that exists and cannot be read is not a run that has decided "
            "nothing")
    return ""


def _budget_extensions(run_dir: Path, adopted_ids: list, run_id: str,
                       revision: int, phases: frozenset) -> list:
    """Every grant this run holds: the pinned ones, plus any newly signed.

    A GRANT IS CHECKED ONCE AND THEN PINNED. ``Granted against`` names the
    adopted set the human was shown, and that set grows the moment the grant is
    used -- so re-checking it on the next budget check would reject the grant
    the run is at that moment relying on. The pin is read first and its entries
    are never re-derived.

    PINNED GRANTS COUNT EVEN WHEN THE RECORD BEHIND THEM IS NO LONGER ADOPTED,
    and that is not a detail. An axis holds at most one Adopted decision, so the
    way to write a second grant on one axis is to supersede the first -- and a
    reader that kept only the live Adopted grants would then see one grant where
    two were signed, silently drop a ceiling the run had already spent against,
    and let a third grant be written as a second. The pin exists precisely so a
    later adoption cannot retire a grant the run has already relied on.
    """
    pins_path = run_dir / _QUORUM_DIRNAME / _EXTENSIONS_FILE
    grants: dict = {}
    if pins_path.is_file():
        pinned = _read_json(pins_path, "the pinned budget extensions")
        if not isinstance(pinned, list):
            raise QuorumSchemaInvalid(
                f"{_EXTENSIONS_FILE} holds a {type(pinned).__name__}, not a "
                "list of grants")
        for index, entry in enumerate(pinned):
            grant = _pinned_grant(entry, f"{_EXTENSIONS_FILE}[{index}]",
                                  phases=phases)
            if grant["decision_id"] in grants:
                raise QuorumSchemaInvalid(
                    f"{_EXTENSIONS_FILE} pins {grant['decision_id']} twice; one "
                    "grant pinned twice counts as two against a cap of "
                    f"{MAX_EXTENSIONS}, or as one ceiling stated two ways")
            grants[grant["decision_id"]] = grant
    decisions = parse_decisions(_decisions_text(run_dir))
    for did in sorted(decisions["decisions"]):
        record = decisions["decisions"][did]
        if (record["action"] != _DRIFT_EXTENSION_ACTION
                or record["status"] != "Adopted"):
            continue
        if did in grants:
            #: Already pinned. Never re-derived and never re-checked
            #: against an adopted set that has moved since it was signed.
            continue
        grants[did] = _live_grant(did, record, run_id=run_id,
                                  revision=revision,
                                  adopted_ids=adopted_ids, phases=phases)
    ordered = [grants[did] for did in sorted(grants)]
    if len(ordered) > MAX_EXTENSIONS:
        raise TrackerValidationError(
            f"{len(ordered)} drift-budget extensions have been granted "
            f"({sorted(grants)}) and the cap is {MAX_EXTENSIONS}; the budget is "
            "now terminal. Three grants with no change to the underlying "
            "problem is not a budget problem -- it means stage 02 selected the "
            "wrong questions, and the repair is a new run with better ones")
    #: Pinned only after the cap is judged, so a grant past the cap is never
    #: written down as one the run holds.
    _pin_extensions(pins_path, ordered)
    return ordered


def quorum_budget(run_dir: str, *, phase: str) -> dict:
    """Remaining machine decision authority, checked BEFORE dispatch.

    ONLY ADOPTIONS ARE CHARGED. Escalations never count -- an escalation is the
    run asking for help, and charging for it teaches the controller to stop
    asking, which is the exact opposite of the design's intent. Rejections do
    not count either: a rejected quorum adopted nothing.

    The budget caps DECISION AUTHORITY and not run cost; ``agent_dispatch_count``
    is a separate counter and this function never reads it.

    Two ceilings, and both bind. The per-phase ceiling stops one phase spending
    the whole run's authority on its own questions; the run ceiling stops the
    phases between them doing it a slice at a time. A human grant raises the
    named phase's ceiling and raises the run's by exactly the extra authority it
    confers -- summed over the phases granted, never taken as a maximum, because
    two grants each conferring three more adoptions confer six, and a run
    ceiling that rose by three would leave the second grant half unusable while
    reporting that it had been honoured.

    ``run_ceiling`` IS THE RUN'S TOTAL AUTHORITY AND ``run_remaining`` IS THIS
    PHASE'S SHARE OF WHAT IS LEFT, and the two are deliberately not one
    subtraction apart. A grant is PHASE-SCOPED: ``Scope`` names the phase whose
    ceiling it raises, so the headroom it confers is spendable by that phase and
    by no other. Read as a single fungible pool -- which is what
    ``run_ceiling - run_adoptions`` says -- a grant scoped ``P04`` let ``P06``
    decide past ``BUDGET_PER_RUN`` on authority the human never gave it, and the
    granted phase got none of it. So the run's authority is accounted in two
    parts: a SHARED pool of ``BUDGET_PER_RUN``, which every phase draws its
    standing three from, and one PRIVATE pool per granted phase holding exactly
    the headroom that grant conferred. An adoption past a phase's standing three
    is drawn from that phase's private pool; every other adoption is drawn from
    the shared one. ``run_remaining`` is therefore what is left of the shared
    pool plus what is left of THIS phase's private pool, and it is never more
    than ``run_ceiling - run_adoptions``: the binding is a tightening, and an
    ungranted phase sees exactly the run ceiling it would have seen with no
    grant in the run at all.
    """
    if not _text(phase) or not _TOKEN.fullmatch(phase.strip()):
        #: HELD TO THE SAME GRAMMAR ``_final_event`` HOLDS A RECORD'S PHASE TO,
        #: and that is the whole argument for the check. The per-phase count is
        #: an equality against this string, so a phase spelled in a way no
        #: ``final.json`` could ever carry matches nothing, reports zero
        #: adoptions and hands the caller a fresh three-adoption budget --
        #: fail-open by unrecognisable token, on the axis where failing open
        #: means the run keeps deciding past the ceiling a human set.
        #:
        #: What this CANNOT catch is a typo that is itself a legal phase token:
        #: ``p04`` for ``P04`` still reports zero adoptions. It is NOT held to
        #: ``## Phases`` -- that section is empty on a freshly initialised run,
        #: and this is the one budget question that must stay answerable before
        #: a phase has a row, because the count it returns is an equality
        #: against the ``final.json`` records rather than a tracker lookup.
        #: A grant's ``Scope`` IS held to that registry, in ``_live_grant``, and
        #: the two are not the same check: a grant exists only after a phase has
        #: exhausted three adoptions, so its phase is registered by then, and a
        #: grant scoped to nothing burns one of only two extensions while this
        #: argument merely reports a budget the caller asked about. The residual
        #: belongs to the caller: the phase passed here is the phase written
        #: into the ``final.json`` the adoption files.
        raise QuorumError(
            f"phase {phase!r} is not a phase token; a budget charged against a "
            "phase no record can name is measured on nothing, and it reports a "
            "full budget for every question the run raises")
    phase = phase.strip()
    path = _run_path(run_dir)
    #: THE RUN ID IS READ FROM THE TRACKER, which is the one place it is
    #: recorded and validated. A grant names the run it was signed for, and a
    #: run id taken from anywhere else -- a sidecar file, the directory name --
    #: is a second spelling that can disagree with the one the schema guards.
    tracker = validate_run(path)
    run = tracker["run"]
    #: THE RUN'S REAL PHASE IDS, read from the one section that holds them, so
    #: a grant's ``Scope`` is checked against the phases this run has rather
    #: than against a shape that resembles one.
    phases = frozenset(row["id"] for row in tracker["phases"])
    events = quorum_events(run_dir)
    adopted = [event for event in events
               if event["status"] == _CHARGED_STATUS]
    adopted_ids = sorted(event["decision_id"] for event in adopted)
    grants = _budget_extensions(path, adopted_ids, run["run_id"],
                                int(run["revision"]), phases)

    #: One ceiling per phase granted, so two grants naming the same phase raise
    #: it once rather than compounding.
    ceilings: dict = {}
    for grant in grants:
        standing = BUDGET_PER_PHASE
        if grant["phase"] in ceilings:
            standing = ceilings[grant["phase"]]
        ceilings[grant["phase"]] = max(standing, grant["authorized_through"])

    charged: dict = {}
    for event in adopted:
        charged[event["phase"]] = charged.get(event["phase"], 0) + 1
    phase_adoptions = charged.get(phase, 0)
    run_adoptions = len(adopted)
    phase_ceiling = ceilings.get(phase, BUDGET_PER_PHASE)
    #: The run's TOTAL authority, summed over the phases granted. Reported as
    #: it always was: two grants each conferring three confer six.
    run_ceiling = BUDGET_PER_RUN + sum(ceilings[scope] - BUDGET_PER_PHASE
                                       for scope in sorted(ceilings))

    #: How much of each private pool has actually been drawn. CAPPED AT THE
    #: HEADROOM, which is what keeps an over-spent phase honest: a phase with
    #: five adoptions and no grant has no private pool to have drawn them from,
    #: so all five are charged to the shared pool rather than two of them
    #: vanishing out of the run's count of itself.
    drawn = 0
    for scope in sorted(ceilings):
        drawn += min(ceilings[scope] - BUDGET_PER_PHASE,
                     max(0, charged.get(scope, 0) - BUDGET_PER_PHASE))
    shared = run_adoptions - drawn
    own = min(phase_ceiling - BUDGET_PER_PHASE,
              max(0, phase_adoptions - BUDGET_PER_PHASE))
    run_remaining = (max(0, BUDGET_PER_RUN - shared)
                     + (phase_ceiling - BUDGET_PER_PHASE) - own)
    reason = None
    if phase_adoptions >= phase_ceiling:
        reason = "phase-budget-exhausted"
    elif run_remaining <= 0:
        reason = "run-budget-exhausted"
    return {
        "run_id": run["run_id"],
        "phase": phase,
        "phase_adoptions": phase_adoptions,
        "phase_ceiling": phase_ceiling,
        "phase_remaining": max(0, phase_ceiling - phase_adoptions),
        "run_adoptions": run_adoptions,
        "run_ceiling": run_ceiling,
        "run_remaining": run_remaining,
        "extensions": grants,
        "adopted": adopted_ids,
        "may_raise": reason is None,
        "reason": reason,
    }


# --- opening a quorum ------------------------------------------------------
#
# Phase 1 of the three-phase record, and the one place two rules meet that are
# each easy to get backwards.
#
# THE BUDGET TRIPS AT RAISE TIME, BEFORE DISPATCH. The natural place to check
# it is where the counter moves -- at adoption -- and a check written there
# passes every budget test in this suite while three brains are dispatched at a
# question that could never have been adopted. The triggering question is never
# sent, so the check is here, ahead of the first byte written into the qid's
# directory.
#
# A RE-RAISE OF A SETTLED QID DISPATCHES NOTHING. This is the compaction-replay
# guard: after a compaction the controller has forgotten that it asked, the
# worker re-publishes byte-identical question text, ``derive_qid`` returns the
# same identity on purpose, and a second quorum on a settled question is how a
# run quietly changes its own mind.

#: Phase 1's record and the directory phase 2 fills. ``open.json`` is published
#: BEFORE any brain is dispatched, so an interruption a moment after dispatch
#: is still classifiable from disk alone, and a re-dispatch can prove it is
#: sending the same bytes.
_OPEN_FILE = "open.json"
_RESPONSES_DIRNAME = "responses"
_PAYLOAD_PREFIX = "payload-"

#: The state an opened quorum is in, spelled as P02 spells it in
#: ``_QUORUM_STATES`` -- the row this record will become carries the same word,
#: and the suite pins the two together so neither can drift alone.
_IN_FLIGHT = "in_flight"

#: Every status an ``open.json`` may carry, which is one. It exists as a set
#: because the membership test it feeds is over a value read back off disk.
_OPEN_STATES = frozenset({_IN_FLIGHT})

#: The terminal status a budget trip writes. Named rather than typed at the
#: literal so it is checked against ``_FINAL_STATUSES`` in one place.
_ESCALATED = "escalated"

#: An owner id, held to what may safely become a PATH COMPONENT.
#:
#: The payload a brain receives is written to ``payload-<owner>.json`` inside
#: the qid's directory, and an owner is agent-authored free text: ``parse_question``
#: builds the list with ``_csv``, which splits on commas and strips, and
#: refuses nothing else. ``check_admissible`` counts them and requires them
#: distinct, which is a question about the quorum and not about the filesystem.
#: So ``Owners: ../../../../etc/brain-a, brain-b, brain-c`` names a path
#: OUTSIDE the run directory, and ``brain/a`` names a subdirectory of the qid's
#: own -- the first writes a payload where no audit trail will ever find it,
#: and the second makes the payload's own name disagree with the owner
#: ``open.json`` records. Neither raises; both look like a quorum that opened.
#:
#: THE SEPARATOR IS THE HALF THAT GUARDS THE FILESYSTEM AND THE LEADING DOT
#: IS NOT -- an earlier note here had it the other way round and was wrong.
#: ``payload-`` sits in front of every owner, so ``..`` is written as
#: ``payload-...json``: a leading dot climbs nothing, hides nothing and lands
#: nowhere new, and NO INPUT distinguishes a grammar that admits it from this
#: one. The first character's rule is therefore PINNED BY A TEST rather than
#: left to a consequence it does not have, and what it buys is not safety but
#: sameness -- an owner id is the shape ``_RUN_ID`` is, so an id means one
#: thing everywhere this run records one, and an owner that is nothing but
#: punctuation is refused at the raise instead of read back later as a name.
#:
#: A TRAILING DOT IS REFUSED DELIBERATELY. ``brain`` and ``brain.`` are two
#: owners to ``check_admissible``, which requires them distinct, and ONE FILE
#: to Windows, which strips it -- and ``select_lock_impl``'s ``msvcrt`` branch
#: says this module means to run there. Two brains sharing one payload file is
#: either a ``publish_immutable`` stop on the second or one brain answering
#: from the other's bytes, and no real owner id ends in a dot.
#:
#: THE LENGTH IS BOUNDED so that no owner this grammar admits can fail at the
#: WRITE. ``payload-<owner>.json`` is a single filename and ``NAME_MAX`` is 255
#: on every filesystem this runs on, so an unbounded owner passes every check
#: here and fails inside ``publish_immutable`` with ``ENAMETOOLONG`` -- after
#: ``question.md``, ``responses/`` and a rewritten projection are already on
#: disk, with no ``open.json`` and no ``final.json``, which is the one shape
#: ``_open_under_lock``'s all-or-nothing discipline does not cover. 64 is ample
#: for a brain id and puts that failure out of reach of a legal one.
_OWNER_MAX = 64


class _Owner:
    """A ``_CharClass``, bounded in length and forbidden a trailing dot.

    A wrapper rather than two more options on ``_CharClass``: both extra rules
    are about THIS grammar becoming a filename on a filesystem this module may
    not be running on, and ``_TOKEN``, ``_RUN_ID`` and ``_ABS_PATH`` would each
    have to be asked the question separately before inheriting an answer.
    """

    __slots__ = ("_body", "_limit")

    def __init__(self, body, limit: int) -> None:
        self._body = body
        self._limit = limit

    def fullmatch(self, value: str) -> bool:
        return (self._body.fullmatch(value) and len(value) <= self._limit
                and not value.endswith("."))


_OWNER = _Owner(_CharClass(_ALNUM, _ALNUM + "._-"), _OWNER_MAX)


def _record_path(question_record) -> Path:
    """``question_record`` as a ``Path``, with anything else refused.

    ``_run_path``'s argument, one function over. ``Path(5)`` raises
    ``TypeError``, outside ``TrackerError``, and the record path is the one
    argument a controller assembles from whatever the raising worker published.
    """
    if not isinstance(question_record, (str, Path)):
        raise QuorumError(
            f"question_record is {type(question_record).__name__}, not a path; "
            "coercing it would open a quorum on a file named by a repr")
    return Path(question_record)


def _write_run_file(path: Path, content: str, what: str) -> None:
    """Write a REGENERATED file inside the run, inside the exception family.

    ``publish_immutable`` is for everything written once -- the question
    record, each payload, ``open.json``, ``final.json``. This is for the one
    file here that is not: ``decisions-effective.md`` is a projection of an
    append-only source and is rewritten whenever that source moves. Its content
    at dispatch time is bound by ``payload_digest``, which is what makes a
    later rewrite detectable rather than silent.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TrackerWriteError(
            f"cannot write {what} at {str(path)!r}: {exc}") from exc


def _opened_record(path: Path, qid: str) -> dict:
    """One ``open.json``, validated the way ``_final_event`` validates its own.

    ``status`` is tested with ``_member`` and it is tested FIRST, ahead of the
    qid comparison, which is the ordering rather than an accident. The record
    is a JSON file on disk in a directory a human may have edited or restored
    from a backup, so ``status`` may legally be a list or an object, and
    ``["in_flight"] in frozenset(...)`` raises ``TypeError`` -- outside
    ``TrackerError``, so it escapes every handler a controller has written.
    Behind any check on another field that happens to raise first, a bare
    ``in`` written here would pass the suite.

    THE QID IS RE-DERIVED FROM THE DIRECTORY AND COMPARED, for the reason
    ``_final_event`` and ``_question_record`` compare it: a quorum directory
    can be copied, renamed or half-restored, and an open record filed under
    another question's qid would have this call report a quorum in flight for a
    question nobody asked -- and dispatch nothing, forever.
    """
    record = _read_json(path, f"the open record for {qid}")
    if not isinstance(record, dict):
        raise QuorumSchemaInvalid(
            f"the open record for {qid} is a {type(record).__name__}, not an "
            "object; a quorum in flight is a record with owners and digests in "
            "it, and a bare value classifies nothing")
    status = record.get("status")
    if not _member(status, _OPEN_STATES):
        raise QuorumSchemaInvalid(
            f"{qid}: open status {status!r} is not {sorted(_OPEN_STATES)}; an "
            "unrecognised status is neither a quorum in flight nor a finalised "
            "one, and the controller cannot say whether it owes a dispatch")
    stated = record.get("qid")
    if not _text(stated) or stated.strip() != qid:
        raise QuorumSchemaInvalid(
            f"the open record filed under {qid} states qid {stated!r}; a record "
            "in flight under another question's identity matches responses, "
            "digests and a decision to a question nobody asked")
    return record


#: The two reasons that mean NOTHING ABOUT THE ANSWER WAS EVER MEASURED, and
#: the whole of them. They are the only refusals the re-raise door below
#: admits: a brain was never dispatched, so there is no earlier measurement to
#: be better than and no bar to clear. Every other reason -- ``below-floor``,
#: ``equal-or-inverted-rung``, ``uncomparable-answer``, ``unmintable-axis`` --
#: is a refusal by the EVIDENCE, and a question re-asked against one of those
#: owes evidence and owes a bar, which is the challenge door.
#:
#: THE TWO TOKENS ARE RESTATED HERE RATHER THAN SHARED WITH ``quorum_budget``,
#: and that is deliberate. The suite derives this phase's reason vocabulary
#: from the module's own source by collecting assignments to a name called
#: ``reason``, so replacing those two literals with a reference to this set
#: would delete both tokens from the vocabulary the batching human's
#: ``_ESCALATION_BLAST`` is checked against. The two spellings are pinned to
#: each other by ``test_the_re_raise_door_admits_exactly_the_budget_refusals``,
#: which reads the reasons ``quorum_budget`` actually returns.
_BUDGET_REASONS = frozenset({"phase-budget-exhausted", "run-budget-exhausted"})


def _trail_ids(run_dir: Path) -> list:
    """Every decision id on the append-only trail, right now.

    Recorded into a budget refusal so that a later re-raise can be held to the
    ORDERING PROPERTY the door rests on: the fact that authorizes a re-ask has
    to be one that WAS NOT THERE when the first answer was recorded. A grant
    already on this list when the question was refused authorized nothing --
    the run had it in hand and was refused anyway -- and a re-ask against it is
    the same question with nothing new to name.
    """
    return sorted(parse_decisions(_decisions_text(run_dir))["decisions"])


def _budget_escalation(qid: str, record: dict, budget: dict,
                       trail: list) -> dict:
    """The terminal record a budget trip writes, and the whole of it.

    NO ``context_digest`` AND NO PAYLOAD DIGEST, because nothing was
    dispatched: there is no context any brain saw and no bytes any brain
    received, and a digest recorded here would be a claim about a dispatch that
    never happened. What it carries instead is the question itself and the two
    counts, because this record is what a human is handed when they are asked
    to decide the question the run may no longer decide for itself.

    The raiser's identity, their candidate answers and their recommendation are
    absent, and their absence is the same whitelist ``_record_projection``
    states: they are recorded in the question record for audit and they frame
    an answer, so they reach neither a brain nor the human this escalation is
    addressed to.
    """
    return {
        "qid": qid,
        "status": _ESCALATED,
        "reason": budget["reason"],
        "phase": record["phase"],
        "axis": record["axis"],
        "question": record["question"],
        "blocks": list(record["blocks"]),
        "owners": list(record["owners"]),
        "decision_id": None,
        "winner": None,
        "dispatched": False,
        "phase_adoptions": budget["phase_adoptions"],
        "phase_ceiling": budget["phase_ceiling"],
        "run_adoptions": budget["run_adoptions"],
        "run_ceiling": budget["run_ceiling"],
        "adopted": list(budget["adopted"]),
        #: THE TRAIL AS IT STOOD WHEN THE QUESTION WAS REFUSED, and the one
        #: cell that makes the re-raise door orderable. ``_reopen_authority``
        #: refuses a grant that is already in this list: the run held that
        #: authority at the moment it was refused, so re-asking against it
        #: names no new fact. Every id, not only the adopted ones -- a grant
        #: is not an adoption and would be invisible in ``adopted``.
        "trail_at_refusal": list(trail),
    }


#: The action an adoption writes, named once so the authority check below and
#: ``_decision_record`` cannot come to disagree about what an adoption is.
_QUORUM_ADOPT_ACTION = "quorum.adopt"

#: The two kinds of fact that may authorize a re-ask, and the whole of them.
#: A CHALLENGE aims at a decision this run's own brains adopted and raises the
#: bar to that decision's rung; a RE-RAISE aims at a human grant that restored
#: headroom the first raise was refused for, and raises nothing, because a
#: budget refusal measured no answer at all.
_REOPEN_CHALLENGE = "challenge"
_REOPEN_RERAISE = "re-raise"


def _reopen_refusal(run_dir: Path, original_qid: str, decision_id: str) -> dict:
    """The terminal BUDGET refusal a re-raise is answering, or a stop.

    WITHOUT THIS BINDING ``_REOPEN_RERAISE`` IS AN IDENTITY-MINTING TOKEN.
    The door was opened for one shape -- a question refused before a single
    brain was dispatched, whose headroom a human then restored -- and the
    authority check saw only the grant. So a question the brains DID answer
    and the EVIDENCE refused (``below-floor``, ``equal-or-inverted-rung``,
    ``uncomparable-answer``) was re-askable against a grant that had nothing to
    do with it: an empty ``Challenge``, three fresh brains, a brand-new
    identity and ``raised_bar_rung = None``, judged at the ordinary floor
    exactly as if it had never been asked. That is a run laundering a refusal
    into an adoption, through the door built to stop it.

    SO THE RE-RAISE IS BOUND TO THE ORIGINAL QUESTION'S OWN OUTCOME. The
    original qid is ``derive_qid(question, axis)`` -- the lineage root, which
    the re-ask already carries -- and this run must hold a terminal
    ``final.json`` there that ESCALATED, for one of ``_BUDGET_REASONS``.
    Anything else is a challenge: it owes evidence and it owes a bar.

    A MISSING RECORD IS A STOP AND NOT A PASS. A question this run never
    asked has never been refused, so there is nothing to re-raise, and the
    grant authorizes a re-ask of nothing.
    """
    path = run_dir / _QUORUM_DIRNAME / original_qid / _FINAL_FILE
    #: ``lexists`` RATHER THAN ``exists``, for the reason every other reader of
    #: this name uses it: a dangling ``final.json`` or a symlink loop answered
    #: "never asked" here would send the re-raise straight past this gate, and
    #: ``_require_regular_file`` inside ``_final_event`` is what then refuses
    #: the shape rather than hanging on it.
    if not os.path.lexists(path):
        raise QuorumError(
            f"cannot re-raise against {decision_id}: this run holds no outcome "
            f"for {original_qid}, the question being re-asked. A budget grant "
            "restores headroom for a question the budget REFUSED, and a "
            "question that was never asked was never refused -- so this names "
            "no fact about the question at all")
    _, refusal = _final_event(path, original_qid)
    reason = refusal.get("reason")
    if refusal["status"] != _ESCALATED or not _member(reason, _BUDGET_REASONS):
        raise QuorumError(
            f"cannot re-raise against {decision_id}: {original_qid} settled as "
            f"{refusal['status']!r}/{reason!r}, and a budget grant re-opens "
            f"only a question refused for {sorted(_BUDGET_REASONS)} -- a "
            "refusal taken before a brain was dispatched, where nothing about "
            "the answer was ever measured. A question the brains answered and "
            "the EVIDENCE refused is re-asked through the challenge door, "
            "which owes evidence and clears a raised bar; admitted here it "
            "would be re-judged at the standing floor with nothing new said")
    return refusal


def _reopen_authority(run_dir: Path, decision_id, record: dict) -> tuple:
    """``(kind, raised_bar_rung)`` for the record that authorizes a re-ask.

    THE DOOR TASK 8 LEFT SHUT, OPENED EXPLICITLY AND NARROWLY. An escalated
    ``final.json`` is terminal, so without this a question the budget refused
    can never be asked again however much headroom a human grants, and a
    decision this run adopted on thin evidence can never be revisited. Falling
    THROUGH the terminal record was the other option and it is fail-open: it
    turns every re-ask into a re-roll and the replay guard into a comment.

    SO A RE-ASK IS ADMITTED ONLY AGAINST A FACT ON THE APPEND-ONLY TRAIL THAT
    WAS NOT THERE WHEN THE FIRST ANSWER WAS RECORDED, and there are exactly
    two:

    * an ADOPTED QUORUM DECISION. The re-ask challenges it, and the bar becomes
      that decision's own grounding rung -- see ``_compute_quorum_result``,
      where clearing it means STRICTLY better evidence, not equal evidence.
    * a HUMAN BUDGET GRANT. The first raise was refused before a single brain
      was dispatched, so nothing about the answer was ever measured; the grant
      is the headroom, the standing floor is the bar, and there is no raised
      bar to clear.

    A HUMAN DECISION ON THE AXIS IS REFUSED OUTRIGHT, and it is the refusal
    that keeps the exemption in ``_apply_adoption_gates`` safe. A quorum may
    decide an open question and may revisit its OWN answer at a higher bar; it
    may never overrule the user. Admitted here, ``Reopen of: H-001`` would
    exempt the user's own decision from the contradiction check and the run
    would adopt straight over it, with every record on disk well-formed.

    A SUPERSEDED OR OPEN RECORD IS REFUSED TOO. A superseded decision is not
    what the run is standing on, so challenging it raises a bar nothing is
    measured against; an Open record decided nothing to challenge.

    BOTH DOORS ARE BOUND TO THE QUESTION BEING RE-ASKED, which is why this
    takes the question record and not a bare D-ID. The authority alone says
    nothing about WHICH question it authorizes, and read that way each door
    failed in its own direction:

    * the CHALLENGE door let a re-open on one axis challenge a decision on
      another. Supersession is axis-derived, so the "challenged" decision was
      never touched, the re-open spent the real lineage's single allowance on
      borrowed authority, and ``final.json`` and ``decisions.md`` both carried
      a ``Reopen Of`` naming a decision nobody had challenged. The axes must
      be equal: a re-ask of a different question is a different question.
    * the RE-RAISE door let a grant re-open a question it had nothing to do
      with -- see ``_reopen_refusal``, which is the binding, and the ordering
      rule below, which is the other half of it.
    """
    #: RULE 9, AT THE SITE WHERE IT BITES. ``decisions["decisions"].get(x)``
    #: HASHES ``x``, and ``reopen_of`` is agent-authored: a list or an object
    #: there raises ``TypeError``, which is outside ``TrackerError`` and kills
    #: the run through a handler no controller has written. Unreachable through
    #: ``open_quorum`` today only because ``parse_question`` yields a ``str``,
    #: which is precisely the accident rule 9 exists to stop relying on --
    #: ``derive_reopen_qid`` guards the same argument and this did not.
    if not isinstance(decision_id, str):
        raise QuorumSchemaInvalid(
            f"reopen_of is {type(decision_id).__name__}, not str; a re-ask is "
            "admitted against the record that authorizes it, and a repr names "
            "no record")
    challenged = decision_id.strip()
    decisions = parse_decisions(_decisions_text(run_dir))
    authority = decisions["decisions"].get(challenged)
    if authority is None:
        raise QuorumError(
            f"cannot re-open {challenged}: this run's audit trail holds no "
            "such decision. A re-ask is admitted only against a record that "
            "authorizes it, and a citation nothing resolves is the run "
            "authorizing itself")
    if authority["status"] != "Adopted":
        raise QuorumError(
            f"cannot re-open {challenged}: its status is "
            f"{authority['status']!r}, not 'Adopted'. A superseded record is "
            "not what the run is standing on and an open one decided nothing, "
            "so neither states a bar and neither is a fact that has changed")
    if (authority["provenance"] == "quorum"
            and authority["action"] == _QUORUM_ADOPT_ACTION):
        #: THE AXES MUST BE THE SAME QUESTION'S. Supersession is derived from
        #: the axis, so a cross-axis challenge leaves the record it claims to
        #: challenge Adopted and untouched -- the re-open adopts BESIDE it, on
        #: a third axis, while both records say a challenge happened. It also
        #: spends the challenged lineage's one allowance on a lineage that has
        #: nothing to do with it.
        if authority["axis"] != record["axis"]:
            raise QuorumError(
                f"cannot re-open {challenged} on axis {record['axis']!r}: that "
                f"decision stands on axis {authority['axis']!r}. A re-open "
                "challenges ONE decision and supersedes it, and supersession "
                "is derived from the axis -- so a challenge aimed across axes "
                "adopts beside the record it names instead of replacing it, "
                "and leaves an audit trail where both say a challenge happened "
                "and neither was challenged")
        rung = authority.get("grounding_rung")
        rung = rung.strip() if isinstance(rung, str) else rung
        #: HELD TO ``ADOPTABLE``, NOT MERELY TO THE LADDER. Only those two
        #: rungs can ever have been adopted, so a record claiming Adopted at
        #: anything lower is a trail that disagrees with itself -- and read as
        #: a bar it would be a bar BELOW the floor, which every answer clears.
        #: That is the self-serving move arriving through the audit trail
        #: instead of through the code.
        if not _member(rung, ADOPTABLE):
            raise QuorumError(
                f"cannot re-open {challenged}: it records grounding rung "
                f"{rung!r}, and only {sorted(ADOPTABLE)} can have been adopted. "
                "The raised bar IS that rung, so a bar read off a record that "
                "disagrees with itself is a bar below the floor -- every "
                "answer clears it and the decision is re-taken at the same "
                "quality of evidence, which is the dice rolled again")
        return _REOPEN_CHALLENGE, rung
    if (authority["provenance"] == "human"
            and authority["action"] == _DRIFT_EXTENSION_ACTION):
        original_qid = _reopen_lineage_root(record)
        refusal = _reopen_refusal(run_dir, original_qid, challenged)
        #: THE ORDERING PROPERTY, WHICH IS THE WHOLE OF THE DESIGN SENTENCE:
        #: a re-ask is admitted only against A FACT THAT WAS NOT THERE WHEN THE
        #: FIRST ANSWER WAS RECORDED. Nothing enforced it, and a grant written
        #: BEFORE the question was ever raised authorized the re-ask -- the run
        #: held that authority at the moment it was refused and was refused
        #: anyway, so it names nothing new. Reached by re-raising in a phase
        #: that still has headroom, because the lineage carries no phase.
        #:
        #: THE CHALLENGE DOOR NEEDS NO SUCH TEST and that is not an omission:
        #: there the authority IS the first answer, so it cannot predate
        #: itself, and the raised bar is read off that same record.
        prior = refusal.get("trail_at_refusal")
        if not isinstance(prior, list) or not all(isinstance(entry, str)
                                                  for entry in prior):
            raise QuorumSchemaInvalid(
                f"the refusal recorded for {original_qid} states "
                f"trail_at_refusal {prior!r}, not a list of decision ids; "
                "without the trail as it stood at the refusal nothing can say "
                "whether the grant is a fact that was not there, and a re-ask "
                "that cannot be ordered against the refusal it answers is the "
                "same question asked again")
        if challenged in prior:
            raise QuorumError(
                f"cannot re-raise {original_qid} against {challenged}: that "
                "grant was already on the audit trail when the question was "
                "refused. A re-ask is admitted only against a fact that was "
                "NOT THERE when the first answer was recorded -- the run held "
                "this authority at the moment it was refused and was refused "
                "anyway, so re-asking against it names nothing new and is the "
                "dice rolled again")
        return _REOPEN_RERAISE, None
    raise QuorumError(
        f"cannot re-open {challenged}: it is a {authority['provenance']} "
        f"decision whose action is {authority['action']!r}, and the only facts "
        "that authorize a re-ask are a quorum adoption (challenged at a raised bar) "
        "and a human drift-budget grant (the headroom the first raise was "
        "refused for). A human's answer on the axis is not one of them -- a "
        "quorum may revisit its own answer and may never overrule the user")


def _screen_challenge(run_dir: Path, challenged: str, stated: list) -> None:
    """Refuse a challenge that names one of the brains it is challenging.

    THE CONTRACT ``challenge`` IS HELD TO HAS FOUR CLAUSES, and this closes the
    third. What a re-open's brains may learn is WHERE TO LOOK; what they may
    not learn is anything about the earlier attempt as an attempt -- because a
    brain told what the last answer scored, or who gave it, is a brain told
    what to beat, and the re-open stops being an independent measurement:

    1. the earlier answer's RUNG NAME -- screened by ``_rung_leak`` on the
       hyphenated names, in ``parse_question``;
    2. its RUNG VALUE -- screened by ``_rung_leak``'s decimal scan;
    3. its OWNER -- screened HERE. It is the one clause that needs the run:
       the owners are in the challenged quorum's ``open.json`` and no reader
       of the record alone can know them;
    4. its DISTANCE FROM THE FLOOR **stated in words** -- ``barely cleared the
       bar``, ``adopted at the floor exactly``, ``only just above the line``.
       NOT SCREENABLE, and recorded as an accepted residual in the plan's
       ``## Unresolved`` rather than guessed at: nothing in the text
       distinguishes it from a legitimate description of the evidence, and a
       heuristic here would be a heuristic exactly where the screen is relied
       on to be total. The raised bar is what bounds its cost -- a brain that
       knows the last answer was close still has to clear the rung STRICTLY.

    THE CHALLENGED QUORUM'S RECORD MUST BE THERE. A quorum whose decision this
    run adopted was dispatched, so its ``open.json`` exists; a challenge aimed
    at a decision whose record has gone is a challenge nothing can screen, and
    passing it would make the screen optional exactly when the trail is
    damaged.
    """
    qid = challenged[len(_QUORUM_PREFIX):]
    opened = _opened_record(
        run_dir / _QUORUM_DIRNAME / qid / _OPEN_FILE, qid)
    owners = opened.get("owners")
    if not isinstance(owners, list):
        raise QuorumSchemaInvalid(
            f"the open record for {qid} states owners {owners!r}, not a list; "
            "a challenge is screened against the brains it challenges, and an "
            "owner list nothing can read screens against nothing")
    for entry in stated:
        lowered = entry.casefold()
        for owner in owners:
            if _text(owner) and _quotes_word(lowered, owner.strip().casefold()):
                raise QuorumError(
                    f"the re-open of {challenged} names {owner.strip()!r}, one "
                    "of the brains that answered it. The challenge reaches all "
                    "three of the new brains verbatim, and a brain told WHO "
                    "gave the earlier answer is a brain pricing the answer by "
                    "its author -- say what the evidence is and where it is, "
                    "not whose answer missed it")


def _prior_reopens(run_dir: Path, lineage_root: str) -> list:
    """Every re-ask already OPENED on this lineage, by qid.

    AT MOST ONE RE-OPEN PER LINEAGE PER RUN. Without the cap a run spends its
    whole drift budget arguing with itself: each answer is challenged by the
    next, every challenge is admissible on its own terms, and the run
    oscillates until the ceiling stops it -- having decided nothing and spent
    everything.

    BOTH FILES ARE READ, AND ``open.json`` IS THE ONE THAT MATTERS. A re-ask
    still in flight has no ``final.json`` at all, so a scan over outcomes alone
    would admit a second challenge while the first was still being answered --
    six brains on one question, which is the oscillation arriving in parallel
    instead of in sequence.

    ``lexists`` RATHER THAN ``exists`` and the shape asked before the open, for
    ``_require_regular_file``'s reason: this runs with the run lock held.
    """
    root = run_dir / _QUORUM_DIRNAME
    if not root.is_dir():
        return []
    found = []
    for directory in sorted(root.iterdir()):
        for name in (_OPEN_FILE, _FINAL_FILE):
            path = directory / name
            if not os.path.lexists(path):
                continue
            record = _read_json(path, f"the {name} of {directory.name}")
            if (isinstance(record, dict)
                    and record.get("lineage_root") == lineage_root):
                found.append(directory.name)
                break
    return found


def _open_under_lock(run_dir: Path, qid: str, record: dict, text: str) -> dict:
    """``open_quorum``'s body, with the run lock already held.

    Split out so the lock is one statement in the caller and so that what runs
    inside it is a single expression to read: settle, budget, dispatch. Every
    read and every write below happens under that lock -- see ``open_quorum``
    for why a check-then-act here is not a check-then-act anybody can interleave.
    """
    #: A SYMLINKED ``quorum/`` PUBLISHES THE WHOLE RECORD OUTSIDE THE RUN, and
    #: that is RECORDED here rather than closed. Every guard this function does
    #: run is against AGENT-AUTHORED TEXT -- an owner, a qid, a run id, a
    #: citation -- untrusted because a worker composed it. A directory symlink
    #: is not that: planting one inside the run directory takes write access to
    #: the run directory, and whoever holds that can write ``final.json``
    #: outright, which is strictly more than choosing where it lands. Closing
    #: it here would buy no authority the attacker does not already hold, and
    #: it would be the module's only directory-symlink check -- ``validate_run``,
    #: ``publish_immutable`` and ``_write_run_file`` all trust the run's own
    #: shape. If that trust is withdrawn it is withdrawn in one place, for every
    #: path, not in this one function.
    directory = run_dir / _QUORUM_DIRNAME / qid
    final_path = directory / _FINAL_FILE
    #: ``lexists`` RATHER THAN ``exists``, AND THE GUARD BELOW IS WHAT IT
    #: PROTECTS. ``exists`` follows the link and answers ``False`` for a
    #: dangling symlink and for a symlink loop -- names this directory carries
    #: -- so a ``final.json`` of either shape walks straight past the
    #: compaction-replay guard. With ``open.json`` beside it the run replays the
    #: OPEN record and calls a settled question in flight; on the shape a BUDGET
    #: TRIP leaves, ``final.json`` and nothing else, it walks past both guards
    #: into the budget check and dispatches three brains at a question this run
    #: has already escalated. That is the run re-asking until it likes the
    #: answer, reached through a symlink, and it is the single failure this
    #: whole phase exists to prevent. ``classify_quorum`` and ``_open_record``
    #: already read the same names with ``lexists`` and stop; the two readers of
    #: one directory must not disagree about whether it holds an outcome.
    if os.path.lexists(final_path):
        #: THE COMPACTION-REPLAY GUARD. One outcome per qid per run: the
        #: outcome is returned and NOTHING is written, because a second quorum
        #: on a question this run has already settled is the run re-asking
        #: until it likes the answer.
        #:
        #: Validated through ``_final_event`` rather than trusted, so a record
        #: restored under the wrong qid is a stop rather than an answer handed
        #: back for a question nobody asked. The full record is returned rather
        #: than the four cells the budget projects, because the caller needs
        #: the winner it is being told not to re-litigate.
        #:
        #: ITS ``status`` IS WHATEVER WAS SETTLED -- any of ``_FINAL_STATUSES``,
        #: not only the ones a first raise can produce -- and ``replay`` is the
        #: discriminator that says so. See ``open_quorum`` for why projecting it
        #: down to those was refused.
        #:
        #: ONE READ FOR BOTH HALVES, for ``_final_event``'s reason: the record
        #: handed back is the record that was validated, not a second reading
        #: of the same name.
        _, settled = _final_event(final_path, qid)
        return dict(settled, replay=True, qid=qid)
    open_path = directory / _OPEN_FILE
    #: ``lexists`` for the reason above, and ``_open_record`` spells it the same
    #: way: a dangling ``open.json`` answered "never dispatched" here would
    #: re-enter the budget and re-raise a question already in flight.
    if os.path.lexists(open_path):
        #: Already dispatched and not yet finalised. The controller owes
        #: responses, not a second dispatch -- and re-publishing the payloads
        #: would be inert anyway, which is exactly why the guard cannot be left
        #: to ``publish_immutable``: a re-raise must not re-enter the budget.
        return dict(_opened_record(open_path, qid), replay=True, qid=qid)

    #: THE RE-ASK DOOR, AHEAD OF THE BUDGET AND AHEAD OF THE FIRST BYTE. It is
    #: an AUTHORITY check, not a spend check: a re-ask the trail does not
    #: authorize is refused whatever headroom the run has left.
    challenged = record["reopen_of"]
    lineage_root = None
    raised_bar_rung = None
    if challenged:
        lineage_root = _reopen_lineage_root(record)
        #: RAISES rather than escalates, exactly as an inadmissible question
        #: does: a re-ask citing a record the trail does not hold is a raiser
        #: fault, and writing a terminal record for it would spend this
        #: question's one identity on somebody's typo.
        kind, raised_bar_rung = _reopen_authority(run_dir, challenged, record)
        #: THE EVIDENCE RULE, ASKED WHERE THE KIND IS KNOWN. A challenge with
        #: an empty ``Challenge`` is the same question, the same context and a
        #: second roll of the dice -- the laundering this whole door is built
        #: to refuse. A re-raise with a NON-empty one is the other error and it
        #: is the one that leaks: nothing was measured, so the only thing a
        #: raiser has to write there is why the budget moved, and ``challenge``
        #: reaches all three brains verbatim.
        stated = [entry for entry in record["challenge"] if _text(entry)]
        if kind == _REOPEN_CHALLENGE and not stated:
            raise QuorumError(
                f"the re-open of {challenged} states no challenge; a re-ask "
                "carrying no evidence is the same question against the same "
                "trail, and the only thing a second answer to it can measure "
                "is which way the dice fell")
        if kind == _REOPEN_RERAISE and stated:
            raise QuorumError(
                f"the re-raise authorized by {challenged} states a challenge; "
                "the first raise was refused before a brain was dispatched, so "
                "no answer was ever measured and there is nothing to challenge "
                "-- and what a raiser writes there at that moment is why the "
                "budget moved, which travels verbatim into all three payloads")
        if kind == _REOPEN_CHALLENGE:
            #: ASKED WHERE THE KIND IS KNOWN, exactly as the evidence rule
            #: above is: only a challenge has brains to name, and only a
            #: challenge cites a ``Q-`` id whose quorum record can be read.
            _screen_challenge(run_dir, challenged.strip(), stated)
        prior = _prior_reopens(run_dir, lineage_root)
        if prior:
            #: ASSIGNED TO A LOCAL rather than written inline, and that is not
            #: a style choice: the suite derives the phase's reason vocabulary
            #: from this module's own source, collecting ``reason=`` keywords
            #: and assignments to a name called ``reason``. A token spelled
            #: any other way is a token ``_ESCALATION_BLAST`` is never asked
            #: about, and the batching human reads a ``-``.
            reason = "second-challenge"
            halt = {
                "qid": qid,
                "status": _ESCALATED,
                "reason": reason,
                "phase": record["phase"],
                "axis": record["axis"],
                "question": record["question"],
                "blocks": list(record["blocks"]),
                "owners": list(record["owners"]),
                "decision_id": None,
                "winner": None,
                "dispatched": False,
                "reopen_of": challenged,
                #: ``lineage_root`` AND NOT THE LIST OF QIDS THAT SHARE IT.
                #: The halt record used to carry ``already_reopened_by`` --
                #: ``prior``, written here and read by NOTHING, the same silent
                #: shape as the ``lineage_root`` that ``_finalisation_base``
                #: could blank with the whole suite still green. It was not
                #: information the record alone held: ``_prior_reopens(run_dir,
                #: lineage_root)`` recomputes it exactly, from the same files,
                #: at any later moment -- so the copy could only ever go stale
                #: against the tree it was copied from.
                "lineage_root": lineage_root,
            }
            #: TERMINAL AND LEGAL, not a status of its own. ``_final_event``
            #: admits five statuses and nothing else, and every reader of this
            #: run walks every ``final.json`` -- ``quorum_events``,
            #: ``current_floor``, ``quorum_tracker_rows`` and therefore every
            #: budget check and every finalisation. A record carrying
            #: ``halted-second-challenge`` would raise in all of them for ever:
            #: one halt would brick the run. It is an escalation, which is what
            #: a halt IS here -- the question stops being the machine's and
            #: goes to a human -- and ``dispatched: False`` says no brain was
            #: asked, which is what keeps it out of the ``## Quorum`` mirror.
            publish_immutable(final_path, _dumps(halt))
            return halt

    #: THE BUDGET TRIPS HERE, AHEAD OF THE FIRST BYTE. Nothing above this line
    #: has written anything, and a trip writes exactly one file -- so a
    #: question the run had no authority to ask leaves a terminal record and no
    #: question record, no projection, no responses directory and no payload.
    budget = quorum_budget(run_dir, phase=record["phase"])
    if not budget["may_raise"]:
        escalation = _budget_escalation(qid, record, budget,
                                        _trail_ids(run_dir))
        publish_immutable(final_path, _dumps(escalation))
        return escalation

    #: The record is published VERBATIM, not re-rendered from the parse.
    #: ``_question_record`` re-parses this file on every payload build and
    #: re-derives the qid from what it finds, so the bytes here and the bytes
    #: the raiser published have to be the same bytes; a round trip through the
    #: parser would make the record agree with this module's renderer instead.
    publish_immutable(directory / _QUESTION_FILE, text)

    #: The projection is regenerated from the audit trail as it stands NOW, and
    #: its content is bound into ``payload_digest`` below. Written before the
    #: payloads because the digest reads it, and read once so that the digest
    #: and ``context_digest`` cannot describe two different moments.
    decisions_text = _decisions_text(run_dir)
    _write_run_file(run_dir / _PROJECTION_FILE,
                    project_decisions(parse_decisions(decisions_text)),
                    "the decisions projection")
    try:
        (directory / _RESPONSES_DIRNAME).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TrackerWriteError(
            f"cannot create the responses directory for {qid}: {exc}; a "
            "response with nowhere to land is a brain's answer lost between "
            "the dispatch and the record of it") from exc

    #: One payload per owner, at the owner's own index, published once. A
    #: re-entry after a crash rebuilds byte-identical payloads -- that is what
    #: ``build_payload``'s purity buys -- so the republish is inert, and a
    #: payload that came back DIFFERENT is refused rather than overwritten.
    for index, owner in enumerate(record["owners"]):
        publish_immutable(directory / f"{_PAYLOAD_PREFIX}{owner}.json",
                          _dumps(build_payload(qid, index, run_dir=run_dir)))

    opened = {
        "qid": qid,
        "status": _IN_FLIGHT,
        "axis": record["axis"],
        "phase": record["phase"],
        "owners": list(record["owners"]),
        "blocks": list(record["blocks"]),
        "options_supplied": record["options_supplied"],
        #: THE QUESTION AS SENT, verbatim and unsquashed. ``derive_qid``
        #: squashes because identity must survive a reflowed line; this digest
        #: answers a different question -- were all three brains asked THESE
        #: bytes -- and a digest over the squashed form attests to a string no
        #: brain was ever shown.
        "question_digest": _digest(record["question"]),
        #: ONE digest over the shared payload and the projection. The three
        #: brains differ only by a constant rule applied to the index, so
        #: ``(payload_digest, n)`` reproduces brain n's bytes exactly, which is
        #: what a re-dispatch needs.
        "payload_digest": payload_digest(qid, run_dir=run_dir),
        #: The AUTHORITY the projection was derived from, not the projection.
        #: ``payload_digest`` already binds what the brains saw; this binds what
        #: the run had decided when they saw it, and the two differ whenever a
        #: decision lands that the projection withholds -- a superseded record,
        #: a budget grant -- which is a context change the brains could not see
        #: and a later contradiction check must.
        "context_digest": _digest(decisions_text),
        #: THE LINEAGE, PERSISTED BEFORE DISPATCH like everything else in this
        #: record. ``reopen_of`` is what licenses the finaliser to supersede
        #: the decision this challenges; ``raised_bar_rung`` is the bar that
        #: adoption must clear STRICTLY; ``lineage_root`` is what a later
        #: challenge to the same question finds so that it halts instead of
        #: opening a third quorum. All three are ``None`` on an ordinary raise,
        #: and the ``None`` is the fact -- there is no bar, and nothing to
        #: supersede.
        #:
        #: NONE OF THE THREE REACHES A PAYLOAD. ``build_payload`` is built from
        #: ``_record_projection``, which names the record's whole contribution
        #: and names none of these; a brain that learned the bar would be a
        #: brain told what to beat.
        "reopen_of": challenged or None,
        "raised_bar_rung": raised_bar_rung,
        "lineage_root": lineage_root,
    }
    publish_immutable(open_path, _dumps(opened))
    return opened


def open_quorum(run_dir: str, *, question_record: str,
                timeout_s: float = DEFAULT_LOCK_TIMEOUT_S) -> dict:
    """Phase 1 of the three-phase record: PERSIST, then dispatch.

    ``open.json`` carries the three owner ids, the shared question digest, the
    per-brain payload digest and the context digest, and it lands BEFORE any
    brain is dispatched -- so an interruption a moment later is still
    classifiable from disk alone, and a re-dispatch can prove it is sending the
    same bytes.

    THE STATUS CONTRACT, IN FULL, because a caller branches on it. Without
    ``replay``, ``status`` is ``in_flight`` -- the quorum this call opened --
    or ``escalated``, the terminal record a budget trip wrote, and those two
    are the whole of what this function INVENTS. With ``replay`` true it is
    whatever the run had already settled: ``in_flight`` for a quorum still
    awaiting responses, or ANY of ``_FINAL_STATUSES`` for one it has finished
    with -- ``adopted``, ``escalated``, ``question-not-decidable``,
    ``rejected-contradicts-human``, ``rejected-contradicts-quorum``.

    PROJECTING A REPLAY DOWN TO THE FIRST THREE WAS CONSIDERED AND REFUSED.
    It would answer "rejected because a human has already decided otherwise"
    with ``escalated``, erasing which decision the brains pulled against --
    the fact the queued escalation row exists to show the human. A replay hands back what ``finalize_quorum``
    wrote, unchanged, and ``replay`` tells a caller which contract it is
    reading.

    THE WHOLE BODY RUNS UNDER THE RUN LOCK, and that is a change of discipline
    rather than a precaution. ``worker_limit >= 4``, so two workers can raise
    two questions at the same moment; without the lock, each reads the budget,
    each rewrites ``decisions-effective.md``, and each drives
    ``quorum_budget``'s extension pin -- which is written with no lock of its
    own. The interleaving that actually corrupts state is the pin: one
    reader derives a grant against the adopted set it saw, the other derives the
    same grant against a set one adoption further on, and ``_live_grant``
    refuses the second as a human on record as having reviewed something else --
    a hard stop, on a legal run, produced by nothing but timing.

    WHAT THE LOCK DOES NOT BUY is the drift cap, and it is worth being exact
    about that because the cap is what this check exists to serve. This
    function SPENDS nothing: the budget is charged by an ADOPTION, which is a
    ``final.json`` with ``status: adopted``, which ``finalize_quorum`` writes.
    So two questions raised against one remaining adoption both pass this check
    even perfectly serialised -- the second reads exactly what the first read,
    because the first charged nothing. The check here is an ADMISSION check: it
    stops three brains being dispatched at a question that could never have been
    adopted. The cap itself can only be enforced at the charge, under the lock
    ``finalize_quorum`` already takes, and a finalisation that adopts without
    re-reading the budget there exceeds it however careful this function is.

    WHAT SERIALISING DOES NOT FIX IS THE PROJECTION, and the commit that took
    this lock claimed in its message that it did. ``decisions-effective.md`` is ONE run-global
    mutable file that every raise rewrites, while each ``open.json`` binds a
    digest over its content AT OPEN TIME -- so a later raise invalidates an
    earlier in-flight quorum's ``payload_digest`` whether or not the two raises
    ever overlapped, and the first quorum's brains are still reading the file
    the second wrote, because they read it OUTSIDE this lock and long after it
    is released. Serialised raises do that just as thoroughly as interleaved
    ones. The lock buys the extension pin; it buys nothing here. What the
    digest buys is that the drift is DETECTABLE rather than silent, and naming
    it is ``classify_quorum``'s ``stale-context``, not this function's.

    A RESERVATION WAS CONSIDERED AND REFUSED. Counting quorums in flight
    against the ceiling here would make the admission check bind under
    concurrency, and it would buy a liveness failure worth more than it saves:
    one crashed quorum leaves an ``open.json`` with no ``final.json``, that
    phase's reservation never clears, and every later question in the phase
    escalates -- the run looking correctly cautious while deciding nothing,
    which is the failure shape the recorded repository root is a standing rule
    against. The cost of NOT reserving is bounded and visible: at worst three
    dispatches spent on a question that finalisation then escalates.

    NEVER CALL THIS FROM INSIDE A HELD RUN LOCK. It takes the run lock for its
    whole body and ``select_lock_impl`` prefers POSIX ``flock``, which belongs
    to the open file description rather than to the process: a nested acquire
    in one process does not recurse, it BLOCKS against itself and then raises
    ``LockBusyError`` at the timeout. So this may not be called from inside
    ``locked_tracker_update``'s ``mutate``, nor from anything else already
    holding the run lock. No caller does today; ``finalize_quorum`` and P06's
    gate transitions are the two that will be tempted, and the failure they
    would see is a timeout on a run with no other worker in it.
    """
    run_dir = _run_path(run_dir)
    #: VALIDATED BEFORE THE LOCK, for ``locked_tracker_update``'s reason: a
    #: foreign, missing or malformed run is a read-only stop, and it must stop
    #: without this call first creating a lock file inside a directory that
    #: belongs to somebody else's tool.
    validate_run(run_dir)
    record_file = _record_path(question_record)
    try:
        text = record_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        #: ``ValueError`` IS THE EMBEDDED NUL, and it is the one this argument
        #: exists to survive: ``_record_path``'s docstring calls
        #: ``question_record`` the one argument a controller assembles from
        #: whatever the raising worker published, and ``Path`` accepts a NUL
        #: that ``open`` then refuses outside ``TrackerError``. ``_cited_file``
        #: spells the same triple for the same reason.
        raise QuorumError(
            f"no readable question record at {str(record_file)!r}: {exc}; a "
            "quorum cannot be opened on a question nobody wrote down") from exc
    record = parse_question(text)
    problems = check_admissible(record)
    if problems:
        #: Refused here rather than at the answers that come back. Three brains
        #: are dispatched at a question or none are, and an inadmissible
        #: question answered by three brains is three dispatches, a decision
        #: record and a run that has decided something it declared itself unable
        #: to ask.
        raise QuorumError(
            f"the question is inadmissible ({problems}); a quorum is never "
            "opened on a question the run has already established it may not "
            "ask")
    for owner in record["owners"]:
        if not _OWNER.fullmatch(owner):
            raise QuorumSchemaInvalid(
                f"owner {owner!r} is not an owner id; each brain's payload is "
                f"published as {_PAYLOAD_PREFIX}<owner>.json inside the "
                "question's own directory, so an owner carrying a separator "
                "writes that brain's payload somewhere no audit trail will "
                "look for it, one ending in a dot is a second owner's file on "
                f"Windows, and one longer than {_OWNER_MAX} characters fails at "
                "the write with the question record already published")
    qid = _record_qid(record)
    with _exclusive_lock(run_dir, timeout_s=timeout_s):
        return _open_under_lock(run_dir, qid, record, text)


# --- phase 2 of the record: the responses ----------------------------------
#
# A BRAIN'S ANSWER IS A SINGLE-ASSIGNMENT CELL. It is written once, under its
# own name, and never edited: a byte-identical redelivery is inert and a
# differing one is refused. That is the whole of what makes a response
# auditable -- the thing the controller graded is the thing the brain said --
# and it is why each answer is its own file rather than a list inside one. A
# crash between two responses loses nothing, a duplicate delivery costs
# nothing, and no write ever has to read what another brain said first.
#
# A SCHEMA-INVALID RESPONSE IS RECORDED, NOT DISCARDED AND NOT REPAIRED.
# Discarding it hides the malformation from the audit trail, so the quorum
# reads as two brains that answered rather than three that were asked;
# repairing it invents a vote. It is recorded with the violations that made it
# invalid, and it buys its owner exactly ONE re-dispatch.
#
# EXACTLY ONE, AND ONLY FOR AN INVALID ANSWER. Re-dispatching a brain whose
# answer was well-formed but unwelcome is the run collecting answers until it
# likes one, which is the failure this entire phase exists to prevent, so a
# second answer from a brain that already answered LEGALLY is refused rather
# than recorded. A second INVALID answer is a non-response: the quorum is
# incomplete and escalates. A brain can therefore force a human look and can
# never force an adoption.

#: The attempts one owner may ever occupy, and the whole of them. Attempt 1 is
#: the dispatch every owner gets; attempt 2 is the single re-dispatch a
#: schema-invalid answer buys. There is no attempt 3, and the bound is a
#: constant rather than a comparison written at each site because it is the
#: drift rule itself: a controller that could raise it would be a controller
#: that can re-ask until it likes the answer.
_MAX_ATTEMPTS = 2

#: What separates an owner from its attempt number in a response filename.
#:
#: TWO UNDERSCORES, AND THE PAIR IS NOT DECORATION. ``_OWNER`` admits ``_``, so
#: an owner may legally be called ``brain__1`` and the naive reading is that
#: ``brain__1__1.json`` is ambiguous. It is not, and the argument is worth
#: stating because the check it replaces would be worse than the hole: the
#: attempt suffix is drawn from ``{1, 2}``, so the only other reading of that
#: name would need an owner ``brain`` and an attempt ``1__1``, which this
#: module never writes and ``_owner_attempts`` never looks for. The map from
#: ``(owner, attempt)`` to a filename is therefore injective over exactly the
#: pairs that exist, and ``check_admissible`` already requires the three owners
#: distinct. Refusing an owner containing the separator would instead refuse an
#: id ``open_quorum`` had already accepted, leaving a quorum that opened and
#: can never be answered.
_ATTEMPT_SEPARATOR = "__"

#: The violation a response earns by answering under ANOTHER question's
#: identity. It is appended to ``validate_brain_response``'s list rather than
#: found inside it, because it is not a fact about the response: the schema
#: requires ``qid`` to be a non-empty string and nothing more, and WHICH string
#: is right is a fact about the quorum the response is being filed into.
#:
#: RECORDED INVALID RATHER THAN REFUSED, which is the opposite of how
#: ``_final_event`` and ``_opened_record`` treat the same disagreement, and the
#: difference is the remedy. A record filed under the wrong qid is corruption a
#: human repairs; a RESPONSE naming the wrong qid is a brain that answered the
#: wrong question, and the designed recovery for that is exactly the one
#: re-dispatch this file grants -- then an escalation. Refusing it outright
#: leaves the controller holding an answer it may neither record nor retry.
_QID_MISMATCH = "qid-mismatch"


def _quorum_directory(run_dir: Path, qid: str) -> Path:
    """The directory one question's whole record lives in."""
    return run_dir / _QUORUM_DIRNAME / qid


def _quorum_qid(qid) -> str:
    """One qid, held to the grammar ``derive_qid`` produces and nothing wider.

    ``qid`` NAMES A DIRECTORY THIS MODULE OPENS, and it is the argument a
    controller carries across a compaction and reassembles from a tracker cell.
    ``Path(...) / None`` raises ``TypeError``, outside ``TrackerError``;
    ``Path(...) / "../../.."`` names a directory outside the quorum tree, whose
    ``open.json`` would be read as this question's; and ``"a\\x00b"`` is the
    string ``Path`` accepts and every later read refuses with ``ValueError``,
    which is outside the family too and outside the ``(OSError, UnicodeError)``
    a read is usually written for.

    ``_QID`` is exactly what ``derive_qid`` emits -- twelve lowercase hex --
    so nothing a real run produces is refused and every one of those is.
    """
    if not _text(qid) or not _QID.fullmatch(qid.strip()):
        raise QuorumSchemaInvalid(
            f"qid {qid!r} is not a question id; a response filed under a name "
            "no derivation produces belongs to a question nobody asked, and "
            "the name is a directory this module opens")
    return qid.strip()


def _open_record(run_dir: Path, qid: str) -> dict:
    """``open.json``, or a stop that says nothing was ever dispatched.

    ABSENCE AND UNREADABILITY ARE TWO STATES, and the split is the one
    ``_decisions_text`` makes for ``decisions.md``. A name that is not there is
    a quorum that was never opened -- which is also the exact shape a BUDGET
    TRIP leaves behind, ``final.json`` written and nothing else -- and no
    response can belong to it, because no brain was dispatched to produce one.
    A name that IS there and cannot be read is corruption, and folding the two
    together would answer a half-written record with "raise the question
    again", which re-dispatches three brains at a question already in flight.

    ``lexists`` rather than ``exists`` for ``_decisions_text``'s reason: a
    dangling symlink and a symlink loop are names that exist and cannot be
    read, and reporting them as "never opened" is the fail-open direction.
    """
    path = _quorum_directory(run_dir, qid) / _OPEN_FILE
    if not os.path.lexists(path):
        raise QuorumError(
            f"quorum {qid} was never opened; a response has nothing to be "
            "recorded against, because nothing was dispatched to produce it")
    return _opened_record(path, qid)


def _record_owners(opened: dict, qid: str) -> list[str]:
    """The owner ids from ``open.json``, HELD TO ``_OWNER`` ON THE WAY BACK IN.

    ``open_quorum`` checks this grammar before it writes the file and checking
    it again here is not belt-and-braces, because the two calls guard different
    writes. There an owner became ``payload-<owner>.json``; here it becomes
    ``<owner>__<attempt>.json``, and a record naming ``../../../evil`` files a
    brain's answer outside the quorum tree and reads one back from outside it.
    ``open.json`` is a file in a directory a human may have edited or restored
    from a backup, and ``_opened_record`` validates the two fields an open
    record is CLASSIFIED by -- its status and its qid. Which strings may become
    filenames is a different question and it is asked here.

    THE COUNT IS CHECKED TOO. Exactly three brains per quorum, and a count is
    never reduced to fit capacity: a record naming two owners would let a
    two-brain quorum finalise, and one naming four would let a fourth brain's
    answer into the grouping.
    """
    owners = opened.get("owners")
    if not isinstance(owners, list) or len(owners) != _BRAINS:
        raise QuorumSchemaInvalid(
            f"the open record for {qid} names {owners!r}, not {_BRAINS} owners; "
            "a count is never reduced to fit capacity, so a record naming any "
            "other number describes a quorum this module never dispatched")
    for owner in owners:
        if not _text(owner) or not _OWNER.fullmatch(owner):
            raise QuorumSchemaInvalid(
                f"the open record for {qid} names owner {owner!r}, which is not "
                f"an owner id; each answer is published as <owner>"
                f"{_ATTEMPT_SEPARATOR}<attempt>.json inside the question's own "
                "directory, so an owner carrying a separator writes a brain's "
                "answer where no audit trail will look for it")
    if len(set(owners)) != len(owners):
        raise QuorumSchemaInvalid(
            f"the open record for {qid} names {owners!r}, in which two owners "
            "are one id; two brains sharing one response file is either a "
            "refused second write or one brain answering out of the other's "
            "bytes, and the quorum cannot say which brain said what")
    return list(owners)


def _bound_digest(opened: dict, qid: str, field: str, cost: str) -> str:
    """One sha256 an open record BINDS, read back and held to the grammar.

    ``opened[field]`` is the spelling this replaces and it is not a shorter
    version of this one: a record that omits the key raises ``KeyError``, which
    is outside ``TrackerError`` and so escapes every handler a controller has
    written -- and ``open.json`` is a file in a directory a human may have
    edited or restored from a backup, where a key going missing is the ordinary
    damage. ``_opened_record`` validates the two fields an open record is
    CLASSIFIED by, its status and its qid, and the digests it BINDS are a
    different question asked here.

    The value is checked against ``_SHA256`` rather than merely found, because
    a field holding ``true``, ``[]`` or ``"pending"`` compares unequal to every
    real digest and would therefore read as drift -- a quorum reported stale,
    routed to a human, on a record that had simply lost a field.
    """
    digest = opened.get(field)
    if not _text(digest) or not _SHA256.fullmatch(digest.strip()):
        raise QuorumSchemaInvalid(
            f"the open record for {qid} binds {field} {digest!r}, which is not "
            f"a digest; {cost}")
    return digest.strip()


def _dispatched_digest(opened: dict, qid: str) -> str:
    """The payload digest ``open.json`` bound AT DISPATCH, never a fresh one.

    READ RATHER THAN RECOMPUTED, and that is the whole reason this helper
    exists instead of a second call to ``payload_digest``.
    ``decisions-effective.md`` is ONE run-global mutable file that every
    ``open_quorum`` rewrites, so a digest computed now stops matching this
    quorum's as soon as any OTHER question is raised -- which is the ordinary
    state of a run with more than one question in it, not a rare one. A
    response record citing the fresh digest would attest that the brain
    answered a context the brain never saw, and nothing downstream could tell:
    the record would look perfectly well-formed and the drift the digest exists
    to expose would have been written out of the evidence.

    So a response is bound to the bytes its own dispatch was bound to. Whether
    those bytes still describe the run is a separate question with a separate
    answer -- ``classify_quorum``'s ``stale-context`` -- and it is answered by
    comparing these two digests, which is only possible while this one is the
    recorded one.
    """
    return _bound_digest(
        opened, qid, "payload_digest",
        "a response recorded against it would cite a dispatch nothing can be "
        "checked against")


def _response_name(owner: str, attempt: int) -> str:
    """One response's filename, spelled in exactly one place."""
    return f"{owner}{_ATTEMPT_SEPARATOR}{attempt}.json"


def _response_record(path: Path, qid: str, owner: str,
                     attempt: int) -> tuple[str, dict]:
    """One recorded response, with the digest of the bytes it was published as.

    THE DIGEST IS TAKEN OVER THE FILE'S OWN TEXT, not recomputed from the
    parse, so it is the value ``publish_immutable`` returned when it wrote the
    file. A redelivery that this function has just proved inert is answered
    with that value, and a caller comparing what it got the first time with
    what it got the second is comparing two statements about the same bytes.

    EVERY FIELD THE RECORD IS READ FOR IS VALIDATED, for ``_final_event``'s
    reason: the file is inside the run directory and a human may have edited
    it. The qid and the owner are re-derived from where the file SITS and
    compared, because a response directory can be copied or half-restored and a
    file filed under another brain's name is one brain's answer counted as
    another's. ``valid`` is required to AGREE with ``problems``: they are two
    spellings of one verdict, and a record claiming to be valid while listing
    violations is a malformed answer that would be clustered and adopted.

    THE SHAPE OF THE NAME IS ASKED BEFORE THE OPEN, for
    ``_require_regular_file``'s reason: ``_owner_attempts`` has already found
    this name to exist, so what is left to establish is that it can be read --
    and a FIFO answers that question by blocking rather than by failing.
    """
    what = f"{owner}'s attempt {attempt} for {qid}"
    _require_regular_file(path, what)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise QuorumError(f"unreadable {what} at {str(path)!r}: {exc}") from exc
    record = _loads(text, what)
    if not isinstance(record, dict):
        raise QuorumSchemaInvalid(
            f"{what} is a {type(record).__name__}, not an object; a recorded "
            "response is a verdict with an answer inside it, and a bare value "
            "is neither")
    stated = record.get("qid")
    if not _text(stated) or stated.strip() != qid:
        raise QuorumSchemaInvalid(
            f"{what} states qid {stated!r}; an answer filed under another "
            "question's identity is grouped, clustered and adopted for a "
            "question nobody asked it")
    named = record.get("owner")
    if not _text(named) or named != owner:
        raise QuorumSchemaInvalid(
            f"{what} states owner {named!r}; one brain's answer read back as "
            "another's is a quorum reporting agreement between a brain and "
            "itself")
    numbered = record.get("attempt")
    if isinstance(numbered, bool) or not isinstance(numbered, int) or numbered != attempt:
        raise QuorumSchemaInvalid(
            f"{what} states attempt {numbered!r}; the attempt is what says "
            "whether the single permitted re-dispatch has been spent, and a "
            "record disagreeing with its own filename spends it twice or never")
    if "response" not in record:
        raise QuorumSchemaInvalid(
            f"{what} holds no response; a verdict with nothing under it records "
            "that a brain was graded and not what it said")
    problems = record.get("problems")
    if not isinstance(problems, list) or not all(_text(item) for item in problems):
        raise QuorumSchemaInvalid(
            f"{what} states problems {problems!r}, which is not a list of "
            "violations; the violations are what a re-dispatch is owed for")
    valid = record.get("valid")
    if not isinstance(valid, bool) or valid != (not problems):
        raise QuorumSchemaInvalid(
            f"{what} states valid {valid!r} beside {len(problems)} violations; "
            "the two are one verdict spelled twice, and a record that calls "
            "itself valid while listing violations is a malformed answer "
            "clustered as a vote")
    return _digest(text), record


def _owner_attempts(run_dir: Path, qid: str, owner: str) -> list[tuple[str, dict]]:
    """Every attempt one owner has on record, in attempt order.

    ENUMERATED, NEVER GLOBBED, and the two readings of the directory differ in
    a way that matters. ``directory.glob(owner + "__*.json")`` numbers attempts
    by SORT POSITION, so a directory holding only ``brain-a__2.json`` -- an
    interrupted restore, a partially copied backup -- reports one attempt and
    calls it the first; the next answer is then published as attempt 2 over a
    file that is already attempt 2, and the single re-dispatch is either spent
    on a brain nothing shows was ever wrong or refused as conflicting evidence.
    A glob also interprets its own argument: ``*``, ``?`` and ``[`` are pattern
    syntax, and although ``_OWNER`` admits none of them today that is a
    property of a grammar one screen away rather than of this read.

    A GAP IS CORRUPTION AND IS A STOP. Attempts are numbered from one without
    holes, so anything else is a record whose first answer is missing, and
    pricing the second as the first is the same spend-it-twice fault.

    AND THE DIRECTORY IS ASKED ABOUT BEFORE THE NAMES INSIDE IT ARE, which is
    ``_require_regular_file``'s rule one level up. Every response FILE is held
    to its shape when it is read; the directory those names are joined onto was
    not held to anything, and ``lexists`` of a name under a REGULAR FILE, a
    dangling link, a symlink loop or a FIFO is ``False`` for every attempt of
    every owner. So a ``responses/`` that is any of those read as "no brain has
    answered" -- and this function feeds the one verdict whose entire value is
    who to dispatch. The run would order a fresh dispatch of brains whose legal
    answers are on record, which ``classify_quorum`` calls impossible by
    construction, and would find out three dispatches later when
    ``record_brain_response`` refused the reply with a write error. A FIFO here
    does not even hang -- nothing opens the directory -- so the whole family
    fails OPEN, silently, which is why it is asked about rather than discovered.

    ABSENCE IS STILL NOT ANSWERED HERE, exactly as ``_require_regular_file``
    leaves it: a name that is not there is the caller's own question, and
    ``record_brain_response`` reaches this before it has created the directory
    the first answer will live in.
    """
    directory = _quorum_directory(run_dir, qid) / _RESPONSES_DIRNAME
    if not directory.is_dir() and os.path.lexists(directory):
        raise QuorumSchemaInvalid(
            f"the responses directory for {qid} at {str(directory)!r} is a name "
            "this run directory carries and is not a directory; every attempt "
            "of every owner then reads as absent, so a quorum whose brains have "
            "answered reports that nobody has and orders their answers to be "
            "collected again")
    present = [attempt for attempt in range(1, _MAX_ATTEMPTS + 1)
               if os.path.lexists(directory / _response_name(owner, attempt))]
    if present != list(range(1, len(present) + 1)):
        raise QuorumSchemaInvalid(
            f"{owner} has attempts {present} on record for {qid}; attempts are "
            "numbered from one without gaps, and a record missing its first "
            "answer prices the second as the first -- the one re-dispatch spent "
            "on a brain nothing shows was ever wrong")
    return [_response_record(directory / _response_name(owner, attempt),
                             qid, owner, attempt) for attempt in present]


def record_brain_response(run_dir: str, *, qid: str, owner: str,
                          payload: object) -> str:
    """Phase 2: one immutable file per response, valid or not.

    ``payload`` IS ANY JSON VALUE, not a ``dict``, and the annotation is a
    departure from the pinned signature that is load-bearing rather than
    cosmetic. What a brain returned is exactly what is in question here: a
    reply that came back as a list, a string or ``null`` is a SCHEMA-INVALID
    answer that must be RECORDED as one -- ``validate_brain_response`` answers
    it with ``response-not-an-object`` and it buys the single re-dispatch --
    and a ``dict`` annotation describes a caller that has already filtered out
    the very shapes this function exists to record. The totality sweep depends
    on it too: every non-object it hands this call must land inside the
    ``TrackerError`` family, which it cannot do if the type says it never
    arrives.

    Returns the SHA256 OF THE PUBLISHED BYTES -- ``publish_immutable``'s return
    value, for ``publish_immutable``'s reason. The response file's path stays
    true when its contents change, and the contents changing is the one thing
    this record exists to prevent, so the identity handed back is the bytes. A
    redelivery this call proves inert is answered with the digest of the bytes
    already on disk, so two calls that stored one answer return one value.

    THE THREE THINGS THIS FUNCTION REFUSES, and why each is not the others:

    * A response from a brain this quorum never dispatched. Grouping counts
      answers, and a fourth answer is a fourth brain.
    * A second answer from a brain whose first was LEGAL. That is the run
      collecting answers until it likes one, and it is refused rather than
      recorded because recording it would put two votes from one brain in front
      of the grouping and leave it to choose.
    * A third answer, or a second from a brain that has already used its
      re-dispatch. A second invalid answer is a non-response: the quorum is
      incomplete and escalates, and the escalation is the remedy.

    A BYTE-IDENTICAL REDELIVERY IS INERT WHICHEVER ATTEMPT IT REPEATS, and the
    comparison is over THE BYTES THIS MODULE WRITES rather than over Python
    equality of the two values. ``_dumps`` is the only spelling this module
    stores JSON in, so comparing serializations answers exactly the question
    ``publish_immutable`` would answer a moment later. ``==`` answers a
    different one and gets it wrong wherever ``json`` holds fewer types than
    Python does: a TUPLE is stored and read back as a list, and a mapping keyed
    by ``1`` is stored and read back keyed by ``"1"``. Neither equals what was
    handed in, so under ``==`` the redelivery of a response already on disk is
    published a second time under a fresh attempt number -- the one re-dispatch
    burned on a duplicate, and the delivery after that refused outright, while
    the bytes on disk were identical all along and said so. (``NaN`` was the
    sharpest case here until ``_dumps`` stopped writing it at all; see there.)

    NO RUN LOCK IS TAKEN, deliberately. Each response is a single-assignment
    cell and ``os.link`` is the atomic arbiter of it, so two writers racing one
    filename produce one winner and one refusal with no window in which either
    sees a partial file -- which is the property a lock would be bought for.
    Taking one here would also make this uncallable from ``open_quorum``'s
    critical section and from ``locked_tracker_update``'s ``mutate``: the run
    lock is POSIX ``flock``, which belongs to the open file description rather
    than the process, so a nested acquire does not recurse, it blocks against
    itself until the timeout.
    """
    run_dir = _run_path(run_dir)
    #: VALIDATED BEFORE ANYTHING IS WRITTEN, for ``open_quorum``'s reason: a
    #: foreign, missing or malformed run is a read-only stop, and this call
    #: publishes a file into the directory it is handed.
    validate_run(run_dir)
    qid = _quorum_qid(qid)
    directory = _quorum_directory(run_dir, qid)
    opened = _open_record(run_dir, qid)
    owners = _record_owners(opened, qid)
    #: ``_member`` rather than a bare ``in``, and what it buys HERE is the
    #: string check rather than the hash safety: ``owners`` is a list, so
    #: ``owner in owners`` compares by equality and raises on nothing. The
    #: string check is the load-bearing half -- ``owner`` becomes a path
    #: component two lines down, and a list that happened to contain a list
    #: would otherwise name a file by its repr.
    if not _member(owner, owners):
        raise QuorumError(
            f"{owner!r} is not one of the {_BRAINS} owners of {qid} ({owners}); "
            "a quorum is three brains and an answer from a fourth is a fourth "
            "vote in a count that admits three")
    dispatched = _dispatched_digest(opened, qid)
    #: Serialized ONCE, ahead of every comparison and of the write, so a value
    #: this module cannot store stops here rather than after an attempt has
    #: been counted against the owner.
    serialized = _dumps(payload)
    attempts = _owner_attempts(run_dir, qid, owner)
    for digest, previous in attempts:
        if _dumps(previous["response"]) == serialized:
            return digest
    if os.path.lexists(directory / _FINAL_FILE):
        #: AFTER the redelivery check and not before it. A duplicate delivery
        #: of something already recorded changes nothing and must stay inert
        #: however late it arrives; growing the record the outcome was computed
        #: from is a different act, and it is refused.
        raise QuorumError(
            f"quorum {qid} is already finalised; an answer added after the "
            "outcome was computed is an answer the outcome was not computed "
            "from, and the record would no longer show what was graded")
    attempt = len(attempts) + 1
    if attempt > _MAX_ATTEMPTS:
        raise QuorumError(
            f"{owner} has already used its one re-dispatch for {qid}; a second "
            "invalid answer is a non-response, so the quorum is incomplete and "
            "escalates -- a brain may force a human look and never an adoption")
    if attempts and attempts[-1][1]["valid"]:
        raise QuorumError(
            f"{owner} has already answered {qid} and its answer was legal; the "
            "one re-dispatch is bought by a SCHEMA-INVALID response and by "
            "nothing else, because re-asking a brain whose answer was merely "
            "unwelcome is the run collecting answers until it likes one")
    problems = validate_brain_response(payload)
    stated = payload.get("qid") if isinstance(payload, dict) else None
    if not (_text(stated) and stated.strip() == qid):
        problems = problems + [_QID_MISMATCH]
    record = {
        "qid": qid,
        "owner": owner,
        "attempt": attempt,
        "valid": not problems,
        "problems": problems,
        #: The digest the DISPATCH bound, copied out of ``open.json``. See
        #: ``_dispatched_digest``: recomputing it here would record the context
        #: as it is now against an answer given to the context as it was.
        "payload_digest": dispatched,
        #: VERBATIM, never repaired and never normalised. The malformation is
        #: the evidence.
        "response": payload,
    }
    return publish_immutable(
        directory / _RESPONSES_DIRNAME / _response_name(owner, attempt),
        _dumps(record))


def quorum_needs_redispatch(run_dir: str, *, qid: str) -> list[str]:
    """The owners owed the single permitted re-dispatch, in dispatch order.

    Owed by exactly one thing: a first answer that was SCHEMA-INVALID. Not a
    late answer, not a weak one, not one the controller dislikes -- those are
    an incomplete quorum and a low rung respectively, and both have their own
    remedy. An owner that has already spent its re-dispatch is owed nothing
    more, whatever came back: a second invalid answer is a non-response, the
    quorum is incomplete, and it escalates.

    THE ORDER IS ``open.json``'s OWNER ORDER, which is the brain-index order
    ``build_payload`` was called in, so a caller re-dispatching owner ``n``
    reads the index it needs out of the position it found the name in.

    WHAT A RE-DISPATCH SENDS IS ALREADY ON DISK and is not rebuilt here. Each
    brain's bytes were published once as ``payload-<owner>.json`` and are
    immutable, so a re-dispatch re-sends that file; ``build_payload`` is pure
    with respect to the index and one ``payload_digest`` binds all three, which
    is what makes those bytes reproducible from ``(payload_digest, n)`` -- but
    only while nothing about the assignment is read from run state. Rebuilding
    the payload from the run AS IT IS NOW would hand the brain a different
    question from the one the digest attests to, and the answer would come back
    looking like an answer to the first.

    THE PROJECTION WILL USUALLY HAVE MOVED BY THEN, and this function does not
    hide that and does not act on it. ``decisions-effective.md`` is one
    run-global mutable file that every ``open_quorum`` rewrites, so an
    in-flight quorum's recorded ``payload_digest`` stops matching what a fresh
    computation produces as soon as another question is raised. That drift
    neither creates nor cancels a re-dispatch debt -- a malformed answer is
    malformed whatever the run has decided since -- so it is not consulted
    here. Naming it is ``classify_quorum``'s ``stale-context``, computed by
    comparing the recorded digest with a fresh one, and it stays computable
    precisely because this function reads neither.

    A FINALISED QUORUM OWES NOTHING, including one whose outcome is the
    terminal record a BUDGET TRIP wrote -- which has a ``final.json`` and no
    ``open.json`` at all, because nothing was ever dispatched. Reading the open
    record first would report that shape as a stop rather than as a question
    that was never asked.

    THE RUN IS VALIDATED FIRST even though this function writes nothing, and
    the global constraint is why: a foreign, missing, malformed or unknown
    schema is a read-only stop that preserves the directory, changes no files
    and DISPATCHES NOTHING. This is the one function whose entire return value
    IS who to dispatch, so honouring only the file-system half of that sentence
    -- writing nothing while naming three brains to send a question to -- is
    the sentence broken by the one route it was written for. A directory whose
    ``progress.md`` belongs to ``superb:pipeline``, or is gone, is not a run
    this module may read a debt out of.
    """
    run_dir = _run_path(run_dir)
    validate_run(run_dir)
    qid = _quorum_qid(qid)
    final_path = _quorum_directory(run_dir, qid) / _FINAL_FILE
    if os.path.lexists(final_path):
        #: Validated rather than merely counted, for the reason
        #: ``_open_under_lock`` validates it: a record restored under the wrong
        #: qid would answer for a question nobody asked, and here it would
        #: answer "nothing is owed" -- a quorum that never gets its brains back
        #: and never escalates either.
        _final_event(final_path, qid)
        return []
    owed = []
    for owner in _record_owners(_open_record(run_dir, qid), qid):
        attempts = _owner_attempts(run_dir, qid, owner)
        if len(attempts) == 1 and not attempts[0][1]["valid"]:
            owed.append(owner)
    return owed


#: Every verdict ``classify_quorum`` may return, and the whole of them. Named
#: so the suite can assert TOTALITY -- that each one is reachable by a run that
#: is in it for a reason no other shares -- because a classifier is exactly the
#: shape where a case can assert the state it expects while the function
#: arrives at it by falling through to a default.
_CLASSIFICATIONS = ("finalised", "ready-to-finalise", "awaiting-responses",
                    "redispatch", "stale-context")

#: Where a stale quorum goes, and it is not back to the brains.
_STALE_ROUTE = "stage-11"


def _context_digest(run_dir: Path) -> str:
    """The digest ``open.json`` records as ``context_digest``, spelled once.

    THE AUTHORITY, NOT THE PROJECTION, and the difference is the whole reason
    both are compared. ``open_quorum`` takes this digest over ``decisions.md``
    -- what the run had DECIDED when the brains were dispatched -- while
    ``payload_digest`` separately binds ``decisions-effective.md``, which is
    what the brains were shown.

    The two move at different moments. ``decisions.md`` moves the instant a
    decision lands; the projection is only rewritten by the NEXT
    ``open_quorum``, and ``project_decisions`` is deterministic, so a second
    raise that follows no decision rewrites it BYTE-IDENTICALLY and moves
    nothing at all. A classifier watching the projection alone therefore calls
    a quorum fresh for exactly as long as no other question happens to be
    raised, on a run that has already decided the thing under it -- and then
    reports the drift late, at a moment chosen by an unrelated question.

    ``_open_under_lock`` does not call this and must not: it reads
    ``decisions.md`` ONCE and digests the same text it projected, so its digest
    and its projection cannot describe two different moments. That the two
    spellings agree is asserted in the suite against a quorum raised a moment
    earlier -- a fresh quorum is never stale, which is the seam where a
    disagreement would surface.
    """
    return _digest(_decisions_text(run_dir))


def _live_owners(live_owners, owners: list, qid: str) -> list[str]:
    """The owners of THIS quorum a caller reports still working, in dispatch order.

    A LIVENESS REPORT IS A HINT AND THE FILES ARE THE AUTHORITY -- spec
    invariant 4 -- so this narrows and never widens. A name that is not one of
    this quorum's three is DROPPED rather than believed: believing it would
    hold a quorum open waiting for an agent no dispatch ever created, which is
    a run that never re-dispatches and never escalates either.

    THE CONTAINER IS CHECKED BEFORE IT IS ITERATED, and the two shapes it
    guards against are both things a controller reassembling state after a
    compaction really produces. ``None`` is the lost list, and ``for owner in
    None`` raises ``TypeError``, outside ``TrackerError``. A BARE STRING is the
    single-owner spelling, and it is worse than a crash: ``"brain-a" in
    "brain-abc"`` is a substring test, so one brain is reported live because
    another brain's name contains its own.

    ``_member`` IS NOT THE GUARD HERE AND THE POSITION IS WHY. The standing
    rule is about an agent-supplied VALUE being hashed by a bare ``in`` against
    a set; here the value is ``owner``, which ``_record_owners`` has already
    held to ``_OWNER``, and the agent-supplied side is the CONTAINER. A list
    membership test compares by equality and hashes nothing, so junk inside
    ``live_owners`` -- a list, a dict, ``None`` -- is answered ``False`` rather
    than raised on. The guard the container needed is the one above it.

    The order is ``open.json``'s owner order, which is ``build_payload``'s
    index order, for ``quorum_needs_redispatch``'s reason: a caller reads the
    index it needs out of the position it found the name in.
    """
    if not isinstance(live_owners, (list, tuple)):
        raise QuorumError(
            f"live_owners for {qid} is {type(live_owners).__name__}, not a "
            "list of owner ids; a bare string reports one brain live because "
            "another brain's name contains its own, and None leaves this "
            "module's exception family altogether")
    claimed = list(live_owners)
    return [owner for owner in owners if owner in claimed]


def classify_quorum(run_dir: str, *, qid: str, live_owners: list) -> dict:
    """What an interrupted quorum needs next. One state per interruption point.

    The three-phase record exists so that EVERY interruption point is
    classifiable from disk, and this is the function that proves it. Five
    states, each a different instruction to the controller, and the order they
    are asked in is the design rather than a convenience.

    ``finalised`` FIRST, AND A FINALISED RECORD IS NEVER RECOMPUTED. A second
    run with different brains gives a different answer about as often as the
    rung gap is narrow, and the controller has no principled way to prefer
    either. ``final.json`` is also the ONE file a budget trip leaves behind --
    no ``open.json``, no payloads, nothing dispatched -- so reading the open
    record first would report that shape as corruption.

    ``stale-context`` SECOND, ahead of every state that would act on the
    answers. Waiting, re-dispatching and computing an outcome are all acts on
    behalf of a question the run has since moved past, and re-deciding on
    resume is precisely the silent-divergence failure this design exists to
    prevent. So the quorum is NOT re-opened and NOT finalised; it is flagged to
    stage 11 and a human sees it. A mismatch is NOT evidence of a crash -- see
    ``_context_digest`` -- it is the ordinary consequence of a decision landing
    under a quorum that was already in flight, which is the normal shape of any
    run with more than one question in it.

    TWO DIGESTS ARE COMPARED, because they catch two different facts at two
    different moments and neither subsumes the other. ``context_digest``
    against ``decisions.md`` catches a decision landing, at the instant it
    lands. ``payload_digest`` against a fresh computation catches the file the
    brains were told to READ being rewritten under them -- including by a hand
    edit of ``decisions-effective.md``, which ``decisions.md`` cannot see at
    all. ``moved`` names which.

    Then the record on disk decides between the last three. Each owner is in
    exactly one of three conditions and the conditions are not headcount:

    * TERMINAL -- its last answer was legal, or it has spent both attempts. A
      second invalid answer is a NON-RESPONSE, so an owner that spent its one
      re-dispatch is terminal too: the quorum is incomplete and escalates, and
      the escalation is the remedy. So ``ready-to-finalise`` means "no dispatch
      is owed, compute the outcome", and the outcome it computes may well be an
      escalation.
    * OWED -- exactly one answer and it was SCHEMA-INVALID. That is the single
      permitted re-dispatch, and it is owed WHATEVER the liveness report says,
      because a brain that has already delivered is not working on this
      question: a report naming it is stale, and the file is the authority.
    * UNANSWERED -- nothing on record. Live, that is ``awaiting-responses`` and
      the controller waits. Not live, the brain died before answering and its
      payload must be re-sent.

    A BRAIN THAT ANSWERED LEGALLY IS NEVER NAMED IN A ``redispatch``, and this
    is not a preference. ``record_brain_response`` REFUSES a second answer from
    a brain whose first was legal -- that is the run collecting answers until
    it likes one -- so naming it would order a dispatch whose answer can never
    be recorded: three brains spent, one reply refused outright, and a quorum
    no further forward. "Discard the partials and re-send" is impossible here
    by construction: every response file is a single-assignment cell.

    THE BYTES A RE-DISPATCH SENDS ARE THE DISPATCHED ONES. ``payload_digest``
    in the verdict is read out of ``open.json``, never recomputed, so it proves
    the identity of what is already on disk as ``payload-<owner>.json``; a
    fresh digest would attest to a question the brain was never asked.

    THE RUN IS VALIDATED FIRST even though nothing here writes. A foreign,
    missing, malformed or unknown schema is a read-only stop that preserves the
    directory, changes no files and DISPATCHES NOTHING -- and this function's
    return value is an instruction to dispatch, so honouring only the
    file-system half of that sentence breaks it by the one route it was written
    for.
    """
    run_dir = _run_path(run_dir)
    validate_run(run_dir)
    qid = _quorum_qid(qid)
    directory = _quorum_directory(run_dir, qid)
    final_path = directory / _FINAL_FILE
    #: ``lexists`` rather than ``exists``, for ``_open_record``'s reason: a
    #: dangling symlink and a symlink loop are names this directory CARRIES,
    #: and answering them with "not settled yet" tells the controller a
    #: finalised quorum still owes its owners a dispatch.
    if os.path.lexists(final_path):
        #: Validated rather than merely found: a record restored under the
        #: wrong qid would hand back an outcome for a question nobody asked,
        #: and hand it back as the one verdict that forbids ever looking again.
        #:
        #: ONE READ FOR BOTH HALVES. ``status`` and ``decision_id`` are the
        #: cells this verdict was validated against and ``result`` is the whole
        #: record it reports; reading the file twice would let the two describe
        #: different bytes on a name a human may be restoring, so the verdict
        #: could say ``adopted`` about a record that no longer does.
        event, record = _final_event(final_path, qid)
        return {
            "state": "finalised",
            "qid": qid,
            "recompute": False,
            "status": event["status"],
            "decision_id": event["decision_id"],
            #: The whole record, not the budget's four cells: the caller needs
            #: the winner it is being told not to re-litigate.
            "result": record,
        }

    opened = _open_record(run_dir, qid)
    owners = _record_owners(opened, qid)
    #: Screened before the digests, so a lost liveness list is refused for what
    #: it is rather than after a page of file reads.
    live = _live_owners(live_owners, owners, qid)
    recorded_context = _bound_digest(
        opened, qid, "context_digest",
        "the drift a resumed quorum is judged by is the distance between that "
        "value and the audit trail as it stands, and a record binding no such "
        "value cannot be judged stale or fresh")
    dispatched = _dispatched_digest(opened, qid)

    current_context = _context_digest(run_dir)
    current_payload = payload_digest(qid, run_dir=run_dir)
    moved = []
    if recorded_context != current_context:
        moved.append("decisions")
    if dispatched != current_payload:
        moved.append("projection")
    if moved:
        return {
            "state": "stale-context",
            "qid": qid,
            "reopen": False,
            "route": _STALE_ROUTE,
            "moved": moved,
            "recorded_context": recorded_context,
            "current_context": current_context,
            "recorded_payload": dispatched,
            "current_payload": current_payload,
        }

    owed, unanswered, terminal = [], [], []
    for owner in owners:
        attempts = _owner_attempts(run_dir, qid, owner)
        if not attempts:
            unanswered.append(owner)
        elif attempts[-1][1]["valid"] or len(attempts) >= _MAX_ATTEMPTS:
            terminal.append(owner)
        else:
            owed.append(owner)

    if len(terminal) == len(owners):
        return {"state": "ready-to-finalise", "qid": qid,
                "owners": list(terminal)}
    #: Rebuilt in ``open.json``'s order rather than concatenated, so the
    #: position a caller reads brain n's index out of is the dispatch order in
    #: every verdict.
    pending = [owner for owner in owners
               if owner in owed or (owner in unanswered and owner not in live)]
    if pending:
        return {
            "state": "redispatch",
            "qid": qid,
            "owners": pending,
            #: The two debts kept apart, because they are owed for different
            #: reasons and a later stage prices them differently: ``owed`` is
            #: the single permitted re-dispatch a SCHEMA-INVALID answer bought,
            #: and it is exactly what ``quorum_needs_redispatch`` returns.
            "owed": list(owed),
            "unanswered": [owner for owner in pending if owner in unanswered],
            "payload_digest": dispatched,
        }
    #: Nothing is pending only if nothing is owed and every unanswered owner is
    #: live, and something is unanswered because not every owner was terminal.
    #: So this is reached by one state of the record and is not a fall-through.
    #:
    #: Ordered by ``live`` rather than by ``unanswered``, which is the one
    #: place ``_live_owners``' ordering is load-bearing: the two agree only
    #: because that helper rebuilt the report in ``open.json``'s order, and a
    #: caller reads brain n's index out of the position it found the name in.
    return {"state": "awaiting-responses", "qid": qid,
            "owners": [owner for owner in live if owner in unanswered]}


# --- phase 3 of the record: clustering, strictness, and adoption -----------
#
# This is where a quorum's answers become a DECISION, and it is the only place
# in the run where a machine may bind the run to something no human said. Four
# rules meet here and every one of them is a rule a reasonable engineer would
# "simplify" into a bug.
#
# A CLUSTER'S RUNG IS ITS HIGHEST MEMBER'S, never the mean and never a
# headcount. Averaging punishes a correct lone expert -- the one brain that
# read the spec, dragged down by the two that guessed -- and it lets two weak
# agreers manufacture a majority out of nothing either of them could show.
#
# SPREAD IS MEASURED BY LADDER POSITION AND BY NOTHING ELSE. Where more than
# one cluster exists the winner's rung must be STRICTLY HIGHER than the
# runner-up's: ``RUNG_ORDER.index(winner) < RUNG_ORDER.index(runner_up)``, with
# no float anywhere in it. Equal rungs never adopt even when both clear the
# floor, because two brains reading the same code and reaching different
# answers from evidence of the same quality is exactly where a numeric margin
# would manufacture a winner out of noise. Unanimity is the one case with no
# runner-up, so the test is vacuous there and the floor alone governs.
#
# THERE IS NO SEPARATE THREE-WAY-SPLIT RULE. Rung strictness subsumes it, and
# it handles the case the old unconditional rule got wrong: one brain citing
# the spec against two speculating SHOULD win, and an escalation there throws
# away the only grounded answer in the room.
#
# AND ORDER IS LOAD-BEARING. Every response's ``effective_rung`` is recomputed
# from disk BEFORE any comparison between responses. Run the resolution
# afterwards and a top-rung response with a dangling citation wins at 0.95 on a
# claim no file supports -- and is then recorded as the rung it declared rather
# than the rung it earned.


def cluster_rung(cluster: list) -> str:
    """A cluster's rung: its HIGHEST member rung, as a name.

    NEVER THE MEAN, never a sum, never headcount-weighted. Averaging punishes a
    correct lone expert and lets two weak agreers manufacture a majority; a sum
    IS a headcount wearing the ladder's clothes.

    ``RUNG_ORDER`` is highest-first, so the highest rung is the SMALLEST index
    and ``min`` over positions is the maximum over rungs. Positions, never
    values: a comparison between two floats here would be the numeric threshold
    this phase exists to keep out, arriving one function away from the place it
    is forbidden.

    Every member's rung is held to the enum on the way in. ``RUNG_ORDER.index``
    raises ``ValueError`` on anything else -- outside ``TrackerError``, so it
    escapes every handler a controller has written -- and this function is
    public: a caller assembles the mapping it is handed.
    """
    if not isinstance(cluster, list) or not cluster:
        raise QuorumError(
            f"an empty cluster has no rung ({cluster!r}); a cluster is the "
            "members that agreed, and nobody agreeing is not an answer priced "
            "at the bottom of the ladder -- it is no answer at all")
    positions = []
    for member in cluster:
        if not isinstance(member, dict):
            raise QuorumSchemaInvalid(
                f"cluster member {member!r} is {type(member).__name__}, not an "
                "object; a member with no readable rung cannot be the maximum "
                "and cannot be shown not to be")
        rung = member.get("effective_rung")
        if not _is_rung(rung):
            raise QuorumSchemaInvalid(
                f"cluster member states effective_rung {rung!r}, which is not "
                "one of the five; a rung outside the enum is never defaulted, "
                "because the value that would arrive is legal and the door it "
                "came through is not")
        positions.append(RUNG_ORDER.index(rung))
    return RUNG_ORDER[min(positions)]


def _answer_key(payload: dict) -> str:
    """One response's answer key, held to being an answer.

    ``payload["answer_key"]`` is the spelling this replaces: ``group_responses``
    is public and a caller assembles what it is handed, so a key that is a list
    compares unequal to every other key and silently makes its response its own
    cluster -- an agreement that never happened, reported as a disagreement.
    """
    if not isinstance(payload, dict):
        raise QuorumSchemaInvalid(
            f"a response is {type(payload).__name__}, not an object; there is "
            "no answer in it to compare and no consequence to compare it by")
    key = payload.get("answer_key")
    if not _text(key):
        raise QuorumSchemaInvalid(
            f"answer_key {key!r} is not an answer; a blank key names no option, "
            "so it matches no other answer and clusters alone -- a brain "
            "reported as disagreeing with two it never spoke against")
    return key.strip()


def _consequence_subjects(payload) -> dict:
    """What a response ASSERTS, as the ``(kind, subject) -> value`` mapping.

    ``_candidate_consequences`` rather than a second reader, and the reuse is
    the point: it is the gate ``check_contradiction`` already puts a candidate
    through, so a consequence legal in grouping and illegal in the
    contradiction check cannot exist. It screens through
    ``_consequence_problems`` -- the same gate ``validate_brain_response``
    uses -- refuses the empty list, and refuses a response that asserts one
    subject twice, which would otherwise agree with whichever other answer
    happened to match the value the dict kept.
    """
    if not isinstance(payload, dict):
        raise QuorumSchemaInvalid(
            f"a response is {type(payload).__name__}, not an object; it "
            "asserts nothing about the repository, so it agrees with nothing "
            "and conflicts with nothing")
    return _candidate_consequences(payload.get("consequences"))


def _same_answer(left: dict, right: dict, options_supplied: bool):
    """``True``, ``False``, or ``None`` when the two describe different things.

    NAMED OPTIONS COMPARE BY KEY, because that is what a named option is: the
    question supplied the vocabulary and an answer either used it or did not.

    PROSE ANSWERS COMPARE BY CONSEQUENCE, because two sentences that mean the
    same thing are not comparable as text and this module interprets no text.
    Two prose answers agree only where they assert the same value for something
    they both spoke about. Sharing NO subject is the third verdict and not a
    fourth kind of agreement: two answers about different files have neither
    agreed nor conflicted, and folding that into either is the fail-open
    direction -- ``True`` manufactures a cluster out of silence, ``False``
    manufactures a disagreement out of it.
    """
    if options_supplied:
        return _answer_key(left) == _answer_key(right)
    here = _consequence_subjects(left)
    there = _consequence_subjects(right)
    shared = sorted(set(here) & set(there))
    if not shared:
        return None
    for key in shared:
        if here[key] != there[key]:
            return False
    return True


def group_responses(responses: list, *, options_supplied: bool) -> tuple:
    """Cluster the answers. WHEN IN DOUBT THEY ARE DIFFERENT ANSWERS.

    Returns ``(clusters, verdicts)``: clusters are lists of INDEXES into
    ``responses``, in the order the responses were dispatched, and ``verdicts``
    maps each ``(i, j)`` pair with ``i < j`` to ``True``, ``False`` or ``None``.

    A response joins a cluster only when it is ``True`` against EVERY member of
    it. ``None`` is not agreement and neither is a majority of the members: an
    answer that agrees with one member and describes something else entirely to
    another has not joined that cluster, and admitting it would let two answers
    that never touched be counted as having agreed through a third. Different
    pushes toward escalation, which is the safe direction.

    ``options_supplied`` IS A BOOL AND IS NOT TRUTH-TESTED FROM A FILE. It
    decides which of two incomparable comparisons is made, so ``"no"`` read
    back off disk -- truthy -- would compare prose answers by an answer key
    none of them was asked to supply, and three distinct answers would cluster
    as one.
    """
    if not isinstance(responses, list):
        raise QuorumSchemaInvalid(
            f"responses are {type(responses).__name__}, not a list; a string "
            "walks one character at a time and anything else walks not at all, "
            "and a quorum over nothing agrees with itself")
    if not isinstance(options_supplied, bool):
        raise QuorumSchemaInvalid(
            f"options_supplied is {options_supplied!r}, not a bool; it selects "
            "between comparing answer keys and comparing consequences, and a "
            "truthy string read back off disk compares prose answers by a key "
            "none of them was asked to supply")
    verdicts = {}
    for first in range(len(responses)):
        for second in range(first + 1, len(responses)):
            verdicts[(first, second)] = _same_answer(
                responses[first], responses[second], options_supplied)
    clusters: list = []
    for index in range(len(responses)):
        for cluster in clusters:
            if all(verdicts[(member, index)] is True for member in cluster):
                cluster.append(index)
                break
        else:
            clusters.append([index])
    return clusters, verdicts


def _best_member(cluster: list) -> dict:
    """The member whose own rung IS the cluster's rung.

    The cluster's answer is recorded from ONE member's payload -- its answer
    text, its consequences, its anchors -- and it must be the member that
    earned the rung the cluster was ranked at. Taking the first member instead
    would record a ``speculation``'s wording and anchors under a ``specified``
    cluster's rung: an audit trail stating that the run adopted an answer on
    grounding the recorded answer never had.

    ``min`` over ladder POSITION, so ties keep dispatch order, and never over
    ``RUNGS`` values: a float comparison here is the numeric threshold this
    phase forbids, one helper away from where it is forbidden.
    """
    return min(cluster,
               key=lambda member: RUNG_ORDER.index(member["effective_rung"]))


# --- the adoption floor ----------------------------------------------------
#
# Individual confidence claims are often unfalsifiable; the DISTRIBUTION is
# not. A run whose adopted decisions are almost all top-rung is either working
# on an exceptionally well-specified problem or grading itself generously, and
# the second is far more common. So after enough adoptions to mean anything,
# a mean above the inflation bar raises the floor one rung for the rest of the
# run -- and the adjustment is RECORDED, because a bar that moved with no
# record of moving is a bar a later reader cannot check.
#
# IT NEVER FALLS. A ratchet that could relax is not a ratchet: the run would
# raise its own bar on the adoptions that inflated it and lower it again on the
# next honest answer, which is the self-serving move every constant in this
# section is frozen against.

#: Where the raised floor is recorded, inside the run's own quorum tree.
_FLOOR_FILE = "floor.json"

#: The floor this run starts at, DERIVED from ``ADOPTION_FLOOR`` rather than
#: re-typed beside it. Two spellings of one bar drift the day either is edited,
#: and the drift is invisible: both values are legal rungs.
_FLOOR_RUNG = next(name for name in RUNG_ORDER if RUNGS[name] == ADOPTION_FLOOR)

#: How many adoptions a distribution needs before it is a distribution. Below
#: this, one top-rung answer is a sample and not a signal.
_INFLATION_SAMPLE = 5

#: The mean above which the run is grading itself generously. This is NOT the
#: spread threshold standing rule 1 forbids and the difference is not a
#: technicality: that rule is about comparing two CLUSTERS, where a float
#: margin manufactures a winner out of noise. This compares no clusters and
#: decides no question -- it reads one run's own record of itself and moves a
#: bar in one direction only.
_INFLATION_MEAN = 0.90


def _persisted_floor(path: Path) -> str:
    """The floor this run has already raised itself to, or the schema floor.

    ``lexists`` RATHER THAN ``exists``, for ``_decisions_text``'s reason and
    with a sharper consequence. ``exists()`` is false for a directory, a
    dangling symlink, a symlink loop and a FIFO, and answering any of them with
    "nothing recorded" silently RESETS the floor to the schema minimum -- the
    one direction this ratchet exists to make impossible, reached by a name the
    run directory carries rather than by a decision anybody made.

    AND A RECORDED FLOOR BELOW THE SCHEMA FLOOR IS A STOP, not a value to be
    clamped. ``floor.json`` is a file in a directory a human -- or a controller
    -- may edit, and ``{"floor_rung": "speculation"}`` is the whole of the
    self-serving move: a machine that can lower its own adoption bar has no
    adoption bar. Clamping it silently would leave the file saying one thing
    and the run doing another, so the file is refused and named.
    """
    if not os.path.lexists(path):
        return _FLOOR_RUNG
    record = _read_json(path, "the recorded adoption floor")
    if not isinstance(record, dict):
        raise QuorumSchemaInvalid(
            f"{_FLOOR_FILE} holds a {type(record).__name__}, not the recorded "
            "floor; a bar that cannot be read is a bar nothing is held to")
    rung = record.get("floor_rung")
    if not _is_rung(rung):
        raise QuorumSchemaInvalid(
            f"{_FLOOR_FILE} records floor_rung {rung!r}, which is not one of "
            "the five; a floor outside the ladder admits every answer or none "
            "of them, and nothing downstream can say which")
    if RUNG_ORDER.index(rung) > RUNG_ORDER.index(_FLOOR_RUNG):
        raise QuorumSchemaInvalid(
            f"{_FLOOR_FILE} records floor_rung {rung!r}, which is BELOW the "
            f"schema floor {_FLOOR_RUNG!r}; the floor rises and never falls, "
            "and a run that can write itself a lower bar has no bar -- this "
            "file is refused rather than clamped, so it cannot say one thing "
            "while the run does another")
    return rung


def _adopted_rungs(run_dir: Path) -> list:
    """The winning rung of every adoption this run has recorded, from the records.

    NOT FROM ``quorum_events``. That function is the BUDGET PROJECTION and says
    so: four cells, and ``winner`` is not one of them, because the budget has no
    stake in how well-grounded an adoption was. Reading the rung out of it is a
    ``KeyError`` -- outside ``TrackerError`` -- and widening it would make the
    budget's screening claim cover a field the budget never reads.

    ``_final_event`` still does the reading, so the qid, the status and the
    phase are validated exactly as the budget validates them, and the rung is
    taken from the same single read rather than from a second one.
    """
    root = run_dir / _QUORUM_DIRNAME
    if not root.is_dir():
        return []
    rungs = []
    for final in sorted(root.glob("*/" + _FINAL_FILE)):
        event, record = _final_event(final, final.parent.name)
        if event["status"] != _CHARGED_STATUS:
            continue
        winner = record.get("winner")
        if not isinstance(winner, dict) or not _is_rung(winner.get("rung")):
            raise QuorumSchemaInvalid(
                f"{event['qid']}: an adopted quorum records winner {winner!r}, "
                "which states no rung; the floor is raised by the distribution "
                "of what this run adopted, and an adoption that reports no "
                "grounding is one the distribution cannot see")
        rungs.append(winner["rung"])
    return rungs


def current_floor(run_dir: str) -> dict:
    """The adoption floor for this run. It RISES on inflation and never falls.

    Returns the floor as a name and as its value; every comparison against it
    in this module is made by ladder POSITION, and the value is reported for
    the terminal report a human reads.

    THE ADJUSTMENT IS WRITTEN DOWN. A bar that moved with no record of moving
    is a bar nobody can check afterwards, and the one question a reader of a
    refused adoption has is what it was measured against.
    """
    path = _run_path(run_dir) / _QUORUM_DIRNAME / _FLOOR_FILE
    rung = _persisted_floor(path)
    adopted = _adopted_rungs(_run_path(run_dir))
    if len(adopted) >= _INFLATION_SAMPLE:
        mean = sum(RUNGS[name] for name in adopted) / len(adopted)
        position = RUNG_ORDER.index(rung)
        raised = RUNG_ORDER[max(0, position - 1)]
        if mean > _INFLATION_MEAN and RUNG_ORDER.index(raised) < position:
            rung = raised
            _write_run_file(
                path,
                _dumps({"floor_rung": rung, "raised_after": len(adopted),
                        "mean": round(mean, 4)}),
                "the recorded adoption floor")
    return {"floor_rung": rung, "floor_value": RUNGS[rung]}


# --- phase 3: the outcome --------------------------------------------------

#: The status a quorum whose three answers were not about one question carries
#: is ``_UNDECIDABLE``, and it is DEFINED WITH ``_QuorumOutcome`` rather than
#: here. It is deliberately not ``escalated`` -- a question the quorum found
#: undecidable and a question it escalated are different facts, and the
#: terminal report keys off which -- and the ``## Quorum`` row has to be able to
#: say so, which made the word part of that column's vocabulary rather than
#: part of this section's private state. Read back from there so the status
#: this writes and the grammar that admits it cannot come apart.

#: ``rejected-contradicts-<provenance>``, built from the provenance of the
#: record that was contradicted so the two statuses cannot come apart from the
#: two provenances.
_REJECTED_PREFIX = "rejected-contradicts-"

#: The transition id one finalisation replays against.
_QUORUM_TRANSITION = "quorum-"

#: Two blockers, not one. One brain unable to proceed is a brain; two is the
#: question. Named so a comparison written at the site cannot drift from it.
_BLOCKED_QUORUM = 2

def _opened_token(opened: dict, qid: str, field: str, cost: str) -> str:
    """One ``open.json`` cell that must be a single token, read back and held.

    ``opened[field]`` is the spelling this replaces, for ``_bound_digest``'s
    reason: a record that omits the key raises ``KeyError``, outside
    ``TrackerError``. The grammar matters as much as the presence -- the phase
    is copied into ``final.json`` and ``_final_event`` refuses a phase that is
    not one token, so an open record carrying junk here would publish a final
    record every later read of this run stops on.
    """
    value = opened.get(field)
    if not _text(value) or not _TOKEN.fullmatch(value.strip()):
        raise QuorumSchemaInvalid(
            f"the open record for {qid} states {field} {value!r}, which is not "
            f"one token; {cost}")
    return value.strip()


def _opened_lineage(opened: dict, qid: str, field: str) -> str | None:
    """One ``open.json`` lineage cell, read back as a token or as absent.

    ``None`` IS A FIRST-CLASS ANSWER HERE and is what every ordinary quorum
    records, which is why this is not ``_opened_token``: that helper refuses an
    absent value, and absence is the normal case for a question nobody
    challenged. What is refused is a value that is PRESENT and not a token --
    the shape that would be copied into ``final.json`` and stop every later
    read of the run.
    """
    value = opened.get(field)
    if value is None:
        return None
    if not _text(value) or not _TOKEN.fullmatch(value.strip()):
        raise QuorumSchemaInvalid(
            f"the open record for {qid} states {field} {value!r}, which is "
            "neither absent nor one token; a lineage cell that cannot be read "
            "is a challenge whose target nothing can resolve")
    return value.strip()


def _opened_bar(opened: dict, qid: str) -> str | None:
    """The raised bar this quorum was opened against, or ``None``.

    THE ONE CELL A RUN WOULD GAIN BY LYING ABOUT. ``open.json`` sits inside the
    run directory, and ``{"raised_bar_rung": "speculation"}`` is the whole of
    the self-serving move: a challenge judged against a bar below the floor
    adopts on anything. So the value is held to the ladder rather than read for
    truthiness, exactly as ``_persisted_floor`` holds ``floor.json`` -- and,
    like that file, it is REFUSED rather than clamped, because a clamped record
    says one thing while the run does another.

    IT IS NOT RE-DERIVED FROM ``decisions.md`` HERE, and that is a ruling
    rather than an omission: the bar is a fact about the trail AS IT STOOD when
    the three brains were dispatched, and a trail that has moved since is
    already caught -- ``_stale_moves`` compares ``context_digest`` against
    ``decisions.md`` and escalates the whole finalisation before any bar is
    consulted. Re-reading it here would answer a question staleness has
    already refused to let be asked.
    """
    rung = opened.get("raised_bar_rung")
    if rung is None:
        return None
    #: ``ADOPTABLE``, NOT THE WHOLE LADDER, and the difference is the whole
    #: point of asking. ``speculation`` IS a legal rung, so a ladder check
    #: passes it -- and a bar of ``speculation`` is below the floor, which
    #: every answer clears. The bar is the rung of a decision that was
    #: ADOPTED, and only two rungs can ever have been.
    if not _member(rung, ADOPTABLE):
        raise QuorumSchemaInvalid(
            f"the open record for {qid} states raised_bar_rung {rung!r}, and "
            f"only {sorted(ADOPTABLE)} can have been adopted; a bar below the "
            "floor is cleared by every answer, which is a run writing itself "
            "permission in the one file that says what it must beat")
    return rung


def _opened_blocks(opened: dict, qid: str) -> list:
    """What this question BLOCKS, read back off the open record.

    It becomes the decision record's ``Scope``, which is the cell a task reads
    to find out whether a decision applies to it. A scope assembled out of
    whatever the file happened to hold would name tasks that do not exist, or
    none at all, in a field nothing downstream validates.
    """
    blocks = opened.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise QuorumSchemaInvalid(
            f"the open record for {qid} states blocks {blocks!r}; a question "
            "that blocks nothing was never admissible, and a decision recorded "
            "with no scope applies to every task or to none")
    for entry in blocks:
        if not _text(entry) or not _TOKEN.fullmatch(entry.strip()):
            raise QuorumSchemaInvalid(
                f"the open record for {qid} states block {entry!r}, which is "
                "not a task token; the scope cell is read to decide whether a "
                "decision binds a task, and one that names nothing binds none")
    return [entry.strip() for entry in blocks]


def _minted_axis(axis: str, qid: str, tracker: dict) -> str:
    """The axis THE DECISION RECORD carries, minting one where none was tagged.

    A question raised after the stage-03 gate closed is asked on the reserved
    literal ``new``, and it is ADOPTED LIKE ANY OTHER -- the fixture holds an
    adopted ``new``-axis row, the suite pins the literal as legal in the
    tracker, and there is no escalation reason token for it anywhere in the
    gate chain. Escalating it would be a schema change dressed as a policy
    answer, and since stage 03 raises at most four questions, ``new`` is the
    default for everything raised mid-run: it would hand the human the common
    case in a skill whose entire point is not doing that.

    THE MINT IS THE QUESTION'S OWN BARE QID. Not a derived slug -- nothing in
    this repository derives one, so the name would be agent-invented and
    unrecomputable, which is the failure ``derive_qid`` is written against: a
    name no derivation can reproduce is a question that can never be found
    again, and ``_ensure_decision_recorded`` must be able to recompute this
    byte-identically to stay idempotent. And not ``axis-<qid>``, because the
    fixture's own stage-03 ids include ``axis-2``: that prefix namespace is
    already occupied by the very ids a minted axis must not collide with.

    THE ROW AND THE RECORD LEGALLY DISAGREE, and both are right. The ``##
    Quorum`` row records WHAT WAS ASKED and keeps ``new`` forever;
    ``_validate_quorum`` closes that cell to the stage-03 question ids plus the
    literal, so a minted axis could not be written there anyway. The decision
    record records THE AXIS THAT QUESTION OPENED. So this is returned ALONGSIDE
    the asked axis rather than replacing it.

    THE COLLISION IS CLOSED HERE, and it is the fail-FALSE twin of the fail-open
    the reservation exists to prevent: a minted axis that happened to equal a
    stage-03 question id would bucket this decision with that axis's decisions
    and manufacture a contradiction that does not exist -- a run halted on a
    disagreement nobody had. The writer already holds the tracker.

    THE REFUSAL IS RAISED HERE AND CAUGHT BY ``_finalisation_base``, which
    turns it into the ``unmintable-axis`` escalation. "Mint one or refuse" is
    this helper's whole contract and a sentinel return would file the refusal
    in the same cell as a legal axis, so the raise stays; the CONSEQUENCE is
    what changed. Raising out of ``finalize_quorum`` wedged the quorum for
    ever -- ``ready-to-finalise``, no ``final.json``, every call raising, no
    re-dispatch owed and nothing else that could move it -- and refusing to
    ADOPT is not the same act as refusing to FINISH. Only the first is what the
    fail-false property above needs: an escalation adopts nothing and writes no
    decision record, so it buckets nothing either, and unlike an exception it is
    counted, inspectable and reaches the terminal report. The ruling, and the
    measurement behind it, is P03's in
    ``docs/superpowers/plans/pipeline-auto/phase-03-quorum-contract.md``.

    KNOWN AND ACCEPTED: two questions that each open the SAME conceptual axis
    mint different axes and are never compared. That is bounded by the drift
    budget and the depth cap, and it fails silent-but-inspectable -- the axis
    still resolves to the question that opened it -- rather than fail-open.
    """
    if axis != _RESERVED_AXIS:
        return axis
    registered = {row["id"] for row in tracker["questions"]}
    if qid in registered:
        raise QuorumSchemaInvalid(
            f"the axis minted for {qid} collides with stage-03 question id "
            f"{qid!r}; the minted axis would share a bucket with that "
            "question's decisions and manufacture a contradiction that does "
            "not exist, which is the fail-false twin of the fail-open the "
            "reserved literal is closed against. The remedy is a human one and "
            "there are two: reword the question so derive_qid mints a "
            "different id, or tag it onto the real axis it belongs to instead "
            "of the reserved literal -- then re-open it")
    return qid


def _finalisation_base(run_dir: Path, qid: str, tracker: dict) -> tuple:
    """The cells every outcome carries, and the open record they came from.

    THE MINT HAPPENS HERE, ahead of every gate, because
    ``check_contradiction`` REFUSES the reserved literal outright: a candidate
    arriving on ``new`` would raise rather than be compared, and moving the
    mint after the check is the one ordering that cannot work.

    AND IT IS THE ONE CELL THAT CAN COME BACK ABSENT. ``_minted_axis`` refuses
    a mint that would collide with a stage-03 question id; the refusal is
    caught here and handed back BESIDE the base rather than propagated, so
    ``_compute_quorum_result`` can escalate on it instead of raising out of
    every finalisation for ever. ``decision_axis`` is then ``None``, which is
    reachable on that outcome and on no other: every reader of the cell --
    ``check_contradiction``'s candidate, ``_decision_record``,
    ``_rendered_decisions``, ``_assert_records_what_was_decided`` -- sits on
    the ADOPTION path, behind gates the escalation returns in front of.

    THE REFUSAL TRAVELS ALONGSIDE, not inside ``base``. Every outcome is
    ``dict(base, ...)`` and is published verbatim into ``final.json``, so a
    cell carried in the base is a cell every adopted record carries too --
    always ``None``, and mistakable for a fact about the adoption.
    """
    opened = _open_record(run_dir, qid)
    axis = _opened_token(
        opened, qid, "axis",
        "the axis is the key every contradiction check groups by, and one that "
        "cannot be written into a decision record groups with nothing")
    phase = _opened_token(
        opened, qid, "phase",
        "the per-phase drift budget groups by it, and a finalisation charged to "
        "no phase at all is an adoption the ceiling cannot see")
    try:
        decision_axis, mint_refusal = _minted_axis(axis, qid, tracker), None
    except QuorumSchemaInvalid as exc:
        decision_axis, mint_refusal = None, str(exc)
    base = {
        "qid": qid,
        #: THE QUESTION AS ASKED, carried in the outcome rather than re-read at
        #: record time. ``_question_record`` re-derives the qid from the
        #: record's own question and axis and compares, so this read is also
        #: where a half-restored directory is caught; carrying the result means
        #: the repair path writes the same words the outcome was computed
        #: against rather than whatever the file says when the repair runs.
        "question": _question_record(run_dir, qid)["question"],
        "axis": axis,
        "decision_axis": decision_axis,
        "phase": phase,
        "blocks": _opened_blocks(opened, qid),
        "context_digest": _bound_digest(
            opened, qid, "context_digest",
            "the drift a resumed quorum is judged by is the distance between "
            "that value and the audit trail as it stands"),
        "decision_id": None,
        "winner": None,
        "winner_rung": None,
        "runner_up_rung": None,
        "clusters": [],
        "effective_rungs": {},
        "demotion_reasons": {},
        "reason": None,
        "dispatched": True,
        #: THE LINEAGE TRAVELS INTO ``final.json``, which is what makes it
        #: durable: ``_prior_reopens`` reads ``lineage_root`` back off the
        #: settled record to cap the next challenge, and ``reopen_of`` is what
        #: licenses ``_apply_adoption_gates`` to supersede exactly one standing
        #: decision and no other.
        "reopen_of": _opened_lineage(opened, qid, "reopen_of"),
        "lineage_root": _opened_lineage(opened, qid, "lineage_root"),
        "raised_bar_rung": _opened_bar(opened, qid),
    }
    return base, opened, mint_refusal


def _stale_moves(run_dir: Path, qid: str, opened: dict, base: dict) -> list:
    """What has moved under this quorum since it was dispatched.

    ``classify_quorum`` asks the same two questions and puts the answer AHEAD
    of every state that would act on the answers, and this is the resolution it
    routes to. Waiting, re-dispatching and computing an outcome are all acts on
    behalf of a question the run has since moved past, and re-deciding on
    resume is precisely the silent-divergence failure this design exists to
    prevent. Three good answers under a moved ``decisions.md`` are three good
    answers to a question that is no longer the one in front of the run.

    TWO DIGESTS, because they catch two facts at two moments and neither
    subsumes the other: ``context_digest`` against ``decisions.md`` catches a
    decision landing at the instant it lands, and ``payload_digest`` against a
    fresh computation catches the file the brains were told to READ being
    rewritten under them -- including by a hand edit of
    ``decisions-effective.md``, which ``decisions.md`` cannot see at all.
    """
    moved = []
    if base["context_digest"] != _context_digest(run_dir):
        moved.append("decisions")
    if _dispatched_digest(opened, qid) != payload_digest(qid, run_dir=run_dir):
        moved.append("projection")
    return moved


def _latest_answers(run_dir: Path, qid: str, owners: list) -> tuple:
    """Each owner's last answer, and the owners whose last answer was malformed.

    ``_owner_attempts`` returns ``(digest, record)`` PAIRS, not records: the
    digest is the identity ``publish_immutable`` returned for the bytes the
    answer was stored as, and unpacking is what keeps the two apart.

    An owner with NOTHING on record is a quorum that is not ready, and it is
    ``QuorumIncomplete`` rather than an escalation: the controller owes a
    dispatch, and escalating would hand a human a question three brains were
    still working on. An owner whose FIRST answer was malformed is owed its one
    re-dispatch for the same reason. An owner whose SECOND was malformed is
    terminal -- a second invalid answer is a non-response -- and that is the
    escalation, because a brain may force a human look and must never be able
    to force an adoption by malforming.
    """
    latest, invalid = [], []
    for owner in owners:
        attempts = _owner_attempts(run_dir, qid, owner)
        if not attempts:
            raise QuorumIncomplete(
                f"{owner} has not answered {qid}; the quorum is not ready and "
                "the controller owes a dispatch, which is not the same fact as "
                "a question a human must now settle")
        _digest, attempt = attempts[-1]
        if attempt["valid"]:
            latest.append((owner, attempt["response"]))
            continue
        if len(attempts) < _MAX_ATTEMPTS:
            raise QuorumIncomplete(
                f"{owner} is owed its one re-dispatch for {qid}; a malformed "
                "first answer buys exactly one re-ask, and finalising before it "
                "is spent decides the question on two brains")
        invalid.append(owner)
    return latest, invalid


def _compute_quorum_result(run_dir: Path, qid: str, tracker: dict) -> dict:
    """The outcome of one quorum, computed from the files and from nothing else.

    THE ORDER OF THE GATES IS THE DESIGN. Staleness outranks every state that
    would act on the answers; a malformed quorum is escalated before anything
    is priced; every response's rung is recomputed FROM DISK before any
    comparison between responses; the floor is applied before the spread,
    because a cluster below the bar is not adopted however far it is above the
    runner-up; and the budget is re-checked LAST, at the moment the adoption
    would actually charge it.

    THE MINT REFUSAL IS ANSWERED FIRST, in the position the raise it replaced
    used to fire from -- inside ``_finalisation_base``, ahead of staleness.
    Only the consequence changed, not the order: a colliding mint is a fact
    about the question record alone, true before any answer is read and
    unchanged by anything the brains say or by the trail moving underneath
    them, so there is no state it could outrank and none that could clear it.
    """
    base, opened, mint_refusal = _finalisation_base(run_dir, qid, tracker)
    if mint_refusal is not None:
        #: NO AXIS, SO NOTHING IS BUCKETED -- which is the whole of what the
        #: collision check protects. The check is untouched and the decision is
        #: still refused; what is no longer refused is FINISHING. Raised, this
        #: left the quorum at ``ready-to-finalise`` with no ``final.json``, no
        #: re-dispatch owed and every call raising again: a run that can never
        #: finalise, which is not the right answer to a hash collision. An
        #: escalation adopts nothing and appends nothing --
        #: ``_ensure_decision_recorded`` writes only on ``adopted`` -- so the
        #: fail-false property survives intact, and it arrives as a counted,
        #: inspectable outcome a human can read the remedy off.
        return dict(base, status=_ESCALATED, reason="unmintable-axis",
                    refusal=mint_refusal)
    owners = _record_owners(opened, qid)
    options_supplied = opened.get("options_supplied")
    if not isinstance(options_supplied, bool):
        raise QuorumSchemaInvalid(
            f"the open record for {qid} states options_supplied "
            f"{options_supplied!r}, not a bool; it decides whether answers are "
            "compared by key or by consequence, and a truthy string read back "
            "off disk clusters three distinct prose answers as one")

    moved = _stale_moves(run_dir, qid, opened, base)
    if moved:
        #: NOT RE-OPENED AND NOT FINALISED ON THE MERITS. The answers may be
        #: perfect and they are answers to a question the run has moved past.
        return dict(base, status=_ESCALATED, reason="stale-context",
                    moved=moved, route=_STALE_ROUTE)

    latest, invalid = _latest_answers(run_dir, qid, owners)
    if invalid:
        return dict(base, status=_ESCALATED, reason="incomplete-quorum",
                    invalid_owners=invalid)

    #: ORDER IS LOAD-BEARING: every citation is resolved from disk BEFORE any
    #: comparison between responses. Run afterwards, a top-rung response with a
    #: dangling citation wins on a claim no file supports and is recorded at
    #: the rung it declared rather than the rung it earned.
    #:
    #: THE ROOT IS THE ``## Run`` FIELD, read through ``repo_root``. Deriving
    #: it here resolves nothing, demotes every grounded answer to
    #: ``engineering-judgement``, puts every cluster below the floor and
    #: escalates the entire run -- with no error anywhere to find it by.
    root = repo_root(tracker)
    for owner, payload in latest:
        base["effective_rungs"][owner] = effective_rung(payload, root)
        #: RECORDED, NOT RE-DERIVED LATER. ``_demotion_reason`` is what priced
        #: this answer; deriving the name again at read time derives it from a
        #: different code path than the one that made the decision, and the two
        #: can disagree with nothing failing.
        base["demotion_reasons"][owner] = _demotion_reason(payload)

    blocked = [owner for owner, payload in latest
               if _text(payload.get("blocker"))]
    if len(blocked) >= _BLOCKED_QUORUM:
        #: One brain unable to proceed is a brain. Two is the question.
        return dict(base, status=_ESCALATED, reason="blocked",
                    blocked_owners=blocked)

    ordered = [owner for owner, _payload in latest]
    payloads = [payload for _owner, payload in latest]
    try:
        clusters, verdicts = group_responses(payloads,
                                             options_supplied=options_supplied)
    except QuorumSchemaInvalid as exc:
        #: THE RESPONSES, never the run, for the reason the contradiction check
        #: below is wrapped -- and this is the call that reaches them FIRST.
        #: ``_candidate_consequences`` refuses a response asserting one
        #: ``(kind, subject)`` twice, and ``_consequence_problems`` -- the gate
        #: ``validate_brain_response`` puts a real response through -- does not
        #: screen for the repeat. So that response is SCHEMA-VALID, is accepted
        #: by ``record_brain_response``, and a brain whose first answer was
        #: legal can never be re-asked: unwrapped, one brain's legal answer
        #: raises out of every finalisation for ever, publishes no
        #: ``final.json``, and leaves the quorum at ``ready-to-finalise`` with
        #: nothing that can move it. A brain may force a human look and must
        #: never be able to halt the run, which is the same rule the malformed
        #: -response path is built on, and ``uncomparable-answer`` is already
        #: the token for an answer this stage cannot compare.
        return dict(base, status=_ESCALATED, reason="uncomparable-answer",
                    refusal=str(exc))
    if verdicts and all(verdict is None for verdict in verdicts.values()):
        #: No two answers spoke about the same thing. That is not a tie and not
        #: a disagreement -- there is nothing here to decide between.
        return dict(base, status=_UNDECIDABLE,
                    reason="answers-describe-different-things")

    graded = [[{"owner": ordered[index], "payload": payloads[index],
                "effective_rung": base["effective_rungs"][ordered[index]]}
               for index in cluster] for cluster in clusters]
    #: Sorted by ladder POSITION and by nothing else, so a tie keeps dispatch
    #: order. A second key -- cluster size, subject count -- could only break
    #: ties between equal rungs, and equal rungs never adopt: it would decide
    #: nothing while looking like a rule.
    ranked = sorted(graded,
                    key=lambda cluster: RUNG_ORDER.index(cluster_rung(cluster)))
    winner = ranked[0]
    winner_rung = cluster_rung(winner)
    runner_up_rung = None
    if len(ranked) > 1:
        runner_up_rung = cluster_rung(ranked[1])
    base["winner_rung"] = winner_rung
    base["runner_up_rung"] = runner_up_rung
    base["clusters"] = [[member["owner"] for member in cluster]
                        for cluster in ranked]

    floor = current_floor(str(run_dir))
    #: BY POSITION, never by value. ``RUNGS[winner] < floor_value`` is the same
    #: answer today and it is a float comparison between two rungs, which is
    #: the shape this phase forbids; the floor is reported as a value for the
    #: human and compared as a position by the code.
    if RUNG_ORDER.index(winner_rung) > RUNG_ORDER.index(floor["floor_rung"]):
        return dict(base, status=_ESCALATED, reason="below-floor",
                    floor_rung=floor["floor_rung"])

    if runner_up_rung is not None:
        #: NO NUMERIC MARGIN. Strictly higher by ladder position or escalate,
        #: and the condition is spelled as the negation of the rule itself --
        #: ``index(winner) < index(runner_up)`` -- so that relaxing it in
        #: either direction fails the suite. Unanimity has no runner-up, so the
        #: test is vacuous there and the floor alone governs.
        if not RUNG_ORDER.index(winner_rung) < RUNG_ORDER.index(runner_up_rung):
            return dict(base, status=_ESCALATED,
                        reason="equal-or-inverted-rung")

    #: THE RAISED BAR, CONSUMED. Everything above this line was already true of
    #: an ordinary quorum; this is the one place a re-open is judged differently
    #: from the question it challenges, and until it existed the bar was
    #: recorded in ``open.json``, mirrored into the row, and read by nothing --
    #: every assertion about the record's CONTENTS passed while the guardrail
    #: did nothing at all. That is the worst shape a guardrail defect takes,
    #: because an absent guardrail gets noticed.
    #:
    #: STRICTLY BETTER, NOT MERELY GOOD ENOUGH. A ``code-evidenced`` answer
    #: re-opening a ``code-evidenced`` decision does not adopt, unanimous or
    #: not, floor or no floor: re-deciding at the same quality of evidence is
    #: not new information, it is the run rolling the dice again -- and the
    #: re-ask was admitted precisely on the claim that something new had been
    #: found. Spelled as the NEGATION of the rule, for the reason the spread
    #: test above is: relaxing it in either direction fails the suite.
    #:
    #: ``None`` IS THE ORDINARY QUORUM and also the post-extension re-raise,
    #: where a budget refusal measured no answer at all and there is therefore
    #: nothing to be better than. The standing floor governs both.
    raised = base["raised_bar_rung"]
    if raised is not None and not RUNG_ORDER.index(winner_rung) < RUNG_ORDER.index(raised):
        return dict(base, status=_ESCALATED, reason="raised-bar-not-cleared")

    decisions_text = _decisions_text(run_dir)
    #: THE AUDIT TRAIL IS PARSED BEFORE ANY GATE READS IT, and a trail that
    #: does not parse is a read-only stop here exactly as it is everywhere
    #: else. Parsed once and handed down, so the contradiction check, the depth
    #: walk and the record writer cannot read three different files.
    decisions = parse_decisions(decisions_text)
    outcome = _apply_adoption_gates(base, winner, winner_rung, decisions)
    if outcome["status"] != _CHARGED_STATUS:
        return outcome

    #: THE DRIFT CAP IS ENFORCED WHERE THE CHARGE HAPPENS, AND THAT IS HERE.
    #: ``open_quorum`` charges NOTHING -- it is an admission check -- so two
    #: questions raised against one remaining adoption both pass it even
    #: perfectly serialised, because the first spent nothing. Checked only at
    #: raise time, the budget bounds how many questions may be ASKED and not
    #: how many decisions a machine may MAKE, which is the opposite of what it
    #: is for. An in-flight reservation was considered and refused: it would
    #: still not protect the cap, and one crashed quorum would leave its phase
    #: escalating every question for ever.
    #:
    #: LAST, after every gate, so that a question which would have been
    #: rejected for contradicting a human is reported as that and not as a
    #: budget that happened to be spent. Escalations never reach this line, so
    #: nothing here charges for asking.
    budget = quorum_budget(str(run_dir), phase=base["phase"])
    if not budget["may_raise"]:
        return dict(base, status=_ESCALATED, reason=budget["reason"],
                    phase_adoptions=budget["phase_adoptions"],
                    phase_ceiling=budget["phase_ceiling"],
                    run_adoptions=budget["run_adoptions"],
                    run_ceiling=budget["run_ceiling"],
                    adopted=list(budget["adopted"]))

    #: THE RECORD IS RENDERED AND VALIDATED BEFORE ``final.json`` IS PUBLISHED,
    #: which is the only order that keeps the run alive. ``decisions.md`` is
    #: append-only and a record the parser refuses makes every later read of
    #: this run a read-only stop; an adoption whose record cannot be written is
    #: therefore not an adoption, and the remedy is the human this stage exists
    #: to reach.
    try:
        _rendered_decisions(outcome, decisions_text, decisions)
    except TrackerValidationError as exc:
        return dict(base, status=_ESCALATED, reason="unrecordable-decision",
                    refusal=str(exc))
    return outcome


def _apply_adoption_gates(base: dict, winner: list, winner_rung: str,
                          decisions: dict) -> dict:
    """Everything that can refuse an answer which already cleared the rung bar.

    A quorum may decide an open question. IT MAY NEVER OVERRULE A RECORDED ONE:
    a candidate contradicting a decision already in effect is rejected at any
    rung, and the rejection is RECORDED rather than discarded -- a run with
    several ``rejected-contradicts-*`` events is a run whose brains keep
    pulling away from what the user asked for, and that count is the earliest
    drift warning available.

    THE IRREVERSIBLE-AXIS LIST IS CLOSED AND NO CONFIDENCE BUYS PAST IT.
    ``forecloses`` and ``blast`` exist precisely so that asking what an answer
    DESTROYS can surface risk that asking what it achieves never does, and the
    blast radius is taken over the WHOLE winning cluster: one member naming
    ``external-service`` is the cluster naming it, because the cluster is what
    is being adopted.

    THE DEPTH IS COMPUTED, NEVER ASSUMED. Writing a placeholder into the
    record's ``Depth`` would put a number into an append-only audit trail that
    nothing later can correct, and depth is the one distance the cap measures.
    ``decision_depth`` raises on an anchor that names no record in effect --
    ideally that is a re-dispatch of that brain, but a brain whose answer was
    LEGAL can never be re-asked (``record_brain_response`` refuses the second
    answer outright), so at this point the only live remedy is the human.
    """
    best = _best_member(winner)
    payload = best["payload"]
    blast = []
    for member in winner:
        for entry in member["payload"]["blast"]:
            if _member(entry, IRREVERSIBLE_AXES) and entry not in blast:
                blast.append(entry)
    if blast:
        return dict(base, status=_ESCALATED, reason="irreversible-axis",
                    blast=sorted(blast))

    try:
        contradicted = check_contradiction(decisions, {
            "axis": base["decision_axis"],
            "answer_key": payload["answer_key"],
            "consequences": payload["consequences"],
        })
    except QuorumSchemaInvalid as exc:
        #: THE CANDIDATE, never the records: every ``QuorumSchemaInvalid``
        #: ``check_contradiction`` raises is about the answer handed to it -- a
        #: generic approval, a key that names no option -- while an unreadable
        #: audit trail is ``TrackerValidationError`` and stays a run stop. An
        #: answer that cannot be compared against the axis cannot be shown NOT
        #: to contradict it, and the permissive reading of that is the one that
        #: adopts; a brain typing ``yes`` must reach a human, not halt the run.
        return dict(base, status=_ESCALATED, reason="uncomparable-answer",
                    refusal=str(exc))
    if contradicted is not None and contradicted == base.get("reopen_of"):
        #: THE ONE DECISION THIS QUORUM IS LICENSED TO REPLACE, and it is not a
        #: hole in the contradiction check -- it is what a re-open IS. The
        #: challenged decision is Adopted on this axis, so it contradicts every
        #: answer that differs from it; without this exemption a re-open could
        #: only ever re-affirm what it was raised to question, and the raised
        #: bar above would gate a path nothing could reach.
        #:
        #: BOUNDED BY THE ADMISSION, NOT BY THIS LINE. ``_reopen_authority``
        #: has already refused any ``reopen_of`` that is not a quorum adoption
        #: or a human budget grant, so this can never exempt a HUMAN answer on
        #: the axis; and it names exactly one D-ID, so a second standing
        #: decision still rejects. The price of the exemption is the strictly
        #: higher rung, which was paid two gates up.
        contradicted = None
    if contradicted is not None:
        provenance = decisions["decisions"][contradicted]["provenance"]
        return dict(
            base, status=_REJECTED_PREFIX + provenance,
            contradicted_decision=contradicted,
            reason=f"the winning answer contradicts {contradicted}, which this "
                   f"run has already decided with provenance {provenance}")

    try:
        depth = decision_depth(decisions, payload["consistent_with"])
    except QuorumSchemaInvalid as exc:
        return dict(base, status=_ESCALATED, reason="unresolvable-anchor",
                    refusal=str(exc))
    if depth > DEPTH_CAP:
        return dict(base, status=_ESCALATED, reason="depth-exceeded",
                    depth=depth)

    return dict(base, status=_CHARGED_STATUS, reason=None, depth=depth,
                decision_id=_QUORUM_PREFIX + base["qid"],
                winner={"answer_key": payload["answer_key"],
                        "answer": payload["answer"],
                        "rung": winner_rung,
                        "owner": best["owner"],
                        "consequences": payload["consequences"],
                        "consistent_with": payload["consistent_with"],
                        "forecloses": payload["forecloses"],
                        "blast": payload["blast"]})


def _repair_decision_record(run_dir: Path, settled: dict) -> None:
    """Finish the interrupted append -- ONLY ONTO THE TRAIL IT WAS DECIDED AGAINST.

    ``final.json`` is published before the decision is appended, so an
    interruption between the two leaves a finalised quorum with no record and
    the next call repairs it. The repair re-renders against the trail AS IT
    STANDS, and ``_rendered_decisions`` supersedes whatever stands on the axis
    NOW -- it has no notion of which of the two decisions is newer. Unguarded
    that inverts the audit trail:

    1. quorum A adopts; ``final.json`` is written and the append is cut short;
    2. quorum B adopts on the same axis -- the axis LOOKS unoccupied, so B is
       not even contradiction-checked against A -- and appends;
    3. A is repaired, and A supersedes B.

    The run's binding decision silently becomes the OLDER answer, B is retired
    by a decision made before it, and the file parses so nothing complains.

    ``context_digest`` IS THE CLOCK, and it is exact rather than approximate.
    ``_stale_moves`` already refused to finalise A at all unless the trail
    still digested to the value bound at dispatch, so at the instant A adopted
    the two were equal: on this path they differ if and only if the trail moved
    AFTER a settled outcome. A byte-identical restoration -- the interrupted
    write itself -- digests equal and repairs normally.

    CHECKED ONLY WHEN THE APPEND IS STILL OWED. A run whose record is already
    on file has moved the trail BY LANDING IT, so the digests differ on every
    replay of every adoption, and testing before that would turn the idempotent
    no-op into a stop.

    A STOP, NOT AN ESCALATION. ``final.json`` is a single-assignment cell and
    this quorum is already settled-adopted and already charged to the budget;
    there is no second outcome to report and no machine answer that is not a
    silent reversal of one of the two decisions. Which of them binds is the
    human's call, and the file is append-only, so the remedy is a hand edit.
    """
    text = _decisions_text(run_dir)
    if settled["decision_id"] in parse_decisions(text)["decisions"]:
        return
    current = _context_digest(run_dir)
    if settled.get("context_digest") != current:
        raise TrackerValidationError(
            f"{settled['decision_id']} was adopted against a decisions trail "
            f"digesting to {settled.get('context_digest')!r} and the trail now "
            f"digests to {current!r}; appending it here would supersede "
            f"whatever stands on {settled['decision_axis']} now, which is a "
            "decision made LATER being retired by one made earlier, and "
            "decisions.md is append-only. Which of the two binds this run is "
            "not a question this stage can answer")
    _ensure_decision_recorded(run_dir, settled)


# --- P03's own tracker rows ------------------------------------------------
#
# NO PHASE WRITES ANOTHER PHASE'S ROWS AND NO PHASE RE-DECLARES ANOTHER
# PHASE'S COLUMNS. P03 owns the quorum lifecycle, so P03 writes the ``##
# Quorum`` and ``## Escalations`` rows that mirror it -- and builds every one
# of them against ``section_columns``, so a column P02 adds, drops or renames
# fails HERE, at the seam, instead of drifting into a write that puts a cell
# under the wrong header and still parses.

#: The state a mirrored row carries. Asserted against ``_QUORUM_STATES`` in the
#: suite rather than indexed out of it, for ``_IN_FLIGHT``'s reason: an index
#: reads as arithmetic over a tuple whose order is not a promise, while a
#: literal plus a pinned assertion says which word and fails if it moves.
_FINALIZED = "finalized"

#: The cell an absent value renders as. ``_csv`` reads it back as the empty
#: tuple, so it is "nothing here" spelled in the one way the parser agrees
#: with -- an empty cell round-trips as a one-element list holding the empty
#: string, which is a different fact.
_ABSENT_CELL = "-"

#: The characters that re-column a ROW, and the whole of them: ``|`` gives the
#: row an extra column and ``,`` splits one token into two inside every
#: list-valued cell. Both PARSE -- that is the whole danger -- and the tracker
#: comes back holding cells nobody wrote.
#:
#: THE CHARACTERS THAT ADD A ROW ARE NOT LISTED HERE. They are asked of the
#: reader, in ``_splits_the_section``, because a written-down list of them was
#: wrong.
_CELL_SEPARATORS = "|,"

#: The statuses that put a question in front of a human, and the whole of them.
#:
#: ``rejected-contradicts-human`` IS ESCALATED, because the spec says so in a
#: governing invariant: "Any candidate answer contradicting a `Provenance:
#: human` decision is rejected AND ESCALATED, at any confidence." This set once
#: left it out, under a comment claiming the blocked task "can proceed on the
#: standing record". It cannot: a rejection writes no ``Q-<qid>`` adoption, so
#: ``resume_task`` has no grant to read and the task stays ``[?]`` -- and
#: without a queued row nothing would ever put that block in front of the one
#: party who can clear it. The human is not being asked to re-decide; they are
#: shown that the run's own evidence pulls against their answer, and every task
#: blocked on that axis stays blocked until they respond.
#:
#: ``rejected-contradicts-quorum`` IS NOT ESCALATED HERE. A standing quorum
#: decision is challenged by ONE re-open at a raised bar per decision per run
#: (``derive_reopen_qid``), and a second challenge escalates as
#: ``second-challenge`` from ``open_quorum`` -- that route, not this set, is
#: how a quorum-on-quorum contradiction reaches a human. Both rejections stay
#: the ``Outcome`` cell of the ``## Quorum`` row, which is where the run's
#: count of "brains pulling away from what was decided" is read from.
#:
#: ``_UNDECIDABLE`` IS ESCALATED, because nothing was settled by it: three
#: answers about three different things leave the question exactly as open as
#: it was raised, and a human is the only remaining way to close it.
_REJECTED_HUMAN = _REJECTED_PREFIX + "human"
_ESCALATING_STATUSES = frozenset({_ESCALATED, _UNDECIDABLE, _REJECTED_HUMAN})

#: Where one escalation's ``Blast`` cell comes from, PER REASON TOKEN, and a
#: reason absent from this mapping is refused rather than defaulted.
#:
#: THE TOTALITY IS THE POINT, not the two values. Every reason this phase can
#: emit has to appear here, so adding a twelfth escalation reason is a change
#: that cannot be made without deciding what a human is shown when it fires --
#: and the suite derives the token list from the finaliser's own source rather
#: than from this table, so a reason added there and forgotten here is a red
#: test and not a ``-`` in the one column the batching human reads.
#:
#: ``irreversible-axis`` IS THE ONE THAT DIFFERS, because it is the one outcome
#: whose record carries the axes that tripped it: the trespass is the fact, not
#: the axis the question was asked on. Everything else touches exactly the axis
#: it was raised against, which is what ``Blast`` means in this section --
#: ``_BLAST_RADII`` is the admissibility vocabulary and is deliberately not
#: this column's.
_BLAST_FROM_TRESPASS = "blast"
_BLAST_FROM_AXIS = "axis"
_ESCALATION_BLAST = MappingProxyType({
    "irreversible-axis": _BLAST_FROM_TRESPASS,
    "unmintable-axis": _BLAST_FROM_AXIS,
    "stale-context": _BLAST_FROM_AXIS,
    "incomplete-quorum": _BLAST_FROM_AXIS,
    "blocked": _BLAST_FROM_AXIS,
    "uncomparable-answer": _BLAST_FROM_AXIS,
    "unresolvable-anchor": _BLAST_FROM_AXIS,
    "unrecordable-decision": _BLAST_FROM_AXIS,
    "below-floor": _BLAST_FROM_AXIS,
    "equal-or-inverted-rung": _BLAST_FROM_AXIS,
    "depth-exceeded": _BLAST_FROM_AXIS,
    "phase-budget-exhausted": _BLAST_FROM_AXIS,
    "run-budget-exhausted": _BLAST_FROM_AXIS,
    "answers-describe-different-things": _BLAST_FROM_AXIS,
    "raised-bar-not-cleared": _BLAST_FROM_AXIS,
    "second-challenge": _BLAST_FROM_AXIS,
})


def _splits_the_section(char: str) -> bool:
    """Would ``char`` give ``## Quorum`` an extra row? ASKED, NOT LISTED.

    ``_sections`` re-splits the rendered tracker with ``str.splitlines()``, and
    that reader breaks on TEN characters -- ``\n``, ``\r``, ``\v``, ``\f``,
    ``\x1c``, ``\x1d``, ``\x1e``, ``\x85``, ``\u2028`` and ``\u2029``. A
    constant naming "the newline characters" named two of them, and the other
    eight passed the screen and split the rendered row in half exactly as a
    newline would -- silently, with both halves the wrong width. Measured:
    ``_cell("a\x0bb")`` passed and its row came back as two lines.

    So the screen asks the reader instead of remembering it. Anything
    ``splitlines`` treats as a line break is a row break here BY DEFINITION,
    including whatever a later Python adds to that set.

    NOT DEAD CODE FOR ``_mirror_quorum``, where every cell is grammar-validated
    upstream -- but ``quorum_tracker_rows`` takes ``axis``, ``depth`` and
    ``winner_rung`` straight out of a hand-editable ``final.json`` and hands
    them to P06 with this as the only screen between.
    """
    return len(f"a{char}b".splitlines()) > 1


def _cell(value, what: str) -> str:
    """One tracker cell, screened out of a record a human may have edited.

    ``final.json`` and ``open.json`` are files inside the run directory, so
    every value that reaches a row arrives from agent-authored or hand-editable
    JSON and may legally be a list, an object or a number.

    THE SHAPE IS REFUSED RATHER THAN COERCED. ``str(["a"])`` is ``"['a']"``,
    which renders, parses back, and reads as a cell somebody wrote; the
    validators downstream would then report an unknown axis or an outcome
    outside the grammar, naming the symptom one section away from the record
    that caused it. ``bool`` is excluded from the integers on purpose --
    ``str(True)`` is ``'True'`` and ``isinstance(True, int)`` is true, so
    admitting it writes a word no column has a meaning for.

    THE POISON CHARACTERS ARE THE ONES THAT STILL PARSE. A ``|`` gives the row
    an extra column, a line break gives the section an extra row, and a ``,``
    turns one token into two inside every comma-separated cell. None of them
    raises anywhere; the tracker simply comes back holding cells nobody wrote,
    which is the failure ``_TOKEN`` exists to prevent one layer up and is asked
    again here because this writer is the one that composes them.

    THE SET IS NOT CLOSED AND IS NOT WRITTEN DOWN. Two separators are named
    here; every row break is DERIVED from the reader that will do the splitting
    -- see ``_splits_the_section``, and the eight characters an earlier closed
    list of "the newline characters" let through.
    """
    if value is None:
        return _ABSENT_CELL
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise QuorumSchemaInvalid(
            f"{what} is a {type(value).__name__}, not a cell; coercing it "
            "would render a repr into the tracker, which parses back looking "
            "exactly like a value somebody wrote")
    text = str(value).strip()
    poison = [char for char in text
              if char in _CELL_SEPARATORS or _splits_the_section(char)]
    if poison:
        raise QuorumSchemaInvalid(
            f"{what} is {text!r}, which carries {poison[0]!r}; that re-shapes "
            "the table SILENTLY -- a pipe adds a column, anything the section "
            "reader treats as a line break adds a row, a comma splits one "
            "token into two -- so the tracker parses back holding cells "
            "nobody wrote")
    return text or _ABSENT_CELL


def _cell_list(values, what: str) -> str:
    """A comma-separated cell, or ``-`` for an empty one.

    ``-`` RATHER THAN THE EMPTY STRING, because ``_csv`` is the reader and the
    two are not the same value to it: ``-`` comes back as ``()`` and ``""``
    comes back as ``("",)``. An empty cell would therefore read as a section
    holding one nameless response, one nameless owner, one nameless axis.
    """
    if values is None:
        return _ABSENT_CELL
    if not isinstance(values, (list, tuple)):
        raise QuorumSchemaInvalid(
            f"{what} is a {type(values).__name__}, not a list; a scalar joined "
            "into a comma-separated cell is one value rendered as a list of "
            "its characters or not rendered at all")
    return ",".join(_cell(value, what) for value in values) or _ABSENT_CELL


def _row_for(section: str, values: dict) -> dict:
    """Order one row by P02's columns, LOUDLY.

    P02 owns the column grammar and P03 owns the quorum lifecycle, so P03
    writes its own rows and re-declares nobody's columns. Checking against
    ``section_columns`` means a column P02 adds, drops or renames fails here --
    at the seam, naming both halves of the mismatch -- rather than drifting
    into a write that nothing notices.

    NAMED, NEVER COUNTED, for ``append_row``'s reason: a row copied from a
    stale column list has exactly the right number of keys and one of them
    spelled for a column that no longer exists. Counting accepts that and
    ``render_tracker`` then reports the column that went MISSING rather than
    the one that was invented.

    ``section`` IS P02'S SECTION KEY -- ``quorum``, ``escalations`` -- and not
    the markdown heading. ``section_columns("Quorum")`` raises, which is the
    right answer to a caller that guessed, and is why this function passes the
    name straight through instead of casefolding it into something that
    happens to work.
    """
    columns = section_columns(section)
    missing = [column for column in columns if column not in values]
    unexpected = [key for key in values if key not in columns]
    if missing or unexpected:
        raise QuorumError(
            f"a {section!r} row P03 built does not match P02's columns "
            f"(missing {missing}, unexpected {unexpected}); reconcile it with "
            f"section_columns({section!r}), which is {list(columns)}")
    return {column: values[column] for column in columns}


def _response_cell(qid: str, owner: str, attempt: int) -> str:
    """Where one recorded answer lives, RUN-RELATIVE.

    Run-relative rather than repo-root-relative, because this cell names a file
    inside the run's own tree and is read by a human resolving it against the
    run directory they are already looking at. ``_run_relative`` is the other
    spelling and is for a path a BRAIN must cite, which is resolved against the
    recorded repository root; using it here would also re-validate the run on
    every cell, inside a lock this writer already holds.
    """
    return (f"{_QUORUM_DIRNAME}/{qid}/{_RESPONSES_DIRNAME}/"
            f"{_response_name(owner, attempt)}")


def _recorded_responses(run_dir: Path, qid: str, owners: list) -> list:
    """Each owner's LATEST answer on disk, and at most one per owner.

    THE LATEST, NOT ALL OF THEM, and the distinction is what keeps the cell
    legal: a brain whose first answer was malformed buys one re-dispatch, so a
    three-brain quorum can hold FOUR response files, and ``_validate_quorum``
    refuses a row citing more than three. It is also the right fact -- the
    superseded first attempt is recorded in the directory and is not what the
    outcome was computed from.

    READ THROUGH ``_owner_attempts`` rather than globbed, so the same gap rule,
    the same shape checks and the same directory guard that priced the quorum
    price the row: a responses directory that is a regular file, a dangling
    link or a FIFO is corruption here exactly as it is there, and not a quorum
    whose brains silently answered nothing.

    AN OWNER WITH NOTHING ON RECORD IS LEGAL HERE, which it is not at
    finalisation. ``stale-context`` and ``unmintable-axis`` both return before
    a single answer is read, so their rows name no response at all -- and that
    is the true cell, not a defect to paper over.
    """
    recorded = []
    for owner in owners:
        attempts = _owner_attempts(run_dir, qid, owner)
        if attempts:
            recorded.append(_response_cell(qid, owner, len(attempts)))
    return recorded


def _quorum_row(run_dir: Path, record: dict) -> dict:
    """One finalised quorum, as the ``## Quorum`` row that mirrors it.

    THE AXIS CELL IS THE AXIS AS ASKED, never ``decision_axis``. The two
    legally disagree and both are right: this row records WHAT WAS ASKED and
    keeps the reserved literal ``new`` for the life of the run, while the
    decision record records THE AXIS THAT QUESTION OPENED, which for a
    ``new``-axis question is its own bare qid. ``_validate_quorum`` closes this
    cell to the stage-03 question ids plus the literal, so a minted axis could
    not be written here anyway -- the two namespaces do not overlap and are not
    meant to.

    EIGHT OF THE TWELVE CELLS ARE NOT IN ``final.json``. ``quorum_events`` is a
    four-cell BUDGET projection and says so; the owners, the two digests and
    the responses belong to the DISPATCH, so they are read back off
    ``open.json`` and off the responses directory. That second source is why
    this takes a run directory and not an event.

    NO RUNG VALUE, NO FLOOR, NO BUDGET COUNT AND NO RAISER. ``Rung`` carries a
    rung NAME, which is what ``_validate_quorum`` admits and what a human
    reads; the value behind it, the adoption floor a ``below-floor`` record
    carries, the two ceilings a budget record carries and the raiser's identity
    all stay out of the tracker, because the tracker is a file a brain can be
    handed and every one of them frames an answer.
    """
    qid = record["qid"]
    opened = _open_record(run_dir, qid)
    owners = _record_owners(opened, qid)
    return _row_for("quorum", {
        "qid": _cell(qid, f"the qid of the final record for {qid}"),
        "axis": _cell(record.get("axis"),
                      f"the axis the final record for {qid} was asked on"),
        "phase": _cell(record.get("phase"),
                       f"the phase the final record for {qid} charges"),
        "state": _FINALIZED,
        "owners": _cell_list(owners, f"an owner of {qid}"),
        "payload_digest": _cell(
            _dispatched_digest(opened, qid),
            f"the payload digest bound by the open record for {qid}"),
        "context_digest": _cell(
            _bound_digest(opened, qid, "context_digest",
                          "the row records the trail this quorum was judged "
                          "against, and a row that records none cannot be "
                          "told apart from one judged against a trail that "
                          "has since moved"),
            f"the context digest bound by the open record for {qid}"),
        "responses": _cell_list(_recorded_responses(run_dir, qid, owners),
                                f"a recorded response for {qid}"),
        "depth": _cell(record.get("depth"),
                       f"the decision depth computed for {qid}"),
        "rung": _cell(record.get("winner_rung"),
                      f"the winning rung computed for {qid}"),
        "outcome": _cell(record.get("status"),
                         f"the status of the final record for {qid}"),
        "decision": _cell(record.get("decision_id"),
                          f"the decision record {qid} adopted"),
    })


def _next_escalation_id(tracker: dict) -> str:
    """The next ``E-<n>``, numbered off the ids the section already holds.

    MAXIMUM PLUS ONE, NOT LENGTH PLUS ONE. ``_validate_escalations`` refuses a
    duplicate id, and a count is not a high-water mark the moment anything ever
    removes a row or writes one out of order -- a resumed run replaying a
    transition that added two rows would mint over the second of them and stop
    the run on a duplicate it created itself.

    IDS THIS GRAMMAR DOES NOT RECOGNISE ARE SKIPPED RATHER THAN PARSED.
    ``int()`` on a cell is a ``ValueError`` outside this module's exception
    family, and the tracker this reads was validated before ``mutate`` was
    called -- so an unrecognised id here is a P06 row shape that has not
    arrived yet, not a number to guess at.
    """
    used = [int(row["id"][len(_ESCALATION_PREFIX):])
            for row in tracker["escalations"]
            if _text(row.get("id")) and _ESCALATION_ID.fullmatch(row["id"])]
    return f"{_ESCALATION_PREFIX}{max(used, default=0) + 1}"


def _escalation_row(tracker: dict, record: dict) -> dict:
    """One escalation queued for the next human gate.

    ``queued``, WITH NO BATCH AND NO RESOLUTION. The three cells are one state:
    ``_validate_escalations`` refuses a queued row that names a batch and
    refuses any unanswered row that names a resolution, because a batch is
    assigned when the escalations are gathered at a stage boundary and a
    resolution exists only after a human has spoken. Writing "pending" here --
    a word no enum in this module holds -- would halt the run at the render.

    THE REASON HAS NOWHERE TO GO, and that is recorded rather than worked
    around. ``## Escalations`` is ``ID | QID | Blast | State | Batch |
    Resolution``: there is no reason column, so the token that says WHY the
    quorum escalated lives in ``final.json`` and is reachable from the row only
    by way of the qid. Inventing a column here would be P03 re-declaring P02's
    grammar, and folding the reason into ``Blast`` would put a non-axis into
    the one cell that is validated as a list of axis tokens. The remedy, if the
    batching human needs the reason in the row, is a P02 column -- named in
    this task's report rather than taken locally.
    """
    reason = record.get("reason")
    #: A REJECTION'S ``reason`` IS A SENTENCE, NOT A TOKEN -- it names the
    #: contradicted decision -- so it is keyed by its status instead. It touches
    #: exactly the axis the question was raised on, like every reason but the
    #: trespass.
    if record.get("status") == _REJECTED_HUMAN:
        source = _BLAST_FROM_AXIS
    else:
        source = _ESCALATION_BLAST.get(reason) if _text(reason) else None
    if source is None:
        raise QuorumError(
            f"{record['qid']} escalated for reason {reason!r}, which no "
            f"Blast cell is mapped for; every reason this phase can emit is "
            "enumerated in _ESCALATION_BLAST so that adding one is a decision "
            "about what the batching human is shown, not a '-' in the only "
            "column they read")
    blast = (record.get("blast") if source == _BLAST_FROM_TRESPASS
             else [record.get("axis")])
    return _row_for("escalations", {
        "id": _next_escalation_id(tracker),
        "qid": _cell(record["qid"], "the qid this escalation belongs to"),
        "blast": _cell_list(blast, f"an axis {record['qid']} escalates on"),
        "state": _ESCALATION_STATES[0],
        "batch": _ABSENT_CELL,
        "resolution": _ABSENT_CELL,
    })


def _mirror_quorum(run_dir: Path, tracker: dict, record: dict) -> dict:
    """Write P03's own rows. Called only from inside a locked transition.

    VALIDATED HERE, BEFORE ``final.json`` IS PUBLISHED, and the ordering is the
    whole point of doing it twice. ``locked_tracker_update`` re-validates what
    ``mutate`` returns -- but it does that AFTER ``mutate`` has run, and by
    then the outcome is already on disk. An illegal row discovered there would
    leave a settled quorum whose rows can never be written, because every later
    call returns the published record without re-entering this path. Asked
    here, the same fault stops the finalisation with nothing published: the
    quorum stays finalisable, a human fixes what is wrong -- a phase the
    tracker has no record of, an axis that is neither a stage-03 question id
    nor the reserved literal -- and the next call finalises normally.

    A STOP, NOT AN ESCALATION, and not a row written with the offending cell
    softened. Both of those are the run editing the audit trail to make its own
    write succeed, and the fact being recorded is the one thing that must not
    be negotiable. ``TrackerValidationError`` is inside ``TrackerError``, so a
    controller's existing handler catches it -- and it must treat it as a human
    stop rather than a retry, because a retry recomputes the same row.

    BOTH VALIDATORS RUN AFTER BOTH APPENDS, and that ordering is the real one.
    ``_validate_escalations`` resolves an escalation's ``QID`` against the qids
    ``## Quorum`` holds, so judging the sections BETWEEN the two appends would
    refuse a row that is about to become legal and stop a finalisation that had
    nothing wrong with it.

    THE APPEND ORDER ITSELF IS NOT LOAD-BEARING, and saying so is a correction
    rather than a caveat: the two calls touch disjoint lists, ``_escalation_row``
    reads only ``tracker["escalations"]``, and ``append_row`` judges a row
    against its own section alone -- so swapping these two lines is an
    EQUIVALENT mutant, and mutation confirmed it. It is written quorum-first
    because that is the order the sections are read in, and a comment claiming
    a dependency the code does not have is a comment that survives the change
    that breaks it.
    """
    tracker = append_row(tracker, "quorum", _quorum_row(run_dir, record))
    if record["status"] in _ESCALATING_STATUSES:
        tracker = append_row(tracker, "escalations",
                             _escalation_row(tracker, record))
    _validate_quorum(tracker)
    _validate_escalations(tracker)
    return tracker


def quorum_tracker_rows(run_dir: str) -> list[dict]:
    """The ``## Quorum`` mirror, re-derived from the files for the terminal report.

    RE-DERIVED, NEVER READ BACK OUT OF THE TRACKER. The tracker is the index
    and ``final.json`` is the evidence; a report built from the index alone
    would report a row a hand edit had changed, and the counter an autonomous
    controller is most motivated to be wrong about is its own count of the
    decisions it made.

    PROVENANCE IS VISIBLE, and it is the ``Decision`` cell that carries it.
    There is no ``Provenance`` column and there does not need to be: every row
    in this section is a machine outcome, and an adopted one names ``Q-<qid>``
    -- a grammar no human decision can wear, which is exactly why
    ``_final_event`` makes an adoption name its own. A provenance field read
    only by a validator has informed nobody; this one is read by whatever
    renders the run's own account of itself.

    A QUORUM THAT DISPATCHED NOTHING HAS NO ROW HERE, and cannot have one. A
    budget trip writes ``final.json`` and not one byte more -- no open record,
    no payload, no context digest, because none of them would be true of a
    dispatch that never happened -- while ``## Quorum`` is validated as a
    DISPATCH record: three owners, two sha256 digests, the responses they
    produced. So those records are skipped, and the omission is deliberate and
    bounded: they remain in ``quorum_events``, which is where the budget and
    the terminal report's escalation count read them from.

    ``dispatched`` IS REQUIRED TO BE A BOOL rather than read for truthiness. A
    record missing it, or carrying a string, would silently drop a real
    adoption out of the run's own account of itself -- the same fail-quiet an
    unreadable record is refused for two functions up.
    """
    path = _run_path(run_dir)
    rows = []
    #: Ordered by ``quorum_events`` and screened by it -- which is also where
    #: two quorums claiming one decision record is caught. The full record is
    #: then re-read through ``_final_event``, because that projection is four
    #: cells by design and this row is twelve. Two reads of one name, and the
    #: second is the one every cell below comes from, so no cell is taken from
    #: a reading the qid check was not applied to.
    for event in quorum_events(str(path)):
        qid = event["qid"]
        _projected, record = _final_event(
            _quorum_directory(path, qid) / _FINAL_FILE, qid)
        dispatched = record.get("dispatched")
        if not isinstance(dispatched, bool):
            raise QuorumSchemaInvalid(
                f"the final record for {qid} states dispatched "
                f"{dispatched!r}, not a bool; the ## Quorum row is a record of "
                "a DISPATCH -- three owners, two digests, the responses they "
                "produced -- and a record that will not say whether it "
                "dispatched anything would be dropped from the run's own "
                "account of itself without a word")
        if dispatched:
            rows.append(_quorum_row(path, record))
    return rows


def finalize_quorum(run_dir: str, *, qid: str) -> dict:
    """Phase 3 of the record, through the tracker lock as ``quorum-<qid>``.

    A FINALISED RECORD IS NEVER RECOMPUTED. ``final.json`` is a
    single-assignment cell and the outcome it holds is returned unchanged: a
    second run of the same three brains gives a different answer about as often
    as the rung gap is narrow, and there is no principled way to prefer either.

    THE ROWS ARE MIRRORED BEFORE EITHER, for the reason ``_mirror_quorum``
    states: a row P02's validators refuse is discovered while the outcome is
    still unpublished, so the fault is a human stop the run recovers from
    rather than a settled quorum that can never be indexed.

    THE DECISION IS APPENDED AFTER ``final.json`` IS PUBLISHED, and the order
    is deliberate. An interruption between the two leaves a finalised quorum
    with no decision record, which the next call REPAIRS -- the append is
    idempotent. The reverse order leaves a decision record with no finalised
    quorum, which the next call would double-append, and ``decisions.md`` is
    append-only.

    BOTH WRITES HAPPEN UNDER THE RUN LOCK, including on the repair path.
    ``decisions.md`` is one run-global file and ``worker_limit >= 4``, so two
    finalisations landing at once would each read the trail, each append, and
    one of the two decisions would simply not be there -- an adoption charged
    to the budget with nothing in the audit trail to show for it.

    NEVER CALL THIS FROM INSIDE A HELD RUN LOCK, for ``open_quorum``'s reason:
    ``select_lock_impl`` prefers POSIX ``flock``, which belongs to the open file
    description rather than to the process, so a nested acquire does not
    recurse -- it blocks against itself and raises at the timeout.
    """
    run_dir = _run_path(run_dir)
    #: VALIDATED BEFORE ANYTHING ELSE, for ``classify_quorum``'s reason: a
    #: foreign, missing or malformed run is a read-only stop, and the repair
    #: path below writes.
    validate_run(run_dir)
    qid = _quorum_qid(qid)
    final_path = _quorum_directory(run_dir, qid) / _FINAL_FILE
    #: ``lexists`` rather than ``exists``, exactly as ``_open_under_lock`` and
    #: ``classify_quorum`` spell it: a dangling symlink and a symlink loop are
    #: names this directory CARRIES, and answering them with "not settled yet"
    #: recomputes an outcome the run has already recorded.
    if os.path.lexists(final_path):
        #: ONE READ FOR BOTH HALVES -- ``_final_event`` validates and hands
        #: back the record it validated, so the verdict and the outcome cannot
        #: describe two different readings of a name a human may be restoring.
        _event, settled = _final_event(final_path, qid)
        if settled.get("status") == _CHARGED_STATUS:
            with _exclusive_lock(run_dir):
                _repair_decision_record(run_dir, settled)
        return settled
    holder: dict = {}

    def mutate(tracker):
        result = _compute_quorum_result(run_dir, qid, tracker)
        #: THE ROWS ARE BUILT AND JUDGED BEFORE ONE BYTE IS PUBLISHED, and the
        #: order is the difference between a recoverable stop and a quorum
        #: whose outcome is on disk and whose rows can never be written. Only
        #: the tracker is touched here, in memory, and
        #: ``locked_tracker_update`` writes it after ``mutate`` returns -- so
        #: if either publish below fails, no row lands either.
        mirrored = _mirror_quorum(run_dir, tracker, result)
        holder["result"] = result
        publish_immutable(final_path, _dumps(result))
        _ensure_decision_recorded(run_dir, result)
        #: What the transition buys is its replay key AND the mirror: the one
        #: transition that changes run state records the outcome, the decision
        #: and the two rows that index them, or none of the four.
        return mirrored

    locked_tracker_update(run_dir, transition_id=_QUORUM_TRANSITION + qid,
                          mutate=mutate)
    result = holder.get("result")
    if result is None:
        #: The transition replayed without ``mutate`` -- only reachable if this
        #: exact transition id was the last one applied, which means the
        #: outcome is on disk. Read rather than recomputed, for the reason the
        #: guard above exists.
        _event, result = _final_event(final_path, qid)
    return result


# --- the decision record ---------------------------------------------------
#
# ADOPTION SUPERSEDES; IT NEVER APPENDS BESIDE. ``templates/decisions.md`` says
# an axis holds at most one ``Adopted`` decision and ``parse_decisions``
# ENFORCES it, so a later adoption on an occupied axis flips the standing
# record to ``Status: Superseded`` AND appends the successor carrying
# ``Supersedes: <id>`` -- both halves, in one write.
#
# HALF A WRITE IS UNRECOVERABLE. The file is append-only: a second ``Adopted``
# record on one axis cannot be withdrawn, and a ``Superseded`` record with no
# successor cannot be completed. Either way the file stops parsing and every
# later read of the run is a read-only stop. So the whole new text is rendered,
# PARSED, and checked against what it was meant to say before one byte of it
# reaches disk.

#: The blank line that separates two records in ``decisions.md``.
_RECORD_GAP = "\n"


def _one_line(value) -> str:
    """Free text as a single field line, with no casefolding.

    ``_squash`` is the wrong helper: it casefolds, and these strings are an
    ANSWER and the things it forecloses -- prose a human reads back out of the
    audit trail. What must go is the NEWLINE: a decision field is one line, and
    a brain's answer is JSON that may legally hold as many as it likes, so an
    unfolded answer would end the record at its first line break and leave the
    rest of it parsed as prose between two decisions.
    """
    return " ".join(str(value).split())


def _decision_record(result: dict, supersedes) -> str:
    """One adopted quorum decision, in the grammar ``parse_decisions`` accepts.

    ``Consistent with`` CARRIES DECISION IDS AND NOTHING ELSE.
    ``_decision_anchors`` refuses anything that is not one, and a response's
    ``consistent_with`` legally holds ``spec`` and ``repo`` anchors whose ids
    are a spec line or a ``path:line``; writing those into this field is a
    record the parser refuses, which -- written first and validated second --
    would be a permanently unparseable audit trail. The field is omitted
    entirely when the answer anchored on no decision, because an anchor list
    that cannot be spelled is not the same fact as one that was empty.
    """
    winner = result["winner"]
    anchors = []
    for entry in winner["consistent_with"]:
        if entry.get("kind") != "decision":
            continue
        anchor = entry["id"].strip()
        if anchor not in anchors:
            #: Deduplicated: ``_decision_anchors`` refuses a repeat, because one
            #: citation is one claim of grounding and a repeat weights it double.
            anchors.append(anchor)
    lines = [
        "",
        f"## {result['decision_id']} — quorum answer on {result['decision_axis']}",
        "",
        f"- **Question:** {_one_line(result['question'])}",
        f"- **Axis:** {result['decision_axis']}",
        f"- **Answer:** {_one_line(winner['answer_key'])} — "
        f"{_one_line(winner['answer'])}",
        "- **Decision action:** quorum.adopt",
        "- **Provenance:** quorum",
        f"- **Depth:** {result['depth']}",
        f"- **Grounding rung:** {winner['rung']}",
        f"- **Runner-up rung:** {result['runner_up_rung'] or '-'}",
        "- **Consequences:** " + ", ".join(
            f"{item['kind']}:{_one_line(item['subject'])}"
            f"={_one_line(item['value'])}" for item in winner["consequences"]),
    ]
    if anchors:
        lines.append(f"- **Consistent with:** {', '.join(anchors)}")
    lines.extend([
        "- **Forecloses:** " + "; ".join(
            _one_line(entry) for entry in winner["forecloses"] if _text(entry)),
        f"- **Context digest:** {result['context_digest']}",
        f"- **Scope:** {', '.join(result['blocks'])}",
    ])
    if supersedes is not None:
        lines.append(f"- **Supersedes:** {supersedes}")
    lines.extend(["- **Status:** Adopted", ""])
    return "\n".join(lines)


def _retired(text: str, did: str) -> str:
    """``text`` with ``did``'s own ``Status`` flipped to ``Superseded``.

    THE ONE LEGAL IN-PLACE MUTATION, and it is half of a write whose other half
    is the successor record. Scoped to the target's OWN section rather than
    applied to the document, for ``_decision_section``'s reason: a status line
    found anywhere would retire whichever record happened to be read first.

    The line is rebuilt around the value rather than matched as a whole
    literal, because ``decisions.md`` carries two field spellings -- the
    emphasised one this phase writes and the plain one the shipped template
    writes -- and a writer that knew only its own would silently fail to retire
    a record a human had copied out of the template.
    """
    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and line[3:].split("—")[0].strip() == did:
            start = index
            break
    if start is None:
        raise TrackerValidationError(
            f"{did} stands adopted on this axis and the audit trail holds no "
            "such section; the retirement and the successor are one write, and "
            "half of it leaves a file that does not parse")
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    flipped = 0
    for index in range(start, end):
        parsed = _decision_field(lines[index].rstrip("\n"))
        if parsed is None or parsed[0] != "status":
            continue
        position = lines[index].rindex(parsed[1])
        lines[index] = (lines[index][:position] + "Superseded"
                        + lines[index][position + len(parsed[1]):])
        flipped += 1
    if flipped != 1:
        raise TrackerValidationError(
            f"{did} states its Status {flipped} times; the retirement half of "
            "the mutation has exactly one line to change, and a record with "
            "none or with two cannot be retired without guessing which")
    return "".join(lines)


def _rendered_decisions(result: dict, text: str, decisions: dict):
    """The whole of the new ``decisions.md``, or ``None`` when it is already on file.

    RENDERED AND VALIDATED BEFORE ANYTHING IS WRITTEN. Writing first and
    parsing afterwards puts a record the parser refuses into an append-only
    file and raises after the irreversible half has happened; every later read
    of the run is then a read-only stop, and the remedy the message prescribes
    -- reword one sentence -- means editing a file the parser will not let lose
    a record.

    AND THE PARSE IS CHECKED AGAINST WHAT THE RECORD WAS MEANT TO SAY. Parsing
    proves the file is readable; it does not prove it says the right thing. A
    consequence whose subject contains a comma, an answer whose key holds an em
    dash, a scope carrying a separator -- each of those renders a record that
    parses cleanly and asserts something the quorum never decided. Compared
    back, every one of them is refused here instead of being discovered by a
    contradiction check months later.
    """
    did = result["decision_id"]
    if did in decisions["decisions"]:
        #: Already on file. The append is idempotent because the repair path
        #: runs on every finalisation of an already-settled quorum, and a
        #: second append would put two records under one heading -- which
        #: ``_decision_sections`` refuses outright.
        return None
    axis = result["decision_axis"]
    standing = [other for other in decisions["axis_index"].get(axis, ())
                if decisions["decisions"][other]["status"] == "Adopted"]
    supersedes = None
    if standing:
        #: ``parse_decisions`` has already refused a file holding two, so this
        #: list is one long. SUPERSEDE, NEVER APPEND BESIDE: a second Adopted
        #: record on one axis is a file that stops parsing, and the axis index
        #: has one Decision column and cannot say which of the two binds.
        supersedes = standing[0]
    updated = text
    if supersedes is not None:
        updated = _retired(updated, supersedes)
    if updated and not updated.endswith("\n"):
        updated += "\n"
    updated = updated + _RECORD_GAP + _decision_record(result, supersedes)
    parsed = parse_decisions(updated)
    _assert_records_what_was_decided(parsed, result, supersedes)
    return updated


def _assert_records_what_was_decided(parsed: dict, result: dict,
                                     supersedes) -> None:
    """The rendered record, read back and compared with the outcome it states.

    A round trip rather than a second rendering: the fields this checks are the
    ones a later reader ROUTES on -- the axis it is bucketed under, the key it
    answers with, the consequences a contradiction is measured by, the depth
    the cap is measured by -- and every one of them can be made to parse
    cleanly while saying something else by a separator inside a value nobody
    escaped.
    """
    did = result["decision_id"]
    record = parsed["decisions"].get(did)
    if record is None:
        raise TrackerValidationError(
            f"the rendered record for {did} does not read back as a decision; "
            "a heading the parser does not recognise is a decision written "
            "into the audit trail that no task can ever cite")
    winner = result["winner"]
    expected = {(item["kind"], _one_line(item["subject"])):
                _one_line(item["value"]) for item in winner["consequences"]}
    mismatches = []
    if record["axis"] != result["decision_axis"]:
        mismatches.append(f"axis {record['axis']!r}")
    if record["answer_key"] != _one_line(winner["answer_key"]):
        mismatches.append(f"answer key {record['answer_key']!r}")
    if record["depth"] != result["depth"]:
        mismatches.append(f"depth {record['depth']!r}")
    if record["status"] != "Adopted":
        mismatches.append(f"status {record['status']!r}")
    if record["consequences"] != expected:
        mismatches.append(f"consequences {sorted(record['consequences'])}")
    if record.get("supersedes", "").strip() != (supersedes or ""):
        mismatches.append(f"supersedes {record.get('supersedes')!r}")
    if mismatches:
        raise TrackerValidationError(
            f"the rendered record for {did} reads back as {mismatches}, which "
            "is not what this quorum decided; a separator inside a value -- a "
            "comma in a subject, an em dash in an answer key -- renders a "
            "record that parses cleanly and asserts something else, and the "
            "file is append-only")


def _ensure_decision_recorded(run_dir: Path, result: dict) -> None:
    """Append the adopted decision if it is not already on file. Idempotent.

    Called with the run lock held, on both the finalising path and the repair
    path: ``decisions.md`` is one run-global file, and two finalisations
    appending at once lose one of the two decisions while both report success.
    """
    if result.get("status") != _CHARGED_STATUS:
        #: Only an adoption writes. An escalation is the run asking for help
        #: and a rejection adopted nothing; recording either as a decision
        #: would put an answer in the trail that nothing decided.
        return
    text = _decisions_text(run_dir)
    decisions = parse_decisions(text)
    updated = _rendered_decisions(result, text, decisions)
    if updated is None:
        return
    _write_run_file(run_dir / _DECISIONS_FILE, updated,
                    "the decisions audit trail")


# ---------------------------------------------------------------------------
# P04: the phase-plan metadata grammar.
#
# THE KEY ORDER IS PINNED. A reordered, renamed, missing or extra key is a
# ``PlanMetadataError``, never a best-effort parse. This is the whole point of
# the format: a phase plan has to be machine-readable STRUCTURE rather than
# prose a worker may reinterpret, and an order-insensitive reader gives that up
# for nothing. Two parties read this comment -- the controller that dispatches
# the phase and the human who audits it afterwards -- and an unordered bag of
# keys is ambiguous to the second one even when the first one copes. The writer
# is bound by the same pin: there is exactly one legal spelling of a phase
# header, so two plans that say the same thing are byte-identical there.
#
# ``review_class`` REPLACES v2's ``review_gate``. The rename is not cosmetic:
# the old key named a boolean gate, the new one carries the review-intensity
# dial value, and a plan still spelling ``review_gate`` is a v2 plan being fed
# to a v1 reader. There is no migration in either direction, so it is refused
# rather than translated.
# ---------------------------------------------------------------------------

#: The review-intensity dial's vocabulary, PUBLIC under the name P05 and P06
#: cite. It is P02's tuple, aliased and not re-typed: ``_validate_phases``
#: already judges the ``Review Class`` cell against ``_REVIEW_CLASSES``, and a
#: second literal here would be a second, divergable source of truth for one
#: enum -- the same defect as a phase re-declaring another phase's columns, and
#: the one the tracker column contract exists to forbid. Aliasing makes drift
#: unspellable rather than merely discouraged.
REVIEW_CLASSES = _REVIEW_CLASSES

#: The comment names, spelled once. ``pipeline-auto-phase`` and
#: ``pipeline-auto-phase-suite`` share a prefix, so every predicate below
#: includes the trailing ``:`` -- without it a suite line is detected as a
#: malformed phase line and the count check fires on the wrong comment.
_PHASE_COMMENT = "pipeline-auto-phase"
_PHASE_SUITE_COMMENT = "pipeline-auto-phase-suite"

#: THE PIN. Not a set, not a mapping: a tuple, because the position of each key
#: is as much a part of the grammar as its name.
_PHASE_KEYS = ("id", "deps", "review_class", "review_reason")
_PHASE_SUITE_KEYS = ("id", "commands")

#: The spelling of "this phase depends on nothing". A bare empty value would be
#: indistinguishable from a key whose value was dropped in an edit.
_NO_DEPS = "none"

_FIELD_SEPARATOR = "; "

#: ASCII control characters, including NUL. They are refused everywhere below
#: for two different reasons that happen to have one check: a cell holding a
#: newline parses back as a different number of ROWS, and a command string
#: holding a NUL raises ``ValueError: embedded null byte`` from the subprocess
#: layer -- outside ``TrackerError`` -- when the suite is eventually run.
#:
#: THIS LIST IS HALF THE RULE, AND IT IS NOT THE ROW-BREAK HALF. Closed on
#: purpose: ``\x00`` and ``\t`` break a subprocess and a cell's width without
#: breaking a LINE, so no reader derives them and they have to be named. The
#: characters that add a ROW are asked of ``_splits_the_section`` instead --
#: an earlier ``_cell_safe`` screened on this constant ALONE and let ``\x85``,
#: ``\u2028`` and ``\u2029`` through, three row breaks no ``range(0x20)`` can
#: contain. That is the closed-list defect ``_splits_the_section`` was written
#: to end, re-declared one layer up and paid for twice.
_CONTROL_CHARACTERS = frozenset(chr(code) for code in range(0x20)) | {"\x7f"}


def _survives_the_encoder(value: str) -> bool:
    """Can ``value`` be written to a UTF-8 file, or handed to a subprocess?
    ASKED, NOT LISTED, for the reason ``_splits_the_section`` asks.

    A JSON ``\\uXXXX`` escape MINTS A LONE SURROGATE out of bytes that are pure
    ASCII on disk: ``commands=["make \\ud800 check"]`` is a plain-ASCII plan
    file whose parsed command cannot be encoded at all. Nothing fails at the
    parse; it fails one layer along, as ``UnicodeEncodeError`` out of the file
    write or the subprocess spawn -- and ``UnicodeEncodeError`` is a
    ``ValueError``, outside ``TrackerError``. That is precisely the escape this
    grammar's "raises ``PlanMetadataError`` and nothing else" promise exists to
    close, arriving from the one direction a plan's own bytes look innocent.

    The ENCODER is asked rather than a surrogate range written down, because
    the question is "will the thing that encodes this refuse it", and the only
    answer that cannot drift from the encoder is the encoder's own.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True

#: Shell/glob metacharacters a repository-relative path may not carry. A plan
#: that declares ``src/*.py`` as a write scope has declared a set whose members
#: depend on when it is expanded, which is not a scope two implementers can be
#: checked against for overlap.
_GLOB_CHARACTERS = "*?[]{}"


def _cell_safe(value: str) -> bool:
    """A string a pipe-delimited tracker cell carries back out unchanged.

    Four properties, all of them round-trip properties rather than taste:

    * no ``|``, which would parse back as a different number of COLUMNS;
    * nothing the section reader breaks a LINE on, which would parse back as a
      different number of ROWS, and no ASCII control character, which would
      additionally blow up the subprocess that runs the command;
    * nothing the UTF-8 encoder refuses, which would raise from outside
      ``TrackerError`` at the write or the spawn that follows;
    * no surrounding whitespace, because a cell's contents are stripped on the
      way in, so ``" a"`` and ``"a"`` are the same cell and only one of them is
      what the plan said.

    THE ROW-BREAK HALF IS ASKED, NOT LISTED, AND THE TWO HALVES ARE A UNION
    rather than a choice. ``_CONTROL_CHARACTERS`` alone lets ``\x85``,
    ``\u2028`` and ``\u2029`` past -- three characters ``str.splitlines``
    breaks on, so a cell holding one comes back as two rows of the wrong width,
    and ``_parse_phase_header`` would hand a controller a value P03's own
    ``_cell`` writer refuses. ``_splits_the_section`` alone loses ``\x00`` and
    ``\t``, which break a subprocess and a cell's width without breaking a
    line. Neither half is the rule; both together are.

    ``,`` IS DELIBERATELY NOT REFUSED HERE, and that is a ruling rather than an
    oversight. ``_CELL_SEPARATORS`` names the comma because it re-columns a
    MULTI-VALUED cell, and this screen is shared by values that are not all
    multi-valued: ``review_reason`` is one free-text cell a human auditor
    reads, and ordinary English prose carries commas. The comma bar therefore
    belongs on the writer that KNOWS a cell is list-valued -- ``_cell_list`` --
    not on a value screen that cannot know.

    THREE WRITERS NOW KNOW, and each carries the bar: ``_cell_list``, which
    joins the members; ``_table_safe(list_valued=True)``, for a worker result's
    list fields; and ``_safe_relative``, because a repository-relative path is
    never the free-text case this screen kept the comma for -- every cell this
    module writes one into is read back with ``_csv``. ``_safe_relative``'s own
    note records why that bar arrived late and what it cost.
    """
    return (isinstance(value, str)
            and "|" not in value
            and not (_CONTROL_CHARACTERS & set(value))
            and not any(_splits_the_section(character) for character in value)
            and _survives_the_encoder(value)
            and value == value.strip())


def _comment_fields(line, name: str, keys: tuple, *, tail: bool) -> tuple:
    """``<!-- name: k1=v1; k2=v2 -->`` -> ``(v1, v2)``, order PINNED.

    The keys are matched positionally against ``keys``. A reordered key fails
    at the position that should have held it, a renamed one fails at its own
    position, a missing one shifts every later key onto the wrong position, and
    an extra one either makes the field count wrong or -- for the one comment
    with a free-text tail -- lands inside the tail where the caller's own value
    check refuses it. That is four distinct defects refused by one mechanism,
    which is why this is positional and not a dict comprehension over splits.

    ``tail`` says whether the LAST value may itself contain the field
    separator. It may for ``commands``, whose JSON legitimately carries
    ``"; "`` inside a shell string; it may not for ``review_reason``, so that a
    fifth key appended after it cannot be absorbed into the reason silently.

    THE TWO ANCHORS DO THE WHITESPACE WORK, and there is deliberately no
    separate ``line == line.strip()`` clause beside them, and no minimum-length
    clause either: ``startswith`` on the full opening refuses an indented
    comment, ``endswith`` on the full closing refuses a trailing-space one, and
    a body too short to hold a field is refused by the field COUNT a line
    later. Each would be a screen no input can reach, and an unreachable screen
    reads, to the next person, as a guarantee something is being checked here
    that is not. What makes the indented copy safe is upstream, in
    ``_comment_indexes``: it DETECTS on the stripped line so an indented copy
    is counted and then refused here, rather than being invisible to the
    "exactly once" count.

    THE BODY MAY NOT ITSELF SPELL A COMMENT DELIMITER. An HTML comment ends at
    the FIRST ``-->``, so ``review_reason=a --> b`` is one byte string with two
    readings: every markdown reader -- and the human auditor the reason exists
    for -- sees the comment end early and the rest of the line as document
    text, while this parser alone sees the whole value. ``<!--`` is refused for
    the mirror reason. Two plans that say the same thing are byte-identical
    here; a value that re-opens or closes the comment breaks that, and it
    breaks it in the direction where the machine and the human disagree.
    """
    opening = f"<!-- {name}: "
    closing = " -->"
    if (not isinstance(line, str)
            or not line.startswith(opening)
            or not line.endswith(closing)):
        raise PlanMetadataError(
            f"a {name!r} metadata comment must be exactly "
            f"{opening}<fields>{closing} on a line of its own, with no leading "
            f"or trailing whitespace; got {line!r}")
    body = line[len(opening):len(line) - len(closing)]
    if "-->" in body or "<!--" in body:
        raise PlanMetadataError(
            f"a {name!r} metadata comment's fields may not spell a comment "
            f"delimiter: {body!r} carries '-->' or '<!--', so a markdown "
            "reader ends the comment at the first one and shows the rest as "
            "document text, while this parser reads the whole line as "
            "metadata. One byte string, two readings")
    parts = (body.split(_FIELD_SEPARATOR, len(keys) - 1) if tail
             else body.split(_FIELD_SEPARATOR))
    if len(parts) != len(keys):
        raise PlanMetadataError(
            f"a {name!r} metadata comment carries exactly {len(keys)} keys "
            f"separated by {_FIELD_SEPARATOR!r}, in the order "
            f"{list(keys)}; got {len(parts)} in {body!r}")
    values = []
    for position, (key, part) in enumerate(zip(keys, parts), start=1):
        prefix = f"{key}="
        if not part.startswith(prefix):
            raise PlanMetadataError(
                f"{name!r} key {position} of {len(keys)} must be {key!r}: the "
                f"key order is PINNED to {list(keys)} and a key that is merely "
                f"PRESENT is not enough, because the order is what makes the "
                f"grammar unambiguous to a reader and a writer alike; got "
                f"{part!r}")
        values.append(part[len(prefix):])
    return tuple(values)


def _parse_command_suite(raw: str) -> tuple[str, ...]:
    """The ``commands=[...]`` value: a JSON array of table-safe command strings.

    ``_loads`` rather than ``json.loads``, and not as a style choice: it is the
    single condition on which ``json`` entered ``ALLOWED_IMPORTS``, and a
    committed AST test asserts that the module's only ``json.loads`` caller is
    ``_loads``. Its ``QuorumSchemaInvalid`` is re-raised as the exception this
    grammar promises, so a controller catching ``PlanMetadataError`` around a
    plan read does not have to also know about the quorum family.

    Every element is checked BEFORE ``set(values)`` is built. A JSON array may
    legally hold an object or an array, both unhashable, and hashing one would
    raise ``TypeError`` from outside ``TrackerError`` -- the bare-``in`` failure
    one layer along.
    """
    try:
        values = _loads(raw, "a phase verification command suite")
    except TrackerError as exc:
        raise PlanMetadataError(
            "a verification command suite must be a JSON array of strings; "
            f"{raw!r} is not readable JSON ({exc})") from exc
    if not isinstance(values, list) or not values:
        raise PlanMetadataError(
            "a verification command suite must be a NONEMPTY JSON array; a "
            "phase that declares no command declares that nothing verifies it, "
            f"which is not the same as a phase nobody wrote a suite for: {raw!r}")
    for value in values:
        if not isinstance(value, str) or not value.strip() or not _cell_safe(value):
            raise PlanMetadataError(
                "every verification command is a nonempty table-safe string: "
                "no '|', nothing the section reader breaks a line on, no "
                "control character, nothing the UTF-8 encoder refuses -- a "
                "JSON escape mints a lone surrogate from pure-ASCII bytes and "
                "the spawn, not the parse, is where it would have raised -- "
                f"and no surrounding whitespace; got {value!r}")
    if len(values) != len(set(values)):
        raise PlanMetadataError(
            "a verification command suite names each command once; a repeat "
            "makes the suite's length disagree with the number of things it "
            f"checks: {list(values)!r}")
    return tuple(values)


def _safe_relative(value) -> PurePosixPath:
    """A repository-relative path a plan may declare, normalised to POSIX.

    THE SEGMENTS ARE CHECKED RAW, never through ``PurePosixPath.parts``, and
    that is the whole trick. ``PurePosixPath`` NORMALISES on construction:
    ``PurePosixPath("src/./a").parts`` is ``('src', 'a')`` and
    ``PurePosixPath("a//b").parts`` is ``('a', 'b')``, so a ``.`` or an empty
    segment is gone before any check over ``parts`` can see it. Two spellings
    that differ in bytes would then both be accepted and recorded as the same
    scope, and the tracker cell would no longer say what the plan said.

    ``..`` survives normalisation and is refused for the obvious reason; ``\\``
    is refused because a Windows-spelled path is a single segment here and
    would escape the repository on the machine that wrote it; a glob character
    is refused because a scope whose membership depends on when it is expanded
    cannot be checked for overlap against another scope.

    AN ABSOLUTE PATH IS REFUSED BY THE SEGMENT LOOP, not by a leading-``/``
    clause of its own: ``"/abs".split("/")`` is ``["", "abs"]``, so the empty
    first segment is already the refusal. The separate clause that used to
    stand here was a screen no input could reach, and an unreachable screen
    reads as a guarantee that something is being checked here which is not --
    the same ruling that removed ``line != line.strip()`` from
    ``_comment_fields``.

    ``_CELL_SEPARATORS`` IS REFUSED WHOLE, AND THAT SUPERSEDES TASK 2'S RULING
    THAT NO COMMA SCREEN BELONGS HERE. Task 2 argued -- correctly, for the
    direction it could see -- that ``_parse_write_scope`` SPLITS on the comma
    before it ever calls this, so from a scope cell a comma-bearing path is not
    a smuggled value but two members, the second refused on its own merits; a
    screen here would then be one no input could reach. What that argument
    could not see is the OTHER direction. A repository-relative path does not
    only come out of a list cell one member at a time; Tasks 6 and 10 put one
    IN, whole and unsplit, from two sources no split ever touches -- a run
    directory's NAME (``_citable_repo_relative``) and a worker document's
    reference field (``_digest_reference``). There the comma is reachable, and
    it was reached: a worker checkpoint's evidence spelled
    ``e/x,attempt-002,attempt-003,baseline:attempt-001@<40 hex>,y.md``
    ``#sha256=<64 hex>`` is appended verbatim to the comma-separated
    ``Checkpoints`` cell, where ``_csv`` reads the injected members back as two
    spent attempt tokens and a SECOND baseline for the attempt just completed.
    The attempt the forged ``baseline:`` names is load-bearing and is the
    COMPLETED one: ``reserved_baseline`` requires exactly one marker per
    attempt, so a second for ``attempt-001`` makes the finished attempt's own
    anchor unreadable to every later phase, while a marker naming some other
    attempt would sit there inert. Both halves land in one value:
    ``reserved_baseline`` refuses the row for ever and ``_require_fresh_attempt``
    refuses every resume, on a row the run has already marked complete. A run directory spelled ``runs/run,1`` splits the
    ``Result`` cell the same way and with it the "an exact replay is inert"
    contract. One character, three cells, and the bar is one screen.

    THE WHOLE CONSTANT IS ASKED RATHER THAN THE COMMA WRITTEN DOWN, and it
    leads ``_cell_safe`` rather than trailing it. ``_CELL_SEPARATORS`` is the
    module's own statement of "the characters that re-column a row, and the
    whole of them"; asking it means a third separator added there is refused
    here without this line being touched, and means this screen does not rest
    on ``_cell_safe`` continuing to refuse ``|`` for its own, different reason.
    The row-break half is NOT copied from it -- that half is asked of the
    reader inside ``_cell_safe``, which this still calls.

    A PATH IS NEVER THE FREE-TEXT CASE ``_cell_safe`` KEPT THE COMMA FOR.
    ``_cell_safe`` admits a comma because it is shared with ``review_reason``
    and ``concerns``, prose a human reads and English punctuates. A
    repository-relative path is the opposite: every cell this module writes one
    into -- ``phase_plans``, ``Result``, ``Checkpoints``, ``Verification``,
    ``evidence``, the scope cells -- is read back with ``_csv``. So this IS the
    writer that knows its value is a list member, which is exactly where
    ``_cell_safe``'s own note said the bar belongs.
    """
    if not isinstance(value, str) or not value:
        raise PlanMetadataError(
            f"a repository-relative path must be a nonempty string: {value!r}")
    #: FOUR REFUSALS AND NOT ONE, because a corpus over this grammar has to be
    #: able to assert WHICH rule it tripped. The single message that used to
    #: stand here named all four clauses for every input, so a NUL and a glob
    #: character produced byte-identical prose and a totality corpus asserting
    #: "the diagnosis" was asserting a constant. Each clause now says the one
    #: thing that is true of its own input.
    if any(character in value for character in _CELL_SEPARATORS):
        raise PlanMetadataError(
            f"unsupported repository-relative path: {value!r}; it carries one "
            f"of {_CELL_SEPARATORS!r}, which re-column a tracker row -- a path "
            "holding one comes back out of its cell as two members, both of "
            "which parse, so the cell says something nobody wrote")
    if "\\" in value:
        raise PlanMetadataError(
            f"unsupported repository-relative path: {value!r}; it is not "
            "POSIX-spelled, and a Windows-spelled path is ONE segment here, so "
            "every segment rule below reads it as a single name and it escapes "
            "the repository on the machine that wrote it")
    if any(character in value for character in _GLOB_CHARACTERS):
        raise PlanMetadataError(
            f"unsupported repository-relative path: {value!r}; it carries a "
            f"glob character ({_GLOB_CHARACTERS!r}), so what it names is a SET "
            "whose members depend on when it is expanded, and two scopes like "
            "that cannot be checked against each other for overlap")
    if not _cell_safe(value):
        raise PlanMetadataError(
            f"unsupported repository-relative path: {value!r}; it carries "
            "something a tracker cell cannot hold -- a '|', an ASCII control "
            "character, something the section reader breaks a LINE on, "
            "something the UTF-8 encoder refuses, or surrounding whitespace")
    for segment in value.split("/"):
        if segment in ("", ".", "..") or segment != segment.strip():
            raise PlanMetadataError(
                f"unsupported repository-relative path: {value!r}; the segment "
                f"{segment!r} is empty, a traversal, or whitespace-padded, and "
                "pathlib would normalise the first two away before any check "
                "over .parts could see them")
    return PurePosixPath(value)


def _comment_indexes(lines, name: str) -> list:
    """Every line that CLAIMS to be a ``name`` comment, by index.

    Detection is on the stripped line and validation is on the raw one, so an
    indented copy is COUNTED -- and then refused by ``_comment_fields`` --
    rather than being invisible to the count. A detector that missed it would
    let a second phase header hide in the file behind two spaces.
    """
    opening = f"<!-- {name}:"
    return [index for index, line in enumerate(lines)
            if line.strip().startswith(opening)]


def _parse_phase_header(lines) -> dict:
    """The phase-plan document header: two comments, in order, keys pinned.

    Returns ``{"id", "deps", "review_class", "review_reason", "commands"}``.
    Raises ``PlanMetadataError`` and nothing else, for every input: this reads
    a file an agent wrote, and a plan grammar that can throw ``AttributeError``
    at a controller has not refused the plan, it has crashed on it.

    It reads NO FILE. The caller has already opened the plan -- through
    ``_require_regular_file``, which is the door every run-directory read uses
    -- and hands the split lines in. Keeping the read out of here is what lets
    the grammar be tested without a filesystem at all, and it means this
    function has no way to be the thing that blocks on a FIFO.
    """
    if isinstance(lines, str) or not isinstance(lines, (list, tuple)):
        raise PlanMetadataError(
            "a phase header is parsed from the plan's LINES: a list of "
            "strings, not the document text (a string is iterable by "
            f"character and would parse as a file of one-character lines); got "
            f"{type(lines).__name__}")
    for index, line in enumerate(lines):
        if not isinstance(line, str):
            raise PlanMetadataError(
                f"plan line {index} is {type(line).__name__}, not a string")

    phase_indexes = _comment_indexes(lines, _PHASE_COMMENT)
    if len(phase_indexes) != 1:
        raise PlanMetadataError(
            f"a phase plan carries exactly one {_PHASE_COMMENT!r} metadata "
            f"comment; this one carries {len(phase_indexes)}. Zero means the "
            "plan is prose a worker would have to interpret; two means two "
            "answers to 'what is this phase' with nothing to choose between "
            "them")
    phase_index = phase_indexes[0]

    first_nonempty = next((line for line in lines if line.strip()), "")
    title = first_nonempty[2:] if first_nonempty.startswith("# ") else ""
    if not title.strip() or title.lstrip().startswith("#"):
        raise PlanMetadataError(
            "a phase plan opens with a level-one markdown title before its "
            f"metadata; the first nonempty line is {first_nonempty!r}")
    #: DETECTED ON THE STRIPPED LINE, exactly as ``_comment_indexes`` detects
    #: its comments, and for the same reason: CommonMark allows up to three
    #: leading spaces on an ATX heading, so a raw ``startswith`` here lets a
    #: plan open ``   ## Overview`` above its metadata and the "metadata
    #: precedes the first section" bar -- fault F8's placement half -- is
    #: cleared by adding two spaces. A defence that strips on one side of a
    #: comparison and not the other is not a defence.
    first_section = next(
        (index for index, line in enumerate(lines)
         if line.strip().startswith("## ")),
        len(lines))
    if phase_index >= first_section:
        raise PlanMetadataError(
            f"the {_PHASE_COMMENT!r} comment is on line {phase_index} and the "
            f"first '## ' section opens on line {first_section}: the metadata "
            "belongs to the DOCUMENT, so it lives in the document header, "
            "before the first section. Inside a section it reads as that "
            "section's metadata")

    phase_id, raw_deps, review_class, review_reason = _comment_fields(
        lines[phase_index], _PHASE_COMMENT, _PHASE_KEYS, tail=False)

    if not _TOKEN.fullmatch(phase_id):
        raise PlanMetadataError(
            f"invalid phase id {phase_id!r}: a phase id is one token")
    if not _member(review_class, REVIEW_CLASSES):
        raise PlanMetadataError(
            f"review_class {review_class!r} is outside {list(REVIEW_CLASSES)!r}; "
            "there is no partial dial setting, and an unknown value is not "
            "quietly the cheaper one")
    if not _text(review_reason) or not _cell_safe(review_reason):
        raise PlanMetadataError(
            f"review_reason {review_reason!r} must be nonempty table-safe text: "
            "the class is a claim about this phase and the reason is the claim's "
            "justification, which is what a human audits afterwards")

    deps = () if raw_deps == _NO_DEPS else tuple(raw_deps.split(","))
    for dep in deps:
        if not _TOKEN.fullmatch(dep):
            raise PlanMetadataError(
                f"invalid phase dependency id {dep!r} in deps={raw_deps!r}; "
                f"a phase that depends on nothing spells it {_NO_DEPS!r}")
        if dep == _NO_DEPS:
            raise PlanMetadataError(
                f"deps={raw_deps!r} mixes {_NO_DEPS!r} with real dependencies; "
                "'depends on nothing' and 'depends on a phase called none' "
                "cannot both be spelled the same way")
        if dep == phase_id:
            raise PlanMetadataError(
                f"phase {phase_id!r} lists itself in deps={raw_deps!r}; a phase "
                "waiting on itself never becomes dispatchable")
    if len(deps) != len(set(deps)):
        raise PlanMetadataError(
            f"deps={raw_deps!r} names a dependency twice; a repeat makes the "
            "dependency count disagree with the number of phases waited on")

    suite_indexes = _comment_indexes(lines, _PHASE_SUITE_COMMENT)
    if len(suite_indexes) != 1 or suite_indexes[0] != phase_index + 1:
        raise PlanMetadataError(
            f"exactly one {_PHASE_SUITE_COMMENT!r} comment occurs on the line "
            f"IMMEDIATELY after the {_PHASE_COMMENT!r} comment; found "
            f"{len(suite_indexes)} at {suite_indexes} against a phase comment "
            f"on line {phase_index}. Separated by so much as a blank line, the "
            "two comments are two independent claims and an edit can move one "
            "without the other")
    suite_id, raw_commands = _comment_fields(
        lines[suite_indexes[0]], _PHASE_SUITE_COMMENT, _PHASE_SUITE_KEYS,
        tail=True)
    if suite_id != phase_id:
        raise PlanMetadataError(
            f"the phase suite names {suite_id!r} and the phase metadata names "
            f"{phase_id!r}: a suite belonging to another phase would verify "
            "that phase and report the result against this one")

    return {
        "id": phase_id,
        "deps": deps,
        "review_class": review_class,
        "review_reason": review_reason,
        "commands": _parse_command_suite(raw_commands),
    }


#: The task comment names, spelled once. ``pipeline-auto-task`` is a PREFIX of
#: ``pipeline-auto-task-suite``, so -- exactly as ``_PHASE_COMMENT`` is a prefix
#: of ``_PHASE_SUITE_COMMENT`` -- every predicate below goes through
#: ``_comment_indexes``, whose opening carries the trailing ``:``. Without it a
#: suite line is detected as a malformed task line and the count check fires on
#: the wrong comment.
_TASK_COMMENT = "pipeline-auto-task"
_TASK_SUITE_COMMENT = "pipeline-auto-task-suite"

#: THE PIN, the task half. A tuple for ``_PHASE_KEYS``' reason: the POSITION of
#: each key is as much a part of the grammar as its name, and F8 is a plan whose
#: keys were reordered, renamed or dropped. Seven keys, checked positionally by
#: ``_comment_fields``, so a reorder fails at the position that should have held
#: the key, a rename fails at its own position, a drop shifts every later key
#: onto the wrong position, and an extra key makes the field count wrong.
_TASK_KEYS = ("id", "deps", "kind", "batch", "order", "write_scope", "outputs")
_TASK_SUITE_KEYS = ("id", "commands")

#: THE GRAMMAR FOR AN ID THAT BECOMES A NAME ON A FILESYSTEM, ALIASED rather
#: than re-typed. ``_validate_assignment`` already states the whole argument
#: for the owner: ``_TOKEN`` "would admit ``/``, ``:``, ``@`` and ``+`` into a
#: name that becomes a path, and a trailing dot into one that becomes a
#: filename." A task id that becomes a DIRECTORY name raises exactly that
#: question, so it gets exactly that answer, and a second ``_CharClass``
#: written beside it would be two grammars that can drift.
_PATH_SEGMENT = _OWNER

#: THE SUFFIX GIT RESERVES FOR ITSELF. ``git check-ref-format`` refuses any ref
#: component ending in ``.lock``, because that is the name it gives the lock
#: file it takes beside the ref while updating it.
_REF_LOCK_SUFFIX = ".lock"


class _RefComponent:
    """A ``_PATH_SEGMENT`` that ``git check-ref-format`` also accepts.

    A WRAPPER rather than two more options on ``_CharClass``, for ``_Owner``'s
    reason: both extra rules are about THIS grammar becoming one component of
    a git ref, and ``_TOKEN``, ``_RUN_ID`` and ``_ABS_PATH`` would each have to
    be asked the question separately before inheriting an answer. ``_TOKEN`` in
    particular must NOT inherit it -- it is shared with ``target_branch``,
    ``phase_id``, ``axis``, ``batch``, ``reviewer`` and ``dep``, and a branch
    name is a ref of several components that legitimately carries ``/``.

    THE TWO RULES ARE GIT'S, MEASURED AND NOT GUESSED. ``git
    check-ref-format`` refuses ``refs/heads/T..1`` and ``refs/heads/T.lock``
    while accepting every other string ``_PATH_SEGMENT`` admits, so these are
    the whole of the residue between the two grammars. Both are otherwise
    perfectly good FILENAMES -- ``T..1`` is one directory component and
    traverses nothing -- which is precisely why the path grammar cannot be
    asked to catch them and why they get their own screen here.
    """

    __slots__ = ("_body",)

    def __init__(self, body) -> None:
        self._body = body

    def fullmatch(self, value: str) -> bool:
        return (self._body.fullmatch(value) and ".." not in value
                and not value.endswith(_REF_LOCK_SUFFIX))


#: THE ONE TASK-ID GRAMMAR, AND IT IS THE INTERSECTION OF EVERY NAME A TASK ID
#: BECOMES. The plan grammar's own refusal already says what those are -- a
#: task id "is written into a tracker cell, A BRANCH NAME and a checkpoint
#: marker" -- and ``worker_result_path`` adds a fourth: a directory under
#: ``agent-output/``. Held only to ``_TOKEN``, a plan could legally declare
#: ``T/1``, ``T:1``, ``T@1``, ``T+1``, ``T1.``, ``T..1``, ``T1.lock`` or a
#: 65-character id; ``reserve_task`` would ACCEPT it, so the slot is held
#: against the ``worker_limit - 3`` implementation cap -- and then nothing can
#: terminate it, because the one helper a worker may call to publish its result
#: refuses the id and ``git check-ref-format`` refuses the branch. That is F2's
#: permanent deadlock reached from a phase plan that is legal by the grammar
#: the plan publishes, and the failure arrives AFTER the work is done.
#:
#: SO IT IS REFUSED AT PLAN IMPORT, where nothing is reserved yet, and again at
#: reservation as defence in depth. Widening publication instead would only
#: move the dead end to the phase that builds the branch, by which time work
#: has already merged.
_TASK_ID = _RefComponent(_PATH_SEGMENT)

#: What a task PRODUCES, and the reason the plan says it rather than the worker.
#: A ``source`` task changes the repository and is proved by running its
#: verification suite; an ``artifact`` task writes documents and is proved by
#: those documents existing. A worker may not demote itself from ``source`` to
#: ``artifact`` because its implementation happened to produce no diff -- "I
#: changed nothing" and "I was never asked to change anything" are different
#: claims, and only the second is one the plan made.
TASK_KINDS = ("source", "artifact")

#: The two typed write-scope forms. ``file:`` is one exact path; ``tree:`` is a
#: directory and everything under it. Task 3's ``scopes_overlap`` reads this
#: tuple rather than re-typing the pair.
_WRITE_SCOPE_TYPES = ("file", "tree")

#: A phase plan holds between one and twelve tasks. Zero means the phase plan is
#: prose a worker would have to interpret into work, which is the thing this
#: grammar exists to stop; the ceiling is here because every task in a phase is
#: reconciled, integrated and range-checked against the same baseline, and a
#: plan that needs more than twelve is two phases that were not split.
MAX_TASKS_PER_PHASE = 12

#: HOW MANY DIGITS AN ORDER MAY BE SPELLED WITH, and it is a SPELLING ceiling
#: rather than a value rule. CPython caps integer<->string conversion at
#: ``sys.int_max_str_digits`` (4300 by default), so ``int(raw_order)`` on a
#: long run of ordinary ASCII digits raises ``ValueError`` -- which is not a
#: ``TrackerError``, and a plan grammar that throws ``ValueError`` at a
#: controller has crashed on the plan rather than refused it. The screen has to
#: bound the string BEFORE the conversion is reachable.
#:
#: TWO DIGITS BECAUSE A PHASE HOLDS AT MOST ``MAX_TASKS_PER_PHASE`` TASKS, so
#: no order in a legal plan needs more digits than the largest task count does.
#: The slack it leaves -- ``order=99`` is accepted and ``order=100`` is not --
#: is deliberate, and the reason it is not tightened into ``order <=
#: MAX_TASKS_PER_PHASE`` is that the value rule would make the task-count
#: ceiling UNREACHABLE: thirteen tasks cannot carry thirteen strictly
#: increasing orders all at most twelve, so the count check would become dead
#: code and the ceiling would be enforced by the wrong diagnosis. Orders are
#: also deliberately allowed to be non-contiguous, so a value rule would be a
#: second, contradicting statement about what an order means.
_MAX_ORDER_DIGITS = len(str(MAX_TASKS_PER_PHASE))


def _declared_members(raw: str, what: str) -> tuple[str, ...]:
    """A comma-separated metadata field, or the literal ``none`` meaning empty.

    ``none`` IS A WHOLE VALUE AND NEVER A MEMBER, which is the guard Task 1
    wrote for phase ``deps`` and which the task grammar needs three times over.
    Without it ``outputs=none,docs/a.md`` reads as two members, the first of
    which is a perfectly legal repository-relative path spelled ``none`` -- so
    an artifact task declaring "no outputs, and also this one" is accepted and
    the run later looks for a file called ``none``. "Declares nothing" and
    "declares a thing called none" cannot both be spelled the same way.

    An EMPTY member is refused for the same reason a trailing comma is a typo
    rather than a value: ``file:src/a.py,`` would otherwise reach the type check
    as ``''`` and be diagnosed as an untyped scope, which names the wrong line
    of the plan.

    THE DUPLICATE CHECK IS HERE, ON THE RAW MEMBERS, and deliberately not
    repeated on the canonical forms downstream. ``_safe_relative`` admits
    exactly one spelling per path -- ``.``-segments, ``//``, a trailing ``/``
    and a backslash are all refused -- so two raw members that canonicalise
    equal are two raw members that were already equal, and a second check over
    the canonical list would be a screen no input can reach.
    """
    if raw == _NO_DEPS:
        return ()
    members = tuple(raw.split(","))
    for member in members:
        if not member:
            raise PlanMetadataError(
                f"{what}={raw!r} has an empty member: a comma separates two "
                "values and a dangling one separates a value from nothing")
        if member == _NO_DEPS:
            raise PlanMetadataError(
                f"{what}={raw!r} mixes {_NO_DEPS!r} with real members; "
                f"'declares nothing' and 'declares a thing called {_NO_DEPS}' "
                "cannot both be spelled the same way")
    if len(members) != len(set(members)):
        raise PlanMetadataError(
            f"{what}={raw!r} names a member twice; a repeat makes the field's "
            "length disagree with the number of things it names")
    return members


def _validate_acyclic_dependencies(dependencies, *, error_type, subject) -> None:
    """Refuse a dependency graph that is not closed, or that holds a cycle.

    THE CLOSURE CHECK IS PART OF THIS FUNCTION, not an assumption about the
    caller. A depth-first walk that indexes ``dependencies[node]`` raises
    ``KeyError`` on an edge to a node that is not a key -- and ``KeyError`` is
    outside ``TrackerError``, so a graph one edge short of closed would kill the
    run instead of stopping it. This helper is parameterised by ``error_type``
    precisely so later phases can hand it their own graphs, and a later caller
    is exactly the one that will not have pre-filtered its edges.

    ``error_type`` and ``subject`` rather than a hard-wired
    ``PlanMetadataError``: the same walk answers "do these tasks deadlock" and
    "do these phases deadlock", and the two stop the run under different names.

    WHAT IT IS TOTAL FOR IS NARROWER THAN "ANY GRAPH", and the limit is stated
    rather than left to be discovered by the reuser this helper is
    parameterised for. It is total for a MAPPING whose edge values are
    iterables of HASHABLE ids and whose longest path is shorter than the
    interpreter's recursion limit. Measured outside that: a non-mapping raises
    ``AttributeError``, a list-valued edge raises ``TypeError: unhashable
    type``, and a chain of a few thousand nodes raises ``RecursionError`` --
    none of them a ``TrackerError``. The closure check above is what makes the
    open graph, the one case a caller really does hand it, land inside the
    family; the three above are caller shapes this module never builds, since
    every caller's ids are ``_TOKEN`` strings and every caller's graph is
    bounded by ``MAX_TASKS_PER_PHASE``. A later caller that cannot promise the
    same owes itself a screen before the call, not a claim from this one.
    """
    unknown = sorted({dependency for edges in dependencies.values()
                      for dependency in edges if dependency not in dependencies})
    if unknown:
        raise error_type(
            f"{subject} dependency graph is not closed: {unknown} "
            f"{'are' if len(unknown) > 1 else 'is'} depended on and never "
            "declared, so nothing will ever satisfy the wait")
    visiting: set = set()
    visited: set = set()

    def visit(node) -> None:
        if node in visiting:
            raise error_type(
                f"{subject} dependency graph contains a cycle through {node!r}; "
                "every member of a cycle waits on a member of the same cycle, "
                "so none of them ever becomes dispatchable")
        if node in visited:
            return
        visiting.add(node)
        for dependency in dependencies[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in dependencies:
        visit(node)


def _parse_write_scope(raw: str):
    """``file:src/a.py,tree:docs`` -> canonical strings plus typed pairs.

    THE TYPE IS MANDATORY, and an untyped scope is refused rather than guessed
    at. ``src/a`` could be one file or a whole subtree, and the two reserve
    differently: under ``scopes_overlap`` a tree collides with every path
    beneath it and a file collides only with itself, so guessing wrong either
    serialises work that could have run concurrently or lets two implementers
    write the same file. A plan that did not say is a plan that has to say.

    Returns ``(canonical, parsed)``. ``canonical`` is what a tracker cell
    records -- one string per scope, in the order the plan wrote them, because
    the declaration order is the plan's and sorting it would record something
    the plan did not say. ``parsed`` is ``(type, PurePosixPath)`` pairs, which
    is what the containment check below and Task 3's overlap algebra want.
    """
    members = _declared_members(raw, "write_scope")
    if not members:
        raise PlanMetadataError(
            "a task declares at least one write scope; a task that writes "
            f"nowhere cannot be reserved against anything, and {_NO_DEPS!r} is "
            "the spelling of an empty LIST, not of 'this task touches no files'")
    canonical: list = []
    parsed: list = []
    for scope in members:
        scope_type, separator, raw_path = scope.partition(":")
        if not separator:
            raise PlanMetadataError(
                f"write scope {scope!r} is untyped: every scope is spelled "
                f"{_WRITE_SCOPE_TYPES[0]}:<path> or {_WRITE_SCOPE_TYPES[1]}:"
                "<path>, because one exact file and a whole subtree reserve "
                "against each other differently")
        if not _member(scope_type, _WRITE_SCOPE_TYPES):
            raise PlanMetadataError(
                f"unsupported write scope type {scope_type!r} in {scope!r}; "
                f"the types are {list(_WRITE_SCOPE_TYPES)!r}. A pattern type "
                "would name a set whose membership depends on when it is "
                "expanded, which two implementers cannot be checked against")
        path = _safe_relative(raw_path)
        canonical.append(f"{scope_type}:{path.as_posix()}")
        parsed.append((scope_type, path))
    return tuple(canonical), parsed


def _within_scope(output: PurePosixPath, parsed_scopes) -> bool:
    """Is ``output`` inside one of these typed scopes?

    ASKED THROUGH ``.parents``, NEVER THROUGH A STRING PREFIX. ``tree:docs``
    does not contain ``docsx/a.md``, and ``"docsx/a.md".startswith("docs")`` is
    ``True`` -- so the prefix spelling hands an artifact task a sibling
    directory it never declared, and the reservation algebra that was supposed
    to keep two implementers apart has already been told the wrong thing.

    A ``tree:`` scope does not contain ITSELF: the scope is a directory and an
    output is a file the task promises to produce, so ``tree:docs`` with
    ``outputs=docs`` is a task promising to produce a directory.

    AND THAT LAST PARAGRAPH IS WHY TASK 3 MUST NOT CALL THIS FUNCTION.
    ``scopes_overlap`` asks a different question -- "may these two tasks run
    concurrently" -- and for it ``tree:docs`` obviously collides with
    ``tree:docs``. Measured: ``_within_scope(PurePosixPath("docs"), [("tree",
    PurePosixPath("docs"))])`` is ``False``, which is the right answer for an
    output and the wrong answer for an overlap. What Task 3 inherits is the
    SHAPE of the containment test -- ``.parents`` and never a string prefix --
    and ``_WRITE_SCOPE_TYPES`` as the vocabulary; it does not inherit this
    predicate, whose asymmetry is deliberate and belongs to outputs alone.

    THE VOCABULARY IS ``_WRITE_SCOPE_TYPES``, NOT A RE-TYPED PAIR OF LITERALS.
    This function held its own ``"file"`` and ``"tree"`` until P04 Task 3's
    review measured it: the module then contained two statements of the scope
    grammar, and renaming a type in the tuple the plan parser reads would have
    left this predicate silently matching NOTHING -- every output would fall
    outside every declared scope, and the scope check that exists to catch a
    task writing where it did not declare would pass everything.
    """
    return any(
        (scope_type == _WRITE_SCOPE_TYPES[0] and output == scope)
        or (scope_type == _WRITE_SCOPE_TYPES[1] and scope in output.parents)
        for scope_type, scope in parsed_scopes)


def _task_heading(lines, index: int, task_id: str) -> None:
    """The task metadata must sit under the heading of the task it describes.

    DETECTED ON THE STRIPPED LINE, for ``_parse_phase_header``'s reason:
    CommonMark allows up to three leading spaces on an ATX heading, so a raw
    ``startswith`` lets a plan indent the heading and lose the binding
    silently. Seven hashes is not a heading at all, and a level-one heading is
    the document title, so the levels that may carry a task are two to six.

    THE ID MUST BE ONE OF THE HEADING'S WORDS, not a substring of it. A
    substring test binds ``## Task T1`` to a metadata comment for ``T12``, and
    a plan whose two tasks are ``T1`` and ``T12`` is not exotic. Splitting on
    whitespace is what makes ``T1`` and ``T12`` different answers.

    ADJACENCY IS "THE PREVIOUS NONEMPTY LINE", not "the previous line": a blank
    line between a heading and its metadata is markdown, and prose between them
    is a second thing claiming to be under that heading.
    """
    previous = next((candidate for candidate in reversed(lines[:index])
                     if candidate.strip()), "")
    stripped = previous.strip()
    hashes = len(stripped) - len(stripped.lstrip("#"))
    body = stripped[hashes:]
    if not 2 <= hashes <= 6 or not body.startswith(" ") or task_id not in body.split():
        raise PlanMetadataError(
            f"the metadata for task {task_id!r} must sit under that task's own "
            f"heading, with nothing but blank lines between them; the nearest "
            f"nonempty line above it is {previous!r}. A heading is two to six "
            "'#' then a space, and the task id is one of its WORDS -- a "
            "substring test would bind '## Task T1' to the metadata for 'T12'")


def _parse_task_metadata(lines, index: int) -> dict:
    """One task definition: the metadata comment at ``index`` and its suite.

    Returns the eight keys ``id``, ``deps``, ``kind``, ``batch``, ``order``,
    ``write_scope``, ``outputs``, ``commands`` -- the seven the plan declares
    plus the verification suite that belongs to the task rather than to the
    line. Raises ``PlanMetadataError`` and nothing else.

    THE KEY ORDER IS THE GRAMMAR. ``_comment_fields`` matches the seven keys
    positionally against ``_TASK_KEYS``, which is what makes a reorder, a
    rename, a drop and an extra key four distinct defects refused by one
    mechanism. ``tail=False``: no task field may absorb the field separator, so
    an eighth key appended after ``outputs`` is a field COUNT error rather than
    something quietly swallowed into the outputs list.
    """
    (task_id, raw_deps, kind, batch, raw_order, raw_scopes,
     raw_outputs) = _comment_fields(lines[index], _TASK_COMMENT, _TASK_KEYS,
                                    tail=False)

    if not _TASK_ID.fullmatch(task_id):
        raise PlanMetadataError(
            f"invalid task id {task_id!r}: a task id is written into a tracker "
            "cell, a branch name, a checkpoint marker and the name of the "
            "directory its results are published in, so it is an alphanumeric "
            "then alphanumerics, dots, underscores and hyphens, at most "
            f"{_OWNER_MAX} characters, with no trailing dot, no '..' and no "
            "'.lock' ending. _TOKEN -- which is all this screen used to ask "
            "for -- admits '/', ':', '@' and '+'; git refuses those in a "
            "branch name and a directory cannot hold them, and reserve_task "
            "would have taken a slot for a task nothing could ever finish")
    _task_heading(lines, index, task_id)
    if not _member(kind, TASK_KINDS):
        raise PlanMetadataError(
            f"task {task_id!r} declares kind={kind!r}, outside "
            f"{list(TASK_KINDS)!r}. The kind is the PLAN's claim about what "
            "this task produces and what proves it; a worker does not get to "
            "restate it because its implementation happened to produce no diff")
    #: ``_TOKEN`` AND DELIBERATELY NOT ``_TASK_ID``. A batch name is written
    #: into a tracker cell and read back out of one, and it becomes no path
    #: and no ref, so the two rules ``_TASK_ID`` adds for git would be a
    #: narrowing with no failure behind it. This screen used to say "for the
    #: reason a task id is", which stopped being true when the task id was
    #: tightened.
    if not _TOKEN.fullmatch(batch):
        raise PlanMetadataError(
            f"invalid batch {batch!r} on task {task_id!r}: a batch name is one "
            "token, because it is written into a tracker cell")

    #: ``int(raw_order)`` ALONE IS NOT THE GRAMMAR, and the module has already
    #: written this defect down once, in ``_Numbered``: ``int(chr(0x0661))`` is 1
    #: and ``int('1_0')`` is 10, so a plan can spell an order in Arabic-Indic
    #: digits or with a separator and the tracker records a number nobody
    #: wrote. ``isascii() and isdigit()`` is the ten characters intended.
    #: The round trip through ``str`` then refuses ``order=01``, which is a
    #: second spelling of a number the plan already has one spelling for.
    #:
    #: THE LENGTH CLAUSE COMES BEFORE THE ROUND TRIP, and the position is the
    #: whole point: ``or`` short-circuits left to right, and ``isascii()`` and
    #: ``isdigit()`` are both TRUE of a four-thousand-digit run, so without a
    #: bound in front of it the ``int(raw_order)`` written INTO this screen is
    #: itself the call that escapes -- CPython caps integer<->string conversion
    #: at ``sys.int_max_str_digits`` and raises ``ValueError``, which is not a
    #: ``TrackerError``. See ``_MAX_ORDER_DIGITS`` for why the bound is a
    #: spelling ceiling and not ``order <= MAX_TASKS_PER_PHASE``.
    if (not raw_order.isascii() or not raw_order.isdigit()
            or len(raw_order) > _MAX_ORDER_DIGITS
            or raw_order != str(int(raw_order))):
        raise PlanMetadataError(
            f"task {task_id!r} declares order={raw_order!r}: an order is at "
            f"most {_MAX_ORDER_DIGITS} ASCII digits with no sign, no separator "
            "and no leading zero. 'isdigit' alone is true of chr(0x0661) and "
            "'int' accepts '1_0', so either would record a number the plan "
            "does not say -- and an UNBOUNDED run of ordinary digits passes "
            "both, then raises ValueError out of the very int() this screen "
            "was written to replace")
    order = int(raw_order)
    if order <= 0:
        raise PlanMetadataError(
            f"task {task_id!r} declares order={order}: tasks are integrated in "
            "declared order and the count starts at 1, so there is no zeroth "
            "or negative position to integrate into")

    deps = _declared_members(raw_deps, f"task {task_id} deps")
    for dependency in deps:
        #: ``_TASK_ID`` AND NOT ``_TOKEN``: a dependency names a task, so it
        #: is the same kind of name and gets the same grammar. Two grammars
        #: for one id would let a plan declare a dependency on an id no task
        #: in it could legally carry, and the diagnosis a reader then gets is
        #: "unknown dependency" rather than "that is not a task id".
        if not _TASK_ID.fullmatch(dependency):
            raise PlanMetadataError(
                f"invalid task dependency id {dependency!r} in deps={raw_deps!r} "
                f"on task {task_id!r}; a dependency names a task and is held to "
                f"the task-id grammar. A task that depends on nothing spells it "
                f"{_NO_DEPS!r}")
        if dependency == task_id:
            raise PlanMetadataError(
                f"task {task_id!r} lists itself in deps={raw_deps!r}; a task "
                "waiting on itself never becomes dispatchable")

    write_scope, parsed_scopes = _parse_write_scope(raw_scopes)
    declared = _declared_members(raw_outputs, f"task {task_id} outputs")
    #: THE TWO HALVES ARE ONE RULE, stated as an equivalence rather than as two
    #: independent checks, because the defect is the plan being able to have it
    #: both ways. A source task proves itself by running its suite, so naming
    #: outputs would be a second, unverified claim; an artifact task proves
    #: itself by its documents existing, so declaring none leaves nothing to
    #: check and "done" becomes whatever the worker says it is.
    if (kind == "source") != (not declared):
        raise PlanMetadataError(
            f"task {task_id!r} is kind={kind!r} with outputs={raw_outputs!r}: a "
            f"source task declares outputs={_NO_DEPS} and is proved by its "
            "verification suite; an artifact task names its exact approved "
            "outputs and is proved by them existing")
    outputs: list = []
    for raw_output in declared:
        output = _safe_relative(raw_output)
        if not _within_scope(output, parsed_scopes):
            raise PlanMetadataError(
                f"task {task_id!r} declares the output {raw_output!r}, which is "
                f"outside its write scope {list(write_scope)!r}. An output the "
                "task may not write is an output another task's implementer is "
                "entitled to be holding")
        outputs.append(output.as_posix())

    #: DETECTED ON THE STRIPPED LINE, exactly as ``_comment_indexes`` detects,
    #: and then validated on the RAW one. A raw ``startswith`` here would make
    #: an INDENTED suite comment invisible, and invisible is the dangerous
    #: direction for the artifact half: the artifact task would be accepted
    #: carrying a source-task suite that this grammar claims to forbid.
    following = lines[index + 1] if index + 1 < len(lines) else ""
    carries_suite = following.strip().startswith(f"<!-- {_TASK_SUITE_COMMENT}:")
    if kind != "source":
        if carries_suite:
            raise PlanMetadataError(
                f"task {task_id!r} is kind={kind!r} and carries a "
                f"{_TASK_SUITE_COMMENT!r} comment. An artifact task is proved "
                "by its exact approved outputs; a suite beside them would be a "
                "second definition of done, and the two can disagree")
        return {
            "id": task_id, "deps": deps, "kind": kind, "batch": batch,
            "order": order, "write_scope": write_scope,
            "outputs": tuple(outputs), "commands": (),
        }
    if not carries_suite:
        raise PlanMetadataError(
            f"source task {task_id!r} needs exactly one {_TASK_SUITE_COMMENT!r} "
            "comment on the line IMMEDIATELY below its metadata. A source task "
            "is proved by running something, and a task that names nothing to "
            "run declares that nothing verifies it")
    suite_id, raw_commands = _comment_fields(
        lines[index + 1], _TASK_SUITE_COMMENT, _TASK_SUITE_KEYS, tail=True)
    if suite_id != task_id:
        raise PlanMetadataError(
            f"the suite below task {task_id!r} names {suite_id!r}: a suite "
            "belonging to another task would verify that task and report the "
            "result against this one")
    return {
        "id": task_id, "deps": deps, "kind": kind, "batch": batch,
        "order": order, "write_scope": write_scope,
        "outputs": tuple(outputs), "commands": _parse_command_suite(raw_commands),
    }


def _plan_text(path) -> str:
    """Open one phase plan and return its text, or refuse inside the family.

    RULE 11 LANDS HERE, because this is the first line of the plan grammar that
    touches a filesystem. ``is_file()`` NEVER MEANS "there is nothing here": it
    is false for a directory, for a dangling symlink, for a symlink LOOP and
    for a FIFO, and all four are names that exist. ``_require_regular_file`` is
    the door, and a bare ``read_text`` is not merely a missing check -- opening
    a FIFO for reading BLOCKS until a writer arrives, and on a plan path a
    controller supplies no writer is coming. That is a deadlock with no
    diagnostic and no timeout, not an error.

    ``.resolve()`` IS NEVER CALLED. On a symlink loop it raises ``RuntimeError``
    -- measured, on this Python, from ``resolve`` itself and with
    ``strict=False`` too -- and ``RuntimeError`` is not a ``TrackerError``.
    ``is_file()`` plus ``os.path.lexists`` answer the same question without it.

    THE SPELLING IS SCREENED BEFORE THE FILESYSTEM IS ASKED, and this is a
    DIFFERENT corpus from a field value's. Measured: for a path holding ``\\x00``
    -- and for one holding a lone surrogate -- ``is_file()`` is False AND
    ``os.path.lexists`` is False, so the door is silent and ``read_text``
    raises ``ValueError: embedded null byte`` / ``UnicodeEncodeError`` from
    outside the family. ``_cell_safe`` is the screen because a plan path is
    also recorded in ``## Run``'s ``phase_plans`` cell, so its union of the
    listed half (NUL and the rest of ``range(0x20)``) and the derived half
    (``\\x85``, ``\\u2028``, ``\\u2029`` -- which name files that really exist
    and really read, and would pass any closed ASCII list) is exactly the bar
    this argument needs.
    """
    if isinstance(path, Path):
        spelling = str(path)
    elif isinstance(path, str):
        spelling = path
    else:
        raise PlanMetadataError(
            f"a phase plan path is a str or a pathlib.Path; got "
            f"{type(path).__name__}. bytes would raise TypeError from Path and "
            "an os.PathLike would hide an arbitrary __fspath__ behind the read")
    if not spelling or not _cell_safe(spelling):
        raise PlanMetadataError(
            f"unusable phase plan path {spelling!r}: it must be a nonempty "
            "string a tracker cell can carry back out unchanged -- no NUL or "
            "other control character, nothing the section reader breaks a line "
            "on, nothing the UTF-8 encoder refuses, no '|', and no surrounding "
            "whitespace. A NUL here reaches the syscall as ValueError and a "
            "lone surrogate as UnicodeEncodeError, both outside TrackerError")
    plan = Path(spelling)
    try:
        _require_regular_file(plan, "a phase plan")
    except QuorumError as exc:
        raise PlanMetadataError(
            f"the phase plan at {spelling!r} is a name this run cannot read "
            f"({exc}); a directory, a dangling link, a symlink loop or "
            "a FIFO is corruption and never an absent plan -- and the FIFO is "
            "why the shape is asked before the open rather than by it, because "
            "that open blocks for a writer that never comes") from exc
    try:
        return plan.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PlanMetadataError(
            f"unreadable phase plan at {spelling!r}: {type(exc).__name__}: "
            f"{exc}. A plan that is missing, unreadable or not UTF-8 is input, "
            "and input stops the run inside this module's exception family") from exc


def parse_plan_metadata(path) -> dict:
    """One approved phase plan's strict metadata: the phase header and its tasks.

    Returns ``{"phase": {...}, "tasks": [{...}, ...]}``. Raises
    ``PlanMetadataError`` and nothing else, for every input -- a plan grammar
    that can throw ``OSError``, ``ValueError`` or ``RuntimeError`` at a
    controller has not refused the plan, it has crashed on it.

    IT READS AND CHANGES NOTHING ELSE. A refused plan is byte-identical after
    the refusal, which is the read-only-stop rule this whole module is built to
    keep.
    """
    lines = _plan_text(path).splitlines()
    phase = _parse_phase_header(lines)

    indexes = _comment_indexes(lines, _TASK_COMMENT)
    tasks = [_parse_task_metadata(lines, index) for index in indexes]
    if not 1 <= len(tasks) <= MAX_TASKS_PER_PHASE:
        raise PlanMetadataError(
            f"a phase plan declares between 1 and {MAX_TASKS_PER_PHASE} tasks; "
            f"this one declares {len(tasks)}. Zero means the plan is prose a "
            "worker would have to interpret into work; more than the ceiling "
            "is two phases that were not split")

    #: EVERY SUITE COMMENT IN THE DOCUMENT IS ACCOUNTED FOR, not just the one
    #: below each task. Checking only adjacency leaves an ORPHAN suite -- a
    #: second copy, or one left behind by an edit that moved its task --
    #: sitting in the plan, claiming to verify a task, verifying nothing, and
    #: visible to a human reader as though it did.
    expected = [index + 1 for index, task in zip(indexes, tasks)
                if task["kind"] == "source"]
    suite_indexes = _comment_indexes(lines, _TASK_SUITE_COMMENT)
    if suite_indexes != expected:
        raise PlanMetadataError(
            f"every {_TASK_SUITE_COMMENT!r} comment belongs immediately below "
            f"the metadata of its own source task; expected them on lines "
            f"{expected} and found them on {suite_indexes}. A suite anywhere "
            "else names a task nothing will run it for")

    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise PlanMetadataError(
            f"a phase plan names each task once; {ids} repeats one. Two "
            "definitions under one id give every later lookup two answers and "
            "nothing to choose between them")
    orders = [task["order"] for task in tasks]
    if any(left >= right for left, right in zip(orders, orders[1:])):
        raise PlanMetadataError(
            f"task orders {orders} must strictly increase down the document. "
            "Worktrees are merged --no-ff IN TASK ORDER, so a repeat leaves two "
            "tasks with equal claim to the same position and a document that "
            "disagrees with its own order field is two answers to 'which is "
            "integrated first'")

    _validate_acyclic_dependencies(
        {task["id"]: task["deps"] for task in tasks},
        error_type=PlanMetadataError, subject="task")

    #: THE TWO ORDERINGS MUST BE THE SAME ORDERING. Strictly increasing orders
    #: and an acyclic, closed dependency graph are each satisfiable while
    #: CONTRADICTING each other: ``T1 order=1 deps=T2`` beside ``T2 order=2``
    #: is acyclic, closed and increasing, and it says T1 is integrated first
    #: and that T1 waits on T2. Worktrees merge ``--no-ff`` IN TASK ORDER, so
    #: that plan has two answers to "which is integrated first" -- the same
    #: defect the strictly-increasing rule closed, arriving by the one route
    #: that rule does not watch.
    #:
    #: RUN AFTER THE GRAPH WALK, because the walk is what proves the graph is
    #: CLOSED: an edge to an id no task declares would otherwise index this
    #: mapping and raise ``KeyError``, from outside the family. Stating it as
    #: "a dependency is strictly earlier" subsumes the self-dependency and the
    #: in-plan cycle, which keep their own checks so that each refusal still
    #: names the thing the plan actually got wrong.
    #:
    #: ``>=`` RATHER THAN ``>`` IS THE STATEMENT AND NOT A REACHABLE BRANCH.
    #: The equal half cannot be spelled: a dependency sharing its dependent's
    #: order is either a different task, and two distinct tasks with equal
    #: orders are already refused above, or the task itself, refused by the
    #: self-dependency check. The comparison says what the rule means; the two
    #: earlier checks are what make the equality unreachable, and
    #: ``test_an_equal_order_dependency_is_unreachable_and_here_is_what_closes_it``
    #: asserts both of them so the claim is measured rather than assumed.
    order_of = {task["id"]: task["order"] for task in tasks}
    for task in tasks:
        for dependency in task["deps"]:
            if order_of[dependency] >= task["order"]:
                raise PlanMetadataError(
                    f"task {task['id']!r} has order={task['order']} and depends "
                    f"on {dependency!r}, whose order is {order_of[dependency]}: "
                    "a dependency is integrated BEFORE the task that waits on "
                    "it, and worktrees are merged --no-ff in task order, so a "
                    "dependency at an equal or later order is a plan that "
                    "integrates work before the work it is built on")
    return {"phase": phase, "tasks": tasks}


# ---------------------------------------------------------------------------
# P04 Task 3: the typed write-scope algebra -- fault F1.
#
# TWO SCOPES OVERLAP IFF THE SET OF REPOSITORY PATHS THEY CLAIM INTERSECTS, and
# EQUALITY ALONE IS THE FAULT THIS BLOCK EXISTS TO CLOSE. Under equality
# ``tree:src`` and ``file:src/a.py`` are different strings and different paths,
# so the two tasks reserve together, two implementers open the same file in two
# worktrees, and the collision surfaces as a merge conflict at integration --
# which the master plan makes a HARD STOP precisely because a conflict there is
# evidence that this function answered wrongly.
#
# THE RULE IS ASKED, NOT ENUMERATED. A ``file:`` scope claims exactly one path;
# a ``tree:`` scope claims its own path and everything strictly beneath it. Each
# claimed set therefore has a SMALLEST member, and it is the scope's own path --
# so two claimed sets intersect iff one scope claims the OTHER'S ROOT. That is
# the whole algebra, it is symmetric by construction rather than by a second
# branch, and it is why ``scopes_overlap`` is two calls to the same containment
# predicate rather than a three-way case analysis over the type pairs. A case
# analysis is where the missing ancestor branch hid in the first place.
#
# CONTAINMENT IS ASKED THROUGH ``.parents`` AND NEVER THROUGH A STRING PREFIX,
# which is the trap one level up from equality: ``"docsx/a.md".startswith(
# "docs")`` is ``True`` and ``tree:docs`` does not contain ``docsx/a.md``, so
# the prefix spelling serialises two tasks that could have run concurrently and,
# read the other way round, would hand ``tree:.git`` authority over
# ``.github/workflows/ci.yml``.
#
# AND IT DOES NOT CALL ``_within_scope``. That predicate answers a different
# question -- "is this OUTPUT inside this declared scope" -- and deliberately
# says a ``tree:`` scope does not contain itself, because a task whose declared
# output is a directory has promised to produce a directory. Measured:
# ``_within_scope(PurePosixPath("docs"), [("tree", PurePosixPath("docs"))])`` is
# ``False``, which is right for an output and catastrophic for an overlap, where
# ``tree:docs`` obviously collides with ``tree:docs``. What is inherited is the
# SHAPE of the test and ``_WRITE_SCOPE_TYPES`` as the vocabulary; not the
# predicate, whose asymmetry belongs to outputs alone.
#
# KNOWN LIMITATION -- CASE AND UNICODE ARE COMPARED AS BYTES, NOT AS A
# FILESYSTEM WOULD. ``tree:src`` and ``tree:SRC`` do not overlap here, and
# neither do the precomposed and decomposed spellings of the same accented
# segment. On a case-insensitive or normalising filesystem (macOS's default
# APFS, NTFS) those pairs name ONE directory, so two implementers could be
# dispatched onto it and this function would have said ``False``. The choice is
# deliberate and it is the git index's: git records path bytes, the tracker
# records the bytes a plan wrote, and the alternatives are worse -- ``casefold``
# would make ``file:Makefile`` and ``file:makefile`` collide on Linux where they
# are two real files, and ``unicodedata.normalize`` would widen
# ``ALLOWED_IMPORTS`` past twelve to make two tracker cells that differ in bytes
# compare equal. What follows from it: on such a filesystem the divergence
# surfaces as the merge conflict the master plan already treats as a hard stop,
# and the mitigation is a plan review that spells one path one way -- not a
# looser comparison here. ``ScopeAlgebraTests`` pins both families as ``False``
# so the limitation cannot be changed silently.
# ---------------------------------------------------------------------------


def _scope_parts(scope: str):
    """ONE typed write scope, as ``(type, PurePosixPath)``.

    THE VOCABULARY AND THE PATH BAR ARE ``_parse_write_scope``'S, NOT A SECOND
    COPY. Re-typing ``{"file", "tree"}`` here would be a second statement of
    the scope grammar that can drift from the plan parser's, and the two
    disagreeing is a scope a plan accepts and the reservation algebra rejects
    -- or worse, the other way round. Task 1 rebound ``_TOKEN`` and silently
    narrowed sixteen call sites; the lesson is the same shape.

    THE ARITY CHECK IS THE PRICE OF THAT REUSE AND IT IS REACHABLE.
    ``_parse_write_scope`` reads the COMMA-SEPARATED field a plan writes, so
    ``scopes_overlap("file:a,tree:b", "file:c")`` would otherwise silently
    compare against only the first member and report that a task claiming
    ``tree:b`` collides with nothing. One scope in, one pair out. The
    zero-member half of ``!= 1`` cannot be spelled -- ``_parse_write_scope``
    already refuses an empty list, and ``none`` with it -- and the comparison
    says what the rule means rather than what is reachable, exactly as the
    ``>=`` in the order/dependency check does.

    THE STRING SCREEN IS FIRST BECAUSE ``_declared_members`` HAS NO TYPE GUARD.
    ``None.split(",")`` is ``AttributeError`` and ``42 == "none"`` is ``False``
    on the way to the same call, and neither is a ``TrackerError``: a
    controller catching this module's family would die on a caller's typo
    instead of refusing it. ``_text`` is the screen the module already uses for
    "a field that was actually filled in".

    ITS TWO HALVES BUY DIFFERENT THINGS AND ONLY ONE OF THEM CHANGES THE
    EXCEPTION. The ``isinstance`` half is the one above: without it a non-string
    leaves this module's family altogether. The ``strip`` half changes only the
    MESSAGE -- ``""``, ``" "`` and ``"\\t"`` are all refused downstream anyway,
    as an "empty member" and as "untyped" respectively, which are two different
    diagnoses of one blank cell and neither of them says the thing the caller
    needs to hear. Narrowing this line to ``isinstance`` therefore survives the
    suite on behaviour alone; ``test_a_blank_scope_is_refused_by_this_screen_
    and_not_merely_downstream`` pins the message so the narrowing is a mutant
    that dies rather than a silent loss of the diagnosis.
    """
    if not _text(scope):
        raise PlanMetadataError(
            "a write scope is a nonempty string spelled "
            f"{_WRITE_SCOPE_TYPES[0]}:<path> or {_WRITE_SCOPE_TYPES[1]}:<path>;"
            f" got {scope!r}")
    _, parsed = _parse_write_scope(scope)
    if len(parsed) != 1:
        raise PlanMetadataError(
            f"{scope!r} names {len(parsed)} write scopes and this asks about "
            "ONE; a comma-separated field is compared with "
            "_scope_sets_overlap, which reads every member, and not by "
            "handing the whole field to a single-scope predicate that would "
            "answer for the first member alone")
    return parsed[0]


def _scope_claims(path: PurePosixPath, scope_type: str,
                  scope_path: PurePosixPath) -> bool:
    """Does the scope ``(scope_type, scope_path)`` claim ``path``?

    The one containment statement the rest of this block is built out of, taken
    on ALREADY-PARSED values so the predicate can be reused without re-reading
    a string. ``file:`` claims one path; ``tree:`` claims its own path and
    every path strictly beneath it, asked through ``.parents``.

    A ``tree:`` SCOPE CLAIMS ITSELF HERE, and that single clause is the
    difference from ``_within_scope``. Both ask about descent; only this one
    also says yes to the root, because two tasks that both declare
    ``tree:docs`` are two tasks that cannot run at the same time.
    """
    return path == scope_path or (
        scope_type == _WRITE_SCOPE_TYPES[1] and scope_path in path.parents)


def _pair_overlaps(one, two) -> bool:
    """Do two ALREADY-PARSED typed scopes claim a repository path in common?

    THE OVERLAP RULE IS SPELLED HERE ONCE AND NOWHERE ELSE. Both callers --
    ``scopes_overlap`` for a pair of strings and ``_scope_sets_overlap`` for the
    cross product of two lists -- used to carry their own copy of ``claims(b in
    a) or claims(a in b)``, which is two statements of one rule that can drift:
    a fix applied to the single-pair spelling and not to the set spelling would
    leave every reservation in the run answering the OLD rule while the unit
    test of the pair passed. That is the same shape this block's header refuses
    for the scope vocabulary, applied to the algebra itself.

    ``one`` and ``two`` are ``(type, PurePosixPath)`` as ``_scope_parts``
    returns them, so the rule can be asked about a pair that has already been
    parsed without re-reading either string.
    """
    type_a, path_a = one
    type_b, path_b = two
    return (_scope_claims(path_b, type_a, path_a)
            or _scope_claims(path_a, type_b, path_b))


def scopes_overlap(a: str, b: str) -> bool:
    """Do two typed write scopes claim any repository path in common?

    ``True`` means the two tasks holding them may not be dispatched together.
    Spare worker capacity never overrides this answer: capacity is about how
    many tasks may run, and this is about which two may not.

    THE ANSWER IS "DOES EITHER SCOPE CLAIM THE OTHER'S ROOT", which is exact
    rather than a heuristic: every claimed set is nonempty and contains its own
    scope path as its smallest member, so if the two sets intersect at all,
    they intersect at one of the two roots. Writing it this way makes symmetry
    a property of the EXPRESSION rather than of a fourth branch somebody has to
    remember to keep in step, and it collapses the type-pair case analysis --
    file/file, tree/file, file/tree, tree/tree -- that is where the ancestor
    branch went missing.

    Raises ``PlanMetadataError`` for anything that is not one typed, safe,
    repository-relative scope, on either side, and nothing else for any input.
    """
    return _pair_overlaps(_scope_parts(a), _scope_parts(b))


def _scope_sets_overlap(left, right) -> bool:
    """Do two SETS of typed write scopes share any claimed path?

    The form a reservation actually asks in: a task declares a list of scopes
    and is compared against the list held by every task already in flight.

    A BARE STRING IS REFUSED RATHER THAN ITERATED. ``"file:src/a.py"`` is a
    perfectly good iterable -- of CHARACTERS -- and the damage is not that the
    characters fail to parse but that they are never reached: ``any()`` over an
    empty right-hand set returns ``False`` before the first one is examined, so
    the single most likely caller mistake reports "no conflict" and two
    implementers are dispatched onto the same file. That is fault F1 arriving
    by a route the overlap rule itself is innocent of.

    ``tuple``/``list`` IS A LISTED PAIR AND THE REASON IS THE IMPORT BUDGET.
    The honest question is "is this a materialised sequence of strings", and
    the abstract answer spells ``collections.abc.Sequence`` -- which ``str``
    satisfies anyway, and which would widen ``ALLOWED_IMPORTS`` past twelve for
    a predicate this module can state. The two shapes this module builds are a
    tuple out of ``_parse_write_scope`` and a list out of a split cell.

    THE SCREEN IS WHAT MAKES THE NESTED WALK SAFE, AND NOTHING AFTER IT
    RE-DEFENDS. The comprehension below walks the right-hand side once per
    member of the left, so a one-shot iterator would be exhausted after the
    first row and every later comparison would silently see an empty set -- the
    same false ``False`` again. That is a reason for the ``tuple``/``list``
    screen, not for a ``tuple(...)`` call underneath it: by the time control
    reaches the parse, both sides are already materialised sequences, and
    ``parsed_left``/``parsed_right`` are lists in any case. Two such calls used
    to sit here, presented as a defence; they were unreachable, and an
    unreachable screen reads as a guarantee that something is being checked
    which is not -- the same ruling ``_safe_relative``'s docstring records for
    its deleted absolute-path clause.

    AN EMPTY LEFT IS REFUSED AND AN EMPTY RIGHT IS NOT, and the asymmetry is the
    two sides meaning different things. The left is "these are MY scopes", and a
    task that declares none does not exist: ``_parse_write_scope`` already
    refuses a scopeless task, so an empty left never comes from a plan -- it
    comes from a lookup that missed, a ``-`` cell, a task id that did not match,
    a split that yielded nothing. Answering ``False`` there means "I failed to
    find my own scopes, therefore nothing can conflict with me", which is fault
    F1's shape arriving by a third route and is exactly the false ``False`` the
    bare-string screen above exists to refuse; the two would otherwise be
    treated inconsistently. The right is "what is already in flight", and an
    empty one is the ordinary first dispatch of a run: nothing is running, so
    nothing conflicts, and ``False`` is the true answer rather than an absence
    of information.

    EVERY SCOPE ON BOTH SIDES IS PARSED BEFORE ANY PAIR IS ANSWERED, so a
    malformed scope is refused whether or not an earlier pair happened to
    collide. With the parse left to ``any()``'s short circuit, the answer to
    "is this scope list well formed" would depend on which pair collided first,
    and a run could adopt a scope the very same list rejects tomorrow.
    """
    for side, which in ((left, "left"), (right, "right")):
        if not isinstance(side, (tuple, list)):
            raise PlanMetadataError(
                f"the {which} write-scope set must be a tuple or a list of "
                f"typed scope strings; got {type(side).__name__} {side!r}. A "
                "bare string is an iterable of characters, and an empty "
                "opposing set would report 'no conflict' before one of them "
                "was ever examined")
    if not left:
        raise PlanMetadataError(
            "the left write-scope set is the asking task's OWN scopes and is "
            "empty; a task that writes nowhere cannot be reserved against "
            "anything, and _parse_write_scope already refuses one, so an empty "
            "left is a lookup that missed rather than a task with no scopes. "
            "Answering 'no conflict' for it would report that a task whose "
            "scopes could not be found collides with nothing. An empty RIGHT "
            "is allowed and means nothing is in flight")
    parsed_left = [_scope_parts(scope) for scope in left]
    parsed_right = [_scope_parts(scope) for scope in right]
    return any(_pair_overlaps(one, two)
               for one in parsed_left
               for two in parsed_right)


def _path_in_scope(path: str, scope: str) -> bool:
    """Is one repository-relative path claimed by one typed write scope?

    The WITNESS form of the overlap question, and the reason it is a public
    part of this block rather than an inlined branch: when ``scopes_overlap``
    says ``True`` there is always a concrete path both scopes claim, and it is
    one of the two scope roots. A test can therefore demand the witness instead
    of accepting the bare boolean -- which is what makes an ancestor rule
    distinguishable from an equality rule, since both say ``True`` for
    ``tree:docs`` against ``tree:docs`` and only one of them can produce
    ``src/a.py`` as the path ``tree:src`` and ``file:src/a.py`` share.

    ``path`` GOES THROUGH ``_safe_relative`` TOO. A caller's path is as
    untrusted as a plan's: ``"src/../../etc"`` normalises into a different
    answer under ``PurePosixPath`` and ``"srcx/a.py"`` must not be admitted by
    a prefix. One bar, stated once, for both sides of the comparison.
    """
    scope_type, scope_path = _scope_parts(scope)
    return _scope_claims(_safe_relative(path), scope_type, scope_path)

# ---------------------------------------------------------------------------
# P04 Task 4: the immutable worker-result codec -- fault F5.
#
# The VOCABULARY is unchanged from superb:pipeline. The ROUTING is not: there,
# all three non-DONE statuses meant "block and ask the human". Here
# NEEDS_CONTEXT and PLAN_CONFLICT raise a QUORUM QUESTION, and a question that
# names no record has been raised nowhere -- so those two statuses must carry a
# resolvable, digest-bound question record or the document cannot be rendered
# at all. Only BLOCKED still halts, because three brains cannot conjure an API
# key, and a halt must say what it is waiting for.
#
# DONE IS EVIDENCE, NOT ACCEPTANCE, and that is a property of this codec rather
# than a sentence in a template. Three mechanisms make it true:
#
#   1. THE STATUS WORD AND THE ROUTING FIELDS ARE TWO INDEPENDENT STATEMENTS OF
#      ONE FACT, and a document is accepted only where they agree. A DONE
#      carrying a question record is refused; a NEEDS_CONTEXT carrying none is
#      refused; a BLOCKED carrying a question record instead of a reason is
#      refused. No status is believed on the strength of the word alone.
#   2. A COMPLETION CLAIM MUST CARRY THE MATERIAL AN IMPORTER CHECKS. P02's
#      ``_validate_tasks`` already refuses a completed row with no result and no
#      verification, a completed SOURCE row with no source ref or commits, and a
#      completed ARTIFACT row with no artifacts. The same bar is applied here,
#      at the codec, so a claim with nothing to check cannot be published and
#      then have to be refused one layer later on a technicality.
#   3. THERE IS NO ACCEPTANCE FIELD. The grammar has fourteen fields and not one
#      of them can say "accepted", "approved" or "verified". Acceptance is a
#      ``## Tasks`` state and this codec cannot write one; a worker's document
#      can only ever be an exhibit.
#
# AND THE DOCUMENT CARRIES NOTHING THE IMPORTER CANNOT SEE. ``parse`` finishes
# by re-rendering what it read and demanding the bytes back, so a result file is
# canonical or it is refused. That is one screen instead of a list of structural
# ones, and it is the reason a paragraph appended under the table, a second
# marker, a checkpoint row above the result table, a CRLF copy or an extra space
# inside a cell cannot ride along unnoticed -- the document's identity is its
# digest, and two byte sequences that parse to one result would give one result
# two identities.
# ---------------------------------------------------------------------------

WORKER_RESULT_MARKER = "<!-- pipeline-auto-worker-result/v1 -->"
WORKER_RESULT_TITLE = "# Pipeline Auto — Worker Result"

#: The five statuses, PARTITIONED BY ROUTE. The partition is the definition and
#: ``WORKER_STATUSES`` is its concatenation, so ``_status_route`` is total over
#: the vocabulary by construction rather than by a default arm somebody has to
#: remember to keep in step. A sixth status added to one of the three tuples is
#: routed the moment it is written down; a sixth added to ``WORKER_STATUSES``
#: alone is impossible, because ``WORKER_STATUSES`` is not written down.
COMPLETION_STATUSES = ("DONE", "DONE_WITH_CONCERNS")
QUORUM_STATUSES = ("NEEDS_CONTEXT", "PLAN_CONFLICT")
HALT_STATUSES = ("BLOCKED",)
WORKER_STATUSES = COMPLETION_STATUSES + QUORUM_STATUSES + HALT_STATUSES

#: The three routes, named here so the codec's own agreement check and Task 10's
#: controller-side routing read the same partition. Task 10 publishes
#: ``QUORUM_ROUTE`` and ``HALT_ROUTE`` for the tracker marker it writes; those
#: are the CELL SPELLINGS a controller reads back, and they are deliberately not
#: these, so a change to one is not silently a change to the other.
_ROUTE_COMPLETION = "completion"
_ROUTE_QUORUM = "quorum"
_ROUTE_HALT = "halt"

#: The field order IS the grammar, exactly as the phase-plan comment's key order
#: is: ``parse_worker_result`` matches the rendered names positionally against
#: this tuple, so a reordered document fails at the position that should have
#: held the field, a renamed one fails at its own position, a dropped one shifts
#: every later field onto the wrong position and an extra one makes the count
#: wrong. Four defects refused by one comparison.
WORKER_RESULT_FIELDS = (
    "run_id", "task_id", "attempt", "owner", "kind", "status", "source_ref",
    "commits", "artifacts", "tests", "evidence", "concerns",
    "question_record", "blocking_reason",
)

#: The fields rendered into ONE comma-separated cell. Their members carry the
#: ``_cell_list`` comma bar that ``_cell_safe`` deliberately does not -- see
#: ``_cell_safe``'s own note on why the comma belongs on the writer that knows a
#: cell is list-valued and not on the value screen that cannot know.
_WORKER_LIST_FIELDS = ("commits", "artifacts", "tests", "evidence")

_WORKER_CHECKPOINTS = "checkpoints"
_CHECKPOINT_KEYS = ("id", "status", "evidence")
_CHECKPOINT_STATES = ("complete", "in_progress", "blocked")

_RESULT_HEADER = ("Field", "Value")
_CHECKPOINT_HEADER = ("ID", "Status", "Evidence")
_TABLE_RULE = "---"

#: THE CROSS-PHASE OWNER GRAMMAR, and it is a LINE rather than the table
#: cell. The master plan pins ``- **Owner:** <id>`` as a binding contract:
#: P06's reviewer-independence check scans every published result in the
#: results tree with that pattern and refuses to hand a task to anyone who
#: ever owned an attempt at it, INCLUDING a released or superseded attempt
#: whose only surviving record is its immutable result file. Rendered as a
#: table cell alone, that scan matches nothing at all and independence is
#: checked against the empty set -- a fail-open, and exactly the property
#: P06 names: a worker released after finishing a task can be assigned to
#: review it.
#:
#: IT CANNOT BE ADDED ANYWHERE ELSE. ``parse_worker_result``'s last screen
#: is a byte comparison against a re-render, so a line a human or a later
#: task appended would make the document non-canonical and unimportable.
#: The renderer is the only door, which is why the line is written here and
#: not left to the caller.
#:
#: THE CELL STAYS. The cell is what ``parse`` reads the owner OUT of -- it
#: is inside the positional field-order screen and every routing rule --
#: and the line is a projection of it: one conversion point, asserted equal
#: on the way back in, so the document cannot state two owners.
_OWNER_LINE_PREFIX = "- **Owner:** "

#: THE WORDS ``parse_worker_result`` READS STRUCTURALLY IN COLUMN ONE,
#: stated from the two row filters that read them rather than listed a
#: second time beside them. A checkpoint whose id is one of these renders
#: as an ordinary row and parses as the table header or the table rule: the
#: checkpoint VANISHES, and the only screen left to refuse the document is
#: the canonical one -- which refuses it for "not canonical", naming the
#: wrong cause. Measured: ``id="ID"`` rendered ``| ID | complete | ... |``,
#: parsed back to zero checkpoints, and was refused with a diagnosis about
#: bytes. ``_TOKEN`` already refuses ``---`` (its first character must be
#: alphanumeric) and no field row is three cells wide, so ``ID`` is the only
#: one reachable today; the tuple is derived from the filters so that a
#: fourth structural word is covered the moment it is written down.
_RESERVED_ROW_WORDS = (_RESULT_HEADER[0], _CHECKPOINT_HEADER[0], _TABLE_RULE)

#: ``<repository-relative-path>#sha256=<64 lowercase hex>``. The delimiter is
#: spelled once and the digest grammar is P02's ``_SHA256``, not a second
#: ``[0-9a-f]{64}`` written beside it: a truncated digest that still looks like
#: hex is the one failure that reads as a successful binding, and there must be
#: exactly one statement of what a bound reference looks like in this module.
_DIGEST_DELIMITER = "#sha256="

_ATTEMPT_PREFIX = "attempt-"
_ATTEMPT_WIDTH = 3
#: HOW MANY DIGITS AN ATTEMPT MAY BE SPELLED WITH, and it is a SPELLING ceiling
#: for the same reason ``_MAX_ORDER_DIGITS`` is: CPython caps integer<->string
#: conversion at ``sys.int_max_str_digits`` (4300 by default), so ``int(digits)``
#: over a long run of ordinary ASCII digits raises ``ValueError`` -- not a
#: ``TrackerError``, so it escapes every handler a controller wrote. The bound
#: has to be reachable BEFORE the conversion is. Nine digits is a billion
#: attempts at one task; the ceiling exists to keep the conversion total, not to
#: express a policy about retries.
#:
#: IT IS ASKED OF BOTH DIRECTIONS, and by comparison rather than by measuring
#: a string. ``_attempt_token`` screened only ``int``/``not bool``/``>= 1``,
#: so ``render`` wrote ``attempt-1000000000`` -- ten digits -- and ``parse``
#: refused its own renderer's bytes: a published, immutable, digest-bound
#: result nothing could import. Worse, ``f"{attempt:d}"`` over an int of more
#: than ``sys.int_max_str_digits`` digits raises ``ValueError`` INSIDE the
#: renderer, which is the escape this bound exists to prevent -- measured,
#: ``_attempt_token(10 ** 5000)`` raised ``ValueError`` before this line
#: existed. ``attempt >= 10 ** _MAX_ATTEMPT_DIGITS`` is an INTEGER comparison,
#: so it is reachable before any conversion is.
_MAX_ATTEMPT_DIGITS = 9
_ATTEMPT_CEILING = 10 ** _MAX_ATTEMPT_DIGITS


def _attempt_token(attempt) -> str:
    """``1`` -> ``attempt-001``. THE SINGLE CONVERSION POINT, in both directions.

    Every P04 signature takes an ``int``; every tracker cell, checkpoint marker,
    worker-result document and evidence record spells the token. Two spellings
    of that conversion would be two answers to "is this the attempt the row
    reserved", which is fault F6 arriving through arithmetic.
    """
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise TrackerValidationError(
            f"attempt must be a positive integer, not {attempt!r}; a bool is "
            "excluded on purpose, because True renders as attempt-001 and "
            "isinstance(True, int) is what would let it")
    if attempt >= _ATTEMPT_CEILING:
        raise TrackerValidationError(
            f"an attempt of {attempt.bit_length()} bits is at least "
            f"{_ATTEMPT_CEILING} and cannot be spelled in "
            f"{_MAX_ATTEMPT_DIGITS} digits -- which is the ceiling "
            "_parse_attempt_token enforces, so rendering it would publish an "
            "immutable, digest-bound result no importer can read. The test is "
            "an integer comparison so that it is reachable before the f-string "
            "raises ValueError, which is not a TrackerError")
    return f"{_ATTEMPT_PREFIX}{attempt:0{_ATTEMPT_WIDTH}d}"


def _parse_attempt_token(value) -> int:
    """``attempt-001`` -> ``1``, and ONLY the canonical spelling.

    THE ORACLE IS THE RENDERER, not a digit-count rule. ``attempt-0001``,
    ``attempt-1`` and ``attempt-01`` all read as attempt one under any
    hand-written pattern, and all three would then parse into a document whose
    re-render is different bytes -- one attempt with several identities, in a
    record whose identity is its digest. The check is therefore
    ``_attempt_token(int(digits)) == value`` and nothing else, which also
    disposes of ``attempt-000`` (zero is not an attempt) without a second rule.

    THE DIGITS ARE SCREENED BEFORE ``int`` SEES THEM, twice over.
    ``str.isdigit`` is true of ``'٣'`` and ``'³'`` and ``int('٣')`` is 3, so an
    attempt spelled in Arabic-Indic digits would convert; and 4301 ASCII digits
    raise ``ValueError`` out of ``int`` itself, outside ``TrackerError``. The
    round-trip would refuse the first anyway; it never gets the chance at the
    second, which is why the length bound is not redundant.
    """
    if not isinstance(value, str) or not value.startswith(_ATTEMPT_PREFIX):
        raise TrackerValidationError(
            f"attempt must be rendered as {_ATTEMPT_PREFIX}NNN; got {value!r}")
    digits = value[len(_ATTEMPT_PREFIX):]
    if not digits or not digits.isascii() or not digits.isdigit():
        raise TrackerValidationError(
            f"attempt must be rendered as {_ATTEMPT_PREFIX}NNN with ASCII "
            f"digits; got {value!r}. 'isdigit' alone is true of chr(0x0661) "
            "and int() accepts it, so the ascii clause is what narrows this to "
            "the ten characters the renderer writes")
    if len(digits) > _MAX_ATTEMPT_DIGITS:
        raise TrackerValidationError(
            f"attempt {value!r} is spelled with {len(digits)} digits; the "
            f"ceiling is {_MAX_ATTEMPT_DIGITS}, because int() raises "
            "ValueError -- which is not a TrackerError -- once the string is "
            "longer than sys.int_max_str_digits, and the bound has to be "
            "reachable before the conversion is")
    attempt = int(digits)
    if attempt < 1:
        raise TrackerValidationError(
            f"{value!r} spells attempt {attempt}; attempts start at one, and "
            "zero is not the attempt a reservation could have recorded")
    if _attempt_token(attempt) != value:
        raise TrackerValidationError(
            f"{value!r} is not the canonical spelling of attempt {attempt}, "
            f"which is {_attempt_token(attempt)!r}; a record whose identity is "
            "the sha256 of its bytes may have exactly one spelling")
    return attempt


class _AttemptToken:
    """``.fullmatch`` over the canonical attempt spelling, for the callers that
    only want the yes/no -- Task 5's evidence validator among them.

    It is a thin front on ``_parse_attempt_token`` rather than a fourth grammar
    object beside ``_CharClass``, ``_Numbered`` and ``_Hex``, because the rule
    here is not a character class at all: it is "this is what the renderer would
    have written", and only the renderer can answer that.
    """

    __slots__ = ()

    def fullmatch(self, value) -> bool:
        try:
            _parse_attempt_token(value)
        except TrackerValidationError:
            return False
        return True


_ATTEMPT_TOKEN = _AttemptToken()


def _table_safe(value, *, field: str, list_valued: bool = False) -> str:
    """One worker-result cell, screened by ``_cell_safe`` rather than by a list.

    THE SCREEN IS NOT A CLOSED LIST OF POISON CHARACTERS, and this is the fifth
    task in this build to have to say so. A screen spelled ``"|" in value or
    "\\n" in value`` passes ``\\x0b``, ``\\x0c``, ``\\x1c``, ``\\x1d``,
    ``\\x1e``, ``\\x85``, ``\\u2028`` and ``\\u2029`` -- every one of which
    ``str.splitlines`` breaks on, so the rendered row comes back as two lines,
    the first of which still parses as a two-cell field row holding HALF the
    value. Measured: a ``concerns`` of ``"a\\x0bb"`` rendered, parsed back as
    ``"a"``, and validated clean. ``_cell_safe`` asks the reader
    (``_splits_the_section``) and asks the encoder (``_survives_the_encoder``)
    instead of remembering them, and adds the ASCII control characters and the
    surrounding-whitespace rule that no reader derives.

    THE COMMA BAR IS SEPARATE AND IS THE CALLER'S TO ASK FOR. ``_cell_safe``
    deliberately admits a comma, because ``concerns`` and ``blocking_reason``
    are free text a human reads and English has commas. A member of a
    comma-separated cell is the opposite case: ``tests=("a,b",)`` renders as
    ``a,b`` and parses back as TWO commands, silently, with the result still
    valid -- so the bar goes on the writer that knows the cell is list-valued.

    ``-`` IS REFUSED AS A LIST MEMBER for the same round-trip reason.
    ``tests=("-",)`` renders the empty-cell marker and parses back as no tests
    at all: a suite of one becomes a suite of none with nothing raised.
    """
    if not isinstance(value, str) or not value:
        raise TrackerValidationError(
            f"{field} must be a nonempty string; got {value!r}")
    if not _cell_safe(value):
        raise TrackerValidationError(
            f"{field}={value!r} is not table-safe: a cell may not carry '|', "
            "anything the section reader breaks a line on, an ASCII control "
            "character, anything the UTF-8 encoder refuses, or surrounding "
            "whitespace -- each of them parses back as different rows, "
            "different columns, or not at all")
    if list_valued:
        if "," in value:
            raise TrackerValidationError(
                f"{field}={value!r} is a member of a comma-separated cell and "
                "carries a ','; it would parse back as two members, which is "
                "silent and still valid")
        if value == _ABSENT_CELL:
            raise TrackerValidationError(
                f"{field} names {_ABSENT_CELL!r} as a member; that is the "
                "empty-cell marker, so a list of one parses back as a list of "
                "none")
    return value


def _digest_reference(value, *, field: str = "reference") -> tuple[str, str]:
    """``<repository-relative-path>#sha256=<digest>`` -> ``(path, digest)``.

    A reference is resolvable and BOUND, and both halves are load-bearing. The
    path goes through ``_safe_relative``, so it is repository-relative,
    POSIX-spelled, traversal-free, glob-free and admits exactly one spelling;
    the digest goes through P02's ``_SHA256``, so a truncated one -- the failure
    that reads as a successful binding -- is refused rather than matched
    loosely.

    ``#`` IS REFUSED INSIDE THE PATH, which is what makes the split
    unambiguous. ``_cell_safe`` admits a ``#``, so ``docs/a#sha256=<64 hex>.md``
    is a legal path and a reference built from it has two plausible readings;
    counting the delimiter once removes the ambiguity rather than resolving it
    by picking a side. Task 10's ``_result_identity`` refuses ``#`` in a
    published result path for the same reason, so the two agree.

    ``,`` IS REFUSED ONE LEVEL DOWN, IN ``_safe_relative``, AND IT IS THE SAME
    ARGUMENT. A reference is a citable token, and every cell that carries one
    -- ``evidence``, ``Verification``, ``Result``, ``Checkpoints``,
    ``phase_plans`` -- is read back with ``_csv``, so a comma inside the path
    half re-columns the cell rather than the reference: the reader gets two
    members, both syntactically fine, neither the one that was written. That
    one is a SPLIT and this one is an AMBIGUITY is why they sit at different
    levels: ``#`` has two readings of one member, ``,`` has one reading of two.

    ``PlanMetadataError`` IS WRAPPED. ``_safe_relative`` belongs to the plan
    grammar and raises the plan grammar's exception; a controller importing a
    worker result catches ``TrackerValidationError`` and would not see it.
    """
    text = _table_safe(value, field=field)
    path, delimiter, digest = text.partition(_DIGEST_DELIMITER)
    if not delimiter or "#" in path or not _SHA256.fullmatch(digest):
        raise TrackerValidationError(
            f"{field}={value!r} must be <repository-relative-path>"
            f"{_DIGEST_DELIMITER}<64 lowercase hex>; an unbound path names a "
            "file whose contents may have changed since, and a short or "
            "upper-case digest matches nothing while looking exactly like a "
            "match")
    try:
        relative = _safe_relative(path)
    except PlanMetadataError as exc:
        raise TrackerValidationError(
            f"{field}={value!r} does not name a usable repository-relative "
            f"path: {exc}") from exc
    return relative.as_posix(), digest


def _status_route(status) -> str:
    """Which of the three routes a status takes. TOTAL over ``WORKER_STATUSES``
    by construction, because that tuple is the concatenation of the three.

    This is the ONE place the reversal from ``superb:pipeline`` is written down.
    There, ``NEEDS_CONTEXT`` and ``PLAN_CONFLICT`` sat with ``BLOCKED`` in a
    single "stop and ask the human" arm; here they are a different route with a
    different required field, and a controller that re-derived the route from a
    list of status literals would be writing that reversal a second time.
    """
    for statuses, route in ((COMPLETION_STATUSES, _ROUTE_COMPLETION),
                            (QUORUM_STATUSES, _ROUTE_QUORUM),
                            (HALT_STATUSES, _ROUTE_HALT)):
        if status in statuses:
            return route
    raise TrackerValidationError(
        f"unknown worker status {status!r}; the vocabulary is "
        f"{list(WORKER_STATUSES)!r}")


def _result_list(value, *, field: str) -> tuple[str, ...]:
    """One list-valued field, normalised to a tuple and screened member by member.

    THE TYPE IS REFUSED RATHER THAN COERCED, and the two shapes it refuses are
    the two that fail OPEN. A bare string is an iterable of characters, so
    ``commits="abc..."`` would validate forty single characters and render a
    comma-separated smear. A generator is empty the second time it is read: the
    validator counts it once, every later reader sees nothing, and a result
    whose commits were never checked renders with an empty commits cell. Both
    were reachable in the draft this replaces; neither raises anything.
    """
    if not isinstance(value, (tuple, list)):
        raise TrackerValidationError(
            f"{field} must be a tuple or a list; got {type(value).__name__} "
            f"{value!r}. A bare string is an iterable of characters and a "
            "generator is empty the second time it is read, so neither can be "
            "validated once and rendered twice")
    values = tuple(value)
    for member in values:
        _table_safe(member, field=field, list_valued=True)
    if len(set(values)) != len(values):
        raise TrackerValidationError(
            f"{field}={list(values)!r} names a member twice; a repeat makes the "
            "cell's length disagree with the number of things it names")
    return values


def _result_checkpoints(value) -> tuple[dict, ...]:
    """The checkpoint table, normalised and screened.

    A CHECKPOINT IS A MAPPING, ASKED BY TYPE. ``set(checkpoint) != {...}`` alone
    admits the list ``["id", "status", "evidence"]``, whose ``set`` is exactly
    the key set, and the next line indexes it by name -- ``TypeError: list
    indices must be integers``, outside ``TrackerError``.
    """
    if not isinstance(value, (tuple, list)):
        raise TrackerValidationError(
            f"{_WORKER_CHECKPOINTS} must be a tuple or a list; got "
            f"{type(value).__name__} {value!r}")
    checkpoints = []
    seen = set()
    for checkpoint in value:
        if not isinstance(checkpoint, dict):
            raise TrackerValidationError(
                f"a checkpoint is a mapping of {list(_CHECKPOINT_KEYS)!r}; got "
                f"{type(checkpoint).__name__} {checkpoint!r}")
        if set(checkpoint) != set(_CHECKPOINT_KEYS):
            raise TrackerValidationError(
                f"a checkpoint carries exactly {list(_CHECKPOINT_KEYS)!r}; got "
                f"{sorted(checkpoint)!r}")
        identifier = _table_safe(checkpoint["id"], field="checkpoint id")
        if not _TOKEN.fullmatch(identifier):
            raise TrackerValidationError(
                f"checkpoint id {identifier!r} is not an identifier token")
        if _member(identifier, _RESERVED_ROW_WORDS):
            raise TrackerValidationError(
                f"checkpoint id {identifier!r} is a word the parser reads "
                f"structurally in column one ({list(_RESERVED_ROW_WORDS)!r}); a "
                "checkpoint named after a table header or the table rule "
                "renders as an ordinary row and parses as neither, so the "
                "checkpoint disappears out of a result whose identity is the "
                "sha256 of bytes that still carry it")
        if not _member(checkpoint["status"], _CHECKPOINT_STATES):
            raise TrackerValidationError(
                f"unknown checkpoint state {checkpoint['status']!r}; the "
                f"vocabulary is {list(_CHECKPOINT_STATES)!r}")
        evidence = _table_safe(checkpoint["evidence"], field="checkpoint evidence")
        _digest_reference(evidence, field="checkpoint evidence")
        if identifier in seen:
            raise TrackerValidationError(
                f"checkpoint {identifier!r} appears twice; a checkpoint whose "
                "state depends on which copy the scan reaches first is not a "
                "checkpoint")
        seen.add(identifier)
        checkpoints.append({"id": identifier, "status": checkpoint["status"],
                            "evidence": evidence})
    return tuple(checkpoints)


def _validate_worker_result(result) -> dict:
    """Screen one worker result and return the NORMALISED copy that renders.

    Called by ``render_worker_result`` and again by ``parse_worker_result``, so
    the two directions cannot disagree about what a legal result is -- which is
    what lets the codec promise that a malformed result cannot be published and
    cannot be imported, rather than only one of the two.

    IT RETURNS A NEW DICT AND THE CALLER RENDERS THAT ONE. Validating the
    caller's dict and then rendering the caller's dict is how a generator gets
    counted once and rendered empty; normalising and rendering the normalised
    copy closes that by construction.
    """
    if not isinstance(result, dict):
        raise TrackerValidationError(
            f"a worker result is a mapping; got {type(result).__name__} "
            f"{result!r}")
    expected = (*WORKER_RESULT_FIELDS, _WORKER_CHECKPOINTS)
    missing = [field for field in expected if field not in result]
    if missing:
        raise TrackerValidationError(
            f"worker result is missing fields: {missing}")
    unknown = sorted(set(result) - set(expected))
    if unknown:
        raise TrackerValidationError(
            f"worker result carries unknown fields: {unknown}. Nothing renders "
            "them, so an importer would never see them and a worker would "
            "believe it had said something")

    scalars = {}
    scalars["run_id"] = _table_safe(result["run_id"], field="run_id")
    if not _RUN_ID.fullmatch(scalars["run_id"]):
        raise TrackerValidationError(
            f"run_id {scalars['run_id']!r} is not a run-id token")
    scalars["task_id"] = _table_safe(result["task_id"], field="task_id")
    if not _TOKEN.fullmatch(scalars["task_id"]):
        raise TrackerValidationError(
            f"task_id {scalars['task_id']!r} is not an identifier token")
    scalars["owner"] = _table_safe(result["owner"], field="owner")
    if not _TOKEN.fullmatch(scalars["owner"]):
        raise TrackerValidationError(
            f"owner {scalars['owner']!r} is not an identifier token")
    scalars["attempt"] = result["attempt"]
    _attempt_token(scalars["attempt"])
    if not _member(result["kind"], TASK_KINDS):
        raise TrackerValidationError(
            f"unknown task kind {result['kind']!r}; the kinds are "
            f"{list(TASK_KINDS)!r}")
    scalars["kind"] = result["kind"]
    route = _status_route(result["status"])
    scalars["status"] = result["status"]

    lists = {field: _result_list(result[field], field=field)
             for field in _WORKER_LIST_FIELDS}

    scalars["source_ref"] = _table_safe(result["source_ref"], field="source_ref")
    if (scalars["source_ref"] != _ABSENT_CELL
            and not _COMMIT.fullmatch(scalars["source_ref"])):
        raise TrackerValidationError(
            f"source_ref {scalars['source_ref']!r} is neither a full 40-hex "
            f"commit nor {_ABSENT_CELL!r}; the baseline..source-head range is a "
            "proof only between immutable ends")
    for commit in lists["commits"]:
        if not _COMMIT.fullmatch(commit):
            raise TrackerValidationError(
                f"commits names {commit!r}; a recorded commit is forty "
                "lowercase hex characters, and a symbolic name resolves "
                "somewhere else tomorrow")
    for reference in lists["evidence"]:
        _digest_reference(reference, field="evidence")

    scalars["concerns"] = _table_safe(result["concerns"], field="concerns")
    scalars["question_record"] = _table_safe(result["question_record"],
                                             field="question_record")
    scalars["blocking_reason"] = _table_safe(result["blocking_reason"],
                                             field="blocking_reason")
    _validate_result_route(scalars, lists, route)

    unwritten = sorted(set(WORKER_RESULT_FIELDS) - set(scalars) - set(lists))
    if unwritten:
        raise TrackerValidationError(
            f"the codec renders {unwritten} but screens nothing into them; a "
            "field added to WORKER_RESULT_FIELDS without a validator is a cell "
            "nobody checks")
    validated = {
        field: lists[field] if field in lists else scalars[field]
        for field in WORKER_RESULT_FIELDS
    }
    validated[_WORKER_CHECKPOINTS] = _result_checkpoints(
        result[_WORKER_CHECKPOINTS])
    return validated


def _validate_result_route(scalars: dict, lists: dict, route: str) -> None:
    """F5, and the whole of "DONE is evidence, not acceptance".

    The status word says which route the controller should take. The routing
    fields say the same thing a second time, in a form that can be resolved: a
    question record that can be opened, a blocking reason that can be read. The
    codec accepts only where the two agree, so no status is acted on because of
    the word alone.
    """
    status = scalars["status"]
    question_record = scalars["question_record"]
    blocking_reason = scalars["blocking_reason"]
    if route == _ROUTE_QUORUM:
        if question_record == _ABSENT_CELL:
            raise TrackerValidationError(
                f"{status} raises a quorum question and must name its question "
                f"record as <path>{_DIGEST_DELIMITER}<digest>. A worker that "
                "says 'I need a decision' without naming the record has raised "
                "nothing, and the controller is left holding a status it cannot "
                "act on -- which is why this is refused exactly as a result "
                "with a missing owner is refused")
        _digest_reference(question_record, field="question_record")
        if blocking_reason != _ABSENT_CELL:
            raise TrackerValidationError(
                f"{status} routes to a quorum, not a halt, so blocking_reason "
                f"must be {_ABSENT_CELL!r}; a result claiming both routes is "
                "one a controller cannot dispatch")
        return
    if route == _ROUTE_HALT:
        if blocking_reason == _ABSENT_CELL:
            raise TrackerValidationError(
                f"{status} halts the run and must say what it is waiting for; "
                "three brains cannot conjure an API key, and a halt with no "
                "stated reason is one nobody can clear")
        if question_record != _ABSENT_CELL:
            raise TrackerValidationError(
                f"{status} halts the run and must not name a question record; "
                "a halt routed to a quorum would spend three brain slots on a "
                "question no quorum can answer")
        return
    if question_record != _ABSENT_CELL or blocking_reason != _ABSENT_CELL:
        raise TrackerValidationError(
            f"{status} is a completion status and carries neither a question "
            f"record nor a blocking reason; it claims the work is finished, so "
            "there is nothing left to ask and nothing left to wait for")
    if not lists["evidence"]:
        raise TrackerValidationError(
            f"{status} claims completion and names no evidence; P02 refuses a "
            "completed task row whose verification cell is empty, and a claim "
            "with nothing to check cannot be refused by checking it -- it can "
            "only be believed, which is what this codec exists to prevent")
    if scalars["kind"] == TASK_KINDS[0]:
        if scalars["source_ref"] == _ABSENT_CELL or not lists["commits"]:
            raise TrackerValidationError(
                f"{status} claims a completed {TASK_KINDS[0]} task and names no "
                "source ref or no commits; the baseline..source-head range "
                "proof has no far end without them, and an empty range is fault "
                "F4 arriving as a completion")
        if not lists["tests"]:
            raise TrackerValidationError(
                f"{status} claims a completed {TASK_KINDS[0]} task and names no "
                "tests; the approved task suite is never empty, so a completion "
                "naming none has run something other than the suite it was "
                "given, or nothing at all")
    elif not lists["artifacts"]:
        raise TrackerValidationError(
            f"{status} claims a completed {TASK_KINDS[1]} task and names no "
            "artifacts; an artifact task is proved by the documents existing, "
            "so a completion naming none has produced nothing")
    if status == COMPLETION_STATUSES[1] and scalars["concerns"] == _ABSENT_CELL:
        raise TrackerValidationError(
            f"{status} states a concern in its own name and records none; "
            f"{COMPLETION_STATUSES[0]} is the status for work with nothing to "
            "flag, and a concern nobody wrote down is one no reviewer can read")


def _result_cell(value) -> str:
    """One rendered cell. Not ``_cell``, which is P03's two-argument writer for
    the ``## Quorum`` mirror and is called at eleven sites -- a module-level
    ``def _cell(value)`` here would rebind the global and turn every one of them
    into a ``TypeError`` at runtime.
    """
    if isinstance(value, tuple):
        return ",".join(value) or _ABSENT_CELL
    return str(value)


def _owner_line(owner: str) -> str:
    r"""``impl-1`` -> ``- **Owner:** impl-1``. THE SINGLE CONVERSION POINT for the
    owner grammar P06 parses, in both directions, for the reason
    ``_attempt_token`` is one: two spellings would be two answers to "who owned
    this attempt", and P06 decides reviewer independence on the answer.

    The owner has already been through ``_table_safe`` and ``_TOKEN``, so it
    carries no whitespace and no line break: the rendered line always satisfies
    P06's ``^-\s+\*\*Owner:\*\*\s*(\S+)\s*$`` and always yields exactly
    this id.
    """
    return f"{_OWNER_LINE_PREFIX}{owner}"


def _screen_owner_line(lines: list, owner: str) -> None:
    """The owner line is present exactly once and agrees with the owner cell.

    The canonical re-render would refuse a disagreement anyway -- but for "not
    canonical", which names the bytes and not the fact. P06 reads this line to
    decide whether a reviewer ever owned the task; a document whose line and
    cell disagree is a document with two owners, and it deserves to be refused
    by the rule it breaks.
    """
    found = [line for line in lines if line.startswith(_OWNER_LINE_PREFIX)]
    if len(found) != 1:
        raise TrackerValidationError(
            f"a worker result states its owner as {_OWNER_LINE_PREFIX!r}<id> "
            f"exactly once; this document has {len(found)}. The line is the "
            "grammar P06's reviewer-independence check parses owner history "
            "out of, and a result that does not carry it is one that reports "
            "no owner to the check that must not hand the task back to them")
    if found[0] != _owner_line(owner):
        raise TrackerValidationError(
            f"the owner line {found[0]!r} does not state the owner cell "
            f"{owner!r}; a result naming two owners is one whose reviewer "
            "independence depends on which of the two a reader happened to "
            "scan")


def _split_row(line: str) -> list:
    """``| a | b |`` -> ``["a", "b"]``. Cells are stripped, which is why
    ``_cell_safe`` refuses a value with surrounding whitespace: two spellings
    that strip to one cell would both parse and only one of them re-renders.
    """
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_worker_result(result: dict) -> str:
    """Render one validated immutable worker result in canonical field order."""
    validated = _validate_worker_result(result)
    rows = tuple(
        (field,
         _attempt_token(validated[field]) if field == "attempt"
         else _result_cell(validated[field]))
        for field in WORKER_RESULT_FIELDS
    )
    checkpoints = tuple(
        tuple(checkpoint[key] for key in _CHECKPOINT_KEYS)
        for checkpoint in validated[_WORKER_CHECKPOINTS]
    )
    lines = [
        WORKER_RESULT_MARKER,
        WORKER_RESULT_TITLE,
        "",
        _owner_line(validated["owner"]),
        "",
        "## Result",
        *_render_table(_RESULT_HEADER, rows),
        "",
        "## Checkpoints",
        *_render_table(_CHECKPOINT_HEADER, checkpoints),
    ]
    return "\n".join(lines) + "\n"


def parse_worker_result(text: str) -> dict:
    """Parse a canonical worker result; refuse a foreign, reordered or
    non-canonical document.

    THE LAST SCREEN IS THE RENDERER. Everything above it reads the tables; the
    final comparison demands that re-rendering what was read gives back the
    bytes that were handed in. Without it the parse is a SEARCH -- it finds the
    rows it recognises and is silent about everything else -- and a worker
    result is an immutable document whose identity is the sha256 of those bytes.
    A parse that ignores part of the file gives one result two identities, and
    the half it ignored is exactly where a sentence contradicting the table
    would sit.
    """
    if not isinstance(text, str):
        raise TrackerValidationError(
            f"a worker result is text; got {type(text).__name__}")
    lines = text.splitlines()
    if not lines or lines[0] != WORKER_RESULT_MARKER:
        raise TrackerValidationError(
            "worker result marker is missing or foreign; the two formats do "
            "not interoperate")
    rows = [_split_row(line) for line in lines if line.startswith("| ")]
    field_rows = [row for row in rows
                  if len(row) == 2
                  and row[0] not in (_RESULT_HEADER[0], _TABLE_RULE)]
    names = [row[0] for row in field_rows]
    if names != list(WORKER_RESULT_FIELDS):
        raise TrackerValidationError(
            "worker result fields are missing, unknown, or reordered: expected "
            f"{list(WORKER_RESULT_FIELDS)}, read {names}")
    values = {row[0]: row[1] for row in field_rows}
    _screen_owner_line(lines, values["owner"])
    result = dict(values)
    result["attempt"] = _parse_attempt_token(values["attempt"])
    for field in _WORKER_LIST_FIELDS:
        raw = values[field]
        result[field] = () if raw == _ABSENT_CELL else tuple(raw.split(","))
    result[_WORKER_CHECKPOINTS] = tuple(
        dict(zip(_CHECKPOINT_KEYS, row))
        for row in rows
        if len(row) == 3 and row[0] not in (_CHECKPOINT_HEADER[0], _TABLE_RULE)
    )
    validated = _validate_worker_result(result)
    if render_worker_result(validated) != text:
        raise TrackerValidationError(
            "worker result is not canonical: re-rendering what was read does "
            "not give back the bytes that were handed in. The document's "
            "identity is the sha256 of those bytes, so anything the parse "
            "ignored -- a second marker, a paragraph under the table, a "
            "checkpoint row outside its section, a CRLF copy, an extra space "
            "inside a cell -- would give one result two identities")
    return validated


# ---------------------------------------------------------------------------
# P04 Task 5: the digest-bound typed PASS record
#
# Evidence is the ONLY acceptable proof that a suite ran, so the codec is built
# the way Task 4's worker-result codec is: ONE validator, called by the renderer
# and again by the parser, and a final byte comparison against a re-render.
#
# THE BRIEF SHIPPED A PARSER AND NO RENDERER, and a parser without one is a
# SEARCH: it finds the rows it recognises and is silent about everything else.
# What "everything else" means here is a paragraph under the table reading "the
# suite actually failed; recorded PASS to unblock the run". Every field the
# table carries is screened; that paragraph is the one place a forged PASS can
# hide, and a search cannot see it. The renderer is also the only way the two
# directions can be SWEPT against each other -- Task 4 had no round-trip family
# and shipped two shapes ``render`` accepted and ``parse`` refused, published
# immutably into files the run can never read and can never correct.
#
# `import hashlib` AND `import re` WERE BOTH IN THE BRIEF AND BOTH ARE ABSENT
# HERE. ``hashlib`` is imported once at the top of this module and a second
# module-level ``import hashlib`` is a second binding of the name, which the
# committed AST guard counts; ``re`` is not among the twelve allowed imports at
# all, and ``_ATTEMPT_TOKEN`` -- which the brief re-declared as a compiled
# pattern -- already exists as Task 4's round-trip front on ``_attempt_token``.
# Rebinding it would have replaced "this is what the renderer would have
# written" with "three or more digits", which accepts ``attempt-0001``: a second
# spelling of attempt one, in a record whose identity is the sha256 of its bytes.
# ---------------------------------------------------------------------------

EVIDENCE_MARKER = "<!-- pipeline-auto-verification-evidence/v1 -->"
EVIDENCE_TITLE = "# Pipeline Auto — Verification Evidence"

#: EXTENDED BY THE PHASE THAT NEEDS THE PURPOSE, never pre-populated here. P05
#: appends ``task-review`` and ``adversarial``; P06 appends ``branch-review``,
#: ``completeness`` and ``final``. The validator refusing an unregistered
#: purpose is the point: a purpose nobody declared is a record nobody validates.
EVIDENCE_PURPOSES = ("task-test", "task-integration", "phase")

#: The two things a suite can be run ABOUT. The template says
#: ``<task_or_phase>/<stable-id>`` and a template that states a rule the codec
#: does not check is a claim nobody enforces, so the kinds are written down here
#: and screened. They are deliberately NOT cross-checked against ``purpose``:
#: the mapping is derivable for the three purposes this phase ships
#: (``task-test`` and ``task-integration`` are about a task, ``phase`` about a
#: phase) and is NOT derivable for ``adversarial``, ``completeness`` or
#: ``final``, so a rule written here would be one P05 and P06 have to remember
#: to extend in a second place -- and a rule that is silently wrong for the
#: purposes added after it is worse than no rule.
EVIDENCE_SUBJECT_KINDS = ("task", "phase")

#: ``outcome`` HAS EXACTLY ONE LEGAL VALUE. A record that is not a PASS is not
#: evidence, and is never written; the field exists so that a reader never has
#: to ask what a record without it would have meant.
EVIDENCE_OUTCOME = "PASS"

#: The attempt cell for a record no attempt owns -- a phase suite belongs to the
#: phase, not to an attempt at a task. Spelled here rather than inline because
#: the renderer writes it and the parser reads it back.
EVIDENCE_NO_ATTEMPT = "N/A"

#: THE FIELD ORDER IS THE GRAMMAR, exactly as ``WORKER_RESULT_FIELDS`` is:
#: ``parse_verification_evidence`` matches the rendered names positionally
#: against this tuple, so a reordered record fails at the position that should
#: have held the field, a renamed one at its own position, a dropped one shifts
#: every later field onto the wrong position, and an extra one makes the count
#: wrong. Four defects refused by one comparison.
EVIDENCE_FIELDS = (
    "purpose", "run_id", "subject", "attempt", "code_state", "outcome",
    "commands", "environment", "inputs",
)

#: The fields rendered as a JSON array rather than as a bare cell. ``commands``
#: has to be one because a shell command legitimately carries the comma that
#: ``_cell_list`` uses as its separator, and ``inputs`` follows it so that the
#: two array cells have one spelling between them.
_EVIDENCE_ARRAY_FIELDS = ("commands", "inputs")


def _json_array_cell(values: tuple) -> str:
    """THE one spelling of a JSON-array cell, for ``commands`` and ``inputs``.

    NO SCREEN IS APPLIED TO THE RESULT, and that is a ruling rather than an
    omission. ``json.dumps`` defaults to ``ensure_ascii``, so every character
    outside ``\\x20``-``\\x7e`` comes back as a ``\\uXXXX`` escape: the rendered
    cell cannot carry a line break, a control character, a lone surrogate or a
    leading or trailing space whatever the members hold. The one character it
    CAN pass through is ``|``, and every member has already been through
    ``_cell_safe``, which refuses it. A ``_table_safe`` call here would
    therefore be a screen no input can reach, and an unreachable screen reads,
    to the next person, as a guarantee that something is being checked here
    which is not.

    ``allow_nan=False``, FOR ``_dumps``'S REASON AND NOT BY CALLING IT.
    ``_dumps`` is the module's one spelling of a JSON *file* -- sorted, indented
    and newline-terminated -- and a tracker cell is one line, so this cannot
    delegate to it; what it can do is not repeat the default it was written to
    correct. Measured: without this, ``_json_array_cell((float("nan"),))``
    returns ``'[NaN]'``, a bare token RFC 8259 has no literal for, so the cell
    a record carries -- and the digest binds -- is a document only Python can
    read back. Today ``commands`` is the only field that reaches here unscreened
    and ``_parse_command_suite`` refuses the float on the way back, so the
    escape is closed downstream; ``ValueError`` is what refuses it now, and
    ``_evidence_commands`` already catches that, so the refusal lands in the
    family and one screen earlier. No AST guard covers ``json.dumps`` -- only
    ``json.loads`` -- so this is written here rather than relied on.
    """
    return json.dumps(list(values), allow_nan=False)


def _evidence_subject(value) -> tuple[str, str]:
    """``task/T1`` -> ``("task", "T1")``. Both halves are screened.

    THE BRIEF'S CHECK WAS ``"/" not in subject or not subject.split("/", 1)[1]``
    and it accepts ``"/T1"``: the delimiter is present and the tail is nonempty,
    so a subject with NO KIND AT ALL is a legal subject. It equally accepts
    ``"phasse/P04"`` and ``"anything/x"``, which is how a record about a typo'd
    kind gets filed under a kind nothing will ever look for -- the failure is
    not that the record is refused later, it is that it is never found.
    """
    text = _table_safe(value, field="subject")
    kind, delimiter, identifier = text.partition("/")
    if not delimiter or not _member(kind, EVIDENCE_SUBJECT_KINDS):
        raise TrackerValidationError(
            f"subject={value!r} must be <kind>/<stable-id> with the kind one "
            f"of {list(EVIDENCE_SUBJECT_KINDS)!r}; a subject with no kind, or "
            "with a kind nothing registers, names a record no reader looking "
            "for this subject will ever find")
    if not _TOKEN.fullmatch(identifier):
        raise TrackerValidationError(
            f"subject={value!r} names {identifier!r} as its stable id, which "
            "is not an identifier token; the id is what a later phase joins "
            "this record to a task or a phase row on")
    return kind, identifier


def _evidence_commands(value) -> tuple[str, ...]:
    """The exact ordered command tuple, SCREENED BY THE READER THAT READS IT BACK.

    ``_parse_command_suite`` is this module's one statement of what a command
    suite is. A second member screen written here would be a second statement,
    and two statements drift in exactly the direction Task 4 already shipped
    twice: a value the renderer accepts and the parser refuses, published
    immutably into a file the run can never read and can never correct. So the
    screen is the ROUND TRIP -- render the cell, hand it to the reader, and
    return the reader's own answer. The renderer and the parser then cannot
    disagree about a command suite, because they are the same call.

    ``PlanMetadataError`` IS WRAPPED, for ``_digest_reference``'s reason.
    ``_parse_command_suite`` belongs to the phase-plan grammar and raises the
    plan grammar's exception, which is a SIBLING of ``TrackerValidationError``
    and not a subclass: the brief's own ``{"commands": "[]"}`` and
    ``{"commands": "not-json"}`` cases assert ``TrackerValidationError`` and
    both would have failed. A controller resolving evidence catches the tracker
    family and would not have seen a malformed suite at all.
    """
    if not isinstance(value, (tuple, list)):
        raise TrackerValidationError(
            f"commands must be a tuple or a list; got {type(value).__name__} "
            f"{value!r}. A bare string is an iterable of characters, so "
            "'make check' would validate as ten commands and render as a "
            "smear, and a generator is empty the second time it is read")
    try:
        cell = _json_array_cell(tuple(value))
    except (TypeError, ValueError) as exc:
        raise TrackerValidationError(
            f"commands={list(value)!r} does not serialise to JSON "
            f"({type(exc).__name__}: {exc}); the cell a record carries is the "
            "array, so a suite that cannot be written is not a suite") from exc
    try:
        return _parse_command_suite(cell)
    except PlanMetadataError as exc:
        raise TrackerValidationError(
            f"commands={list(value)!r} is not a usable verification command "
            f"suite: {exc}") from exc


def _evidence_inputs(value) -> tuple[str, ...]:
    """The artifacts the suite consumed, each BOUND to its content digest.

    THE BRIEF NEVER LOOKED AT THIS FIELD. Its template declares ``inputs`` as an
    ``artifact_JSON_path_sha256_array_or_dash`` and its parser reads the cell
    and hands it back as whatever text was in it -- so the one field that says
    "and these are the exact bytes the suite was run against" was the only field
    in a digest-bound proof record that was not bound to anything. An unbound
    path names a file whose contents may have changed since, which is the
    failure ``_digest_reference`` exists for, arriving through the field whose
    whole job is to prevent it.

    THE ``isinstance`` GUARD IS REACHABLE TWICE OVER, which is why it stays
    where the ones in ``_json_array_cell`` and ``_validate_verification_evidence``
    went. Review read it as the same unreachable pattern -- a bare string
    becomes a tuple of characters that each fail ``_digest_reference``, a
    generator is materialised by ``tuple()`` -- and both of those are true and
    neither is the case that matters. Measured with the guard bypassed:
    ``inputs=5`` raises ``TypeError: 'int' object is not iterable`` from
    ``tuple()``, OUTSIDE ``TrackerError``, killing a controller that wrapped an
    evidence render in ``except TrackerError``; and ``inputs=iter(())`` is
    ACCEPTED, rendering the empty-cell marker for a record whose author handed
    over an iterator. A screen with a measured escape behind it is not a screen
    that reads as a guarantee of nothing.
    """
    if not isinstance(value, (tuple, list)):
        raise TrackerValidationError(
            f"inputs must be a tuple or a list; got {type(value).__name__} "
            f"{value!r}. A non-iterable reaches tuple() as a TypeError from "
            "outside this module's exception family, and an exhausted iterator "
            "reaches it as no inputs at all")
    values = tuple(value)
    for member in values:
        _digest_reference(member, field="inputs member")
    if len(set(values)) != len(values):
        raise TrackerValidationError(
            f"inputs={list(values)!r} names a reference twice; a repeat makes "
            "the array's length disagree with the number of artifacts it binds")
    return values


def _evidence_inputs_cell(cell: str) -> tuple[str, ...]:
    """The ``inputs`` CELL -> the tuple ``_evidence_inputs`` screens.

    ``[]`` IS REFUSED AND ``-`` IS NOT. Both say "this suite consumed nothing"
    and only one of them re-renders, so accepting the pair would give one record
    two spellings -- and this record's identity is the sha256 of its bytes.
    """
    if cell == _ABSENT_CELL:
        return ()
    try:
        values = _loads(cell, "an evidence inputs array")
    except TrackerError as exc:
        raise TrackerValidationError(
            f"inputs must be {_ABSENT_CELL!r} or a JSON array of "
            f"<path>{_DIGEST_DELIMITER}<digest> references; {cell!r} is not "
            f"readable JSON ({exc})") from exc
    if not isinstance(values, list) or not values:
        raise TrackerValidationError(
            f"inputs must be {_ABSENT_CELL!r} or a NONEMPTY JSON array; "
            f"{cell!r} is neither. An empty array and {_ABSENT_CELL!r} say the "
            "same thing and only one of them re-renders, so a record that "
            "accepted both would have two spellings and two digests")
    return tuple(values)


def _validate_verification_evidence(record) -> dict:
    """Screen one evidence record and return the NORMALISED copy that renders.

    Called by ``render_verification_evidence`` and again by
    ``parse_verification_evidence``, so the two directions cannot disagree about
    what a legal record is -- which is what lets this codec promise that a
    forged record can neither be written nor read, rather than only one of the
    two. It returns a NEW dict and the caller renders that one, so a value
    validated once cannot be rendered from a different object.

    THE ATTEMPT IS A TOKEN HERE AND AN ``int`` IN A WORKER RESULT, and the
    difference is deliberate rather than an oversight P05 should tidy up.
    Evidence for a phase suite belongs to no attempt at all, and an ``int``
    field carrying the sentinel ``N/A`` is a field with two types. The token is
    still ``_attempt_token``'s own output -- ``_ATTEMPT_TOKEN`` is a round trip
    through the renderer, not a digit-count pattern -- so there is exactly one
    spelling of any given attempt across both documents.

    ``purpose`` AND ``outcome`` DO NOT GO THROUGH ``_table_safe``, and the
    omission is deliberate. Both are compared against a CLOSED SET of values
    this module wrote -- ``EVIDENCE_PURPOSES`` through ``_member``, which is
    total over every type, and ``EVIDENCE_OUTCOME`` through ``!=``, which is
    too -- so nothing a ``_table_safe`` call could refuse survives the line
    below it, whatever type or spelling it arrives as. Mutation confirmed it:
    deleting both screens left the whole suite green, an equivalent mutant. An
    unreachable screen reads, to the next person, as a guarantee that something
    is being checked here which is not, and this file has already removed the
    same pattern from ``_json_array_cell`` and ``_evidence_commands``. The
    other seven fields keep theirs and the difference is not taste:
    ``_RUN_ID``, ``_ATTEMPT_TOKEN`` and ``_COMMIT`` are matched with
    ``fullmatch``, which raises ``TypeError`` on a non-string -- outside this
    module's exception family -- so ``_table_safe`` is what makes the value a
    string before the pattern is asked; ``environment`` is free text screened
    by nothing else at all; and the two array fields have their own readers.
    ``_member`` and ``!=`` need no such help, which is exactly why these two
    screens were the unreachable ones.
    """
    if not isinstance(record, dict):
        raise TrackerValidationError(
            f"a verification evidence record is a mapping; got "
            f"{type(record).__name__} {record!r}")
    missing = [field for field in EVIDENCE_FIELDS if field not in record]
    if missing:
        raise TrackerValidationError(
            f"verification evidence is missing fields: {missing}")
    unknown = sorted(set(record) - set(EVIDENCE_FIELDS))
    if unknown:
        raise TrackerValidationError(
            f"verification evidence carries unknown fields: {unknown}. Nothing "
            "renders them, so a reader would never see them and a worker would "
            "believe it had said something")

    values = {}
    values["purpose"] = record["purpose"]
    if not _member(values["purpose"], EVIDENCE_PURPOSES):
        raise TrackerValidationError(
            f"unknown evidence purpose {values['purpose']!r}; the registered "
            f"purposes are {list(EVIDENCE_PURPOSES)!r} and each phase adds the "
            "one it needs, because a purpose nobody declared is a record "
            "nobody validates")
    values["run_id"] = _table_safe(record["run_id"], field="run_id")
    if not _RUN_ID.fullmatch(values["run_id"]):
        raise TrackerValidationError(
            f"run_id {values['run_id']!r} is not a run-id token; evidence that "
            "cannot name its run is evidence for no run")
    kind, identifier = _evidence_subject(record["subject"])
    values["subject"] = f"{kind}/{identifier}"
    values["attempt"] = _table_safe(record["attempt"], field="attempt")
    if (values["attempt"] != EVIDENCE_NO_ATTEMPT
            and not _ATTEMPT_TOKEN.fullmatch(values["attempt"])):
        raise TrackerValidationError(
            f"attempt {values['attempt']!r} is neither {EVIDENCE_NO_ATTEMPT!r} "
            f"nor the canonical spelling {_attempt_token(1)!r} of an attempt. "
            "The spelling is the renderer's own, so 'attempt-0001' is refused "
            "as hard as 'later': a record whose identity is the sha256 of its "
            "bytes may name its attempt exactly one way")
    values["code_state"] = _table_safe(record["code_state"], field="code_state")
    if not _COMMIT.fullmatch(values["code_state"]):
        raise TrackerValidationError(
            f"code_state {values['code_state']!r} must be a full 40-character "
            "lowercase hex commit. A symbolic name resolves somewhere else "
            "tomorrow, so a record bound to one proves a suite passed at no "
            "particular state; for a task-integration record it is the --no-ff "
            "merge commit, never the task branch tip")
    values["outcome"] = record["outcome"]
    if values["outcome"] != EVIDENCE_OUTCOME:
        raise TrackerValidationError(
            f"outcome {values['outcome']!r} is not {EVIDENCE_OUTCOME!r}; a "
            "record that is not a PASS is not evidence and is never written, "
            "so this field has exactly one legal value and 'pass' is not it")
    values["commands"] = _evidence_commands(record["commands"])
    values["environment"] = _table_safe(record["environment"],
                                        field="environment")
    if values["environment"] == _ABSENT_CELL:
        raise TrackerValidationError(
            f"environment is {_ABSENT_CELL!r}, which is the empty-cell marker; "
            "a PASS that does not say what it passed on is a PASS nobody can "
            "reproduce, and the field exists to stop exactly that")
    values["inputs"] = _evidence_inputs(record["inputs"])
    return {field: values[field] for field in EVIDENCE_FIELDS}


def _evidence_cell(field: str, value) -> str:
    """One rendered evidence cell. The two array fields render as JSON; an empty
    ``inputs`` renders the empty-cell marker, and ``commands`` can never be
    empty because ``_parse_command_suite`` refuses an empty suite."""
    if field in _EVIDENCE_ARRAY_FIELDS:
        return _json_array_cell(value) if value else _ABSENT_CELL
    return value


def render_verification_evidence(record: dict) -> str:
    """Render one validated typed PASS record in canonical field order.

    THE ONLY WRITER. ``parse_verification_evidence``'s last screen is a byte
    comparison against this function's output, so a record that this did not
    write cannot be read back -- which is the whole of the guarantee that the
    bytes a digest binds are the bytes a validator saw.
    """
    validated = _validate_verification_evidence(record)
    rows = tuple((field, _evidence_cell(field, validated[field]))
                 for field in EVIDENCE_FIELDS)
    lines = [
        EVIDENCE_MARKER,
        EVIDENCE_TITLE,
        "",
        *_render_table(_RESULT_HEADER, rows),
    ]
    return "\n".join(lines) + "\n"


def parse_verification_evidence(text: str) -> dict:
    """Parse one typed PASS record; refuse a foreign, reordered, or
    non-canonical document.

    THE LAST SCREEN IS THE RENDERER, for ``parse_worker_result``'s reason and
    for one more that is specific to evidence. Everything above it reads the
    table; the final comparison demands that re-rendering what was read gives
    back the bytes that were handed in. Without it the parse is a SEARCH, and
    the half it ignores is where a sentence contradicting the table would sit --
    "the suite actually failed, recorded PASS to unblock the run". Every field
    in the table is screened; prose is the only place a forged PASS can hide,
    and this record is the ONLY acceptable proof that a suite ran.
    """
    if not isinstance(text, str):
        raise TrackerValidationError(
            f"a verification evidence record is text; got {type(text).__name__}")
    lines = text.splitlines()
    if not lines or lines[0] != EVIDENCE_MARKER:
        raise TrackerValidationError(
            f"verification evidence marker is missing or foreign; this codec "
            f"reads {EVIDENCE_MARKER!r} and nothing else, and the formats do "
            "not interoperate")
    rows = [_split_row(line) for line in lines if line.startswith("| ")]
    field_rows = [row for row in rows
                  if len(row) == 2
                  and row[0] not in (_RESULT_HEADER[0], _TABLE_RULE)]
    names = [row[0] for row in field_rows]
    if names != list(EVIDENCE_FIELDS):
        raise TrackerValidationError(
            "verification evidence fields are missing, unknown, or reordered: "
            f"expected {list(EVIDENCE_FIELDS)}, read {names}")
    cells = {row[0]: row[1] for row in field_rows}
    record = dict(cells)
    try:
        record["commands"] = _parse_command_suite(cells["commands"])
    except PlanMetadataError as exc:
        raise TrackerValidationError(
            f"the commands cell {cells['commands']!r} is not a verification "
            f"command suite: {exc}") from exc
    record["inputs"] = _evidence_inputs_cell(cells["inputs"])
    validated = _validate_verification_evidence(record)
    if render_verification_evidence(validated) != text:
        raise TrackerValidationError(
            "verification evidence is not canonical: re-rendering what was "
            "read does not give back the bytes that were handed in. The "
            "record's identity is the sha256 of those bytes, so anything the "
            "parse ignored -- a paragraph under the table claiming the suite "
            "actually failed, a second marker, a CRLF copy, an extra space "
            "inside a cell -- would be carried by a document nobody checked")
    return validated


def _openable_path(value, *, field: str) -> Path:
    """One path this module is about to open, screened before ``Path`` sees
    it -- for its TYPE and for its SPELLING, which are two corpora.

    THE NAME IS GENERAL BECAUSE THE SCREEN IS. It began as a screen over
    ``resolve_evidence``'s two search roots; Task 10 takes a ``result_path``
    off a controller and needs exactly the same two questions asked of it.
    A second spelling of "is this a name the filesystem could even be asked
    about" is a second answer, and the one that goes stale is silent -- so
    the function is renamed rather than copied, and both of its original
    call sites keep their own ``field`` labels.

    THE TYPE. ``Path(None)`` is a ``TypeError`` from outside this module's
    exception family, and a controller that caught ``TrackerError`` around an
    evidence read would not catch it. ``bytes`` raises from ``Path`` too, and an
    ``os.PathLike`` would hide an arbitrary ``__fspath__`` behind the read, so
    the accepted types are ``str`` and ``Path`` and nothing else.

    THE SPELLING, AND THIS IS THE HALF A TYPE CHECK CANNOT DO. Measured on this
    Python, against the shipped type-check-only form: a ``run_dir`` or a
    ``repo_dir`` holding ``\\x00`` reaches the syscall as ``ValueError:
    embedded null byte``, from outside ``TrackerError`` -- and it gets there
    silently, because ``is_file()`` and ``os.path.lexists`` are BOTH false for
    that spelling, so no door upstream sees it. ``_cell_safe`` is the screen,
    exactly as ``_plan_text`` uses it for a plan path: a path corpus is not a
    field corpus, and a lone surrogate is the reason the encoder is ASKED
    (``_survives_the_encoder``) rather than remembered.

    THE SURROGATES DO NOT ALL BEHAVE ALIKE, and an earlier revision of this
    docstring said they did. Measured at the ``read_bytes`` call site, with the
    filesystem encoding ``utf-8`` and its error handler ``surrogateescape``:
    only ``U+DC80``-``U+DCFF`` are the ``surrogateescape`` spelling of a real
    filename byte, and those reach the syscall as an ordinary
    ``FileNotFoundError`` -- a file that can exist and merely does not.
    ``U+D800``, ``U+DC00`` and ``U+DFFF`` are outside that window: the encoder
    refuses them and raises ``UnicodeEncodeError``, a ``ValueError``, from
    outside ``TrackerError``. So the screen is load-bearing for most of the
    surrogate range and not for one 128-character slice of it -- which is
    exactly why the encoder is asked per spelling instead of the range being
    remembered, and why a screen that admitted "surrogates are fine on Linux"
    would have been generalised from the one slice that supports it.

    ``reference`` NEEDS NO SCREEN HERE because it already has one:
    ``_digest_reference`` runs it through ``_table_safe`` -> ``_cell_safe``
    before this function is ever called. The roots were the only two arguments
    reaching the filesystem unspelt.
    """
    if isinstance(value, Path):
        spelling = str(value)
    elif isinstance(value, str):
        spelling = value
    else:
        raise TrackerValidationError(
            f"{field} must be a str or a pathlib.Path; got "
            f"{type(value).__name__} {value!r}. bytes would raise TypeError "
            "from Path and an os.PathLike would hide an arbitrary __fspath__ "
            "behind the read")
    if not spelling or not _cell_safe(spelling):
        raise TrackerValidationError(
            f"unusable {field} {spelling!r}: a path this module opens must be "
            "a nonempty string a tracker cell can carry back out unchanged -- no "
            "NUL or other control character, nothing the section reader breaks "
            "a line on, nothing the UTF-8 encoder refuses, no '|', and no "
            "surrounding whitespace. A NUL here reaches the syscall as "
            "ValueError and a lone surrogate as UnicodeEncodeError, both "
            "outside TrackerError, and both past a door that cannot see them")
    return Path(spelling)


class EvidenceMissing(TrackerValidationError):
    """No copy of a digest-bound evidence reference exists under either root.

    UNDER ``TrackerValidationError`` so that every ``except TrackerError`` and
    every ``except TrackerValidationError`` already written keeps catching it:
    this class ADDS a distinction, it does not move a stop out of anyone's
    reach.

    IT EXISTS BECAUSE ``resolve_evidence`` HAS THREE OUTCOMES AND SHIPPED WITH
    TWO NAMES. Resolved; ABSENT -- nothing under the run directory and nothing
    under the repository root; and CORRUPT -- a name that is there and cannot
    be read, or bytes that do not hash to the digest the reference binds, or
    bytes that are not UTF-8. Absence and all three corruptions arrived as the
    same class with the same (absent) ``__cause__``, so the only thing a caller
    could branch on was a substring of a diagnostic -- prose the next task is
    free to reword, which makes it a contract nobody agreed to. This is
    ``QuorumSchemaInvalid``'s own argument one codec along: "a caller -- and a
    test -- that could only see the family could not tell X from Y".

    THE TWO ARE NOT ONE RECOVERY, which is why the distinction is worth a
    class. "No evidence was ever published for this subject" is a run that has
    not done the work yet and may still do it; "the evidence that was published
    cannot be read or does not match its digest" is a run whose durable state
    is damaged, and retrying the same read forever is the wrong answer to it.
    """


def resolve_evidence(run_dir, repo_dir, reference: str) -> dict:
    """Resolve a digest-bound evidence reference and verify its content digest.

    THE RUN DIRECTORY IS SEARCHED FIRST AND A DIGEST MISMATCH STOPS THERE. The
    obvious alternative -- treat a mismatch as "not the file I meant" and keep
    looking -- reads as trying harder and is a fail-open: one reference would
    then resolve to whichever of two files happened to hash right, so anyone
    who can write the repository copy chooses which record a mismatching run
    copy is replaced by. One reference names one document.

    THE SHAPE IS ASKED BEFORE THE OPEN, AND ONLY "NOT THERE" KEEPS LOOKING.
    RULE 11 LANDS HERE TOO, and this function earned it the hard way: reading
    first and folding every ``OSError`` into "keep looking" HANGS THE RUN on a
    FIFO. Measured, bounded at 5s: a FIFO at ``evidence/T1.md`` under the run
    directory left ``resolve_evidence`` blocked in ``open`` with no writer ever
    coming, holding whatever lock the caller holds, with no diagnostic and no
    timeout. ``is_file()`` is false for a FIFO, so the brief's
    ``is_file()``-then-read merely SKIPPED it; a bare read is worse than the
    brief. ``_require_regular_file`` is the door -- ``stat`` on a FIFO returns
    immediately, only ``open`` waits -- and a directory, a dangling link, a
    symlink loop and a FIFO are corruption here exactly as they are everywhere
    else in this module, never an absent record.

    AND UNREADABLE IS NOT ABSENT EITHER, which the door alone does NOT fix:
    ``is_file()`` is TRUE for a mode-``000`` regular file, because ``stat``
    needs ``+x`` on the parent and not ``+r`` on the file. Measured against the
    undifferentiated ``except OSError: continue``: a valid repository copy and
    an UNREADABLE run copy resolved silently to the repository copy -- which
    defeats the precedence rule the paragraph above argues for, by making the
    run copy unreadable instead of mismatching. So the residual ``OSError`` is
    SPLIT. ``FileNotFoundError`` and ``NotADirectoryError`` are the name not
    being there -- the ordinary "the run has no copy" case, and the loser of
    the time-of-check/time-of-use race the door opens -- and they keep looking.
    Every other ``OSError`` is a name that is there and cannot be read, and it
    stops, inside the family, naming the root it stopped under.

    THE DECODE IS WRAPPED for the same family reason. A file whose digest
    matches and whose bytes are not UTF-8 raises ``UnicodeDecodeError``, which
    is a ``ValueError``; the brief decoded it bare.

    THE DOOR'S OWN ``OSError`` IS NOT HANDLED HERE, and the absence of a second
    ``except`` on that call is deliberate rather than an omission.
    ``_require_regular_file`` used to let ``is_file()``'s residual ``OSError``
    -- ``ENAMETOOLONG`` on a 312-character reference, ``EACCES`` under a
    mode-``000`` parent -- straight out through this ``except QuorumError``,
    and both left the family. The split that closes it is inside the door,
    where its other five call sites inherit it too; catching ``OSError`` here
    would have fixed this function and left ``_plan_text`` and the three quorum
    readers holding the same hole.

    THREE OUTCOMES, AND THE ABSENT ONE HAS ITS OWN CLASS. ``EvidenceMissing``
    is raised only by the fall-off below -- nothing under either root. Every
    corruption (a name that cannot be read, a digest mismatch, bytes that are
    not UTF-8) stays a plain ``TrackerValidationError``, so a caller branches
    on a class rather than on a substring of a sentence.
    """
    relative, digest = _digest_reference(reference, field="evidence reference")
    roots = (_openable_path(run_dir, field="run_dir"),
             _openable_path(repo_dir, field="repo_dir"))
    for root in roots:
        candidate = root / relative
        try:
            _require_regular_file(candidate, "an evidence record")
        except QuorumError as exc:
            raise TrackerValidationError(
                f"evidence {reference!r} names {relative!r} under {str(root)!r}, "
                f"which this run cannot read ({exc}). Corruption is never "
                "absence, so it stops here rather than falling through to the "
                "other search root") from exc
        try:
            content = candidate.read_bytes()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            raise TrackerValidationError(
                f"evidence {reference!r} names {relative!r} under {str(root)!r}, "
                f"which is a regular file this run cannot read ({exc}). An "
                "unreadable copy is corruption, never absence: treating it as "
                "absence lets whoever can make the run copy unreadable choose "
                "the repository copy in its place") from exc
        if hashlib.sha256(content).hexdigest() != digest:
            raise TrackerValidationError(
                f"evidence digest does not match its content: {reference!r} "
                f"resolved to {relative!r} under {str(root)!r}, whose sha256 "
                "is something else. A reference names one document, so a "
                "mismatch stops here rather than looking for a copy that "
                "happens to hash right")
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TrackerValidationError(
                f"evidence {reference!r} matches its digest and is not UTF-8 "
                f"({exc}); a record this module cannot read is not a record it "
                "can have checked") from exc
        return parse_verification_evidence(decoded)
    raise EvidenceMissing(
        f"evidence is missing: {reference!r} names {relative!r}, which is not "
        "there under the run directory or under the repository root. A "
        "reference nothing resolves is a PASS nobody can inspect")


# ---------------------------------------------------------------------------
# P04 Task 6: tracker accessors, ref resolution, and the slot cap -- F1, F2.
#
# THREE NAMES THIS BLOCK'S BRIEF LISTED AS PRODUCTS ALREADY EXISTED, and a
# module-level redefinition rebinds the global for every existing caller.
# ``_field`` is P02's header-to-key map, read wherever a section's columns are;
# the brief re-declared it with a second parameter, which would have moved all
# of them at once. ``_csv`` is P02's cell reader, and the brief's version folded
# ``-`` and ``""`` together -- two values ``_cell_list`` keeps apart on purpose.
# ``_attempt_token`` is Task 4's single conversion point, with the nine-digit
# spelling ceiling the brief's version lacks. All three are CONSUMED here.
# ---------------------------------------------------------------------------

#: P02's ``_field`` under the name this block reads it by. AN ALIAS, NEVER A
#: SECOND COPY: ``parse_tracker``, ``render_tracker``, ``SECTIONS`` and
#: ``append_row`` all key rows through that one function, so a reimplementation
#: here would be a second answer to "what is this column called" -- correct on
#: the day it was written and free to drift from the spelling the tracker is
#: actually stored in afterwards.
#:
#: It is IDEMPOTENT over its own output, which is what lets a caller apply it to
#: ``section_columns(...)`` -- already keys, not display headers -- without
#: knowing which of the two it was handed.
_key = _field


def _run_field(tracker: dict, field: str) -> str:
    """One ``## Run`` cell, or a stop inside this module's exception family.

    ``tracker["run"][field]`` raises ``KeyError`` on a tracker with no run
    section and ``TypeError`` on one whose run section is a list -- both
    outside ``TrackerError``, so both escape every handler a controller has
    written and kill the run rather than stopping it.
    """
    try:
        return tracker["run"][field]
    except (KeyError, TypeError, IndexError) as exc:
        raise TrackerValidationError(
            f"tracker run field is missing or unreadable: {field}") from exc


def _task_row(tracker: dict, task_id) -> dict:
    """The one ``## Tasks`` row with this id. THE ROW ITSELF, not a copy.

    ``_validate_tasks`` refuses a duplicate id, so "the row" is well defined;
    an unknown id is a stop rather than ``None``, because every caller below
    would otherwise index ``None`` one line later and leave the family.
    """
    for row in tracker.get("tasks", ()) or ():
        if row["id"] == task_id:
            return row
    raise TrackerValidationError(f"unknown task: {task_id!r}")


def _replace_task(tracker: dict, replacement: dict) -> dict:
    """Swap one task row for an edited copy, IN PLACE IN THE ORDER IT HAD.

    A replacement matching no row RAISES rather than appending or silently
    doing nothing: the caller's edit would otherwise be lost while the
    transition it belongs to reported itself applied, which is the one failure
    a durable transition may never have.
    """
    target = replacement["id"]
    rows = tracker.get("tasks", ()) or ()
    if not any(row["id"] == target for row in rows):
        raise TrackerValidationError(
            f"cannot replace task {target!r}: no row carries that id, and an "
            "edit applied to nothing is a transition that reports itself done")
    tracker["tasks"] = [
        replacement if row["id"] == target else row for row in rows
    ]
    return tracker


def _quorum_owners(tracker: dict) -> set:
    """Owners held by an IN-FLIGHT quorum.

    P04 reads ``QID``, ``State`` and ``Owners`` and writes nothing here:
    ``## Quorum`` belongs entirely to P03. A finalized row holds no slots --
    its brains have answered and been released -- so folding the two states
    together would make every past quorum permanently occupy the capacity the
    next one needs.

    The ``-``/empty filter is over MEMBERS, not over the cell: ``_csv`` already
    answers ``()`` for a whole cell spelled ``-``, but ``a,-,b`` and ``a,,b``
    are multi-valued cells with a placeholder inside them, and those are the
    spellings that would otherwise enter the set as owner names.
    """
    owners: set = set()
    for row in tracker.get("quorum", ()) or ():
        if row["state"] != _IN_FLIGHT:
            continue
        owners.update(value for value in _csv(row["owners"])
                      if value and value != _ABSENT_CELL)
    return owners


def _append_history(value: str, entry: str) -> str:
    """Append one entry to a comma-separated history cell.

    ``-`` is the empty marker, so appending to it REPLACES it; appending beside
    it would leave a cell whose first member is the absence sentinel, which
    ``_csv`` reads back as a nameless checkpoint.

    BOTH BRANCHES ARE LIVE, AND THE EQUIVALENCE IS STATED OVER THE DOMAIN
    RATHER THAN OVER ONE CALLER. An earlier justification argued the appending
    branch never runs -- "``reserve_task`` only runs on a ``[ ]`` row whose
    ``checkpoints`` cell is ``-``, so this is the identity" -- which is an
    argument about ONE of the two call sites. ``import_phase_plan`` is the
    other, and there the entry branch is the live one: the first import sets
    ``phase_plans`` from ``-`` to a path, and every import after it appends
    beside a real path
    (``test_a_second_phase_appends_and_stays_index_aligned``). A totality claim
    derives its case list from the call tree, not from one fixture -- and an
    equivalence claim is a totality claim about the inputs that reach it.

    So the rule is the function's own: two inputs mean "nothing recorded yet"
    and are REPLACED; anything else is EXTENDED. Which caller lands in which
    branch is a consequence, never the premise.
    """
    return entry if value in ("", _ABSENT_CELL) else f"{value},{entry}"


# ---------------------------------------------------------------------------
# P04 Task 6: capacity arithmetic -- fault F2.
#
# THREE SLOTS ARE HELD FOR A QUORUM AND THE RESERVE IS NOT A TUNING KNOB.
# Reserving up to ``worker_limit`` deadlocks the run PERMANENTLY: a blocked task
# holds the slot needed to dispatch the brains that would unblock it, and there
# is no timeout, no retry and no state anyone can reach that frees it. Nothing
# in superb:pipeline covers this, because superb:pipeline has no brains.
# ---------------------------------------------------------------------------

QUORUM_SLOT_RESERVE = 3

#: A blocked ``[?]`` task STILL OCCUPIES ITS IMPLEMENTATION SLOT. The worker
#: holding it has not been released -- it is waiting on the answer -- which is
#: the whole reason the three slots above are held back in the first place.
#: ``[x]`` and ``[ ]`` are deliberately absent: a finished task's worker is
#: free, and an unstarted task never had one.
_OCCUPYING_STATES = ("[~]", "[?]")


def implementation_slot_cap(worker_limit) -> int:
    """How many slots implementation tasks may occupy at once.

    THE FLOOR IS ONE, NOT ZERO. Below ``worker_limit = 4`` the subtraction goes
    non-positive and a cap of zero would stop the run rather than slow it: with
    the floor, tasks serialise and the three brain slots stay free, which is the
    degraded mode the constraint intends.

    ``bool`` is excluded BY TYPE and first, for ``initialize_run``'s reason:
    ``isinstance(True, int)`` is true and ``True - 3`` is ``-2``, so a bare
    ``isinstance`` admits a cap computed from a flag.
    """
    if (isinstance(worker_limit, bool) or not isinstance(worker_limit, int)
            or worker_limit < 1):
        raise TrackerValidationError(
            f"worker_limit {worker_limit!r} is not a positive integer; the "
            "implementation cap is derived from it and a cap derived from a "
            "string, a float or a flag is a capacity nobody granted")
    return max(1, worker_limit - QUORUM_SLOT_RESERVE)


def _implementation_owners(tracker: dict) -> set:
    return {
        row["owner"] for row in tracker.get("tasks", ()) or ()
        if _member(row["state"], _OCCUPYING_STATES)
        and row["owner"] != _ABSENT_CELL
    }


def _active_owners(tracker: dict) -> set:
    """Every worker this run is currently holding, of either kind."""
    return _implementation_owners(tracker) | _quorum_owners(tracker)


# ---------------------------------------------------------------------------
# P04 Task 6: reading a git reference WITHOUT running git.
#
# The brief named ``_git`` and ``_git_out`` as ``subprocess.run`` wrappers.
# ``subprocess`` IS NOT IN ``ALLOWED_IMPORTS`` and the master plan refuses it by
# name -- "arbitrary command execution, the single capability this boundary most
# exists to withhold". So the ref store is read directly, the same translation
# every ``re.compile`` screen in these plans gets and for the same reason.
#
# THE REPOSITORY ROOT IS THE ONE RECORDED AT INIT. It is never derived from
# ``run_dir`` depth: a run directory nested at an unexpected depth would
# otherwise bind the run to the wrong repository, silently.
# ---------------------------------------------------------------------------

_GIT_DIRNAME = ".git"
#: ``.git`` is a FILE holding this prefix in a linked worktree -- which is the
#: whole integration topology of this phase, one worktree per concurrently
#: dispatched implementer, so a resolver that required a directory would refuse
#: every repository this run actually creates.
_GITDIR_PREFIX = "gitdir: "
_COMMONDIR_FILE = "commondir"

#: What `git`'s own `is_git_directory()` requires before it will call a
#: directory a repository: a readable `HEAD`, an `objects` directory and a
#: `refs` directory. Spelled here because this module answers the same
#: question and must not answer it more weakly -- see `_git_store`.
_HEAD_FILE = "HEAD"
_OBJECTS_DIRNAME = "objects"
_REFS_DIRNAME = "refs"
_PACKED_REFS_FILE = "packed-refs"
_SYMREF_PREFIX = "ref: "
_PEEL_PREFIX = "^"
_COMMENT_PREFIX = "#"
#: A symbolic ref may point at another symbolic ref. The chain is bounded so a
#: cycle is a diagnostic rather than a hang; git's own limit is 5.
_SYMREF_LIMIT = 8
#: The five names git will look for directly under ``$GIT_DIR``. Every other
#: unqualified name is searched through the namespaces below, in gitrevisions'
#: order -- which is why ``refs/heads/`` precedes ``refs/remotes/`` here: a
#: resolver that reversed them would review a stale fetched tip and say nothing.
_PSEUDO_REFS = ("HEAD", "FETCH_HEAD", "ORIG_HEAD", "MERGE_HEAD",
                "CHERRY_PICK_HEAD")
_REF_NAMESPACES = ("refs/", "refs/tags/", "refs/heads/", "refs/remotes/")


def _repo_dir(tracker: dict) -> Path:
    """The recorded repository root as a path, resolved once."""
    root = repo_root(tracker)
    try:
        return Path(root).resolve()
    except (OSError, RuntimeError) as exc:
        #: ``resolve`` raises ``RuntimeError`` on a symlink loop even with
        #: ``strict=False``, and ``RuntimeError`` is not a ``TrackerError``.
        raise TrackerValidationError(
            f"the recorded repository root {root!r} cannot be resolved "
            f"({type(exc).__name__}: {exc})") from exc


def _ref_name(value) -> str:
    """One git reference name, screened before any of it reaches a path.

    ``_TOKEN`` -- which is all ``target_branch`` is held to -- ADMITS ``/``,
    so ``a/../../../../etc/passwd`` is a perfectly legal tracker cell and would
    otherwise be joined straight onto the ref store. The segments are asked RAW
    for ``_safe_relative``'s reason: pathlib normalises ``.`` and an empty
    segment away before any check over ``.parts`` could see them.

    The segment rules are ``_safe_relative``'s PLUS GIT'S HIDDEN-COMPONENT
    RULE, which is strictly stronger and was previously written here as an
    identity. ``.hidden``, ``a/.h/b``, ``..weird`` and ``...`` are all accepted
    by ``_safe_relative`` and refused here, matching ``git check-ref-format``;
    stronger is the safe direction for a value that becomes a path.

    ``"."`` AND ``".."`` ARE NOT IN THE TUPLE, and their absence is the point.
    Both start with ``.``, so ``startswith(".")`` on the line below refuses
    them; listing them as well was two checks refusing the same input, and a
    mutant deleting ``".."`` from the tuple survived the whole suite because
    nothing could tell the difference. This is the ``_table_safe``-on-
    ``purpose`` case and NOT ``_require_regular_file``'s absence arm: the
    domination is between two clauses of ONE condition in THIS file, permanent
    and unable to move, where the absence arm is dominated by a relation
    between two things in the standard library, either of which can. So this
    one is deleted and that one is kept. ``""`` is what remains load-bearing:
    an empty segment starts with nothing.
    """
    if not isinstance(value, str) or not value or not _cell_safe(value):
        raise TrackerValidationError(
            f"unusable git reference {value!r}: it must be a nonempty string a "
            "tracker cell can carry back out unchanged")
    for segment in value.split("/"):
        if (segment == "" or segment != segment.strip()
                or segment.startswith(".")):
            raise TrackerValidationError(
                f"unusable git reference {value!r}: the segment {segment!r} is "
                "empty, a traversal, whitespace-padded or hidden, and a "
                "reference that walks out of the ref store names a file rather "
                "than a commit")
    return value


def _ref_text(path: Path, what: str, *, namespace_ok: bool = True):
    """The contents of one ref-store file, ``None`` if no ref file is there.

    ``is_file()`` NEVER MEANS "there is nothing here": it is false for a
    directory, a dangling symlink, a symlink loop and a FIFO, and a FIFO opened
    for reading BLOCKS until a writer arrives -- under the run lock, with no
    writer coming. ``_require_regular_file`` is this module's door for that and
    is used rather than re-written; it raises inside the quorum family, so the
    wrap is what keeps a ref-store fault reading as a tracker fault.

    A DIRECTORY IS THE ONE EXCEPTION, AND IT IS NOT A WEAKENING OF THAT RULE.
    A ref namespace IS a directory: ``refs/tags/`` exists precisely because
    ``refs/tags/v1`` does, and ``refs/remotes/origin/`` because
    ``refs/remotes/origin/HEAD`` does. So a directory at a candidate is not
    corruption at all -- it is the ordinary shape of a name that has children
    and no value of its own, and git walks straight past it to the next
    candidate. Refusing it aborted the whole search at the FIRST such name:
    with a plain branch ``target`` and an unrelated tag ``target/rc1``, the
    directory ``refs/tags/target/`` sits EARLIER in gitrevisions' order than
    the ``refs/heads/target`` the run wants, and the run died on a repository
    ``git rev-parse`` answers without complaint. It also made the
    ``refs/remotes/<name>/HEAD`` candidate this function's own caller appends
    unreachable by construction: that candidate can only ever be reached
    THROUGH the directory ``refs/remotes/<name>/``.

    ``namespace_ok=False`` IS THE EXEMPTION WITHDRAWN WHERE ITS JUSTIFICATION
    DOES NOT EXIST, and it is not a second opinion about directories. The
    whole argument above is "look further" -- the exemption's entire content
    is that there is a NEXT candidate to look at. For a pseudo-ref there is
    not: ``_ref_candidates`` returns a ONE-element tuple for every name in
    ``_PSEUDO_REFS``, and ``$GIT_DIR/MERGE_HEAD/`` is never a ref namespace
    because no name is ever spelled beneath it. So for those callers a
    directory carries no information about a further candidate and falls back
    into the sentence the other four are refused by. Withdrawing it there
    cannot regress the ``refs/tags/target/`` case it was written for, because
    that case is reached only through a multi-candidate name.

    THE OTHER FOUR STILL RAISE, and the difference is that none of them is a
    shape the ref store legitimately has. A directory means "look further"; a
    FIFO, a dangling link, a symlink loop and a name this process cannot read
    mean "something is here and this run cannot establish what", which is the
    one answer that must never be folded into absence. Git is more forgiving
    than this -- measured, it ignores a broken loose ref with a warning and
    carries on -- and the divergence is deliberate in the strict direction: a
    baseline is one end of a range proof, and guessing past a ref store this
    run cannot read is how a proof acquires an end nobody checked.
    """
    is_directory = False
    try:
        #: Asked BEFORE the door, because the door's answer for a directory is
        #: "corruption" and here it is "keep looking". ``is_dir()`` raises for
        #: exactly the errnos ``is_file()`` raises for, and those are the
        #: door's business rather than this branch's -- so they fall through
        #: to it and are reported there, once, in the door's own words.
        is_directory = path.is_dir()
    except OSError:
        pass
    if is_directory:
        if namespace_ok:
            return None
        raise TrackerValidationError(
            f"{what} at {str(path)!r} is a directory at a name that has no "
            "namespace beneath it; a pseudo-ref has exactly one candidate and "
            "nothing further to look at, so this is a corrupt store and never "
            "an absent reference")
    try:
        _require_regular_file(path, what)
    except QuorumError as exc:
        raise TrackerValidationError(
            f"{what} at {str(path)!r} is a name this run cannot read ({exc}); "
            "a dangling link, a symlink loop, a FIFO or a name this process "
            "cannot examine is corruption and never an absent reference. A "
            "DIRECTORY never reaches here: where a next candidate exists a ref "
            "namespace is a directory, so it reads as absence and the search "
            "moves on, and where one does not it is refused above") from exc
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, ValueError) as exc:
        #: ``ValueError`` RATHER THAN ``UnicodeError``, WHICH IT CONTAINS. A
        #: NUL byte anywhere in a path is ``ValueError: embedded null byte``
        #: from the ``open`` wrapper and is NOT an ``OSError``, so it escaped
        #: this module's exception family altogether -- and the two shapes
        #: above CANNOT catch it for us: ``pathlib``'s ``is_dir``/``is_file``
        #: both swallow ``ValueError`` and answer ``False``, so a NUL path
        #: reads as plain absence right up to the read that raises. Measured,
        #: and reachable twice over with input THE WORKER CONTROLS: the
        #: repository root this proof is taken over, and the ``.git`` /
        #: ``commondir`` pointer payloads inside it, which are files in a
        #: repository the worker writes. An unhandled ``ValueError`` under the
        #: run lock kills an unattended run; refusing the name does not.
        raise TrackerValidationError(
            f"unreadable {what} at {str(path)!r}: {type(exc).__name__}: "
            f"{exc}") from exc


def _git_store(repo) -> tuple:
    """``(gitdir, commondir)`` for one checkout.

    They differ in a linked worktree: per-worktree state (``HEAD``) lives in
    ``gitdir`` and the shared refs live in ``commondir``, so a resolver that
    knew only one of the two would read either the wrong ``HEAD`` or no
    branches at all.

    "IS A GIT REPOSITORY" IS ASKED THE WAY GIT ASKS IT, and it used to be
    asked far more weakly. The only question here was ``(<repo>/.git).is_dir()``
    -- so the WEAKEST artifact that yielded a complete ``attested`` proof was a
    directory containing exactly ONE FILE, ``.git/refs/heads/<ref>`` holding
    forty hex characters. No objects, no ``HEAD``, no ``config``. Measured:
    ``git -C`` on that directory says ``fatal: not a git repository``, and so
    does the argv this module emits for it, while the module produced a full
    proof. A docstring that Tasks 10 and 11 read as a specification promised
    "a directory this process can read as a git repository" and delivered "a
    directory with a ref file in it".

    So the three things ``git``'s own ``is_git_directory()`` requires are
    required here: a readable ``HEAD``, an ``objects`` directory and a
    ``refs`` directory. ``HEAD`` is per-worktree and is asked of ``gitdir``;
    ``objects`` and ``refs`` are shared and are asked of the COMMONDIR, which
    is why they are checked after it is resolved rather than before -- in a
    linked worktree ``gitdir`` carries neither. ``HEAD`` goes through
    ``_ref_text`` and therefore through ``_require_regular_file``: a FIFO at
    ``HEAD`` would otherwise block forever under the run lock. Its CONTENT is
    deliberately not parsed -- an unborn branch, a detached HEAD and a symref
    are all ordinary, and this function's job is "is this a repository", not
    "what is checked out".
    """
    root = Path(repo)
    pointer = root / _GIT_DIRNAME
    try:
        is_directory = pointer.is_dir()
    except OSError as exc:
        raise TrackerValidationError(
            f"the repository at {str(root)!r} cannot be examined "
            f"({type(exc).__name__}: {exc})") from exc
    if is_directory:
        gitdir = pointer
    else:
        text = _ref_text(pointer, "the .git pointer")
        if text is None or not text.startswith(_GITDIR_PREFIX):
            raise TrackerValidationError(
                f"{str(root)!r} is not a git repository: it carries no {_GIT_DIRNAME} "
                "directory and no gitdir pointer, so no reference in it resolves")
        gitdir = _relative_to(root, text[len(_GITDIR_PREFIX):].strip())
    common = _ref_text(gitdir / _COMMONDIR_FILE, "the git commondir pointer")
    common = gitdir if common is None else _relative_to(gitdir, common.strip())
    if _ref_text(gitdir / _HEAD_FILE, "the git HEAD file") is None:
        raise TrackerValidationError(
            f"{str(root)!r} is not a git repository: {str(gitdir)!r} carries no "
            f"readable {_HEAD_FILE}, and a ref file on its own is not a "
            "repository -- `git -C` refuses such a directory and so does the "
            "command this module emits for it")
    for required in (_OBJECTS_DIRNAME, _REFS_DIRNAME):
        candidate = common / required
        try:
            present = candidate.is_dir()
        except OSError as exc:
            raise TrackerValidationError(
                f"the repository at {str(root)!r} cannot be examined "
                f"({type(exc).__name__}: {exc})") from exc
        if not present:
            raise TrackerValidationError(
                f"{str(root)!r} is not a git repository: {str(common)!r} "
                f"carries no {required}/ directory, which is one of the three "
                "things git's own `is_git_directory` requires before it will "
                "read a reference out of a directory")
    return gitdir, common


def _relative_to(base: Path, value: str) -> Path:
    """One git pointer file's payload, which may be absolute or base-relative."""
    if not value:
        raise TrackerValidationError(
            f"an empty git directory pointer under {str(base)!r} names nothing")
    pointed = Path(value)
    return pointed if pointed.is_absolute() else base / pointed


def _ref_candidates(name: str) -> tuple:
    """The ordered names git would try for one reference."""
    if name.startswith(_REF_NAMESPACES[0]) or name in _PSEUDO_REFS:
        return (name,)
    return tuple(f"{space}{name}" for space in _REF_NAMESPACES) + (
        f"{_REF_NAMESPACES[3]}{name}/HEAD",)


def _packed_ref(common: Path, name: str):
    """One entry from ``packed-refs``, PEELED where the file peeled it.

    ``git pack-refs`` DELETES the loose file, so a resolver that read only
    ``refs/heads/<name>`` would report an entirely ordinary repository as having
    no target branch. An annotated tag's line is followed by a ``^<sha>`` line
    carrying the commit it points at, which is what ``<ref>^{commit}`` means.
    """
    text = _ref_text(common / _PACKED_REFS_FILE, "the git packed-refs file")
    if text is None:
        return None
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line or line.startswith((_COMMENT_PREFIX, _PEEL_PREFIX)):
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2 or parts[1].strip() != name:
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if following.startswith(_PEEL_PREFIX):
            return following[len(_PEEL_PREFIX):].strip()
        return parts[0].strip()
    return None


def _lookup_ref(gitdir: Path, common: Path, name: str):
    """The raw contents of the first ref file that answers to ``name``.

    LOOSE BEFORE PACKED FOR EACH CANDIDATE, AND NEVER LOOSE-FOR-ALL BEFORE
    PACKED-FOR-ALL. The candidate order is gitrevisions' -- ``refs/tags/``
    precedes ``refs/heads/`` -- and storage is NOT a tiebreak between two
    candidates, only between two spellings of the SAME one. So on a store
    carrying a packed ``refs/tags/x`` and a loose ``refs/heads/x``, the tag is
    reached at the earlier candidate and WINS, which is what ``git rev-parse x``
    answers on that same store.

    An earlier revision of this docstring had both halves backwards -- it
    claimed the loose head wins and that the swap would resolve the tag, when
    it is the swap that resolves the head. Hoisting the packed lookup into a
    second loop would scan every candidate loose first, find ``refs/heads/x``
    before any packed entry, and resolve the HEAD: a silent disagreement with
    ``git rev-parse`` on an ordinary repository, and the nesting this function
    exists to refuse.

    AN EMPTY LOOSE FILE IS A BROKEN REF, NOT AN ABSENT ONE, and the difference
    is which of the two lookups below it cancels. Measured against real
    ``git rev-parse`` rather than read off the source: with an empty
    ``refs/heads/target`` AND a packed ``refs/heads/target``, git says
    ``warning: ignoring broken ref refs/heads/target`` and FAILS -- the loose
    file shadows the packed entry even though it carries nothing. It does not
    end the whole search, though: with an empty ``refs/tags/target`` and a
    valid loose ``refs/heads/target``, git warns and answers the head. So
    emptiness cancels THIS CANDIDATE'S packed fallback and nothing else, which
    is what ``broken`` carries past the store loop. Treating it as plain
    absence -- the previous behaviour -- resolved a repository ``git rev-parse``
    refuses, which is the worse direction of the two: the run would proceed on
    a baseline git itself will not name.

    ``packed-refs`` IS READ FROM ``common``, NEVER FROM ``gitdir``. ``git
    pack-refs`` writes ONE file, in the common directory, shared by every
    linked worktree; a linked worktree's own ``gitdir`` has no ``packed-refs``
    at all. Reading it from ``gitdir`` loses every packed ref in every linked
    worktree at once -- an ordinary repository, since packing is what git does
    on its own during ``gc``.

    ONE DIVERGENCE FROM GIT IS KNOWN AND KEPT: a loose file AT a candidate that
    is also a directory PREFIX of a later candidate in ``packed-refs`` -- an
    empty ``refs/remotes/x`` with a packed ``refs/remotes/x/HEAD`` -- is a
    directory/file conflict git resolves by refusing both, and this resolver
    answers the packed entry. It is a ref store git itself calls corrupt, and
    naming it here is cheaper than a second conflict model.
    """
    for candidate in _ref_candidates(name):
        broken = False
        for store in (gitdir, common):
            text = _ref_text(store / candidate, f"the git ref {candidate!r}")
            if text is None:
                continue
            if text.strip():
                return text.strip()
            broken = True
        if broken:
            continue
        packed = _packed_ref(common, candidate)
        if packed is not None:
            return packed
    return None


def _resolved_commit(repo, ref: str) -> str:
    """One reference, resolved to the single 40-character commit it names.

    THE ANSWER IS AN OBJECT NAME OR IT IS A STOP. A symbolic name resolves
    somewhere else tomorrow, and every range proof this run makes has this value
    as one of its ends, so anything that does not come back as a full object
    name is refused rather than recorded.

    THE STORE IS OPENED BEFORE THE OBJECT-NAME SHORT-CIRCUIT, NOT AFTER IT, and
    that order is a fix rather than a preference. The short-circuit sat first,
    so a ref that was ALREADY forty hex characters answered itself and this
    function touched nothing: no ``.git``, no pointer file, no ref store. Every
    end of the production range proof is forty hex characters -- the
    reservation baseline is one by construction and a worker's ``source_ref``
    is schema-bound to be one -- so BOTH ends short-circuited, and a complete
    `attested` proof was obtainable over a directory that is not a repository
    and commits that do not exist (measured, before this change). Reading the
    store first does not make the module able to check that an object name
    EXISTS -- no object is ever decompressed here, ``zlib`` is off the import
    list -- but it does make every answer this function gives conditional on
    ``repo`` being a repository this process can read, which is the fact the
    ``-C <repo>`` pinning in the emitted command rests on.
    """
    name = _ref_name(ref)
    gitdir, common = _git_store(repo)
    if _COMMIT.fullmatch(name):
        return name
    seen = [name]
    for _ in range(_SYMREF_LIMIT):
        value = _lookup_ref(gitdir, common, name)
        if value is None:
            raise TrackerValidationError(
                f"reference {ref!r} names no reference in the repository at "
                f"{str(repo)!r}; a baseline that cannot be resolved is one end "
                "of a range proof that has no end")
        if value.startswith(_SYMREF_PREFIX):
            name = _ref_name(value[len(_SYMREF_PREFIX):].strip())
            if name in seen:
                raise TrackerValidationError(
                    f"reference {ref!r} is a symbolic-ref cycle through "
                    f"{name!r}; following it is a hang rather than an answer")
            seen.append(name)
            continue
        if not _COMMIT.fullmatch(value):
            raise TrackerValidationError(
                f"reference {ref!r} resolves to {value!r}, which is not one "
                "40-character object name")
        return value
    raise TrackerValidationError(
        f"reference {ref!r} is a symbolic-ref chain deeper than "
        f"{_SYMREF_LIMIT}; a baseline nobody can reach is not a baseline")


# ---------------------------------------------------------------------------
# P04 Task 6: the approved task definition.
#
# THE PLAN IS THE AUTHORITY AND THE ROW IS A MIRROR OF IT. There is no ``Deps``
# column: dependencies live in the phase-plan metadata and nowhere else, so a
# row that carried its own copy would be a second, divergable source of truth.
# Only ``Kind`` is cross-checked, because ``Kind`` is what decides whether a
# reservation persists a baseline at all.
# ---------------------------------------------------------------------------

def _phase_plan_path(tracker: dict, phase_id) -> Path:
    """The approved phase plan for one phase, as an absolute path.

    ``phase_plans`` and ``## Phases`` are written in ONE transition by
    ``import_phase_plan``, in the same order, which is what makes "the entry at
    that phase's index" a fact rather than a convention. The length check is
    what notices if that ever stops being true.
    """
    paths = _csv(_run_field(tracker, "phase_plans"))
    phase_ids = [row["id"] for row in tracker.get("phases", ()) or ()]
    if len(paths) != len(phase_ids) or not _member(phase_id, phase_ids):
        raise TrackerValidationError(
            f"phase {phase_id!r} does not resolve to exactly one approved "
            f"phase plan: {len(phase_ids)} phase rows against {len(paths)} "
            "recorded plan paths")
    try:
        relative = _safe_relative(paths[phase_ids.index(phase_id)])
    except PlanMetadataError as exc:
        raise TrackerValidationError(
            f"the recorded phase plan for {phase_id!r} is not a usable "
            f"repository-relative path ({exc})") from exc
    return _repo_dir(tracker) / relative


def _approved_definition(tracker: dict, task_id: str) -> dict:
    """The phase plan's definition of one task row.

    The brief's signature took ``run_dir`` as well. Nothing here reads it: the
    plan is found through the RECORDED repository root and the recorded
    ``phase_plans`` cell, which is exactly the property the run-dir-depth rule
    exists to protect, and an argument no body reads is an argument a caller
    can get wrong for free.
    """
    row = _task_row(tracker, task_id)
    plan = _phase_plan_path(tracker, row["phase"])
    definition = next(
        (task for task in parse_plan_metadata(plan)["tasks"]
         if task["id"] == task_id), None)
    if definition is None:
        raise TrackerValidationError(
            f"task {task_id!r} is not defined by the approved phase plan at "
            f"{str(plan)!r}; a task the plan does not name is work nobody "
            "approved a write scope for")
    if row["kind"] != definition["kind"]:
        raise TrackerValidationError(
            f"task {task_id!r} records kind {row['kind']!r} and the approved "
            f"plan declares {definition['kind']!r}; the plan is the authority, "
            "and the kind is what decides whether a reservation persists the "
            "baseline every range proof needs")
    return definition


# ---------------------------------------------------------------------------
# P04 Task 6: importing one approved phase plan.
#
# ``initialize_run`` writes the ``## Run`` artifact references and an EMPTY
# ``## Tasks``, and leaves ``phase_plans`` at ``-`` because stage 07 is what
# discovers a phase plan. Appending the rows is P04's, because the row set is a
# projection of the phase-plan metadata grammar and of nothing else.
# ---------------------------------------------------------------------------

def import_phase_plan(run_dir, *, phase_plan) -> dict:
    """Append one approved phase plan's phase row, task rows and path.

    ALL THREE IN ONE TRANSITION. ``_phase_plan_path`` reads the ``phase_plans``
    entry at the phase's own index, so a design that recorded the path in a
    second transition would have a window in which the two lists disagree --
    and the tracker would resolve one phase's tasks against another's plan.

    A SECOND IMPORT OF A PHASE RAISES; an immediate re-issue of the SAME
    transition replays and is inert. The two are different events and P02's
    replay key is what tells them apart: a controller resuming an interrupted
    import must not be told its run is corrupt, and a controller importing a
    phase it already imported must not be told nothing happened.
    """
    #: NORMALISED FIRST, the way every P03 entry point does it. ``validate_run``
    #: deliberately does not coerce -- its first statement is
    #: ``run_dir / "progress.md"`` -- so a ``str`` reaching it raises
    #: ``TypeError``, which is outside ``TrackerError`` and escapes every
    #: handler a controller has written. A ``str`` is the likeliest spelling a
    #: controller holds, and ``None``, an ``int`` and a ``bytes`` are what a
    #: caller that lost the run directory holds; ``_run_path`` answers all four
    #: inside the family.
    run_dir = _run_path(run_dir)
    metadata = parse_plan_metadata(phase_plan)
    phase_id = metadata["phase"]["id"]

    def mutate(tracker: dict) -> dict:
        root = _repo_dir(tracker)
        try:
            relative = Path(phase_plan).resolve().relative_to(root).as_posix()
        except (ValueError, OSError, RuntimeError) as exc:
            raise TrackerValidationError(
                f"the phase plan at {str(phase_plan)!r} is not inside the "
                f"recorded repository root {str(root)!r}, so it has no "
                "repository-relative spelling to record") from exc
        try:
            _safe_relative(relative)
        except PlanMetadataError as exc:
            raise TrackerValidationError(
                f"the phase plan path {relative!r} cannot be held in a tracker "
                f"cell ({exc})") from exc
        if any(row["id"] == phase_id for row in tracker["phases"]):
            raise TrackerValidationError(
                f"phase {phase_id} is already imported; a second import would "
                "give one phase two review classes and its tasks two rows")
        seen = {row["id"] for row in tracker["tasks"]}
        phase = {column: _ABSENT_CELL for column in section_columns("phases")}
        phase.update({
            _key("ID"): phase_id,
            _key("State"): "[ ]",
            _key("Review Class"): metadata["phase"]["review_class"],
            _key("Class Source"): "plan",
        })
        append_row(tracker, "phases", phase)
        for task in metadata["tasks"]:
            if task["id"] in seen:
                raise TrackerValidationError(
                    f"duplicate task id {task['id']!r}: a row in this tracker "
                    "already carries it, so two approved phase plans disagree "
                    "about which phase owns it")
            seen.add(task["id"])
            row = {column: _ABSENT_CELL for column in section_columns("tasks")}
            row.update({
                _key("ID"): task["id"],
                _key("Phase"): phase_id,
                _key("Kind"): task["kind"],
                _key("State"): "[ ]",
                _key("Provisional"): "no",
            })
            append_row(tracker, "tasks", row)
        tracker["run"]["phase_plans"] = _append_history(
            tracker["run"]["phase_plans"], relative)
        return tracker

    return locked_tracker_update(
        run_dir, transition_id=f"import-phase-plan-{phase_id}", mutate=mutate)


# ---------------------------------------------------------------------------
# P04 Task 6: the reservation guards -- faults F1 and F2.
# ---------------------------------------------------------------------------

def _require_dependencies_complete(tracker: dict, definition: dict) -> None:
    for dependency in definition["deps"]:
        if _task_row(tracker, dependency)["state"] != "[x]":
            raise TrackerValidationError(
                f"dependency {dependency} of task {definition['id']} is not "
                "complete; the plan integrates it first, and starting the "
                "dependent now builds on work that may still change")


def _require_no_scope_conflict(tracker: dict, definition: dict) -> None:
    """F1: two tasks whose write scopes intersect are never active together.

    SPARE CAPACITY NEVER OVERRIDES THIS. Capacity is about how many tasks may
    run; this is about which two may not, and under plain equality ``tree:src``
    and ``file:src/a.py`` are different strings, reserve together, and two
    implementers open the same file in two worktrees.
    """
    for row in tracker.get("tasks", ()) or ():
        if (row["id"] == definition["id"]
                or not _member(row["state"], _OCCUPYING_STATES)):
            continue
        other = _approved_definition(tracker, row["id"])
        if _scope_sets_overlap(definition["write_scope"], other["write_scope"]):
            raise TrackerValidationError(
                f"write scope conflict: {definition['id']} "
                f"{list(definition['write_scope'])} overlaps active "
                f"{other['id']} {list(other['write_scope'])}")


def _require_capacity(tracker: dict, owner: str) -> None:
    """F2: three slots stay free for the quorum that unblocks a blocked task.

    TWO BOUNDS, AND THE SECOND IS NOT THE FIRST RESTATED. The cap bounds
    implementation tasks; ``worker_limit`` bounds everyone, brains included.

    THE SECOND CLAUSE SEPARATES FROM THE FIRST IN TWO REGIMES, not one. An
    earlier revision of this docstring named only the second of them and
    derived the exclusion algebraically -- "``i + 1 <= L - 3`` and ``i + 4 > L``
    have no common solution, so one quorum is dominated by the cap". That
    derivation DROPS THE ``max(1, ...)`` FLOOR ``implementation_slot_cap``
    applies, and the floor is the whole point of that function: for
    ``L <= 3`` the cap is ``1``, not ``L - 3``, so ``i = 0`` passes the first
    bound and ONE in-flight quorum's three owners plus the incoming one already
    exceed ``L``.

    The two regimes, taken from a search of the integer space rather than from
    algebra re-derived by hand -- the first derivation read as verified and was
    not:

    * **The floor binds** (``worker_limit`` 1, 2 or 3): cap ``1``, no
      implementation owner yet, one in-flight quorum. Searching every
      ``(L, |impl|, quorum rows, |quorum owners|)`` shape over ``L`` 1..12
      finds the one-quorum regime is EXACTLY ``L in {1, 2, 3}`` with
      ``|impl| == 0`` FOR A CALLER WHO IS NOT ALREADY AN IMPLEMENTATION OWNER.
      That qualifier is not decoration and an earlier revision of this
      sentence ended at "and nothing else", which is false: neither
      ``reserve_task`` nor ``resume_task`` carries a one-task-per-owner guard,
      so an owner already holding a row skips the FIRST clause entirely
      (``owner in owners``) and arrives at the second with ``|impl| == 1``.
      At ``L == 3`` with one quorum in flight that is ``|{owner} u 3 brains|
      == 4 > 3`` and the second clause is what refuses it. The headline regime
      is unaffected -- it is about which clause binds a NEW owner -- but the
      second clause's reachable inputs are not only the ones listed above.
    * **Above the floor**, two in-flight quorums -- six brain owners against a
      cap computed from three.

    The first regime is a real degraded mode and not the F2 deadlock: at
    ``L <= 3`` every reservation is refused WHILE a quorum is in flight, and
    the quorum finalises and releases its owners without needing a slot it
    cannot have. It is temporary by construction, which is exactly what
    separates it from the permanent deadlock reserving past the cap creates.
    """
    limit = int(_run_field(tracker, "worker_limit"))
    cap = implementation_slot_cap(limit)
    owners = _implementation_owners(tracker)
    if owner not in owners and len(owners) + 1 > cap:
        raise TrackerValidationError(
            f"implementation slots exhausted: {len(owners)} of {cap} in use "
            f"(worker_limit {limit} minus {QUORUM_SLOT_RESERVE} held for a "
            "quorum). Reserving past the cap deadlocks the run permanently: a "
            "blocked task holds the slot the brains that would unblock it need")
    if len(_active_owners(tracker) | {owner}) > limit:
        raise TrackerValidationError(
            f"global worker_limit {limit} is exhausted, counting the owners an "
            "in-flight quorum holds as well as the implementation tasks")


def _validate_assignment(task_id, owner, attempt) -> str:
    """The three identity arguments, screened before the lock is ever taken.

    IT RETURNS THE ATTEMPT TOKEN rather than checking the attempt and leaving
    the caller to convert it. The two spellings were written side by side and
    the screen was then DOMINATED by the conversion one line below it -- a
    mutant deleting it changed nothing, because ``_attempt_token`` is total and
    raising and the caller needed its result anyway. Returning the value is what
    makes the single conversion point a single CALL.

    ``_OWNER`` rather than ``_TOKEN``: the owner grammar is already pinned --
    P03 writes owner ids into response FILENAMES, and the 64-character bound and
    the trailing-dot rule are about exactly that. Re-deriving it from ``_TOKEN``
    here would admit ``/``, ``:``, ``@`` and ``+`` into a name that becomes a
    path, and a trailing dot into one that becomes a filename.

    AND THAT ARGUMENT APPLIES TO BOTH ID ARGUMENTS, which is the defect this
    function shipped with: it stated the rule and then applied it to only one
    of them. A task id becomes a DIRECTORY under ``agent-output/`` and a
    BRANCH NAME, so ``_TASK_ID`` is the grammar, and the cost of getting it
    wrong is worse than a late refusal. ``reserve_task`` ACCEPTED an id that
    ``publish_worker_result`` refuses, so the task reached ``[~]``, held a slot
    against the ``worker_limit - 3`` implementation cap, and could never reach
    a terminal state through the one helper a worker may call -- F2's
    permanent deadlock, reached from a phase plan that was legal by the
    grammar the plan publishes. ``_parse_task_metadata`` is the loud stop and
    this is the defence in depth; both are needed, because a tracker row can
    also arrive from a resumed run whose plan was imported by an older build.
    """
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise TrackerValidationError(
            f"invalid task id {task_id!r}: a task id is written into a tracker "
            "cell, into the replay key of the transition that reserves it, "
            "into a branch name and into the name of the directory its result "
            "is published in, so it is held to the task-id grammar and not to "
            "_TOKEN. Accepting one _TOKEN admits and publication refuses would "
            "hold an implementation slot against the worker_limit cap for a "
            "task that can never reach a terminal state")
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise TrackerValidationError(
            f"invalid owner {owner!r}: an owner is one bounded identifier "
            "token, because it is written into a table cell and into the "
            "name of the file that carries this worker's answer")
    return _attempt_token(attempt)


def reserve_task(run_dir, *, task_id: str, owner: str, attempt: int) -> dict:
    """Persist the first ``[ ] -> [~]`` assignment, with its baseline.

    THE BASELINE IS THE TARGET TIP AT RESERVATION, and it is persisted here
    rather than derived later. ``HEAD~1`` silently truncates a multi-commit task
    to its last commit and every earlier commit escapes every scope and range
    check; the run's own ``base_commit`` is equally wrong in the other
    direction, because tasks integrated before this one are already in the
    target and would be charged to this task's range.

    An ARTIFACT task records none: it produces no source range, so a baseline
    would be one end of a proof that is never drawn.
    """
    #: NORMALISED FIRST, the way every P03 entry point does it. ``validate_run``
    #: deliberately does not coerce -- its first statement is
    #: ``run_dir / "progress.md"`` -- so a ``str`` reaching it raises
    #: ``TypeError``, which is outside ``TrackerError`` and escapes every
    #: handler a controller has written. A ``str`` is the likeliest spelling a
    #: controller holds, and ``None``, an ``int`` and a ``bytes`` are what a
    #: caller that lost the run directory holds; ``_run_path`` answers all four
    #: inside the family.
    run_dir = _run_path(run_dir)
    token = _validate_assignment(task_id, owner, attempt)

    def mutate(tracker: dict) -> dict:
        row = _task_row(tracker, task_id)
        if row["state"] != "[ ]":
            raise TrackerValidationError(
                f"reserve_task handles the first start only; task {task_id} is "
                f"{row['state']!r}, and a re-assignment carries a decision "
                "reference that this transition has nowhere to put")
        definition = _approved_definition(tracker, task_id)
        _require_dependencies_complete(tracker, definition)
        _require_no_scope_conflict(tracker, definition)
        _require_capacity(tracker, owner)
        checkpoint = f"started:{token}"
        if definition["kind"] == TASK_KINDS[0]:
            baseline = _resolved_commit(
                _repo_dir(tracker), _run_field(tracker, "target_branch"))
            checkpoint = f"{checkpoint},baseline:{token}@{baseline}"
        updated = dict(row)
        updated.update({
            _key("State"): "[~]",
            _key("Owner"): owner,
            _key("Attempt"): token,
            _key("Checkpoints"): _append_history(row["checkpoints"], checkpoint),
        })
        return _replace_task(tracker, updated)

    return locked_tracker_update(
        run_dir, transition_id=f"reserve-{task_id}-{attempt}", mutate=mutate)


# ---------------------------------------------------------------------------
# P04 Task 7: resuming an answered block.
#
# TRANSITION AUTHORITY COMES FROM AN EXPLICIT ADOPTED DECISION, never from the
# wording of an answer, and the grant is bound to THE BLOCK and not merely to
# the task. WHICH DECISION IS THE GRANT DEPENDS ON THE ARM. A block on a quorum
# is released by the `quorum.adopt` record `Q-<qid>` that answers it -- the
# spec lists `quorum.adopt` and `task.resume` as distinct actions and says
# "quorum exists to unblock", so the adoption answering the blocked question IS
# the grant. A halt is released by a human `task.resume` that "names the exact
# blocked task in `Scope`, names the attempt it releases in `Attempt`, and its
# `Status` must be `Adopted`" (`templates/decisions.md`).
#
# THIS ONCE DEMANDED `task.resume` ON BOTH ARMS, and the quorum arm was then
# closed for good: `finalize_quorum` writes `Q-<qid>` as `quorum.adopt`,
# decision ids are unique, so no `task.resume` grant could ever carry the id
# the qid binding requires. Every adopted quorum left its task at `[?]`.
#
# WHAT THE TASK ROW ALREADY SAYS IS THE BINDING, and it was free. `settle_quorum`
# mints a quorum decision id as `"Q-" + qid` and `_final_event` already refuses
# an adoption naming any other id, so a quorum decision id CONTAINS the identity
# of the question it answers. Task 10 writes `quorum:<qid>@<path>#sha256=<digest>`
# into the `Question` cell -- the qid for the binding, the digest-bound path for
# the audit trail -- and this transition compares. Without that comparison a
# decision answering an ENTIRELY DIFFERENT question, scoped to T1 with action
# `task.resume`, resumes T1: no quorum, no escalation, and not one unit of the
# drift budget that exists to cap machine decision authority.
#
# THE `halt:` ARM HAS NO DERIVATION AVAILABLE and the code must not pretend
# otherwise. Nothing opened a quorum, so no qid exists and there is no question
# record to hash; the grant asserts the blocker string and carries
# `Provenance: human`, and that arm is an ASSERTION BY THE WRITER. Nothing here
# can tell a correctly copied blocker from a carelessly copied one.
# `decisions.md` is unsigned and hand-editable, so all of this is
# TAMPER-EVIDENT BY CROSS-REFERENCE and none of it is tamper-proof.
#
# Context compaction and a restarted controller are NOT a blocked-task retry.
# Neither answers a question, so neither mints an attempt: this transition runs
# only on a `[?]` row, and a `[~]` row is refused with its own state named.
#
# THE PRODUCES BLOCK WAS A CLAIM TO CHECK AND TWO OF ITS FIVE NAMES DID NOT
# SURVIVE IT.
#
# * `_decision_sections` ALREADY EXISTS -- it is P03's, it takes the whole text
#   of `decisions.md` and returns an ORDERED LIST of `(heading, fields)` pairs,
#   and `parse_decisions` iterates that list. The brief's version was a `dict`
#   keyed by heading. TWO REASONS ONCE WRITTEN HERE FOR REFUSING IT WERE FALSE
#   ABOUT THE BRIEF AND ARE CORRECTED RATHER THAN DROPPED, because in this
#   build a justification that does not hold is itself the defect: the brief's
#   dict version DOES raise on a repeated heading -- its quoted body carries
#   `if current in sections: raise TrackerValidationError(...)` -- so it would
#   NOT have let a second `## H-001` overwrite the first; and iterating a dict
#   under `for did, fields in ...` unpacks each heading CHARACTER-WISE, so the
#   failure is a `ValueError`, not a `TypeError` (and a two-character heading
#   would unpack silently, which is why the diagnosis matters). The reasons
#   that DO hold: it returns a `dict` where every existing caller iterates
#   pairs, a module-level redefinition rebinds the global for `parse_decisions`
#   and every other caller, its heading grammar `(?:H|Q|D)-[0-9A-Za-z]+` admits
#   a third namespace `_decision_id` refuses and a `Q-` body no qid can be, and
#   it needs `re`, which `ALLOWED_IMPORTS` does not hold.
#   CONSUMED HERE, never re-declared.
# * `_decision_fields(lines)` IS NOT BUILT. The brief wrote a decision record as
#   a `| Field | Value |` table and needed a reader for it. That is not this
#   repository's grammar: `templates/decisions.md` writes `- Field: value`, P03's
#   record grammar writes `- **Field:** value`, and `_decision_field` already
#   reads both, with `_decision_sections` assembling them and `parse_decisions`
#   validating the result. A second field reader would be a second answer to
#   "what is a decision record" in the one file whose whole job is to be the
#   audit trail -- and the table spelling is pinned as a REJECTION instead.
#
# So `_validate_decision` reads the trail through `_decisions_text`, the ONE
# door onto `decisions.md`, and through `parse_decisions`, which already refuses
# a generic approval, an unknown action, a provenance that disagrees with the id
# and every other thing a record can get wrong. What is left here is the four
# facts that are specific to THIS grant, and nothing that is already refused
# upstream -- a duplicate screen is one that can be deleted without a test
# noticing.
# ---------------------------------------------------------------------------

#: The one decision action that authorises a task transition. A NEW NAME over an
#: OLD VALUE: `_DECISION_ACTIONS` is P03's closed set of five and the suite pins
#: this constant inside it, because a sixth action spelled only here would be an
#: authority no validator in this run would ever honour.
RESUME_ACTION = "task.resume"

#: The delimiters a checkpoint entry is built from, and the whole of them:
#: `started:attempt-001`, `baseline:attempt-001@<sha>` and
#: `resumed:attempt-001->attempt-002@<decision>`. `->` is listed because it is
#: the one that carries TWO attempts in a single entry, and a scan that split on
#: `:` and `@` alone would see `attempt-001->attempt-002` as one unrecognisable
#: token and spend neither of them.
#:
#: `-` IS DELIBERATELY ABSENT even though it is a separator inside the marker,
#: because it is also a character INSIDE `attempt-001`: splitting on it would
#: destroy every token this scan exists to find.
_CHECKPOINT_DELIMITERS = (":", "@", "->")

#: The two arms a blocked task's `Question` cell may take, and the whole of
#: them. Task 10 renders `quorum:<qid>@<path>#sha256=<digest>` and
#: `halt:<reason>`; `_validate_decision` splits on the same two prefixes. They
#: are constants and not literals because a grant is bound to a block through
#: this vocabulary, and two spellings of it would be two answers to "what is
#: this task blocked on" in the one cell that says so.
#:
#: `-` IS NEITHER ARM and is not listed as a third: P02's `_validate_tasks`
#: already refuses a `[?]` row whose `Question` cell is the absence marker, so
#: a row reaching here carries something. What it does NOT guarantee is that
#: the something is one of these two, which is why the else-branch below is a
#: stop rather than a pass.
_QUESTION_QUORUM_ARM = "quorum:"
_QUESTION_HALT_ARM = "halt:"


def _recorded_attempts(row: dict) -> set:
    """Every attempt this task row has already spent, from its own history.

    THE HISTORY, NOT THE `Attempt` CELL. After one resume the cell reads
    `attempt-002` and `attempt-001` survives only inside `Checkpoints` -- and it
    is still spent. A screen that compared the cell alone would let a third
    attempt re-use the first one's token, and the reservation checkpoint, the
    worker result and the evidence record would then all exist twice under one
    identity, which is fault F6 arriving through arithmetic rather than through
    a claim.

    Tokens are recognised by `_ATTEMPT_TOKEN`, which is a front on
    `_parse_attempt_token` -- so "is this an attempt" is answered by the renderer
    that writes them and not by a second grammar. Anything else in the history,
    a commit sha or a decision id included, simply is not one.
    """
    candidates = [row["attempt"]]
    for entry in _csv(row["checkpoints"]):
        parts = [entry]
        for delimiter in _CHECKPOINT_DELIMITERS:
            parts = [piece for part in parts for piece in part.split(delimiter)]
        candidates.extend(parts)
    return {value for value in candidates if _ATTEMPT_TOKEN.fullmatch(value)}


#: The checkpoint prefix a resume writes: `resumed:<prior>-><new>@<decision>`.
#: Named because `_resumed_by` reads back exactly what `resume_task` writes,
#: and two spellings would let a spent adoption read as unspent.
_RESUMED_CHECKPOINT = "resumed:"


def _resumed_by(row: dict) -> set:
    """Every decision id this task row has already resumed on, from its history.

    THE QUORUM ARM'S ANSWER TO THE ATTEMPT BINDING. A `quorum.adopt` record is
    written by `finalize_quorum` and carries no `Attempt`, so the halt arm's
    rule -- the grant names the attempt it releases -- has nothing to read. The
    qid already ties the adoption to ONE question, but not to one block: a
    resumed attempt that raises the very same question derives the very same
    qid, re-blocks on the same `quorum:<qid>@...` cell, and would otherwise be
    released again by the adoption that released the first block. The
    append-only `Checkpoints` cell already records every resume with the
    decision it cited, so a spent adoption is read from there.
    """
    spent = set()
    for entry in _csv(row["checkpoints"]):
        if entry.startswith(_RESUMED_CHECKPOINT):
            spent.add(entry.rsplit(_CHECKPOINT_DELIMITERS[1], 1)[-1])
    return spent


def _require_fresh_attempt(row: dict, token: str) -> None:
    """The new attempt is one this task has never had.

    TASK 6 PROVED THIS SCREEN UNREACHABLE FROM `reserve_task` and ruled that it
    belongs here. Both halves of that closure were the same shape read from
    opposite ends: `reserve_task` accepts only a `[ ]` row, and P02's
    `_validate_tasks` refuses a `[ ]` row that carries ANY lifecycle cell -- so
    there is no attempt history there to compare against. A `[?]` row is the
    other case entirely: `_validate_tasks` REQUIRES it to carry an owner, an
    attempt and checkpoints, so the input this screen reads always exists and
    the screen really does decide something.

    It takes the TOKEN, not the integer, and that is `_validate_assignment`'s
    ruling applied one function further: `_attempt_token` is the single
    conversion point, and a screen that re-converted what its caller had already
    converted would be a screen dominated by the conversion beside it.

    ONE RULE, NOT TWO. `new_attempt == prior_attempt` is not a second check: the
    prior attempt is in the history by construction, so one screen with one
    diagnosis answers both. Two would be two refusals of one input differing
    only in wording, and the second could be deleted with nothing going red.
    """
    if _member(token, _recorded_attempts(row)):
        raise TrackerValidationError(
            f"attempt {token} has already been used by task {row['id']}; an "
            "attempt is an identity, not a counter -- the reservation "
            "checkpoint, the immutable worker result and the evidence record "
            "are all bound to it, and a re-used token gives two pieces of work "
            "one identity")


def _validate_decision(run_dir, row: dict, decision_ref: str) -> dict:
    """The adopted grant for THIS BLOCK, or a stop.

    THE ROW IS TAKEN, NOT THE TASK ID, and that REOPENS THIS TASK'S OWN RULING
    that the brief's `tracker` argument should be dropped because nothing here
    would read it. That ruling was right while the screens were four facts
    about a record; it stops being right the moment a screen has to read the
    row's `Attempt` and `Question` cells. The row is already in hand three
    lines earlier inside `mutate`, so taking it costs nothing, and re-reading
    the tracker here would add a second reader of a table the caller holds.

    The `tracker` argument itself is still NOT taken, and for the reason the
    brief's version failed rather than the reason once written down: the brief
    resolved the file itself and reported an unresolvable one as "decisions
    file is missing". `_decisions_text` is the ONE door onto `decisions.md` --
    the budget, the projection and `open_quorum` all read the trail through it
    -- and it is what separates a missing file from a name that exists and
    cannot be read. Folding a directory, a dangling link or a FIFO back into
    "no decisions yet" would make an unreadable audit trail read as an
    unrestricted grant.

    NOT ONE SCREEN IS A DUPLICATE OF `parse_decisions`. That parser already
    refuses an unknown action, a generic approval, a provenance that disagrees
    with the id, an Open record carrying an authority, and a `Superseded`
    record nothing supersedes. What is specific to this grant is: it resolves,
    it is the live record, it carries THE ACTION ITS ARM REQUIRES
    (`quorum.adopt` for `quorum:`, `task.resume` for `halt:`), it names this
    task, it is not the absence marker, IT IS NOT ALREADY SPENT, and IT NAMES
    THE BLOCK.

    The absence marker is one `parse_decisions` does NOT refuse: `-` is a
    non-empty string and is not a rubber stamp, so it passes every upstream
    screen while recording that a question was asked and nothing that settles
    it.

    A GRANT IS SPENT AND NOT STANDING, and each arm spends it differently.
    Without that a single adopted record authorises unlimited resumes of its
    task for ever: `_require_fresh_attempt` bounds the ATTEMPTS a task may
    mint, not the GRANTS one record may be read as. On the halt arm the human
    `task.resume` names the attempt it releases, and the row's `Attempt` cell is
    compared -- the same string as the caller's `prior_attempt` by
    construction, since `mutate` refuses the row unless they agree. On the
    quorum arm the adoption carries no `Attempt` (`finalize_quorum` writes
    none), so `_resumed_by` reads the append-only `Checkpoints` history and
    refuses an adoption this task has already resumed on.

    THE BLOCK, THROUGH THE QUESTION CELL, AND THE TWO ARMS ARE NOT THE SAME
    KIND OF THING.

    * `quorum:<qid>@...` is DERIVED. `settle_quorum` mints a quorum decision id
      as `"Q-" + qid` and `_final_event` already refuses an adoption naming any
      other id, for exactly this reason -- so a quorum decision id contains the
      identity of the question it answers and the comparison is arithmetic, not
      trust. Re-opens close for free: `derive_reopen_qid` mints a DIFFERENT
      qid, so a stale answer cannot resume a re-asked block.
    * `halt:<reason>` is ASSERTED. No quorum was opened, so no qid exists and
      there is no question record to hash. The grant repeats the reason in a
      `Blocker` field and must carry `Provenance: human`. NOTHING HERE CAN TELL
      A CORRECTLY COPIED BLOCKER FROM A CARELESSLY COPIED ONE, and the template
      says so in the same words rather than claiming an enforcement that does
      not exist.

    ONE ARM OR THE OTHER, NEVER NEITHER. `_validate_tasks` requires a `[?]`
    row's `Question` cell to be something, and nothing anywhere requires it to
    be one of these two -- so a cell in neither form reaches here, binds the
    grant to nothing, and is a stop.

    NO DEFAULT HERE MAY MAKE ITS OWN COMPARISON VACUOUS, and that is a rule
    about the `.get` and NOT about the `if` below it. A field read as
    `record.get(name, <the very thing it is about to be compared with>)` turns
    an ABSENT field into a PASS: the screen still reads as a guarantee, the
    comparison is still correct, and no mutant aimed at that comparison finds
    anything. So every optional field defaults to `_ABSENT_CELL`, which is a
    value no legal counterpart can equal. BOTH DEFAULTS ARE PINNED -- a mutant
    re-pointing either at its comparand dies.

    WHAT IS REFUSED EXPLICITLY IS THE CELL, NOT THE RECORD, and that split was
    measured rather than argued. An explicit `granted_attempt == _ABSENT_CELL`
    and an explicit `asserted == _ABSENT_CELL` were both written first and
    both SURVIVED as mutants: with the defaults above they are unreachable
    second refusals of an input the comparison already refuses, and a screen
    that can be deleted with nothing going red is one this build deletes. The
    two CELL-side screens are the opposite -- each kills its mutant:

    * `halt:-` IS A LEGAL CELL. `_validate_tasks` refuses a `[?]` row whose
      `Question` is `-` and says nothing about a halt ON `-`, so the reason
      split out of that cell is the absence marker itself -- which is exactly
      what a record with no `Blocker` field reads back as. The two sides
      matched, and a grant asserting nothing cleared a halt asserting nothing
      through a comparison that was perfectly correct. The cell must state a
      blocker for there to be anything to repeat.
    * `quorum:` WITH NOTHING AFTER IT yields an empty qid, and the comparison
      then asks whether `decision_ref` is the literal `Q-`. `_decision_id`
      refuses that before the lock, so it was unreachable -- but only by a
      screen two functions away, which is not a property this one should rest
      on, and the diagnosis it produced named `qid ''`.

    AND NONE OF THIS IS TAMPER-PROOF. `decisions.md` is unsigned and
    hand-editable and no code in this module ever writes a `task.resume`
    record, so every halt grant is hand-authored. What the screens buy is that a
    grant clearing a block BY ACCIDENT -- a stale answer, another question's
    answer, a spent grant read a second time -- is caught; a writer who means
    to author a record that satisfies all seven can.
    """
    task_id = row["id"]
    records = parse_decisions(_decisions_text(Path(run_dir)))["decisions"]
    record = records.get(decision_ref)
    if record is None:
        raise TrackerValidationError(
            f"decision {decision_ref} does not resolve in this run's audit "
            "trail; a grant the trail cannot produce is authority nobody gave, "
            "and a block is settled by a recorded decision or not at all")
    if record["status"] != _DECISION_STATUSES[0]:
        raise TrackerValidationError(
            f"decision {decision_ref} is {record['status']} and not "
            f"{_DECISION_STATUSES[0]}; the trail has already replaced it, and "
            "acting on a retired record applies a grant the run withdrew")
    cell = row["question"]
    if cell.startswith(_QUESTION_QUORUM_ARM):
        expected_action = _QUORUM_ADOPT_ACTION
    elif cell.startswith(_QUESTION_HALT_ARM):
        expected_action = RESUME_ACTION
    else:
        raise TrackerValidationError(
            f"task {task_id} is blocked on {cell!r}, which is neither "
            f"{_QUESTION_QUORUM_ARM!r} nor {_QUESTION_HALT_ARM!r}; a grant can "
            "be bound to a question record or to an asserted halt, and a cell "
            "in neither form binds it to nothing")
    if record["action"] != expected_action:
        raise TrackerValidationError(
            f"decision {decision_ref} carries decision action "
            f"{record['action']!r} rather than {expected_action!r}; a block "
            "on a quorum is released by the adoption that answers it and a "
            "halt by a human's resume grant, and authority to restart a task "
            "is an explicit recorded action, never something read out of the "
            "prose of a decision that settled something else")
    scope = _csv(record.get("scope", _ABSENT_CELL))
    if not _member(task_id, scope):
        raise TrackerValidationError(
            f"decision {decision_ref} is not scoped to task {task_id}; its "
            f"Scope names {list(scope)}, and a grant written for one task is "
            "not a grant for whichever task happens to cite it")
    if record["answer"] == _ABSENT_CELL:
        raise TrackerValidationError(
            f"decision {decision_ref} records {_ABSENT_CELL!r} where its answer "
            "belongs; that is this schema's empty cell, so an adopted record "
            "carrying it has written down that a question was asked and "
            "nothing at all that settles it")
    if expected_action == _QUORUM_ADOPT_ACTION:
        qid = cell[len(_QUESTION_QUORUM_ARM):].split("@", 1)[0].strip()
        if not qid or qid == _ABSENT_CELL:
            raise TrackerValidationError(
                f"task {task_id} is blocked on {cell!r}, which names no qid; "
                "the derived arm binds a grant to the identity of the question "
                "it answers, and a cell naming no question identifies nothing "
                "for a grant to be bound to")
        if decision_ref != f"Q-{qid}":
            raise TrackerValidationError(
                f"decision {decision_ref} does not answer what task {task_id} "
                f"is blocked on: that block names qid {qid!r}, whose answer is "
                f"'Q-{qid}'. A quorum decision id is 'Q-' followed by the qid "
                "it settles, so a grant naming any other id settled another "
                "question -- and a re-open derives a new qid, so a stale "
                "answer cannot resume a re-asked block")
        if _member(decision_ref, _resumed_by(row)):
            raise TrackerValidationError(
                f"decision {decision_ref} has already resumed task {task_id} "
                "once; an adoption is spent on the block it answered, and a "
                "task that re-raised the same question after resuming on it is "
                "a new block the adoption was never counted against")
    else:
        blocker = cell[len(_QUESTION_HALT_ARM):].strip()
        if not blocker or blocker == _ABSENT_CELL:
            raise TrackerValidationError(
                f"task {task_id} is halted on {cell!r}, which states no "
                "blocker; the asserted arm binds a grant by having the record "
                "repeat the reason back, and there is nothing here to repeat")
        if record["provenance"] != "human":
            raise TrackerValidationError(
                f"decision {decision_ref} is a {record['provenance']} answer "
                f"and task {task_id} is halted rather than in quorum; a halt "
                "opened no question, so there is no qid to bind a machine "
                "answer to it and the arm is a human assertion or nothing")
        granted_attempt = record.get("attempt", _ABSENT_CELL).strip()
        if granted_attempt != row["attempt"]:
            raise TrackerValidationError(
                f"decision {decision_ref} grants the resume of attempt "
                f"{granted_attempt!r} and task {task_id} is blocked at "
                f"{row['attempt']!r}; a grant is spent on the attempt it "
                "names, and one naming only the task would authorise every "
                "resume of that task for ever")
        asserted = record.get("blocker", _ABSENT_CELL).strip()
        if asserted != blocker:
            raise TrackerValidationError(
                f"decision {decision_ref} states Blocker {asserted!r} and task "
                f"{task_id} is halted on {blocker!r}; this arm is an ASSERTION "
                "by whoever wrote the record and not a derivation -- no qid "
                "exists to derive from -- so the two strings agreeing is the "
                "whole of the binding there is")
    return record


def _require_decisions_pointer(tracker: dict, run_dir) -> None:
    """The run's own `decisions` pointer names the file the grant is read from.

    `_decisions_text` reads `<run_dir>/decisions.md` and `initialize_run`
    separately records `decisions` as a repo-root-relative path. Nothing
    validated that the two agree, and today they always do because
    `initialize_run` writes the constant -- so this is LATENT rather than live.
    It is asked HERE, at the first caller for which it matters, because
    `resume_task` is the first transition to rest a GRANT on that file: if the
    pointer is ever written differently, the authority to restart a task would
    be read out of a file the run does not consider its audit trail, and
    nothing would object.

    ASKED, NOT RESOLVED THROUGH. Pointing `_decisions_text` at the field
    instead would make the one door's answer depend on a tracker cell for the
    budget and the projection too, and those two read the trail on runs this
    transition never touches. Agreement is the property that matters; which of
    the two spellings wins is not this task's to decide.
    """
    stated = _run_field(tracker, "decisions")
    if (_repo_dir(tracker) / stated).resolve() != (
            Path(run_dir) / _DECISIONS_FILE).resolve():
        raise TrackerValidationError(
            f"this run records its audit trail at {stated!r} and a resume "
            f"grant is read from {_DECISIONS_FILE!r} inside the run directory; "
            "the two must name one file, because a grant read from anywhere "
            "else is authority taken from a document the run does not treat as "
            "its audit trail")


def resume_task(run_dir, *, task_id: str, prior_attempt: int, new_owner: str,
                new_attempt: int, decision_ref: str) -> dict:
    """Persist an answered ``[?] -> [~]`` assignment before redispatch.

    A FRESH BASELINE IS RECORDED FOR A SOURCE TASK, re-derived rather than
    carried forward. The target branch moves while a task is blocked -- other
    tasks integrate -- and re-using attempt one's baseline would charge every
    commit that landed in between to this attempt's range. The prior baseline is
    APPENDED BESIDE, never replaced: it is still one end of the range proof for
    the work attempt one actually did.

    THE CAP IS ASKED AGAIN, and an answered block buys no capacity. A run whose
    brains are still in flight waits rather than over-subscribing the three
    slots the next quorum needs -- which is the deadlock F2 names, reached the
    long way round. So are the dependency and scope rules: a dependency can
    regress between the block and the answer, and the answer may be exactly
    "that task was wrong, redo it", so the reservation's old verdict is not
    evidence about the state the resume runs in.

    THE `Question` CELL IS LEFT EXACTLY AS IT WAS, and that is a correction
    rather than an omission. This transition once overwrote it with
    `resolved:<ref>`, which destroyed the tracker's only pointer to WHAT WAS
    ASKED in the same write that acted on the answer -- so a grant bound to the
    wrong block could not even be audited afterwards. Nothing consumes that
    cell on a `[~]` row: `_validate_tasks` constrains it only for `[ ]` (which
    must carry no lifecycle state at all) and for `[?]` (which must carry
    something), and the resume is already recorded where a record belongs --
    `resumed:<prior>-><new>@<decision>` in the APPEND-ONLY `Checkpoints` cell.
    Overwriting bought a second, lossy copy of a fact the history already held.

    `decision_ref` IS SCREENED BEFORE THE LOCK IS EVER TAKEN, and by the same
    `_decision_id` grammar `_validate_tasks` holds a task's `Decisions` cell to.
    It is interpolated into the replay key -- which is what makes a re-issue
    citing a DIFFERENT decision a new transition rather than an inert replay of
    the first -- so an unscreened one would come back from
    `locked_tracker_update` as `invalid transition identity`: a diagnosis about
    a transition name, handed to a caller that named a decision wrongly.
    """
    #: NORMALISED FIRST, the way every P03 entry point does it. ``validate_run``
    #: deliberately does not coerce -- its first statement is
    #: ``run_dir / "progress.md"`` -- so a ``str`` reaching it raises
    #: ``TypeError``, which is outside ``TrackerError`` and escapes every
    #: handler a controller has written. A ``str`` is the likeliest spelling a
    #: controller holds, and ``None``, an ``int`` and a ``bytes`` are what a
    #: caller that lost the run directory holds; ``_run_path`` answers all four
    #: inside the family.
    run_dir = _run_path(run_dir)
    token = _validate_assignment(task_id, new_owner, new_attempt)
    prior_token = _attempt_token(prior_attempt)
    if not isinstance(decision_ref, str) or not _decision_id(decision_ref):
        raise TrackerValidationError(
            f"invalid decision reference {decision_ref!r}: a resume names an "
            "'H-<n>' or 'Q-<qid>' decision, because the id is what says whether "
            "a human or a quorum granted it and it is written into both the "
            "task's Question cell and this transition's replay key")
    marker = f"{_RESUMED_CHECKPOINT}{prior_token}->{token}@{decision_ref}"

    def mutate(tracker: dict) -> dict:
        row = _task_row(tracker, task_id)
        if row["state"] != "[?]" or row["attempt"] != prior_token:
            raise TrackerValidationError(
                f"resume_task answers a blocked attempt; task {task_id} is "
                f"{row['state']!r} at {row['attempt']!r} and this resume names "
                f"{prior_token!r}. A compaction or a restarted controller is "
                "not a blocked-task retry and mints no attempt")
        _require_fresh_attempt(row, token)
        _require_decisions_pointer(tracker, run_dir)
        _validate_decision(run_dir, row, decision_ref)
        definition = _approved_definition(tracker, task_id)
        _require_dependencies_complete(tracker, definition)
        _require_no_scope_conflict(tracker, definition)
        _require_capacity(tracker, new_owner)
        checkpoint = marker
        if definition["kind"] == TASK_KINDS[0]:
            baseline = _resolved_commit(
                _repo_dir(tracker), _run_field(tracker, "target_branch"))
            checkpoint = f"{checkpoint},baseline:{token}@{baseline}"
        updated = dict(row)
        updated.update({
            _key("State"): "[~]",
            _key("Owner"): new_owner,
            _key("Attempt"): token,
            _key("Checkpoints"): _append_history(row["checkpoints"], checkpoint),
        })
        return _replace_task(tracker, updated)

    return locked_tracker_update(
        run_dir,
        transition_id=f"resume-{task_id}-{prior_attempt}-{new_attempt}"
                      f"-{decision_ref}",
        mutate=mutate)


# ---------------------------------------------------------------------------
# P04 Task 8: the baseline-anchored source-range proof -- faults F3 and F4.
#
# THIS IS THE ONLY PLACE THE RUN CHECKS A WORKER'S STORY AGAINST THE
# REPOSITORY, and the module does not execute git to do it.
#
# The brief for this task called `_git_out` three times and `_git` once. Both
# are `subprocess.run` wrappers; `subprocess` is the single capability
# `ALLOWED_IMPORTS` most exists to withhold, and the master plan's quorum ruled
# the shape that replaces them: THE MODULE EMITS THE ARGV, THE CONTROLLER RUNS
# IT, THE MODULE VALIDATES THE TRANSCRIPT. That is not a new pattern here --
# P06's `final_suite_commands` / `record_final_verification` already gate the
# terminal transition that way, and `resolve_evidence` already does it for test
# results. The skill's whole verification story rests on attested external
# execution; independence is bought by a NON-CLAIMANT re-running, never by this
# module executing.
#
# Running git inside a repository the worker can write IS worker-controlled
# code execution: `core.fsmonitor`, `core.sshCommand`, `include.path` in
# `.git/config` and `diff.external`/`textconv` via `.gitattributes` are all
# "run this program" knobs that `rev-list` and `diff` honour. Shelling out
# would hand the withheld capability to the party it was withheld from.
#
# WHAT IS DERIVED HERE, ON NOBODY'S WORD, AND WHAT IS NOT. The head is read
# out of the ref store: `verify_source_range` takes a required `head_ref`, and
# the proved head is the tip THIS repository holds for it -- a `head` sha that
# disagrees is refused rather than believed. The baseline is the sha
# `reserve_task` recorded by resolving the target branch AT RESERVATION
# (`reserved_baseline` below); it is module-derived historically and is
# re-derived nowhere, because the target branch has moved on and there is no
# current reference to check it against. Nothing here reads a git OBJECT --
# `zlib` and `subprocess` are both off the import list -- so "this commit
# exists" is not a fact this module can establish about either end.
#
# THE FIRST VERSION OF THIS PARAGRAPH CLAIMED MORE THAN THE CODE DID, which is
# the failure this build is built to catch. It said both ends were
# module-derived when `_resolved_commit` short-circuited on any forty-hex ref
# without opening the ref store -- and both production ends ARE forty hex
# characters. A full `attested` proof was obtainable over commits that do not
# exist in a directory that is not a repository. `_resolved_commit` now opens
# the store before that short-circuit and the head comes from a reference, so
# the anchor is a fact rather than a sentence.
#
# The chain is then read out of the transcript's OWN INTERNAL STRUCTURE (first
# parent equals the baseline, each parent equals the previous, exactly one
# parent each, no commit named twice, the last equals the head, no entry with
# an empty path list) rather than believed as an assertion the transcript
# makes about itself.
#
# `--no-renames` IS LOAD-BEARING AND NOT A STYLE CHOICE. Rename detection is ON
# by default and git then reports only a rename's DESTINATION. Measured on a
# real repository (`RenameHidesTheVictimTests`): a task whose declared scope is
# `mine/` runs `git mv theirs/victim.py mine/victim.py`; `git diff --name-only`
# prints `mine/victim.py` alone, every path is inside the declared scope, and
# THE CHECK PASSES WHILE THE TASK HAS DELETED ANOTHER TASK'S FILE.
# `--no-renames` prints both sides and the check refuses. The pathspec-limited
# guard in the Global Constraints is NOT affected and must not be "fixed" to
# match: limiting by path makes git report the SOURCE side of a rename, so
# moving a file out of `skills/pipeline/` prints it either way.
#
# `proof_mode` RECORDS WHAT KIND OF PROOF THIS IS. Appearing to verify is the
# failure mode to avoid, so the returned dict carries `attested` bound to the
# digest of the exact transcript that was checked, and absent evidence is a
# refusal that NAMES WHAT IS MISSING rather than a weaker check passed
# silently.
#
# Residual risk, stated plainly: a controller that FABRICATES a transcript
# defeats this -- and defeats every other option, because it owns `progress.md`
# and `locked_tracker_update` runs in its own process. What this design defeats
# mechanically is the worker who edits outside its scope, truncates its range,
# reports a head its own ref store does not carry, or reports a head off an
# unrelated history.
#
# "NAMES COMMITS THAT DO NOT EXIST" IS NOT DEFEATED HERE, and the earlier
# wording said it was. A wholly fabricated intermediate commit spliced into a
# chain that still starts at the baseline and ends at the head is ACCEPTED by
# this function, because checking it would mean reading a git object and this
# module reads none. The defence against it is Task 10's cross-comparison of
# the worker's `commits` against the controller's own transcript. Tasks 10 and
# 11 read this block as their specification, so it says which of the two
# functions holds that line -- AND WHAT TASK 10 HAS TO DO FOR THE LINE TO
# EXIST, because "deferred to Task 10" was checked against the phase plan and
# Task 10 as sketched could not have carried it: the call omitted the required
# `transcript=`, nothing said where a transcript came from, and the only
# comparison present would have been the worker's list against the worker's
# own document. The phase plan now says the three things, and they are
# repeated here because this block is what gets read:
#
#   1. THE CONTROLLER RUNS THE COMMAND. It calls `source_range_commands`,
#      executes the argv, and passes the captured stdout as `transcript`.
#      A transcript taken from the worker's document makes the comparison
#      compare the worker with itself, which is worse than no check because
#      it reads as one.
#   2. `head_ref` IS DERIVED BY THE CONTROLLER -- `task/<task_id>`, the
#      spelling this phase already pins for the same task -- and never read
#      out of the worker's result.
#   3. THE COMPARISON IS `result["commits"]` (the worker's claim) against
#      `proof["commits"]` (the controller's evidence). A commit the worker
#      invented is not in the controller's `git log` output, so the tuples
#      differ. That, and nothing here, is what closes the gap.
# ---------------------------------------------------------------------------

#: The word the master plan pins for a proof taken over attested external
#: execution rather than over an object read this module performed itself.
PROOF_ATTESTED = "attested"

#: NUL, as the record separator between commits in the transcript -- THE SAME
#: `_NUL` the filesystem door screens for, aliased here rather than respelled.
#: It is the ONE byte a POSIX path cannot carry, which is what makes the split
#: unambiguous: a repository really may hold a file named with forty hex
#: characters and a space, so "does this line look like a header" is not a
#: question with a safe answer. `%x00` is git's own spelling of it inside a
#: `--format`, so the emitted argv carries the four characters `%x00` and no
#: actual NUL -- an argv element with a NUL in it is one `subprocess` refuses.
_RANGE_SEPARATOR = _NUL

#: `%H %P`: the commit and its parents, space separated, and NOTHING ELSE.
#: Parents come from here rather than from a `_commit_parents` object read
#: precisely because the module performs no object read; linearity is then a
#: property of the transcript's structure, which is checkable, rather than a
#: claim it makes.
_RANGE_FORMAT = "--format=%x00%H %P"

#: The checkpoint marker `reserve_task` and `resume_task` write. Spelled ONCE
#: and read back through the same constant: a second spelling would be a
#: second answer to "where is this attempt's baseline", in the one cell that
#: says so.
_BASELINE_CHECKPOINT = "baseline:"


def _repo_argument(repo) -> str:
    """The repository location, as one thing that can be an argv element.

    `os.PathLike` IS ACCEPTED BECAUSE EVERY CALLER HAS A `Path`, and `os.fspath`
    is the standard-library answer for "give me the string". A PathLike that
    answers with bytes falls through to the string screen and is refused there
    rather than silently becoming `b'/repo'` inside an argv this module told a
    controller to run.

    THE NUL SCREEN IS NOT DECORATION. `subprocess` refuses an argv element
    containing one with a `ValueError`, so an unscreened location would turn a
    bad tracker cell into a crash in the CONTROLLER, outside this module's
    exception family and far from the thing that was wrong. It is also the
    record separator this transcript grammar is built on.
    """
    if isinstance(repo, os.PathLike):
        try:
            repo = os.fspath(repo)
        except TypeError as exc:
            raise TrackerValidationError(
                f"the repository location {repo!r} cannot be spelled as a path "
                f"({type(exc).__name__}: {exc})") from exc
    if not _text(repo):
        raise TrackerValidationError(
            f"the repository location {repo!r} is not a nonempty path; the "
            "emitted command is pinned to it with `-C`, so a proof obtained "
            "somewhere else cannot be handed back as this one")
    if _RANGE_SEPARATOR in repo:
        raise TrackerValidationError(
            "the repository location carries a NUL byte, which no argv element "
            "may hold and which is this transcript grammar's record separator")
    #: THE SAME HARM AS THE NUL, THROUGH THE OTHER DOOR, and it was found by
    #: Task 11's totality corpus rather than by this function's own. A lone
    #: surrogate that is NOT one of `surrogateescape`'s -- `"\ud800"`, which
    #: no filesystem produced -- makes `os.fsencode` raise `UnicodeEncodeError`
    #: inside `subprocess`, in the CONTROLLER's process, outside this module's
    #: exception family and far from the tracker cell that was wrong. That is
    #: the identical sentence the NUL screen above is justified by, so it is
    #: the identical screen.
    #:
    #: `os.fsencode` RATHER THAN `.encode("utf-8")`, and the difference is a
    #: live repository rather than a nicety: a POSIX path holding bytes that
    #: are not UTF-8 arrives in Python as `surrogateescape` code points in
    #: `\udc80`-`\udcff`, `subprocess` encodes those back to the original
    #: bytes without complaint, and `str.encode` would refuse the legitimate
    #: repository this module is being pointed at. The screen must be the one
    #: the consumer actually performs.
    try:
        os.fsencode(repo)
    except (UnicodeEncodeError, ValueError) as exc:
        raise TrackerValidationError(
            f"the repository location {repo!r} cannot be spelled as an argv "
            f"element ({type(exc).__name__}: {exc}); an unencodable name would "
            "raise inside the controller's process rather than here, which is "
            "the harm the NUL screen above exists to prevent") from exc
    return repo


def _range_ends(repo, baseline, head, head_ref) -> tuple:
    """`(location, baseline sha, head sha)` -- THE HEAD TAKEN FROM A REFERENCE.

    THIS IS THE ANCHOR, AND SAYING SO IS NOT THE SAME AS BEING IT. The first
    version of this function resolved both ends through `_resolved_commit` and
    called that "both ends module-derived". It was not: `_resolved_commit`
    returned a forty-hex ref unchanged without opening anything, and both ends
    of the production call ARE forty hex characters -- the baseline by
    construction from `reserved_baseline`, the head because a worker result's
    `source_ref` is schema-bound to one. The module therefore derived nothing,
    read no ref store and never established that `repo` was a repository at
    all; a complete `attested` proof was obtainable over a directory that did
    not exist. Two things changed. `_resolved_commit` now opens the store
    BEFORE the short-circuit, so no answer it gives is free of the repository.
    And the head is no longer accepted as a bare object name.

    `head_ref` IS THE TASK'S BRANCH AND IT IS REQUIRED. The module resolves it
    through the ref store and THAT is the head of the proved range; `head` is
    the sha the worker CLAIMS, checked against it and refused on disagreement.
    An object name is refused for `head_ref` specifically because an object
    name answers itself: accepting one would restore the hole this parameter
    exists to close, and a case that cannot be tied to the ref store must
    refuse rather than attest.

    `head` IS HELD TO THE MIRROR OF THAT RULE, and the first version of this
    function was not consistent about it. `head_ref` must NOT be an object
    name; `head` must BE one. Both ends went through `_resolved_commit`, so
    `head="HEAD"`, `head="main"` or `head=head_ref` resolved through the same
    store and the `claimed != tip` comparison compared the store with itself
    -- a no-op, measured. The only thing standing behind it was "a worker
    result's `source_ref` is forty hex by schema", which is EXACTLY the
    reasoning that produced the hole this function was rewritten to close, so
    it is not trusted for `head` either. A claim that is not spelled as a
    claim is refused before the store is asked.

    WHAT THIS ESTABLISHES, STATED SO NOBODY HAS TO INFER IT:

    * `repo` is a directory this process can read as a git repository, in
      git's OWN sense of the phrase: a `.git` directory or a gitdir pointer,
      a readable commondir, a readable `HEAD`, and `objects/` and `refs/`
      directories. The weaker earlier test -- `.git` is a directory -- was
      satisfied by a directory holding one ref file that `git -C` itself
      refuses, so the sentence promised more than the code asked.
    * `head_ref` is a reference THIS store carries, and the returned tip is
      the value the store holds for it, not a value anybody supplied.
    * the caller's `head`, if it names a different commit than that tip, is
      refused.

    WHAT IT DOES NOT ESTABLISH, EQUALLY PLAINLY:

    * that the BASELINE is a commit in this repository. It is the sha
      `reserve_task` recorded by resolving the target branch AT RESERVATION,
      and the target branch has moved on since; there is no current reference
      to check it against and this module reads no objects, so the baseline is
      module-derived HISTORICALLY and is re-derived nowhere.
    * that any commit named in the transcript exists. No object is ever read
      -- `zlib` and `subprocess` are both off the import list -- so a
      fabricated intermediate commit is defeated by Task 10's cross-comparison
      against the controller's own transcript, never here.
    """
    location = _repo_argument(repo)
    if not _text(head_ref):
        raise TrackerValidationError(
            f"the head reference {head_ref!r} is not a nonempty reference "
            "name; the head of a proved range is read out of this "
            "repository's ref store, never taken as an object name on the "
            "worker's word")
    if _COMMIT.fullmatch(head_ref):
        raise TrackerValidationError(
            f"the head reference {head_ref!r} is an object name, and an object "
            "name answers itself: resolving one establishes nothing about this "
            "repository. Name the reference whose tip it is, or the proof is "
            "anchored on a number nobody checked")
    tip = _resolved_commit(location, head_ref)
    if not isinstance(head, str) or not _COMMIT.fullmatch(head):
        raise TrackerValidationError(
            f"the claimed head {head!r} is not an object name; the head is a "
            "CLAIM checked against the tip this ref store holds, and a claim "
            "spelled as a reference makes the store answer itself -- "
            f"{head!r} and {head_ref!r} would both resolve here and the "
            "comparison would compare nothing")
    claimed = _resolved_commit(location, head)
    if claimed != tip:
        raise TrackerValidationError(
            f"the claimed head {claimed} is not the tip of {head_ref!r}, which "
            f"this repository's ref store says is {tip}; a head the store does "
            "not agree with is the worker's word about its own range")
    return (location, _resolved_commit(location, baseline), tip)


def _range_argv(location: str, base: str, tip: str) -> tuple:
    """The one command, built once, so the emitter and the diagnostic agree.

    EVERYTHING IN THE REPOSITORY THAT CAN CHANGE HOW A PATH IS SPELLED OR
    WHETHER IT APPEARS AT ALL IS NEUTRALISED HERE. That is the master plan's
    general rule, and the wording is "everything in the repository" rather
    than "every git config" because the first phrasing was NARROWER THAN THE
    HAZARD and missed the fourth instance outright -- a replace ref is not a
    config. The same defect has now been measured four times:

    * `diff.renames` is ON by default and reports only a rename's
      DESTINATION, so `git mv theirs/victim.py mine/victim.py` passes a scope
      check for `tree:mine` while deleting another task's file.
      `--no-renames` prints both sides.
    * `diff.relative` reports paths relative to the command's directory, so
      with `-C <repo>/mine` the out-of-scope `theirs/secret.py` VANISHES from
      the transcript entirely and `mine/a.py` is spelled `a.py`.
      `--no-relative` restores both. Measured.
    * `diff.ignoreSubmodules=all` -- and the per-submodule
      `submodule.<name>.ignore=all` -- removes a changed submodule gitlink
      from `--name-only` OUTPUT ALTOGETHER. Measured: a commit that bumps
      `mods/sub` prints `mods/sub` by default and prints nothing at all under
      that config, so a commit touching one in-scope file and one out-of-scope
      submodule passes the scope check. `--ignore-submodules=none` restores
      it.
    * `core.quotePath` decides whether a non-ASCII path is C-quoted or
      printed raw, which is "how a path is spelled" exactly. It is pinned to
      `true` -- git's own default -- rather than to `false` because that keeps
      the transcript PURE ASCII and therefore always decodable by whatever
      captured it, and because a C-quoted path begins with `"` and is refused
      by the scope check. Pinning the permissive value would push a decode
      failure into the controller, which is the harm `_repo_argument`'s NUL
      screen exists to prevent. Fail closed, deterministically, rather than
      fail closed by default.
    * `refs/replace/` REWRITES THE OBJECT GRAPH ITSELF, and it is the worst
      of the four because it needs NO CONFIG EDIT: `core.useReplaceRefs`
      defaults to `true` and `git replace -f <tip> <decoy>` is ordinary
      porcelain writing an ordinary ref in a repository the worker owns.
      Measured: a tip that changes `mine/a.py` AND `theirs/secret.py`,
      replaced by a same-parent decoy touching only `mine/a.py`, prints one
      path through the unpinned argv and both through the pinned one. It
      defeats more than the rename bypass did -- `%H` and `%P` print the REAL
      commit and the REAL parent, so the chain walk, the distinctness screen,
      the baseline anchor and the head claim are all satisfied by genuine
      history and only the path list is substituted. `git replace` on the
      tip's TREE hides a path the same way, and the same pin restores it.

    THE REPLACE PIN IS TWO TOKENS AND THE SECOND ONE IS THE LOAD-BEARING ONE.
    Measured on git 2.39.5, and it is the reverse of what the option name
    suggests: `--no-replace-objects` ALONE IS DEFEATED by `core.useReplaceRefs
    = true` in the repository's own `.git/config`, which the worker owns.

        --no-replace-objects, no config          -> mine/a.py theirs/secret.py
        --no-replace-objects, repo config true   -> mine/a.py        <- DEFEATED
        -c core.useReplaceRefs=false, cfg true   -> mine/a.py theirs/secret.py
        both, repo config true                   -> mine/a.py theirs/secret.py

    The flag is applied before config parsing and the config then overwrites
    it; a `-c` is the highest-precedence source and no file can reach past it.
    So `-c core.useReplaceRefs=false` is what actually holds, and
    `--no-replace-objects` is kept beside it because it is git's documented
    spelling of the intent and because a pin whose strength depends on one
    version's parse order should not be a single token. NEITHER IS REDUNDANT
    -- do not delete the `-c` as a duplicate of the flag.

    A NON-ASCII PATH CAN NEVER BE PROVED, AND THAT IS A PRODUCT CONSTRAINT,
    not an accident. `core.quotePath=true` C-quotes it, a C-quoted path begins
    with `"`, and no scope claims such a path -- so a task that commits a
    non-ASCII filename INSIDE ITS OWN DECLARED SCOPE cannot prove its range.
    Pinning the value makes that permanent rather than dependent on a config,
    so it is recorded here as a rule this build accepts: NO TASK MAY ADD A
    PATH OUTSIDE ASCII. The alternative -- pinning `false` -- buys non-ASCII
    paths at the price of a transcript whose decoding depends on the
    controller's locale, which is the harm `_repo_argument`'s NUL screen
    exists to prevent.

    A SIXTH WAS FOUND BY TASK 11 AND THE ENTRY BELOW USED TO CLAIM IT WAS
    INERT. `log.showSignature` was measured against this argv, found inert,
    and written down as inert -- and the measurement was taken over a history
    with no signed commit in it, which measures nothing. Re-measured on git
    2.39.5 over a commit carrying a `gpgsig` header: with `log.showSignature
    = true` in the repository's own config, gpg's verification text is written
    to STDOUT and lands INSIDE the transcript -- thirteen `gpg:` lines in the
    first record's BODY, where `_parse_range_transcript` reads them as paths,
    and before the first separator when the signed commit is the only record,
    where the transcript is refused as not beginning at one. Both ends are
    wrong in the SAFE direction -- the injected lines are claimed by no scope,
    so the range is refused -- but the refusal blames the worker's range for
    the repository's config, which is a false accusation against an honest
    worker and, in a real run, an unfindable one. `--no-show-signature` is a
    `log` option, so it outranks every config source inside the repository:
    measured holding against `.git/config`, a command-line `-c`, an
    `[include] path =` file, a `.git/config.worktree` under
    `extensions.worktreeConfig`, and `gpg.format` -- unlike
    `--no-replace-objects`, no file reaches past it and no second token is
    needed.

    Measured and NOT pinned, with the reason: `log.abbrevCommit`,
    `log.decorate` and `log.follow` are inert against a custom `--format` and
    an empty pathspec; `diff.orderFile` changes the
    order of paths inside one record and the union is sorted here anyway;
    `diff.external` is not consulted by `--name-only`; `log.diffMerges` can
    only ADD paths for a merge, and a merge inside the range is refused on its
    parent count, which comes from `%P` and no config touches.

    Swept for a FIFTH under the widened wording and none found, each measured
    inert against this argv on a real repository whose range touches one
    in-scope and one out-of-scope path: `.git/info/grafts` (both a reparent to
    the baseline's parent and a reparent to the decoy -- it rewrites parents
    and hides no path), `.git/info/attributes` and `.gitattributes`
    (`theirs/* -diff binary`), `.gitignore` and `.git/info/exclude` (they
    speak about untracked files, not about a committed diff),
    `core.sparseCheckout` with `.git/info/sparse-checkout`, a written
    `commit-graph`, a `[include] path =` in `.git/config` pointing at a file
    that sets all three of the configs above, `extensions.worktreeConfig`
    with a `.git/config.worktree` doing the same, `core.attributesFile`,
    `core.excludesFile`, `.git/objects/info/alternates`, `diff.noprefix` and
    `diff.srcPrefix`, `core.ignoreCase`, `core.precomposeUnicode`, and
    `log.diffMerges=off` -- a command-line `-c` and a `log` option both
    outrank every config FILE, which is the general reason most of these are
    inert. `.git/shallow` is the one that is not inert, and it fails in the
    SAFE direction: it makes the tip look parentless, so `--name-only` prints
    its WHOLE tree and the scope check sees MORE paths, never fewer.
    """
    return ((
        "git", "--no-replace-objects", "-C", location,
        "-c", "core.quotePath=true", "-c", "core.useReplaceRefs=false", "log",
        "--reverse", "--no-renames", "--no-relative",
        "--ignore-submodules=none", "--name-only", "--no-show-signature",
        "--no-color", _RANGE_FORMAT, f"{base}..{tip}", "--",
    ),)


def source_range_commands(repo, *, baseline: str, head: str,
                          head_ref: str) -> tuple:
    """The exact commands whose output proves one task's implementation range.

    ONE command, and it is a `log` rather than a `rev-list` plus a `diff` per
    commit, because the module cannot know how many commits are in the range
    before it has been told -- and because two commands would be two
    transcripts to reconcile for a fact one of them already carries.

    `head_ref` IS REQUIRED HERE TOO, and not as symmetry for its own sake: the
    argv this function hands a controller carries the resolved ends, so an
    emitter that would accept a head the ref store never named would print a
    command whose range is the worker's word. The emitter and the verifier
    anchor identically because they call `_range_ends` identically.
    """
    return _range_argv(*_range_ends(repo, baseline, head, head_ref))


def _parse_range_transcript(text) -> tuple:
    """One transcript, as `({"commit", "parents", "paths"}, ...)`.

    THE GRAMMAR IS STRICT BY CONSTRUCTION. This is the module's whole reading
    of an external process's stdout, so a shape it cannot account for is
    refused rather than skipped: a parser that shrugged at a line it did not
    recognise would let a spliced record ride along as a path, or a path ride
    along as a record.

    The shape git actually emits, measured rather than recalled: each record is
    the separator, then `<commit> <parents...>`, then -- ONLY WHEN THE COMMIT
    CHANGED SOMETHING -- one empty line and then one line per path. An empty
    commit is a header and nothing else, which is exactly the signal fault F4
    needs and the reason the header is not followed by an unconditional blank.
    """
    if not isinstance(text, str):
        raise TrackerValidationError(
            "a range transcript is the captured stdout of the emitted command, "
            f"which is text; got {type(text).__name__}")
    if not text:
        return ()
    if not text.startswith(_RANGE_SEPARATOR):
        raise TrackerValidationError(
            f"a range transcript begins at a record separator; this one begins "
            f"{text[:60]!r}, so it is not the output of the emitted command")
    entries = []
    for chunk in text.split(_RANGE_SEPARATOR)[1:]:
        lines = chunk.split("\n")
        if lines.pop() != "":
            raise TrackerValidationError(
                "every record in a range transcript is newline-terminated; the "
                "last one is not, so the transcript was truncated mid-record")
        if not lines:
            raise TrackerValidationError(
                "a range transcript carries an empty record, which names no "
                "commit at all")
        commit, space, rest = lines[0].partition(" ")
        if not space:
            raise TrackerValidationError(
                f"the range transcript record {lines[0]!r} is not "
                "'<commit> <parents>'; the separator between them is one space")
        parents = tuple(rest.split(" ")) if rest else ()
        for name in (commit,) + parents:
            if not _COMMIT.fullmatch(name):
                raise TrackerValidationError(
                    f"the range transcript names {name!r}, which is not one "
                    "40-character lowercase object name")
        body = lines[1:]
        if not body:
            paths = ()
        elif body[0] == "" and len(body) > 1 and all(body[1:]):
            paths = tuple(body[1:])
        else:
            raise TrackerValidationError(
                f"the record for {commit} is neither a bare header nor a header "
                "followed by one empty line and one nonempty path per line")
        entries.append({"commit": commit, "parents": parents, "paths": paths})
    return tuple(entries)


def verify_source_range(repo, *, baseline: str, head: str, head_ref: str,
                        scopes, transcript: str) -> dict:
    """Prove one task's implementation range against its persisted baseline.

    WHAT IS ANCHORED AND WHAT IS ATTESTED ARE TWO DIFFERENT SENTENCES, and
    `_range_ends` above spells out both in full. In one line: the repository
    is established as a repository, the head is the tip THIS ref store holds
    for `head_ref` and the caller's `head` is refused if it disagrees, the
    baseline is the sha the reservation recorded and is re-derived nowhere,
    and no commit named in the transcript is proved to exist. The returned
    `proof_mode` says `attested` for exactly that reason.

    THE BASELINE IS THE ONE PERSISTED AT RESERVATION, for THE ATTEMPT BEING
    PROVED. `HEAD~1` silently truncates a multi-commit task to its last commit
    and every earlier commit escapes the scope check -- and after Task 7 there
    is a second way to get it wrong that is louder and worse: a resumed task
    carries TWO `baseline:` checkpoints with different shas, and proving attempt
    two against attempt one's baseline charges the task with every commit that
    landed in the target branch while it was BLOCKED. `reserved_baseline` is
    what makes that a lookup by attempt rather than a scan.
    """
    if not isinstance(scopes, (list, tuple)):
        raise TrackerValidationError(
            "a source range is proved against a list of typed write scopes; "
            f"got {type(scopes).__name__}. A bare string is the dangerous "
            "spelling: iterating one yields CHARACTERS, not scopes")
    scopes = tuple(scopes)
    if not scopes:
        raise TrackerValidationError(
            "a source range needs at least one approved write scope; with none "
            "declared there is nothing for a changed path to be inside, and "
            "'no scope' must never read as 'every scope'")
    for scope in scopes:
        _scope_parts(scope)                      # rejects untyped/unsafe scopes
    location, base, tip = _range_ends(repo, baseline, head, head_ref)
    printable = " ".join(_range_argv(location, base, tip)[0])
    if base == tip:
        raise TrackerValidationError(
            f"source range is empty: the head {tip} equals the recorded "
            "baseline, and a task that moved the branch nowhere has no "
            "implementation to prove")
    if not isinstance(transcript, str):
        raise TrackerValidationError(
            f"no range transcript was supplied for {base}..{tip}. This module "
            "never executes git, so the proof is the captured stdout of: "
            f"{printable} -- absent evidence is a refusal naming what is "
            "missing, never a weaker check passed silently")
    entries = _parse_range_transcript(transcript)
    if not entries:
        raise TrackerValidationError(
            f"the range transcript names no commit, so the head {tip} does not "
            f"descend the recorded baseline {base}; re-run {printable} if the "
            "transcript was lost rather than empty")
    for entry in entries:
        if not entry["parents"]:
            raise TrackerValidationError(
                f"{entry['commit']} is a root commit, so the recorded baseline "
                f"{base} is not an ancestor of the head {tip}; an unrelated "
                "history proves nothing about this task")
        if len(entry["parents"]) != 1:
            raise TrackerValidationError(
                f"the implementation range must be linear; {entry['commit']} "
                f"has {len(entry['parents'])} parents, and a merge belongs to "
                "integration rather than to one implementer's worktree")
    #: A COMMIT APPEARS ONCE, AND THE CHAIN WALK BELOW CANNOT SAY SO. Nothing
    #: in git forbids a commit being its own parent, so the three records
    #: `<C parent BASE> <TIP parent C> <TIP parent TIP>` chain from the
    #: baseline, end at the head and were ACCEPTED -- `commits` came back
    #: carrying the tip twice. `<A parent BASE> <B parent A> <A parent B>` is
    #: the same fault without the self-parenting and is the reason this is a
    #: distinctness check rather than a "never its own parent" check: the
    #: second shape has no self-parent anywhere. Task 10 compares the worker's
    #: `commits` list against this tuple and will read it as the range in
    #: order, so a repeat is a disagreement waiting to happen rather than a
    #: harmless echo.
    names = tuple(entry["commit"] for entry in entries)
    if len(set(names)) != len(names):
        repeated = tuple(sorted(
            name for name in set(names) if names.count(name) > 1))
        raise TrackerValidationError(
            f"the range transcript names {', '.join(repeated)} more than "
            "once; an implementation range is a chain of distinct commits, "
            "and a repeated record is a duplicated entry rather than a "
            "second commit")
    previous = base
    for entry in entries:
        if entry["parents"][0] != previous:
            if previous == base:
                raise TrackerValidationError(
                    f"the recorded baseline {base} is not an ancestor of "
                    f"{entry['commit']}, which names parent "
                    f"{entry['parents'][0]}; a transcript rooted anywhere else "
                    "is evidence about a different range")
            raise TrackerValidationError(
                f"the range transcript is not a chain: {entry['commit']} names "
                f"parent {entry['parents'][0]} where the commit before it is "
                f"{previous}")
        previous = entry["commit"]
    if previous != tip:
        raise TrackerValidationError(
            f"the range transcript ends at {previous}, not at the recorded "
            f"head {tip}; a range that stops short leaves its last commits "
            "outside every scope and range check")
    for entry in entries:
        if not entry["paths"]:
            raise TrackerValidationError(
                f"source range contains an empty commit: {entry['commit']} "
                "changed no repository path, and no diff is neither an "
                "artifact completion nor a reason to commit")
    changed = tuple(sorted(
        {path for entry in entries for path in entry["paths"]}))
    outside = tuple(
        path for path in changed
        if not any(_path_in_scope(path, scope) for scope in scopes))
    if outside:
        raise TrackerValidationError(
            f"source range changed paths outside its approved write scope "
            f"{scopes}: {', '.join(outside)}")
    return {
        "baseline": base,
        "head": tip,
        "commits": tuple(entry["commit"] for entry in entries),
        "changed_paths": changed,
        "proof_mode":
            f"{PROOF_ATTESTED}{_DIGEST_DELIMITER}{_digest(transcript)}",
    }


def reserved_baseline(row, *, attempt) -> str:
    """The baseline this task persisted FOR THIS ATTEMPT, or a stop.

    THE PRODUCES BLOCK NAMED THREE FUNCTIONS AND NONE OF THEM COULD REACH THIS
    FACT, which is the one the whole proof is anchored on. It is added rather
    than left to callers because Task 7 made the cell AMBIGUOUS: after a resume
    the history reads

        started:attempt-001,baseline:attempt-001@<a>,
        resumed:attempt-001->attempt-002@<decision>,baseline:attempt-002@<b>

    with `<a>` and `<b>` DIFFERENT, because `resume_task` re-derives the target
    tip rather than carrying the old one forward. "The first `baseline:`" and
    "the last `baseline:`" are both wrong for one of the two attempts, and
    reading the wrong one charges a task that was BLOCKED with every commit
    that landed in the target branch while it waited -- a loud failure on
    innocent work, which erodes trust in the gate faster than a silent pass
    does. So the lookup is BY ATTEMPT and the match is on the whole marker.

    NOT FOUND IS A STOP AND NEVER A FALLBACK. An artifact task records no
    baseline at all -- it produces no source range -- and the honest answer for
    it is "this attempt recorded none", stated with the attempt named, rather
    than the nearest baseline belonging to somebody else.

    The attempt goes through `_attempt_token`, the module's single conversion
    point, so "which attempt" is answered by the renderer that WRITES these
    markers and not by a second grammar beside it.
    """
    token = _attempt_token(attempt)
    if not isinstance(row, dict):
        raise TrackerValidationError(
            f"a reservation baseline is read off a task row; got "
            f"{type(row).__name__}")
    for key in ("id", "checkpoints"):
        if key not in row:
            raise TrackerValidationError(
                f"the task row has no {key!r} cell, so it is not a row this "
                "run wrote")
    if not _text(row["checkpoints"]):
        raise TrackerValidationError(
            f"task {row['id']!r} carries no checkpoint history, so it has "
            f"recorded no baseline for {token}")
    marker = f"{_BASELINE_CHECKPOINT}{token}{_CHECKPOINT_DELIMITERS[1]}"
    found = tuple(entry[len(marker):] for entry in _csv(row["checkpoints"])
                  if entry.startswith(marker))
    if len(found) != 1:
        raise TrackerValidationError(
            f"task {row['id']!r} records {len(found)} baselines for {token} and "
            "a range proof has exactly one; an artifact task records none, and "
            "two would make the anchor a choice rather than a fact")
    if not _COMMIT.fullmatch(found[0]):
        raise TrackerValidationError(
            f"task {row['id']!r} records {found[0]!r} as the baseline for "
            f"{token}, which is not one 40-character object name; a symbolic "
            "end resolves somewhere else tomorrow")
    return found[0]


# ---------------------------------------------------------------------------
# P04 Task 9: immutable worker-result publication.
#
# The one helper a worker may call. Publication is ATOMIC and NO-CLOBBER:
# republishing byte-identical content is an idempotent no-op, and any other
# content at the same path is conflicting evidence rather than an update.
# ---------------------------------------------------------------------------

#: THE TREE, AND IT IS A CROSS-PHASE CONTRACT rather than a local naming
#: choice. P06's ``owner_history`` scans ``<run_dir>/agent-output/**/*.md`` for
#: owners the tracker no longer names and decides master-reviewer independence
#: on what it finds; P07 publishes the same tree in ``SKILL.md`` as the run
#: layout a user reads. Pointed at a directory nobody writes, that scan
#: contributes the EMPTY SET and ``owner_history`` returns only the owners it
#: already had from tracker rows -- a fail-open in the one direction the check
#: exists to close, because a worker released after finishing a task can then
#: be drawn to review its own work. The name is therefore a constant P06 and
#: P07 CITE, exactly as ``_OWNER_LINE_PREFIX`` is the constant they cite for
#: the owner line, and for the identical reason: a second spelling of a
#: cross-phase contract is two answers to one question, and the one that goes
#: stale is silent.
AGENT_OUTPUT_DIRNAME = "agent-output"

#: The task-id grammar this task screens against is ``_TASK_ID``, stated once
#: beside the plan grammar that is now the first screen to apply it. It is
#: ``_PATH_SEGMENT`` -- P03's ``_OWNER``, aliased -- narrowed to what ``git
#: check-ref-format`` accepts, because a task id becomes both a directory here
#: and a branch component in a later phase.


def worker_result_path(run_dir, *, task_id, attempt) -> Path:
    """Where attempt ``attempt`` of ``task_id`` publishes its one result.

    THE MAP FROM (task, attempt) TO A PATH IS INJECTIVE, and that is the whole
    design constraint, because the file at the far end of it is an immutable
    record whose identity is the sha256 of its bytes. Two task ids that share a
    path produce one of two wrong answers: the second task to publish is
    refused as "conflicting evidence" about a record it never wrote, or -- if
    the two happened to render the same bytes -- accepted as an idempotent
    replay of one. Neither is recoverable from the file, because the file no
    longer says which task it belongs to.

    SO A TASK ID THAT IS NOT ONE PATH SEGMENT IS REFUSED, NOT MANGLED. A
    ``task_id.replace("/", "-")`` is the mangling, and it is not injective:
    ``T/1`` and ``T-1`` are two tasks and one directory. The refusal is loud,
    it happens before any write, and it names the characters.

    THE SAME SCREEN NOW RUNS AT PLAN IMPORT, and this one is defence in depth
    rather than the only line. It was written when ``_parse_task_metadata``
    and ``_validate_assignment`` held a task id to ``_TOKEN`` alone, which
    ADMITS ``/``, ``:``, ``@``, ``+`` and a trailing dot -- so a plan could
    legally declare an id no directory can hold, ``reserve_task`` would take a
    slot for it, and nothing could ever release that slot. Both of those
    screens now ask ``_TASK_ID``, so a legal plan cannot reach this refusal at
    all; that is the correct end state for a screen of this kind and not a
    reason to delete it, exactly as ``_require_regular_file``'s absence arm
    records.

    THE ATTEMPT IS SPELLED BY ``_attempt_token`` AND BY NOTHING ELSE. An
    ``f"attempt-{attempt}.md"`` written here is a second spelling of a
    conversion that documents itself as the single point of one, and the two
    disagree on every input -- ``attempt-1`` against ``attempt-001``. That is
    fault F6 arriving through arithmetic, in the name of the very file whose
    identity the comparison is about. ``_attempt_token`` is also the screen: it
    refuses zero, a negative, a bool and an attempt too wide to spell.

    ``_run_path`` RATHER THAN ``Path(run_dir)``: ``Path(5)`` raises
    ``TypeError``, which is outside ``TrackerError`` and escapes every handler
    a controller has written.
    """
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise TrackerValidationError(
            f"task id {task_id!r} cannot be one directory name: it must be an "
            f"alphanumeric then alphanumerics, dots, underscores and hyphens, "
            f"at most {_OWNER_MAX} characters, with no trailing dot, no '..' "
            "and no '.lock' ending. Mangling it into a legal name would map "
            "two task ids onto one immutable record")
    return (_run_path(run_dir) / AGENT_OUTPUT_DIRNAME / task_id
            / f"{_attempt_token(attempt)}.md")


def _published_result_bytes(path: Path):
    """The bytes already published at ``path``, or ``None`` if nothing is.

    ``_require_regular_file`` RATHER THAN ``path.exists()``, and the difference
    is a hang rather than a wrong answer. ``exists()`` and ``is_file()`` are
    both False for a DIRECTORY, a dangling symlink, a symlink LOOP and a FIFO,
    and false for a NUL-bearing name as well -- CPython swallows the
    ``ValueError``. Three of those five fail an open loudly; the FIFO does not.
    Opening one for reading BLOCKS until a writer arrives, and on a name under
    a run directory no writer is ever coming, so an unattended controller stops
    dead holding the run lock, with no diagnostic and no timeout. The shape is
    therefore asked before the open rather than discovered by it, through the
    module's one door.

    ``read_bytes`` RATHER THAN ``read_text(encoding="utf-8")``. A file at this
    name whose bytes are not valid UTF-8 raises ``UnicodeDecodeError`` out of
    the text reader -- a ``ValueError``, not a ``TrackerError`` -- so a
    controller branching on the family never sees it. Bytes are also the right
    comparison: the record's identity is the sha256 of its bytes, and two byte
    strings that decode to one string are still two records.

    THE ABSENCE SPLIT IS ``_require_regular_file``'s OWN, one level down.
    ``FileNotFoundError`` and ``NotADirectoryError`` are the two spellings of
    "not there" -- the second is what a read reports when a PARENT component is
    a regular file -- and the door already folds exactly those two into
    absence. Every other ``OSError`` is a name this run cannot establish
    anything about, and an unestablished name is never published over.
    """
    _require_regular_file(path, "a published worker result")
    try:
        return path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise TrackerValidationError(
            f"the worker result already at {str(path)!r} cannot be read "
            f"({type(exc).__name__}: {exc}), so whether this publication would "
            "be a replay or a second document under one identity is unknown -- "
            "and an immutable record is never written over an unknown one"
        ) from exc


def _citable_repo_relative(resolved_run: Path, root: Path, inside: str) -> str:
    """The repository-relative spelling of a published record, or a stop.

    WHAT THIS RETURNS IS WHAT A LATER PHASE MUST BE ABLE TO CITE, so it is
    screened against the grammar that will hold it rather than merely computed.
    ``_digest_reference`` is that grammar -- ``<repository-relative-path>``
    ``#sha256=<64 lowercase hex>`` -- and it puts the path through
    ``_safe_relative`` and refuses ``#`` inside it, because
    ``docs/a#sha256=<hex>.md#sha256=<hex>`` has two plausible readings and the
    module counts the delimiter once rather than picking a side. A run
    directory spelled with a ``#``, a ``,``, a glob character, a backslash or
    anything a tracker cell cannot carry therefore produces a record nothing
    can bind a digest to -- so it is refused BEFORE the record exists, rather
    than discovered by Task 10 after an immutable file is already on disk.

    THE ``,`` IS ``_safe_relative``'s AND IS NOT SPELLED AGAIN HERE, which is
    the difference between it and the ``#`` above. ``#`` is a delimiter of the
    REFERENCE and so is asked where the reference is assembled; ``,`` is the
    delimiter of the CELL, and every cell that holds a repository-relative path
    is read back with ``_csv``, so the bar belongs on the path grammar itself
    and is inherited here. It was not always: a run directory at ``runs/run,1``
    published without complaint, and the ``Result`` cell it produced split into
    two members -- so ``_member(identity, accepted)`` could never match and the
    documented "an exact replay is inert" contract RAISED, while the
    conflicting-evidence screen beside it became unreachable.

    IT IS THE RUN DIRECTORY THAT IS RESOLVED, AND THE RECORD'S OWN SEGMENTS
    ARE APPENDED LEXICALLY. Resolving the record's full path would follow a
    symlink at the record's own name and answer with what the link POINTS AT:
    a link to a file outside the repository would be reported as a record
    outside the repository, when the name this run publishes is plainly inside
    it, and a symlink LOOP at that name would be reported as an unspellable
    path rather than as the corruption it is. What a later phase cites is the
    NAME, and the name is ``<run>/agent-output/<task>/<attempt>.md``.
    ``inside`` is taken from the built path rather than reassembled here, so
    the layout has one statement -- ``worker_result_path``'s.

    THE ROOT IS THE ONE RECORDED AT INIT, read back through ``repo_root``. It
    is never derived from ``run_dir`` depth, which is the rule the whole phase
    is held to.
    """
    try:
        #: PATH DIVISION AND NOT AN f-STRING JOIN. ``Path.relative_to``
        #: answers ``.`` when the two are the same directory, so the string
        #: form produces ``./agent-output/...`` -- which ``_safe_relative``
        #: then refuses for carrying a ``.`` segment, reporting a record AT
        #: the repository root as an uncitable path. Division normalises
        #: that one case and changes nothing else.
        relative = (resolved_run.relative_to(root) / inside).as_posix()
    except ValueError as exc:
        raise TrackerValidationError(
            f"the directory {str(resolved_run)!r} is not inside the recorded "
            f"repository root {str(root)!r}, so a worker result published in "
            "it has no repository-relative spelling and no later phase could "
            "cite it") from exc
    if _DIGEST_DELIMITER[0] in relative:
        raise TrackerValidationError(
            f"the worker result path {relative!r} carries "
            f"{_DIGEST_DELIMITER[0]!r}, which is the delimiter of a bound "
            f"reference: {relative}{_DIGEST_DELIMITER}<digest> has two "
            "readings, and a reference whose path half is ambiguous binds a "
            "digest to whichever of the two the reader happened to take")
    try:
        _safe_relative(relative)
    except PlanMetadataError as exc:
        raise TrackerValidationError(
            f"the worker result path {relative!r} is not a repository-relative "
            f"path a later phase can cite or a tracker cell can hold: {exc}"
        ) from exc
    return relative


def publish_worker_result(run_dir, *, result: dict) -> str:
    """Publish one immutable attempt result; return its repository-relative path.

    THE ORDER IS THE CONTRACT. Everything that can refuse runs before anything
    is written, so a refusal leaves the run directory byte-identical: the
    result is rendered (which validates it), the name is built, the name is
    resolved, the run is validated, and the spelling a later phase will cite is
    screened. Only then is a byte written. ``validate_run`` LAST of the
    refusals and not first, because a run directory whose own name cannot be
    resolved must be told so -- reporting it as "missing progress.md", which is
    what ``validate_run`` says for a NUL-bearing path because ``is_file()``
    answers False for one, sends a reader to inspect a tracker that is fine.

    THE PRE-CHECK IS WHAT SEPARATES A REPLAY FROM CONFLICTING EVIDENCE.
    ``publish_immutable`` already refuses to clobber, and it already treats
    identical bytes as inert -- but it reports the conflict as a
    ``TrackerWriteError``, which is the family for "the write did not happen",
    and this one did not fail to write: it found a different answer already
    recorded under the same identity. That is a validation fact and it is
    raised as one. Reading first is also what keeps the FIFO out of
    ``_link_publish``'s own ``path.read_bytes()``, which runs under the run
    lock with nothing bounding it.

    THE DIGEST IS COMPARED AGAINST THE BYTES ON DISK, which is the only
    comparison that says anything. ``publish_immutable`` returns
    ``sha256(content)`` and its body is that expression, so checking its return
    value against ``sha256(content)`` compares a value with itself: a screen
    that cannot fire, under prose claiming the bytes on disk were checked. The
    other operand is the file. Both screens below are contract assertions
    across a phase boundary -- P02 owns the publisher and may change it -- in
    the same category as ``_screen_owner_line``, which the canonical re-render
    also dominates and which Task 4 kept for the same reason: the caller of
    this function is handed a path and a promise about what is at it.
    """
    content = render_worker_result(result)
    #: ``result[...]`` is safe only because the render above is total and has
    #: already refused a non-mapping, a missing key and a non-string id.
    path = worker_result_path(
        run_dir, task_id=result["task_id"], attempt=result["attempt"])
    home = _run_path(run_dir)
    try:
        resolved_run = home.resolve()
    except (ValueError, OSError, RuntimeError) as exc:
        #: A NUL raises ``ValueError`` and a lone surrogate
        #: ``UnicodeEncodeError`` -- a ``ValueError`` subclass -- and
        #: ``pathlib`` swallows neither here, while ``is_file()`` swallows both
        #: and answers "absent", which is how a NUL would otherwise reach
        #: ``validate_run`` and be reported as a missing tracker. A symlink
        #: loop raises ``RuntimeError``, which is not a ``TrackerError`` at all.
        raise TrackerValidationError(
            f"the run directory {str(home)!r} cannot be resolved "
            f"({type(exc).__name__}: {exc}); a run this module cannot locate "
            "is not a run known to be empty, and nothing is published into one"
        ) from exc
    #: ``home`` AND NOT ``run_dir``, and the difference is the whole of the
    #: family guarantee. ``validate_run`` deliberately does not coerce -- its
    #: first statement is ``run_dir / "progress.md"`` -- so handing it the raw
    #: argument raises ``TypeError`` for the one shape ``_run_path`` exists to
    #: normalise and ``worker_result_path`` declares legal: a ``str``. That is
    #: outside ``TrackerError``, it escapes every handler a controller has
    #: written, and it is the likeliest spelling a worker subprocess holds,
    #: out of argv or JSON. Normalising two lines above and then throwing the
    #: normalised value away is the "caller that had lost track of what it was
    #: holding" ``validate_run``'s docstring names.
    relative = _citable_repo_relative(
        resolved_run, _repo_dir(validate_run(home)),
        path.relative_to(home).as_posix())

    data = content.encode("utf-8")
    published = _published_result_bytes(path)
    if published is not None:
        if published != data:
            raise TrackerValidationError(
                f"a conflicting immutable result already exists at "
                f"{str(path)!r}: {len(published)} bytes are recorded under this "
                f"run, task and attempt and this publication renders "
                f"{len(data)}. A second answer under one identity is "
                "conflicting evidence to be reconciled, never an update -- "
                "which of the two is the real one is not a question a writer "
                "gets to settle by writing again")
        return relative

    digest = publish_immutable(path, content)
    written = _published_result_bytes(path)
    if written != data:
        raise TrackerValidationError(
            f"the bytes now at {str(path)!r} are not the bytes that were "
            "validated; the record a later phase will read is not the document "
            "this call screened, so the path returned would be a promise about "
            "a file nobody checked")
    if hashlib.sha256(written).hexdigest() != digest:
        raise TrackerValidationError(
            f"publish_immutable reported {digest!r} for {str(path)!r}, whose "
            f"bytes hash to {hashlib.sha256(written).hexdigest()!r}; the digest "
            "IS the record's identity, and one that does not hash the file "
            "fails at the phase that cites the record rather than at the one "
            "that wrote it")
    return relative


# ---------------------------------------------------------------------------
# P04 Task 10: controller-side result import -- faults F3, F4, F5 and F6.
#
# A WORKER SAYING DONE IS NOT COMPLETION EVIDENCE. All five statuses and both
# kinds undergo the same four-part identity check -- run, task, attempt, owner
# -- against the assignment THIS controller persisted. Routing is explicit and
# never inferred from the wording: ``NEEDS_CONTEXT`` and ``PLAN_CONFLICT`` park
# the attempt at ``[?]`` behind a QUORUM marker carrying a resolvable,
# digest-bound question record; ``BLOCKED`` parks it behind a HALT marker
# carrying the stated blocker.
#
# THE CONTROLLER RUNS THE COMMAND AND THE MODULE VALIDATES WHAT COMES BACK.
# ``verify_source_range``'s header defers "a worker who names commits that do
# not exist" to this task, and that deferral only pays off if the transcript
# the comparison rests on is the CONTROLLER'S. Three things had to exist for
# it, and none of them did when this block was first sketched: the call omitted
# ``transcript=`` entirely (a ``TypeError``, since the parameter has no
# default); nothing said where a transcript came from, so the only available
# one was the worker's -- and ``tuple(result["commits"]) != proof["commits"]``
# over the worker's own transcript compares the worker with itself, which is
# WORSE than no check because it reads as one; and ``task_branch`` was never
# bound anywhere in the phase plan.
#
# So: ``import_worker_result`` calls ``source_range_commands`` itself, hands
# the argv to a ``run_command`` CALLABLE THE CONTROLLER SUPPLIES, and passes
# the captured stdout as ``transcript``. ``subprocess`` is off this module's
# import list and stays off it; the capability arrives as an argument, which is
# what lets the AST screen keep the import out while the proof still rests on
# a command that really ran. The worker's document contributes ``head`` (a
# claim ``_range_ends`` checks against the ref store's tip) and ``commits`` (a
# claim the comparison checks). It contributes NO transcript and NO branch
# name: the worker-result grammar has fourteen fields and none is either.
#
# WHAT THIS STILL DOES NOT CLOSE, stated so Task 11 does not over-read it: a
# controller that fabricates the transcript defeats this and everything else,
# and neither task proves the BASELINE is a commit in the repository -- it is
# the sha ``reserve_task`` resolved at reservation and the target branch has
# moved on. Task 8's header says so and this one does not weaken it.
#
# FIVE THINGS THE BRIEF'S STEP-3 CODE GOT WRONG AGAINST THE COMMITTED MODULE,
# each corrected here and each pinned by a test:
#
# * ``_attempt_baseline`` is ``reserved_baseline``, already shipped by Task 8
#   with the resume ambiguity argued into its docstring. CONSUMED, never
#   re-spelled.
# * ``_approved_definition(run_dir, tracker, task_id)`` is ``(tracker,
#   task_id)``: Task 6 argued the ``run_dir`` out because no line of the body
#   reads it.
# * ``integration="-"`` on a completed source row is REFUSED by P02's
#   ``_validate_tasks``: the two legal values are an integration commit and
#   ``held``, because "deliberately deferred" and "never written down" are the
#   two states a resuming controller has to tell apart. ``held`` is what this
#   transition writes and Task 11 is what replaces it.
# * ``.is_file()`` on an artifact output is the predicate this build has ruled
#   against four times: it is False for a directory, a dangling link, a symlink
#   loop, a FIFO and a NUL-bearing name. THE PREDICATE DOES NOT HANG, and this
#   correction matters because the claim that it does has been repeated
#   forward: measured, ``is_file()`` on a FIFO answers False in 0.000s and
#   ``os.path.lexists`` answers True in 0.000s. ``stat`` never blocks. What
#   blocks for ever is the OPEN a later reader performs on the name the
#   predicate has just mis-classified as absent -- and under the run lock that
#   reader is an unattended controller with no diagnostic and no timeout. So
#   the defect ``is_file()`` introduces here is a WRONG ANSWER, and the hang is
#   what the wrong answer leads the next caller into.
#   ``_require_regular_file`` is the door, and it is the door because it
#   answers the shape question before anyone opens anything.
# * one command comparison over BOTH kinds cannot hold: an artifact task
#   declares no suite, so its approved tuple is empty, and
#   ``_parse_command_suite`` refuses an empty array -- no evidence record can
#   ever carry it, so every artifact import would have been impossible.
# ---------------------------------------------------------------------------

#: The PUBLIC names P05 and P06 cite for the two non-completion routes, and
#: they are ALIASES rather than a second typing of two words already in this
#: module. ``_ROUTE_QUORUM`` / ``_ROUTE_HALT`` are Task 4's route vocabulary
#: and ``_QUESTION_QUORUM_ARM`` / ``_QUESTION_HALT_ARM`` are the ``Question``
#: cell arms ``_validate_decision`` splits a resume grant on. A public constant
#: that drifted from the arm would bind a grant to nothing, in the one cell
#: that says what a task is blocked on.
QUORUM_ROUTE = _ROUTE_QUORUM
HALT_ROUTE = _ROUTE_HALT

#: ``task/<id>``, and it is DERIVED FROM THE EVIDENCE SUBJECT KIND rather than
#: typed. ``_validate_task_test_evidence`` requires a record whose ``subject``
#: is exactly this string, and ``_evidence_subject`` requires the half before
#: the slash to be one of ``EVIDENCE_SUBJECT_KINDS``. Spelling the prefix from
#: that tuple makes the branch name and the evidence subject ONE derivation, so
#: the range check and the evidence check cannot come to different conclusions
#: about which branch a task is on -- which is the whole reason ``head_ref``
#: exists.
TASK_BRANCH_PREFIX = f"{EVIDENCE_SUBJECT_KINDS[0]}/"

#: The checkpoint marker this transition writes for the range proof, and the
#: reason it is a checkpoint rather than a column. ``proof_mode`` is the one
#: fact the import learns that no existing cell holds: WHICH transcript proved
#: the range. ``## Tasks`` is P02 schema and its committed fixture is the
#: authority on the sixteen columns, so a seventeenth invented here would be a
#: column no validator of P02's knows about -- Task 8 and Task 9 both declined
#: to add one and this task declines too. ``Checkpoints`` is where per-attempt
#: facts already live, keyed by the attempt token exactly as ``started:``,
#: ``baseline:`` and ``resumed:`` are, and the proof is a per-attempt fact
#: anchored on the very ``baseline:`` marker beside it. ``Verification`` is the
#: other candidate and is the wrong one: that cell holds digest-bound PASS
#: DOCUMENTS a later phase resolves, and a proof mode is not a document.
_RANGE_CHECKPOINT = "range:"
_WORKER_CHECKPOINT = "worker:"
_COMPLETED_CHECKPOINT = "completed:"
_BLOCKED_CHECKPOINT = "blocked:"


def _task_branch(tracker: dict, task_id) -> str:
    """``task/<task_id>``, read out of the tracker and screened, or a stop.

    DERIVED, NEVER STORED, AND NEVER READ OUT OF THE RESULT. The worker-result
    grammar has no branch field; adding one would put the anchor of the range
    proof back on the worker's word, which is exactly what ``head_ref`` exists
    to prevent. If a future topology ever needs a name that is not derivable,
    it goes in a run field the CONTROLLER writes at reservation -- it never
    arrives in the result.

    THE ID COMES OFF THE ROW, not off the argument, so the branch is spelled
    from the controller's own record of the reservation. The spelling is then
    asserted against ``_TASK_ID`` -- the same grammar ``reserve_task`` used --
    because Task 9's fix round made this derivation TOTAL by refusing at
    reservation any id ``git check-ref-format`` rejects as a branch. That makes
    this arm defence in depth rather than the only line, and it is kept for
    ``worker_result_path``'s reason: a tracker row can still arrive from a
    resumed run whose plan an older build imported.
    """
    row = _task_row(tracker, task_id)
    identifier = row["id"]
    if not isinstance(identifier, str) or not _TASK_ID.fullmatch(identifier):
        raise TrackerValidationError(
            f"task id {identifier!r} cannot be spelled as the branch "
            f"{TASK_BRANCH_PREFIX}<id>: git refuses it as a reference "
            "component, so the range proof would have no head to resolve and "
            "the evidence record would name a subject nothing can be joined "
            "to. Mangling it into a legal name is not injective -- 'T/1' and "
            "'T-1' are two tasks and one branch")
    return f"{TASK_BRANCH_PREFIX}{identifier}"


def _range_transcript(run_command, commands) -> str:
    """Run the argv this module emitted; return the captured stdout RAW.

    THE ONE PLACE THE ARGV IS EXECUTED, so the emitted command and the executed
    command cannot drift: everything above builds exactly one ``commands``
    tuple, hands it here, and the string that comes back is the string
    ``verify_source_range`` is given.

    NO ``.strip()``. The leading NUL record separator and the trailing newline
    are BOTH load-bearing in the grammar ``_parse_range_transcript`` reads -- a
    transcript that does not begin at a separator is refused as not being the
    emitted command's output, and a record that is not newline-terminated is
    refused as truncated mid-record. Stripping either turns a valid transcript
    into a grammar refusal, which reads as a defect in the worker's range.

    THE CALLABLE IS THE CAPABILITY. ``subprocess`` is off this module's import
    list and stays off it, so a controller that wants a result imported hands
    over the ability to run one command. A failure inside that callable is NOT
    this module's exception family -- ``subprocess.run(check=True)`` raises
    ``CalledProcessError`` -- so it is caught and restated as what it means
    here: no transcript, naming the command that produced none. ``Exception``
    and not ``BaseException``: a ``KeyboardInterrupt`` is the operator, not a
    failed proof.

    AND THE ANSWER IS SCREENED FOR ITS TYPE. ``capture_output=True`` without
    ``text=True`` answers ``bytes``; passed on, it would be refused one call
    later with a diagnosis about a transcript rather than about the controller
    that produced it.
    """
    if not callable(run_command):
        raise TrackerValidationError(
            f"the range transcript is captured by a callable the controller "
            f"supplies; got {type(run_command).__name__} {run_command!r}, "
            "which is not callable. This module never executes git -- it emits "
            "the argv and validates the transcript -- so the ability to run "
            "one command is an argument, and a caller that has not supplied it "
            "cannot have a range proved")
    captured = []
    for argv in commands:
        printable = " ".join(argv)
        try:
            answer = run_command(tuple(argv))
        except TrackerError:
            raise
        except Exception as exc:
            raise TrackerValidationError(
                f"the controller could not run {printable} "
                f"({type(exc).__name__}: {exc}); a command that did not run "
                "produced no transcript, and absent evidence is a refusal "
                "naming what is missing rather than a weaker check passed "
                "silently") from exc
        if not isinstance(answer, str):
            raise TrackerValidationError(
                f"the controller answered {printable} with "
                f"{type(answer).__name__}; a range transcript is captured "
                "stdout, which is text. capture_output=True without text=True "
                "answers bytes, and a transcript this module cannot read is "
                "not one it can have checked")
        captured.append(answer)
    return "".join(captured)


def _imported_result_document(path: Path) -> tuple:
    """``(bytes, parsed result)`` for one published record, or a stop.

    ``_published_result_bytes`` IS THE DOOR, reused rather than re-spelled: it
    already asks the shape before the open (a FIFO under this name would block
    for ever, under the run lock), reads BYTES rather than text because the
    record's identity is the sha256 of its bytes, and splits "not there" from
    "there and unreadable".

    WHAT IS ADDED HERE IS THE TWO ANSWERS THAT DIFFER FOR AN IMPORT. Absence is
    a STOP -- a missing worker result is never evidence the work completed, and
    never grounds to repeat it, which is fault F7 one task early -- where for a
    publication it is the ordinary case. And corruption arrives from the door as
    ``QuorumSchemaInvalid``, which is a ``QuorumError`` and NOT a
    ``TrackerValidationError``; every test and every controller branching on
    the validation class would miss it, so it is restated in the family this
    transition promises.
    """
    try:
        content = _published_result_bytes(path)
    except QuorumError as exc:
        raise TrackerValidationError(
            f"the worker result at {str(path)!r} is a name this run cannot "
            f"read ({exc}); a directory, a dangling link, a symlink loop or a "
            "FIFO is corruption and never an absent result") from exc
    if content is None:
        raise TrackerValidationError(
            f"no worker result is published at {str(path)!r}; a result that is "
            "not there is not there -- it is never evidence that the work "
            "completed, and never grounds to repeat it")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrackerValidationError(
            f"the worker result at {str(path)!r} is not UTF-8 ({exc}); a record "
            "this module cannot read is not a record it can have checked, and "
            "UnicodeDecodeError is a ValueError from outside this family"
        ) from exc
    return content, parse_worker_result(text)


def _result_identity(result_path: Path, content: bytes, repo: Path) -> tuple:
    """``(<relative>#sha256=<digest>, <relative>)`` for one published record.

    THE IDENTITY IS WHAT THE ``Result`` CELL CARRIES AND WHAT A LATER PHASE
    CITES, so the path half is screened against the grammar that will hold it
    -- ``_digest_reference`` -- rather than merely computed.
    ``_citable_repo_relative`` is that screen, shared with
    ``publish_worker_result`` so the string this reads back is the string that
    function returned: two derivations of one spelling would disagree about a
    run directory with an unusual name, and the record's identity would then
    depend on which side of the boundary you asked.

    THE DIRECTORY IS RESOLVED AND THE RECORD'S OWN NAME IS APPENDED. Resolving
    the record itself would follow a symlink AT THE RECORD'S NAME and answer
    with what the link points at, so a link to a file outside the repository
    would be reported as a record outside the repository when the name this run
    published is plainly inside it -- and a symlink loop at that name would be
    reported as an unspellable path rather than as the corruption it is. What a
    later phase cites is the NAME.
    """
    if not result_path.name:
        raise TrackerValidationError(
            f"{str(result_path)!r} names no file, so there is no record for an "
            "identity to be about")
    try:
        directory = result_path.parent.resolve()
    except (ValueError, OSError, RuntimeError) as exc:
        #: A NUL raises ``ValueError``, a lone surrogate ``UnicodeEncodeError``
        #: and a symlink loop ``RuntimeError`` -- the last is not a
        #: ``TrackerError`` at all, and ``pathlib`` swallows none of the three
        #: here while ``is_file()`` swallows the first two and answers "absent".
        raise TrackerValidationError(
            f"the directory holding {str(result_path)!r} cannot be resolved "
            f"({type(exc).__name__}: {exc}); a record this module cannot locate "
            "is not a record known to be anywhere") from exc
    relative = _citable_repo_relative(directory, repo, result_path.name)
    return (f"{relative}{_DIGEST_DELIMITER}{hashlib.sha256(content).hexdigest()}",
            relative)


def _resolve_question_record(run_dir, repo_dir, reference: str) -> str:
    """The complete ``Question`` cell for the quorum arm, or a stop. Fault F5.

    ``quorum:<qid>@<path>#sha256=<digest>`` -- the qid for the binding, the
    digest-bound path for the audit trail. THE WHOLE ARM IS SPELLED HERE and
    nowhere else, because ``_validate_decision`` splits a resume grant on
    exactly this shape: it reads the qid out of the cell and refuses any
    decision whose id is not ``Q-<qid>``. Two spellings of the cell would be
    two answers to "what is this task blocked on" in the one cell that says so.

    THE QID IS DERIVED FROM THE RECORD'S OWN QUESTION AND AXIS, never read off
    the path it was cited at. ``_record_qid`` is the single statement of that
    derivation -- the same one ``open_quorum`` files a record under and
    ``_question_record`` re-derives -- and a re-ask derives a DIFFERENT qid
    through ``derive_reopen_qid``, which is what stops a stale answer resuming
    a re-asked block. The cited path is then required to be where this run
    files that qid, so a record answering under another question's identity is
    a stop rather than a cell whose grant binding is arithmetic on the wrong
    number.

    ONE SEARCH ROOT, AND THAT IS A NARROWING OF ``resolve_evidence``'S RULE
    RATHER THAN AN OVERSIGHT. Evidence may legitimately live under the run
    directory or under the repository root, so that resolver searches both in a
    pinned order. A question record may not: ``open_quorum`` writes exactly one,
    at ``<run>/quorum/<qid>/question.md``, and the comparison below is against
    that one name -- so a second root would be a place to put a copy that the
    binding then has to choose between.

    THE DIGEST IS CHECKED BEFORE THE RECORD IS PARSED, and a mismatch stops
    here rather than reading as "not the file I meant". One reference names one
    document; treating a mismatch as a miss is how whoever can write a second
    copy gets to choose which one a reader lands on.
    """
    relative, digest = _digest_reference(reference, field="question_record")
    candidate = _openable_path(repo_dir, field="repo_dir") / relative
    try:
        _require_regular_file(candidate, "a question record")
    except QuorumError as exc:
        raise TrackerValidationError(
            f"question record {reference!r} names {relative!r}, which this run "
            f"cannot read ({exc}); corruption is never absence") from exc
    try:
        content = candidate.read_bytes()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise TrackerValidationError(
            f"question record is missing: {reference!r} names {relative!r}, "
            "which is not there under the recorded repository root. A quorum "
            "raised against a record nobody wrote is a question no brain can "
            "be asked") from exc
    except OSError as exc:
        raise TrackerValidationError(
            f"question record {reference!r} names {relative!r}, which is a "
            f"regular file this run cannot read ({exc}); an unreadable record "
            "is corruption, never absence") from exc
    if hashlib.sha256(content).hexdigest() != digest:
        raise TrackerValidationError(
            f"question record digest does not match its content: {reference!r} "
            f"resolved to {relative!r}, whose sha256 is something else. An "
            "unbound path names a file whose contents may have changed since, "
            "which is the whole reason the reference carries a digest")
    try:
        qid = _record_qid(parse_question(content.decode("utf-8")))
    except (UnicodeDecodeError, QuorumError) as exc:
        raise TrackerValidationError(
            f"the question record at {relative!r} is not one this run can read "
            f"back ({type(exc).__name__}: {exc}); a block whose record cannot "
            "be parsed names no question and binds no grant") from exc
    filed = _run_path(run_dir) / _QUORUM_DIRNAME / qid / _QUESTION_FILE
    try:
        misfiled = filed.resolve() != candidate.resolve()
    except (ValueError, OSError, RuntimeError) as exc:
        raise TrackerValidationError(
            f"the question record cited at {relative!r} cannot be compared "
            f"with {str(filed)!r} ({type(exc).__name__}: {exc})") from exc
    if misfiled:
        raise TrackerValidationError(
            f"the question record cited at {relative!r} derives qid {qid!r}, "
            f"which this run files at {str(filed)!r}. A record answering under "
            "another question's identity produces a block whose grant binding "
            "-- 'Q-' followed by the qid -- is arithmetic on the wrong number, "
            "and every response and decision keyed by it would look "
            "well-formed")
    return (f"{_QUESTION_QUORUM_ARM}{qid}@{relative}"
            f"{_DIGEST_DELIMITER}{digest}")


def _validate_task_test_evidence(run_dir, tracker: dict, result: dict,
                                 definition: dict, code_state: str,
                                 subject: str) -> None:
    """Exactly one digest-bound ``task-test`` PASS record, bound to this work.

    FOUR FACTS PICK THE RECORD OUT and all four are identity: the purpose, the
    run, the subject -- which is ``_task_branch``'s single derivation, so the
    evidence check and the range check cannot disagree about which branch this
    is -- and the attempt token. EXACTLY ONE, because two records for one
    attempt are two answers to "did the suite pass" and nothing here would get
    to choose; zero is a completion with nothing to inspect.

    THEN TWO FACTS BIND IT TO THIS RESULT. The ``code_state`` is the head the
    range proof established for a source task, and the target tip for an
    artifact task -- a record bound to an earlier commit proves the suite
    passed against code this result is not about. And the command tuple is the
    plan's, on BOTH sides: the record must name it, and so must the result,
    because checking only the record would let a worker claim it ran one suite
    while citing a record that proves another.

    THE COMMAND RULE IS KIND-DEPENDENT AND THE BRIEF'S SINGLE COMPARISON COULD
    NOT HOLD. An artifact task declares no verification suite, so its approved
    tuple is EMPTY -- and ``_parse_command_suite`` refuses an empty array, so
    no evidence record can ever carry it. A record-side comparison against ``()``
    is therefore unsatisfiable and would have made every artifact import
    impossible. What IS available for an artifact is the result side: the plan
    approved no suite, so a result naming one has run something nobody approved.
    """
    records = [resolve_evidence(run_dir, _repo_dir(tracker), reference)
               for reference in result["evidence"]]
    matching = [record for record in records
                if record["purpose"] == EVIDENCE_PURPOSES[0]
                and record["run_id"] == result["run_id"]
                and record["subject"] == subject
                and record["attempt"] == _attempt_token(result["attempt"])]
    if len(matching) != 1:
        raise TrackerValidationError(
            f"a completed task needs exactly one digest-bound "
            f"{EVIDENCE_PURPOSES[0]} PASS record naming run "
            f"{result['run_id']!r}, subject {subject!r} and attempt "
            f"{_attempt_token(result['attempt'])}; this result resolves "
            f"{len(matching)} of them out of {len(records)} evidence "
            "references, and a claim with nothing to check can only be "
            "believed")
    record = matching[0]
    if record["code_state"] != code_state:
        raise TrackerValidationError(
            f"task-test evidence is bound to a different code state "
            f"({record['code_state']}) than the result it accompanies "
            f"({code_state}); a suite that passed against other code has not "
            "been run against this one")
    if tuple(result["tests"]) != definition["commands"]:
        raise TrackerValidationError(
            f"the result names {list(result['tests'])!r} where the approved "
            f"task suite is {list(definition['commands'])!r}; a completion must "
            "name the exact ordered approved task suite, and an artifact task "
            "whose plan approved none must name none")
    if definition["commands"] and record["commands"] != definition["commands"]:
        raise TrackerValidationError(
            f"task-test evidence names {list(record['commands'])!r} where the "
            f"approved task suite is {list(definition['commands'])!r}; the "
            "record must name the exact ordered approved task suite, or it is "
            "a PASS for something nobody approved")


def _require_artifact_outputs(repo, outputs) -> None:
    """Every approved output of an artifact task is a regular file on disk.

    ``_require_regular_file`` AND NOT ``.is_file()``. The brief wrote ``if not
    (repo / output).is_file()``, which answers False for a directory, a
    dangling symlink, a symlink loop, a FIFO and a NUL-bearing name -- five
    names that exist, reported as "the output is missing". Four of those are
    corruption and deserve to be said so; the FIFO is worse than a wrong
    diagnosis, because a later reader of that path BLOCKS on the open under
    the run lock with no writer coming.

    SO ABSENCE IS ASKED SEPARATELY, after the door. The door deliberately does
    not answer absence -- every caller decides what a missing name means for
    it -- and here it means the artifact task produced nothing, which is a
    completion claim with no document behind it.

    A FUNCTION RATHER THAN FOUR LINES INSIDE ``mutate``. The door's callers
    are enumerated from the module's syntax tree by ENCLOSING FUNCTION NAME,
    and ``mutate`` is the name every transition gives its closure -- a door
    call there would enter that roster as a name eleven functions share and
    could not be driven on its own.
    """
    for output in outputs:
        target = _openable_path(repo, field="repo_dir") / output
        try:
            _require_regular_file(target, "an approved artifact output")
        except QuorumError as exc:
            raise TrackerValidationError(
                f"the approved artifact output {output} is a name this run "
                f"cannot read ({exc}); a directory, a dangling link, a symlink "
                "loop or a FIFO is corruption and never a produced document"
            ) from exc
        if not os.path.lexists(target):
            raise TrackerValidationError(
                f"the approved artifact output {output} is not on disk; an "
                "artifact task is proved by its documents existing, so a "
                "completion naming one that does not has produced nothing")

def import_worker_result(run_dir, *, result_path, run_command) -> dict:
    """Validate one immutable result against its active assignment; import once.

    ``run_command`` IS REQUIRED AND IS THE CONTROLLER'S CAPABILITY. The module
    never executes git; it emits the argv and validates the transcript. Because
    this transition is itself inside the module, the execution arrives as a
    callable rather than as an import, and the AST screen keeps ``subprocess``
    out while the proof still rests on a command that really ran. REQUIRED
    rather than defaulted, for the rule this build pays for elsewhere: a
    default is a capability nobody declared, and the branch that discovers it
    missing is reached only AFTER the identity checks have passed -- so a
    controller without it would learn so at the end of a successful-looking
    import rather than at the call. A quorum-raising or blocked result never
    runs it, and is still required to declare that its caller could.

    THE DIGEST IS PART OF THE TRANSITION ID, and that is load-bearing rather
    than decorative. ``locked_tracker_update`` recognises a replay by comparing
    ``transition_id`` against ``last_transition`` and returns current state
    WITHOUT CALLING ``mutate``. Keyed on task and attempt alone, a second
    import of a document whose bytes had been edited since would be recognised
    as a replay and silently accepted -- the conflicting-evidence screen inside
    ``mutate`` would be unreachable. Keyed on the content, the same document
    replays and a different one is examined.

    THE FILE IS READ TWICE ON PURPOSE. The pre-lock read builds the replay key;
    the read inside ``mutate`` is the one that is validated and recorded,
    because anything read before the lock is stale by definition. If the two
    disagree the key names content that was not applied, which is harmless:
    what the tracker records is what was read under the lock.
    """
    home = _run_path(run_dir)
    path = _openable_path(result_path, field="result_path")
    if not callable(run_command):
        raise TrackerValidationError(
            f"import_worker_result needs the controller's command runner; got "
            f"{type(run_command).__name__} {run_command!r}, which is not "
            "callable. This module emits the argv that proves a source range "
            "and never runs one, so the ability to run it is an argument -- "
            "and it is asked for before the lock, because a caller that cannot "
            "supply it has not failed a check, it has called wrongly")
    content, published = _imported_result_document(path)
    transition = (f"import-{published['task_id']}-"
                  f"{_attempt_token(published['attempt'])}-"
                  f"{hashlib.sha256(content).hexdigest()}")

    def mutate(tracker: dict) -> dict:
        repo = _repo_dir(tracker)
        current, result = _imported_result_document(path)
        identity, relative = _result_identity(path, current, repo)
        token = _attempt_token(result["attempt"])
        row = _task_row(tracker, result["task_id"])
        accepted = _csv(row["result"])

        #: AN EXACT REPLAY IS INERT, and it is the second line rather than the
        #: first: the replay key above settles only the MOST RECENT transition,
        #: so once anything else has landed this is what recognises the same
        #: document arriving twice.
        if _member(identity, accepted):
            return tracker
        if any(entry.split(_DIGEST_DELIMITER, 1)[0] == relative
               for entry in accepted):
            raise TrackerValidationError(
                f"an accepted result path now carries conflicting content: "
                f"{relative!r} is already recorded against task "
                f"{result['task_id']} under a different digest. A second answer "
                "under one identity is evidence to be reconciled, never an "
                "update -- which of the two is the real one is not a question "
                "a writer settles by writing again")
        if result["run_id"] != _run_field(tracker, "run_id"):
            raise TrackerValidationError(
                f"result run identity {result['run_id']!r} does not match this "
                f"tracker's {_run_field(tracker, 'run_id')!r}; a result from "
                "another run is another run's evidence")
        if row["state"] != _TASK_STATES[1] or row["attempt"] != token:
            raise TrackerValidationError(
                f"result attempt {token} is not the current active attempt of "
                f"task {result['task_id']}, which is {row['state']} at "
                f"{row['attempt']!r}; a result for an attempt the controller is "
                "not waiting on is one nobody dispatched")
        if result["owner"] != row["owner"]:
            raise TrackerValidationError(
                f"result owner {result['owner']!r} does not match the "
                f"controller-assigned owner {row['owner']!r}; the assignment is "
                "what says whose work this is, and it is the controller's")
        definition = _approved_definition(tracker, row["id"])
        if result["kind"] != row["kind"] or result["kind"] != definition["kind"]:
            raise TrackerValidationError(
                f"result kind {result['kind']!r} does not match the approved "
                f"plan ({definition['kind']!r}) or the task row "
                f"({row['kind']!r}); a worker cannot change what kind of task "
                "it was given because its implementation happened to produce "
                "no diff")

        updated = dict(row)
        updated["result"] = _append_history(row["result"], identity)
        for checkpoint in result[_WORKER_CHECKPOINTS]:
            entry = (f"{_WORKER_CHECKPOINT}{token}:{checkpoint['id']}:"
                     f"{checkpoint['status']}@{checkpoint['evidence']}")
            #: THE READER IS ASKED WHETHER THIS ENTRY SPENDS AN ATTEMPT, and
            #: it is asked rather than a character list written down, for
            #: ``_splits_the_section``'s reason one layer up.
            #:
            #: This entry is assembled from ``_CHECKPOINT_DELIMITERS`` and
            #: ``_recorded_attempts`` RE-SPLITS it on exactly those, so every
            #: delimiter the assembly uses is one the worker's own
            #: ``evidence`` reference can spell again. ``_safe_relative`` bars
            #: the CELL's delimiters -- a path may not re-column the list --
            #: but ``:`` and ``@`` are ordinary path characters that a scope
            #: path is explicitly allowed to carry, so the ENTRY's delimiters
            #: cannot be barred there without narrowing the path grammar for
            #: everyone. Measured: a checkpoint whose evidence is published at
            #: ``evidence/a@attempt-002@b.md`` imports at ``[x]`` and
            #: ``_recorded_attempts`` then reports ``attempt-002`` as spent, so
            #: ``_require_fresh_attempt`` refuses that resume for ever. A
            #: worker blocking itself could pick the tokens it would never be
            #: allowed to retry on -- a durable denial written by the party
            #: this whole transition exists to distrust.
            #:
            #: The screen is therefore the READER's own answer over the entry
            #: alone: the only attempt an imported checkpoint may name is the
            #: one the controller is importing. Asking the reader means a
            #: delimiter added to ``_CHECKPOINT_DELIMITERS`` tomorrow is
            #: covered without this line being touched, and means the screen
            #: cannot drift from the scan it is protecting.
            spent = _recorded_attempts(
                {"id": row["id"], "attempt": token, "checkpoints": entry})
            if spent != {token}:
                raise TrackerValidationError(
                    f"checkpoint {checkpoint['id']!r} of task "
                    f"{result['task_id']} names "
                    f"{sorted(spent - {token})!r} where only {token} belongs: "
                    "an imported checkpoint is appended to the controller's "
                    f"{_WORKER_CHECKPOINT.rstrip(':')!r} history, which "
                    "_recorded_attempts re-splits on the same delimiters this "
                    "entry is built from -- so a reference spelling one of "
                    "them would SPEND an attempt this task has not had, and no "
                    "resume to it could ever be granted again")
            updated["checkpoints"] = _append_history(
                updated["checkpoints"], entry)

        if _member(result["status"], COMPLETION_STATUSES):
            #: ``head_ref`` IS DERIVED BY THE CONTROLLER and the evidence
            #: subject is the same string, so the two checks below cannot come
            #: to different conclusions about which branch this task is on.
            branch = _task_branch(tracker, row["id"])
            if result["kind"] == TASK_KINDS[0]:
                baseline = reserved_baseline(row, attempt=result["attempt"])
                #: THE CONTROLLER RUNS THE COMMAND. ``transcript`` is the
                #: stdout captured from the argv THIS MODULE emitted; handing
                #: the worker's own transcript here would make the ``commits``
                #: comparison below compare the worker with itself.
                transcript = _range_transcript(
                    run_command,
                    source_range_commands(repo, baseline=baseline,
                                          head=result["source_ref"],
                                          head_ref=branch))
                proof = verify_source_range(
                    repo, baseline=baseline,
                    head=result["source_ref"],   # a CLAIM, checked at the tip
                    head_ref=branch,             # NOT from ``result``
                    scopes=definition["write_scope"],
                    transcript=transcript)
                #: WORKER-CLAIM AGAINST CONTROLLER-EVIDENCE. This is the line
                #: Task 8's header defers "names commits that do not exist" to,
                #: and it holds only because ``proof`` came from the transcript
                #: above rather than from the worker's document.
                if tuple(result["commits"]) != proof["commits"]:
                    raise TrackerValidationError(
                        "implementation commits must equal the complete "
                        "ordered baseline-to-source range: the result names "
                        f"{list(result['commits'])!r} and the transcript this "
                        f"controller captured names {list(proof['commits'])!r}")
                _validate_task_test_evidence(
                    home, tracker, result, definition, proof["head"], branch)
                updated.update(source_ref=proof["head"],
                               commits=",".join(proof["commits"]),
                               artifacts=_ABSENT_CELL,
                               integration=_INTEGRATION_HELD)
                updated["checkpoints"] = _append_history(
                    updated["checkpoints"],
                    f"{_RANGE_CHECKPOINT}{token}"
                    f"{_CHECKPOINT_DELIMITERS[1]}{proof['proof_mode']}")
            else:
                if tuple(result["artifacts"]) != definition["outputs"]:
                    raise TrackerValidationError(
                        f"artifact result names {list(result['artifacts'])!r} "
                        f"and the plan approves the exact approved outputs "
                        f"{list(definition['outputs'])!r}; an artifact task is "
                        "proved by the documents it was approved to produce")
                _require_artifact_outputs(repo, result["artifacts"])
                _validate_task_test_evidence(
                    home, tracker, result, definition,
                    _resolved_commit(repo, _run_field(tracker, "target_branch")),
                    branch)
                updated.update(source_ref=_ABSENT_CELL, commits=_ABSENT_CELL,
                               artifacts=",".join(result["artifacts"]),
                               integration=_INTEGRATION_NA)
            #: ``Verification`` HOLDS THE DOCUMENTS, which is what
            #: ``_validate_tasks`` means by "its verification evidence": the
            #: digest-bound typed PASS records a later phase resolves. The
            #: command tuple is already inside those records, so writing it
            #: here instead would be a copy nobody can resolve to a file.
            updated["verification"] = _append_history(
                row["verification"], ",".join(result["evidence"]))
            updated["state"] = _TASK_STATES[3]
            updated["checkpoints"] = _append_history(
                updated["checkpoints"], f"{_COMPLETED_CHECKPOINT}{token}")
        else:
            #: THE MARKER IS READ BY THE CONTROLLER AND NEVER INFERRED FROM THE
            #: WORDING. ``_validate_result_route`` has already refused a quorum
            #: status with no question record and a halt with no reason, so the
            #: field each arm reads is present by construction.
            if _member(result["status"], QUORUM_STATUSES):
                marker = _resolve_question_record(
                    home, repo, result["question_record"])
            else:
                marker = f"{_QUESTION_HALT_ARM}{result['blocking_reason']}"
            updated["state"] = _TASK_STATES[2]
            updated["question"] = marker
            #: THE CHECKPOINT NAMES THE BLOCK, AND A BARE ``blocked:<attempt>``
            #: names only that there was one. ``Question`` holds ONE cell and
            #: the next block OVERWRITES it, while ``Checkpoints`` is
            #: append-only -- so a bare marker loses the first question the
            #: moment a resumed task blocks a second time, and the audit
            #: pointer this checkpoint exists to be is then a pointer to
            #: nothing. The committed fixture (``valid-progress.md``) and the
            #: predecessor -- which both WRITES this shape and VALIDATES it,
            #: ``pipeline_state.py:528-531`` -- carry the ``@`` payload, and
            #: this module wrote the bare form against both.
            #:
            #: SCREENED AS A LIST MEMBER, because ``Checkpoints`` is
            #: comma-separated and ``_table_safe``'s own rule is that "the bar
            #: goes on the writer that knows the cell is list-valued". The
            #: quorum arm is comma-free by construction -- ``_safe_relative``
            #: bars the cell's delimiters in the path and the qid is hex -- but
            #: ``blocking_reason`` is free text a human reads, and a comma in
            #: it would append TWO history members, silently and still valid.
            updated["checkpoints"] = _append_history(
                updated["checkpoints"],
                f"{_BLOCKED_CHECKPOINT}{token}{_CHECKPOINT_DELIMITERS[1]}"
                + _table_safe(marker, field="the blocked checkpoint's question",
                              list_valued=True))
        return _replace_task(tracker, updated)

    return locked_tracker_update(home, transition_id=transition, mutate=mutate)


# ---------------------------------------------------------------------------
# P04 Task 11: integration -- faults F9 and F10.
#
# One worktree per concurrently dispatched implementer, merged ``--no-ff`` in
# task order. ``--no-ff`` is LOAD-BEARING: a fast-forward collapses the merge
# commit and with it the boundary clause 2 of the ancestry predicate checks. A
# conflict is a HARD STOP, because under typed write-scope validation a
# conflict should be impossible and is therefore evidence that a scope
# declaration was wrong.
#
# THE BRIEF FOR THIS TASK NAMED SIX CALLS THAT CANNOT RUN -- ``_git`` three
# times and ``_git_out`` three times, both ``subprocess.run`` wrappers -- and
# consumed a seventh name, ``_commit_parents``, that would have to read a
# commit object. ``subprocess`` is refused by name, the ``os`` command family
# is refused by an AST screen that enumerates it from ``dir(os)``, and ``zlib``
# is off the import list, so no object is ever decompressed. The shape is
# therefore the one Tasks 8 and 10 built and the master plan's quorum ruled:
# THE MODULE EMITS THE EXACT ARGV, THE CONTROLLER EXECUTES IT, AND THE MODULE
# VALIDATES THE TRANSCRIPT.
#
# THREE OF THE BRIEF'S GIT CALLS NEEDED NO GIT AT ALL, and moving them off it
# makes each answer strictly stronger rather than merely cheaper:
#
#   * ``MERGE_HEAD`` is already in ``_PSEUDO_REFS`` and the ref-store reader
#     answers it today, so "is this tree mid-merge" is a file this module
#     reads itself -- no controller, no transcript, nothing to fabricate.
#   * THE COLLIDING TASK IS THE ONE WHOSE DECLARED SCOPE CLAIMS THE CONFLICTED
#     PATH. The brief reached for ``git show --name-only`` over each recorded
#     commit, which answers "who touched it"; the message's whole claim is that
#     a SCOPE DECLARATION was wrong, and ``_path_in_scope`` answers exactly
#     that question against the approved plan.
#   * "the merge commit is an ancestor of the target branch" becomes
#     ``merge == _resolved_commit(repo, target_branch)`` read off the ref
#     store. That is DERIVED rather than attested, and it is strictly stronger
#     than the ancestry it replaces -- every commit equal to the tip is an
#     ancestor of it and not conversely. The walk is kept only as the fallback
#     for the case the equality cannot cover: the tip has moved on because a
#     later task integrated first.
#
# AND ``merge --abort`` MUST NOT RETURN. The module never writes to the user's
# repository; it raises the hard stop and NAMES the abort as the controller's
# next action. Running it here would be this module taking a write it has no
# authority for, in the one situation where the evidence most needs preserving.
# ---------------------------------------------------------------------------

#: ``MERGE_HEAD``, ALIASED out of the pseudo-ref tuple the ref-store reader
#: already searches rather than re-typed. A second spelling would be a second
#: answer to "which name says a merge is in progress", and the one that goes
#: stale is silent.
_MERGE_HEAD = _PSEUDO_REFS[3]

#: A ``--no-ff`` merge has EXACTLY two parents. One is a fast-forward, which is
#: fault F10; three or more is an octopus, which merges several tasks into one
#: commit and destroys the per-task boundary just as thoroughly.
_MERGE_PARENTS = 2

#: ``<gitdir>/info/grafts``. Read by this module rather than pinned on the
#: command line, and the reason is measured rather than assumed -- see
#: ``_graft_screen``.
_GRAFT_DIRNAME = "info"
_GRAFT_FILENAME = "grafts"

#: The checkpoint this transition writes, keyed by the attempt token exactly as
#: ``started:``, ``baseline:``, ``range:`` and ``completed:`` are. It is NOT
#: written to ``Verification``: that cell holds digest-bound typed PASS
#: DOCUMENTS a later phase resolves with ``resolve_evidence``, and an
#: ``integrated:`` marker is not a document -- writing it there would put an
#: entry nothing can resolve to a file in the one cell whose whole contract is
#: that every entry resolves. The ``Integration`` column already carries the
#: commit; the checkpoint carries WHICH ATTEMPT integrated it, which no column
#: holds.
_INTEGRATED_CHECKPOINT = "integrated:"

#: The two words the hard stop is recognised by. Spelled as constants because
#: the controller branches on the first and performs the second, and a message
#: is the only channel this module has to either.
_HARD_STOP = "HARD STOP"
_ABORT_ACTION = "git merge --abort"


def _integration_pins(location: str) -> tuple:
    """The pinned ``git`` prefix every command in this block is built on.

    A PIN IS ONLY A PIN IF IT CANNOT BE UNDONE FROM INSIDE THE REPOSITORY, and
    each of these was measured on this machine's git (2.39.5) against a real
    repository rather than read off documentation.

    ``-c core.useReplaceRefs=false`` IS THE LOAD-BEARING ONE HERE, and the
    hazard it closes is fault F10 itself rather than a path-hiding bypass.
    Measured: take an ordinary fast-forward commit with ONE parent, build a
    decoy with ``git commit-tree`` carrying the same tree, the same first
    parent and the TASK BRANCH TIP as a second parent, and ``git replace -f``
    the real commit with it. ``%P`` then prints two parents whose second is
    exactly the tip clause 2 looks for -- a fast-forward presented as a
    ``--no-ff`` merge, with no config edit and no object forgery, using
    ordinary porcelain in a repository the worker owns. The reverse also
    measured: replacing a real merge with a single-parent decoy hides the
    second parent. ``--no-replace-objects`` ALONE IS DEFEATED by
    ``core.useReplaceRefs = true`` in the repository's own config, and the
    ``-c`` is the highest-precedence source that no file can reach past --
    exactly as Task 8 measured for the path list. NEITHER TOKEN IS REDUNDANT.

    ``-c core.commitGraph=false`` is added HERE and is not in Task 8's argv.
    The commit-graph is a cache of the parent and reachability data these two
    commands are entirely about, it is an unsigned file in
    ``.git/objects/info/`` that the worker can write, and git does not verify
    it before trusting it.

    THE WITNESS IS CONSTRUCTED, and it took the third construction rather than
    the first. Re-measured on git 2.39.5: git declines to write a graph while
    ``.git/info/grafts`` is in effect (rc=0, NO file written), but under a
    REPLACE REF it writes one happily (rc=0, file present) that records the
    REAL parents. So neither borrowed construction yields a forgery -- and an
    earlier revision of this paragraph claimed the replace-refs half as
    measured when it does not reproduce, which is ``8a0a0da``'s defect (a
    config measured against a repository that cannot trigger it) arriving in a
    docstring instead of in a fixture.

    WHAT DOES FORGE ONE is the property the sentence above actually asserts:
    the file is unsigned and unverified, so it is EDITED rather than coaxed out
    of git. One 4-byte field -- the second-parent slot of a fast-forward
    commit's ``CDAT`` record, set from ``0x70000000`` ("no second parent") to
    the task branch tip's index -- makes ``%P`` print fault F10 exactly: a
    one-parent commit presented as a ``--no-ff`` merge whose second parent is
    the tip clause 2 looks for, with no object written and no config touched.
    ``git commit-graph verify`` rejects the file afterwards; ``git log`` never
    asks it to. The pin restores the real single parent, and
    ``test_a_forged_commit_graph_invents_a_second_parent_and_the_pin_kills_it``
    is the witness this paragraph used to say did not exist.

    ``--no-show-signature`` is added HERE for a hazard that IS witnessed.
    Measured: with a commit carrying a ``gpgsig`` header and
    ``log.showSignature = true`` in the repository's own config, gpg's
    verification text is written to STDOUT, ahead of the record separator, and
    lands inside the transcript this module parses. It is a config file, so a
    command-line flag outranks it. (Task 8's ``_range_argv`` had the same
    exposure and failed CLOSED there -- the injected lines arrive where a path
    list is read, so they are refused as out-of-scope paths -- but the
    diagnosis blamed the worker's range for the repository's config. It now
    carries the same token; ``PathSpellingConfigTests`` measures it.)

    ``-c core.quotePath=true`` pins git's OWN default so a non-ASCII path is
    C-quoted rather than raw. It keeps the transcript pure ASCII and therefore
    decodable by whatever captured it, and a C-quoted path begins with ``"``,
    which no write scope claims -- so it fails closed in the direction this
    build already accepted for Task 8. ``--no-color`` pins the same property
    against ``color.ui``.

    WHAT NO ARGV CAN PIN, MEASURED AND REPORTED RATHER THAN ASSUMED:
    ``.git/info/grafts``. It rewrites ``%P`` outright -- the same forged second
    parent as above, with no object written at all -- and on git 2.39.5
    ``core.graftFile`` is INERT from a config file AND from a ``-c``; only the
    ``GIT_GRAFT_FILE`` environment variable turns it off, and this module emits
    argv, never an environment. So the graft file is screened as a FILE, by
    ``_graft_screen`` below, which is a read this module already performs for
    ``packed-refs`` and is beyond the reach of anything written inside the
    repository.
    """
    return (
        "git", "--no-replace-objects", "-C", location,
        "-c", "core.quotePath=true",
        "-c", "core.useReplaceRefs=false",
        "-c", "core.commitGraph=false",
    )


def _integration_end(value, *, field: str) -> str:
    """One end of an integration command, as a 40-character object name.

    EVERY END OF EVERY COMMAND IN THIS BLOCK IS AN OBJECT NAME BEFORE IT IS AN
    ARGV ELEMENT. A symbolic end resolves somewhere else tomorrow, and the
    caller has already resolved each of these through ``_resolved_commit``; the
    screen is what makes that a property of the emitted command rather than a
    convention its callers happen to follow.
    """
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise TrackerValidationError(
            f"the integration {field} {value!r} is not one 40-character "
            "lowercase object name; the emitted command names immutable ends "
            "only, because a name that resolves elsewhere tomorrow proves "
            "nothing about the merge that happened today")
    return value


def merge_parents_commands(repo, *, merge_commit: str) -> tuple:
    """The exact command whose output names one merge commit's parents.

    ``--no-walk`` rather than ``-1``: one commit, named, with no history walk
    behind it, so nothing about the surrounding graph can change which record
    comes back. The format is ``_RANGE_FORMAT`` -- the SAME ``%x00%H %P`` Task
    8 emits -- so the one transcript grammar in this module reads both, and a
    record with no paths is already the shape ``_parse_range_transcript``
    accepts for a commit that changed nothing.
    """
    location = _repo_argument(repo)
    return ((
        *_integration_pins(location), "log", "--no-walk",
        "--no-show-signature", "--no-color", _RANGE_FORMAT,
        _integration_end(merge_commit, field="merge commit"), "--",
    ),)


def integration_range_commands(repo, *, first_parent: str,
                               second_parent: str) -> tuple:
    """The exact command whose output is one merge's second-parent commit set.

    ``<first parent>..<second parent>``, SPELLED WITH THE RESOLVED PARENTS
    RATHER THAN WITH ``<merge>^1..<merge>^2``. The caret spelling is what the
    master plan wrote and it is one round trip shorter, but it is not TOTAL: a
    merge commit with no first parent -- a root commit handed in as one --
    makes ``<merge>^1`` a fatal error in the CONTROLLER's process rather than a
    refusal in this module's exception family, which is the harm
    ``_repo_argument``'s NUL screen exists to prevent. Naming the parents that
    the first command already established costs one command and makes every
    end of this one a 40-character object name.

    The same argv answers clause 2's fallback, with the target tip as the left
    end: ``<target tip>..<merge>`` is EMPTY exactly when the merge is an
    ancestor of the target branch.
    """
    location = _repo_argument(repo)
    base = _integration_end(first_parent, field="first parent")
    tip = _integration_end(second_parent, field="second parent")
    return ((
        *_integration_pins(location), "log", "--reverse",
        "--no-show-signature", "--no-color", _RANGE_FORMAT, f"{base}..{tip}",
        "--",
    ),)


def conflicted_paths_commands(repo) -> tuple:
    """The exact command whose output names the unmerged paths of a merge.

    THE FOUR PATH-HIDING MECHANISMS ARE PINNED HERE TOO, for Task 8's reasons
    and not as decoration: ``--no-renames`` because rename detection reports
    only a rename's destination, ``--no-relative`` because ``diff.relative``
    drops every path outside the command's directory, ``--ignore-submodules=
    none`` because ``diff.ignoreSubmodules=all`` removes a changed gitlink from
    the output altogether, and ``core.quotePath=true`` because it decides how a
    path is spelled. A conflicted path this command fails to print is a
    collision the hard stop cannot name, which is the whole content of the
    message fault F9 demands.

    BUT ONLY TWO OF THE FOUR CAN FIRE AGAINST THE UNMERGED SET, which is
    measured rather than assumed, because "pinned" and "proved" are different
    words and this build has already been caught calling a config load-bearing
    over a corpus that could not trigger it. Measured on git 2.39.5 against a
    tree carrying a real content conflict, a real rename-rename conflict, a
    real conflicted gitlink and a real non-ASCII conflicted path:

    * ``core.quotePath`` FIRES. Set to ``false`` by the repository the non-
      ASCII path is printed raw; pinned, it is C-quoted.
    * ``diff.relative`` FIRES, but ONLY WHEN THE LOCATION IS A SUBDIRECTORY of
      the work tree -- which is reachable rather than hypothetical, because
      the location is the run's ``repo_root`` and nothing requires that to be
      the top level of the git repository. From the top level the setting
      changes nothing.
    * ``diff.renames`` and ``diff.ignoreSubmodules`` DO NOT FIRE, and cannot:
      ``--diff-filter=U`` selects unmerged INDEX entries, which are emitted by
      stage rather than paired into renames or classified as submodule
      changes. Both tokens stay -- they cost nothing, the argv stays uniform
      with Task 8's where they DO fire, and a pin whose absence nobody would
      notice is how a later git changes its mind unobserved.
      ``ConflictPathSpellingTests`` asserts all four measurements, the two
      negative ones included, so that later git fails a test instead.

    ``--diff-filter=U`` IS WHAT MAKES IT THE UNMERGED SET rather than the
    working tree's ordinary diff. It is read for a DIAGNOSIS, never for a
    decision: the hard stop is raised on ``MERGE_HEAD`` alone, which this
    module reads itself, so a controller that answered this command with
    nothing at all would still be stopped -- it would only be stopped less
    informatively.
    """
    location = _repo_argument(repo)
    return ((
        *_integration_pins(location), "diff", "--no-renames", "--no-relative",
        "--ignore-submodules=none", "--no-color", "--name-only",
        "--diff-filter=U", "--",
    ),)


def _graft_screen(repo) -> None:
    """Refuse a repository whose graft file rewrites the parent relation.

    THE ONE HAZARD IN THIS BLOCK THAT NO EMITTED FLAG CAN REACH, measured on
    git 2.39.5: a line ``<commit> <parent> <parent>`` in
    ``<gitdir>/info/grafts`` makes ``%P`` print a second parent that the commit
    object does not carry -- fault F10 forged with one ordinary file write and
    no object at all -- and ``core.graftFile`` is inert both from a config file
    and from a command-line ``-c``. Only ``GIT_GRAFT_FILE`` turns it off, and
    this module emits argv rather than an environment.

    So the file is screened rather than the flag, which is what the pin rule
    actually asks for: the module reads it itself, the same way it already
    reads ``packed-refs``, ``HEAD`` and the gitdir pointer, and nothing written
    inside the repository can reach past that. ``_ref_text`` is the reader
    rather than ``open``, because it goes through ``_require_regular_file``: a
    FIFO at this name would otherwise block for ever under the run lock.

    BOTH STORES ARE ASKED. Git reads the graft file out of the COMMON
    directory, which is a different directory from ``gitdir`` in exactly the
    topology this phase creates -- one linked worktree per concurrently
    dispatched implementer -- so asking only one of the two would leave the
    channel open in the ordinary case.

    AN EMPTY OR WHITESPACE FILE IS NOT A GRAFT. ``git init`` templates and
    tooling leave empty files behind, and refusing one would stop a run over a
    file that changes no parent of anything.
    """
    gitdir, common = _git_store(repo)
    for store in (gitdir, common):
        path = store / _GRAFT_DIRNAME / _GRAFT_FILENAME
        text = _ref_text(path, "the git graft file")
        if text is not None and text.strip():
            raise TrackerValidationError(
                f"the repository at {str(path)!r} carries a graft file, which "
                "rewrites the parent relation this integration predicate is "
                "entirely about: a grafted commit reports a second parent it "
                "does not have, which is a fast-forward wearing a merge's "
                "shape. No command-line option turns it off on this git, so a "
                "repository carrying one cannot have its integration proved. "
                "Remove it, or convert it with `git replace "
                "--convert-graft-file` and the replace pin will neutralise it")


def _merge_in_progress(repo):
    """The ``MERGE_HEAD`` this tree is mid-merge on, or ``None``.

    NO CONTROLLER AND NO TRANSCRIPT. ``MERGE_HEAD`` is one of the five names
    git looks for directly under ``$GIT_DIR`` and is already in
    ``_PSEUDO_REFS``, so the ref-store reader this module has answered it
    before this task existed. The brief spent a ``git rev-parse --verify`` on
    the question and then a second command on the unmerged paths; only the
    second needs a controller, and only for the DIAGNOSIS.

    That separation is the point. The hard stop is raised on a fact this module
    established itself, so a controller that answers the path command with
    nothing -- or with a lie -- cannot make a conflicted tree look clean. It
    can only make the message less specific.

    A VALUE THAT IS NOT AN OBJECT NAME IS A STOP, NOT AN ABSENCE. ``MERGE_HEAD``
    is written by ``git merge`` as one object name per line; anything else at
    that name is a repository state this run cannot classify, and folding it
    into "no merge in progress" would let the one screen that fault F9 rests on
    be switched off by writing a junk file.

    AND THAT SENTENCE WAS NOT TRUE OF THE CODE THAT CARRIED IT. ``_lookup_ref``
    is the general resolver, and it is general in two ways this one name cannot
    afford. ``_ref_text`` reads a DIRECTORY as absence, because a ref namespace
    is a directory and the search must move to the next candidate; and
    ``_lookup_ref`` reads an EMPTY or whitespace-only loose file as ``broken``,
    which cancels that candidate's packed fallback and then falls off the end
    as ``None``. Both are right for ``refs/heads/<branch>``. Both answered "no
    merge in progress" over a tree with unmerged index entries -- measured
    against a real ``git merge`` conflict, where ``git commit`` itself says
    ``error: Committing is not possible because you have unmerged files`` --
    and ``integrate_task`` then recorded a durable integration over it.

    A ZERO-BYTE ``MERGE_HEAD`` NEEDS NO ADVERSARY: it is what an interrupted or
    crashed ``git merge`` leaves behind. The directory needs one ``mkdir``, and
    it is the same adversary ``_graft_screen`` already exists for -- a file
    written inside a repository the worker owns.

    SO THE TWO STORES ARE ASKED HERE RATHER THAN THROUGH THE RESOLVER, and the
    reason the withdrawal is safe is structural rather than a judgement call:
    ``_ref_candidates(_MERGE_HEAD)`` is a ONE-element tuple, so there is no
    next candidate for a directory to send the search to, no namespace beneath
    the name, and no ``packed-refs`` entry -- ``git pack-refs`` packs
    ``refs/``, never a pseudo-ref. Every shape a ``.git/MERGE_HEAD`` can have
    is therefore one of three answers: absent (no merge), a regular file whose
    content is one object name (that merge), or a stop. The FIFO, the dangling
    link, the loop and the unreadable name are still ``_ref_text``'s to refuse,
    and the ``namespace_ok=False`` flag hands it the directory as well.

    BOTH STORES ARE ASKED, for ``_graft_screen``'s reason and measured the
    same way. Git writes this name into the PER-WORKTREE gitdir -- which is
    why a merge in the main worktree lands at ``$GIT_COMMON_DIR/MERGE_HEAD``,
    where the two directories coincide, and why a linked worktree's own gitdir
    carries none and ``git rev-parse MERGE_HEAD`` there answers "not
    mid-merge". This phase runs one linked worktree per concurrently
    dispatched implementer, so asking only ``gitdir`` would let a run record a
    durable integration while the shared repository is mid-merge. Asking both
    ERRS CLOSED: the cost is a stop while another worktree is mid-merge, and
    the alternative is a record written over a merge state this run never
    read.
    """
    gitdir, common = _git_store(repo)
    value = None
    for store in (gitdir, common):
        text = _ref_text(store / _MERGE_HEAD, f"the git ref {_MERGE_HEAD!r}",
                         namespace_ok=False)
        if text is None:
            continue
        #: NOT ``continue`` ON AN EMPTY FILE, which is what the resolver does.
        #: There is no packed fallback and no later candidate to reach, so the
        #: only thing "keep looking" could reach is ``return None`` -- the one
        #: answer a tree mid-merge must never get.
        if not text.strip():
            raise TrackerValidationError(
                f"{_MERGE_HEAD} at {str(store / _MERGE_HEAD)!r} carries no "
                "object name; an empty or whitespace-only file there is what "
                "an interrupted `git merge` leaves behind, and a tree whose "
                "merge state this run cannot read is never a tree it may "
                "record an integration over")
        value = text.strip()
        break
    if value is None:
        return None
    if not _COMMIT.fullmatch(value):
        raise TrackerValidationError(
            f"{_MERGE_HEAD} names {value!r}, which is not one 40-character "
            "object name; a tree whose merge state this run cannot read is "
            "never a tree it may record an integration over")
    return value


def _claimed_by(path: str, scopes) -> bool:
    """Does any of these typed write scopes claim this repository path?

    ``_path_in_scope`` RAISES for a path no scope could ever claim -- absolute,
    a traversal, glob-bearing, or the C-quoted spelling ``core.quotePath=true``
    prints for a non-ASCII name -- because it screens the path through
    ``_safe_relative`` exactly as it screens the scope. Here that is an ANSWER
    and not a fault: a path no declaration can even spell is claimed by no
    declaration, and the hard stop still has to be raised. Letting the
    exception out would turn the diagnosis into the failure.
    """
    for scope in scopes:
        try:
            if _path_in_scope(path, scope):
                return True
        except PlanMetadataError:
            return False
    return False


def _declared_scopes(tracker: dict, task_id) -> tuple:
    """One task's APPROVED write scope, or ``()`` if the plan cannot say.

    The plan is the authority and ``_approved_definition`` is the only reader
    of it, but this is called while BUILDING A DIAGNOSIS: a phase plan that has
    moved, or a row whose kind has drifted, must not replace the hard stop with
    a different exception. The empty tuple reads as "this run could not recover
    the declaration", which is itself worth printing beside a collision.
    """
    try:
        return tuple(_approved_definition(tracker, task_id)["write_scope"])
    except TrackerError:
        return ()


def _colliding_task(tracker: dict, task_id, paths) -> tuple:
    """Who else this conflict implicates: ``((id, scopes, claimed), ...)``.

    THE COLLIDING TASK IS THE ONE WHOSE DECLARED SCOPE CLAIMS A CONFLICTED
    PATH, and that is a stronger answer than the brief's ``git show
    --name-only`` over each recorded commit rather than a cheaper one. The
    message's entire claim is that A SCOPE DECLARATION WAS WRONG; "who touched
    this path" is evidence about commits, while ``_path_in_scope`` against the
    approved plan is evidence about declarations, which is the thing being
    accused. It also needs no repository, no controller and no transcript.

    THE EMPTY-HANDED CASE IS NOT A FAILURE, IT IS THE LOUDER FINDING. When no
    declaration claims the conflicted path -- which is what the fixture for
    fault F9 constructs, and what a real scope bug looks like -- the fact is
    that the path is outside EVERY approved scope, so every task that has
    reached the repository is a candidate and each is named with what it
    actually declared. A single confidently-wrong name would be worse than a
    list: the run is stopping so a human can read the declarations.

    Ordering puts proven claimants first and is otherwise by id, so the message
    is stable across runs rather than dependent on row order.
    """
    _task_row(tracker, task_id)              # an unknown subject is a stop
    found = []
    for row in tracker.get("tasks", ()) or ():
        other = row["id"]
        if other == task_id:
            continue
        scopes = _declared_scopes(tracker, other)
        claimed = tuple(path for path in paths if _claimed_by(path, scopes))
        if claimed or row["state"] == _TASK_STATES[3]:
            found.append((other, scopes, claimed))
    return tuple(sorted(found, key=lambda entry: (not entry[2], entry[0])))


def _conflicted_paths(repo, run_command) -> tuple:
    """The unmerged paths, deduplicated, in the order the command printed them.

    ONE PATH PER LINE IS SAFE BECAUSE GIT QUOTES CONTROL CHARACTERS
    UNCONDITIONALLY, WHICH IS NOT WHAT ``core.quotePath`` GOVERNS. An earlier
    revision of this sentence said the newline safety came from the pin and
    offered a counterfactual -- "unpinned, the same path would split into two
    lines" -- that is false. Measured on git 2.39.5 with paths spelled
    ``a\\nb.py`` and ``tab\\there.py``: under ``core.quotePath=true`` AND under
    ``core.quotePath=false``, git prints ``"a\\nb.py"``, one C-quoted token
    either way. The setting changes only the NON-ASCII case, where ``true``
    gives ``"h\\303\\251llo.py"`` and ``false`` gives the raw UTF-8 bytes.

    So the record separator survives a newline whatever the repository says,
    and ``core.quotePath=true`` is pinned for the reason
    ``conflicted_paths_commands`` gives instead: a pure-ASCII transcript that
    is decodable by whatever captured it, and a C-quoted path that begins with
    ``"``, which no write scope claims, so it fails closed.
    """
    text = _range_transcript(run_command, conflicted_paths_commands(repo))
    return tuple(dict.fromkeys(line for line in text.split("\n") if line))


def _integration_ancestry(repo, *, commits, branch_tip: str,
                          merge_commit: str, target_branch: str,
                          run_command) -> tuple:
    """The three-clause ancestry predicate for the per-worktree topology.

    Clause 1 is unchanged from ``superb:pipeline``: a task's recorded commits
    are ancestors of its own branch tip. Clause 2 becomes: the task branch tip
    is the merge commit's SECOND parent, and the merge commit is the target
    branch. Clause 3's code state is the MERGE COMMIT, which P05 and P06 bind
    their ``task-integration`` evidence to.

    ``--no-ff`` IS LOAD-BEARING, NOT STYLISTIC, and the parent count is where
    that is enforced. A fast-forward leaves no merge commit at all, so the
    boundary between "what this task wrote" and "what the target branch already
    had" -- the boundary clause 2 is about -- simply does not exist to check.
    An octopus is refused by the same clause and for the same reason from the
    other side: several tasks share one commit and no per-task boundary
    survives either.

    CLAUSE 2's SECOND HALF IS A REF-STORE EQUALITY BEFORE IT IS A WALK, and
    that ordering is the strengthening the brief did not have. ``merge ==
    _resolved_commit(repo, target_branch)`` is DERIVED by this module from the
    ref store it reads itself; ``merge-base --is-ancestor`` would be attested
    by the controller. Equality is also strictly stronger: every commit equal
    to the tip is an ancestor of it and not conversely. The walk is kept only
    for the case equality cannot cover -- a later task integrated first and the
    tip has moved past this merge -- where ``<target tip>..<merge>`` is empty
    exactly when the merge is an ancestor of the branch.

    CLAUSE 1 IS THE SET EQUALITY AND NOT A SEPARATE ANCESTRY QUESTION. Because
    the merge commit exists, ``<first parent>..<second parent>`` yields the
    exact task commit set directly, with no baseline bookkeeping; requiring it
    to EQUAL the recorded ordered commits proves every recorded commit is
    reachable from the branch tip and that no commit rode along unrecorded.
    The chain is then checked from the transcript's own structure -- one parent
    each, each parent the record before it, the first parent the merge's first
    parent, the last record the branch tip -- rather than read off it as an
    assertion, which is Task 8's rule applied to Task 8's grammar.
    """
    location = _repo_argument(repo)
    _graft_screen(location)
    commits = tuple(commits)
    if not commits:
        raise TrackerValidationError(
            "integration needs at least one recorded commit: a task that moved "
            "its branch nowhere has no boundary to prove and nothing to "
            "integrate")
    for name in commits:
        _integration_end(name, field="recorded commit")
    tip = _resolved_commit(location, _integration_end(branch_tip,
                                                      field="branch tip"))
    merge = _resolved_commit(location, _integration_end(merge_commit,
                                                        field="merge commit"))
    target = _resolved_commit(location, target_branch)
    if merge != target:
        #: The tip has moved on, so equality cannot answer. `<tip>..<merge>` is
        #: empty exactly when the merge is reachable from the branch.
        beyond = _parse_range_transcript(_range_transcript(
            run_command, integration_range_commands(
                location, first_parent=target, second_parent=merge)))
        if beyond:
            raise TrackerValidationError(
                f"the merge commit {merge} is not on the target branch "
                f"{target_branch!r}, whose tip this ref store says is "
                f"{target}; an integration the target branch does not carry is "
                "work this run has not integrated")
    header = _parse_range_transcript(_range_transcript(
        run_command, merge_parents_commands(location, merge_commit=merge)))
    if len(header) != 1 or header[0]["commit"] != merge:
        raise TrackerValidationError(
            f"the controller's transcript for {merge} names "
            f"{[entry['commit'] for entry in header]!r} rather than that one "
            "commit; a header that is not about the merge commit is not "
            "evidence about this integration")
    parents = header[0]["parents"]
    if len(parents) != _MERGE_PARENTS:
        raise TrackerValidationError(
            f"integration must be a --no-ff merge with exactly "
            f"{_MERGE_PARENTS} parents; {merge} has {len(parents)}. A "
            "fast-forward collapses the merge commit the predicate depends on, "
            "and an octopus dissolves the per-task boundary from the other "
            "side -- either way there is nothing left that says where this "
            "task's work begins")
    if parents[1] != tip:
        raise TrackerValidationError(
            f"the merge commit's second parent is {parents[1]} and the task "
            f"branch tip is {tip}; the second parent is what makes this merge "
            "an integration OF THIS TASK rather than of whatever else was in "
            "flight")
    walked = _parse_range_transcript(_range_transcript(
        run_command, integration_range_commands(
            location, first_parent=parents[0], second_parent=parents[1])))
    names = tuple(entry["commit"] for entry in walked)
    if len(set(names)) != len(names):
        raise TrackerValidationError(
            f"the integration walk of {merge} names a commit more than once; "
            "an implementation range is a chain of distinct commits and a "
            "repeated record is a duplicated entry rather than a second "
            "commit")
    previous = parents[0]
    for entry in walked:
        if len(entry["parents"]) != 1 or entry["parents"][0] != previous:
            raise TrackerValidationError(
                f"the integration walk of {merge} is not a linear chain from "
                f"{parents[0]}: {entry['commit']} names parents "
                f"{list(entry['parents'])!r} where the record before it is "
                f"{previous}")
        previous = entry["commit"]
    if previous != tip:
        raise TrackerValidationError(
            f"the integration walk ends at {previous}, not at the task branch "
            f"tip {tip}; a walk that stops short leaves its last commits "
            "outside every ancestry and scope check")
    if names != commits:
        raise TrackerValidationError(
            "the merge's second-parent walk does not equal the recorded "
            f"ordered task commit set: the controller's transcript names "
            f"{list(names)!r} and the tracker records {list(commits)!r}")
    return names


def integrate_task(run_dir, *, task_id: str, merge_commit: str,
                   run_command) -> dict:
    """Record one task's ``--no-ff`` integration, or stop hard on a conflict.

    ``run_command`` IS REQUIRED AND IS THE CONTROLLER'S CAPABILITY, for
    ``import_worker_result``'s reasons exactly: the module emits the argv and
    validates the transcript, so the ability to run one command arrives as an
    argument rather than as an import, and it is asked for BEFORE the lock
    because a caller that cannot supply it has not failed a check -- it has
    called wrongly.

    THE HARD STOP COMES FIRST, BEFORE EVERY ROW CHECK. A conflicted ``git merge
    --no-ff`` leaves the tree mid-merge with unmerged paths and NO MERGE COMMIT
    to validate, so anything checked before it would report a different fault
    about a repository whose real problem is that two write scopes collided.
    The one thing checked earlier is that the task id names a row, because a
    diagnosis about a task this run does not have is not a diagnosis.

    AND THE STOP IS RAISED ON A FACT THIS MODULE ESTABLISHED. ``MERGE_HEAD``
    comes from the ref store this module reads itself; only the PATH LIST in
    the message comes from the controller. A controller that answers the path
    command with nothing still gets stopped -- less informatively, which is the
    right direction for the one failure this phase refuses to recover from.
    """
    home = _run_path(run_dir)
    if not callable(run_command):
        raise TrackerValidationError(
            f"integrate_task needs the controller's command runner; got "
            f"{type(run_command).__name__} {run_command!r}, which is not "
            "callable. This module emits the argv that proves an integration "
            "and never runs one, so the ability to run it is an argument -- "
            "and it is asked for before the lock, because a caller that cannot "
            "supply it has not failed a check, it has called wrongly")

    def mutate(tracker: dict) -> dict:
        repo = _repo_dir(tracker)
        row = _task_row(tracker, task_id)
        if _merge_in_progress(repo) is not None:
            paths = _conflicted_paths(repo, run_command)
            implicated = _colliding_task(tracker, task_id, paths)
            others = "; ".join(
                f"task {other} declared {list(scopes)!r}"
                + (f" and claims {list(claimed)!r}" if claimed else "")
                for other, scopes, claimed in implicated)
            if not others:
                others = ("no other task at all, which means the conflicting "
                          "path is outside every approved write scope this "
                          "run knows about")
            raise TrackerValidationError(
                f"{_HARD_STOP}: the integration of task {task_id} conflicted, "
                "which proves that a write scope declaration was wrong. The "
                f"controller must now run `{_ABORT_ACTION}` -- this module "
                "never writes to the repository, so the tree is still "
                "mid-merge and the evidence is intact. The run stops here: the "
                "task is NOT redone alone, because that papers over the broken "
                "declaration and lets the next task hit the same collision; "
                "the merge is NOT retried; and no resolution flag is offered, "
                "because under typed write-scope validation this state should "
                f"be unreachable. Conflicting paths: {list(paths)!r}. Task "
                f"{task_id} declared {list(_declared_scopes(tracker, task_id))!r}. "
                f"Also implicated: {others}")
        if row["kind"] != TASK_KINDS[0]:
            raise TrackerValidationError(
                f"task {task_id!r} is {row['kind']!r} and only a source task "
                "integrates; an artifact task produces no source range, so "
                "there is no boundary to prove and nothing to merge")
        if row["state"] != _TASK_STATES[3]:
            raise TrackerValidationError(
                f"task {task_id!r} is {row['state']} and only a completed task "
                "integrates; recording an integration over work that has not "
                "finished would make the merge commit the proof of a range "
                "nobody has verified")
        resolved = _resolved_commit(repo, merge_commit)
        if row["integration"] == resolved:
            return tracker                                 # replay: inert
        if row["integration"] != _INTEGRATION_HELD:
            raise TrackerValidationError(
                f"task {task_id!r} is already integrated at "
                f"{row['integration']!r} and this call names {resolved}; a "
                "second answer under one identity is evidence to be "
                "reconciled, never an update")
        _integration_ancestry(
            repo, commits=_csv(row["commits"]),
            branch_tip=_resolved_commit(repo, row["source_ref"]),
            merge_commit=resolved,
            target_branch=_run_field(tracker, "target_branch"),
            run_command=run_command)
        updated = dict(row)
        updated["integration"] = resolved
        updated["checkpoints"] = _append_history(
            row["checkpoints"],
            f"{_INTEGRATED_CHECKPOINT}{row['attempt']}"
            f"{_CHECKPOINT_DELIMITERS[1]}{resolved}")
        return _replace_task(tracker, updated)

    return locked_tracker_update(
        home, transition_id=f"integrate-{task_id}-{merge_commit}",
        mutate=mutate)


# ---------------------------------------------------------------------------
# P04 Task 12: file-first reconciliation -- fault F7.
#
# After a compaction, restart or interruption the run rebuilds its next action
# from FILES AND THE REF STORE, never from conversation memory. A commit that
# appeared immediately before the interruption is neither automatic success nor
# grounds to repeat five hours of work. A MISSING result is neither: it is an
# open question about a worker that may still be alive, and answering it either
# way is F7.
#
# SO THIS FUNCTION DOES EXACTLY ONE THING BY ITSELF. It imports a published
# result whose four-part identity -- run, task, attempt, owner -- matches the
# assignment this controller persisted, through the transition that already
# adjudicates that. Everything else it finds becomes a QUESTION (contradictory
# evidence somebody has to settle) or a DIAGNOSTIC (a name in the results tree
# this run cannot read), and neither channel changes a byte.
#
# ``run_command`` IS REQUIRED, and it is the Task 10 supersession reaching its
# last consumer. The module never executes git: ``import_worker_result`` and
# ``_integration_ancestry`` both take the controller's runner as a required
# keyword-only argument, and a reconciliation is the caller of both. A default
# here would be a capability nobody declared, discovered at the end of a
# successful-looking recovery rather than at the call.
# ---------------------------------------------------------------------------

def _result_store_names(root: Path, diagnostics: list) -> list:
    """Every name in the results tree, and every directory that could not be listed.

    ``Path.rglob`` IS NOT ASKED, because it lies by omission. CPython's
    recursive selector swallows ``PermissionError`` while it walks: measured on
    this interpreter, a task directory at mode ``000`` holding a genuine
    published result lists as the directory alone, and the store itself at mode
    ``000`` lists as nothing at all -- no exception either way, while
    ``is_dir()`` on the store still answers True. Every live attempt was then
    reported as awaiting a worker whose answer was on disk behind a door this
    run could not open, which is F7's fail-open arriving through the walk
    rather than through a name. It is the fourth "is anything here?" question
    in this module found answering "no" for "cannot tell", after directories,
    FIFOs and NUL-bearing names.

    SO EACH DIRECTORY IS LISTED BY ``os.scandir`` ITSELF, AND A LISTING THAT
    FAILS IS A FINDING. The ``OSError`` is caught per directory -- one
    unsearchable task directory must not hide the others -- and reported as
    ``unreadable-result-store:<dir>:<exc>``. A directory that vanishes
    between its parent's listing and its own is the same finding: this tree is
    append-only, so a name disappearing from it is not a result known absent.

    ONE ABSENCE IS REAL, AND IT IS ASKED BY ``lexists`` RATHER THAN BY THE
    LISTING'S ERRNO. A store that was never created is a run in which nothing
    has been published yet. A store that is a regular file, a dangling link or
    a loop also fails the listing -- ``ENOTDIR``, ``ENOENT``, ``ELOOP`` -- and
    ``ENOENT`` is the same errno the genuine absence raises, so the errno cannot
    be the test; the name is.

    THE MODULE OWNS THE LAYOUT, SO THE TASK LAYER IS THE ONLY SILENT ONE.
    ``worker_result_path`` is ``agent-output/<task id>/<attempt>.md``: a real
    directory directly under the store is the module's own structure and is
    only descended into. A real directory anywhere deeper -- including one AT a
    canonical result name -- is descended into AND returned as a name, so the
    door refuses it as the corruption it is. Descending matters as much as
    naming: a second copy of a result filed one level down is still a second
    answer for one attempt, and a walk that stopped at the layout would import
    the first copy without ever seeing the conflict. A symlink anywhere, to a
    directory or looping back up the tree, is a name and is never followed, so
    the walk visits each real directory once and a loop cannot make it revisit
    anything.

    A NUL BYTE IS SCREENED, not handed to ``os.scandir``, which raises
    ``ValueError`` -- outside ``OSError`` and outside this module's family.
    ``reconcile_run`` cannot reach it (``validate_run`` refuses such a run
    directory first), and the screen reports rather than answers "empty".

    The names come back SORTED: directory order is the filesystem's, and a
    report whose lines move between two runs over one tree cannot be diffed
    across an interruption, which is the only use it has.
    """
    if _NUL in str(root):
        diagnostics.append(
            f"unreadable-result-store:{root!r}: the results tree's name "
            "carries a NUL byte, which no syscall accepts; nothing under it is "
            "known to be absent")
        return []
    names: list = []
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        try:
            with os.scandir(directory) as entries:
                children = sorted(
                    (Path(entry.path), entry.is_dir(follow_symlinks=False))
                    for entry in entries)
        except OSError as exc:
            if depth == 0 and not os.path.lexists(directory):
                return []
            diagnostics.append(f"unreadable-result-store:{directory}:{exc}")
            continue
        for child, is_directory in reversed(children):
            if is_directory:
                pending.append((child, depth + 1))
            if not is_directory or depth > 0:
                names.append(child)
    return sorted(names)


def _result_candidates(run_dir: Path, diagnostics: list) -> list:
    """Every parsed worker result under ``agent-output``, and what could not be.

    ``is_dir()`` IS NOT ASKED AS "IS THERE ANYTHING HERE". It answers False for
    a regular file, a dangling symlink, a symlink loop and a NUL-bearing name,
    and folding those into "no result has been published" is F7's fail-open
    wearing a predicate: every live attempt would then be reported as awaiting
    a worker whose answer is sitting on disk, unreadable. Neither is the walk
    asked by a predicate that swallows its own failures -- see
    ``_result_store_names``.

    THE PREDICATE IS INSTANT AND THE OPEN IS WHAT BLOCKS. A FIFO published
    under this tree answers ``is_file()`` False in no time at all and then
    hangs ``read_text`` for ever -- under the run lock, with no writer ever
    coming. So the shape goes through this module's one door,
    ``_require_regular_file``, BEFORE anything is opened, and the read is what
    is bounded rather than the predicate.

    NO NAME BELOW THE TASK LAYER IS SKIPPED. Every such name reaches the door,
    so a directory or a symlink at the document layer is refused as what it is
    rather than dropped before the door could see it.
    ``publish_worker_result`` writes neither.

    THIS IS THE ONE CALLER OF THE DOOR THAT CATCHES ITS REFUSAL AND DOES NOT
    RE-RAISE. Five others catch it and translate it into another
    ``TrackerError``, and still stop; a reconciliation that stopped on one
    unreadable name would lose the findings about every other row.

    A DOCUMENT WITH NO MARKER IS NAMED RATHER THAN SKIPPED. This tree is
    written by ``publish_worker_result`` and by nothing else, so an unexplained
    document in it is exactly the thing reconciliation may not read as absence.
    """
    candidates: list = []
    root = run_dir / AGENT_OUTPUT_DIRNAME
    for path in _result_store_names(root, diagnostics):
        try:
            _require_regular_file(path, "published worker result")
            content = path.read_text(encoding="utf-8")
        except (TrackerError, OSError, UnicodeError) as exc:
            diagnostics.append(f"unreadable-result-candidate:{path}:{exc}")
            continue
        if not content.startswith(WORKER_RESULT_MARKER):
            diagnostics.append(f"foreign-result-candidate:{path}")
            continue
        try:
            candidates.append((path, parse_worker_result(content)))
        except TrackerError as exc:
            diagnostics.append(f"partial-or-malformed-result:{path}:{exc}")
    return candidates


def reconcile_run(run_dir, *, run_command) -> dict:
    """Rebuild the next recovery action from authoritative files and Git evidence.

    Returns ``{"actions": tuple, "questions": tuple, "diagnostics": tuple}``.
    ``actions`` is what the controller may do next; ``questions`` is
    contradictory evidence that a human or a quorum settles; ``diagnostics`` is
    a name in the results tree this run could not read. Only the import arm
    writes anything, and only through ``import_worker_result``.

    EVERY APPROVED PHASE PLAN IS RE-READ BEFORE ANY TASK ROW IS TRUSTED. The
    row is a mirror of the plan -- kind, write scope, dependencies and the
    verification suite live there and nowhere else -- so recovering against
    rows whose authority no longer parses is recovering against a document that
    changed underneath the run. That is a read-only stop and it is raised, not
    reported: a report derived from an unreadable authority is worse than no
    report.

    THE TRACKER IS RE-READ BETWEEN THE TWO PASSES. The first pass may import,
    and an import is a durable transition under the run lock; the second pass
    asks about completion and integration, so it must ask of the state the
    first pass left rather than of the copy it started from.

    AN UNROUTABLE ``Question`` CELL PRODUCES NO ACTION. The cell has exactly
    two arms, ``quorum:<qid>@<path>#sha256=<digest>`` and ``halt:<reason>``,
    and the route alone is not one of them: a cell spelled ``quorum`` with
    nothing behind it would otherwise be routed as a quorum nobody can look up.
    The detail is taken with ``partition`` rather than ``split`` because a halt
    reason is free text and may carry colons of its own.

    THE BRIEF'S TWO UNREACHABLE ARMS ARE NOT IMPLEMENTED, and both are asserted
    unreachable by tests rather than argued here: ``integration in {"-", ""}``
    and an artifact row whose integration is not ``N/A`` are states
    ``_validate_tasks`` refuses to store, so ``validate_run`` -- called one
    line above -- raises before either could be reached. The integration-held
    sentinel is what a completed, unintegrated source task actually carries.
    """
    run_dir = _run_path(run_dir)
    if not callable(run_command):
        raise TrackerValidationError(
            f"reconcile_run needs the controller's command runner; got "
            f"{type(run_command).__name__} {run_command!r}, which is not "
            "callable. This module emits the argv that proves a source range "
            "and an integration and never runs one, so the ability to run it "
            "is an argument -- and it is asked for before anything is opened, "
            "because a caller that cannot supply it has not failed a check, it "
            "has called wrongly")
    tracker = validate_run(run_dir)
    repo = _repo_dir(tracker)
    run_id = _run_field(tracker, "run_id")
    target = _run_field(tracker, "target_branch")
    actions: list = []
    questions: list = []
    diagnostics: list = []

    for phase in tracker.get("phases", ()) or ():
        parse_plan_metadata(_phase_plan_path(tracker, phase["id"]))

    candidates = _result_candidates(run_dir, diagnostics)

    for row in tracker.get("tasks", ()) or ():
        if row["state"] != _TASK_STATES[1]:
            continue
        same_task = [
            (path, result) for path, result in candidates
            if result["run_id"] == run_id and result["task_id"] == row["id"]
        ]
        matches = [(path, result) for path, result in same_task
                   if _attempt_token(result["attempt"]) == row["attempt"]]
        #: THE MAP FROM (task, attempt) TO A PATH IS INJECTIVE, so a second
        #: document for one attempt is one no transition of this module wrote.
        #: Which of the two is the real one is not a question a recovery
        #: settles by picking one.
        if len(matches) > 1:
            questions.append(f"conflicting-results:{row['id']}:{row['attempt']}")
            continue
        if matches:
            path, result = matches[0]
            if result["owner"] != row["owner"]:
                questions.append(
                    f"result-owner-contradiction:{row['id']}:{row['attempt']}:"
                    f"{path}")
                continue
            try:
                import_worker_result(run_dir, result_path=path,
                                     run_command=run_command)
            except TrackerError as exc:
                questions.append(
                    f"result-evidence-contradiction:{row['id']}:"
                    f"{row['attempt']}:{exc}")
            else:
                actions.append(f"imported:{row['id']}:{row['attempt']}")
            continue
        stale = [str(path) for path, _ in same_task]
        if stale:
            questions.append(
                f"superseded-or-conflicting-result:{row['id']}:"
                f"{row['attempt']}:{','.join(stale)}")
        #: A MISSING RESULT IS NOT COMPLETION AND NOT GROUNDS TO REPEAT THE
        #: WORK. It is a question about whether the owner is still alive, and
        #: that is a question the controller can answer and this module cannot.
        actions.append(
            f"await-or-check-live-owner:{row['id']}:{row['attempt']}:"
            f"{row['owner']}")

    tracker = validate_run(run_dir)
    for row in tracker.get("tasks", ()) or ():
        if row["state"] == _TASK_STATES[3] and row["kind"] == TASK_KINDS[0]:
            if row["integration"] == _INTEGRATION_HELD:
                actions.append(f"integration-pending:{row['id']}")
                continue
            try:
                _integration_ancestry(
                    repo, commits=_csv(row["commits"]),
                    branch_tip=_resolved_commit(repo, row["source_ref"]),
                    merge_commit=row["integration"], target_branch=target,
                    run_command=run_command)
            except TrackerError as exc:
                questions.append(f"integration-contradiction:{row['id']}:{exc}")
        elif row["state"] == _TASK_STATES[2]:
            route, _, detail = row["question"].partition(":")
            if not detail or not _member(route, (QUORUM_ROUTE, HALT_ROUTE)):
                questions.append(
                    f"unroutable-block:{row['id']}:{row['question']}")
            else:
                actions.append(f"await-{route}:{row['id']}:{detail}")

    return {"actions": tuple(actions), "questions": tuple(questions),
            "diagnostics": tuple(diagnostics)}
