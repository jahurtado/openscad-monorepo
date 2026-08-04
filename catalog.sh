#!/usr/bin/env bash
# catalog.sh — start the parts gallery and open it in the default browser.
#
#   ./catalog.sh            # serve on http://127.0.0.1:8000 and open the browser
#   ./catalog.sh 9000       # another port
#
# If a server is already serving on that port, it does NOT start another: it just
# opens a new browser tab (if the browser is already open, it reuses the window).
# Works on macOS and on Windows (run it from Git Bash / MSYS2). Ctrl-C to stop.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
port="${1:-8000}"
url="http://127.0.0.1:${port}/"

# Runs tools/gallery.py with the repo's environment (same approach as build.sh):
# venv already set up -> fast path; otherwise uv syncs and runs. Uses exec so the
# background PID is the server's (so Ctrl-C / the trap kill it).
run_gallery() {
  if [ -x "$here/.venv/bin/python" ]; then
    exec "$here/.venv/bin/python" "$here/tools/gallery.py" "$@"          # macOS/Linux
  elif [ -x "$here/.venv/Scripts/python.exe" ]; then
    exec "$here/.venv/Scripts/python.exe" "$here/tools/gallery.py" "$@"  # Windows
  elif command -v uv >/dev/null 2>&1; then
    exec uv run --project "$here" "$here/tools/gallery.py" "$@"
  else
    echo "no environment found; install uv and run 'uv sync' (see README.md, Prerequisites)" >&2
    exit 1
  fi
}

# Opens a URL in the system's default browser (new tab if it's already open).
open_url() {
  case "$(uname -s)" in
    Darwin) open "$1" ;;                                    # macOS
    MINGW*|MSYS*|CYGWIN*)                                    # Windows (Git Bash / MSYS2 / Cygwin)
      powershell.exe -NoProfile -Command "Start-Process '$1'" 2>/dev/null \
        || cmd //c start "" "$1" ;;
    Linux)
      if grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null; then     # WSL -> Windows browser
        cmd.exe /c start "" "$1" 2>/dev/null || powershell.exe -NoProfile -Command "Start-Process '$1'"
      else xdg-open "$1"; fi ;;
    *) python3 -c 'import webbrowser,sys; webbrowser.open(sys.argv[1])' "$1" ;;
  esac
}

# Server already on that port? -> just open a tab and leave.
if command -v curl >/dev/null 2>&1 && curl -fsS -m 2 "${url}catalog" >/dev/null 2>&1; then
  echo "gallery already serving on ${url} — opening a tab"
  open_url "$url"
  exit 0
fi

# Start the server in the background and schedule it to die on exit.
echo "starting the gallery on ${url}  (Ctrl-C to stop)"
run_gallery --port "$port" &
srv=$!
trap 'kill "$srv" 2>/dev/null || true' EXIT INT TERM

# Wait for the server to respond, then open the browser.
if command -v curl >/dev/null 2>&1; then
  for ((i = 0; i < 40; i++)); do
    curl -fsS -m 1 "${url}catalog" >/dev/null 2>&1 && break
    sleep 0.25
  done
else
  sleep 2
fi
open_url "$url"

# Keep the server in the foreground (Ctrl-C stops it via the trap).
wait "$srv" || true
