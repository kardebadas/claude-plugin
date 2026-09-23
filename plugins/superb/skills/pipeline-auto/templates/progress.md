<!-- pipeline-auto/v1 -->
# Pipeline Auto — Progress Tracker

## Run
| Field | Value |
| --- | --- |
| run_id | <run_id> |
| schema | pipeline-auto/v1 |
| base_commit | <base_commit> |
| target_branch | <target_branch> |
| repo_root | <repo_root> |
| worker_limit | <worker_limit> |
| agent_dispatch_count | 0 |
| dispatch_projection | - |
| dispatch_soft_ceiling | - |
| dispatch_hard_ceiling | - |
| spec | - |
| master_plan | - |
| phase_plans | - |
| decisions | docs/superpowers/runs/<run_id>/decisions.md |
| findings | docs/superpowers/runs/<run_id>/findings.md |
| completeness_proposals | docs/superpowers/runs/<run_id>/completeness-proposals.md |
| revision | 0 |
| last_transition | initialized |

## Stage
| Stage | Stage State | Next Action |
| --- | --- | --- |
| 01 | active | dispatch-intent-readers |
| 02 | pending | - |
| 03 | pending | - |
| 04 | pending | - |
| 05 | pending | - |
| 06 | pending | - |
| 07 | pending | - |
| 08 | pending | - |
| 09 | pending | - |
| 10 | pending | - |
| 11 | pending | - |
| 12 | pending | - |

## Intent
| ID | Kind | State | Owner | Result | Conflicts |
| --- | --- | --- | --- | --- | --- |

## Questions
| ID | Origin | Slot | State | Decision |
| --- | --- | --- | --- | --- |

## Quorum
| QID | Axis | Phase | State | Owners | Payload Digest | Context Digest | Responses | Depth | Rung | Outcome | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Escalations
| ID | QID | Blast | State | Batch | Resolution |
| --- | --- | --- | --- | --- | --- |

## Tasks
| ID | Phase | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question | Decisions | Provisional |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Task Review
| Task | Round | Intensity | State | Reviewer | Package | Report | Critical | Important | Minor | Adversarial | Adversarial Verdict | Open | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Fix Rounds
| Scope | Round | State | Fixer | Findings | Commits | Verification | Re-review | Remaining |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Phases
| ID | State | Verification | Review Class | Class Source | Ratchet | Gate |
| --- | --- | --- | --- | --- | --- | --- |

## Gates
| ID | Type | Phase | State | Base | Head | Assignments | Reports | Verification | Findings |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
