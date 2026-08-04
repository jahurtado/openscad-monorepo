---
name: openscad-design-from-stl
description: |
  Reconstruct a parametric OpenSCAD model from one or more existing STL MESHES
  (faithful replica, replica + parametrize, or redesign using the STL as a
  dimensional reference). Drives the mesh → characterize → method → iterate flow
  against the criteria. If there is NO STL and you design from measurements, use openscad-design-from-specs.
model: inherit
---

# Parametric design from an STL

Procedure for taking a mesh to a parametric `.scad`. It assumes the **model anatomy** from
[`docs/components.md`](../../../docs/components.md) and the invariants in `CLAUDE.md` — I don't repeat them.

## Before you start
- Pre-flight once: `uv run tools/health_check.py`.
- **No mesh at hand** (rehearsing the flow, or demonstrating it)? Nothing binary ships in this repo:
  generate one with `./build.sh example` and use `projects/example/prints/example_base_print.stl` as
  the stand-in vendor mesh. Its parametric source is right there, so every number the flow recovers
  can be checked against the truth — see README, "Try it against the starter project".
- **Don't improvise with trimesh or the OpenSCAD binary by hand** (a guard blocks them): there's a tool
  for each step (`check.py`, `analyze.py`, `slice.py`, `render3d.py`, `compare.py`, `make_assembly.py`,
  `center_input.py`). Only reach past them in the rare case where you need something very specific that
  the tools can't do.

## Flow
0. **Identify the working directory** based on the project we're working in, or create a new directory
   inside `projects/`.
1. Copy the meshes (STL files) into `resources/` and **center** with `tools/center_input.py` (repositions, does not reorient).
2. **Assemble the reference** with `tools/make_assembly.py` (`stl_assembly.scad`) using the STL files that belong to the same design.
3. **Validate the assembly/orientation WITH the user** before designing, in case there is more than one STL file.
   The unit of work is always a `.scad` (everything operates on it, never on the raw STL).
4. **Characterize** the 3D model with the **`stl-analyzer`** subagent. Identify features, possible
   modeling strategies, holes, standoffs, chamfers, etc.
5. **Write `stl_assembly.batch`** with the planes that actually reveal the part (not just x/y/z=0).
   That manifest is not documentation: it is the input `tools/run_batch.py` consumes to regenerate the
   whole slice-set in one pass (step 9). Curate it so it stays worth re-running on every iteration.
6. **`tools/slice_viewer.py`** → the user **curates** the sections. Don't proceed until they confirm.
7. **Declare the METHOD (`// METHOD:`) and review it BEFORE building**: per feature, which primitive it
   comes from. Launch the **`design-conventions-reviewer`** subagent on the plan — it's the cheapest
   place to catch the bluff (declaring a sweep and actually stacking).
8. **Bottom-up**: detail features → combine them parametrized. Overhang **±EPS** on every cutter/stack.
9. **Iterate** `check.py` (manifold) + **`run_batch.py`**, which regenerates every plane of the `.batch`
   in one pass — that is what the manifest from step 5 is for; drop to `slice.py` directly only for a
   one-off plane you don't want in the set. Then **look at it in 3D from several
   viewpoints** with `render3d.py` (clean 3D views; `--vs <mesh>` = deviation heatmap against the
   reference, which `slice` doesn't give). For the NUMERIC criterion against the mesh, `compare.py`
   (Hausdorff per plane). **Criterion depends on the goal (step 0).**
9b. **Verify the functional FEATURES per section against the mesh** with `slice_viewer.py --vs <mesh>`
   (overlay of the model on the reference, plane by plane). The numeric PASS is **not enough**: `check`/`compare`/
   `render3d` don't distinguish which **side** of a hole is capped, on which **face** a pocket sits, **conical vs
   flat**, **blind vs through**, or **hex vs round**. Walk through every feature and confirm it by eye. *(Lesson from
   the A/B bench: the surface metric oversells; the section cut is the arbiter.)*
10. **METHOD criterion before delivery**: run `design-conventions-reviewer` on the final `.scad`.
   Definition of done = geometry PASS (manifold) ∧ **every functional feature verified per section (9b)** ∧
   reviewer PASS. A green `compare` over a slice-stack — or with a capped hole / rounded hex /
   flattened countersink the metric didn't catch — is **not** done.

## Method
Build following the **[design rules](../../../docs/design-rules.md)** — the idioms (faceted trace forbidden,
organic silhouette → DXF, thread → a thread library (not bundled), revolution → `rotate_extrude`, coplanar faces →
±EPS) and the imported DXF profile protocol live there, and they are what the
`design-conventions-reviewer` judges in steps 7 and 10.
