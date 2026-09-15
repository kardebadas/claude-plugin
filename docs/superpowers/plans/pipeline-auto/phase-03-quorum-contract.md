# P03 — Quorum Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the quorum machinery of `pipeline_auto_state.py` — qid derivation, the brain-response schema validator, grounding-rung recomputation from *resolved* evidence, the three-phase quorum record, contradiction detection against `decisions.md`, depth, and the drift budget — so a three-agent quorum can adopt a decision only when the evidence, not the headcount and not a self-reported number, says it may.

**Architecture:** All quorum state is files under `<run_dir>/quorum/`, because spec invariant 4 makes files the authority and an interruption must be classifiable from disk alone. The record has three separately-durable phases: `open.json` (owners, per-brain payload digests, the shared question digest, and the context digest, published **before** dispatch), `responses/<owner>__<attempt>.json` (one immutable file per response), and `final.json` (the computed outcome). Only the third goes through P02's tracker lock, with `transition_id = "quorum-" + qid`, so replay-is-inert semantics protect the one transition that changes run state. A brain never types a number: it selects a rung name, the controller resolves its evidence with a real file read, demotes on failure, and derives the value from `RUNGS`.

**Tech Stack:** Python 3 standard library only (`hashlib`, `json`, `pathlib`, `re`, `types.MappingProxyType`). `pytest` for tests. Markdown for `decisions.md` and the findings ledger; JSON for quorum records and brain payloads.

**Spec:** `docs/superpowers/specs/2026-09-14-pipeline-auto-design.md` — "The quorum contract" (lines 112–401) and "Failure modes and mitigations" (lines 497–562)

**Master plan:** `docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md` — Global Constraints and the "P03 produces" block

**Depends on:** P02 (`schema-core`). Its produced signatures are assumed to exist and work.

**Review class:** `required`

---

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

### P03-specific standing rules

Each of these has at least one test in this plan. They are restated here because
each is a rule a reasonable engineer would "simplify" into a bug.

1. **Never write a numeric spread threshold.** If `spread >= 0.15`, `margin`, or any float comparison between two clusters appears anywhere in this phase, you have made the exact error the phase exists to prevent. Spread is `RUNG_ORDER.index(winner) < RUNG_ORDER.index(runner_up)` and nothing else.
2. **Never write `RUNGS.get(rung, 0.55)`** or any `dict.get` with a default over the rung enum. `0.55` is already in the module for the demotion rule, so defaulting to it looks principled and reads as defensive. It silently converts every malformed response into a legal vote. An unknown rung raises.
3. A cluster's rung is the **maximum** member rung. Never a mean, never a sum, never headcount-weighted.
4. Two-of-three agreement is never on its own a reason to adopt.
5. Rung *names* may appear in a brain payload. Rung *values*, the adoption floor, the budget, the raiser's identity, and the raiser's candidate answers may not.
6. Escalation never decrements the drift budget. Only adoption does.
7. The controller never asks a brain to reconsider its confidence, never dispatches a fourth brain, and never synthesises an answer of its own.
8. **Never compute a repository root.** It is a `## Run` field; read it with P02's `repo_root(tracker)` and pass it to `effective_rung(response, repo_root)`. Deriving it from directory depth is a guess about where a run directory sits relative to the repository, and today that guess is wrong — runs live at `docs/superpowers/runs/<run-id>/`, which is `parents[3]`. **The failure shape is why this is a standing rule rather than a detail:** a wrong root resolves no citation, so every `specified` and `code-evidenced` answer demotes to `engineering-judgement` at 0.55, so everything lands below the 0.85 floor, so the run escalates every single question — while looking like a correctly cautious quorum. No error, no exception, no failing test. The skill would appear to work and would be useless.
9. **Never test membership of a brain-supplied value with a bare `in` against a set.** `x in frozenset(...)` HASHES `x`, and a JSON value may legally be a list or an object, both unhashable. The `TypeError` is outside `TrackerError`, so it escapes every handler a controller has written and kills the run on a brain's typo. Use `_member(value, allowed)` — `isinstance(value, str) and value in allowed` — which accepts exactly what a bare `in` accepted and returns `False` instead of raising on the rest. **And pin every call site**: reverting `_member` to a bare `in` must fail the suite. The Task 3 review found this escape in `effective_rung`; the verification pass then found three more sites in `validate_brain_response` where the source was already right and nothing would have noticed if it stopped being. A correct line with no test is a line that will be "simplified".
10. **A totality test must derive its case list from the function body, not from memory.** `test_a_malformed_response_never_escapes_the_tracker_error_family` claimed "any JSON value at all, in any of the fields this function reads", listed fourteen payloads, and never varied `kind` — the one field that crashed. Enumerate the reads from the call tree, then vary each with both an unhashable value and a wrong-typed scalar.

---

## File Structure

| File | Responsibility | P03 action |
| --- | --- | --- |
| `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py` | The spine. P03 appends its quorum section below P02's schema core; P03 adds no new module | Modify |
| `plugins/superb/skills/pipeline-auto/templates/findings.md` | Findings ledger, carrying the fixer-dispute adjudication column — an adjudication is a factual question and never enters `decisions.md` | Create |
| `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py` | Unit tests; P03 appends its own `class Quorum*` test classes | Modify |
| `plugins/superb/skills/pipeline-auto/tests/fixtures/quorum/` | Question records, brain responses, and the small repo tree evidence resolves against | Create |

P03 creates **no** prose, **no** agent file, **no** prompt template. `prompts/brain.md` is P07's; P03's `build_payload` is the machine that fills it and `validate_brain_response` is the gate that judges what comes back. P07's `templates/decisions.md` must emit the grammar P03's `parse_decisions` accepts.

### Durable layout P03 owns

```text
<run_dir>/
├── decisions.md                      # P03 parses, validates, and appends to (append-only)
├── decisions-effective.md            # generated read-only projection handed to brains
└── quorum/
    ├── floor.json                    # adoption floor for this run; rises on inflation, never falls
    ├── extensions.json               # pinned, human-granted budget extensions
    └── <qid>/
        ├── open.json                 # phase 1: owners, digests, context digest — BEFORE dispatch
        ├── payload-<owner>.json      # the exact bytes that brain received;
        │                              # one digest in open.json binds all three
        ├── responses/
        │   ├── <owner>__1.json       # phase 2: one immutable file per response
        │   └── <owner>__2.json       # exists only after the single permitted re-dispatch
        └── final.json                # phase 3: the computed outcome
```

---

## Carried forward from P02 Task 5 (commit `687bacc`)

Three things P02 settled that this phase must not re-decide or contradict.

**Build `RUNGS` over `RUNG_NAMES`; do not redefine it.** P02 owns the five rung
names and asserts membership directly — there is no `.get(..., default)` and no
fallback anywhere in the module, because `RUNGS.get(rung_id, 0.55)` silently
converts every malformed response into an engineering-judgement vote, and 0.55 is
a legal value arriving through an illegal door. A second definition here would
let the two drift apart, which is the same hole with an extra step.

**The question `ID` column now carries three roles** — intent-conflict id (Task 4
made the claim referential), axis token, and quorum axis namespace. Confirm that
is what `derive_qid` hashes before writing it. If the qid should hash something
narrower, say so rather than hashing a column whose meaning depends on which
validator is reading it.

**A `## Questions` id may itself be the literal `new`.** `_validate_questions`
checks uniqueness only, so a question named `new` is indistinguishable from the
reserved axis literal at `pipeline_auto_state.py:786`. Found in Task 5's review
and left to this phase deliberately. Either reserve `new` as an illegal question
id, or make the axis check distinguish "the literal" from "a question that
happens to be called that" — but do not leave both readings live.

**`new` is a by-construction hole in the contradiction check**, and the schema
cannot close it. A free-token axis clears the check by being unrecognisable — the
same fail-open shape `_BLAST_RADII` is closed against. P02 set the fixture's
adopted-row axis to the literal `new` because it is legal under both the
referential and free-token readings. If this phase's contradiction detection
depends on the axis being resolvable, reject `new` explicitly rather than assume
a namespace it will not get.

## Interfaces

### Consumes from P02 — assumed to exist and work

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
def validate_run(run_dir: Path) -> dict: ...          # Path, and never coerced
def initialize_run(run_dir: Path, *, run_id: str, base_commit: str,
                   target_branch: str, worker_limit: int,
                   repo_root: str) -> dict: ...            # repo_root is REQUIRED
def classify_filesystem(path: str) -> str: ...             # unknown => the run does not start
def locked_tracker_update(run_dir: str, *, transition_id: str, mutate) -> dict: ...
def publish_immutable(path: str, content: str) -> str: ...
def derive_next_action(tracker: dict) -> str: ...

def repo_root(tracker: dict) -> str: ...            # the `## Run` field; NEVER derived
def section_columns(name: str) -> tuple[str, ...]: ...
def append_row(tracker: dict, section: str, row: dict) -> dict: ...
```

Three behaviours P03 depends on and must not re-implement:

- `locked_tracker_update` validates, takes an exclusive lock, re-reads, revalidates, applies `mutate`, renders, reparses, atomically replaces. **A replayed `transition_id` returns current state without calling `mutate` at all.** That is what makes `finalize_quorum` replay-inert.
- `publish_immutable(path, content)` writes once; a byte-identical second call is a no-op returning the same path; a differing second call raises. That is what makes every response file and `final.json` a single-assignment cell.
- `repo_root(tracker)` returns the `## Run` field that `initialize_run` recorded. **P03 never computes a repository root** — not by `parents[N]`, not by walking for `.git`. See the standing rule below; this is the single most dangerous line in the phase.

P03 owns the quorum lifecycle, so **P03 writes its own `## Quorum` and `## Escalations` rows**, through `section_columns` and `append_row`, inside `locked_tracker_update`. No phase writes another phase's rows and no phase re-declares another phase's columns: every row P03 builds is checked against `section_columns(...)` before the write, so a column change in P02 breaks loudly at the seam instead of drifting into a mismatched write.

### Produces — consumed by P05 and P06

Names marked **(master plan)** are verbatim from the master plan's "P03 produces" block and may not be renamed. Names marked **(P03)** are additions; `## Unresolved` says why each was needed.

```python
RUNGS = MappingProxyType({"specified": 0.95, "code-evidenced": 0.85,
                          "convention-cited": 0.70, "engineering-judgement": 0.55,
                          "speculation": 0.30})                     # (master plan) frozen; NOT run config
ADOPTION_FLOOR = 0.85                                                # (master plan)
DEPTH_CAP = 2                                                        # (master plan)
BUDGET_PER_PHASE = 3                                                 # (master plan)
BUDGET_PER_RUN = 10                                                  # (master plan)
MAX_EXTENSIONS = 2                                                   # (master plan)

def derive_qid(question: str, axis: str) -> str: ...                 # (master plan)
def effective_rung(response: dict, repo_root: str) -> str: ...       # (master plan) returns a RUNG NAME
def cluster_rung(cluster: list) -> str: ...                          # (master plan) MAX member rung
def build_payload(qid: str, brain_index: int, *, run_dir: str) -> dict: ...  # (master plan) pure w.r.t. brain_index
def payload_digest(qid: str, *, run_dir: str) -> str: ...            # (P03) ONE digest binding all three
def project_decisions(decisions: dict) -> str: ...                   # (master plan)
def open_quorum(run_dir: str, *, question_record: str) -> dict: ...  # (master plan)
def record_brain_response(run_dir: str, *, qid: str, owner: str,
                          payload: dict) -> str: ...                 # (master plan)
def finalize_quorum(run_dir: str, *, qid: str) -> dict: ...          # (master plan)
def check_contradiction(decisions: dict, candidate: dict) -> str | None: ...  # (master plan)
def decision_depth(decisions: dict, consistent_with: list) -> int: ...# (master plan)

RUNG_ORDER: tuple[str, ...]      # highest rung first; all comparisons use index, never value  (P03)
DEMOTION_RUNG = "engineering-judgement"                              # (P03)
ADOPTABLE: frozenset[str]        # {"specified", "code-evidenced"}                             (P03)
IRREVERSIBLE_AXES: frozenset[str]                                    # (P03)
READING_ASSIGNMENTS: tuple[dict, ...]   # exactly three, source-biased, index-addressed        (P03)

class QuorumError(TrackerError): ...                                 # (P03)
class QuorumSchemaInvalid(QuorumError): ...                          # (P03)
class QuorumIncomplete(QuorumError): ...                             # (P03)

def validate_brain_response(payload: dict) -> list[str]: ...         # (P03)
def parse_decisions(text: str) -> dict: ...                          # (P03)
def check_admissible(record: dict) -> list[str]: ...                 # (P03)
def group_responses(responses: list, *, options_supplied: bool) -> tuple[list, dict]: ...  # (P03)
def classify_quorum(run_dir: str, *, qid: str, live_owners: list) -> dict: ...  # (P03)
def quorum_needs_redispatch(run_dir: str, *, qid: str) -> list[str]: ...  # (P03)
def quorum_events(run_dir: str) -> list[dict]: ...                   # (P03)
def quorum_budget(run_dir: str, *, phase: str) -> dict: ...          # (P03)
def current_floor(run_dir: str) -> dict: ...                         # (P03)
def quorum_tracker_rows(run_dir: str) -> list[dict]: ...             # (P03) built against section_columns("Quorum")
```

**Type notes for downstream implementers.** `effective_rung` and `cluster_rung` return a **rung name** (`str`), never a float; callers look the value up in `RUNGS`. `check_contradiction` returns the offending **D-ID** or `None`, never a boolean. `classify_quorum().state` is one of `finalised`, `ready-to-finalise`, `awaiting-responses`, `redispatch`, `stale-context`. `finalize_quorum().status` is one of `adopted`, `escalated`, `rejected-contradicts-human`, `rejected-contradicts-quorum`, `question-not-decidable`. `open_quorum().status` is one of `in_flight`, `adopted`, `escalated`.

---

## Data contracts P03 defines

The master plan names the functions, not the shapes. These are P03's; P07's prompts and templates must conform to them.

### Question record — published by the raising worker, input to `open_quorum`

```json
{
  "question": "Which storage engine backs the session table?",
  "axis": "storage-engine",
  "phase": "P04",
  "blocks": ["T04"],
  "raiser": "worker-7",
  "options_supplied": true,
  "options": [{"key": "postgres"}, {"key": "sqlite"}],
  "candidate_answers": ["postgres because we already run it"],
  "recommendation": "postgres",
  "reading_roots": {"spec": "docs/superpowers/specs/2026-09-14-pipeline-auto-design.md",
                    "intent-brief": "intent-brief.md", "repo": ".", "tests": "tests",
                    "decisions-effective": "decisions-effective.md",
                    "phase-plan": "docs/superpowers/plans/pipeline-auto/phase-04-task-lifecycle.md"},
  "owners": ["brain-a", "brain-b", "brain-c"]
}
```

`candidate_answers`, `recommendation` and `raiser` exist **so `build_payload` can be proved to drop them.** They are recorded for audit and are structurally unreachable from the payload builder.

`options` are *not* "the raiser's candidate options" the spec prohibits. The
prohibition is on the raiser's preferred answers and recommendation; the named
options are part of the question itself — admissibility criterion 4 requires
them, and `answer_key` comparison is defined against them. The distinction is
load-bearing and is why `build_payload` whitelists `options` while excluding
`candidate_answers`.

### Brain response — strict JSON, every key required, no others permitted

```json
{
  "qid": "a1b2c3d4e5f6",
  "answer_key": "postgres",
  "answer": "Back the session table with the existing PostgreSQL instance.",
  "rung": "code-evidenced",
  "evidence": [{"kind": "repo", "path": "db/engine.py", "line": 12, "quote": "PostgresEngine"}],
  "consequences": [{"kind": "file-exists", "subject": "db/session.sql", "value": "present"}],
  "consistent_with": [{"kind": "decision", "id": "H-001"}],
  "forecloses": ["a filesystem-only deployment"],
  "blast": ["storage-engine"],
  "alternatives": [{"answer_key": "sqlite", "rung": "engineering-judgement",
                    "reason": "no concurrent-writer story"}],
  "what_would_change_my_mind": "A decision record pinning the run to a single-file database.",
  "blocker": null
}
```

There is **no** `confidence`, `score`, or `certainty` field, and no field a brain could use to raise a question of its own — the only exit is `blocker`. Any unknown key fails validation, which is how a brain that types a number is caught.

`evidence[*].kind` is `spec`, `intent-brief`, `decision`, or `repo`; a `decision` item carries `decision` in place of `line`. `consistent_with[*].kind` is `decision`, `spec`, or `repo`. `consequences[*].kind` is one of `file-exists`, `signature`, `command-passes`, `config-value` — an assertion that would be verifiably true of the repository if the answer were adopted, never a rationale.

### `decisions.md` record grammar — P03 parses it, P07's template must emit it

```markdown
## H-001 — Session storage

- **Question:** Which storage engine backs the session table?
- **Axis:** storage-engine
- **Answer:** postgres — Back the session table with the existing PostgreSQL instance.
- **Decision action:** none
- **Provenance:** human
- **Depth:** 0
- **Consequences:** file-exists:db/session.sql=present
- **Scope:** T04
- **Status:** Adopted
```

A quorum record adds `Grounding rung`, `Runner-up rung`, `Consistent with`, `Forecloses` and `Context digest`, and carries `## Q-<qid>`, `Provenance: quorum`, `Decision action: quorum.adopt`.

A budget extension carries `Decision action: quorum.extend-budget`, `Provenance: human`, and all of `Authorized run`, `Source revision`, `Authorized through`, `Granted against`.

---

## Verification suite for this phase

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The second command must print **nothing**. Any output means `skills/pipeline/` was modified and the phase fails.

### Test module bootstrap

The skill directory is `pipeline-auto`, which is not a legal Python identifier, so the test module loads the spine by path. P02 should already have written this block; if it has not, add it as the first thing in Task 1.

```python
import importlib.util
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[5]
SPINE = REPOSITORY / "plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py"
_spec = importlib.util.spec_from_file_location("pipeline_auto_state", SPINE)
pipeline_auto_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline_auto_state)
```

### Shared test helpers — add these once, in Task 1, below the bootstrap

```python
import contextlib, hashlib, json, tempfile, unittest
from pathlib import Path

RUN_ID = "2026-09-14-quorum-tests"
BASE = "0" * 40


def quorum_run(stack):
    """A run at its REAL depth under a repo root, with repo_root asserted.

    Named `quorum_run`, not `new_run`: `new_run(case, **overrides)` already
    exists at `test_pipeline_auto_state.py:4570` and takes a TestCase. A case
    wanting `addCleanup` rather than an ExitStack should call the equivalent
    `repo_with_a_run(case, layout=...)` (added by Task 3, ~line 6648), which
    builds the same production-depth layout AND writes a real cited file.

    The layout is the production one — docs/superpowers/runs/<run-id>/ — so any
    phase tempted to derive the root from directory depth gets `parents[3]`, not
    `parents[0]`, and the assertion below is the seam where a disagreement with
    P02 surfaces immediately instead of silently demoting every citation.
    """
    root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
    (root / ".git").mkdir()
    run_dir = root / "docs" / "superpowers" / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    pipeline_auto_state.initialize_run(
        run_dir, run_id=RUN_ID, base_commit=BASE,
        target_branch="feat/pipeline-auto", worker_limit=4,
        repo_root=str(root),
    )
    (run_dir / "decisions.md").write_text("<!-- pipeline-auto-decisions/v1 -->\n", encoding="utf-8")
    recorded = pipeline_auto_state.repo_root(pipeline_auto_state.validate_run(run_dir))
    assert Path(recorded).resolve() == root.resolve(), (
        f"P02 recorded repo_root {recorded!r}; the tests assume {str(root)!r}")
    return root, run_dir


def response(**overrides):
    """A valid, grounded brain response; override exactly the field under test."""
    base = {
        "qid": "0" * 12,
        "answer_key": "postgres",
        "answer": "Use the existing PostgreSQL instance.",
        "rung": "code-evidenced",
        "evidence": [{"kind": "repo", "path": "db/engine.py", "line": 1, "quote": "PostgresEngine"}],
        "consequences": [{"kind": "file-exists", "subject": "db/session.sql", "value": "present"}],
        "consistent_with": [{"kind": "decision", "id": "H-001"}],
        "forecloses": ["a filesystem-only deployment"],
        "blast": ["storage-engine"],
        "alternatives": [{"answer_key": "sqlite", "rung": "speculation", "reason": "no concurrent writers"}],
        "what_would_change_my_mind": "A decision pinning the run to a single-file database.",
        "blocker": None,
    }
    base.update(overrides)
    return base


def write_repo(root, relpath, text):
    path = Path(root) / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
```

---
## Tasks

