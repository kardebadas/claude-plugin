import calendar
import contextlib
import errno
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import weakref
from pathlib import Path
from unittest import mock

import session
from session import (
    ROUND_RE,
    LockHeld,
    LockUnavailable,
    Session,
    read_json,
    write_json_atomic,
)


def _mkstemp_dir(args, kwargs):
    """tempfile.mkstemp's dir argument, however the caller chose to pass it.

    Keyword or third positional are the same behaviour, so the test must not
    care which one a refactor picks.
    """
    if "dir" in kwargs:
        return kwargs["dir"]
    return args[2] if len(args) > 2 else None


@contextlib.contextmanager
def _default_encoding_is_not_utf8():
    """Stand in for a machine whose default text encoding is not UTF-8.

    A read_text() or an os.fdopen() that forgot to name its encoding is
    invisible here, because this machine's locale is UTF-8 -- and setting
    LC_ALL=C does not expose it either, since CPython auto-enables UTF-8 mode
    under the C locale. Both are accidents of where the suite runs; a Windows
    cp1252 box, or any non-UTF-8 locale Python does not coerce, would turn the
    same characters into different bytes. Substituting the fallback pins the
    contract wherever the suite runs, on the write side as well as the read
    side -- a file written in the wrong encoding is corrupt for good, which is
    the worse of the two failures.
    """
    real_read_text = Path.read_text
    real_fdopen = os.fdopen

    def read_text(self, encoding=None, *args, **kwargs):
        return real_read_text(self, encoding or "latin-1", *args, **kwargs)

    def fdopen(fd, *args, **kwargs):
        mode = kwargs.get("mode", args[0] if args else "r")
        named = "encoding" in kwargs or len(args) > 2
        if "b" not in mode and not named:
            kwargs["encoding"] = "latin-1"
        return real_fdopen(fd, *args, **kwargs)

    with mock.patch.object(Path, "read_text", read_text), \
            mock.patch.object(os, "fdopen", fdopen):
        yield


class SessionPathsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.s = Session(self.root)
        self.s.ensure_dirs()

    def tearDown(self):
        self._tmp.cleanup()

    def _round(self, n):
        write_json_atomic(self.s.questions_path(n), {"round": n, "questions": []})

    def test_craft_dir_is_beside_the_brief(self):
        self.assertEqual(self.s.craft_dir, self.root.resolve() / ".craft")
        self.assertEqual(self.s.brief_path, self.root.resolve() / "CRAFT.md")

    def test_a_non_canonical_project_dir_is_resolved(self):
        (self.root / "sub").mkdir()
        s = Session(Path(self.root) / "sub" / "..")
        self.assertEqual(s.craft_dir, self.root.resolve() / ".craft")
        self.assertEqual(s.brief_path, self.root.resolve() / "CRAFT.md")

    def test_paths_are_zero_padded_to_three_digits(self):
        self.assertEqual(self.s.questions_path(2).name, "round-002.questions.json")
        self.assertEqual(self.s.draft_path(12).name, "round-012.draft.json")
        self.assertEqual(self.s.answers_path(7).name, "round-007.answers.json")

    def test_current_round_is_none_when_no_rounds_exist(self):
        self.assertIsNone(self.s.current_round())

    def test_current_round_is_the_highest_number(self):
        self._round(1)
        self._round(2)
        self.assertEqual(self.s.current_round(), 2)

    def test_a_gap_in_numbering_does_not_break_discovery(self):
        self._round(1)
        self._round(3)
        self.assertEqual(self.s.current_round(), 3)

    def test_non_question_files_are_ignored(self):
        self._round(1)
        write_json_atomic(self.s.answers_path(9), {"round": 9})
        write_json_atomic(self.s.draft_path(9), {"round": 9})
        (self.s.craft_dir / "round-abc.questions.json").write_text("{}")
        self.assertEqual(self.s.current_round(), 1)

    def test_current_round_is_none_when_the_craft_dir_does_not_exist(self):
        """A project that has never had a round is a normal state, not an error:
        callers ask before anything has been written."""
        fresh = Session(self.root / "never-used")
        self.assertFalse(fresh.craft_dir.exists())
        self.assertIsNone(fresh.current_round())

    def test_names_outside_the_round_grammar_are_ignored(self):
        """The filename grammar is a contract: anchored at both ends, exactly
        three digits, and literal dots."""
        strays = [
            "round-002.questions.json.bak",
            "round-2.questions.json",
            "round-0002.questions.json",
            "round-002xquestionsxjson",
            "xround-002.questions.json",
        ]
        for name in strays:
            (self.s.craft_dir / name).write_text("{}", encoding="utf-8")
            self.assertIsNone(
                ROUND_RE.match(name), "{} should not match ROUND_RE".format(name)
            )
        self.assertIsNone(self.s.current_round())

    def test_write_leaves_no_temp_files_behind(self):
        """Named exactly, not filtered by prefix: a refactor free to rename the
        temp file is not free to leave one behind."""
        self._round(1)
        self.assertEqual(
            sorted(p.name for p in self.s.craft_dir.iterdir()),
            ["round-001.questions.json"],
        )

    def test_write_goes_through_a_same_dir_temp_file_and_os_replace(self):
        """The atomicity guarantee itself: a temp file in the destination's own
        directory (so the rename is same-filesystem) swapped in by os.replace.
        A plain path.write_text() implementation fails this test."""
        path = self.s.questions_path(4)
        real_mkstemp = session.tempfile.mkstemp
        real_replace = session.os.replace
        calls = {}

        def recording_mkstemp(*args, **kwargs):
            fd, tmp = real_mkstemp(*args, **kwargs)
            calls["mkstemp"] = (args, kwargs)
            calls["tmp"] = tmp
            return fd, tmp

        def recording_replace(src, dst):
            calls["replace"] = (src, dst)
            return real_replace(src, dst)

        with mock.patch("session.tempfile.mkstemp", recording_mkstemp), \
                mock.patch("session.os.replace", recording_replace):
            write_json_atomic(path, {"round": 4})

        self.assertIn("mkstemp", calls, "no temp file was created")
        args, kwargs = calls["mkstemp"]
        self.assertEqual(str(_mkstemp_dir(args, kwargs)), str(path.parent))
        self.assertIn("replace", calls, "os.replace was never called")
        src, dst = calls["replace"]
        self.assertEqual(str(src), calls["tmp"])
        self.assertEqual(str(dst), str(path))
        self.assertEqual(read_json(path), {"round": 4})

    def test_a_failed_write_leaves_the_destination_untouched(self):
        path = self.s.questions_path(5)
        path.write_text('{"round": 5}', encoding="utf-8")
        with self.assertRaises(TypeError):
            write_json_atomic(path, {"bad": object()})
        self.assertEqual(path.read_text(encoding="utf-8"), '{"round": 5}')
        self.assertEqual(
            sorted(p.name for p in self.s.craft_dir.iterdir()),
            ["round-005.questions.json"],
        )

    def test_write_then_read_round_trips(self):
        write_json_atomic(self.s.questions_path(1), {"round": 1, "note": "café ☕"})
        self.assertEqual(read_json(self.s.questions_path(1))["note"], "café ☕")

    def test_unicode_is_written_literally_and_not_escaped(self):
        path = self.s.questions_path(6)
        write_json_atomic(path, {"note": "café ☕"})
        raw = path.read_text(encoding="utf-8")
        self.assertIn("café ☕", raw)
        self.assertNotIn("\\u", raw)
        self.assertEqual(json.loads(raw)["note"], "café ☕")

    def test_read_json_raises_value_error_on_bad_json(self):
        self.s.questions_path(1).write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_json(self.s.questions_path(1))

    def test_read_brief_is_empty_string_when_missing(self):
        self.assertEqual(self.s.read_brief(), "")

    def test_read_brief_returns_the_file(self):
        self.s.brief_path.write_text("# Vision\n", encoding="utf-8")
        self.assertEqual(self.s.read_brief(), "# Vision\n")

    def test_write_creates_the_missing_parent_directories(self):
        """Callers hand over a path, not a prepared directory tree."""
        path = self.root / "a" / "b" / "c" / "round-001.questions.json"
        self.assertFalse(path.parent.exists())
        write_json_atomic(path, {"round": 1})
        self.assertTrue(path.is_file())
        self.assertEqual(read_json(path), {"round": 1})

    def test_read_json_decodes_utf8_whatever_the_locale_is(self):
        path = self.s.questions_path(8)
        path.write_bytes('{"note": "café ☕"}'.encode("utf-8"))
        with _default_encoding_is_not_utf8():
            self.assertEqual(read_json(path)["note"], "café ☕")

    def test_read_brief_decodes_utf8_whatever_the_locale_is(self):
        self.s.brief_path.write_bytes("# Café ☕\n".encode("utf-8"))
        with _default_encoding_is_not_utf8():
            self.assertEqual(self.s.read_brief(), "# Café ☕\n")

    def test_read_brief_propagates_errors_that_are_not_a_missing_file(self):
        """An unreadable brief is a real failure. Only its absence is empty."""
        self.s.brief_path.write_text("# Vision\n", encoding="utf-8")
        with mock.patch("pathlib.Path.read_text", side_effect=PermissionError("nope")):
            with self.assertRaises(PermissionError):
                self.s.read_brief()

    def test_write_encodes_utf8_whatever_the_locale_is(self):
        """The mirror of the read-side test, and the more damaging half: bytes
        written under a cp1252 default are wrong on disk permanently."""
        path = self.s.questions_path(9)
        with _default_encoding_is_not_utf8():
            write_json_atomic(path, {"note": "café"})
        raw = path.read_bytes()
        self.assertIn("café".encode("utf-8"), raw)
        self.assertEqual(json.loads(raw.decode("utf-8"))["note"], "café")

    def test_writing_a_path_again_replaces_what_was_there(self):
        """Overwriting is the normal case, not the exception -- the draft file
        is rewritten every time the user types."""
        path = self.s.draft_path(1)
        write_json_atomic(path, {"round": 1, "text": "first"})
        write_json_atomic(path, {"round": 1, "text": "second"})
        self.assertEqual(read_json(path), {"round": 1, "text": "second"})
        self.assertEqual(
            sorted(p.name for p in self.s.craft_dir.iterdir()),
            ["round-001.draft.json"],
        )

    def test_ensure_dirs_may_be_called_again_on_a_session_that_has_one(self):
        """A server calls it on startup and may call it again per request."""
        self.assertTrue(self.s.craft_dir.is_dir())
        self.s.ensure_dirs()
        self.s.ensure_dirs()
        self.assertTrue(self.s.craft_dir.is_dir())

    def test_ensure_dirs_creates_every_missing_level_of_the_path(self):
        """A project dir several levels below anything that exists is still a
        project dir."""
        deep = Session(self.root / "a" / "b" / "c")
        self.assertFalse(deep.project_dir.exists())
        deep.ensure_dirs()
        self.assertTrue(deep.craft_dir.is_dir())

    def test_the_round_grammar_is_anchored_at_the_start_of_the_name(self):
        """ROUND_RE is exported, so a later consumer may reach for .search or
        .findall. The anchor has to do the work, not re.match's own rule that
        it only ever tries position zero."""
        self.assertIsNone(ROUND_RE.search("xround-002.questions.json"))
        self.assertIsNone(ROUND_RE.search("backup/round-002.questions.json"))
        self.assertIsNotNone(ROUND_RE.search("round-002.questions.json"))

    def test_a_string_path_is_accepted_by_both_entry_points(self):
        """Callers hand over whatever they are holding; str is contract."""
        path = self.s.questions_path(3)
        write_json_atomic(str(path), {"round": 3})
        self.assertTrue(path.is_file())
        self.assertEqual(read_json(str(path)), {"round": 3})

    def test_only_ascii_digits_are_round_numbers(self):
        """Three digits means 0-9, and nothing else.

        \\d also accepts Unicode digits, so an Arabic-Indic 002 would otherwise
        be read as round 2. The names are checked directly rather than written
        to disk: under a non-UTF-8 filesystem encoding they are not creatable
        filenames at all.
        """
        self.assertIsNone(ROUND_RE.match("round-\u0660\u0660\u0662.questions.json"))
        self.assertIsNone(ROUND_RE.match("round-\u07c0\u07c0\u07c2.questions.json"))
        self.assertIsNotNone(ROUND_RE.match("round-002.questions.json"))

    def test_a_trailing_newline_is_not_part_of_the_round_grammar(self):
        """$ also matches immediately before a trailing newline, so under it a
        file named "round-002.questions.json\\n" was read as round 2. \\Z is the
        end of the string and nothing else. Nothing in the system produces such
        a name; the grammar should still say what it means."""
        name = "round-002.questions.json\n"
        self.assertIsNone(ROUND_RE.match(name))
        self.assertIsNone(ROUND_RE.search(name))
        self.assertIsNotNone(ROUND_RE.match("round-002.questions.json"))
        try:
            (self.s.craft_dir / name).write_text("{}", encoding="utf-8")
        except (OSError, ValueError) as exc:
            self.skipTest(
                "this filesystem will not hold a newline in a name: {}".format(exc)
            )
        self.assertIsNone(self.s.current_round())
        self._round(1)
        self.assertEqual(self.s.current_round(), 1)

    def test_a_directory_named_like_a_round_is_not_a_round(self):
        """current_round() reports rounds that were written, and a directory is
        not something anyone wrote a round into."""
        (self.s.craft_dir / "round-005.questions.json").mkdir()
        self.assertIsNone(self.s.current_round())
        self._round(1)
        self.assertEqual(self.s.current_round(), 1)


