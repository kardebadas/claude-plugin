# Pipeline Rebuild v2 — Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED EXECUTION ROUTE: use the approved Pipeline v2 controller and its multi-task batches. Do not invoke superpowers:subagent-driven-development or superpowers:executing-plans. V2 batches replace their handoff and no task receives formal review; progress.md is the sole live tracker.

**Goal:** Preserve shared Superb plugin checks while replacing V1-only Pipeline validation with V2 helper, fixture, mutation, CI, setup, package, and user-documentation coverage.

**Architecture:** tools/check-plugin.py remains the repository-wide structural gate, but Phase 1's Python helper suite owns V2 tracker parsing and fixture semantics. The mutation harness keeps its clean-copy/no-op-aware method. CI invokes the V2 unit/integration suite, while setup and docs distinguish Pipeline Python 3.11+ from Craft Python 3.9+.

**Tech Stack:** Python 3.11+ standard library and unittest, Bash, GitHub Actions YAML, JSON, Markdown.

**Spec:** docs/superpowers/specs/2026-09-08-pipeline-rebuild-v2-design.md

<!-- pipeline-v2-phase: id=03; deps=01,02; review_gate=final-only; review_reason=Repository validation, packaging, and documentation are mechanically verified here; formal acceptance occurs only at the final master gate. -->

## Global constraints

- Dependencies: Phases 1 and 2 must be integrated, mechanically verified, and accepted at their required gates.
- Binding decisions: D-001 through D-010 in docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/decisions.md, especially D-002, D-003, D-009, and D-010.
- Preserve unrelated shared checks: UTF-8/frontmatter, namespace/marketplace/manifests, placeholder protection, shared brief, executable scripts, agents, leakage scan, and narrow run-directory ignore policy.
- Delete V1-only RV/RVJ, lanes, ceil(N/5), M/C reviewer arithmetic, --run tracker linting, V1 fixture calls, recursive fix-mode, and task-brief assumptions. Do not add compatibility behavior for them.
- The V2 helper is Python 3.11+ and standard-library-only. Preserve Craft UI/source/test Python 3.9+ support and its existing floor test.
- Add no numeric coverage threshold. Every mutation proves it changed its target; a failed anchor/precondition is NO-OP, never a kill.
- Review gate: final-only. Do not dispatch a Phase 3 formal reviewer. The two-reviewer master gate remains after Phase 4.
- No push, PR, publish, merge, or staging of docs/superpowers/runs/2026-09-08-pipeline-rebuild-v2/.

## Stable tasks, writes, and batches

| ID | Batch | Depends on | Write scope | Batch compatibility |
| --- | --- | --- | --- | --- |
| P3-T01 | P3-validation | phase IDs 01,02 | tools/check-plugin.py; tools/check-plugin.sh | Implements validator against controlled prerequisites; full release gate is intentionally still red in the worktree. |
| P3-T02 | P3-validation | P3-T01, P3-T03, P3-T06 | tools/check-plugin-mutants.sh | Runs only after CI/manifests make the complete clean baseline conforming. |
| P3-T03 | P3-ci | P3-T01 | .github/workflows/checks.yml | Owns only workflow edits and a task-local workflow audit; does not edit P3-T01 files. |
| P3-T04 | P3-setup | phase IDs 01,02 | plugins/superb/skills/setup/check-deps.sh, SKILL.md, README.md | May run in parallel with P3-T05/P3-T06. |
| P3-T05 | P3-docs | phase IDs 01,02 | README.md; plugins/superb/README.md | May run with P3-T04/P3-T06; integrate before phase verification. |
| P3-T06 | P3-package | P3-T03; phase ID 02 | both plugin.json manifests | Lands the final structural prerequisite; complete release baseline runs here before P3-T02. |

The phase comment owns cross-phase dependencies 01,02. Each task comment therefore lists only same-phase task IDs (or none) in its required deps field; no task metadata invents a pseudo task ID for a phase.

## File map

