"""Drive a whole pipeline-auto run, as its controller, against a foreign repo.

Run it directly:

    python3 plugins/superb/skills/pipeline-auto/examples/controller_walkthrough.py

It builds a throwaway git repository in a temporary directory, loads the state
module from the skill's own ``scripts/`` directory (by location, the way an
installed skill is loaded, never by a checkout-relative import), and drives one
run from ``initialize_run`` to a terminal ``derive_next_action`` -- following
the controller procedure as ``SKILL.md`` and ``references/*.md`` teach it,
through the module's public writers and the git argv the module emits.

WHAT THIS PROVES. That a legitimate run can be completed by the machinery as
the skill describes it; that every path the module wrote lies inside the
temporary root it was handed (an audit hook records the module's writes, so
this is asserted, not assumed); that the module spawned no process itself; and
that every git call this controller made ran with its working directory inside
that root.

WHAT THIS DOES NOT PROVE. It is not an installation test: nothing is copied
into a plugin cache and no plugin loader runs. It runs on Linux only
(``classify_filesystem`` answers ``unknown`` elsewhere and the run would halt),
and skips with that reason on any other platform.

DEVIATION FROM THE P09 PLAN, AND WHY. The phase-09 plan says the walkthrough
"does not shell out". Task completion needs real commits, a real range proof
and a real integration merge, and the module deliberately never executes git:
it emits argv and validates the transcript the controller hands back. This
script IS the controller, so it runs (a) the argv the module emits, through
the ``run_command`` capability, and (b) the few git commands a controller runs
itself -- init, config, commit, branch, checkout, merge -- plus the task test
suites it re-runs as evidence. All of them run with ``cwd`` inside the
temporary repository, which is asserted on every call. The capability ban
binds the MODULE, not this script: ``pipeline_auto_state`` keeps its twelve
``ALLOWED_IMPORTS`` and no ``subprocess``.

Where the skill routes a stage or gate transition through a raw
``locked_tracker_update`` because no writer exists, this script does the same
and records it in ``RAW_TRANSITIONS``, naming the writer that is missing. Where
the machinery refuses something the skill says is legal, the refusal is
recorded in ``FINDINGS`` rather than routed around.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = SKILL_ROOT / "scripts" / "pipeline_auto_state.py"

RUN_ID = "2026-09-23-walkthrough"
TARGET = "feat/walkthrough"
RUN_REL = f"docs/superpowers/runs/{RUN_ID}"
SPEC_REL = "docs/superpowers/specs/walkthrough-design.md"
MASTER_REL = "docs/superpowers/plans/walkthrough-master-plan.md"
PLAN_REL = {"P1": "docs/superpowers/plans/walkthrough/phase-1.md",
            "P2": "docs/superpowers/plans/walkthrough/phase-2.md"}
BRAINS = ("brain-a", "brain-b", "brain-c")
REVIEWERS = {"A": "master-reviewer-a", "B": "master-reviewer-b"}

#: Every raw ``locked_tracker_update`` this controller needed, as
#: ``(transition_id, what it did, the writer that is missing)``.
RAW_TRANSITIONS: list = []
#: Every place the machinery and the skill disagree, or a legal step is refused.
FINDINGS: list = []
#: One line per stage passed, printed at the end.
LOG: list = []


class WalkthroughFailure(AssertionError):
    """A step the walkthrough expected to succeed did not."""


def check(condition, message: str) -> None:
    if not condition:
        raise WalkthroughFailure(message)


def finding(severity: str, title: str, detail: str) -> None:
    if any(title == seen for _, seen, _ in FINDINGS):
        return
    FINDINGS.append((severity, title, detail))
    print(f"FINDING [{severity}]: {title}")


def say(line: str) -> None:
    LOG.append(line)
    print(f"OK: {line}")


def load_module():
    """Load the state module by its location inside the skill.

    Bytecode caching is switched off first: the loader would otherwise write
    ``scripts/__pycache__`` inside the skill, outside the temporary root.
    """
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(
        "pipeline_auto_state_walkthrough", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load the state module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inside(root: Path, path) -> bool:
    target = Path(path).resolve()
    resolved = root.resolve()
    return target == resolved or resolved in target.parents


def assert_confined(root: Path, touched) -> None:
    """Every path the run touched must lie inside the root it was handed."""
    outside = sorted(str(Path(p).resolve()) for p in touched
                     if not inside(root, p))
    if outside:
        raise WalkthroughFailure(
            f"the run touched {outside}, outside the repository root it was "
            f"handed ({root.resolve()})")


# ---------------------------------------------------------------------------
# Confinement: every filesystem write the MODULE makes is recorded by an audit
# hook, gated to the calls this controller makes into the module. The
# controller's own writes (the foreign repo, the worker's files) are not the
# module's and are not counted; the git subprocesses the module asks for are
# run by the controller and are asserted separately (cwd inside the root).
# ---------------------------------------------------------------------------

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_PATH_EVENTS = {"os.mkdir", "os.rename", "os.replace", "os.remove", "os.rmdir",
                "os.link", "os.symlink", "os.truncate", "os.chmod", "os.utime",
                "os.chown", "shutil.rmtree", "shutil.copyfile", "shutil.move"}


class ModuleAudit:
    """Records what the module writes and reads while it is being called."""

    def __init__(self):
        self.depth = 0
        self.writes: set = set()
        self.reads: set = set()
        self.spawned: list = []

    def hook(self, event, args):
        if self.depth <= 0:
            return
        if event == "open":
            path, mode, flags = (tuple(args) + (None, None, None))[:3]
            if not isinstance(path, (str, bytes, os.PathLike)):
                return
            path = os.fsdecode(path)
            writing = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                       or (isinstance(flags, int) and flags & _WRITE_FLAGS))
            (self.writes if writing else self.reads).add(os.path.abspath(path))
        elif event in _PATH_EVENTS:
            for arg in args:
                if isinstance(arg, (str, bytes, os.PathLike)):
                    self.writes.add(os.path.abspath(os.fsdecode(arg)))
        elif event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
                       "os.spawn", "os.fork"):
            self.spawned.append((event, repr(args)[:200]))


AUDIT = ModuleAudit()
_HOOKED = False


class Audited:
    """A view of the module whose every callable runs under the audit."""

    def __init__(self, module):
        object.__setattr__(self, "_module", module)

    def __getattr__(self, name):
        value = getattr(self._module, name)
        if not callable(value) or isinstance(value, type):
            return value

        def call(*args, **kwargs):
            AUDIT.depth += 1
            try:
                return value(*args, **kwargs)
            finally:
                AUDIT.depth -= 1
        return call


# ---------------------------------------------------------------------------
# The controller.
# ---------------------------------------------------------------------------

def git_env() -> dict:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="walkthrough", GIT_AUTHOR_EMAIL="w@example.invalid",
               GIT_COMMITTER_NAME="walkthrough",
               GIT_COMMITTER_EMAIL="w@example.invalid",
               GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")
    return env


class Controller:
    def __init__(self, module, root: Path):
        self.raw_module = module
        self.pas = Audited(module)
        self.root = root.resolve()
        self.repo = self.root
        self.run_dir = self.repo / RUN_REL
        self.git_cwds: list = []
        self.emitted: list = []
        self.human_ids = 0

    # -- process execution, always confined to the temporary repository ----

    def _spawn(self, argv, *, strict=True) -> subprocess.CompletedProcess:
        cwd = self.repo
        check_cwd = Path(cwd).resolve()
        check(inside(self.root, check_cwd),
              f"refusing to run {argv!r} outside the temporary repository")
        for flag, value in zip(argv, argv[1:]):
            if flag == "-C":
                check(inside(self.root, value),
                      f"argv {argv!r} points git at {value}, outside the root")
        self.git_cwds.append(str(check_cwd))
        depth, AUDIT.depth = AUDIT.depth, 0     # the controller's call, not the module's
        try:
            return subprocess.run(list(argv), cwd=cwd, env=git_env(),
                                  capture_output=True, text=True, check=strict)
        finally:
            AUDIT.depth = depth

    def git(self, *args) -> str:
        return self._spawn(("git", *args)).stdout.strip()

    def run_command(self, argv) -> str:
        """The capability the module is handed: run ONE emitted argv, raw."""
        argv = tuple(argv)
        check(argv and argv[0] == "git",
              f"the module emitted a non-git argv {argv!r}")
        self.emitted.append(argv)
        return self._spawn(argv).stdout

    def raw(self, transition_id: str, what: str, missing: str, mutate) -> dict:
        """A raw transition, recorded with the writer that would replace it."""
        RAW_TRANSITIONS.append((transition_id, what, missing))
        return self.pas.locked_tracker_update(
            self.run_dir, transition_id=transition_id, mutate=mutate)

    def import_result(self, path: str) -> dict:
        """import_worker_result on the path publish_worker_result returned."""
        return self.pas.import_worker_result(
            self.run_dir, result_path=path, run_command=self.run_command)

    def tracker(self) -> dict:
        return self.pas.validate_run(self.run_dir)

    def dispatch(self, count: int, what: str) -> None:
        """execution.md: compare, then count, every agent dispatch."""
        run = self.tracker()["run"]
        current = int(run["agent_dispatch_count"])
        hard = run["dispatch_hard_ceiling"]
        check(hard == "-" or current + count <= int(hard),
              f"dispatching {what} would pass the hard ceiling {hard}")

        def mutate(tracker: dict) -> dict:
            tracker["run"]["agent_dispatch_count"] = str(current + count)
            return tracker
        self.raw(f"dispatch-{current + count}", f"count {count} dispatch(es): {what}",
                 "a dispatch-count writer (execution.md: 'counting and refusing "
                 "is yours')", mutate)

    def task(self, task_id: str) -> dict:
        return next(row for row in self.tracker()["tasks"] if row["id"] == task_id)

    # -- the foreign repository ---------------------------------------------

    def write(self, relative: str, text: str) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def build_repo(self) -> None:
        self.git("init", "-q", "-b", "main")
        self.write("app/__init__.py", "")
        self.write("app/greet.py", "def greet(name):\n    return name\n")
        self.write("tests/__init__.py", "")
        self.write("README.md", "# foreign\n")
        #: The run directory is the controller's, never a task's commit.
        self.write(".git/info/exclude", "docs/superpowers/runs/\n")
        self.git("add", "app", "tests", "README.md")
        self.git("commit", "-qm", "foreign seed")
        self.git("checkout", "-q", "-b", TARGET)
        self.base_commit = self.git("rev-parse", "HEAD")

    # -- stages 01-07 (references/planning.md) ------------------------------

    def move_stage(self, closing: str, opening: str, action: str, extra=None,
                   *, missing: str) -> dict:
        """Close one stage and open the next, in one transition."""
        def mutate(tracker: dict) -> dict:
            for row in tracker["stages"]:
                if row["stage"] == closing:
                    row.update(stage_state="complete", next_action="-")
                elif row["stage"] == opening:
                    row.update(stage_state="active", next_action=action)
            if extra is not None:
                extra(tracker)
            return tracker
        return self.raw(f"stage-{closing}-to-{opening}",
                        f"close stage {closing}, open {opening} ({action})",
                        missing, mutate)

    def set_next_action(self, stage: str, action: str, missing: str) -> dict:
        def mutate(tracker: dict) -> dict:
            for row in tracker["stages"]:
                if row["stage"] == stage:
                    row["next_action"] = action
            return tracker
        return self.raw(f"stage-{stage}-{action}", f"stage {stage} -> {action}",
                        missing, mutate)

    def initialize(self) -> None:
        self.run_dir.mkdir(parents=True)
        check(self.pas.classify_filesystem(self.run_dir) == "supported-local",
              "the temporary directory is not a supported local filesystem")
        self.pas.initialize_run(
            self.run_dir, run_id=RUN_ID, base_commit=self.base_commit,
            target_branch=TARGET, worker_limit=6, repo_root=str(self.repo))
        tracker = self.tracker()
        recorded = Path(self.pas.repo_root(tracker)).resolve()
        check(recorded == self.repo,
              f"recorded repo_root {recorded} is not the root handed in")
        check(self.pas.derive_next_action(tracker) == "dispatch-intent-readers",
              "a new run does not start at dispatch-intent-readers")
        self.pas.derive_next_action(tracker)
        say("initialize_run: run at production depth, repo_root recorded as "
            "the root handed in, stage 01 dispatch-intent-readers")

    def stages_01_to_05(self) -> None:
        #: Stage 01: three readers, one reconciled brief.
        self.dispatch(3, "intent readers")
        for index in (1, 2, 3):
            self.write(f"{RUN_REL}/scratch/intent-reader-{index}.md",
                       f"reader {index}: greet and count, nothing else\n")
        self.write(f"{RUN_REL}/intent-brief.md",
                   "# Intent brief\n\nA greeting helper and a counter.\n")

        def intent(tracker: dict) -> None:
            for index in (1, 2, 3):
                self.pas.append_row(tracker, "intent", {
                    "id": f"reader-{index}", "kind": "reader",
                    "state": "published", "owner": f"intent-reader-{index}",
                    "result": f"scratch/intent-reader-{index}.md",
                    "conflicts": "-"})
            self.pas.append_row(tracker, "intent", {
                "id": "brief", "kind": "brief", "state": "published",
                "owner": "reconciled", "result": "intent-brief.md",
                "conflicts": "-"})
        self.move_stage("01", "02", "dispatch-proposal-brains", intent,
                        missing="stage-01 intent writer (readers + brief) and "
                                "stage transition 01->02")

        #: Stage 02: the proposal brains' merged questions, ranked.
        self.dispatch(3, "proposal brains")
        def questions(tracker: dict) -> None:
            for slot, qid in enumerate(("greeting-style", "count-bound"), 1):
                self.pas.append_row(tracker, "questions", {
                    "id": qid, "origin": "synthesis", "slot": str(slot),
                    "state": "asked", "decision": "-"})
        self.move_stage("02", "03", "ask-the-gate", questions,
                        missing="stage-02 question writer and transition 02->03")

        #: Stage 03: the one gate. Answers recorded as H-1, H-2.
        self.decisions_text = self.read_decisions()
        self.append_decision(self.human_record(
            "greeting-style", "How should greet() address the user?",
            "exclaim — Hello, <name>! with an exclamation mark", scope="run"))
        self.append_decision(self.human_record(
            "count-bound", "What is the largest value count() may return?",
            "unbounded — no bound; plain integers", scope="run"))

        def answered(tracker: dict) -> None:
            for row, did in zip(tracker["questions"], ("H-1", "H-2")):
                row.update(state="answered", decision=did)
            tracker["intent"][3]["state"] = "frozen"
        self.move_stage("03", "04", "design-and-review-class", answered,
                        missing="stage-03 gate-answer writer and transition 03->04")

        #: Stage 04 -> 05 -> 06: design, spec, master plan.
        self.write(SPEC_REL, SPEC_TEXT)
        self.move_stage("04", "05", "write-spec",
                        missing="stage transition 04->05")

        def spec(tracker: dict) -> None:
            tracker["run"]["spec"] = SPEC_REL
        self.move_stage("05", "06", "write-master-plan", spec,
                        missing="stage transition 05->06 and the spec path")
        say("stages 01-05: intent, questions, the gate (H-1, H-2), spec -- by "
            "raw transitions, as planning.md says (no writer exists)")

    def stage_06(self) -> None:
        self.write(MASTER_REL, MASTER_TEXT)

        def master(tracker: dict) -> dict:
            tracker["run"]["master_plan"] = MASTER_REL
            return tracker
        self.raw("record-master-plan", "record ## Run master_plan",
                 "a master-plan path writer (close_phase_set takes ids only)",
                 master)
        tracker = self.pas.close_phase_set(self.run_dir, phase_ids=["P1", "P2"])
        check(self.pas.derive_next_action(tracker) == "fan-out-phase-plans",
              "close_phase_set did not open stage 07")
        say("stage 06: close_phase_set sealed P1,P2 and opened stage 07")

    def stage_07(self) -> None:
        self.dispatch(2, "phase planners")
        self.write(PLAN_REL["P1"], PHASE_1_PLAN)
        self.write(PLAN_REL["P2"], PHASE_2_PLAN)
        self.git("add", SPEC_REL, MASTER_REL, *PLAN_REL.values())
        self.git("commit", "-qm", "planning documents")
        for phase in ("P1", "P2"):
            self.pas.import_phase_plan(self.run_dir,
                                       phase_plan=str(self.repo / PLAN_REL[phase]))
        tracker = self.pas.freeze_dispatch_ceiling(self.run_dir)
        run = tracker["run"]
        check(run["dispatch_projection"] == str(7 * 6 + 3 * 10 + 5),
              f"dispatch projection {run['dispatch_projection']} is not the "
              "planning.md formula over six tasks")
        self.move_stage("07", "08", "write-red-tests",
                        missing="stage transition 07->08 (freeze_dispatch_ceiling "
                                "freezes but does not close stage 07)")
        say(f"stage 07: imported P1 and P2, froze the dispatch ceiling "
            f"({run['dispatch_projection']}/{run['dispatch_soft_ceiling']}/"
            f"{run['dispatch_hard_ceiling']})")

    # -- decisions.md: the controller's file, append-only --------------------

    def decisions_path(self) -> Path:
        return self.repo / self.tracker()["run"]["decisions"]

    def read_decisions(self) -> str:
        path = self.decisions_path()
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def append_decision(self, record: str) -> None:
        path = self.decisions_path()
        text = path.read_text(encoding="utf-8") if path.exists() else DECISIONS_HEAD
        path.write_text(text.rstrip("\n") + "\n\n" + record, encoding="utf-8")
        self.pas.parse_decisions(path.read_text(encoding="utf-8"))

    def human_record(self, axis, question, answer, *, scope, action="none",
                     extra=()) -> str:
        self.human_ids += 1
        did = f"H-{self.human_ids}"
        self.last_human = did
        lines = [f"## {did} — {axis}", "",
                 f"- **Question:** {question}",
                 f"- **Axis:** {axis}",
                 f"- **Answer:** {answer}",
                 f"- **Decision action:** {action}",
                 "- **Provenance:** human",
                 "- **Depth:** 0",
                 f"- **Scope:** {scope}",
                 *extra,
                 "- **Status:** Adopted"]
        return "\n".join(lines) + "\n"

    # -- stage 09: one task, as execution.md teaches it ----------------------

    def reserve(self, task_id: str, owner: str, attempt: int = 1) -> dict:
        self.dispatch(1, f"implementer {owner} for {task_id}")
        tracker = self.pas.reserve_task(self.run_dir, task_id=task_id,
                                        owner=owner, attempt=attempt)
        return next(row for row in tracker["tasks"] if row["id"] == task_id)

    def worker_commit(self, branch: str, files: dict, message: str) -> list:
        """The implementer's work: commits on its own branch, cut from target."""
        exists = self._spawn(("git", "rev-parse", "--verify", "-q",
                              f"refs/heads/{branch}"), strict=False).returncode == 0
        if exists:
            self.git("checkout", "-q", branch)
        else:
            self.git("checkout", "-q", "-b", branch, TARGET)
        commits = []
        for relative, text in files.items():
            self.write(relative, text)
            self.git("add", "--", relative)
            self.git("commit", "-qm", f"{message}: {relative}")
            commits.append(self.git("rev-parse", "HEAD"))
        self.git("checkout", "-q", TARGET)
        return commits

    def rerun_suite(self, commit: str, commands) -> None:
        """The controller's own re-run of a suite at one commit (the evidence)."""
        self.git("checkout", "-q", "--detach", commit)
        try:
            for command in commands:
                completed = self._spawn(tuple(command.split()), strict=False)
                check(completed.returncode == 0,
                      f"suite command {command!r} failed at {commit}: "
                      f"{completed.stderr[-400:]}")
        finally:
            self.git("checkout", "-q", TARGET)

    def publish_evidence(self, *, purpose: str, subject: str, attempt: str,
                         code_state: str, commands, name: str) -> str:
        record = {"purpose": purpose, "run_id": RUN_ID, "subject": subject,
                  "attempt": attempt, "code_state": code_state,
                  "outcome": "PASS", "commands": tuple(commands),
                  "environment": f"python{sys.version_info[0]}."
                                 f"{sys.version_info[1]}-linux",
                  "inputs": ()}
        text = self.pas.render_verification_evidence(record)
        digest = self.pas.publish_immutable(self.run_dir / "evidence" / name, text)
        return f"evidence/{name}#sha256={digest}"

    def result(self, task_id: str, row: dict, status: str, **fields) -> dict:
        base = {"run_id": RUN_ID, "task_id": task_id,
                "attempt": int(row["attempt"].split("-")[1]),
                "owner": row["owner"], "kind": row["kind"], "status": status,
                "source_ref": "-", "commits": (), "artifacts": (), "tests": (),
                "evidence": (), "concerns": "-", "question_record": "-",
                "blocking_reason": "-", "checkpoints": ()}
        base.update(fields)
        return base

    def complete(self, task_id: str, files: dict, *, integrate=True) -> dict:
        """Implement, re-run, publish, import and integrate one [~] task."""
        row = self.task(task_id)
        #: The module derives the head ref as ``task/<task id>``
        #: (``_task_branch``); no reference or prompt says so (FINDINGS).
        branch = f"task/{task_id}"
        finding("medium", "the task branch name is load-bearing and untaught",
                "import_worker_result resolves the range head as "
                "'task/<task id>' (_task_branch, TASK_BRANCH_PREFIX); a worker "
                "branch named otherwise is refused ('names no reference'). "
                "Neither execution.md, prompts/implementer.md nor the task "
                "brief tells the controller or the implementer that name.")
        if files:
            commits = self.worker_commit(branch, files, f"{task_id} work")
        else:
            #: A resumed attempt whose work already stands on its branch.
            commits = self.git("rev-list", "--reverse",
                               f"{self.baseline(task_id)}..{branch}").split()
        commands = TASK_SUITES[task_id]
        #: execution.md step 1: re-run the task's exact suite at the worker's
        #: head, and record THAT as the task-test evidence.
        self.rerun_suite(commits[-1], commands)
        evidence = self.publish_evidence(
            purpose="task-test", subject=f"task/{task_id}",
            attempt=row["attempt"], code_state=commits[-1], commands=commands,
            name=f"{task_id}-{row['attempt']}-task-test.md")
        result = self.result(task_id, row, "DONE", source_ref=commits[-1],
                             commits=tuple(commits), tests=tuple(commands),
                             evidence=(evidence,))
        path = self.pas.publish_worker_result(self.run_dir, result=result)
        tracker = self.import_result(path)
        row = next(r for r in tracker["tasks"] if r["id"] == task_id)
        check(row["state"] == "[x]" and row["integration"] == "held",
              f"import left {task_id} at {row['state']}/{row['integration']}")
        if integrate:
            self.integrate(task_id, branch)
        return self.task(task_id)

    def integrate(self, task_id: str, branch: str) -> None:
        self.git("checkout", "-q", TARGET)
        self.git("merge", "-q", "--no-ff", "--no-edit", "-m",
                 f"integrate {task_id}", branch)
        merge = self.git("rev-parse", "HEAD")
        self.publish_evidence(
            purpose="task-integration", subject=f"task/{task_id}",
            attempt=self.task(task_id)["attempt"], code_state=merge,
            commands=TASK_SUITES[task_id],
            name=f"{task_id}-integration.md")
        finding("low", "task-integration evidence is required by the skill and "
                "read by nothing",
                "execution.md: integration needs 'one task-integration PASS "
                "record for the merge commit'; integrate_task never reads one "
                "and no tracker cell records it (this walkthrough publishes it "
                "anyway).")
        tracker = self.pas.integrate_task(self.run_dir, task_id=task_id,
                                          merge_commit=merge,
                                          run_command=self.run_command)
        row = next(r for r in tracker["tasks"] if r["id"] == task_id)
        check(row["integration"] == merge,
              f"integrate_task recorded {row['integration']} for {task_id}")


    # -- dispatch helpers: the skill's own scripts, run by the controller ----

    def task_brief(self, task_id: str) -> Path:
        finding("low", "task-brief needs numbered task headings the plan "
                "grammar does not require",
                "scripts/task-brief takes TASK_NUMBER as digits and extracts "
                "'## Task <digits>'; planning.md's metadata grammar only says "
                "'immediately below each task heading', and task ids like "
                "'P1-T1' are not numbers. The walkthrough's plans head each "
                "task '## Task <order>: <id>'.")
        phase = task_id.split("-")[0]
        number = str(PHASE_TASKS[phase].index(task_id) + 1)
        out = self.run_dir / "scratch" / f"{task_id}-brief.md"
        completed = self._spawn(("bash", str(SKILL_ROOT / "scripts" / "task-brief"),
                                 str(self.run_dir), str(self.repo / PLAN_REL[phase]),
                                 number, str(out)), strict=False)
        check(completed.returncode == 0 and task_id in out.read_text(encoding="utf-8"),
              f"task-brief did not extract {task_id}: {completed.stderr}")
        return out

    def review_package(self, base: str, head: str) -> str:
        completed = self._spawn(("bash", str(SKILL_ROOT / "scripts" / "review-package"),
                                 str(self.run_dir), base, head), strict=False)
        check(completed.returncode == 0,
              f"review-package failed: {completed.stderr}")
        path = Path(completed.stdout.split(":")[0].split("wrote ", 1)[1])
        check(inside(self.root, path), f"review package written outside: {path}")
        return path.relative_to(self.run_dir).as_posix()

    # -- quorum (references/quorum.md) ---------------------------------------

    def question_text(self, qid_heading: str, *, question, axis, phase, blocks,
                      raiser, options, owners=None, blast=None) -> str:
        lines = ["<!-- pipeline-auto/v1 -->", "", f"## {qid_heading}", "",
                 f"- **Question:** {question}",
                 f"- **Axis:** {axis}",
                 f"- **Phase:** {phase}",
                 f"- **Blocks:** {blocks}",
                 f"- **Raiser:** {raiser}",
                 "- **Options supplied:** yes",
                 f"- **Options:** {', '.join(options)}",
                 f"- **Candidate answers:** {options[0]}",
                 f"- **Recommendation:** {options[0]}"]
        if owners is not None:
            lines += [f"- **Reading roots:** spec={SPEC_REL}, "
                      f"intent-brief={RUN_REL}/intent-brief.md, repo=., "
                      f"tests=tests, phase-plan={PLAN_REL[phase]}",
                      f"- **Owners:** {', '.join(owners)}",
                      f"- **Blast radius:** {blast}"]
        return "\n".join(lines) + "\n"

    def open_question(self, task_id: str, question: str, options, *,
                      axis: str = "new", raiser=None) -> tuple:
        """The worker's record, the completed copy, then open_quorum."""
        row = self.task(task_id)
        phase = row["phase"]
        raiser = raiser or row["owner"]
        qid = self.pas.derive_qid(question, axis)
        fields = dict(question=question, axis=axis, phase=phase,
                      blocks=task_id, raiser=raiser, options=options)
        stem = f"{RUN_REL}/scratch/{task_id}-{row['attempt']}-question"
        self.write(f"{stem}.md", self.question_text(f"Q-{qid} — {task_id}", **fields))
        completed = self.write(f"{stem}-completed.md", self.question_text(
            f"Q-{qid} — {task_id}", owners=BRAINS, blast="task", **fields))
        parsed = self.pas.parse_question(completed.read_text(encoding="utf-8"))
        check(self.pas.check_admissible(parsed) == [],
              f"check_admissible refused {task_id}'s question")
        budget = self.pas.quorum_budget(str(self.run_dir), phase=phase)
        check(budget["may_raise"], f"budget refuses a quorum in {phase}: {budget}")
        opened = self.pas.open_quorum(str(self.run_dir),
                                      question_record=str(completed))
        check(opened["qid"] == qid and opened["status"] == "in_flight",
              f"open_quorum returned {opened}")
        published = self.run_dir / "quorum" / qid / "question.md"
        digest = hashlib.sha256(published.read_bytes()).hexdigest()
        return qid, f"{RUN_REL}/quorum/{qid}/question.md#sha256={digest}"

    def raise_question(self, task_id: str, question: str, options) -> str:
        """NEEDS_CONTEXT: open the quorum, publish the result, import (park)."""
        row = self.task(task_id)
        qid, reference = self.open_question(task_id, question, options)
        result = self.result(task_id, row, "NEEDS_CONTEXT",
                             question_record=reference)
        path = self.pas.publish_worker_result(self.run_dir, result=result)
        tracker = self.import_result(path)
        parked = next(r for r in tracker["tasks"] if r["id"] == task_id)
        check(parked["state"] == "[?]" and qid in parked["question"],
              f"{task_id} was not parked on {qid}: {parked['state']} "
              f"{parked['question']}")
        return qid

    def brain_response(self, qid: str, answer_key: str, *, line: int,
                       quote: str, other: str, rung: str = "specified") -> dict:
        return {
            "qid": qid, "answer_key": answer_key,
            "answer": f"Use {answer_key}.",
            "rung": rung,
            "evidence": [{"kind": "spec", "path": SPEC_REL, "line": line,
                          "quote": quote}],
            "consequences": [{"kind": "command-passes",
                              "subject": f"python3 -m unittest -k {answer_key}",
                              "value": "exit-0"}],
            "consistent_with": [{"kind": "decision", "id": "H-1"}],
            "forecloses": [f"the {other} reading"],
            "blast": [qid],
            "alternatives": [{"answer_key": other, "rung": "speculation",
                              "reason": "nothing on disk asks for it"}],
            "what_would_change_my_mind": "A spec line asking for the other option.",
            "blocker": None,
        }

    def answer_brains(self, qid: str, responses) -> None:
        """Dispatch three brains on their own payloads; record what they wrote."""
        self.dispatch(3, f"brains for {qid}")
        for index, (owner, response) in enumerate(zip(BRAINS, responses)):
            payload = self.pas.build_payload(qid, index, run_dir=str(self.run_dir))
            check(payload["qid"] == qid, "build_payload named another qid")
            out = self.write(f"{RUN_REL}/scratch/{qid}-{owner}.json",
                             json.dumps(response, indent=2))
            self.pas.record_brain_response(
                str(self.run_dir), qid=qid, owner=owner,
                payload=json.loads(out.read_text(encoding="utf-8")))

    # -- the per-task gate (execution.md) ------------------------------------

    def resume(self, task_id: str, prior: int, owner: str, decision: str) -> None:
        self.dispatch(1, f"implementer {owner} for {task_id} (resumed)")
        self.pas.resume_task(str(self.run_dir), task_id=task_id,
                             prior_attempt=prior, new_owner=owner,
                             new_attempt=prior + 1, decision_ref=decision)

    def baseline(self, task_id: str) -> str:
        row = self.task(task_id)
        return self.pas.reserved_baseline(
            row, attempt=int(row["attempt"].split("-")[1]))

    def review_round(self, task_id: str, round_number: int, reviewer: str, *,
                     minor: int = 0, state: str = "accepted") -> dict:
        self.dispatch(1, f"task reviewer for {task_id} round {round_number}")
        row = self.task(task_id)
        head = (row["source_ref"] if row["source_ref"] != "-"
                else self.git("rev-parse", f"task/{task_id}"))
        package = self.review_package(self.baseline(task_id), head)
        report = f"scratch/{task_id}-review-{round_number}.md"
        self.write(f"{RUN_REL}/{report}",
                   f"spec: pass\nquality: {minor} minor\nverification: re-ran\n")
        self.rerun_suite(head, TASK_SUITES[task_id])
        rerun = f"scratch/{task_id}-review-{round_number}-rerun.txt"
        self.write(f"{RUN_REL}/{rerun}", "OK\n")
        review = {"task": task_id, "round": str(round_number),
                  "intensity": "standard", "state": state,
                  "reviewer": reviewer, "package": package, "report": report,
                  "critical": "0", "important": "0", "minor": str(minor),
                  "adversarial": "-", "adversarial_verdict": "-",
                  "open": str(minor), "evidence": rerun}

        def mutate(tracker: dict) -> dict:
            return self.pas.append_row(tracker, "task_review", review)
        return self.raw(f"review-{task_id}-{round_number}",
                        f"## Task Review row {task_id} round {round_number} "
                        f"({state})",
                        "a ## Task Review writer (execution.md: 'write rows "
                        "through locked_tracker_update')", mutate)

    # -- reconciliation parking (execution.md, the per-task gate) ------------

    def park_on_reconciliation(self, task_id: str, qid: str, reference: str,
                               review: dict, *, clear_completion=False) -> dict:
        """Move a task under review to [?] on the reconciliation question.

        No public writer does this. The only writer of a ``Question`` cell is
        ``import_worker_result``; this raw transition renders the cell and the
        ``blocked:`` checkpoint exactly the way that writer does
        (``quorum:<qid>@<path>#sha256=<digest>``) and records the disputed
        round in the same transition.
        """
        marker = f"quorum:{qid}@{reference}"

        def mutate(tracker: dict) -> dict:
            row = next(r for r in tracker["tasks"] if r["id"] == task_id)
            row["state"] = "[?]"
            row["question"] = marker
            if clear_completion:
                #: A [?] row may not carry completion cells (_TASK_COMPLETION);
                #: the commits stay on the branch and in the result file.
                for key in ("source_ref", "commits", "artifacts", "integration"):
                    row[key] = "-"
            entry = f"blocked:{row['attempt']}@{marker}"
            row["checkpoints"] = (entry if row["checkpoints"] == "-"
                                  else f"{row['checkpoints']},{entry}")
            return self.pas.append_row(tracker, "task_review", review)
        suffix = "-cleared" if clear_completion else ""
        return self.raw(f"reconcile-park-{task_id}{suffix}",
                        f"park {task_id} [x]->[?] on reconciliation quorum "
                        f"{qid}, with its disputed review round"
                        + (", clearing its completion cells" if clear_completion
                           else ""),
                        "a reconciliation parking writer (the Question cell's "
                        "only writer is import_worker_result)", mutate)

    # -- escalations (quorum.md, Escalating) ---------------------------------

    def escalation_row(self, qid: str) -> dict:
        return next(r for r in self.tracker()["escalations"] if r["qid"] == qid)

    def set_escalation(self, esc_id: str, *, what: str, **cells) -> dict:
        def mutate(tracker: dict) -> dict:
            next(r for r in tracker["escalations"] if r["id"] == esc_id).update(cells)
            return tracker
        return self.raw(f"escalation-{esc_id}-{cells.get('state')}", what,
                        "an escalation batch/answer writer (quorum.md: 'no "
                        "function writes asked/answered')", mutate)

    def human_resume(self, qid: str, task_id: str, question: str,
                     answer: str) -> str:
        """Batch the escalation, record the human's answer, answer the row."""
        row = self.escalation_row(qid)
        check(row["state"] == "queued",
              f"finalize_quorum did not queue an escalation for {qid}: {row}")
        check(self.pas.derive_next_action(self.tracker()) == "await-escalation-batch",
              "a queued escalation does not make the next action "
              "await-escalation-batch")
        batch = f"batch-{row['id'].split('-')[1]}"
        self.set_escalation(row["id"], state="asked", batch=batch,
                            what=f"{row['id']} asked in {batch}")
        self.append_decision(self.human_record(
            f"answer-{qid}", question, answer, scope=task_id,
            action="task.resume"))
        did = self.last_human
        self.set_escalation(row["id"], state="answered", resolution=did,
                            what=f"{row['id']} answered by {did}")
        return did

    # -- the phase boundary (execution.md) -----------------------------------

    def verify_phase(self, phase: str) -> None:
        tip = self.git("rev-parse", TARGET)
        self.rerun_suite(tip, PHASE_SUITES[phase])
        reference = self.publish_evidence(
            purpose="phase", subject=f"phase/{phase}", attempt="N/A",
            code_state=tip, commands=PHASE_SUITES[phase],
            name=f"{phase}-phase.md")

        def mutate(tracker: dict) -> dict:
            row = next(r for r in tracker["phases"] if r["id"] == phase)
            row.update(state="[x]", verification=reference)
            return tracker
        self.raw(f"verify-{phase}", f"phase {phase} [x] with its phase evidence",
                 "a phase-verification writer (execution.md: 'phase "
                 "verification and phase advance' are not enforced by code)",
                 mutate)

