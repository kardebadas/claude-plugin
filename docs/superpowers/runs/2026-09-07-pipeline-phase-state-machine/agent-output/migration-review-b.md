# Migration review B — pipeline phase state machine

**Reviewer:** Reviewer B (whole-change review, `main..HEAD`, 17 commits / 41 files)
**Verdict ownership:** the gates and their evidence — `tools/check-plugin.py`,
`tools/check-plugin-mutants.sh`, `tools/fixtures/*`, `.github/workflows/checks.yml`,
the two plugin manifests and `.claude-plugin/marketplace.json`.
**Method:** read the whole diff; then ran every gate myself; then *replayed each new
mutant and 13 conforming-but-wrong probes of my own* against throwaway copies and read
the actual `FAIL` text, because a mutant that dies is not evidence that it died for its
own reason.

---

## 1. Commands run, and their real output

```
$ cd /home/wp3/IntellijProjects/claude-plugin
$ ./tools/check-plugin.sh | tail -3
  ok    87 cited mutant names all defined in check-plugin-mutants.sh

check-plugin: PASS

$ for d in run-ok run-open-rv run-fixloop; do ./tools/check-plugin.sh --run tools/fixtures/$d | tail -2; done
### run-ok
check-plugin: PASS
### run-open-rv
check-plugin: PASS
### run-fixloop
check-plugin: PASS

$ ./tools/check-plugin-mutants.sh 2>&1 | tail -6
  killed    implemented-unreviewed fixture opens its review early
  killed    implemented-unreviewed fixture advances to the next phase
  killed    fix-loop fixture advances with a blocking finding open
  killed    fix-loop fixture dispatches a round with no fix plan on disk
  killed    CI stops linting one of the fixture run directories

killed=137 survived=0
check-plugin-mutants: PASS

$ python3 -m unittest discover -s plugins/superb/skills/craft/tests 2>&1 | tail -3
Ran 19 tests in 0.407s

OK
```

`grep -i "SURVIVED|no-op|WARN"` over the full 146-line harness log returns **only** the
`killed=137 survived=0` summary line — no `SURVIVED`, no no-op diagnostic, no warning.
`grep --version` confirms `ugrep 7.8.4`, so the dash hazard documented above
`run_mutant()` is live in this environment; a mechanical scan of every `grep`
invocation in the harness for a pattern beginning with `-` without a preceding `--`
returns **0 hits**, so that class is closed.

### Attribution replay — every new mutant killed by its own arm

Replayed each mutation into a fresh copy and captured the actual `FAIL` line(s):

| Mutant | `FAIL` that killed it | Attributable? |
|---|---|---|
| reviews a phase with an unchecked task | `progress.md:119: Phase 2's RV is [x] while 1 task line(s)…` | yes, sole FAIL |
| reviews a phase with a task still in progress | `progress.md:125: Phase 3's RV is [x] while 1 task line(s)…` | yes, sole FAIL |
| advances past a phase with an open RV | `Next action names a phase later than Phase 1, which still has an open RV/RVJ line` | yes, sole FAIL |
| advances past a phase with an open blocking finding | `…later than Phase 1, which still has open blocking finding F-001 (Critical)` | yes, sole FAIL — proves the ledger half runs |
| next action names a later phase than its own state | `…later than Phase 2, which still has an open task line and an open RV/RVJ line` | yes, sole FAIL |
| integration reviewer with no boundary | `progress.md:119: declares an integration reviewer but names no boundary: <what>` | yes, sole FAIL |
| multi-slice round silent about its integration reviewer | `progress.md:144: declares 2 slice reviewers and no integration reviewer, and does not say why` | yes, sole FAIL |
| **declares two integration reviewers** | `declares 2 integration reviewers…` **plus** `declares 4 reviewers, lists 3 report files` | **NO — see Minor 1** |
| fix round names no fix plan | `progress.md:137: round declaring M=2 names no fixplan <file>.md` | yes, sole FAIL |
| cites a fix plan not in agent-output | `progress.md:137: round names fix plan 'p3-fixplan-r9.md', which is not in agent-output/` | yes, sole FAIL |
| run-open-rv opens its review early | `run-open-rv/progress.md:36: Phase 2's RV is [~] while 1 task line(s)…` | yes, sole FAIL |
| run-open-rv advances to the next phase | `…later than Phase 2, which still has an open RV/RVJ line` | yes, sole FAIL |
| run-fixloop advances with a blocking finding open | `…later than Phase 2, which still has open blocking finding F-002 (Major)` | yes, sole FAIL |
| run-fixloop round with no fix plan on disk | `run-fixloop/progress.md:39: round names fix plan 'p2-fixplan-r2.md', which is not in agent-output/` | yes, sole FAIL |
| CI stops linting one of the fixture run directories | `checks.yml never lints tools/fixtures/run-fixloop with --run` | yes, sole FAIL |
| task-brief missing / non-executable / no shebang | own arm each (`== pipeline dispatch scripts ==`) | yes |

