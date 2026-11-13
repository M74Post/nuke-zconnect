"""Stand-in `nuke` module, so zconnect imports outside Nuke."""

from __future__ import annotations

import sys
import types

nuke = types.ModuleType("nuke")
nuke.INPUTS = 1
nuke.HIDDEN_INPUTS = 2
sys.modules.setdefault("nuke", nuke)
