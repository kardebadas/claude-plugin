# P05 — Dial and Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the review-intensity dial mechanical and un-lowerable — a round-scoped `## Task Review` ledger, a `## Fix Rounds` ledger, an adversarial-trigger evaluator that fires independently of intensity, a one-way ratchet, and provisional/taint propagation whose rungs inherit downward.

**Architecture:** One appended `# --- dial and gate ---` section in the existing spine, `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`, below P03's and P04's code. The load-bearing design choice is that **nothing here is enforced by a controller branch**. Every never-off rule is a *semantic validation rule* added to P02's `_validate_tracker_semantics` dispatcher, so an illegal completion cannot be written: `locked_tracker_update` re-parses its own render before the atomic replace, so a mutate that marks a task `[x]` in violation raises `TrackerValidationError` and leaves `progress.md` byte-identical. "The dial may never switch off" becomes "the tracker cannot record a run in which it was switched off."

**Tech Stack:** Python 3 standard library only — `re`, `json`, `hashlib`, plus what P02–P04 already import. **`pytest` is NOT installed on this machine and must not be used.** Tests are `unittest.TestCase`, discovered with `python3 -m unittest discover`; written that way they also run under pytest if it ever appears.

**Spec:** `docs/superpowers/specs/2026-09-14-pipeline-auto-design.md`

**Master plan:** `docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md`

**Depends on:** P03 (quorum record, rung ladder), P04 (task lifecycle, typed scopes). Both are built; this phase consumes their signatures verbatim and re-implements none of them.

---

## Global Constraints

Copied verbatim from the master plan. Every task's requirements implicitly include this section.

- `plugins/superb/skills/pipeline/` is **not modified**. Not one line. Verify with `git diff --name-only` before every commit.
- Schema string is exactly `pipeline-auto/v1`; tracker marker is exactly `<!-- pipeline-auto/v1 -->`.
- No migration path from `pipeline-run/v1` or `pipeline-run/v2` exists or is ever added, in either direction.
- A foreign, missing, malformed, or unknown schema is a **read-only stop**: preserve the directory, change no files, dispatch nothing. Rejected input must be **byte-identical** after the rejected parse.
- Rungs are **schema constants, not run configuration**: `specified` 0.95, `code-evidenced` 0.85, `convention-cited` 0.70, `engineering-judgement` 0.55, `speculation` 0.30.
- Adoption floor is `code-evidenced` (0.85). `convention-cited` and everything below it **cannot be adopted** — "the codebase does it this way" is not authority for a machine decision.
- A brain **never types a number**. It selects a rung; the controller derives the value.
- Spread is measured **by rung**: where more than one cluster exists, the winner's rung must be strictly higher than the runner-up's. Equal rungs never adopt. There is no numeric spread threshold, and no separate three-way-split rule — rung strictness subsumes it.
- A rung outside the enum is schema-invalid: re-dispatch that brain once, then escalate. Never default it to a legal value.
- Drift budget: **3 quorum adoptions per phase, 10 per run**, checked **before dispatch**. Escalations never count against it. At most 2 human-granted extensions per run.
- The drift budget caps decision authority, **not** run cost. `agent_dispatch_count` is a separate counter.
- Depth cap is **2**. Human decisions are depth 0.
- Implementation tasks may occupy at most `worker_limit - 3` slots. `worker_limit >= 4` is required for concurrency.
- Exactly three brains per quorum, exactly three readers at stage 01. A count is never reduced to fit capacity.
- Python: standard library only. No new dependencies in any phase.
- No absolute home-directory paths in any committed file. Repository-relative paths only.
- No push, no publish, no PR, no merge into `main`/`master`.

### P05-specific standing rules

These are the spec's dial clauses, restated as the rules this phase's code must make true. Every reviewer of this phase reads them as its constraints block.

1. **The dial controls whether a reviewer runs, never what bar that reviewer applies.** The never-off list from the spec: the adversarial trigger check; typed write-scope declaration and conflict detection; digest-bound typed PASS evidence; the `baseline..source-head` range proof and integration ancestry predicate; immutable four-part worker result identity; TDD RED-before-GREEN evidence; the most-capable-model policy; and the zero-open-findings bar itself.
2. **Adversarial triggers are independent — any single one fires.** The line-count trigger is its own trigger, not a minimum size the others must also meet. **A 10-line auth change is high-risk.**
3. **The ratchet is upward only**, `final-only → required`, mechanically triggered, never downward and never by quorum.
4. **A ratchet does not retroactively review complete tasks.** It gates every remaining task and adds a phase-scoped review over the phase's whole edge at the zero-open-findings bar.
5. **Zero open findings at every severity.** Severity communicates urgency and risk; it is never a fix/no-fix gate.
6. **Rungs inherit downward.** A quorum raised by a tainted task inherits the taint, and its adopted rung is capped at the minimum of its own and the tainting decision's.

---

## What this phase owns, and what it deliberately does not

**Owns:** the round-scoped grammar and semantics of `## Task Review`; the semantics of `## Fix Rounds`; `adversarial_required`; `record_task_review`; `open_fix_round` / `close_fix_round`; `ratchet_triggers_fired` / `ratchet_phase`; `propagate_provisional`; `provisional_constraints_block`; `inherited_rung_cap`; and the five new semantic-validation rules listed below.

**Does not own, and must not re-implement:** the lock, the atomic replace, `locked_tracker_update`, `publish_immutable`, `parse_tracker`/`render_tracker` (P02); rung values, clustering, adoption arithmetic, budget, depth, `finalize_quorum` (P03); `reserve_task`, `resume_task`, `scopes_overlap`, `publish_worker_result`, `import_worker_result`, `verify_source_range`, `reconcile_run` (P04); reviewer dispatch, `DECISION-CHALLENGE` routing, completeness freeze, phase-set immutability (P06).

### Why `## Task Review` is a section and not columns on `## Tasks`

Three reasons, and each of them is a bug someone will otherwise introduce.

**A task has N review rounds, not one.** The gate loop is implement → review → fix → re-review → … → approved, and the number of rounds is data, not a constant. Columns on `## Tasks` force one of two broken shapes: multiple rows per task, which breaks the one-row-per-task invariant every task-replacement helper in P04 assumes (`reserve_task` and `resume_task` locate a task by scanning for its single `ID` row); or one comma-packed history cell, which is exactly how the old pipeline's `Checkpoints` column became unparseable — a cell that accretes `red,green,blocked:attempt-001@path` until no grammar covers it.

**`## Gates` already sets the precedent.** A gate is a repeating record about a phase and it lives in its own section rather than as columns on `## Phases`. A review round is a repeating record about a task; it gets the same treatment for the same reason.

**`## Tasks` is already fifteen columns and at its practical limit.** Adding fourteen more produces a twenty-nine-column table that no renderer diff is readable in and no reviewer can check by eye.

### Why `Intensity` is recorded per round

So that an upward ratchet is **visible in history**. A phase-level `Review Class` cell records only the current class; a run that started `final-only`, ratcheted on an adversarial finding, and finished `required` renders identically to a run that was always `required`. Per-round intensity makes the ratchet an auditable fact — and it is what the intensity-monotonicity rule (Task 4) is checked against.

### Why `Open` is live and the severity counts are historical

`Critical`, `Important` and `Minor` are the immutable counts that round found; they are never rewritten. `Open` is how many of that round's findings remain open **now**. When `record_task_review` appends round N+1, it sets every earlier round of that task to `Open: 0` — a re-review re-examines everything the previous round raised, so its own `Open` count is the authoritative current state and older counts are superseded by construction.

This is what makes "a task may not reach `[x]` while **any** of its `## Task Review` rows has `Open != 0`" a mechanical rule that needs no finding-id bookkeeping, while still preserving the severity history that would otherwise be destroyed by overwriting the counts.

### Why the never-off rules are validator rules, not controller branches

The spec's dial has exactly one shape a competent implementer will reach for:

```python
if phase.review_class == "required":
    run_review_gate()          # <- and the adversarial pass lives in here
```

In SDD's own flow the adversarial pass fires *inside* the task gate, after the task reviewer approves. So the obvious implementation puts the adversarial pass in the `required` branch and switches it off with everything else — one line of entirely plausible code, passing every other test in the suite, violating the never-off list. A controller branch cannot defend against this, because the controller branch *is* the bug.

A validator rule can. `parse_tracker` refuses a tracker in which a task with a fired trigger reached `[x]` without a `safe` adversarial verdict, **at every intensity**; `locked_tracker_update` re-parses its own render before replacing the file; therefore the transition that would record the bug raises instead of landing. Task 2 is that test.

---

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py` | Modify — widen `_TASK_REVIEW_HEADER`, append a `# --- dial and gate (P05) ---` section | All P05 constants, validators and transitions |
| `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py` | Modify — append P05 test classes | P05 tests |
| `plugins/superb/skills/pipeline-auto/tests/fixtures/valid-progress.md` | Modify — migrate `## Task Review` to fourteen columns | The one fully-populated valid tracker |
| `plugins/superb/skills/pipeline-auto/tests/fixtures/final-only-progress.md` | Create | A `final-only` phase carrying mechanical rounds — the substrate for the sharpest test and the ratchet tests |
| `plugins/superb/skills/pipeline-auto/templates/progress.md` | Modify — same fourteen-column header | The template `initialize_run` renders from |

---

## Carried forward from P02 Task 6 (commit `0ecfa77`)

**One ratchet hole is outside P02's reach and is yours to close.** P02 makes a
downward reclassification unspellable: `Class Source` admits only `plan` (no
ratchet record permitted) and `ratchet` (pinned to `required`, and required to
name `<trigger>@<evidence>`). The whole cross product is asserted.

What P02 cannot catch is a phase row claiming `Class Source: plan` while its
phase plan's metadata says `required`. Detecting that needs the plan file, and
the state module never opens one — `PlanMetadataError` exists for the phase that
does. That phase is P05.

Without this check, a controller can buy its way out of the full per-task gate by
writing `plan` over a class it never had, which is the same self-interested move
the one-way ratchet exists to forbid, taking the one route the schema cannot see.
Read the phase plan's metadata and compare.

**Also settled by Task 6:** the `Decisions` column is validated as a grammar
(`H-<n>` | `Q-<qid>`), not referentially. Resolution is against `decisions.md`
per `phase-06-master-gate.md:1438`, and the state module never opens that file.
Do not add an in-tracker referential rule here — it broke nine pre-existing
cases when tried.

## Interfaces

### Consumes from P02 — assumed to exist and work

```python
SCHEMA = "pipeline-auto/v1"
MARKER = "<!-- pipeline-auto/v1 -->"

class TrackerError(Exception): ...
class TrackerValidationError(TrackerError): ...

def parse_tracker(text: str) -> dict: ...
def render_tracker(tracker: dict) -> str: ...
def validate_run(run_dir: str) -> dict: ...
def initialize_run(run_dir: str, *, run_id: str, base_commit: str,
                   target_branch: str, worker_limit: int) -> dict: ...
def locked_tracker_update(run_dir: str, *, transition_id: str, mutate) -> dict: ...
def publish_immutable(path: str, content: str) -> str: ...  # returns the sha256 hex digest, NOT the path
def derive_next_action(tracker: dict) -> str: ...

_SECTIONS, _TASK_REVIEW_HEADER, _FIX_ROUND_HEADER, _COMMIT, _csv, _field
_validate_tracker_semantics(tracker) -> None     # the dispatcher P05 extends
_validate_tasks, _validate_phases, _validate_gates
_REVIEW_CLASSES = ("final-only", "required")
_CLASS_SOURCES = ("plan", "ratchet")
_TASK_STATES = ("[ ]", "[~]", "[?]", "[x]")
```

`## Tasks` carries a `Phase` column, settled in P02. Every P05 function that needs a task's phase reads `task["phase"]` and never infers it from a task-id prefix — the per-phase drift budget and the ratchet are otherwise underivable from the tracker.

Two P02 behaviours P05 depends on and must not re-implement:

- `locked_tracker_update` validates, locks, re-reads, revalidates, applies `mutate`, renders, **re-parses its own render**, then atomically replaces. A `mutate` producing a semantically invalid tracker raises before the replace, and the file is untouched. This is the mechanism every never-off rule in P05 rides on.
- A replayed `transition_id` returns current state **without calling `mutate` at all**. Every P05 transition id is therefore derived deterministically from its inputs.

### Consumes from P03 — assumed to exist and work

```python
RUNGS         # MappingProxyType, frozen schema constants
RUNG_ORDER    # tuple, HIGHEST rung first; all comparisons use index, never value
ADOPTABLE     # frozenset({"specified", "code-evidenced"})
def quorum_tracker_rows(run_dir: str) -> list[dict]: ...
def quorum_events(run_dir: str) -> list[dict]: ...
def finalize_quorum(run_dir: str, *, qid: str) -> dict: ...
```

`RUNG_ORDER` is highest-first, so "the lower of two rungs" is the one with the **larger** index. Every comparison in P05 uses `RUNG_ORDER.index(...)`; no P05 code ever reads a float out of `RUNGS`.

### Consumes from P04 — assumed to exist and work

```python
def reserve_task(run_dir: str, *, task_id: str, owner: str, attempt: int) -> dict: ...
def resume_task(run_dir: str, *, task_id: str, prior_attempt: int,
                new_owner: str, new_attempt: int, decision_ref: str) -> dict: ...
def scopes_overlap(a: str, b: str) -> bool: ...          # file:/tree: with ancestor rules
def publish_worker_result(run_dir: str, *, result: dict) -> str: ...
def import_worker_result(run_dir: str, *, result_path: str) -> dict: ...
def verify_source_range(repo: str, *, baseline: str, head: str, scopes: list) -> dict: ...
def reconcile_run(run_dir: str) -> dict: ...
```

### Produces — consumed by P06

Names marked **(master plan)** are verbatim from the master plan's "P05 produces" block and may not be renamed. Names marked **(P05)** are additions; `## Unresolved — reported, not invented` says why each was needed.

