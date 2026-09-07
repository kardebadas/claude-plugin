# Migration review — findings ledger

Consolidated from `agent-output/migration-review-a.md` (state machine and prose)
and `agent-output/migration-review-b.md` (gates and evidence). Both reviewers
returned before any fix was dispatched.

**Dedup:** A's *"the no-advance arm's ledger half maps by exact label and drops
what it cannot match"* and B's `C1` are the same defect; B's is broader (four
measured shapes rather than one), so they merge into **F-001** and A's probe is
recorded as a fifth shape.

**Tiers are this skill's three:** Critical / Major / Minor. Neither reviewer
emitted `Important`.

## Blocking ledger

| ID | Sev | Area | File:line | Finding | State | Closed by |
| -- | --- | ---- | --------- | ------- | ----- | --------- |
| F-001 | Critical | gate | `tools/check-plugin.py:2126-2137` | Ledger row parse drops any row with a bolded `Sev`, a capitalised `Open`, a `Phase 2`-style cell, an extra column, or a heading whose label differs — and the arm then prints `ok` over a tracker that advanced past an open blocking finding | closed | fix `da34392` — header-driven column lookup + cell normalisation + row-width check + report-not-drop |
| F-002 | Major | gate | `tools/check-plugin.py:2110-2115` | A phase with **no** `RV` line at all is not a blocker: `any()` over an empty list is `False`, so an implementation phase that was never given a review line reads exactly like a reviewed one | closed | fix `da34392` — a phase with no review line is a blocker in its own right |
| F-003 | Major | gate | `tools/check-plugin.py:1988`, `:1996`, `:2062` | `parse_tracker_phases` returning `[]` makes both new arms vacuous — review-not-early is guarded by `elif _phs:` and no-advance falls through to an affirmative pass | closed | fix `da34392` — `if not _phs: bad(...)`; bullet regex accepts bolded/dotted ids |
| F-004 | Major | gate | `tools/check-plugin.py:2062-2080` | The review-not-early arm FAILs the **legal** leading-`RVJ` joining-phase shape the skill's own templates prescribe | closed | fix `da34392` — `RVJ` judged by placement — leading exempt, trailing not |
| F-005 | Major | gate | `tools/check-plugin.py:1608` | The fix-plan requirement is scoped to `key == "M"`, so writing `N=` on a fix round removes it entirely | closed | fix `da34392` — keyed off the round mark: an appended round must be keyed `M` |
| F-006 | Major | gate | `tools/check-plugin.py:1425` | A closed or appended round with no parseable declaration is `continue`d past, bypassing six arms including the two this branch added | closed | fix `da34392` — exemption narrowed to the `WAIVED` form |
| F-007 | Major | gate | `tools/check-plugin.py:2139-2144` | Only `**Next action:**` is read; `**Phase:**` is never checked, and a `Next action` naming no phase passes every branch | closed | fix `da34392` — both Current State fields read; naming no phase now fails |
| F-008 | Major | prose | `references/fix-loop.md:65-70` | The phase REVIEW state still prescribes an integration reviewer whenever `s > 1` — the retired rule, verbatim, in the file the executor is sent to | closed | fix `da34392` — the conditional rule written into the phase REVIEW bullet |
| F-009 | Major | prose | `SKILL.md:1028`, `references/fix-loop.md:598-599` | The re-review fan-out is summarised with the retired unconditional rule, contradicting the table at `fix-loop.md:457` | closed | fix `da34392` — both summaries point at the authority table |
| F-010 | Major | prose | `references/parallel.md:122-123` | A pre-`RV` build-gate failure is still given an F-ID and the fix loop, contradicting step 6 five lines above and four other files | closed | fix `da34392` — step 7 repairs inside IMPLEMENT; the conflict note stops writing to the ledger |
| F-011 | Major | prose | `SKILL.md:672-674` | "every task takes an implementer, a reviewer and usually a fix round or two" — the retired architecture stated as fact, and no sweep pattern matches it | closed | fix `da34392` — cost model restated without the per-task reviewer |
| F-012 | Major | prose | `templates/implementer-prompt.md:20`, `references/parallel.md:94`, `references/implement.md:74` | The `task-brief` citation appears in three forms, two of which resolve only inside this repository, while a run executes in the user's project | closed | fix `da34392` — one `<skill-dir>` form, resolved by the orchestrator, declared as a payload slot |
| F-013 | Minor | prose | `references/run-state.md:216-228` | The resume precedence table, introduced as exhaustive, has no row for a partially implemented phase | closed | fix `da34392` — the partially-implemented row added |
| F-014 | Minor | prose | `SKILL.md` digraph | `Stage 4b` carries a `clean / next phase` edge into `IMPLEMENT`, so a state other than `PASS` reaches the next phase | closed | fix `da34392` — `Stage 4b` routes through `PASS`; only GATE 2 and `PASS` reach `IMPLEMENT` |
| F-015 | Minor | prose | `references/fix-loop.md` | The file that owns the fix loop never names `FIX_PLAN`, `FIX_IMPLEMENT`, `RE_REVIEW` | closed | fix `da34392` — the three states named where the file owns them |
| F-016 | Minor | prose | `references/fix-loop.md` | The `M=0 → no round` justification is inaccurate about what such an iteration may edit | closed | fix `da34392` — `M=0` justification states it means no ownable commit at all |
| F-017 | Minor | gate | `tools/check-plugin.py` | A linter comment still states the integration rule in its inverted (pre-migration) form | closed | fix `da34392` — all four statements restated as the conditional rule |
| F-018 | Minor | prose | `SKILL.md` fan-out | The reviewer fan-out — the largest dispatch class — carries no model-tier instruction | closed | fix `da34392` — reviewer tier stated at the fan-out |
| F-019 | Minor | gate | `tools/check-plugin-mutants.sh:1585-1594` | `"run tracker declares two integration reviewers"` is co-killed by the report-count arm, so it proves nothing about its own | closed | fix `da34392` — mutation grows the report set and coverage table, so one arm can object |
| F-020 | Minor | gate | `tools/check-plugin-mutants.sh` | `run_mutant` discards a mutant's own no-op diagnostics whenever the mutant is killed, hiding a rotted anchor behind a green result | closed | fix `da34392` — no-ops reported and failed even on a kill — caught 3 immediately, 2 pre-existing |
| F-021 | Minor | gate | `tools/check-plugin.py` | An `M=0 → no round` record may carry a `fixplan` field and nothing objects | closed | fix `da34392` — an `M=0` record naming a `fixplan` is now a violation |
| F-022 | Minor | gate | `tools/check-plugin.py:1489` | The boundary test accepts any `boundary:` in the record, including one declaring an absence | closed | fix `da34392` — a negation after `boundary:` is not a named boundary |
| F-023 | Minor | gate | `tools/check-plugin.py` CI arm | The fixture-coverage check matches by substring, so one fixture's step can satisfy another's requirement | closed | fix `da34392` — exact step match, not substring |
| F-024 | Minor | fixture | `tools/fixtures/*` | No run-mode fixture contains an `RVJ`, so the `RVJ` arms have no conforming run-mode input | closed | fix `da34392` — `run-open-rv` Phase 3 carries a leading `RVJ` |

