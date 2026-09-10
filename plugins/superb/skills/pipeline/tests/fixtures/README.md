# Pipeline v2 state fixtures

These files are immutable input evidence for the state-contract tests. Valid
fixtures must round-trip through the canonical renderer. Rejection tests must
compare the fixture bytes before and after an attempted parse or transition;
an invalid input must never be rewritten into a guessed state.

Legacy fixtures added by later tasks remain rejection evidence. They are not
migration inputs and must not be edited by resume or initialization tests.

`pre-adoption-v2-progress.md` is the frozen exact first pre-release v2 format
used only by the D-017 controller adoption tests. Ordinary validation and
resume must reject it; it is not a legacy-v1 or general migration fixture.

P1-06 result fixtures always carry the controller-assigned `owner`. The stale
and conflicting fixtures are syntactically valid evidence whose assignment
identity must be rejected against an authoritative active task; their names do
not make them a second source of state.