```python
ADVERSARIAL_TRIGGERS = ("concurrency", "authz", "crypto", "schema", "migration",
                        "delete", "regulated", "public-api", "large-surface")   # (master plan)
RATCHET_TRIGGERS = ("adversarial-finding", "repeated-suite-failure",
                    "debug-locality", "low-confidence-dependency",
                    "accumulated-surface")                                      # (master plan)

def adversarial_required(diff_paths: list, changed_lines: int) -> str | None: ...   # (master plan)
def record_task_review(run_dir: str, *, task_id: str, attempt: str,
                       verdict: dict) -> dict: ...                                  # (master plan)
def open_fix_round(run_dir: str, *, scope: str, findings: list) -> dict: ...         # (master plan)
def ratchet_phase(run_dir: str, *, phase: str, trigger: str,
                  evidence_ref: str) -> dict: ...                                   # (master plan)
def propagate_provisional(tracker: dict) -> dict: ...                               # (master plan)

LARGE_SURFACE_LINES = 300                                                       # (P05)
FIX_ROUND_CAP = 3                                                               # (P05)
INTENSITIES = ("mechanical", "full")                                            # (P05)
INTENSITY_ORDER = ("mechanical", "full")   # index ascending = strictly stronger (P05)
TASK_REVIEW_STATES = ("dispatched", "reported", "approved", "blocked")          # (P05)
FIX_ROUND_STATES = ("fixing", "complete", "reconciling")                        # (P05)
CLASS_INTENSITY = {"final-only": "mechanical", "required": "full"}              # (P05)

class DialError(TrackerError): ...                                              # (P05)

def task_intensity(tracker: dict, task_id: str) -> str: ...                     # (P05)
def close_fix_round(run_dir: str, *, scope: str, round_no: int, commits: str,
                    verification: str, re_review: str, remaining: str) -> dict: ...  # (P05)
def ratchet_triggers_fired(tracker: dict, *, phase: str, suite_failures: int = 0,
                           debug_root_cause_paths: tuple = (),
                           phase_scopes: tuple = (),
                           changed_lines: dict | None = None) -> tuple: ...     # (P05)
def provisional_constraints_block(tracker: dict, *, task_id: str,
                                  adopted_answers: dict) -> str: ...            # (P05)
def inherited_rung_cap(tracker: dict, *, qid: str) -> str | None: ...           # (P05)
```

**Type notes for P06's implementer.** `adversarial_required` returns a **trigger name** or `None`, never a boolean — the tracker records *which* trigger fired. `task_intensity` returns `"mechanical"` or `"full"`, never a review class. `ratchet_triggers_fired` returns a tuple of trigger names in `RATCHET_TRIGGERS` order, possibly empty. `inherited_rung_cap` returns a **rung name** or `None`; `None` means "no cap applies", not "cap to the bottom". `ratchet_phase(...)["status"]` is one of `ratcheted`, `already-required`.

---

## Data contracts P05 defines

### `## Task Review` — the round-scoped ledger

Fourteen columns, in exactly this order. This **replaces** P02's nine-column placeholder header (see `## Unresolved`).

| Column | Key | Grammar |
| --- | --- | --- |
| `Task` | `task` | a task id present in `## Tasks` |
| `Round` | `round` | integer ≥ 1, contiguous from 1 per task, unique per `(Task, Round)` |
| `Intensity` | `intensity` | `mechanical` \| `full` |
| `State` | `state` | `dispatched` \| `reported` \| `approved` \| `blocked` |
| `Reviewer` | `reviewer` | owner token; `-` **iff** `Intensity` is `mechanical` |
| `Package` | `package` | path to the `baseline..source-head` review package; **never `-`, at any intensity** |
| `Report` | `report` | reviewer report path; `-` iff `Intensity` is `mechanical` or `State` is `dispatched` |
| `Critical` | `critical` | non-negative integer |
| `Important` | `important` | non-negative integer |
| `Minor` | `minor` | non-negative integer |
| `Adversarial` | `adversarial` | a name in `ADVERSARIAL_TRIGGERS`, or `-` when no trigger fired |
| `Adversarial Verdict` | `adversarial_verdict` | `safe` \| `findings` \| `-` |
| `Open` | `open` | non-negative integer, `≤ Critical + Important + Minor` |
| `Evidence` | `evidence` | path to the independent verification re-run; `-` iff `State` is `dispatched` |

`Package` is never `-` because the range proof and the trigger check are both on the never-off list, and both read the package. A `mechanical` round has no reviewer and no report — but it still has a package, an evidence file, and a trigger evaluation.

### `## Fix Rounds` — unchanged columns, new semantics

P02's nine columns stand: `Scope`, `Round`, `State`, `Fixer`, `Findings`, `Commits`, `Verification`, `Re-review`, `Remaining`.

| Column | Grammar |
| --- | --- |
| `Scope` | a task id in `## Tasks`, a phase id in `## Phases`, or a gate id in `## Gates` |
| `Round` | integer 1..`FIX_ROUND_CAP`, contiguous from 1 per scope |
| `State` | `fixing` \| `complete` \| `reconciling` |
| `Fixer` | exactly one owner token — never a list |
| `Findings` | comma-separated finding ids, never `-` |
| `Remaining` | `none`, or comma-separated finding ids still open |

`Fixer` is a single token because the spec requires one fixer per round carrying **all** findings: "One fixer with the complete list produces coherent fixes; per-finding fixers each rebuild context and produce piecemeal, sometimes conflicting edits."

`reconciling` is the state the spec's decision-dispute path parks in: "The task moves to `[?]` with a reconciliation question reference, its owner slot releases, and independent work continues. The fix-round counter **does not increment**." A `reconciling` round therefore does not count toward `FIX_ROUND_CAP`.

### The five semantic-validation rules added to P02's validator

Stated here once, verbatim, because they are what this phase is *for*. Each is an **addition** to `_validate_tracker_semantics`, wired in Task 9; none replaces or weakens an existing P02 rule.

| # | Rule | Task |
| --- | --- | --- |
| **V1** | A task may not reach `[x]` while any of its `## Task Review` rows has `Open != 0`, or while any of its rows is in state `dispatched` or `blocked`. | 3 |
| **V2** | A task any of whose `## Task Review` rows carries `Intensity: full` may not reach `[x]` without at least one round in state `approved`. | 4 |
| **V3** | A task any of whose `## Task Review` rows carries `Adversarial != -` may not reach `[x]` unless that row's `Adversarial Verdict` is `safe` — **at every intensity**. | 2 |
| **V4** | Intensity is non-decreasing across a task's rounds. A `full → mechanical` transition is invalid. | 4 |
| **V5** | A task that is not `[x]`, in a phase whose `Review Class` is `required`, may not have its latest round at `mechanical`. (Completed tasks are exempt: a ratchet does not retroactively review complete tasks.) | 6 |

Two supporting rules fall out of the same pass and are tested with them: a task at `[x]` must have **at least one** `## Task Review` row (the check, the package and the evidence are never-off, so their record must exist), and a task may not be `[x]` while a `## Fix Rounds` row scoped to it is in state `fixing` or `reconciling`.

---

## Verification suite for this phase

Ordered command tuple. All three must pass before P05 is complete. Run every command from the repository root.

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The second and third commands must print **nothing**. Any output from the second means `skills/pipeline/` was modified and the phase fails.

**`pytest` is not installed on this machine** — `python3 -c "import pytest"` raises `ModuleNotFoundError` under Python 3.11.2. Every test in this phase is a `unittest.TestCase`, so it runs under `unittest discover` today and under pytest if it is ever installed. No `Run:` line in this plan names pytest.

**Do not add `-t .` to the discover command.** The skill directory is `pipeline-auto`, which contains a hyphen, so a top-level-relative discovery would try to import `plugins.superb.skills.pipeline-auto.tests` and fail with `ImportError: Start directory is not importable`. Verified on this machine. Omitting `-t` makes discovery put the tests directory itself on `sys.path` and import the module as `test_pipeline_auto_state`, which is what P02's and P03's bootstrap already assume.

Sub-suites are selected with repeated `-k` flags, which `unittest` ORs together — `-k A -k B`, never pytest's `-k "A or B"` expression syntax.

### Test module bootstrap and shared helpers

P02 wrote the bootstrap and P03 wrote `new_run`; both are already at the top of `tests/test_pipeline_auto_state.py`. P05 adds nothing to them except the two helpers below, which go directly under P03's helpers, once, in Task 1.

```python
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def valid_text():
    return (FIXTURES / "valid-progress.md").read_text(encoding="utf-8")


def final_only_text():
    return (FIXTURES / "final-only-progress.md").read_text(encoding="utf-8")


def seed(run_dir, text):
    """Drop a fixture tracker into an initialized run directory, bypassing the
    stage machinery. The fixture is already valid, so this is a legal state."""
    (Path(run_dir) / "progress.md").write_text(text, encoding="utf-8")
    return pipeline_auto_state.parse_tracker(text)
```

`valid_text()` may already exist from P02; if it does, reuse it and add only `FIXTURES`, `final_only_text` and `seed`.

---

## Tasks

### Task 1: Widen `## Task Review` to the round-scoped fourteen columns

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py` (the `_TASK_REVIEW_HEADER` constant; append a `# --- dial and gate (P05) ---` section below P04's code)
- Modify: `plugins/superb/skills/pipeline-auto/tests/fixtures/valid-progress.md`
- Modify: `plugins/superb/skills/pipeline-auto/templates/progress.md`
- Create: `plugins/superb/skills/pipeline-auto/tests/fixtures/final-only-progress.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `parse_tracker`, `render_tracker`, `_TASK_REVIEW_HEADER`, `_validate_tracker_semantics`, `_field`, `TrackerValidationError`.
- Produces: the widened `_TASK_REVIEW_HEADER`, `INTENSITIES`, `INTENSITY_ORDER`, `TASK_REVIEW_STATES`, `CLASS_INTENSITY`, `class DialError(TrackerError)`, and the module-private `_validate_task_review` covering **identity and cell grammar only** — rounds contiguous and unique, `Task` resolvable, enums legal, counts non-negative, `Open <= Critical + Important + Minor`, and the `-` correspondences. Completion rules V1–V5 are added by Tasks 2–6.

**Named fault this task catches:** modelling review as one row per task — the shape that makes a second round unrepresentable and forces the comma-packed history cell that destroyed the old pipeline's `Checkpoints` column. The fixture is external truth: it carries two rounds for one task whether or not the module's parser can hold them.

- [ ] **Step 1: Migrate the valid fixture**

In `plugins/superb/skills/pipeline-auto/tests/fixtures/valid-progress.md`, replace the whole `## Task Review` section with exactly this. Change nothing else in the file.

```markdown
## Task Review
| Task | Round | Intensity | State | Reviewer | Package | Report | Critical | Important | Minor | Adversarial | Adversarial Verdict | Open | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01-T01 | 1 | full | reported | reviewer-1 | scratch/p01-t01-r1-package.md | scratch/p01-t01-r1-review.md | 0 | 0 | 1 | - | - | 0 | scratch/p01-t01-r1-rerun.txt |
| P01-T01 | 2 | full | approved | reviewer-1 | scratch/p01-t01-r2-package.md | scratch/p01-t01-r2-review.md | 0 | 0 | 0 | large-surface | safe | 0 | scratch/p01-t01-r2-rerun.txt |
| P01-T02 | 1 | full | approved | reviewer-3 | scratch/p01-t02-r1-package.md | scratch/p01-t02-r1-review.md | 0 | 0 | 0 | - | - | 0 | scratch/p01-t02-r1-rerun.txt |
| P02-T01 | 1 | full | blocked | reviewer-2 | scratch/p02-t01-r1-package.md | scratch/p02-t01-r1-review.md | 1 | 1 | 0 | - | - | 2 | scratch/p02-t01-r1-rerun.txt |
```

P01-T01 round 1 found one Minor and shows `Open: 0` — fix round 1 in `## Fix Rounds` closed it and round 2's re-review superseded the count. That is the live-`Open` contract from the design notes, demonstrated in the fixture rather than asserted in prose.

- [ ] **Step 2: Write the `final-only` fixture**

Create `plugins/superb/skills/pipeline-auto/tests/fixtures/final-only-progress.md` with exactly this content. It is the substrate for Task 2's sharpest test and every ratchet test.

```markdown
<!-- pipeline-auto/v1 -->
# Pipeline Auto — Progress Tracker

## Run
| Field | Value |
| --- | --- |
| run_id | 2026-09-14-final-only |
| schema | pipeline-auto/v1 |
| base_commit | c8bddd610119f52b54bf077d284c7f5d8362ae77 |
| target_branch | feat/pipeline-auto |
| worker_limit | 4 |
| agent_dispatch_count | 6 |
| spec | docs/superpowers/specs/2026-09-14-pipeline-auto-design.md |
| master_plan | docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md |
| phase_plans | docs/superpowers/plans/pipeline-auto/phase-07-skill-prose.md |
| decisions | docs/superpowers/runs/2026-09-14-final-only/decisions.md |
| findings | docs/superpowers/runs/2026-09-14-final-only/findings.md |
| completeness_proposals | docs/superpowers/runs/2026-09-14-final-only/completeness-proposals.md |
| revision | 4 |
| last_transition | task-review-P07-T01-attempt-001 |

## Stage
| Stage | Stage State | Next Action |
| --- | --- | --- |
| 01 | complete | - |
| 02 | complete | - |
| 03 | complete | - |
| 04 | complete | - |
| 05 | complete | - |
| 06 | complete | - |
| 07 | complete | - |
| 08 | complete | - |
| 09 | active | run-task-gate-P07-T02 |
| 10 | pending | - |
| 11 | pending | - |
| 12 | pending | - |

## Intent
| ID | Kind | State | Owner | Result | Conflicts |
| --- | --- | --- | --- | --- | --- |
| reader-1 | reader | published | intent-reader-1 | scratch/intent-reader-1.md | - |
| reader-2 | reader | published | intent-reader-2 | scratch/intent-reader-2.md | - |
| reader-3 | reader | published | intent-reader-3 | scratch/intent-reader-3.md | - |
| brief | brief | frozen | reconciled | scratch/intent-brief.md | - |

## Questions
| ID | Origin | Slot | State | Decision |
| --- | --- | --- | --- | --- |
| axis-1 | synthesis | 1 | answered | H-1 |

## Quorum
| QID | Axis | Phase | State | Owners | Payload Digest | Context Digest | Responses | Depth | Rung | Outcome | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Escalations
| ID | QID | Blast | State | Batch | Resolution |
| --- | --- | --- | --- | --- | --- |

## Tasks
| ID | Phase | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question | Provisional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P07-T01 | P07 | source | [x] | impl-1 | attempt-001 | scratch/p07-t01-result.md | red,green | refs/heads/feat/pipeline-auto | 3333333333333333333333333333333333333333 | - | 4444444444444444444444444444444444444444 | scratch/p07-t01-tests.txt | - | no |
| P07-T02 | P07 | source | [ ] | - | - | - | - | - | - | - | - | - | - | no |

## Task Review
| Task | Round | Intensity | State | Reviewer | Package | Report | Critical | Important | Minor | Adversarial | Adversarial Verdict | Open | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P07-T01 | 1 | mechanical | approved | - | scratch/p07-t01-r1-package.md | - | 0 | 0 | 0 | - | - | 0 | scratch/p07-t01-r1-verify.txt |

## Fix Rounds
| Scope | Round | State | Fixer | Findings | Commits | Verification | Re-review | Remaining |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Phases
| ID | State | Verification | Review Class | Class Source | Ratchet | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| P07 | [~] | - | final-only | plan | - | gate-p07 |

## Gates
| ID | Type | Phase | State | Base | Head | Assignments | Reports | Verification | Findings |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gate-p07 | phase | P07 | pending | - | - | - | - | - | findings.md |
| gate-master | master | - | pending | - | - | - | - | - | findings.md |
```