### Task 1: Frozen rung ladder and qid derivation

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py` (append a `# --- quorum ---` section below P02's code)
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: P02's `SCHEMA`, `TrackerError`, `render_tracker`, `initialize_run`
- Produces: `RUNGS`, `RUNG_ORDER`, `ADOPTION_FLOOR`, `DEMOTION_RUNG`, `ADOPTABLE`, `DEPTH_CAP`, `BUDGET_PER_PHASE`, `BUDGET_PER_RUN`, `MAX_EXTENSIONS`, `IRREVERSIBLE_AXES`, `QuorumError`, `QuorumSchemaInvalid`, `QuorumIncomplete`, `derive_qid`

The rung values live beside `SCHEMA` as a `MappingProxyType` and never enter the tracker's `## Run` section. A controller that can edit its own adoption bar has no adoption bar; freezing the mapping makes the self-serving move fail at the language level rather than at review.

`derive_qid` deliberately excludes the decisions digest. Including it would give the same question a new identity every time anything else was decided, and the run would re-litigate itself after every compaction.

- [ ] **Step 1: Write the failing tests**

```python
class QuorumConstants(unittest.TestCase):
    def test_rungs_are_frozen_schema_constants(self):
        with self.assertRaises(TypeError):
            pipeline_auto_state.RUNGS["specified"] = 0.99
        self.assertEqual(pipeline_auto_state.RUNGS["specified"], 0.95)
        self.assertEqual(pipeline_auto_state.RUNGS["code-evidenced"], 0.85)
        self.assertEqual(pipeline_auto_state.RUNGS["convention-cited"], 0.70)
        self.assertEqual(pipeline_auto_state.RUNGS["engineering-judgement"], 0.55)
        self.assertEqual(pipeline_auto_state.RUNGS["speculation"], 0.30)
        self.assertEqual(pipeline_auto_state.ADOPTION_FLOOR, 0.85)

    def test_rung_values_never_reach_the_tracker(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = quorum_run(stack)
            rendered = (run_dir / "progress.md").read_text(encoding="utf-8")
        for value in ("0.95", "0.85", "0.70", "0.55", "0.30"):
            self.assertNotIn(value, rendered)

    def test_rung_order_is_high_to_low_and_adoptable_stops_at_the_floor(self):
        self.assertEqual(
            pipeline_auto_state.RUNG_ORDER,
            ("specified", "code-evidenced", "convention-cited",
             "engineering-judgement", "speculation"),
        )
        self.assertEqual(pipeline_auto_state.ADOPTABLE, frozenset({"specified", "code-evidenced"}))
        self.assertEqual(pipeline_auto_state.DEMOTION_RUNG, "engineering-judgement")


class DeriveQid(unittest.TestCase):
    def test_normalizes_whitespace_and_case_but_not_axis(self):
        a = pipeline_auto_state.derive_qid("Which storage engine?", "storage-engine")
        b = pipeline_auto_state.derive_qid("  which   STORAGE\n engine? ", "storage-engine")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 12)
        self.assertNotEqual(a, pipeline_auto_state.derive_qid("Which storage engine?", "Storage-Engine"))
        self.assertNotEqual(a, pipeline_auto_state.derive_qid("Which storage engine?", "new"))

    def test_qid_is_independent_of_the_decisions_digest(self):
        # THE COMPACTION-REPLAY SEED. A qid that moves when anything else is
        # decided makes every re-raise a new question and the run re-litigates
        # itself. derive_qid takes no context and must take none.
        with self.assertRaises(TypeError):
            pipeline_auto_state.derive_qid("Which storage engine?", "storage-engine", "deadbeef")
        expected = hashlib.sha256(b"which storage engine?\x00storage-engine").hexdigest()[:12]
        self.assertEqual(pipeline_auto_state.derive_qid("Which storage engine?", "storage-engine"), expected)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k QuorumConstants -k DeriveQid -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'RUNGS'`

- [ ] **Step 3: Write the implementation**

```python
# --------------------------------------------------------------------------
# Quorum contract (P03)
# --------------------------------------------------------------------------
# The five rung values are SCHEMA CONSTANTS, frozen beside SCHEMA. They are not
# run configuration and never appear in the tracker's ## Run section: a
# controller able to lower its own adoption bar has no bar. See the spec,
# "Confidence by grounding tier".

RUNGS = MappingProxyType({
    "specified": 0.95,
    "code-evidenced": 0.85,
    "convention-cited": 0.70,
    "engineering-judgement": 0.55,
    "speculation": 0.30,
})
RUNG_ORDER = ("specified", "code-evidenced", "convention-cited",
              "engineering-judgement", "speculation")
ADOPTION_FLOOR = 0.85
DEMOTION_RUNG = "engineering-judgement"
ADOPTABLE = frozenset({"specified", "code-evidenced"})
DEPTH_CAP = 2
BUDGET_PER_PHASE = 3
BUDGET_PER_RUN = 10
MAX_EXTENSIONS = 2

IRREVERSIBLE_AXES = frozenset({
    "product-scope", "destructive-data", "schema-migration", "external-service",
    "paid-dependency", "public-api", "wire-format", "authn-model", "authz-model",
    "runtime-cost", "licensing", "writes-outside-repo",
})


class QuorumError(TrackerError):
    """A quorum record is unusable."""


class QuorumSchemaInvalid(QuorumError):
    """A brain response violates the response schema; it is never repaired."""


class QuorumIncomplete(QuorumError):
    """The quorum cannot be finalised yet; the controller owes a dispatch."""


def _squash(text) -> str:
    return " ".join(str(text).split()).casefold()


def derive_qid(question: str, axis: str) -> str:
    """Stable identity for one question on one axis.

    The decisions digest is deliberately NOT an input. Including it would give
    the same question a new identity whenever anything else was decided, so a
    re-raise after a compaction would dispatch a second quorum and the run would
    re-litigate ground it had already settled. Context is recorded separately as
    `context_digest` for audit.
    """
    payload = _squash(question).encode("utf-8") + b"\x00" + axis.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]
```

Add `from types import MappingProxyType` and `import hashlib`, `import json`, `import re` to the module imports if P02 has not already.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k QuorumConstants -k DeriveQid -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): freeze the rung ladder and derive context-free qids"
```

---

> **Corrected after `497cad8` and `268f712`.** `repo_root` is now a REQUIRED
> keyword of `initialize_run` and a `## Run` field; `validate_run` takes a `Path`
> and never coerces it; `section_columns`, `append_row` and `classify_filesystem`
> now exist. The signatures and the `quorum_run` helper above were written against
> a module where none of that was true, and the old call raises `TypeError`.
> Copy from the corrected forms, not from memory of an earlier task.

### Task 2: Strict brain-response schema validator

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `RUNGS`
- Produces: `validate_brain_response(payload: dict) -> list[str]` — a list of violation strings, empty when valid

The validator is strict in both directions: every known key must be present, and no unknown key may be. Unknown-key rejection is what catches a brain that types a number, because `confidence`, `score` and `certainty` are exactly the keys such a brain invents. The validator does **not** judge grounding — an empty falsifier is schema-valid and is punished later by demotion, while an empty `alternatives` list is a schema violation with a reserved code that drives the single permitted re-dispatch.

- [ ] **Step 1: Write the failing tests**

```python
class ValidateBrainResponse(unittest.TestCase):
    def test_a_grounded_response_is_valid(self):
        self.assertEqual(pipeline_auto_state.validate_brain_response(response()), [])

    def test_a_self_reported_number_is_rejected_as_an_unknown_key(self):
        payload = response()
        payload["confidence"] = 0.97
        problems = pipeline_auto_state.validate_brain_response(payload)
        self.assertTrue(any("confidence" in problem for problem in problems), problems)

    def test_a_rung_outside_the_enum_is_schema_invalid(self):
        problems = pipeline_auto_state.validate_brain_response(response(rung="high"))
        self.assertIn("rung-not-in-enum", problems)

    def test_a_numeric_rung_is_schema_invalid(self):
        self.assertIn("rung-not-in-enum", pipeline_auto_state.validate_brain_response(response(rung=0.95)))

    def test_empty_alternatives_is_a_reserved_violation_not_a_demotion(self):
        self.assertIn("empty-alternatives", pipeline_auto_state.validate_brain_response(response(alternatives=[])))

    def test_an_alternative_without_a_reason_is_empty_alternatives(self):
        payload = response(alternatives=[{"answer_key": "sqlite", "rung": "speculation", "reason": "   "}])
        self.assertIn("empty-alternatives", pipeline_auto_state.validate_brain_response(payload))

    def test_an_empty_falsifier_is_schema_valid_and_demoted_later_not_rejected(self):
        self.assertEqual(pipeline_auto_state.validate_brain_response(response(what_would_change_my_mind="")), [])

    def test_forecloses_is_required(self):
        self.assertTrue(pipeline_auto_state.validate_brain_response(response(forecloses=[])))

    def test_a_brain_cannot_raise_a_question(self):
        payload = response()
        payload["raises"] = {"question": "and what about caching?"}
        self.assertTrue(any("raises" in problem for problem in
                            pipeline_auto_state.validate_brain_response(payload)))

    def test_a_missing_key_is_reported_and_never_defaulted(self):
        payload = response()
        del payload["consistent_with"]
        self.assertTrue(any("consistent_with" in problem for problem in
                            pipeline_auto_state.validate_brain_response(payload)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ValidateBrainResponse -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'validate_brain_response'`

- [ ] **Step 3: Write the implementation**

```python
_RESPONSE_KEYS = frozenset({
    "qid", "answer_key", "answer", "rung", "evidence", "consequences",
    "consistent_with", "forecloses", "blast", "alternatives",
    "what_would_change_my_mind", "blocker",
})
_EVIDENCE_KINDS = frozenset({"spec", "intent-brief", "decision", "repo"})
_ANCHOR_KINDS = frozenset({"decision", "spec", "repo"})
_CONSEQUENCE_KINDS = frozenset({"file-exists", "signature", "command-passes", "config-value"})


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_brain_response(payload: dict) -> list[str]:
    """Return every schema violation. An empty list means the response is legal.

    Strict in both directions. Unknown keys are violations because a brain that
    types a number invents exactly `confidence`, `score` or `certainty`, and a
    validator that ignores extras lets that number reach the arithmetic. There
    is no field through which a brain can raise a question of its own; the only
    exit is `blocker`.
    """
    if not isinstance(payload, dict):
        return ["response-not-an-object"]
    problems = []
    for key in sorted(set(payload) - _RESPONSE_KEYS):
        problems.append(f"unknown-field:{key}")
    for key in sorted(_RESPONSE_KEYS - set(payload)):
        problems.append(f"missing-field:{key}")

    for key in ("qid", "answer_key", "answer"):
        if key in payload and not _text(payload[key]):
            problems.append(f"empty-field:{key}")

    # No default. An unknown rung is schema-invalid, never RUNGS.get(rung, 0.55).
    if payload.get("rung") not in RUNGS:
        problems.append("rung-not-in-enum")

    for item in payload.get("evidence") or ():
        if not isinstance(item, dict) or item.get("kind") not in _EVIDENCE_KINDS:
            problems.append("evidence-item-malformed")
        elif not _text(item.get("path")) or not _text(item.get("quote")):
            problems.append("evidence-item-malformed")
        elif item["kind"] == "decision":
            if not _text(item.get("decision")):
                problems.append("evidence-item-malformed")
        elif not isinstance(item.get("line"), int) or isinstance(item.get("line"), bool):
            problems.append("evidence-item-malformed")

    consequences = payload.get("consequences")
    if not isinstance(consequences, list) or not consequences:
        problems.append("empty-consequences")
    else:
        for item in consequences:
            if (not isinstance(item, dict) or item.get("kind") not in _CONSEQUENCE_KINDS
                    or not _text(item.get("subject")) or not _text(item.get("value"))):
                problems.append("consequence-item-malformed")

    anchors = payload.get("consistent_with")
    if not isinstance(anchors, list) or not anchors:
        problems.append("empty-consistent-with")
    else:
        for item in anchors:
            if not isinstance(item, dict) or item.get("kind") not in _ANCHOR_KINDS:
                problems.append("consistent-with-item-malformed")

    forecloses = payload.get("forecloses")
    if not isinstance(forecloses, list) or not any(_text(entry) for entry in forecloses):
        problems.append("empty-forecloses")

    if not isinstance(payload.get("blast"), list):
        problems.append("blast-not-a-list")

    alternatives = payload.get("alternatives")
    if (not isinstance(alternatives, list) or not alternatives
            or not all(isinstance(alt, dict) and _text(alt.get("answer_key"))
                       and _text(alt.get("reason")) and alt.get("rung") in RUNGS
                       for alt in alternatives)):
        # Reserved code: this is the one violation that drives a re-dispatch.
        problems.append("empty-alternatives")

    if "what_would_change_my_mind" in payload and not isinstance(
            payload["what_would_change_my_mind"], str):
        problems.append("falsifier-not-a-string")

    blocker = payload.get("blocker", None)
    if blocker is not None and not _text(blocker):
        problems.append("blocker-not-a-string")
    return problems
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ValidateBrainResponse -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): reject brain responses that type a number or omit a second-best"
```

---

> **From Task 2 (`58d22ba`).** `evidence: []` is **schema-valid** — the schema
> validator judges shape, not grounding, and deliberately reads no file. So
> `effective_rung` must demote an empty evidence list rather than assume it holds
> at least one item. An `IndexError` here would escape `TrackerError` entirely,
> which is the defect Task 2 just removed from its own validator.
>
> Also: the context's helper **collided** with the existing
> `new_run(case, **overrides)` at `test_pipeline_auto_state.py:4570`, which takes
> a TestCase. It is renamed `quorum_run(stack)` throughout this plan — shadowing
> it would have bound every `new_run(self.stack)` in Tasks 4-13 to the
> case-taking helper, and the real-depth `repo_root` assertion would silently
> never run. That assertion is the only thing standing between this phase and the
> failure where every citation fails to resolve while the run looks correctly
> cautious. A case wanting `addCleanup` instead of an `ExitStack` should call
> `repo_with_a_run(case, layout=...)` (Task 3, ~line 6648), which builds the same
> production-depth layout and writes a real cited file into it.

### Task 3: Evidence resolution and rung demotion

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `RUNGS`, `RUNG_ORDER`, `DEMOTION_RUNG`, `QuorumSchemaInvalid`
- Produces: `effective_rung(response: dict, repo_root: str) -> str`

This is where the claim is priced. A brain's declared rung is a claim about where its answer comes from; `effective_rung` checks that claim by reading the file. A dangling or unquotable citation **demotes to `engineering-judgement` (0.55)** — not rejects. Rejection discards information and hands a malformed brain a veto; demotion prices the claim at what it turned out to be worth, and 0.55 is below the floor, so an inflated claim is defeated arithmetically rather than argued with.

Three further demotions to the same rung, each answering a different way a brain can look grounded without being grounded: no separable second-best, an empty falsifier, and an answer anchored only in repository code with nothing the user actually said.

Demotion never *promotes*: a `speculation` response with a broken citation stays at `speculation`.

- [ ] **Step 1: Write the failing tests**

```python
class EffectiveRung(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        write_repo(self.root, "db/engine.py", "class PostgresEngine:\n    pass\n")
        write_repo(self.root, "db/pool.py", "PostgresEngine pool\n")
        write_repo(self.root, "spec.md", "The session table is backed by PostgreSQL.\n")

    def rung(self, payload):
        return pipeline_auto_state.effective_rung(payload, str(self.root))

    def test_a_resolving_quoted_citation_keeps_the_declared_rung(self):
        self.assertEqual(self.rung(response()), "code-evidenced")

    def test_a_path_that_exists_at_a_line_that_does_not_contain_the_claim_demotes(self):
        # THE NAMED FAULT: an implementation that checks the rung is in the enum
        # and evidence is non-empty, but never RESOLVES the citation, returns
        # "specified" here and adopts a claim nothing supports.
        payload = response(
            rung="specified",
            evidence=[{"kind": "spec", "path": "spec.md", "line": 1, "quote": "backed by MySQL"}],
        )
        self.assertEqual(self.rung(payload), "engineering-judgement")
        self.assertLess(pipeline_auto_state.RUNGS[self.rung(payload)], pipeline_auto_state.ADOPTION_FLOOR)

    def test_a_nonexistent_path_demotes(self):
        payload = response(
            rung="specified",
            evidence=[{"kind": "spec", "path": "no/such/file.md", "line": 1, "quote": "anything"}],
        )
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_a_line_number_past_the_end_of_the_file_demotes(self):
        payload = response(evidence=[{"kind": "repo", "path": "db/engine.py", "line": 900,
                                       "quote": "PostgresEngine"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_specified_cited_only_from_repository_code_demotes(self):
        payload = response(rung="specified")   # evidence kind is "repo", not spec/intent/decision
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_convention_cited_needs_two_exemplars(self):
        one = response(rung="convention-cited")
        self.assertEqual(self.rung(one), "engineering-judgement")
        two = response(rung="convention-cited", evidence=[
            {"kind": "repo", "path": "db/engine.py", "line": 1, "quote": "PostgresEngine"},
            {"kind": "repo", "path": "db/pool.py", "line": 1, "quote": "PostgresEngine"},
        ])
        self.assertEqual(self.rung(two), "convention-cited")

    def test_a_second_best_in_the_same_rung_demotes(self):
        payload = response(alternatives=[{"answer_key": "sqlite", "rung": "code-evidenced",
                                          "reason": "also in the tree"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_an_empty_falsifier_demotes(self):
        self.assertEqual(self.rung(response(what_would_change_my_mind="   ")), "engineering-judgement")

    def test_anchoring_in_repository_code_alone_demotes(self):
        payload = response(consistent_with=[{"kind": "repo", "id": "db/engine.py:1"}])
        self.assertEqual(self.rung(payload), "engineering-judgement")

    def test_demotion_never_promotes_a_speculation(self):
        payload = response(rung="speculation", evidence=[], what_would_change_my_mind="")
        self.assertEqual(self.rung(payload), "speculation")

    def test_a_wrong_repo_root_silently_demotes_every_grounded_answer(self):
        """THE TEST BETWEEN THIS DESIGN AND A SILENT TOTAL FAILURE.

        With the wrong root nothing resolves, so every `specified` and
        `code-evidenced` answer falls to 0.55, every cluster lands below the 0.85
        floor, and the run escalates every question while looking like a
        correctly cautious quorum. No error, no exception, nothing else in the
        suite goes red. The root is a `## Run` field and is never computed.
        """
        payload = response()
        self.assertEqual(pipeline_auto_state.effective_rung(payload, str(self.root)),
                         "code-evidenced")
        self.assertEqual(pipeline_auto_state.effective_rung(payload, str(self.root / "db")),
                         "engineering-judgement")
        self.assertEqual(pipeline_auto_state.effective_rung(payload, str(self.root.parent)),
                         "engineering-judgement")

    def test_the_recorded_repo_root_is_the_one_citations_resolve_against(self):
        with contextlib.ExitStack() as stack:
            root, run_dir = quorum_run(stack)
            write_repo(root, "db/engine.py", "class PostgresEngine:\n")
            recorded = pipeline_auto_state.repo_root(pipeline_auto_state.validate_run(str(run_dir)))
            self.assertEqual(pipeline_auto_state.effective_rung(response(), recorded),
                             "code-evidenced")
            # The run sits three directories deep; a derived root would be wrong.
            self.assertNotEqual(Path(recorded).resolve(), run_dir.resolve())

    def test_an_unknown_rung_raises_and_is_never_defaulted(self):
        # Defeats RUNGS.get(rung, 0.55): 0.55 is a legal value arriving through
        # an illegal door, and nothing downstream could tell the difference.
        with self.assertRaises(pipeline_auto_state.QuorumSchemaInvalid):
            self.rung(response(rung="high"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k EffectiveRung -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'effective_rung'`

- [ ] **Step 3: Write the implementation**

```python
# What each rung must actually be able to show, checked against evidence that
# RESOLVES. Rungs absent from this mapping require none.
_RUNG_EVIDENCE = {
    "specified": (frozenset({"spec", "intent-brief", "decision"}), 1),
    "code-evidenced": (frozenset({"repo"}), 1),
    "convention-cited": (frozenset({"repo"}), 2),
}


def _decision_section(text: str, decision_id: str) -> str | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("## ") and line[3:].split("—")[0].strip() == decision_id:
            end = index + 1
            while end < len(lines) and not lines[end].startswith("## "):
                end += 1
            return "\n".join(lines[index:end])
    return None


def _evidence_resolves(item: dict, repo_root: str) -> bool:
    """True only if the cited place exists AND contains the quoted claim."""
    try:
        text = (Path(repo_root) / item["path"]).read_text(encoding="utf-8")
    except (OSError, UnicodeError, KeyError, TypeError, ValueError):
        return False
    quote = _squash(item.get("quote", ""))
    if not quote:
        return False
    if item.get("kind") == "decision":
        section = _decision_section(text, str(item.get("decision", "")))
        return section is not None and quote in _squash(section)
    lines = text.splitlines()
    number = item.get("line")
    if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= len(lines):
        return False
    return quote in _squash(lines[number - 1])


def _not_above(rung: str, limit: str) -> str:
    """The lower of two rungs. Demotion must never raise a weak claim."""
    return RUNG_ORDER[max(RUNG_ORDER.index(rung), RUNG_ORDER.index(limit))]


def _demotion_reason(response: dict) -> str | None:
    if not str(response.get("what_would_change_my_mind", "")).strip():
        return "empty-falsifier"
    declared = response.get("rung")
    if any(alt.get("rung") == declared for alt in response.get("alternatives") or ()):
        return "second-best-in-the-same-rung"
    if not any(entry.get("kind") in {"decision", "spec"}
               for entry in response.get("consistent_with") or ()):
        return "anchored-only-in-repository-code"
    return None


def effective_rung(response: dict, repo_root: str) -> str:
    """The rung this response actually earned, as a NAME.

    Order is load-bearing: evidence is resolved from disk BEFORE any comparison
    between responses. Running the resolution after the comparison lets a
    top-rung response with a dangling citation win on a claim no file supports.
    """
    declared = response.get("rung")
    if declared not in RUNGS:
        raise QuorumSchemaInvalid(f"rung {declared!r} is outside the enum and is never defaulted")
    evidence = list(response.get("evidence") or ())
    resolved = [_evidence_resolves(item, repo_root) for item in evidence]
    if not all(resolved):
        return _not_above(declared, DEMOTION_RUNG)
    kinds, minimum = _RUNG_EVIDENCE.get(declared, (frozenset(), 0))
    if minimum:
        qualifying = sum(1 for item, ok in zip(evidence, resolved)
                         if ok and item.get("kind") in kinds)
        if qualifying < minimum:
            return _not_above(declared, DEMOTION_RUNG)
    if _demotion_reason(response) is not None:
        return _not_above(declared, DEMOTION_RUNG)
    return declared
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k EffectiveRung -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): price a rung by resolving its evidence from disk"
```

---

### Task 4: Decisions contract, effective projection, and the findings ledger

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Create: `plugins/superb/skills/pipeline-auto/templates/findings.md`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `TrackerValidationError`, `RUNGS`
- Produces: `parse_decisions(text: str) -> dict`, `project_decisions(decisions: dict) -> str`

`parse_decisions` returns `{"decisions": {D-ID: record}, "axis_index": {axis: [D-ID, ...]}}`. Provenance is required and must agree with the ID prefix, so provenance survives even if the field is lost. Two *adopted* decisions contradicting each other on one axis is a **read-only stop** of the same severity as a foreign schema: the file is the audit trail, and an audit trail holding both answers has already failed.

`project_decisions` renders `decisions-effective.md`, the only decision material a brain ever sees. It carries question, answer and provenance and **nothing else** — no value, no rung name, no rejected alternatives. Adopted answers must be included or brains re-litigate settled ground and manufacture the very drift the quorum is supposed to bound. Values must be excluded because a brain reading "adopted at 0.85" treats the decision as soft and reverses it, where a brain reading it as simply a decision treats it as binding. Provenance must be included so a brain can recognise a human decision and refuse to contradict it.

The findings ledger is P03's because the fixer-dispute adjudication lands there and never in `decisions.md`: an adjudication is a factual question about a finding, not a requirement decision, and filing it as a decision would let a dispute about whether code is broken masquerade as a statement about what the user wants.

- [ ] **Step 1: Write the failing tests**

```python
HUMAN = """<!-- pipeline-auto-decisions/v1 -->

