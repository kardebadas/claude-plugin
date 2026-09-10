#!/usr/bin/env python3
"""Strict Pipeline v2 Markdown contracts.

This module intentionally supports one tracker, worker-result, and phase-plan
metadata grammar. Mutation, locking, scheduling, and recovery are added by the
later Phase 1 tasks.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import platform
import plistlib
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by selection simulation
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised by selection simulation
    msvcrt = None

SCHEMA = "pipeline-run/v2"
_PRE_RELEASE_ADOPTION_RUN_ID = "2026-09-08-pipeline-rebuild-v2"
_TRACKER_MARKER = f"<!-- {SCHEMA} -->"
_RESULT_MARKER = "<!-- pipeline-worker-result/v2 -->"
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_TASK_STATES = {"[ ]", "[~]", "[?]", "[x]"}
_WORKER_STATUSES = {"DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "PLAN_CONFLICT", "BLOCKED"}


class SchemaError(ValueError):
    """The tracker or worker-result text does not match the v2 contract."""


class PlanMetadataError(ValueError):
    """A phase plan does not match the fixed v2 metadata contract."""


class LegacySchemaError(SchemaError):
    """A recognized Pipeline v1 tracker was supplied to v2."""


class LockBusyError(RuntimeError):
    """Another cooperating controller held the run-local lock to the deadline."""


class LockUnavailableError(RuntimeError):
    """The required OS-backed locking primitive could not be used."""


class TrackerWriteError(RuntimeError):
    """A tracker update failed before replacement; the old tracker remains."""


class UpdateOutcomeUncertain(RuntimeError):
    """Replacement occurred but a later synchronization operation failed."""

    def __init__(self, message: str, tracker: Tracker | None = None):
        self.tracker = tracker
        super().__init__(message)


class TransitionError(ValueError):
    """A requested controller transition is illegal for the current state."""


class EvidenceError(ValueError):
    """Worker evidence is missing, stale, conflicting, or assignment-inconsistent."""


class FilesystemSuitabilityError(RuntimeError):
    """The tracker filesystem is known unsupported or lacks required approval."""


class _AlreadyApplied(Exception):
    def __init__(self, tracker: Tracker):
        self.tracker = tracker


@dataclass(frozen=True)
class TaskRecord:
    id: str
    kind: str
    state: str
    owner: str
    attempt: str
    result: str
    checkpoints: str
    source_ref: str
    commits: str
    artifacts: str
    integration: str
    verification: str
    question: str


@dataclass(frozen=True)
class PhaseRecord:
    id: str
    state: str
    verification: str
    review_gate: str
    review_reason: str
    gate: str


@dataclass(frozen=True)
class GateRecord:
    id: str
    type: str
    phase: str
    state: str
    base: str
    head: str
    assignments: str
    reports: str
    verification: str
    findings: str
    questions: str


@dataclass(frozen=True)
class RemediationRecord:
    gate: str
    round_number: int
    state: str
    fixers: str
    released_fixers: str
    findings: str
    fix_plan: str
    commits: str
    verification: str
    re_review: str


@dataclass(frozen=True)
class Tracker:
    run_fields: tuple[tuple[str, str], ...]
    current_fields: tuple[tuple[str, str], ...]
    tasks: tuple[TaskRecord, ...]
    phases: tuple[PhaseRecord, ...]
    gates: tuple[GateRecord, ...]
    remediation: tuple[RemediationRecord, ...]

    def _run_value(self, key: str) -> str:
        return dict(self.run_fields)[key]

    @property
    def run_id(self) -> str:
        return self._run_value("run_id")

    @property
    def base_commit(self) -> str:
        return self._run_value("base_commit")

    @property
    def target_branch(self) -> str:
        return self._run_value("target_branch")

    @property
    def worker_limit(self) -> int:
        return int(self._run_value("worker_limit"))

    @property
    def revision(self) -> int:
        return int(self._run_value("revision"))

    @property
    def last_transition(self) -> str:
        return self._run_value("last_transition")


RuntimeCapacityProvider = Callable[[Path, Tracker], int | None]
_BOUND_RUNTIME_CAPACITY: ContextVar[
    tuple[Path, RuntimeCapacityProvider] | None
] = ContextVar("pipeline_v2_runtime_capacity", default=None)


@contextmanager
def bind_runtime_capacity_provider(
    run_dir: Path,
    provider: RuntimeCapacityProvider,
) -> Iterator[None]:
    """Bind a fast, side-effect-free capacity source to one controller/run scope."""
    if not callable(provider):
        raise TransitionError("runtime capacity provider must be callable")
    token = _BOUND_RUNTIME_CAPACITY.set((Path(run_dir).resolve(), provider))
    try:
        yield
    finally:
        _BOUND_RUNTIME_CAPACITY.reset(token)


@dataclass(frozen=True)
class Checkpoint:
    id: str
    status: str
    evidence: str


@dataclass(frozen=True)
class WorkerResult:
    run_id: str
    task_id: str
    attempt: str
    owner: str
    kind: str
    status: str
    source_ref: str
    commits: tuple[str, ...]
    artifacts: tuple[str, ...]
    tests: str
    evidence: tuple[str, ...]
    concerns: str
    question: str
    blocking_reason: str
    checkpoints: tuple[Checkpoint, ...]


@dataclass(frozen=True)
class PlannedTask:
    id: str
    deps: tuple[str, ...]
    kind: str
    batch: str
    order: int
    write_scope: tuple[str, ...]
    outputs: tuple[str, ...]
    verification_commands: tuple[str, ...]


@dataclass(frozen=True)
class PhaseMetadata:
    id: str
    deps: tuple[str, ...]
    review_gate: str
    review_reason: str
    verification_commands: tuple[str, ...]


@dataclass(frozen=True)
class VerificationEvidence:
    purpose: str
    run_id: str
    subject: str
    attempt: str
    code_state: str
    commands: tuple[str, ...]
    environment: str
    inputs: str


@dataclass(frozen=True)
class ReconciliationReport:
    actions: tuple[str, ...]
    questions: tuple[str, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class FilesystemInfo:
    classification: str
    fs_type: str
    fingerprint: str


_RUN_KEYS = (
    "run_id", "tracker_format", "schema_adoption", "base_commit", "target_branch",
    "worker_limit", "filesystem_class", "filesystem_type", "filesystem_fingerprint",
    "filesystem_ack", "spec", "master_plan", "phase_plans", "decisions", "findings",
    "revision", "last_transition",
)
_PRE_ADOPTION_RUN_KEYS = (
    "run_id", "base_commit", "target_branch", "worker_limit", "spec", "master_plan",
    "phase_plans", "decisions", "findings", "revision", "last_transition",
)
_CURRENT_KEYS = ("phase", "batch", "next_action")
_RESULT_KEYS = ("run_id", "task_id", "attempt", "owner", "kind", "status", "source_ref", "commits", "artifacts", "tests", "evidence", "concerns", "question", "blocking_reason")
_TASK_HEADER = ("ID", "Kind", "State", "Owner", "Attempt", "Result", "Checkpoints", "Source Ref", "Commits", "Artifacts", "Integration", "Verification", "Question")
_PHASE_HEADER = ("ID", "State", "Verification", "Review Gate", "Review Reason", "Gate")
_GATE_HEADER = ("ID", "Type", "Phase", "State", "Base", "Head", "Assignments", "Reports", "Verification", "Findings", "Questions")
_REMEDIATION_HEADER = ("Gate", "Round", "State", "Fixers", "Released Fixers", "Findings", "Fix Plan", "Commits", "Verification", "Re-review")
_PRE_ADOPTION_REMEDIATION_HEADER = ("Gate", "Round", "State", "Findings", "Fix Plan", "Commits", "Verification", "Re-review")
_CHECKPOINT_HEADER = ("ID", "Status", "Evidence")


def _cells(line: str, error: type[ValueError]) -> tuple[str, ...]:
    if not line.startswith("|") or not line.endswith("|"):
        raise error("table row must start and end with '|'")
    values = tuple(part.strip() for part in line[1:-1].split("|"))
    if any(not value for value in values):
        raise error("table cells cannot be empty")
    return values


def _table(section: list[str], header: tuple[str, ...], error: type[ValueError]) -> tuple[tuple[str, ...], ...]:
    content = [line for line in section if line]
    if len(content) < 3 or _cells(content[0], error) != header:
        raise error(f"expected table header: {header!r}")
    separator = _cells(content[1], error)
    if len(separator) != len(header) or any(value != "---" for value in separator):
        raise error("invalid table separator")
    rows = tuple(_cells(line, error) for line in content[2:])
    if not rows or any(len(row) != len(header) for row in rows):
        raise error("table must have complete data rows")
    return rows


def _sections(text: str, marker: str, title: str, headings: tuple[str, ...], error: type[ValueError]) -> dict[str, list[str]]:
    lines = text.splitlines()
    if not text.endswith("\n") or lines[:2] != [marker, title]:
        raise error("invalid marker, title, or terminal newline")
    positions = []
    for heading in headings:
        matches = [index for index, line in enumerate(lines) if line == heading]
        if len(matches) != 1:
            raise error(f"expected exactly one {heading!r} section")
        positions.append(matches[0])
    if positions != sorted(positions) or [line for line in lines if line.startswith("## ")] != list(headings):
        raise error("unknown or reordered section")
    if any(lines[2:positions[0]]):
        raise error("unexpected content before first section")
    return {heading: lines[positions[i] + 1:positions[i + 1] if i + 1 < len(positions) else len(lines)] for i, heading in enumerate(headings)}


def _key_values(section: list[str], keys: tuple[str, ...], error: type[ValueError]) -> tuple[tuple[str, str], ...]:
    rows = _table(section, ("Field", "Value"), error)
    if tuple(row[0] for row in rows) != keys:
        raise error("missing, duplicate, unknown, or reordered field")
    return tuple((row[0], row[1]) for row in rows)


def _csv(value: str) -> tuple[str, ...]:
    return () if value == "-" else tuple(part.strip() for part in value.split(","))


def _unique(values: tuple[object, ...], attr: str, error: type[ValueError]) -> None:
    ids = [getattr(value, attr) for value in values]
    if len(ids) != len(set(ids)):
        raise error(f"duplicate {attr}")


def _parse_tracker_for_exact_reconciliation(text: str) -> Tracker:
    headings = ("## Run", "## Current State", "## Tasks", "## Phases", "## Gates", "## Remediation")
    sections = _sections(text, _TRACKER_MARKER, "# Pipeline v2 — Progress Tracker", headings, SchemaError)
    run_fields = _key_values(sections["## Run"], _RUN_KEYS, SchemaError)
    current_fields = _key_values(sections["## Current State"], _CURRENT_KEYS, SchemaError)
    run = dict(run_fields)
    if not _TOKEN.fullmatch(run["run_id"]) or not _COMMIT.fullmatch(run["base_commit"]):
        raise SchemaError("invalid run identity")
    if run["tracker_format"] != "2":
        raise SchemaError("unsupported tracker_format")
    if run["schema_adoption"] != "none" and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._/-]*@[0-9a-f]{64}", run["schema_adoption"]
    ):
        raise SchemaError("invalid schema_adoption identity")
    if run["filesystem_class"] not in {"supported-local", "unknown"}:
        raise SchemaError("invalid or unsupported filesystem classification")
    if not run["filesystem_type"] or not re.fullmatch(r"[A-Za-z0-9._+-]+", run["filesystem_type"]):
        raise SchemaError("invalid filesystem type")
    if not re.fullmatch(r"[0-9a-f]{64}", run["filesystem_fingerprint"]):
        raise SchemaError("invalid filesystem fingerprint")
    if run["filesystem_class"] == "supported-local" and run["filesystem_ack"] != "N/A":
        raise SchemaError("supported local filesystem uses filesystem_ack=N/A")
    if run["filesystem_class"] == "unknown" and not run["filesystem_ack"].endswith("@" + run["filesystem_fingerprint"]):
        raise SchemaError("unknown filesystem needs a fingerprint-bound acknowledgement")
    try:
        if int(run["worker_limit"]) <= 0 or int(run["revision"]) < 0:
            raise ValueError
    except ValueError as exc:
        raise SchemaError("worker_limit must be positive and revision nonnegative") from exc
    if not _TOKEN.fullmatch(run["last_transition"]):
        raise SchemaError("invalid last_transition")
    tasks = tuple(TaskRecord(*row) for row in _table(sections["## Tasks"], _TASK_HEADER, SchemaError))
    phases = tuple(PhaseRecord(*row) for row in _table(sections["## Phases"], _PHASE_HEADER, SchemaError))
    gates = tuple(GateRecord(*row) for row in _table(sections["## Gates"], _GATE_HEADER, SchemaError))
    try:
        remediation = tuple(RemediationRecord(row[0], int(row[1]), *row[2:]) for row in _table(sections["## Remediation"], _REMEDIATION_HEADER, SchemaError))
    except ValueError as exc:
        raise SchemaError("remediation round must be an integer") from exc
    for collection, attr in ((tasks, "id"), (phases, "id"), (gates, "id")):
        _unique(collection, attr, SchemaError)
    round_ids = [(row.gate, row.round_number) for row in remediation]
    if len(round_ids) != len(set(round_ids)) or any(row.round_number <= 0 for row in remediation):
        raise SchemaError("invalid or duplicate remediation round")
    for task in tasks:
        if task.kind not in {"source", "artifact"} or task.state not in _TASK_STATES:
            raise SchemaError("invalid task kind or state")
        if task.kind == "source" and task.artifacts != "-":
            raise SchemaError("source task cannot carry artifacts")
        if task.kind == "artifact" and (task.source_ref != "-" or task.commits != "-"):
            raise SchemaError("artifact task cannot carry source provenance")
        if task.kind == "artifact" and task.state == "[x]" and (task.artifacts == "-" or task.integration != "N/A"):
            raise SchemaError("completed artifact task needs artifacts and N/A integration")
        if task.state == "[~]" and (task.owner == "-" or task.attempt == "-"):
            raise SchemaError("active task needs owner and attempt")
    for phase in phases:
        if phase.state not in _TASK_STATES or phase.review_gate not in {"required", "final-only"}:
            raise SchemaError("invalid phase state or review gate")
        if phase.review_gate == "required" and phase.review_reason == "-":
            raise SchemaError("required phase review needs a reason")
    for gate in gates:
        if gate.type not in {"phase", "master"} or gate.state not in {"pending", "in_progress", "re_reviewing", "blocked", "accepted"}:
            raise SchemaError("invalid gate type or state")
        if gate.state in {"in_progress", "re_reviewing"} and gate.assignments == "-":
            raise SchemaError("active review gate needs reviewer assignments")
        if any(not _TOKEN.fullmatch(value) for value in _csv(gate.assignments)):
            raise SchemaError("invalid reviewer assignment identity")
    if any(row.state not in {"pending", "fixing", "re_reviewing", "blocked", "complete"} for row in remediation):
        raise SchemaError("invalid remediation state")
    for row in remediation:
        if row.state == "fixing" and row.fixers == "-":
            raise SchemaError("fixing remediation needs active fixers")
        if row.state != "fixing" and row.fixers != "-":
            raise SchemaError("only fixing remediation may carry active fixers")
        for value in (*_csv(row.fixers), *_csv(row.released_fixers)):
            if not _TOKEN.fullmatch(value):
                raise SchemaError("invalid remediation worker identity")
    tracker = Tracker(run_fields, current_fields, tasks, phases, gates, remediation)
    if len(_active_worker_ids(tracker)) > tracker.worker_limit:
        raise SchemaError("active worker identities exceed the global worker limit")
    return tracker


def parse_tracker(text: str) -> Tracker:
    """Parse the one supported tracker format and reject incomplete round outcomes."""
    tracker = _parse_tracker_for_exact_reconciliation(text)
    for row in tracker.remediation:
        outcomes = [
            item for item in _csv(row.verification)
            if item.startswith("remaining-blockers=")
        ]
        if row.state == "complete" and len(outcomes) != 1:
            raise SchemaError("completed remediation round needs exactly one remaining-blockers outcome")
        if row.state != "complete" and outcomes:
            raise SchemaError("only a completed remediation round may record remaining-blockers")
        if outcomes:
            value = outcomes[0].split("=", 1)[1]
            blockers = value.split("+")
            targets = {
                finding
                for remediation in tracker.remediation
                if remediation.gate == row.gate
                for finding in _csv(remediation.findings)
            }
            gate = next((gate for gate in tracker.gates if gate.id == row.gate), None)
            if gate is not None:
                targets.update(_gate_finding_ids(gate))
            if value == "none":
                blockers = []
            elif (
                not value
                or "none" in blockers
                or len(blockers) != len(set(blockers))
                or any(not _TOKEN.fullmatch(blocker) for blocker in blockers)
                or not set(blockers).issubset(targets)
            ):
                raise SchemaError("remaining-blockers must be none or unique targeted finding IDs")
    _validate_tracker_semantics(tracker)
    return tracker


def _parse_finding_origin(value: str) -> tuple[str, str, str] | None:
    match = re.fullmatch(
        r"([A-Za-z0-9][A-Za-z0-9._/-]*)@(Critical|Important|Minor)@sha256=([0-9a-f]{64})",
        value,
    )
    return None if match is None else (match.group(1), match.group(2), match.group(3))


def _gate_finding_ids(gate: GateRecord) -> tuple[str, ...]:
    values = _csv(gate.findings)
    return tuple(parsed[0] if (parsed := _parse_finding_origin(value)) else value for value in values)


def _validate_tracker_semantics(tracker: Tracker) -> None:
    phase_ids = {phase.id for phase in tracker.phases}
    gate_ids = {gate.id for gate in tracker.gates}
    for task in tracker.tasks:
        if task.state == "[ ]" and any(
            value != "-" for value in (
                task.owner, task.attempt, task.result, task.checkpoints,
                task.source_ref, task.commits, task.artifacts,
                task.integration, task.verification, task.question,
            )
        ):
            raise SchemaError("unstarted task cannot carry lifecycle or proof state")
        if task.state in {"[~]", "[?]", "[x]"} and (
            task.owner == "-" or task.attempt == "-" or task.checkpoints == "-"
        ):
            raise SchemaError("started task needs owner, attempt, and checkpoints")
        if task.kind == "source" and task.state in {"[~]", "[?]"}:
            try:
                _attempt_baseline(task, task.attempt)
            except TransitionError as exc:
                raise SchemaError(str(exc)) from exc
        if task.state == "[~]":
            if any(
                value != "-" for value in (
                    task.source_ref, task.commits, task.artifacts, task.integration,
                )
            ):
                raise SchemaError("active task cannot claim completion or integration")
            resumed = any(
                re.fullmatch(rf"resumed:[^,]+->{re.escape(task.attempt)}@[^,]+", item)
                for item in _csv(task.checkpoints)
            )
            if (task.result != "-" or task.verification != "-") and not resumed:
                raise SchemaError("only a resumed active task may preserve prior result evidence")
        if task.state == "[?]" and (
            task.question == "-"
            or not any(item.startswith(f"blocked:{task.attempt}@") for item in _csv(task.checkpoints))
        ):
            raise SchemaError("blocked task needs its current question checkpoint")
        if task.state == "[?]" and any(
            value != "-" for value in (
                task.source_ref, task.commits, task.artifacts, task.integration,
            )
        ):
            raise SchemaError("blocked task cannot claim completion or integration")
        if task.state == "[x]":
            if task.result == "-" or task.verification == "-":
                raise SchemaError("completed task needs result and verification evidence")
            if task.kind == "source" and (
                task.source_ref == "-" or task.commits == "-" or task.integration == "N/A"
            ):
                raise SchemaError("completed source task needs source provenance and integration state")
            if task.kind == "artifact" and (
                task.artifacts == "-" or task.integration != "N/A"
            ):
                raise SchemaError("completed artifact task needs exact artifacts and N/A integration")
    for phase in tracker.phases:
        if phase.state == "[x]" and phase.verification == "-":
            raise SchemaError("verified phase needs verification evidence")
        if phase.state in {"[ ]", "[~]"} and phase.verification != "-":
            raise SchemaError("unverified phase cannot carry verification evidence")
        if phase.state == "[x]" and phase.gate != "-" and phase.gate not in gate_ids:
            raise SchemaError("phase refers to an unknown review gate")
    for gate in tracker.gates:
        if gate.type == "phase" and gate.phase not in phase_ids:
            raise SchemaError("phase review gate refers to an unknown phase")
        if gate.type == "master" and gate.phase != "-":
            raise SchemaError("master review gate cannot name a phase")
        if gate.state in {"in_progress", "re_reviewing", "blocked", "accepted"} and any(
            value == "-" for value in (gate.base, gate.head, gate.assignments)
        ):
            raise SchemaError("opened review gate needs its immutable edge and assignments")
        if gate.state in {"blocked", "accepted"} and any(
            value == "-" for value in (gate.reports, gate.verification)
        ):
            raise SchemaError("evaluated review gate needs reports and verification")
        if gate.state == "accepted" and gate.questions != "-":
            raise SchemaError("accepted review gate cannot retain unresolved questions")
        origins = tuple(_parse_finding_origin(value) for value in _csv(gate.findings))
        if any(origin is not None for origin in origins) and any(origin is None for origin in origins):
            raise SchemaError("gate findings cannot mix sealed and unsealed identities")
        if gate.state in {"blocked", "re_reviewing"} and gate.findings != "-" and any(
            origin is None for origin in origins
        ):
            raise SchemaError("active blocked/re-reviewing gate needs sealed finding origins")
        if len(_gate_finding_ids(gate)) != len(set(_gate_finding_ids(gate))):
            raise SchemaError("gate finding identities must be unique")
    active_rounds: dict[str, list[RemediationRecord]] = {}
    for row in tracker.remediation:
        if row.gate not in gate_ids:
            raise SchemaError("remediation row refers to an unknown gate")
        if row.state == "pending" and any(
            value != "-" for value in (
                row.fixers, row.released_fixers, row.findings, row.fix_plan,
                row.commits, row.verification, row.re_review,
            )
        ):
            raise SchemaError("pending remediation cannot carry lifecycle state")
        if row.state == "fixing" and (
            row.fixers == "-" or row.findings == "-" or row.fix_plan == "-"
            or row.commits != "-" or row.re_review != "-"
        ):
            raise SchemaError("fixing remediation has incomplete or impossible state")
        if row.state == "re_reviewing" and (
            row.fixers != "-" or row.released_fixers == "-" or row.findings == "-"
            or row.fix_plan == "-" or row.commits == "-" or row.verification == "-"
        ):
            raise SchemaError("re-reviewing remediation has incomplete state")
        if row.state == "complete" and (
            row.fixers != "-" or row.findings == "-" or row.fix_plan == "-"
            or row.commits == "-" or row.verification == "-" or row.re_review == "-"
        ):
            raise SchemaError("completed remediation has incomplete state")
        if row.state in {"fixing", "re_reviewing"}:
            active_rounds.setdefault(row.gate, []).append(row)
        gate = next(item for item in tracker.gates if item.id == row.gate)
        if row.state == "fixing" and gate.state != "blocked":
            raise SchemaError("fixing remediation requires its gate to remain blocked")
        if row.state == "re_reviewing" and gate.state != "re_reviewing":
            raise SchemaError("re-reviewing remediation requires a matching gate state")
    if any(len(rows) > 1 for rows in active_rounds.values()):
        raise SchemaError("a gate cannot have multiple active remediation rounds")
    for gate in tracker.gates:
        if gate.state == "re_reviewing" and not any(
            row.gate == gate.id and row.state == "re_reviewing"
            for row in tracker.remediation
        ):
            raise SchemaError("re-reviewing gate requires exactly one matching active round")


def _row(values: tuple[object, ...]) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"


def _render_table(header: tuple[str, ...], rows: tuple[tuple[object, ...], ...]) -> list[str]:
    return [_row(header), _row(tuple("---" for _ in header)), *[_row(row) for row in rows]]


def render_tracker(tracker: Tracker) -> str:
    task_rows = tuple(tuple(getattr(row, field) for field in TaskRecord.__dataclass_fields__) for row in tracker.tasks)
    phase_rows = tuple(tuple(getattr(row, field) for field in PhaseRecord.__dataclass_fields__) for row in tracker.phases)
    gate_rows = tuple(tuple(getattr(row, field) for field in GateRecord.__dataclass_fields__) for row in tracker.gates)
    remediation_rows = tuple(
        (
            row.gate, row.round_number, row.state, row.fixers, row.released_fixers,
            row.findings, row.fix_plan, row.commits, row.verification, row.re_review,
        )
        for row in tracker.remediation
    )
    blocks = [
        [_TRACKER_MARKER, "# Pipeline v2 — Progress Tracker"],
        ["## Run", *_render_table(("Field", "Value"), tracker.run_fields)],
        ["## Current State", *_render_table(("Field", "Value"), tracker.current_fields)],
        ["## Tasks", *_render_table(_TASK_HEADER, task_rows)],
        ["## Phases", *_render_table(_PHASE_HEADER, phase_rows)],
        ["## Gates", *_render_table(_GATE_HEADER, gate_rows)],
        ["## Remediation", *_render_table(_REMEDIATION_HEADER, remediation_rows)],
    ]
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"


def parse_worker_result(text: str) -> WorkerResult:
    headings = ("## Result", "## Checkpoints")
    sections = _sections(text, _RESULT_MARKER, "# Pipeline v2 — Worker Result", headings, SchemaError)
    values = dict(_key_values(sections["## Result"], _RESULT_KEYS, SchemaError))
    checkpoints = tuple(Checkpoint(*row) for row in _table(sections["## Checkpoints"], _CHECKPOINT_HEADER, SchemaError))
    _unique(checkpoints, "id", SchemaError)
    commits, artifacts, evidence = _csv(values["commits"]), _csv(values["artifacts"]), _csv(values["evidence"])
    if values["kind"] not in {"source", "artifact"} or values["status"] not in _WORKER_STATUSES:
        raise SchemaError("invalid worker kind or status")
    if any(not _TOKEN.fullmatch(values[key]) for key in ("run_id", "task_id", "attempt", "owner")):
        raise SchemaError("worker result needs valid run, task, attempt, and owner identities")
    if values["tests"] == "-" or not evidence:
        raise SchemaError("worker result needs tests and evidence")
    if any(checkpoint.status not in {"complete", "in_progress", "blocked"} or checkpoint.evidence == "-" for checkpoint in checkpoints):
        raise SchemaError("invalid worker checkpoint")
    completed = values["status"] in {"DONE", "DONE_WITH_CONCERNS"}
    if completed and values["kind"] == "source":
        if values["source_ref"] == "-" or not commits or artifacts or any(not _COMMIT.fullmatch(commit) for commit in commits):
            raise SchemaError("completed source result needs source ref and commits only")
    elif completed and (values["source_ref"] != "-" or commits or not artifacts):
        raise SchemaError("completed artifact result needs artifacts and no source provenance")
    elif not completed and values["kind"] == "source" and (values["source_ref"] != "-" or commits or artifacts):
        raise SchemaError("unfinished source result cannot claim completed provenance")
    elif not completed and values["kind"] == "artifact" and (values["source_ref"] != "-" or commits):
        raise SchemaError("unfinished artifact result cannot carry source provenance")
    if not completed and (values["question"] == "-" or not _TOKEN.fullmatch(values["question"])):
        raise SchemaError("blocked worker status needs a stable question reference")
    if values["status"] == "BLOCKED" and values["blocking_reason"] == "-":
        raise SchemaError("BLOCKED result needs a blocking reason")
    return WorkerResult(values["run_id"], values["task_id"], values["attempt"], values["owner"], values["kind"], values["status"], values["source_ref"], commits, artifacts, values["tests"], evidence, values["concerns"], values["question"], values["blocking_reason"], checkpoints)


def render_worker_result(result: WorkerResult) -> str:
    values = (
        result.run_id,
        result.task_id,
        result.attempt,
        result.owner,
        result.kind,
        result.status,
        result.source_ref,
        ",".join(result.commits) or "-",
        ",".join(result.artifacts) or "-",
        result.tests,
        ",".join(result.evidence) or "-",
        result.concerns,
        result.question,
        result.blocking_reason,
    )
    blocks = [
        [_RESULT_MARKER, "# Pipeline v2 — Worker Result"],
        ["## Result", *_render_table(("Field", "Value"), tuple(zip(_RESULT_KEYS, values)))],
        [
            "## Checkpoints",
            *_render_table(
                _CHECKPOINT_HEADER,
                tuple((checkpoint.id, checkpoint.status, checkpoint.evidence) for checkpoint in result.checkpoints),
            ),
        ],
    ]
    text = "\n\n".join("\n".join(block) for block in blocks) + "\n"
    if parse_worker_result(text) != result:
        raise SchemaError("worker result cannot be rendered canonically")
    return text


_PHASE_METADATA = re.compile(r"<!-- pipeline-v2-phase: id=([^;]+); deps=([^;]+); review_gate=([^;]+); review_reason=(.+) -->\Z")
_TASK_METADATA = re.compile(r"<!-- pipeline-v2-task: id=([^;]+); deps=([^;]+); kind=([^;]+); batch=([^;]+); order=([^;]+); write_scope=([^;]+); outputs=([^;]+) -->\Z")
_PHASE_SUITE = re.compile(r"<!-- pipeline-v2-phase-suite: id=([^;]+); commands=(.+) -->\Z")
_TASK_SUITE = re.compile(r"<!-- pipeline-v2-task-suite: id=([^;]+); commands=(.+) -->\Z")


def _parse_command_suite(raw: str) -> tuple[str, ...]:
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlanMetadataError("verification commands must be a JSON string array") from exc
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value or "|" in value or "\n" in value for value in values)
        or len(values) != len(set(values))
    ):
        raise PlanMetadataError("verification commands must be unique nonempty table-safe strings")
    return tuple(values)


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in path.parts) or any(character in value for character in "*?[]{}"):
        raise PlanMetadataError(f"unsupported repository-relative path: {value!r}")
    return path


def _validate_acyclic_dependencies(
    dependencies: dict[str, tuple[str, ...]],
    *,
    error_type: type[ValueError],
    subject: str,
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise error_type(f"{subject} dependency graph contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in dependencies[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in dependencies:
        visit(node)


def _parse_phase_document(path: Path) -> tuple[PhaseMetadata, tuple[PlannedTask, ...]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    phase_indexes = [index for index, line in enumerate(lines) if line.startswith("<!-- pipeline-v2-phase:")]
    if len(phase_indexes) != 1:
        raise PlanMetadataError("phase plan needs one valid ordered phase metadata comment")
    phase_index = phase_indexes[0]
    phase = _PHASE_METADATA.fullmatch(lines[phase_index])
    first_nonempty = next((line for line in lines if line.strip()), "")
    first_section = next((index for index, line in enumerate(lines) if line.startswith("## ")), len(lines))
    if phase is None or not re.fullmatch(r"# [^#].+", first_nonempty) or phase_index >= first_section:
        raise PlanMetadataError("phase metadata must be in the document header before the first section")
    assert phase is not None
    if phase.group(3) not in {"required", "final-only"} or not phase.group(4).strip():
        raise PlanMetadataError("invalid phase review metadata")
    phase_deps = () if phase.group(2) == "none" else tuple(phase.group(2).split(","))
    suite_indexes = [index for index, line in enumerate(lines) if line.startswith("<!-- pipeline-v2-phase-suite:")]
    if len(suite_indexes) != 1 or suite_indexes[0] != phase_index + 1:
        raise PlanMetadataError("phase suite must occur exactly once immediately after phase metadata")
    phase_suite = _PHASE_SUITE.fullmatch(lines[suite_indexes[0]])
    if phase_suite is None or phase_suite.group(1) != phase.group(1):
        raise PlanMetadataError("phase suite identity must match phase metadata")
    metadata = PhaseMetadata(
        phase.group(1), phase_deps, phase.group(3), phase.group(4),
        _parse_command_suite(phase_suite.group(2)),
    )
    tasks = []
    for index, line in enumerate(lines):
        if not line.startswith("<!-- pipeline-v2-task:"):
            continue
        match = _TASK_METADATA.fullmatch(line)
        if match is None:
            raise PlanMetadataError("task metadata keys are missing, unknown, or reordered")
        task_id, deps_raw, kind, batch, order_raw, scopes_raw, outputs_raw = match.groups()
        previous_task = next((candidate for candidate in reversed(lines[:index]) if candidate.strip()), "")
        if not re.fullmatch(rf"#{{2,6}} .*\b{re.escape(task_id)}\b.*", previous_task):
            raise PlanMetadataError(f"task metadata for {task_id} must immediately follow its task heading")
        if kind not in {"source", "artifact"} or not _TOKEN.fullmatch(task_id) or not _TOKEN.fullmatch(batch):
            raise PlanMetadataError("invalid task id, kind, or batch")
        try:
            order = int(order_raw)
            if order <= 0:
                raise ValueError
        except ValueError as exc:
            raise PlanMetadataError("task order must be a positive integer") from exc
        deps = () if deps_raw == "none" else tuple(deps_raw.split(","))
        if any(not _TOKEN.fullmatch(dep) for dep in deps):
            raise PlanMetadataError("invalid dependency id")
        scopes = tuple(scopes_raw.split(","))
        parsed_scopes = []
        for scope in scopes:
            if ":" not in scope:
                raise PlanMetadataError("write scope must be typed")
            scope_type, raw_scope = scope.split(":", 1)
            if scope_type not in {"file", "tree"}:
                raise PlanMetadataError("unsupported write scope type")
            parsed_scopes.append((scope_type, _safe_relative(raw_scope)))
        outputs = () if outputs_raw == "none" else tuple(outputs_raw.split(","))
        if (kind == "source") != (not outputs):
            raise PlanMetadataError("source uses outputs=none; artifact names exact outputs")
        for output_raw in outputs:
            output = _safe_relative(output_raw)
            if not any((scope_type == "file" and output == scope) or (scope_type == "tree" and scope in output.parents) for scope_type, scope in parsed_scopes):
                raise PlanMetadataError("artifact output is outside its write scope")
        suite_candidates = [
            candidate
            for candidate in lines[index + 1:index + 2]
            if candidate.startswith("<!-- pipeline-v2-task-suite:")
        ]
        if kind == "source":
            if len(suite_candidates) != 1:
                raise PlanMetadataError(f"source task {task_id} needs one adjacent verification suite")
            task_suite = _TASK_SUITE.fullmatch(suite_candidates[0])
            if task_suite is None or task_suite.group(1) != task_id:
                raise PlanMetadataError("task suite identity must match task metadata")
            verification_commands = _parse_command_suite(task_suite.group(2))
        else:
            if suite_candidates:
                raise PlanMetadataError("artifact tasks use exact outputs, not a source-task suite")
            verification_commands = ()
        tasks.append(PlannedTask(task_id, deps, kind, batch, order, scopes, outputs, verification_commands))
    if not 1 <= len(tasks) <= 12:
        raise PlanMetadataError("phase plan must contain between 1 and 12 tasks")
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        raise PlanMetadataError("duplicate task id")
    known = set(ids)
    if any(dependency not in known or dependency == task.id for task in tasks for dependency in task.deps):
        raise PlanMetadataError("unknown or self dependency")
    _validate_acyclic_dependencies(
        {task.id: task.deps for task in tasks},
        error_type=PlanMetadataError,
        subject="task",
    )
    return metadata, tuple(tasks)


def parse_phase_plan(path: Path) -> tuple[PlannedTask, ...]:
    """Return the immutable task definitions from one approved phase plan."""
    return _parse_phase_document(path)[1]


_LEGACY_TASK = re.compile(r"^- \[[ x~?]\] (?:T[0-9]+|RV|RVJ)\b")
_ARTIFACT_KEYS = ("spec", "master_plan", "phase_plans", "decisions", "findings")
_SUPPORTED_LOCAL_FILESYSTEMS = {
    "apfs", "btrfs", "ext2", "ext3", "ext4", "hfs", "hfsplus", "overlay",
    "tmpfs", "ufs", "xfs", "zfs",
}
_UNSUPPORTED_FILESYSTEMS = {
    "9p", "afs", "ceph", "cifs", "fuse.sshfs", "glusterfs", "lustre", "nfs",
    "nfs4", "smb", "smbfs",
}


def _diagnostic(run_dir: Path, detail: str) -> str:
    return f"{run_dir}: {detail}; no files were changed"


def _recognized_v1(text: str) -> bool:
    return (
        "# Pipeline — Progress Tracker" in text
        and "## Current State" in text
        and any(_LEGACY_TASK.match(line) for line in text.splitlines())
    )


def _existing_path(path: Path) -> Path:
    candidate = Path(path).resolve(strict=False)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.exists():
        raise FilesystemSuitabilityError(f"cannot identify an existing filesystem anchor for {path}")
    return candidate


def _decode_mountinfo(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _filesystem_fingerprint(*parts: object) -> str:
    return hashlib.sha256("\0".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _linux_filesystem(path: Path) -> tuple[str, str]:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise FilesystemSuitabilityError(f"cannot read /proc/self/mountinfo: {exc}") from exc
    resolved = _existing_path(path)
    matches: list[tuple[int, str, str, str]] = []
    for line in lines:
        fields = line.split()
        try:
            separator = fields.index("-")
            mount_point = Path(_decode_mountinfo(fields[4])).resolve(strict=False)
            fs_type = fields[separator + 1].casefold()
            source = _decode_mountinfo(fields[separator + 2])
        except (ValueError, IndexError):
            continue
        if resolved == mount_point or mount_point in resolved.parents:
            matches.append((len(mount_point.parts), mount_point.as_posix(), fs_type, source))
    if not matches:
        raise FilesystemSuitabilityError(f"no mountinfo entry contains {resolved}")
    _, mount_point, fs_type, source = max(matches)
    return fs_type, _filesystem_fingerprint("linux", os.stat(resolved).st_dev, mount_point, fs_type, source)


def _macos_filesystem(path: Path) -> tuple[str, str]:
    resolved = _existing_path(path)
    mount_result = subprocess.run(
        ("/usr/bin/stat", "-f", "%m", str(resolved)),
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    mount_point = mount_result.stdout.strip()
    if mount_result.returncode != 0 or not mount_point:
        raise FilesystemSuitabilityError(
            f"macOS mount-point probe failed: {mount_result.stderr.strip()}"
        )
    disk_result = subprocess.run(
        ("/usr/sbin/diskutil", "info", "-plist", mount_point),
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if disk_result.returncode != 0 or not disk_result.stdout:
        detail = disk_result.stderr.decode("utf-8", errors="replace").strip()
        raise FilesystemSuitabilityError(f"macOS filesystem metadata probe failed: {detail}")
    try:
        metadata = plistlib.loads(disk_result.stdout)
    except (plistlib.InvalidFileException, ValueError, TypeError) as exc:
        raise FilesystemSuitabilityError("macOS filesystem metadata is not a valid property list") from exc
    fs_type = metadata.get("FilesystemType")
    recorded_mount = metadata.get("MountPoint")
    device = metadata.get("DeviceIdentifier")
    if (
        not isinstance(fs_type, str) or not fs_type
        or not isinstance(recorded_mount, str) or Path(recorded_mount) != Path(mount_point)
        or not isinstance(device, str) or not device
        or not (Path(mount_point) == resolved or Path(mount_point) in resolved.parents)
    ):
        raise FilesystemSuitabilityError("macOS filesystem metadata is missing or inconsistent")
    normalized = fs_type.casefold()
    return normalized, _filesystem_fingerprint(
        "darwin", os.stat(resolved).st_dev, mount_point, normalized, device,
    )


def _windows_filesystem(path: Path) -> tuple[str, str]:  # pragma: no cover - simulation tested
    import ctypes
    from ctypes import wintypes

    resolved = str(_existing_path(path))
    if resolved.startswith("\\\\"):
        return "remote", _filesystem_fingerprint("windows", resolved)
    volume = Path(resolved).anchor
    drive_type = ctypes.windll.kernel32.GetDriveTypeW(wintypes.LPCWSTR(volume))
    if drive_type == 4:  # DRIVE_REMOTE
        return "remote", _filesystem_fingerprint("windows", volume, drive_type)
    fs_name = ctypes.create_unicode_buffer(256)
    if not ctypes.windll.kernel32.GetVolumeInformationW(
        wintypes.LPCWSTR(volume), None, 0, None, None, None, fs_name, len(fs_name)
    ):
        raise FilesystemSuitabilityError("Windows GetVolumeInformationW failed")
    fs_type = fs_name.value.casefold()
    return fs_type, _filesystem_fingerprint("windows", volume.casefold(), drive_type, fs_type)


def classify_filesystem(path: Path) -> FilesystemInfo:
    """Classify the containing mount/volume without mutating it."""
    system = platform.system()
    try:
        if system == "Linux":
            fs_type, fingerprint = _linux_filesystem(path)
        elif system == "Darwin":
            fs_type, fingerprint = _macos_filesystem(path)
        elif system == "Windows":
            fs_type, fingerprint = _windows_filesystem(path)
        else:
            return FilesystemInfo("unknown", system.casefold() or "unknown", _filesystem_fingerprint(system, _existing_path(path)))
    except FilesystemSuitabilityError:
        return FilesystemInfo("unknown", "probe-failed", _filesystem_fingerprint(system, _existing_path(path)))
    if fs_type in _UNSUPPORTED_FILESYSTEMS or fs_type == "remote":
        classification = "unsupported"
    elif fs_type in _SUPPORTED_LOCAL_FILESYSTEMS or (system == "Windows" and fs_type in {"ntfs", "refs"}):
        classification = "supported-local"
    else:
        classification = "unknown"
    return FilesystemInfo(classification, fs_type, fingerprint)


def _filesystem_ack(
    info: FilesystemInfo,
    acknowledgement: str | None,
    *,
    decisions_path: Path | None = None,
    run_id: str | None = None,
) -> str:
    if info.classification == "unsupported":
        raise FilesystemSuitabilityError(f"filesystem {info.fs_type} is known unsupported for tracker mutation")
    if info.classification == "supported-local":
        if acknowledgement not in {None, "N/A"}:
            raise FilesystemSuitabilityError("supported local filesystem does not accept an override acknowledgement")
        return "N/A"
    if not acknowledgement or acknowledgement != acknowledgement.strip() or "|" in acknowledgement:
        raise FilesystemSuitabilityError(
            f"filesystem {info.fs_type} suitability is unknown; an explicit fingerprint-bound acknowledgement is required"
        )
    if not re.fullmatch(rf"D-[0-9]+@{re.escape(info.fingerprint)}", acknowledgement):
        raise FilesystemSuitabilityError("filesystem acknowledgement is not bound to the current mount/volume fingerprint")
    decision_ref = acknowledgement.split("@", 1)[0]
    if decisions_path is None or run_id is None:
        raise FilesystemSuitabilityError("unknown-filesystem acknowledgement needs an authoritative run decision")
    try:
        sections = _decision_sections(Path(decisions_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TransitionError) as exc:
        raise FilesystemSuitabilityError(
            f"cannot read filesystem authorization decision at {decisions_path}: {exc}"
        ) from exc
    lines = sections.get(decision_ref)
    if lines is None:
        raise FilesystemSuitabilityError(f"filesystem authorization decision {decision_ref} is missing")
    answers = _field_lines(lines, "Answer")
    questions = _field_lines(lines, "Question")
    statuses = _field_lines(lines, "Status")
    scopes = _field_lines(lines, "Scope")
    if len(questions) != 1 or len(answers) != 1 or len(statuses) != 1 or len(scopes) != 1:
        raise FilesystemSuitabilityError("filesystem decision evidence is missing, duplicated, or conflicting")
    _require_decision_action(lines, "filesystem.authorize", FilesystemSuitabilityError)
    answer = answers[0].strip().rstrip(".")
    if (
        not answer
        or answer.casefold() in {"approved", "yes", "continue", "proceed", "go"}
        or statuses[0].strip().rstrip(".").casefold() != "resolved"
    ):
        raise FilesystemSuitabilityError("filesystem decision is unresolved or lacks an explicit answer")
    scope = scopes[0]
    combined = f"{answer} {scope}".casefold()
    if (
        run_id.casefold() not in scope.casefold()
        or info.fingerprint.casefold() not in scope.casefold()
        or info.fs_type.casefold() not in combined
    ):
        raise FilesystemSuitabilityError("filesystem decision is unrelated to this run, type, or fingerprint")
    for other_ref, other_lines in sections.items():
        if other_ref == decision_ref:
            continue
        other_status = _field_lines(other_lines, "Status")
        other_questions = _field_lines(other_lines, "Question")
        other_answers = _field_lines(other_lines, "Answer")
        other_scope = " ".join(_field_lines(other_lines, "Scope")).casefold()
        if (
            len(other_status) == 1
            and other_status[0].strip().rstrip(".").casefold() in {"open", "pending", "blocked"}
            and run_id.casefold() in other_scope
            and info.fingerprint.casefold() in other_scope
        ):
            raise FilesystemSuitabilityError(f"unresolved decision {other_ref} still conflicts with filesystem authority")
        if (
            len(other_status) == 1
            and other_status[0].strip().rstrip(".").casefold() == "resolved"
            and len(other_questions) == 1
            and other_questions[0].strip().rstrip(".").casefold()
            == questions[0].strip().rstrip(".").casefold()
            and len(other_answers) == 1
            and other_answers[0].strip().rstrip(".").casefold() != answer.casefold()
            and run_id.casefold() in other_scope
            and info.fingerprint.casefold() in other_scope
        ):
            raise FilesystemSuitabilityError(f"resolved decision {other_ref} conflicts with filesystem authority")
    return acknowledgement


def _validate_tracker_filesystem(run_dir: Path, tracker: Tracker) -> FilesystemInfo:
    info = classify_filesystem(run_dir)
    recorded = dict(tracker.run_fields)
    _filesystem_ack(
        info,
        recorded["filesystem_ack"],
        decisions_path=_resolved_reference(run_dir, recorded["decisions"]),
        run_id=tracker.run_id,
    )
    if (
        recorded["filesystem_class"], recorded["filesystem_type"], recorded["filesystem_fingerprint"]
    ) != (info.classification, info.fs_type, info.fingerprint):
        raise FilesystemSuitabilityError("tracker filesystem identity changed; explicit reconciliation is required")
    return info


def validate_run(run_dir: Path) -> Tracker:
    """Read and validate a v2 run without mutating it."""
    run_dir = Path(run_dir)
    progress = run_dir / "progress.md"
    if not progress.is_file():
        raise SchemaError(_diagnostic(run_dir, "missing progress.md/schema information"))
    try:
        text = progress.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SchemaError(_diagnostic(run_dir, f"unreadable progress.md ({exc})")) from exc
    if _recognized_v1(text):
        raise LegacySchemaError(
            _diagnostic(
                run_dir,
                "v2 cannot resume this legacy format; continuing the old run requires "
                "a compatible v1 version or an explicitly approved fresh v2 run",
            )
        )
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if first_line != _TRACKER_MARKER:
        if first_line.startswith("<!-- pipeline-run/"):
            detail = f"unknown or unsupported schema marker {first_line!r}"
        else:
            detail = "missing v2 schema marker and state is not recognized v1"
        raise SchemaError(_diagnostic(run_dir, detail))
    try:
        return parse_tracker(text)
    except SchemaError as exc:
        raise SchemaError(_diagnostic(run_dir, f"malformed v2 tracker ({exc})")) from exc


def _write_initial_tracker(path: Path, text: str) -> None:
    """Publish a complete first tracker atomically without replacing a winner."""
    descriptor = -1
    temporary: str | None = None
    published = False
    try:
        descriptor, temporary = tempfile.mkstemp(
            dir=str(path.parent), prefix=".progress.", suffix=".tmp"
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            descriptor = -1
            handle.write(text)
            _sync_file(handle)
        os.link(temporary, path)
        published = True
        os.unlink(temporary)
        temporary = None
        _sync_directory(path.parent)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        if not published:
            raise TrackerWriteError(
                f"initial tracker publication failed before atomic publication; progress.md was not replaced: {exc}"
            ) from exc
        observed = None
        try:
            observed = validate_run(path.parent)
        except SchemaError:
            pass
        raise UpdateOutcomeUncertain(
            "initial tracker publication may have applied before directory synchronization failed; "
            f"reconcile progress.md before retry: {exc}",
            observed,
        ) from exc


def _initial_tracker(
    *,
    run_dir: Path,
    run_id: str,
    base_commit: str,
    target_branch: str,
    worker_limit: int,
    artifacts: dict[str, str],
    filesystem: FilesystemInfo,
    filesystem_ack: str,
) -> Tracker:
    if tuple(artifacts) != _ARTIFACT_KEYS:
        raise SchemaError(f"artifacts must contain exactly these ordered keys: {_ARTIFACT_KEYS!r}")
    phase_paths = tuple(
        _resolved_reference(run_dir, item)
        for item in artifacts["phase_plans"].split(",")
    )
    if not phase_paths:
        raise SchemaError("at least one phase plan is required")
    phase_documents = tuple(_parse_phase_document(path) for path in phase_paths)
    phase_ids = [metadata.id for metadata, _ in phase_documents]
    if len(phase_ids) != len(set(phase_ids)):
        raise SchemaError("phase IDs must be unique")
    known_phases = set(phase_ids)
    if any(dep not in known_phases for metadata, _ in phase_documents for dep in metadata.deps):
        raise SchemaError("phase dependency is unknown")
    phase_order = {phase_id: index for index, phase_id in enumerate(phase_ids)}
    if any(
        phase_order[dependency] >= phase_order[metadata.id]
        for metadata, _ in phase_documents
        for dependency in metadata.deps
    ):
        raise SchemaError("phase dependencies must precede their dependent phase in approved order")
    _validate_acyclic_dependencies(
        {metadata.id: metadata.deps for metadata, _ in phase_documents},
        error_type=SchemaError,
        subject="phase",
    )
    if phase_documents[0][0].deps:
        raise SchemaError("the initial phase cannot have an unsatisfied dependency")
    tasks = tuple(
        TaskRecord(task.id, task.kind, "[ ]", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-")
        for _, planned in phase_documents
        for task in planned
    )
    required_gates = tuple(
        GateRecord(f"phase-{metadata.id}", "phase", metadata.id, "pending", "-", "-", "-", "-", "-", artifacts["findings"], "-")
        for metadata, _ in phase_documents
        if metadata.review_gate == "required"
    )
    master_gate = GateRecord("master", "master", "-", "pending", base_commit, "-", "-", "-", "-", artifacts["findings"], "-")
    phases = tuple(
        PhaseRecord(
            metadata.id,
            "[ ]",
            "-",
            metadata.review_gate,
            metadata.review_reason,
            f"phase-{metadata.id}" if metadata.review_gate == "required" else "-",
        )
        for metadata, _ in phase_documents
    )
    gates = required_gates + (master_gate,)
    remediation = tuple(RemediationRecord(gate.id, 1, "pending", "-", "-", "-", "-", "-", "-", "-") for gate in gates)
    first_metadata, first_tasks = phase_documents[0]
    return Tracker(
        tuple(
            zip(
                _RUN_KEYS,
                (
                    run_id,
                    "2",
                    "none",
                    base_commit,
                    target_branch,
                    str(worker_limit),
                    filesystem.classification,
                    filesystem.fs_type,
                    filesystem.fingerprint,
                    filesystem_ack,
                    artifacts["spec"],
                    artifacts["master_plan"],
                    artifacts["phase_plans"],
                    artifacts["decisions"],
                    artifacts["findings"],
                    "0",
                    "initialized",
                ),
            )
        ),
        (("phase", first_metadata.id), ("batch", first_tasks[0].batch), ("next_action", first_tasks[0].id)),
        tasks,
        phases,
        gates,
        remediation,
    )


def initialize_run(
    run_dir: Path,
    *,
    run_id: str,
    base_commit: str,
    target_branch: str,
    worker_limit: int,
    artifacts: dict[str, str],
    approved_existing: tuple[Path, ...],
    filesystem_acknowledgement: str | None = None,
) -> Tracker:
    """Create a new v2 tracker without overwriting any existing state."""
    run_dir = Path(run_dir)
    filesystem = classify_filesystem(run_dir)
    filesystem_ack = _filesystem_ack(
        filesystem,
        filesystem_acknowledgement,
        decisions_path=_resolved_reference(run_dir, artifacts["decisions"]),
        run_id=run_id,
    )
    phase_paths = tuple(artifacts["phase_plans"].split(","))
    try:
        _master_phase_paths(
            run_dir, artifacts["master_plan"], phase_paths,
            error_type=SchemaError,
        )
    except (OSError, UnicodeError) as exc:
        raise SchemaError(
            _diagnostic(run_dir, f"approved master plan is unreadable ({exc})")
        ) from exc
    tracker = _initial_tracker(
        run_dir=run_dir,
        run_id=run_id,
        base_commit=base_commit,
        target_branch=target_branch,
        worker_limit=worker_limit,
        artifacts=artifacts,
        filesystem=filesystem,
        filesystem_ack=filesystem_ack,
    )
    text = render_tracker(tracker)
    parse_tracker(text)
    if run_dir.exists() and not run_dir.is_dir():
        raise SchemaError(_diagnostic(run_dir, "run path exists and is not a directory"))
    progress = run_dir / "progress.md"
    if progress.exists():
        try:
            validate_run(run_dir)
        except LegacySchemaError:
            raise
        except SchemaError as exc:
            raise exc
        raise SchemaError(_diagnostic(run_dir, "a valid v2 tracker already exists; use resume"))
    approved = {Path(path).resolve() for path in approved_existing}
    existing = {path.resolve() for path in run_dir.rglob("*")} if run_dir.exists() else set()
    if existing != approved:
        raise SchemaError(_diagnostic(run_dir, "existing entries do not exactly match approved_existing"))
    for path in existing:
        if path.is_file():
            try:
                contents = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise SchemaError(_diagnostic(run_dir, f"approved existing artifact is unreadable ({exc})")) from exc
            if _recognized_v1(contents) or _TRACKER_MARKER in contents or "<!-- pipeline-run/" in contents:
                raise SchemaError(_diagnostic(run_dir, f"approved path {path} contains tracker/schema-like state"))
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_initial_tracker(progress, text)
    return validate_run(run_dir)


def inspect_run(run_dir: Path) -> dict[str, object]:
    """Return a read-only summary of validated v2 state."""
    run_dir = Path(run_dir)
    tracker = validate_run(run_dir)
    persisted_next_action = dict(tracker.current_fields)["next_action"]
    diagnostic = "-"
    try:
        derived_next_action = derive_next_action(run_dir, tracker)
    except (OSError, UnicodeError, PlanMetadataError, TransitionError) as exc:
        derived_next_action = None
        diagnostic = f"next action could not be derived: {exc}"
    summary = {
        "run_id": tracker.run_id,
        "target_branch": tracker.target_branch,
        "worker_limit": tracker.worker_limit,
        "revision": tracker.revision,
        "phase": dict(tracker.current_fields)["phase"],
        "next_action": persisted_next_action,
        "persisted_next_action": persisted_next_action,
        "derived_next_action": derived_next_action,
        "next_action_consistent": persisted_next_action == derived_next_action,
        "next_action_diagnostic": diagnostic,
        "task_counts": {state: sum(task.state == state for task in tracker.tasks) for state in sorted(_TASK_STATES)},
    }
    return summary


_POSIX_CONTENTION = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}
_WINDOWS_CONTENTION = {errno.EACCES, errno.EDEADLOCK}


def select_lock_impl(fcntl_module, msvcrt_module):
    """Select an inspected standard-library lock implementation.

    The Windows path follows the repository's Craft implementation. It is
    executable code but remains a simulation-only support claim in this Linux
    environment until native Windows process tests exercise it.
    """
    if fcntl_module is not None and hasattr(fcntl_module, "flock"):
        def acquire(fd: int) -> bool:
            try:
                fcntl_module.flock(fd, fcntl_module.LOCK_EX | fcntl_module.LOCK_NB)
            except OSError as exc:
                if exc.errno in _POSIX_CONTENTION:
                    return False
                raise
            return True

        def release(fd: int) -> None:
            fcntl_module.flock(fd, fcntl_module.LOCK_UN)

        return acquire, release, "POSIX flock; native platform test required"
    if msvcrt_module is not None and hasattr(msvcrt_module, "locking"):
        def acquire(fd: int) -> bool:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt_module.locking(fd, msvcrt_module.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in _WINDOWS_CONTENTION:
                    return False
                raise
            return True

        def release(fd: int) -> None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt_module.locking(fd, msvcrt_module.LK_UNLCK, 1)

        return acquire, release, "Implemented; simulation-tested; native Windows verification pending."
    raise LockUnavailableError(
        "no supported OS-backed lock primitive: fcntl.flock and msvcrt.locking are unavailable"
    )


@contextmanager
def _exclusive_lock(run_dir: Path, *, timeout_s: float) -> Iterator[None]:
    """Hold the stable run-local lock without ever unlinking its path."""
    if timeout_s < 0:
        raise LockUnavailableError("lock timeout must be nonnegative")
    lock_path = Path(run_dir) / ".pipeline-state.lock"
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise LockUnavailableError(f"cannot open run-local lock {lock_path}: {exc}") from exc
    acquired = False
    acquire = release = None
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
            os.fsync(fd)
        try:
            acquire, release, _ = select_lock_impl(fcntl, msvcrt)
        except LockUnavailableError:
            raise
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                acquired = acquire(fd)
            except OSError as exc:
                raise LockUnavailableError(f"cannot acquire run-local lock {lock_path}: {exc}") from exc
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise LockBusyError(f"run-local lock busy at {lock_path} after {timeout_s:.3f}s")
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        try:
            descriptor = os.fstat(fd)
            named = os.stat(lock_path)
        except OSError as exc:
            raise LockUnavailableError(f"cannot verify stable run-local lock {lock_path}: {exc}") from exc
        if (descriptor.st_dev, descriptor.st_ino) != (named.st_dev, named.st_ino):
            raise LockUnavailableError(f"run-local lock resource changed while acquiring {lock_path}")
        yield
    finally:
        if acquired and release is not None:
            try:
                release(fd)
            except OSError:
                pass
        os.close(fd)


def _sync_file(handle) -> None:
    handle.flush()
    os.fsync(handle.fileno())


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":  # native semantics remain pending verification
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _with_transition_identity(tracker: Tracker, transition_id: str, revision: int) -> Tracker:
    fields = tuple(
        (key, str(revision) if key == "revision" else transition_id if key == "last_transition" else value)
        for key, value in tracker.run_fields
    )
    return replace(tracker, run_fields=fields)


def _replace_tracker(run_dir: Path, text: str, transition_id: str) -> None:
    progress = run_dir / "progress.md"
    descriptor = -1
    temporary: str | None = None
    replaced = False
    try:
        descriptor, temporary = tempfile.mkstemp(
            dir=str(run_dir), prefix=".progress.", suffix=".tmp"
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            descriptor = -1
            handle.write(text)
            _sync_file(handle)
        os.replace(temporary, progress)
        replaced = True
        temporary = None
        _sync_directory(run_dir)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if not replaced:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            raise TrackerWriteError(
                f"tracker update {transition_id} failed before replacement; old tracker preserved: {exc}"
            ) from exc
        observed = None
        try:
            observed = validate_run(run_dir)
        except SchemaError:
            pass
        raise UpdateOutcomeUncertain(
            f"tracker update {transition_id} may have applied after replacement; reconcile revision/transition identity before retry: {exc}",
            observed,
        ) from exc


def locked_tracker_update(
    run_dir: Path,
    transition_id: str,
    transition: Callable[[Tracker], Tracker],
    *,
    timeout_s: float,
    replay_returns_current: bool = True,
    refresh_next_action: bool = False,
) -> Tracker:
    """Validate and atomically apply one idempotent controller transition."""
    if not _TOKEN.fullmatch(transition_id):
        raise SchemaError("invalid transition identity")
    run_dir = Path(run_dir)
    preflight = validate_run(run_dir)
    _validate_tracker_filesystem(run_dir, preflight)
    with _exclusive_lock(run_dir, timeout_s=timeout_s):
        current = validate_run(run_dir)
        _validate_tracker_filesystem(run_dir, current)
        if current.last_transition == transition_id and replay_returns_current:
            return current
        proposed = transition(current)
        if not isinstance(proposed, Tracker):
            raise SchemaError("transition must return a Tracker")
        if proposed.run_id != current.run_id or proposed.base_commit != current.base_commit or proposed.target_branch != current.target_branch:
            raise SchemaError("transition cannot change run identity")
        if refresh_next_action:
            proposed = _with_next_action(
                proposed,
                derive_next_action(run_dir, proposed),
            )
        updated = _with_transition_identity(proposed, transition_id, current.revision + 1)
        canonical = render_tracker(updated)
        reparsed = parse_tracker(canonical)
        _replace_tracker(run_dir, canonical, transition_id)
        return reparsed


def _parse_pre_adoption_tracker(text: str) -> tuple[
    tuple[tuple[str, str], ...], tuple[tuple[str, str], ...], tuple[TaskRecord, ...],
    tuple[PhaseRecord, ...], tuple[GateRecord, ...], tuple[tuple[str, ...], ...],
]:
    """Frozen parser for the exact first pre-release v2 tracker format."""
    headings = ("## Run", "## Current State", "## Tasks", "## Phases", "## Gates", "## Remediation")
    sections = _sections(text, _TRACKER_MARKER, "# Pipeline v2 — Progress Tracker", headings, SchemaError)
    run_fields = _key_values(sections["## Run"], _PRE_ADOPTION_RUN_KEYS, SchemaError)
    current_fields = _key_values(sections["## Current State"], _CURRENT_KEYS, SchemaError)
    run = dict(run_fields)
    if not _TOKEN.fullmatch(run["run_id"]) or not _COMMIT.fullmatch(run["base_commit"]):
        raise SchemaError("invalid pre-adoption run identity")
    try:
        if int(run["worker_limit"]) <= 0 or int(run["revision"]) < 0:
            raise ValueError
    except ValueError as exc:
        raise SchemaError("invalid pre-adoption numeric field") from exc
    if not _TOKEN.fullmatch(run["last_transition"]):
        raise SchemaError("invalid pre-adoption transition identity")
    tasks = tuple(TaskRecord(*row) for row in _table(sections["## Tasks"], _TASK_HEADER, SchemaError))
    phases = tuple(PhaseRecord(*row) for row in _table(sections["## Phases"], _PHASE_HEADER, SchemaError))
    gates = tuple(GateRecord(*row) for row in _table(sections["## Gates"], _GATE_HEADER, SchemaError))
    remediation = _table(sections["## Remediation"], _PRE_ADOPTION_REMEDIATION_HEADER, SchemaError)
    for collection, attribute in ((tasks, "id"), (phases, "id"), (gates, "id")):
        _unique(collection, attribute, SchemaError)
    round_ids: list[tuple[str, int]] = []
    for row in remediation:
        try:
            number = int(row[1])
        except ValueError as exc:
            raise SchemaError("invalid pre-adoption remediation round") from exc
        round_ids.append((row[0], number))
        if number <= 0 or row[2] not in {"pending", "in_progress", "blocked", "complete"}:
            raise SchemaError("invalid pre-adoption remediation state")
    if len(round_ids) != len(set(round_ids)):
        raise SchemaError("duplicate pre-adoption remediation round")
    if any(task.kind not in {"source", "artifact"} or task.state not in _TASK_STATES for task in tasks):
        raise SchemaError("invalid pre-adoption task")
    if any(phase.state not in _TASK_STATES or phase.review_gate not in {"required", "final-only"} for phase in phases):
        raise SchemaError("invalid pre-adoption phase")
    if any(gate.type not in {"phase", "master"} or gate.state not in {"pending", "in_progress", "blocked", "accepted"} for gate in gates):
        raise SchemaError("invalid pre-adoption gate")
    return run_fields, current_fields, tasks, phases, gates, remediation


def _publish_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            _sync_file(handle)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise EvidenceError(f"immutable adoption artifact conflicts with existing file: {path}")
        _sync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def adopt_pre_release_tracker(
    run_dir: Path,
    *,
    expected_run_id: str,
    expected_revision: int,
    expected_sha256: str,
    adoption_id: str,
    active_fixers: dict[str, tuple[str, ...]],
    filesystem_acknowledgement: str | None = None,
) -> Tracker:
    """Explicitly adopt the one deployed pre-release v2 format; never called by resume."""
    if not _TOKEN.fullmatch(adoption_id) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise SchemaError("invalid adoption identity or expected digest")
    run_dir = Path(run_dir).resolve()
    if expected_run_id != _PRE_RELEASE_ADOPTION_RUN_ID or run_dir.name != _PRE_RELEASE_ADOPTION_RUN_ID:
        raise SchemaError("pre-release schema adoption is restricted to the identified Pipeline v2 rebuild run")
    progress = run_dir / "progress.md"
    try:
        source = progress.read_bytes()
    except OSError as exc:
        raise SchemaError(_diagnostic(run_dir, f"cannot read adoption source ({exc})")) from exc
    adoption_value = f"{adoption_id}@{expected_sha256}"
    try:
        current_new = parse_tracker(source.decode("utf-8"))
    except (SchemaError, UnicodeError):
        current_new = None
    if current_new is not None:
        fields = dict(current_new.run_fields)
        if current_new.run_id == expected_run_id and fields["schema_adoption"] == adoption_value:
            return current_new
        raise SchemaError("tracker is already in the strict format with a different adoption identity")
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise SchemaError("pre-adoption tracker digest does not match the expected source bytes")
    decoded = source.decode("utf-8")
    old_run, current_fields, tasks, phases, gates, old_remediation = _parse_pre_adoption_tracker(decoded)
    old = dict(old_run)
    if old["run_id"] != expected_run_id or int(old["revision"]) != expected_revision:
        raise SchemaError("pre-adoption run identity or revision does not match")
    if any(task.state == "[~]" for task in tasks) or any(gate.state == "in_progress" for gate in gates):
        raise TransitionError("pre-release adoption requires a quiescent task/reviewer state")
    filesystem = classify_filesystem(run_dir)
    filesystem_ack = _filesystem_ack(
        filesystem,
        filesystem_acknowledgement,
        decisions_path=_resolved_reference(run_dir, old["decisions"]),
        run_id=old["run_id"],
    )
    mapped: list[RemediationRecord] = []
    active_gates: set[str] = set()
    for row in old_remediation:
        gate, number_raw, state, findings, fix_plan, commits, verification, re_review = row
        fixers = active_fixers.get(gate, ())
        if state == "in_progress":
            if not fixers or len(fixers) != len(set(fixers)) or any(not _TOKEN.fullmatch(owner) for owner in fixers):
                raise TransitionError(f"active remediation {gate} needs verified fixer ownership for adoption")
            active_gates.add(gate)
            mapped_state = "fixing"
            active_value = ",".join(fixers)
        else:
            if fixers:
                raise TransitionError(f"inactive remediation {gate} cannot gain active fixers during adoption")
            mapped_state = state
            active_value = "-"
        mapped.append(
            RemediationRecord(
                gate, int(number_raw), mapped_state, active_value, "-", findings,
                fix_plan, commits, verification, re_review,
            )
        )
    if set(active_fixers) != active_gates:
        raise TransitionError("active fixer mapping does not exactly match active remediation rows")
    run_values = (
        old["run_id"], "2", adoption_value, old["base_commit"], old["target_branch"],
        old["worker_limit"], filesystem.classification, filesystem.fs_type,
        filesystem.fingerprint, filesystem_ack, old["spec"], old["master_plan"],
        old["phase_plans"], old["decisions"], old["findings"], str(expected_revision + 1),
        adoption_id,
    )
    adopted = Tracker(tuple(zip(_RUN_KEYS, run_values)), current_fields, tasks, phases, gates, tuple(mapped))
    canonical = render_tracker(adopted)
    installed = parse_tracker(canonical)
    snapshot_path = run_dir / "agent-output" / f"{adoption_id}-snapshot.md"
    receipt_path = run_dir / "agent-output" / f"{adoption_id}-receipt.md"
    with _exclusive_lock(run_dir, timeout_s=5.0):
        observed = progress.read_bytes()
        if observed != source:
            raise TransitionError("pre-adoption tracker changed before the adoption lock was acquired")
        _parse_pre_adoption_tracker(observed.decode("utf-8"))
        try:
            _publish_immutable(snapshot_path, source)
        except OSError as exc:
            raise TrackerWriteError(f"schema adoption failed before replacement; old tracker preserved: {exc}") from exc
        _replace_tracker(run_dir, canonical, adoption_id)
        reread = validate_run(run_dir)
        if reread != installed:
            raise UpdateOutcomeUncertain("adopted tracker did not re-read as the validated target", reread)
        receipt = (
            "# Pipeline v2 tracker adoption receipt\n\n"
            f"- run_id: {expected_run_id}\n"
            f"- adoption_id: {adoption_id}\n"
            f"- old_revision: {expected_revision}\n"
            f"- new_revision: {reread.revision}\n"
            f"- old_sha256: {expected_sha256}\n"
            f"- new_sha256: {hashlib.sha256(canonical.encode('utf-8')).hexdigest()}\n"
            f"- tasks_preserved: {len(tasks)}\n"
            f"- gates_preserved: {len(gates)}\n"
            f"- remediation_rows_preserved: {len(mapped)}\n"
        ).encode("utf-8")
        try:
            _publish_immutable(receipt_path, receipt)
        except (OSError, EvidenceError) as exc:
            raise UpdateOutcomeUncertain(
                f"schema adoption applied but receipt publication failed: {exc}", reread,
            ) from exc
        return reread


def _replace_task(tracker: Tracker, replacement: TaskRecord) -> Tracker:
    return replace(
        tracker,
        tasks=tuple(replacement if task.id == replacement.id else task for task in tracker.tasks),
    )


def _task_record(tracker: Tracker, task_id: str) -> TaskRecord:
    matches = [task for task in tracker.tasks if task.id == task_id]
    if len(matches) != 1:
        raise TransitionError(f"unknown task {task_id}")
    return matches[0]


def _project_root(run_dir: Path) -> Path:
    for candidate in (Path(run_dir), *Path(run_dir).parents):
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd()


def _resolved_reference(run_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _project_root(run_dir) / path


def _planned_tasks(run_dir: Path, tracker: Tracker) -> dict[str, PlannedTask]:
    paths = dict(tracker.run_fields)["phase_plans"].split(",")
    tasks: dict[str, PlannedTask] = {}
    for value in paths:
        for task in parse_phase_plan(_resolved_reference(run_dir, value)):
            if task.id in tasks:
                raise TransitionError(f"duplicate planned task {task.id}")
            tasks[task.id] = task
    return tasks


def _approved_task_definition(
    run_dir: Path,
    tracker: Tracker,
    phase_plan: Path,
    task_id: str,
) -> PlannedTask:
    approved_paths = {
        _resolved_reference(run_dir, value).resolve()
        for value in dict(tracker.run_fields)["phase_plans"].split(",")
    }
    supplied = Path(phase_plan).resolve()
    if supplied not in approved_paths:
        raise TransitionError("phase plan is not one of the run's authoritative approved plans")
    supplied_tasks = {task.id: task for task in parse_phase_plan(supplied)}
    authoritative = _planned_tasks(run_dir, tracker)
    definition = supplied_tasks.get(task_id)
    if definition is None or authoritative.get(task_id) != definition:
        raise TransitionError("task metadata does not match the authoritative approved plans")
    return definition


def _scope_parts(scope: str) -> tuple[str, PurePosixPath]:
    kind, value = scope.split(":", 1)
    return kind, PurePosixPath(value)


def _scopes_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    for left_raw in left:
        left_kind, left_path = _scope_parts(left_raw)
        for right_raw in right:
            right_kind, right_path = _scope_parts(right_raw)
            if left_kind == right_kind == "file" and left_path == right_path:
                return True
            if left_kind == "tree" and (left_path == right_path or left_path in right_path.parents):
                return True
            if right_kind == "tree" and (right_path == left_path or right_path in left_path.parents):
                return True
    return False


def _decision_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^## (D-[0-9]+)(?:\s|$)", line)
        if match:
            current = match.group(1)
            if current in sections:
                raise TransitionError(f"duplicate decision {current}")
            sections[current] = []
        elif current is not None and not line.startswith("## "):
            sections[current].append(line)
    return sections


def _field_lines(lines: list[str], field: str) -> list[str]:
    prefix = f"- **{field}:**"
    return [line[len(prefix):].strip() for line in lines if line.startswith(prefix)]


_DECISION_ACTIONS = frozenset({
    "task.resume",
    "review.resolve-question",
    "filesystem.authorize",
    "remediation.start-round",
    "none",
})


def _require_decision_action(
    lines: list[str],
    expected: str,
    error_type: type[Exception] = TransitionError,
) -> None:
    actions = _field_lines(lines, "Decision action")
    if len(actions) != 1:
        raise error_type("decision action is missing, duplicated, or ambiguous")
    action = actions[0]
    if action not in _DECISION_ACTIONS:
        raise error_type(f"unknown decision action {action!r}")
    if action != expected:
        raise error_type(f"decision action {action!r} cannot authorize {expected!r}")


def _scope_names_task(scope: str, task_id: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9._/-]){re.escape(task_id)}(?![A-Za-z0-9._/-])", scope) is not None


def _validate_decision(run_dir: Path, tracker: Tracker, task: TaskRecord, decision_ref: str) -> None:
    if task.question != decision_ref:
        raise TransitionError("decision reference does not match the task's current blocker")
    decisions_path = _resolved_reference(run_dir, dict(tracker.run_fields)["decisions"])
    try:
        text = decisions_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"cannot read recorded decisions at {decisions_path}: {exc}") from exc
    sections = _decision_sections(text)
    if decision_ref not in sections:
        raise TransitionError(f"decision {decision_ref} is missing")
    lines = sections[decision_ref]
    questions = _field_lines(lines, "Question")
    answers = _field_lines(lines, "Answer")
    statuses = _field_lines(lines, "Status")
    scopes = _field_lines(lines, "Scope") + _field_lines(lines, "Affected task")
    if len(questions) != 1 or len(answers) != 1 or len(statuses) != 1 or len(scopes) != 1:
        raise TransitionError("decision evidence is missing, duplicated, or conflicting")
    _require_decision_action(lines, "task.resume")
    answer = answers[0].strip().rstrip(".")
    if not answer or answer.casefold() in {"approved", "yes", "continue", "proceed", "go", "pending user response"}:
        raise TransitionError("generic approval or an empty answer cannot resolve a blocker")
    if statuses[0].strip().rstrip(".").casefold() != "resolved":
        raise TransitionError("decision is not resolved")
    if not _scope_names_task(scopes[0], task.id):
        raise TransitionError("decision is unrelated to the blocked task")
    for other_ref, other_lines in sections.items():
        if other_ref == decision_ref:
            continue
        other_statuses = _field_lines(other_lines, "Status")
        other_scopes = _field_lines(other_lines, "Scope") + _field_lines(other_lines, "Affected task")
        other_questions = _field_lines(other_lines, "Question")
        other_answers = _field_lines(other_lines, "Answer")
        if (
            len(other_statuses) == 1
            and other_statuses[0].strip().rstrip(".").casefold() in {"open", "pending", "blocked"}
            and any(_scope_names_task(scope, task.id) for scope in other_scopes)
        ):
            raise TransitionError(f"unresolved decision {other_ref} still blocks {task.id}")
        if (
            len(other_statuses) == 1
            and other_statuses[0].strip().rstrip(".").casefold() == "resolved"
            and len(other_questions) == 1
            and other_questions[0].strip().rstrip(".").casefold() == questions[0].strip().rstrip(".").casefold()
            and len(other_answers) == 1
            and other_answers[0].strip().rstrip(".").casefold() != answer.casefold()
            and any(_scope_names_task(scope, task.id) for scope in other_scopes)
        ):
            raise TransitionError(f"resolved decision {other_ref} conflicts for {task.id}")


def _validate_start_guards(run_dir: Path, tracker: Tracker, task_id: str) -> PlannedTask:
    current_phase = dict(tracker.current_fields)["phase"]
    current_metadata, current_tasks = _phase_document_for(tracker, run_dir, current_phase)
    _approved_phase_sequence(run_dir, tracker)
    _validate_phase_prerequisites(tracker, current_metadata)
    planned = _planned_tasks(run_dir, tracker)
    current_ids = {task.id for task in current_tasks}
    if task_id not in current_ids:
        raise TransitionError(f"task {task_id} is not part of the authoritative current phase {current_phase}")
    target = planned[task_id]
    if any(gate.state in {"in_progress", "re_reviewing", "blocked"} for gate in tracker.gates):
        raise TransitionError("an unresolved review gate prevents implementation dispatch")
    if any(row.state in {"fixing", "re_reviewing", "blocked"} for row in tracker.remediation):
        raise TransitionError("an unresolved remediation obligation prevents implementation dispatch")
    records = {task.id: task for task in tracker.tasks}
    for dependency in target.deps:
        record = records[dependency]
        if not _dependency_ready(Path(run_dir), tracker, record):
            raise TransitionError(f"dependency {dependency} is not verified and integrated")
    active = [task for task in tracker.tasks if task.state == "[~]" and task.id != task_id]
    if len(_active_worker_ids(tracker)) >= tracker.worker_limit:
        raise TransitionError("global worker limit is exhausted")
    for task in active:
        other = planned.get(task.id)
        if other is not None and _scopes_overlap(target.write_scope, other.write_scope):
            raise TransitionError(f"write scope conflicts with active task {task.id}")
    return target


def _dependency_ready(run_dir: Path, tracker: Tracker, task: TaskRecord) -> bool:
    if task.state != "[x]" or task.verification == "-":
        return False
    if task.kind == "artifact":
        if task.integration != "N/A" or task.artifacts == "-":
            return False
        try:
            definition = _planned_tasks(run_dir, tracker)[task.id]
            _validate_artifact_evidence(
                run_dir, tracker, task, definition,
                _artifact_evidence_references(task), _project_root(run_dir),
                require_target_tip=False,
            )
        except (KeyError, TransitionError):
            return False
        return True
    if task.integration in {"-", "N/A"} or task.commits == "-":
        return False
    repo_dir = _project_root(run_dir)
    if any(item.startswith("baseline:") for item in _csv(task.checkpoints)):
        candidates = tuple(
            item for item in _csv(task.verification)
            if "#sha256=" in item and item.endswith("@" + task.integration)
        )
        valid_references = []
        for reference in candidates:
            try:
                _validate_verification_evidence(
                    run_dir, (reference,), task.integration,
                    purpose="task-integration", run_id=tracker.run_id,
                    subject=f"task/{task.id}", attempt="N/A",
                )
            except TransitionError:
                continue
            valid_references.append(reference)
        if len(valid_references) != 1:
            return False
    else:
        escaped = re.escape(task.integration)
        historical_patterns = (
            rf"reconciled-existing-integration:{escaped}",
            rf"integrated-head:{escaped}",
            rf"integrated:[^,@]+@{escaped}",
            rf"integration@{escaped}:[^,]+",
            rf"integrated-[^:]+:PASS@{escaped}",
            rf"integrated:[^,]+@{escaped}",
        )
        if not any(
            any(re.fullmatch(pattern, item) for pattern in historical_patterns)
            for item in _csv(task.verification)
        ):
            return False
    return all(
        _git(repo_dir, "merge-base", "--is-ancestor", commit, task.integration)
        for commit in task.commits.split(",")
    ) and _git(repo_dir, "merge-base", "--is-ancestor", task.integration, tracker.target_branch)


def _active_worker_ids(tracker: Tracker) -> set[str]:
    workers = {task.owner for task in tracker.tasks if task.state == "[~]" and task.owner != "-"}
    for gate in tracker.gates:
        if gate.state in {"in_progress", "re_reviewing"}:
            available = max(0, tracker.worker_limit - len(workers))
            workers.update(_csv(gate.assignments)[:available])
    for row in tracker.remediation:
        if row.state == "fixing":
            workers.update(_csv(row.fixers))
    workers.discard("-")
    return workers


def _detected_runtime_capacity(run_dir: Path, tracker: Tracker) -> int:
    binding = _BOUND_RUNTIME_CAPACITY.get()
    canonical = Path(run_dir).resolve()
    if binding is None or binding[0] != canonical:
        raise TransitionError("current runtime capacity is not bound for this run")
    try:
        capacity = binding[1](canonical, tracker)
    except Exception as exc:
        raise TransitionError(f"runtime capacity provider failed: {exc}") from exc
    if capacity is None or isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
        raise TransitionError("runtime capacity provider did not establish a positive integer")
    return capacity


def _validate_worker_capacity(
    tracker: Tracker,
    additions: tuple[str, ...],
    capacity: int | None,
) -> None:
    if capacity is None or isinstance(capacity, bool) or capacity <= 0:
        raise TransitionError("runtime capacity must be an established positive integer")
    if tracker.worker_limit > capacity:
        raise TransitionError(
            f"recorded worker_limit {tracker.worker_limit} exceeds detected runtime capacity {capacity}"
        )
    if any(not _TOKEN.fullmatch(owner) for owner in additions):
        raise TransitionError("worker assignment is not a valid identifier")
    if len(_active_worker_ids(tracker) | set(additions)) > min(tracker.worker_limit, capacity):
        raise TransitionError("global worker limit or runtime capacity is exhausted")


def _validate_review_queue_capacity(
    tracker: Tracker,
    assignments: tuple[str, ...],
    capacity: int | None,
) -> None:
    """Require capacity for the next queued reviewer, not the whole required set."""
    if not assignments:
        raise TransitionError("review queue needs at least one assignment")
    if capacity is None or isinstance(capacity, bool) or capacity <= 0:
        raise TransitionError("runtime capacity must be an established positive integer")
    if tracker.worker_limit > capacity:
        raise TransitionError(
            f"recorded worker_limit {tracker.worker_limit} exceeds detected runtime capacity {capacity}"
        )
    if any(not _TOKEN.fullmatch(owner) for owner in assignments):
        raise TransitionError("reviewer assignment is not a valid identifier")
    if len(_active_worker_ids(tracker)) >= min(tracker.worker_limit, capacity):
        raise TransitionError("global worker limit or runtime capacity is exhausted")


def _with_next_action(tracker: Tracker, action: str) -> Tracker:
    if not action or "|" in action or "\n" in action:
        raise TransitionError("derived next action is not table-safe")
    return replace(
        tracker,
        current_fields=tuple(
            (key, action if key == "next_action" else value)
            for key, value in tracker.current_fields
        ),
    )


def _phase_documents(
    run_dir: Path,
    tracker: Tracker,
) -> tuple[tuple[str, PhaseMetadata, tuple[PlannedTask, ...]], ...]:
    documents = []
    for raw_path in dict(tracker.run_fields)["phase_plans"].split(","):
        metadata, tasks = _parse_phase_document(_resolved_reference(run_dir, raw_path))
        documents.append((raw_path, metadata, tasks))
    return tuple(documents)


_MASTER_PHASE_PATH = re.compile(
    r"(?<![A-Za-z0-9._/-])((?:[A-Za-z]:)?/?[A-Za-z0-9._/-]*phase(?:-[A-Za-z0-9._-]+)?\.md)(?![A-Za-z0-9._/-])"
)


def _master_phase_paths(
    run_dir: Path,
    master_value: str,
    supplied_paths: tuple[str, ...],
    *,
    error_type: type[ValueError] = TransitionError,
) -> tuple[str, ...]:
    """Return the exact approved phase order encoded by the master plan."""
    master_path = _resolved_reference(run_dir, master_value)
    master = master_path.read_text(encoding="utf-8")
    declared = tuple(match.group(1) for match in _MASTER_PHASE_PATH.finditer(master))
    if not declared:
        raise error_type("approved master plan has no phase-plan references")
    declared_ids = tuple(_resolved_reference(run_dir, value).resolve() for value in declared)
    supplied_ids = tuple(_resolved_reference(run_dir, value).resolve() for value in supplied_paths)
    if len(declared_ids) != len(set(declared_ids)):
        raise error_type("approved master plan has duplicate phase-plan references")
    if len(supplied_ids) != len(set(supplied_ids)):
        raise error_type("run has duplicate phase-plan references")
    if set(declared_ids) != set(supplied_ids):
        raise error_type("run phase plans are missing or extra relative to the approved master plan")
    if declared_ids != supplied_ids:
        raise error_type("run phase-plan order conflicts with the approved master plan")
    return supplied_paths


def _validate_phase_prerequisites(tracker: Tracker, metadata: PhaseMetadata) -> None:
    phases = {phase.id: phase for phase in tracker.phases}
    for dependency in metadata.deps:
        phase = phases.get(dependency)
        if phase is None or phase.state != "[x]":
            raise TransitionError(f"phase dependency {dependency} is not verified")
        if phase.review_gate == "required":
            gate = _gate_record(tracker, f"phase-{dependency}")
            if gate.state != "accepted":
                raise TransitionError(f"phase dependency {dependency} has an unresolved review gate")


def _unresolved_task_question(task: TaskRecord) -> bool:
    return task.question != "-" and not task.question.startswith("resolved:")


def _gate_next_action(tracker: Tracker, gate: GateRecord) -> str:
    if gate.state == "pending":
        return f"open-gate-{gate.id}"
    if gate.state == "in_progress":
        return f"await-review-{gate.id}"
    if gate.state == "re_reviewing":
        return f"await-re-review-{gate.id}"
    if gate.state == "accepted":
        if gate.type == "master":
            final = tuple(item for item in _csv(gate.verification) if item.startswith("final="))
            return "complete" if len(final) == 1 else "final-verification"
        return f"advance-phase-{gate.phase}"
    if gate.questions != "-":
        return f"await-review-question-{gate.id}"
    active_round = next(
        (
            row
            for row in tracker.remediation
            if row.gate == gate.id and row.state in {"fixing", "re_reviewing"}
        ),
        None,
    )
    if active_round is not None:
        verb = "continue-fixes" if active_round.state == "fixing" else "await-re-review"
        return f"{verb}-{gate.id}-round-{active_round.round_number}"
    return f"start-remediation-{gate.id}"


def derive_next_action(run_dir: Path, tracker: Tracker) -> str:
    """Derive the next permitted action from plans and authoritative tracker facts."""
    run_dir = Path(run_dir)
    phase_id = dict(tracker.current_fields)["phase"]
    documents = _phase_documents(run_dir, tracker)
    current = [document for document in documents if document[1].id == phase_id]
    if len(current) != 1:
        raise TransitionError(f"current phase {phase_id} does not resolve to one approved plan")
    _, metadata, planned = current[0]
    records = {task.id: task for task in tracker.tasks}

    for definition in sorted(planned, key=lambda item: (item.order, item.id)):
        task = records[definition.id]
        if task.state == "[?]" or _unresolved_task_question(task):
            return f"await-user-decision-{task.id}"
    active = [records[item.id] for item in planned if records[item.id].state == "[~]"]
    if active:
        return f"continue-{sorted(active, key=lambda item: item.id)[0].id}"
    for definition in sorted(planned, key=lambda item: (item.order, item.id)):
        task = records[definition.id]
        if task.state != "[x]":
            continue
        if task.kind == "source" and task.integration == "-":
            return f"integrate-{task.id}"
        if not _dependency_ready(run_dir, tracker, task):
            return f"reconcile-{task.id}"

    unstarted = [item for item in planned if records[item.id].state == "[ ]"]
    if unstarted:
        all_planned = _planned_tasks(run_dir, tracker)
        all_active = [task for task in tracker.tasks if task.state == "[~]"]
        if len(all_active) >= tracker.worker_limit:
            return "wait-for-worker-capacity"
        for definition in sorted(unstarted, key=lambda item: (item.order, item.id)):
            if any(not _dependency_ready(run_dir, tracker, records[dep]) for dep in definition.deps):
                continue
            if any(
                (other := all_planned.get(active_task.id)) is not None
                and _scopes_overlap(definition.write_scope, other.write_scope)
                for active_task in all_active
            ):
                continue
            return definition.id
        return "wait-for-task-dependencies"

    phase = next((item for item in tracker.phases if item.id == phase_id), None)
    if phase is None:
        raise TransitionError(f"current phase {phase_id} is absent from tracker")
    if phase.state == "[?]" and phase.verification.startswith("failed:"):
        return f"repair-phase-{phase_id}"
    if phase.state != "[x]" or phase.verification == "-":
        return f"verify-phase-{phase_id}"
    if metadata.review_gate == "required":
        phase_gate = _gate_record(tracker, f"phase-{phase_id}")
        if phase_gate.state != "accepted":
            return _gate_next_action(tracker, phase_gate)

    phase_ids = [document[1].id for document in documents]
    if phase_ids[-1] != phase_id:
        return f"advance-phase-{phase_id}"
    master_gate = _gate_record(tracker, "master")
    if master_gate.state == "accepted" and any(
        item.startswith("final=") for item in _csv(master_gate.verification)
    ):
        _validate_persisted_final_verification(run_dir, tracker, master_gate)
    return _gate_next_action(tracker, master_gate)


def _scheduler_context(run_dir: Path, phase_plan: Path, capacity: int | None) -> tuple[Tracker, tuple[PlannedTask, ...], int]:
    tracker = validate_run(run_dir)
    _validate_worker_capacity(tracker, (), capacity)
    assert capacity is not None
    approved_paths = {
        _resolved_reference(run_dir, value).resolve()
        for value in dict(tracker.run_fields)["phase_plans"].split(",")
    }
    supplied_path = Path(phase_plan).resolve()
    if supplied_path not in approved_paths:
        raise TransitionError("phase plan is not one of the run's approved phase plans")
    metadata, planned = _parse_phase_document(supplied_path)
    if dict(tracker.current_fields)["phase"] != metadata.id:
        raise TransitionError("phase plan does not match the active phase")
    _approved_phase_sequence(run_dir, tracker)
    _validate_phase_prerequisites(tracker, metadata)
    authoritative = _planned_tasks(run_dir, tracker)
    if any(authoritative.get(task.id) != task for task in planned):
        raise TransitionError("phase plan task metadata conflicts with the run's approved plans")
    if any(gate.state in {"in_progress", "re_reviewing", "blocked"} for gate in tracker.gates):
        raise TransitionError("an unresolved review gate prevents implementation dispatch")
    if any(row.state in {"fixing", "re_reviewing", "blocked"} for row in tracker.remediation):
        raise TransitionError("an unresolved remediation obligation prevents implementation dispatch")
    return tracker, planned, min(tracker.worker_limit, capacity) - len(_active_worker_ids(tracker))


def next_eligible_actions(
    run_dir: Path,
    phase_plan: Path,
    *,
    capacity: int | None,
) -> tuple[PlannedTask, ...]:
    """Return an advisory, conflict-free subset; reservation must revalidate it."""
    tracker, planned, available = _scheduler_context(Path(run_dir), Path(phase_plan), capacity)
    if available <= 0:
        return ()
    records = {task.id: task for task in tracker.tasks}
    active = tuple(task for task in tracker.tasks if task.state == "[~]")
    authoritative = _planned_tasks(Path(run_dir), tracker)
    selected: list[PlannedTask] = []
    for candidate in sorted(planned, key=lambda item: (item.order, item.id)):
        record = records[candidate.id]
        if record.state != "[ ]" or record.question != "-":
            continue
        if any(not _dependency_ready(Path(run_dir), tracker, records[dependency]) for dependency in candidate.deps):
            continue
        if any(
            active_plan is not None and _scopes_overlap(candidate.write_scope, active_plan.write_scope)
            for active_record in active
            for active_plan in (authoritative.get(active_record.id),)
        ):
            continue
        if any(_scopes_overlap(candidate.write_scope, other.write_scope) for other in selected):
            continue
        selected.append(candidate)
        if len(selected) == available:
            break
    return tuple(selected)


def reserve_tasks(
    run_dir: Path,
    phase_plan: Path,
    *,
    task_ids: tuple[str, ...],
    owners: tuple[str, ...],
    attempts: tuple[str, ...],
    capacity: int | None,
) -> Tracker:
    """Atomically reserve a currently ready, pairwise-independent task set."""
    if not task_ids or len(task_ids) != len(owners) or len(task_ids) != len(attempts):
        raise TransitionError("task, owner, and attempt identities must be nonempty and aligned")
    if len(task_ids) != len(set(task_ids)) or len(attempts) != len(set(attempts)):
        raise TransitionError("task and attempt identities must be unique within a reservation")
    if any(not _TOKEN.fullmatch(value) for value in (*owners, *attempts)):
        raise TransitionError("owner and attempt identities must be valid tokens")
    transition_id = "reserve-" + "-".join(f"{task}-{attempt}" for task, attempt in zip(task_ids, attempts))

    def transition(current: Tracker) -> Tracker:
        detected = _detected_runtime_capacity(Path(run_dir), current)
        tracker, planned, available = _scheduler_context(Path(run_dir), Path(phase_plan), detected)
        if tracker != current:
            raise TransitionError("tracker changed while the reservation lock was held")
        _validate_worker_capacity(tracker, owners, detected)
        by_id = {task.id: task for task in planned}
        records = {task.id: task for task in tracker.tasks}
        try:
            selected = tuple(by_id[task_id] for task_id in task_ids)
        except KeyError as exc:
            raise TransitionError(f"unknown task in reservation: {exc.args[0]}") from exc
        if any(records[item.id].state != "[ ]" or records[item.id].question != "-" for item in selected):
            raise TransitionError("every reserved task must still be unstarted and unblocked")
        if any(
            not _dependency_ready(Path(run_dir), tracker, records[dependency])
            for item in selected
            for dependency in item.deps
        ):
            raise TransitionError("a reserved task dependency is not verified and integrated")
        authoritative = _planned_tasks(Path(run_dir), tracker)
        active_plans = tuple(
            authoritative.get(record.id)
            for record in tracker.tasks
            if record.state == "[~]"
        )
        if any(
            active_plan is not None and _scopes_overlap(item.write_scope, active_plan.write_scope)
            for item in selected
            for active_plan in active_plans
        ):
            raise TransitionError("a reserved task conflicts with active write ownership")
        if any(
            _scopes_overlap(left.write_scope, right.write_scope)
            for index, left in enumerate(selected)
            for right in selected[index + 1:]
        ):
            raise TransitionError("reserved tasks have conflicting write scopes")
        updated = tracker
        for item, owner, attempt in zip(selected, owners, attempts):
            record = _task_record(updated, item.id)
            if any(attempt in value for value in (record.attempt, record.checkpoints, record.result)):
                raise TransitionError("task attempt has already been used")
            checkpoint = f"started:{attempt}"
            if item.kind == "source":
                baseline = _resolved_commit(_project_root(Path(run_dir)), tracker.target_branch)
                checkpoint = f"{checkpoint},baseline:{attempt}@{baseline}"
            updated = _replace_task(
                updated,
                replace(
                    record,
                    state="[~]",
                    owner=owner,
                    attempt=attempt,
                    checkpoints=_append_history(record.checkpoints, checkpoint),
                ),
            )
        return updated

    return locked_tracker_update(
        Path(run_dir), transition_id, transition, timeout_s=5.0,
        replay_returns_current=False, refresh_next_action=True,
    )


def _append_history(value: str, entry: str) -> str:
    return entry if value == "-" else f"{value},{entry}"


def start_task(run_dir: Path, *, task_id: str, owner: str, attempt: str) -> Tracker:
    """Persist the first `[ ] -> [~]` transition before dispatch."""
    if not owner or not attempt or "|" in owner or "|" in attempt:
        raise TransitionError("owner and attempt are required table-safe values")

    def transition(tracker: Tracker) -> Tracker:
        task = _task_record(tracker, task_id)
        if task.state != "[ ]":
            raise TransitionError("start_task handles first start only")
        definition = _validate_start_guards(Path(run_dir), tracker, task_id)
        _validate_worker_capacity(
            tracker,
            (owner,),
            _detected_runtime_capacity(Path(run_dir), tracker),
        )
        if any(attempt in value for value in (task.attempt, task.checkpoints, task.result)):
            raise TransitionError("task attempt has already been used")
        checkpoint = f"started:{attempt}"
        if definition.kind == "source":
            baseline = _resolved_commit(_project_root(Path(run_dir)), tracker.target_branch)
            checkpoint = f"{checkpoint},baseline:{attempt}@{baseline}"
        return _replace_task(
            tracker,
            replace(task, state="[~]", owner=owner, attempt=attempt, checkpoints=_append_history(task.checkpoints, checkpoint)),
        )

    return locked_tracker_update(
        Path(run_dir),
        f"start-{task_id}-{attempt}",
        transition,
        timeout_s=5.0,
        replay_returns_current=False,
        refresh_next_action=True,
    )


def record_task_question(
    run_dir: Path,
    *,
    task_id: str,
    attempt: str,
    question_or_block_ref: str,
    reason: str,
) -> Tracker:
    if not question_or_block_ref or not reason or "|" in reason:
        raise TransitionError("question reference and reason are required")

    def transition(tracker: Tracker) -> Tracker:
        task = _task_record(tracker, task_id)
        if task.state != "[~]" or task.attempt != attempt:
            raise TransitionError("only the current active attempt may be blocked")
        checkpoint = f"blocked:{attempt}@{question_or_block_ref}"
        return _replace_task(
            tracker,
            replace(task, state="[?]", checkpoints=_append_history(task.checkpoints, checkpoint), question=question_or_block_ref),
        )

    return locked_tracker_update(
        Path(run_dir), f"question-{task_id}-{attempt}-{question_or_block_ref}",
        transition, timeout_s=5.0, refresh_next_action=True,
    )


def resume_task(
    run_dir: Path,
    *,
    task_id: str,
    prior_attempt: str,
    new_owner: str,
    new_attempt: str,
    decision_ref: str,
) -> Tracker:
    """Persist an answered `[?] -> [~]` transition before redispatch."""
    if not all((prior_attempt, new_owner, new_attempt, decision_ref)) or "|" in new_owner:
        raise TransitionError("resume identity fields are required")
    marker = f"resumed:{prior_attempt}->{new_attempt}@{decision_ref}"

    def transition(tracker: Tracker) -> Tracker:
        task = _task_record(tracker, task_id)
        if task.state == "[~]" and task.attempt == new_attempt and task.owner == new_owner and marker in task.checkpoints:
            raise _AlreadyApplied(tracker)
        if task.state != "[?]" or task.attempt != prior_attempt:
            raise TransitionError("resume requires the matching blocked attempt")
        if new_attempt == prior_attempt or any(new_attempt in value for value in (task.checkpoints, task.result)):
            raise TransitionError("new attempt must be distinct and unused")
        _validate_decision(Path(run_dir), tracker, task, decision_ref)
        definition = _validate_start_guards(Path(run_dir), tracker, task_id)
        _validate_worker_capacity(
            tracker,
            (new_owner,),
            _detected_runtime_capacity(Path(run_dir), tracker),
        )
        checkpoint = marker
        if definition.kind == "source":
            baseline = _resolved_commit(_project_root(Path(run_dir)), tracker.target_branch)
            checkpoint = f"{checkpoint},baseline:{new_attempt}@{baseline}"
        return _replace_task(
            tracker,
            replace(
                task,
                state="[~]",
                owner=new_owner,
                attempt=new_attempt,
                checkpoints=_append_history(task.checkpoints, checkpoint),
                question=f"resolved:{decision_ref}",
            ),
        )

    try:
        return locked_tracker_update(
            Path(run_dir), f"resume-{task_id}-{prior_attempt}-{new_attempt}-{decision_ref}",
            transition, timeout_s=5.0, refresh_next_action=True,
        )
    except _AlreadyApplied as applied:
        return applied.tracker


def _git(repo_dir: Path, *args: str) -> bool:
    completed = subprocess.run(
        ("git", "-C", str(repo_dir), *args),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _git_output(repo_dir: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo_dir), *args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise TransitionError(
            f"Git evidence command failed: git {' '.join(args)}: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _resolved_commit(repo_dir: Path, reference: str) -> str:
    resolved = _git_output(repo_dir, "rev-parse", "--verify", f"{reference}^{{commit}}")
    if not _COMMIT.fullmatch(resolved):
        raise TransitionError("Git reference did not resolve to one full commit")
    return resolved


def _attempt_baseline(task: TaskRecord, attempt: str) -> str:
    prefix = f"baseline:{attempt}@"
    matches = [item.removeprefix(prefix) for item in _csv(task.checkpoints) if item.startswith(prefix)]
    if len(matches) != 1 or not _COMMIT.fullmatch(matches[0]):
        raise TransitionError("source attempt needs exactly one recorded full-commit baseline")
    return matches[0]


def _path_in_write_scope(path: str, scopes: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    return any(
        (kind == "file" and candidate == scope)
        or (kind == "tree" and (candidate == scope or scope in candidate.parents))
        for kind, scope in (_scope_parts(raw) for raw in scopes)
    )


def _validate_source_provenance(
    *,
    repo_dir: Path,
    task: TaskRecord,
    definition: PlannedTask,
    attempt: str,
    source_ref: str,
    commits: tuple[str, ...],
) -> str:
    baseline = _attempt_baseline(task, attempt)
    source_head = _resolved_commit(repo_dir, source_ref)
    if baseline == source_head or not _git(repo_dir, "merge-base", "--is-ancestor", baseline, source_head):
        raise TransitionError("source completion must be strictly after its recorded baseline")
    expected = tuple(
        line for line in _git_output(repo_dir, "rev-list", "--reverse", f"{baseline}..{source_head}").splitlines()
        if line
    )
    if not expected or commits != expected:
        raise TransitionError("implementation commits must equal the complete ordered baseline-to-source range")
    changed = tuple(
        line for line in _git_output(repo_dir, "diff", "--name-only", baseline, source_head).splitlines()
        if line
    )
    if not changed:
        raise TransitionError("source task produced no repository change")
    if any(not _path_in_write_scope(path, definition.write_scope) for path in changed):
        raise TransitionError("source task changed a path outside its approved write scope")
    return source_head


def _is_target_tip(repo_dir: Path, target_branch: str, commit: str) -> bool:
    """Return whether commit and the designated target branch name the same history point."""
    return _git(repo_dir, "merge-base", "--is-ancestor", commit, target_branch) and _git(
        repo_dir, "merge-base", "--is-ancestor", target_branch, commit
    )


def complete_task(
    run_dir: Path,
    *,
    task_id: str,
    attempt: str,
    phase_plan: Path,
    source_ref: str | None,
    commits: tuple[str, ...],
    artifacts: tuple[Path, ...],
    evidence: tuple[str, ...],
    repo_dir: Path,
) -> Tracker:
    def transition(tracker: Tracker) -> Tracker:
        definition = _approved_task_definition(Path(run_dir), tracker, Path(phase_plan), task_id)
        task = _task_record(tracker, task_id)
        if task.state != "[~]" or task.attempt != attempt:
            raise TransitionError("result does not match the current active attempt")
        if task.kind != definition.kind or not evidence:
            raise TransitionError("task kind or completion evidence does not match the plan")
        if task.kind == "source":
            if source_ref is None or not commits or artifacts:
                raise TransitionError("source completion requires source ref and commits only")
            source_head = _validate_source_provenance(
                repo_dir=Path(repo_dir), task=task, definition=definition,
                attempt=attempt, source_ref=source_ref, commits=commits,
            )
            _validate_verification_evidence(
                Path(run_dir), evidence, source_head,
                purpose="task-test", run_id=tracker.run_id,
                subject=f"task/{task.id}", attempt=attempt,
                commands=definition.verification_commands,
            )
            replacement = replace(
                task,
                state="[x]",
                result=_append_history(task.result, f"result:{attempt}"),
                checkpoints=_append_history(task.checkpoints, f"completed:{attempt}"),
                source_ref=source_head,
                commits=",".join(commits),
                artifacts="-",
                integration="-",
                verification=_append_history(task.verification, ",".join(evidence)),
            )
        else:
            if source_ref is not None or commits:
                raise TransitionError("artifact completion cannot carry source provenance")
            actual = []
            for artifact in artifacts:
                path = artifact if artifact.is_absolute() else Path(repo_dir) / artifact
                try:
                    actual.append(path.relative_to(repo_dir).as_posix())
                except ValueError as exc:
                    raise TransitionError("artifact is outside repository root") from exc
                if not path.is_file():
                    raise TransitionError(f"artifact is missing: {path}")
            if tuple(actual) != definition.outputs:
                raise TransitionError("artifact paths do not exactly match approved outputs")
            _validate_artifact_evidence(
                Path(run_dir), tracker, task, definition, evidence, Path(repo_dir),
                require_target_tip=True,
            )
            replacement = replace(
                task,
                state="[x]",
                result=_append_history(task.result, f"result:{attempt}"),
                checkpoints=_append_history(task.checkpoints, f"completed:{attempt}"),
                source_ref="-",
                commits="-",
                artifacts=",".join(actual),
                integration="N/A",
                verification=_append_history(task.verification, ",".join(evidence)),
            )
        return _replace_task(tracker, replacement)

    return locked_tracker_update(
        Path(run_dir), f"complete-{task_id}-{attempt}", transition,
        timeout_s=5.0, refresh_next_action=True,
    )


def record_task_integration(
    run_dir: Path,
    *,
    task_id: str,
    integration_commit: str,
    verification: tuple[str, ...],
    repo_dir: Path,
) -> Tracker:
    if not verification or not _COMMIT.fullmatch(integration_commit):
        raise TransitionError("integration commit and verification are required")

    def transition(tracker: Tracker) -> Tracker:
        task = _task_record(tracker, task_id)
        if task.kind != "source" or task.state != "[x]" or task.commits == "-":
            raise TransitionError("only a completed source task can be integrated")
        _validate_verification_evidence(
            Path(run_dir), verification, integration_commit,
            purpose="task-integration", run_id=tracker.run_id,
            subject=f"task/{task.id}", attempt="N/A",
        )
        if not _git(repo_dir, "cat-file", "-e", f"{integration_commit}^{{commit}}"):
            raise TransitionError("integration commit does not exist")
        for commit in task.commits.split(","):
            if not _git(repo_dir, "merge-base", "--is-ancestor", commit, integration_commit):
                raise TransitionError("integration commit does not contain every implementation commit")
        if not _git(repo_dir, "merge-base", "--is-ancestor", integration_commit, tracker.target_branch):
            raise TransitionError("integration commit is not contained by target branch")
        return _replace_task(
            tracker,
            replace(
                task,
                integration=integration_commit,
                verification=_append_history(task.verification, ",".join(verification)),
            ),
        )

    return locked_tracker_update(
        Path(run_dir), f"integrate-{task_id}-{integration_commit}", transition,
        timeout_s=5.0, refresh_next_action=True,
    )


def publish_worker_result(path: Path, result: WorkerResult) -> None:
    """Publish an immutable result without exposing partially written content."""
    path = Path(path)
    canonical = render_worker_result(result).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == canonical:
            return
        raise EvidenceError(f"worker result already exists with conflicting content: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    published = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(canonical)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            published = True
        except FileExistsError:
            if path.read_bytes() == canonical:
                return
            raise EvidenceError(f"worker result was concurrently published with conflicting content: {path}")
        _sync_directory(path.parent)
    except EvidenceError:
        raise
    except OSError as exc:
        qualifier = "may already be published" if published else "was not published"
        raise EvidenceError(f"worker result publication failed ({qualifier}): {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _result_identity(result_path: Path, content: bytes, repo_dir: Path) -> tuple[str, str]:
    try:
        relative = result_path.resolve().relative_to(repo_dir.resolve()).as_posix()
    except ValueError as exc:
        raise EvidenceError("worker result is outside the repository root") from exc
    if any(character in relative for character in ",|#"):
        raise EvidenceError("worker result path contains an unsupported identity delimiter")
    digest = hashlib.sha256(content).hexdigest()
    return f"{relative}#sha256={digest}", relative


def _result_checkpoints(task: TaskRecord, result: WorkerResult) -> str:
    value = task.checkpoints
    for checkpoint in result.checkpoints:
        value = _append_history(
            value,
            f"worker:{result.attempt}:{checkpoint.id}:{checkpoint.status}@{checkpoint.evidence}",
        )
    return value


def import_worker_result(
    run_dir: Path,
    *,
    result_path: Path,
    phase_plan: Path,
    repo_dir: Path,
) -> Tracker:
    """Validate an immutable result against its active assignment and import once."""
    result_path = Path(result_path)
    repo_dir = Path(repo_dir)
    try:
        initial_content = result_path.read_bytes()
        initial_result = parse_worker_result(initial_content.decode("utf-8"))
    except (OSError, UnicodeError) as exc:
        raise EvidenceError(f"worker result is unreadable: {result_path}: {exc}") from exc
    identity, relative_path = _result_identity(result_path, initial_content, repo_dir)
    digest = identity.rsplit("=", 1)[1]
    transition_id = f"import-{initial_result.task_id}-{initial_result.attempt}-{digest}"

    def transition(tracker: Tracker) -> Tracker:
        try:
            current_content = result_path.read_bytes()
            result = parse_worker_result(current_content.decode("utf-8"))
        except (OSError, UnicodeError) as exc:
            raise EvidenceError(f"worker result became unreadable during import: {exc}") from exc
        current_identity, current_relative = _result_identity(result_path, current_content, repo_dir)
        if current_identity != identity or current_relative != relative_path or result != initial_result:
            raise EvidenceError("worker result changed while import was being validated")
        try:
            task = _task_record(tracker, result.task_id)
        except TransitionError as exc:
            raise EvidenceError(str(exc)) from exc
        accepted = () if task.result == "-" else tuple(task.result.split(","))
        if identity in accepted:
            raise _AlreadyApplied(tracker)
        if any(entry.split("#sha256=", 1)[0] == relative_path for entry in accepted):
            raise EvidenceError("accepted result path now has conflicting content")
        if result.run_id != tracker.run_id or result.task_id != task.id:
            raise EvidenceError("result run/task identity does not match the tracker")
        if task.state != "[~]" or result.attempt != task.attempt:
            raise EvidenceError("result attempt is not the current active attempt")
        if result.owner != task.owner:
            raise EvidenceError("result owner does not match the controller-assigned owner")
        for evidence_reference in result.evidence:
            evidence_path = evidence_reference.split("#sha256=", 1)[0]
            try:
                safe_evidence = _safe_relative(evidence_path)
            except PlanMetadataError as exc:
                raise EvidenceError(f"worker evidence path is unsafe: {evidence_path}") from exc
            candidates = (
                Path(run_dir) / safe_evidence,
                _project_root(Path(run_dir)) / safe_evidence,
            )
            if not any(path.is_file() for path in candidates):
                raise EvidenceError(f"worker evidence is missing: {evidence_path}")
        allowed_checkpoint_evidence = set(result.evidence) | set(result.artifacts)
        if any(checkpoint.evidence not in allowed_checkpoint_evidence for checkpoint in result.checkpoints):
            raise EvidenceError("worker checkpoint refers to undeclared evidence")
        try:
            definition = _approved_task_definition(Path(run_dir), tracker, Path(phase_plan), task.id)
        except (TransitionError, PlanMetadataError) as exc:
            raise EvidenceError(str(exc)) from exc
        if result.kind != task.kind or result.kind != definition.kind:
            raise EvidenceError("result kind/task metadata does not match the approved plan")
        verification = _append_history(task.verification, f"tests:{result.tests}")
        verification = _append_history(verification, f"evidence:{','.join(result.evidence)}")
        checkpoints = _result_checkpoints(task, result)
        result_history = _append_history(task.result, identity)
        if result.status in {"DONE", "DONE_WITH_CONCERNS"}:
            if result.kind == "source":
                try:
                    source_head = _validate_source_provenance(
                        repo_dir=repo_dir, task=task, definition=definition,
                        attempt=result.attempt, source_ref=result.source_ref,
                        commits=result.commits,
                    )
                    _validate_verification_evidence(
                        Path(run_dir), result.evidence, source_head,
                        purpose="task-test", run_id=tracker.run_id,
                        subject=f"task/{task.id}", attempt=result.attempt,
                        commands=definition.verification_commands,
                    )
                except TransitionError as exc:
                    raise EvidenceError(str(exc)) from exc
                replacement = replace(
                    task,
                    state="[x]",
                    result=result_history,
                    checkpoints=_append_history(checkpoints, f"completed:{result.attempt}"),
                    source_ref=source_head,
                    commits=",".join(result.commits),
                    artifacts="-",
                    integration="-",
                    verification=verification,
                )
            else:
                actual = tuple(result.artifacts)
                if actual != definition.outputs:
                    raise EvidenceError("artifact result does not name the exact approved outputs")
                for output in actual:
                    if not (repo_dir / output).is_file():
                        raise EvidenceError(f"artifact output is missing: {output}")
                try:
                    _validate_artifact_evidence(
                        Path(run_dir), tracker, task, definition, result.evidence,
                        repo_dir, require_target_tip=True,
                    )
                except TransitionError as exc:
                    raise EvidenceError(str(exc)) from exc
                artifact_verification = _append_history(task.verification, f"tests:{result.tests}")
                for reference in result.evidence:
                    artifact_verification = _append_history(artifact_verification, reference)
                replacement = replace(
                    task,
                    state="[x]",
                    result=result_history,
                    checkpoints=_append_history(checkpoints, f"completed:{result.attempt}"),
                    source_ref="-",
                    commits="-",
                    artifacts=",".join(actual),
                    integration="N/A",
                    verification=artifact_verification,
                )
        else:
            if result.status == "BLOCKED" and result.blocking_reason == "-":
                raise EvidenceError("BLOCKED result needs a blocking reason")
            replacement = replace(
                task,
                state="[?]",
                result=result_history,
                checkpoints=_append_history(checkpoints, f"blocked:{result.attempt}@{result.question}"),
                verification=verification,
                question=result.question,
            )
        return _replace_task(tracker, replacement)

    try:
        return locked_tracker_update(
            Path(run_dir), transition_id, transition,
            timeout_s=5.0, refresh_next_action=True,
        )
    except _AlreadyApplied as applied:
        return applied.tracker


def _replace_phase(tracker: Tracker, replacement: PhaseRecord) -> Tracker:
    return replace(
        tracker,
        phases=tuple(replacement if phase.id == replacement.id else phase for phase in tracker.phases),
    )


def _replace_gate(tracker: Tracker, replacement: GateRecord) -> Tracker:
    return replace(
        tracker,
        gates=tuple(replacement if gate.id == replacement.id else gate for gate in tracker.gates),
    )


def _gate_record(tracker: Tracker, gate_id: str) -> GateRecord:
    matches = [gate for gate in tracker.gates if gate.id == gate_id]
    if len(matches) != 1:
        raise TransitionError(f"unknown review gate {gate_id}")
    return matches[0]


def _phase_document_for(tracker: Tracker, run_dir: Path, phase_id: str) -> tuple[PhaseMetadata, tuple[PlannedTask, ...]]:
    matches = []
    for value in dict(tracker.run_fields)["phase_plans"].split(","):
        document = _parse_phase_document(_resolved_reference(run_dir, value))
        if document[0].id == phase_id:
            matches.append(document)
    if len(matches) != 1:
        raise TransitionError(f"phase {phase_id} does not resolve to one approved plan")
    return matches[0]


def record_phase_verification(
    run_dir: Path,
    *,
    phase_id: str,
    head: str,
    commands: tuple[str, ...],
    evidence: tuple[str, ...],
) -> Tracker:
    if not commands or not evidence or not _COMMIT.fullmatch(head):
        raise TransitionError("phase verification needs commands, evidence, and a full commit")

    def transition(tracker: Tracker) -> Tracker:
        metadata, planned = _phase_document_for(tracker, Path(run_dir), phase_id)
        if commands != metadata.verification_commands:
            raise TransitionError("phase verification commands must exactly match the approved ordered suite")
        records = _validate_verification_evidence(
            Path(run_dir), evidence, head,
            purpose="phase", run_id=tracker.run_id,
            subject=f"phase/{phase_id}", attempt="N/A",
            commands=metadata.verification_commands,
        )
        matches = [phase for phase in tracker.phases if phase.id == phase_id]
        if len(matches) != 1:
            raise TransitionError(f"unknown phase {phase_id}")
        phase = matches[0]
        if phase.review_gate != metadata.review_gate or phase.review_reason != metadata.review_reason:
            raise TransitionError("phase review classification or reason conflicts with approved metadata")
        task_records = {task.id: task for task in tracker.tasks}
        if any(not _dependency_ready(Path(run_dir), tracker, task_records[item.id]) for item in planned):
            raise TransitionError("every phase task must be verified and truthfully integrated")
        repo_dir = _project_root(Path(run_dir))
        if not _git(repo_dir, "cat-file", "-e", f"{head}^{{commit}}") or not _is_target_tip(
            repo_dir, tracker.target_branch, head
        ):
            raise TransitionError("phase verification HEAD is not the designated target branch tip")
        if any(
            task_records[item.id].kind == "source"
            and not _git(repo_dir, "merge-base", "--is-ancestor", task_records[item.id].integration, head)
            for item in planned
        ):
            raise TransitionError("phase verification HEAD does not contain every source integration")
        verification = f"head:{head};commands:{','.join(records[0].commands)};evidence:{evidence[0]}"
        return _replace_phase(tracker, replace(phase, state="[x]", verification=verification))

    return locked_tracker_update(
        Path(run_dir), f"verify-phase-{phase_id}-{head}", transition,
        timeout_s=5.0, refresh_next_action=True,
    )


def _phase_verification_head(phase: PhaseRecord) -> str | None:
    match = re.search(r"(?:^|;)head:([0-9a-f]{40})(?:;|$)", phase.verification)
    return match.group(1) if match else None


def _phase_verification_evidence(phase: PhaseRecord) -> tuple[str, ...]:
    match = re.search(r"(?:^|;)evidence:([^;]+)(?:;|$)", phase.verification)
    return () if match is None else _csv(match.group(1))


def _approved_phase_sequence(
    run_dir: Path,
    tracker: Tracker,
) -> tuple[tuple[str, PhaseMetadata, tuple[PlannedTask, ...]], ...]:
    fields = dict(tracker.run_fields)
    documents = _phase_documents(run_dir, tracker)
    try:
        _master_phase_paths(
            run_dir,
            fields["master_plan"],
            tuple(raw_path for raw_path, _, _ in documents),
        )
    except (OSError, UnicodeError) as exc:
        master_path = _resolved_reference(run_dir, fields["master_plan"])
        raise TransitionError(f"approved master plan is unreadable: {master_path}: {exc}") from exc
    return documents


def advance_phase(
    run_dir: Path,
    *,
    completed_phase_id: str,
    next_phase_id: str,
) -> Tracker:
    """Atomically advance one accepted phase to its approved immediate successor."""
    if not _TOKEN.fullmatch(completed_phase_id) or not _TOKEN.fullmatch(next_phase_id):
        raise TransitionError("phase advancement needs valid phase identities")
    transition_id = f"advance-{completed_phase_id}-to-{next_phase_id}"

    def transition(tracker: Tracker) -> Tracker:
        current_phase_id = dict(tracker.current_fields)["phase"]
        if current_phase_id != completed_phase_id:
            raise TransitionError("completed_phase_id does not match the current phase")
        documents = _approved_phase_sequence(Path(run_dir), tracker)
        phase_ids = [metadata.id for _, metadata, _ in documents]
        try:
            current_index = phase_ids.index(completed_phase_id)
        except ValueError as exc:
            raise TransitionError("completed phase is absent from the approved master sequence") from exc
        if current_index + 1 >= len(documents) or phase_ids[current_index + 1] != next_phase_id:
            raise TransitionError("next phase is not the approved immediate successor")

        _, completed_metadata, completed_tasks = documents[current_index]
        _, next_metadata, next_tasks = documents[current_index + 1]
        phase_records = {phase.id: phase for phase in tracker.phases}
        completed_phase = phase_records.get(completed_phase_id)
        if completed_phase is None or completed_phase.state != "[x]":
            raise TransitionError("completed phase has not passed mechanical verification")
        verification_head = _phase_verification_head(completed_phase)
        if verification_head is None:
            raise TransitionError("completed phase verification has no applicable code-state identity")
        repo_dir = _project_root(Path(run_dir))
        if not _git(repo_dir, "merge-base", "--is-ancestor", verification_head, tracker.target_branch):
            raise TransitionError("completed phase verification is not on the target branch")

        tasks = {task.id: task for task in tracker.tasks}
        if any(not _dependency_ready(Path(run_dir), tracker, tasks[item.id]) for item in completed_tasks):
            raise TransitionError("every completed-phase task needs truthful completion and integration evidence")
        if any(
            tasks[item.id].kind == "source"
            and not _git(repo_dir, "merge-base", "--is-ancestor", tasks[item.id].integration, verification_head)
            for item in completed_tasks
        ):
            raise TransitionError("phase verification does not cover every task integration")
        if any(_unresolved_task_question(task) for task in tracker.tasks):
            raise TransitionError("an unresolved task question prevents phase advancement")
        if any(gate.questions != "-" for gate in tracker.gates):
            raise TransitionError("an unresolved review question prevents phase advancement")
        if any(row.state in {"fixing", "re_reviewing", "blocked"} for row in tracker.remediation):
            raise TransitionError("an unresolved remediation obligation prevents phase advancement")

        if completed_metadata.review_gate == "required":
            gate = _gate_record(tracker, f"phase-{completed_phase_id}")
            if gate.state != "accepted":
                raise TransitionError("required phase review has not been accepted")
            if (
                gate.head == "-"
                or not _git(repo_dir, "merge-base", "--is-ancestor", verification_head, gate.head)
                or not _is_target_tip(repo_dir, tracker.target_branch, gate.head)
            ):
                raise TransitionError("required phase review does not cover the verified phase state")
        elif not _is_target_tip(repo_dir, tracker.target_branch, verification_head):
            raise TransitionError("final-only phase verification is no longer the target branch tip")

        for dependency in next_metadata.deps:
            dependency_phase = phase_records.get(dependency)
            if dependency_phase is None or dependency_phase.state != "[x]":
                raise TransitionError(f"next phase dependency {dependency} is not verified")
            if dependency_phase.review_gate == "required":
                dependency_gate = _gate_record(tracker, f"phase-{dependency}")
                if dependency_gate.state != "accepted":
                    raise TransitionError(f"next phase dependency {dependency} has an unresolved review gate")

        next_phase = phase_records.get(next_phase_id)
        if next_phase is None or next_phase.state != "[ ]":
            raise TransitionError("next phase is absent, already active, or already completed")
        first_task = min(next_tasks, key=lambda item: (item.order, item.id))
        updated_phases = tuple(
            replace(phase, state="[~]") if phase.id == next_phase_id else phase
            for phase in tracker.phases
        )
        updated_current = tuple(
            (
                key,
                next_phase_id if key == "phase" else first_task.batch if key == "batch" else value,
            )
            for key, value in tracker.current_fields
        )
        return replace(tracker, current_fields=updated_current, phases=updated_phases)

    return locked_tracker_update(
        Path(run_dir), transition_id, transition,
        timeout_s=5.0, refresh_next_action=True,
    )


def _phase_review_boundary(run_dir: Path, tracker: Tracker, phase_id: str) -> str:
    documents = _approved_phase_sequence(run_dir, tracker)
    phase_ids = [metadata.id for _, metadata, _ in documents]
    try:
        index = phase_ids.index(phase_id)
    except ValueError as exc:
        raise TransitionError(f"phase {phase_id} is absent from the approved sequence") from exc
    if index == 0:
        return tracker.base_commit
    previous_id = phase_ids[index - 1]
    previous = next(phase for phase in tracker.phases if phase.id == previous_id)
    if previous.review_gate == "required":
        previous_gate = _gate_record(tracker, f"phase-{previous_id}")
        if previous_gate.state != "accepted" or previous_gate.head == "-":
            raise TransitionError("prior required phase has no accepted review boundary")
        return previous_gate.head
    boundary = _phase_verification_head(previous)
    if previous.state != "[x]" or boundary is None:
        raise TransitionError("prior phase has no verified review boundary")
    return boundary


def open_review_gate(
    run_dir: Path,
    *,
    gate_id: str,
    base: str,
    head: str,
    reviewer_assignments: tuple[str, ...],
    capacity: int | None = None,
) -> Tracker:
    if not _COMMIT.fullmatch(base) or not _COMMIT.fullmatch(head):
        raise TransitionError("review base and HEAD must be full commits")
    if len(reviewer_assignments) != len(set(reviewer_assignments)) or any(not _TOKEN.fullmatch(item) for item in reviewer_assignments):
        raise TransitionError("reviewer assignments must be unique valid identifiers")

    def transition(tracker: Tracker) -> Tracker:
        gate = _gate_record(tracker, gate_id)
        if gate.state != "pending":
            raise TransitionError("only a pending review gate can be opened")
        if gate.type == "phase":
            phase = next((item for item in tracker.phases if item.id == gate.phase), None)
            if phase is None or phase.review_gate != "required" or phase.state != "[x]" or len(reviewer_assignments) != 1:
                raise TransitionError("required phase review needs one reviewer after mechanical verification")
            if head != _phase_verification_head(phase):
                raise TransitionError("phase review HEAD must equal the recorded phase verification HEAD")
            if base != _phase_review_boundary(Path(run_dir), tracker, gate.phase):
                raise TransitionError("phase review base must equal the approved phase boundary")
            _, planned = _phase_document_for(tracker, Path(run_dir), gate.phase)
            owners = {next(task for task in tracker.tasks if task.id == item.id).owner for item in planned}
            if reviewer_assignments[0] in owners:
                raise TransitionError("phase reviewer must be independent from implementation owners")
        else:
            if len(reviewer_assignments) != 2 or any(phase.state != "[x]" for phase in tracker.phases):
                raise TransitionError("master review needs two reviewers after all phases verify")
            if any(item.type == "phase" and item.state != "accepted" for item in tracker.gates):
                raise TransitionError("master review waits for every required phase gate")
            documents = _approved_phase_sequence(Path(run_dir), tracker)
            last_phase_id = documents[-1][1].id
            last_phase = next(
                (phase for phase in tracker.phases if phase.id == last_phase_id), None
            )
            expected_head = (
                _phase_verification_head(last_phase) if last_phase is not None else None
            )
            if base != tracker.base_commit or head != expected_head:
                raise TransitionError(
                    "master review must use the immutable run base and last approved phase verification HEAD"
                )
            implementation_owners = {
                task.owner for task in tracker.tasks if task.owner != "-"
            }
            if implementation_owners.intersection(reviewer_assignments):
                raise TransitionError(
                    "master reviewers must be independent from every task implementation owner"
                )
        _validate_review_queue_capacity(
            tracker, reviewer_assignments,
            _detected_runtime_capacity(Path(run_dir), tracker),
        )
        repo_dir = _project_root(Path(run_dir))
        if not _git(repo_dir, "merge-base", "--is-ancestor", base, head) or not _is_target_tip(
            repo_dir, tracker.target_branch, head
        ):
            raise TransitionError("review range is not an integrated target-branch range")
        return _replace_gate(
            tracker,
            replace(gate, state="in_progress", base=base, head=head, assignments=",".join(reviewer_assignments)),
        )

    return locked_tracker_update(
        Path(run_dir), f"open-gate-{gate_id}-{head}", transition,
        timeout_s=5.0, refresh_next_action=True,
    )


_HISTORICAL_REVIEW_FIELDS = ("gate", "assignment", "base", "head", "findings")
_REVIEW_FIELDS = (*_HISTORICAL_REVIEW_FIELDS, "outcomes")
_FINDING_HEADER = ("ID", "Gate", "Severity", "Status", "Disposition", "Evidence", "Fix Commit", "Re-review")
_VERIFICATION_MARKER = "<!-- pipeline-verification-evidence/v2 -->"
_VERIFICATION_FIELDS = (
    "purpose", "run_id", "subject", "attempt", "code_state", "outcome",
    "commands", "environment", "inputs",
)
_VERIFICATION_PURPOSES = {"task-test", "task-integration", "phase", "remediation", "final"}


def _validate_verification_evidence(
    run_dir: Path,
    references: tuple[str, ...],
    expected_head: str,
    *,
    purpose: str | None = None,
    run_id: str | None = None,
    subject: str | None = None,
    attempt: str | None = None,
    commands: tuple[str, ...] | None = None,
) -> tuple[VerificationEvidence, ...]:
    """Require one digest-bound typed PASS proof for the exact code state."""
    if len(references) != 1:
        raise TransitionError("exactly one verification evidence reference is required")
    project_root = _project_root(run_dir).resolve()
    parsed: list[VerificationEvidence] = []
    for reference in references:
        path_and_digest, separator, recorded_head = reference.rpartition("@")
        raw_path, digest_separator, digest = path_and_digest.rpartition("#sha256=")
        if (
            separator != "@"
            or digest_separator != "#sha256="
            or recorded_head != expected_head
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not raw_path
            or any(character in raw_path for character in ",;|\n")
        ):
            raise TransitionError("verification reference must bind path, SHA-256, and exact code state")
        evidence_path = Path(raw_path)
        if evidence_path.is_absolute():
            raise TransitionError("verification evidence path must be repository-relative")
        evidence_path = project_root / evidence_path
        resolved = evidence_path.resolve()
        if not resolved.is_relative_to(project_root):
            raise TransitionError("verification evidence must remain inside the project workspace")
        try:
            content = resolved.read_bytes()
            text = content.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise TransitionError(f"verification evidence is unreadable: {resolved}: {exc}") from exc
        if hashlib.sha256(content).hexdigest() != digest:
            raise TransitionError("verification evidence digest does not match its immutable reference")
        lines = text.splitlines()
        if not lines or lines[0] != _VERIFICATION_MARKER:
            raise TransitionError("verification evidence marker is missing")
        values = dict(_key_values(lines[1:], _VERIFICATION_FIELDS, TransitionError))
        try:
            command_values = json.loads(values["commands"])
        except json.JSONDecodeError as exc:
            raise TransitionError("verification commands must be a JSON string array") from exc
        if (
            values["purpose"] not in _VERIFICATION_PURPOSES
            or not _TOKEN.fullmatch(values["run_id"])
            or not re.fullmatch(
                r"(?:project|(?:task|phase|gate)/[A-Za-z0-9][A-Za-z0-9._/-]*)",
                values["subject"],
            )
            or (values["attempt"] != "N/A" and not _TOKEN.fullmatch(values["attempt"]))
            or values["code_state"] != expected_head
            or values["outcome"] != "PASS"
            or not isinstance(command_values, list)
            or not command_values
            or any(not isinstance(command, str) or not command or "|" in command or "\n" in command for command in command_values)
            or len(command_values) != len(set(command_values))
            or values["environment"] in {"", "-"}
            or values["inputs"] in {"", "-"}
        ):
            raise TransitionError("verification evidence does not prove PASS on the applicable code state")
        record = VerificationEvidence(
            values["purpose"], values["run_id"], values["subject"],
            values["attempt"], values["code_state"], tuple(command_values),
            values["environment"], values["inputs"],
        )
        expected = (
            (purpose, record.purpose, "purpose"),
            (run_id, record.run_id, "run"),
            (subject, record.subject, "subject"),
            (attempt, record.attempt, "attempt"),
            (commands, record.commands, "commands"),
        )
        for wanted, actual, label in expected:
            if wanted is not None and wanted != actual:
                raise TransitionError(f"verification evidence {label} does not match the required identity")
        parsed.append(record)
    return tuple(parsed)


def _validate_persisted_final_verification(
    run_dir: Path,
    tracker: Tracker,
    gate: GateRecord,
) -> VerificationEvidence:
    references = tuple(
        item.removeprefix("final=")
        for item in _csv(gate.verification)
        if item.startswith("final=")
    )
    if len(references) != 1 or gate.state != "accepted" or gate.head == "-":
        raise TransitionError("accepted master gate has malformed final verification state")
    record = _validate_verification_evidence(
        run_dir, references, gate.head,
        purpose="final", run_id=tracker.run_id, subject="project", attempt="N/A",
    )[0]
    if not _is_target_tip(_project_root(run_dir), tracker.target_branch, gate.head):
        raise TransitionError("final verification no longer names the designated target tip")
    return record


def record_final_verification(
    run_dir: Path,
    *,
    head: str,
    commands: tuple[str, ...],
    evidence: tuple[str, ...],
    repo_dir: Path,
) -> Tracker:
    """Persist discoverable final evidence and the terminal complete action."""
    if not _COMMIT.fullmatch(head) or not commands or not evidence:
        raise TransitionError("final verification needs a full HEAD, commands, and evidence")
    transition_id = "final-verification-" + hashlib.sha256(
        "\0".join((head, *commands, *evidence)).encode("utf-8")
    ).hexdigest()

    def transition(tracker: Tracker) -> Tracker:
        gate = _gate_record(tracker, "master")
        existing = tuple(item for item in _csv(gate.verification) if item.startswith("final="))
        if existing:
            raise TransitionError("final verification is already recorded with different evidence")
        if gate.state != "accepted" or gate.head != head:
            raise TransitionError("final verification requires the accepted master-review HEAD")
        if not _is_target_tip(Path(repo_dir), tracker.target_branch, head):
            raise TransitionError("final verification HEAD is not the designated target tip")
        if _git_output(Path(repo_dir), "status", "--porcelain", "--untracked-files=no"):
            raise TransitionError("tracked working-tree changes prevent final completion")
        _validate_verification_evidence(
            Path(run_dir), evidence, head,
            purpose="final", run_id=tracker.run_id, subject="project", attempt="N/A",
            commands=commands,
        )
        reference = evidence[0]
        updated = _replace_gate(
            tracker,
            replace(gate, verification=_append_history(gate.verification, f"final={reference}")),
        )
        _validate_persisted_final_verification(Path(run_dir), updated, _gate_record(updated, "master"))
        return updated

    return locked_tracker_update(
        Path(run_dir), transition_id, transition,
        timeout_s=5.0, refresh_next_action=True,
    )


def _artifact_evidence_references(task: TaskRecord) -> tuple[str, ...]:
    references = []
    for item in _csv(task.verification):
        candidate = item.removeprefix("evidence:")
        if "#sha256=" in candidate and "@" in candidate:
            references.append(candidate)
    return tuple(references)


def _validate_artifact_evidence(
    run_dir: Path,
    tracker: Tracker,
    task: TaskRecord,
    definition: PlannedTask,
    references: tuple[str, ...],
    repo_dir: Path,
    *,
    require_target_tip: bool,
) -> VerificationEvidence:
    if task.kind != "artifact" or definition.kind != "artifact":
        raise TransitionError("artifact evidence can validate only a plan-declared artifact task")
    if tuple(_csv(task.artifacts)) not in {(), definition.outputs}:
        raise TransitionError("recorded artifact outputs conflict with the approved task definition")
    if len(references) != 1:
        raise TransitionError("artifact completion needs exactly one typed validation record")
    _, separator, recorded_head = references[0].rpartition("@")
    if separator != "@" or not _COMMIT.fullmatch(recorded_head):
        raise TransitionError("artifact validation must bind one full code-state commit")
    records = _validate_verification_evidence(
        run_dir, references, recorded_head,
        purpose="task-test", run_id=tracker.run_id,
        subject=f"task/{task.id}", attempt=task.attempt,
    )
    try:
        inputs = json.loads(records[0].inputs)
    except json.JSONDecodeError as exc:
        raise TransitionError("artifact validation inputs must be a JSON string array") from exc
    if (
        not isinstance(inputs, list)
        or any(not isinstance(item, str) for item in inputs)
        or len(inputs) != len(set(inputs))
    ):
        raise TransitionError("artifact validation inputs must be unique digest-bound output identities")
    input_paths = tuple(item.rpartition("#sha256=")[0] for item in inputs)
    if input_paths != definition.outputs:
        raise TransitionError("artifact validation inputs do not exactly match approved outputs")
    project_root = _project_root(run_dir).resolve()
    if Path(repo_dir).resolve() != project_root:
        raise TransitionError("artifact validation repository root does not match the run workspace")
    for identity in inputs:
        _resolve_digest_bound_reference(run_dir, identity)
    if require_target_tip:
        if not _is_target_tip(project_root, tracker.target_branch, recorded_head):
            raise TransitionError("artifact validation code state is not the designated target branch tip")
    elif not _git(project_root, "merge-base", "--is-ancestor", recorded_head, tracker.target_branch):
        raise TransitionError("artifact validation code state is no longer on the target branch")
    return records[0]


def _parse_review_report(
    path: Path,
    *,
    allow_sealed_historical: bool = False,
) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"review report is unreadable: {path}: {exc}") from exc
    marker = "<!-- pipeline-review-report/v2 -->"
    positions = [index for index, line in enumerate(lines) if line == marker]
    if len(positions) != 1:
        raise TransitionError("review report needs exactly one terminal report marker")
    report_lines = lines[positions[0] + 1:]
    try:
        return dict(_key_values(report_lines, _REVIEW_FIELDS, TransitionError))
    except TransitionError:
        if not allow_sealed_historical:
            raise
    return dict(_key_values(report_lines, _HISTORICAL_REVIEW_FIELDS, TransitionError))


def _review_outcomes(report: dict[str, str]) -> dict[str, str]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        values: dict[str, object] = {}
        for key, value in pairs:
            if key in values:
                raise TransitionError(f"review outcomes contains duplicate finding {key}")
            values[key] = value
        return values

    try:
        outcomes = json.loads(report["outcomes"], object_pairs_hook=unique_object)
    except (KeyError, json.JSONDecodeError) as exc:
        raise TransitionError("new review report needs a valid outcomes JSON object") from exc
    if (
        not isinstance(outcomes, dict)
        or any(
            not isinstance(finding, str)
            or not _TOKEN.fullmatch(finding)
            or outcome not in {"Open", "Resolved"}
            for finding, outcome in outcomes.items()
        )
    ):
        raise TransitionError("review outcomes must map finding IDs to Open or Resolved")
    return outcomes


def _digest_bound_reference(run_dir: Path, path: Path) -> str:
    project_root = _project_root(run_dir).resolve()
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(project_root).as_posix()
    except ValueError as exc:
        raise TransitionError("review evidence must remain inside the project workspace") from exc
    if any(character in relative for character in ",;|#\n"):
        raise TransitionError("review evidence path contains an unsupported identity delimiter")
    try:
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        raise TransitionError(f"review evidence is unreadable: {resolved}: {exc}") from exc
    return f"{relative}#sha256={digest}"


def _resolve_digest_bound_reference(run_dir: Path, value: str) -> Path:
    raw_path, separator, digest = value.rpartition("#sha256=")
    if separator != "#sha256=" or not raw_path or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise TransitionError("review evidence reference must bind a path and SHA-256 digest")
    path = _resolved_reference(run_dir, raw_path).resolve()
    project_root = _project_root(run_dir).resolve()
    if not path.is_relative_to(project_root):
        raise TransitionError("review evidence must remain inside the project workspace")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise TransitionError(f"review evidence is unreadable: {path}: {exc}") from exc
    if hashlib.sha256(content).hexdigest() != digest:
        raise TransitionError("review evidence digest does not match its immutable identity")
    return path


def _finding_origin_identity(
    row: tuple[str, ...],
    report_identities: tuple[str, ...],
    reports: tuple[dict[str, str], ...],
) -> str:
    finding_id, gate_id, severity = row[:3]
    introducing = tuple(
        identity
        for identity, report in zip(report_identities, reports)
        if finding_id in _csv(report["findings"])
    )
    if not introducing:
        raise TransitionError(f"finding {finding_id} has no introducing review report")
    payload = json.dumps(
        [finding_id, gate_id, severity, *introducing],
        separators=(",", ":"), sort_keys=False,
    ).encode("utf-8")
    return f"{finding_id}@{severity}@sha256={hashlib.sha256(payload).hexdigest()}"


def _sealed_review_package(
    run_dir: Path,
    gate: GateRecord,
    report_paths: tuple[Path, ...],
    rows: tuple[tuple[str, ...], ...],
    *,
    allow_sealed_historical: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    reports, report_head = _review_report_set(
        tuple(Path(path).resolve() for path in report_paths),
        gate=gate, expected_base=gate.base,
        allow_sealed_historical=allow_sealed_historical,
    )
    if report_head != gate.head:
        raise TransitionError("initial reports do not match the gate's opened HEAD")
    identities = tuple(_digest_bound_reference(run_dir, path) for path in report_paths)
    origins = tuple(
        _finding_origin_identity(row, identities, reports)
        for row in sorted(rows, key=lambda item: item[0])
    )
    return identities, origins


def _validate_sealed_gate_evidence(
    run_dir: Path,
    tracker: Tracker,
    gate: GateRecord,
    findings_path: Path,
    *,
    finding_ids: set[str] | None = None,
) -> None:
    report_values = _csv(gate.reports)
    origins = tuple(_parse_finding_origin(value) for value in _csv(gate.findings))
    if not report_values or any(origin is None for origin in origins):
        raise TransitionError("blocked gate review evidence has not been digest-sealed")
    report_paths = tuple(_resolve_digest_bound_reference(run_dir, value) for value in report_values)
    rows = tuple(
        row for row in _parse_findings(findings_path)
        if row[1] == gate.id and (finding_ids is None or row[0] in finding_ids)
    )
    reports, initial_head = _review_report_set(
        report_paths, gate=gate, expected_base=gate.base,
        allow_sealed_historical=True,
    )
    repo_dir = _project_root(run_dir)
    if not _git(repo_dir, "merge-base", "--is-ancestor", initial_head, gate.head):
        raise TransitionError("sealed initial review HEAD is not an ancestor of the current gate HEAD")
    expected_reports = tuple(_digest_bound_reference(run_dir, path) for path in report_paths)
    ordered_rows = tuple(sorted(rows, key=lambda item: item[0]))
    expected_by_id = {
        row[0]: _finding_origin_identity(row, expected_reports, reports)
        for row in ordered_rows
        if any(row[0] in _csv(report["findings"]) for report in reports)
    }
    pending = {row[0] for row in ordered_rows} - set(expected_by_id)
    cursor = initial_head
    for remediation in sorted(
        (
            row for row in tracker.remediation
            if row.gate == gate.id and row.state == "complete"
        ),
        key=lambda row: row.round_number,
    ):
        if not pending:
            break
        paths = tuple(
            _resolve_digest_bound_reference(run_dir, value)
            for value in _csv(remediation.re_review)
        )
        wave_reports, cursor = _review_report_set(
            paths, gate=gate, expected_base=cursor,
            allow_sealed_historical=True,
        )
        identities = tuple(_digest_bound_reference(run_dir, path) for path in paths)
        for row in ordered_rows:
            if row[0] in pending and any(
                row[0] in _csv(report["findings"]) for report in wave_reports
            ):
                expected_by_id[row[0]] = _finding_origin_identity(
                    row, identities, wave_reports,
                )
                pending.remove(row[0])
    if pending:
        raise TransitionError(
            f"finding {sorted(pending)[0]} has no introducing review report"
        )
    expected_origins = tuple(expected_by_id[row[0]] for row in ordered_rows)
    recorded_origins = tuple(
        value for value in _csv(gate.findings)
        if finding_ids is None or (_parse_finding_origin(value) or (value, "", ""))[0] in finding_ids
    )
    if report_values != expected_reports or recorded_origins != expected_origins:
        raise TransitionError("review reports or finding origins conflict with the sealed gate package")


_MASTER_ROUND_ONE_SEAL_RUN = "2026-09-08-pipeline-rebuild-v2"
_MASTER_ROUND_ONE_SEAL_REVISION = 119
_MASTER_ROUND_ONE_SEAL_TRACKER_DIGEST = "5e07cd560718630adad54ed3d016fd69bb2110c699c261b13b419e5a91c8305e"
_MASTER_ROUND_ONE_SEAL_FINDINGS = tuple(f"MASTER-{number:03d}" for number in range(1, 7))
_MASTER_ROUND_ONE_SEAL_FIXER = "master-fixer-controller"
_MASTER_ROUND_ONE_SEAL_REPORT_DIGESTS = (
    "9060f4156f48b6259b933d4c5d47f138c5adb68d1d9ce816f5e1b686d9056542",
    "58386de65448288f7492edd417d6f368faaecf7e6ea2e456894e01ae7c28eebb",
)
_MASTER_ROUND_ONE_SEAL_FINDINGS_DIGEST = "dd459120587218de73e66570bef396226bf9c611557cbcd79d5db644d9837e86"


def seal_active_master_round_one(run_dir: Path) -> Tracker:
    """Seal the exact D-027 bootstrap package before fix recording or re-review."""
    run_dir = Path(run_dir)
    marker_prefix = "master-initial-seal:"

    def already_sealed(tracker: Tracker) -> bool:
        row = next(
            (item for item in tracker.remediation if item.gate == "master" and item.round_number == 1),
            None,
        )
        if row is None or not any(item.startswith(marker_prefix) for item in _csv(row.verification)):
            return False
        gate = _gate_record(tracker, "master")
        findings_path = _resolved_reference(run_dir, dict(tracker.run_fields)["findings"])
        _validate_sealed_gate_evidence(run_dir, tracker, gate, findings_path)
        return True

    try:
        current = validate_run(run_dir)
    except SchemaError:
        current = None
    if current is not None and already_sealed(current):
        return current

    with _exclusive_lock(run_dir, timeout_s=5.0):
        progress = run_dir / "progress.md"
        source = progress.read_bytes()
        if hashlib.sha256(source).hexdigest() != _MASTER_ROUND_ONE_SEAL_TRACKER_DIGEST:
            raise TransitionError("D-027 sealing tracker digest does not match the authorized post-start state")
        tracker = _parse_tracker_for_exact_reconciliation(source.decode("utf-8"))
        if tracker.run_id != _MASTER_ROUND_ONE_SEAL_RUN or tracker.revision != _MASTER_ROUND_ONE_SEAL_REVISION:
            raise TransitionError("D-027 sealing run or revision does not match the authorized state")
        gate = _gate_record(tracker, "master")
        row = next(
            (item for item in tracker.remediation if item.gate == "master" and item.round_number == 1),
            None,
        )
        if (
            gate.state != "blocked"
            or _csv(gate.findings) != _MASTER_ROUND_ONE_SEAL_FINDINGS
            or row is None
            or row.state != "fixing"
            or _csv(row.findings) != _MASTER_ROUND_ONE_SEAL_FINDINGS
            or row.fixers != _MASTER_ROUND_ONE_SEAL_FIXER
            or row.commits != "-"
            or row.re_review != "-"
        ):
            raise TransitionError("D-027 sealing gate or round shape is not the authorized bootstrap state")
        report_paths = tuple(_resolved_reference(run_dir, value).resolve() for value in _csv(gate.reports))
        observed_report_digests = tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in report_paths)
        findings_path = _resolved_reference(run_dir, dict(tracker.run_fields)["findings"]).resolve()
        if observed_report_digests != _MASTER_ROUND_ONE_SEAL_REPORT_DIGESTS:
            raise TransitionError("D-027 initial review reports changed before sealing")
        if hashlib.sha256(findings_path.read_bytes()).hexdigest() != _MASTER_ROUND_ONE_SEAL_FINDINGS_DIGEST:
            raise TransitionError("D-027 findings ledger changed before sealing")
        rows = tuple(row_ for row_ in _parse_findings(findings_path) if row_[1] == gate.id)
        if tuple(sorted(row_[0] for row_ in rows)) != _MASTER_ROUND_ONE_SEAL_FINDINGS:
            raise TransitionError("D-027 findings ledger no longer has the authorized finding set")
        report_identities, origins = _sealed_review_package(
            run_dir, gate, report_paths, rows,
            allow_sealed_historical=True,
        )
        seal_payload = json.dumps(
            [*report_identities, *origins], separators=(",", ":")
        ).encode("utf-8")
        seal_digest = hashlib.sha256(seal_payload).hexdigest()
        sealed_gate = replace(
            gate,
            reports=",".join(report_identities),
            findings=",".join(origins),
        )
        sealed_row = replace(row, verification=f"{marker_prefix}{seal_digest}")
        proposed = replace(
            _replace_gate(tracker, sealed_gate),
            remediation=tuple(sealed_row if item is row else item for item in tracker.remediation),
        )
        proposed = _with_next_action(proposed, derive_next_action(run_dir, proposed))
        transition_id = f"seal-master-round-1-{seal_digest}"
        updated = _with_transition_identity(proposed, transition_id, tracker.revision + 1)
        canonical = render_tracker(updated)
        reparsed = parse_tracker(canonical)
        _replace_tracker(run_dir, canonical, transition_id)
        return reparsed


def _parse_findings(path: Path) -> tuple[tuple[str, ...], ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"findings ledger is unreadable: {path}: {exc}") from exc
    if not lines or lines[0] != "<!-- pipeline-findings/v2 -->":
        raise TransitionError("findings ledger marker is missing")
    content = [line for line in lines[1:] if line]
    if len(content) < 2 or _cells(content[0], TransitionError) != _FINDING_HEADER:
        raise TransitionError(f"expected findings table header: {_FINDING_HEADER!r}")
    separator = _cells(content[1], TransitionError)
    if len(separator) != len(_FINDING_HEADER) or any(value != "---" for value in separator):
        raise TransitionError("invalid findings table separator")
    rows = tuple(_cells(line, TransitionError) for line in content[2:])
    if any(len(row) != len(_FINDING_HEADER) for row in rows):
        raise TransitionError("finding rows must be complete")
    ids = [row[0] for row in rows]
    if len(ids) != len(set(ids)):
        raise TransitionError("finding IDs must be unique")
    return rows


def _resolved_decision_for_terms(
    run_dir: Path,
    tracker: Tracker,
    decision_ref: str,
    terms: set[str],
) -> str:
    decisions_path = _resolved_reference(run_dir, dict(tracker.run_fields)["decisions"])
    try:
        sections = _decision_sections(decisions_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"cannot read recorded decisions at {decisions_path}: {exc}") from exc
    lines = sections.get(decision_ref)
    if lines is None:
        raise TransitionError(f"decision {decision_ref} is missing")
    answers = _field_lines(lines, "Answer")
    questions = _field_lines(lines, "Question")
    statuses = _field_lines(lines, "Status")
    scopes = _field_lines(lines, "Scope") + _field_lines(lines, "Affected task") + _field_lines(lines, "Affected work")
    if len(questions) != 1 or len(answers) != 1 or len(statuses) != 1 or not scopes:
        raise TransitionError("decision evidence is missing, duplicated, or conflicting")
    _require_decision_action(lines, "review.resolve-question")
    answer = answers[0].strip().rstrip(".")
    if not answer or answer.casefold() in {"approved", "yes", "continue", "proceed", "go", "pending user response"}:
        raise TransitionError("generic approval or an empty answer cannot resolve a review blocker")
    if statuses[0].strip().rstrip(".").casefold() != "resolved":
        raise TransitionError("decision is not resolved")
    if not any(_scope_names_task(scope, term) for scope in scopes for term in terms):
        raise TransitionError("decision is unrelated to the current review blocker")
    for other_ref, other_lines in sections.items():
        if other_ref == decision_ref:
            continue
        other_status = _field_lines(other_lines, "Status")
        other_questions = _field_lines(other_lines, "Question")
        other_scopes = _field_lines(other_lines, "Scope") + _field_lines(other_lines, "Affected task") + _field_lines(other_lines, "Affected work")
        other_answers = _field_lines(other_lines, "Answer")
        if (
            len(other_status) == 1
            and other_status[0].strip().rstrip(".").casefold() in {"open", "pending", "blocked"}
            and any(_scope_names_task(scope, term) for scope in other_scopes for term in terms)
        ):
            raise TransitionError(f"unresolved decision {other_ref} still blocks review acceptance")
        if (
            len(other_status) == 1
            and other_status[0].strip().rstrip(".").casefold() == "resolved"
            and len(other_questions) == 1
            and other_questions[0].strip().rstrip(".").casefold()
            == questions[0].strip().rstrip(".").casefold()
            and len(other_answers) == 1
            and other_answers[0].strip().rstrip(".").casefold() != answer.casefold()
            and any(_scope_names_task(scope, term) for scope in other_scopes for term in terms)
        ):
            raise TransitionError(f"resolved decision {other_ref} conflicts on the same review scope")
    return answer


def resolve_gate_questions(
    run_dir: Path,
    *,
    gate_id: str,
    decision_refs: tuple[str, ...],
) -> Tracker:
    """Clear only current gate questions backed by applicable explicit decisions."""
    if not decision_refs or len(decision_refs) != len(set(decision_refs)):
        raise TransitionError("gate question resolution needs unique decision references")

    def transition(tracker: Tracker) -> Tracker:
        gate = _gate_record(tracker, gate_id)
        if set(_csv(gate.questions)) != set(decision_refs):
            raise TransitionError("decision references do not exactly match the current gate questions")
        terms = {gate.id, *_gate_finding_ids(gate)}
        if gate.phase != "-":
            terms.add(gate.phase)
        for decision_ref in decision_refs:
            _resolved_decision_for_terms(Path(run_dir), tracker, decision_ref, terms)
        return _replace_gate(tracker, replace(gate, questions="-"))

    return locked_tracker_update(
        Path(run_dir), f"resolve-gate-{gate_id}-{'-'.join(sorted(decision_refs))}",
        transition, timeout_s=5.0, refresh_next_action=True,
    )


def _validate_remediation_extension_decision(
    run_dir: Path,
    tracker: Tracker,
    *,
    decision_ref: str,
    gate_id: str,
    round_number: int,
    finding_ids: tuple[str, ...],
) -> None:
    decisions_path = _resolved_reference(run_dir, dict(tracker.run_fields)["decisions"])
    try:
        sections = _decision_sections(decisions_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TransitionError) as exc:
        raise TransitionError(f"cannot read remediation-extension decision: {exc}") from exc
    lines = sections.get(decision_ref)
    if lines is None:
        raise TransitionError(f"remediation-extension decision {decision_ref} is missing")
    required = {
        "Question": _field_lines(lines, "Question"),
        "Answer": _field_lines(lines, "Answer"),
        "Decision action": _field_lines(lines, "Decision action"),
        "Authorized run": _field_lines(lines, "Authorized run"),
        "Source revision": _field_lines(lines, "Source revision"),
        "Authorized gate": _field_lines(lines, "Authorized gate"),
        "Required state": _field_lines(lines, "Required state"),
        "Required question": _field_lines(lines, "Required question"),
        "Predecessor decision": _field_lines(lines, "Predecessor decision"),
        "Authorized through round": _field_lines(lines, "Authorized through round"),
        "Authorized findings": _field_lines(lines, "Authorized findings"),
        "Authority marker": _field_lines(lines, "Authority marker"),
        "Scope": _field_lines(lines, "Scope"),
        "Status": _field_lines(lines, "Status"),
    }
    if any(len(values) != 1 for values in required.values()):
        raise TransitionError("remediation-extension decision evidence is incomplete or ambiguous")
    _require_decision_action(lines, "remediation.start-round")
    answer = required["Answer"][0].strip().rstrip(".")
    if required["Status"][0].strip().rstrip(".").casefold() != "resolved":
        raise TransitionError("remediation-extension decision is unresolved")
    if required["Authorized gate"][0] != gate_id:
        raise TransitionError("remediation-extension decision names a different gate")
    if required["Authorized run"][0] != tracker.run_id:
        raise TransitionError("remediation-extension decision names a different run")
    if required["Source revision"][0] != str(tracker.revision):
        raise TransitionError("remediation-extension decision is stale for this tracker revision")
    gate = _gate_record(tracker, gate_id)
    if required["Required state"][0] != gate.state or required["Required question"][0] != gate.questions:
        raise TransitionError("remediation-extension decision does not match the required gate state")
    if round_number == 4:
        predecessor = "D-006"
    else:
        prior = next(
            (
                row for row in tracker.remediation
                if row.gate == gate_id and row.round_number == round_number - 1
            ),
            None,
        )
        authorities = (
            tuple(item.split("=", 1)[1] for item in _csv(prior.verification) if item.startswith("extension-authority="))
            if prior is not None else ()
        )
        if len(authorities) != 1:
            raise TransitionError("remediation-extension predecessor authority is missing or ambiguous")
        predecessor = authorities[0]
    if required["Predecessor decision"][0] != predecessor:
        raise TransitionError("remediation-extension decision names a different predecessor authority")
    if required["Authorized through round"][0] != str(round_number):
        raise TransitionError("remediation-extension decision names a different round ceiling")
    if tuple(_csv(required["Authorized findings"][0])) != finding_ids:
        raise TransitionError("remediation-extension decision names a different finding set")
    if required["Authority marker"][0] != f"remediation-extension:{gate_id}:through-round-{round_number}":
        raise TransitionError("remediation-extension authority marker is invalid")
    if gate_id.casefold() not in required["Scope"][0].casefold():
        raise TransitionError("remediation-extension decision scope is unrelated to the requested gate")


def start_remediation_round(
    run_dir: Path,
    *,
    gate_id: str,
    round_number: int,
    finding_ids: tuple[str, ...],
    fix_plan: str,
    fixer_assignments: tuple[str, ...] = (),
    capacity: int | None = None,
    extension_decision_ref: str | None = None,
) -> Tracker:
    if (
        round_number < 1
        or not finding_ids
        or len(finding_ids) != len(set(finding_ids))
        or not fixer_assignments
        or len(fixer_assignments) != len(set(fixer_assignments))
    ):
        raise TransitionError("remediation round must be positive with unique targeted findings")
    if round_number <= 3 and extension_decision_ref is not None:
        raise TransitionError("ordinary remediation rounds do not accept extension authority")
    if round_number > 3 and (
        extension_decision_ref is None or re.fullmatch(r"D-[0-9]+", extension_decision_ref) is None
    ):
        raise TransitionError("a post-limit round requires an explicit finite-extension decision")
    def transition(tracker: Tracker) -> Tracker:
        fix_plan_path = _review_evidence_path(Path(run_dir), fix_plan)
        fix_plan_identity = _digest_bound_reference(Path(run_dir), fix_plan_path)
        gate = _gate_record(tracker, gate_id)
        rows = list(tracker.remediation)
        existing = next((row for row in rows if row.gate == gate_id and row.round_number == round_number), None)
        authority = f"extension-authority={extension_decision_ref}" if extension_decision_ref else "-"
        replacement = RemediationRecord(
            gate_id, round_number, "fixing", ",".join(fixer_assignments), "-",
            ",".join(finding_ids), fix_plan_identity, "-", authority, "-",
        )
        _remediation_scope(Path(run_dir), replacement)
        if (
            existing is not None
            and existing.state == "fixing"
            and existing.findings == ",".join(finding_ids)
            and existing.fix_plan == fix_plan_identity
            and existing.fixers == ",".join(fixer_assignments)
            and existing.verification == authority
        ):
            raise _AlreadyApplied(tracker)
        if gate.state != "blocked":
            raise TransitionError("remediation requires a blocked gate")
        if round_number > 3:
            expected_questions = {
                f"remediation-no-progress-round-{round_number - 1}",
                f"remediation-oscillation-round-{round_number - 1}",
                f"remediation-limit-reached-round-{round_number - 1}",
            }
            if gate.questions not in expected_questions:
                raise TransitionError("finite extension does not resolve the gate's current stop reason")
            _validate_remediation_extension_decision(
                Path(run_dir), tracker, decision_ref=extension_decision_ref,
                gate_id=gate_id, round_number=round_number, finding_ids=finding_ids,
            )
        elif gate.questions != "-":
            raise TransitionError("an unresolved gate question prevents remediation dispatch")
        _validate_worker_capacity(
            tracker, fixer_assignments,
            _detected_runtime_capacity(Path(run_dir), tracker),
        )
        authoritative_findings = _resolved_reference(
            Path(run_dir), dict(tracker.run_fields)["findings"]
        )
        _validate_sealed_gate_evidence(Path(run_dir), tracker, gate, authoritative_findings)
        finding_rows = tuple(
            row for row in _parse_findings(authoritative_findings)
            if row[1] == gate.id
        )
        open_blockers = {
            row[0]
            for row in finding_rows
            if row[1] == gate.id and row[2] in {"Critical", "Important"} and row[3] == "Open"
        }
        authorized_minors: set[str] = set()
        for row in finding_rows:
            finding_id, _, severity, status, disposition, evidence, fix_commit, re_review = row
            if severity != "Minor" or status != "Open":
                continue
            if disposition != "-" or fix_commit != "-" or re_review != "-" or not re.fullmatch(r"D-[0-9]+", evidence):
                raise TransitionError("an open Minor needs one explicit fix-disposition decision reference")
            answer = _resolved_decision_for_terms(
                Path(run_dir), tracker, evidence, {gate.id, finding_id},
            )
            if "fix" not in answer.casefold():
                raise TransitionError("Minor decision does not explicitly authorize fixing this finding")
            authorized_minors.add(finding_id)
        if set(finding_ids) != open_blockers | authorized_minors:
            raise TransitionError("remediation targets must match open blockers and authorized Minor fixes")
        if existing is not None and existing.state != "pending":
            raise TransitionError("remediation round is already used or conflicting")
        if round_number > 1:
            prior = next((row for row in rows if row.gate == gate_id and row.round_number == round_number - 1), None)
            if prior is None or prior.state != "complete":
                raise TransitionError("prior remediation round is not complete")
        if existing is None:
            rows.append(replacement)
        else:
            rows[rows.index(existing)] = replacement
        updated = replace(tracker, remediation=tuple(rows))
        if round_number > 3:
            updated = _replace_gate(updated, replace(gate, questions="-"))
        return updated

    try:
        return locked_tracker_update(
            Path(run_dir), f"remediate-{gate_id}-{round_number}", transition,
            timeout_s=5.0, refresh_next_action=True,
        )
    except _AlreadyApplied as applied:
        return applied.tracker


def record_remediation_fixes(
    run_dir: Path,
    *,
    gate_id: str,
    round_number: int,
    fix_head: str,
    commits: tuple[str, ...],
    verification: tuple[str, ...],
    capacity: int | None,
    repo_dir: Path,
) -> Tracker:
    """Release fixers and reserve the existing independent reviewers for re-review."""
    if not _COMMIT.fullmatch(fix_head) or not verification:
        raise TransitionError("fix integration needs a HEAD and verification")

    def transition(tracker: Tracker) -> Tracker:
        gate = _gate_record(tracker, gate_id)
        row = next(
            (item for item in tracker.remediation if item.gate == gate_id and item.round_number == round_number),
            None,
        )
        if row is None or row.state != "fixing" or row.fixers == "-":
            raise TransitionError("only an active fixing round can move to re-review")
        scope = _remediation_scope(Path(run_dir), row)
        all_artifact = bool(scope) and all(kind == "artifact" for kind, _ in scope.values())
        _validate_sealed_gate_evidence(
            Path(run_dir), tracker, gate,
            _resolved_reference(Path(run_dir), dict(tracker.run_fields)["findings"]),
        )
        _validate_verification_evidence(
            Path(run_dir), verification, fix_head,
            purpose="remediation", run_id=tracker.run_id,
            subject=f"gate/{gate_id}", attempt=f"round-{round_number}",
        )
        if gate.state != "blocked" or gate.questions != "-":
            raise TransitionError("gate is not eligible for re-review")
        if not _git(Path(repo_dir), "cat-file", "-e", f"{fix_head}^{{commit}}") or not _is_target_tip(
            Path(repo_dir), tracker.target_branch, fix_head
        ):
            raise TransitionError("fix HEAD is not integrated on the target branch")
        if all_artifact:
            if commits or fix_head != gate.head:
                raise TransitionError("an all-artifact round uses no commits and preserves the reviewed HEAD")
        elif (
            not commits
            or fix_head == gate.head
            or not _git(Path(repo_dir), "merge-base", "--is-ancestor", gate.head, fix_head)
            or any(
                not _COMMIT.fullmatch(commit)
                or _git(Path(repo_dir), "merge-base", "--is-ancestor", commit, gate.head)
                or not _git(Path(repo_dir), "merge-base", "--is-ancestor", gate.head, commit)
                or not _git(Path(repo_dir), "merge-base", "--is-ancestor", commit, fix_head)
                for commit in commits
            )
        ):
            raise TransitionError("fix commit lacks strict post-review provenance in the integrated fix HEAD")
        released = _append_history(row.released_fixers, row.fixers)
        updated_row = replace(
            row,
            state="re_reviewing",
            fixers="-",
            released_fixers=released,
            commits=",".join(commits) if commits else "N/A",
            verification=_append_history(row.verification, ",".join(verification)),
        )
        interim = replace(
            tracker,
            remediation=tuple(updated_row if item is row else item for item in tracker.remediation),
        )
        assignments = _csv(gate.assignments)
        _validate_review_queue_capacity(
            interim, assignments,
            _detected_runtime_capacity(Path(run_dir), interim),
        )
        return _replace_gate(interim, replace(gate, state="re_reviewing"))

    return locked_tracker_update(
        Path(run_dir), f"fixes-{gate_id}-{round_number}-{fix_head}", transition,
        timeout_s=5.0, refresh_next_action=True,
    )


def _recorded_remaining_blockers(row: RemediationRecord | None) -> set[str] | None:
    if row is None:
        return None
    entries = [item for item in _csv(row.verification) if item.startswith("remaining-blockers=")]
    if len(entries) != 1:
        return None
    value = entries[0].split("=", 1)[1]
    return set() if value == "none" else set(value.split("+"))


_ACTIVE_ROUND_OUTCOME_RUN = "2026-09-08-pipeline-rebuild-v2"
_ACTIVE_ROUND_OUTCOME_GATE = "phase-01"
_ACTIVE_ROUND_OUTCOME_ROUND = 1
_ACTIVE_ROUND_OUTCOME_DECISION = "D-019"
_ACTIVE_ROUND_OUTCOME_BLOCKERS = {
    "P1-GATE-002", "P1-GATE-004", "P1-GATE-007", "P1-GATE-008",
}


def _round_outcomes_from_notes(path: Path, report_ids: set[str]) -> set[str]:
    """Read the fixed Round 1 finding-results table used by D-019."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"round outcome notes are unreadable: {path}: {exc}") from exc
    try:
        start = lines.index("| Finding | Result | Evidence |")
    except ValueError as exc:
        raise TransitionError("round outcome notes have no finding-results table") from exc
    if start + 1 >= len(lines) or _cells(lines[start + 1], TransitionError) != ("---", "---", "---"):
        raise TransitionError("round outcome notes have an invalid table separator")
    rows: list[tuple[str, ...]] = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        row = _cells(line, TransitionError)
        if len(row) != 3:
            raise TransitionError("round outcome rows must have finding, result, and evidence")
        rows.append(row)
    ids = [row[0] for row in rows]
    if set(ids) != report_ids or len(ids) != len(set(ids)):
        raise TransitionError("round outcome notes do not cover each reported finding exactly once")
    open_ids: set[str] = set()
    for finding_id, result, evidence in rows:
        if evidence == "-":
            raise TransitionError("round outcome notes need evidence for every finding")
        if result == "Resolved":
            continue
        if result not in {"Open — Critical", "Open — Important"}:
            raise TransitionError("round outcome notes contain an unsupported or ambiguous result")
        open_ids.add(finding_id)
    return open_ids


