# zconnect

Connect Nuke nodes by fuzzy search instead of dragging pipes.

Select a node, press `Z`, type a few letters, press `Enter`. The match
connects to the first free input. Search covers node name, label, class and
Read file name. Nodes you use often and recently rank first. On the mask
input, Roto, Keyer and shape nodes rank first.

`Shift+Z` jumps to any node, backdrop or sticky note instead.

## Install

Copy `zconnect.py` into `~/.nuke` and add this to `~/.nuke/menu.py`:

```python
import nuke
import zconnect

graph = nuke.menu("Node Graph")
graph.addCommand("zconnect/Connect input", zconnect.show, "z", shortcutContext=2)
graph.addCommand("zconnect/Jump to node", zconnect.jump, "shift+z", shortcutContext=2)
```

Change `"z"` and `"shift+z"` to use other keys.

Or clone the repo and add it to the plugin path in `~/.nuke/init.py`. Its
`menu.py` registers the default keys:

```python
nuke.pluginAddPath("/path/to/zconnect")
```

## Keys

| Key                   | Action                                                    |
| --------------------- | --------------------------------------------------------- |
| `Z`                   | Connect an input of the selected node                     |
| `Shift+Z`             | Jump to a node                                            |
| `Tab` / `Down`, `Up`  | Move through results                                      |
| `Enter` or click      | Connect or jump, then close                               |
| `Shift+Enter`         | Jump and open the properties panel (jump mode)            |
| `Alt+A`               | Next input tab (`B`, `A`, `mask`)                         |
| `Alt+F`               | Frame the node. `Enter` connects and stays, `Esc` returns |
| `Alt+P`               | Open properties in a floating panel                       |
| `Esc`                 | Close                                                     |

## Development

Tests run without Nuke; `tests/conftest.py` fakes the `nuke` module:

```bash
uv run pytest
```

Build a large test comp to try it on:

```bash
nuke -t scripts/make_test_script.py ~/zconnect_test.nk
```

## License

MIT
