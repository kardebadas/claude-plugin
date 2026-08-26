#!/usr/bin/env python3
"""craft UI command line.

`serve` starts the local server as a detached background process, hands it
the project lock for its whole life, and writes .craft/server-info so that
the commands after it can find the thing it started.

Exit codes: 0 ok, 2 TIMEOUT, 3 NOSERVER, 4 LOCKED. 1 is everything else that
stopped a command from doing its job, and 64 is "you called me wrong" -- see
CraftParser for why that one may not be 2, which is what argparse would
otherwise use for it.

Two properties are worth stating outside a function, because both were bugs
before they were properties:

* The lock belongs to the CHILD, for the child's whole life. The parent takes
  nothing, so there is no window in which the lock changes hands and no way
  for the parent's exit to release it.
* A refused `serve` destroys nothing. It does not delete server-info, and it
  does not delete the lock file -- the two things a running session's other
  commands read. A second `serve` on a busy project used to unlink the first
  one's server-info on its way to being refused, which left `wait`, `status`
  and `stop` unable to find a server that was serving perfectly well.
"""
# Deliberate: kept so any annotation added later may use `int | None` syntax
# while this project's floor is Python 3.9. Do not delete.
from __future__ import annotations

import sys

# The floor this project is written to. tests/test_python_floor.py enforces
# it with ast.parse(feature_version=(3, 9)), which sees SYNTAX and nothing
# else: a call to a stdlib API added after 3.9 parses happily and then fails
# at import time, deep inside a file the user did not write, as an
# AttributeError or a ModuleNotFoundError that names neither version. This is
# the runtime half of the same gate, and it has to run before the imports it
# protects -- `from server import ...` is precisely where such a failure
# would land first.
REQUIRED_PYTHON = (3, 9)


def python_version_error(actual=None):
    """One sentence for an interpreter that is too old, or None.

    Both versions are named, and so is the interpreter that was used, since
    "run it with a newer python3" is only actionable if you can tell which
    one you just ran.
    """
    if actual is None:
        actual = sys.version_info
    actual = tuple(actual)[:3]
    if actual >= REQUIRED_PYTHON:
        return None
    return (
        "craftui needs Python {} or newer, but {} is Python {} -- run it with "
        "a newer interpreter.".format(
            ".".join(str(part) for part in REQUIRED_PYTHON),
            sys.executable or "this interpreter",
            ".".join(str(part) for part in actual),
        )
    )


_VERSION_ERROR = python_version_error()
if _VERSION_ERROR is not None:
    sys.stderr.write(_VERSION_ERROR + "\n")
    raise SystemExit(1)

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import webbrowser  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import (  # noqa: E402
    MAX_ROUND,
    MIN_ROUND,
    CraftServer,
    make_key,
    parse_round,
)
from session import (  # noqa: E402
    LockHeld,
    LockUnavailable,
    Session,
    read_json,
    write_json_atomic,
)

# How long the parent waits for the child to say what happened. Everything
# the child does before it answers is local: take a lock, bind a loopback
# socket, write one small file. Fifteen seconds is not a budget any of that
# has ever needed; it is the bound on a parent that would otherwise wait for
# a child that will never speak.
SERVE_START_TIMEOUT_S = 15

# How often the parent looks. Small enough that `serve` feels immediate,
# large enough that the wait is not a spin.
SERVE_POLL_S = 0.02

# How often the server checks that it still holds the project and that it is
# not idle. Four times a second: two fstats and a subtraction, and it is also
# the worst-case delay between another session stealing the lock file and
# this one noticing.
WATCHDOG_INTERVAL_S = 0.25

# How long the shutdown waits for writes that were already in flight.
#
# It is a bound on a wedged write, not a budget for an honest one: a write
# here is one json.dump of at most a few megabytes, one fsync and one rename,
# which is milliseconds on any working filesystem. Five seconds is three
# orders of magnitude of headroom.
#
# Five and not more because of what is downstream: STOP_SIGTERM_WAIT_S. A
# drain that ran to its full bound plus the release after it has to finish
# comfortably inside that, or `stop` starts lying about what it did.
WRITE_DRAIN_TIMEOUT_S = 5.0