So the two resume fixtures **do** encode the states they claim and arms **do** read
them (four kills land on `run-open-rv` / `run-fixloop` specifically), and 15 of the 16
new mutants are attributable. That is good work. The findings below are what the
harness structurally cannot see.

### Conforming-but-wrong probes I ran (the item-12 sweep)

Each was applied to a throwaway copy and the gate run over it. `PASS` here means the
gate reported `check-plugin: PASS` on an input that violates the invariant the arm
exists for.

| # | Probe | Result |
|---|---|---|
| P1 | ledger `State` cell written `Open` (capital) + Next action advanced past that phase | **PASS** (should FAIL) |
| P2 | ledger `Sev` cell written `**Major**` + advanced | **PASS** (should FAIL) |
| P3 | ledger gains one column so `State` is col 7 + advanced | **PASS** (should FAIL) |
| P4 | ledger `Phase` cell written `Phase 2` instead of `2` + advanced | **PASS** (should FAIL) |
| P5 | fix round relabelled `N=2 C=1 → 1 slice + 0 integration`, `fixplan` deleted | **PASS** (should FAIL) |
| P5b | fix round written `C=1 → 1 slice + 0 integration` (no `M=`/`N=`), `fixplan` deleted | **PASS** (should FAIL) |
| P6 | `fixplan: p2-fixplan-r2.md` (colon form) | FAIL — loud, correct |
| P7 | task line renamed `Task 5` while its phase's `RV` is `[~]` | FAIL — arm survives (`T`+`ask` still matches) |
| P7b | task line renamed `2.5 — a task` while its phase's `RV` is `[~]` | **PASS** (should FAIL) |
| P7c | task line bolded `**T5**` while its phase's `RV` is `[~]` | **PASS** (should FAIL) |
| P8 | `**Phase:** 3` while Phase 2 holds an open blocking finding | **PASS** (should FAIL) |
| P9 | `nint not in (0,1)` branch replaced with `if False:`, then double the integration count | **still FAIL** — killed by the report-count arm |
| P9b | double the integration count *and* grow the report set to match | FAIL from the own arm (arm is functional) |
| P10 | phase headings demoted to `### Phase N`, review opened early **and** Next action advanced | **PASS**, and the gate printed `ok  no unfinished phase in the tracker` |
| P11 | `**Phase:** 3` + `**Next action:** T4 — a task` (no phase word) while Phase 2 has an open finding | **PASS** |
| P12 | `M=0 → no round` record also names a `fixplan` | **PASS** (prose forbids it) |
| P13 | **legal** joining-phase shape: leading `[x] RVJ` above that phase's own unstarted tasks | **FAIL — false positive** |

---

## 2. Findings

### Critical

#### C1 — The `findings.md` ledger parse silently drops rows, and the no-advance arm then *affirms* the invariant it did not check
`tools/check-plugin.py:2126-2137` (regex at `:2126-2128`, severity filter at `:2131`,
phase lookup at `:2133`), pass line at `:2160-2166`.

The row regex is
```python
r"^\|\s*(F-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|" r"[^|]*\|[^|]*\|\s*open\s*\|"
```
It is correct for the shipped `templates/findings.md` shape (7 columns, `State` in
column 6) — I checked that against the template and against `run-fixloop/findings.md`.
It silently misses **every** deviation, and I measured four:

- **`| Open |`** — the pattern is not `re.I`, so a capitalised state is not `open` and
  not anything else either; the row vanishes (P1).
