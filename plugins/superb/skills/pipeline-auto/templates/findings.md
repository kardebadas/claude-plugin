<!-- pipeline-auto-findings/v1 -->
| ID | Scope | Severity | Status | Disposition | Evidence | Adjudication | Fix Round | Re-review |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F-1 | T04 | critical | open | - | tests/test_session.py:41 and the command that fails there | - | 1 | pending |
| F-2 | T04 | important | closed | fixed | db/session.py:12, verified by the task's own test command | disputed:F-2-refutation confirmed | 1 | accepted |
| F-3 | T04 | minor | closed | refuted | db/pool.py:8, the adjudicator's own citation | disputed:F-3-refutation refuted | 1 | accepted |

<!--
One row per finding, and a row is never deleted. A finding that stops being
open is CLOSED with a disposition, because a ledger that loses its refuted
findings cannot show that anything was ever contested.

`Severity` is one of

    critical | important | minor

and the bar is ZERO OPEN FINDINGS AT EVERY SEVERITY, so severity orders the
work and never excuses it. There is no fourth word: a fourth word is where "it
mostly held" would go, and a deferral category is the one thing this project
does not have.

`Adjudication` records a FIXER DISPUTE and its outcome. It reads `-` when the
finding is undisputed; otherwise `disputed:<refutation-ref>` followed by the
adjudicator's verdict:

    confirmed   the finding stands and the fixer fixes it
    refuted     the finding closes, on the adjudicator's own citation
    plausible   genuinely irreducible -- and only then does it become a quorum
                question, framed neutrally rather than loaded toward fixing

A dispute is admissible only with a refutation citing `file:line`, or a command
and its output. A bare disagreement is inadmissible and the finding stands.

ONE adjudicator settles it, not three. "Can line 41 be null" is a FACT, settled
by reading code or running an experiment, not by a confidence-weighted vote --
three models agreeing that line 41 cannot be null is far weaker evidence than
one model running the test. Routing facts to the quorum is a category error,
and it is the mechanism by which a quorum degrades into a general-purpose "ask
three models when unsure" reflex, which is itself a drift vector.

If no admissible verdict returns at all, the finding STANDS and is fixed: a
false-positive finding costs one wasted fix, a wrongly-refuted finding ships a
defect, and those two costs are not symmetric.

AN ADJUDICATION NEVER ENTERS `decisions.md`. It is a factual question about
this finding, not a requirement decision, and filing it as a decision would let
an argument about whether code is broken masquerade as a statement about what
the user asked for. Nor may a reviewer finding reverse a decision on a styling
preference: a minor, or any quality-part finding, that would require reversing
a decision goes to reconciliation, and if the decision survives the finding is
recorded `refuted - governed by <D-ID>` and does not block completion.

`Fix Round` is the round that carried the finding; `Re-review` is the state of
the review that followed it. Neither of them excuses an open finding.
-->
