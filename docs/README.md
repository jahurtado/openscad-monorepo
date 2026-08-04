# Reference documentation

Index of the monorepo's reference documentation. All reference docs live in this folder.

## Quick map — what to read for what

| If you need… | Read |
|---|---|
| The **definition** of a CAD / OpenSCAD / FDM term | [`concepts.md`](concepts.md) — the glossary |
| How to **model an external component** (the model: visual + cutout + anchors, in `components/` or `projects/<x>/modules/`) | [`components.md`](components.md) |
| The **design rules** (construction idioms: faceted trace, silhouette→DXF, coplanar faces, the DXF protocol, the `LINT-OK` escape hatch) | [`design-rules.md`](design-rules.md) |
| The iterative **measurement dialogue** + test pieces (`test/` per project; worked example in `projects/example/test/lid_fit_test.scad`) | skill `openscad-design-from-specs` |
| The dimensioned **drawing** per component (`drawings/`, `tools/dimsketch.py`) | [`tools-guide.md` § dimsketch](tools-guide.md#dimsketchpy--drawings) + the skill |
| **Using the tools** in `tools/` (check, slice, run_batch, analyze, compare, build…) with examples, images and the dependency map | [`tools-guide.md`](tools-guide.md) |

## The documents

- **[`concepts.md`](concepts.md)** — Parametric / OpenSCAD / FDM glossary. The
  English term is the primary entry. This is the place for *term definitions*.

- **[`components.md`](components.md)** — How to reproduce an external component
  (sensor, connector, board) as a model. It lives in `projects/<x>/modules/` (one-off) or
  is promoted to the `components/` catalog (reusable). Two paths: empirical (calipers +
  primitives) and mesh (centering a vendor STL). Anatomy, origin, template, validation.

- **[`design-rules.md`](design-rules.md)** — The **design rules**: the construction
  idioms (how to generate each kind of geometry correctly) + the protocol for imported
  DXF profiles. These are rules of **method** (not geometry), shared by both design skills and
  enforced by the `design-conventions-reviewer` subagent.

- **[`tools-guide.md`](tools-guide.md)** — User guide for the helpers in
  `tools/` (health_check, build, check, slice, run_batch, analyze, make_assembly,
  slice_viewer, compare, render3d, center_input, dxf_smoother, dimsketch, and gallery — the
  browsable catalog served with `./catalog.sh`), with an example and its image for each one (reproducible demo
  piece in [`examples/demo.scad`](examples/demo.scad)), the **dependency map**
  between tools, and a note on the **method criterion** (no tool). The exact flags derive from each
  tool's `--help` and are not documented here.

## The `lib/` layer

Local libraries live in `lib/`, alongside their code: **each file carries its own header** with its
API and the reasoning behind its choices. That header is the source — no list is kept here, because
the layer is meant to grow and any catalogue written elsewhere drifts from the code. To see what is
there: `ls lib/` and read the header of whichever one fits.

## Where each lesson learned goes

The routing (term → `concepts.md`; geometry → `lib/`; workflow anti-pattern → the skill) is a
repo convention; the detail isn't repeated here.
