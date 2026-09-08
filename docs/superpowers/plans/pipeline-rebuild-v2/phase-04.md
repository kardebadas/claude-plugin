# Pipeline v2 Phase 4 — Behavioral Pressure, Acceptance, and Performance Evidence Implementation Plan

> **For agentic workers:** REQUIRED EXECUTION ROUTE: use approved Pipeline v2 multi-task batches. Do **not** invoke `superpowers:subagent-driven-development` or `superpowers:executing-plans`; their handoffs and per-task-review workflow are overridden. Workers receive the zero-assumption contract, do not edit `progress.md` or spawn helpers, and return only `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `PLAN_CONFLICT`, or `BLOCKED`. **Review gate: final-only.** No Phase 4 task/phase reviewer is authorized; the verified phase immediately enters the mandatory two-reviewer master gate.

**Goal:** Reuse Phase 2’s real-agent evidence, add only eight genuinely uncovered fresh-agent dispatches, complete A-01–A-20 evidence, and produce honest performance, limitation, recovery, and master-review evidence.

**Architecture:** Committed worker stimuli contain facts only. A separate local controller-only oracle file maps those stimuli to A-IDs and pass/fail predicates; an extractor can emit only the selected stimulus. Raw output is one immutable file per dispatch. The controller validates raw evidence and Phase 1/3 mechanical results, then writes summaries/matrix rows without substituting summaries for raw output.

**Tech Stack:** Markdown fixtures/evidence, Python 3.11 standard library, installed `superpowers:writing-skills`, Pipeline helper `unittest`, existing validation/mutation/Craft gates, Git/Git worktrees.

**Spec:** `docs/superpowers/specs/2026-09-08-pipeline-rebuild-v2-design.md`

<!-- pipeline-v2-phase: id=04; deps=01,02,03; review_gate=final-only; review_reason=Phase 4 is acceptance evidence and mandatory-master-review preparation; no ordinary phase review is authorized. -->

## Global constraints

- Phase 4 begins only after Phases 1–3 are integrated/verified and Phase 1/2 required gates are accepted. D-001 through D-010 are binding.
- The global `worker_limit=3` covers pressure agents, implementers, fixers, and reviewers. Controllers own state/consolidation and never cause a fourth worker or nested dispatch.
- Phase 2 P2-T01/P2-T08’s **six identical RED/GREEN full-pressure pairs** and **at least five plus five unresolved-choice wording micro-tests** are reused as evidence. Phase 4 does not re-run those scenarios.
- Phase 4 makes **exactly 8 new actual-agent dispatches**: R01–R04 control/v2 pairs. They run in four waves: R01-control/R02-control/R03-control (3); R01-v2/R02-v2/R03-v2 (3); R04-control (1); R04-v2 (1). A v2 arm never receives a control output; each pair uses separate fresh contexts and the same integrated HEAD/stimulus. No more than three agents are active.
- A control that follows safe behavior is `NON_DISCRIMINATING`, not proof that v2 taught it. A v2 failure/question/evidence contradiction leaves its A-ID unmet and follows the approved TDD/systematic-repair route.
- Evidence classes are `ACTUAL_AGENT`, `AUTOMATED`, `HISTORICAL`, or `UNAVAILABLE`. Worker closing prose is not acceptance proof.
- Runtime evidence is local/ignored and survives only the same workspace’s compaction. Do not stage run artifacts; never push, publish, create a PR, or merge into `main`/`master`.

## Exact artifacts and interfaces

| Exact path | Owner/action |
| --- | --- |
| `plugins/superb/skills/pipeline/tests/fixtures/pressure/phase-04-worker-stimuli.md` | Committed facts-only input catalog; create/commit in P4-01. |
| `plugins/superb/skills/pipeline/tests/fixtures/pressure/extract_phase04_stimulus.py` | Committed stdlib extractor; create/commit in P4-01. Reads only the worker catalog and emits one named stimulus. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/phase-04-controller-oracles.md` | Controller-only A-ID/predicate definitions; create locally in P4-01; never provide/read by a worker. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r01-control-01.md`, `p4-r01-v2-01.md` | Raw actual outputs for R01. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r02-control-01.md`, `p4-r02-v2-01.md` | Raw actual outputs for R02. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r03-control-01.md`, `p4-r03-v2-01.md` | Raw actual outputs for R03. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r04-control-01.md`, `p4-r04-v2-01.md` | Raw actual outputs for R04. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/phase-04-reused-p2-index.md` | Controller index to the six P2 pair files and 5+5 micro-test files; exact paths/hashes and A-ID mapping; local only. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/phase-04-automated-evidence.md` | Fresh command/class/HEAD/elapsed/exit evidence; local only. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/acceptance-matrix.md`, `recovery-finish-rehearsal.md`, `performance.md`, `limitations.md` | Controller summaries; local only; each references raw paths rather than replacing them. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/remote-baseline-before-implementation.md` | Optional, externally pre-existing baseline of read-only remote refs. P4-05 may consume but must never create/backdate it. |
| `docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/master-review-package.md` | Controller-owned final package; local only. |

