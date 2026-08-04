#!/usr/bin/env python3
"""render3d — CLEAN 3D iso views of a piece (no cut plane), from several angles,
plus a deviation HEATMAP against a reference mesh.

`slice.py` previews are *section-first* (they show WHERE a plane cuts). This tool
gives 3D views from several perspectives and, with --vs, measures how far a model drifts from its mesh:

    uv run tools/render3d.py projects/x/main.scad                  # *_solid, 4 iso angles
    uv run tools/render3d.py projects/x/main.scad --parts a,b      # specific module(s), multicolor
    uv run tools/render3d.py piece.stl --angles 6
    uv run tools/render3d.py projects/x/main.scad --vs ref.stl     # deviation heatmap

With --vs <ref> = BIDIRECTIONAL deviation HEATMAP: colors BOTH surfaces by true
surface-to-surface distance — the reference by its distance to the model (where the model FALLS
SHORT) and the model by its distance to the reference (where it OVERSHOOTS) — green <--vs-tol
(matches), yellow, orange, red ≥2 mm, and prints the max/mean deviation. It measures true
separation (handles curved surfaces well and has no noise). It answers "how far does the model drift?".

Everything renders through the same path as the other tools (bake→STL + OpenSCAD image);
outputs go to the project's build/. The binary is located with `locate_openscad`
(or --openscad <path>).
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import (build_dir, discover_modules, locate_openscad,
                     render_module, scad_fn_baseline)

ISO_RX, ISO_RY, ISO_RZ0 = 55, 0, 25          # base iso rotation (same as slice.ISO_CAM)
PALETTE = ["gold", "steelblue", "orange", "green", "purple", "cyan"]


def _imp(stl: Path) -> str:
    return f'import("{Path(stl).resolve().as_posix()}", convexity=10);'


def bake(openscad: str, src: Path, module: str | None, fn, outdir: Path) -> Path:
    """STL for `src`: as-is if it's an .stl; otherwise renders `module` to build/."""
    src = Path(src)
    if src.suffix.lower() == ".stl":
        return src
    out = outdir / f"_r3d_{src.stem}_{module or 'top'}.stl"
    if module is None:
        # no module: render the file's top-level
        r = subprocess.run([openscad, "-o", str(out), str(src)], capture_output=True, text=True)
    else:
        r = render_module(openscad, src, module, out, fn=fn)
    if not out.exists():
        sys.exit(f"render failed: {src} [{module}]\n{r.stderr}")
    return out


def resolve_pieces(openscad, inp: Path, parts, fn, outdir) -> list[Path]:
    """List of STLs to paint for `inp` (direct .stl, or front-door modules)."""
    if inp.suffix.lower() == ".stl":
        return [inp]
    if parts:
        mods = [m.strip() for m in parts.split(",") if m.strip()]
    else:
        mods = discover_modules(inp, r"_solid") or discover_modules(inp, r"_print")
        if not mods:
            sys.exit(f"no *_solid/*_print modules found in {inp}; use --parts")
    return [bake(openscad, inp, m, fn, outdir) for m in mods]


def render_iso(openscad, body_lines: list[str], out_png: Path, size: int, rotz: float,
               rotx: float = ISO_RX):
    """Clean iso render (ortho, viewall, autocenter) of the given body, no plane.
    `rotx` = camera elevation (zenith): higher = more from above."""
    with tempfile.NamedTemporaryFile("w", suffix=".scad", delete=False) as f:
        f.write("\n".join(body_lines) + "\n")
        tmp = Path(f.name)
    try:
        cam = f"0,0,0,{rotx},{ISO_RY},{rotz:.1f},100"
        subprocess.run([openscad, "-o", str(out_png), f"--imgsize={size},{size}",
                        "--projection=ortho", "--viewall", "--autocenter",
                        f"--camera={cam}", str(tmp)], capture_output=True, text=True)
    finally:
        tmp.unlink(missing_ok=True)
    if not out_png.exists():
        sys.exit(f"image render failed: {out_png}")


def angles(n: int, rz0: float = ISO_RZ0) -> list[float]:
    return [rz0 + i * 360.0 / max(1, n) for i in range(max(1, n))]


def _first_solid(scad: Path) -> str:
    mods = discover_modules(scad, r"_solid") or discover_modules(scad, r"_print")
    if not mods:
        sys.exit(f"--vs: no *_solid found in {scad}; pass it as an .stl or add a *_solid module")
    return mods[0]


