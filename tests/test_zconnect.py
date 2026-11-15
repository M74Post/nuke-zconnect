from __future__ import annotations

from typing import Any

import pytest

import zconnect
from zconnect import (
    MASK_CLASSES,
    Candidate,
    Frecency,
    clamp_to_screen,
    dag_to_widget,
    fuzzy_score,
    input_slot,
    rank,
    socket_name,
    sockets,
)

NOW = 1_000_000.0


# === FAKES === #


def _candidate(name: str, *extras: str, cls: str = "Node", distance: float = 0.0) -> Candidate:
    return Candidate(
        node=name,
        key=("s.nk", name),
        name=name,
        cls=cls,
        extras=list(extras),
        distance=distance,
    )


class FakeKnob:
    def __init__(self, value: str) -> None:
        self._value = value

    def value(self) -> str:
        return self._value


class FakeNode:
    def __init__(
        self,
        inputs: list[Any] | None = None,
        *,
        optional: int = -1,
        cls: str = "Grade",
        name: str = "Node1",
        knobs: dict[str, str] | None = None,
    ) -> None:
        self._inputs = inputs or []
        self._optional = optional
        self._cls = cls
        self._name = name
        self._knobs = knobs or {}

    def __getitem__(self, knob: str) -> FakeKnob:
        return FakeKnob(self._knobs[knob])

    def Class(self) -> str:
        return self._cls

    def name(self) -> str:
        return self._name

    def fullName(self) -> str:
        return self._name

    def knob(self, knob: str) -> bool:
        return knob in self._knobs

    def optionalInput(self) -> int:
        return self._optional

    def maxInputs(self) -> int:
        return len(self._inputs)

    def input(self, index: int) -> Any:
        return self._inputs[index]

    def inputs(self) -> int:
        connected = [i for i, node in enumerate(self._inputs) if node is not None]
        return connected[-1] + 1 if connected else 0


# === FUZZY AND RANKING === #


def test_columns_join_label_and_file() -> None:
    """The third table column holds label and file name together."""
    candidate = _candidate("Read4", "bg plate", "bg_plate_v003.exr")
    assert candidate.columns == ("Read4", "Node", "bg plate  ·  bg_plate_v003.exr")


def test_fuzzy_rejects_non_subsequence() -> None:
    """A query that is not a subsequence of the text does not match."""
    assert fuzzy_score("xz", "plate") is None


def test_fuzzy_prefers_word_start() -> None:
    """A match at a word start scores higher than one in the middle of a word."""
    assert fuzzy_score("p", "bg_plate") > fuzzy_score("p", "comp")


def test_fuzzy_treats_camel_case_hump_as_word_start() -> None:
    """The second C in ColorCorrect starts a word, so "cc" beats a shorter mid-word match."""
    assert fuzzy_score("cc", "ColorCorrect") > fuzzy_score("cc", "Concat")


def test_rank_matches_read_file_basename() -> None:
    """Read nodes are found by their file name, not only by ReadN."""
    bg = _candidate("Read4", "bg_plate_v003.exr")
    fg = _candidate("Read7", "fg_plate_v003.exr")
    assert rank([bg, fg], "fg", frecency=Frecency(), now=NOW) == [fg]


def test_rank_frecency_breaks_equal_matches() -> None:
    """With equal match quality, the more recently used node ranks first."""
    first = _candidate("plate1")
    second = _candidate("plate2")
    frecency = Frecency()
    frecency.add(second.key, NOW)
    assert rank([first, second], "plate", frecency=frecency, now=NOW)[0] is second


def test_rank_strong_match_beats_one_use() -> None:
    """One past use does not lift a weak match above a strong one."""
    strong = _candidate("plate")
    weak = _candidate("comp_out")
    frecency = Frecency()
    frecency.add(weak.key, NOW)
    assert rank([strong, weak], "p", frecency=frecency, now=NOW)[0] is strong


def test_rank_empty_query_uses_distance() -> None:
    """With no query and no history, the nearest node ranks first."""
    far = _candidate("far", distance=500)
    near = _candidate("near", distance=50)
    assert rank([far, near], "", frecency=Frecency(), now=NOW) == [near, far]


def test_rank_boost_lifts_mask_sources() -> None:
    """With the mask socket picked, a Roto ranks above a closer Grade."""
    roto = _candidate("Roto1", cls="Roto", distance=500)
    grade = _candidate("Grade1", cls="Grade", distance=10)
    ranked = rank([grade, roto], "", frecency=Frecency(), now=NOW, boost_classes=MASK_CLASSES)
    assert ranked[0] is roto


# === CANDIDATES === #


