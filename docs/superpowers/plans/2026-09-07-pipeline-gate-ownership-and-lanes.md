# Pipeline Gate Ownership and Lane State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans —
> or equivalent direct execution of this approved plan — to implement it
> task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Do NOT use `superpowers:subagent-driven-development` as the orchestrator,
> and do NOT use `superb:pipeline`.** SDD dispatches a formal reviewer when an
> implementer returns `DONE` and has no implementation-only mode, which is the
> pattern the skill under repair exists to remove; and `pipeline`'s Stage 4 is
> the artifact being changed, so running it here would validate the fix with
> the machinery being fixed. Every task below carries a mechanical gate — its
> linter arm goes RED before the change and GREEN after, with a mutant proving
> the arm can fail — so per-task verification is done by the gate, not by a
> reviewer agent. The single review of this work happens once, over the whole
> change, after Task 10.

**Goal:** Close five state-machine defects left by PR #3 — gate ownership in the
fix loop, lane-aware Current State, waved reviewer sizing, review of every
repository-changing fix, and committed run artifacts — without restoring
per-task formal review.

**Architecture:** A fix loop belongs to the `review_gate` (`RV` or `RVJ`) that
raised its findings, and rounds are appended under that gate's own line. Current
State becomes one `**Lane <id>:**` line per active lane, compared per lane
against that lane's own dependency chain. Reviewer count comes from task count,
`s = ceil(N/5)`, independent of the wave count, so implementation scheduling
cannot reduce review coverage.
`M` is keyed on whether the repository changed, so a deletion owes a re-review.

**Tech Stack:** Markdown skill prose; Python 3 stdlib only (`tools/check-plugin.py`
— PyYAML is not guaranteed present); Bash mutation harness
(`tools/check-plugin-mutants.sh`); GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-07-pipeline-gate-ownership-and-lanes-design.md`

## Global Constraints

- **Never push, publish, merge, or open a PR.** Commit to this branch only.
- **Never restore per-task formal review.** These five invariants are load-bearing,
  each already has an arm and mutants, and no task here may weaken one:
  `COMPLETING AN IMPLEMENTATION TASK DISPATCHES NO REVIEWER`;
  `REVIEW MAY NOT BEGIN WHILE ANY TASK IN THE PHASE IS UNCHECKED`;
  all reviewers return → consolidate → fix plan → dispatch;
  `PASS` is the only normal edge to the next phase;
  implementation complete ≠ phase complete.
- **No unrelated changes.** Do not touch `superb:craft`, `superb:bug-investigate`,
  `superb:setup`, or `plugins/superb/skills/craft/ui/`. `superb:bug-fix` is not
  edited.
- **Never edit anything outside this repository** — in particular
  `~/.claude/skills/subagent-driven-development/` and the superpowers plugin cache.
- `tools/check-plugin.py` is **stdlib-only**.
- **Every new arm cites its mutants** in a `# Mutants: "..."` comment, and every
  cited name must exist as `run_mutant "<name>"` — `check-plugin.py`'s citation
  arm fails the build on a dangling citation, and the reverse (a mutant with no
  citation) is allowed.
- **New `run_mutant` blocks go immediately BEFORE the harness summary block**
  (the `echo "killed=$PASS survived=$SURV no-op=$NOOP"` lines). Appending to the
  end of the file puts them after the verdict, where kills go uncounted.
- **Mutant guards anchor on structural forms, never bare phrases.** Fixture and
  skill prose contains the literal strings a guard greps for; anchor on a bullet
  prefix, a middot-delimited field, or a line-anchored regex. For any phrase that
  can wrap across lines, use a whitespace-flexible regex (`\s+`-joined) — arms
  read flattened text, mutants read raw text.
- **Arms that call `relpath` must sit after its definition**
  (`tools/check-plugin.py:1285`).
- **Both directions for every arm.** Every shape the templates prescribe must
  PASS, and every wrong shape must FAIL. PR #3's costliest defects were arms
  that failed conforming input.
- **Never print an affirmative line about a comparison that did not happen.**
  `_untrusted` is set by every report either half of the advancement arm makes
  about its own subject; both `ok(...)` calls require it clear. Any new report
  added here sets it too.
- **Run the harness after every prose, fixture, or arm edit** — and never pipe
  it through `tail`, which discards the no-op diagnostics. `killed=N survived=0
  no-op=0` is the only acceptable result.
- Verification command for nearly every task:
  `./tools/check-plugin.sh && for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d; done && ./tools/check-plugin-mutants.sh`

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `tools/fixtures/run-lanes/` | Two legal concurrent lanes, a join phase gated by a leading `RVJ`. The only fixture exercising lanes; today no fixture even contains two lanes. |
| `tools/fixtures/run-rvj-fix/` | An `RVJ` carrying its own appended fix round, with the matching blocking row in `findings.md`. The only fixture exercising gate-owned rounds. |
| `docs/superpowers/runs/pipeline-phase-machine.md` | The concise permanent record distilled from PR #3's review history, in the established loose-file pattern of `pipeline-phase-seam.md`. |

**Modified**

| Path | Change |
|---|---|
| `plugins/superb/skills/pipeline/SKILL.md` | `review_gate` in the Stage 4 states and the `RV` line section; both `RVJ` transitions; `ceil(N/5)` sizing and `W` as informational in the regime table, fan-out table and REVIEW state; Current State grammar; `M` keyed on repository change; composed-skill and rationalization rows |
| `references/fix-loop.md` | Gate-neutral reopen rule; `RVJ` fix-round home; `ceil(N/5)` sizing with waves as implementation-only; `M`'s definition and its closed route list; the deletion route |
| `references/parallel.md` | Lane grammar reference; slice boundaries as whole-wave unions; join gating |
| `references/run-state.md` | Current State grammar; the `W=` field; per-lane resume precedence; the worked `N=12 waved` example |
| `templates/progress.md` | Current State becomes `**Lane <id>:**` lines; `W=` in the `RV` grammar comment; `RVJ` round form |
| `templates/findings.md` | The route list; `M=0` semantics |
| `plugins/superb/skills/pipeline/README.md` | Fan-out prose; lane prose |
| `tools/check-plugin.py` | `W=` in `decl`; `min` sizing arm; round-owner attribution; gate-owns-its-round arm; route narrowing; lane reading and per-lane comparison; join gating; `.gitignore` arm |
| `tools/check-plugin-mutants.sh` | Mutants for every new arm; retarget the `waved`-exemption guard |
| `tools/fixtures/run-ok/`, `run-open-rv/`, `run-fixloop/` | Current State → `Lane A`; `run-open-rv` Phase 2 gains `W=2` |
| `.github/workflows/checks.yml` | `--run` over the two new fixtures |
| `.gitignore` | Ignore `docs/superpowers/runs/*/` |
| `plugins/superb/.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` | version `0.13.0` |

**Removed**

| Path | Reason |
|---|---|
| `docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine/` (12 files) | Ephemeral run artifacts PR #3 committed as a byproduct; never the subject of a keep decision; incomplete as a run record |

---

## Phase Overview

| Phase | Tasks | Deliverable |
|---|---|---|
| 1 — review sizing | 1 | `s = ceil(N/5)` for every phase, mechanically checked; the `waved` bypass gone; `W` informational |
| 2 — gate ownership | 2, 3 | `review_gate`; rounds attributed to their gate; a gate that raised a blocker carries its own round |
| 3 — commit-backed review | 4 | `deleted` owes a re-review; `M=0` means zero repository commits |
| 4 — lanes | 5, 6, 7, 8 | One canonical lane grammar; per-lane comparison; join gating; per-lane resume |
| 5 — artifacts and release | 9, 10 | Run artifacts removed with a gate behind the rule; final contradiction sweep; 0.13.0 |

---
# Phase 1 — Review sizing

Goal: reviewer count comes from the task count for every `N=` gate, `ceil(N/5)`,
and no implementation scheduling choice can reduce it.

---

### Task 1: `s = ceil(N/5)` for every phase, and `W` made informational

**Root cause being fixed:** an implementation scheduling construct was allowed to
set the review budget. Six prose sites size review from waves
(`SKILL.md:213-214`, `:233`, `:758-760`, `:1010-1013`, `fix-loop.md:44-47`,
`run-state.md:85-87`), so a coarse wave table silently bought a smaller review —
`N=12` in one wave took one reviewer. And the `waved` marker is the sole
exemption from the only `N=`-regime sizing arm
(`tools/check-plugin.py:1537-1538`), so `N=12 waved → 1 slice` and
`N=12 waved → 9 slice` are both accepted today.

**Files:**
- Modify: `tools/check-plugin.py:1245-1246` (the `decl` regex), `:1536-1551` (the sizing arm)
- Modify: `plugins/superb/skills/pipeline/SKILL.md:212-214`, `:226-235` (regime table), `:757-760` (REVIEW state), `:971-978` (fan-out table), `:1007-1013` (slice boundaries)
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:42-47`
- Modify: `plugins/superb/skills/pipeline/references/run-state.md:53` (the worked example), `:85-87`
- Modify: `plugins/superb/skills/pipeline/references/parallel.md:136-139`
- Modify: `plugins/superb/skills/pipeline/README.md:52-54`
- Modify: `plugins/superb/skills/pipeline/templates/progress.md` (the `RV` grammar comment)
- Modify: `tools/fixtures/run-ok/progress.md` (Phase 4 gains an informational `W`; a new Phase 5 covers `N=12 W=1 → 3 slice`)
- Modify: `tools/check-plugin-mutants.sh:1556-1575` (the dead `waved` exemption guard) and its summary block

**Interfaces:**
- Produces: the `W` named group in `decl`, present **only so a round carrying
  `W=<n>` still parses**. No arm reads it for arithmetic. Tasks 6 and 7's
  fixtures may write `W=` freely.

- [ ] **Step 1: Write the failing arm**

In `tools/check-plugin.py`, add `W` to `decl` (`:1245-1246`) where `waved` sat,
so a round carrying it still matches rather than falling into the
"no parseable declaration" violation:

```python
decl  = re.compile(r"(?P<key>N|M)=(?P<n>\d+)\s*(?:W=(?P<W>\d+)\s*)?(?:C=(?P<C>\d+)\s*)?"
                   r"(?:->|→)\s*(?P<s>\d+)\s*slice\s*\+\s*(?P<i>\d+)\s*integration")
