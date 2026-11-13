"""Nuke runs this file at startup once the repo folder is on the plugin path."""

from __future__ import annotations

import nuke

import zconnect

graph = nuke.menu("Node Graph")
graph.addCommand("zconnect/Connect input", zconnect.show, "z", shortcutContext=2)
graph.addCommand("zconnect/Jump to node", zconnect.jump, "shift+z", shortcutContext=2)
