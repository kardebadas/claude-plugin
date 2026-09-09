<!-- pipeline-worker-result/v2 -->
# Pipeline v2 — Worker Result

## Result
| Field | Value |
| --- | --- |
| run_id | <run_id> |
| task_id | <task_id> |
| attempt | <attempt_id> |
| owner | <controller_assigned_owner> |
| kind | <source_or_artifact> |
| status | <worker_status> |
| source_ref | <source_ref_or_dash> |
| commits | <commits_or_dash> |
| artifacts | <artifacts_or_dash> |
| tests | <test_commands> |
| evidence | <digest_bound_typed_task_evidence_or_artifact_validation_paths> |
| concerns | <concerns_or_dash> |
| question | <question_or_dash> |
| blocking_reason | <blocking_reason_or_dash> |

## Checkpoints
| ID | Status | Evidence |
| --- | --- | --- |
| <checkpoint_id> | <complete_in_progress_or_blocked> | <evidence_path> |