_UI_DIR = Path(session.__file__).resolve().parent

# A whole craft session in another process: it announces itself, waits to be
# released, tries the lock, reports what happened, and then holds whatever it
# got until the parent says stop. Every step is a line in each direction, so
# the tests below rendezvous on real I/O and never sleep for a duration.
_CHILD_SOURCE = """\
import os
import sys

sys.path.insert(0, sys.argv[1])
from session import LockHeld, Session


def say(text):
    sys.stdout.write(text + "\\n")
    sys.stdout.flush()


def wait_for_parent():
    if not sys.stdin.readline():
        raise SystemExit(0)


s = Session(sys.argv[2])
say("ready")
wait_for_parent()
try:
    s.acquire_lock()
    say("won {}".format(os.getpid()))
except LockHeld as exc:
    say("refused {}".format(exc.pid))
wait_for_parent()
"""


class _LockChild:
    """A craft session in a real OS process, driven one line at a time."""

    # A bound on a hang, never a wait for a result: every line this class asks
    # for is one the child writes immediately or not at all. An implementation
    # that blocks on the lock instead of refusing it trips this rather than
    # wedging the suite.
    TIMEOUT = 30

    def __init__(self, project_dir):
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _CHILD_SOURCE, str(_UI_DIR), str(project_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            universal_newlines=True,
        )
        self._lines = queue.Queue()
        self._reader = threading.Thread(target=self._pump)
        self._reader.daemon = True
        self._reader.start()

    def _pump(self):
        # stop() may close the pipe under this thread, which is a normal end
        # to it and not something to print a traceback about.
        try:
            for line in self.proc.stdout:
                self._lines.put(line.rstrip("\n"))
        except (OSError, ValueError):
            pass
        self._lines.put(None)

    def line(self):
        """The child's next line, or an assertion failure explaining silence."""
        try:
            line = self._lines.get(timeout=self.TIMEOUT)
        except queue.Empty:
            raise AssertionError(
                "child {} said nothing in {}s -- it is blocked, not refused".format(
                    self.proc.pid, self.TIMEOUT
                )
            )
        if line is None:
            raise AssertionError(
                "child {} exited without answering".format(self.proc.pid)
            )
        return line

    def release(self):
        """Let the child past its next rendezvous."""
        try:
            self.proc.stdin.write("go\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise AssertionError(
                "child {} is gone, so it cannot be released: {}".format(
                    self.proc.pid, exc
                )
            )

    def kill(self):
        """SIGKILL, and reap. On return the kernel has dropped its lock."""
        self.proc.kill()
        self.proc.wait()

    def stop(self):
        """Reap it whatever state it is in. Idempotent, and never raises."""
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        try:
            self.proc.wait(timeout=self.TIMEOUT)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


def _dead_pid():
    """A pid that names nothing: a child run to completion and reaped.

    Nothing here may name it as a holder, so several tests need one, and a
    number picked out of the air is not one -- it might be in use.
    """
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _rewrite_in_place(path, text):
    """Replace a file's bytes without replacing the file.

    write_json_atomic puts a *new* inode at the name, and a new inode carries
    none of the old one's locks. A test that wants the lock file to say
    something else while its holder still holds it has to write through the
    same file.
    """
    fd = os.open(str(path), os.O_WRONLY | os.O_TRUNC)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


class SessionLockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()
        self._sessions = [self.s]

    def tearDown(self):
        for s in self._sessions:
            s.release_lock()
        self._tmp.cleanup()

    def _session(self):
        """Another session on this project, released however the test ends."""
        s = Session(self.s.project_dir)
        self._sessions.append(s)
        return s

    def test_acquiring_writes_our_pid(self):
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_a_live_lock_is_refused(self):
        self.s.acquire_lock()
        with self.assertRaises(LockHeld) as caught:
            self._session().acquire_lock()
        self.assertEqual(caught.exception.pid, os.getpid())
        self.assertTrue(caught.exception.started_at)

    def test_a_second_session_on_one_project_in_one_process_is_refused(self):
        """Two Session objects, two os.open calls, two open file descriptions
        -- so the kernel arbitrates this exactly as it would between two
        processes, and an implementation that only compares pids to its own
        would let the second one through."""
        first = self._session()
        second = self._session()
        first.acquire_lock()
        with self.assertRaises(LockHeld):
            second.acquire_lock()

    def test_a_refused_acquire_does_not_drop_the_lock_it_was_refused_by(self):
        """The refused acquirer closes its own descriptor on the way out.

        With POSIX record locks that close would release the *holder's* lock
        too, because those are keyed on (process, inode) -- and the project
        would come unlocked the moment anyone was told it was locked. flock is
        keyed on the open file description, so it does not. A third acquire
        still being refused is what proves it.
        """
        self.s.acquire_lock()
        with self.assertRaises(LockHeld):
            self._session().acquire_lock()
        with self.assertRaises(LockHeld):
            self._session().acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_a_refused_acquire_leaks_no_file_descriptor(self):
        """The server refuses, reports, and keeps running. A descriptor left
        open per refusal is a slow leak nothing else here would notice."""
        fd_dir = Path("/proc/self/fd")
        if not fd_dir.is_dir():
            self.skipTest("no /proc/self/fd on this platform to count against")
        self.s.acquire_lock()
        before = len(os.listdir(str(fd_dir)))
        for _ in range(20):
            with self.assertRaises(LockHeld):
                self._session().acquire_lock()
        self.assertEqual(len(os.listdir(str(fd_dir))), before)

    def test_release_then_acquire_again_works(self):
        self.s.acquire_lock()
        self.s.release_lock()
        other = self._session()
        other.acquire_lock()  # must not raise
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_releasing_a_session_that_never_acquired_does_nothing(self):
        never = self._session()
        never.release_lock()
        never.release_lock()
        self.assertFalse(self.s.lock_path.exists())
        self.s.acquire_lock()  # must not raise

    def test_release_leaves_a_lock_file_it_never_took_alone(self):
        """Shutdown of a session that never got the lock must not reach into
        the file, because the session that did get it is still using it."""
        self.s.acquire_lock()
        refused = self._session()
        with self.assertRaises(LockHeld):
            refused.acquire_lock()
        refused.release_lock()
        self.assertTrue(self.s.lock_path.is_file())
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())
        with self.assertRaises(LockHeld):
            self._session().acquire_lock()

    def test_the_lock_file_is_still_there_after_a_release(self):
        """Nothing in this module unlinks the lock file, ever.

        Removing a lock by path is the bug this design deletes: two sessions
        could each judge one file removable, and the loser's unlink deleted the
        winner's live lock. The file left behind is inert -- the next acquire
        truncates and rewrites it -- and the acquire below proves it is not in
        anybody's way.
        """
        self.s.acquire_lock()
        self.s.release_lock()
        self.assertTrue(self.s.lock_path.is_file())
        self._session().acquire_lock()  # must not raise
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_a_lock_file_nobody_holds_is_taken_whatever_it_says(self):
        """The file is data, not the lock. Corrupt, empty, half-written or
        naming a process that never existed, it holds nobody out -- the kernel
        was asked, and the kernel said the lock is free."""
        leftovers = [
            "{not json",
            "",
            json.dumps({"started_at": "old"}),
            json.dumps({"pid": 0, "started_at": "old"}),
            json.dumps({"pid": "unknown", "started_at": "old"}),
            json.dumps([1, 2, 3]),
        ]
        for leftover in leftovers:
            with self.subTest(leftover=leftover):
                self.s.release_lock()
                self.s.lock_path.write_text(leftover, encoding="utf-8")
                self.s.acquire_lock()
                self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())