Raw report interface, required once per dispatch:

```markdown
# P4-R01-CONTROL-01
- Evidence class: ACTUAL_AGENT
- Stimulus ID/SHA-256: R01/<digest>; base/HEAD: <sha>/<sha>
- Supplied files: <worker-visible paths only>
- Worker status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | PLAN_CONFLICT | BLOCKED
- Observed artifact/Git/command paths: <paths>
- Raw response: <verbatim>
```

The controller summary adds the oracle result and A-ID mapping. Worker-visible files never contain strings `controller-only`, `ORACLE:`, `expected-result:`, `PASS`, `FAIL`, or an A-ID-to-predicate mapping.

## A-01–A-20 mapping

| ID | Required behavior | Primary evidence |
| --- | --- | --- |
| A-01 | Unanswered discovery question asks user; no default. | P2 unresolved-choice pair plus 5+5 micro-tests. |
| A-02 | Planner escalates unspecified interface. | P4 R01 pair. |
| A-03 | Implementer `NEEDS_CONTEXT` gets cited answer or user escalation. | P4 R01 pair plus Phase 1 import regression. |
| A-04 | Fixer with two unspecified behaviors asks. | P4 R01 pair. |
| A-05 | Recorded answer survives compaction/reuse. | P4 R02 pair. |
| A-06 | Master/all phase plans precede implementation. | P4 R03 pair and file audit. |
| A-07 | Context loss recovers next action from files. | P4 R02 pair and reconciliation regression. |
| A-08 | Post-commit interruption reconciles once. | P2 post-commit pair plus Phase 1 reconciliation regression. |
| A-09 | Multi-task batch preserves complete/running/blocked/unstarted. | P4 R02 pair plus Phase 1 regression. |
| A-10 | Simultaneous reports cannot corrupt/overwrite tracker. | Phase 1 real-process atomic/import regression. |
| A-11 | Twelve independent tasks batch safely, not mandatory sequential fresh agents. | P4 R03 pair plus scheduler regression. |
| A-12 | Dependent shared-file tasks do not conflict in parallel. | P2 conflicting-scope pair plus scheduler regression. |
| A-13 | Normal phase verifies/continues without formal phase review. | P2 final-only/required pair plus gate regression. |
| A-14 | High-risk phase blocks dependents until review passes. | P2 final-only/required pair plus gate regression. |
| A-15 | All phases route to mandatory master review. | P4 R04 pair and P4-08 package. |
| A-16 | Reports consolidate before fix dispatch. | P4 R04 pair plus gate regression. |
| A-17 | Repository-changing fixes require re-review. | Phase 1 gate/remediation regression. |
| A-18 | Failing implementation gate leaves phase unfinished. | Phase 1 gate/remediation regression. |
| A-19 | Explicit coverage policy enforced; missing policy not invented. | P4 R03 pair. |
| A-20 | Clean committed feature branch; no push/PR/publish/main merge. | P2 remote-refusal pair plus P4-05 local/remote-baseline audit. |

## Batches

P4-01 is sequential foundation. P4-02 is controller-only reuse. P4-03 dispatches R01/R02/R03 exactly as the first two three-worker waves; P4-04 dispatches R04 exactly as two one-worker waves. P4-05 through P4-08 are controller-only and sequential. This is the entire new-dispatch budget: **8**.

### P4-01 — Separate worker stimuli from controller oracles

