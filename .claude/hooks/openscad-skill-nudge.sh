#!/usr/bin/env bash
# UserPromptSubmit nudge — parametric OpenSCAD design repo.
# If the user's prompt mentions design/STL/OpenSCAD work, inject a reminder to
# invoke the applicable design skill (openscad-design-from-specs /
# openscad-design-from-stl) and follow its numbered flow instead of improvising
# (trimesh / OpenSCAD CLI). It is a NUDGE: it only injects context, never blocks
# (always exit 0).
set -euo pipefail

# Same jq resolution as the guard: no hard-coded path.
JQ="$(command -v jq || true)"
[ -n "$JQ" ] || exit 0

input="$(cat)"
prompt="$(printf '%s' "$input" | "$JQ" -r '.prompt // .user_prompt // empty' 2>/dev/null || true)"

# Keywords (case-insensitive) that give away a design task in this repo.
if printf '%s' "$prompt" | grep -qiE 'stl|openscad|param[eé]tric|dise[nñ]|design|pieza|componente|component|malla|mesh|modules/|components/'; then
  "$JQ" -cn '{
    hookSpecificOutput: {
      hookEventName: "UserPromptSubmit",
      additionalContext: (
        "[Repo reminder] This looks like an OpenSCAD design task. " +
        "Invoke the applicable design skill — `openscad-design-from-specs` (from measurements) or `openscad-design-from-stl` (from a mesh) — and follow ITS numbered flow BEFORE using tools; " +
        "do not reproduce the procedure here (the skill is the single source of truth, and the acceptance criterion depends on the goal you set in its Step 0). " +
        "Do not improvise with trimesh or the OpenSCAD binary by hand: a guard blocks them, and the tools already provide watertight/volume/bbox, the assembly and the sections."
      )
    }
  }'
fi
exit 0