def _validate_active_round_outcome_decision(run_dir: Path, tracker: Tracker, decision_ref: str) -> None:
    if decision_ref != _ACTIVE_ROUND_OUTCOME_DECISION:
        raise TransitionError("the active round-outcome repair requires decision D-019")
    path = _resolved_reference(run_dir, dict(tracker.run_fields)["decisions"])
    try:
        sections = _decision_sections(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TransitionError) as exc:
        raise TransitionError(f"cannot read the D-019 reconciliation decision: {exc}") from exc
    lines = sections.get(decision_ref)
    if lines is None:
        raise TransitionError("decision D-019 is missing")
    answers = _field_lines(lines, "Answer")
    statuses = _field_lines(lines, "Status")
    scopes = _field_lines(lines, "Scope") + _field_lines(lines, "Affected work")
    if len(answers) != 1 or len(statuses) != 1 or not scopes:
        raise TransitionError("decision D-019 is missing, duplicated, or conflicting")
    if statuses[0].strip().rstrip(".").casefold() != "resolved":
        raise TransitionError("decision D-019 is unresolved")
    authority = " ".join((answers[0], *scopes))
    required_terms = {
        _ACTIVE_ROUND_OUTCOME_RUN,
        _ACTIVE_ROUND_OUTCOME_GATE,
        "Round 1",
        *_ACTIVE_ROUND_OUTCOME_BLOCKERS,
    }
    if any(term.casefold() not in authority.casefold() for term in required_terms):
        raise TransitionError("decision D-019 does not authorize this exact run, gate, round, and blocker set")
    for other_ref, other_lines in sections.items():
        if other_ref == decision_ref:
            continue
        other_status = _field_lines(other_lines, "Status")
        other_scope = " ".join(
            _field_lines(other_lines, "Scope") + _field_lines(other_lines, "Affected work")
        ).casefold()
        if (
            len(other_status) == 1
            and other_status[0].strip().rstrip(".").casefold() in {"open", "pending", "blocked"}
            and _ACTIVE_ROUND_OUTCOME_RUN.casefold() in other_scope
            and _ACTIVE_ROUND_OUTCOME_GATE in other_scope
        ):
            raise TransitionError(f"unresolved decision {other_ref} conflicts with D-019")


