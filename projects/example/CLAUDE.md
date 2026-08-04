# example — CLAUDE.md

> Design documentation: [`docs/design.md`](docs/design.md).

## Project

The template's **starter** project: a two-piece enclosure for a generic 50 × 70 PCB.
It exists to seed the canonical layout (`main.scad` + `modules/` + `_config`) and,
above all, to show **the three layers working together** — the shell comes from
`lib/rounded`, the board retention from the `components/pcb_holder` component, and
this project only combines them.

It mates with no real hardware: the PCB dimensions are the component's defaults.
**Delete it** (the whole `projects/example/` folder) once you have pieces of your own.

## Layout / pieces

Single front door: `main.scad` (module catalog: `base_print | lid_print` printables,
`base_solid | lid_solid` for inspection, `assembly`). The geometry lives in `modules/`:

- `modules/base.scad` — the tray: a rounded shell open on top, with the four corner
  clips of `pcb_holder` standing on its floor.
- `modules/lid.scad` — the lid: a plate of the same outline plus a **rim** that plugs
  into the cavity and locates it (not a solid slab: that would fill the box with
  plastic).
- `modules/example_config.scad` — the constants, with their provenance (`ADJUST`) and
  the derived ones exposed as functions (`box_cav_w()`, `box_rim_z()`…).
- `main.batch` — the iteration slice-set: the two central elevations plus three planes
  that actually give this part away (the clips, the PCB seating plane, the lid joint).

And the test-piece convention, in `test/`:

- `test/lid_fit_test.scad` — a corner coupon of the tray and of the lid, cut out of the
  **real** `base()`/`lid()` with an `intersection()` instead of re-derived, to settle the
  one dimension here that is a guess (`BOX_LID_CL`) for 2 cm³ instead of 30.

## Frames

- **Tray**: XY centred on the PCB, `z = 0` at the bottom of the box (the print bed).
- **Lid**: same XY, `z = 0` at the **mating plane** (the tray rim), plate growing +Z and
  rim hanging −Z. So in the assembly it is just `translate([0, 0, box_rim_z()]) lid()`.
- `pcb_holder` brings its own frame (`z = 0` = host floor), which is why the tray lifts
  it by `BOX_FLOOR`.

## Status

Verified with the tools: both pieces manifold and watertight (`check.py`), no interference
between tray and lid (`check.py --parts`), and reviewed by sections. **Never printed** — it
is a template, not a part in use.