# How long `stop` will wait after SIGTERM for the server to go before it
# reports the session dead.
#
# Task 9 owns `stop` and is where this is spent; it lives here because it is
# half of a relationship, and the other half is WRITE_DRAIN_TIMEOUT_S above.
# Written as a bare 10 in a test instead, the coupling was asserted against a
# number rather than against the wait it stands for: shorten the wait in Task
# 9 and the assertion goes on passing while `stop` starts reporting a death
# that has not happened. Named here so that the two constants can be compared
# to each other, which is the thing that actually has to hold.
STOP_SIGTERM_WAIT_S = 10.0


def info_path(session):
    return session.craft_dir / "server-info"


def error_path(session):
    return session.craft_dir / "serve-error"


def log_path(session):
    """Where the detached server's stderr goes.

    A background process has no terminal to complain to, and it has two
    things worth complaining about: a request that failed with a bug in a
    handler, and the lock file being removed under it. Sending those to
    DEVNULL would make the second one -- which is the holder's only chance to
    notice that another session may now own the project -- unobservable by
    anybody. Opened for append, never truncated: truncating would be a
    destructive act performed by a `serve` that may be about to be refused,
    and everything written here is exceptional rather than per-request.
    """
    return session.craft_dir / "server.log"


def read_server_info(session):
    """The recorded server-info as a dict, or None.

    Every way it can fail to be a JSON object is None and not an exception:
    missing, half-written, a directory, unreadable, or a JSON array. Later
    commands branch on this rather than guard it.

    A server-info that is present says a server WAS started, not that one is
    running now -- it survives the session that wrote it, deliberately, so
    that the next `serve` can reuse the port. server_alive is the liveness
    question.
    """
    try:
        info = read_json(info_path(session))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def _pid_alive(pid):
    """Is this pid running?

    Used ONLY to ask whether our own recorded server process is still up, and
    never for mutual exclusion. Deciding who owns a project from a pid is the
    bug the kernel lock exists to remove; see session.py's lock note.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, and is somebody else's
    except OSError:
        return False  # anything else the platform could not answer
    except (OverflowError, ValueError):
        # A pid too large for a C long. int() accepted it, os.kill cannot,
        # and this is a file on disk that anything could have written.
        return False
    return True


def server_alive(session):
    info = read_server_info(session)
    return bool(info and _pid_alive(info.get("pid")))


def _port_free(port):
    """Could a server bind this port right now?

    SO_REUSEADDR because CraftServer sets allow_reuse_address, so the probe
    has to ask the question the real bind will ask. Without it a TIME_WAIT
    left by the previous session's browser makes its own port look taken and
    port reuse never happens.
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    if not 0 < port < 65536:
        return False
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _pick_port(session, requested):
    """Reuse the last port when it is free, so an open tab reconnects itself.

    0 means "any", which is what socket binding already means by it.
    """
    if requested:
        return int(requested)
    info = read_server_info(session)
    if info and _port_free(info.get("port")):
        return int(info["port"])
    return 0


# --------------------------------------------------------------------- serve


