#!/usr/bin/env python3
"""
DXF Curve Smoother - Vanilla Python Module

Smooths polygon curves in DXF files by adding interpolated points 
only on continuous curves (small direction changes). Sharp corners 
are preserved.

Usage:
    uv run tools/dxf_smoother.py input.dxf [output.dxf] [--angle DEGREES] [--points N]
"""

import re
import math
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Point:
    x: float
    y: float
    
    def distance_to(self, other: 'Point') -> float:
        return math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)
    
    def __eq__(self, other):
        if not isinstance(other, Point):
            return False
        return abs(self.x - other.x) < 1e-6 and abs(self.y - other.y) < 1e-6
    
    def __hash__(self):
        return hash((round(self.x, 6), round(self.y, 6)))


@dataclass
class Line:
    start: Point
    end: Point
    layer: str


class DXFParser:
    """Parses DXF files and extracts geometry as LINE segments. Handles LINE, old-style
    POLYLINE/VERTEX and LWPOLYLINE entities — so DXFs saved by CAD editors (which often emit
    POLYLINE, unreadable by OpenSCAD) round-trip through here into OpenSCAD-readable LINEs."""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.lines: List[Line] = []
        self.header_content: str = ""
        
    def parse(self) -> List[Line]:
        """Parse the DXF file and return list of Line objects."""
        with open(self.filepath, 'r') as f:
            content = f.read()
        
        # Store header section for later
        header_match = re.search(r'(.*?ENTITIES)', content, re.DOTALL)
        if header_match:
            self.header_content = header_match.group(1)
        
        # Parse LINE entities
        self.lines = []
        
        # Split content into tokens (group code + value pairs)
        lines_text = content.split('\n')
        tokens = []
        i = 0
        while i < len(lines_text) - 1:
            code = lines_text[i].strip()
            value = lines_text[i + 1].strip() if i + 1 < len(lines_text) else ""
            tokens.append((code, value))
            i += 2
        
        # Find LINE / POLYLINE / LWPOLYLINE entities (VERTEX/SEQEND tokens left over from a
        # POLYLINE are simply ignored by the next iterations — they match no entity branch).
        i = 0
        while i < len(tokens):
            code, value = tokens[i]
            if code == '0' and value == 'LINE':
                line = self._parse_line_entity(tokens, i)
                if line:
                    self.lines.append(line)
            elif code == '0' and value == 'POLYLINE':
                self.lines.extend(self._parse_polyline_entity(tokens, i))
            elif code == '0' and value == 'LWPOLYLINE':
                self.lines.extend(self._parse_lwpolyline_entity(tokens, i))
            i += 1

        return self.lines

    @staticmethod
    def _verts_to_lines(verts: List["Point"], layer: str, closed: bool) -> List["Line"]:
        """Chain a vertex list into LINE segments; close the loop if `closed`."""
        segs = [Line(verts[k], verts[k + 1], layer) for k in range(len(verts) - 1)]
        if closed and len(verts) >= 2:
            segs.append(Line(verts[-1], verts[0], layer))
        return segs

    def _parse_polyline_entity(self, tokens, start_idx: int) -> List["Line"]:
        """Old-style POLYLINE: a header (8=layer, 70=flags) then VERTEX entities until SEQEND."""
        layer, closed = "0", False
        i = start_idx + 1
        while i < len(tokens) and tokens[i][0] != '0':       # POLYLINE header
            code, value = tokens[i]
            if code == '8':
                layer = value
            elif code == '70':
                closed = bool(int(float(value)) & 1)
            i += 1
        verts: List[Point] = []
        while i < len(tokens):
            code, value = tokens[i]
            if code == '0' and value == 'VERTEX':
                x = y = 0.0
                j = i + 1
                while j < len(tokens) and tokens[j][0] != '0':
                    c2, v2 = tokens[j]
                    if c2 == '10':
                        x = float(v2)
                    elif c2 == '20':
                        y = float(v2)
                    j += 1
                verts.append(Point(x, y))
                i = j
            else:                                            # SEQEND (or anything else) ends it
                break
        return self._verts_to_lines(verts, layer, closed)

    def _parse_lwpolyline_entity(self, tokens, start_idx: int) -> List["Line"]:
        """LWPOLYLINE: 8=layer, 70=flags, then repeated 10/20 vertex coordinate pairs."""
        layer, closed, verts, cur_x = "0", False, [], None
        i = start_idx + 1
        while i < len(tokens) and tokens[i][0] != '0':
            code, value = tokens[i]
            if code == '8':
                layer = value
            elif code == '70':
                closed = bool(int(float(value)) & 1)
            elif code == '10':
                cur_x = float(value)
            elif code == '20' and cur_x is not None:
                verts.append(Point(cur_x, float(value)))
                cur_x = None
            i += 1
        return self._verts_to_lines(verts, layer, closed)
    
    def _parse_line_entity(self, tokens: List[Tuple[str, str]], start_idx: int) -> Optional[Line]:
        """Parse a single LINE entity starting at the given index."""
        layer = "0"
        x1 = y1 = x2 = y2 = 0.0
        
        i = start_idx + 1
        while i < len(tokens):
            code, value = tokens[i]
            
            # Stop at next entity
            if code == '0':
                break
            
            if code == '8':
                layer = value
            elif code == '10':
                x1 = float(value)
            elif code == '20':
                y1 = float(value)
            elif code == '11':
                x2 = float(value)
            elif code == '21':
                y2 = float(value)
            
            i += 1
        
        return Line(Point(x1, y1), Point(x2, y2), layer)


