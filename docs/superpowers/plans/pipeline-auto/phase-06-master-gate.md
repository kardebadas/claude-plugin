# P06 — Master Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build stages 11 and 12 of `pipeline_auto_state.py` — the phase-set freeze that makes scope expansion structurally impossible, the two-reviewer master gate with independence checked against owner *history*, `DECISION-CHALLENGE` routing that never lets a reviewer overrule the one human gate, the completeness freeze, evidence-derived acceptance, final verification, and a terminal report that opens with every decision the run made without the user.

**Architecture:** The phase set is sealed by a stage-06 transition that publishes an immutable `phase-set.json`; every P06 entry point re-checks the seal, and `create_phase` — the only writer of a `## Phases` row — refuses after the seal exists. That single guard is what turns "never invent scope" from a rule into an unavailable operation, and it is why the completeness critic's `MISSING-FROM-SPEC` class can be frozen to a file rather than policed. Above it sit three pure routers (`route_contradiction`, `classify_completeness_item`, `raised_floor`) and four durable transitions (`open_master_gate`, `record_master_report`, `evaluate_master_gate`, `record_final_verification`), all of which derive their conclusions from files and none of which accept a caller's verdict as input.

**Tech Stack:** Python 3 standard library only (`hashlib`, `json`, `pathlib`, `re`). `unittest` for tests — **pytest is not installed on this machine and no test in this phase may import it**. Markdown for `findings.md`, `completeness-proposals.md`, reviewer packets, reports and the terminal report; JSON for the sealed gate records.

**Spec:** `docs/superpowers/specs/2026-09-14-pipeline-auto-design.md` — "Governing invariants" 6 and 7, "Contradiction routing", "Completeness proposals", the stage 11/12 rows, and "Cascading on a low-confidence answer"

**Master plan:** `docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md` — Global Constraints, the P02/P03/P04/P05 interface blocks, and the run-wide Verification suite

**Depends on:** P05 (`dial-and-gate`), and through it P02, P03 and P04. Every signature those phases publish is assumed to exist and work.

**Review class:** `required`

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

### P06-specific standing rules

Each has at least one test in this plan. They are restated because each is a rule
a competent engineer would "simplify" into exactly the bug it exists to prevent.

1. **`create_phase` is the only function that ever appends a `## Phases` row, and it is dead after stage 06.** If any other function in this phase grows the phase set, the structural guarantee is gone and every prose rule about scope becomes decoration.
2. **Independence is checked against owner *history*, never against current owner cells.** `row["owner"] for row in tracker["tasks"]` is the wrong set and looks like the right one.
3. **`SPEC-NOT-MET` is not a proposal.** It is a Critical finding at the zero-open-findings bar. `MISSING-FROM-SPEC` is frozen and never dispatched. The controller routes on `traces_to`, never on the label the critic typed.
4. **A reviewer finding prevails over a recorded decision only when it is Critical or Important AND its verdict part is `spec-compliance` or `verification-evidence`.** Any other combination goes to reconciliation. "The reviewer is the later, more informed voice" is the plausible, wrong simplification.
5. **A reconciliation never increments a fix-round counter.** A decision dispute must not burn the three-round budget and escalate for the wrong reason.
6. **A `DECISION-CHALLENGE` against `Provenance: human` halts. Always.** Not "usually", not "unless Critical". Zero brain dispatches, at any confidence, at any severity.
7. **Acceptance is derived, never supplied.** No function in this phase takes an `accepted=` parameter, a `base=`, or a `head=`. A caller who can assert acceptance or choose the reviewed edge *is* the gate.
8. **The terminal report leads with the weakest quorum decision.** Not the most recent, not the highest-blast, not alphabetical. A provenance field read only by a validator has informed nobody.

---

## What this phase owns, and what it deliberately does not

Owned: the stage-06 seal and its guard; `## Gates` master-row transitions; reviewer
assignment and independence; the two reviewer packets; the master report block grammar;
`findings.md` parse/render/upsert; the contradiction routing table; the challenge ledger
and the raised-bar re-open record; unbiased reconciliation; the completeness critic's two
classes and the proposals file; evidence-derived master acceptance; the stage-12 run-wide
suite contract; the terminal report.

Not owned: per-task review rows and the fix-round *machinery* (P05 — P06 reads the rows
and writes at most a finding disposition); adversarial triggers and the ratchet (P05);
quorum dispatch, clustering, rungs, budget (P03 — P06 never opens a quorum, it only
routes to one); task reserve/resume/integration (P04); the tracker grammar itself (P02).

P06 creates **no** prose, **no** agent file and **no** prompt template. `references/review.md`
is P07's; the packets this phase builds are the machine-generated half of what P07's
`prompts/` will wrap.

---

## File Structure

| File | Responsibility | P06 action |
| --- | --- | --- |
| `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py` | The spine. P06 appends a `# --- master gate ---` section below P05's code; P06 adds no new module | Modify |
| `plugins/superb/skills/pipeline-auto/templates/completeness-proposals.md` | The frozen-proposals file's header and the reasoning a maintainer needs to defend the freeze | Create |
| `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py` | Unit tests; P06 appends its own `class MasterGate*` / `class PhaseSet*` test classes | Modify |
| `plugins/superb/skills/pipeline-auto/tests/fixtures/stage-06-progress.md` | A valid tracker with stage 06 **active** and an empty phase set — the only state in which work may be created | Create |
| `plugins/superb/skills/pipeline-auto/tests/fixtures/master-gate-progress.md` | A valid tracker with every phase verified and stage 11 active — the state the master gate opens from | Create |
| `plugins/superb/skills/pipeline-auto/tests/fixtures/master-gate-decisions.md` | One human decision and two quorum decisions at different rungs; external truth for packet and report ordering | Create |
| `plugins/superb/skills/pipeline-auto/tests/fixtures/master-gate-findings.md` | A findings ledger carrying one already-resolved finding | Create |

### Durable layout P06 owns

```text
<run_dir>/
├── phase-set.json                   # sealed at stage-06 close; the immutability evidence
├── completeness-proposals.md        # frozen proposals; never a task, never dispatched
├── terminal-report.md               # published once, at stage-12 close
└── gate-master/
    ├── assignments.json             # sealed roles, reviewers, base, head, owner history
    ├── packet-A.md                  # requirements / decisions reviewer
    ├── packet-B.md                  # integration / architecture reviewer
    ├── reports/master-A.md          # immutable, digest-bound
    ├── reports/master-B.md
    ├── challenges.json              # append-only; a D-ID appearing twice is an automatic halt
    ├── reconciliations/<F-ID>.md    # the reconciliation question the task points at
    ├── completeness.json            # the critic's classified items
    ├── verification.json            # digest-bound master-gate PASS at the reviewed head
    └── final-verification.json      # the stage-12 run-wide suite record
```

`quorum/<qid>/reopen.json` is written by P06 and read by P03's dispatch path. It is the
only file P06 places under a directory another phase owns, and it carries the challenging
evidence and nothing else.

---

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
def locked_tracker_update(run_dir: str, *, transition_id: str, mutate) -> dict: ...
def publish_immutable(path: str, content: str) -> str: ...
def derive_next_action(tracker: dict) -> str: ...
def append_row(tracker: dict, section: str, row: dict) -> dict: ...
def repo_root(tracker: dict) -> str: ...