def _heatmap(openscad, ref_stl: Path, model_stls, out_dir: Path, base: str,
             size: int, rzs: list[float], tol: float, rotx: float = ISO_RX):
    """BIDIRECTIONAL deviation heatmap at one or more angles. Colors BOTH surfaces by true
    surface-to-surface distance (handles curves, no slivers):
      - the REFERENCE by its distance to the model → highlights where the model LACKS material,
      - the MODEL by its distance to the reference → highlights where it has EXCESS.
    In the render, at each point you see whichever surface sticks out, so both directions show.
    Bands: green <tol (matches), yellow tol-1, orange 1-2, red ≥2 mm. Returns (dmax, dmean,
    [pngs])."""
    import numpy as np
    import trimesh
    ref = trimesh.load(str(ref_stl), process=True)
    parts = [trimesh.load(str(p), process=True) for p in model_stls]
    mdl = trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0]
    _, d_ref, _ = mdl.nearest.on_surface(ref.triangles_center)   # ref→model (lacking)
    _, d_mdl, _ = ref.nearest.on_surface(mdl.triangles_center)   # model→ref (excess)
    bands = [(max(tol, 1e-6), "lightgreen"), (1.0, "gold"), (2.0, "orange"), (float("inf"), "red")]
    body, tmps = ["$fn=64;"], []
    for tag, mesh, dist in (("r", ref, d_ref), ("m", mdl, d_mdl)):
        lo = 0.0
        for i, (thr, col) in enumerate(bands):
            mask = (dist >= lo) & (dist < thr)
            lo = thr
            if not mask.any():
                continue
            sub = mesh.submesh([np.where(mask)[0]], append=True)
            sp = out_dir / f"_r3d_hm_{tag}{i}.stl"
            sub.export(str(sp))
            tmps.append(sp)
            body.append(f'color("{col}") {_imp(sp)}')
    multi = len(rzs) > 1
    pngs = []
    for rz in rzs:
        png = out_dir / (f"{base}_{int(round(rz)) % 360:03d}.png" if multi else f"{base}.png")
        render_iso(openscad, body, png, size, rz, rotx)
        pngs.append(png)
    for sp in tmps:
        sp.unlink(missing_ok=True)
    both = np.concatenate([d_ref, d_mdl])
    return float(both.max()), float(both.mean()), pngs


def main():
    ap = argparse.ArgumentParser(description="clean 3D iso views + deviation heatmap against a reference")
    ap.add_argument("input", help="front door .scad or an .stl")
    ap.add_argument("--parts", help="front-door module(s) (multicolor), e.g. a or a,b "
                                    "(if omitted: every *_solid)")
    ap.add_argument("--vs", help="reference (.stl/.scad): bidirectional deviation heatmap")
    ap.add_argument("--vs-tol", type=float, default=0.3,
                    help="heatmap: below this (mm) counts as 'matches' (green). Default 0.3.")
    ap.add_argument("--angles", type=int, default=4, help="number of iso views (turntable); default 4")
    ap.add_argument("--rx", type=float, default=ISO_RX,
                    help=f"camera elevation/zenith in degrees (default {ISO_RX}; higher = more from above)")
    ap.add_argument("--rz", type=float, default=ISO_RZ0,
                    help=f"base azimuth of the iso view in degrees (default {ISO_RZ0}; spins the piece)")
    ap.add_argument("--size", type=int, default=900, help="PNG side in px (default 900)")
    ap.add_argument("--fn", type=int, default=None, help="$fn to rasterize the .scad (default: front-door baseline)")
    ap.add_argument("--openscad", help="path to the OpenSCAD binary")
    args = ap.parse_args()

    openscad = locate_openscad(args.openscad)
    inp = Path(args.input)
    if not inp.exists():
        sys.exit(f"does not exist: {inp}")
    outdir = build_dir(inp)
    fn = args.fn
    name = inp.stem

    pieces = resolve_pieces(openscad, inp, args.parts, fn, outdir)
    fnv = fn if fn is not None else (scad_fn_baseline(inp) if inp.suffix.lower() != ".stl" else 64)

    written = []

    if args.vs:
        # Deviation HEATMAP (surface-to-surface distance, bidirectional; handles curves).
        ref = Path(args.vs)
        if not ref.exists():
            sys.exit(f"--vs does not exist: {ref}")
        ref_stl = bake(openscad, ref, _first_solid(ref), fn, outdir) \
            if ref.suffix.lower() != ".stl" else ref
        dmax, dmean, pngs = _heatmap(openscad, ref_stl, pieces, outdir,
                                     f"{name}_vs_{ref.stem}_heatmap", args.size,
                                     angles(args.angles, args.rz), args.vs_tol, args.rx)
        print(f"  heatmap: max deviation {dmax:.2f}mm  mean {dmean:.2f}mm  (bidirectional; "
              f"green<{args.vs_tol} yellow<1 orange<2 red≥2)")
        written += pngs
    else:
        # clean iso views (no cut plane), turntable.
        body0 = [f"$fn={fnv};"]
        for i, p in enumerate(pieces):
            body0.append(f'color("{PALETTE[i % len(PALETTE)]}") {_imp(p)}')
        for rz in angles(args.angles, args.rz):
            out = outdir / f"{name}_iso_{int(round(rz)) % 360:03d}.png"
            render_iso(openscad, body0, out, args.size, rz, args.rx)
            written.append(out)

    for w in written:
        print(f"  {w}")


if __name__ == "__main__":
    main()