# ---------------------------------------------------------------------------
# The foreign repository's planning documents.
# ---------------------------------------------------------------------------

SPEC_TEXT = """# Walkthrough feature design

greet(name) returns the greeting the user chose at the gate.
count(items) returns the number of items and raises on a negative total.
farewell(name) returns a farewell line for the user.
wave(name) returns a wave line for the user.
Every public function is covered by a unittest module under tests/.
"""

MASTER_TEXT = """# Walkthrough master plan

| Phase | Depends | Plan | Review class |
| --- | --- | --- | --- |
| P1 | none | docs/superpowers/plans/walkthrough/phase-1.md | required |
| P2 | P1 | docs/superpowers/plans/walkthrough/phase-2.md | final-only |
"""

PHASE_SUITES = {"P1": ["python3 -m unittest discover -s tests"],
                "P2": ["python3 -m unittest discover -s tests"]}
TASK_SUITES = {
    "P1-T1": ["python3 -m unittest tests.test_greet"],
    "P1-T2": ["python3 -m unittest tests.test_count"],
    "P1-T3": ["python3 -m unittest tests.test_shout"],
    "P2-T1": ["python3 -m unittest tests.test_farewell"],
    "P2-T2": ["python3 -m unittest tests.test_wave"],
    "P2-T3": ["python3 -m unittest tests.test_beam"],
}
SCOPES = {
    "P1-T1": "file:app/greet.py,file:tests/test_greet.py",
    "P1-T2": "file:app/count.py,file:tests/test_count.py",
    "P1-T3": "file:app/shout.py,file:tests/test_shout.py",
    "P2-T1": "file:app/farewell.py,file:tests/test_farewell.py",
    "P2-T2": "file:app/wave.py,file:tests/test_wave.py",
    "P2-T3": "file:app/beam.py,file:tests/test_beam.py",
}