```

Then replace the sizing arm at `:1536-1551` entirely:

```python
            # REVIEWER COUNT COMES FROM TASK COUNT, AND FROM NOTHING ELSE.
            # `s == ceil(N/5)` for every normal `N=` gate round.
            #
            # Waves used to size this, and `waved` exempted a round from the
            # arm outright — so a coarse wave table bought a smaller review
            # (`N=12` in one wave took one reviewer) and `N=12 waved → 9 slice`
            # passed too. Waves are an IMPLEMENTATION scheduling construct:
            # they decide which tasks may run concurrently, the worktree and
            # branch scheduling, the merge order and the implementation build
            # gates. Review slices are formed after the phase has landed, over
            # the whole phase diff, and a slice MAY split work that executed in
            # one wave. Implementation independence and review partitioning are
            # different concerns.
            #
            # `W=<n>` is parsed and IGNORED here. It stays legal on the line
            # because it is useful for implementation and history, but it never
            # participates in this arithmetic — a tracker must not be able to
            # buy a smaller review by declaring fewer waves.
            #
            # `RVJ` is excluded by `kind` and that is NOT free: an `RVJ`
            # declares `0 slice + 1 integration` with its `N` the task count
            # across the reviewed unit, so without the test this arm reports
            # every worked `RVJ` record for declaring 0 where `ceil(17/5)` is 4.
            # `M=` rounds are excluded by `key`: they are sized from the fix
            # diff's clusters and declare that count as `C`.
            # Mutants: "run tracker round departs from ceil(N/5)",
            #          "run tracker one-wave phase under-fans-out",
            #          "run tracker informational W changes the expected count".
            ntasks = int(d.group("n"))
            if kind == "RV" and d.group("key") == "N":
                want_s = -(-ntasks // 5)
                if nslice != want_s:
                    viol += 1
                    bad(f"{where}: `N={ntasks}` round declares {nslice} slice "
                        f"reviewers, but `ceil(N/5)` is {want_s}. Reviewer "
                        "count comes from the task count and from nothing "
                        "else: waves schedule implementation, they do not "
                        "size review, and a slice may split work that ran in "
                        "one wave. A `W=` on the line is informational and is "
                        "not read here — implementation scheduling never "
                        f"reduces review coverage. REMEDY: dispatch {want_s} "
                        "slice reviewers over approximately balanced "
                        "contiguous ranges covering the whole phase diff")
```

- [ ] **Step 2: Run the gate to verify it fails**

Run: `./tools/check-plugin.sh 2>&1 | grep FAIL`

Expected: a `FAIL` naming `references/run-state.md`'s worked example, which is
`N=12 waved → 2 slice + 1 integration` — with the exemption gone, `ceil(12/5)`
is 3 and the old marker no longer parses. Plus the dangling-citation `FAIL` for
the three mutant names not yet defined.

Record the exact list; every one is edited below.

- [ ] **Step 3: Fix the worked example and the sizing sites**

`references/run-state.md:53` — the only worked example carrying the old marker.
A 12-task phase takes `ceil(12/5)` = 3 regardless of its waves:

```markdown
- [x] RV — review fan-out · N=12 W=1 → 3 slice + 1 integration · boundary: the T4 contract consumed by T11 · reports p4-review-{a,b,c,int}.md · coverage p4-coverage.md → F-021
```

`references/run-state.md:85-87` — the sizing bullet:

```markdown
- `N=<tasks>[ W=<waves>] → <s> slice + <i> integration` — `N` is on the line so
  the fan-out is re-derivable at closure rather than trusted from the step most
  likely to have been skipped. **`s` is `ceil(N/5)`**, always. `W`, when
  present, records how many implementation waves the phase ran and is
  **informational only**: waves schedule implementation, they do not size
  review. An **`M=`** re-review **writes its cluster count on the line as
  `C=<n>` and `s` must equal it**; an **`RVJ`** is always
  `0 slice + 1 integration` with `N` informational.
```

`SKILL.md:226-235` — the regime table. The two `N=` rows collapse into one,
because there is now one rule:

```markdown
| Key on the line | `s` is | Re-derivable from the line? |
| --- | --- | --- |
| `N=<n>`, optionally `W=<w>` | `ceil(N/5)`, always. `W` records the phase's implementation wave count and is informational — it never sizes review. | **Yes.** That is what `N` is on the line for: the fan-out is re-derivable at closure instead of trusted from the step that gets skipped. |
| `M=<m> C=<c>` | `c`, the file clusters in the fix diff | **As a declaration only.** `C` makes the sizing auditable and an arithmetic slip between the two numbers red, without establishing the count itself. `M` sizes nothing. |
| `RVJ` | always `0 slice + 1 integration`, its `N` informational | **Yes**, from the form. |
```

Replace the preamble above it (`SKILL.md:226-228`):

```markdown
**Which regime sized the round — and the line proves it.** Every regime's `s` is
re-derivable from the line the round is written on; the `M=` row's `C` is a
declaration whose *arithmetic* is checked rather than whose count is
established.
```

`SKILL.md:757-760` — the REVIEW state's operative instruction:

```markdown
`N` = the phase's task count → dispatch `ceil(N/5)` slice reviewers in parallel,
over approximately balanced contiguous commit ranges covering the whole phase
diff. **Waves do not enter this.** They scheduled the implementation — which
tasks ran concurrently, in which worktrees, merged in which order — and review
slices are formed afterwards, over what landed. A slice may split work that
executed in one wave; implementation independence and review partitioning are
different concerns.
```

`SKILL.md:971-978` — the fan-out table:

```markdown
| Tasks in phase (N) | Slice reviewers | Integration reviewer | Total |
|--------------------|-----------------|----------------------|-------|
| 1–5                | 1               | 0 (one slice sees all) | 1   |
| 6–10               | 2               | 0, or 1 at a declared boundary | 2–3 |
| 11–12              | 3               | 0, or 1 at a declared boundary | 3–4 |

`s` is `ceil(N/5)`, independent of the wave count: `N=8 W=8` and `N=8 W=1` both
take 2, and `N=12 W=1` takes 3. **Implementation scheduling never reduces review
coverage** — a phase that ran as one wave gets the same review budget as one
that ran as twelve.
```

`SKILL.md:1007-1013` — slice boundaries:

```markdown
**Slices are commit ranges, not vibes.** Take each slice's boundaries from the
hashes recorded against its tasks in the tracker. Tasks that touch the same
files make a "contiguous ~5 tasks" slice ambiguous; `<first>^..<last>` does not.
Cut `ceil(N/5)` approximately balanced contiguous ranges over the phase branch,
and **a slice may split work that executed in one implementation wave** — waves
scheduled the work, they do not partition the review of it. What the slices owe
is coverage: every commit on the phase branch inside some slice, and no two
slices carrying the identical range.
```

`references/fix-loop.md:42-47`:

```markdown
     Spawn the slice reviewers in parallel. **How many comes from the task
     count: `s = ceil(N/5)`, always.** Waves scheduled the implementation and do
     not size the review; a `W=` on the `RV` line is informational. Assign
     approximately balanced contiguous commit ranges covering the whole phase
     diff — a slice may split work that ran in one wave, because implementation
     independence and review partitioning are different concerns.
```

`references/parallel.md:136-139` — this is the wave-boundary slice guidance, and
it is the one place the removed restriction did real work:

```markdown
Slice reviewers for a phase that contained waves take ranges over `P`'s
first-parent history, and the wave merges are a convenient place to read commit
boundaries from — but they do not decide how many slices there are, nor where
the cuts must fall. The count is `ceil(N/5)`; cut approximately balanced
contiguous ranges over `PB..PH`. A slice may span a wave merge or split a wave's
members, because a wave is an implementation schedule and a slice is a review
partition.
```

`README.md:52-54`:

```markdown
**Reviewer fan-out.** A phase of N tasks gets `ceil(N/5)` slice reviewers over
exact commit ranges covering the whole phase diff — independent of how many
implementation waves it ran, because scheduling never reduces review coverage.
```

`templates/progress.md` — in the `RV` grammar comment, replace the sizing
sentence:

```
     s = ceil(N/5), always. W= may appear on the line to record how many
     implementation waves the phase ran; it is informational and never sizes
     review. Waves schedule implementation; review slices are cut afterwards
     over the whole phase diff, and a slice may split a wave.
```

- [ ] **Step 4: Give the fixtures the two required PASS cases**

`tools/fixtures/run-ok` Phase 4 is `N=7 → 2 slice + 0 integration`, and
`ceil(7/5)` is 2, so its shape is already correct. Add an informational `W` to
prove the tolerant parse:

```markdown
- [x] RV — review fan-out · N=7 W=3 → 2 slice + 0 integration
      · no integration boundary
      · reports p4-review-{a,b}.md · coverage p4-coverage.md → no findings
```

Then add a Phase 5 covering the case the brief calls out explicitly — a
single-wave phase that must still take three reviewers:

```markdown
## Phase 5 — fixture, one implementation wave, three review slices · deps: Phase 4
- [x] T6 — a task · W1 · deps T5 — `fffffff`
- [x] RV — review fan-out · N=12 W=1 → 3 slice + 0 integration
      · no integration boundary
      · reports p5-review-{a,b,c}.md · coverage p5-coverage.md → no findings
```

Create `p5-review-a.md`, `p5-review-b.md`, `p5-review-c.md` as one-line stubs
and `p5-coverage.md` with three rows carrying **distinct** ranges above a
`git log --oneline` line, ending `COVERED: 3/3 commits`.

Update `run-ok/progress.md`'s own arithmetic paragraph to state the new rule and
name Phase 5 as the one-wave-three-slices case — the fixture documents its own
purpose, and leaving it stale is the failure it warns about.

- [ ] **Step 5: Run the gate to verify it passes**

```bash
./tools/check-plugin.sh 2>&1 | grep -E 'FAIL|closed review rounds' | cut -c1-150
./tools/check-plugin.sh --run tools/fixtures/run-ok 2>&1 | tail -1
```

Expected: no `FAIL` except the dangling mutant citations.

- [ ] **Step 6: Prove both directions by hand before writing the mutants**

On `mktemp -d` copies only:

```bash
probe() { W=$(mktemp -d); cp -r tools/fixtures/run-ok "$W/f"
  ( cd "$W" && eval "$2" ) >/dev/null 2>&1
  printf '  %-52s FAIL=%s\n' "$1" "$(./tools/check-plugin.sh --run "$W/f" 2>&1 | grep -cE "FAIL  $W/f")"
  rm -rf "$W"; }
probe "N=8 W=8, 2 slices (must be 0)"    'sed -i "s|N=8 → 2 slice|N=8 W=8 → 2 slice|" f/progress.md'
probe "N=8 W=8, 4 slices (must be >0)"   'sed -i "s|N=8 → 2 slice + 1 integration|N=8 W=8 → 4 slice + 1 integration|" f/progress.md'
probe "N=12 W=1, 3 slices (must be 0)"   'true   # shipped as Phase 5'
probe "N=12 W=1, 1 slice (must be >0)"   'sed -i "s|N=12 W=1 → 3 slice|N=12 W=1 → 1 slice|" f/progress.md'
probe "N=8 W=1, 2 slices (must be 0)"    'sed -i "s|N=8 → 2 slice|N=8 W=1 → 2 slice|" f/progress.md'
probe "W removed, count unchanged (0)"   'sed -i "s|N=7 W=3 → 2 slice|N=7 → 2 slice|" f/progress.md'
```

Every "must be 0" case reporting 0 and every "must be >0" case reporting more
than 0 is the required behaviour from the spec, measured. The last case is the
one that proves `W` is genuinely informational: removing it changes nothing.

- [ ] **Step 7: Add the mutants**

Insert into `tools/check-plugin-mutants.sh` immediately **before** the summary
block:

```bash
# Reviewer count comes from task count. `waved` used to exempt a round from the
# sizing arm outright, and wave-based sizing let a coarse wave table buy a
# smaller review.
run_mutant "run tracker round departs from ceil(N/5)" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -cF "N=8 → 2 slice + 1 integration" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one N=8 round declaring 2 slices"
else
  sed -i "s|N=8 → 2 slice + 1 integration|N=8 → 4 slice + 1 integration|" "$f"
  grep -qF "N=8 → 4 slice" "$f" || echo "mutant is a no-op: the slice count was not raised"
  grep -qF "reports p2-review-{a,b,int}.md" "$f" || echo "mutant is a no-op: the report set moved too, so a kill could come from the file-count arm"
fi'
run_mutant "run tracker one-wave phase under-fans-out" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "N=12 W=1 → 3 slice" "$f"; then
  echo "mutant is a no-op: the fixture has no N=12 W=1 round declaring 3 slices"
else
  sed -i "s|N=12 W=1 → 3 slice + 0 integration|N=12 W=1 → 1 slice + 0 integration|" "$f"
  sed -i "s|reports p5-review-{a,b,c}.md|reports p5-review-a.md|" "$f"
  grep -qF "N=12 W=1 → 1 slice" "$f" || echo "mutant is a no-op: the slice count was not reduced"
  grep -qF "reports p5-review-a.md" "$f" || echo "mutant is a no-op: the report set did not shrink with it, so a kill could come from the file-count arm"
fi'
run_mutant "run tracker informational W changes the expected count" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if ! grep -qF "N=7 W=3 → 2 slice" "$f"; then
  echo "mutant is a no-op: the fixture has no N=7 W=3 round"
else
  sed -i "s|N=7 W=3 → 2 slice|N=7 W=1 → 2 slice|" "$f"
  grep -qF "N=7 W=1 → 2 slice" "$f" || echo "mutant is a no-op: W was not changed"
fi'
```

The third mutant is a **survivor by design in the arm under test and must be
killed by nothing** — changing `W` from 3 to 1 must leave `ceil(7/5) = 2`
correct, so this mutant proves `W` is informational. Because the harness fails on
a survivor, do **not** add it as a `run_mutant`; instead assert it in Step 6's
probe list (the "W removed, count unchanged" case) and delete this third block.
Keep only the first two mutants.

Then delete the dead `waved` exemption guard inside
`"run tracker's unwaved round departs from ceil(N/5)"` (renamed to
`"run tracker round departs from ceil(N/5)"` above) and the section comment's
claim that the arm is scoped to an unwaved regime.

- [ ] **Step 8: Verify the mutants kill**

```bash
./tools/check-plugin-mutants.sh 2>&1 | grep -E 'departs from ceil|under-fans-out|killed=|SURVIVED|NO-OP'
```

Expected: both named mutants `killed`, and the summary `survived=0 no-op=0`.

- [ ] **Step 9: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py tools/check-plugin-mutants.sh tools/fixtures/run-ok
git commit -m "fix(pipeline): reviewer count comes from task count, never from waves

An implementation scheduling construct was setting the review budget. Six prose
sites sized review from waves, so a coarse wave table silently bought a smaller
review -- N=12 in one wave took one reviewer -- and the waved marker was the
sole exemption from the only N= sizing arm, so N=12 waved -> 9 slice passed too.

s = ceil(N/5) now, for every normal N= gate, independent of the wave count:
N=8 W=8 and N=8 W=1 both take 2, and N=12 W=1 takes 3. W stays legal on the
line because it is useful for implementation and history, but it is parsed and
ignored -- a tracker cannot buy a smaller review by declaring fewer waves.

Waves are implementation scheduling: which tasks run concurrently, worktrees,
merge order, build gates. Review slices are cut after the phase lands, over the
whole diff, and a slice MAY split work that ran in one wave. The old
'a wave is never split across two reviewers' restriction is removed wherever it
was a review-sizing constraint; implementation independence and review
partitioning are different concerns."
```

---

# Phase 2 — Gate ownership

Goal: a fix loop belongs to the `review_gate` that raised its findings, rounds
are appended under that gate's own line, and the linter can tell the difference.

---

### Task 2: `review_gate`, and rounds attributed to their gate

**Root cause being fixed:** `references/fix-loop.md:450` says *"Only when `RV` is
already `[x]` … does a re-review reopen it"* — `RV` only — while
`fix-loop.md:173-177` requires an `RVJ`'s blocking findings to run the fix loop
under the `RVJ`'s own Counters row. An `RVJ` fix round therefore has a budget
with no home. The linter cannot detect a misfiled round: `kind` is `"round"` for
every appended record and no arm consults the stem it hangs under.

**Files:**
- Modify: `tools/check-plugin.py:1392-1400` (the `marks` loop), the `lint_review_lines` return, and both call sites (`:1698`, `:1810`)
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:444-457` (the reopen rule), `:173-182` (the `RVJ` block)
- Modify: `plugins/superb/skills/pipeline/SKILL.md:273-279` (the round-append grammar), `:800-830` (the Stage 4 states), `:326-335` (the `RVJ` section)
- Modify: `plugins/superb/skills/pipeline/references/run-state.md:119-126`
- Modify: `plugins/superb/skills/pipeline/templates/progress.md` (the `RVJ` legend gains a round form)
- Modify: `tools/check-plugin-mutants.sh`

**Interfaces:**
- Produces: `lint_review_lines(...)` returns
  `(closed_rounds, no_round_records, violations, gates)` where `gates` is a list
  of dicts `{"kind": "RV"|"RVJ", "line": int, "fids": [str], "rounds": int}` in
  file order. Task 3 consumes `gates`.

- [ ] **Step 1: Write the failing arm**

In `tools/check-plugin.py`, compute each mark's owning gate before the loop and
attribute rounds to it. Replace `:1392` and add the accumulator:

```python
        # EVERY APPENDED ROUND HAS AN OWNING GATE, and it is the nearest
        # preceding `RV`/`RVJ` mark. `kind` is `"round"` for every appended
        # record, so without this the gate a round hangs under is invisible —
        # and the reopen rule the prose used to state named `RV` only, while an
        # `RVJ`'s findings are required to run the fix loop under the `RVJ`'s
        # own Counters row. A round misfiled under a different gate is that
        # budget spent on the wrong line's evidence.
        # Mutants: "run tracker round precedes any review gate".
        marks = [(m.start(), (m.group(1) or m.group(2))) for m in start.finditer(flat)]
        owners, _last = [], None
        for _p, _k in marks:
            if _k in ("RV", "RVJ"):
                _last = (_k, _p)
            owners.append(_last)
        gates = []
        for idx, (pos, kind) in enumerate(marks):
```

Inside the loop, after `where` is bound, record the gate or the round:

```python
            if kind in ("RV", "RVJ"):
                gates.append({"kind": kind, "line": lineno(pos),
                              "fids": re.findall(r"\bF-\d+", rec), "rounds": 0})
            elif owners[idx] is None:
                viol += 1
                bad(f"{where}: an appended `→ round` record with no review gate "
                    "above it — a fix round belongs to the gate that raised its "
                    "findings, so a round with no gate has no owner and its "
                    "evidence closes nothing. REMEDY: append the round under "
                    "its own `RV` or `RVJ` line")
            elif gates:
                gates[-1]["rounds"] += 1
```

Change the return at the function's end from `return seen, nseen, viol` to
`return seen, nseen, viol, gates`, and update both call sites:

```python
seen, nseen, viol, _egates = lint_review_lines(pdir.rglob("*.md"))
```
```python
        rseen, rnseen, rviol, rgates = lint_review_lines(
            [tracker], agent_output=ao, bullet_bounded=True)
```

Extend the examples pass line to report the attribution, so the arm's subject is
visible on a green build:

```python
       f"{seen} closed review rounds, {nseen} of them `M=0 → no round`, "
       f"{sum(1 for g in _egates if g['kind'] == 'RVJ')} of the gates `RVJ`: "
```

- [ ] **Step 2: Run the gate to verify it fails**

Run: `./tools/check-plugin.sh 2>&1 | grep FAIL`
Expected: the dangling-citation `FAIL` for
`"run tracker round precedes any review gate"`. The orphan-round arm itself does
not fire on conforming input — its RED comes from its mutant, which is why
Step 6 is not optional.

- [ ] **Step 3: Make the reopen rule gate-neutral**

`references/fix-loop.md:444-457`. Replace the `RV`-only rule:

```markdown
   **A re-review reopens the gate that raised the findings, and no other.** Call
   it the **`review_gate`** — an `RV` for a phase's own review, an `RVJ` for a
   split's joint review or a lane join's. A re-review runs over fix commits, not
   over the gate's original diff, so it can only append a round to a gate the
   fan-out already closed: closing a gate on a re-review would tick the box with
   no reviewer having seen what that gate exists to read.

   Only when the `review_gate` is already `[x]` from a completed review does a
   re-review reopen **that gate** to `[~]` and reclose it with the round
   appended under **its own line**, in the full per-round grammar — so every
   round has a declared number its file count is checked against, not only the
   first.

   **An `RVJ`'s rounds belong to the `RVJ`.** Its findings run the fix loop
   under the `RVJ`'s own Counters row (*Joint integration review*, above), and
   its rounds are appended under the `RVJ` line. Appending them to a joining
   phase's `RV` spends that phase's review budget on a join it never covered,
   and leaves the `RVJ`'s own evidence claiming a clean review it did not get.
```

`references/fix-loop.md:173-182` — the `RVJ` block gains the round's home
alongside the budget it already names:

```markdown
- Its findings get F-IDs in `findings.md` like any others. Blocking ones run the
  fix loop under the **`RVJ`'s own Counters row** — not the siblings' shared
  row, which they may already have spent — and their rounds are appended under
  the **`RVJ`'s own line**, because the gate that raised a finding is the gate
  whose evidence has to answer for it.
```

- [ ] **Step 4: State `CLOSE(review_gate)` and both `RVJ` transitions**

`SKILL.md:326-335`, after the placement sentence. Closing a gate is one
operation; what it unlocks depends on which gate closed, and none of this is
written down today:

````markdown
**Closing a gate is not accepting a phase.** The generic terminal operation is
`CLOSE(review_gate)` — the gate's box goes `[x]` with its findings closed.
`PASS` is **phase acceptance**, and only a phase's own `RV` can produce it:

```
CLOSE(RV)              → phase PASS
CLOSE(trailing RVJ)    → NEXT PHASE
CLOSE(leading RVJ)     → IMPLEMENT JOINING PHASE
```

```
A CLEAN LEADING RVJ MUST NEVER MARK THE JOINING PHASE PASS.
```

A **leading** `RVJ` gates *entry*, never *completion*: it reviews the lanes that
merged into this phase, not this phase's own tasks, so after it closes the
joining phase still owes the whole of `IMPLEMENT → RV → PASS`. A **trailing**
`RVJ` closes a Rule 3 split, and the run advances past it. An `RVJ` is not a
phase gate and never stands in for one.
````

Mirror the same three transitions into the Stage 4 state machine at
`SKILL.md:819-823`, which currently describes only the trailing case, and use
`CLOSE(review_gate)` for the fix loop's terminal there rather than `PASS`.

**Watch the fence.** The block above is four backticks because it contains a
three-backtick fence; copying it as three would terminate the outer fence early.

- [ ] **Step 5: Give the round grammar an `RVJ` worked example**

`templates/progress.md`'s `RVJ` legend shows only `[ ]` and `[x]` forms with no
appended round, which is why no fixture writes one. Add the round form directly
beneath it:

```
  [x] RVJ — joint integration review · split 4a+4b · N=17 -> 0 slice + 1 integration
      · reports j-4ab-int.md · coverage j-4ab-coverage.md -> F-031
      -> round 2: M=1 C=1 -> 1 slice + 0 integration
         · fixplan j-4ab-fixplan-r2.md · reports j-4ab-rr2-a.md
         · coverage j-4ab-rr2-coverage.md -> F-031 closed
```

Add one line of prose above it: `An RVJ's fix rounds append under the RVJ, never
under a phase's RV — the gate that raised a finding owns the round that answers
it.` Mirror the same worked round into `references/run-state.md:119-126`, which
states the per-round rule.

- [ ] **Step 6: Add the mutant and verify it kills**

```bash
run_mutant "run tracker round precedes any review gate" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "→ round 2: M=2 C=1" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one appended round"
else
  python3 - "$f" <<"EOF"
import pathlib,sys,re
p=pathlib.Path(sys.argv[1]); t=p.read_text()
# Move the round block above every gate line, so it has no owner.
m=re.search(r"(?m)^      → round 2: M=2 C=1.*(?:\n        .*)*\n", t)
assert m, "mutant is a no-op: the round block is not in the expected shape"
blk=m.group(0)
t=t[:m.start()]+t[m.end():]
i=t.index("## Phase 1")
p.write_text(t[:i]+blk+t[i:])
EOF
  grep -qF "→ round 2: M=2 C=1" "$f" || echo "mutant is a no-op: the round block was lost rather than moved"
fi'
```

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep -E 'precedes any review gate|killed=|SURVIVED|NO-OP'`
Expected: `killed`, and `survived=0 no-op=0`.

- [ ] **Step 7: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "feat(pipeline): a fix loop belongs to the gate that raised its findings

The reopen rule said RV only, while an RVJ's blocking findings were required to
run the fix loop under the RVJ's own Counters row -- a budget with no home. The
rule is now gate-neutral: review_gate is RV or RVJ, a re-review reopens the
gate that raised the findings, and an RVJ's rounds append under the RVJ's own
line rather than a joining phase's RV.

Every appended round is attributed to its nearest preceding gate, so a round
with no gate above it is now a violation and the gate kinds are reported on the
pass line. Both RVJ transitions are written down for the first time: a trailing
RVJ advances the run past a split, a leading RVJ only lets the joining phase
start."
```

---

### Task 3: A gate that raised a blocking finding carries its own round

**Files:**
- Modify: `tools/check-plugin.py` (a new arm in the `--run` block, after the ledger parse)
- Create: `tools/fixtures/run-rvj-fix/progress.md`, `findings.md`, `agent-output/` (7 files)
- Modify: `.github/workflows/checks.yml`
- Modify: `tools/check-plugin-mutants.sh` (`enable_run_dir` baseline + mutants)

**Interfaces:**
- Consumes: `rgates` from Task 2, and the ledger rows the no-advance arm already
  parses (`_blockers`, and the per-row `_norm`/`_ci` machinery).

- [ ] **Step 1: Write the failing arm**

In the `--run` block, after the ledger table walk and before
`_blockers.sort(...)`, collect the blocking F-IDs by id so the gate join can use
them. Add `_blocking_ids = set()` beside `_blockers = []`, and inside the row
loop where a blocking row is appended, also `_blocking_ids.add(_fid_upper)`.

Then, after `_blockers.sort(...)`:

```python
        # A GATE THAT RAISED A BLOCKING FINDING CARRIES A ROUND OF ITS OWN.
        # `fix-loop.md` requires an `RVJ`'s findings to run the fix loop under
        # the `RVJ`'s own Counters row, and now under its own line — but a run
        # that appends them to a joining phase's `RV` produces a tracker where
        # the `RVJ` closed clean and the `RV` carries rounds for findings it
        # never raised. This is the join that catches it: the gate whose outcome
        # named the F-ID is the gate that owes the round.
        #
        # Scoped to BLOCKING ids only. A gate closing with Minor findings owes
        # no round — Minors defer to the Stage 5 hand-off — so requiring one
        # would fail a conforming tracker.
        # Mutants: "run tracker RVJ findings are answered under the phase RV",
        #          "run tracker gate with a blocking finding carries no round".
        if _ltext and _blocking_ids:
            for _g in rgates:
                _own = [f for f in _g["fids"] if f.upper() in _blocking_ids]
                if _own and _g["rounds"] == 0:
                    _untrusted = True
                    bad(f"{relpath(tracker)}:{_g['line']}: this {_g['kind']} "
                        f"closed naming blocking {', '.join(sorted(set(_own)))} "
                        "and carries no fix round of its own — the gate that "
                        "raised a finding is the gate whose evidence has to "
                        "answer for it, so a round filed under another gate "
                        "leaves this one claiming a clean review it did not "
                        "get. REMEDY: append the round under this "
                        f"{_g['kind']}")
```

- [ ] **Step 2: Run the gate to verify it fails**

Run: `./tools/check-plugin.sh --run tools/fixtures/run-fixloop 2>&1 | grep FAIL`

Expected: **no** new `FAIL` — `run-fixloop`'s Phase 2 `RV` names `F-001, F-002`
and does carry a round, so the arm is satisfied. The RED comes from Step 4's
fixture and Step 6's mutants. Confirm the two dangling citations are the only
failures.

- [ ] **Step 3: Build the `run-rvj-fix` fixture**

The corpus has no `RVJ` carrying a round, so the arm's happy path has no input.
Create `tools/fixtures/run-rvj-fix/progress.md`:

```markdown
# Pipeline — Progress Tracker

A fixture run directory, not a real one. Its job is the one shape no other
fixture holds: **an `RVJ` that raised a blocking finding and carries its own fix
round.** Phase 2 is the last sibling of a split, so its `RVJ` trails its `RV`;
the `RVJ` closed naming `F-010`, and `F-010`'s round is appended under the
`RVJ`, not under the phase's `RV`.

That is the whole point. `references/fix-loop.md` requires an `RVJ`'s findings to
run the fix loop under the `RVJ`'s own Counters row and under its own line, and
the gate-ownership arm reads exactly this join: the gate whose outcome named the
blocking id is the gate that owes the round. File the round under the `RV`
instead and the `RVJ` reads as a clean review it never got — which is the mutant
`"run tracker RVJ findings are answered under the phase RV"`.

Phase 1 is closed plainly so the tracker has a conforming non-`RVJ` round for
the review-line linter, and `F-010` is `closed` in `findings.md` so the join has
a blocking id to match.

## Current State
- **Lane A:** done
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-rvj-fix/

## Phase 1 — fixture, closed · deps: none
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, a split's last sibling · deps: Phase 1
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] T3 — a task · W1 · deps T1 — `ccccccc`
- [x] RV — review fan-out · N=2 → 1 slice + 0 integration
      · reports p2-review-a.md · coverage p2-coverage.md → no findings