SECTIONS: dict[str, tuple[str, ...]]
STAGES: tuple[str, ...]                  # "01".."12"
_REVIEW_CLASSES = ("final-only", "required")
_GATE_STATES = ("pending", "in_progress", "blocked", "accepted")
```

Two behaviours P06 depends on and must not re-implement:

- `locked_tracker_update` validates, locks, re-reads, revalidates, applies `mutate`,
  renders, reparses, atomically replaces, and **returns the resulting tracker dict**.
  A replayed `transition_id` returns current state without calling `mutate` at all —
  that is what makes `close_phase_set` and `evaluate_master_gate` replay-inert.
- `publish_immutable(path, content)` writes once and **returns the sha256 hex digest of
  the content, not the path**; a byte-identical second call is a no-op returning the same
  digest; a differing second call raises. That is what makes `assignments.json`, each
  report, and `final-verification.json` single-assignment cells.

`append_row(tracker, section, row)`'s `section` argument is spelled as the tracker dict
key — `"phases"`, `"escalations"` — matching `SECTIONS`. If P02 keyed `SECTIONS` by the
`## `-prefixed heading instead, change the two call sites in this phase; **do not add a
second appender.**

### Consumes from P03

```python
RUNGS: Mapping[str, float]
RUNG_ORDER: tuple[str, ...]              # highest rung first; compare by index, never value
ADOPTION_FLOOR = 0.85

def derive_qid(question: str, axis: str) -> str: ...
def parse_decisions(text: str) -> dict: ...   # {"decisions": {D-ID: record}, "axis_index": {...}}
def check_admissible(record: dict) -> list[str]: ...   # [] when admissible
def open_quorum(run_dir: str, *, question_record: str) -> dict: ...
def quorum_events(run_dir: str) -> list[dict]: ...
class QuorumError(TrackerError): ...
```

A `parse_decisions` record carries `id`, `axis`, `provenance`, `action`, `answer`,
`answer_key`, `status`, `depth`, `consequences`, `consistent_with`, plus every raw field
lowercased with spaces replaced by underscores — so `- **Grounding rung:** specified`
reaches P06 as `record["grounding_rung"]` and `- **Scope:** P02-T01` as `record["scope"]`.

### Consumes from P04 and P05

```python
def reconcile_run(run_dir: str) -> dict: ...
def verify_source_range(repo: str, *, baseline: str, head: str, scopes: list) -> dict: ...
def open_fix_round(run_dir: str, *, scope: str, findings: list) -> dict: ...
```

P06 calls none of these inside a transition. They are named because the controller prose
in P07 sequences them around this phase's functions, and because Task 7's test asserts
that a reconciliation leaves P05's fix-round rows untouched.

### Produces — consumed by P07 (prose), P08 (pressure GREEN) and P09 (walkthrough)

```python
PHASE_SET_STAGE = "06"
MASTER_GATE_ID = "gate-master"
SEVERITIES = ("Critical", "Important", "Minor")
VERDICT_PARTS = ("spec-compliance", "quality", "verification-evidence")
CRITIC_CLASSES = ("SPEC-NOT-MET", "MISSING-FROM-SPEC")
ROUTES = ("ordinary-fix-loop", "ordinary-quorum", "adjudicator", "reopen-raised-bar",
          "unbiased-reconciliation", "reviewer-prevails", "halt-escalation",
          "halt-second-challenge")
MASTER_REPORT_MARKER = "<!-- pipeline-auto-review-report/v1 -->"
PROPOSALS_MARKER = "<!-- pipeline-auto-completeness-proposals/v1 -->"
TERMINAL_REPORT_HEADING = "## Decisions this run made without you"

class GateError(TrackerError): ...
class PhaseSetFrozen(TrackerError): ...
class ReviewerIndependenceError(GateError): ...

def phase_set_frozen(tracker: dict) -> bool: ...
def assert_phase_set_intact(run_dir: str, tracker: dict | None = None) -> list[str]: ...
def create_phase(run_dir: str, *, phase_id: str, review_class: str) -> dict: ...
def close_phase_set(run_dir: str) -> dict: ...

def owner_history(run_dir: str) -> frozenset[str]: ...
def open_master_gate(run_dir: str, *, reviewers: dict) -> dict: ...
def tainting_decisions(run_dir: str) -> dict: ...
def build_reviewer_packet(run_dir: str, *, role: str) -> str: ...

def parse_findings(text: str) -> list[dict]: ...
def render_findings(rows: list[dict]) -> str: ...
def upsert_finding(run_dir: str, row: dict) -> list[dict]: ...
def open_findings(run_dir: str) -> list[dict]: ...
def parse_master_report(text: str) -> dict: ...
def record_master_report(run_dir: str, *, assignment: str, report_path: str) -> dict: ...

def route_contradiction(decisions: dict, item: dict, *, prior_challenges=()) -> dict: ...
def raised_floor(rung: str) -> str: ...
def record_challenge(run_dir: str, *, challenge: dict) -> dict: ...

def open_reconciliation(run_dir: str, *, finding_id: str, decision_id: str, scope: str) -> dict: ...
def record_reconciliation(run_dir: str, *, finding_id: str, decision_id: str,
                          adjudicator: str, outcome: str, evidence: str) -> dict: ...
def supersede_decision(run_dir: str, *, decision_id: str) -> str: ...

def classify_completeness_item(item: dict) -> str: ...
def record_completeness(run_dir: str, *, items: list) -> dict: ...
def completeness_proposals(run_dir: str) -> list[dict]: ...

def evaluate_master_gate(run_dir: str) -> dict: ...
def final_suite_commands(base_commit: str, project_root: str) -> tuple[tuple[str, ...], ...]: ...
def record_final_verification(run_dir: str, *, results: list) -> dict: ...
def derive_terminal_action(run_dir: str) -> str: ...
def render_terminal_report(run_dir: str) -> str: ...
def publish_terminal_report(run_dir: str) -> str: ...
```

**Type notes for downstream implementers.** `route_contradiction` returns
`{"route", "reason", "decision_id", "dispatch_brains"}`; `route` is one of `ROUTES` and
`dispatch_brains` is a bool that is `True` for exactly two routes. `classify_completeness_item`
returns a member of `CRITIC_CLASSES` or raises — it never returns `None`.
`evaluate_master_gate` returns `{"accepted": bool, "blockers": list[str]}` and takes no
verdict. `raised_floor` returns a rung **name**. `owner_history` returns a `frozenset`, so
a caller cannot mutate the set it checked against.

---

## Data contracts P06 defines

### Master review report — the terminal block

Each report preserves its technical narrative first and ends with exactly one block.
Nothing but blank lines may follow it.

```markdown
# Master review — reviewer A

...narrative, findings discussion, evidence...

## Findings

| Finding | Severity | Verdict Part | Traces To | Requires Reversal Of | Claim |
| --- | --- | --- | --- | --- | --- |
| F-101 | Minor | quality | none | Q-7c6b5a4938d2 | `render_tracker` should be called `emit_tracker`. |

<!-- pipeline-auto-review-report/v1 -->
| Field | Value |
| --- | --- |
| gate | gate-master |
| assignment | master-A |
| reviewer | reviewer-a |
| base | c8bddd610119f52b54bf077d284c7f5d8362ae77 |
| head | 4444444444444444444444444444444444444444 |
| findings | F-101 |
| outcomes | {"F-101":"Open"} |
```

`Traces To` is a `<path>.md:<line>` that resolves, or the literal `none`.
`Requires Reversal Of` is a recorded D-ID, or `-`. A clean report uses `findings=-`
and `outcomes={}` and omits the `## Findings` table.

### `DECISION-CHALLENGE` record