## H-001 — Session storage

- **Question:** Which storage engine backs the session table?
- **Axis:** storage-engine
- **Answer:** postgres — Use the existing PostgreSQL instance.
- **Decision action:** none
- **Provenance:** human
- **Depth:** 0
- **Consequences:** file-exists:db/session.sql=present
- **Scope:** T04
- **Status:** Adopted
"""


class ParseDecisions(unittest.TestCase):
    def test_parses_records_and_builds_the_axis_index(self):
        parsed = pipeline_auto_state.parse_decisions(HUMAN)
        self.assertEqual(parsed["decisions"]["H-001"]["provenance"], "human")
        self.assertEqual(parsed["decisions"]["H-001"]["answer_key"], "postgres")
        self.assertEqual(parsed["decisions"]["H-001"]["depth"], 0)
        self.assertEqual(parsed["axis_index"]["storage-engine"], ["H-001"])

    def test_missing_provenance_is_invalid(self):
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_decisions(HUMAN.replace("- **Provenance:** human\n", ""))

    def test_provenance_must_agree_with_the_id_prefix(self):
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_decisions(HUMAN.replace("Provenance:** human", "Provenance:** quorum"))

    def test_two_adopted_contradicting_answers_on_one_axis_are_a_read_only_stop(self):
        clash = HUMAN + HUMAN.split("\n\n", 1)[1].replace("H-001", "Q-abc123def456").replace(
            "Provenance:** human", "Provenance:** quorum").replace(
            "Answer:** postgres", "Answer:** sqlite").replace(
            "file-exists:db/session.sql=present", "file-exists:db/session.sql=absent").replace(
            "Decision action:** none", "Decision action:** quorum.adopt")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.parse_decisions(clash)

    def test_a_generic_answer_is_rejected(self):
        for empty in ("approved", "proceed", "continue", "yes"):
            with self.assertRaises(pipeline_auto_state.TrackerValidationError):
                pipeline_auto_state.parse_decisions(
                    HUMAN.replace("postgres — Use the existing PostgreSQL instance.", empty))


class ProjectDecisions(unittest.TestCase):
    def test_the_projection_carries_question_answer_and_provenance_only(self):
        source = HUMAN.replace(
            "- **Status:** Adopted\n",
            "- **Grounding rung:** specified\n"
            "- **Rejected alternatives:** sqlite — no concurrent writers\n"
            "- **Status:** Adopted\n")
        projection = pipeline_auto_state.project_decisions(pipeline_auto_state.parse_decisions(source))
        self.assertIn("Which storage engine backs the session table?", projection)
        self.assertIn("postgres", projection)
        self.assertIn("human", projection)
        for leak in ("0.95", "0.85", "0.70", "0.55", "0.30",
                     "specified", "Rejected alternatives", "sqlite", "Grounding rung"):
            self.assertNotIn(leak, projection)

    def test_superseded_decisions_are_not_projected(self):
        source = HUMAN.replace("- **Status:** Adopted", "- **Status:** Superseded")
        self.assertNotIn("postgres", pipeline_auto_state.project_decisions(
            pipeline_auto_state.parse_decisions(source)))


class FindingsTemplate(unittest.TestCase):
    def test_the_ledger_carries_an_adjudication_column(self):
        path = (REPOSITORY / "plugins/superb/skills/pipeline-auto/templates/findings.md")
        header = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(header[0], "<!-- pipeline-auto-findings/v1 -->")
        self.assertIn("Adjudication", header[1])
        self.assertIn("Severity", header[1])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ParseDecisions -k ProjectDecisions -k FindingsTemplate -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'parse_decisions'`

- [ ] **Step 3: Write the implementation**

Create `plugins/superb/skills/pipeline-auto/templates/findings.md`:

```markdown
<!-- pipeline-auto-findings/v1 -->
| ID | Scope | Severity | Status | Disposition | Evidence | Adjudication | Fix Round | Re-review |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

<!--
One row per finding. Severity is one of critical | major | minor; the bar is
zero OPEN findings at every severity, so severity orders the work and never
excuses it.

Adjudication records a fixer dispute and its outcome: `-` when undisputed,
otherwise `disputed:<refutation-ref>` then `upheld` or `refuted`. A dispute is
admissible only with a refutation citing file:line or a command and its output;
a bare disagreement is inadmissible and the finding stands. If fewer than two
valid cited verdicts return, or the adjudication splits, the finding STANDS and
is fixed: a false-positive finding costs one wasted fix, a wrongly-refuted
finding ships a defect, and those costs are not symmetric.

An adjudication NEVER enters decisions.md. It is a factual question about this
finding, not a requirement decision, and filing it as a decision would let an
argument about whether code is broken masquerade as a statement about what the
user asked for.
-->
```

Append to the spine:

```python
_DECISION_ACTIONS = frozenset({"task.resume", "quorum.adopt", "quorum.extend-budget", "none"})
_GENERIC_ANSWERS = frozenset({"", "approved", "yes", "continue", "proceed", "go",
                              "ok", "okay", "pending user response"})
_FIELD = re.compile(r"^- \*\*([^:*]+):\*\*\s*(.*)$")


def _decision_records(text: str) -> dict:
    records, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].split("—")[0].strip()
            records[current] = {}
            continue
        match = _FIELD.match(line)
        if match and current is not None:
            key = match.group(1).strip().casefold().replace(" ", "_")
            records[current][key] = match.group(2).strip()
    return records


def _consequence_map(raw: str) -> dict:
    mapping = {}
    for entry in (part.strip() for part in raw.split(",") if part.strip()):
        head, _, value = entry.partition("=")
        kind, _, subject = head.partition(":")
        mapping[(kind.strip(), subject.strip())] = value.strip()
    return mapping


def parse_decisions(text: str) -> dict:
    """Parse decisions.md into records plus a validated axis index.

    Two adopted decisions contradicting each other on one axis is a read-only
    stop of the same severity as a foreign schema: the file IS the audit trail,
    and a trail holding both answers has already failed.
    """
    decisions, axis_index = {}, {}
    for did, fields in _decision_records(text).items():
        provenance = fields.get("provenance", "").strip().casefold()
        if provenance not in {"human", "quorum"}:
            raise TrackerValidationError(f"{did}: Provenance must be human or quorum")
        expected = "human" if did.startswith("H-") else "quorum" if did.startswith("Q-") else None
        if expected is None or expected != provenance:
            raise TrackerValidationError(f"{did}: id prefix and Provenance disagree")
        action = fields.get("decision_action", "").strip()
        if action not in _DECISION_ACTIONS:
            raise TrackerValidationError(f"{did}: unknown decision action {action!r}")
        if action == "quorum.extend-budget" and provenance != "human":
            raise TrackerValidationError(f"{did}: quorum.extend-budget requires Provenance: human")
        answer = fields.get("answer", "").strip()
        if answer.rstrip(".").casefold() in _GENERIC_ANSWERS:
            raise TrackerValidationError(f"{did}: a generic approval is not an answer")
        axis = fields.get("axis", "").strip()
        if not axis:
            raise TrackerValidationError(f"{did}: Axis is required")
        status = fields.get("status", "").strip().casefold().capitalize()
        if status not in {"Adopted", "Superseded"}:
            raise TrackerValidationError(f"{did}: Status must be Adopted or Superseded")
        record = dict(fields)
        record.update({
            "id": did, "axis": axis, "provenance": provenance, "action": action,
            "answer": answer, "answer_key": answer.split("—")[0].strip(),
            "status": status, "depth": int(fields.get("depth", "0") or 0),
            "consequences": _consequence_map(fields.get("consequences", "")),
            "consistent_with": [entry.strip() for entry in
                                fields.get("consistent_with", "").split(",") if entry.strip()],
        })
        decisions[did] = record
        axis_index.setdefault(axis, []).append(did)

    for axis, ids in axis_index.items():
        adopted = [decisions[did] for did in ids if decisions[did]["status"] == "Adopted"]
        for index, left in enumerate(adopted):
            for right in adopted[index + 1:]:
                if _contradicts(left, right):
                    raise TrackerValidationError(
                        f"axis {axis} holds two adopted contradicting answers "
                        f"({left['id']} and {right['id']}); this run is a read-only stop")
    return {"decisions": decisions, "axis_index": axis_index}


def _contradicts(left: dict, right: dict) -> bool:
    if left.get("answer_key") and right.get("answer_key") and left["answer_key"] != right["answer_key"]:
        return True
    shared = set(left["consequences"]) & set(right["consequences"])
    return any(left["consequences"][key] != right["consequences"][key] for key in shared)


def project_decisions(decisions: dict) -> str:
    """Render decisions-effective.md: the only decision material a brain sees.

    Question, answer and provenance. No value, no rung, no rejected
    alternatives. Adopted answers must be present or brains re-litigate settled
    ground; values must be absent or a brain reads "adopted at 0.85" as soft and
    reverses it; provenance must be present so a brain can recognise a human
    decision and refuse to contradict it.
    """
    lines = ["<!-- pipeline-auto-decisions-effective/v1 -->", "",
             "# Decisions in effect", "",
             "Read-only. Generated. Do not cite a value; there is none here.", ""]
    for did in sorted(decisions["decisions"]):
        record = decisions["decisions"][did]
        if record["status"] != "Adopted" or record["action"] == "quorum.extend-budget":
            continue
        lines += [f"## {did}", "",
                  f"- **Question:** {record['question']}",
                  f"- **Answer:** {record['answer']}",
                  f"- **Provenance:** {record['provenance']}", ""]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ParseDecisions -k ProjectDecisions -k FindingsTemplate -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/templates/findings.md \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): validate the decisions contract and project it without values"
```

---

> **From Task 2 (`58d22ba`).** `consistent_with` anchors are validated by `kind`
> only, so `{"kind": "decision"}` with no `id` passes the schema. `decision_depth`
> must decide what an anchor without an id means — the violation code
> `consistent-with-item-malformed` is reserved for it. Treating it as depth 0 by
> accident would let a brain claim grounding in a decision it never names.

### Task 5: Contradiction detection and decision depth

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `parse_decisions`, `DEPTH_CAP`
- Produces: `check_contradiction(decisions: dict, candidate: dict) -> str | None`, `decision_depth(decisions: dict, consistent_with: list) -> int`

Detection is **structural, not semantic**. Every stage-03 question has a stable axis id and every later question is tagged to one, so the check is: on this axis, does the candidate's consequence set require a different value from an adopted decision's? Human-provenance decisions are scanned first so the returned D-ID names the human decision whenever one is contradicted — the rejection status and the terminal report both key off which D-ID comes back.

Depth counts layers of inference away from the last thing a human actually said. Human is 0, an answer citing only depth-0 is 1, and depth 3 is not quorum-eligible: three layers out is where the run stops building the user's product and starts building its own.

- [ ] **Step 1: Write the failing tests**

```python
class CheckContradiction(unittest.TestCase):
    def setUp(self):
        self.decisions = pipeline_auto_state.parse_decisions(HUMAN)

    def test_an_agreeing_candidate_is_not_a_contradiction(self):
        candidate = {"axis": "storage-engine", "answer_key": "postgres",
                     "consequences": [{"kind": "file-exists", "subject": "db/session.sql",
                                       "value": "present"}]}
        self.assertIsNone(pipeline_auto_state.check_contradiction(self.decisions, candidate))

    def test_a_different_option_on_a_decided_axis_names_the_decision(self):
        candidate = {"axis": "storage-engine", "answer_key": "sqlite",
                     "consequences": [{"kind": "file-exists", "subject": "db/session.sql",
                                       "value": "absent"}]}
        self.assertEqual(pipeline_auto_state.check_contradiction(self.decisions, candidate), "H-001")

    def test_a_contradicting_consequence_is_caught_without_answer_keys(self):
        candidate = {"axis": "storage-engine", "answer_key": "",
                     "consequences": [{"kind": "file-exists", "subject": "db/session.sql",
                                       "value": "absent"}]}
        self.assertEqual(pipeline_auto_state.check_contradiction(self.decisions, candidate), "H-001")

    def test_a_different_axis_is_not_a_contradiction(self):
        candidate = {"axis": "log-format", "answer_key": "sqlite",
                     "consequences": [{"kind": "file-exists", "subject": "db/session.sql",
                                       "value": "absent"}]}
        self.assertIsNone(pipeline_auto_state.check_contradiction(self.decisions, candidate))

    def test_human_decisions_are_reported_ahead_of_quorum_ones(self):
        both = HUMAN + (
            "\n## Q-aaaaaaaaaaaa — Session storage, again\n\n"
            "- **Question:** Which storage engine backs the session table?\n"
            "- **Axis:** storage-engine\n"
            "- **Answer:** postgres — Use the existing PostgreSQL instance.\n"
            "- **Decision action:** quorum.adopt\n- **Provenance:** quorum\n"
            "- **Depth:** 1\n"
            "- **Consequences:** file-exists:db/session.sql=present\n"
            "- **Scope:** T05\n- **Status:** Adopted\n")
        decisions = pipeline_auto_state.parse_decisions(both)
        candidate = {"axis": "storage-engine", "answer_key": "sqlite", "consequences": [
            {"kind": "file-exists", "subject": "db/session.sql", "value": "absent"}]}
        self.assertEqual(pipeline_auto_state.check_contradiction(decisions, candidate), "H-001")


class DecisionDepth(unittest.TestCase):
    def test_an_answer_citing_only_a_human_decision_is_depth_one(self):
        decisions = pipeline_auto_state.parse_decisions(HUMAN)
        self.assertEqual(pipeline_auto_state.decision_depth(
            decisions, [{"kind": "decision", "id": "H-001"}]), 1)

    def test_an_answer_citing_only_the_spec_is_depth_one(self):
        decisions = pipeline_auto_state.parse_decisions(HUMAN)
        self.assertEqual(pipeline_auto_state.decision_depth(
            decisions, [{"kind": "spec", "id": "spec.md:12"}]), 1)

    def test_depth_accumulates_and_three_exceeds_the_cap(self):
        text = HUMAN
        for did, depth in (("Q-aaaaaaaaaaaa", 1), ("Q-bbbbbbbbbbbb", 2)):
            text += (f"\n## {did} — derived\n\n- **Question:** q\n- **Axis:** a-{did}\n"
                     f"- **Answer:** k — an answer\n- **Decision action:** quorum.adopt\n"
                     f"- **Provenance:** quorum\n- **Depth:** {depth}\n"
                     f"- **Consequences:** file-exists:x{did}=present\n"
                     f"- **Scope:** T0\n- **Status:** Adopted\n")
        decisions = pipeline_auto_state.parse_decisions(text)
        self.assertEqual(pipeline_auto_state.decision_depth(
            decisions, [{"kind": "decision", "id": "Q-bbbbbbbbbbbb"}]), 3)
        self.assertGreater(3, pipeline_auto_state.DEPTH_CAP)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k CheckContradiction -k DecisionDepth -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'check_contradiction'`

- [ ] **Step 3: Write the implementation**

```python
def check_contradiction(decisions: dict, candidate: dict) -> str | None:
    """Return the D-ID this candidate contradicts on its axis, or None.

    Structural, never semantic: same axis, then a different option or a
    conflicting consequence value. Human-provenance decisions are scanned first
    so the returned D-ID names the human decision whenever one is contradicted —
    the rejection status and the terminal report both key off it.
    """
    ids = decisions["axis_index"].get(candidate.get("axis", ""), [])
    ordered = sorted(ids, key=lambda did: 0 if decisions["decisions"][did]["provenance"] == "human" else 1)
    probe = {
        "answer_key": candidate.get("answer_key", ""),
        "consequences": {(c["kind"], c["subject"]): c["value"]
                         for c in candidate.get("consequences") or ()},
    }
    for did in ordered:
        record = decisions["decisions"][did]
        if record["status"] != "Adopted" or record["action"] == "quorum.extend-budget":
            continue
        if _contradicts(record, probe):
            return did
    return None


def decision_depth(decisions: dict, consistent_with: list) -> int:
    """Layers of inference away from the last thing a human actually said.

    Human decisions are depth 0, so an answer citing only depth-0 material is
    depth 1. Spec and repository anchors are facts rather than inferences and
    contribute 0. Depth 3 is not quorum-eligible.
    """
    deepest = 0
    for entry in consistent_with or ():
        if entry.get("kind") != "decision":
            continue
        record = decisions["decisions"].get(str(entry.get("id", "")))
        if record is not None:
            deepest = max(deepest, record["depth"])
    return deepest + 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k CheckContradiction -k DecisionDepth -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): detect axis contradictions structurally and bound decision depth"
```

---
### Task 6: Admissibility and the per-brain payload

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Create: `plugins/superb/skills/pipeline-auto/tests/fixtures/quorum/question-record.json`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `RUNG_ORDER`, `derive_qid`
- Produces: `READING_ASSIGNMENTS`, `check_admissible(record) -> list[str]`, `build_payload(qid, brain_index, *, run_dir) -> dict`

Three instances of one model reading one payload are **not three independent samples — they are one prior sampled three times.** Shared weights plus a shared prompt produce correlated error, so agreement is far weaker evidence than it looks. Independence has to be manufactured: all three get the **identical verbatim question**, which fair comparison requires, and **different reading assignments**, which biases each toward a *source* and never toward an answer. It also makes the rung distribution informative — three brains that each looked somewhere different and none found grounding is the mechanical signature of drift.

The three payloads are bound by **one digest over the shared payload**, not by three. The reading assignment is a *constant rule* rather than data — index 0 grounds in the spec and intent brief, index 1 in repository code and tests, index 2 in the decisions record and phase plan — and `build_payload` is pure with respect to the index, so brain n's payload is fully determined by `(shared payload, n)` and a re-dispatch of index n is reproducible from `(payload_digest, n)`. That is precisely the property the partial-quorum recovery path rests on, and it is the reason the assignment rule lives in the module's frozen constants beside `RUNGS` rather than in `## Run`: a controller that can write its own assignment rule can change what a brain was asked after the fact.

> **From Task 3 (`5eb82dc`).** Every path a brain may cite has to be
> **repo-root-relative**. `effective_rung(response, repo_root)` takes exactly one
> root — the `## Run` field — resolves `evidence[].path` against it, and requires
> the result to lie inside it. So the `reading_roots` this payload hands a brain,
> and the `decisions_effective` path beside them, are repo-root-relative paths
> (`docs/superpowers/runs/<run-id>/decisions-effective.md`), never run-dir-relative
> ones. Hand a brain `decisions-effective.md` and every decision citation it makes
> resolves to `<repo_root>/decisions-effective.md`, which does not exist — and a
> citation that does not resolve **demotes silently**. The run then escalates every
> question it is ever asked while looking like a correctly cautious quorum. The
> signature is master-plan-pinned at two arguments, so this is the only place the
> contract can be held.

`_shared_payload` is a **whitelist constructor**. It names every key it emits, so the prohibited material is not filtered out, it is never reachable: the raiser's identity, candidate answers and recommendation, the adoption floor, the budget, every rung value, and any elapsed-time or cost signal. A filter can be defeated by a new field; a whitelist cannot.

Admissibility is enforced only where it can be enforced mechanically. Criteria 2 ("decidable from the repository") and 5 ("one decision, not several") are judgment calls carried by P07's prose and the raiser's own declaration; criteria 1, 3 and 4 are checked here. Criterion 4 reuses the options test from `plugins/superb/agents/architecture-discovery.md:54-73`: blank the title, keep the options, and a reader can still tell what is being decided — mechanically, adjectives are not options.

- [ ] **Step 1: Write the failing tests**

```python
QUESTION = {
    "question": "Which storage engine backs the session table?",
    "axis": "storage-engine",
    "phase": "P04",
    "blocks": ["T04"],
    "raiser": "worker-7",
    "options_supplied": True,
    "options": [{"key": "postgres"}, {"key": "sqlite"}],
    "candidate_answers": ["postgres because we already run it"],
    "recommendation": "postgres",
    # Repo-root-relative, every one: these become the brain's citations, and
    # effective_rung resolves a citation against the REPO root.
    "reading_roots": {"spec": "docs/superpowers/specs/design.md",
                      "intent-brief": "docs/superpowers/runs/R/intent-brief.md",
                      "repo": ".", "tests": "tests",
                      "decisions-effective": "docs/superpowers/runs/R/decisions-effective.md",
                      "phase-plan": "docs/superpowers/plans/phase-04.md"},
    "owners": ["brain-a", "brain-b", "brain-c"],
}


class CheckAdmissible(unittest.TestCase):
    def test_a_well_formed_question_is_admissible(self):
        self.assertEqual(pipeline_auto_state.check_admissible(QUESTION), [])

    def test_a_question_blocking_nothing_is_an_opinion(self):
        self.assertIn("blocks-nothing", pipeline_auto_state.check_admissible(dict(QUESTION, blocks=[])))

    def test_an_axis_is_required(self):
        self.assertIn("missing-axis", pipeline_auto_state.check_admissible(dict(QUESTION, axis="")))

    def test_adjectives_are_not_options(self):
        bad = dict(QUESTION, options=[{"key": "modern"}, {"key": "pragmatic"}])
        self.assertIn("options-fail-the-options-test", pipeline_auto_state.check_admissible(bad))

    def test_a_single_option_is_not_a_question(self):
        self.assertIn("fewer-than-two-options",
                      pipeline_auto_state.check_admissible(dict(QUESTION, options=[{"key": "postgres"}])))

    def test_exactly_three_owners_are_required(self):
        self.assertIn("owner-count-is-not-three",
                      pipeline_auto_state.check_admissible(dict(QUESTION, owners=["brain-a", "brain-b"])))


class BuildPayload(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = quorum_run(self.stack)
        self.qid = pipeline_auto_state.derive_qid(QUESTION["question"], QUESTION["axis"])
        (self.run_dir / "quorum" / self.qid).mkdir(parents=True)
        (self.run_dir / "quorum" / self.qid / "question.json").write_text(
            json.dumps(QUESTION), encoding="utf-8")
        self.payloads = [pipeline_auto_state.build_payload(self.qid, index, run_dir=str(self.run_dir))
                         for index in range(3)]

    def test_the_question_is_identical_across_all_three_brains(self):
        questions = {payload["question"] for payload in self.payloads}
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions.pop(), QUESTION["question"])

    def test_the_reading_assignments_differ(self):
        labels = [payload["reading_assignment"]["label"] for payload in self.payloads]
        self.assertEqual(len(set(labels)), 3)
        self.assertEqual(labels[0], "spec-and-intent")
        self.assertEqual(labels[1], "code-and-tests")
        self.assertEqual(labels[2], "decisions-and-plan")

    def test_the_payload_never_carries_the_raisers_candidates(self):
        for payload in self.payloads:
            rendered = json.dumps(payload)
            self.assertNotIn("worker-7", rendered)
            self.assertNotIn("because we already run it", rendered)
            self.assertNotIn("recommendation", rendered)
            self.assertNotIn("candidate", rendered)

    def test_the_payload_never_carries_the_floor_or_any_rung_value(self):
        # A brain that knows the bar clears the bar. Names may travel; numbers
        # may not, and neither may the budget or any elapsed-time signal.
        for payload in self.payloads:
            rendered = json.dumps(payload)
            for leak in ("0.95", "0.85", "0.70", "0.55", "0.30",
                         "ADOPTION_FLOOR", "floor", "budget", "elapsed", "deadline", "cost"):
                self.assertNotIn(leak, rendered.casefold())

    def test_the_payload_offers_rung_names_so_a_brain_can_select_one(self):
        self.assertEqual(tuple(self.payloads[0]["rungs"]), pipeline_auto_state.RUNG_ORDER)

    def test_a_brain_index_outside_the_three_is_refused(self):
        with self.assertRaises(pipeline_auto_state.QuorumError):
            pipeline_auto_state.build_payload(self.qid, 3, run_dir=str(self.run_dir))

    def test_the_three_payloads_differ_only_in_the_assignment_block(self):
        shared = []
        for payload in self.payloads:
            stripped = dict(payload)
            stripped.pop("reading_assignment")
            shared.append(json.dumps(stripped, indent=2, sort_keys=True))
        self.assertEqual(len(set(shared)), 1)

    def test_one_digest_binds_all_three_and_rebuilds_each_byte_for_byte(self):
        # THE ASSERTION THE PARTIAL-RECOVERY RULE RESTS ON, and nothing else in
        # the design checks it: a re-dispatch of brain n must be reproducible
        # from (payload_digest, n). It stops holding the moment build_payload
        # reads anything from the tracker or from run state.
        digest = pipeline_auto_state.payload_digest(self.qid, run_dir=str(self.run_dir))
        rendered = [json.dumps(payload, indent=2, sort_keys=True) for payload in self.payloads]
        for index in range(3):
            rebuilt = pipeline_auto_state.build_payload(self.qid, index, run_dir=str(self.run_dir))
            self.assertEqual(json.dumps(rebuilt, indent=2, sort_keys=True), rendered[index])
        self.assertEqual(pipeline_auto_state.payload_digest(self.qid, run_dir=str(self.run_dir)), digest)

    def test_the_assignment_rule_is_frozen(self):
        with self.assertRaises(TypeError):
            pipeline_auto_state.READING_ASSIGNMENTS[0]["read"] = ("repo",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k CheckAdmissible -k BuildPayload -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'check_admissible'`

Also write `tests/fixtures/quorum/question-record.json` containing the `QUESTION` dict above, so later tasks and P09 can load the same record from disk.

- [ ] **Step 3: Write the implementation**

```python
# Three assignments, each biased toward a SOURCE and never toward an answer.
# Shared weights plus a shared prompt produce correlated error; a different
# place to look is what actually decorrelates three instances of one model.
# The assignment is a constant RULE, not data, and it is frozen beside RUNGS for
# the same reason those are: a controller that can write its own assignment rule
# can change what a brain was asked after the fact. Because the rule is constant
# and build_payload is pure, brain n's payload is fully determined by
# (shared payload, n) — which is what lets ONE digest bind all three.
READING_ASSIGNMENTS = (
    MappingProxyType({"index": 0, "label": "spec-and-intent",
                      "read": ("spec", "intent-brief")}),
    MappingProxyType({"index": 1, "label": "code-and-tests",
                      "read": ("repo", "tests")}),
    MappingProxyType({"index": 2, "label": "decisions-and-plan",
                      "read": ("decisions-effective", "phase-plan")}),
)

# Adjectives describe how someone feels about a choice instead of naming it, and
# an answer to them cannot be written down as a decision. See the options test
# in plugins/superb/agents/architecture-discovery.md:54-73.
_NON_OPTIONS = frozenset({
    "modern", "traditional", "scalable", "simple", "pragmatic", "robust", "clean",
    "flexible", "best-practice", "best practice", "standard", "idiomatic", "lightweight",
})

_RESPONSE_SCHEMA_DOC = (
    "Return one JSON object and nothing else. Required keys: qid, answer_key, answer, "
    "rung, evidence, consequences, consistent_with, forecloses, blast, alternatives, "
    "what_would_change_my_mind, blocker. Any other key is rejected. Select a rung by "
    "name from `rungs`; never write a number anywhere in the response. Every evidence "
    "item must quote text that is actually at the place it cites. `alternatives` must "
    "name a rejected second-best with a real reason. If you cannot answer, set `blocker`."
)


def check_admissible(record: dict) -> list[str]:
    """Mechanical admissibility. Judgment criteria stay with P07's prose."""
    problems = []
    if not [entry for entry in record.get("blocks") or () if _text(entry)]:
        problems.append("blocks-nothing")
    if not _text(record.get("axis")):
        problems.append("missing-axis")
    if not _text(record.get("question")):
        problems.append("missing-question")
    if len(record.get("owners") or ()) != 3:
        problems.append("owner-count-is-not-three")
    options = record.get("options") or ()
    if record.get("options_supplied"):
        keys = [str(option.get("key", "")).strip() for option in options]
        if len([key for key in keys if key]) < 2:
            problems.append("fewer-than-two-options")
        if len(set(keys)) != len(keys):
            problems.append("duplicate-options")
        if any(key.casefold() in _NON_OPTIONS for key in keys):
            problems.append("options-fail-the-options-test")
    return problems


