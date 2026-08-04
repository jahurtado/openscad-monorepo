#!/usr/bin/env python3
"""
compare — overlay the cross-sections of TWO designs and gate their differences
PER DETECTOR (contour, holes) plus the global volume / extents. (FILLETS R is
reported but does NOT gate — see below.)

The validation gate for the "remodel a resources/ mesh with solid primitives"
workflow, and for any A/B design diff. It slices BOTH inputs at the same plane(s)
in the SAME world frame — NO alignment: both designs must already sit in the same
position (that is the caller's job, fixed up front) — overlays the sections, and
marks in RED everything that diverges beyond tolerance. Each DETECTOR is gated on
its own:

  VOLUME    solid-volume delta %                          (3D, watertight only)
  EXTENTS   per-axis bbox-extent delta                    (3D)
  CONTOUR   max (Hausdorff) + mean outline deviation      (per plane)
  HOLES     matched-hole Ø/size delta + missing / extra   (per plane)
  FILLETS   matched-arc R delta — INFORMATIONAL, no gate   (per plane)

FILLETS deliberately does not gate: a MESHED arc's radius is fragile (partial
arcs, faceting, and concentric arcs -same centre, inner/outer Ø- that the matcher
could cross-pair, yielding false ΔR). A real radius error changes the profile →
CONTOUR catches it. So FILLETS is reported (and painted red in the overlay if
Δ>tol) but does NOT enter the verdict. It matches by centre AND radius.

It REUSES slice.py's sectioning + feature detection (resolve_pieces /
section_loaded / collect_features), so "what counts as a hole / an arc" is exactly
what slice reports — no second detector to drift. Exits non-zero if ANY detector
exceeds its tolerance, so it doubles as a pre-commit / CI gate next to check.py.

Per-detector tolerances live in tools/tolerances.json (the baseline, easy to tune);
--tolerances other.json loads a custom set; --tol / --vol-tol override per run.

Planes default to the three central sections top / front / side; pass explicit
planes (z=20, x=44) or names to override. One overlay plot per plane -> build/.

OVERLAY COLORS (roles detected by extension, not by order):
    REFERENCE (the .stl mesh)  -> GRAY fill  (the ground truth)
    MODEL     (the .scad)      -> BLUE dashed outline (what we built)
    (if both inputs are the same type, falls back to A=gray / B=blue by order)
    RED    = deviation OUTSIDE tolerance
    ORANGE = real difference but WITHIN tolerance (between the noise floor and tol)
The title and legend show each file's ROLE and NAME next to its color.

Usage:
    uv run tools/compare.py model.scad reference.stl
    uv run tools/compare.py main.scad reference.stl --parts-a lid_solid top
    uv run tools/compare.py a.stl b.stl z=20 x=44 --tol 0.3
    uv run tools/compare.py model.scad reference.stl --tolerances tight.json
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np

from _common import build_dir, locate_openscad
from _geom import AXES
from slice import (collect_features, load_meshes, parse_plane, piece_geom,
                   resolve_pieces, section_loaded)

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
TOL_KEYS = ("contour", "holes", "fillets", "extents", "volume")


def load_tolerances(path=None):
    """compare's gate tolerances (mm; volume in %): the defaults in
    tools/tolerances.json, overlaid with a custom JSON via --tolerances — keys it
    omits fall back to the defaults. Returns {contour,holes,fillets,extents,volume}."""
    base = json.loads((HERE / "tolerances.json").read_text()).get("compare", {})
    tol = {k: float(base[k]) for k in TOL_KEYS}
    if path:
        p = Path(path)
        if not p.exists():
            sys.exit(f"--tolerances: {p} does not exist")
        try:
            custom = json.loads(p.read_text()).get("compare", {})
        except json.JSONDecodeError as e:
            sys.exit(f"--tolerances: invalid JSON in {p}: {e}")
        for k in TOL_KEYS:
            if k in custom:
                tol[k] = float(custom[k])
    return tol
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ----------------------------------------------------------------------------- inputs

def one_piece(input_path, parts, fn, openscad, build, label):
    """Resolve a side's input to a SINGLE trimesh mesh (the union of its modules):
    one design = one section per plane. `parts` picks front-door modules; several
    are fused into the one piece we compare. A single .stl is taken as-is."""
    import trimesh
    pieces = resolve_pieces([input_path], parts, fn, openscad, build)
    meshes = [m for _n, m in load_meshes(pieces)]
    m = meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)
    return label, m


# ----------------------------------------------------------------------------- detectors

def _size(p):
    x0, y0, x1, y1 = p["bbox"]
    return x1 - x0, y1 - y0


def _match(items_a, items_b, max_dist):
    """Greedy nearest-CENTRE matching of two feature lists (same frame). Returns
    (pairs, only_a, only_b): pairs that line up within max_dist, and the leftovers
    present on only one side (= a feature added or dropped by the remodel)."""
    pairs, used, only_a = [], set(), []
    for pa in items_a:
        ca = np.asarray(pa["center"])
        best, bj = None, None
        for j, pb in enumerate(items_b):
            if j in used:
                continue
            d = float(np.hypot(*(np.asarray(pb["center"]) - ca)))
            if d <= max_dist and (best is None or d < best):
                best, bj = d, j
        if bj is None:
            only_a.append(pa)
        else:
            used.add(bj)
            pairs.append((pa, items_b[bj]))
    only_b = [pb for j, pb in enumerate(items_b) if j not in used]
    return pairs, only_a, only_b


def contour_dev(ga, gb, tol):
    """Symmetric point-to-boundary deviation between two section polygons in the
    SAME frame (no alignment). Returns (max ~ Hausdorff, mean, red_pts, orange_pts):
      red_pts    — deviation > tol (OUTSIDE tolerance)
      orange_pts — deviation within tol but real (between a facet-noise floor
                   and tol): there is a difference, but below the limit.
    These are the overlay's two levels showing WHERE and HOW MUCH the profiles differ."""
    red, orange = [], []
    floor = min(0.03, 0.4 * tol)        # floor: ignores facet/mesh noise

    def scan(src, dst):
        ds = []
        n = max(200, int(src.length / 0.5))
        for t in np.linspace(0, 1, n, endpoint=False):
            p = src.interpolate(t, normalized=True)
            d = p.distance(dst)
            ds.append(d)
            if d > tol:
                red.append((p.x, p.y))
            elif d > floor:
                orange.append((p.x, p.y))
        return np.array(ds) if ds else np.array([0.0])

    da, db = scan(ga.boundary, gb.boundary), scan(gb.boundary, ga.boundary)
    return max(da.max(), db.max()), (da.mean() + db.mean()) / 2, red, orange


