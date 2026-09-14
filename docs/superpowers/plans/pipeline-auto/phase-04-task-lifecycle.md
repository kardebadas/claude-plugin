# P04 Task Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pipeline-auto task lifecycle — reserve, resume, typed write scopes, immutable worker-result identity, the baseline-anchored source-range proof, integration ancestry, and file-first reconciliation — inside `pipeline_auto_state.py`, together with the phase-plan metadata grammar parser and the two result/evidence templates.

**Architecture:** P04 appends a task-lifecycle layer to the single state module P02 created. Every durable mutation goes through P02's `locked_tracker_update`; P04 supplies only `mutate` callables and pure validators. The phase-plan metadata grammar is a strict, key-order-pinned HTML-comment format so a plan is machine-readable structure rather than prose a worker may reinterpret. Two semantics change from `superb:pipeline`: `NEEDS_CONTEXT` and `PLAN_CONFLICT` now route to a quorum instead of halting, and implementation tasks may never occupy more than `worker_limit - 3` slots so the three brain slots that would unblock them always exist.

**Tech Stack:** Python 3 standard library only. `pytest` for tests. Markdown for all durable state. `git` invoked through `subprocess` for every commit fact.

**Spec:** `docs/superpowers/specs/2026-09-14-pipeline-auto-design.md`

**Master plan:** `docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md`

**Phase:** P04 — task-lifecycle. **Review class:** `required`. **Depends on:** P02. **Independent of:** P03.

## Global Constraints

- `plugins/superb/skills/pipeline/` is **not modified**. Not one line. Verify with `git diff --name-only` before every commit.
- Schema string is exactly `pipeline-auto/v1`; tracker marker is exactly `<!-- pipeline-auto/v1 -->`.
- No migration path from `pipeline-run/v1` or `pipeline-run/v2` exists or is ever added, in either direction.
- A foreign, missing, malformed, or unknown schema is a **read-only stop**: preserve the directory, change no files, dispatch nothing. Rejected input must be **byte-identical** after the rejected parse.
- Implementation tasks may occupy at most `worker_limit - 3` slots. `worker_limit >= 4` is required for concurrency.
- Exactly three brains per quorum, exactly three readers at stage 01. A count is never reduced to fit capacity.
- Python: standard library only. No new dependencies in any phase.
- No absolute home-directory paths in any committed file. Repository-relative paths only.
- No push, no publish, no PR, no merge into `main`/`master`.
- Worktree granularity: one per concurrently dispatched implementer, merged `--no-ff` in task order. `--no-ff` preserves ancestry by construction, so the no-squash rule holds.
- **A merge conflict at integration is a hard stop.** Under typed write-scope validation a conflict should be impossible, so a conflict is evidence the scope declaration was wrong — not something to auto-redo past. Redoing the task alone papers over a broken declaration and lets the next task hit the same collision. The run stops and reports which two scopes overlapped.

## What changes from `superb:pipeline`

Read these four before writing any code. They are the point of the phase, and each is a named fault below.

1. **Status semantics reverse for two of five.** The vocabulary is unchanged — `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `PLAN_CONFLICT`, `BLOCKED` — but in `superb:pipeline` all three non-DONE statuses mean "block and ask the human". In pipeline-auto, `NEEDS_CONTEXT` and `PLAN_CONFLICT` mean "raise a quorum question". Only `BLOCKED` still means halt, because three brains cannot conjure an API key or a permission.
2. **A quorum-raising result must carry a question record reference.** A `NEEDS_CONTEXT` or `PLAN_CONFLICT` result without a resolvable, digest-bound `question_record` is **rejected**, exactly as a result with a missing owner is rejected today.
3. **Implementation tasks may reserve at most `worker_limit - 3` slots.** Three are held for a quorum. Without this the run deadlocks permanently: a blocked task holds the slot needed to dispatch the brains that would unblock it. Below `worker_limit = 4` the cap floors at one, so tasks serialise and the brain slots stay free.
4. **The review baseline is the one persisted at reservation**, never `HEAD~1`. `HEAD~1` silently truncates a multi-commit task to its last commit and the earlier commits escape every scope and range check.
5. **A merge conflict at integration is a hard stop, not an abort-and-redo-alone.** Redoing the task alone papers over a broken scope declaration and lets the next task hit the same collision. The error names both task ids and both declared scopes.
6. **The ancestry predicate is written for the per-implementer-worktree topology.** Clause 1 is unchanged: a task's recorded commits are ancestors of its own branch tip. Clause 2 becomes: the task branch tip is an ancestor of the `--no-ff` merge commit, and the merge commit is an ancestor of the target branch. Clause 3 is unchanged but its code state is the **merge commit**. `--no-ff` is load-bearing, not stylistic — a fast-forward collapses the merge commit and destroys the boundary clause 2 checks, so the predicate asserts two parents.

## Named faults this phase's tests must catch

| # | Fault | Caught by |
| --- | --- | --- |
| F1 | `scopes_overlap` implemented as plain equality, so `tree:src` and `file:src/a.py` reserve together and two implementers write the same file | Task 3, Task 6 |
| F2 | Reserving up to `worker_limit` instead of `worker_limit - 3`, deadlocking the run | Task 6 |
| F3 | Using `HEAD~1` as the review baseline instead of the baseline persisted at reservation | Task 8, Task 10 |
| F4 | Accepting a source range containing a pre-baseline, extra, unrelated, or empty commit | Task 8, Task 10 |
| F5 | A quorum-raising result with no question record reference | Task 4, Task 10 |
| F6 | A result whose `run_id + task_id + attempt + owner` does not exactly match the persisted assignment | Task 10 |
| F7 | Treating a missing worker result as evidence of completion, or as grounds to repeat the work | Task 11 |
| F8 | A phase plan whose metadata keys are reordered, renamed, or missing `review_class` | Task 1, Task 2 |
| F9 | A merge conflict at integration auto-recovered (redo-alone, `--strategy=ours`, retry) instead of stopping and naming both colliding scopes | Task 11 |
| F10 | A fast-forward integration accepted, collapsing the merge commit that clause 2 of the ancestry predicate checks | Task 11 |

---

## File Structure

| File | Responsibility | P04 action |
| --- | --- | --- |
| `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py` | The spine. P04 appends the plan grammar, scope algebra, result/evidence codecs, and the task lifecycle transitions | Modify (created by P02) |
| `plugins/superb/skills/pipeline-auto/templates/worker-result.md` | Canonical immutable worker-result document | Create |
| `plugins/superb/skills/pipeline-auto/templates/verification-evidence.md` | Canonical digest-bound typed PASS record | Create |
| `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py` | Every P04 test and the shared run/repo harness | Create |

P04 puts its tests in their own file rather than appending to `tests/test_pipeline_auto_state.py`. The master plan's verification suite runs the whole `tests/` directory, so a second file is inside the named structure, and it keeps P03's and P04's write scopes disjoint — which is exactly the property `scopes_overlap` exists to enforce.

## Interfaces consumed from P02

P04 calls these and assumes they exist and work:

```python
SCHEMA = "pipeline-auto/v1"
MARKER = "<!-- pipeline-auto/v1 -->"

class TrackerError(Exception): ...
class ForeignSchemaError(TrackerError): ...
class TrackerValidationError(TrackerError): ...
class TrackerWriteError(TrackerError): ...
class UpdateOutcomeUncertain(TrackerError): ...
class PlanMetadataError(TrackerError): ...

def parse_tracker(text: str) -> dict: ...
def render_tracker(tracker: dict) -> str: ...
def validate_run(run_dir: str) -> dict: ...
def initialize_run(run_dir: str, *, run_id: str, base_commit: str,
                   target_branch: str, worker_limit: int) -> dict: ...
def locked_tracker_update(run_dir: str, *, transition_id: str, mutate) -> dict: ...
def publish_immutable(path: str, content: str) -> str: ...
def derive_next_action(tracker: dict) -> str: ...
```

**Assumed tracker dict shape.** P02's signatures name `dict` but not its keys. P04 touches the tracker through exactly four private accessors — `_run_field`, `_current_field`, `_task_row`, `_replace_task` — plus `_quorum_owners`. If P02's shape differs from the assumption below, those five functions are the only code that changes.

```python
tracker = {
    "run": {"run_id": str, "base_commit": str, "target_branch": str,
            "worker_limit": str, "revision": str, "spec": str,
            "master_plan": str, "phase_plans": str, "decisions": str,
            "findings": str},
    "current": {"stage": str, "phase": str, "next_action": str},
    "phases": [{"id": str, "state": str, "review_class": str,
                "class_source": str, "ratchet": str}],
    "tasks": [{"id": str, "state": str, "kind": str, "owner": str,
               "attempt": str, "deps": str, "checkpoints": str,
               "result": str, "source_ref": str, "commits": str,
               "artifacts": str, "integration": str, "verification": str,
               "question": str, "provisional": str}],
    "quorum": [{"qid": str, "state": str, "owners": str}],
}
```

Every scalar is a table-safe string; `-` is the empty marker; multi-valued cells are comma-separated. `worker_limit` is read with `int(...)`.

## Interfaces P04 produces

Implemented exactly as the master plan states them:

```python
def reserve_task(run_dir: str, *, task_id: str, owner: str, attempt: int) -> dict: ...
def resume_task(run_dir: str, *, task_id: str, prior_attempt: int,
                new_owner: str, new_attempt: int, decision_ref: str) -> dict: ...
def scopes_overlap(a: str, b: str) -> bool: ...
def publish_worker_result(run_dir: str, *, result: dict) -> str: ...
def import_worker_result(run_dir: str, *, result_path: str) -> dict: ...
def verify_source_range(repo: str, *, baseline: str, head: str, scopes: list) -> dict: ...
def reconcile_run(run_dir: str) -> dict: ...
```

Plus the phase-plan metadata grammar parser, named `parse_phase_plan(path) -> tuple[PhaseMetadata, tuple[PlannedTask, ...]]`, and the two templates.

## Phase verification suite

The exact ordered command tuple for P04:

```bash
python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v
python3 -m pytest plugins/superb/skills/pipeline-auto/tests/ -v
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The third command must print nothing.

---

### Task 1: Phase-plan header grammar and the test harness

The phase-plan metadata comment is what stops a plan being prose a worker reinterprets. The grammar is strict and its key **order is pinned**: a reordered, renamed, or missing key is a `PlanMetadataError`, not a best-effort parse. `review_class` replaces v2's `review_gate` and carries the review-intensity dial value.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Create: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `PlanMetadataError` from P02.
- Produces: `PhaseMetadata(id, deps, review_class, review_reason, commands)` NamedTuple; `_parse_phase_document(path) -> tuple[PhaseMetadata, tuple]` returning `(metadata, ())` for now; `_safe_relative(value) -> PurePosixPath`; `_parse_command_suite(raw) -> tuple[str, ...]`; `_TOKEN`; and the test harness functions `write_phase_plan`, `phase_header`, `task_block`.

- [ ] **Step 1: Write the failing test**

