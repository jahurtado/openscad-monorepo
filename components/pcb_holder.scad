// =====================================================================
//  pcb_holder — PCB retention by corner or edge (slide-in retainer).
//
//  DESIGNED companion (invented geometry, parametric) that holds a PCB. It is NOT a
//  press-fit clip (*snap-fit*): each holder is a simple capture —*ledge* below + *lip*
//  above, separated by = PCB thickness + clearance— with the INNER side open. There
//  are two holder types, combinable:
//    · CORNER: L-shaped bracket, registers the PCB in X and Y.
//    · EDGE: straight, captures one edge — side (X) or end (Y); its position along
//      the edge is parametric (shift), just like its size.
//
//  ASSEMBLY MODEL (the user's): TWO parts, each with its own holders; the PCB is placed
//  and the two parts close over it and are screwed EXTERNALLY (the screws come from the
//  host part, not from the holder). That is why the holders carry no lead-in chamfer:
//  the PCB does not slide, the parts do. The component delivers the holder as a POSITIVE
//  + anchors.
//
//  REUSABLE across projects: PCB footprint (width × length), thickness, and size +
//  position of each holder, all parametric. Single source: consumers import it, they do
//  not copy it. (The convention is that a catalog component is developed in its own bench
//  project; this one comes WITHOUT its bench — `projects/example/` merely consumes it.
//  See `components/CLAUDE.md` § What's here.)
//
//  Units mm. Local frame: PCB footprint CENTERED in XY (origin = center of the PCB);
//  z = 0 = seating face of the holders (host floor). The PCB sits at z = STANDOFF
//  (bottom face) .. STANDOFF + PCB_T (top face); the lip overhangs above it.
// =====================================================================

// ---------- Inputs (design defaults; ADJUST = tune with a test print) ----------
PCBH_PCB_T    = 1.5; // ADJUST: PCB thickness (≈1.5; depends on the PCB)
PCBH_REF_T    = 1.6; // REFERENCE PCB thickness (the thickest standard FR-4) used to level
                     // the TOP FACE of the clip: with `level_clip` (ON), a thinner PCB
                     // does not lower the clip — the lip grows upward to this reference
                     // plane, so every clip finishes at the SAME height. The compensation
                     // is never negative: a PCB THICKER than this follows its own
                     // thickness (the clip is not trimmed).
PCBH_FIT      = 0.2; // ADJUST: XY clearance between PCB edge and wall (per side)
PCBH_SLOT_CL  = 0.2; // ADJUST: vertical clearance (gap − PCB thickness): play under the lip
PCBH_CLIP_W   = 8;   // ADJUST: CORNER clip arm along the X edge
PCBH_CLIP_D   = 8;   // ADJUST: CORNER clip arm along the Y edge
PCBH_WALL     = 2;   // ADJUST: outer wall thickness
PCBH_STANDOFF = 2;   // ADJUST: ledge height (PCB above the host floor)
PCBH_LIP      = 1.5; // ADJUST: lip overhang over the PCB (inward)
PCBH_LIP_T    = 1.2; // ADJUST: lip thickness (Z)

// EDGE clip (side / end): captures ONE straight edge at a given position.
PCBH_EDGE_LEN   = 12; // ADJUST: edge-clip length along the edge
PCBH_EDGE_DEPTH = 6;  // ADJUST: clip reach inward under the PCB (perpendicular to the edge)

// Default PCB footprint (for preview/bench; the consumer passes its own).
PCBH_DEF_W = 50; // ADJUST: default PCB width (X)
PCBH_DEF_L = 70; // ADJUST: default PCB length (Y)

PCBH_OVER = 0.01; // overlap to avoid coplanar faces

// Total holder height = ledge + PCB slot + lip. With `level_clip` the top face is
// leveled to the reference PCB (`pcb_ref_t`), never below the real one.
function pcb_holder_height(pcb_t = PCBH_PCB_T, slot_cl = PCBH_SLOT_CL,
                           standoff = PCBH_STANDOFF, lip_t = PCBH_LIP_T,
                           pcb_ref_t = PCBH_REF_T, level_clip = true) =
  standoff + (level_clip ? max(pcb_t, pcb_ref_t) : pcb_t) + slot_cl + lip_t;

