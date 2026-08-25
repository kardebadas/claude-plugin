import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import session
from session import ROUND_RE, Session, read_json, write_json_atomic


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

    A read_text() that forgot to name its encoding is invisible here, because
    this machine's locale is UTF-8 -- and setting LC_ALL=C does not expose it
    either, since CPython auto-enables UTF-8 mode under the C locale. Both are
    accidents of where the suite runs; a Windows cp1252 box, or any non-UTF-8
    locale Python does not coerce, would decode the same bytes differently.
    Substituting the fallback pins the contract wherever the suite runs.
    """
    real_read_text = Path.read_text

    def read_text(self, encoding=None, *args, **kwargs):
        return real_read_text(self, encoding or "latin-1", *args, **kwargs)

    with mock.patch.object(Path, "read_text", read_text):
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
        self._round(1)
        leftovers = [p.name for p in self.s.craft_dir.iterdir() if p.name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

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
        leftovers = [p.name for p in self.s.craft_dir.iterdir() if p.name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

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


if __name__ == "__main__":
    unittest.main()