P07-T01 is the honest `final-only` completion: mechanical round, no reviewer, no report, but a package, an evidence file, and `Adversarial: -` because no trigger fired on its diff. Task 2 is what happens when a trigger *does* fire.

- [ ] **Step 3: Update the template**

In `plugins/superb/skills/pipeline-auto/templates/progress.md`, replace the `## Task Review` header and separator rows with the fourteen-column form so `initialize_run` renders the new schema:

```markdown
## Task Review
| Task | Round | Intensity | State | Reviewer | Package | Report | Critical | Important | Minor | Adversarial | Adversarial Verdict | Open | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
```

- [ ] **Step 4: Write the failing tests**

Append to `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`, below P03's helpers (adding `FIXTURES`, `valid_text`, `final_only_text` and `seed` from the bootstrap section above if they are not already present):

```python
class TaskReviewShapeTests(unittest.TestCase):
    def test_the_header_is_the_fourteen_round_scoped_columns(self):
        self.assertEqual(
            pipeline_auto_state._TASK_REVIEW_HEADER,
            ("Task", "Round", "Intensity", "State", "Reviewer", "Package",
             "Report", "Critical", "Important", "Minor", "Adversarial",
             "Adversarial Verdict", "Open", "Evidence"),
        )

    def test_one_task_carries_many_rounds(self):
        """A task has N review rounds, not one. Columns on ## Tasks would force
        either multiple rows per task -- breaking the one-row-per-task invariant
        the P04 task-replacement helpers assume -- or a comma-packed history
        cell, which is how the old pipeline's Checkpoints column became
        unparseable."""
        tracker = pipeline_auto_state.parse_tracker(valid_text())
        rounds = [row for row in tracker["task_review"] if row["task"] == "P01-T01"]
        self.assertEqual([row["round"] for row in rounds], ["1", "2"])

    def test_parse_render_round_trips_the_widened_section(self):
        text = valid_text()
        self.assertEqual(
            pipeline_auto_state.render_tracker(pipeline_auto_state.parse_tracker(text)),
            text,
        )

    def test_the_final_only_fixture_is_valid(self):
        tracker = pipeline_auto_state.parse_tracker(final_only_text())
        self.assertEqual(tracker["phases"][0]["review_class"], "final-only")

    def test_rounds_are_contiguous_from_one(self):
        text = valid_text().replace("| P01-T01 | 2 | full |", "| P01-T01 | 3 | full |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_round_number_is_unique_per_task(self):
        text = valid_text().replace("| P01-T01 | 2 | full |", "| P01-T01 | 1 | full |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_review_row_must_name_a_known_task(self):
        text = valid_text().replace("| P01-T02 | 1 | full |", "| P99-T99 | 1 | full |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_intensity_is_mechanical_or_full(self):
        text = valid_text().replace("| P01-T02 | 1 | full |", "| P01-T02 | 1 | medium |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_package_is_never_absent_at_any_intensity(self):
        """The range proof and the trigger check are both on the never-off list
        and both read the package."""
        text = final_only_text().replace("scratch/p07-t01-r1-package.md", "-")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_mechanical_round_carries_no_reviewer(self):
        text = final_only_text().replace(
            "| P07-T01 | 1 | mechanical | approved | - |",
            "| P07-T01 | 1 | mechanical | approved | reviewer-9 |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_full_round_must_name_its_reviewer(self):
        text = valid_text().replace(
            "| P01-T02 | 1 | full | approved | reviewer-3 |",
            "| P01-T02 | 1 | full | approved | - |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_open_cannot_exceed_the_findings_it_counts(self):
        text = valid_text().replace(
            "| 1 | 1 | 0 | - | - | 2 | scratch/p02-t01-r1-rerun.txt |",
            "| 1 | 1 | 0 | - | - | 5 | scratch/p02-t01-r1-rerun.txt |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_an_adversarial_verdict_requires_a_trigger(self):
        text = valid_text().replace(
            "| 0 | 0 | 0 | - | - | 0 | scratch/p01-t02-r1-rerun.txt |",
            "| 0 | 0 | 0 | - | safe | 0 | scratch/p01-t02-r1-rerun.txt |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_an_unknown_adversarial_trigger_is_rejected(self):
        text = valid_text().replace(
            "| large-surface | safe |", "| vibes | safe |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k TaskReviewShape`
Expected: FAIL — `AssertionError: ('Task', 'Attempt', 'Reviewer', ...) != ('Task', 'Round', ...)` on the header test, and `TrackerValidationError` on every fixture parse because the rendered column count no longer matches.

- [ ] **Step 6: Widen the header and write the identity validator**

In `pipeline_auto_state.py`, replace the `_TASK_REVIEW_HEADER` constant in place:

```python
_TASK_REVIEW_HEADER = (
    "Task", "Round", "Intensity", "State", "Reviewer", "Package", "Report",
    "Critical", "Important", "Minor", "Adversarial", "Adversarial Verdict",
    "Open", "Evidence",
)
```

Then append a new section at the end of the module:

```python
# --------------------------------------------------------------------------
# Dial and gate (P05)
# --------------------------------------------------------------------------
# The dial controls WHETHER A REVIEWER RUNS, never WHAT BAR THAT REVIEWER
# APPLIES. Every rule below is a semantic validation rule rather than a
# controller branch, because the controller branch is the bug: the natural
# implementation of a dial is `if intensity == "full": run_review_gate()`, and
# in SDD's own flow the adversarial pass lives inside that gate. One plausible
# line switches the never-off list off. A validator cannot be talked round.

INTENSITIES = ("mechanical", "full")
INTENSITY_ORDER = ("mechanical", "full")      # index ascending = strictly stronger
TASK_REVIEW_STATES = ("dispatched", "reported", "approved", "blocked")
CLASS_INTENSITY = {"final-only": "mechanical", "required": "full"}

ADVERSARIAL_TRIGGERS = ("concurrency", "authz", "crypto", "schema", "migration",
                        "delete", "regulated", "public-api", "large-surface")

_ADVERSARIAL_VERDICTS = ("safe", "findings")
_NON_NEGATIVE = re.compile(r"(?:0|[1-9][0-9]*)")


class DialError(TrackerError):
    """A dial or gate transition that would violate the never-off list."""


def _count(value: str, what: str) -> int:
    if not _NON_NEGATIVE.fullmatch(value):
        raise TrackerValidationError(f"{what} is a non-negative integer")
    return int(value)


def _rounds_by_task(tracker: dict) -> dict:
    """Task id -> its review rows, in recorded order."""
    grouped: dict = {}
    for row in tracker["task_review"]:
        grouped.setdefault(row["task"], []).append(row)
    return grouped


def _validate_task_review(tracker: dict) -> None:
    tasks = {row["id"]: row for row in tracker["tasks"]}
    for task_id, rows in _rounds_by_task(tracker).items():
        if task_id not in tasks:
            raise TrackerValidationError("a review round names an unknown task")
        numbers = [_count(row["round"], "Round") for row in rows]
        if numbers != list(range(1, len(numbers) + 1)):
            raise TrackerValidationError(
                "a task's review rounds are contiguous and unique, numbered from 1"
            )
    for row in tracker["task_review"]:
        if row["intensity"] not in INTENSITIES:
            raise TrackerValidationError("intensity is mechanical or full")
        if row["state"] not in TASK_REVIEW_STATES:
            raise TrackerValidationError("unknown review round state")
        if row["package"] == "-":
            raise TrackerValidationError(
                "every review round names its review package at every intensity: "
                "the range proof and the trigger check are never switched off"
            )
        mechanical = row["intensity"] == "mechanical"
        if mechanical != (row["reviewer"] == "-"):
            raise TrackerValidationError(
                "a mechanical round has no reviewer and a full round names one"
            )
        report_absent = mechanical or row["state"] == "dispatched"
        if report_absent != (row["report"] == "-"):
            raise TrackerValidationError(
                "a report is present exactly for a reported full round"
            )
        if (row["state"] == "dispatched") != (row["evidence"] == "-"):
            raise TrackerValidationError(
                "a round carries verification evidence unless it is still dispatched"
            )
        found = sum(_count(row[key], key.title())
                    for key in ("critical", "important", "minor"))
        if _count(row["open"], "Open") > found:
            raise TrackerValidationError("Open cannot exceed the findings it counts")
        if row["adversarial"] != "-" and row["adversarial"] not in ADVERSARIAL_TRIGGERS:
            raise TrackerValidationError("unknown adversarial trigger")
        if row["adversarial"] == "-" and row["adversarial_verdict"] != "-":
            raise TrackerValidationError(
                "an adversarial verdict requires a fired trigger"
            )
        if row["adversarial_verdict"] not in ("-",) + _ADVERSARIAL_VERDICTS:
            raise TrackerValidationError("an adversarial verdict is safe or findings")
```

Wire it in by adding one line to `_validate_tracker_semantics`, after `_validate_tasks`:

```python
    _validate_task_review(tracker)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, including every P02/P03/P04 test — the fixture migration must not break them.

- [ ] **Step 8: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): make task review a round-scoped ledger"
```

---

### Task 2: The adversarial trigger check the dial can never switch off

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `ADVERSARIAL_TRIGGERS`, `_validate_task_review`, `_rounds_by_task`, `locked_tracker_update`, `parse_tracker`, `TrackerValidationError`.
- Produces: `LARGE_SURFACE_LINES = 300`, `_ADVERSARIAL_PATH_PATTERNS`, `adversarial_required(diff_paths: list, changed_lines: int) -> str | None`, and validation rule **V3** inside `_validate_task_review`.

**Named fault this task catches — the sharpest in the phase.** A `final-only` task whose diff fires a high-risk trigger is marked `[x]` with `Adversarial Verdict: -`. The natural implementation of a dial is one branch — `if phase.intensity == "full": run_review_gate()` — and in SDD's own flow the adversarial pass lives *inside* that gate, firing after the task reviewer approves. So the obvious, almost inevitable implementation puts the adversarial pass in the `full` branch and switches it off with everything else: one line of entirely plausible code, passing every other test in the suite, violating the never-off list.

**Second named fault.** The line-count trigger implemented as "300+ lines **and** a risky path" instead of as an independent trigger. The spec says verbatim: *a 10-line auth change is high-risk.*

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class AdversarialTriggerTests(unittest.TestCase):
    def test_the_trigger_names_match_the_pattern_table_plus_large_surface(self):
        named = tuple(name for name, _ in pipeline_auto_state._ADVERSARIAL_PATH_PATTERNS)
        self.assertEqual(named + ("large-surface",),
                         pipeline_auto_state.ADVERSARIAL_TRIGGERS)

    def test_a_ten_line_auth_change_is_high_risk(self):
        """The spec, verbatim: 'A 10-line auth change is high-risk.' The
        line-count trigger is its own trigger, not a minimum size the others
        must also meet."""
        self.assertEqual(
            pipeline_auto_state.adversarial_required(["src/auth/session.py"], 10),
            "authz",
        )

    def test_a_large_diff_touching_nothing_risky_still_fires(self):
        self.assertEqual(
            pipeline_auto_state.adversarial_required(["docs/notes.md"], 301),
            "large-surface",
        )

    def test_three_hundred_lines_exactly_does_not_fire(self):
        self.assertIsNone(
            pipeline_auto_state.adversarial_required(["docs/notes.md"], 300))

    def test_each_path_trigger_fires_independently_at_one_line(self):
        cases = {
            "concurrency": "src/worker/locks.py",
            "authz": "api/permissions.rb",
            "crypto": "lib/crypto/hmac.go",
            "schema": "db/schema.sql",
            "migration": "db/migrations/0007_add_col.py",
            "delete": "app/services/purge.py",
            "regulated": "billing/invoice.py",
            "public-api": "src/api/routes.ts",
        }
        for expected, path in cases.items():
            with self.subTest(trigger=expected):
                self.assertEqual(
                    pipeline_auto_state.adversarial_required([path], 1), expected)

    def test_a_substring_alone_does_not_fire(self):
        """'rapid' contains 'api'; 'keystone' contains 'key'. Token boundaries,
        not substrings -- a trigger that fires on everything is a trigger
        nobody keeps."""
        self.assertIsNone(
            pipeline_auto_state.adversarial_required(
                ["src/rapid.py", "docs/keystone.md"], 4))

    def test_no_paths_and_no_size_fires_nothing(self):
        self.assertIsNone(pipeline_auto_state.adversarial_required([], 0))