// ---------- Anchors + accessors (functions, NOT top-level vars) ----------
// XY center of a PCB corner (sx, sy ∈ {−1,1}).
function pcb_holder_corner_xy(sx, sy, width, length) = [sx * width / 2, sy * length / 2];

// anchor(name, ...): component reference.
//   "pcb_size" -> [W, L, pcb_t] · "seat_z" -> z of the PCB bottom face (= standoff)
//   "height" -> total holder height · "corner_lt/rt/lb/rb" -> [x, y, seat_z] of each corner
function pcb_holder_anchor(name, width = PCBH_DEF_W, length = PCBH_DEF_L,
                           pcb_t = PCBH_PCB_T, standoff = PCBH_STANDOFF,
                           pcb_ref_t = PCBH_REF_T, level_clip = true) =
    name == "pcb_size" ? [width, length, pcb_t]
  : name == "seat_z"   ? standoff
  : name == "height"   ? pcb_holder_height(pcb_t = pcb_t, standoff = standoff,
                                           pcb_ref_t = pcb_ref_t, level_clip = level_clip)
  : name == "corner_lb" ? [pcb_holder_corner_xy(-1, -1, width, length)[0], pcb_holder_corner_xy(-1, -1, width, length)[1], standoff]
  : name == "corner_rb" ? [pcb_holder_corner_xy( 1, -1, width, length)[0], pcb_holder_corner_xy( 1, -1, width, length)[1], standoff]
  : name == "corner_lt" ? [pcb_holder_corner_xy(-1,  1, width, length)[0], pcb_holder_corner_xy(-1,  1, width, length)[1], standoff]
  : name == "corner_rt" ? [pcb_holder_corner_xy( 1,  1, width, length)[0], pcb_holder_corner_xy( 1,  1, width, length)[1], standoff]
  : undef;

// ---------- Private helper: CORNER clip in the (+X,+Y) quadrant ----------
// Explicit coordinates at the +,+ corner; the other 3 via scale([sx,sy,1]) (mirror).
// L-shaped walls ONLY on the two OUTER edges (+X,+Y); the inner side (toward the
// center of the PCB) is left OPEN — the corner goes in there and the two halves meet.
// rim    = INWARD reach of the ledge/base under the PCB edge (thin rim; instead of
//          the solid clip_w×clip_d base). Default = clip_w (compat).
// base_h = height of the BASE/foot that extends the clip BEYOND the +Y edge of the PCB
//          (in a host printed on its side, that direction = toward the print bed). base_h<=0
//          → no base (the consumer adds the support, as before). The foot is a THIN
//          section (thickness `rim` in Z) that backs the overhang so it is not left in air.
module _pcb_holder_corner_pp(width, length, pcb_t, fit, slot_cl, clip_w, clip_d,
                             wall, standoff, lip, lip_t, rim, base_h,
                             pcb_ref_t, level_clip) {
  hw = width / 2;  hl = length / 2;
  xo = hw + fit;   yo = hl + fit;            // inner faces of the outer walls
  xout = xo + wall; yout = yo + wall;        // outer faces
  x_in = hw - clip_w; y_in = hl - clip_d;    // inward reach of the clip (X/Y edge)
  // eff_t levels the TOP FACE of the clip: with level_clip, a PCB thinner than the
  // reference does not lower the clip (the lip grows upward). It never trims below the
  // real PCB → the compensation is never negative.
  eff_t = level_clip ? max(pcb_t, pcb_ref_t) : pcb_t;
  Htop  = standoff + eff_t + slot_cl + lip_t;
  z_lip = standoff + pcb_t + slot_cl;        // bottom face of the lip (follows the REAL PCB)
  union() {
    // Ledge/base = L-shaped rim (reach `rim`), not a solid block → less material behind the PCB.
    translate([x_in, hl - rim, 0]) cube([xout - x_in, yout - (hl - rim), standoff]);   // +Y rim
    translate([hw - rim, y_in, 0]) cube([xout - (hw - rim), yout - y_in, standoff]);   // +X rim
    translate([x_in, yo, 0]) cube([xout - x_in, wall, Htop]);                     // +Y wall
    translate([xo, y_in, 0]) cube([wall, yout - y_in, Htop]);                     // +X wall
    translate([x_in, hl - lip, z_lip]) cube([xout - x_in, yout - (hl - lip), lip_t]); // +Y lip
    translate([hw - lip, y_in, z_lip]) cube([xout - (hw - lip), yout - y_in, lip_t]); // +X lip
    // BASE/foot: extends the clip beyond the +Y edge (toward the bed/floor) with the FULL
    // SECTION of the clip (z 0..Htop) → same width as the grip (no step) and solid down to
    // the floor. (The thin rim behind the PCB is the ledge above, a separate thing.)
    if (base_h > 0)
      translate([x_in, yout, 0]) cube([xout - x_in, base_h, Htop]);
  }
}

