---
name: simplediagrams-diagram-skill
description: Create new editable SimpleDiagrams (.simplediagram) documents from a description or an image of a diagram, using the published shape catalogue, labels and connectors. Use for flowcharts, architecture diagrams, process maps, BPMN and UML diagrams, org charts, UI flows and redrawing a pictured diagram as an editable one.
license: MIT
---

# Build a SimpleDiagrams document

Create a **new** `.simplediagram` document from a short JSON spec. The builder knows the document format and reads the public shape catalogue with one request per command, falling back to the packaged list bundled with the skill. It stores nothing between runs and writes only the new document or preview you name. Work from the user's description and source files they identify. Never replace an existing output.

When the source is an image, read [from-an-image.md](references/from-an-image.md) first. It replaces step 1 below with an inventory of what the picture shows, and adds a comparison against the picture and a report of anything unclear.

Read [visual-design.md](references/visual-design.md) for layout guidance. Use [example-spec.json](assets/example-spec.json) as a starting point and [diagram-spec-1.schema.json](schema/diagram-spec-1.schema.json) for all supported fields. [document-format.md](references/document-format.md) describes the generated package if a build error needs investigation.

## Build

The script paths below are relative to this `SKILL.md` directory (`SKILL_DIR`). The builder needs Python 3.10+ and Pydantic 2. `uv run` may fetch Pydantic if it is not cached; use an existing local Python environment with Pydantic 2 when offline.

1. Identify the things to show and their relationships. Use 5–15 nodes per page when practical.
2. Search the full catalogue with `uv run "$SKILL_DIR/scripts/find_shapes.py" database --json`, or run without a query to list libraries. Search uses descriptions and keywords as well as names. Use a result's returned `selector`, or the native `rectangle`, `ellipse`, `note` and `text` shapes. Every result can be placed. Prefer a packaged result (`packaged: true`) when it fits as well: it needs no library. A document opens in apps since 5.0.8 unless the build's `needs` lines say otherwise (5.0.16 for one with downloadable shapes), and a packaged shape added in a later release is a dashed placeholder in an earlier app; the `needs` lines name the release each newer shape needs. Use a downloadable result when it is the shape the diagram needs; the document then names its library, and the build prints `needs` lines saying which library and SimpleDiagrams version show it. Pass those lines on to the user. The app draws a downloadable shape in its library's own colours, so leave `fill`, `stroke` and `line_width` off it, and once its shapes are in place the app saves the file in its own current format. Read [shape-catalogue.md](references/shape-catalogue.md) for requests, offline use and result paging.
3. Place nodes on a grid and connect them by node key. Prefer one flow direction and short labels. Write the JSON spec beside the intended output.
4. Check the spec without writing a document:

   ```bash
   uv run "$SKILL_DIR/scripts/build_diagram.py" output/order-flow.spec.json
   ```

5. Fix errors and layout warnings. A warning names a shape by its label, or by its node key when it has none. Optionally write a **new** wireframe SVG to inspect spacing and routes; it shows frames rather than the library artwork:

   ```bash
   uv run "$SKILL_DIR/scripts/preview_diagram.py" output/order-flow.spec.json output/order-flow-preview.svg
   ```

6. Build to a **new** path ending in `.simplediagram`:

   ```bash
   uv run "$SKILL_DIR/scripts/build_diagram.py" output/order-flow.spec.json "output/Order flow.simplediagram"
   ```

   If the path exists, choose another name. Keep the spec beside the output so it can be rebuilt. Report the output path and the checks actually completed.

## Spec essentials

```json
{
  "spec_version": 1,
  "name": "Order flow",
  "pages": [{
    "name": "Overview",
    "nodes": [
      {"key": "shop", "shape": "basic/Square", "label": "Web shop", "col": 0, "row": 0, "width": 140, "height": 70},
      {"key": "db", "shape": "basic/Cylinder", "label": "Orders", "col": 1, "row": 0, "scale": 1.6, "label_position": "below"}
    ],
    "edges": [{"source": "shop", "target": "db", "label": "writes"}]
  }]
}
```

- Each node needs a page-unique `key`, a `shape`, and either grid `col`/`row` or point `x`/`y`. Set `width`/`height` for labeled boxes; use `scale` and `label_position: "below"` for pictorial library shapes. A library shape that has its own label placement (a BPMN event puts its name below) gets it unless the spec sets `label_position`.
- Each edge names a source and target node. The builder routes it and adds a target arrow by default. Use `source_side`/`target_side` only when the automatic route needs correction. To attach to one particular connection point, such as a component's lead end, give `source_point`/`target_point` with an id from the shape's `connection_points` (the `points:` line in find_shapes.py's listing) instead of a side; the route starts exactly there. An edge may join two different points of one node when it names both `source_point` and `target_point`; it is routed around the shape. Some library shapes have no connection points (BPMN task marks sit on a task): connect the shape they mark instead.
- For BPMN process diagrams use the `bpmn` library: events, gateways, typed tasks, sub-processes, data and messages. Plain tasks and plain gateways are Basic shapes; pools and lanes are not offered yet. The skill writes no shape data, so the BPMN details the app attaches to a shape placed by hand are not filled in.
- For UML diagrams use the `uml` library: actor, initial-node, final-node, flow-final, terminate, fork-join-bar, note and package. Give the fork / join bar a `width` or `scale`, never a `height`: it keeps its thickness, and a larger `line_width` makes it bolder. Because connected shapes stay unturned, the bar is always horizontal, so lay activity flows out top to bottom. Draw a class, interface or entity as a labelled `rectangle`; the app's ready-made class tables, system boundary and sequence-diagram lifelines are not offered yet. Draw each relationship with these edge settings, from the first end to the second:

  | Relationship | `pattern` | `start_ending` | `end_ending` | `route` | Draw from → to |
  |---|---|---|---|---|---|
  | Association | solid | none | none | orthogonal | either way |
  | Inheritance | solid | none | solidArrow | orthogonal | child → parent |
  | Implements | dashed | none | solidArrow | orthogonal | class → interface |
  | Dependency | dashed | none | arrow | orthogonal | user → used |
  | Aggregation | solid | openDiamond | none | orthogonal | whole → part |
  | Composition | solid | diamond | none | orthogonal | whole → part |
  | Message | solid | none | filledArrow | straight | caller → called |
  | Reply | dashed | none | arrow | straight | called → caller |
  | Async message | solid | none | arrow | straight | sender → receiver |
  | One to many | solid | oneAndOnlyOne | zeroOrMany | orthogonal | one → many |
- Keep colors and shape meanings consistent. Leave connected shapes unrotated.
- To show a shape mirrored, set `flip_horizontal` or `flip_vertical` on its node. Its connection points move with the artwork and keep their ids, and sides still mean the page's left, right, top and bottom.
- The output is a folder with `manifest.json`, `document.json`, and an empty `assets/` directory. Let the builder write it; do not edit the generated files.
- The builder prints a `needs` line when the document needs a newer app than 5.0.8: the line endings `circlePlus`, `cross` and `halfArrow` need 5.0.11; BPMN and UML shapes, the ten Basic shapes added with them, and a connector attached to a flipped shape need 5.1.0. Tell the user which version opens the document.
