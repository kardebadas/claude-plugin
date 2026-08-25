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

    This means exactly one thing and nothing else: the kernel refused us the
    lock because a live process holds it. Every other way the lock can fail --
    a directory at that name, a mode we may not open, a read-only or full
    filesystem -- is LockUnavailable. Keeping the two apart is not cosmetic.
    A user told "another session owns this, kill pid None" has one obvious
    remedy left, which is to delete the lock file by hand; that is precisely
    the act that puts two live holders on one project (see _is_file_at).

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


def describe_os_error(error):
    """An OSError as a phrase a person can act on, errno name included."""
    if error is None:
        return "reason unknown"
    text = getattr(error, "strerror", None) or str(error)
    number = getattr(error, "errno", None)
    if number is None:
        return text
    name = errno.errorcode.get(number, "errno {}".format(number))
    return "{} ({})".format(text, name)


class LockUnavailable(Exception):
    """Raised when the lock cannot be used at all, for reasons that are not
    contention.

    A directory sitting at the lock's name, a mode that forbids opening it, a
    .craft/ we may not write into, a read-only or a full filesystem: in none
    of those does anybody own the project, so none of them may be reported as
    if somebody did. `error` is the underlying OSError (or None when the
    failure was not one) and `errno` its number, so a caller can discriminate
    without reading the message, and the message names the real cause and the
    path so that a user is pointed at the thing that is actually wrong.
    """

    def __init__(self, path, error=None, reason=None):
        self.path = str(path)
        self.error = error
        self.errno = getattr(error, "errno", None)
        self.reason = describe_os_error(error) if reason is None else reason
        super().__init__(
            "cannot use the craft session lock at {}: {}".format(self.path, self.reason)
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
#
# What the kernel arbitrates, though, is an inode, and every caller here names
# a path. The two can come apart -- see _is_file_at -- so an acquire is not
# finished when the lock is granted; it is finished when the file that was
# locked is shown to be the file the name still points at.
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


# The Windows counterpart of _WOULD_BLOCK. The CRT's _locking sets EACCES for
# "locking violation", which under LK_NBLCK is what contention looks like, and
# EDEADLOCK when a retrying mode gives up -- also contention. EBADF, EINVAL and
# anything else are real failures and must not be reported as an owner.
_WINDOWS_WOULD_BLOCK = (errno.EACCES, errno.EDEADLOCK)

# NEVER EXECUTED. Written to the same contract as the fcntl pair above and
# reviewed by reading only: no Windows interpreter has ever run this project,
# so treat it as unproven. msvcrt.locking works from the current file offset,
# hence the seek -- acquire_lock leaves the offset past the payload it wrote.
#
# Two things a reading of the Windows API establishes that cannot be fixed
# from here, recorded so nobody has to rediscover them:
#
# 1. Windows byte-range locks are MANDATORY, not advisory. A holder that has
#    locked byte 0 makes that byte unreadable to everyone else, so a refused
#    acquirer cannot read the payload naming the holder: LockHeld.pid is
#    always None on Windows, and the refusal can never say whose session it
#    is. The Unix half of that message is not portable and should not be
#    promised in a UI that runs on both.
# 2. Locks still outstanding when a process terminates are released by the OS
#    only "after an indeterminate interval" -- the guarantee is eventual, not
#    immediate. So "a held lock means a live holder" is exact on Unix, where
#    flock is dropped with the last descriptor of the open file description,
#    and approximate on Windows, where a just-killed session may keep the
#    project locked for a short while afterwards.
def _msvcrt_try_lock(fd):
    """True if we now hold fd exclusively; False if another live process does.

    Anything that is not the genuine "already locked" errno is re-raised, the
    same discrimination the fcntl branch makes, so that a bad descriptor or a
    failed seek surfaces as LockUnavailable instead of masquerading as an
    owner nobody can name or kill.
    """
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        if exc.errno in _WINDOWS_WOULD_BLOCK:
            return False
        raise
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


def _lock_or_unavailable(fd, path):
    """_try_lock_exclusive, with everything that is not contention named.

    The primitives re-raise anything outside their would-block set, and every
    one of those is a reason the lock cannot be used rather than a reason
    somebody else has it.
    """
    try:
        return _try_lock_exclusive(fd)
    except OSError as exc:
        raise LockUnavailable(path, exc) from exc


def _is_file_at(fd, path):
    """True if fd still refers to the file that `path` names right now.

    The lock is held on an inode; every caller of this module names it by a
    path. Between the os.open and the lock being granted the name can come to
    mean a different file -- `rm .craft/session.lock`, a `git clean -xdf` over
    a .craft/ this project gitignores by design, or any os.replace of the
    write_json_atomic shape -- and then the lock we were granted guards an
    orphan while somebody else holds the file everybody else is looking at.
    Two live holders on one project, and CRAFT.md is rewritten whole every
    round, so one of them silently loses every answer the other collected.

    Both st_dev and st_ino: inode numbers are only unique within a
    filesystem, and a .craft/ that was removed and recreated may not be on the
    one it was on before.
    """
    try:
        there = os.stat(str(path))
    except OSError:
        return False  # gone, or unreadable -- either way it is not our file
    here = os.fstat(fd)
    return (here.st_dev, here.st_ino) == (there.st_dev, there.st_ino)


def _write_all(fd, payload):
    """Write every byte of payload to fd, however many writes that takes.

    os.write returns how much it wrote and is entitled to write less than it
    was given. Discarding that number truncates the holder's identity, which
    degrades a refusal that should name a pid into one that names nobody.
    """
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, "wrote no bytes to the session lock")
        view = view[written:]