class SessionLockAcrossProcessesTest(unittest.TestCase):
    """The lock's real subject: separate OS processes on one project.

    Nothing here interleaves anything by hand. The children are real, they
    rendezvous on pipes, and they are reaped however the test ends.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()
        self._children = []

    def tearDown(self):
        for child in self._children:
            child.stop()
        self.s.release_lock()
        self._tmp.cleanup()

    def _child(self):
        child = _LockChild(self.s.project_dir)
        self._children.append(child)
        return child

    @staticmethod
    def _dead_pid():
        return _dead_pid()

    def _holding_child(self):
        """A child that has the lock and is sitting on it."""
        child = self._child()
        self.assertEqual(child.line(), "ready")
        child.release()
        outcome = child.line()
        self.assertTrue(
            outcome.startswith("won"), "the first child was refused: {}".format(outcome)
        )
        return child

    def test_exactly_one_of_two_racing_processes_wins(self):
        """Both children reach the lock before either has finished with it.

        They are started, they both announce themselves, and only then are
        both released -- so the loser's attempt lands while the winner is
        still holding, which is the only arrangement in which "one wins" means
        anything. The winner holds until this test is over.

        The loser may land inside the winner's own acquire, between the lock
        being granted and the payload being written, and then there is nobody
        on disk to name. That is why the refusal is asserted here and the
        naming is asserted separately, against a holder that has settled.
        """
        children = [self._child(), self._child()]
        for child in children:
            self.assertEqual(child.line(), "ready")
        for child in children:
            child.release()
        outcomes = [child.line() for child in children]

        won = [o for o in outcomes if o.startswith("won")]
        refused = [o for o in outcomes if o.startswith("refused")]
        self.assertEqual(len(won), 1, "outcomes were {}".format(outcomes))
        self.assertEqual(len(refused), 1, "outcomes were {}".format(outcomes))

        winner_pid = int(won[0].split()[1])
        self.assertIn(
            refused[0],
            ("refused {}".format(winner_pid), "refused None"),
            "the loser was refused by somebody other than the winner",
        )
        self.assertEqual(read_json(self.s.lock_path)["pid"], winner_pid)

        # And this process is refused too, for as long as the winner lives.
        with self.assertRaises(LockHeld):
            self.s.acquire_lock()

    def test_killing_the_holder_releases_the_lock(self):
        """SIGKILL runs no shutdown code, writes no file and leaves the lock
        file exactly where it was. The kernel drops the lock anyway, which is
        the whole reason liveness is no longer inferred from a pid."""
        child = self._holding_child()
        holder_pid = read_json(self.s.lock_path)["pid"]
        self.assertEqual(holder_pid, child.proc.pid)
        child.kill()

        self.assertTrue(self.s.lock_path.is_file())
        self.assertEqual(read_json(self.s.lock_path)["pid"], holder_pid)
        self.s.acquire_lock()  # no reclaim, no cleanup, no force
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_a_dead_pid_in_the_file_does_not_open_a_live_holders_lock(self):
        """The regression test for the unlink-by-path bug.

        The file says a process that no longer exists owns the project, while
        a live process holds the kernel lock on that very file. The old
        implementation read the pid, judged the lock stale, unlinked it and
        took the project -- deleting a live session's lock. Nothing about the
        file's contents may override what the kernel says.
        """
        child = self._holding_child()
        _rewrite_in_place(
            self.s.lock_path,
            json.dumps({"pid": self._dead_pid(), "started_at": "old"}),
        )
        with self.assertRaises(LockHeld):
            self.s.acquire_lock()
        # Not taken, and not tampered with: the holder is still the holder.
        with self.assertRaises(LockHeld):
            self.s.acquire_lock()
        self.assertTrue(self.s.lock_path.is_file())
        child.stop()

    def test_a_lock_held_by_another_live_process_is_refused(self):
        """The refusal, with a holder that is genuinely somebody else -- so it
        cannot pass by accident on a check that compares pids to our own."""
        child = self._holding_child()
        with self.assertRaises(LockHeld) as caught:
            self.s.acquire_lock()
        self.assertEqual(caught.exception.pid, child.proc.pid)
        self.assertEqual(read_json(self.s.lock_path)["pid"], child.proc.pid)

    def test_the_refusal_names_the_holders_pid_and_start_time(self):
        """The message is the whole user-facing value of the refusal: it is
        how someone finds the other session and decides whether to end it."""
        child = self._holding_child()
        on_disk = read_json(self.s.lock_path)
        with self.assertRaises(LockHeld) as caught:
            self.s.acquire_lock()
        self.assertEqual(caught.exception.pid, child.proc.pid)
        self.assertEqual(caught.exception.started_at, on_disk["started_at"])
        message = str(caught.exception)
        self.assertIn(str(child.proc.pid), message)
        self.assertIn(on_disk["started_at"], message)

    def test_a_string_pid_on_disk_is_reported_as_an_int(self):
        """LockHeld declares pid: int, and the file may name its holder as the
        JSON string "1234" -- hand-edited, or written by some other tool. The
        holder is refused either way, and the pid a caller reads off the
        exception is still something int() has already been applied to."""
        child = self._holding_child()
        _rewrite_in_place(
            self.s.lock_path,
            json.dumps({"pid": str(child.proc.pid), "started_at": "old"}),
        )
        with self.assertRaises(LockHeld) as caught:
            self.s.acquire_lock()
        self.assertIsInstance(caught.exception.pid, int)
        self.assertEqual(caught.exception.pid, child.proc.pid)
        self.assertIn(str(child.proc.pid), str(caught.exception))

    def test_the_refusal_reports_no_pid_when_the_lock_file_is_unreadable(self):
        """The kernel says held; the file says nothing legible. The refusal
        still stands, and pid is None rather than the string "unknown", so a
        caller reaching for int(exc.pid) behind a None check does not choke."""
        child = self._holding_child()
        _rewrite_in_place(self.s.lock_path, "{not json")
        with self.assertRaises(LockHeld) as caught:
            self.s.acquire_lock()
        self.assertIsNone(caught.exception.pid)
        self.assertIn("unknown", str(caught.exception))
        child.stop()

    def test_a_holder_that_exits_cleanly_frees_the_project(self):
        """The ordinary end of a session, from the outside: the child returns
        from its last rendezvous and exits, and the project is free."""
        child = self._holding_child()
        child.release()
        child.stop()
        self.assertEqual(child.proc.returncode, 0)
        self.s.acquire_lock()  # must not raise
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())


class RefusalNamesTheHolderTest(unittest.TestCase):
    """What a refusal is allowed to say about who is holding the project.

    The refusal is the only thing a user sees, and what it says decides what
    they do next. Told a pid, they look for that session. Told nothing, or
    told a pid that is not running, the one remedy left is to delete the lock
    file by hand -- which is exactly how two live sessions end up on one
    project, each rewriting CRAFT.md whole.

    So the message has three obligations, and each is a test here: read again
    when the winner has not written itself down yet, never name a process that
    is not running, and never leave the file as the only thing left to try.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()
        self._sessions = [self.s]

    def tearDown(self):
        for s in self._sessions:
            s.release_lock()
        self._tmp.cleanup()

    def _session(self):
        s = Session(self.s.project_dir)
        self._sessions.append(s)
        return s

    def test_a_refusal_waits_for_the_winner_to_write_down_who_it_is(self):
        """The window every double-launch lands in.

        The kernel grants the lock before the winner truncates, writes and
        fsyncs its payload, so a loser refused in that window reads an empty
        file -- or, since nothing ever unlinks it, the previous holder. One
        read is the wrong instrument: measured over 240 contended acquires it
        named the live holder 4.6% of the time. The file is made to arrive
        late here, and the refusal still has to name the process that has it.
        """
        self.s.acquire_lock()
        real_read = Session._read_lock
        reads = []

        def late(inner):
            reads.append(True)
            if len(reads) < 4:
                return None  # the winner has not got to its write yet
            return real_read(inner)

        with mock.patch.object(Session, "_read_lock", late):
            with self.assertRaises(LockHeld) as caught:
                self._session().acquire_lock()

        self.assertGreaterEqual(len(reads), 4, "the lock file was read only once")
        self.assertEqual(caught.exception.pid, os.getpid())
        self.assertEqual(
            caught.exception.started_at, read_json(self.s.lock_path)["started_at"]
        )
        self.assertIn(str(os.getpid()), str(caught.exception))

    def test_a_refusal_stops_reading_rather_than_waiting_for_a_holder(self):
        """Bounded, and bounded by a number rather than by patience.

        A holder that never writes a payload is a real state -- it may have
        been killed between the lock and the write, and the lock file it left
        behind stays empty forever. A server startup that never returns is
        worse than one that says it cannot name the holder, so the reading is
        counted out and the refusal goes ahead without a name.
        """
        reads = []

        def never(inner):
            reads.append(True)
            return None

        # Asserted before anything is run, so that a bound raised to something
        # absurd fails this test rather than sitting in it for ten minutes.
        self.assertLessEqual(
            session._HOLDER_READ_ATTEMPTS, 32, "a refusal has to be prompt"
        )
        self.assertLessEqual(session._HOLDER_READ_BACKOFF_CAP, 0.25)
        self.s.acquire_lock()
        started = time.time()
        with mock.patch.object(Session, "_read_lock", never):
            with self.assertRaises(LockHeld) as caught:
                self._session().acquire_lock()
        elapsed = time.time() - started

        self.assertEqual(len(reads), session._HOLDER_READ_ATTEMPTS)
        self.assertLess(elapsed, 2.0, "the refusal waited far longer than its bound")
        self.assertIsNone(caught.exception.pid)
        self.assertIn("unknown", str(caught.exception))

    def test_a_refusal_never_names_a_process_that_is_not_running(self):
        """Nothing unlinks the lock file, so the pid in it is the previous
        holder's until the current one overwrites it -- and a user sent to
        find a process that exited last week is a user who deletes the lock
        file. Liveness decides only whether the message may say the name; the
        lock is held either way, and the refusal stands either way.
        """
        self.s.acquire_lock()
        dead = _dead_pid()
        _rewrite_in_place(
            self.s.lock_path, json.dumps({"pid": dead, "started_at": "last week"})
        )
        with self.assertRaises(LockHeld) as caught:
            self._session().acquire_lock()
        self.assertIsNone(caught.exception.pid)
        self.assertNotIn(str(dead), str(caught.exception))
        self.assertNotIn("last week", str(caught.exception))
        self.assertIn("unknown", str(caught.exception))

    def test_liveness_never_decides_who_owns_the_lock(self):
        """The distinction that two earlier designs died on.

        A dead pid in the file used to mean the lock was stale, which meant a
        reclaim, which meant an unlink by path, which meant one session
        deleting another's live lock. The file now says a corpse owns the
        project while a live session holds it, and the answer is still no.
        """
        self.s.acquire_lock()
        _rewrite_in_place(
            self.s.lock_path, json.dumps({"pid": _dead_pid(), "started_at": "old"})
        )
        with self.assertRaises(LockHeld):
            self._session().acquire_lock()
        self.assertTrue(self.s.lock_path.is_file())
        self.assertTrue(self.s.verify_lock_still_ours())

    def test_a_refusal_offers_a_remedy_that_is_not_the_lock_file(self):
        """Both messages, since the unknown one is the usual one.

        A user acts on the sentence. It has to leave them with something to do
        that is not reaching for the file, so it names the session and not the
        path -- and the unknown one says the honest thing, which is that the
        other session is probably still starting up.
        """
        unknown = str(LockHeld(None, "unknown"))
        named = str(LockHeld(4321, "2026-08-25T09:00:00Z"))
        for message in (unknown, named):
            lowered = message.lower()
            for word in ("rm ", "delete", "remove", "unlink", "session.lock", "kill"):
                self.assertNotIn(
                    word,
                    lowered,
                    "{!r} sends the user at the lock file".format(message),
                )
            self.assertIn("close", lowered)
            self.assertIn("wait", lowered)
        self.assertIn("starting up", unknown)
        self.assertIn("4321", named)


