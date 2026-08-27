#!/usr/bin/env bash
# Runs the whole craft UI suite. Every task must leave this green.
#
# Two layers, in this order. The unit and integration tests come first
# because they say WHICH part broke; the smoke test comes last because it
# says whether the thing works at all, which is only worth asking once the
# parts have answered for themselves.
set -euo pipefail
UI_DIR="$(cd "$(dirname "$0")/../plugins/superb/skills/craft/ui" && pwd)"
cd "$UI_DIR"
python3 -m unittest discover -s tests -t . "$@"
echo
"$UI_DIR/tests/smoke.sh"
