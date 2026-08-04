"""dimsketch — a TOOLKIT for the LLM to draw a part's PARAMETRIC SKETCH.

NOT a faithful dimensioned drawing of the geometry — that is `slice` (it sections
the real mesh). dimsketch is for a SIMPLE schematic whose job is to make clear to
the USER **which parameters they can tweak and how each affects the part**. The LLM
authors the layout (simple boxes/circles); this toolkit supplies values, provenance
and a consistent style so the sketch doesn't have to be re-coded from scratch each
time. One sketch per plane by default; extra views for complex parts — the LLM
decides, after analysing the part with `slice` + reading the parameter file.

Provenance colour encodes where each number came from, mirroring the wrapper tags:

    MEASURED  (blue)  — verified against the physical part (user measurement).
    ADJUST    (grey)  — estimate / standard, to confirm by test print  [ASSUMED].
    MISSING   (red)   — a dimension the user has NOT supplied yet (draw as "?").

The toolkit, in three layers:
  - `read_params(scad)` — parse `NAME = value; // MEASURED|ADJUST: desc` (follows
    `include`) so the generator never hand-copies constants nor hand-picks colours.
  - `sketch(nviews)` / `finish(fig, path)` — figure scaffold (aspect-equal, axes off,
    legend, save), no boilerplate.
  - `param_h/param_v/param_dia(ax, …, p, grows=…)` + `param_table(…)` — parameter
    cotas labelled `NAME = value` in their provenance colour, with an optional arrow
    glyph for "how it grows", and a side panel of the tweakable knobs.

Usage (one plane):

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools"))
    import dimsketch as ds

    P = ds.read_params(".../components/foo.scad")     # {NAME: Param(value, prov, desc)}
    fig, (ax,) = ds.sketch(1, titles=["planta (XY)"])
    ds.board_outline(ax, P["FOO_W"].value, P["FOO_H"].value, 2)
    ds.param_h(ax, -20.5, 20.5, 24, P["FOO_W"], grows="x")   # cota = "FOO_W = 41" (azul), ↔
    ds.param_table(ax, P, only=["FOO_W", "FOO_H"])
    ds.finish(fig, os.path.join(os.path.dirname(__file__), "foo_dims.png"))
"""
import ast
import operator
import os
import re
from collections import namedtuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.lines as ml
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle

# ---- provenance colour convention (keep in lockstep with MEASURED/ADJUST) ----
MEASURED = "#1f6fd4"   # blue  — user-measured against the real part
MISSING  = "#d62728"   # red   — dimension the user has not given yet
ASSUMED  = "#888888"   # grey  — standard-part estimate / not measured

FILL = "#efe7c8"       # board fill
EDGE = "#4a4a4a"       # outlines


# ---- shapes -----------------------------------------------------------------
def board_outline(ax, w, h, r, fc=FILL, ec=EDGE, lw=1.6):
    """Rounded-rectangle PCB / part outline, centred at the origin."""
    ax.add_patch(FancyBboxPatch((-w/2 + r, -h/2 + r), w - 2*r, h - 2*r,
                 boxstyle=f"round,pad={r},rounding_size={r}",
                 fc=fc, ec=ec, lw=lw))


def rrect(ax, cx, cy, w, h, r, **kw):
    """Rounded rectangle (obround when r == min(w,h)/2), centred at (cx,cy)."""
    r = min(r, w/2, h/2)
    if r <= 0:
        return rect(ax, cx, cy, w, h, **kw)
    ax.add_patch(FancyBboxPatch((cx - w/2 + r, cy - h/2 + r), w - 2*r, h - 2*r,
                 boxstyle=f"round,pad={r},rounding_size={r}", **kw))


def rect(ax, cx, cy, w, h, **kw):
    """Plain rectangle centred at (cx,cy) — for elevation blocks."""
    ax.add_patch(Rectangle((cx - w/2, cy - h/2), w, h, **kw))


def circle(ax, cx, cy, d, **kw):
    """Circle of diameter d centred at (cx,cy) — round features (jack, button)."""
    ax.add_patch(Circle((cx, cy), d/2, **kw))


# ---- dimension (cota) lines -------------------------------------------------
def dim_h(ax, x1, x2, y, text, color, text_off=0.6, tick=1.2, fontsize=9):
    """Horizontal cota between x1 and x2 at height y, labelled above the line."""
    ax.annotate("", (x1, y), (x2, y),
                arrowprops=dict(arrowstyle="<->", color=color, lw=1.3))
    for x in (x1, x2):
        ax.plot([x, x], [y - tick, y + tick], color=color, lw=0.8)
    ax.text((x1 + x2) / 2, y + text_off, text, ha="center", va="bottom",
            color=color, fontsize=fontsize, fontweight="bold")