Create `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
"""P04 task-lifecycle tests for pipeline-auto."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "pipeline_auto_state.py"
)
_SPEC = importlib.util.spec_from_file_location("pipeline_auto_state", _MODULE_PATH)
state = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(state)


# --------------------------------------------------------------------------
# Shared harness. Every later task reuses these.
# --------------------------------------------------------------------------

def phase_header(
    *,
    phase_id: str = "P04",
    deps: str = "none",
    review_class: str = "required",
    review_reason: str = "task lifecycle is security-relevant",
    commands: str = '["python3 -m pytest tests -q"]',
) -> str:
    return (
        f"<!-- pipeline-auto-phase: id={phase_id}; deps={deps}; "
        f"review_class={review_class}; review_reason={review_reason} -->\n"
        f"<!-- pipeline-auto-phase-suite: id={phase_id}; commands={commands} -->\n"
    )


def task_block(
    task_id: str,
    *,
    deps: str = "none",
    kind: str = "source",
    batch: str = "b1",
    order: int = 1,
    write_scope: str = "file:src/a.py",
    outputs: str = "none",
    commands: str | None = None,
) -> str:
    text = (
        f"## Task {task_id}\n\n"
        f"<!-- pipeline-auto-task: id={task_id}; deps={deps}; kind={kind}; "
        f"batch={batch}; order={order}; write_scope={write_scope}; "
        f"outputs={outputs} -->\n"
    )
    if kind == "source":
        suite = commands or f'["python3 -m pytest tests -k {task_id} -q"]'
        text += f"<!-- pipeline-auto-task-suite: id={task_id}; commands={suite} -->\n"
    return text + "\nProse describing the task.\n\n"


def write_phase_plan(directory: Path, body: str, *, header: str | None = None,
                     name: str = "phase-04.md") -> Path:
    path = Path(directory) / name
    path.write_text(
        "# Phase 04 plan\n\n" + (header or phase_header()) + "\n" + body,
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# Task 1 tests
# --------------------------------------------------------------------------

def test_phase_header_parses_pinned_key_order(tmp_path):
    plan = write_phase_plan(tmp_path, task_block("T1"))
    metadata, _ = state._parse_phase_document(plan)
    assert metadata.id == "P04"
    assert metadata.deps == ()
    assert metadata.review_class == "required"
    assert metadata.review_reason == "task lifecycle is security-relevant"
    assert metadata.commands == ("python3 -m pytest tests -q",)


def test_phase_header_rejects_reordered_keys(tmp_path):
    header = (
        "<!-- pipeline-auto-phase: id=P04; review_class=required; deps=none; "
        "review_reason=swapped -->\n"
        '<!-- pipeline-auto-phase-suite: id=P04; commands=["a"] -->\n'
    )
    plan = write_phase_plan(tmp_path, task_block("T1"), header=header)
    with pytest.raises(state.PlanMetadataError):
        state._parse_phase_document(plan)


def test_phase_header_rejects_v2_review_gate_key(tmp_path):
    header = (
        "<!-- pipeline-auto-phase: id=P04; deps=none; review_gate=required; "
        "review_reason=old grammar -->\n"
        '<!-- pipeline-auto-phase-suite: id=P04; commands=["a"] -->\n'
    )
    plan = write_phase_plan(tmp_path, task_block("T1"), header=header)
    with pytest.raises(state.PlanMetadataError):
        state._parse_phase_document(plan)


def test_phase_header_rejects_unknown_review_class(tmp_path):
    plan = write_phase_plan(
        tmp_path, task_block("T1"), header=phase_header(review_class="medium")
    )
    with pytest.raises(state.PlanMetadataError):
        state._parse_phase_document(plan)


def test_phase_header_rejects_empty_review_reason(tmp_path):
    plan = write_phase_plan(
        tmp_path, task_block("T1"), header=phase_header(review_reason="   ")
    )
    with pytest.raises(state.PlanMetadataError):
        state._parse_phase_document(plan)


def test_phase_suite_must_immediately_follow_phase_metadata(tmp_path):
    header = (
        "<!-- pipeline-auto-phase: id=P04; deps=none; review_class=required; "
        "review_reason=split -->\n\n"
        '<!-- pipeline-auto-phase-suite: id=P04; commands=["a"] -->\n'
    )
    plan = write_phase_plan(tmp_path, task_block("T1"), header=header)
    with pytest.raises(state.PlanMetadataError):
        state._parse_phase_document(plan)


def test_phase_suite_identity_must_match_phase_metadata(tmp_path):
    header = (
        "<!-- pipeline-auto-phase: id=P04; deps=none; review_class=required; "
        "review_reason=mismatch -->\n"
        '<!-- pipeline-auto-phase-suite: id=P05; commands=["a"] -->\n'
    )
    plan = write_phase_plan(tmp_path, task_block("T1"), header=header)
    with pytest.raises(state.PlanMetadataError):
        state._parse_phase_document(plan)


def test_phase_metadata_must_precede_the_first_section(tmp_path):
    path = tmp_path / "phase-04.md"
    path.write_text(
        "# Phase 04 plan\n\n## Overview\n\n" + phase_header() + "\n"
        + task_block("T1"),
        encoding="utf-8",
    )
    with pytest.raises(state.PlanMetadataError):
        state._parse_phase_document(path)


def test_phase_metadata_must_occur_exactly_once(tmp_path):
    plan = write_phase_plan(
        tmp_path, task_block("T1"), header=phase_header() + phase_header()
    )
    with pytest.raises(state.PlanMetadataError):
        state._parse_phase_document(plan)


@pytest.mark.parametrize(
    "commands",
    ['[]', '["a","a"]', '["a",""]', '["a|b"]', '"a"', '["a"'],
)
def test_command_suite_rejects_malformed_values(tmp_path, commands):
    plan = write_phase_plan(
        tmp_path, task_block("T1"), header=phase_header(commands=commands)
    )
    with pytest.raises(state.PlanMetadataError):
        state._parse_phase_document(plan)


@pytest.mark.parametrize(
    "value",
    ["/abs/path", "../escape", "a/../b", "src/*.py", "", "a\\b", "src/./a"],
)
def test_safe_relative_rejects_unsupported_paths(value):
    with pytest.raises(state.PlanMetadataError):
        state._safe_relative(value)


def test_safe_relative_accepts_canonical_repository_relative_path():
    assert state._safe_relative("src/pkg/a.py").as_posix() == "src/pkg/a.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute '_parse_phase_document'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: phase-plan metadata grammar
#
# The key order below is PINNED. A reordered, renamed, or missing key is a
# PlanMetadataError, never a best-effort parse. This is what stops a phase plan
# being prose a worker may reinterpret.
# ---------------------------------------------------------------------------

import json
import re
from pathlib import Path, PurePosixPath
from typing import NamedTuple

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")

_PHASE_METADATA = re.compile(
    r"<!-- pipeline-auto-phase: id=([^;]+); deps=([^;]+); "
    r"review_class=([^;]+); review_reason=(.+) -->\Z"
)
_PHASE_SUITE = re.compile(
    r"<!-- pipeline-auto-phase-suite: id=([^;]+); commands=(.+) -->\Z"
)

REVIEW_CLASSES = ("required", "final-only")


class PhaseMetadata(NamedTuple):
    id: str
    deps: tuple[str, ...]
    review_class: str
    review_reason: str
    commands: tuple[str, ...]


def _parse_command_suite(raw: str) -> tuple[str, ...]:
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlanMetadataError(
            "verification commands must be a JSON string array"
        ) from exc
    if (
        not isinstance(values, list)
        or not values
        or any(
            not isinstance(value, str) or not value or "|" in value or "\n" in value
            for value in values
        )
        or len(values) != len(set(values))
    ):
        raise PlanMetadataError(
            "verification commands must be unique nonempty table-safe strings"
        )
    return tuple(values)


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(character in value for character in "*?[]{}")
    ):
        raise PlanMetadataError(f"unsupported repository-relative path: {value!r}")
    return path


def _phase_header(lines: list[str]) -> PhaseMetadata:
    phase_indexes = [
        index for index, line in enumerate(lines)
        if line.startswith("<!-- pipeline-auto-phase:")
    ]
    if len(phase_indexes) != 1:
        raise PlanMetadataError(
            "phase plan needs exactly one ordered phase metadata comment"
        )
    phase_index = phase_indexes[0]
    phase = _PHASE_METADATA.fullmatch(lines[phase_index])
    first_nonempty = next((line for line in lines if line.strip()), "")
    first_section = next(
        (index for index, line in enumerate(lines) if line.startswith("## ")),
        len(lines),
    )
    if (
        phase is None
        or not re.fullmatch(r"# [^#].+", first_nonempty)
        or phase_index >= first_section
    ):
        raise PlanMetadataError(
            "phase metadata keys are missing, unknown, or reordered, or the "
            "comment is not in the document header before the first section"
        )
    if not _TOKEN.fullmatch(phase.group(1)):
        raise PlanMetadataError("invalid phase id")
    if phase.group(3) not in REVIEW_CLASSES or not phase.group(4).strip():
        raise PlanMetadataError(
            "review_class must be 'required' or 'final-only' with a nonempty "
            "review_reason"
        )
    deps = () if phase.group(2) == "none" else tuple(phase.group(2).split(","))
    if any(not _TOKEN.fullmatch(dep) for dep in deps):
        raise PlanMetadataError("invalid phase dependency id")

    suite_indexes = [
        index for index, line in enumerate(lines)
        if line.startswith("<!-- pipeline-auto-phase-suite:")
    ]
    if len(suite_indexes) != 1 or suite_indexes[0] != phase_index + 1:
        raise PlanMetadataError(
            "phase suite must occur exactly once immediately after phase metadata"
        )
    suite = _PHASE_SUITE.fullmatch(lines[suite_indexes[0]])
    if suite is None or suite.group(1) != phase.group(1):
        raise PlanMetadataError("phase suite identity must match phase metadata")
    return PhaseMetadata(
        phase.group(1), deps, phase.group(3), phase.group(4),
        _parse_command_suite(suite.group(2)),
    )


def _parse_phase_document(path) -> tuple[PhaseMetadata, tuple]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return _phase_header(lines), ()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: PASS (all Task 1 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): pin phase-plan header grammar with review_class"
```

---

### Task 2: Task metadata grammar, typed write scopes, and dependency validation

A task definition declares `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, and `outputs` in that exact order, immediately beneath its own heading. `kind` is `source` or `artifact`; a worker cannot change it because its implementation happened to produce no diff. A source task declares `outputs=none` and one adjacent verification suite; an artifact task names every exact approved output and no suite.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `PhaseMetadata`, `_parse_phase_document`, `_safe_relative`, `_parse_command_suite`, `_TOKEN` from Task 1; `PlanMetadataError` from P02.
- Produces: `PlannedTask(id, deps, kind, batch, order, write_scope, outputs, verification_commands)` NamedTuple where `write_scope` and `outputs` are tuples of canonical strings; `parse_phase_plan(path) -> tuple[PhaseMetadata, tuple[PlannedTask, ...]]`; `_validate_acyclic_dependencies(dependencies, *, error_type, subject)`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 2 tests
# --------------------------------------------------------------------------

def test_task_metadata_parses_all_declared_fields(tmp_path):
    plan = write_phase_plan(
        tmp_path,
        task_block("T1", write_scope="file:src/a.py,tree:docs")
        + task_block(
            "T2", deps="T1", kind="artifact", batch="b2", order=2,
            write_scope="tree:docs", outputs="docs/report.md",
        ),
    )
    _, tasks = state.parse_phase_plan(plan)
    assert [task.id for task in tasks] == ["T1", "T2"]
    assert tasks[0].kind == "source"
    assert tasks[0].write_scope == ("file:src/a.py", "tree:docs")
    assert tasks[0].outputs == ()
    assert tasks[0].verification_commands == (
        "python3 -m pytest tests -k T1 -q",
    )
    assert tasks[1].kind == "artifact"
    assert tasks[1].deps == ("T1",)
    assert tasks[1].order == 2
    assert tasks[1].outputs == ("docs/report.md",)
    assert tasks[1].verification_commands == ()


def test_task_metadata_rejects_reordered_keys(tmp_path):
    block = (
        "## Task T1\n\n"
        "<!-- pipeline-auto-task: id=T1; kind=source; deps=none; batch=b1; "
        "order=1; write_scope=file:src/a.py; outputs=none -->\n"
        '<!-- pipeline-auto-task-suite: id=T1; commands=["a"] -->\n'
    )
    plan = write_phase_plan(tmp_path, block)
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


def test_task_metadata_must_immediately_follow_its_heading(tmp_path):
    block = (
        "## Task T1\n\nSome prose first.\n\n"
        "<!-- pipeline-auto-task: id=T1; deps=none; kind=source; batch=b1; "
        "order=1; write_scope=file:src/a.py; outputs=none -->\n"
        '<!-- pipeline-auto-task-suite: id=T1; commands=["a"] -->\n'
    )
    plan = write_phase_plan(tmp_path, block)
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


@pytest.mark.parametrize(
    "scope",
    ["src/a.py", "glob:src/*.py", "file:/etc/passwd", "file:../a.py",
     "tree:", "file:src/*.py"],
)
def test_write_scope_must_be_typed_and_canonical(tmp_path, scope):
    plan = write_phase_plan(tmp_path, task_block("T1", write_scope=scope))
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


def test_source_task_may_not_declare_outputs(tmp_path):
    plan = write_phase_plan(
        tmp_path, task_block("T1", kind="source", outputs="src/a.py")
    )
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


def test_artifact_task_must_declare_outputs(tmp_path):
    plan = write_phase_plan(
        tmp_path, task_block("T1", kind="artifact", outputs="none")
    )
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


def test_artifact_output_outside_its_write_scope_is_rejected(tmp_path):
    plan = write_phase_plan(
        tmp_path,
        task_block("T1", kind="artifact", write_scope="tree:docs",
                   outputs="reports/out.md"),
    )
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


def test_source_task_requires_one_adjacent_verification_suite(tmp_path):
    block = (
        "## Task T1\n\n"
        "<!-- pipeline-auto-task: id=T1; deps=none; kind=source; batch=b1; "
        "order=1; write_scope=file:src/a.py; outputs=none -->\n"
    )
    plan = write_phase_plan(tmp_path, block)
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


def test_artifact_task_may_not_carry_a_source_task_suite(tmp_path):
    block = (
        "## Task T1\n\n"
        "<!-- pipeline-auto-task: id=T1; deps=none; kind=artifact; batch=b1; "
        "order=1; write_scope=tree:docs; outputs=docs/a.md -->\n"
        '<!-- pipeline-auto-task-suite: id=T1; commands=["a"] -->\n'
    )
    plan = write_phase_plan(tmp_path, block)
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


def test_duplicate_task_ids_are_rejected(tmp_path):
    plan = write_phase_plan(tmp_path, task_block("T1") + task_block("T1", order=2))
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


def test_unknown_and_self_dependencies_are_rejected(tmp_path):
    for deps in ("T9", "T1"):
        plan = write_phase_plan(tmp_path, task_block("T1", deps=deps))
        with pytest.raises(state.PlanMetadataError):
            state.parse_phase_plan(plan)


def test_cyclic_dependencies_are_rejected(tmp_path):
    plan = write_phase_plan(
        tmp_path,
        task_block("T1", deps="T2", write_scope="file:src/a.py")
        + task_block("T2", deps="T1", order=2, write_scope="file:src/b.py"),
    )
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(plan)


def test_phase_plan_task_count_is_bounded(tmp_path):
    empty = write_phase_plan(tmp_path, "\nNo tasks here.\n", name="empty.md")
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(empty)
    thirteen = "".join(
        task_block(f"T{index}", order=index, write_scope=f"file:src/a{index}.py")
        for index in range(1, 14)
    )
    overfull = write_phase_plan(tmp_path, thirteen, name="overfull.md")
    with pytest.raises(state.PlanMetadataError):
        state.parse_phase_plan(overfull)


def test_task_order_must_be_a_positive_integer(tmp_path):
    for order in ("0", "-1", "one"):
        block = (
            "## Task T1\n\n"
            f"<!-- pipeline-auto-task: id=T1; deps=none; kind=source; batch=b1; "
            f"order={order}; write_scope=file:src/a.py; outputs=none -->\n"
            '<!-- pipeline-auto-task-suite: id=T1; commands=["a"] -->\n'
        )
        plan = write_phase_plan(tmp_path, block, name=f"order-{order}.md")
        with pytest.raises(state.PlanMetadataError):
            state.parse_phase_plan(plan)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'parse_phase_plan'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`, and replace the stub `_parse_phase_document` from Task 1 with the version below:

