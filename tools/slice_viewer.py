#!/usr/bin/env python3
"""
slice_viewer — a slice browser for a part: precompute every slice along
all three axes (preview + plot), then step through them in a tiny GUI (axis radio +
position slider). A visual-inspection tool for the user, not a headless reader.

Two phases in one command:
  1. PREPROCESS — load the mesh once and section it every --step mm along x, y
     and z, writing each level's DUO (`<axis>_<idx>_preview.png` + `_plot.png`)
     plus a `slices.json` manifest to build/<stem>_slices/. Reuses slice.py
     wholesale (resolve_pieces / section_loaded / collect_features / emit_plot / emit_preview).
  2. GUI — a matplotlib window: pick the axis (x/y/z radio), drag the position
     slider; the matching preview (WHERE it cuts) and plot (the dimensioned
     section) load side by side. A CAPTURE panel turns the browser into a way
     to CURATE the inspection set: when a section is worth keeping, name it and
     Save — it writes a `<name> <axis>=<pos> [parts=…]` line into the sibling
     `<stem>.batch` (stl_assembly.scad→stl_assembly.batch; what run_batch reads).
     Click an existing entry to jump to it; Delete removes it. So the human
     explores and decides which sections matter; the tool records them
     consistently (the .batch panel needs a .scad front door, not an .stl).

The preprocess runs in a SUBPROCESS: emit_plot renders headless (Agg), which would
otherwise lock matplotlib's backend and stop the GUI window from opening. The parent
stays backend-clean and shows an interactive window.

Preprocess cost scales with 1/step (one OpenSCAD preview render per level, ×3 axes),
so a coarse --step is fast to scan, a fine one is thorough. The per-level renders run
across a process pool (--jobs, default = all cores), each worker loading the baked
STL once — roughly an N-core speedup over a serial sweep. --reuse skips the build and
opens the GUI on the existing sections dir.

With --vs <ref.scad|ref.stl> (like render3d's --vs), each level's PLOT slot becomes
compare.py's section overlay against that reference — model in blue over the reference
in grey, with red/orange marking where the outline/holes deviate beyond tolerance —
instead of the dimensioned section. The preview ("where it cuts") is unchanged, the
sweep/GUI/capture work exactly as before, and the two designs must already sit in the
SAME world frame (no alignment, same rule as compare.py). Where the reference doesn't
cross a plane the level falls back to the plain dimensioned section.

Usage:
    uv run tools/slice_viewer.py main.scad                 # all *_solid, step 2 mm
    uv run tools/slice_viewer.py main.scad --parts lid_solid --step 1
    uv run tools/slice_viewer.py part.stl --step 3
    uv run tools/slice_viewer.py main.scad --vs ref.stl    # each slice = compare overlay vs ref
    uv run tools/slice_viewer.py main.scad --vs other.scad --vs-parts lid_solid --tol 0.3
    uv run tools/slice_viewer.py main.scad --reuse         # just open the GUI again
    uv run tools/slice_viewer.py main.scad --build-only    # precompute, no window

The captured parts= mirror how the viewer was launched: --parts lid_solid → the
saved line carries parts=lid_solid; the default (all *_solid) is left off the line.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from _common import build_dir, locate_openscad, repo_root
from _geom import AXES
from compare import compare_plane, load_tolerances   # reuse compare's overlay + per-detector tols for --vs
from run_batch import parse_line          # reuse the .batch line grammar for the capture panel
from slice import (collect_features, emit_plot, emit_preview, face_gaps,
                   load_meshes, resolve_pieces, section_loaded)

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PREVIEW_FN = 16     # the preview only adds a flat cut-plane cube to a baked STL — $fn is irrelevant
DEFAULT_JOBS = os.cpu_count() or 4     # the sweep is embarrassingly parallel — use every core


# ----------------------------------------------------------------------------- preprocess

def _render_one(meshes, pieces, input_name, ai, pos, base, openscad, size, frame, vs=None):
    """Section at axis ai = pos and write the level's DUO. `frame` is the FIXED
    plot extent for this axis (so every level shares a pixel grid). Returns the two
    PNG names (or None, None if the plane misses the part). The unit of parallel work.

    With `vs` (a context dict from a --vs run: model_fused / ref_fused meshes, tol,
    tags, roles), the PLOT slot becomes compare.py's overlay for this plane (model in
    blue over the reference in grey, red/orange = deviation) instead of the dimensioned
    section — the preview ("where it cuts") is unchanged. Falls back to the dimensioned
    plot when the reference doesn't cross this plane, so a model-bearing level always
    shows something."""
    res = section_loaded(meshes, ai, pos, quiet=True)
    base = Path(base)
    if res is None:
        return None, None
    secs, ua, va, fp, diag = res
    plot_png = Path(f"{base}_plot.png")
    emit_preview(Path(f"{base}_preview.png"), pieces, ai, pos, openscad, PREVIEW_FN, size)
    if vs is not None:
        rec = compare_plane(f"{AXES[ai]}={pos:.1f}", vs["model_fused"], vs["ref_fused"],
                            ai, pos, vs["tol"], base.parent, vs["tag_a"], vs["tag_b"],
                            vs["role_a"], vs["role_b"], out_png=plot_png, frame=frame)
        if rec is not None:
            return f"{base.name}_plot.png", f"{base.name}_preview.png"
        # reference misses this plane -> fall through to the plain dimensioned section
    feats = collect_features(secs, diag)
    gaps = face_gaps(secs, ua, va, diag) if len(secs) > 1 else []
    emit_plot(plot_png, input_name, ai, pos, secs, feats, gaps, fp, ua, va, diag, frame=frame)
    return f"{base.name}_plot.png", f"{base.name}_preview.png"


_W = {}     # per-worker state: the meshes are loaded ONCE per process, not per level


def _init_worker(piece_paths, input_name, openscad, size, vs=None):
    _W.update(pieces=[(n, Path(p)) for n, p in piece_paths],
              input=input_name, openscad=openscad, size=size, vs=vs)
    _W["meshes"] = load_meshes(_W["pieces"])


def _render_level(task):
    ai, k, pos, base, frame = task
    plot, preview = _render_one(_W["meshes"], _W["pieces"], _W["input"],
                                ai, pos, base, _W["openscad"], _W["size"], frame,
                                vs=_W.get("vs"))
    return ai, k, plot, preview


def _signature(pieces, parts, step, size, vs_sig=None):
    """A hash of what determines the output: the baked STL bytes (geometry — `fn`
    and `parts` are already baked in) plus the params that shape the images. A rerun
    with the same signature can reuse the existing sections instead of redoing it.
    `vs_sig` folds in the --vs comparison identity (reference bytes + parts + tol) so a
    plain build and a compare build never share a cache."""
    h = hashlib.sha1()
    for name, stl in sorted(pieces):
        h.update(name.encode())
        h.update(Path(stl).read_bytes())
    h.update(repr((sorted(parts) if parts else None, round(step, 6), size, vs_sig)).encode())
    return h.hexdigest()


def _fuse(meshes):
    """Fuse [(name, mesh)] into ONE trimesh mesh (a design = one section per plane)."""
    import trimesh
    ms = [m for _n, m in meshes]
    return ms[0] if len(ms) == 1 else trimesh.util.concatenate(ms)


def _build_vs_context(inputs, model_meshes, vs_input, vs_parts, tol, fn, openscad, outdir):
    """Assemble the --vs comparison context: fuse the model and resolve+fuse the
    reference (.scad/.stl) into single meshes, pick the grey/blue roles by extension
    (.stl=REFERENCE, .scad=MODEL — same convention as compare.py), and hash the
    fused reference for the cache signature. Returns (ctx, vs_sig, ref_lo3, ref_hi3)."""
    ref_pieces = resolve_pieces([vs_input], vs_parts, fn, openscad, outdir)
    ref_meshes = load_meshes(ref_pieces)
    ref_fused = _fuse(ref_meshes)
    model_fused = _fuse(model_meshes)

    def _role(p):
        e = Path(p).suffix.lower()
        return "REFERENCE" if e == ".stl" else "MODEL" if e == ".scad" else None
    role_a, role_b = _role(inputs[0]), _role(vs_input)
    if not (role_a and role_b and role_a != role_b):
        role_a = role_b = None
    tag_a, tag_b = Path(inputs[0]).stem, Path(vs_input).stem
    if tag_a == tag_b:
        tag_a, tag_b = tag_a + "_a", tag_b + "_b"

    vs_sig = hashlib.sha1(ref_fused.export(file_type="stl")).hexdigest()
    vs_sig = hashlib.sha1((vs_sig + repr((sorted(vs_parts) if vs_parts else None,
                                          sorted(tol.items())))).encode()).hexdigest()
    ctx = dict(model_fused=model_fused, ref_fused=ref_fused, tol=tol,
               tag_a=tag_a, tag_b=tag_b, role_a=role_a, role_b=role_b)
    return ctx, vs_sig, ref_fused.bounds[0], ref_fused.bounds[1]


def build_slices(inputs, parts, step, fn, size, openscad, outdir, jobs, force=False,
                 vs_input=None, vs_parts=None, tol=None):
    """Sweep x/y/z every `step` mm, writing each level's preview+plot and a
    `slices.json` manifest to `outdir`. The per-level renders run across a process
    pool (each worker loads the baked STL once); jobs<=1 stays in-process. Headless
    (Agg, via slice.emit_plot). Skips the (expensive) render when the inputs hash to
    the same signature already on disk — unless `force`.

    With `vs_input` (a reference .scad/.stl), each level's PLOT becomes compare.py's
    overlay vs that reference instead of the dimensioned section (preview unchanged)."""
    outdir.mkdir(parents=True, exist_ok=True)
    pieces = resolve_pieces(inputs, parts, fn, openscad, outdir)     # bake the STL(s) once
    meshes = load_meshes(pieces)

    vs, vs_sig, ref_lo3, ref_hi3 = None, None, None, None
    if vs_input is not None:
        vs, vs_sig, ref_lo3, ref_hi3 = _build_vs_context(
            inputs, meshes, vs_input, vs_parts, tol, fn, openscad, outdir)
    sig = _signature(pieces, parts, step, size, vs_sig)

    mpath = outdir / "slices.json"
    if not force and mpath.exists():
        try:
            old = json.loads(mpath.read_text())
        except Exception:
            old = {}
        imgs = [outdir / L[k] for a in old.get("axes", {}).values()
                for L in a["levels"] for k in ("plot", "preview") if L[k]]
        if old.get("sig") == sig and imgs and all(p.exists() for p in imgs):
            for stl in outdir.glob("*__slice_*.stl"):
                stl.unlink()
            print(f"no changes (hash {sig[:8]}…): reusing {len(imgs) // 2} already-processed "
                  f"levels (--force to redo)")
            return

    for f in outdir.glob("*.png"):       # geometry/params changed → regenerate from scratch
        f.unlink()
    mpath.unlink(missing_ok=True)

    lo3 = np.min([m.bounds[0] for _, m in meshes], axis=0)     # model extent: drives the sweep
    hi3 = np.max([m.bounds[1] for _, m in meshes], axis=0)
    # The plot WINDOW spans model+reference when comparing, so the reference never gets
    # clipped at the frame edge even where it overhangs the model.
    flo3 = np.minimum(lo3, ref_lo3) if vs else lo3
    fhi3 = np.maximum(hi3, ref_hi3) if vs else hi3

    # FIXED plot frame per axis: the part's full extent in that plane's two axes, so
    # every level of the axis renders on the same pixel grid (a feature stays put as
    # you scrub). A midpoint section tells us which two axes (ua,va) the plane uses.
    def axis_frame(ai):
        res = section_loaded(meshes, ai, float((lo3[ai] + hi3[ai]) / 2), quiet=True)
        if res is None:
            return None
        _s, ua, va, _fp, _d = res
        return (float(flo3[ua]), float(fhi3[ua]), float(flo3[va]), float(fhi3[va]))

    tasks, manifest = [], {"input": inputs[0].name, "step": step, "sig": sig,
                           "vs": Path(vs_input).name if vs_input is not None else None, "axes": {}}
    for ai in (0, 1, 2):
        axis = AXES[ai]
        lo, hi = float(lo3[ai]), float(hi3[ai])
        frame = axis_frame(ai)
        n = max(1, int(math.floor((hi - lo) / step)))
        levels = []
        for k in range(n + 1):
            pos = lo + k * step
            tasks.append((ai, k, float(pos), str(outdir / f"{axis}_{k:03d}"), frame))
            levels.append({"pos": round(pos, 3), "plot": None, "preview": None})
        manifest["axes"][axis] = {"extent": [round(lo, 3), round(hi, 3)], "levels": levels}

    def apply(ai, k, plot, preview):
        lv = manifest["axes"][AXES[ai]]["levels"][k]
        lv["plot"], lv["preview"] = plot, preview

    n_tasks = len(tasks)
    print(f"  {n_tasks} levels across 3 axes · {jobs} process(es)", flush=True)
    done = 0
    if jobs <= 1:
        for ai, k, pos, base, frame in tasks:
            apply(ai, k, *_render_one(meshes, pieces, inputs[0].name, ai, pos, base,
                                      openscad, size, frame, vs=vs))
            done += 1
    else:
        piece_paths = [(n, str(p)) for n, p in pieces]
        with Pool(jobs, initializer=_init_worker,
                  initargs=(piece_paths, inputs[0].name, openscad, size, vs)) as pool:
            for ai, k, plot, preview in pool.imap_unordered(_render_level, tasks):
                apply(ai, k, plot, preview)
                done += 1
                if done % 10 == 0 or done == n_tasks:
                    print(f"    {done}/{n_tasks}", flush=True)

    for stl in outdir.glob("*__slice_*.stl"):        # drop the intermediate bakes
        stl.unlink()
    (outdir / "slices.json").write_text(json.dumps(manifest))
    filled = sum(1 for a in manifest["axes"].values() for lv in a["levels"] if lv["plot"])
    print(f"sections: {filled}/{n_tasks} levels with a section → {outdir}")


# ----------------------------------------------------------------------------- main.batch I/O

_CENTRAL_AXIS = {"top": "z", "front": "y", "side": "x"}   # named central section -> cut axis


def read_entries(batch_path):
    """[(name, spec, parts)] from a main.batch (blanks/comments dropped), via the same
    grammar run_batch uses — so the panel lists exactly what the batch will regenerate."""
    if not batch_path or not Path(batch_path).exists():
        return []
    return [e for e in (parse_line(L) for L in Path(batch_path).read_text().splitlines()) if e]


def _name_of(line):
    code = line.split("#", 1)[0].strip()
    return code.split()[0] if code else None


def upsert_entry(batch_path, name, line):
    """Replace the line whose first token is `name`, else append it. Comments and order
    are preserved; a header is written if the file is new."""
    p = Path(batch_path)
    lines = p.read_text().splitlines() if p.exists() else []
    if not any(_name_of(L) for L in lines):              # new/empty file → seed a header
        scad = p.with_name(p.stem + ".scad")             # the .scad this batch regenerates
        try:
            ref = scad.resolve().relative_to(repo_root())
        except Exception:
            ref = scad.name
        lines = lines or [f"# {p.stem} sections — regenerate: uv run tools/run_batch.py {ref}"]
    for i, L in enumerate(lines):
        if _name_of(L) == name:
            lines[i] = line
            break
    else:
        lines.append(line)
    p.write_text("\n".join(lines) + "\n")


def delete_entry(batch_path, name):
    p = Path(batch_path)
    if not p.exists():
        return
    p.write_text("\n".join(L for L in p.read_text().splitlines() if _name_of(L) != name) + "\n")


def spec_axis_pos(spec, axes):
    """Resolve a .batch spec to (axis_letter, pos): a central name (top/front/side) maps
    to the bbox midpoint of its axis, `z=2.0` parses directly. None if unmappable."""
    if spec in _CENTRAL_AXIS:
        ax = _CENTRAL_AXIS[spec]
        lo, hi = axes[ax]["extent"]
        return ax, (lo + hi) / 2
    if "=" in spec:
        a, _, v = spec.partition("=")
        if a.strip() in ("x", "y", "z"):
            try:
                return a.strip(), float(v)
            except ValueError:
                return None
    return None


# ----------------------------------------------------------------------------- GUI

def run_gui(outdir, batch_path=None, parts=None):
    """Axis radio + position slider over the precomputed slices, plus a main.batch
    capture panel: name the section you're viewing and Save it as a
    `<name> <axis>=<pos> [parts=…]` line, click an existing entry to jump to it, or
    Delete it. Images are PRELOADED and the two imshow artists updated in place
    (set_data) — no disk read or axes rebuild per tick, so the slider stays fluid.
    Imports matplotlib lazily so the parent picks an interactive backend."""
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Button, RadioButtons, Slider, TextBox

    man = json.loads((outdir / "slices.json").read_text())
    data = man["axes"]

    # Preload everything ONCE: decode each PNG to an array now, never during a drag.
    names = {L[k] for a in data.values() for L in a["levels"] for k in ("plot", "preview") if L[k]}
    print(f"preloading {len(names)} images…", flush=True)
    cache = {nm: mpimg.imread(str(outdir / nm)) for nm in names}

    def first(key):
        for a in data.values():
            for L in a["levels"]:
                if L[key]:
                    return cache[L[key]]
        return np.ones((4, 4, 4))

    state = {"axis": "z", "idx": 0}              # current view; fmt_line reads it for capture
    entries, holder = [], {"list": None, "labels": []}
    guard = {"prog": False}                      # suppress the radio callback during a jump

    fig = plt.figure(figsize=(14, 8))
    fig.canvas.manager.set_window_title(f"slice_viewer — {man['input']}")
    ax_prev = fig.add_axes([0.02, 0.32, 0.40, 0.62]); ax_prev.axis("off")
    ax_plot = fig.add_axes([0.43, 0.32, 0.38, 0.62]); ax_plot.axis("off")
    ax_radio = fig.add_axes([0.02, 0.10, 0.05, 0.16])
    ax_sld = fig.add_axes([0.14, 0.24, 0.66, 0.03])

    # persistent artists — we only swap their pixels (set_data), never recreate them;
    # interpolation="nearest" keeps the per-tick redraw cheap (no antialiased resample)
    prev_im = ax_prev.imshow(first("preview"), interpolation="nearest")
    plot_im = ax_plot.imshow(first("plot"), interpolation="nearest")
    ax_prev.set_title("preview — where it cuts", fontsize=9)
    ax_plot.set_title(f"plot — compare overlay vs {man['vs']}" if man.get("vs")
                      else "plot — dimensioned section", fontsize=9)
    prev_txt = ax_prev.text(0.5, 0.5, "(no section here)", ha="center", va="center",
                            transform=ax_prev.transAxes, color="#888", fontsize=11, visible=False)
    plot_txt = ax_plot.text(0.5, 0.5, "(no section here)", ha="center", va="center",
                            transform=ax_plot.transAxes, color="#888", fontsize=11, visible=False)

    radio = RadioButtons(ax_radio, ("x", "y", "z"), active=2)
    sld = Slider(ax_sld, "position", 0, max(1, len(data["z"]["levels"]) - 1), valinit=0, valstep=1)
    msg = fig.text(0.14, 0.05, "", fontsize=9, color="#246")

    def show(axis, idx):
        levels = data[axis]["levels"]
        idx = max(0, min(int(round(idx)), len(levels) - 1))
        state["axis"], state["idx"] = axis, idx
        L = levels[idx]
        for im, txt, key in ((prev_im, prev_txt, "preview"), (plot_im, plot_txt, "plot")):
            if L[key]:
                im.set_data(cache[L[key]]); im.set_visible(True); txt.set_visible(False)
            else:
                im.set_visible(False); txt.set_visible(True)
        fig.suptitle(f"{man['input']}    {axis} = {L['pos']:.2f} mm    "
                     f"level {idx + 1}/{len(levels)}", fontsize=12)
        fig.canvas.draw_idle()

    def set_axis_view(axis, idx):
        levels = data[axis]["levels"]
        sld.valmax = max(1, len(levels) - 1)
        sld.ax.set_xlim(sld.valmin, sld.valmax)
        sld.eventson = False
        sld.set_val(max(0, min(idx, len(levels) - 1)))   # set slider without re-firing show
        sld.eventson = True
        show(axis, idx)

    def on_slide(val):
        show(state["axis"], val)

    def on_axis(label):
        if guard["prog"]:                # a programmatic jump set this — don't reset to 0
            return
        set_axis_view(label, 0)

    def jump_to(axis, pos):
        levels = data[axis]["levels"]
        idx = min(range(len(levels)), key=lambda i: abs(levels[i]["pos"] - pos))
        guard["prog"] = True
        radio.set_active(("x", "y", "z").index(axis))
        guard["prog"] = False
        set_axis_view(axis, idx)

    sld.on_changed(on_slide)
    radio.on_clicked(on_axis)

    # ---- main.batch capture panel (only when slicing a .scad front door) ----
    if batch_path is not None:
        ax_list = fig.add_axes([0.83, 0.30, 0.16, 0.64])
        ax_name = fig.add_axes([0.20, 0.13, 0.18, 0.045])
        ax_save = fig.add_axes([0.40, 0.13, 0.12, 0.045])
        ax_del = fig.add_axes([0.54, 0.13, 0.12, 0.045])
        namebox = TextBox(ax_name, "name ")
        b_save = Button(ax_save, "Save to batch")
        b_del = Button(ax_del, "Delete")

        def fmt_line(name):
            pos = data[state["axis"]]["levels"][state["idx"]]["pos"]
            line = f"{name}  {state['axis']}={round(pos, 1):g}"
            return line + (f"  parts={parts}" if parts else "")

        def on_pick(label):
            i = holder["labels"].index(label)
            name, spec, _p = entries[i]
            namebox.set_val(name)            # so Save updates / Delete targets this entry
            r = spec_axis_pos(spec, data)
            if r:
                jump_to(*r)
            msg.set_text(f"{name}  →  {spec}"); fig.canvas.draw_idle()

        def rebuild_list():
            ax_list.clear(); ax_list.axis("off")
            ax_list.set_title("main.batch", fontsize=9)
            entries[:] = read_entries(batch_path)
            labels = [f"{n}   {s}" + (f"  [{p}]" if p else "") for (n, s, p) in entries]
            holder["labels"] = labels
            if labels:
                rb = RadioButtons(ax_list, labels)
                for lbl in rb.labels:
                    lbl.set_fontsize(8)
                rb.on_clicked(on_pick)
                holder["list"] = rb           # keep a ref so the widget stays live
            else:
                ax_list.text(0.5, 0.92, "(no entries yet)", ha="center", va="top",
                             transform=ax_list.transAxes, color="#888", fontsize=9)
                holder["list"] = None
            fig.canvas.draw_idle()

        def on_save(_event):
            name = namebox.text.strip()
            if not name:
                msg.set_text("type a name first"); fig.canvas.draw_idle(); return
            line = fmt_line(name)
            upsert_entry(batch_path, name, line)
            rebuild_list()
            msg.set_text(f"saved   {line}   → {Path(batch_path).name}"); fig.canvas.draw_idle()

        def on_del(_event):
            name = namebox.text.strip()
            if not name:
                msg.set_text("type or click a name to delete"); fig.canvas.draw_idle(); return
            delete_entry(batch_path, name)
            rebuild_list()
            msg.set_text(f"deleted   {name}"); fig.canvas.draw_idle()

        b_save.on_clicked(on_save)
        b_del.on_clicked(on_del)
        holder["widgets"] = (namebox, b_save, b_del)   # keep refs alive for plt.show()
        rebuild_list()
    else:
        fig.text(0.83, 0.6, "(.batch capture needs a\nmain.scad front door)",
                 fontsize=9, color="#888")

    show("z", 0)
    plt.show()


# ----------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="a .scad front door or a single .stl")
    ap.add_argument("--parts", default=None,
                    help="front-door module(s) to slice (default: all *_solid)")
    ap.add_argument("--vs", default=None, metavar="REF",
                    help="reference design (.scad/.stl): each slice's plot becomes compare.py's "
                         "overlay (model in blue over reference in grey; red/orange = deviation) "
                         "instead of the dimensioned section. Both must sit in the SAME frame "
                         "(no alignment), like compare.py")
    ap.add_argument("--vs-parts", default=None,
                    help="front-door module(s) of the --vs reference to slice (default: all *_solid)")
    ap.add_argument("--tolerances", default=None, metavar="FILE",
                    help="--vs: custom tolerances JSON (compare.py shape); omitted keys fall back to defaults")
    ap.add_argument("--tol", type=float, default=None,
                    help="--vs: override all mm detectors (contour/holes/fillets/extents) for the overlay")
    ap.add_argument("--step", type=float, default=2.0, help="sweep step in mm (default 2.0)")
    ap.add_argument("--reuse", action="store_true",
                    help="skip preprocessing entirely; open the GUI on the existing sections dir")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if the inputs hash unchanged (default: reuse on match)")
    ap.add_argument("--build-only", action="store_true",
                    help="only precompute the slices, do not open the GUI")
    ap.add_argument("--size", type=int, default=700, help="preview render size px (default 700)")
    ap.add_argument("--jobs", "-j", type=int, default=DEFAULT_JOBS,
                    help=f"parallel render processes for the preprocess (default {DEFAULT_JOBS}; 1 = in-process)")
    ap.add_argument("--fn", type=int, default=120)
    ap.add_argument("--openscad", default=None)
    ap.add_argument("--_build", dest="build", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        sys.exit(f"no such file: {inp}")
    outdir = build_dir(inp) / f"{inp.stem}_slices"
    # the capture panel writes the sibling <stem>.batch (main.scad→main.batch,
    # stl_assembly.scad→stl_assembly.batch) — only meaningful for a .scad front door
    batch_path = inp.with_name(f"{inp.stem}.batch") if inp.suffix.lower() == ".scad" else None

    vs_input = Path(args.vs) if args.vs else None
    if vs_input is not None and not vs_input.exists():
        sys.exit(f"--vs does not exist: {vs_input}")

    if args.build:                                   # internal: the headless preprocess worker
        parts = args.parts.split(",") if args.parts else None
        vs_parts = args.vs_parts.split(",") if args.vs_parts else None
        tol = None
        if vs_input is not None:                     # resolve compare's per-detector tolerances once
            tol = load_tolerances(args.tolerances)
            if args.tol is not None:
                for k in ("contour", "holes", "fillets", "extents"):
                    tol[k] = args.tol
        build_slices([inp], parts, args.step, args.fn, args.size,
                   locate_openscad(args.openscad), outdir, args.jobs, args.force,
                   vs_input=vs_input, vs_parts=vs_parts, tol=tol)
        return 0

    if args.reuse:
        if not (outdir / "slices.json").exists():
            sys.exit(f"--reuse but no precomputed sections in {outdir} — run it without --reuse first")
    else:
        # Preprocess in a SUBPROCESS so its Agg backend doesn't block the GUI window.
        cmd = [sys.executable, str(Path(__file__).resolve()), "--_build", str(inp),
               "--step", str(args.step), "--fn", str(args.fn), "--size", str(args.size),
               "--jobs", str(args.jobs)]
        if args.force:
            cmd.append("--force")
        if args.parts:
            cmd += ["--parts", args.parts]
        if args.vs:
            cmd += ["--vs", str(vs_input)]
        if args.vs_parts:
            cmd += ["--vs-parts", args.vs_parts]
        if args.tolerances:
            cmd += ["--tolerances", args.tolerances]
        if args.tol is not None:
            cmd += ["--tol", str(args.tol)]
        if args.openscad:
            cmd += ["--openscad", args.openscad]
        if subprocess.run(cmd).returncode != 0:
            sys.exit("the section preprocess failed")

    if args.build_only:
        print(f"sections ready in {outdir} (--reuse to open the viewer without recomputing)")
        return 0

    run_gui(outdir, batch_path, args.parts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
