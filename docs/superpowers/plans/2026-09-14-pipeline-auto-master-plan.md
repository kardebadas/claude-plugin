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
- **Agent-supplied JSON is never tested for membership with a bare `in` against a set.** `x in frozenset(...)` hashes `x`, and a JSON value may legally be a list or an object — both unhashable, and the resulting `TypeError` is outside `TrackerError`, so it escapes every handler a controller has written and kills the run on an agent's typo. Use `_member(value, allowed)`. Every call site must be pinned: reverting it to a bare `in` must fail the suite. Found in `effective_rung` by review, then in three more places where the source was already correct and nothing would have noticed it changing.
- **A test claiming totality derives its case list from the function's call tree**, not from what the author remembers reading. Vary every field with both an unhashable value and a wrong-typed scalar.
- **`is_file()` never means "there is nothing here".** It is false for a directory, a dangling symlink, a symlink loop and a FIFO — all of which exist and cannot be read. Folding them into "absent" is fail-open. Ask existence of the name (`os.path.lexists`) and readability of the target (`read_text` only for a regular file, which also stops a FIFO blocking under a lock). Found twice in consecutive tasks, both times only by mutation.
- **A SYMMETRIC property is blind to a screen deleted from the code both sides share.** P04 Task 5 swept 972 generated records asserting "render accepts iff parse accepts", against builders that call neither function. The oracle was genuinely independent — and the sweep still stayed green under three mutants, because deleting a check from the *shared* validator removes it from both sides at once and the biconditional still holds. Agreement tests catch divergence, never a shared omission. **Pair every agreement sweep with a table of candidates carrying their own verdicts** (legal/illegal, decided independently of the implementation), or the sweep certifies only that the two directions are equally wrong. Mutation is what exposed this: 18/22 on the first run with the sweep green on all three survivors.
- **And a candidate table of VALUES does not reach a screen whose subject is the DOCUMENT.** The correction above was still not enough, and the same task proved it. The candidate table fixed the three survivors and a fourth stayed alive: the byte comparison `render(validated) != text`, made newline-insensitive (`.rstrip("\n")`) and then whitespace-insensitive (`.strip()`). Both mutants accepted the canonical record, the same record with no trailing newline, and the same record with three — **one record, three legal spellings, three sha256s** — with the full 1456-test suite green. Neither the sweep nor the table could see it: every document either builds goes through one fixture that always emits one leading marker line and exactly one trailing `\n`, so all of that coverage is over CELLS and the ENVELOPE around them was pinned by nothing. **When a screen's subject is the whole document — a byte comparison, a marker line, a field-name sequence — the corpus must vary the outer boundary**: trailing-newline count, leading blank lines, a trailing space, a CRLF copy, a BOM, an indented table. Add one literal canonical specimen too, so the boundary is pinned by a comparison a reader can check by eye.
- **`cp` is aliased to `cp -i` in this environment and `cp -f` does not reliably suppress it** — one restore of the user's `plugin.json` silently did nothing. Use `cat src > dst` or `/bin/cp`, and re-read the file to confirm a restore actually happened.
- **A phase plan's "Produces" block is a claim to CHECK, not a list to implement.** Four names across three P04 briefs were already defined in the module, and a module-level redefinition rebinds the global for every existing caller. `_cell` is P03's tracker-cell writer with **eleven** call sites — redefining it with a different arity is a `TypeError` at all eleven; `_field` (line 261), `_csv` (line 344) and `_COMMIT` (line 719) are P02's. Task 1 did exactly this to `_TOKEN` and silently narrowed a grammar used at sixteen sites. **Before implementing a Produces block, check each name against the module: a name that exists is consumed, never re-declared.** The mechanical form of this rule is an AST guard asserting no module-level name is bound twice, which P04 Task 4 added. **As first written it enforced three binding forms, not all** — `def`, `class` and a plain `x = ...` — and measured against four injected duplicates it missed the annotated assignment (`x: T = ...`), the tuple target (`x, y = ...`) and the one inside a module-level `try`, and ignored `import`/`from … import` bindings entirely. It was widened in the P04 Task 4 fix round to count every binding form, including those inside a module-level `if`, `try`, `for` or `with`, while treating the arms of an `if`/`else` or `try`/`except` as alternatives so the module's own `fcntl`/`msvcrt` platform switch is not a false positive. **Read the claim as scoped to what the guard covers**: it catches a duplicate module-level binding, in any syntactic form, without anyone remembering to look — it does not see a name shadowed inside a function, a name bound by `exec`, or a name a `from x import *` would bring in.
- **A fixture whose incidental properties coincide with the property under test cannot distinguish them.** Every `ClassifyQuorum` fixture used owners `brain-a, brain-b, brain-c` — alphabetical *and* dispatch order — and only ever made the *first* owner the answered one. So across a whole test class, "dispatch order", "alphabetical order" and "the first owner" were one thing, and two mutants that reordered the dispatch list survived 847 tests. The claim mattered: a caller rebuilds brain *n*'s payload from the position it finds the name in, so a wrong order re-sends the wrong brain's bytes. **When a test asserts an ordering, a selection, or an identity, build the fixture so the right answer and the incidental one differ** — non-alphabetical names, the interesting element in the middle, a count that is not also an index.

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
| `plugins/superb/agents/pipeline-auto-intent-reader.md` | Stage-01 reader; strict JSON hypothesis out, no design proposals. `tools:` exactly `{Read, Grep, Glob}` — same reason as the brain, and sharper: it writes the intent brief every later citation anchors to |

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