- **`| **Major** |`** — `_sev.lower()` is then `"**major**"`, which is not in
  `("critical","major","bug")`, so `:2131` `continue`s past it (P2). This is the most
  likely shape to occur: the ledger's own prose bolds every tier name it discusses, and
  the orchestrator writing the row has just read that prose.
- **an extra column** — `State` moves to column 7 and the fixed `[^|]*\|[^|]*\|` spine
  no longer lands on it (P3).
- **`| Phase 2 |`** in the `Phase` cell — `:2133` looks up `f"phase {_phl}"`, i.e.
  `"phase phase 2"`, which is in no index, so the blocker is dropped (P4).

Any one of these makes the arm's ledger half vacuous while the gate prints
`ok  Next action does not point past an unfinished phase`. That is an affirmative claim
about the advancement invariant, made over a tracker that advanced past a phase with an
open Critical/Major finding. It is the same defect class as the history the design doc
cites — "every gate read *no open blocking IDs*, which is vacuously true when review
never ran" — with the vacuity moved from the predicate into the parser. Worse than the
2026-09-01 case in one respect: the pass line here *names* the thing it did not
establish, and the arm already knows how to say otherwise (`_ledger_note` at `:2157`
exists precisely to avoid this for an absent file).

**Why it matters:** this is the one arm standing between the run and the failure the
whole migration was designed to prevent, and it is defeated by markdown bolding.

**Concrete fix** (all in `check-plugin.py`):
1. Add `re.I` to the row `finditer`, and match the state cell as
   `\s*open\s*` case-insensitively.
2. Normalise the cells before comparing: strip `*`, `` ` `` and whitespace from `_sev`
   and `_phl`, and strip a leading `phase\s*` from `_phl` before the `_idx` lookup.
3. Stop counting columns. Split the row on `|`, drop the empty ends, and locate `State`
   and `Sev` **by the ledger's own header row** (`| ID | Sev | Phase | … | State | … |`)
   rather than by fixed position.
4. Make the shape checkable rather than assumed: if `findings.md` is present and holds a
   blocking-ledger table whose header row does not carry the expected column names, or
   which contains an `F-\d+` row that the row regex does not match, `bad(...)` — an
   unparseable ledger must read as "not checked", never as "empty". Add a mutant that
   bolds `Sev` on the `run-fixloop` open row and advances `Next action`; it must be
   killed by this arm alone.

---

### Major

#### J1 — `parse_tracker_phases` can return an empty list, and both new run-mode arms then check nothing on a green build
`tools/check-plugin.py:1988` (heading regex), `:1996` (bullet regex), `:2062`, `:2082`,
`:2166`.

The heading regex is `r"##\s+(Phase\s+[^\s—·]+)"` and the bullet regex requires
`(RVJ|RV|T[0-9A-Za-z.]+)`. Both are unenforced conventions:

- Demote the headings to `### Phase N` and `_phs` is `[]`. The review-not-early arm is
  guarded by `elif _phs:` so it prints nothing, and the no-advance arm falls through to
  `ok("no unfinished phase in the tracker")` — an affirmative pass over a tracker it
  could not parse. Measured (P10) with a review opened early **and** `Next action`
  advanced: `check-plugin: PASS`.
- Write task lines as `- [ ] 2.5 — …` or `- [ ] **T5** — …` and the phase has zero
  tasks as far as the arm is concerned; a `[~]` `RV` over open work passes. Measured
  (P7b, P7c).

This file already knows the rule and states it two hundred lines earlier, at `:1782-1795`:
"an arm whose subject can vanish from the docs is an arm that silently starts checking
nothing, and the count in the pass line is what makes that visible on a green build" —
which is why `seen` and `nseen` are each separately required non-zero. The two new arms
were not given the same treatment.

**Concrete fix:** after `:2062`, `if not _phs: bad(...)` — a tracker with a closed `RV`
round and no parseable `## Phase` heading is a tracker this gate cannot check, and it
must say so. Report `len(_phs)` and the task count in both pass lines. Loosen the
bullet regex to `\[([ x~])\]\s*\**\s*(RVJ|RV|T[\w.]+)` so a bolded or dotted task id is
still a task, and add a mutant that demotes the fixture's headings — it must be killed
by the new "no phases parsed" branch.