def phase_plan(phase: str, deps: str, review_class: str, reason: str,
               tasks) -> str:
    lines = [f"# Phase {phase} plan", "",
             f"<!-- pipeline-auto-phase: id={phase}; deps={deps}; "
             f"review_class={review_class}; review_reason={reason} -->",
             f"<!-- pipeline-auto-phase-suite: id={phase}; "
             f"commands={json.dumps(PHASE_SUITES[phase])} -->", ""]
    for order, task_id in enumerate(tasks, 1):
        #: ``scripts/task-brief`` extracts by ``Task <digits>``, so the heading
        #: carries the order number and the id follows it.
        lines += [f"## Task {order}: {task_id}", "",
                  f"<!-- pipeline-auto-task: id={task_id}; deps=none; "
                  f"kind=source; batch=b{order}; order={order}; "
                  f"write_scope={SCOPES[task_id]}; outputs=none -->",
                  f"<!-- pipeline-auto-task-suite: id={task_id}; "
                  f"commands={json.dumps(TASK_SUITES[task_id])} -->", "",
                  f"Implement {task_id} test-first.", ""]
    return "\n".join(lines)


PHASE_TASKS = {"P1": ("P1-T1", "P1-T2", "P1-T3"),
               "P2": ("P2-T1", "P2-T2", "P2-T3")}
