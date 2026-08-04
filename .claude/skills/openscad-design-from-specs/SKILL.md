---
name: openscad-design-from-specs
description: |
  Design a parametric component (its .scad model in components/ or projects/<x>/modules/)
  from MEASUREMENTS — calipers, datasheet, functional dimensions — with no starting STL.
  Drives the measure → model → test → refine loop through dialogue (one measurement per turn).
  To start from an existing STL, use openscad-design-from-stl.
model: inherit
---

# Designing a component from specifications

Procedure for creating or iterating a component **model** from measurements. It assumes the
**model anatomy** (roles, template, choosing the origin) from [`docs/components.md`](../../../docs/components.md)
and the invariants in `CLAUDE.md` — I don't repeat them.

## Before you start
- Pre-flight once: `uv run tools/health_check.py` (tooling acceptance check).
- Where does it live? Reusable → `components/`; project one-off → `projects/<x>/modules/`.
- **Criterion**: this flow does not replicate an STL → the criterion is `check.py` manifold + correct
  **functional dimensions** (not `compare.py`).

## The loop
1. **Choose the origin** and document it in the header (anchors are expressed relative to it).
2. **Model** the visual + cutout + anchors with primitives — only what affects the *fit*. Tag each
   constant with `// MEASURED:` or `// ADJUST:`. To **see it in 3D from several viewpoints** while you
   model, use `render3d.py` (clean 3D views; there's no mesh here, so no `--vs`); the drawing and the
   test verify the dimensions.
3. **Dimension drawing** (`drawings/<name>_dims.py`): color = provenance (blue MEASURED, gray ADJUST, red missing).
4. **Refine through the measurement dialogue** (below) until it fits physically.

## Measurement dialogue (the heart)
The hard part is the numbers, not the OpenSCAD. Converge them incrementally without losing the trail:

- **One measurement per turn.** Pick the highest-risk `ADJUST` constant (footprint + mounting holes
  first; cosmetic — `clearance`, fillets — last). Ask for it citing **name + current value + reference
  axis + unit (mm)**. Accept `skip`.
- **On receiving it**: flip the tag `ADJUST → MEASURED` in place — keeping the trail (rule in
  [design-rules](../../../docs/design-rules.md)) — and **regenerate the drawing**.
- **Link** mechanically related constants by formula, not with two loose literals.
- **Test piece** (`test/`): the smallest print that exercises ONLY what is still uncertain,
  **reusing the model's geometry instead of re-deriving it** — otherwise the coupon and the part
  drift apart and the test proves nothing. Two idioms: a 1 mm plate carrying just the cutouts
  (calling the model's sub-modules), or an `intersection()` of the real piece with a small window,
  which reuses by construction and needs no sub-modules at all. Worked example of the second:
  `projects/example/test/lid_fit_test.scad`. Cheap to print, hold it against the real part.
- **After printing**: "fits" → mark MEASURED **only** what the test exercised (never wholesale);
  "off by N mm along D" → adjust that constant and reprint a partial plate; "can't tell" → ask for the
  next measurement.

## Shape from a 2D profile (DXF)
If the shape is defined by a **2D profile the user draws** (Inkscape → DXF) rather than loose
measurements: `linear_extrude`/`rotate_extrude` of the profile + the machined mouths/holes added **on
top** with `difference()`. It's the same idiom whether you come from specs or from STL — follow the
**imported DXF profile protocol** and the other idioms in the [design rules](../../../docs/design-rules.md).

### Validated path: PHYSICAL SILHOUETTE + PHOTO over a known-pitch grid

When the user has the shape **in hand** — a paper cutout, a cardboard template, the broken part —
don't ask them to draw it or dictate the dimensions of a curve. **Ask for a photo of the silhouette
resting on a grid background of known pitch** (a 10 mm cutting mat works) and trace it. This
approach has been validated end to end on a real project: the part printed from the tracing fit on
the first try.

Conditions for it to work:
- **Flat silhouette resting on the grid plane.** A paper cutout is the ideal case; an object with
  volume introduces parallax and the tracing stops being faithful.
- **Grid visible next to the part**, and good part/background contrast (segmentation is a threshold).
- **Measure the grid pitch LOCALLY, in bands right next to the part, and separately in X and Y.** A
  global scale bakes the residual perspective of a handheld shot into a systematic size error (2 %
  between axes in the real case).
- **Filter BEFORE decimating.** A raster contour carries pixel staircase on top of the cutout's
  waviness; if you decimate finer than the noise you keep it, and `dxf_smoother` will interpolate it
  faithfully. Order: low-pass → decimate to few points → `dxf_smoother`.
- **Protect from the filter what is straight by design**: split the contour at the corners (the ends
  of the major dimension), replace flat faces with exact segments and pin the corners, or the
  low-pass rounds them off and bows the resting face.

**If the silhouette has THICKNESS, the tracing is valid for SHAPE but NOT for SIZE.** The error is
not noise: it is a **systematic scale factor**, because the contour of an object of thickness `t`
floats above the grid plane and parallax enlarges it. Measured on a real case: a 4.25 mm-thick key
came out **3 % oversized** while the shape was exact (traced ellipse axis ratio 0.659 vs 0.657
measured). Operational takeaway: **use the tracing to choose the primitive and its proportions; use
the calipers to pin the scale**. And don't discard a tracing for coming out big — the shape
conclusion survives the size error.

And the discipline that goes with it: dimensions that come from a tracing are **`ADJUST`, not
`MEASURED`** — a photo against a grid gives on the order of ±0.3 mm, it is not a caliper. Flip them
when the printed part (or the calipers on the template) confirms. The traced DXF is **the source of
the shape**; keep the photo and the tracing script in `resources/` as provenance, and leave
cutouts/machining as parametric operations in the `.scad` instead of baking them into the DXF.

## Definition of done
- `check.py` manifold (Status/Genus) + correct functional dimensions.
- Test piece confirmed against the real component.
- Dimension drawing up to date (no unjustified reds).