#### J2 — The review-not-early arm FAILs the legal leading-`RVJ` joining-phase shape the skill's own templates prescribe
`tools/check-plugin.py:2062-2080`.

`templates/progress.md` (RVJ block) and `references/run-state.md` both say an `RVJ` is
"Placed AFTER a split's last sibling, or **ABOVE the first task of a joining phase**",
and `SKILL.md`'s `RV` note repeats it: "a joining phase's `RVJ` leads, sitting above
that phase's first task". So a joining phase whose lanes have just merged legitimately
looks like:

```markdown
## Phase 4 — a joining phase · deps: Phase 2, Phase 3
- [x] RVJ — joint integration review · lanes A+B · N=5 → 0 slice + 1 integration …
- [ ] T7 — a task · W1 · deps none
- [ ] RV — review fan-out
```

The arm collects `RVJ` into `_ph["reviews"]` and the phase's own unstarted tasks into
`_ph["tasks"]`, and reports:

```
FAIL  run-open-rv/progress.md:43: Phase 4's RVJ is [x] while 1 task line(s) in that
      phase are not [x] (first at line 45, T7) — …
```

Measured (P13). A leading `RVJ` does not review *this* phase — it reviews the lanes that
joined into it — so the arm's premise ("a started round and an unchecked task line
cannot both be true of a phase reviewed as a whole") does not hold for it. Consequence:
any real run that uses lanes cannot pass `--run` until the joining phase finishes, and
Stage 5's linter duty makes a `FAIL` block the finish. The pressure that creates is to
tick the box early or move the `RVJ`, both of which are worse than the state the arm was
protecting. It went unseen because no fixture and no worked example encodes a leading
`RVJ` (see Minor 6), so the arm has never met one.

