//////////////////////////////////////////////////////////////////////////////
// OpenSCAD Component Collection at www.mytechexperiments.com
// Copyright (c) 2015-2026 Jose Antonio Hurtado
//
// Released under the MIT License. See the LICENSE file at the root of this
// repository for the full text.
//
//////////////////////////////////////////////////////////////////////////////
//
//  rounded.scad — boxes and cylinders with rounded / beveled edges,
//  built from primitives (cube + corner spheres/cylinders) instead of
//  minkowski(). The whole point is to AVOID minkowski, which is very
//  expensive to render — reach for these to round borders. (See the
//  project's todo-notes / design conventions.)
//
//  Every solid is centered at the origin. `fn` controls the roundness
//  facet count (defaults to the caller's $fn).
//
//  Quick guide:
//    rounded_cube            — box, ALL 12 edges + 8 corners rounded.
//    rounded_flat_cube       — box, only the 4 vertical (Z) edges rounded.
//    rounded_flat_cube_x/_y  — same, rounding axis along X / Y instead.
//    rounded_flat_cube_y_bevel — NEGATIVE bevel/chamfer cutter for edges.
//    rounded_cylinder        — cylinder with rounded or beveled rims.
//
//////////////////////////////////////////////////////////////////////////////

// Box with EVERY edge and corner rounded by radius `r` — the cheap
// stand-in for minkowski(cube, sphere(r)). `r` is clamped to half the
// smallest dimension. Centered at origin.
//
// Built as the convex hull() of 8 corner spheres. Despite hull's
// reputation, this beats the old difference()+union() of 12 boxes / 8
// spheres / 12 cylinders: ~15-30% faster and ~25% fewer triangles, in
// one convex op instead of a stack of 3D booleans. Same volume to
// ~0.01%. Caveat: the flat faces are tangent to the *faceted* spheres,
// so each dimension lands a sub-$fn sagitta under nominal (~0.001 mm at
// $fn=180) — negligible for FDM. Only valid because a rounded box is
// convex; a non-convex solid cannot use hull.
module rounded_cube(x, y, z, r, fn = $fn) {
  radius = min(r, x / 2, y / 2, z / 2);

  hull()
    for (sx = [-1, 1], sy = [-1, 1], sz = [-1, 1])
      translate([sx * (x / 2 - radius),
                 sy * (y / 2 - radius),
                 sz * (z / 2 - radius)])
        sphere(r = radius, $fn = fn);
}

// Box with only the four VERTICAL (Z-aligned) edges rounded by `r` —
// i.e. an extruded rounded-rectangle. Top and bottom faces stay sharp.
// `r` clamped to half the smaller of x, y. Centered at origin.
//
// Built as the 2D hull() of four corner circles, swept up with
// linear_extrude — one convex op, no 3D CSG. r = 0 falls back to a plain
// square (corner circles would be degenerate). The hull degrades
// gracefully across the WHOLE radius range: at r = x/2 the left/right
// circles share a center and you get a stadium; at r = x/2 = y/2 all four
// coincide and you get a circle.
//
// (The earlier `offset(r) square([x-2r, y-2r])` form rendered EMPTY exactly
// at those limits — once a side hit 2*r the inner square collapsed to zero
// width and offset() of a zero-area square is empty. The hull form has no
// such degenerate. For r < x/2, y/2 it yields the identical rounded-rect.)
module rounded_flat_cube(x, y, z, r, fn = $fn) {
  radius = min(r, x / 2, y / 2);

  linear_extrude(height = z, center = true)
    if (radius <= 0)
      square([x, y], center = true);
    else
      hull()
        for (sx = [-1, 1], sy = [-1, 1])
          translate([sx * (x / 2 - radius), sy * (y / 2 - radius)])
            circle(r = radius, $fn = fn);
}

// rounded_flat_cube with the rounded edges running along X instead of Z
// (the box keeps overall size x,y,z; the rounded edges are the ones
// parallel to X). Centered at origin.
module rounded_flat_cube_x(x, y, z, r, fn = $fn) {
  rotate([0, 90, 0])
    rounded_flat_cube(z, y, x, r, fn);
}

// As rounded_flat_cube_x, but the rounded edges run along Y.
module rounded_flat_cube_y(x, y, z, r, fn = $fn) {
  rotate([90, 0, 0])
    rounded_flat_cube(x, z, y, r, fn);
}

