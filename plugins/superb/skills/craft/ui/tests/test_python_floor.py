"""An executable gate for this project's Python 3.9 floor.

The floor is declared, but no 3.9 interpreter exists on the machines this
suite runs on, so for four review rounds "3.9-compatible" was asserted from
reading and never executed. ast.parse(source, feature_version=(3, 9)) closes
that hole from a newer interpreter: it refuses grammar that 3.9 did not have
(`match`, `except*`) while accepting grammar it did (the walrus operator,
`dict | dict` at runtime).

The limitation, plainly: this checks SYNTAX ONLY. It cannot see a call to a
standard-library API added after 3.9 -- str.removeprefix, tomllib,
dict.__or__ on a 3.8 dict, functools.cache, anything of that shape parses
happily at feature_version=(3, 9) and then fails at import time on a real 3.9.
This is a real gate against the most common way the floor gets broken. It is
not a proof of 3.9 compatibility, and it does not replace running the suite on
a real 3.9 interpreter should one ever be available.
"""
import ast
import unittest
from pathlib import Path

FLOOR = (3, 9)

# The UI package root: this file is <ui>/tests/test_python_floor.py. Derived
# from __file__ rather than the working directory, because the runner may be
# invoked from anywhere.
UI_DIR = Path(__file__).resolve().parent.parent


def _ui_sources():
    """Every .py file under the UI package, tests and __init__.py included."""
    return sorted(UI_DIR.rglob("*.py"))


class PythonFloorTest(unittest.TestCase):
    def test_every_ui_source_file_parses_at_the_floor(self):
        """The gate itself. One unparseable file names itself and the rest of
        the tree is still checked."""
        for path in _ui_sources():
            rel = path.relative_to(UI_DIR)
            with self.subTest(source=str(rel)):
                source = path.read_text(encoding="utf-8")
                try:
                    ast.parse(source, filename=str(path), feature_version=FLOOR)
                except SyntaxError as exc:
                    self.fail(
                        "{} is not valid Python {}.{} syntax: {}".format(
                            rel, FLOOR[0], FLOOR[1], exc
                        )
                    )

    def test_the_glob_actually_found_the_sources(self):
        """A gate that silently checks nothing because a path was wrong is
        worse than no gate at all."""
        found = _ui_sources()
        self.assertGreaterEqual(
            len(found),
            3,
            "only found {} .py file(s) under {} -- the glob is wrong".format(
                len(found), UI_DIR
            ),
        )
        names = [p.name for p in found]
        self.assertIn("session.py", names)
        self.assertIn("test_python_floor.py", names)

    def test_the_floor_rejects_grammar_newer_than_it(self):
        """Proves the gate has teeth. Were feature_version ever ignored or
        removed, every other assertion here would go green and useless, so
        this test fails loudly instead."""
        match_source = (
            "def f(x):\n"
            "    match x:\n"
            "        case 1:\n"
            "            return 'one'\n"
            "        case _:\n"
            "            return 'other'\n"
        )
        # Sanity: it is valid on the interpreter running this suite, so the
        # rejection below can only come from feature_version.
        ast.parse(match_source)
        with self.assertRaises(SyntaxError):
            ast.parse(match_source, feature_version=FLOOR)

    def test_the_floor_accepts_grammar_that_3_9_had(self):
        """The other half of the teeth: the gate must not simply reject
        everything. An equivalent 3.9-legal snippet parses."""
        legal_source = (
            "def f(x):\n"
            "    if x == 1:\n"
            "        return 'one'\n"
            "    return 'other'\n"
        )
        ast.parse(legal_source, feature_version=FLOOR)
        # Grammar 3.9 does have, and which a naive floor check might reject.
        ast.parse("if (n := 1) > 0:\n    pass\n", feature_version=FLOOR)
        ast.parse("from __future__ import annotations\n", feature_version=FLOOR)


if __name__ == "__main__":
    unittest.main()
