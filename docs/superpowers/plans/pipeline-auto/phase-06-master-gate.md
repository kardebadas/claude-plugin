# P06 — Master Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build stages 11 and 12 of `pipeline_auto_state.py` — the phase-set freeze that makes scope expansion structurally impossible, the two-reviewer master gate with independence checked against owner *history*, `DECISION-CHALLENGE` routing that never lets a reviewer overrule the one human gate, the completeness freeze, evidence-derived acceptance, final verification, and a terminal report that opens with every decision the run made without the user.

**Architecture:** The phase set is sealed by a stage-06 transition that publishes an immutable `phase-set.json`; every P06 entry point re-checks the seal, and `create_phase` — the only writer of a `## Phases` row — refuses after the seal exists. That single guard is what turns "never invent scope" from a rule into an unavailable operation, and it is why the completeness critic's `MISSING-FROM-SPEC` class can be frozen to a file rather than policed. Above it sit three pure routers (`route_contradiction`, `classify_completeness_item`, `raised_floor`) and four durable transitions (`open_master_gate`, `record_master_report`, `evaluate_master_gate`, `record_final_verification`), all of which derive their conclusions from files and none of which accept a caller's verdict as input.

**Tech Stack:** Python 3 standard library only (`hashlib`, `json`, `pathlib`, `re`). `unittest` for tests (`pytest` collects the same classes). Markdown for `findings.md`, `completeness-proposals.md`, reviewer packets, reports and the terminal report; JSON for the sealed gate records.

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
- `publish_immutable(path, content)` writes once; a byte-identical second call is a
  no-op returning the same path; a differing second call raises. That is what makes
  `assignments.json`, each report, and `final-verification.json` single-assignment cells.

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
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
python3 -c "import ast; ast.parse(open('plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py').read())"
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The third command must print **nothing**. Any output means `skills/pipeline/` was modified
and the phase fails. `python3 -m pytest plugins/superb/skills/pipeline-auto/tests/ -v` is
the master plan's form and collects the same `unittest.TestCase` classes; `unittest discover`
is the form that runs with the standard library alone, which this repository requires.

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