## Round 2 ledger (raised by the round-1 fix's own re-review)

| ID | Sev | Area | File:line | Finding | State | Closed by |
| -- | --- | ---- | --------- | ------- | ----- | --------- |
| N-001 | Critical | gate | `check-plugin.py:2339` | `**Phase:**` required the literal word "phase" inside its value, which the template's `<number and name>` form never contains — so the field was unreadable on every conforming tracker and F-007's measured defect still passed | closed | `_named_phase` accepts the bare leading id |
| N-002 | Critical | gate | `check-plugin.py:2240` | A leading `RVJ` satisfied F-002's "has a review line" test, so a joining phase with all tasks `[x]` and no `RV` of its own was not a blocker — F-002 and F-004 read one list and disagreed about what an `RVJ` covers | closed | the test asks for an `RV` specifically |
| N-003 | Major | gate | `check-plugin.py:2298` | The row-width check applied the blocking header's width to every `F-` row in the file, including the narrower *Deferred Minor findings* table the template ships — so any run deferring one Minor failed the gate | closed | rows scoped to the blocking table only |
| N-004 | Major | gate | `check-plugin.py:2352` | With `**Phase:**` unreadable, the "neither field names a phase" branch fired on a template-conforming Current State whenever any phase was unfinished — i.e. the ordinary mid-run case | closed | N-001's fix resolves it |
| N-005 | Minor | gate | `check-plugin.py:1552` | The boundary test enumerated negations, so `not applicable` and `nothing crosses …` both passed | closed | inverted: a boundary must look like one |
| N-006 | Minor | gate | `check-plugin.py:2344` | `_na_present`/`_ph_present` computed and never read; a Current State naming a nonexistent phase was caught only by the accident of a blocker existing | closed | reported on its own, as the ledger half already does |
| N-007 | Minor | gate | `check-plugin.py:1926` | F-008…F-011 corrected four prose sites and pinned none, so each could rot back on a green build | closed | a held-phrase arm + 4 mutants; caught `implement.md` stating the rule in different words |
| N-008 | Minor | gate | `check-plugin.py:2360` | The no-subject arm `bad(...)`s and then execution continued to an affirmative pass line about a file it could not parse | closed | the pass lines are guarded by `_phs` |
| N-009 | Minor | gate | `check-plugin-mutants.sh:1928` | The Current-State mutant wrote `**Phase:** Phase 3`, a shape no template produces and the only one the broken arm could read — so it certified an arm that did nothing | closed | retargeted to the bare form |
| N-010 | Minor | prose | `references/fix-loop.md:381` | F-016's insert was flush-left inside a 3-space list item, orphaning the block and dangling the sentence after it | closed | indentation repaired, sentence rejoined |

