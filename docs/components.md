# Modeling an external component

An external component (sensor, connector, PCB module, etc.) is reproduced as a reusable parametric **model** so it can be fitted into the final part.

## Characteristics

- If it is reusable across different projects, it is added to the catalog inside `components/`.
- If it is NOT reusable (specific to one project), it is added as a project module in `projects/<p>/modules/`.
- They have no dependencies on other components. The only dependencies allowed are on the basic primitives defined in `lib/`.
- **Every reusable component gets an associated bench project** (`pcb_holder` is here without its bench;
  `projects/example/` doubles as the consumer that exercises it). It lives in `components/` as the **single source** (just the importable `.scad`), but its scaffolding —drawings, documentation, tests, provenance photo— lives in a `projects/<name>/` project that imports it (doesn't copy it) and serves as a bench to develop and validate it.

## Design strategies

Depending on where the geometry comes from — the **process** for each one lives in its skill:

- **From a pre-existing STL model** → skill `openscad-design-from-stl`.
- **With no pre-existing model** (from measurements/specs) → skill `openscad-design-from-specs`.

## Anatomy of a component

A component is not a single module but **several** —one per ROLE (table below): the solid, the
cutout, the anchors…—. They all share the component's **same local origin**, so the part
that uses it places it **once** (`translate()`/`rotate()`) and all its parts fall into place
together. Implement only the roles that apply.

| Role       | Signature                         | When?                                  | What it is                              |
| ---------- | --------------------------------- | -------------------------------------- | --------------------------------------- |
| **solid**  | `module <name>()`                 | always                                 | the object as-is (visual / clash)       |
| **cutout** | `module <name>_cutout(clearance)` | if the host subtracts something        | the negative: void / window / holes     |
| **anchor** | `function <name>_anchor(name)`    | if there are positions or measurements | points/measurements in local coords     |
| **mount**  | `module <name>_mount(...)`        | only "cartridge" (bezel/bracket/chassis) | the structure that integrates it       |
| **lid**    | `module <name>_lid(...)`          | if it carries a lid/companion          | a printable part that goes with it      |

**Minimum:** `solid` + `cutout` + `anchor`; `mount`/`lid` only when they apply.

Interface rules:

- The **anchors are functions**, not loose variables (`use <...>` only imports modules and functions).
- **`clearance`** is always a parameter (~0.3 mm FDM by default).
- The **cutout ≠ visual + clearance**: it shares the origin but its shape is deliberately
  different (protrusions as negative volume, through-holes, windows, reliefs). Its cylinders and
  openings **protrude** past the wall, never flush (see [`design-rules.md`](design-rules.md)):
  ±20 mm in Z, ±50 mm at the openings.
- A **fully enclosed** component (access via lid) is just a cutout *with no openings*.

### Choosing the origin

Decide it **before** drawing and document it in the model's header; the anchors are expressed relative to it. For a PCB: bottom face at `Z=0` (it rests on standoffs), XY centered on the mounting-hole pattern (what anchors the board to the box), not on the contour.

## Template

```scad
// ============================================================
//  <name> — component model. Source: <datasheet | resources/<name>.stl>.
//  Origin: bottom face at Z=0, XY centered on the hole pattern.
//  Bbox:  x∈[..], y∈[..], z∈[0, ..].
// ============================================================

<NAME>_PCB     = [25, 18, 1.6];  // MEASURED: PCB outline
<NAME>_HOLE_DX = 20;             // MEASURED: hole spacing

function <name>_anchor(name) =
    name == "origin"  ? [0, 0, 0] :
    name == "mount_a" ? [ <NAME>_HOLE_DX/2, 0, 0] :
    name == "mount_b" ? [-<NAME>_HOLE_DX/2, 0, 0] :
    undef;

module <name>() {
    color("green") cube(<NAME>_PCB, center = true);   // or import(...) if the visual comes from an STL
}

// Cylinders ±20 mm in Z to always cross the wall.
module <name>_cutout(clearance = 0.3) {
    for (a = ["mount_a", "mount_b"])
        translate(<name>_anchor(a))
            translate([0, 0, -20]) cylinder(h = 40, r = 1.5 + clearance);
}

<name>();   // self-preview (use <...> ignores it; never include)
```

Part files do **not** set `$fn`/`$fa`/`$fs` — they inherit them from the part that imports them.

## Worked example: `arduino_nano`

The three representations in a single origin (PCB bottom face at `Z=0`):

```scad
module arduino_nano() {                       // nominal: visual with no clearance
    color("DarkGreen") cube([43.18, 17.78, 1.6]);              // PCB
    color("Silver") translate([-2, 17.78/2 - 4, 1.6])
        cube([8, 8, 3.2]);                                     // mini-USB poking out
}

module arduino_nano_cutout(clearance = 0.3) {                 // negative to subtract
    c = clearance;
    translate([-c, -c, -c])                                    // PCB void with clearance
        cube([43.18 + 2*c, 17.78 + 2*c, 1.6 + 2*c]);
    translate([-50, 17.78/2 - 4 - c, 1.6 - c])                 // USB through the wall
        cube([60, 8 + 2*c, 3.2 + 2*c]);
}

function arduino_nano_anchor(name) =                          // points in local coords
    name == "origin"      ? [0, 0, 0] :
    name == "center"      ? [43.18/2, 17.78/2, 1.6/2] :
    name == "usb"         ? [0, 17.78/2, 1.6/2] :
    name == "mount_hole1" ? [2.54, 2.54, 0] :
    name == "mount_hole2" ? [40.64, 2.54, 0] :
    undef;
```

Use from the part — the mounting holes are positioned via anchors, with no coordinate recomputation:

```scad
difference() {
    my_enclosure();
    translate([10, 10, 2]) arduino_nano_cutout();
    for (a = ["mount_hole1", "mount_hole2"])
        translate([10, 10, 2] + arduino_nano_anchor(a))
            cylinder(d = 2.5, h = 20, center = true);
}
```

> The literals (43.18, 17.78…) are inline for the example's brevity; a real model would put them as named constants tagged `MEASURED`/`ADJUST` (see [Template](#template)).