class PolylineBuilder:
    """Builds connected polylines from individual line segments."""
    
    def __init__(self, lines: List[Line], tolerance: float = 1e-4):
        self.lines = lines
        self.tolerance = tolerance
    
    def build_polylines(self) -> Dict[str, List[List[Point]]]:
        """Group lines by layer and build connected polylines."""
        # Group lines by layer
        layers: Dict[str, List[Line]] = {}
        for line in self.lines:
            if line.layer not in layers:
                layers[line.layer] = []
            layers[line.layer].append(line)
        
        # Build polylines for each layer
        result: Dict[str, List[List[Point]]] = {}
        for layer, layer_lines in layers.items():
            result[layer] = self._build_layer_polylines(layer_lines)
        
        return result
    
    def _build_layer_polylines(self, lines: List[Line]) -> List[List[Point]]:
        """Build connected polylines from a list of lines."""
        if not lines:
            return []
        
        polylines = []
        remaining = list(lines)
        
        while remaining:
            # Start a new polyline
            current_line = remaining.pop(0)
            polyline = [current_line.start, current_line.end]
            
            # Try to extend the polyline
            changed = True
            while changed and remaining:
                changed = False
                for i, line in enumerate(remaining):
                    # Check if line connects to end of polyline
                    if self._points_close(line.start, polyline[-1]):
                        polyline.append(line.end)
                        remaining.pop(i)
                        changed = True
                        break
                    elif self._points_close(line.end, polyline[-1]):
                        polyline.append(line.start)
                        remaining.pop(i)
                        changed = True
                        break
                    # Check if line connects to start of polyline
                    elif self._points_close(line.end, polyline[0]):
                        polyline.insert(0, line.start)
                        remaining.pop(i)
                        changed = True
                        break
                    elif self._points_close(line.start, polyline[0]):
                        polyline.insert(0, line.end)
                        remaining.pop(i)
                        changed = True
                        break
            
            polylines.append(polyline)
        
        return polylines
    
    def _points_close(self, p1: Point, p2: Point) -> bool:
        """Check if two points are within tolerance."""
        return p1.distance_to(p2) < self.tolerance