PHASE_1_PLAN = phase_plan("P1", "none", "required",
                          "public helpers other code will import",
                          PHASE_TASKS["P1"])
PHASE_2_PLAN = phase_plan("P2", "P1", "final-only",
                          "two small leaf helpers with no callers",
                          PHASE_TASKS["P2"])

DECISIONS_HEAD = "<!-- pipeline-auto-decisions/v1 -->\n"


FILES = {
    "P1-T1": {"tests/test_greet.py":
              "import unittest\nfrom app.greet import greet\n\n\n"
              "class T(unittest.TestCase):\n    def test_greet(self):\n"
              "        self.assertEqual(greet('Ada'), 'Hello, Ada!')\n",
              "app/greet.py": "def greet(name):\n    return f'Hello, {name}!'\n"},
    "P1-T2": {"tests/test_count.py":
              "import unittest\nfrom app.count import count\n\n\n"
              "class T(unittest.TestCase):\n    def test_count(self):\n"
              "        self.assertEqual(count([1, 2]), 2)\n",
              "app/count.py": "def count(items):\n    return len(list(items))\n"},
    "P1-T3": {"tests/test_shout.py":
              "import unittest\nfrom app.shout import shout\n\n\n"
              "class T(unittest.TestCase):\n    def test_shout(self):\n"
              "        self.assertEqual(shout('hi'), 'HI!')\n",
              "app/shout.py": "def shout(text):\n    return text.upper() + '!'\n"},
    "P2-T1": {"tests/test_farewell.py":
              "import unittest\nfrom app.farewell import farewell\n\n\n"
              "class T(unittest.TestCase):\n    def test_farewell(self):\n"
              "        self.assertEqual(farewell('Ada'), 'Goodbye, Ada!')\n",
              "app/farewell.py":
              "def farewell(name):\n    return f'Goodbye, {name}!'\n"},
    "P2-T2": {"tests/test_wave.py":
              "import unittest\nfrom app.wave import wave\n\n\n"
              "class T(unittest.TestCase):\n    def test_wave(self):\n"
              "        self.assertEqual(wave('Ada'), 'Ada waves.')\n",
              "app/wave.py": "def wave(name):\n    return f'{name} waves.'\n"},
    "P2-T3": {"tests/test_beam.py":
              "import unittest\nfrom app.beam import beam\n\n\n"
              "class T(unittest.TestCase):\n    def test_beam(self):\n"
              "        self.assertEqual(beam('Ada'), 'Ada beams!')\n",
              "app/beam.py": "def beam(name):\n    return f'{name} beams!'\n"},
}