class ContendedRefusalTest(unittest.TestCase):
    """The refusal a double-launch actually produces, measured not asserted.

    Every other refusal test establishes the holder first and asks afterwards,
    which is the one arrangement in which the payload is always already on
    disk -- and it is why a message that was wrong most of the time survived a
    suite of ninety-seven tests. Here the two sessions are started together,
    so the loser is refused while the winner is still between being granted
    the lock and writing down who it is.

    The project directory is deliberately reused across rounds. Nothing
    unlinks the lock file, so from the second round on it holds a pid that has
    since exited, and a refusal that reports whatever it reads names a corpse.
    Measured over 240 rounds before this was fixed: 4.6% named the live
    holder, 65.8% named nobody, 29.6% named a dead pid.
    """

    # Enough rounds that a message which names the holder by luck cannot pass,
    # and few enough to keep the suite under a second of process churn.
    ROUNDS = 16
    # Every round must be truthful. The majority is about the retry working at
    # all, and is set well below what a fixed implementation does (16 of 16
    # here, 240 of 240 in the measurement above) so that an ordinarily busy
    # machine does not fail a correct implementation.
    LEAST_NAMED = 12

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()
        self._children = []

    def tearDown(self):
        for child in self._children:
            child.stop()
        self._tmp.cleanup()

    def _race(self):
        """Two real sessions started together; (winner pid, refusal) after."""
        children = [_LockChild(self.s.project_dir), _LockChild(self.s.project_dir)]
        self._children.extend(children)
        try:
            for child in children:
                self.assertEqual(child.line(), "ready")
            for child in children:
                child.release()
            outcomes = [child.line() for child in children]
        finally:
            for child in children:
                child.stop()
        won = [o for o in outcomes if o.startswith("won")]
        refused = [o for o in outcomes if o.startswith("refused")]
        self.assertEqual(len(won), 1, "outcomes were {}".format(outcomes))
        self.assertEqual(len(refused), 1, "outcomes were {}".format(outcomes))
        return int(won[0].split()[1]), refused[0].split()[1]

    def test_a_contended_refusal_names_the_process_that_actually_holds_it(self):
        named = 0
        for round_number in range(self.ROUNDS):
            winner, reported = self._race()
            with self.subTest(round=round_number):
                if reported == "None":
                    continue
                self.assertEqual(
                    int(reported),
                    winner,
                    "the refusal named {} while {} held the lock".format(
                        reported, winner
                    ),
                )
                named += 1
        self.assertGreaterEqual(
            named,
            self.LEAST_NAMED,
            "only {} of {} contended refusals could name the holder".format(
                named, self.ROUNDS
            ),
        )

    def test_a_pid_a_contended_refusal_names_is_a_process_that_exists(self):
        """The winner is still sitting on the lock when the loser is refused,
        so a named pid has to be findable right then -- which is the whole
        premise of telling a user to go and close it. Checked while the winner
        is alive rather than after, because a pid checked after everything has
        exited proves nothing either way.
        """
        for round_number in range(self.ROUNDS // 4):
            children = [_LockChild(self.s.project_dir), _LockChild(self.s.project_dir)]
            self._children.extend(children)
            for child in children:
                self.assertEqual(child.line(), "ready")
            for child in children:
                child.release()
            outcomes = [child.line() for child in children]
            refused = [o for o in outcomes if o.startswith("refused")]
            self.assertEqual(len(refused), 1, "outcomes were {}".format(outcomes))
            reported = refused[0].split()[1]
            with self.subTest(round=round_number):
                if reported != "None":
                    # Still holding: nothing has been released yet.
                    self.assertTrue(
                        session._pid_is_alive(int(reported)),
                        "the refusal named {}, which is not running".format(reported),
                    )
            for child in children:
                child.stop()


class SessionLockHardeningTest(unittest.TestCase):
    """Tests for the parts of the lock the happy-path tests above do not pin.

    Each one names a single-line change to session.py that would otherwise
    pass the whole suite: taking the lock and dropping it again, closing the
    descriptor at the end of the acquire, writing a timestamp nobody can read,
    reaching for a locking primitive the platform does not have.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.s = Session(self.root)
        self.s.ensure_dirs()
        self._sessions = [self.s]

    def tearDown(self):
        for s in self._sessions:
            s.release_lock()
        self._tmp.cleanup()

    def _session(self, project_dir=None):
        s = Session(self.s.project_dir if project_dir is None else project_dir)
        self._sessions.append(s)
        return s

    def test_the_lock_lives_in_the_session_directory(self):
        self.assertEqual(self.s.lock_path, self.s.craft_dir / "session.lock")

    def test_acquiring_creates_the_session_directory(self):
        """The server takes the lock before anything else has run."""
        fresh = self._session(self.root / "never-used")
        self.assertFalse(fresh.craft_dir.exists())
        fresh.acquire_lock()
        self.assertTrue(fresh.lock_path.is_file())
        self.assertEqual(read_json(fresh.lock_path)["pid"], os.getpid())

    def test_the_lock_is_still_held_after_acquire_returns(self):
        """The descriptor is the lock. Closing it at the end of the acquire --
        the natural-looking tidy-up -- unlocks the project while the session
        that thinks it holds it carries on writing CRAFT.md."""
        self.s.acquire_lock()
        with self.assertRaises(LockHeld):
            self._session().acquire_lock()

    def test_lock_held_normalises_the_pid_it_is_handed(self):
        """LockHeld is exported and raised from more than one place, so the
        int-or-None contract belongs to the exception itself rather than to
        the discipline of whoever constructs it."""
        self.assertEqual(LockHeld("1234", "old").pid, 1234)
        self.assertEqual(LockHeld(1234, "old").pid, 1234)
        self.assertIsNone(LockHeld(None, "old").pid)
        self.assertIsNone(LockHeld("unknown", "unknown").pid)
        self.assertIn("unknown", str(LockHeld(None, "unknown")))
        self.assertIn("1234", str(LockHeld("1234", "old")))

    def test_a_lock_that_is_a_directory_is_refused_rather_than_crashing(self):
        """Anything can be sitting at that name. A directory there cannot be
        opened as a file and cannot be locked, so the acquire has to say the
        project is unavailable rather than raise IsADirectoryError out of a
        traceback that names nothing a user can act on.

        It says it as LockUnavailable, not as LockHeld: no session owns this
        project, and reporting one that does leaves a user with nothing to try
        except deleting the lock by hand -- which is the act that puts two
        live holders on one project.
        """
        self.s.lock_path.mkdir()
        with self.assertRaises(LockUnavailable) as caught:
            self.s.acquire_lock()
        self.assertNotIsInstance(caught.exception, LockHeld)
        with self.assertRaises(LockUnavailable):
            self.s.acquire_lock()
        self.s.release_lock()  # shutdown must still get out
        self.assertTrue(self.s.lock_path.is_dir())
        self.assertEqual(
            sorted(p.name for p in self.s.craft_dir.iterdir()),
            ["session.lock"],
            "a temp file was left behind by the failed acquires",
        )

    def test_the_lock_records_when_it_was_taken_in_utc(self):
        """started_at is shown to a human in the refusal, so it has to be a
        real timestamp in a stated zone. The clock is moved off UTC for the
        acquire: a local-time implementation writes a stamp hours away from now
        and fails the recency check, while a UTC one is unaffected."""
        if not hasattr(time, "tzset"):
            self.skipTest("no tzset on this platform, so TZ cannot be moved")
        previous = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "Pacific/Kiritimati"  # UTC+14, no DST
            time.tzset()
            self.assertNotEqual(
                time.strftime("%H", time.localtime()),
                time.strftime("%H", time.gmtime()),
                "TZ did not move the local clock, so this test proves nothing",
            )
            self.s.acquire_lock()
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

        stamp = read_json(self.s.lock_path)["started_at"]
        parsed = calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
        self.assertLess(
            abs(parsed - time.time()),
            600,
            "started_at {!r} is not close to now in UTC".format(stamp),
        )

    def test_the_lock_file_holds_only_the_payload_that_was_last_written(self):
        """The acquire writes through an existing file rather than replacing
        it, so a longer previous payload must be truncated away and not left
        trailing after the new one."""
        self.s.lock_path.write_text("x" * 4096, encoding="utf-8")
        self.s.acquire_lock()
        raw = self.s.lock_path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(raw)["pid"], os.getpid())
        self.assertNotIn("x", raw)

    def test_releasing_a_lock_that_is_not_there_is_not_an_error(self):
        """Shutdown runs whether or not startup got as far as the lock."""
        self.assertFalse(self.s.lock_path.exists())
        self.s.release_lock()
        self.assertFalse(self.s.lock_path.exists())

    def test_the_lock_is_per_project(self):
        """One lock per project directory, not one per machine."""
        other = self._session(self.root / "other-project")
        self.s.acquire_lock()
        other.acquire_lock()  # must not raise
        self.assertNotEqual(self.s.lock_path, other.lock_path)
        self.assertTrue(self.s.lock_path.is_file())
        self.assertTrue(other.lock_path.is_file())

    def test_the_lock_file_is_not_mistaken_for_a_round(self):
        """It lives in the same directory the round files do."""
        self.s.acquire_lock()
        self.assertIsNone(self.s.current_round())
        self.assertIsNone(ROUND_RE.match(self.s.lock_path.name))

    def test_the_lock_survives_a_round_trip_of_acquire_release_acquire(self):
        """The ordinary server lifecycle, twice, in one project.

        The second acquire returning at all is the real assertion here: it runs
        outside assertRaises, so a release that left the lock held would come
        back as a LockHeld and fail the test.
        """
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())
        self.s.release_lock()
        self.assertTrue(self.s.lock_path.is_file())
        self.s.acquire_lock()
        second = read_json(self.s.lock_path)
        self.assertEqual(second["pid"], os.getpid())
        self.assertTrue(second["started_at"])
        self.assertEqual(
            [p.name for p in self.s.craft_dir.iterdir()], ["session.lock"]
        )


class LockPlatformDispatchTest(unittest.TestCase):
    """Which locking primitive gets chosen, and on what evidence.

    The module attributes are read through `session` on purpose: the assertion
    is about the names the module itself bound at import, which a from-import
    copy could not tell apart from a second one.
    """

    def test_the_dispatch_selects_the_fcntl_lock_on_this_platform(self):
        self.assertIsNotNone(session.fcntl, "this suite is expected to run on Unix")
        self.assertIs(session._try_lock_exclusive, session._fcntl_try_lock)
        self.assertIs(session._unlock, session._fcntl_unlock)
        self.assertEqual(
            session.select_lock_impl(session.fcntl, session.msvcrt),
            (session._fcntl_try_lock, session._fcntl_unlock),
        )

    def test_the_dispatch_would_select_msvcrt_where_there_is_no_fcntl(self):
        """The Windows branch cannot be executed here, but the choice of it
        can: the selection is a function of the two modules, so a machine with
        no fcntl and a msvcrt is expressible without pretending to be one."""
        fake_msvcrt = types.SimpleNamespace(
            locking=lambda *args: None, LK_NBLCK=0, LK_UNLCK=0
        )
        self.assertEqual(
            session.select_lock_impl(None, fake_msvcrt),
            (session._msvcrt_try_lock, session._msvcrt_unlock),
        )
        # fcntl wins when both are there, so a Cygwin-shaped machine with both
        # gets the primitive this project has actually exercised.
        self.assertEqual(
            session.select_lock_impl(session.fcntl, fake_msvcrt),
            (session._fcntl_try_lock, session._fcntl_unlock),
        )

    def test_the_dispatch_is_by_capability_and_not_by_platform_name(self):
        """A module that is present but carries no locking primitive is not a
        locking implementation, and neither is no module at all. Both are a
        loud refusal rather than a lock that silently never locks."""
        with self.assertRaises(RuntimeError):
            session.select_lock_impl(types.SimpleNamespace(), types.SimpleNamespace())
        with self.assertRaises(RuntimeError):
            session.select_lock_impl(None, None)

    def test_the_fcntl_lock_reports_a_conflict_rather_than_raising(self):
        """The primitive's own contract, under the two shapes a refusal
        arrives in: BlockingIOError on Linux, EACCES on the BSDs. Anything
        else is a real failure and must not be swallowed as "somebody else
        has it"."""
        with mock.patch.object(
            session.fcntl, "flock", side_effect=BlockingIOError(errno.EWOULDBLOCK, "x")
        ):
            self.assertFalse(session._fcntl_try_lock(0))
        with mock.patch.object(
            session.fcntl, "flock", side_effect=OSError(errno.EACCES, "x")
        ):
            self.assertFalse(session._fcntl_try_lock(0))
        with mock.patch.object(
            session.fcntl, "flock", side_effect=OSError(errno.ENOLCK, "x")
        ):
            with self.assertRaises(OSError):
                session._fcntl_try_lock(0)


class FileIdentityTest(unittest.TestCase):
    """What "the same file" means, since the whole of the fix rests on it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "a-file"
        self.path.write_text("x", encoding="utf-8")
        self.fd = os.open(str(self.path), os.O_RDWR)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(os.close, self.fd)

    def _stat_like(self, real, st_dev=None, st_ino=None, st_size=None, st_mtime=None):
        """A stat result differing from `real` in exactly the fields named.

        The ten-field tuple os.stat_result is built from carries whole-second
        timestamps, so a copy made from that alone differs from the original
        in st_mtime no matter what else it says -- and a check comparing
        timestamps instead of inodes would then pass every test below without
        ever looking at an inode. The second argument is what keeps the copy
        byte-identical in the fields nobody asked to change.
        """
        fields = list(real)
        fields[1] = real.st_ino if st_ino is None else st_ino
        fields[2] = real.st_dev if st_dev is None else st_dev
        fields[6] = real.st_size if st_size is None else st_size
        mtime = real.st_mtime if st_mtime is None else st_mtime
        fields[8] = int(mtime)
        return os.stat_result(
            tuple(fields),
            {
                "st_atime": real.st_atime,
                "st_mtime": mtime,
                "st_ctime": real.st_ctime,
                "st_atime_ns": real.st_atime_ns,
                "st_mtime_ns": int(mtime * 1e9),
                "st_ctime_ns": real.st_ctime_ns,
            },
        )

    def test_a_descriptor_on_the_file_the_path_names_is_that_file(self):
        """The control: without this passing, every negative below could be
        passing because the check always says no."""
        self.assertTrue(session._is_file_at(self.fd, self.path))

    def test_a_different_inode_at_the_same_name_is_a_different_file(self):
        """os.replace puts a new inode at an old name and carries none of its
        locks over. This is the shape write_json_atomic has.

        The replacement is made indistinguishable from the original in
        everything but the inode -- the same bytes, so the same size, and the
        original's timestamps copied onto it -- so that only a check which
        compares the inode can tell the two apart. A lock file is a few dozen
        bytes of JSON rewritten by every session in turn, so two of them
        agreeing on size and mtime is the ordinary case here, not a contrived
        one.
        """
        real = os.fstat(self.fd)
        other = self.path.with_name("other")
        other.write_text("x", encoding="utf-8")
        os.utime(str(other), ns=(real.st_atime_ns, real.st_mtime_ns))
        os.replace(str(other), str(self.path))
        now = os.stat(str(self.path))
        self.assertNotEqual(now.st_ino, real.st_ino, "the inode did not change")
        self.assertEqual(
            (now.st_size, now.st_mtime),
            (real.st_size, real.st_mtime),
            "the two files differ in size or mtime, so this proves less than it says",
        )
        self.assertFalse(session._is_file_at(self.fd, self.path))

    def test_a_name_that_no_longer_exists_is_not_our_file(self):
        os.unlink(str(self.path))
        self.assertFalse(session._is_file_at(self.fd, self.path))

    def test_identity_is_the_device_as_well_as_the_inode(self):
        """Inode numbers are unique within a filesystem and nowhere else, and
        a .craft/ that was removed and recreated need not be on the one it was
        on before. Comparing st_ino alone would call two different files the
        same one whenever the numbers happened to collide, which is exactly
        the case the retry exists to catch.

        Two filesystems cannot be conjured here, so the second stat is the one
        a second filesystem would have produced: same inode number, same size,
        same timestamps, different device.
        """
        real = os.fstat(self.fd)
        elsewhere = self._stat_like(real, st_dev=real.st_dev + 1)
        self.assertEqual(elsewhere.st_ino, real.st_ino)
        self.assertEqual(
            (elsewhere.st_size, elsewhere.st_mtime), (real.st_size, real.st_mtime)
        )
        with mock.patch("session.os.stat", return_value=elsewhere):
            self.assertFalse(session._is_file_at(self.fd, self.path))
        # And the mirror, so the assertion above cannot pass by comparing
        # nothing at all: same device, different inode is also a different file.
        same_dev = self._stat_like(real, st_ino=real.st_ino + 1)
        self.assertEqual(
            (same_dev.st_size, same_dev.st_mtime), (real.st_size, real.st_mtime)
        )
        with mock.patch("session.os.stat", return_value=same_dev):
            self.assertFalse(session._is_file_at(self.fd, self.path))

    def test_identity_is_not_the_size_and_the_time_the_file_was_written(self):
        """The other half of what "the same file" has to mean, and the half a
        suite can pass without ever having pinned it.

        A file is still ours when it has been written to since we opened it --
        which the lock file is, by every acquire that truncates and rewrites
        it. Substituting (st_size, st_mtime) for (st_dev, st_ino) leaves the
        inode tests above green and fails here, which is the point: identity
        is which file it is, not what is currently in it.
        """
        real = os.fstat(self.fd)
        rewritten = self._stat_like(
            real, st_size=real.st_size + 4096, st_mtime=real.st_mtime + 60
        )
        self.assertEqual(
            (rewritten.st_dev, rewritten.st_ino), (real.st_dev, real.st_ino)
        )
        with mock.patch("session.os.stat", return_value=rewritten):
            self.assertTrue(session._is_file_at(self.fd, self.path))


class SessionLockPathIdentityTest(unittest.TestCase):
    """The lock is granted on an inode; every caller of it names a path.

    Between the os.open and the lock being granted, the name can come to mean
    a different file. The old implementation never looked, so it would sit
    holding an orphaned inode while a real second process held the file at the
    name -- two live holders on one project, and CRAFT.md is rewritten whole
    every round.

    Each test below opens that window deliberately, fires one real trigger in
    it, and lets a genuine second OS process take the file that is at the path
    afterwards. Nothing is interleaved by hand: the child rendezvouses on
    pipes and is reaped however the test ends.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()
        self._children = []
        self._sessions = [self.s]

    def tearDown(self):
        for child in self._children:
            child.stop()
        for s in self._sessions:
            s.release_lock()
        self._tmp.cleanup()

    def _holding_child(self):
        """A real second craft session that has the lock and is sitting on it."""
        child = _LockChild(self.s.project_dir)
        self._children.append(child)
        self.assertEqual(child.line(), "ready")
        child.release()
        outcome = child.line()
        self.assertTrue(
            outcome.startswith("won"), "the child was refused: {}".format(outcome)
        )
        return child

    def _refused_when_the_path_moves_under_us(self, trigger):
        """Fire `trigger` between our open and our lock, then hand the path to
        a real second process, and assert we are refused rather than joining
        it as a second holder."""
        real_try_lock = session._try_lock_exclusive
        state = {"attempts": 0, "child": None}

        def hook(fd):
            state["attempts"] += 1
            if state["child"] is None:
                trigger()
                state["child"] = self._holding_child()
            return real_try_lock(fd)

        with mock.patch.object(session, "_try_lock_exclusive", hook):
            with self.assertRaises(LockHeld) as caught:
                self.s.acquire_lock()

        child = state["child"]
        self.assertIsNotNone(child, "the trigger never ran, so nothing was proved")
        self.assertEqual(state["attempts"], 2, "the acquire did not start over")
        self.assertEqual(caught.exception.pid, child.proc.pid)
        # The holder is untouched, still holds it, and still refuses us.
        self.assertEqual(read_json(self.s.lock_path)["pid"], child.proc.pid)
        with self.assertRaises(LockHeld):
            self.s.acquire_lock()

    def test_a_lock_file_removed_under_us_does_not_make_us_a_second_holder(self):
        """`rm .craft/session.lock`, which is the remedy a user reaches for
        when they are told to kill pid None."""
        self._refused_when_the_path_moves_under_us(
            lambda: os.unlink(str(self.s.lock_path))
        )

    def test_a_craft_dir_removed_under_us_does_not_make_us_a_second_holder(self):
        """`git clean -xdf`, over a .craft/ this project gitignores by its own
        design. The directory goes with the file, so the retry has to be able
        to put both back."""
        self._refused_when_the_path_moves_under_us(
            lambda: shutil.rmtree(str(self.s.craft_dir))
        )

    def test_a_lock_file_replaced_under_us_does_not_make_us_a_second_holder(self):
        """An os.replace of the write_json_atomic shape: the name survives,
        the inode under it does not, and a lock held on the old one guards
        nothing anybody else can see."""

        def replace():
            fd, tmp = tempfile.mkstemp(dir=str(self.s.craft_dir), prefix=".tmp-")
            os.close(fd)
            os.replace(tmp, str(self.s.lock_path))

        self._refused_when_the_path_moves_under_us(replace)

    def test_a_lock_file_removed_under_us_with_nobody_else_there_is_retaken(self):
        """The other half of the retry: when the name really is free, starting
        over must end in holding it, not in an error. The lock file is put
        back, and it is the one at the path that we hold."""
        real_try_lock = session._try_lock_exclusive
        state = {"attempts": 0}

        def hook(fd):
            state["attempts"] += 1
            if state["attempts"] == 1:
                os.unlink(str(self.s.lock_path))
            return real_try_lock(fd)

        with mock.patch.object(session, "_try_lock_exclusive", hook):
            self.s.acquire_lock()

        self.assertEqual(state["attempts"], 2)
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())
        with self.assertRaises(LockHeld):
            Session(self.s.project_dir).acquire_lock()

    def test_a_name_that_keeps_being_replaced_is_reported_and_not_spun_on(self):
        """A path something outside this session churns is pathological, not
        something to retry forever: a server startup that never returns is
        worse than one that says why. The trigger stops well before an
        unbounded implementation would, so that a missing bound fails this
        test instead of hanging the suite.
        """
        real_try_lock = session._try_lock_exclusive
        state = {"attempts": 0}

        def hook(fd):
            state["attempts"] += 1
            if state["attempts"] <= 20:
                os.unlink(str(self.s.lock_path))
                os.close(os.open(str(self.s.lock_path), os.O_CREAT | os.O_RDWR, 0o644))
            return real_try_lock(fd)

        with mock.patch.object(session, "_try_lock_exclusive", hook):
            with self.assertRaises(LockUnavailable) as caught:
                self.s.acquire_lock()

        self.assertEqual(state["attempts"], session._LOCK_ATTEMPTS)
        self.assertIn(str(self.s.lock_path), str(caught.exception))
        self.assertIsNone(self.s._lock_fd, "a descriptor was kept on a lost file")

    def test_starting_over_leaks_no_file_descriptor(self):
        """Every abandoned attempt closes the descriptor it locked. A retry
        loop that did not would leak one per attempt and keep the orphaned
        lock alive for the life of the process."""
        fd_dir = Path("/proc/self/fd")
        if not fd_dir.is_dir():
            self.skipTest("no /proc/self/fd on this platform to count against")
        real_try_lock = session._try_lock_exclusive
        state = {"attempts": 0}

        def hook(fd):
            # Bounded well past the real limit rather than forever, so that an
            # unbounded retry loop fails this test instead of hanging the suite.
            state["attempts"] += 1
            if state["attempts"] <= 20:
                os.unlink(str(self.s.lock_path))
                os.close(os.open(str(self.s.lock_path), os.O_CREAT | os.O_RDWR, 0o644))
            return real_try_lock(fd)

        before = len(os.listdir(str(fd_dir)))
        for _ in range(10):
            state["attempts"] = 0
            with mock.patch.object(session, "_try_lock_exclusive", hook):
                with self.assertRaises(LockUnavailable):
                    self.s.acquire_lock()
        self.assertEqual(len(os.listdir(str(fd_dir))), before)