// NEGATIVE bevel/chamfer cutter for the edges and corners of a flat cube
// of size x,y,z. Subtract it from the box to knock the edges off at a
// straight angle (a chamfer, not a round). Mirrors a wedge to all four
// sides/corners.
//
//   size  — bevel depth (how far the cut reaches in from each face).
//   angle — bevel angle of the wedge.
//   r     — optional radius that rounds the bevel's outer corner
//           transition; r = 0 leaves a pure straight chamfer.
//
// Centered at origin, matching the rounded_* boxes it cuts.
module rounded_flat_cube_y_bevel(x, y, z, size, angle, r) {
  translate([0, y / 2 - size, z / 2])
    rotate([angle, 0, 0])
      translate([0, size, -size])
        cube([x, size * 2, size * 2], center=true);

  mirror([0, 1, 0])
    translate([0, y / 2 - size, z / 2])
      rotate([angle, 0, 0])
        translate([0, size, -size])
          cube([x, size * 2, size * 2], center=true);

  mirror([0, 0, 1])
    translate([0, y / 2 - size, z / 2])
      rotate([angle, 0, 0])
        translate([0, size, -size])
          cube([x, size * 2, size * 2], center=true);

  mirror([0, 1, 0])
    mirror([0, 0, 1])
      translate([0, y / 2 - size, z / 2])
        rotate([angle, 0, 0])
          translate([0, size, -size])
            cube([x, size * 2, size * 2], center=true);

  translate([x / 2, y / 2 - size, 0])
    rotate([0, 0, angle])
      translate([size, size, 0])
        cube([size * 2, size * 2, z], center=true);

  mirror([0, 1, 0])
    translate([x / 2, y / 2 - size, 0])
      rotate([0, 0, angle])
        translate([size, size, 0])
          cube([size * 2, size * 2, z], center=true);

  mirror([1, 0, 0])
    translate([x / 2, y / 2 - size, 0])
      rotate([0, 0, angle])
        translate([size, size, 0])
          cube([size * 2, size * 2, z], center=true);

  mirror([0, 1, 0])
    mirror([1, 0, 0])
      translate([x / 2, y / 2 - size, 0])
        rotate([0, 0, angle])
          translate([size, size, 0])
            cube([size * 2, size * 2, z], center=true);

  translate([x / 2 - size, 0, z / 2])
    rotate([0, angle, 0])
      translate([size, 0, size])
        cube([size * 2, y, size * 2], center=true);

  mirror([0, 0, 1])
    translate([x / 2 - size, 0, z / 2])
      rotate([0, angle, 0])
        translate([size, 0, size])
          cube([size * 2, y, size * 2], center=true);

  mirror([1, 0, 0])
    translate([x / 2 - size, 0, z / 2])
      rotate([0, angle, 0])
        translate([size, 0, size])
          cube([size * 2, y, size * 2], center=true);

  mirror([0, 0, 1])
    mirror([1, 0, 0])
      translate([x / 2 - size, 0, z / 2])
        rotate([0, angle, 0])
          translate([size, 0, size])
            cube([size * 2, y, size * 2], center=true);