<!-- pipeline-v2-task: id=P4-01; deps=none; batch=pressure-foundation; order=1; write_scope=plugins/superb/skills/pipeline/tests/fixtures/pressure/phase-04-worker-stimuli.md,plugins/superb/skills/pipeline/tests/fixtures/pressure/extract_phase04_stimulus.py,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/phase-04-controller-oracles.md -->

**Files:** Create exactly the three named paths.

**Consumes / produces:** Consumes approved A-01–A-20 behavior; produces facts-only R01–R04 worker stimuli and controller-only oracle sections. The extractor interface is `python3.11 .../extract_phase04_stimulus.py R01` → only R01 facts on stdout, exit 2 for unknown ID.

**Behavior:** R01 covers planner/implementer/fixer escalation (A-02–A-04); R02 covers recorded decision, compaction, recovery, and multi-task state (A-05/A-07/A-09); R03 covers plan-before-implementation, twelve-task batching, and missing coverage policy (A-06/A-11/A-19); R04 covers master routing and consolidation-before-fix (A-15/A-16). Controller oracles contain predicates; the worker catalog does not.

- [ ] **RED:** Write extractor tests/check commands before its implementation:

  ```bash
  python3.11 plugins/superb/skills/pipeline/tests/fixtures/pressure/extract_phase04_stimulus.py R01 > /tmp/p4-r01-stimulus.md
  ```

  Expected: nonzero before the extractor exists.

- [ ] **GREEN:** Implement a stdlib-only exact-heading extractor that opens only `phase-04-worker-stimuli.md`, emits one `## RNN` block, and has no oracle-file path/import/string.

- [ ] **Leak/placeholder check:**

  ```bash
  for id in R01 R02 R03 R04; do python3.11 plugins/superb/skills/pipeline/tests/fixtures/pressure/extract_phase04_stimulus.py "$id" > "/tmp/$id.md" || exit 1; done &&
  ! rg -n 'controller-only|ORACLE:|expected-result:|A-[0-9]{2}[[:space:]]*[-=:]|[|][[:space:]]*PASS[[:space:]]*[|]|[|][[:space:]]*FAIL[[:space:]]*[|]|T[B]D|TO[D]O|<[^>]+>' /tmp/R0[1-4].md &&
  test "$(rg -n '^## R0[1-4]$' plugins/superb/skills/pipeline/tests/fixtures/pressure/phase-04-worker-stimuli.md | wc -l)" -eq 4 &&
  test "$(rg -n '^## R0[1-4]$' docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/phase-04-controller-oracles.md | wc -l)" -eq 4
  ```

  Expected: success; each worker input is stimulus only, every oracle is controller-only, and no placeholder/leak survives.

- [ ] **Commit only worker-visible inputs:**

  ```bash
  git add plugins/superb/skills/pipeline/tests/fixtures/pressure/phase-04-worker-stimuli.md plugins/superb/skills/pipeline/tests/fixtures/pressure/extract_phase04_stimulus.py
  git commit -m "test(pipeline): isolate phase four pressure stimuli"
  ```

### P4-02 — Index, validate, and reuse Phase 2 actual-agent evidence

<!-- pipeline-v2-task: id=P4-02; deps=P4-01; batch=phase-04-reuse; order=1; write_scope=docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/phase-04-reused-p2-index.md -->

**Files:** Create only the named local index.

**Consumes / produces:** Consumes P2-T01’s six `p2-red-*.md`, P2-T08’s six `p2-green-*.md`, five-or-more `p2-micro-no-guidance-*.md`, and five-or-more `p2-micro-v2-guidance-*.md`. Produces exact resolved paths, SHA-256s, fresh-worker IDs, scenario names, results, and mapping for A-01 (unresolved choice plus 5+5), A-07 (malformed/resume safety support), A-08, A-12, A-13/A-14, and A-20.

**Acceptance:** The index proves controls precede matching green reports and micro-tests have a manually recorded 5+5 comparison. It does not re-run an identical P2 scenario or replace its raw evidence with prose.

- [ ] **Verify exact reusable inventory:**

  ```bash
  test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p2-red-*.md' -type f | wc -l)" -eq 6 &&
  test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p2-green-*.md' -type f | wc -l)" -eq 6 &&
  test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p2-micro-no-guidance-*.md' -type f | wc -l)" -ge 5 &&
  test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p2-micro-v2-guidance-*.md' -type f | wc -l)" -ge 5
  ```

  Expected: success; missing/mismatched/unclear P2 evidence is `PLAN_CONFLICT`, not a resample.