**Round 2's own lesson, recorded because it changed how round 3 was verified.**
Two round-1 fixes over-corrected into *failing a conforming input* (N-003,
N-004), which is worse operationally than the hole they replaced: a missed hole
is latent, a false failure blocks every real run. Round 1 verified only that
wrong shapes fail. **The template is the authority on shape**, and round 3
verified both directions — nine probes, of which one turned out to be
mis-designed rather than the fix being broken.

**And a sixth reflow casualty.** All four of N-007's pin mutants were first
written with `grep`/`sed` over raw text; every pinned phrase wraps, so three
SURVIVED and one NO-OP'd while the arm they were proving was correct all along.
The arm reads flattened text; the mutants now do too.

## Round 3 ledger (raised by the round-2 fix's own re-review)

**This round changed approach, at the user's direction.** Rounds 1→2→3 each
produced Criticals from the same two arms — the `findings.md` ledger parse and
the Current-State phase reader — because both parsed free-form prose, and each
fix added a heuristic with a new gap. No finding ID repeated, so the letter of
the convergence rule never tripped; its spirit did. The loop was stopped and the
choice put to the user, who chose **tighten the grammar, not the parser**. Both
arms are now smaller than before: the phase reader has one anchored token where
it had a search, and the ledger parse requires a header the template pins.

