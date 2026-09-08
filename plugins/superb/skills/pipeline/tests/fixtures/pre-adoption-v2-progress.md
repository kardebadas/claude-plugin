<!-- pipeline-run/v2 -->
# Pipeline v2 — Progress Tracker

## Run
| Field | Value |
| --- | --- |
| run_id | 2026-09-08-pipeline-rebuild-v2 |
| base_commit | 8348959d1b201a873c68512642a0eb8e5754eaa8 |
| target_branch | feat/example |
| worker_limit | 3 |
| spec | docs/superpowers/specs/example-design.md |
| master_plan | docs/superpowers/plans/example-master-plan.md |
| phase_plans | docs/superpowers/plans/example/phase-01.md,docs/superpowers/plans/example/phase-02.md |
| decisions | docs/superpowers/runs/2026-09-08-example/decisions.md |
| findings | docs/superpowers/runs/2026-09-08-example/findings.md |
| revision | 7 |
| last_transition | transition-007 |

## Current State
| Field | Value |
| --- | --- |
| phase | 02 |
| batch | P2-pressure |
| next_action | verify-phase-02 |

## Tasks
| ID | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1-01 | source | [x] | worker-1 | attempt-001 | agent-output/p1-01.md | red,green | refs/heads/feat/example | 0123456789abcdef0123456789abcdef01234567 | - | fedcba9876543210fedcba9876543210fedcba98 | tests/p1-01.txt | - |
| P2-T01 | artifact | [x] | worker-2 | attempt-002 | agent-output/p2-t01.md | control,green | - | - | docs/evidence.md | N/A | artifact-check.txt | - |

## Phases
| ID | State | Verification | Review Gate | Review Reason | Gate |
| --- | --- | --- | --- | --- | --- |
| 01 | [x] | phase-01-tests.txt | required | State corruption would invalidate downstream work. | phase-01 |
| 02 | [~] | - | required | Instruction ambiguity could authorize unsafe work. | phase-02 |

## Gates
| ID | Type | Phase | State | Base | Head | Assignments | Reports | Verification | Findings | Questions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| phase-01 | phase | 01 | accepted | 8348959d1b201a873c68512642a0eb8e5754eaa8 | fedcba9876543210fedcba9876543210fedcba98 | requirements | agent-output/phase-01-review.md | phase-01-tests.txt | findings.md | - |
| master | master | - | pending | 8348959d1b201a873c68512642a0eb8e5754eaa8 | - | requirements,reliability | - | - | findings.md | - |

## Remediation
| Gate | Round | State | Findings | Fix Plan | Commits | Verification | Re-review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| phase-01 | 1 | complete | F-001 | fix-plan-phase-01-r1.md | abcdef0123456789abcdef0123456789abcdef01 | phase-01-r1-tests.txt | agent-output/phase-01-r1-review.md |