def _question_record(run_dir: str, qid: str) -> dict:
    path = Path(run_dir) / "quorum" / qid / "question.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise QuorumError(f"no question record for {qid}: {exc}") from exc


def _run_relative(run_dir: str, name: str) -> str:
    """A file inside the run, expressed the way a brain must CITE it.

    Repo-root-relative, because `effective_rung` resolves every citation
    against the recorded repo root and refuses one that escapes it. The root is
    READ BACK here, never derived: a run lives at `docs/superpowers/runs/<id>/`
    so the root looks like `parents[3]` — until a run sits somewhere else, and
    there is no index right for both.
    """
    root = Path(repo_root(validate_run(Path(run_dir)))).resolve()
    try:
        inside = Path(run_dir).resolve().relative_to(root)
    except ValueError:
        raise QuorumError(
            f"run_dir {run_dir!r} is not inside the recorded repo_root "
            f"{str(root)!r}; a brain handed a path it cannot cite produces "
            "evidence that never resolves, and evidence that never resolves "
            "demotes without raising") from None
    return (inside / name).as_posix()


def _shared_payload(qid: str, run_dir: str) -> dict:
    """The index-INDEPENDENT half of every brain's payload.

    A WHITELIST constructor. Every key emitted is named here, so the raiser's
    identity, candidate answers and recommendation, the adoption floor, the drift
    budget, every rung value, and any elapsed-time or cost signal are not
    filtered out — they are unreachable. A filter can be defeated by a new field.
    """
    record = _question_record(run_dir, qid)
    return {
        "qid": qid,
        "question": record["question"],          # identical verbatim for all three
        "axis": record["axis"],
        "options": [{"key": option["key"]} for option in record.get("options") or ()],
        "reading_roots": dict(record.get("reading_roots") or {}),
        # Repo-root-relative, like every reading root: this is a path the
        # brain will CITE, and effective_rung resolves citations against the
        # repo root, not against run_dir.
        "decisions_effective": _run_relative(run_dir, "decisions-effective.md"),
        "rungs": list(RUNG_ORDER),               # NAMES only, never values
        "response_schema": _RESPONSE_SCHEMA_DOC,
        "you_are_one_of_several": True,
        # Empty except on a re-open (Task 13), which carries the challenging
        # evidence but never the challenged answer's rung or its owner.
        "challenge": [dict(item) for item in record.get("challenge_evidence") or ()],
    }


def payload_digest(qid: str, *, run_dir: str) -> str:
    """ONE digest binding all three brains' payloads.

    It covers the shared payload and the decisions projection. That is
    sufficient — and not a shortcut — because the reading assignment is a
    constant rule rather than data and build_payload is pure with respect to the
    index, so a re-dispatch of brain n is reproducible from (payload_digest, n).
    It stops binding the moment anything about the assignment is read from the
    tracker or from run state, at which point the recovery path would silently
    re-send a brain a different payload than it first received.
    """
    projection = Path(run_dir) / "decisions-effective.md"
    text = projection.read_text(encoding="utf-8") if projection.exists() else ""
    return _digest(_dumps(_shared_payload(qid, run_dir)) + "\x00" + text)