```python
_TASK_METADATA = re.compile(
    r"<!-- pipeline-auto-task: id=([^;]+); deps=([^;]+); kind=([^;]+); "
    r"batch=([^;]+); order=([^;]+); write_scope=([^;]+); outputs=([^;]+) -->\Z"
)
_TASK_SUITE = re.compile(
    r"<!-- pipeline-auto-task-suite: id=([^;]+); commands=(.+) -->\Z"
)

TASK_KINDS = ("source", "artifact")
MAX_TASKS_PER_PHASE = 12


class PlannedTask(NamedTuple):
    id: str
    deps: tuple[str, ...]
    kind: str
    batch: str
    order: int
    write_scope: tuple[str, ...]
    outputs: tuple[str, ...]
    verification_commands: tuple[str, ...]


def _validate_acyclic_dependencies(dependencies, *, error_type, subject) -> None:
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


def _parse_write_scope(raw: str) -> tuple[tuple[str, ...], list]:
    canonical: list[str] = []
    parsed: list[tuple[str, PurePosixPath]] = []
    for scope in raw.split(","):
        if ":" not in scope:
            raise PlanMetadataError("write scope must be typed as file: or tree:")
        scope_type, raw_path = scope.split(":", 1)
        if scope_type not in {"file", "tree"}:
            raise PlanMetadataError(f"unsupported write scope type: {scope_type!r}")
        path = _safe_relative(raw_path)
        canonical.append(f"{scope_type}:{path.as_posix()}")
        parsed.append((scope_type, path))
    if len(set(canonical)) != len(canonical):
        raise PlanMetadataError("duplicate write scope entry")
    return tuple(canonical), parsed


def _parse_task(lines: list[str], index: int) -> PlannedTask:
    match = _TASK_METADATA.fullmatch(lines[index])
    if match is None:
        raise PlanMetadataError("task metadata keys are missing, unknown, or reordered")
    task_id, deps_raw, kind, batch, order_raw, scopes_raw, outputs_raw = match.groups()
    previous = next(
        (candidate for candidate in reversed(lines[:index]) if candidate.strip()), ""
    )
    if not re.fullmatch(rf"#{{2,6}} .*\b{re.escape(task_id)}\b.*", previous):
        raise PlanMetadataError(
            f"task metadata for {task_id} must immediately follow its task heading"
        )
    if (
        kind not in TASK_KINDS
        or not _TOKEN.fullmatch(task_id)
        or not _TOKEN.fullmatch(batch)
    ):
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

    write_scope, parsed_scopes = _parse_write_scope(scopes_raw)
    outputs_list = () if outputs_raw == "none" else tuple(outputs_raw.split(","))
    if (kind == "source") != (not outputs_list):
        raise PlanMetadataError(
            "source declares outputs=none; artifact names its exact approved outputs"
        )
    outputs: list[str] = []
    for raw_output in outputs_list:
        output = _safe_relative(raw_output)
        if not any(
            (scope_type == "file" and output == scope)
            or (scope_type == "tree" and scope in output.parents)
            for scope_type, scope in parsed_scopes
        ):
            raise PlanMetadataError(
                f"artifact output is outside its write scope: {raw_output}"
            )
        outputs.append(output.as_posix())

    suite_candidates = [
        candidate for candidate in lines[index + 1:index + 2]
        if candidate.startswith("<!-- pipeline-auto-task-suite:")
    ]
    if kind == "source":
        if len(suite_candidates) != 1:
            raise PlanMetadataError(
                f"source task {task_id} needs one adjacent verification suite"
            )
        suite = _TASK_SUITE.fullmatch(suite_candidates[0])
        if suite is None or suite.group(1) != task_id:
            raise PlanMetadataError("task suite identity must match task metadata")
        commands = _parse_command_suite(suite.group(2))
    else:
        if suite_candidates:
            raise PlanMetadataError(
                "artifact tasks use exact outputs, not a source-task suite"
            )
        commands = ()
    return PlannedTask(
        task_id, deps, kind, batch, order, write_scope, tuple(outputs), commands
    )


def _parse_phase_document(path) -> tuple[PhaseMetadata, tuple[PlannedTask, ...]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    metadata = _phase_header(lines)
    tasks = [
        _parse_task(lines, index)
        for index, line in enumerate(lines)
        if line.startswith("<!-- pipeline-auto-task:")
    ]
    if not 1 <= len(tasks) <= MAX_TASKS_PER_PHASE:
        raise PlanMetadataError(
            f"phase plan must contain between 1 and {MAX_TASKS_PER_PHASE} tasks"
        )
    ids = [task.id for task in tasks]
    if len(ids) != len(set(ids)):
        raise PlanMetadataError("duplicate task id")
    known = set(ids)
    if any(
        dependency not in known or dependency == task.id
        for task in tasks
        for dependency in task.deps
    ):
        raise PlanMetadataError("unknown or self dependency")
    _validate_acyclic_dependencies(
        {task.id: task.deps for task in tasks},
        error_type=PlanMetadataError,
        subject="task",
    )
    return metadata, tuple(tasks)


def parse_phase_plan(path) -> tuple[PhaseMetadata, tuple[PlannedTask, ...]]:
    """Return one approved phase plan's immutable metadata and task definitions."""
    return _parse_phase_document(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): parse strict task metadata and typed write scopes"
```

---

### Task 3: `scopes_overlap` — the ancestor rule (fault F1)

Two scopes conflict for equal file paths, equal or ancestor tree paths, or a tree path equal to or containing a file path. Implemented as plain equality, `tree:src` and `file:src/a.py` reserve together and two implementers write the same file. Spare capacity never overrides a conflict.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `_safe_relative`, `PlanMetadataError`.
- Produces: `scopes_overlap(a: str, b: str) -> bool`; `_scope_parts(scope) -> tuple[str, PurePosixPath]`; `_path_in_scope(path: str, scope: str) -> bool`; `_scope_sets_overlap(left, right) -> bool`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 3 tests -- fault F1
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("file:src/a.py", "file:src/a.py"),
        ("tree:src", "file:src/a.py"),          # the fault equality misses
        ("file:src/a.py", "tree:src"),          # and its mirror
        ("tree:src", "tree:src/deep/nested"),
        ("tree:src/deep/nested", "tree:src"),
        ("tree:src", "tree:src"),
        ("tree:src/pkg", "file:src/pkg/mod/a.py"),
        ("tree:src/a.py", "file:src/a.py"),     # a tree naming exactly one file
    ],
)
def test_overlapping_scopes_conflict(left, right):
    assert state.scopes_overlap(left, right) is True
    assert state.scopes_overlap(right, left) is True


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("file:src/a.py", "file:src/b.py"),
        ("tree:src", "tree:docs"),
        ("tree:src", "file:docs/a.md"),
        ("tree:source", "file:src/a.py"),       # prefix-of-a-name is not ancestry
        ("tree:src/pkg", "file:src/pkgx/a.py"),
        ("file:src/a.py", "tree:src/a.py/deep"),
    ],
)
def test_disjoint_scopes_do_not_conflict(left, right):
    assert state.scopes_overlap(left, right) is False
    assert state.scopes_overlap(right, left) is False


@pytest.mark.parametrize("scope", ["src/a.py", "glob:src", "file:../a", "file:"])
def test_scopes_overlap_rejects_untyped_or_unsafe_scopes(scope):
    with pytest.raises(state.PlanMetadataError):
        state.scopes_overlap(scope, "file:src/a.py")


def test_scope_sets_overlap_finds_a_single_conflicting_pair():
    left = ("file:src/a.py", "tree:docs")
    right = ("file:src/b.py", "file:docs/index.md")
    assert state._scope_sets_overlap(left, right) is True
    assert state._scope_sets_overlap(left, ("file:src/b.py", "tree:reports")) is False


@pytest.mark.parametrize(
    ("path", "scope", "expected"),
    [
        ("src/a.py", "file:src/a.py", True),
        ("src/a.py", "file:src/b.py", False),
        ("src/a.py", "tree:src", True),
        ("src/deep/a.py", "tree:src", True),
        ("srcx/a.py", "tree:src", False),
        ("src", "tree:src", True),
    ],
)
def test_path_in_scope(path, scope, expected):
    assert state._path_in_scope(path, scope) is expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -k scope -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'scopes_overlap'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: typed write-scope algebra
#
# Equality alone is WRONG: tree:src and file:src/a.py would then reserve
# together and two implementers would write the same file. The ancestor branch
# is the whole point of this function.
# ---------------------------------------------------------------------------

def _scope_parts(scope: str) -> tuple[str, PurePosixPath]:
    if not isinstance(scope, str) or ":" not in scope:
        raise PlanMetadataError(f"write scope must be typed: {scope!r}")
    scope_type, raw_path = scope.split(":", 1)
    if scope_type not in {"file", "tree"}:
        raise PlanMetadataError(f"unsupported write scope type: {scope_type!r}")
    return scope_type, _safe_relative(raw_path)


def scopes_overlap(a: str, b: str) -> bool:
    """Return whether two typed write scopes claim any common repository path."""
    kind_a, path_a = _scope_parts(a)
    kind_b, path_b = _scope_parts(b)
    if kind_a == "file" and kind_b == "file":
        return path_a == path_b
    if kind_a == "tree" and kind_b == "tree":
        return path_a == path_b or path_a in path_b.parents or path_b in path_a.parents
    tree, other = (path_a, path_b) if kind_a == "tree" else (path_b, path_a)
    return tree == other or tree in other.parents


def _scope_sets_overlap(left, right) -> bool:
    return any(scopes_overlap(one, two) for one in left for two in right)