- [x] RVJ — joint integration review · split 2a+2b · N=4 → 0 slice + 1 integration
      · reports j-2ab-int.md · coverage j-2ab-coverage.md → F-010
      → round 2: M=1 C=1 → 1 slice + 0 integration
        · fixplan j-2ab-fixplan-r2.md · reports j-2ab-rr2-a.md
        · coverage j-2ab-rr2-coverage.md → F-010 closed
```

`findings.md` carries one closed blocking row keyed to the join:

```markdown
# Pipeline — Findings Ledger (fixture)

A fixture. `F-010` was raised by Phase 2's `RVJ` and closed by the round
appended under that same `RVJ`, which is the join the gate-ownership arm reads.

## Blocking ledger

| ID | Sev | Phase | File:line | Finding | State | Closed by |
| -- | --- | ----- | --------- | ------- | ----- | --------- |
| F-010 | Major | 2 | `src/j.py:4` | a cross-sibling contract mismatch | closed | fix `f0f0f0f` + the RVJ's round 2 covered it |

## Counters

| Scope | Fix-loop iteration | Cap | Deepest fix-mode depth this chain | Cap |
| ----- | ------------------ | --- | --------------------------------- | --- |
| RVJ split 2a+2b | 1 | 5 | 0 | 2 |

## Iteration log (convergence rule input)

| Iter | Scope | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | RVJ split 2a+2b | 0 | F-010 | none | 2026-09-07 10:00 |

## Deferred Minor findings

| ID | Phase | File:line | Finding |
| -- | ----- | --------- | ------- |
```

Create the seven files the rounds name under
`tools/fixtures/run-rvj-fix/agent-output/`: `p1-review-a.md`, `p1-coverage.md`,
`p2-review-a.md`, `p2-coverage.md`, `j-2ab-int.md`, `j-2ab-coverage.md`,
`j-2ab-fixplan-r2.md`, `j-2ab-rr2-a.md`, `j-2ab-rr2-coverage.md`. Each report is
a one-line stub; each coverage file is an assignment table above a
`git log --oneline` line, ending `COVERED: <n>/<n> commits`; the fix plan follows
`templates/fix-plan.md`.

- [ ] **Step 4: Verify the fixture conforms, then prove the arm fires**

```bash
./tools/check-plugin.sh --run tools/fixtures/run-rvj-fix 2>&1 | tail -1
```
Expected: `check-plugin: PASS` (bar the dangling citations).

Then prove the arm on a copy, by moving the round to the wrong gate:

```bash
W=$(mktemp -d); cp -r tools/fixtures/run-rvj-fix "$W/f"
python3 - "$W/f/progress.md" <<'EOF'
import pathlib,sys,re
p=pathlib.Path(sys.argv[1]); t=p.read_text()
m=re.search(r"(?m)^      → round 2: M=1 C=1.*(?:\n        .*)*\n", t)
blk=m.group(0); t=t[:m.start()]+t[m.end():]
t=t.replace("      · reports p2-review-a.md · coverage p2-coverage.md → no findings\n",
            "      · reports p2-review-a.md · coverage p2-coverage.md → no findings\n"+blk, 1)
p.write_text(t)
EOF
./tools/check-plugin.sh --run "$W/f" 2>&1 | grep "FAIL  $W/f" | cut -c1-140
rm -rf "$W"
```
Expected: a `FAIL` naming Phase 2's `RVJ` as closing on `F-010` with no round of
its own.

- [ ] **Step 5: Wire the fixture into CI and the harness baseline**

`.github/workflows/checks.yml`, after the existing `--run` lines:

```yaml
      - run: ./tools/check-plugin.sh --run tools/fixtures/run-rvj-fix
```

And add `tools/fixtures/run-rvj-fix` to the harness's baseline `for fx in …`
loop, so a mutant over it means what its name says.

- [ ] **Step 6: Add the mutants and verify they kill**

```bash
run_mutant "run tracker RVJ findings are answered under the phase RV" '
enable_run_dir tools/fixtures/run-rvj-fix || exit 0
f=tools/fixtures/run-rvj-fix/progress.md
if [ "$(grep -c "→ round 2: M=1 C=1" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one appended round"
else
  python3 - "$f" <<"EOF"
import pathlib,sys,re
p=pathlib.Path(sys.argv[1]); t=p.read_text()
m=re.search(r"(?m)^      → round 2: M=1 C=1.*(?:\n        .*)*\n", t)
assert m, "mutant is a no-op: the round block is not in the expected shape"
blk=m.group(0); t=t[:m.start()]+t[m.end():]
anchor="      · reports p2-review-a.md · coverage p2-coverage.md → no findings\n"
assert t.count(anchor)==1, "mutant is a no-op: the phase RV closing line is not unique"
p.write_text(t.replace(anchor, anchor+blk, 1))
EOF
  grep -qF "→ round 2: M=1 C=1" "$f" || echo "mutant is a no-op: the round was lost rather than moved"
  grep -qE "^\| F-010 .*\| closed \|" tools/fixtures/run-rvj-fix/findings.md || echo "mutant is a no-op: F-010 is not a closed blocking row, so the join has nothing to read"
fi'
run_mutant "run tracker gate with a blocking finding carries no round" '
enable_run_dir tools/fixtures/run-rvj-fix || exit 0
f=tools/fixtures/run-rvj-fix/progress.md
if [ "$(grep -c "→ round 2: M=1 C=1" "$f")" != 1 ]; then
  echo "mutant is a no-op: the fixture no longer has exactly one appended round"
else
  python3 - "$f" <<"EOF"
import pathlib,sys,re
p=pathlib.Path(sys.argv[1]); t=p.read_text()
out=re.sub(r"(?m)^      → round 2: M=1 C=1.*(?:\n        .*)*\n", "", t)
assert out!=t, "mutant is a no-op: the round block was not removed"
p.write_text(out)
EOF
  grep -qF "→ round 2:" "$f" && echo "mutant is a no-op: a round survived on the gate"
  grep -qF "→ F-010" "$f" || echo "mutant is a no-op: the RVJ no longer names F-010, so it owes no round"
fi'
```

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep -E 'answered under the phase RV|carries no round|killed=|SURVIVED|NO-OP'`
Expected: both `killed`, `survived=0 no-op=0`.

- [ ] **Step 7: Commit**

```bash
git add tools/check-plugin.py tools/check-plugin-mutants.sh tools/fixtures/run-rvj-fix .github/workflows/checks.yml
git commit -m "test(tools): the gate that raised a blocking finding owes the round

Nothing could tell an RVJ's fix round from a phase RV's, so a run that filed an
RVJ's findings under the joining phase's RV produced a tracker where the RVJ
read clean and the RV carried rounds for findings it never raised. The arm
joins each closed gate's outcome against the ledger's blocking rows: the gate
whose outcome named the id is the gate that owes the round.

Scoped to blocking ids, because a gate closing with Minor findings owes no
round and requiring one would fail a conforming tracker. run-rvj-fix is the
first fixture with an RVJ carrying a round at all."
```

---

# Phase 3 — Commit-backed review

Goal: `M` is keyed on whether the repository changed. A deletion is a commit, so
it owes a fix plan and a re-review; `withdrawn` is the only new closed route and
it cannot become an escape hatch.

---

### Task 4: `deleted` owes a re-review, and `withdrawn` is narrow

**Root cause being fixed:** `references/fix-loop.md:390-397` excludes two routes
from `M` — *"a deletion or a user-ruled false positive, and the list is closed"* —
on the reasoning that neither *"leaves a commit a reviewer could be assigned"*.
That is true of a false positive and false of a deletion. `fix-loop.md:515-519`
says outright *"Deleting the claim opens no re-review round"*, and
`fix-loop.md:472-479` excludes a deletion's commit from the coverage union. So
`finding → delete text → mark closed → no review` is a legal path today, and a
deletion-only commit is still a commit.

**Files:**
- Modify: `tools/check-plugin.py:1250` (the `route` regex and its new siblings), `:1414-1417` (the "names no closure route" problem), `:1421-1426` (beside the `pinned by` problem), `:1430-1439` (the REMEDY), and the `--run` ledger row loop (`:2470`, `:2509`)
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:386-400` (`M`'s definition and its closed route list), `:405-425` (the worked `M=0` record), `:472-479` (the ownable predicate), `:512-522` (the deletion bullet)
- Modify: `plugins/superb/skills/pipeline/SKILL.md:288-302` (the `M=0` section and its worked record)
- Modify: `plugins/superb/skills/pipeline/templates/findings.md:72-80` (the `State` values and the closure conditions)
- Modify: `tools/fixtures/run-fixloop/findings.md` (a conforming `withdrawn` row)
- Modify: `tools/check-plugin-mutants.sh`

**Interfaces:**
- Consumes: nothing from Tasks 1–3.
- Produces: module-level `delrt`, `withrt`, `withok` compiled patterns beside
  `route` and `pinrt`, used only inside the `M=0` block. No later task reads them.

- [ ] **Step 1: Narrow the accepted routes and forbid the commit-producing one**

`tools/check-plugin.py:1250`. Replace the `route` line and add its siblings:

```python
# ROUTES ARE KEYED ON WHETHER THE REPOSITORY CHANGED, not on the route's name.
# `deleted` used to sit here beside `user-ruled false positive` on the
# reasoning that neither leaves a commit a reviewer could be assigned — true of
# a false positive, false of a deletion. A deletion-only commit is still a
# commit, so `deleted` becomes a FORBIDDEN route on an `M=0` round, exactly as
# `pinned by` already is, and it takes the fix loop like every other finding.
route  = re.compile(r"\bF-\d+\s*,?\s+(user-ruled false positive|withdrawn)")
pinrt  = re.compile(r"\bpinned by\b")
delrt  = re.compile(r"\bdeleted\b")
# `withdrawn` MUST STATE ITS REASON. A bare `withdrawn` is precisely the escape
# hatch the design forbids: it would absorb "the orchestrator disagrees" and
# "the finding seems low value", which are routes INTO the fix loop, not out of
# it. Only a duplicate, a malformed finding, or one superseded by another — and
# only with no repository change behind it.
withrt = re.compile(r"\bwithdrawn\b")
withok = re.compile(r"\bwithdrawn\s*(?:->|→)\s*"
                    r"(?:superseded by F-\d+|duplicate of F-\d+|malformed)\b")
```

- [ ] **Step 2: Report the two new problems inside the `M=0` block**

`tools/check-plugin.py`, in the `M=0 → no round` block. Replace the
"names no closure route" problem and add two more, immediately after the
`pinrt` problem so the forbidden routes read together:

```python
                if not route.search(body):
                    probs.append("names no closure route — every F-ID needs "
                                 "`user-ruled false positive` or `withdrawn "
                                 "→ <reason>` after it")
```

```python
                if delrt.search(body):
                    probs.append("names a `deleted` route, which no `M=0` "
                                 "round can carry — deleting the claim is a "
                                 "repository change, and a deletion-only "
                                 "commit is still a commit, so it is owed a "
                                 "fix plan and a focused re-review like any "
                                 "other fix")
                if withrt.search(body) and not withok.search(body):
                    probs.append("names a bare `withdrawn` route — a "
                                 "withdrawal is a duplicate, a malformed "
                                 "finding, or one superseded by another, and "
                                 "it must say which: `withdrawn → duplicate "
                                 "of F-NNN`, `withdrawn → superseded by "
                                 "F-NNN`, or `withdrawn → malformed`")
```

And the REMEDY at the end of that block, so the message prescribes a shape the
arm accepts:

```python
                        + "carrying `reports` or `coverage` is claiming reviewers a "
                        "round of nobody never had, and one naming a pin or a "
                        "deletion is not an `M=0` iteration at all. REMEDY: write "
                        "it as `→ round <n>: M=0 → no round · closures: F-018 "
                        "user-ruled false positive, F-019 withdrawn → duplicate "
                        "of F-011 → no findings`")