def reconcile_active_rebuild_round_one_outcome(
    run_dir: Path,
    *,
    expected_revision: int,
    expected_tracker_sha256: str,
    decision_ref: str,
    report_path: Path,
    notes_path: Path,
) -> Tracker:
    """Apply D-019's one exact-run repair; ordinary resume never calls this."""
    if expected_revision < 0 or not re.fullmatch(r"[0-9a-f]{64}", expected_tracker_sha256):
        raise TransitionError("round-outcome reconciliation needs an expected revision and tracker digest")
    run_dir = Path(run_dir).resolve()
    if run_dir.name != _ACTIVE_ROUND_OUTCOME_RUN:
        raise TransitionError("round-outcome reconciliation is restricted to the identified active rebuild run")
    report_path = Path(report_path).resolve()
    notes_path = Path(notes_path).resolve()
    if notes_path != report_path.with_name(report_path.stem + "-notes.md"):
        raise TransitionError("round-outcome notes do not match the immutable re-review evidence package")
    try:
        report_bytes = report_path.read_bytes()
        notes_bytes = notes_path.read_bytes()
        source = (run_dir / "progress.md").read_bytes()
    except OSError as exc:
        raise TransitionError(f"round-outcome reconciliation evidence is unreadable: {exc}") from exc
    evidence_digest = hashlib.sha256(report_bytes + b"\0" + notes_bytes).hexdigest()
    provenance = f"round-outcome-reconciliation={decision_ref}@{evidence_digest}"
    outcome = "remaining-blockers=" + "+".join(sorted(_ACTIVE_ROUND_OUTCOME_BLOCKERS))
    transition_id = f"D-019-round-01-{evidence_digest[:16]}"

    try:
        current = parse_tracker(source.decode("utf-8"))
    except (SchemaError, UnicodeError):
        current = None
    if current is not None:
        if current.run_id != _ACTIVE_ROUND_OUTCOME_RUN:
            raise TransitionError("D-019 replay run identity does not match")
        _validate_active_round_outcome_decision(run_dir, current, decision_ref)
        row = next(
            (item for item in current.remediation if item.gate == _ACTIVE_ROUND_OUTCOME_GATE and item.round_number == 1),
            None,
        )
        if row is not None and outcome in _csv(row.verification) and provenance in _csv(row.verification):
            return current
        raise TransitionError("the active tracker no longer has D-019's exact replay state")

    if hashlib.sha256(source).hexdigest() != expected_tracker_sha256:
        raise TransitionError("round-outcome predecessor digest does not match")
    try:
        predecessor = _parse_tracker_for_exact_reconciliation(source.decode("utf-8"))
    except (SchemaError, UnicodeError) as exc:
        raise TransitionError(f"round-outcome predecessor is malformed: {exc}") from exc
    if predecessor.run_id != _ACTIVE_ROUND_OUTCOME_RUN or predecessor.revision != expected_revision:
        raise TransitionError("round-outcome predecessor run or revision does not match")
    _validate_tracker_filesystem(run_dir, predecessor)

    with _exclusive_lock(run_dir, timeout_s=5.0):
        observed = (run_dir / "progress.md").read_bytes()
        if observed != source:
            raise TransitionError("tracker changed before round-outcome reconciliation acquired the lock")
        tracker = _parse_tracker_for_exact_reconciliation(observed.decode("utf-8"))
        _validate_tracker_filesystem(run_dir, tracker)
        _validate_active_round_outcome_decision(run_dir, tracker, decision_ref)
        gate = _gate_record(tracker, _ACTIVE_ROUND_OUTCOME_GATE)
        round_one = next(
            (item for item in tracker.remediation if item.gate == gate.id and item.round_number == 1),
            None,
        )
        round_two = next(
            (item for item in tracker.remediation if item.gate == gate.id and item.round_number == 2),
            None,
        )
        if (
            round_one is None
            or round_one.state != "complete"
            or _recorded_remaining_blockers(round_one) is not None
            or round_one.re_review == "-"
            or round_two is None
            or round_two.state != "re_reviewing"
            or set(_csv(round_two.findings)) != _ACTIVE_ROUND_OUTCOME_BLOCKERS
            or round_two.re_review != "-"
            or gate.state != "re_reviewing"
            or gate.head == "-"
        ):
            raise TransitionError("active remediation history does not match D-019's exact repair shape")
        recorded_report = _resolved_reference(run_dir, round_one.re_review).resolve()
        if recorded_report != report_path:
            raise TransitionError("D-019 report is not the Round 1 row's recorded re-review evidence")
        report = _parse_review_report(report_path, allow_sealed_historical=True)
        report_ids = set(_csv(report["findings"]))
        if (
            report["gate"] != gate.id
            or report["assignment"] not in _csv(gate.assignments)
            or report["head"] != gate.head
            or report["head"] not in _csv(round_one.commits)
            or report_ids != set(_csv(round_one.findings))
        ):
            raise TransitionError("Round 1 report does not match the recorded gate, code state, or findings")
        if _round_outcomes_from_notes(notes_path, report_ids) != _ACTIVE_ROUND_OUTCOME_BLOCKERS:
            raise TransitionError("Round 1 evidence does not prove D-019's exact blocker baseline")
        updated_round_one = replace(
            round_one,
            verification=_append_history(_append_history(round_one.verification, outcome), provenance),
        )
        proposed = replace(
            tracker,
            remediation=tuple(updated_round_one if item is round_one else item for item in tracker.remediation),
        )
        updated = _with_transition_identity(proposed, transition_id, tracker.revision + 1)
        canonical = render_tracker(updated)
        reparsed = parse_tracker(canonical)
        _replace_tracker(run_dir, canonical, transition_id)
        return reparsed


