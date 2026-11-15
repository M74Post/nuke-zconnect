"""Connect Nuke nodes by fuzzy search.

https://github.com/sisoe24/nuke-zconnect
Copyright (c) 2026 virgilsisoe. MIT License, see LICENSE.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nuke

__version__ = "0.1.0"

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

MAX_ROWS = 15
SKIP_CLASSES = frozenset({"Viewer"})
# Graph decoration: never an input, but a landmark worth jumping to.
NO_OUTPUT_CLASSES = frozenset({"BackdropNode", "StickyNote"})
SEPARATORS = frozenset("_-. /")

# Input labels for nodes whose arrows are not simply "input" and "mask".
INPUT_NAMES = {
    "Merge2": ["B", "A"],
    "Copy": ["B", "A"],
    "Keymix": ["B", "A"],
}

# Nodes that usually feed a mask input rank higher when the mask socket is picked.
MASK_CLASSES = frozenset({"Roto", "RotoPaint", "Keyer", "Radial", "Rectangle", "Ramp"})
CLASS_BOOST = 5.0


# === FUZZY MATCH === #


def fuzzy_score(query: str, text: str) -> float | None:
    """Return a match score, or None when `query` is not a subsequence of `text`."""
    if not query:
        return 0.0

    query = query.lower()
    original = text
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
        # Word start: after a separator, or a camelCase hump like the C in ColorCorrect.
        if (
            index == 0
            or text[index - 1] in SEPARATORS
            or (original[index].isupper() and original[index - 1].islower())
        ):
            score += 5.0

        previous = index
        position = index + 1

    # Prefer short texts: "plate" beats "plate_denoise_final" for the same query.
    return score - len(text) * 0.01


# === FRECENCY === #


def age_weight(seconds: float) -> float:
    """Weight a use by its age: recent uses count more."""
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
        """Return use count weighted by how long ago `key` was last used."""
        if key not in self.entries:
            return 0.0
        count, last_used = self.entries[key]
        return count * age_weight(now - last_used)

    def add(self, key: tuple[str, str], now: float) -> None:
        """Count one more use of `key` at time `now`."""
        count, _ = self.entries.get(key, (0, 0.0))
        self.entries[key] = (count + 1, now)


# TODO: scores reset when Nuke closes, and renamed nodes lose theirs.
FRECENCY = Frecency()


# === RANKING === #


@dataclass
class Candidate:
    """A node that can become an input, with the texts the query matches against."""

    node: Any
    key: tuple[str, str]
    name: str
    cls: str
    extras: list[str]
    distance: float

    # === PROPERTIES === #

    @property
    def texts(self) -> list[str]:
        """Return every text the query can match: name, class, label, file name."""
        return [self.name, self.cls, *self.extras]

    @property
    def columns(self) -> tuple[str, str, str]:
        """Return the table cells: name, class, then label and file joined."""
        return self.name, self.cls, "  ·  ".join(self.extras)


def _best_match(query: str, candidate: Candidate) -> float | None:
    scores = [fuzzy_score(query, text) for text in candidate.texts]
    matches = [score for score in scores if score is not None]
    return max(matches) if matches else None


def rank(
    candidates: list[Candidate],
    query: str,
    *,
    frecency: Frecency,
    now: float,
    boost_classes: frozenset[str] = frozenset(),
) -> list[Candidate]:
    """Filter candidates by `query` and sort best first.

    Match quality and frecency add up, so a strong match on an unused node
    beats a weak match on a used one. Nodes of `boost_classes` get a fixed bonus
    (mask sources for the mask socket). Distance in the DAG breaks ties.
    """
    scored = []
    for candidate in candidates:
        match = _best_match(query, candidate)
        if match is None:
            continue

        total = match + 2.0 * math.log1p(frecency.score(candidate.key, now))
        if candidate.cls in boost_classes:
            total += CLASS_BOOST
        scored.append((total, candidate))

    ranked = sorted(scored, key=lambda item: (-item[0], item[1].distance))
    return [candidate for _, candidate in ranked]


# === NUKE GRAPH === #


def _downstream(node: Any) -> set[str]:
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


def _extras(node: Any) -> list[str]:
    """Return the label's first line and the file name, when the node has them."""
    extras = []

    label = node["label"].value().strip() if node.knob("label") else ""
    if label:
        extras.append(label.splitlines()[0])

    # You remember a Read by its file, not by Read12.
    if node.knob("file") and node["file"].value():
        extras.append(Path(node["file"].value()).name)

    return extras