| Path | Phase-3 responsibility |
| --- | --- |
| tools/check-plugin.py | Retain shared checks; replace V1 Pipeline parser/linter with narrow V2 release-shape, version, and CI checks. |
| tools/check-plugin.sh | Default structural-gate wrapper only; retired --run is rejected as an unknown argument. |
| tools/check-plugin-mutants.sh | Keep shared clean-copy mutations; replace V1 tracker/lane mutants with V2 structural and CI mutants. |
| .github/workflows/checks.yml | Run V2 suite and default gates; remove V1 fixture --run commands. |
| plugins/superb/skills/setup/* | Report Pipeline Python requirement without installing a runtime; preserve Craft scope. |
| README.md; plugins/superb/README.md | Explain V2 operation, limits, verification, and commands. |
| plugins/superb/.claude-plugin/plugin.json; plugins/superb/.codex-plugin/plugin.json | Exact approved 0.14.0 version and V2-aligned Pipeline wording. |

### Task P3-T01: Replace V1 Pipeline validation with a narrow V2 release gate
<!-- pipeline-v2-task: id=P3-T01; deps=none; kind=source; batch=P3-validation; order=1; write_scope=file:tools/check-plugin.py,file:tools/check-plugin.sh; outputs=none -->

**Files:**

- Modify: tools/check-plugin.py (argument handling; V1 Pipeline sections currently beginning at the “pipeline RV/RVJ examples” block through end-of-file).
- Verify unchanged shared sections: tools/check-plugin.py lines 52–1232; re-home the existing .gitignore check before deleting the V1 semantic block.
- Verify interface unchanged: tools/check-plugin.sh lines 1–3.

**Interfaces:**

- Consumes Phase 1: plugins/superb/skills/pipeline/scripts/pipeline_state.py, tests/test_pipeline_state.py, tests/fixtures/.
- Consumes Phase 2: SKILL.md, README.md, references/planning.md, references/execution.md, references/persistence.md, references/review.md, and templates/progress.md, decisions.md, findings.md, fix-plan.md, worker-result.md.
- Produces default-only ./tools/check-plugin.sh: exit 0 only after shared checks, V2 release inventory, V2 template marker, exact manifest version, and exact CI-command audit pass. P3-T01 proves its new predicates against a controlled throwaway conforming tree; it does not require the live tree to pass before P3-T03/P3-T06 land.
- Produces no duplicate tracker parser, --run mode, V1 fixture validation, reviewer arithmetic, or task-brief dependency.

**Acceptance behavior:**

- Keep every shared check named in Global constraints.
- Preserve the existing run-artifacts ignore check verbatim in behavior: docs/superpowers/runs/*/ remains ignored, while curated specs, plans, and loose runs/*.md records remain trackable. Re-home that shared check above the deleted V1 Pipeline semantic section; do not delete it merely because its current source location follows V1 code.
- Remove V1 code for lint_review_lines, lanes/current state, RV/RVJ pins, task-brief ownership, phase-review state, and real-run --run handling.
- Require this V2 inventory: SKILL.md, README.md, references/{planning,execution,persistence,review}.md, scripts/pipeline_state.py, templates/{progress,decisions,findings,fix-plan,worker-result}.md, tests/test_pipeline_state.py, tests/fixtures/.
- Require pipeline-run/v2 in the progress template, both manifests at 0.14.0, and P3-T03's complete CI contract: uses: actions/setup-python@v5, python-version: '3.11', then python -m unittest discover -s plugins/superb/skills/pipeline/tests -v.
- Retired --run is an unknown argument (exit 2), so it cannot read or mutate V1 fixtures.

- [ ] **Step 1: Write failing V2 structural assertions**

  Add required_pipeline_paths and require these exact ordered CI fragments:

      uses: actions/setup-python@v5
      python-version: '3.11'
      python -m unittest discover -s plugins/superb/skills/pipeline/tests -v

  Keep diagnostics naming each missing path, marker, version, or command.

- [ ] **Step 2: Run RED**

  Run: ./tools/check-plugin.sh

  Expected: FAIL after Phase 2 has deleted V1 tracker/task-brief contracts; it must not green from obsolete RV/RVJ/lane examples.

  Run: ./tools/check-plugin.sh --run tools/fixtures/run-ok

  Expected: exit 2 with unknown argument '--run'; no fixture change.

- [ ] **Step 3: Implement the minimum gate**

  Keep the strict argument guard and shared sections. First move the existing narrow .gitignore validation intact into the retained shared area; then delete V1 Pipeline semantic blocks as a unit and add only inventory, marker, exact-version, and CI-command checks. Phase 1 remains the authority for malformed schema, transitions, locks, scheduling, results, and fixtures.

- [ ] **Step 4: Run task-local GREEN against controlled prerequisites and retain live RED**

  Run: ./tools/check-plugin.sh

  Expected: nonzero only for the still-unimplemented P3-T03 CI and/or P3-T06 manifest prerequisites; a different failure blocks P3-T01.

  Run the gate in a guarded throwaway conforming copy:

  ```bash
  task_tmp=$(mktemp -d)
  cp -a . "$task_tmp/repo"
  python3.11 - "$task_tmp/repo" <<'PY'
  import json
  import sys
  from pathlib import Path

  root = Path(sys.argv[1])
  for relative in ("plugins/superb/.claude-plugin/plugin.json", "plugins/superb/.codex-plugin/plugin.json"):
      path = root / relative
      data = json.loads(path.read_text(encoding="utf-8"))
      if data.get("version") != "0.13.0":
          raise SystemExit(f"no-op guard failed: {relative} baseline version")
      data["version"] = "0.14.0"
      path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
  workflow = root / ".github/workflows/checks.yml"
  text = workflow.read_text(encoding="utf-8")
  start = "      # `--run` is a second mode"
  end = "      - run: ./tools/check-plugin-mutants.sh"
  if text.count(start) != 1 or text.count(end) != 1:
      raise SystemExit("no-op guard failed: v1 CI block")
  replacement = (
      "      - uses: actions/setup-python@v5\n"
      "        with:\n"
      "          python-version: '3.11'\n"
      "      - run: python -m unittest discover -s plugins/superb/skills/pipeline/tests -v\n"
  )
  workflow.write_text(text[:text.index(start)] + replacement + text[text.index(end):], encoding="utf-8")
  PY
  (cd "$task_tmp/repo" && ./tools/check-plugin.sh)
  task_status=$?
  rm -rf "$task_tmp"
  test "$task_status" -eq 0
  ```

  Expected: `check-plugin: PASS` in the controlled copy, proving P3-T01's predicates without editing live P3-T03/P3-T06 files. The live failure remains expected until their tasks integrate.

  Run: before=$(git hash-object tools/fixtures/run-ok/progress.md); ./tools/check-plugin.sh --run tools/fixtures/run-ok >/tmp/p3-t01.out 2>&1; rc=$?; after=$(git hash-object tools/fixtures/run-ok/progress.md); test "$rc" -eq 2 && test "$before" = "$after" && rg -F "unknown argument '--run'" /tmp/p3-t01.out

  Expected: shell assertion passes; rejected V1 input is read-only.

- [ ] **Step 5: Commit**

      git add tools/check-plugin.py tools/check-plugin.sh
      git commit -m "test(pipeline): validate v2 release structure"

### Task P3-T02: Replace V1 mutations with no-op-aware V2 mutations
<!-- pipeline-v2-task: id=P3-T02; deps=P3-T01,P3-T03,P3-T06; kind=source; batch=P3-validation; order=2; write_scope=file:tools/check-plugin-mutants.sh; outputs=none -->

**Files:**

- Modify: tools/check-plugin-mutants.sh (retain clean-copy framework and applicable shared mutants; replace V1 run-fixture/RV/RVJ/lane families).

**Interfaces:**

- Consumes P3-T01's validator plus integrated P3-T03 CI and P3-T06 manifests; its clean live baseline must now pass before mutation.
- Produces ./tools/check-plugin-mutants.sh exit 0 only if the clean baseline passes, every mutation changed its target and was killed, and there are zero SURVIVED/NO-OP results.
- Required V2 mutant names and targets: remove pipeline_state.py; change pipeline-run/v2; remove references/execution.md; set one manifest to 0.13.0; remove actions/setup-python@v5; remove the exact Pipeline CI command; insert retired check-plugin.sh --run into CI.

**Acceptance behavior:**

- Preserve throwaway-copy-only behavior; never restore or write the user tree.
- Delete all V1 fixture baseline, helper, and mutation logic, because Phase 1 fixture tests preserve V2 behavior.
- Each new mutation guards its anchor, announces mutant is a no-op if absent, and replaces the target with a deliberately different value.

- [ ] **Step 1: Write a failing desired-inventory audit, then the V2 mutation cases**

  Before editing, require all seven planned mutation names/anchors in `tools/check-plugin-mutants.sh`; this task-local audit must fail because the old v1 families do not implement them. Do not use the old harness's successful v1 run as RED evidence.

  Example marker mutation:

      run_mutant "v2 template loses schema marker" '
        f=plugins/superb/skills/pipeline/templates/progress.md
        grep -qF -- "pipeline-run/v2" "$f" || { echo "mutant is a no-op: v2 marker absent"; exit 0; }
        sed -i "s/pipeline-run\/v2/pipeline-run\/broken/" "$f"
      '

- [ ] **Step 2: Run RED after confirming the complete clean baseline**

  Run: ./tools/check-plugin.sh

  Expected: PASS because P3-T03 and P3-T06 are dependencies.

  Run the seven-name/anchor inventory audit from Step 1.

  Expected: nonzero until all seven V2 mutations exist. The old mutation harness may still pass its obsolete tests, but that is not this task's GREEN evidence.

- [ ] **Step 3: Implement the V2 mutation set**

  Retain run_mutant, clean baseline, shared mutations, and final nonzero failure for SURVIVED, NO-OP, or bad baseline. Replace only V1-specific families and obsolete fixture helpers with the seven named mutations.

- [ ] **Step 4: Run GREEN and changed-target proof**

  Run: ./tools/check-plugin-mutants.sh

  Expected: check-plugin-mutants: PASS; zero SURVIVED and zero NO-OP.

  Run: task_tmp=$(mktemp -d); cp -a . "$task_tmp/repo"; sed -i 's/pipeline-run\/v2/pipeline-run\/broken/' "$task_tmp/repo/plugins/superb/skills/pipeline/templates/progress.md"; (cd "$task_tmp/repo" && ./tools/check-plugin.sh); rc=$?; rm -rf "$task_tmp"; test "$rc" -ne 0

  Expected: assertion passes. This proves the marker mutation changed its target and the default gate killed it without touching the worktree.

- [ ] **Step 5: Commit**

      git add tools/check-plugin-mutants.sh
      git commit -m "test(pipeline): mutate v2 validation invariants"

### Task P3-T03: Wire V2 tests and gates into CI
<!-- pipeline-v2-task: id=P3-T03; deps=P3-T01; kind=source; batch=P3-ci; order=1; write_scope=file:.github/workflows/checks.yml; outputs=none -->

**Files:**

- Modify: .github/workflows/checks.yml lines 7–38.
- Consumes without edit: plugins/superb/skills/pipeline/tests/ and tools/check-plugin*.{sh,py}.

**Interfaces:**

- Consumes the explicitly provisioned CI command: python -m unittest discover -s plugins/superb/skills/pipeline/tests -v.
- Produces CI that runs that command once, ./tools/check-plugin.sh once, ./tools/check-plugin-mutants.sh once, and no check-plugin.sh --run invocation.

**Acceptance behavior:**

- In the existing plugin job, provision Python with actions/setup-python@v5 and python-version: '3.11' before the Pipeline suite. Replace six V1 fixture --run workflow steps with the exact provisioned-interpreter command. Its valid/invalid/legacy/schema/transition/scheduler/recovery/gate fixtures are owned by the suite.
- Keep the shared plugin gate, mutant harness, craft brief job, Craft UI job, Craft python3 commands, and browser installation/assertion behavior.
- P3-T01's already-implemented audit fails if the exact suite command is absent or --run remains. P3-T03 does not edit that audit.

- [ ] **Step 1: Run the existing command audit as RED**

  Run P3-T01's gate and separately inspect only `.github/workflows/checks.yml` for the exact provisioned-interpreter suite command and absence of `check-plugin.sh --run`. Do not edit `tools/check-plugin.py` or `tools/check-plugin.sh` in this task.

- [ ] **Step 2: Run RED**

  Run: ./tools/check-plugin.sh

  Expected: FAIL naming missing Pipeline suite command and/or a retired --run CI call.

- [ ] **Step 3: Update workflow minimally**

  Retain default structural/mutation steps, add this setup step before the suite, and replace V1 fixture calls with:

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python -m unittest discover -s plugins/superb/skills/pipeline/tests -v

- [ ] **Step 4: Run GREEN**

  Run: python3.11 -m unittest discover -s plugins/superb/skills/pipeline/tests -v

  Expected: Pipeline tests pass. Do not require the complete plugin gate yet: P3-T06's version prerequisite is deliberately still pending, and P3-T02's mutation harness follows it.

  Run: rg -n -F 'uses: actions/setup-python@v5' .github/workflows/checks.yml && rg -n -F "python-version: '3.11'" .github/workflows/checks.yml && test "$(rg -c -F 'python -m unittest discover -s plugins/superb/skills/pipeline/tests -v' .github/workflows/checks.yml)" -eq 1

  Expected: success; task-local CI ownership is verified without calling a later task's release baseline.

  Run: ! rg -n 'check-plugin\.sh --run|run-(ok|open-rv|fixloop|rvj-fix|lanes|leading-rvj-fix)' .github/workflows/checks.yml

  Expected: success; CI has no V1 fixture grammar call.

- [ ] **Step 5: Commit**

      git add .github/workflows/checks.yml
      git commit -m "ci: run pipeline v2 validation suite"

### Task P3-T04: Report Pipeline Python 3.11+ without changing Craft support
<!-- pipeline-v2-task: id=P3-T04; deps=none; kind=source; batch=P3-setup; order=1; write_scope=file:plugins/superb/skills/setup/check-deps.sh,file:plugins/superb/skills/setup/SKILL.md,file:plugins/superb/skills/setup/README.md; outputs=none -->

**Files:**

- Modify: plugins/superb/skills/setup/check-deps.sh lines 93–106.
- Modify: plugins/superb/skills/setup/SKILL.md lines 13–15 and 80–97.
- Modify: plugins/superb/skills/setup/README.md lines 9–44.
- Verify unchanged: plugins/superb/skills/craft/ui/tests/test_python_floor.py lines 1–110.

**Interfaces:**

- Produces REQUIRED pipeline-python OK only when discovered python3 has sys.version_info >= (3, 11); otherwise REQUIRED pipeline-python MISSING and existing required-dependency exit status 1.
- Preserves OPTIONAL python3 as Craft UI reporting; Craft retains Python 3.9+.
- Produces no ACTION that installs/upgrades Python or edits user configuration.

**Acceptance behavior:**

- Determine the floor with sys.version_info, not lexical shell version comparison, and report discovered version on success.
- Missing/below-floor Python reports an unsatisfied Pipeline requirement; setup docs direct reporting that limitation rather than runtime installation.
- Keep superpowers' existing required scope, and keep Craft's separate fallback and floor.

- [ ] **Step 1: Write failing setup check**

  Use the runtime predicate:

      python3 -c 'import sys; raise SystemExit(not (sys.version_info >= (3, 11)))'

  The success branch must emit REQUIRED pipeline-python OK; no-runtime/below-floor branch must emit REQUIRED pipeline-python MISSING and set status 1.

- [ ] **Step 2: Run RED**

  Run: ./plugins/superb/skills/setup/check-deps.sh | rg '^REQUIRED pipeline-python '

  Expected: no match before implementation.

- [ ] **Step 3: Implement narrow report and docs**

  Add the requirement after Craft's optional report, reuse note_worse 1 for unsatisfied status, add no runtime installer action, and revise only stated Pipeline/Craft dependency prose.

- [ ] **Step 4: Run GREEN**

  Run: ./plugins/superb/skills/setup/check-deps.sh; rc=$?; test "$rc" -eq 0 -o "$rc" -eq 1 -o "$rc" -eq 2

  Expected: documented exit status and exactly one pipeline-python line; no installation.

  Run: python3 -m unittest discover -s plugins/superb/skills/craft/ui/tests -p 'test_python_floor.py' -v && rg -n 'Python 3\.9\+' plugins/superb/skills/setup/SKILL.md plugins/superb/skills/setup/README.md

  Expected: Craft floor test and documentation both remain green.

- [ ] **Step 5: Commit**

      git add plugins/superb/skills/setup/check-deps.sh plugins/superb/skills/setup/SKILL.md plugins/superb/skills/setup/README.md
      git commit -m "docs(setup): report pipeline python requirement"

### Task P3-T05: Update user documentation to the V2 contract
<!-- pipeline-v2-task: id=P3-T05; deps=none; kind=source; batch=P3-docs; order=1; write_scope=file:README.md,file:plugins/superb/README.md; outputs=none -->

**Files:**

- Modify: README.md lines 24–76, 115–149, 190–275.
- Modify: plugins/superb/README.md lines 7–19.
- Consumes without edit: Phase 2 Pipeline README, SKILL.md, and four references.

**Interfaces:**

- Produces V2-aligned Pipeline descriptions. No user-facing command may name deleted V1 references, /review, fix-mode, lanes/RV/RVJ, per-task reviewers, or an interactive finishing workflow.

**Acceptance behavior:**

- Explain file-authoritative recovery, v2-only resume/read-only legacy rejection, zero-assumption questions, persisted worker limit, compatible multi-task batches/task checkpoints, mechanical phase verification, final-only versus required formal review, bounded remediation, exactly two final-master reviewers, and no push/PR/merge completion.
- State Pipeline's Python 3.11+ helper and Craft's distinct Python 3.9+ UI support.
- List V2 unittest, default gate, and mutation harness. Do not claim performance without Phase 4 evidence or native Windows verification without native test evidence.
- Preserve non-Pipeline setup, Craft, bug-investigate, bug-fix, installation, namespace, and layout content unless a Pipeline statement needs correction.

- [ ] **Step 1: Write RED scans**

      rg -n 'pipeline-run/v2|Python 3\.11\+|final-only|master review|worker_limit' README.md plugins/superb/README.md
      ! rg -n '/review|fix-mode|RVJ|ceil\(N/5\)|references/(implement|fix-loop|parallel|run-state)\.md' README.md plugins/superb/README.md

- [ ] **Step 2: Run RED**

  Expected: positive scan incomplete and negative scan finds current V1 docs.

- [ ] **Step 3: Rewrite only Pipeline sections**

  Apply the acceptance contract. Keep limitations explicit and do not copy historic V1 details into active docs.

- [ ] **Step 4: Run GREEN**

  Run: rg -n 'pipeline-run/v2|Python 3\.11\+|final-only|master review|worker_limit' README.md plugins/superb/README.md && ! rg -n '/review|fix-mode|RVJ|ceil\(N/5\)|references/(implement|fix-loop|parallel|run-state)\.md' README.md plugins/superb/README.md

  Expected: task-local documentation assertions succeed. Do not require the complete release gate here because this task has no dependency on P3-T03/P3-T06/P3-T02; the strict gate remains in the phase verification after all tasks integrate.

- [ ] **Step 5: Commit**

      git add README.md plugins/superb/README.md
      git commit -m "docs(pipeline): describe v2 workflow"

### Task P3-T06: Ship the approved package version
<!-- pipeline-v2-task: id=P3-T06; deps=P3-T03; kind=source; batch=P3-package; order=1; write_scope=file:plugins/superb/.claude-plugin/plugin.json,file:plugins/superb/.codex-plugin/plugin.json; outputs=none -->

**Files:**

- Modify: plugins/superb/.claude-plugin/plugin.json lines 2–28.
- Modify: plugins/superb/.codex-plugin/plugin.json lines 2–27.
- Verify unchanged: unrelated 0.13.0+codex.20260908074624 cachebuster outside this feature worktree.

**Interfaces:**

- Produces identical JSON string "version": "0.14.0" in both manifests.
- Consumes P3-T01 exact-version check, integrated P3-T03 CI prerequisite, and the approved V2 description language from the design/Phase 2; it has no dependency on the disjoint root-documentation task.
- Does not change plugin name, author, Codex skills path, marketplace source/name, or cachebuster metadata.

**Acceptance behavior:**

- Both files parse as JSON and match the D-010 version exactly, not merely each other.
- Pipeline descriptions identify V2 file-authoritative operation without making other skills undiscoverable.

- [ ] **Step 1: Write failing version assertion**

  P3-T01 must reject current 0.13.0 with a diagnostic requiring 0.14.0.

- [ ] **Step 2: Run RED**

  Run: ./tools/check-plugin.sh

  Expected: FAIL because manifests are not D-010's version even though they match each other.

- [ ] **Step 3: Update only approved values**

      "version": "0.14.0"

  Refresh only Pipeline-related text required to align with the approved design and integrated Phase 2 wording; do not depend on or edit P3-T05 files.

- [ ] **Step 4: Run GREEN and no-unrelated-change proof**

  Run: python3 -m json.tool plugins/superb/.claude-plugin/plugin.json >/dev/null && python3 -m json.tool plugins/superb/.codex-plugin/plugin.json >/dev/null && ./tools/check-plugin.sh

  Expected: both parse and the complete default release gate passes now that CI and manifest prerequisites are integrated. This establishes the clean baseline consumed by P3-T02.

  Run: ! git diff -- plugins/superb/.claude-plugin/plugin.json plugins/superb/.codex-plugin/plugin.json | rg '^[+-].*0\.13\.0\+codex'

  Expected: no output; unrelated cachebuster remains untouched.

- [ ] **Step 5: Commit**

      git add plugins/superb/.claude-plugin/plugin.json plugins/superb/.codex-plugin/plugin.json
      git commit -m "chore(superb): release pipeline v2 metadata"

## Phase integration and mechanical verification

The executable dependency chain is:

1. P3-T01 implements/tests validator predicates in a controlled throwaway conforming tree; the live full gate remains red only for named later prerequisites.
2. P3-T03, depending on P3-T01, edits only `checks.yml` and uses task-local CI/Pipeline-suite checks.
3. P3-T06, depending on P3-T03, updates both manifests and establishes the first complete live `check-plugin.sh` baseline.
4. P3-T02, depending on P3-T01/P3-T03/P3-T06, replaces the mutation inventory and runs it against that conforming baseline.
5. P3-T04/P3-T05 may run alongside compatible parts of this chain, subject to the global limit and typed-scope reservation. All six source tasks must satisfy complete integration ancestry before the phase suite.

After every task is integrated on feat/pipeline-rebuild-v2, run:

    python3.11 -m unittest discover -s plugins/superb/skills/pipeline/tests -v
    ./tools/check-plugin.sh
    ./tools/check-plugin-mutants.sh
    python3 -m unittest discover -s plugins/superb/skills/craft/tests -v
    ./tools/test-craftui.sh
    git diff --check
    git status --short --branch

Expected: every V2 fixture gate and intended failing case is covered by the Phase 1 suite; default validation and all changed-target mutations pass; Craft's Python 3.9 syntax guard remains green; JSON/setup/docs/CI audits pass; no whitespace errors remain; only intended committed feature changes exist. Native macOS/Windows evidence unavailable locally is reported, not claimed.

## Phase gate and handoff

**Review gate: final-only.** Record fresh mechanical evidence in progress.md. Do not request a Phase 3 formal reviewer and do not review tasks individually. Continue only through the approved Pipeline v2 batch scheduler when Phase 4 becomes eligible; after Phase 4, mandatory master review uses exactly the two D-007 reviewers.
