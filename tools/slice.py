#!/usr/bin/env python3
"""
slice — the cross-section primitive. Cut a part (a .scad front door or a single
.stl) at a plane and emit everything readable about that section:

  <base>_preview.png  3D part(s) + the translucent cut plane (WHERE it cuts), iso
  <base>_plot.png     dimensioned section: footprint, holes (Ø/SLOT/RECT/POLY),
                      fillets (R), chamfers/bevels (angle), per-face clearances;
                      one colour per piece
  console + <base>_features.txt   the SAME measures, numerically (grep-friendly)
  <base>_poly.txt     one line per polygon (KIND piece= role= … pts=[[x,y],…]) so
                      the LLM greps the contour it wants and pastes it into a
                      polygon()/linear_extrude()
  <base>_section.svg  (--svg) the section, one Inkscape layer per piece

Input rules:
  - a .scad → its modules (one STL each, baked + combined, multi-colour). Choose
    with --parts a,b,…; one name = one piece, several = a multi-colour fit.
    Default (no --parts) = all *_solid, else the file's top level.
  - ONE .stl → a single (one-colour) piece.
  - SEVERAL .stl → refused: build an assembly.scad first (with Customizers for
    each piece's pose), because slice will not guess the assembly transform.

By default it writes preview + plot + poly (the numeric readout always prints);
--svg adds the SVG, --only limits the FILE artifacts. If --only hides features, a
reminder lists what else was detected, so the LLM remembers to look.

Usage:
    uv run tools/slice.py part.stl z=3.1
    uv run tools/slice.py main.scad z=20 --parts plate_seated,peg_seated
    uv run tools/slice.py main.scad z=20,x=5 --parts lid_solid --only plot,poly
    uv run tools/slice.py part.stl y=0 --svg
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np

from _common import build_dir, locate_openscad, render_module
from _geom import (AXES, arc_segments, classify, dim_h, dim_v,
                   face_projection, face_section, segment_contour)

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# OpenSCAD CSS colours per piece (preview) + a softer matched pair for the plot.
PALETTE = ["gold", "red", "steelblue", "green", "orange", "purple", "cyan"]
PLOT_FILL = ["#8FB0D9", "#E3A07A", "#8FC2A0", "#E0C683", "#B79BD0", "#7FC4CC", "#E29CC0"]
PLOT_EDGE = ["#3F6FA3", "#B5673C", "#43855E", "#9C8030", "#6E4F95", "#357E88", "#A85676"]
ISO_CAM = "0,0,0,55,0,25,100"            # rot triple for the iso preview
PLANE_RE = re.compile(r"^([xyz])=(-?\d+(?:\.\d+)?)$")
SOLID_RE = re.compile(r"^\s*module\s+(\w+_solid)\b", re.M)
ALL_OUTPUTS = ("preview", "plot", "poly", "svg", "dxf")
# Named CENTRAL sections (cut through the part centre), one per orthographic plane:
# top = plan (⊥z), front = front elevation (⊥y), side = side elevation (⊥x).
NAMED_PLANES = {"top": 2, "front": 1, "side": 0}


def parse_plane(tok):
    """A plane spec -> (axis, pos|None, label). `pos=None` means 'centre' (resolved to
    the bbox midpoint once the mesh is loaded). Accepts `z=3.1` and the named central
    sections `top`/`front`/`side`. Returns None if `tok` is not a plane spec."""
    tok = tok.strip()
    if tok in NAMED_PLANES:
        return (NAMED_PLANES[tok], None, tok)
    m = PLANE_RE.match(tok)
    if m:
        return (AXES.index(m.group(1)), float(m.group(2)), f"{m.group(1)}{float(m.group(2)):g}")
    return None


# ----------------------------------------------------------------------------- input

def discover_solids(scad: Path) -> list[str]:
    seen: list[str] = []
    for m in SOLID_RE.findall(scad.read_text()):
        if m not in seen:
            seen.append(m)
    return seen


def _render_union(openscad, scad, mods, stl, fn):
    """Render several modules of `scad` unioned into ONE STL (one fused piece) via a
    throwaway `use <scad>; m1(); m2(); …`."""
    body = (f"use <{scad.resolve().as_posix()}>\n$fn={fn};\n"
            + "".join(f"{m}();\n" for m in mods))
    with tempfile.NamedTemporaryFile("w", suffix=".scad", delete=False) as f:
        f.write(body)
        tw = Path(f.name)
    try:
        subprocess.run([openscad, "-o", str(stl), str(tw)], capture_output=True, text=True)
    finally:
        tw.unlink(missing_ok=True)


def resolve_pieces(inputs, parts, fn, openscad, build, fuse=False):
    """Return [(name, stl_path), ...]. A single .stl -> one piece; a .scad ->
    one STL per chosen module (rendered to build/), or ONE fused STL with --fuse.
    Several .stl -> error."""
    stls = [p for p in inputs if p.suffix.lower() == ".stl"]
    scads = [p for p in inputs if p.suffix.lower() == ".scad"]
    if len(stls) > 1 or (stls and scads):
        sys.exit("multiple STLs: slice does not guess the assembly. Create an assembly.scad "
                 "(e.g. with make_assembly, with per-piece pose Customizers) and "
                 "pass it as the .scad input.")
    if stls:
        return [(stls[0].stem, stls[0])]      # a single STL is already one piece
    if not scads:
        sys.exit("missing a .scad or .stl input")
    scad = scads[0]
    if parts:
        mods = parts
    else:
        mods = discover_solids(scad) or [None]      # None -> render top level
    if fuse:
        named = [m for m in mods if m]
        if not named:
            sys.exit(f"{scad.name}: --fuse needs named modules to fuse "
                     f"(no *_solid; name them with --parts)")
        stl = build / f"{scad.stem}__slice_fused.stl"
        _render_union(openscad, scad, named, stl, fn)
        if not (stl.exists() and stl.stat().st_size):
            sys.exit(f"{scad.name}: the fusion yielded no geometry")
        return [(scad.stem, stl)]                    # one piece, one colour, no gaps
    pieces = []
    for mod in mods:
        stl = build / f"{scad.stem}__slice_{mod or 'top'}.stl"
        if mod:
            render_module(openscad, scad, mod, stl, fn=fn)
        else:
            subprocess.run([openscad, "-o", str(stl), "-D", f"$fn={fn}", str(scad)],
                           capture_output=True, text=True)
        if stl.exists() and stl.stat().st_size:
            pieces.append((mod or scad.stem, stl))
        else:
            print(f"  (warning: '{mod}' yielded no geometry)")
    if not pieces:
        sys.exit(f"{scad.name}: nothing to section (right module? try --parts)")
    return pieces


# ----------------------------------------------------------------------------- geometry

def load_meshes(pieces):
    """[(name, stl)] -> [(name, trimesh mesh)], loaded ONCE (so a sweep doesn't
    reload per section). The only direct trimesh contact; everything downstream
    works on these handles via face_section."""
    import trimesh
    return [(name, trimesh.load(str(stl), process=True)) for name, stl in pieces]


def section_loaded(meshes, ai, pos, quiet=False):
    """Section pre-loaded meshes at axis ai = pos. Returns (secs, ua, va, fp, diag)
    or None if no piece crosses the plane. `quiet` silences the per-plane notes (a
    dense sweep must not print per level)."""
    secs, allpts = [], []
    for i, (name, m) in enumerate(meshes):
        sec = face_section(m, ai, pos)
        if sec is None:
            if not quiet:
                print(f"  (empty section for '{name}' at {AXES[ai]}={pos})")
            continue
        if not quiet and abs(sec["cut"] - pos) > 1e-9:   # nudged off a coplanar face (safe_cut)
            print(f"  ⓘ {AXES[ai]}={pos} lands on a coplanar face of '{name}'; "
                  f"sectioned at {AXES[ai]}={sec['cut']:.4f} to avoid degeneracy")
        secs.append((name, sec, PLOT_FILL[i % len(PLOT_FILL)], PLOT_EDGE[i % len(PLOT_EDGE)]))
        allpts.append(np.vstack(sec["contours"]))
    if not secs:
        return None
    ua, va = secs[0][1]["ua"], secs[0][1]["va"]
    pts = np.vstack(allpts)
    fp = (pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max())
    diag = max(fp[1] - fp[0], fp[3] - fp[2])
    return secs, ua, va, fp, diag


def section_pieces(pieces, ai, pos):
    """Section each piece (from STL paths) at axis ai = pos — loads then sections."""
    return section_loaded(load_meshes(pieces), ai, pos)


def projection_loaded(meshes, ti):
    """Project pre-loaded meshes ALONG axis ti (the silhouette). Same (secs, ua, va, fp, diag)
    shape as section_loaded, so the whole downstream is identical — just face_projection per piece."""
    secs, allpts = [], []
    for i, (name, m) in enumerate(meshes):
        sec = face_projection(m, ti)
        if sec is None:
            print(f"  (empty projection for '{name}' along {AXES[ti]})")
            continue
        secs.append((name, sec, PLOT_FILL[i % len(PLOT_FILL)], PLOT_EDGE[i % len(PLOT_EDGE)]))
        allpts.append(np.vstack(sec["contours"]))
    if not secs:
        return None
    ua, va = secs[0][1]["ua"], secs[0][1]["va"]
    pts = np.vstack(allpts)
    fp = (pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max())
    diag = max(fp[1] - fp[0], fp[3] - fp[2])
    return secs, ua, va, fp, diag


def piece_geom(sec):
    """shapely (Multi)Polygon of a piece's section (exterior contours, holes cut)."""
    import shapely.geometry as sg
    from shapely.ops import unary_union
    polys = [sg.Polygon(c) for c in sec["contours"]]
    holes = [sg.Polygon(r) for r in sec["hole_rings"]]
    g = unary_union(polys)
    if holes:
        g = g.difference(unary_union(holes))
    return g