def _is_candidate(node: Any, *, target: Any | None, downstream: set[str]) -> bool:
    if node.Class() in SKIP_CLASSES:
        return False
    if target is not None and node.Class() in NO_OUTPUT_CLASSES:
        return False
    if target is not None and node.fullName() == target.fullName():
        return False
    if node.fullName() in downstream:
        return False
    if node.Class() == "Dot" and not node["label"].value().strip():
        return False
    return True


def collect_candidates(target: Any | None) -> list[Candidate]:
    """Return every node that can become an input of `target`.

    Without a target (jump mode), return every node, nearest to the view center first.
    """
    script = nuke.root().name()
    if target is None:
        downstream: set[str] = set()
        origin = tuple(nuke.center())
    else:
        downstream = _downstream(target)
        origin = (target.xpos(), target.ypos())

    candidates = []
    for node in nuke.allNodes():
        if not _is_candidate(node, target=target, downstream=downstream):
            continue

        distance = math.hypot(node.xpos() - origin[0], node.ypos() - origin[1])
        candidates.append(
            Candidate(
                node=node,
                key=(script, node.fullName()),
                name=node.name(),
                cls=node.Class(),
                extras=_extras(node),
                distance=distance,
            )
        )
    return candidates


def input_slot(target: Any) -> int:
    """Return the first free input that is not the mask: the socket offered by default.

    Falls back to input 0 when all are taken.
    """
    optional = target.optionalInput()
    for index in range(target.maxInputs()):
        if index != optional and target.input(index) is None:
            return index
    return 0


def sockets(target: Any) -> list[int]:
    """Return the inputs to show as tabs: connected ones, the first free one, and the mask.

    Merge has thousands of A inputs, so this stops at the mask instead of listing them.
    """
    count = max(target.inputs(), input_slot(target) + 1, target.optionalInput() + 1)
    return list(range(min(target.maxInputs(), count)))


def socket_name(target: Any, slot: int) -> str:
    """Return the label Nuke draws on the input arrow."""
    if slot == target.optionalInput():
        return "mask"

    # Nuke's Python API can't read arrow labels, hence the table.
    names = INPUT_NAMES.get(target.Class())
    if names is None:
        return "input" if slot == 0 else str(slot)
    if slot < len(names):
        return names[slot]
    # Merge-like nodes: index 3 is A2, index 4 is A3, and so on (index 2 is the mask).
    return f"{names[-1]}{slot - 1}"


def connect(target: Any, candidate: Candidate, *, slot: int) -> None:
    """Plug `candidate` into input `slot` of `target` as one undo step and count the use."""
    nuke.Undo.begin("zconnect")
    try:
        target.setInput(slot, candidate.node)
    finally:
        nuke.Undo.end()

    FRECENCY.add(candidate.key, time.time())


def frame(node: Any) -> None:
    """Select only `node` and fit the Node Graph view to it."""
    for selected in nuke.selectedNodes():
        selected.setSelected(False)
    node.setSelected(True)
    nuke.zoomToFitSelected()


def jump_to(candidate: Candidate, *, open_properties: bool = False) -> None:
    """Frame `candidate` and count the use, so nodes you jump to rank higher next time."""
    frame(candidate.node)
    if open_properties:
        nuke.show(candidate.node)
    FRECENCY.add(candidate.key, time.time())


# === PLACEMENT === #


def dag_to_widget(
    point: tuple[float, float],
    *,
    center: tuple[float, float],
    zoom: float,
    size: tuple[int, int],
) -> tuple[int, int]:
    """Convert a DAG coordinate to pixels inside the Node Graph widget.

    The widget shows `center` in its middle, scaled by `zoom`.
    """
    x = size[0] / 2 + (point[0] - center[0]) * zoom
    y = size[1] / 2 + (point[1] - center[1]) * zoom
    return round(x), round(y)


