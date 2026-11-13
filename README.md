# zconnect

Connect Nuke nodes by fuzzy search instead of dragging pipes across the graph.

Select a node, press `X`, type a few letters of the node you want, press `Enter`.
The picked node becomes an input of the selected node. Matches cover the node
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
| `Shift+X` | Open the popup targeting the mask input |
| `Tab` / `Down`, `Shift+Tab` / `Up` | Move through the results |
| `Enter` or click | Connect and close |
| `Alt+F` | Frame the highlighted node in the graph; the view returns on close |
| `Alt+A` | Cycle the input to connect into |
| `Esc` | Close without connecting |

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
