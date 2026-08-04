#!/usr/bin/env python3
"""
Render a .scad piece to STL and report manifold health in one shot:
OpenSCAD's Status + Genus, plus trimesh watertight / volume / bbox.
Replaces the manual `openscad -o ... | grep` + `python -c "import
trimesh..."` dance after every structural edit.

Usage:
    uv run tools/check.py projects/example/main.scad
    uv run tools/check.py main.scad --module lid_print --fn 96
    uv run tools/check.py --all                      # every *.scad of the current project (cwd)
    uv run tools/check.py a.scad b.scad -D CLR=0.2

Interference (clash) check — given >=2 zero-arg modules already in their
seated/world position, no PAIR may overlap. The volume of every pairwise
intersection must be <= --clash-eps (mm3); a positive overlap is a
collision. This is an interference check, NOT a clearance check: parts
that merely touch (0 mm gap) pass — use slice.py --parts
to eyeball the gap itself.
    uv run tools/check.py projects/example/main.scad --parts base_solid,lid_solid
    uv run tools/check.py projects/example/main.scad --parts base_solid,lid_solid --clash-eps 0.05

Exit code is non-zero if any render is not manifold (Status != NoError)
or any pair interferes over eps, so it doubles as a pre-commit / CI gate.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

from _common import (discover_modules, locate_openscad, mesh_min_gap,
                     project_dir, render_module)

# trimesh computes mass properties / closest-points on non-watertight meshes and
# numpy emits fp RuntimeWarnings (divide-by-zero on slivers); they are benign noise
# for a CLI gate (real failures are exceptions or non-manifold Status, not warnings).
warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = Path(__file__).resolve().parent.parent

STATUS_RE = re.compile(r"Status:\s*(\S+)")
GENUS_RE = re.compile(r"Genus:\s*(-?\d+)")
UNKNOWN_RE = re.compile(r"Ignoring unknown module '([^']+)'")
LE_RE = re.compile(r"\blinear_extrude\s*\(\s*(?:h\s*=\s*)?([0-9]*\.?[0-9]+)")


def calque_warning(scad: Path) -> str:
    """Heuristic: a model built by STACKING tens of micro-slice `linear_extrude`s is a section
    CALQUE — the mesh traced layer-by-layer (the anti-pattern an A/B no-harness arm falls into,
    and which a harness arm must NOT). A `linear_extrude` is a perfectly good design primitive;
    the smell is MANY of them at a TINY height (a part sliced into 0.5 mm layers). Source-level
    scan of the passed .scad (self-contained replicas — the case that matters). Non-gating: this
    returns a warning string for `check` to surface, it never flips the manifold verdict."""
    try:
        src = scad.read_text()
    except Exception:
        return ""
    micro = sum(1 for h in LE_RE.findall(src) if float(h) <= 1.5)
    total = len(re.findall(r"\blinear_extrude\b", src))
    if micro >= 12:
        return (f"POSSIBLE CALQUE: {micro} micro-height linear_extrudes (<=1.5mm) stacked — "
                f"looks like the part was CLONED section by section, not a parametric model. "
                f"linear_extrude is fine as a design primitive where it makes sense; NOT for "
                f"tracing the mesh as micro-layers. Rebuild with parametric features "
                f"(analyze + slice → primitives).")
    if total >= 20:
        return (f"POSSIBLE CALQUE: {total} linear_extrudes in the model — check it is not a stack "
                f"of sections (a calque) instead of parametric geometry.")
    return ""


def check_one(openscad_bin: str, scad: Path, module: str | None, fn: int,
              defines: list[str], explicit: bool = True) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        stl = Path(f.name)
    try:
        if module:
            # A named piece of a front-door catalogue: render `use <main>; module()`.
            r = render_module(openscad_bin, scad, module, stl, fn=fn, defines=defines)
        else:
            # No module → render the file's own top level (test pieces, components).
            cmd = [openscad_bin, "-o", str(stl), "-D", f"$fn={fn}"]
            for d in defines:
                cmd += ["-D", d]
            cmd.append(str(scad))
            r = subprocess.run(cmd, capture_output=True, text=True)
        out = r.stdout + r.stderr
        status = (STATUS_RE.search(out) or [None, "?"])[1] if STATUS_RE.search(out) else "?"
        genus = (GENUS_RE.search(out) or [None, "?"])[1] if GENUS_RE.search(out) else "?"
        empty = not (stl.exists() and stl.stat().st_size > 0)
        has_error = "ERROR" in out
        # References that don't resolve render SILENTLY (OpenSCAD only warns and keeps
        # Status=NoError) — a renamed/typo'd module call or a missing `use`/`include`
        # would masquerade as a green render. Treat both as HARD failures.
        broken_refs = (sorted(set(UNKNOWN_RE.findall(out)))
                       + sorted(set(re.findall(r"Can't open library '([^']+)'", out))))
        label = f"{scad.name}" + (f" [{module}]" if module else "")

        # A file meant to be `include`d (shared constants/config) renders no
        # geometry. In a bulk sweep that is not a failure — only flag an empty
        # render when the file was requested explicitly (positional or --module).
        if empty and not has_error and not broken_refs and not explicit:
            print(f"  [-- ] {label:34} no geometry (include/config) — skipped")
            return True

        wt, vol, bbox = "-", "-", "-"
        if not empty:
            try:
                import trimesh
                m = trimesh.load(str(stl), process=True)
                wt = "yes" if m.is_watertight else "NO"
                vol = f"{m.volume / 1000:.1f}cm3"
                lo, hi = m.bounds
                bbox = (f"{hi[0]-lo[0]:.1f}x{hi[1]-lo[1]:.1f}x{hi[2]-lo[2]:.1f}")
            except Exception as e:
                wt = f"trimesh:{e}"

        ok = status == "NoError" and not broken_refs
        flag = "ok " if ok else "ERR"
        print(f"  [{flag}] {label:34} Status={status:8} Genus={genus:>3} "
              f"watertight={wt:4} vol={vol:9} bbox={bbox}")
        if broken_refs:
            print(f"        ↳ FAILURE: reference(s) that do not exist: {', '.join(broken_refs)}")
        cw = calque_warning(scad)
        if cw:
            print(f"        ⚠ {cw}")
        # watertight=NO with a clean Status: typically COINCIDENT/COPLANAR faces
        # (a cutter flush with the wall, stacked solids sharing a face). Warning, not
        # a gate: it can also be a benign trimesh false negative.
        if wt == "NO" and status == "NoError":
            print(f"        ⚠ watertight=NO with Status=NoError: likely "
                  f"coincident/coplanar faces — give difference() cutters a ±EPS "
                  f"overhang and overlap the stacked solids. (If Genus/Status are "
                  f"healthy it may be a benign trimesh artifact from coincident faces.)")
        # surface real warnings/errors
        for ln in out.splitlines():
            if ("WARNING" in ln or "ERROR" in ln) and "Fontconfig" not in ln:
                print(f"        {ln}")
        return ok
    finally:
        stl.unlink(missing_ok=True)


def _body_volume(openscad_bin: str, body: str, fn: int,
                 defines: list[str]) -> tuple[float, list[str]]:
    """Render an inline OpenSCAD body to STL; return (volume_mm3, unknown_modules).
    An empty result (empty intersection, or all-unknown modules) -> volume 0."""
    with tempfile.NamedTemporaryFile("w", suffix=".scad", delete=False) as f:
        f.write(body)
        scad = Path(f.name)
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as g:
        stl = Path(g.name)
    try:
        cmd = [openscad_bin, "-o", str(stl), "-D", f"$fn={fn}"]
        for d in defines:
            cmd += ["-D", d]
        cmd.append(str(scad))
        r = subprocess.run(cmd, capture_output=True, text=True)
        unknown = sorted(set(UNKNOWN_RE.findall(r.stdout + r.stderr)))
        vol = 0.0
        if stl.exists() and stl.stat().st_size > 0:
            try:
                import trimesh
                vol = float(trimesh.load(str(stl), process=True).volume)
            except Exception:
                vol = 0.0
        return vol, unknown
    finally:
        scad.unlink(missing_ok=True)
        stl.unlink(missing_ok=True)


def _render_mesh(openscad_bin: str, body: str, fn: int, defines: list[str]):
    """Render an inline OpenSCAD body to STL; return (trimesh|None, unknown_modules).
    None when nothing rendered (empty / all-unknown modules / load error)."""
    with tempfile.NamedTemporaryFile("w", suffix=".scad", delete=False) as f:
        f.write(body)
        scad = Path(f.name)
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as g:
        stl = Path(g.name)
    try:
        cmd = [openscad_bin, "-o", str(stl), "-D", f"$fn={fn}"]
        for d in defines:
            cmd += ["-D", d]
        cmd.append(str(scad))
        r = subprocess.run(cmd, capture_output=True, text=True)
        unknown = sorted(set(UNKNOWN_RE.findall(r.stdout + r.stderr)))
        mesh = None
        if stl.exists() and stl.stat().st_size > 0:
            try:
                import trimesh
                mesh = trimesh.load(str(stl), process=True)
                if mesh.is_empty or len(mesh.vertices) == 0:
                    mesh = None
            except Exception:
                mesh = None
        return mesh, unknown
    finally:
        scad.unlink(missing_ok=True)
        stl.unlink(missing_ok=True)


def clash_check(openscad_bin: str, scad: Path, parts: list[str], fn: int,
                defines: list[str], eps: float, min_gap: float | None = None) -> bool:
    """Pairwise INTERFERENCE + CLEARANCE check. Each part is a zero-arg module
    already in its seated/world position. For every pair:
      - interference: the CSG intersection volume must be <= eps (a positive
        overlap is a collision), rendered via OpenSCAD (manifold-check authority).
      - clearance: for non-overlapping pairs, the min surface-to-surface gap (mm,
        sampled proximity) — this is what clash=0 can't tell you (touch vs gap).
        Fails if any clear pair is closer than min_gap (when given).
    -D constant overrides do NOT reach `use`d modules, so parts render with the
    file's default constants. Returns True if no pair overlaps / under-gaps."""
    piece = scad.resolve().as_posix()
    hdr = f"clash+gap check (eps={eps:g} mm3"
    hdr += f", min-gap={min_gap:g} mm" if min_gap is not None else ""
    print(hdr + f"): {scad.name}")
    ok = True

    # Render each part once to a mesh; reused for the empty-module sanity and the
    # pairwise clearance. A typo'd/empty module would make every result vacuous.
    meshes: dict[str, object] = {}
    for p in parts:
        mesh, unknown = _render_mesh(
            openscad_bin, f"use <{piece}>\n$fn={fn};\n{p}();\n", fn, defines)
        if unknown:
            print(f"  [ERR] module '{p}' unknown — not defined in {scad.name}")
            ok = False
        elif mesh is None:
            print(f"  [warn] module '{p}' renders empty — its results are meaningless")
        meshes[p] = mesh

    # Pairwise: overlap volume (CSG); and, when clear, the min clearance (mm).
    n = len(parts)
    overlap: dict[tuple[int, int], float] = {}
    gap: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            v, _ = _body_volume(
                openscad_bin,
                f"use <{piece}>\n$fn={fn};\n"
                f"intersection() {{ {parts[i]}(); {parts[j]}(); }}\n", fn, defines)
            overlap[(i, j)] = v
            mi, mj = meshes[parts[i]], meshes[parts[j]]
            gap[(i, j)] = (mesh_min_gap(mi, mj)[0]
                           if (v <= eps and mi is not None and mj is not None)
                           else float("nan"))

    # Matrix (upper triangle): clearance in mm, or "OVL" when the pair overlaps.
    w = max(8, max(len(p) for p in parts) + 1)
    print("  gap(mm)/OVL " + "".join(f"{p:>{w}}" for p in parts))
    for i, pi in enumerate(parts):
        row = f"{pi:>{max(w, 12)}}"
        for j in range(n):
            if j < i:
                cell = ""
            elif j == i:
                cell = "-"
            elif overlap[(i, j)] > eps:
                cell = "OVL"
            else:
                g = gap[(i, j)]
                cell = "?" if g != g else f"{g:.2f}"
            row += f"{cell:>{w}}"
        print("  " + row)

    # Gate 1: interference (overlaps).
    overs = [(parts[i], parts[j], v) for (i, j), v in overlap.items() if v > eps]
    for a, b, v in sorted(overs, key=lambda t: -t[2]):
        ok = False
        print(f"  [ERR] {a} & {b} overlap = {v:.3f} mm3  (collision)")
    # Gate 2: clearance (only when --min-gap given).
    if min_gap is not None:
        unders = [(parts[i], parts[j], gap[(i, j)]) for (i, j) in gap
                  if gap[(i, j)] == gap[(i, j)] and gap[(i, j)] < min_gap]
        for a, b, g in sorted(unders, key=lambda t: t[2]):
            ok = False
            print(f"  [ERR] {a} & {b} clearance = {g:.2f} mm  (< {min_gap:g})")
    if ok:
        print("  [ok ] no interference; clearances " +
              ("OK" if min_gap is not None else "shown above"))
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scad", nargs="*", type=Path)
    ap.add_argument("--all", action="store_true",
                    help="check every *.scad in the current project (cwd)")
    ap.add_argument("--all-projects", action="store_true",
                    help="check every project's pieces + test pieces (CI sweep)")
    ap.add_argument("--module", default=None,
                    help="render this named module of a front door (use <main>; "
                         "module()) instead of the file's top level")
    ap.add_argument("--fn", type=int, default=64)
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--openscad", default=None)
    ap.add_argument("--parts", default=None,
                    help="comma list of zero-arg module names in seated/world "
                         "position; runs a pairwise interference (clash) check "
                         "on the single given .scad, e.g. --parts base_solid,lid_solid")
    ap.add_argument("--clash-eps", type=float, default=0.01,
                    help="max tolerated pairwise intersection volume in mm3 "
                         "(default 0.01; absorbs coplanar-seating slivers)")
    ap.add_argument("--min-gap", type=float, default=None,
                    help="with --parts: minimum tolerated CLEARANCE (mm) between "
                         "any non-overlapping pair; fails the gate if any clear "
                         "pair is closer (default: report only, no gate)")
    args = ap.parse_args()

    explicit_paths = {f.resolve() for f in args.scad}  # asked-for by name
    files = list(args.scad)
    if args.all:
        files += sorted(project_dir(Path.cwd()).glob("*.scad"))
    if args.all_projects:
        files += sorted((ROOT / "projects").glob("*/*.scad"))
        files += sorted((ROOT / "projects").glob("*/test/*.scad"))
        files += sorted((ROOT / "components").glob("test/*.scad"))
        files += sorted(ROOT.glob("*.scad"))  # loose root pieces (pre-migration)
    # stl_assembly.scad is a generated STL→parametric reference scaffold (make_assembly.py),
    # not a deliverable/test piece: its top level is a bare import() (no Status line, no *_print
    # module), so a bulk sweep would false-fail on it. Skip in sweeps; still checkable if named.
    files = [f for f in files
             if f.name != "stl_assembly.scad" or f.resolve() in explicit_paths]
    # dedupe, preserve order
    seen, uniq = set(), []
    for f in files:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(f)
    files = uniq
    if not files:
        sys.exit("nothing to check; pass files, --all, or --all-projects")

    openscad_bin = locate_openscad(args.openscad)
    all_ok = True

    # With --parts the file may be a pure assembly harness (seated modules, no
    # printable top level), so the manifold pass only runs when there is
    # something to render: no --parts, or --parts WITH an explicit --module.
    if not args.parts or args.module is not None:
        print("manifold check:")
        for scad in files:
            if not scad.exists():
                print(f"  [ERR] {scad}: no such file")
                all_ok = False
                continue
            is_explicit = (args.module is not None
                           or scad.resolve() in explicit_paths)
            # In a sweep (not explicitly named, no --module), a front door renders
            # only its default-view call — leaving the deliverables unchecked.
            # Discover its `*_print` pieces and check each by name.
            pieces = ([] if (args.module is not None or is_explicit)
                      else discover_modules(scad, r'_print'))
            if pieces:
                for pc in pieces:
                    all_ok &= check_one(openscad_bin, scad, pc, args.fn,
                                        args.defines, explicit=False)
            else:
                all_ok &= check_one(openscad_bin, scad, args.module, args.fn,
                                    args.defines, explicit=is_explicit)

    if args.parts:
        if len(files) != 1:
            sys.exit("--parts needs exactly one .scad (the assembly that "
                     "defines the seated modules)")
        if not files[0].exists():
            sys.exit(f"no such file: {files[0]}")
        parts = [p.strip() for p in args.parts.split(",") if p.strip()]
        if len(parts) < 2:
            sys.exit("--parts needs at least two modules to check for clashes")
        if args.module is not None:
            print()
        all_ok &= clash_check(openscad_bin, files[0], parts, args.fn,
                              args.defines, args.clash_eps, args.min_gap)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