class NeverOffAtMechanicalIntensityTests(unittest.TestCase):
    """THE sharpest test in P05. A final-only task whose diff fires a high-risk
    trigger cannot reach [x] with an unresolved adversarial verdict. If the
    adversarial pass was implemented inside the `full` branch of the dial, the
    tracker can record this state and these tests fail."""

    def _triggered_final_only(self, trigger, verdict, state="[x]"):
        text = final_only_text().replace(
            "| P07-T01 | 1 | mechanical | approved | - | "
            "scratch/p07-t01-r1-package.md | - | 0 | 0 | 0 | - | - | 0 | "
            "scratch/p07-t01-r1-verify.txt |",
            "| P07-T01 | 1 | mechanical | approved | - | "
            "scratch/p07-t01-r1-package.md | - | 0 | 0 | 0 | "
            f"{trigger} | {verdict} | 0 | scratch/p07-t01-r1-verify.txt |")
        if state != "[x]":
            text = text.replace("| P07-T01 | P07 | source | [x] |",
                                f"| P07-T01 | P07 | source | {state} |")
        return text

    def test_large_surface_at_mechanical_intensity_cannot_complete_unresolved(self):
        """> 300 changed source lines in a final-only phase. The trigger fired;
        the verdict is '-'; the task is [x]. This is the exact state the
        one-branch dial produces."""
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(
                self._triggered_final_only("large-surface", "-"))

    def test_an_auth_path_at_mechanical_intensity_cannot_complete_unresolved(self):
        """Ten lines, one auth path, a final-only phase. Separately from the
        line count, because the triggers are independent."""
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(
                self._triggered_final_only("authz", "-"))

    def test_a_findings_verdict_at_mechanical_intensity_cannot_complete(self):
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(
                self._triggered_final_only("authz", "findings"))

    def test_a_safe_verdict_at_mechanical_intensity_completes(self):
        tracker = pipeline_auto_state.parse_tracker(
            self._triggered_final_only("authz", "safe"))
        row = tracker["task_review"][0]
        self.assertEqual((row["intensity"], row["adversarial_verdict"]),
                         ("mechanical", "safe"))

    def test_an_unresolved_trigger_is_legal_before_completion(self):
        """The rule gates completion, not the record. A task still in flight may
        carry a fired trigger whose adversarial pass has not yet returned."""
        pipeline_auto_state.parse_tracker(
            self._triggered_final_only("authz", "-", state="[~]"))

    def test_a_completed_task_must_have_a_review_round_at_all(self):
        """Deleting the round is the other way to make the check disappear."""
        text = final_only_text().replace(
            "| P07-T01 | 1 | mechanical | approved | - | "
            "scratch/p07-t01-r1-package.md | - | 0 | 0 | 0 | - | - | 0 | "
            "scratch/p07-t01-r1-verify.txt |\n", "")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_the_transition_that_would_record_it_raises_and_changes_nothing(self):
        """End to end: locked_tracker_update re-parses its own render before the
        atomic replace, so the mutate that marks the task complete raises and
        progress.md is byte-identical afterwards."""
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, self._triggered_final_only("authz", "-", state="[~]"))
            before = (Path(run_dir) / "progress.md").read_bytes()

            def mutate(tracker):
                task = next(row for row in tracker["tasks"] if row["id"] == "P07-T01")
                task["state"] = "[x]"
                task["result"] = "scratch/p07-t01-result.md"
                task["verification"] = "scratch/p07-t01-tests.txt"
                task["source_ref"] = "refs/heads/feat/pipeline-auto"
                task["commits"] = "3" * 40
                task["integration"] = "4" * 40
                return tracker

            with self.assertRaises(pipeline_auto_state.TrackerValidationError):
                pipeline_auto_state.locked_tracker_update(
                    str(run_dir), transition_id="complete-P07-T01", mutate=mutate)
            self.assertEqual((Path(run_dir) / "progress.md").read_bytes(), before)
```

Add `import contextlib` to the test module's imports if P03's helpers did not already add it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k AdversarialTrigger -k NeverOffAtMechanical`
Expected: FAIL — `AttributeError: module has no attribute '_ADVERSARIAL_PATH_PATTERNS'`, and `TrackerValidationError not raised` on every completion test.

- [ ] **Step 3: Write the trigger evaluator**

Append to the `# --- dial and gate (P05) ---` section:

```python
LARGE_SURFACE_LINES = 300

# Matched against the lowercased path with token boundaries, never as bare
# substrings: 'rapid' contains 'api' and 'keystone' contains 'key'. A trigger
# that fires on everything is a trigger somebody deletes.
_TOKEN_EDGE = r"(?:^|[/_.\-])"
_TOKEN_END = r"(?:[/_.\-]|$)"
_ADVERSARIAL_PATH_PATTERNS = tuple(
    (name, re.compile(_TOKEN_EDGE + r"(?:" + alternatives + r")" + _TOKEN_END))
    for name, alternatives in (
        ("concurrency", r"lock|locks|locking|mutex|semaphore|thread|threads|"
                        r"threading|async|asyncio|concurrency|concurrent|signal|"
                        r"signals|scheduler|worker|workers|queue|queues"),
        ("authz",       r"auth|authn|authz|authentication|authorization|login|"
                        r"logout|session|sessions|permission|permissions|role|"
                        r"roles|acl|token|tokens|credential|credentials"),
        ("crypto",      r"crypto|cipher|ciphers|encrypt|encryption|decrypt|"
                        r"hmac|signing|signature|signatures|keystore|keyring|"
                        r"secret|secrets"),
        ("schema",      r"schema|schemas|ddl"),
        ("migration",   r"migration|migrations|migrate|alembic|liquibase|flyway"),
        ("delete",      r"delete|deletes|deletion|destroy|purge|prune|drop|"
                        r"dedup|dedupe|deduplicate"),
        ("regulated",   r"payment|payments|billing|invoice|invoices|ledger|phi|"
                        r"pii|patient|patients|ssn|hipaa|gdpr"),
        ("public-api",  r"api|apis|openapi|swagger|proto|protobuf|grpc|wire|"
                        r"endpoint|endpoints|route|routes|router|serializer|"
                        r"serializers"),
    )
)


def adversarial_required(diff_paths: list, changed_lines: int) -> str | None:
    """The fired trigger's name, or None. Never a boolean: the tracker records
    WHICH trigger fired.

    Triggers are INDEPENDENT -- any single one fires. The line count is its own
    trigger, not a minimum size the others must also meet. The spec, verbatim:
    'A 10-line auth change is high-risk.' Collapsing this into
    '300 lines AND a risky path' is the obvious and wrong reading.

    This function is called at EVERY intensity. The dial controls whether a
    reviewer runs, never whether the check happens.
    """
    lowered = [str(path).lower() for path in diff_paths]
    for name, pattern in _ADVERSARIAL_PATH_PATTERNS:
        if any(pattern.search(path) for path in lowered):
            return name
    if int(changed_lines) > LARGE_SURFACE_LINES:
        return "large-surface"
    return None
```

- [ ] **Step 4: Add validation rule V3**

Append to `_validate_task_review`, after the per-row loop:

```python
    for task_id, rows in _rounds_by_task(tracker).items():
        if tasks[task_id]["state"] != "[x]":
            continue
        # V3 -- AT EVERY INTENSITY. The dial may never switch off the
        # adversarial trigger check, so a fired trigger must be resolved
        # `safe` before completion whether the phase is required or final-only.
        for row in rows:
            if row["adversarial"] != "-" and row["adversarial_verdict"] != "safe":
                raise TrackerValidationError(
                    f"task {task_id} fired the {row['adversarial']} adversarial "
                    "trigger and cannot complete without a 'safe' verdict; the "
                    "trigger check is never switched off by the dial"
                )
```

And, in the same completion loop, the supporting rule that a completed task has a record at all. Add it immediately before the `for row in rows` loop, and add the matching guard for tasks with **no** rows by iterating the task table instead:

```python
    reviewed = _rounds_by_task(tracker)
    for task in tracker["tasks"]:
        if task["state"] == "[x]" and not reviewed.get(task["id"]):
            raise TrackerValidationError(
                f"task {task['id']} is complete with no review round; the review "
                "package, the verification evidence and the adversarial trigger "
                "check are recorded at every intensity"
            )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, whole file.

- [ ] **Step 6: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): fire adversarial triggers independently of the dial"
```

---

### Task 3: `record_task_review` and zero open findings at every severity

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `locked_tracker_update`, `parse_tracker`, `_rounds_by_task`, `_TASK_REVIEW_HEADER`, `_field`, `TASK_REVIEW_STATES`, `DialError`.
- Produces: `record_task_review(run_dir: str, *, task_id: str, attempt: str, verdict: dict) -> dict`, and validation rule **V1**.

**Named fault this task catches:** a review round with `Minor: 1, Open: 1` marks the task complete. Severity-as-gate is the likeliest regression in this phase, because essentially every other pipeline treats Minor as non-blocking — and the reviewer template's own heading, "Minor (Must Still Fix Before Task Completion)", exists precisely because that instinct is universal. Severity communicates urgency and risk; it is never a fix/no-fix gate.

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class ZeroOpenFindingsTests(unittest.TestCase):
    def test_a_single_open_minor_blocks_completion(self):
        """Severity communicates urgency and risk; it is never a fix/no-fix
        gate. A task is complete only when its rounds report no open findings
        at ANY severity."""
        text = valid_text().replace(
            "| P01-T02 | 1 | full | approved | reviewer-3 | "
            "scratch/p01-t02-r1-package.md | scratch/p01-t02-r1-review.md | "
            "0 | 0 | 0 | - | - | 0 |",
            "| P01-T02 | 1 | full | approved | reviewer-3 | "
            "scratch/p01-t02-r1-package.md | scratch/p01-t02-r1-review.md | "
            "0 | 0 | 1 | - | - | 1 |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_closed_minor_in_history_does_not_block(self):
        """P01-T01 round 1 found a Minor and shows Open: 0 -- the fix round
        closed it and round 2's re-review superseded the count. History is
        preserved; the gate reads Open."""
        tracker = pipeline_auto_state.parse_tracker(valid_text())
        first = tracker["task_review"][0]
        self.assertEqual((first["minor"], first["open"]), ("1", "0"))

    def test_a_dispatched_round_blocks_completion(self):
        text = valid_text().replace(
            "| P01-T02 | 1 | full | approved | reviewer-3 | "
            "scratch/p01-t02-r1-package.md | scratch/p01-t02-r1-review.md | "
            "0 | 0 | 0 | - | - | 0 | scratch/p01-t02-r1-rerun.txt |",
            "| P01-T02 | 1 | full | dispatched | reviewer-3 | "
            "scratch/p01-t02-r1-package.md | - | 0 | 0 | 0 | - | - | 0 | - |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_an_approved_round_cannot_carry_open_findings(self):
        text = valid_text().replace(
            "| 0 | 0 | 1 | - | - | 0 | scratch/p01-t01-r1-rerun.txt |",
            "| 0 | 0 | 1 | - | - | 1 | scratch/p01-t01-r1-rerun.txt |")
        text = text.replace("| P01-T01 | 1 | full | reported |",
                            "| P01-T01 | 1 | full | approved |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)


class RecordTaskReviewTests(unittest.TestCase):
    def _verdict(self, **overrides):
        base = {"state": "reported", "intensity": "mechanical", "reviewer": "-",
                "package": "scratch/p07-t02-r1-package.md", "report": "-",
                "critical": 0, "important": 0, "minor": 0, "open": 0,
                "adversarial": "-", "adversarial_verdict": "-",
                "evidence": "scratch/p07-t02-r1-verify.txt"}
        base.update(overrides)
        return base

    def _started(self):
        text = final_only_text().replace(
            "| P07-T02 | P07 | source | [ ] | - | - | - | - |",
            "| P07-T02 | P07 | source | [~] | impl-2 | attempt-001 | - | red |")
        return text

    def test_the_first_round_is_numbered_one(self):
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, self._started())
            result = pipeline_auto_state.record_task_review(
                str(run_dir), task_id="P07-T02", attempt="attempt-001",
                verdict=self._verdict())
            self.assertEqual(result["round"], 1)

    def test_a_second_round_increments_and_zeroes_the_first_open_count(self):
        """A re-review re-examines everything the previous round raised, so its
        own Open count is authoritative and the older one is superseded."""
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, self._started())
            pipeline_auto_state.record_task_review(
                str(run_dir), task_id="P07-T02", attempt="attempt-001",
                verdict=self._verdict(state="blocked", minor=2, open=2))
            pipeline_auto_state.record_task_review(
                str(run_dir), task_id="P07-T02", attempt="attempt-001",
                verdict=self._verdict(state="approved"))
            tracker = pipeline_auto_state.validate_run(str(run_dir))
            rows = [r for r in tracker["task_review"] if r["task"] == "P07-T02"]
            self.assertEqual([(r["round"], r["minor"], r["open"]) for r in rows],
                             [("1", "2", "0"), ("2", "0", "0")])

    def test_a_stale_attempt_is_refused(self):
        """A reviewer report bound to a superseded attempt is not evidence about
        the attempt that is running."""
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, self._started())
            with self.assertRaises(pipeline_auto_state.DialError):
                pipeline_auto_state.record_task_review(
                    str(run_dir), task_id="P07-T02", attempt="attempt-000",
                    verdict=self._verdict())

    def test_recording_the_same_verdict_twice_is_inert(self):
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, self._started())
            verdict = self._verdict()
            pipeline_auto_state.record_task_review(
                str(run_dir), task_id="P07-T02", attempt="attempt-001",
                verdict=verdict)
            pipeline_auto_state.record_task_review(
                str(run_dir), task_id="P07-T02", attempt="attempt-001",
                verdict=verdict)
            tracker = pipeline_auto_state.validate_run(str(run_dir))
            rows = [r for r in tracker["task_review"] if r["task"] == "P07-T02"]
            self.assertEqual(len(rows), 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ZeroOpenFindings -k RecordTaskReview`
Expected: FAIL — `TrackerValidationError not raised`, then `AttributeError: module has no attribute 'record_task_review'`.

- [ ] **Step 3: Add validation rule V1**

Inside `_validate_task_review`'s completion loop (the one added in Task 2), alongside V3:

```python
        for row in rows:
            # V1 -- zero open findings at EVERY severity. Severity communicates
            # urgency and risk; it is never a fix/no-fix gate.
            if _count(row["open"], "Open") != 0:
                raise TrackerValidationError(
                    f"task {task_id} is complete with {row['open']} open finding(s) "
                    f"on round {row['round']}; Minor counts"
                )
            if row["state"] in ("dispatched", "blocked"):
                raise TrackerValidationError(
                    f"task {task_id} is complete while round {row['round']} is "
                    f"still {row['state']}"
                )
```

And in the per-row loop, the `approved` invariant:

```python
        if row["state"] == "approved" and _count(row["open"], "Open") != 0:
            raise TrackerValidationError(
                "an approved round carries zero open findings at every severity"
            )
```

- [ ] **Step 4: Write `record_task_review`**

Append to the `# --- dial and gate (P05) ---` section:

```python
_VERDICT_KEYS = ("state", "intensity", "reviewer", "package", "report",
                 "critical", "important", "minor", "adversarial",
                 "adversarial_verdict", "open", "evidence")


def _verdict_row(task_id: str, round_no: int, verdict: dict) -> dict:
    missing = [key for key in _VERDICT_KEYS if key not in verdict]
    if missing:
        raise DialError(f"verdict is missing required keys: {', '.join(missing)}")
    extra = [key for key in verdict if key not in _VERDICT_KEYS]
    if extra:
        raise DialError(f"verdict carries unknown keys: {', '.join(extra)}")
    row = {"task": task_id, "round": str(round_no)}
    row.update({key: str(verdict[key]) for key in _VERDICT_KEYS})
    return row


def record_task_review(run_dir: str, *, task_id: str, attempt: str,
                       verdict: dict) -> dict:
    """Append one review round for a task and supersede the previous round's
    open count.

    `attempt` binds the round to the task's CURRENT reservation: a reviewer
    report produced against a superseded attempt is not evidence about the
    attempt that is running, and is refused rather than silently recorded.

    `Round` is derived, never supplied -- the round number is a fact about the
    ledger, not a caller's claim about it.
    """
    digest = hashlib.sha256(
        json.dumps({"task": task_id, "attempt": attempt, "verdict": verdict},
                   sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]

    def mutate(tracker: dict) -> dict:
        task = next((row for row in tracker["tasks"] if row["id"] == task_id), None)
        if task is None:
            raise DialError(f"no such task: {task_id}")
        if task["attempt"] != attempt:
            raise DialError(
                f"review round is bound to {attempt} but task {task_id} is on "
                f"{task['attempt']}"
            )
        prior = [row for row in tracker["task_review"] if row["task"] == task_id]
        highest = max((INTENSITY_ORDER.index(row["intensity"]) for row in prior),
                      default=-1)
        if INTENSITY_ORDER.index(str(verdict["intensity"])) < highest:
            raise DialError(
                "review intensity is upward-only: a full round is never followed "
                "by a mechanical one"
            )
        for row in prior:
            row["open"] = "0"        # superseded by this round's re-review
        tracker["task_review"].append(
            _verdict_row(task_id, len(prior) + 1, verdict))
        return tracker

    tracker = locked_tracker_update(
        run_dir, transition_id=f"task-review-{task_id}-{attempt}-{digest}",
        mutate=mutate)
    rows = [row for row in tracker["task_review"] if row["task"] == task_id]
    return {"task": task_id, "attempt": attempt, "round": len(rows),
            "state": rows[-1]["state"], "open": int(rows[-1]["open"])}
```

Add `import hashlib, json` at the top of the module if P02 or P03 did not already import them.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, whole file.

- [ ] **Step 6: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): gate completion on zero open findings at every severity"
```

---

### Task 4: The intensity ratchet — upward only, and `full` needs an approval

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `INTENSITY_ORDER`, `CLASS_INTENSITY`, `_rounds_by_task`, `_validate_task_review`.
- Produces: `task_intensity(tracker: dict, task_id: str) -> str`, and validation rules **V2** and **V4**.

**Named fault this task catches:** a `full → mechanical` intensity transition succeeds. Downward reclassification is the cost optimization an autonomous controller is most motivated to make about itself — a run that has already paid for one full round has every incentive to decide the next one can be cheaper — so it must be **structurally impossible**, not discouraged. `record_task_review` refuses to write it (Task 3) and the validator refuses to hold it (here); neither alone is sufficient, because a hand-edited or externally-generated tracker bypasses the first and a buggy caller bypasses the second.

**Second named fault:** a task at `Intensity: full` reaching `[x]` with no `approved` round. The `required` class buys "completion only after a round returns zero" — a task whose last round is `reported` has a reviewer's findings list and no reviewer's approval, and the difference is the whole gate.

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class IntensityRatchetTests(unittest.TestCase):
    def test_full_then_mechanical_is_rejected(self):
        """Downward reclassification is the cost optimization an autonomous
        controller is most motivated to make about itself. Structurally
        impossible, not discouraged."""
        text = valid_text().replace("| P01-T01 | 2 | full |",
                                    "| P01-T01 | 2 | mechanical |")
        text = text.replace(
            "| P01-T01 | 2 | mechanical | approved | reviewer-1 | "
            "scratch/p01-t01-r2-package.md | scratch/p01-t01-r2-review.md |",
            "| P01-T01 | 2 | mechanical | approved | - | "
            "scratch/p01-t01-r2-package.md | - |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_mechanical_then_full_is_accepted(self):
        text = valid_text().replace(
            "| P01-T01 | 1 | full | reported | reviewer-1 | "
            "scratch/p01-t01-r1-package.md | scratch/p01-t01-r1-review.md |",
            "| P01-T01 | 1 | mechanical | reported | - | "
            "scratch/p01-t01-r1-package.md | - |")
        tracker = pipeline_auto_state.parse_tracker(text)
        rows = [r for r in tracker["task_review"] if r["task"] == "P01-T01"]
        self.assertEqual([r["intensity"] for r in rows], ["mechanical", "full"])

    def test_record_task_review_refuses_to_write_a_downgrade(self):
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, final_only_text().replace(
                "| P07-T02 | P07 | source | [ ] | - | - | - | - |",
                "| P07-T02 | P07 | source | [~] | impl-2 | attempt-001 | - | red |"))
            full = {"state": "blocked", "intensity": "full", "reviewer": "reviewer-1",
                    "package": "scratch/p.md", "report": "scratch/r.md",
                    "critical": 1, "important": 0, "minor": 0, "open": 1,
                    "adversarial": "-", "adversarial_verdict": "-",
                    "evidence": "scratch/v.txt"}
            pipeline_auto_state.record_task_review(
                str(run_dir), task_id="P07-T02", attempt="attempt-001", verdict=full)
            downgrade = dict(full, intensity="mechanical", reviewer="-",
                             report="-", state="approved", critical=0, open=0)
            with self.assertRaises(pipeline_auto_state.DialError):
                pipeline_auto_state.record_task_review(
                    str(run_dir), task_id="P07-T02", attempt="attempt-001",
                    verdict=downgrade)


class FullIntensityApprovalTests(unittest.TestCase):
    def test_a_full_task_cannot_complete_without_an_approved_round(self):
        text = valid_text().replace(
            "| P01-T02 | 1 | full | approved | reviewer-3 |",
            "| P01-T02 | 1 | full | reported | reviewer-3 |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_mechanical_only_task_needs_no_approved_round(self):
        """final-only buys mechanical verification only; stage 11 is the net."""
        text = final_only_text().replace(
            "| P07-T01 | 1 | mechanical | approved | - |",
            "| P07-T01 | 1 | mechanical | reported | - |")
        tracker = pipeline_auto_state.parse_tracker(text)
        self.assertEqual(tracker["task_review"][0]["state"], "reported")

    def test_task_intensity_follows_the_phase_review_class(self):
        required = pipeline_auto_state.parse_tracker(valid_text())
        final_only = pipeline_auto_state.parse_tracker(final_only_text())
        self.assertEqual(
            pipeline_auto_state.task_intensity(required, "P02-T01"), "full")
        self.assertEqual(
            pipeline_auto_state.task_intensity(final_only, "P07-T02"), "mechanical")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k IntensityRatchet -k FullIntensityApproval`