class CurveSmoother:
    """Smooths polylines by adding interpolated points only on continuous curves."""
    
    def __init__(self, angle_threshold: float = 15.0, points_per_segment: int = 8):
        """
        Initialize the smoother.
        
        Args:
            angle_threshold: Maximum angle change (degrees) to consider as continuous curve.
                            Corners with larger angle changes are preserved as-is.
            points_per_segment: Number of interpolated points to add per smoothable segment.
        """
        self.angle_threshold = angle_threshold
        self.points_per_segment = points_per_segment
    
    def smooth(self, points: List[Point]) -> List[Point]:
        """
        Smooth the polyline by adding interpolated points only where 
        the direction change is small (continuous curve).
        """
        if len(points) < 3:
            return points
        
        result = [points[0]]
        
        for i in range(1, len(points) - 1):
            p_prev = points[i - 1]
            p_curr = points[i]
            p_next = points[i + 1]
            
            angle_change = self._calculate_angle_change(p_prev, p_curr, p_next)
            
            if angle_change <= self.angle_threshold:
                # Continuous curve - add interpolated points
                interpolated = self._interpolate_curve(p_prev, p_curr, p_next)
                result.extend(interpolated)
            else:
                # Sharp corner - keep the point as-is
                result.append(p_curr)
        
        result.append(points[-1])
        return result
    
    def _calculate_angle_change(self, p1: Point, p2: Point, p3: Point) -> float:
        """
        Calculate the angle change at p2 between segments p1->p2 and p2->p3.
        Returns angle in degrees (0 = straight line, 180 = complete reversal).
        """
        # Vector from p1 to p2
        v1x = p2.x - p1.x
        v1y = p2.y - p1.y
        
        # Vector from p2 to p3
        v2x = p3.x - p2.x
        v2y = p3.y - p2.y
        
        # Calculate magnitudes
        mag1 = math.sqrt(v1x * v1x + v1y * v1y)
        mag2 = math.sqrt(v2x * v2x + v2y * v2y)
        
        if mag1 < 1e-10 or mag2 < 1e-10:
            return 0.0  # Degenerate case
        
        # Normalize vectors
        v1x /= mag1
        v1y /= mag1
        v2x /= mag2
        v2y /= mag2
        
        # Dot product gives cos(angle)
        dot = v1x * v2x + v1y * v2y
        
        # Clamp to avoid numerical issues with acos
        dot = max(-1.0, min(1.0, dot))
        
        # Angle between vectors (0 = same direction, 180 = opposite)
        angle_rad = math.acos(dot)
        angle_deg = math.degrees(angle_rad)
        
        # We want angle change from straight line
        # If vectors point same direction, angle is 0, change is 0
        # If vectors are perpendicular, angle is 90, change is 90
        return angle_deg
    
    def _interpolate_curve(self, p1: Point, p2: Point, p3: Point) -> List[Point]:
        """
        Add interpolated points around p2 using quadratic Bezier interpolation.
        Returns list of points (not including p1, includes interpolated points around p2).
        """
        result = []
        
        # Use quadratic Bezier with p2 as control point
        # B(t) = (1-t)^2 * P0 + 2*(1-t)*t * P1 + t^2 * P2
        
        # Midpoint between p1 and p2
        mid1 = Point((p1.x + p2.x) / 2, (p1.y + p2.y) / 2)
        # Midpoint between p2 and p3  
        mid2 = Point((p2.x + p3.x) / 2, (p2.y + p3.y) / 2)
        
        # Generate points along quadratic Bezier from mid1 to mid2 with p2 as control
        for i in range(self.points_per_segment + 1):
            t = i / self.points_per_segment
            
            # Quadratic Bezier formula
            mt = 1 - t
            x = mt * mt * mid1.x + 2 * mt * t * p2.x + t * t * mid2.x
            y = mt * mt * mid1.y + 2 * mt * t * p2.y + t * t * mid2.y
            
            result.append(Point(x, y))
        
        return result


class DXFWriter:
    """Writes smoothed polylines back to DXF format."""
    
    def __init__(self, output_path: str):
        self.output_path = output_path
    
    def write(self, polylines: Dict[str, List[List[Point]]]):
        """Write polylines to a DXF file."""
        with open(self.output_path, 'w') as f:
            # Write header
            f.write('999\n')
            f.write('"DXF R12 Output - Smoothed" (www.mydxf.blogspot.com)\n')
            f.write(' 0 \n')
            f.write('SECTION\n')
            f.write(' 2 \n')
            f.write('HEADER\n')
            f.write(' 9 \n')
            f.write('$ACADVER\n')
            f.write(' 1 \n')
            f.write('AC1009\n')
            f.write(' 9 \n')
            f.write('$EXTMIN\n')
            f.write(' 10 \n')
            f.write(' 0 \n')
            f.write(' 20 \n')
            f.write(' 0 \n')
            f.write(' 9 \n')
            f.write('$EXTMAX\n')
            f.write(' 10 \n')
            f.write(' 8.5 \n')
            f.write(' 20 \n')
            f.write(' 11 \n')
            f.write(' 0 \n')
            f.write('ENDSEC\n')
            f.write(' 0 \n')
            f.write('SECTION\n')
            f.write(' 2 \n')
            f.write('ENTITIES\n')
            
            # Write lines for each layer
            for layer, layer_polylines in polylines.items():
                for polyline in layer_polylines:
                    self._write_polyline_as_lines(f, polyline, layer)
            
            # Write footer
            f.write(' 0 \n')
            f.write('ENDSEC\n')
            f.write(' 0 \n')
            f.write('EOF\n')
    
    def _write_polyline_as_lines(self, f, points: List[Point], layer: str):
        """Write a polyline as individual LINE entities."""
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            
            f.write('0\n')
            f.write('LINE\n')
            f.write('8\n')
            f.write(f'{layer}\n')
            f.write('10\n')
            f.write(f'{p1.x:.6f}\n')
            f.write('20\n')
            f.write(f'{p1.y:.6f}\n')
            f.write('11\n')
            f.write(f'{p2.x:.6f}\n')
            f.write('21\n')
            f.write(f'{p2.y:.6f}\n')