- `tests/pressure/stimuli/S01..S10.md` — committed, **facts only**. A stimulus states the situation and never states the correct behaviour, or the baseline measures the skill instead of the agent. (This contract said `S01..S08` until P01 closed; P01 built **ten**, and `oracles.md` carries ten `Correct behaviour:` entries and ten `GREEN predicate:` lines. Corrected here rather than in P08's plan, because this block is what P08's worker consumes verbatim.)

**Binding on P08, from P01's measurement — these are findings, not preferences:**

- **Exclude S05 from scoring.** Its stimulus scaffolds the answer, so it did not fail on the behaviour it tests, and a GREEN on it would measure the stimulus rather than the skill. Nine scenarios score.
- **Run GREEN with the pressure suffix.** P01's RED waves were dispatched with `pressure=suffix` where the plan had specified `plain` for waves 1-3. That deviation is recorded, and it binds: a GREEN measured without the suffix is not comparable to the RED it is being compared against.
- **Depend on `RED-baseline.md`, never on `records/`.** The raw transcripts are ignored in place and do not survive a different workspace; the curated baseline is committed and does.
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
def render_verification_evidence(record: dict) -> str: ...        # THE only writer
def parse_verification_evidence(text: str) -> dict: ...           # last screen is the renderer
def resolve_evidence(run_dir, repo_dir, reference: str) -> dict: ...  # run dir first; a mismatch stops there
```

**The verification-evidence codec is public and belongs to P04** (added by the
Task 5 fix round, on `integrate_task`'s precedent above). P05 and P06 both
consume evidence records and neither can reach a private codec. Three
constraints ride with the names and bind their callers:

- **A record is rendered and only then published.** `render_verification_evidence`
  is the ONLY writer, because `parse_verification_evidence`'s last screen is a
  byte comparison against its output — so a document assembled any other way
  cannot be read back, and a record's identity is the sha256 of exactly those
  bytes. Task 10 must render *then* `publish_immutable`, never write a document
  it built itself.
- **`EVIDENCE_PURPOSES` is extended by the phase that needs the purpose.** P05
  appends `task-review` and `adversarial`; P06 appends `branch-review`,
  `completeness` and `final`. An unregistered purpose is refused, which is the
  point: a purpose nobody declared is a record nobody validates.
- **`purpose` and `subject` are deliberately NOT cross-checked** and no
  cross-field rule is pinned today (`purpose="phase"` with `subject="task/T1"`
  validates). The mapping is derivable for the three purposes P04 ships and is
  not derivable for `adversarial`, `completeness` or `final`, so a rule written
  now is one P05 and P06 must remember to extend in a second place. If P06 wants
  it, the shape is a registry beside `EVIDENCE_PURPOSES`, not a conditional.

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

## What `ALLOWED_IMPORTS` actually gates

The allowlist has moved in both directions and the rule that decides it is
**capability, not convenience.**

`tempfile` was added in Task 9 and removed in its fix round once `os.open` with
`O_CREAT|O_EXCL` proved to give identical exclusivity — it carried real
capability (file creation, and a silent 0600 mode that was narrowing the
tracker's permissions on every write) and bought nothing that could not be had
without it.

`copy` was added in Task 10 and kept, even though a reviewer proved a hand-rolled
two-level copy passes every test. It opens nothing, execs nothing and reaches no
filesystem, so it widens no capability; and the hand-rolled form would encode the
tracker's shape a second time beside `_SECTIONS`, where the two can drift.

So the question to ask of a proposed member is not "could this be avoided?" —
almost always it could — but **"does this let the module do something it
previously could not?"** If yes, justify the capability or find another way. If
no, the cost is a name in a list and the benefit is usually a rule stated once
instead of twice.

## The plugin gate's real baseline is ONE failure, not three

`./tools/check-plugin.sh` reports three failures in this working tree and
**one** on committed content. Measured both ways:

```
with the dirty plugin.json            with plugin.json committed
  FAIL version drift claude/codex       FAIL pipeline-auto has no SKILL.md
  FAIL pipeline-auto has no SKILL.md    (nothing else)
  FAIL codex manifest Pipeline v2
