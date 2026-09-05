# Pipeline — Progress Tracker

A fixture run directory, not a real one. It exists so `check-plugin.sh --run`
has a conforming input to prove itself against, and so the mutants in
tools/check-plugin-mutants.sh have something they can break. Every review
record below is closed and conforming, and each is here for a reason: Phase 1
names a single report file and Phase 2 names a brace-expanded set — the two
report-set forms the grammar writes, and the expansion is what makes the
second one checkable — while Phase 3 is a long record whose `reports` and
`coverage` fields sit past 400 flattened characters of the record's own
start, which is what a real tracker's prose does and what the byte-capped
reader this fixture replaced reported as a missing coverage file.

Phase 3's closing `T4` bullet is not decoration either. It names a coverage
file in its own subject, so it is the witness that a record ends at the next
`- [` bullet: read on to the next round instead and the RV record above it
would borrow that field, letting a round carrying no coverage of its own pass.

## What `--run` establishes over this file, and what it cannot

It establishes, for every closed `RV`/`RVJ` round in the tracker: the
declared `<s> slice + <i> integration` count equals the number of report
files that round lists, with brace sets expanded; an `RVJ` round declares
`0 slice + 1 integration`; the round names a `coverage` file; every report
file it names exists in `agent-output/`; and an `M=0 → no round` record
carries its closure routes and no reviewer evidence. It also establishes that
the tracker is readable and that at least one round is closed.

It does not establish that the fan-out was **sized** correctly, and that is
not a gap to be closed later — the size is not derivable from the line. The
rule is one reviewer per file cluster in the fix diff, whose input is the
diff; the line records only what was declared and what was listed, so a round
declaring one reviewer over a seven-cluster diff is internally consistent and
passes here. Nor does it establish that a named report file says anything,
that coverage reached `<n>/<n>`, or that a round happened when it claims to.

## Current State
- **Phase:** done (fixture)
- **Next action:** none; this run directory is a linter fixture
- **Last updated:** 2026-09-05
- **Run directory:** tools/fixtures/run-ok/

## Phase 1 — fixture, single report file · deps: none
- [x] T1 — a task · W1 · deps none — `aaaaaaa`
- [x] RV — review fan-out · N=1 → 1 slice + 0 integration
      · reports p1-review-a.md · coverage p1-coverage.md → no findings

## Phase 2 — fixture, brace-expanded report set · deps: Phase 1
- [x] T2 — another task · W1 · deps T1 — `bbbbbbb`
- [x] RV — review fan-out · N=8 → 2 slice + 1 integration
      · reports p2-review-{a,b,int}.md · coverage p2-coverage.md → no findings

## Phase 3 — fixture, a record longer than the old byte window · deps: Phase 2
- [x] T3 — a third task · W1 · deps T2 — `ccccccc`
- [x] RV — review fan-out · N=9 → 3 slice + 1 integration
      · scope: the phase's own commits plus the two follow-up fixes that
        landed against T3 after the first pass, which is why this round runs
        wider than the phase line alone would suggest and why the reviewers
        were pointed at the merge range rather than at the task's own commit
      · note: a real round record carries prose of exactly this kind — what
        the reviewers were given, what was deliberately left out of scope,
        and which earlier round's findings this one re-reads — and it is that
        prose, not any malformation, that pushes the fields below past the
        400-character window a terse worked example never reached
      · reports p3-review-{a,b,c,int}.md · coverage p3-coverage.md → no findings
- [x] T4 — file coverage p3-coverage.md into the phase ledger · W1 · deps T3 — `ddddddd`
