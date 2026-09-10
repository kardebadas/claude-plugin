<!-- pipeline-run/v2 -->
# Pipeline v2 — Progress Tracker

## Run
| Field | Value |
| --- | --- |
| run_id | malformed |
| base_commit | 8348959d1b201a873c68512642a0eb8e5754eaa8 |
| target_branch | feat/example |
| worker_limit | 3 |
| spec | docs/spec.md |
| master_plan | docs/master.md |
| phase_plans | docs/phase.md |
| decisions | docs/decisions.md |
| findings | docs/findings.md |
| revision | 0 |
| last_transition | initialized |
| invented | forbidden |

## Current State
| Field | Value |
| --- | --- |
| phase | 01 |
| batch | state-core |
| next_action | P1-01 |

## Tasks
| ID | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1-01 | source | [ ] | - | - | - | - | - | - | - | - | - | - |

## Phases
| ID | State | Verification | Review Gate | Review Reason | Gate |
| --- | --- | --- | --- | --- | --- |
| 01 | [ ] | - | required | Required reason. | phase-01 |

## Gates
| ID | Type | Phase | State | Base | Head | Assignments | Reports | Verification | Findings | Questions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| phase-01 | phase | 01 | pending | - | - | requirements | - | - | docs/findings.md | - |

## Remediation
| Gate | Round | State | Findings | Fix Plan | Commits | Verification | Re-review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| phase-01 | 1 | pending | - | - | - | - | - |
