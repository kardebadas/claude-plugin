#!/usr/bin/env python3
"""craft UI command line.

`serve` starts the local server as a detached background process, hands it
the project lock for its whole life, and writes .craft/server-info so that
the commands after it can find the thing it started.

Exit codes: 0 ok, 2 TIMEOUT, 3 NOSERVER, 4 LOCKED. 1 is everything else that
stopped a command from doing its job.

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

from server import CraftServer, make_key  # noqa: E402
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
# Five and not more because of what is downstream: `stop` sends SIGTERM and
# waits ten seconds for the process to go before it reports. A drain that ran
# to the full bound plus the release after it has to finish comfortably
# inside that, or `stop` starts lying about what it did.
WRITE_DRAIN_TIMEOUT_S = 5.0


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


def _watchdog(server, session):
    """The two reasons a running session stops on its own.

    Runs on its own thread; server.shutdown() from here is what ends
    serve_forever on the main one.
    """
    while True:
        time.sleep(WATCHDOG_INTERVAL_S)
        # If our lock file was removed or replaced under us, another session
        # can already have acquired the project and be rewriting CRAFT.md.
        # No acquirer-side check can prevent that -- once the name is gone
        # there is nothing left to compare against -- so the holder is the
        # only party that can still notice. Say so loudly and get out.
        if not session.verify_lock_still_ours():
            sys.stderr.write(
                "craftui: {} was removed or replaced; another session may now "
                "hold this project. Shutting down rather than risk two writers "
                "on CRAFT.md.\n".format(session.lock_path)
            )
            sys.stderr.flush()
            server.close_writes()
            server.shutdown()
            return
        if server.idle_seconds() > server.idle_timeout_s:
            server.close_writes()
            server.shutdown()
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
        server.close_writes()
        server.shutdown()

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
        drained = shutdown_and_release(server, session, WRITE_DRAIN_TIMEOUT_S)
        # The log is the only record a detached process leaves, and this line
        # is the difference between a session that went through the drain and
        # one that was killed where it stood. Without it, a SIGTERM handler
        # that was never installed looks exactly like one that worked: the
        # default action kills the process, the kernel drops the flock, and
        # every observable outside the process is the same -- while the drain
        # this task exists for has been skipped entirely.
        sys.stderr.write(
            "craftui: session ended {}; the project is free.\n".format(
                "cleanly" if drained else "with writes still running"
            )
        )
        sys.stderr.flush()
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


# ----------------------------------------------------------------------- cli


def _idle_minutes(text):
    """A float number of minutes that is actually a duration.

    Zero and negative shut the server down on the watchdog's first tick,
    which looks exactly like a server that failed to start; NaN compares
    false against everything, so the idle check would never fire again.
    Refused here, before a lock is taken and before anything is written.
    """
    try:
        value = float(text)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("{!r} is not a number of minutes".format(text))
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(
            "the idle timeout must be a positive number of minutes, not {!r}".format(
                text
            )
        )
    return value


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


def build_parser():
    parser = argparse.ArgumentParser(prog="craftui")
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

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