```

- [ ] **Step 3: Add the ledger arm — a withdrawal names no commit**

`tools/check-plugin.py`, in the `--run` block's ledger row loop. Beside `_ci`
(`:2470`), add the optional column index:

```python
                  _ci = {k: _hdr.index(k) for k in ("id", "sev", "phase", "state")}
                  # OPTIONAL BY DESIGN: `templates/findings.md` requires only
                  # the four names above, so `Closed by` may be absent and the
                  # withdrawal check below is guarded on it rather than
                  # assuming it.
                  _cbi = _hdr.index("closed by") if "closed by" in _hdr else None
```

And immediately after `_lrows += 1`, before the `state != "open"` skip — a
withdrawn row is not open, so a check placed after the skip would never run:

```python
                      # A WITHDRAWN FINDING HAS NO FIX COMMIT. `withdrawn` means
                      # duplicate, malformed, or superseded, with no repository
                      # change behind it; a hash in `Closed by` is the evidence
                      # that a change was made, and a finding with a fix commit
                      # takes the fix loop. The linter cannot count commits — it
                      # can refuse the row that names one.
                      if (_cbi is not None
                              and _norm(_cells[_ci["state"]]) == "withdrawn"):
                          _h = next((h for h in re.findall(
                                        r"\b[0-9a-f]{7,40}\b", _cells[_cbi])
                                     if re.search(r"[0-9]", h)), None)
                          if _h:
                              _untrusted = True
                              bad(f"{relpath(_ledger)}: "
                                  f"{_norm(_cells[_ci['id']]).upper()} is "
                                  f"`withdrawn` while `Closed by` names {_h!r} — "
                                  "a commit hash is evidence that the repository "
                                  "changed for this finding, and a finding with a "
                                  "fix commit cannot be withdrawn. `withdrawn` is "
                                  "a duplicate, a malformed finding, or one "
                                  "superseded by another, with nothing committed. "
                                  "REMEDY: close it through the fix loop — fix "
                                  "plan, fix, focused re-review — or, if it really "
                                  "was a duplicate, drop the hash")
```

**A digit is required in the token** so an English word made only of hex letters
(`deface`, `added`) cannot be read as a hash.

Cite the mutants above the `--run` block's citation comment:

```python
#          "run ledger withdrawn row names a fix commit",
```

- [ ] **Step 4: Run the gate to verify it fails**

Run: `./tools/check-plugin.sh 2>&1 | grep -E 'FAIL|no closure route|deleted'`
Expected: `FAIL` on the two worked `M=0` records that still say `deleted` —
`references/fix-loop.md:412` and `SKILL.md:297`. That is the arm going RED
against the un-fixed repo, and it is the whole point of ordering the arm first.

- [ ] **Step 5: Rewrite `M`'s definition and its route list**

`references/fix-loop.md:386-400`. Replace the closed-list sentence:

```markdown
   A targeted F-ID is excluded exactly when its closure route **changed nothing
   in the repository**: a **user-ruled false positive**, or a **withdrawal**.
   The list is keyed on that predicate, not on the routes' names, and it is
   closed. **A deletion is not on it** — deleting the claim is a repository
   change, and a deletion-only commit is a commit a reviewer can be assigned, so
   a deletion stays in `M` for the same reason a pin does. **A pin is not on it
   either**: it commits a test.
```

Then the `M=0` licence, in the same passage:

```markdown
   An iteration whose every targeted F-ID left by one of those two routes
   therefore has `M=0` and **runs no round**. `M=0` is legal only when the
   iteration produced **zero repository-changing commits** — any commit at all
   means `M >= 1` and a round is owed:

   ```
   NO REPOSITORY CHANGE → re-review may be unnecessary
   ANY FIX COMMIT       → fix plan → fix implementation → re-review
   ```
```

- [ ] **Step 6: Define `withdrawn` where the routes are named**

`references/fix-loop.md`, directly beneath the route list from Step 5:

```markdown
   **`withdrawn` is narrow, and defined so it cannot become an escape hatch.** A
   finding is `withdrawn` when it is removed during consolidation or
   reconciliation because it is an exact **duplicate** of another stable F-ID,
   **malformed** or not actually a finding, or **superseded** by another finding
   that fully represents the same issue — **and no repository change has been
   made for it.** It may be marked `withdrawn` only *before* any fix commit for
   it exists, and the ledger records which reason:

   ```
   withdrawn → superseded by F-NNN | duplicate of F-NNN | malformed
   ```

   It does **not** mean any of these, and each is a route into the fix loop
   rather than out of it: the orchestrator disagrees with the finding; the
   finding seems low value; ignoring it is the easiest fix; text or code was
   deleted; code was changed; tests were changed; documentation was changed; the
   finding was partially fixed; a reviewer stopped mentioning it. **If any
   repository-changing commit exists for the finding, `withdrawn` is
   forbidden.**
```

- [ ] **Step 7: Fix the two worked `M=0` records**

`references/fix-loop.md:405-425`. The record currently reads
`→ round 3: M=0 → no round · closures: F-018 deleted, F-019 user-ruled false
positive → no findings`. Both worked records are the arm's positive input, read
through `lint_review_lines`' prose call site, so they must become shapes the
narrowed regex accepts:

```
      → round 3: M=0 → no round · closures: F-018 user-ruled false positive,
        F-019 withdrawn → duplicate of F-011 → no findings
```

`SKILL.md:297` the same way:

```
      → round 4: M=0 → no round · closures: F-021 withdrawn → malformed → no findings
```

- [ ] **Step 8: Take the deletion exemptions out of the ownable predicate**

`references/fix-loop.md:472-479` — the ownable qualifier currently carves out a
deletion's commit:

```markdown
**Ownable** is the qualifier the rows are keyed on: an ownable commit is one a
reviewer can be assigned, which is **every commit the fix-mode run produced**.
`M` is counted over that same predicate — a targeted F-ID is out of `M` exactly
when its closure changed nothing in the repository (step 3, above) — so an
iteration with no commit is an iteration with `M=0`, and it has no row here at
all, not even the first row, because its round was never owed.
```

`references/fix-loop.md:512-522` — replace the deletion bullet outright:

```markdown
- **A claim finding closed by deletion is counted in `M`, and its commit is in
  the coverage union.** Deleting the claim is a repository change: the sentence
  is gone, the file is different, and a reviewer can read the diff. So a
  deletion takes the same path as any other fix — fix plan, deletion commit,
  focused re-review, then close — and its commit is assigned to a slice like
  every other. **A pin is counted too**, and its commit is in the union: a pin
  commits a test, and "a failing or vacuous test" is one of the re-tag
  predicate's Major branches, which no reviewer is in a position to apply to a
  test nobody was assigned.
```

- [ ] **Step 9: Update the ledger template**

`templates/findings.md:72`. The `State` list gains the new value and the
closure conditions gain the withdrawal:

```markdown
**State** is one of `open`, `closed`, `false-positive`, `withdrawn`. Closing
requires either:
```

Add beneath the existing closure conditions:

```markdown
`withdrawn` is not a closure — it is a removal, and it is narrow: a duplicate of
another stable F-ID, a malformed non-finding, or one superseded by a finding that
fully represents the same issue, **with no repository change made for it**. Write
the reason in `Closed by` as `withdrawn → duplicate of F-NNN`,
`withdrawn → superseded by F-NNN`, or `withdrawn → malformed`, and **never a
commit hash** — a hash means a commit exists, and a finding with a fix commit
takes the fix loop instead. A deletion is a fix, not a withdrawal.
```

- [ ] **Step 10: Give the ledger arm a conforming row**

`tools/fixtures/run-fixloop/findings.md`. Add one row to the blocking table, so
the ledger arm has a positive input as well as a mutant:

```
| F-003 | Major | 2 | `src/b.py:20` | a duplicate of F-002, raised by a second reviewer | withdrawn | withdrawn → duplicate of F-002 |
```

Extend that fixture's header prose by one sentence, because a fixture row with
no stated reason is a row a later edit will "tidy":

```markdown
`F-003` is `withdrawn` as a duplicate of `F-002`, with no hash in `Closed by` —
the shape the withdrawal arm must accept. Put a commit hash in that cell and the
arm fires: a finding with a fix commit cannot be withdrawn.
```

- [ ] **Step 11: Run the gate to verify it passes**

Run: `./tools/check-plugin.sh && for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d; done`
Expected: no `FAIL`. `F-003` is not `open`, so it does not enter `_blockers` and
`run-fixloop`'s no-advance expectations are unchanged.

- [ ] **Step 12: Add the mutants**

Insert immediately **before** the harness summary block:

```bash
run_mutant "M=0 round names a deleted route" '
f=plugins/superb/skills/pipeline/SKILL.md
if ! grep -qF "F-021 withdrawn → malformed" "$f"; then
  echo "mutant is a no-op: the worked M=0 record is not in the expected shape"
else
  sed -i "s|F-021 withdrawn → malformed|F-021 deleted|" "$f"
  grep -qF "F-021 deleted" "$f" || echo "mutant is a no-op: the route was not swapped"
fi'

run_mutant "M=0 round names a bare withdrawn" '
f=plugins/superb/skills/pipeline/SKILL.md
if ! grep -qF "F-021 withdrawn → malformed" "$f"; then
  echo "mutant is a no-op: the worked M=0 record is not in the expected shape"
else
  sed -i "s|F-021 withdrawn → malformed|F-021 withdrawn|" "$f"
  grep -q "F-021 withdrawn *→" "$f" && echo "mutant is a no-op: the reason survived the edit"
fi'

run_mutant "run ledger withdrawn row names a fix commit" '
enable_run || exit 0
f=tools/fixtures/run-fixloop/findings.md
if [ "$(grep -c "| withdrawn | withdrawn → duplicate of F-002 |" "$f")" != 1 ]; then
  echo "mutant is a no-op: the withdrawn row is not in the expected shape"
else
  sed -i "s#| withdrawn | withdrawn → duplicate of F-002 |#| withdrawn | fix \`9c3a1f7\` |#" "$f"
  grep -qF "9c3a1f7" "$f" || echo "mutant is a no-op: the hash was not written"
fi'
```

**`grep -qF -- ` is not needed here** because no pattern begins with `-`; where
one does, `grep` on this machine is **ugrep** and parses it as an option, so a
`--` is mandatory. The rule is documented above `run_mutant()`.

- [ ] **Step 13: Verify the mutants kill**

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep -E 'deleted route|bare withdrawn|withdrawn row names|killed=|SURVIVED|NO-OP'`
Expected: three `killed`, and `survived=0 no-op=0`.

- [ ] **Step 14: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py tools/check-plugin-mutants.sh tools/fixtures/run-fixloop
git commit -m "fix(pipeline): a deletion is a commit, so it owes a re-review

M's exclusion list was keyed on the route's name rather than on whether the
repository changed. That was true of a user-ruled false positive and false of a
deletion: deleting the claim opened no re-review round and its commit was left
out of the coverage union, so finding -> delete text -> mark closed -> no review
was a legal path.

M=0 now means the iteration produced zero repository-changing commits. deleted
comes off the closed list and takes the fix loop like any other finding; the
closed list is user-ruled false positive and withdrawn.

withdrawn is defined narrowly so it cannot become an escape hatch -- a
duplicate, a malformed finding, or one superseded by another, with nothing
committed -- and it must state which. The linter cannot count commits, so it
refuses an M=0 round naming a deletion, a bare withdrawn with no reason, and a
ledger row that is withdrawn while Closed by names a hash."
```

---

# Phase 4 — Lanes

Goal: one canonical lane grammar, a persisted `phase → lane` mapping the linter
validates rather than re-derives, per-lane advancement, deterministic join
collapse, and per-lane resume.

A lane is an **active execution branch between a fork and a join** — not a
maximal dependency chain. In a diamond `A → B,C → D`, `A` and `D` sit on both
maximal chains, so chain membership is not a partition and *"which lane owns
this phase"* has no answer. Every task in this phase depends on that: the
mapping is written once at GATE 2, persisted on the phase headings, and checked.

---

### Task 5: The canonical lane grammar, and per-lane advancement

**Root cause being fixed:** `templates/progress.md:11` prescribes a single
`**Next action:**` field while `references/parallel.md:167` requires one per
active lane, and `SKILL.md:176` sides with the template. There is no per-lane
tracker syntax at all. The linter reads at most two fields with `re.search`
(first match only, `check-plugin.py:2631-2633`), its duplicate guard at `:2594`
is hardcoded to `"Phase"`, and its comparison is
`max(_named) > _blockers[0][0]` (`:2656`) — latest named position against the
earliest unfinished phase *anywhere*. Lane B legitimately at phase 6 while lane
A's phase 2 is open makes that true, so **a conforming two-lane tracker
hard-fails the gate today**.

**Files:**
- Modify: `tools/check-plugin.py:2124-2133` (`parse_tracker_phases` keeps the heading), a new `parse_phase_lanes` after `:2148`, `:2334-2336` (the lane mapping beside `_idx`), `:2593-2700` (the whole Current State block)
- Modify: `plugins/superb/skills/pipeline/templates/progress.md:8-14` (Current State), the phase-heading legend
- Modify: `plugins/superb/skills/pipeline/SKILL.md:176` (the Current State description)
- Modify: `plugins/superb/skills/pipeline/references/run-state.md:55-70` (the heading grammar), `:100-115` (Current State)
- Modify: `plugins/superb/skills/pipeline/references/parallel.md:60-70` (lane derivation), `:160-172` (the per-lane `Next action` requirement)
- Modify: `tools/fixtures/run-ok/progress.md`, `run-open-rv/progress.md`, `run-fixloop/progress.md`
- Modify: `tools/check-plugin-mutants.sh` (17 mutants retargeted)

**Interfaces:**
- Produces: `parse_phase_lanes(phases) -> (lanes, deps, multi)` where `lanes` is
  `{phase index: lane id}`, `deps` is `{phase index: [dep indexes]}` and `multi`
  is `[(phase index, [lane ids])]` for headings carrying more than one field.
  Tasks 6 and 7 consume all three. `parse_tracker_phases` entries gain
  `"heading"` — the raw heading line.
- Produces: `_lanemap`, `_depmap`, `_lane_named` (a list of `(lane id, phase
  index)`) inside the `--run` block. Task 7's arms read them.

- [ ] **Step 1: Keep the heading line on every parsed phase**

`tools/check-plugin.py:2131`. The heading regex stops at `—` and `·`, so the
fields after the name are discarded today and `· deps:` has never been read:

```python
            cur = {"label": f"Phase {mh.group(1).strip()}", "line": n,
                   # THE WHOLE HEADING IS KEPT, because the fields after the
                   # name are where `· deps:` and `· lane:` live and the label
                   # regex deliberately stops before them. Reading them here
                   # rather than re-splitting the file elsewhere keeps one
                   # parser of one grammar.
                   "heading": line,
                   "tasks": [], "reviews": []}