def shutdown_and_release(server, session, drain_timeout_s):
    """Stop serving, let the writes already started finish, THEN let go.

    The order is the whole of it. Handler threads are daemons and
    server_close() joins none of them, so a write that was inside
    write_json_atomic when the server stopped goes on running; if the lock is
    released first, that write can land in a project another session has
    already, legitimately, acquired. CRAFT.md is rewritten whole every round,
    so the round the other session collects is the round that disappears.

    Shutting the gate comes before stopping the loop, so that nothing new
    starts writing during the wind-down, and the wait is bounded so that a
    write wedged on an unresponsive filesystem cannot hold the exit open for
    ever. When the bound is reached the lock goes anyway and the reason is
    said out loud: at that point the process is about to exit, and the kernel
    would drop the flock regardless.

    The line saying how the session ended is written here, before the
    release, for the same reason and not merely for tidiness. In the detached
    child sys.stderr IS .craft/server.log, so that line is a write into the
    project like any other, and "a write cannot outlive the session's claim
    on the project" has to include it or it is a rule with an unwritten
    exception. It used to sit in _run_server's finally, after this function
    had already let go.

    Returns whether the drain completed. Safe to call twice, and safe to call
    from inside the thread that was serving -- shutdown() returns at once once
    serve_forever has already stopped.

    One precondition, and it is a deadlock rather than an error if it is
    broken: serve_forever must have been ENTERED at least once. BaseServer
    creates its __is_shut_down event unset and only sets it when serve_forever
    finishes, so shutdown() on a server that never served waits for an event
    nothing will ever set. A failure before serving has nothing in flight to
    drain anyway -- no handler thread has existed -- so those paths close the
    socket and let the caller release the lock instead of coming here.
    """
    server.close_writes()
    server.shutdown()
    server.server_close()
    drained = server.drain_writes(drain_timeout_s)
    if not drained:
        sys.stderr.write(
            "craftui: {} write(s) did not finish within {}s and this session is "
            "letting go of the project anyway; a write still running now may "
            "land in a project another session has taken.\n".format(
                server.writes_in_flight, drain_timeout_s
            )
        )
    # The log is the only record a detached process leaves, and this line is
    # the difference between a session that went through the drain and one
    # that was killed where it stood. Without it, a SIGTERM handler that was
    # never installed looks exactly like one that worked: the default action
    # kills the process, the kernel drops the flock, and every observable
    # outside the process is the same -- while the drain this task exists for
    # has been skipped entirely.
    sys.stderr.write(
        "craftui: session ended {}; the project is free.\n".format(
            "cleanly" if drained else "with writes still running"
        )
    )
    sys.stderr.flush()
    session.release_lock()
    return drained


def _locked_message(session, exc):
    """What a refused `serve` prints. Never a remedy that is `rm`.

    Deleting the lock file is the one act that puts two live holders on one
    project, so neither branch may leave it as the only thing left to try.
    The pid branch names a process to stop. The other branch exists because
    the winner is granted the lock a moment before it writes down who it is,
    and a double-launch's loser usually lands in that window -- so the honest
    thing to say is that a session is starting up, not that some unnameable
    process must be hunted down.
    """
    if exc.pid is None:
        return (
            "LOCKED  a craft session owns {} (holder unknown, started {})\n"
            "        it is starting up, or it did not record which process it "
            "is -- close\n"
            "        that craft session, or wait for it to finish".format(
                session.craft_dir, exc.started_at
            )
        )
    return (
        "LOCKED  another craft session (pid {}, started {}) owns {}\n"
        "        that process is still running; stop it, or kill {}".format(
            exc.pid, exc.started_at, session.craft_dir, exc.pid
        )
    )


def _record_serve_error(session, exit_code, message):
    """Tell the parent why this child is not going to serve.

    attempt_pid is how the parent knows the answer is to its own question:
    nothing here unlinks anything, so a serve-error may be one left behind by
    an attempt that failed minutes ago, and reporting that as this attempt's
    outcome would refuse a `serve` that had actually succeeded.
    """
    try:
        write_json_atomic(
            error_path(session),
            {
                "type": "serve-failed",
                "attempt_pid": os.getpid(),
                "exit_code": exit_code,
                "message": message,
            },
        )
    except OSError:
        # There is nowhere left to say it. The exit code still travels, and
        # the parent's timeout message names the log.
        sys.stderr.write(message + "\n")


def _read_serve_error(session, attempt_pid):
    try:
        failure = read_json(error_path(session))
    except (OSError, ValueError):
        return None
    if not isinstance(failure, dict):
        return None
    if failure.get("attempt_pid") != attempt_pid:
        return None
    return failure


