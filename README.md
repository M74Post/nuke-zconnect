# zconnect

Connect Nuke nodes by fuzzy search instead of dragging pipes across the graph.

Select a node and press `X`, type a few letters of the node you want, press
`Enter`. The picked node connects to the first free input of the selected
node; `Alt+A` cycles to another input first. Matches cover the node
name, its label, its class, and the file name of Read nodes. Nodes you picked
recently rank higher, like `zoxide`.

Status: early prototype. The interaction is still changing.

## Install

Add the repo folder to Nuke's plugin path in `~/.nuke/init.py`:

```python
nuke.pluginAddPath("/path/to/zconnect")
```

Nuke then runs this repo's `menu.py`, which registers the shortcuts in the
Node Graph.

## Keys

| Key | Action |
|---|---|
| `X` | Open the popup for the selected node |
| `Alt+A` | Switch to the next input tab (`B`, `A`, `mask`...); click a tab works too |
| `Tab` / `Down`, `Shift+Tab` / `Up` | Move through the results |
| `Enter` or click | Connect and close |
| `Alt+F` | Frame the highlighted node in the graph; the view returns on close |
| `Esc` | Close without connecting |

The popup opens just under the selected node. The input starts on the first
free one; nodes with a single input show no tabs. When the mask input is picked, Roto,
RotoPaint, Keyer, Radial, Rectangle and Ramp nodes rank higher.

## Development

Run the tests (no Nuke needed):

```bash
uv run pytest
```

Build a large test comp inside Nuke with `scripts/make_test_script.py`:
paste it into the Script Editor, or save it as a script from a terminal:

```bash
nuke -t scripts/make_test_script.py ~/zconnect_test.nk
```