def compare_plane(label, mesh_a, mesh_b, ai, pos, tol, build, tag_a, tag_b, role_a=None, role_b=None,
                  out_png=None, frame=None):
    """Slice both meshes at axis ai = pos, compare per detector, draw the overlay.
    `tol` carries the per-detector thresholds (tol["contour"/"holes"/"fillets"]).
    Returns a record (numbers + which detectors failed) or None if the plane misses
    one side. `out_png` overrides the default `{tag_a}_vs_{tag_b}_{label}_compare.png`
    output path (so callers like slice_viewer can target a slice's plot slot); `frame`
    = (umin, umax, vmin, vmax) pins the plot window instead of autoscaling per plane
    (so a swept browser keeps a feature put across levels)."""
    ra = section_loaded([("A", mesh_a)], ai, pos, quiet=True)
    rb = section_loaded([("B", mesh_b)], ai, pos, quiet=True)
    if ra is None or rb is None:
        return None
    secs_a, ua, va, _fpa, diag_a = ra
    secs_b, _, _, _fpb, diag_b = rb
    sec_a, sec_b = secs_a[0][1], secs_b[0][1]
    feats_a = collect_features(secs_a, diag_a)["A"]
    feats_b = collect_features(secs_b, diag_b)["B"]
    ga, gb = piece_geom(sec_a), piece_geom(sec_b)
    diag = max(diag_a, diag_b)

    # CONTOUR
    if ga.is_empty or gb.is_empty:
        return None
    cmax, cmean, cred, corange = contour_dev(ga, gb, tol["contour"])

    # HOLES — match by centre, compare size; leftovers = missing / extra
    hpairs, honly_a, honly_b = _match(feats_a["holes"], feats_b["holes"], 0.25 * diag)
    hdmax, hred, horange = 0.0, [], []
    for pa, pb in hpairs:
        wa, ha = _size(pa)
        wb, hb = _size(pb)
        dsz = max(abs(wa - wb), abs(ha - hb))
        hdmax = max(hdmax, dsz)
        if dsz > tol["holes"]:
            hred.append((pa["center"], f"Δ{dsz:.2f}", "o"))
        elif dsz > min(0.03, 0.4 * tol["holes"]):
            horange.append((pa["center"], f"Δ{dsz:.2f}", "o"))   # diff within tol
    hred += [(p["center"], "missing", "x") for p in honly_a]    # in A, dropped in B
    hred += [(p["center"], "extra", "P") for p in honly_b]    # added in B

    # FILLETS — match by centre AND radius (do NOT cross-pair concentric arcs: a saddle has
    # inner and outer Ø with the SAME centre; matching by centre alone paired the wrong arc
    # and yielded huge false ΔR). An arc is only "the same one" if its centre AND radius are
    # close; leftovers (the mesh segments a smooth arc into several; mesh and CSG detect a
    # different number of arcs) do NOT count. INFORMATIONAL, no gate: a meshed arc's radius
    # is fragile (partial arcs, faceting) and CONTOUR already gates the real geometry.
    fa = [(cx, cy, r) for _o, cx, cy, r, _s in feats_a["fillets"]]
    fb = [(cx, cy, r) for _o, cx, cy, r, _s in feats_b["fillets"]]
    fdmax, fred, fn, used = 0.0, [], 0, set()
    for ax, ay, ar in fa:
        bj, bd = None, None
        for j, (bx, by, br) in enumerate(fb):
            if j in used:
                continue
            if np.hypot(bx - ax, by - ay) > 0.25 * diag or abs(br - ar) > max(2.0, 0.25 * ar):
                continue                                  # neither the same centre nor the same arc
            d = float(np.hypot(np.hypot(bx - ax, by - ay), br - ar))
            if bd is None or d < bd:
                bd, bj = d, j
        if bj is not None:
            used.add(bj); fn += 1
            dr = abs(fb[bj][2] - ar)
            fdmax = max(fdmax, dr)
            if dr > tol["fillets"]:
                fred.append(((ax, ay), f"ΔR{dr:.2f}"))

    out = Path(out_png) if out_png else build / f"{tag_a}_vs_{tag_b}_{label}_compare.png"
    compare_plot(out, label, sec_a, sec_b, cred, corange, hred, horange, fred, ua, va,
                 tag_a, tag_b, role_a, role_b, frame=frame)

    fails = []
    if cmax > tol["contour"]:
        fails.append("CONTOUR")
    if hdmax > tol["holes"] or honly_a or honly_b:
        fails.append("HOLES")
    # FILLETS does NOT gate (informational): the meshed radius is fragile; CONTOUR is the truth.
    return dict(label=label, plane=AXES[ua] + AXES[va], contour=(cmax, cmean),
                holes=(len(hpairs), hdmax, len(honly_a), len(honly_b)),
                fillets=(fn, fdmax), plot=out, fails=fails)