def face_gaps(secs, ua, va, diag):
    """Per-pair, per-face minimum clearance between facing pieces. Returns
    [(nameA, nameB, face, dist, (px,py), (qx,qy)), ...]. Face ∈ {+u,-u,+v,-v}
    (u=first plane axis, v=second). Skips touching (<0.05mm) and far (> diag/2)."""
    from itertools import combinations
    geoms = [(n, piece_geom(s)) for n, s, _, _ in secs]
    out, gapmax = [], 0.5 * diag
    for (na, ga), (nb, gb) in combinations(geoms, 2):
        if ga.intersects(gb) and ga.intersection(gb).area > 1e-6:
            continue                                  # overlap/nested -> no clearance
        ba, bb = ga.boundary, gb.boundary
        best = {}
        for t in np.linspace(0, 1, max(200, int(ba.length / 0.5)), endpoint=False):
            p = ba.interpolate(t, normalized=True)
            q = bb.interpolate(bb.project(p))
            d = p.distance(q)
            if d < 0.05 or d > gapmax:
                continue
            dx, dy = q.x - p.x, q.y - p.y
            face = ("+u" if dx > 0 else "-u") if abs(dx) >= abs(dy) else ("+v" if dy > 0 else "-v")
            if face not in best or d < best[face][0]:
                best[face] = (d, (p.x, p.y), (q.x, q.y))
        for face, (d, pp, qq) in best.items():
            out.append((na, nb, face, d, pp, qq))
    return out


