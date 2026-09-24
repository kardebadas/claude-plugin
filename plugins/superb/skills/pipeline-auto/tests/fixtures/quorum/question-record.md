<!-- pipeline-auto/v1 -->

# Question record — the input to open_quorum and to build_payload
#
# One question, published by the raising worker. `Raiser`, `Candidate answers`
# and `Recommendation` are here SO THAT `build_payload` can be proved to drop
# them: they are recorded for audit and are structurally unreachable from the
# payload builder, which names every key it emits.
#
# Every reading root is REPO-ROOT-RELATIVE. `effective_rung` resolves a brain's
# citations against the recorded repository root and refuses one that escapes
# it, so a root that is absolute or that climbs out with `..` sends a brain
# somewhere its citations can only be refused — and a refused citation demotes
# silently.
#
# There is deliberately NO `decisions-effective` root here. Where this run's
# decisions projection lives is a fact about the run, not a claim the raiser
# makes; `_shared_payload` derives it from the run directory and the recorded
# repository root, so there is exactly one spelling of it.

## Q-ee1433c675a3 — Session storage

- **Question:** Which storage engine backs the session table?
- **Axis:** storage-engine
- **Phase:** P04
- **Blocks:** T04
- **Raiser:** worker-7
- **Options supplied:** yes
- **Options:** postgres, sqlite
- **Candidate answers:** postgres because we already run it
- **Recommendation:** postgres
- **Reading roots:** spec=docs/superpowers/specs/design.md, intent-brief=docs/superpowers/runs/R/intent-brief.md, repo=., tests=tests, phase-plan=docs/superpowers/plans/phase-04.md
- **Owners:** brain-a, brain-b, brain-c
