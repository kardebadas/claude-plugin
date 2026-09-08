# Example Phase

<!-- pipeline-v2-phase: id=99; deps=none; review_gate=final-only; review_reason=Mechanical verification is sufficient before the master gate. -->

### PX-01 — Source task
<!-- pipeline-v2-task: id=PX-01; deps=none; kind=source; batch=state-core; order=1; write_scope=file:src/state.py,tree:tests/fixtures; outputs=none -->

Source task body.

### PX-02 — Artifact task
<!-- pipeline-v2-task: id=PX-02; deps=PX-01; kind=artifact; batch=evidence; order=1; write_scope=tree:docs/evidence; outputs=docs/evidence/result.md -->

Artifact task body.
