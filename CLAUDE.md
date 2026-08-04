# CLAUDE.md

> **OpenSCAD monorepo template** for designing parametric, 3D-printed parts, driven by Claude
> Code. This file describes **what the repo is, what it contains, and how it's organized** — the
> architecture and conventions. The **how you actually work** (the design loop, the tools) lives in
> the skills and [`docs/tools-guide.md`](docs/tools-guide.md); to start a design, invoke
> whichever skill applies: `openscad-design-from-specs` (from measurements) or
> `openscad-design-from-stl` (from a mesh).

## Documentation map — who owns what

Each fact is **defined in exactly one place**; everything else links to it. Before explaining
something in depth here, check whether its owner already covers it:

| Topic | Owner (single source of truth) |
|---|---|
| Front door (`main.scad`), `_print`/`_solid` naming, `$fn` baseline | [`projects/CLAUDE.md`](projects/CLAUDE.md) |
| Component catalog (promotion, backward compatibility) | [`components/CLAUDE.md`](components/CLAUDE.md) |
| Reusable primitives (catalog, rules for touching them) | [`lib/CLAUDE.md`](lib/CLAUDE.md) |
| Modeling an external component (model roles, origin, template) | [`docs/components.md`](docs/components.md) |
| Construction idioms/rules (faceted trace, silhouette→DXF, coplanar, DXF protocol, `LINT-OK`, `assert` in `use`d files) + **the print bed** | [`docs/design-rules.md`](docs/design-rules.md) |
| Measurement dialogue + test pieces (the process) | skill `openscad-design-from-specs` |
| Using the tools (setup, examples, the design loop) | [`docs/tools-guide.md`](docs/tools-guide.md) |
| Definition of a CAD/OpenSCAD/FDM term | [`docs/concepts.md`](docs/concepts.md) (glossary) |
| Full index of `docs/` | [`docs/README.md`](docs/README.md) |

## Interacting with the user

- Reply in the user's language.
- **Documentation language**: prose in the `.md` files is written for an English-speaking reader;
  use the standard English CAD/OpenSCAD/FDM/electronics terms directly. In
  [`docs/concepts.md`](docs/concepts.md) (the glossary) the English term is the primary entry.
- **Correct imprecise terminology inline** when it introduces a risk of misunderstanding the
  geometry or the process (not out of pedantry). Critical case: **"round it off / take the edge off"
  is AMBIGUOUS** between *fillet* (concave radius), *round* (radius on a convex edge), and *chamfer*
  (a flat angled cut) — **ask which one** and request the radius, or the width and angle; don't
  assume 45°. Definitions in `docs/concepts.md §3`.

## Architecture — the three layers

```
projects/  ──►  components/  ──►  lib/
 (leaves)        (catalog)        (primitives)
    └───────────────────────────────►┘   (a project can pull from lib/ directly)
```

- **`lib/`** — **general** parametric primitives, with no physical artifact behind them
  (`rounded_cube`, `rounded_cylinder`…). Pure code, infinitely reusable; no `resources`/`test`/
  `drawings`. See [`lib/CLAUDE.md`](lib/CLAUDE.md).
- **`components/`** — the **catalog**: models of **concrete physical parts** that are reusable
  (measured from the real world, or designed companions that mate with one). Holds **only the
  importable `.scad`** (the single source); the scaffolding lives in its bench project. See
  [`components/CLAUDE.md`](components/CLAUDE.md).
- **`projects/<x>/`** — **leaf** designs: the product you actually print. They consume `components/`
  and `lib/`. See [`projects/CLAUDE.md`](projects/CLAUDE.md).

**The `lib` vs `components` axis:** the test is **"general primitive vs concrete physical part,"**
not "invented vs measured." `rounded_cube` → `lib/`; a lid for *this specific* PCB → `components/`,
even if nothing gets measured.

### Direction of dependencies (the golden rule)

Dependencies **only flow downward**; nothing ever depends on a project.

- **Allowed:** `projects → components`, `projects → lib`, `components → lib`, and `modules → modules`
  (a sibling in the same project).
- **Forbidden:** `lib → components/projects`, `components → projects`, `projects → projects` (another
  project).

### Where each thing lives

