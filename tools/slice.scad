// ============================================================
//  slice — reusable TRUE 2D cross-section helper for inspecting
//  interiors (wall thickness, clearances, snap engagement, pockets)
//  that the outer surface hides.
//
//  slice(axis, pos) — `projection(cut=true)` of the children at the
//  plane axis = pos. Output is a 2D shape in the XY plane: render it
//  from the TOP view. The cut plane is mapped onto z = 0 so that WORLD Z
//  always lands on the image vertical (part stands base-down, like the
//  design orientation), with no mirror (matrices have det +1):
//    z: image X,Y = world X,Y
//    x: image X,Y = world Y, Z   (look along −X; Z up, Y right)
//    y: image X,Y = world X, Z   (look along +Y; Z up, X right)
//  Crisp outline for reading exact profile / fit (e.g. the inner clip
//  radius against the box).
//
//    axis = "x" | "y" | "z"
//
//  Usage:
//    use <tools/slice.scad>
//    slice("z", 19) my_part();        // cross-section at z = 19
//
//  Colour survives (color() wraps the projection, outside any CSG) — so to
//  compare two parts, slice each separately and colour each:
//    color("gold") slice("z", 19) partA();
//    color("red")  slice("z", 19) partB();
//
//  Inspection-only geometry (never part of a printed piece) — lives in
//  tools/, not lib/. Usable directly for live interactive slicing in the
//  OpenSCAD GUI, OR driven headless by tools/slice.py / run_batch.py.
// ============================================================

module slice(axis = "z", pos = 0) {
    if (axis == "z")
        projection(cut = true)
            translate([0, 0, -pos]) children();
    else if (axis == "x")
        projection(cut = true)
            multmatrix([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, -pos], [0, 0, 0, 1]])
                children();
    else if (axis == "y")
        projection(cut = true)
            multmatrix([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, pos], [0, 0, 0, 1]])
                children();
}

// ---------- Self-preview (top-level; `use <...>` ignores it — never `include`) ----------
// The 2D cross-section of a sphere at z = 2: a disc (its outline at that height).
$fn = 48;
slice("z", pos = 2) sphere(12);
