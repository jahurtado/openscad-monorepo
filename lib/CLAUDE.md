# lib/ — rules for modifying the primitives

These files are **reusable primitives** imported with `use <...>` by both project pieces (`projects/<x>/modules/`) and components (`components/`). A change here propagates to everything that uses them, so modifications are held to a higher bar than ordinary design code. Read this before touching anything in `lib/`.

> **One primitive is here as the worked example** (`rounded.scad`), plus the cut-plane viewer that every front door imports. This layer is meant to grow — arcs, buttons, screw cutters, whatever your parts keep asking for.

## 1. Backward compatibility

Follow the **compatibility rule** in [`../docs/design-rules.md`](../docs/design-rules.md) — a change here
propagates to everything that imports the primitive. What's specific to OpenSCAD/`lib/`:

- **OpenSCAD has NO overloading.** Two modules with the same name don't coexist: the last definition shadows the earlier one (verified: `foo(a)` + `foo(a,b)` → both calls go to the second). You can't keep two signatures under one name.
- The **shim** is `<name>_legacy` marked `// DEPRECATED`, implemented as a thin translation to the new module (not a copy of the old body, unless the new one can't reproduce it). Verify it yields identical geometry.
- **Break clean** (no shim) only if `grep -rn "<name>" . --include=*.scad` confirms **zero call sites**. When in doubt, shim.

## 2. Validate before/after every change

Geometry must be identical except for the intended change. Render the old and new versions of the same
case with **`check.py`** and compare the **volume + bbox** it reports (never the `openscad` binary by
hand — the guard blocks it; everything goes through the tools):

```
uv run tools/check.py old_case.scad --module <case> --fn 96   # note volume + bbox
uv run tools/check.py new_case.scad --module <case> --fn 96   # dV ≈ 0, d(bbox) ≈ 0
```

To compare per detector (outline, holes…) use `compare.py`. Cover the edge cases of the signature
(each extreme, radius 0, overrides). For a refactor, "same geometry down to the cubic millimeter" is
the acceptance criterion.

## 3. Conventions these files already follow

Keep them when editing or adding a new file:

- **Self-preview**: each file ends with a top-level block that renders a representative module (opening the file in OpenSCAD shows geometry). If you add a relevant public module, add it to the demo.
- **Never `include <...>` these files** — only `use <...>`. `include` executes the top-level and would leak the self-preview into the importer.
- **Don't set `$fn`/`$fa`/`$fs` at file level** — they're inherited from the importer. If a module needs explicit facet control, expose a `fn = $fn` parameter and pass it as `$fn=fn` at the call site. The self-preview block may set a local `$fn` (the `use` ignores it).
- **`undef` sentinel = "inherit the default"** for optional overrides, **never `0`** (which is a legitimate value: zero radius = sharp edge). Pattern: one shared default + per-element overrides (e.g. `r` + `tr`/`br`, `bevel` + `bevel_top`/`bevel_bottom`).
- **Prefer a single 2D/convex op over stacked 3D booleans** where possible (`offset`+`linear_extrude`, `hull` of convexes, `rotate_extrude` of a profile) — but **measure**: on the Manifold backend it doesn't always speed things up. Clarity already justifies the pattern; don't claim a speedup you didn't measure.

## 4. The catalogue is the files themselves

**Do not hand-roll** what already exists. Before writing a primitive: `ls lib/` and read the
**header** of whichever file fits — each one documents its API, its parameters and the reasoning
behind its choices right there. That header is the single source.

No catalogue table is kept here, **deliberately**: the layer is meant to grow, and any list written
somewhere else drifts from the code the moment you add, rename or extend a primitive.

One exception worth knowing: `cut_plane_viewer.scad` is **not a geometric primitive** but a GUI
inspection aid. It lives in `lib/` because it is reusable `.scad`, and the `main.scad` front doors
import it in their `[Inspect cut plane]` block — there it is a contract, not a catalogue entry.
