# P04 Task Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pipeline-auto task lifecycle — reserve, resume, typed write scopes, immutable worker-result identity, the baseline-anchored source-range proof, integration ancestry, and file-first reconciliation — inside `pipeline_auto_state.py`, together with the strict phase-plan metadata grammar parser and the two result/evidence templates.

**Architecture:** P04 appends a task-lifecycle layer to the single state module P02 created. Every durable mutation goes through P02's `locked_tracker_update`; P04 supplies only `mutate` callables and pure validators, and reads tracker geometry through P02's `section_columns` / `append_row` / `repo_root`. The phase-plan metadata grammar is a strict, key-order-pinned HTML-comment format so a plan is machine-readable structure rather than prose a worker may reinterpret. Two semantics change from `superb:pipeline`: `NEEDS_CONTEXT` and `PLAN_CONFLICT` now route to a quorum instead of halting, and implementation tasks may never occupy more than `worker_limit - 3` slots so the three brain slots that would unblock them always exist.

**Tech Stack:** Python 3.11 standard library only, **tests included**. `pytest` is **not installed** and must not be used — tests are `unittest.TestCase`, run under `python3 -m unittest discover`. Markdown for all durable state. `git` invoked through `subprocess` for every commit fact.

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
- **Python standard library only, tests included. `pytest` is NOT installed on this machine.** Tests are `unittest.TestCase`; the discovery command is the one in the verification suite below.
- No absolute home-directory paths in any committed file. Repository-relative paths only.
- No push, no publish, no PR, no merge into `main`/`master`.
- The repository root is the one **recorded at init** and read back with P02's `repo_root(tracker)`. It is **never** derived from `run_dir` depth.
- Worktree granularity: one per concurrently dispatched implementer, merged `--no-ff` in task order. `--no-ff` preserves ancestry by construction, so the no-squash rule holds.
- **A merge conflict at integration is a hard stop.** Under typed write-scope validation a conflict should be impossible, so a conflict is evidence the scope declaration was wrong — not something to auto-redo past. Redoing the task alone papers over a broken declaration and lets the next task hit the same collision. The run stops and reports which two scopes collided.

## What changes from `superb:pipeline`

Read these six before writing any code. They are the point of the phase, and each is a named fault below.

1. **Status semantics reverse for two of five.** The vocabulary is unchanged — `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `PLAN_CONFLICT`, `BLOCKED` — but in `superb:pipeline` all three non-DONE statuses mean "block and ask the human". In pipeline-auto, `NEEDS_CONTEXT` and `PLAN_CONFLICT` mean "raise a quorum question". Only `BLOCKED` still means halt, because three brains cannot conjure an API key or a permission.
2. **A quorum-raising result must carry a question record reference.** A `NEEDS_CONTEXT` or `PLAN_CONFLICT` result without a resolvable, digest-bound `question_record` is **rejected**, exactly as a result with a missing owner is rejected today.
3. **Implementation tasks may reserve at most `worker_limit - 3` slots.** Three are held for a quorum. Without this the run deadlocks permanently: a blocked task holds the slot needed to dispatch the brains that would unblock it. Below `worker_limit = 4` the cap floors at one, so tasks serialise and the brain slots stay free.
4. **The review baseline is the one persisted at reservation**, never `HEAD~1`. `HEAD~1` silently truncates a multi-commit task to its last commit and the earlier commits escape every scope and range check.
5. **A merge conflict at integration is a hard stop, not an abort-and-redo-alone.** The error names both task ids and both declared scopes.
6. **The ancestry predicate is written for the per-implementer-worktree topology.** Clause 1 is unchanged: a task's recorded commits are ancestors of its own branch tip. Clause 2 becomes: the task branch tip is an ancestor of the `--no-ff` merge commit, **and** the merge commit is an ancestor of the target branch. Clause 3 is unchanged but its code state is the **merge commit**. `--no-ff` is load-bearing, not stylistic — a fast-forward collapses the merge commit and destroys the boundary clause 2 checks, so the predicate asserts two parents. Because the merge commit exists, `git rev-list --reverse <merge>^1..<merge>^2` yields the exact task commit set directly, without baseline bookkeeping.

## Named faults this phase's tests must catch

| # | Fault | Caught by |
| --- | --- | --- |
| F1 | `scopes_overlap` implemented as plain equality, so `tree:src` and `file:src/a.py` reserve together and two implementers write the same file | Task 3, Task 6 |
| F2 | Reserving up to `worker_limit` instead of `worker_limit - 3`, deadlocking the run | Task 6 |
| F3 | Using `HEAD~1` as the review baseline instead of the baseline persisted at reservation | Task 8, Task 10 |
| F4 | Accepting a source range containing a pre-baseline, extra, unrelated, or empty commit | Task 8, Task 10 |
| F5 | A quorum-raising result with no question record reference | Task 4, Task 10 |
| F6 | A result whose `run_id + task_id + attempt + owner` does not exactly match the persisted assignment | Task 10 |
| F7 | Treating a missing worker result as evidence of completion, or as grounds to repeat the work | Task 12 |
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

P04 puts its tests in their own file rather than appending to `tests/test_pipeline_auto_state.py`. The master plan's verification suite discovers the whole `tests/` directory, so a second file is inside the named structure, and it keeps P03's and P04's write scopes disjoint — which is exactly the property `scopes_overlap` exists to enforce.

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
                   target_branch: str, worker_limit: int, repo_root: str) -> dict: ...
def locked_tracker_update(run_dir: str, *, transition_id: str, mutate) -> dict: ...
def publish_immutable(path: str, content: str) -> str: ...   # returns the sha256 hex digest
def derive_next_action(tracker: dict) -> str: ...

SECTIONS: dict[str, tuple[str, ...]]
def section_columns(name: str) -> tuple[str, ...]: ...
def append_row(tracker: dict, section: str, row: dict) -> dict: ...
def repo_root(tracker: dict) -> str: ...
def classify_filesystem(path: str) -> str: ...
```

Three consequences P04 must honour:

- `publish_immutable` returns a **sha256 hex digest**, not a path. `publish_worker_result` computes its own return path and uses the returned digest as the result's content identity.
- The repository root comes from `repo_root(tracker)`. P04 contains **no** `.git`-walking function.
- P02 owns every section's column grammar. P04 writes rows through `append_row` and reads column names through `section_columns`, so `## Tasks` and `## Quorum` cannot drift from their validator.

**Assumed tracker dict shape.** P02's signatures name `dict` but not its nesting. P04 touches the tracker through exactly five private accessors — `_run_field`, `_current_field`, `_task_row`, `_replace_task`, `_quorum_owners`. If P02's shape differs, those five functions are the only code that changes.

```python
tracker = {
    "run": {"run_id", "base_commit", "target_branch", "worker_limit",
            "repo_root", "revision", "spec", "master_plan", "phase_plans",
            "decisions", "findings"},              # str -> str
    "current": {"stage", "phase", "next_action"},  # str -> str
    "phases": [ {...} ],   # columns from section_columns("Phases")
    "tasks":  [ {...} ],   # columns from section_columns("Tasks")
    "quorum": [ {...} ],   # columns from section_columns("Quorum")
}
```

Every cell is a table-safe string; `-` is the empty marker; multi-valued cells are comma-separated. `worker_limit` is read with `int(...)`.

## Interfaces P04 produces

Implemented exactly as the master plan states them:

```python
def reserve_task(run_dir: str, *, task_id: str, owner: str, attempt: int) -> dict: ...
def resume_task(run_dir: str, *, task_id: str, prior_attempt: int,
                new_owner: str, new_attempt: int, decision_ref: str) -> dict: ...
def scopes_overlap(a: str, b: str) -> bool: ...
def parse_plan_metadata(path: str) -> dict: ...
def publish_worker_result(run_dir: str, *, result: dict) -> str: ...
def import_worker_result(run_dir: str, *, result_path: str) -> dict: ...
def verify_source_range(repo: str, *, baseline: str, head: str, scopes: list) -> dict: ...
def reconcile_run(run_dir: str) -> dict: ...
```

Plus `templates/worker-result.md` and `templates/verification-evidence.md`.

## Phase verification suite

The exact ordered command tuple for P04:

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The second command must print nothing. Every task below re-runs the first command, narrowed with `unittest`'s own `-k` filter. There is no `pytest` anywhere in this plan.

---

