"""Session directory, atomic writes and round discovery for the craft UI.

The session directory lives beside CRAFT.md in the user's project. Nothing in
this module knows anything about HTTP, and nothing here ever writes CRAFT.md.
"""
# Deliberate: kept so any annotation added later may use `int | None` syntax
# while this project's floor is Python 3.9. Do not delete.
from __future__ import annotations

import errno
import json
import os
import re
import tempfile
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # not a Unix
    fcntl = None

try:
    import msvcrt
except ImportError:  # not a Windows
    msvcrt = None

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


# ---------------------------------------------------------------------------
# The lock itself: the kernel owns it, not us.
#
# Liveness used to be inferred from a pid written into the lock file, which
# forced a staleness judgement, which forced a reclaim that unlinked the lock
# by path. Two sessions could reach that unlink over the same file and the
# loser deleted the winner's live lock. Nothing here unlinks the lock file, and
# nothing here judges liveness: an advisory exclusive lock is held on an open
# descriptor for the life of the process, and the kernel drops it when that
# process ends by any means, SIGKILL included. A lock that is held therefore
# means a live holder, always, and the only remedy is to end that process.
# ---------------------------------------------------------------------------

_WOULD_BLOCK = (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES)


def _fcntl_try_lock(fd):
    """True if we now hold fd exclusively; False if another live process does.

    flock(2) locks the open file description rather than the (process, inode)
    pair POSIX record locks use, so closing some *other* descriptor onto the
    same file does not quietly drop this lock -- which is what the refused
    acquirer below does on its way out.
    """
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:  # BlockingIOError is one of these
        if exc.errno in _WOULD_BLOCK:
            return False
        raise
    return True


def _fcntl_unlock(fd):
    fcntl.flock(fd, fcntl.LOCK_UN)


# NEVER EXECUTED. Written to the same contract as the fcntl pair above and
# reviewed by reading only: no Windows interpreter has ever run this project,
# so treat it as unproven. msvcrt.locking works from the current file offset,
# hence the seek -- acquire_lock leaves the offset past the payload it wrote.
def _msvcrt_try_lock(fd):
    """True if we now hold fd exclusively; False if another live process does."""
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _msvcrt_unlock(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def select_lock_impl(fcntl_module, msvcrt_module):
    """The (try_lock, unlock) pair for the modules a platform actually has.

    Selection is by capability rather than by comparing os.name to a string,
    and it is a plain function of its two arguments so that the choice can be
    asserted -- both branches of it -- from whichever platform the suite runs
    on.
    """
    if fcntl_module is not None and hasattr(fcntl_module, "flock"):
        return _fcntl_try_lock, _fcntl_unlock
    if msvcrt_module is not None and hasattr(msvcrt_module, "locking"):
        return _msvcrt_try_lock, _msvcrt_unlock
    raise RuntimeError(
        "no file-locking primitive on this platform: neither fcntl.flock nor "
        "msvcrt.locking is available, so one session per project cannot be "
        "enforced"
    )


_try_lock_exclusive, _unlock = select_lock_impl(fcntl, msvcrt)


class Session:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir).resolve()
        self.craft_dir = self.project_dir / ".craft"
        self.brief_path = self.project_dir / "CRAFT.md"
        # The descriptor the lock lives on. Open for as long as we hold the
        # project, closed only by release_lock or by the process ending.
        self._lock_fd = None

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

        Only ever used to name a holder in a refusal. Nothing decided here
        governs whether the lock is held -- the kernel already answered that.

        OSError covers the whole family of ways the path can refuse to be read
        as a file -- missing, a directory, unreadable -- because none of them
        name a holder, and none of them should reach a caller as a traceback.
        """
        try:
            holder = read_json(self.lock_path)
        except (OSError, ValueError):
            return None
        return holder if isinstance(holder, dict) else None

    def acquire_lock(self):
        """Take the session lock. CRAFT.md is rewritten whole every round, so two
        sessions on one project silently lose one session's answers."""
        self.ensure_dirs()
        try:
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        except OSError as exc:
            # Something is at that name that cannot be opened as a file -- a
            # directory, or a file we may not touch. We cannot hold the
            # project, which is all a caller needs to be told.
            raise LockHeld(None, "unknown") from exc
        try:
            if not _try_lock_exclusive(fd):
                # Reading the file is a courtesy to the message and nothing
                # more; whatever it says, the refusal already stands.
                holder = self._read_lock() or {}
                raise LockHeld(holder.get("pid"), holder.get("started_at", "unknown"))
            payload = {
                "pid": os.getpid(),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            # Truncate first, then write. A refusal landing in the window
            # between the two reads an empty file and names nobody, which is
            # honest; writing over the top without truncating would leave the
            # previous holder's tail behind and could name the wrong process.
            os.ftruncate(fd, 0)
            os.write(fd, json.dumps(payload).encode("utf-8"))
            os.fsync(fd)
        except BaseException:
            os.close(fd)  # also drops the lock, if the failure was after taking it
            raise
        self._lock_fd = fd

    def release_lock(self):
        """Drop the lock if we are holding one, and do nothing if we are not.

        It never unlinks the lock file. Removing a lock by path is what let one
        session delete another's live lock; the file left behind is inert, and
        the next acquire truncates and rewrites it.
        """
        fd = self._lock_fd
        if fd is None:
            return
        self._lock_fd = None
        try:
            _unlock(fd)
        except OSError:
            pass  # closing the descriptor drops the lock regardless
        finally:
            os.close(fd)
