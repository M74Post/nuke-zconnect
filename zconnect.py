"""zconnect: connect the selected node to another node by fuzzy search, ranked by frecency.

Select a node, press the hotkey, type a few letters, press Enter.
The picked node becomes an input of the selected node.

Single file on purpose: copy it next to a menu.py and it works.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nuke

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

LOGGER = logging.getLogger(__name__)

MAX_ROWS = 15
SKIP_CLASSES = frozenset({"Viewer", "BackdropNode", "StickyNote", "Root"})
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
        """Return use count weighted by how long ago `key` was last used."""
        if key not in self.entries:
            return 0.0
        count, last_used = self.entries[key]
        return count * age_weight(now - last_used)

    def add(self, key: tuple[str, str], now: float) -> None:
        """Count one more use of `key` at time `now`."""
        count, _ = self.entries.get(key, (0, 0.0))
        self.entries[key] = (count + 1, now)


# shortcut: renamed nodes lose their score and nothing persists after Nuke closes;
# key by a stored node id and save to JSON if that starts to hurt.
_frecency: Frecency | None = None


def get_frecency() -> Frecency:
    """Return the session-wide frecency table."""
    global _frecency
    if _frecency is None:
        _frecency = Frecency()
    return _frecency


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

    # Read nodes are named Read1..ReadN; the file name is what the artist remembers.
    if node.knob("file") and node["file"].value():
        extras.append(Path(node["file"].value()).name)

    return extras


def _is_candidate(node: Any, *, target: Any, downstream: set[str]) -> bool:
    if node.Class() in SKIP_CLASSES:
        return False
    if node.fullName() == target.fullName() or node.fullName() in downstream:
        return False
    if node.Class() == "Dot" and not node["label"].value().strip():
        return False
    return True


def collect_candidates(target: Any) -> list[Candidate]:
    """Return every node in the current graph that can become an input of `target`."""
    script = nuke.root().name()
    downstream = _downstream(target)

    candidates = []
    for node in nuke.allNodes():
        if not _is_candidate(node, target=target, downstream=downstream):
            continue

        distance = math.hypot(node.xpos() - target.xpos(), node.ypos() - target.ypos())
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

    When every input is taken, input 0 is offered: the artist may want to rewire it.
    """
    optional = target.optionalInput()
    for index in range(target.maxInputs()):
        if index != optional and target.input(index) is None:
            return index
    return 0


def sockets(target: Any) -> list[int]:
    """Return the input indexes the artist can pick from, in index order.

    Covers every connected input, the first free one, and everything up to the mask,
    so an empty Merge offers B, A, mask. Merge has thousands of A inputs; the range
    stops there instead of listing them all.
    """
    count = max(target.inputs(), input_slot(target) + 1, target.optionalInput() + 1)
    return list(range(min(target.maxInputs(), count)))


def socket_name(target: Any, slot: int) -> str:
    """Return the label Nuke draws on the input arrow, as far as the Python API lets us know it."""
    if slot == target.optionalInput():
        return "mask"

    # shortcut: the Python API has no call for input labels; extend this table as nodes come up.
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

    get_frecency().add(candidate.key, time.time())


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


def _dag_widget() -> Any | None:
    """Return the visible Node Graph widget, preferring the one under the cursor."""
    # shortcut: Nuke names its graph widgets "DAG.1", "DAG.2"...; this is not public API,
    # so a None result falls back to the cursor position.
    graphs = [
        widget
        for widget in QtWidgets.QApplication.allWidgets()
        if widget.objectName().startswith("DAG") and widget.isVisible()
    ]
    cursor = QtGui.QCursor.pos()
    for widget in graphs:
        if widget.rect().contains(widget.mapFromGlobal(cursor)):
            return widget
    return graphs[0] if graphs else None


