# P02 — Schema Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py` — the durable-state spine of `superb:pipeline-auto`: parse, render, semantically validate, lock, atomically replace and initialize a `pipeline-auto/v1` tracker — plus the two templates and the `sdd-workspace` script every later phase needs.

**Architecture:** One standard-library Python module. The markdown tracker is the only durable state; it parses into a plain `dict` of plain `str` cells, is checked by a set of per-section semantic validators, and renders back through a single canonical renderer so parse → render is byte-stable. Every mutation goes through `locked_tracker_update`, which takes an OS-level exclusive lock on a run-local lock file, re-reads and re-validates under the lock, applies the caller's `mutate`, renders, **re-parses its own render as a canary**, then writes a temp file *inside the run directory*, fsyncs it, `os.replace`s it over `progress.md`, and fsyncs the directory. The two durability points sit in two separate `try` blocks so a pre-replace failure is `TrackerWriteError` ("nothing happened") and a post-replace failure is `UpdateOutcomeUncertain` ("it may have applied").

**Tech Stack:** Python 3 standard library only — `os`, `re`, `copy`, `errno`, `time`, `hashlib`, `tempfile`, `pathlib`, `contextlib`, plus `fcntl`/`msvcrt` guarded by `try: import`. Tests are `unittest.TestCase`, so they run under both `python3 -m unittest discover` and `pytest`. Bash for `scripts/sdd-workspace`.

**Spec:** `docs/superpowers/specs/2026-09-14-pipeline-auto-design.md`

**Master plan:** `docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md`

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

---

## What this phase owns, and what it deliberately does not

P02 owns **the shape of durable state and the mechanics of changing it safely**. It does not own any policy that reads that state.

Owned: the eleven tracker sections and their exact column sets; structural parse and render; per-section semantic validation; the foreign-schema read-only stop; the lock; the atomic replace and its three outcomes; `locked_tracker_update`; `initialize_run`; `publish_immutable`; `derive_next_action`; `templates/progress.md`; `templates/decisions.md`; `scripts/sdd-workspace`.

Not owned, and left to later phases: qid derivation, rung recomputation and clustering, contradiction detection, budget and depth *enforcement* (P03); reserve/resume, scope overlap, range proofs, reconciliation (P04); adversarial trigger evaluation and the ratchet *decision* (P05); reviewer dispatch, challenge routing, completeness freeze (P06). P02 validates that the tracker **records** these coherently; it never decides them.

### Why there is no `## Remediation`

The spec drops it. Fix rounds in `superb:pipeline-auto` are scoped to a task, a phase, or a gate rather than only to a gate, and they carry the zero-open-findings outcome directly. `_sections` rejects any `## ` heading outside the known set, so a tracker carrying `## Remediation` fails validation instead of being silently ignored. Task 1 tests exactly that.

### Why `## Stage` is load-bearing and belongs here

Stages 01–07 produce artifacts — the reconciled intent brief, the four human answers, the design, the spec, the master plan, the phase plans — that Git cannot reconstruct and the task table does not mention. A compaction during stage 02 leaves a controller that, reading only `## Tasks`, concludes nothing has started and re-runs stage 01. Three fresh readers produce a *different* intent brief, the run silently forks from its own history, and no later step can detect it.

`## Stage` therefore carries all twelve rows at all times, with a monotone state sequence: zero or more `complete`, then at most one `active`, then zero or more `pending`. A tracker showing stage 01 `pending` while stage 02 is `active` is not a state this run can be in, and parsing it fails.

### Why the rung enum lives here and the rung *values* do not

The spec: "These five values are schema constants, not run configuration. Putting them in `## Run` as tunables would let an autonomous controller lower its own adoption bar." So `## Run` carries **no** `adoption_floor` and **no** rung values. P02 defines only `RUNG_NAMES`, the ordered enum, because the schema must reject an out-of-enum `Rung` cell — the spec calls that case "schema-invalid", which is this module's job. P03 builds its `RUNGS` value map over these exact names and owns `ADOPTION_FLOOR`.

### Why there is no budget counter field

Per-phase and per-run adoption counts are obtained by counting `## Quorum` rows whose `Outcome` is `adopted`, filtered by `Phase`. A stored counter would be a second source of truth for a fact already recorded row by row, and the two would drift — precisely the failure this schema exists to prevent. `agent_dispatch_count` **is** a stored `## Run` field, because dispatches are not all recorded as rows and the number is therefore not derivable.

---

## The schema, in full

Marker `<!-- pipeline-auto/v1 -->`, title `# Pipeline Auto — Progress Tracker`, then exactly these eleven sections in exactly this order.

**`## Run`** — a `| Field | Value |` table with exactly these keys, in this order:

`run_id`, `schema`, `base_commit`, `target_branch`, `worker_limit`, `agent_dispatch_count`, `spec`, `master_plan`, `phase_plans`, `decisions`, `findings`, `completeness_proposals`, `revision`, `last_transition`

| Section | Columns |
| --- | --- |
| `## Stage` | `Stage`, `Stage State`, `Next Action` |
| `## Intent` | `ID`, `Kind`, `State`, `Owner`, `Result`, `Conflicts` |
| `## Questions` | `ID`, `Origin`, `Slot`, `State`, `Decision` |
| `## Quorum` | `QID`, `Axis`, `Phase`, `State`, `Owners`, `Payload Digest`, `Context Digest`, `Responses`, `Depth`, `Rung`, `Outcome`, `Decision` |
| `## Escalations` | `ID`, `QID`, `Blast`, `State`, `Batch`, `Resolution` |
| `## Tasks` | `ID`, `Phase`, `Kind`, `State`, `Owner`, `Attempt`, `Result`, `Checkpoints`, `Source Ref`, `Commits`, `Artifacts`, `Integration`, `Verification`, `Question`, `Provisional` |
| `## Task Review` | `Task`, `Attempt`, `Reviewer`, `State`, `Spec Verdict`, `Quality Verdict`, `Verification`, `Findings`, `Adversarial` |
| `## Fix Rounds` | `Scope`, `Round`, `State`, `Fixer`, `Findings`, `Commits`, `Verification`, `Re-review`, `Remaining` |
| `## Phases` | `ID`, `State`, `Verification`, `Review Class`, `Class Source`, `Ratchet`, `Gate` |
| `## Gates` | `ID`, `Type`, `Phase`, `State`, `Base`, `Head`, `Assignments`, `Reports`, `Verification`, `Findings` |

Every cell is a non-empty string. Absence is the literal `-`. Lists are comma-separated. A column header becomes a dict key by lowercasing and replacing spaces and hyphens with underscores, so `Re-review` is `re_review` and `QID` is `qid`.

Every table may have **zero** data rows; only `## Stage` is fixed at twelve. This differs from `superb:pipeline`, which required at least one row — in `pipeline-auto` an empty `## Quorum` is the normal state of a healthy run.

---

## Verification suite for this phase

Ordered command tuple. All four must pass before P02 is complete.

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
python3 -c "import ast; ast.parse(open('plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py').read())"
git diff --name-only -- plugins/superb/skills/pipeline/
git status --short
```

The third command must print **nothing**. Any output means `skills/pipeline/` was modified and the phase fails. `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/ -v` is the master plan's form and collects the same `unittest.TestCase` classes wherever pytest is installed; `unittest discover` is the form that runs with the standard library alone, which this repository's constraint requires.

---

## Task 1: Structural parse and render, byte-stable

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Create: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`
- Create: `plugins/superb/skills/pipeline-auto/tests/fixtures/valid-progress.md`
- Create: `plugins/superb/skills/pipeline-auto/tests/fixtures/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `SCHEMA: str`, `MARKER: str`, `TITLE: str`, `RUNG_NAMES: tuple[str, ...]`, `TrackerError`, `ForeignSchemaError`, `TrackerValidationError`, `TrackerWriteError`, `UpdateOutcomeUncertain`, `PlanMetadataError`, `parse_tracker(text: str) -> dict`, `render_tracker(tracker: dict) -> str`, and the module-private `_SECTIONS`, `_RUN_KEYS`, `_csv`, `_field`.

**Named fault this task catches:** `render_tracker` omitting a column while `parse_tracker` still accepts the shorter header, silently losing a cell on every write. The fixture is external truth: it carries all fifteen task columns whether or not the module's header constant still does.

- [ ] **Step 1: Write the fixture**

Create `plugins/superb/skills/pipeline-auto/tests/fixtures/valid-progress.md` with exactly this content. It is the only valid tracker fixture; every later task reuses it.

```markdown
<!-- pipeline-auto/v1 -->
# Pipeline Auto — Progress Tracker

## Run
| Field | Value |
| --- | --- |
| run_id | 2026-09-14-pipeline-auto |
| schema | pipeline-auto/v1 |
| base_commit | c8bddd610119f52b54bf077d284c7f5d8362ae77 |
| target_branch | feat/pipeline-auto |
| worker_limit | 6 |
| agent_dispatch_count | 48 |
| spec | docs/superpowers/specs/2026-09-14-pipeline-auto-design.md |
| master_plan | docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md |
| phase_plans | docs/superpowers/plans/pipeline-auto/phase-01-pressure-baselines.md,docs/superpowers/plans/pipeline-auto/phase-02-schema-core.md |
| decisions | docs/superpowers/runs/2026-09-14-pipeline-auto/decisions.md |
| findings | docs/superpowers/runs/2026-09-14-pipeline-auto/findings.md |
| completeness_proposals | docs/superpowers/runs/2026-09-14-pipeline-auto/completeness-proposals.md |
| revision | 12 |
| last_transition | ratchet-P02-accumulated-surface |

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
| 09 | active | run-task-gate-P02-T01 |
| 10 | pending | - |
| 11 | pending | - |
| 12 | pending | - |

## Intent
| ID | Kind | State | Owner | Result | Conflicts |
| --- | --- | --- | --- | --- | --- |
| reader-1 | reader | published | intent-reader-1 | scratch/intent-reader-1.md | - |
| reader-2 | reader | published | intent-reader-2 | scratch/intent-reader-2.md | - |
| reader-3 | reader | published | intent-reader-3 | scratch/intent-reader-3.md | - |
| brief | brief | frozen | reconciled | scratch/intent-brief.md | C-001 |

## Questions
| ID | Origin | Slot | State | Decision |
| --- | --- | --- | --- | --- |
| axis-1 | intent-conflict | 1 | answered | H-1 |
| axis-2 | synthesis | 2 | answered | H-2 |

## Quorum
| QID | Axis | Phase | State | Owners | Payload Digest | Context Digest | Responses | Depth | Rung | Outcome | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3f2a1b0c9d8e | axis-1 | P02 | finalized | brain-1,brain-2,brain-3 | 4f1c0a2b3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8 | a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90 | scratch/q1-brain-1.json,scratch/q1-brain-2.json,scratch/q1-brain-3.json | 1 | specified | adopted | Q-3f2a1b0c9d8e |
| 7c6b5a4938d2 | new | P02 | in_flight | brain-4,brain-5,brain-6 | b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1 | a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90 | scratch/q2-brain-4.json | - | - | - | - |

## Escalations
| ID | QID | Blast | State | Batch | Resolution |
| --- | --- | --- | --- | --- | --- |
| E-1 | 7c6b5a4938d2 | phase | queued | - | - |
| E-2 | - | run | answered | batch-1 | H-3 |

## Tasks
| ID | Phase | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question | Provisional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01-T01 | P01 | source | [x] | impl-1 | attempt-001 | scratch/p01-t01-result.md | red,green | refs/heads/feat/pipeline-auto | 0123456789abcdef0123456789abcdef01234567 | - | fedcba9876543210fedcba9876543210fedcba98 | scratch/p01-t01-tests.txt | - | no |
| P01-T02 | P01 | source | [x] | impl-4 | attempt-001 | scratch/p01-t02-result.md | red,green | refs/heads/feat/pipeline-auto | 2222222222222222222222222222222222222222 | - | held | scratch/p01-t02-tests.txt | - | yes |
| P02-T01 | P02 | artifact | [~] | impl-2 | attempt-002 | - | red | - | - | - | - | - | - | yes |
| P02-T02 | P02 | source | [?] | impl-3 | attempt-001 | - | blocked:attempt-001@scratch/p02-t02-question.md | - | - | - | - | - | scratch/p02-t02-question.md | no |

## Task Review
| Task | Attempt | Reviewer | State | Spec Verdict | Quality Verdict | Verification | Findings | Adversarial |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01-T01 | attempt-001 | reviewer-1 | accepted | pass | pass | scratch/p01-t01-rerun.txt | none | large-surface |
| P02-T01 | attempt-002 | reviewer-2 | blocked | fail | pass | scratch/p02-t01-rerun.txt | F-001,F-002 | - |

## Fix Rounds
| Scope | Round | State | Fixer | Findings | Commits | Verification | Re-review | Remaining |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01-T01 | 1 | complete | fixer-0 | F-003 | abcdef0123456789abcdef0123456789abcdef01 | scratch/p01-t01-r1-tests.txt | scratch/p01-t01-r1-review.md | none |
| P02-T01 | 1 | fixing | fixer-1 | F-001,F-002 | - | - | - | - |

## Phases
| ID | State | Verification | Review Class | Class Source | Ratchet | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| P01 | [x] | scratch/p01-verification.txt | required | plan | - | gate-p01 |
| P02 | [~] | - | required | ratchet | accumulated-surface@scratch/p02-ratchet.md | gate-p02 |

## Gates
| ID | Type | Phase | State | Base | Head | Assignments | Reports | Verification | Findings |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gate-p01 | phase | P01 | accepted | c8bddd610119f52b54bf077d284c7f5d8362ae77 | fedcba9876543210fedcba9876543210fedcba98 | spec,quality | scratch/gate-p01-review.md | scratch/gate-p01-tests.txt | findings.md |
| gate-p02 | phase | P02 | in_progress | c8bddd610119f52b54bf077d284c7f5d8362ae77 | 1111111111111111111111111111111111111111 | spec,quality | - | - | findings.md |
| gate-master | master | - | pending | - | - | - | - | - | findings.md |
```

Create `plugins/superb/skills/pipeline-auto/tests/fixtures/README.md`:

```markdown
# pipeline-auto/v1 state fixtures

`valid-progress.md` is the single fully-populated valid tracker. It is external
truth, not a convenience: it carries every column of every section, so a change
to a header constant in `pipeline_auto_state.py` that drops a column fails the
byte round-trip instead of silently losing a cell on every future write. Edit it
only when the schema genuinely changes, and change the module in the same commit.

Invalid input is built by surgery on these bytes inside the test that needs it,
so each rejection test states exactly which byte made it invalid.

Rejection tests compare the file's bytes before and after the attempted parse or
transition. An invalid or foreign tracker must be byte-identical afterwards: a
read-only stop that rewrites the file into a guessed state is not a stop.

