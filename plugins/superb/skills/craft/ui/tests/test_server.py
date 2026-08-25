"""The HTTP surface: who gets in, what comes out, and what never happens.

Every test here is written against a mutant. The session key is the only thing
standing between a page on the machine and the user's brief, so the auth tests
are adversarial by construction: a prefix of the key, a superstring of it, a
cookie whose NAME merely ends in the right letters, a key that is not ASCII.
Each of those is a one-line change to server.py away from being accepted.
"""
import functools
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import server as server_module
from server import COOKIE, APP_HTML, CraftServer, make_key
from session import Session, write_json_atomic

VALID_ROUND = {
    "round": 1,
    "questions": [
        {"id": "Q-1", "importance": "REQUIRED", "title": "Auth?", "type": "text"}
    ],
}


class ServerTestCase(unittest.TestCase):
    """A live server on an ephemeral port, torn down whatever happens.

    Cleanups rather than tearDown: a failure part-way through setUp still
    releases the port and joins the thread, and the join is asserted, so a
    leaked serving thread fails THIS test instead of flaking somebody else's
    an hour later.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.session = Session(self._tmp.name)
        self.session.ensure_dirs()
        self.key = make_key()
        self.server = self.start_server()
        self.base = "http://127.0.0.1:{}".format(self.server.port)

    def start_server(self, **kw):
        server = CraftServer(self.session, self.key, port=0, **kw)
        self.addCleanup(server.server_close)
        # A short poll interval, because shutdown() waits for the current one
        # and the default 0.5 s is paid by every teardown in this file. Not a
        # sleep and not a race: serve_forever polls, and shutdown() returns
        # only once the loop has actually stopped.
        serve = functools.partial(server.serve_forever, poll_interval=0.01)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        # LIFO: shutdown, then join, then server_close.
        self.addCleanup(self._join, thread)
        self.addCleanup(server.shutdown)
        return server

    def _join(self, thread):
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "the serving thread outlived shutdown()")

    def url(self, path, key=True):
        url = "{}{}".format(self.base, path)
        if key is True:
            key = self.key
        if isinstance(key, str):
            sep = "&" if "?" in path else "?"
            url += sep + "key=" + urllib.parse.quote(key, safe="")
        return url

    def request(self, path, key=True, cookie=None, **kw):
        request = urllib.request.Request(self.url(path, key), **kw)
        if cookie is True:
            cookie = "{}={}".format(COOKIE, self.key)
        if isinstance(cookie, str):
            request.add_header("Cookie", cookie)
        return request

    def get(self, path, **kw):
        return urllib.request.urlopen(self.request(path, **kw), timeout=5)

    def get_json(self, path, **kw):
        response = self.get(path, **kw)
        self.assertIn("application/json", response.headers.get("Content-Type", ""))
        return json.loads(response.read().decode("utf-8"))

    def refused(self, path, **kw):
        """The HTTPError from a request that must not be served."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get(path, **kw)
        return caught.exception


