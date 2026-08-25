"""HTTP surface for the craft UI.

Deliberately stupid: it moves JSON between the agent's files and the browser
and renders CRAFT.md for display. It makes no product decisions, contacts no
model, and never writes CRAFT.md.

It is also the only part of this tool that anything on the machine can reach,
so the parts that are not stupid are all in one place and all here:

* Loopback only, enforced in the constructor rather than assumed from a
  default argument, and enforced BEFORE the bind.
* Every request carries the session key, whatever its method, checked
  before the path is even looked at -- so a caller without it cannot tell an
  endpoint from a typo, and cannot use the 404 as a filesystem probe. GET is
  the only method that goes anywhere; every other method, the ones nobody
  here has heard of included, is refused behind the key rather than by the
  stdlib in front of it.
  The one thing that stays in front of it is a request the stdlib cannot
  parse at all -- a URL too long, too many headers, an HTTP version it does
  not speak -- which it answers itself with 414, 431 or 505 before any code
  here runs. Those touch nothing and say nothing about the machine, but they
  are not gated, and claiming otherwise would be a lie in a docstring people
  will trust.
* The key travels in the query string and nowhere else. There is no session
  cookie and no code here that would read one: cookies are scoped to a HOST
  and not to a port (RFC 6265 s8.5), so a cookie set by this server is a
  cookie any other http://127.0.0.1:<port> page can make the browser fetch
  and read back -- and a stolen one was a complete credential, since a
  request carrying it needed no key in the URL at all.
* The key is compared in constant time, against every value the query string
  offers for it.
* Extracting that key is total: a request target that will not parse yields
  no key and the ordinary 403, never an exception in front of the gate.
* Nothing derived from the request ever becomes a filesystem path. Exactly
  three URLs are served and there is no static file handler at all.
* An error tells the browser which of the agent's files is wrong by name and
  stops there: no absolute paths, no tracebacks, nothing about the machine.
* The agent's terminal learns no more than the browser does. Request logging
  is off, and a client hanging up mid-response -- which is all a reload is --
  is counted rather than printed as a traceback full of absolute paths.
* A connection is bounded twice, by two clocks that are not the same clock.
  `timeout` is the idle one socketserver applies with settimeout(); the
  ceiling on reading a whole request is `read_budget`, an absolute deadline,
  because an idle clock every arriving byte resets is not a ceiling at all.
"""
# Deliberate: kept so any annotation added later may use `int | None` syntax
# while this project's floor is Python 3.9. Do not delete.
from __future__ import annotations

import hmac
import io
import ipaddress
import json
import secrets
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import markdown
import schema
from session import describe_os_error, read_json

APP_HTML = Path(__file__).with_name("app.html")

# 256 bits from the OS CSPRNG. The key travels in a URL the user pastes into
# a browser, so it has to survive being seen without being guessable, and hex
# survives copy-paste, shells and query strings without encoding.
KEY_BYTES = 32


def make_key():
    return secrets.token_hex(KEY_BYTES)


def keys_match(supplied, expected):
    """Constant-time comparison of two keys, for any str at all.

    Constant time is cheap here and the alternative is a habit: `==` on a
    secret returns as soon as two bytes differ, and this server answers on
    loopback where scheduling noise is at its smallest. Whether 64 hex
    characters could really be walked out of it over HTTP is not the point --
    the point is that nobody downstream has to work out whether it could.

    hmac.compare_digest refuses non-ASCII str with TypeError, and the value
    arrives from a query string, so both sides are encoded to bytes first. A
    key of "café" must be a refusal, not a traceback out of do_GET -- that
    would be a crash reachable with no credential whatsoever.
    """
    if not isinstance(supplied, str) or not isinstance(expected, str):
        return False
    return hmac.compare_digest(
        supplied.encode("utf-8", "replace"), expected.encode("utf-8", "replace")
    )


