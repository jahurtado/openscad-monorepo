#!/usr/bin/env python3
"""
analyze — reconstruct a part's 3D features by correlating dense per-axis slice scans.

It does NOT touch geometry itself: it runs `slice.py --scan-axis all` (one subprocess,
which loads the mesh once, sections every --step mm along x/y/z, and dumps the per-level
classified features as JSON), then CORRELATES those 2D slices into 3D primitives with
real dimensions — the concrete coordinates / diameters / lengths an LLM needs to refine a
design.

Method: a 2D shape that persists across a contiguous run of slices is a "tube"; its 2D
bbox extruded over the run is a 3D box. The SAME physical feature shows up as a tube in
more than one axis (a rectangular window is a box in all three), so tubes are CLUSTERED by
3D-box overlap and each cluster reported once. A cluster with a round (CIRCLE) tube is a
CYLINDER — diameter from the circle, axis = the swept axis, length from the run; positive
(island) -> STANDOFF, negative (hole) -> BORE. A non-round cluster is an OPENING (hole) or
BOSS (island): a prism with its 3D extents + section shape (RECT/SLOT/POLY). Coaxial bores
of different Ø merge into a counterbore.

Only AXIS-ALIGNED features reduce cleanly (a tilted cylinder does not — out of scope, same
as the meshes are modelled aligned). Tolerances are scale-relative.

Usage:
    uv run tools/analyze.py part.stl
    uv run tools/analyze.py projects/example/main.scad --parts base_solid    # a front-door module
    uv run tools/analyze.py part.stl --step 0.5              # finer sweep
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import locate_openscad, render_module

HERE = Path(__file__).resolve().parent
AXES = "xyz"
AX_UV = {0: (1, 2), 1: (0, 2), 2: (0, 1)}   # axis ti -> its two in-plane axes (ua, va)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# --------------------------------------------------------------------------- scan (via slice)

def bake(input_path, parts, openscad):
    """Render a .scad to ONE STL up front (a .stl is used as-is), so every scan/refine
    sweep works on a mesh — no OpenSCAD re-render per subprocess (the thing that made a
    .scad with many features hang). Returns (stl_path, scratch_dir_or_None)."""
    if input_path.suffix.lower() == ".stl":
        return input_path, None
    osc = locate_openscad(openscad)
    scratch = Path(tempfile.mkdtemp(prefix="analyze_"))
    stl = scratch / "baked.stl"
    if parts and "," not in parts:                # a single named module
        render_module(osc, input_path, parts, stl, fn=120)
    else:                                         # the file's top-level geometry (e.g. the
        subprocess.run([osc, "-o", str(stl), str(input_path)],   # SHOW=off default view)
                       capture_output=True, text=True)
    if not (stl.exists() and stl.stat().st_size):
        shutil.rmtree(scratch, ignore_errors=True)
        sys.exit(f"could not render {input_path} to STL (correct module/--parts?)")
    return stl, scratch


def run_scan(input_path, step, parts, openscad, axis="all", rng=None):
    """Subprocess `slice.py --scan-axis` and return the parsed JSON (slice owns all
    geometry + its own scratch; analyze only reads the result). `rng=(a,b)` restricts a
    single-axis sweep to a window (used to refine a transition by a fine sweep)."""
    cmd = [sys.executable, str(HERE / "slice.py"), str(input_path),
           "--scan-axis", axis, "--step", str(step)]
    if rng is not None:
        cmd += [f"--range={rng[0]},{rng[1]}"]   # `=` so a negative a/b isn't read as a flag
    if parts:
        cmd += ["--parts", parts]
    if openscad:
        cmd += ["--openscad", openscad]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"slice --scan-axis failed:\n{r.stderr.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"slice returned no JSON:\n{r.stdout[:300]}\n{r.stderr[:300]}")


def _match(s, role, kind, c, wh):
    r, k, sc, swh, _bb = s
    tol = max(0.6, 0.15 * max(wh))
    return (r == role and k == kind
            and math.hypot(sc[0] - c[0], sc[1] - c[1]) <= tol
            and abs(swh[0] - wh[0]) + abs(swh[1] - wh[1]) <= 2 * tol)


def _fine_levels(ctx, ti, lo, hi):
    """ONE fine sweep of axis ti over [lo,hi] -> its levels. Cached per (ti,lo,hi) so a
    whole axis is swept finely just ONCE (a subprocess per axis, not per endpoint — the
    subprocess startup + STL reload is what made per-endpoint refinement crawl)."""
    input_path, _step, fine, _parts, openscad = ctx
    data = run_scan(input_path, fine, None, openscad, axis=AXES[ti], rng=(lo, hi))
    return data["axes"][0]["levels"]


def _edge_in(levels, role, kind, c, wh, is_start):
    present = [L["pos"] for L in levels if any(_match(s, role, kind, c, wh) for s in _shapes(L))]
    if not present:
        return None
    return min(present) if is_start else max(present)


# --------------------------------------------------------------------------- tube tracking

def _shapes(level):
    """Classified shapes in a level: (role, kind, (cu, cv), (w, h), bbox2d). Positive
    shapes (islands) are kept ONLY when round (CIRCLE) — a FREE cylindrical standoff. A
    non-round positive contour in a side sweep is body material between holes (a false
    boss). Connected bosses (a post tied to a wall by a leg) aren't isolated islands, so
    they're recovered separately, from their blind bore (see infer_bosses)."""
    out = []
    for pc in level["pieces"]:
        for role, key in (("hole", "holes"), ("island", "islands")):
            for s in pc[key]:
                if role == "island" and s["kind"] != "CIRCLE":
                    continue
                u0, v0, u1, v1 = s["bbox"]
                out.append((role, s["kind"], ((u0 + u1) / 2, (v0 + v1) / 2),
                            (u1 - u0, v1 - v0), (u0, v0, u1, v1)))
    return out


