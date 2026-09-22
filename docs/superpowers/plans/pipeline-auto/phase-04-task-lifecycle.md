# P04 Task Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pipeline-auto task lifecycle — reserve, resume, typed write scopes, immutable worker-result identity, the baseline-anchored source-range proof, integration ancestry, and file-first reconciliation — inside `pipeline_auto_state.py`, together with the strict phase-plan metadata grammar parser and the two result/evidence templates.

**Architecture:** P04 appends a task-lifecycle layer to the single state module P02 created. Every durable mutation goes through P02's `locked_tracker_update`; P04 supplies only `mutate` callables and pure validators, and reads tracker geometry through P02's `section_columns` / `append_row` / `repo_root`. The phase-plan metadata grammar is a strict, key-order-pinned HTML-comment format so a plan is machine-readable structure rather than prose a worker may reinterpret. Two semantics change from `superb:pipeline`: `NEEDS_CONTEXT` and `PLAN_CONFLICT` now route to a quorum instead of halting, and implementation tasks may never occupy more than `worker_limit - 3` slots so the three brain slots that would unblock them always exist.

**Tech Stack:** Python 3.11 standard library only, **tests included**. `pytest` is **not installed** and must not be used — tests are `unittest.TestCase`, run under `python3 -m unittest discover`. Markdown for all durable state. `git` invoked through `subprocess` for every commit fact.

**Spec:** `docs/superpowers/specs/2026-09-14-pipeline-auto-design.md`

**Master plan:** `docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md`

**Phase:** P04 — task-lifecycle. **Review class:** `required`. **Depends on:** P02. **Independent of:** P03.

## Gap left open by P02 Task 11 (commit `4d91366`)

**`## Run` has no semantic validator.** Every other section gained one in Tasks
3-7, but `base_commit`, `target_branch` and `worker_limit` are checked in exactly
one place — `initialize_run` — and never again. So a later `mutate` can write
nonsense into `worker_limit` and nothing objects; only `_IDENTITY_KEYS` would
notice a change, and only to the keys it guards.

That matters here because this phase reads `worker_limit` to decide capacity, and
the drift budget lives in `## Run` too. A run that quietly rewrites its own
`worker_limit` reserves the wrong number of brain slots; one that rewrites its
budget counters buys itself authority it was never granted — the same class of
self-interested move the one-way ratchet exists to forbid, taking a route the
schema does not watch.

Add `_validate_run` alongside the existing validators, and pin it the way the
others are pinned: a mutant that removes the call must die.

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

## Tracker column contract — read it from the fixture, not from here

The authority is P02's committed fixture, `plugins/superb/skills/pipeline-auto/tests/fixtures/valid-progress.md`. Open it before writing Task 6. The transcription below is for orientation only; where the two disagree, **the fixture wins**.

`## Tasks` — 16 columns, in this order:

```text
ID | Phase | Kind | State | Owner | Attempt | Result | Checkpoints |
Source Ref | Commits | Artifacts | Integration | Verification | Question |
Decisions | Provisional
```

Two consequences that bite immediately:

- **There is no `Deps` column.** Dependencies live in the phase-plan metadata and nowhere else, so `_approved_definition` compares only `Kind` against the plan and reads `deps` from `parse_plan_metadata`. A task row that carried its own copy of `deps` would be a second, divergable source of truth.
- **`Attempt` is a token, not a bare integer**: the fixture shows `attempt-001`, `attempt-002`. Every P04 signature takes `attempt: int`; every tracker cell, checkpoint marker, and result document renders it as `attempt-%03d`. `_attempt_token(attempt)` is the single conversion point.

`## Quorum` — 12 columns, in this order:

```text
QID | Axis | Phase | State | Owners | Payload Digest | Context Digest |
Responses | Depth | Rung | Outcome | Decision
```

P04 reads exactly three of them — `QID`, `State`, `Owners` — and treats `State == "in_flight"` as occupying three worker slots. It writes none: the whole section belongs to P03.

`## Phases` — 7 columns: `ID | State | Verification | Review Class | Class Source | Ratchet | Gate`.

`## Run` fields P04 reads: `run_id`, `target_branch`, `worker_limit`, `phase_plans`, `decisions`. The repository root comes from P02's `repo_root(tracker)` **function**, never from a run field and never from `run_dir` depth.

**Key form.** Column headers are title-case with spaces (`Source Ref`, `Payload Digest`); P04 addresses rows by the snake_case form of the header (`source_ref`, `payload_digest`) through `_field(row, "Source Ref")`, which accepts either spelling. That one function is the whole coupling to P02's key convention.

Every cell is a table-safe string; `-` is the empty marker; multi-valued cells are comma-separated. `worker_limit` is read with `int(...)`.

## Interfaces P04 produces

Implemented exactly as the master plan states them:

```python
def reserve_task(run_dir: str, *, task_id: str, owner: str, attempt: int) -> dict: ...
def resume_task(run_dir: str, *, task_id: str, prior_attempt: int,
                new_owner: str, new_attempt: int, decision_ref: str) -> dict: ...
def scopes_overlap(a: str, b: str) -> bool: ...
def parse_plan_metadata(path: str) -> dict: ...
def import_phase_plan(run_dir: str, *, phase_plan: str) -> dict: ...
def publish_worker_result(run_dir: str, *, result: dict) -> str: ...
def import_worker_result(run_dir: str, *, result_path: str,
                         run_command) -> dict: ...
#   `run_command(argv: tuple[str, ...]) -> str` is REQUIRED, not defaulted.
#   The module never executes git: it emits the argv and validates the
#   transcript, so the ability to run one command is the controller's
#   capability and arrives as an argument. The callable is handed the exact
#   argv and must return the captured stdout RAW -- no `.strip()`: the
#   leading NUL record separator and the trailing newline are both
#   load-bearing in the grammar `_parse_range_transcript` reads.
#   Changed by P04 Task 10; see the master plan's supersession note.
def verify_source_range(repo: str, *, baseline: str, head: str, head_ref: str,
                        scopes: list, transcript: str) -> dict: ...
def integrate_task(run_dir: str, *, task_id: str, merge_commit: str) -> dict: ...
def reconcile_run(run_dir: str) -> dict: ...
```

Plus `templates/worker-result.md` and `templates/verification-evidence.md`.

## Pinned marker and comment strings

P05 and P06 cite these rather than re-deriving them:

| Constant | Value |
| --- | --- |
| `WORKER_RESULT_MARKER` | `<!-- pipeline-auto-worker-result/v1 -->` |
| `EVIDENCE_MARKER` | `<!-- pipeline-auto-verification-evidence/v1 -->` |
| phase metadata comment | `<!-- pipeline-auto-phase: id=…; deps=…; review_class=…; review_reason=… -->` |
| phase suite comment | `<!-- pipeline-auto-phase-suite: id=…; commands=[…] -->` |
| task metadata comment | `<!-- pipeline-auto-task: id=…; deps=…; kind=…; batch=…; order=…; write_scope=…; outputs=… -->` |
| task suite comment | `<!-- pipeline-auto-task-suite: id=…; commands=[…] -->` |
| `EVIDENCE_PURPOSES` | `("task-test", "task-integration", "phase")` |
| `QUORUM_ROUTE` / `HALT_ROUTE` | `"quorum"` / `"halt"` |
| `REVIEW_CLASSES` | `("final-only", "required")` — P02's `_REVIEW_CLASSES`, ALIASED not re-typed, so the order is P02's and not this table's |
| `WORKER_STATUSES` | `("DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "PLAN_CONFLICT", "BLOCKED")` |

`EVIDENCE_PURPOSES` is **extended by the phase that needs the purpose**, never pre-populated here. P04 ships three; P05 appends `task-review` and `adversarial`; P06 appends `branch-review`, `completeness`, `final`. The validator rejecting an unregistered purpose is the point: a purpose nobody declared is a record nobody validates.

## Phase verification suite

The exact ordered command tuple for P04:

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The second command must print nothing. Every task below re-runs the first command, narrowed with `unittest`'s own `-k` filter. There is no `pytest` anywhere in this plan.

**Three verified facts about this command. Run it; do not reason about it.**

- **No `-t`.** `pipeline-auto` is hyphenated, so `-t .` makes discovery resolve the start directory as the module path `plugins.superb.skills.pipeline-auto.tests`, which is not a legal Python identifier. With `-t .` the command dies with `ImportError: Start directory is not importable`. Without `-t`, discovery uses the start directory as its own top level and the suite runs.
- **`-k` ORs when repeated.** `-k A -k B` selects both. unittest does **not** accept pytest's `-k "A or B"` — that pattern matches nothing.
- **A `-k` that matches nothing reports `OK` and exits 0.** So every sub-suite step below asserts the reported `Ran N tests` count, not the exit status. A step whose count is wrong has selected the wrong tests even when it says OK.

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

    python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
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
    commands: str = '["python3 -m unittest discover -s tests"]',
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
                         ("python3 -m unittest discover -s tests",))

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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k PhaseHeaderGrammarTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute '_parse_phase_header'` The run must still report `Ran 12 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k PhaseHeaderGrammarTests`
Expected: OK — `Ran 12 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): pin phase-plan header grammar with review_class"
```

---

> **RULING — the task-id grammar must be tightened HERE, and it is a deadlock,
> not an inconvenience.** Raised by P04 Task 9 (a task id carrying `/ : @ +` is
> accepted by the plan grammar and by `_validate_assignment` but refused at
> publication) and adjudicated by its review, which ran it end to end.
>
> **It is worse than "cannot publish a result".** `reserve_task` **accepts**
> such a task, so the slot is held against the `worker_limit - 3` cap and can
> **never terminate** — F2's permanent deadlock reached by another route. A
> legal phase plan can therefore wedge a run, and the failure arrives after the
> work is done.
>
> **Decisive evidence, and it is the plan grammar's own words.** The message
> says a task id is "written into a tracker cell, **a branch name** and a
> checkpoint marker" — and `git check-ref-format` already refuses `T:1` and
> `T1.` as branch names. So widening publication instead only moves the dead
> end later, to P05, after work has merged.
>
> **Fix:** tighten `_parse_task_metadata` (Task 2, `:11371`) and
> `_validate_assignment` (Task 6, `:14059`) **in the same commit**, before P05
> consumes any of it. **Do NOT tighten `_TOKEN`** — it is shared with
> `target_branch`, `axis`, `phase_id` and others that legitimately want `/`.

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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k TaskMetadataGrammarTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'parse_plan_metadata'` The run must still report `Ran 15 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ScopeAlgebraTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'scopes_overlap'` The run must still report `Ran 5 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k WorkerResultCodecTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'render_worker_result'` The run must still report `Ran 13 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

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
| attempt | <attempt-NNN> |
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
    lines += [
        f"| {field} | "
        f"{_attempt_token(result[field]) if field == 'attempt' else _cell(result[field])} |"
        for field in WORKER_RESULT_FIELDS
    ]
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
    if not _ATTEMPT_TOKEN.fullmatch(values["attempt"]):
        raise TrackerValidationError(
            "attempt must be rendered as an attempt token such as attempt-001"
        )
    result["attempt"] = int(values["attempt"].removeprefix("attempt-"))
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
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
        "attempt": "attempt-001",
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
        self.assertEqual(record["attempt"], "attempt-001")
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
            {"attempt": "0"}, {"attempt": "later"}, {"attempt": "1"},
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k VerificationEvidenceCodecTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'EVIDENCE_MARKER'` The run must still report `Ran 6 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/superb/skills/pipeline-auto/templates/verification-evidence.md`:

```markdown
<!-- pipeline-auto-verification-evidence/v1 -->
| Field | Value |
| --- | --- |
| purpose | <task-test_task-integration_or_phase> |
| run_id | <run_id> |
| subject | <task_or_phase>/<stable-id> |
| attempt | <attempt-NNN_or_N/A> |
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

_ATTEMPT_TOKEN = re.compile(r"attempt-[0-9]{3,}\Z")

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
    if record["attempt"] != "N/A" and not _ATTEMPT_TOKEN.fullmatch(record["attempt"]):
        raise TrackerValidationError(
            "evidence attempt must be an attempt token such as attempt-001, or N/A"
        )
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
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
- Produces: `_key`, `_field`, `_set_field`, `_run_field`, `_task_row`, `_replace_task`, `_quorum_owners`, `_csv`, `_append_history`, `_attempt_token`; `QUORUM_SLOT_RESERVE = 3`; `implementation_slot_cap(worker_limit: int) -> int`; `_implementation_owners(tracker)`, `_active_owners(tracker)`; `_repo_dir(tracker) -> Path`; `_git`, `_git_out`, `_resolved_commit`; `_phase_plan_path(tracker, phase_id) -> Path`; `_approved_definition(run_dir, tracker, task_id) -> dict`; `import_phase_plan(run_dir, *, phase_plan) -> dict`; `_require_dependencies_complete`, `_require_no_scope_conflict`, `_require_capacity`, `_require_fresh_attempt`, `_validate_assignment`; `reserve_task(run_dir, *, task_id, owner, attempt) -> dict`.

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

    initialize_run writes the `## Run` artifact references and an EMPTY
    `## Tasks`. The task rows are appended by import_phase_plan, which is P04's.
    """
    repo = make_repo(root)
    run_dir = repo / "docs" / "superpowers" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    plan = write_phase_plan(run_dir, tasks_body)
    relative_plan = plan.relative_to(repo).as_posix()
    state.initialize_run(
        run_dir, run_id="run-1", base_commit=git(repo, "rev-parse", "HEAD"),
        target_branch="target", worker_limit=worker_limit, repo_root=str(repo),
        phase_plans=relative_plan,
        decisions="docs/superpowers/runs/run-1/decisions.md",
        findings="docs/superpowers/runs/run-1/findings.md",
    )
    state.import_phase_plan(run_dir, phase_plan=plan)
    return repo, run_dir, plan


def three_disjoint_tasks() -> str:
    return "".join(
        task_block(f"T{index}", order=index, batch=f"b{index}",
                   write_scope=f"file:src/a{index}.py")
        for index in range(1, 4)
    )


def blank_row(section: str) -> dict:
    """An all-'-' row with exactly P02's committed columns for that section."""
    return {state._key(column): "-" for column in state.section_columns(section)}


def open_quorum_row(run_dir, owners=("brain-1", "brain-2", "brain-3")) -> None:
    """Stand in for P03's open_quorum: one in_flight record with three owners."""
    def mutate(tracker: dict) -> dict:
        row = blank_row("Quorum")
        row.update(qid="3f2a1b0c9d8e", axis="new", phase="P04",
                   state="in_flight", owners=",".join(owners))
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

class ImportPhasePlanTests(TempDirTestCase):

    def test_appends_one_row_per_planned_task_with_the_committed_columns(self):
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        tracker = state.validate_run(run_dir)
        self.assertEqual([row["id"] for row in tracker["tasks"]],
                         ["T1", "T2", "T3"])
        expected = {state._key(c) for c in state.section_columns("Tasks")}
        for row in tracker["tasks"]:
            with self.subTest(task=row["id"]):
                self.assertEqual(set(row), expected)
                self.assertEqual(row["state"], "[ ]")
                self.assertEqual(row["phase"], "P04")
                self.assertEqual(row["kind"], "source")
                self.assertEqual(row["owner"], "-")
                self.assertEqual(row["attempt"], "-")
                self.assertEqual(row["provisional"], "no")

    def test_task_rows_carry_no_dependency_column(self):
        """Dependencies live in the phase plan and nowhere else; a second copy
        on the row would be a divergable source of truth."""
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        tracker = state.validate_run(run_dir)
        self.assertNotIn("deps", tracker["tasks"][0])
        self.assertNotIn("dependencies", tracker["tasks"][0])

    def test_records_the_phase_with_its_plan_declared_review_class(self):
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        tracker = state.validate_run(run_dir)
        phase = next(row for row in tracker["phases"] if row["id"] == "P04")
        self.assertEqual(phase["review_class"], "required")
        self.assertEqual(phase["class_source"], "plan")
        self.assertEqual(phase["ratchet"], "-")

    def test_refuses_to_import_the_same_phase_twice(self):
        repo, run_dir, plan = make_run(self.tmp, three_disjoint_tasks())
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.TrackerValidationError):
            state.import_phase_plan(run_dir, phase_plan=plan)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_a_malformed_plan_imports_nothing(self):
        repo = make_repo(self.tmp)
        run_dir = repo / "docs" / "superpowers" / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        plan = write_phase_plan(run_dir, task_block("T1"),
                                header=phase_header(review_class="medium"))
        state.initialize_run(
            run_dir, run_id="run-1", base_commit=git(repo, "rev-parse", "HEAD"),
            target_branch="target", worker_limit=6, repo_root=str(repo),
            phase_plans=plan.relative_to(repo).as_posix(),
            decisions="docs/superpowers/runs/run-1/decisions.md",
            findings="docs/superpowers/runs/run-1/findings.md",
        )
        with self.assertRaises(state.PlanMetadataError):
            state.import_phase_plan(run_dir, phase_plan=plan)
        self.assertEqual(state.validate_run(run_dir)["tasks"], [])


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
        self.assertEqual(row["attempt"], "attempt-001")
        self.assertIn("started:attempt-001", row["checkpoints"])
        self.assertIn(f"baseline:attempt-001@{target}", row["checkpoints"])

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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ImportPhasePlanTests -k SlotCapTests -k ReserveTaskTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'import_phase_plan'` The run must still report `Ran 19 tests` (5 + 3 + 11); repeated `-k` flags OR together, and unittest does NOT accept pytest's `-k "A or B"`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: tracker accessors
#
# The column tuples are P02's, committed at tests/fixtures/valid-progress.md.
# `_field` is the ONLY place that knows how a column header becomes a dict key,
# so a change in P02's key convention costs one function, not a rewrite.
#
# For a one-word header the key and the header agree once lower-cased, so the
# bodies below index rows directly (row["state"], row["source_ref"]). `_field`
# is used wherever the header is multi-word or where tolerance matters.
# ---------------------------------------------------------------------------

import subprocess


def _key(column: str) -> str:
    """Map a committed column header ('Source Ref') to its dict key."""
    return column.strip().lower().replace(" ", "_")


def _field(row: dict, column: str) -> str:
    for candidate in (_key(column), column):
        if candidate in row:
            return row[candidate]
    raise TrackerValidationError(f"row is missing the {column!r} column")


def _set_field(row: dict, column: str, value: str) -> dict:
    row[_key(column) if _key(column) in row or column not in row else column] = value
    return row


def _run_field(tracker: dict, field: str) -> str:
    try:
        return tracker["run"][field]
    except (KeyError, TypeError) as exc:
        raise TrackerValidationError(f"tracker run field is missing: {field}") from exc


def _task_row(tracker: dict, task_id: str) -> dict:
    for row in tracker.get("tasks", ()):
        if _field(row, "ID") == task_id:
            return row
    raise TrackerValidationError(f"unknown task: {task_id}")


def _replace_task(tracker: dict, replacement: dict) -> dict:
    target = _field(replacement, "ID")
    tracker["tasks"] = [
        replacement if _field(row, "ID") == target else row
        for row in tracker["tasks"]
    ]
    return tracker


def _quorum_owners(tracker: dict) -> set:
    """Owners held by an in-flight quorum. P04 reads QID/State/Owners and
    writes nothing here: `## Quorum` belongs entirely to P03."""
    owners: set = set()
    for row in tracker.get("quorum", ()) or ():
        if _field(row, "State") != "in_flight":
            continue
        owners.update(
            value for value in str(_field(row, "Owners")).split(",")
            if value and value != "-"
        )
    return owners


def _csv(value: str) -> tuple:
    return () if value in {"", "-"} else tuple(value.split(","))


def _append_history(value: str, entry: str) -> str:
    return entry if value in {"", "-"} else f"{value},{entry}"


def _attempt_token(attempt: int) -> str:
    """The tracker renders an attempt as `attempt-001`; P04 signatures take an
    int. This is the single conversion point."""
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise TrackerValidationError("attempt must be a positive integer")
    return f"attempt-{attempt:03d}"


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


# =====================================================================
# DO NOT IMPLEMENT `_git` OR `_git_out`. THEY CANNOT EXIST.
#
# They are `subprocess.run` wrappers. `subprocess` is not in
# ALLOWED_IMPORTS and the master plan refuses it BY NAME, calling
# arbitrary command execution "the single capability this boundary most
# exists to withhold". The import guard refuses it; an exact-set test
# pins the twelve.
#
# They survive here only because the 13 call sites below them, in Tasks
# 8 and 11, still read the way they were first drafted. Under the quorum
# decision ("the module never executes git", master plan) every one of
# those becomes a read of the CONTROLLER-SUPPLIED TRANSCRIPT, with both
# endpoints re-derived in-module by `_resolved_commit`. Task 6 already
# set the precedent: it replaced `git rev-parse` with a 227-line ref-store
# reader rather than shelling out.
#
# `os.popen`/`os.system`/`os.exec*` are NOT a loophole. They are the same
# capability by another name and are screened by name; see the master
# plan's "the subprocess ban is nominal" section.
# =====================================================================


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

def _phase_plan_path(tracker: dict, phase_id: str) -> Path:
    """The master plan is the exact ordered authority for its phase-plan paths,
    so a phase's plan is the `phase_plans` entry at that phase's index."""
    paths = _csv(_run_field(tracker, "phase_plans"))
    phase_ids = [_field(row, "ID") for row in tracker.get("phases", ())]
    if len(paths) != len(phase_ids) or phase_id not in phase_ids:
        raise TrackerValidationError(
            f"phase {phase_id} does not resolve to exactly one approved phase plan"
        )
    return _repo_dir(tracker) / _safe_relative(paths[phase_ids.index(phase_id)])


def _approved_definition(run_dir, tracker: dict, task_id: str) -> dict:
    row = _task_row(tracker, task_id)
    plan = _phase_plan_path(tracker, _field(row, "Phase"))
    tasks = parse_plan_metadata(plan)["tasks"]
    definition = next((task for task in tasks if task["id"] == task_id), None)
    if definition is None:
        raise TrackerValidationError(
            f"task {task_id} is not defined by the approved phase plan"
        )
    # There is no Deps column: dependencies live in the phase plan and nowhere
    # else, so only Kind is cross-checked against the row.
    if _field(row, "Kind") != definition["kind"]:
        raise TrackerValidationError(
            "task kind does not match the authoritative approved plan"
        )
    return definition


# ---------------------------------------------------------------------------
# P04: phase-plan import
#
# initialize_run writes the `## Run` artifact references and an EMPTY
# `## Tasks`. Appending the task rows is P04's, because the row set is a
# projection of the phase-plan metadata grammar and of nothing else.
# ---------------------------------------------------------------------------

def import_phase_plan(run_dir, *, phase_plan) -> dict:
    """Append one approved phase plan's task rows; idempotent per phase."""
    metadata = parse_plan_metadata(phase_plan)
    phase_id = metadata["phase"]["id"]

    def mutate(tracker: dict) -> dict:
        existing = {_field(row, "ID") for row in tracker.get("tasks", ())}
        if any(_field(row, "ID") == phase_id for row in tracker.get("phases", ())):
            raise TrackerValidationError(f"phase {phase_id} is already imported")
        phase = {_key(column): "-" for column in section_columns("Phases")}
        phase.update({
            _key("ID"): phase_id, _key("State"): "[ ]",
            _key("Review Class"): metadata["phase"]["review_class"],
            _key("Class Source"): "plan",
        })
        append_row(tracker, "Phases", phase)
        for task in metadata["tasks"]:
            if task["id"] in existing:
                raise TrackerValidationError(f"duplicate task id: {task['id']}")
            row = {_key(column): "-" for column in section_columns("Tasks")}
            row.update({
                _key("ID"): task["id"], _key("Phase"): phase_id,
                _key("Kind"): task["kind"], _key("State"): "[ ]",
                _key("Provisional"): "no",
            })
            append_row(tracker, "Tasks", row)
        return tracker

    return locked_tracker_update(
        run_dir, transition_id=f"import-phase-plan-{phase_id}", mutate=mutate
    )


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
    token = _attempt_token(attempt)
    history = ",".join((row["attempt"], row["checkpoints"], row["result"]))
    if token in history:
        raise TrackerValidationError(f"task {token} has already been used")


