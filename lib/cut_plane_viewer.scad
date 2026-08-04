// ============================================================
//  cut_plane_viewer — interactive cut-plane viewer for the OpenSCAD GUI.
//
//  cut_plane_view(axis, pos, show) wraps a part and shows a section plane at
//  axis = pos four ways, so you sweep CUT_POS in the Customizer and read where
//  / how the plane cuts:
//    "off"   — just the part, no plane (the clean default view: this is why it can
//              live at the end of a main.scad without changing its default render).
//    "plane" — part + a translucent red plane at pos (WHERE it cuts).
//    "cut"   — part clipped at the plane (half-space): the cross-section in 3D,
//              in place (a cutaway view).
//    "slice" — the TRUE 2D cross-section, extruded thin and placed back ON the
//              cut plane (in situ): the clean outline, where it actually cuts.
//
//  Self-contained (no `use`/`include`): the 2D section uses the slice.scad
//  projection convention INLINE (z: img=XY · x: img=Y,Z · y: img=X,Z; det +1,
//  no mirror). So tools/make_assembly.py can either `use <cut_plane_viewer.scad>`
//  (in-repo project files) or copy these module defs verbatim into a portable,
//  dependency-free stl_assembly.scad — ONE source either way.
//
//  Inspection-only geometry (never part of a printed piece). It lives in lib/
//  because it is reusable .scad consumed by the main.scad front doors, even
//  though it is not a geometric primitive (see lib/CLAUDE.md). Drive it from a
//  Customizer file; never `include` (it would leak the
//  self-preview). The block between the first `module` and the Self-preview line
//  is what make_assembly inlines, so keep all state in module defaults (no
//  top-level constants there).
// ============================================================
module cut_plane_view(axis = "x", pos = 0, show = "off", plane_size = 300) {
    if (show == "off") children();
    else if (show == "cut") intersection() { children(); _cpv_half(axis, pos); }
    else if (show == "slice") _cpv_slice(axis, pos) children();
    else { children(); color([0.85, 0.10, 0.10, 0.33]) _cpv_plane(axis, pos, plane_size); }
}
module _cpv_plane(axis, pos, s = 300, th = 0.6) {
    if (axis == "x")      translate([pos, 0, 0]) cube([th, s, s], center = true);
    else if (axis == "y") translate([0, pos, 0]) cube([s, th, s], center = true);
    else                  translate([0, 0, pos]) cube([s, s, th], center = true);
}
module _cpv_half(axis, pos, b = 1000) {
    if (axis == "x")      translate([pos - b, -b/2, -b/2]) cube(b);
    else if (axis == "y") translate([-b/2, pos - b, -b/2]) cube(b);
    else                  translate([-b/2, -b/2, pos - b]) cube(b);
}
module _cpv_section(axis, pos) {
    if (axis == "z") projection(cut = true) translate([0, 0, -pos]) children();
    else if (axis == "x") projection(cut = true)
        multmatrix([[0,1,0,0],[0,0,1,0],[1,0,0,-pos],[0,0,0,1]]) children();
    else projection(cut = true)
        multmatrix([[1,0,0,0],[0,0,1,0],[0,-1,0,pos],[0,0,0,1]]) children();
}
module _cpv_slice(axis, pos, th = 0.6) {
    if (axis == "z") translate([0,0,pos])
        linear_extrude(th, center=true) _cpv_section("z", pos) children();
    else if (axis == "x") translate([pos,0,0]) rotate([90,0,90])
        linear_extrude(th, center=true) _cpv_section("x", pos) children();
    else translate([0,pos,0]) rotate([90,0,0])
        linear_extrude(th, center=true) _cpv_section("y", pos) children();
}

// ---------- Self-preview (top-level; `use <...>` ignores it — never `include`) ----------
$fn = 48;
cut_plane_view("x", 4, "cut") difference() { cube(30, center = true); sphere(18); }
