# Parametric CAD / OpenSCAD glossary

A glossary of terms useful for parametric design, focused on OpenSCAD, 3D printing, and electronics enclosures.

> This file is **vocabulary only**: it defines the terms for naming the
> elements involved in 3D modeling of parts, so we all share a common
> language. The **how-to** lives elsewhere: the flow for modeling an external
> component in [`components.md`](components.md) and the rules for reusable
> primitives alongside their code in `lib/`.

---

## 1. Boolean operations and CSG

- **CSG (Constructive Solid Geometry)**: the paradigm in which solids are built by combining primitives through boolean operations. The foundation of OpenSCAD.
- **Union**: combines two solids. In OpenSCAD: `union()`.
- **Difference**: subtraction. In OpenSCAD: `difference()`. The first child is the base; the rest are subtracted.
- **Intersection**: keeps only the common volume. In OpenSCAD: `intersection()`.
- **Hull**: the convex hull of its children. In OpenSCAD: `hull()`.
- **Minkowski sum**: useful for rounding edges (with a sphere) or creating 3D offsets. In OpenSCAD: `minkowski()`.
- **Offset**: expands or contracts a 2D profile by a given distance. In OpenSCAD: `offset()`.
- **Manifold mesh**: a closed, watertight mesh in which every edge is shared by exactly two faces. CGAL (the engine OpenSCAD uses for F6) rejects non-manifold geometry.
- **Coplanar-face problem**: when a `difference()` cutter has a face EXACTLY coplanar with a face of the base solid, the boolean output has a zero-thickness shell where the two faces overlap, which CGAL reports as non-manifold. Most common when the cutter's Z range matches the slab's Z range exactly, or when the cutter's outer edge coincides with an existing enclosure wall. **Fix**: extend the cutter a small epsilon (≈0.05–0.1 mm) past the base solid's faces on every coinciding axis. This pattern is sometimes called *epsilon poking* / *over-cut*.

```scad
// Bad: cutter z range matches slab exactly -> coplanar faces, CGAL chokes.
difference() {
    cube([20, 20, 2]);
    translate([5, 5, 0]) cube([10, 10, 2]);  // top/bottom faces are coplanar
}

// Good: extend cutter past both faces of the slab.
EPS = 0.05;
difference() {
    cube([20, 20, 2]);
    translate([5, 5, -EPS]) cube([10, 10, 2 + 2*EPS]);
}
```

- **Phantom membrane (the SILENT variant of the problem above)**: two cutters *stacked* along the cutting axis that share the plane where they meet. Typical case: a stepped counterbore — a wide cylinder from one face to a shoulder, and a narrow coaxial cylinder from the shoulder to the other face. If both end EXACTLY at the shoulder plane, their two coplanar caps fuse into a zero-thickness shell (a *membrane*) that closes off the hole's core. Unlike the base case, this produces **no error**: F6 reports `Status: NoError` and `watertight=True`, and the volume barely changes (the membrane is ≈0 mm³). It only gives itself away through (a) a surface visible in *preview* where you should be able to see through, and (b) the **genus**: a plate with N through-holes must be genus N; the membrane drops it to N−1 (one hole stopped being a through-hole). **Fix**: overlap the two cutters across the step (the second one starts a margin before the shoulder plane), so the core is cut by BOTH and no shared cap remains; the shoulder is still defined by the wide cylinder, intact.

---

## 2. Geometry and transformations

- **Primitive**: a basic shape (cube, cylinder, sphere, polygon, etc.).
- **Sketch**: a 2D profile used to generate a solid.
- **Linear extrude**: linear extrusion of a 2D profile. In OpenSCAD: `linear_extrude()`.
- **Rotate extrude**: revolves a 2D profile around an axis. In OpenSCAD: `rotate_extrude()`.
- **Sweep**: sweeps a profile along a path.
- **Loft**: a smooth transition between two or more distinct profiles.
- **Mirror**: reflects across a plane. In OpenSCAD: `mirror()`.
- **Translate / rotate / scale**: translation, rotation, and scaling.
- **Bounding box**: the minimal enclosing box that contains the part.
- **Centroid**: the geometric center.
- **Origin**: the local geometric reference (plane, axis, or point) from which the part is built or measured; in a component, the local frame to which its anchors and cutout refer.

---

## 3. Edges and finishes

The three ways to "break" an edge are **distinct geometries** — decide which one before modeling:

