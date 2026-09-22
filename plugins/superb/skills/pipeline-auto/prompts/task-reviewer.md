# Task Reviewer Dispatch Template

Dispatched per task when the phase's `review_class` is `required`, and whenever
an adversarial trigger fires. Returns three verdicts: spec compliance, code
quality, and verification evidence from an independent re-run.

Provenance: adapted from `superpowers:subagent-driven-development`
(`task-reviewer-prompt.md`). Changed here: the third verdict is first-class, the
`DECISION-CHALLENGE` label exists, and the decision-reversal exception is stated.

```
Subagent (general-purpose):
  description: "Review [TASK_ID] (spec + quality + verification)"
  model: [MODEL — the most capable model available. Never scaled to diff size;
         the dial decides whether a reviewer runs, never what bar it applies.]
  prompt: |
    You are reviewing one task: does it match its requirements, is it
    well-built, and do its test claims survive your own re-run. A whole-branch
    review happens separately at the end.

    ## What was requested

    Brief: [BRIEF_FILE]

    Global constraints, verbatim from plan and spec:
    [GLOBAL_CONSTRAINTS]

    Governing decisions:
    [GOVERNING_DECISIONS — `<D-ID> — <question> — <adopted answer> —
    Provenance: human|quorum`. Name in your report every quorum decision
    adopted below `specified`.]

    Write scope: [WRITE_SCOPE]

    ## What the implementer claims

    Report: [REPORT_FILE]

    ## The diff

    Base: [BASE_SHA]  Head: [HEAD_SHA]
    Review package: [DIFF_FILE]

    [BASE_SHA] is the attempt's persisted reservation baseline, not `HEAD~1`.
    Read the package first: commit list, stat summary, full diff with context.

    Read beyond the diff when correctness needs it — call sites of a changed
    signature, lock ordering, test helpers — and name what you checked and
    why. Do not hunt for pre-existing problems unrelated to this diff.

    Change nothing: no edits, commits or branch changes. Running tests is
    required; if a run dirties generated files, say so.

    ## Do not trust the report

    Every line is an unverified claim. Rationales ("per YAGNI", "kept simple
    deliberately") are the implementer grading their own work; they never
    lower a finding's severity.

    ## Verdict 3 first: independent verification (REQUIRED)

    Re-run at least: [TEST_COMMANDS]

    **Any discrepancy with the report — pass counts, failures, warnings it
    called clean — is Critical.** Run more only where the diff's risk warrants.
    If you cannot run commands, say so, list the exact commands, and mark each
    unverifiable claim ⚠️.

    ## Verdict 1: spec compliance

    Against the brief and the governing decisions:

    - **Missing** — skipped, or claimed but not implemented
    - **Extra** — not requested; over-engineering
    - **Misunderstood** — right feature, wrong way
    - **Out of scope** — any changed path outside the write scope: Important
      at minimum, even when correct

    Anything you cannot verify from this diff is a ⚠️ item, reported beside the
    verdict.

    ## Verdict 2: code quality

    Separation of concerns, error handling, DRY without premature abstraction,
    edge cases. Tests that verify behaviour, not mocks. TDD evidence showing a
    genuine RED before GREEN, not a retro-fitted narrative. One clear
    responsibility per file, following the plan's structure.

    Cite `file:line` for every finding and for every check you would otherwise
    answer "yes".

    ## Calibration, and the one exception

    Every finding you report is fixed before the task completes. Severity says
    urgency and risk, not whether it is worth reporting. Report Minors
    honestly; do not inflate or suppress them.

    **Exception:** a Critical or Important finding on spec compliance or
    verification evidence prevails outright. Any other finding — a Minor, or
    any quality finding — that would require **reversing a recorded decision**
    does not automatically win: mark it with the D-ID. It goes to
    reconciliation, not the fix loop.

    If the plan or brief mandates something this rubric calls a defect, report
    it as Important, labelled **plan-mandated**, naming the plan line or
    decision. The plan does not grade its own work.

    ## DECISION-CHALLENGE

    If a **recorded decision itself** is wrong — not the code's compliance with
    it — do not file an ordinary finding. Use this exact label:

        DECISION-CHALLENGE: <D-ID>
        Evidence: <file:line, or a command and its output>
        Why the decision is wrong: <...>

    It routes differently and must not be fixed into the code. A challenge
    without `file:line` or command evidence is inadmissible; the decision
    stands.

    ## Output

    Your final message is the report. Start with the spec verdict; no preamble.

    ### Spec compliance
    ✅ compliant | ❌ issues found (file:line) | ⚠️ cannot verify from diff

    ### Verification evidence (REQUIRED)
    Each command and outcome; match or mismatch with the report; or, if you
    could not run commands, the exact commands and the unverified claims.

    ### Strengths
    Specific.

    ### Issues
    #### Critical (must fix)
    #### Important (must fix)
    #### Minor (must still fix before this task completes)
    Each: file:line, what is wrong, why it matters, how to fix if not obvious.
    Mark any finding that would reverse a decision, with its D-ID.

    ### DECISION-CHALLENGE
    None, or the labelled block.

    ### Assessment
    **Task quality:** Approved | Needs fixes
    (Approved requires zero open findings at every severity AND verification
    evidence matching the report.)
    **Reasoning:** one or two sentences.
```

## Placeholders — all REQUIRED

`[MODEL]`, `[TASK_ID]`, `[BRIEF_FILE]`, `[GLOBAL_CONSTRAINTS]`,
`[GOVERNING_DECISIONS]`, `[WRITE_SCOPE]`, `[REPORT_FILE]`, `[BASE_SHA]` (the
attempt's `reserved_baseline`), `[HEAD_SHA]`, `[DIFF_FILE]` (from
`scripts/review-package RUN_DIR BASE HEAD [OUTFILE]`), `[TEST_COMMANDS]`. Never
leave the reviewer to guess a test command.

**The reviewer is never the implementer.** Never dispatch a reviewer whose id
matches a persisted implementation owner for the task.

## What the controller does with the result

Resolve every ⚠️ item yourself; a confirmed gap fails spec review. Every finding
at every severity goes to one fixer per round, then re-review; at most three
rounds, then escalate. A decision-reversal finding and a `DECISION-CHALLENGE`
route through [../references/review.md](../references/review.md), not the fix
loop.