```

Update the docstring's returned-shape paragraph to name `heading`.

- [ ] **Step 2: Write the lane-mapping parser**

`tools/check-plugin.py`, immediately after `parse_tracker_phases` (`:2148`):

```python
_LANEFLD = re.compile(r"·\s*lane:\s*([A-Z][A-Za-z0-9]*)")
_DEPSFLD = re.compile(r"·\s*deps:\s*([^·]*)")


def parse_phase_lanes(phases):
    """`{index: lane id}`, `{index: [dep indexes]}`, and the multi-lane headings.

    Read from the phase headings and from NOTHING ELSE. A lane is an active
    execution branch between a fork and a join, not a maximal dependency
    chain: in a diamond `A → B,C → D`, `A` and `D` sit on both maximal chains,
    so chain membership is not a partition and "which lane owns this phase"
    has no answer. The mapping is therefore allocated once at GATE 2,
    persisted on the headings so it survives compaction and resume, and
    VALIDATED here — never re-derived by enumerating chains.
    """
    idx = {ph["label"].lower(): i for i, ph in enumerate(phases)}
    lanes, deps, multi = {}, {}, []
    for i, ph in enumerate(phases):
        head = ph.get("heading", "")
        found = _LANEFLD.findall(head)
        if len(found) > 1:
            multi.append((i, found))
        if found:
            lanes[i] = found[0]
        dd, m = [], _DEPSFLD.search(head)
        if m:
            for t in re.findall(r"[0-9]+[0-9A-Za-z.]*", m.group(1)):
                j = idx.get(f"phase {t.lower()}")
                # A DEP NAMING A PHASE THIS TRACKER LACKS is dropped here and
                # reported by the arm that owns unresolvable references. This
                # helper returns what it could read, never a guess.
                if j is not None:
                    dd.append(j)
        deps[i] = sorted(set(dd))
    return lanes, deps, multi
```

`· deps: none` yields no ids and therefore an empty list, which is what "no
dependency" means to every consumer.

- [ ] **Step 3: Validate the mapping's well-formedness**

`tools/check-plugin.py:2334`, beside `_idx` and before `_blockers` is consumed:

```python
        _lanemap, _depmap, _lanemulti = parse_phase_lanes(_phs)
        for _i2, _found in _lanemulti:
            _untrusted = True
            bad(f"{relpath(tracker)}: {_phs[_i2]['label']}'s heading carries "
                f"{len(_found)} `· lane:` fields ({', '.join(_found)}) — a "
                "phase is executed by exactly one active lane, and this gate "
                "reads the first, so a second field is a lane assignment "
                "nobody validates. REMEDY: one `· lane:` per heading")
        _nolane = [ph["label"] for _i2, ph in enumerate(_phs)
                   if _i2 not in _lanemap]
        if _phs and _nolane:
            _untrusted = True
            bad(f"{relpath(tracker)}: {_nolane[0]}'s heading carries no "
                "`· lane:` field"
                + (f", and so do {len(_nolane) - 1} more" if len(_nolane) > 1
                   else "")
                + " — the phase → lane mapping is persisted on the headings so "
                "it survives compaction and resume, and a phase with no lane "
                "is one no per-lane check can reach. A sequential run assigns "
                "every phase `· lane: A`. REMEDY: assign every phase its lane "
                "at GATE 2, as `templates/progress.md` ships it")
```

- [ ] **Step 4: Replace the Current State reader**

`tools/check-plugin.py:2593-2651`. Delete the `**Phase:**` duplicate guard, the
missing-`**Phase:**` report, `_named_phase`, the `_na_*`/`_ph_*` resolutions and
the per-field loop. In their place — `_FIELDRE` stays, because the retired
fields still have to be recognised to be refused:

```python
        _FIELDRE = r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?\*\*%s:\*\*"
        _LANERE = re.compile(
            r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?\*\*Lane\s+([A-Z][A-Za-z0-9]*):\*\*"
            r"\s*(.*)$", re.M)
        # `done` and `waiting at join Phase <id>` are the two blessed phase-less
        # forms. Everything else that names no phase is a value this arm
        # reports rather than guesses at.
        _PHASELESS = re.compile(r"^\s*(?:done\b|waiting at join\b)", re.I)

        # THE OLD TWO-FIELD GRAMMAR IS GONE, and its absence is REPORTED rather
        # than tolerated. Keeping `**Phase:**` for single-lane runs would mean
        # two grammars and a mode switch in this gate, and a mode-switch branch
        # is what produced most of the defects this change repairs.
        for _dead in ("Phase", "Next action"):
            if re.search(_FIELDRE % _dead, _csblock, re.M):
                _untrusted = True
                bad(f"{relpath(tracker)}: Current State carries a "
                    f"`**{_dead}:**` field, which this grammar replaced with "
                    "one `- **Lane <id>:**` line per active lane — a sequential "
                    "run writes exactly one, `- **Lane A:** …`. REMEDY: write "
                    "the lane lines `templates/progress.md` ships")

        _seen_lane, _lane_cs = set(), []
        for _lid, _val in _LANERE.findall(_csblock):
            if _lid in _seen_lane:
                _untrusted = True
                bad(f"{relpath(tracker)}: two or more `**Lane {_lid}:**` lines "
                    "inside the `## Current State` block, and this gate reads "
                    "the first — so a stale line left above a fresh one is the "
                    "one that counts. This is RR5-4's rule one level down: a "
                    "lane's position must live in exactly one place. REMEDY: "
                    "keep one line per lane, and replace its value rather than "
                    "adding a line")
                continue
            _seen_lane.add(_lid)
            _lane_cs.append((_lid, _val))

        if _phs and not _lane_cs:
            _untrusted = True
            bad(f"{relpath(tracker)}: no `**Lane <id>:**` line inside a "
                "`## Current State` block — those lines are where the "
                "advancement check reads each lane's position, so it read "
                "nothing and compared nothing. An unreadable position must not "
                "read as a satisfied one. REMEDY: keep the Current State block "
                "at the top, as `templates/progress.md` ships it")

        def _resolve_phase(value):
            """`(phase index, raw id)` for a lane line's value."""
            # ANCHORED AT THE START, and that is the whole of the fix for a
            # Critical. Searching the value for `phase <token>` anywhere read a
            # MENTIONED phase in preference to the named one: `Phase 3 — moved
            # on past the phase 2 fix loop` resolved to 2, and the gate passed
            # over a finding open against Phase 2. A lane line names its phase
            # FIRST — `templates/progress.md` prescribes
            # `- **Lane <id>:** Phase <id> — <that lane's next unchecked line>`.
            g = re.match(r"\s*(?:[Pp]hase\s+)?([0-9]+[0-9A-Za-z.]*)\b", value)
            if not g:
                return None, None
            return _idx.get(f"phase {g.group(1)}".lower()), g.group(1)

        _lane_named = []
        for _lid, _val in _lane_cs:
            _i, _pid = _resolve_phase(_val)
            if _pid is not None and _i is None:
                _untrusted = True
                bad(f"{relpath(tracker)}: Current State's `**Lane {_lid}:**` "
                    f"names phase {_pid!r}, which matches no `## Phase` heading "
                    "in this tracker — so the advancement check could not "
                    "locate that lane's own position and compared nothing. "
                    "REMEDY: name a phase the tracker has")
                continue
            if _i is None:
                if not _PHASELESS.match(_val):
                    _untrusted = True
                    bad(f"{relpath(tracker)}: Current State's "
                        f"`**Lane {_lid}:**` names no phase and is not one of "
                        "the two phase-less forms — its value is "
                        f"{_val.strip()[:40]!r}. A lane line is `Phase <id> — "
                        "<that lane's next unchecked line>`, or `done`, or "
                        "`waiting at join Phase <id>`. An executor writes a "
                        "phase-less value exactly when it believes that lane is "
                        "over, which is precisely when it may be wrong about an "
                        "open finding. REMEDY: name the lane's phase")
                continue
            if _lanemap and _lid not in set(_lanemap.values()):
                _untrusted = True
                bad(f"{relpath(tracker)}: Current State names "
                    f"`**Lane {_lid}:**`, which no `## Phase` heading carries as "
                    "`· lane:` — the mapping is persisted on the headings and "
                    "Current State is checked against it, so a lane existing "
                    "only here is a position this gate cannot validate. "
                    "REMEDY: assign the lane on its phases' headings at GATE 2")
                continue
            _lane_named.append((_lid, _i))
```

- [ ] **Step 5: Make the comparison per lane**

`tools/check-plugin.py:2656`. Replace the global comparison and its affirmative
cascade:

```python
        # ONE LANE'S OPEN WORK NEVER FAILS ANOTHER LANE. The old comparison was
        # `max(_named) > _blockers[0][0]` — the latest named position against
        # the earliest unfinished phase ANYWHERE — so Lane B legitimately at
        # phase 6 while Lane A's phase 2 was open made it true, and a
        # conforming two-lane tracker hard-failed this gate. Each lane is now
        # compared against the earliest unfinished phase ASSIGNED TO IT.
        _adv = []
        for _lid, _i in _lane_named:
            _own = [b for b in _blockers if _lanemap.get(b[0]) == _lid]
            if _own and _i > _own[0][0]:
                _adv.append((_lid, _own[0]))
        if _adv:
            for _lid, _b in _adv:
                bad(f"{relpath(tracker)}: Current State's `**Lane {_lid}:**` "
                    f"names a phase later than {_b[1]}, which is assigned to "
                    f"that lane and still has {_b[2]} — a phase is complete "
                    "only when its tasks are `[x]`, its `RV` is `[x]` and every "
                    "blocking finding scoped to it is closed. Advancing here is "
                    "the orchestration failure this gate exists for: "
                    "implementation complete is not phase complete, and an "
                    "empty ledger is what an unreviewed phase looks like too. "
                    "REMEDY: point that lane at its own next action — its "
                    "review, or its fix loop")
        # THE RULE THE WHOLE ARM OBEYS: never print an affirmative line about a
        # comparison that did not happen.
        elif _blockers and not _lane_named:
            bad(f"{relpath(tracker)}: {_blockers[0][1]} has "
                f"{_blockers[0][2]}, and no lane line names a phase — so there "
                "is nothing to compare it against and the advancement "
                "invariant is uncheckable on this tracker. REMEDY: name the "
                "phase on the lane that owns it")
        elif _lane_named and not _untrusted:
            ok("no lane points past an unfinished phase of its own"
               + _ledger_note)
        elif _phs and not _blockers and not _untrusted:
            ok("no unfinished phase in the tracker" + _ledger_note)
```

- [ ] **Step 6: Run the gate to verify it fails**

Run: `for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d; done 2>&1 | grep -E 'FAIL|Lane|lane'`
Expected: every fixture `FAIL`s — each still writes `**Phase:**`/`**Next
action:**` and carries no `· lane:` on any heading. That is the arm RED against
the un-migrated grammar; Steps 7–9 turn it GREEN.

- [ ] **Step 7: Migrate the template**

`templates/progress.md`. Replace the Current State block:

```markdown
## Current State
- **Lane A:** Phase 2 — T3
- **Last updated:** <timestamp>
- **Run directory:** <PROJECT_DIR>/docs/superpowers/runs/YYYY-MM-DD-<topic>/
```

Add the grammar beneath it:

```markdown
**One line per active lane, and a sequential run has exactly one: `Lane A`.**
`**Lane <id>:**` where `<id>` is `[A-Z][A-Za-z0-9]*`. The value is
`Phase <phase-id> — <that lane's next unchecked line>`, phase id first. Two
phase-less values are legal: `done`, when that lane has nothing unfinished, and
`waiting at join Phase <id>`, when the lane's own phases are all `PASS` but its
join has not opened. There is no `**Phase:**` field and no `**Next action:**`
field — one grammar, no mode switch.
```

And the phase-heading legend:

```markdown
## Phase <n> — <name> · deps: <phases, or none> · lane: <id>
```

```markdown
**`· lane:` is the persisted lane assignment**, written at GATE 2 for every
phase and never recomputed. `· deps:` says whether a phase *may* execute;
`· lane:` says which concurrent execution branch executes it. The mapping lives
here so `phase → lane` survives compaction and resume without depending on
anything the orchestrator remembers.
```

- [ ] **Step 8: Migrate the reference prose**

`SKILL.md:176` — replace the single-`Next action` description with the lane
grammar above, in one sentence plus the worked block.

`references/run-state.md` — the Current State grammar and the heading grammar
take the same two blocks; the `**Phase:**`/`**Next action:**` descriptions go.

`references/parallel.md:167` — the requirement is already per-lane, so it
becomes the grammar rather than a contradiction:

```markdown
Current State carries **one `- **Lane <id>:**` line per active lane**, each
naming that lane's phase and its first unchecked line inside it. That is the
only per-lane position a run records, and it is checked against the `· lane:`
assignments on the phase headings.
```

`references/parallel.md:60-70` — replace lane *derivation* with lane
*allocation*, because computing lanes from chains is the defect:

```markdown
**Lanes are allocated at GATE 2, not derived on every read.** A lane is an
active execution branch between a fork and a join. Walking the approved plan's
phases in approved-plan order: the first phase takes `Lane A`; at a fork, the
successor first in approved-plan order keeps the forking phase's lane and each
further successor takes the next unused id; at a join, the joining phase carries
the lane of its **first contributing predecessor in approved-plan order**, which
survives while the others retire when the leading `RVJ` closes. Write each
assignment on the phase's heading as `· lane: <id>`.

