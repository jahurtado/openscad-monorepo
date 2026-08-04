// analyze_tests.scad — fixtures with KNOWN dimensions to gate tools/analyze.py.
// Each module is a single solid; analyze should recover the dims in the comments.
$fn = 96;

// Plate 40x30x6 with a Ø8 hole right through.
module through_hole() difference() {
    translate([-20, -15, 0]) cube([40, 30, 6]);
    translate([0, 0, -1]) cylinder(d = 8, h = 8);
}

// Same plate: Ø8 through + Ø16 counterbore in the top 3 mm.
module counterbore() difference() {
    translate([-20, -15, 0]) cube([40, 30, 6]);
    translate([0, 0, -1]) cylinder(d = 8, h = 8);
    translate([0, 0, 3]) cylinder(d = 16, h = 4);
}

// Plate with a Ø6 BLIND hole 4 mm deep from the top (z 2..6).
module blind_hole() difference() {
    translate([-20, -15, 0]) cube([40, 30, 6]);
    translate([0, 0, 2]) cylinder(d = 6, h = 5);
}

// Plate with a Ø6 blind hole whose mouth is at z = 2.4 (OFF the 1 mm grid) — to gate
// the fine refinement: a coarse 1 mm sweep brackets it at z2..3, refine pins z≈2.4.
module blind_offgrid() difference() {
    translate([-20, -15, 0]) cube([40, 30, 6]);
    translate([0, 0, 2.4]) cylinder(d = 6, h = 5);
}

// Cup (Ø20, h10) with a Ø16 cavity from the top and a central Ø5 post (a STANDOFF
// that stands z 2..10 inside the cavity → an island in the slices).
module standoff() {
    difference() {
        cylinder(d = 20, h = 10);
        translate([0, 0, 2]) cylinder(d = 16, h = 9);
    }
    translate([0, 0, 2]) cylinder(d = 5, h = 8);
}

// Walled box 40x30x10, cavity 36x26 open at the top, floor 2 mm -> walls 2 mm all round.
module walled_box() difference() {
    translate([-20, -15, 0]) cube([40, 30, 10]);
    translate([-18, -13, 2]) cube([36, 26, 9]);
}

// Same box but the cavity widens in the upper band (z 6..10): walls 2 mm (z2..6) ->
// 1 mm (z6..10) — a recess in the wall, seen as two stacked cavities of different size.
module recess_box() difference() {
    translate([-20, -15, 0]) cube([40, 30, 10]);
    translate([-18, -13, 2]) cube([36, 26, 9]);
    translate([-19, -14, 6]) cube([38, 28, 5]);
}

// ---------- Self-preview (top-level; `use <...>` ignores it) ----------
standoff();
