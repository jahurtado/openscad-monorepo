#!/usr/bin/env bash
# docs.sh — serve (or build) the documentation site from docs/.
#
#   ./docs.sh              # serve on http://127.0.0.1:8000 and open the browser
#   ./docs.sh --no-open    # serve without opening a browser
#   ./docs.sh --port 8100  # another port (any mkdocs serve flag passes through)
#   ./docs.sh build        # write the static site to site/ instead of serving
#
# The site is MkDocs Material, and it lives in its OWN uv project under
# resources/mkdocs/ — it needs neither OpenSCAD nor trimesh, so it is kept apart
# from the modeling tools in the root pyproject. mkdocs.yml (at the repo root)
# points at docs/.
#
# Ctrl-C to stop.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; install it (https://docs.astral.sh/uv/) — the docs site needs it" >&2
  exit 1
fi

# `build` as the first word switches from serving to writing site/.
cmd="serve"
if [ "${1:-}" = "build" ]; then
  cmd="build"
  shift
fi

# Serving opens a browser, like catalog.sh does. mkdocs has that built in (-o), and it
# waits for the first build before opening. `--no-open` opts out; an explicit -o/--open
# is respected as-is so we never pass it twice.
args=()
open_flag=()
if [ "$cmd" = "serve" ]; then
  want_open=1
  for a in "$@"; do
    case "$a" in
      --no-open) want_open=0 ;;          # consumed here: mkdocs has no such flag
      -o|--open) want_open=0; args+=("$a") ;;   # already asked for it
      *) args+=("$a") ;;
    esac
  done
  [ "$want_open" -eq 1 ] && open_flag=(--open)
else
  args=("$@")
fi

# -f pins the config at the repo root, so the site is identical wherever you run this from.
# The `${arr[@]+…}` guard keeps `set -u` happy with an EMPTY array on bash 3.2,
# which is what macOS still ships.
exec uv run --project "$here/resources/mkdocs" mkdocs "$cmd" -f "$here/mkdocs.yml" \
     ${open_flag[@]+"${open_flag[@]}"} ${args[@]+"${args[@]}"}