| What it is | Where | Contract |
|---|---|---|
| **General** parametric primitive (`rounded_cube`, `rounded_cylinder`) | `lib/` | backward compatible (it's an API) |
| **Reusable** physical part, or a **companion** that mates with one | `components/` | backward compatible (it's an API) |
| Project-**private** physical model (one-off, rare) | `projects/<x>/modules/` | none |
| Project **design** geometry (case, lid, front panel) | `projects/<x>/modules/` | none |

**When in doubt:** *"would another design plausibly run into this same physical object?"* → yes =
`components/`; no = `modules/`. A private model lives in `modules/` (it gets no folder of its own) and
in practice is rare: it gets promoted as soon as a 2nd project needs it.

### Promotion (`modules/` → `components/`)

A **2nd project** needing a private model **forces** you to promote it — you don't cross-reference
between projects. **Precondition:** the `.scad` to be promoted may only depend on `lib/` (a component
doesn't depend on other modules or components); if it drags in deps to sibling modules, resolve those
first. Procedure: create a **bench project** `projects/<name>/` for its scaffolding (test, drawings,
provenance), `git mv` **only the `.scad`** to `components/`, rewrite the imports (the depth changes),
and apply **backward compatibility** ([`docs/design-rules.md`](docs/design-rules.md)).

## Layout

```
<repo>/
├── CLAUDE.md  README.md
├── docs/         # repo-wide reference (concepts, components, design-rules, tools-guide, README)
├── tools/        # Python tooling + .scad helpers
├── lib/          # general primitives (+ lib/CLAUDE.md)
├── components/   # catalog: ONLY the importable .scad files (+ components/CLAUDE.md)
└── projects/<x>/ # one design (below)
```

```
projects/<x>/
├── CLAUDE.md      # project context
├── main.scad      # the SINGLE front door (operational detail → projects/CLAUDE.md)
├── main.batch     # iteration slice-set
├── modules/       # ALL local .scad: parts + (rarely) private models + <x>_config.scad
├── test/  drawings/  resources/   # test pieces · dimensioned drawings · raw input (never imported)
└── build/         # render outputs (gitignored)
```

### Imports = relative paths (no symlinks, no `OPENSCADPATH`)

By the location of the importing file:

- **`modules/<piece>.scad`** → `use <../../../lib/...>` · `use <../../../components/...>` ·
  `include <<x>_config.scad>` · sibling `use <other.scad>`.
- **`main.scad`** → `use <modules/<piece>.scad>`.
- **`components/<name>.scad`** → `use <../lib/...>` (the only allowed dependency).
- **bench project / test** (`projects/<x>/test/`) → `use <../../../components/<name>.scad>` · `use <../modules/<piece>.scad>`.

No `.scad` ever imports from `resources/`.

> **Photos in `resources/`: strip the EXIF BEFORE committing.** Reference photos come out of a
> phone/camera with **GPS in the EXIF**, and if the repo is shared or public that leak is real, not
> theoretical. Strip at the JPEG-marker level (drop the `APP1` segments: Exif **and** XMP) instead
> of re-saving with PIL: it is lossless, the pixels stay byte-identical, and any tracing script
> that depends on them keeps reproducing the same numbers.

## Design conventions

- **Front-door naming:** `module <part>_print()` = the bed-oriented deliverable;
  `module <part>_solid()` = the inspection/assembly solid. Respect those names. (Owner:
  [`projects/CLAUDE.md`](projects/CLAUDE.md).)
- **`$fn` only in the front door** (a baseline, e.g. `180`); `lib/`, `components/` and the parts
  **never** set it (they inherit it); a call site that needs an exact count passes `$fn=N` right
  there.
- **MEASURED vs ADJUST:** every constant that carries a position is annotated `// MEASURED:`
  (verified) or `// ADJUST:` (an estimate), and when the real measurement arrives it gets flipped in
  place **without ever deleting the trail**. (Full rule:
  [`docs/design-rules.md`](docs/design-rules.md); procedure: skill `openscad-design-from-specs`.)
- **Outputs inside the project, never global:** ephemeral renders (PNGs, temporary STLs) →
  `projects/<x>/build/`; final STLs → `projects/<x>/prints/`. Both gitignored.

## How you work

The **design loop and its tools** are carried by the skills (`openscad-design-from-specs` /
`openscad-design-from-stl`) and [`docs/tools-guide.md`](docs/tools-guide.md); invoke them
instead of improvising. Two hooks reinforce it: a `PreToolUse` guard (`openscad-guard.sh`)
**blocks** calling trimesh and the OpenSCAD binary by hand — everything goes through the tools
(`uv run tools/...`) — and a `UserPromptSubmit` nudge (`openscad-skill-nudge.sh`) reminds you to
invoke the applicable skill when the prompt smells like a design task. Two fresh-context subagents
support the flow: **`stl-analyzer`** (mesh perception when starting an STL→parametric job) and
**`design-conventions-reviewer`** (adversarial judge of the method). The **browsable catalog** of
projects is served with `./catalog.sh` (→ `tools/gallery.py`; see the
[guide](docs/tools-guide.md#gallerypy--catalogsh)).

## Lessons learned — where to capture each one

When an iteration reveals something reusable, capture it in its place and cross-link:
- **Definition of a term** → `docs/concepts.md` (glossary).
- **Reusable geometry pattern / lesson** → next to its code in `lib/` (header or `lib/CLAUDE.md`).
- **Workflow anti-pattern / gotcha** → whichever design skill applies
  (`openscad-design-from-specs` / `openscad-design-from-stl`).

Trigger: after resolving a subtle error (manifold, alignments, geometry that fails) or consolidating
an approach that worked after several iterations, propose to the user what to capture and where.

## Projects

There is no single project at the root: this is a **monorepo**. Each design lives in
`projects/<x>/` with its own `CLAUDE.md` (where its `## Project` section goes: what it is, what it
mates with, where the meshes come from) and its `docs/design.md` (design narrative). See
[`projects/CLAUDE.md`](projects/CLAUDE.md). It comes with one starter project,
`projects/example/`, which seeds the canonical layout and conventions; delete it when you start
your own designs.
