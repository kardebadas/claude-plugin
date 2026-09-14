# Pipeline Auto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `superb:pipeline-auto`, a standalone skill that carries a feature from idea to implementation with exactly one human gate, resolving every later decision by a three-agent confidence quorum.

**Architecture:** A controller skill (`SKILL.md` + five references) over a single Python state module that owns all durable transitions. The state module is a markdown-tracker parser/renderer with strict semantic validation, an OS-level lock, atomic replacement, and immutable artifact publication. Review discipline is the subagent-driven-development protocol, inlined rather than invoked, with intensity set per phase by a one-way ratchet dial. Every decision the run makes without the user is recorded with its grounding tier and surfaced in the terminal report.

**Tech Stack:** Python 3 standard library only, tests included. **`pytest` is NOT installed on this machine and must not be used** — tests are `unittest.TestCase` and run under `python3 -m unittest discover -s <dir> -v`. **Never pass `-t .`** — `pipeline-auto` is hyphenated, so top-level-relative discovery tries to import `plugins.superb.skills.pipeline-auto.tests` and dies with `ImportError: Start directory is not importable`. Verified on Python 3.11.2, with and without `__init__.py`. Sub-suites use repeated `-k A -k B` (unittest ORs them), not pytest's `-k "A or B"`. Markdown for all durable state. POSIX file locking with a documented fallback.

**Spec:** `docs/superpowers/specs/2026-09-14-pipeline-auto-design.md`

## Global Constraints

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

## File Structure

| File | Responsibility |
| --- | --- |
| `plugins/superb/skills/pipeline-auto/SKILL.md` | Controller prose: invocation modes, stage routing table, zero-assumption reversal, Red Flags, stop checks |
| `references/planning.md` | Stages 01–07: intent read, question synthesis, the gate, design, spec, master plan, phase fan-out |
| `references/quorum.md` | Admissibility, payload and prohibition list, tier table, adoption arithmetic, replay, escalation |
| `references/execution.md` | Stages 08–10: dial, per-task gate, TDD, scopes, evidence, integration, debugging |
| `references/review.md` | Stages 11–12: master gate, contradiction routing, completeness freeze, final verification |
| `references/persistence.md` | Tracker operations, status, resume, results, recovery |
| `scripts/pipeline_auto_state.py` | **The spine.** All durable transitions. Parse/render, validation, lock, atomic replace, immutable publication, quorum record, task lifecycle, dial, gates |
| `scripts/task-brief` | Extract one task's text from a phase plan to a uniquely named file |
| `scripts/review-package` | Build a commit list + stat + full diff for a range into one file |
| `scripts/sdd-workspace` | Create the self-ignoring `scratch/` inside the run directory |
| `prompts/implementer.md` | Per-task implementer dispatch template |
| `prompts/task-reviewer.md` | Three-verdict reviewer template (spec, quality, independent verification) |
| `prompts/adversarial-reviewer.md` | Refutation template for triggered diffs |
| `prompts/brain.md` | Quorum brain template: strict JSON out, tier selection, prohibition list |
| `templates/*.md` | `progress`, `decisions`, `findings`, `worker-result`, `verification-evidence`, `task-brief`, `worker-report`, `completeness-proposals` |
| `examples/controller_walkthrough.py` | Executable end-to-end proof in a foreign empty repo |
| `tests/test_pipeline_auto_state.py` | Unit tests, re-derived against this skill's own faults |
| `tests/fixtures/` | Valid and invalid trackers, phase plans, worker results, brain responses |
| `plugins/superb/agents/pipeline-auto-brain.md` | `tools:` exactly `{Read, Grep, Glob}`. **No `Bash`** — frontmatter allowlists tools, not commands, so "read-only Bash" is unenforceable and a brain holding `Bash` can rewrite `decisions.md`. No `Agent`, no `Write`, no `Edit` |
| `plugins/superb/agents/pipeline-auto-intent-reader.md` | Stage-01 reader; strict JSON hypothesis out, no design proposals |

---

## Phases

