# projects/ — one directory per design

Each subfolder of `projects/` is an independent **project**: a part or set of
printable parts designed together. Projects import code from `lib/` and
components from `components/` with **relative paths** — and **never** depend on
another project (dependency direction).

A project may have its own **project-specific components** (private models in `modules/`,
not yet reused by anyone else). If a 2nd project needs one, it's **promoted** to
`components/` (mandatory, no cross-referencing between projects). In addition, every catalog
component has its **bench project** here (hosting its drawings/doc/test; see
[`../docs/components.md`](../docs/components.md)) — a convention this monorepo template does not yet
demonstrate: it ships `projects/example/`, which *consumes* `components/pcb_holder` but is not its bench.

## Project layout (Option A: `main.scad` + `modules/`)

The **folder tree, relative imports and dependency direction** are **repo architecture** (not
repeated here). This document owns the **operational detail of the front door** and the
**per-project templates**.

> **Per-project `docs/` vs root `docs/`.** The repo's root `docs/` is the **repo-wide
> reference** (glossary, monorepo, components…). Each project's `docs/` is the
> **design doc for THAT part** (narrative: what it is, decisions and rationale, mechanics). Don't
> conflate them: different level, different scope.

### Front door (`main.scad`)

- **`main.scad` = single entry point.** A **catalog of CLEAN-named modules**
  (no project tag) that re-export the private geometry in `modules/`. The
  piece is selected by its name. The **tools discover pieces by regex over these names**
  — respect them:
  - `module <piece>_print()` — printable deliverable, already oriented to the slicer's bed; discovered
    by `build.py` (emits one STL each).
  - `module <piece>_solid()` — assembly/inspection solid; discovered by `slice`/`run_batch`
    (without `--parts`).
  - `assembly` / `full_assembly` / views — plainly named compositions.

  The real geometry lives in `modules/`; `main.scad` only forwards and composes.
- **Default view + cut inspection:** the final top-level call is
  `cut_plane_view(CUT_AXIS, CUT_POS, SHOW) <showcase>();` (with `use <../../lib/cut_plane_viewer.scad>`
  and a Customizer block `/* [Inspect cut plane] */`). With `SHOW="off"` (default) it's the clean
  showcase; in the Customizer you sweep a cut plane (`plane`/`cut`/`slice`) — the explorer is built
  into `main.scad`. `use <main>` ignores the top-level (the call + `CUT_*` variables), so it's
  invisible to the tools. If the showcase uses `%` ghosts, wrap an all-solid module.
- Each `<piece>_print()` carries its **print orientation** (its rotation/flip).
- **`modules/*.scad` are pieces, not front doors**: they do NOT set `$fn` (they inherit it from
  `main.scad`, which sets the baseline `$fn`).
- **Self-preview**: every `modules/<piece>.scad` ends with a top-level block that renders a
  representative module (opening the file on its own in OpenSCAD shows geometry, not an empty
  canvas; the local `$fn` goes in that block, since outside `main.scad` it is not inherited). The
  front door ignores it — `use <modules/…>` does not execute the top-level; **never** `include` a
  piece. It is the same convention as in `lib/` ([`../lib/CLAUDE.md`](../lib/CLAUDE.md)). The
  `<x>_config.scad` does **not** carry a self-preview (it is `include`d, has no geometry, and would
  leak into all its importers).
- **Recommendation — measurements as functions.** The important dims/positions/anchors that live
  in `modules/` are best exposed as **functions** (`function pb_hh() = …;`), not top-level
  variables: `use` only imports modules and functions, so a measurement stays readable from another
  file.

**Building deliverables:** `./build.sh <project>` (wrapper around `tools/build.py`) → one STL per
`*_print` in `projects/<x>/prints/`; `--inspect` also regenerates the `main.batch` sections. See
[`../docs/tools-guide.md`](../docs/tools-guide.md).

## Design doc — `docs/design.md` (MANDATORY, one per project)

Every project carries a **narrative design doc** in `docs/design.md`. It's for a human who
opens the project and wants to understand **what the part is and why it's designed that way**,
without reading the code. It does **not** duplicate the `CLAUDE.md` (which is terse context for
Claude) or the `drawings/` (which are dimensions): the `CLAUDE.md` links to `docs/design.md` and
stays short.

Structure (omit the section that doesn't apply; don't invent — mark anything unconfirmed):

```markdown
# <Project> — Design documentation

## What it is and purpose
<The part, what it's for, what it mates with.>

## Requirements and constraints
<Starting measurements, materials, print/assembly constraints, what's NOT addressed.>

## Design decisions
<Each non-trivial decision with its WHY and the discarded alternatives. This is the section that
pays off most over time: it keeps you from re-litigating what's already decided.>

## Mechanics / how it works
<How it fits/retains/articulates; the coordinate frame; component reuse and their
transformations (e.g. "sensor_board rotated −90° about X").>

## Key parameters
<The `<X>_config.scad` it imports and their effect; what to touch to adapt the part.>

## Printing
<Print orientation of each piece (`<piece>_print`), supports/overhangs, slicer settings if any.>

## Status and evolution
<What's validated (test print) vs pending; which iterations happened and what was learned.>
```

Keep it alive: when a design decision changes or an iteration reveals something, **update
`docs/design.md`** (just as the dimension drawing is regenerated). Link to `drawings/` and the
`CLAUDE.md` where it applies.

## Template for `projects/<x>/CLAUDE.md`

```markdown
# <Project> — CLAUDE.md

## Project

<What part(s) are designed, what they mate with, where the reference meshes come
from.> Full design doc: [`docs/design.md`](docs/design.md).

## Layout / pieces

Single front door: `main.scad` (module catalog: `<piece>_print` printables,
`<piece>_solid` for inspection, `assembly`). Geometry in `modules/`:
- `modules/<piece>.scad` — <what it emits>.
- `modules/<x>_config.scad` — project constants.
```
