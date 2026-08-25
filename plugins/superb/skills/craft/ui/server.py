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
  the only method that goes anywhere; the rest are refused, but refused here
  and behind the key rather than by the stdlib in front of it.
  The one thing that stays in front of it is a request the stdlib cannot
  parse at all -- a URL too long, too many headers, an HTTP version it does
  not speak -- which it answers itself with 414, 431 or 505 before any code
  here runs. Those touch nothing and say nothing about the machine, but they
  are not gated, and claiming otherwise would be a lie in a docstring people
  will trust.
* The key is compared in constant time, against every value that carries the
  right cookie NAME, never as a substring of the Cookie header.
* Nothing derived from the request ever becomes a filesystem path. Exactly
  three URLs are served and there is no static file handler at all.
* An error tells the browser which of the agent's files is wrong by name and
  stops there: no absolute paths, no tracebacks, nothing about the machine.
* The agent's terminal learns no more than the browser does. Request logging
  is off, and a client hanging up mid-response -- which is all a reload is --
  is counted rather than printed as a traceback full of absolute paths.
"""
# Deliberate: kept so any annotation added later may use `int | None` syntax
# while this project's floor is Python 3.9. Do not delete.
from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import markdown
import schema
from session import describe_os_error, read_json

APP_HTML = Path(__file__).with_name("app.html")
COOKIE = "craftkey"

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


def cookie_values(header, name):
    """Every value in a Cookie header carrying exactly this name.

    Not a substring search over the raw header: `"craftkey=<key>" in header`
    also accepts `xcraftkey=<key>`, and cookies are scoped to a host, NOT to
    a port -- anything else listening on 127.0.0.1 can set a cookie this
    server will be handed.

    Every match, not the last one, which is what a dict-shaped parser gives.
    A browser may send several cookies of one name (differing paths, or a
    host-only one beside a domain one), and a stray `craftkey=junk` from
    another local app must not be able to shadow the real one and lock the
    user out of their own session.

    The NAME is stripped, because the separator is "; " and the space belongs
    to the separator. The VALUE is not: RFC 6265 gives cookie-value no spaces
    at all, so " <key>" and "<key> " are not this key, and widening the match
    by a strip() is a loosening nobody asked for.
    """
    values = []
    for part in (header or "").split(";"):
        crumb, sep, value = part.partition("=")
        if sep and crumb.strip() == name:
            values.append(value)
    return values


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


class _Handler(BaseHTTPRequestHandler):
    server_version = "craftui"
    sys_version = ""  # no free interpreter version for anything scanning ports

    # A connection that is opened and then goes quiet holds a thread and a
    # file descriptor for as long as the client likes; three hundred of them
    # hold three hundred, and nothing here reaps them. This is the ceiling.
    # Generous, because the same clock also bounds a client reading a
    # response slowly, which is a thing an honest client may do.
    timeout = 30

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
        # raw_requestline is assigned from rfile.readline(), so a timeout
        # waiting for the request line raises before the assignment -- and
        # since the stdlib swallows the exception, an unset request line is
        # the only trace a half-open connection leaves behind. A client that
        # sends the request line and then stalls in its headers times out on
        # the same clock, inside parse_headers where this cannot see it: the
        # connection closes either way, only the count misses it.
        self.raw_requestline = None
        BaseHTTPRequestHandler.handle_one_request(self)
        if self.raw_requestline is None:
            self.handle_timeout()

    def _supplied_keys(self):
        """Every key this request offers: query string first, then cookies."""
        query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        return list(query.get("key", [])) + cookie_values(
            self.headers.get("Cookie"), COOKIE
        )

    def _authed(self):
        expected = self.server.key
        for supplied in self._supplied_keys():
            if keys_match(supplied, expected):
                return True
        return False

    def _send(self, code, body, ctype="application/json; charset=utf-8", set_cookie=False):
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
        if set_cookie:
            # HttpOnly: the page reads its key from the URL, never from
            # document.cookie, so script has no business reading this -- and
            # script that wants to is script carrying the key off the machine.
            self.send_header(
                "Set-Cookie",
                "{}={}; Path=/; SameSite=Strict; HttpOnly".format(COOKIE, self.server.key),
            )
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
        path = urlparse(self.path).path
        if path == "/":
            return self._page()
        if path == "/api/round":
            return self._json(self.server.round_payload())
        if path == "/api/brief":
            return self._json(self.server.brief_payload())
        return self._text(404, "not found")

    def _unsupported(self):
        """Every method that is not GET: gated first, refused second.

        The stdlib answers an unknown method with a 501 of its own, from
        inside handle_one_request -- before any handler runs, so with no key
        checked and none of the headers every other response here carries.
        What this server does not implement it should not implement
        differently for a caller holding the key and a caller who is not.

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

    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _unsupported

    def _page(self):
        try:
            body = APP_HTML.read_bytes()
        except OSError:
            # Letting this raise sends no response at all -- the browser sees
            # a reset connection -- and prints the absolute path in a
            # traceback across the agent's terminal.
            return self._text(500, "the craft UI page could not be read")
        return self._send(200, body, "text/html; charset=utf-8", set_cookie=True)


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

        Never raises. The agent writes these files while the browser is
        polling them, and a half-written or hand-edited round has to come
        back as a message on the page rather than as a dead connection.
        """
        number = self.session.current_round()
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