```json
{
  "kind": "DECISION-CHALLENGE",
  "decision_id": "H-001",
  "reviewer": "reviewer-a",
  "evidence": "scripts/pipeline_auto_state.py:812",
  "consequence": "A thirty-second bound drops every transition on a contended NFS mount."
}
```

There is no `requested_answer`, `proposed_answer` or `replacement_answer` key, and the
presence of one is an error rather than an ignored field. A reviewer reports what a
decision **costs**; it never proposes the answer that would replace it.

### Completeness critic item

```json
{
  "id": "F-201",
  "class": "SPEC-NOT-MET",
  "traces_to": "docs/superpowers/specs/2026-09-14-pipeline-auto-design.md:517",
  "statement": "The critic's two classes are never written to distinct sinks.",
  "evidence": "scripts/pipeline_auto_state.py:1401",
  "scope": "gate-master"
}
```

`class` and `traces_to` must agree: `SPEC-NOT-MET` cites a spec line, `MISSING-FROM-SPEC`
carries the literal `none`. Disagreement is an error, because relabelling is the only
route by which a proposal could ever enter the fix loop.

### Findings ledger row

P03's `templates/findings.md` fixes the columns:
`ID | Scope | Severity | Status | Disposition | Evidence | Adjudication | Fix Round | Re-review`.
`Status` is `open` or `resolved`. `Disposition` for the one principled exception to
zero-open-findings is the literal string `REFUTED — governed by <D-ID>`.

---

## Verification suite for this phase

Ordered command tuple. All four must pass before P06 is complete.

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v
python3 -c "import ast; ast.parse(open('plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py').read())"
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The third command must print **nothing**. Any output means `skills/pipeline/` was modified
and the phase fails.

**pytest is not installed on this machine** (`python3 -c "import pytest"` raises
`ModuleNotFoundError`; Python is 3.11.2, standard library only). No test in this phase may
`import pytest`, use `pytest.raises`, `pytest.fixture`, `tmp_path`, `monkeypatch`, a
`@pytest.mark` decorator, or a bare assert-style test function. Every test is a
`unittest.TestCase` method using `self.assertRaises`, `setUp`, `tempfile.TemporaryDirectory`
and `unittest.mock.patch` — which also runs unchanged under pytest if it ever appears.

### Test module bootstrap

P02 wrote this block. P02's tests bind the module as `pas`; P03's spell it
`pipeline_auto_state`. Both names refer to the same module object — if only one binding
exists, add the other beside it rather than importing twice.

```python
import importlib.util
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[5]
SPINE = REPOSITORY / "plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py"
_spec = importlib.util.spec_from_file_location("pipeline_auto_state", SPINE)
pipeline_auto_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline_auto_state)
pas = pipeline_auto_state
```

### Shared test helpers — add these once, in Task 1, below the bootstrap

```python
import contextlib, json, shutil, tempfile, unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "c8bddd610119f52b54bf077d284c7f5d8362ae77"
HEAD = "4444444444444444444444444444444444444444"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def new_run(stack, tracker_fixture: str = "master-gate-progress.md"):
    """A temp run directory holding one of P06's tracker fixtures plus its
    decisions ledger, findings ledger and an empty results directory."""
    root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
    run_dir = root / "run"
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "scratch").mkdir()
    (run_dir / "progress.md").write_text(fixture(tracker_fixture), encoding="utf-8")
    (run_dir / "decisions.md").write_text(fixture("master-gate-decisions.md"), encoding="utf-8")
    (run_dir / "findings.md").write_text(fixture("master-gate-findings.md"), encoding="utf-8")
    return root, run_dir


def tracker_of(run_dir) -> dict:
    return pas.parse_tracker((Path(run_dir) / "progress.md").read_text(encoding="utf-8"))


def opened_gate(run_dir, a="reviewer-a", b="reviewer-b") -> dict:
    return pas.open_master_gate(str(run_dir), reviewers={"A": a, "B": b})


def write_result(run_dir, name: str, owner: str) -> Path:
    """A superseded-attempt worker result: the owner is released and the tracker
    no longer names it anywhere."""
    path = Path(run_dir) / "results" / name
    path.write_text(
        "<!-- pipeline-auto-worker-result/v1 -->\n\n"
        f"- **Owner:** {owner}\n- **Status:** SUPERSEDED\n", encoding="utf-8")
    return path


def report_text(*, assignment="master-A", reviewer="reviewer-a", base=BASE, head=HEAD,
                findings=(), gate="gate-master", trailer="") -> str:
    """A master review report. `findings` is a sequence of
    (id, severity, verdict_part, traces_to, requires_reversal_of, claim)."""
    lines = [f"# Master review — {assignment}", "", "Narrative first.", ""]
    if findings:
        lines += ["## Findings", "",
                  "| Finding | Severity | Verdict Part | Traces To | "
                  "Requires Reversal Of | Claim |",
                  "| --- | --- | --- | --- | --- | --- |"]
        lines += ["| " + " | ".join(row) + " |" for row in findings]
        lines.append("")
    ids = ",".join(row[0] for row in findings) or "-"
    outcomes = json.dumps({row[0]: "Open" for row in findings}, separators=(",", ":"))
    lines += [pas.MASTER_REPORT_MARKER,
              "| Field | Value |", "| --- | --- |",
              f"| gate | {gate} |", f"| assignment | {assignment} |",
              f"| reviewer | {reviewer} |", f"| base | {base} |", f"| head | {head} |",
              f"| findings | {ids} |", f"| outcomes | {outcomes} |"]
    if trailer:
        lines += ["", trailer]
    return "\n".join(lines) + "\n"


def publish_report(run_dir, **kwargs) -> dict:
    assignment = kwargs.get("assignment", "master-A")
    path = Path(run_dir) / "scratch" / f"{assignment}-report.md"
    path.write_text(report_text(**kwargs), encoding="utf-8")
    return pas.record_master_report(str(run_dir), assignment=assignment,
                                    report_path=str(path))


def pass_master_verification(run_dir, head: str = HEAD) -> None:
    directory = Path(run_dir) / "gate-master"
    directory.mkdir(exist_ok=True)
    (directory / "verification.json").write_text(
        json.dumps({"head": head, "outcome": "PASS",
                    "command": "python3 -m unittest discover -s tests"}),
        encoding="utf-8")


def suite_results(run_dir, *, third="", fourth="", order=None):
    """A stage-12 results list. `third`/`fourth` are the stdout the two silent
    commands are claimed to have produced."""
    tracker = tracker_of(run_dir)
    commands = pas.final_suite_commands(tracker["run"]["base_commit"], pas.repo_root(tracker))
    commands = order if order is not None else commands
    outputs = ["... 214 passed ...", "walkthrough OK", third, fourth]
    return [{"command": list(command), "exit_code": 0, "stdout": output}
            for command, output in zip(commands, outputs)]
```

---
## Tasks

