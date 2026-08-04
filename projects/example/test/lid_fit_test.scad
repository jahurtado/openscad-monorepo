// ============================================================
//  lid_fit_test.scad — TEST PIECE: does the lid rim actually fit the cavity?
//
//  The starter box has exactly one dimension that is a guess rather than a
//  measurement: BOX_LID_CL, the play between the lid rim and the cavity wall
//  (see docs/design.md, "Status and evolution"). Printing both full pieces to
//  find out costs ~30 cm3 of plastic and a couple of hours. This coupon answers
//  the same question with a corner of each, in minutes.
//
//  HOW IT REUSES THE MODEL (the rule that makes a test piece worth trusting):
//  it does NOT re-derive the geometry. It calls the real `base()` and `lid()`
//  and INTERSECTS them with a corner window — so whatever the coupon shows is,
//  by construction, what the real pieces do. Change example_config.scad and the
//  coupon follows; there is no second copy of the numbers to drift.
//
//  Both coupons are cut in the SAME frame (the lid in its assembled pose), so
//  they are guaranteed to be cut at the same place.
//
//    uv run tools/check.py projects/example/test/lid_fit_test.scad --module fit_base_print
//    uv run tools/build.py projects/example/test/lid_fit_test.scad   # both coupons -> prints/
//
//  Then: print both, push one into the other and read the fit.
//    slides together with a little play      -> BOX_LID_CL is right; flip it to MEASURED
//    will not enter / needs force            -> raise BOX_LID_CL, reprint just this
//    rattles                                 -> lower it
//  Whatever you conclude, flip the tag in example_config.scad and never delete
//  the trail (see docs/design-rules.md).
// ============================================================

use <../modules/base.scad>
use <../modules/lid.scad>
include <../modules/example_config.scad>

$fn = 180;             // this file is its own front door, so it sets the baseline

// ---- what the coupon keeps -------------------------------------------------
FIT_WIN  = 24;   // ADJUST: XY size of the corner window cut out of each piece
FIT_BAND = 8;    // ADJUST: how far below the rim the tray coupon reaches (mm)

// The window sits on the +X/+Y corner: a real corner exercises the rounded
// corner radius as well as the two straight walls, which a mid-wall slab would
// not.
function fit_win_cx() = box_outer_w() / 2 - FIT_WIN / 2;
function fit_win_cy() = box_outer_l() / 2 - FIT_WIN / 2;

module fit_window(z_lo, z_hi) {
    translate([fit_win_cx(), fit_win_cy(), (z_lo + z_hi) / 2])
        cube([FIT_WIN, FIT_WIN, z_hi - z_lo], center = true);
}

// ---- the coupons, in the assembly frame ------------------------------------
// Tray: the top band of wall, i.e. the cavity mouth the rim has to enter.
module fit_base_solid() {
    intersection() {
        base();
        fit_window(box_rim_z() - FIT_BAND, box_rim_z() + BOX_EPS);
    }
}

// Lid: plate + rim, taken in its ASSEMBLED pose so it shares the tray's frame.
module fit_lid_solid() {
    intersection() {
        translate([0, 0, box_rim_z()]) lid();
        fit_window(box_rim_z() - BOX_LIP_H - BOX_EPS, box_rim_z() + BOX_LID_T);
    }
}

// ---- printable deliverables (build discovers *_print) ----------------------
// Each coupon is moved to the origin and dropped onto the bed. The tray coupon
// prints on its cut face; the lid coupon is flipped exactly like lid_print, so
// the surface that meets the bed is the same one as on the real part.
module fit_base_print() {
    translate([-fit_win_cx(), -fit_win_cy(), -(box_rim_z() - FIT_BAND)])
        fit_base_solid();
}

module fit_lid_print() {
    translate([-fit_win_cx(), fit_win_cy(), box_rim_z() + BOX_LID_T])
        rotate([180, 0, 0])
            fit_lid_solid();
}

// ---------- Self-preview (top-level; `use <...>` ignores it) ----------
// The two coupons as they mate, which is what the test is about.
fit_base_solid();
fit_lid_solid();
