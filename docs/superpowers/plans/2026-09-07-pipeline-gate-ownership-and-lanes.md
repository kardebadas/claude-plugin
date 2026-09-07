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

- [ ] **Step 4: State both `RVJ` transitions**

`SKILL.md:326-335`, after the placement sentence. These differ, and neither is
written as a transition today:

```markdown
**The two placements have different successors.** A `RVJ` is not a phase gate and
never stands in for one:

```
trailing RVJ (after a Rule 3 split's last sibling):
    phase RV PASS → RVJ → clean → NEXT PHASE

leading RVJ (above a joining phase's first task):
    every contributing lane PASS → RVJ → clean → IMPLEMENT joining phase
```

A clean **leading** `RVJ` gates *entry*, never *completion*: it reviews the
lanes that merged into this phase, not this phase's own tasks, so the joining
phase still owes its own `RV` and cannot reach `PASS` on the `RVJ` alone. A
clean **trailing** `RVJ` closes the split, and the run advances past it.
```

Mirror the same two transitions into the Stage 4 state machine at
`SKILL.md:819-823`, which currently describes only the trailing case.

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