def _validate_assignment(owner, attempt) -> None:
    if not isinstance(owner, str) or not _TOKEN.fullmatch(owner) or "|" in owner:
        raise TrackerValidationError("owner must be a table-safe identifier token")
    _attempt_token(attempt)          # rejects a non-positive or non-int attempt


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
        token = _attempt_token(attempt)
        checkpoint = f"started:{token}"
        if definition["kind"] == "source":
            baseline = _resolved_commit(
                _repo_dir(tracker), _run_field(tracker, "target_branch")
            )
            checkpoint = f"{checkpoint},baseline:{token}@{baseline}"
        row = dict(row)
        row.update(state="[~]", owner=owner, attempt=token,
                   checkpoints=_append_history(row["checkpoints"], checkpoint))
        return _replace_task(tracker, row)

    return locked_tracker_update(
        run_dir, transition_id=f"reserve-{task_id}-{attempt}", mutate=mutate
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): hold three worker slots for a quorum when reserving tasks"
```

---

> **QUORUM DECISION — the resume grant binds to the BLOCK, via the qid.**
> Three brains, decorrelated (ledger grammar / threat model / build cost), all
> `code-evidenced`, all converging. Recorded here because Tasks 7 and 10 must
> change together.
>
> **The hole.** `_validate_decision` is four screens wide and never reads the
> task row. A decision answering a *different* question, scoped to T1 with
> action `task.resume`, resumes T1. Worse than "wrong task": a controller can
> hand-author a `task.resume` record and clear a block **without a quorum, an
> escalation, or a unit of drift budget** — the budget that caps machine
> decision authority is bypassed entirely.
>
> **The binding already exists and is free.** `settle_quorum` mints
> `decision_id = "Q-" + qid`, and `_final_event` already refuses an adoption
> naming any other id, with the comment "without this an adoption may name
> ANOTHER quorum's decision -- or a HUMAN's". So a quorum decision id
> *contains the identity of the question it answers*. The only missing link is
> that the `Question` cell holds a worker-chosen path instead of that qid.
>
> **What to build:**
> 1. **Task 10** (unbuilt, so this is a plan edit not a rewrite) derives the qid
>    itself with the committed `derive_qid` from the published question record —
>    never trusting the worker for identity — and writes
>    `quorum:<qid>@<path>#sha256=<digest>`: the qid for the binding, the bound
>    path for the audit trail.
> 2. **Task 10** also appends `blocked:<attempt>@<question>` to `Checkpoints`,
>    which is append-only. The committed fixture already shows this shape
>    (`valid-progress.md:71`) and the predecessor both writes and *validates* it
>    (`pipeline_state.py:528-531`). `_validate_tasks` requires it on a `[?]` row.
>    **This costs zero lines in `resume_task`** and makes the audit pointer
>    survive every resume.
> 3. **Task 7**: `_validate_decision` takes `row` (it is already in hand three
>    lines earlier, inside `mutate`) and adds a fifth screen — on the quorum
>    route, `decision_ref == "Q-" + qid` split from the cell. ~10 lines, no file
>    read, no new column, no fixture change. This also closes re-opens:
>    `derive_reopen_qid` mints a different qid, so a stale answer cannot resume
>    a re-asked block.
> 4. **Bind the grant to the attempt.** A single adopted `task.resume` currently
>    authorises *unlimited* resumes of its task, for ever — `_require_fresh_attempt`
>    bounds attempts, not grants. `phase-07-skill-prose.md:3285` already says the
>    grant is "for the named prior attempt"; the attempt appears nowhere in it.
>    Require it and compare.
> 5. **The `halt:` route has no machine binding and the template must say so.**
>    No qid exists and there is no question record. Use an asserted `Blocker`
>    field compared against the cell, require `Provenance: human`, and state
>    plainly that this arm is an assertion by the writer, not a derivation.
>    Require one arm or the other, never neither.
>
> **Rejected.** *Two-phase stamp-back* is structurally impossible, not merely
> impolite: P03 has no task id — `_QUORUM_HEADER` carries `Phase`, never a task —
> so it would have to scan `## Tasks` for the row naming the qid, which is the
> reverse index it was supposed to create. *Weakening the template* legitimises
> the hole silently. *The `Decisions` column* is P06's provisional-taint edge;
> putting the grant there would silently make a resumed task taint-eligible.
>
> **Two honest weaknesses, to carry into the work.** The harness constant
> `QUESTION_REF = "quorum:docs/q.md#sha256=3c…"` points at a file that does not
> exist, so no fixture contains a real qid and **the current suite could not
> catch a subtly wrong qid comparison** — `blocked_run` must publish a real
> record first. And nothing in this module can catch a controller that copies
> the wrong blocker string on the halt arm; the template must not claim
> otherwise. `decisions.md` is unsigned and hand-editable, so this is
> tamper-evident by cross-reference, never tamper-proof.
>
> **Also settled:** the template clause this replaces was the drift, not the
> code. It was authored in the shipped template, appears in neither the spec nor
> the P02 plan, and describes the state `resume_task` *produces* read as a
> precondition — satisfiable only after the transition it was meant to gate. The
> predecessor implements it literally at `pipeline_state.py:1907` and it is dead
> code there too, reachable only from a hand-doctored tracker.

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
        self.assertEqual(row["attempt"], "attempt-002")
        self.assertIn("resumed:attempt-001->attempt-002@Q-0001", row["checkpoints"])
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
        self.assertIn(f"baseline:attempt-002@{moved}",
                      task_row(tracker, "T1")["checkpoints"])

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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ResumeTaskTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'resume_task'` The run must still report `Ran 10 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

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
    marker = (f"resumed:{_attempt_token(prior_attempt)}->"
              f"{_attempt_token(new_attempt)}@{decision_ref}")

    def mutate(tracker: dict) -> dict:
        row = _task_row(tracker, task_id)
        if row["state"] != "[?]" or row["attempt"] != _attempt_token(prior_attempt):
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
            checkpoint = f"{checkpoint},baseline:{_attempt_token(new_attempt)}@{baseline}"
        row = dict(row)
        row.update(state="[~]", owner=new_owner, attempt=_attempt_token(new_attempt),
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): gate task resume on an explicit task.resume decision"
```

---

> **AMENDED BY QUORUM DECISION — read the master plan's "the module never
> executes git" section before starting.** This task's brief was written around
> `_git`/`_git_out`, which are `subprocess.run` wrappers and **cannot exist**:
> `subprocess` is refused by name. The signature gains `transcript`, the module
> emits the argv via `source_range_commands` and validates what the controller
> ran, and `_commit_parents` is not built. Both endpoints stay module-derived
> (`_resolved_commit` and the reservation checkpoint), so a transcript rooted
> elsewhere fails at the first link. **Every changed-path command must use
> `--no-renames`** — without it a task can delete another task's file by moving
> it into its own scope and pass this very check.

### Task 8: `verify_source_range` — the baseline-anchored range proof (faults F3, F4)

A source task completes implementation only when its resolved source head contains exactly the complete, ordered, nonempty `baseline..source-head` range, every changed path is inside its approved typed write scope, and no commit in the range is empty. The baseline is the one persisted at reservation. `HEAD~1` is the wrong baseline: it silently truncates a multi-commit task to its last commit, and every earlier commit escapes the scope check entirely.

The implementation range is linear by construction — one worktree per implementer, merged only at integration — so a merge commit inside the range is a contradiction, not a variation.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `_git`, `_git_out`, `_resolved_commit`, `_path_in_scope`, `_scope_parts`.
- Produces: `source_range_commands(repo, *, baseline, head, head_ref) -> tuple`;
  `_parse_range_transcript(text) -> tuple`;
  `verify_source_range(repo, *, baseline, head, head_ref, scopes, transcript) -> dict` returning
  `{"baseline", "head", "commits", "changed_paths", "proof_mode"}`.
  `_commit_parents` is NOT produced — parents come from the transcript, not from an object read.
  **`head_ref` was added by the Task 8 fix round and is required.** Without it the
  "both endpoints module-derived" clause was false in the only case that ships:
  `_resolved_commit` short-circuited on a 40-hex ref before reading the ref store,
  and both production ends are 40-hex, so a complete `attested` proof was obtainable
  over a directory that is not a repository. The head is now the tip the ref store
  holds for `head_ref`; the `head` sha is a claim checked against it. The **baseline**
  is still not re-derived — it is the sha `reserve_task` recorded at reservation and
  the target branch has moved on — and no commit is proved to exist, because the
  module reads no objects.
  **Where Task 10 gets `head_ref`:** from the controller's own knowledge of the
  per-implementer-worktree topology, NOT from the worker's document. The
  worker-result grammar has fourteen fields and none of them is a branch, and
  adding one would put the anchor back on the worker's word — the point of the
  parameter is that the module resolves a reference the controller names.
  **SETTLED in Task 10** (it was left there as "a decision for Task 10 to
  argue", and a sketch that used an unbound `task_branch` was not that
  argument): `_task_branch(tracker, task_id)` derives `task/<task_id>`, which
  is already this phase's pinned spelling for the same task, and Task 9's fix
  round made the derivation total by refusing an unspellable task id at
  reservation.

  **`head` is a CLAIM and must be spelled as one.** It is refused unless it is
  forty hex characters — the exact mirror of `head_ref`, which is refused *if*
  it is. Both ends went through `_resolved_commit`, so `head="HEAD"`,
  `head="main"` or `head=head_ref` made the store resolve both sides and the
  `claimed != tip` check compared the store with itself. Measured: a no-op in
  every one of those spellings. The only thing behind accepting them was "a
  worker result's `source_ref` is forty hex by schema" — the reasoning that
  produced the hole above — so it is not trusted for `head` either.

  **What "`repo` is a git repository" means, exactly.** It is now git's own
  test: a `.git` directory or gitdir pointer, a readable commondir, a readable
  `HEAD`, and `objects/` and `refs/` directories. The earlier test was
  `(<repo>/.git).is_dir()` alone, and the weakest artifact that satisfied it
  and produced a full `attested` proof was a directory holding ONE FILE —
  `.git/refs/heads/<ref>` with forty hex in it — that real `git -C` refuses
  and that the module's own emitted argv cannot be run against.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 8 tests -- faults F3 and F4
# --------------------------------------------------------------------------

def commit_file(repo, relative: str, text: str, message: str) -> str:
    path = Path(repo) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


class SourceRangeTests(TempDirTestCase):

    def three_commit_branch(self):
        repo = make_repo(self.tmp)
        baseline = git(repo, "rev-parse", "target")
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        commits = tuple(
            commit_file(repo, "src/a1.py", f"value = {index}\n", f"step {index}")
            for index in range(1, 4)
        )
        return repo, baseline, commits

    def test_accepts_the_complete_ordered_range(self):
        repo, baseline, commits = self.three_commit_branch()
        proof = state.verify_source_range(
            repo, baseline=baseline, head=commits[-1], scopes=["file:src/a1.py"]
        )
        self.assertEqual(proof["baseline"], baseline)
        self.assertEqual(proof["head"], commits[-1])
        self.assertEqual(proof["commits"], commits)
        self.assertEqual(proof["changed_paths"], ("src/a1.py",))

    def test_head_tilde_one_baseline_truncates_a_multi_commit_task(self):
        """F3: HEAD~1 is not the review baseline. It silently drops the earlier
        commits, which then escape every scope and range check."""
        repo, baseline, commits = self.three_commit_branch()
        persisted = state.verify_source_range(
            repo, baseline=baseline, head=commits[-1], scopes=["file:src/a1.py"]
        )
        truncated = state.verify_source_range(
            repo, baseline=commits[-2], head=commits[-1], scopes=["file:src/a1.py"]
        )
        self.assertEqual(len(persisted["commits"]), 3)
        self.assertEqual(len(truncated["commits"]), 1)
        self.assertNotEqual(truncated["commits"], persisted["commits"])
        self.assertLess(set(truncated["commits"]), set(persisted["commits"]))

    def test_rejects_an_empty_commit(self):
        """F4: no diff is not an artifact completion and not a reason for an
        empty commit."""
        repo, baseline, commits = self.three_commit_branch()
        git(repo, "commit", "-q", "--allow-empty", "-m", "nothing happened")
        head = git(repo, "rev-parse", "HEAD")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=baseline, head=head, scopes=["file:src/a1.py"]
            )
        self.assertIn("empty commit", str(caught.exception))

    def test_rejects_an_empty_range(self):
        repo, baseline, _ = self.three_commit_branch()
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=baseline, head=baseline, scopes=["file:src/a1.py"]
            )
        self.assertIn("empty", str(caught.exception))

    def test_rejects_a_head_that_does_not_descend_the_baseline(self):
        """F4: an unrelated commit proves nothing about this task."""
        repo, baseline, _ = self.three_commit_branch()
        git(repo, "checkout", "-q", "--orphan", "unrelated")
        git(repo, "rm", "-rqf", ".")
        unrelated = commit_file(repo, "other.py", "x = 1\n", "unrelated history")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=baseline, head=unrelated, scopes=["file:other.py"]
            )
        self.assertIn("ancestor", str(caught.exception))

    def test_rejects_a_merge_inside_the_implementation_range(self):
        """One worktree per implementer means the implementation range is
        linear. A merge inside it belongs to integration, not to the task."""
        repo, baseline, _ = self.three_commit_branch()
        git(repo, "checkout", "-q", "-b", "side", baseline)
        commit_file(repo, "src/side.py", "side = 1\n", "side work")
        git(repo, "checkout", "-q", "task/T1")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
        head = git(repo, "rev-parse", "HEAD")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=baseline, head=head,
                scopes=["file:src/a1.py", "file:src/side.py"],
            )
        self.assertIn("linear", str(caught.exception))

    def test_rejects_an_out_of_scope_path(self):
        repo, baseline, _ = self.three_commit_branch()
        head = commit_file(repo, "src/escaped.py", "escaped = 1\n", "out of scope")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.verify_source_range(
                repo, baseline=baseline, head=head, scopes=["file:src/a1.py"]
            )
        self.assertIn("src/escaped.py", str(caught.exception))

    def test_accepts_a_tree_scope_covering_every_changed_path(self):
        repo, baseline, _ = self.three_commit_branch()
        head = commit_file(repo, "src/deep/nested.py", "nested = 1\n", "in a tree")
        proof = state.verify_source_range(
            repo, baseline=baseline, head=head, scopes=["tree:src"]
        )
        self.assertIn("src/deep/nested.py", proof["changed_paths"])

    def test_rejects_untyped_or_absent_scopes(self):
        repo, baseline, commits = self.three_commit_branch()
        with self.assertRaises(state.PlanMetadataError):
            state.verify_source_range(
                repo, baseline=baseline, head=commits[-1], scopes=["src/a1.py"]
            )
        with self.assertRaises(state.TrackerValidationError):
            state.verify_source_range(
                repo, baseline=baseline, head=commits[-1], scopes=[]
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k SourceRangeTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'verify_source_range'` The run must still report `Ran 9 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

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

def _commit_parents(repo, commit: str) -> tuple:
    return tuple(_git_out(repo, "rev-list", "--parents", "-n", "1", commit).split()[1:])


def verify_source_range(repo, *, baseline: str, head: str, scopes, transcript: str) -> dict:
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
    # `--no-renames` is LOAD-BEARING, not a style choice. With rename detection
    # on -- the DEFAULT -- git reports only a rename's destination. Measured:
    # a task whose declared scope is `mine/` runs `git mv theirs/victim.py
    # mine/victim.py`; `git diff --name-only` then prints only `mine/victim.py`,
    # every path is inside the declared scope, and THIS CHECK PASSES while the
    # task has deleted another task's file. `--no-renames` prints both paths and
    # the check refuses. The pathspec-limited guard in the Global Constraints is
    # NOT affected -- limiting by path makes git report the source side -- so do
    # not "fix" that one to match.
    changed = tuple(line for line in _parse_range_transcript(transcript).paths if line)
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
    return {"baseline": base, "head": tip, "commits": commits,
            "changed_paths": changed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): prove source ranges against the reserved baseline"
