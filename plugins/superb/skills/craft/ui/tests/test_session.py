import calendar
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import session
from session import (
    ROUND_RE,
    LockHeld,
    Session,
    pid_alive,
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


class SessionLockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Session(self._tmp.name)
        self.s.ensure_dirs()

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _dead_pid():
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def test_acquiring_writes_our_pid(self):
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_a_live_lock_is_refused(self):
        self.s.acquire_lock()
        with self.assertRaises(LockHeld) as caught:
            Session(self.s.project_dir).acquire_lock()
        self.assertEqual(caught.exception.pid, os.getpid())
        self.assertTrue(caught.exception.started_at)

    def test_a_stale_lock_is_reclaimed(self):
        write_json_atomic(self.s.lock_path, {"pid": self._dead_pid(), "started_at": "old"})
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_a_corrupt_lock_is_reclaimed(self):
        self.s.lock_path.write_text("{not json", encoding="utf-8")
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_force_takes_over_a_live_lock(self):
        write_json_atomic(self.s.lock_path, {"pid": os.getpid(), "started_at": "now"})
        other = Session(self.s.project_dir)
        other.acquire_lock(force=True)
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_release_removes_the_lock(self):
        self.s.acquire_lock()
        self.s.release_lock()
        self.assertFalse(self.s.lock_path.exists())
        Session(self.s.project_dir).acquire_lock()  # must not raise

    def test_release_leaves_someone_elses_lock_alone(self):
        write_json_atomic(self.s.lock_path, {"pid": 1, "started_at": "old"})
        self.s.release_lock()
        self.assertTrue(self.s.lock_path.exists())

    def test_pid_alive_agrees_with_reality(self):
        self.assertTrue(pid_alive(os.getpid()))
        self.assertFalse(pid_alive(self._dead_pid()))

    def test_pid_alive_reads_a_pid_that_json_carried_as_a_string(self):
        """JSON carries whatever the writer put there, and a lock naming its
        holder as "1234" names a live process just as surely as 1234 does.
        Without the int() coercion the check answers "dead" and the whole
        refusal turns into a theft, with every other test still green."""
        self.assertTrue(pid_alive(str(os.getpid())))
        self.assertFalse(pid_alive(str(self._dead_pid())))

    def test_pid_alive_says_no_to_a_pid_that_is_not_a_process(self):
        """kill(2) reads 0 and negatives as process groups, so a lock claiming
        "pid": 0 would read as a live holder and could only be cleared with
        --force. Nothing at or below zero is a process to ask about."""
        self.assertFalse(pid_alive(0))
        self.assertFalse(pid_alive(-1))
        self.assertFalse(pid_alive(-os.getpid()))


class SessionLockHardeningTest(unittest.TestCase):
    """Tests for the parts of the lock the happy-path tests above do not pin.

    Each one names a single-line change to session.py that would otherwise
    pass the whole suite: dropping O_EXCL, signalling the pid it asks about,
    reclaiming a lock it should refuse, writing a timestamp nobody can read.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.s = Session(self.root)
        self.s.ensure_dirs()

    def tearDown(self):
        self._tmp.cleanup()

    @contextlib.contextmanager
    def _sleeping_child(self):
        """A real process, alive for the duration, owned by this user.

        The only honest stand-in for "another craft session is running": a live
        pid that is not ours, so force and refusal can be told apart from the
        no-op they collapse into when the holder pid happens to be our own.
        """
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            yield proc
        finally:
            proc.kill()
            proc.wait()

    def test_the_lock_lives_in_the_session_directory(self):
        self.assertEqual(self.s.lock_path, self.s.craft_dir / "session.lock")

    def test_acquiring_creates_the_session_directory(self):
        """The server takes the lock before anything else has run."""
        fresh = Session(self.root / "never-used")
        self.assertFalse(fresh.craft_dir.exists())
        fresh.acquire_lock()
        self.assertTrue(fresh.lock_path.is_file())
        self.assertEqual(read_json(fresh.lock_path)["pid"], os.getpid())

    def test_the_lock_file_is_created_exclusively(self):
        """The whole guarantee rests on the create, not on a prior look.

        A read-then-write implementation ("is there a lock? no -- write one")
        passes every other test here and still lets two servers that start in
        the same millisecond both believe they won. os.link makes the kernel
        the arbiter exactly as O_CREAT|O_EXCL did -- it refuses a name that
        exists -- and it publishes a file that already holds its payload, so
        this asserts both halves: the lock arrived by an exclusive primitive,
        and it named its holder the moment it became visible.
        """
        real_link = session.os.link
        published = []

        def recording_link(src, dst, *args, **kwargs):
            result = real_link(src, dst, *args, **kwargs)
            if str(dst) == str(self.s.lock_path):
                published.append(Path(dst).read_text(encoding="utf-8"))
            return result

        with mock.patch("session.os.link", recording_link):
            self.s.acquire_lock()

        self.assertTrue(
            published, "the lock file was never published through os.link"
        )
        for payload in published:
            self.assertEqual(json.loads(payload)["pid"], os.getpid())

        # And the primitive is the exclusive one: a second publish of the same
        # name fails rather than overwriting the holder that is already there.
        fd, tmp = tempfile.mkstemp(dir=str(self.s.craft_dir))
        os.close(fd)
        try:
            with self.assertRaises(FileExistsError):
                os.link(tmp, str(self.s.lock_path))
        finally:
            os.unlink(tmp)

    def test_a_second_acquirer_cannot_win_while_the_first_is_publishing(self):
        """The lock is never visible in a state that names nobody.

        The old implementation created the lock with O_CREAT|O_EXCL and only
        then wrote its JSON, so between those two syscalls the file existed and
        was zero bytes. A second acquirer arriving in that window read it as
        unreadable, called it unowned, unlinked it and made its own -- and both
        sessions then believed they held the project, with the file naming the
        second. This interleaves two acquires deterministically at the instant
        the lock file first appears -- no threads, no sleeps -- and requires
        the second one to be refused.
        """
        other = Session(self.s.project_dir)
        state = {"running": False, "outcome": None}

        def run_other_acquirer():
            if state["running"] or state["outcome"] is not None:
                return  # the nested acquire must not re-enter this hook
            state["running"] = True
            try:
                other.acquire_lock()
                state["outcome"] = "won"
            except LockHeld:
                state["outcome"] = "refused"
            finally:
                state["running"] = False

        real_open = session.os.open
        real_link = session.os.link

        def hooked_open(path, *args, **kwargs):
            fd = real_open(path, *args, **kwargs)
            if str(path) == str(self.s.lock_path):
                run_other_acquirer()  # the lock exists now: is it complete?
            return fd

        def hooked_link(src, dst, *args, **kwargs):
            result = real_link(src, dst, *args, **kwargs)
            if str(dst) == str(self.s.lock_path):
                run_other_acquirer()  # the lock exists now: is it complete?
            return result

        with mock.patch("session.os.open", hooked_open), \
                mock.patch("session.os.link", hooked_link):
            self.s.acquire_lock()

        self.assertEqual(
            state["outcome"],
            "refused",
            "a second acquirer took the project while the first was publishing",
        )
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_acquire_gives_up_rather_than_spinning_forever(self):
        """The reclaim path loops. A lock that keeps reappearing between the
        unlink and the create must end in a refusal, not a hung server."""
        real_link = session.os.link
        attempts = []

        def always_taken(src, dst, *args, **kwargs):
            if str(dst) == str(self.s.lock_path):
                attempts.append(str(dst))
                raise FileExistsError(17, "File exists", str(dst))
            return real_link(src, dst, *args, **kwargs)

        with mock.patch("session.os.link", always_taken):
            with self.assertRaises(LockHeld) as caught:
                self.s.acquire_lock()

        self.assertGreater(len(attempts), 1, "it never retried")
        self.assertLess(len(attempts), 50, "the retry is not bounded tightly enough")
        # Nobody was identified, so pid is None -- not the string "unknown",
        # which a caller reaching for int(exc.pid) would choke on.
        self.assertIsNone(caught.exception.pid)
        self.assertIn("unknown", str(caught.exception))

    def test_the_refusal_names_the_holder_on_disk(self):
        """The message is the whole user-facing value of the refusal: it is how
        someone finds the other session and decides whether to --force."""
        self.s.acquire_lock()
        on_disk = read_json(self.s.lock_path)
        with self.assertRaises(LockHeld) as caught:
            Session(self.s.project_dir).acquire_lock()
        self.assertEqual(caught.exception.pid, on_disk["pid"])
        self.assertEqual(caught.exception.started_at, on_disk["started_at"])
        message = str(caught.exception)
        self.assertIn(str(on_disk["pid"]), message)
        self.assertIn(on_disk["started_at"], message)

    def test_a_lock_held_by_another_live_process_is_refused(self):
        """The refusal, with a holder that is genuinely somebody else -- so it
        cannot pass by accident on a check that compares pids to our own."""
        with self._sleeping_child() as proc:
            write_json_atomic(
                self.s.lock_path, {"pid": proc.pid, "started_at": "old"}
            )
            with self.assertRaises(LockHeld) as caught:
                self.s.acquire_lock()
            self.assertEqual(caught.exception.pid, proc.pid)
            self.assertEqual(read_json(self.s.lock_path)["pid"], proc.pid)

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

    def test_a_string_pid_on_disk_is_reported_as_an_int(self):
        """LockHeld declares pid: int, and a lock may name its holder as the
        JSON string "1234" -- hand-edited, or written by some other tool. The
        holder is still refused, and the pid a caller reads off the exception
        is still something int() has already been applied to."""
        with self._sleeping_child() as proc:
            write_json_atomic(
                self.s.lock_path, {"pid": str(proc.pid), "started_at": "old"}
            )
            with self.assertRaises(LockHeld) as caught:
                self.s.acquire_lock()
            self.assertIsInstance(caught.exception.pid, int)
            self.assertEqual(caught.exception.pid, proc.pid)
            self.assertIn(str(proc.pid), str(caught.exception))
            self.assertEqual(read_json(self.s.lock_path)["pid"], str(proc.pid))

    def test_a_lock_that_is_a_directory_is_refused_rather_than_crashing(self):
        """Anything can be sitting at that name. A directory there cannot be
        read, cannot be unlinked, and cannot be rescued by --force, so all
        three entry points have to say so rather than raise IsADirectoryError
        out of a traceback that names nothing a user can act on."""
        self.s.lock_path.mkdir()
        with self.assertRaises(LockHeld):
            self.s.acquire_lock()
        with self.assertRaises(LockHeld):
            self.s.acquire_lock(force=True)
        self.s.release_lock()  # shutdown must still get out
        self.assertTrue(self.s.lock_path.is_dir())
        self.assertEqual(
            sorted(p.name for p in self.s.craft_dir.iterdir()),
            ["session.lock"],
            "a temp file was left behind by the failed acquires",
        )

    def test_a_lock_claiming_pid_zero_is_reclaimed(self):
        """The lock file is data, and 0 is not a process. Read as one it would
        answer "alive" through kill(2)'s process-group rule and hold the
        project shut against a session that has every right to it."""
        write_json_atomic(self.s.lock_path, {"pid": 0, "started_at": "old"})
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_force_takes_over_a_lock_held_by_another_live_process(self):
        """force is the escape hatch, and it has to work against a real live
        holder, replacing both fields rather than editing the pid in place.

        This is the load-bearing force test, and the only one: the sibling in
        SessionLockTest seeds the lock with our own pid, so it passes even
        against a force that does nothing at all. Do not prune this as a
        duplicate of it -- the duplicate is the one that proves nothing."""
        with self._sleeping_child() as proc:
            write_json_atomic(
                self.s.lock_path, {"pid": proc.pid, "started_at": "old"}
            )
            self.s.acquire_lock(force=True)
            data = read_json(self.s.lock_path)
            self.assertEqual(data["pid"], os.getpid())
            self.assertNotEqual(data["started_at"], "old")

    def test_a_lock_missing_its_pid_is_reclaimed(self):
        """A half-written or hand-edited lock names nobody, so it holds nobody
        out. It must not be read as a live holder, and must not raise."""
        write_json_atomic(self.s.lock_path, {"started_at": "old"})
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

    def test_an_empty_lock_file_is_reclaimed(self):
        """A zero-byte lock names nobody, so it holds nobody out.

        No live acquirer produces this shape any more -- the lock is published
        with its payload already in it -- so what is left is a file some other
        accident truncated. Reclaiming it is still the right call: refusing on
        it would wedge the project shut behind a holder nobody can name."""
        self.s.lock_path.write_text("", encoding="utf-8")
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())

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

    def test_pid_alive_does_not_signal_the_process_it_asks_about(self):
        """It asks, it does not act. Signal 0 is the question; any real signal
        number turns a liveness check into a way to kill the other session."""
        with self._sleeping_child() as proc:
            self.assertTrue(pid_alive(proc.pid))
            with self.assertRaises(subprocess.TimeoutExpired):
                proc.wait(timeout=0.5)

    def test_pid_alive_says_yes_when_the_pid_is_someone_elses(self):
        """EPERM means the process exists and is not ours -- the strongest
        possible evidence of a live holder, and it must not read as absent."""
        with mock.patch("session.os.kill", side_effect=PermissionError(1, "nope")):
            self.assertTrue(pid_alive(os.getpid()))

    def test_pid_alive_says_no_when_the_pid_is_not_a_pid(self):
        """The value comes out of a JSON file anyone may edit."""
        self.assertFalse(pid_alive(None))
        self.assertFalse(pid_alive("not-a-pid"))
        self.assertFalse(pid_alive([]))

    def test_releasing_a_lock_that_is_not_there_is_not_an_error(self):
        """Shutdown runs whether or not startup got as far as the lock."""
        self.assertFalse(self.s.lock_path.exists())
        self.s.release_lock()
        self.assertFalse(self.s.lock_path.exists())

    def test_releasing_clears_a_lock_nobody_can_read(self):
        """An unreadable lock names no owner, so it would otherwise wedge the
        project shut until someone deleted the file by hand."""
        self.s.lock_path.write_text("{not json", encoding="utf-8")
        self.s.release_lock()
        self.assertFalse(self.s.lock_path.exists())

    def test_the_lock_is_per_project(self):
        """One lock per project directory, not one per machine."""
        other_root = self.root / "other-project"
        other = Session(other_root)
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
        outside assertRaises, so a release that left the lock behind would come
        back as a LockHeld and fail the test.
        """
        self.s.acquire_lock()
        self.assertEqual(read_json(self.s.lock_path)["pid"], os.getpid())
        self.s.release_lock()
        self.assertFalse(self.s.lock_path.exists())
        self.s.acquire_lock()
        second = read_json(self.s.lock_path)
        self.assertEqual(second["pid"], os.getpid())
        self.assertTrue(second["started_at"])
        self.assertTrue(self.s.lock_path.is_file())
        self.assertEqual(
            [p.name for p in self.s.craft_dir.iterdir()], ["session.lock"]
        )


if __name__ == "__main__":
    unittest.main()