def _popup_position(target: Any) -> Any:
    """Return the global position just under `target` in the Node Graph, or the cursor position."""
    dag = _dag_widget()
    if dag is None:
        LOGGER.warning("zconnect: no Node Graph widget found, opening at the cursor.")
        return QtGui.QCursor.pos()

    below_node = (target.xpos() + target.screenWidth() / 2, target.ypos() + target.screenHeight())
    x, y = dag_to_widget(
        below_node,
        center=tuple(nuke.center()),
        zoom=nuke.zoom(),
        size=(dag.width(), dag.height()),
    )
    if not dag.rect().contains(QtCore.QPoint(x, y)):
        LOGGER.debug("zconnect: %s is outside the view, opening at the cursor.", target.name())
        return QtGui.QCursor.pos()
    return dag.mapToGlobal(QtCore.QPoint(x, y + 8))


def _place(popup: QtWidgets.QWidget, target: Any) -> None:
    """Move `popup` under `target`, kept inside the screen it opens on."""
    popup.adjustSize()
    position = _popup_position(target)

    screen = QtGui.QGuiApplication.screenAt(position) or QtGui.QGuiApplication.primaryScreen()
    area = screen.availableGeometry()
    x, y = clamp_to_screen(
        (position.x(), position.y()),
        size=(popup.width(), popup.height()),
        screen=(area.x(), area.y(), area.width(), area.height()),
    )
    popup.move(x, y)


# === UI === #


class Popup(QtWidgets.QFrame):
    """Search field, input tabs and result table for connecting one target node."""

    def __init__(
        self,
        target: Any,
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

        self._slot = input_slot(target)
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
        # Set before connecting the signal, so building the tabs does not refresh twice.
        self._tabs.setCurrentIndex(self._slots.index(self._slot))
        self._tabs.currentChanged.connect(self._on_tab_changed)

        hint = "   (Alt+A: switch input)" if len(self._slots) > 1 else ""
        self._query = QtWidgets.QLineEdit()
        self._query.setPlaceholderText(f"connect to {self._target.name()}{hint}")
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

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._tabs)
        layout.addWidget(self._query)
        layout.addWidget(self._table)
        self.setLayout(layout)

    def _current_row(self) -> int:
        return self._table.indexOfTopLevelItem(self._table.currentItem())

    def _set_row(self, row: int) -> None:
        self._table.setCurrentItem(self._table.topLevelItem(row))

    def _refresh(self) -> None:
        is_mask = self._slot == self._target.optionalInput()
        boost = MASK_CLASSES if is_mask else frozenset()
        ranked = rank(
            self._candidates,
            self._query.text(),
            frecency=get_frecency(),
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

        for node in nuke.selectedNodes():
            node.setSelected(False)
        self._matches[row].node.setSelected(True)
        nuke.zoomToFitSelected()

    def _accept(self) -> None:
        row = self._current_row()
        self.close()
        if 0 <= row < len(self._matches):
            connect(self._target, self._matches[row], slot=self._slot)

    def _next_socket(self) -> None:
        self._tabs.setCurrentIndex((self._tabs.currentIndex() + 1) % len(self._slots))

    def _alt_key(self, key: int) -> bool:
        # Compare key codes, not event.text(): on macOS Option+A types "å".
        if key == QtCore.Qt.Key_F:
            self._focus()
            return True
        if key == QtCore.Qt.Key_A:
            self._next_socket()
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
        """Put view and selection back where the artist was working, whatever closed the popup."""
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
            self._accept()
            return True
        if key in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Down):
            self._move(1)
            return True
        if key in (QtCore.Qt.Key_Backtab, QtCore.Qt.Key_Up):
            self._move(-1)
            return True
        return False


# Keeps the open popup alive when Nuke has no active window to own it.
_popup: Popup | None = None


def show() -> None:
    """Open the popup for the selected node. Bind this to the hotkey."""
    global _popup

    try:
        target = nuke.selectedNode()
    except ValueError:
        nuke.message("zconnect: select a node first.")
        return

    if target.maxInputs() == 0:
        nuke.message(f"zconnect: {target.name()} has no inputs.")
        return

    _popup = Popup(
        target,
        candidates=collect_candidates(target),
        slots=sockets(target),
        parent=QtWidgets.QApplication.activeWindow(),
    )
    _place(_popup, target)
    _popup.show()
    _popup.setFocus()