### Task 1: The phase-set freeze

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/tests/fixtures/stage-06-progress.md`
- Create: `plugins/superb/skills/pipeline-auto/tests/fixtures/master-gate-progress.md`
- Create: `plugins/superb/skills/pipeline-auto/tests/fixtures/master-gate-decisions.md`
- Create: `plugins/superb/skills/pipeline-auto/tests/fixtures/master-gate-findings.md`
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py` (append a `# --- master gate ---` section below P05's code)
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: P02's `parse_tracker`, `locked_tracker_update`, `publish_immutable`, `append_row`, `TrackerValidationError`, `_REVIEW_CLASSES`, and the module-private `_dumps`, `_load_json`, `_digest` that P02/P03 already define. If one of those three is spelled differently in the module, use the existing spelling — **do not add a second JSON writer or a second digest helper.**
- Produces: `PHASE_SET_STAGE`, `MASTER_GATE_ID`, `GateError`, `PhaseSetFrozen`, `ReviewerIndependenceError`, `_stage_row`, `phase_set_frozen`, `assert_phase_set_intact`, `create_phase`, `close_phase_set`

**The structural guarantee this phase owns.** Spec invariant 6: "The phase set is immutable
after stage 06. The run cannot create work for itself. Scope expansion is structurally
impossible, not merely forbidden." Phase creation is a stage-06 transition. Once stage 06
closes, `create_phase` — the only function in the module that appends a `## Phases` row —
refuses, so the controller could not create work for itself even if a later stage convinced
it that it should. Every other rule in this phase, including the completeness freeze, leans
on that. Build it first, and build it as a guard rather than a paragraph.

**Named fault this task catches:** a controller that reaches stage 11, reads a compelling
`MISSING-FROM-SPEC` proposal, and creates a tenth phase to implement it — which is the
single failure mode the whole autonomous design is built to make impossible.

- [ ] **Step 1: Write the four fixtures**

Create `plugins/superb/skills/pipeline-auto/tests/fixtures/stage-06-progress.md` — a valid
tracker with stage 06 **active**, an empty phase set, and nothing downstream:

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
| repo_root | . |
| worker_limit | 6 |
| agent_dispatch_count | 9 |
| spec | docs/superpowers/specs/2026-09-14-pipeline-auto-design.md |
| master_plan | docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md |
| phase_plans | - |
| decisions | decisions.md |
| findings | findings.md |
| completeness_proposals | completeness-proposals.md |
| revision | 6 |
| last_transition | record-spec |

## Stage
| Stage | Stage State | Next Action |
| --- | --- | --- |
| 01 | complete | - |
| 02 | complete | - |
| 03 | complete | - |
| 04 | complete | - |
| 05 | complete | - |
| 06 | active | write-master-plan |
| 07 | pending | - |
| 08 | pending | - |
| 09 | pending | - |
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
| lock-wait | synthesis | 1 | answered | H-001 |

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

Create `plugins/superb/skills/pipeline-auto/tests/fixtures/master-gate-progress.md` — every
phase verified, the `required` phase's gate accepted, stage 11 active, and one provisional task:

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
| repo_root | . |
| worker_limit | 6 |
| agent_dispatch_count | 114 |
| spec | docs/superpowers/specs/2026-09-14-pipeline-auto-design.md |
| master_plan | docs/superpowers/plans/2026-09-14-pipeline-auto-master-plan.md |
| phase_plans | docs/superpowers/plans/pipeline-auto/phase-01-pressure-baselines.md,docs/superpowers/plans/pipeline-auto/phase-02-schema-core.md |
| decisions | decisions.md |
| findings | findings.md |
| completeness_proposals | completeness-proposals.md |
| revision | 41 |
| last_transition | verify-phase-P02 |

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
| 09 | complete | - |
| 10 | complete | - |
| 11 | active | open-master-gate |
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
| lock-wait | synthesis | 1 | answered | H-001 |

## Quorum
| QID | Axis | Phase | State | Owners | Payload Digest | Context Digest | Responses | Depth | Rung | Outcome | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3f2a1b0c9d8e | lock-strategy | P02 | finalized | brain-1,brain-2,brain-3 | a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90 | b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1 | scratch/q1-brain-1.json,scratch/q1-brain-2.json,scratch/q1-brain-3.json | 1 | specified | adopted | Q-3f2a1b0c9d8e |
| 7c6b5a4938d2 | render-order | P02 | finalized | brain-4,brain-5,brain-6 | b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1 | b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1 | scratch/q2-brain-4.json,scratch/q2-brain-5.json,scratch/q2-brain-6.json | 2 | code-evidenced | adopted | Q-7c6b5a4938d2 |

## Escalations
| ID | QID | Blast | State | Batch | Resolution |
| --- | --- | --- | --- | --- | --- |

## Tasks
| ID | Phase | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question | Provisional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01-T01 | P01 | source | [x] | impl-1 | attempt-001 | results/p01-t01-attempt-001.md | red,green | refs/heads/feat/pipeline-auto | 1111111111111111111111111111111111111111 | - | 3333333333333333333333333333333333333333 | scratch/p01-t01-tests.txt | - | no |
| P02-T01 | P02 | source | [x] | impl-2 | attempt-002 | results/p02-t01-attempt-002.md | red,green | refs/heads/feat/pipeline-auto | 2222222222222222222222222222222222222222 | - | 4444444444444444444444444444444444444444 | scratch/p02-t01-tests.txt | - | yes |

## Task Review
| Task | Attempt | Reviewer | State | Spec Verdict | Quality Verdict | Verification | Findings | Adversarial |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01-T01 | attempt-001 | reviewer-1 | accepted | pass | pass | scratch/p01-t01-rerun.txt | none | - |
| P02-T01 | attempt-002 | reviewer-2 | accepted | pass | pass | scratch/p02-t01-rerun.txt | none | large-surface |

## Fix Rounds
| Scope | Round | State | Fixer | Findings | Commits | Verification | Re-review | Remaining |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P02-T01 | 1 | complete | fixer-1 | F-001 | 5555555555555555555555555555555555555555 | scratch/p02-t01-r1-tests.txt | scratch/p02-t01-r1-review.md | none |

## Phases
| ID | State | Verification | Review Class | Class Source | Ratchet | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| P01 | [x] | scratch/p01-verification.txt | final-only | plan | - | - |
| P02 | [x] | scratch/p02-verification.txt | required | ratchet | accumulated-surface@scratch/p02-ratchet.md | gate-p02 |

## Gates
| ID | Type | Phase | State | Base | Head | Assignments | Reports | Verification | Findings |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gate-p02 | phase | P02 | accepted | 3333333333333333333333333333333333333333 | 4444444444444444444444444444444444444444 | spec,quality | scratch/gate-p02-review.md | scratch/gate-p02-tests.txt | findings.md |
| gate-master | master | - | pending | - | - | - | - | - | findings.md |
```

Create `plugins/superb/skills/pipeline-auto/tests/fixtures/master-gate-decisions.md`:

```markdown
<!-- pipeline-auto-decisions/v1 -->

## H-001 — Lock wait bound

- **Question:** How long may a controller wait for the run lock?
- **Axis:** lock-wait
- **Answer:** bounded-30s — Wait at most thirty seconds, then report the failure.
- **Decision action:** none
- **Provenance:** human
- **Depth:** 0
- **Consequences:** signature:acquire_lock=timeout
- **Scope:** P02-T08
- **Status:** Adopted

## Q-3f2a1b0c9d8e — Lock strategy

- **Question:** Which locking primitive backs the run lock?
- **Axis:** lock-strategy
- **Answer:** fcntl — Take an exclusive fcntl.flock on a run-local lock file.
- **Decision action:** quorum.adopt
- **Provenance:** quorum
- **Depth:** 1
- **Grounding rung:** specified
- **Runner-up rung:** convention-cited
- **Consistent with:** H-001
- **Forecloses:** a lock shared across hosts
- **Context digest:** b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1
- **Consequences:** signature:acquire_lock=flock
- **Scope:** P02-T08
- **Status:** Adopted

## Q-7c6b5a4938d2 — Render order

- **Question:** In what order does render_tracker emit the eleven sections?
- **Axis:** render-order
- **Answer:** schema-order — Emit the eleven sections in the order the schema fixes.
- **Decision action:** quorum.adopt
- **Provenance:** quorum
- **Depth:** 2
- **Grounding rung:** code-evidenced
- **Runner-up rung:** engineering-judgement
- **Consistent with:** H-001
- **Forecloses:** an alphabetical renderer
- **Context digest:** b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1
- **Consequences:** signature:render_tracker=schema-order
- **Scope:** P02-T01
- **Status:** Adopted
```

Create `plugins/superb/skills/pipeline-auto/tests/fixtures/master-gate-findings.md`:

```markdown
<!-- pipeline-auto-findings/v1 -->
| ID | Scope | Severity | Status | Disposition | Evidence | Adjudication | Fix Round | Re-review |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F-001 | P02-T01 | Minor | resolved | Fixed | scratch/p02-t01-r1-review.md | - | 1 | scratch/p02-t01-r1-review.md |
```

- [ ] **Step 2: Write the failing tests**

Append to the test file, below the shared helpers:

```python
class PhaseSetImmutability(unittest.TestCase):
    def test_a_phase_is_creatable_while_stage_06_is_active(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack, "stage-06-progress.md")
            pas.create_phase(str(run_dir), phase_id="P01", review_class="required")
            pas.create_phase(str(run_dir), phase_id="P02", review_class="final-only")
            self.assertEqual([row["id"] for row in tracker_of(run_dir)["phases"]],
                             ["P01", "P02"])

    def test_closing_stage_06_seals_the_ids_and_opens_stage_07(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack, "stage-06-progress.md")
            pas.create_phase(str(run_dir), phase_id="P01", review_class="required")
            sealed = pas.close_phase_set(str(run_dir))
            self.assertEqual(sealed["phases"], ["P01"])
            self.assertTrue((run_dir / "phase-set.json").exists())
            tracker = tracker_of(run_dir)
            self.assertTrue(pas.phase_set_frozen(tracker))
            self.assertEqual(pas._stage_row(tracker, "07")["stage_state"], "active")

    def test_creating_a_phase_after_the_close_raises_and_changes_nothing(self):
        # THE SCOPE-EXPANSION SEED. A controller at stage 11 holding a compelling
        # MISSING-FROM-SPEC proposal has exactly one way to act on it: create work.
        # After stage 06 there is no transition that does.
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack, "stage-06-progress.md")
            pas.create_phase(str(run_dir), phase_id="P01", review_class="required")
            pas.close_phase_set(str(run_dir))
            before = (run_dir / "progress.md").read_bytes()
            with self.assertRaises(pas.PhaseSetFrozen):
                pas.create_phase(str(run_dir), phase_id="P02", review_class="required")
            self.assertEqual((run_dir / "progress.md").read_bytes(), before)

    def test_the_master_gate_fixture_is_already_frozen(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            self.assertTrue(pas.phase_set_frozen(tracker_of(run_dir)))

    def test_a_frozen_run_with_no_sealed_file_is_a_stop(self):
        """Stage 06 complete and no phase-set.json means the immutability claim
        has no evidence behind it; a run in that state is not resumable."""
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            with self.assertRaises(pas.PhaseSetFrozen):
                pas.assert_phase_set_intact(str(run_dir))

    def test_a_hand_added_phase_row_fails_the_seal(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            (run_dir / "phase-set.json").write_text(
                json.dumps({"phases": ["P01", "P02"], "digest": "x"}), encoding="utf-8")
            text = (run_dir / "progress.md").read_text(encoding="utf-8").replace(
                "| P02 | [x] | scratch/p02-verification.txt | required | ratchet | "
                "accumulated-surface@scratch/p02-ratchet.md | gate-p02 |\n",
                "| P02 | [x] | scratch/p02-verification.txt | required | ratchet | "
                "accumulated-surface@scratch/p02-ratchet.md | gate-p02 |\n"
                "| P03 | [ ] | - | required | plan | - | - |\n")
            (run_dir / "progress.md").write_text(text, encoding="utf-8")
            with self.assertRaises(pas.PhaseSetFrozen):
                pas.assert_phase_set_intact(str(run_dir))

    def test_a_removed_phase_row_fails_the_seal(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            (run_dir / "phase-set.json").write_text(
                json.dumps({"phases": ["P01", "P02", "P03"], "digest": "x"}),
                encoding="utf-8")
            with self.assertRaises(pas.PhaseSetFrozen):
                pas.assert_phase_set_intact(str(run_dir))

    def test_close_phase_set_is_replay_inert(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack, "stage-06-progress.md")
            pas.create_phase(str(run_dir), phase_id="P01", review_class="required")
            first = pas.close_phase_set(str(run_dir))
            snapshot = (run_dir / "progress.md").read_bytes()
            self.assertEqual(pas.close_phase_set(str(run_dir)), first)
            self.assertEqual((run_dir / "progress.md").read_bytes(), snapshot)

    def test_create_phase_is_idempotent_on_an_existing_id(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack, "stage-06-progress.md")
            pas.create_phase(str(run_dir), phase_id="P01", review_class="required")
            pas.create_phase(str(run_dir), phase_id="P01", review_class="required")
            self.assertEqual(len(tracker_of(run_dir)["phases"]), 1)

    def test_an_empty_phase_set_cannot_be_sealed(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack, "stage-06-progress.md")
            with self.assertRaises(pas.TrackerValidationError):
                pas.close_phase_set(str(run_dir))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k PhaseSet`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'create_phase'`

- [ ] **Step 4: Write the implementation**

Append to `pipeline_auto_state.py`:

```python
# --------------------------------------------------------------------------
# Master gate and completion (P06)
# --------------------------------------------------------------------------
# Spec invariant 6: "The phase set is immutable after stage 06. The run cannot
# create work for itself. Scope expansion is structurally impossible, not merely
# forbidden." Phase creation is a stage-06 transition and `create_phase` is the
# only function in this module that appends a ## Phases row. Once the stage
# closes it refuses, so a controller at stage 11 holding a persuasive
# completeness proposal has no operation available that would act on it. Every
# other rule in this section — the completeness freeze above all — leans on that
# being a guard rather than a paragraph.

PHASE_SET_STAGE = "06"
MASTER_GATE_ID = "gate-master"


class GateError(TrackerError):
    """The master gate cannot proceed from the recorded facts."""


class PhaseSetFrozen(TrackerError):
    """Work creation was attempted after the stage-06 close, or the sealed set moved."""


class ReviewerIndependenceError(GateError):
    """A proposed reviewer has owned work in this run."""


def _stage_row(tracker: dict, stage: str) -> dict:
    for row in tracker["stages"]:
        if row["stage"] == stage:
            return row
    raise TrackerValidationError(f"## Stage is missing stage {stage}")


def phase_set_frozen(tracker: dict) -> bool:
    """True once stage 06 has closed."""
    return _stage_row(tracker, PHASE_SET_STAGE)["stage_state"] == "complete"


def _phase_set_path(run_dir) -> Path:
    return Path(run_dir) / "phase-set.json"


def assert_phase_set_intact(run_dir: str, tracker: dict | None = None) -> list[str]:
    """Re-check the seal on every read that matters, and return the phase ids.

    The seal is checked rather than trusted because `create_phase` is not the
    only way bytes reach `progress.md`: a hand edit, a partially applied
    transition, or a resumed session working from stale memory can all grow or
    shrink the set. The seal turns any of those into a stop.
    """
    directory = Path(run_dir)
    if tracker is None:
        tracker = parse_tracker((directory / "progress.md").read_text(encoding="utf-8"))
    ids = [row["id"] for row in tracker["phases"]]
    path = _phase_set_path(directory)
    if not path.exists():
        if phase_set_frozen(tracker):
            raise PhaseSetFrozen(
                "stage 06 is complete but no sealed phase set was published; the "
                "immutability claim has no evidence behind it and the run is a stop")
        return ids
    sealed = _load_json(path)["phases"]
    if ids != sealed:
        raise PhaseSetFrozen(
            f"the phase set changed after stage 06: sealed {sealed}, tracker {ids}")
    return ids


def create_phase(run_dir: str, *, phase_id: str, review_class: str) -> dict:
    """Append one ## Phases row. The ONLY function that ever does, and it is dead
    the moment stage 06 closes."""
    if review_class not in _REVIEW_CLASSES:
        raise TrackerValidationError("review class is final-only or required")

    def mutate(tracker):
        assert_phase_set_intact(run_dir, tracker)
        stage = _stage_row(tracker, PHASE_SET_STAGE)
        if stage["stage_state"] == "complete":
            raise PhaseSetFrozen(
                f"stage 06 has closed; {phase_id} cannot be created. The run cannot "
                "create work for itself — that is what makes scope expansion "
                "impossible rather than merely forbidden.")
        if stage["stage_state"] != "active":
            raise PhaseSetFrozen(
                "phase creation is a stage-06 transition and stage 06 is not active")
        if any(row["id"] == phase_id for row in tracker["phases"]):
            return tracker
        return append_row(tracker, "phases", {
            "id": phase_id, "state": "[ ]", "verification": "-",
            "review_class": review_class, "class_source": "plan",
            "ratchet": "-", "gate": "-",
        })

    return locked_tracker_update(run_dir, transition_id=f"create-phase-{phase_id}",
                                 mutate=mutate)


def close_phase_set(run_dir: str) -> dict:
    """Stage-06 close. After this returns, `create_phase` can never succeed again."""
    directory = Path(run_dir)

    def mutate(tracker):
        stage = _stage_row(tracker, PHASE_SET_STAGE)
        if stage["stage_state"] != "active":
            raise PhaseSetFrozen("stage 06 is not active; the phase set seals at its close")
        if not tracker["phases"]:
            raise TrackerValidationError(
                "a sealed phase set cannot be empty: there would be no legal way to add one")
        stage["stage_state"] = "complete"
        stage["next_action"] = "-"
        following = _stage_row(tracker, "07")
        following["stage_state"] = "active"
        following["next_action"] = "fan-out-phase-plans"
        return tracker

    tracker = locked_tracker_update(str(directory), transition_id="close-phase-set",
                                    mutate=mutate)
    ids = [row["id"] for row in tracker["phases"]]
    publish_immutable(str(_phase_set_path(directory)),
                      _dumps({"phases": ids, "digest": _digest(",".join(ids))}))
    return {"phases": ids, "frozen": True}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k PhaseSet`
Expected: PASS (10 tests)

- [ ] **Step 6: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): make the phase set immutable after stage 06"
```

---

### Task 2: Reviewer independence over owner history

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `assert_phase_set_intact`, `_stage_row`, `GateError`, `ReviewerIndependenceError`, P02's `parse_tracker`, `locked_tracker_update`, `publish_immutable`, `_csv`, `_dumps`
- Produces: `owner_history(run_dir) -> frozenset[str]`, `_last_verified_head(tracker) -> str`, `open_master_gate(run_dir, *, reviewers) -> dict`

**Named fault this task catches:** independence checked against the owner cells that
happen to be current. A worker released after finishing a task is *exactly* the identity
most likely to be free when reviewers are drawn, and its `Owner` cell is overwritten by
the next attempt — so the check passes and the reviewer reviews their own code with a
clean tracker row as cover. History is reconstructed from the tracker's five owner-bearing
sections **and** from every immutable worker result on disk, which is where a superseded
attempt's owner is the only surviving record.

`base` and `head` are not parameters. The base is the immutable tracker `base_commit`; the
head is derived from the last integrated source task. A caller who can choose the reviewed
edge can choose a diff that flatters the run, which is the cheapest way to pass a gate.

- [ ] **Step 1: Write the failing tests**

```python
class MasterReviewerIndependence(unittest.TestCase):
    def test_owner_history_includes_a_released_superseded_owner(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            write_result(run_dir, "p02-t01-attempt-001.md", "impl-7")
            history = pas.owner_history(str(run_dir))
            self.assertIn("impl-7", history)                       # only on disk
            self.assertNotIn("impl-7", {row["owner"] for row in tracker_of(run_dir)["tasks"]})
            self.assertEqual(history & {"-", "reconciled"}, frozenset())

    def test_owner_history_covers_tasks_reviews_fixers_readers_and_brains(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            history = pas.owner_history(str(run_dir))
            for owner in ("impl-1", "impl-2", "reviewer-1", "reviewer-2",
                          "fixer-1", "intent-reader-1", "brain-1", "brain-6"):
                self.assertIn(owner, history)

    def test_a_released_worker_cannot_be_drawn_as_a_master_reviewer(self):
        # THE INDEPENDENCE SEED. impl-7 finished attempt-001 and was released;
        # the tracker's owner cell now reads impl-2. Checking "current owners"
        # would clear impl-7 to review the code impl-7 wrote.
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            write_result(run_dir, "p02-t01-attempt-001.md", "impl-7")
            with self.assertRaises(pas.ReviewerIndependenceError) as caught:
                opened_gate(run_dir, a="impl-7")
            self.assertIn("impl-7", str(caught.exception))
            self.assertFalse((run_dir / "gate-master").exists())

    def test_a_brain_a_fixer_and_a_task_reviewer_are_all_ineligible(self):
        for owner in ("brain-3", "fixer-1", "reviewer-2"):
            with self.subTest(owner=owner), contextlib.ExitStack() as stack:
                _root, run_dir = new_run(stack)
                with self.assertRaises(pas.ReviewerIndependenceError):
                    opened_gate(run_dir, b=owner)

    def test_the_two_reviewers_must_differ(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            with self.assertRaises(pas.ReviewerIndependenceError):
                opened_gate(run_dir, a="reviewer-x", b="reviewer-x")

    def test_exactly_two_roles_a_and_b(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            for reviewers in ({"A": "r1"}, {"A": "r1", "B": "r2", "C": "r3"}):
                with self.assertRaises(pas.GateError):
                    pas.open_master_gate(str(run_dir), reviewers=reviewers)

    def test_the_edge_is_derived_and_cannot_be_supplied(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            with self.assertRaises(TypeError):
                pas.open_master_gate(str(run_dir),
                                     reviewers={"A": "reviewer-a", "B": "reviewer-b"},
                                     head="0" * 40)

    def test_opening_seals_the_assignments_and_the_derived_edge(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            sealed = opened_gate(run_dir)
            self.assertEqual(sealed["base"], BASE)
            self.assertEqual(sealed["head"], HEAD)
            self.assertEqual(sealed["assignments"]["master-A"]["reviewer"], "reviewer-a")
            self.assertEqual(sealed["assignments"]["master-B"]["role"], "B")
            gate = next(row for row in tracker_of(run_dir)["gates"]
                        if row["id"] == pas.MASTER_GATE_ID)
            self.assertEqual(gate["state"], "in_progress")
            self.assertEqual(gate["assignments"], "master-A,master-B")

    def test_a_held_integration_is_not_a_reviewable_head(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            text = (run_dir / "progress.md").read_text(encoding="utf-8").replace(
                "| 4444444444444444444444444444444444444444 | scratch/p02-t01-tests.txt |",
                "| held | scratch/p02-t01-tests.txt |")
            (run_dir / "progress.md").write_text(text, encoding="utf-8")
            with self.assertRaises(pas.GateError):
                opened_gate(run_dir)

    def test_an_unverified_phase_blocks_the_gate(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            text = (run_dir / "progress.md").read_text(encoding="utf-8").replace(
                "| P01 | [x] | scratch/p01-verification.txt |",
                "| P01 | [~] | - |")
            (run_dir / "progress.md").write_text(text, encoding="utf-8")
            with self.assertRaises(pas.GateError):
                opened_gate(run_dir)

    def test_a_required_phase_without_an_accepted_gate_blocks(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            text = (run_dir / "progress.md").read_text(encoding="utf-8").replace(
                "| gate-p02 | phase | P02 | accepted |", "| gate-p02 | phase | P02 | blocked |")
            (run_dir / "progress.md").write_text(text, encoding="utf-8")
            with self.assertRaises(pas.GateError):
                opened_gate(run_dir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k MasterReviewerIndependence`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'owner_history'`

- [ ] **Step 3: Write the implementation**

```python
_OWNER_LINE = re.compile(r"^-\s+\*\*Owner:\*\*\s*(\S+)\s*$", re.MULTILINE)
_NON_OWNERS = frozenset({"-", "reconciled"})


def owner_history(run_dir: str) -> frozenset[str]:
    """Every identifier that has EVER owned work in this run.

    Current owner cells are the wrong set and look like the right one. A worker
    released after finishing attempt-001 vanishes from `## Tasks` the moment
    attempt-002 is reserved, and it is precisely that released worker who is
    free when master reviewers are drawn. The surviving record of a superseded
    attempt is its immutable result file, so the result tree is scanned too.
    """
    directory = Path(run_dir)
    tracker = parse_tracker((directory / "progress.md").read_text(encoding="utf-8"))
    owners: set[str] = set()
    for row in tracker["tasks"]:
        owners.add(row["owner"])
    for row in tracker["intent"]:
        owners.add(row["owner"])
    for row in tracker["task_review"]:
        owners.add(row["reviewer"])
    for row in tracker["fix_rounds"]:
        owners.update(_csv(row["fixer"]))
    for row in tracker["quorum"]:
        owners.update(_csv(row["owners"]))
    results = directory / "results"
    if results.is_dir():
        for path in sorted(results.rglob("*.md")):
            owners.update(_OWNER_LINE.findall(path.read_text(encoding="utf-8")))
    return frozenset(owners - _NON_OWNERS)


def _last_verified_head(tracker: dict) -> str:
    """The head the master gate reviews, derived from integrated source work."""
    integrated = [row for row in tracker["tasks"]
                  if row["state"] == "[x]" and row["kind"] == "source"]
    if not integrated:
        raise GateError("no completed source task: there is no reviewed edge")
    last = integrated[-1]
    if last["integration"] == "held":
        raise GateError(
            f"{last['id']} is complete but its integration is held; the edge is not final")
    return last["integration"]


def open_master_gate(run_dir: str, *, reviewers: dict) -> dict:
    """Open stage 11 with two sealed, independent reviewer assignments.

    Neither `base` nor `head` is a parameter. The base is the immutable tracker
    `base_commit` and the head is derived from the last integrated source task:
    a caller able to choose the reviewed edge can choose a diff that flatters
    the run, which is the cheapest way there is to pass a gate.
    """
    directory = Path(run_dir)
    if set(reviewers) != {"A", "B"}:
        raise GateError("the master gate takes exactly two reviewers, roles A and B")
    if reviewers["A"] == reviewers["B"]:
        raise ReviewerIndependenceError("the two master reviewers must be different agents")
    history = owner_history(str(directory))
    conflicted = sorted(ident for ident in reviewers.values() if ident in history)
    if conflicted:
        raise ReviewerIndependenceError(
            f"{conflicted[0]} appears in this run's owner history. Independence is "
            "checked against every identifier that has ever owned a task, review, fix "
            "round, intent read or brain slot — not against the owner cells that "
            "happen to be current, because a worker released after finishing a task "
            "is exactly the reviewer who would be reviewing their own code.")

    def mutate(tracker):
        assert_phase_set_intact(str(directory), tracker)
        unfinished = [row["id"] for row in tracker["phases"] if row["state"] != "[x]"]
        if unfinished:
            raise GateError(f"phase {unfinished[0]} is not verified")
        for phase in tracker["phases"]:
            if phase["review_class"] != "required":
                continue
            gate = next((row for row in tracker["gates"] if row["id"] == phase["gate"]), None)
            if gate is None or gate["state"] != "accepted":
                raise GateError(
                    f"required phase {phase['id']} has no accepted phase gate")
        master = next((row for row in tracker["gates"] if row["id"] == MASTER_GATE_ID), None)
        if master is None:
            raise GateError("the tracker has no master gate row")
        if master["state"] != "pending":
            return tracker
        master["state"] = "in_progress"
        master["base"] = tracker["run"]["base_commit"]
        master["head"] = _last_verified_head(tracker)
        master["assignments"] = "master-A,master-B"
        stage = _stage_row(tracker, "11")
        stage["stage_state"] = "active"
        stage["next_action"] = "await-master-reports"
        return tracker

    tracker = locked_tracker_update(str(directory), transition_id="open-master-gate",
                                    mutate=mutate)
    master = next(row for row in tracker["gates"] if row["id"] == MASTER_GATE_ID)
    sealed = {
        "gate": MASTER_GATE_ID,
        "base": master["base"],
        "head": master["head"],
        "assignments": {
            "master-A": {"role": "A", "reviewer": reviewers["A"]},
            "master-B": {"role": "B", "reviewer": reviewers["B"]},
        },
        "owner_history": sorted(history),
    }
    gate_dir = directory / "gate-master"
    (gate_dir / "reports").mkdir(parents=True, exist_ok=True)
    publish_immutable(str(gate_dir / "assignments.json"), _dumps(sealed))
    return sealed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k MasterReviewerIndependence`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): check master reviewer independence against owner history"
```

---

### Task 3: The reviewer packet, unfiltered by provenance

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `open_master_gate`'s sealed `assignments.json`, P03's `parse_decisions` and `RUNG_ORDER`, P02's `parse_tracker`, `_csv`, `_load_json`
- Produces: `_PACKET_HEADINGS`, `tainting_decisions(run_dir) -> dict`, `build_reviewer_packet(run_dir, *, role) -> str`

**Named fault this task catches:** the packet filtered to `Provenance: human` on the
reasonable-sounding grounds that human answers are the requirements and quorum answers are
implementation detail. That inverts the gate. The quorum answers are the ones nobody
checked, challenging them is the reviewer's entire job at stage 11, and a reviewer who
cannot see which answers the machine gave itself cannot tell a requirement from an
invention. The rungs travel with them: rungs must never reach a brain (a brain that knows
the bar clears the bar) and must always reach a reviewer (a reviewer who cannot see the bar
cannot tell whether it was cleared).

The spec's provisionality rule is explicit that a label is not enough — the tainting
decision's ID **and adopted answer** are copied verbatim into the reviewer's
global-constraints block, and "that second half is what makes it more than a label".

- [ ] **Step 1: Write the failing tests**

```python
class ReviewerPacket(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = new_run(self.stack)
        opened_gate(self.run_dir)

    def packet(self, role="A") -> str:
        return Path(pas.build_reviewer_packet(str(self.run_dir), role=role)).read_text(
            encoding="utf-8")

    def test_the_packet_is_not_filtered_to_human_provenance(self):
        # THE FILTERED-PACKET SEED. Both quorum answers must be visible, with the
        # rung each was adopted on, because challenging them is the job.
        text = self.packet()
        self.assertIn("Q-3f2a1b0c9d8e", text)
        self.assertIn("Q-7c6b5a4938d2", text)
        self.assertIn("H-001", text)
        self.assertIn("specified", text)
        self.assertIn("code-evidenced", text)

    def test_the_weakest_quorum_decision_is_listed_first(self):
        text = self.packet()
        self.assertLess(text.index("Q-7c6b5a4938d2"), text.index("Q-3f2a1b0c9d8e"))

    def test_the_packet_carries_rung_names_and_never_rung_values(self):
        text = self.packet()
        for value in ("0.95", "0.85", "0.70", "0.55", "0.30"):
            self.assertNotIn(value, text)

    def test_reviewer_a_is_pointed_at_the_decision_record(self):
        self.assertIn("decisions.md", self.packet("A"))
        self.assertIn("requirements", self.packet("A"))
        self.assertIn("integration", self.packet("B"))

    def test_the_tainting_decision_answer_is_copied_verbatim(self):
        taints = pas.tainting_decisions(str(self.run_dir))
        self.assertEqual(sorted(taints), ["P02-T01"])
        self.assertEqual([record["id"] for record in taints["P02-T01"]],
                         ["Q-7c6b5a4938d2"])
        answer = taints["P02-T01"][0]["answer"]
        self.assertIn(answer, self.packet())

    def test_a_specified_decision_never_taints(self):
        """Provisionality is about a decision adopted at code-evidenced rather
        than specified. Q-3f2a1b0c9d8e is specified and taints nothing."""
        taints = pas.tainting_decisions(str(self.run_dir))
        self.assertNotIn("Q-3f2a1b0c9d8e",
                         [record["id"] for records in taints.values() for record in records])

    def test_the_packet_states_the_human_challenge_rule(self):
        text = self.packet()
        self.assertIn("DECISION-CHALLENGE", text)
        self.assertIn("never a request to overrule", text)

    def test_an_unknown_role_is_refused(self):
        with self.assertRaises(pas.GateError):
            pas.build_reviewer_packet(str(self.run_dir), role="C")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k ReviewerPacket`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'build_reviewer_packet'`

- [ ] **Step 3: Write the implementation**

```python
_PACKET_HEADINGS = {
    "A": ("Reviewer A — requirements, behaviour, error paths, assumptions, "
          "and the decision record"),
    "B": ("Reviewer B — integration, architecture, persistence, recovery, "
          "concurrency, security, regressions, and test quality"),
}


def tainting_decisions(run_dir: str) -> dict:
    """{task_id: [decision, ...]} for every provisional task.

    A quorum decision adopted at `code-evidenced` rather than `specified` taints
    every task in its scope. The spec is explicit that the label alone is not
    the mitigation: the tainting decision's ID and adopted answer are copied
    verbatim into the reviewer's global-constraints block, and that second half
    is what makes it more than a label.
    """
    directory = Path(run_dir)
    tracker = parse_tracker((directory / "progress.md").read_text(encoding="utf-8"))
    parsed = parse_decisions((directory / "decisions.md").read_text(encoding="utf-8"))
    weak = [record for record in parsed["decisions"].values()
            if record["provenance"] == "quorum"
            and record["status"] == "Adopted"
            and record.get("grounding_rung") != "specified"]
    taints = {}
    for task in tracker["tasks"]:
        if task["provisional"] != "yes":
            continue
        taints[task["id"]] = [record for record in weak
                              if task["id"] in _csv(record.get("scope", "-"))]
    return taints


def _weakest_first(records: list) -> list:
    """Sort by grounding rung ascending: least-grounded answer first."""
    return sorted(records,
                  key=lambda record: (-RUNG_ORDER.index(record.get("grounding_rung",
                                                                   RUNG_ORDER[-1])),
                                      record["id"]))


def build_reviewer_packet(run_dir: str, *, role: str) -> str:
    """Write gate-master/packet-<role>.md and return its path."""
    if role not in _PACKET_HEADINGS:
        raise GateError("the master gate has exactly two roles, A and B")
    directory = Path(run_dir)
    sealed = _load_json(directory / "gate-master" / "assignments.json")
    parsed = parse_decisions((directory / "decisions.md").read_text(encoding="utf-8"))
    adopted = [record for record in parsed["decisions"].values()
               if record["status"] == "Adopted"]
    quorum = _weakest_first([r for r in adopted if r["provenance"] == "quorum"])
    human = sorted((r for r in adopted if r["provenance"] == "human"),
                   key=lambda record: record["id"])

    lines = [
        f"# {_PACKET_HEADINGS[role]}", "",
        f"- **Gate:** {sealed['gate']}",
        f"- **Assignment:** master-{role}",
        f"- **Edge:** `{sealed['base']}..{sealed['head']}`", "",
        "## Global constraints", "",
        "Score against the decision record below. Reviewer A's primary authority is",
        "`decisions.md`: a change that is good code and contradicts a recorded",
        "decision is a finding, not a preference.", "",
    ]
    taints = tainting_decisions(str(directory))
    if any(taints.values()):
        lines += ["### Provisional work in this branch", "",
                  "Each task below rests on an answer the run gave itself at less than",
                  "`specified` grounding. Name the decision in any finding you raise",
                  "against that task.", ""]
        for task_id in sorted(taints):
            for record in taints[task_id]:
                lines += [
                    f"- **{task_id}** rests on **{record['id']}** "
                    f"(grounding rung `{record.get('grounding_rung', '-')}`).",
                    f"  - Adopted answer, verbatim: {record['answer']}",
                ]
        lines.append("")
    lines += [
        "## Decisions in force", "",
        "This table is **not** filtered to `Provenance: human`. Every answer the run",
        "gave itself is listed with the grounding rung it was adopted on, weakest",
        "first, because challenging those answers is your job. Raise a",
        "`DECISION-CHALLENGE` against any of them. Against a `Provenance: human`",
        "decision a challenge is a report of consequence and never a request to",
        "overrule: say what defect the decision causes, and stop there.", "",
        "| D-ID | Provenance | Grounding rung | Axis | Question | Adopted answer |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for record in quorum + human:
        lines.append(
            f"| {record['id']} | {record['provenance']} | "
            f"{record.get('grounding_rung', '-')} | {record['axis']} | "
            f"{record['question']} | {record['answer']} |")
    lines += [
        "", "## Findings contract", "",
        "Every finding carries a severity (`Critical`, `Important`, `Minor`), a verdict",
        "part (`spec-compliance`, `quality`, `verification-evidence`), and `traces_to`:",
        "a `<spec-path>.md:<line>` that resolves, or the literal `none`. A finding that",
        "would require reversing a recorded decision names it in `Requires Reversal Of`.",
        "The bar is zero open findings at every severity.", "",
    ]
    path = directory / "gate-master" / f"packet-{role}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -t . -v -k ReviewerPacket`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): show reviewers every quorum decision with its rung"
```

---