```

---

### Task 9: `publish_worker_result`

> **CROSS-PHASE CONTRACT, raised by the P04 Task 4 review and SETTLED HERE.**
> P06's reviewer-independence check (`owner_history`) scans the tree of
> immutable worker results for owners the tracker no longer names. It was
> written against `run_dir / "results"` with a regex. Two of the three things
> the raising note claimed are true; one is not, and it is corrected here so
> nobody re-fixes a working part.
>
> **1. The directory was wrong. `agent-output/` wins; P06 moves.** P04 writes
> `run_dir / "agent-output"`, and that is also the tree **P07 publishes in
> `SKILL.md`** as the run layout a user reads. `results/` appears nowhere but
> `owner_history` and its own test helper. The reader moves, not the published
> layout. The failure was silent in the fail-open direction — the scan
> contributed the empty set and `owner_history` returned only the owners it
> already had from tracker rows — so **a worker released after finishing a
> task could be drawn to review its own work**, which is the one property this
> check exists to enforce.
>
> **2. The grammar was NOT wrong. Do not "fix" it.** The raising note said
> `render_worker_result` emits the owner as a table cell rather than as
> `- **Owner:** <id>`. It emits **both**: the table carries an `owner` field
> and the document also carries the pinned line, produced by `_owner_line`,
> which P04 documents as "THE SINGLE CONVERSION POINT for the owner grammar
> P06 parses, in both directions" and which names this very pattern. The
> reverse direction is `_screen_owner_line`, and both share the pinned
> constant `_OWNER_LINE_PREFIX = "- **Owner:** "`. The master plan's pin
> (`:354`) is honoured. The note was checking `render_worker_result`'s own body
> rather than its call tree — the mistake Rule 10 exists to prevent.
>
> **3. The regex cannot be written at all, grammar notwithstanding.** `re` is
> **not in `ALLOWED_IMPORTS`** (`__future__, contextlib, copy, errno, fcntl,
> hashlib, json, msvcrt, os, pathlib, time, types`), so `_OWNER_LINE =
> re.compile(...)` is refused by the import guard before it ever runs. Because
> the grammar is already pinned as a **prefix constant**, the fix is smaller
> than a regex, not larger: `line.startswith(_OWNER_LINE_PREFIX)` and take the
> remainder. That keeps P04's single conversion point single — a second
> spelling of the grammar here would be exactly the two-answers defect
> `_owner_line` was written to prevent.
>
> **Do not reach for `parse_worker_result` instead.** It refuses anything not
> byte-for-byte canonical, so one unrelated `.md` under the tree would stop the
> master gate. The prefix scan reads the one field this check needs.
>
> **4. The scan has the Rule 11 hazard.** `read_text` over `rglob("*.md")` with
> no regular-file door: a FIFO under `agent-output/` blocks the master gate
> forever, holding the run lock — the same defect as P04 Task 5's C1. The scan
> below uses `_require_regular_file`.
>
> `_SPEC_TRACE` at Task 5 is the **second** `re` site in this phase and is
> corrected the same way; see the note there.


A worker publishes its own immutable result and nothing else. Publication is atomic and no-clobber: republishing byte-identical content is an idempotent no-op, and any other content at the same path is conflicting evidence, not an update. `publish_immutable` returns the sha256 hex digest, so `publish_worker_result` computes the repository-relative path itself and checks the returned digest against the content it rendered.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: P02's `publish_immutable` (returns a digest), `validate_run`, `repo_root`; `render_worker_result`.
- Produces: `worker_result_path(run_dir, *, task_id, attempt) -> Path`; `publish_worker_result(run_dir, *, result: dict) -> str`.

> **This tree has a consumer outside P04.** P06's `owner_history` scans
> `<run_dir>/agent-output/**/*.md` for owners the tracker no longer names, and
> decides master-reviewer independence on what it finds. Two things are
> therefore binding and may not be changed by a later task without changing
> `phase-06-master-gate.md` in the same commit: the **directory name**
> `agent-output/`, and the **owner line** `_owner_line` emits. P06 reads that
> line through P04's own `_OWNER_LINE_PREFIX` rather than re-spelling it, so
> the grammar has exactly one definition — but that also means a change here
> silently changes the independence check there. The published result is not
> only a record; it is the evidence a released worker existed.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 9 tests
# --------------------------------------------------------------------------

class PublishWorkerResultTests(TempDirTestCase):

    def test_writes_a_canonical_immutable_file(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        relative = state.publish_worker_result(run_dir, result=worker_result())
        self.assertFalse(Path(relative).is_absolute())
        self.assertIn("agent-output", relative)
        published = repo / relative
        self.assertTrue(published.is_file())
        self.assertEqual(
            state.parse_worker_result(published.read_text(encoding="utf-8")),
            worker_result(),
        )

    def test_content_digest_matches_what_publish_immutable_reported(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        relative = state.publish_worker_result(run_dir, result=worker_result())
        expected = hashlib.sha256((repo / relative).read_bytes()).hexdigest()
        rendered = state.render_worker_result(worker_result())
        self.assertEqual(
            hashlib.sha256(rendered.encode("utf-8")).hexdigest(), expected
        )

    def test_is_idempotent_for_identical_content(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        first = state.publish_worker_result(run_dir, result=worker_result())
        before = (repo / first).read_bytes()
        second = state.publish_worker_result(run_dir, result=worker_result())
        self.assertEqual(second, first)
        self.assertEqual((repo / first).read_bytes(), before)

    def test_refuses_to_overwrite_conflicting_content(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        relative = state.publish_worker_result(run_dir, result=worker_result())
        before = (repo / relative).read_bytes()
        with self.assertRaises(state.TrackerValidationError):
            state.publish_worker_result(
                run_dir, result=worker_result(concerns="changed my mind")
            )
        self.assertEqual((repo / relative).read_bytes(), before)

    def test_validates_before_writing_anything(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        with self.assertRaises(state.TrackerValidationError):
            state.publish_worker_result(
                run_dir, result=quorum_result("NEEDS_CONTEXT", question_record="-")
            )
        self.assertFalse((run_dir / "agent-output").exists())

    def test_result_path_is_attempt_scoped(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        first = state.worker_result_path(run_dir, task_id="T1", attempt=1)
        second = state.worker_result_path(run_dir, task_id="T1", attempt=2)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, second.parent)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k PublishWorkerResultTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'publish_worker_result'` The run must still report `Ran 6 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

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
    return (Path(run_dir) / "agent-output" / task_id.replace("/", "-")
            / f"attempt-{attempt}.md")


def publish_worker_result(run_dir, *, result: dict) -> str:
    """Publish one immutable attempt result; return its repository-relative path."""
    content = render_worker_result(result)          # validates before any write
    path = worker_result_path(
        run_dir, task_id=result["task_id"], attempt=result["attempt"]
    )
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise TrackerValidationError(
                f"a conflicting immutable result already exists at {path}"
            )
    else:
        digest = publish_immutable(str(path), content)   # returns the sha256 digest
        if digest != hashlib.sha256(content.encode("utf-8")).hexdigest():
            raise TrackerValidationError(
                "published content digest does not match the rendered result"
            )
    repo = _repo_dir(validate_run(run_dir))
    return path.resolve().relative_to(repo).as_posix()
```

`publish_immutable` is P02's no-clobber atomic publication and returns the content digest. The pre-check above turns its clobber refusal into the documented distinction between an idempotent replay and conflicting evidence; the digest comparison proves the bytes on disk are the bytes that were validated.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): publish attempt-scoped immutable worker results"
```

---

### Task 10: `import_worker_result` — identity, routing, and completion (faults F3–F6)

A worker saying `DONE` is not completion evidence. The controller imports a result only after validating its immutable four-part identity, the approved task definition, the required files, the Git facts, and the digest-bound typed PASS record. All five statuses and both kinds undergo the same four-part assignment check.

Routing is where pipeline-auto departs from `superb:pipeline`: `NEEDS_CONTEXT` and `PLAN_CONFLICT` park the attempt at `[?]` with a **quorum** marker and a resolvable question record; `BLOCKED` parks it at `[?]` with a **halt** marker. The controller reads the marker; it never infers the route from the wording.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `parse_worker_result`, **`source_range_commands`** (the controller runs the argv itself — see below), `verify_source_range`, `resolve_evidence`, `_approved_definition`, `_repo_dir`, `_attempt_baseline`, P02's `locked_tracker_update`, `derive_next_action`.
- Produces: `QUORUM_ROUTE = "quorum"`, `HALT_ROUTE = "halt"`; `_attempt_baseline(row, attempt) -> str`; `_result_identity(path, content, repo) -> tuple[str, str]`; `_validate_task_test_evidence(...)`; `import_worker_result(run_dir, *, result_path) -> dict`; **`_task_branch(tracker, task_id) -> str`** and **`_range_transcript(repo, argv) -> str`** (both new, both argued below).

#### The defence Task 8 defers here, and the three things that have to exist for it to work

`verify_source_range`'s module header names **this task** as the defence
against a worker that "names commits that do not exist" — Task 8 reads no git
object, so a fabricated intermediate commit spliced into a chain that still
starts at the baseline and ends at the head is accepted there. That deferral
was honest but it pointed at something that, as this section was first
sketched, **could not have been built**. All three were measured against the
sketch below:

1. **The call omitted `transcript=`.** `verify_source_range(repo, *, baseline,
   head, head_ref, scopes, transcript)` has no default on `transcript`, so the
   sketched call raised `TypeError: missing 1 required keyword-only argument`.
2. **Nothing said where the transcript came from, and the only comparison
   present was circular.** `proof["commits"]` is parsed out of whatever
   transcript is passed. If that transcript is the worker's, then
   `tuple(result["commits"]) != proof["commits"]` compares the worker's list
   against the worker's own document and defeats nothing. The header's phrase
   is "the **controller's own** transcript", and that is a requirement on this
   task, not a description of one.
3. **`task_branch` was never bound.** The name appeared once in the whole
   phase plan — in the sketch — and was never derived or persisted.

So the rule for this task, and it is not optional:

**THE CONTROLLER RUNS THE COMMAND ITSELF.** `import_worker_result` calls
`source_range_commands(repo, baseline=…, head=…, head_ref=…)`, executes the
argv it returns, and passes the captured **stdout** as `transcript`. The
worker's document contributes `head` (a *claim*, which `_range_ends` checks
against the ref store's tip) and `commits` (a *claim*, which the comparison
below checks). It contributes **no transcript and no branch name**. A
transcript taken from the worker's document would make the cross-comparison
compare the worker with itself, which is worse than no check because it reads
as one.

- `_range_transcript(repo, argv)` is the one place the argv is executed, so the
  emitted command and the executed command cannot drift. It captures stdout
  **raw** — no `.strip()`: the leading NUL record separator and the trailing
  newline are both load-bearing in the grammar Task 8 parses, and stripping
  either turns a valid transcript into a grammar refusal.
- `subprocess` is off `pipeline_auto_state.py`'s import list and stays off it.
  The execution lives in the **controller**, which is why Task 8 emits an argv
  instead of running one; if `import_worker_result` is itself inside the
  module, then the module gains a `run_command` **callable parameter** the
  controller supplies and the AST screen keeps `subprocess` out. Decide which
  before writing the test, and write the decision here.

**`head_ref` comes from `_task_branch(tracker, task_id)`, never from the
worker.** The worker-result grammar has fourteen fields and none is a branch;
adding one would put the anchor back on the worker's word, which is the whole
reason `head_ref` exists. The name is **derived, not stored**: `task/<task_id>`
is already this phase's pinned spelling — `_validate_task_test_evidence` below
requires an evidence record whose `subject` is `f"task/{result['task_id']}"`,
and Task 11's fixtures merge `task/T2` — and Task 9's fix round made the
derivation total by refusing **at reservation** any task id that
`git check-ref-format` rejects, so there is no id in a tracker that cannot be
spelled as this branch. `_task_branch(tracker, task_id)` therefore reads the
id out of the tracker row the controller already holds, spells the branch, and
asserts the spelling against the same grammar `reserve_task` used — one
derivation, used by the evidence check and the range check alike, so the two
cannot come to different conclusions about which branch the task is on. If a
future topology needs a name that is not derivable, it goes in a run field the
**controller** writes at reservation; it never arrives in the result.

**The comparison is then worker-claim against controller-evidence:**

```python
if tuple(result["commits"]) != proof["commits"]:
    raise TrackerValidationError(
        "implementation commits must equal the complete ordered "
        "baseline-to-source range"
    )