- [ ] **Write the index and validate raw references.**

  Run:

  ```bash
  rg -n 'A-01|A-08|A-12|A-13|A-14|A-20|sha256|p2-red-|p2-green-|p2-micro-' docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/phase-04-reused-p2-index.md
  ```

  Expected: every reused mapping names its raw P2 files and no P4 dispatch occurs.

### P4-03 — Dispatch three uncovered fresh-context pairs

<!-- pipeline-v2-task: id=P4-03; deps=P4-01,P4-02; batch=phase-04-fresh; order=1; write_scope=docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r01-control-01.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r01-v2-01.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r02-control-01.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r02-v2-01.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r03-control-01.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r03-v2-01.md -->

**Files:** Create exactly the six listed raw output files, one per dispatch.

**Consumes / produces:** Consumes P4-01 extractor. Produces six immutable raw reports: R01-control/v2, R02-control/v2, R03-control/v2. Controller-only oracles are read after raw reports land, never put in a worker prompt.

**Acceptance:** Wave 1 has exactly R01/R02/R03 controls; wave 2 has exactly their v2 counterparts, each with a new worker and no control output. Every raw report uses stable attempt identity, input digest, supplied worker-visible paths, verbatim output, status, and artifact evidence.

- [ ] **RED wave:** Extract R01/R02/R03, hash each, and dispatch three fresh general agents without Pipeline instructions. Atomically persist only their individual raw files.

- [ ] **GREEN wave:** Dispatch three separate fresh agents with the same extracted stimuli plus `SKILL.md` and the applicable active v2 reference(s), but no controller oracle/control report. Persist only the matching individual raw files.

- [ ] **Raw-output check:**

  ```bash
  for f in p4-r01-control-01.md p4-r01-v2-01.md p4-r02-control-01.md p4-r02-v2-01.md p4-r03-control-01.md p4-r03-v2-01.md; do
    test -s "docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/$f" || exit 1
  done
  test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p4-r0[1-3]-*-01.md' -type f | wc -l)" -eq 6
  ```

  Expected: six and only six named raw outputs; summaries may cite them but cannot substitute for them.

### P4-04 — Dispatch the uncovered master-flow pair

<!-- pipeline-v2-task: id=P4-04; deps=P4-03; batch=phase-04-fresh; order=2; write_scope=docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r04-control-01.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r04-v2-01.md -->

**Files:** Create exactly the two listed raw output files.

**Consumes / produces:** Consumes R04 stimulus and controller-only R04 oracle. Produces R04-control then separate R04-v2 raw output, covering A-15/A-16 without duplicating P2’s final-only/required decision sample.

**Acceptance:** The control is one fresh general agent. After its output is persisted, the v2 arm is one separate fresh agent with only R04 stimulus plus active v2 references. Neither receives predicate, A-ID mapping, or the other report. No task reviewer/fixer is dispatched.

- [ ] **RED then GREEN:** Dispatch/persist R04-control-01; then dispatch/persist R04-v2-01. Record worker IDs and stimulus SHA-256 in each raw report.

- [ ] **Check dispatch budget and files.**

  ```bash
  test -s docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r04-control-01.md &&
  test -s docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/p4-r04-v2-01.md &&
  test "$(find docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output -maxdepth 1 -name 'p4-r0[1-4]-*-01.md' -type f | wc -l)" -eq 8
  ```

  Expected: exactly eight new actual-agent outputs across P4-03/P4-04.

### P4-05 — Validate automated transitions, recovery, and remote evidence limits

<!-- pipeline-v2-task: id=P4-05; deps=P4-04; batch=phase-04-consolidation; order=1; write_scope=docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/phase-04-automated-evidence.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/recovery-finish-rehearsal.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/limitations.md -->

**Files:** Create only the three named local summaries.

**Consumes / produces:** Consumes raw P2/P4 reports and Phase 1 tests. Produces fresh automated evidence for A-03/A-07–A-10/A-11–A-14/A-16–A-18 plus a rehearsal and limitation record.

