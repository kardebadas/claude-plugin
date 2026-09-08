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


@dataclass(frozen=True)
class PhaseMetadata:
    id: str
    deps: tuple[str, ...]
    review_gate: str
    review_reason: str


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


def parse_tracker(text: str) -> Tracker:
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


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in path.parts) or any(character in value for character in "*?[]{}"):
        raise PlanMetadataError(f"unsupported repository-relative path: {value!r}")
    return path


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
    metadata = PhaseMetadata(phase.group(1), phase_deps, phase.group(3), phase.group(4))
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
        tasks.append(PlannedTask(task_id, deps, kind, batch, order, scopes, outputs))
    if not tasks:
        raise PlanMetadataError("phase plan contains no tasks")
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        raise PlanMetadataError("duplicate task id")
    known = set(ids)
    if any(dependency not in known or dependency == task.id for task in tasks for dependency in task.deps):
        raise PlanMetadataError("unknown or self dependency")
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
    completed = subprocess.run(
        ("/usr/bin/stat", "-f", "%T", str(resolved)),
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise FilesystemSuitabilityError(f"macOS filesystem probe failed: {completed.stderr.strip()}")
    fs_type = completed.stdout.strip().casefold()
    return fs_type, _filesystem_fingerprint("darwin", os.stat(resolved).st_dev, fs_type)


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
    statuses = _field_lines(lines, "Status")
    scopes = _field_lines(lines, "Scope")
    if len(answers) != 1 or len(statuses) != 1 or len(scopes) != 1:
        raise FilesystemSuitabilityError("filesystem decision evidence is missing, duplicated, or conflicting")
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
        or not any(term in answer.casefold() for term in ("authorize", "allow", "approve", "use"))
    ):
        raise FilesystemSuitabilityError("filesystem decision is unrelated to this run, type, or fingerprint")
    for other_ref, other_lines in sections.items():
        if other_ref == decision_ref:
            continue
        other_status = _field_lines(other_lines, "Status")
        other_scope = " ".join(_field_lines(other_lines, "Scope")).casefold()
        if (
            len(other_status) == 1
            and other_status[0].strip().rstrip(".").casefold() in {"open", "pending", "blocked"}
            and run_id.casefold() in other_scope
            and info.fingerprint.casefold() in other_scope
        ):
            raise FilesystemSuitabilityError(f"unresolved decision {other_ref} still conflicts with filesystem authority")
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
    """Create, never replace, the first tracker; P1-03 adds atomic updates."""
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()


