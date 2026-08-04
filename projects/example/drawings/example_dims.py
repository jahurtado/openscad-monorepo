"""example_dims — parametric SKETCH of the starter enclosure.

A simple sketch of the knobs that dimension the box (not the faithful drawing:
that's `slice`'s job). Values and provenance come from modules/example_config.scad
via ds.read_params (single source). Two views: plan (XY) with the cavity and the
PCB it houses, and a front elevation (XZ) with floor, cavity and the lid lip.

Regenerate: uv run projects/example/drawings/example_dims.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools"))
import dimsketch as ds

P = ds.read_params(os.path.join(os.path.dirname(__file__), "..", "modules", "example_config.scad"))

PCB_W = P["BOX_PCB_W"].value
PCB_L = P["BOX_PCB_L"].value
FIT   = P["BOX_FIT"].value
HW    = P["BOX_HOLDER_WALL"].value
HH    = P["BOX_HOLDER_H"].value
WALL  = P["BOX_WALL"].value
FLOOR = P["BOX_FLOOR"].value
HEAD  = P["BOX_HEADROOM"].value
R     = P["BOX_CORNER_R"].value
LID_T = P["BOX_LID_T"].value
LIP_H = P["BOX_LIP_H"].value

# Derived exactly as the .scad does (functions there, arithmetic here).
CAV_W = PCB_W + 2 * (FIT + HW)
CAV_L = PCB_L + 2 * (FIT + HW)
CAV_H = HH + HEAD
OUT_W = CAV_W + 2 * WALL
OUT_L = CAV_L + 2 * WALL
RIM_Z = FLOOR + CAV_H

fig, (axp, axe, axt) = ds.sketch(
    3, size=(8.2, 11.0), height_ratios=[1.5, 0.9, 0.9],
    titles=["plan (X→, Y↑) — outer shell, cavity and the PCB it houses",
            "front elevation (X→, Z↑) — floor, cavity, lid lip",
            None])

# ===== (1) PLAN XY =====
ds.board_outline(axp, OUT_W, OUT_L, R + WALL)                       # outer shell
ds.rect(axp, 0, 0, CAV_W, CAV_L, fc="white", ec="#bbb", lw=0.9)     # cavity
ds.rect(axp, 0, 0, PCB_W, PCB_L, fc="#cfe0cf", ec="#9bb59b",        # the board
        lw=1.0, alpha=0.75)
axp.text(0, 0, "PCB", ha="center", va="center", color="#5a7a5a", fontsize=9)

ds.param_h(axp, -PCB_W / 2, PCB_W / 2, PCB_L / 2 + 4, P["BOX_PCB_W"], grows="x")
ds.param_v(axp, -PCB_L / 2, PCB_L / 2, PCB_W / 2 + 5, P["BOX_PCB_L"], grows="y")
ds.param_h(axp, -OUT_W / 2, -CAV_W / 2, -OUT_L / 2 - 7, P["BOX_WALL"], grows="x")
ds.param_dia(axp, OUT_W / 2 - 0.3 * R, OUT_L / 2 - 0.3 * R, 2 * R, P["BOX_CORNER_R"], grows="r")
axp.set_xlim(-OUT_W / 2 - 16, OUT_W / 2 + 16)
axp.set_ylim(-OUT_L / 2 - 18, OUT_L / 2 + 12)

# ===== (2) FRONT ELEVATION XZ =====
# Base: floor + the two walls, drawn as a U.
ds.rect(axe, 0, FLOOR / 2, OUT_W, FLOOR, fc=ds.FILL, ec=ds.EDGE, lw=1.4)
for sx in (-1, 1):
    ds.rect(axe, sx * (CAV_W + WALL) / 2, FLOOR + CAV_H / 2, WALL, CAV_H,
            fc=ds.FILL, ec=ds.EDGE, lw=1.4)
# Lid: plate on the rim + the lip hanging into the cavity.
ds.rect(axe, 0, RIM_Z + LID_T / 2, OUT_W, LID_T, fc="#dbe4ef", ec=ds.EDGE, lw=1.4)
for sx in (-1, 1):
    ds.rect(axe, sx * (CAV_W - P["BOX_LIP_T"].value) / 2, RIM_Z - LIP_H / 2,
            P["BOX_LIP_T"].value, LIP_H, fc="#dbe4ef", ec=ds.EDGE, lw=1.2)
# The board on its standoff, for scale.
axe.plot([-PCB_W / 2, PCB_W / 2], [FLOOR + 2, FLOOR + 2], color="#5a7a5a", lw=2.5)

ds.param_v(axe, 0, FLOOR, -OUT_W / 2 - 4, P["BOX_FLOOR"], grows="y")
ds.param_v(axe, FLOOR + HH, RIM_Z, OUT_W / 2 + 4, P["BOX_HEADROOM"], grows="y")
ds.param_v(axe, RIM_Z - LIP_H, RIM_Z, OUT_W / 2 + 12, P["BOX_LIP_H"], grows="y")
ds.param_v(axe, RIM_Z, RIM_Z + LID_T, -OUT_W / 2 - 12, P["BOX_LID_T"], grows="y")
axe.set_xlim(-OUT_W / 2 - 22, OUT_W / 2 + 22)
axe.set_ylim(-4, RIM_Z + LID_T + 6)

# ===== (3) knobs panel =====
ds.param_table(axt, P, only=["BOX_PCB_W", "BOX_PCB_L", "BOX_PCB_T", "BOX_WALL",
                             "BOX_FLOOR", "BOX_HEADROOM", "BOX_CORNER_R",
                             "BOX_LID_T", "BOX_LIP_H", "BOX_LIP_T", "BOX_LID_CL"])

ds.finish(fig, os.path.join(os.path.dirname(__file__), "example_dims.png"))