`plugins/superb/skills/pipeline/tests/fixtures/valid-v2-progress.md` and
`legacy-v1-progress.md` are read by the foreign-schema tests and are never
copied here and never modified. They belong to `superb:pipeline`, which this
skill does not interoperate with and never migrates from.
```

- [ ] **Step 2: Write the failing test**

Create `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`:

```python
"""Contract tests for the pipeline-auto/v1 state spine."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[3]
FIXTURES = SKILL_DIR / "tests" / "fixtures"
FOREIGN_FIXTURES = (
    REPO_ROOT / "plugins" / "superb" / "skills" / "pipeline" / "tests" / "fixtures"
)

sys.path.insert(0, str(SKILL_DIR / "scripts"))

import pipeline_auto_state as pas  # noqa: E402


def valid_text() -> str:
    return (FIXTURES / "valid-progress.md").read_text(encoding="utf-8")


class SchemaIdentityTests(unittest.TestCase):
    def test_schema_and_marker_are_the_exact_agreed_strings(self):
        self.assertEqual(pas.SCHEMA, "pipeline-auto/v1")
        self.assertEqual(pas.MARKER, "<!-- pipeline-auto/v1 -->")
        self.assertEqual(pas.TITLE, "# Pipeline Auto — Progress Tracker")

    def test_every_tracker_error_shares_one_root(self):
        for error in (pas.ForeignSchemaError, pas.TrackerValidationError,
                      pas.TrackerWriteError, pas.UpdateOutcomeUncertain,
                      pas.PlanMetadataError):
            self.assertTrue(issubclass(error, pas.TrackerError), error.__name__)

    def test_the_rung_enum_is_the_five_spec_names_lowest_first(self):
        self.assertEqual(
            pas.RUNG_NAMES,
            ("speculation", "engineering-judgement", "convention-cited",
             "code-evidenced", "specified"),
        )

    def test_no_run_field_carries_a_rung_value_or_an_adoption_floor(self):
        """Rungs are schema constants. A tunable floor in ## Run would let an
        autonomous controller lower its own adoption bar."""
        self.assertNotIn("adoption_floor", pas._RUN_KEYS)
        for key in pas._RUN_KEYS:
            self.assertNotIn(key, pas.RUNG_NAMES)


class RoundTripTests(unittest.TestCase):
    def test_render_of_a_parse_is_byte_identical_to_the_fixture(self):
        """Catches a renderer that drops a column the parser still tolerates.

        The fixture, not the module, holds the full column set. If a header
        constant loses a column, either the parse rejects the wider fixture or
        the render emits a narrower table; both fail this assertion.
        """
        text = valid_text()
        self.assertEqual(pas.render_tracker(pas.parse_tracker(text)), text)

    def test_the_parse_exposes_every_section_the_schema_names(self):
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual(
            sorted(tracker),
            sorted(["run", "stages", "intent", "questions", "quorum", "escalations",
                    "tasks", "task_review", "fix_rounds", "phases", "gates"]),
        )
        self.assertEqual(len(tracker["stages"]), 12)
        self.assertEqual(len(tracker["tasks"][0]), 15)
        self.assertEqual(tracker["tasks"][0]["provisional"], "no")
        self.assertEqual(tracker["fix_rounds"][0]["re_review"],
                         "scratch/p01-t01-r1-review.md")
        self.assertEqual(tracker["quorum"][0]["qid"], "3f2a1b0c9d8e")
        self.assertEqual(tracker["quorum"][0]["rung"], "specified")

    def test_a_remediation_section_is_rejected_rather_than_ignored(self):
        text = valid_text() + "\n## Remediation\n| Gate | Round |\n| --- | --- |\n"
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_reordered_or_renamed_sections_are_rejected(self):
        text = valid_text().replace("## Questions", "## ZZQuestions")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_renamed_run_field_is_rejected(self):
        text = valid_text().replace("| worker_limit |", "| workers |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_empty_cell_is_rejected_because_absence_is_spelled_dash(self):
        text = valid_text().replace("| E-1 | 7c6b5a4938d2 |", "| E-1 |  |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_missing_terminal_newline_is_rejected(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(valid_text().rstrip("\n"))

    def test_a_table_with_no_data_rows_parses_to_an_empty_list(self):
        text = valid_text()
        for row in ("| E-1 | 7c6b5a4938d2 | phase | queued | - | - |\n",
                    "| E-2 | - | run | answered | batch-1 | H-3 |\n"):
            text = text.replace(row, "")
        tracker = pas.parse_tracker(text)
        self.assertEqual(tracker["escalations"], [])
        self.assertEqual(pas.render_tracker(tracker), text)

    def test_render_rejects_a_row_missing_a_field(self):
        tracker = pas.parse_tracker(valid_text())
        del tracker["tasks"][0]["provisional"]
        with self.assertRaises(pas.TrackerValidationError):
            pas.render_tracker(tracker)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline_auto_state'`

- [ ] **Step 4: Write the implementation**

Create `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`:

```python
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
_TASK_HEADER = (
    "ID", "Phase", "Kind", "State", "Owner", "Attempt", "Result", "Checkpoints",
    "Source Ref", "Commits", "Artifacts", "Integration", "Verification",
    "Question", "Provisional",
)
_TASK_REVIEW_HEADER = (
    "Task", "Attempt", "Reviewer", "State", "Spec Verdict", "Quality Verdict",
    "Verification", "Findings", "Adversarial",
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 13 tests

- [ ] **Step 6: Confirm `skills/pipeline/` is untouched, then commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/fixtures/valid-progress.md \
        plugins/superb/skills/pipeline-auto/tests/fixtures/README.md
git commit -m "feat(pipeline-auto): byte-stable pipeline-auto/v1 parse and render"
```

The first command must print nothing before you stage anything.

---

## Task 2: `validate_run` and the foreign-schema read-only stop

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py` (append)
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py` (append)

**Interfaces:**
- Consumes: `parse_tracker`, `ForeignSchemaError`, `TrackerValidationError`, `MARKER`, `SCHEMA`.
- Produces: `validate_run(run_dir: str) -> dict`, and the test helper `make_run(case, text=None) -> Path` that every later task reuses.

**Named fault this task catches:** deleting the marker check in `validate_run`, so a `pipeline-run/v2` tracker is accepted and then mutated by a later transition. The test feeds the *existing* `superb:pipeline` fixture bytes and asserts both the exception and that the file is byte-identical afterwards.

- [ ] **Step 1: Write the failing test**

Append to the test file, above the `if __name__` block:

```python
import shutil
import tempfile


def make_run(case: unittest.TestCase, text: str | None = None) -> Path:
    """A temp run directory holding one progress.md. Removed when the case ends."""
    run_dir = Path(tempfile.mkdtemp(prefix="pipeline-auto-"))
    case.addCleanup(shutil.rmtree, run_dir, ignore_errors=True)
    (run_dir / "progress.md").write_text(
        valid_text() if text is None else text, encoding="utf-8"
    )
    return run_dir


class ForeignSchemaStopTests(unittest.TestCase):
    def test_a_pipeline_run_v2_tracker_is_rejected_and_left_byte_identical(self):
        """The marker check is the only thing between this module and a tracker
        belonging to another skill. Delete it and a v2 run is parsed, then
        rewritten into pipeline-auto shape by the first transition."""
        foreign = (FOREIGN_FIXTURES / "valid-v2-progress.md").read_bytes()
        run_dir = make_run(self, foreign.decode("utf-8"))
        progress = run_dir / "progress.md"
        with self.assertRaises(pas.ForeignSchemaError) as caught:
            pas.validate_run(run_dir)
        self.assertEqual(progress.read_bytes(), foreign)
        self.assertIn("superb:pipeline", str(caught.exception))
        self.assertIn("no files were changed", str(caught.exception))

    def test_a_legacy_v1_tracker_is_rejected_and_left_byte_identical(self):
        legacy = (FOREIGN_FIXTURES / "legacy-v1-progress.md").read_bytes()
        run_dir = make_run(self, legacy.decode("utf-8"))
        with self.assertRaises(pas.ForeignSchemaError):
            pas.validate_run(run_dir)
        self.assertEqual((run_dir / "progress.md").read_bytes(), legacy)

    def test_an_unknown_marker_is_rejected(self):
        run_dir = make_run(self, "<!-- pipeline-auto/v9 -->\n# Whatever\n")
        with self.assertRaises(pas.ForeignSchemaError):
            pas.validate_run(run_dir)

    def test_a_missing_progress_file_is_a_read_only_stop(self):
        run_dir = Path(tempfile.mkdtemp(prefix="pipeline-auto-"))
        self.addCleanup(shutil.rmtree, run_dir, ignore_errors=True)
        with self.assertRaises(pas.ForeignSchemaError):
            pas.validate_run(run_dir)
        self.assertEqual(list(run_dir.iterdir()), [])

    def test_a_malformed_but_correctly_marked_tracker_raises_validation_not_foreign(self):
        broken = valid_text().replace("| worker_limit | 6 |", "| worker_limit | 6 | 6 |")
        run_dir = make_run(self, broken)
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.validate_run(run_dir)
        self.assertNotIsInstance(caught.exception, pas.ForeignSchemaError)
        self.assertEqual((run_dir / "progress.md").read_text(encoding="utf-8"), broken)

    def test_a_valid_run_returns_its_tracker(self):
        tracker = pas.validate_run(make_run(self))
        self.assertEqual(tracker["run"]["schema"], pas.SCHEMA)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ForeignSchemaStop`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'validate_run'`

- [ ] **Step 3: Write the implementation**

Add `from pathlib import Path` to the module's imports, then append:

```python
def _diagnostic(run_dir: Path, detail: str) -> str:
    return (
        f"{run_dir}: {detail}; no files were changed. "
        f"superb:pipeline-auto reads only {SCHEMA}. It does not interoperate with "
        "superb:pipeline (pipeline-run/v1, pipeline-run/v2) and there is no "
        "migration in either direction."
    )


def validate_run(run_dir: str) -> dict:
    """Read and validate a run without mutating anything on disk.

    Every rejection path leaves the directory exactly as it was found. That is
    the whole contract: a foreign, missing or malformed tracker stops the run
    rather than being repaired into a guess.
    """
    run_dir = Path(run_dir)
    progress = run_dir / "progress.md"
    if not progress.is_file():
        raise ForeignSchemaError(_diagnostic(run_dir, "missing progress.md"))
    try:
        text = progress.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ForeignSchemaError(
            _diagnostic(run_dir, f"unreadable progress.md ({exc})")
        ) from exc
    lines = text.splitlines()
    first = lines[0] if lines else ""
    if first != MARKER:
        raise ForeignSchemaError(
            _diagnostic(run_dir, f"schema marker is {first!r}, not {MARKER!r}")
        )
    try:
        return parse_tracker(text)
    except TrackerValidationError as exc:
        raise TrackerValidationError(
            _diagnostic(run_dir, f"malformed {SCHEMA} tracker ({exc})")
        ) from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 19 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): read-only stop on foreign, missing, or malformed trackers"
```

---

## Task 3: `## Stage` semantics and `derive_next_action`

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `parse_tracker`, `TrackerValidationError`.
- Produces: `STAGES: tuple[str, ...]` (`"01".."12"`), `derive_next_action(tracker: dict) -> str`, and the module-private `_validate_tracker_semantics(tracker) -> None` dispatcher that Tasks 4–7 extend.

**Why this task exists:** a compaction during stage 02 that silently re-runs stage 01 is both unrecoverable and undetectable. `## Stage` is the only section whose absence has that property.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
def with_stages(states: list[str], actions: list[str] | None = None) -> str:
    """The valid fixture with its twelve stage rows replaced wholesale."""
    actions = actions if actions is not None else ["-"] * len(states)
    lines = valid_text().splitlines(keepends=True)
    start = next(index for index, line in enumerate(lines)
                 if line.startswith("| 01 | "))
    rows = [f"| {stage} | {state} | {action} |\n"
            for stage, state, action in zip(pas.STAGES, states, actions)]
    return "".join(lines[:start] + rows + lines[start + 12:])


class StageSectionTests(unittest.TestCase):
    def test_the_fixture_is_stages_01_through_12_in_order(self):
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual(pas.STAGES, tuple(f"{n:02d}" for n in range(1, 13)))
        self.assertEqual(tuple(row["stage"] for row in tracker["stages"]), pas.STAGES)

    def test_a_pending_stage_before_an_active_one_is_rejected(self):
        """The compaction fault: stage 02 is running, stage 01 reads unstarted,
        and a resuming controller re-dispatches the three intent readers,
        producing a different brief and forking the run from its own history."""
        states = ["pending", "active"] + ["pending"] * 10
        actions = ["-", "synthesise-questions"] + ["-"] * 10
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))

    def test_a_pending_stage_before_a_complete_one_is_rejected(self):
        states = ["pending", "complete", "active"] + ["pending"] * 9
        actions = ["-", "-", "run-brainstorming"] + ["-"] * 9
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))

    def test_two_active_stages_are_rejected(self):
        states = ["active", "active"] + ["pending"] * 10
        actions = ["read-intent", "synthesise-questions"] + ["-"] * 10
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))

    def test_a_missing_stage_row_is_rejected(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(valid_text().replace("| 12 | pending | - |\n", ""))

    def test_a_duplicated_stage_row_is_rejected(self):
        text = valid_text().replace("| 11 | pending | - |\n",
                                    "| 10 | pending | - |\n")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_the_active_stage_must_name_its_next_action(self):
        states = ["complete"] * 8 + ["active"] + ["pending"] * 3
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states))

    def test_a_pending_stage_cannot_carry_a_next_action(self):
        states = ["complete"] * 8 + ["active"] + ["pending"] * 3
        actions = ["-"] * 8 + ["run-task-gate-P02-T01", "debug-later"] + ["-", "-"]
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))

    def test_an_unknown_stage_state_is_rejected(self):
        states = ["complete"] * 8 + ["paused"] + ["pending"] * 3
        actions = ["-"] * 8 + ["run-task-gate-P02-T01"] + ["-"] * 3
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))


class NextActionTests(unittest.TestCase):
    def test_a_queued_escalation_outranks_the_active_stage(self):
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual(pas.derive_next_action(tracker), "await-escalation-batch")

    def test_without_a_pending_escalation_the_active_stage_supplies_the_action(self):
        tracker = pas.parse_tracker(valid_text())
        tracker["escalations"] = [row for row in tracker["escalations"]
                                  if row["state"] == "answered"]
        self.assertEqual(pas.derive_next_action(tracker), "run-task-gate-P02-T01")

    def test_a_run_whose_stages_are_all_complete_is_complete(self):
        tracker = pas.parse_tracker(with_stages(["complete"] * 12))
        tracker["escalations"] = []
        self.assertEqual(pas.derive_next_action(tracker), "complete")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k "Stage or NextAction"`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'STAGES'`

- [ ] **Step 3: Write the implementation**

Append to `pipeline_auto_state.py`, then add `_validate_tracker_semantics(tracker)` as the last statement of `parse_tracker` before `return tracker`:

```python
STAGES = tuple(f"{index:02d}" for index in range(1, 13))
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
        raise TrackerValidationError("## Stage must list stages 01..12 exactly once, in order")
    states = [row["stage_state"] for row in stages]
    unknown = [state for state in states if state not in _STAGE_STATES]
    if unknown:
        raise TrackerValidationError(f"unknown stage state {unknown[0]!r}")
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
    _validate_stages(tracker)


def derive_next_action(tracker: dict) -> str:
    """The single next action, derived from files rather than remembered.

    A pending escalation outranks the stage: the spec requires ``next_action``
    to read ``await-escalation-batch`` rather than any generic block, so a
    resuming controller and the terminal report both see why the run is waiting.
    """
    if any(row["state"] in ("queued", "asked") for row in tracker["escalations"]):
        return "await-escalation-batch"
    for row in tracker["stages"]:
        if row["stage_state"] == "active":
            return row["next_action"]
    return "complete"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 31 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): make stages 01-12 recoverable across compaction"
```

---

## Task 4: `## Intent`, `## Questions` and `## Escalations` semantics

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `_validate_tracker_semantics`, `TrackerValidationError`, `_csv`.
- Produces: module-private `_validate_intent`, `_validate_questions`, `_validate_escalations`, all three wired into `_validate_tracker_semantics`.

**Rules from the spec these encode:** exactly three stage-01 readers, never fewer to fit capacity; the reconciled brief is immutable after stage 03; unresolved intent conflicts take stage-03 question slots *ahead of* any synthesised question; stage 03 asks at most four questions in one call; escalations batch at most four per `AskUserQuestion` call.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
class IntentSectionTests(unittest.TestCase):
    def test_the_fixture_carries_three_readers_and_one_brief(self):
        tracker = pas.parse_tracker(valid_text())
        self.assertEqual([row["id"] for row in tracker["intent"]],
                         ["reader-1", "reader-2", "reader-3", "brief"])

    def test_two_readers_are_rejected_because_a_count_is_never_reduced(self):
        text = valid_text().replace(
            "| reader-3 | reader | published | intent-reader-3 | scratch/intent-reader-3.md | - |\n",
            "",
        )
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_brief_cannot_publish_before_all_three_readers_have(self):
        text = valid_text().replace(
            "| reader-2 | reader | published | intent-reader-2 | scratch/intent-reader-2.md | - |",
            "| reader-2 | reader | dispatched | intent-reader-2 | - | - |",
        )
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_brief_cannot_freeze_before_stage_03_closes(self):
        states = ["complete", "active"] + ["pending"] * 10
        actions = ["-", "synthesise-questions"] + ["-"] * 10
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(with_stages(states, actions))

    def test_a_published_reader_must_name_its_immutable_result(self):
        text = valid_text().replace(
            "| reader-1 | reader | published | intent-reader-1 | scratch/intent-reader-1.md | - |",
            "| reader-1 | reader | published | intent-reader-1 | - | - |",
        )
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_conflicts_belong_to_the_brief_not_to_a_reader(self):
        text = valid_text().replace(
            "| reader-1 | reader | published | intent-reader-1 | scratch/intent-reader-1.md | - |",
            "| reader-1 | reader | published | intent-reader-1 | scratch/intent-reader-1.md | C-002 |",
        )
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)


class QuestionSectionTests(unittest.TestCase):
    def test_five_questions_are_rejected(self):
        extra = "".join(
            f"| axis-{n} | synthesis | {n} | asked | - |\n" for n in range(3, 6)
        )
        text = valid_text().replace("\n## Quorum", "\n" + extra + "\n## Quorum")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_synthesised_question_cannot_take_a_slot_above_an_intent_conflict(self):
        """An unresolved intent conflict is by definition higher blast radius
        than anything stage 02 synthesised, so it takes the earlier slot."""
        text = valid_text().replace(
            "| axis-1 | intent-conflict | 1 | answered | H-1 |\n"
            "| axis-2 | synthesis | 2 | answered | H-2 |",
            "| axis-1 | synthesis | 1 | answered | H-1 |\n"
            "| axis-2 | intent-conflict | 2 | answered | H-2 |",
        )
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_slots_must_be_one_through_n_in_order(self):
        text = valid_text().replace("| axis-2 | synthesis | 2 |",
                                    "| axis-2 | synthesis | 4 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_answered_question_records_a_human_decision_id(self):
        text = valid_text().replace("| axis-1 | intent-conflict | 1 | answered | H-1 |",
                                    "| axis-1 | intent-conflict | 1 | answered | Q-3f2a1b0c9d8e |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unanswered_question_cannot_carry_a_decision(self):
        text = valid_text().replace("| axis-2 | synthesis | 2 | answered | H-2 |",
                                    "| axis-2 | synthesis | 2 | asked | H-2 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)


class EscalationSectionTests(unittest.TestCase):
    def test_a_batch_asks_at_most_four(self):
        extra = "".join(
            f"| E-{n} | - | run | asked | batch-1 | - |\n" for n in range(3, 7)
        )
        text = valid_text().replace(
            "| E-2 | - | run | answered | batch-1 | H-3 |\n",
            "| E-2 | - | run | answered | batch-1 | H-3 |\n" + extra,
        )
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_queued_escalation_has_not_been_batched(self):
        text = valid_text().replace("| E-1 | 7c6b5a4938d2 | phase | queued | - | - |",
                                    "| E-1 | 7c6b5a4938d2 | phase | queued | batch-1 | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_answered_escalation_records_its_human_resolution(self):
        text = valid_text().replace("| E-2 | - | run | answered | batch-1 | H-3 |",
                                    "| E-2 | - | run | answered | batch-1 | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_escalation_cannot_point_at_an_unknown_quorum(self):
        text = valid_text().replace("| E-1 | 7c6b5a4938d2 |", "| E-1 | 000000000000 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k "Intent or Question or Escalation"`
Expected: FAIL — the rejection cases parse successfully, so `assertRaises` reports `TrackerValidationError not raised`

- [ ] **Step 3: Write the implementation**

Append, and add all three calls to `_validate_tracker_semantics`:

```python
_INTENT_IDS = ("reader-1", "reader-2", "reader-3", "brief")
_INTENT_STATES = ("pending", "dispatched", "published", "frozen")
_QUESTION_ORIGINS = ("intent-conflict", "synthesis")
_QUESTION_STATES = ("proposed", "asked", "answered")
_ESCALATION_STATES = ("queued", "asked", "answered", "halted")
_HUMAN_DECISION = re.compile(r"H-[0-9]+")
_QUORUM_DECISION = re.compile(r"Q-[0-9a-f]{12}")
_QID = re.compile(r"[0-9a-f]{12}")
_ESCALATION_ID = re.compile(r"E-[0-9]+")
_MAX_QUESTIONS = 4
_MAX_BATCH = 4


def _stage_state(tracker: dict, stage: str) -> str:
    return next(row["stage_state"] for row in tracker["stages"] if row["stage"] == stage)


def _validate_intent(tracker: dict) -> None:
    """Three readers, one reconciled brief, and a brief that freezes after 03."""
    rows = tracker["intent"]
    if not rows:
        return
    if tuple(row["id"] for row in rows) != _INTENT_IDS:
        raise TrackerValidationError(
            "## Intent carries exactly three readers then one brief; a count is "
            "never reduced to fit capacity"
        )
    readers, brief = rows[:3], rows[3]
    if any(row["kind"] != "reader" for row in readers) or brief["kind"] != "brief":
        raise TrackerValidationError("intent row kind does not match its identity")
    if any(row["state"] not in _INTENT_STATES for row in rows):
        raise TrackerValidationError("unknown intent state")
    if any(row["state"] == "frozen" for row in readers):
        raise TrackerValidationError("only the reconciled brief freezes")
    for row in readers:
        if (row["state"] == "published") != (row["result"] != "-"):
            raise TrackerValidationError(
                "a reader publishes with its immutable result, or neither"
            )
        if row["conflicts"] != "-":
            raise TrackerValidationError(
                "conflicts are flagged on the reconciled brief, never on a reader"
            )
    if brief["state"] in ("published", "frozen"):
        if any(row["state"] != "published" for row in readers):
            raise TrackerValidationError(
                "the intent brief cannot publish before all three readers have"
            )
        if brief["result"] == "-":
            raise TrackerValidationError("a published intent brief names its result")
    elif brief["result"] != "-":
        raise TrackerValidationError("an unpublished brief cannot claim a result")
    if brief["state"] == "frozen" and _stage_state(tracker, "03") != "complete":
        raise TrackerValidationError(
            "the intent brief freezes only once stage 03 closes"
        )


def _validate_questions(tracker: dict) -> None:
    """At most four stage-03 questions; intent conflicts take the earlier slots."""
    rows = tracker["questions"]
    if len(rows) > _MAX_QUESTIONS:
        raise TrackerValidationError("stage 03 asks at most four questions in one call")
    if len({row["id"] for row in rows}) != len(rows):
        raise TrackerValidationError("duplicate question axis id")
    if [row["slot"] for row in rows] != [str(n) for n in range(1, len(rows) + 1)]:
        raise TrackerValidationError("question slots must be 1..n, in order")
    origins = [row["origin"] for row in rows]
    if any(origin not in _QUESTION_ORIGINS for origin in origins):
        raise TrackerValidationError("unknown question origin")
    if origins != sorted(origins, key=_QUESTION_ORIGINS.index):
        raise TrackerValidationError(
            "an unresolved intent conflict outranks any synthesised question and "
            "takes the earlier slot"
        )
    for row in rows:
        if row["state"] not in _QUESTION_STATES:
            raise TrackerValidationError("unknown question state")
        if row["state"] == "answered":
            if not _HUMAN_DECISION.fullmatch(row["decision"]):
                raise TrackerValidationError(
                    "an answered stage-03 question records an H-<n> decision; "
                    "a quorum can never answer the one human gate"
                )
        elif row["decision"] != "-":
            raise TrackerValidationError("only an answered question carries a decision")


def _validate_escalations(tracker: dict) -> None:
    rows = tracker["escalations"]
    qids = {row["qid"] for row in tracker["quorum"]}
    if len({row["id"] for row in rows}) != len(rows):
        raise TrackerValidationError("duplicate escalation id")
    batches: dict[str, int] = {}
    for row in rows:
        if not _ESCALATION_ID.fullmatch(row["id"]):
            raise TrackerValidationError("escalation ids are E-<n>")
        if row["qid"] != "-" and row["qid"] not in qids:
            raise TrackerValidationError("escalation refers to an unknown qid")
        if not _TOKEN.fullmatch(row["blast"]):
            raise TrackerValidationError("escalation blast radius must be a token")
        if row["state"] not in _ESCALATION_STATES:
            raise TrackerValidationError("unknown escalation state")
        if row["state"] == "queued" and row["batch"] != "-":
            raise TrackerValidationError("a queued escalation has not been batched yet")
        if row["state"] in ("asked", "answered") and row["batch"] == "-":
            raise TrackerValidationError("an asked escalation names its batch")
        if row["state"] == "answered":
            if not _HUMAN_DECISION.fullmatch(row["resolution"]):
                raise TrackerValidationError(
                    "an answered escalation records an H-<n> resolution"
                )
        elif row["resolution"] != "-":
            raise TrackerValidationError("only an answered escalation carries a resolution")
        if row["batch"] != "-":
            batches[row["batch"]] = batches.get(row["batch"], 0) + 1
    if any(count > _MAX_BATCH for count in batches.values()):
        raise TrackerValidationError(
            "an escalation batch asks at most four questions per AskUserQuestion call"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 46 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): validate intent, stage-03 questions, and escalation batches"
```

---

## Task 5: `## Quorum` semantics and the rung enum

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `RUNG_NAMES`, `_validate_tracker_semantics`, `_csv`, `_SHA256`, `_QID`, `_QUORUM_DECISION`.
- Produces: module-private `_validate_quorum`, wired into `_validate_tracker_semantics`.

**Rules from the spec these encode:** the three-phase record (`in_flight` carries three owner ids and the payload digest *before* dispatch; a `finalized` record carries the computed result); exactly three distinct brains, never fewer; a rung outside the enum is schema-invalid, never defaulted; an adopted row names its `Q-<hash>` decision and the winning rung; every axis is a stage-03 question id or the literal `new`.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
ADOPTED_ROW = (
    "| 3f2a1b0c9d8e | axis-1 | P02 | finalized | brain-1,brain-2,brain-3 | "
    "4f1c0a2b3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8 | "
    "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90 | "
    "scratch/q1-brain-1.json,scratch/q1-brain-2.json,scratch/q1-brain-3.json | "
    "1 | specified | adopted | Q-3f2a1b0c9d8e |"
)


def replace_adopted(new_row: str) -> str:
    return valid_text().replace(ADOPTED_ROW, new_row)


class QuorumSectionTests(unittest.TestCase):
    def test_a_rung_outside_the_enum_is_schema_invalid(self):
        """The spec forbids defaulting an out-of-enum rung to a legal value.
        Accepting 'high' here would let a malformed brain force an adoption."""
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(replace_adopted(ADOPTED_ROW.replace("| specified |", "| high |")))

    def test_two_brains_are_rejected_because_a_count_is_never_reduced(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(replace_adopted(
                ADOPTED_ROW.replace("brain-1,brain-2,brain-3", "brain-1,brain-2")))

    def test_three_owner_slots_must_be_three_distinct_brains(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(replace_adopted(
                ADOPTED_ROW.replace("brain-1,brain-2,brain-3", "brain-1,brain-1,brain-3")))

    def test_an_in_flight_quorum_cannot_carry_a_computed_result(self):
        """The three-phase record exists so an interruption is classifiable. A
        row that is both in flight and decided is not classifiable."""
        text = valid_text().replace(
            "| 7c6b5a4938d2 | new | P02 | in_flight |",
            "| 7c6b5a4938d2 | new | P02 | in_flight |").replace(
            "scratch/q2-brain-4.json | - | - | - | - |",
            "scratch/q2-brain-4.json | 1 | specified | adopted | Q-7c6b5a4938d2 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_in_flight_quorum_must_already_carry_its_payload_digest(self):
        text = valid_text().replace(
            "| b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1 |",
            "| - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_adoption_requires_all_three_responses_on_disk(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(replace_adopted(ADOPTED_ROW.replace(
                "scratch/q1-brain-1.json,scratch/q1-brain-2.json,scratch/q1-brain-3.json",
                "scratch/q1-brain-1.json,scratch/q1-brain-2.json")))

    def test_an_adopted_quorum_records_a_quorum_decision_id(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(replace_adopted(
                ADOPTED_ROW.replace("| Q-3f2a1b0c9d8e |", "| H-9 |")))

    def test_an_escalated_quorum_cannot_carry_a_decision(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(replace_adopted(
                ADOPTED_ROW.replace("| adopted | Q-3f2a1b0c9d8e |",
                                    "| escalated | Q-3f2a1b0c9d8e |")))

    def test_an_axis_must_be_a_stage_03_question_or_the_literal_new(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(replace_adopted(
                ADOPTED_ROW.replace("| axis-1 |", "| axis-9 |")))

    def test_a_duplicate_qid_is_rejected_because_one_adopted_answer_per_qid(self):
        text = valid_text().replace(ADOPTED_ROW, ADOPTED_ROW + "\n" + ADOPTED_ROW)
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unknown_outcome_word_is_rejected(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(replace_adopted(
                ADOPTED_ROW.replace("| adopted |", "| approved |")))

    def test_a_rejection_outcome_is_accepted_without_p02_enumerating_the_reasons(self):
        tracker = pas.parse_tracker(replace_adopted(ADOPTED_ROW.replace(
            "| 1 | specified | adopted | Q-3f2a1b0c9d8e |",
            "| - | - | rejected-contradicts-human | - |")))
        self.assertEqual(tracker["quorum"][0]["outcome"], "rejected-contradicts-human")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Quorum`
Expected: FAIL — `TrackerValidationError not raised`

- [ ] **Step 3: Write the implementation**

Append, and add `_validate_quorum(tracker)` to `_validate_tracker_semantics`:

```python
_QUORUM_STATES = ("in_flight", "finalized")
#: ``adopted``, ``escalated``, or a ``rejected-*`` reason. P02 does not close the
#: rejection vocabulary: naming the reasons is P03's contract, and an enum here
#: would have to be edited in two places every time one is added.
_QUORUM_OUTCOME = re.compile(r"adopted|escalated|rejected-[a-z][a-z-]*")


def _validate_quorum(tracker: dict) -> None:
    """The three-phase quorum record, structurally.

    P02 checks that a row is a possible state of the protocol. Whether the
    adoption was *correct* — floor, strictness, contradiction, depth, budget —
    is P03's arithmetic and is deliberately absent here.
    """
    rows = tracker["quorum"]
    axes = {row["id"] for row in tracker["questions"]} | {"new"}
    phases = {row["id"] for row in tracker["phases"]}
    if len({row["qid"] for row in rows}) != len(rows):
        raise TrackerValidationError(
            "duplicate qid: there is one adopted answer per qid per run"
        )
    for row in rows:
        if not _QID.fullmatch(row["qid"]):
            raise TrackerValidationError("a qid is twelve lowercase hex characters")
        if row["axis"] not in axes:
            raise TrackerValidationError(
                "a quorum axis is a stage-03 question id or the literal 'new'"
            )
        if row["phase"] != "-" and row["phase"] not in phases:
            raise TrackerValidationError("quorum row refers to an unknown phase")
        if row["state"] not in _QUORUM_STATES:
            raise TrackerValidationError("unknown quorum state")
        owners = _csv(row["owners"])
        if len(owners) != 3 or len(set(owners)) != 3:
            raise TrackerValidationError(
                "a quorum dispatches exactly three distinct brains; a count is "
                "never reduced to fit capacity"
            )
        for key in ("payload_digest", "context_digest"):
            if not _SHA256.fullmatch(row[key]):
                raise TrackerValidationError(
                    f"{key} must be sha256 hex and is persisted before dispatch"
                )
        responses = _csv(row["responses"])
        if len(responses) > 3 or len(set(responses)) != len(responses):
            raise TrackerValidationError(
                "a quorum records at most three distinct response files"
            )
        if row["state"] == "in_flight":
            if any(row[key] != "-" for key in ("depth", "rung", "outcome", "decision")):
                raise TrackerValidationError(
                    "an in-flight quorum carries no computed result; the three-phase "
                    "record exists so an interruption is always classifiable"
                )
            continue
        if not _QUORUM_OUTCOME.fullmatch(row["outcome"]):
            raise TrackerValidationError("unknown quorum outcome")
        if row["rung"] != "-" and row["rung"] not in RUNG_NAMES:
            raise TrackerValidationError(
                f"rung {row['rung']!r} is outside the enum; an out-of-enum rung is "
                "schema-invalid and is never defaulted to a legal value"
            )
        if row["depth"] != "-" and not row["depth"].isdigit():
            raise TrackerValidationError("decision depth must be a non-negative integer")
        if row["outcome"] == "adopted":
            if len(responses) != 3:
                raise TrackerValidationError(
                    "adoption requires three valid responses on disk"
                )
            if not _QUORUM_DECISION.fullmatch(row["decision"]):
                raise TrackerValidationError(
                    "an adopted quorum records its Q-<hash> decision so provenance "
                    "survives even if the Provenance field is lost"
                )
            if row["rung"] == "-" or row["depth"] == "-":
                raise TrackerValidationError(
                    "an adopted quorum records its winning rung and decision depth"
                )
        elif row["decision"] != "-":
            raise TrackerValidationError("only an adopted quorum carries a decision")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 58 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): validate the three-phase quorum record and the rung enum"
```

---

## Task 6: `## Tasks`, `## Phases` and `## Gates` semantics, including the one-way ratchet

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `_validate_tracker_semantics`, `_COMMIT`, `_csv`.
- Produces: module-private `_validate_tasks`, `_validate_phases`, `_validate_gates`, wired into `_validate_tracker_semantics`.

**Rules from the spec these encode:** an unstarted task carries no lifecycle state; completion and integration are **separate facts**, so a finished task may be `[x]` with its integration `held` while the budget freeze holds it; `review_class ∈ {final-only, required}`; the ratchet is upward-only and a tracker class differing from plan metadata is legal only with a matching ratchet record.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
class TaskSectionTests(unittest.TestCase):
    def test_an_unstarted_task_cannot_carry_lifecycle_state(self):
        text = valid_text().replace(
            "| P02-T01 | P02 | artifact | [~] | impl-2 | attempt-002 |",
            "| P02-T01 | P02 | artifact | [ ] | impl-2 | attempt-002 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_started_task_needs_owner_attempt_and_checkpoints(self):
        text = valid_text().replace(
            "| P02-T01 | P02 | artifact | [~] | impl-2 | attempt-002 | - | red |",
            "| P02-T01 | P02 | artifact | [~] | - | - | - | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_in_flight_task_cannot_claim_completion_or_integration(self):
        text = valid_text().replace(
            "| P02-T01 | P02 | artifact | [~] | impl-2 | attempt-002 | - | red | - | - | - | - | - | - | yes |",
            "| P02-T01 | P02 | artifact | [~] | impl-2 | attempt-002 | - | red | - | - | docs/x.md | N/A | - | - | yes |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_blocked_task_names_its_question(self):
        text = valid_text().replace(
            "| - | scratch/p02-t02-question.md | no |", "| - | - | no |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_completed_source_task_may_hold_its_integration(self):
        """Completion and integration are separate facts. When the drift budget
        trips, running work finishes, publishes and imports to [x]; only
        integration is held. Freezing the import too would lose a finished
        task's evidence and repeat the work on resume."""
        tracker = pas.parse_tracker(valid_text())
        held = next(row for row in tracker["tasks"] if row["id"] == "P01-T02")
        self.assertEqual(held["state"], "[x]")
        self.assertEqual(held["integration"], "held")

    def test_a_completed_source_task_cannot_leave_integration_unrecorded(self):
        text = valid_text().replace(
            "| 2222222222222222222222222222222222222222 | - | held |",
            "| 2222222222222222222222222222222222222222 | - | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_completed_artifact_task_carries_na_integration(self):
        text = valid_text().replace(
            "| P02-T01 | P02 | artifact | [~] | impl-2 | attempt-002 | - | red | - | - | - | - | - | - | yes |",
            "| P02-T01 | P02 | artifact | [x] | impl-2 | attempt-002 | scratch/r.md | red | - | - | - | held | scratch/v.txt | - | yes |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_provisional_is_yes_or_no(self):
        text = valid_text().replace(
            "| scratch/p01-t01-tests.txt | - | no |",
            "| scratch/p01-t01-tests.txt | - | maybe |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_task_cannot_belong_to_an_unknown_phase(self):
        text = valid_text().replace("| P01-T01 | P01 |", "| P01-T01 | P99 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)


class PhaseSectionTests(unittest.TestCase):
    def test_the_ratchet_is_one_way(self):
        """final-only -> required only. A ratchet record paired with a
        final-only class is a downward reclassification wearing a ratchet's
        clothes, and the schema refuses it."""
        text = valid_text().replace(
            "| P02 | [~] | - | required | ratchet |",
            "| P02 | [~] | - | final-only | ratchet |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_ratcheted_class_must_name_its_trigger_and_evidence(self):
        text = valid_text().replace(
            "| required | ratchet | accumulated-surface@scratch/p02-ratchet.md |",
            "| required | ratchet | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_plan_sourced_class_cannot_carry_a_ratchet_record(self):
        text = valid_text().replace(
            "| required | plan | - | gate-p01 |",
            "| required | plan | accumulated-surface@scratch/p01-ratchet.md | gate-p01 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_review_class_is_final_only_or_required(self):
        text = valid_text().replace("| required | plan |", "| medium | plan |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unverified_phase_cannot_carry_verification_evidence(self):
        text = valid_text().replace("| P02 | [~] | - |", "| P02 | [~] | scratch/x.txt |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_verified_phase_needs_verification_evidence(self):
        text = valid_text().replace("| P01 | [x] | scratch/p01-verification.txt |",
                                    "| P01 | [x] | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)


class GateSectionTests(unittest.TestCase):
    def test_a_master_gate_cannot_name_a_phase(self):
        text = valid_text().replace("| gate-master | master | - |",
                                    "| gate-master | master | P02 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_phase_gate_must_name_a_known_phase(self):
        text = valid_text().replace("| gate-p01 | phase | P01 |",
                                    "| gate-p01 | phase | P99 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_opened_gate_needs_its_immutable_edge(self):
        text = valid_text().replace(
            "| gate-p02 | phase | P02 | in_progress | c8bddd610119f52b54bf077d284c7f5d8362ae77 |",
            "| gate-p02 | phase | P02 | in_progress | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_accepted_gate_needs_reports_and_verification(self):
        text = valid_text().replace(
            "| spec,quality | scratch/gate-p01-review.md | scratch/gate-p01-tests.txt |",
            "| spec,quality | - | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_phase_cannot_point_at_an_unknown_gate(self):
        text = valid_text().replace("| - | gate-p01 |", "| - | gate-p99 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k "TaskSection or PhaseSection or GateSection"`
Expected: FAIL — `TrackerValidationError not raised`

- [ ] **Step 3: Write the implementation**

Append, and add all three calls to `_validate_tracker_semantics` — `_validate_phases` **before** `_validate_tasks` and `_validate_gates` so an unknown phase id is reported against the phase table:

```python
_TASK_KINDS = ("source", "artifact")
_TASK_STATES = ("[ ]", "[~]", "[?]", "[x]")
_PHASE_STATES = ("[ ]", "[~]", "[x]")
_REVIEW_CLASSES = ("final-only", "required")
_CLASS_SOURCES = ("plan", "ratchet")
_GATE_TYPES = ("phase", "master")
_GATE_STATES = ("pending", "in_progress", "blocked", "accepted")
_TASK_LIFECYCLE = (
    "owner", "attempt", "result", "checkpoints", "source_ref", "commits",
    "artifacts", "integration", "verification", "question",
)
_TASK_COMPLETION = ("source_ref", "commits", "artifacts", "integration")


def _validate_tasks(tracker: dict) -> None:
    phases = {row["id"] for row in tracker["phases"]}
    seen: set[str] = set()
    for task in tracker["tasks"]:
        if task["id"] in seen:
            raise TrackerValidationError("duplicate task id")
        seen.add(task["id"])
        if task["phase"] not in phases:
            raise TrackerValidationError("task refers to an unknown phase")
        if task["kind"] not in _TASK_KINDS:
            raise TrackerValidationError("unknown task kind")
        if task["state"] not in _TASK_STATES:
            raise TrackerValidationError("unknown task state")
        if task["provisional"] not in ("yes", "no"):
            raise TrackerValidationError("Provisional is yes or no")
        if task["state"] == "[ ]" and any(task[key] != "-" for key in _TASK_LIFECYCLE):
            raise TrackerValidationError("an unstarted task carries no lifecycle state")
        if task["state"] != "[ ]" and any(
            task[key] == "-" for key in ("owner", "attempt", "checkpoints")
        ):
            raise TrackerValidationError(
                "a started task needs owner, attempt, and checkpoints"
            )
        if task["state"] in ("[~]", "[?]") and any(
            task[key] != "-" for key in _TASK_COMPLETION
        ):
            raise TrackerValidationError(
                "an in-flight task cannot claim completion or integration"
            )
        if task["state"] == "[?]" and task["question"] == "-":
            raise TrackerValidationError("a blocked task names its question record")
        if task["state"] != "[x]":
            continue
        if task["result"] == "-" or task["verification"] == "-":
            raise TrackerValidationError(
                "a completed task needs its immutable result and verification evidence"
            )
        if task["kind"] == "source":
            # Completion and integration are separate facts. When the drift
            # budget trips, running work finishes, publishes and imports to [x];
            # only integration is held. 'held' is therefore a legal integration
            # value, but an unrecorded one never is.
            if task["source_ref"] == "-" or task["commits"] == "-":
                raise TrackerValidationError(
                    "a completed source task needs its source ref and commits"
                )
            if task["integration"] == "N/A" or (
                task["integration"] != "held" and not _COMMIT.fullmatch(task["integration"])
            ):
                raise TrackerValidationError(
                    "a completed source task records its integration commit or 'held'"
                )
        elif task["artifacts"] == "-" or task["integration"] != "N/A":
            raise TrackerValidationError(
                "a completed artifact task names its artifacts and carries N/A integration"
            )


def _validate_phases(tracker: dict) -> None:
    gates = {row["id"] for row in tracker["gates"]}
    seen: set[str] = set()
    for phase in tracker["phases"]:
        if phase["id"] in seen:
            raise TrackerValidationError("duplicate phase id")
        seen.add(phase["id"])
        if phase["state"] not in _PHASE_STATES:
            raise TrackerValidationError("unknown phase state")
        if phase["review_class"] not in _REVIEW_CLASSES:
            raise TrackerValidationError("review class is final-only or required")
        if phase["class_source"] not in _CLASS_SOURCES:
            raise TrackerValidationError("class source is plan or ratchet")
        if phase["class_source"] == "ratchet":
            if phase["ratchet"] == "-":
                raise TrackerValidationError(
                    "a tracker review class differing from plan metadata is legal "
                    "only with a matching ratchet record naming trigger and evidence"
                )
            if phase["review_class"] != "required":
                raise TrackerValidationError(
                    "the ratchet is upward-only: final-only -> required, never back"
                )
        elif phase["ratchet"] != "-":
            raise TrackerValidationError(
                "only a ratcheted phase records a ratchet trigger"
            )
        if (phase["state"] == "[x]") != (phase["verification"] != "-"):
            raise TrackerValidationError(
                "a phase is verified with evidence, or neither"
            )
        if phase["gate"] != "-" and phase["gate"] not in gates:
            raise TrackerValidationError("phase refers to an unknown review gate")


def _validate_gates(tracker: dict) -> None:
    phases = {row["id"] for row in tracker["phases"]}
    seen: set[str] = set()
    for gate in tracker["gates"]:
        if gate["id"] in seen:
            raise TrackerValidationError("duplicate gate id")
        seen.add(gate["id"])
        if gate["type"] not in _GATE_TYPES:
            raise TrackerValidationError("gate type is phase or master")
        if gate["type"] == "phase" and gate["phase"] not in phases:
            raise TrackerValidationError("a phase gate refers to an unknown phase")
        if gate["type"] == "master" and gate["phase"] != "-":
            raise TrackerValidationError("a master gate cannot name a phase")
        if gate["state"] not in _GATE_STATES:
            raise TrackerValidationError("unknown gate state")
        if gate["state"] != "pending" and any(
            gate[key] == "-" for key in ("base", "head", "assignments")
        ):
            raise TrackerValidationError(
                "an opened gate needs its immutable edge and its assignments"
            )
        if gate["state"] in ("blocked", "accepted") and any(
            gate[key] == "-" for key in ("reports", "verification")
        ):
            raise TrackerValidationError(
                "an evaluated gate needs its reports and verification evidence"
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 78 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): validate tasks, phases, gates, and the one-way ratchet"
```

---

## Task 7: `## Task Review` and `## Fix Rounds` semantics

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `_validate_tracker_semantics`, `_csv`.
- Produces: module-private `_validate_task_review`, `_validate_fix_rounds`, wired into `_validate_tracker_semantics`.

**Rules from the spec these encode:** a task reviewer returns **three** verdicts — spec, quality, and verification evidence from an independent re-run; a task's own implementer never reviews it; **one fixer per round**; and the fix loop closes only on a round that returns **zero open findings**, a bar the dial may never switch off.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
class TaskReviewSectionTests(unittest.TestCase):
    def test_a_tasks_own_implementer_cannot_review_it(self):
        """Non-implementer review is one of the things the dial may never
        switch off. Self-review passes anything."""
        text = valid_text().replace(
            "| P01-T01 | attempt-001 | reviewer-1 |",
            "| P01-T01 | attempt-001 | impl-1 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_evaluated_review_needs_all_three_verdicts(self):
        text = valid_text().replace(
            "| P02-T01 | attempt-002 | reviewer-2 | blocked | fail | pass | scratch/p02-t01-rerun.txt |",
            "| P02-T01 | attempt-002 | reviewer-2 | blocked | fail | pass | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_accepted_review_passes_on_both_spec_and_quality(self):
        text = valid_text().replace(
            "| P01-T01 | attempt-001 | reviewer-1 | accepted | pass | pass |",
            "| P01-T01 | attempt-001 | reviewer-1 | accepted | fail | pass |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_accepted_review_closes_at_zero_open_findings(self):
        text = valid_text().replace(
            "| scratch/p01-t01-rerun.txt | none | large-surface |",
            "| scratch/p01-t01-rerun.txt | F-004 | large-surface |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_blocked_review_must_name_its_open_findings(self):
        text = valid_text().replace(
            "| scratch/p02-t01-rerun.txt | F-001,F-002 | - |",
            "| scratch/p02-t01-rerun.txt | none | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_review_cannot_refer_to_an_unknown_task(self):
        text = valid_text().replace("| P02-T01 | attempt-002 | reviewer-2 |",
                                    "| P09-T09 | attempt-002 | reviewer-2 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_an_unknown_verdict_word_is_rejected(self):
        text = valid_text().replace(
            "| accepted | pass | pass |", "| accepted | ok | pass |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)


class FixRoundSectionTests(unittest.TestCase):
    def test_the_loop_closes_only_on_a_round_with_zero_remaining_findings(self):
        """Zero open findings at every severity is the bar. A final round that
        still lists findings is a fix loop that stopped early."""
        text = valid_text().replace(
            "| scratch/p01-t01-r1-review.md | none |",
            "| scratch/p01-t01-r1-review.md | F-003 |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_round_with_remaining_findings_is_legal_when_a_later_round_follows(self):
        text = valid_text().replace(
            "| P01-T01 | 1 | complete | fixer-0 | F-003 | abcdef0123456789abcdef0123456789abcdef01 "
            "| scratch/p01-t01-r1-tests.txt | scratch/p01-t01-r1-review.md | none |",
            "| P01-T01 | 1 | complete | fixer-0 | F-003 | abcdef0123456789abcdef0123456789abcdef01 "
            "| scratch/p01-t01-r1-tests.txt | scratch/p01-t01-r1-review.md | F-003 |\n"
            "| P01-T01 | 2 | complete | fixer-2 | F-003 | abcdef0123456789abcdef0123456789abcdef02 "
            "| scratch/p01-t01-r2-tests.txt | scratch/p01-t01-r2-review.md | none |")
        tracker = pas.parse_tracker(text)
        self.assertEqual(len(tracker["fix_rounds"]), 3)

    def test_a_scope_cannot_have_two_active_rounds(self):
        text = valid_text().replace(
            "| P02-T01 | 1 | fixing | fixer-1 | F-001,F-002 | - | - | - | - |",
            "| P02-T01 | 1 | fixing | fixer-1 | F-001,F-002 | - | - | - | - |\n"
            "| P02-T01 | 2 | fixing | fixer-3 | F-001 | - | - | - | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_rounds_are_numbered_one_through_n_per_scope(self):
        text = valid_text().replace("| P02-T01 | 1 | fixing |", "| P02-T01 | 3 | fixing |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_fixing_round_names_one_fixer_and_has_no_commits_yet(self):
        text = valid_text().replace(
            "| P02-T01 | 1 | fixing | fixer-1 | F-001,F-002 | - |",
            "| P02-T01 | 1 | fixing | fixer-1,fixer-9 | F-001,F-002 | - |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_only_a_completed_round_records_remaining_findings(self):
        text = valid_text().replace(
            "| P02-T01 | 1 | fixing | fixer-1 | F-001,F-002 | - | - | - | - |",
            "| P02-T01 | 1 | fixing | fixer-1 | F-001,F-002 | - | - | - | none |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)

    def test_a_round_cannot_name_an_unknown_scope(self):
        text = valid_text().replace("| P02-T01 | 1 | fixing |", "| P09-T09 | 1 | fixing |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_tracker(text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k "TaskReview or FixRound"`
Expected: FAIL — `TrackerValidationError not raised`

- [ ] **Step 3: Write the implementation**

Append, and add both calls to `_validate_tracker_semantics`:

```python
_REVIEW_STATES = ("pending", "reviewing", "blocked", "accepted")
_VERDICTS = ("-", "pass", "fail")
_FIX_ROUND_STATES = ("pending", "fixing", "re_reviewing", "complete")
_FIX_ROUND_LIFECYCLE = (
    "fixer", "findings", "commits", "verification", "re_review", "remaining",
)


def _validate_task_review(tracker: dict) -> None:
    """Three verdicts, a reviewer who is not the implementer, and a zero bar."""
    current = {row["id"]: (row["attempt"], row["owner"]) for row in tracker["tasks"]}
    seen: set[tuple[str, str]] = set()
    for review in tracker["task_review"]:
        key = (review["task"], review["attempt"])
        if key in seen:
            raise TrackerValidationError("duplicate task review row for one attempt")
        seen.add(key)
        if review["task"] not in current:
            raise TrackerValidationError("task review refers to an unknown task")
        attempt, owner = current[review["task"]]
        if review["attempt"] == attempt and review["reviewer"] == owner:
            raise TrackerValidationError(
                "a task's own implementer cannot review it; non-implementer review "
                "is one of the things the dial may never switch off"
            )
        if review["state"] not in _REVIEW_STATES:
            raise TrackerValidationError("unknown task review state")
        if any(review[key] not in _VERDICTS
               for key in ("spec_verdict", "quality_verdict")):
            raise TrackerValidationError("a verdict is pass or fail")
        if review["state"] == "pending" and any(
            review[key] != "-" for key in
            ("spec_verdict", "quality_verdict", "verification", "findings")
        ):
            raise TrackerValidationError("a pending task review carries no verdicts")
        if review["state"] in ("blocked", "accepted"):
            if any(review[key] == "-" for key in
                   ("spec_verdict", "quality_verdict", "verification")):
                raise TrackerValidationError(
                    "an evaluated task review returns three verdicts: spec, quality, "
                    "and verification evidence from an independent re-run"
                )
        if review["state"] == "accepted":
            if review["spec_verdict"] != "pass" or review["quality_verdict"] != "pass":
                raise TrackerValidationError(
                    "an accepted task review passes on both spec and quality"
                )
            if review["findings"] != "none":
                raise TrackerValidationError(
                    "an accepted task review closes at zero open findings"
                )
        if review["state"] == "blocked" and review["findings"] in ("-", "none"):
            raise TrackerValidationError("a blocked task review names its open findings")
        if review["adversarial"] != "-" and not _TOKEN.fullmatch(review["adversarial"]):
            raise TrackerValidationError("the adversarial cell names the trigger that fired")


def _validate_fix_rounds(tracker: dict) -> None:
    scopes = (
        {row["id"] for row in tracker["tasks"]}
        | {row["id"] for row in tracker["phases"]}
        | {row["id"] for row in tracker["gates"]}
    )
    by_scope: dict[str, list[dict]] = {}
    for fix in tracker["fix_rounds"]:
        if fix["scope"] not in scopes:
            raise TrackerValidationError("fix round names an unknown scope")
        if not fix["round"].isdigit() or int(fix["round"]) < 1:
            raise TrackerValidationError("fix round numbers start at 1")
        if fix["state"] not in _FIX_ROUND_STATES:
            raise TrackerValidationError("unknown fix round state")
        by_scope.setdefault(fix["scope"], []).append(fix)
        if fix["state"] == "pending" and any(
            fix[key] != "-" for key in _FIX_ROUND_LIFECYCLE
        ):
            raise TrackerValidationError("a pending fix round carries no lifecycle state")
        if fix["state"] == "fixing":
            if len(_csv(fix["fixer"])) != 1:
                raise TrackerValidationError(
                    "one fixer per round, carrying all findings"
                )
            if fix["findings"] == "-" or fix["commits"] != "-":
                raise TrackerValidationError(
                    "a fixing round names its findings and has produced no commits yet"
                )
        if fix["state"] == "re_reviewing" and any(
            fix[key] == "-" for key in ("fixer", "findings", "commits", "verification")
        ):
            raise TrackerValidationError(
                "a re-reviewing round needs fixer, findings, commits, and verification"
            )
        if fix["state"] == "complete":
            if any(fix[key] == "-" for key in _FIX_ROUND_LIFECYCLE):
                raise TrackerValidationError(
                    "a completed fix round records its full lifecycle and its outcome"
                )
        elif fix["remaining"] != "-":
            raise TrackerValidationError(
                "only a completed fix round records remaining findings"
            )
    for scope, rounds in by_scope.items():
        numbers = sorted(int(fix["round"]) for fix in rounds)
        if numbers != list(range(1, len(numbers) + 1)):
            raise TrackerValidationError(f"fix rounds for {scope} must be numbered 1..n")
        if sum(1 for fix in rounds if fix["state"] in ("fixing", "re_reviewing")) > 1:
            raise TrackerValidationError(f"{scope} cannot have two active fix rounds")
        last = max(rounds, key=lambda fix: int(fix["round"]))
        if last["state"] == "complete" and last["remaining"] != "none":
            raise TrackerValidationError(
                "the fix loop closes only on a round that returns zero open findings "
                "at every severity"
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 92 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): validate task reviews and the zero-open-findings fix loop"
```

---

## Task 8: The run-local exclusive lock

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `TrackerWriteError`.
- Produces: `LockUnavailableError(TrackerWriteError)`, `LockBusyError(TrackerWriteError)`, `select_lock_impl(fcntl_module, msvcrt_module) -> tuple[callable, callable, str]`, and the module-private `_exclusive_lock(run_dir, *, timeout_s)` context manager.

**Why these are `TrackerWriteError` subclasses:** the master plan's P02 block fixes five exception names. A lock failure is, semantically, "the write did not happen and nothing changed", which is exactly `TrackerWriteError`. Subclassing keeps the published contract exact while letting a caller distinguish contention from a missing primitive. No caller is required to know the subclasses.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
import multiprocessing
import os
import types


def hold_lock(run_dir: str, ready, release) -> None:
    import pipeline_auto_state as module
    with module._exclusive_lock(Path(run_dir), timeout_s=5.0):
        ready.set()
        release.wait(20)


class LockTests(unittest.TestCase):
    def test_lock_errors_are_write_errors_so_callers_know_nothing_changed(self):
        self.assertTrue(issubclass(pas.LockUnavailableError, pas.TrackerWriteError))
        self.assertTrue(issubclass(pas.LockBusyError, pas.TrackerWriteError))

    def test_a_second_holder_times_out_rather_than_racing(self):
        run_dir = make_run(self)
        context = multiprocessing.get_context("spawn")
        ready, release = context.Event(), context.Event()
        holder = context.Process(target=hold_lock,
                                 args=(str(run_dir), ready, release))
        holder.start()
        self.addCleanup(holder.join)
        self.addCleanup(release.set)
        self.assertTrue(ready.wait(20), "the holder never acquired the lock")
        with self.assertRaises(pas.LockBusyError):
            with pas._exclusive_lock(run_dir, timeout_s=0.2):
                pass

    def test_the_lock_is_reacquirable_once_released(self):
        run_dir = make_run(self)
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            pass
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            pass

    def test_the_lock_file_lives_in_the_run_directory_and_is_never_unlinked(self):
        run_dir = make_run(self)
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            pass
        lock_path = run_dir / ".pipeline-auto.lock"
        self.assertTrue(lock_path.is_file())
        inode = lock_path.stat().st_ino
        with pas._exclusive_lock(run_dir, timeout_s=1.0):
            pass
        self.assertEqual(lock_path.stat().st_ino, inode)

    def test_no_os_lock_primitive_is_an_explicit_failure_not_a_silent_no_lock(self):
        """Falling back to 'no lock' would make every concurrency guarantee in
        this module a comment."""
        with self.assertRaises(pas.LockUnavailableError):
            pas.select_lock_impl(None, None)
        with self.assertRaises(pas.LockUnavailableError):
            pas.select_lock_impl(types.SimpleNamespace(), types.SimpleNamespace())

    def test_a_negative_timeout_is_rejected(self):
        run_dir = make_run(self)
        with self.assertRaises(pas.LockUnavailableError):
            with pas._exclusive_lock(run_dir, timeout_s=-1.0):
                pass
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Lock`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'LockUnavailableError'`

- [ ] **Step 3: Write the implementation**

Add these imports to the module header, then append the code:

```python
import errno
import os
import time
from contextlib import contextmanager

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - exercised only on Windows
    fcntl = None
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - exercised only on POSIX
    msvcrt = None
```

```python
class LockUnavailableError(TrackerWriteError):
    """No usable OS lock primitive, or the lock resource changed underfoot."""


class LockBusyError(TrackerWriteError):
    """Another holder has the run lock. Nothing was changed."""


LOCK_FILENAME = ".pipeline-auto.lock"
DEFAULT_LOCK_TIMEOUT_S = 10.0
_CONTENTION = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLOCK}


def select_lock_impl(fcntl_module, msvcrt_module):
    """Return (acquire, release, description) for the best available primitive.

    There is deliberately no third branch. A 'no lock available, proceed anyway'
    fallback would turn every concurrency guarantee in this module into a
    comment, and the failure would only ever show up as corrupted state.
    """
    if fcntl_module is not None and hasattr(fcntl_module, "flock"):
        def acquire(descriptor: int) -> bool:
            try:
                fcntl_module.flock(descriptor,
                                   fcntl_module.LOCK_EX | fcntl_module.LOCK_NB)
            except OSError as exc:
                if exc.errno in _CONTENTION:
                    return False
                raise
            return True

        def release(descriptor: int) -> None:
            fcntl_module.flock(descriptor, fcntl_module.LOCK_UN)

        return acquire, release, "POSIX flock"

    if msvcrt_module is not None and hasattr(msvcrt_module, "locking"):
        def acquire(descriptor: int) -> bool:
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt_module.locking(descriptor, msvcrt_module.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in _CONTENTION:
                    return False
                raise
            return True

        def release(descriptor: int) -> None:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt_module.locking(descriptor, msvcrt_module.LK_UNLCK, 1)

        return acquire, release, "msvcrt locking; native Windows verification pending"

    raise LockUnavailableError(
        "no OS-backed lock primitive: fcntl.flock and msvcrt.locking are both "
        "unavailable, and this module never proceeds without a lock"
    )


@contextmanager
def _exclusive_lock(run_dir, *, timeout_s: float = DEFAULT_LOCK_TIMEOUT_S):
    """Hold the stable run-local lock, never unlinking its path.

    Unlinking a lock file lets two holders lock two different inodes at the
    same path and both believe they won, so the path is created once and kept.
    The post-acquire identity check catches the case where somebody else
    removed and recreated it while we were waiting.
    """
    if timeout_s < 0:
        raise LockUnavailableError("lock timeout must be non-negative")
    run_dir = Path(run_dir)
    lock_path = run_dir / LOCK_FILENAME
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise LockUnavailableError(f"cannot open run lock {lock_path}: {exc}") from exc
    acquired = False
    release = None
    try:
        acquire, release, _ = select_lock_impl(fcntl, msvcrt)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                acquired = acquire(descriptor)
            except OSError as exc:
                raise LockUnavailableError(
                    f"cannot acquire run lock {lock_path}: {exc}"
                ) from exc
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise LockBusyError(
                    f"run lock {lock_path} busy after {timeout_s:.3f}s; nothing changed"
                )
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        try:
            held = os.fstat(descriptor)
            named = os.stat(lock_path)
        except OSError as exc:
            raise LockUnavailableError(
                f"cannot verify run lock identity {lock_path}: {exc}"
            ) from exc
        if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
            raise LockUnavailableError(
                f"the run lock resource changed while acquiring {lock_path}"
            )
        yield
    finally:
        if acquired and release is not None:
            try:
                release(descriptor)
            except OSError:
                pass
        os.close(descriptor)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 98 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): add the run-local exclusive lock with no silent fallback"
```

---

## Task 9: Atomic replacement and the three write outcomes

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `TrackerWriteError`, `UpdateOutcomeUncertain`.
- Produces: module-private `_sync_file(handle)`, `_sync_directory(directory)`, `_replace_tracker(run_dir, text, transition_id)`.

**Named faults this task catches, both of them:**

1. `_replace_tracker` writing its temp file outside the run directory, so `os.replace` crosses a filesystem boundary, raises `OSError`, and stops being atomic. The test asserts both the `dir=` argument and that the temp file's `st_dev` equals the run directory's.
2. Catching both sync failures under one `except`, so a post-replace directory-sync failure surfaces as `TrackerWriteError` — "nothing happened" — when in fact the replacement already landed. Every autonomous retry path in this run depends on that distinction: a retry after `TrackerWriteError` is safe, a retry after `UpdateOutcomeUncertain` must reconcile `revision` and `last_transition` first or it double-applies.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
from unittest import mock


class ReplaceTrackerTests(unittest.TestCase):
    def test_the_file_being_renamed_lives_in_the_run_directory(self):
        """A temp file in the system temp dir makes os.replace a cross-device
        rename: it raises instead of swapping, and atomicity is gone. Assert
        both the location and the device, because on a machine where /tmp
        happens to share a device with the repo the location check is the only
        one that still fails."""
        run_dir = make_run(self)
        seen = {}
        real_replace = os.replace

        def spy(src, dst):
            seen["src"] = Path(src)
            seen["src_dev"] = os.stat(src).st_dev
            return real_replace(src, dst)

        with mock.patch.object(pas.os, "replace", side_effect=spy):
            pas._replace_tracker(run_dir, valid_text(), "transition-1")
        self.assertEqual(seen["src"].parent.resolve(), Path(run_dir).resolve())
        self.assertEqual(seen["src_dev"], os.stat(run_dir / "progress.md").st_dev)
        self.assertEqual((run_dir / "progress.md").read_text(encoding="utf-8"),
                         valid_text())

    def test_a_pre_replace_failure_leaves_the_old_tracker_intact(self):
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()
        with mock.patch.object(pas, "_sync_file",
                               side_effect=OSError(5, "simulated fsync failure")):
            with self.assertRaises(pas.TrackerWriteError) as caught:
                pas._replace_tracker(run_dir, valid_text().replace("| 12 |\n", "| 99 |\n"),
                                     "transition-2")
        self.assertNotIsInstance(caught.exception, pas.UpdateOutcomeUncertain)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)
        self.assertEqual([p.name for p in run_dir.iterdir()], ["progress.md"])

    def test_a_post_replace_failure_raises_update_outcome_uncertain(self):
        """The replacement already landed. Reporting TrackerWriteError here
        tells an autonomous retry that nothing happened, and it re-applies a
        transition that did apply."""
        run_dir = make_run(self)
        replacement = valid_text().replace("| revision | 12 |", "| revision | 13 |")
        with mock.patch.object(pas, "_sync_directory",
                               side_effect=OSError(5, "simulated dirsync failure")):
            with self.assertRaises(pas.UpdateOutcomeUncertain):
                pas._replace_tracker(run_dir, replacement, "transition-3")
        self.assertEqual((run_dir / "progress.md").read_text(encoding="utf-8"),
                         replacement)

    def test_update_outcome_uncertain_is_not_caught_as_a_plain_write_error_by_accident(self):
        self.assertFalse(issubclass(pas.UpdateOutcomeUncertain, pas.TrackerWriteError))
        self.assertTrue(issubclass(pas.UpdateOutcomeUncertain, pas.TrackerError))

    def test_a_successful_replace_leaves_no_temp_file_behind(self):
        run_dir = make_run(self)
        pas._replace_tracker(run_dir, valid_text(), "transition-4")
        self.assertEqual(sorted(p.name for p in run_dir.iterdir()), ["progress.md"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ReplaceTracker`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute '_replace_tracker'`

- [ ] **Step 3: Write the implementation**

Add `import tempfile` to the module header, then append:

```python
def _sync_file(handle) -> None:
    handle.flush()
    os.fsync(handle.fileno())


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":  # native directory-sync semantics remain unverified
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_tracker(run_dir, text: str, transition_id: str) -> None:
    """Replace progress.md atomically, and be exact about which outcome occurred.

    Two try blocks, not one. Everything up to and including ``os.replace`` is
    'nothing has happened yet' and fails as TrackerWriteError. The directory
    fsync afterwards is 'it already happened, durably or not' and fails as
    UpdateOutcomeUncertain. Collapsing them into a single except — even with a
    `replaced` flag — is the edit that makes a retry double-apply, because the
    caller is told nothing changed when the replacement already landed.

    The temp file is created with ``dir=run_dir`` so it shares a filesystem with
    progress.md. A temp file elsewhere makes os.replace a cross-device rename,
    which raises rather than swapping, and atomicity is gone.
    """
    run_dir = Path(run_dir)
    progress = run_dir / "progress.md"
    descriptor = -1
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            dir=str(run_dir), prefix=".progress.", suffix=".tmp"
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            descriptor = -1
            handle.write(text)
            _sync_file(handle)
        os.replace(temporary, progress)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise TrackerWriteError(
            f"tracker update {transition_id} failed before replacement; "
            f"the old tracker is intact and nothing changed: {exc}"
        ) from exc

    try:
        _sync_directory(run_dir)
    except OSError as exc:
        raise UpdateOutcomeUncertain(
            f"tracker update {transition_id} replaced progress.md, then the "
            "directory sync failed; the update may or may not survive a crash. "
            "Reconcile revision and last_transition before retrying — a blind "
            f"retry can double-apply: {exc}"
        ) from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 103 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): separate the pre-replace and post-replace write outcomes"
```

---

## Task 10: `locked_tracker_update` — the only way state ever changes

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `validate_run`, `parse_tracker`, `render_tracker`, `_exclusive_lock`, `_replace_tracker`, `DEFAULT_LOCK_TIMEOUT_S`.
- Produces: `locked_tracker_update(run_dir: str, *, transition_id: str, mutate, timeout_s: float = DEFAULT_LOCK_TIMEOUT_S) -> dict`.

`mutate` is called with a deep copy of the current tracker dict and must return a tracker dict. `timeout_s` is keyword-only with a default, so every call in the master plan's signature remains valid.

**Named fault this task catches:** a replayed `transition_id` mutating instead of returning current state. Every autonomous resume path re-issues the transition it was in the middle of; if replay applies a second time, a resumed run silently doubles a task record, a quorum response, or a dispatch count.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
def bump_dispatches(tracker: dict) -> dict:
    tracker["run"]["agent_dispatch_count"] = str(
        int(tracker["run"]["agent_dispatch_count"]) + 1)
    return tracker


class LockedUpdateTests(unittest.TestCase):
    def test_a_successful_update_bumps_revision_and_records_the_transition(self):
        run_dir = make_run(self)
        result = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                           mutate=bump_dispatches)
        self.assertEqual(result["run"]["revision"], "13")
        self.assertEqual(result["run"]["last_transition"], "dispatch-1")
        self.assertEqual(result["run"]["agent_dispatch_count"], "49")
        self.assertEqual(pas.validate_run(run_dir), result)

    def test_a_replayed_transition_returns_current_state_without_mutating(self):
        """Every resume path re-issues the transition it was interrupted in. If
        replay applies a second time, a resumed run silently doubles whatever
        that transition recorded."""
        run_dir = make_run(self)
        pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                  mutate=bump_dispatches)
        after_first = (run_dir / "progress.md").read_bytes()
        calls = []

        def should_not_run(tracker):
            calls.append(tracker)
            return bump_dispatches(tracker)

        replayed = pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                             mutate=should_not_run)
        self.assertEqual(calls, [])
        self.assertEqual((run_dir / "progress.md").read_bytes(), after_first)
        self.assertEqual(replayed["run"]["revision"], "13")
        self.assertEqual(replayed["run"]["agent_dispatch_count"], "49")

    def test_the_reparse_canary_rejects_a_mutation_that_renders_invalid_state(self):
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()

        def regress_stage(tracker):
            tracker["stages"][0]["stage_state"] = "pending"
            return tracker

        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(run_dir, transition_id="regress-1",
                                      mutate=regress_stage)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_a_transition_cannot_change_run_identity(self):
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()

        def rebrand(tracker):
            tracker["run"]["run_id"] = "2026-09-14-somebody-elses-run"
            return tracker

        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(run_dir, transition_id="rebrand-1", mutate=rebrand)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_the_intent_brief_is_immutable_once_stage_03_closes(self):
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()

        def rewrite_brief(tracker):
            brief = next(row for row in tracker["intent"] if row["id"] == "brief")
            brief["result"] = "scratch/intent-brief-v2.md"
            return tracker

        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(run_dir, transition_id="brief-2",
                                      mutate=rewrite_brief)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_a_foreign_tracker_is_refused_before_mutate_is_ever_called(self):
        foreign = (FOREIGN_FIXTURES / "valid-v2-progress.md").read_bytes()
        run_dir = make_run(self, foreign.decode("utf-8"))
        calls = []
        with self.assertRaises(pas.ForeignSchemaError):
            pas.locked_tracker_update(run_dir, transition_id="dispatch-1",
                                      mutate=lambda t: calls.append(t) or t)
        self.assertEqual(calls, [])
        self.assertEqual((run_dir / "progress.md").read_bytes(), foreign)

    def test_mutate_must_return_a_tracker_dict(self):
        run_dir = make_run(self)
        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(run_dir, transition_id="bad-1",
                                      mutate=lambda tracker: None)

    def test_an_invalid_transition_identity_is_rejected(self):
        run_dir = make_run(self)
        with self.assertRaises(pas.TrackerValidationError):
            pas.locked_tracker_update(run_dir, transition_id="not a token",
                                      mutate=bump_dispatches)

    def test_a_mutate_that_raises_partway_changes_nothing_on_disk(self):
        """mutate gets a deep copy, so a worker that dies halfway through a
        transition cannot leave a half-applied tracker behind."""
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()

        def half_apply(tracker):
            tracker["run"]["agent_dispatch_count"] = "999"
            raise RuntimeError("worker died mid-transition")

        with self.assertRaises(RuntimeError):
            pas.locked_tracker_update(run_dir, transition_id="half-1", mutate=half_apply)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)
        self.assertEqual(pas.validate_run(run_dir)["run"]["agent_dispatch_count"], "48")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k LockedUpdate`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'locked_tracker_update'`

- [ ] **Step 3: Write the implementation**

Add `import copy` to the module header, then append:

```python
_IDENTITY_KEYS = ("run_id", "schema", "base_commit", "target_branch")


def _guard_frozen_intent(current: dict, proposed: dict) -> None:
    """The reconciled intent brief is immutable once stage 03 closes.

    A contradicting finding escalates and a human amends it; no transition
    rewrites it in place. Without this guard a later stage could quietly
    substitute a different brief and every downstream artifact would still
    look consistent.
    """
    frozen = [row for row in current["intent"]
              if row["id"] == "brief" and row["state"] == "frozen"]
    if not frozen:
        return
    after = [row for row in proposed["intent"] if row["id"] == "brief"]
    if len(after) != 1 or after[0] != frozen[0]:
        raise TrackerValidationError(
            "the intent brief is immutable once stage 03 closes; a contradicting "
            "finding escalates and the human amends it"
        )


def locked_tracker_update(run_dir: str, *, transition_id: str, mutate,
                          timeout_s: float = DEFAULT_LOCK_TIMEOUT_S) -> dict:
    """Apply exactly one idempotent durable transition.

    Order, and why each step is here:

    1. validate before locking, so a foreign or malformed run stops without
       ever creating a lock file inside somebody else's directory;
    2. take the exclusive run lock;
    3. re-read and re-validate under the lock, because the preflight read is
       already stale by the time the lock is held;
    4. replay check: the same transition_id returns current state and calls
       nothing, so a resume that re-issues its interrupted transition is inert;
    5. apply ``mutate`` to a deep copy;
    6. refuse any change to run identity;
    7. stamp revision and last_transition;
    8. render, then **reparse the render** — the canary. A mutation that would
       produce a tracker this module cannot read back is rejected before a
       single byte reaches disk;
    9. replace atomically and return the reparsed tracker, never the in-memory
       one, so callers only ever see state that survived a round trip.
    """
    if not _TOKEN.fullmatch(transition_id):
        raise TrackerValidationError("invalid transition identity")
    run_dir = Path(run_dir)
    validate_run(run_dir)
    with _exclusive_lock(run_dir, timeout_s=timeout_s):
        current = validate_run(run_dir)
        if current["run"]["last_transition"] == transition_id:
            return current
        proposed = mutate(copy.deepcopy(current))
        if not isinstance(proposed, dict):
            raise TrackerValidationError("mutate must return a tracker dict")
        for key in _IDENTITY_KEYS:
            if proposed.get("run", {}).get(key) != current["run"][key]:
                raise TrackerValidationError(f"a transition cannot change {key}")
        _guard_frozen_intent(current, proposed)
        proposed["run"]["revision"] = str(int(current["run"]["revision"]) + 1)
        proposed["run"]["last_transition"] = transition_id
        canonical = render_tracker(proposed)
        reparsed = parse_tracker(canonical)
        _replace_tracker(run_dir, canonical, transition_id)
        return reparsed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 112 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): route every durable transition through one idempotent update"
```

---

## Task 11: `initialize_run` and `publish_immutable`

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `render_tracker`, `parse_tracker`, `validate_run`, `_sync_file`, `_sync_directory`, `STAGES`, `_RUN_KEYS`.
- Produces: `initialize_run(run_dir: str, *, run_id: str, base_commit: str, target_branch: str, worker_limit: int) -> dict`, `publish_immutable(path: str, content: str) -> str` (returns the sha256 hex digest of the published bytes).

**Why `os.link` and not `os.replace` for the first write:** `initialize_run` must never overwrite a tracker that already exists — a second controller starting the same run must lose, not clobber. `os.link` fails with `FileExistsError` instead of replacing, which is exactly that behaviour. `publish_immutable` uses the same primitive for the same reason: an immutable artifact that can be overwritten is not immutable, and the audit trail is worthless.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
import hashlib


class InitializeRunTests(unittest.TestCase):
    def fresh(self) -> Path:
        run_dir = Path(tempfile.mkdtemp(prefix="pipeline-auto-init-")) / "run"
        self.addCleanup(shutil.rmtree, run_dir.parent, ignore_errors=True)
        return run_dir

    def test_a_new_run_starts_at_stage_01_with_every_table_empty(self):
        run_dir = self.fresh()
        tracker = pas.initialize_run(
            run_dir, run_id="2026-09-14-example",
            base_commit="c8bddd610119f52b54bf077d284c7f5d8362ae77",
            target_branch="feat/example", worker_limit=6)
        self.assertEqual(tracker["run"]["revision"], "0")
        self.assertEqual(tracker["run"]["last_transition"], "initialized")
        self.assertEqual(tracker["run"]["agent_dispatch_count"], "0")
        self.assertEqual(tracker["run"]["schema"], pas.SCHEMA)
        self.assertEqual([row["stage_state"] for row in tracker["stages"]],
                         ["active"] + ["pending"] * 11)
        for key in ("intent", "questions", "quorum", "escalations", "tasks",
                    "task_review", "fix_rounds", "phases", "gates"):
            self.assertEqual(tracker[key], [], key)
        self.assertEqual(pas.validate_run(run_dir), tracker)
        self.assertNotEqual(pas.derive_next_action(tracker), "complete")

    def test_run_artifacts_are_addressed_under_the_run_directory_convention(self):
        run_dir = self.fresh()
        tracker = pas.initialize_run(
            run_dir, run_id="2026-09-14-example",
            base_commit="c8bddd610119f52b54bf077d284c7f5d8362ae77",
            target_branch="feat/example", worker_limit=6)
        base = "docs/superpowers/runs/2026-09-14-example"
        self.assertEqual(tracker["run"]["decisions"], f"{base}/decisions.md")
        self.assertEqual(tracker["run"]["findings"], f"{base}/findings.md")
        self.assertEqual(tracker["run"]["completeness_proposals"],
                         f"{base}/completeness-proposals.md")
        for key in ("spec", "master_plan", "phase_plans"):
            self.assertEqual(tracker["run"][key], "-", key)

    def test_initialize_refuses_to_overwrite_an_existing_tracker(self):
        run_dir = make_run(self)
        before = (run_dir / "progress.md").read_bytes()
        with self.assertRaises(pas.ForeignSchemaError):
            pas.initialize_run(run_dir, run_id="2026-09-14-example",
                               base_commit="c8bddd610119f52b54bf077d284c7f5d8362ae77",
                               target_branch="feat/example", worker_limit=6)
        self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_a_run_never_targets_main_or_master(self):
        for branch in ("main", "master"):
            with self.assertRaises(pas.TrackerValidationError):
                pas.initialize_run(self.fresh(), run_id="2026-09-14-example",
                                   base_commit="c8bddd610119f52b54bf077d284c7f5d8362ae77",
                                   target_branch=branch, worker_limit=6)

    def test_a_short_base_commit_is_rejected(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.initialize_run(self.fresh(), run_id="2026-09-14-example",
                               base_commit="c8bddd61", target_branch="feat/example",
                               worker_limit=6)

    def test_a_worker_limit_below_one_is_rejected(self):
        with self.assertRaises(pas.TrackerValidationError):
            pas.initialize_run(self.fresh(), run_id="2026-09-14-example",
                               base_commit="c8bddd610119f52b54bf077d284c7f5d8362ae77",
                               target_branch="feat/example", worker_limit=0)

    def test_a_worker_limit_below_four_is_allowed_and_serialises(self):
        """worker_limit >= 4 is required for *concurrency*, not for legality:
        below it, tasks serialise so the three brain slots stay free."""
        tracker = pas.initialize_run(
            self.fresh(), run_id="2026-09-14-example",
            base_commit="c8bddd610119f52b54bf077d284c7f5d8362ae77",
            target_branch="feat/example", worker_limit=2)
        self.assertEqual(tracker["run"]["worker_limit"], "2")


class PublishImmutableTests(unittest.TestCase):
    def test_publishing_returns_the_sha256_of_the_bytes_written(self):
        run_dir = make_run(self)
        path = run_dir / "scratch" / "q1-brain-1.json"
        digest = pas.publish_immutable(path, '{"rung": "specified"}')
        self.assertEqual(digest,
                         hashlib.sha256(b'{"rung": "specified"}').hexdigest())
        self.assertEqual(path.read_text(encoding="utf-8"), '{"rung": "specified"}')

    def test_republishing_identical_content_is_inert(self):
        run_dir = make_run(self)
        path = run_dir / "scratch" / "result.md"
        first = pas.publish_immutable(path, "same\n")
        second = pas.publish_immutable(path, "same\n")
        self.assertEqual(first, second)
        self.assertEqual(path.read_text(encoding="utf-8"), "same\n")

    def test_republishing_different_content_is_refused_and_changes_nothing(self):
        """An immutable artifact that can be overwritten is not immutable, and
        an audit trail built on overwritable files informs nobody."""
        run_dir = make_run(self)
        path = run_dir / "scratch" / "result.md"
        pas.publish_immutable(path, "original\n")
        with self.assertRaises(pas.TrackerWriteError):
            pas.publish_immutable(path, "tampered\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "original\n")

    def test_publishing_leaves_no_temp_file_behind(self):
        run_dir = make_run(self)
        path = run_dir / "scratch" / "result.md"
        pas.publish_immutable(path, "content\n")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["result.md"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k "InitializeRun or PublishImmutable"`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'initialize_run'`

- [ ] **Step 3: Write the implementation**

Add `import hashlib` to the module header, then append:

```python
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
RUN_ARTIFACT_ROOT = "docs/superpowers/runs"
_FIRST_NEXT_ACTION = "dispatch-intent-readers"


def _link_publish(path: Path, data: bytes, what: str) -> None:
    """Write bytes then hard-link them into place, so an existing file wins.

    os.replace would overwrite a concurrent winner. os.link raises
    FileExistsError instead, which is the behaviour both a first tracker and an
    immutable artifact need.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            _sync_file(handle)
        try:
            os.link(temporary, path)
            linked = True
        except FileExistsError:
            if path.read_bytes() != data:
                raise TrackerWriteError(
                    f"{what} already exists at {path} with different content; "
                    "an immutable artifact is never overwritten"
                ) from None
    except OSError as exc:
        raise TrackerWriteError(f"cannot publish {what} at {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    if not linked:
        return
    try:
        _sync_directory(path.parent)
    except OSError as exc:
        raise UpdateOutcomeUncertain(
            f"{what} at {path} was created, then the directory sync failed; it may "
            f"or may not survive a crash: {exc}"
        ) from exc


def publish_immutable(path: str, content: str) -> str:
    """Publish content once, at a path that can never be rewritten.

    Returns the sha256 hex digest of the published bytes, which is the identity
    later phases bind a worker result, a brain response, or a payload to.
    """
    data = content.encode("utf-8")
    _link_publish(Path(path), data, "immutable artifact")
    return hashlib.sha256(data).hexdigest()


def initialize_run(run_dir: str, *, run_id: str, base_commit: str,
                   target_branch: str, worker_limit: int) -> dict:
    """Create the first tracker for a run, or refuse and change nothing."""
    run_dir = Path(run_dir)
    if not _RUN_ID.fullmatch(run_id):
        raise TrackerValidationError("invalid run id")
    if not _COMMIT.fullmatch(base_commit):
        raise TrackerValidationError("base commit must be a full 40-character sha")
    if target_branch in ("main", "master"):
        raise TrackerValidationError(
            "pipeline-auto never targets main or master: success leaves a clean "
            "committed feature branch and nothing is merged or pushed"
        )
    if int(worker_limit) < 1:
        raise TrackerValidationError("worker_limit must be at least 1")
    progress = run_dir / "progress.md"
    if progress.exists():
        raise ForeignSchemaError(
            _diagnostic(run_dir, "progress.md already exists; resume instead of initializing")
        )
    artifacts = f"{RUN_ARTIFACT_ROOT}/{run_id}"
    tracker = {
        "run": {
            "run_id": run_id,
            "schema": SCHEMA,
            "base_commit": base_commit,
            "target_branch": target_branch,
            "worker_limit": str(int(worker_limit)),
            "agent_dispatch_count": "0",
            "spec": "-",
            "master_plan": "-",
            "phase_plans": "-",
            "decisions": f"{artifacts}/decisions.md",
            "findings": f"{artifacts}/findings.md",
            "completeness_proposals": f"{artifacts}/completeness-proposals.md",
            "revision": "0",
            "last_transition": "initialized",
        },
        "stages": [
            {
                "stage": stage,
                "stage_state": "active" if stage == "01" else "pending",
                "next_action": _FIRST_NEXT_ACTION if stage == "01" else "-",
            }
            for stage in STAGES
        ],
        "intent": [], "questions": [], "quorum": [], "escalations": [],
        "tasks": [], "task_review": [], "fix_rounds": [], "phases": [], "gates": [],
    }
    text = render_tracker(tracker)
    parse_tracker(text)
    _link_publish(progress, text.encode("utf-8"), "initial tracker")
    return validate_run(run_dir)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 123 tests

- [ ] **Step 5: Commit**

```bash
git diff --name-only -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): initialize a run and publish artifacts that cannot be rewritten"
```

---

## Task 12: Templates and `scripts/sdd-workspace`

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/templates/progress.md`
- Create: `plugins/superb/skills/pipeline-auto/templates/decisions.md`
- Create: `plugins/superb/skills/pipeline-auto/scripts/sdd-workspace`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `MARKER`, `TITLE`, `_SECTIONS`, `_RUN_KEYS`.
- Produces: `templates/progress.md`, `templates/decisions.md`, and `scripts/sdd-workspace <run-dir>`, which creates `<run-dir>/scratch/` with a self-ignoring `.gitignore` and prints the directory's absolute path.

**Why `sdd-workspace` is in P02 rather than P07:** stage 12 gates completion on an empty `git status --short`, and the run writes large ephemera — briefs, implementer reports, review packages — throughout stages 08–11. P05's per-task gate needs the directory to exist before P07's prose is written. It lives **inside the run directory**, never under `.superpowers/sdd`, whose durability hole is what this hybrid exists to close. Provenance: `superpowers:subagent-driven-development/scripts/sdd-workspace`, re-pointed at the run directory.

**Named fault this task catches:** the template drifting from the renderer. A controller copying a template whose headers no longer match `_SECTIONS` produces a tracker that fails validation on its first read, at which point the run has already started.

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
import subprocess

TEMPLATES = SKILL_DIR / "templates"
SCRIPTS = SKILL_DIR / "scripts"


class TemplateTests(unittest.TestCase):
    def test_the_progress_template_matches_the_renderer_exactly(self):
        """A template that drifts from _SECTIONS produces a tracker which fails
        validation on its first read — after the run has already started."""
        lines = (TEMPLATES / "progress.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], pas.MARKER)
        self.assertEqual(lines[1], pas.TITLE)
        self.assertEqual([line for line in lines if line.startswith("## ")],
                         [heading for heading, _, _ in pas._SECTIONS])
        for _, _, header in pas._SECTIONS[1:]:
            self.assertIn("| " + " | ".join(header) + " |", lines)
        run_keys = [line.split("|")[1].strip() for line in lines
                    if line.startswith("| ") and line.split("|")[1].strip() in pas._RUN_KEYS]
        self.assertEqual(run_keys, list(pas._RUN_KEYS))

    def test_the_progress_template_lists_all_twelve_stages(self):
        text = (TEMPLATES / "progress.md").read_text(encoding="utf-8")
        for stage in pas.STAGES:
            self.assertIn(f"| {stage} | ", text)

    def test_the_decisions_template_makes_provenance_and_status_mandatory(self):
        text = (TEMPLATES / "decisions.md").read_text(encoding="utf-8")
        for required in ("## Axis Index", "- Provenance:", "- Status:", "- Action:",
                         "- Rung:", "- Depth:", "Append-only"):
            self.assertIn(required, text)

    def test_the_decisions_template_names_only_the_legal_actions(self):
        text = (TEMPLATES / "decisions.md").read_text(encoding="utf-8")
        for action in ("task.resume", "quorum.adopt", "none", "quorum.extend-budget"):
            self.assertIn(action, text)


class SddWorkspaceTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, check=True)

    def seeded_repo(self) -> tuple[Path, Path]:
        repo = Path(tempfile.mkdtemp(prefix="pipeline-auto-repo-"))
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        run_dir = repo / "docs" / "superpowers" / "runs" / "2026-09-14-example"
        run_dir.mkdir(parents=True)
        (run_dir / "progress.md").write_text("tracked\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t",
                 "commit", "-qm", "seed")
        return repo, run_dir

    def test_scratch_is_created_inside_the_run_directory_and_ignores_itself(self):
        """Stage 12 gates completion on an empty `git status --short`, and the
        run writes briefs, reports and review packages throughout stages 08-11."""
        repo, run_dir = self.seeded_repo()
        result = subprocess.run([str(SCRIPTS / "sdd-workspace"), str(run_dir)],
                                capture_output=True, text=True, check=True)
        scratch = run_dir / "scratch"
        self.assertEqual(Path(result.stdout.strip()).resolve(), scratch.resolve())
        self.assertTrue((scratch / ".gitignore").is_file())
        (scratch / "task-brief-P02-T01.md").write_text("ephemeral\n", encoding="utf-8")
        (scratch / "review-package.diff").write_text("ephemeral\n", encoding="utf-8")
        self.assertEqual(self.git(repo, "status", "--short").stdout, "")

    def test_it_is_idempotent(self):
        repo, run_dir = self.seeded_repo()
        for _ in range(2):
            subprocess.run([str(SCRIPTS / "sdd-workspace"), str(run_dir)],
                           capture_output=True, text=True, check=True)
        self.assertEqual(self.git(repo, "status", "--short").stdout, "")

    def test_it_refuses_a_run_directory_that_does_not_exist(self):
        result = subprocess.run(
            [str(SCRIPTS / "sdd-workspace"), "/nonexistent/run/dir"],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_it_refuses_to_guess_when_given_no_run_directory(self):
        result = subprocess.run([str(SCRIPTS / "sdd-workspace")],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_the_script_is_executable(self):
        self.assertTrue(os.access(SCRIPTS / "sdd-workspace", os.X_OK))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k "Template or SddWorkspace"`
Expected: FAIL — `FileNotFoundError` on `templates/progress.md`

- [ ] **Step 3: Write the templates and the script**

Create `plugins/superb/skills/pipeline-auto/templates/progress.md`:

```markdown
<!-- pipeline-auto/v1 -->
# Pipeline Auto — Progress Tracker

## Run
| Field | Value |
| --- | --- |
| run_id | <run_id> |
| schema | pipeline-auto/v1 |
| base_commit | <base_commit> |
| target_branch | <target_branch> |
| worker_limit | <worker_limit> |
| agent_dispatch_count | 0 |
| spec | - |
| master_plan | - |
| phase_plans | - |
| decisions | docs/superpowers/runs/<run_id>/decisions.md |
| findings | docs/superpowers/runs/<run_id>/findings.md |
| completeness_proposals | docs/superpowers/runs/<run_id>/completeness-proposals.md |
| revision | 0 |
| last_transition | initialized |

## Stage
| Stage | Stage State | Next Action |
| --- | --- | --- |
| 01 | active | dispatch-intent-readers |
| 02 | pending | - |
| 03 | pending | - |
| 04 | pending | - |
| 05 | pending | - |
| 06 | pending | - |
| 07 | pending | - |
| 08 | pending | - |
| 09 | pending | - |
| 10 | pending | - |
| 11 | pending | - |
| 12 | pending | - |

## Intent
| ID | Kind | State | Owner | Result | Conflicts |
| --- | --- | --- | --- | --- | --- |

## Questions
| ID | Origin | Slot | State | Decision |
| --- | --- | --- | --- | --- |

## Quorum
| QID | Axis | Phase | State | Owners | Payload Digest | Context Digest | Responses | Depth | Rung | Outcome | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Escalations
| ID | QID | Blast | State | Batch | Resolution |
| --- | --- | --- | --- | --- | --- |

## Tasks
| ID | Phase | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question | Provisional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Task Review
| Task | Attempt | Reviewer | State | Spec Verdict | Quality Verdict | Verification | Findings | Adversarial |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Fix Rounds
| Scope | Round | State | Fixer | Findings | Commits | Verification | Re-review | Remaining |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Phases
| ID | State | Verification | Review Class | Class Source | Ratchet | Gate |
| --- | --- | --- | --- | --- | --- | --- |

## Gates
| ID | Type | Phase | State | Base | Head | Assignments | Reports | Verification | Findings |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
```

Create `plugins/superb/skills/pipeline-auto/templates/decisions.md`:

```markdown
<!-- pipeline-auto/v1 -->
# Pipeline Auto — Decisions

Append-only. The one legal in-place mutation is `Status: Adopted` becoming
`Status: Superseded`. Nothing else in a recorded decision is ever edited.

Provenance is `human` or `quorum` and must be visible in three places: here, in
the tracker index, and in the terminal report. A provenance field read only by a
validator has informed nobody.

Human answers are `H-<n>`; quorum answers are `Q-<hash>`, where the hash is the
qid. Provenance therefore stays legible even if the field itself is lost.

`Action` is one of `task.resume`, `quorum.adopt`, `none`, or — only on a human
decision — `quorum.extend-budget`. A generic approval is not a decision: a
quorum answer of "proceed" is as empty as a human's.

`Rung` is `N/A` on a human decision. A human answer is depth 0 and carries no
grounding rung; rungs describe how well a *machine* answer is grounded.

## Axis Index
| Axis | Decision | Provenance | Status |
| --- | --- | --- | --- |
| <axis_id> | <decision_id> | human | Adopted |

## Decisions

### <decision_id>
- Axis: <axis_id>
- Provenance: human
- Status: Adopted
- Action: task.resume
- Question: <the question exactly as it was asked>
- Answer: <the option chosen, never a bare approval>
- Rung: N/A
- Depth: 0
- Consequences: <assertions that would be verifiably true of the repository if
  this answer were adopted — a file that would exist, a signature, a command
  that would pass; never a rationale>
- Forecloses: <what adopting this answer destroys or rules out>
- Recorded: <iso-8601 timestamp>
```

Create `plugins/superb/skills/pipeline-auto/scripts/sdd-workspace`:

```bash
#!/usr/bin/env bash
# Create and print the scratch directory a pipeline-auto run uses for its
# short-lived artifacts: task briefs, implementer reports, review packages,
# brain payloads and responses.
#
# It lives INSIDE the run directory, not under .superpowers/sdd. A workspace
# outside the run directory is not covered by the run's own durability or
# recovery story, and that durability hole is exactly what this skill exists
# to close. A self-ignoring .gitignore keeps the whole directory out of
# `git status --short`, which gates completion at stage 12, without modifying
# any tracked file.
#
# Provenance: superpowers:subagent-driven-development/scripts/sdd-workspace,
# re-pointed from the repository root to the run directory.
#
# Usage: sdd-workspace <run-dir>
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: sdd-workspace <run-dir>" >&2
  exit 2
fi

run_dir=$1
if [ ! -d "$run_dir" ]; then
  echo "sdd-workspace: run directory does not exist: $run_dir" >&2
  exit 1
fi

dir="$run_dir/scratch"
mkdir -p "$dir"
printf '*\n' > "$dir/.gitignore"
cd "$dir" && pwd
```

Make it executable:

```bash
chmod +x plugins/superb/skills/pipeline-auto/scripts/sdd-workspace
```

- [ ] **Step 4: Run the whole suite to verify everything passes**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS, 132 tests

- [ ] **Step 5: Run the phase verification suite**

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
python3 -c "import ast; ast.parse(open('plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py').read())"
git diff --name-only -- plugins/superb/skills/pipeline/
git status --short
```

The third command must print nothing. The fourth must show only the new `pipeline-auto` files.

- [ ] **Step 6: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): add tracker and decisions templates and the run-local scratch workspace"
```

---

## Named faults, and which test catches each

Every entry is an exact source edit someone could plausibly make. Each is caught by a test nothing else catches.

| Fault | Test |
| --- | --- |
| Delete the marker check in `validate_run`, so a `pipeline-run/v2` tracker is accepted and then mutated | `ForeignSchemaStopTests.test_a_pipeline_run_v2_tracker_is_rejected_and_left_byte_identical` — feeds the existing `superb:pipeline` fixture bytes, asserts `ForeignSchemaError` **and** that the file is byte-identical afterwards |
| `render_tracker` drops a column while `parse_tracker` still accepts the shorter header, silently losing a cell on every write | `RoundTripTests.test_render_of_a_parse_is_byte_identical_to_the_fixture` — byte comparison against the fully-populated fixture |
| `_replace_tracker` writes its temp file outside the run directory, so `os.replace` crosses filesystems and stops being atomic | `ReplaceTrackerTests.test_the_file_being_renamed_lives_in_the_run_directory` — asserts the renamed file's parent **and** its `st_dev` |
| Both sync failures caught under one `except`, so a post-replace directory-sync failure raises `TrackerWriteError` instead of `UpdateOutcomeUncertain` | `ReplaceTrackerTests.test_a_post_replace_failure_raises_update_outcome_uncertain` plus its pre-replace twin, which pins the other side of the boundary |
| A replayed `transition_id` mutates instead of returning current state | `LockedUpdateTests.test_a_replayed_transition_returns_current_state_without_mutating` — asserts `mutate` was never called, bytes unchanged, revision unchanged |
| A compaction during stage 02 lets stage 01 read `pending`, so a resuming controller re-runs it | `StageSectionTests.test_a_pending_stage_before_an_active_one_is_rejected` |
| The ratchet is made two-way, letting a phase drop from `required` to `final-only` | `PhaseSectionTests.test_the_ratchet_is_one_way` |
| An out-of-enum rung is defaulted to a legal value instead of being schema-invalid | `QuorumSectionTests.test_a_rung_outside_the_enum_is_schema_invalid` |
| A task's own implementer reviews it | `TaskReviewSectionTests.test_a_tasks_own_implementer_cannot_review_it` |
| The fix loop closes on a round that still lists findings | `FixRoundSectionTests.test_the_loop_closes_only_on_a_round_with_zero_remaining_findings` |
| `## Remediation` is re-added and silently ignored | `RoundTripTests.test_a_remediation_section_is_rejected_rather_than_ignored` |
| A missing lock primitive falls back to "proceed without a lock" | `LockTests.test_no_os_lock_primitive_is_an_explicit_failure_not_a_silent_no_lock` |
| The template drifts from the renderer, so a controller-copied tracker fails on first read | `TemplateTests.test_the_progress_template_matches_the_renderer_exactly` |
| `scratch/` stops ignoring itself, so stage 12's `git status --short` gate never passes | `SddWorkspaceTests.test_scratch_is_created_inside_the_run_directory_and_ignores_itself` |

## Deliberately not ported from `superb:pipeline`

These exist in `pipeline/scripts/pipeline_state.py` and are **not** reimplemented here. They serve rules this skill dropped, or are scar tissue keyed to one historical run.

- the pre-adoption parser and `adopt_pre_release_tracker`
- `seal_active_master_round_one`, `reconcile_active_rebuild_round_one_outcome`
- `_LEGACY_TASK`, `_recognized_v1` — `pipeline-auto` needs no legacy *recognizer*; any first line that is not `MARKER` is foreign, which is both simpler and stricter
- `_filesystem_ack` and the acknowledgement plumbing
- `## Remediation` and every rule attached to it

`pipeline/tests/test_pipeline_state.py` (6836 lines) is **not** ported. The inheritance that matters is the method its fixtures README states: invalid input must be byte-identical after a rejected parse. Every rejection test above asserts that.

## Self-review

**Spec coverage.** The master plan assigns P02 the state schema and governing invariant 4 ("files are the authority"). Walking the spec's `State schema` section: the family name and the no-migration rule are Task 1 and Task 2; the read-only stop with a diagnostic naming the other skill is Task 2; the run-artifact convention and the self-ignoring `scratch/` inside the run directory are Tasks 11 and 12; `## Stage` is Task 3; `## Intent`, `## Questions`, `## Escalations` are Task 4; `## Quorum` is Task 5; `## Tasks` gaining `Provisional` and `## Phases` gaining `Review Class`, `Class Source`, `Ratchet` are Task 6; `## Task Review` and `## Fix Rounds` are Task 7; `## Remediation` being dropped is Task 1; the `decisions.md` axis index, `Provenance`, append-only rule and narrowed action set are Task 12's template, with the parser and its validation belonging to P03 as the master plan assigns. Every signature in the master plan's "P02 produces" block has a task: `parse_tracker`/`render_tracker` (1), `validate_run` (2), `derive_next_action` (3), `locked_tracker_update` (10), `initialize_run` and `publish_immutable` (11), and all six exception classes (1).

**Placeholder scan.** No TBDs, no "add validation", no "similar to Task N", no reference to a function no task defines. Every code step carries the code.

**Type consistency.** `parse_tracker` returns `dict`; every validator takes that `dict` and returns `None`, raising on failure. `render_tracker` takes the same `dict` and returns `str`. `validate_run`, `initialize_run` and `locked_tracker_update` all return the same `dict` shape, and `locked_tracker_update` returns the **reparsed** one so a caller can never hold state that has not survived a round trip. `publish_immutable` returns `str` — a sha256 hex digest. `derive_next_action` takes a tracker `dict`, not a `run_dir`, matching the master plan exactly. `select_lock_impl` returns `(acquire, release, description)`. `RUNG_NAMES` is a tuple of names ordered lowest grounding first; P03's `RUNGS` maps those names to floats, consistent with the master plan's note that the rung accessor returns a name, not a value.

**Task count.** Twelve genuine tasks, each ending in an independently testable deliverable and a commit.

**Two adjustments made during review.** The lock exceptions were originally standalone; they became `TrackerWriteError` subclasses so the master plan's five-exception contract stays exact while callers can still tell contention from a missing primitive. And `## Tasks` gained a `Phase` column, because the drift budget is per phase and the ratchet is per phase, and without it neither count can be derived from the tracker at all.

## Unresolved — reported, not invented

Each of these is a decision the spec and master plan do not contain. P02 does not invent them; where P02 had to act to stay implementable, what it did is stated so it can be corrected.

1. **`PlanMetadataError` has no raiser in any phase's interface block.** The master plan places it in "P02 produces", but no P02 function parses phase-plan metadata, and no phase block names a `parse_plan_metadata` signature. P02 defines the class exactly as specified and raises it nowhere. Whichever phase reads `review_class` out of phase-plan metadata — P05 by the deliverable table — needs that signature added to the master plan.

2. **`publish_immutable(path, content) -> str` does not say what the string is.** This plan returns the sha256 hex digest of the published bytes, because P03 binds brain responses to a payload digest and P04 binds worker results to a four-part identity, and the path is something the caller already has. If it was meant to be the path, P03 and P04 will need a separate digest helper.

3. **The run-level inflation check records an adjustment with nowhere to put it.** The spec says that after five or more adopted events with a mean above 0.90, "the adoption floor rises one tier for the rest of the run and the adjustment is recorded" — while also forbidding the floor from appearing in `## Run` as a tunable. No section or field is named for the recorded adjustment. P02 adds neither, so P03 currently has no durable place to write it.

4. **`Decision action` has four values in the spec and three in the same spec.** The `State schema` section says actions "narrow to `task.resume | quorum.adopt | none`", and the `Budget extension` section requires `Decision action: quorum.extend-budget`. P02's `decisions.md` template lists all four and marks `quorum.extend-budget` as human-only. P03 owns the validator and needs the contradiction settled.

5. **No phase owns executable filesystem classification.** The spec's recorded defaults make an unclassified filesystem a read-only stop, but the master plan's self-review routes recorded defaults to P07 prose and P04, and no interface block carries a `classify_filesystem` signature. P02 implements none, so no phase currently enforces that stop.

6. **`pytest` is not installed in this environment and is a third-party dependency.** The master plan's Tech Stack names pytest while its Global Constraints say standard library only, no new dependencies in any phase. The tests here are `unittest.TestCase` classes, which pytest collects unchanged, so both commands work wherever pytest exists — but this phase's verification tuple uses `python3 -m unittest discover`, which is the form that runs under the stated constraint.

7. **The `Blast` vocabulary is unenumerated.** Escalations are "ranked by blast radius" and adoption checks every `blast` entry against the closed irreversible-axis list, but no document gives the token set. P02 validates `Blast` as a token only; P06 needs the vocabulary named before it can rank or compare.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/pipeline-auto/phase-02-schema-core.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.