def _build_server(session, args, key):
    """The bound server, with one retry that only a reused port may have.

    _pick_port probes, and then this binds; between the two the port can be
    taken. A port we chose ourselves is not worth failing over -- fall back
    to an ephemeral one. A port the USER asked for is: silently serving on a
    different one is worse than saying the one they named is busy.
    """
    port = _pick_port(session, args.port)
    idle_timeout_s = args.idle_timeout_minutes * 60.0
    try:
        return CraftServer(session, key, port=port, idle_timeout_s=idle_timeout_s)
    except OSError:
        if port and not args.port:
            return CraftServer(session, key, port=0, idle_timeout_s=idle_timeout_s)
        raise


def _stop_serving(server):
    """Refuse new writes, then end serve_forever. Idempotent.

    The gate shuts first for the same reason it does in shutdown_and_release:
    nothing new may start writing during the wind-down.
    """
    server.close_writes()
    server.shutdown()


def _say_then_stop(server, message):
    """Say why the session is ending, then end it -- and end it regardless.

    Both halves are load-bearing and they were learned in that order.

    The message goes FIRST because shutdown() frees the main thread to run
    the exit path, and this is a daemon thread with no promise of another
    instruction after that. Announcing afterwards lost the announcement in 12
    runs out of 20 on a loaded machine: the server exited cleanly and the log
    said only that, with nothing to say the project had been taken. This
    notice is the entire point of the check that produces it.

    The write sits under a finally because it must not be able to prevent the
    shutdown it is announcing. A full filesystem -- exactly the sort of state
    a project directory is in when things are going wrong -- raised here,
    skipped the shutdown, and killed the one thread able to end the session,
    leaving the server holding a project another session already owned for
    the rest of the four-hour idle default.
    """
    try:
        try:
            sys.stderr.write(message)
            sys.stderr.flush()
        finally:
            _stop_serving(server)
    except Exception:
        # There is nowhere left to say it, and saying it was never the job --
        # ending the session is, and the finally above has already done it.
        pass


def _watchdog(server, session):
    """The two reasons a running session stops on its own.

    Runs on its own thread; server.shutdown() from here is what ends
    serve_forever on the main one.

    This thread is the ONLY thing that can end a session that nobody signals,
    which is what makes an exception in here different from an exception
    anywhere else: it does not fail a request, it removes the one party able
    to notice that the project has been taken. So the loop body fails closed.
    A raise ends the session rather than the thread, because a watchdog that
    cannot decide must not go on watching in name only -- the alternative,
    measured, is a server holding somebody else's project for the whole
    four-hour idle default with nothing in the log to say why.

    That is one of the two remedies here and it is deliberately not the only
    one; see _say_then_stop for the other, and for why the two are worth
    having separately.
    """
    while True:
        try:
            time.sleep(WATCHDOG_INTERVAL_S)
            # If our lock file was removed or replaced under us, another
            # session can already have acquired the project and be rewriting
            # CRAFT.md. No acquirer-side check can prevent that -- once the
            # name is gone there is nothing left to compare against -- so the
            # holder is the only party that can still notice. Say so loudly,
            # and get out whether or not saying it worked.
            if not session.verify_lock_still_ours():
                _say_then_stop(
                    server,
                    "craftui: {} was removed or replaced; another session may "
                    "now hold this project. Shutting down rather than risk two "
                    "writers on CRAFT.md.\n".format(session.lock_path),
                )
                return
            if server.idle_seconds() > server.idle_timeout_s:
                _stop_serving(server)
                return
        except BaseException as exc:  # noqa: BLE001 -- deliberate, see above
            _say_then_stop(
                server,
                "craftui: the session watchdog stopped with {!r}; shutting "
                "down rather than hold this project unwatched.\n".format(exc),
            )
            return


