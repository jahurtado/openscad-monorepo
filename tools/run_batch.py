#!/usr/bin/env python3
"""
run_batch — regenerate a .scad's inspection set from its `<stem>.batch` manifest.

A thin ORCHESTRATOR: it reads the `<stem>.batch` sitting next to the target `.scad`
(`main.scad`→`main.batch`, `stl_assembly.scad`→`stl_assembly.batch`), one section per line,
and shells out to slice.py for each, naming the output by the line's name. It owns no
geometry — the section work is slice's; this just runs the batch. `build --inspect` calls it
after building the STLs, so the iteration sections regenerate alongside the deliverables.

batch line:  <name>  <spec>  [parts=a,b]   # comment
  spec = a central section  top|front|side  (cut through the part centre), or an explicit
         plane  z=3.1 / x=-10 / y=0.  A bare `front` (one token) uses the spec as the name.
  parts = front-door modules to slice (multi-colour + per-face gaps); default all *_solid.

Each line -> slice.py <scad> <spec> --name <name> [--parts …] --only plot,preview
          -> build/<stem>_<name>_{plot,preview}.png. build/ is cleaned first so it holds
             only the latest set.

Usage:
    uv run tools/run_batch.py example                            # → main.scad / main.batch
    uv run tools/run_batch.py projects/example/main.scad
    uv run tools/run_batch.py stl_assembly.scad                  # → stl_assembly.batch
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _common import build_dir, project_dir, repo_root

ROOT = repo_root()
HERE = Path(__file__).resolve().parent


def resolve_main(arg: str) -> Path:
    """Resolve a project NAME or DIR → its main.scad, or a path to ANY .scad → that .scad
    (so `stl_assembly.scad` works, not just `main.scad`). The manifest is always the
    `<stem>.batch` next to the resolved file."""
    p = Path(arg)
    for cand in (p, p / "main.scad", ROOT / "projects" / arg / "main.scad"):
        if cand.is_file():
            return cand.resolve()
    sys.exit(f"no .scad for {arg!r} (project name, dir, or path to a .scad)")


def parse_line(line: str):
    """`<name> <spec> [parts=…]` -> (name, spec, parts|None). A one-token line uses the
    spec as the name (e.g. `front`). Returns None for blanks/comments."""
    line = line.split("#", 1)[0].strip()
    if not line:
        return None
    f = line.split()
    name = f[0]
    spec = f[1] if len(f) > 1 and not f[1].startswith("parts=") else f[0]
    parts = next((t[len("parts="):] for t in f[1:] if t.startswith("parts=")), None)
    return name, spec, parts


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="project name/dir (→ main.scad), or a path to a .scad")
    ap.add_argument("--openscad", default=None)
    args = ap.parse_args()

    main_scad = resolve_main(args.project)
    manifest = main_scad.with_name(main_scad.stem + ".batch")     # main.scad→main.batch, stl_assembly.scad→stl_assembly.batch
    if not manifest.exists():
        sys.exit(f"no {manifest.relative_to(ROOT)} (the list of sections to regenerate)")
    build = build_dir(main_scad)
    stem = main_scad.stem
    for f in build.glob(f"{stem}_*"):            # clean the previous set first (files only —
        if f.is_file():                          # skip dirs like slice_viewer's <stem>_slices/)
            f.unlink()

    lines = [x for x in (parse_line(L) for L in manifest.read_text().splitlines()) if x]
    print(f"batch {project_dir(main_scad).name}: {len(lines)} sections")
    ok = True
    for name, spec, parts in lines:
        cmd = [sys.executable, str(HERE / "slice.py"), str(main_scad), spec,
               "--name", name, "--only", "plot,preview"]
        if parts:
            cmd += ["--parts", parts]
        if args.openscad:
            cmd += ["--openscad", args.openscad]
        r = subprocess.run(cmd, capture_output=True, text=True)
        good = r.returncode == 0 and (build / f"{stem}_{name}_plot.png").exists()
        ok = ok and good
        print(f"  {name:14} {spec:12} {'ok' if good else 'FAIL'}")
        if not good:
            print("    " + ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1])

    for f in build.glob(f"{stem}__slice_*.stl"):   # drop slice's intermediate renders
        f.unlink()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