def target_parts(target):
    """A request target as (path, query), or ("", "") if it is not one.

    Total by construction, and that is the whole reason it exists. urlsplit
    raises ValueError("Invalid IPv6 URL") on an unbalanced "[" or "]" in an
    authority, and a request target reaches self.path verbatim: CPython
    rewrites a leading "//" to "/", but an ABSOLUTE-form target -- which
    RFC 9112 s3.2.2 says a server has to accept on any request -- is not
    rewritten and arrives intact. `GET http://[::1/ HTTP/1.0` therefore
    raised out of key extraction, which runs in front of the auth check: no
    response at all, on every method, to a caller holding no credential, and
    one line on the agent's terminal per attempt at whatever rate they liked.

    Anything that will not parse yields no path and no query, which is no
    key, which is the same 403 a typo gets. That is the honest answer: an
    unparseable target is not a request for anything this server has.
    """
    try:
        parts = urlsplit(target)
    except ValueError:
        return "", ""
    return parts.path, parts.query


def _reason(exc):
    """An exception as a phrase for the browser, with no path in it.

    The person at the browser is not always the person who started the
    session, and where the agent keeps its files is not theirs to learn. The
    file's own name is said separately by the caller, which is the part that
    is actually useful.
    """
    if isinstance(exc, OSError):
        return describe_os_error(exc)
    return str(exc)


def require_loopback(host):
    """Refuse any bind address that is not the loopback interface.

    The default argument is not the guarantee: a one-character edit turns it
    into "" and puts the brief, and a URL carrying the session key, on every
    interface the machine has. Checked here, before the socket exists, so a
    refusal never leaves a port open behind it.
    """
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is None or not address.is_loopback:
            raise ValueError(
                "the craft UI serves loopback only, so it cannot bind {!r}; "
                "use 127.0.0.1, ::1 or localhost".format(host)
            )


class _RequestReader(io.RawIOBase):
    """The connection, read under one absolute deadline for the whole request.

    `timeout` is applied by socketserver with settimeout(), which is an IDLE
    clock and not a ceiling: every byte that arrives resets it. A client
    trickling one byte per just-under-timeout seconds therefore holds a
    thread and a descriptor for as long as it cares to -- readline(65537)
    will take 64 KiB at that rate, and the header parser another hundred
    lines after it -- which is days, from any unprivileged process on the
    machine, at a cost of one byte a minute.

    So the ceiling is an absolute deadline, and it is enforced HERE, on the
    recv, rather than around the readline that loops over recvs: arming it
    per readline would give the whole budget back to every byte, which is
    the bug again with more steps. Each read gets whichever is smaller of
    what is left of the budget and the idle clock, so the request line and
    the headers together are read inside `read_budget` seconds or the
    connection ends.

    The budget is lifted the moment the headers are parsed, because nothing
    in this server reads a body and an honest client may legitimately read a
    response slowly. From there the idle clock alone bounds the write.
    """

    def __init__(self, handler):
        io.RawIOBase.__init__(self)
        self._handler = handler
        self._deadline = None

    def start(self):
        """Begin one request's budget, now."""
        self._deadline = time.monotonic() + self._handler.read_budget

    def finished(self):
        """The request is read; the response is the idle clock's problem."""
        self._deadline = None
        self._handler.connection.settimeout(self._handler.timeout)

    def readable(self):
        return True

    def readinto(self, buffer):
        connection = self._handler.connection
        idle = self._handler.timeout
        if self._deadline is not None:
            left = self._deadline - time.monotonic()
            if left <= 0:
                self._handler.timed_out = True
                raise socket.timeout("the request outlived its read budget")
            connection.settimeout(left if idle is None else min(left, idle))
        try:
            return connection.recv_into(buffer)
        except socket.timeout:
            # Recorded rather than merely raised. BaseHTTPRequestHandler
            # swallows this, and handle_one_request below could only ever
            # observe a timeout on the request LINE -- so a client stalling
            # inside its headers closed the connection and left no trace at
            # all. Every read timeout is one read timeout, wherever it fell.
            self._handler.timed_out = True
            raise