def build_payload(qid: str, brain_index: int, *, run_dir: str) -> dict:
    """The exact material one brain receives: the shared payload plus its rule.

    Pure with respect to `brain_index`. Nothing here consults the tracker or any
    run state; the only inputs are the question record, the projection, and the
    frozen assignment rule.
    """
    if not isinstance(brain_index, int) or isinstance(brain_index, bool) or not 0 <= brain_index < 3:
        raise QuorumError(f"brain_index {brain_index!r} is outside the three-brain quorum")
    assignment = READING_ASSIGNMENTS[brain_index]
    payload = _shared_payload(qid, run_dir)
    roots = payload["reading_roots"]
    payload["reading_assignment"] = {
        "label": assignment["label"],
        "read": [{"source": source, "root": roots.get(source, "")}
                 for source in assignment["read"]],
    }
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k CheckAdmissible -k BuildPayload -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/fixtures/quorum/question-record.json \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): manufacture brain independence with per-source reading assignments"
```

---

### Task 7: Drift budget, events, and the human budget extension

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `parse_decisions`, `BUDGET_PER_PHASE`, `BUDGET_PER_RUN`, `MAX_EXTENSIONS`
- Produces: `quorum_events(run_dir) -> list[dict]`, `quorum_budget(run_dir, *, phase) -> dict`

Only adoptions count. Escalations never do — an escalation is the run asking for help, and charging for it teaches the controller to stop asking, which is the exact opposite of the design's intent.

The extension reuses the existing pipeline's remediation-extension field discipline, re-pointed at the drift budget: that contract was dropped on the grounds that no human is present mid-run, but a human answering an escalation **is** present, so the reasoning did not apply. `Granted against` is the anti-reflex mechanism — the human is on record as having seen the specific decisions they are waving through, so a bare "continue" cannot become an extension. A grant is checked against the adopted set once and then **pinned** to `quorum/extensions.json`, so a later adoption cannot silently retire a grant the run has already relied on.

Two extensions per run, then the budget is terminal. Three grants with no change to the underlying problem is not a budget problem — it means stage 02 selected the wrong four questions, and the repair is a new run with better ones.

- [ ] **Step 1: Write the failing tests**

```python
def seed_final(run_dir, qid, *, status, phase, rung="code-evidenced", decision_id=None):
    directory = Path(run_dir) / "quorum" / qid
    (directory / "responses").mkdir(parents=True, exist_ok=True)
    record = {"qid": qid, "status": status, "phase": phase, "axis": f"axis-{qid}",
              "decision_id": decision_id, "winner": {"rung": rung, "answer_key": "postgres"}}
    (directory / "final.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
    return record


EXTENSION = """
## H-900 — Budget extension

- **Question:** May the run continue past the drift budget?
- **Axis:** drift-budget
- **Answer:** extend — three further adoptions in P04.
- **Decision action:** quorum.extend-budget
- **Provenance:** human
- **Depth:** 0
- **Authorized run:** {run_id}
- **Source revision:** rev-1
- **Authorized through:** 6
- **Granted against:** {granted}
- **Consequences:** config-value:drift-budget=extended
- **Scope:** P04
- **Status:** Adopted
"""


class QuorumBudget(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = quorum_run(self.stack)

    def test_escalations_never_consume_the_budget(self):
        # THE NAMED FAULT: a counter incremented on every finalisation rather
        # than on adoption burns the budget on the run asking for help.
        for index in range(3):
            seed_final(self.run_dir, f"esc{index:09d}", status="escalated", phase="P04")
        budget = pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")
        self.assertEqual(budget["phase_adoptions"], 0)
        self.assertEqual(budget["phase_remaining"], 3)
        self.assertTrue(budget["may_raise"])

    def test_three_adoptions_exhaust_the_phase(self):
        for index in range(3):
            seed_final(self.run_dir, f"ado{index:09d}", status="adopted", phase="P04",
                       decision_id=f"Q-ado{index:09d}")
        budget = pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")
        self.assertEqual(budget["phase_adoptions"], 3)
        self.assertEqual(budget["phase_remaining"], 0)
        self.assertFalse(budget["may_raise"])
        self.assertEqual(budget["reason"], "phase-budget-exhausted")

    def test_rejections_do_not_consume_the_budget_either(self):
        seed_final(self.run_dir, "rej000000000", status="rejected-contradicts-human", phase="P04")
        self.assertEqual(pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")["phase_adoptions"], 0)

    def test_a_matching_extension_raises_the_ceiling_and_is_pinned(self):
        ids = []
        for index in range(3):
            ids.append(f"Q-ado{index:09d}")
            seed_final(self.run_dir, f"ado{index:09d}", status="adopted", phase="P04",
                       decision_id=ids[-1])
        (self.run_dir / "decisions.md").write_text(
            HUMAN + EXTENSION.format(run_id=RUN_ID, granted=", ".join(sorted(ids))), encoding="utf-8")
        budget = pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")
        self.assertTrue(budget["may_raise"])
        self.assertEqual(budget["phase_ceiling"], 6)
        pinned = json.loads((self.run_dir / "quorum" / "extensions.json").read_text(encoding="utf-8"))
        self.assertEqual([grant["decision_id"] for grant in pinned], ["H-900"])

    def test_a_grant_whose_granted_against_does_not_match_is_rejected(self):
        # Without this the anti-reflex mechanism is just a comment: a human who
        # typed "continue" would be recorded as having reviewed decisions they
        # were never shown.
        seed_final(self.run_dir, "ado000000000", status="adopted", phase="P04",
                   decision_id="Q-ado000000000")
        (self.run_dir / "decisions.md").write_text(
            HUMAN + EXTENSION.format(run_id=RUN_ID, granted="Q-something-else"), encoding="utf-8")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")

    def test_a_grant_for_another_run_is_rejected(self):
        (self.run_dir / "decisions.md").write_text(
            HUMAN + EXTENSION.format(run_id="some-other-run", granted=""), encoding="utf-8")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")

    def test_an_unlimited_ceiling_is_rejected(self):
        (self.run_dir / "decisions.md").write_text(
            HUMAN + EXTENSION.format(run_id=RUN_ID, granted="").replace(
                "Authorized through:** 6", "Authorized through:** unlimited"), encoding="utf-8")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")

    def test_a_third_extension_is_refused(self):
        text = HUMAN
        for index in range(3):
            text += EXTENSION.format(run_id=RUN_ID, granted="").replace("H-900", f"H-90{index}")
        (self.run_dir / "decisions.md").write_text(text, encoding="utf-8")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")

    def test_an_extension_can_never_be_granted_by_quorum(self):
        (self.run_dir / "decisions.md").write_text(
            HUMAN + EXTENSION.format(run_id=RUN_ID, granted="").replace(
                "H-900", "Q-900000000000").replace("Provenance:** human", "Provenance:** quorum"),
            encoding="utf-8")
        with self.assertRaises(pipeline_auto_state.TrackerValidationError):
            pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k QuorumBudget -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'quorum_budget'`

- [ ] **Step 3: Write the implementation**

```python
def _quorum_root(run_dir) -> Path:
    return Path(run_dir) / "quorum"


def _load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _dumps(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def quorum_events(run_dir: str) -> list[dict]:
    """Every finalised quorum in this run, ordered by qid.

    Derived from final.json files rather than from a separate log, so there is
    one place a record can exist and no way for a counter to disagree with the
    evidence. Rejections are events too: a run with several
    rejected-contradicts-* events is a run whose brains keep pulling away from
    what the user asked for, and that count is the earliest drift warning
    available.
    """
    events = []
    root = _quorum_root(run_dir)
    if not root.is_dir():
        return events
    for final in sorted(root.glob("*/final.json")):
        events.append(_load_json(final))
    return events


def _budget_extensions(run_dir, adopted_ids: list[str], run_id: str) -> list[dict]:
    decisions_path = Path(run_dir) / "decisions.md"
    if not decisions_path.exists():
        return []
    decisions = parse_decisions(decisions_path.read_text(encoding="utf-8"))
    pins_path = _quorum_root(run_dir) / "extensions.json"
    pinned = {grant["decision_id"]: grant for grant in
              (_load_json(pins_path) if pins_path.exists() else [])}
    grants = []
    for did in sorted(decisions["decisions"]):
        record = decisions["decisions"][did]
        if record["action"] != "quorum.extend-budget" or record["status"] != "Adopted":
            continue
        if did in pinned:
            grants.append(pinned[did])
            continue
        for field in ("authorized_run", "source_revision", "authorized_through", "granted_against"):
            if field not in record:
                raise TrackerValidationError(f"{did}: quorum.extend-budget requires {field}")
        if record["authorized_run"].strip() != run_id:
            raise TrackerValidationError(f"{did}: extension authorizes run {record['authorized_run']!r}")
        through = record["authorized_through"].strip()
        if not through.isdigit():
            raise TrackerValidationError(f"{did}: Authorized through must be a finite number")
        shown = tuple(entry.strip() for entry in record["granted_against"].split(",") if entry.strip())
        if shown != tuple(sorted(adopted_ids)):
            raise TrackerValidationError(
                f"{did}: Granted against does not match the adopted set the human was shown")
        grants.append({"decision_id": did, "phase": record.get("scope", "").strip(),
                       "authorized_through": int(through), "granted_against": list(shown)})
    if len(grants) > MAX_EXTENSIONS:
        raise TrackerValidationError(
            f"{len(grants)} budget extensions granted; the cap is {MAX_EXTENSIONS} and the "
            f"budget is now terminal")
    if grants:
        pins_path.parent.mkdir(parents=True, exist_ok=True)
        pins_path.write_text(_dumps(grants), encoding="utf-8")
    return grants


def quorum_budget(run_dir: str, *, phase: str) -> dict:
    """Remaining machine decision authority. Only ADOPTIONS are charged.

    Escalations and rejections never count: an escalation is the run asking for
    help, and charging for it teaches the controller to stop asking.
    """
    events = quorum_events(run_dir)
    adopted = [event for event in events if event["status"] == "adopted"]
    adopted_ids = sorted(event["decision_id"] for event in adopted if event.get("decision_id"))
    run_id = str(_load_json(Path(run_dir) / "quorum" / "run-id.json")["run_id"]) \
        if (Path(run_dir) / "quorum" / "run-id.json").exists() \
        else validate_run(str(run_dir))["run"]["run_id"]
    grants = _budget_extensions(run_dir, adopted_ids, run_id)

    phase_ceiling = BUDGET_PER_PHASE
    run_ceiling = BUDGET_PER_RUN
    for grant in grants:
        if grant["phase"] == phase:
            phase_ceiling = max(phase_ceiling, grant["authorized_through"])
        run_ceiling = max(run_ceiling, BUDGET_PER_RUN + grant["authorized_through"] - BUDGET_PER_PHASE)

    phase_adoptions = sum(1 for event in adopted if event["phase"] == phase)
    run_adoptions = len(adopted)
    reason = None
    if phase_adoptions >= phase_ceiling:
        reason = "phase-budget-exhausted"
    elif run_adoptions >= run_ceiling:
        reason = "run-budget-exhausted"
    return {
        "phase": phase,
        "phase_adoptions": phase_adoptions, "phase_ceiling": phase_ceiling,
        "phase_remaining": max(0, phase_ceiling - phase_adoptions),
        "run_adoptions": run_adoptions, "run_ceiling": run_ceiling,
        "run_remaining": max(0, run_ceiling - run_adoptions),
        "extensions": grants, "adopted": adopted_ids,
        "may_raise": reason is None, "reason": reason,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k QuorumBudget -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): charge only adoptions and pin human budget extensions"
```

---

### Task 8: Opening a quorum — the budget trips before dispatch

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `check_admissible`, `derive_qid`, `build_payload`, `quorum_budget`, `project_decisions`, `publish_immutable`
- Produces: `open_quorum(run_dir, *, question_record) -> dict`

Phase 1 of the three-phase record. `open.json` carries the three owner ids, the shared question digest, the per-brain payload digests and the context digest, and it is published **before** any brain is dispatched — so an interruption immediately after dispatch is still classifiable, and a re-dispatch can prove it is sending the same bytes.

Two rules meet here and both are easy to get backwards:

**The budget trips at raise time, before dispatch.** The triggering question is never sent to brains. The off-by-one is natural because the counter increments where the adoption happens, so the check wants to live there too — and every other budget test still passes with it in the wrong place, while three brains get dispatched for a question that could never have been adopted.

**A re-raise of a settled qid dispatches nothing.** This is the compaction-replay guard: after a compaction the controller has forgotten that it asked, the worker re-publishes byte-identical question text, and a second quorum on a settled question is how a run quietly changes its own mind.

- [ ] **Step 1: Write the failing tests**

```python
class OpenQuorum(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root, self.run_dir = quorum_run(self.stack)
        self.record_path = self.run_dir / "question-T04.json"
        self.record_path.write_text(json.dumps(QUESTION), encoding="utf-8")
        self.qid = pipeline_auto_state.derive_qid(QUESTION["question"], QUESTION["axis"])

    def test_the_open_record_is_published_before_any_response_exists(self):
        opened = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(self.record_path))
        self.assertEqual(opened["status"], "in_flight")
        directory = self.run_dir / "quorum" / self.qid
        record = json.loads((directory / "open.json").read_text(encoding="utf-8"))
        self.assertEqual(record["owners"], QUESTION["owners"])
        self.assertEqual(record["payload_digest"],
                         pipeline_auto_state.payload_digest(self.qid, run_dir=str(self.run_dir)))
        self.assertTrue(record["question_digest"])
        self.assertTrue(record["context_digest"])
        self.assertEqual(list((directory / "responses").iterdir()), [])
        for owner in QUESTION["owners"]:
            self.assertTrue((directory / f"payload-{owner}.json").exists())

    def test_it_writes_the_decisions_projection_for_the_brains(self):
        pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(self.record_path))
        self.assertTrue((self.run_dir / "decisions-effective.md").exists())

    def test_an_inadmissible_question_is_discarded_without_dispatch(self):
        self.record_path.write_text(json.dumps(dict(QUESTION, blocks=[])), encoding="utf-8")
        with self.assertRaises(pipeline_auto_state.QuorumError):
            pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(self.record_path))
        self.assertFalse((self.run_dir / "quorum" / self.qid).exists())

    def test_the_budget_trips_before_dispatch_not_after_adoption(self):
        # THE NAMED FAULT: with the check at adoption time the fourth question
        # still reaches three brains. Assert it never leaves the controller.
        for index in range(3):
            seed_final(self.run_dir, f"ado{index:09d}", status="adopted", phase="P04",
                       decision_id=f"Q-ado{index:09d}")
        opened = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(self.record_path))
        self.assertEqual(opened["status"], "escalated")
        self.assertEqual(opened["reason"], "phase-budget-exhausted")
        directory = self.run_dir / "quorum" / self.qid
        self.assertFalse((directory / "open.json").exists())
        self.assertEqual(list(directory.glob("payload-*.json")), [])
        self.assertEqual(json.loads((directory / "final.json").read_text(
            encoding="utf-8"))["status"], "escalated")

    def test_a_re_raise_of_a_settled_question_dispatches_nothing(self):
        # THE COMPACTION-REPLAY BUG. Nothing cheaper catches it: after a
        # compaction the controller has forgotten it asked, the worker publishes
        # byte-identical text, and a second quorum on a settled question is how a
        # run quietly changes its own mind.
        first = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(self.record_path))
        directory = self.run_dir / "quorum" / self.qid
        (directory / "final.json").write_text(_dumps_for_test({
            "qid": self.qid, "status": "adopted", "phase": "P04", "axis": "storage-engine",
            "decision_id": f"Q-{self.qid}",
            "winner": {"rung": "code-evidenced", "answer_key": "postgres",
                       "answer": "Use the existing PostgreSQL instance."},
        }), encoding="utf-8")
        before = sorted(path.name for path in directory.rglob("*"))
        second = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(self.record_path))
        self.assertEqual(sorted(path.name for path in directory.rglob("*")), before)
        self.assertEqual(second["status"], "adopted")
        self.assertTrue(second["replay"])
        self.assertEqual(json.dumps(second["winner"], sort_keys=True),
                         json.dumps({"rung": "code-evidenced", "answer_key": "postgres",
                                     "answer": "Use the existing PostgreSQL instance."},
                                    sort_keys=True))
        self.assertEqual(first["qid"], second["qid"])

    def test_a_re_raise_keeps_its_qid_when_decisions_have_moved_on(self):
        pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(self.record_path))
        first = json.loads((self.run_dir / "quorum" / self.qid / "open.json").read_text(encoding="utf-8"))
        (self.run_dir / "decisions.md").write_text(HUMAN, encoding="utf-8")
        self.assertEqual(pipeline_auto_state.derive_qid(QUESTION["question"], QUESTION["axis"]), self.qid)
        self.assertTrue(first["context_digest"])
```

Add the tiny helper next to the other test helpers:

```python
def _dumps_for_test(value):
    return json.dumps(value, indent=2, sort_keys=True) + "\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k OpenQuorum -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'open_quorum'`

- [ ] **Step 3: Write the implementation**

```python
def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _context_digest(run_dir) -> str:
    path = Path(run_dir) / "decisions.md"
    return _digest(path.read_text(encoding="utf-8")) if path.exists() else _digest("")


def open_quorum(run_dir: str, *, question_record: str) -> dict:
    """Phase 1 of the three-phase record: persist, then dispatch.

    open.json carries the owners, the shared question digest, the per-brain
    payload digests and the context digest, and lands BEFORE any brain is
    dispatched, so an interruption a moment later is still classifiable and a
    re-dispatch can prove it is sending the same bytes.
    """
    run_dir = Path(run_dir)
    record = _load_json(question_record)
    problems = check_admissible(record)
    if problems:
        raise QuorumError(f"question is inadmissible: {', '.join(problems)}")

    qid = derive_qid(record["question"], record["axis"])
    directory = _quorum_root(run_dir) / qid
    final_path = directory / "final.json"

    # One adopted answer per qid per run. A re-raise returns the record and
    # dispatches nothing.
    if final_path.exists():
        settled = _load_json(final_path)
        return dict(settled, replay=True, qid=qid)
    if (directory / "open.json").exists():
        return dict(_load_json(directory / "open.json"), status="in_flight", replay=True, qid=qid)

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "responses").mkdir(exist_ok=True)
    (directory / "question.json").write_text(_dumps(record), encoding="utf-8")

    # THE BUDGET TRIPS HERE, BEFORE DISPATCH. Checking at adoption time still
    # passes every other budget test while sending three brains a question that
    # could never have been adopted.
    budget = quorum_budget(str(run_dir), phase=record["phase"])
    if not budget["may_raise"]:
        escalation = {"qid": qid, "status": "escalated", "reason": budget["reason"],
                      "phase": record["phase"], "axis": record["axis"],
                      "decision_id": None, "winner": None,
                      "adopted": budget["adopted"], "dispatched": False,
                      "context_digest": _context_digest(run_dir)}
        publish_immutable(str(final_path), _dumps(escalation))
        _mirror_terminal(run_dir, escalation)
        return escalation

    decisions_path = run_dir / "decisions.md"
    parsed = parse_decisions(decisions_path.read_text(encoding="utf-8")) if decisions_path.exists() \
        else {"decisions": {}, "axis_index": {}}
    (run_dir / "decisions-effective.md").write_text(project_decisions(parsed), encoding="utf-8")

    # ONE digest, over the shared payload and the projection. The three brains
    # differ only by a constant rule applied to the index, so (digest, n)
    # reproduces brain n's bytes exactly — which is what a re-dispatch needs.
    for index, owner in enumerate(record["owners"]):
        (directory / f"payload-{owner}.json").write_text(
            _dumps(build_payload(qid, index, run_dir=str(run_dir))), encoding="utf-8")
    digest = payload_digest(qid, run_dir=str(run_dir))

    opened = {
        "qid": qid, "status": "in_flight", "axis": record["axis"], "phase": record["phase"],
        "owners": list(record["owners"]),
        "question_digest": _digest(_squash(record["question"])),
        "payload_digest": digest,
        "context_digest": _context_digest(run_dir),
        "options_supplied": bool(record.get("options_supplied")),
        "blocks": list(record.get("blocks") or ()),
    }
    publish_immutable(str(directory / "open.json"), _dumps(opened))
    return opened
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k OpenQuorum -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): persist the quorum before dispatch and trip the budget at raise time"
```

---
### Task 9: Immutable responses and the single permitted re-dispatch

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `validate_brain_response`, `publish_immutable`
- Produces: `record_brain_response(run_dir, *, qid, owner, payload) -> str`, `quorum_needs_redispatch(run_dir, *, qid) -> list[str]`

Phase 2 of the record. Each response lands as its own immutable file, so a crash between two responses loses nothing and a duplicate delivery is inert.

A schema-invalid response — an out-of-enum rung, an empty `alternatives` list — is **recorded as invalid**, not discarded and not repaired. That brain is re-dispatched **once** with the identical payload under attempt 2. A second invalid response is a non-response: the quorum is incomplete and escalates. A brain must not be able to force adoption by malforming — only to force a human look.

- [ ] **Step 1: Write the failing tests**

```python
class RecordBrainResponse(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root, self.run_dir = quorum_run(self.stack)
        write_repo(self.root, "db/engine.py", "class PostgresEngine:\n")
        path = self.run_dir / "question.json"
        path.write_text(json.dumps(QUESTION), encoding="utf-8")
        self.qid = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(path))["qid"]
        self.responses = self.run_dir / "quorum" / self.qid / "responses"

    def record(self, owner, payload):
        return pipeline_auto_state.record_brain_response(
            str(self.run_dir), qid=self.qid, owner=owner, payload=payload)

    def test_a_valid_response_lands_as_its_own_immutable_file(self):
        self.record("brain-a", response(qid=self.qid))
        stored = json.loads((self.responses / "brain-a__1.json").read_text(encoding="utf-8"))
        self.assertTrue(stored["valid"])
        self.assertEqual(stored["attempt"], 1)
        self.assertEqual(stored["problems"], [])

    def test_a_byte_identical_redelivery_is_inert(self):
        first = self.record("brain-a", response(qid=self.qid))
        self.assertEqual(first, self.record("brain-a", response(qid=self.qid)))
        self.assertEqual(len(list(self.responses.glob("brain-a__*.json"))), 1)

    def test_a_malformed_rung_is_recorded_invalid_and_owes_exactly_one_redispatch(self):
        # THE SHARPEST TEST IN THE PHASE. It catches RUNGS.get(rung_id, 0.55),
        # which is overwhelmingly natural to write because 0.55 is already in the
        # module for the demotion rule, so defaulting to it looks principled and
        # reads as defensive. It converts every malformed response into an
        # engineering-judgement vote through an illegal door.
        self.record("brain-a", response(qid=self.qid, rung="high"))
        stored = json.loads((self.responses / "brain-a__1.json").read_text(encoding="utf-8"))
        self.assertFalse(stored["valid"])
        self.assertIn("rung-not-in-enum", stored["problems"])
        self.assertEqual(pipeline_auto_state.quorum_needs_redispatch(str(self.run_dir), qid=self.qid),
                         ["brain-a"])

    def test_an_empty_alternatives_list_owes_a_redispatch(self):
        self.record("brain-a", response(qid=self.qid, alternatives=[]))
        self.assertEqual(pipeline_auto_state.quorum_needs_redispatch(str(self.run_dir), qid=self.qid),
                         ["brain-a"])

    def test_a_valid_second_attempt_clears_the_debt(self):
        self.record("brain-a", response(qid=self.qid, rung="high"))
        self.record("brain-a", response(qid=self.qid))
        self.assertEqual(json.loads((self.responses / "brain-a__2.json").read_text(
            encoding="utf-8"))["attempt"], 2)
        self.assertEqual(pipeline_auto_state.quorum_needs_redispatch(str(self.run_dir), qid=self.qid), [])

    def test_a_second_malformed_response_is_a_non_response_and_owes_nothing_more(self):
        self.record("brain-a", response(qid=self.qid, rung="high"))
        self.record("brain-a", response(qid=self.qid, rung="higher"))
        self.assertEqual(pipeline_auto_state.quorum_needs_redispatch(str(self.run_dir), qid=self.qid), [])
        with self.assertRaises(pipeline_auto_state.QuorumError):
            self.record("brain-a", response(qid=self.qid))

    def test_a_response_to_an_unopened_quorum_is_refused(self):
        with self.assertRaises(pipeline_auto_state.QuorumError):
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid="ffffffffffff", owner="brain-a", payload=response())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k RecordBrainResponse -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'record_brain_response'`

- [ ] **Step 3: Write the implementation**

```python
def _open_record(run_dir, qid: str) -> dict:
    path = _quorum_root(run_dir) / qid / "open.json"
    if not path.exists():
        raise QuorumError(f"quorum {qid} was never opened; nothing may be recorded against it")
    return _load_json(path)


def _owner_attempts(run_dir, qid: str, owner: str) -> list[dict]:
    directory = _quorum_root(run_dir) / qid / "responses"
    return [_load_json(path) for path in sorted(directory.glob(f"{owner}__*.json"))]


def record_brain_response(run_dir: str, *, qid: str, owner: str, payload: dict) -> str:
    """Phase 2: one immutable file per response, valid or not.

    A schema-invalid response is RECORDED, never discarded and never repaired.
    Discarding hides the malformation from the audit; repairing invents a vote.
    """
    opened = _open_record(run_dir, qid)
    if owner not in opened["owners"]:
        raise QuorumError(f"{owner} is not one of the three owners of {qid}")
    attempts = _owner_attempts(run_dir, qid, owner)
    if attempts and attempts[-1]["response"] == payload:
        return str(_quorum_root(run_dir) / qid / "responses" / f"{owner}__{len(attempts)}.json")
    if len(attempts) >= 2:
        raise QuorumError(f"{owner} has already used its one re-dispatch for {qid}")
    problems = validate_brain_response(payload)
    record = {"qid": qid, "owner": owner, "attempt": len(attempts) + 1,
              "valid": not problems, "problems": problems, "response": payload}
    return publish_immutable(
        str(_quorum_root(run_dir) / qid / "responses" / f"{owner}__{record['attempt']}.json"),
        _dumps(record))


def quorum_needs_redispatch(run_dir: str, *, qid: str) -> list[str]:
    """Owners owed the single permitted re-dispatch with the identical payload.

    Exactly one. A second invalid response is a non-response: the quorum is
    incomplete and escalates, so a brain can force a human look but never an
    adoption.
    """
    owed = []
    for owner in _open_record(run_dir, qid)["owners"]:
        attempts = _owner_attempts(run_dir, qid, owner)
        if len(attempts) == 1 and not attempts[0]["valid"]:
            owed.append(owner)
    return owed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k RecordBrainResponse -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): record every brain response immutably and allow exactly one re-dispatch"
```

---

### Task 10: Classifying an interrupted quorum

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `_open_record`, `quorum_needs_redispatch`, `_context_digest`
- Produces: `classify_quorum(run_dir, *, qid, live_owners) -> dict`

The three-phase record exists so that **every** interruption point is classifiable from disk. This is the function that proves it. Five states, and each is a different instruction to the controller:

- `finalised` — a finalised record is **never recomputed**. Never re-run a quorum to check: a second run with different brains produces a different answer roughly as often as the rung gap is narrow, and the controller has no principled way to prefer either.
- `ready-to-finalise` — three terminal responses on disk; compute, do not re-dispatch.
- `awaiting-responses` — owners are still live; wait.
- `redispatch` — zero to two responses and no live owners; discard partials and re-send the **identical** payload, its digest proving identity.
- `stale-context` — the recorded `context_digest` no longer matches `decisions.md`. The quorum is **not** re-opened; it is flagged to stage 11. Re-deciding on resume is precisely the silent-divergence failure this design exists to prevent.

- [ ] **Step 1: Write the failing tests**

