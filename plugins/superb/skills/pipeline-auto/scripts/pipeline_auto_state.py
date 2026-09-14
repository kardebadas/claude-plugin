"""Durable state for superb:pipeline-auto. Python standard library only.

The tracker is the authority. Conversation memory never is. Every durable
transition in this run goes through this module.

This module does not interoperate with superb:pipeline. `pipeline-run/v1` and
`pipeline-run/v2` are foreign schemas and there is no migration in either
direction — not here, not later.
"""

from __future__ import annotations

import re

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

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@:+-]*")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


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
    content = [line for line in section if line]
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
    if any(lines[2:positions[0]]):
        raise TrackerValidationError("unexpected content before the first section")
    return {
        heading: lines[positions[index] + 1:(
            positions[index + 1] if index + 1 < len(positions) else len(lines)
        )]
        for index, heading in enumerate(_HEADINGS)
    }


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
    return tracker


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
