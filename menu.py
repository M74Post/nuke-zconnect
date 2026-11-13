"""Nuke runs this file at startup once the repo folder is on the plugin path."""

from __future__ import annotations

import nuke

import zconnect

nuke.menu("Node Graph").addCommand("zconnect/Connect input", zconnect.show, "x", shortcutContext=2)
