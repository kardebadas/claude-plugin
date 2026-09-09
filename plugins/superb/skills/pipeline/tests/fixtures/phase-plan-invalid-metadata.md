# Invalid Example Phase

<!-- pipeline-v2-phase: id=99; deps=none; review_gate=final-only; review_reason=Mechanical verification is sufficient before the master gate. -->
<!-- pipeline-v2-phase-suite: id=99; commands=["python3.11 -m unittest example -v"] -->

### PX-01 — Invalid task
<!-- pipeline-v2-task: id=PX-01; deps=none; kind=source; batch=state-core; order=1; write_scope=file:src/*.py; outputs=none -->
<!-- pipeline-v2-task-suite: id=PX-01; commands=["python3.11 -m unittest example.SourceTest -v"] -->

Glob scopes are ambiguous and forbidden.