def _review_report_set(
    paths: tuple[Path, ...],
    *,
    gate: GateRecord,
    expected_base: str,
    allow_sealed_historical: bool = False,
    rereview: bool = False,
) -> tuple[tuple[dict[str, str], ...], str]:
    reports = tuple(
        _parse_review_report(path, allow_sealed_historical=allow_sealed_historical)
        for path in paths
    )
    expected_assignments = tuple(sorted(_csv(gate.assignments)))
    if tuple(sorted(report["assignment"] for report in reports)) != expected_assignments:
        raise TransitionError("required reviewer reports are missing, duplicated, or unexpected")
    heads = {report["head"] for report in reports}
    if (
        len(heads) != 1
        or any(report["gate"] != gate.id or report["base"] != expected_base for report in reports)
    ):
        raise TransitionError("review reports do not form the required gate/code-state edge")
    if not allow_sealed_historical:
        expected_gate_findings = set(_gate_finding_ids(gate))
        for report in reports:
            report_findings = set(_csv(report["findings"]))
            outcomes = _review_outcomes(report)
            if set(outcomes) != report_findings:
                raise TransitionError("review outcomes must map every reported finding exactly once")
            if rereview:
                if not expected_gate_findings.issubset(report_findings):
                    raise TransitionError("each re-review must conclude every existing gate finding")
            elif any(outcome != "Open" for outcome in outcomes.values()):
                raise TransitionError("initial review findings must be reported Open")
    return reports, next(iter(heads))