```

with `result["commits"]` read out of the worker's document and
`proof["commits"]` read out of a transcript **the controller captured** from a
command **the module emitted**. That is a genuine cross-comparison, and it is
what closes the fabricated-commit gap: a commit the worker invented is not in
the controller's `git log` output, so the two tuples differ.

**What it still does not close, stated so Task 11 does not over-read it:** a
controller that fabricates the transcript defeats this and everything else, and
neither task proves the **baseline** is a commit in the repository — it is the
sha `reserve_task` resolved at reservation and the target branch has moved on.
Task 8's header says so; do not weaken that sentence here.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 10 tests -- faults F3, F4, F5, F6
# --------------------------------------------------------------------------

class ImportWorkerResultTests(TempDirTestCase):

    def reserved_run(self, *, worker_limit: int = 6):
        repo, run_dir, plan = make_run(
            self.tmp, three_disjoint_tasks(), worker_limit=worker_limit
        )
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        return repo, run_dir

    def implement(self, repo, count: int = 2):
        """Commit `count` in-scope commits on a task branch; return its commits."""
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        return tuple(
            commit_file(repo, "src/a1.py", f"value = {index}\n", f"step {index}")
            for index in range(1, count + 1)
        )

    def done_result(self, repo, run_dir, commits, **overrides) -> dict:
        digest = write_evidence(
            run_dir / "evidence", code_state=commits[-1],
            commands='["python3 -m unittest -k T1"]',
        )
        return worker_result(
            source_ref=commits[-1], commits=commits,
            tests=("python3 -m unittest -k T1",),
            evidence=(f"evidence/T1.md#sha256={digest}",),
            **overrides,
        )

    def publish(self, repo, run_dir, result) -> Path:
        return repo / state.publish_worker_result(run_dir, result=result)

    def test_imports_a_complete_source_result(self):
        repo, run_dir = self.reserved_run()
        commits = self.implement(repo)
        path = self.publish(repo, run_dir, self.done_result(repo, run_dir, commits))
        tracker = state.import_worker_result(run_dir, result_path=path)
        row = task_row(tracker, "T1")
        self.assertEqual(row["state"], "[x]")
        self.assertEqual(row["source_ref"], commits[-1])
        self.assertEqual(row["commits"], ",".join(commits))
        self.assertEqual(row["integration"], "-")
        self.assertIn("completed:attempt-001", row["checkpoints"])
        self.assertTrue(state.derive_next_action(tracker))

    def test_rejects_every_four_part_identity_mismatch(self):
        """F6: run_id + task_id + attempt + owner must match the controller's
        persisted assignment exactly."""
        cases = (
            {"run_id": "run-other"},
            {"task_id": "T2"},
            {"attempt": 2},
            {"owner": "impl-9"},
        )
        for override in cases:
            with self.subTest(override=override):
                repo, run_dir = self.reserved_run()
                commits = self.implement(repo)
                result = self.done_result(repo, run_dir, commits, **override)
                path = self.publish(repo, run_dir, result)
                before = (run_dir / "progress.md").read_bytes()
                with self.assertRaises(state.TrackerValidationError):
                    state.import_worker_result(run_dir, result_path=path)
                self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_rejects_a_head_tilde_one_truncated_commit_list(self):
        """F3: the persisted baseline, not HEAD~1. A truncated list drops the
        earlier commits from every check."""
        repo, run_dir = self.reserved_run()
        commits = self.implement(repo, count=3)
        result = self.done_result(repo, run_dir, commits)
        result["commits"] = commits[-1:]            # what HEAD~1 would have yielded
        path = self.publish(repo, run_dir, result)
        with self.assertRaises(state.TrackerValidationError) as caught:
            state.import_worker_result(run_dir, result_path=path)
        self.assertIn("complete ordered", str(caught.exception))

    def test_rejects_an_extra_pre_baseline_commit(self):
        """F4: a pre-baseline commit is not part of this task's range."""
        repo, run_dir = self.reserved_run()
        baseline = git(repo, "rev-parse", "target")
        commits = self.implement(repo)
        result = self.done_result(repo, run_dir, commits)
        result["commits"] = (baseline,) + commits
        path = self.publish(repo, run_dir, result)
        with self.assertRaises(state.TrackerValidationError):
            state.import_worker_result(run_dir, result_path=path)

    def test_rejects_evidence_bound_to_a_different_code_state(self):
        repo, run_dir = self.reserved_run()
        commits = self.implement(repo)
        digest = write_evidence(
            run_dir / "evidence", code_state=commits[0],   # not the source head
            commands='["python3 -m unittest -k T1"]',
        )
        result = worker_result(
            source_ref=commits[-1], commits=commits,
            tests=("python3 -m unittest -k T1",),
            evidence=(f"evidence/T1.md#sha256={digest}",),
        )
        path = self.publish(repo, run_dir, result)
        with self.assertRaises(state.TrackerValidationError):
            state.import_worker_result(run_dir, result_path=path)

    def test_rejects_evidence_naming_a_different_command_tuple(self):
        repo, run_dir = self.reserved_run()
        commits = self.implement(repo)
        digest = write_evidence(
            run_dir / "evidence", code_state=commits[-1],
            commands='["python3 -m unittest -k something-else"]',
        )
        result = worker_result(
            source_ref=commits[-1], commits=commits,
            tests=("python3 -m unittest -k T1",),
            evidence=(f"evidence/T1.md#sha256={digest}",),
        )
        path = self.publish(repo, run_dir, result)
        with self.assertRaises(state.TrackerValidationError):
            state.import_worker_result(run_dir, result_path=path)

    def test_quorum_statuses_park_the_attempt_with_a_quorum_marker(self):
        """F5: the question record must exist and match its digest."""
        for status in state.QUORUM_STATUSES:
            with self.subTest(status=status):
                repo, run_dir = self.reserved_run()
                digest = (run_dir / "questions").mkdir(parents=True, exist_ok=True)
                content = f"# Question for {status}\n"
                (run_dir / "questions" / "q1.md").write_text(content, encoding="utf-8")
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                reference = f"questions/q1.md#sha256={digest}"
                result = quorum_result(status, question_record=reference)
                path = self.publish(repo, run_dir, result)
                tracker = state.import_worker_result(run_dir, result_path=path)
                row = task_row(tracker, "T1")
                self.assertEqual(row["state"], "[?]")
                self.assertEqual(row["question"], f"{state.QUORUM_ROUTE}:{reference}")

    def test_quorum_status_with_an_unresolvable_question_record_is_rejected(self):
        repo, run_dir = self.reserved_run()
        result = quorum_result(
            "NEEDS_CONTEXT", question_record=f"questions/absent.md#sha256={DIGEST}"
        )
        path = self.publish(repo, run_dir, result)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(state.TrackerValidationError):
            state.import_worker_result(run_dir, result_path=path)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_blocked_parks_the_attempt_with_a_halt_marker(self):
        repo, run_dir = self.reserved_run()
        result = worker_result(
            status="BLOCKED", source_ref="-", commits=(), evidence=(),
            blocking_reason="no staging credential",
        )
        path = self.publish(repo, run_dir, result)
        tracker = state.import_worker_result(run_dir, result_path=path)
        row = task_row(tracker, "T1")
        self.assertEqual(row["state"], "[?]")
        self.assertEqual(row["question"],
                         f"{state.HALT_ROUTE}:no staging credential")

    def test_import_replay_is_an_idempotent_no_op(self):
        repo, run_dir = self.reserved_run()
        commits = self.implement(repo)
        path = self.publish(repo, run_dir, self.done_result(repo, run_dir, commits))
        state.import_worker_result(run_dir, result_path=path)
        snapshot = (run_dir / "progress.md").read_bytes()
        tracker = state.import_worker_result(run_dir, result_path=path)
        self.assertEqual((run_dir / "progress.md").read_bytes(), snapshot)
        self.assertEqual(task_row(tracker, "T1")["state"], "[x]")

    def test_changed_content_under_an_accepted_identity_is_conflicting(self):
        repo, run_dir = self.reserved_run()
        commits = self.implement(repo)
        path = self.publish(repo, run_dir, self.done_result(repo, run_dir, commits))
        state.import_worker_result(run_dir, result_path=path)
        tampered = path.read_text(encoding="utf-8").replace(
            "| concerns | - |", "| concerns | quietly edited |"
        )
        path.write_text(tampered, encoding="utf-8")
        with self.assertRaises(state.TrackerValidationError):
            state.import_worker_result(run_dir, result_path=path)

    def test_artifact_result_must_name_the_exact_approved_outputs(self):
        body = task_block("T1", kind="artifact", write_scope="tree:docs",
                          outputs="docs/out.md")
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=6)
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "out.md").write_text("output\n", encoding="utf-8")
        digest = write_evidence(
            run_dir / "evidence", code_state=git(repo, "rev-parse", "target"),
            subject="task/T1", commands='["python3 -m unittest -k T1"]',
        )
        wrong = worker_result(
            kind="artifact", source_ref="-", commits=(),
            artifacts=("docs/other.md",), tests=("python3 -m unittest -k T1",),
            evidence=(f"evidence/T1.md#sha256={digest}",),
        )
        path = self.publish(repo, run_dir, wrong)
        with self.assertRaises(state.TrackerValidationError):
            state.import_worker_result(run_dir, result_path=path)

    def test_rejects_a_result_for_a_task_that_is_not_active(self):
        repo, run_dir, _ = make_run(self.tmp, three_disjoint_tasks(), worker_limit=6)
        result = worker_result(
            status="BLOCKED", source_ref="-", commits=(), evidence=(),
            blocking_reason="never started",
        )
        path = self.publish(repo, run_dir, result)
        with self.assertRaises(state.TrackerValidationError):
            state.import_worker_result(run_dir, result_path=path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ImportWorkerResultTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'import_worker_result'` The run must still report `Ran 13 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: controller-side result import
#
# A worker saying DONE is not completion evidence. All five statuses and both
# kinds undergo the same four-part identity check. Routing is explicit:
# NEEDS_CONTEXT / PLAN_CONFLICT -> quorum, BLOCKED -> halt.
# ---------------------------------------------------------------------------

QUORUM_ROUTE = "quorum"
HALT_ROUTE = "halt"


def _attempt_baseline(row: dict, attempt: int) -> str:
    prefix = f"baseline:{_attempt_token(attempt)}@"
    matches = [
        item.removeprefix(prefix) for item in _csv(row["checkpoints"])
        if item.startswith(prefix)
    ]
    if len(matches) != 1 or not _COMMIT.fullmatch(matches[0]):
        raise TrackerValidationError(
            "a source attempt needs exactly one recorded full-commit baseline"
        )
    return matches[0]


def _result_identity(result_path: Path, content: bytes, repo: Path):
    try:
        relative = result_path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise TrackerValidationError(
            "worker result is outside the repository root"
        ) from exc
    if any(character in relative for character in ",|#"):
        raise TrackerValidationError(
            "worker result path contains an unsupported identity delimiter"
        )
    return f"{relative}#sha256={hashlib.sha256(content).hexdigest()}", relative


def _validate_task_test_evidence(run_dir, tracker: dict, result: dict,
                                 definition: dict, code_state: str) -> None:
    records = [
        resolve_evidence(run_dir, _repo_dir(tracker), reference)
        for reference in result["evidence"]
    ]
    matching = [
        record for record in records
        if record["purpose"] == "task-test"
        and record["run_id"] == result["run_id"]
        and record["subject"] == f"task/{result['task_id']}"
        and record["attempt"] == _attempt_token(result["attempt"])
    ]
    if len(matching) != 1:
        raise TrackerValidationError(
            "a task needs exactly one digest-bound task-test PASS record naming "
            "its run, task, and attempt"
        )
    record = matching[0]
    if record["code_state"] != code_state:
        raise TrackerValidationError(
            "task-test evidence is bound to a different code state than the "
            "result it accompanies"
        )
    if record["commands"] != definition["commands"] or tuple(result["tests"]) \
            != definition["commands"]:
        raise TrackerValidationError(
            "task-test evidence must name the exact ordered approved task suite"
        )


def import_worker_result(run_dir, *, result_path) -> dict:
    """Validate an immutable result against its active assignment and import once."""
    result_path = Path(result_path)
    try:
        content = result_path.read_bytes()
        published = parse_worker_result(content.decode("utf-8"))
    except (OSError, UnicodeError) as exc:
        raise TrackerValidationError(
            f"worker result is unreadable: {result_path}: {exc}"
        ) from exc
    digest = hashlib.sha256(content).hexdigest()
    transition = f"import-{published['task_id']}-{published['attempt']}-{digest}"

    def mutate(tracker: dict) -> dict:
        repo = _repo_dir(tracker)
        current = result_path.read_bytes()
        result = parse_worker_result(current.decode("utf-8"))
        identity, relative = _result_identity(result_path, current, repo)
        row = _task_row(tracker, result["task_id"])
        accepted = _csv(row["result"])
        if identity in accepted:
            return tracker                           # exact replay: inert
        if any(entry.split("#sha256=", 1)[0] == relative for entry in accepted):
            raise TrackerValidationError(
                "an accepted result path now carries conflicting content"
            )
        if result["run_id"] != _run_field(tracker, "run_id"):
            raise TrackerValidationError("result run identity does not match the tracker")
        if row["state"] != "[~]" or row["attempt"] != _attempt_token(result["attempt"]):
            raise TrackerValidationError(
                "result attempt is not the current active attempt"
            )
        if result["owner"] != row["owner"]:
            raise TrackerValidationError(
                "result owner does not match the controller-assigned owner"
            )
        definition = _approved_definition(run_dir, tracker, row["id"])
        if result["kind"] != row["kind"] or result["kind"] != definition["kind"]:
            raise TrackerValidationError(
                "result kind does not match the approved plan"
            )

        updated = dict(row)
        updated["result"] = _append_history(row["result"], identity)
        updated["verification"] = _append_history(
            row["verification"], f"tests:{','.join(result['tests']) or '-'}"
        )
        for checkpoint in result["checkpoints"]:
            updated["checkpoints"] = _append_history(
                updated["checkpoints"],
                f"worker:{_attempt_token(result['attempt'])}:{checkpoint['id']}:"
                f"{checkpoint['status']}@{checkpoint['evidence']}",
            )

        if result["status"] in COMPLETION_STATUSES:
            if result["kind"] == "source":
                #: `head_ref` is DERIVED by the controller, never read out of
                #: `result`: the worker-result grammar has no branch field and
                #: adding one would put the anchor back on the worker's word.
                branch = _task_branch(tracker, row["id"])
                baseline = _attempt_baseline(row, result["attempt"])
                #: THE CONTROLLER RUNS THE COMMAND. `transcript` is the stdout
                #: the controller captured from the argv the module emitted --
                #: passing the worker's own transcript here would make the
                #: `commits` comparison below compare the worker with itself.
                argv = source_range_commands(
                    repo,
                    baseline=baseline,
                    head=result["source_ref"],
                    head_ref=branch,
                )
                proof = verify_source_range(
                    repo,
                    baseline=baseline,
                    head=result["source_ref"],   # a CLAIM, checked against the tip
                    head_ref=branch,             # NOT from `result`
                    scopes=definition["write_scope"],
                    transcript=_range_transcript(repo, argv),
                )
                #: worker-claim vs controller-evidence. This is the line the
                #: Task 8 header defers "names commits that do not exist" to,
                #: and it only holds because `proof` came from the transcript
                #: ABOVE rather than from the worker's document.
                if tuple(result["commits"]) != proof["commits"]:
                    raise TrackerValidationError(
                        "implementation commits must equal the complete ordered "
                        "baseline-to-source range"
                    )
                _validate_task_test_evidence(
                    run_dir, tracker, result, definition, proof["head"]
                )
                updated.update(source_ref=proof["head"],
                               commits=",".join(proof["commits"]),
                               artifacts="-", integration="-")
            else:
                if tuple(result["artifacts"]) != definition["outputs"]:
                    raise TrackerValidationError(
                        "artifact result does not name the exact approved outputs"
                    )
                for output in result["artifacts"]:
                    if not (repo / output).is_file():
                        raise TrackerValidationError(
                            f"artifact output is missing: {output}"
                        )
                _validate_task_test_evidence(
                    run_dir, tracker, result, definition,
                    _resolved_commit(repo, _run_field(tracker, "target_branch")),
                )
                updated.update(source_ref="-", commits="-",
                               artifacts=",".join(result["artifacts"]),
                               integration="N/A")
            updated["state"] = "[x]"
            updated["checkpoints"] = _append_history(
                updated["checkpoints"], f"completed:{_attempt_token(result['attempt'])}"
            )
        else:
            if result["status"] in QUORUM_STATUSES:
                resolve_question_record(run_dir, tracker, result["question_record"])
                marker = f"{QUORUM_ROUTE}:{result['question_record']}"
            else:
                marker = f"{HALT_ROUTE}:{result['blocking_reason']}"
            updated["state"] = "[?]"
            updated["question"] = marker
            updated["checkpoints"] = _append_history(
                updated["checkpoints"], f"blocked:{_attempt_token(result['attempt'])}@{marker}"
            )
        return _replace_task(tracker, updated)

    return locked_tracker_update(run_dir, transition_id=transition, mutate=mutate)


def resolve_question_record(run_dir, tracker: dict, reference: str) -> str:
    """Resolve a quorum-raising result's question record and verify its digest."""
    relative, digest = _digest_reference(reference)
    for candidate in (Path(run_dir) / relative, _repo_dir(tracker) / relative):
        if not candidate.is_file():
            continue
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            raise TrackerValidationError(
                f"question record digest does not match its content: {reference}"
            )
        return relative
    raise TrackerValidationError(f"question record is missing: {reference}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): route quorum-raising results and validate result identity"
```

