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