class AuthTest(ServerTestCase):
    def test_no_key_at_all_is_forbidden(self):
        self.assertEqual(self.refused("/", key=False).code, 403)

    def test_a_wrong_key_is_forbidden(self):
        self.assertEqual(self.refused("/", key="deadbeef").code, 403)

    def test_a_prefix_of_the_key_is_forbidden(self):
        """Kills startswith, a truncated compare, and `supplied in key`."""
        self.assertEqual(self.refused("/", key=self.key[:-1]).code, 403)

    def test_a_superstring_of_the_key_is_forbidden(self):
        """Kills `key in supplied` and any substring test in that direction."""
        self.assertEqual(self.refused("/", key=self.key + "x").code, 403)

    def test_a_key_differing_only_in_the_last_character_is_forbidden(self):
        """Kills a compare that stops early, however it got there."""
        last = "0" if self.key[-1] != "0" else "1"
        self.assertEqual(self.refused("/", key=self.key[:-1] + last).code, 403)

    def test_a_non_ascii_key_is_forbidden_and_does_not_crash_the_server(self):
        """secrets.compare_digest raises TypeError on non-ASCII str. A crash
        here would be a 500-shaped hole reachable with no credential at all."""
        self.assertEqual(self.refused("/", key="café☃").code, 403)
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_a_key_with_a_null_byte_is_forbidden(self):
        self.assertEqual(self.refused("/", key=self.key + "\x00").code, 403)

    def test_the_key_in_the_query_string_works(self):
        self.assertEqual(self.get("/").status, 200)

    def test_an_empty_key_parameter_is_forbidden(self):
        """parse_qs drops blank values unless asked not to; an empty key must
        be a refusal either way, never a match against a missing value."""
        self.assertEqual(self.refused("/?key=", key=False).code, 403)

    def test_the_cookie_alone_works(self):
        self.assertEqual(self.get("/", key=False, cookie=True).status, 200)

    def test_the_cookie_works_beside_other_cookies(self):
        header = "ga=1; {}={}; theme=dark".format(COOKIE, self.key)
        self.assertEqual(self.get("/", key=False, cookie=header).status, 200)

    def test_a_cookie_whose_name_merely_ends_in_the_right_letters_is_forbidden(self):
        """The substring check `"craftkey=<key>" in header` accepts this.
        A different local server on 127.0.0.1 can set a cookie for the whole
        host -- cookies are not isolated by port -- so the name must match
        exactly, not as a suffix of somebody else's."""
        header = "x{}={}".format(COOKIE, self.key)
        self.assertEqual(self.refused("/", key=False, cookie=header).code, 403)

    def test_a_cookie_value_with_trailing_junk_is_forbidden(self):
        header = "{}={}junk".format(COOKIE, self.key)
        self.assertEqual(self.refused("/", key=False, cookie=header).code, 403)

    def test_a_padded_cookie_value_is_not_the_key(self):
        """A cookie value has no spaces in it; the space after a ";" belongs
        to the separator and is stripped off the NAME. Widening the value's
        match by a strip() would accept a key that is not the key."""
        # Leading, not trailing: the header parser strips a trailing space off
        # the whole header value before this code ever sees it.
        for header in ("{}= {}", "{}=\t{}", "{}= {} ; x=1"):
            header = header.format(COOKIE, self.key)
            self.assertEqual(self.refused("/", key=False, cookie=header).code, 403, header)

    def test_a_wrong_cookie_does_not_shadow_a_right_one(self):
        """Last-wins cookie parsing turns a stray craftkey= from another
        localhost app into a lockout. Every value carrying the name counts."""
        header = "{0}=junk; {0}={1}".format(COOKIE, self.key)
        self.assertEqual(self.get("/", key=False, cookie=header).status, 200)
        header = "{0}={1}; {0}=junk".format(COOKIE, self.key)
        self.assertEqual(self.get("/", key=False, cookie=header).status, 200)

    def test_a_malformed_cookie_header_is_a_refusal_not_a_crash(self):
        self.assertEqual(self.refused("/", key=False, cookie="=;;;=x=").code, 403)
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_every_endpoint_is_gated_not_just_the_page(self):
        for path in ("/", "/api/round", "/api/brief"):
            self.assertEqual(self.refused(path, key=False).code, 403, path)

    def test_an_unauthorised_caller_cannot_tell_a_real_path_from_a_fake_one(self):
        """Auth runs before routing, so /api/round and /nope look identical to
        somebody without the key. Otherwise the 404 is a filesystem probe."""
        real = self.refused("/api/round", key=False)
        fake = self.refused("/nope", key=False)
        self.assertEqual((real.code, fake.code), (403, 403))
        self.assertEqual(real.read(), fake.read())

    def test_a_refusal_never_echoes_the_key(self):
        error = self.refused("/", key="deadbeef")
        self.assertNotIn(self.key, error.read().decode("utf-8", "replace"))
        self.assertNotIn(self.key, str(error.headers))

    def test_a_refusal_does_not_hand_out_the_cookie(self):
        self.assertIsNone(self.refused("/", key=False).headers.get("Set-Cookie"))

    def test_an_unauthorised_request_cannot_hold_the_session_open(self):
        """The idle clock is what eventually ends an abandoned session. If an
        anonymous caller resets it, any process on the machine can keep the
        server -- and the project lock it holds -- alive indefinitely."""
        self.server._last -= 100
        before = self.server.idle_seconds()
        self.refused("/", key=False)
        self.assertGreaterEqual(self.server.idle_seconds(), before)


