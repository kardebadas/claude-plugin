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

## Carried forward from P02 Task 7 (commit `b7cfc97`)

**`Open` is not cross-checked against `## Fix Rounds` findings.** P02 owns shape:
it enforces `Open == Critical + Important + Minor` and pins `accepted` to
`Open 0` in both directions. Whether a finding id cited in a fix round actually
exists is `findings.md`'s business, and this module never opens that file. If
your gate depends on a cited finding being real, check it yourself.

**The per-round `Intensity` is deliberately not cross-checked against
`## Phases`.** Doing so would mean reading the dial, and no validator may branch
on `Review Class` — the dial decides whether a reviewer runs, never what bar it
applies. A round recorded at an intensity its phase never had is therefore
expressible; if that matters at the gate, catch it there.

## Carried forward from P02 Task 6's review (commit `0ecfa77`)

**`tainting_decisions` must check existence, not just citation.** It matches
`record["id"] in cited`, so a well-formed but non-existent `Q-<12 hex>` in a
task's `Decisions` cell silently produces **no taint** — the task looks clean
because the decision it rests on cannot be found, which is the opposite of what
should happen.

P02 deliberately validates the `Decisions` column by grammar only. Resolution is
against `decisions.md`, which the state module never opens, so P02's grammar
check is what stops garbage reaching you — but existence is yours. A cited id
that resolves to nothing is a tracker that disagrees with its own decision
record, and it should raise rather than quietly mark a tainted task clean.

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
classes and the proposals file; evidence-derived master acceptance; the **master-gate fix
loop** with its three-round bound, no-progress halt and oscillation halt; the stage-12
run-wide suite contract; the terminal report.