def _path_in_scope(path: str, scope: str) -> bool:
    kind, scope_path = _scope_parts(scope)
    candidate = _safe_relative(path)
    if kind == "file":
        return candidate == scope_path
    return candidate == scope_path or scope_path in candidate.parents
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): carry the ancestor branch in scope conflict detection"
```

---

### Task 4: Worker-result template and codec — the reversed status semantics (fault F5)

The vocabulary is unchanged from `superb:pipeline`. The routing is not. `NEEDS_CONTEXT` and `PLAN_CONFLICT` raise a quorum question and therefore **must** carry a resolvable, digest-bound `question_record`; `BLOCKED` still halts and must carry a `blocking_reason`. The codec enforces this at parse time, so a malformed result cannot even be published.

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/templates/worker-result.md`
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `TASK_KINDS` (Task 2), `TrackerValidationError` (P02).
- Produces: `WORKER_RESULT_MARKER`; `COMPLETION_STATUSES`, `QUORUM_STATUSES`, `HALT_STATUSES`, `WORKER_STATUSES`; `WORKER_RESULT_FIELDS`; `render_worker_result(result: dict) -> str`; `parse_worker_result(text: str) -> dict`; `_digest_reference(value) -> tuple[str, str]`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 4 tests -- fault F5
# --------------------------------------------------------------------------

DIGEST = "a" * 64


def worker_result(**overrides) -> dict:
    result = {
        "run_id": "run-1",
        "task_id": "T1",
        "attempt": 1,
        "owner": "impl-1",
        "kind": "source",
        "status": "DONE",
        "source_ref": "b" * 40,
        "commits": ("b" * 40,),
        "artifacts": (),
        "tests": ("python3 -m pytest tests -k T1 -q",),
        "evidence": (f"docs/superpowers/runs/run-1/evidence/T1.md#sha256={DIGEST}",),
        "concerns": "-",
        "question_record": "-",
        "blocking_reason": "-",
        "checkpoints": (),
    }
    result.update(overrides)
    return result


def test_worker_result_round_trips(tmp_path):
    original = worker_result(
        checkpoints=(
            {
                "id": "c1",
                "status": "complete",
                "evidence": f"docs/superpowers/runs/run-1/evidence/T1.md#sha256={DIGEST}",
            },
        )
    )
    text = state.render_worker_result(original)
    assert text.startswith(state.WORKER_RESULT_MARKER)
    assert state.parse_worker_result(text) == original


def test_worker_result_field_order_is_pinned(tmp_path):
    text = state.render_worker_result(worker_result())
    rows = [
        line.split("|")[1].strip()
        for line in text.splitlines()
        if line.startswith("| ") and line.count("|") == 3
    ]
    assert rows[:2] == ["Field", "---"] or rows[0] == "Field"
    assert [row for row in rows if row in state.WORKER_RESULT_FIELDS] == list(
        state.WORKER_RESULT_FIELDS
    )


def test_worker_result_rejects_a_foreign_marker():
    text = state.render_worker_result(worker_result()).replace(
        state.WORKER_RESULT_MARKER, "<!-- pipeline-worker-result/v2 -->"
    )
    with pytest.raises(state.TrackerValidationError):
        state.parse_worker_result(text)


def test_worker_result_rejects_reordered_fields():
    text = state.render_worker_result(worker_result())
    lines = text.splitlines()
    owner = next(i for i, line in enumerate(lines) if line.startswith("| owner "))
    lines[owner], lines[owner - 1] = lines[owner - 1], lines[owner]
    with pytest.raises(state.TrackerValidationError):
        state.parse_worker_result("\n".join(lines) + "\n")


@pytest.mark.parametrize("status", ["NEEDS_CONTEXT", "PLAN_CONFLICT"])
def test_quorum_status_without_a_question_record_is_rejected(status):
    """F5: a quorum-raising result missing its question record is rejected,
    exactly as a result with a missing owner is rejected."""
    with pytest.raises(state.TrackerValidationError):
        state.render_worker_result(
            worker_result(status=status, question_record="-", source_ref="-",
                          commits=(), evidence=())
        )


@pytest.mark.parametrize("status", ["NEEDS_CONTEXT", "PLAN_CONFLICT"])
def test_quorum_status_with_a_digest_bound_question_record_is_accepted(status):
    result = worker_result(
        status=status,
        question_record=f"docs/superpowers/runs/run-1/questions/q1.md#sha256={DIGEST}",
        source_ref="-", commits=(), evidence=(),
    )
    assert state.parse_worker_result(state.render_worker_result(result)) == result


@pytest.mark.parametrize("status", ["NEEDS_CONTEXT", "PLAN_CONFLICT"])
def test_quorum_status_question_record_must_be_digest_bound(status):
    with pytest.raises(state.TrackerValidationError):
        state.render_worker_result(
            worker_result(status=status, source_ref="-", commits=(), evidence=(),
                          question_record="docs/superpowers/runs/run-1/questions/q1.md")
        )


def test_blocked_requires_a_blocking_reason_and_no_question_record():
    with pytest.raises(state.TrackerValidationError):
        state.render_worker_result(
            worker_result(status="BLOCKED", blocking_reason="-", source_ref="-",
                          commits=(), evidence=())
        )
    with pytest.raises(state.TrackerValidationError):
        state.render_worker_result(
            worker_result(
                status="BLOCKED",
                blocking_reason="no credential for the staging API",
                question_record=f"docs/q.md#sha256={DIGEST}",
                source_ref="-", commits=(), evidence=(),
            )
        )
    accepted = worker_result(
        status="BLOCKED", blocking_reason="no credential for the staging API",
        source_ref="-", commits=(), evidence=(),
    )
    assert state.parse_worker_result(state.render_worker_result(accepted)) == accepted


def test_completion_status_may_carry_neither_question_record_nor_blocking_reason():
    for field in ("question_record", "blocking_reason"):
        with pytest.raises(state.TrackerValidationError):
            state.render_worker_result(
                worker_result(**{field: f"docs/q.md#sha256={DIGEST}"
                                 if field == "question_record" else "why"})
            )


def test_status_vocabulary_is_exactly_five_values():
    assert state.WORKER_STATUSES == (
        "DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "PLAN_CONFLICT", "BLOCKED",
    )
    assert state.QUORUM_STATUSES == ("NEEDS_CONTEXT", "PLAN_CONFLICT")
    assert state.HALT_STATUSES == ("BLOCKED",)
    with pytest.raises(state.TrackerValidationError):
        state.render_worker_result(worker_result(status="OK"))


def test_worker_result_rejects_unsafe_scalars():
    for override in ({"owner": "impl|1"}, {"concerns": "a|b"}, {"attempt": 0},
                     {"attempt": "1"}, {"kind": "binary"}, {"run_id": ""}):
        with pytest.raises(state.TrackerValidationError):
            state.render_worker_result(worker_result(**override))


def test_worker_result_template_matches_the_codec_fields():
    template = (
        Path(state.__file__).resolve().parents[1] / "templates" / "worker-result.md"
    ).read_text(encoding="utf-8")
    assert template.startswith(state.WORKER_RESULT_MARKER)
    for field in state.WORKER_RESULT_FIELDS:
        assert f"| {field} | " in template
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -k worker_result -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'render_worker_result'`

- [ ] **Step 3: Write minimal implementation**

Create `plugins/superb/skills/pipeline-auto/templates/worker-result.md`:

```markdown
<!-- pipeline-auto-worker-result/v1 -->
# Pipeline Auto — Worker Result

## Result
| Field | Value |
| --- | --- |
| run_id | <run_id> |
| task_id | <task_id> |
| attempt | <positive_integer> |
| owner | <controller_assigned_owner> |
| kind | <source_or_artifact> |
| status | <DONE_DONE_WITH_CONCERNS_NEEDS_CONTEXT_PLAN_CONFLICT_or_BLOCKED> |
| source_ref | <full_source_head_sha_or_dash> |
| commits | <ordered_full_shas_or_dash> |
| artifacts | <exact_approved_outputs_or_dash> |
| tests | <exact_ordered_task_suite_or_dash> |
| evidence | <path#sha256=digest_list_or_dash> |
| concerns | <concerns_or_dash> |
| question_record | <path#sha256=digest_or_dash> |
| blocking_reason | <blocking_reason_or_dash> |

## Checkpoints
| ID | Status | Evidence |
| --- | --- | --- |
| <checkpoint_id> | <complete_in_progress_or_blocked> | <path#sha256=digest> |

`question_record` is REQUIRED for `NEEDS_CONTEXT` and `PLAN_CONFLICT`: those
statuses raise a quorum question, and a result that names no question record is
rejected. `blocking_reason` is REQUIRED for `BLOCKED`, which still halts the
run — three brains cannot conjure an API key. A completion status carries
neither.
```

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: immutable worker-result codec
#
# The status vocabulary is unchanged from superb:pipeline. The ROUTING is not:
# NEEDS_CONTEXT and PLAN_CONFLICT now raise a quorum question, so they must
# carry a resolvable digest-bound question record. Only BLOCKED still halts.
# ---------------------------------------------------------------------------

WORKER_RESULT_MARKER = "<!-- pipeline-auto-worker-result/v1 -->"

COMPLETION_STATUSES = ("DONE", "DONE_WITH_CONCERNS")
QUORUM_STATUSES = ("NEEDS_CONTEXT", "PLAN_CONFLICT")
HALT_STATUSES = ("BLOCKED",)
WORKER_STATUSES = COMPLETION_STATUSES + QUORUM_STATUSES + HALT_STATUSES

WORKER_RESULT_FIELDS = (
    "run_id", "task_id", "attempt", "owner", "kind", "status", "source_ref",
    "commits", "artifacts", "tests", "evidence", "concerns",
    "question_record", "blocking_reason",
)
_TUPLE_FIELDS = ("commits", "artifacts", "tests", "evidence")
_CHECKPOINT_STATES = ("complete", "in_progress", "blocked")
_DIGEST_REFERENCE = re.compile(r"(?P<path>[^#]+)#sha256=(?P<digest>[0-9a-f]{64})\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _table_safe(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value or "|" in value or "\n" in value:
        raise TrackerValidationError(f"{field} must be a nonempty table-safe string")
    return value


def _digest_reference(value: str) -> tuple[str, str]:
    match = _DIGEST_REFERENCE.fullmatch(_table_safe(value, field="reference"))
    if match is None:
        raise TrackerValidationError(
            f"reference must be <repository-relative-path>#sha256=<digest>: {value!r}"
        )
    return _safe_relative(match.group("path")).as_posix(), match.group("digest")


def _validate_worker_result(result: dict) -> dict:
    missing = [field for field in WORKER_RESULT_FIELDS if field not in result]
    if missing or "checkpoints" not in result:
        raise TrackerValidationError(f"worker result is missing fields: {missing}")
    for field in ("run_id", "task_id", "owner", "concerns"):
        _table_safe(result[field], field=field)
    if not _TOKEN.fullmatch(result["owner"]) or not _TOKEN.fullmatch(result["task_id"]):
        raise TrackerValidationError("owner and task_id must be identifier tokens")
    attempt = result["attempt"]
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise TrackerValidationError("attempt must be a positive integer")
    if result["kind"] not in TASK_KINDS:
        raise TrackerValidationError(f"unknown task kind: {result['kind']!r}")
    status = result["status"]
    if status not in WORKER_STATUSES:
        raise TrackerValidationError(f"unknown worker status: {status!r}")
    for field in _TUPLE_FIELDS:
        values = tuple(result[field])
        if any(not _table_safe(value, field=field) for value in values):
            raise TrackerValidationError(f"{field} entries must be table-safe")
        if len(set(values)) != len(values):
            raise TrackerValidationError(f"duplicate {field} entry")
    for reference in tuple(result["evidence"]):
        _digest_reference(reference)
    if result["source_ref"] != "-" and not _COMMIT.fullmatch(result["source_ref"]):
        raise TrackerValidationError("source_ref must be a full 40-hex commit or '-'")
    if any(not _COMMIT.fullmatch(commit) for commit in result["commits"]):
        raise TrackerValidationError("commits must be full 40-hex shas")

    question_record = result["question_record"]
    blocking_reason = _table_safe(result["blocking_reason"], field="blocking_reason")
    if status in QUORUM_STATUSES:
        if question_record == "-":
            raise TrackerValidationError(
                f"{status} raises a quorum question and must name a question record"
            )
        _digest_reference(question_record)
        if blocking_reason != "-":
            raise TrackerValidationError(
                f"{status} routes to a quorum, not a halt; blocking_reason must be '-'"
            )
    elif status in HALT_STATUSES:
        if blocking_reason == "-":
            raise TrackerValidationError("BLOCKED result needs a blocking reason")
        if question_record != "-":
            raise TrackerValidationError(
                "BLOCKED halts the run and must not name a question record"
            )
    else:
        if question_record != "-" or blocking_reason != "-":
            raise TrackerValidationError(
                "a completion status carries neither question record nor blocking reason"
            )

    for checkpoint in tuple(result["checkpoints"]):
        if set(checkpoint) != {"id", "status", "evidence"}:
            raise TrackerValidationError("checkpoint needs exactly id/status/evidence")
        if not _TOKEN.fullmatch(checkpoint["id"]):
            raise TrackerValidationError("checkpoint id must be an identifier token")
        if checkpoint["status"] not in _CHECKPOINT_STATES:
            raise TrackerValidationError(f"unknown checkpoint state: {checkpoint['status']!r}")
        _digest_reference(checkpoint["evidence"])
    return result


def _cell(value) -> str:
    if isinstance(value, (tuple, list)):
        return ",".join(value) if value else "-"
    return str(value)


def render_worker_result(result: dict) -> str:
    """Render one validated immutable worker result in canonical field order."""
    _validate_worker_result(result)
    lines = [
        WORKER_RESULT_MARKER,
        "# Pipeline Auto — Worker Result",
        "",
        "## Result",
        "| Field | Value |",
        "| --- | --- |",
    ]
    lines += [f"| {field} | {_cell(result[field])} |" for field in WORKER_RESULT_FIELDS]
    lines += ["", "## Checkpoints", "| ID | Status | Evidence |", "| --- | --- | --- |"]
    lines += [
        f"| {item['id']} | {item['status']} | {item['evidence']} |"
        for item in result["checkpoints"]
    ]
    return "\n".join(lines) + "\n"


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_worker_result(text: str) -> dict:
    """Parse a canonical worker result, rejecting a foreign or reordered document."""
    lines = text.splitlines()
    if not lines or lines[0] != WORKER_RESULT_MARKER:
        raise TrackerValidationError(
            "worker result marker is missing or foreign; the two formats do not "
            "interoperate"
        )
    rows = [_split_row(line) for line in lines if line.startswith("| ")]
    field_rows = [row for row in rows if len(row) == 2 and row[0] not in {"Field", "---"}]
    if [row[0] for row in field_rows] != list(WORKER_RESULT_FIELDS):
        raise TrackerValidationError(
            "worker result fields are missing, unknown, or reordered"
        )
    values = {row[0]: row[1] for row in field_rows}
    checkpoints = tuple(
        {"id": row[0], "status": row[1], "evidence": row[2]}
        for row in rows
        if len(row) == 3 and row[0] not in {"ID", "---"}
    )
    result = {field: values[field] for field in WORKER_RESULT_FIELDS}
    try:
        result["attempt"] = int(values["attempt"])
    except ValueError as exc:
        raise TrackerValidationError("attempt must be a positive integer") from exc
    for field in _TUPLE_FIELDS:
        raw = values[field]
        result[field] = () if raw == "-" else tuple(raw.split(","))
    result["checkpoints"] = checkpoints
    return _validate_worker_result(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/templates/worker-result.md \
        plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): require a question record on quorum-raising results"
```

