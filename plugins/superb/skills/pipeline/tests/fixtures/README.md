# Pipeline v2 state fixtures

These files are immutable input evidence for the state-contract tests. Valid
fixtures must round-trip through the canonical renderer. Rejection tests must
compare the fixture bytes before and after an attempted parse or transition;
an invalid input must never be rewritten into a guessed state.

Legacy fixtures added by later tasks remain rejection evidence. They are not
migration inputs and must not be edited by resume or initialization tests.
