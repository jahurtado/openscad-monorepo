#!/usr/bin/env python3
"""
Shared 2D-section geometry — used by slice.py and analyze.py so
the hole/arc/segment detection and dimension-drawing live in ONE place (no
duplication across tools). Pure geometry + matplotlib dim helpers; no CLI, no I/O.

  classify        — name a through-hole from its shape (CIRCLE/SLOT/RECT/POLY)
  arc_segments    — every circular arc of a contour (fillets / rounded corners)
  segment_contour — the ANGLED straight runs of a contour (chamfers / bevels + angle)
  face_section    — section a mesh ⊥ an axis -> contours + classified holes
  fit_circle / _resample / dim_h / dim_v — primitives
"""
from __future__ import annotations

import numpy as np

AXES = "xyz"


def fit_circle(x, y):
    """Algebraic (Kasa) circle fit -> (cx, cy, r)."""
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    b = x ** 2 + y ** 2
    c, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = c[0], c[1]
    r = np.sqrt(c[2] + cx ** 2 + cy ** 2)
    return cx, cy, r


def _resample(pts, n=256):
    """Resample a closed contour to n points at UNIFORM arc-length spacing. A raw
    section mixes dense facets (on arcs) with 2-point straight edges; the uniform
    spacing makes windowed curvature meaningful — straight runs get many zero-
    curvature points, cleanly separated from the arcs (which otherwise merge into
    one bad fit on a coarse contour)."""
    seg = np.hypot(*(np.roll(pts, -1, 0) - pts).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total < 1e-9:
        return pts
    s = np.linspace(0.0, total, n, endpoint=False)
    px = np.interp(s, cum, np.append(pts[:, 0], pts[0, 0]))
    py = np.interp(s, cum, np.append(pts[:, 1], pts[0, 1]))
    return np.column_stack([px, py])


def _curvature(pts, win=2):
    """Windowed curvature (1/R) per point of a resampled closed contour, plus the
    per-vertex turn and segment length. Shared by arc_segments / segment_contour."""
    n = len(pts)
    edge = np.roll(pts, -1, 0) - pts
    seg = np.hypot(edge[:, 0], edge[:, 1])
    ang = np.arctan2(edge[:, 1], edge[:, 0])
    turn = (ang - np.roll(ang, 1) + np.pi) % (2 * np.pi) - np.pi   # turn AT vertex i
    w = np.arange(-win, win + 1)
    cturn = np.array([turn[(i + w) % n].sum() for i in range(n)])
    clen = np.array([seg[(i + w) % n].sum() for i in range(n)]) + 1e-9
    return cturn / clen, turn          # SIGNED curvature (sign = convex / concave)


def _runs(mask):
    """Yield index arrays of consecutive True runs of `mask` over a CLOSED loop
    (rotated to start at a False vertex so a run isn't split across the wrap)."""
    n = len(mask)
    order = np.arange(n) if mask.all() else (np.arange(n) + int(np.argmin(mask))) % n
    lab = mask[order]
    i = 0
    while i < n:
        j = i
        while j < n and lab[j] == lab[i]:
            j += 1
        if lab[i]:
            yield order[i:j]
        i = j


def _sign_runs(sgn):
    """Yield index arrays of maximal runs of CONSTANT NON-ZERO sign over a closed
    loop (0 = straight, ±1 = convex / concave arc). Splitting by sign keeps a
    convex bump and the concave cusp beside it — and any chain of adjacent/repeated
    arcs — as SEPARATE runs, instead of merging them into one un-fittable blob."""
    n = len(sgn)
    zero = np.where(sgn == 0)[0]
    start = int(zero[0]) if len(zero) else 0
    order = (np.arange(n) + start) % n
    s = sgn[order]
    i = 0
    while i < n:
        j = i
        while j < n and s[j] == s[i]:
            j += 1
        if s[i] != 0:
            yield order[i:j]
        i = j


def arc_segments(pts, diag, win=2, min_span_deg=18):
    """Every circular arc of a closed contour `pts` (n,2, world plane) — ANY arc,
    not just 90° corners. Returns [(cx, cy, r, span_deg), ...].

    The contour is resampled to uniform spacing, then windowed curvature labels
    each point arc-vs-straight; consecutive arc points are grouped and each run is
    least-squares circle-fit. An arc counts only if it spans >= min_span_deg, has
    radius >= a small fraction of the footprint, fits tightly, and has ~CONSTANT
    curvature (a polygon corner or strip edge spikes the curvature and is rejected).
    All gates are SCALE/SHAPE-FREE (angles + ratios)."""
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 4:
        return []
    pts = _resample(pts, min(1500, max(256, 3 * len(pts))))   # don't downsample dense contours
    n = len(pts)
    curv, turn = _curvature(pts, win)
    acurv = np.abs(curv)
    sgn = np.where(acurv > 1.0 / diag, np.sign(curv), 0.0)   # convex/concave/straight
    arcs = []
    for idx in _sign_runs(sgn):       # same-sign runs: adjacent/repeated arcs stay separate
        q = pts[np.append(idx, (idx[-1] + 1) % n)]   # include the closing vertex
        if len(q) < 5:
            continue
        cx, cy, r = fit_circle(q[:, 0], q[:, 1])
        span = np.degrees(abs(turn[idx].sum()))
        resid = float(np.abs(np.hypot(q[:, 0] - cx, q[:, 1] - cy) - r).max())
        cr = acurv[idx]
        cv = float(cr.std() / cr.mean()) if cr.mean() > 1e-9 else 9.0
        span_rad = abs(turn[idx].sum())
        conc = float(np.abs(turn[idx]).max() / span_rad) if span_rad > 1e-9 else 9.0
        if (span >= min_span_deg and r >= 0.02 * diag
                and resid <= 0.06 * r and cv <= 0.6 and conc <= 0.6
                and len(idx) >= max(4, span / 20)):
            arcs.append((cx, cy, r, span))
    return arcs


def segment_contour(pts, diag, win=2, line_tol_deg=8, min_len_frac=0.05):
    """The ANGLED STRAIGHT runs of a closed contour — i.e. CHAMFERS / BEVELS (a
    flat edge cut at an angle), which `arc_segments` (curved → fillets) does not
    see and axis-aligned edges (walls) are not. Returns
    [(x0, y0, x1, y1, angle_deg), ...] where angle_deg is the inclination vs the
    nearest axis (0 = axis-aligned, 45 = a classic chamfer).

    Same windowed-curvature segmentation as arc_segments but on the LOW-curvature
    (straight) runs, breaking at corners/arcs; a run whose direction sits more than
    `line_tol_deg` off both axes is an angled edge. Short runs are dropped."""
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 4:
        return []
    pts = _resample(pts, min(1500, max(256, 3 * len(pts))))   # don't downsample dense contours
    n = len(pts)
    curv, _turn = _curvature(pts, win)
    straight = np.abs(curv) <= 1.0 / diag            # complement of the arc mask
    out = []
    minlen = min_len_frac * diag
    for idx in _runs(straight):
        p0, p1 = pts[idx[0]], pts[(idx[-1] + 1) % n]
        if np.hypot(*(p1 - p0)) < minlen:
            continue
        a = np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0])) % 90.0
        acute = min(a, 90.0 - a)                     # 0..45 off the nearest axis
        if acute > line_tol_deg:                     # angled -> chamfer / bevel
            out.append((float(p0[0]), float(p0[1]), float(p1[0]), float(p1[1]),
                        round(acute, 1)))
    return out