def track_tubes(axis_scan, ti, step):
    """Track shapes through the level stack into tubes. Greedy match by role + kind +
    centre + size between consecutive levels; tolerances scale with the size so it holds
    on a 2 mm post and a 30 mm bore alike. Returns tube dicts with a 3D AABB."""
    closed, open_t = [], []

    def tol(sz):
        return max(0.4, 0.12 * sz)

    for L in axis_scan["levels"]:
        pos = L["pos"]
        for t in open_t:
            t["_hit"] = False
        for role, kind, c, wh, bb in _shapes(L):
            best, bestcost = None, 1e9
            for t in open_t:
                if t["_hit"] or t["role"] != role or t["kind"] != kind:
                    continue
                dc = math.hypot(c[0] - t["c"][0], c[1] - t["c"][1])
                dw = abs(wh[0] - t["wh"][0]) + abs(wh[1] - t["wh"][1])
                if dc <= tol(max(t["wh"])) and dw <= 2 * tol(max(t["wh"])) and dc + dw < bestcost:
                    best, bestcost = t, dc + dw
            if best is not None:
                n = best["n"] + 1
                best["c"] = tuple((best["c"][i] * best["n"] + c[i]) / n for i in range(2))
                best["wh"] = tuple((best["wh"][i] * best["n"] + wh[i]) / n for i in range(2))
                best["bb"] = tuple((best["bb"][i] * best["n"] + bb[i]) / n for i in range(4))
                best["b"], best["n"], best["_hit"] = pos, n, True
            else:
                open_t.append(dict(role=role, kind=kind, c=c, wh=wh, bb=bb,
                                   a=pos, b=pos, n=1, _hit=True))
        survivors = []
        for t in open_t:
            (survivors if t["_hit"] else closed).append(t)
        open_t = survivors
    closed += open_t
    tubes = [t for t in closed if t["n"] >= 2 or (t["b"] - t["a"]) >= step]
    for t in tubes:                              # 3D AABB: [x0,x1,y0,y1,z0,z1]
        ua, va = AX_UV[ti]
        box = [0.0] * 6
        box[2 * ti], box[2 * ti + 1] = t["a"], t["b"]
        u0, v0, u1, v1 = t["bb"]
        box[2 * ua], box[2 * ua + 1] = u0, u1
        box[2 * va], box[2 * va + 1] = v0, v1
        t["aabb"], t["axis"] = box, ti
    return tubes


