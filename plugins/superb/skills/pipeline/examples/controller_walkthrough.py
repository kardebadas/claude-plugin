#!/usr/bin/env python3
"""Runnable one-phase Pipeline v2 controller walkthrough.

The target project is deliberately outside the installed skill directory. This
example creates a disposable artifact-only run, imports the helper by installed
path, and drives it through task evidence, phase verification, master review,
and durable final completion.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def load_helper(skill_dir: Path):
    helper_path = skill_dir.resolve() / "scripts/pipeline_state.py"
    spec = importlib.util.spec_from_file_location("installed_pipeline_state", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Pipeline v2 helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(project: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=project, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def verification(
    project: Path, *, name: str, purpose: str, subject: str, attempt: str,
    head: str, commands: tuple[str, ...], inputs: str,
) -> str:
    path = project / "docs/superpowers/runs/walkthrough/agent-output" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!-- pipeline-verification-evidence/v2 -->\n"
        "| Field | Value |\n| --- | --- |\n"
        f"| purpose | {purpose} |\n| run_id | walkthrough |\n"
        f"| subject | {subject} |\n| attempt | {attempt} |\n"
        f"| code_state | {head} |\n| outcome | PASS |\n"
        f"| commands | {json.dumps(commands, separators=(',', ':'))} |\n"
        "| environment | local-walkthrough |\n"
        f"| inputs | {inputs} |\n",
        encoding="utf-8",
    )
    relative = path.relative_to(project).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{relative}#sha256={digest}@{head}"


def review_report(
    project: Path, *, assignment: str, base: str, head: str,
) -> Path:
    path = project / "docs/superpowers/runs/walkthrough/agent-output" / f"{assignment}.md"
    path.write_text(
        "<!-- pipeline-review-report/v2 -->\n"
        "| Field | Value |\n| --- | --- |\n"
        "| gate | master |\n"
        f"| assignment | {assignment} |\n| base | {base} |\n| head | {head} |\n"
        "| findings | - |\n| outcomes | {} |\n",
        encoding="utf-8",
    )
    return path


def run(skill_dir: Path, project: Path) -> dict[str, str]:
    state = load_helper(skill_dir)
    project.mkdir(parents=True)
    git(project, "init", "-q")
    git(project, "config", "user.email", "pipeline@example.invalid")
    git(project, "config", "user.name", "Pipeline Walkthrough")
    (project / "README.md").write_text("walkthrough\n", encoding="utf-8")
    git(project, "add", "README.md")
    git(project, "commit", "-qm", "walkthrough base")
    head = git(project, "rev-parse", "HEAD")
    git(project, "branch", "feature/walkthrough")

    docs = project / "docs/superpowers"
    phase = docs / "plans/walkthrough/phase-01.md"
    phase.parent.mkdir(parents=True)
    phase.write_text(
        "# Walkthrough phase\n\n"
        "<!-- pipeline-v2-phase: id=01; deps=none; review_gate=final-only; "
        "review_reason=Mechanical verification only. -->\n"
        "<!-- pipeline-v2-phase-suite: id=01; commands=[\"phase-check\"] -->\n\n"
        "### W-01 — Produce evidence\n"
        "<!-- pipeline-v2-task: id=W-01; deps=none; kind=artifact; batch=walkthrough; "
        "order=1; write_scope=file:evidence/output.md; outputs=evidence/output.md -->\n",
        encoding="utf-8",
    )
    master = docs / "plans/walkthrough-master-plan.md"
    master.write_text(f"# Master\n\n- **Detailed plan:** `{phase}`\n", encoding="utf-8")
    spec = docs / "specs/walkthrough-design.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Approved walkthrough design\n", encoding="utf-8")
    run_dir = docs / "runs/walkthrough"
    run_dir.mkdir(parents=True)
    decisions = run_dir / "decisions.md"
    findings = run_dir / "findings.md"
    decisions.write_text("# Decisions\n", encoding="utf-8")
    findings.write_text(
        "<!-- pipeline-findings/v2 -->\n"
        "| ID | Gate | Severity | Status | Disposition | Evidence | Fix Commit | Re-review |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n",
        encoding="utf-8",
    )
    approved = (decisions.resolve(), findings.resolve())
    state.initialize_run(
        run_dir, run_id="walkthrough", base_commit=head,
        target_branch="feature/walkthrough", worker_limit=2,
        artifacts={
            "spec": spec.relative_to(project).as_posix(),
            "master_plan": master.relative_to(project).as_posix(),
            "phase_plans": phase.relative_to(project).as_posix(),
            "decisions": decisions.relative_to(project).as_posix(),
            "findings": findings.relative_to(project).as_posix(),
        },
        approved_existing=approved,
    )

    output = project / "evidence/output.md"
    output.parent.mkdir()
    output.write_text("artifact validated\n", encoding="utf-8")
    output_identity = (
        f"evidence/output.md#sha256={hashlib.sha256(output.read_bytes()).hexdigest()}"
    )
    task_evidence = verification(
        project, name="task.md", purpose="task-test", subject="task/W-01",
        attempt="attempt-1", head=head, commands=("artifact-validation",),
        inputs=json.dumps((output_identity,), separators=(",", ":")),
    )
    with state.bind_runtime_capacity_provider(run_dir, lambda _run, _tracker: 2):
        state.start_task(run_dir, task_id="W-01", owner="worker-a", attempt="attempt-1")
    result_path = run_dir / "agent-output/worker-a-result.md"
    state.publish_worker_result(
        result_path,
        state.WorkerResult(
            "walkthrough", "W-01", "attempt-1", "worker-a", "artifact", "DONE",
            "-", (), ("evidence/output.md",), "artifact-validation", (task_evidence,),
            "-", "-", "-", (state.Checkpoint("tested", "complete", task_evidence),),
        ),
    )
    state.import_worker_result(
        run_dir, result_path=result_path, phase_plan=phase, repo_dir=project,
    )

    phase_evidence = verification(
        project, name="phase.md", purpose="phase", subject="phase/01", attempt="N/A",
        head=head, commands=("phase-check",), inputs="walkthrough-artifact",
    )
    state.record_phase_verification(
        run_dir, phase_id="01", head=head, commands=("phase-check",),
        evidence=(phase_evidence,),
    )
    with state.bind_runtime_capacity_provider(run_dir, lambda _run, _tracker: 2):
        state.open_review_gate(
            run_dir, gate_id="master", base=head, head=head,
            reviewer_assignments=("reviewer-a", "reviewer-b"), capacity=2,
        )
    reports = tuple(
        review_report(project, assignment=assignment, base=head, head=head)
        for assignment in ("reviewer-a", "reviewer-b")
    )
    state.evaluate_and_close_review_gate(
        run_dir, gate_id="master", findings_path=findings,
        report_paths=reports, verification=(phase_evidence,), rereview_paths=(),
    )
    final_evidence = verification(
        project, name="final.md", purpose="final", subject="project", attempt="N/A",
        head=head, commands=("final-check",), inputs="accepted-master-head",
    )
    state.record_final_verification(
        run_dir, head=head, commands=("final-check",), evidence=(final_evidence,),
        repo_dir=project,
    )
    tracker = state.validate_run(run_dir)
    return {
        "next_action": state.derive_next_action(run_dir, tracker),
        "current_phase": dict(tracker.current_fields)["phase"],
        "master_gate": next(gate.state for gate in tracker.gates if gate.id == "master"),
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: controller_walkthrough.py <installed-skill-dir> <empty-project-dir>")
    print(json.dumps(run(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True))