def classify(poly, w, h):
    """Name a hole from its section shape. Returns (label, detail-string).

    Three independent ratios, because circularity ALONE confuses an elongated
    RECT with a SLOT (both elongated) and a hex with a CIRCLE (both round-ish):
      circ = 4*pi*A / P^2     -> 1.0 for a circle, ~0.91 hex, lower for corners
      fill = A / (w*h)        -> ~1.0 fills its bbox (RECT), ~0.79 circle, slot between
      aspect = long / short
    A circle is round (circ high). A RECT fills its bbox (fill high). A SLOT is
    elongated with rounded ends (fill between, aspect high). Everything else POLY."""
    long, short = max(w, h), min(w, h)
    aspect = long / short if short > 1e-6 else 999.0
    bbox_area = w * h
    fill = poly.area / bbox_area if bbox_area > 1e-9 else 0.0
    circ = 4 * np.pi * poly.area / (poly.length ** 2) if poly.length else 0.0
    # Corner rounding = area the corners carve out of the bbox, normalized by
    # short^2 -> aspect-INDEPENDENT (fill is NOT: a long thin slot's rounded ends
    # are a negligible fraction of its bbox, so fill stays ~1 and masquerades as
    # RECT). ~0 for sharp corners; ~0.215 (=1-pi/4) for fully rounded ends.
    round_def = (bbox_area - poly.area) / (short ** 2) if short > 1e-6 else 0.0
    if circ >= 0.93:                              # round all over -> circle
        d = 2 * np.sqrt(poly.area / np.pi)
        return "CIRCLE", f"d={d:.2f}  (bbox {w:.2f}x{h:.2f})"
    if aspect >= 1.3 and round_def >= 0.05:       # elongated, rounded ends -> slot
        return "SLOT", f"{long:.2f} x {short:.2f}  end-r={short / 2:.2f}"
    if fill >= 0.95:                              # fills its bbox, sharp -> rectangle
        return "RECT", f"{w:.2f} x {h:.2f}"
    if aspect >= 1.3 and fill >= 0.80:            # elongated (fallback) -> slot
        return "SLOT", f"{long:.2f} x {short:.2f}  end-r={short / 2:.2f}"
    return "POLY", f"{w:.2f} x {h:.2f}  ({len(poly.exterior.coords) - 1} pts)"