Each phase gets its own detailed plan at `docs/superpowers/plans/pipeline-auto/phase-NN-<slug>.md`, written by a `superpowers:writing-plans` worker against this master plan and the spec. No phase plan invents an interface this document does not name; unresolved interfaces are reported back, not guessed.

| Phase | Depends on | Review class | Deliverable |
| --- | --- | --- | --- |
| P01 pressure-baselines | — | `required` | RED transcripts of agents failing each scenario with no skill present |
| P02 schema-core | — | `required` | `pipeline_auto_state.py`: parse, render, validate, lock, atomic replace, initialize, filesystem classification. `## Tasks` carries a `Phase` column — the per-phase drift budget and the ratchet are otherwise underivable |
| P03 quorum-contract | P02 | `required` | Quorum record, qid derivation, tier recomputation, contradiction detection, budget, depth |
| P04 task-lifecycle | P02 | `required` | Reserve/start/resume, typed scopes, result identity, range proof, ancestry, reconciliation |
| P05 dial-and-gate | P03, P04 | `required` | `## Task Review` (14 columns — a task has N rounds, so a placeholder that cannot express per-round intensity and live `Open` counts carries none of the never-off rules), `## Fix Rounds`, adversarial trigger, one-way ratchet, provisional propagation |
| P06 master-gate | P05 | `required` | Two-reviewer gate, `DECISION-CHALLENGE` routing, completeness freeze, phase-set immutability, final verification |
| P07 skill-prose | P06 | `final-only` | `SKILL.md`, five references, two agent files, four prompts, all templates, three inlined scripts |
| P08 pressure-green | P01, P07 | `required` | GREEN transcripts, loophole closure, re-verification |
| P09 walkthrough | P07, P08 | `final-only` | `controller_walkthrough.py` proving the skill works from an installed path in a foreign repo |

P01 and P02 are independent and may run concurrently. P03 and P04 are independent of each other once P02 lands. Everything else is sequential.

P07 is `final-only` because prose carries no unit-testable fault; its gate is P08. It is **not** exempt from the structure validator (see its interface contract below), nor from any of the things the dial may never switch off.

---

## Interface contracts between phases

Phase-plan workers consume these verbatim. A worker needing something not listed here reports it rather than inventing it.

### P01 produces — consumed by P08

- `tests/pressure/stimuli/S01..S08.md` — committed, **facts only**. A stimulus states the situation and never states the correct behaviour, or the baseline measures the skill instead of the agent.
- `tests/pressure/oracles.md` — **uncommitted while P01 measures, committed by P01's last task**. Per scenario: the correct behaviour, the fail predicate, the rationalization watchlist, and a `GREEN predicate:` line. P08 asserts against this line verbatim. See the ordering note below.
- `tests/pressure/records/<class>/` — evidence records, where `<class>` is `actual-agent` or `simulated`. A committed validator rejects any record whose internal class label disagrees with its directory.
- `tests/pressure/RED-baseline.md` — the one committed curated record: two tables, one row per scenario, carrying the verbatim rationalization and the fail-predicate outcome.

Raw transcripts live in `tests/pressure/records/`, ignored in place by a self-ignoring `.gitignore`. Only the stimuli, the validator and `RED-baseline.md` are committed during P01. P08 depends on `RED-baseline.md`, not on the transcripts, so it survives a different workspace.

**`oracles.md` is uncommitted during P01 and committed by P01's final task, after every RED record is captured and validated.** The ordering is the whole point and must be stated in the plan: the oracle has to be secret while the RED baseline is measured, because an unaided agent that can read the answers is measuring the repository rather than itself. After P01 closes, secrecy is no longer purchasable at any price — P07 writes the correct behaviour into `SKILL.md`, which is the same information. Withholding the oracle past that point buys nothing and costs P08 its GREEN predicates, so P01 commits it on the way out.

### P02 produces — consumed by P03, P04, P05, P06, P09

