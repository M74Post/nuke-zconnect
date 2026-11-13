"""zconnect: connect the selected node to another node by fuzzy search, ranked by frecency.

Select a node, press the hotkey, type a few letters, press Enter.
The picked node becomes an input of the selected node.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)

MAX_ROWS = 15
SKIP_CLASSES = {"Viewer", "BackdropNode", "StickyNote", "Root"}
SEPARATORS = set("_-. /")


# === FUZZY MATCH === #


def fuzzy_score(query: str, text: str) -> float | None:
    """Return a match score, or None when `query` is not a subsequence of `text`."""
    if not query:
        return 0.0

    query = query.lower()
    text = text.lower()

    score = 0.0
    previous = -2
    position = 0
    for char in query:
        index = text.find(char, position)
        if index == -1:
            return None

        score += 1.0
        if index == previous + 1:
            score += 3.0
        if index == 0 or text[index - 1] in SEPARATORS:
            score += 5.0

        previous = index
        position = index + 1

    # Prefer short texts: "plate" beats "plate_denoise_final" for the same query.
    return score - len(text) * 0.01


# === FRECENCY === #


def age_weight(seconds: float) -> float:
    """Return the zoxide age multiplier for an entry last used `seconds` ago."""
    if seconds < 3600:
        return 4.0
    if seconds < 86400:
        return 2.0
    if seconds < 604800:
        return 0.5
    return 0.25


@dataclass
class Frecency:
    """Session-only use counts, keyed by (script name, node full name)."""

    entries: dict[tuple[str, str], tuple[int, float]] = field(default_factory=dict)

    def score(self, key: tuple[str, str], now: float) -> float:
        if key not in self.entries:
            return 0.0
        count, last_used = self.entries[key]
        return count * age_weight(now - last_used)

    def add(self, key: tuple[str, str], now: float) -> None:
        count, _ = self.entries.get(key, (0, now))
        self.entries[key] = (count + 1, now)


# shortcut: renamed nodes lose their score and nothing persists after Nuke closes;
# key by a stored node id and save to JSON if that starts to hurt.
FRECENCY = Frecency()


# === RANKING === #


@dataclass
class Candidate:
    node: Any
    key: tuple[str, str]
    texts: list[str]
    distance: float

    @property
    def columns(self) -> tuple[str, str, str]:
        """Return the table cells: name, class, then label and file joined."""
        return self.texts[0], self.texts[1], "  ·  ".join(self.texts[2:])


def rank(candidates: list[Candidate], query: str, frecency: Frecency, now: float) -> list[Candidate]:
    """Filter candidates by `query` and sort best first.

    Match quality and frecency add up, so a strong match on an unused node
    beats a weak match on a used one. Distance in the DAG breaks ties.
    """
    scored = []
    for candidate in candidates:
        matches = [s for s in (fuzzy_score(query, text) for text in candidate.texts) if s is not None]
        if not matches:
            continue
        total = max(matches) + 2.0 * math.log1p(frecency.score(candidate.key, now))
        scored.append((-total, candidate.distance, candidate))

    scored.sort(key=lambda item: (item[0], item[1]))
    return [candidate for _, _, candidate in scored]


# === NUKE === #


def _downstream(nuke: Any, node: Any) -> set[str]:
    """Return full names of every node fed by `node`. Connecting one of them would make a cycle."""
    seen: set[str] = set()
    stack = [node]
    while stack:
        current = stack.pop()
        for dependent in current.dependent(nuke.INPUTS | nuke.HIDDEN_INPUTS, forceEvaluate=False):
            name = dependent.fullName()
            if name not in seen:
                seen.add(name)
                stack.append(dependent)
    return seen


def _texts(node: Any) -> list[str]:
    texts = [node.name(), node.Class()]

    label = node["label"].value().strip() if node.knob("label") else ""
    if label:
        texts.append(label.splitlines()[0])

    # Read nodes are named Read1..ReadN; the file name is what the artist remembers.
    if node.knob("file") and node["file"].value():
        texts.append(os.path.basename(node["file"].value()))

    return texts


def _is_candidate(node: Any, target: Any, downstream: set[str]) -> bool:
    if node.Class() in SKIP_CLASSES:
        return False
    if node.fullName() == target.fullName() or node.fullName() in downstream:
        return False
    if node.Class() == "Dot" and not node["label"].value().strip():
        return False
    return True


def collect_candidates(nuke: Any, target: Any) -> list[Candidate]:
    """Return every node in the current graph that can become an input of `target`."""
    script = nuke.root().name()
    downstream = _downstream(nuke, target)

    candidates = []
    for node in nuke.allNodes():
        if not _is_candidate(node, target, downstream):
            continue
        candidates.append(
            Candidate(
                node=node,
                key=(script, node.fullName()),
                texts=_texts(node),
                distance=math.hypot(node.xpos() - target.xpos(), node.ypos() - target.ypos()),
            )
        )
    return candidates


def input_slot(target: Any, mask: bool) -> int:
    """Return the input index to fill: the mask input, or the first free non-mask input.

    When every input is taken, input 0 is replaced: the artist picked a node on purpose.
    """
    optional = target.optionalInput()
    if mask:
        return optional

    for index in range(target.maxInputs()):
        if index != optional and target.input(index) is None:
            return index
    return 0


def sockets(target: Any) -> list[int]:
    """Return the input indexes Alt+A cycles through, in index order.

    Covers every connected input, the first free one, and everything up to the mask,
    so an empty Merge offers B, A, mask. Merge has thousands of A inputs; the range
    stops there instead of listing them all.
    """
    count = max(target.inputs(), input_slot(target, mask=False) + 1, target.optionalInput() + 1)
    return list(range(min(target.maxInputs(), count)))


def socket_name(target: Any, slot: int) -> str:
    label = target.inputLabel(slot) if hasattr(target, "inputLabel") else ""
    return label or str(slot)


def connect(nuke: Any, target: Any, source: Any, slot: int) -> None:
    nuke.Undo.begin("zconnect")
    try:
        target.setInput(slot, source)
    finally:
        nuke.Undo.end()

    FRECENCY.add((nuke.root().name(), source.fullName()), time.time())


# === UI === #


def _qt() -> tuple[Any, Any, Any]:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


_popup: Any = None


def show(mask: bool = False) -> None:
    """Open the search popup for the selected node. Bind this to the hotkey.

    Inside the popup: type to filter, Tab/Up/Down to move, Enter to connect,
    Alt+F to pan the DAG to the highlighted node, Alt+A to cycle the input socket.
    """
    global _popup

    import nuke

    try:
        target = nuke.selectedNode()
    except ValueError:
        nuke.message("zconnect: select a node first.")
        return

    if mask and target.optionalInput() >= target.maxInputs():
        nuke.message(f"zconnect: {target.name()} has no mask input.")
        return

    QtCore, QtGui, QtWidgets = _qt()
    candidates = collect_candidates(nuke, target)

    slots = sockets(target)
    first_slot = input_slot(target, mask)

    class Popup(QtWidgets.QFrame):
        def __init__(self) -> None:
            super().__init__(QtWidgets.QApplication.activeWindow(), QtCore.Qt.Popup)

            self._matches: list[Candidate] = []
            self._slot = first_slot
            self._saved_view: tuple[float, list[float]] | None = None
            self._saved_selection: list[Any] = []

            self.setMinimumWidth(640)

            self._socket = QtWidgets.QLabel()

            self._query = QtWidgets.QLineEdit()
            self._query.textChanged.connect(self._refresh)
            self._query.installEventFilter(self)

            self._table = QtWidgets.QTreeWidget()
            self._table.setHeaderLabels(["Name", "Class", "Label / File"])
            self._table.setRootIsDecorated(False)
            self._table.setUniformRowHeights(True)
            self._table.setAllColumnsShowFocus(True)
            self._table.setFocusPolicy(QtCore.Qt.NoFocus)
            self._table.itemClicked.connect(lambda *_: self._accept())

            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(4, 4, 4, 4)
            layout.addWidget(self._socket)
            layout.addWidget(self._query)
            layout.addWidget(self._table)
            self.setLayout(layout)

            self._show_socket()
            self._refresh("")

        def hideEvent(self, event: Any) -> None:
            # Put view and selection back where the artist was working, whatever closed the popup.
            if self._saved_view is not None:
                for node in nuke.selectedNodes():
                    node.setSelected(False)
                for node in self._saved_selection:
                    node.setSelected(True)
                nuke.zoom(*self._saved_view)
            super().hideEvent(event)

        def _current_row(self) -> int:
            return self._table.indexOfTopLevelItem(self._table.currentItem())

        def _set_row(self, row: int) -> None:
            self._table.setCurrentItem(self._table.topLevelItem(row))

        def _show_socket(self) -> None:
            self._socket.setText(
                f"{target.name()} \u2190 {socket_name(target, self._slot)}"
                "      Alt+A socket   Alt+F focus"
            )

        def _refresh(self, query: str) -> None:
            self._matches = rank(candidates, query, FRECENCY, time.time())[:MAX_ROWS]
            self._table.clear()
            for candidate in self._matches:
                self._table.addTopLevelItem(QtWidgets.QTreeWidgetItem(list(candidate.columns)))
            for column in (0, 1):
                self._table.resizeColumnToContents(column)
            if self._matches:
                self._set_row(0)

        def _move(self, step: int) -> None:
            if self._matches:
                self._set_row((self._current_row() + step) % len(self._matches))

        def _cycle_socket(self) -> None:
            self._slot = slots[(slots.index(self._slot) + 1) % len(slots)]
            self._show_socket()

        def _focus(self) -> None:
            row = self._current_row()
            if not 0 <= row < len(self._matches):
                return
            if self._saved_view is None:
                self._saved_view = (nuke.zoom(), nuke.center())
                self._saved_selection = nuke.selectedNodes()

            for node in nuke.selectedNodes():
                node.setSelected(False)
            self._matches[row].node.setSelected(True)
            nuke.zoomToFitSelected()

        def _accept(self) -> None:
            row = self._current_row()
            self.close()
            if 0 <= row < len(self._matches):
                connect(nuke, target, self._matches[row].node, self._slot)

        def eventFilter(self, watched: Any, event: Any) -> bool:
            if event.type() != QtCore.QEvent.KeyPress:
                return False

            key = event.key()
            if event.modifiers() & QtCore.Qt.AltModifier:
                if key == QtCore.Qt.Key_A:
                    self._cycle_socket()
                    return True
                if key == QtCore.Qt.Key_F:
                    self._focus()
                    return True
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self._accept()
                return True
            if key in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Down):
                self._move(1)
                return True
            if key in (QtCore.Qt.Key_Backtab, QtCore.Qt.Key_Up):
                self._move(-1)
                return True
            return False

    _popup = Popup()
    _popup.move(QtGui.QCursor.pos())
    _popup.show()
    _popup._query.setFocus()