def _serve_child(args):
    """The server process itself. Owns the project lock for its whole life."""
    session = Session(args.project_dir)
    try:
        session.ensure_dirs()
        session.acquire_lock()
    except LockHeld as exc:
        _record_serve_error(session, 4, _locked_message(session, exc))
        return 4
    except (LockUnavailable, OSError) as exc:
        _record_serve_error(session, 1, "ERROR   {}".format(exc))
        return 1
    try:
        return _run_server(session, args)
    finally:
        # A backstop, and idempotent: the ordinary path released the lock
        # inside shutdown_and_release, after the drain. This one covers the
        # paths that never got that far.
        session.release_lock()


def _run_server(session, args):
    key = make_key()
    try:
        server = _build_server(session, args, key)
    except OSError as exc:
        _record_serve_error(
            session,
            1,
            "ERROR   the craft UI server could not bind 127.0.0.1 port {}: "
            "{}".format(args.port, exc),
        )
        return 1

    def stop():
        _stop_serving(server)

    def on_signal(signum, frame):
        # Off the signal handler entirely: shutdown() waits for the serving
        # loop, which is the thread this handler is interrupting.
        threading.Thread(target=stop, daemon=True).start()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    threading.Thread(target=_watchdog, args=(server, session), daemon=True).start()

    try:
        write_json_atomic(
            info_path(session),
            {
                "type": "server-started",
                "port": server.port,
                "pid": os.getpid(),
                "key": key,
                # The address that was actually bound, not a name for it. This
                # server binds 127.0.0.1 only, and "localhost" resolves to ::1
                # first on plenty of machines.
                "url": "http://{}:{}/?key={}".format(
                    server.server_address[0], server.port, key
                ),
            },
        )
    except OSError as exc:
        # A read-only project, a full disk. The server is up and nobody can
        # be told where -- so say that, rather than leave the parent to
        # discover it as a fifteen-second silence.
        _record_serve_error(
            session, 1, "ERROR   {} could not be written: {}".format(
                info_path(session).name, exc))
        # Not shutdown_and_release: serve_forever has not been entered, so
        # shutdown() would wait for an event nothing will set -- and there is
        # nothing to drain, because no request has ever been accepted. The
        # lock goes back in _serve_child's finally.
        server.close_writes()
        server.server_close()
        return 1
    try:
        server.serve_forever()
    finally:
        # This says how the session ended as well as ending it -- the notice
        # is written in there, ahead of the release, so that no write of ours
        # outlives our claim on the project.
        shutdown_and_release(server, session, WRITE_DRAIN_TIMEOUT_S)
    return 0


def cmd_serve(args):
    session = Session(args.project_dir)
    try:
        session.ensure_dirs()
    except OSError as exc:
        print("ERROR   {} could not be created: {}".format(session.craft_dir, exc))
        return 1

    child_argv = [
        sys.executable,
        os.path.abspath(__file__),
        "serve",
        "--project-dir",
        str(session.project_dir),
        "--port",
        str(args.port),
        "--idle-timeout-minutes",
        repr(args.idle_timeout_minutes),
        "--_child",
    ]

    # The detached server has no terminal, so its stderr goes somewhere it
    # can be read afterwards. Opened before the spawn and closed straight
    # after: the child keeps its own descriptor.
    try:
        log = open(str(log_path(session)), "a", encoding="utf-8")
    except OSError:
        log = None
    try:
        child = subprocess.Popen(
            child_argv,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log.fileno() if log else subprocess.DEVNULL,
            stderr=log.fileno() if log else subprocess.DEVNULL,
        )
    except OSError as exc:
        print("ERROR   the craft UI server could not be started: {}".format(exc))
        return 1
    finally:
        if log is not None:
            log.close()

    deadline = time.monotonic() + SERVE_START_TIMEOUT_S
    while True:
        # Sampled BEFORE the files are read, so that a child which wrote its
        # answer and then exited is still reported by its answer: if this is
        # True, whatever it was going to write is already there.
        exited = child.poll() is not None
        failure = _read_serve_error(session, child.pid)
        if failure is not None:
            print(failure.get("message", "ERROR   the craft UI server did not start"))
            try:
                # A file on disk, even if only our own child should have
                # written it. A shell reads the exit code, so it has to be
                # an int or the CLI ends in a traceback instead of a code.
                return int(failure["exit_code"])
            except (KeyError, TypeError, ValueError):
                return 1
        info = read_server_info(session)
        if info and info.get("pid") == child.pid:
            print(json.dumps(info))
            if args.open:
                webbrowser.open(info["url"])
            return 0
        if exited:
            print(
                "ERROR   the craft UI server exited ({}) without starting. See "
                "{}".format(child.returncode, log_path(session))
            )
            return 1
        if time.monotonic() >= deadline:
            print(
                "ERROR   the craft UI server did not start within {}s. See "
                "{}".format(SERVE_START_TIMEOUT_S, log_path(session))
            )
            return 1
        time.sleep(SERVE_POLL_S)


