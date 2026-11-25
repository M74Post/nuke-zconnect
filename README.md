# zconnect

Plug nodes together without dragging pipes across the graph.

Select a node, hit `Z`, type a few letters of the node you want, `Enter`.
`Shift+Z` uses the same search to jump to a node instead.

## Install

Download the Source code zip from the
[latest release](https://github.com/M74Post/nuke-zconnect/releases/latest), unzip it
anywhere, and add the folder to the plugin path in `~/.nuke/init.py`:

```python
nuke.pluginAddPath("/path/to/nuke-zconnect")
```

Or copy `zconnect.py` into `~/.nuke` and add this to `~/.nuke/menu.py`:

```python
import nuke
import zconnect

graph = nuke.menu("Node Graph")
# Change the keys to whatever you like.
graph.addCommand("zconnect/Connect input", zconnect.show, "z", shortcutContext=2)
graph.addCommand("zconnect/Jump to node", zconnect.jump, "shift+z", shortcutContext=2)
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

## Maintainer

Made and maintained by [Virgil Sisoe](https://github.com/sisoe24).

## License

MIT
