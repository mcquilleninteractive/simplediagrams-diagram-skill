# Laying out a diagram people can read

A diagram works when a reader can answer "what are the parts, and how do they relate?" in a few seconds. Almost everything below serves one of two things: making the structure visible through position, and keeping connectors from competing with it.

## Before placing anything

1. **Name the one question the diagram answers.** "How does an order get fulfilled?" is a diagram. "Our system" is not; it becomes several.
2. **Choose the kind of diagram**, because it fixes the layout:

   | Subject | Layout |
   |---|---|
   | A process or sequence of steps | One line of flow, left to right; decisions branch off it |
   | A system's parts and what calls what | Layers: callers on one side, what they depend on on the other |
   | A hierarchy (org chart, breakdown) | Tree, top to bottom, children centred under the parent |
   | A cycle | Ring, clockwise |
   | A comparison | Columns with matching rows |

3. **Count the nodes.** Five to nine reads at a glance. Past about fifteen, split by page: an overview whose nodes are each a later page.

## Position carries the meaning

- **Pick one direction of flow and keep it.** Left to right for processes and data flow, top to bottom for hierarchies. Every arrow that runs against it should be a deliberate exception such as a retry or feedback loop.
- **Put things of the same rank on the same row or column.** All the services on one row, all the stores on the next. A reader takes alignment as "these are the same kind of thing", so do not align unrelated nodes by accident.
- **Order neighbours to shorten connectors.** Within a row, place each node nearest the nodes it connects to. This single step removes most crossings. If two connectors cross, try swapping two nodes in a row before anything else.
- **Put the main path on a straight line.** The sequence that matters most should run through the middle without a bend; branches and exceptions go above and below it.
- **Keep spacing even.** Use whole `col` and `row` values. The default pitch (240 across, 160 down) leaves 100 points between 140-wide boxes, which is enough for an arrowhead and a short label. Raise `column_pitch` when connectors carry labels longer than two words.
- **Use half steps sparingly.** `row: 1.5` centres a node between two rows, which suits a node fed by both. More than a couple of these and the grid stops being visible.
- **Leave room around groups.** Separate two clusters with an empty row or column rather than a box drawn around each.

## Connectors

The build routes connectors for you: from side to side (or from a connection point the spec names), horizontal and vertical runs only, with branches from one side sharing a line. Your layout decides whether that comes out clean.

- **Prefer `orthogonal`.** Straight horizontal and vertical runs are the easiest to follow. Use `straight` only when both ends are already aligned or for a deliberately informal sketch, and `curved` for a loop back against the flow.
- **Aligned neighbours get a perfectly straight line.** Two nodes on the same row or column connect with one segment and no bends. Aim for most of your connectors to be like this.
- **A bend is a cost.** One bend is fine, two is the normal offset route, more means the nodes are in the wrong places.
- **Never run a connector through a shape or a label.** The build steers around other shapes where it can and warns with `connector-through-shape` or `connector-through-label` where it cannot. Fix it by moving the node out of the way; only then reach for `source_side` and `target_side`, and expect a warning if the sides you force send the line back through its own shape.
- **One connector per relationship.** Two connectors between the same pair of sides are drawn on top of each other (`connectors-overlap`). For a two-way relationship use one connector with an ending at both ends.
- **Avoid crossings; never leave an ambiguous one.** The build warns with `connectors-cross`. Reorder nodes first. If one crossing is unavoidable, make sure the lines cross at right angles and well away from any bend.
- **Fan out from one side.** When a node feeds several others, leave them all from the same side so they share one trunk and split, like a tree. The trunk runs midway between the shapes, so the branches only share it when the targets are the same width or share a left edge; make a row of targets one size. Likewise several connectors arriving at one node should arrive on one side.
- **Enter and leave in the direction of flow.** In a left-to-right diagram, connectors leave from the right and arrive on the left. A connector into the top of a box in that diagram reads as a different kind of relationship, so use it only for one (a dependency, a note).
- **One arrowhead, at the target.** Use arrows on both ends only for a genuinely two-way exchange. Use no arrowhead (`end_ending: "none"`) for association without direction.
- **Use line pattern for kind, not decoration.** Solid for the main relationship; `dashed` for a secondary one (optional, asynchronous, "reads from"). Pick the meaning once and keep it across pages.
- **Label only what the shapes do not already say.** A label is one to three words in the reader's vocabulary: "places order", "on failure". If every connector needs a label, the nodes are probably named too vaguely.

## Shapes and text

- **One shape per kind of thing.** If a cylinder is a database once, it is a database everywhere, and nothing else is a cylinder. Three or four kinds is usually the limit before a legend is needed.
- **Boxes hold labels; icons carry them outside.** For a labelled box use `basic/Square` with an explicit `width` and `height`. For pictorial shapes (people, databases, documents, clouds) use `scale` to size them and `label_position: "below"`, because artwork under text is unreadable.
- **Captions need room.** A caption wider than its icon is placed as its own centred text under the icon. Leave the row beneath clear, and bring connectors into the icon from the sides or the top so they do not cross the caption. In a top-to-bottom layout put captions `above`, or use labelled boxes instead of icons.
- **Do not rotate connected shapes.** The app moves an attached end with the rotation and the stored route no longer matches (`rotated-end`).
- **Make same-rank shapes the same size.** Set one `width` and `height` for all the boxes in a row, sized to the longest label, rather than fitting each to its own text.
- **Size to the text.** At the default 15-point font a 140-wide box holds roughly 14 characters a line. That figure is an estimate, not a measurement of the app's font, so leave slack. The build warns with `label-overflow`; widen the box or break the label with `\n` at a natural point rather than shrinking the font.
- **Labels are names, not sentences.** Two or three words, title or sentence case used consistently. Put explanation in a `note` beside the diagram, not in the node.
- **Keep text at one size** for nodes, and one smaller size for connector labels (the build uses 13). Use `bold` for a title or the one node that is the subject, not for emphasis in general.

## Color

SimpleDiagrams draws in a hand-drawn style: black lines on white, with color used lightly. Follow that.

- **Start with no color at all.** White fills and black lines, the library default, is a complete diagram.
- **Add color only to carry meaning**: one hue for a category ("external systems"), or one accent for the thing the diagram is about. Two or three fills at most, and say what they mean if it is not obvious.
- **Use pale fills** so black text stays readable: for example `#D8ECFF` (sky), `#DDF5E3` (mint), `#FFF1A8` (note yellow), which are the app's own Quick Styles. Keep outlines dark.
- **Do not rely on color alone.** Pair it with shape or position so the diagram still reads in grayscale and for color-blind readers.
- **Keep connectors neutral.** The default dark gray. Color a connector only to mark a path, and then color the whole path.

## Final check

Render the wireframe and look at it as a reader would. Then confirm:

- The flow direction is obvious without reading a single label.
- The main path is a straight line.
- No build warnings remain.
- Every node has at least one connector, unless it is a note or title.
- Nodes of one kind share a shape, a size and a row or column.
- Spacing between neighbours is the same everywhere.
- Nothing is labelled that the layout already makes clear.