# ---------------------------------------------------------------------- wait

# How often `wait` looks.
#
# It runs for hours and it ends a person's silence, so it is pulled both
# ways. A look is a read of the answers file, a read of server-info and one
# kill(pid, 0): measured at 18.9 us of cpu, so four a second is 0.008% of a
# core and 2.2 s of cpu across an eight-hour wait. That is the cheap half.
# The other half is that a quarter of a second is under the ~1 s at which a
# person notices that something waited, so pressing Send and having the agent
# wake reads as immediate.
#
# Faster buys nothing anybody can perceive. Slower is what actually costs:
# it stretches DEAD_SERVER_STRIKES, so a dead session goes unreported for
# longer, and it puts a visible pause between Send and the agent's reply.
# It is also WATCHDOG_INTERVAL_S, which is the same trade made once already
# in this file.
POLL_S = 0.25

# How many consecutive looks may find no live server before `wait` gives up
# on the session.
#
# Consecutive, not cumulative, because the miss this has to survive is a
# `serve` restart: from the moment the old process dies until the new one
# writes server-info, every look misses, and a single miss read as a death
# would end a wait the user is still typing into. Eight looks is two seconds;
# a serve spawn from launch to server-info measured 0.112-0.144 s over five
# runs, so the window is more than an order of magnitude clear of it.
#
# The consequence at the other end, and it is deliberate: a `wait` started
# before any server exists does not sit there hoping one appears. It reports
# NOSERVER after ~2 s, because "no server has ever been started here" and
# "the server has gone" are the same fact to the agent, and both are answered
# by starting one.
DEAD_SERVER_STRIKES = 8

# How many consecutive looks may find an answers file that exists and cannot
# be read before that is reported rather than retried.
#
# The retry is the point: the file is written by another process, so a read
# can land in the middle of one. That is a moment -- write_json_atomic
# renames a complete file into place, so under this name a torn read is
# barely reachable at all -- and two seconds of it is three orders of
# magnitude more than a rename needs.
#
# What the bound is for is the other case. A file that is a directory, or is
# unreadable, or holds something that is not a round of answers, will never
# become readable, and retrying it until the deadline would report TIMEOUT --
# which the skill answers by arming another wait that can only fail the same
# way, for ever. Saying so once is the only exit from that loop.
UNREADABLE_STRIKES = 8

ABSENT, UNREADABLE, READY = "absent", "unreadable", "ready"


def read_answers(path):
    """(state, payload) for a round's answers file. Never raises.

    Read first and ask whether it exists afterwards, rather than the other
    way round: os.replace is what puts this file there, so a check followed
    by a read has a window between them, and the read's own errno answers the
    question anyway. FileNotFoundError is the file not being there yet; every
    other OSError is a file that is there and cannot be read -- a directory,
    a permission, a .craft that stopped being a directory, and on Windows a
    share violation against the rename itself.

    A payload that is not an object is UNREADABLE rather than READY. `null`,
    `[]` and `"nonsense"` are all valid JSON, and .get on any of them is an
    AttributeError out of a command whose whole job is to return a code.
    """
    try:
        payload = read_json(path)
    except FileNotFoundError:
        return ABSENT, None
    except (OSError, ValueError):
        return UNREADABLE, None
    if not isinstance(payload, dict):
        return UNREADABLE, None
    return READY, payload