def test_extras_take_label_first_line_and_file_name() -> None:
    """Extras hold the label's first line and the file name without its folder."""
    read = FakeNode(knobs={"label": " bg plate\nv003 ", "file": "/show/plates/bg_v003.%04d.exr"})
    assert zconnect._extras(read) == ["bg plate", "bg_v003.%04d.exr"]


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (FakeNode(cls="Grade", name="Grade1"), True),
        (FakeNode(cls="Viewer", name="Viewer1"), False),
        (FakeNode(cls="Dot", name="Dot1", knobs={"label": ""}), False),
        (FakeNode(cls="Dot", name="Dot2", knobs={"label": "bg"}), True),
        (FakeNode(cls="Grade", name="Target"), False),
        (FakeNode(cls="Grade", name="Write1"), False),
    ],
)
def test_is_candidate_filters_unusable_nodes(node: FakeNode, expected: bool) -> None:
    """Skips viewers, unlabelled Dots, the target itself and its downstream nodes."""
    target = FakeNode(name="Target")
    assert zconnect._is_candidate(node, target=target, downstream={"Write1"}) is expected


def test_is_candidate_without_target_keeps_every_node() -> None:
    """Jump mode has no target, so only skipped classes and unlabelled Dots drop out."""
    grade = FakeNode(cls="Grade", name="Grade1")
    viewer = FakeNode(cls="Viewer", name="Viewer1")
    assert zconnect._is_candidate(grade, target=None, downstream=set())
    assert not zconnect._is_candidate(viewer, target=None, downstream=set())


def test_downstream_follows_dependents() -> None:
    """Every node fed by the target is excluded, through several levels."""

    class Node:
        def __init__(self, name: str, dependents: list[Node]) -> None:
            self._name = name
            self._dependents = dependents

        def fullName(self) -> str:
            return self._name

        def dependent(self, _what: int, forceEvaluate: bool) -> list[Node]:
            return self._dependents

    write = Node("Write1", [])
    merge = Node("Merge1", [write])
    grade = Node("Grade1", [merge])
    assert zconnect._downstream(grade) == {"Merge1", "Write1"}


# === SOCKETS === #


@pytest.mark.parametrize(
    ("inputs", "optional", "expected"),
    [
        (["B", None, None, None, None], 2, [0, 1, 2]),
        ([None] * 5, 2, [0, 1, 2]),
        (["B", "A", None, None, None], 2, [0, 1, 2, 3]),
        ([None, None], 1, [0, 1]),
        ([None], 1, [0]),
    ],
    ids=["merge-b-only", "merge-empty", "merge-b-and-a", "unconnected", "no-mask"],
)
def test_sockets_offers_used_free_and_mask_inputs(
    inputs: list[Any],
    optional: int,
    expected: list[int],
) -> None:
    """Offers connected inputs, the first free one and the mask, not every A input."""
    assert sockets(FakeNode(inputs, optional=optional)) == expected


@pytest.mark.parametrize(
    ("inputs", "optional", "expected"),
    [
        (["B", None, None], 2, 1),
        (["src", "mask"], 1, 0),
    ],
    ids=["skips-mask-and-taken", "all-taken-offers-first"],
)
def test_input_slot_picks_first_free_non_mask(
    inputs: list[Any],
    optional: int,
    expected: int,
) -> None:
    """Defaults to the first free input that is not the mask, else input 0."""
    assert input_slot(FakeNode(inputs, optional=optional)) == expected


def test_socket_name_merge() -> None:
    """Merge sockets read B, A, mask, A2 like the arrows Nuke draws."""
    merge = FakeNode([None] * 5, optional=2, cls="Merge2")
    assert [socket_name(merge, slot) for slot in range(4)] == ["B", "A", "mask", "A2"]


def test_socket_name_unknown_class() -> None:
    """A node missing from the table gets "input" and "mask"."""
    grade = FakeNode([None, None], optional=1)
    assert [socket_name(grade, slot) for slot in range(2)] == ["input", "mask"]


# === PLACEMENT === #


def test_dag_to_widget_center_maps_to_middle() -> None:
    """The DAG point at the view center lands in the middle of the widget."""
    assert dag_to_widget((100, 200), center=(100, 200), zoom=1.0, size=(800, 600)) == (400, 300)


def test_dag_to_widget_scales_offset_by_zoom() -> None:
    """Offsets from the center are scaled by the zoom level."""
    assert dag_to_widget((150, 180), center=(100, 200), zoom=2.0, size=(800, 600)) == (500, 260)


def test_clamp_to_screen_keeps_inside() -> None:
    """A popup that would cross the bottom-right corner is pulled back on screen."""
    position = clamp_to_screen((1800, 1000), size=(640, 300), screen=(0, 0, 1920, 1080))
    assert position == (1280, 780)


def test_clamp_to_screen_leaves_fitting_popup() -> None:
    """A popup already on screen does not move."""
    position = clamp_to_screen((100, 100), size=(640, 300), screen=(0, 0, 1920, 1080))
    assert position == (100, 100)