def _initial_tracker(
    *,
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
    phase_paths = tuple(Path(item) for item in artifacts["phase_plans"].split(","))
    if not phase_paths:
        raise SchemaError("at least one phase plan is required")
    phase_documents = tuple(_parse_phase_document(path) for path in phase_paths)
    phase_ids = [metadata.id for metadata, _ in phase_documents]
    if len(phase_ids) != len(set(phase_ids)):
        raise SchemaError("phase IDs must be unique")
    known_phases = set(phase_ids)
    if any(dep not in known_phases for metadata, _ in phase_documents for dep in metadata.deps):
        raise SchemaError("phase dependency is unknown")
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
    tracker = _initial_tracker(
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
    try:
        _write_initial_tracker(progress, text)
    except OSError as exc:
        raise SchemaError(_diagnostic(run_dir, f"could not create progress.md ({exc})")) from exc
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
    answers = _field_lines(lines, "Answer")
    statuses = _field_lines(lines, "Status")
    scopes = _field_lines(lines, "Scope") + _field_lines(lines, "Affected task")
    if len(answers) != 1 or len(statuses) != 1 or len(scopes) != 1:
        raise TransitionError("decision evidence is missing, duplicated, or conflicting")
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
        if (
            len(other_statuses) == 1
            and other_statuses[0].strip().rstrip(".").casefold() in {"open", "pending", "blocked"}
            and any(_scope_names_task(scope, task.id) for scope in other_scopes)
        ):
            raise TransitionError(f"unresolved decision {other_ref} still blocks {task.id}")


def _validate_start_guards(run_dir: Path, tracker: Tracker, task_id: str) -> PlannedTask:
    current_phase = dict(tracker.current_fields)["phase"]
    _, current_tasks = _phase_document_for(tracker, run_dir, current_phase)
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
        return task.integration == "N/A" and task.artifacts != "-"
    if task.integration in {"-", "N/A"} or task.commits == "-":
        return False
    repo_dir = _project_root(run_dir)
    return task.integration in task.verification and all(
        _git(repo_dir, "merge-base", "--is-ancestor", commit, task.integration)
        for commit in task.commits.split(",")
    ) and _git(repo_dir, "merge-base", "--is-ancestor", task.integration, tracker.target_branch)


def _active_worker_ids(tracker: Tracker) -> set[str]:
    workers = {task.owner for task in tracker.tasks if task.state == "[~]" and task.owner != "-"}
    for gate in tracker.gates:
        if gate.state in {"in_progress", "re_reviewing"}:
            workers.update(_csv(gate.assignments))
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
        return "final-verification" if gate.type == "master" else f"advance-phase-{gate.phase}"
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
        return _gate_next_action(tracker, _gate_record(tracker, f"phase-{phase_id}"))

    phase_ids = [document[1].id for document in documents]
    if phase_ids[-1] != phase_id:
        return f"advance-phase-{phase_id}"
    return _gate_next_action(tracker, _gate_record(tracker, "master"))


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
        tracker, planned, available = _scheduler_context(Path(run_dir), Path(phase_plan), capacity)
        if tracker != current:
            raise TransitionError("tracker changed while the reservation lock was held")
        _validate_worker_capacity(tracker, owners, capacity)
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
            updated = _replace_task(
                updated,
                replace(
                    record,
                    state="[~]",
                    owner=owner,
                    attempt=attempt,
                    checkpoints=_append_history(record.checkpoints, f"started:{attempt}"),
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
        _validate_start_guards(Path(run_dir), tracker, task_id)
        _validate_worker_capacity(
            tracker,
            (owner,),
            _detected_runtime_capacity(Path(run_dir), tracker),
        )
        if any(attempt in value for value in (task.attempt, task.checkpoints, task.result)):
            raise TransitionError("task attempt has already been used")
        return _replace_task(
            tracker,
            replace(task, state="[~]", owner=owner, attempt=attempt, checkpoints=_append_history(task.checkpoints, f"started:{attempt}")),
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
        _validate_start_guards(Path(run_dir), tracker, task_id)
        _validate_worker_capacity(
            tracker,
            (new_owner,),
            _detected_runtime_capacity(Path(run_dir), tracker),
        )
        return _replace_task(
            tracker,
            replace(
                task,
                state="[~]",
                owner=new_owner,
                attempt=new_attempt,
                checkpoints=_append_history(task.checkpoints, marker),
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
            if not _git(repo_dir, "rev-parse", "--verify", source_ref):
                raise TransitionError("source ref does not exist")
            for commit in commits:
                if not _COMMIT.fullmatch(commit) or not _git(repo_dir, "cat-file", "-e", f"{commit}^{{commit}}") or not _git(repo_dir, "merge-base", "--is-ancestor", commit, source_ref):
                    raise TransitionError("implementation commit is invalid or absent from source ref")
            replacement = replace(
                task,
                state="[x]",
                result=_append_history(task.result, f"result:{attempt}"),
                checkpoints=_append_history(task.checkpoints, f"completed:{attempt}"),
                source_ref=source_ref,
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
    if not any(integration_commit in item for item in verification):
        raise TransitionError("integration verification must identify the integration commit")

    def transition(tracker: Tracker) -> Tracker:
        task = _task_record(tracker, task_id)
        if task.kind != "source" or task.state != "[x]" or task.commits == "-":
            raise TransitionError("only a completed source task can be integrated")
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
        for evidence_path in result.evidence:
            try:
                safe_evidence = _safe_relative(evidence_path)
            except PlanMetadataError as exc:
                raise EvidenceError(f"worker evidence path is unsafe: {evidence_path}") from exc
            if not (Path(run_dir) / safe_evidence).is_file():
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
                if not _git(repo_dir, "rev-parse", "--verify", result.source_ref):
                    raise EvidenceError("worker source ref does not exist")
                if any(
                    not _git(repo_dir, "cat-file", "-e", f"{commit}^{{commit}}")
                    or not _git(repo_dir, "merge-base", "--is-ancestor", commit, result.source_ref)
                    for commit in result.commits
                ):
                    raise EvidenceError("worker commit is invalid or absent from its source ref")
                replacement = replace(
                    task,
                    state="[x]",
                    result=result_history,
                    checkpoints=_append_history(checkpoints, f"completed:{result.attempt}"),
                    source_ref=result.source_ref,
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
                replacement = replace(
                    task,
                    state="[x]",
                    result=result_history,
                    checkpoints=_append_history(checkpoints, f"completed:{result.attempt}"),
                    source_ref="-",
                    commits="-",
                    artifacts=",".join(actual),
                    integration="N/A",
                    verification=verification,
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
        _validate_verification_evidence(Path(run_dir), evidence, head)
        metadata, planned = _phase_document_for(tracker, Path(run_dir), phase_id)
        matches = [phase for phase in tracker.phases if phase.id == phase_id]
        if len(matches) != 1:
            raise TransitionError(f"unknown phase {phase_id}")
        phase = matches[0]
        if phase.review_gate != metadata.review_gate or phase.review_reason != metadata.review_reason:
            raise TransitionError("phase review classification or reason conflicts with approved metadata")
        records = {task.id: task for task in tracker.tasks}
        if any(not _dependency_ready(Path(run_dir), tracker, records[item.id]) for item in planned):
            raise TransitionError("every phase task must be verified and truthfully integrated")
        repo_dir = _project_root(Path(run_dir))
        if not _git(repo_dir, "cat-file", "-e", f"{head}^{{commit}}") or not _git(repo_dir, "merge-base", "--is-ancestor", head, tracker.target_branch):
            raise TransitionError("phase verification HEAD is not on the target branch")
        if any(
            records[item.id].kind == "source"
            and not _git(repo_dir, "merge-base", "--is-ancestor", records[item.id].integration, head)
            for item in planned
        ):
            raise TransitionError("phase verification HEAD does not contain every source integration")
        verification = f"head:{head};commands:{','.join(commands)};evidence:{','.join(evidence)}"
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
    documents = _phase_documents(run_dir, tracker)
    master_path = _resolved_reference(run_dir, dict(tracker.run_fields)["master_plan"])
    try:
        master = master_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"approved master plan is unreadable: {master_path}: {exc}") from exc
    missing = [raw_path for raw_path, _, _ in documents if raw_path not in master]
    if missing:
        raise TransitionError(
            "approved master plan does not reference every phase plan: " + ",".join(missing)
        )
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
            if gate.head == "-" or not _git(repo_dir, "merge-base", "--is-ancestor", verification_head, gate.head):
                raise TransitionError("required phase review does not cover the verified phase state")

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
            _, planned = _phase_document_for(tracker, Path(run_dir), gate.phase)
            owners = {next(task for task in tracker.tasks if task.id == item.id).owner for item in planned}
            if reviewer_assignments[0] in owners:
                raise TransitionError("phase reviewer must be independent from implementation owners")
        else:
            if len(reviewer_assignments) != 2 or any(phase.state != "[x]" for phase in tracker.phases):
                raise TransitionError("master review needs two reviewers after all phases verify")
            if any(item.type == "phase" and item.state != "accepted" for item in tracker.gates):
                raise TransitionError("master review waits for every required phase gate")
        _validate_worker_capacity(tracker, reviewer_assignments, capacity)
        repo_dir = _project_root(Path(run_dir))
        if not _git(repo_dir, "merge-base", "--is-ancestor", base, head) or not _git(repo_dir, "merge-base", "--is-ancestor", head, tracker.target_branch):
            raise TransitionError("review range is not an integrated target-branch range")
        return _replace_gate(
            tracker,
            replace(gate, state="in_progress", base=base, head=head, assignments=",".join(reviewer_assignments)),
        )

    return locked_tracker_update(
        Path(run_dir), f"open-gate-{gate_id}-{head}", transition,
        timeout_s=5.0, refresh_next_action=True,
    )


_REVIEW_FIELDS = ("gate", "assignment", "base", "head", "findings")
_FINDING_HEADER = ("ID", "Gate", "Severity", "Status", "Disposition", "Evidence", "Fix Commit", "Re-review")
_VERIFICATION_MARKER = "<!-- pipeline-verification-evidence/v2 -->"
_VERIFICATION_FIELDS = ("code_state", "outcome", "commands")


def _validate_verification_evidence(
    run_dir: Path,
    references: tuple[str, ...],
    expected_head: str,
) -> None:
    """Require digest-bound PASS evidence whose recorded code state is exact."""
    if not references:
        raise TransitionError("verification evidence is required")
    if len(references) != len(set(references)):
        raise TransitionError("verification evidence references must be unique")
    project_root = _project_root(run_dir).resolve()
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
        if (
            values["code_state"] != expected_head
            or values["outcome"] != "PASS"
            or values["commands"] in {"", "-"}
        ):
            raise TransitionError("verification evidence does not prove PASS on the applicable code state")


def _parse_review_report(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"review report is unreadable: {path}: {exc}") from exc
    if not lines or lines[0] != "<!-- pipeline-review-report/v2 -->":
        raise TransitionError("review report marker is missing")
    values = dict(_key_values(lines[1:], _REVIEW_FIELDS, TransitionError))
    return values


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
) -> None:
    decisions_path = _resolved_reference(run_dir, dict(tracker.run_fields)["decisions"])
    try:
        sections = _decision_sections(decisions_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise TransitionError(f"cannot read recorded decisions at {decisions_path}: {exc}") from exc
    lines = sections.get(decision_ref)
    if lines is None:
        raise TransitionError(f"decision {decision_ref} is missing")
    answers = _field_lines(lines, "Answer")
    statuses = _field_lines(lines, "Status")
    scopes = _field_lines(lines, "Scope") + _field_lines(lines, "Affected task") + _field_lines(lines, "Affected work")
    if len(answers) != 1 or len(statuses) != 1 or not scopes:
        raise TransitionError("decision evidence is missing, duplicated, or conflicting")
    answer = answers[0].strip().rstrip(".")
    if not answer or answer.casefold() in {"approved", "yes", "continue", "proceed", "go", "pending user response"}:
        raise TransitionError("generic approval or an empty answer cannot resolve a review blocker")
    if statuses[0].strip().rstrip(".").casefold() != "resolved":
        raise TransitionError("decision is not resolved")
    folded_scopes = " ".join(scopes).casefold()
    if not any(term.casefold() in folded_scopes for term in terms):
        raise TransitionError("decision is unrelated to the current review blocker")
    for other_ref, other_lines in sections.items():
        if other_ref == decision_ref:
            continue
        other_status = _field_lines(other_lines, "Status")
        other_scopes = _field_lines(other_lines, "Scope") + _field_lines(other_lines, "Affected task") + _field_lines(other_lines, "Affected work")
        if (
            len(other_status) == 1
            and other_status[0].strip().rstrip(".").casefold() in {"open", "pending", "blocked"}
            and any(term.casefold() in " ".join(other_scopes).casefold() for term in terms)
        ):
            raise TransitionError(f"unresolved decision {other_ref} still blocks review acceptance")


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
        terms = {gate.id, gate.phase, *_csv(gate.findings)}
        for decision_ref in decision_refs:
            _resolved_decision_for_terms(Path(run_dir), tracker, decision_ref, terms)
        return _replace_gate(tracker, replace(gate, questions="-"))

    return locked_tracker_update(
        Path(run_dir), f"resolve-gate-{gate_id}-{'-'.join(sorted(decision_refs))}",
        transition, timeout_s=5.0, refresh_next_action=True,
    )


def start_remediation_round(
    run_dir: Path,
    *,
    gate_id: str,
    round_number: int,
    finding_ids: tuple[str, ...],
    fix_plan: str,
    fixer_assignments: tuple[str, ...] = (),
    capacity: int | None = None,
) -> Tracker:
    if (
        round_number not in {1, 2, 3}
        or not finding_ids
        or len(finding_ids) != len(set(finding_ids))
        or not fixer_assignments
        or len(fixer_assignments) != len(set(fixer_assignments))
    ):
        raise TransitionError("remediation round must be 1..3 with unique targeted findings")
    if not Path(fix_plan).is_file():
        raise TransitionError("remediation fix plan does not exist")

    def transition(tracker: Tracker) -> Tracker:
        gate = _gate_record(tracker, gate_id)
        if gate.state != "blocked":
            raise TransitionError("remediation requires a blocked gate")
        if gate.questions != "-":
            raise TransitionError("an unresolved gate question prevents remediation dispatch")
        _validate_worker_capacity(tracker, fixer_assignments, capacity)
        authoritative_findings = _resolved_reference(
            Path(run_dir), dict(tracker.run_fields)["findings"]
        )
        open_blockers = {
            row[0]
            for row in _parse_findings(authoritative_findings)
            if row[1] == gate.id and row[2] in {"Critical", "Important"} and row[3] == "Open"
        }
        if set(finding_ids) != open_blockers:
            raise TransitionError("remediation targets must exactly match the gate's current blocking findings")
        rows = list(tracker.remediation)
        existing = next((row for row in rows if row.gate == gate_id and row.round_number == round_number), None)
        if existing is not None and existing.state == "fixing" and existing.findings == ",".join(finding_ids) and existing.fix_plan == fix_plan and existing.fixers == ",".join(fixer_assignments):
            raise _AlreadyApplied(tracker)
        if existing is not None and existing.state != "pending":
            raise TransitionError("remediation round is already used or conflicting")
        if round_number > 1:
            prior = next((row for row in rows if row.gate == gate_id and row.round_number == round_number - 1), None)
            if prior is None or prior.state != "complete":
                raise TransitionError("prior remediation round is not complete")
        replacement = RemediationRecord(
            gate_id, round_number, "fixing", ",".join(fixer_assignments), "-",
            ",".join(finding_ids), fix_plan, "-", "-", "-",
        )
        if existing is None:
            rows.append(replacement)
        else:
            rows[rows.index(existing)] = replacement
        return replace(tracker, remediation=tuple(rows))

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
    if not _COMMIT.fullmatch(fix_head) or not commits or not verification:
        raise TransitionError("fix integration needs a HEAD, commits, and verification")

    def transition(tracker: Tracker) -> Tracker:
        _validate_verification_evidence(Path(run_dir), verification, fix_head)
        gate = _gate_record(tracker, gate_id)
        row = next(
            (item for item in tracker.remediation if item.gate == gate_id and item.round_number == round_number),
            None,
        )
        if row is None or row.state != "fixing" or row.fixers == "-":
            raise TransitionError("only an active fixing round can move to re-review")
        if gate.state != "blocked" or gate.questions != "-":
            raise TransitionError("gate is not eligible for re-review")
        if (
            not _git(Path(repo_dir), "cat-file", "-e", f"{fix_head}^{{commit}}")
            or not _git(Path(repo_dir), "merge-base", "--is-ancestor", fix_head, tracker.target_branch)
            or fix_head == gate.head
            or not _git(Path(repo_dir), "merge-base", "--is-ancestor", gate.head, fix_head)
        ):
            raise TransitionError("fix HEAD is not integrated on the target branch")
        if any(
            not _COMMIT.fullmatch(commit)
            or _git(Path(repo_dir), "merge-base", "--is-ancestor", commit, gate.head)
            or not _git(Path(repo_dir), "merge-base", "--is-ancestor", gate.head, commit)
            or not _git(Path(repo_dir), "merge-base", "--is-ancestor", commit, fix_head)
            for commit in commits
        ):
            raise TransitionError("fix commit lacks strict post-review provenance in the integrated fix HEAD")
        released = _append_history(row.released_fixers, row.fixers)
        updated_row = replace(
            row,
            state="re_reviewing",
            fixers="-",
            released_fixers=released,
            commits=",".join(commits),
            verification=",".join(verification),
        )
        interim = replace(
            tracker,
            remediation=tuple(updated_row if item is row else item for item in tracker.remediation),
        )
        assignments = _csv(gate.assignments)
        _validate_worker_capacity(interim, assignments, capacity)
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

    def transition(tracker: Tracker) -> Tracker:
        gate = _gate_record(tracker, gate_id)
        if gate.state not in {"in_progress", "re_reviewing"}:
            raise TransitionError("gate is not open for evaluation")
        authoritative_findings = _resolved_reference(
            Path(run_dir), dict(tracker.run_fields)["findings"]
        ).resolve()
        if Path(findings_path).resolve() != authoritative_findings:
            raise TransitionError("findings ledger is not the run's authoritative findings artifact")
        reports = tuple(_parse_review_report(Path(path)) for path in report_paths)
        expected_assignments = tuple(gate.assignments.split(","))
        if tuple(sorted(report["assignment"] for report in reports)) != tuple(sorted(expected_assignments)):
            raise TransitionError("required reviewer reports are missing, duplicated, or unexpected")
        if any(report["gate"] != gate.id or report["base"] != gate.base or report["head"] != gate.head for report in reports):
            raise TransitionError("review report belongs to a different gate or code state")
        active_round = next(
            (row for row in tracker.remediation if row.gate == gate.id and row.state == "re_reviewing"),
            None,
        )
        rereviews = tuple(_parse_review_report(Path(path)) for path in rereview_paths)
        reviewed_head = gate.head
        if active_round is not None:
            if not rereviews:
                raise TransitionError("an active remediation round requires re-review evidence")
            if tuple(sorted(report["assignment"] for report in rereviews)) != tuple(sorted(expected_assignments)):
                raise TransitionError("re-review assignments do not match the gate")
            rereview_heads = {report["head"] for report in rereviews}
            if len(rereview_heads) != 1 or any(report["gate"] != gate.id for report in rereviews):
                raise TransitionError("re-review reports disagree on gate or reviewed HEAD")
            reviewed_head = next(iter(rereview_heads))
            if any(report["base"] != gate.head for report in rereviews):
                raise TransitionError("re-review base must be the prior reviewed HEAD")
            repo_dir = _project_root(Path(run_dir))
            if not _git(repo_dir, "merge-base", "--is-ancestor", gate.head, reviewed_head) or not _git(repo_dir, "merge-base", "--is-ancestor", reviewed_head, tracker.target_branch):
                raise TransitionError("re-review code state is not integrated after the prior gate HEAD")
        _validate_verification_evidence(Path(run_dir), verification, reviewed_head)
        if active_round is not None:
            recorded_verification = tuple(
                item
                for item in _csv(active_round.verification)
                if not item.startswith("remaining-blockers=")
            )
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
        report_ids = {finding for report in (*reports, *rereviews) for finding in _csv(report["findings"])}
        if row_ids != report_ids:
            raise TransitionError("review reports and findings ledger disagree")
        invalid_rows: list[tuple[str, ...]] = []
        blockers: list[tuple[str, ...]] = []
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
                    if evidence == "-" or fix_commit == "-" or re_review == "-":
                        invalid_rows.append(row)
                elif disposition == "Rejected":
                    if evidence == "-" or fix_commit != "-":
                        invalid_rows.append(row)
                else:
                    invalid_rows.append(row)
            else:
                if status != "Resolved" or disposition not in {"Fixed", "Deferred", "Rejected"} or evidence == "-":
                    invalid_rows.append(row)
                if disposition == "Fixed" and (fix_commit == "-" or re_review == "-"):
                    invalid_rows.append(row)
                if disposition in {"Deferred", "Rejected"} and fix_commit != "-":
                    invalid_rows.append(row)
        fixed_commits = [row[6] for row in rows if row[4] == "Fixed" and row[6] != "-"]
        rereview_ids = {finding for report in rereviews for finding in _csv(report["findings"])}
        fixed_ids = {row[0] for row in rows if row[4] == "Fixed" and row[6] != "-"}
        if fixed_commits and (not rereviews or not fixed_ids.issubset(rereview_ids)):
            raise TransitionError("repository-changing review fixes require matching re-review evidence")
        repo_dir = _project_root(Path(run_dir))
        remediation_commits = {
            commit
            for remediation in tracker.remediation
            if remediation.gate == gate.id
            for commit in _csv(remediation.commits)
        }
        if any(
            not _COMMIT.fullmatch(commit)
            or commit not in remediation_commits
            or not _git(repo_dir, "merge-base", "--is-ancestor", commit, reviewed_head)
            for commit in fixed_commits
        ):
            raise TransitionError("review fix commit is invalid or absent from the reviewed HEAD")
        if invalid_rows:
            raise TransitionError("finding status, severity, disposition, or evidence is invalid")
        questions = gate.questions
        remediation_rows = list(tracker.remediation)
        if active_round is not None:
            targeted = set(active_round.findings.split(","))
            open_blocker_ids = {row[0] for row in blockers}
            progress = bool(targeted - open_blocker_ids)
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
            elif blockers and active_round.round_number == 3:
                questions = "remediation-limit-reached-round-3"
            completed_round = replace(
                active_round,
                state="complete",
                verification=_append_history(
                    active_round.verification,
                    "remaining-blockers=" + ("+".join(sorted(open_blocker_ids)) or "none"),
                ),
                re_review=",".join(str(Path(path)) for path in rereview_paths),
            )
            remediation_rows[remediation_rows.index(active_round)] = completed_round
        state = "blocked" if blockers or questions != "-" else "accepted"
        replacement = replace(
            gate,
            state=state,
            head=reviewed_head,
            reports=",".join(str(Path(path)) for path in report_paths),
            verification=",".join(verification),
            findings=",".join(sorted(row_ids)) or "-",
            questions=questions,
        )
        return replace(_replace_gate(tracker, replacement), remediation=tuple(remediation_rows))

    return locked_tracker_update(
        Path(run_dir),
        f"evaluate-gate-{gate_id}-{hashlib.sha256('|'.join(verification).encode()).hexdigest()}",
        transition, timeout_s=5.0, refresh_next_action=True,
    )


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