class SessionLockUnavailableTest(unittest.TestCase):
    """The failures that are not contention, told apart from the one that is.

    Every case here is produced with no other craft session in existence. The
    old code turned all of them into "another session owns this, kill pid
    None", and a user handed that message has one remedy left -- deleting the
    lock file by hand, which is the trigger the identity check above exists to
    survive. LockHeld now means exactly one thing: a live process holds it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.s = Session(self.root)
        self.s.ensure_dirs()
        self._sessions = [self.s]

    def tearDown(self):
        for s in self._sessions:
            s.release_lock()
        self._tmp.cleanup()

    def _session(self):
        s = Session(self.s.project_dir)
        self._sessions.append(s)
        return s

    def _skip_if_root(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root is not stopped by a file mode, so this proves nothing")

    def test_the_two_lock_failures_are_different_exceptions(self):
        """Neither is a subclass of the other, so `except LockHeld` cannot
        quietly swallow a filesystem fault and report an owner for it."""
        self.assertFalse(issubclass(LockUnavailable, LockHeld))
        self.assertFalse(issubclass(LockHeld, LockUnavailable))

    def test_a_directory_at_the_lock_name_names_the_real_cause(self):
        self.s.lock_path.mkdir()
        with self.assertRaises(LockUnavailable) as caught:
            self.s.acquire_lock()
        exc = caught.exception
        self.assertEqual(exc.errno, errno.EISDIR)
        self.assertEqual(exc.path, str(self.s.lock_path))
        self.assertIsInstance(exc.error, OSError)
        self.assertIn(str(self.s.lock_path), str(exc))
        self.assertIn("EISDIR", str(exc))
        self.assertNotIn("None", str(exc))

    def test_a_lock_file_we_may_not_open_names_the_real_cause(self):
        self._skip_if_root()
        self.s.lock_path.write_text("{}", encoding="utf-8")
        os.chmod(str(self.s.lock_path), 0o444)
        try:
            with self.assertRaises(LockUnavailable) as caught:
                self.s.acquire_lock()
        finally:
            # Restored here rather than in a cleanup: cleanups run after
            # tearDown, and tearDown is what removes the directory this mode
            # would otherwise keep it from removing.
            os.chmod(str(self.s.lock_path), 0o644)
        self.assertEqual(caught.exception.errno, errno.EACCES)
        self.assertIn(str(self.s.lock_path), str(caught.exception))

    def test_a_craft_dir_we_may_not_write_into_names_the_real_cause(self):
        self._skip_if_root()
        self.assertFalse(self.s.lock_path.exists())
        os.chmod(str(self.s.craft_dir), 0o555)
        try:
            with self.assertRaises(LockUnavailable) as caught:
                self.s.acquire_lock()
        finally:
            os.chmod(str(self.s.craft_dir), 0o755)
        self.assertEqual(caught.exception.errno, errno.EACCES)

    def test_a_read_only_or_a_full_filesystem_names_the_real_cause(self):
        """Neither can be conjured in a temp directory, so the errno the
        kernel would return is returned instead. What is being pinned is that
        no OSError from the open is read as an owner."""
        for number in (errno.EROFS, errno.ENOSPC, errno.ENAMETOOLONG, errno.EMFILE):
            with self.subTest(errno=number):
                failure = OSError(number, os.strerror(number))
                with mock.patch("session.os.open", side_effect=failure):
                    with self.assertRaises(LockUnavailable) as caught:
                        self.s.acquire_lock()
                self.assertEqual(caught.exception.errno, number)
                self.assertIs(caught.exception.error, failure)
                self.assertIn(str(self.s.lock_path), str(caught.exception))

    def test_a_lock_error_that_is_not_contention_names_the_real_cause(self):
        """The primitive re-raises anything outside its would-block set, and
        every one of those is a reason the lock is unusable rather than a
        reason somebody else has it. ENOLCK is the realistic one: an NFS mount
        with no lock daemon behind it."""
        for number in (errno.ENOLCK, errno.EBADF, errno.EINVAL):
            with self.subTest(errno=number):
                with mock.patch.object(
                    session.fcntl, "flock", side_effect=OSError(number, "x")
                ):
                    with self.assertRaises(LockUnavailable) as caught:
                        self.s.acquire_lock()
                self.assertEqual(caught.exception.errno, number)
                self.assertNotIsInstance(caught.exception, LockHeld)

    def test_contention_is_still_reported_as_a_held_lock(self):
        """The other side of the split, so that discriminating did not simply
        turn every refusal into a filesystem fault."""
        self.s.acquire_lock()
        with self.assertRaises(LockHeld) as caught:
            self._session().acquire_lock()
        self.assertNotIsInstance(caught.exception, LockUnavailable)
        self.assertEqual(caught.exception.pid, os.getpid())

    def test_an_unusable_lock_leaks_no_file_descriptor(self):
        """A server that reports the fault and keeps running must not lose a
        descriptor each time somebody retries."""
        fd_dir = Path("/proc/self/fd")
        if not fd_dir.is_dir():
            self.skipTest("no /proc/self/fd on this platform to count against")
        before = len(os.listdir(str(fd_dir)))
        for _ in range(20):
            with mock.patch.object(
                session.fcntl, "flock", side_effect=OSError(errno.ENOLCK, "x")
            ):
                with self.assertRaises(LockUnavailable):
                    self.s.acquire_lock()
        self.assertEqual(len(os.listdir(str(fd_dir))), before)

    def test_an_unusable_lock_leaves_the_session_holding_nothing(self):
        """Shutdown still has to get out, and a later acquire must not be
        refused by a descriptor this session never kept."""
        self.s.lock_path.mkdir()
        with self.assertRaises(LockUnavailable):
            self.s.acquire_lock()
        self.s.release_lock()  # must not raise
        os.rmdir(str(self.s.lock_path))
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_an_unavailable_lock_reads_as_a_sentence_about_the_file(self):
        """The message is the whole point of the split. It must name the path
        and the cause, and it must not tell anyone to kill anything."""
        failure = OSError(errno.EROFS, "Read-only file system")
        exc = LockUnavailable(self.s.lock_path, failure)
        self.assertIn(str(self.s.lock_path), str(exc))
        self.assertIn("Read-only file system", str(exc))
        self.assertIn("EROFS", str(exc))
        self.assertNotIn("kill", str(exc))
        bare = LockUnavailable(self.s.lock_path)
        self.assertIsNone(bare.errno)
        self.assertIn(str(self.s.lock_path), str(bare))


class SessionLockOwningProcessTest(unittest.TestCase):
    """Who is allowed to release the lock.

    flock lives on the open file description, and fork() shares one rather
    than copying it, so LOCK_UN through a child's inherited copy frees the
    *parent's* lock while the parent goes on believing it holds the project.
    Nothing forks today -- the server is threaded, and the descriptor is not
    handed to subprocesses -- so this is a tripwire for the tasks still to
    come rather than a live bug.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()
        self._sessions = [self.s]

    def tearDown(self):
        for s in self._sessions:
            s.release_lock()
        self._tmp.cleanup()

    def _session(self):
        s = Session(self.s.project_dir)
        self._sessions.append(s)
        return s

    def _reap(self, pid):
        try:
            os.waitpid(pid, 0)
        except (ChildProcessError, OSError):
            pass

    def test_a_forked_child_releasing_does_not_free_the_parents_lock(self):
        if not hasattr(os, "fork"):
            self.skipTest("no os.fork on this platform")
        self.s.acquire_lock()
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            # The child. os._exit, so that no test fixture, no temporary
            # directory and no unittest reporting runs twice.
            code = 1
            try:
                os.close(read_fd)
                self.s.release_lock()
                code = 0
            except BaseException:
                code = 3
            finally:
                try:
                    os.write(write_fd, b"released\n")
                except OSError:
                    pass
                os._exit(code)

        self.addCleanup(self._reap, pid)
        os.close(write_fd)
        with os.fdopen(read_fd, "rb") as fh:
            said = fh.read()  # rendezvous: EOF is the child having exited
        self.assertEqual(said, b"released\n")
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFEXITED(status), "the child did not exit normally")
        self.assertEqual(
            os.WEXITSTATUS(status),
            0,
            "release_lock in a forked child must be a no-op, not an error",
        )

        # The parent still holds the project, which is the whole assertion.
        with self.assertRaises(LockHeld) as caught:
            self._session().acquire_lock()
        self.assertEqual(caught.exception.pid, os.getpid())
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_the_process_that_took_the_lock_can_still_release_it(self):
        """The control for the test above: guarding the release by pid must
        not stop the ordinary release from working."""
        self.s.acquire_lock()
        self.s.release_lock()
        self._session().acquire_lock()  # must not raise

    def test_a_forked_child_does_not_believe_it_holds_the_parents_lock(self):
        """The tripwire itself, fired.

        fork() shares the open file description the lock lives on, so without
        the at-fork handler a child inherits a Session that says it holds the
        project: it would release the parent's lock, and -- worse, because it
        is silent -- it would hold the flock open after the parent was killed,
        so the next session to come along is refused by a process that no
        longer exists. Nothing forks today, but multiprocessing defaults to
        fork on Linux, so this is registered rather than remembered.
        """
        if not hasattr(os, "fork"):
            self.skipTest("no os.fork on this platform")
        self.s.acquire_lock()
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            # The child. os._exit, so that no fixture and no unittest
            # reporting runs twice.
            try:
                os.close(read_fd)
                said = "fd={} pid={} ours={}".format(
                    self.s._lock_fd,
                    self.s._lock_pid,
                    self.s.verify_lock_still_ours(),
                )
                self.s.release_lock()  # must be a no-op, not an error
                os.write(write_fd, said.encode("utf-8"))
            except BaseException as exc:  # noqa: BLE001 - reported, not handled
                try:
                    os.write(write_fd, "raised {!r}".format(exc).encode("utf-8"))
                except OSError:
                    pass
            finally:
                os._exit(0)

        self.addCleanup(self._reap, pid)
        os.close(write_fd)
        with os.fdopen(read_fd, "rb") as fh:
            said = fh.read().decode("utf-8")  # EOF is the child having exited
        os.waitpid(pid, 0)
        self.assertEqual(said, "fd=None pid=None ours=False")

        # The parent still holds the project, which is the other half of it.
        self.assertTrue(self.s.verify_lock_still_ours())
        with self.assertRaises(LockHeld) as caught:
            self._session().acquire_lock()
        self.assertEqual(caught.exception.pid, os.getpid())

    def test_the_at_fork_handler_may_be_run_twice(self):
        """It is registered per import of the module, and a project that
        imports session under two names registers it twice. Running it again
        over a set it has already emptied has to be a no-op rather than a
        second close of a descriptor this process may have reused.
        """
        self.s.acquire_lock()
        holders = weakref.WeakSet([self.s])
        with mock.patch.object(session, "_LOCK_HOLDERS", holders):
            session._forget_lock_after_fork()
            session._forget_lock_after_fork()
        self.assertIsNone(self.s._lock_fd)
        self.assertIsNone(self.s._lock_pid)
        self.assertFalse(self.s.verify_lock_still_ours())
        self.assertEqual(len(holders), 0)
        self.s.release_lock()  # must not raise, and has nothing to do
        # The descriptor went with the state, so the project is free again.
        self._session().acquire_lock()

    def test_holding_the_lock_registers_the_session_and_releasing_it_does_not(self):
        """The handler can only clear what it can find, and a set nothing is
        ever added to would make the fork test above pass for the wrong
        reason. Releasing takes the entry out again, so a long-lived process
        that opens many projects does not accumulate them."""
        self.assertNotIn(self.s, session._LOCK_HOLDERS)
        self.s.acquire_lock()
        self.assertIn(self.s, session._LOCK_HOLDERS)
        self.s.release_lock()
        self.assertNotIn(self.s, session._LOCK_HOLDERS)