```

Two of the three come entirely from an uncommitted edit to
`plugins/superb/.codex-plugin/plugin.json` — a Codex build stamped
`0.14.0+codex.20260910151644` — that predates this build and belongs to the
user. **Do not commit it**: committing would write a fabricated version drift
into the repository to make a gate look green.

The one genuine failure is cleared by P07, which creates `SKILL.md`. After
that the plugin gate is fully green on a clean tree, and any new failure is
this build's.

This was mis-stated as "three known pre-existing failures" from P01 through
P03 Task 11. No decision depended on it — the count was consistent across
every task and none of the three was ever caused by a commit here — but the
characterisation was wrong, and a worker told to expect three would accept a
regression that took it from one to three.

## Every phase closes with an interface sweep

**This step exists because four pinned interfaces escaped two complete phases.**
`repo_root`, `section_columns`, `append_row` and `classify_filesystem` were all
named in the "P02 produces" block above. P02 ran twelve tasks and twelve reviews
without building any of them, because **no P02 task consumed them** — every
review checked what its task claimed, none checked what this plan promised the
next phase. They surfaced only when P03 Task 1 reached for a name that was not
there, and were closed after the fact in `497cad8` and `268f712`.

`repo_root` is the one that shows the cost. Without it, P03 would have derived
the repository root from run-directory depth; every citation would then fail to
resolve, every grounded answer would demote to `engineering-judgement`,
everything would land below the adoption floor, and the run would escalate every
question it was ever asked **while looking like a correctly cautious quorum.** No
error, no failing test.

**So before a phase is called complete, check its own "produces" block against
the module**, name by name. A name with no consumer inside its phase has nothing
else checking it exists. This takes a minute and it is the only thing standing
between a promised interface and a phase that consumes it discovering the
absence.

## Platform support is Linux-only, and fails closed

`classify_filesystem` returns `unknown` on macOS and Windows, and unknown is a
halt — the lock and the atomic replace rest on POSIX semantics that not every
filesystem honours, so a run that cannot classify its filesystem does not start.

Probing macOS needs `subprocess` and `plistlib`; Windows needs `ctypes`.
**`ALLOWED_IMPORTS` stays at eleven and these are refused.** `subprocess` grants
arbitrary command execution, which is the single capability this boundary most
exists to withhold, and platform detection is not worth it. The failure is in the
safe direction: the skill refuses to run rather than running with its
single-writer and atomic-write guarantees quietly false.

P07 must state this as a platform requirement in `SKILL.md` rather than leaving a
macOS user to discover it as an unexplained halt.

## Cross-phase clarifications

Resolved after the phase plans were written, where two phases needed the same
answer. These bind every phase.

**Stage 11 re-reviews after a fix round, bounded at three rounds.** Neither the
spec nor the master plan said so, and P06 correctly refused to invent it — but it
is entailed rather than open. The inlined SDD protocol states that a final review
returning findings gets one fix subagent carrying the complete list, then the
final review re-runs on the updated package, and the branch is done when a round
returns zero. The recorded default extends zero-open-findings to the master gate,
so a gate that could not re-review would be a gate that can never close after its
first finding. The bound is the same fix-round cap of three that applies at task
scope: a fourth round **halts to the escalation queue** rather than looping. A
round that resolves none of its targeted findings, or whose fixes oscillate,
halts immediately without consuming the remaining rounds.

**`repo_root` is a `## Run` field**, not a derived value, and P02 carries it in
`_RUN_KEYS`. P06's fixtures already assume this. It is recorded by
`initialize_run` and read by `effective_rung` for citation resolution — deriving
it from run-directory depth is the defect that would silently demote every
grounded answer below the floor while appearing to work.