Expected: FAIL — `TrackerValidationError not raised`, and `AttributeError: module has no attribute 'task_intensity'`.

- [ ] **Step 3: Write `task_intensity` and rules V2 and V4**

Append to the `# --- dial and gate (P05) ---` section:

```python
def task_intensity(tracker: dict, task_id: str) -> str:
    """The intensity this task's NEXT round must run at, from its phase's
    current review class. Returns an intensity name, never a review class."""
    task = next((row for row in tracker["tasks"] if row["id"] == task_id), None)
    if task is None:
        raise DialError(f"no such task: {task_id}")
    phase = next(row for row in tracker["phases"] if row["id"] == task["phase"])
    return CLASS_INTENSITY[phase["review_class"]]
```

Add to `_validate_task_review`, in the per-task loop that already checks round contiguity:

```python
        # V4 -- intensity is non-decreasing across a task's rounds. A
        # full -> mechanical transition is a downward reclassification wearing
        # a round number's clothes.
        ladder = [INTENSITY_ORDER.index(row["intensity"]) for row in rows]
        if any(later < earlier for earlier, later in zip(ladder, ladder[1:])):
            raise TrackerValidationError(
                f"task {task_id} review intensity went downward; the dial is "
                "upward-only and never switches off"
            )
```

And to the completion loop, beside V1 and V3:

```python
        # V2 -- a task reviewed at full intensity completes only on an approval.
        # `required` buys "completion only after a round returns zero"; a task
        # whose last round is merely `reported` has a findings list and no
        # approval, and the difference is the entire gate.
        if any(row["intensity"] == "full" for row in rows) and not any(
            row["state"] == "approved" for row in rows
        ):
            raise TrackerValidationError(
                f"task {task_id} was reviewed at full intensity and cannot "
                "complete without an approved round"
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): make downward review intensity structurally impossible"
```

---

### Task 5: `## Fix Rounds` — one fixer, all findings, capped at three

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `locked_tracker_update`, `_FIX_ROUND_HEADER`, `_csv`, `_COMMIT`, `DialError`.
- Produces: `FIX_ROUND_CAP = 3`, `FIX_ROUND_STATES`, `_validate_fix_rounds`, `open_fix_round(run_dir, *, scope, findings) -> dict`, `close_fix_round(run_dir, *, scope, round_no, commits, verification, re_review, remaining) -> dict`.