def cmd_wait(args):
    """Block until the user sends this round, and say what happened.

    This is the seam between an agent's turn and a human's attention: the
    agent writes a round, starts this, and stops. Whatever this prints is the
    whole of what the agent knows when it wakes up, so there is exactly one
    line of it and the exit code says the same thing the line does.

    It reads. It writes nothing -- not the answers, not .craft, not a lock --
    because a wait against a project no server ever ran in must leave no
    trace of one.
    """
    session = Session(args.project_dir)
    answers = session.answers_path(args.round)
    deadline = time.monotonic() + args.timeout
    dead_server_strikes = 0
    unreadable_strikes = 0

    while True:
        state, payload = read_answers(answers)
        if state == READY:
            # `is True`, not truthiness: bool("false") is True, which is the
            # reason the server refuses a `finished` that is not a boolean.
            # Anything else here is a hand-edited file, and the two mistakes
            # are not the same size -- FINISHED ends the conversation, while
            # SUBMITTED costs one more round of questions.
            token = "FINISHED" if payload.get("finished") is True else "SUBMITTED"
            print("{} round={} answers={}".format(token, args.round, answers))
            return 0

        if state == UNREADABLE:
            # No liveness check on this path, deliberately: the round is
            # already on disk, so whether the server is still up is not the
            # question any more.
            unreadable_strikes += 1
            if unreadable_strikes >= UNREADABLE_STRIKES:
                print(
                    "ERROR   {} exists and cannot be read as a round of "
                    "answers".format(answers)
                )
                return 1
        else:
            unreadable_strikes = 0
            dead_server_strikes = (
                0 if server_alive(session) else dead_server_strikes + 1
            )
            if dead_server_strikes >= DEAD_SERVER_STRIKES:
                print("NOSERVER")
                return 3

        # Every path through the loop reaches this. A retry that skipped it
        # would be a --timeout that does not exist, and the agent would never
        # get its turn back.
        if time.monotonic() >= deadline:
            print("TIMEOUT round={}".format(args.round))
            # Said where it cannot be mistaken for the outcome, because the
            # outcome is one line on stdout and a shell reads it. TIMEOUT is
            # a heartbeat: the agent arms another wait and the user goes on
            # typing. Left as the bare word in a transcript otherwise full of
            # failures, it reads as one.
            sys.stderr.write(
                "craftui: round {} is still open after {:g}s and nothing has "
                "been sent yet. This is a heartbeat, not a failure -- run "
                "wait again to go on waiting.\n".format(args.round, args.timeout)
            )
            return 2
        time.sleep(POLL_S)


# ----------------------------------------------------------------------- cli


def _positive_duration(text, unit):
    """A float duration in `unit` that is actually a duration.

    The two durations on this command line fail the same four ways, so they
    are refused in the same place. Zero and negative shut the server down on
    the watchdog's first tick -- which looks exactly like a server that
    failed to start -- and make a `wait` that is over before it begins. NaN
    is the one worth naming: it compares false against everything, so an idle
    check built from it never fires again and a deadline built from it is
    never reached. Refused here, before a lock is taken, before a browser is
    opened, and before anything is written.
    """
    try:
        value = float(text)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            "{!r} is not a number of {}".format(text, unit))
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(
            "a positive number of {} is required, not {!r}".format(unit, text))
    return value


def _idle_minutes(text):
    return _positive_duration(text, "minutes")


def _timeout_seconds(text):
    return _positive_duration(text, "seconds")


