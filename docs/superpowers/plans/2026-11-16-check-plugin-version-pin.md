# check-plugin version pin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `tools/check-plugin.sh` and `tools/check-plugin-mutants.sh` pass at any release version, so a version bump alone never turns CI red again.

**Architecture:** Remove the hard-coded `0.16.0` from the gate and from the one mutant that anchors on it. The existing drift check (`tools/check-plugin.py:158-166`) keeps guarding a missing or mismatched version. A new "release bump" step in the mutants harness proves a bumped copy still passes.

**Tech Stack:** Python 3.11 standard library, bash.

**Spec:** `docs/superpowers/specs/2026-11-16-check-plugin-version-pin.md`

**Executor:** superpowers:subagent-driven-development. Work in the worktree `.claude/worktrees/fix-version-pin`, branch `claude/fix-version-pin`.

## Global Constraints

- No release number may appear in `tools/check-plugin.py` or `tools/check-plugin-mutants.sh` except the mutant's deliberate `0.13.0` and the release-bump step's `99.0.0`.
- Commit subjects follow the repo's style: `test(tools): …`, `fix(tools): …`.
- No `Co-Authored-By` or any attribution trailer; no session link or session id anywhere.
- No absolute home-directory path in any file.

## Review Focus

- Both manifests lose their `version` key: the gate must still FAIL (the drift check's `claude_version and …` guard). Pinned by a new mutant in Task 2.
- One manifest at a different version from the other: the gate must FAIL. Already pinned by the existing "one manifest reverts to 0.13.0" mutant, kept in Task 2.
- Both manifests bumped together to a new version: the gate must PASS. Pinned by Task 1.

---

### Task 1: Regression test — a version bump alone must pass

**Files:**
- Modify: `tools/check-plugin-mutants.sh` (insert before line 76, `echo "baseline (unmutated copy must PASS):"`)

**Interfaces:**
- Consumes: `$SRC`, `$WORK` (defined at lines 9-10); the copy idiom `tar -C "$SRC" --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$DIR" -xf -` used by the baseline.
- Produces: a step that exits the harness with 1 when a bumped copy fails the gate.

- [ ] **Step 1: Insert the release-bump step before the baseline step**

```bash
echo "release bump (both manifests at a version no release used must PASS):"
BUMP="$WORK/bump"
mkdir -p "$BUMP"
tar -C "$SRC" --exclude=.git --exclude=__pycache__ -cf - . | tar -C "$BUMP" -xf -
(cd "$BUMP" && python3 -c "
import json
for p in ('plugins/superb/.claude-plugin/plugin.json', 'plugins/superb/.codex-plugin/plugin.json'):
    d = json.load(open(p)); d['version'] = '99.0.0'; json.dump(d, open(p, 'w'), indent=2)
")
if (cd "$BUMP" && ./tools/check-plugin.sh) >/dev/null 2>&1; then
  echo "  ok    a version bump alone passes"
else
  echo "  FAIL  a version bump alone fails the gate: a release number is pinned"
  (cd "$BUMP" && ./tools/check-plugin.sh) | grep FAIL
  exit 1
fi
echo
```

- [ ] **Step 2: Run it and watch it fail**

Run: `./tools/check-plugin-mutants.sh; echo "exit=$?"`
Expected: exactly these lines, then `exit=1`. The baseline and mutants do not run.

```
release bump (both manifests at a version no release used must PASS):
  FAIL  a version bump alone fails the gate: a release number is pinned
  FAIL  claude manifest must identify the release as version 0.16.0
  FAIL  codex manifest must identify the release as version 0.16.0
```

Record this output in your report: it is the failing-first evidence.

- [ ] **Step 3: Commit**

```bash
git add tools/check-plugin-mutants.sh
git commit -m "test(tools): require a version bump alone to pass check-plugin"
```

### Task 2: Stop pinning the release version

**Files:**
- Modify: `tools/check-plugin.py:458-461` (the pin loop and its trailing blank line)
- Modify: `tools/check-plugin-mutants.sh` (the mutant "one manifest reverts to 0.13.0", line 158 before Task 1's insertion)

**Interfaces:**
- Consumes: Task 1's release-bump step; the drift check at `tools/check-plugin.py:158-166`.
- Produces: a gate with no release number in it.

- [ ] **Step 1: Delete the pin loop**

Remove these lines from `tools/check-plugin.py`, plus the blank line after them, so one blank line remains before `progress_text, progress_error = read(`:

```python
for label in ("claude", "codex"):
    if label in manifests and manifests[label].get("version") != "0.16.0":
        bad(f"{label} manifest must identify the release as version 0.16.0")
```

- [ ] **Step 2: Make the 0.13.0 mutant release-agnostic**

In the mutant "one manifest reverts to 0.13.0", replace the anchor
`assert d.get('version')=='0.16.0', 'mutant is a no-op: Claude manifest is not at the approved baseline'`
with
`assert d.get('version') and d['version']!='0.13.0', 'mutant is a no-op: Claude manifest has no version or is already 0.13.0'`.
Everything else on that line stays.

- [ ] **Step 3: Add the Review Focus mutant after it**

```bash
run_mutant "both manifests lose their version" "$J \"import json; paths=['plugins/superb/.claude-plugin/plugin.json','plugins/superb/.codex-plugin/plugin.json']; data=[json.load(open(p)) for p in paths]; assert all(d.get('version') for d in data), 'mutant is a no-op: a manifest already has no version'; [(d.pop('version'),json.dump(d,open(p,'w'),indent=2)) for p,d in zip(paths,data)]\""
```

- [ ] **Step 4: Run both gates**

Run: `./tools/check-plugin.sh; echo "exit=$?"`
Expected: last line `check-plugin: PASS`, `exit=0`.

Run: `./tools/check-plugin-mutants.sh; echo "exit=$?"`
Expected: `ok    a version bump alone passes`, `ok    clean copy passes`, `killed` for both "one manifest reverts to 0.13.0" and "both manifests lose their version", a summary line ending `0 survived; 0 no-op`, `check-plugin-mutants: PASS`, `exit=0`.

- [ ] **Step 5: Commit**

```bash
git add tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "fix(tools): stop pinning the release version in check-plugin"
```

### Task 3: Verification

**Files:** none modified.

- [ ] **Step 1: Run the CI commands from `.github/workflows/checks.yml`**

```bash
./tools/check-plugin.sh
python3 -m unittest discover -s plugins/superb/skills/pipeline/tests -v
./tools/check-plugin-mutants.sh
python3 -m unittest discover -s plugins/superb/skills/craft/tests -v
```

Expected: `check-plugin: PASS`; both unittest runs end `OK` (skips allowed); `check-plugin-mutants: PASS`.

- [ ] **Step 2: Check the branch's commits for attribution or session links**

Run: `git log origin/main..HEAD --format=%B | grep -inE 'co-authored-by|claude\.ai/code|session' ; echo "matches=$?"`
Expected: no output, `matches=1`.

- [ ] **Step 3: Check no release number is pinned**

Run: `grep -nE '0\.1[4-9]\.0|0\.1[0-9]\.[0-9]' tools/check-plugin.py tools/check-plugin-mutants.sh`
Expected: only the mutant's `0.13.0` lines.
