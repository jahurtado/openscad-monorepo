#!/usr/bin/env bash
# PreToolUse(Bash) guard — parametric OpenSCAD design repo.
# BLOCKS (permissionDecision=deny) the two shortcuts the workflow explicitly
# forbids (see openscad-skill-nudge.sh):
#   1. raw trimesh              -> use tools/check.py / analyze.py / slice.py
#   2. invoking the OpenSCAD binary by hand (CLI render/inspection)
#                               -> use tools/check.py / slice.py / build.py / make_assembly.py
# The LEGITIMATE `--openscad <path>` flag the tools accept is NOT blocked
# (it is stripped before searching for binary invocations).
# If no pattern matches: exit 0 with no output -> let the command through.
set -uo pipefail

# jq lives in different places (/usr/bin on recent macOS, /opt/homebrew/bin via
# Homebrew, /usr/bin or /run/current-system on Linux). Resolve it instead of
# hard-coding a path: with a hard-coded one that is missing, the guard would fail
# OPEN and silently stop guarding anything.
JQ="$(command -v jq || true)"
if [ -z "$JQ" ]; then
  printf 'openscad-guard: jq not found — the OpenSCAD guard is DISABLED\n' >&2
  exit 0
fi

input="$(cat)"
tool="$("$JQ" -r '.tool_name // empty' <<<"$input" 2>/dev/null || true)"
[ "$tool" = "Bash" ] || exit 0
cmd="$("$JQ" -r '.tool_input.command // empty' <<<"$input" 2>/dev/null || true)"
[ -n "$cmd" ] || exit 0

# Strip the legitimate `--openscad <path>` (or `--openscad=<path>`) flag before
# searching for the binary, so it is not mistaken for a manual invocation.
stripped="$(/usr/bin/sed -E 's/--openscad[= ]+[^ ]+//g' <<<"$cmd")"

deny() {
  "$JQ" -cn --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# 1. Raw trimesh: running python (one-liner -c or heredoc) that uses trimesh.
if grep -qE '\b(python3?|uv[[:space:]]+run[[:space:]]+python)\b' <<<"$stripped" \
   && grep -qE '\btrimesh\b' <<<"$stripped"; then
  deny "BLOCKED by the repo guard: raw trimesh. The OpenSCAD workflow forbids improvising with trimesh — there is already a tool for this: tools/check.py gives Status/Genus/watertight/volume/bbox for a piece (and --parts for clash/clearance), tools/analyze.py reconstructs 3D features, tools/slice.py sections. Rewrite using the tool. (If you truly need raw trimesh, ask the user to relax/remove the guard in .claude/hooks/openscad-guard.sh.)"
fi

# 2. OpenSCAD binary by hand: executable path, `openscad` in command position,
#    or an $OSCAD/$OPENSCAD var holding it. The executable must be FOLLOWED by
#    whitespace/end (args) — so "openscad" as a path fragment does NOT match
#    (e.g. a repo path like .../my-openscad-parts/...), which used to be a false positive.
if grep -qE '/OpenSCAD\.app/Contents/MacOS/OpenSCAD|(^|[;&|(]|&&|\|\||\bdo\b|\bthen\b)[[:space:]]*"?([^[:space:]"'\'']*/)?(openscad|OpenSCAD)([[:space:]]|$)|\$\{?(OSCAD|OPENSCAD)\b' <<<"$stripped"; then
  deny "BLOCKED by the repo guard: direct invocation of the OpenSCAD binary. The workflow forbids the manual OpenSCAD CLI — use the tool: tools/check.py (render→STL + manifold/volume/bbox), tools/slice.py (2D sections + iso preview of WHERE it cuts), tools/build.py (final STLs), tools/make_assembly.py (assembly of loose STLs). The --openscad <path> flag inside a 'uv run tools/...' IS allowed. Rewrite using the tool."
fi

exit 0