### Task 1: Phase-plan header grammar and the test harness

The phase-plan metadata comment is what stops a plan being prose a worker reinterprets. The grammar is strict and its key **order is pinned**: a reordered, renamed, or missing key is a `PlanMetadataError`, not a best-effort parse. `review_class` replaces v2's `review_gate` and carries the review-intensity dial value.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Create: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `PlanMetadataError` from P02.
- Produces: `REVIEW_CLASSES`; `_TOKEN`; `_parse_command_suite(raw) -> tuple[str, ...]`; `_safe_relative(value) -> PurePosixPath`; `_parse_phase_header(lines) -> dict` with keys `id`, `deps`, `review_class`, `review_reason`, `commands`; and the test harness `phase_header`, `task_block`, `write_phase_plan`, `TempDirTestCase`.

- [ ] **Step 1: Write the failing test**

Create `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
"""P04 task-lifecycle tests for pipeline-auto.

Standard library only: pytest is not installed. Run with

    python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v
"""
from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_auto_state.py"
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
    commands: str = '["python3 -m unittest discover -s tests -t ."]',
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
        suite = commands or f'["python3 -m unittest -k {task_id}"]'
        text += f"<!-- pipeline-auto-task-suite: id={task_id}; commands={suite} -->\n"
    return text + "\nProse describing the task.\n\n"


def write_phase_plan(directory, body: str, *, header: str | None = None,
                     name: str = "phase-04.md") -> Path:
    path = Path(directory) / name
    path.write_text(
        "# Phase 04 plan\n\n" + (header or phase_header()) + "\n" + body,
        encoding="utf-8",
    )
    return path


class TempDirTestCase(unittest.TestCase):
    """Give every test its own scratch directory without pytest fixtures."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)


# --------------------------------------------------------------------------
# Task 1 tests -- fault F8
# --------------------------------------------------------------------------

class PhaseHeaderGrammarTests(TempDirTestCase):

    def _expect_rejection(self, plan: Path) -> None:
        before = plan.read_bytes()
        with self.assertRaises(state.PlanMetadataError):
            state._parse_phase_header(plan.read_text(encoding="utf-8").splitlines())
        self.assertEqual(plan.read_bytes(), before)

    def test_parses_pinned_key_order(self):
        plan = write_phase_plan(self.tmp, task_block("T1"))
        header = state._parse_phase_header(
            plan.read_text(encoding="utf-8").splitlines()
        )
        self.assertEqual(header["id"], "P04")
        self.assertEqual(header["deps"], ())
        self.assertEqual(header["review_class"], "required")
        self.assertEqual(header["review_reason"],
                         "task lifecycle is security-relevant")
        self.assertEqual(header["commands"],
                         ("python3 -m unittest discover -s tests -t .",))

    def test_rejects_reordered_keys(self):
        header = (
            "<!-- pipeline-auto-phase: id=P04; review_class=required; deps=none; "
            "review_reason=swapped -->\n"
            '<!-- pipeline-auto-phase-suite: id=P04; commands=["a"] -->\n'
        )
        self._expect_rejection(
            write_phase_plan(self.tmp, task_block("T1"), header=header)
        )

    def test_rejects_the_v2_review_gate_key(self):
        header = (
            "<!-- pipeline-auto-phase: id=P04; deps=none; review_gate=required; "
            "review_reason=old grammar -->\n"
            '<!-- pipeline-auto-phase-suite: id=P04; commands=["a"] -->\n'
        )
        self._expect_rejection(
            write_phase_plan(self.tmp, task_block("T1"), header=header)
        )

    def test_rejects_unknown_review_class(self):
        self._expect_rejection(
            write_phase_plan(self.tmp, task_block("T1"),
                             header=phase_header(review_class="medium"))
        )

    def test_rejects_empty_review_reason(self):
        self._expect_rejection(
            write_phase_plan(self.tmp, task_block("T1"),
                             header=phase_header(review_reason="   "))
        )

    def test_suite_must_immediately_follow_phase_metadata(self):
        header = (
            "<!-- pipeline-auto-phase: id=P04; deps=none; review_class=required; "
            "review_reason=split -->\n\n"
            '<!-- pipeline-auto-phase-suite: id=P04; commands=["a"] -->\n'
        )
        self._expect_rejection(
            write_phase_plan(self.tmp, task_block("T1"), header=header)
        )

    def test_suite_identity_must_match_phase_metadata(self):
        header = (
            "<!-- pipeline-auto-phase: id=P04; deps=none; review_class=required; "
            "review_reason=mismatch -->\n"
            '<!-- pipeline-auto-phase-suite: id=P05; commands=["a"] -->\n'
        )
        self._expect_rejection(
            write_phase_plan(self.tmp, task_block("T1"), header=header)
        )

    def test_metadata_must_precede_the_first_section(self):
        path = self.tmp / "late.md"
        path.write_text(
            "# Phase 04 plan\n\n## Overview\n\n" + phase_header() + "\n"
            + task_block("T1"),
            encoding="utf-8",
        )
        self._expect_rejection(path)

    def test_metadata_must_occur_exactly_once(self):
        self._expect_rejection(
            write_phase_plan(self.tmp, task_block("T1"),
                             header=phase_header() + phase_header())
        )

    def test_command_suite_rejects_malformed_values(self):
        for commands in ("[]", '["a","a"]', '["a",""]', '["a|b"]', '"a"', '["a"'):
            with self.subTest(commands=commands):
                self._expect_rejection(
                    write_phase_plan(self.tmp, task_block("T1"), name="c.md",
                                     header=phase_header(commands=commands))
                )

    def test_safe_relative_rejects_unsupported_paths(self):
        for value in ("/abs/path", "../escape", "a/../b", "src/*.py", "",
                      "a\\b", "src/./a"):
            with self.subTest(value=value):
                with self.assertRaises(state.PlanMetadataError):
                    state._safe_relative(value)

    def test_safe_relative_accepts_a_canonical_repository_relative_path(self):
        self.assertEqual(state._safe_relative("src/pkg/a.py").as_posix(),
                         "src/pkg/a.py")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k PhaseHeaderGrammarTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute '_parse_phase_header'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`. Move every `import` to the module head before committing; they are shown inline here so each block is self-contained.

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

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")

_PHASE_METADATA = re.compile(
    r"<!-- pipeline-auto-phase: id=([^;]+); deps=([^;]+); "
    r"review_class=([^;]+); review_reason=(.+) -->\Z"
)
_PHASE_SUITE = re.compile(
    r"<!-- pipeline-auto-phase-suite: id=([^;]+); commands=(.+) -->\Z"
)

REVIEW_CLASSES = ("required", "final-only")


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