class CookieTest(ServerTestCase):
    def cookie_header(self):
        return self.get("/").headers.get("Set-Cookie") or ""

    def test_the_page_sets_the_cookie(self):
        self.assertIn("{}={}".format(COOKIE, self.key), self.cookie_header())

    def test_the_cookie_is_http_only(self):
        """The page takes the key from the URL, never from document.cookie, so
        script has no reason to read it -- and script that wants to read it is
        script exfiltrating the key."""
        self.assertIn("httponly", self.cookie_header().lower())

    def test_the_cookie_is_samesite_strict(self):
        self.assertIn("samesite=strict", self.cookie_header().lower().replace(" ", ""))

    def test_the_cookie_is_scoped_to_the_whole_app(self):
        self.assertIn("path=/", self.cookie_header().lower())

    def test_responses_are_never_cached(self):
        """The page's URL carries the key. A cached copy is a leaked key."""
        for path in ("/", "/api/round", "/api/brief"):
            header = self.get(path).headers.get("Cache-Control", "")
            self.assertIn("no-store", header, path)

    def test_responses_carry_the_hardening_headers(self):
        for path in ("/", "/api/round", "/api/brief"):
            headers = self.get(path).headers
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff", path)
            self.assertEqual(headers.get("Referrer-Policy"), "no-referrer", path)

    def test_the_server_header_does_not_advertise_the_interpreter(self):
        self.assertNotIn("Python", self.get("/").headers.get("Server", ""))


class PageTest(ServerTestCase):
    def test_the_page_is_served_verbatim_as_html(self):
        response = self.get("/")
        self.assertEqual(response.read(), APP_HTML.read_bytes())
        self.assertEqual(response.headers.get("Content-Type"), "text/html; charset=utf-8")

    def test_the_page_is_self_contained(self):
        """No CDN, no remote font, no external script: the whole point of a
        local tool is that it works with the network unplugged, and a remote
        subresource would carry the key-bearing URL off the machine."""
        text = APP_HTML.read_text(encoding="utf-8").lower()
        for forbidden in ("<script src", "src=\"http", "src='http", "href=\"http",
                          "href='http", "@import", "url(http"):
            self.assertNotIn(forbidden, text)

    def test_an_unknown_path_is_404_not_500(self):
        self.assertEqual(self.refused("/nope").code, 404)

    def test_a_traversal_shaped_path_serves_nothing(self):
        for path in ("/../server.py", "/api/round/../../server.py", "/./server.py",
                     "/app.html", "/session.py"):
            error = self.refused(path)
            self.assertEqual(error.code, 404, path)
            self.assertNotIn("make_key", error.read().decode("utf-8", "replace"))

    def test_a_404_body_names_no_path(self):
        body = self.refused("/nope").read().decode("utf-8", "replace")
        self.assertNotIn(self._tmp.name, body)
        self.assertNotIn(str(APP_HTML), body)

    def test_a_missing_page_file_is_a_clean_500_and_the_server_survives(self):
        """A read that raises out of do_GET gets no response at all -- the
        client sees a reset connection and the traceback prints the absolute
        path into the agent's terminal."""
        server_module.APP_HTML = APP_HTML.with_name("does-not-exist.html")
        self.addCleanup(setattr, server_module, "APP_HTML", APP_HTML)
        error = self.refused("/")
        self.assertEqual(error.code, 500)
        body = error.read().decode("utf-8", "replace")
        self.assertNotIn(str(server_module.APP_HTML), body)
        self.assertNotIn("Traceback", body)
        server_module.APP_HTML = APP_HTML
        self.assertEqual(self.get("/").status, 200)

    def test_writing_methods_are_not_served_yet(self):
        for method in ("POST", "PUT", "DELETE"):
            error = self.refused("/api/round", method=method, data=b"{}")
            self.assertEqual(error.code, 501, method)


