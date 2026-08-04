// ============================================================
//  main.scad — front door of example (starter project).
//
//  A small two-piece enclosure for a PCB: a tray that reuses the
//  `pcb_holder` component to retain the board, and a lid that plugs into it.
//  It exists to seed the canonical layout and to show the three layers
//  working together — projects → components → lib.
//
//  main is a catalogue of named modules that forward to the geometry in
//  modules/. A piece is picked by its name (build discovers *_print); there is
//  no RENDER variable. Delete the whole projects/example/ folder once you have
//  your pieces.
//    ./build.sh example                      # one STL per *_print
//    uv run tools/run_batch.py projects/example/main.scad
// ============================================================

use <modules/base.scad>
use <modules/lid.scad>
use <../../components/pcb_holder.scad>
include <modules/example_config.scad>

$fn = 180;                 // print-quality baseline (override -D '$fn=24' for preview)

// ── Printable deliverables (build discovers *_print) ──
// Print-bed orientation lives HERE. The tray already sits open-side up; the lid
// is flipped so its flat outer face goes on the bed and the lip points up.
module base_print() base();
module lid_print() translate([0, 0, BOX_LID_T]) rotate([180, 0, 0]) lid();

// ── Inspection solids (slice/run_batch discover *_solid) ──
// Each in its assembled pose, so a section cuts them where they really meet.
module base_solid() base();
module lid_solid() translate([0, 0, box_rim_z()]) lid();

// ── Assembly ──
// The board is a ghost: it is the reference the holders capture, not a part we print.
module assembly() {
    base_solid();
    lid_solid();
    %translate([0, 0, BOX_FLOOR]) pcb_holder_pcb(width = BOX_PCB_W, length = BOX_PCB_L,
                                                 pcb_t = BOX_PCB_T);
}

// All-solid twin of the showcase: the % ghost above is invisible to a cut view,
// so the viewer wraps this one instead. NOTE the name does NOT end in `_solid`:
// slice/run_batch discover pieces by that suffix, and a composite that matched
// would be sectioned as one more piece, duplicating the geometry of the others.
module assembly_all() {
    base_solid();
    lid_solid();
}

// ── Default view + cut inspection in the Customizer ──
// `use <main>` ignores these top-level statements (variables + call): the tools only
// see the modules above. Open main.scad in the GUI and move SHOW/CUT_POS to sweep
// the cut plane; SHOW="off" = the usual clean view.
use <../../lib/cut_plane_viewer.scad>
/* [Inspect cut plane] */
CUT_AXIS = "y";   // [x, y, z]
CUT_POS  = 0;     // [-45:1:45]
SHOW     = "off"; // [off, plane, cut, slice]
cut_plane_view(CUT_AXIS, CUT_POS, SHOW) assembly_all();
