// ============================================================
//  base.scad — the tray of the starter enclosure: a rounded shell, open on
//  top, with the PCB retainers standing on its floor.
//
//  This is the piece that shows the three layers working together:
//    · lib/rounded.scad     → the shell (a generic primitive)
//    · components/pcb_holder → the retainers (a concrete reusable part)
//    · this file             → the design that combines them
//
//  Frame: XY centred on the PCB, z = 0 at the bottom of the box (the print bed).
//  Piece, not a front door: it does NOT set $fn — main.scad does.
// ============================================================

use <../../../lib/rounded.scad>
use <../../../components/pcb_holder.scad>
include <example_config.scad>

// Invariants. They live in a module and get CALLED from the geometry, because
// OpenSCAD skips top-level statements of a file imported with `use` — an assert
// in the header would be silently ignored exactly when it matters.
module _box_asserts() {
    assert(BOX_HOLDER_H == pcb_holder_height(pcb_t = BOX_PCB_T),
           "BOX_HOLDER_H no longer matches pcb_holder_height() — the component moved; re-read its defaults and update the constant (the drawing needs it as a literal).");
}

// The tray: shell minus the cavity, plus the retainers on the floor.
module base() {
    _box_asserts();
    difference() {
        // Outer shell. The outer radius follows the inner one so the wall keeps
        // a constant thickness all the way round the corner.
        translate([0, 0, box_rim_z() / 2])
            rounded_flat_cube(box_outer_w(), box_outer_l(), box_rim_z(),
                              BOX_CORNER_R + BOX_WALL);

        // Cavity, open at the top: the cutter pokes BOX_EPS past the rim so the
        // opening is a real hole and not a coplanar face.
        translate([0, 0, BOX_FLOOR + (box_cav_h() + BOX_EPS) / 2])
            rounded_flat_cube(box_cav_w(), box_cav_l(), box_cav_h() + BOX_EPS,
                              BOX_CORNER_R);
    }

    // The retainers. Their own frame has z = 0 at the host floor, so they get
    // lifted by the floor thickness; the component does the rest.
    translate([0, 0, BOX_FLOOR])
        pcb_holder(width = BOX_PCB_W, length = BOX_PCB_L, pcb_t = BOX_PCB_T);
}

// ---------- Self-preview (top-level; `use <...>` ignores it) ----------
// Opening this file on its own in OpenSCAD shows geometry, not an empty canvas.
// $fn goes here because outside main.scad it is not inherited.
$fn = 64;
base();