# --------------------------------------------------------------------------- 3D clustering

def _iou(a, b):
    inter = 1.0
    for k in range(3):
        lo, hi = max(a[2 * k], b[2 * k]), min(a[2 * k + 1], b[2 * k + 1])
        if hi <= lo:
            return 0.0
        inter *= (hi - lo)
    va = (a[1] - a[0]) * (a[3] - a[2]) * (a[5] - a[4])
    vb = (b[1] - b[0]) * (b[3] - b[2]) * (b[5] - b[4])
    return inter / (va + vb - inter) if (va + vb - inter) > 0 else 0.0


def cluster(tubes):
    """Union-find clusters of tubes whose 3D boxes overlap a lot (same physical feature
    seen from different axes). Same role only — a hole and a post never merge."""
    parent = list(range(len(tubes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(tubes)):
        for j in range(i + 1, len(tubes)):
            if tubes[i]["role"] == tubes[j]["role"] and \
               _iou(tubes[i]["aabb"], tubes[j]["aabb"]) > 0.35:
                parent[find(i)] = find(j)
    groups = {}
    for i, t in enumerate(tubes):
        groups.setdefault(find(i), []).append(t)
    return list(groups.values())


# --------------------------------------------------------------------------- classify + emit

def _union_box(group):
    b = [min(t["aabb"][0] for t in group), max(t["aabb"][1] for t in group),
         min(t["aabb"][2] for t in group), max(t["aabb"][3] for t in group),
         min(t["aabb"][4] for t in group), max(t["aabb"][5] for t in group)]
    return b


def classify_feature(group, pbb):
    """One cluster -> a 3D feature dict. Prefer a CIRCLE tube (cylinder); else a prism."""
    role = group[0]["role"]
    box = _union_box(group)
    ext = [box[1] - box[0], box[3] - box[2], box[5] - box[4]]
    ctr = [(box[2 * k] + box[2 * k + 1]) / 2 for k in range(3)]
    circ = next((t for t in group if t["kind"] == "CIRCLE"), None)
    if circ is not None:
        ax = circ["axis"]
        d = 0.5 * (circ["wh"][0] + circ["wh"][1])
        return dict(shape="CYLINDER", role=role, axis=ax, d=d,
                    a=circ["a"], b=circ["b"], center=circ["c"], box=box, pbb=pbb)
    # prism: thru-axis = the thinnest extent (the wall it pierces / its depth)
    thru = min(range(3), key=lambda k: ext[k])
    kind = max((t["kind"] for t in group), key=lambda k: ["RECT", "SLOT", "POLY"].index(k)
               if k in ("RECT", "SLOT", "POLY") else -1)
    return dict(shape="PRISM", role=role, kind=kind, thru=thru, ext=ext,
                center=ctr, box=box, pbb=pbb)


def recess_bands(scan, ti, d0, d1, part, step):
    """Walk a cavity's own thru-range and read the dominant hole's in-plane size at each
    level; group into bands of roughly-constant wall thickness. >1 band = a recess (the
    wall steps). Targeted (only inside a confirmed cavity), so the loose tube matcher can
    stay robust while genuine steps are still caught. Returns [(lo, hi, wu, wv)]."""
    ip = AX_UV[ti]
    axis_scan = next(a for a in scan["axes"] if a["axis"] == AXES[ti])
    samples = []
    for L in axis_scan["levels"]:
        if not (d0 - step <= L["pos"] <= d1 + step):
            continue
        big = None
        for pc in L["pieces"]:
            for h in pc["holes"]:
                bb = h["bbox"]
                area = (bb[2] - bb[0]) * (bb[3] - bb[1])
                if big is None or area > big[0]:
                    big = (area, bb[2] - bb[0], bb[3] - bb[1])
        if big:
            samples.append((L["pos"], big[1], big[2]))
    if not samples:
        return []
    bands, cur = [], [samples[0]]
    for s in samples[1:]:
        if abs(s[1] - cur[-1][1]) <= 0.5 and abs(s[2] - cur[-1][2]) <= 0.5:
            cur.append(s)
        else:
            bands.append(cur); cur = [s]
    bands.append(cur)
    out = []
    for grp in bands:
        wu = sum(g[1] for g in grp) / len(grp)
        wv = sum(g[2] for g in grp) / len(grp)
        wall_u = (part[2 * ip[0] + 1] - part[2 * ip[0]] - wu) / 2
        wall_v = (part[2 * ip[1] + 1] - part[2 * ip[1]] - wv) / 2
        out.append((grp[0][0], grp[-1][0], wall_u, wall_v))
    return out


def _depth(lo, hi, a, b, step):
    elo, ehi = (a - lo) <= 1.5 * step, (hi - b) <= 1.5 * step
    return int(elo) + int(ehi)


def merge_coaxial(cyls, pbb, step):
    """Collinear bores sharing axis+centre but different Ø, end-to-end -> a counterbore
    (e.g. Ø8 through + Ø16 counterbore). Annotates the wider one as a counterbore. If the
    COMBINED stack spans both part faces, the NARROW bore is a through hole (counterbored):
    flag it so it isn't mislabelled `blind` just because its own far end dies at the
    counterbore mouth (an interior surface), not at a face."""
    for c in cyls:
        c["note"] = ""
    for i, a in enumerate(cyls):
        for b in cyls[i + 1:]:
            if a["axis"] != b["axis"] or a["role"] != b["role"]:
                continue
            if math.hypot(a["center"][0] - b["center"][0],
                          a["center"][1] - b["center"][1]) > 0.5:
                continue
            lo, hi = sorted([a, b], key=lambda c: c["a"])
            if abs(hi["a"] - lo["b"]) <= 1.5 * step:        # end-to-end
                wide = a if a["d"] > b["d"] else b
                narrow = b if wide is a else a
                wide["note"] = "counterbore"
                elo, ehi = pbb[AXES[a["axis"]]]
                if _depth(elo, ehi, lo["a"], hi["b"], step) == 2:   # stack reaches both faces
                    narrow["thru_cbore"] = True                     # -> through, not blind
                    narrow["note"] = "under counterbore"
    return cyls


def refine_features(feats, pbb, ctx):
    """Pin each feature's INTERNAL endpoints (not at a part face) to fine precision.
    Batched per axis: gather every internal edge, then do ONE fine sweep per axis over
    the span that covers them all (a subprocess per axis, not per endpoint). Face-reaching
    ends are already exact, so they're left alone. ctx = (input, step, fine, parts, osc)."""
    step = ctx[1]
    # collect internal edges as jobs: (ti, edge_pos, is_start, role, kind, c, wh, setter)
    jobs = []

    def add(ti, edge, is_start, role, kind, c, wh, setter):
        lo, hi = pbb[AXES[ti]]
        if (is_start and (edge - lo) > 1.5 * step) or (not is_start and (hi - edge) > 1.5 * step):
            jobs.append((ti, edge, is_start, role, kind, c, wh, setter))

    for f in feats:
        if f["shape"] == "CYLINDER":
            ti, wh = f["axis"], (f["d"], f["d"])
            add(ti, f["a"], True, f["role"], "CIRCLE", f["center"], wh,
                lambda p, f=f: f.__setitem__("a", p))
            add(ti, f["b"], False, f["role"], "CIRCLE", f["center"], wh,
                lambda p, f=f: f.__setitem__("b", p))
        else:
            ti = f["thru"]
            ua, va = AX_UV[ti]
            c, wh = (f["center"][ua], f["center"][va]), (f["ext"][ua], f["ext"][va])
            add(ti, f["box"][2 * ti], True, f["role"], f["kind"], c, wh,
                lambda p, f=f, ti=ti: f["box"].__setitem__(2 * ti, p))
            add(ti, f["box"][2 * ti + 1], False, f["role"], f["kind"], c, wh,
                lambda p, f=f, ti=ti: f["box"].__setitem__(2 * ti + 1, p))

    for ti in (0, 1, 2):
        axis_jobs = [j for j in jobs if j[0] == ti]
        if not axis_jobs:
            continue
        lo = min(j[1] for j in axis_jobs) - 1.5 * step
        hi = max(j[1] for j in axis_jobs) + 1.5 * step
        levels = _fine_levels(ctx, ti, lo, hi)            # ONE fine sweep for this axis
        for _ti, _edge, is_start, role, kind, c, wh, setter in axis_jobs:
            p = _edge_in(levels, role, kind, c, wh, is_start)
            if p is not None:
                setter(p)

    for f in feats:                                       # prisms: refresh ext/center from box
        if f["shape"] != "CYLINDER":
            f["ext"] = [f["box"][2 * k + 1] - f["box"][2 * k] for k in range(3)]
            f["center"] = [(f["box"][2 * k] + f["box"][2 * k + 1]) / 2 for k in range(3)]


def boss_radius(scan, ti, cu, cv, za, zb):
    """The boss's outer WALL is a circular arc centred on the bore — the arc detector
    measures its radius precisely. Take the median radius of arcs centred on (cu,cv) with
    a large span (a near-full circle = the post wall; a small-span arc is a part corner,
    not the boss) over the bore's z-range. Returns the radius, or None."""
    axis_scan = next((a for a in scan["axes"] if a["axis"] == AXES[ti]), None)
    if axis_scan is None:
        return None
    rs = []
    for L in axis_scan["levels"]:
        if not (za - 0.5 <= L["pos"] <= zb + 0.5):
            continue
        for pc in L["pieces"]:
            for fl in pc["fillets"]:
                c = fl["c"]
                if math.hypot(c[0] - cu, c[1] - cv) <= 1.5 and fl["span"] >= 180:
                    rs.append(fl["r"])
    if not rs:
        return None
    rs.sort()
    return rs[len(rs) // 2]


def infer_bosses(feats, scan, pbb, step):
    """A BORE whose mouth is on an INTERIOR surface (reaches NEITHER part face -> our
    `internal` class) sits in a recessed post: a BOSS. That's the clean signal — a blind
    hole that reaches a face is just a pocket in a slab, NOT a boss. These posts are tied
    to a wall by a leg (never isolated islands), so the tube tracker misses them; recover
    one BOSS per internal bore. The collar Ø comes from the boss WALL ARC (measured, the
    reliable signal); only if no arc is found do we fall back to an estimate (~bore×2)."""
    bosses = []
    for f in feats:
        if f["shape"] != "CYLINDER" or f["role"] != "hole":
            continue
        ti = f["axis"]
        lo, hi = pbb[AXES[ti]]
        if _depth(lo, hi, f["a"], f["b"], step) != 0:        # only `internal` bores -> boss
            continue
        cu, cv = f["center"]
        r = boss_radius(scan, ti, cu, cv, f["a"], f["b"])
        bosses.append(dict(shape="CYLINDER", role="island", label="BOSS", axis=ti,
                           center=f["center"], d=(2 * r if r else f["d"] * 2.0),
                           a=f["a"], b=f["b"], inferred=True, bore_d=f["d"], est=r is None))
    feats.extend(bosses)


def dedup_cylinders(feats):
    """Collapse near-identical CYLINDER features. The multi-axis tube tracker re-finds the same
    physical bore from several scan directions, so a long axis-aligned channel can show up 6× (same
    axis, centre, Ø and span). Two cylinders merge when they share axis+role, the centres and Ø match
    (Δ<0.35) and their spans overlap — a genuine second bore differs in POSITION, and a real coaxial
    step (counterbore) differs in Ø, so neither merges. Keeps one, widening its span to the union."""
    dropped = set()
    cyls = [f for f in feats if f["shape"] == "CYLINDER" and not f.get("inferred")]
    for i, f in enumerate(cyls):
        if id(f) in dropped:
            continue
        for g in cyls[i + 1:]:
            if id(g) in dropped:
                continue
            if (f["axis"] == g["axis"] and f["role"] == g["role"]
                    and abs(f["d"] - g["d"]) < 0.35
                    and math.hypot(f["center"][0] - g["center"][0],
                                   f["center"][1] - g["center"][1]) < 0.5
                    and not (g["b"] < f["a"] - 0.5 or g["a"] > f["b"] + 0.5)):   # spans overlap
                f["a"], f["b"] = min(f["a"], g["a"]), max(f["b"], g["b"])
                dropped.add(id(g))
    return [f for f in feats if id(f) not in dropped]


def detect_seats(feats, scan, step):
    """A bore can open into a wider NON-circular recess at its mouth — a hex nut trap or a
    polygonal/keyed seat. The tube tracker keeps the round shaft and drops the short polygonal
    mouth (it tracks by shape, and POLY≠CIRCLE breaks the tube), so probe each bore's mouth
    levels directly: a coaxial, wider, non-CIRCLE hole sitting at/just outside the mouth is the
    seat. Annotates f['seat'] = {kind,w,h,depth,side}. This is the signal the consumer needs to
    model a hex pocket instead of a plain cylinder — paired with the skill rule to slice-confirm."""
    levels_by_axis = {a["axis"]: a["levels"] for a in scan["axes"]}
    for f in feats:
        if f["shape"] != "CYLINDER" or f["role"] != "hole" or f.get("inferred"):
            continue
        cu, cv = f["center"]
        d = f["d"]
        levels = levels_by_axis[AXES[f["axis"]]]
        best = None
        for sgn, mouth in ((1, f["b"]), (-1, f["a"])):
            seat = []
            for L in levels:
                off = sgn * (L["pos"] - mouth)
                if not (-1.0 * step <= off <= 4.0 * step):        # at / just outside this mouth
                    continue
                for pc in L["pieces"]:
                    for h in pc["holes"]:
                        if h["kind"] == "CIRCLE":
                            continue
                        bb = h["bbox"]
                        hc = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
                        if math.hypot(hc[0] - cu, hc[1] - cv) > max(1.0, 0.5 * d):
                            continue                              # not coaxial with the bore
                        w, hh = bb[2] - bb[0], bb[3] - bb[1]
                        if max(w, hh) >= d + 0.5:                 # genuinely wider than the shaft
                            seat.append((L["pos"], h["kind"], w, hh))
            if seat:
                ps = [s[0] for s in seat]
                cand = dict(kind=seat[0][1], w=max(s[2] for s in seat),
                            h=max(s[3] for s in seat), depth=abs(max(ps) - min(ps)) + step,
                            side="+" if sgn > 0 else "-")
                if best is None or cand["w"] * cand["h"] > best["w"] * best["h"]:
                    best = cand
        if best is not None:
            f["seat"] = best


def compute_features(scan, step, ctx=None):
    """Run the full pipeline (tubes -> 3D cluster -> classify -> refine -> coaxial) and
    tag each feature with a display `label` (BORE/STANDOFF/OPENING/BOSS/CAVITY), so the
    text readout and the debug .scad agree. Returns (feats, pbb, part)."""
    pbb = {a["axis"]: a["extent"] for a in scan["axes"]}
    tubes = []
    for a in scan["axes"]:
        tubes += track_tubes(a, AXES.index(a["axis"]), step)
    feats = [classify_feature(g, pbb) for g in cluster(tubes)]
    if ctx is not None:
        refine_features(feats, pbb, ctx)
    feats = dedup_cylinders(feats)          # after refine: spans are final, so true dups coincide
    merge_coaxial([f for f in feats if f["shape"] == "CYLINDER"], pbb, step)
    detect_seats(feats, scan, step)
    part = [0.0] * 6
    for k, ltr in enumerate(AXES):
        part[2 * k], part[2 * k + 1] = pbb[ltr]
    for f in feats:
        if f["shape"] == "CYLINDER":
            f["label"] = "STANDOFF" if f["role"] == "island" else "BORE"
        else:
            ip = AX_UV[f["thru"]]
            face = (part[2 * ip[0] + 1] - part[2 * ip[0]]) * (part[2 * ip[1] + 1] - part[2 * ip[1]])
            cav = f["ext"][ip[0]] * f["ext"][ip[1]]
            f["label"] = ("CAVITY" if (f["role"] == "hole" and face > 0 and cav >= 0.30 * face)
                          else ("OPENING" if f["role"] == "hole" else "BOSS"))
    infer_bosses(feats, scan, pbb, step)   # a post around each internal bore (collar from arc)
    return feats, pbb, part


def emit_text(input_name, feats, pbb, part, scan, step):
    lines = [f"# analyze {input_name}   (slice scan, step {step:g} mm)",
             "# bbox " + "  ".join(f"{ax}[{e[0]:.2f},{e[1]:.2f}]" for ax, e in pbb.items())]
    DEPTH = {"BORE": {2: "through", 1: "blind", 0: "internal"},
             "STANDOFF": {2: "full-height", 1: "rooted", 0: "floating"}}
    rows = []
    for f in feats:
        if f["shape"] == "CYLINDER" and f["label"] == "BOSS":     # inferred post around a bore
            ax = AXES[f["axis"]]
            dd = "~%.2f" % f["d"] if f.get("est") else f"{f['d']:.2f}"
            rows.append(("BOSS", 0, f"BOSS      axis={ax}  center=({f['center'][0]:.2f},"
                         f"{f['center'][1]:.2f})  d={dd}  {ax}[{f['a']:.2f},{f['b']:.2f}]  "
                         f"len={f['b'] - f['a']:.2f}  (post around internal bore Ø{f['bore_d']:.2f})"))
        elif f["shape"] == "CYLINDER":
            ax = AXES[f["axis"]]
            lo, hi = pbb[ax]
            kind = f["label"]
            depth = DEPTH[kind][2 if f.get("thru_cbore") else _depth(lo, hi, f["a"], f["b"], step)]
            note = f"  ({f['note']})" if f.get("note") else ""
            s = f.get("seat")
            seat = (f"  SEAT[{s['side']}]={s['kind']} {s['w']:.2f}x{s['h']:.2f} deep~{s['depth']:.2f}"
                    f"  (NON-CIRCULAR seat — model the {s['kind']} section, not a bore; slice to confirm)"
                    if s else "")
            rows.append((kind, 0, f"{kind:9} axis={ax}  center=({f['center'][0]:.2f},"
                         f"{f['center'][1]:.2f})  d={f['d']:.2f}  {ax}[{f['a']:.2f},{f['b']:.2f}]"
                         f"  len={f['b'] - f['a']:.2f}  {depth}{note}{seat}"))
        else:
            ax = AXES[f["thru"]]
            lo, hi = pbb[ax]
            box = f["box"]
            d0, d1 = box[2 * f["thru"]], box[2 * f["thru"] + 1]
            e = f["ext"]
            ip = AX_UV[f["thru"]]
            if f["label"] == "CAVITY":
                bands = recess_bands(scan, f["thru"], d0, d1, part, step)
                stepped = len(bands) > 1
                walls = []
                for k in range(3):
                    if stepped and k in ip:
                        walls += [f"{AXES[k]}-=varies", f"{AXES[k]}+=varies"]
                        continue
                    gm, gp = box[2 * k] - part[2 * k], part[2 * k + 1] - box[2 * k + 1]
                    walls.append(f"{AXES[k]}-=" + ("open" if gm <= 0.3 else f"{gm:.2f}"))
                    walls.append(f"{AXES[k]}+=" + ("open" if gp <= 0.3 else f"{gp:.2f}"))
                rows.append(("CAVITY", 2, f"CAVITY    {f['kind']:5} center=({f['center'][0]:.2f},"
                             f"{f['center'][1]:.2f},{f['center'][2]:.2f})  "
                             f"size={e[0]:.2f}x{e[1]:.2f}x{e[2]:.2f}  walls: " + "  ".join(walls)))
                if stepped:
                    seg = "  ->  ".join(f"{AXES[f['thru']]}[{blo:.2f},{bhi:.2f}] "
                                        f"wall {AXES[ip[0]]}={wu:.2f} {AXES[ip[1]]}={wv:.2f}"
                                        for blo, bhi, wu, wv in bands)
                    rows.append(("CAVITY", 3, f"  RECESS  {seg}"))
            else:
                name = f["label"]
                depth = ("through" if _depth(lo, hi, d0, d1, step) == 2
                         else ("blind" if f["role"] == "hole" else "raised"))
                rows.append((name, 1, f"{name:9} {f['kind']:5} thru={ax}  "
                             f"center=({f['center'][0]:.2f},{f['center'][1]:.2f},{f['center'][2]:.2f})  "
                             f"size={e[0]:.2f}x{e[1]:.2f}x{e[2]:.2f}  {depth}"))
    for _k, _o, line in sorted(rows, key=lambda r: (r[1], r[0])):
        lines.append(line)
    if not rows:
        lines.append("(no features detected)")
    return "\n".join(lines)


def emit_debug_scad(feats, original_stl):
    """An OpenSCAD file rendering each detection as a coloured primitive (BORE/STANDOFF ->
    cylinder, OPENING/BOSS/CAVITY -> box) over the real mesh as a transparent background
    (`%import`), so you can eyeball WHERE analyze found things vs the part."""
    COL = {"BORE": '"red"', "STANDOFF": '"green"', "OPENING": '"orange"',
           "BOSS": '"yellow"', "CAVITY": "[0,1,1,0.30]"}
    L = ["// analyze --debug-scad: detections as primitives over the part (open in OpenSCAD, F5).",
         "// %import = the real mesh (transparent grey); coloured solids = what analyze detected.",
         "$fn = 48;", ""]
    if original_stl:
        L += [f'%import("{Path(original_stl).resolve().as_posix()}");', ""]
    for f in feats:
        col = COL[f["label"]]
        if f["shape"] == "CYLINDER":
            ax, (cx, cy), a, d = f["axis"], f["center"], f["a"], f["d"]
            h = f["b"] - f["a"]
            pre = {0: f"translate([{a:.3f},{cx:.3f},{cy:.3f}]) rotate([0,90,0])",
                   1: f"translate([{cx:.3f},{a:.3f},{cy:.3f}]) rotate([-90,0,0])",
                   2: f"translate([{cx:.3f},{cy:.3f},{a:.3f}])"}[ax]
            L.append(f"color({col}) {pre} cylinder(d={d:.3f}, h={h:.3f});")
        else:
            b = f["box"]
            L.append(f"color({col}) translate([{b[0]:.3f},{b[2]:.3f},{b[4]:.3f}]) "
                     f"cube([{b[1] - b[0]:.3f},{b[3] - b[2]:.3f},{b[5] - b[4]:.3f}]);")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="an .stl, or a .scad front door")
    ap.add_argument("--parts", default=None,
                    help="front-door module(s) to analyze (passed through to slice)")
    ap.add_argument("--step", type=float, default=1.0, help="coarse sweep step in mm (default 1.0)")
    ap.add_argument("--fine", type=float, default=0.05,
                    help="fine step for refining internal transitions (default 0.05)")
    ap.add_argument("--no-refine", action="store_true",
                    help="skip the fine refinement of internal endpoints (faster, ±step)")
    ap.add_argument("--debug-scad", type=Path, default=None, metavar="FILE.scad",
                    help="also write an OpenSCAD file with every detection as a coloured "
                         "primitive over the part (transparent) — to eyeball the detections")
    ap.add_argument("--openscad", default=None)
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"no such file: {args.input}")
    stl, scratch = bake(args.input, args.parts, args.openscad)
    try:
        scan = run_scan(stl, args.step, None, args.openscad)   # an STL: --parts already baked in
        ctx = None if args.no_refine else (stl, args.step, args.fine, None, args.openscad)
        feats, pbb, part = compute_features(scan, args.step, ctx)
        print(emit_text(args.input.name, feats, pbb, part, scan, args.step))
        if args.debug_scad:
            dbg = args.debug_scad
            partstl = dbg.with_name(dbg.stem + "_part.stl")   # persist the mesh for the overlay
            shutil.copy(stl, partstl)
            dbg.write_text(emit_debug_scad(feats, partstl))
            print(f"\ndebug scad -> {dbg}  (open it in OpenSCAD; F5)")
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
