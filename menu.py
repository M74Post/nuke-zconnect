"""Nuke runs this file at startup once the repo folder is on the plugin path."""

from __future__ import annotations

import nuke

import zconnect

graph = nuke.menu("Node Graph")
graph.addCommand("zconnect/Connect input", lambda: zconnect.show(), "x", shortcutContext=2)
graph.addCommand("zconnect/Connect mask", lambda: zconnect.show(mask=True), "shift+x", shortcutContext=2)
