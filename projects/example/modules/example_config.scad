// ============================================================
//  example_config.scad — constants for the starter enclosure.
//
//  `include`d (not `use`d) by the pieces, so these are plain variables.
//  No geometry here, and no self-preview: an `include` would leak it into
//  every importer.
//
//  Every constant carries its provenance: MEASURED = verified with calipers
//  against the real part; ADJUST = an estimate, to be confirmed. Flip the tag
//  in place when the measurement arrives, and never delete the trail.
// ============================================================

// ---- the board this box houses ---------------------------------------------
// The defaults of the pcb_holder component: a generic 50 × 70 board. Swap these
// for your own and everything below follows.
BOX_PCB_W = 50;   // ADJUST: PCB width  (X, mm)
BOX_PCB_L = 70;   // ADJUST: PCB length (Y, mm)
BOX_PCB_T = 1.5;  // ADJUST: PCB thickness (mm)

// ---- what the component reserves around the board --------------------------
// pcb_holder puts an L-shaped wall of PCBH_WALL outside each PCB corner, with
// PCBH_FIT of play per side. The cavity has to clear both, or the holders would
// not fit inside their own box.
BOX_FIT         = 0.2;  // ADJUST: XY play between PCB edge and holder (per side) = PCBH_FIT
BOX_HOLDER_WALL = 2;    // ADJUST: holder outer wall = PCBH_WALL
BOX_HOLDER_H    = 5.0;  // ADJUST: total holder height, = pcb_holder_height() with the
                        // component defaults (standoff 2 + ref PCB 1.6 + slot 0.2 + lip 1.2).
                        // Mirrored here, so revisit it if the component's defaults move.

// ---- the enclosure ---------------------------------------------------------
BOX_WALL     = 2;    // ADJUST: outer wall thickness (mm)
BOX_FLOOR    = 2;    // ADJUST: floor thickness (mm)
BOX_HEADROOM = 12;   // ADJUST: free height above the holder lip, for tall components
BOX_CORNER_R = 3;    // ADJUST: inner corner radius in plan (mm)

// ---- the lid ---------------------------------------------------------------
BOX_LID_T   = 2;     // ADJUST: lid plate thickness (mm)
BOX_LIP_H   = 3;     // ADJUST: depth the lid lip plugs into the cavity (mm)
BOX_LIP_T   = 1.5;   // ADJUST: wall thickness of that lip — it is a rim, not a slab
BOX_LID_CL  = 0.25;  // ADJUST: play of that lip against the cavity wall (per side)

BOX_EPS = 0.05;      // local manifold fudge: overhang for cutters, overlap for unions

// ---- derived (functions, so `use` can read them from another file) ----------
// Cavity = board + the component's own footprint. Everything else hangs off this.
function box_cav_w() = BOX_PCB_W + 2 * (BOX_FIT + BOX_HOLDER_WALL);
function box_cav_l() = BOX_PCB_L + 2 * (BOX_FIT + BOX_HOLDER_WALL);
function box_cav_h() = BOX_HOLDER_H + BOX_HEADROOM;

function box_outer_w() = box_cav_w() + 2 * BOX_WALL;
function box_outer_l() = box_cav_l() + 2 * BOX_WALL;

// z of the rim the lid lands on (top of the base walls).
function box_rim_z() = BOX_FLOOR + box_cav_h();