def _polygons_full(p2d):
    """Like trimesh's `p2d.polygons_full`, but robust: when a cut grazes coplanar
    faces it spawns near-duplicate concentric loops and trimesh's shell+hole repair
    raises `unable to recover polygon!`. The individual closed loops are still valid,
    so on failure we rebuild the shell/hole tree ourselves by even/odd nesting depth
    (shell = even depth; its holes = loops whose innermost container it is), repairing
    any invalid combination with buffer(0)."""
    try:
        return list(p2d.polygons_full)
    except Exception:
        pass
    closed = sorted((p for p in p2d.polygons_closed if p is not None and p.area > 0),
                    key=lambda p: -p.area)
    # Grazing a coplanar face triples a loop into near-coincident concentric copies
    # (areas within <1%); keeping them spawns phantom thin-ring shells. Drop a loop
    # contained in a larger KEPT one whose area it nearly matches (ratio > 0.99) —
    # scale-free, and a real thin wall (ratio well below 0.99) survives.
    rings = []
    for r in closed:
        if any(k.area * 0.99 < r.area and k.contains(r.representative_point())
               for k in rings):
            continue
        rings.append(r)
    if not rings:
        return []
    # depth[i] = how many rings strictly contain ring i; innermost container = parent.
    pts = [r.representative_point() for r in rings]
    contains = [[j != i and rings[j].area > rings[i].area and rings[j].contains(pts[i])
                 for j in range(len(rings))] for i in range(len(rings))]
    depth = [sum(row) for row in contains]
    out = []
    for i, r in enumerate(rings):
        if depth[i] % 2:                       # odd depth = hole of some shell
            continue
        holes = []
        for j, rj in enumerate(rings):
            if depth[j] == depth[i] + 1 and contains[j][i]:
                # i must be j's INNERMOST container among the shells
                inner = max((k for k in range(len(rings)) if contains[j][k]),
                            key=lambda k: depth[k], default=i)
                if inner == i:
                    holes.append(rj.exterior.coords)
        import shapely.geometry as sg
        poly = sg.Polygon(r.exterior.coords, holes)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            continue
        # buffer(0) may split into a MultiPolygon — keep the parts
        out.extend(getattr(poly, "geoms", [poly]))
    return sorted(out, key=lambda p: -p.area)


