"""The craft UI command line.

Everything here spawns real processes, so two rules run through the file.

Nothing sleeps for a fixed duration where a condition can be polled: a
passing run leaves the moment the condition holds, and a deadline is only how
a failing one ends. And every child is reaped whatever happens -- a leaked
server holds the project lock and sits on an idle timeout measured in hours,
so it would not fail this test, it would fail somebody else's an hour later.
"""
# Deliberate: kept so any annotation added later may use `int | None` syntax
# while this project's floor is Python 3.9. Do not delete.
from __future__ import annotations

import ast
import contextlib
import errno
import functools
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import craftui
import server as server_module
import session as session_module
from server import CraftServer, make_key
from session import LockHeld, Session, read_json, write_json_atomic

UI_DIR = Path(__file__).resolve().parent.parent
CRAFTUI = str(UI_DIR / "craftui.py")

# Long enough that a loaded machine does not fail a test that would pass, and
# short enough that a hung child ends the run rather than the suite.
PATIENCE_S = 30

# What has to be left over after the drain has run to its full bound: the
# lock release, the log line, and the interpreter shutting down. "Comfortably
# inside" from craftui's own comment, written as a number so the two
# constants it relates can be compared rather than each checked against a
# literal of its own.
HEADROOM_AFTER_THE_DRAIN_S = 2.0

# How long a stolen lock may go unnoticed before the holder is running on a
# project somebody else owns. Measured over twenty runs each way: 0.225-0.241 s
# idle, 0.199-0.235 s with twelve spinners on twelve cpus. Eight times the
# worst of that, so a loaded machine passes -- and well under the five seconds
# a widened WATCHDOG_INTERVAL_S would cost, so widening it does not.
NOTICE_DEADLINE_S = 2.0


def run(*args, **kw):
    return subprocess.run(
        [sys.executable, CRAFTUI] + list(args),
        capture_output=True,
        text=True,
        timeout=kw.pop("timeout", PATIENCE_S),
        **kw
    )


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