def _parse_phase_header(lines: list[str]) -> dict:
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
    return {
        "id": phase.group(1),
        "deps": deps,
        "review_class": phase.group(3),
        "review_reason": phase.group(4),
        "commands": _parse_command_suite(suite.group(2)),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k PhaseHeaderGrammarTests`
Expected: OK — 12 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): pin phase-plan header grammar with review_class"
```

---

### Task 2: Task metadata grammar and `parse_plan_metadata`

A task definition declares `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, and `outputs` in that exact order, immediately beneath its own heading. `kind` is `source` or `artifact`; a worker cannot change it because its implementation happened to produce no diff. A source task declares `outputs=none` and one adjacent verification suite; an artifact task names every exact approved output and no suite.

`parse_plan_metadata(path) -> dict` is the public entry point named in the master plan's P04 block. It returns `{"phase": {...}, "tasks": [{...}, ...]}`.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `_parse_phase_header`, `_safe_relative`, `_parse_command_suite`, `_TOKEN`, `PlanMetadataError`.
- Produces: `TASK_KINDS = ("source", "artifact")`; `MAX_TASKS_PER_PHASE = 12`; `_validate_acyclic_dependencies(dependencies, *, error_type, subject)`; `_parse_write_scope(raw)`; `_parse_task_metadata(lines, index) -> dict`; `parse_plan_metadata(path) -> dict` whose `tasks` entries carry keys `id`, `deps`, `kind`, `batch`, `order`, `write_scope`, `outputs`, `commands`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`, above the `if __name__` guard (every later task appends in the same place):

```python
# --------------------------------------------------------------------------
# Task 2 tests -- fault F8
# --------------------------------------------------------------------------

class TaskMetadataGrammarTests(TempDirTestCase):

    def _expect_rejection(self, body: str, *, name: str = "reject.md") -> None:
        plan = write_phase_plan(self.tmp, body, name=name)
        before = plan.read_bytes()
        with self.assertRaises(state.PlanMetadataError):
            state.parse_plan_metadata(plan)
        self.assertEqual(plan.read_bytes(), before)

    def test_parses_all_declared_fields(self):
        plan = write_phase_plan(
            self.tmp,
            task_block("T1", write_scope="file:src/a.py,tree:docs")
            + task_block("T2", deps="T1", kind="artifact", batch="b2", order=2,
                         write_scope="tree:docs", outputs="docs/report.md"),
        )
        metadata = state.parse_plan_metadata(plan)
        self.assertEqual(metadata["phase"]["review_class"], "required")
        tasks = metadata["tasks"]
        self.assertEqual([task["id"] for task in tasks], ["T1", "T2"])
        self.assertEqual(tasks[0]["kind"], "source")
        self.assertEqual(tasks[0]["write_scope"], ("file:src/a.py", "tree:docs"))
        self.assertEqual(tasks[0]["outputs"], ())
        self.assertEqual(tasks[0]["commands"], ("python3 -m unittest -k T1",))
        self.assertEqual(tasks[1]["kind"], "artifact")
        self.assertEqual(tasks[1]["deps"], ("T1",))
        self.assertEqual(tasks[1]["order"], 2)
        self.assertEqual(tasks[1]["outputs"], ("docs/report.md",))
        self.assertEqual(tasks[1]["commands"], ())

    def test_rejects_reordered_keys(self):
        self._expect_rejection(
            "## Task T1\n\n"
            "<!-- pipeline-auto-task: id=T1; kind=source; deps=none; batch=b1; "
            "order=1; write_scope=file:src/a.py; outputs=none -->\n"
            '<!-- pipeline-auto-task-suite: id=T1; commands=["a"] -->\n'
        )

    def test_metadata_must_immediately_follow_its_heading(self):
        self._expect_rejection(
            "## Task T1\n\nSome prose first.\n\n"
            "<!-- pipeline-auto-task: id=T1; deps=none; kind=source; batch=b1; "
            "order=1; write_scope=file:src/a.py; outputs=none -->\n"
            '<!-- pipeline-auto-task-suite: id=T1; commands=["a"] -->\n'
        )

    def test_write_scope_must_be_typed_and_canonical(self):
        for scope in ("src/a.py", "glob:src/*.py", "file:/etc/passwd",
                      "file:../a.py", "tree:", "file:src/*.py"):
            with self.subTest(scope=scope):
                self._expect_rejection(task_block("T1", write_scope=scope))

    def test_duplicate_write_scope_entries_are_rejected(self):
        self._expect_rejection(
            task_block("T1", write_scope="file:src/a.py,file:src/a.py")
        )

    def test_source_task_may_not_declare_outputs(self):
        self._expect_rejection(task_block("T1", kind="source", outputs="src/a.py"))

    def test_artifact_task_must_declare_outputs(self):
        self._expect_rejection(task_block("T1", kind="artifact", outputs="none"))

    def test_artifact_output_outside_its_write_scope_is_rejected(self):
        self._expect_rejection(
            task_block("T1", kind="artifact", write_scope="tree:docs",
                       outputs="reports/out.md")
        )

    def test_source_task_requires_one_adjacent_verification_suite(self):
        self._expect_rejection(
            "## Task T1\n\n"
            "<!-- pipeline-auto-task: id=T1; deps=none; kind=source; batch=b1; "
            "order=1; write_scope=file:src/a.py; outputs=none -->\n"
        )

    def test_artifact_task_may_not_carry_a_source_task_suite(self):
        self._expect_rejection(
            "## Task T1\n\n"
            "<!-- pipeline-auto-task: id=T1; deps=none; kind=artifact; batch=b1; "
            "order=1; write_scope=tree:docs; outputs=docs/a.md -->\n"
            '<!-- pipeline-auto-task-suite: id=T1; commands=["a"] -->\n'
        )

    def test_duplicate_task_ids_are_rejected(self):
        self._expect_rejection(task_block("T1") + task_block("T1", order=2))

    def test_unknown_and_self_dependencies_are_rejected(self):
        for deps in ("T9", "T1"):
            with self.subTest(deps=deps):
                self._expect_rejection(task_block("T1", deps=deps),
                                       name=f"dep-{deps}.md")

    def test_cyclic_dependencies_are_rejected(self):
        self._expect_rejection(
            task_block("T1", deps="T2", write_scope="file:src/a.py")
            + task_block("T2", deps="T1", order=2, write_scope="file:src/b.py")
        )

    def test_task_count_is_bounded(self):
        self._expect_rejection("\nNo tasks here.\n", name="empty.md")
        self._expect_rejection(
            "".join(
                task_block(f"T{index}", order=index,
                           write_scope=f"file:src/a{index}.py")
                for index in range(1, 14)
            ),
            name="overfull.md",
        )

    def test_order_must_be_a_positive_integer(self):
        for order in ("0", "-1", "one"):
            with self.subTest(order=order):
                self._expect_rejection(
                    "## Task T1\n\n"
                    f"<!-- pipeline-auto-task: id=T1; deps=none; kind=source; "
                    f"batch=b1; order={order}; write_scope=file:src/a.py; "
                    "outputs=none -->\n"
                    '<!-- pipeline-auto-task-suite: id=T1; commands=["a"] -->\n',
                    name=f"order-{order}.md",
                )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k TaskMetadataGrammarTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'parse_plan_metadata'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

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


def _parse_write_scope(raw: str):
    canonical: list[str] = []
    parsed: list = []
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


def _parse_task_metadata(lines: list[str], index: int) -> dict:
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
    if (kind not in TASK_KINDS or not _TOKEN.fullmatch(task_id)
            or not _TOKEN.fullmatch(batch)):
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
    declared = () if outputs_raw == "none" else tuple(outputs_raw.split(","))
    if (kind == "source") != (not declared):
        raise PlanMetadataError(
            "source declares outputs=none; artifact names its exact approved outputs"
        )
    outputs: list[str] = []
    for raw_output in declared:
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

    adjacent = [
        candidate for candidate in lines[index + 1:index + 2]
        if candidate.startswith("<!-- pipeline-auto-task-suite:")
    ]
    if kind == "source":
        if len(adjacent) != 1:
            raise PlanMetadataError(
                f"source task {task_id} needs one adjacent verification suite"
            )
        suite = _TASK_SUITE.fullmatch(adjacent[0])
        if suite is None or suite.group(1) != task_id:
            raise PlanMetadataError("task suite identity must match task metadata")
        commands = _parse_command_suite(suite.group(2))
    else:
        if adjacent:
            raise PlanMetadataError(
                "artifact tasks use exact outputs, not a source-task suite"
            )
        commands = ()
    return {
        "id": task_id, "deps": deps, "kind": kind, "batch": batch, "order": order,
        "write_scope": write_scope, "outputs": tuple(outputs), "commands": commands,
    }


def parse_plan_metadata(path) -> dict:
    """Return one approved phase plan's strict metadata: phase header plus tasks."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    phase = _parse_phase_header(lines)
    tasks = [
        _parse_task_metadata(lines, index)
        for index, line in enumerate(lines)
        if line.startswith("<!-- pipeline-auto-task:")
    ]
    if not 1 <= len(tasks) <= MAX_TASKS_PER_PHASE:
        raise PlanMetadataError(
            f"phase plan must contain between 1 and {MAX_TASKS_PER_PHASE} tasks"
        )
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise PlanMetadataError("duplicate task id")
    known = set(ids)
    if any(
        dependency not in known or dependency == task["id"]
        for task in tasks for dependency in task["deps"]
    ):
        raise PlanMetadataError("unknown or self dependency")
    _validate_acyclic_dependencies(
        {task["id"]: task["deps"] for task in tasks},
        error_type=PlanMetadataError, subject="task",
    )
    return {"phase": phase, "tasks": tasks}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): add parse_plan_metadata with pinned task key order"
```

---

### Task 3: `scopes_overlap` — the ancestor rule (fault F1)

Two scopes conflict for equal file paths, equal or ancestor tree paths, or a tree path equal to or containing a file path. Implemented as plain equality, `tree:src` and `file:src/a.py` reserve together and two implementers write the same file. Spare capacity never overrides a conflict.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `_safe_relative`, `PlanMetadataError`.
- Produces: `scopes_overlap(a: str, b: str) -> bool`; `_scope_parts(scope)`; `_path_in_scope(path: str, scope: str) -> bool`; `_scope_sets_overlap(left, right) -> bool`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 3 tests -- fault F1
# --------------------------------------------------------------------------

class ScopeAlgebraTests(unittest.TestCase):

    def test_overlapping_scopes_conflict(self):
        cases = (
            ("file:src/a.py", "file:src/a.py"),
            ("tree:src", "file:src/a.py"),          # the pair plain equality misses
            ("tree:src", "tree:src/deep/nested"),
            ("tree:src", "tree:src"),
            ("tree:src/pkg", "file:src/pkg/mod/a.py"),
            ("tree:src/a.py", "file:src/a.py"),     # a tree naming exactly one file
        )
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertTrue(state.scopes_overlap(left, right))
                self.assertTrue(state.scopes_overlap(right, left))

    def test_disjoint_scopes_do_not_conflict(self):
        cases = (
            ("file:src/a.py", "file:src/b.py"),
            ("tree:src", "tree:docs"),
            ("tree:src", "file:docs/a.md"),
            ("tree:source", "file:src/a.py"),       # a name prefix is not ancestry
            ("tree:src/pkg", "file:src/pkgx/a.py"),
            ("file:src/a.py", "tree:src/a.py/deep"),
        )
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertFalse(state.scopes_overlap(left, right))
                self.assertFalse(state.scopes_overlap(right, left))

    def test_rejects_untyped_or_unsafe_scopes(self):
        for scope in ("src/a.py", "glob:src", "file:../a", "file:"):
            with self.subTest(scope=scope):
                with self.assertRaises(state.PlanMetadataError):
                    state.scopes_overlap(scope, "file:src/a.py")

    def test_scope_sets_find_a_single_conflicting_pair(self):
        left = ("file:src/a.py", "tree:docs")
        self.assertTrue(
            state._scope_sets_overlap(left, ("file:src/b.py", "file:docs/index.md"))
        )
        self.assertFalse(
            state._scope_sets_overlap(left, ("file:src/b.py", "tree:reports"))
        )

    def test_path_in_scope(self):
        cases = (
            ("src/a.py", "file:src/a.py", True),
            ("src/a.py", "file:src/b.py", False),
            ("src/a.py", "tree:src", True),
            ("src/deep/a.py", "tree:src", True),
            ("srcx/a.py", "tree:src", False),
            ("src", "tree:src", True),
        )
        for path, scope, expected in cases:
            with self.subTest(path=path, scope=scope):
                self.assertIs(state._path_in_scope(path, scope), expected)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k ScopeAlgebraTests`
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

def _scope_parts(scope: str):
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): carry the ancestor branch in scope conflict detection"
```

---

### Task 4: Worker-result template and codec — the reversed status semantics (fault F5)

The vocabulary is unchanged from `superb:pipeline`. The routing is not. `NEEDS_CONTEXT` and `PLAN_CONFLICT` raise a quorum question and therefore **must** carry a resolvable, digest-bound `question_record`; `BLOCKED` still halts and must carry a `blocking_reason`. The codec enforces this at render and at parse, so a malformed result cannot even be published.

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/templates/worker-result.md`
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `TASK_KINDS`, `_TOKEN`, `_safe_relative`, `TrackerValidationError`.
- Produces: `WORKER_RESULT_MARKER`; `COMPLETION_STATUSES`, `QUORUM_STATUSES`, `HALT_STATUSES`, `WORKER_STATUSES`; `WORKER_RESULT_FIELDS`; `_COMMIT`; `_table_safe`, `_digest_reference`, `_split_row`, `_cell`; `render_worker_result(result: dict) -> str`; `parse_worker_result(text: str) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 4 tests -- fault F5
# --------------------------------------------------------------------------

DIGEST = "a" * 64
COMMIT = "b" * 40


def worker_result(**overrides) -> dict:
    result = {
        "run_id": "run-1",
        "task_id": "T1",
        "attempt": 1,
        "owner": "impl-1",
        "kind": "source",
        "status": "DONE",
        "source_ref": COMMIT,
        "commits": (COMMIT,),
        "artifacts": (),
        "tests": ("python3 -m unittest -k T1",),
        "evidence": (f"docs/superpowers/runs/run-1/evidence/T1.md#sha256={DIGEST}",),
        "concerns": "-",
        "question_record": "-",
        "blocking_reason": "-",
        "checkpoints": (),
    }
    result.update(overrides)
    return result


def quorum_result(status: str, **overrides) -> dict:
    return worker_result(
        status=status, source_ref="-", commits=(), evidence=(),
        question_record=f"docs/superpowers/runs/run-1/questions/q1.md#sha256={DIGEST}",
        **overrides,
    )


class WorkerResultCodecTests(unittest.TestCase):

    def test_round_trips(self):
        original = worker_result(checkpoints=(
            {"id": "c1", "status": "complete",
             "evidence": f"docs/superpowers/runs/run-1/evidence/T1.md#sha256={DIGEST}"},
        ))
        text = state.render_worker_result(original)
        self.assertTrue(text.startswith(state.WORKER_RESULT_MARKER))
        self.assertEqual(state.parse_worker_result(text), original)

    def test_field_order_is_pinned_in_the_rendered_document(self):
        text = state.render_worker_result(worker_result())
        rendered = [
            line.split("|")[1].strip()
            for line in text.splitlines()
            if line.startswith("| ") and line.count("|") == 3
        ]
        self.assertEqual(
            [name for name in rendered if name in state.WORKER_RESULT_FIELDS],
            list(state.WORKER_RESULT_FIELDS),
        )

    def test_rejects_a_foreign_marker(self):
        text = state.render_worker_result(worker_result()).replace(
            state.WORKER_RESULT_MARKER, "<!-- pipeline-worker-result/v2 -->"
        )
        with self.assertRaises(state.TrackerValidationError):
            state.parse_worker_result(text)

    def test_rejects_reordered_fields(self):
        lines = state.render_worker_result(worker_result()).splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith("| owner "))
        lines[index], lines[index - 1] = lines[index - 1], lines[index]
        with self.assertRaises(state.TrackerValidationError):
            state.parse_worker_result("\n".join(lines) + "\n")

    def test_quorum_status_without_a_question_record_is_rejected(self):
        """F5: a quorum-raising result missing its question record is rejected,
        exactly as a result with a missing owner is rejected."""
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(
                        quorum_result(status, question_record="-")
                    )

    def test_quorum_status_with_a_digest_bound_question_record_is_accepted(self):
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                result = quorum_result(status)
                self.assertEqual(
                    state.parse_worker_result(state.render_worker_result(result)),
                    result,
                )

    def test_quorum_question_record_must_be_digest_bound(self):
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(quorum_result(
                        status,
                        question_record="docs/superpowers/runs/run-1/questions/q1.md",
                    ))

    def test_quorum_status_may_not_also_carry_a_blocking_reason(self):
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(
                        quorum_result(status, blocking_reason="also blocked")
                    )

    def test_blocked_requires_a_blocking_reason_and_no_question_record(self):
        base = dict(source_ref="-", commits=(), evidence=())
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(
                worker_result(status="BLOCKED", blocking_reason="-", **base)
            )
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(worker_result(
                status="BLOCKED", blocking_reason="no staging credential",
                question_record=f"docs/q.md#sha256={DIGEST}", **base,
            ))
        accepted = worker_result(
            status="BLOCKED", blocking_reason="no staging credential", **base
        )
        self.assertEqual(
            state.parse_worker_result(state.render_worker_result(accepted)), accepted
        )

    def test_completion_status_carries_neither_routing_field(self):
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(
                worker_result(question_record=f"docs/q.md#sha256={DIGEST}")
            )
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(worker_result(blocking_reason="why"))

    def test_status_vocabulary_is_exactly_five_values(self):
        self.assertEqual(state.WORKER_STATUSES, (
            "DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "PLAN_CONFLICT", "BLOCKED",
        ))
        self.assertEqual(state.QUORUM_STATUSES, ("NEEDS_CONTEXT", "PLAN_CONFLICT"))
        self.assertEqual(state.HALT_STATUSES, ("BLOCKED",))
        with self.assertRaises(state.TrackerValidationError):
            state.render_worker_result(worker_result(status="OK"))

    def test_rejects_unsafe_scalars(self):
        for override in ({"owner": "impl|1"}, {"concerns": "a|b"}, {"attempt": 0},
                         {"attempt": "1"}, {"kind": "binary"}, {"run_id": ""},
                         {"commits": ("short",)}, {"source_ref": "nope"}):
            with self.subTest(override=override):
                with self.assertRaises(state.TrackerValidationError):
                    state.render_worker_result(worker_result(**override))

    def test_template_matches_the_codec_fields(self):
        template = (
            Path(state.__file__).resolve().parents[1] / "templates" / "worker-result.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(template.startswith(state.WORKER_RESULT_MARKER))
        for field in state.WORKER_RESULT_FIELDS:
            with self.subTest(field=field):
                self.assertIn(f"| {field} | ", template)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k WorkerResultCodecTests`
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
statuses raise a quorum question, and a result naming no question record is
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


def _table_safe(value, *, field: str) -> str:
    if not isinstance(value, str) or not value or "|" in value or "\n" in value:
        raise TrackerValidationError(f"{field} must be a nonempty table-safe string")
    return value


def _digest_reference(value: str):
    match = _DIGEST_REFERENCE.fullmatch(_table_safe(value, field="reference"))
    if match is None:
        raise TrackerValidationError(
            f"reference must be <repository-relative-path>#sha256=<digest>: {value!r}"
        )
    try:
        path = _safe_relative(match.group("path"))
    except PlanMetadataError as exc:
        raise TrackerValidationError(str(exc)) from exc
    return path.as_posix(), match.group("digest")


def _validate_worker_result(result: dict) -> dict:
    missing = [
        field for field in (*WORKER_RESULT_FIELDS, "checkpoints")
        if field not in result
    ]
    if missing:
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
        for value in values:
            _table_safe(value, field=field)
        if len(set(values)) != len(values):
            raise TrackerValidationError(f"duplicate {field} entry")
    for reference in tuple(result["evidence"]):
        _digest_reference(reference)
    if result["source_ref"] != "-" and not _COMMIT.fullmatch(result["source_ref"]):
        raise TrackerValidationError("source_ref must be a full 40-hex commit or '-'")
    if any(not _COMMIT.fullmatch(commit) for commit in result["commits"]):
        raise TrackerValidationError("commits must be full 40-hex shas")

    question_record = _table_safe(result["question_record"], field="question_record")
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
    elif question_record != "-" or blocking_reason != "-":
        raise TrackerValidationError(
            "a completion status carries neither question record nor blocking reason"
        )

    for checkpoint in tuple(result["checkpoints"]):
        if set(checkpoint) != {"id", "status", "evidence"}:
            raise TrackerValidationError("checkpoint needs exactly id/status/evidence")
        if not _TOKEN.fullmatch(checkpoint["id"]):
            raise TrackerValidationError("checkpoint id must be an identifier token")
        if checkpoint["status"] not in _CHECKPOINT_STATES:
            raise TrackerValidationError(
                f"unknown checkpoint state: {checkpoint['status']!r}"
            )
        _digest_reference(checkpoint["evidence"])
    return result


def _cell(value) -> str:
    if isinstance(value, (tuple, list)):
        return ",".join(value) if value else "-"
    return str(value)


def _split_row(line: str) -> list:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


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


def parse_worker_result(text: str) -> dict:
    """Parse a canonical worker result, rejecting a foreign or reordered document."""
    lines = text.splitlines()
    if not lines or lines[0] != WORKER_RESULT_MARKER:
        raise TrackerValidationError(
            "worker result marker is missing or foreign; the two formats do not "
            "interoperate"
        )
    rows = [_split_row(line) for line in lines if line.startswith("| ")]
    field_rows = [
        row for row in rows if len(row) == 2 and row[0] not in {"Field", "---"}
    ]
    if [row[0] for row in field_rows] != list(WORKER_RESULT_FIELDS):
        raise TrackerValidationError(
            "worker result fields are missing, unknown, or reordered"
        )
    values = {row[0]: row[1] for row in field_rows}
    result = {field: values[field] for field in WORKER_RESULT_FIELDS}
    try:
        result["attempt"] = int(values["attempt"])
    except ValueError as exc:
        raise TrackerValidationError("attempt must be a positive integer") from exc
    for field in _TUPLE_FIELDS:
        raw = values[field]
        result[field] = () if raw == "-" else tuple(raw.split(","))
    result["checkpoints"] = tuple(
        {"id": row[0], "status": row[1], "evidence": row[2]}
        for row in rows
        if len(row) == 3 and row[0] not in {"ID", "---"}
    )
    return _validate_worker_result(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v`
Expected: OK

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

A digest-bound typed PASS record is the only acceptable proof that a suite ran. It names the run, the subject, the attempt, the full tested commit, and the exact ordered command tuple. `outcome` is the literal `PASS`; there is no other legal value, because a record that is not a PASS is not evidence and is never written.

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/templates/verification-evidence.md`
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `_parse_command_suite`, `_digest_reference`, `_COMMIT`, `_split_row`, `TrackerValidationError`.
- Produces: `EVIDENCE_MARKER`; `EVIDENCE_PURPOSES = ("task-test", "task-integration", "phase")`; `EVIDENCE_FIELDS`; `parse_verification_evidence(text: str) -> dict`; `resolve_evidence(run_dir, repo_dir, reference) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py` (add `import hashlib` beside the other imports at the top of the file):

```python
# --------------------------------------------------------------------------
# Task 5 tests
# --------------------------------------------------------------------------

def evidence_text(**overrides) -> str:
    fields = {
        "purpose": "task-test",
        "run_id": "run-1",
        "subject": "task/T1",
        "attempt": "1",
        "code_state": COMMIT,
        "outcome": "PASS",
        "commands": '["python3 -m unittest -k T1"]',
        "environment": "python3.11-linux",
        "inputs": "-",
    }
    fields.update(overrides)
    rows = "\n".join(f"| {key} | {value} |" for key, value in fields.items())
    return f"{state.EVIDENCE_MARKER}\n| Field | Value |\n| --- | --- |\n{rows}\n"


def write_evidence(directory, name: str = "T1.md", **overrides) -> str:
    """Write one evidence file and return its sha256 hex digest."""
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    content = evidence_text(**overrides)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class VerificationEvidenceCodecTests(TempDirTestCase):

    def test_round_trips(self):
        record = state.parse_verification_evidence(evidence_text())
        self.assertEqual(record["purpose"], "task-test")
        self.assertEqual(record["subject"], "task/T1")
        self.assertEqual(record["attempt"], "1")
        self.assertEqual(record["code_state"], COMMIT)
        self.assertEqual(record["commands"], ("python3 -m unittest -k T1",))

    def test_rejects_a_foreign_marker(self):
        text = evidence_text().replace(
            state.EVIDENCE_MARKER, "<!-- pipeline-verification-evidence/v2 -->"
        )
        with self.assertRaises(state.TrackerValidationError):
            state.parse_verification_evidence(text)

    def test_rejects_invalid_records(self):
        cases = (
            {"outcome": "FAIL"}, {"outcome": "pass"}, {"purpose": "remediation"},
            {"purpose": "anything"}, {"code_state": "short"}, {"commands": "[]"},
            {"commands": "not-json"}, {"environment": "-"}, {"subject": "T1"},
            {"attempt": "0"}, {"attempt": "later"},
        )
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(state.TrackerValidationError):
                    state.parse_verification_evidence(evidence_text(**override))

    def test_rejects_reordered_fields(self):
        lines = evidence_text().splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith("| outcome "))
        lines[index], lines[index - 1] = lines[index - 1], lines[index]
        with self.assertRaises(state.TrackerValidationError):
            state.parse_verification_evidence("\n".join(lines) + "\n")

    def test_resolve_evidence_verifies_the_digest(self):
        run_dir = self.tmp / "run"
        digest = write_evidence(run_dir / "evidence")
        record = state.resolve_evidence(
            run_dir, self.tmp, f"evidence/T1.md#sha256={digest}"
        )
        self.assertEqual(record["subject"], "task/T1")
        with self.assertRaises(state.TrackerValidationError):
            state.resolve_evidence(
                run_dir, self.tmp, f"evidence/T1.md#sha256={'c' * 64}"
            )
        with self.assertRaises(state.TrackerValidationError):
            state.resolve_evidence(
                run_dir, self.tmp, f"evidence/absent.md#sha256={digest}"
            )

    def test_template_matches_the_codec_fields(self):
        template = (
            Path(state.__file__).resolve().parents[1]
            / "templates" / "verification-evidence.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(template.startswith(state.EVIDENCE_MARKER))
        for field in state.EVIDENCE_FIELDS:
            with self.subTest(field=field):
                self.assertIn(f"| {field} | ", template)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k VerificationEvidenceCodecTests`
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
    for candidate in (Path(run_dir) / relative, Path(repo_dir) / relative):
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v`
Expected: OK

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
- Consumes: P02's `initialize_run`, `validate_run`, `locked_tracker_update`, `append_row`, `section_columns`, `repo_root`; `parse_plan_metadata`, `_scope_sets_overlap`, `TrackerValidationError`.
- Produces: `QUORUM_SLOT_RESERVE = 3`; `implementation_slot_cap(worker_limit: int) -> int`; `_run_field`, `_current_field`, `_task_row`, `_replace_task`, `_quorum_owners`, `_csv`, `_append_history`; `_implementation_owners(tracker)`, `_active_owners(tracker)`; `_repo_dir(tracker) -> Path`; `_git`, `_git_out`, `_resolved_commit`; `_active_phase_plan(run_dir, tracker) -> Path`; `_approved_definition(run_dir, tracker, task_id) -> dict`; `_require_dependencies_complete`, `_require_no_scope_conflict`, `_require_capacity`, `_require_fresh_attempt`, `_validate_assignment`; `reserve_task(run_dir, *, task_id, owner, attempt) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Run harness -- reused by tasks 6 through 12
# --------------------------------------------------------------------------

def git(repo, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *args),
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def make_repo(root) -> Path:
    repo = Path(root) / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    (repo / "src").mkdir()
    (repo / "src" / "seed.py").write_text("seed = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "seed")
    git(repo, "branch", "-f", "target", "HEAD")
    return repo


def make_run(root, tasks_body: str, *, worker_limit: int = 4):
    """Return (repo, run_dir, phase_plan).

    P02's initialize_run takes no artifact references and seeds no task rows, so
    the harness writes `phase_plans`, the active phase, and the `## Tasks` rows
    through one explicit locked update using P02's append_row. See "Unresolved".
    """
    repo = make_repo(root)
    run_dir = repo / "docs" / "superpowers" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    plan = write_phase_plan(run_dir, tasks_body)
    state.initialize_run(
        run_dir, run_id="run-1", base_commit=git(repo, "rev-parse", "HEAD"),
        target_branch="target", worker_limit=worker_limit, repo_root=str(repo),
    )
    relative_plan = plan.relative_to(repo).as_posix()
    tasks = state.parse_plan_metadata(plan)["tasks"]

    def mutate(tracker: dict) -> dict:
        tracker["run"]["phase_plans"] = relative_plan
        tracker["current"]["phase"] = "P04"
        state.append_row(tracker, "Phases", {
            "id": "P04", "state": "active", "review_class": "required",
            "class_source": "plan", "ratchet": "-",
        })
        for task in tasks:
            row = {column: "-" for column in state.section_columns("Tasks")}
            row.update(id=task["id"], state="[ ]", kind=task["kind"],
                       deps=",".join(task["deps"]) or "-", provisional="no")
            state.append_row(tracker, "Tasks", row)
        return tracker

    state.locked_tracker_update(run_dir, transition_id="seed-p04", mutate=mutate)
    return repo, run_dir, plan


def three_disjoint_tasks() -> str:
    return "".join(
        task_block(f"T{index}", order=index, batch=f"b{index}",
                   write_scope=f"file:src/a{index}.py")
        for index in range(1, 4)
    )


def open_quorum_row(run_dir, owners=("brain-1", "brain-2", "brain-3")) -> None:
    """Stand in for P03's open_quorum: one in_flight record with three owners."""
    def mutate(tracker: dict) -> dict:
        row = {column: "-" for column in state.section_columns("Quorum")}
        row.update(qid="q0001", state="in_flight", owners=",".join(owners))
        return state.append_row(tracker, "Quorum", row)

    state.locked_tracker_update(run_dir, transition_id="test-open-quorum", mutate=mutate)


def task_row(tracker: dict, task_id: str) -> dict:
    return next(row for row in tracker["tasks"] if row["id"] == task_id)


def set_task_state(run_dir, task_id: str, **fields) -> None:
    def mutate(tracker: dict) -> dict:
        task_row(tracker, task_id).update(fields)
        return tracker

    state.locked_tracker_update(
        run_dir, transition_id=f"test-set-{task_id}-{sorted(fields)}", mutate=mutate
    )


# --------------------------------------------------------------------------
# Task 6 tests -- faults F1 and F2
# --------------------------------------------------------------------------

class SlotCapTests(unittest.TestCase):

    def test_cap_holds_three_slots_for_a_quorum(self):
        self.assertEqual(state.QUORUM_SLOT_RESERVE, 3)
        self.assertEqual(state.implementation_slot_cap(4), 1)
        self.assertEqual(state.implementation_slot_cap(6), 3)
        self.assertEqual(state.implementation_slot_cap(10), 7)

    def test_cap_floors_at_one_so_tasks_serialise_rather_than_stall(self):
        # Below four the cap floors at ONE, not zero: tasks serialise and the
        # brain slots stay free. Flooring at zero would stop the run instead.
        self.assertEqual(state.implementation_slot_cap(3), 1)
        self.assertEqual(state.implementation_slot_cap(1), 1)

    def test_cap_rejects_a_nonpositive_limit(self):
        for value in (0, -1, True, "4"):
            with self.subTest(value=value):
                with self.assertRaises(state.TrackerValidationError):
                    state.implementation_slot_cap(value)


class ReserveTaskTests(TempDirTestCase):

    def test_worker_limit_four_reserves_one_task_and_a_quorum_still_fits(self):
        """F2: reserving up to worker_limit deadlocks the run permanently --
        the blocked task holds the slot needed to dispatch the brains that
        would unblock it."""
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=4)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)

        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        self.assertIn("quorum", str(caught.exception))

        tracker = state.validate_run(run_dir)
        self.assertEqual(
            [row["id"] for row in tracker["tasks"] if row["state"] == "[~]"], ["T1"]
        )
        self.assertEqual(state._implementation_owners(tracker), {"impl-1"})

        # The three held slots are really available: a quorum opened afterwards
        # takes them and the run sits AT its limit, not over it.
        open_quorum_row(run_dir)
        tracker = state.validate_run(run_dir)
        self.assertEqual(
            state._quorum_owners(tracker), {"brain-1", "brain-2", "brain-3"}
        )
        self.assertEqual(len(state._active_owners(tracker)), 4)
        self.assertEqual(int(tracker["run"]["worker_limit"]), 4)

        with self.assertRaises(state.TrackerValidationError):
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)

    def test_worker_limit_six_reserves_three_tasks_then_refuses_a_fourth(self):
        body = three_disjoint_tasks() + task_block(
            "T4", order=4, batch="b4", write_scope="file:src/a4.py"
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=6)
        for index in range(1, 4):
            state.reserve_task(
                run_dir, task_id=f"T{index}", owner=f"impl-{index}", attempt=1
            )
        tracker = state.validate_run(run_dir)
        self.assertEqual(len(state._implementation_owners(tracker)), 3)
        with self.assertRaises(state.TrackerValidationError):
            state.reserve_task(run_dir, task_id="T4", owner="impl-4", attempt=1)

    def test_a_blocked_task_still_occupies_its_implementation_slot(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=4)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        set_task_state(run_dir, "T1", state="[?]",
                       question=f"quorum:docs/q.md#sha256={DIGEST}")
        tracker = state.validate_run(run_dir)
        self.assertEqual(state._implementation_owners(tracker), {"impl-1"})
        with self.assertRaises(state.TrackerValidationError):
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)

    def test_overlapping_scopes_never_reserve_together_despite_spare_capacity(self):
        """F1: tree:src and file:src/a.py must never both be active."""
        body = (
            task_block("T1", order=1, batch="b1", write_scope="tree:src")
            + task_block("T2", order=2, batch="b2", write_scope="file:src/a.py")
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=12)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        self.assertIn("write scope", str(caught.exception))
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_reservation_persists_the_baseline_for_a_source_task(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        target = git(repo, "rev-parse", "target")
        tracker = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        row = task_row(tracker, "T1")
        self.assertEqual(row["state"], "[~]")
        self.assertEqual(row["owner"], "impl-1")
        self.assertEqual(row["attempt"], "1")
        self.assertIn("started:1", row["checkpoints"])
        self.assertIn(f"baseline:1@{target}", row["checkpoints"])

    def test_artifact_task_reservation_records_no_baseline(self):
        body = task_block("T1", kind="artifact", write_scope="tree:docs",
                          outputs="docs/out.md")
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=6)
        tracker = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        self.assertNotIn("baseline:", task_row(tracker, "T1")["checkpoints"])

    def test_handles_the_first_start_only(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        with self.assertRaises(state.TrackerValidationError):
            state.reserve_task(run_dir, task_id="T1", owner="impl-9", attempt=2)

    def test_refuses_an_incomplete_dependency(self):
        body = (
            task_block("T1", order=1, batch="b1", write_scope="file:src/a1.py")
            + task_block("T2", deps="T1", order=2, batch="b2",
                         write_scope="file:src/a2.py")
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=8)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.reserve_task(run_dir, task_id="T2", owner="impl-2", attempt=1)
        self.assertIn("dependency", str(caught.exception))

    def test_rejects_bad_identity_and_a_reused_attempt(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        cases = (
            {"task_id": "T1", "owner": "impl|1", "attempt": 1},
            {"task_id": "T1", "owner": "impl-1", "attempt": 0},
            {"task_id": "T1", "owner": "impl-1", "attempt": "1"},
            {"task_id": "TX", "owner": "impl-1", "attempt": 1},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(state.TrackerValidationError):
                    state.reserve_task(run_dir, **kwargs)

    def test_replay_of_the_same_transition_is_inert(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        first = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        snapshot = (run_dir / "progress.md").read_bytes()
        replay = state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        self.assertEqual((run_dir / "progress.md").read_bytes(), snapshot)
        self.assertEqual(
            task_row(replay, "T1")["attempt"], task_row(first, "T1")["attempt"]
        )

    def test_repository_root_comes_from_the_tracker_not_from_run_dir_depth(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        tracker = state.validate_run(run_dir)
        self.assertEqual(state._repo_dir(tracker), repo.resolve())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k SlotCapTests`
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
        raise TrackerValidationError(
            f"tracker current field is missing: {field}"
        ) from exc


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


def _quorum_owners(tracker: dict) -> set:
    owners: set = set()
    for row in tracker.get("quorum", ()) or ():
        if row.get("state") != "in_flight":
            continue
        owners.update(
            value for value in str(row.get("owners", "-")).split(",")
            if value and value != "-"
        )
    return owners


def _csv(value: str) -> tuple:
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


def implementation_slot_cap(worker_limit) -> int:
    """Return how many slots implementation tasks may occupy at once."""
    if (not isinstance(worker_limit, int) or isinstance(worker_limit, bool)
            or worker_limit < 1):
        raise TrackerValidationError("worker_limit must be a positive integer")
    return max(1, worker_limit - QUORUM_SLOT_RESERVE)


def _implementation_owners(tracker: dict) -> set:
    return {
        row["owner"] for row in tracker.get("tasks", ())
        if row["state"] in _OCCUPYING_STATES and row["owner"] != "-"
    }


def _active_owners(tracker: dict) -> set:
    return _implementation_owners(tracker) | _quorum_owners(tracker)


# ---------------------------------------------------------------------------
# P04: Git facts
#
# The repository root is the one recorded at init. It is NEVER derived from
# run_dir depth: a run directory nested at an unexpected depth would otherwise
# silently bind the run to the wrong repository.
# ---------------------------------------------------------------------------

def _repo_dir(tracker: dict) -> Path:
    return Path(repo_root(tracker)).resolve()


def _git(repo, *args: str) -> bool:
    return subprocess.run(
        ("git", "-C", str(repo), *args),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0


def _git_out(repo, *args: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo), *args), capture_output=True, text=True, check=False,
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
# P04: approved task definitions and reservation guards
# ---------------------------------------------------------------------------

def _active_phase_plan(run_dir, tracker: dict) -> Path:
    paths = _csv(_run_field(tracker, "phase_plans"))
    phase_ids = [row["id"] for row in tracker.get("phases", ())]
    current = _current_field(tracker, "phase")
    if len(paths) != len(phase_ids) or current not in phase_ids:
        raise TrackerValidationError(
            "the current phase does not resolve to exactly one approved phase plan"
        )
    return _repo_dir(tracker) / _safe_relative(paths[phase_ids.index(current)])


def _approved_definition(run_dir, tracker: dict, task_id: str) -> dict:
    tasks = parse_plan_metadata(_active_phase_plan(run_dir, tracker))["tasks"]
    definition = next((task for task in tasks if task["id"] == task_id), None)
    if definition is None:
        raise TrackerValidationError(
            f"task {task_id} is not defined by the approved phase plan"
        )
    row = _task_row(tracker, task_id)
    if row["kind"] != definition["kind"] or _csv(row["deps"]) != definition["deps"]:
        raise TrackerValidationError(
            "task metadata does not match the authoritative approved plan"
        )
    return definition


def _require_dependencies_complete(tracker: dict, definition: dict) -> None:
    for dependency in definition["deps"]:
        if _task_row(tracker, dependency)["state"] != "[x]":
            raise TrackerValidationError(f"dependency {dependency} is not complete")


def _require_no_scope_conflict(run_dir, tracker: dict, definition: dict) -> None:
    for row in tracker.get("tasks", ()):
        if row["id"] == definition["id"] or row["state"] not in _OCCUPYING_STATES:
            continue
        other = _approved_definition(run_dir, tracker, row["id"])
        if _scope_sets_overlap(definition["write_scope"], other["write_scope"]):
            raise TrackerValidationError(
                f"write scope conflict: {definition['id']} "
                f"{definition['write_scope']} overlaps active {other['id']} "
                f"{other['write_scope']}"
            )


def _require_capacity(tracker: dict, owner: str) -> None:
    limit = int(_run_field(tracker, "worker_limit"))
    cap = implementation_slot_cap(limit)
    owners = _implementation_owners(tracker)
    if owner not in owners and len(owners) + 1 > cap:
        raise TrackerValidationError(
            f"implementation slots exhausted: {len(owners)} of {cap} in use "
            f"(worker_limit {limit} minus {QUORUM_SLOT_RESERVE} held for a quorum)"
        )
    if len(_active_owners(tracker) | {owner}) > limit:
        raise TrackerValidationError(
            f"global worker_limit {limit} is exhausted, including quorum owners"
        )


def _require_fresh_attempt(row: dict, attempt: int) -> None:
    used = set(_csv(row["attempt"]))
    for history in (row["checkpoints"], row["result"]):
        for entry in _csv(history):
            used.update(re.findall(r"(?<![0-9])[0-9]+(?![0-9])", entry))
    if str(attempt) in used:
        raise TrackerValidationError(f"task attempt {attempt} has already been used")


def _validate_assignment(owner, attempt) -> None:
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
        if definition["kind"] == "source":
            baseline = _resolved_commit(
                _repo_dir(tracker), _run_field(tracker, "target_branch")
            )
            checkpoint = f"{checkpoint},baseline:{attempt}@{baseline}"
        row = dict(row)
        row.update(state="[~]", owner=owner, attempt=str(attempt),
                   checkpoints=_append_history(row["checkpoints"], checkpoint))
        return _replace_task(tracker, row)

    return locked_tracker_update(
        run_dir, transition_id=f"reserve-{task_id}-{attempt}", mutate=mutate
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): hold three worker slots for a quorum when reserving tasks"
```

---

### Task 7: `resume_task`

An answered blocked attempt moves `[?] -> [~]`. The prior attempt must match, the new attempt must be distinct and unused, and `decision_ref` must resolve to an explicit adopted answer whose `Decision action` is `task.resume` and whose scope names the task. Context compaction or a restarted controller is not a blocked-task retry and creates no new attempt.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: everything Task 6 produced; `_split_row`.
- Produces: `RESUME_ACTION = "task.resume"`; `_decision_sections(text) -> dict`; `_decision_fields(lines) -> dict`; `_validate_decision(run_dir, tracker, decision_ref, task_id)`; `resume_task(run_dir, *, task_id, prior_attempt, new_owner, new_attempt, decision_ref) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 7 tests
# --------------------------------------------------------------------------

RESUME_DECISION = """# Decisions

## Q-0001
| Field | Value |
| --- | --- |
| Question | Which serialiser does T1 use? |
| Answer | The standard-library json module. |
| Provenance | quorum |
| Status | Adopted |
| Scope | T1 |
| Decision action | task.resume |
"""


def write_decisions(run_dir, body: str) -> None:
    (Path(run_dir) / "decisions.md").write_text(body, encoding="utf-8")

    def mutate(tracker: dict) -> dict:
        tracker["run"]["decisions"] = "decisions.md"
        return tracker

    state.locked_tracker_update(
        run_dir, transition_id=f"test-decisions-{len(body)}", mutate=mutate
    )


class ResumeTaskTests(TempDirTestCase):

    def blocked(self, *, worker_limit: int = 6):
        repo, run_dir, plan = make_run(
            self.tmp, three_disjoint_tasks(), worker_limit=worker_limit
        )
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        set_task_state(run_dir, "T1", state="[?]",
                       question=f"quorum:docs/q.md#sha256={DIGEST}")
        write_decisions(run_dir, RESUME_DECISION)
        return repo, run_dir

    def test_moves_an_answered_block_back_to_active(self):
        repo, run_dir = self.blocked()
        tracker = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref="Q-0001",
        )
        row = task_row(tracker, "T1")
        self.assertEqual(row["state"], "[~]")
        self.assertEqual(row["owner"], "impl-2")
        self.assertEqual(row["attempt"], "2")
        self.assertIn("resumed:1->2@Q-0001", row["checkpoints"])
        self.assertEqual(row["question"], "resolved:Q-0001")

    def test_records_a_fresh_baseline_for_a_source_task(self):
        repo, run_dir = self.blocked()
        (repo / "src" / "later.py").write_text("later = 1\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "target moved")
        git(repo, "branch", "-f", "target", "HEAD")
        moved = git(repo, "rev-parse", "target")
        tracker = state.resume_task(
            run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
            new_attempt=2, decision_ref="Q-0001",
        )
        self.assertIn(f"baseline:2@{moved}", task_row(tracker, "T1")["checkpoints"])

    def test_requires_the_matching_blocked_attempt(self):
        repo, run_dir = self.blocked()
        with self.assertRaises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=9, new_owner="impl-2",
                new_attempt=2, decision_ref="Q-0001",
            )

    def test_requires_a_distinct_unused_attempt(self):
        repo, run_dir = self.blocked()
        with self.assertRaises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=1, decision_ref="Q-0001",
            )

    def test_rejects_a_decision_without_the_task_resume_action(self):
        repo, run_dir = self.blocked()
        write_decisions(run_dir, RESUME_DECISION.replace("task.resume", "none"))
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref="Q-0001",
            )
        self.assertIn("task.resume", str(caught.exception))

    def test_rejects_a_decision_scoped_to_another_task(self):
        repo, run_dir = self.blocked()
        write_decisions(
            run_dir, RESUME_DECISION.replace("| Scope | T1 |", "| Scope | T3 |")
        )
        with self.assertRaises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref="Q-0001",
            )

    def test_rejects_a_superseded_or_missing_decision(self):
        repo, run_dir = self.blocked()
        write_decisions(run_dir, RESUME_DECISION.replace("Adopted", "Superseded"))
        with self.assertRaises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref="Q-0001",
            )
        write_decisions(run_dir, RESUME_DECISION)
        with self.assertRaises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref="Q-0404",
            )

    def test_rejects_a_generic_approval_as_an_answer(self):
        repo, run_dir = self.blocked()
        write_decisions(
            run_dir,
            RESUME_DECISION.replace(
                "| Answer | The standard-library json module. |", "| Answer | - |"
            ),
        )
        with self.assertRaises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref="Q-0001",
            )

    def test_refuses_an_active_task(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        write_decisions(run_dir, RESUME_DECISION)
        with self.assertRaises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref="Q-0001",
            )

    def test_still_honours_the_implementation_slot_cap(self):
        repo, run_dir = self.blocked(worker_limit=4)
        open_quorum_row(run_dir)
        with self.assertRaises(state.TrackerValidationError):
            state.resume_task(
                run_dir, task_id="T1", prior_attempt=1, new_owner="impl-2",
                new_attempt=2, decision_ref="Q-0001",
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k ResumeTaskTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'resume_task'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: resume an answered block
#
# Transition authority comes from an explicit `Decision action: task.resume`
# scoped to this task, never from the wording of an answer.
# ---------------------------------------------------------------------------

RESUME_ACTION = "task.resume"
_DECISION_HEADING = re.compile(r"^## ((?:H|Q|D)-[0-9A-Za-z]+)(?:\s|$)")


def _decision_sections(text: str) -> dict:
    sections: dict = {}
    current = None
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


def _decision_fields(lines) -> dict:
    fields: dict = {}
    for line in lines:
        if not line.startswith("| "):
            continue
        cells = _split_row(line)
        if len(cells) == 2 and cells[0] not in {"Field", "---"}:
            fields[cells[0]] = cells[1]
    return fields


def _validate_decision(run_dir, tracker: dict, decision_ref: str, task_id: str) -> None:
    relative = _safe_relative(_run_field(tracker, "decisions"))
    candidates = (Path(run_dir) / relative, _repo_dir(tracker) / relative)
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise TrackerValidationError(f"decisions file is missing: {relative}")
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
            f"decision {decision_ref} does not carry "
            f"'Decision action: {RESUME_ACTION}'"
        )
    if task_id not in _csv(fields.get("Scope", "-")):
        raise TrackerValidationError(
            f"decision {decision_ref} is not scoped to task {task_id}"
        )
    answer = fields.get("Answer", "").strip()
    if not answer or answer == "-":
        raise TrackerValidationError(
            f"decision {decision_ref} carries no explicit answer"
        )


def resume_task(run_dir, *, task_id: str, prior_attempt: int, new_owner: str,
                new_attempt: int, decision_ref: str) -> dict:
    """Persist an answered `[?] -> [~]` assignment before redispatch."""
    _validate_assignment(new_owner, new_attempt)
    if (not isinstance(prior_attempt, int) or isinstance(prior_attempt, bool)
            or prior_attempt < 1):
        raise TrackerValidationError("prior_attempt must be a positive integer")
    if not decision_ref or "|" in decision_ref:
        raise TrackerValidationError("decision_ref is required and must be table-safe")
    if new_attempt == prior_attempt:
        raise TrackerValidationError("the new attempt must be distinct")
    marker = f"resumed:{prior_attempt}->{new_attempt}@{decision_ref}"

    def mutate(tracker: dict) -> dict:
        row = _task_row(tracker, task_id)
        if row["state"] != "[?]" or row["attempt"] != str(prior_attempt):
            raise TrackerValidationError("resume requires the matching blocked attempt")
        _require_fresh_attempt(row, new_attempt)
        _validate_decision(run_dir, tracker, decision_ref, task_id)
        definition = _approved_definition(run_dir, tracker, task_id)
        _require_dependencies_complete(tracker, definition)
        _require_no_scope_conflict(run_dir, tracker, definition)
        _require_capacity(tracker, new_owner)
        checkpoint = marker
        if definition["kind"] == "source":
            baseline = _resolved_commit(
                _repo_dir(tracker), _run_field(tracker, "target_branch")
            )
            checkpoint = f"{checkpoint},baseline:{new_attempt}@{baseline}"
        row = dict(row)
        row.update(state="[~]", owner=new_owner, attempt=str(new_attempt),
                   checkpoints=_append_history(row["checkpoints"], checkpoint),
                   question=f"resolved:{decision_ref}")
        return _replace_task(tracker, row)

    return locked_tracker_update(
        run_dir,
        transition_id=f"resume-{task_id}-{prior_attempt}-{new_attempt}-{decision_ref}",
        mutate=mutate,
    )
```

`_require_capacity` counts the resuming owner against the same `worker_limit - 3` cap: an answered block does not buy extra capacity, so a run whose brains are still in flight waits rather than over-subscribing.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): gate task resume on an explicit task.resume decision"
```

---
