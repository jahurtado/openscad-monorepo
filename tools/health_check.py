#!/usr/bin/env python3
"""
Pre-flight health check for the whole tool chain. Run it once after setup
and any time before starting design work — it proves nothing is missing
or misconfigured BEFORE a render fails three steps into a task.

It does NOT just `import x`: the failure mode that bites here is deferred
dependencies (trimesh imports fine, then `mesh.section()` blows up because
scipy/networkx/rtree aren't there). So it EXERCISES the real paths:

  - every required Python module imports (+ version)
  - trimesh.section + to_2D actually runs on a box (proves the section
    stack is live, not just installed)
  - matplotlib renders off-screen (slice _plot)
  - dimsketch renders a dimensioned figure (drawings/<name>_dims.py)
  - dxf_smoother round-trips a coarse-arc fixture: parse -> smooth ->
    write -> reparse, asserting smoothing actually adds points
  - OpenSCAD is locatable, reports a version, and round-trips a cube
    .scad -> STL -> trimesh (proves check.py / slice.py will work)
  - every tool script imports + parses args (--help exits 0)

Exits non-zero if anything fails, so it doubles as a CI / pre-commit gate.

Usage:
    uv run tools/health_check.py
    uv run tools/health_check.py --openscad /path/to/openscad   # if auto-detect fails
"""
from __future__ import annotations

import argparse
import importlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows consoles default to cp1252 and choke on any stray non-ASCII.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# (module, why it matters) — kept in lockstep with pyproject.toml dependencies.
REQUIRED_MODULES = [
    ("numpy", "everything numeric"),
    ("trimesh", "mesh load / section / export"),
    ("manifold3d", "trimesh boolean backend"),
    ("scipy", "graph traversal behind mesh.section()"),
    ("networkx", "closed-loop graphs in section"),
    ("rtree", "enclosure tree (holes inside loops)"),
    ("shapely", "sections / hole classification (slice, analyze)"),
    ("matplotlib", "slice _plot (sections + dimensions)"),
]
TOOLS = ["center_input", "dxf_smoother", "analyze", "run_batch", "check", "compare", "build", "make_assembly", "slice", "slice_viewer", "render3d", "gallery"]

results: list[tuple[bool, str]] = []


