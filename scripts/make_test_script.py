"""Build a big fake comp to try zconnect on.

Paste into the Script Editor, or: nuke -t scripts/make_test_script.py out.nk
"""

from __future__ import annotations

import random
import sys
from typing import Any

import nuke

SEED = 74
COLUMN_WIDTH = 180
ROW_HEIGHT = 60

ELEMENTS = [
    "bg_plate", "fg_plate", "cleanplate", "mg_plate", "sky_replace",
    "smoke_elem", "smoke_elem_b", "fire_elem", "sparks_elem", "dust_elem",
    "debris_elem", "rain_elem", "fog_elem", "lens_flare", "glow_pass",
    "char_beauty", "char_spec", "char_diffuse", "char_shadow", "char_ao",
    "env_beauty", "env_reflection", "env_depth", "env_motion",
    "crowd_l", "crowd_r", "vehicle_beauty", "vehicle_shadow", "matte_painting",
    "light_wrap",
]
CORRECTIONS = [
    "Grade", "ColorCorrect", "Transform", "Blur",
    "Saturation", "HueCorrect", "Defocus", "Erode",
]
DOT_LABELS = ["to comp", "denoised", "precomp", "keep", "for despill", "graded", "lineup"]


def _place(node: Any, *, column: float, row: int) -> Any:
    node.setXYpos(int(column * COLUMN_WIDTH), row * ROW_HEIGHT)
    return node


def _element(name: str, *, column: int, rng: random.Random) -> Any:
    """Build one element branch and return its last node."""
    version = rng.randint(1, 12)
    path = f"/shows/demo/sh010/elements/{name}/{name}_v{version:03d}.####.exr"
    read = _place(nuke.nodes.Read(file=path), column=column, row=0)

    last = read
    row = 1
    for correction in rng.sample(CORRECTIONS, rng.randint(2, 6)):
        node = _place(getattr(nuke.nodes, correction)(), column=column, row=row)
        node.setInput(0, last)
        last = node
        row += 1

    if rng.random() < 0.4:
        roto = _place(nuke.nodes.Roto(label=f"{name} mask"), column=column + 0.5, row=row - 1)
        grade = _place(nuke.nodes.Grade(label="masked"), column=column, row=row)
        grade.setInput(0, last)
        grade.setInput(grade.optionalInput(), roto)
        last = grade
        row += 1

    if rng.random() < 0.5:
        label = f"{name} {rng.choice(DOT_LABELS)}"
        dot = _place(nuke.nodes.Dot(label=label), column=column, row=row)
        dot.setInput(0, last)
        last = dot

    return last


def _orphans(rng: random.Random, start_column: int) -> None:
    """Add loose nodes and unlabelled Dots, the clutter real scripts have."""
    for index in range(20):
        node = getattr(nuke.nodes, rng.choice(CORRECTIONS + ["Dot", "NoOp", "Shuffle"]))()
        _place(node, column=start_column + index % 5, row=12 + index // 5)


def build() -> None:
    """Build the whole fake comp in the current script."""
    rng = random.Random(SEED)

    branches = [_element(name, column=column, rng=rng) for column, name in enumerate(ELEMENTS)]

    comp = branches[0]
    for row, branch in enumerate(branches[1:], start=1):
        operation = rng.choice(["over", "over", "plus", "screen"])
        merge = _place(nuke.nodes.Merge2(operation=operation), column=0, row=10 + row)
        merge.setInput(0, comp)
        merge.setInput(1, branch)
        comp = merge

    write = nuke.nodes.Write(file="/shows/demo/sh010/comp/sh010_comp_v001.####.exr")
    _place(write, column=0, row=11 + len(branches))
    write.setInput(0, comp)

    _orphans(rng, len(ELEMENTS) + 1)
    nuke.nodes.BackdropNode(
        label="elements",
        xpos=-40,
        ypos=-60,
        bdwidth=len(ELEMENTS) * COLUMN_WIDTH,
        bdheight=10 * ROW_HEIGHT,
    )


if __name__ == "__main__":
    build()
    if len(sys.argv) > 1:
        nuke.scriptSaveAs(sys.argv[1], overwrite=1)