class SessionLockOwnershipCheckTest(unittest.TestCase):
    """verify_lock_still_ours: the holder noticing it has been undermined.

    An `rm .craft/session.lock` after a session has the lock cannot be caught
    by the next acquirer -- the name it would compare against is gone, so it
    opens a fresh file, is granted a lock on it, and both sessions believe
    they own the project. Four live holders were produced this way, one per
    removal. Nothing on the acquiring side can fix that, so the holder is the
    one who has to look, and this is what a server calls on a timer before
    shutting down loudly.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()
        self._sessions = [self.s]

    def tearDown(self):
        for s in self._sessions:
            s.release_lock()
        self._tmp.cleanup()

    def _session(self):
        s = Session(self.s.project_dir)
        self._sessions.append(s)
        return s

    def test_a_session_that_never_acquired_holds_nothing(self):
        self.assertFalse(self.s.verify_lock_still_ours())

    def test_a_session_holding_the_lock_says_so(self):
        self.s.acquire_lock()
        self.assertTrue(self.s.verify_lock_still_ours())
        self.assertTrue(self.s.verify_lock_still_ours(), "asking twice changed it")

    def test_a_session_that_released_the_lock_no_longer_holds_it(self):
        self.s.acquire_lock()
        self.s.release_lock()
        self.assertFalse(self.s.verify_lock_still_ours())

    def test_a_lock_file_removed_under_the_holder_is_no_longer_ours(self):
        """`rm .craft/session.lock`. The lock is still held -- the kernel does
        not care that the name is gone -- but it now guards an inode nobody
        can reach, and the check has to say so rather than raise."""
        self.s.acquire_lock()
        os.unlink(str(self.s.lock_path))
        self.assertFalse(self.s.verify_lock_still_ours())

    def test_a_craft_dir_removed_under_the_holder_is_no_longer_ours(self):
        """`git clean -xdf`, over a .craft/ this project gitignores."""
        self.s.acquire_lock()
        shutil.rmtree(str(self.s.craft_dir))
        self.assertFalse(self.s.verify_lock_still_ours())

    def test_a_lock_file_replaced_under_the_holder_is_no_longer_ours(self):
        """The name survives, the inode under it does not."""
        self.s.acquire_lock()
        fd, tmp = tempfile.mkstemp(dir=str(self.s.craft_dir), prefix=".tmp-")
        os.close(fd)
        os.replace(tmp, str(self.s.lock_path))
        self.assertFalse(self.s.verify_lock_still_ours())

    def test_the_check_tells_the_two_holders_of_one_project_apart(self):
        """The catastrophe end to end, which is what makes the check worth
        having: the file is removed, a second session takes the project, and
        both of them are holding a lock. The one asking the question is the
        only place that difference is visible."""
        self.s.acquire_lock()
        os.unlink(str(self.s.lock_path))
        second = self._session()
        second.acquire_lock()  # nothing can stop this; the name was free
        self.assertTrue(second.verify_lock_still_ours())
        self.assertFalse(self.s.verify_lock_still_ours())
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_the_check_never_raises_on_a_lock_file_it_cannot_stat(self):
        """It runs on a timer inside a server, so it reports rather than
        throws, whatever the filesystem says."""
        self.s.acquire_lock()
        for failure in (
            OSError(errno.EACCES, "Permission denied"),
            OSError(errno.ENOENT, "No such file or directory"),
            OSError(errno.EIO, "Input/output error"),
        ):
            with self.subTest(errno=failure.errno):
                with mock.patch("session.os.stat", side_effect=failure):
                    self.assertFalse(self.s.verify_lock_still_ours())
        self.assertTrue(self.s.verify_lock_still_ours())


class SessionLockPayloadWriteTest(unittest.TestCase):
    """The holder's identity reaches the file whole, or not at all.

    os.write is entitled to write less than it was given. Discarding what it
    returns truncates the JSON, and a refusal that should have named a pid
    names nobody -- which is the message that sends a user to delete the lock
    file.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()
        self._sessions = [self.s]

    def tearDown(self):
        for s in self._sessions:
            s.release_lock()
        self._tmp.cleanup()

    def _session(self):
        s = Session(self.s.project_dir)
        self._sessions.append(s)
        return s

    def test_a_short_write_still_leaves_the_whole_payload_in_the_lock(self):
        real_write = os.write
        calls = []

        def one_byte_at_a_time(fd, data):
            calls.append(len(data))
            return real_write(fd, data[:1])

        with mock.patch("session.os.write", one_byte_at_a_time):
            self.s.acquire_lock()

        self.assertGreater(
            len(calls), 1, "the payload was short enough to prove nothing"
        )
        holder = read_json(self.s.lock_path)
        self.assertEqual(holder["pid"], os.getpid())
        self.assertTrue(holder["started_at"])
        with self.assertRaises(LockHeld) as caught:
            self._session().acquire_lock()
        self.assertEqual(caught.exception.pid, os.getpid())

    def test_a_write_that_never_progresses_is_reported_and_not_spun_on(self):
        with mock.patch("session.os.write", return_value=0):
            with self.assertRaises(LockUnavailable) as caught:
                self.s.acquire_lock()
        self.assertIn(str(self.s.lock_path), str(caught.exception))
        self.assertIsNone(self.s._lock_fd)
        self.s.acquire_lock()  # and the failure left the project free

    def test_a_failed_payload_write_does_not_leave_the_project_locked(self):
        with mock.patch(
            "session.os.write", side_effect=OSError(errno.ENOSPC, "No space left")
        ):
            with self.assertRaises(LockUnavailable) as caught:
                self.s.acquire_lock()
        self.assertEqual(caught.exception.errno, errno.ENOSPC)
        self._session().acquire_lock()  # must not raise