---

### Task 5: Verification-evidence template and codec

A digest-bound typed PASS record is the only acceptable proof that a suite ran. It names the run, the subject, the attempt, the full tested commit, and the exact ordered command tuple. `outcome` is the literal `PASS`; there is no other legal value, because a non-PASS record is not evidence.

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/templates/verification-evidence.md`
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `_parse_command_suite`, `_safe_relative`, `_digest_reference`, `_COMMIT`, `_split_row`, `TrackerValidationError`.
- Produces: `EVIDENCE_MARKER`; `EVIDENCE_PURPOSES = ("task-test", "task-integration", "phase")`; `EVIDENCE_FIELDS`; `parse_verification_evidence(text: str) -> dict`; `resolve_evidence(run_dir, repo_dir, reference) -> dict` which resolves a `path#sha256=` reference, verifies the digest, and returns the parsed record.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 5 tests
# --------------------------------------------------------------------------

import hashlib


def evidence_text(**overrides) -> str:
    fields = {
        "purpose": "task-test",
        "run_id": "run-1",
        "subject": "task/T1",
        "attempt": "1",
        "code_state": "b" * 40,
        "outcome": "PASS",
        "commands": '["python3 -m pytest tests -k T1 -q"]',
        "environment": "python3.11-linux",
        "inputs": "-",
    }
    fields.update(overrides)
    rows = "\n".join(f"| {key} | {value} |" for key, value in fields.items())
    return (
        f"{state.EVIDENCE_MARKER}\n| Field | Value |\n| --- | --- |\n{rows}\n"
    )


def write_evidence(directory: Path, name: str = "T1.md", **overrides) -> str:
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    content = evidence_text(**overrides)
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return digest


def test_verification_evidence_round_trips():
    record = state.parse_verification_evidence(evidence_text())
    assert record["purpose"] == "task-test"
    assert record["subject"] == "task/T1"
    assert record["attempt"] == "1"
    assert record["code_state"] == "b" * 40
    assert record["commands"] == ("python3 -m pytest tests -k T1 -q",)


def test_verification_evidence_rejects_a_foreign_marker():
    text = evidence_text().replace(
        state.EVIDENCE_MARKER, "<!-- pipeline-verification-evidence/v2 -->"
    )
    with pytest.raises(state.TrackerValidationError):
        state.parse_verification_evidence(text)


@pytest.mark.parametrize(
    "override",
    [
        {"outcome": "FAIL"},
        {"outcome": "pass"},
        {"purpose": "remediation"},
        {"purpose": "anything"},
        {"code_state": "short"},
        {"commands": "[]"},
        {"commands": "not-json"},
        {"environment": "-"},
        {"subject": "T1"},
    ],
)
def test_verification_evidence_rejects_invalid_records(override):
    with pytest.raises(state.TrackerValidationError):
        state.parse_verification_evidence(evidence_text(**override))


def test_verification_evidence_rejects_reordered_fields():
    lines = evidence_text().splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("| outcome "))
    lines[index], lines[index - 1] = lines[index - 1], lines[index]
    with pytest.raises(state.TrackerValidationError):
        state.parse_verification_evidence("\n".join(lines) + "\n")


def test_resolve_evidence_verifies_the_digest(tmp_path):
    run_dir = tmp_path / "run"
    digest = write_evidence(run_dir / "evidence")
    record = state.resolve_evidence(run_dir, tmp_path, f"evidence/T1.md#sha256={digest}")
    assert record["subject"] == "task/T1"
    with pytest.raises(state.TrackerValidationError):
        state.resolve_evidence(run_dir, tmp_path, f"evidence/T1.md#sha256={'c' * 64}")
    with pytest.raises(state.TrackerValidationError):
        state.resolve_evidence(run_dir, tmp_path, f"evidence/absent.md#sha256={digest}")


def test_verification_evidence_template_matches_the_codec_fields():
    template = (
        Path(state.__file__).resolve().parents[1]
        / "templates" / "verification-evidence.md"
    ).read_text(encoding="utf-8")
    assert template.startswith(state.EVIDENCE_MARKER)
    for field in state.EVIDENCE_FIELDS:
        assert f"| {field} | " in template
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -k evidence -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'EVIDENCE_MARKER'`

- [ ] **Step 3: Write minimal implementation**

Create `plugins/superb/skills/pipeline-auto/templates/verification-evidence.md`:

```markdown
<!-- pipeline-auto-verification-evidence/v1 -->
| Field | Value |
| --- | --- |
| purpose | <task-test_task-integration_or_phase> |
| run_id | <run_id> |
| subject | <task_or_phase>/<stable-id> |
| attempt | <positive_integer_or_N/A> |
| code_state | <full_tested_commit> |
| outcome | PASS |
| commands | ["<exact-command>","<next-command>"] |
| environment | <applicable_environment_identity> |
| inputs | <artifact_JSON_path_sha256_array_or_dash> |

`outcome` has exactly one legal value. A record that is not a PASS is not
evidence, so it is never written. For `task-integration` the `code_state` is
the `--no-ff` merge commit, not the task branch tip.
```

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: digest-bound typed PASS evidence
# ---------------------------------------------------------------------------

import hashlib

EVIDENCE_MARKER = "<!-- pipeline-auto-verification-evidence/v1 -->"
EVIDENCE_PURPOSES = ("task-test", "task-integration", "phase")
EVIDENCE_FIELDS = (
    "purpose", "run_id", "subject", "attempt", "code_state", "outcome",
    "commands", "environment", "inputs",
)


def parse_verification_evidence(text: str) -> dict:
    """Parse one typed PASS record, rejecting a foreign or reordered document."""
    lines = text.splitlines()
    if not lines or lines[0] != EVIDENCE_MARKER:
        raise TrackerValidationError(
            "verification evidence marker is missing or foreign"
        )
    rows = [
        _split_row(line) for line in lines
        if line.startswith("| ") and line.count("|") == 3
    ]
    field_rows = [row for row in rows if row[0] not in {"Field", "---"}]
    if [row[0] for row in field_rows] != list(EVIDENCE_FIELDS):
        raise TrackerValidationError(
            "verification evidence fields are missing, unknown, or reordered"
        )
    record = {row[0]: row[1] for row in field_rows}
    if record["purpose"] not in EVIDENCE_PURPOSES:
        raise TrackerValidationError(f"unknown evidence purpose: {record['purpose']!r}")
    if record["outcome"] != "PASS":
        raise TrackerValidationError("a record that is not PASS is not evidence")
    if not _COMMIT.fullmatch(record["code_state"]):
        raise TrackerValidationError("code_state must be a full 40-hex commit")
    if "/" not in record["subject"] or not record["subject"].split("/", 1)[1]:
        raise TrackerValidationError("subject must be <kind>/<stable-id>")
    for field in ("run_id", "environment"):
        if record[field] in {"", "-"}:
            raise TrackerValidationError(f"{field} is required on evidence")
    if record["attempt"] != "N/A":
        try:
            if int(record["attempt"]) < 1:
                raise ValueError
        except ValueError as exc:
            raise TrackerValidationError(
                "evidence attempt must be a positive integer or N/A"
            ) from exc
    record["commands"] = _parse_command_suite(record["commands"])
    return record


def resolve_evidence(run_dir, repo_dir, reference: str) -> dict:
    """Resolve a digest-bound evidence reference and verify its content digest."""
    relative, digest = _digest_reference(reference)
    candidates = (Path(run_dir) / relative, Path(repo_dir) / relative)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        content = candidate.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise TrackerValidationError(
                f"evidence digest does not match its content: {reference}"
            )
        return parse_verification_evidence(content.decode("utf-8"))
    raise TrackerValidationError(f"evidence is missing: {reference}")
```

The `import hashlib` and `_parse_command_suite` reuse mean the module keeps one
import block at the top after refactoring; move all `import` statements to the
head of the file before committing.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/templates/verification-evidence.md \
        plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): add digest-bound typed PASS evidence codec"
