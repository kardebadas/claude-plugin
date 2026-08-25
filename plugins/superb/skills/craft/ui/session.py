"""Session directory, atomic writes and round discovery for the craft UI.

The session directory lives beside CRAFT.md in the user's project. Nothing in
this module knows anything about HTTP, and nothing here ever writes CRAFT.md.
"""
# Deliberate: kept so any annotation added later may use `int | None` syntax
# while this project's floor is Python 3.9. Do not delete.
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

ROUND_RE = re.compile(r"^round-([0-9]{3})\.questions\.json\Z")


def write_json_atomic(path, obj):
    """Write obj as JSON so a reader never sees a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path):
    """Read JSON. Raises ValueError (JSONDecodeError) if the file is malformed."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


class LockHeld(Exception):
    """Raised when another live craft session owns this project directory."""

    def __init__(self, pid, started_at):
        self.pid = pid
        self.started_at = started_at
        super().__init__(
            "craft session pid {} (started {}) owns this project".format(pid, started_at)
        )


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


class Session:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir).resolve()
        self.craft_dir = self.project_dir / ".craft"
        self.brief_path = self.project_dir / "CRAFT.md"

    def ensure_dirs(self):
        self.craft_dir.mkdir(parents=True, exist_ok=True)

    def questions_path(self, n):
        return self.craft_dir / "round-{:03d}.questions.json".format(n)

    def draft_path(self, n):
        return self.craft_dir / "round-{:03d}.draft.json".format(n)

    def answers_path(self, n):
        return self.craft_dir / "round-{:03d}.answers.json".format(n)

    def current_round(self):
        """The highest-numbered round the agent has written, or None."""
        if not self.craft_dir.is_dir():
            return None
        found = []
        for entry in self.craft_dir.iterdir():
            match = ROUND_RE.match(entry.name)
            if match and entry.is_file():
                found.append(int(match.group(1)))
        return max(found) if found else None

    def read_brief(self):
        try:
            return self.brief_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    @property
    def lock_path(self):
        return self.craft_dir / "session.lock"

    def _read_lock(self):
        try:
            return read_json(self.lock_path)
        except (FileNotFoundError, ValueError):
            return None

    def acquire_lock(self, force=False):
        """Take the session lock. CRAFT.md is rewritten whole every round, so two
        sessions on one project silently lose one session's answers."""
        self.ensure_dirs()
        for _ in range(5):
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                holder = self._read_lock()
                if holder and pid_alive(holder.get("pid")) and not force:
                    raise LockHeld(holder.get("pid"), holder.get("started_at", "unknown"))
                try:
                    os.unlink(str(self.lock_path))
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "pid": os.getpid(),
                        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                    fh,
                )
            return
        raise LockHeld("unknown", "unknown")

    def release_lock(self):
        """Remove the lock, but only if it is ours."""
        holder = self._read_lock()
        if holder is None or holder.get("pid") == os.getpid():
            try:
                os.unlink(str(self.lock_path))
            except FileNotFoundError:
                pass