def safe_cut(m, ti, cut):
    """A cut that lands EXACTLY on a mesh face perpendicular to the axis (a coplanar
    floor / membrane — e.g. a flat base at z=0) makes trimesh sectioning degenerate:
    it returns duplicate concentric loops and phantom segments (a spurious chamfer,
    broken SVG), while the same cut ±a micron is clean. Detect that coincidence and
    nudge the cut by a geometrically negligible epsilon TOWARD the model centre, so
    the plane slices solid instead of grazing the face. Returns the cut to use."""
    lo, hi = m.bounds[0, ti], m.bounds[1, ti]
    extent = hi - lo
    perp = np.abs(m.face_normals[:, ti]) > 0.999       # faces ⊥ the axis (a flat cap)
    if extent <= 0 or not perp.any():
        return cut
    coords = m.vertices[m.faces[perp][:, 0], ti]       # axis-coord of each such face
    if not np.any(np.abs(coords - cut) <= 1e-6 * max(1.0, extent)):
        return cut
    eps = 1e-3 * extent
    return cut + (eps if 0.5 * (lo + hi) >= cut else -eps)


def face_section(m, ti, cut):
    """Section `m` perpendicular to axis `ti` at world coord `cut`. Returns
    {ua, va, cut, contours, hole_rings, holes, slivers, fp, min_feat, hole_sig} or
    None if the cut is empty. `cut` is the coord actually sliced (see safe_cut —
    nudged off a coplanar face). EVERY exterior ring is a contour, every interior
    ring a hole (classified); sub-mm interior rings are dropped as section slivers."""
    import shapely.geometry as sg
    ua, va = sorted(i for i in range(3) if i != ti)  # the two broad axes (x<y<z)
    cut = safe_cut(m, ti, cut)
    lo, hi = m.bounds
    origin = (lo + hi) / 2.0
    origin[ti] = cut
    sec = m.section(plane_origin=origin, plane_normal=np.eye(3)[ti])
    if sec is None:
        return None
    p2d, to_world = sec.to_2D()
    polys = _polygons_full(p2d)
    if not polys:
        return None

    def W2(uv):  # local 2D -> world (ua, va)
        p = to_world @ np.array([uv[0], uv[1], 0.0, 1.0])
        return (p[ua], p[va])

    pminx, pminy, pmaxx, pmaxy = polys[0].bounds
    min_feat = max(0.6, 0.006 * max(pmaxx - pminx, pmaxy - pminy))
    contours, hole_rings, holes, slivers, sig = [], [], [], 0, []
    for poly in polys:
        contours.append(np.array([W2(c) for c in poly.exterior.coords]))
        for ring in poly.interiors:
            wr = np.array([W2(c) for c in ring.coords])
            a0, a1 = wr[:, 0].min(), wr[:, 0].max()
            b0, b1 = wr[:, 1].min(), wr[:, 1].max()
            if max(a1 - a0, b1 - b0) < min_feat:
                slivers += 1
                continue
            hole_rings.append(wr)
            lp = sg.Polygon([(c[0], c[1]) for c in ring.coords])
            label, detail = classify(lp, a1 - a0, b1 - b0)
            ca, cb = (a0 + a1) / 2, (b0 + b1) / 2
            holes.append((label, ca, cb, detail))
            sig.append((label, round(ca, 1), round(cb, 1),
                        round(a1 - a0, 1), round(b1 - b0, 1)))
    allpts = np.vstack(contours)
    fp = (allpts[:, 0].min(), allpts[:, 0].max(),
          allpts[:, 1].min(), allpts[:, 1].max())
    return dict(ua=ua, va=va, cut=cut, contours=contours, hole_rings=hole_rings,
                holes=holes, slivers=slivers, fp=fp, min_feat=min_feat,
                hole_sig=tuple(sorted(sig)))