def record(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name))
    print(f"  [{'ok ' if ok else 'ERR'}] {name:30} {detail}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Pre-flight health check for the tool chain.")
    ap.add_argument("--openscad", default=None,
                    help="explicit OpenSCAD path if auto-detect fails")
    args = ap.parse_args()

    v = sys.version_info
    print("tooling health check\n")
    print(f"interpreter   python {v.major}.{v.minor}.{v.micro}  ({sys.executable})")
    if ".venv" not in sys.prefix:
        print("  note: not running from .venv — if deps fail below, see README.md (Prerequisites)")

    print("\npython dependencies:")
    for mod, why in REQUIRED_MODULES:
        try:
            m = importlib.import_module(mod)
            record(True, mod, f"{getattr(m, '__version__', '?'):12} ({why})")
        except Exception:
            record(False, mod,
                   f"MISSING ({why}) — fix: uv sync")

    sys.path.insert(0, str(HERE))  # tools/ on path for sibling imports

    print("\nfunctional checks:")
    try:
        import trimesh
        box = trimesh.creation.box(extents=(10, 10, 4))
        sec = box.section(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1])
        n = len(sec.to_2D()[0].polygons_full)
        assert n == 1, f"expected 1 loop, got {n}"
        record(True, "trimesh.section + to_2D",
               "box cross-section OK (scipy/networkx/rtree/shapely all live)")
    except Exception as e:
        record(False, "trimesh.section + to_2D", f"{type(e).__name__}: {e}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        fig.savefig(io.BytesIO())
        plt.close(fig)
        record(True, "matplotlib Agg render", f"{matplotlib.__version__}")
    except Exception as e:
        record(False, "matplotlib Agg render", f"{type(e).__name__}: {e}")

    try:
        import matplotlib.pyplot as plt
        import dimsketch as ds
        fig, ax = plt.subplots()
        ds.board_outline(ax, 10, 10, 1)
        ds.dim_h(ax, -5, 5, 7, "10.0", ds.MEASURED)
        ds.legend(fig)
        fig.savefig(io.BytesIO())
        plt.close(fig)
        record(True, "dimsketch render", "plan dimension + legend OK (drawings/<name>_dims.py)")
    except Exception as e:
        record(False, "dimsketch render", f"{type(e).__name__}: {e}")

    try:
        import dxf_smoother as dxf
        fx = HERE / "fixtures" / "coarse_arc.dxf"
        lines = dxf.DXFParser(str(fx)).parse()
        plys = dxf.PolylineBuilder(lines).build_polylines()
        before = sum(len(p) for v in plys.values() for p in v)
        sm = dxf.CurveSmoother()
        smoothed = {L: [sm.smooth(p) for p in v] for L, v in plys.items()}
        after = sum(len(p) for v in smoothed.values() for p in v)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.dxf"
            dxf.DXFWriter(str(out)).write(smoothed)
            reparsed = dxf.DXFParser(str(out)).parse()
        assert after > before and len(reparsed) > len(lines), "no points added"
        record(True, "dxf_smoother round-trip",
               f"fixture {before}->{after} pts, {len(lines)}->{len(reparsed)} segs")
    except Exception as e:
        record(False, "dxf_smoother round-trip", f"{type(e).__name__}: {e}")

    print("\nopenscad:")
    osc = None
    try:
        from _common import locate_openscad
        try:
            osc = locate_openscad(args.openscad)
        except SystemExit:
            osc = None
    except Exception as e:
        record(False, "import _common", f"{type(e).__name__}: {e}")

    if not osc:
        record(False, "locate openscad",
               "not found in PATH / /Applications / Program Files — "
               "pass --openscad or install OpenSCAD")
    else:
        record(True, "locate openscad", osc)
        try:
            r = subprocess.run([osc, "--version"], capture_output=True,
                               text=True, timeout=30)
            blob = (r.stdout + r.stderr).strip().splitlines()
            record(True, "openscad --version", blob[0] if blob else "?")
        except Exception as e:
            record(False, "openscad --version", f"{type(e).__name__}: {e}")
        try:
            import trimesh
            with tempfile.TemporaryDirectory() as d:
                scad, stl = Path(d) / "t.scad", Path(d) / "t.stl"
                scad.write_text("cube([10,10,10]);\n")
                r = subprocess.run([osc, "-o", str(stl), str(scad)],
                                   capture_output=True, text=True, timeout=60)
                if stl.exists() and stl.stat().st_size > 0:
                    m = trimesh.load(str(stl), process=True)
                    record(True, "openscad render roundtrip",
                           f"cube vol={m.volume:.0f}mm3 watertight={m.is_watertight}")
                else:
                    record(False, "openscad render roundtrip",
                           (r.stderr or "no STL produced").strip()[:120])
        except Exception as e:
            record(False, "openscad render roundtrip", f"{type(e).__name__}: {e}")

    print("\ntool scripts (import + argparse via --help):")
    for t in TOOLS:
        try:
            r = subprocess.run([sys.executable, str(HERE / f"{t}.py"), "--help"],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                record(True, f"{t}.py", "OK")
            else:
                tail = (r.stderr.strip().splitlines() or ["?"])[-1]
                record(False, f"{t}.py", tail)
        except Exception as e:
            record(False, f"{t}.py", f"{type(e).__name__}: {e}")

    fails = [n for ok, n in results if not ok]
    print()
    if fails:
        print(f"HEALTH CHECK FAILED — {len(fails)} problem(s): {', '.join(fails)}")
        return 1
    print(f"ALL {len(results)} CHECKS PASSED — tooling ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
