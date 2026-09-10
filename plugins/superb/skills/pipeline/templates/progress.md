<!-- pipeline-run/v2 -->
# Pipeline v2 — Progress Tracker

## Run
| Field | Value |
| --- | --- |
| run_id | <run_id> |
| tracker_format | 2 |
| schema_adoption | none |
| base_commit | <base_commit> |
| target_branch | <target_branch> |
| worker_limit | <worker_limit> |
| filesystem_class | <filesystem_class> |
| filesystem_type | <filesystem_type> |
| filesystem_fingerprint | <filesystem_fingerprint> |
| filesystem_ack | <filesystem_ack> |
| spec | <spec_path> |
| master_plan | <master_plan_path> |
| phase_plans | <phase_plan_paths> |
| decisions | <decisions_path> |
| findings | <findings_path> |
| revision | 0 |
| last_transition | initialized |

## Current State
| Field | Value |
| --- | --- |
| phase | <phase_id> |
| batch | <batch_id> |
| next_action | <next_action> |

## Tasks
| ID | Kind | State | Owner | Attempt | Result | Checkpoints | Source Ref | Commits | Artifacts | Integration | Verification | Question |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <task_id> | source | [ ] | - | - | - | - | - | - | - | - | - | - |

## Phases
| ID | State | Verification | Review Gate | Review Reason | Gate |
| --- | --- | --- | --- | --- | --- |
| <phase_id> | [ ] | - | <review_gate> | <review_reason> | <gate_id> |

## Gates
| ID | Type | Phase | State | Base | Head | Assignments | Reports | Verification | Findings | Questions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <gate_id> | phase | <phase_id> | pending | - | - | - | - | - | <findings_path> | - |

## Remediation
| Gate | Round | State | Fixers | Released Fixers | Findings | Fix Plan | Commits | Verification | Re-review |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <gate_id> | 1 | pending | - | - | - | - | - | - | - |