```python
class ClassifyQuorum(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root, self.run_dir = quorum_run(self.stack)
        write_repo(self.root, "db/engine.py", "class PostgresEngine:\n")
        path = self.run_dir / "question.json"
        path.write_text(json.dumps(QUESTION), encoding="utf-8")
        self.qid = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(path))["qid"]

    def classify(self, live_owners=()):
        return pipeline_auto_state.classify_quorum(
            str(self.run_dir), qid=self.qid, live_owners=list(live_owners))

    def test_no_responses_with_live_owners_is_awaiting(self):
        self.assertEqual(self.classify(QUESTION["owners"])["state"], "awaiting-responses")

    def test_two_responses_and_no_live_owners_is_a_redispatch_of_identical_bytes(self):
        for owner in QUESTION["owners"][:2]:
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid=self.qid, owner=owner, payload=response(qid=self.qid))
        verdict = self.classify()
        self.assertEqual(verdict["state"], "redispatch")
        self.assertEqual(sorted(verdict["owners"]), sorted(QUESTION["owners"]))
        opened = json.loads((self.run_dir / "quorum" / self.qid / "open.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["payload_digest"], opened["payload_digest"])

    def test_three_responses_is_ready_to_finalise_and_never_redispatched(self):
        for owner in QUESTION["owners"]:
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid=self.qid, owner=owner, payload=response(qid=self.qid))
        self.assertEqual(self.classify(QUESTION["owners"])["state"], "ready-to-finalise")

    def test_an_owner_owed_a_redispatch_is_named(self):
        pipeline_auto_state.record_brain_response(
            str(self.run_dir), qid=self.qid, owner="brain-a", payload=response(qid=self.qid, rung="high"))
        verdict = self.classify()
        self.assertEqual(verdict["state"], "redispatch")
        self.assertIn("brain-a", verdict["owners"])

    def test_a_finalised_record_is_never_recomputed(self):
        (self.run_dir / "quorum" / self.qid / "final.json").write_text(
            _dumps_for_test({"qid": self.qid, "status": "adopted", "phase": "P04",
                             "winner": {"rung": "code-evidenced"}}), encoding="utf-8")
        verdict = self.classify(QUESTION["owners"])
        self.assertEqual(verdict["state"], "finalised")
        self.assertFalse(verdict["recompute"])

    def test_a_moved_context_is_flagged_stale_and_never_reopened(self):
        (self.run_dir / "decisions.md").write_text(HUMAN, encoding="utf-8")
        verdict = self.classify()
        self.assertEqual(verdict["state"], "stale-context")
        self.assertFalse(verdict["reopen"])
        self.assertEqual(verdict["route"], "stage-11")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ClassifyQuorum -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'classify_quorum'`

- [ ] **Step 3: Write the implementation**

```python
def classify_quorum(run_dir: str, *, qid: str, live_owners: list) -> dict:
    """What an interrupted quorum needs next. One state per interruption point."""
    directory = _quorum_root(run_dir) / qid
    final_path = directory / "final.json"
    if final_path.exists():
        # Never re-run a quorum to check. A second run with different brains
        # gives a different answer about as often as the rung gap is narrow, and
        # there is no principled way to prefer either.
        return {"state": "finalised", "qid": qid, "recompute": False,
                "result": _load_json(final_path)}

    opened = _open_record(run_dir, qid)
    if opened["context_digest"] != _context_digest(run_dir):
        # NOT re-opened. Re-deciding on resume is the silent-divergence failure.
        return {"state": "stale-context", "qid": qid, "reopen": False, "route": "stage-11",
                "recorded_context": opened["context_digest"],
                "current_context": _context_digest(run_dir)}

    terminal, owed = 0, []
    for owner in opened["owners"]:
        attempts = _owner_attempts(run_dir, qid, owner)
        if not attempts:
            continue
        if attempts[-1]["valid"] or len(attempts) >= 2:
            terminal += 1
        else:
            owed.append(owner)

    if terminal == len(opened["owners"]):
        return {"state": "ready-to-finalise", "qid": qid, "owners": list(opened["owners"])}
    live = [owner for owner in live_owners if owner in opened["owners"]]
    if live and not owed:
        return {"state": "awaiting-responses", "qid": qid, "owners": live}
    missing = [owner for owner in opened["owners"]
               if not _owner_attempts(run_dir, qid, owner)]
    # The identical payload, its single digest proving identity: brain n is
    # rebuilt from (payload_digest, n).
    return {"state": "redispatch", "qid": qid, "owners": sorted(set(owed) | set(missing)),
            "payload_digest": opened["payload_digest"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ClassifyQuorum -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): classify every quorum interruption point from disk"
```

---

### Task 11: Clustering, rung strictness, and adoption

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `effective_rung`, `RUNG_ORDER`, `RUNGS`, `ADOPTION_FLOOR`, `locked_tracker_update`
- Produces: `group_responses(responses, *, options_supplied)`, `cluster_rung(cluster) -> str`, `finalize_quorum(run_dir, *, qid) -> dict` (adoption path), `current_floor(run_dir) -> dict`

> **From Task 3 (`5eb82dc`).** `_demotion_reason(response)` already names WHY a
> response that cites real files is still ungrounded — `empty-falsifier`,
> `second-best-in-the-same-rung`, `anchored-only-in-repository-code`. Record that
> name per response in `final.json`. Deriving it again at read time means deriving
> it from a different code path than the one that priced the answer, and the two
> can disagree without anything failing.

**Order is load-bearing.** Every response's `effective_rung` is recomputed from disk **before** any comparison between responses. Running the resolution afterwards lets a top-rung response with a dangling citation win on a claim no file supports, and no other test in this suite covers the ordering.

A cluster's rung is its **highest** member rung, never the mean. Averaging punishes a correct lone expert and lets two weak agreers manufacture a majority.

Where more than one cluster exists the winner's rung must be **strictly higher** than the runner-up's. **Equal rungs never adopt**, even when both clear the floor: two brains reading the same code and reaching different answers from evidence of the same quality is exactly where a numeric margin would manufacture a winner out of noise. Unanimity is the one case with no runner-up, so the strictness test is vacuous there and the floor alone governs.

**There is no separate three-way-split rule and you must not add one.** Rung strictness subsumes it, and it handles the case the old unconditional rule got wrong: one brain citing the spec against two speculating *should* win.

- [ ] **Step 1: Write the failing tests**

```python
def graded(root, answer_key, rung, *, subject=None, line=1):
    payload = response(
        answer_key=answer_key, rung=rung,
        consequences=[{"kind": "file-exists", "subject": subject or "db/session.sql",
                       "value": answer_key}],
    )
    if rung == "specified":
        payload["evidence"] = [{"kind": "spec", "path": "spec.md", "line": line,
                                "quote": "session table"}]
    elif rung == "code-evidenced":
        payload["evidence"] = [{"kind": "repo", "path": "db/engine.py", "line": 1,
                                "quote": "PostgresEngine"}]
    elif rung == "convention-cited":
        payload["evidence"] = [
            {"kind": "repo", "path": "db/engine.py", "line": 1, "quote": "PostgresEngine"},
            {"kind": "repo", "path": "db/pool.py", "line": 1, "quote": "PostgresEngine"}]
    else:
        payload["evidence"] = []
    return payload


class ClusterRung(unittest.TestCase):
    def test_a_cluster_takes_its_highest_member_rung_never_the_mean(self):
        cluster = [{"effective_rung": "speculation"}, {"effective_rung": "specified"}]
        self.assertEqual(pipeline_auto_state.cluster_rung(cluster), "specified")
        self.assertNotEqual(pipeline_auto_state.cluster_rung(cluster), "convention-cited")

    def test_an_empty_cluster_has_no_rung(self):
        with self.assertRaises(pipeline_auto_state.QuorumError):
            pipeline_auto_state.cluster_rung([])


class GroupResponses(unittest.TestCase):
    def test_named_options_cluster_on_answer_key(self):
        responses = [response(answer_key="postgres"), response(answer_key="postgres"),
                     response(answer_key="sqlite")]
        clusters, _ = pipeline_auto_state.group_responses(responses, options_supplied=True)
        self.assertEqual(sorted(len(cluster) for cluster in clusters), [1, 2])

    def test_prose_answers_cluster_on_non_contradicting_consequences(self):
        same = {"kind": "file-exists", "subject": "db/session.sql", "value": "present"}
        other = {"kind": "file-exists", "subject": "db/session.sql", "value": "absent"}
        responses = [response(answer_key="", consequences=[same]),
                     response(answer_key="", consequences=[same]),
                     response(answer_key="", consequences=[other])]
        clusters, _ = pipeline_auto_state.group_responses(responses, options_supplied=False)
        self.assertEqual(sorted(len(cluster) for cluster in clusters), [1, 2])

    def test_answers_sharing_no_subject_are_neither_agreement_nor_conflict(self):
        responses = [
            response(answer_key="", consequences=[{"kind": "file-exists", "subject": "a",
                                                    "value": "present"}]),
            response(answer_key="", consequences=[{"kind": "file-exists", "subject": "b",
                                                    "value": "present"}]),
            response(answer_key="", consequences=[{"kind": "file-exists", "subject": "c",
                                                    "value": "present"}]),
        ]
        _clusters, verdicts = pipeline_auto_state.group_responses(responses, options_supplied=False)
        self.assertTrue(all(verdict is None for verdict in verdicts.values()))


class FinalizeAdoption(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root, self.run_dir = quorum_run(self.stack)
        write_repo(self.root, "db/engine.py", "class PostgresEngine:\n")
        write_repo(self.root, "db/pool.py", "PostgresEngine pool\n")
        write_repo(self.root, "spec.md", "The session table is the run's own store.\n")
        (self.run_dir / "decisions.md").write_text(HUMAN.replace(
            "- **Axis:** storage-engine", "- **Axis:** unrelated-axis"), encoding="utf-8")
        self.path = self.run_dir / "question.json"
        self.path.write_text(json.dumps(QUESTION), encoding="utf-8")
        self.qid = pipeline_auto_state.open_quorum(
            str(self.run_dir), question_record=str(self.path))["qid"]

    def answer(self, payloads):
        for owner, payload in zip(QUESTION["owners"], payloads):
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid=self.qid, owner=owner, payload=dict(payload, qid=self.qid))
        return pipeline_auto_state.finalize_quorum(str(self.run_dir), qid=self.qid)

    def test_a_strictly_higher_cluster_adopts(self):
        result = self.answer([graded(self.root, "postgres", "specified"),
                              graded(self.root, "postgres", "speculation"),
                              graded(self.root, "sqlite", "speculation")])
        self.assertEqual(result["status"], "adopted")
        self.assertEqual(result["winner"]["answer_key"], "postgres")
        self.assertEqual(result["winner"]["rung"], "specified")
        self.assertEqual(result["runner_up_rung"], "speculation")

    def test_one_spec_citation_beats_two_speculations(self):
        # The retired three-way-split rule would have escalated this and thrown
        # away the only grounded answer in the room. Rung strictness keeps it.
        result = self.answer([graded(self.root, "postgres", "specified"),
                              graded(self.root, "sqlite", "speculation"),
                              graded(self.root, "duckdb", "speculation")])
        self.assertEqual(result["status"], "adopted")
        self.assertEqual(result["winner"]["answer_key"], "postgres")

    def test_two_clusters_at_equal_rung_escalate_even_above_the_floor(self):
        result = self.answer([graded(self.root, "postgres", "code-evidenced"),
                              graded(self.root, "postgres", "speculation"),
                              graded(self.root, "sqlite", "code-evidenced")])
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["reason"], "equal-or-inverted-rung")

    def test_two_of_three_agreement_is_not_sufficient_on_its_own(self):
        result = self.answer([graded(self.root, "postgres", "convention-cited"),
                              graded(self.root, "postgres", "convention-cited"),
                              graded(self.root, "sqlite", "speculation")])
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["reason"], "below-floor")

    def test_a_unanimous_convention_cited_answer_escalates(self):
        # convention-cited sits BELOW the floor on purpose: a machine may decide
        # what the spec or the code entails, but it may not decide by imitation.
        result = self.answer([graded(self.root, "postgres", "convention-cited")] * 3)
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["reason"], "below-floor")

    def test_a_unanimous_code_evidenced_answer_adopts_with_no_runner_up(self):
        result = self.answer([graded(self.root, "postgres", "code-evidenced")] * 3)
        self.assertEqual(result["status"], "adopted")
        self.assertIsNone(result["runner_up_rung"])

    def test_evidence_is_resolved_before_any_comparison(self):
        # THE ORDERING FAULT. With resolution after the comparison the dangling
        # `specified` claim wins at 0.95 on a line that does not exist.
        dangling = graded(self.root, "duckdb", "specified")
        dangling["evidence"] = [{"kind": "spec", "path": "no/such/spec.md", "line": 1,
                                 "quote": "duckdb"}]
        result = self.answer([dangling,
                              graded(self.root, "postgres", "code-evidenced"),
                              graded(self.root, "postgres", "speculation")])
        self.assertEqual(result["status"], "adopted")
        self.assertEqual(result["winner"]["answer_key"], "postgres")
        self.assertEqual(result["winner"]["rung"], "code-evidenced")
        self.assertEqual(result["effective_rungs"]["brain-a"], "engineering-judgement")

    def test_a_second_malformed_response_escalates_rather_than_evaluating_two_answers(self):
        for owner in QUESTION["owners"][:1]:
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid=self.qid, owner=owner,
                payload=dict(graded(self.root, "postgres", "specified"), qid=self.qid, rung="high"))
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid=self.qid, owner=owner,
                payload=dict(graded(self.root, "postgres", "specified"), qid=self.qid, rung="higher"))
        for owner in QUESTION["owners"][1:]:
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid=self.qid, owner=owner,
                payload=dict(graded(self.root, "postgres", "specified"), qid=self.qid))
        result = pipeline_auto_state.finalize_quorum(str(self.run_dir), qid=self.qid)
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["reason"], "incomplete-quorum")

    def test_two_blockers_escalate(self):
        blocked = dict(graded(self.root, "postgres", "specified"), blocker="no API key on disk")
        result = self.answer([blocked, blocked, graded(self.root, "postgres", "specified")])
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["reason"], "blocked")

    def test_answers_describing_different_things_are_not_decidable(self):
        record = dict(QUESTION, options_supplied=False, options=[],
                      question="What should the session layer do?")
        path = self.run_dir / "q2.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        qid = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(path))["qid"]
        for owner, subject in zip(QUESTION["owners"], ("a", "b", "c")):
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid=qid, owner=owner,
                payload=dict(graded(self.root, "", "specified", subject=subject), qid=qid))
        result = pipeline_auto_state.finalize_quorum(str(self.run_dir), qid=qid)
        self.assertEqual(result["status"], "question-not-decidable")

    def test_adoption_appends_one_decision_and_replay_appends_none(self):
        self.answer([graded(self.root, "postgres", "specified"),
                     graded(self.root, "postgres", "speculation"),
                     graded(self.root, "sqlite", "speculation")])
        after_first = (self.run_dir / "decisions.md").read_text(encoding="utf-8")
        self.assertIn(f"## Q-{self.qid}", after_first)
        self.assertIn("- **Provenance:** quorum", after_first)
        self.assertIn("- **Decision action:** quorum.adopt", after_first)
        pipeline_auto_state.finalize_quorum(str(self.run_dir), qid=self.qid)
        self.assertEqual((self.run_dir / "decisions.md").read_text(encoding="utf-8"), after_first)

    def test_the_floor_rises_once_the_adopted_distribution_inflates(self):
        for index in range(5):
            seed_final(self.run_dir, f"inf{index:09d}", status="adopted", phase="P04",
                       rung="specified", decision_id=f"Q-inf{index:09d}")
        floor = pipeline_auto_state.current_floor(str(self.run_dir))
        self.assertEqual(floor["floor_rung"], "specified")
        persisted = json.loads((self.run_dir / "quorum" / "floor.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["floor_rung"], "specified")
        # It never falls back once raised.
        seed_final(self.run_dir, "low000000000", status="adopted", phase="P04",
                   rung="code-evidenced", decision_id="Q-low000000000")
        self.assertEqual(pipeline_auto_state.current_floor(str(self.run_dir))["floor_rung"], "specified")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ClusterRung -k GroupResponses -k FinalizeAdoption -v`
Expected: FAIL with `AttributeError: module 'pipeline_auto_state' has no attribute 'cluster_rung'`

- [ ] **Step 3: Write the implementation**

```python
def cluster_rung(cluster: list) -> str:
    """A cluster's rung is its HIGHEST member rung.

    Never the mean. Averaging punishes a correct lone expert and lets two weak
    agreers manufacture a majority.
    """
    if not cluster:
        raise QuorumError("an empty cluster has no rung")
    return RUNG_ORDER[min(RUNG_ORDER.index(member["effective_rung"]) for member in cluster)]


def _consequence_subjects(payload: dict) -> dict:
    return {(item["kind"], item["subject"]): item["value"] for item in payload["consequences"]}


def _same_answer(left: dict, right: dict, options_supplied: bool):
    """True, False, or None when the two describe different things."""
    if options_supplied:
        return left["answer_key"] == right["answer_key"]
    a, b = _consequence_subjects(left), _consequence_subjects(right)
    shared = set(a) & set(b)
    if not shared:
        return None
    if any(a[key] != b[key] for key in shared):
        return False
    return True


def group_responses(responses: list, *, options_supplied: bool) -> tuple[list, dict]:
    """Cluster answers. When in doubt they are DIFFERENT answers.

    Different pushes toward escalation, which is the safe direction.
    """
    verdicts = {}
    for i in range(len(responses)):
        for j in range(i + 1, len(responses)):
            verdicts[(i, j)] = _same_answer(responses[i], responses[j], options_supplied)
    clusters = []
    for index in range(len(responses)):
        for cluster in clusters:
            if all(verdicts[tuple(sorted((index, member)))] is True for member in cluster):
                cluster.append(index)
                break
        else:
            clusters.append([index])
    return clusters, verdicts


def current_floor(run_dir: str) -> dict:
    """The adoption floor for this run. It rises on inflation and never falls.

    Individual confidence claims are often unfalsifiable; the distribution is
    not. After five or more adoptions a mean above 0.90 raises the bar one rung
    for the rest of the run, and the adjustment is recorded.
    """
    path = _quorum_root(run_dir) / "floor.json"
    persisted = _load_json(path) if path.exists() else None
    rung = persisted["floor_rung"] if persisted else "code-evidenced"
    adopted = [event for event in quorum_events(run_dir) if event["status"] == "adopted"]
    if len(adopted) >= 5:
        mean = sum(RUNGS[event["winner"]["rung"]] for event in adopted) / len(adopted)
        if mean > 0.90:
            raised = RUNG_ORDER[max(0, RUNG_ORDER.index(rung) - 1)]
            if RUNG_ORDER.index(raised) < RUNG_ORDER.index(rung):
                rung = raised
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_dumps({"floor_rung": rung, "raised_after": len(adopted),
                                        "mean": round(mean, 4)}), encoding="utf-8")
    return {"floor_rung": rung, "floor_value": RUNGS[rung]}


def finalize_quorum(run_dir: str, *, qid: str) -> dict:
    """Phase 3, through the tracker lock with transition_id "quorum-"+qid.

    A replayed transition never calls mutate, so a re-finalisation after a
    compaction recomputes nothing and appends nothing.
    """
    run_dir = Path(run_dir)
    final_path = _quorum_root(run_dir) / qid / "final.json"
    if final_path.exists():
        result = _load_json(final_path)
        _ensure_decision_recorded(run_dir, result)
        return result
    holder = {}

    def mutate(tracker):
        # repo_root comes from the tracker, never from directory arithmetic.
        holder["result"] = _compute_quorum_result(run_dir, qid, tracker)
        publish_immutable(str(final_path), _dumps(holder["result"]))
        return _mirror_quorum(tracker, holder["result"])

    locked_tracker_update(str(run_dir), transition_id=f"quorum-{qid}", mutate=mutate)
    result = holder.get("result") or _load_json(final_path)
    _ensure_decision_recorded(run_dir, result)
    return result


def _compute_quorum_result(run_dir, qid: str, tracker: dict) -> dict:
    opened = _open_record(run_dir, qid)
    base = {"qid": qid, "axis": opened["axis"], "phase": opened["phase"],
            "context_digest": opened["context_digest"], "decision_id": None,
            "winner": None, "runner_up_rung": None, "effective_rungs": {}, "dispatched": True}

    latest, invalid = [], []
    for owner in opened["owners"]:
        attempts = _owner_attempts(run_dir, qid, owner)
        if not attempts:
            raise QuorumIncomplete(f"{owner} has not responded to {qid}")
        attempt = attempts[-1]
        if not attempt["valid"]:
            if len(attempts) < 2:
                raise QuorumIncomplete(f"{owner} is owed its one re-dispatch for {qid}")
            invalid.append(owner)
            continue
        latest.append((owner, attempt["response"]))

    if invalid:
        # A second malformed response is a non-response. A brain must not be able
        # to force adoption by malforming — only to force a human look.
        return dict(base, status="escalated", reason="incomplete-quorum", invalid_owners=invalid)

    # ORDER IS LOAD-BEARING: resolve every citation from disk BEFORE comparing.
    # The root is the `## Run` field. Deriving it here would demote every
    # grounded answer to 0.55 and escalate the entire run, silently.
    root = repo_root(tracker)
    rungs = {}
    for owner, payload in latest:
        rungs[owner] = effective_rung(payload, root)
    base["effective_rungs"] = rungs

    if sum(1 for _owner, payload in latest if payload.get("blocker")) >= 2:
        return dict(base, status="escalated", reason="blocked")

    payloads = [payload for _owner, payload in latest]
    owners = [owner for owner, _payload in latest]
    clusters, verdicts = group_responses(payloads, options_supplied=opened["options_supplied"])
    if verdicts and all(verdict is None for verdict in verdicts.values()):
        return dict(base, status="question-not-decidable", reason="answers-describe-different-things")

    def members(cluster):
        return [{"owner": owners[index], "payload": payloads[index],
                 "effective_rung": rungs[owners[index]]} for index in cluster]

    ranked = sorted(
        (members(cluster) for cluster in clusters),
        key=lambda cluster: (RUNG_ORDER.index(cluster_rung(cluster)),
                             len(_union_subjects(cluster))),
    )
    winner = ranked[0]
    winner_rung = cluster_rung(winner)
    runner_up_rung = cluster_rung(ranked[1]) if len(ranked) > 1 else None
    base["runner_up_rung"] = runner_up_rung

    floor = current_floor(str(run_dir))
    if RUNGS[winner_rung] < floor["floor_value"]:
        return dict(base, status="escalated", reason="below-floor", winner_rung=winner_rung)

    # NO NUMERIC MARGIN. Strictly higher by ladder position, or escalate.
    # Unanimity has no runner-up, so the test is vacuous and the floor governs.
    if runner_up_rung is not None and RUNG_ORDER.index(winner_rung) >= RUNG_ORDER.index(runner_up_rung):
        return dict(base, status="escalated", reason="equal-or-inverted-rung",
                    winner_rung=winner_rung)

    best = max(winner, key=lambda member: (RUNG_ORDER.index(member["effective_rung"]) * -1,))
    return _apply_adoption_gates(run_dir, base, winner, best, winner_rung)