---

### Task 11: `integrate_task` — `--no-ff` ancestry and the merge-conflict hard stop (faults F9, F10)

Worktree granularity is one per concurrently dispatched implementer, merged `--no-ff` in task order. `--no-ff` is **load-bearing, not stylistic**: a fast-forward collapses the merge commit, and with it the boundary clause 2 of the ancestry predicate checks. Because the merge commit exists, `git rev-list --reverse <merge>^1..<merge>^2` yields the exact task commit set directly, with no baseline bookkeeping.

The controller performs the merge; `integrate_task` validates and records it. **A merge conflict is a hard stop.** A conflicted `git merge --no-ff` leaves the repository mid-merge with unmerged paths and no merge commit, so `integrate_task` detects that state before anything else, aborts the merge, records nothing, and raises naming **both task ids and both declared scopes**. It never redoes the task alone, never retries, and never resolves with a strategy flag: under typed write-scope validation a conflict should be impossible, so it is evidence a scope declaration was wrong, and redoing the task alone papers over the broken declaration and lets the next task hit the same collision.

The conflict scenario is constructed directly at the Git level in the test. A correct declaration should make it unreachable through the full validated path — which is precisely why reaching it must stop the run rather than recover.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `_git`, `_git_out`, `_resolved_commit`, `_repo_dir`, `_approved_definition`, `resolve_evidence`, `_task_row`, `_replace_task`, `_csv`, `_commit_parents`.
- Produces: `_git_run(repo, *args)`; `_merge_in_progress(repo) -> tuple`; `_colliding_task(tracker, repo, task_id, paths) -> tuple`; `_integration_ancestry(repo, *, commits, branch_tip, merge_commit, target_branch) -> tuple`; `integrate_task(run_dir, *, task_id, merge_commit) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 11 tests -- faults F9 and F10
# --------------------------------------------------------------------------

class IntegrationTests(TempDirTestCase):

    def two_task_run(self, *, scopes=("file:src/a1.py", "file:src/a2.py")):
        body = (
            task_block("T1", order=1, batch="b1", write_scope=scopes[0])
            + task_block("T2", order=2, batch="b2", write_scope=scopes[1])
        )
        repo, run_dir, _ = make_run(self.tmp, body, worker_limit=8)
        return repo, run_dir

    def branch(self, repo, name: str, relative: str, text: str) -> str:
        git(repo, "checkout", "-q", "-b", name, "target")
        head = commit_file(repo, relative, text, f"{name} work")
        git(repo, "checkout", "-q", "target")
        return head

    def merge_no_ff(self, repo, branch: str, message: str) -> str:
        git(repo, "checkout", "-q", "target")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", "-m", message, branch)
        return git(repo, "rev-parse", "HEAD")

    def test_no_ff_merge_creates_the_boundary_the_predicate_checks(self):
        repo, run_dir = self.two_task_run()
        tip = self.branch(repo, "task/T1", "src/a1.py", "one = 1\n")
        merge = self.merge_no_ff(repo, "task/T1", "integrate T1")
        parents = state._commit_parents(repo, merge)
        self.assertEqual(len(parents), 2)
        self.assertEqual(parents[1], tip)
        walked = state._integration_ancestry(
            repo, commits=(tip,), branch_tip=tip, merge_commit=merge,
            target_branch="target",
        )
        self.assertEqual(walked, (tip,))

    def test_a_fast_forward_integration_is_rejected(self):
        """F10: --no-ff is load-bearing. A fast-forward collapses the merge
        commit and destroys the boundary clause 2 checks."""
        repo, run_dir = self.two_task_run()
        tip = self.branch(repo, "task/T1", "src/a1.py", "one = 1\n")
        git(repo, "merge", "-q", "--ff-only", "task/T1")
        head = git(repo, "rev-parse", "HEAD")
        self.assertEqual(head, tip)                       # fast-forwarded
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._integration_ancestry(
                repo, commits=(tip,), branch_tip=tip, merge_commit=head,
                target_branch="target",
            )
        self.assertIn("--no-ff", str(caught.exception))

    def test_clause_one_rejects_a_commit_outside_the_branch_tip(self):
        repo, run_dir = self.two_task_run()
        tip = self.branch(repo, "task/T1", "src/a1.py", "one = 1\n")
        stray = self.branch(repo, "task/T2", "src/a2.py", "two = 2\n")
        merge = self.merge_no_ff(repo, "task/T1", "integrate T1")
        with self.assertRaises(state.TrackerValidationError):
            state._integration_ancestry(
                repo, commits=(tip, stray), branch_tip=tip, merge_commit=merge,
                target_branch="target",
            )

    def test_clause_two_rejects_a_merge_outside_the_target_branch(self):
        repo, run_dir = self.two_task_run()
        tip = self.branch(repo, "task/T1", "src/a1.py", "one = 1\n")
        git(repo, "checkout", "-q", "-b", "elsewhere", "target")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", "-m", "off target", "task/T1")
        merge = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "target")
        with self.assertRaises(state.TrackerValidationError) as caught:
            state._integration_ancestry(
                repo, commits=(tip,), branch_tip=tip, merge_commit=merge,
                target_branch="target",
            )
        self.assertIn("target", str(caught.exception))

    def test_integrate_task_records_the_merge_commit(self):
        repo, run_dir = self.two_task_run()
        tip = self.branch(repo, "task/T1", "src/a1.py", "one = 1\n")
        set_task_state(run_dir, "T1", state="[x]", commits=tip, source_ref=tip,
                       owner="impl-1", attempt="attempt-001")
        merge = self.merge_no_ff(repo, "task/T1", "integrate T1")
        tracker = state.integrate_task(run_dir, task_id="T1", merge_commit=merge)
        row = task_row(tracker, "T1")
        self.assertEqual(row["integration"], merge)
        self.assertEqual(git(repo, "rev-parse", "target"), merge)

    def test_integrate_task_replay_is_inert(self):
        repo, run_dir = self.two_task_run()
        tip = self.branch(repo, "task/T1", "src/a1.py", "one = 1\n")
        set_task_state(run_dir, "T1", state="[x]", commits=tip, source_ref=tip,
                       owner="impl-1", attempt="attempt-001")
        merge = self.merge_no_ff(repo, "task/T1", "integrate T1")
        state.integrate_task(run_dir, task_id="T1", merge_commit=merge)
        snapshot = (run_dir / "progress.md").read_bytes()
        state.integrate_task(run_dir, task_id="T1", merge_commit=merge)
        self.assertEqual((run_dir / "progress.md").read_bytes(), snapshot)

    def test_a_merge_conflict_is_a_hard_stop_naming_both_tasks_and_scopes(self):
        """F9: a conflict proves a scope declaration was wrong. Redoing the task
        alone papers over that and lets the next task collide again."""
        repo, run_dir = self.two_task_run()
        # Both branches touch src/shared.py, which NEITHER declared. Constructed
        # directly: a correct declaration should make this unreachable.
        first = self.branch(repo, "task/T1", "src/shared.py", "shared = 1\n")
        second = self.branch(repo, "task/T2", "src/shared.py", "shared = 2\n")
        merged = self.merge_no_ff(repo, "task/T1", "integrate T1")
        set_task_state(run_dir, "T1", state="[x]", commits=first,
                       source_ref=first, integration=merged,
                       owner="impl-1", attempt="attempt-001")
        set_task_state(run_dir, "T2", state="[x]", commits=second,
                       source_ref=second, owner="impl-2", attempt="attempt-001")

        # The controller attempts the merge; git leaves the tree mid-merge.
        conflicted = state._git_run(
            repo, "merge", "--no-ff", "--no-edit", "-m", "integrate T2", "task/T2"
        )
        self.assertNotEqual(conflicted.returncode, 0)

        with self.assertRaises(state.TrackerValidationError) as caught:
            state.integrate_task(run_dir, task_id="T2", merge_commit=second)
        message = str(caught.exception)
        for fragment in ("HARD STOP", "T1", "T2", "file:src/a1.py",
                         "file:src/a2.py", "src/shared.py"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, message)

        # Hard stop: the merge was aborted, nothing was recorded, no retry and
        # no redo-alone happened.
        self.assertEqual(git(repo, "status", "--short"), "")
        self.assertEqual(git(repo, "rev-parse", "HEAD"), merged)
        tracker = state.validate_run(run_dir)
        self.assertEqual(task_row(tracker, "T2")["integration"], "-")

    def test_integrate_task_refuses_an_unfinished_task(self):
        repo, run_dir = self.two_task_run()
        tip = self.branch(repo, "task/T1", "src/a1.py", "one = 1\n")
        merge = self.merge_no_ff(repo, "task/T1", "integrate T1")
        with self.assertRaises(state.TrackerValidationError):
            state.integrate_task(run_dir, task_id="T1", merge_commit=merge)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k IntegrationTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute '_integration_ancestry'` The run must still report `Ran 8 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: integration
#
# One worktree per concurrently dispatched implementer, merged --no-ff in task
# order. --no-ff is LOAD-BEARING: a fast-forward collapses the merge commit and
# destroys the boundary clause 2 checks. A conflict is a HARD STOP, because
# under typed write-scope validation a conflict should be impossible and is
# therefore evidence the scope declaration was wrong.
# ---------------------------------------------------------------------------

def _git_run(repo, *args: str):
    return subprocess.run(
        ("git", "-C", str(repo), *args), capture_output=True, text=True, check=False
    )


def _merge_in_progress(repo) -> tuple:
    """Return the unmerged paths if the repository is mid-merge, else ()."""
    if _git_run(repo, "rev-parse", "--verify", "MERGE_HEAD").returncode != 0:
        return ()
    return tuple(
        line for line in
        _git_out(repo, "diff", "--name-only", "--diff-filter=U").splitlines() if line
    ) or ("<unnamed>",)


def _colliding_task(tracker: dict, repo, task_id: str, paths) -> tuple:
    """Name the other task whose recorded commits touched a conflicting path."""
    for path in paths:
        for row in tracker.get("tasks", ()):
            other_id = _field(row, "ID")
            if other_id == task_id:
                continue
            for commit in _csv(row["commits"]):
                touched = _git_out(
                    repo, "show", "--pretty=format:", "--name-only", commit
                ).split()
                if path in touched:
                    return other_id, path
    return "unknown", (tuple(paths) or ("unknown",))[0]


def _integration_ancestry(repo, *, commits, branch_tip: str, merge_commit: str,
                          target_branch: str) -> tuple:
    """Check the three-clause ancestry predicate for the worktree topology."""
    repo = Path(repo)
    commits = tuple(commits)
    if not commits:
        raise TrackerValidationError("integration needs at least one recorded commit")
    parents = _commit_parents(repo, merge_commit)
    if len(parents) != 2:
        raise TrackerValidationError(
            "integration must be a --no-ff merge with exactly two parents; a "
            "fast-forward collapses the merge commit the predicate depends on"
        )
    if parents[1] != branch_tip:
        raise TrackerValidationError(
            "the merge commit's second parent must be the task branch tip"
        )
    # Clause 1: every recorded commit is an ancestor of its own branch tip, and
    # the second-parent walk yields exactly that ordered set.
    for commit in commits:
        if not _git(repo, "merge-base", "--is-ancestor", commit, branch_tip):
            raise TrackerValidationError(
                f"recorded commit {commit} is not an ancestor of the task branch tip"
            )
    walked = tuple(
        line for line in _git_out(
            repo, "rev-list", "--reverse", f"{merge_commit}^1..{merge_commit}^2"
        ).splitlines() if line
    )
    if walked != commits:
        raise TrackerValidationError(
            "the merge's second-parent walk does not equal the recorded ordered "
            f"task commit set: {walked} != {commits}"
        )
    # Clause 2: branch tip -> merge commit -> target branch.
    if not _git(repo, "merge-base", "--is-ancestor", branch_tip, merge_commit):
        raise TrackerValidationError(
            "the task branch tip is not an ancestor of the merge commit"
        )
    if not _git(repo, "merge-base", "--is-ancestor", merge_commit, target_branch):
        raise TrackerValidationError(
            f"the merge commit is not an ancestor of the target branch "
            f"{target_branch}"
        )
    return walked


def integrate_task(run_dir, *, task_id: str, merge_commit: str) -> dict:
    """Record one task's --no-ff integration, or stop hard on a conflict."""

    def mutate(tracker: dict) -> dict:
        repo = _repo_dir(tracker)
        target = _run_field(tracker, "target_branch")
        row = _task_row(tracker, task_id)
        definition = _approved_definition(run_dir, tracker, task_id)

        # The hard stop comes FIRST: a conflicted `git merge --no-ff` leaves the
        # tree mid-merge with no merge commit to validate.
        unmerged = _merge_in_progress(repo)
        if unmerged:
            other_id, path = _colliding_task(tracker, repo, task_id, unmerged)
            other_scope = ()
            if other_id != "unknown":
                other_scope = _approved_definition(
                    run_dir, tracker, other_id
                )["write_scope"]
            raise TrackerValidationError(
                "HARD STOP: the integration merge conflicted, which proves a "
                "write scope declaration was wrong. THE CONTROLLER MUST RUN "
                "`git merge --abort`; this module does not write to the "
                "repository. Not redoing the task alone "
                "-- that papers over the broken declaration and the next task "
                f"collides again. Colliding paths: {', '.join(unmerged)} "
                f"(first: {path}). Task {task_id} declared "
                f"{definition['write_scope']}; task {other_id} declared "
                f"{other_scope}."
            )

        if row["state"] != "[x]" or row["kind"] != "source":
            raise TrackerValidationError(
                "only a completed source task is integrated"
            )
        resolved = _resolved_commit(repo, merge_commit)
        if row["integration"] == resolved:
            return tracker                                   # replay: inert
        if row["integration"] not in {"-", ""}:
            raise TrackerValidationError(
                f"task {task_id} is already integrated at {row['integration']}"
            )
        _integration_ancestry(
            repo, commits=_csv(row["commits"]),
            branch_tip=_resolved_commit(repo, row["source_ref"]),
            merge_commit=resolved, target_branch=target,
        )
        updated = dict(row)
        updated["integration"] = resolved
        updated["verification"] = _append_history(
            row["verification"], f"integration:{resolved}"
        )
        return _replace_task(tracker, updated)

    return locked_tracker_update(
        run_dir, transition_id=f"integrate-{task_id}-{merge_commit}", mutate=mutate
    )
```

