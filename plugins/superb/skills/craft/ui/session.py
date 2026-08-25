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
    """Raised when another live craft session owns this project directory.

    `pid` is an int when the holder could be identified and None when it could
    not, so a caller may do int(exc.pid) behind a single None check. It is
    never the string "unknown".
    """

    def __init__(self, pid, started_at):
        self.pid = as_pid(pid)
        self.started_at = started_at
        if self.pid is None:
            message = "a craft session owns this project (holder unknown, started {})"
            super().__init__(message.format(started_at))
        else:
            super().__init__(
                "craft session pid {} (started {}) owns this project".format(
                    self.pid, started_at
                )
            )


def as_pid(value):
    """A pid read off disk as an int, or None when it is not one.

    JSON carries whatever the writer put there, so a lock may name its holder
    as the string "1234". That is a pid; "unknown" and None are not.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def pid_alive(pid):
    """Does a process with this pid exist? Never signals it, only asks.

    The int() coercion is load-bearing: a lock whose pid is the JSON string
    "1234" names a live session, and without the coercion this would answer
    "dead" and the lock would be stolen out from under it.
    """
    pid = as_pid(pid)
    if pid is None or pid <= 0:
        # kill(2) reads 0 and negatives as process groups, not processes, so
        # they would otherwise answer "alive" and wedge the project shut.
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True  # exists, owned by someone else
    except (OSError, OverflowError):
        return False
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
        """The lock's contents as a dict, or None if nothing readable is there.

        OSError covers the whole family of ways the path can refuse to be read
        as a file -- missing, a directory, unreadable -- because none of them
        name a holder, and none of them should reach a caller as a traceback.
        """
        try:
            holder = read_json(self.lock_path)
        except (OSError, ValueError):
            return None
        return holder if isinstance(holder, dict) else None

    def _publish_lock(self):
        """Make the lock appear, already holding its payload. True if we won.

        The payload is written to a temp file first and published with a link,
        because os.link refuses a name that exists -- the same exclusivity
        O_CREAT|O_EXCL gave -- while leaving no window in which the lock is
        visible and empty. Creating the lock first and writing it second left
        exactly that window, and a second acquirer arriving inside it read a
        zero-byte file, called it unowned, and took the project.
        """
        payload = {
            "pid": os.getpid(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        fd, tmp = tempfile.mkstemp(
            dir=str(self.craft_dir), prefix=".lock-", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.link(tmp, str(self.lock_path))
            except FileExistsError:
                return False
            return True
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def acquire_lock(self, force=False):
        """Take the session lock. CRAFT.md is rewritten whole every round, so two
        sessions on one project silently lose one session's answers."""
        self.ensure_dirs()
        for _ in range(5):
            if self._publish_lock():
                return
            holder = self._read_lock()
            if holder is not None and not force:
                pid = as_pid(holder.get("pid"))
                if pid_alive(pid):
                    raise LockHeld(pid, holder.get("started_at", "unknown"))
            try:
                os.unlink(str(self.lock_path))
            except FileNotFoundError:
                pass
            except OSError as exc:
                # Something is at that name and it will not go away -- a
                # directory, or a file we may not remove. Refusing names the
                # project as locked, which is what it is.
                raise LockHeld(None, "unknown") from exc
        raise LockHeld(None, "unknown")

    def release_lock(self):
        """Remove the lock, but only if it is ours.

        Best effort by design: shutdown runs whether or not startup got as far
        as taking a lock, and a lock we cannot remove is left for acquire to
        report rather than crashing the way out.
        """
        holder = self._read_lock()
        if holder is None or as_pid(holder.get("pid")) == os.getpid():
            try:
                os.unlink(str(self.lock_path))
            except OSError:
                pass