- **Fillet**: an edge rounded with a constant **radius**. Convention reserves "fillet" for *concave* (interior) edges, but it's widely used for any radiused edge. Defined by its radius `r`.
- **Round / rounding**: a *convex* (exterior) radiused edge. Same geometry as a fillet, opposite curvature. Also defined by the radius `r`.
- **Chamfer (bevel)**: a **flat angled cut** across the edge — NOT rounded. "Chamfer" and "bevel" are near-synonyms (bevel is the more colloquial term). Defined by a width/setback and an angle (often, but not always, 45°).
- **Edge**: an edge.
- **Face**: a face.
- **Vertex**: a vertex.
- **Draft angle**: the angle needed to release parts from injection molds.

---

## 4. Cutouts, holes and openings

- **Cutout**: a recess of arbitrary shape, typically to house a component or provide external access (USB, jack, button).
- **Hole**: a hole, usually cylindrical, through or blind.
- **Through hole**: a hole that passes all the way through.
- **Blind hole**: a hole that does not pass through.
- **Pocket**: a blind cavity of defined shape, typical in CNC machining.
- **Cavity**: a generic term for an empty interior space.
- **Slot**: an elongated opening. When its ends are full semicircles (end radius = width/2) the shape is called an *obround* (engineering) or *stadium* / *capsule* (geometry); with an end radius smaller than width/2 it's a rounded-corner slot, not an *obround*.
- **Recess**: a shallow indentation.
- **Notch**: a small indentation cut open on an **edge** (V-shaped, square or rounded). Often used to **index**/orient one part against another, or to seat a protrusion that drops into it (see *keying* and *index feature* below).
- **Relief / relief cut**: a shallow recess specifically meant to give clearance to an adjacent part (button cap, connector body, etc.).
- **Counterbore**: a cylindrical recess for cylindrical screw heads (socket head cap screws).
- **Countersink**: a conical recess for conical (tapered) screw heads.
- **Spotface**: a shallow flat surface around a hole to seat a head or washer.
- **Grille / vent**: a pattern of slots/holes for ventilation or to bring external buttons through.
- **Negative / negative part**: the geometric representation of the volume to be subtracted.
- **Keep-out volume / keep-out zone**: a reserved area where there must be no material (cables, ventilation, connector access).
- **Clearance volume**: the component's volume plus clearance and the space needed for cables, tools, etc.

---

## 5. Protrusions and reinforcements

- **Boss**: a cylindrical protrusion, typically solid and threaded for a screw.
- **Rib**: a thin, elongated reinforcement.
- **Gusset**: a triangular reinforcement in a corner.
- **Standoff**: a spacer column that holds two surfaces apart (typical for PCBs).
- **Spacer**: a separator (similar to a standoff, but usually a separate part).
- **Lip**: a thin protruding edge.
- **Flange**: a wider perimeter edge.
- **Tab**: a small protruding tab.
- **Lug**: an ear-shaped protrusion with a hole for fastening.

---

## 6. Fits, tolerances and clearances

- **Tolerance**: the admissible margin of error.
- **Clearance**: the gap between two parts that must not touch. Typical in FDM: 0.15–0.3 mm.
- **Interference fit / press fit**: the part is slightly larger than the hole and requires force to assemble.
- **Slip fit**: a smooth fit, no appreciable clearance but no pressure.
- **Snap fit**: an elastic fit using clips.
- **Living hinge**: a flexible hinge integrated into the part itself — a thin strip of material that bends without breaking.
- **Flexure**: any elastic structure designed to deform predictably and spring back. A living hinge is a kind of flexure.
- **Cantilever**: a beam supported at only one end; the free end flexes under load.
- **Cantilever button / flexure button**: a button formed by a U- or C-shaped cut in a panel, leaving a tab attached on one side that flexes when pressed (e.g. to actuate a tactile switch underneath).
- **Kerf**: the width of material removed by a cut (laser, CNC, saw).
- **Backlash**: play in mechanisms (gears, leadscrews).
- **Shrinkage**: the material's contraction as it cools.

---

## 7. Fastening and joints

- **Mounting hole**: a hole used to fix the part in place.
- **Fastener**: a fastening element (screw, nut, rivet, etc.).
- **Heat-set insert / threaded insert**: a metal threaded insert installed into plastic with heat.
- **Captive nut**: a nut retained inside a shaped pocket so it can't rotate.
- **Self-tapping screw**: a screw that cuts its own thread.
- **Thread**: a screw thread.
- **Pitch**: the thread pitch.
- **Major / minor diameter**: the outer / inner diameter of the thread.
- **Keying / polarization (poka-yoke)**: giving two parts complementary features (tab+slot, protrusion+notch) that only mate in **one** orientation, so they cannot be assembled wrong. *Poka-yoke* = "mistake-proof".
- **Index / registration feature**: a protrusion, notch or *locating pin* that **locates** one part relative to another in a **repeatable** position (in addition to, or instead of, fastening it). It provides no retention by itself: it defines **where** the part lands. A keyed assembly is usually a registration feature that also admits only one orientation.

