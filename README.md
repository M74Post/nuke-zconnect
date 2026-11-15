# zconnect

Connect Nuke nodes by fuzzy search instead of dragging pipes.

Select a node, press `Z`, type a few letters, press `Enter`. The match
connects to the first free input. Search covers node name, label, class and
Read file name. Nodes you use often and recently rank first. On the mask
input, Roto, Keyer and shape nodes rank first.

`Shift+Z` jumps to any node, backdrop or sticky note instead.

## Install

Download `nuke-zconnect-<version>.zip` from the
[releases](https://github.com/sisoe24/nuke-zconnect/releases), unzip it
anywhere, and add the folder to the plugin path in `~/.nuke/init.py`:

```python
nuke.pluginAddPath("/path/to/zconnect")
```

To use other keys, copy only `zconnect.py` into `~/.nuke` and add this to
`~/.nuke/menu.py`, with your own keys in place of `"z"` and `"shift+z"`:

```python
import nuke
import zconnect

graph = nuke.menu("Node Graph")
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

Build the release zip:

```bash
mkdir -p dist/zconnect && cp zconnect.py menu.py LICENSE README.md dist/zconnect/
(cd dist && zip -r nuke-zconnect-0.1.0.zip zconnect)
```

## License

MIT