```python
SCHEMA = "pipeline-auto/v1"
MARKER = "<!-- pipeline-auto/v1 -->"

class TrackerError(Exception): ...
class ForeignSchemaError(TrackerError): ...       # v1/v2/unknown marker -> read-only stop
class TrackerValidationError(TrackerError): ...   # semantically impossible state
class TrackerWriteError(TrackerError): ...        # write failed, nothing changed
class UpdateOutcomeUncertain(TrackerError): ...   # replaced then sync failed; may have applied
class PlanMetadataError(TrackerError): ...        # phase-plan comment grammar violation

def parse_tracker(text: str) -> dict: ...
def render_tracker(tracker: dict) -> str: ...
def validate_run(run_dir: str) -> dict: ...
def initialize_run(run_dir: str, *, run_id: str, base_commit: str,
                   target_branch: str, worker_limit: int, repo_root: str) -> dict: ...
def locked_tracker_update(run_dir: str, *, transition_id: str, mutate) -> dict: ...
def publish_immutable(path: str, content: str) -> str: ...   # returns the sha256 hex digest, not the path
def derive_next_action(tracker: dict) -> str: ...

# Section column grammar — P02 OWNS ALL OF IT, including sections whose rows
# later phases write. A phase that writes rows it does not own still needs the
# grammar validated in one place, or `## Quorum` drifts from its validator.
SECTIONS: dict[str, tuple[str, ...]]   # section name -> ordered column tuple
def section_columns(name: str) -> tuple[str, ...]: ...
def append_row(tracker: dict, section: str, row: dict) -> dict: ...
# `## Tasks` carries BOTH `Phase` and `Decisions`. `Phase` makes the per-phase
# drift budget derivable; `Decisions` (the decision ids a task's plan cites) is
# what lets taint cross a phase boundary. Without it the provisional closure
# stops at the raising phase and a P05 decision tainting a P07 task is silently
# unmarked — the exact cascade the taint rule exists to catch.
def repo_root(tracker: dict) -> str: ...   # recorded at init; NEVER derived from run_dir depth
def classify_filesystem(path: str) -> str: ...  # unclassified => read-only stop BEFORE the run starts
```

`locked_tracker_update` contract: validate, acquire exclusive lock, re-read, revalidate, apply `mutate`, render, **reparse the render**, write to a temp file in the run directory, fsync, atomic replace, fsync the directory. A replayed `transition_id` returns current state without mutating. A post-replace sync failure raises `UpdateOutcomeUncertain`, never `TrackerWriteError`.

### P03 produces — consumed by P05, P06

```python
RUNGS = {"specified": 0.95, "code-evidenced": 0.85, "convention-cited": 0.70,
         "engineering-judgement": 0.55, "speculation": 0.30}   # frozen; NOT run config
ADOPTION_FLOOR = 0.85
DEPTH_CAP = 2
BUDGET_PER_PHASE = 3
BUDGET_PER_RUN = 10
MAX_EXTENSIONS = 2

def derive_qid(question: str, axis: str) -> str: ...      # sha256(normalize(q) + "\x00" + axis)[:12]
def effective_rung(response: dict, repo_root: str) -> str: ...  # resolve citation, then demote
def cluster_rung(cluster: list) -> str: ...               # MAX member rung, never mean
def project_decisions(decisions: dict) -> str: ...        # question + answer + provenance ONLY; no values
def open_quorum(run_dir: str, *, question_record: str) -> dict: ...
def record_brain_response(run_dir: str, *, qid: str, owner: str, payload: dict) -> str: ...
def build_payload(qid: str, brain_index: int, *, run_dir: str) -> dict: ...
def finalize_quorum(run_dir: str, *, qid: str) -> dict: ...  # adopted | escalated | rejected-*
def check_contradiction(decisions: dict, candidate: dict) -> str | None: ...
def decision_depth(decisions: dict, consistent_with: list) -> int: ...
```

### P04 produces — consumed by P05, P06

```python
def reserve_task(run_dir: str, *, task_id: str, owner: str, attempt: int) -> dict: ...
def resume_task(run_dir: str, *, task_id: str, prior_attempt: int,
                new_owner: str, new_attempt: int, decision_ref: str) -> dict: ...
