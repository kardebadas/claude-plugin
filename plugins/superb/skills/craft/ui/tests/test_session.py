import calendar
import contextlib
import errno
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import session
from session import (
    ROUND_RE,
    LockHeld,
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
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

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
        traceback that names nothing a user can act on."""
        self.s.lock_path.mkdir()
        with self.assertRaises(LockHeld):
            self.s.acquire_lock()
        with self.assertRaises(LockHeld):
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


if __name__ == "__main__":
    unittest.main()
