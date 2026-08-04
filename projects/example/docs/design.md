# example — Design documentation

> The template's **starter** project. This `design.md` also serves as an **example** of the
> convention: copy it (and delete it along with the rest of `projects/example/`) when you start
> your own design.

## What it is and purpose

A two-piece box — tray and lid — for a generic 50 × 70 mm PCB. It mates with no real hardware:
its purpose is to **seed the canonical layout** of the repo and to show the full reuse chain:

- `lib/rounded` provides the generic primitive (the rounded-corner shell),
- `components/pcb_holder` provides the concrete reusable part (the board retention),
- this project only **combines** the two and adds what is its own.

Dependencies only go down, and neither layer knows this project exists.

## Requirements and constraints

- The PCB is retained with **no screws and no posts**: the component's four corner clips do it
  (ledge below, lip above).
- The cavity has to clear the PCB **and the component itself**: the holder puts a wall of
  `PCBH_WALL` outside each corner, plus `PCBH_FIT` of play per side. Hence the cavity is the
  PCB + 4.4 mm and not the bare PCB.
- Both pieces printable **without supports**: the tray rests on its floor and the lid prints
  flipped, flat outer face against the bed.
- Footprint within a 180 × 180 bed (58.4 × 78.4 actual).

## Design decisions

- **Two pieces and not one.** It is the minimum for the example to have a joint worth
  inspecting by sections — the very loop this repo preaches.
- **The lid rim is a rim, not a slab.** The first version modelled it as a solid block the size
  of the cavity: it passed `check.py` just as happily (manifold, watertight) but it was 21 cm³
  of plastic and left the box with no usable space. The section cut gave it away. Hollowing it
  brought it down to 10.2 cm³. It is the textbook case of **a numeric PASS not implying a
  usable part**.
- **No screws.** A screwed closure would pull in a screw-cutter primitive (not shipped in this
  template) plus inserts and bosses, and the
  starter would stop reading in one sitting. The rim locates the lid but does NOT retain it (0.25 mm of clearance per side); a real
  project would add screws or a snap.
- **The holder height is duplicated as a constant** (`BOX_HOLDER_H`) even though the component
  exposes it as a function. The reason is NOT that it cannot be called — `use` does import
  functions, and `base.scad` calls it in its `assert`: it is that the **dimension drawing** reads
  literal constants out of the `.scad` (`dimsketch.read_params`), and a function cannot be read
  that way. So the copy does not drift silently, `base()` asserts it still matches
  `pcb_holder_height()`. The pure concession is `BOX_FIT` / `BOX_HOLDER_WALL`, which mirror
  `PCBH_FIT` / `PCBH_WALL` because the component exposes no accessors for those.

## Mechanics / how it works

The tray is the shell minus the cavity, with the holders standing on its floor (lifted by
`BOX_FLOOR`, because the component's frame puts its `z = 0` at the host floor). The PCB seats on
the ledges at `BOX_FLOOR + standoff` and is trapped under the lips.

The lid rests its plate on the tray rim and drops a rim into the cavity, with `BOX_LID_CL` of
play per side, which centres it and stops it shifting sideways.

## Key parameters

All in `modules/example_config.scad`, each with its provenance tag. The ones you touch first
when adapting the box to another PCB: `BOX_PCB_W`, `BOX_PCB_L`, `BOX_PCB_T` and `BOX_HEADROOM`
(the free height above the lip, which depends on how tall whatever sits on the board is). The
rest — walls, floor, radius, lid clearance — is rarely touched.

Dimension drawing: `drawings/example_dims.py` (regenerate with `uv run`).

## Printing

- `base_print` — as is, open side up.
- `lid_print` — flipped 180°, outer face against the bed and the rim pointing up.

No supports on either. `build.py` emits one STL for each.

## Status and evolution

Verified with the tools: `check.py` reports manifold and watertight on both pieces,
`check.py --parts` finds no interference between tray and lid, and the five sections of
`main.batch` have been reviewed. **Never printed**: it is a template. If anyone does print it,
the first thing to confirm with calipers is `BOX_LID_CL` — the lid clearance is the only thing
here that is a guess.

That guess has its **test piece**: `test/lid_fit_test.scad` cuts a corner coupon out of the real
`base()` and `lid()` (an `intersection()`, not a second copy of the geometry) so the fit can be
printed and read for ~2 cm³ instead of the ~30 cm³ the two full pieces cost. It is also the
worked example of the `test/` convention that the `openscad-design-from-specs` skill asks for.
When someone prints it, the outcome flips `BOX_LID_CL` from `ADJUST` to `MEASURED` — and this
section says so.