**Concrete fix:** restrict `_startedr` to `RV` lines, and handle `RVJ` separately with
its placement rule: a **trailing** `RVJ` (below the phase's last task line) is subject to
the same "all tasks `[x]`" condition; a **leading** `RVJ` (above the phase's first task
line) is exempt, because its subject is the joined lanes and not this phase.
`parse_tracker_phases` already carries line numbers, so the leading/trailing test is
`rvj_lineno < min(task linenos)`. Add both shapes to a fixture and a mutant for the
trailing case.

#### J3 — The fix-plan arm is scoped to `key == "M"`, so relabelling the round removes the requirement
`tools/check-plugin.py:1608` (`if d.group("key") == "M" and int(d.group("n")) >= 1:`),
regex at `:1237`.

`decl` at `:1234-1236` accepts `N` or `M` as the round key. Rewrite the fixture's
planned round as
```
→ round 2: N=2 C=1 → 1 slice + 0 integration · reports p2-rr2-a.md · coverage …
```
with the `fixplan` field deleted, and the gate PASSes (P5). Nothing else objects:
`ceil(2/5)` is 1, so the sizing arm at `:1493` is satisfied by the declared `1 slice`,
and the `C=` arm at `:1571` is also `M`-scoped. So the required fix-plan artifact — the
whole of spec §3 — is optional to anyone who writes `N=` on a fix round, and there is no
arm anywhere saying a round appended with `→ round <n>:` must be keyed `M`.

`M=0 → no round` **is** correctly exempt (the `nor` branch at `:1391` `continue`s before
reaching `:1608`) — I confirmed the two such records in the tree keep passing.

**Concrete fix:** an appended `→ round <n>:` record is by definition a fix round, so key
off the round mark rather than off the declaration: require `key == "M"` on any record
whose `start` match was the `round` alternative, and `bad(...)` when it is keyed `N`
("a re-review round is sized by its fix diff's clusters, not by a task count").
Then keep the `m >= 1` fixplan requirement as written. Add a mutant that rewrites
`M=2 C=1` to `N=2 C=1` on the `run-ok` round; it must die on the new branch.

#### J4 — A closed round whose declaration is absent or malformed is skipped entirely, taking every new arm with it
`tools/check-plugin.py:1425` — `if not d: continue  # e.g. the WAIVED form, which
carries no counts`.

Write the fix round as `→ round 2: C=1 → 1 slice + 0 integration` (no `M=`, no `N=`) and
`decl` does not match, so the record is dropped before the `RVJ` shape arm, the
`ceil(N/5)` arm, the conditional-integration arm, the reports-count arm, the coverage
arm and the new fix-plan arm. Measured: `check-plugin: PASS` with no fix plan named and
none on disk (P5b). The same escape hides a multi-slice round from the integration
declaration requirement.

The `continue` predates this branch (it exists for the `WAIVED` form), but this branch
hangs two new invariants off the code path behind it, which promotes it from a laxity to
a bypass. It is also self-concealing: because `seen` is not incremented, a tracker with
one conforming round elsewhere still reports `rseen > 0` and never mentions the round it
could not read.

**Concrete fix:** narrow the exemption to the form it was written for. Detect the
`WAIVED` shape explicitly (`WAIVED by user:` in `rec`) and `continue` only for that;
for any other closed round or appended round with no parseable declaration, `bad(...)`
naming the record and demanding the `N=`/`M=` declaration. Add a mutant that strips
`M=2 ` from the `run-ok` round and leaves `C=1` behind.

#### J5 — Only `**Next action:**` is read; `**Current State**`'s `**Phase:**` field is never checked, and a `Next action` naming no phase makes the arm vacuous
`tools/check-plugin.py:2139-2144`, `:2160-2170`; section comment at `:2086`
("**Current State** may not point past an unfinished phase"); spec gate table,
`docs/superpowers/specs/2026-09-07-pipeline-phase-state-machine-design.md:302`
("`Current State` naming a later phase … fails").

`templates/progress.md` gives `Current State` two machine-readable fields:
`- **Phase:** <current phase number and name>` and `- **Next action:** …`. The arm reads
only the second. Measured:

- P8: `- **Phase:** 3 — moved on` while Phase 2 holds `F-002` open → **PASS**.
- P11: `**Phase:** 3` *and* `**Next action:** T4 — a task` (no phase word, which is the
  template's own suggested form — "the single next unchecked line") → **PASS**. `_named`
  is `None`, and `_named is None` is a pass in every branch.

So the arm holds only the *narrow* reading of the invariant, while the linter's own
comment, the spec's gate table and the pass-line wording all claim the broad one. An
orchestrator that writes `Phase: 4` and a bare `Next action: T5` advances with the gate
green — and `Phase:` is the field the resume protocol's reader looks at first.

**Concrete fix:** read both fields. Resolve `**Phase:**` through the same `_idx`, and
FAIL when *either* field names a phase later than `_blockers[0][0]`. When there is an
unfinished phase and **neither** field names a phase, that is not a pass either —
`bad(...)` requiring `Current State` to name the phase it is in, since an unlocatable
Current State is exactly what makes the invariant uncheckable. Add two mutants (one per
field), each killed by this arm alone.

---

### Minor

#### N1 — The "declares two integration reviewers" mutant is killed by the wrong arm
`tools/check-plugin-mutants.sh:1585-1594`; arm at `tools/check-plugin.py:1509`.

The mutant rewrites `2 slice + 1 integration` to `2 slice + 2 integration` and leaves
the three-file `reports` set alone, so the reviewer-count arm (`declares {want}
reviewers, lists {got} report files`) also fires. I replaced the arm's condition at
`:1509` with `if False:` and re-ran the mutation: it still dies (P9). So the mutant
proves nothing about its own arm. The arm *is* functional — P9b (double the count and
grow the report set to four) produced `declares 2 integration reviewers` from the own
arm — but that is my measurement, not the harness's. The mutant's own guards
(`grep -q "boundary: the T2 contract" || echo …`) cannot catch this, because
`run_mutant` discards the mutation script's output whenever the mutant is killed
(`tools/check-plugin-mutants.sh:33-38`) — see N2.

**Fix:** grow the report set with the reviewer count and add the fourth report file, as
P9b did, so only the own arm can fire. It will still co-fire with the coverage-row arm,
so also add `p2-review-int2.md`'s coverage row — or, simpler, mutate a round whose
declaration is `1 integration` down to `0` and up to `2` in one step that keeps
`want` constant (`2 slice + 2 integration` with `1 slice + 3 integration` is not it;
prefer building the case on a fixture round dedicated to this mutant).

#### N2 — `run_mutant` discards a mutant's own no-op diagnostics whenever the mutant is killed
`tools/check-plugin-mutants.sh:33-38`.

`out` is captured and printed **only** on `SURVIVED`. Every guard of the form
`… || echo "mutant is a no-op: … so a kill could come from another arm"` is therefore
inert in exactly the situation it was written for: if another arm kills the mutant, the
harness prints `killed` and throws the warning away. That is the structural reason N1
escaped, and the reason the branch's own execution log had to discover three of its four
silent-failure classes by hand.

**Fix:** print `out` whenever it is non-empty, on kill as well as on survival, prefixed
so it is visibly a diagnostic and not a failure — and consider exiting non-zero when any
diagnostic mentions "a kill could come from". A `killed` line with a suppressed
"this kill is not attributable" note is worse than no line at all.

#### N3 — `M=0 → no round` may carry a `fixplan` and nothing objects
`tools/check-plugin.py:1392-1420` (the `nor` probs list); prose at
`SKILL.md` `RV` field table and `references/run-state.md:95-100`
("**absent from an `M=0 → no round` record**, which dispatched no fix and so had nothing
to plan").

The `nor` branch checks for `reports`, `coverage`, a declaration and a pinned route, but
not for `fixplan`. Appending `· fixplan p3-fixplan-r2.md` to the fixture's `M=0` record
passes (P12). A `no round` record naming a fix plan claims a plan for fixes that never
ran — the same shape as "claiming reviewers a round of nobody never had", which that
branch already rejects two lines away.

**Fix:** add `if fixp.search(body): probs.append("names a `fixplan`, which no `M=0 → no
round` record can carry — no fix ran, so there was nothing to plan")`, plus a mutant.

#### N4 — The boundary check accepts any `boundary:` in the record, including a declared absence
`tools/check-plugin.py:1514` — `not re.search(r"boundary:\s*\S", rec)`.

`· boundary: none` or `· boundary: n/a` satisfies it, as would the word appearing inside
a round's free-text `scope:` prose (`run-ok`'s Phase 3 record is 400+ characters of such
prose). The arm's purpose is that a reader can tell a decided boundary from an
undecided one, and `boundary: none` defeats that while declaring `i=1`.

**Fix:** reject a boundary whose value is `none`/`n/a`/`-`/`tbd`, and anchor the match
to a field position (`(?:^|[·|])\s*boundary:\s*`) rather than anywhere in the record.

#### N5 — The CI fixture arm matches by substring, so one fixture can satisfy another's requirement
`tools/check-plugin.py:1150-1163` — `if f"--run {_rel}" not in t:`.

`--run tools/fixtures/run-ok` is a substring of `--run tools/fixtures/run-okay`, so a
future fixture whose name extends an existing one is covered by the wrong step. The arm
is otherwise well built — it enumerates `tools/fixtures/*/progress.md` rather than
hard-coding names, so a fourth fixture is caught the day it lands, and its mutant is
attributable.

**Fix:** match on a word boundary — check each `--run <path>` token parsed out of the
workflow against the fixture set, rather than substring-testing the whole file.

#### N6 — No run-mode fixture contains an `RVJ`, so the `RVJ` arms have no conforming run-mode input
`tools/fixtures/*/progress.md` — `grep -c RVJ` returns 2 for `run-ok` (both in prose,
neither a bullet) and 0 for the two new fixtures.

The `RVJ` shape arm at `:1430` and the `RVJ` handling in the two new arms are exercised
only by the skill's own worked examples in `pdir` mode, where the review-not-early and
no-advance arms do not run at all. That is precisely how J2 stayed invisible.

**Fix:** add an `RVJ` phase to a fixture — both placements: a split's trailing `RVJ`
below its sibling's tasks, and a joining phase's leading `RVJ` above its own. The second
is the input that makes J2's fix checkable, and it belongs in CI beside the other three.

---

## 3. Items reviewed with nothing to report

Stated explicitly, per the review contract:

- **Item 1 — reintroduction of task-level review.** None. The five-pattern sweep
  (`check-plugin.py:1867-1901`) runs over flattened text of every `pdir` `.md`, which
  closes the wrap-across-lines hole; I searched the skill independently for
  `review (each|every|the) task`, `task-level review`, `reviewer for (the|each) task`,
  `adversarial` and `review its own task` and the only hits are prohibitions in
  `references/implement.md:19-20` phrased so they do not trip the sweep
  ("no task-scoped reviewer", "no adversarial pass"). No arm anywhere *permits* task
  review. The four sweep mutants are each attributable and each re-introduces exactly
  one sentence.
- **Item 7 — the deleted pre-`RV` round.** Fully removed: the held-phrase entry, its
  citation, the summary clause, the mutant and the sibling assertion naming it are all
  gone; `templates/findings.md`'s Counters scope now reads "A build-gate failure before
  the phase's review has run is not a scope here at all", with no `pre-RV` row. The one
  surviving repo-wide mention outside `docs/` is
  `references/implement.md:130` — "`RV` is a fix loop; there is no pre-`RV` fix loop to
  enter" — which is the deliberate prohibition. Nothing depends on the removed rule.
- **Item 9 — stale SDD references in the tools.** All remaining mentions in
  `check-plugin.py` (`:254`, `:276`, `:1803-1804`, `:1842-1861`) are the comments
  explaining the removal and the `bug-fix` scope carve-out, which the brief says to leave
  alone. No arm still requires SDD attribution.
- **Item 10 — model selection.** `grep -i "opus|sonnet|haiku|model"` over both tools
  returns **nothing**. No tier is forced. (`templates/implementer-prompt.md:8` and
  `references/implement.md:45-53` carry model *guidance* in the skill, which is not the
  tools and not in scope.)
- **Item 8, the parts that hold.** `i=0` at one slice is unconditional — the branch at
  `:1533` sits in an `elif` chain that `nslice == 1` cannot reach earlier, and the
  existing `worked one-slice round adds an integration reviewer` mutant kills it.
  `RVJ` remains exempt from the conditional-integration branches (`nslice == 0` matches
  none of them) and remains held to `0 slice + 1 integration` by `:1430`. A multi-slice
  round cannot omit the declaration (mutant G, sole-FAIL) — except through J4.
- **Manifests and marketplace.** `0.11.0 → 0.12.0` in both
  `plugins/superb/.claude-plugin/plugin.json` and
  `plugins/superb/.codex-plugin/plugin.json`; `.claude-plugin/marketplace.json`'s
  description rewritten to "a per-phase review gate no phase advances past until it
  closes, planned fix rounds" with `reviewer fan-out, a recursive fix loop` dropped —
  consistent with the new architecture and with the two READMEs (spec §8 satisfied:
  root `README.md:142-147` is now a phase-level promise, `:206-219` remaps Stage 4 to
  pipeline's own references and records SDD as `bug-fix`'s dependency).
- **`.github/workflows/checks.yml`.** All three fixtures linted, with a comment saying
  why; the bare run and the mutant harness both still present.
- **Recorded deviations.** I read the execution log at
  `docs/superpowers/plans/2026-09-07-pipeline-phase-state-machine.md:2895-3142`. It is
  unusually honest and complete — it records the arm-placement `NameError`, the fifth
  sweep pattern, the disarmed severity arm, the four reflow-broken mutants, the ugrep
  hazard and the CI-arm weakening. **None** of C1 or J1–J5 or N1–N6 appears there, so
  none of them is a recorded deviation.

---

## 4. Verdict

The architecture change is right and the evidence behind it is far above the usual bar:
15 of 16 new mutants kill through their own arm and no other, the two resume fixtures
encode real states that arms genuinely read, and CI now lints all three. What the
harness cannot see is what I found: the advancement invariant's ledger half is defeated
by markdown bolding and its `Current State` half reads only one of two fields (C1, J5);
the tracker parser can silently yield no subject at all while the gate affirms the
invariant (J1); the required fix-plan artifact is optional to anyone who writes `N=` on
the round, or no declaration at all (J3, J4); and the review-not-early arm rejects a
legal shape the skill's own templates prescribe (J2).

C1, J1, J3, J4 and J5 are each a green gate over the exact violation the migration
exists to prevent. J2 is a red gate over a legal run. All six are fixable inside
`check-plugin.py` plus fixtures and mutants; none requires revisiting the design.

**Counts:** Critical 1 · Major 5 · Minor 6.

VERDICT: FINDINGS MUST BE FIXED