  if (r > 0) {

    translate([0, size, 0])
      difference() {
        translate([x / 2 + r, -y / 2 - size, z / 2 + r])
          translate([-r, 0, -r])
            cube([2 * r, 2 * size, 2 * r], center=true);

        translate([x / 2, -y / 2, z / 2])
          translate([-r, 0, -r])
            rotate([90, 0, 0])
              cylinder(r1=r + size, r2=r - size, h=2 * size, center=true);
      }

    mirror([0, 1, 0])
      translate([0, size, 0])
        difference() {
          translate([x / 2 + r, -y / 2 - size, z / 2 + r])
            translate([-r, 0, -r])
              cube([2 * r, 2 * size, 2 * r], center=true);

          translate([x / 2, -y / 2, z / 2])
            translate([-r, 0, -r])
              rotate([90, 0, 0])
                cylinder(r1=r + size, r2=r - size, h=2 * size, center=true);
        }

    mirror([0, 0, 1])
      translate([0, size, 0])
        difference() {
          translate([x / 2 + r, -y / 2 - size, z / 2 + r])
            translate([-r, 0, -r])
              cube([2 * r, 2 * size, 2 * r], center=true);

          translate([x / 2, -y / 2, z / 2])
            translate([-r, 0, -r])
              rotate([90, 0, 0])
                cylinder(r1=r + size, r2=r - size, h=2 * size, center=true);
        }

    mirror([0, 1, 0])
      mirror([0, 0, 1])
        translate([0, size, 0])
          difference() {
            translate([x / 2 + r, -y / 2 - size, z / 2 + r])
              translate([-r, 0, -r])
                cube([2 * r, 2 * size, 2 * r], center=true);

            translate([x / 2, -y / 2, z / 2])
              translate([-r, 0, -r])
                rotate([90, 0, 0])
                  cylinder(r1=r + size, r2=r - size, h=2 * size, center=true);
          }

    mirror([1, 0, 0])
      translate([0, size, 0])
        difference() {
          translate([x / 2 + r, -y / 2 - size, z / 2 + r])
            translate([-r, 0, -r])
              cube([2 * r, 2 * size, 2 * r], center=true);

          translate([x / 2, -y / 2, z / 2])
            translate([-r, 0, -r])
              rotate([90, 0, 0])
                cylinder(r1=r + size, r2=r - size, h=2 * size, center=true);
        }

    mirror([1, 0, 0])
      mirror([0, 1, 0])
        translate([0, size, 0])
          difference() {
            translate([x / 2 + r, -y / 2 - size, z / 2 + r])
              translate([-r, 0, -r])
                cube([2 * r, 2 * size, 2 * r], center=true);

            translate([x / 2, -y / 2, z / 2])
              translate([-r, 0, -r])
                rotate([90, 0, 0])
                  cylinder(r1=r + size, r2=r - size, h=2 * size, center=true);
          }

    mirror([1, 0, 0])
      mirror([0, 0, 1])
        translate([0, size, 0])
          difference() {
            translate([x / 2 + r, -y / 2 - size, z / 2 + r])
              translate([-r, 0, -r])
                cube([2 * r, 2 * size, 2 * r], center=true);

            translate([x / 2, -y / 2, z / 2])
              translate([-r, 0, -r])
                rotate([90, 0, 0])
                  cylinder(r1=r + size, r2=r - size, h=2 * size, center=true);
          }

    mirror([1, 0, 0])
      mirror([0, 1, 0])
        mirror([0, 0, 1])
          translate([0, size, 0])
            difference() {
              translate([x / 2 + r, -y / 2 - size, z / 2 + r])
                translate([-r, 0, -r])
                  cube([2 * r, 2 * size, 2 * r], center=true);

              translate([x / 2, -y / 2, z / 2])
                translate([-r, 0, -r])
                  rotate([90, 0, 0])
                    cylinder(r1=r + size, r2=r - size, h=2 * size, center=true);
            }
  }
}

// Cylinder of diameter `d`, height `h`, with its top and/or bottom rim
// rounded (a fillet) or beveled (a chamfer). Centered at origin.
//
//   r     — default rim radius for BOTH ends (0 = sharp cylinder).
//   tr,br — per-end radius override (top / bottom). undef (the default)
//           inherits r; any number WINS, including 0 — so tr=0 / br=0
//           force a sharp rim there even when r > 0. Setting both tr and
//           br makes r irrelevant.
//   bevel — default rim STYLE for both ends: false = round (a fillet),
//           true = straight chamfer.
//   bevel_top, bevel_bottom — per-end style override, exactly mirroring
//           tr/br over r: undef (the default) inherits bevel; an explicit
//           true/false wins. Lets one rim round and the other chamfer.
//
// Radii are clamped to fit within `h`.
//
// Built as a SINGLE rotate_extrude of the full half-section profile (axis
// → bottom rim → wall → top rim → axis). The old version revolved each
// rim torus separately and trimmed it with a difference(), then unioned
// in two fill cylinders — a stack of 3D booleans whose cost scales with
// $fn. One rotate_extrude of one polygon has zero 3D booleans and yields
// the same solid. (Same "single op over stacked booleans" theme as the
// boxes — though here it's a wash on the Manifold
// backend, not a speedup; the win is clarity.)
// CAVEAT — a BARE rounded_cylinder is not watertight. The revolved profile touches
// the axis (x = 0) at both ends, and that degenerate pole fan survives into the STL:
// `check.py` on a piece that is *only* this module reports watertight=NO (verified;
// `rotate_extrude` of a profile starting at x=0.001 instead reports yes). In practice
// it is harmless — union it with any other body and the mesh is re-meshed and passes —
// but do not use it alone as a deliverable without checking. Radii are clamped to h
// and to d/2, so an oversized r no longer throws "children may not lie across the Y axis".
//
// DO NOT "fix" this by unioning a fill body over the axis. It was tried and measured:
// a fill makes the BARE cylinder watertight and simultaneously breaks the unioned
// case — plate + rounded_cylinder went watertight=yes -> NO, including with no rim at
// all. That trade is backwards, because unioned (a post on a plate, a boss on a wall)
// is the common case and bare is the rare one. Two things surfaced while measuring,
// worth knowing before trying again:
//   · The failure tracks the rim radius VALUE, not the geometry: with a fill present,
//     binary-exact radii (0.25, 0.5, 1, 3) pass and inexact ones (0.1, 0.3, 0.6, 1.2)
//     fail, at every d, h and $fn.
//   · What actually degenerates is a fill whose radius EQUALS the end-face radius: the
//     two coplanar caps then share a boundary circle. Reproduced with hand-written
//     geometry and no library: fill r = 10-0.6 fails, r = 9.0 on the same profile passes.
// If you do reopen this, the acceptance criterion is BOTH cases — bare and unioned into
// a larger body — not just the one in front of you.
module rounded_cylinder(d, h, r = 0, tr = undef, br = undef,
                        bevel = false, bevel_top = undef, bevel_bottom = undef,
                        fn = $fn) {

  // r is the shared radius default; tr/br override per end. undef inherits
  // r, any number (incl. 0) wins — so tr=0 / br=0 force a sharp rim.
  aux_tr = is_undef(tr) ? r : tr;
  aux_br = is_undef(br) ? r : br;

  // bevel is the shared style default; bevel_top/bevel_bottom override per
  // end the same way (undef inherits bevel, explicit true/false wins).
  bev_t = is_undef(bevel_top)    ? bevel : bevel_top;
  bev_b = is_undef(bevel_bottom) ? bevel : bevel_bottom;

  top_radius = min(aux_tr, h, d / 2);
  bottom_radius = max(min(h - top_radius, aux_br, d / 2), 0);

  R = d / 2;

  // Quarter-arc as a point list, center (cx,cz), sweeping a0→a1 degrees.
  function arc_pts(cx, cz, rad, a0, a1, n) =
    [ for (i = [0 : n]) let (a = a0 + (a1 - a0) * i / n)
        [cx + rad * cos(a), cz + rad * sin(a)] ];

  steps = max(1, round(fn / 4));

  // Each outer corner: sharp (1 pt), chamfer (2 pts), or round (arc).
  bottom_corner =
    bottom_radius <= 0 ? [[R, -h / 2]]
    : bev_b            ? [[R - bottom_radius, -h / 2], [R, -h / 2 + bottom_radius]]
    :                    arc_pts(R - bottom_radius, -h / 2 + bottom_radius, bottom_radius, -90, 0, steps);

  top_corner =
    top_radius <= 0 ? [[R, h / 2]]
    : bev_t         ? [[R, h / 2 - top_radius], [R - top_radius, h / 2]]
    :                 arc_pts(R - top_radius, h / 2 - top_radius, top_radius, 0, 90, steps);

  profile = concat([[0, -h / 2]], bottom_corner, top_corner, [[0, h / 2]]);

  rotate_extrude(angle = 360, $fn = fn)
    polygon(profile);
}