def wait_until(predicate, timeout=PATIENCE_S):
    """Poll until something another process did becomes visible."""
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def free_port():
    """A port nothing is listening on. Racy by nature; nothing here is
    load-bearing on it staying free, which is why the test that uses it
    asserts what was bound rather than that the bind succeeded."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class CommandTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.session = Session(self.root)
        self.info_path = Path(self.root) / ".craft" / "server-info"
        self.lock_path = Path(self.root) / ".craft" / "session.lock"
        self.log_path = Path(self.root) / ".craft" / "server.log"
        self._pids = []
        # Registered before anything that can fail, and LIFO: the children go
        # first, then the tree they were writing into. `stop` does not exist
        # until Task 9, so this is the whole of the reaping.
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._reap)

    def _reap(self):
        for pid in self._pids:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if not pid_alive(pid):
                    break
                try:
                    os.kill(pid, sig)
                except OSError:
                    break
                wait_until(lambda: not pid_alive(pid), timeout=5)

    def serve(self, *extra, **kw):
        result = run("serve", "--project-dir", self.root, *extra, **kw)
        info = self.info(missing_ok=True)
        if info and "pid" in info:
            self._pids.append(info["pid"])
        return result

    def info(self, missing_ok=False):
        try:
            return json.loads(self.info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if missing_ok:
                return None
            raise

    def log(self):
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def locked_out(self):
        """Whether a fresh acquirer is refused the project right now.

        The kernel's answer, not a file's contents: this is what "the server
        holds the lock" has to mean.
        """
        other = Session(self.root)
        try:
            other.acquire_lock()
        except LockHeld:
            return True
        other.release_lock()
        return False

    def fetch(self, url):
        return urllib.request.urlopen(url, timeout=10)


class ServeTest(CommandTestCase):
    def test_serve_writes_server_info_and_prints_it(self):
        result = self.serve()
        self.assertEqual(result.returncode, 0, result.stderr + self.log())
        printed = json.loads(result.stdout.strip())
        self.assertEqual(printed["type"], "server-started")
        self.assertEqual(printed, self.info())
        self.assertGreater(printed["port"], 0)
        self.assertIn("key=", printed["url"])
        self.assertEqual(
            sorted(printed), ["key", "pid", "port", "type", "url"],
            "server-info is read by wait, status and stop; its keys are a contract",
        )
        self.assertTrue(pid_alive(printed["pid"]), "server-info names a dead process")

    def test_the_advertised_url_actually_serves_the_page(self):
        self.serve()
        with self.fetch(self.info()["url"]) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers.get("Content-Type", ""))

    def test_the_advertised_url_names_the_address_that_was_bound(self):
        """localhost may resolve to ::1, and this server binds 127.0.0.1
        only, so the URL says the address rather than a name for it."""
        self.serve()
        info = self.info()
        self.assertTrue(
            info["url"].startswith("http://127.0.0.1:{}/".format(info["port"])),
            info["url"],
        )

    def test_the_advertised_key_is_the_one_the_server_wants(self):
        """A blank or a constant key would still produce a URL with `key=` in
        it, and would still serve the page. This is what tells them apart."""
        self.serve()
        info = self.info()
        for target in ("/", "/?key=nope", "/api/round?key="):
            with self.subTest(target=target):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.fetch("http://127.0.0.1:{}{}".format(info["port"], target))
                caught.exception.close()
                self.assertEqual(caught.exception.code, 403)
        self.assertGreaterEqual(len(info["key"]), 32)

    def test_two_sessions_do_not_share_a_key(self):
        # Both return codes are asserted before either parse. Without them a
        # serve that failed arrives as `JSONDecodeError: Expecting value:
        # line 1 column 1` naming neither the cause nor which of the two
        # commands produced it -- which is exactly how the one flaky failure
        # this file has ever produced presented itself.
        started = self.serve()
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        first = json.loads(started.stdout)
        with tempfile.TemporaryDirectory() as other_root:
            other = run("serve", "--project-dir", other_root)
            self.assertEqual(other.returncode, 0, other.stdout + other.stderr)
            second = json.loads(other.stdout)
            self._pids.append(second["pid"])
            self.assertNotEqual(first["key"], second["key"])

    def test_the_server_holds_the_lock(self):
        self.serve()
        self.assertTrue(self.locked_out(), "the project was not actually locked")
        lock = read_json(self.lock_path)
        self.assertEqual(lock["pid"], self.info()["pid"])

    def test_serve_never_writes_the_brief(self):
        self.serve()
        self.assertFalse((Path(self.root) / "CRAFT.md").exists())

    def test_a_second_serve_is_refused_with_exit_4(self):
        self.serve()
        held = self.info()
        result = self.serve()
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("LOCKED", result.stdout)
        self.assertIn("kill", result.stdout)
        self.assertIn(str(held["pid"]), result.stdout)

    def test_a_refused_serve_leaves_the_running_session_alone(self):
        """The refusal must not be the thing that breaks the session it was
        refused by: server-info is what wait, status and stop read."""
        self.serve()
        before = self.info()
        self.assertEqual(self.serve().returncode, 4)
        self.assertEqual(self.info(), before)
        self.assertTrue(pid_alive(before["pid"]))
        with self.fetch(before["url"]) as response:
            self.assertEqual(response.status, 200)

    def test_a_stale_serve_error_does_not_refuse_a_fresh_serve(self):
        """Nothing here unlinks anything, so the serve-error a `serve` finds
        is as likely to be a refusal from ten minutes ago as this attempt's
        answer. Without matching it to the attempt it belongs to, a project
        that was once busy is refused for ever after -- and the pid it names
        belongs to nobody, so the remedy it offers cannot be carried out."""
        (Path(self.root) / ".craft").mkdir(parents=True, exist_ok=True)
        (Path(self.root) / ".craft" / "serve-error").write_text(
            json.dumps({
                "type": "serve-failed",
                "attempt_pid": 999999,
                "exit_code": 4,
                "message": "LOCKED  another craft session (pid 1) owns this",
            }), encoding="utf-8")
        result = self.serve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("LOCKED", result.stdout)
        self.assertTrue(pid_alive(self.info()["pid"]))

    def test_a_second_serve_that_is_refused_does_not_poison_the_next_one(self):
        """The same thing end to end: refused once, the holder goes, and the
        next serve has to succeed."""
        self.serve()
        pid = self.info()["pid"]
        self.assertEqual(self.serve().returncode, 4)
        os.kill(pid, signal.SIGKILL)
        self.assertTrue(wait_until(lambda: not pid_alive(pid)))
        result = self.serve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_killed_server_leaves_the_project_immediately_lockable(self):
        """The kernel drops a flock on process death, so there is no reclaim
        step and no --force."""
        self.serve()
        pid = self.info()["pid"]
        os.kill(pid, signal.SIGKILL)
        self.assertTrue(wait_until(lambda: not pid_alive(pid)))
        self.assertNotIn("session ended", self.log(),
                         "a killed server cannot have exited cleanly")
        result = self.serve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(self.info()["pid"], pid)

    def test_sigterm_stops_the_server_gracefully(self):
        """What Task 9's `stop` will send.

        The death alone proves nothing: with no handler installed SIGTERM's
        default action kills the process, the kernel drops the flock, and
        every observable outside the process is identical -- while the drain
        this whole task exists for has been skipped. So this asserts the
        clean-exit line, which only the handler's path writes.
        """
        self.serve()
        pid = self.info()["pid"]
        os.kill(pid, signal.SIGTERM)
        self.assertTrue(wait_until(lambda: not pid_alive(pid)))
        self.assertTrue(wait_until(lambda: "session ended cleanly" in self.log()),
                        "SIGTERM killed the server instead of shutting it down")
        self.assertFalse(self.locked_out())
        self.assertTrue(
            self.info_path.exists(),
            "server-info must survive a clean stop -- the port is reused from it",
        )

    def test_an_explicit_port_is_honoured(self):
        port = free_port()
        result = self.serve("--port", str(port))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.info()["port"], port)

    def test_a_busy_explicit_port_is_reported_rather_than_waited_out(self):
        """A port somebody else holds is an answer, not a fifteen-second
        silence followed by a timeout that names the wrong cause."""
        with socket.socket() as taken:
            taken.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            taken.bind(("127.0.0.1", 0))
            taken.listen(1)
            port = taken.getsockname()[1]
            started = time.monotonic()
            result = self.serve("--port", str(port))
            elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(str(port), result.stdout)
        self.assertLess(elapsed, 10, "the failure was waited out, not reported")
        self.assertTrue(wait_until(lambda: not self.locked_out()),
                        "a failed start kept the project locked")

    def test_a_stolen_lock_file_shuts_the_server_down(self):
        """Nothing can stop a second acquirer once the name is gone, so the
        holder is the only party left that can notice."""
        self.serve()
        pid = self.info()["pid"]
        self.lock_path.unlink()
        self.assertTrue(
            wait_until(lambda: not pid_alive(pid)),
            "server kept running after its lock file was removed",
        )
        self.assertIn("session.lock", self.log())
        self.assertIn("another session", self.log())

    def test_a_stolen_lock_is_noticed_within_a_couple_of_seconds(self):
        """WATCHDOG_INTERVAL_S is the width of the window in which two
        sessions can both believe they own the project, and nothing else in
        the suite fails if it is widened: at five seconds every other test
        stays green while that window grows twentyfold. This is what the
        constant is for, asserted as the delay a user would actually suffer
        rather than as the number itself.
        """
        self.serve()
        pid = self.info()["pid"]
        started = time.monotonic()
        self.lock_path.unlink()
        self.assertTrue(
            wait_until(lambda: "another session" in self.log()),
            "the holder never noticed that its lock file had gone",
        )
        self.assertLess(
            time.monotonic() - started, NOTICE_DEADLINE_S,
            "the window in which two sessions can both own this project is "
            "wider than WATCHDOG_INTERVAL_S is written to make it",
        )
        self.assertTrue(wait_until(lambda: not pid_alive(pid)))

    def test_a_replaced_lock_file_shuts_the_server_down(self):
        """Removal is not the only way the name stops meaning our inode."""
        self.serve()
        pid = self.info()["pid"]
        impostor = self.lock_path.with_name("impostor")
        impostor.write_text("{}", encoding="utf-8")
        os.replace(str(impostor), str(self.lock_path))
        self.assertTrue(
            wait_until(lambda: not pid_alive(pid)),
            "server kept running after its lock file was replaced",
        )

    def test_the_idle_timeout_exits_and_releases_the_lock(self):
        self.serve("--idle-timeout-minutes", "0.02")  # 1.2 s
        pid = self.info()["pid"]
        self.assertTrue(wait_until(lambda: not pid_alive(pid)), "idle server never exited")
        self.assertTrue(wait_until(lambda: "session ended cleanly" in self.log()),
                        "the idle exit did not go through the drain")
        # The lock file is never unlinked -- the kernel released the lock when
        # the process died. What matters is that the project is lockable again.
        self.assertFalse(self.locked_out())
        result = self.serve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_server_being_used_is_not_idle(self):
        """The other half of the clock. A watchdog that always shut down
        would pass the test above and lose the user's session mid-round."""
        self.serve("--idle-timeout-minutes", "0.03")  # 1.8 s
        info = self.info()
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            with self.fetch(info["url"]) as response:
                self.assertEqual(response.status, 200)
            time.sleep(0.3)
        self.assertTrue(pid_alive(info["pid"]), "a server in use was reaped as idle")

    def test_the_key_is_not_left_readable_by_the_rest_of_the_machine(self):
        """server-info carries a live credential into the user's project.

        write_json_atomic goes through mkstemp, which creates at 0600 and is
        not subject to the umask, and os.replace keeps the mode. That is a
        property of somebody else's function, which is why it is asserted
        here rather than assumed.
        """
        self.serve()
        mode = self.info_path.stat().st_mode
        self.assertEqual(mode & 0o077, 0, oct(mode))

    def test_the_log_never_carries_the_key(self):
        """The log is an ordinary 0644 file. The key must not be in it."""
        self.serve("--idle-timeout-minutes", "0.02")
        key = self.info()["key"]
        pid = self.info()["pid"]
        self.assertTrue(wait_until(lambda: not pid_alive(pid)))
        self.assertNotIn(key, self.log())

    def test_open_launches_the_browser_at_the_advertised_url(self):
        """webbrowser honours $BROWSER, so a script standing in for one is
        the whole test. Without this, deleting `if args.open:` breaks nothing
        that anything here can see."""
        opened = Path(self.root) / "opened.txt"
        fake = Path(self.root) / "fake-browser.sh"
        fake.write_text(
            '#!/bin/sh\nprintf "%s" "$1" > {}\n'.format(opened), encoding="utf-8")
        fake.chmod(0o755)
        env = dict(os.environ, BROWSER=str(fake))
        result = self.serve("--open", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(wait_until(opened.exists, timeout=10), "no browser was launched")
        self.assertEqual(opened.read_text(encoding="utf-8"), self.info()["url"])

    def test_without_open_no_browser_is_launched(self):
        opened = Path(self.root) / "opened.txt"
        fake = Path(self.root) / "fake-browser.sh"
        fake.write_text(
            '#!/bin/sh\nprintf "%s" "$1" > {}\n'.format(opened), encoding="utf-8")
        fake.chmod(0o755)
        self.serve(env=dict(os.environ, BROWSER=str(fake)))
        # A negative, so it is worth a fixed wait: long enough that the
        # launch above would have happened by now.
        time.sleep(1.0)
        self.assertFalse(opened.exists())

    def test_a_server_info_that_cannot_be_written_is_reported_not_waited_out(self):
        """A server nobody can be told the address of is a failed start, and
        the parent must hear that rather than time out fifteen seconds later
        with a message that names the wrong cause."""
        (Path(self.root) / ".craft").mkdir(parents=True, exist_ok=True)
        self.info_path.mkdir()  # a directory where the file has to go
        started = time.monotonic()
        result = self.serve()
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("server-info", result.stdout)
        self.assertLess(elapsed, 10, "the failure was waited out, not reported")
        self.assertTrue(wait_until(lambda: not self.locked_out()),
                        "a failed start kept the project locked")

    def test_a_bad_port_is_refused_by_the_parser_not_by_a_failed_bind(self):
        """A usage error, not exit 1 from a child that spawned, took the lock
        and then failed to bind. Both are non-zero, which is why the codes
        are what this asserts: the second spends a process and a lock to say
        something the flag itself could have said.

        The code moved from 2 to USAGE_EXIT when `wait` arrived, because 2 is
        TIMEOUT and a usage error is not an outcome. UsageExitTest is where
        that is argued; this is one of the two places it is observed through
        a real process.
        """
        for value in ("-1", "65536", "99999", "2147483648"):
            with self.subTest(value=value):
                result = self.serve("--port", value)
                self.assertEqual(
                    result.returncode, craftui.USAGE_EXIT,
                    result.stdout + result.stderr)
                self.assertIn("65535", result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertFalse(self.info_path.exists())
                self.assertFalse(self.locked_out())

    def test_a_port_that_is_not_a_number_is_refused(self):
        for value in ("1e3", "banana", "", " 1", "0x10", "+1"):
            with self.subTest(value=value):
                result = self.serve("--port", value)
                self.assertEqual(
                    result.returncode, craftui.USAGE_EXIT,
                    result.stdout + result.stderr)
                self.assertIn("port", result.stderr)
                self.assertFalse(self.info_path.exists())

    def test_a_bad_idle_timeout_is_refused_before_anything_starts(self):
        for value in ("0", "-1", "nan", "inf", "banana"):
            with self.subTest(value=value):
                result = self.serve("--idle-timeout-minutes", value)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(wait_until(lambda: not self.locked_out()))
                self.assertFalse(self.info_path.exists())


class HelperTest(unittest.TestCase):
    """read_server_info and server_alive are imported by Tasks 8 and 9, so
    every way they can be handed rubbish is part of their contract."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.session = Session(self._tmp.name)
        self.session.ensure_dirs()
        self.path = Path(self._tmp.name) / ".craft" / "server-info"

    def test_no_file_is_no_info_and_no_server(self):
        self.assertIsNone(craftui.read_server_info(self.session))
        self.assertFalse(craftui.server_alive(self.session))

    def test_a_half_written_file_is_no_info(self):
        self.path.write_text('{"port": 1', encoding="utf-8")
        self.assertIsNone(craftui.read_server_info(self.session))
        self.assertFalse(craftui.server_alive(self.session))

    def test_json_that_is_not_an_object_is_no_info(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(craftui.read_server_info(self.session))

    def test_a_directory_where_the_file_should_be_is_no_info(self):
        self.path.mkdir()
        self.assertIsNone(craftui.read_server_info(self.session))
        self.assertFalse(craftui.server_alive(self.session))

    def test_a_live_pid_is_a_live_server(self):
        self.path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        self.assertTrue(craftui.server_alive(self.session))

    def test_a_pid_that_is_not_a_pid_is_not_a_server(self):
        for value in (None, "unknown", -1, 0, [], 2 ** 70):
            with self.subTest(pid=value):
                self.path.write_text(json.dumps({"pid": value}), encoding="utf-8")
                self.assertFalse(craftui.server_alive(self.session))

    def test_a_process_we_may_not_signal_still_counts_as_alive(self):
        """EPERM says the process exists and is somebody else's, which is
        still a live holder. Nothing else in the suite reaches that arm, so
        it is reached deliberately: pid 1 is root's on any machine this runs
        on unprivileged."""
        if os.geteuid() == 0:
            self.skipTest("running as root, so nothing is unsignalable")
        with self.assertRaises(PermissionError):
            os.kill(1, 0)  # the premise, so this cannot pass vacuously
        self.path.write_text(json.dumps({"pid": 1}), encoding="utf-8")
        self.assertTrue(craftui.server_alive(self.session))

    def test_a_dead_pid_is_not_a_server(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self.path.write_text(json.dumps({"pid": dead.pid}), encoding="utf-8")
        self.assertFalse(craftui.server_alive(self.session))


class PortChoiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.session = Session(self._tmp.name)
        self.session.ensure_dirs()
        self.path = Path(self._tmp.name) / ".craft" / "server-info"

    def record(self, port):
        self.path.write_text(json.dumps({"port": port}), encoding="utf-8")

    def test_an_explicit_request_beats_the_recorded_port(self):
        self.record(free_port())
        self.assertEqual(craftui._pick_port(self.session, 4321), 4321)

    def test_a_recorded_port_is_reused_when_it_is_free(self):
        port = free_port()
        self.record(port)
        self.assertEqual(craftui._pick_port(self.session, 0), port)

    def test_a_recorded_port_somebody_else_took_is_not_reused(self):
        with socket.socket() as taken:
            taken.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            taken.bind(("127.0.0.1", 0))
            taken.listen(1)
            self.record(taken.getsockname()[1])
            self.assertEqual(craftui._pick_port(self.session, 0), 0)

    def test_a_port_left_in_time_wait_is_still_reusable(self):
        """A browser that talked to the last session leaves a TIME_WAIT
        behind on its port, and a bare bind is refused for it. CraftServer
        sets allow_reuse_address, so the probe has to ask the same question
        the real bind will -- otherwise the reuse this whole path exists for
        never once happens."""
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        accepted, _ = listener.accept()
        accepted.close()  # this side closes first, so this side waits
        client.close()
        listener.close()

        def bare_bind_refused():
            probe = socket.socket()
            try:
                probe.bind(("127.0.0.1", port))
                return False
            except OSError:
                return True
            finally:
                probe.close()

        if not wait_until(bare_bind_refused, timeout=3):
            self.skipTest("this kernel produced no TIME_WAIT to test against")
        self.record(port)
        self.assertTrue(craftui._port_free(port))
        self.assertEqual(craftui._pick_port(self.session, 0), port)

    def test_nothing_recorded_is_an_ephemeral_port(self):
        self.assertEqual(craftui._pick_port(self.session, 0), 0)

    def test_a_recorded_port_that_is_not_a_port_is_ignored(self):
        for value in (None, "http", -1, 0, 65536, 2 ** 40, [1]):
            with self.subTest(port=value):
                self.record(value)
                self.assertEqual(craftui._pick_port(self.session, 0), 0)


class BindFallbackTest(unittest.TestCase):
    """_pick_port probes and then _build_server binds, and the port can be
    taken between the two. Reproduced here by making the probe say yes about
    a port that is already listening, which is exactly what the losing side
    of that race sees."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.session = Session(self._tmp.name)
        self.session.ensure_dirs()
        self.taken = socket.socket()
        self.addCleanup(self.taken.close)
        self.taken.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.taken.bind(("127.0.0.1", 0))
        self.taken.listen(1)
        self.busy = self.taken.getsockname()[1]
        (Path(self._tmp.name) / ".craft" / "server-info").write_text(
            json.dumps({"port": self.busy}), encoding="utf-8")

    def args(self, port):
        import argparse
        return argparse.Namespace(port=port, idle_timeout_minutes=1.0)

    def test_a_reused_port_taken_since_the_probe_falls_back(self):
        real = craftui._port_free
        craftui._port_free = lambda port: True
        self.addCleanup(setattr, craftui, "_port_free", real)
        server = craftui._build_server(self.session, self.args(0), make_key())
        self.addCleanup(server.server_close)
        self.assertGreater(server.port, 0)
        self.assertNotEqual(server.port, self.busy)

    def test_a_port_the_user_named_is_never_silently_swapped(self):
        with self.assertRaises(OSError):
            craftui._build_server(self.session, self.args(self.busy), make_key())


class _ParkedWrite:
    """A write_json_atomic that stops in the middle of the write.

    The defect this exists for is a write outliving the lock, and the only
    way to observe it deterministically is to hold a write open across the
    shutdown rather than hope one lands there.
    """

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def __call__(self, path, obj):
        self.entered.set()
        self.release.wait(timeout=PATIENCE_S)
        session_module.write_json_atomic(path, obj)
        self.finished.set()


class ShutdownTestCase(unittest.TestCase):
    """A real server, holding the real lock, exactly as the child does."""

    def setUp(self):
        # shutdown_and_release says how the session ended, and in the child
        # that line goes to .craft/server.log because the child's stderr IS
        # that file. Here it would go to the runner's, so it is captured --
        # registered first, and so undone last, which also keeps anything
        # written during the cleanups out of the run's output.
        self.noise = io.StringIO()
        capture = contextlib.redirect_stderr(self.noise)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        self._parked = []
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.session = Session(self.root)
        self.session.ensure_dirs()
        self.session.acquire_lock()
        self.addCleanup(self.session.release_lock)
        self.key = make_key()
        self.server = CraftServer(self.session, self.key, port=0)
        self.addCleanup(self.server.server_close)
        serve = functools.partial(self.server.serve_forever, poll_interval=0.01)
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        self.addCleanup(self._join)
        self.addCleanup(self.server.shutdown)
        self.base = "http://127.0.0.1:{}".format(self.server.port)

    def _join(self):
        self.thread.join(timeout=10)
        self.assertFalse(self.thread.is_alive(), "the serving thread outlived shutdown()")

    def park_writes(self):
        parked = _ParkedWrite()
        real = server_module.write_json_atomic
        server_module.write_json_atomic = parked
        self.addCleanup(setattr, server_module, "write_json_atomic", real)
        self.addCleanup(parked.release.set)
        self._parked.append(parked)
        return parked

    def submit(self, number=1):
        """POST a round from a thread. Returns the thread; failures are the
        test's business only when it asks."""
        url = "{}/api/submit?key={}".format(self.base, self.key)
        body = json.dumps({"round": number, "answers": {"Q-1": {"text": "x"}}})
        outcome = []

        def send():
            request = urllib.request.Request(
                url, data=body.encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=PATIENCE_S) as response:
                    outcome.append(response.status)
            except Exception as exc:  # recorded, not raised, off the main thread
                # An HTTPError is also a response, and it owns a socket the
                # interpreter will otherwise complain about at some unrelated
                # test's expense.
                getattr(exc, "close", lambda: None)()
                outcome.append(exc)

        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        self.addCleanup(self._join_sender, thread)
        return thread, outcome

    def _join_sender(self, thread):
        """Join a sender, having first let go of anything holding it up.

        Cleanups run LIFO and park_writes always runs before submit, so its
        release lands AFTER this join -- and the sender cannot answer until
        that release happens. A test that left a write parked therefore paid
        this join's full ten seconds every run, waiting on an event a later
        cleanup was going to set. It was 10.318 s of a 46 s suite, for a
        drain the test bounds at 0.3 s. Releasing here rather than relying on
        the ordering keeps the trap shut for every test that parks a write,
        not just the one that fell into it.
        """
        for parked in self._parked:
            parked.release.set()
        thread.join(10)

    def locked_out(self):
        other = Session(self.root)
        try:
            other.acquire_lock()
        except LockHeld:
            return True
        other.release_lock()
        return False


class ShutdownDrainTest(ShutdownTestCase):
    """daemon_threads = True, so server_close() joins nothing.

    A handler inside write_json_atomic when the server stops keeps running,
    and reached os.replace after the process had released the project lock --
    session one writing into session two's project after session two had
    legitimately acquired it. Two live writers on one project is the single
    thing the lock exists to prevent.
    """

    def test_the_lock_is_not_released_until_an_in_flight_write_has_finished(self):
        parked = self.park_writes()
        self.submit()
        self.assertTrue(parked.entered.wait(PATIENCE_S), "the write never started")

        done = threading.Event()
        outcome = []

        def stop():
            outcome.append(
                craftui.shutdown_and_release(self.server, self.session, PATIENCE_S))
            done.set()

        stopper = threading.Thread(target=stop, daemon=True)
        stopper.start()
        self.addCleanup(stopper.join, PATIENCE_S)

        # A negative, so it is worth a fixed wait: for as long as the write is
        # parked, the shutdown must still be waiting and the project must
        # still be ours.
        self.assertFalse(done.wait(0.5), "the shutdown finished with a write in flight")
        self.assertTrue(self.locked_out(), "the lock went while a write was in flight")
        self.assertFalse(parked.finished.is_set())

        parked.release.set()
        self.assertTrue(done.wait(PATIENCE_S), "the shutdown never finished")
        self.assertEqual(outcome, [True])
        self.assertTrue(parked.finished.is_set())
        self.assertFalse(self.locked_out(), "the project stayed locked after the drain")

    def test_the_write_that_held_the_shutdown_open_actually_landed(self):
        parked = self.park_writes()
        self.submit(number=7)
        self.assertTrue(parked.entered.wait(PATIENCE_S))
        parked.release.set()
        self.assertTrue(craftui.shutdown_and_release(self.server, self.session, PATIENCE_S))
        self.assertEqual(read_json(self.session.answers_path(7))["round"], 7)

    def test_a_wedged_write_cannot_hold_the_exit_open_forever(self):
        parked = self.park_writes()
        self.submit()
        self.assertTrue(parked.entered.wait(PATIENCE_S))
        started = time.monotonic()
        drained = craftui.shutdown_and_release(self.server, self.session, 0.3)
        elapsed = time.monotonic() - started
        noise = self.noise
        self.assertFalse(drained, "a parked write reported itself drained")
        self.assertLess(elapsed, 10, "the bound on the wait is not a bound")
        self.assertGreaterEqual(elapsed, 0.3, "the wait was not waited")
        self.assertIn("1", noise.getvalue())
        self.assertIn("did not finish", noise.getvalue())
        self.assertIn("session ended with writes still running", noise.getvalue(),
                      "an exit that skipped the drain reported itself as clean")
        self.assertFalse(self.locked_out(), "a wedged write held the project forever")

    def test_a_shutdown_with_nothing_in_flight_does_not_wait(self):
        started = time.monotonic()
        self.assertTrue(craftui.shutdown_and_release(self.server, self.session, PATIENCE_S))
        self.assertLess(time.monotonic() - started, 5)
        self.assertFalse(self.locked_out())
        self.assertIn("session ended cleanly", self.noise.getvalue(),
                      "a drained exit did not say so")

    def test_shutting_down_twice_is_not_an_error(self):
        self.assertTrue(craftui.shutdown_and_release(self.server, self.session, 1.0))
        self.assertTrue(craftui.shutdown_and_release(self.server, self.session, 1.0))

    def test_no_new_write_may_start_while_the_drain_waits(self):
        """The other half of the drain: waiting for the writes already inside
        the gate is worth nothing if a new one may walk in behind them.

        Asked of the gate rather than over HTTP, because by the time the
        drain is waiting the listening socket is shut and a fresh connection
        never reaches a handler at all -- so an HTTP request would prove the
        listener closed and say nothing about the gate. begin_write is the
        call a handler already accepted makes on its way to writing, which
        is the request that can still be in the building.
        """
        parked = self.park_writes()
        self.submit(number=1)
        self.assertTrue(parked.entered.wait(PATIENCE_S))

        done = threading.Event()
        stopper = threading.Thread(
            target=lambda: (craftui.shutdown_and_release(
                self.server, self.session, PATIENCE_S), done.set()),
            daemon=True)
        stopper.start()
        self.addCleanup(stopper.join, PATIENCE_S)
        self.addCleanup(parked.release.set)

        self.assertTrue(
            wait_until(lambda: self.server.writes_closed, timeout=10),
            "the shutdown never shut the write gate")
        self.assertFalse(self.server.begin_write(),
                         "a new write was admitted while the drain waited")
        self.assertEqual(self.server.writes_in_flight, 1, "the parked write only")

        parked.release.set()
        self.assertTrue(done.wait(PATIENCE_S))
        self.assertFalse(self.session.answers_path(2).exists(),
                         "a refused write wrote anyway")


class _NotingStderr(io.StringIO):
    """A stderr that records WHEN it was written into somebody's call list.

    A write to stderr leaves no trace in a _Recorder's calls, so an ordering
    that puts it on the wrong side of release_lock is invisible to a test
    that only watches the recorder. This puts the two on one timeline.
    """

    def __init__(self, calls):
        io.StringIO.__init__(self)
        self._calls = calls

    def write(self, text):
        if text.strip():
            self._calls.append("stderr")
        return io.StringIO.write(self, text)


class _FullDiskStderr(io.StringIO):
    """A .craft/server.log on a filesystem with no room left.

    Not a hypothetical: the stolen-lock notice is written at exactly the
    moment a session is in trouble, and ENOSPC is one of the ways a project
    directory gets into that state in the first place.
    """

    def write(self, text):
        raise OSError(errno.ENOSPC, "No space left on device")


class _WatchdogSession:
    """A session that answers the one question the watchdog asks it."""

    def __init__(self, ours=True, error=None):
        self.lock_path = "/nowhere/.craft/session.lock"
        self.ours = ours  # public: a test flips it to end a running watchdog
        self._error = error

    def verify_lock_still_ours(self):
        if self._error is not None:
            raise self._error
        return self.ours


class _WatchdogServer:
    """Enough of a server for the watchdog, remembering what it was told.

    The real one cannot be used here: shutdown() on a server that never
    entered serve_forever waits for an event nothing will set, and these
    cases are all about what happens on the way to that call rather than
    inside it.
    """

    def __init__(self, calls=None, idle_seconds=0.0, idle_timeout_s=3600.0,
                 error=None):
        self.calls = [] if calls is None else calls
        self.stopped = threading.Event()
        self.idle_timeout_s = idle_timeout_s
        self._idle_seconds = idle_seconds
        self._error = error

    def close_writes(self):
        self.calls.append("close_writes")

    def shutdown(self):
        self.calls.append("shutdown")
        self.stopped.set()

    def idle_seconds(self):
        if self._error is not None:
            raise self._error
        return self._idle_seconds


class WatchdogTest(unittest.TestCase):
    """The watchdog thread is the only thing that can end a session nobody
    signals, so an exception in it does not fail a request -- it removes the
    one party able to notice that another session has taken the project.

    Three properties, and each has a case of its own because each was got
    wrong once. The notice is written before the shutdown, or it is lost --
    shutdown() frees the main thread to exit the process out from under this
    daemon thread. The write cannot prevent the shutdown it announces, which
    is what the finally is for. And the loop body fails closed, so anything
    that raises ends the session rather than only this thread.
    """

    def run_watchdog(self, server, session, stderr=None):
        """Run the real watchdog against fakes until it ends the session."""
        with contextlib.redirect_stderr(stderr or io.StringIO()):
            thread = threading.Thread(
                target=craftui._watchdog, args=(server, session), daemon=True)
            thread.start()
            self.assertTrue(
                server.stopped.wait(PATIENCE_S),
                "the watchdog never ended the session: {}".format(server.calls))
            thread.join(PATIENCE_S)
        self.assertFalse(thread.is_alive(), "the watchdog thread outlived the session")

    def test_a_stolen_lock_ends_the_session(self):
        server = _WatchdogServer()
        noise = io.StringIO()
        self.run_watchdog(server, _WatchdogSession(ours=False), stderr=noise)
        self.assertEqual(server.calls, ["close_writes", "shutdown"])
        self.assertIn("session.lock", noise.getvalue())
        self.assertIn("another session", noise.getvalue())

    def test_a_stolen_lock_ends_the_session_when_the_notice_cannot_be_written(self):
        """The full filesystem is the case the whole check exists for, and it
        was the one case that defeated it: the notice is written first, ENOSPC
        raised there, and the shutdown it was announcing never happened. The
        thread died with it, so nothing was left that could end the session,
        and the server held a project another session already owned for the
        rest of the four-hour idle default."""
        server = _WatchdogServer()
        self.run_watchdog(
            server, _WatchdogSession(ours=False), stderr=_FullDiskStderr())
        self.assertEqual(server.calls, ["close_writes", "shutdown"])

    def test_the_stolen_lock_notice_is_written_before_the_shutdown_it_announces(self):
        """Not tidiness -- the notice is lost otherwise.

        shutdown() releases the main thread, which runs the exit path, and
        this is a daemon thread with no promise of another instruction after
        that. Announcing afterwards was measured on a loaded machine at 12
        losses in 20 runs: the server exited cleanly and .craft/server.log
        said only that, with nothing in it to say the project had been taken.
        On an idle machine it passed every time, which is why the loss is
        asserted as an order rather than waited for.
        """
        server = _WatchdogServer()
        noise = _NotingStderr(server.calls)
        self.run_watchdog(server, _WatchdogSession(ours=False), stderr=noise)
        self.assertEqual(server.calls, ["stderr", "close_writes", "shutdown"])

    def test_a_watchdog_that_cannot_check_the_lock_ends_the_session(self):
        """An unreadable .craft/, an fstat that failed, a bug added later:
        the watchdog cannot tell those from a stolen lock, and a watchdog
        that cannot decide must fail closed rather than stop watching."""
        server = _WatchdogServer()
        session = _WatchdogSession(error=OSError(errno.EIO, "I/O error"))
        noise = io.StringIO()
        self.run_watchdog(server, session, stderr=noise)
        self.assertEqual(server.calls, ["close_writes", "shutdown"])
        self.assertIn("watchdog stopped", noise.getvalue())

    def test_a_watchdog_that_cannot_check_the_clock_ends_the_session(self):
        """The second arm of the loop, reached only once the lock check has
        passed -- so this also proves the fake session's true branch."""
        server = _WatchdogServer(error=RuntimeError("no clock"))
        noise = io.StringIO()
        self.run_watchdog(server, _WatchdogSession(ours=True), stderr=noise)
        self.assertEqual(server.calls, ["close_writes", "shutdown"])
        self.assertIn("no clock", noise.getvalue())

    def test_an_idle_session_is_ended_and_a_busy_one_is_not(self):
        """The fakes are only worth what they exercise: without this, every
        case above could pass against a watchdog whose ordinary arms were
        broken."""
        idle = _WatchdogServer(idle_seconds=99.0, idle_timeout_s=1.0)
        self.run_watchdog(idle, _WatchdogSession(ours=True))
        self.assertEqual(idle.calls, ["close_writes", "shutdown"])

        busy = _WatchdogServer(idle_seconds=0.0, idle_timeout_s=3600.0)
        session = _WatchdogSession(ours=True)
        with contextlib.redirect_stderr(io.StringIO()):
            thread = threading.Thread(
                target=craftui._watchdog, args=(busy, session), daemon=True)
            thread.start()
            # A negative, so it is worth a fixed wait: several watchdog
            # ticks, in which a watchdog that always shut down would have.
            self.assertFalse(busy.stopped.wait(craftui.WATCHDOG_INTERVAL_S * 4))
            self.assertEqual(busy.calls, [])
            # Not left running. A daemon thread that never ends outlives this
            # test and ticks through everybody else's.
            session.ours = False
            self.assertTrue(busy.stopped.wait(PATIENCE_S))
            thread.join(PATIENCE_S)
        self.assertFalse(thread.is_alive())


class _Recorder:
    """A server and a session that only remember what order they were used in."""

    writes_in_flight = 0

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def record(*_args, **_kw):
            self.calls.append(name)
            return True

        return record


class ArgumentTest(unittest.TestCase):
    """The two typed flags, at the function rather than through argv.

    One of these cases cannot travel through argv at all: under LC_ALL=C the
    filesystem encoding is ASCII and a non-ASCII argument cannot be spawned,
    which is how this test came to be here rather than in ServeTest.
    """

    def refused(self, parse, value):
        with self.assertRaises(craftui.argparse.ArgumentTypeError) as caught:
            parse(value)
        return str(caught.exception)

    def test_a_port_written_in_non_ascii_digits_is_refused(self):
        """int() reads "\u0663" as 3 and str.isdigit() calls it a digit, which
        is the trap session.py's _ROUND_TEXT is written around. One number,
        one spelling."""
        self.assertEqual(int("\u0663"), 3)  # the premise
        self.assertIn("65535", self.refused(craftui._port_number, "\u0663"))

    def test_the_ports_that_are_ports(self):
        for value, expected in (("0", 0), ("1", 1), ("8080", 8080), ("65535", 65535)):
            with self.subTest(value=value):
                self.assertEqual(craftui._port_number(value), expected)

    def test_the_idle_timeouts_that_are_durations(self):
        for value, expected in (("0.02", 0.02), ("240", 240.0), ("1e3", 1000.0)):
            with self.subTest(value=value):
                self.assertEqual(craftui._idle_minutes(value), expected)

    def test_the_idle_timeouts_that_are_not(self):
        for value in ("0", "-1", "nan", "inf", "-inf", "banana", ""):
            with self.subTest(value=value):
                self.refused(craftui._idle_minutes, value)


class ShutdownOrderTest(unittest.TestCase):
    """The order is the fix. Every step of it is load-bearing and none of it
    is visible from outside the process, so it is asserted directly."""

    def test_the_lock_goes_last_and_the_gate_shuts_first(self):
        recorder = _Recorder()
        with contextlib.redirect_stderr(io.StringIO()):
            craftui.shutdown_and_release(recorder, recorder, 1.0)
        self.assertEqual(
            recorder.calls,
            ["close_writes", "shutdown", "server_close", "drain_writes", "release_lock"],
        )

    def test_the_notice_that_the_session_ended_is_written_before_the_lock_goes(self):
        """In the child, stderr IS .craft/server.log, so this line is a write
        into the project and the rule it has to obey is the same one the
        drain exists for: nothing of ours may land after we have let go. It
        sat in _run_server's finally, after the release, on every clean exit.
        """
        recorder = _Recorder()
        with contextlib.redirect_stderr(_NotingStderr(recorder.calls)) as noise:
            craftui.shutdown_and_release(recorder, recorder, 1.0)
        self.assertEqual(
            recorder.calls,
            ["close_writes", "shutdown", "server_close", "drain_writes",
             "stderr", "release_lock"],
        )
        self.assertIn("session ended cleanly", noise.getvalue())

    def test_the_drain_bound_fits_inside_what_stop_will_wait(self):
        """Task 9's `stop` sends SIGTERM and waits STOP_SIGTERM_WAIT_S before
        it reports. A drain that ran to its full bound plus the release after
        it has to finish comfortably inside that, or `stop` reports a lie.

        The two constants are compared to each other and not to the number
        either happens to hold today. Written as `<= 8`, this passed happily
        while Task 9 shortened its wait to five -- so the coupling it was
        written to protect could break with the test still green.
        """
        self.assertGreater(craftui.WRITE_DRAIN_TIMEOUT_S, 0)
        self.assertGreater(craftui.STOP_SIGTERM_WAIT_S, 0)
        self.assertLessEqual(
            craftui.WRITE_DRAIN_TIMEOUT_S + HEADROOM_AFTER_THE_DRAIN_S,
            craftui.STOP_SIGTERM_WAIT_S,
            "the drain plus the release after it no longer fits inside what "
            "stop waits, so stop will report a death that has not happened",
        )


class VersionFloorTest(unittest.TestCase):
    """tests/test_python_floor.py enforces the floor for SYNTAX only -- it
    cannot see a stdlib API added after 3.9. This is the runtime half: on an
    interpreter that is too old, one sentence naming both versions, not a
    SyntaxError or an AttributeError out of somewhere deep."""

    def fake_version(self, version):
        """A real interpreter that reports an old version_info at startup.

        sitecustomize is imported by site before the main script runs, and
        sys.version_info is an ordinary attribute of an ordinary module, so
        this exercises the guard as it is actually reached rather than
        calling the function it delegates to.
        """
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, True))
        Path(directory, "sitecustomize.py").write_text(
            "import sys\nsys.version_info = {!r}\n".format(version), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = directory + os.pathsep + env.get("PYTHONPATH", "")
        return env

    def test_an_old_interpreter_is_refused_with_one_clear_sentence(self):
        env = self.fake_version((3, 8, 10, "final", 0))
        # A temporary directory and not ".", which is the source tree this
        # suite is run from. This case is safe only for as long as the guard
        # above works; the day it regresses, `--project-dir .` starts a real
        # detached server holding a kernel lock on the repository's own
        # .craft/ and leaks it for the four-hour idle default -- so the test
        # for the guard would take the repository down with it.
        with tempfile.TemporaryDirectory() as project:
            result = run("serve", "--project-dir", project, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("3.9", result.stderr)
        self.assertIn("3.8.10", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(
            len([line for line in result.stderr.splitlines() if line.strip()]), 1,
            result.stderr)

    def test_the_floor_itself_is_allowed_through(self):
        env = self.fake_version((3, 9, 0, "final", 0))
        result = run("--help", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("needs Python", result.stderr)

    def test_the_message_names_both_versions(self):
        message = craftui.python_version_error((3, 7, 17))
        self.assertIsNotNone(message)
        self.assertIn("3.9", message)
        self.assertIn("3.7.17", message)

    def test_every_version_at_or_above_the_floor_passes(self):
        for version in ((3, 9), (3, 9, 0), (3, 9, 21), (3, 11, 2), (4, 0, 0)):
            with self.subTest(version=version):
                self.assertIsNone(craftui.python_version_error(version))

    def test_every_version_below_the_floor_fails(self):
        for version in ((2, 7, 18), (3, 0), (3, 8), (3, 8, 20), (3, 8, 99)):
            with self.subTest(version=version):
                self.assertIsNotNone(craftui.python_version_error(version))

    def test_the_guard_runs_before_the_modules_it_protects_are_imported(self):
        """A guard underneath the imports is not a guard: `from server import`
        is exactly where a post-3.9 stdlib API would raise first."""
        module = ast.parse(Path(CRAFTUI).read_text(encoding="utf-8"))
        guard = None
        first_local_import = None
        for index, node in enumerate(module.body):
            for child in ast.walk(node):
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Name)
                        and child.func.id == "python_version_error"
                        and guard is None):
                    guard = index
            if (isinstance(node, ast.ImportFrom)
                    and node.module in ("server", "session")
                    and first_local_import is None):
                first_local_import = index
        self.assertIsNotNone(guard, "nothing at module level calls the version guard")
        self.assertIsNotNone(first_local_import, "craftui imports neither server nor session")
        self.assertLess(guard, first_local_import)


# --------------------------------------------------------------------- wait

# Captured before any test patches it, so a test that wants the real liveness
# question back can have it.
REAL_SERVER_ALIVE = craftui.server_alive


def snapshot(root):
    """Every path under root and what is in it. `wait` must not change this."""
    seen = {}
    for path in sorted(Path(root).rglob("*")):
        key = str(path.relative_to(root))
        try:
            seen[key] = path.read_bytes() if path.is_file() else "<dir>"
        except OSError as exc:
            seen[key] = "<unreadable {}>".format(exc.errno)
    return seen


class WaitTest(CommandTestCase):
    """`wait` through argv, which is the only way the craft skill calls it.

    Almost nothing here starts a real server, deliberately. `wait` never
    speaks to the server: it reads .craft/server-info and asks whether that
    pid is alive, so a server-info naming any process that is up is a live
    server as far as `wait` can tell, and this test process is one. What is
    asserted here is what a shell sees -- the exit code, and one line on
    stdout -- plus one end-to-end run against a real server, because the file
    `wait` watches is written by a real POST and nothing else in this file
    would notice if that contract changed. The properties of the polling loop
    itself are in CmdWaitTest, where a poll costs nothing.
    """

    def wait(self, *extra):
        return run("wait", "--project-dir", self.root, "--round", "1", *extra)

    def answers(self, number=1, finished=False):
        path = self.session.answers_path(number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"round": number, "finished": finished, "answers": {}}),
            encoding="utf-8",
        )
        return path

    def pretend_server(self, pid=None):
        """A server-info naming a live process. `wait` asks nothing else."""
        pid = os.getpid() if pid is None else pid
        write_json_atomic(
            self.info_path,
            {"type": "server-started", "port": 1, "pid": pid, "key": "k",
             "url": "http://127.0.0.1:1/?key=k"},
        )

    def test_no_server_exits_3(self):
        result = self.wait("--timeout", "5")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "NOSERVER\n")

    def test_answers_already_present_return_submitted(self):
        self.pretend_server()
        path = self.answers(1, finished=False)
        result = self.wait("--timeout", "10")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout, "SUBMITTED round=1 answers={}\n".format(path))

    def test_finished_answers_return_finished(self):
        self.pretend_server()
        path = self.answers(1, finished=True)
        result = self.wait("--timeout", "10")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout, "FINISHED round=1 answers={}\n".format(path))

    def test_a_real_submit_through_a_real_server_is_what_wait_reports(self):
        """The whole seam, once, with nothing faked: a browser POSTs, the
        server writes the file, `wait` finds it and says where it is."""
        self.serve()
        info = self.info()
        request = urllib.request.Request(
            "http://127.0.0.1:{}/api/submit?key={}".format(info["port"], info["key"]),
            data=json.dumps(
                {"round": 1, "answers": {"Q-1": {"text": "yes"}}, "finished": False}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertIs(json.loads(response.read())["ok"], True)
        result = self.wait("--timeout", "20")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = self.session.answers_path(1)
        self.assertEqual(
            result.stdout, "SUBMITTED round=1 answers={}\n".format(path))
        self.assertEqual(
            read_json(path)["answers"], {"Q-1": {"text": "yes"}},
            "wait named a file that is not the one the browser sent")

    def test_a_mistyped_flag_is_not_a_timeout(self):
        """The defect this task exists to close. argparse exits 2 and this
        CLI documents 2 as TIMEOUT, which the skill answers by arming another
        wait -- so one wrong flag name would loop for ever on a command that
        never ran, waiting on a user who was never asked anything."""
        result = run(
            "wait", "--project-dir", self.root, "--round", "1", "--timout", "5")
        self.assertEqual(result.returncode, craftui.USAGE_EXIT, result.stderr)
        self.assertEqual(result.stdout, "", "a usage error printed an outcome")
        self.assertIn("--timout", result.stderr)


class CmdWaitTest(unittest.TestCase):
    """The polling loop, in this process, with the poll interval collapsed.

    Through argv every one of these would cost a spawn and real seconds --
    DEAD_SERVER_STRIKES alone is two of them -- and none of what is asserted
    here is a property of the process boundary. The three things that are
    really do run as processes, in WaitTest.

    server_alive is stubbed rather than driven by real pids: it is total and
    HelperTest covers every way it can be handed rubbish. What these tests
    are about is what the loop does with the answers it gives.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.session = Session(self.root)
        self.answers_path = self.session.answers_path(1)
        self.alive_calls = 0
        self.elapsed = None
        self.patch("POLL_S", 0.001)
        self.alive(True)

    def patch(self, name, value):
        previous = getattr(craftui, name)
        self.addCleanup(setattr, craftui, name, previous)
        setattr(craftui, name, value)

    def alive(self, answer):
        """Stub server_alive. `answer` is a bool or an f(call number) -> bool."""
        def stub(_session):
            self.alive_calls += 1
            return answer(self.alive_calls) if callable(answer) else answer

        self.patch("server_alive", stub)

    def real_alive(self):
        """Put the real liveness question back for one test."""
        self.patch("server_alive", REAL_SERVER_ALIVE)

    def write(self, text, path=None):
        path = self.answers_path if path is None else path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def payload(self, **extra):
        body = {"round": 1, "answers": {}}
        body.update(extra)
        return json.dumps(body)

    def wait(self, timeout=5.0, number=1):
        args = craftui.build_parser().parse_args(
            ["wait", "--project-dir", self.root,
             "--round", str(number), "--timeout", repr(timeout)])
        out, err = io.StringIO(), io.StringIO()
        started = time.monotonic()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = craftui.cmd_wait(args)
        self.elapsed = time.monotonic() - started
        self.assertEqual(
            out.getvalue().count("\n"), 1,
            "wait must print exactly one line, and printed {!r}".format(
                out.getvalue()))
        return code, out.getvalue().strip(), err.getvalue()

    # -- what it says -----------------------------------------------------

    def test_submitted_names_the_round_and_the_file(self):
        self.write(self.payload(finished=False))
        code, line, _ = self.wait()
        self.assertEqual(code, 0)
        self.assertEqual(
            line, "SUBMITTED round=1 answers={}".format(self.answers_path))

    def test_finished_names_the_round_and_the_file(self):
        self.write(self.payload(finished=True))
        code, line, _ = self.wait()
        self.assertEqual(code, 0)
        self.assertEqual(
            line, "FINISHED round=1 answers={}".format(self.answers_path))

    def test_only_a_real_true_finishes_the_session(self):
        """bool("false") is True, which is why the server refuses a finished
        that is not a boolean. Anything that reaches here as something else
        is a hand-edited file, and the two mistakes are not the same size:
        FINISHED ends the conversation, SUBMITTED costs one more round."""
        for value in ('"false"', '"no"', '"true"', "1", "[]", "{}", '"yes"'):
            with self.subTest(finished=value):
                self.write(
                    '{{"round": 1, "finished": {}, "answers": {{}}}}'.format(value))
                code, line, _ = self.wait()
                self.assertEqual(code, 0)
                self.assertTrue(line.startswith("SUBMITTED"), line)

    def test_a_missing_finished_key_is_not_finished(self):
        self.write('{"round": 1, "answers": {}}')
        self.assertTrue(self.wait()[1].startswith("SUBMITTED"))

    def test_the_round_it_was_asked_about_is_the_round_it_watches(self):
        self.write(self.payload(finished=False), self.session.answers_path(2))
        code, line, _ = self.wait(timeout=0.05, number=1)
        self.assertEqual(code, 2, line)

    # -- when nothing arrives ---------------------------------------------

    def test_nothing_arriving_times_out_with_exit_2(self):
        code, line, err = self.wait(timeout=0.2)
        self.assertEqual(code, 2)
        self.assertEqual(line, "TIMEOUT round=1")
        self.assertGreaterEqual(self.elapsed, 0.2, "the timeout was not waited out")
        self.assertIn("heartbeat", err.lower())

    def test_the_timeout_says_out_loud_that_it_is_not_a_failure(self):
        """Whoever reads this sees a bare TIMEOUT in a transcript otherwise
        full of failures. The agent arms another one and the user goes on
        typing; the line has to say so, and not on stdout, which is one line
        and is read by a shell."""
        err = self.wait(timeout=0.05)[2].lower()
        self.assertIn("not a failure", err)
        self.assertIn("again", err)
        self.assertNotIn("error", err)

    def test_answers_arriving_mid_wait_are_picked_up(self):
        timer = threading.Timer(0.05, self.write, args=(self.payload(),))
        timer.start()
        self.addCleanup(timer.cancel)
        code, line, _ = self.wait(timeout=10)
        self.assertEqual(code, 0)
        self.assertTrue(line.startswith("SUBMITTED round=1"), line)
        self.assertLess(self.elapsed, 5, "it waited out the timeout instead")

    # -- when the server goes ----------------------------------------------

    def test_a_dead_server_mid_wait_exits_3(self):
        self.alive(lambda call: call < 3)
        code, line, _ = self.wait(timeout=30)
        self.assertEqual(code, 3)
        self.assertEqual(line, "NOSERVER")

    def test_noserver_needs_a_full_run_of_misses(self):
        """Exactly the run, and not one miss fewer: the count is the whole of
        what keeps a restart from reading as a death."""
        self.alive(False)
        code, _, _ = self.wait(timeout=30)
        self.assertEqual(code, 3)
        self.assertEqual(self.alive_calls, craftui.DEAD_SERVER_STRIKES)

    def test_a_gap_shorter_than_the_run_does_not_end_the_wait(self):
        """A `serve` restart leaves server-info naming a dead pid for as long
        as the restart takes. One miss short of the run, over and over, must
        never be reported as a death."""
        self.alive(lambda call: call % craftui.DEAD_SERVER_STRIKES == 0)
        code, line, _ = self.wait(timeout=0.2)
        self.assertEqual(code, 2, line)
        self.assertGreater(
            self.alive_calls, craftui.DEAD_SERVER_STRIKES * 2,
            "the loop did not run long enough for this to have proved anything")

    def test_answers_are_read_before_the_server_is_doubted(self):
        """A server that exits the moment the user presses Send has still
        delivered the round. Asking the liveness question first would throw
        away answers that are already on disk."""
        self.write(self.payload())
        self.alive(False)
        code, line, _ = self.wait(timeout=30)
        self.assertEqual(code, 0, line)
        self.assertTrue(line.startswith("SUBMITTED"), line)
        self.assertEqual(self.alive_calls, 0, "it doubted the server first")

    # -- when the file is there and cannot be read -------------------------

    def test_a_torn_read_is_retried_not_reported(self):
        """The file is written by another process, so a read can land in the
        middle of one. That is a moment, not a malformed round.

        Counted rather than timed: the torn reads are made to happen, one
        fewer than the bound, so this asserts the retry right up to the edge
        of it instead of racing a timer against a collapsed poll interval.
        """
        self.write(self.payload())
        real, torn = craftui.read_json, []

        def tearing(path):
            if len(torn) < craftui.UNREADABLE_STRIKES - 1:
                torn.append(path)
                raise ValueError("Expecting value: line 1 column 1 (char 0)")
            return real(path)

        self.patch("read_json", tearing)
        code, line, _ = self.wait(timeout=30)
        self.assertEqual(len(torn), craftui.UNREADABLE_STRIKES - 1)
        self.assertEqual(code, 0, line)
        self.assertTrue(line.startswith("SUBMITTED"), line)

    def test_the_run_of_unreadable_looks_has_to_be_consecutive(self):
        """Counted cumulatively rather than in a run, a file that goes
        unreadable, away, and unreadable again -- which is what deleting a
        bad file and letting the server write it afresh looks like -- would
        be reported as broken on the strength of two separate blips.

        Written as a script of reads rather than as files on disk, because
        what is being asserted is the counter and not the filesystem.
        """
        self.write(self.payload())
        real, script = craftui.read_json, (
            [ValueError] * (craftui.UNREADABLE_STRIKES - 1)
            + [FileNotFoundError]
            + [ValueError] * (craftui.UNREADABLE_STRIKES - 1)
        )
        self.assertGreater(len(script), craftui.UNREADABLE_STRIKES,
                           "the script is too short to have proved anything")
        reads = []

        def scripted(path):
            reads.append(path)
            if len(reads) <= len(script):
                raise script[len(reads) - 1]("scripted")
            return real(path)

        self.patch("read_json", scripted)
        code, line, _ = self.wait(timeout=30)
        self.assertEqual(len(reads), len(script) + 1)
        self.assertEqual(code, 0, line)
        self.assertTrue(line.startswith("SUBMITTED"), line)

    def test_a_file_that_never_becomes_readable_is_reported_not_waited_out(self):
        """Reporting this as TIMEOUT would be a lie the skill acts on: it
        arms another wait, which can only fail the same way, for ever."""
        for text in ('{"round": 1, "finish', "[]", '"nonsense"', "null", ""):
            with self.subTest(text=text):
                self.write(text)
                code, line, _ = self.wait(timeout=30)
                self.assertEqual(code, 1, line)
                self.assertIn(str(self.answers_path), line)

    def test_a_directory_where_the_answers_go_is_reported(self):
        self.answers_path.parent.mkdir(parents=True, exist_ok=True)
        self.answers_path.mkdir()
        code, line, _ = self.wait(timeout=30)
        self.assertEqual(code, 1, line)
        self.assertIn(str(self.answers_path), line)

    def test_the_timeout_is_honoured_while_the_file_is_unreadable(self):
        """The deadline is checked on every path through the loop. A retry
        that skips it is a --timeout that does not exist, and an agent that
        never gets its turn back."""
        self.patch("UNREADABLE_STRIKES", 10 ** 9)
        self.write("{ not json")
        code, line, _ = self.wait(timeout=0.2)
        self.assertEqual(code, 2, line)
        self.assertLess(self.elapsed, 10, "the wait ignored its own deadline")

    # -- what it must not do -----------------------------------------------

    def test_a_server_info_left_behind_by_a_dead_session_is_not_a_server(self):
        """server-info survives a clean exit so that the next `serve` can
        reuse the port. Presence says a server was started here; it does not
        say one is running. Read as liveness, it would hand the agent a wait
        that cannot end, on a session that finished hours ago.

        The real server_alive, and a pid that really has gone."""
        self.real_alive()
        dead = subprocess.Popen([sys.executable, "-c", ""])
        dead.wait()
        write_json_atomic(
            Path(self.root) / ".craft" / "server-info",
            {"type": "server-started", "port": 1, "pid": dead.pid, "key": "k"},
        )
        code, line, _ = self.wait(timeout=30)
        self.assertEqual(code, 3, line)
        self.assertEqual(line, "NOSERVER")

    def test_wait_writes_nothing_into_the_project(self):
        """It is a reader. Creating .craft, or touching a lock, would make a
        wait against a project no server ever ran in leave a trace of one."""
        self.real_alive()
        self.assertEqual(snapshot(self.root), {}, "the fixture was not empty")
        code, _, _ = self.wait(timeout=30)
        self.assertEqual(code, 3, "the real liveness question was not asked")
        self.assertEqual(snapshot(self.root), {})

    def test_wait_changes_nothing_it_reads(self):
        self.write(self.payload())
        write_json_atomic(
            Path(self.root) / ".craft" / "server-info",
            {"type": "server-started", "port": 1, "pid": os.getpid(), "key": "k"},
        )
        before = snapshot(self.root)
        self.wait()
        self.assertEqual(snapshot(self.root), before)


class ReadAnswersTest(unittest.TestCase):
    """read_answers is total: three states and no exception, whatever is on
    disk. cmd_wait branches on it rather than guarding it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "round-001.answers.json"

    def written(self, text):
        self.path.write_text(text, encoding="utf-8")
        return craftui.read_answers(self.path)

    def test_a_file_that_is_not_there_is_absent(self):
        self.assertEqual(craftui.read_answers(self.path), (craftui.ABSENT, None))

    def test_a_round_of_answers_is_ready(self):
        state, payload = self.written('{"round": 1, "answers": {}}')
        self.assertEqual(state, craftui.READY)
        self.assertEqual(payload, {"round": 1, "answers": {}})

    def test_everything_json_can_be_that_is_not_an_object_is_unreadable(self):
        """null, [] and "nonsense" all parse. .get on any of them is an
        AttributeError out of a command whose whole job is to return a code."""
        for text in ("null", "[]", '"nonsense"', "3", "true"):
            with self.subTest(text=text):
                self.assertEqual(self.written(text), (craftui.UNREADABLE, None))

    def test_a_half_written_file_is_unreadable(self):
        for text in ("", "{", '{"round": 1, "finish', "not json at all"):
            with self.subTest(text=text):
                self.assertEqual(self.written(text), (craftui.UNREADABLE, None))

    def test_a_directory_is_unreadable_and_not_an_exception(self):
        self.path.mkdir()
        self.assertEqual(craftui.read_answers(self.path), (craftui.UNREADABLE, None))

    def test_a_missing_parent_is_absent_not_unreadable(self):
        """A project with no .craft at all is a round that has not arrived,
        which is exactly what a wait armed before the first submit sees."""
        deep = Path(self._tmp.name) / "nope" / "round-001.answers.json"
        self.assertEqual(craftui.read_answers(deep), (craftui.ABSENT, None))


class PollIntervalTest(unittest.TestCase):
    """The two numbers the loop is made of, asserted as the properties they
    exist for rather than as the literals they happen to be. Nothing here
    patches either of them."""

    def test_the_dead_server_window_outlasts_a_serve_restart(self):
        """A `serve` spawn is a few hundred milliseconds, and for all of it
        server-info still names the pid that has gone. The window has to be
        the margin over that, or a restart reads as a death and a wait the
        user is still typing into is abandoned."""
        self.assertGreaterEqual(
            craftui.DEAD_SERVER_STRIKES * craftui.POLL_S, 1.5)

    def test_a_poll_a_person_could_notice_is_no_poll(self):
        """It runs for hours, so it has to be cheap; it ends a person's
        silence, so it has to be quick. A look is four syscalls."""
        self.assertLessEqual(craftui.POLL_S, 0.5)
        self.assertGreaterEqual(craftui.POLL_S, 0.05)

    def test_the_unreadable_window_is_orders_of_magnitude_past_a_rename(self):
        """What it retries is a read landing inside another process's write,
        which is one os.replace wide."""
        self.assertGreaterEqual(
            craftui.UNREADABLE_STRIKES * craftui.POLL_S, 1.0)


class UsageExitTest(unittest.TestCase):
    """"You called me wrong" must not be spelled like an outcome.

    argparse exits 2 for a usage error and this CLI documents 2 as TIMEOUT.
    Every case here goes through argparse's own error path, and the
    subcommand cases go through a subparser, which inherits the override only
    because add_subparsers defaults parser_class to type(self).
    """

    def refused(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                craftui.build_parser().parse_args(argv)
        return caught.exception.code, err.getvalue()

    def test_the_usage_code_is_outside_every_outcome_this_cli_documents(self):
        """0 ok, 1 failed, 2 TIMEOUT, 3 NOSERVER, 4 LOCKED. A usage error is
        none of them, and the one it must not be is 2."""
        self.assertNotIn(craftui.USAGE_EXIT, (0, 1, 2, 3, 4))

    def test_every_way_of_calling_it_wrong_exits_the_same(self):
        for argv in (
            [],
            ["nosuchcommand"],
            ["wait"],
            ["wait", "--round"],
            ["wait", "--round", "1", "--timout", "5"],
            ["wait", "--round", "1", "extra"],
            ["serve", "--port", "banana"],
            ["serve", "--idle-timeout-minutes", "0"],
            ["serve", "--nonsense"],
        ):
            with self.subTest(argv=argv):
                code, err = self.refused(argv)
                self.assertEqual(code, craftui.USAGE_EXIT, err)

    def test_a_round_that_cannot_name_a_file_is_refused_at_the_flag(self):
        """One round, one spelling -- the rule the server parses a round by,
        reused rather than restated. Waited out instead of refused, each of
        these is a full timeout spent on a file that can never appear."""
        for value in ("0", "-1", "1.0", "1e3", "01", "1000", "", " 1", "banana",
                      "\u0663", "+1", "0x1"):
            with self.subTest(round=value):
                argv = ["wait", "--round", value]
                code, err = self.refused(argv)
                self.assertEqual(code, craftui.USAGE_EXIT, err)

    def test_a_timeout_that_is_not_a_duration_is_refused_at_the_flag(self):
        """nan is the one that matters: it compares false against everything,
        so a deadline built from it is never reached and the wait never ends,
        which is the one failure a heartbeat cannot recover from."""
        for value in ("nan", "inf", "-inf", "0", "-1", "banana", ""):
            with self.subTest(timeout=value):
                argv = ["wait", "--round", "1", "--timeout", value]
                code, err = self.refused(argv)
                self.assertEqual(code, craftui.USAGE_EXIT, err)

    def test_the_rounds_and_timeouts_that_are_accepted(self):
        """The other half: a gate that refuses everything is not a gate."""
        args = craftui.build_parser().parse_args(
            ["wait", "--round", "999", "--timeout", "1e3"])
        self.assertEqual((args.round, args.timeout), (999, 1000.0))
        for value in ("1", "7", "42", "999"):
            with self.subTest(round=value):
                self.assertEqual(
                    craftui.build_parser().parse_args(
                        ["wait", "--round", value]).round, int(value))

    def test_the_subparsers_inherit_it_rather_than_being_given_it(self):
        """add_subparsers defaults parser_class to type(self). If that ever
        stops being true, every flag on every subcommand goes back to exiting
        2, which is TIMEOUT."""
        parser = craftui.build_parser()
        subs = [action for action in parser._actions
                if isinstance(action, craftui.argparse._SubParsersAction)]
        self.assertEqual(len(subs), 1)
        self.assertTrue(subs[0].choices)
        for name, sub in subs[0].choices.items():
            with self.subTest(command=name):
                self.assertIsInstance(sub, craftui.CraftParser)

    def test_help_still_exits_zero(self):
        """Asking how to call it is not calling it wrong."""
        for argv in (["--help"], ["wait", "--help"], ["serve", "--help"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.refused(argv)[0], 0)


if __name__ == "__main__":
    unittest.main()