def clamp_to_screen(
    position: tuple[int, int],
    *,
    size: tuple[int, int],
    screen: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Move a rectangle of `size` at `position` so it stays inside `screen`.

    `screen` is (x, y, width, height).
    """
    left, top, width, height = screen
    x = min(max(position[0], left), left + width - size[0])
    y = min(max(position[1], top), top + height - size[1])
    return x, y


def _place(popup: QtWidgets.QWidget, target: Any | None) -> None:
    """Move `popup` under `target` in the focused Node Graph, or to the cursor in jump mode."""
    popup.adjustSize()
    position = QtGui.QCursor.pos()
    # Qt sometimes reports no focus widget when the hotkey fires; then open at the cursor.
    dag = QtWidgets.QApplication.focusWidget()
    if target is not None and dag is not None:
        below_node = (target.xpos() + target.screenWidth() / 2, target.ypos() + target.screenHeight())
        x, y = dag_to_widget(
            below_node,
            center=tuple(nuke.center()),
            zoom=nuke.zoom(),
            size=(dag.width(), dag.height()),
        )
        position = dag.mapToGlobal(QtCore.QPoint(x, y + 8))

    area = QtGui.QGuiApplication.screenAt(position).availableGeometry()
    x, y = clamp_to_screen(
        (position.x(), position.y()),
        size=(popup.width(), popup.height()),
        screen=(area.x(), area.y(), area.width(), area.height()),
    )
    popup.move(x, y)


# === UI === #


class Popup(QtWidgets.QFrame):
    """Search field, input tabs and result table.

    With a target node, Enter connects the pick to it. Without one, Enter jumps to the pick.
    """

    def __init__(
        self,
        target: Any | None,
        *,
        candidates: list[Candidate],
        slots: list[int],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent, QtCore.Qt.Popup)

        self._target = target
        self._candidates = candidates
        self._slots = slots

        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setMinimumWidth(640)

        self._slot = input_slot(target) if target is not None else 0
        self._matches: list[Candidate] = []
        self._saved_view: tuple[float, list[float]] | None = None
        self._saved_selection: list[Any] = []

        self._build_ui()
        self._refresh()

    # === PRIVATE === #

    def _build_ui(self) -> None:
        self._tabs = QtWidgets.QTabBar()
        self._tabs.setFocusPolicy(QtCore.Qt.NoFocus)
        self._tabs.setDrawBase(False)
        for slot in self._slots:
            self._tabs.addTab(socket_name(self._target, slot))
        self._tabs.setVisible(len(self._slots) > 1)
        if self._slots:
            # Set before connecting the signal, so building the tabs does not refresh twice.
            self._tabs.setCurrentIndex(self._slots.index(self._slot))
        self._tabs.currentChanged.connect(self._on_tab_changed)

        if self._target is None:
            placeholder = "jump to node"
        else:
            placeholder = f"connect to {self._target.name()}"
        self._query = QtWidgets.QLineEdit()
        self._query.setPlaceholderText(placeholder)
        self._query.textChanged.connect(self._on_query_changed)
        self._query.installEventFilter(self)
        self.setFocusProxy(self._query)

        self._table = QtWidgets.QTreeWidget()
        self._table.setHeaderLabels(["Name", "Class", "Label / File"])
        self._table.setRootIsDecorated(False)
        self._table.setUniformRowHeights(True)
        self._table.setAllColumnsShowFocus(True)
        self._table.setFocusPolicy(QtCore.Qt.NoFocus)
        self._table.itemClicked.connect(self._on_item_clicked)

        self._hints = QtWidgets.QLabel(self._hint_text())
        self._hints.setStyleSheet("color: gray;")
        # Wrap so the hints follow the table's width instead of widening the popup.
        self._hints.setWordWrap(True)
        font = self._hints.font()
        font.setPointSizeF(font.pointSizeF() * 0.9)
        self._hints.setFont(font)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._tabs)
        layout.addWidget(self._query)
        layout.addWidget(self._table)
        layout.addWidget(self._hints)
        self.setLayout(layout)

    def _hint_text(self) -> str:
        if self._target is None:
            hints = ["Enter: jump", "Shift+Enter: jump + panel"]
        else:
            hints = ["Enter: connect"]
        hints.append("Tab/↑↓: move")
        if len(self._slots) > 1:
            hints.append("Alt+A: input")
        hints += ["Alt+F: frame", "Alt+P: properties", "Esc: close"]
        return "  ·  ".join(hints)

    def _current_row(self) -> int:
        return self._table.indexOfTopLevelItem(self._table.currentItem())

    def _set_row(self, row: int) -> None:
        self._table.setCurrentItem(self._table.topLevelItem(row))

    def _refresh(self) -> None:
        is_mask = self._target is not None and self._slot == self._target.optionalInput()
        boost = MASK_CLASSES if is_mask else frozenset()
        ranked = rank(
            self._candidates,
            self._query.text(),
            frecency=FRECENCY,
            now=time.time(),
            boost_classes=boost,
        )
        self._matches = ranked[:MAX_ROWS]

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

    def _focus(self) -> None:
        """Frame the highlighted node; the view and selection come back on close."""
        row = self._current_row()
        if not 0 <= row < len(self._matches):
            return

        if self._saved_view is None:
            self._saved_view = (nuke.zoom(), nuke.center())
            self._saved_selection = nuke.selectedNodes()

        frame(self._matches[row].node)

    def _accept(self, *, open_properties: bool = False) -> None:
        row = self._current_row()
        # After Alt+F, stay on the picked node.
        previewed = self._saved_view is not None
        # Closing first restores any Alt+F preview, so the jump below starts from the real view.
        self.close()
        if not 0 <= row < len(self._matches):
            return

        if self._target is None:
            jump_to(self._matches[row], open_properties=open_properties)
        else:
            connect(self._target, self._matches[row], slot=self._slot)
            if previewed:
                frame(self._matches[row].node)

    def _show_properties(self) -> None:
        """Open the highlighted node's properties in a floating panel, keeping the search open."""
        row = self._current_row()
        if not 0 <= row < len(self._matches):
            return

        nuke.show(self._matches[row].node, True)
        # The new panel takes focus; take it back so typing keeps going to the search.
        self.activateWindow()
        self._query.setFocus()

    def _next_socket(self) -> None:
        if len(self._slots) > 1:
            self._tabs.setCurrentIndex((self._tabs.currentIndex() + 1) % len(self._slots))

    def _alt_key(self, key: int) -> bool:
        # Compare key codes, not event.text(): on macOS Option+A types "å".
        if key == QtCore.Qt.Key_F:
            self._focus()
            return True
        if key == QtCore.Qt.Key_A:
            self._next_socket()
            return True
        if key == QtCore.Qt.Key_P:
            self._show_properties()
            return True
        return False

    # === SLOTS === #

    @QtCore.Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        self._slot = self._slots[index]
        self._refresh()

    @QtCore.Slot(str)
    def _on_query_changed(self, _text: str) -> None:
        self._refresh()

    @QtCore.Slot()
    def _on_item_clicked(self) -> None:
        self._accept()

    # === PUBLIC === #

    def hideEvent(self, event: Any) -> None:
        """Restore the view and selection after an Alt+F preview."""
        if self._saved_view is not None:
            for node in nuke.selectedNodes():
                node.setSelected(False)
            for node in self._saved_selection:
                node.setSelected(True)
            nuke.zoom(*self._saved_view)
        super().hideEvent(event)

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """Handle the popup keys typed in the search field."""
        if event.type() != QtCore.QEvent.KeyPress:
            return False

        key = event.key()
        if event.modifiers() & QtCore.Qt.AltModifier:
            return self._alt_key(key)
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._accept(open_properties=bool(event.modifiers() & QtCore.Qt.ShiftModifier))
            return True
        if key in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Down):
            self._move(1)
            return True
        if key in (QtCore.Qt.Key_Backtab, QtCore.Qt.Key_Up):
            self._move(-1)
            return True
        return False


# Keeps the open popup alive: without this reference the jump popup closes at once.
_popup: Popup | None = None


def _open(target: Any | None, *, slots: list[int]) -> None:
    global _popup

    _popup = popup = Popup(
        target,
        candidates=collect_candidates(target),
        slots=slots,
        parent=QtWidgets.QApplication.activeWindow(),
    )
    _place(popup, target)
    popup.show()
    popup.setFocus()


def jump() -> None:
    """Open the popup to select and frame any node. Bind this to the jump hotkey."""
    _open(None, slots=[])


def show() -> None:
    """Open the popup to connect an input of the selected node. Bind this to the main hotkey."""
    try:
        target = nuke.selectedNode()
    except ValueError:
        nuke.message("zconnect: select a node first.")
        return

    if target.maxInputs() == 0:
        nuke.message(f"zconnect: {target.name()} has no inputs.")
        return

    _open(target, slots=sockets(target))