**Do not compute a phase's lane from its dependency chains.** In a diamond
`A → B,C → D`, the maximal chains are `A → B → D` and `A → C → D`, so `A` and
`D` belong to both: chain membership is not a partition, and a phase on two
lanes has no owner. The DAG decides whether a phase may execute; the lane id
records which branch executes it.
```

- [ ] **Step 9: Migrate the three fixtures**

Each tracker's Current State collapses to one lane line, and every heading gains
`· lane: A` — all three fixtures are sequential runs.

`tools/fixtures/run-ok/progress.md`:

```markdown
## Current State
- **Lane A:** done (fixture)
- **Last updated:** 2026-09-05
- **Run directory:** tools/fixtures/run-ok/
```

```
## Phase 1 — fixture, single report file · deps: none · lane: A
## Phase 2 — fixture, brace-expanded report set · deps: Phase 1 · lane: A
## Phase 3 — fixture, a record longer than the old byte window · deps: Phase 2 · lane: A
## Phase 4 — fixture, multi-slice with no integration boundary · deps: Phase 3 · lane: A
```

`tools/fixtures/run-open-rv/progress.md`:

```markdown
- **Lane A:** Phase 2 — RV
```

```
## Phase 1 — fixture, closed · deps: none · lane: A
## Phase 2 — fixture, implemented and unreviewed · deps: Phase 1 · lane: A
## Phase 3 — fixture, a joining phase, not started · deps: Phase 2 · lane: A
```

`tools/fixtures/run-fixloop/progress.md`:

```markdown
- **Lane A:** Phase 2 — fix loop round 3, write the round's fix plan for F-002
```

```
## Phase 1 — fixture, closed · deps: none · lane: A
## Phase 2 — fixture, implemented and reviewed, a finding still open · deps: Phase 1 · lane: A
## Phase 3 — fixture, not started · deps: Phase 2 · lane: A
```

Then fix each fixture's own header prose, which describes the old fields by
name: `run-open-rv` says *"`Next action` names Phase 2's `RV`"* and `run-fixloop`
says *"So `Next action` names Phase 2's fix loop instead"*. Both become
*"`Lane A` names …"*. **A fixture whose prose describes a grammar it no longer
writes is how the next editor reintroduces the old one.**

- [ ] **Step 10: Run the gate to verify it passes**

Run: `./tools/check-plugin.sh && for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d; done`
Expected: no `FAIL`, and each `--run` prints
`no lane points past an unfinished phase of its own` — except `run-ok`, whose
lane is `done`, which prints `no unfinished phase in the tracker`.

- [ ] **Step 11: Retarget every mutant that wrote the old fields**

Seventeen mutants in `tools/check-plugin-mutants.sh` write `**Phase:**` or
`**Next action:**`; against the migrated fixtures each one becomes a no-op, and
the harness fails a self-declared no-op even when it kills. Retarget them all —
`sed -n '/^run_mutant/{=;p}' tools/check-plugin-mutants.sh` locates each:

| Mutant | Retarget |
|---|---|
| `run tracker advances past a phase with an open RV` | `s\|^- \*\*Lane A:\*\*.*\|- **Lane A:** Phase 3 — T3\|` |
| `run tracker advances past a phase with an open blocking finding` | same substitution, `run-fixloop` |
| `run tracker next action names a later phase than its own state` | rename to `run tracker lane names a later phase than its own state`, same substitution |
| `implemented-unreviewed fixture advances to the next phase` | guard on `Lane A:** Phase 2 — RV`, write `Phase 3 — T6` |
| `fix-loop fixture advances with a blocking finding open` | guard on `Lane A:** Phase 2 — fix loop`, write `Phase 3 — T4` |
| `run tracker phase carries no RV line at all` | lane line moved to `Phase 3` |
| `run tracker ledger row bolds its severity` | lane line moved to `Phase 3` |
| `run tracker Current State phase advances while Next action does not` | **restate** as `run tracker Current State keeps the retired Phase field` — insert `- **Phase:** 2 — stale` above the lane line, killing on the retired-field arm |
| `run tracker Current State names a mentioned phase` | `- **Lane A:** Phase 3 — moved on past the phase 2 fix loop` |
| `run tracker second blocking table gates nothing` | lane line unchanged; only its `**Phase:**` reference in the guard changes |
| `run tracker Current State is shadowed by a prose decoy` | decoy becomes a prose `- **Lane A:**` line outside the block; keep the substitute-then-insert order and the positional assertions |
| `run tracker ledger row id is bolded` | lane line moved to `Phase 3` |
| `run tracker grows a second Current State block` | second block carries a lane line |
| `run tracker ledger row id is not F-<n>` | lane line moved to `Phase 3` |
| `run tracker Phase field resolves to nothing` | rename to `run tracker lane line resolves to nothing`; write `- **Lane A:** moved on` — no phase, and not a blessed phase-less form |
| `run tracker hides a stale Phase field above the fresh one` | rename to `run tracker hides a stale Lane A line above the fresh one`; insert a second `- **Lane A:**` above the fresh one |
| `run tracker ledger row id has a letter after the dash` | lane line moved to `Phase 3` |

Add two mutants for the arms Step 3 introduced, immediately before the harness
summary block:

```bash
run_mutant "run tracker phase heading carries no lane" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "^## Phase 2 .* · lane: A$" "$f")" != 1 ]; then
  echo "mutant is a no-op: Phase 2s heading is not in the expected shape"
else
  sed -i "s|^\(## Phase 2 .*\) · lane: A$|\1|" "$f"
  grep -q "^## Phase 2 .* · lane:" "$f" && echo "mutant is a no-op: the lane field survived"
fi'