P05 and P06 record the matching digest-bound `task-integration` PASS record with `resolve_evidence`; its `code_state` is the **merge commit**, never the task branch tip.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): stop hard on an integration merge conflict"
```

---

### Task 12: `reconcile_run` — file-first recovery (fault F7)

After a compaction, restart, or interruption, the run reconstructs its next action from files and Git, never from conversation memory. A commit that appeared immediately before the interruption is neither automatic success nor grounds to repeat five hours of work. A **missing** result is neither.

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`

**Interfaces:**
- Consumes: `validate_run`, `parse_worker_result`, `import_worker_result`, `_integration_ancestry`, `_repo_dir`, `WORKER_RESULT_MARKER`.
- Produces: `reconcile_run(run_dir) -> dict` returning `{"actions": tuple, "questions": tuple, "diagnostics": tuple}`.

- [ ] **Step 1: Write the failing test**

Append to `plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py`:

```python
# --------------------------------------------------------------------------
# Task 12 tests -- fault F7
# --------------------------------------------------------------------------

class ReconcileRunTests(TempDirTestCase):

    def active_run(self):
        repo, run_dir, plan = make_run(
            self.tmp, three_disjoint_tasks(), worker_limit=6
        )
        state.reserve_task(run_dir, task_id="T1", owner="impl-1", attempt=1)
        return repo, run_dir

    def test_a_missing_result_is_neither_completion_nor_grounds_to_repeat(self):
        """F7: an active attempt with no result stays exactly as it is."""
        repo, run_dir = self.active_run()
        before = (run_dir / "progress.md").read_bytes()
        report = state.reconcile_run(run_dir)
        self.assertIn("await-or-check-live-owner:T1:attempt-001:impl-1", report["actions"])
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)
        tracker = state.validate_run(run_dir)
        row = task_row(tracker, "T1")
        self.assertEqual(row["state"], "[~]")
        self.assertEqual(row["attempt"], "attempt-001")        # no new attempt invented
        self.assertNotIn("[x]", row["state"])

    def test_a_commit_without_a_result_does_not_complete_the_task(self):
        repo, run_dir = self.active_run()
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        commit_file(repo, "src/a1.py", "one = 1\n", "work that was never published")
        report = state.reconcile_run(run_dir)
        self.assertIn("await-or-check-live-owner:T1:attempt-001:impl-1", report["actions"])
        self.assertEqual(task_row(state.validate_run(run_dir), "T1")["state"], "[~]")

    def test_a_matching_result_is_imported_once(self):
        repo, run_dir = self.active_run()
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        commits = (commit_file(repo, "src/a1.py", "one = 1\n", "step 1"),)
        digest = write_evidence(
            run_dir / "evidence", code_state=commits[-1],
            commands='["python3 -m unittest -k T1"]',
        )
        state.publish_worker_result(run_dir, result=worker_result(
            source_ref=commits[-1], commits=commits,
            tests=("python3 -m unittest -k T1",),
            evidence=(f"evidence/T1.md#sha256={digest}",),
        ))
        report = state.reconcile_run(run_dir)
        self.assertIn("imported:T1:attempt-001", report["actions"])
        self.assertEqual(task_row(state.validate_run(run_dir), "T1")["state"], "[x]")
        again = state.reconcile_run(run_dir)
        self.assertNotIn("imported:T1:attempt-001", again["actions"])

    def test_a_result_with_a_contradicting_owner_raises_a_question(self):
        repo, run_dir = self.active_run()
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        commits = (commit_file(repo, "src/a1.py", "one = 1\n", "step 1"),)
        digest = write_evidence(
            run_dir / "evidence", code_state=commits[-1],
            commands='["python3 -m unittest -k T1"]',
        )
        state.publish_worker_result(run_dir, result=worker_result(
            owner="impostor", source_ref=commits[-1], commits=commits,
            tests=("python3 -m unittest -k T1",),
            evidence=(f"evidence/T1.md#sha256={digest}",),
        ))
        before = (run_dir / "progress.md").read_bytes()
        report = state.reconcile_run(run_dir)
        self.assertTrue(
            any(item.startswith("result-owner-contradiction:T1:attempt-001")
                for item in report["questions"])
        )
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_a_malformed_result_candidate_becomes_a_diagnostic_not_a_state_change(self):
        repo, run_dir = self.active_run()
        broken = state.worker_result_path(run_dir, task_id="T1", attempt=1)
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text(
            state.WORKER_RESULT_MARKER + "\n| Field | Value |\n", encoding="utf-8"
        )
        report = state.reconcile_run(run_dir)
        self.assertTrue(
            any(item.startswith("partial-or-malformed-result")
                for item in report["diagnostics"])
        )
        self.assertEqual(task_row(state.validate_run(run_dir), "T1")["state"], "[~]")

    def test_a_completed_unintegrated_source_task_reports_integration_pending(self):
        repo, run_dir = self.active_run()
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        tip = commit_file(repo, "src/a1.py", "one = 1\n", "step 1")
        set_task_state(run_dir, "T1", state="[x]", commits=tip, source_ref=tip)
        report = state.reconcile_run(run_dir)
        self.assertIn("integration-pending:T1", report["actions"])

    def test_a_recorded_integration_outside_the_target_raises_a_question(self):
        repo, run_dir = self.active_run()
        git(repo, "checkout", "-q", "-b", "task/T1", "target")
        tip = commit_file(repo, "src/a1.py", "one = 1\n", "step 1")
        git(repo, "checkout", "-q", "-b", "elsewhere", "target")
        git(repo, "merge", "-q", "--no-ff", "--no-edit", "-m", "off target", "task/T1")
        merge = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "target")
        set_task_state(run_dir, "T1", state="[x]", commits=tip, source_ref=tip,
                       integration=merge)
        report = state.reconcile_run(run_dir)
        self.assertTrue(
            any(item.startswith("integration-contradiction:T1")
                for item in report["questions"])
        )

    def test_a_blocked_task_surfaces_its_route(self):
        repo, run_dir = self.active_run()
        set_task_state(run_dir, "T1", state="[?]",
                       question=f"{state.QUORUM_ROUTE}:questions/q1.md#sha256={DIGEST}")
        report = state.reconcile_run(run_dir)
        self.assertTrue(
            any(item.startswith(f"await-{state.QUORUM_ROUTE}:T1")
                for item in report["actions"])
        )
        set_task_state(run_dir, "T1", question=f"{state.HALT_ROUTE}:no credential")
        report = state.reconcile_run(run_dir)
        self.assertTrue(
            any(item.startswith(f"await-{state.HALT_ROUTE}:T1")
                for item in report["actions"])
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ReconcileRunTests`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'reconcile_run'` The run must still report `Ran 8 tests`. A `-k` pattern that matches nothing still reports OK and exits 0, so the count is the assertion, not the exit status.

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
# ---------------------------------------------------------------------------
# P04: file-first reconciliation
#
# A commit that appeared immediately before an interruption is neither
# automatic success nor grounds to repeat five hours of work. A MISSING result
# is neither. Partial, stale, or contradictory evidence preserves the current
# state and produces a diagnostic or a question.
# ---------------------------------------------------------------------------

def reconcile_run(run_dir) -> dict:
    """Rebuild the next recovery action from authoritative files and Git evidence."""
    run_dir = Path(run_dir)
    tracker = validate_run(run_dir)
    repo = _repo_dir(tracker)
    target = _run_field(tracker, "target_branch")
    actions: list = []
    questions: list = []
    diagnostics: list = []

    # Revalidate every approved phase plan before trusting any task row.
    for phase in tracker.get("phases", ()):
        parse_plan_metadata(_phase_plan_path(tracker, _field(phase, "ID")))

    candidates: list = []
    output_dir = run_dir / "agent-output"
    if output_dir.is_dir():
        for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                diagnostics.append(f"unreadable-result-candidate:{path}:{exc}")
                continue
            if not content.startswith(WORKER_RESULT_MARKER):
                continue
            try:
                candidates.append((path, parse_worker_result(content)))
            except TrackerValidationError as exc:
                diagnostics.append(f"partial-or-malformed-result:{path}:{exc}")

    for row in tracker.get("tasks", ()):
        if row["state"] != "[~]":
            continue
        matches = [
            (path, result) for path, result in candidates
            if result["run_id"] == _run_field(tracker, "run_id")
            and result["task_id"] == row["id"]
            and _attempt_token(result["attempt"]) == row["attempt"]
        ]
        if len(matches) > 1:
            questions.append(f"conflicting-results:{row['id']}:{row['attempt']}")
            continue
        if matches:
            path, result = matches[0]
            if result["owner"] != row["owner"]:
                questions.append(
                    f"result-owner-contradiction:{row['id']}:{row['attempt']}:{path}"
                )
                continue
            try:
                import_worker_result(run_dir, result_path=path)
            except TrackerError as exc:
                questions.append(
                    f"result-evidence-contradiction:{row['id']}:{row['attempt']}:{exc}"
                )
            else:
                actions.append(f"imported:{row['id']}:{row['attempt']}")
            continue
        stale = [
            str(path) for path, result in candidates
            if result["run_id"] == _run_field(tracker, "run_id")
            and result["task_id"] == row["id"]
        ]
        if stale:
            questions.append(
                f"superseded-or-conflicting-result:{row['id']}:{row['attempt']}:"
                f"{','.join(stale)}"
            )
        # A missing result is NOT completion and NOT grounds to repeat the work.
        actions.append(
            f"await-or-check-live-owner:{row['id']}:{row['attempt']}:{row['owner']}"
        )

    tracker = validate_run(run_dir)
    for row in tracker.get("tasks", ()):
        if row["state"] == "[x]" and row["kind"] == "source":
            if row["integration"] in {"-", ""}:
                actions.append(f"integration-pending:{row['id']}")
                continue
            try:
                _integration_ancestry(
                    repo, commits=_csv(row["commits"]),
                    branch_tip=_resolved_commit(repo, row["source_ref"]),
                    merge_commit=row["integration"], target_branch=target,
                )
            except TrackerError as exc:
                questions.append(f"integration-contradiction:{row['id']}:{exc}")
        elif row["state"] == "[x]" and row["kind"] == "artifact":
            if row["integration"] != "N/A":
                questions.append(f"artifact-integration-contradiction:{row['id']}")
        elif row["state"] == "[?]":
            route, _, detail = row["question"].partition(":")
            if route not in {QUORUM_ROUTE, HALT_ROUTE}:
                questions.append(f"unroutable-block:{row['id']}:{row['question']}")
            else:
                actions.append(f"await-{route}:{row['id']}:{detail}")

    return {"actions": tuple(actions), "questions": tuple(questions),
            "diagnostics": tuple(diagnostics)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: OK — the whole P04 suite

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/    # must print nothing
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_task_lifecycle.py
git commit -m "feat(pipeline-auto): reconcile interrupted runs from files and Git"
```

