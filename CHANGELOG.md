# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

### Added

- `Z` opens a fuzzy search popup that connects the picked node to an input of
  the selected node. Matches cover the node name, label, class and the file
  name of Read nodes.
- Results rank by frecency: nodes you picked recently and often rank higher.
- Input sockets show as tabs. The popup starts on the first free input, and
  `Alt+A` cycles through the inputs.
- Roto, RotoPaint, Keyer, Radial, Rectangle and Ramp nodes rank higher when
  the mask input is picked.
- Nodes downstream of the target are left out, so a connection cannot make a cycle.
- `Shift+Z` jump mode selects and frames any node. `Shift+Enter` also opens its
  properties panel.
- `Alt+F` frames the highlighted node. `Esc` returns the view; `Enter`
  connects and stays on the node.
- `Alt+P` opens the highlighted node's properties in a floating panel.
- A key hint row at the bottom of the popup.
- The popup opens under the selected node in the focused Node Graph.