# ---------------------------------------------------------------------------
# The run.
# ---------------------------------------------------------------------------

def drive(ctl: Controller) -> None:
    ctl.build_repo()
    ctl.initialize()
    ctl.stages_01_to_05()
    ctl.stage_06()
    ctl.stage_07()
    ctl.move_stage("08", "09", "run-phase-P1",
                   missing="stage transition 08->09")
    # -- P1-T1: the plain path, with its per-task gate (P1 is required) ----
    ctl.reserve("P1-T1", "impl-1")
    ctl.task_brief("P1-T1")
    ctl.complete("P1-T1", FILES["P1-T1"], integrate=False)
    ctl.review_round("P1-T1", 1, "task-reviewer-1")
    ctl.integrate("P1-T1", "task/P1-T1")
    say("P1-T1: reserved, briefed (task-brief), committed, re-run as task-test "
        "evidence, published, imported, reviewed (review-package, round 1 "
        "accepted), integrated --no-ff")

    # -- P1-T2: NEEDS_CONTEXT -> quorum -> adopted -> resume on Q-<qid> -----
    ctl.reserve("P1-T2", "impl-2")
    ctl.task_brief("P1-T2")
    qid = ctl.raise_question(
        "P1-T2", "Should count() raise ValueError or return zero on a negative total?",
        ["raise", "zero"])
    ctl.answer_brains(qid, [
        ctl.brain_response(qid, "raise", line=4, quote="raises on a negative total",
                           other="zero")] * 3)
    final = ctl.pas.finalize_quorum(str(ctl.run_dir), qid=qid)
    check(final["status"] == "adopted", f"finalize_quorum did not adopt: {final}")
    ctl.resume("P1-T2", 1, "impl-2b", f"Q-{qid}")
    ctl.complete("P1-T2", FILES["P1-T2"], integrate=False)
    ctl.review_round("P1-T2", 1, "task-reviewer-1")
    ctl.integrate("P1-T2", "task/P1-T2")
    say(f"P1-T2: NEEDS_CONTEXT parked on quorum {qid}; three brain responses "
        f"recorded from files; finalize_quorum adopted; resume_task on Q-{qid}; "
        "attempt 2 completed, reviewed, integrated")

    reconciliation(ctl, qid)
    ctl.verify_phase("P1")
    say("P1: phase suite re-run on the integrated tip, phase evidence "
        "published, phase [x]")
    ctl.set_next_action("09", "run-phase-P2", "stage 09 next-action writer")

    phase_two(ctl)
    ctl.verify_phase("P2")
    say("P2: phase evidence published, phase [x]")
    master_gate_and_completion(ctl)