class SessionLockInterruptTest(unittest.TestCase):
    """An interrupt on the boundary between taking the lock and recording it.

    The descriptor is the lock. If the assignment that records it sits outside
    the try, a signal arriving between the fsync and the assignment leaves the
    lock held on a descriptor nothing tracks: release_lock becomes a no-op,
    and the process is refused by its own lock for as long as it lives.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()
        self._sessions = [self.s]

    def tearDown(self):
        for s in self._sessions:
            s.release_lock()
        self._tmp.cleanup()

    def _session(self):
        s = Session(self.s.project_dir)
        self._sessions.append(s)
        return s

    def test_an_interrupt_just_after_the_payload_is_written_frees_the_lock(self):
        """The interrupt is aimed at the last step of the acquire: the payload
        is on disk and fsynced, and the very next thing the acquire does is
        raise. Everything up to that point has happened, so what is being
        pinned is that the descriptor is still closed and the project still
        free -- failing closed, not held by a ghost."""
        real_getpid = os.getpid
        calls = []

        def getpid():
            calls.append(True)
            if len(calls) == 2:  # the payload's pid was the first
                raise KeyboardInterrupt("signal on the boundary")
            return real_getpid()

        with mock.patch("session.os.getpid", getpid):
            with self.assertRaises(KeyboardInterrupt):
                self.s.acquire_lock()

        self.assertEqual(len(calls), 2, "the interrupt did not land where it was aimed")
        self.assertIsNone(
            self.s._lock_fd, "the lock is held on an untracked descriptor"
        )
        self.s.release_lock()  # must not raise
        self._session().acquire_lock()  # and the project is free again


class MsvcrtLockContractTest(unittest.TestCase):
    """The Windows primitive's contract, asserted from a machine without one.

    _msvcrt_try_lock is never executed on this platform, but it is a plain
    function of a descriptor and the msvcrt module `session` bound at import,
    so substituting that module exercises the branch honestly. What is pinned
    is the discrimination the fcntl branch already makes: contention is False,
    and everything else is raised so that acquire_lock reports it as
    LockUnavailable instead of naming an owner nobody can find or kill.
    """

    def setUp(self):
        fd, path = tempfile.mkstemp()
        self.fd = fd
        self.addCleanup(os.close, fd)
        self.addCleanup(os.unlink, path)

    def _fake_msvcrt(self, error=None):
        calls = []

        def locking(fd, mode, nbytes):
            calls.append((fd, mode, nbytes))
            if error is not None:
                raise error

        fake = types.SimpleNamespace(locking=locking, LK_NBLCK=1, LK_UNLCK=0)
        return fake, calls

    def test_the_msvcrt_lock_says_so_when_it_took_the_file(self):
        fake, calls = self._fake_msvcrt()
        with mock.patch.object(session, "msvcrt", fake):
            self.assertTrue(session._msvcrt_try_lock(self.fd))
        self.assertEqual(calls, [(self.fd, fake.LK_NBLCK, 1)])

    def test_the_msvcrt_lock_reports_a_conflict_rather_than_raising(self):
        """EACCES is what the CRT sets for a locking violation, which under
        LK_NBLCK is contention; EDEADLOCK is the retrying mode giving up."""
        for number in (errno.EACCES, errno.EDEADLOCK):
            with self.subTest(errno=number):
                fake, _ = self._fake_msvcrt(OSError(number, "locking violation"))
                with mock.patch.object(session, "msvcrt", fake):
                    self.assertFalse(session._msvcrt_try_lock(self.fd))

    def test_the_msvcrt_lock_re_raises_anything_that_is_not_a_conflict(self):
        """A bad descriptor, a bad argument, a full disk: none of them mean
        another session owns the project, and returning False for all of them
        is how "somebody has it" came to mean "something went wrong"."""
        for number in (errno.EBADF, errno.EINVAL, errno.ENOSPC):
            with self.subTest(errno=number):
                fake, _ = self._fake_msvcrt(OSError(number, "x"))
                with mock.patch.object(session, "msvcrt", fake):
                    with self.assertRaises(OSError) as caught:
                        session._msvcrt_try_lock(self.fd)
                self.assertEqual(caught.exception.errno, number)

    def test_a_failed_seek_is_not_reported_as_a_conflict(self):
        """The seek is part of the primitive -- msvcrt.locking works from the
        current offset -- so its failures belong to the same contract."""
        fake, calls = self._fake_msvcrt()
        with mock.patch.object(session, "msvcrt", fake), \
                mock.patch("session.os.lseek", side_effect=OSError(errno.EBADF, "x")):
            with self.assertRaises(OSError):
                session._msvcrt_try_lock(self.fd)
        self.assertEqual(calls, [], "the lock was attempted from an unknown offset")


if __name__ == "__main__":
    unittest.main()
