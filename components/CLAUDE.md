# components/ — catalog of real components (reusable models)

`components/` is the **catalog**: parametric models of real physical objects reusable across
projects (unlike `lib/`, which holds basic modeling libraries). It keeps **only the importable `.scad`** (single source); the development scaffolding — tests, drawings, photos — lives in the **bench project** `projects/<name>/`, which imports it. *(No bench project comes with it — see "What's here" below.)*

**Each component documents its identity (what it is, source/vendor, origin) in its `.scad` header;
its API is the modules that same file defines** — not cataloged or described here. For everything else:

- **Modeling a component** (anatomy: roles, origin, template) → [`../docs/components.md`](../docs/components.md).
- **Design rules** (construction idioms + annotating `MEASURED`/`ADJUST` constants) → [`../docs/design-rules.md`](../docs/design-rules.md).

## What's here

One worked example, `pcb_holder` — the component the starter project reuses, so the whole chain
`projects → components → lib` is there to read end to end. This layer is meant to grow: it is where
your first promoted component lands, next to the parts you measure off your own hardware.

`pcb_holder` comes **without a bench project**: `projects/example/` doubles as the consumer that
exercises it, which is enough to read the chain end to end but is *not* the bench the convention asks
for. Expect to create `projects/<name>/` when you promote your first component — don't take this
layout as evidence that a component may live here bare.

## Backward compatibility

A shared component **is API**: changing its origin, its anchors or the semantics of its cutout
**silently breaks** every project that uses it. Follow the **compatibility rule** in
[`../docs/design-rules.md`](../docs/design-rules.md); here the observable surface is origin/anchors/cutout and the
impact criterion is `uv run tools/check.py --all-projects` (no render of any project may break).