def reconciliation(ctl: Controller, governing: str) -> None:
    """Item 7: park a task under review on a reconciliation quorum.

    ``governing`` is the qid of the quorum decision the reviewer's Minor
    finding would reverse -- the spec's case ("requires reversing a quorum
    decision", design spec, "A reviewer finding may not reverse a decision").
    """
    pas = ctl.raw_module
    ctl.reserve("P1-T3", "impl-3")
    ctl.task_brief("P1-T3")
    ctl.complete("P1-T3", FILES["P1-T3"], integrate=False)
    row = ctl.task("P1-T3")
    package = ctl.review_package(ctl.baseline("P1-T3"), row["source_ref"])
    ctl.write(f"{RUN_REL}/scratch/P1-T3-review-1.md",
              f"quality: Minor F-001 -- shout() should return '' on bad input "
              f"the lenient way, which reverses Q-{governing} (raise)\n")
    ctl.write(f"{RUN_REL}/scratch/P1-T3-review-1-rerun.txt", "OK\n")
    blocked = {"task": "P1-T3", "round": "1", "intensity": "standard",
               "state": "blocked", "reviewer": "task-reviewer-1",
               "package": package, "report": "scratch/P1-T3-review-1.md",
               "critical": "0", "important": "0", "minor": "1",
               "adversarial": "-", "adversarial_verdict": "-", "open": "1",
               "evidence": "scratch/P1-T3-review-1-rerun.txt"}
    #: Probe 1: the gate's failing verdict, recorded while the task is [x].
    try:
        ctl.pas.locked_tracker_update(
            ctl.run_dir, transition_id="probe-blocked-round-on-x",
            mutate=lambda t: pas.append_row(t, "task_review", dict(blocked)))
        finding("info", "a blocked review round is recordable on an imported "
                "task", "no refusal")
    except pas.TrackerError as exc:
        finding("high", "the per-task gate cannot record a failing round after "
                "import",
                "import_worker_result moves a DONE task straight to [x], and "
                "_validate_task_review refuses an [x] task whose last round is "
                f"not accepted. Refusal: {exc}. execution.md orders import "
                "BEFORE the per-task gate ('Import, completion, integration' "
                "then 'The per-task gate ... Complete only after a round "
                "returns zero'), but import IS the completion. Running the gate "
                "before import works (this walkthrough does so for P1-T3's "
                "attempt 2).")
    #: Probe 2: "a quorum question on the decision's axis". A quorum decision's
    #: axis is its own minted qid.
    question = ("Should shout() return an empty string on bad input instead of "
                "raising, reversing the count() ruling?")
    survives = [ctl.brain_response("0" * 12, "raise", line=4,
                                   quote="raises on a negative total",
                                   other="lenient")] * 3
    on_axis = False
    try:
        probe = None
        probe, _ = ctl.open_question("P1-T3", question, ["raise", "lenient"],
                                     axis=governing, raiser="task-reviewer-1")
        ctl.answer_brains(probe, [dict(r, qid=probe, blast=[probe])
                                  for r in survives])
        final = ctl.pas.finalize_quorum(str(ctl.run_dir), qid=probe)
        on_axis = final["status"] == "adopted"
    except pas.TrackerError as exc:
        wedged = (ctl.pas.classify_quorum(str(ctl.run_dir), qid=probe,
                                          live_owners=list(BRAINS))["state"]
                  if probe else "not opened")
        finding("high", "a reconciliation question on a quorum decision's axis "
                "opens but can never be finalised",
                f"open_quorum accepted axis {governing!r} (the minted axis of "
                f"Q-{governing}) and dispatched; finalize_quorum then raised "
                f"({type(exc).__name__}: {exc}) while mirroring the ## Quorum "
                "row, publishing nothing; classify_quorum still reports "
                f"{wedged!r} and reconcile_run reports nothing, so the quorum "
                "is wedged on disk. execution.md: 'The reconciliation is a "
                "quorum question on the decision's axis'; a quorum decision's "
                "axis is its minted qid, which ## Quorum's Axis cell refuses "
                "(stage-03 ids and 'new' only), and open_quorum does not check "
                "it. Fallback used: the same question on axis 'new'.")
    if on_axis:
        qid, reference = probe, None
        check(False, "unexpected: the on-axis reconciliation adopted")
    qid, reference = ctl.open_question(
        "P1-T3", question, ["raise", "lenient"], raiser="task-reviewer-1")
    #: Probe 3: park it. First exactly as import_worker_result renders a
    #: parked row; then with the completion cells cleared.
    parked = False
    for clear in (False, True):
        try:
            tracker = ctl.park_on_reconciliation("P1-T3", qid, reference,
                                                 blocked, clear_completion=clear)
        except pas.TrackerError as exc:
            RAW_TRANSITIONS[-1] = RAW_TRANSITIONS[-1][:2] + (
                RAW_TRANSITIONS[-1][2] + " [REFUSED]",)
            finding("high", "reconciliation parking of an imported task is "
                    "refused" + (" even with its completion cells cleared"
                                 if clear else ""),
                    f"raw park transition (import's cell rendering"
                    f"{', completion cells cleared' if clear else ''}) refused: "
                    f"{exc}")
            continue
        cell = next(r for r in tracker["tasks"] if r["id"] == "P1-T3")
        parked = cell["state"] == "[?]"
        say(f"reconciliation: raw park of P1-T3 on {qid} passed every guard"
            + (" once its completion cells were cleared" if clear else ""))
        break
    if not parked:
        return
    owners = pas._implementation_owners(ctl.tracker())
    if "impl-3" in owners:
        finding("medium", "a parked reconciliation task keeps its owner slot",
                "spec (reconciliation) and execution.md: 'its owner slot "
                "releases'. _implementation_owners counts '[~]' and '[?]', so a "
                "parked task still holds a slot under implementation_slot_cap.")
    #: The decision survives: all three brains ground 'raise' in the spec.
    ctl.answer_brains(qid, [dict(r, qid=qid, blast=[qid]) for r in survives])
    final = ctl.pas.finalize_quorum(str(ctl.run_dir), qid=qid)
    check(final["status"] == "adopted",
          f"the reconciliation quorum did not adopt: {final.get('status')} "
          f"{final.get('reason')}")
    try:
        ctl.resume("P1-T3", 1, "impl-3b", f"Q-{qid}")
    except pas.TrackerError as exc:
        finding("high", "a reconciliation-parked task does not resume on the "
                "adoption", f"resume_task refused Q-{qid}: {exc}")
        return
    #: The finding closes REFUTED -- governed by the surviving decision.
    ctl.write(f"{RUN_REL}/scratch/P1-T3-review-2.md",
              f"F-001: REFUTED — governed by Q-{governing}\n")
    #: Round 2 is recorded BEFORE the attempt-2 import: once a round exists,
    #: an [x] row needs its last round accepted, so the gate must close first.
    ctl.review_round("P1-T3", 2, "task-reviewer-1")
    ctl.complete("P1-T3", None, integrate=False)
    ctl.integrate("P1-T3", "task/P1-T3")
    fix_rounds = [r for r in ctl.tracker()["fix_rounds"] if r["scope"] == "P1-T3"]
    check(not fix_rounds, "the reconciliation spent a fix round")
    say("reconciliation: on axis new"
        f", adopted Q-{qid} (the decision survives), resume_task released "
        "P1-T3 on it, round 2 accepted with F-001 REFUTED, attempt 2 "
        "re-imported the standing commits, integrated; no fix round spent")


