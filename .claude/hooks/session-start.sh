#!/bin/bash
# Prepare a Claude Code on the web session and hand it a known-good baseline.
#
# There is nothing to install: docs/node_modules is vendored and committed, and
# the engine and its tests are pure stdlib Python. So this verifies the
# toolchain is actually present, confirms the vendored dependency survived the
# checkout, and runs the part of the suite that does not need Archipelago --
# about four seconds all told, which is cheap enough to buy a session that
# starts out knowing whether the tree is green.
#
# It never fails the session. A red check is information the session needs at
# its start, not a reason to refuse to open, so failures are reported loudly and
# the hook still exits 0.
#
# Local sessions are skipped deliberately. The checks below assume a POSIX shell
# and a `python3`, and the development machine for this project is Windows,
# where the hook would only ever report false failures.

set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0

failures=()

have() { command -v "$1" >/dev/null 2>&1; }

# Windows calls it `python`, Debian calls it `python3`, and this has to work
# whichever one the image ships.
if have python3; then
  PY=python3
elif have python; then
  PY=python
else
  PY=""
  failures+=("python is not on PATH -- every check below needs it")
fi

if ! have node; then
  failures+=("node is not on PATH -- the browser suite cannot run")
fi

# archipelago.js is vendored rather than pulled from a CDN, so the browser
# client gains no runtime dependency on anyone else's uptime. It is also what
# Jekyll's default excludes would drop on Pages, which is why docs/.nojekyll
# exists -- if the tree arrived without it, say so here rather than letting an
# import failure explain it later.
if [ ! -f docs/node_modules/archipelago.js/dist/index.js ]; then
  failures+=("vendored archipelago.js is missing from docs/node_modules")
fi
if [ ! -f docs/.nojekyll ]; then
  failures+=("docs/.nojekyll is missing -- Pages would drop the vendored client")
fi

run() {
  local label="$1"
  shift
  local output
  if output=$("$@" 2>&1); then
    printf '  ok    %s\n' "$label"
  else
    printf '  FAIL  %s\n' "$label"
    printf '%s\n' "$output" | tail -15 | sed 's/^/          /'
    failures+=("$label")
  fi
}

echo "AP_10 -- checking the tree"

if have node; then
  run "browser suite and the shared item tables (npm test)" npm test --silent
fi

if [ -n "$PY" ]; then
  run "phase solver (tests/test_phases.py)"      "$PY" tests/test_phases.py
  run "hand loop and table (tests/test_game.py)" "$PY" tests/test_game.py
  run "module URL stamps are current"            "$PY" tools/stamp_build.py --check
  run "README rules match the engine"            "$PY" tools/check_rules_doc.py
  run "table of contents is current"             "$PY" tools/update_toc.py --check
fi

echo
echo "Not runnable here, and not a failure: the 73 apworld tests in"
echo "phase10/test/, tools/check_store_balance.py and tools/check_multiworld.py"
echo "all need an Archipelago source checkout (set AP_ROOT), and tests/ui_check.py"
echo "needs Kivy and a display. See CLAUDE.md."

if [ ${#failures[@]} -gt 0 ]; then
  echo
  echo "${#failures[@]} check(s) failed before any edit was made, so the tree"
  echo "arrived this way. Treat it as pre-existing unless you can show otherwise:"
  for f in "${failures[@]}"; do
    echo "  - $f"
  done
fi

exit 0