def _round_verification_items(row: RemediationRecord) -> tuple[str, ...]:
    items = _csv(row.verification)
    seals = tuple(item for item in items if item.startswith("master-initial-seal:"))
    if len(seals) > 1 or any(
        re.fullmatch(r"master-initial-seal:[0-9a-f]{64}", seal) is None
        for seal in seals
    ):
        raise TransitionError("master initial seal metadata is malformed or duplicated")
    return tuple(
        item for item in items
        if not item.startswith("remaining-blockers=")
        and not item.startswith("round-outcome-reconciliation=")
        and not item.startswith("extension-authority=")
        and not item.startswith("master-initial-seal:")
    )


def _validate_completed_round_edge(
    run_dir: Path,
    tracker: Tracker,
    gate: GateRecord,
    row: RemediationRecord,
    prior_head: str,
) -> tuple[tuple[dict[str, str], ...], str]:
    paths = tuple(_resolve_digest_bound_reference(run_dir, value) for value in _csv(row.re_review))
    if not paths:
        raise TransitionError("completed remediation round has no re-review evidence")
    reports, reviewed_head = _review_report_set(
        paths, gate=gate, expected_base=prior_head,
        allow_sealed_historical=True,
    )
    verification = _round_verification_items(row)
    scope = _remediation_scope(run_dir, row)
    all_artifact = bool(scope) and all(kind == "artifact" for kind, _ in scope.values())
    commits = _csv(row.commits)
    if all_artifact:
        if row.commits != "N/A" or reviewed_head != prior_head:
            raise TransitionError("completed artifact-only round has inconsistent no-commit provenance")
        commits = ()
    elif not commits or any(not _COMMIT.fullmatch(commit) for commit in commits):
        raise TransitionError("completed remediation round has malformed fix provenance")
    repo_dir = _project_root(run_dir)
    if (
        not _git(repo_dir, "merge-base", "--is-ancestor", prior_head, reviewed_head)
        or not _git(repo_dir, "merge-base", "--is-ancestor", reviewed_head, tracker.target_branch)
        or any(not _git(repo_dir, "merge-base", "--is-ancestor", commit, reviewed_head) for commit in commits)
    ):
        raise TransitionError("completed remediation round is not a contiguous integrated review edge")
    try:
        _validate_verification_evidence(run_dir, verification, reviewed_head)
    except TransitionError:
        provenance = tuple(
            item for item in _csv(row.verification)
            if item.startswith("round-outcome-reconciliation=D-019@")
        )
        if not (
            tracker.run_id == _ACTIVE_ROUND_OUTCOME_RUN
            and gate.id == _ACTIVE_ROUND_OUTCOME_GATE
            and row.round_number == _ACTIVE_ROUND_OUTCOME_ROUND
            and len(provenance) == 1
            and len(verification) == 1
            and verification[0].endswith("@" + reviewed_head)
        ):
            raise
    return reports, reviewed_head


