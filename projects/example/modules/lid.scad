// ============================================================
//  lid.scad — the cover of the starter enclosure: a plate with a lip that
//  plugs into the cavity and keeps it located.
//
//  Frame: XY centred like the base, and z = 0 at the MATING PLANE (the rim of
//  the base). The plate grows upward, the lip hangs downward — so in the
//  assembly it is just `translate([0, 0, box_rim_z()]) lid()`.
//  Piece, not a front door: it does NOT set $fn — main.scad does.
// ============================================================

use <../../../lib/rounded.scad>
include <example_config.scad>

module lid() {
    // The plate: same footprint as the box, so the outside is flush.
    translate([0, 0, BOX_LID_T / 2])
        rounded_flat_cube(box_outer_w(), box_outer_l(), BOX_LID_T,
                          BOX_CORNER_R + BOX_WALL);

    // The lip that enters the cavity, minus its clearance per side. It is a RIM,
    // not a slab: a solid plug would fill the box with plastic and leave no room
    // for anything standing on the board. It overlaps the plate by BOX_EPS —
    // a union of merely touching solids is a zero-thickness contact.
    lip_w = box_cav_w() - 2 * BOX_LID_CL;
    lip_l = box_cav_l() - 2 * BOX_LID_CL;
    translate([0, 0, -(BOX_LIP_H - BOX_EPS) / 2])
        difference() {
            rounded_flat_cube(lip_w, lip_l, BOX_LIP_H + BOX_EPS, BOX_CORNER_R);
            // Hollow it out. The cutter pokes past both ends so neither face is
            // left coplanar with the rim's.
            rounded_flat_cube(lip_w - 2 * BOX_LIP_T, lip_l - 2 * BOX_LIP_T,
                              BOX_LIP_H + BOX_EPS + 2 * BOX_EPS,
                              max(BOX_CORNER_R - BOX_LIP_T, 0.1));
        }
}

// ---------- Self-preview (top-level; `use <...>` ignores it) ----------
$fn = 64;
lid();