---

## 8. Parametric design

- **Parameter**: a variable that defines the part (width, height, wall thickness...).
- **Constraint**: a geometric restriction (parallelism, tangency, fixed distance).
- **Feature**: a concrete geometric feature (a hole, a boss, a fillet).
- **Module**: in OpenSCAD, a reusable block that generates geometry. Similar to a function.
- **Function**: in OpenSCAD, returns a value (not geometry).
- **Anchor / attachment point**: a reference point for positioning parts. A central concept in the BOSL2 library.
- **DRY (Don't Repeat Yourself)**: the principle of avoiding repeated values; use parameters.
- **Magic number**: a literal value with no explanation; bad practice.
- **Faceted trace**: the anti-pattern of reproducing a curved or organic contour by **sampling it into a list of points** and embedding them as a `polygon()`, instead of reconstructing the shape (a smoothed DXF profile, a `rotate_extrude`, the right primitive). The result matches the silhouette while being unparametric and unmodifiable — it *looks* right and *is* built wrong. Forbidden by the [design rules](design-rules.md); a short hand-written `polygon` with named dimensions (a rail profile, a trapezoid) is **not** a faceted trace.
- **`$fn`, `$fa`, `$fs`**: OpenSCAD special variables that control the resolution of curved surfaces.
- **Manifold**: a closed, well-formed mesh (no holes, no inverted faces). Required for printing.
- **Non-manifold**: a mesh with errors (edges shared by more than two faces, etc.).
- **Preview vs render (F5 vs F6)**: in OpenSCAD, quick view vs full CSG computation.

---

## 9. 3D printing specifics (FDM)

- **Layer height**: typically 0.1–0.3 mm.
- **Wall / perimeter**: the outer wall.
- **Wall thickness**: recommended as a multiple of the nozzle diameter.
- **Infill**: internal fill density (%).
- **Top / bottom layers**: the solid top and bottom layers.
- **Overhang**: an overhang. Problematic beyond ~45°.
- **Bridge**: a gap spanned between two points with no support beneath.
- **Support**: a temporary support structure.
- **Brim / raft / skirt**: bed-adhesion aids.
- **Seam**: the visible line where the nozzle changes layers.
- **Stringing**: thin filament strands between parts from poor retraction.
- **Elephant foot**: widening of the bottom layer caused by squish.
- **Z-seam**: the vertical seam.
- **Anisotropy**: the part is stronger in the XY plane than along Z.
- **Nozzle diameter**: typically 0.4 mm.
- **Slicer**: software that converts STL/3MF into G-code (Cura, PrusaSlicer, Orca...).

---

## 10. File formats

- **SCAD**: OpenSCAD source code.
- **STL**: triangular mesh. The 3D-printing standard, but lacks units and color.
- **3MF**: a modern format with metadata, materials, colors, and units.
- **STEP / IGES**: parametric / interchange CAD formats.
- **OBJ**: a mesh with texture support.
- **DXF / SVG**: 2D formats, useful for profiles and laser cutting.
- **G-code**: machine instructions (printer, CNC).

---

## 11. Useful mechanical concepts

- **Centerline**: the center line.
- **Pitch circle**: the reference circle on gears.
- **Module (gears)**: the gear module, which defines the tooth size.
- **Aspect ratio**: the ratio between dimensions.
- **Symmetry plane**: the plane of symmetry.
- **Assembly**: a set of parts.
- **Exploded view**: an exploded view.
- **BOM (Bill Of Materials)**: the bill of materials.

---

## 12. Terms of the external-component pattern

The glossary only *names* the pieces of this pattern; the **how to apply it**
(model anatomy, template, worked example, BOSL2 anchors) lives in
[`components.md`](components.md).

- **Model (of a component)**: a `.scad` file (in `components/` or `modules/`) that reproduces an external component (sensor, connector, board) as a set of representations in a common local coordinate system. It isn't printed; the part imports it with `use <...>`.
- **Nominal / visual representation**: the faithful geometric model of the component, **with no clearance**, used to visualize the assembly and detect collisions (e.g. `arduino_nano()`).
- **Cutout**: the *negative* volume to subtract from the part so the component fits and its accesses stay open; it includes clearance and long extensions (see §4). It is not "the visual + clearance": its shape is deliberately different (e.g. `arduino_nano_cutout(clearance)`).
- **Anchor**: a reference point in the component's *local* coordinates, exposed as a **function** (`use <...>` doesn't import loose variables) to position features relative to the part (e.g. `arduino_nano_anchor("usb")`).

---

_Reference glossary for parametric design in OpenSCAD. For the how-to, see [`components.md`](components.md); the local library layer lives in `lib/`, where each file documents itself in its own header._