def _validated_review_lineage(
    run_dir: Path,
    tracker: Tracker,
    gate: GateRecord,
    report_paths: tuple[Path, ...],
    active_round: RemediationRecord | None,
) -> tuple[tuple[dict[str, str], ...], tuple[dict[str, str], ...]]:
    resolved_input = tuple(Path(path).resolve() for path in report_paths)
    if active_round is None:
        initial_reports, initial_head = _review_report_set(
            resolved_input, gate=gate, expected_base=gate.base,
        )
        if initial_head != gate.head:
            raise TransitionError("initial reports do not match the gate's opened HEAD")
        return initial_reports, ()

    persisted_paths = tuple(
        _resolve_digest_bound_reference(run_dir, value) for value in _csv(gate.reports)
    )
    if not persisted_paths or resolved_input != persisted_paths:
        raise TransitionError("remediation evaluation must reuse the immutable initial report set")
    initial_reports, cursor = _review_report_set(
        persisted_paths, gate=gate, expected_base=gate.base,
        allow_sealed_historical=True,
    )
    historical: list[dict[str, str]] = []
    completed = sorted(
        (
            row for row in tracker.remediation
            if row.gate == gate.id
            and row.state == "complete"
            and row.round_number < active_round.round_number
        ),
        key=lambda row: row.round_number,
    )
    if tuple(row.round_number for row in completed) != tuple(range(1, active_round.round_number)):
        raise TransitionError("completed remediation rounds do not form a contiguous sequence")
    for row in completed:
        reports, cursor = _validate_completed_round_edge(
            run_dir, tracker, gate, row, cursor,
        )
        historical.extend(reports)
    if cursor != gate.head:
        raise TransitionError("persisted review lineage does not end at the gate's rolling HEAD")
    return initial_reports, tuple(historical)


