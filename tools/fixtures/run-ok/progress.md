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

**Every round here is sized by the regime its own key names**, and the two
arithmetic arms read that: all three phases are unwaved `N=`, so `s` is
`ceil(N/5)` — `N=1` takes 1, `N=8` takes 2, `N=9` takes 2 — and `i` is 1 above
one slice and 0 at one slice. An earlier version of this fixture declared
`N=9 → 3 slice + 1 integration` and both gates passed it: the one regime the
skill says *is* re-derivable from the line was the regime the fixture broke.

Each round's coverage table carries **one row per report file, and no two
rows the same range** — which is what the over-fan-out arm reads, so a fixture
whose slices all shared a range (this one's did, until it was corrected) would
leave that arm unexercised on the happy path while demonstrating the very
duplication the fan-out rule forbids. Phase 3's two slices are T3's commit and
the follow-up fix its `scope` note names, and Phase 2's second range is an
orchestrator-authored commit with no task line of its own — the commits
the skill says are covered like any other and are covered by nothing until a
slice is widened to reach them. Both phases declare more tasks (`N=8`, `N=9`)
than their abbreviated bullet lists show; a fixture is not a run.

Phase 3's closing `T4` bullet is not decoration either. It names a coverage
file in its own subject, so it is the witness that a record ends at the next
`- [` bullet: read on to the next round instead and the RV record above it
would borrow that field, letting a round carrying no coverage of its own pass.

**That bullet sits after its phase's `RV`, which the tracker grammar forbids** —
`templates/progress.md` puts a phase's `RV` last among its own task lines — and
the departure is deliberate and confined to Phase 3 of this fixture: the record
boundary is only observable when something follows the round, so a conforming
layout could not exercise it. The other phases close on their `RV`, the way a
real tracker does. Read this file as a linter input, not as a model of a run.

## What `--run` establishes over this file, and what it cannot

It establishes, for every closed `RV`/`RVJ` round in the tracker: the
declared `<s> slice + <i> integration` count equals the number of report
files that round lists, with brace sets expanded; an unwaved `N=` round's `s`
equals `ceil(N/5)`; `i` is 1 whenever `s` is above 1 and 0 at one slice; an
`RVJ` round declares `0 slice + 1 integration`; an `M=` re-review round
declares a `C=<n>` cluster count and `s` equals it; the round names a
`coverage` file; every report file it names, and the coverage file it names,
exist in `agent-output/`; on a round declaring two or more slices, every
report file it names has its own row in that coverage table and no two of
those rows carry the same range; and an `M=0 → no round` record carries its
closure routes and no reviewer evidence. It also establishes that
the tracker is readable and that at least one round is closed.

**Outside the unwaved `N=` regime** it does not establish that the fan-out was
**sized** correctly. It catches one half of that — an over-wide fan-out whose
duplication is visible in the recorded ranges, two reviewers handed the same
range — but the other half is not derivable from the tracker there: a waved
phase's wave count is not on the line, and the rule for a re-review round is
one reviewer per file cluster in the fix diff, whose input is the diff;
`C=<n>` puts the cluster count on the line, and the arm compares it against
`s`, but `C` is written by whoever chose `s`, so a round declaring one reviewer
over a seven-cluster diff writes `C=1` and passes here (measured), and one that
over-fanned out onto genuinely distinct ranges writes the matching `C` and
passes too. Nor does it establish that a named report or coverage file says
anything — their existence is checked, their contents are not, so
`COVERED: <n>/<n>` goes unread — or that a round happened when it claims to.

**The integration reviewer is conditional, and both arms of that are here.**
Phases 2 and 3 keep their integration reviewer and each names the boundary it
covers; **Phase 4** runs two slices with none and says so on a line of its own.
Those are the only two legal shapes above one slice, and the arm reads both: a
reviewer with no boundary named is the automatic third reviewer the rule
replaced, and a multi-slice round silent about it makes an omission
indistinguishable from a judgement. At one slice `i` is still 0
unconditionally — Phase 1 is that shape, and no boundary can license a second
reviewer over a diff the one slice already read in full.

**Phase 4 declares `N=7`, not `N=8`**, and that is load-bearing too: a mutant
requires exactly one closed round declaring `N=8` so its kill is attributable to
the `ceil(N/5)` arm alone, and a second `N=8` round turned it into a no-op
(measured). `ceil(7/5)` is also 2, so the shape this phase exists to demonstrate
is unchanged.

**Phase 4 exists rather than Phase 3 being converted**, and that is not
arbitrary: four mutants target Phase 3 specifically as the round carrying an
integration reviewer and a three-row coverage table — the repeated-range arm,
the missing-row arm, the collapsed-integration-range arm and the long-record
coverage-field arm all read it. Converting Phase 3 to the boundary-less shape
turned all four into no-ops (measured), each reporting that its target was gone
rather than that the gate had a hole. A new phase adds the shape without
removing anyone's target.

**Phase 3 also carries the fixture's only planned re-review round.** Its
`round 2` declares `M=2 C=1` and names a `fixplan` file, which is what the
fix-plan arm reads: a round that dispatched fixes must name the plan they were
written from, and a plan named but absent reads exactly like a planned round, so
both the field and the file are checked. `M=0 -> no round` records are exempt by
construction — no fix ran, so there was nothing to plan — and the two such
records elsewhere in this tree are what keep that exemption exercised.

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
      · boundary: the T2 contract consumed by the orchestrator commit in slice b
      · reports p2-review-{a,b,int}.md · coverage p2-coverage.md → no findings

## Phase 3 — fixture, a record longer than the old byte window · deps: Phase 2
- [x] T3 — a third task · W1 · deps T2 — `ccccccc`
- [x] RV — review fan-out · N=9 → 2 slice + 1 integration
      · boundary: T3's helper consumed by the follow-up fix in slice b
      · scope: the phase's own commits plus the follow-up fix that landed
        against T3 after the first pass, which is why this round runs wider
        than the phase line alone would suggest and why the reviewers were
        pointed at the merge range rather than at the task's own commit
      · note: a real round record carries prose of exactly this kind — what
        the reviewers were given, what was deliberately left out of scope,
        and which earlier round's findings this one re-reads — and it is that
        prose, not any malformation, that pushes the fields below past the
        400-character window a terse worked example never reached
      · reports p3-review-{a,b,int}.md · coverage p3-coverage.md → F-001, F-002
      → round 2: M=2 C=1 → 1 slice + 0 integration · fixplan p3-fixplan-r2.md
        · reports p3-rr2-a.md · coverage p3-rr2-coverage.md
        → F-001 closed, F-002 closed
- [x] T4 — file coverage p3-coverage.md into the phase ledger · W1 · deps T3 — `ddddddd`

## Phase 4 — fixture, multi-slice with no integration boundary · deps: Phase 3
- [x] T5 — a fifth task · W1 · deps T4 — `eeeeeee`
- [x] RV — review fan-out · N=7 → 2 slice + 0 integration
      · no integration boundary
      · reports p4-review-{a,b}.md · coverage p4-coverage.md → no findings