class RoundTest(ServerTestCase):
    def test_no_rounds_yet(self):
        payload = self.get_json("/api/round")
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["round"])

    def test_a_valid_round_is_served_whole(self):
        write_json_atomic(self.session.questions_path(1), VALID_ROUND)
        payload = self.get_json("/api/round")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["round"], VALID_ROUND)

    def test_a_new_round_supersedes_the_old_one(self):
        write_json_atomic(self.session.questions_path(1), VALID_ROUND)
        self.assertEqual(self.get_json("/api/round")["round"]["round"], 1)
        write_json_atomic(self.session.questions_path(2), dict(VALID_ROUND, round=2))
        self.assertEqual(self.get_json("/api/round")["round"]["round"], 2)

    def test_round_ten_beats_round_nine(self):
        """Highest number, not highest name: a lexical max serves round 9
        forever once the session reaches double figures."""
        for n in (9, 10):
            write_json_atomic(self.session.questions_path(n), dict(VALID_ROUND, round=n))
        self.assertEqual(self.get_json("/api/round")["round"]["round"], 10)

    def test_non_ascii_survives_the_round_trip(self):
        question = dict(VALID_ROUND["questions"][0], title="Café ☃?")
        write_json_atomic(self.session.questions_path(1), dict(VALID_ROUND, questions=[question]))
        payload = self.get_json("/api/round")
        self.assertEqual(payload["round"]["questions"][0]["title"], "Café ☃?")

    def test_malformed_json_reports_an_error_and_the_server_survives(self):
        self.session.questions_path(1).write_text("{not json", encoding="utf-8")
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertIn("round-001.questions.json", payload["error"])
        self.assertEqual(self.get("/").status, 200)  # still alive

    def test_undecodable_bytes_report_an_error_rather_than_crashing(self):
        self.session.questions_path(1).write_bytes(b"\xff\xfe{\x00")
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertIn("round-001.questions.json", payload["error"])

    def test_an_unreadable_round_file_reports_an_error(self):
        path = self.session.questions_path(1)
        write_json_atomic(path, VALID_ROUND)
        path.chmod(0o000)
        self.addCleanup(path.chmod, 0o644)
        try:
            path.read_text(encoding="utf-8")
        except PermissionError:
            pass
        else:
            self.skipTest("this user can read a mode-000 file; probably root")
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertIn("round-001.questions.json", payload["error"])

    def test_an_error_never_names_a_filesystem_path(self):
        """The file's name is useful; where the agent keeps its files is not,
        and the browser is not always the person who started the session."""
        self.session.questions_path(1).write_text("{not json", encoding="utf-8")
        payload = self.get_json("/api/round")
        self.assertNotIn(self._tmp.name, json.dumps(payload))

    def test_a_schema_invalid_round_reports_details(self):
        broken = {"round": 1, "questions": [{"id": "Q-1", "title": "x", "type": "dropdown"}]}
        write_json_atomic(self.session.questions_path(1), broken)
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertTrue(any("type must be one of" in d for d in payload["details"]))

    def test_a_schema_invalid_round_is_not_served_as_content(self):
        """The page must never render a round the validator rejected."""
        broken = {"round": 1, "questions": [{"id": "Q-1", "title": "x", "type": "dropdown"}]}
        write_json_atomic(self.session.questions_path(1), broken)
        self.assertIsNone(self.get_json("/api/round").get("round"))

    def test_a_round_that_is_not_an_object_is_rejected(self):
        write_json_atomic(self.session.questions_path(1), ["not", "a", "round"])
        payload = self.get_json("/api/round")
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["details"])


class BriefTest(ServerTestCase):
    def test_a_missing_brief_renders_empty(self):
        self.assertEqual(self.get_json("/api/brief")["html"], "")

    def test_the_brief_is_rendered_to_html(self):
        self.session.brief_path.write_text("# Vision\n\nA player.\n", encoding="utf-8")
        html = self.get_json("/api/brief")["html"]
        self.assertIn("<h1>Vision</h1>", html)
        self.assertIn("<p>A player.</p>", html)

    def test_the_brief_is_escaped_on_the_way_out(self):
        """Kills any mutant that hands the raw file to the page. CRAFT.md is
        written by an agent from the user's own words; it is not trusted HTML."""
        self.session.brief_path.write_text("<script>alert(1)</script>\n", encoding="utf-8")
        html = self.get_json("/api/brief")["html"]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_non_ascii_in_the_brief_survives(self):
        self.session.brief_path.write_text("café ☃\n", encoding="utf-8")
        self.assertIn("café ☃", self.get_json("/api/brief")["html"])

    def test_an_undecodable_brief_is_reported_not_a_crash(self):
        self.session.brief_path.write_bytes(b"# hi\n\xff\xfe\n")
        payload = self.get_json("/api/brief")
        self.assertEqual(payload["html"], "")
        self.assertIn("CRAFT.md", payload["error"])
        self.assertNotIn(self._tmp.name, json.dumps(payload))
        self.assertEqual(self.get("/").status, 200)  # still alive


class ReadOnlyTest(ServerTestCase):
    def snapshot(self):
        state = {}
        for path in sorted(Path(self._tmp.name).rglob("*")):
            state[str(path)] = path.stat().st_mtime_ns if path.is_file() else "dir"
            if path.is_file():
                state[str(path) + ":bytes"] = path.read_bytes()
        return state

    def test_serving_writes_nothing_at_all(self):
        """The agent owns every file in the project. The server reads."""
        self.session.brief_path.write_text("# Vision\n", encoding="utf-8")
        write_json_atomic(self.session.questions_path(1), VALID_ROUND)
        before = self.snapshot()
        for path in ("/", "/api/round", "/api/brief"):
            self.get(path).read()
        self.refused("/nope")
        self.refused("/", key=False)
        self.assertEqual(self.snapshot(), before)


