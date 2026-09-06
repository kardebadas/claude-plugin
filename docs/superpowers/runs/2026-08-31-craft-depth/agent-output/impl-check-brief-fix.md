# check-brief against real briefs — implementation log

Branch `fix/check-brief-real-briefs`. Plan
`docs/superpowers/plans/2026-09-01-check-brief-real-briefs.md`, spec
`docs/bug-fix/2026-09-01-check-brief-rejects-real-briefs.md`.

## Baseline, before any change

`python3 plugins/superb/skills/craft/check-brief.py /home/wp3/IntellijProjects/faz-me-o-irs`

```
PASS structure
PASS nothing-open
FAIL traceability — legal_operating_model resolves to nothing
FAIL concreteness — no acceptance sentence: Verified email/password and Google authentication,
rc=1
```

Reproduces the spec's reported symptom byte for byte. Suite was 19 tests, all green
— which is the point: the suite was green while the gate rejected every real brief.

## Task 1 — `8f78634` — the fixture in the template's idiom

Created `plugins/superb/skills/craft/tests/fixtures/template_brief.md` (53 lines),
written fresh from the template's *shapes* only. No content from the user's brief
was copied.

Wired `TEMPLATE_BRIEF` and `TemplateShapedBriefTest` into `test_check_brief.py`.

Ran it. **Failed as the plan predicted**, on two predicates at once:

```
PASS structure
PASS nothing-open
SKIP traceability — no round files; hand-written brief
FAIL traceability — a decision is sourced from 'Founder request and concept', not the user
FAIL concreteness — no acceptance sentence: Verified email and password authentication, recove
```

## Task 2 — `08fe7c5` — traceability checks provenance, not echoed ids

Replaced `predicate_traceability` with the plan's body. The template-idiom fixture's
traceability failure went away; concreteness still failed. That part matched.

### Deviation 1 — four pre-existing tests the plan did not enumerate

The rewrite broke four tests the plan says nothing about:

| Test | Why it broke |
| ---- | ------------ |
| `test_complete_brief_passes` | `COMPLETE` recorded Confirmed Decisions as a **markdown table**. `SKILL.md:1246` writes `### DEC-014 — Title` with `**Source:**`; no table appears anywhere in the template. |
| `test_fenced_code_is_not_parsed_as_content` | Same `COMPLETE`. |
| `test_required_decision_sourced_from_recommendation_fails` | Asserted spec defect 3 — `**Source:**` must contain the substring `user`. |
| `test_uppercase_importance_is_actually_checked` | Asserted spec defect 1 — the echoed-question-id rule this task deletes. |

All four are the **same defect class the spec names**: fixtures written to match
the script rather than the skill. Actions taken:

- `COMPLETE`'s decision table rewritten into the template's `### DEC-001 — Title` /
  `**Decision:** / **Source:** / **Status:**` form.
- `test_required_decision_sourced_from_recommendation_fails` replaced with three
  tests of the rule that survives: `test_decision_without_a_source_fails`,
  `test_decision_with_an_empty_source_fails`,
  `test_confirmed_decisions_without_dec_entries_fails`.
- `test_uppercase_importance_is_actually_checked` and
  `test_q1_does_not_collide_with_q10` deleted — both bound the round-file id-echo
  arm that this task removes. (The latter used `assertNotIn`, so it was passing
  vacuously and would have gone unnoticed.)

Nothing was weakened: mutation coverage of the new predicate is strictly larger
than the coverage of the old one that was removed.

### Deviation 2 — a dead branch in the plan's own predicate

The plan's `src = re.search(r"\*\*Source:\*\*\s*(.+)", block)` uses `\s*`, which
crosses the newline. On

```
**Source:**
**Status:** Confirmed
```

it captures `**Status:** Confirmed` and reports the Source as populated, so the
plan's `if not src or not src.group(1).strip()` branch was unreachable. Changed to
`[ \t]*(.*)` — same-line only — which makes the branch live.
`test_decision_with_an_empty_source_fails` is the test that found it.

Also dropped the now-unused `import json`.

## Task 3 — `a6f60c2` — concreteness measures substance

Replaced `predicate_concreteness` with the plan's body verbatim. The
template-idiom fixture passed.

### Deviation 3 — four more collateral tests

Three were wording-only (they still fail, with a message that no longer invents
an "acceptance sentence"), renamed to what they now bind:

- `test_feature_without_acceptance_sentence_fails` → `test_feature_too_thin_to_act_on_fails`
- `test_url_colon_is_not_an_acceptance_sentence` → `test_a_bare_url_is_not_a_feature`
- `test_core_features_with_no_bullets_fails` — assertion updated to `lists nothing`

The fourth, `test_empty_technical_axis_fails` (`- Database:` must fail), asserted
spec **defect 4** itself — a `:` with content after it in every Technical
Preferences line. It was **deleted**, not rescued, and here is the reasoning,
because this is the one place where a word-count floor would have looked like a
harmless save:

> `- Database: Postgres.` is a legitimate, fully concrete two-word preference.
> `- Database:` is one word. No word floor separates them. The only thing that
> distinguishes an empty label from a terse real one is the label grammar —
> which is precisely the rule `SKILL.md` never specifies and the spec names
> fabricated. So the check cannot detect this case without reinstating defect 4.
> The section is still required non-empty by `predicate_structure`.

## Task 4 — `6623e85` — the assumption guard reads the two-line form

Wrote `test_a_high_impact_unconfirmed_assumption_is_caught_in_template_form`
first and ran it: **failed with `0 != 1`**, exactly as the plan predicted — the
guard did not see the two-line form. Added the per-`### ASSUMPTION-NNN` block scan
alongside the existing single-line scan (both kept). Suite went green, 20 tests.

## Task 4 Step 5 — the real gate

`python3 plugins/superb/skills/craft/check-brief.py /home/wp3/IntellijProjects/faz-me-o-irs`

```
PASS structure
FAIL nothing-open — ASSUMPTION-002 is high impact and unconfirmed
PASS traceability (29 decisions, each sourced)
PASS concreteness
rc=1
```

**The plan expected exit 0. It is not exit 0 — and the plan's expectation
contradicted its own spec.** Spec defect 5 states in terms: *"`ASSUMPTION-002` is
exactly that case and passes. The reported `PASS nothing-open` is a false pass."*
Fixing the guard necessarily makes that assumption fire. Step 5 could never have
been exit 0 and Step 3 both.

The three predicates the bug was actually about — structure, traceability,
concreteness — **all pass against the real brief**, from `FAIL traceability` and
`FAIL concreteness` at baseline. The reported bug is fixed.

The brief's text is unambiguous:

```
### ASSUMPTION-002 — Initial support boundary
**Impact if incorrect:** High
**Status:** Unconfirmed
```

Nothing was weakened to make this green.

### Open finding — the guard's *verdict* is not template-supported

The matching is now faithful. Whether a high-impact unconfirmed assumption should
*block* `VISION CLEAR` is a policy `SKILL.md` does not state, and the evidence
leans against it:

- `SKILL.md:1216-1226`, the **only** worked example of an assumption record, is
  verbatim `**Impact if incorrect:** High` + `**Status:** Unconfirmed`, presented
  as correct, expected output — not as an error condition.
- `SKILL.md:1228` says *"Never silently convert an assumption into a confirmed
  requirement"* — instructing the brief to leave exactly this state standing.
- The Completion criteria (`SKILL.md:1508-1523`) require the brief to record
  *"what assumptions remain"*. Visible, not resolved.

So the guard may be a fourth fabricated rule of the same family, and this fix has
made it effective for the first time. It predates the plan and the spec's author
judged it correct, so I did not touch it — but it needs a decision, because with
it in place `VISION CLEAR` is still unreachable for this brief and the spec's
*Consequence* section is only partly discharged.

### Adjacent hole, not fixed

`ASSUMPTION-001` in the same brief is `**Impact if incorrect:** Critical` +
`**Status:** Unconfirmed`. The plan's regex matches `High\b` only, so a
*more* severe assumption slips through a guard that catches a less severe one.
`SKILL.md` specifies no impact vocabulary at all (the string `Impact if incorrect`
occurs once, at line 1224, with the value `High`). Left as the plan wrote it; it
does not change today's verdict, since `ASSUMPTION-002` already fails the gate.

## Gates

| Gate | Result |
| ---- | ------ |
| `./tools/check-plugin.sh` | PASS |
| `./tools/check-plugin-mutants.sh` | PASS — killed=35, survived=0 |
| `python3 -m unittest discover -s plugins/superb/skills/craft/tests` | OK — 20 tests |

## Read-only compliance

`/home/wp3/IntellijProjects/faz-me-o-irs` was only ever read. `CRAFT.md` is
unchanged: mtime `Aug 30 01:22`, size `26483`, md5
`0900b9079e77368a0593a75f158780ab`, identical before and after. No content from
that brief was copied into any fixture.
