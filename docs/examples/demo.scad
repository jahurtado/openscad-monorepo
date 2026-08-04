// =====================================================================
//  demo.scad — DEMONSTRATION piece for the tools guide in docs/.
//  A rounded plate with a hole + a peg that fits with clearance,
//  to illustrate the tools (views, slice, parts, clearances...). A catalogue
//  of named modules, like a real main.scad: name them in --parts.
// =====================================================================
$fn = 64;

// 44x30x6 plate, r=4 corners, central hole Ø12 + M3 side drill.
module plate() {
  difference() {
    linear_extrude(6) offset(4) square([36, 22], center = true);
    translate([0, 0, -1]) cylinder(d = 12, h = 8);             // central hole Ø12
    translate([14, 0, 3]) rotate([0, 90, 0]) cylinder(d = 3.2, h = 12); // side drill
  }
}
// Ø11 peg (0.5 mm radial clearance in the hole) with a Ø16 head.
module peg() {
  cylinder(d = 11, h = 10);
  translate([0, 0, 10]) cylinder(d = 16, h = 3);
}
// WORLD/SEATED positions (for --parts): the peg inserted in the hole.
module plate_seated() plate();
module peg_seated() translate([0, 0, 1]) peg();

// Assembly (showcase): plate + seated peg.
module assembly() { color("steelblue") plate_seated(); color("orange") peg_seated(); }

assembly();   // default view when opened in OpenSCAD (use ignores it)