Not owned: per-task review rows and the **task-scope** fix loop (P05 — P06 reads those rows
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

**Two sections P05 reshapes, which this phase's fixtures and code follow.**
`## Task Review` is **fourteen** columns — `Task`, `Round`, `Intensity`, `State`,
`Reviewer`, `Package`, `Report`, `Critical`, `Important`, `Minor`, `Adversarial`,
`Adversarial Verdict`, `Open`, `Evidence` — not P02's nine-column placeholder, which could
express neither N rounds per task nor a live `Open` count and so could carry none of the
never-off rules. `## Tasks` carries a `Decisions` column listing the decision ids that
task's plan cites, **and that column is what lets taint cross a phase boundary**: without
it the provisional closure stops at the phase that raised the decision, so a decision
adopted during P01 that governs a P02 task goes silently unmarked — exactly the cascade the
taint rule exists to catch. `owner_history` reads `## Task Review`'s `Reviewer` and
`tainting_decisions` reads `## Tasks`' `Decisions`; every other cell is read by name, so
column *order* is P05's to fix.

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

P06 calls none of these inside a transition. They are named because the controller prose in
P07 sequences them around this phase's functions, and because Task 7's test asserts that a
reconciliation leaves P05's fix-round rows untouched. In particular, **P06 does not call
`open_fix_round`**: Task 10 owns the gate-scope loop end-to-end, because P05's function is
shaped for a task scope and a per-task review row. The `## Fix Rounds` grammar is shared and
P02 validates it for both scopes.

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

def _gate_row(tracker: dict) -> dict: ...
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

MAX_GATE_FIX_ROUNDS = 3
GATE_HALTS = ("round-cap", "no-progress", "oscillation")

def gate_fix_rounds(run_dir: str) -> list[dict]: ...
def open_gate_fix_round(run_dir: str, *, fixer: str, findings: list) -> dict: ...
def record_gate_fix_round(run_dir: str, *, round_number: int, fixer: str, commits: str,
                          verification: str, re_review: str, remaining: list) -> dict: ...

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
verdict. `open_gate_fix_round` and `record_gate_fix_round` both return
`{"round", "halted", "reason", "dispatch", ...}`; `halted` is a bool and `reason` is a
`GATE_HALTS` member or `-`, never `None`, so a caller cannot mistake a halt for a quiet
success. `raised_floor` returns a rung **name**. `owner_history` returns a `frozenset`, so
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
and the phase fails.

`-t` is deliberately absent: `pipeline-auto` is hyphenated, so `-t .` makes discovery
try to import `plugins.superb.skills.pipeline-auto.tests`, which is not a legal Python
package name, and it dies with `ImportError: Start directory is not importable`. For a
sub-suite, `unittest` takes **repeated** `-k` flags and ORs them
(`-k FindingsLedger -k MasterReportBlock`); it does not accept pytest's `-k "A or B"`.

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
    decisions ledger, findings ledger and an empty results directory.

    A tracker whose stage 06 has closed also gets its sealed `phase-set.json`,
    because a frozen run without one is a stop by design and every gate function
    re-checks the seal.
    """
    root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
    run_dir = root / "run"
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "scratch").mkdir()
    (run_dir / "progress.md").write_text(fixture(tracker_fixture), encoding="utf-8")
    (run_dir / "decisions.md").write_text(fixture("master-gate-decisions.md"), encoding="utf-8")
    (run_dir / "findings.md").write_text(fixture("master-gate-findings.md"), encoding="utf-8")
    tracker = pas.parse_tracker((run_dir / "progress.md").read_text(encoding="utf-8"))
    if pas.phase_set_frozen(tracker):
        seal_phase_set(run_dir, [row["id"] for row in tracker["phases"]])
    return root, run_dir


def seal_phase_set(run_dir, phases) -> None:
    (Path(run_dir) / "phase-set.json").write_text(
        json.dumps({"phases": list(phases), "digest": "-"}), encoding="utf-8")


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
> **From the P03 Task 3 review.** `effective_rung` validates the recorded
> `repo_root` **before** it reads any evidence, so on a checkout that has moved
> it raises `QuorumError` for *every* response — including a `speculation` with
> no evidence at all. That is deliberate (a wrong root demotes everything
> silently, which is worse), but it means a run whose root has moved can price
> nothing: the gate sees a stop, not a low rung. Do not treat that exception as
> a quorum outcome.
>
> Related, and binding: `effective_rung`'s signature stays at **two** arguments.
> The test pinning "the root is recorded, never derived" distinguishes a
> `__file__`-derived root but could NOT distinguish a `run_dir`-derived one,
> because `run_dir.parents[3] == repo_root` in the production layout. Passing
> `run_dir` in would make that derivation constructible and silently blunt the
> only guard against this phase's invisible failure.

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
| ID | Phase | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question | Provisional | Decisions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Task Review
| Task | Round | Intensity | State | Reviewer | Package | Report | Critical | Important | Minor | Adversarial | Adversarial Verdict | Open | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

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
| 7c6b5a4938d2 | render-order | P01 | finalized | brain-4,brain-5,brain-6 | b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1 | b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1 | scratch/q2-brain-4.json,scratch/q2-brain-5.json,scratch/q2-brain-6.json | 2 | code-evidenced | adopted | Q-7c6b5a4938d2 |

## Escalations
| ID | QID | Blast | State | Batch | Resolution |
| --- | --- | --- | --- | --- | --- |

## Tasks
| ID | Phase | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question | Provisional | Decisions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01-T01 | P01 | source | [x] | impl-1 | attempt-001 | results/p01-t01-attempt-001.md | red,green | refs/heads/feat/pipeline-auto | 1111111111111111111111111111111111111111 | - | 3333333333333333333333333333333333333333 | scratch/p01-t01-tests.txt | - | no | Q-3f2a1b0c9d8e |
| P02-T01 | P02 | source | [x] | impl-2 | attempt-002 | results/p02-t01-attempt-002.md | red,green | refs/heads/feat/pipeline-auto | 2222222222222222222222222222222222222222 | - | 4444444444444444444444444444444444444444 | scratch/p02-t01-tests.txt | - | yes | Q-7c6b5a4938d2 |

## Task Review
| Task | Round | Intensity | State | Reviewer | Package | Report | Critical | Important | Minor | Adversarial | Adversarial Verdict | Open | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P01-T01 | 1 | final-only | accepted | reviewer-1 | scratch/p01-t01-package.md | scratch/p01-t01-review.md | 0 | 0 | 0 | - | - | 0 | scratch/p01-t01-rerun.txt |
| P02-T01 | 1 | required | accepted | reviewer-2 | scratch/p02-t01-package.md | scratch/p02-t01-review.md | 0 | 0 | 1 | large-surface | REFUTED | 0 | scratch/p02-t01-rerun.txt |

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
            (run_dir / "phase-set.json").unlink()
            with self.assertRaises(pas.PhaseSetFrozen):
                pas.assert_phase_set_intact(str(run_dir))

    def test_a_hand_added_phase_row_fails_the_seal(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
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
            seal_phase_set(run_dir, ["P01", "P02", "P03"])
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k PhaseSet`
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k PhaseSet`
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k MasterReviewerIndependence`
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
        ten = _stage_row(tracker, "10")
        if ten["stage_state"] != "active":
            raise GateError("stage 10 is not active; the master gate opens at its close")
        ten["stage_state"] = "complete"
        ten["next_action"] = "-"
        eleven = _stage_row(tracker, "11")
        eleven["stage_state"] = "active"
        eleven["next_action"] = "await-master-reports"
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

**Why stage 10 closes in this same mutate.** Opening stage 11 without closing stage 10
would leave a window in which no stage is active and stages 11-12 are still pending — a
tracker P02's `derive_next_action` cannot act on, because there is no active row to read a
next action from and the run is plainly not complete. P06 already found this exact fault in
the gate fix loop and wrote the rule out: *a transition is the unit at which state is legal,
so any change needing two writes to stay legal is one write.* Closing 10 and opening 11 are
two halves of one legal state change, so they are one `locked_tracker_update`, and an
interruption lands either before or after it rather than inside it.

**The same holds for stages 08, 09 and 10.** Each of them closes as the next one opens, in a
single `mutate`: the writer that finishes a stage sets that row to `complete` with
`next_action` `-` and sets its successor to `active` with the successor's first action, in
one locked transition. No specified writer ever leaves the stage table with nothing active
while work remains — stage 12's close is the sole exception, and it is the terminal state in
which all twelve rows read `complete`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k MasterReviewerIndependence`
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

    def test_taint_crosses_a_phase_boundary_through_the_decisions_column(self):
        # THE CASCADE SEED. Q-7c6b5a4938d2 was raised during P01 and governs the
        # P02 task that cites it. A closure keyed on the raising phase would stop
        # at P01 and leave P02-T01 silently unmarked.
        tracker = tracker_of(self.run_dir)
        raised_in = next(row["phase"] for row in tracker["quorum"]
                         if row["decision"] == "Q-7c6b5a4938d2")
        task = next(row for row in tracker["tasks"] if row["id"] == "P02-T01")
        self.assertEqual(raised_in, "P01")
        self.assertNotEqual(task["phase"], raised_in)
        self.assertIn("Q-7c6b5a4938d2", task["decisions"])
        self.assertEqual(
            [record["id"] for record in pas.tainting_decisions(str(self.run_dir))["P02-T01"]],
            ["Q-7c6b5a4938d2"])

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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ReviewerPacket`
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
    every task that cites it. The task's `Decisions` cell is the primary source
    rather than the decision's own `Scope`, because that is the edge that
    crosses a phase boundary: a decision adopted during P01 can govern a P02
    task, and a scope-only closure would stop at P01 and leave the P02 task
    unmarked. The spec is also explicit that the label alone is not the
    mitigation: the tainting decision's ID and adopted answer are copied
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
        cited = set(_csv(task.get("decisions", "-")))
        taints[task["id"]] = [
            record for record in weak
            if record["id"] in cited or task["id"] in _csv(record.get("scope", "-"))]
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

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ReviewerPacket`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): show reviewers every quorum decision with its rung"
```

---
### Task 4: The findings ledger and the master report block

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `GateError`, `MASTER_GATE_ID`, the sealed `assignments.json`, P02's `publish_immutable`, `TrackerValidationError`, `_csv`, `_load_json`
- Produces: `SEVERITIES`, `VERDICT_PARTS`, `MASTER_REPORT_MARKER`, `_SPEC_TRACE`, `_pipe_cells`, `_gate_row`, `parse_findings`, `render_findings`, `upsert_finding`, `open_findings`, `parse_master_report`, `record_master_report`

**Named fault this task catches:** a report whose `head` is not the gate's head. Two
reviewers over "the same complete edge" is the whole basis of the two-reviewer gate, and a
reviewer who re-derived the edge themselves — from `HEAD~1`, from a worktree tip, from the
branch as it stood when they started — produces a report that looks identical and covers
different code.

**Two heads are in play, and keeping them apart is the point.** The gate's head advances
through fix rounds (Task 10); a sealed report does not. A report is written against the
gate's **current** edge, published under a head-qualified path, and recorded in
`report-bindings.json` with the exact edge it was written against. The digest binding is
what makes it evidence, so rebinding a sealed report to a later head would silently claim a
reviewer saw code they never read. The second named fault is severity and verdict part being free text: every
later routing decision in this phase reads those two fields, so an unconstrained value
silently picks a route.

`upsert_finding` exists so a rediscovered issue keeps its ID. Two reviewers reporting the
same defect must produce one row, or zero-open-findings counts the same fix twice.

- [ ] **Step 1: Write the failing tests**

```python
class FindingsLedger(unittest.TestCase):
    def test_the_fixture_ledger_round_trips(self):
        rows = pas.parse_findings(fixture("master-gate-findings.md"))
        self.assertEqual([row["id"] for row in rows], ["F-001"])
        self.assertEqual(rows[0]["status"], "resolved")
        self.assertEqual(pas.parse_findings(pas.render_findings(rows)), rows)

    def test_an_unknown_severity_is_refused(self):
        text = fixture("master-gate-findings.md").replace("| Minor |", "| Nitpick |")
        with self.assertRaises(pas.TrackerValidationError):
            pas.parse_findings(text)

    def test_a_rediscovered_finding_keeps_its_id_and_its_row(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            pas.upsert_finding(str(run_dir), {"id": "F-010", "scope": "gate-master",
                                              "severity": "Important", "status": "open"})
            pas.upsert_finding(str(run_dir), {"id": "F-010", "scope": "gate-master",
                                              "severity": "Important", "status": "open",
                                              "evidence": "reports/master-B.md"})
            rows = pas.parse_findings((run_dir / "findings.md").read_text(encoding="utf-8"))
            self.assertEqual([row["id"] for row in rows], ["F-001", "F-010"])
            self.assertEqual(rows[1]["evidence"], "reports/master-B.md")

    def test_open_findings_excludes_resolved_rows(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            self.assertEqual(pas.open_findings(str(run_dir)), [])
            pas.upsert_finding(str(run_dir), {"id": "F-010", "scope": "gate-master",
                                              "severity": "Minor", "status": "open"})
            self.assertEqual([row["id"] for row in pas.open_findings(str(run_dir))], ["F-010"])


class MasterReportBlock(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = new_run(self.stack)
        opened_gate(self.run_dir)

    def test_a_clean_report_records(self):
        recorded = publish_report(self.run_dir)
        self.assertEqual(recorded["findings"], [])
        self.assertEqual(recorded["head"], HEAD)
        self.assertTrue(
            (self.run_dir / "gate-master" / "reports" / f"master-A@{HEAD[:12]}.md").exists())
        self.assertEqual(len(recorded["digest"]), 64)
        binding = json.loads((self.run_dir / "gate-master" / "report-bindings.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(binding["master-A"]["head"], HEAD)

    def test_a_report_with_findings_lands_them_in_the_ledger(self):
        publish_report(self.run_dir, findings=[
            ("F-101", "Minor", "quality", "none", "Q-7c6b5a4938d2",
             "`render_tracker` should be called `emit_tracker`.")])
        rows = pas.parse_findings((self.run_dir / "findings.md").read_text(encoding="utf-8"))
        self.assertIn("F-101", [row["id"] for row in rows])
        self.assertEqual([row["status"] for row in rows if row["id"] == "F-101"], ["open"])

    def test_a_report_reviewing_a_different_head_is_refused(self):
        # THE DRIFTED-EDGE SEED. Two reviewers over the SAME complete edge is the
        # basis of the gate; a re-derived head produces an identical-looking
        # report over different code.
        with self.assertRaises(pas.GateError) as caught:
            publish_report(self.run_dir, head="9" * 40)
        self.assertIn("identical gate edge", str(caught.exception))

    def test_a_report_from_an_unsealed_reviewer_is_refused(self):
        with self.assertRaises(pas.GateError):
            publish_report(self.run_dir, reviewer="reviewer-z")

    def test_a_report_for_an_unknown_assignment_is_refused(self):
        with self.assertRaises(pas.GateError):
            publish_report(self.run_dir, assignment="master-C")

    def test_a_nonterminal_block_is_refused(self):
        with self.assertRaises(pas.GateError):
            publish_report(self.run_dir, trailer="One more thought.")

    def test_a_duplicated_outcome_key_is_refused(self):
        text = report_text(findings=[("F-101", "Minor", "quality", "none", "-", "x")])
        text = text.replace('{"F-101":"Open"}', '{"F-101":"Open","F-101":"Open"}')
        path = self.run_dir / "scratch" / "dup.md"
        path.write_text(text, encoding="utf-8")
        with self.assertRaises(pas.GateError):
            pas.record_master_report(str(self.run_dir), assignment="master-A",
                                     report_path=str(path))

    def test_an_unknown_severity_or_verdict_part_is_refused(self):
        for row in (("F-101", "Blocker", "quality", "none", "-", "x"),
                    ("F-101", "Minor", "style", "none", "-", "x")):
            with self.subTest(row=row), self.assertRaises(pas.GateError):
                publish_report(self.run_dir, findings=[row])

    def test_traces_to_must_be_a_spec_line_or_the_literal_none(self):
        with self.assertRaises(pas.GateError):
            publish_report(self.run_dir, findings=[
                ("F-101", "Minor", "quality", "somewhere in the spec", "-", "x")])

    def test_a_declared_finding_list_that_disagrees_with_the_table_is_refused(self):
        text = report_text(findings=[("F-101", "Minor", "quality", "none", "-", "x")])
        text = text.replace("| findings | F-101 |", "| findings | F-101,F-102 |")
        path = self.run_dir / "scratch" / "mismatch.md"
        path.write_text(text, encoding="utf-8")
        with self.assertRaises(pas.GateError):
            pas.record_master_report(str(self.run_dir), assignment="master-A",
                                     report_path=str(path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k FindingsLedger -k MasterReportBlock`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'parse_findings'`

- [ ] **Step 3: Write the implementation**

```python
SEVERITIES = ("Critical", "Important", "Minor")
VERDICT_PARTS = ("spec-compliance", "quality", "verification-evidence")
MASTER_REPORT_MARKER = "<!-- pipeline-auto-review-report/v1 -->"

_FINDINGS_MARKER = "<!-- pipeline-auto-findings/v1 -->"
_FINDING_COLUMNS = ("id", "scope", "severity", "status", "disposition",
                    "evidence", "adjudication", "fix_round", "re_review")
_FINDING_HEADERS = ("ID", "Scope", "Severity", "Status", "Disposition",
                    "Evidence", "Adjudication", "Fix Round", "Re-review")
_FINDING_STATUSES = ("open", "resolved")
_REPORT_FIELDS = ("gate", "assignment", "reviewer", "base", "head", "findings", "outcomes")
_FINDING_TABLE_HEADER = ("| Finding | Severity | Verdict Part | Traces To | "
                         "Requires Reversal Of | Claim |")
_SPEC_TRACE = re.compile(r"^[A-Za-z0-9_./-]+\.md:\d+$")


def _pipe_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_findings(text: str) -> list[dict]:
    if not text.startswith(_FINDINGS_MARKER):
        raise TrackerValidationError(f"findings.md must open with {_FINDINGS_MARKER}")
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = _pipe_cells(line)
        if cells[0] in ("ID", "---"):
            continue
        if len(cells) != len(_FINDING_COLUMNS):
            raise TrackerValidationError(
                f"findings row has {len(cells)} cells, expected {len(_FINDING_COLUMNS)}")
        row = dict(zip(_FINDING_COLUMNS, cells))
        if row["severity"] not in SEVERITIES:
            raise TrackerValidationError(
                f"{row['id']}: severity is Critical, Important or Minor")
        if row["status"] not in _FINDING_STATUSES:
            raise TrackerValidationError(f"{row['id']}: status is open or resolved")
        rows.append(row)
    return rows


def render_findings(rows: list) -> str:
    lines = [_FINDINGS_MARKER,
             "| " + " | ".join(_FINDING_HEADERS) + " |",
             "| " + " | ".join(["---"] * len(_FINDING_COLUMNS)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row.get(column) or "-"
                                       for column in _FINDING_COLUMNS) + " |")
    return "\n".join(lines) + "\n"


def upsert_finding(run_dir: str, row: dict) -> list[dict]:
    """Write one finding. A rediscovered issue keeps its ID.

    Two reviewers reporting the same defect must produce one row, or the
    zero-open-findings bar counts the same fix twice and a fixer is dispatched
    against a defect that no longer exists.
    """
    path = Path(run_dir) / "findings.md"
    rows = parse_findings(path.read_text(encoding="utf-8")) if path.exists() else []
    incoming = {column: row.get(column, "-") for column in _FINDING_COLUMNS}
    for index, existing in enumerate(rows):
        if existing["id"] == incoming["id"]:
            rows[index] = {**existing,
                           **{key: value for key, value in incoming.items() if value != "-"}}
            break
    else:
        rows.append(incoming)
    rendered = render_findings(rows)
    parse_findings(rendered)
    path.write_text(rendered, encoding="utf-8")
    return rows


def open_findings(run_dir: str) -> list[dict]:
    path = Path(run_dir) / "findings.md"
    if not path.exists():
        return []
    return [row for row in parse_findings(path.read_text(encoding="utf-8"))
            if row["status"] == "open"]


def _no_duplicate_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("repeated finding key")
    return dict(pairs)


def parse_master_report(text: str) -> dict:
    """Parse the terminal report block and the findings table above it."""
    if text.count(MASTER_REPORT_MARKER) != 1:
        raise GateError("a report carries exactly one terminal report block")
    narrative, _, trailer = text.partition(MASTER_REPORT_MARKER)

    fields, seen = {}, 0
    for line in trailer.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("|"):
            raise GateError("the report block must be terminal; nothing may follow it")
        cells = _pipe_cells(stripped)
        if len(cells) != 2:
            raise GateError("the report block is a two-column Field/Value table")
        if cells[0] in ("Field", "---"):
            continue
        if cells[0] in fields:
            raise GateError(f"duplicate report field {cells[0]!r}")
        fields[cells[0]] = cells[1]
        seen += 1
    missing = [name for name in _REPORT_FIELDS if name not in fields]
    if missing:
        raise GateError(f"report block is missing {missing[0]}")
    if seen != len(_REPORT_FIELDS):
        raise GateError("the report block carries exactly the seven known fields")

    findings, in_table = [], False
    for line in narrative.splitlines():
        stripped = line.strip()
        if stripped == _FINDING_TABLE_HEADER:
            in_table = True
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = _pipe_cells(stripped)
        if cells[0] == "---":
            continue
        if len(cells) != 6:
            raise GateError("a findings row has six cells")
        finding = dict(zip(("id", "severity", "verdict_part", "traces_to",
                            "requires_reversal_of", "claim"), cells))
        if finding["severity"] not in SEVERITIES:
            raise GateError(f"{finding['id']}: severity is Critical, Important or Minor")
        if finding["verdict_part"] not in VERDICT_PARTS:
            raise GateError(
                f"{finding['id']}: verdict part is spec-compliance, quality or "
                "verification-evidence — every routing decision at this gate reads it")
        trace = finding["traces_to"]
        if trace != "none" and not _SPEC_TRACE.fullmatch(trace):
            raise GateError(f"{finding['id']}: traces_to is <path>.md:<line> or none")
        findings.append(finding)

    declared = [] if fields["findings"] == "-" else _csv(fields["findings"])
    if declared != [finding["id"] for finding in findings]:
        raise GateError("the report block's findings list must match its findings table")
    try:
        outcomes = json.loads(fields["outcomes"], object_pairs_hook=_no_duplicate_keys)
    except ValueError as error:
        raise GateError(f"outcomes is one JSON object with unique keys: {error}") from None
    if sorted(outcomes) != sorted(declared):
        raise GateError("outcomes must map every declared finding exactly once")
    if any(value not in ("Open", "Resolved") for value in outcomes.values()):
        raise GateError("an outcome is Open or Resolved")
    return {**fields, "findings_table": findings, "outcomes": outcomes}


def _gate_row(tracker: dict) -> dict:
    gate = next((row for row in tracker["gates"] if row["id"] == MASTER_GATE_ID), None)
    if gate is None:
        raise GateError("the tracker has no master gate row")
    return gate


def record_master_report(run_dir: str, *, assignment: str, report_path: str) -> dict:
    """Seal one master report against the gate's CURRENT edge and bind it there.

    The gate's head advances through fix rounds; a sealed report does not. Each
    report is published under a head-qualified path and recorded in
    `report-bindings.json` with the exact edge it was written against, because
    the digest binding is what makes it evidence — rebinding a sealed report to a
    later head would silently claim a reviewer saw code they never read.
    """
    directory = Path(run_dir)
    sealed = _load_json(directory / "gate-master" / "assignments.json")
    if assignment not in sealed["assignments"]:
        raise GateError(f"{assignment} is not a sealed master assignment")
    tracker = parse_tracker((directory / "progress.md").read_text(encoding="utf-8"))
    gate = _gate_row(tracker)
    text = Path(report_path).read_text(encoding="utf-8")
    block = parse_master_report(text)
    expected = sealed["assignments"][assignment]
    if block["gate"] != MASTER_GATE_ID:
        raise GateError("the report names a different gate")
    if block["assignment"] != assignment:
        raise GateError("the report names a different assignment")
    if block["reviewer"] != expected["reviewer"]:
        raise GateError(
            f"{assignment} is sealed to {expected['reviewer']}, not {block['reviewer']}")
    if (block["base"], block["head"]) != (gate["base"], gate["head"]):
        raise GateError(
            "both master reports review the identical gate edge; this one reviewed "
            f"{block['base']}..{block['head']} rather than the gate's current "
            f"{gate['base']}..{gate['head']}")

    relative = f"gate-master/reports/{assignment}@{gate['head'][:12]}.md"
    digest = publish_immutable(str(directory / relative), text)
    bindings_path = directory / "gate-master" / "report-bindings.json"
    bindings = _load_json(bindings_path) if bindings_path.exists() else {}
    bindings[assignment] = {"base": gate["base"], "head": gate["head"],
                            "path": relative, "digest": digest}
    bindings_path.write_text(_dumps(bindings), encoding="utf-8")

    for finding in block["findings_table"]:
        upsert_finding(str(directory), {
            "id": finding["id"],
            "scope": MASTER_GATE_ID,
            "severity": finding["severity"],
            "status": "open" if block["outcomes"][finding["id"]] == "Open" else "resolved",
            "evidence": relative,
        })
    return {"assignment": assignment, "digest": digest, "path": relative,
            "base": gate["base"], "head": gate["head"],
            "findings": block["findings_table"], "outcomes": block["outcomes"]}
```

`report-bindings.json` sits beside `reports/` rather than inside it, so a directory listing
of `reports/` is exactly the set of sealed reports and nothing else.

Add `import json` to the module imports if P02/P03 have not already.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k FindingsLedger -k MasterReportBlock`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): bind master reports to the sealed gate edge"
```

---

### Task 5: The contradiction routing table

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `GateError`, P03's `parse_decisions`
- Produces: `ROUTES`, `_route`, `route_contradiction(decisions, item, *, prior_challenges=()) -> dict`

**What this function is, and is not.** It is the spec's contradiction-routing table written
once, as a pure function over the decision record and one item. The controller's only power
here is routing: it may **not** decide which of the reviewer and the decision record is
right, so nothing in this function inspects the merits of either claim. It reads provenance,
kind, severity, verdict part, and whether the D-ID has been challenged before.

**Named fault this task catches:** a **Minor quality** finding that would require reversing
a quorum decision winning automatically. Under zero-open-findings every Minor must be fixed,
so an automatic reviewer win lets a naming opinion silently overturn architecture. The
reviewer prevails **only** when the finding is Critical or Important **and** its verdict
part is spec-compliance or verification-evidence. Every other combination — a Minor of any
part, a quality-part finding of any severity — goes to an unbiased reconciliation.

**Second named fault:** a `DECISION-CHALLENGE` against a `Provenance: human` decision
reaching the quorum. Three brains cannot be asked whether the user meant what the user said.
The route is `halt-escalation`, at any confidence and any severity, and `dispatch_brains` is
`False` for it and for every other halt.

- [ ] **Step 1: Write the failing tests**

```python
class ContradictionRouting(unittest.TestCase):
    def setUp(self):
        self.decisions = pas.parse_decisions(fixture("master-gate-decisions.md"))

    def test_code_not_complying_with_a_decision_is_an_ordinary_fix(self):
        routed = pas.route_contradiction(self.decisions, {
            "kind": "finding", "severity": "Critical",
            "verdict_part": "spec-compliance", "decision_id": None})
        self.assertEqual(routed["route"], "ordinary-fix-loop")
        self.assertFalse(routed["dispatch_brains"])

    def test_a_plan_mandated_finding_tracing_to_a_human_decision_halts(self):
        routed = pas.route_contradiction(self.decisions, {
            "kind": "plan-mandated", "decision_id": "H-001"})
        self.assertEqual(routed["route"], "halt-escalation")
        self.assertFalse(routed["dispatch_brains"])

    def test_a_plan_mandated_finding_tracing_to_a_quorum_decision_reopens(self):
        routed = pas.route_contradiction(self.decisions, {
            "kind": "plan-mandated", "decision_id": "Q-7c6b5a4938d2"})
        self.assertEqual(routed["route"], "reopen-raised-bar")
        self.assertTrue(routed["dispatch_brains"])

    def test_a_plan_invented_requirement_is_an_ordinary_quorum(self):
        routed = pas.route_contradiction(self.decisions, {
            "kind": "plan-mandated", "decision_id": None})
        self.assertEqual(routed["route"], "ordinary-quorum")
        self.assertTrue(routed["dispatch_brains"])

    def test_a_challenge_to_a_human_decision_always_halts(self):
        # THE OVERRULE SEED. A reviewer does not overrule the one human gate, at
        # any confidence and at any severity.
        for severity in pas.SEVERITIES:
            with self.subTest(severity=severity):
                routed = pas.route_contradiction(self.decisions, {
                    "kind": "DECISION-CHALLENGE", "decision_id": "H-001",
                    "severity": severity})
                self.assertEqual(routed["route"], "halt-escalation")
                self.assertFalse(routed["dispatch_brains"])

    def test_a_challenge_to_a_quorum_decision_reopens_once(self):
        routed = pas.route_contradiction(self.decisions, {
            "kind": "DECISION-CHALLENGE", "decision_id": "Q-3f2a1b0c9d8e"})
        self.assertEqual(routed["route"], "reopen-raised-bar")

    def test_a_second_challenge_to_one_d_id_halts_automatically(self):
        routed = pas.route_contradiction(
            self.decisions,
            {"kind": "DECISION-CHALLENGE", "decision_id": "Q-3f2a1b0c9d8e"},
            prior_challenges=("Q-3f2a1b0c9d8e",))
        self.assertEqual(routed["route"], "halt-second-challenge")
        self.assertFalse(routed["dispatch_brains"])

    def test_a_fixer_dispute_goes_to_one_adjudicator_not_three_brains(self):
        routed = pas.route_contradiction(self.decisions, {
            "kind": "fixer-dispute", "refutation": "tests/test_x.py:41 asserts the opposite"})
        self.assertEqual(routed["route"], "adjudicator")
        self.assertFalse(routed["dispatch_brains"])

    def test_a_bare_fixer_disagreement_leaves_the_finding_standing(self):
        routed = pas.route_contradiction(self.decisions, {
            "kind": "fixer-dispute", "refutation": ""})
        self.assertEqual(routed["route"], "ordinary-fix-loop")

    def test_a_minor_quality_reversal_goes_to_reconciliation_not_an_automatic_win(self):
        # THE SILENT-OVERTURN SEED. Under zero-open-findings every Minor must be
        # fixed, so an automatic reviewer win lets a naming opinion overturn
        # architecture.
        routed = pas.route_contradiction(self.decisions, {
            "kind": "finding", "severity": "Minor", "verdict_part": "quality",
            "decision_id": "Q-7c6b5a4938d2"})
        self.assertEqual(routed["route"], "unbiased-reconciliation")
        self.assertFalse(routed["dispatch_brains"])

    def test_the_reviewer_prevails_only_on_blocking_spec_or_verification_parts(self):
        prevails = [("Critical", "spec-compliance"), ("Important", "spec-compliance"),
                    ("Critical", "verification-evidence"),
                    ("Important", "verification-evidence")]
        reconciles = [("Minor", "spec-compliance"), ("Minor", "verification-evidence"),
                      ("Minor", "quality"), ("Critical", "quality"),
                      ("Important", "quality")]
        for severity, part in prevails:
            with self.subTest(severity=severity, part=part):
                self.assertEqual(pas.route_contradiction(self.decisions, {
                    "kind": "finding", "severity": severity, "verdict_part": part,
                    "decision_id": "Q-7c6b5a4938d2"})["route"], "reviewer-prevails")
        for severity, part in reconciles:
            with self.subTest(severity=severity, part=part):
                self.assertEqual(pas.route_contradiction(self.decisions, {
                    "kind": "finding", "severity": severity, "verdict_part": part,
                    "decision_id": "Q-7c6b5a4938d2"})["route"], "unbiased-reconciliation")

    def test_exactly_two_routes_dispatch_brains(self):
        self.assertEqual(
            {route for route in pas.ROUTES
             if pas._route(route, "x")["dispatch_brains"]},
            {"ordinary-quorum", "reopen-raised-bar"})

    def test_an_unknown_decision_id_is_an_error_not_a_default_route(self):
        with self.assertRaises(pas.GateError):
            pas.route_contradiction(self.decisions, {
                "kind": "DECISION-CHALLENGE", "decision_id": "Q-deadbeefdead"})

    def test_an_unknown_kind_is_an_error(self):
        with self.assertRaises(pas.GateError):
            pas.route_contradiction(self.decisions, {"kind": "vibes"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ContradictionRouting`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'route_contradiction'`

- [ ] **Step 3: Write the implementation**

```python
ROUTES = ("ordinary-fix-loop", "ordinary-quorum", "adjudicator", "reopen-raised-bar",
          "unbiased-reconciliation", "reviewer-prevails", "halt-escalation",
          "halt-second-challenge")
_BRAIN_ROUTES = frozenset({"ordinary-quorum", "reopen-raised-bar"})
_BLOCKING_SEVERITIES = frozenset({"Critical", "Important"})
_REVERSING_PARTS = frozenset({"spec-compliance", "verification-evidence"})


def _route(route: str, reason: str, decision_id: str | None = None) -> dict:
    if route not in ROUTES:
        raise GateError(f"unknown route {route!r}")
    return {"route": route, "reason": reason, "decision_id": decision_id,
            "dispatch_brains": route in _BRAIN_ROUTES}


def route_contradiction(decisions: dict, item: dict, *, prior_challenges=()) -> dict:
    """The spec's contradiction-routing table, as one pure function.

    The controller's only power here is routing. It may not decide which of the
    reviewer and the decision record is right, so nothing below inspects the
    merits of either claim: only provenance, kind, severity, verdict part, and
    whether this D-ID has been challenged before.
    """
    kind = item.get("kind")
    records = decisions["decisions"]
    decision_id = item.get("decision_id")
    record = None
    if decision_id:
        record = records.get(decision_id)
        if record is None:
            raise GateError(f"{decision_id} is not a recorded decision")

    if kind == "fixer-dispute":
        # A fact, not a decision. "Can line 41 be null" is settled by reading code
        # and running an experiment; three models agreeing is far weaker evidence
        # than one model running the test. Routing facts to the quorum is the
        # mechanism by which a quorum degrades into an ask-three-models reflex.
        if not str(item.get("refutation", "")).strip():
            return _route("ordinary-fix-loop",
                          "a dispute with no file:line or command output is "
                          "inadmissible; the finding stands")
        return _route("adjudicator",
                      "one adjudicator settles the fact by citation or focused "
                      "experiment; only a PLAUSIBLE verdict becomes a quorum question")

    if kind == "DECISION-CHALLENGE":
        if decision_id in tuple(prior_challenges):
            return _route("halt-second-challenge",
                          f"{decision_id} has already been challenged once in this run; "
                          "a second challenge is the anti-oscillation halt",
                          decision_id)
        if record["provenance"] == "human":
            return _route("halt-escalation",
                          "a reviewer does not overrule the one human gate; a maintained "
                          "objection escalates as a report of consequence",
                          decision_id)
        return _route("reopen-raised-bar",
                      "one re-open at a raised bar, at most once per D-ID per run",
                      decision_id)

    if kind == "plan-mandated":
        if record is None:
            return _route("ordinary-quorum",
                          "the plan invented this requirement; no recorded decision "
                          "backs it")
        if record["provenance"] == "human":
            return _route("halt-escalation",
                          "the mandate traces to a human decision", decision_id)
        return _route("reopen-raised-bar",
                      "the mandate traces to a quorum decision", decision_id)

    if kind == "finding":
        if record is None:
            return _route("ordinary-fix-loop",
                          "code does not comply with a decision; ordinary fix loop")
        severity = item.get("severity")
        part = item.get("verdict_part")
        if severity not in SEVERITIES:
            raise GateError(f"unknown severity {severity!r}")
        if part not in VERDICT_PARTS:
            raise GateError(f"unknown verdict part {part!r}")
        if severity in _BLOCKING_SEVERITIES and part in _REVERSING_PARTS:
            return _route("reviewer-prevails",
                          "a blocking spec-compliance or verification-evidence finding "
                          "outranks the decision it contradicts", decision_id)
        # Under zero-open-findings every Minor must be fixed, so an automatic
        # reviewer win would let a naming opinion silently overturn architecture.
        return _route("unbiased-reconciliation",
                      "a Minor, or any quality-part finding, that would require "
                      "reversing a recorded decision goes to an unbiased reconciliation",
                      decision_id)

    raise GateError(f"unknown contradiction kind {kind!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k ContradictionRouting`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): route contradictions without deciding them"
```

---

### Task 6: The challenge ledger, the halt, and the raised bar

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `route_contradiction`, P03's `parse_decisions`, `derive_qid`, `RUNG_ORDER`, P02's `locked_tracker_update`, `append_row`, `derive_next_action`, `publish_immutable`
- Produces: `_CHALLENGE_PROHIBITED`, `raised_floor(rung) -> str`, `_queue_escalation`, `_challenge_ledger`, `record_challenge(run_dir, *, challenge) -> dict`

**Named fault this task catches:** a `DECISION-CHALLENGE` against a `Provenance: human`
decision reaching the quorum. The test asserts the halt reaches the escalation queue **and**
that the run directory gained **zero** brain dispatch records — no `quorum/<qid>/` directory,
no `open.json`, nothing. Routing correctly and dispatching anyway is a real failure mode:
the routing table returns a string, and a caller that reads the string and then calls
`open_quorum` regardless has satisfied the router and broken the invariant. This transition
is where that becomes impossible, because the halt path has no dispatch in it at all.

A challenge record carries `evidence` and `consequence`. It may not carry
`requested_answer`, `proposed_answer` or `replacement_answer`, and the presence of one is an
error rather than an ignored field — a reviewer reports what a decision **costs** and never
proposes the answer that replaces it. A challenge to a human decision with no stated
consequence is refused for the same reason: consequence is the only form in which the
objection may travel.

**The raised bar has arithmetic, and it must be applied rather than recorded.** "At a
raised bar" with no definition is a mood. The re-open's floor is one rung above the
decision's own grounding rung, clamped at the top of the ladder, and the re-open record
carries the challenging evidence and **not** the original rung, the original answer, or the
identities that adopted it.

**Third named fault, from the master plan's cross-phase clarifications:** the raised bar
recorded in the quorum row and never consulted at adoption. That is a silent no-op, and it
passes every test that inspects the row's contents — which is why `RaisedBarIsApplied` below
drives the real adoption path and carries a control case. A re-opened question adopts only
when the winning cluster's rung is **strictly higher than the rung originally adopted**, not
merely above the floor.

- [ ] **Step 1: Write the failing tests**

```python
class DecisionChallenge(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = new_run(self.stack)
        opened_gate(self.run_dir)

    def challenge(self, **overrides):
        payload = {"kind": "DECISION-CHALLENGE", "decision_id": "H-001",
                   "reviewer": "reviewer-a",
                   "evidence": "scripts/pipeline_auto_state.py:812",
                   "consequence": "A thirty-second bound drops every contended transition."}
        payload.update(overrides)
        return pas.record_challenge(str(self.run_dir), challenge=payload)

    def test_raised_floor_climbs_one_rung_and_clamps_at_the_top(self):
        self.assertEqual(pas.raised_floor("code-evidenced"), "specified")
        self.assertEqual(pas.raised_floor("convention-cited"), "code-evidenced")
        self.assertEqual(pas.raised_floor("specified"), "specified")

    def test_a_challenge_to_a_human_decision_halts_with_zero_brain_dispatches(self):
        # THE OVERRULE SEED, at the transition. Routing correctly and dispatching
        # anyway is a real failure: the halt path contains no dispatch at all.
        routed = self.challenge()
        self.assertEqual(routed["route"], "halt-escalation")
        self.assertTrue(routed["escalated"])
        self.assertIsNone(routed["reopened"])
        self.assertFalse((self.run_dir / "quorum").exists())
        ledger = json.loads((self.run_dir / "gate-master" / "challenges.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual([entry["dispatched_brains"] for entry in ledger], [False])

    def test_the_halt_reaches_the_escalation_queue_and_the_next_action(self):
        self.challenge()
        tracker = tracker_of(self.run_dir)
        queued = [row for row in tracker["escalations"] if row["state"] == "queued"]
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["blast"], "run")
        self.assertEqual(pas.derive_next_action(tracker), "await-escalation-batch")

    def test_a_human_challenge_without_a_consequence_is_refused(self):
        with self.assertRaises(pas.GateError):
            self.challenge(consequence="   ")

    def test_a_challenge_proposing_a_replacement_answer_is_refused(self):
        for key in ("requested_answer", "proposed_answer", "replacement_answer"):
            with self.subTest(key=key), self.assertRaises(pas.GateError) as caught:
                self.challenge(**{key: "use a lock-free queue"})
            self.assertIn(key, str(caught.exception))

    def test_a_quorum_challenge_writes_a_reopen_at_a_raised_floor(self):
        routed = self.challenge(decision_id="Q-7c6b5a4938d2",
                                consequence="", evidence="tests/test_render.py:88")
        self.assertEqual(routed["route"], "reopen-raised-bar")
        qid = pas.derive_qid("In what order does render_tracker emit the eleven sections?",
                             "render-order")
        text = (self.run_dir / "quorum" / qid / "reopen.json").read_text(encoding="utf-8")
        self.assertIn("tests/test_render.py:88", text)
        self.assertIn("specified", text)          # the RAISED floor

    def test_the_reopen_record_leaks_neither_the_original_rung_nor_who_adopted_it(self):
        self.challenge(decision_id="Q-7c6b5a4938d2", consequence="",
                       evidence="tests/test_render.py:88")
        qid = pas.derive_qid("In what order does render_tracker emit the eleven sections?",
                             "render-order")
        text = (self.run_dir / "quorum" / qid / "reopen.json").read_text(encoding="utf-8")
        for leak in ("code-evidenced", "engineering-judgement", "brain-4", "brain-5",
                     "brain-6", "schema-order"):
            self.assertNotIn(leak, text)

    def test_a_second_challenge_to_one_d_id_halts_and_dispatches_nothing(self):
        self.challenge(decision_id="Q-3f2a1b0c9d8e", consequence="",
                       evidence="tests/test_lock.py:12")
        second = self.challenge(decision_id="Q-3f2a1b0c9d8e", consequence="",
                                evidence="tests/test_lock.py:19")
        self.assertEqual(second["route"], "halt-second-challenge")
        self.assertTrue(second["escalated"])
        ledger = json.loads((self.run_dir / "gate-master" / "challenges.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(len(ledger), 2)
        self.assertFalse(any(entry["dispatched_brains"] for entry in ledger))
```

```python
class RaisedBarIsApplied(unittest.TestCase):
    """A raised bar recorded and never applied is a silent no-op, and it passes
    every test that only inspects the re-open record.

    The master plan's cross-phase clarification is binding: a re-opened
    question's adoption requires the winning cluster's rung to be **strictly
    higher than the rung originally adopted**, not merely above the floor. P03
    owns that path; this is P06's assertion at the seam, and the third test is
    the control that makes the first two discriminating rather than merely
    green.
    """

    QUESTION = "In what order does render_tracker emit the eleven sections?"
    AXIS = "render-order"

    def reopened(self, stack):
        root, run_dir = new_run(stack)
        # `repo_root` is a ## Run field, never derived from run-directory depth:
        # citation resolution must land on the tree these responses actually cite.
        text = (run_dir / "progress.md").read_text(encoding="utf-8").replace(
            "| repo_root | . |", f"| repo_root | {root} |")
        (run_dir / "progress.md").write_text(text, encoding="utf-8")
        write_repo(root, "scripts/render.py", "SECTIONS = SCHEMA_ORDER\n")
        write_repo(root, "spec.md", "The renderer emits sections in schema order.\n")
        opened_gate(run_dir)
        pas.record_challenge(str(run_dir), challenge={
            "kind": "DECISION-CHALLENGE", "decision_id": "Q-7c6b5a4938d2",
            "reviewer": "reviewer-a", "evidence": "tests/test_render.py:88",
            "consequence": ""})
        return root, run_dir

    def question_record(self, run_dir, *, question, axis):
        record = {"question": question, "axis": axis, "phase": "P02",
                  "blocks": ["gate-master"], "raiser": "reviewer-a",
                  "options_supplied": True,
                  "options": [{"key": "schema-order"}, {"key": "alphabetical"}],
                  "candidate_answers": [], "recommendation": "-",
                  "reading_roots": {"repo": ".", "spec": "spec.md"},
                  "owners": ["brain-7", "brain-8", "brain-9"]}
        path = Path(run_dir) / "scratch" / f"{axis}-question.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return str(path)

    def run_quorum(self, run_dir, *, question, axis, rung):
        qid = pas.derive_qid(question, axis)
        pas.open_quorum(str(run_dir), question_record=self.question_record(
            run_dir, question=question, axis=axis))
        evidence = ([{"kind": "spec", "path": "spec.md", "line": 1,
                      "quote": "schema order"}] if rung == "specified"
                    else [{"kind": "repo", "path": "scripts/render.py", "line": 1,
                           "quote": "SCHEMA_ORDER"}])
        for owner in ("brain-7", "brain-8", "brain-9"):
            pas.record_brain_response(str(run_dir), qid=qid, owner=owner, payload=response(
                qid=qid, answer_key="schema-order",
                answer="Emit the eleven sections in schema order.",
                rung=rung, evidence=evidence,
                consequences=[{"kind": "signature", "subject": "render_tracker",
                               "value": "schema-order"}],
                consistent_with=[{"kind": "decision", "id": "H-001"}],
                blast=[axis],
                alternatives=[{"answer_key": "alphabetical", "rung": "speculation",
                               "reason": "no reader expects it"}]))
        return pas.finalize_quorum(str(run_dir), qid=qid)

    def test_a_reopen_refuses_an_answer_that_only_clears_the_floor(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = self.reopened(stack)
            result = self.run_quorum(run_dir, question=self.QUESTION, axis=self.AXIS,
                                     rung="code-evidenced")
            self.assertNotEqual(result["status"], "adopted")

    def test_a_reopen_adopts_only_strictly_above_the_original_rung(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = self.reopened(stack)
            result = self.run_quorum(run_dir, question=self.QUESTION, axis=self.AXIS,
                                     rung="specified")
            self.assertEqual(result["status"], "adopted")

    def test_control_the_same_answer_adopts_on_a_question_never_reopened(self):
        # Without this control the first test passes against any run that simply
        # escalates everything, and the raised bar would still be a no-op.
        with contextlib.ExitStack() as stack:
            _root, run_dir = self.reopened(stack)
            result = self.run_quorum(run_dir, question="Which newline does render use?",
                                     axis="newline", rung="code-evidenced")
            self.assertEqual(result["status"], "adopted")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k DecisionChallenge -k RaisedBarIsApplied`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'raised_floor'`

- [ ] **Step 3: Write the implementation**

```python
_CHALLENGE_PROHIBITED = ("requested_answer", "proposed_answer", "replacement_answer")


def raised_floor(rung: str) -> str:
    """One rung above, clamped at the top of the ladder.

    "At a raised bar" with no arithmetic behind it is a mood. RUNG_ORDER runs
    highest first, so the raised floor is the entry one index earlier.
    """
    return RUNG_ORDER[max(RUNG_ORDER.index(rung) - 1, 0)]


def _challenge_ledger(run_dir) -> list:
    path = Path(run_dir) / "gate-master" / "challenges.json"
    return _load_json(path) if path.exists() else []


def _queue_escalation(run_dir: str, *, blast: str, reason: str) -> dict:
    """Queue one escalation. Escalations surface at stage boundaries, batched."""
    def mutate(tracker):
        taken = {row["id"] for row in tracker["escalations"]}
        index = 1
        while f"E-{index}" in taken:
            index += 1
        return append_row(tracker, "escalations", {
            "id": f"E-{index}", "qid": "-", "blast": blast,
            "state": "queued", "batch": "-", "resolution": "-"})

    return locked_tracker_update(
        run_dir, transition_id=f"escalate-{_digest(reason)[:12]}", mutate=mutate)


def record_challenge(run_dir: str, *, challenge: dict) -> dict:
    """Route one DECISION-CHALLENGE and act on the route.

    The halt path contains no dispatch. That matters more than the routing:
    `route_contradiction` returns a string, and a caller that reads the string
    and calls `open_quorum` anyway has satisfied the router while breaking the
    invariant. Here there is nothing to call.
    """
    directory = Path(run_dir)
    for key in _CHALLENGE_PROHIBITED:
        if key in challenge:
            raise GateError(
                f"a DECISION-CHALLENGE carries evidence and consequence, never {key}: "
                "a reviewer reports what a decision costs and never proposes the answer "
                "that would replace it")
    parsed = parse_decisions((directory / "decisions.md").read_text(encoding="utf-8"))
    prior = [entry["decision_id"] for entry in _challenge_ledger(directory)]
    routed = route_contradiction(parsed, dict(challenge, kind="DECISION-CHALLENGE"),
                                 prior_challenges=prior)
    record = parsed["decisions"][challenge["decision_id"]]
    if (routed["route"] == "halt-escalation"
            and not str(challenge.get("consequence", "")).strip()):
        raise GateError(
            "a challenge to a human decision must state the consequence that decision "
            "causes; a report of consequence is the only form in which the objection "
            "may travel")

    entry = {"decision_id": challenge["decision_id"],
             "reviewer": challenge.get("reviewer", "-"),
             "route": routed["route"], "reason": routed["reason"],
             "evidence": challenge.get("evidence", ""),
             "consequence": challenge.get("consequence", ""),
             "dispatched_brains": False}
    gate_dir = directory / "gate-master"
    gate_dir.mkdir(exist_ok=True)
    (gate_dir / "challenges.json").write_text(
        _dumps(_challenge_ledger(directory) + [entry]), encoding="utf-8")

    if routed["route"] in ("halt-escalation", "halt-second-challenge"):
        _queue_escalation(str(directory), blast="run", reason=routed["reason"])
        return dict(routed, escalated=True, reopened=None)

    # A re-open at a raised bar. The record carries the challenging evidence and
    # never the original score or who chose it: a brain that learns the previous
    # answer and its grounding is anchored to it, and the re-open would measure
    # agreement with the last quorum instead of the question.
    reopen = {"axis": record["axis"], "question": record["question"],
              "raised_floor": raised_floor(record.get("grounding_rung", "code-evidenced")),
              "challenging_evidence": challenge.get("evidence", "")}
    qid = derive_qid(record["question"], record["axis"])
    target = directory / "quorum" / qid
    target.mkdir(parents=True, exist_ok=True)
    publish_immutable(str(target / "reopen.json"), _dumps(reopen))
    return dict(routed, escalated=False, reopened=reopen)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k DecisionChallenge -k RaisedBarIsApplied`
Expected: PASS (11 tests)

`RaisedBarIsApplied` exercises P03's adoption path, not P06's code. If it fails
because `finalize_quorum` ignores `reopen.json`, **that is the defect it exists to
catch** — the raised bar is recorded and never applied — and the fix belongs in P03,
not in weakening this test. The three tests reuse P03's `response()` and
`write_repo()` helpers, already in this module.

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): halt every challenge to a human decision, dispatching nothing"
```

---
### Task 7: Unbiased reconciliation, and the fix-round counter that does not move

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `owner_history`, `upsert_finding`, `GateError`, P03's `parse_decisions`, P02's `locked_tracker_update`, `_load_json`
- Produces: `RECONCILIATION_OUTCOMES`, `open_reconciliation(run_dir, *, finding_id, decision_id, scope) -> dict`, `record_reconciliation(run_dir, *, finding_id, decision_id, adjudicator, outcome, evidence) -> dict`, `supersede_decision(run_dir, *, decision_id) -> str`

**Named fault this task catches:** the fix-round counter incrementing during a
reconciliation. A reconciliation is a dispute about which of two *recorded* authorities
governs; it is not a fix attempt. If it burns a round, three ordinary disputes exhaust the
budget and the run escalates reporting "three fix rounds failed to resolve the blockers",
which is false and points a human at the wrong problem. The test compares the scope's fix
rounds before and after, by number.

**Second named fault:** the reconciliation adjudicated by someone with a stake. Either
master reviewer would be defending their own finding and any prior owner would be defending
their own code, so both are ineligible — the same rule as reviewer independence, applied to
the one agent who breaks the tie.

**The one principled exception to zero-open-findings.** When the decision survives, the
finding is recorded `REFUTED — governed by <D-ID>` with status `resolved`, and therefore
does not block completion. It is narrow (only a finding that would *reverse* a recorded
decision can reach here), recorded (the disposition names the governing decision), and
mechanical (`open_findings` filters on status, so the exception needs no special case at
the gate).

- [ ] **Step 1: Write the failing tests**

```python
class Reconciliation(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = new_run(self.stack)
        opened_gate(self.run_dir)
        publish_report(self.run_dir, findings=[
            ("F-101", "Minor", "quality", "none", "Q-7c6b5a4938d2",
             "`render_tracker` should be called `emit_tracker`.")])

    def rounds(self):
        return [row["round"] for row in tracker_of(self.run_dir)["fix_rounds"]
                if row["scope"] == "P02-T01"]

    def test_a_reconciliation_does_not_burn_a_fix_round(self):
        # THE WRONG-BUDGET SEED. A decision dispute that consumes a fix round
        # makes the run escalate "three fix rounds failed" — which is false, and
        # sends a human after the wrong problem.
        before = self.rounds()
        pas.open_reconciliation(str(self.run_dir), finding_id="F-101",
                                decision_id="Q-7c6b5a4938d2", scope="P02-T01")
        pas.record_reconciliation(str(self.run_dir), finding_id="F-101",
                                  decision_id="Q-7c6b5a4938d2",
                                  adjudicator="adjudicator-1",
                                  outcome="decision-survives",
                                  evidence="scripts/pipeline_auto_state.py:640")
        self.assertEqual(self.rounds(), before)
        self.assertEqual(before, ["1"])

    def test_a_surviving_decision_refutes_the_finding_and_unblocks_completion(self):
        pas.open_reconciliation(str(self.run_dir), finding_id="F-101",
                                decision_id="Q-7c6b5a4938d2", scope="P02-T01")
        pas.record_reconciliation(str(self.run_dir), finding_id="F-101",
                                  decision_id="Q-7c6b5a4938d2",
                                  adjudicator="adjudicator-1",
                                  outcome="decision-survives",
                                  evidence="scripts/pipeline_auto_state.py:640")
        ledger = (self.run_dir / "findings.md").read_text(encoding="utf-8")
        self.assertIn("REFUTED — governed by Q-7c6b5a4938d2", ledger)
        self.assertEqual([row["id"] for row in pas.open_findings(str(self.run_dir))], [])

    def test_a_prevailing_finding_supersedes_the_decision_and_still_blocks(self):
        pas.open_reconciliation(str(self.run_dir), finding_id="F-101",
                                decision_id="Q-7c6b5a4938d2", scope="P02-T01")
        pas.record_reconciliation(str(self.run_dir), finding_id="F-101",
                                  decision_id="Q-7c6b5a4938d2",
                                  adjudicator="adjudicator-1",
                                  outcome="finding-prevails",
                                  evidence="tests/test_render.py:88")
        decisions = pas.parse_decisions(
            (self.run_dir / "decisions.md").read_text(encoding="utf-8"))
        self.assertEqual(decisions["decisions"]["Q-7c6b5a4938d2"]["status"], "Superseded")
        self.assertEqual([row["id"] for row in pas.open_findings(str(self.run_dir))],
                         ["F-101"])

    def test_superseding_is_the_only_in_place_mutation_and_is_idempotent(self):
        first = pas.supersede_decision(str(self.run_dir), decision_id="Q-7c6b5a4938d2")
        second = pas.supersede_decision(str(self.run_dir), decision_id="Q-7c6b5a4938d2")
        self.assertEqual(first, second)
        self.assertEqual(first.count("## Q-7c6b5a4938d2"), 1)

    def test_a_master_reviewer_cannot_adjudicate_their_own_finding(self):
        pas.open_reconciliation(str(self.run_dir), finding_id="F-101",
                                decision_id="Q-7c6b5a4938d2", scope="P02-T01")
        for biased in ("reviewer-a", "reviewer-b", "impl-2", "fixer-1"):
            with self.subTest(adjudicator=biased), \
                 self.assertRaises(pas.ReviewerIndependenceError):
                pas.record_reconciliation(str(self.run_dir), finding_id="F-101",
                                          decision_id="Q-7c6b5a4938d2",
                                          adjudicator=biased,
                                          outcome="decision-survives", evidence="x:1")

    def test_an_unknown_outcome_is_refused(self):
        pas.open_reconciliation(str(self.run_dir), finding_id="F-101",
                                decision_id="Q-7c6b5a4938d2", scope="P02-T01")
        with self.assertRaises(pas.GateError):
            pas.record_reconciliation(str(self.run_dir), finding_id="F-101",
                                      decision_id="Q-7c6b5a4938d2",
                                      adjudicator="adjudicator-1",
                                      outcome="split-the-difference", evidence="x:1")

    def test_opening_writes_the_reconciliation_question_the_task_points_at(self):
        opened = pas.open_reconciliation(str(self.run_dir), finding_id="F-101",
                                         decision_id="Q-7c6b5a4938d2", scope="P02-T01")
        question = self.run_dir / opened["question"]
        self.assertTrue(question.exists())
        text = question.read_text(encoding="utf-8")
        self.assertIn("F-101", text)
        self.assertIn("Q-7c6b5a4938d2", text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Reconciliation`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'open_reconciliation'`

- [ ] **Step 3: Write the implementation**

```python
RECONCILIATION_OUTCOMES = ("decision-survives", "finding-prevails")


def open_reconciliation(run_dir: str, *, finding_id: str, decision_id: str,
                        scope: str) -> dict:
    """Park the disputed work and write the reconciliation question.

    The fix loop does not stall during a reconciliation: independent work
    continues, and the fix-round counter DOES NOT INCREMENT. A reconciliation is
    a dispute about which of two recorded authorities governs, not a fix
    attempt; charging it a round makes three ordinary disputes escalate the run
    as "three fix rounds failed to resolve the blockers", which is false and
    points a human at the wrong problem.

    A parked task keeps its recorded owner — a `[?]` task must name an owner to
    be resumable — while its capacity slot is free for other work.
    """
    directory = Path(run_dir)
    folder = directory / "gate-master" / "reconciliations"
    folder.mkdir(parents=True, exist_ok=True)
    relative = f"gate-master/reconciliations/{finding_id}.md"
    (directory / relative).write_text(
        f"# Reconciliation — {finding_id} against {decision_id}\n\n"
        f"- **Finding:** {finding_id}\n"
        f"- **Decision:** {decision_id}\n"
        f"- **Scope:** {scope}\n\n"
        "The finding would require reversing the decision, and it is not a blocking\n"
        "spec-compliance or verification-evidence finding, so neither side wins\n"
        "automatically. An unbiased adjudicator — not a master reviewer, not the fixer,\n"
        "not any prior owner in this run — settles which authority governs.\n",
        encoding="utf-8")

    def mutate(tracker):
        task = next((row for row in tracker["tasks"] if row["id"] == scope), None)
        if task is not None and task["state"] == "[~]":
            task["state"] = "[?]"
            task["question"] = relative
        return tracker

    locked_tracker_update(str(directory),
                          transition_id=f"reconcile-open-{finding_id}", mutate=mutate)
    return {"finding": finding_id, "decision": decision_id, "scope": scope,
            "question": relative, "fix_round_consumed": False}


def supersede_decision(run_dir: str, *, decision_id: str) -> str:
    """`Adopted -> Superseded`, the ONLY legal in-place mutation of decisions.md.

    The file is append-only and is the run's audit trail. This is the one
    function that edits a byte already in it, and it edits exactly one field.
    """
    path = Path(run_dir) / "decisions.md"
    text = path.read_text(encoding="utf-8")
    parsed = parse_decisions(text)
    if decision_id not in parsed["decisions"]:
        raise GateError(f"{decision_id} is not a recorded decision")
    if parsed["decisions"][decision_id]["status"] != "Adopted":
        return text
    lines = text.splitlines(keepends=True)
    start = next(index for index, line in enumerate(lines)
                 if line.startswith(f"## {decision_id} "))
    end = next((index for index in range(start + 1, len(lines))
                if lines[index].startswith("## ")), len(lines))
    for index in range(start, end):
        if lines[index].startswith("- **Status:**"):
            lines[index] = "- **Status:** Superseded\n"
            break
    else:
        raise TrackerValidationError(f"{decision_id} has no Status field")
    updated = "".join(lines)
    parse_decisions(updated)
    path.write_text(updated, encoding="utf-8")
    return updated


def record_reconciliation(run_dir: str, *, finding_id: str, decision_id: str,
                          adjudicator: str, outcome: str, evidence: str) -> dict:
    """Settle one reconciliation. Still no fix round consumed."""
    if outcome not in RECONCILIATION_OUTCOMES:
        raise GateError(
            f"a reconciliation returns {RECONCILIATION_OUTCOMES}, not {outcome!r}; "
            "there is no third outcome and no controller override")
    directory = Path(run_dir)
    sealed = _load_json(directory / "gate-master" / "assignments.json")
    reviewers = {entry["reviewer"] for entry in sealed["assignments"].values()}
    if adjudicator in reviewers or adjudicator in owner_history(str(directory)):
        raise ReviewerIndependenceError(
            f"{adjudicator} has a stake: a master reviewer would be defending their own "
            "finding and a prior owner would be defending their own code")

    if outcome == "decision-survives":
        # The one principled exception to zero open findings: narrow, because only
        # a finding that would REVERSE a recorded decision can reach here; and
        # recorded, because the disposition names the decision that governs.
        upsert_finding(str(directory), {
            "id": finding_id, "status": "resolved",
            "disposition": f"REFUTED — governed by {decision_id}",
            "adjudication": f"reconciled:{adjudicator}", "evidence": evidence})
    else:
        supersede_decision(str(directory), decision_id=decision_id)
        upsert_finding(str(directory), {
            "id": finding_id, "status": "open",
            "adjudication": f"reconciled:{adjudicator}", "evidence": evidence})

    record = {"finding": finding_id, "decision": decision_id, "outcome": outcome,
              "adjudicator": adjudicator, "evidence": evidence,
              "fix_round_consumed": False}
    publish_immutable(
        str(directory / "gate-master" / "reconciliations" / f"{finding_id}.json"),
        _dumps(record))
    return record
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k Reconciliation`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): reconcile decision disputes without burning a fix round"
```

---

### Task 8: The completeness critic's two classes, and the freeze

**Files:**
- Create: `plugins/superb/skills/pipeline-auto/templates/completeness-proposals.md`
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `upsert_finding`, `create_phase`, `PhaseSetFrozen`, `_SPEC_TRACE`, `GateError`, P03's `check_admissible` and `open_quorum`
- Produces: `CRITIC_CLASSES`, `PROPOSALS_MARKER`, `classify_completeness_item(item) -> str`, `record_completeness(run_dir, *, items) -> dict`, `completeness_proposals(run_dir) -> list[dict]`

**Named fault this task catches:** the critic's two classes collapsing into one.
`SPEC-NOT-MET` is **not** a proposal — it means an approved requirement is unmet, so it is a
Critical finding and it blocks at the zero-open-findings bar. `MISSING-FROM-SPEC` is frozen
to `completeness-proposals.md`, given an ID, surfaced in the terminal report, and never
converted into a task, dispatched, or quorum'd. The controller routes on `traces_to`, never
on the label the critic typed, and a label that disagrees with its `traces_to` is an error
rather than a believed claim — **relabelling is the only route by which a proposal could
ever enter the fix loop.**

**Second named fault, and the one assertion that closes the whole scope-invention hole:**
a completeness proposal consumed as a decision. A question whose `blocks` list is empty is
refused admission. That single assertion is generic rather than special-cased, because every
legitimate quorum question blocks named work — a task id, a gate id, a planning artifact —
and a proposal blocks nothing: the branch is already finished. "Should we also handle X" has
no natural ceiling, and three brains asked whether an adjacent case is worth covering will
say yes, confidently, because yes is always defensible. It is the one question class where
the quorum has a systematic rather than a random bias.

**Why the freeze is not policed.** `_freeze_proposal` records; it does not forbid. The
forbidding is Task 1's: phase creation is a stage-06 transition, stage 06 has long closed by
stage 11, so there is no phase a new task could belong to and no transition that would make
one. The test asserts that directly.

- [ ] **Step 1: Write the template**

Create `plugins/superb/skills/pipeline-auto/templates/completeness-proposals.md`:

```markdown
<!-- pipeline-auto-completeness-proposals/v1 -->

# Completeness proposals (frozen)

Recorded for the user. Never converted into a task, never dispatched, never sent
to a quorum.

<!--
The reasoning belongs here so a future maintainer can defend the rule rather than
assert it.

The stage-11 critic classifies every item as SPEC-NOT-MET or MISSING-FROM-SPEC.

SPEC-NOT-MET is NOT a proposal. It means an approved requirement is unmet, so it
is a Critical finding and it enters the fix loop at the zero-open-findings bar.
It belongs in findings.md, not in this file.

MISSING-FROM-SPEC lands here. Every other quorum in this skill answers a question
that BLOCKS work, and the quorum exists to unblock, not to enlarge. "Should we
also handle X" has no natural ceiling: three brains asked whether an adjacent
case is worth covering will say yes, confidently, because yes is always
defensible. It is the one question class where the quorum has a systematic rather
than a random bias.

This is not merely forbidden, it is impossible. Phase creation is a stage-06
transition, and after stage 06 closes the phase set is immutable, so there is no
phase a new task could belong to. The state machine enforces it; the controller's
restraint is not load-bearing.

One `## CP-<n>` section per proposal, with Statement, Evidence, Traces to (always
`none`), and Status (always `Frozen`).
-->
```

- [ ] **Step 2: Write the failing tests**

```python
class CompletenessFreeze(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = new_run(self.stack)
        opened_gate(self.run_dir)

    SPEC_LINE = "docs/superpowers/specs/2026-09-14-pipeline-auto-design.md:517"

    def test_spec_not_met_is_a_blocking_critical_finding_not_a_proposal(self):
        recorded = pas.record_completeness(str(self.run_dir), items=[{
            "id": "F-201", "class": "SPEC-NOT-MET", "traces_to": self.SPEC_LINE,
            "statement": "The two critic classes reach one sink.",
            "evidence": "scripts/pipeline_auto_state.py:1401"}])
        self.assertEqual(recorded["blocking"], ["F-201"])
        self.assertEqual(recorded["frozen"], [])
        rows = {row["id"]: row for row in pas.open_findings(str(self.run_dir))}
        self.assertEqual(rows["F-201"]["severity"], "Critical")
        self.assertFalse((self.run_dir / "completeness-proposals.md").exists())

    def test_missing_from_spec_is_frozen_and_never_becomes_work(self):
        recorded = pas.record_completeness(str(self.run_dir), items=[{
            "id": "-", "class": "MISSING-FROM-SPEC", "traces_to": "none",
            "statement": "A sibling case for Windows lock fallback is uncovered.",
            "evidence": "scripts/pipeline_auto_state.py:980"}])
        self.assertEqual(recorded["blocking"], [])
        self.assertEqual([item["id"] for item in recorded["frozen"]], ["CP-001"])
        self.assertIn("CP-001",
                      (self.run_dir / "completeness-proposals.md").read_text(encoding="utf-8"))
        self.assertEqual(pas.open_findings(str(self.run_dir)), [])
        tracker = tracker_of(self.run_dir)
        self.assertEqual(len(tracker["tasks"]), 2)
        self.assertEqual([row["id"] for row in tracker["phases"]], ["P01", "P02"])

    def test_a_frozen_proposal_cannot_become_a_phase(self):
        # THE FREEZE IS STRUCTURAL. Even a controller that has decided to act on
        # the proposal has no transition available that creates work.
        pas.record_completeness(str(self.run_dir), items=[{
            "id": "-", "class": "MISSING-FROM-SPEC", "traces_to": "none",
            "statement": "A sibling case is uncovered.", "evidence": "-"}])
        with self.assertRaises(pas.PhaseSetFrozen):
            pas.create_phase(str(self.run_dir), phase_id="P10", review_class="required")

    def test_relabelling_cannot_smuggle_a_proposal_into_the_fix_loop(self):
        # THE COLLAPSED-CLASSES SEED. Routing on the label rather than on
        # traces_to lets the critic promote a proposal to a finding by typing a
        # different word.
        with self.assertRaises(pas.GateError):
            pas.classify_completeness_item({"id": "F-202", "class": "SPEC-NOT-MET",
                                            "traces_to": "none", "statement": "x"})

    def test_a_proposal_citing_a_spec_line_is_a_finding_not_a_proposal(self):
        with self.assertRaises(pas.GateError):
            pas.classify_completeness_item({"id": "-", "class": "MISSING-FROM-SPEC",
                                            "traces_to": self.SPEC_LINE, "statement": "x"})

    def test_an_unknown_class_and_a_missing_trace_are_both_errors(self):
        for item in ({"class": "NICE-TO-HAVE", "traces_to": "none", "statement": "x"},
                     {"class": "SPEC-NOT-MET", "traces_to": "", "statement": "x"}):
            with self.subTest(item=item), self.assertRaises(pas.GateError):
                pas.classify_completeness_item(item)

    def test_proposals_are_numbered_and_accumulate(self):
        for statement in ("first", "second", "third"):
            pas.record_completeness(str(self.run_dir), items=[{
                "id": "-", "class": "MISSING-FROM-SPEC", "traces_to": "none",
                "statement": statement, "evidence": "-"}])
        self.assertEqual([item["id"] for item in pas.completeness_proposals(str(self.run_dir))],
                         ["CP-001", "CP-002", "CP-003"])


class ProposalIsNotADecision(unittest.TestCase):
    """One generic assertion closes the whole scope-invention hole.

    Every legitimate quorum question blocks named work — a task id, a gate id, a
    planning artifact. A completeness proposal blocks nothing, because the branch
    is already finished. So the admissibility rule that a question must block
    named work is, by itself, the rule that a proposal can never be decided.
    """

    def record(self, blocks):
        return {"question": "Should the run also cover the Windows lock fallback?",
                "axis": "new", "phase": "P02", "blocks": list(blocks),
                "raiser": "critic", "options_supplied": True,
                "options": [{"key": "yes"}, {"key": "no"}],
                "candidate_answers": [], "recommendation": "-",
                "reading_roots": {"repo": "."},
                "owners": ["brain-7", "brain-8", "brain-9"]}

    def test_a_question_blocking_nothing_is_refused_admission(self):
        problems = pas.check_admissible(self.record([]))
        self.assertTrue(problems)
        self.assertTrue(any("block" in problem.lower() for problem in problems))

    def test_a_question_blocking_named_work_is_admissible(self):
        self.assertEqual(pas.check_admissible(self.record(["P02-T01"])), [])

    def test_open_quorum_refuses_it_and_dispatches_nothing(self):
        with contextlib.ExitStack() as stack:
            _root, run_dir = new_run(stack)
            path = run_dir / "scratch" / "proposal-question.json"
            path.write_text(json.dumps(self.record([])), encoding="utf-8")
            with self.assertRaises(pas.QuorumError):
                pas.open_quorum(str(run_dir), question_record=str(path))
            self.assertFalse((run_dir / "quorum").exists())
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k CompletenessFreeze -k ProposalIsNotADecision`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'record_completeness'`

- [ ] **Step 4: Write the implementation**

```python
CRITIC_CLASSES = ("SPEC-NOT-MET", "MISSING-FROM-SPEC")
PROPOSALS_MARKER = "<!-- pipeline-auto-completeness-proposals/v1 -->"


def classify_completeness_item(item: dict) -> str:
    """Route on `traces_to`, never on the label the critic typed.

    SPEC-NOT-MET is not a proposal: it means an APPROVED requirement is unmet, so
    it must name the spec line it fails to meet, and it blocks. MISSING-FROM-SPEC
    traces to nothing by definition and is frozen. Relabelling is the only route
    by which a proposal could ever enter the fix loop, so a label that disagrees
    with its trace is an error rather than a believed claim.
    """
    label = item.get("class")
    if label not in CRITIC_CLASSES:
        raise GateError(
            f"a completeness item is SPEC-NOT-MET or MISSING-FROM-SPEC, not {label!r}")
    trace = str(item.get("traces_to", "")).strip()
    if not trace:
        raise GateError("every completeness item states traces_to: <spec-path>.md:<line> "
                        "or the literal none")
    if label == "SPEC-NOT-MET":
        if trace == "none" or not _SPEC_TRACE.fullmatch(trace):
            raise GateError(
                "SPEC-NOT-MET means an approved requirement is unmet, so it must name the "
                "spec line it fails to meet; an item tracing to nothing is a proposal "
                "wearing a finding's label")
        return "SPEC-NOT-MET"
    if trace != "none":
        raise GateError(
            "MISSING-FROM-SPEC traces to nothing by definition; an item citing a spec "
            "line is SPEC-NOT-MET and blocks")
    return "MISSING-FROM-SPEC"


def completeness_proposals(run_dir: str) -> list[dict]:
    path = Path(run_dir) / "completeness-proposals.md"
    if not path.exists():
        return []
    proposals, current = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## CP-"):
            current = {"id": line[3:].strip()}
            proposals.append(current)
        elif current is not None and line.startswith("- **Statement:**"):
            current["statement"] = line.split(":**", 1)[1].strip()
    return proposals


def _freeze_proposal(run_dir: Path, item: dict) -> dict:
    """Record a MISSING-FROM-SPEC item. Records; does not forbid.

    The forbidding is `create_phase`'s: phase creation is a stage-06 transition
    and stage 06 closed long before stage 11, so there is no phase a new task
    could belong to and no transition that would make one. Nothing here needs to
    police anything.
    """
    path = run_dir / "completeness-proposals.md"
    if not path.exists():
        path.write_text(
            f"{PROPOSALS_MARKER}\n\n# Completeness proposals (frozen)\n\n"
            "Recorded for the user. Never converted into a task, never dispatched,\n"
            "never sent to a quorum. Every other quorum in this run answered a question\n"
            "that BLOCKED work; the quorum exists to unblock, not to enlarge.\n\n",
            encoding="utf-8")
    proposal_id = f"CP-{len(completeness_proposals(str(run_dir))) + 1:03d}"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"## {proposal_id}\n\n"
                     f"- **Statement:** {item['statement']}\n"
                     f"- **Evidence:** {item.get('evidence', '-')}\n"
                     f"- **Traces to:** none\n"
                     f"- **Status:** Frozen\n\n")
    return {"id": proposal_id, "statement": item["statement"]}


def record_completeness(run_dir: str, *, items: list) -> dict:
    """Split the critic's output into its two sinks and write each."""
    directory = Path(run_dir)
    blocking, frozen = [], []
    for item in items:
        if classify_completeness_item(item) == "SPEC-NOT-MET":
            upsert_finding(str(directory), {
                "id": item["id"], "scope": item.get("scope", MASTER_GATE_ID),
                "severity": "Critical", "status": "open",
                "evidence": item["traces_to"]})
            blocking.append(item["id"])
        else:
            frozen.append(_freeze_proposal(directory, item))
    gate_dir = directory / "gate-master"
    gate_dir.mkdir(exist_ok=True)
    (gate_dir / "completeness.json").write_text(
        _dumps({"blocking": blocking, "frozen": [item["id"] for item in frozen]}),
        encoding="utf-8")
    return {"blocking": blocking, "frozen": frozen}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k CompletenessFreeze -k ProposalIsNotADecision`
Expected: PASS (10 tests)

- [ ] **Step 6: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): freeze completeness proposals and block spec-not-met"
```

---
### Task 9: Evidence-derived master-gate acceptance

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `assert_phase_set_intact`, `parse_master_report`, `open_findings`, `_challenge_ledger`, `_stage_row`, `MASTER_GATE_ID`, P02's `locked_tracker_update`, `_load_json`
- Produces: `evaluate_master_gate(run_dir) -> dict`

**Named fault this task catches:** acceptance supplied rather than derived. A caller's
`accepted=True`, an empty open-findings list handed in as an argument, or a reviewer
silently omitting an earlier finding proves nothing — the function takes no verdict, reads
the files, and returns its own. The second fault is a gate that closes with an open Minor:
the bar here is the same zero-open-findings bar as a task gate, because a gate that can
defer while task gates cannot is incoherent. The only exception is a finding already
recorded `REFUTED — governed by <D-ID>`, and it needs no special case because that finding's
status is `resolved`.

- [ ] **Step 1: Write the failing tests**

```python
class MasterGateAcceptance(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = new_run(self.stack)
        opened_gate(self.run_dir)

    def both_clean_reports(self):
        publish_report(self.run_dir, assignment="master-A", reviewer="reviewer-a")
        publish_report(self.run_dir, assignment="master-B", reviewer="reviewer-b")

    def test_acceptance_cannot_be_supplied(self):
        with self.assertRaises(TypeError):
            pas.evaluate_master_gate(str(self.run_dir), accepted=True)

    def test_one_report_is_not_a_two_reviewer_gate(self):
        publish_report(self.run_dir, assignment="master-A", reviewer="reviewer-a")
        pass_master_verification(self.run_dir)
        result = pas.evaluate_master_gate(str(self.run_dir))
        self.assertFalse(result["accepted"])
        self.assertIn("master-B has not reported", result["blockers"])

    def test_missing_verification_blocks(self):
        self.both_clean_reports()
        result = pas.evaluate_master_gate(str(self.run_dir))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("verification" in blocker for blocker in result["blockers"]))

    def test_verification_at_a_different_head_blocks(self):
        self.both_clean_reports()
        pass_master_verification(self.run_dir, head="9" * 40)
        self.assertFalse(pas.evaluate_master_gate(str(self.run_dir))["accepted"])

    def test_an_open_minor_blocks_exactly_like_a_critical(self):
        self.both_clean_reports()
        pass_master_verification(self.run_dir)
        pas.upsert_finding(str(self.run_dir), {"id": "F-110", "scope": "gate-master",
                                               "severity": "Minor", "status": "open"})
        result = pas.evaluate_master_gate(str(self.run_dir))
        self.assertFalse(result["accepted"])
        self.assertIn("F-110 is open (Minor)", result["blockers"])

    def test_a_refuted_governed_finding_does_not_block(self):
        self.both_clean_reports()
        pass_master_verification(self.run_dir)
        pas.upsert_finding(str(self.run_dir), {
            "id": "F-110", "scope": "gate-master", "severity": "Minor",
            "status": "resolved",
            "disposition": "REFUTED — governed by Q-7c6b5a4938d2"})
        self.assertTrue(pas.evaluate_master_gate(str(self.run_dir))["accepted"])

    def test_a_queued_escalation_blocks(self):
        self.both_clean_reports()
        pass_master_verification(self.run_dir)
        pas.record_challenge(str(self.run_dir), challenge={
            "kind": "DECISION-CHALLENGE", "decision_id": "H-001", "reviewer": "reviewer-a",
            "evidence": "x:1", "consequence": "It drops contended transitions."})
        result = pas.evaluate_master_gate(str(self.run_dir))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("escalation" in blocker for blocker in result["blockers"]))
        self.assertTrue(any("challenge to H-001" in blocker for blocker in result["blockers"]))

    def test_a_moved_phase_set_is_a_stop_not_a_blocker(self):
        self.both_clean_reports()
        pass_master_verification(self.run_dir)
        seal_phase_set(self.run_dir, ["P01"])
        with self.assertRaises(pas.PhaseSetFrozen):
            pas.evaluate_master_gate(str(self.run_dir))

    def test_a_clean_gate_accepts_and_opens_stage_12(self):
        self.both_clean_reports()
        pass_master_verification(self.run_dir)
        result = pas.evaluate_master_gate(str(self.run_dir))
        self.assertEqual(result, {"accepted": True, "blockers": []})
        tracker = tracker_of(self.run_dir)
        gate = next(row for row in tracker["gates"] if row["id"] == pas.MASTER_GATE_ID)
        self.assertEqual(gate["state"], "accepted")
        self.assertEqual(pas._stage_row(tracker, "11")["stage_state"], "complete")
        self.assertEqual(pas._stage_row(tracker, "12")["stage_state"], "active")
        self.assertEqual(pas.derive_next_action(tracker), "record-final-verification")

    def test_evaluation_is_replay_inert(self):
        self.both_clean_reports()
        pass_master_verification(self.run_dir)
        pas.evaluate_master_gate(str(self.run_dir))
        snapshot = (self.run_dir / "progress.md").read_bytes()
        self.assertTrue(pas.evaluate_master_gate(str(self.run_dir))["accepted"])
        self.assertEqual((self.run_dir / "progress.md").read_bytes(), snapshot)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k MasterGateAcceptance`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'evaluate_master_gate'`

- [ ] **Step 3: Write the implementation**

```python
def evaluate_master_gate(run_dir: str) -> dict:
    """Derive master-gate acceptance from the recorded evidence.

    There is no `accepted` parameter. A caller's assertion, an empty
    open-findings list handed in as an argument, or a reviewer silently omitting
    an earlier finding proves nothing; a caller who can assert acceptance IS the
    gate. The bar is zero open findings at every severity — the same bar a task
    gate applies, because a master gate that can defer while task gates cannot is
    incoherent.

    Each report is validated against the edge IT was written against, and then
    separately required to cover the gate's CURRENT edge. Those are two different
    checks and collapsing them loses one of the two guarantees: validating
    against the current head would reject a correctly sealed report after the
    first fix round, and accepting a report bound to an older head would close
    the gate over code nobody reviewed.
    """
    directory = Path(run_dir)
    tracker = parse_tracker((directory / "progress.md").read_text(encoding="utf-8"))
    assert_phase_set_intact(str(directory), tracker)
    sealed = _load_json(directory / "gate-master" / "assignments.json")

    gate = _gate_row(tracker)
    bindings_path = directory / "gate-master" / "report-bindings.json"
    bindings = _load_json(bindings_path) if bindings_path.exists() else {}

    blockers = []
    for assignment in sorted(sealed["assignments"]):
        binding = bindings.get(assignment)
        if binding is None:
            blockers.append(f"{assignment} has not reported")
            continue
        block = parse_master_report((directory / binding["path"]).read_text(encoding="utf-8"))
        # Checked against the head it was WRITTEN against, never the current one.
        # A sealed report keeps its own edge forever; the gate's head moves past
        # it through fix rounds, and that is exactly how a stale report is
        # recognised rather than quietly re-used.
        if (block["base"], block["head"]) != (binding["base"], binding["head"]):
            blockers.append(f"{assignment}'s sealed report no longer matches its binding")
        elif binding["head"] != gate["head"]:
            blockers.append(f"{assignment} has not re-reviewed the current edge")

    for row in open_findings(str(directory)):
        blockers.append(f"{row['id']} is open ({row['severity']})")

    for row in tracker["escalations"]:
        if row["state"] in ("queued", "asked"):
            blockers.append(f"escalation {row['id']} is unresolved")

    for entry in _challenge_ledger(directory):
        if entry["route"] in ("halt-escalation", "halt-second-challenge"):
            blockers.append(f"challenge to {entry['decision_id']} halted the gate")

    verification = directory / "gate-master" / "verification.json"
    if not verification.exists():
        blockers.append("no digest-bound master verification record")
    else:
        record = _load_json(verification)
        if record.get("head") != gate["head"] or record.get("outcome") != "PASS":
            blockers.append("master verification does not PASS at the reviewed head")

    if blockers:
        return {"accepted": False, "blockers": blockers}

    def mutate(updated):
        gate = _gate_row(updated)
        gate["state"] = "accepted"
        gate["reports"] = ",".join(bindings[name]["path"]
                                   for name in sorted(sealed["assignments"]))
        gate["verification"] = "gate-master/verification.json"
        eleven = _stage_row(updated, "11")
        eleven["stage_state"] = "complete"
        eleven["next_action"] = "-"
        twelve = _stage_row(updated, "12")
        twelve["stage_state"] = "active"
        twelve["next_action"] = "record-final-verification"
        return updated

    locked_tracker_update(str(directory), transition_id="accept-master-gate", mutate=mutate)
    return {"accepted": True, "blockers": []}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k MasterGateAcceptance`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): derive master-gate acceptance from evidence alone"
```

---

### Task 10: The master-gate fix loop, bounded at three rounds

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `MASTER_GATE_ID`, `_queue_escalation`, `open_findings`, `GateError`, P02's `parse_tracker`, `locked_tracker_update`, `append_row`, `_csv`
- Produces: `MAX_GATE_FIX_ROUNDS`, `GATE_HALTS`, `gate_fix_rounds(run_dir) -> list[dict]`, `open_gate_fix_round(run_dir, *, fixer, findings) -> dict`, `record_gate_fix_round(run_dir, *, round_number, fixer, commits, verification, re_review, remaining) -> dict`

**Why this task exists.** The master plan's cross-phase clarifications settle what this plan
originally refused to invent: stage 11 **does** re-review after a fix round, bounded at the
same cap of three that applies at task scope. The entailment is short — the inlined SDD
protocol gives a final review that returns findings one fix subagent carrying the complete
list, then re-runs the review on the updated package and finishes when a round returns zero;
the recorded default extends zero-open-findings to the master gate; so a gate that could not
re-review would be a gate that can never close after its first finding, which makes
`SPEC-NOT-MET` unfixable by construction.

**Named fault this task catches:** a fourth round. The cap is not advisory — a fourth round
**halts to the escalation queue** and dispatches nobody, because a gate still blocked after
three rounds has a problem no further round will solve, and looping produces commits,
renamed findings and a claim of improvement rather than progress.

**Second named fault, and the one a counter alone misses: oscillation.** A round that
re-opens a finding an earlier round resolved halts immediately, with rounds still on the
clock. A counter cannot see it: rounds 1, 2 and 3 can each "resolve" a finding and each
re-break the one before it, staying inside the cap forever while converging on nothing. The
same immediate halt covers a round that resolves **none** of its targeted findings — and
neither halt consumes the remaining rounds, because the budget is not the thing that ran out.

**Third named fault: the gate's head not advancing.** The inlined SDD protocol re-runs the
final review on *the updated package*. A gate whose head stayed at the initial edge would
re-review code that does not contain the fixes, so the same findings return every round and
the three-round cap fires on **every** gate that ever produced a finding — a loop that
cannot succeed rather than a conservative one. `record_gate_fix_round` therefore advances
`gate.head` to the fix commit.

**Fourth named fault, and its exact opposite: a sealed report rebound to the new head.** The
gate advances; the evidence does not. Task 4 binds each report to the edge it was written
against and Task 9 checks it there, so after a round the round-1 reports still validate
against their own head **and** are correctly not treated as covering the round-2 edge. A
test that only checks the head moved passes against an implementation that rebinds every
report to it, silently claiming a reviewer saw code they never read — which is why the test
below asserts both halves.

**Scope note.** P06 owns the gate-scope loop end-to-end rather than calling P05's
`open_fix_round`, which is shaped for a task scope and a per-task review row. The `## Fix
Rounds` grammar is shared and P02 validates it for both.

**One grammar consequence worth stating,** because it looks like a bug and is not: P02
rejects a scope whose **last** round is `complete` with `Remaining` other than `none`. So a
round closing with findings still open closes and opens its successor as `pending` in the
**same** transition, and a **halted** round is left `re_reviewing` rather than `complete` —
which is also what it truthfully is. A halted round therefore records no `Remaining`; the
still-open findings are in `findings.md` and the block is the escalation row.

**Why that is one transition and not two.** Closing the round and opening its successor in
separate `locked_tracker_update` calls leaves the tracker *invalid* in between — last round
`complete`, `Remaining` non-empty — so an interruption between the two writes strands the
run in a state its own validator rejects, recoverable only by hand. This is precisely the
class of bug the single-locked-transition discipline exists to prevent: a transition is the
unit at which state is legal, and any change that needs two writes to stay legal is one
write.

- [ ] **Step 1: Write the failing tests**

```python
class MasterGateFixRounds(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = new_run(self.stack)
        opened_gate(self.run_dir)
        publish_report(self.run_dir, assignment="master-A", reviewer="reviewer-a")
        publish_report(self.run_dir, assignment="master-B", reviewer="reviewer-b")
        pass_master_verification(self.run_dir)

    FIXES = ("7" * 40, "8" * 40, "9" * 40)

    def cycle(self, number, targeted, remaining, fixer="fixer-9"):
        opened = pas.open_gate_fix_round(str(self.run_dir), fixer=fixer,
                                         findings=list(targeted))
        if opened["halted"]:
            return opened
        return pas.record_gate_fix_round(
            str(self.run_dir), round_number=opened["round"], fixer=fixer,
            commits=self.FIXES[number - 1],
            verification="scratch/gate-fix-tests.txt",
            re_review="scratch/gate-re-review.md", remaining=list(remaining))

    def bindings(self):
        return json.loads((self.run_dir / "gate-master" / "report-bindings.json")
                          .read_text(encoding="utf-8"))

    def gate_head(self):
        return next(row for row in tracker_of(self.run_dir)["gates"]
                    if row["id"] == pas.MASTER_GATE_ID)["head"]

    def re_review_at(self, head):
        publish_report(self.run_dir, assignment="master-A", reviewer="reviewer-a", head=head)
        publish_report(self.run_dir, assignment="master-B", reviewer="reviewer-b", head=head)
        pass_master_verification(self.run_dir, head=head)

    def queued(self):
        return [row for row in tracker_of(self.run_dir)["escalations"]
                if row["state"] == "queued"]

    def test_a_round_returning_zero_closes_the_loop_and_lets_the_gate_accept(self):
        pas.upsert_finding(str(self.run_dir), {"id": "F-101", "scope": "gate-master",
                                               "severity": "Critical", "status": "open"})
        self.cycle(1, ["F-101"], [])
        pas.upsert_finding(str(self.run_dir), {"id": "F-101", "status": "resolved",
                                               "disposition": "Fixed"})
        self.assertEqual([row["state"] for row in pas.gate_fix_rounds(str(self.run_dir))],
                         ["complete"])
        self.re_review_at(self.FIXES[0])
        self.assertTrue(pas.evaluate_master_gate(str(self.run_dir))["accepted"])

    def test_the_gate_head_advances_to_the_fix_commit(self):
        # Without this the re-review reads code that does not contain the fixes,
        # the same findings return every round, and the three-round cap fires on
        # every gate that ever produced a finding.
        self.assertEqual(self.gate_head(), HEAD)
        self.cycle(1, ["F-101"], [])
        self.assertEqual(self.gate_head(), self.FIXES[0])

    def test_a_sealed_report_keeps_its_own_head_and_does_not_cover_a_later_one(self):
        # THE REBINDING SEED. A test that only checks the head moved passes
        # against an implementation that rebinds every report to it, silently
        # claiming a reviewer saw code they never read. Both halves are asserted.
        self.assertEqual(self.bindings()["master-A"]["head"], HEAD)
        pas.upsert_finding(str(self.run_dir), {"id": "F-101", "scope": "gate-master",
                                               "severity": "Critical", "status": "open"})
        self.cycle(1, ["F-101"], [])
        pas.upsert_finding(str(self.run_dir), {"id": "F-101", "status": "resolved",
                                               "disposition": "Fixed"})

        self.assertEqual(self.gate_head(), self.FIXES[0])          # the gate advanced
        binding = self.bindings()["master-A"]
        self.assertEqual(binding["head"], HEAD)                    # the evidence did not
        sealed = (self.run_dir / binding["path"]).read_text(encoding="utf-8")
        self.assertEqual(pas.parse_master_report(sealed)["head"], HEAD)

        pass_master_verification(self.run_dir, head=self.FIXES[0])
        result = pas.evaluate_master_gate(str(self.run_dir))
        self.assertFalse(result["accepted"])
        self.assertIn("master-A has not re-reviewed the current edge", result["blockers"])
        self.assertIn("master-B has not re-reviewed the current edge", result["blockers"])

        self.re_review_at(self.FIXES[0])
        self.assertTrue(pas.evaluate_master_gate(str(self.run_dir))["accepted"])
        self.assertEqual(self.bindings()["master-A"]["head"], self.FIXES[0])
        # the round-1 report is still on disk, still bound to its own edge
        self.assertTrue((self.run_dir / binding["path"]).exists())

    def test_three_rounds_are_allowed_and_the_fourth_halts(self):
        # THE UNBOUNDED-LOOP SEED. A gate still blocked after three rounds has a
        # problem no fourth round solves; commits and renamed findings are not
        # progress.
        self.cycle(1, ["F-101", "F-102", "F-103"], ["F-102", "F-103"])
        self.cycle(2, ["F-102", "F-103"], ["F-103"])
        self.cycle(3, ["F-103", "F-104"], ["F-104"])
        self.assertEqual(len(pas.gate_fix_rounds(str(self.run_dir))), 4)
        fourth = pas.open_gate_fix_round(str(self.run_dir), fixer="fixer-9",
                                         findings=["F-104"])
        self.assertTrue(fourth["halted"])
        self.assertEqual(fourth["reason"], "round-cap")
        self.assertFalse(fourth["dispatch"])
        self.assertEqual(len(self.queued()), 1)

    def test_a_halted_round_dispatches_no_reviewer_and_blocks_the_gate(self):
        self.cycle(1, ["F-101", "F-102", "F-103"], ["F-102", "F-103"])
        self.cycle(2, ["F-102", "F-103"], ["F-103"])
        self.cycle(3, ["F-103", "F-104"], ["F-104"])
        before = sorted(path.name for path in
                        (self.run_dir / "gate-master" / "reports").iterdir())
        pas.open_gate_fix_round(str(self.run_dir), fixer="fixer-9", findings=["F-104"])
        after = sorted(path.name for path in
                       (self.run_dir / "gate-master" / "reports").iterdir())
        self.assertEqual(before, after)
        pas.upsert_finding(str(self.run_dir), {"id": "F-104", "scope": "gate-master",
                                               "severity": "Important", "status": "open"})
        result = pas.evaluate_master_gate(str(self.run_dir))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("escalation" in blocker for blocker in result["blockers"]))

    def test_a_round_resolving_none_halts_immediately_with_rounds_to_spare(self):
        halted = self.cycle(1, ["F-101", "F-102"], ["F-101", "F-102"])
        self.assertTrue(halted["halted"])
        self.assertEqual(halted["reason"], "no-progress")
        self.assertEqual(len(self.queued()), 1)
        self.assertEqual([row["state"] for row in pas.gate_fix_rounds(str(self.run_dir))],
                         ["re_reviewing"])

    def test_oscillation_halts_even_though_the_counter_has_room(self):
        # THE OSCILLATION SEED. Rounds 1, 2 and 3 can each resolve a finding and
        # each re-break the one before it, staying inside the cap forever while
        # converging on nothing. A counter cannot see this; only the history can.
        self.cycle(1, ["F-101", "F-102"], ["F-102"])          # F-101 resolved
        reopened = pas.open_gate_fix_round(str(self.run_dir), fixer="fixer-9",
                                           findings=["F-101", "F-102"])
        self.assertTrue(reopened["halted"])
        self.assertEqual(reopened["reason"], "oscillation")
        self.assertFalse(reopened["dispatch"])
        self.assertEqual(len(self.queued()), 1)
        self.assertLess(len([row for row in pas.gate_fix_rounds(str(self.run_dir))
                             if row["state"] == "complete"]), pas.MAX_GATE_FIX_ROUNDS)

    def test_opening_twice_returns_the_active_round_rather_than_a_second_one(self):
        first = pas.open_gate_fix_round(str(self.run_dir), fixer="fixer-9",
                                        findings=["F-101"])
        second = pas.open_gate_fix_round(str(self.run_dir), fixer="fixer-9",
                                         findings=["F-101"])
        self.assertEqual(first["round"], second["round"])
        self.assertEqual(len(pas.gate_fix_rounds(str(self.run_dir))), 1)

    def test_closing_an_unopened_round_is_an_error(self):
        with self.assertRaises(pas.GateError):
            pas.record_gate_fix_round(str(self.run_dir), round_number=1, fixer="fixer-9",
                                      commits="6" * 40, verification="v.txt",
                                      re_review="r.md", remaining=[])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k MasterGateFixRounds`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'open_gate_fix_round'`

- [ ] **Step 3: Write the implementation**

```python
MAX_GATE_FIX_ROUNDS = 3
GATE_HALTS = ("round-cap", "no-progress", "oscillation")


def gate_fix_rounds(run_dir: str) -> list[dict]:
    """`## Fix Rounds` rows scoped to the master gate, in round order."""
    tracker = parse_tracker((Path(run_dir) / "progress.md").read_text(encoding="utf-8"))
    return sorted((row for row in tracker["fix_rounds"] if row["scope"] == MASTER_GATE_ID),
                  key=lambda row: int(row["round"]))


def _remaining_of(row: dict) -> list[str]:
    if row["remaining"] in ("-", "none"):
        return []
    return _csv(row["remaining"])


def _resolved_so_far(rounds: list) -> set:
    """Findings some completed round targeted and did not leave remaining."""
    resolved = set()
    for row in rounds:
        if row["state"] != "complete":
            continue
        resolved |= set(_csv(row["findings"])) - set(_remaining_of(row))
    return resolved


def _halt(run_dir: str, reason: str, round_number) -> dict:
    _queue_escalation(run_dir, blast="run", reason=f"master-gate-{reason}")
    return {"round": round_number, "halted": True, "reason": reason, "dispatch": False}


def open_gate_fix_round(run_dir: str, *, fixer: str, findings: list) -> dict:
    """Start the next master-gate fix round, or halt.

    One fixer per round carrying all findings. Two halts are decided here:
    the cap, and oscillation — a round re-opening a finding an earlier round
    resolved. Oscillation halts with rounds still on the clock, because the
    budget is not the thing that ran out; three rounds that each resolve a
    finding and re-break the previous one stay inside the cap forever while
    converging on nothing, and a counter cannot see it.
    """
    directory = Path(run_dir)
    rounds = gate_fix_rounds(str(directory))
    active = [row for row in rounds if row["state"] in ("fixing", "re_reviewing")]
    if active:
        return {"round": int(active[0]["round"]), "halted": False,
                "reason": "-", "dispatch": True}

    reopened = _resolved_so_far(rounds) & set(findings)
    if reopened:
        return _halt(str(directory), "oscillation", None)
    complete = [row for row in rounds if row["state"] == "complete"]
    if len(complete) >= MAX_GATE_FIX_ROUNDS:
        return _halt(str(directory), "round-cap", None)

    number = len(complete) + 1

    def mutate(tracker):
        row = next((entry for entry in tracker["fix_rounds"]
                    if entry["scope"] == MASTER_GATE_ID
                    and entry["round"] == str(number)), None)
        values = {"state": "fixing", "fixer": fixer, "findings": ",".join(findings),
                  "commits": "-", "verification": "-", "re_review": "-", "remaining": "-"}
        if row is not None:
            row.update(values)
            return tracker
        return append_row(tracker, "fix_rounds",
                          {"scope": MASTER_GATE_ID, "round": str(number), **values})

    locked_tracker_update(str(directory), transition_id=f"gate-fix-open-{number}",
                          mutate=mutate)
    return {"round": number, "halted": False, "reason": "-", "dispatch": True}


def record_gate_fix_round(run_dir: str, *, round_number: int, fixer: str, commits: str,
                          verification: str, re_review: str, remaining: list) -> dict:
    """Close one master-gate fix round and open its successor, or halt.

    A round that resolved NONE of its targeted findings halts immediately and
    leaves the remaining rounds unspent: commits, renamed findings, and a claimed
    improvement are not progress, and spending two more rounds on them would
    escalate the run for the wrong reason three rounds later.

    A round closing with findings still open opens its successor in the SAME
    transition, because P02 rejects a scope whose last round is `complete` with
    a `Remaining` other than `none`; doing it in two writes would leave the
    tracker invalid in between, strandable by any interruption. A halted round
    stays `re_reviewing`, which is also what it truthfully is.

    A completing round also advances `gate.head` to its fix commit, because the
    re-review must read the updated package. Sealed reports are NOT moved with
    it: each stays bound to the edge it was written against, and `evaluate_master_gate`
    is what notices that a report bound to an older head no longer covers the gate.
    """
    directory = Path(run_dir)
    rounds = gate_fix_rounds(str(directory))
    row = next((entry for entry in rounds if entry["round"] == str(round_number)), None)
    if row is None or row["state"] not in ("fixing", "re_reviewing"):
        raise GateError(f"the master gate has no open fix round {round_number}")

    targeted = _csv(row["findings"])
    remaining = list(remaining)
    stalled = bool(remaining) and set(remaining) == set(targeted)

    def mutate(tracker):
        entry = next(item for item in tracker["fix_rounds"]
                     if item["scope"] == MASTER_GATE_ID
                     and item["round"] == str(round_number))
        entry.update({"fixer": fixer, "commits": commits, "verification": verification,
                      "re_review": re_review})
        if stalled:
            entry["state"] = "re_reviewing"
            entry["remaining"] = "-"
            return tracker
        entry["state"] = "complete"
        entry["remaining"] = ",".join(remaining) if remaining else "none"
        # The gate advances to the fix commit; the sealed reports do not move.
        _gate_row(tracker)["head"] = commits
        if remaining:
            tracker = append_row(tracker, "fix_rounds", {
                "scope": MASTER_GATE_ID, "round": str(round_number + 1),
                "state": "pending", "fixer": "-", "findings": "-", "commits": "-",
                "verification": "-", "re_review": "-", "remaining": "-"})
        return tracker

    locked_tracker_update(str(directory), transition_id=f"gate-fix-close-{round_number}",
                          mutate=mutate)
    if stalled:
        return _halt(str(directory), "no-progress", round_number)
    return {"round": round_number, "halted": False, "reason": "-",
            "dispatch": bool(remaining), "remaining": remaining,
            "next_round": round_number + 1 if remaining else None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k MasterGateFixRounds`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): bound the master-gate fix loop and halt on oscillation"
```

---

### Task 11: Final verification — the run-wide suite, and the two commands that must print nothing

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `MASTER_GATE_ID`, `_stage_row`, `completeness_proposals`, P02's `repo_root`, `derive_next_action`, `publish_immutable`, `locked_tracker_update`
- Produces: `FINAL_SUITE_SILENT`, `final_suite_commands(base_commit, project_root) -> tuple[tuple[str, ...], ...]`, `record_final_verification(run_dir, *, results) -> dict`, `derive_terminal_action(run_dir) -> str`

**The run-wide suite, copied from the master plan's "Verification suite" section:**

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
python3 plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py
git -C . diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

**Named fault this task catches:** the third and fourth commands passing on exit code alone.
Both exit `0` when they print something — `git diff --name-only` exits 0 whether or not the
path changed, and `git status --short` exits 0 with a dirty tree. Checking only the exit
code means the run completes while `plugins/superb/skills/pipeline/` has been modified,
which is the single Global Constraint the whole rewrite exists to honour, and while the
working tree is dirty. Those two commands are verified on **stdout**, and the assertion is
that they printed **nothing**.

**Second named fault:** the git commands run against a different repository. They are bound
to the run's recorded project root through `repo_root(tracker)` and carry it as `git -C`, so
a clean status obtained somewhere else cannot supply the proof.

- [ ] **Step 1: Write the failing tests**

```python
class FinalVerification(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = new_run(self.stack)
        opened_gate(self.run_dir)
        publish_report(self.run_dir, assignment="master-A", reviewer="reviewer-a")
        publish_report(self.run_dir, assignment="master-B", reviewer="reviewer-b")
        pass_master_verification(self.run_dir)
        pas.evaluate_master_gate(str(self.run_dir))

    def test_the_suite_is_the_master_plans_four_commands_in_order(self):
        commands = pas.final_suite_commands(BASE, ".")
        self.assertEqual(len(commands), 4)
        self.assertEqual(commands[0], ("python3", "-m", "unittest", "discover", "-s",
                                       "plugins/superb/skills/pipeline-auto/tests", "-v"))
        self.assertEqual(commands[1], ("python3",
                                       "plugins/superb/skills/pipeline-auto/examples/"
                                       "controller_walkthrough.py"))
        self.assertEqual(commands[2], ("git", "-C", ".", "diff", "--name-only",
                                       f"{BASE}..HEAD", "--",
                                       "plugins/superb/skills/pipeline/"))
        self.assertEqual(commands[3], ("git", "-C", ".", "status", "--short"))
        self.assertEqual(pas.FINAL_SUITE_SILENT, (2, 3))

    def test_a_modified_pipeline_skill_fails_even_though_git_exits_zero(self):
        # THE SILENT-PASS SEED. `git diff --name-only` exits 0 whether or not the
        # path changed. Checking the exit code alone completes a run that
        # modified plugins/superb/skills/pipeline/.
        results = suite_results(self.run_dir,
                                third="plugins/superb/skills/pipeline/references/review.md")
        with self.assertRaises(pas.TrackerValidationError) as caught:
            pas.record_final_verification(str(self.run_dir), results=results)
        self.assertIn("review.md", str(caught.exception))

    def test_a_dirty_working_tree_fails_even_though_git_exits_zero(self):
        results = suite_results(self.run_dir, fourth="?? scratch/notes.md")
        with self.assertRaises(pas.TrackerValidationError):
            pas.record_final_verification(str(self.run_dir), results=results)

    def test_a_failing_suite_command_fails(self):
        results = suite_results(self.run_dir)
        results[0]["exit_code"] = 1
        with self.assertRaises(pas.TrackerValidationError):
            pas.record_final_verification(str(self.run_dir), results=results)

    def test_the_commands_must_be_the_exact_ordered_tuple(self):
        commands = pas.final_suite_commands(BASE, ".")
        for order in (tuple(reversed(commands)), commands[:3],
                      (("git", "-C", "/elsewhere", "status", "--short"),) + commands[:3]):
            with self.subTest(order=order), self.assertRaises(pas.TrackerValidationError):
                pas.record_final_verification(
                    str(self.run_dir), results=suite_results(self.run_dir, order=order))

    def test_final_verification_requires_an_accepted_master_gate(self):
        with contextlib.ExitStack() as stack:
            _root, fresh = new_run(stack)
            with self.assertRaises(pas.GateError):
                pas.record_final_verification(str(fresh), results=[])

    def test_a_clean_suite_closes_stage_12_and_derives_complete(self):
        record = pas.record_final_verification(str(self.run_dir),
                                               results=suite_results(self.run_dir))
        self.assertEqual(record["outcome"], "PASS")
        self.assertEqual(record["head"], HEAD)
        self.assertEqual(len(record["digest"]), 64)
        tracker = tracker_of(self.run_dir)
        self.assertEqual(pas._stage_row(tracker, "12")["stage_state"], "complete")
        self.assertEqual(pas.derive_next_action(tracker), "complete")
        self.assertEqual(pas.derive_terminal_action(str(self.run_dir)), "complete")

    def test_a_frozen_proposal_turns_completion_into_complete_with_proposals(self):
        pas.record_completeness(str(self.run_dir), items=[{
            "id": "-", "class": "MISSING-FROM-SPEC", "traces_to": "none",
            "statement": "A sibling case is uncovered.", "evidence": "-"}])
        pas.record_final_verification(str(self.run_dir), results=suite_results(self.run_dir))
        self.assertEqual(pas.derive_terminal_action(str(self.run_dir)),
                         "complete-with-proposals")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k FinalVerification`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'final_suite_commands'`

- [ ] **Step 3: Write the implementation**

```python
# Indices into the run-wide suite whose STDOUT must be empty. Both commands exit
# 0 when they print something: `git diff --name-only` exits 0 whether or not the
# path changed, and `git status --short` exits 0 with a dirty tree. Verifying
# them on exit code alone completes a run that modified
# plugins/superb/skills/pipeline/ — the one Global Constraint this whole rewrite
# exists to honour — or that left the working tree dirty.
FINAL_SUITE_SILENT = (2, 3)


def final_suite_commands(base_commit: str, project_root: str) -> tuple:
    """The master plan's run-wide suite, in its exact order.

    The git commands carry `-C <project_root>`, bound to the run's recorded root,
    so a clean status obtained in some other repository cannot supply the proof.
    """
    return (
        ("python3", "-m", "unittest", "discover", "-s",
         "plugins/superb/skills/pipeline-auto/tests", "-v"),
        ("python3",
         "plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py"),
        ("git", "-C", project_root, "diff", "--name-only", f"{base_commit}..HEAD", "--",
         "plugins/superb/skills/pipeline/"),
        ("git", "-C", project_root, "status", "--short"),
    )


def record_final_verification(run_dir: str, *, results: list) -> dict:
    """Stage 12. Record the run-wide suite against the accepted master HEAD."""
    directory = Path(run_dir)
    tracker = parse_tracker((directory / "progress.md").read_text(encoding="utf-8"))
    gate = next((row for row in tracker["gates"] if row["id"] == MASTER_GATE_ID), None)
    if gate is None or gate["state"] != "accepted":
        raise GateError("final verification follows an accepted master gate")
    expected = final_suite_commands(tracker["run"]["base_commit"], repo_root(tracker))
    actual = tuple(tuple(entry["command"]) for entry in results)
    if actual != expected:
        raise TrackerValidationError(
            "final verification runs the run-wide suite in its exact order and against "
            f"the run's own project root; expected {expected}, got {actual}")
    for index, entry in enumerate(results):
        printable = " ".join(entry["command"])
        if entry["exit_code"] != 0:
            raise TrackerValidationError(f"{printable} exited {entry['exit_code']}")
        if index in FINAL_SUITE_SILENT and entry["stdout"].strip():
            first = entry["stdout"].strip().splitlines()[0]
            raise TrackerValidationError(
                f"{printable} must print nothing and printed {first!r}")

    rendered = _dumps({"head": gate["head"], "outcome": "PASS", "results": results})
    digest = publish_immutable(
        str(directory / "gate-master" / "final-verification.json"), rendered)

    def mutate(updated):
        twelve = _stage_row(updated, "12")
        twelve["stage_state"] = "complete"
        twelve["next_action"] = "-"
        return updated

    locked_tracker_update(str(directory), transition_id="record-final-verification",
                          mutate=mutate)
    return {"digest": digest, "head": gate["head"], "outcome": "PASS"}


def derive_terminal_action(run_dir: str) -> str:
    """`complete`, or `complete-with-proposals` when the critic froze anything.

    Derived from files rather than stored, so the tracker never holds a second
    copy of a fact the proposals file already carries.
    """
    directory = Path(run_dir)
    tracker = parse_tracker((directory / "progress.md").read_text(encoding="utf-8"))
    action = derive_next_action(tracker)
    if action == "complete" and completeness_proposals(str(directory)):
        return "complete-with-proposals"
    return action
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k FinalVerification`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): verify the two silent commands on stdout, not exit code"
```

---

### Task 12: The terminal report, leading with what the user never approved

**Files:**
- Modify: `plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py`
- Modify: `plugins/superb/skills/pipeline-auto/tests/test_pipeline_auto_state.py`

**Interfaces:**
- Consumes: `_weakest_first`, `tainting_decisions`, `completeness_proposals`, `derive_terminal_action`, `_challenge_ledger`, P03's `parse_decisions` and `quorum_events`, P02's `publish_immutable`
- Produces: `TERMINAL_REPORT_HEADING`, `render_terminal_report(run_dir) -> str`, `publish_terminal_report(run_dir) -> str`

**Named fault this task catches:** a provenance field read only by a validator. The run can
record `Provenance: quorum` on every machine decision, validate it on every write, and still
hand the user a report in which those decisions are indistinguishable from the ones they
made themselves. The report therefore **opens** with them, under a heading that says plainly
they were decided without the user, sorted by grounding rung **ascending** — weakest first,
because the answer the run was least sure of is the one most likely to be wrong and least
likely to be noticed.

The test asserts the lowest-rung decision appears in the report's **first** table, not merely
somewhere in the document. A report that buries the weakest decision under four sections has
the field and not the effect.

- [ ] **Step 1: Write the failing tests**

```python
class TerminalReport(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        _root, self.run_dir = new_run(self.stack)
        opened_gate(self.run_dir)
        publish_report(self.run_dir, assignment="master-A", reviewer="reviewer-a")
        publish_report(self.run_dir, assignment="master-B", reviewer="reviewer-b")
        pass_master_verification(self.run_dir)
        pas.evaluate_master_gate(str(self.run_dir))
        pas.record_final_verification(str(self.run_dir), results=suite_results(self.run_dir))

    def first_table(self, text: str) -> list[str]:
        """The rows of the report's first pipe table, in order."""
        rows, seen_header = [], False
        for line in text.splitlines():
            if line.startswith("|"):
                seen_header = True
                if not line.startswith("| ---"):
                    rows.append(line)
            elif seen_header:
                break
        return rows

    def test_the_report_opens_with_the_decisions_made_without_the_user(self):
        text = pas.render_terminal_report(str(self.run_dir))
        self.assertIn(pas.TERMINAL_REPORT_HEADING, text)
        self.assertIn("without you", pas.TERMINAL_REPORT_HEADING)
        body = text.split(pas.TERMINAL_REPORT_HEADING, 1)[0]
        self.assertNotIn("|", body)      # nothing tabular precedes it

    def test_the_lowest_rung_decision_is_in_the_first_table(self):
        # THE UNINFORMED-USER SEED. A provenance field read only by a validator
        # has informed nobody; a report that buries the weakest decision under
        # four sections has the field and not the effect.
        rows = self.first_table(pas.render_terminal_report(str(self.run_dir)))
        self.assertIn("Q-7c6b5a4938d2", rows[1])          # weakest, first data row
        self.assertIn("code-evidenced", rows[1])
        self.assertIn("Q-3f2a1b0c9d8e", rows[2])
        self.assertIn("specified", rows[2])

    def test_the_report_names_the_terminal_action(self):
        self.assertIn("complete", pas.render_terminal_report(str(self.run_dir)))

    def test_frozen_proposals_are_surfaced_and_marked_not_implemented(self):
        pas.record_completeness(str(self.run_dir), items=[{
            "id": "-", "class": "MISSING-FROM-SPEC", "traces_to": "none",
            "statement": "A sibling case is uncovered.", "evidence": "-"}])
        text = pas.render_terminal_report(str(self.run_dir))
        self.assertIn("CP-001", text)
        self.assertIn("not implemented", text)
        self.assertIn("complete-with-proposals", text)

    def test_provisional_work_is_listed_with_its_tainting_decision(self):
        text = pas.render_terminal_report(str(self.run_dir))
        self.assertIn("P02-T01", text)
        self.assertIn("Q-7c6b5a4938d2", text)

    def test_a_run_with_no_quorum_decision_still_says_so_in_the_first_table(self):
        (self.run_dir / "decisions.md").write_text(
            "\n".join(fixture("master-gate-decisions.md").splitlines()[:13]) + "\n",
            encoding="utf-8")
        rows = self.first_table(pas.render_terminal_report(str(self.run_dir)))
        self.assertIn("no decision was taken without you", rows[1])

    def test_publishing_is_immutable_and_replay_inert(self):
        first = pas.publish_terminal_report(str(self.run_dir))
        self.assertEqual(first, pas.publish_terminal_report(str(self.run_dir)))
        self.assertTrue((self.run_dir / "terminal-report.md").exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v -k TerminalReport`
Expected: FAIL — `AttributeError: module 'pipeline_auto_state' has no attribute 'render_terminal_report'`

- [ ] **Step 3: Write the implementation**

```python
TERMINAL_REPORT_HEADING = "## Decisions this run made without you"


def render_terminal_report(run_dir: str) -> str:
    """The run's closing report, leading with what the user never approved.

    Provenance must be visible in three places — the decision record, the tracker
    index, and here. A provenance field read only by a validator has informed
    nobody. Quorum decisions come first, sorted by grounding rung ASCENDING: the
    answer the run was least sure of is the one most likely to be wrong and least
    likely to be noticed, so it is the first row the user reads.
    """
    directory = Path(run_dir)
    tracker = parse_tracker((directory / "progress.md").read_text(encoding="utf-8"))
    parsed = parse_decisions((directory / "decisions.md").read_text(encoding="utf-8"))
    quorum = _weakest_first([record for record in parsed["decisions"].values()
                             if record["provenance"] == "quorum"
                             and record["status"] == "Adopted"])
    action = derive_terminal_action(str(directory))

    lines = [f"# {tracker['run']['run_id']} — terminal report", "",
             f"Next action: `{action}`.", "",
             TERMINAL_REPORT_HEADING, "",
             "A three-agent quorum decided each of these; you did not. They are listed",
             "weakest grounding first — the top row is the answer this run was least",
             "sure of.", "",
             "| D-ID | Grounding rung | Axis | Question | Adopted answer | Blocked work |",
             "| --- | --- | --- | --- | --- | --- |"]
    if not quorum:
        lines.append("| - | - | - | no decision was taken without you | - | - |")
    for record in quorum:
        lines.append(
            f"| {record['id']} | {record.get('grounding_rung', '-')} | {record['axis']} | "
            f"{record['question']} | {record['answer']} | {record.get('scope', '-')} |")

    taints = tainting_decisions(str(directory))
    lines += ["", "## Provisional work", "",
              "Tasks resting on an answer adopted below `specified` grounding.", ""]
    if not any(taints.values()):
        lines.append("None.")
    for task_id in sorted(task for task, records in taints.items() if records):
        for record in taints[task_id]:
            lines.append(f"- **{task_id}** rests on **{record['id']}** "
                         f"(`{record.get('grounding_rung', '-')}`): {record['answer']}")

    rejected = [event for event in quorum_events(str(directory))
                if str(event.get("status", "")).startswith("rejected-contradicts")]
    lines += ["", "## Rejected contradictions", "",
              f"{len(rejected)} candidate answers were rejected for contradicting a "
              "recorded decision.",
              "A run with several of these is a run whose brains kept pulling away from "
              "what you asked for.", ""]
    for event in rejected:
        lines.append(f"- `{event.get('qid', '-')}` — {event.get('status')}")

    challenges = _challenge_ledger(directory)
    lines += ["", "## Reviewer challenges to recorded decisions", ""]
    lines.append("None." if not challenges else "")
    for entry in challenges:
        lines.append(f"- **{entry['decision_id']}** — {entry['route']}: {entry['reason']}")

    proposals = completeness_proposals(str(directory))
    lines += ["", "## Completeness proposals (frozen — not implemented)", "",
              "Recorded for you. The run could not act on these: phase creation closed at",
              "stage 06, so there was no way to turn one into work.", ""]
    lines.append("None." if not proposals else "")
    for proposal in proposals:
        lines.append(f"- **{proposal['id']}** — {proposal.get('statement', '-')}")

    gate = next((row for row in tracker["gates"] if row["id"] == MASTER_GATE_ID), None)
    lines += ["", "## Verification", "",
              f"- Master gate edge: `{gate['base']}..{gate['head']}`" if gate else "- -",
              f"- Master gate state: {gate['state']}" if gate else "- -",
              "- Final verification: gate-master/final-verification.json", ""]
    return "\n".join(lines) + "\n"


def publish_terminal_report(run_dir: str) -> str:
    """Publish the report once. A byte-identical republish is inert."""
    return publish_immutable(str(Path(run_dir) / "terminal-report.md"),
                             render_terminal_report(run_dir))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v`
Expected: PASS — every P02–P06 class, including the 11 new P06 classes

- [ ] **Step 5: Run the full phase suite**

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
python3 -c "import ast; ast.parse(open('plugins/superb/skills/pipeline-auto/scripts/pipeline_auto_state.py').read())"
git diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The third command must print nothing.

- [ ] **Step 6: Commit**

```bash
git add plugins/superb/skills/pipeline-auto/
git commit -m "feat(pipeline-auto): lead the terminal report with the weakest quorum decision"
```

---

## Self-review

**Spec coverage.** The master plan's P06 row names five deliverables and each has a task.
Two-reviewer gate with non-implementer enforcement: Tasks 2, 3, 4, 9. `DECISION-CHALLENGE`
routing: Tasks 5 and 6, covering all eight rows of the spec's contradiction-routing table
plus the Minor/quality reversal rule. Completeness freeze: Task 8. Phase-set immutability:
Task 1, built first because Task 8's freeze is only real if Task 1's guard is. Final
verification: Task 11. The spec's governing invariant 6 is Task 1; invariant 7 (no push,
publish, PR or merge) is Task 11, where `git status --short` and the untouched-`pipeline/`
proof are checked on stdout rather than exit code — this phase adds no push path at all, so
there is nothing else to gate. The spec's "Cascading on a low-confidence answer" — verbatim
copy of the tainting decision into the reviewer's global-constraints block — is Task 3. The
terminal-report requirement from invariant 5 is Task 12.

**Master-plan cross-phase clarifications.** All five bind this phase and all five are
covered. The gate's head advances to each fix commit while sealed reports stay bound to the
edge they were written against: Task 4 binds, Task 9 checks each report against its own
binding and separately requires coverage of the current edge, Task 10 advances. Those are
two checks on purpose — validating a report against the current head would reject a
correctly sealed report after the first fix round, and accepting one bound to an older head
would close the gate over code nobody reviewed. Stage-11 re-review bounded at three rounds is Task 10, with the fourth-round halt
and the oscillation halt as separate named faults, because a counter alone cannot see
oscillation. `repo_root` as a `## Run` field is in both fixtures and is read through P02's
`repo_root(tracker)` in Task 11, never derived from run-directory depth. The raised bar
being *applied* rather than recorded is Task 6's `RaisedBarIsApplied`, which drives P03's
real adoption path and carries a control case — a test that inspected only the re-open
record would pass against a complete no-op. The worker-result owner grammar
`- **Owner:** <id>` is Task 2's `_OWNER_LINE`, and the independence check parses history
rather than current owners so a released worker cannot review its own task.

**On the two commands that must print nothing.** Both `git diff --name-only` and
`git status --short` exit `0` while printing, so an exit-code assertion passes on a run that
modified `plugins/superb/skills/pipeline/` — the one Global Constraint the whole rewrite
exists to honour. `FINAL_SUITE_SILENT = (2, 3)` verifies them on stdout, and both tests name
the reason in their own names:
`test_a_modified_pipeline_skill_fails_even_though_git_exits_zero` and
`test_a_dirty_working_tree_fails_even_though_git_exits_zero`.

**Placeholder scan.** No TBDs, no "add error handling", no "similar to Task N". Every Step 1
carries the actual test code and every Step 3 the actual implementation. The four fixtures
are written out in full rather than described. The one template file is written out in full.

**Type consistency.** `route_contradiction` returns the same four-key dict everywhere, built
only by `_route`, which validates its own route name against `ROUTES` — so a typo'd route is
an exception rather than a silently-unhandled string. `classify_completeness_item` returns a
`CRITIC_CLASSES` member or raises and never returns `None`. `raised_floor` and
`_weakest_first` both address `RUNG_ORDER` by index and never by value, matching P03's rule
that no float comparison exists between rungs. `open_findings`, `parse_findings` and
`upsert_finding` all speak the same nine-column row dict. `evaluate_master_gate` and
`record_final_verification` both return dicts and take no verdict.

**Gap found and closed.** The first draft had `tainting_decisions` keyed only on the
decision's own `Scope` field. That stops the provisional closure at the phase that raised
the decision, so a decision adopted during P01 governing a P02 task goes unmarked. It now
reads the task's `Decisions` column first — the column that exists precisely to cross a
phase boundary — and the fixture was changed so `Q-7c6b5a4938d2` is raised in P01 and taints
a P02 task, with a test asserting the two phases differ.

**Second gap found and closed.** The first draft's test helper did not write
`phase-set.json`, so every gate function — each of which re-checks the seal — would have
failed in every test for the wrong reason, and `test_a_frozen_run_with_no_sealed_file_is_a_stop`
would have passed accidentally. `new_run` now seals a frozen fixture and that one test
unlinks the file explicitly.

**Fifth gap found and closed.** The gate fix loop's first draft never advanced
`gate.head`, so every re-review would have read code without the fixes in it, the same
findings would have returned each round, and the three-round cap would have fired on every
gate that ever produced a finding. `record_gate_fix_round` now advances the head, and the
opposite error — rebinding sealed reports to the new head — is blocked by per-report
bindings whose test asserts both halves, because a test that only checks the head moved
passes against an implementation that rebinds everything.

**Fourth gap found and closed.** The gate fix loop's first draft closed a round with
findings still open and opened its successor in two transitions. P02 rejects a scope whose
last round is `complete` with a `Remaining` other than `none`, so the tracker was invalid
between the two writes — an interruption there strands the run in a state its own validator
rejects. That is the class of bug the single-locked-transition discipline exists to prevent:
a transition is the unit at which state is legal, so any change needing two writes to stay
legal is one write. Closing and opening now happen in one transition, and a halted round
stays `re_reviewing`, which is also what it truthfully is.

**A test pattern worth copying.** `RaisedBarIsApplied`'s third case asserts that the same
`code-evidenced` answer **does** adopt on a question that was never re-opened. Without it the
first two cases pass against a run that escalates everything, and the raised bar would still
be a no-op. The general form: a test that only proves the strict path rejects has not proven
the lenient path accepts, and a one-sided assertion is satisfied by a stuck implementation.
The same shape is why Task 10's rebinding test asserts that the gate accepts once both
reviewers re-report at the new head, not merely that the stale reports blocked.

**Third gap found and closed.** `evaluate_master_gate` originally treated a moved phase set
as a blocker. That is wrong: a blocker is something a fix round can clear, and a phase set
that no longer matches its seal is evidence the run's history is not what it claims. It
raises `PhaseSetFrozen` instead, and a test asserts the difference.

---

## Unresolved — reported, not invented

None of the following is settled by `2026-09-14-pipeline-auto-design.md` or
`2026-09-14-pipeline-auto-master-plan.md`. Each is marked **derived** (from a cited artifact
in this repository, and safe to overrule), **open** (no basis to derive; a decision is
needed), or **blocking** (a task here cannot be completed until someone rules).

**Four items in the first draft of this list are now settled by the master plan's
`## Cross-phase clarifications` section and are recorded below as resolved rather than
deleted, so a reader can see what was asked and what was answered.**

1. **`repo_root` as a `## Run` field.** **RESOLVED — binding.** The master plan now states
   that `repo_root` is a `## Run` field carried in P02's `_RUN_KEYS`, recorded by
   `initialize_run` and read by `effective_rung` for citation resolution. Deriving it from
   run-directory depth is the defect that would silently demote every grounded answer below
   the floor while appearing to work. Both fixtures here carry `| repo_root | . |`
   immediately after `target_branch`; only the placement within the key order remains P02's
   to fix, and nothing in this phase depends on it.

2. **Column placement of `Decisions` in `## Tasks`, and the fourteen `## Task Review`
   columns.** *Open.* The coordinator supplied both column sets but not `Decisions`'
   position; this plan's fixtures place it last, after `Provisional`. Every function here
   reads cells by name, so only the two fixture files depend on order. P05 owns the final
   order and these fixtures follow it.

3. **`Adversarial Verdict` vocabulary.** *Derived* from the spec's adjudication verdicts
   (`CONFIRMED`, `REFUTED`, `PLAUSIBLE`); the master-gate fixture uses `REFUTED`, chosen
   because a `CONFIRMED` or unrefuted `PLAUSIBLE` adversarial finding is ratchet trigger (a)
   and would make the fixture's phase state ambiguous. If P05 fixes a different vocabulary,
   the fixture needs a one-word edit.

4. **Run-local `decisions.md`, `findings.md` and `completeness-proposals.md`.** *Derived*
   from P03's `open_quorum`, which already reads `run_dir / "decisions.md"` directly. The
   `## Run` cells naming those files are therefore advisory labels rather than the paths the
   helpers resolve. If they are meant to be authoritative, every read in this phase needs to
   go through them and P03's needs the same change.

5. **Master reviewer identifiers and how they are drawn.** *Open.* Nothing in either
   document says who supplies `reviewers={"A": ..., "B": ...}`. This plan validates the pair
   and refuses a conflicted one; it does not allocate. The controller prose in P07 must say
   where the two identifiers come from, and that they must not be recycled from any earlier
   role in the run.

6. **The magnitude of "a raised bar".** *Derived.* The spec says a `DECISION-CHALLENGE`
   against a quorum decision becomes "one re-open at a raised bar" without defining the
   raise. `raised_floor` moves one rung up the ladder, clamped at `specified`, matching the
   one other place the spec raises a bar by a defined amount — the run-level inflation
   check, where "the adoption floor rises one rung". If a different magnitude is intended,
   it is a one-line change in `raised_floor`.

7. **Where the re-open's raised floor is enforced.** **RESOLVED — binding, and P03 owes
   code.** The master plan now states that a re-opened question's adoption requires the
   winning cluster's rung to be **strictly higher than the rung originally adopted**, not
   merely above the floor, and that P03 owns the path. P06 writes
   `quorum/<qid>/reopen.json`; Task 6's `RaisedBarIsApplied` asserts the adoption path
   consumes it, with a control case so the assertion cannot be satisfied by a run that
   simply escalates everything. **P03's plan on disk still does not mention re-opens**, so
   that test will fail until P03 implements the consumption — which is the correct failure,
   not a reason to weaken the test.

8. **The adjudicator's identity and model.** *Open.* The spec requires "one adjudicator —
   most capable model, read-only" for a fixer dispute and an "unbiased reconciliation" for a
   decision dispute, without saying whether they are the same agent type. This plan enforces
   only that the reconciliation adjudicator is neither master reviewer nor any prior owner.
   P07 must define the agent.

9. **`quorum_events` record shape.** *Derived.* Task 11 reads `event["status"]` and
   `event["qid"]` and counts statuses beginning `rejected-contradicts`, matching P03's
   documented `finalize_quorum().status` values. P03 declares `quorum_events(run_dir) ->
   list[dict]` without fixing the keys. If they differ, the rejected-contradictions section
   of the terminal report needs the real key names.

10. **Worker-result owner grammar.** **RESOLVED — binding.** The master plan now pins the
    worker-result template's owner grammar as `- **Owner:** <id>`, owned by P04, and states
    that independence is checked against every owner appearing in any task's history —
    including released and superseded attempts — rather than against current owners. That is
    exactly what `owner_history`'s `_OWNER_LINE` scan of `<run_dir>/results/**/*.md` does,
    and Task 2's released-worker test is the assertion.

11. **Escalation blast radius for a halted challenge.** *Derived.* `_queue_escalation` uses
    `blast="run"` because the spec makes the freeze on raising run-wide and because a
    challenge to a recorded decision is not scoped to one phase. Neither document enumerates
    the legal blast values; P02 validates only that it is a token.

12. **Whether stage 11 may re-open after a fix round.** **RESOLVED — entailed, and now
    built as Task 10.** The master plan's clarification derives it rather than decreeing it:
    the inlined SDD protocol re-runs the final review on the updated package and finishes
    when a round returns zero, and the recorded default extends zero-open-findings to the
    master gate — so a gate that could not re-review could never close after its first
    finding, which makes `SPEC-NOT-MET` unfixable by construction. The bound is the same cap
    of three that applies at task scope; a fourth round halts to the escalation queue, and a
    round resolving none of its targets, or one whose fixes oscillate, halts immediately
    without spending the remainder. Task 10 builds it with both halts as separate named
    faults.

13. **Whether a master-gate re-review advances `gate.head`.** **RESOLVED — entailed, and
    now built.** The master plan rules that it does, and the reasoning is short: the inlined
    SDD protocol re-runs the final review on the *updated package*, so a gate whose head
    stayed at the initial edge would re-review code without the fixes, the same findings
    would return every round, and Task 10's cap would fire on every gate that ever produced
    a finding — a loop that cannot succeed rather than a conservative one. Two heads are in
    play and the distinction is the point: `record_gate_fix_round` advances `gate.head` to
    the fix commit, while each report stays bound to the edge it was written against, since
    the digest binding is what makes it evidence. Task 4 binds, Task 9 checks each report
    against its own binding and separately requires coverage of the current edge, Task 10
    advances and asserts both halves.

**Nothing in this list now blocks P07.** Items 1, 7, 10, 12 and 13 are settled by the master
plan's `## Cross-phase clarifications`; item 7 additionally owes code in P03, and Task 6's
`RaisedBarIsApplied` will fail until it lands, which is the correct failure. The remaining
items are naming and placement details that change one line each.