def phase_two(ctl: Controller) -> None:
    pas = ctl.raw_module
    # -- P2-T1: a quorum that ties and escalates; a human answer resumes it --
    ctl.reserve("P2-T1", "impl-5")
    tie = ctl.raise_question(
        "P2-T1", "Is farewell() formal or casual?", ["formal", "casual"])
    ctl.answer_brains(tie, [
        ctl.brain_response(tie, "formal", line=5,
                           quote="returns a farewell line", other="casual"),
        ctl.brain_response(tie, "formal", line=5,
                           quote="returns a farewell line", other="casual"),
        ctl.brain_response(tie, "casual", line=5,
                           quote="for the user", other="formal")])
    final = ctl.pas.finalize_quorum(str(ctl.run_dir), qid=tie)
    check(final["status"] == "escalated"
          and final["reason"] == "equal-or-inverted-rung",
          f"the tie did not escalate as equal-or-inverted-rung: {final}")

    # -- P2-T2: its quorum is answered while the tie waits for the human -----
    ctl.reserve("P2-T2", "impl-6")
    stale = ctl.raise_question(
        "P2-T2", "Does wave() put the name first or last?", ["first", "last"])
    ctl.answer_brains(stale, [
        ctl.brain_response(stale, "first", line=6, quote="returns a wave line",
                           other="last")] * 3)
    ready = ctl.pas.classify_quorum(str(ctl.run_dir), qid=stale,
                                    live_owners=list(BRAINS))
    check(ready["state"] == "ready-to-finalise",
          f"P2-T2's answered quorum is {ready}")

    #: The human answers the tie: decisions.md changes under P2-T2's quorum.
    h_tie = ctl.human_resume(tie, "P2-T1", "Is farewell() formal or casual?",
                             "formal — Goodbye, <name>!")
    ctl.resume("P2-T1", 1, "impl-5b", h_tie)
    ctl.complete("P2-T1", FILES["P2-T1"])
    say(f"P2-T1: quorum {tie} tied at specified and escalated "
        f"(equal-or-inverted-rung); E-row batched, human answer {h_tie} "
        f"recorded, row answered; resume_task on {h_tie}; completed, integrated")

    # -- P2-T2: stale-context, finalised as the corrected quorum.md says -----
    state = ctl.pas.classify_quorum(str(ctl.run_dir), qid=stale,
                                    live_owners=list(BRAINS))
    check(state["state"] == "stale-context",
          f"a decisions.md change did not make {stale} stale-context: {state}")
    final = ctl.pas.finalize_quorum(str(ctl.run_dir), qid=stale)
    check(final["status"] == "escalated" and final["reason"] == "stale-context",
          f"finalize_quorum on a stale quorum returned {final}")
    h_stale = ctl.human_resume(stale, "P2-T2",
                               "Does wave() put the name first or last?",
                               "first — <name> waves.")
    ctl.resume("P2-T2", 1, "impl-6b", h_stale)
    ctl.complete("P2-T2", FILES["P2-T2"])
    say(f"P2-T2: decisions.md moved under quorum {stale}; classify_quorum "
        "reported stale-context; finalize_quorum escalated it (stale-context) "
        f"without reading an answer; human {h_stale} resumed it; completed")

    human_axis_supersession(ctl)