// ---------- POSITIVE — one CORNER clip (at corner sx,sy of the footprint) ----------
module pcb_holder_corner_clip(
  sx = 1, sy = 1,
  width = PCBH_DEF_W, length = PCBH_DEF_L,
  pcb_t = PCBH_PCB_T, fit = PCBH_FIT, slot_cl = PCBH_SLOT_CL,
  clip_w = PCBH_CLIP_W, clip_d = PCBH_CLIP_D, wall = PCBH_WALL,
  standoff = PCBH_STANDOFF, lip = PCBH_LIP, lip_t = PCBH_LIP_T,
  rim = undef, base_h = 0,
  pcb_ref_t = PCBH_REF_T, level_clip = true
) {
  // default rim = clip_w ("wide" base as before); pass it small for a thin rim.
  rim_e = is_undef(rim) ? clip_w : rim;
  // sx,sy ∈ {−1,1}: scale mirrors the +,+ corner to the requested quadrant (identity if 1).
  scale([sx, sy, 1])
    _pcb_holder_corner_pp(width, length, pcb_t, fit, slot_cl, clip_w, clip_d,
                          wall, standoff, lip, lip_t, rim_e, base_h,
                          pcb_ref_t, level_clip);
}

// ---------- Private helper: straight EDGE clip (canonical: +X edge at x=half) ----------
// A single outer wall + ledge + lip, inner side open. `pos` = center along the edge
// (shift); `len` = length; `depth` = reach inward under the PCB.
module _pcb_holder_edge_pp(half, pos, len, depth, pcb_t, fit, slot_cl,
                           wall, standoff, lip, lip_t, pcb_ref_t, level_clip) {
  xo = half + fit;  xout = xo + wall;
  x_in = half - depth;
  y0 = pos - len / 2;
  eff_t = level_clip ? max(pcb_t, pcb_ref_t) : pcb_t;  // levels the top face of the clip
  Htop  = standoff + eff_t + slot_cl + lip_t;
  z_lip = standoff + pcb_t + slot_cl;                  // lip follows the REAL PCB
  union() {
    translate([x_in, y0, 0]) cube([xout - x_in, len, standoff]);                  // ledge/base
    translate([xo, y0, 0]) cube([wall, len, Htop]);                               // outer wall
    translate([half - lip, y0, z_lip]) cube([xout - (half - lip), len, lip_t]);   // lip
  }
}

// ---------- POSITIVE — one EDGE clip (side / end) ----------
// side ∈ "left"|"right" (sides, X axis) | "bottom"|"top" (ends, Y axis).
// pos = SHIFT of the center along the edge (0 = centered; + toward the edge's +axis).
// len / depth = holder size (along the edge / inward).
module pcb_holder_edge_clip(
  side = "left", pos = 0, len = PCBH_EDGE_LEN, depth = PCBH_EDGE_DEPTH,
  width = PCBH_DEF_W, length = PCBH_DEF_L,
  pcb_t = PCBH_PCB_T, fit = PCBH_FIT, slot_cl = PCBH_SLOT_CL,
  wall = PCBH_WALL, standoff = PCBH_STANDOFF, lip = PCBH_LIP, lip_t = PCBH_LIP_T,
  pcb_ref_t = PCBH_REF_T, level_clip = true
) {
  hw = width / 2;  hl = length / 2;
  // Canonical = +X edge; the other 3 faces by mirror/rotation (they map the open side too).
  if (side == "right")
    _pcb_holder_edge_pp(hw, pos, len, depth, pcb_t, fit, slot_cl, wall, standoff, lip, lip_t, pcb_ref_t, level_clip);
  else if (side == "left")
    mirror([1, 0, 0]) _pcb_holder_edge_pp(hw, pos, len, depth, pcb_t, fit, slot_cl, wall, standoff, lip, lip_t, pcb_ref_t, level_clip);
  else if (side == "top")
    rotate([0, 0, 90]) _pcb_holder_edge_pp(hl, -pos, len, depth, pcb_t, fit, slot_cl, wall, standoff, lip, lip_t, pcb_ref_t, level_clip);
  else if (side == "bottom")
    rotate([0, 0, -90]) _pcb_holder_edge_pp(hl, pos, len, depth, pcb_t, fit, slot_cl, wall, standoff, lip, lip_t, pcb_ref_t, level_clip);
}