```

---

### Task 6: Tracker accessors, Git helpers, and `reserve_task` — the slot cap (faults F1, F2)

This is the strongest test in the phase. `worker_limit - 3` is not a tuning knob: three slots are held for a quorum, and without the reserve a blocked task holds the slot needed to dispatch the brains that would unblock it, so the run deadlocks permanently. No existing test covers it, because `superb:pipeline` has no brains.

A blocked `[?]` task still occupies its implementation slot — the spec's rationale says so in as many words — so the cap counts `[~]` and `[?]` alike.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: P02's `initialize_run`, `validate_run`, `locked_tracker_update`; `parse_phase_plan`, `scopes_overlap`, `_scope_sets_overlap`, `TrackerValidationError`.
- Produces: `QUORUM_SLOT_RESERVE = 3`; `implementation_slot_cap(worker_limit: int) -> int`; `_run_field`, `_current_field`, `_task_row`, `_replace_task`, `_append_history`; `_implementation_owners(tracker) -> set[str]`; `_quorum_owners(tracker) -> set[str]`; `_active_owners(tracker) -> set[str]`; `_project_root(run_dir) -> Path`; `_git(repo, *args) -> bool`; `_git_out(repo, *args) -> str`; `_resolved_commit(repo, ref) -> str`; `_active_phase_plan(run_dir, tracker) -> Path`; `_approved_definition(run_dir, tracker, task_id) -> PlannedTask`; `reserve_task(run_dir, *, task_id, owner, attempt) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Run harness -- reused by tasks 6 through 12
# --------------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo), *args),
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    (repo / "src").mkdir()
    (repo / "src" / "seed.py").write_text("seed = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "seed")
    git(repo, "branch", "-f", "target", "HEAD")
    return repo


def make_run(tmp_path: Path, tasks_body: str, *, worker_limit: int = 4) -> tuple[Path, Path, Path]:
    """Return (repo, run_dir, phase_plan).

    NOTE: P02's initialize_run signature accepts no artifact references and
    seeds no task rows, so the harness writes `phase_plans`, the active phase,
    and the `## Tasks` rows through one explicit locked update. See
    "Unresolved" in the phase plan.
    """
    repo = make_repo(tmp_path)
    run_dir = repo / "docs" / "superpowers" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    plan = write_phase_plan(run_dir, tasks_body)
    state.initialize_run(
        run_dir, run_id="run-1", base_commit=git(repo, "rev-parse", "HEAD"),
        target_branch="target", worker_limit=worker_limit,
    )
    relative_plan = plan.relative_to(repo).as_posix()
    _, tasks = state.parse_phase_plan(plan)

    def mutate(tracker: dict) -> dict:
        tracker["run"]["phase_plans"] = relative_plan
        tracker["current"]["phase"] = "P04"
        tracker["phases"] = [{
            "id": "P04", "state": "active", "review_class": "required",
            "class_source": "plan", "ratchet": "-",
        }]
        tracker["tasks"] = [{
            "id": task.id, "state": "[ ]", "kind": task.kind, "owner": "-",
            "attempt": "-", "deps": ",".join(task.deps) or "-",
            "checkpoints": "-", "result": "-", "source_ref": "-", "commits": "-",
            "artifacts": "-", "integration": "-", "verification": "-",
            "question": "-", "provisional": "no",
        } for task in tasks]
        return tracker

    state.locked_tracker_update(run_dir, transition_id="seed-p04", mutate=mutate)
    return repo, run_dir, plan


def three_disjoint_tasks() -> str:
    return "".join(
        task_block(f"T{index}", order=index, batch=f"b{index}",
                   write_scope=f"file:src/a{index}.py")
        for index in range(1, 4)
    )


def open_quorum_row(run_dir: Path, owners=("brain-1", "brain-2", "brain-3")) -> None:
    """Stand in for P03's open_quorum: persist one in_flight record with three owners."""
    def mutate(tracker: dict) -> dict:
        tracker.setdefault("quorum", []).append(
            {"qid": "q0001", "state": "in_flight", "owners": ",".join(owners)}
        )
        return tracker

    state.locked_tracker_update(run_dir, transition_id="test-open-quorum", mutate=mutate)


def task_row(tracker: dict, task_id: str) -> dict:
    return next(row for row in tracker["tasks"] if row["id"] == task_id)


# --------------------------------------------------------------------------
# Task 6 tests -- faults F1 and F2
# --------------------------------------------------------------------------

def test_implementation_slot_cap_holds_three_slots_for_a_quorum():
    assert state.QUORUM_SLOT_RESERVE == 3
    assert state.implementation_slot_cap(4) == 1
    assert state.implementation_slot_cap(6) == 3
    assert state.implementation_slot_cap(10) == 7
    # Below four, the cap floors at one so tasks serialise and the brain slots
    # stay free. It never floors at zero: that would stop the run instead.
    assert state.implementation_slot_cap(3) == 1
    assert state.implementation_slot_cap(1) == 1


def test_worker_limit_four_reserves_exactly_one_task_and_a_quorum_still_fits(tmp_path):
    """F2: reserving up to worker_limit deadlocks the run permanently -- the
    blocked task holds the slot needed to dispatch the brains that unblock it."""
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=4)
    state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)

    with pytest.raises(state.TrackerValidationError) as excinfo:
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
    assert "worker_limit" in str(excinfo.value)

    tracker = state.validate_run(run_dir)
    assert [row["id"] for row in tracker["tasks"] if row["state"] == "[~]"] == ["T1"]
    assert state._implementation_owners(tracker) == {"impl-1"}

    # The three held slots are really available: a quorum opened afterwards
    # takes them and the run is at, not over, its limit.
    open_quorum_row(run_dir)
    tracker = state.validate_run(run_dir)
    assert state._quorum_owners(tracker) == {"brain-1", "brain-2", "brain-3"}
    assert len(state._active_owners(tracker)) == 4 == int(tracker["run"]["worker_limit"])

    with pytest.raises(state.TrackerValidationError):
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)


def test_worker_limit_six_reserves_three_tasks_then_refuses(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    for index in range(1, 4):
        state.reserve_task(run_dir, task_id=f"T{index}", owner=f"impl-{index}", attempt=1)
    tracker = state.validate_run(run_dir)
    assert len(state._implementation_owners(tracker)) == 3
    body = three_disjoint_tasks() + task_block(
        "T4", order=4, batch="b4", write_scope="file:src/a4.py"
    )
    repo2, run_dir2, _ = make_run(tmp_path / "second", body, worker_limit=6)
    for index in range(1, 4):
        state.reserve_task(run_dir2, task_id=f"T{index}", owner=f"impl-{index}", attempt=1)
    with pytest.raises(state.TrackerValidationError):
        state.reserve_task(run_dir2, task_id="T4", owner="impl-4", attempt=1)


def test_a_blocked_task_still_occupies_its_implementation_slot(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=4)
    state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)

    def block(tracker: dict) -> dict:
        row = task_row(tracker, "T1")
        row["state"] = "[?]"
        row["question"] = "quorum:docs/q.md#sha256=" + DIGEST
        return tracker

    state.locked_tracker_update(run_dir, transition_id="test-block", mutate=block)
    tracker = state.validate_run(run_dir)
    assert state._implementation_owners(tracker) == {"impl-1"}
    with pytest.raises(state.TrackerValidationError):
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)


def test_overlapping_scopes_never_reserve_together_even_with_spare_capacity(tmp_path):
    """F1: tree:src and file:src/a.py must not both be active."""
    body = (
        task_block("T1", order=1, batch="b1", write_scope="tree:src")
        + task_block("T2", order=2, batch="b2", write_scope="file:src/a.py")
    )
    repo, run_dir, _ = make_run(tmp_path, body, worker_limit=12)
    state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
    before = (run_dir / "progress.md").read_bytes()
    with pytest.raises(state.TrackerValidationError) as excinfo:
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
    assert "write scope" in str(excinfo.value)
    assert (run_dir / "progress.md").read_bytes() == before