**Named fault this task catches:** a reconciliation incrementing the fix-round counter. The spec: "The fix loop does not stall during reconciliation. The task moves to `[?]` with a reconciliation question reference, its owner slot releases, and independent work continues. The fix-round counter **does not increment** — a decision dispute must not burn the three-round budget and escalate for the wrong reason." A counter that counts reconciliations escalates the *right* task for the *wrong* reason, and the escalation the human sees is about fix capacity rather than about the decision dispute that actually blocked it.

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class FixRoundTests(unittest.TestCase):
    def test_one_fixer_carries_all_findings(self):
        """One fixer with the complete list produces coherent fixes;
        per-finding fixers each rebuild context and produce piecemeal,
        sometimes conflicting edits."""
        text = valid_text().replace("| P02-T01 | 1 | fixing | fixer-1 |",
                                    "| P02-T01 | 1 | fixing | fixer-1,fixer-2 |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_fix_round_names_its_findings(self):
        text = valid_text().replace(
            "| P02-T01 | 1 | fixing | fixer-1 | F-001,F-002 |",
            "| P02-T01 | 1 | fixing | fixer-1 | - |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_fix_round_scope_must_resolve(self):
        text = valid_text().replace("| P02-T01 | 1 | fixing |",
                                    "| P99-T99 | 1 | fixing |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_a_task_cannot_complete_with_a_fix_round_still_fixing(self):
        text = valid_text().replace("| P01-T01 | 1 | complete | fixer-0 |",
                                    "| P01-T01 | 1 | fixing | fixer-0 |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)

    def test_the_cap_is_three_counted_rounds(self):
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, final_only_text())
            for index in range(1, 4):
                pipeline_auto_state.open_fix_round(
                    str(run_dir), scope="P07-T01", findings=[f"F-{index:03d}"])
                pipeline_auto_state.close_fix_round(
                    str(run_dir), scope="P07-T01", round_no=index,
                    commits="5" * 40, verification=f"scratch/fix-{index}.txt",
                    re_review=f"scratch/rr-{index}.md", remaining="none")
            with self.assertRaises(pipeline_auto_state.DialError):
                pipeline_auto_state.open_fix_round(
                    str(run_dir), scope="P07-T01", findings=["F-004"])

    def test_a_reconciling_round_does_not_burn_the_budget(self):
        """A decision dispute must not burn the three-round budget and escalate
        for the wrong reason."""
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, final_only_text())
            pipeline_auto_state.open_fix_round(
                str(run_dir), scope="P07-T01", findings=["F-001"],
                state="reconciling")
            for index in range(1, 4):
                result = pipeline_auto_state.open_fix_round(
                    str(run_dir), scope="P07-T01", findings=[f"F-10{index}"])
                self.assertEqual(result["counted_rounds"], index)
                pipeline_auto_state.close_fix_round(
                    str(run_dir), scope="P07-T01", round_no=result["round"],
                    commits="5" * 40, verification=f"scratch/fix-{index}.txt",
                    re_review=f"scratch/rr-{index}.md", remaining="none")

    def test_rounds_are_contiguous_per_scope(self):
        text = valid_text().replace("| P02-T01 | 1 | fixing |",
                                    "| P02-T01 | 2 | fixing |")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_tracker(text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k FixRound`
Expected: FAIL — `TrackerValidationError not raised`, then `AttributeError: module has no attribute 'open_fix_round'`.

- [ ] **Step 3: Write the validator and the two transitions**

Append to the `# --- dial and gate (P05) ---` section:

```python
FIX_ROUND_CAP = 3
FIX_ROUND_STATES = ("fixing", "complete", "reconciling")
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _counted_rounds(rows: list) -> int:
    """Reconciliation rounds are excluded: a decision dispute must not burn the
    three-round budget and escalate for the wrong reason."""
    return sum(1 for row in rows if row["state"] != "reconciling")


def _validate_fix_rounds(tracker: dict) -> None:
    scopes = ({row["id"] for row in tracker["tasks"]}
              | {row["id"] for row in tracker["phases"]}
              | {row["id"] for row in tracker["gates"]})
    tasks = {row["id"]: row for row in tracker["tasks"]}
    grouped: dict = {}
    for row in tracker["fix_rounds"]:
        if row["scope"] not in scopes:
            raise TrackerValidationError(
                "a fix round names an unknown task, phase, or gate")
        if row["state"] not in FIX_ROUND_STATES:
            raise TrackerValidationError("unknown fix round state")
        if not _OWNER.fullmatch(row["fixer"]):
            raise TrackerValidationError(
                "one fixer per round, carrying all findings: Critical, Important "
                "and Minor together"
            )
        if row["findings"] == "-":
            raise TrackerValidationError("a fix round names the findings it carries")
        if row["state"] == "complete" and any(
            row[key] == "-" for key in ("commits", "verification", "re_review")
        ):
            raise TrackerValidationError(
                "a complete fix round cites its commits, its verification, and "
                "the re-review that confirmed it"
            )
        grouped.setdefault(row["scope"], []).append(row)
    for scope, rows in grouped.items():
        numbers = [_count(row["round"], "Round") for row in rows]
        if numbers != list(range(1, len(numbers) + 1)):
            raise TrackerValidationError(
                "a scope's fix rounds are contiguous and unique, numbered from 1")
        if _counted_rounds(rows) > FIX_ROUND_CAP:
            raise TrackerValidationError(
                f"a scope may not exceed {FIX_ROUND_CAP} counted fix rounds")
        task = tasks.get(scope)
        if task is not None and task["state"] == "[x]" and any(
            row["state"] in ("fixing", "reconciling") for row in rows
        ):
            raise TrackerValidationError(
                f"task {scope} is complete with an unfinished fix round")


def open_fix_round(run_dir: str, *, scope: str, findings: list,
                   fixer: str = "-", state: str = "fixing") -> dict:
    """Open one fix round carrying ALL of that round's findings.

    `findings` is the complete list at every severity. The cap counts only
    rounds that are not `reconciling`.
    """
    if not findings:
        raise DialError("a fix round carries at least one finding")
    if state not in FIX_ROUND_STATES:
        raise DialError(f"unknown fix round state: {state}")
    joined = ",".join(str(item) for item in findings)
    owner = fixer if fixer != "-" else f"fixer-{scope}-{len(joined)}"

    def mutate(tracker: dict) -> dict:
        rows = [row for row in tracker["fix_rounds"] if row["scope"] == scope]
        if state != "reconciling" and _counted_rounds(rows) >= FIX_ROUND_CAP:
            raise DialError(
                f"scope {scope} has used its {FIX_ROUND_CAP} fix rounds; the next "
                "step is escalation, not a fourth round"
            )
        tracker["fix_rounds"].append({
            "scope": scope, "round": str(len(rows) + 1), "state": state,
            "fixer": owner, "findings": joined, "commits": "-",
            "verification": "-", "re_review": "-", "remaining": "-",
        })
        return tracker

    tracker = locked_tracker_update(
        run_dir, transition_id=f"fix-round-{scope}-{joined}", mutate=mutate)
    rows = [row for row in tracker["fix_rounds"] if row["scope"] == scope]
    return {"scope": scope, "round": int(rows[-1]["round"]),
            "counted_rounds": _counted_rounds(rows), "findings": list(findings)}


def close_fix_round(run_dir: str, *, scope: str, round_no: int, commits: str,
                    verification: str, re_review: str, remaining: str) -> dict:
    """Close one fix round. It does NOT clear any ## Task Review open count --
    only the next re-review does, because only a reviewer can say a finding is
    actually gone."""

    def mutate(tracker: dict) -> dict:
        row = next((item for item in tracker["fix_rounds"]
                    if item["scope"] == scope and item["round"] == str(round_no)),
                   None)
        if row is None:
            raise DialError(f"no fix round {round_no} for scope {scope}")
        row.update({"state": "complete", "commits": commits,
                    "verification": verification, "re_review": re_review,
                    "remaining": remaining})
        return tracker

    locked_tracker_update(
        run_dir, transition_id=f"fix-round-close-{scope}-{round_no}", mutate=mutate)
    return {"scope": scope, "round": round_no, "remaining": remaining}
```

Wire it in by adding one line to `_validate_tracker_semantics`, after `_validate_task_review`:

```python
    _validate_fix_rounds(tracker)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): cap fix rounds without counting reconciliations"
```

---

### Task 6: The one-way ratchet — mechanical triggers, no retroactive review

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `locked_tracker_update`, `scopes_overlap` (P04), `_rounds_by_task`, `CLASS_INTENSITY`, `DialError`.
- Produces: `RATCHET_TRIGGERS`, `ratchet_triggers_fired(...) -> tuple`, `ratchet_phase(run_dir, *, phase, trigger, evidence_ref) -> dict`, and validation rule **V5**.

**Named fault this task catches:** a ratchet that retroactively re-reviews complete tasks, or a "ratchet" that lets the class travel downward. The spec is precise on both: "A ratchet does not retroactively review complete tasks. It gates every remaining task and adds a phase-scoped review over the phase's whole edge at the zero-open-findings bar," and "**Upward ratchet only**, `final-only → required`, mechanically triggered, never downward and never by quorum."

**Note on trigger inputs.** Three of the five triggers depend on facts the tracker does not carry — suite-failure counts, stage-10 root-cause paths, and per-task changed-line counts. They are **parameters**, passed in explicitly by the controller from the phase verification log, the debug report, and the review packages. "Mechanical, no judgment" means the function computes the triggers from facts it is given; it never estimates a fact it was not given.

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class RatchetTriggerTests(unittest.TestCase):
    def _final_only(self):
        return pipeline_auto_state.parse_tracker(final_only_text())

    def test_the_trigger_names_are_the_master_plan_tuple(self):
        self.assertEqual(
            pipeline_auto_state.RATCHET_TRIGGERS,
            ("adversarial-finding", "repeated-suite-failure", "debug-locality",
             "low-confidence-dependency", "accumulated-surface"),
        )

    def test_an_adversarial_pass_returning_anything_but_safe_fires(self):
        text = final_only_text().replace(
            "| 0 | 0 | 0 | - | - | 0 | scratch/p07-t01-r1-verify.txt |",
            "| 0 | 1 | 0 | authz | findings | 1 | scratch/p07-t01-r1-verify.txt |")
        text = text.replace("| P07-T01 | P07 | source | [x] |",
                            "| P07-T01 | P07 | source | [~] |")
        text = text.replace(
            "| P07-T01 | P07 | source | [~] | impl-1 | attempt-001 | "
            "scratch/p07-t01-result.md | red,green | "
            "refs/heads/feat/pipeline-auto | "
            "3333333333333333333333333333333333333333 | - | "
            "4444444444444444444444444444444444444444 | "
            "scratch/p07-t01-tests.txt | - | no |",
            "| P07-T01 | P07 | source | [~] | impl-1 | attempt-001 | - | "
            "red,green | - | - | - | - | - | - | no |")
        tracker = pipeline_auto_state.parse_tracker(text)
        self.assertIn("adversarial-finding",
                      pipeline_auto_state.ratchet_triggers_fired(tracker, phase="P07"))

    def test_a_code_evidenced_adoption_in_the_phase_fires(self):
        """(d): a quorum adopted a decision in this phase at code-evidenced
        rather than specified."""
        tracker = self._final_only()
        tracker["quorum"].append({
            "qid": "a" * 12, "axis": "axis-1", "phase": "P07", "state": "finalized",
            "owners": "brain-1,brain-2,brain-3", "payload_digest": "b" * 64,
            "context_digest": "c" * 64, "responses": "scratch/q.json", "depth": "1",
            "rung": "code-evidenced", "outcome": "adopted", "decision": "Q-" + "a" * 12,
        })
        self.assertIn("low-confidence-dependency",
                      pipeline_auto_state.ratchet_triggers_fired(tracker, phase="P07"))

    def test_a_specified_adoption_does_not_fire(self):
        tracker = self._final_only()
        tracker["quorum"].append({
            "qid": "a" * 12, "axis": "axis-1", "phase": "P07", "state": "finalized",
            "owners": "brain-1,brain-2,brain-3", "payload_digest": "b" * 64,
            "context_digest": "c" * 64, "responses": "scratch/q.json", "depth": "1",
            "rung": "specified", "outcome": "adopted", "decision": "Q-" + "a" * 12,
        })
        self.assertEqual(
            pipeline_auto_state.ratchet_triggers_fired(tracker, phase="P07"), ())

    def test_cumulative_changed_lines_over_three_hundred_fire(self):
        self.assertIn(
            "accumulated-surface",
            pipeline_auto_state.ratchet_triggers_fired(
                self._final_only(), phase="P07",
                changed_lines={"P07-T01": 180, "P07-T02": 140}),
        )

    def test_two_suite_failures_fire(self):
        self.assertIn(
            "repeated-suite-failure",
            pipeline_auto_state.ratchet_triggers_fired(
                self._final_only(), phase="P07", suite_failures=2))

    def test_a_root_cause_inside_the_phase_scopes_fires(self):
        self.assertIn(
            "debug-locality",
            pipeline_auto_state.ratchet_triggers_fired(
                self._final_only(), phase="P07",
                debug_root_cause_paths=("file:src/dial.py",),
                phase_scopes=("tree:src",)),
        )

    def test_a_root_cause_outside_the_phase_scopes_does_not_fire(self):
        self.assertEqual(
            pipeline_auto_state.ratchet_triggers_fired(
                self._final_only(), phase="P07",
                debug_root_cause_paths=("file:other/x.py",),
                phase_scopes=("tree:src",)),
            (),
        )


class RatchetPhaseTests(unittest.TestCase):
    def test_a_ratchet_raises_the_class_and_records_trigger_and_evidence(self):
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, final_only_text())
            result = pipeline_auto_state.ratchet_phase(
                str(run_dir), phase="P07", trigger="adversarial-finding",
                evidence_ref="scratch/p07-adversarial.md")
            self.assertEqual(result["status"], "ratcheted")
            tracker = pipeline_auto_state.validate_run(str(run_dir))
            phase = next(r for r in tracker["phases"] if r["id"] == "P07")
            self.assertEqual(
                (phase["review_class"], phase["class_source"], phase["ratchet"]),
                ("required", "ratchet",
                 "adversarial-finding@scratch/p07-adversarial.md"))

    def test_a_ratchet_does_not_retroactively_review_complete_tasks(self):
        """It gates every REMAINING task. P07-T01 is [x] with a mechanical
        round; that round is untouched and no new round is opened for it."""
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, final_only_text())
            before = pipeline_auto_state.validate_run(str(run_dir))["task_review"]
            result = pipeline_auto_state.ratchet_phase(
                str(run_dir), phase="P07", trigger="accumulated-surface",
                evidence_ref="scratch/p07-lines.txt")
            tracker = pipeline_auto_state.validate_run(str(run_dir))
            self.assertEqual(tracker["task_review"], before)
            self.assertEqual(result["gated_tasks"], ["P07-T02"])

    def test_a_ratchet_adds_a_phase_scoped_review_over_the_whole_edge(self):
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, final_only_text())
            pipeline_auto_state.ratchet_phase(
                str(run_dir), phase="P07", trigger="repeated-suite-failure",
                evidence_ref="scratch/p07-suite.txt")
            tracker = pipeline_auto_state.validate_run(str(run_dir))
            gate = next(r for r in tracker["gates"] if r["id"] == "gate-p07-ratchet")
            self.assertEqual((gate["type"], gate["phase"]), ("phase", "P07"))

    def test_an_unknown_trigger_is_refused(self):
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, final_only_text())
            with self.assertRaises(pipeline_auto_state.DialError):
                pipeline_auto_state.ratchet_phase(
                    str(run_dir), phase="P07", trigger="seems-risky",
                    evidence_ref="scratch/x.md")

    def test_ratcheting_an_already_required_phase_is_inert(self):
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, valid_text())
            result = pipeline_auto_state.ratchet_phase(
                str(run_dir), phase="P01", trigger="adversarial-finding",
                evidence_ref="scratch/x.md")
            self.assertEqual(result["status"], "already-required")
            phase = next(r for r in pipeline_auto_state.validate_run(str(run_dir))
                         ["phases"] if r["id"] == "P01")
            self.assertEqual(phase["class_source"], "plan")

    def test_a_ratcheted_phase_gates_every_remaining_task(self):
        """V5: after the ratchet, an incomplete task in the phase may not have
        its latest round at mechanical."""
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, final_only_text())
            pipeline_auto_state.ratchet_phase(
                str(run_dir), phase="P07", trigger="accumulated-surface",
                evidence_ref="scratch/p07-lines.txt")
            tracker = pipeline_auto_state.validate_run(str(run_dir))
            text = pipeline_auto_state.render_tracker(tracker).replace(
                "| P07-T02 | P07 | source | [ ] | - | - | - | - |",
                "| P07-T02 | P07 | source | [~] | impl-2 | attempt-001 | - | red |")
            text = text.replace(
                "## Fix Rounds",
                "| P07-T02 | 1 | mechanical | reported | - | scratch/p.md | - | "
                "0 | 0 | 0 | - | - | 0 | scratch/v.txt |\n\n## Fix Rounds")
            with self.assertRaises(pipeline_auto_state.TrackerValidationError):
                pipeline_auto_state.parse_tracker(text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k RatchetTrigger -k RatchetPhase`
Expected: FAIL — `AttributeError: module has no attribute 'RATCHET_TRIGGERS'`.

- [ ] **Step 3: Write the trigger evaluator and the ratchet transition**

Append to the `# --- dial and gate (P05) ---` section:

```python
RATCHET_TRIGGERS = ("adversarial-finding", "repeated-suite-failure",
                    "debug-locality", "low-confidence-dependency",
                    "accumulated-surface")

_SUITE_FAILURE_RATCHET = 2
_PHASE_SURFACE_LINES = 300


def ratchet_triggers_fired(tracker: dict, *, phase: str, suite_failures: int = 0,
                           debug_root_cause_paths: tuple = (),
                           phase_scopes: tuple = (),
                           changed_lines: dict | None = None) -> tuple:
    """Every ratchet trigger currently fired for one phase, in RATCHET_TRIGGERS
    order. Mechanical: no judgment, no thresholds a caller can move.

    Three of the five depend on facts the tracker does not carry -- the phase
    suite's failure count, stage 10's root-cause paths, and per-task changed
    line counts. They are parameters. The function computes triggers from facts
    it is GIVEN; it never estimates a fact it was not given.
    """
    phase_tasks = {row["id"] for row in tracker["tasks"] if row["phase"] == phase}
    fired = []

    # (a) any task produced a CONFIRMED or unrefuted PLAUSIBLE adversarial
    #     finding -- recorded as an adversarial verdict that is not `safe`.
    if any(row["task"] in phase_tasks and row["adversarial"] != "-"
           and row["adversarial_verdict"] == "findings"
           for row in tracker["task_review"]):
        fired.append("adversarial-finding")

    # (b) the phase suite has failed twice or more.
    if int(suite_failures) >= _SUITE_FAILURE_RATCHET:
        fired.append("repeated-suite-failure")

    # (c) a stage-10 root cause traced into a file inside this phase's write
    #     scopes. Scope comparison is P04's; this function never re-implements it.
    if any(scopes_overlap(cause, scope)
           for cause in debug_root_cause_paths for scope in phase_scopes):
        fired.append("debug-locality")

    # (d) a quorum adopted a decision in this phase at code-evidenced rather
    #     than specified.
    if any(row["phase"] == phase and row["outcome"] == "adopted"
           and row["rung"] == "code-evidenced" for row in tracker["quorum"]):
        fired.append("low-confidence-dependency")

    # (e) cumulative changed source lines in the phase exceed 300.
    counts = changed_lines or {}
    if sum(int(counts.get(task_id, 0)) for task_id in phase_tasks) > _PHASE_SURFACE_LINES:
        fired.append("accumulated-surface")

    return tuple(name for name in RATCHET_TRIGGERS if name in fired)


def ratchet_phase(run_dir: str, *, phase: str, trigger: str,
                  evidence_ref: str) -> dict:
    """Raise one phase from final-only to required.

    UPWARD ONLY. There is no downward counterpart and no parameter that could
    become one: this function's only write to `Review Class` is the literal
    string "required".

    It does NOT retroactively review complete tasks -- no ## Task Review row is
    read, written, or removed here. It gates every REMAINING task (V5 then
    refuses a mechanical latest round on any of them) and opens a phase-scoped
    gate over the phase's whole edge at the zero-open-findings bar.
    """
    if trigger not in RATCHET_TRIGGERS:
        raise DialError(f"unknown ratchet trigger: {trigger}")
    if evidence_ref == "-":
        raise DialError("a ratchet cites the evidence that fired it")
    gate_id = f"gate-{phase.lower()}-ratchet"

    def mutate(tracker: dict) -> dict:
        row = next((item for item in tracker["phases"] if item["id"] == phase), None)
        if row is None:
            raise DialError(f"no such phase: {phase}")
        if row["review_class"] == "required":
            return tracker
        row["review_class"] = "required"
        row["class_source"] = "ratchet"
        row["ratchet"] = f"{trigger}@{evidence_ref}"
        if not any(gate["id"] == gate_id for gate in tracker["gates"]):
            tracker["gates"].append({
                "id": gate_id, "type": "phase", "phase": phase, "state": "pending",
                "base": "-", "head": "-", "assignments": "-", "reports": "-",
                "verification": "-", "findings": tracker["run"]["findings"],
            })
        return tracker

    before = validate_run(run_dir)
    already = next(item for item in before["phases"]
                   if item["id"] == phase)["review_class"] == "required"
    tracker = locked_tracker_update(
        run_dir, transition_id=f"ratchet-{phase}-{trigger}", mutate=mutate)
    gated = [task["id"] for task in tracker["tasks"]
             if task["phase"] == phase and task["state"] != "[x]"]
    return {"status": "already-required" if already else "ratcheted",
            "phase": phase, "trigger": trigger, "evidence": evidence_ref,
            "gate": None if already else gate_id, "gated_tasks": gated}
```

- [ ] **Step 4: Add validation rule V5**

Append to `_validate_task_review`, in the per-task loop:

```python
        # V5 -- a ratchet gates every REMAINING task. A completed task keeps the
        # mechanical rounds it completed under: a ratchet does not retroactively
        # review complete tasks.
        task = tasks[task_id]
        if task["state"] != "[x]":
            phase = next(row for row in tracker["phases"]
                         if row["id"] == task["phase"])
            required = CLASS_INTENSITY[phase["review_class"]]
            if INTENSITY_ORDER.index(rows[-1]["intensity"]) < \
                    INTENSITY_ORDER.index(required):
                raise TrackerValidationError(
                    f"task {task_id} is incomplete in a {phase['review_class']} "
                    f"phase and its latest round is {rows[-1]['intensity']}"
                )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, whole file.

- [ ] **Step 6: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): ratchet review class upward without retroactive review"
```

---

### Task 7: Provisional propagation and the verbatim reviewer constraints block

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `RATCHET_TRIGGERS`, `ratchet_phase`, `parse_tracker`, `DialError`.
- Produces: `propagate_provisional(tracker: dict) -> dict`, `provisional_constraints_block(tracker: dict, *, task_id: str, adopted_answers: dict) -> str`.

**Named fault this task catches:** provisionality recorded as a label and nothing else. The spec is explicit that the label is the smaller half: "The tainting decision's ID and adopted answer are copied **verbatim into the reviewer's global-constraints block** — that second half is what makes it more than a label." A `Provisional: yes` cell that no reviewer ever reads has informed nobody, exactly like the provenance field the spec insists must be visible in three places.

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class ProvisionalPropagationTests(unittest.TestCase):
    def _tainted(self):
        tracker = pipeline_auto_state.parse_tracker(final_only_text())
        tracker["tasks"][1]["state"] = "[~]"
        tracker["tasks"][1]["owner"] = "impl-2"
        tracker["tasks"][1]["attempt"] = "attempt-001"
        tracker["tasks"][1]["checkpoints"] = "red"
        tracker["tasks"][1]["question"] = "scratch/p07-t02-question.md"
        tracker["quorum"].append({
            "qid": "d" * 12, "axis": "axis-1", "phase": "P07", "state": "finalized",
            "owners": "brain-1,brain-2,brain-3", "payload_digest": "b" * 64,
            "context_digest": "c" * 64, "responses": "scratch/q.json", "depth": "1",
            "rung": "code-evidenced", "outcome": "adopted", "decision": "Q-" + "d" * 12,
        })
        return tracker

    def test_a_code_evidenced_adoption_taints_the_phase_s_open_tasks(self):
        result = pipeline_auto_state.propagate_provisional(self._tainted())
        self.assertIn("P07-T02", result["tainted"])
        task = next(r for r in result["tracker"]["tasks"] if r["id"] == "P07-T02")
        self.assertEqual(task["provisional"], "yes")

    def test_a_specified_adoption_taints_nothing(self):
        tracker = self._tainted()
        tracker["quorum"][-1]["rung"] = "specified"
        result = pipeline_auto_state.propagate_provisional(tracker)
        self.assertEqual(result["tainted"], [])

    def test_a_taint_requires_the_phase_to_ratchet(self):
        """Provisionality ratchets its phase to required."""
        result = pipeline_auto_state.propagate_provisional(self._tainted())
        self.assertEqual(result["ratchet"],
                         {"P07": "low-confidence-dependency"})

    def test_a_complete_task_is_not_retroactively_tainted(self):
        result = pipeline_auto_state.propagate_provisional(self._tainted())
        self.assertNotIn("P07-T01", result["tainted"])

    def test_the_reviewer_block_carries_the_decision_id_and_answer_verbatim(self):
        tracker = pipeline_auto_state.propagate_provisional(
            self._tainted())["tracker"]
        block = pipeline_auto_state.provisional_constraints_block(
            tracker, task_id="P07-T02",
            adopted_answers={"Q-" + "d" * 12: "Back the session table with SQLite."})
        self.assertIn("Q-" + "d" * 12, block)
        self.assertIn("Back the session table with SQLite.", block)
        self.assertIn("code-evidenced", block)

    def test_an_untainted_task_produces_an_empty_block(self):
        tracker = pipeline_auto_state.parse_tracker(final_only_text())
        self.assertEqual(
            pipeline_auto_state.provisional_constraints_block(
                tracker, task_id="P07-T01", adopted_answers={}),
            "",
        )

    def test_a_missing_adopted_answer_is_refused_rather_than_summarised(self):
        tracker = pipeline_auto_state.propagate_provisional(
            self._tainted())["tracker"]
        with self.assertRaises(pipeline_auto_state.DialError):
            pipeline_auto_state.provisional_constraints_block(
                tracker, task_id="P07-T02", adopted_answers={})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ProvisionalPropagation`
Expected: FAIL — `AttributeError: module has no attribute 'propagate_provisional'`.

- [ ] **Step 3: Write the propagation**

Append to the `# --- dial and gate (P05) ---` section:

```python
def _tainting_decisions(tracker: dict, phase: str) -> list:
    """Adopted quorum rows in one phase whose rung is below `specified`.

    The spec's tainting condition is 'adopted at code-evidenced rather than
    specified'. Only `specified` and `code-evidenced` are adoptable at all, so
    this is every adopted row that is not `specified`.
    """
    return [row for row in tracker["quorum"]
            if row["phase"] == phase and row["outcome"] == "adopted"
            and row["rung"] != "specified"]


def propagate_provisional(tracker: dict) -> dict:
    """Mark every task resting on a below-`specified` adoption as provisional
    and name the phases that must ratchet.

    A tainted task obliges stage-11 reviewer A to score and name it, and lists
    it in the terminal report. The caller applies `ratchet` through
    `ratchet_phase` -- this function is pure and writes no file.

    A COMPLETE task is not retroactively tainted, for the same reason a ratchet
    does not retroactively review one.
    """
    tainted, ratchet = [], {}
    for phase_row in tracker["phases"]:
        phase = phase_row["id"]
        decisions = _tainting_decisions(tracker, phase)
        if not decisions:
            continue
        ratchet[phase] = "low-confidence-dependency"
        for task in tracker["tasks"]:
            if task["phase"] != phase or task["state"] == "[x]":
                continue
            task["provisional"] = "yes"
            tainted.append(task["id"])
    return {"tracker": tracker, "tainted": tainted, "ratchet": ratchet}


def provisional_constraints_block(tracker: dict, *, task_id: str,
                                  adopted_answers: dict) -> str:
    """The block copied VERBATIM into the reviewer's global constraints.

    A `Provisional: yes` cell that no reviewer reads has informed nobody. The
    tainting decision's ID and its adopted answer travel into the review
    dispatch word for word -- never paraphrased, never summarised, and never
    omitted because the answer was not supplied.
    """
    task = next((row for row in tracker["tasks"] if row["id"] == task_id), None)
    if task is None:
        raise DialError(f"no such task: {task_id}")
    if task["provisional"] != "yes":
        return ""
    lines = ["## Provisional dependency — this task rests on a machine decision",
             "",
             "This task's dependency closure contains a quorum decision adopted "
             "below `specified`. Score it and name it in your report.",
             ""]
    for row in _tainting_decisions(tracker, task["phase"]):
        decision_id = row["decision"]
        if decision_id not in adopted_answers:
            raise DialError(
                f"the adopted answer for {decision_id} was not supplied; the "
                "reviewer block carries it verbatim or not at all"
            )
        lines.append(f"- **{decision_id}** (adopted at `{row['rung']}`, axis "
                     f"`{row['axis']}`): {adopted_answers[decision_id]}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): propagate provisionality into the reviewer constraints"
```

---

### Task 8: Rungs inherit downward — the minimum cap

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `RUNG_ORDER` (P03), `_tainting_decisions`, `DialError`.
- Produces: `inherited_rung_cap(tracker: dict, *, qid: str) -> str | None`.

**Named fault this task catches:** a quorum raised by a tainted task adopting at a rung **higher** than the tainting decision's. The spec: "A quorum raised *by* a tainted task inherits the taint, and its adopted rung is capped at the minimum of its own and the tainting decision's. A `specified` answer resting on a `code-evidenced` premise is not a `specified` answer. Without this the argmax will happily build a tower on a weak root, laundering a soft premise into confident descendants."

This is the compounding failure: each individual step looks well-grounded, and the run's mean effective value goes *up* as the foundation gets weaker, so even the run-level inflation check reads the tower as healthy.

**Ordering note.** `RUNG_ORDER` is **highest rung first**, so the *lower* of two rungs is the one with the *larger* index. Every comparison here uses `RUNG_ORDER.index`, never a float from `RUNGS` — a float comparison is the version of this code that silently inverts when someone reorders the ladder.

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class InheritedRungCapTests(unittest.TestCase):
    def _with_tainted_descendant(self, own_rung):
        """P07-T02 is tainted by a code-evidenced adoption, then raises its own
        quorum which clusters at `own_rung`."""
        tracker = pipeline_auto_state.parse_tracker(final_only_text())
        tracker["tasks"][1].update({
            "state": "[?]", "owner": "impl-2", "attempt": "attempt-001",
            "checkpoints": "blocked:attempt-001@scratch/p07-t02-question.md",
            "question": "scratch/p07-t02-question.md",
        })
        tracker["quorum"].extend([
            {"qid": "d" * 12, "axis": "axis-1", "phase": "P07",
             "state": "finalized", "owners": "brain-1,brain-2,brain-3",
             "payload_digest": "b" * 64, "context_digest": "c" * 64,
             "responses": "scratch/q1.json", "depth": "1",
             "rung": "code-evidenced", "outcome": "adopted",
             "decision": "Q-" + "d" * 12},
            {"qid": "e" * 12, "axis": "new", "phase": "P07",
             "state": "finalized", "owners": "brain-4,brain-5,brain-6",
             "payload_digest": "f" * 64, "context_digest": "c" * 64,
             "responses": "scratch/q2.json", "depth": "2",
             "rung": own_rung, "outcome": "adopted",
             "decision": "Q-" + "e" * 12},
        ])
        pipeline_auto_state.propagate_provisional(tracker)
        return tracker

    def test_a_specified_answer_on_a_code_evidenced_premise_is_capped(self):
        """A specified answer resting on a code-evidenced premise is not a
        specified answer."""
        tracker = self._with_tainted_descendant("specified")
        self.assertEqual(
            pipeline_auto_state.inherited_rung_cap(tracker, qid="e" * 12),
            "code-evidenced",
        )

    def test_the_cap_is_the_minimum_of_the_two_not_the_descendant_s_own(self):
        tracker = self._with_tainted_descendant("convention-cited")
        self.assertEqual(
            pipeline_auto_state.inherited_rung_cap(tracker, qid="e" * 12),
            "convention-cited",
        )

    def test_an_untainted_quorum_is_not_capped(self):
        tracker = pipeline_auto_state.parse_tracker(final_only_text())
        tracker["quorum"].append(
            {"qid": "e" * 12, "axis": "new", "phase": "P07", "state": "finalized",
             "owners": "brain-4,brain-5,brain-6", "payload_digest": "f" * 64,
             "context_digest": "c" * 64, "responses": "scratch/q2.json",
             "depth": "1", "rung": "specified", "outcome": "adopted",
             "decision": "Q-" + "e" * 12})
        self.assertIsNone(
            pipeline_auto_state.inherited_rung_cap(tracker, qid="e" * 12))

    def test_the_cap_uses_rung_order_and_never_a_float(self):
        """RUNG_ORDER is highest-first: the LOWER rung has the LARGER index.
        A float comparison silently inverts when someone reorders the ladder."""
        tracker = self._with_tainted_descendant("specified")
        cap = pipeline_auto_state.inherited_rung_cap(tracker, qid="e" * 12)
        self.assertGreater(pipeline_auto_state.RUNG_ORDER.index(cap),
                           pipeline_auto_state.RUNG_ORDER.index("specified"))

    def test_an_unknown_qid_is_refused(self):
        tracker = pipeline_auto_state.parse_tracker(final_only_text())
        with self.assertRaises(pipeline_auto_state.DialError):
            pipeline_auto_state.inherited_rung_cap(tracker, qid="0" * 12)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k InheritedRungCap`
Expected: FAIL — `AttributeError: module has no attribute 'inherited_rung_cap'`.

- [ ] **Step 3: Write the cap**

Append to the `# --- dial and gate (P05) ---` section:

```python
def inherited_rung_cap(tracker: dict, *, qid: str) -> str | None:
    """The rung this quorum may adopt at, given the taint of the task that
    raised it -- or None when no cap applies.

    A quorum raised BY a tainted task inherits the taint, and its adopted rung
    is capped at the minimum of its own and the tainting decision's. Without
    this the argmax builds a tower on a weak root, laundering a soft premise
    into confident descendants -- and because each step looks well-grounded on
    its own, the run-level inflation check reads the tower as healthy.

    RUNG_ORDER is highest-first, so the minimum of two rungs is the one with
    the LARGER index. Never compare the floats in RUNGS here.
    """
    row = next((item for item in tracker["quorum"] if item["qid"] == qid), None)
    if row is None:
        raise DialError(f"no such quorum record: {qid}")
    provisional = {task["id"] for task in tracker["tasks"]
                   if task["provisional"] == "yes" and task["phase"] == row["phase"]}
    if not provisional:
        return None
    premises = [item["rung"] for item in _tainting_decisions(tracker, row["phase"])
                if item["qid"] != qid]
    if not premises:
        return None
    own = row["rung"] if row["rung"] in RUNG_ORDER else RUNG_ORDER[-1]
    weakest = max([own] + premises, key=RUNG_ORDER.index)
    return weakest
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): cap an inherited rung at its weakest premise"
```

---

### Task 9: Wire the dial end to end and prove a `final-only` phase ratchets

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: every P05 name above.
- Produces: no new names. This task confirms `_validate_tracker_semantics` calls `_validate_task_review` and `_validate_fix_rounds`, that `derive_next_action` is unaffected, and that the phase's whole story runs.

**Named fault this task catches:** a validator rule written and never wired. Rules V1–V5 all live inside `_validate_task_review`; if the one line adding it to `_validate_tracker_semantics` is lost in a merge, every completion test in this phase starts passing vacuously — `parse_tracker` accepts everything and the `assertRaises` blocks never fire because the *fixture manipulation* is what they were really testing. The wiring test is the only thing standing between that and a silently disabled gate.

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class DialWiringTests(unittest.TestCase):
    def test_the_p05_validators_are_wired_into_the_dispatcher(self):
        """A rule written and never wired makes every assertRaises in this phase
        pass vacuously."""
        import inspect
        source = inspect.getsource(pipeline_auto_state._validate_tracker_semantics)
        self.assertIn("_validate_task_review(tracker)", source)
        self.assertIn("_validate_fix_rounds(tracker)", source)

    def test_the_never_off_surface_is_exported(self):
        for name in ("ADVERSARIAL_TRIGGERS", "RATCHET_TRIGGERS",
                     "LARGE_SURFACE_LINES", "FIX_ROUND_CAP", "INTENSITIES",
                     "adversarial_required", "record_task_review",
                     "open_fix_round", "ratchet_phase", "propagate_provisional",
                     "task_intensity", "ratchet_triggers_fired",
                     "provisional_constraints_block", "inherited_rung_cap"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(pipeline_auto_state, name))

    def test_a_final_only_phase_runs_its_whole_story(self):
        with contextlib.ExitStack() as stack:
            _, run_dir = new_run(stack)
            seed(run_dir, final_only_text().replace(
                "| P07-T02 | P07 | source | [ ] | - | - | - | - |",
                "| P07-T02 | P07 | source | [~] | impl-2 | attempt-001 | - | red |"))

            # The trigger check runs at mechanical intensity, as it always does.
            trigger = pipeline_auto_state.adversarial_required(
                ["src/auth/session.py"], 10)
            self.assertEqual(trigger, "authz")

            pipeline_auto_state.record_task_review(
                str(run_dir), task_id="P07-T02", attempt="attempt-001",
                verdict={"state": "blocked", "intensity": "mechanical",
                         "reviewer": "-", "package": "scratch/p07-t02-pkg.md",
                         "report": "-", "critical": 1, "important": 0, "minor": 0,
                         "open": 1, "adversarial": trigger,
                         "adversarial_verdict": "findings",
                         "evidence": "scratch/p07-t02-verify.txt"})

            # (a) fires: an adversarial pass returned anything but safe.
            tracker = pipeline_auto_state.validate_run(str(run_dir))
            self.assertEqual(
                pipeline_auto_state.ratchet_triggers_fired(tracker, phase="P07"),
                ("adversarial-finding",))

            result = pipeline_auto_state.ratchet_phase(
                str(run_dir), phase="P07", trigger="adversarial-finding",
                evidence_ref="scratch/p07-t02-adversarial.md")
            self.assertEqual(result["gated_tasks"], ["P07-T02"])

            # The remaining task is now gated at full intensity.
            tracker = pipeline_auto_state.validate_run(str(run_dir))
            self.assertEqual(
                pipeline_auto_state.task_intensity(tracker, "P07-T02"), "full")

            pipeline_auto_state.open_fix_round(
                str(run_dir), scope="P07-T02", findings=["F-001"], fixer="fixer-1")
            pipeline_auto_state.close_fix_round(
                str(run_dir), scope="P07-T02", round_no=1, commits="6" * 40,
                verification="scratch/fix-1.txt", re_review="scratch/rr-1.md",
                remaining="none")
            pipeline_auto_state.record_task_review(
                str(run_dir), task_id="P07-T02", attempt="attempt-001",
                verdict={"state": "approved", "intensity": "full",
                         "reviewer": "reviewer-1", "package": "scratch/p07-t02-pkg2.md",
                         "report": "scratch/p07-t02-review2.md", "critical": 0,
                         "important": 0, "minor": 0, "open": 0,
                         "adversarial": trigger, "adversarial_verdict": "safe",
                         "evidence": "scratch/p07-t02-verify2.txt"})

            def complete(tracker):
                task = next(r for r in tracker["tasks"] if r["id"] == "P07-T02")
                task.update({"state": "[x]", "result": "scratch/p07-t02-result.md",
                             "verification": "scratch/p07-t02-tests.txt",
                             "source_ref": "refs/heads/feat/pipeline-auto",
                             "commits": "7" * 40, "integration": "8" * 40})
                return tracker

            pipeline_auto_state.locked_tracker_update(
                str(run_dir), transition_id="complete-P07-T02", mutate=complete)
            tracker = pipeline_auto_state.validate_run(str(run_dir))
            self.assertEqual(
                next(r for r in tracker["tasks"] if r["id"] == "P07-T02")["state"],
                "[x]")
            # And the completed task's first, mechanical round is untouched.
            first = next(r for r in tracker["task_review"]
                         if r["task"] == "P07-T02" and r["round"] == "1")
            self.assertEqual(first["intensity"], "mechanical")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k DialWiring`
Expected: FAIL if either validator line is missing; if Tasks 1–8 wired both, the first two pass and only `test_a_final_only_phase_runs_its_whole_story` may fail on ordering.

- [ ] **Step 3: Confirm the wiring**

`_validate_tracker_semantics` must read, in this order:

```python
def _validate_tracker_semantics(tracker: dict) -> None:
    _validate_stages(tracker)
    _validate_intent(tracker)
    _validate_questions(tracker)
    _validate_quorum(tracker)
    _validate_escalations(tracker)
    _validate_phases(tracker)
    _validate_tasks(tracker)
    _validate_task_review(tracker)
    _validate_fix_rounds(tracker)
    _validate_gates(tracker)
```

`_validate_phases` stays before `_validate_tasks` (P02's ordering, so an unknown phase id is reported against the phase table) and `_validate_task_review` after `_validate_tasks`, so a review row naming a structurally invalid task is reported against the task table first. Add any P05 line that is missing; change nothing else.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, whole file.

Then run the phase's ordered verification tuple:

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

Expected: the test command PASSes; both git commands print nothing.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): wire the dial validators and prove a final-only ratchet"
```

---

## Self-review

**Spec coverage.** Every clause of the spec's "Review-intensity dial" maps to a task: `review_class ∈ {final-only, required}` mirrored into the tracker → Task 1 and P02's `_validate_phases`; what `required` buys (task brief, package from the persisted baseline, three verdicts, fix loop to zero open findings at every severity, completion only after a zero round) → Tasks 3, 4, 5; what `final-only` buys → Tasks 1, 2; the never-off list → Task 2 (trigger check, package, evidence), Task 3 (zero-open-findings bar), Task 4 (the dial controls whether a reviewer runs, never the bar); independent adversarial triggers and the 10-line auth change → Task 2; the upward ratchet table (a)–(e) → Task 6; "a ratchet does not retroactively review complete tasks" → Task 6 and rule V5's completion exemption; "a tracker `review_class` differing from plan metadata is legal only with a matching ratchet record" → P02's `_validate_phases`, re-exercised by Task 6. From "Failure modes and mitigations": "Cascading on a low-confidence answer" → Task 7; "Rungs inherit downward" → Task 8. From "Contradiction routing": the reconciliation path's non-incrementing fix-round counter → Task 5.

**Coverage of the master plan's P05 block.** All five `ADVERSARIAL_TRIGGERS` / `RATCHET_TRIGGERS` / function names appear verbatim with the declared signatures. `adversarial_required` returns the trigger name or `None`, never a boolean, per the master plan's type note.

**Placeholder scan.** No TBDs, no "add appropriate validation", no "similar to Task N". Every step carries the code or the exact command and its expected output. Every fixture is written out in full.

**Type consistency.** `adversarial_required -> str | None` (trigger name). `task_intensity -> str` in `INTENSITIES`, never a review class. `ratchet_triggers_fired -> tuple` in `RATCHET_TRIGGERS` order. `inherited_rung_cap -> str | None` (rung name), compared by `RUNG_ORDER.index`, never by a float from `RUNGS`. `propagate_provisional -> dict` with keys `tracker`, `tainted`, `ratchet`. `ratchet_phase(...)["status"]` is `ratcheted` or `already-required`. `record_task_review(...)` returns `round` as an `int` while the tracker cell is a `str`, matching P02's "every cell is a string" rule.

**Ordering check.** Task 2 needs Task 1's fourteen-column header; Task 4's V5 needs Task 6's ratchet only at test time, and the rule itself is added in Task 6, so Task 4 ships V2 and V4 only. Task 8 needs Task 7's `_tainting_decisions`. Task 9 needs all of them. No task depends on a later one.

**The one-row-per-task invariant.** Nothing in P05 adds, removes, or duplicates a `## Tasks` row. `propagate_provisional` mutates only the `Provisional` cell; `ratchet_phase` mutates only `## Phases` and appends to `## Gates`. P04's `reserve_task` and `resume_task` continue to find exactly one row per task id.

---

## Unresolved — reported, not invented

Six items the spec and master plan do not settle. None is invented here; each is implemented in the narrowest form the two documents actually support, and flagged.

1. **`## Task Review`'s column set conflicts with P02's.** P02 shipped a nine-column placeholder — `Task, Attempt, Reviewer, State, Spec Verdict, Quality Verdict, Verification, Findings, Adversarial` — which cannot express N rounds per task, per-round intensity, per-severity counts, or a live open count, and therefore cannot carry any of rules V1–V5. Task 1 replaces it with the fourteen-column round-scoped form. **This is a schema change to already-built P02 code**, not an addition to it: P02's fixture, template and header constant all change. Flagging it because a reviewer of P05 will otherwise read it as scope creep, and because P06's plan may already be written against the nine-column form.

2. **`record_task_review`'s `attempt` parameter versus the `Round` column.** The master plan freezes `record_task_review(run_dir, *, task_id, attempt, verdict)`, but the fourteen-column set has `Round` and no `Attempt`. Implemented as: `attempt` binds the round to the task's current reservation and is refused if stale; `Round` is derived from the ledger. The attempt is therefore validated but not stored on the review row. If P06 needs to attribute a historical round to a superseded attempt, the column set needs a fifteenth column and this plan does not add one.

3. **`DONE_WITH_CONCERNS` as a ratchet trigger has no name.** The directing brief lists "`DONE_WITH_CONCERNS` with a correctness or scope concern" among the ratchet triggers, but the spec's table (a)–(e) does not contain it and the master plan's frozen `RATCHET_TRIGGERS` tuple has exactly five entries with no slot for it. Adding a sixth name would violate "No phase plan invents an interface this document does not name." Implemented instead at the place the prior art already puts it: SDD's status handling — "If the concerns are about correctness or scope, address them before review" — which is a pre-review block in P07's controller prose, not a ratchet. **If it is meant to be a ratchet trigger, the master plan's tuple needs a sixth name and this plan needs a revision.**

4. **Trigger (c) is "stage-10 root cause", not "stage-11 finding".** The spec's table says "a stage-10 root cause traced into a file inside this phase's write scopes", and the master plan names it `debug-locality`. The directing brief says "a stage-11 finding tracing back to a task in the phase". Implemented per the spec and master plan. The stage-11 variant, if intended, is a different trigger with a different evidence source and is not implemented.

5. **Trigger (b), `repeated-suite-failure`, is not in the brief's list** but is in the spec's table and the master plan's tuple. Implemented per the spec and master plan.

6. **Provisional propagation cannot cross phases.** The spec taints "any task whose dependency closure contains a decision adopted at `code-evidenced`", but `## Phases` carries no dependency edges and `## Tasks` carries no per-task decision references, so the closure is not computable from the tracker beyond the raising phase. `propagate_provisional` therefore taints the incomplete tasks of the phase in which the adoption was recorded, and nothing downstream. **A run whose P05 decision taints a P07 task will not mark that P07 task provisional.** Closing this needs either a `Depends On` column on `## Phases` or a `Decisions` column on `## Tasks`; both are P02 schema changes and this plan does not make them.

Three smaller additions, made rather than reported because the spec fully specifies the mechanism and only the name was missing: `ratchet_triggers_fired`, `close_fix_round`, `task_intensity`, `provisional_constraints_block` and `inherited_rung_cap` are P05 names not in the master plan's P05 block. Each is listed in `## Produces` marked **(P05)** so P06 consumes it deliberately. `ratchet_triggers_fired` additionally takes four parameters carrying facts the tracker does not hold — suite failures, root-cause paths, phase write scopes, and per-task changed lines — because computing a trigger from a fact the function was not given would be an estimate, and the ratchet is mechanical.

One verification-command correction, already applied throughout this plan: the coordinator's `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v` **does not execute in this repository**. `-t .` makes discovery import the start directory as a package relative to the repository root, and `pipeline-auto` contains a hyphen, so it fails with `ImportError: Start directory is not importable`. Verified on this machine under Python 3.11.2, both with and without an `__init__.py` in `tests/`. Every command in this plan therefore omits `-t`, matching P02's and P03's existing form. **The master plan's Tech Stack line carries the `-t .` form and should be corrected there too, for P01, P02, P03, P04, P06–P09.**

One documentation discrepancy, for whoever maintains the master plan: its **Self-review** section refers to `effective_tier` and `TIERS`, while its **P03 produces** block and P03's own plan use `effective_rung` and `RUNGS`. The interface block is authoritative and P05 consumes `RUNGS` / `RUNG_ORDER` / `effective_rung`.