**Acceptance:** Mechanical rules are primarily helper tests, not pressure prose. Compare remote refs only with the pre-implementation baseline if it exists; otherwise label the no-push/PR/publish remote-state subclaim `UNAVAILABLE` and never assert it was proven.

- [ ] **Run direct mechanical evidence.**

  ```bash
  python3.11 -m unittest plugins.superb.skills.pipeline.tests.test_pipeline_state.AtomicMutationTest plugins.superb.skills.pipeline.tests.test_pipeline_state.WorkerResultImportTest plugins.superb.skills.pipeline.tests.test_pipeline_state.ReconciliationTest plugins.superb.skills.pipeline.tests.test_pipeline_state.SchedulerReadinessTest plugins.superb.skills.pipeline.tests.test_pipeline_state.PhaseGateAndRemediationTest -v
  ```

  Expected: PASS; record command, class results, HEAD, platform, elapsed time, and linked A-IDs. A named absent class is `PLAN_CONFLICT`.

- [ ] **Perform read-only remote comparison or disclose inability.**

  Run:

  ```bash
  git ls-remote --heads --tags origin > /tmp/p4-remote-current.txt
  ```

  Expected: no remote mutation. If `origin` is absent or this read-only command cannot obtain refs, record that as `UNAVAILABLE`. If the persisted baseline exists, compare its normalized refs to `/tmp/p4-remote-current.txt` and record equal/different refs. If it does not exist, record in `limitations.md`: “No persisted pre-implementation remote-ref baseline exists; remote non-mutation cannot be proven from Phase 4.” Do not create/backdate a baseline and do not claim A-20’s remote subclaim PASS.

- [ ] **Rehearsal check:** Record file-first source order, exact post-commit result reconciliation, batch task states, final-only transition, and master-gate next action. Cite raw or automated files for every statement.

### P4-06 — Consolidate the complete acceptance matrix and full verification

<!-- pipeline-v2-task: id=P4-06; deps=P4-05; batch=phase-04-consolidation; order=2; write_scope=docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/acceptance-matrix.md -->

**Files:** Create only `acceptance-matrix.md` locally.

**Consumes / produces:** Consumes all raw P2/P4 reports, P4-05 output, plans, decisions, and Git evidence. Produces exactly 20 controller-validated rows; a row always references at least one raw/automated evidence path.

**Acceptance:** `PASS` requires its mapping’s evidence and validation. `NON_DISCRIMINATING`/`UNAVAILABLE` remain visible. A missing remote baseline prevents claiming the A-20 remote non-mutation subclaim proven; it is not repaired by `git remote -v`.

- [ ] **Run fresh full verification.**

  ```bash
  python3.11 -m unittest discover -s plugins/superb/skills/pipeline/tests -v &&
  ./tools/check-plugin.sh &&
  ./tools/check-plugin-mutants.sh &&
  python3 -m unittest discover -s plugins/superb/skills/craft/tests -v &&
  ./tools/test-craftui.sh &&
  git diff --check &&
  test -z "$(git status --porcelain --untracked-files=all --ignored=no)"
  ```

  Expected: all pass on integrated HEAD; failure keeps the phase unfinished.

- [ ] **Matrix/raw-reference check.**

  ```bash
  test "$(rg -n '^[|] A-(0[1-9]|1[0-9]|20) [|]' docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/acceptance-matrix.md | wc -l)" -eq 20 &&
  for f in p4-r01-control-01.md p4-r01-v2-01.md p4-r02-control-01.md p4-r02-v2-01.md p4-r03-control-01.md p4-r03-v2-01.md p4-r04-control-01.md p4-r04-v2-01.md; do rg -q "$f" docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/acceptance-matrix.md || exit 1; done &&
  ! rg -n '^[|] A-[0-9]{2} [|].*[|] PASS [|].*[|] *$' docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/acceptance-matrix.md
  ```

  Expected: all twenty rows and all eight raw outputs are cited; no PASS has an empty validation/evidence field.

- [ ] **Record Phase 4 verification** through the controller only after these checks pass. Persist `final-only`; do not open a Phase 4 review gate.

### P4-07 — Report comparable performance and limitations

<!-- pipeline-v2-task: id=P4-07; deps=P4-06; batch=phase-04-consolidation; order=3; write_scope=docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/performance.md,docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/limitations.md -->

