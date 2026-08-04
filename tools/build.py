#!/usr/bin/env python3
"""
Build STL(s) for a project's pieces from its main.scad front door.

ONE generic builder for the whole monorepo (no per-project scripts, no
Makefile). Point it at a project — by name, by directory, or by a path to a
main.scad — and it renders its piece modules to that project's prints/. The
pieces are DISCOVERED from main.scad's `module <x>_print()` definitions (the
catalogue-by-convention front door), so nothing needs per-project configuration.

By default it builds ONE STL PER PIECE — every `*_print` module (the repo
convention `<piece>_print`), each to its own STL. Name explicit module(s) to
build just those.

Usage:
    uv run tools/build.py example                    # one STL per piece: example_base_print.stl, example_lid_print.stl
    uv run tools/build.py example lid_print          # a named piece module
    uv run tools/build.py example --list             # list main.scad's *_print pieces
    uv run tools/build.py example --inspect          # build + regenerate main.batch sections
    uv run tools/build.py projects/example/main.scad     # path also works
    uv run tools/build.py --all-projects             # one STL per piece, every project (CI build)
    uv run tools/build.py --all-projects --inspect   # build + inspect images, every project

Each piece is rendered via a throwaway `use <main>; <piece>();` (see
_common.render_module) — main.scad is a catalogue of named modules, each piece
named directly. STLs land in projects/<name>/prints/<name>_<piece>.stl — the FINAL
deliverables, kept apart from the ephemeral build/. prints/ is gitignored.
Renders use the file's $fn baseline (print quality) unless --fn overrides it.
Exit code is non-zero if any render produced no STL — doubles as a gate.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _common import (discover_modules, locate_openscad, prints_dir,
                     project_dir, render_module, repo_root)

ROOT = repo_root()


def print_modules(main_scad: Path) -> list[str]:
    """The deliverable pieces of a front door: every top-level `module <x>_print()`
    (repo convention `<piece>_print`), one STL each. The front door is a catalogue
    of named modules — discovered by name (this regex over the source)."""
    return discover_modules(main_scad, r'_print')


def resolve_main(arg: str) -> Path:
    """Resolve a project NAME, a project DIR, or a path to a .scad → main.scad."""
    p = Path(arg)
    for cand in (p, p / "main.scad", ROOT / "projects" / arg / "main.scad"):
        if cand.is_file():
            return cand.resolve()
    sys.exit(f"no main.scad for {arg!r} "
             f"(try a project name like 'example', a dir, or a path to main.scad)")


def run_inspect(main_scad: Path, openscad: str | None) -> bool:
    """Regenerate the project's iteration sections from its main.batch manifest (shells
    out to run_batch.py, which delegates each line to slice.py). A project without a
    main.batch is skipped, not an error."""
    manifest = main_scad.with_name("main.batch")
    name = project_dir(main_scad).name
    if not manifest.exists():
        print(f"inspect {name}:  (no main.batch, skipping)")
        return True
    cmd = [sys.executable, str(ROOT / "tools" / "run_batch.py"), str(main_scad)]
    if openscad:
        cmd += ["--openscad", openscad]
    sys.stdout.flush()  # the subprocess writes to the fd directly; flush our
    return subprocess.run(cmd).returncode == 0  # buffered output first so order holds


def build_one(openscad: str, main_scad: Path, target: str, fn: int | None) -> bool:
    stem = project_dir(main_scad).name
    out = prints_dir(main_scad) / f"{stem}_{target}.stl"
    r = render_module(openscad, main_scad, target, out, fn=fn)
    ok = out.exists() and out.stat().st_size > 0
    print(f"  {out.name:40} {'ok' if ok else 'FAILED'}")
    if not ok:
        for ln in (r.stdout + r.stderr).splitlines():
            if "ERROR" in ln or "WARNING" in ln:
                print(f"      {ln}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?",
                    help="project name, directory, or path to main.scad")
    ap.add_argument("targets", nargs="*",
                    help="piece modules to build (default: every *_print module)")
    ap.add_argument("--all", action="store_true",
                    help="build every *_print module (same as no targets)")
    ap.add_argument("--all-projects", action="store_true",
                    help="build every project under projects/ (one STL per piece each)")
    ap.add_argument("--inspect", action="store_true",
                    help="after building, also regenerate the project's inspection "
                         "sections from its main.batch manifest (PNGs -> build/)")
    ap.add_argument("--list", action="store_true",
                    help="list main.scad's *_print piece modules and exit")
    ap.add_argument("--fn", type=int, default=None,
                    help="override $fn (default: file baseline = print quality)")
    ap.add_argument("--openscad", default=None)
    args = ap.parse_args()

    openscad = locate_openscad(args.openscad)

    if args.all_projects:
        mains = sorted((ROOT / "projects").glob("*/main.scad"))
        if not mains:
            sys.exit("no projects found under projects/")
        all_ok = True
        for m in mains:
            targets = print_modules(m)
            print(f"build {project_dir(m).name}:")
            if targets:
                for t in targets:
                    all_ok &= build_one(openscad, m, t, args.fn)
            else:
                print("  (nothing to build: no *_print modules)")
            if args.inspect:
                all_ok &= run_inspect(m, args.openscad)
        sys.exit(0 if all_ok else 1)

    if not args.project:
        ap.error("project is required (or use --all-projects)")
    main_scad = resolve_main(args.project)
    pieces = print_modules(main_scad)

    if args.list:
        print(f"{main_scad.relative_to(ROOT)} *_print pieces:")
        for m in pieces:
            print(f"  {m}")
        return

    if args.targets:
        targets = args.targets
        known = set(discover_modules(main_scad, r''))  # every top-level module name
        unknown = [t for t in targets if known and t not in known]
        if unknown:
            print(f"  (warning: not a module in main.scad: {', '.join(unknown)})")
    else:  # default (and --all): one STL per *_print piece
        targets = pieces
        if not targets:
            sys.exit(f"{main_scad.name}: nothing to build (no *_print modules); "
                     f"use --list or name a module")

    print(f"build {project_dir(main_scad).name}:")
    all_ok = all(build_one(openscad, main_scad, t, args.fn) for t in targets)
    if args.inspect:
        all_ok &= run_inspect(main_scad, args.openscad)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