class _Handler(BaseHTTPRequestHandler):
    server_version = "craftui"
    sys_version = ""  # no free interpreter version for anything scanning ports

    # The IDLE clock, and only that: socketserver hands it to settimeout(),
    # so it bounds the gap between two bytes and never a whole request. It is
    # what ends a connection that is opened and then goes quiet -- three
    # hundred of those hold three hundred threads and descriptors, and
    # nothing here reaps them. Generous, because after the headers it is also
    # what bounds a client reading a response slowly, which is a thing an
    # honest client may do.
    timeout = 30

    # The ceiling the line above is NOT. An absolute deadline for reading one
    # whole request, enforced per recv by _RequestReader. Generous for the
    # same reason and for one more: every request this server answers is a
    # request line and a handful of headers, so thirty seconds is not a
    # budget any honest client has ever needed to notice.
    read_budget = 30

    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        self.timed_out = False
        # The stdlib's rfile is a buffered reader over the socket, and its
        # every read gets the idle clock afresh. Swap in one that reads the
        # same socket under the budget above. Closing the old one releases
        # makefile's reference and nothing else; the socket belongs to
        # socketserver, which closes it in shutdown_request.
        self.rfile.close()
        self._reader = _RequestReader(self)
        size = self.rbufsize if self.rbufsize > 0 else io.DEFAULT_BUFFER_SIZE
        self.rfile = io.BufferedReader(self._reader, size)

    def parse_request(self):
        parsed = BaseHTTPRequestHandler.parse_request(self)
        # Reached whether the request parsed or not, and in both cases the
        # reading is over: a bad request is answered and the connection ends.
        self._reader.finished()
        return parsed

    def log_message(self, fmt, *args):
        pass  # the agent's terminal is not a web log

    def handle_timeout(self):
        """The client went quiet mid-request, so the connection ends.

        socketserver puts `timeout` on the socket and BaseHTTPRequestHandler
        catches the socket.timeout that follows, silences it through
        log_error and returns -- so the connection does close, but no policy
        was chosen and nothing can see that it happened. This is the policy,
        and the count is how a test says the ceiling above is real.
        """
        self.close_connection = True
        self.server.timeouts += 1

    def handle_one_request(self):
        # Two signals, because they see different halves of the same thing.
        # _RequestReader sets timed_out on any read timeout, headers
        # included, which is where the count used to be lost. raw_requestline
        # stays as the backstop it always was: it is assigned from
        # rfile.readline(), so anything that raises before the assignment --
        # and the stdlib swallows it -- leaves the request line unset.
        self.raw_requestline = None
        self.timed_out = False
        self._reader.start()
        BaseHTTPRequestHandler.handle_one_request(self)
        if self.timed_out or self.raw_requestline is None:
            self.handle_timeout()

    def _supplied_keys(self):
        """Every key this request's query string offers. Never raises.

        The query string is the only place a key may come from -- see the
        cookie paragraph in the module docstring -- and target_parts is what
        keeps a malformed target from raising in front of the gate.
        """
        query = parse_qs(target_parts(self.path)[1], keep_blank_values=True)
        return list(query.get("key", []))

    def _authed(self):
        expected = self.server.key
        for supplied in self._supplied_keys():
            if keys_match(supplied, expected):
                return True
        return False

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # The page's own URL carries the key; a cached copy of any of this is
        # a copy of the user's brief somebody did not mean to keep.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # The key is in the query string, so every outbound navigation is a
        # chance to hand it to a third party in a Referer. markdown.py already
        # puts rel="noreferrer" on brief links; this covers everything else.
        self.send_header("Referrer-Policy", "no-referrer")
        # No Set-Cookie, deliberately, and this is the only place one could
        # go. A cookie here was scoped to 127.0.0.1 as a HOST -- ports do not
        # separate cookie jars -- so any other local port could pull one
        # subresource off this server and read the key back out of the
        # response it caused. Nothing needs it: the page is one file with no
        # subresources and every fetch it makes appends ?key=.
        self.end_headers()
        # A HEAD is answered with the headers a GET would carry and none of
        # the body. protocol_version is HTTP/1.0, so a body written anyway is
        # merely discarded by the close that follows -- but it is bytes the
        # protocol says are not there, and it becomes the start of the next
        # response the day anything here speaks 1.1.
        if self.command != "HEAD":
            self.wfile.write(data)

    def _text(self, code, body):
        self._send(code, body, "text/plain; charset=utf-8")

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json; charset=utf-8")

    def do_GET(self):
        # Auth first, and identically for every URL: a caller without the key
        # learns only that something is listening. Note that touch() comes
        # after -- an anonymous caller must not be able to hold an abandoned
        # session (and the project lock under it) open for ever by polling.
        if not self._authed():
            return self._text(403, "forbidden")
        self.server.touch()
        path = target_parts(self.path)[0]
        if path == "/":
            return self._page()
        if path == "/api/round":
            return self._json(self.server.round_payload())
        if path == "/api/brief":
            return self._json(self.server.brief_payload())
        return self._text(404, "not found")

    def __getattr__(self, name):
        """Any do_* at all, so that "every method is gated" is true.

        Naming the six methods below was narrower than the docstring
        claimed: TRACE, CONNECT and any three letters somebody invents have
        no do_* of their own, so the stdlib answered them with a 501 from
        inside handle_one_request -- no key checked, and none of the four
        hardening headers every other response here carries. Nothing escaped
        through that (the method name is escaped, and a 501 says nothing
        about the machine), but the gap was in the one place this file says
        there is no gap, and a docstring people trust is worth more than the
        four lines it costs to make it true.

        __getattr__ runs only when ordinary lookup has already failed, so
        do_GET and the assignments below are untouched by it, and anything
        that is not a do_* -- the stdlib's own hasattr(self,
        "_headers_buffer") among them -- still gets its AttributeError.
        """
        if name.startswith("do_"):
            return self._unsupported
        raise AttributeError(name)

    def _unsupported(self):
        """Every method that is not GET: gated first, refused second.

        Left alone, the stdlib answers a method with no do_* by sending a 501
        of its own from inside handle_one_request -- before any handler runs,
        so with no key checked and none of the headers every other response
        here carries. What this server does not implement it should not
        implement differently for a caller holding the key and a caller who
        is not; __getattr__ above is what makes sure nothing reaches that
        501, whatever the method is called.

        Task 6 replaces the POST and PATCH arms with real handlers. Its rule
        is this one: _authed() first, before anything is read or touched.
        """
        if self.headers.get("Content-Length") or self.headers.get("Transfer-Encoding"):
            # Nothing here reads the body, and an unread body is the start of
            # the next request as far as the connection is concerned. Already
            # true today, since protocol_version is HTTP/1.0 and every
            # response is followed by a close; said out loud so that it stays
            # true, because task 6's handlers arrive on this same path.
            self.close_connection = True
        if not self._authed():
            return self._text(403, "forbidden")
        self.server.touch()
        return self._text(501, "not implemented")

    # Named as well as caught by __getattr__: these are the ones task 6 comes
    # back for, and a real handler wants a real assignment to replace.
    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _unsupported

    def _page(self):
        try:
            body = APP_HTML.read_bytes()
        except OSError:
            # Letting this raise sends no response at all -- the browser sees
            # a reset connection -- and prints the absolute path in a
            # traceback across the agent's terminal.
            return self._text(500, "the craft UI page could not be read")
        return self._send(200, body, "text/html; charset=utf-8")


class CraftServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, session, key, host="127.0.0.1", port=0, idle_timeout_s=14400):
        require_loopback(host)
        if ":" in host:
            self.address_family = socket.AF_INET6
        ThreadingHTTPServer.__init__(self, (host, port), _Handler)
        self.session = session
        self.key = key
        self.idle_timeout_s = idle_timeout_s
        self._last = time.monotonic()
        # What has gone wrong and how often. A count is the whole of the
        # record, because nothing here prints a traceback -- see handle_error.
        self.disconnects = 0
        self.handler_errors = 0
        self.timeouts = 0

    def handle_error(self, request, client_address):
        """A client hanging up is not news. Anything else is, quietly.

        socketserver's own handle_error prints a whole traceback to stderr,
        absolute paths and all, and an ordinary browser produces one every
        time a page is reloaded or navigated away from mid-response. That is
        the invariant every response here keeps, spilled onto the agent's
        terminal by a reload -- and reachable with a perfectly valid key.

        Not a blanket pass, though: a genuine bug in a handler still has to
        be findable, so it is counted and one terse line names the exception
        TYPE. Not its message and not the request line: an OSError's message
        carries the path it failed on, and the request line carries the
        session key. A type and a count are enough to know a bug is there and
        to go and reproduce it, and neither of them is about this machine.
        """
        exc = sys.exc_info()[1]
        # ConnectionError is the whole family: broken pipe, reset by peer,
        # aborted. socket.timeout is separate, and is TimeoutError from 3.10.
        if isinstance(exc, (ConnectionError, socket.timeout)):
            self.disconnects += 1
            return
        self.handler_errors += 1
        print(
            "craft ui: a request failed with {}".format(type(exc).__name__),
            file=sys.stderr,
        )

    @property
    def port(self):
        return self.server_address[1]

    def touch(self):
        self._last = time.monotonic()

    def idle_seconds(self):
        return time.monotonic() - self._last

    def round_payload(self):
        """The current round, or why it cannot be served.

        Never raises, and that now includes finding out WHICH round it is.
        current_round() sat outside the guard while raising like everything
        else that touches a filesystem: it calls is_dir() and then
        iterdir(), and a .craft/ that passes the first and refuses the
        second -- mode 000, or any of the ways a directory can stop being
        readable between two syscalls -- took the request down with it. The
        browser got a reset connection, which is exactly the failure _page
        is already guarded against.

        The agent writes these files while the browser is polling them, and
        a half-written, hand-edited or unreadable round has to come back as
        a message on the page.
        """
        try:
            number = self.session.current_round()
        except OSError as exc:
            # Named by the directory, not by where it is: the same rule the
            # file-level messages below keep.
            return {
                "ok": False,
                "error": "{} could not be read: {}".format(
                    self.session.craft_dir.name, _reason(exc)
                ),
            }
        if number is None:
            return {"ok": True, "round": None}
        name = self.session.questions_path(number).name
        try:
            obj = read_json(self.session.questions_path(number))
        except ValueError as exc:  # malformed JSON, or bytes that are not UTF-8
            return {"ok": False, "error": "{} is not valid JSON: {}".format(name, exc)}
        except OSError as exc:
            return {
                "ok": False,
                "error": "{} could not be read: {}".format(name, _reason(exc)),
            }
        errors = schema.validate_round(obj)
        if errors:
            return {"ok": False, "error": "{} is invalid".format(name), "details": errors}
        return {"ok": True, "round": obj}

    def brief_payload(self):
        """CRAFT.md as HTML. Missing is empty; unreadable is said out loud.

        Session.read_brief absorbs a missing file and nothing else, so a
        CRAFT.md that is a directory, or that carries a byte that is not
        UTF-8, would otherwise take the request down with it.
        """
        try:
            text = self.session.read_brief()
        except (OSError, ValueError) as exc:
            return {
                "html": "",
                "error": "CRAFT.md could not be read: {}".format(_reason(exc)),
            }
        return {"html": markdown.render(text)}