// ---------- POSITIVE — placement: corners and/or edges ----------
// corners = list of [sx,sy] (default all 4).
// edges   = list of [side, pos?, len?, depth?] — pos = shift (def 0), len/depth = holder
//           size (def PCBH_EDGE_LEN / PCBH_EDGE_DEPTH). E.g.: ["left", 12] = left side
//           clip shifted +12 in Y; ["top", -8, 20] = top end at −8 in X, 20 long. For the
//           2-part assembly, pass each half its own holders.
module pcb_holder(
  width = PCBH_DEF_W, length = PCBH_DEF_L,
  corners = [[-1, -1], [1, -1], [-1, 1], [1, 1]],
  edges = [],
  pcb_t = PCBH_PCB_T, fit = PCBH_FIT, slot_cl = PCBH_SLOT_CL,
  clip_w = PCBH_CLIP_W, clip_d = PCBH_CLIP_D, wall = PCBH_WALL,
  standoff = PCBH_STANDOFF, lip = PCBH_LIP, lip_t = PCBH_LIP_T,
  edge_len = PCBH_EDGE_LEN, edge_depth = PCBH_EDGE_DEPTH,
  pcb_ref_t = PCBH_REF_T, level_clip = true
) {
  for (c = corners)
    pcb_holder_corner_clip(c[0], c[1], width, length, pcb_t, fit, slot_cl,
                           clip_w, clip_d, wall, standoff, lip, lip_t,
                           pcb_ref_t = pcb_ref_t, level_clip = level_clip);
  for (e = edges)
    pcb_holder_edge_clip(
      e[0],
      is_undef(e[1]) ? 0 : e[1],          // pos (shift)
      is_undef(e[2]) ? edge_len : e[2],   // len
      is_undef(e[3]) ? edge_depth : e[3], // depth
      width, length, pcb_t, fit, slot_cl, wall, standoff, lip, lip_t,
      pcb_ref_t = pcb_ref_t, level_clip = level_clip);
}

// ---------- REFERENCE — the PCB in its seated position (visual / clash) ----------
module pcb_holder_pcb(width = PCBH_DEF_W, length = PCBH_DEF_L,
                      pcb_t = PCBH_PCB_T, standoff = PCBH_STANDOFF) {
  color("#2e6e3f")
    translate([0, 0, standoff + pcb_t / 2])
      cube([width, length, pcb_t], center = true);
}

// ---------- Self-preview (top-level; `use <...>` ignores it — never `include`) ----------
// Three configurations (each as 2 colored halves + ref PCB): corners | sides | ends.
$fn = 48;
translate([-70, 0, 0]) {           // corners
  color("#caa14a") pcb_holder(corners = [[-1, -1], [1, -1]]);
  color("#7fa6c9") pcb_holder(corners = [[-1, 1], [1, 1]]);
  %pcb_holder_pcb();
}
translate([0, 0, 0]) {             // sides
  color("#caa14a") pcb_holder(corners = [], edges = [["left", 0]]);
  color("#7fa6c9") pcb_holder(corners = [], edges = [["right", 0]]);
  %pcb_holder_pcb();
}
translate([70, 0, 0]) {            // ends
  color("#caa14a") pcb_holder(corners = [], edges = [["bottom", 0]]);
  color("#7fa6c9") pcb_holder(corners = [], edges = [["top", 0]]);
  %pcb_holder_pcb();
}