def test_reservation_persists_the_baseline_for_a_source_task(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    target = git(repo, "rev-parse", "target")
    tracker = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
    row = task_row(tracker, "T1")
    assert row["state"] == "[~]"
    assert row["owner"] == "impl-1"
    assert row["attempt"] == "1"
    assert f"baseline:1@{target}" in row["checkpoints"]
    assert "started:1" in row["checkpoints"]


def test_artifact_task_reservation_records_no_baseline(tmp_path):
    body = task_block("T1", kind="artifact", write_scope="tree:docs",
                      outputs="docs/out.md")
    repo, run_dir, _ = make_run(tmp_path, body, worker_limit=6)
    tracker = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
    assert "baseline:" not in task_row(tracker, "T1")["checkpoints"]


def test_reserve_task_handles_the_first_start_only(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
    with pytest.raises(state.TrackerValidationError):
        state.reserve_task(run_dir, task_id="T1", owner="impl-9", attempt=2)


def test_reserve_task_refuses_an_incomplete_dependency(tmp_path):
    body = (
        task_block("T1", order=1, batch="b1", write_scope="file:src/a1.py")
        + task_block("T2", deps="T1", order=2, batch="b2",
                     write_scope="file:src/a2.py")
    )
    repo, run_dir, _ = make_run(tmp_path, body, worker_limit=8)
    with pytest.raises(state.TrackerValidationError) as excinfo:
        state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
    assert "dependency" in str(excinfo.value)


def test_reserve_task_rejects_a_reused_attempt_and_bad_identity(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    for kwargs in (
        {"task_id": "T1", "owner": "impl|1", "attempt": 1},
        {"task_id": "T1", "owner": "impl-1", "attempt": 0},
        {"task_id": "T1", "owner": "impl-1", "attempt": "1"},
        {"task_id": "TX", "owner": "impl-1", "attempt": 1},
    ):
        with pytest.raises(state.TrackerValidationError):
            state.reserve_task(run_dir, **kwargs)


def test_reserve_task_replay_is_inert(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    first = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
    snapshot = (run_dir / "progress.md").read_bytes()
    replay = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
    assert (run_dir / "progress.md").read_bytes() == snapshot
    assert task_row(replay, "T1")["attempt"] == task_row(first, "T1")["attempt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -k "slot or reserve or quorum" -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'QUORUM_SLOT_RESERVE'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: tracker accessors
#
# Every P04 read of the tracker dict goes through these five functions. If
# P02's shape differs from the documented assumption, this is the only code
# that changes.
# ---------------------------------------------------------------------------

import subprocess


def _run_field(tracker: dict, field: str) -> str:
    try:
        return tracker["run"][field]
    except (KeyError, TypeError) as exc:
        raise TrackerValidationError(f"tracker run field is missing: {field}") from exc


def _current_field(tracker: dict, field: str) -> str:
    try:
        return tracker["current"][field]
    except (KeyError, TypeError) as exc:
        raise TrackerValidationError(f"tracker current field is missing: {field}") from exc


def _task_row(tracker: dict, task_id: str) -> dict:
    for row in tracker.get("tasks", ()):
        if row["id"] == task_id:
            return row
    raise TrackerValidationError(f"unknown task: {task_id}")


def _replace_task(tracker: dict, replacement: dict) -> dict:
    tracker["tasks"] = [
        replacement if row["id"] == replacement["id"] else row
        for row in tracker["tasks"]
    ]
    return tracker


def _quorum_owners(tracker: dict) -> set[str]:
    owners: set[str] = set()
    for row in tracker.get("quorum", ()) or ():
        if row.get("state") != "in_flight":
            continue
        owners.update(
            value for value in str(row.get("owners", "-")).split(",")
            if value and value != "-"
        )
    return owners


def _csv(value: str) -> tuple[str, ...]:
    return () if value in {"", "-"} else tuple(value.split(","))


def _append_history(value: str, entry: str) -> str:
    return entry if value in {"", "-"} else f"{value},{entry}"


# ---------------------------------------------------------------------------
# P04: capacity arithmetic
#
# Three slots are held for a quorum. Reserving up to worker_limit deadlocks the
# run permanently: a blocked task holds the slot needed to dispatch the brains
# that would unblock it. A blocked [?] task therefore still occupies its slot.
# ---------------------------------------------------------------------------

QUORUM_SLOT_RESERVE = 3
_OCCUPYING_STATES = ("[~]", "[?]")


def implementation_slot_cap(worker_limit: int) -> int:
    """Return how many slots implementation tasks may occupy at once."""
    if not isinstance(worker_limit, int) or isinstance(worker_limit, bool) or worker_limit < 1:
        raise TrackerValidationError("worker_limit must be a positive integer")
    return max(1, worker_limit - QUORUM_SLOT_RESERVE)


def _implementation_owners(tracker: dict) -> set[str]:
    return {
        row["owner"] for row in tracker.get("tasks", ())
        if row["state"] in _OCCUPYING_STATES and row["owner"] != "-"
    }


def _active_owners(tracker: dict) -> set[str]:
    return _implementation_owners(tracker) | _quorum_owners(tracker)


# ---------------------------------------------------------------------------
# P04: Git facts
# ---------------------------------------------------------------------------

def _project_root(run_dir) -> Path:
    candidate = Path(run_dir).resolve()
    for directory in (candidate, *candidate.parents):
        if (directory / ".git").exists():
            return directory
    raise TrackerValidationError(f"run directory is not inside a repository: {run_dir}")


def _git(repo, *args: str) -> bool:
    return subprocess.run(
        ("git", "-C", str(repo), *args),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0


def _git_out(repo, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo), *args),
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise TrackerValidationError(
            f"git {' '.join(args)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout


def _resolved_commit(repo, ref: str) -> str:
    resolved = _git_out(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    if not _COMMIT.fullmatch(resolved):
        raise TrackerValidationError(f"reference did not resolve to one commit: {ref}")
    return resolved


# ---------------------------------------------------------------------------
# P04: approved task definitions
# ---------------------------------------------------------------------------

def _active_phase_plan(run_dir, tracker: dict) -> Path:
    paths = _csv(_run_field(tracker, "phase_plans"))
    phase_ids = [row["id"] for row in tracker.get("phases", ())]
    current = _current_field(tracker, "phase")
    if len(paths) != len(phase_ids) or current not in phase_ids:
        raise TrackerValidationError(
            "the current phase does not resolve to exactly one approved phase plan"
        )
    return _project_root(run_dir) / _safe_relative(paths[phase_ids.index(current)])


def _approved_definition(run_dir, tracker: dict, task_id: str) -> PlannedTask:
    _, tasks = parse_phase_plan(_active_phase_plan(run_dir, tracker))
    definition = next((task for task in tasks if task.id == task_id), None)
    if definition is None:
        raise TrackerValidationError(
            f"task {task_id} is not defined by the approved phase plan"
        )
    row = _task_row(tracker, task_id)
    if row["kind"] != definition.kind or _csv(row["deps"]) != definition.deps:
        raise TrackerValidationError(
            "task metadata does not match the authoritative approved plan"
        )
    return definition


def _require_dependencies_complete(tracker: dict, definition: PlannedTask) -> None:
    for dependency in definition.deps:
        if _task_row(tracker, dependency)["state"] != "[x]":
            raise TrackerValidationError(
                f"dependency {dependency} is not complete"
            )


def _require_no_scope_conflict(run_dir, tracker: dict, definition: PlannedTask) -> None:
    for row in tracker.get("tasks", ()):
        if row["id"] == definition.id or row["state"] not in _OCCUPYING_STATES:
            continue
        other = _approved_definition(run_dir, tracker, row["id"])
        if _scope_sets_overlap(definition.write_scope, other.write_scope):
            raise TrackerValidationError(
                f"write scope conflict: {definition.id} {definition.write_scope} "
                f"overlaps active {other.id} {other.write_scope}"
            )


def _require_capacity(tracker: dict, owner: str) -> None:
    limit = int(_run_field(tracker, "worker_limit"))
    cap = implementation_slot_cap(limit)
    owners = _implementation_owners(tracker)
    if owner not in owners and len(owners) + 1 > cap:
        raise TrackerValidationError(
            f"implementation slots exhausted: {len(owners)} of {cap} "
            f"(worker_limit {limit} minus {QUORUM_SLOT_RESERVE} held for a quorum)"
        )
    if len(_active_owners(tracker) | {owner}) > limit:
        raise TrackerValidationError(f"global worker_limit {limit} is exhausted")


def _require_fresh_attempt(row: dict, attempt: int) -> None:
    token = str(attempt)
    used = set(_csv(row["attempt"]))
    for history in (row["checkpoints"], row["result"]):
        for entry in _csv(history):
            used.update(re.findall(r"(?<![0-9])[0-9]+(?![0-9])", entry))
    if token in used:
        raise TrackerValidationError(f"task attempt {attempt} has already been used")


def _validate_assignment(owner: str, attempt: int) -> None:
    if not isinstance(owner, str) or not _TOKEN.fullmatch(owner) or "|" in owner:
        raise TrackerValidationError("owner must be a table-safe identifier token")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise TrackerValidationError("attempt must be a positive integer")


def reserve_task(run_dir, *, task_id: str, owner: str, attempt: int) -> dict:
    """Persist the first `[ ] -> [~]` assignment, with its baseline, before dispatch."""
    _validate_assignment(owner, attempt)

    def mutate(tracker: dict) -> dict:
        row = _task_row(tracker, task_id)
        if row["state"] != "[ ]":
            raise TrackerValidationError("reserve_task handles the first start only")
        definition = _approved_definition(run_dir, tracker, task_id)
        _require_dependencies_complete(tracker, definition)
        _require_fresh_attempt(row, attempt)
        _require_no_scope_conflict(run_dir, tracker, definition)
        _require_capacity(tracker, owner)
        checkpoint = f"started:{attempt}"
        if definition.kind == "source":
            baseline = _resolved_commit(
                _project_root(run_dir), _run_field(tracker, "target_branch")
            )
            checkpoint = f"{checkpoint},baseline:{attempt}@{baseline}"
        row = dict(row)
        row.update(
            state="[~]", owner=owner, attempt=str(attempt),
            checkpoints=_append_history(row["checkpoints"], checkpoint),
        )
        return _replace_task(tracker, row)

    return locked_tracker_update(
        run_dir, transition_id=f"reserve-{task_id}-{attempt}", mutate=mutate
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): hold three worker slots for a quorum when reserving tasks"
```

---

### Task 7: `resume_task`

An answered blocked attempt moves `[?] -> [~]`. The prior attempt must match, the new attempt must be distinct and unused, and `decision_ref` must resolve to an explicit applicable answer whose `Decision action` is `task.resume`. Context compaction or a restarted controller is not a blocked-task retry and creates no new attempt.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: everything Task 6 produced.
- Produces: `_decision_sections(text) -> dict[str, list[str]]`; `_validate_decision(run_dir, tracker, decision_ref, task_id) -> None`; `resume_task(run_dir, *, task_id, prior_attempt, new_owner, new_attempt, decision_ref) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 7 tests
# --------------------------------------------------------------------------

def write_decisions(run_dir: Path, body: str) -> None:
    path = run_dir / "decisions.md"
    path.write_text(body, encoding="utf-8")

    def mutate(tracker: dict) -> dict:
        tracker["run"]["decisions"] = "decisions.md"
        return tracker

    state.locked_tracker_update(run_dir, transition_id="test-decisions", mutate=mutate)


RESUME_DECISION = """# Decisions

## D-001
| Field | Value |
| --- | --- |
| Question | Which serialiser does T1 use? |
| Answer | The stdlib json module. |
| Provenance | quorum |
| Status | Adopted |
| Scope | T1 |
| Decision action | task.resume |
"""


def blocked_task(tmp_path: Path, worker_limit: int = 6) -> tuple[Path, Path]:
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=worker_limit)
    state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)

    def block(tracker: dict) -> dict:
        row = task_row(tracker, "T1")
        row["state"] = "[?]"
        row["question"] = f"quorum:docs/q.md#sha256={DIGEST}"
        row["checkpoints"] = state._append_history(row["checkpoints"], "blocked:1")
        return tracker

    state.locked_tracker_update(run_dir, transition_id="test-block", mutate=block)
    write_decisions(run_dir, RESUME_DECISION)
    return repo, run_dir


def test_resume_task_moves_an_answered_block_to_active(tmp_path):
    repo, run_dir = blocked_task(tmp_path)
    tracker = state.resume_task(
        run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
        new_attempt=2, decision_ref="D-001",
    )
    row = task_row(tracker, "T1")
    assert row["state"] == "[~]"
    assert row["owner"] == "impl-2"
    assert row["attempt"] == "2"
    assert "resumed:1->2@D-001" in row["checkpoints"]
    assert row["question"] == "resolved:D-001"


def test_resume_task_records_a_fresh_baseline_for_a_source_task(tmp_path):
    repo, run_dir = blocked_task(tmp_path)
    (repo / "src" / "later.py").write_text("later = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "target moved")
    git(repo, "branch", "-f", "target", "HEAD")
    moved = git(repo, "rev-parse", "target")
    tracker = state.resume_task(
        run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
        new_attempt=2, decision_ref="D-001",
    )
    assert f"baseline:2@{moved}" in task_row(tracker, "T1")["checkpoints"]


def test_resume_task_requires_the_matching_blocked_attempt(tmp_path):
    repo, run_dir = blocked_task(tmp_path)
    with pytest.raises(state.TrackerValidationError):
        state.resume_task(
            run_dir, task_id="T1", prior_attempt=9, new_owner="impl-2",
            new_attempt=2, decision_ref="D-001",
        )


def test_resume_task_requires_a_distinct_unused_attempt(tmp_path):
    repo, run_dir = blocked_task(tmp_path)
    for new_attempt in (1,):
        with pytest.raises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=new_attempt, decision_ref="D-001",
            )


def test_resume_task_rejects_a_decision_without_the_task_resume_action(tmp_path):
    repo, run_dir = blocked_task(tmp_path)
    write_decisions(run_dir, RESUME_DECISION.replace("task.resume", "none"))
    with pytest.raises(state.TrackerValidationError) as excinfo:
        state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref="D-001",
        )
    assert "task.resume" in str(excinfo.value)


def test_resume_task_rejects_a_decision_scoped_to_another_task(tmp_path):
    repo, run_dir = blocked_task(tmp_path)
    write_decisions(run_dir, RESUME_DECISION.replace("| Scope | T1 |", "| Scope | T3 |"))
    with pytest.raises(state.TrackerValidationError):
        state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref="D-001",
        )


def test_resume_task_rejects_a_superseded_or_missing_decision(tmp_path):
    repo, run_dir = blocked_task(tmp_path)
    write_decisions(run_dir, RESUME_DECISION.replace("Adopted", "Superseded"))
    with pytest.raises(state.TrackerValidationError):
        state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref="D-001",
        )
    write_decisions(run_dir, RESUME_DECISION)
    with pytest.raises(state.TrackerValidationError):
        state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref="D-404",
        )


def test_resume_task_refuses_an_active_task(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
    write_decisions(run_dir, RESUME_DECISION)
    with pytest.raises(state.TrackerValidationError):
        state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref="D-001",
        )


def test_resume_task_still_honours_the_implementation_slot_cap(tmp_path):
    repo, run_dir = blocked_task(tmp_path, worker_limit=4)
    write_decisions(run_dir, RESUME_DECISION)
    open_quorum_row(run_dir)
    with pytest.raises(state.TrackerValidationError):
        state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref="D-001",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -k resume -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'resume_task'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: resume an answered block
# ---------------------------------------------------------------------------

RESUME_ACTION = "task.resume"
_DECISION_HEADING = re.compile(r"^## ((?:H|Q|D)-[0-9A-Za-z]+)(?:\s|$)")


def _decision_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _DECISION_HEADING.match(line)
        if match:
            current = match.group(1)
            if current in sections:
                raise TrackerValidationError(f"duplicate decision {current}")
            sections[current] = []
        elif current is not None and not line.startswith("## "):
            sections[current].append(line)
    return sections


def _decision_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines:
        if not line.startswith("| "):
            continue
        cells = _split_row(line)
        if len(cells) == 2 and cells[0] not in {"Field", "---"}:
            fields[cells[0]] = cells[1]
    return fields


def _validate_decision(run_dir, tracker: dict, decision_ref: str, task_id: str) -> None:
    path = _project_root(run_dir) / _safe_relative(_run_field(tracker, "decisions"))
    if not path.is_file():
        path = Path(run_dir) / _safe_relative(_run_field(tracker, "decisions"))
    try:
        sections = _decision_sections(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TrackerValidationError(f"decisions file is unreadable: {exc}") from exc
    if decision_ref not in sections:
        raise TrackerValidationError(f"decision {decision_ref} does not resolve")
    fields = _decision_fields(sections[decision_ref])
    if fields.get("Status") != "Adopted":
        raise TrackerValidationError(f"decision {decision_ref} is not Adopted")
    if fields.get("Decision action") != RESUME_ACTION:
        raise TrackerValidationError(
            f"decision {decision_ref} does not carry 'Decision action: {RESUME_ACTION}'"
        )
    if task_id not in _csv(fields.get("Scope", "-")):
        raise TrackerValidationError(
            f"decision {decision_ref} is not scoped to task {task_id}"
        )
    if not fields.get("Answer", "").strip() or fields["Answer"] == "-":
        raise TrackerValidationError(
            f"decision {decision_ref} carries no explicit answer"
        )


def resume_task(run_dir, *, task_id: str, prior_attempt: int, new_owner: str,
                new_attempt: int, decision_ref: str) -> dict:
    """Persist an answered `[?] -> [~]` assignment before redispatch."""
    _validate_assignment(new_owner, new_attempt)
    if not isinstance(prior_attempt, int) or isinstance(prior_attempt, bool) or prior_attempt < 1:
        raise TrackerValidationError("prior_attempt must be a positive integer")
    if not decision_ref or "|" in decision_ref:
        raise TrackerValidationError("decision_ref is required and must be table-safe")
    if new_attempt == prior_attempt:
        raise TrackerValidationError("the new attempt must be distinct")
    marker = f"resumed:{prior_attempt}->{new_attempt}@{decision_ref}"

    def mutate(tracker: dict) -> dict:
        row = _task_row(tracker, task_id)
        if row["state"] != "[?]" or row["attempt"] != str(prior_attempt):
            raise TrackerValidationError(
                "resume requires the matching blocked attempt"
            )
        _require_fresh_attempt(row, new_attempt)
        _validate_decision(run_dir, tracker, decision_ref, task_id)
        definition = _approved_definition(run_dir, tracker, task_id)
        _require_dependencies_complete(tracker, definition)
        _require_no_scope_conflict(run_dir, tracker, definition)
        _require_capacity(tracker, new_owner)
        checkpoint = marker
        if definition.kind == "source":
            baseline = _resolved_commit(
                _project_root(run_dir), _run_field(tracker, "target_branch")
            )
            checkpoint = f"{checkpoint},baseline:{new_attempt}@{baseline}"
        row = dict(row)
        row.update(
            state="[~]", owner=new_owner, attempt=str(new_attempt),
            checkpoints=_append_history(row["checkpoints"], checkpoint),
            question=f"resolved:{decision_ref}",
        )
        return _replace_task(tracker, row)

    return locked_tracker_update(
        run_dir,
        transition_id=f"resume-{task_id}-{prior_attempt}-{new_attempt}-{decision_ref}",
        mutate=mutate,
    )
```

`_require_capacity` counts the resuming owner against the same
`worker_limit - 3` cap: an answered block does not buy extra capacity, so a run
whose brains are still in flight waits rather than over-subscribing.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): gate task resume on an explicit task.resume decision"
```

---

### Task 8: `verify_source_range` — the baseline-anchored range proof (faults F3, F4)

A source task completes implementation only when its resolved source head contains exactly the complete, ordered, nonempty `baseline..source-head` range, every changed path is inside its approved typed write scope, and no commit in the range is empty. The baseline is the one persisted at reservation. `HEAD~1` is the wrong baseline: it silently truncates a multi-commit task to its last commit, and every earlier commit escapes the scope check entirely.

The implementation range is linear by construction — one worktree per implementer, merged only at integration — so a merge commit inside the range is a contradiction, not a variation.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `_git`, `_git_out`, `_resolved_commit`, `_path_in_scope`, `_scope_parts`, `_COMMIT`.
- Produces: `verify_source_range(repo, *, baseline, head, scopes) -> dict` returning `{"baseline", "head", "commits", "changed_paths"}`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 8 tests -- faults F3 and F4
# --------------------------------------------------------------------------

def commit_file(repo: Path, relative: str, text: str, message: str) -> str:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def three_commit_branch(tmp_path: Path) -> tuple[Path, str, tuple[str, ...]]:
    repo = make_repo(tmp_path)
    baseline = git(repo, "rev-parse", "target")
    git(repo, "checkout", "-q", "-b", "task/T1", "target")
    commits = tuple(
        commit_file(repo, "src/a1.py", f"value = {index}\n", f"step {index}")
        for index in range(1, 4)
    )
    return repo, baseline, commits


def test_verify_source_range_accepts_the_complete_ordered_range(tmp_path):
    repo, baseline, commits = three_commit_branch(tmp_path)
    proof = state.verify_source_range(
        repo, baseline=baseline, head=commits[-1], scopes=["file:src/a1.py"]
    )
    assert proof["baseline"] == baseline
    assert proof["head"] == commits[-1]
    assert proof["commits"] == commits
    assert proof["changed_paths"] == ("src/a1.py",)


def test_head_tilde_one_baseline_truncates_a_multi_commit_task(tmp_path):
    """F3: HEAD~1 is not the review baseline. It silently drops the earlier
    commits, which then escape every scope and range check."""
    repo, baseline, commits = three_commit_branch(tmp_path)
    persisted = state.verify_source_range(
        repo, baseline=baseline, head=commits[-1], scopes=["file:src/a1.py"]
    )
    truncated = state.verify_source_range(
        repo, baseline=commits[-2], head=commits[-1], scopes=["file:src/a1.py"]
    )
    assert len(persisted["commits"]) == 3
    assert len(truncated["commits"]) == 1
    assert truncated["commits"] != persisted["commits"]
    assert set(truncated["commits"]) < set(persisted["commits"])


def test_verify_source_range_rejects_an_empty_commit(tmp_path):
    """F4: no diff is not an artifact completion and not a reason for an
    empty commit."""
    repo, baseline, commits = three_commit_branch(tmp_path)
    git(repo, "commit", "-q", "--allow-empty", "-m", "nothing happened")
    head = git(repo, "rev-parse", "HEAD")
    with pytest.raises(state.TrackerValidationError) as excinfo:
        state.verify_source_range(
            repo, baseline=baseline, head=head, scopes=["file:src/a1.py"]
        )
    assert "empty commit" in str(excinfo.value)


def test_verify_source_range_rejects_an_empty_range(tmp_path):
    repo, baseline, _ = three_commit_branch(tmp_path)
    with pytest.raises(state.TrackerValidationError) as excinfo:
        state.verify_source_range(
            repo, baseline=baseline, head=baseline, scopes=["file:src/a1.py"]
        )
    assert "empty" in str(excinfo.value)


def test_verify_source_range_rejects_a_head_that_does_not_descend_the_baseline(tmp_path):
    """F4: an unrelated commit proves nothing about this task."""
    repo, baseline, commits = three_commit_branch(tmp_path)
    git(repo, "checkout", "-q", "--orphan", "unrelated")
    git(repo, "rm", "-rqf", ".")
    unrelated = commit_file(repo, "other.py", "x = 1\n", "unrelated history")
    with pytest.raises(state.TrackerValidationError) as excinfo:
        state.verify_source_range(
            repo, baseline=baseline, head=unrelated, scopes=["file:other.py"]
        )
    assert "ancestor" in str(excinfo.value)


def test_verify_source_range_rejects_a_merge_inside_the_implementation_range(tmp_path):
    """One worktree per implementer means the implementation range is linear.
    A merge inside it belongs to integration, not to the task."""
    repo, baseline, commits = three_commit_branch(tmp_path)
    git(repo, "checkout", "-q", "-b", "side", baseline)
    commit_file(repo, "src/side.py", "side = 1\n", "side work")
    git(repo, "checkout", "-q", "task/T1")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    head = git(repo, "rev-parse", "HEAD")
    with pytest.raises(state.TrackerValidationError) as excinfo:
        state.verify_source_range(
            repo, baseline=baseline, head=head,
            scopes=["file:src/a1.py", "file:src/side.py"],
        )
    assert "linear" in str(excinfo.value)


def test_verify_source_range_rejects_an_out_of_scope_path(tmp_path):
    repo, baseline, commits = three_commit_branch(tmp_path)
    head = commit_file(repo, "src/escaped.py", "escaped = 1\n", "out of scope")
    with pytest.raises(state.TrackerValidationError) as excinfo:
        state.verify_source_range(
            repo, baseline=baseline, head=head, scopes=["file:src/a1.py"]
        )
    assert "src/escaped.py" in str(excinfo.value)


def test_verify_source_range_accepts_a_tree_scope_covering_every_path(tmp_path):
    repo, baseline, commits = three_commit_branch(tmp_path)
    head = commit_file(repo, "src/deep/nested.py", "nested = 1\n", "in a tree scope")
    proof = state.verify_source_range(
        repo, baseline=baseline, head=head, scopes=["tree:src"]
    )
    assert "src/deep/nested.py" in proof["changed_paths"]


def test_verify_source_range_rejects_untyped_scopes(tmp_path):
    repo, baseline, commits = three_commit_branch(tmp_path)
    with pytest.raises(state.PlanMetadataError):
        state.verify_source_range(
            repo, baseline=baseline, head=commits[-1], scopes=["src/a1.py"]
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -k source_range -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'verify_source_range'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: the baseline-anchored source-range proof
#
# The baseline is the one PERSISTED AT RESERVATION. HEAD~1 silently truncates a
# multi-commit task to its last commit and every earlier commit escapes the
# scope check.
# ---------------------------------------------------------------------------

def _commit_parents(repo, commit: str) -> tuple[str, ...]:
    fields = _git_out(repo, "rev-list", "--parents", "-n", "1", commit).split()
    return tuple(fields[1:])


def verify_source_range(repo, *, baseline: str, head: str, scopes: list) -> dict:
    """Prove one task's implementation range against its persisted baseline."""
    repo = Path(repo)
    scopes = tuple(scopes)
    if not scopes:
        raise TrackerValidationError("a source range needs at least one write scope")
    for scope in scopes:
        _scope_parts(scope)                      # rejects untyped/unsafe scopes
    base = _resolved_commit(repo, baseline)
    tip = _resolved_commit(repo, head)
    if base == tip:
        raise TrackerValidationError(
            "source range is empty: the head equals the recorded baseline"
        )
    if not _git(repo, "merge-base", "--is-ancestor", base, tip):
        raise TrackerValidationError(
            "the recorded baseline is not an ancestor of the source head; an "
            "unrelated commit proves nothing about this task"
        )
    commits = tuple(
        line for line in
        _git_out(repo, "rev-list", "--reverse", f"{base}..{tip}").splitlines() if line
    )
    if not commits:
        raise TrackerValidationError("source range contains no commits")
    for commit in commits:
        parents = _commit_parents(repo, commit)
        if len(parents) != 1:
            raise TrackerValidationError(
                f"the implementation range must be linear; {commit} has "
                f"{len(parents)} parents and merges belong to integration"
            )
        if not _git_out(repo, "diff", "--name-only", parents[0], commit).strip():
            raise TrackerValidationError(
                f"source range contains an empty commit: {commit}"
            )
    changed = tuple(
        line for line in
        _git_out(repo, "diff", "--name-only", base, tip).splitlines() if line
    )
    if not changed:
        raise TrackerValidationError("source range changed no repository path")
    outside = tuple(
        path for path in changed
        if not any(_path_in_scope(path, scope) for scope in scopes)
    )
    if outside:
        raise TrackerValidationError(
            f"source range changed paths outside its approved write scope "
            f"{scopes}: {', '.join(outside)}"
        )
    return {
        "baseline": base, "head": tip, "commits": commits, "changed_paths": changed,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): prove source ranges against the reserved baseline"
```

---

### Task 9: `publish_worker_result`

A worker publishes its own immutable result and nothing else. Publication is atomic and no-clobber: republishing byte-identical content is an idempotent no-op, and any other content at the same path is conflicting evidence, not an update.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: P02's `publish_immutable`; `render_worker_result`.
- Produces: `worker_result_path(run_dir, *, task_id, attempt) -> Path`; `publish_worker_result(run_dir, *, result: dict) -> str` returning the repository-relative published path.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 9 tests
# --------------------------------------------------------------------------

def test_publish_worker_result_writes_a_canonical_immutable_file(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    relative = state.publish_worker_result(run_dir, result=worker_result())
    published = repo / relative
    assert published.is_file()
    assert state.parse_worker_result(published.read_text(encoding="utf-8")) \
        == worker_result()
    assert "agent-output" in relative
    assert not Path(relative).is_absolute()


def test_publish_worker_result_is_idempotent_for_identical_content(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    first = state.publish_worker_result(run_dir, result=worker_result())
    before = (repo / first).read_bytes()
    second = state.publish_worker_result(run_dir, result=worker_result())
    assert second == first
    assert (repo / first).read_bytes() == before


def test_publish_worker_result_refuses_to_overwrite_conflicting_content(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    relative = state.publish_worker_result(run_dir, result=worker_result())
    before = (repo / relative).read_bytes()
    with pytest.raises(state.TrackerValidationError):
        state.publish_worker_result(
            run_dir, result=worker_result(concerns="changed my mind")
        )
    assert (repo / relative).read_bytes() == before


def test_publish_worker_result_validates_before_writing_anything(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    with pytest.raises(state.TrackerValidationError):
        state.publish_worker_result(
            run_dir,
            result=worker_result(status="NEEDS_CONTEXT", question_record="-",
                                 source_ref="-", commits=(), evidence=()),
        )
    assert not (run_dir / "agent-output").exists()


def test_worker_result_path_is_attempt_scoped(tmp_path):
    repo, run_dir, _ = make_run(tmp_path, three_disjoint_tasks(), worker_limit=6)
    first = state.worker_result_path(run_dir, task_id="T1", attempt=1)
    second = state.worker_result_path(run_dir, task_id="T1", attempt=2)
    assert first != second
    assert first.parent == second.parent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -k publish -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'publish_worker_result'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: immutable result publication
#
# The one helper a worker may call. Only the controller imports.
# ---------------------------------------------------------------------------

def worker_result_path(run_dir, *, task_id: str, attempt: int) -> Path:
    if not _TOKEN.fullmatch(task_id):
        raise TrackerValidationError("task_id must be an identifier token")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise TrackerValidationError("attempt must be a positive integer")
    return Path(run_dir) / "agent-output" / task_id.replace("/", "-") / f"attempt-{attempt}.md"


def publish_worker_result(run_dir, *, result: dict) -> str:
    """Publish one immutable attempt result and return its repository-relative path."""
    content = render_worker_result(result)          # validates before any write
    path = worker_result_path(
        run_dir, task_id=result["task_id"], attempt=result["attempt"]
    )
    existing = None
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != content:
            raise TrackerValidationError(
                f"a conflicting immutable result already exists at {path}"
            )
    if existing is None:
        publish_immutable(str(path), content)
    return path.resolve().relative_to(_project_root(run_dir)).as_posix()
```

`publish_immutable` is P02's no-clobber atomic publication. The pre-check above
turns its clobber refusal into the documented distinction between an idempotent
replay and conflicting evidence.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): publish attempt-scoped immutable worker results"
```

---