def scopes_overlap(a: str, b: str) -> bool: ...   # file:/tree: with ancestor rules
def parse_plan_metadata(path: str) -> dict: ...   # strict comment grammar, pinned key order; raises PlanMetadataError
def publish_worker_result(run_dir: str, *, result: dict) -> str: ...
def import_worker_result(run_dir: str, *, result_path: str) -> dict: ...
def verify_source_range(repo: str, *, baseline: str, head: str, scopes: list) -> dict: ...
def reconcile_run(run_dir: str) -> dict: ...
```

### P05 produces — consumed by P06

```python
ADVERSARIAL_TRIGGERS = ("concurrency", "authz", "crypto", "schema", "migration",
                        "delete", "regulated", "public-api", "large-surface")
RATCHET_TRIGGERS = ("adversarial-finding", "repeated-suite-failure",
                    "debug-locality", "low-confidence-dependency", "accumulated-surface")

def adversarial_required(diff_paths: list, changed_lines: int) -> str | None: ...
def record_task_review(run_dir: str, *, task_id: str, attempt: int, verdict: dict) -> dict: ...
def open_fix_round(run_dir: str, *, scope: str, findings: list) -> dict: ...
def ratchet_phase(run_dir: str, *, phase: str, trigger: str, evidence_ref: str) -> dict: ...
def propagate_provisional(tracker: dict) -> dict: ...
```

### P07 produces — consumed by P09

A structure validator, `tests/test_skill_structure.py`, asserting: frontmatter present and within limits; every `references/*.md` named in `SKILL.md`'s routing table exists on disk; every agent named in `SKILL.md` exists as a file; every prompt template referenced resolves. Its named fault: renaming a reference without updating the routing table produces a dead route at runtime, silently, mid-run.

---

## Verification suite

Each phase's plan names its exact ordered command tuple. The run-wide suite, executed at the master gate and at final verification, is:

```bash
python3 -m unittest discover -s plugins/superb/skills/pipeline-auto/tests -v
python3 plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py
git -C . diff --name-only c8bddd610119f52b54bf077d284c7f5d8362ae77..HEAD -- plugins/superb/skills/pipeline/
git status --short
```

The third command must print **nothing**. Any output means `skills/pipeline/` was modified and the run fails. The fourth must also print nothing at stage 12.

---

## Self-review

**Spec coverage.** Every spec section maps to a phase: the reversal statement and Red Flags to P07; governing invariants to P02 (4), P03 (1, 2, 3, 5), P06 (6, 7); composition to P07; stages to P07 prose with mechanics in P03–P06; the quorum contract to P03; the dial to P05; contradiction routing to P06; completeness proposals to P06; failure modes to P03 (drift, inflation, contradiction, depth), P05 (cascading, provisional), P06 (challenge routing), P04 (scope conflicts); state schema to P02; phase breakdown to this document; deliverables to P07; recorded defaults to P07 prose and P04 (worktree granularity); unknowns to P07 prose.

**Gap found and closed.** The spec's `## Stage` tracker section — the thing that makes stages 01–07 recoverable at all — had no home in the phase table. It belongs to P02, not P03, because a compaction during stage 02 must be recoverable before any quorum machinery exists. P02's phase plan carries it.

**Second gap found and closed.** `git status --short` cleanliness at stage 12 requires `scratch/` to be self-ignoring. That is `scripts/sdd-workspace`, listed under P07, but it is needed by P05's per-task gate. Moved to P02's deliverable set as a prerequisite; P07 carries only its documentation.

**Placeholder scan.** No TBDs. Every interface block above carries real signatures. Phase plans carry the code.

**Type consistency.** `effective_rung` returns a rung name (string), not a float; callers in P05 and P06 look the value up in `RUNGS`. `check_contradiction` returns the offending D-ID or `None`, not a boolean. `adversarial_required` returns the trigger name or `None`, not a boolean — so the tracker can record *which* trigger fired.