def face_projection(m, ti):
    """Silhouette of mesh `m` projected ALONG axis `ti` onto the other two axes (ua, va) — the
    outline you'd see looking down `ti`, with through-voids as holes. SAME return shape as
    face_section (contours/hole_rings/holes/fp/…) but `cut=None`, so slice's whole downstream
    (features/plot/svg/dxf) works unchanged. Axis-aligned: union the triangles' (ua,va) footprints
    (edge-on side walls collapse to ~0 area and drop out; the cap faces carry the silhouette)."""
    import shapely.geometry as sg
    from shapely.ops import unary_union
    ua, va = sorted(i for i in range(3) if i != ti)
    parts = []
    for tri in m.triangles:
        poly = sg.Polygon([(tri[k][ua], tri[k][va]) for k in range(3)])
        if poly.area > 1e-9:
            parts.append(poly if poly.is_valid else poly.buffer(0))
    if not parts:
        return None
    merged = unary_union(parts)
    polys = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
    polys = [p for p in polys if p.geom_type == "Polygon" and p.area > 0]
    if not polys:
        return None
    pminx, pminy, pmaxx, pmaxy = polys[0].bounds
    min_feat = max(0.6, 0.006 * max(pmaxx - pminx, pmaxy - pminy))
    contours, hole_rings, holes, slivers, sig = [], [], [], 0, []
    for poly in polys:
        contours.append(np.array(poly.exterior.coords))
        for ring in poly.interiors:
            wr = np.array(ring.coords)
            a0, a1 = wr[:, 0].min(), wr[:, 0].max()
            b0, b1 = wr[:, 1].min(), wr[:, 1].max()
            if max(a1 - a0, b1 - b0) < min_feat:
                slivers += 1
                continue
            hole_rings.append(wr)
            lp = sg.Polygon([(c[0], c[1]) for c in ring.coords])
            label, detail = classify(lp, a1 - a0, b1 - b0)
            ca, cb = (a0 + a1) / 2, (b0 + b1) / 2
            holes.append((label, ca, cb, detail))
            sig.append((label, round(ca, 1), round(cb, 1), round(a1 - a0, 1), round(b1 - b0, 1)))
    allpts = np.vstack(contours)
    fp = (allpts[:, 0].min(), allpts[:, 0].max(), allpts[:, 1].min(), allpts[:, 1].max())
    return dict(ua=ua, va=va, cut=None, contours=contours, hole_rings=hole_rings,
                holes=holes, slivers=slivers, fp=fp, min_feat=min_feat,
                hole_sig=tuple(sorted(sig)))


def dim_h(ax, x0, x1, y, off, text, fs=9):
    """Horizontal dimension line at height y+off, with extension ticks."""
    yy = y + off
    ax.annotate("", xy=(x1, yy), xytext=(x0, yy),
                arrowprops=dict(arrowstyle="<->", color="navy", lw=1.2))
    for x in (x0, x1):
        ax.plot([x, x], [y, yy], color="navy", lw=0.6, ls=":")
    ax.text((x0 + x1) / 2, yy, text, ha="center", va="top",
            color="navy", fontsize=fs)


def dim_v(ax, y0, y1, x, off, text, fs=9):
    """Vertical dimension line at x+off, with extension ticks."""
    xx = x + off
    ax.annotate("", xy=(xx, y1), xytext=(xx, y0),
                arrowprops=dict(arrowstyle="<->", color="navy", lw=1.2))
    for y in (y0, y1):
        ax.plot([x, xx], [y, y], color="navy", lw=0.6, ls=":")
    ax.text(xx, (y0 + y1) / 2, text, ha="right", va="center",
            color="navy", fontsize=fs, rotation=90)