ROUND_RANGE = "a round number is {} to {}".format(MIN_ROUND, MAX_ROUND)


def _round_number(text):
    """The same round number the server would parse out of a request.

    One round, one spelling, on both sides of the wire: parse_round is what
    decides which file a POST writes, so it has to be what decides which file
    `wait` watches. Its own comment has the reasoning -- no sign, no leading
    zero, no float, and not str.isdigit(), which is true of "\u0663".

    Refused at the flag rather than waited out. A round that cannot name a
    file is a wait against a file that can never appear, and the agent would
    spend the whole timeout finding that out.
    """
    number = parse_round(text)
    if number is None:
        raise argparse.ArgumentTypeError("{}, not {!r}".format(ROUND_RANGE, text))
    return number


# A port as it may be written on the command line: ASCII decimal digits, and
# no more of them than a port can have. Not int() on its own, which is happy
# with " 1", with "\n80", and with "٣" -- the same trap session.py's
# _ROUND_TEXT is written around. None of those is dangerous for a port, but a
# flag that accepts three spellings of the same number is a flag two people
# will describe differently.
_PORT_TEXT = re.compile(r"\A[0-9]{1,5}\Z")

PORT_RANGE = "a port is 0 to 65535, where 0 means any free port"


def _port_number(text):
    if not _PORT_TEXT.match(text or ""):
        raise argparse.ArgumentTypeError("{}, not {!r}".format(PORT_RANGE, text))
    value = int(text)
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError("{}, not {!r}".format(PORT_RANGE, text))
    return value


# What "you called me wrong" exits with. EX_USAGE from sysexits.h, and
# outside every code this CLI documents. See CraftParser.
USAGE_EXIT = 64


class CraftParser(argparse.ArgumentParser):
    """A parser whose usage errors cannot be mistaken for an outcome.

    argparse exits 2 for "you called me wrong", and this CLI documents 2 as
    TIMEOUT -- which the craft skill reads as "the user is still thinking"
    and answers by running `wait` again. So a renamed or mistyped flag would
    put the skill in a loop, waiting for ever on a command that never ran and
    on a user who was never asked anything. The caller building argv here is
    an agent reading a skill file, which is precisely where a flag name goes
    wrong.

    Subcommands inherit this: add_subparsers defaults parser_class to
    type(self), so every subparser is a CraftParser too, and it is a
    subparser that refuses a bad --port or --round.

    error() only. --help and --version go through exit() and still leave 0,
    because asking how to call it is not calling it wrong.
    """

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("{}: error: {}\n".format(self.prog, message))
        raise SystemExit(USAGE_EXIT)


def build_parser():
    parser = CraftParser(prog="craftui")
    subs = parser.add_subparsers(dest="command", required=True)

    serve = subs.add_parser("serve", help="start the craft UI server")
    serve.add_argument("--project-dir", default=".")
    serve.add_argument("--port", type=_port_number, default=0)
    serve.add_argument("--open", action="store_true")
    serve.add_argument("--idle-timeout-minutes", type=_idle_minutes, default=240.0)
    # There is no --force. The lock is a kernel lock held on an open
    # descriptor for the holder's whole life, so a lock that is held always
    # means a live holder and the only remedy is to end that process.
    serve.add_argument(
        "--_child", dest="_child", action="store_true", help=argparse.SUPPRESS
    )
    serve.set_defaults(func=lambda a: _serve_child(a) if a._child else cmd_serve(a))

    wait = subs.add_parser("wait", help="block until the user sends a round")
    wait.add_argument("--project-dir", default=".")
    wait.add_argument("--round", type=_round_number, required=True)
    # Fifteen minutes. Long enough that an agent is not woken for nothing
    # while somebody reads the questions properly, short enough that a
    # session which ended in the browser is noticed the same afternoon.
    wait.add_argument("--timeout", type=_timeout_seconds, default=900.0)
    wait.set_defaults(func=cmd_wait)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
