# zconnect

Connect Nuke nodes by fuzzy search instead of dragging pipes across the graph.

Select a node and press `Z`, type a few letters of the node you want, press
`Enter`. The picked node connects to the first free input of the selected
node; `Alt+A` cycles to another input first. Matches cover the node
name, its label, its class, and the file name of Read nodes. Nodes you picked
recently rank higher, like `zoxide`.

`Shift+Z` opens the same search without a selected node and jumps to the
pick: it selects the node and frames it, like `z` in zoxide changes directory.

## Install

zconnect is one file, `zconnect.py`. Either copy it into `~/.nuke` and add
this to `~/.nuke/menu.py`:

```python
import nuke
import zconnect

graph = nuke.menu("Node Graph")
graph.addCommand("zconnect/Connect input", zconnect.show, "z", shortcutContext=2)
graph.addCommand("zconnect/Jump to node", zconnect.jump, "shift+z", shortcutContext=2)
```

Or add the repo folder to Nuke's plugin path in `~/.nuke/init.py`, and this
repo's `menu.py` registers the shortcuts for you:

```python
nuke.pluginAddPath("/path/to/zconnect")
```

### Shortcut clash

`Z` and `Shift+Z` may already be bound in your Nuke setup, by Nuke itself or by
another plugin. The zconnect binding takes over the key in the Node Graph.
To keep the existing shortcut, pass a different key to `addCommand`, for
example `"alt+z"`.

## Keys

| Key                                | Action                                                                    |
| ---------------------------------- | ------------------------------------------------------------------------- |
| `Z`                                | Open the popup to connect an input of the selected node                   |
| `Shift+Z`                          | Open the popup to jump to any node                                        |
| `Alt+A`                            | Switch to the next input tab (`B`, `A`, `mask`...); click a tab works too |
| `Tab` / `Down`, `Shift+Tab` / `Up` | Move through the results                                                  |
| `Enter` or click                   | Connect (or jump) and close                                               |
| `Shift+Enter`                      | Jump mode only: jump and open the node's properties panel                 |
| `Alt+P`                            | Open the highlighted node's properties in a floating panel                |
| `Alt+F`                            | Frame the highlighted node; `Esc` returns the view, `Enter` connects and stays there |
| `Esc`                              | Close without connecting                                                  |

A hint row at the bottom of the popup lists these keys and wraps to the popup width.
The popup opens just under the selected node. The input starts on the first
free one; nodes with a single input show no tabs. When the mask input is picked, Roto,
RotoPaint, Keyer, Radial, Rectangle and Ramp nodes rank higher.

## Development

Run the tests (no Nuke needed; `tests/conftest.py` stands in for the `nuke` module):

```bash
uv run pytest
```

Build a large test comp inside Nuke with `scripts/make_test_script.py`:
paste it into the Script Editor, or save it as a script from a terminal:

```bash
nuke -t scripts/make_test_script.py ~/zconnect_test.nk
```

## License

MIT. See [LICENSE](LICENSE).