**A re-open applies a raised bar, and the bar must be applied, not merely
recorded.** P03 owns the re-open path. A re-opened question's adoption requires
the winning cluster's rung to be strictly higher than the rung originally
adopted — not merely above the floor. Recording the raised bar in the quorum row
without enforcing it at adoption is a silent no-op, and it is the kind of defect
that passes every test asserting the row's contents.

**The worker-result template's owner grammar is `- **Owner:** <id>`.** P04 owns
the template; P06's reviewer-independence check parses owner history out of it.
Independence is checked against every owner that appears in any task's history,
including released and superseded attempts — not against current owners only, or
a worker released after finishing a task can be assigned to review it.

**`gate.head` advances with each fix round; sealed reports keep the head they
were written against.** Entailed, not open: the inlined SDD protocol re-runs the
final review on *the updated package*, and a gate whose head stayed at the
initial edge would re-review code that does not contain the fixes — returning the
same findings every round until the cap halts, which makes the fix loop a
guaranteed no-op rather than a loop.

So `record_gate_fix_round` advances `gate.head` to the fix commit, and
`evaluate_master_gate` compares each report against the head **it was written
against**, not against the current one. A report sealed at the initial edge stays
bound to that edge — its digest binding is what makes it evidence, and rebinding
it to a later head would silently claim a reviewer saw code they never read. A
round therefore has two heads in play, and the distinction is the whole point:
the gate advances, the evidence does not.

**Section column tuples are pinned by P02's committed fixture**, not by any
later phase's assumption. Read them from
`plugins/superb/skills/pipeline-auto/tests/fixtures/valid-progress.md` rather
than restating them — a restatement is a second source of truth that drifts. As
built:

| Section | Columns |
| --- | --- |
| `## Intent` | ID, Kind, State, Owner, Result, Conflicts |
| `## Questions` | ID, Origin, Slot, State, Decision |
| `## Quorum` | QID, Axis, Phase, State, Owners, Payload Digest, Context Digest, Responses, Depth, Rung, Outcome, Decision |
| `## Escalations` | ID, QID, Blast, State, Batch, Resolution |
| `## Tasks` | ID, Phase, Kind, State, Owner, Attempt, Result, Checkpoints, Source Ref, Commits, Artifacts, Integration, Verification, Question, Decisions, Provisional |
| `## Task Review` | Task, Round, Intensity, State, Reviewer, Package, Report, Critical, Important, Minor, Adversarial, Adversarial Verdict, Open, Evidence |
| `## Phases` | ID, State, Verification, Review Class, Class Source, Ratchet, Gate |
| `## Gates` | ID, Type, Phase, State, Base, Head, Assignments, Reports, Verification, Findings |

**Correction to an earlier claim of mine:** I wrote that `Payload Digest` is per
brain index. It is not, and the committed fixture is right — one digest per cell.

The reading assignment is a **constant rule**, not data: index 0 grounds in the
spec and intent brief, 1 in repository code and tests, 2 in the decisions record
and phase plan. `build_payload` is pure, so brain *n*'s payload is fully
determined by the shared payload plus *n*. One digest over the shared payload —
the question record and the decisions projection — therefore binds all three, and
a re-dispatch of index *n* is reproducible from `(Payload Digest, n)`.

This is why the fixture needs no third column, and why "identical payload"
elsewhere in this document means identical to that index's own payload. If the
assignment rule ever becomes data rather than a constant, this collapses and the
column has to carry three digests — so the rule belongs in the frozen constants
beside `RUNGS`, not in `## Run`.

**`integrate_task` is public and belongs to P04.** The spec assigns integration
and the ancestry predicate to the task lifecycle, but the interface block named
no transition, so P04 built it privately. A private integration transition cannot
be called by P05's gate or exercised by P06's tests. Add it to the P04 surface:

```python
def integrate_task(run_dir: str, *, task_id: str, merge_commit: str) -> dict: ...
```

**`initialize_run` seeds artifact references and an empty `## Tasks`.** P04 found
it seeds neither, while the lifecycle needs both. `phase_plans`, `decisions`,
`findings` and `repo_root` are `## Run` fields written at init; task rows are
appended by the phase-plan import, which is P04's, not P02's.

**`EVIDENCE_PURPOSES` is extended by the phase that needs a purpose**, and the
validator rejects an unlisted one. P04 ships `task-test`, `task-integration`,
`phase`. P05 adds `task-review` and `adversarial`; P06 adds `branch-review`,
`completeness` and `final`. A phase that writes an evidence record under a
purpose it did not register fails parse — which is the intended behaviour, since
a purpose nobody declared is a record nobody validates.

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
