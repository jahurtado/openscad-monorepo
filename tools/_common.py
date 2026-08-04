#!/usr/bin/env python3
"""
Shared helpers for the monorepo tools — the single source for three things
every render/inspect tool needs, so they don't each re-roll them:

  - locate_openscad()  : find the OpenSCAD binary (PATH, /Applications, Program Files)
  - repo_root()        : the repo root (parent of this tools/ dir)
  - project_dir(path)  : the project a file belongs to (a child of projects/,
                         or the top-level components/ or lib/ dir)
  - build_dir(path)    : that project's build/ dir (created), where a tool's
                         outputs go — never a single global build/.

Imported as a sibling: tools run as `uv run tools/<x>.py`, so tools/ is on
sys.path[0] and `from _common import ...` resolves.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WINDOWS_DEFAULT = r"C:\Program Files\OpenSCAD\openscad.exe"
# macOS installs to /Applications and never lands on PATH; glob covers
# versioned bundles (OpenSCAD-2024.app, nightly, …).
MACOS_GLOB = "/Applications/OpenSCAD*.app/Contents/MacOS/OpenSCAD"


def locate_openscad(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    found = shutil.which("openscad")
    if found:
        return found
    for cand in [WINDOWS_DEFAULT, *sorted(glob.glob(MACOS_GLOB), reverse=True)]:
        if os.path.exists(cand):
            return cand
    sys.exit("openscad executable not found; pass --openscad <path>")


def repo_root() -> Path:
    """Repo root = parent of the tools/ dir holding this file."""
    return Path(__file__).resolve().parent.parent


def project_dir(path) -> Path:
    """The project a file belongs to, for deciding where its build/ lives:
      - <root>/projects/<name>/...      -> <root>/projects/<name>
      - <root>/components/... | lib/... -> <root>/components | <root>/lib
      - anything else (loose file at the root, pre-migration) -> <root>
    """
    p = Path(path).resolve()
    root = repo_root()
    try:
        rel = p.relative_to(root)
    except ValueError:
        return p.parent
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "projects":
        return root / "projects" / parts[1]
    if parts and parts[0] in ("components", "lib"):
        return root / parts[0]
    return root


def build_dir(path) -> Path:
    """The build/ dir for a file's project (created if missing).

    build/ is EPHEMERAL working output (inspection PNGs, temp STLs) — gitignored.
    Final STL deliverables go to prints/ instead (see prints_dir)."""
    d = project_dir(path) / "build"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prints_dir(path) -> Path:
    """The prints/ dir for a file's project (created if missing).

    prints/ holds the FINAL STL deliverables (what you slice/print), kept apart
    from the ephemeral build/ so they don't get mixed with — or wiped alongside —
    working renders. Gitignored too (STLs are large, regenerable from the .scad)."""
    d = project_dir(path) / "prints"
    d.mkdir(parents=True, exist_ok=True)
    return d


_FN_RE = re.compile(r'^\s*\$fn\s*=\s*([\d.]+)', re.M)


def scad_fn_baseline(main_scad, default: int = 180) -> str:
    """The `$fn` baseline declared at top level of a front door. A throwaway that
    `use`s the front door does NOT inherit it (`use` ignores top-level statements),
    so render helpers re-set it to keep print quality. Falls back to `default`."""
    try:
        m = _FN_RE.search(Path(main_scad).read_text())
    except OSError:
        m = None
    return m.group(1) if m else str(default)


def discover_modules(main_scad, suffix: str) -> list[str]:
    """Top-level `module <name><suffix>` names defined in a front door, in source
    order, de-duplicated. `suffix` is a regex tail anchored by a word boundary —
    e.g. r'_print' (build deliverables) or r'_solid' (inspection solids).

    The front door is a catalogue of named modules; tools discover the pieces by
    name (this regex over the source), not by a dispatch variable."""
    try:
        text = Path(main_scad).read_text()
    except OSError:
        return []
    pat = re.compile(r'^\s*module\s+(\w+' + suffix + r')\b', re.M)
    seen: set[str] = set()
    out: list[str] = []
    for name in pat.findall(text):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def render_module(openscad: str, main_scad, module: str, out_stl,
                  fn=None, defines=()) -> subprocess.CompletedProcess:
    """Render ONE named module of a front door to `out_stl`, via a throwaway
    `use <main>; <module>();`. A front door exposes each piece as a named module,
    and tools name it directly.

    `use <main>` brings in main's module definitions but drops its top-level
    statements (the `$fn` baseline and the default-view call), so we re-set `$fn`
    to the file baseline (or `fn`). main's own relative `use <modules/...>` resolve
    against main's directory, so the throwaway can live anywhere. Returns the
    CompletedProcess (inspect .stdout/.stderr for OpenSCAD warnings)."""
    main_scad = Path(main_scad).resolve()
    fnv = fn if fn is not None else scad_fn_baseline(main_scad)
    body = f"use <{main_scad.as_posix()}>\n$fn={fnv};\n{module}();\n"
    with tempfile.NamedTemporaryFile("w", suffix=".scad", delete=False) as f:
        f.write(body)
        tw = Path(f.name)
    try:
        cmd = [openscad, "-o", str(out_stl)]
        for d in defines:
            cmd += ["-D", d]
        cmd.append(str(tw))
        return subprocess.run(cmd, capture_output=True, text=True)
    finally:
        tw.unlink(missing_ok=True)


def mesh_min_gap(a, b, n: int = 3000):
    """Approx. minimum surface-to-surface CLEARANCE (mm) between two trimesh
    meshes, plus the closest pair of points (pa on `a`, pb on `b`).

    This is the *clearance* the clash check explicitly does NOT measure (clash
    only flags overlap; a 0 mm³ overlap can't tell "touching" from "1 mm apart").
    Sampling-based (area-weighted surface samples + vertices), so it's an
    approximation that tightens with `n`; returns ~0 when the meshes touch or
    overlap (real overlap is for the clash check to report).

    Returns (gap_mm, pa, pb). trimesh/numpy imported lazily so importing this
    module stays cheap for tools that don't need geometry.
    """
    import numpy as np
    import trimesh
    qa = np.vstack([a.sample(n), a.vertices])  # query points on A
    qb = np.vstack([b.sample(n), b.vertices])  # query points on B
    with np.errstate(all="ignore"):  # trimesh's triangle closest-point divides by 0 on slivers
        cb, db, _ = trimesh.proximity.ProximityQuery(b).on_surface(qa)  # nearest B-pt per A-query
        ca, da, _ = trimesh.proximity.ProximityQuery(a).on_surface(qb)  # nearest A-pt per B-query
    ia, ib = int(np.argmin(db)), int(np.argmin(da))
    return ((float(db[ia]), qa[ia], cb[ia]) if db[ia] <= da[ib]
            else (float(da[ib]), ca[ib], qb[ib]))