def dim_v(ax, y1, y2, x, text, color, ha="left", tick=1.2, fontsize=9):
    """Vertical cota between y1 and y2 at abscissa x, labelled beside the line."""
    ax.annotate("", (x, y1), (x, y2),
                arrowprops=dict(arrowstyle="<->", color=color, lw=1.3))
    for y in (y1, y2):
        ax.plot([x - tick, x + tick], [y, y], color=color, lw=0.8)
    dx = 0.8 if ha == "left" else -0.8
    ax.text(x + dx, (y1 + y2) / 2, text, ha=ha, va="center",
            color=color, fontsize=fontsize, fontweight="bold", rotation=90)


def diameter(ax, cx, cy, d, text, color, lead=(12, -18), fontsize=9):
    """Diameter callout with a leader arrow pointing at the circle edge."""
    import math
    ex = cx + (d / 2) * math.cos(math.radians(-45))
    ey = cy + (d / 2) * math.sin(math.radians(-45))
    ax.annotate(text, (ex, ey), (cx + lead[0], cy + lead[1]),
                color=color, fontsize=fontsize, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=color, lw=1.2))


# ---- legend + save ----------------------------------------------------------
def legend(fig, loc="lower center", bbox=(0.5, 0.005)):
    """Standard provenance legend (blue / red / grey)."""
    fig.legend(handles=[
        ml.Line2D([], [], color=MEASURED, lw=2, label="measured (MEASURED)"),
        ml.Line2D([], [], color=MISSING,  lw=2, label="not given yet (MISSING)"),
        ml.Line2D([], [], color=ASSUMED,  lw=2, label="assumed / not measured (ADJUST)"),
    ], loc=loc, ncol=3, fontsize=8, frameon=False, bbox_to_anchor=bbox)


def save(fig, path, dpi=130, pad=0.03):
    """tight_layout + savefig, leaving room for the bottom legend."""
    fig.tight_layout(rect=[0, pad, 1, 1])
    fig.savefig(path, dpi=dpi)
    print(f"wrote {path}")


# ---- parameters: read them (with provenance) straight from the .scad ---------
Param = namedtuple("Param", "name value prov desc")   # value: float|None; prov: a colour const

_PROV = {"MEASURED": MEASURED, "ADJUST": ASSUMED}      # .scad tag -> sketch colour
# tag may carry a parenthetical source qualifier before the colon: `// MEASURED (usuario): ...`
_PARAM_RE = re.compile(
    r'^\s*([A-Za-z_]\w*)\s*=\s*([^;]+?)\s*;\s*//\s*(MEASURED|ADJUST)\s*(?:\([^)]*\))?\s*:\s*(.*)$')
_INCLUDE_RE = re.compile(r'^\s*include\s*<\s*([^>]+)\s*>')


_NUM_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
            ast.USub: operator.neg, ast.UAdd: operator.pos}


_NUM_FNS = {"min": min, "max": max, "abs": abs}   # the ones OpenSCAD shares with Python