def _union_subjects(cluster: list) -> set:
    subjects = set()
    for member in cluster:
        subjects |= set(_consequence_subjects(member["payload"]))
    return subjects
```

`_apply_adoption_gates` and `_ensure_decision_recorded` are written in Task 12; for this task, stub them to the adoption path only:

```python
def _apply_adoption_gates(run_dir, base, winner, best, winner_rung):
    payload = best["payload"]
    return dict(base, status="adopted", reason=None,
                winner={"answer_key": payload["answer_key"], "answer": payload["answer"],
                        "rung": winner_rung, "owner": best["owner"],
                        "consequences": payload["consequences"],
                        "consistent_with": payload["consistent_with"],
                        "forecloses": payload["forecloses"], "blast": payload["blast"]},
                decision_id=f"Q-{base['qid']}", depth=1)


def _ensure_decision_recorded(run_dir, result: dict) -> None:
    """Append the adopted decision if it is not already on file. Idempotent.

    Publishing final.json first and appending second means an interruption
    between the two leaves a finalised record with no decision, which this
    repairs on the next call; the reverse order would double-append.
    """
    if result["status"] != "adopted":
        return
    path = Path(run_dir) / "decisions.md"
    text = path.read_text(encoding="utf-8") if path.exists() else "<!-- pipeline-auto-decisions/v1 -->\n"
    heading = f"## {result['decision_id']}"
    if heading in text:
        return
    winner = result["winner"]
    consequences = ", ".join(f"{item['kind']}:{item['subject']}={item['value']}"
                             for item in winner["consequences"])
    record = "\n".join([
        "", f"{heading} — quorum answer on {result['axis']}", "",
        f"- **Question:** {_question_record(run_dir, result['qid'])['question']}",
        f"- **Axis:** {result['axis']}",
        f"- **Answer:** {winner['answer_key']} — {winner['answer']}",
        "- **Decision action:** quorum.adopt",
        "- **Provenance:** quorum",
        f"- **Depth:** {result['depth']}",
        f"- **Grounding rung:** {winner['rung']}",
        f"- **Runner-up rung:** {result['runner_up_rung'] or '-'}",
        f"- **Consequences:** {consequences}",
        f"- **Consistent with:** {', '.join(str(entry.get('id', '')) for entry in winner['consistent_with'])}",
        f"- **Forecloses:** {'; '.join(winner['forecloses'])}",
        f"- **Context digest:** {result['context_digest']}",
        f"- **Scope:** {', '.join(_open_record(run_dir, result['qid'])['blocks'])}",
        "- **Status:** Adopted", ""])
    path.write_text(text + record, encoding="utf-8")
    parse_decisions(path.read_text(encoding="utf-8"))   # axis index validated on every write
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ClusterRung -k GroupResponses -k FinalizeAdoption -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): adopt only on a strictly higher cluster rung above the floor"
```

---

### Task 12: The rejection gates and P03's own tracker rows

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `check_contradiction`, `decision_depth`, `IRREVERSIBLE_AXES`, `DEPTH_CAP`, `parse_decisions`
- Produces: `_apply_adoption_gates` (full), `_row_for`, `_quorum_row`, `_escalation_row`, `_mirror_quorum`, `quorum_tracker_rows(run_dir) -> list[dict]`

A quorum may decide an open question. **It may never overrule a recorded one.** A candidate contradicting a `Provenance: human` decision is rejected and escalated at any rung, and the rejection is **recorded, not discarded**: a run with several `rejected-contradicts-*` events is a run whose brains keep pulling away from what the user asked for, and that count is the earliest drift warning available.

The irreversible-axis list is closed and enumerated, and no confidence buys past it. `forecloses` is required precisely so that asking what an answer *destroys* can surface risk that asking what it *achieves* never does.

The drift budget is deliberately **not** re-checked here. It tripped at raise time; charging it again at adoption would double-count, and a budget charged on escalation teaches the run not to ask.

P03 also writes its **own** `## Quorum` and `## Escalations` rows here, through P02's `section_columns` and `append_row`, inside the same locked transition that publishes `final.json`. No phase writes another phase's rows and no phase re-declares another phase's columns. The column names below are asserted against `section_columns(...)` on every write, so if P02's grammar differs the very first run of this task names the mismatch — no guess survives silently, which is the whole point of routing the write through the primitive instead of a local tuple.

- [ ] **Step 1: Write the failing tests**

```python
class FinalizeRejections(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root, self.run_dir = quorum_run(self.stack)
        write_repo(self.root, "db/engine.py", "class PostgresEngine:\n")
        write_repo(self.root, "spec.md", "The session table is the run's own store.\n")

    def run_quorum(self, record, payloads):
        path = self.run_dir / f"q-{record['axis']}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        qid = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(path))["qid"]
        for owner, payload in zip(record["owners"], payloads):
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid=qid, owner=owner, payload=dict(payload, qid=qid))
        return pipeline_auto_state.finalize_quorum(str(self.run_dir), qid=qid)

    def test_contradicting_a_human_decision_is_rejected_and_records_no_decision(self):
        # THE NAMED FAULT: remove this gate and the quorum adopts on an axis a
        # human already decided, silently, at any rung.
        (self.run_dir / "decisions.md").write_text(
            HUMAN.replace("- **Axis:** storage-engine", "- **Axis:** auth-model")
                 .replace("postgres — Use the existing PostgreSQL instance.", "session-cookie — Cookies.")
                 .replace("file-exists:db/session.sql=present", "config-value:auth=session-cookie"),
            encoding="utf-8")
        record = dict(QUESTION, axis="auth-model", question="Which auth model?",
                      options=[{"key": "session-cookie"}, {"key": "jwt"}])
        payload = graded(self.root, "jwt", "specified")
        payload["consequences"] = [{"kind": "config-value", "subject": "auth", "value": "jwt"}]
        before = (self.run_dir / "decisions.md").read_text(encoding="utf-8")
        result = self.run_quorum(record, [payload, payload,
                                          graded(self.root, "session-cookie", "speculation")])
        self.assertEqual(result["status"], "rejected-contradicts-human")
        self.assertEqual(result["contradicted_decision"], "H-001")
        self.assertIn("H-001", result["reason"])
        self.assertEqual((self.run_dir / "decisions.md").read_text(encoding="utf-8"), before)

    def test_the_rejection_is_recorded_as_an_event_for_the_terminal_report(self):
        self.test_contradicting_a_human_decision_is_rejected_and_records_no_decision()
        statuses = [event["status"] for event in pipeline_auto_state.quorum_events(str(self.run_dir))]
        self.assertIn("rejected-contradicts-human", statuses)

    def test_an_irreversible_blast_escalates_at_the_top_rung(self):
        record = dict(QUESTION, axis="new", question="Do we add a hosted queue?")
        payload = dict(graded(self.root, "postgres", "specified"), blast=["external-service"])
        result = self.run_quorum(record, [payload, payload,
                                          graded(self.root, "sqlite", "speculation")])
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["reason"], "irreversible-axis")

    def test_depth_three_is_not_quorum_eligible(self):
        text = HUMAN.replace("- **Axis:** storage-engine", "- **Axis:** unrelated")
        text += ("\n## Q-cccccccccccc — derived\n\n- **Question:** q\n- **Axis:** deep-axis\n"
                 "- **Answer:** k — an answer\n- **Decision action:** quorum.adopt\n"
                 "- **Provenance:** quorum\n- **Depth:** 2\n"
                 "- **Consequences:** file-exists:deep=present\n- **Scope:** T0\n"
                 "- **Status:** Adopted\n")
        (self.run_dir / "decisions.md").write_text(text, encoding="utf-8")
        record = dict(QUESTION, axis="new", question="Which cache layer?")
        payload = graded(self.root, "postgres", "specified")
        payload["consistent_with"] = [{"kind": "decision", "id": "Q-cccccccccccc"},
                                      {"kind": "spec", "id": "spec.md:1"}]
        result = self.run_quorum(record, [payload, payload,
                                          graded(self.root, "sqlite", "speculation")])
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["reason"], "depth-exceeded")
        self.assertEqual(result["depth"], 3)

    def test_three_escalations_then_an_adoption_still_succeeds_under_a_phase_budget_of_three(self):
        # THE NAMED FAULT: a counter incremented on every finalisation burns the
        # phase budget on three requests for help and then refuses the one
        # question the run could actually have answered.
        for index in range(3):
            record = dict(QUESTION, axis=f"split-{index}", question=f"Question {index}?")
            self.run_quorum(record, [graded(self.root, "postgres", "code-evidenced"),
                                     graded(self.root, "sqlite", "code-evidenced"),
                                     graded(self.root, "duckdb", "speculation")])
        self.assertEqual(pipeline_auto_state.quorum_budget(str(self.run_dir), phase="P04")["phase_adoptions"], 0)
        record = dict(QUESTION, axis="finally", question="A question that can be answered?")
        result = self.run_quorum(record, [graded(self.root, "postgres", "specified"),
                                          graded(self.root, "postgres", "speculation"),
                                          graded(self.root, "sqlite", "speculation")])
        self.assertEqual(result["status"], "adopted")


class QuorumTrackerRows(unittest.TestCase):
    def test_every_event_is_mirrored_with_its_provenance_visible(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = quorum_run(stack)
            seed_final(run_dir, "aaaaaaaaaaaa", status="adopted", phase="P04",
                       decision_id="Q-aaaaaaaaaaaa")
            seed_final(run_dir, "bbbbbbbbbbbb", status="rejected-contradicts-human", phase="P04")
            rows = pipeline_auto_state.quorum_tracker_rows(str(run_dir))
        self.assertEqual([row["QID"] for row in rows], ["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
        self.assertEqual(rows[0]["Provenance"], "quorum")
        self.assertEqual(rows[0]["Decision"], "Q-aaaaaaaaaaaa")
        self.assertEqual(rows[1]["Status"], "rejected-contradicts-human")
        self.assertEqual(rows[1]["Decision"], "-")

    def test_rows_are_ordered_by_p02s_columns_and_break_loudly_on_a_mismatch(self):
        columns = pipeline_auto_state.section_columns("Quorum")
        with contextlib.ExitStack() as stack:
            _root, run_dir = quorum_run(stack)
            seed_final(run_dir, "aaaaaaaaaaaa", status="adopted", phase="P04",
                       decision_id="Q-aaaaaaaaaaaa")
            row = pipeline_auto_state.quorum_tracker_rows(str(run_dir))[0]
        self.assertEqual(tuple(row), columns)
        with self.assertRaises(pipeline_auto_state.QuorumError):
            pipeline_auto_state._row_for("Quorum", {"QID": "x"})

    def test_an_escalation_is_mirrored_into_the_escalations_section(self):
        with contextlib.ExitStack() as stack:
            root, run_dir = quorum_run(stack)
            write_repo(root, "db/engine.py", "class PostgresEngine:\n")
            write_repo(root, "db/pool.py", "PostgresEngine pool\n")
            (run_dir / "decisions.md").write_text(
                HUMAN.replace("- **Axis:** storage-engine", "- **Axis:** unrelated-axis"),
                encoding="utf-8")
            path = run_dir / "question.json"
            path.write_text(json.dumps(QUESTION), encoding="utf-8")
            qid = pipeline_auto_state.open_quorum(
                str(run_dir), question_record=str(path))["qid"]
            for owner, key in zip(QUESTION["owners"], ("postgres", "sqlite", "duckdb")):
                pipeline_auto_state.record_brain_response(
                    str(run_dir), qid=qid, owner=owner,
                    payload=dict(graded(root, key, "convention-cited"), qid=qid))
            result = pipeline_auto_state.finalize_quorum(str(run_dir), qid=qid)
            tracker = pipeline_auto_state.validate_run(str(run_dir))
        self.assertEqual(result["status"], "escalated")
        escalations = tracker["escalations"]
        self.assertEqual(escalations[-1]["QID"], qid)
        self.assertEqual(escalations[-1]["State"], "pending")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k FinalizeRejections -k QuorumTrackerRows -v`
Expected: FAIL — `AssertionError: 'adopted' != 'rejected-contradicts-human'` from the Task 11 stub

- [ ] **Step 3: Write the implementation**

Replace the Task 11 stub with the full gate chain:

```python
def _apply_adoption_gates(run_dir, base, winner, best, winner_rung) -> dict:
    """Everything that can refuse an answer that already cleared the rung bar.

    The drift budget is deliberately absent: it tripped at raise time, and
    charging it again here would double-count. Nothing in this chain charges an
    escalation either — an escalation is the run asking for help.
    """
    payload = best["payload"]
    candidate = {
        "axis": base["axis"], "answer_key": payload["answer_key"],
        "consequences": payload["consequences"],
    }
    blast = set()
    for member in winner:
        blast |= {str(entry) for entry in member["payload"].get("blast") or ()}
    summary = {
        "answer_key": payload["answer_key"], "answer": payload["answer"],
        "rung": winner_rung, "owner": best["owner"],
        "consequences": payload["consequences"], "consistent_with": payload["consistent_with"],
        "forecloses": payload["forecloses"], "blast": sorted(blast),
    }
    base = dict(base, winner=summary)

    # No confidence buys past the closed list. `forecloses` is required so that
    # asking what an answer DESTROYS surfaces risk that asking what it achieves
    # never does.
    trespass = sorted(blast & IRREVERSIBLE_AXES)
    if trespass:
        return dict(base, status="escalated", reason="irreversible-axis",
                    irreversible=trespass, winner=None, blast=sorted(blast))

    decisions_path = Path(run_dir) / "decisions.md"
    decisions = parse_decisions(decisions_path.read_text(encoding="utf-8")) \
        if decisions_path.exists() else {"decisions": {}, "axis_index": {}}

    # A quorum may decide an open question. It may never overrule a recorded one.
    contradicted = check_contradiction(decisions, candidate)
    if contradicted is not None:
        provenance = decisions["decisions"][contradicted]["provenance"]
        return dict(base, winner=None,
                    status=f"rejected-contradicts-{provenance}",
                    reason=f"the adopted consequences contradict {contradicted} "
                           f"(Provenance: {provenance}) on axis {base['axis']}",
                    contradicted_decision=contradicted)

    depth = decision_depth(decisions, payload["consistent_with"])
    if depth > DEPTH_CAP:
        return dict(base, status="escalated", reason="depth-exceeded", depth=depth, winner=None)

    return dict(base, status="adopted", reason=None, depth=depth,
                decision_id=f"Q-{base['qid']}")


def _row_for(section: str, values: dict) -> dict:
    """Order one row by P02's columns, loudly.

    P02 owns the column grammar and P03 owns the quorum lifecycle, so P03 writes
    its own rows and re-declares nobody's columns. Checking against
    `section_columns` means a column change in P02 fails here at the seam rather
    than drifting into a mismatched write nothing notices.
    """
    columns = section_columns(section)
    missing = [column for column in columns if column not in values]
    unexpected = [key for key in values if key not in columns]
    if missing or unexpected:
        raise QuorumError(
            f"{section} row does not match P02's columns "
            f"(missing {missing}, unexpected {unexpected}); reconcile with section_columns()")
    return {column: values[column] for column in columns}


def _quorum_row(event: dict) -> dict:
    winner = event.get("winner") or {}
    return _row_for("Quorum", {
        "QID": event["qid"],
        "Axis": event.get("axis", "-"),
        "Phase": event.get("phase", "-"),
        "Status": event["status"],
        "Provenance": "quorum",
        "Rung": winner.get("rung", "-"),
        "Runner-up": event.get("runner_up_rung") or "-",
        "Decision": event.get("decision_id") or "-",
        "Reopen Of": event.get("reopen_of") or "-",
        "Raised Bar": event.get("raised_bar_rung") or "-",
        "Payload Digest": event.get("payload_digest", "-"),
        "Reason": event.get("reason") or "-",
    })


def _escalation_row(event: dict) -> dict:
    winner = event.get("winner") or {}
    return _row_for("Escalations", {
        "ID": f"E-{event['qid']}",
        "QID": event["qid"],
        "Axis": event.get("axis", "-"),
        "Phase": event.get("phase", "-"),
        "Reason": event.get("reason") or event["status"],
        "Blast": ", ".join(winner.get("blast") or ()) or "-",
        "State": "pending",
    })


def _mirror_quorum(tracker: dict, event: dict) -> dict:
    """Write P03's own rows. Called only from inside a locked transition."""
    tracker = append_row(tracker, "Quorum", _quorum_row(event))
    if event["status"] != "adopted":
        tracker = append_row(tracker, "Escalations", _escalation_row(event))
    return tracker


def quorum_tracker_rows(run_dir: str) -> list[dict]:
    """The `## Quorum` mirror, re-derived for the terminal report.

    Provenance must be visible in three places — the decision record, the tracker
    index, and the terminal report. A provenance field read only by a validator
    has informed nobody.
    """
    return [_quorum_row(event) for event in quorum_events(run_dir)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run the full phase suite:

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

Expected: all tests PASS; the second command prints nothing.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): reject quorum answers that overrule a human, go too deep, or turn a one-way door"
```

---

### Task 13: Consuming a re-open's raised bar

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Test: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `open_quorum`, `_compute_quorum_result`, `build_payload`, `quorum_events`, `derive_qid`, `RUNG_ORDER`
- Produces: `derive_reopen_qid(question, axis, original_decision_id) -> str`, re-open handling inside `open_quorum`, `build_payload` and `_compute_quorum_result`

P06 found the gap: a re-open records a raised bar and **nothing consumes it**. That is the nastiest shape of defect in this design, because every test asserting the quorum row's contents passes — the bar is right there in the data — while adoption never reads it. A silent no-op in a guardrail is worse than an absent guardrail, because the absent one gets noticed.

Three rules, each with its own failure if dropped:

- **A re-opened question adopts only on a rung strictly higher than the one originally adopted** — not merely at or above the floor. A `code-evidenced` answer re-opening a `code-evidenced` decision does not adopt, even unanimous, even clearing the floor. Re-deciding at the same quality of evidence is not new information; it is the run rolling the dice again.
- **At most one re-open per decision lineage per run.** A second challenge to the same D-ID halts rather than opening a third quorum. This is the anti-oscillation rule; without it a run spends its budget arguing with itself.
- **The re-open payload carries the challenging evidence but never the original rung or who chose it.** A brain that learns the prior answer was adopted at `code-evidenced` treats it as soft; a brain that sees only the question and the challenge treats it on its merits. The prior *answer* stays visible through `decisions-effective.md`, which is deliberate — brains must not re-litigate settled ground by accident — but the projection carries no value and no owner, so nothing there prices it either.

A re-open needs its own identity: the original qid is settled, and `open_quorum` would return the replay. `derive_reopen_qid` namespaces the axis with the challenged D-ID, so the identity stays deterministic — a compaction mid-re-open replays inert exactly like any other quorum — while the lineage stays legible in the qid's input.

**The test below is three cases, and case 3 is what makes the other two mean anything.** Without the control, cases 1 and 2 both pass against an implementation that escalates everything: you would have proven the strict path rejects without ever proving the lenient path accepts. A one-sided assertion is satisfied by a stuck implementation. Apply this shape wherever a rule makes a bar *stricter* — always pair it with an unchanged case that must still pass.

- [ ] **Step 1: Write the failing tests**

```python
class ReopenRaisedBar(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root, self.run_dir = quorum_run(self.stack)
        write_repo(self.root, "db/engine.py", "class PostgresEngine:\n")
        write_repo(self.root, "db/pool.py", "PostgresEngine pool\n")
        write_repo(self.root, "spec.md", "The session table is the run's own store.\n")
        (self.run_dir / "decisions.md").write_text(
            HUMAN.replace("- **Axis:** storage-engine", "- **Axis:** unrelated-axis"),
            encoding="utf-8")
        # An adopted quorum decision at code-evidenced, for the challenge to aim at.
        self.original = self.settle("storage-engine", "postgres", "code-evidenced")

    def settle(self, axis, answer_key, rung):
        record = dict(QUESTION, axis=axis, question=f"Which engine for {axis}?")
        result = self.run_quorum(record, [graded(self.root, answer_key, rung),
                                          graded(self.root, answer_key, rung),
                                          graded(self.root, "duckdb", "speculation")])
        self.assertEqual(result["status"], "adopted")
        return result

    def run_quorum(self, record, payloads):
        path = self.run_dir / f"q-{record['axis'].replace('#', '_').replace(':', '_')}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        opened = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(path))
        if opened["status"] != "in_flight":
            return opened
        for owner, payload in zip(record["owners"], payloads):
            pipeline_auto_state.record_brain_response(
                str(self.run_dir), qid=opened["qid"], owner=owner,
                payload=dict(payload, qid=opened["qid"]))
        return pipeline_auto_state.finalize_quorum(str(self.run_dir), qid=opened["qid"])

    def reopen_record(self, axis="storage-engine"):
        return dict(QUESTION, axis=axis, question=f"Which engine for {axis}?",
                    reopen_of=self.original["decision_id"],
                    challenge_evidence=[{"kind": "repo", "path": "db/pool.py", "line": 1,
                                         "quote": "PostgresEngine"}])

    # --- case 1: the same rung does not clear a raised bar -------------------
    def test_code_evidenced_unanimity_does_not_adopt_on_a_reopened_question(self):
        result = self.run_quorum(self.reopen_record(),
                                 [graded(self.root, "sqlite", "code-evidenced")] * 3)
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["reason"], "raised-bar-not-cleared")
        self.assertEqual(result["raised_bar_rung"], "code-evidenced")
        self.assertEqual(result["reopen_of"], self.original["decision_id"])

    # --- case 2: a strictly higher rung does clear it ------------------------
    def test_specified_adopts_on_the_same_reopened_question(self):
        result = self.run_quorum(self.reopen_record(),
                                 [graded(self.root, "sqlite", "specified"),
                                  graded(self.root, "sqlite", "specified"),
                                  graded(self.root, "duckdb", "speculation")])
        self.assertEqual(result["status"], "adopted")
        self.assertEqual(result["winner"]["rung"], "specified")
        self.assertEqual(result["reopen_of"], self.original["decision_id"])

    # --- case 3: THE CONTROL. Without it, an implementation that escalates
    # everything passes cases 1 and 2 and the raised bar is still a no-op.
    def test_the_same_code_evidenced_answer_adopts_on_a_question_never_reopened(self):
        record = dict(QUESTION, axis="log-format", question="Which engine for log-format?")
        result = self.run_quorum(record, [graded(self.root, "sqlite", "code-evidenced")] * 3)
        self.assertEqual(result["status"], "adopted")
        self.assertEqual(result["winner"]["rung"], "code-evidenced")
        self.assertIsNone(result["raised_bar_rung"])

    # --- anti-oscillation ----------------------------------------------------
    def test_a_second_challenge_to_the_same_decision_halts_without_dispatch(self):
        self.run_quorum(self.reopen_record(),
                        [graded(self.root, "sqlite", "code-evidenced")] * 3)
        second = self.run_quorum(self.reopen_record(),
                                 [graded(self.root, "duckdb", "specified")] * 3)
        self.assertEqual(second["status"], "halted-second-challenge")
        self.assertFalse(second["dispatched"])
        qid = pipeline_auto_state.derive_reopen_qid(
            "Which engine for storage-engine?", "storage-engine", self.original["decision_id"])
        self.assertEqual(list((self.run_dir / "quorum" / qid).glob("payload-*.json")), [])

    def test_a_reopen_gets_its_own_deterministic_identity(self):
        first = pipeline_auto_state.derive_reopen_qid("q", "axis", "Q-aaaaaaaaaaaa")
        self.assertEqual(first, pipeline_auto_state.derive_reopen_qid("q", "axis", "Q-aaaaaaaaaaaa"))
        self.assertNotEqual(first, pipeline_auto_state.derive_qid("q", "axis"))
        self.assertNotEqual(first, pipeline_auto_state.derive_reopen_qid("q", "axis", "Q-bbbbbbbbbbbb"))

    # --- what the brains may and may not see ---------------------------------
    def test_the_reopen_payload_carries_the_challenge_but_never_the_prior_rung(self):
        record = self.reopen_record()
        path = self.run_dir / "q-reopen-payload.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        opened = pipeline_auto_state.open_quorum(str(self.run_dir), question_record=str(path))
        for index in range(3):
            payload = pipeline_auto_state.build_payload(
                opened["qid"], index, run_dir=str(self.run_dir))
            rendered = json.dumps(payload)
            self.assertIn("db/pool.py", rendered)
            self.assertNotIn("code-evidenced", rendered)
            self.assertNotIn(self.original["winner"]["owner"], rendered)
            self.assertNotIn("raised_bar", rendered)
            for leak in ("0.95", "0.85", "0.70", "0.55", "0.30"):
                self.assertNotIn(leak, rendered)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -k ReopenRaisedBar -v`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'derive_reopen_qid'`, and case 1 fails with `'adopted' != 'escalated'` once that is added, which is the gap itself.

- [ ] **Step 3: Write the implementation**

Add the identity helper and the lineage check:

```python
def _mirror_terminal(run_dir, event: dict) -> None:
    """Mirror a record that terminated without ever reaching finalize_quorum.

    Uses the spec's mandated transition id, so a replay after a compaction is
    inert exactly as it is for an ordinary finalisation.
    """
    locked_tracker_update(str(run_dir), transition_id=f"quorum-{event['qid']}",
                          mutate=lambda tracker: _mirror_quorum(tracker, event))


def derive_reopen_qid(question: str, axis: str, original_decision_id: str) -> str:
    """A re-open needs its own identity.

    The original qid is settled, so open_quorum would return its replay. The
    challenged D-ID namespaces the axis, which keeps the identity deterministic —
    a compaction mid-re-open replays inert like any other quorum — and keeps the
    lineage legible in the qid's own input.
    """
    return derive_qid(question, f"{axis}#reopen:{original_decision_id}")


def _reopen_lineage_root(run_dir, decision_id: str) -> str:
    """Follow the challenge chain back to the decision it all started from."""
    by_decision = {event["decision_id"]: event for event in quorum_events(run_dir)
                   if event.get("decision_id")}
    seen, current = set(), decision_id
    while current in by_decision and by_decision[current].get("reopen_of"):
        if current in seen:
            break
        seen.add(current)
        current = by_decision[current]["reopen_of"]
    return current


def _prior_reopens(run_dir, root: str) -> list[dict]:
    return [event for event in quorum_events(run_dir)
            if event.get("reopen_of") and _reopen_lineage_root(run_dir, event["reopen_of"]) == root]
```

In `open_quorum`, immediately after the admissibility check, replace the qid derivation with the re-open-aware form and add the lineage gate:

```python
    challenged = str(record.get("reopen_of") or "")
    if challenged:
        qid = derive_reopen_qid(record["question"], record["axis"], challenged)
    else:
        qid = derive_qid(record["question"], record["axis"])
    directory = _quorum_root(run_dir) / qid
    final_path = directory / "final.json"

    if final_path.exists():
        settled = _load_json(final_path)
        return dict(settled, replay=True, qid=qid)
    if (directory / "open.json").exists():
        return dict(_load_json(directory / "open.json"), status="in_flight", replay=True, qid=qid)

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "responses").mkdir(exist_ok=True)
    (directory / "question.json").write_text(_dumps(record), encoding="utf-8")

    raised_bar_rung = None
    if challenged:
        # At most one re-open per lineage per run. A second challenge halts
        # rather than opening a third quorum: without this the run spends its
        # budget arguing with itself.
        root = _reopen_lineage_root(run_dir, challenged)
        if _prior_reopens(run_dir, root):
            halt = {"qid": qid, "status": "halted-second-challenge",
                    "reason": f"{challenged} has already been re-opened once in this run",
                    "phase": record["phase"], "axis": record["axis"],
                    "reopen_of": challenged, "lineage_root": root,
                    "decision_id": None, "winner": None, "dispatched": False,
                    "context_digest": _context_digest(run_dir)}
            publish_immutable(str(final_path), _dumps(halt))
            _mirror_terminal(run_dir, halt)
            return halt
        raised_bar_rung = _adopted_rung(run_dir, challenged)
```

with the rung lookup, which reads the *record*, never the payload:

```python
def _adopted_rung(run_dir, decision_id: str) -> str:
    for event in quorum_events(run_dir):
        if event.get("decision_id") == decision_id and event["status"] == "adopted":
            return event["winner"]["rung"]
    decisions_path = Path(run_dir) / "decisions.md"
    if decisions_path.exists():
        record = parse_decisions(decisions_path.read_text(encoding="utf-8"))["decisions"].get(decision_id)
        if record and record.get("grounding_rung") in RUNGS:
            return record["grounding_rung"]
    raise QuorumError(f"cannot re-open {decision_id}: it has no adopted rung on record")
```

Carry the bar into `open.json` by extending the `opened` dict built later in the same function:

```python
    opened = {
        "qid": qid, "status": "in_flight", "axis": record["axis"], "phase": record["phase"],
        "owners": list(record["owners"]),
        "question_digest": _digest(_squash(record["question"])),
        "payload_digest": digest,
        "context_digest": _context_digest(run_dir),
        "options_supplied": bool(record.get("options_supplied")),
        "blocks": list(record.get("blocks") or ()),
        "reopen_of": challenged or None,
        "raised_bar_rung": raised_bar_rung,
    }
```

No change is needed in `build_payload`: `_shared_payload` already whitelists
`challenge` from the question record's `challenge_evidence`, and the prior rung
and the prior owner are simply never named there, so they cannot leak. Keeping
the challenge inside the *shared* payload is also what preserves the single-digest
binding — a challenge added per-index would break the `(payload_digest, n)`
reproduction the recovery path depends on.

In `_compute_quorum_result`, carry the lineage into the record and apply the bar immediately after the strictness test, before `_apply_adoption_gates`:

```python
    base = {"qid": qid, "axis": opened["axis"], "phase": opened["phase"],
            "context_digest": opened["context_digest"], "decision_id": None,
            "winner": None, "runner_up_rung": None, "effective_rungs": {}, "dispatched": True,
            "payload_digest": opened["payload_digest"],
            "reopen_of": opened.get("reopen_of"),
            "raised_bar_rung": opened.get("raised_bar_rung")}
```

```python
    # A re-open adopts only on evidence STRICTLY BETTER than the decision it
    # challenges. Re-deciding at the same quality of evidence is not new
    # information; it is the run rolling the dice again. Nothing else consumes
    # this field, so an implementation that records the bar and ignores it here
    # passes every row-content assertion in the suite.
    raised = base["raised_bar_rung"]
    if raised is not None and RUNG_ORDER.index(winner_rung) >= RUNG_ORDER.index(raised):
        return dict(base, status="escalated", reason="raised-bar-not-cleared",
                    winner_rung=winner_rung)

    best = max(winner, key=lambda member: (RUNG_ORDER.index(member["effective_rung"]) * -1,))
    return _apply_adoption_gates(run_dir, base, winner, best, winner_rung)
```

`_quorum_row` already carries `Reopen Of` and `Raised Bar`, so the mirror shows
the lineage as soon as `_compute_quorum_result` puts them in `base`. No change is
needed there — but if `section_columns("Quorum")` does not yet contain those two
columns, `_row_for` raises immediately and P02 owns adding them. That is the seam
working as intended: a missing column fails at the write, never silently.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

Expected: all tests PASS, including all three `ReopenRaisedBar` cases; the second command prints nothing. P06's `RaisedBarIsApplied` — which drives this same path through `open_quorum`, three `record_brain_response` calls, and `finalize_quorum` — goes green from the other side once this lands.

- [ ] **Step 5: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py \
        plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py
git commit -m "feat(pipeline-auto): make a re-open's raised bar actually gate adoption"
```

---

## Self-review

**Spec coverage.** Every clause of "The quorum contract" maps to a task.
Admissibility → Task 6. `qid` derivation and the excluded decisions digest →
Task 1, re-asserted in Task 8. The rung table and its schema-constant status →
Task 1. Citation resolution and demotion → Task 3. The three further demotions →
Task 3. The run-level inflation check → Task 11 (`current_floor`). Independence,
reading assignments and the prohibition list → Task 6. `decisions-effective.md` →
Task 4. Comparing prose answers → Task 11. Adoption arithmetic, rung strictness,
equal-rung refusal, vacuous strictness under unanimity → Task 11. The retired
three-way-split rule is asserted *absent* by
`test_one_spec_citation_beats_two_speculations`. Drift budget and the raise-time
trip → Tasks 7 and 8. Budget extension → Task 7. Replay and idempotency → Tasks 8
and 10. Contradicting a human answer, contradicting an earlier quorum answer,
depth cap, irreversible axes → Tasks 5 and 12. Provenance visible in three places
→ Tasks 4 (record), 12 (tracker rows), and P06 (terminal report).

**Gap found and closed.** The spec's "the axis index in `decisions.md` is
validated on every write" had no writer. `_ensure_decision_recorded` now
re-parses the file after appending, so a write that would create two adopted
contradicting answers on one axis fails immediately rather than at the next read.

**Second gap found and closed.** `final.json` is published *before* the decision
is appended, and `_ensure_decision_recorded` is idempotent and is also called on
the replay path. The reverse order would double-append after an interruption
between the two writes; this order leaves a repairable hole instead of a
corrupted audit trail.

**Third gap found and closed.** The budget check moved out of `finalize_quorum`
entirely. With it in both places, three brains are dispatched and *then* refused,
which is the spend the budget exists to prevent.

**Fourth gap, found by P06 and closed in Task 13.** The re-open path recorded a
raised bar that nothing read. Every assertion about the quorum row's *contents*
passed — the bar was in the data — while adoption never consulted it, which is
the worst shape a guardrail defect can take, because an absent guardrail gets
noticed and a silent one does not. Task 13 consumes it in
`_compute_quorum_result`, and its three-case test carries the control that makes
the other two cases mean anything.

**Placeholder scan.** No TBDs, no "add error handling", no "similar to Task N".
Every step carries the code it needs. The one forward reference —
`_apply_adoption_gates` in Task 11 — is a working stub with real behaviour that
Task 12 replaces, not a placeholder, and Task 11's tests pass against it.

**Fifth gap, ruled by the coordinator and closed in Tasks 3, 11 and 12.**
`_repo_root` is deleted. The root is a `## Run` field read with P02's
`repo_root(tracker)` and passed to `effective_rung(response, repo_root)`; nothing
in the phase computes it. The named test
`test_a_wrong_repo_root_silently_demotes_every_grounded_answer` guards the one
failure in this design with no error, no exception and no other failing test:
a wrong root resolves nothing, so every grounded answer falls to 0.55, so the run
escalates every question while looking correctly cautious. `quorum_run` now builds
the run at its production depth and asserts the recorded root, so a disagreement
with P02 surfaces at the seam.

**One-sided-assertion scan.** Every task that makes a bar *stricter* pairs its
rejection case with a case that must still be accepted: Task 3's
`test_convention_cited_needs_two_exemplars` asserts both the demotion and the
two-exemplar pass; Task 11 pairs the unanimous `convention-cited` escalation with
the unanimous `code-evidenced` adoption; Task 13 carries P06's explicit control.
A stuck implementation that refuses everything fails all three.

**Type consistency.** `effective_rung` and `cluster_rung` both return rung
*names*; every comparison in the module uses `RUNG_ORDER.index`, and the only
float comparison in the phase is against `floor_value` in `_compute_quorum_result`
— there is no float comparison between two clusters anywhere. `check_contradiction`
returns a D-ID or `None`. `quorum_budget` returns `may_raise`/`reason`, which is
what `open_quorum` branches on. `group_responses` returns index lists, which
`_compute_quorum_result` maps to owner-tagged members before calling
`cluster_rung`, so `cluster_rung`'s input always carries `effective_rung`.

---

## Unresolved — reported, not invented

Each of these is something the spec and master plan do not settle. None has been
guessed at in code beyond the minimum noted; each needs a ruling.

1. ~~`build_payload(qid, brain_index)` has no way to find the run.~~
   **Settled.** `build_payload(qid, brain_index, *, run_dir)` is the pinned
   signature; the question record is read from
   `<run_dir>/quorum/<qid>/question.json`. Also settled, after a correction from
   the coordinator that P04 caught against the committed fixture: `## Quorum`'s
   `Payload Digest` is **one digest, not three** — over the shared payload plus
   the decisions projection. It binds all three brains because the reading
   assignment is a constant rule rather than data and `build_payload` is pure
   with respect to the index, so brain n is reproducible from
   `(payload_digest, n)`. **The condition under which this stops holding** is
   named in the code: if anything about the assignment is ever read from the
   tracker or from run state, the single digest no longer binds and the
   partial-recovery path would silently re-dispatch a brain with a payload
   different from the one it first received. `test_one_digest_binds_all_three_
   and_rebuilds_each_byte_for_byte` is the guard.

2. ~~P02 publishes no `## Quorum` / `## Escalations` row grammar.~~
   **Settled.** P02 owns the column grammar and exposes `section_columns(name)`
   and `append_row(tracker, section, row)`; P03 owns the quorum lifecycle and so
   writes its own rows through those, inside `locked_tracker_update`. No phase
   writes another phase's rows; no phase re-declares another phase's columns.
   `quorum_tracker_rows()` builds against `section_columns("Quorum")` rather than
   a local tuple, so a column change in P02 breaks loudly at the seam. `reopen_of`
   and `raised_bar_rung` are carried as `Reopen Of` and `Raised Bar`.

3. **The tie-break by strict consequence subset can never produce an adoption.**
   The spec lists it between "higher rung wins" and "escalate", but it also says
   equal rungs never adopt, so any pair the subset rule could separate has
   already escalated. This plan implements the subset rule as *report ordering*
   only — it decides which cluster is named "winner" in the escalation record, so
   the human sees the less-foreclosing answer first. If it was meant to be able
   to adopt, the equal-rung rule and this one need reconciling.

4. **`agent_dispatch_count` has no threshold values.** The spec names the counter
   and says a soft threshold escalates reporting and a hard one stops the run
   resumably, but gives no numbers and no owner. P03 does not implement it. The
   drift budget it sits beside is implemented in full.

5. **Two stale references in the spec's "Failure modes" section.** It still says
   an answer anchored only in repository code is "capped at `general-practice`"
   and that provisionality propagates below **0.80** — both from the superseded
   six-tier table. This plan reads the first as `engineering-judgement` (the
   current demotion rung, likewise below the floor). The second is P05's and is
   now **dead as written**: with the new ladder nothing between 0.85 and 0.70
   exists, so "below 0.80" selects exactly the rungs that can never be adopted.
   P05 needs a rung name, not a number.

6. **`quorum.extend-budget` is absent from the spec's narrowed decision-action
   vocabulary.** "State schema" says actions narrow to
   `task.resume | quorum.adopt | none`, while "Budget extension" requires a
   fourth. This plan accepts all four in `parse_decisions`. The vocabulary
   sentence needs updating, or the extension needs a different carrier.

7. **`initialize_run` does not name artifact paths.** P02's signature takes no
   `artifacts` mapping, so P03 assumes `<run_dir>/decisions.md` and
   `<run_dir>/decisions-effective.md` by convention. If P02 lands a different
   layout, `_context_digest`, `_ensure_decision_recorded` and `open_quorum` need
   the real path.

8. ~~Evidence paths resolve against `Path(run_dir).parents[0]`.~~
   **Settled, and the function is deleted.** `repo_root` is a `## Run` field
   written by `initialize_run` and read back with P02's `repo_root(tracker)`;
   P03 computes no repository root by any means. Standing rule 8 states the
   failure shape and Task 3 carries the test.

9. **The findings ledger marker `pipeline-auto-findings/v1` is derived, not
   specified.** It follows the schema family name; the spec fixes only the
   tracker marker. This is the only item still open, and it is cosmetic.

Items 1, 2 and 8 are closed by coordinator ruling. Items 3–7 and 9 remain
reported; none blocks execution of this phase.