def master_gate_and_completion(ctl: Controller) -> None:
    pas = ctl.raw_module
    ctl.move_stage("09", "10", "debug-none-open", missing="stage transition 09->10")
    ctl.move_stage("10", "11", "open-master-gate", missing="stage transition 10->11")
    tracker = ctl.pas.open_master_gate(str(ctl.run_dir), reviewers=dict(REVIEWERS))
    gate = next(r for r in tracker["gates"] if r["type"] == "master")
    check(gate["base"] == ctl.base_commit, "the master gate's base is not base_commit")
    check(gate["head"] == ctl.git("rev-parse", TARGET),
          "the master gate's head is not the target tip")
    #: An implementer may not review: the tracker refuses it.
    try:
        ctl.pas.open_master_gate(str(ctl.run_dir),
                                 reviewers={"A": "impl-1", "B": "someone"})
        finding("high", "an implementer was accepted as a master reviewer", "")
    except pas.TrackerError:
        pass
    ctl.dispatch(3, "two master reviewers and the completeness critic")
    reports = []
    for role, reviewer in sorted(REVIEWERS.items()):
        report = f"scratch/master-{role.lower()}.md"
        ctl.write(f"{RUN_REL}/{report}", f"reviewer {role} ({reviewer}): 0 findings\n")
        reports.append(report)
    ctl.rerun_suite(gate["head"], PHASE_SUITES["P2"])
    review = ctl.publish_evidence(
        purpose="branch-review", subject=f"gate/{gate['id']}", attempt="N/A",
        code_state=gate["head"], commands=PHASE_SUITES["P2"],
        name="master-branch-review.md")

    def accept(tracker: dict) -> dict:
        row = next(r for r in tracker["gates"] if r["type"] == "master")
        row.update(state="accepted", reports=",".join(reports),
                   verification=review)
        return tracker
    ctl.raw("master-gate-accept", "master gate reports, verification, accepted",
            "a master-gate verdict writer (review.md: 'writers for the master "
            "gate's reports, verdict, fix rounds and stage 12' do not exist)",
            accept)
    say(f"stage 11: open_master_gate({REVIEWERS['A']}, {REVIEWERS['B']}) over "
        f"base_commit..{gate['head'][:12]}; an implementer as reviewer refused; "
        "two reports and branch-review evidence recorded; gate accepted")

    ctl.move_stage("11", "12", "final-verification", missing="stage transition 11->12")
    ctl.rerun_suite(gate["head"], PHASE_SUITES["P2"])
    ctl.publish_evidence(purpose="final", subject=f"gate/{gate['id']}",
                         attempt="N/A", code_state=gate["head"],
                         commands=PHASE_SUITES["P2"], name="final.md")

    def finish(tracker: dict) -> dict:
        row = next(r for r in tracker["stages"] if r["stage"] == "12")
        row.update(stage_state="complete", next_action="-")
        return tracker
    tracker = ctl.raw("stage-12-complete", "close stage 12 (all stages complete)",
                      "a stage-12 completion writer", finish)
    status = ctl.git("status", "--short")
    check(status == "", f"the tree is not clean at completion: {status!r}")

    #: The variant without proposals: no completeness-proposals.md yet.
    check(pas.derive_next_action(ctl.tracker()) == "complete",
          "a finished run with no proposals does not derive 'complete'")
    #: The critic's MISSING-FROM-SPEC item, in the template's exact shape.
    template = (SKILL_ROOT / "templates" / "completeness-proposals.md").read_text(
        encoding="utf-8")
    path = ctl.repo / tracker["run"]["completeness_proposals"]
    check(not path.exists() or "## CP-" not in path.read_text(encoding="utf-8"),
          "completeness-proposals.md already holds a proposal")
    path.write_text(template.rstrip("\n") + "\n\n" + (
        "## CP-1\n\n"
        "- **Statement:** A localisation layer for greet() and farewell().\n"
        "- **Evidence:** The critic: no approved requirement asks for more "
        "than one language.\n"
        "- **Traces to:** none\n"
        "- **Status:** Frozen\n"
        "- **Classification:** MISSING-FROM-SPEC\n"), encoding="utf-8")
    action = ctl.pas.derive_next_action(ctl.tracker())
    check(action == "complete-with-proposals",
          f"a frozen CP-1 derives {action!r}, not complete-with-proposals")
    say("stage 12: final evidence, stages all complete, tree clean; "
        "derive_next_action = 'complete' with no proposals and "
        "'complete-with-proposals' once CP-1 (template shape) is written")

    #: persistence.md, file-first resume: a fresh session reconciles and
    #: derives the terminal action from files and Git alone.
    fresh = load_module()
    report = Audited(fresh).reconcile_run(str(ctl.run_dir),
                                          run_command=ctl.run_command)
    check(not report["actions"], f"reconcile_run on a finished run acted: {report}")
    action = Audited(fresh).derive_next_action(
        Audited(fresh).validate_run(ctl.run_dir))
    check(action == "complete-with-proposals",
          f"a fresh module instance derives {action!r}")
    say(f"resume: a fresh module instance's reconcile_run took no action "
        f"({len(report['questions'])} question(s), "
        f"{len(report['diagnostics'])} diagnostic(s)) and derived "
        "complete-with-proposals from files")
    for item in report["questions"] + report["diagnostics"]:
        print(f"  reconcile: {item}")


def human_axis_supersession(ctl: Controller) -> None:
    """A worker question tagged to a stage-03 axis, answered in agreement."""
    pas = ctl.raw_module
    ctl.reserve("P2-T3", "impl-7")
    qid, reference = ctl.open_question(
        "P2-T3", "Does beam() end with the exclamation mark the gate chose?",
        ["exclaim", "plain"], axis="greeting-style")
    result = ctl.result("P2-T3", ctl.task("P2-T3"), "NEEDS_CONTEXT",
                        question_record=reference)
    path = ctl.pas.publish_worker_result(ctl.run_dir, result=result)
    ctl.import_result(path)
    ctl.answer_brains(qid, [
        ctl.brain_response(qid, "exclaim", line=3,
                           quote="the greeting the user chose at the gate",
                           other="plain")] * 3)
    final = ctl.pas.finalize_quorum(str(ctl.run_dir), qid=qid)
    check(final["status"] == "adopted", f"P2-T3 quorum: {final}")
    records = pas.parse_decisions(ctl.read_decisions())["decisions"]
    if records["H-1"]["status"] != "Adopted":
        finding("high", "a quorum adoption that AGREES with a human decision "
                "retires it",
                f"Q-{qid}, asked on stage-03 axis 'greeting-style' and agreeing "
                f"with H-1, was written with 'Supersedes: H-1' and H-1 is now "
                f"{records['H-1']['status']}. finalize_quorum's writer "
                "supersedes whatever stands on the axis (\"ADOPTION SUPERSEDES; "
                "IT NEVER APPENDS BESIDE\"), and check_contradiction clears an "
                "agreeing candidate. The axis then holds a quorum decision, so "
                "a later contradicting answer is rejected-contradicts-quorum "
                "(re-openable at a raised bar) instead of "
                "rejected-contradicts-human. Spec §2 ('It may never overrule a "
                "recorded one'); SKILL.md ('No rung and no unanimity outranks a "
                "human's recorded answer ... it stays Adopted'); quorum.md lets "
                "a question carry a stage-03 axis.")
    ctl.resume("P2-T3", 1, "impl-7b", f"Q-{qid}")
    ctl.complete("P2-T3", FILES["P2-T3"])
    say(f"P2-T3: question on stage-03 axis greeting-style adopted Q-{qid} in "
        "agreement with H-1; resumed, completed, integrated")


def main() -> int:
    global _HOOKED
    if sys.platform != "linux":
        print(f"SKIP: pipeline-auto is Linux-only and this is {sys.platform!r}; "
              "classify_filesystem answers 'unknown' there and the run would halt")
        return 0
    module = load_module()
    if not _HOOKED:
        sys.addaudithook(AUDIT.hook)
        _HOOKED = True
    AUDIT.writes.clear()
    AUDIT.reads.clear()
    AUDIT.spawned.clear()
    RAW_TRANSITIONS.clear()
    FINDINGS.clear()
    LOG.clear()
    root = Path(tempfile.mkdtemp(prefix="pipeline-auto-walkthrough-"))
    try:
        ctl = Controller(module, root)
        drive(ctl)
        assert_confined(root, AUDIT.writes)
        check(not AUDIT.spawned,
              f"the module spawned a process itself: {AUDIT.spawned}")
        check(ctl.git_cwds and all(inside(root, c) for c in ctl.git_cwds),
              "a git call ran outside the temporary repository")
        say(f"confinement: {len(AUDIT.writes)} module write paths, every one "
            f"inside the root; {len(ctl.git_cwds)} git/suite calls "
            f"({len(ctl.emitted)} of them module-emitted argv), every cwd "
            "inside the root; the module spawned nothing itself")
        outside_reads = sorted(p for p in AUDIT.reads if not inside(root, p))
        print(f"MODULE READS OUTSIDE THE ROOT: {len(outside_reads)}")
        for path in outside_reads:
            print(f"  {path}")
        print(f"RAW TRANSITIONS: {len(RAW_TRANSITIONS)}")
        grouped: dict = {}
        for transition_id, what, missing in RAW_TRANSITIONS:
            grouped.setdefault(missing, []).append(transition_id)
        for missing, ids in grouped.items():
            print(f"  [{len(ids)}] missing: {missing}")
            print(f"      {', '.join(ids)}")
        print(f"FINDINGS: {len(FINDINGS)}")
        for finding in FINDINGS:
            print(f"  {finding}")
        return 0
    finally:
        if os.environ.get("WALKTHROUGH_KEEP"):
            print(f"kept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