run_mutant "run tracker phase heading carries two lanes" '
enable_run || exit 0
f=tools/fixtures/run-ok/progress.md
if [ "$(grep -c "^## Phase 3 .* · lane: A$" "$f")" != 1 ]; then
  echo "mutant is a no-op: Phase 3s heading is not in the expected shape"
else
  sed -i "s|^\(## Phase 3 .* · lane: A\)$|\1 · lane: B|" "$f"
  grep -q "^## Phase 3 .* · lane: A · lane: B$" "$f" || echo "mutant is a no-op: the second lane field was not added"
fi'
```

Cite every new mutant name in the `--run` block's citation comment.

- [ ] **Step 12: Verify the whole harness**

Run: `./tools/check-plugin-mutants.sh`
Expected: `killed=<N> survived=0 no-op=0`. **Never pipe this through `tail`** —
it discards the no-op diagnostics, which is exactly the signal a retargeted
mutant gets wrong.

- [ ] **Step 13: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py tools/check-plugin-mutants.sh tools/fixtures
git commit -m "feat(pipeline): one lane line per active lane, compared per lane

The template prescribed a single Next action field, parallel.md required one per
active lane, and SKILL.md sided with the template. There was no per-lane tracker
syntax at all, and the linter compared the latest named position against the
earliest unfinished phase anywhere -- so a conforming two-lane tracker
hard-failed the gate.

Current State is now one - **Lane <id>:** line per active lane, with Lane A for a
sequential run and no Phase/Next action fields to switch modes on. The
phase -> lane mapping is persisted on the phase headings as · lane: <id>,
allocated at GATE 2, and validated rather than re-derived: a lane is an active
execution branch between a fork and a join, and enumerating maximal dependency
chains cannot partition a diamond.

Each lane is compared against the earliest unfinished phase assigned to it, so
one lane's open work no longer fails another."
```

---

### Task 6: The `run-lanes` diamond fixture

**Root cause being fixed:** no fixture contains two lanes, so every per-lane arm
Task 5 added is exercised only by mutants against single-lane input. The
positive direction — a legal concurrent two-lane state — has no input at all,
and PR #3's costliest defects were arms that failed conforming input.

**Files:**
- Create: `tools/fixtures/run-lanes/progress.md`, `findings.md`, `agent-output/` reports
- Modify: `tools/check-plugin.py` (the rule-2 duplicate-current arm)
- Modify: `.github/workflows/checks.yml`
- Modify: `tools/check-plugin-mutants.sh` (`enable_run_dir` for the new fixture)

**Interfaces:**
- Consumes: `_lane_named`, `_lanemap` from Task 5.
- Produces: `tools/fixtures/run-lanes/` — the diamond every Task 7 arm reads.

- [ ] **Step 1: Add the rule-2 arm**

`tools/check-plugin.py`, after `_lane_named` is built:

```python
        # TWO ACTIVE LANES NEVER EXECUTE THE SAME PHASE. This is the
        # shared-ancestor failure and the double-owned-join failure in one
        # check: a joining phase named current by both contributing lanes makes
        # "which lane advances when the RVJ closes" unanswerable, and a shared
        # ancestor named by two lanes means the fork was recorded as a
        # duplication rather than a branch.
        _bycur = {}
        for _lid, _i in _lane_named:
            _bycur.setdefault(_i, []).append(_lid)
        for _i, _lids in sorted(_bycur.items()):
            if len(_lids) > 1:
                _untrusted = True
                bad(f"{relpath(tracker)}: {_phs[_i]['label']} is the current "
                    f"phase of {len(_lids)} lanes ({', '.join(_lids)}) — a "
                    "phase is executed by exactly one active lane. REMEDY: one "
                    "lane owns the phase; every other contributor writes "
                    "`waiting at join Phase <id>` until the leading `RVJ` "
                    "closes and retires it")
```

- [ ] **Step 2: Write the fixture tracker**

`tools/fixtures/run-lanes/progress.md`. The diamond is
`Phase 1 → Phase 2, Phase 3 → Phase 4`, with `Lane A` carrying 1, 2 and 4 and
`Lane B` carrying 3. Phase 2 is `PASS`, Phase 3 is still open, so `Lane A` is
waiting at the join and Phase 4 has not started:

````markdown
# Pipeline — Progress Tracker

A fixture run directory, not a real one. Its job is the one state no other
fixture can hold: **two concurrent lanes at different legal positions.** Before
this fixture existed, every per-lane arm was exercised by mutants alone and the
conforming shape had no input — which is how an arm that fails legal input ships.

The graph is the canonical diamond, `Phase 1 → Phase 2, Phase 3 → Phase 4`.
`Phase 1` forks: `Phase 2` is first in approved-plan order so it keeps `Lane A`,
and `Phase 3` takes the newly allocated `Lane B`. `Phase 4` joins, and it carries
`Lane A` because `Phase 2` is its **first contributing predecessor in
approved-plan order** — the survivor is chosen at GATE 2 and written down, never
picked at runtime.

`Phase 2` is `PASS` and `Phase 3` is still open, so this is the state the old
global comparison hard-failed: `Lane B` sits at `Phase 3` while `Lane A` has
nothing unfinished of its own, and `Lane A` writes `waiting at join Phase 4`
rather than naming `Phase 4` — a waiting contributor never names the joining
phase. `Phase 4`'s leading `RVJ` is `[ ]`, its tasks are unchecked, and neither
may start until both contributors are `PASS` and that `RVJ` is `[x]`.

## Current State
- **Lane A:** waiting at join Phase 4
- **Lane B:** Phase 3 — T3
- **Last updated:** 2026-09-07
- **Run directory:** tools/fixtures/run-lanes/

## Phase 1 — fixture, the fork · deps: none · lane: A
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, the first branch · deps: Phase 1 · lane: A
- [x] T2 — a task · W1 · deps T1 — `bbbbbbb`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p2-review-a.md · coverage p2-coverage.md → no findings

## Phase 3 — fixture, the second branch, still open · deps: Phase 1 · lane: B
- [ ] T3 — a task · W1 · deps T1
- [ ] RV — review fan-out

## Phase 4 — fixture, the join · deps: Phase 2, Phase 3 · lane: A
- [ ] RVJ — joint integration review · lanes A+B · N=1 → 0 slice + 1 integration
- [ ] T4 — a task · W1 · deps T2, T3
- [ ] RV — review fan-out
````

The `RVJ` sits **above** the first task, which is what makes it a *leading*
`RVJ` and what exempts it from the review-not-early rule by line number
(`check-plugin.py:2255-2258`).

- [ ] **Step 3: Write the fixture's ledger and reports**

`tools/fixtures/run-lanes/findings.md` — a header and an empty blocking table
with the four required column names, so the ledger half has a readable input
that contributes no blocking row:

```markdown
# Pipeline — Findings Ledger (fixture)

A fixture, not a run. Nothing is open here: this fixture's subject is lane
position, and a blocking finding would put the no-advance arm's ledger half in
the way of that. `tools/fixtures/run-fixloop` is the fixture that exercises the
ledger half.

## Blocking ledger

| ID | Sev | Phase | File:line | Finding | State | Closed by |
| -- | --- | ----- | --------- | ------- | ----- | --------- |
```

Then the four files the two closed rounds name:

```bash
mkdir -p tools/fixtures/run-lanes/agent-output
cd tools/fixtures/run-lanes/agent-output
for f in p1-review-a p1-coverage p2-review-a p2-coverage; do
  printf '# %s\n\nA fixture report. Its existence is what the round record above is checked against.\n' "$f" > "$f.md"
done
```

Give each `*-coverage.md` the one-row coverage table the coverage arm reads,
matching the shape `run-ok`'s coverage files use.

- [ ] **Step 4: Verify the fixture conforms**

Run: `./tools/check-plugin.sh --run tools/fixtures/run-lanes`
Expected: no `FAIL`, and the affirmative
`no lane points past an unfinished phase of its own`. **This is the direction
that matters most.** A `FAIL` here means an arm rejects the grammar the
templates prescribe — fix the arm, not the fixture.

- [ ] **Step 5: Wire it into CI and the harness baseline**

`.github/workflows/checks.yml` — add `run-lanes` to the `--run` matrix beside
the three existing fixtures.

`tools/check-plugin-mutants.sh` — the baseline must lint the new fixture too, or
a mutant that breaks only `run-lanes` is a mutant nothing catches. Add it
wherever `run-ok`, `run-open-rv` and `run-fixloop` are enumerated, and confirm
`enable_run_dir tools/fixtures/run-lanes` resolves.

- [ ] **Step 6: Add the mutants**

```bash
run_mutant "run tracker two lanes claim the same phase" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- **Lane A:** waiting at join Phase 4" "$f"; then
  echo "mutant is a no-op: Lane A is not waiting at the join"
else
  sed -i "s|^- \*\*Lane B:\*\*.*|- **Lane B:** Phase 3 — T3|" "$f"
  sed -i "s|^- \*\*Lane A:\*\*.*|- **Lane A:** Phase 3 — T3|" "$f"
  grep -c -- "Phase 3 — T3" "$f" | grep -qx 2 || echo "mutant is a no-op: the two lanes do not both name Phase 3"
fi'

run_mutant "run tracker lane exists only in Current State" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- **Lane B:** Phase 3 — T3" "$f"; then
  echo "mutant is a no-op: Lane Bs line is not in the expected shape"
else
  sed -i "s|^- \*\*Lane B:\*\* Phase 3 — T3|- **Lane C:** Phase 3 — T3|" "$f"
  grep -qF -- "- **Lane C:**" "$f" || echo "mutant is a no-op: the lane was not renamed"
fi'
```

**`grep -qF --` with the explicit `--`**: `grep` on this machine is ugrep, and a
pattern beginning with `-` is parsed as an option — the failure mode is a mutant
that silently disables itself and then survives, blaming the fixture.

- [ ] **Step 7: Verify the mutants kill**

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep -E 'same phase|only in Current State|killed=|SURVIVED|NO-OP'`
Expected: two `killed`, and `survived=0 no-op=0`.

- [ ] **Step 8: Commit**

```bash
git add tools/fixtures/run-lanes tools/check-plugin.py tools/check-plugin-mutants.sh .github/workflows/checks.yml
git commit -m "test(pipeline): a diamond fixture for two concurrent lanes

No fixture contained two lanes, so every per-lane arm was exercised by mutants
against single-lane input and the conforming shape had no input at all. This
adds the canonical diamond -- Phase 1 forks to Phase 2 and Phase 3, which join
at Phase 4 -- with Lane A carrying 1, 2 and 4 and Lane B carrying 3.

Phase 2 is PASS while Phase 3 is open, which is precisely the state the old
global comparison hard-failed. Lane A writes waiting at join Phase 4 rather than
naming the joining phase, and the arm that two active lanes never execute the
same phase now has both directions."
```

---

### Task 7: Deterministic join collapse

**Root cause being fixed:** the design's join rule is mechanical only if the
survivor is decided before the run starts. Nothing today reads `· deps:` at all,
so a joining phase can carry any contributor's lane, can be entered before its
contributors are `PASS`, can be entered while its leading `RVJ` is open, and a
retired lane id can reappear on a later phase — four defects with one root: the
persisted mapping was never validated against the graph.

**Files:**
- Modify: `tools/check-plugin.py` (three arms in the `--run` block, after Task 6's rule-2 arm)
- Modify: `plugins/superb/skills/pipeline/references/parallel.md` (the join section)
- Modify: `plugins/superb/skills/pipeline/SKILL.md` (GATE 2's lane-assignment step)
- Modify: `tools/check-plugin-mutants.sh`

**Interfaces:**
- Consumes: `_lanemap`, `_depmap`, `_lane_named`, `_lane_cs`, `_blockers`, `_phs`
  from Tasks 5 and 6.
- Produces: nothing later tasks read.

- [ ] **Step 1: State the survivor rule at GATE 2**

`SKILL.md`, in GATE 2's steps. The plan's approval is where the mapping is
written, so this is where the rule belongs:

````markdown
**GATE 2 assigns every phase its lane.** Walk the approved plan's phases in
approved-plan order and write `· lane: <id>` on each heading:

```
contributors    = direct predecessor phases, in approved-plan order
surviving_lane  = lane(contributors[0])
joining_phase.lane = surviving_lane
```

```
JOIN SURVIVOR SELECTION IS DETERMINISTIC.
THE ORCHESTRATOR MUST NOT CHOOSE A JOIN SURVIVOR AT RUNTIME.
THE JOINING PHASE'S PERSISTED `lane:` FIELD MUST EQUAL
THE LANE OF ITS FIRST CONTRIBUTING PREDECESSOR IN APPROVED-PLAN ORDER.
```

The first phase takes `Lane A`. At a fork, the successor first in approved-plan
order keeps the forking phase's lane and each further successor takes the next
unused id. At a join, the joining phase takes the lane above; the other
contributing lanes retire when the leading `RVJ` closes, and **a retired lane id
is never allocated again in that run.**
````

`references/parallel.md`'s join section takes the same block plus the collapse:

```
Phase B PASS
Phase C PASS
leading RVJ clean
→ CLOSE(leading RVJ)
→ retain Lane A          (the planned survivor)
→ retire Lane B
→ Lane A owns Phase D
```

Runtime performs that collapse; it never chooses the survivor. A clean leading
`RVJ` lets the joining phase **start** — it does not mark it `PASS`, which the
phase still owes its own `RV` for.

- [ ] **Step 2: Add the survivor arm**

`tools/check-plugin.py`, after Task 6's rule-2 arm:

```python
        # THE JOIN SURVIVOR IS THE PLANNED ONE. `_phs` is in FILE ORDER, which
        # is approved-plan order to every arm that reads it, so the first
        # contributing predecessor is `_dd[0]`. Checking the persisted mapping
        # against the graph is what makes the survivor rule mechanical instead
        # of a convention nobody can enforce.
        _joins = {}
        for _j, _dd in sorted(_depmap.items()):
            _dl = {_lanemap[x] for x in _dd if x in _lanemap}
            if len(_dl) < 2:
                continue                      # not a join: one contributing lane
            _joins[_j] = _dd
            _want = _lanemap.get(_dd[0])
            if _want and _lanemap.get(_j) != _want:
                _untrusted = True
                bad(f"{relpath(tracker)}: {_phs[_j]['label']} joins "
                    f"{len(_dl)} lanes and carries `· lane: "
                    f"{_lanemap.get(_j)}`, but its first contributing "
                    f"predecessor in approved-plan order is "
                    f"{_phs[_dd[0]]['label']} on lane {_want} — a joining "
                    "phase takes that lane, decided at GATE 2 and written "
                    "down. The orchestrator must not choose a survivor at "
                    f"runtime. REMEDY: write `· lane: {_want}` on "
                    f"{_phs[_j]['label']}")
```

- [ ] **Step 3: Add the join-gating arm**

Immediately after it:

```python
        _csmap = dict(_lane_cs)
        for _j, _dd in _joins.items():
            _owner = [lid for lid, i in _lane_named if i == _j]
            if not _owner:
                continue                      # nobody is in the joining phase
            _lanes_in = {_lanemap[x] for x in _dd if x in _lanemap}
            _open = [b for b in _blockers
                     if b[0] < _j and _lanemap.get(b[0]) in _lanes_in]
            # THE GATE ACTION IS LEGAL, THE IMPLEMENTATION ACTION IS NOT, and
            # the difference is who runs the leading `RVJ`. Once every
            # contributor is `PASS`, the surviving lane names the `RVJ` — that
            # is the gate being executed. Naming a task is entering the phase,
            # and only a closed leading `RVJ` licenses that.
            _isgate = re.search(r"(?:—|-)\s*RVJ\b", _csmap.get(_owner[0], ""))
            _t1 = min((t[2] for t in _phs[_j]["tasks"]), default=None)
            _lead = [r for r in _phs[_j]["reviews"]
                     if r[0] == "RVJ" and (_t1 is None or r[2] < _t1)]
            if _open:
                bad(f"{relpath(tracker)}: Current State's "
                    f"`**Lane {_owner[0]}:**` names {_phs[_j]['label']}, which "
                    f"joins {len(_lanes_in)} lanes, while {_open[0][1]} — "
                    f"assigned to a contributing lane — still has "
                    f"{_open[0][2]}. A join is reachable only when every "
                    "contributing lane's last phase is `PASS`. REMEDY: point "
                    "that lane at `waiting at join "
                    f"{_phs[_j]['label']}` until the contributors close")
            elif not _lead:
                _untrusted = True
                bad(f"{relpath(tracker)}: {_phs[_j]['label']} joins "
                    f"{len(_lanes_in)} lanes but carries no leading `RVJ` — an "
                    "`RVJ` above the phase's first task, which is what reviews "
                    "the lanes that merged here. Without it the join is "
                    "entered on nobody's review. REMEDY: add the leading `RVJ`, "
                    "above the first task")
            elif not _isgate and not any(r[1] == "x" for r in _lead):
                bad(f"{relpath(tracker)}: Current State's "
                    f"`**Lane {_owner[0]}:**` names an implementation action in "
                    f"{_phs[_j]['label']} while its leading `RVJ` is not `[x]` "
                    "— a leading `RVJ` gates *entry* to a joining phase, so the "
                    "only action legal before it closes is the `RVJ` itself. "
                    "REMEDY: name the gate — `Phase "
                    f"{_phs[_j]['label'].split()[-1]} — RVJ` — until it closes")
```

- [ ] **Step 4: Add the retired-id arm**

```python
        # A RETIRED LANE ID IS NEVER REUSED. A lane retires at the join that
        # consumes it — the first joining phase depending on one of its phases
        # and carrying a different id — so a later phase carrying that id is
        # either a resurrected lane or an accidental collision, and both make
        # "which branch is this" unanswerable after a resume.
        for _lid in sorted(set(_lanemap.values())):
            _own = sorted(i for i in _lanemap if _lanemap[i] == _lid)
            _ret = next((_j for _j in sorted(_depmap)
                         if _lanemap.get(_j) != _lid
                         and any(_lanemap.get(x) == _lid
                                 for x in _depmap[_j])), None)
            if _ret is None:
                continue
            _after = [i for i in _own if i > _ret]
            if _after:
                _untrusted = True
                bad(f"{relpath(tracker)}: lane {_lid} retires at "
                    f"{_phs[_ret]['label']}, which consumes it on lane "
                    f"{_lanemap.get(_ret)}, but {_phs[_after[0]]['label']} "
                    "carries it again later in approved-plan order. A retired "
                    "lane id is never allocated again in the same run. REMEDY: "
                    "allocate the next unused id for that branch")
```

- [ ] **Step 5: Run the gate to verify it passes**

Run: `for d in run-ok run-open-rv run-fixloop run-lanes; do ./tools/check-plugin.sh --run tools/fixtures/$d; done`
Expected: no `FAIL`. `run-lanes` is the only fixture with a join; `Lane A` is
`waiting at join Phase 4`, so `_owner` is empty for Phase 4 and the gating arm
correctly compares nothing. The survivor and retired-id arms *do* run on it:
Phase 4 carries `· lane: A`, matching Phase 2, and `Lane B` retires at Phase 4
with no later phase carrying it.

- [ ] **Step 6: Add the mutants**

```bash
run_mutant "join phase takes the wrong contributors lane" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if [ "$(grep -c "^## Phase 4 .* · lane: A$" "$f")" != 1 ]; then
  echo "mutant is a no-op: Phase 4s heading is not in the expected shape"
else
  sed -i "s|^\(## Phase 4 .*\) · lane: A$|\1 · lane: B|" "$f"
  grep -q "^## Phase 4 .* · lane: B$" "$f" || echo "mutant is a no-op: the lane was not swapped"
fi'

run_mutant "join starts before a contributing lane passes" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- **Lane A:** waiting at join Phase 4" "$f"; then
  echo "mutant is a no-op: Lane A is not waiting at the join"
else
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4|- **Lane A:** Phase 4 — RVJ|" "$f"
  grep -qF -- "- **Lane A:** Phase 4 — RVJ" "$f" || echo "mutant is a no-op: Lane A did not enter the join"
fi'

run_mutant "join starts an implementation task before its leading RVJ closes" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if ! grep -qF -- "- [ ] T3 — a task" "$f"; then
  echo "mutant is a no-op: Phase 3s task is not in the expected shape"
else
  # Close Phase 3 so both contributors pass, then enter the join on a TASK
  # rather than on the gate. The leading RVJ stays `[ ]`, which is the only
  # thing this mutant is about.
  sed -i "s|^- \[ \] T3 — a task · W1 · deps T1|- [x] T3 — a task · W1 · deps T1 — \`ccccccc\`|" "$f"
  sed -i "s|^- \[ \] RV — review fan-out$|- [x] RV — review fan-out · N=1 → 1 slice + 0 integration\n      · reports p3-review-a.md · coverage p3-coverage.md → no findings|" "$f"
  sed -i "s|^- \*\*Lane A:\*\* waiting at join Phase 4|- **Lane A:** Phase 4 — T4|" "$f"
  grep -qF -- "- **Lane A:** Phase 4 — T4" "$f" || echo "mutant is a no-op: Lane A did not name a task in the join"
fi'

run_mutant "retired lane id is reused later in the run" '
enable_run_dir tools/fixtures/run-lanes || exit 0
f=tools/fixtures/run-lanes/progress.md
if [ "$(grep -c "^## Phase 4 .* · lane: A$" "$f")" != 1 ]; then
  echo "mutant is a no-op: Phase 4s heading is not in the expected shape"
else
  printf "\n## Phase 5 — fixture, a resurrected lane · deps: Phase 4 · lane: B\n- [ ] T5 — a task · W1 · deps T4\n- [ ] RV — review fan-out\n" >> "$f"
  grep -q "^## Phase 5 .* · lane: B$" "$f" || echo "mutant is a no-op: the resurrected phase was not appended"
fi'
```

The third mutant writes a **multi-line** replacement through `sed`'s `\n`, which
GNU `sed` honours in the replacement text. Verify it landed as two lines before
trusting the kill: `sed -n '/Phase 3/,/Phase 4/p'` on the mutated copy.

- [ ] **Step 7: Verify the mutants kill**

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep -E 'contributors lane|before a contributing|leading RVJ closes|retired lane id|killed=|SURVIVED|NO-OP'`
Expected: four `killed`, and `survived=0 no-op=0`. A `SURVIVED` on the third
means the gating arm read the closed `RV` rather than the open `RVJ` — check
`_lead`'s line-number filter, not the mutant.

- [ ] **Step 8: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "feat(pipeline): the join survivor is decided at GATE 2, not at runtime

Nothing read · deps: at all, so a joining phase could carry any contributor's
lane, could be entered before its contributors passed or while its leading RVJ
was open, and a retired lane id could reappear on a later phase.

GATE 2 now assigns the joining phase the lane of its first contributing
predecessor in approved-plan order, and the linter checks the persisted mapping
against the graph. A join is reachable only when every contributing lane's last
phase is PASS; before the leading RVJ closes, the only legal action in the
joining phase is that RVJ itself -- it gates entry, never completion. And a lane
retires at the join that consumes it, so its id is never allocated again."
```

---

### Task 8: Per-lane resume

**Root cause being fixed:** `references/run-state.md:216-222` says *"the first
row that matches is the state, and its action is **the only** valid next
action"* — one state for the whole run. Under lanes that is false: two lanes have
two states and two next actions, and a resumed run reading that table picks one
lane's action and abandons the other's.

**Files:**
- Modify: `plugins/superb/skills/pipeline/references/run-state.md:216-240`
- Modify: `plugins/superb/skills/pipeline/SKILL.md` (the resume section)
- Modify: `tools/check-plugin.py` (the held-phrase arm near `:440-600`)
- Modify: `tools/check-plugin-mutants.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Make the precedence table per-lane**

`references/run-state.md:216`. Replace the preamble and add the two lane rows:

```markdown
6. **Resume derives the state from disk, per lane, in this precedence.** Read
   the `· lane:` assignments off the phase headings first — that mapping is
   persisted precisely so a resumed run never has to infer it — then, **for each
   active lane**, read down; the first row that matches is that lane's state,
   and its action is the only valid next action **for that lane**. A run with
   two active lanes has two states and two next actions, and taking one lane's
   action as the run's is how a resumed run abandons the other. This protocol
   changes how a run is re-entered, never what the run is allowed to do.
```

Two rows join the table, above the final `PASS` row:

```markdown
   | every phase of this lane `[x]`, its join's leading `RVJ` `[ ]`, another contributing lane unfinished | waiting at join | **nothing for this lane.** Write `waiting at join Phase <id>` and resume the lane that is unfinished |
   | every contributing lane `PASS`, the join's leading `RVJ` `[ ]` | `RVJ` | the surviving lane runs the leading `RVJ` — the lane the joining phase's `· lane:` names, and no other |
```

And the closing rules gain the collapse:

```markdown
   **A resumed run never chooses a join survivor.** The joining phase's
   `· lane:` already names it, from GATE 2. When the leading `RVJ` closes, retire
   the other contributing lanes' Current State lines and the surviving lane owns
   the joining phase — which then owes its own `IMPLEMENT → RV → PASS`.
```

- [ ] **Step 2: Mirror it into `SKILL.md`**

The resume section's summary of the precedence rule carries the same
"for that lane" qualification and the same survivor sentence. **Both copies are
held by Step 3**, so leaving one behind is a `FAIL`, not a silent divergence.

- [ ] **Step 3: Hold the phrases**

`tools/check-plugin.py`'s held-phrase arm. Add to the per-phrase file sets, with
the same structure the neighbouring phrases use:

```python
            # PER-LANE RESUME is held in both files that state the precedence
            # rule. The old preamble — "its action is the only valid next
            # action" — is FALSE under lanes: two lanes have two next actions,
            # and a resumed run taking one as the run's abandons the other. An
            # unheld copy is one edit from the singular form, and the singular
            # form reads as correct.
            ("the only valid next action **for that lane**",
             ("references/run-state.md", "SKILL.md")),
            ("A resumed run never chooses a join survivor",
             ("references/run-state.md", "SKILL.md")),
```

Match the arm's existing whitespace handling: these phrases can wrap, so they
are compared against the **flattened** text, as its neighbours are.

- [ ] **Step 4: Run the gate to verify both directions**

Run: `./tools/check-plugin.sh 2>&1 | grep -E 'FAIL|valid next action'`
Expected: no `FAIL` after Steps 1–2; and, before them, a `FAIL` naming both
files. Prove the RED by hand once: delete the phrase from `SKILL.md`, re-run,
confirm the `FAIL`, restore it.

- [ ] **Step 5: Add the mutants**

```bash
run_mutant "resume precedence drops the per-lane qualification" '
f=plugins/superb/skills/pipeline/references/run-state.md
if ! grep -qF -- "the only valid next action **for that lane**" "$f"; then
  echo "mutant is a no-op: the per-lane phrase is not present to remove"
else
  perl -0pi -e "s/the only valid next action \*\*for that lane\*\*/the only valid next action/" "$f"
  grep -qF -- "the only valid next action **for that lane**" "$f" && echo "mutant is a no-op: the phrase survived"
fi'

run_mutant "resume lets the orchestrator pick a join survivor" '
f=plugins/superb/skills/pipeline/references/run-state.md
if ! grep -qF -- "A resumed run never chooses a join survivor" "$f"; then
  echo "mutant is a no-op: the survivor sentence is not present to remove"
else
  perl -0pi -e "s/A resumed run never chooses a join survivor/A resumed run picks whichever lane is furthest along/" "$f"
  grep -qF -- "A resumed run never chooses a join survivor" "$f" && echo "mutant is a no-op: the sentence survived"
fi'
```

`perl -0pi` rather than `sed`, because the phrase can wrap across lines and
`sed` is line-oriented — the reflow hazard that made four earlier pin mutants
survive.

- [ ] **Step 6: Verify the mutants kill**

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep -E 'per-lane qualification|pick a join survivor|killed=|SURVIVED|NO-OP'`
Expected: two `killed`, and `survived=0 no-op=0`.

- [ ] **Step 7: Commit**

```bash
git add plugins/superb/skills/pipeline tools/check-plugin.py tools/check-plugin-mutants.sh
git commit -m "feat(pipeline): resume is evaluated per lane

The precedence table said the first matching row is the state and its action is
the only valid next action -- one state for the whole run. With two active lanes
that is false: two lanes have two states and two next actions, and a resumed run
taking one lane's action as the run's abandons the other.

The table is now read per lane, off the persisted · lane: assignments, and gains
the two states lanes introduce: waiting at join, and the surviving lane running
the leading RVJ. A resumed run never chooses a join survivor -- the joining
phase's · lane: already names it. Both copies of the rule are held."
```

---

# Phase 5 — Artifacts and release

Goal: the commit policy says what it means, a mechanism enforces it, PR #3's
ephemeral artifacts are gone, and the change ships as 0.13.0.

---

### Task 9: Ephemeral versus curated, with a gate behind it

**Root cause being fixed:** `SKILL.md:157` states *"**Never `git add` anything
under `docs/superpowers/`** — run state, specs and plans are all **deliberately
local-only**"*, repeated in `run-state.md:19`, `fix-loop.md:601`, and two
rationalization/red-flag rows. It is enforced by prose alone — there is no
`.gitignore` coverage, which is why 41 files are tracked — and it contradicts
what the repository actually does: committed specs and plans, five curated loose
`runs/*.md` records, and this change adding a sixth. The rule was written as a
**path** rule; it was always a **lifecycle** rule.

**Counted, not assumed:** `git ls-files docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine/ | wc -l` returns **11**, not the 12 the design states. Use the command's answer, and remove what is tracked rather than a number.

**Files:**
- Modify: `.gitignore`
- Modify: `tools/check-plugin.py` (a new arm, after `relpath`'s definition at `:1285`)
- Modify: `plugins/superb/skills/pipeline/SKILL.md:157-158`, `:623`, `:950`, `:1170`, `:1324`
- Modify: `plugins/superb/skills/pipeline/references/run-state.md:19-20`
- Modify: `plugins/superb/skills/pipeline/references/fix-loop.md:600-601`
- Create: `docs/superpowers/runs/pipeline-phase-machine.md`
- Remove: every tracked file under `docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine/`
- Modify: `tools/check-plugin-mutants.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Add the ignore rule**

`.gitignore`, appended with the reason, because a bare pattern is the kind of
line a later cleanup deletes:

```gitignore
# Pipeline run directories are ephemeral execution state -- progress.md,
# register.md, kit.md, findings.md, fix plans, agent-output/ -- and are never
# committed. Loose curated records directly under runs/ ARE trackable, which is
# why this pattern ends in `*/` and not `*`: `docs/superpowers/` would hide the
# specs, plans and distilled records that are permanent documentation.
docs/superpowers/runs/*/
```

- [ ] **Step 2: Write the failing arm**

`tools/check-plugin.py`, after `relpath`'s definition (`:1285`) — the constraint
that arms calling `relpath` sit below it applies here:

```python
print("\n== run artifacts are ignored ==")
# A RULE WITH NO MECHANISM IS THE DEFECT THIS ARM IS ABOUT. The skill's law was
# enforced by prose alone, and 41 files under `docs/superpowers/` are tracked as
# a result. This checks the IGNORE RULE, not the tree: the pre-PR#3 run
# directories are tracked by an explicit keep decision, so an arm phrased "no
# run directory is tracked" would fail on history it must not touch. Git ignores
# only what is untracked, so the rule stops the NEXT run committing its
# artifacts while the grandfathered files stay.
_gi = ROOT / ".gitignore"
_gilines = [ln.strip() for ln in
            (_gi.read_text(encoding="utf-8") if _gi.exists() else "").split("\n")
            if ln.strip() and not ln.strip().startswith("#")]
if "docs/superpowers/runs/*/" in _gilines:
    ok("`.gitignore` covers pipeline run directories")
else:
    bad("`.gitignore` carries no `docs/superpowers/runs/*/` line — pipeline run "
        "directories are ephemeral execution state (progress.md, register.md, "
        "kit.md, findings.md, fix plans, agent-output/) and the skill's rule "
        "against committing them is enforced by prose alone without it, which "
        "is how PR #3's artifacts rode into the repository as a byproduct. "
        "REMEDY: add `docs/superpowers/runs/*/` to the root `.gitignore`")
# AND NOT ONE PATTERN WIDER. `docs/superpowers/` or `docs/superpowers/runs/*`
# would also hide the specs, plans and curated loose records that ARE permanent
# documentation — including the one this change adds. The distinction the
# history already draws is directory versus loose file, and it is the whole
# policy.
_wide = [ln for ln in _gilines
         if re.match(r"^/?docs/superpowers/?$", ln)
         or re.match(r"^/?docs/superpowers/\*", ln)
         or re.match(r"^/?docs/superpowers/runs/?$", ln)
         or re.match(r"^/?docs/superpowers/runs/\*$", ln)]
if _wide:
    bad(f"`.gitignore` carries {_wide[0]!r}, which hides curated permanent "
        "documentation as well as ephemeral run state — specs, plans and the "
        "loose `runs/*.md` records this repository deliberately keeps. The "
        "policy is: a runtime directory is forbidden, a curated permanent "
        "document is an intentional exception. REMEDY: narrow it to "
        "`docs/superpowers/runs/*/`")
else:
    ok("`.gitignore` leaves curated specs, plans and loose `runs/*.md` trackable")
```

Cite both mutants above the arm.

- [ ] **Step 3: Run the gate to verify it fails, then passes**

Run: `git stash push .gitignore && ./tools/check-plugin.sh 2>&1 | grep -E 'FAIL|runs/\*'; git stash pop`
Expected: `FAIL` without the rule, no `FAIL` with it. Prove the second direction
by hand too: add `docs/superpowers/` to `.gitignore`, re-run, confirm the
over-broad `FAIL`, remove it.

- [ ] **Step 4: Replace the absolute wording — `SKILL.md:157-158`**

````markdown
- **Never `git add` pipeline runtime directories under
  `docs/superpowers/runs/*/`** — `progress.md`, `register.md`, `kit.md`,
  `findings.md`, fix plans, `agent-output/`, review reports, and any other
  runtime evidence. That material is **ephemeral execution state**: it belongs
  on disk for the run and to a resume, and nowhere else. The root `.gitignore`
  enforces it.
- **Curated permanent documentation may be deliberately committed.**
  `docs/superpowers/specs/*.md`, `docs/superpowers/plans/*.md`, and loose
  `docs/superpowers/runs/*.md` records — distilled histories like
  `runs/pipeline-phase-seam.md` — are repository documentation when someone
  decides they are. **Nothing auto-commits them**; the permission is only that
  they may be tracked.

```
runtime directory          = forbidden
curated permanent document = intentional, deliberate exception
```
````

- [ ] **Step 5: Replace the absolute wording — the other six sites**

Each keeps its own sentence's job; only the absolute claim changes.

| Site | Change |
|---|---|
| `SKILL.md:623` | *"(local-only, like everything under `docs/superpowers/`…"* → *"(local-only, like everything in the run directory…"* |
| `SKILL.md:950` | *"`docs/superpowers/` is local-only"* → *"the run directory is local-only"*; the hand-off sentence is unchanged |
| `SKILL.md:1170` | *"Nothing under `docs/superpowers/` is committed."* → *"The run directory is never committed."* |
| `SKILL.md:1324` | same substitution as `:1170` |
| `run-state.md:19-20` | *"Nothing under `docs/superpowers/` is ever `git add`ed — run state, specs and plans are deliberately local-only"* → *"Nothing in the run directory is ever `git add`ed — run state is deliberately local-only. Curated specs, plans and loose `runs/*.md` records may be deliberately committed as repository documentation."* The guard-rail-counters conclusion is unchanged |
| `fix-loop.md:600-601` | the path sentence keeps its meaning; *"and never `git add`ed"* becomes *"and never `git add`ed — the run directory is ignored by the root `.gitignore`"* |

**Do not weaken the runtime-artifact protection anywhere**, and do not make the
`docs/superpowers/` tree trackable by default. Every one of these edits narrows
the *scope* of a prohibition that stays absolute inside that scope.

- [ ] **Step 6: Distil the permanent record**

`docs/superpowers/runs/pipeline-phase-machine.md`, in the established loose-file
pattern of `pipeline-phase-seam.md`: what PR #3 changed, the seven review rounds
and the 63 findings they produced, the defect class that recurred (a check
reporting success about something it never examined), and the two properties
installed in response — `_untrusted`, and the harness failing a self-declared
no-op even when the mutant kills. Two pages at most. **It replaces 11 files
whose value was that they recorded a review; the record is what has value.**

- [ ] **Step 7: Remove the ephemeral artifacts**

```bash
git rm -r docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine/
git status --porcelain docs/superpowers/runs/
```

Expected: the 11 tracked files staged for deletion, and no other run directory
touched. **Every pre-PR#3 file stays** — removing them destroys deliberately
kept history, and `specs/2026-08-31-craft-depth-design.md:4` cites one of them
as its evidence base. Confirm with
`git ls-files docs/superpowers/runs/ | grep -c 2026-08-31` before and after.

- [ ] **Step 8: Add the mutants**

```bash
run_mutant "gitignore drops the run-directory rule" '
if ! grep -qxF -- "docs/superpowers/runs/*/" .gitignore; then
  echo "mutant is a no-op: the ignore rule is not present to remove"
else
  sed -i "\|^docs/superpowers/runs/\*/$|d" .gitignore
  grep -qxF -- "docs/superpowers/runs/*/" .gitignore && echo "mutant is a no-op: the rule survived"
fi'

run_mutant "gitignore hides curated documentation too" '
if ! grep -qxF -- "docs/superpowers/runs/*/" .gitignore; then
  echo "mutant is a no-op: the ignore rule is not present to widen"
else
  sed -i "s|^docs/superpowers/runs/\*/$|docs/superpowers/|" .gitignore
  grep -qxF -- "docs/superpowers/" .gitignore || echo "mutant is a no-op: the rule was not widened"
fi'
```

`grep -qxF --` with the explicit `--`: the pattern begins with `d`, but the
habit is the protection — ugrep parses a leading `-` as an option, and a
self-disabled mutant survives while blaming its target.

- [ ] **Step 9: Verify the mutants kill**

Run: `./tools/check-plugin-mutants.sh 2>&1 | grep -E 'drops the run-directory|hides curated|killed=|SURVIVED|NO-OP'`
Expected: two `killed`, and `survived=0 no-op=0`. The harness must restore
`.gitignore` between mutants — confirm with `git diff --stat .gitignore` after
the run, which must be empty.

- [ ] **Step 10: Commit**

```bash
git add .gitignore tools/check-plugin.py tools/check-plugin-mutants.sh plugins/superb/skills/pipeline docs/superpowers/runs/pipeline-phase-machine.md
git add -A docs/superpowers/runs/2026-09-07-pipeline-phase-state-machine
git commit -m "chore(pipeline): ephemeral run state is ignored, curated documentation is not

Never git add anything under docs/superpowers/ could not coexist with committed
specs and plans, five curated loose runs/*.md records, and this change adding a
sixth. The rule was written as a path rule; it was always a lifecycle rule.

Ephemeral pipeline execution state -- everything inside a run directory -- is
local-only and now mechanically protected by docs/superpowers/runs/*/ in the
root .gitignore. Curated permanent documentation may be deliberately committed:
specs, plans, and loose runs/*.md records. Nothing auto-commits them.

The ignore pattern is deliberately not docs/superpowers/, which would hide the
documentation this repository keeps on purpose, and an arm checks both
directions. PR #3's run artifacts -- 11 files that rode into fix commits as a
byproduct and were never the subject of a keep decision -- are removed, with the
review history distilled into one permanent record. Every pre-PR#3 file stays:
they were kept deliberately, and git ignores only what is untracked."
```

---

### Task 10: Contradiction sweep and release

**Files:**
- Modify: `plugins/superb/skills/pipeline/README.md`, and whatever the sweep finds
- Modify: `plugins/superb/.claude-plugin/plugin.json`, `plugins/superb/.codex-plugin/plugin.json`

**Interfaces:** none.

- [ ] **Step 1: Sweep for stale concepts**

Every term this change retired or redefined. Run each; read every hit; a hit is
either correct in its new meaning or a contradiction to fix:

```bash
cd plugins/superb/skills/pipeline
grep -rn "waved" .                      # retired: no exemption to name
grep -rn "per wave" . | grep -i review  # waves must not size review
grep -rn "Next action" .                # retired field
grep -rn '\*\*Phase:\*\*' .             # retired field
grep -rn "maximal chain" .              # lanes are not chains
grep -rn "deleted" . | grep -i "M=0\|no round\|not counted"
grep -rn "local-only" .                 # scope must be the run directory
grep -rn "only valid next action" .     # must be per lane
```

Expected after Tasks 1–9: `waved` returns nothing; `Next action` and
`**Phase:**` return only the migration notes explaining their removal;
`maximal chain` returns only `parallel.md`'s explanation of why lanes are not
chains; every `local-only` hit scopes to the run directory.

- [ ] **Step 2: Sweep the README**

`plugins/superb/skills/pipeline/README.md` carries fan-out and lane prose that
no arm reads, which is exactly why it drifts. Bring its reviewer-count sentence
to `ceil(N/5)` and its lane sentence to the fork/join model.

- [ ] **Step 3: Check for a contradiction the arms cannot see**

```bash
grep -rn "ceil(" plugins/superb/skills/pipeline | grep -v "ceil(N/5)\|ceil(N / 5)"
```

Expected: nothing. Any other `ceil(...)` in the skill is a second sizing rule.

- [ ] **Step 4: Bump the version**

Both files, `0.12.0` → `0.13.0`:

```bash
sed -i 's/"version": "0.12.0"/"version": "0.13.0"/' \
  plugins/superb/.claude-plugin/plugin.json \
  plugins/superb/.codex-plugin/plugin.json
grep -h '"version"' plugins/superb/.claude-plugin/plugin.json plugins/superb/.codex-plugin/plugin.json
```

Expected: two `0.13.0` lines. **The two files must agree** — a version arm reads
both.

- [ ] **Step 5: Full verification**

```bash
./tools/check-plugin.sh
for d in run-ok run-open-rv run-fixloop run-lanes; do ./tools/check-plugin.sh --run tools/fixtures/$d; done
./tools/check-plugin-mutants.sh
```

Expected: no `FAIL` anywhere, and `killed=<N> survived=0 no-op=0`. **Never pipe
the harness through `tail`.** Record `N` — the whole-change review reads it
against the 162 mutants on `main` plus the ones this plan adds.

- [ ] **Step 6: Commit**

```bash
git add plugins/superb
git commit -m "chore: superb 0.13.0"
```

---

## After Task 10 — the single review of this change

Per the plan header, **no formal review runs between tasks**; each task's gate
is its verification. Once Task 10 is committed:

1. Review the completed change **as a unit**, with reviewers sized `ceil(N/5)`
   over the 10 tasks — 2 slice reviewers — plus 1 integration reviewer, because
   there is a real cross-slice boundary: the lane mapping Task 5 persists is
   consumed by Tasks 6, 7 and 8.
2. Consolidate every finding into **one** fix plan before any fix is written.
3. Fix, then re-review the fix commits under the same gate.
4. Run `superpowers:verification-before-completion` over the result.
5. Deliver the 10-item report the brief asks for.

**Do not push, merge, publish, or make unrelated changes** at any point.

---

## Self-Review

Checked against
`docs/superpowers/specs/2026-09-07-pipeline-gate-ownership-and-lanes-design.md`
after the plan was complete.

**Spec coverage.** Every design row maps to a task: Issue 1 → Tasks 2, 3;
Issue 2 → Tasks 5, 6, 7, 8; Issue 3 → Task 1; Issue 4 → Task 4; Issue 5 →
Task 9. Test matrix rows 1, 2, 2a, 2b → Tasks 2, 3, 6; 3, 3a, 3b, 3c → Tasks 5,
6; 4, 5, 5a–5d → Tasks 5, 6, 7; 5e, 5f → Task 7; 6, 7, 8 → Task 1; 9, 9a–9d, 10
→ Task 4; 10a–10c → Task 9; 11, 12 → existing arms, unchanged and protected by
the Global Constraints; 13, 14 → Tasks 3 and 6; 15 → Task 8.

**One deliberate deviation from the spec, recorded rather than silently
applied:** the design says 12 files under
`runs/2026-09-07-pipeline-phase-state-machine/`; `git ls-files` says 11. Task 9
removes what is tracked and says so.

**Placeholders.** None: every code step carries the code, every prose step
carries the replacement text, every mutant is written out.

**Type consistency.** `parse_phase_lanes` returns `(lanes, deps, multi)` in
Task 5 and is read as three values in Tasks 6 and 7. `_lanemap`, `_depmap`,
`_lane_named`, `_lane_cs` and `_joins` keep their names and shapes across Tasks
5–7. `lint_review_lines`' fourth return value `gates` is produced in Task 2 and
consumed in Task 3 with the documented dict keys. `_untrusted` is set by every
new report that speaks about its own subject.