def smooth_dxf(
    input_path: str,
    output_path: Optional[str] = None,
    angle_threshold: float = 15.0,
    points_per_segment: int = 8,
    no_smooth: bool = False
) -> str:
    """
    Smooth curves in a DXF file.
    
    Args:
        input_path: Path to the input DXF file
        output_path: Path to the output DXF file (default: input_smoothed.dxf)
        angle_threshold: Maximum angle change (degrees) to smooth. 
                        Corners with larger changes are preserved. (default: 15)
        points_per_segment: Number of interpolated points per smoothed segment (default: 8)
    
    Returns:
        Path to the output file
    """
    input_path = Path(input_path)
    
    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}_smoothed{input_path.suffix}"
    else:
        output_path = Path(output_path)
    
    # Parse input
    print(f"Parsing {input_path}...")
    parser = DXFParser(str(input_path))
    lines = parser.parse()
    print(f"Found {len(lines)} line segments")
    
    # Build polylines
    print("Building polylines...")
    builder = PolylineBuilder(lines)
    polylines = builder.build_polylines()
    
    for layer, layer_polylines in polylines.items():
        total_points = sum(len(p) for p in layer_polylines)
        print(f"  Layer '{layer}': {len(layer_polylines)} polyline(s), {total_points} points")
    
    # Smooth polylines — or, in convert-only mode, pass them straight through (just a format
    # normalize: any DXF entity -> OpenSCAD-readable LINEs, geometry untouched).
    if no_smooth:
        print("Convert-only (no smoothing): geometry left as-is, re-emitted as LINE entities.")
        smoothed_polylines: Dict[str, List[List[Point]]] = polylines
    else:
        print(f"Smoothing curves (angle threshold: {angle_threshold}°, points per segment: {points_per_segment})...")
        smoother = CurveSmoother(angle_threshold=angle_threshold, points_per_segment=points_per_segment)
        smoothed_polylines = {}
        for layer, layer_polylines in polylines.items():
            smoothed_polylines[layer] = [
                smoother.smooth(polyline) for polyline in layer_polylines
            ]
        for layer, layer_polylines in smoothed_polylines.items():
            total_points = sum(len(p) for p in layer_polylines)
            print(f"  Layer '{layer}': {total_points} points after smoothing")
    
    # Write output
    print(f"Writing {output_path}...")
    writer = DXFWriter(str(output_path))
    writer.write(smoothed_polylines)
    
    print("Done!")
    return str(output_path)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Smooth polygon curves in DXF files by adding interpolated points on continuous curves"
    )
    parser.add_argument("input", help="Input DXF file")
    parser.add_argument("output", nargs="?", help="Output DXF file (default: input_smoothed.dxf)")
    parser.add_argument(
        "-a", "--angle",
        type=float,
        default=15.0,
        help="Angle threshold in degrees. Corners with larger angle changes are preserved (default: 15)"
    )
    parser.add_argument(
        "-p", "--points",
        type=int,
        default=8,
        help="Number of interpolated points per smoothed segment (default: 8)"
    )
    parser.add_argument(
        "--no-smooth",
        action="store_true",
        help="convert only: normalize any DXF (POLYLINE/LWPOLYLINE) to OpenSCAD-readable LINEs "
             "without smoothing (geometry untouched). Use to make an editor's DXF importable."
    )

    args = parser.parse_args()

    smooth_dxf(
        input_path=args.input,
        output_path=args.output,
        angle_threshold=args.angle,
        points_per_segment=args.points,
        no_smooth=args.no_smooth
    )


if __name__ == "__main__":
    main()