def _gate_evaluation_request_digest(
    findings_path: Path,
    report_paths: tuple[Path, ...],
    rereview_paths: tuple[Path, ...],
    verification: tuple[str, ...],
) -> str:
    digest = hashlib.sha256()
    for label, paths in (("findings", (findings_path,)), ("report", report_paths), ("rereview", rereview_paths)):
        for path in paths:
            resolved = Path(path).resolve()
            try:
                content = resolved.read_bytes()
            except OSError as exc:
                raise TransitionError(f"gate evidence is unreadable: {resolved}: {exc}") from exc
            digest.update(label.encode())
            digest.update(b"\0")
            digest.update(str(resolved).encode())
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")
    for item in verification:
        digest.update(b"verification\0")
        digest.update(item.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _review_evidence_path(run_dir: Path, value: str) -> Path:
    if "#sha256=" in value:
        return _resolve_digest_bound_reference(run_dir, value)
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    candidates = tuple(
        candidate.resolve()
        for candidate in (Path(run_dir) / path, _project_root(run_dir) / path)
        if candidate.exists()
    )
    if len(set(candidates)) != 1:
        raise TransitionError(f"review evidence reference is missing or ambiguous: {value}")
    return candidates[0]


def _validate_rejection_evidence(run_dir: Path, finding_id: str, value: str) -> None:
    path = _review_evidence_path(run_dir, value)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"rejection evidence is unreadable: {path}: {exc}") from exc
    finding_fields = re.findall(r"(?im)^finding:\s*(\S+)\s*$", text)
    rationale_fields = re.findall(r"(?im)^rationale:\s*(\S.*)$", text)
    if finding_fields != [finding_id] or len(rationale_fields) != 1:
        raise TransitionError("rejection evidence must identify the finding and record a rationale")


def _validate_deferred_evidence(
    run_dir: Path,
    tracker: Tracker,
    finding_id: str,
    value: str,
) -> None:
    path = _resolve_digest_bound_reference(run_dir, value)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"deferred-disposition evidence is unreadable: {path}: {exc}") from exc
    fields = {
        name: re.findall(rf"(?im)^{name}:\s*(\S.*)$", text)
        for name in ("Finding", "Impact", "Reason", "Authority")
    }
    if (
        fields["Finding"] != [finding_id]
        or any(len(fields[name]) != 1 or fields[name][0] == "-" for name in ("Impact", "Reason"))
        or len(fields["Authority"]) != 1
        or re.fullmatch(r"D-[0-9]+", fields["Authority"][0]) is None
    ):
        raise TransitionError(
            "deferred-disposition evidence must identify one finding, impact, reason, and decision authority"
        )
    decision_ref = fields["Authority"][0]
    decisions_path = _resolved_reference(run_dir, dict(tracker.run_fields)["decisions"])
    try:
        sections = _decision_sections(decisions_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TransitionError) as exc:
        raise TransitionError(f"deferred-disposition authority is unreadable: {exc}") from exc
    lines = sections.get(decision_ref)
    if lines is None:
        raise TransitionError("deferred-disposition authority decision is missing")
    answers = _field_lines(lines, "Answer")
    statuses = _field_lines(lines, "Status")
    scopes = _field_lines(lines, "Scope")
    if len(answers) != 1 or len(statuses) != 1 or len(scopes) != 1:
        raise TransitionError("deferred-disposition authority is missing, duplicated, or ambiguous")
    _require_decision_action(lines, "review.resolve-question")
    answer = answers[0].strip().rstrip(".")
    if (
        statuses[0].strip().rstrip(".").casefold() != "resolved"
        or "defer" not in answer.casefold()
        or finding_id.casefold() not in answer.casefold()
        or not _scope_names_task(scopes[0], finding_id)
    ):
        raise TransitionError("decision does not explicitly authorize this finding's deferral")
    for other_ref, other_lines in sections.items():
        if other_ref == decision_ref:
            continue
        other_status = _field_lines(other_lines, "Status")
        other_scopes = _field_lines(other_lines, "Scope")
        if (
            len(other_status) == 1
            and other_status[0].strip().rstrip(".").casefold() in {"open", "pending", "blocked"}
            and any(_scope_names_task(scope, finding_id) for scope in other_scopes)
        ):
            raise TransitionError(f"unresolved decision {other_ref} conflicts with deferral authority")


