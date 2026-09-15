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
    for row in stages:
        if row["stage_state"] == "active" and row["next_action"] == "-":
            raise TrackerValidationError("the active stage must name its next action")
        if row["stage_state"] != "active" and row["next_action"] != "-":
            raise TrackerValidationError("only the active stage carries a next action")


def _validate_tracker_semantics(tracker: dict) -> None:
    """Every per-section semantic rule, run as the last step of a parse.

    Structural parsing proves the bytes are a tracker; this proves they are a
    state the run can actually be in. Later phases extend the dispatcher rather
    than add a second entry point, so there is exactly one place a tracker is
    judged and no way to obtain an unvalidated one.
    """
    _validate_stages(tracker)


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