---

## Self-review

**Spec coverage.** P04's row in the spec's phase table reads "Task lifecycle carry-over — reserve/start/resume, typed scopes, result identity, baseline range proof, integration ancestry, reconciliation". Reserve is Task 6; resume is Task 7; typed scopes are Tasks 2, 3, and 6; result identity is Tasks 4, 9, and 10; the baseline range proof is Task 8; integration ancestry is Task 11; reconciliation is Task 12. The spec's "Cost blowup" mitigation (`worker_limit - 3`, brains as three unique owners) is Task 6. The quorum contract's "A worker never dispatches brains… `BLOCKED` still means halt" is Tasks 4 and 10. The recorded default for worktree granularity and the merge-conflict hard stop is Task 11. The master plan's `parse_plan_metadata` is Tasks 1 and 2, `import_phase_plan` is Task 6, `integrate_task` is Task 11, and the two templates are Tasks 4 and 5. Every "P04 produces" signature has a task.

**Placeholder scan.** No TBDs, no "add appropriate error handling", no "similar to Task N". Every step carries the actual test or implementation code. Every `Run:` line names `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v` with **no `-t`**, and every sub-suite step asserts the reported `Ran N tests`. There is no `pytest` invocation, import, decorator, or fixture anywhere in this plan. Both facts were checked by executing the commands, not by reading them.

**Type consistency.** `parse_plan_metadata` returns `{"phase": dict, "tasks": list[dict]}` and every consumer (`_approved_definition`, `reconcile_run`) indexes those dicts by string key, never by attribute. `verify_source_range` returns a dict with `commits` as a `tuple[str, ...]`, and `import_worker_result` compares `tuple(result["commits"])` against it. `_integration_ancestry` returns the same kind of tuple from the second-parent walk and compares it the same way. `implementation_slot_cap` returns an `int`. `scopes_overlap` takes two single scope **strings**; `_scope_sets_overlap` takes two iterables of them — the reservation guard calls the set form, and Task 3 tests both. `publish_worker_result` returns a repository-relative path **string**; `publish_immutable` returns a **digest**, and Task 9 keeps them distinct. **Attempts are `int` in every P04 signature and the token `attempt-NNN` in every tracker cell, checkpoint marker, worker-result document and evidence record**; `_attempt_token` is the one conversion point and every comparison goes through it. `_repo_dir` returns a `Path` built from P02's `repo_root(tracker)`; nothing walks for `.git` and nothing derives the root from `run_dir` depth.

**One deliberate redundancy.** The quorum/halt routing rule is enforced twice: in the codec (Task 4, so a malformed result cannot be published) and at import (Task 10, so a hand-written file cannot be imported). That is not duplication to remove — the publisher and the importer are different trust boundaries.

---

## Resolved interface questions — settled, with where each one landed

The nine items P04 originally reported back have all been answered. They are recorded here so a later reader sees the decision rather than re-deriving it.

| # | Question | Resolution | Where it lands in this plan |
| --- | --- | --- | --- |
| 1 | `initialize_run` seeds no artifact references and no task rows | `initialize_run` writes `phase_plans`, `decisions`, `findings`, `repo_root` and an **empty** `## Tasks`; appending task rows is P04's | Task 6, `import_phase_plan` |
| 2 | No evidence-specific exception type | Reuse `TrackerValidationError`; do **not** invent `EvidenceError` | every rejection path |
| 3 | No public integration transition | `integrate_task(run_dir, *, task_id, merge_commit) -> dict` is public and P04's; a private helper could not be called by P05's gate or exercised by P06's tests | Task 11 |
| 4 | `## Quorum` columns unpinned | Pinned by P02's committed fixture: 12 columns. P04 reads `QID`, `State`, `Owners` and writes none | Tracker column contract |
| 5 | `## Tasks` columns unpinned | Pinned by the same fixture: 16 columns, **no `Deps`**, and `Attempt` is the token `attempt-001` | Tracker column contract, `_attempt_token` |
| 6 | `derive_next_action` vocabulary for the new routes | **SUPERSEDED BY TASK 10.** The halt arm is `halt:<reason>` as answered. The quorum arm is the complete `quorum:<qid>@<path>#sha256=<digest>` and NOT `quorum:<question-record>`: Task 7's `_validate_decision` reads the qid out of this cell to bind a resume grant, splitting on `@`, and a cell holding only the reference yields the whole reference as the "qid" — so the grant it looks for is `Q-<whole reference>`, which no decision id can ever be, and every resume of a quorum-blocked task is refused by the `Q-<qid>` mismatch. (It is refused by THAT arm and not by the "names no qid" arm: the reference is non-empty, so the empty-qid arm never fires. A diagnosis quoted that the code never produces is the same defect in a smaller size.) The action strings stay P02/P03's. Consumers must write and read the full arm — see the note under the interface block above | Task 10 |
| 7 | Marker and comment strings | Accepted as derived, now pinned in this plan so P05 cites rather than re-derives | Pinned marker and comment strings |
| 8 | Artifact-task evidence binding | Accepted as derived: exact outputs on disk, `code_state` bound to the target tip | Task 10 |
| 9 | `EVIDENCE_PURPOSES` after `## Remediation` was dropped | Each phase appends the purposes it needs. P04 ships three; P05 adds `task-review`, `adversarial`; P06 adds `branch-review`, `completeness`, `final`. An unregistered purpose is rejected by design | Task 5, Pinned strings |

**Two things a P04 implementer must do rather than assume.**

Read `plugins/superb/skills/pipeline-auto/tests/fixtures/valid-progress.md` before writing Task 6. The column transcription in this plan is orientation; the fixture is the authority, and it is the thing that changes.

Run the verification tuple. Do not reason about it. The `-t .` that this plan carried in its first two drafts came from an instruction, survived a written claim that it had been verified, and never executed once — `pipeline-auto` is hyphenated, so `-t .` makes discovery resolve the start directory as the module path `plugins.superb.skills.pipeline-auto.tests` and die with `ImportError: Start directory is not importable`. A command that has not been executed is not a verified command.