# How many times an acquire will start over because the file at lock_path was
# replaced under it. A single retry covers the ordinary race; a name being
# replaced three times running is something outside this session churning the
# path, and spinning on that would hang a server startup rather than report it.
_LOCK_ATTEMPTS = 3


class Session:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir).resolve()
        self.craft_dir = self.project_dir / ".craft"
        self.brief_path = self.project_dir / "CRAFT.md"
        # The descriptor the lock lives on. Open for as long as we hold the
        # project, closed only by release_lock or by the process ending, and
        # the pid that took it -- see release_lock for why the pid matters.
        self._lock_fd = None
        self._lock_pid = None

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
        sessions on one project silently lose one session's answers.

        Raises LockHeld when a live process holds the project, and
        LockUnavailable when the lock file cannot be used at all.
        """
        for _ in range(_LOCK_ATTEMPTS):
            if self._take_lock_once():
                return
        raise LockUnavailable(
            self.lock_path,
            reason=(
                "the file at that name was replaced by a different file on "
                "each of {} attempts, so the lock could not be pinned to it "
                "-- something outside this session keeps deleting or "
                "replacing it".format(_LOCK_ATTEMPTS)
            ),
        )

    def _take_lock_once(self):
        """One whole attempt: open, lock, and check we locked the right file.

        True when the lock is ours. False when the file we locked turned out
        not to be the one at lock_path any more -- not a failure, just a
        reason to start again from the open. LockHeld and LockUnavailable
        come out of here as themselves.

        The directory is ensured per attempt rather than once: the reason to
        be here twice is that the path was destroyed under us, and `rm -rf
        .craft/` destroys the directory along with it.
        """
        self.ensure_dirs()
        fd = self._open_lock_file()
        try:
            if not _lock_or_unavailable(fd, self.lock_path):
                # Reading the file is a courtesy to the message and nothing
                # more; whatever it says, the refusal already stands.
                holder = self._read_lock() or {}
                raise LockHeld(holder.get("pid"), holder.get("started_at", "unknown"))
            ours = _is_file_at(fd, self.lock_path)
            if ours:
                self._write_holder(fd)
                # Both assignments inside the try, and the pid before the
                # descriptor: an interrupt on that boundary must never leave
                # the lock held on an fd nothing tracks, because release_lock
                # would then be a no-op and this process would be locked out
                # by itself for as long as it lives. _lock_fd is the flag
                # release_lock reads, so it goes last.
                self._lock_pid = os.getpid()
                self._lock_fd = fd
        except BaseException:
            os.close(fd)  # also drops the lock, if the failure was after taking it
            raise
        if not ours:
            # We hold a lock on a file nobody can reach by that name any more.
            # Dropping it and starting over is what stops us from sitting on
            # an orphan while another session holds the real one.
            os.close(fd)
        return ours

    def _open_lock_file(self):
        try:
            return os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        except OSError as exc:
            # A directory at that name, a mode we may not open, a read-only or
            # a full filesystem. Nobody owns the project in any of those, and
            # saying somebody does sends the user to delete the lock file.
            raise LockUnavailable(self.lock_path, exc) from exc

    def _write_holder(self, fd):
        """Record who we are in the file, for the sake of somebody's refusal."""
        payload = {
            "pid": os.getpid(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            # Truncate first, then write. A refusal landing in the window
            # between the two reads an empty file and names nobody, which is
            # honest; writing over the top without truncating would leave the
            # previous holder's tail behind and could name the wrong process.
            os.ftruncate(fd, 0)
            _write_all(fd, json.dumps(payload).encode("utf-8"))
            os.fsync(fd)
        except OSError as exc:
            raise LockUnavailable(self.lock_path, exc) from exc

    def release_lock(self):
        """Drop the lock if we are holding one, and do nothing if we are not.

        It never unlinks the lock file. Removing a lock by path is what let one
        session delete another's live lock; the file left behind is inert, and
        the next acquire truncates and rewrites it.

        A process that is not the one that took the lock does nothing here,
        and does not treat that as an error. fork() copies this object and
        shares the open file description the lock lives on, so LOCK_UN through
        the child's copy would free the *parent's* lock while the parent went
        on believing it held the project. Nothing forks today -- the server is
        threaded -- but a released lock nobody released is not a failure any
        test downstream of that would attribute to the right cause.
        """
        fd = self._lock_fd
        if fd is None:
            return
        if self._lock_pid != os.getpid():
            return
        self._lock_fd = None
        self._lock_pid = None
        try:
            _unlock(fd)
        except OSError:
            pass  # closing the descriptor drops the lock regardless
        finally:
            os.close(fd)
