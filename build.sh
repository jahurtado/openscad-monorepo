#!/usr/bin/env bash
# build.sh — the simplest shortcut to build a project's STLs.
#
#   ./build.sh <project> [pieces...]     e.g.  ./build.sh example
#   ./build.sh example base_print lid_print   # one STL per named piece
#   ./build.sh example --all             # one STL per *_print module
#   ./build.sh example --inspect         # build + regenerate the main.batch sections
#   ./build.sh example --list            # list the project's *_print modules
#   ./build.sh --all-projects            # one STL per piece, in every project (CI)
#
# Thin wrapper over tools/build.py that AUTOMATICALLY uses the repo's venv
# (on macOS there is no bare `python`). All arguments pass through as-is.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$here/.venv/bin/python" ]; then
  exec "$here/.venv/bin/python" "$here/tools/build.py" "$@"   # venv already set up: fast path
elif command -v uv >/dev/null 2>&1; then
  exec uv run --project "$here" "$here/tools/build.py" "$@"   # uv syncs the .venv and runs
else
  echo "environment not found; install uv and run 'uv sync' (see README.md, Prerequisites)"; exit 1
fi
