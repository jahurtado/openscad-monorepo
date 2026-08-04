#!/usr/bin/env python3
"""
Centers STL or DXF input files for use as design references in OpenSCAD wrappers.

Default mode for STL: XY bbox centroid at origin, Z bbox-min at 0
(the object sits on the Z=0 plane, centered in plan). Default mode for
DXF: bbox centroid at origin.

Always writes to a new file. The original input is left untouched.
Default output path: <stem>_centered<ext> next to the input.

Usage:
    uv run tools/center_input.py INPUT
    uv run tools/center_input.py INPUT -o OUTPUT
    uv run tools/center_input.py INPUT -m centroid
    uv run tools/center_input.py profile.dxf --smooth --angle 10 --points 6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from dxf_smoother import (
    CurveSmoother,
    DXFParser,
    DXFWriter,
    Point,
    PolylineBuilder,
)


def _resolve_output(input_path: Path, output: str | None) -> Path:
    if output:
        return Path(output)
    return input_path.parent / f"{input_path.stem}_centered{input_path.suffix}"


def _stl_offset(bounds, mode: str) -> Tuple[float, float, float]:
    (xmin, ymin, zmin), (xmax, ymax, zmax) = bounds
    if mode == "xy-base":
        return (-(xmin + xmax) / 2.0, -(ymin + ymax) / 2.0, -zmin)
    if mode == "centroid":
        return (-(xmin + xmax) / 2.0, -(ymin + ymax) / 2.0, -(zmin + zmax) / 2.0)
    if mode == "min":
        return (-xmin, -ymin, -zmin)
    raise ValueError(f"unknown mode: {mode}")


def _fmt_bbox3(b) -> str:
    (xmin, ymin, zmin), (xmax, ymax, zmax) = b
    return (
        f"x[{xmin:+.2f}..{xmax:+.2f}] "
        f"y[{ymin:+.2f}..{ymax:+.2f}] "
        f"z[{zmin:+.2f}..{zmax:+.2f}]"
    )


def _fmt_bbox2(b) -> str:
    (xmin, ymin), (xmax, ymax) = b
    return f"x[{xmin:+.2f}..{xmax:+.2f}] y[{ymin:+.2f}..{ymax:+.2f}]"


def center_stl(input_path: Path, output_path: Path, mode: str, flip: str) -> None:
    try:
        import trimesh
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "trimesh required for STL centering. "
            "Install with: uv sync"
        ) from exc

    mesh = trimesh.load(str(input_path), force="mesh")
    if mesh.is_empty:
        raise RuntimeError(f"{input_path}: empty mesh")

    bounds_before = mesh.bounds.copy()

    # Optional 180° flip around X, Y, or Z BEFORE centering. The bbox
    # changes after the flip, so the offset is computed on the rotated
    # mesh — net effect for --flip y --mode xy-base: connectors switch
    # X side AND the original top face lands on z=0.
    if flip != "none":
        axis_vec = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[flip]
        R = trimesh.transformations.rotation_matrix(np.pi, axis_vec)
        mesh.apply_transform(R)

    dx, dy, dz = _stl_offset(mesh.bounds, mode)
    mesh.apply_translation((dx, dy, dz))
    bounds_after = mesh.bounds

    mesh.export(str(output_path))

    print("STL centered:")
    print(f"  in   : {input_path}")
    print(f"  out  : {output_path}")
    print(f"  mode : {mode}")
    print(f"  flip : {flip}")
    print(f"  bbox before: {_fmt_bbox3(bounds_before)}")
    print(f"  bbox after : {_fmt_bbox3(bounds_after)}")
    print(f"  offset     : ({dx:+.3f}, {dy:+.3f}, {dz:+.3f})")


def _dxf_bounds(polylines: Dict[str, List[List[Point]]]):
    xs: List[float] = []
    ys: List[float] = []
    for layer_polylines in polylines.values():
        for pl in layer_polylines:
            for p in pl:
                xs.append(p.x)
                ys.append(p.y)
    if not xs:
        raise RuntimeError("no points in DXF")
    return (min(xs), min(ys)), (max(xs), max(ys))


def _dxf_offset(bounds, mode: str) -> Tuple[float, float]:
    (xmin, ymin), (xmax, ymax) = bounds
    if mode in ("xy-base", "centroid"):
        return (-(xmin + xmax) / 2.0, -(ymin + ymax) / 2.0)
    if mode == "min":
        return (-xmin, -ymin)
    raise ValueError(f"unknown mode: {mode}")


def _translate_polylines(
    polylines: Dict[str, List[List[Point]]], dx: float, dy: float
) -> Dict[str, List[List[Point]]]:
    return {
        layer: [[Point(p.x + dx, p.y + dy) for p in pl] for pl in layer_polylines]
        for layer, layer_polylines in polylines.items()
    }


def center_dxf(
    input_path: Path,
    output_path: Path,
    mode: str,
    smooth: bool,
    angle: float,
    points: int,
) -> None:
    parser = DXFParser(str(input_path))
    lines = parser.parse()
    if not lines:
        raise RuntimeError(f"{input_path}: no LINE entities")

    builder = PolylineBuilder(lines)
    polylines = builder.build_polylines()

    if smooth:
        smoother = CurveSmoother(angle_threshold=angle, points_per_segment=points)
        polylines = {
            layer: [smoother.smooth(pl) for pl in layer_polylines]
            for layer, layer_polylines in polylines.items()
        }

    bounds_before = _dxf_bounds(polylines)
    dx, dy = _dxf_offset(bounds_before, mode)
    centered = _translate_polylines(polylines, dx, dy)
    bounds_after = _dxf_bounds(centered)

    DXFWriter(str(output_path)).write(centered)

    label = "DXF centered + smoothed" if smooth else "DXF centered"
    print(f"{label}:")
    print(f"  in   : {input_path}")
    print(f"  out  : {output_path}")
    print(f"  mode : {mode}")
    print(f"  bbox before: {_fmt_bbox2(bounds_before)}")
    print(f"  bbox after : {_fmt_bbox2(bounds_after)}")
    print(f"  offset     : ({dx:+.3f}, {dy:+.3f})")


def main() -> int:
    arg_parser = argparse.ArgumentParser(
        description=(
            "Center STL/DXF input files for use as design references. "
            "Always writes to a new file; the original is left untouched."
        )
    )
    arg_parser.add_argument("input", help="Input STL or DXF file")
    arg_parser.add_argument(
        "-o",
        "--out",
        help="Output path (default: <stem>_centered<ext> next to input)",
    )
    arg_parser.add_argument(
        "-m",
        "--mode",
        choices=("xy-base", "centroid", "min"),
        default="xy-base",
        help=(
            "Centering mode. "
            "xy-base (default): XY bbox centroid at origin, Z bbox-min at 0. "
            "centroid: full bbox centroid at origin. "
            "min: bbox min corner at origin."
        ),
    )
    arg_parser.add_argument(
        "--smooth",
        action="store_true",
        help="DXF only: apply curve smoothing before centering",
    )
    arg_parser.add_argument(
        "--angle",
        type=float,
        default=15.0,
        help="DXF smoothing angle threshold in degrees (default: 15)",
    )
    arg_parser.add_argument(
        "--points",
        type=int,
        default=8,
        help="DXF smoothing points per segment (default: 8)",
    )
    arg_parser.add_argument(
        "--flip",
        choices=("none", "x", "y", "z"),
        default="none",
        help=(
            "STL only: 180° rotation around the named axis BEFORE centering. "
            "Use --flip y to flip top-to-bottom AND mirror X (e.g. when "
            "connectors face the wrong side). Default: none."
        ),
    )

    args = arg_parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"error: {input_path} does not exist", file=sys.stderr)
        return 2

    output_path = _resolve_output(input_path, args.out)

    if output_path.resolve() == input_path.resolve():
        print(
            f"error: output equals input ({input_path}). "
            "Refusing to overwrite original.",
            file=sys.stderr,
        )
        return 2

    ext = input_path.suffix.lower()
    if ext == ".stl":
        if args.smooth:
            print("warning: --smooth ignored for STL input", file=sys.stderr)
        center_stl(input_path, output_path, args.mode, args.flip)
    elif ext == ".dxf":
        if args.flip != "none":
            print("warning: --flip ignored for DXF input", file=sys.stderr)
        center_dxf(
            input_path,
            output_path,
            args.mode,
            args.smooth,
            args.angle,
            args.points,
        )
    else:
        print(
            f"error: unsupported extension '{ext}' (expected .stl or .dxf)",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