class BindingTest(ServerTestCase):
    def test_the_default_bind_is_the_loopback_interface(self):
        """One line -- a host default of "" or "0.0.0.0" -- puts the brief and
        a key-bearing URL on every interface the machine has."""
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.server.socket.getsockname()[0], "127.0.0.1")

    def test_the_port_property_reports_the_bound_port(self):
        port = self.server.port
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        self.assertEqual(port, self.server.socket.getsockname()[1])

    def test_a_non_loopback_host_is_refused(self):
        for host in ("0.0.0.0", "", "192.168.1.10", "example.com"):
            with self.assertRaises(ValueError, msg=host):
                CraftServer(self.session, self.key, host=host, port=0)

    def test_a_refused_host_leaves_no_socket_listening(self):
        """The guard has to run before the bind, or the refusal still exposed
        the port for as long as the interpreter keeps the socket."""
        probe = socket.socket()
        probe.bind(("0.0.0.0", 0))
        port = probe.getsockname()[1]
        probe.close()
        with self.assertRaises(ValueError):
            CraftServer(self.session, self.key, host="0.0.0.0", port=port)
        again = socket.socket()
        try:
            again.bind(("0.0.0.0", port))  # free, so nothing was left listening
        finally:
            again.close()

    def test_the_ipv6_loopback_is_accepted_and_binds_ipv6(self):
        """The skip is decided by the machine, not by the code under test: a
        server that failed to select AF_INET6 would otherwise fail to bind ::1
        and be excused as "no IPv6 here"."""
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            probe.bind(("::1", 0))
        except OSError as exc:
            self.skipTest("no IPv6 loopback on this machine: {}".format(exc))
        finally:
            probe.close()
        server = CraftServer(self.session, self.key, host="::1", port=0)
        try:
            self.assertEqual(server.address_family, socket.AF_INET6)
            self.assertEqual(server.socket.getsockname()[0], "::1")
        finally:
            server.server_close()

    def test_localhost_is_accepted(self):
        server = CraftServer(self.session, self.key, host="localhost", port=0)
        try:
            self.assertTrue(server.port > 0)
        finally:
            server.server_close()


class IdleTest(ServerTestCase):
    def test_a_request_resets_the_idle_clock(self):
        self.server._last -= 100
        self.assertGreater(self.server.idle_seconds(), 50)
        self.get("/api/round").read()
        self.assertLess(self.server.idle_seconds(), 5)

    def test_touch_is_what_resets_it(self):
        self.server._last -= 100
        self.server.touch()
        self.assertLess(self.server.idle_seconds(), 1)

    def test_the_idle_timeout_is_four_hours_by_default(self):
        self.assertEqual(self.server.idle_timeout_s, 14400)
        other = CraftServer(self.session, self.key, port=0, idle_timeout_s=5)
        try:
            self.assertEqual(other.idle_timeout_s, 5)
        finally:
            other.server_close()


class KeyTest(unittest.TestCase):
    def test_a_key_is_long_and_hex(self):
        key = make_key()
        self.assertEqual(len(key), 64)
        int(key, 16)  # raises if it is not hex

    def test_two_keys_differ(self):
        self.assertNotEqual(make_key(), make_key())

    def test_the_cookie_name_is_stable(self):
        """Tasks 6 and 10 name this string too; changing it breaks them
        silently, because a missing cookie merely falls back to the URL."""
        self.assertEqual(COOKIE, "craftkey")


class ConcurrencyTest(ServerTestCase):
    def test_two_requests_at_once_are_both_served(self):
        """ThreadingHTTPServer, not HTTPServer: a poll in one tab must not
        block the other. Serialised handling would still pass every test
        above."""
        write_json_atomic(self.session.questions_path(1), VALID_ROUND)
        results = []
        barrier = threading.Barrier(3, timeout=5)

        def hit():
            try:
                barrier.wait()
                results.append(self.get_json("/api/round")["round"]["round"])
            except Exception as exc:  # recorded, not raised, off the main thread
                results.append(exc)

        threads = [threading.Thread(target=hit) for _ in range(2)]
        for thread in threads:
            thread.start()
        try:
            barrier.wait()
        finally:
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
        self.assertEqual(results, [1, 1])


if __name__ == "__main__":
    unittest.main()