# ----------------------------------------------------------------------------- plot

ORANGE = "#ff8c00"


def _ref_side(role_a, role_b):
    """Which side is drawn as the REFERENCE (gray fill = the truth): whichever is
    the .stl (REFERENCE) or, if the other is a .scad (MODEL), by elimination. If
    both are the same type (roles None), fallback: A = gray. Returns 'a' or 'b'."""
    if role_a == "REFERENCE" or role_b == "MODEL":
        return "a"
    if role_b == "REFERENCE" or role_a == "MODEL":
        return "b"
    return "a"


def compare_plot(out_png, label, sec_a, sec_b, cred, corange, hred, horange, fred, ua, va,
                 tag_a="A", tag_b="B", role_a=None, role_b=None, frame=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    fig, ax = plt.subplots(figsize=(8, 7))

    if _ref_side(role_a, role_b) == "a":
        ref_sec, ref_tag, model_sec, model_tag = sec_a, tag_a, sec_b, tag_b
    else:
        ref_sec, ref_tag, model_sec, model_tag = sec_b, tag_b, sec_a, tag_a

    # REFERENCE: GRAY fill (the background truth).
    for c in ref_sec["contours"]:
        ax.fill(c[:, 0], c[:, 1], color="#dddddd", alpha=0.6)
        ax.plot(c[:, 0], c[:, 1], "-", lw=1.6, color="#555555")
    for r in ref_sec["hole_rings"]:
        ax.fill(r[:, 0], r[:, 1], color="white")
        ax.plot(r[:, 0], r[:, 1], "-", lw=1.0, color="#999999")
    # MODEL: BLUE dashed, outline only (what we compare against the truth).
    for c in model_sec["contours"]:
        ax.plot(c[:, 0], c[:, 1], "--", lw=1.5, color="#1f77b4")
    for r in model_sec["hole_rings"]:
        ax.plot(r[:, 0], r[:, 1], "--", lw=1.0, color="#1f77b4")

    # ORANGE: real difference but WITHIN tolerance (drawn first, beneath the red).
    if corange:
        d = np.asarray(corange)
        ax.plot(d[:, 0], d[:, 1], ".", color=ORANGE, ms=4, zorder=5)
    for (cx, cy), lbl, mk in horange:
        ax.plot([cx], [cy], mk, color=ORANGE, ms=10, mew=2, mfc="none", zorder=6)
        ax.text(cx, cy, f" {lbl}", color=ORANGE, fontsize=8, fontweight="bold", zorder=6)
    # ROJO: fuera de tolerancia (encima).
    if cred:
        d = np.asarray(cred)
        ax.plot(d[:, 0], d[:, 1], ".", color="red", ms=4, zorder=7)
    for (cx, cy), lbl, mk in hred:
        ax.plot([cx], [cy], mk, color="red", ms=10, mew=2, mfc="none", zorder=8)
        ax.text(cx, cy, f" {lbl}", color="red", fontsize=8, fontweight="bold", zorder=8)
    for (cx, cy), lbl in fred:
        ax.plot([cx], [cy], "s", color="red", ms=8, mew=2, mfc="none", zorder=8)
        ax.text(cx, cy, f" {lbl}", color="red", fontsize=8, fontweight="bold", zorder=8)

    if frame is not None:                            # fixed window (swept browser: feature stays put)
        umin, umax, vmin, vmax = frame
        pad = 0.08 * max(umax - umin, vmax - vmin, 1.0)
        ax.set_xlim(umin - pad, umax + 1.6 * pad)
        ax.set_ylim(vmin - pad, vmax + 1.6 * pad)
    else:
        allp = np.vstack([np.vstack(sec_a["contours"]), np.vstack(sec_b["contours"])])
        amin, amax = allp[:, 0].min(), allp[:, 0].max()
        bmin, bmax = allp[:, 1].min(), allp[:, 1].max()
        pad = 0.08 * max(amax - amin, bmax - bmin, 1.0)
        ax.set_xlim(amin - pad, amax + 1.6 * pad)
        ax.set_ylim(bmin - pad, bmax + 1.6 * pad)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_xlabel(f"{AXES[ua]} (mm)")
    ax.set_ylabel(f"{AXES[va]} (mm)")
    ax.set_title(f"{ref_tag} [gray]  vs  {model_tag} [blue]  —  {label}")
    ax.legend(handles=[Patch(facecolor="#dddddd", edgecolor="#555555", label=f"{ref_tag} (gray)"),
                       Patch(facecolor="none", edgecolor="#1f77b4", label=f"{model_tag} (blue)"),
                       Patch(facecolor="none", edgecolor="red", label="outside tolerance"),
                       Patch(facecolor="none", edgecolor=ORANGE, label="diff within tolerance")],
              loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=8)
    if frame is not None:
        # fixed canvas (constant pixel grid across levels AND axes) so a swept viewer
        # can swap images with set_data without distorting the aspect ratio; wider room
        # reserved at the right than emit_plot since this legend's labels are longer.
        fig.subplots_adjust(left=0.09, right=0.72, top=0.92, bottom=0.10)
        fig.savefig(str(out_png), dpi=140)
    else:
        fig.tight_layout()
        fig.savefig(str(out_png), dpi=140, bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------------- main

def _ok(passed):
    return "[ok ]" if passed else "[ERR]"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("args", nargs="+",
                    help="two inputs (.scad/.stl) + optional planes (z=20, top, front, side)")
    ap.add_argument("--parts-a", default=None,
                    help="front-door module(s) for input A (comma list; fused if several)")
    ap.add_argument("--parts-b", default=None, help="front-door module(s) for input B")
    ap.add_argument("--tolerances", default=None, metavar="FILE",
                    help="custom tolerances JSON (same shape as tools/tolerances.json; "
                         "keys it omits fall back to the defaults)")
    ap.add_argument("--tol", type=float, default=None,
                    help="override ALL mm detectors (contour/holes/fillets/extents) for "
                         "this run; default: the per-detector values in tools/tolerances.json")
    ap.add_argument("--vol-tol", type=float, default=None,
                    help="override the volume-delta gate, %% (default: tolerances.json)")
    ap.add_argument("--fn", type=int, default=120)
    ap.add_argument("--openscad", default=None)
    # intermixed: planes may sit before OR after the flags (`a b --parts-a X top`).
    args = ap.parse_intermixed_args()

    # Tolerances: JSON (default or --tolerances) → --tol/--vol-tol per-run override.
    tol = load_tolerances(args.tolerances)
    if args.tol is not None:
        for k in ("contour", "holes", "fillets", "extents"):
            tol[k] = args.tol
    if args.vol_tol is not None:
        tol["volume"] = args.vol_tol

    planes, inputs = [], []
    for a in args.args:
        parsed = [parse_plane(t) for t in a.split(",")]
        if all(p is not None for p in parsed):
            planes.extend(parsed)
        else:
            inputs.append(Path(a))
    if len(inputs) != 2:
        sys.exit("compare needs TWO inputs — the MODEL (.scad) and the REFERENCE (.stl)")
    for p in inputs:
        if not p.exists():
            sys.exit(f"does not exist: {p}")
    if not planes:                                   # default: the three central sections
        planes = [parse_plane(n) for n in ("top", "front", "side")]

    openscad = locate_openscad(args.openscad)
    build = build_dir(inputs[0])
    a_in, b_in = inputs
    tag_a, tag_b = a_in.stem, b_in.stem
    if tag_a == tag_b:
        tag_a, tag_b = tag_a + "_a", tag_b + "_b"

    # Roles by extension: the .stl mesh is the REFERENCE, the .scad is the MODEL
    # we built. They are only assigned if there is exactly one of each (otherwise
    # None -> the plot falls back to A/B order).
    def _role(p):
        e = p.suffix.lower()
        return "REFERENCE" if e == ".stl" else "MODEL" if e == ".scad" else None
    role_a, role_b = _role(a_in), _role(b_in)
    if not (role_a and role_b and role_a != role_b):
        role_a = role_b = None

    parts_a = args.parts_a.split(",") if args.parts_a else None
    parts_b = args.parts_b.split(",") if args.parts_b else None
    _, mesh_a = one_piece(a_in, parts_a, args.fn, openscad, build, "A")
    _, mesh_b = one_piece(b_in, parts_b, args.fn, openscad, build, "B")

    lo = np.minimum(mesh_a.bounds[0], mesh_b.bounds[0])
    hi = np.maximum(mesh_a.bounds[1], mesh_b.bounds[1])

    src = f" ({Path(args.tolerances).name})" if args.tolerances else ""
    rl_a = f" [{role_a}]" if role_a else ""
    rl_b = f" [{role_b}]" if role_b else ""
    print(f"# compare  A={a_in.name}{rl_a}  B={b_in.name}{rl_b}   "
          f"(red = outside tol; orange = diff within tol; tolerances{src})")

    # VOLUME (3D, watertight only)
    vol_ok = None
    if mesh_a.is_watertight and mesh_b.is_watertight:
        va, vb = mesh_a.volume / 1000, mesh_b.volume / 1000
        dv = (vb - va) / va * 100 if va else float("inf")
        vol_ok = abs(dv) <= tol["volume"]
        print(f"VOLUME    A={va:.2f}cm3  B={vb:.2f}cm3  delta={dv:+.2f}%  (tol {tol['volume']:g}%)   {_ok(vol_ok)}")
    else:
        print("VOLUME    n/a (some mesh is not watertight — merge of several pieces)")

    # EXTENTS (3D, per-axis)
    ea, eb = mesh_a.bounds[1] - mesh_a.bounds[0], mesh_b.bounds[1] - mesh_b.bounds[0]
    edmax = float(np.abs(ea - eb).max())
    ext_ok = edmax <= tol["extents"]
    print("EXTENTS   A=[{:.2f} {:.2f} {:.2f}]  B=[{:.2f} {:.2f} {:.2f}]  dmax={:.2f}mm  (tol {:g})   {}"
          .format(*ea, *eb, edmax, tol["extents"], _ok(ext_ok)))

    recs = []
    for ai, pos, label in planes:
        if pos is None:                              # central section -> combined bbox midpoint
            pos = float((lo[ai] + hi[ai]) / 2)
        rec = compare_plane(label, mesh_a, mesh_b, ai, pos, tol, build, tag_a, tag_b, role_a, role_b)
        if rec is None:
            print(f"PLANE {label}: one of the two sections is empty — skipping")
            continue
        recs.append(rec)
        cmax, cmean = rec["contour"]
        n, hdmax, miss, extra = rec["holes"]
        fn_, fdmax = rec["fillets"]
        print(f"PLANE {label} ({rec['plane']})")
        print(f"  CONTOUR  max={cmax:.2f}mm  mean={cmean:.2f}mm  (tol {tol['contour']:g})   {_ok(cmax <= tol['contour'])}")
        print(f"  HOLES    matched={n}  Ø/size-dmax={hdmax:.2f}mm  missing={miss} extra={extra}"
              f"  (tol {tol['holes']:g})   {_ok(hdmax <= tol['holes'] and not miss and not extra)}")
        print(f"  FILLETS  matched={fn_}  R-dmax={fdmax:.2f}mm  (informational, no gate — CONTOUR is the truth)")
        print(f"  plot     {rec['plot']}")

    fails = []
    if vol_ok is not None and not vol_ok:        # vol_ok may be a numpy.bool_ → do NOT use `is False`
        fails.append("VOLUME")
    if not ext_ok:
        fails.append("EXTENTS")
    for rec in recs:
        fails += [f"{d}({rec['label']})" for d in rec["fails"]]

    if fails:
        print(f"RESULT FAIL — detectors outside tol: {', '.join(fails)}")
        return 1
    print("RESULT PASS — every detector within tol")
    return 0


if __name__ == "__main__":
    sys.exit(main())