def _eval_num(node, scope):
    """Evaluate a constant numeric AST node: literals, refs to already-known params,
    + - * / % ** / unary, and min()/max()/abs() (which is how the stops of a parameter
    cascade are written in .scad). Raises ValueError on anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in scope and scope[node.id] is not None:
            return scope[node.id]
        raise ValueError(node.id)
    if isinstance(node, ast.BinOp) and type(node.op) in _NUM_OPS:
        return _NUM_OPS[type(node.op)](_eval_num(node.left, scope), _eval_num(node.right, scope))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _NUM_OPS:
        return _NUM_OPS[type(node.op)](_eval_num(node.operand, scope))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _NUM_FNS and not node.keywords):
        return _NUM_FNS[node.func.id](*[_eval_num(a, scope) for a in node.args])
    raise ValueError(ast.dump(node))


def _num_value(rhs, scope):
    """Resolve a .scad right-hand side to a float: a plain literal, or simple constant
    arithmetic over numeric literals and earlier params (e.g. `-50.0 + 0.5`, `SPINE_W`).
    Returns None for anything non-numeric (a real geometry expression)."""
    try:
        return float(rhs)
    except ValueError:
        pass
    try:
        return _eval_num(ast.parse(rhs.strip(), mode="eval").body, scope)
    except (ValueError, SyntaxError):
        return None


def read_params(scad_path, _seen=None):
    """Parse `NAME = value; // MEASURED|ADJUST: desc` lines from a .scad and the files
    it `include`s, returning {NAME: Param(value, prov, desc)}. `value` is a float when
    the right-hand side is a plain number OR simple constant arithmetic over earlier params
    (e.g. `-50.0 + 0.5`, `SPINE_W`); else None (a real geometry expression). Provenance maps
    MEASURED->blue, ADJUST->grey. So a generator never hand-copies constants nor
    hand-assigns colours — both come from the wrapper, the single source of truth."""
    scad_path = os.path.abspath(scad_path)
    _seen = _seen if _seen is not None else set()
    out = {}
    if scad_path in _seen or not os.path.exists(scad_path):
        return out
    _seen.add(scad_path)
    base = os.path.dirname(scad_path)
    for line in open(scad_path, encoding="utf-8"):
        inc = _INCLUDE_RE.match(line)
        if inc:                                        # pull params from included files too
            for k, v in read_params(os.path.join(base, inc.group(1)), _seen).items():
                out.setdefault(k, v)
            continue
        m = _PARAM_RE.match(line)
        if m:
            name, rhs, tag, desc = m.groups()
            scope = {k: p.value for k, p in out.items() if p.value is not None}
            val = _num_value(rhs, scope)               # literal, or constant arithmetic over earlier params
            out[name] = Param(name, val, _PROV[tag], desc.strip())
    return out


# ---- figure scaffold (no per-generator boilerplate) -------------------------
def sketch(nviews=1, size=None, titles=None, height_ratios=None):
    """Build a figure of `nviews` stacked views, each aspect-equal with axes hidden.
    Returns (fig, axes-as-list). Pair with finish(). Replaces the repeated
    plt.subplots + 'for a: set_aspect/axis off' boilerplate."""
    if size is None:
        size = (8, 8) if nviews == 1 else (8.2, 3.0 + 3.2 * nviews)
    gs = {"height_ratios": height_ratios} if height_ratios else None
    fig, axs = plt.subplots(nviews, 1, figsize=size, gridspec_kw=gs)
    axs = [axs] if nviews == 1 else list(axs)
    for i, a in enumerate(axs):
        a.set_aspect("equal")
        a.axis("off")
        if titles and i < len(titles) and titles[i]:
            a.set_title(titles[i], fontsize=8, color=EDGE)
    return fig, axs


def finish(fig, path, dpi=130):
    """Standard provenance legend + save. One call to close a sketch."""
    legend(fig)
    save(fig, path, dpi=dpi)


# ---- parameter cotas: cota labelled with the PARAM NAME + value + provenance --
_GROW = {"x": " ↔", "y": " ↕", "z": " ↕", "r": " ⌀", None: ""}   # "how it grows" glyph


def _short(name, prefix=""):
    return name[len(prefix):] if prefix and name.startswith(prefix) else name


def _ptext(p, grows=None, prefix=""):
    v = f"{p.value:g}" if isinstance(p.value, (int, float)) else "?"
    return f"{_short(p.name, prefix)} = {v}{_GROW.get(grows, '')}"


def param_h(ax, x1, x2, y, p, grows="x", prefix="", **kw):
    """Horizontal cota for a PARAMETER: labelled `NAME = value` in its provenance
    colour. `grows` adds a direction glyph (x=↔, y=↕, r=⌀) hinting how it affects the
    part; `prefix` drops a redundant name prefix (e.g. "PCBH_") on the label so it
    fits in tight spots. `p` is a Param (from read_params)."""
    dim_h(ax, x1, x2, y, _ptext(p, grows, prefix), p.prov, **kw)


def param_v(ax, y1, y2, x, p, grows="y", prefix="", **kw):
    """Vertical cota for a PARAMETER (see param_h)."""
    dim_v(ax, y1, y2, x, _ptext(p, grows, prefix), p.prov, **kw)


def param_dia(ax, cx, cy, d, p, grows="r", prefix="", **kw):
    """Diameter callout for a PARAMETER: `NAME = value` + leader, in its colour."""
    diameter(ax, cx, cy, d, _ptext(p, grows, prefix), p.prov, **kw)


def param_table(ax, params, only=None, prefix="", title="tweakable parameters",
                x=0.0, y0=1.0, dy=0.11, fontsize=8):
    """Knobs panel in `ax`: one line per tweakable parameter — `NAME = value` in its
    provenance colour + its description in grey. `only` picks/orders names; `prefix`
    is dropped from the shown names. Give it its OWN blank axes (e.g. the last view of
    sketch(nviews=3,...)); it switches the axes to free aspect and full [0,1] coords."""
    ax.set_aspect("auto"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    names = only if only is not None else list(params)
    ax.text(x, y0, title, transform=ax.transAxes, fontsize=fontsize + 1,
            fontweight="bold", color=EDGE, va="top")
    for i, name in enumerate(names):
        p = params.get(name)
        if p is None:
            continue
        y = y0 - dy * (i + 1.2)
        v = f"{p.value:g}" if isinstance(p.value, (int, float)) else "?"
        ax.text(x, y, f"{_short(name, prefix)} = {v}", transform=ax.transAxes,
                fontsize=fontsize, fontweight="bold", color=p.prov, va="top", family="monospace")
        ax.text(x + 0.26, y, p.desc, transform=ax.transAxes, fontsize=fontsize - 1,
                color=ASSUMED, va="top")