**Files:** Create `performance.md`; append only performance/platform/remote-evidence limits to `limitations.md`.

**Consumes / produces:** Consumes P4-05/06 evidence and historical Phase seam (3 arms), Wave seam (7 arms), compact study (3 RED/3 GREEN), and mailbox observations. Produces a table with metric, v2 command/scenario, v2 value, historical source, comparability, and claim.

**Acceptance:** Measure helper/test elapsed, mutation-suite runs, Phase 4 actual dispatch count (exactly 8), heavy-verification count, orchestrator turns, and SKILL word/line size. Historical values are `HISTORICAL`; non-like-for-like comparison is `N/A`; wait-for-user time is separate. No speed claim lacks same-workload source.

- [ ] **Measure reproducibly.**

  ```bash
  git show 8348959d1b201a873c68512642a0eb8e5754eaa8:plugins/superb/skills/pipeline/SKILL.md | wc -wl &&
  wc -wl plugins/superb/skills/pipeline/SKILL.md &&
  git rev-parse HEAD &&
  python3.11 --version
  ```

  Expected: record environment and current/base identities; time P4-06 commands once on this HEAD.

- [ ] **Claim check.**

  ```bash
  ! rg -n 'faster|speedup|reduced|improved performance' docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/performance.md ||
  rg -n 'same workload|comparable source' docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/performance.md
  ```

  Expected: no unsupported performance claim; Linux/macOS/Windows and remote-baseline limitations are distinct.

### P4-08 — Final-only completion and exact master-gate handoff

<!-- pipeline-v2-task: id=P4-08; deps=P4-07; batch=phase-04-consolidation; order=4; write_scope=docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/master-review-package.md -->

**Files:** Create only `agent-output/master-review-package.md` locally.

**Consumes / produces:** Consumes Phase 4 verification, matrix, raw evidence, performance/limitations, D-005–D-007, and HEAD. Produces the master package; it is not a Phase 4 review.

**Acceptance:** No blocker/question/failed required check exists; all limitations are disclosed. Package records base `8348959d1b201a873c68512642a0eb8e5754eaa8`, exact integrated HEAD, every A-ID/evidence path, and complementary reviewer scopes.

- [ ] **Mandatory master-gate handoff:** After Phase 4 verification, record review base `8348959d1b201a873c68512642a0eb8e5754eaa8` and current integrated HEAD. Dispatch **exactly two** independent complementary D-007 reviewers over the same range: Reviewer A covers approved design/plan, behavior, assumptions, correctness/error paths, and decisions; Reviewer B covers integration, architecture, recovery/persistence/concurrency/security, regressions, and test quality. Dispatch concurrently only if active workers remain at most 3. Save raw reports at `agent-output/master-review-a.md` and `agent-output/master-review-b.md`. Collect both, validate/deduplicate findings, ask unresolved questions, persist one `fix-plan-<gate>-r<n>.md` before compatible TDD fix batches, verify, and re-review the **same** gate. Stop only on D-005 acceptance or D-006 block/escalation. Ordinary fixes do not restart the pipeline.

- [ ] **Handoff check.**

  ```bash
  git rev-parse 8348959d1b201a873c68512642a0eb8e5754eaa8 &&
  git rev-parse HEAD &&
  rg -q 'Reviewer A' docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/master-review-package.md &&
  rg -q 'Reviewer B' docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/master-review-package.md &&
  rg -q 'exactly two' docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/agent-output/master-review-package.md
  ```

  Expected: master gate may start; final acceptance remains prohibited until both reports, remediation/re-reviews, and final verification satisfy D-005/D-006.

## Verification and review classification

**Mechanical verification:** P4-05 direct helper evidence; P4-06 full repository commands, all 20 matrix rows, raw-reference check, Git cleanliness, recovery rehearsal, remote-baseline comparison or explicit inability; P4-07 performance/limitations check.

**Review gate:** `final-only`. P4-08 is the immediate mandatory master-gate handoff, not a Phase 4 review.

**Plan self-check:** Eight stable tasks (under 12); strict metadata comments; dependencies/batches/writes are explicit; exactly eight new fresh-agent dispatches; P2 six pairs and 5+5 micro-tests are reused without resampling; all A-01–A-20 are mapped; only P4-01 commits worker-visible fixtures; all runtime evidence remains ignored.
