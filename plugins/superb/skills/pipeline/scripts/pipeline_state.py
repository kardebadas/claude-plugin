#!/usr/bin/env python3
"""Strict Pipeline v2 Markdown contracts.

This module intentionally supports one tracker, worker-result, and phase-plan
metadata grammar. Mutation, locking, scheduling, and recovery are added by the
later Phase 1 tasks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SCHEMA = "pipeline-run/v2"
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


_RUN_KEYS = ("run_id", "base_commit", "target_branch", "worker_limit", "spec", "master_plan", "phase_plans", "decisions", "findings", "revision", "last_transition")
_CURRENT_KEYS = ("phase", "batch", "next_action")
_RESULT_KEYS = ("run_id", "task_id", "attempt", "kind", "status", "source_ref", "commits", "artifacts", "tests", "evidence", "concerns", "question", "blocking_reason")
_TASK_HEADER = ("ID", "Kind", "State", "Owner", "Attempt", "Result", "Checkpoints", "Source Ref", "Commits", "Artifacts", "Integration", "Verification", "Question")
_PHASE_HEADER = ("ID", "State", "Verification", "Review Gate", "Review Reason", "Gate")
_GATE_HEADER = ("ID", "Type", "Phase", "State", "Base", "Head", "Assignments", "Reports", "Verification", "Findings", "Questions")
_REMEDIATION_HEADER = ("Gate", "Round", "State", "Findings", "Fix Plan", "Commits", "Verification", "Re-review")
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
    for phase in phases:
        if phase.state not in _TASK_STATES or phase.review_gate not in {"required", "final-only"}:
            raise SchemaError("invalid phase state or review gate")
        if phase.review_gate == "required" and phase.review_reason == "-":
            raise SchemaError("required phase review needs a reason")
    for gate in gates:
        if gate.type not in {"phase", "master"} or gate.state not in {"pending", "in_progress", "blocked", "accepted"}:
            raise SchemaError("invalid gate type or state")
    if any(row.state not in {"pending", "in_progress", "blocked", "complete"} for row in remediation):
        raise SchemaError("invalid remediation state")
    return Tracker(run_fields, current_fields, tasks, phases, gates, remediation)


def _row(values: tuple[object, ...]) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"


def _render_table(header: tuple[str, ...], rows: tuple[tuple[object, ...], ...]) -> list[str]:
    return [_row(header), _row(tuple("---" for _ in header)), *[_row(row) for row in rows]]


def render_tracker(tracker: Tracker) -> str:
    task_rows = tuple(tuple(getattr(row, field) for field in TaskRecord.__dataclass_fields__) for row in tracker.tasks)
    phase_rows = tuple(tuple(getattr(row, field) for field in PhaseRecord.__dataclass_fields__) for row in tracker.phases)
    gate_rows = tuple(tuple(getattr(row, field) for field in GateRecord.__dataclass_fields__) for row in tracker.gates)
    remediation_rows = tuple((row.gate, row.round_number, row.state, row.findings, row.fix_plan, row.commits, row.verification, row.re_review) for row in tracker.remediation)
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
    if values["attempt"] == "-" or values["tests"] == "-" or not evidence:
        raise SchemaError("worker result needs attempt, tests, and evidence")
    if any(checkpoint.status not in {"complete", "in_progress", "blocked"} or checkpoint.evidence == "-" for checkpoint in checkpoints):
        raise SchemaError("invalid worker checkpoint")
    if values["kind"] == "source":
        if values["source_ref"] == "-" or not commits or artifacts or any(not _COMMIT.fullmatch(commit) for commit in commits):
            raise SchemaError("source result needs source ref and commits only")
    elif values["source_ref"] != "-" or commits or not artifacts:
        raise SchemaError("artifact result needs artifacts and no source provenance")
    return WorkerResult(values["run_id"], values["task_id"], values["attempt"], values["kind"], values["status"], values["source_ref"], commits, artifacts, values["tests"], evidence, values["concerns"], values["question"], values["blocking_reason"], checkpoints)


_PHASE_METADATA = re.compile(r"<!-- pipeline-v2-phase: id=([^;]+); deps=([^;]+); review_gate=([^;]+); review_reason=(.+) -->\Z")
_TASK_METADATA = re.compile(r"<!-- pipeline-v2-task: id=([^;]+); deps=([^;]+); kind=([^;]+); batch=([^;]+); order=([^;]+); write_scope=([^;]+); outputs=([^;]+) -->\Z")


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in path.parts) or any(character in value for character in "*?[]{}"):
        raise PlanMetadataError(f"unsupported repository-relative path: {value!r}")
    return path


def _parse_phase_document(path: Path) -> tuple[PhaseMetadata, tuple[PlannedTask, ...]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    phase_lines = [line for line in lines if line.startswith("<!-- pipeline-v2-phase:")]
    if len(phase_lines) != 1 or _PHASE_METADATA.fullmatch(phase_lines[0]) is None:
        raise PlanMetadataError("phase plan needs one valid ordered phase metadata comment")
    phase = _PHASE_METADATA.fullmatch(phase_lines[0])
    assert phase is not None
    if phase.group(3) not in {"required", "final-only"} or not phase.group(4).strip():
        raise PlanMetadataError("invalid phase review metadata")
    phase_deps = () if phase.group(2) == "none" else tuple(phase.group(2).split(","))
    metadata = PhaseMetadata(phase.group(1), phase_deps, phase.group(3), phase.group(4))
    tasks = []
    for line in lines:
        if not line.startswith("<!-- pipeline-v2-task:"):
            continue
        match = _TASK_METADATA.fullmatch(line)
        if match is None:
            raise PlanMetadataError("task metadata keys are missing, unknown, or reordered")
        task_id, deps_raw, kind, batch, order_raw, scopes_raw, outputs_raw = match.groups()
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


def _diagnostic(run_dir: Path, detail: str) -> str:
    return f"{run_dir}: {detail}; no files were changed"


def _recognized_v1(text: str) -> bool:
    return (
        "# Pipeline — Progress Tracker" in text
        and "## Current State" in text
        and any(_LEGACY_TASK.match(line) for line in text.splitlines())
    )


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
    remediation = tuple(RemediationRecord(gate.id, 1, "pending", "-", "-", "-", "-", "-") for gate in gates)
    first_metadata, first_tasks = phase_documents[0]
    return Tracker(
        tuple(
            zip(
                _RUN_KEYS,
                (
                    run_id,
                    base_commit,
                    target_branch,
                    str(worker_limit),
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
) -> Tracker:
    """Create a new v2 tracker without overwriting any existing state."""
    run_dir = Path(run_dir)
    tracker = _initial_tracker(
        run_id=run_id,
        base_commit=base_commit,
        target_branch=target_branch,
        worker_limit=worker_limit,
        artifacts=artifacts,
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
    tracker = validate_run(run_dir)
    return {
        "run_id": tracker.run_id,
        "target_branch": tracker.target_branch,
        "worker_limit": tracker.worker_limit,
        "revision": tracker.revision,
        "phase": dict(tracker.current_fields)["phase"],
        "next_action": dict(tracker.current_fields)["next_action"],
        "task_counts": {state: sum(task.state == state for task in tracker.tasks) for state in sorted(_TASK_STATES)},
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline_state.py")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("run_dir", type=Path)
    next_command = commands.add_parser("next")
    next_command.add_argument("run_dir", type=Path)
    next_command.add_argument("--phase-plan", type=Path, required=True)
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
            validate_run(args.run_dir)
            parse_phase_plan(args.phase_plan)
            print("next is read-only but scheduling is unavailable until P1-05", file=sys.stderr)
            return 2
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
        )
        print(f"initialized {args.run_dir}")
        return 0
    except (SchemaError, PlanMetadataError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