_ARTIFACT_REMEDIATION_MARKER = "<!-- pipeline-artifact-remediation/v2 -->"
_ARTIFACT_REMEDIATION_FIELDS = (
    "finding", "gate", "round", "fix_plan", "artifacts", "verification",
)
_REMEDIATION_SCOPE_MARKER = "<!-- pipeline-remediation-scope/v2 -->"
_REMEDIATION_SCOPE_HEADER = ("Finding", "Kind", "Artifacts")


def _remediation_scope(
    run_dir: Path,
    row: RemediationRecord,
    *,
    required: bool = False,
) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Parse the optional narrow machine authority from an immutable fix plan."""
    plan = _resolve_digest_bound_reference(run_dir, row.fix_plan)
    try:
        lines = plan.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"remediation fix plan is unreadable: {plan}: {exc}") from exc
    positions = [index for index, line in enumerate(lines) if line == _REMEDIATION_SCOPE_MARKER]
    if not positions:
        if required:
            raise TransitionError("artifact-only remediation needs machine-readable fix-plan authority")
        return {}
    if len(positions) != 1:
        raise TransitionError("remediation fix plan needs at most one scope authority")
    table_lines: list[str] = []
    for line in lines[positions[0] + 1:]:
        if not line.startswith("|"):
            break
        table_lines.append(line)
    rows = _table(table_lines, _REMEDIATION_SCOPE_HEADER, TransitionError)
    finding_ids = tuple(item[0] for item in rows)
    if finding_ids != _csv(row.findings) or len(finding_ids) != len(set(finding_ids)):
        raise TransitionError("remediation scope must exactly match the targeted finding order")
    scope: dict[str, tuple[str, tuple[str, ...]]] = {}
    for finding_id, kind, raw_artifacts in rows:
        if kind == "source":
            if raw_artifacts != "none":
                raise TransitionError("source remediation scope must declare artifacts as none")
            artifacts: tuple[str, ...] = ()
        elif kind == "artifact":
            try:
                parsed = json.loads(raw_artifacts)
            except json.JSONDecodeError as exc:
                raise TransitionError("artifact remediation scope must use a JSON string array") from exc
            if (
                not isinstance(parsed, list)
                or not parsed
                or any(not isinstance(item, str) for item in parsed)
                or len(parsed) != len(set(parsed))
            ):
                raise TransitionError("artifact remediation scope needs unique nonempty paths")
            try:
                artifacts = tuple(_safe_relative(item).as_posix() for item in parsed)
            except PlanMetadataError as exc:
                raise TransitionError(str(exc)) from exc
        else:
            raise TransitionError("remediation scope kind must be source or artifact")
        scope[finding_id] = (kind, artifacts)
    return scope


def _validate_artifact_remediation_evidence(
    run_dir: Path,
    tracker: Tracker,
    gate: GateRecord,
    remediation: RemediationRecord,
    finding_id: str,
    value: str,
    re_review: str,
    rereview_paths: tuple[Path, ...],
    verification: tuple[str, ...],
) -> None:
    """Validate an explicitly artifact-only fix without inventing a commit."""
    if finding_id not in _csv(remediation.findings):
        raise TransitionError("artifact-only fix is not targeted by the active remediation round")
    scope = _remediation_scope(run_dir, remediation, required=True)
    kind, approved_artifacts = scope[finding_id]
    if kind != "artifact":
        raise TransitionError("approved remediation scope classifies this finding as source")
    path = _resolve_digest_bound_reference(run_dir, value)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"artifact-remediation evidence is unreadable: {path}: {exc}") from exc
    if not lines or lines[0] != _ARTIFACT_REMEDIATION_MARKER:
        raise TransitionError("artifact-remediation evidence marker is missing")
    values = dict(
        _key_values(lines[1:], _ARTIFACT_REMEDIATION_FIELDS, TransitionError)
    )
    if (
        values["finding"] != finding_id
        or values["gate"] != gate.id
        or values["round"] != str(remediation.round_number)
        or values["fix_plan"] != remediation.fix_plan
    ):
        raise TransitionError("artifact-remediation evidence does not match the approved round")
    try:
        artifacts = json.loads(values["artifacts"])
    except json.JSONDecodeError as exc:
        raise TransitionError("artifact-remediation artifacts must be a JSON string array") from exc
    if (
        not isinstance(artifacts, list)
        or not artifacts
        or any(not isinstance(item, str) for item in artifacts)
        or len(artifacts) != len(set(artifacts))
    ):
        raise TransitionError("artifact-remediation artifacts must be unique digest-bound identities")
    artifact_paths = tuple(item.rpartition("#sha256=")[0] for item in artifacts)
    if artifact_paths != approved_artifacts:
        raise TransitionError("artifact-remediation evidence does not match approved artifact paths")
    for artifact in artifacts:
        _resolve_digest_bound_reference(run_dir, artifact)
    if len(verification) != 1 or values["verification"] != verification[0]:
        raise TransitionError("artifact-remediation evidence does not match recorded verification")
    expected_rereview = _review_evidence_path(run_dir, re_review)
    supplied_rereviews = {Path(item).resolve() for item in rereview_paths}
    if expected_rereview not in supplied_rereviews:
        raise TransitionError("artifact-only fix lacks its applicable re-review")


def _validate_artifact_remediation_disposition(
    run_dir: Path,
    tracker: Tracker,
    gate: GateRecord,
    active_round: RemediationRecord | None,
    finding_id: str,
    evidence: str,
    re_review: str,
    rereview_paths: tuple[Path, ...],
    verification: tuple[str, ...],
) -> None:
    matches = 0
    for remediation in tracker.remediation:
        if (
            remediation.gate != gate.id
            or finding_id not in _csv(remediation.findings)
            or remediation.state not in {"re_reviewing", "complete"}
        ):
            continue
        if remediation is active_round:
            candidate_rereviews = rereview_paths
            candidate_verification = verification
        else:
            candidate_rereviews = tuple(
                _resolve_digest_bound_reference(run_dir, item)
                for item in _csv(remediation.re_review)
            )
            candidate_verification = _round_verification_items(remediation)
        try:
            _validate_artifact_remediation_evidence(
                run_dir, tracker, gate, remediation, finding_id, evidence,
                re_review, candidate_rereviews, candidate_verification,
            )
        except TransitionError:
            continue
        matches += 1
    if matches != 1:
        raise TransitionError(
            "artifact-only finding is not bound to exactly one targeted remediation round and re-review"
        )


def _blocking_remediation_progress(
    rows: tuple[tuple[str, ...], ...],
    targeted: set[str],
    open_blockers: set[str],
) -> bool:
    blocking_targets = {
        row[0] for row in rows
        if row[0] in targeted and row[2] in {"Critical", "Important"}
    }
    return bool(blocking_targets - open_blockers)


def evaluate_and_close_review_gate(
    run_dir: Path,
    *,
    gate_id: str,
    findings_path: Path,
    report_paths: tuple[Path, ...],
    verification: tuple[str, ...],
    rereview_paths: tuple[Path, ...],
) -> Tracker:
    if not report_paths or not verification:
        raise TransitionError("gate evaluation needs all reports and code-state verification")
    request_digest = _gate_evaluation_request_digest(
        Path(findings_path), report_paths, rereview_paths, verification,
    )
    transition_id = f"evaluate-gate-{gate_id}-{request_digest}"

    def transition(tracker: Tracker) -> Tracker:
        if _gate_evaluation_request_digest(
            Path(findings_path), report_paths, rereview_paths, verification,
        ) != request_digest:
            raise TransitionError("gate evidence changed while evaluation was being reserved")
        if tracker.last_transition == transition_id:
            raise _AlreadyApplied(tracker)
        gate = _gate_record(tracker, gate_id)
        if gate.state not in {"in_progress", "re_reviewing"}:
            raise TransitionError("gate is not open for evaluation")
        authoritative_findings = _resolved_reference(
            Path(run_dir), dict(tracker.run_fields)["findings"]
        ).resolve()
        if Path(findings_path).resolve() != authoritative_findings:
            raise TransitionError("findings ledger is not the run's authoritative findings artifact")
        active_round = next(
            (row for row in tracker.remediation if row.gate == gate.id and row.state == "re_reviewing"),
            None,
        )
        if active_round is not None:
            _remediation_scope(Path(run_dir), active_round)
        reports, historical_reports = _validated_review_lineage(
            Path(run_dir), tracker, gate, report_paths, active_round,
        )
        reviewed_head = gate.head
        repo_dir = _project_root(Path(run_dir))
        rereviews: tuple[dict[str, str], ...] = ()
        if active_round is not None:
            if not rereviews:
                if not rereview_paths:
                    raise TransitionError("an active remediation round requires re-review evidence")
            rereviews, reviewed_head = _review_report_set(
                tuple(Path(path).resolve() for path in rereview_paths),
                gate=gate,
                expected_base=gate.head,
                rereview=True,
            )
            if not _git(repo_dir, "merge-base", "--is-ancestor", gate.head, reviewed_head) or not _git(repo_dir, "merge-base", "--is-ancestor", reviewed_head, tracker.target_branch):
                raise TransitionError("re-review code state is not integrated after the prior gate HEAD")
        if gate.type in {"phase", "master"} and not _is_target_tip(
            repo_dir, tracker.target_branch, reviewed_head
        ):
            raise TransitionError(
                f"{gate.type} review HEAD is no longer the designated target branch tip"
            )
        if active_round is not None:
            _validate_verification_evidence(
                Path(run_dir), verification, reviewed_head,
                purpose="remediation", run_id=tracker.run_id,
                subject=f"gate/{gate.id}", attempt=f"round-{active_round.round_number}",
            )
        else:
            subject_phase = gate.phase
            if gate.type == "master":
                candidates = [
                    item for item in tracker.phases
                    if item.state == "[x]" and _phase_verification_head(item) == reviewed_head
                ]
                if not candidates:
                    raise TransitionError("master gate has no recorded phase verification for its reviewed HEAD")
                subject_phase = candidates[-1].id
            _validate_verification_evidence(
                Path(run_dir), verification, reviewed_head,
                purpose="phase", run_id=tracker.run_id,
                subject=f"phase/{subject_phase}", attempt="N/A",
            )
        if active_round is not None:
            recorded_verification = _round_verification_items(active_round)
        else:
            if gate.type == "phase":
                phase = next(item for item in tracker.phases if item.id == gate.phase)
            else:
                candidates = [
                    item
                    for item in tracker.phases
                    if item.state == "[x]" and _phase_verification_head(item) == reviewed_head
                ]
                if not candidates:
                    raise TransitionError("master gate has no recorded phase verification for its reviewed HEAD")
                phase = candidates[-1]
            recorded_verification = _phase_verification_evidence(phase)
        if set(verification) != set(recorded_verification):
            raise TransitionError("gate verification does not match the authoritative recorded verification")
        rows = tuple(row for row in _parse_findings(authoritative_findings) if row[1] == gate.id)
        row_ids = {row[0] for row in rows}
        if active_round is not None:
            prior_finding_ids = set(_gate_finding_ids(gate))
            _validate_sealed_gate_evidence(
                Path(run_dir), tracker, gate, authoritative_findings,
                finding_ids=prior_finding_ids,
            )
            reported_rereview_ids = {
                finding_id
                for report in rereviews
                for finding_id in _csv(report["findings"])
            }
            new_finding_ids = reported_rereview_ids - prior_finding_ids
            if row_ids != prior_finding_ids | new_finding_ids:
                raise TransitionError("findings ledger does not match prior and newly introduced findings")
            parsed_outcomes = tuple(_review_outcomes(report) for report in rereviews)
            outcome_sets = {
                finding_id: {
                    report_outcomes[finding_id]
                    for report_outcomes in parsed_outcomes
                    if finding_id in report_outcomes
                }
                for finding_id in row_ids
            }
            if any(not outcomes or len(outcomes) != 1 for outcomes in outcome_sets.values()):
                raise TransitionError("reviewer outcome conflict requires explicit consolidation")
            ledger_status = {row[0]: row[3] for row in rows}
            if any(next(iter(outcomes)) != ledger_status[finding_id] for finding_id, outcomes in outcome_sets.items()):
                raise TransitionError("re-review outcomes and authoritative finding status disagree")
            if any(ledger_status[finding_id] != "Open" for finding_id in new_finding_ids):
                raise TransitionError("a newly introduced re-review finding must remain Open")
        report_ids = {
            finding
            for report in (*reports, *historical_reports, *rereviews)
            for finding in _csv(report["findings"])
        }
        if row_ids != report_ids:
            raise TransitionError("review reports and findings ledger disagree")
        invalid_rows: list[tuple[str, ...]] = []
        blockers: list[tuple[str, ...]] = []
        authorized_minor_fixes: list[tuple[str, ...]] = []
        for row in rows:
            _, _, severity, status, disposition, evidence, fix_commit, re_review = row
            if severity not in {"Critical", "Important", "Minor"} or status not in {"Open", "Resolved"}:
                invalid_rows.append(row)
                continue
            if severity in {"Critical", "Important"}:
                if status == "Open":
                    blockers.append(row)
                    if disposition != "-" or fix_commit != "-" or re_review != "-":
                        invalid_rows.append(row)
                elif disposition == "Fixed":
                    if evidence == "-" or re_review == "-":
                        invalid_rows.append(row)
                    elif fix_commit == "-":
                        _validate_artifact_remediation_disposition(
                            Path(run_dir), tracker, gate, active_round, row[0], evidence,
                            re_review, rereview_paths, verification,
                        )
                elif disposition == "Rejected":
                    if evidence == "-" or fix_commit != "-":
                        invalid_rows.append(row)
                    else:
                        _validate_rejection_evidence(Path(run_dir), row[0], evidence)
                else:
                    invalid_rows.append(row)
            else:
                if status == "Open":
                    if disposition != "-" or fix_commit != "-" or re_review != "-" or not re.fullmatch(r"D-[0-9]+", evidence):
                        invalid_rows.append(row)
                    else:
                        try:
                            answer = _resolved_decision_for_terms(
                                Path(run_dir), tracker, evidence, {gate.id, row[0]},
                            )
                        except TransitionError:
                            invalid_rows.append(row)
                        else:
                            if "fix" not in answer.casefold():
                                invalid_rows.append(row)
                            else:
                                authorized_minor_fixes.append(row)
                    continue
                if disposition not in {"Fixed", "Deferred", "Rejected"} or evidence == "-":
                    invalid_rows.append(row)
                if disposition == "Fixed":
                    if re_review == "-":
                        invalid_rows.append(row)
                    elif fix_commit == "-":
                        _validate_artifact_remediation_disposition(
                            Path(run_dir), tracker, gate, active_round, row[0], evidence,
                            re_review, rereview_paths, verification,
                        )
                if disposition in {"Deferred", "Rejected"} and fix_commit != "-":
                    invalid_rows.append(row)
                if disposition == "Rejected" and evidence != "-":
                    _validate_rejection_evidence(Path(run_dir), row[0], evidence)
                if disposition == "Deferred" and evidence != "-":
                    _validate_deferred_evidence(Path(run_dir), tracker, row[0], evidence)
        for finding in (row for row in rows if row[4] == "Fixed" and row[6] != "-"):
            finding_id, _, _, _, _, _, fix_commit, re_review = finding
            if not _COMMIT.fullmatch(fix_commit) or not _git(
                repo_dir, "merge-base", "--is-ancestor", fix_commit, reviewed_head
            ):
                raise TransitionError("review fix commit is invalid or absent from the reviewed HEAD")
            expected_rereview = _review_evidence_path(Path(run_dir), re_review)
            matching_rounds: list[RemediationRecord] = []
            for remediation in tracker.remediation:
                if (
                    remediation.gate != gate.id
                    or finding_id not in _csv(remediation.findings)
                    or fix_commit not in _csv(remediation.commits)
                ):
                    continue
                if remediation is not active_round and finding_id in (_recorded_remaining_blockers(remediation) or set()):
                    continue
                paths = (
                    tuple(Path(path).resolve() for path in rereview_paths)
                    if remediation is active_round
                    else tuple(_resolve_digest_bound_reference(Path(run_dir), value) for value in _csv(remediation.re_review))
                )
                if expected_rereview in paths:
                    matching_rounds.append(remediation)
            if len(matching_rounds) != 1:
                raise TransitionError("fixed finding is not bound to exactly one targeted remediation round and re-review")
        if invalid_rows:
            raise TransitionError("finding status, severity, disposition, or evidence is invalid")
        questions = gate.questions
        remediation_rows = list(tracker.remediation)
        if active_round is not None:
            targeted = set(active_round.findings.split(","))
            open_blocker_ids = {row[0] for row in blockers}
            progress = _blocking_remediation_progress(rows, targeted, open_blocker_ids)
            previous = next(
                (
                    row
                    for row in tracker.remediation
                    if row.gate == gate.id
                    and row.round_number == active_round.round_number - 1
                    and row.state == "complete"
                ),
                None,
            )
            previous_remaining = _recorded_remaining_blockers(previous)
            prior_targets = {
                finding
                for remediation in tracker.remediation
                if remediation.gate == gate.id and remediation.round_number < active_round.round_number
                for finding in _csv(remediation.findings)
            }
            oscillating = bool(
                previous is not None
                and previous_remaining is not None
                and (open_blocker_ids & prior_targets) - previous_remaining
            )
            if blockers and oscillating:
                questions = f"remediation-oscillation-round-{active_round.round_number}"
            elif blockers and not progress:
                questions = f"remediation-no-progress-round-{active_round.round_number}"
            else:
                ceiling = active_round.round_number if any(
                    item.startswith("extension-authority=") for item in _csv(active_round.verification)
                ) else 3
                if blockers and active_round.round_number == ceiling:
                    questions = f"remediation-limit-reached-round-{ceiling}"
            completed_round = replace(
                active_round,
                state="complete",
                verification=_append_history(
                    active_round.verification,
                    "remaining-blockers=" + ("+".join(sorted(open_blocker_ids)) or "none"),
                ),
                re_review=",".join(
                    _digest_bound_reference(Path(run_dir), Path(path))
                    for path in rereview_paths
                ),
            )
            remediation_rows[remediation_rows.index(active_round)] = completed_round
        state = "blocked" if blockers or authorized_minor_fixes or questions != "-" else "accepted"
        if active_round is None:
            report_identities, finding_origins = _sealed_review_package(
                Path(run_dir), gate, report_paths, rows,
            )
            persisted_reports = ",".join(report_identities)
            persisted_findings = ",".join(finding_origins) or "-"
        else:
            persisted_reports = gate.reports
            prior_origins = {
                parsed[0]: value
                for value in _csv(gate.findings)
                if (parsed := _parse_finding_origin(value)) is not None
            }
            rereview_identities = tuple(
                _digest_bound_reference(Path(run_dir), Path(path))
                for path in rereview_paths
            )
            for row in rows:
                if row[0] in new_finding_ids:
                    prior_origins[row[0]] = _finding_origin_identity(
                        row, rereview_identities, rereviews,
                    )
            persisted_findings = ",".join(
                prior_origins[finding_id] for finding_id in sorted(prior_origins)
            ) or "-"
        replacement = replace(
            gate,
            state=state,
            head=reviewed_head,
            reports=persisted_reports,
            verification=",".join(verification),
            findings=persisted_findings,
            questions=questions,
        )
        return replace(_replace_gate(tracker, replacement), remediation=tuple(remediation_rows))

    try:
        return locked_tracker_update(
            Path(run_dir), transition_id, transition, timeout_s=5.0,
            replay_returns_current=False, refresh_next_action=True,
        )
    except _AlreadyApplied as applied:
        return applied.tracker


def reconcile_run(
    run_dir: Path,
    *,
    phase_plan: Path,
    repo_dir: Path,
) -> ReconciliationReport:
    """Rebuild the next recovery action from authoritative files and Git evidence."""
    run_dir = Path(run_dir)
    repo_dir = Path(repo_dir)
    tracker = validate_run(run_dir)
    actions: list[str] = []
    questions: list[str] = []
    diagnostics: list[str] = []

    approved_plan_paths = {
        _resolved_reference(run_dir, value).resolve()
        for value in dict(tracker.run_fields)["phase_plans"].split(",")
    }
    if Path(phase_plan).resolve() not in approved_plan_paths:
        raise TransitionError("reconciliation phase plan is not approved for this run")
    parse_phase_plan(phase_plan)

    run_fields = dict(tracker.run_fields)
    for field in ("spec", "master_plan", "decisions", "findings"):
        path = _resolved_reference(run_dir, run_fields[field])
        try:
            path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            questions.append(f"unreadable-authoritative-artifact:{field}:{path}:{exc}")

    parsed_results: list[tuple[Path, WorkerResult]] = []
    output_dir = run_dir / "agent-output"
    if output_dir.is_dir():
        for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                diagnostics.append(f"unreadable-result-candidate:{path}:{exc}")
                continue
            if not content.startswith(_RESULT_MARKER):
                continue
            try:
                parsed_results.append((path, parse_worker_result(content)))
            except SchemaError as exc:
                diagnostics.append(f"partial-or-malformed-result:{path}:{exc}")

    for task in tracker.tasks:
        if task.state != "[~]":
            continue
        matches = [
            (path, result)
            for path, result in parsed_results
            if result.run_id == tracker.run_id and result.task_id == task.id and result.attempt == task.attempt
        ]
        if len(matches) > 1:
            questions.append(f"conflicting-results:{task.id}:{task.attempt}")
            continue
        if len(matches) == 1:
            path, result = matches[0]
            if result.owner != task.owner:
                questions.append(f"result-owner-contradiction:{task.id}:{task.attempt}:{path}")
                continue
            try:
                import_worker_result(run_dir, result_path=path, phase_plan=phase_plan, repo_dir=repo_dir)
            except (EvidenceError, SchemaError, TransitionError) as exc:
                questions.append(f"result-evidence-contradiction:{task.id}:{task.attempt}:{exc}")
            else:
                actions.append(f"imported:{task.id}:{task.attempt}")
            continue
        stale = [
            path for path, result in parsed_results
            if result.run_id == tracker.run_id and result.task_id == task.id
        ]
        if stale:
            questions.append(f"superseded-or-conflicting-result:{task.id}:{task.attempt}:{','.join(str(path) for path in stale)}")
        actions.append(f"await-or-check-live-owner:{task.id}:{task.attempt}:{task.owner}")

    tracker = validate_run(run_dir)
    for task in tracker.tasks:
        if task.state == "[x]" and task.kind == "source":
            if task.integration == "-":
                actions.append(f"integration-pending:{task.id}")
            elif not _dependency_ready(run_dir, tracker, task):
                questions.append(f"integration-contradiction:{task.id}")
        elif task.state == "[x]" and task.kind == "artifact" and not _dependency_ready(run_dir, tracker, task):
            questions.append(f"artifact-evidence-contradiction:{task.id}")
        elif task.state == "[?]":
            actions.append(f"await-user-decision:{task.id}:{task.question}")
    for row in tracker.remediation:
        if row.state in {"fixing", "re_reviewing"}:
            try:
                _remediation_scope(run_dir, row)
            except TransitionError as exc:
                questions.append(
                    f"fix-plan-contradiction:{row.gate}:{row.round_number}:{exc}"
                )
            else:
                actions.append(f"resume-remediation:{row.gate}:{row.round_number}")

    return ReconciliationReport(tuple(actions), tuple(questions), tuple(diagnostics))


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline_state.py")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("run_dir", type=Path)
    next_command = commands.add_parser("next")
    next_command.add_argument("run_dir", type=Path)
    next_command.add_argument("--phase-plan", type=Path, required=True)
    next_command.add_argument("--capacity", type=int)
    init = commands.add_parser("init")
    init.add_argument("run_dir", type=Path)
    init.add_argument("--run-id", required=True)
    init.add_argument("--base-commit", required=True)
    init.add_argument("--target-branch", required=True)
    init.add_argument("--worker-limit", required=True, type=int)
    init.add_argument("--spec", required=True)
    init.add_argument("--master-plan", required=True)
    init.add_argument("--phase-plans", required=True)
    init.add_argument("--decisions", required=True)
    init.add_argument("--findings", required=True)
    init.add_argument("--approved-existing", action="append", default=[], type=Path)
    init.add_argument("--filesystem-acknowledgement")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        if args.command == "validate":
            validate_run(args.run_dir)
            print("valid pipeline-run/v2")
            return 0
        if args.command == "inspect":
            print(json.dumps(inspect_run(args.run_dir), sort_keys=True))
            return 0
        if args.command == "next":
            ready = next_eligible_actions(args.run_dir, args.phase_plan, capacity=args.capacity)
            print(json.dumps({"eligible": [task.id for task in ready]}, sort_keys=True))
            return 0
        artifacts = {
            "spec": args.spec,
            "master_plan": args.master_plan,
            "phase_plans": args.phase_plans,
            "decisions": args.decisions,
            "findings": args.findings,
        }
        initialize_run(
            args.run_dir,
            run_id=args.run_id,
            base_commit=args.base_commit,
            target_branch=args.target_branch,
            worker_limit=args.worker_limit,
            artifacts=artifacts,
            approved_existing=tuple(args.approved_existing),
            filesystem_acknowledgement=args.filesystem_acknowledgement,
        )
        print(f"initialized {args.run_dir}")
        return 0
    except (
        SchemaError, PlanMetadataError, TransitionError, FilesystemSuitabilityError,
        LockBusyError, LockUnavailableError, TrackerWriteError, UpdateOutcomeUncertain,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