def piece_polys(name, sec, diag):
    """Canonical polygon list for one piece, each with a STABLE `id` — the join key
    shared by _features.txt (shape + bbox, no points) and _poly.txt (the points), so
    you read a shape in features and `grep id=<that id>` its points in poly. Every
    contour is an outline (`o#`) unless it is a small POSITIVE island (`i#`, e.g. a
    post/boss — classified by SHAPE because a coarse cylinder is a faceted polygon
    that per-point arc detection misses); every hole ring is a hole (`h#`)."""
    import shapely.geometry as sg
    multi = len(sec["contours"]) > 1
    polys, no, ni, nh = [], 0, 0, 0

    def rec(tag, n, kind, role, pts, detail):
        a = np.asarray(pts)
        bbox = (a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max())
        return dict(id=f"{name}:{tag}{n}", kind=kind, role=role, pts=a, detail=detail,
                    bbox=bbox, center=((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2))

    for c in sec["contours"]:
        w, h = c[:, 0].max() - c[:, 0].min(), c[:, 1].max() - c[:, 1].min()
        if multi and max(w, h) < 0.3 * diag:
            label, detail = classify(sg.Polygon(c), w, h)
            polys.append(rec("i", ni, label, "island", c, detail)); ni += 1
        else:
            polys.append(rec("o", no, "OUTLINE", "outline", c, None)); no += 1
    for ring, (label, _ca, _cb, detail) in zip(sec["hole_rings"], sec["holes"]):
        polys.append(rec("h", nh, label, "hole", ring, detail)); nh += 1
    return polys


def collect_features(secs, diag):
    """Per piece: the canonical polygon list (`polys`, with ids) + the sub-features
    of each outline — fillets (arcs) and chamfers (angled straight runs), each TAGGED
    with the id of the outline it lies on (a fillet is not its own polygon). `holes`
    and `islands` are the classified polygons, measured at their OWN scale."""
    feats = {}
    for name, sec, _, _ in secs:
        polys = piece_polys(name, sec, diag)
        fillets, chamfers = [], []
        for p in polys:
            if p["role"] != "outline":
                continue
            cdiag = max(p["bbox"][2] - p["bbox"][0], p["bbox"][3] - p["bbox"][1], 1e-6)
            fillets += [(p["id"], *seg) for seg in arc_segments(p["pts"], cdiag)]
            chamfers += [(p["id"], *seg) for seg in segment_contour(p["pts"], cdiag)]
        feats[name] = dict(
            polys=polys, fillets=fillets, chamfers=chamfers,
            holes=[p for p in polys if p["role"] == "hole"],
            islands=[p for p in polys if p["role"] == "island"])
    return feats


# ----------------------------------------------------------------------------- outputs

def emit_numeric(input_name, ai, pos, secs, feats, gaps, ua, va, label=None):
    """Structured, grep-friendly numeric readout to stdout (and the caller may
    also write it to _features.txt). `label` overrides the `axis=pos` header (e.g. a projection)."""
    def bb(p):                                   # bbox as [umin,vmin,umax,vmax]
        x0, y0, x1, y1 = p["bbox"]
        return f"bbox=[{x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}]"

    where = label if label is not None else f"{AXES[ai]}={pos}"
    lines = [f"# slice {input_name}  {where}  (plane {AXES[ua]}{AXES[va]})",
             f"# id is the JOIN KEY: read a shape here, then grep id=<id> in _poly.txt for its points"]
    for name, sec, _, _ in secs:
        amin, amax, bmin, bmax = sec["fp"]
        f = feats[name]
        lines.append(f"PIECE {name}  footprint {AXES[ua]}[{amin:.2f},{amax:.2f}] "
                     f"{AXES[va]}[{bmin:.2f},{bmax:.2f}] = {amax-amin:.2f}x{bmax-bmin:.2f}  "
                     f"contours={len(sec['contours'])} holes={len(f['holes'])} "
                     f"islands={len(f['islands'])} fillets={len(f['fillets'])} "
                     f"chamfers={len(f['chamfers'])}")
        for p in f["polys"]:
            if p["role"] == "outline":
                lines.append(f"  OUTLINE id={p['id']}  {bb(p)} n={len(p['pts'])}")
        for p in sorted(f["holes"], key=lambda q: -q["center"][1]):
            cx, cy = p["center"]
            lines.append(f"  HOLE   id={p['id']} {p['kind']:6} "
                         f"center=({cx:.2f},{cy:.2f}) {bb(p)}  {p['detail']}")
        for p in f["islands"]:
            cx, cy = p["center"]
            lines.append(f"  ISLAND id={p['id']} {p['kind']:6} "
                         f"center=({cx:.2f},{cy:.2f}) {bb(p)}  {p['detail']}")
        for oid, cx, cy, r, span in f["fillets"]:
            lines.append(f"  FILLET on={oid} R={r:.2f} "
                         f"center=({cx:.2f},{cy:.2f}) span={span:.0f}deg")
        for oid, x0, y0, x1, y1, ang in f["chamfers"]:
            lines.append(f"  CHAMFER on={oid} angle={ang:.1f}deg "
                         f"from=({x0:.2f},{y0:.2f}) to=({x1:.2f},{y1:.2f})")
    fmap = {"+u": f"+{AXES[ua]}", "-u": f"-{AXES[ua]}", "+v": f"+{AXES[va]}", "-v": f"-{AXES[va]}"}
    for na, nb, face, d, _pp, _qq in gaps:
        lines.append(f"  GAP {na}<->{nb} face={fmap[face]} min={d:.2f}mm")
    txt = "\n".join(lines)
    print(txt)
    return txt


def emit_poly(secs, feats):
    """One line per polygon, grep-friendly + paste-ready into polygon()/linear_extrude.
    `id` is the JOIN KEY back to _features.txt (read the shape there, grep its id here).
    KIND id=<id> piece=<n> role=<outline|hole|island> n=<#> bbox=[..] pts=[[x,y],...]"""
    rows = []
    for name, _sec, _, _ in secs:
        for p in feats[name]["polys"]:
            pts = [[round(float(x), 3), round(float(y), 3)] for x, y in p["pts"]]
            x0, y0, x1, y1 = p["bbox"]
            bb = [round(float(x0), 2), round(float(y0), 2),
                  round(float(x1), 2), round(float(y1), 2)]
            compact = "[" + ",".join(f"[{x:g},{y:g}]" for x, y in pts) + "]"
            rows.append(f"{p['kind']} id={p['id']} piece={name} role={p['role']} "
                        f"n={len(pts)} bbox={bb} pts={compact}")
    return "\n".join(rows) + "\n"


def emit_dxf(secs, feats, path):
    """Section as DXF (R12): every contour / hole / island as a closed polyline, one layer per
    piece. Reuses the dxf_smoother writer; same 2D frame as poly/SVG (u horizontal, v vertical,
    e.g. world Y×Z for an x= plane). For CAD/CAM — laser, waterjet, or import as a reference."""
    from dxf_smoother import DXFWriter, Point
    layers = {}
    for name, _sec, _, _ in secs:
        rings = []
        for p in feats[name]["polys"]:
            ring = [Point(float(x), float(y)) for x, y in p["pts"]]
            if len(ring) >= 2 and (ring[0].x != ring[-1].x or ring[0].y != ring[-1].y):
                ring.append(Point(ring[0].x, ring[0].y))   # close the ring
            if len(ring) >= 2:
                rings.append(ring)
        layers[name] = rings
    DXFWriter(path).write(layers)


def emit_svg(secs, feats, fp, ua, va):
    """Section as SVG: one Inkscape layer per piece (exterior + holes as one
    even-odd path), plus a SEPARATE `cotas` layer with the dimensions (footprint
    W×H, hole/island Ø & sizes, fillet R, chamfer angle) — toggle it independently
    of the geometry in Inkscape. CAD y-up -> SVG y-down (flip)."""
    amin, amax, bmin, bmax = fp
    mw = 0.05 * max(amax - amin, bmax - bmin) + 1.0
    W, H = (amax - amin) + 2 * mw, (bmax - bmin) + 2 * mw
    fs = max(2.0, 0.022 * max(W, H))            # text height, scales with the part
    sw = 0.08 * fs                              # cota line/stroke width

    def X(x):
        return x - amin + mw

    def Y(y):
        return bmax - y + mw                    # flip to SVG y-down

    def P(pts):                                 # contour -> SVG path data
        d = ""
        for k, (x, y) in enumerate(pts):
            d += ("M" if k == 0 else "L") + f"{X(x):.3f},{Y(y):.3f}"
        return d + "Z"

    ah, hm, off = 1.3 * fs, 0.5 * fs, 2.6 * fs   # arrowhead size, marker half-size, label offset

    def txt(x, y, s, col, rot=0):
        t = f' transform="rotate({rot} {X(x):.2f} {Y(y):.2f})"' if rot else ""
        return (f'    <text x="{X(x):.2f}" y="{Y(y):.2f}" font-size="{fs:.2f}" '
                f'fill="{col}"{t}>{s}</text>')

    def line(x0, y0, x1, y1, col, arr="", lw=None):   # arr: "", "end", or "both"
        mk = ""
        if arr in ("end", "both"):
            mk += f' marker-end="url(#arr{col[1:]})"'
        if arr == "both":
            mk += f' marker-start="url(#arr{col[1:]})"'
        return (f'    <line x1="{X(x0):.2f}" y1="{Y(y0):.2f}" x2="{X(x1):.2f}" '
                f'y2="{Y(y1):.2f}" stroke="{col}" stroke-width="{lw or sw:.2f}"{mk}/>')

    def mark(x, y, col, diag=False):             # center marker: "+" (hole/fillet) or "x" (island)
        d = 0.707 * hm if diag else 0
        lw = 1.3 * sw
        if diag:
            return (line(x - d, y - d, x + d, y + d, col, lw=lw) + "\n"
                    + line(x - d, y + d, x + d, y - d, col, lw=lw))
        return (line(x - hm, y, x + hm, y, col, lw=lw) + "\n"
                + line(x, y - hm, x, y + hm, col, lw=lw))

    DIM, ARC, CHA = "#c0007a", "#127a12", "#d2691e"   # echo the _plot palette
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
           f'width="{W:.2f}mm" height="{H:.2f}mm" viewBox="0 0 {W:.3f} {H:.3f}">']
    out.append('  <defs>')
    for col in (DIM, ARC, CHA):                  # one arrowhead marker per cota colour
        out.append(f'    <marker id="arr{col[1:]}" viewBox="0 0 10 10" refX="9" refY="5" '
                   f'markerWidth="{ah:.2f}" markerHeight="{ah:.2f}" markerUnits="userSpaceOnUse" '
                   f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    out.append('  </defs>')
    for i, (name, sec, fill, _edge) in enumerate(secs):
        col = PALETTE[i % len(PALETTE)]
        d = " ".join(P(c) for c in sec["contours"]) + " " + \
            " ".join(P(r) for r in sec["hole_rings"])
        out.append(f'  <g inkscape:groupmode="layer" inkscape:label="{name}" id="{name}">')
        out.append(f'    <path d="{d.strip()}" fill="{col}" fill-opacity="0.4" '
                   f'fill-rule="evenodd" stroke="{col}" stroke-width="0.3"/>')
        out.append("  </g>")

    # ---- separate dimensions layer (geometry stays clean; toggle this on/off) ----
    out.append('  <g inkscape:groupmode="layer" inkscape:label="dimensions" id="dimensions">')
    # outer footprint W×H as double-arrow dimension lines, just outside the part
    yb, xl = bmin - 0.45 * mw, amin - 0.45 * mw
    out.append(line(amin, yb, amax, yb, DIM, arr="both"))
    out.append(txt((amin + amax) / 2, yb - 0.3 * fs, f"{amax-amin:.1f}", DIM))
    out.append(line(xl, bmin, xl, bmax, DIM, arr="both"))
    out.append(txt(xl - 0.3 * fs, (bmin + bmax) / 2, f"{bmax-bmin:.1f}", DIM, rot=-90))
    for name, sec, _, _ in secs:
        f = feats[name]
        # holes (+) and islands (x): centre marker + leader arrow -> centre + label
        for role, items in (("hole", f["holes"]), ("island", f["islands"])):
            for p in items:
                ca, cb = p["center"]
                s = "Ø" + p["detail"].split("d=")[1].split()[0] if p["kind"] == "CIRCLE" \
                    else f"{p['kind']} {p['detail'].split('(')[0].strip()}"
                out.append(mark(ca, cb, DIM, diag=(role == "island")))
                out.append(line(ca + off, cb + off, ca, cb, DIM, arr="end"))
                out.append(txt(ca + off, cb + off, s, DIM))
        for _oid, cx, cy, r, _span in f["fillets"]:
            out.append(mark(cx, cy, ARC))
            out.append(txt(cx + 0.6 * fs, cy, f"R{r:.1f}", ARC))
        for _oid, x0, y0, x1, y1, ang in f["chamfers"]:
            out.append(line(x0, y0, x1, y1, CHA, lw=2.0 * sw))
            out.append(txt((x0 + x1) / 2, (y0 + y1) / 2, f"{ang:.0f}°", CHA))
    out.append("  </g>")
    out.append("</svg>\n")
    return "\n".join(out)


def _oriented(ring, ccw):
    """Close `ring` and wind it CCW (exterior) or CW (hole). Filling a piece as ONE
    compound path with CW holes leaves the holes TRANSPARENT under matplotlib's
    nonzero rule — so a hole never paints over another piece drawn beneath it."""
    a = np.asarray(ring, float)
    if not np.allclose(a[0], a[-1]):
        a = np.vstack([a, a[0]])
    twice_area = np.sum(a[:-1, 0] * a[1:, 1] - a[1:, 0] * a[:-1, 1])
    return a[::-1] if (twice_area > 0) != ccw else a


def emit_plot(out_png, input_name, ai, pos, secs, feats, gaps, fp, ua, va, diag, frame=None, title=None):
    """Dimensioned section plot. By default the axes autoscale to THIS section's
    footprint and the canvas is cropped tight. Pass `frame=(umin,umax,vmin,vmax)`
    (world extent in the plane axes) for a FIXED frame + fixed canvas — every level
    of a sweep then lands on the same pixel grid (slice_viewer's tomography), so a
    feature stays put as you scrub. In framed mode the outer footprint cotas are
    dropped (they need room outside the part)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, PathPatch
    from matplotlib.path import Path as MPath
    amin, amax, bmin, bmax = fp
    pad = 0.08 * diag
    fig, ax = plt.subplots(figsize=(8, 7))

    for name, sec, fill, edge in secs:
        # fill the piece as ONE compound path (exterior CCW, holes CW) so the holes
        # are TRANSPARENT — a hole must never paint white over a piece beneath it.
        verts, codes = [], []
        for ring, ccw in ([(c, True) for c in sec["contours"]]
                          + [(r, False) for r in sec["hole_rings"]]):
            a = _oriented(ring, ccw)
            verts.extend(a)
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(a) - 2) + [MPath.CLOSEPOLY]
        if verts:
            ax.add_patch(PathPatch(MPath(verts, codes), facecolor=fill,
                                   edgecolor="none", alpha=0.45))
        for c in sec["contours"]:
            ax.plot(c[:, 0], c[:, 1], "-", lw=1.4, color=edge)
        for r in sec["hole_rings"]:
            ax.plot(r[:, 0], r[:, 1], "-", lw=1.1, color="crimson")

    if frame is None:
        dim_h(ax, amin, amax, bmin, -2.1 * pad, f"{amax-amin:.1f}")
        dim_v(ax, bmin, bmax, amin, -2.1 * pad, f"{bmax-bmin:.1f}")

    def tag_of(p):
        return ("Ø" + p["detail"].split("d=")[1].split(" ")[0]) if p["kind"] == "CIRCLE" \
            else f"{p['kind']} {p['detail'].split('  ')[0]}"

    for name in feats:
        f = feats[name]
        for p in f["holes"]:
            ca, cb = p["center"]
            ax.plot([ca], [cb], "+", color="crimson", ms=9, mew=1.5)
            ax.annotate(tag_of(p), xy=(ca, cb), xytext=(ca + pad, cb + pad), fontsize=8,
                        color="crimson",
                        arrowprops=dict(arrowstyle="->", color="crimson", lw=1))
        for _oid, cx, cy, r, span in f["fillets"]:
            ax.plot([cx], [cy], "+", color="darkgreen", ms=8, mew=1.4)
            ax.text(cx, cy, f" R{r:.1f}", color="darkgreen", fontsize=8, va="center")
        for p in f["islands"]:
            ca, cb = p["center"]
            ax.plot([ca], [cb], "x", color="navy", ms=8, mew=1.6)
            ax.text(ca, cb, f" {tag_of(p)}", color="navy", fontsize=8, va="center")
        for _oid, x0, y0, x1, y1, ang in f["chamfers"]:
            ax.plot([x0, x1], [y0, y1], "-", color="darkorange", lw=2.4, alpha=0.8)
            ax.text((x0 + x1) / 2, (y0 + y1) / 2, f"{ang:.0f}°", color="darkorange",
                    fontsize=8, fontweight="bold")

    fmap = {"+u": f"+{AXES[ua]}", "-u": f"-{AXES[ua]}", "+v": f"+{AXES[va]}", "-v": f"-{AXES[va]}"}
    for na, nb, face, d, pp, qq in gaps:
        mx, my = (pp[0] + qq[0]) / 2, (pp[1] + qq[1]) / 2
        ax.plot([pp[0], qq[0]], [pp[1], qq[1]], "-", color="magenta", lw=1)
        ax.plot([mx], [my], "o", color="magenta", ms=5)
        ax.text(mx, my, f" {d:.2f}", color="magenta", fontsize=8, fontweight="bold")

    ax.set_aspect("equal"); ax.grid(True, alpha=0.3)
    if frame is not None:
        fx0, fx1, fy0, fy1 = frame
        fm = 0.06 * max(fx1 - fx0, fy1 - fy0, 1e-6)
        ax.set_xlim(fx0 - fm, fx1 + fm); ax.set_ylim(fy0 - fm, fy1 + fm)
    else:
        ax.set_xlim(amin - 3.0 * pad, amax + 1.4 * pad)
        ax.set_ylim(bmin - 3.0 * pad, bmax + 1.4 * pad)
    ax.set_xlabel(f"{AXES[ua]} (mm)"); ax.set_ylabel(f"{AXES[va]} (mm)")
    ax.set_title(title if title is not None else f"{input_name} — {AXES[ai]}={pos:g}")
    if frame is not None:
        # fixed layout (constant canvas) reserving room at the right, so a
        # multi-piece legend sits OUTSIDE the plot — never over the part
        fig.subplots_adjust(left=0.10, right=0.84, top=0.92, bottom=0.10)
    if len(secs) > 1:                                  # legend OUTSIDE the data area, top-right
        ax.legend(handles=[Patch(facecolor=fill, edgecolor=edge, label=name)
                           for name, _s, fill, edge in secs],
                  loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=8)
    if frame is not None:
        fig.savefig(str(out_png), dpi=140); plt.close(fig)     # fixed canvas → same pixel grid
    else:
        fig.tight_layout()
        fig.savefig(str(out_png), dpi=140, bbox_inches="tight"); plt.close(fig)


def emit_preview(out_png, pieces, ai, pos, openscad, fn, size):
    """3D render: pieces (coloured) + a thin translucent red plane at axis=pos, iso.
    Bounds (camera framing) come from the pieces' own STLs, computed below."""
    import trimesh
    los, his = [], []
    body = [f"$fn={fn};"]
    for i, (name, stl) in enumerate(pieces):
        col = PALETTE[i % len(PALETTE)]
        body.append(f'color("{col}") import("{Path(stl).resolve().as_posix()}", convexity=10);')
        b = trimesh.load(str(stl), process=False).bounds
        los.append(b[0]); his.append(b[1])
    lo = np.min(los, 0); hi = np.max(his, 0)
    ext = (hi - lo) * 1.3
    ctr = (lo + hi) / 2
    dims = list(ext); c = list(ctr)
    dims[ai], c[ai] = 0.4, pos                  # thin plane at the cut
    body.append(f"color([0.85,0.10,0.10,0.32]) translate([{c[0]:.3f},{c[1]:.3f},{c[2]:.3f}]) "
                f"cube([{dims[0]:.3f},{dims[1]:.3f},{dims[2]:.3f}], center=true);")
    with tempfile.NamedTemporaryFile("w", suffix=".scad", delete=False) as f:
        f.write("\n".join(body) + "\n")
        tmp = Path(f.name)
    try:
        subprocess.run([openscad, "-o", str(out_png), f"--imgsize={size},{size}",
                        "--projection=ortho", "--viewall", "--autocenter",
                        f"--camera={ISO_CAM}", str(tmp)], capture_output=True, text=True)
    finally:
        tmp.unlink(missing_ok=True)


# ----------------------------------------------------------------------------- scan

def _shape_json(p):
    """One classified shape (hole/island) as JSON. pts only for POLY (CIRCLE/SLOT/RECT
    are fully described by kind + bbox; an extruded POLY needs its contour)."""
    x0, y0, x1, y1 = p["bbox"]
    cx, cy = p["center"]
    d = {"kind": p["kind"], "c": [round(cx, 3), round(cy, 3)],
         "bbox": [round(float(x0), 3), round(float(y0), 3),
                  round(float(x1), 3), round(float(y1), 3)],
         "detail": p["detail"]}
    if p["kind"] == "POLY":
        d["pts"] = [[round(float(x), 3), round(float(y), 3)] for x, y in p["pts"]]
    return d


def scan_axis_json(in_name, pieces, axes, step, rng=None):
    """Dense sweep along each axis: load the meshes ONCE, section every `step` mm over
    the extent, and return a JSON-serialisable dump of the per-level features (the raw
    data analyze correlates into 3D primitives). Each level carries footprint + holes /
    islands / fillets / chamfers; forward-compatible with per-level preview/plot paths
    for a future GUI viewer. `rng=(a,b)` restricts the sweep to a sub-window (used by
    analyze to refine a transition by bisection-style fine sweep)."""
    meshes = load_meshes(pieces)
    out = {"input": in_name, "step": step, "axes": []}
    for ai in axes:
        if rng is not None:
            lo, hi = float(rng[0]), float(rng[1])
        else:
            lo = float(min(m.bounds[0][ai] for _, m in meshes))
            hi = float(max(m.bounds[1][ai] for _, m in meshes))
        n = max(1, int(math.floor((hi - lo) / step)))
        levels = []
        for k in range(n + 1):
            pos = lo + k * step
            res = section_loaded(meshes, ai, pos, quiet=True)
            if res is None:
                levels.append({"pos": round(pos, 3), "pieces": []})
                continue
            secs, ua, va, _fp, diag = res
            feats = collect_features(secs, diag)
            pj = []
            for name, sec, _, _ in secs:
                f = feats[name]
                a0, a1, b0, b1 = sec["fp"]
                pj.append({
                    "name": name,
                    "footprint": [round(a0, 3), round(a1, 3), round(b0, 3), round(b1, 3)],
                    "holes":   [_shape_json(p) for p in f["holes"]],
                    "islands": [_shape_json(p) for p in f["islands"]],
                    "fillets": [{"c": [round(cx, 3), round(cy, 3)], "r": round(r, 3),
                                 "span": round(span)}
                                for _oid, cx, cy, r, span in f["fillets"]],
                    "chamfers": [{"from": [round(x0, 3), round(y0, 3)],
                                  "to": [round(x1, 3), round(y1, 3)], "ang": round(ang, 1)}
                                 for _oid, x0, y0, x1, y1, ang in f["chamfers"]],
                })
            levels.append({"pos": round(sec["cut"], 3) if len(secs) == 1 else round(pos, 3),
                           "plane": AXES[ua] + AXES[va], "pieces": pj})
        out["axes"].append({"axis": AXES[ai], "extent": [round(lo, 3), round(hi, 3)],
                            "levels": levels})
    return out


# ----------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("args", nargs="+",
                    help="one input (.scad or .stl) + one or more planes axis=pos (e.g. z=3.1)")
    ap.add_argument("--parts", default=None,
                    help="comma list of front-door modules: one = a single piece, several = a "
                         "multi-colour fit (default: all *_solid, else the file's top level)")
    ap.add_argument("--fuse", action="store_true",
                    help="union all chosen modules into ONE piece (one colour, no gaps) "
                         "instead of slicing each separately")
    ap.add_argument("--only", default=None,
                    help="comma subset of " + ",".join(ALL_OUTPUTS) + " (default: all)")
    ap.add_argument("--svg", action="store_true", help="also write the section SVG (layers)")
    ap.add_argument("--dxf", action="store_true",
                    help="also write the section DXF (R12, one layer per piece) for CAD/CAM")
    ap.add_argument("--project", choices=("x", "y", "z"), default=None,
                    help="instead of a plane cut, output the SILHOUETTE projected along this axis "
                         "(the side/edge profile — keeps thickness & standing features)")
    ap.add_argument("--name", default=None,
                    help="output label for the (single) plane, e.g. <stem>_<name>_plot.png "
                         "(used by run_batch to name each manifest line)")
    ap.add_argument("--scan-axis", default=None, metavar="x|y|z|all",
                    help="dense sweep: section every --step along the axis (or all 3) and dump "
                         "per-level features as JSON to stdout (no images). Feeds analyze.py.")
    ap.add_argument("--step", type=float, default=1.0,
                    help="sweep step in mm for --scan-axis (default 1.0)")
    ap.add_argument("--range", default=None, metavar="a,b",
                    help="restrict --scan-axis to the window [a,b] (single axis only)")
    ap.add_argument("--fn", type=int, default=120)
    ap.add_argument("--size", type=int, default=1000)
    ap.add_argument("--openscad", default=None)
    args = ap.parse_args()

    planes, inputs = [], []
    for a in args.args:
        toks = a.split(",")                  # planes: space- OR comma-separated; z=3, top, front, side
        parsed = [parse_plane(t) for t in toks]
        if all(p is not None for p in parsed):
            planes.extend(parsed)
        else:
            inputs.append(Path(a))
    if not inputs:
        sys.exit("missing a .scad or .stl input")
    for p in inputs:
        if not p.exists():
            sys.exit(f"does not exist: {p}")

    openscad = locate_openscad(args.openscad)
    build = build_dir(inputs[0])
    parts = args.parts.split(",") if args.parts else None
    in_name = inputs[0].name
    stem = inputs[0].stem

    if args.scan_axis:                       # dense sweep -> JSON to stdout (no planes needed)
        sel = args.scan_axis.lower()
        axes = [0, 1, 2] if sel == "all" else ([AXES.index(sel)] if sel in AXES else None)
        if axes is None:
            sys.exit("--scan-axis must be x, y, z or all")
        rng = None
        if args.range:
            if len(axes) != 1:
                sys.exit("--range requires a single-axis --scan-axis (x|y|z)")
            try:
                a, b = (float(v) for v in args.range.split(","))
            except ValueError:
                sys.exit("--range must be 'a,b' (e.g. 4,6)")
            rng = (a, b)
        # Intermediate renders are pure scratch (output is JSON to stdout): keep them
        # OUT of build/ in a clearly-named subdir, and delete it when done.
        import shutil
        scratch = build / f"_scan_{stem}"
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            pieces = resolve_pieces(inputs, parts, args.fn, openscad, scratch, fuse=args.fuse)
            print(json.dumps(scan_axis_json(in_name, pieces, axes, args.step, rng)))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return 0

    pieces = resolve_pieces(inputs, parts, args.fn, openscad, build, fuse=args.fuse)

    if args.project:                              # silhouette ALONG an axis (not a plane cut)
        ti = AXES.index(args.project)
        outs = (set(args.only.split(",")) if args.only else set(ALL_OUTPUTS[1:3]))  # plot, poly
        if args.svg: outs.add("svg")
        if args.dxf: outs.add("dxf")
        res = projection_loaded(load_meshes(pieces), ti)
        if res is None:
            sys.exit(f"empty projection along {args.project}")
        secs, ua, va, fp, diag = res
        label, ttl = f"proj{args.project}", (f"{in_name} — projection along {args.project}"
                                             f"  ({AXES[ua]}{AXES[va]} silhouette)")
        base = build / f"{stem}_{label}"
        feats = collect_features(secs, diag)
        txt = emit_numeric(in_name, ti, None, secs, feats, [], ua, va, label=f"proj {args.project}")
        Path(f"{base}_features.txt").write_text(txt + "\n")
        if "poly" in outs:
            Path(f"{base}_poly.txt").write_text(emit_poly(secs, feats)); print(f"poly      {base}_poly.txt")
        if "svg" in outs:
            Path(f"{base}_section.svg").write_text(emit_svg(secs, feats, fp, ua, va)); print(f"svg       {base}_section.svg")
        if "dxf" in outs:
            emit_dxf(secs, feats, f"{base}_section.dxf"); print(f"dxf       {base}_section.dxf")
        if "plot" in outs:
            emit_plot(Path(f"{base}_plot.png"), in_name, ti, None, secs, feats, [], fp, ua, va, diag, title=ttl)
            print(f"plot      {base}_plot.png")
        return 0

    if not planes:
        sys.exit("missing a plane: z=3.1, or a central section top|front|side — or use --scan-axis")
    if args.name:
        if len(planes) != 1:
            sys.exit("--name requires a single plane")
        ai, pos, _ = planes[0]
        planes = [(ai, pos, args.name)]

    outputs = (set(args.only.split(",")) if args.only else set(ALL_OUTPUTS[:3]))
    if args.svg:
        outputs.add("svg")
    if args.dxf:
        outputs.add("dxf")

    meshes = load_meshes(pieces)              # once: section + bbox (centre of top/front/side)
    lo3 = np.min([m.bounds[0] for _, m in meshes], axis=0)
    hi3 = np.max([m.bounds[1] for _, m in meshes], axis=0)

    for ai, pos, label in planes:
        if pos is None:                      # named central section -> bbox midpoint
            pos = float((lo3[ai] + hi3[ai]) / 2)
        base = build / f"{stem}_{label}"
        res = section_loaded(meshes, ai, pos)
        if res is None:
            print(f"# {in_name} {label}: empty section")
            continue
        secs, ua, va, fp, diag = res
        feats = collect_features(secs, diag)
        gaps = face_gaps(secs, ua, va, diag) if len(secs) > 1 else []

        txt = emit_numeric(in_name, ai, pos, secs, feats, gaps, ua, va)
        (Path(f"{base}_features.txt")).write_text(txt + "\n")

        if "poly" in outputs:
            Path(f"{base}_poly.txt").write_text(emit_poly(secs, feats))
            print(f"poly      {base}_poly.txt")
        if "svg" in outputs:
            Path(f"{base}_section.svg").write_text(emit_svg(secs, feats, fp, ua, va))
            print(f"svg       {base}_section.svg")
        if "dxf" in outputs:
            emit_dxf(secs, feats, f"{base}_section.dxf")
            print(f"dxf       {base}_section.dxf")
        if "plot" in outputs:
            emit_plot(Path(f"{base}_plot.png"), in_name, ai, pos, secs, feats, gaps,
                      fp, ua, va, diag)
            print(f"plot      {base}_plot.png")
        if "preview" in outputs:
            emit_preview(Path(f"{base}_preview.png"), pieces, ai, pos, openscad,
                         args.fn, args.size)
            print(f"preview   {base}_preview.png")

        # Reminder: if --only hid outputs, list what else is there to look at.
        if args.only:
            tot = {k: sum(len(feats[n][k]) for n in feats)
                   for k in ("holes", "islands", "fillets", "chamfers")}
            tot["gaps"] = len(gaps)
            extra = ", ".join(f"{v} {k}" for k, v in tot.items() if v)
            if extra:
                print(f"  ⚠ also detected (not all shown with --only): {extra} "
                      f"— run without --only or check _features.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
