from __future__ import annotations

from typing import Any

from zconnect import main
from zconnect.main import (
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


def _candidate(name: str, *texts: str, distance: float = 0.0) -> Candidate:
    return Candidate(node=name, key=("s.nk", name), texts=[name, "Node", *texts], distance=distance)


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


def test_rank_matches_read_file_basename() -> None:
    """Read nodes are found by their file name, not only by ReadN."""
    bg = _candidate("Read4", "bg_plate_v003.exr")
    fg = _candidate("Read7", "fg_plate_v003.exr")
    assert rank([bg, fg], "fg", Frecency(), NOW) == [fg]


def test_rank_frecency_breaks_equal_matches() -> None:
    """With equal match quality, the more recently used node ranks first."""
    first = _candidate("plate1")
    second = _candidate("plate2")
    frecency = Frecency()
    frecency.add(second.key, NOW)
    assert rank([first, second], "plate", frecency, NOW)[0] is second


def test_rank_strong_match_beats_one_use() -> None:
    """One past use does not lift a weak match above a strong one."""
    strong = _candidate("plate")
    weak = _candidate("comp_out")
    frecency = Frecency()
    frecency.add(weak.key, NOW)
    assert rank([strong, weak], "p", frecency, NOW)[0] is strong


def test_rank_empty_query_uses_distance() -> None:
    """With no query and no history, the nearest node ranks first."""
    far = _candidate("far", distance=500)
    near = _candidate("near", distance=50)
    assert rank([far, near], "", Frecency(), NOW) == [near, far]


class FakeNode:
    def __init__(self, inputs: list[Any], optional: int, cls: str = "Grade") -> None:
        self._inputs = inputs
        self._optional = optional
        self._cls = cls

    def Class(self) -> str:
        return self._cls

    def optionalInput(self) -> int:
        return self._optional

    def maxInputs(self) -> int:
        return len(self._inputs)

    def input(self, index: int) -> Any:
        return self._inputs[index]

    def inputs(self) -> int:
        connected = [i for i, node in enumerate(self._inputs) if node is not None]
        return connected[-1] + 1 if connected else 0


def test_sockets_merge_offers_one_free_a_and_mask() -> None:
    """A Merge with only B connected cycles B, A, mask, not every possible A input."""
    merge = FakeNode(["B", None, None, None, None], optional=2)
    assert sockets(merge) == [0, 1, 2]


def test_sockets_empty_merge_includes_a() -> None:
    """An unconnected Merge offers B, A and mask before anything is connected."""
    assert sockets(FakeNode([None] * 5, optional=2)) == [0, 1, 2]


def test_sockets_merge_with_b_and_a_offers_next_a() -> None:
    """With B and A taken, the next free A input after the mask is offered."""
    assert sockets(FakeNode(["B", "A", None, None, None], optional=2)) == [0, 1, 2, 3]


def test_sockets_unconnected_node() -> None:
    """A node with nothing connected offers input 0 and its mask."""
    assert sockets(FakeNode([None, None], optional=1)) == [0, 1]


def test_sockets_without_mask() -> None:
    """A node without an optional input offers no mask socket."""
    assert sockets(FakeNode([None], optional=1)) == [0]


def test_input_slot_skips_mask_and_taken_inputs() -> None:
    """Merge with B taken defaults to A, not the mask."""
    assert input_slot(FakeNode(["B", None, None], optional=2)) == 1


def test_input_slot_all_taken_offers_first() -> None:
    """When every input is taken, input 0 is the default."""
    assert input_slot(FakeNode(["src", "mask"], optional=1)) == 0


def test_socket_name_merge() -> None:
    """Merge sockets read B, A, mask, A2 like the arrows Nuke draws."""
    merge = FakeNode([None] * 5, optional=2, cls="Merge2")
    assert [socket_name(merge, slot) for slot in range(4)] == ["B", "A", "mask", "A2"]


def test_socket_name_unknown_class() -> None:
    """A node missing from the table gets "input" and "mask"."""
    grade = FakeNode([None, None], optional=1)
    assert [socket_name(grade, slot) for slot in range(2)] == ["input", "mask"]


def test_rank_boost_lifts_mask_sources() -> None:
    """With the mask socket picked, a Roto ranks above a closer Grade."""
    roto = Candidate(node="Roto1", key=("s.nk", "Roto1"), texts=["Roto1", "Roto"], distance=500)
    grade = Candidate(node="Grade1", key=("s.nk", "Grade1"), texts=["Grade1", "Grade"], distance=10)
    assert rank([grade, roto], "", Frecency(), NOW, MASK_CLASSES)[0] is roto


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

    class FakeNuke:
        INPUTS = 1
        HIDDEN_INPUTS = 2

    write = Node("Write1", [])
    merge = Node("Merge1", [write])
    grade = Node("Grade1", [merge])
    assert main._downstream(FakeNuke, grade) == {"Merge1", "Write1"}


def test_dag_to_widget_center_maps_to_middle() -> None:
    """The DAG point at the view center lands in the middle of the widget."""
    assert dag_to_widget((100, 200), (100, 200), 1.0, (800, 600)) == (400, 300)


def test_dag_to_widget_scales_offset_by_zoom() -> None:
    """Offsets from the center are scaled by the zoom level."""
    assert dag_to_widget((150, 180), (100, 200), 2.0, (800, 600)) == (500, 260)


def test_clamp_to_screen_keeps_inside() -> None:
    """A popup that would cross the bottom-right corner is pulled back on screen."""
    assert clamp_to_screen((1800, 1000), (640, 300), (0, 0, 1920, 1080)) == (1280, 780)


def test_clamp_to_screen_leaves_fitting_popup() -> None:
    """A popup already on screen does not move."""
    assert clamp_to_screen((100, 100), (640, 300), (0, 0, 1920, 1080)) == (100, 100)