| ID | Sev | Area | File:line | Finding | State | Closed by |
| -- | --- | ---- | --------- | ------- | ----- | --------- |
| NEW-01 | Critical | gate | `check-plugin.py:2422` | `_named_phase` searched the whole field for `phase <token>` before its bare-id fallback, so `**Phase:** 3 — moved on past the phase 2 fix loop` resolved to 2 and the gate passed over a finding open against Phase 2 | closed | the reference is anchored at the field's start; `templates/progress.md` prescribes that form |
| NEW-02 | Critical | gate | `check-plugin.py:2346` | N-003's row scoping made the unparseable-ledger `bad()` dead code — `_seen_fid` read `_rows`, empty exactly when no header was found — so a ledger whose header renames `Phase` read as clean with an open Critical | closed | `_seen_fid` scans the file; the header is a pinned grammar |
| NEW-03 | Major | gate | `check-plugin.py:2335` | Only the first matching table's rows were read, so a second blocking table gated nothing | closed | every blocking table is walked, each with its own header |
| NEW-04 | Minor | gate | `check-plugin.py:1556` | `-`/`—` sat inside a `\b` group needing a word character after the dash, so `boundary: -` passed; and the stated word-count could never run, `rec` being a flattened window | closed | dashes are their own alternative; the inoperative count dropped |
| NEW-05 | Minor | gate | `check-plugin.py:1910` | The pin arm `continue`d past a pinned file it could not read, while its pass line claimed every file was checked | closed | an unreadable pinned file is reported |
| NEW-06 | Minor | gate | `check-plugin.py:1895` | The pin's file list omitted `templates/progress.md` — a migration-corrected site, and the file a run copies into its own run directory | closed | added, with its own mutant |
| NEW-07 | Minor | gate | `check-plugin.py:2428` | Two flags computed and never read (N-006's own complaint, carried into its replacement), and the nonexistent-phase report unguarded by `_phs`, giving three diagnoses for one defect | closed | flags dropped, report guarded |

**A negative result worth keeping.** The re-reviewer established that the
boundary arm's *stated* mechanism was not the one running — the word count could
never fire — and that removing it costs nothing, because a one-word boundary
(`boundary: seam`) is legitimate and must pass. Without that, the obvious "fix"
would have been to enforce the word count and break a conforming shape, which is
round 2's mistake again.

## Round 4 ledger (raised by the round-3 fix's own re-review)

**Round 4's re-review came back with the risk of the grammar approach not
having materialised:** both directions were clean — no shape the templates or
the three fixtures prescribe now fails — all seven NEW-* closed, and no
regressions. What remained were three small mechanical defects in a parser that
is now smaller than it was, plus six Minors. All ten are fixed here.

| ID | Sev | Area | File:line | Finding | State | Closed by |
| -- | --- | ---- | --------- | ------- | ----- | --------- |
| NEW-F1 | Critical | gate | `check-plugin.py:2456` | The phase token was anchored inside the field's value but the FIELD was still located by a search over the whole tracker, so a prose line containing `**Phase:** 2` outranked the real Current State — and round 4 had itself added a literal `**Phase:**` example to the template every run copies | closed | the `## Current State` block is isolated first; the field must be a list item at a line start |
| NEW-F2 | Critical | gate | `check-plugin.py:2383` | The row detector was the one comparison in the arm that skipped `_norm`, so `\| **F-002** \|` was not a row at all — dropped from the table walk and from `_seen_fid`, so nothing reported it | closed | one normalised row test used everywhere |
| NEW-F3 | Major | gate | `check-plugin.py:2384` | `_seen_fid`'s `count("\|") >= 6` filter excluded a four-column blocking table, the minimum the template blesses, making its "a renamed column turns into a build failure" claim false for that shape | closed | no width filter; row-ness is "first cell is an F-id", width is checked against the header and reported |
| NEW-F4 | Minor | gate | `check-plugin-mutants.sh` | The second-blocking-table mutant was co-killed by table 1's own open row, so it proved nothing about walking more than one table | closed | the mutant closes table 1's row first |
| NEW-F5 | Minor | gate | `check-plugin-mutants.sh` | The unreadable-pinned-file mutant was co-killed by the generic read arm | closed | mutant deleted; the branch is recorded as deliberately unpinned, because an unreadable skill file trips several arms and no mutation isolates it |
| NEW-F6 | Minor | gate | `check-plugin.py:2426` | NEW-07 guarded the Current-State half's "matches no heading" report but left the ledger half's identical report unguarded, so an unparseable tracker drew a second, misleading diagnosis | closed | both halves guarded by `_phs`; one diagnosis, verified |
| NEW-F7 | Minor | prose | `templates/progress.md:52` | The template claimed the gate reports a phase-less field; it does not, and `run-ok` ships that shape legitimately | closed | the claim now matches the behaviour: legitimate when nothing is unfinished, reported as uncheckable when something is |
| NEW-F8 | Minor | gate | `check-plugin.py:2380` | `_rows += _tbl` was a dead assignment that also shadowed the loop variable | closed | deleted |
| NEW-F9 | Minor | gate | `check-plugin.py:2120` | The phase label kept the whitespace it matched while every lookup builds one space, so `## Phase  2` matched nothing and drew four reports for one stray space | closed | the label is normalised at capture; verified 0 reports |

**A process bug of the executor's own, recorded because it discarded work
silently.** The edit helper used through this branch wrote its file only after
every edit in a batch succeeded, so one missed anchor calling `sys.exit(1)`
threw away three edits that had already applied — and the verification run
immediately afterwards was testing unmodified code, reporting the old failure.
It was caught only because a probe that should have gone to zero stayed at
three. The helper now writes what succeeded before reporting what did not. Same
class as every other finding in this ledger: a green-looking result from a check
that never ran.

## Round 5 ledger (raised by the round-4 fix's own re-review)

**Round 5's re-review was the first with no Critical, and the first to give a
convergence assessment.** Its verdict: the ledger half has converged and would
ship; the Current State field reader had not, because five rounds had produced
five locator bugs and every one failed the **same way — silently**, falling back
to `**Next action:**` and printing an affirmative pass. So round 6 is not a
sixth locator heuristic. It makes the failure **loud**: a `**Phase:**` field the
arm cannot locate is now a build failure.

| ID | Sev | Area | File:line | Finding | State | Closed by |
| -- | --- | ---- | --------- | ------- | ----- | --------- |
| RR5-1 | Major | gate | `check-plugin.py:2499` | **A round-5 regression.** Narrowing the locator to a `-`/`*` list item made `**Phase:** 3`, `+ **Phase:** 3` and `1. **Phase:** 3` silently unreadable, so an openly advanced field gated nothing. The pre-round-5 code read all three | closed | marker optional; heading anchored; **an unlocatable field is reported** |
| RR5-2 | Major | gate | `check-plugin.py:2407` | Row-ness required exactly `F-<digits>`, so a row keyed `N-002` or `F-002a` was dropped from the table walk **and** from the unread-row count — nothing printed. Reachable on this migration's own ledgers, which use `N-`, `NEW-` and `NEW-F` ids | closed | row-ness is "the first cell looks like a finding id"; `F-NNN` pinned in the template |
| RR5-3 | Minor | gate | `check-plugin.py:2496` | The block split key was un-anchored, so a tracker quoting `## Current State` in prose **false-failed** | closed | anchored to a line start; verified passing |
| RR5-4 | Minor | gate | `check-plugin.py:2496` | A duplicated `## Current State` block was unreported, leaving a stale block authoritative | closed | reported, with a mutant |
| RR5-5 | Minor | gate | `check-plugin-mutants.sh:2060` | The decoy mutant died under either half of the NEW-F1 fix, pinning neither | closed | rewritten as a line-start item above the heading, pinning block isolation alone |
| RR5-6 | Minor | gate | `check-plugin.py:2545` | Both fields naming a nonexistent phase drew three reports, one of them false | closed | the phaseless branch skips fields that were read |

**And one more instance of the failure mode this whole ledger is about.** The
retargeted decoy mutant SURVIVED its first run — a **mutant** bug, not a gate
bug: it inserted the decoy before substituting, so `count=1` advanced the decoy
and left the real field correct, and its guard passed because the decoy carried
the string the guard grepped for. A check reporting success without having
examined the thing it names, for the seventh distinct time on this branch (an
empty `reviews` list, an unnormalised cell, a reflowed anchor, a stripped
fixture target, a ugrep dash, an edit helper discarding writes, and now a
substring guard two lines could satisfy). It now asserts **positionally** — the
real field inside the block changed, the decoy landed above the heading.

## Round 6 ledger — the cap-exempt regression correction

**The fix-loop cap (5) fired here.** The round-6 re-review returned
`FINDINGS MUST BE FIXED` with one Critical that round 6 had itself introduced,
and recommended treating it as a regression correction rather than a sixth
iteration — undoing a regression completes the round already counted. The choice
was put to the user, who directed exactly that. RR6-3 was fixed too rather than
deferred, because deferring it would have left a claim finding in a shipped
template.

| ID | Sev | Area | File:line | Finding | State | Closed by |
| -- | --- | ---- | --------- | ------- | ----- | --------- |
| RR6-1 | Critical | gate | `check-plugin.py:2594` | **A round-6 regression.** The guard keyed off `_*_seen` ("a field exists") instead of `_*_id` ("a field named a phase"), so `**Phase:** done` — a form the template blesses and `run-ok` ships — plus a phaseless `Next action` printed `ok no unfinished phase` over an open Major. Round 5 had this input FAILing | closed | the affirmative arms require a comparison to have happened |
| RR6-2 | Major | gate | `check-plugin.py:2531` | `re.search` is first-match-wins, so a stale `**Phase:**` line left above a fresh one *inside* the block silently became the field read — RR5-4's rule one level down | closed | more than one `**Phase:**` in the block is reported |
| RR6-3 | Minor | gate | `check-plugin.py:2421` | Row-ness still required a digit after the dash and letters before it, dropping `NEW-F2` and `RR5-2` — **the ids this branch's own ledger uses for rounds 4 and 5**, and `NEW-F` was the shape the code comment cited as its own reachability argument | closed | widened to any finding-id shape, making the template's claim true rather than narrowing the claim |
| RR6-4 | Minor | gate | `check-plugin.py:2600` | A nonexistent-phase report was followed by a false `ok no unfinished phase` | closed | guarded; **unpinnable by a mutant** (removing it restores a false line on a build red either way), so verified by hand — every probe asserts zero false-ok lines |

**What the round-6 re-review established beyond the findings**, and the reason
this correction is a generalisation rather than three patches: *"the first change
on this branch that removed a class rather than an instance"* — it reintroduced
round 5's exact locator bug and got a red build instead of an `ok` line, and 15
of 18 loss shapes now report loudly. But the premise was applied one layer too
narrowly. The five locator bugs were instances of a bigger invariant: **the arm
must never print an affirmative line about a comparison it did not make.** Round
6 fail-closed on "could not locate the field"; RR6-1 and RR6-2 are "located it
but it resolved to nothing" and "located a field, but not the right one". The
affirmative arms now require the comparison, and each remaining case is reported
by a named arm.

## Counters

| Scope | Fix-loop iteration | Cap | Deepest fix-mode depth this chain | Cap |
| ----- | ------------------ | --- | --------------------------------- | --- |
| Migration (Phase 5) | 5 | 5 | 0 | 2 |

## Iteration log (convergence rule input)

| Iter | Scope | Depth | Targeted F-IDs | Open after re-review | At |
| ---- | ----- | ----- | -------------- | -------------------- | -- |
| 1 | Migration | 0 | F-001..F-024 | N-001..N-010 raised | 2026-09-07 |
| 2 | Migration | 0 | N-001..N-010 | NEW-01..NEW-07 raised | 2026-09-07 |
| 3 | Migration | 0 | NEW-01..NEW-07 | NEW-F1..NEW-F9 raised | 2026-09-07 |
| 4 | Migration | 0 | NEW-F1..NEW-F9 | RR5-1..RR5-6 raised | 2026-09-07 |
| 5 | Migration | 0 | RR5-1..RR5-6 | RR6-1..RR6-4 raised (cap reached) | 2026-09-07 |
| 5r | Migration | 0 | RR6-1..RR6-4 | <pending re-review> — cap-exempt regression correction, user-directed | 2026-09-07 |