// DEPRECATED — back-compat shim for the pre-refactor interface, where
// tr/br used 0 (not undef) to mean "inherit r", and bevel == 1 chamfered
// only the TOP rim (the bottom stayed rounded). Translates faithfully to
// rounded_cylinder(). New code should call rounded_cylinder() directly.
module rounded_cylinder_legacy(d, h, r = 0, tr = 0, br = 0, bevel = 0) {
  rounded_cylinder(d, h, r = r,
                   tr = tr > 0 ? tr : undef,
                   br = br > 0 ? br : undef,
                   bevel_top = (bevel == 1),   // old: bevel=1 → top chamfer
                   bevel_bottom = false);      // old: bottom always rounded
}

///////////////////////////////////////////////////////////////////////////
// Demo — renders only when this file is opened directly.

rounded_cube(x=10, y=10, z=10, r=2, fn=32);

translate([15, 0, 0])
  rounded_flat_cube(x=10, y=10, z=5, r=2.5, fn=32);

translate([0, 15, 0])
  rounded_flat_cube(x=10, y=5, z=5, r=2.5, fn=32);

translate([0, -15, 0])
  rounded_flat_cube_x(x=20, y=10, z=8, r=2.5, fn=32);

translate([-20, -15, 0])
  rounded_flat_cube_y(x=15, y=10, z=8, r=2.5, fn=32);

// rounded_cylinder variants (rim radius is on the OUTER edge):
translate([-18, 0, 0])              // both rims rounded
  rounded_cylinder(d=10, h=10, r=2, fn=32);

translate([-18, 15, 0])            // per-end: fat top fillet, small bottom
  rounded_cylinder(d=10, h=10, tr=3.5, br=1, fn=32);

translate([15, 15, 0])             // both rims chamfered (beveled)
  rounded_cylinder(d=10, h=10, r=2.5, bevel=true, fn=32);

translate([32, 15, 0])             // sharp top (tr=0), rounded bottom — override beats r
  rounded_cylinder(d=10, h=10, r=2.5, tr=0, fn=32);

translate([32, 0, 0])              // mixed style: chamfer top, round bottom
  rounded_cylinder(d=10, h=10, r=2.5, bevel_top=true, fn=32);
