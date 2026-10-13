---
name: simplediagrams-diagram-skill
description: Create new editable SimpleDiagrams (.simplediagram) documents from a description or from an image of a diagram (a photo of a whiteboard or notebook sketch, a screenshot, a scan) using the bundled built-in shapes, labels, and connectors. Use for flowcharts, architecture diagrams, process maps, org charts, and UI flows, and to redraw a pictured diagram as an editable one.
license: MIT
---

# Build a SimpleDiagrams document

Create a **new** `.simplediagram` document from a short JSON spec. The bundled builder knows the document format and the built-in shape catalog. Work from the user's description and source files they identify. Never replace an existing output.

When the source is an image, read [from-an-image.md](references/from-an-image.md) first. It replaces step 1 below with an inventory of what the picture shows, and adds a comparison against the picture and a report of anything unclear.

Read [visual-design.md](references/visual-design.md) for layout guidance. Use [example-spec.json](assets/example-spec.json) as a starting point and [diagram-spec-1.schema.json](schema/diagram-spec-1.schema.json) for all supported fields. [document-format.md](references/document-format.md) describes the generated package if a build error needs investigation.

## Build

The script paths below are relative to this `SKILL.md` directory (`SKILL_DIR`). The builder needs Python 3.10+ and Pydantic 2. `uv run` may fetch Pydantic if it is not cached; use an existing local Python environment with Pydantic 2 when offline.

1. Identify the things to show and their relationships. Use 5–15 nodes per page when practical.
2. Choose shapes from the bundled catalog. Run `python3 "$SKILL_DIR/scripts/find_shapes.py"` to list libraries, or pass a search term such as `database`. Use only returned `<library>/<item>` names or the native `rectangle`, `ellipse`, `note`, and `text` shapes.
3. Place nodes on a grid and connect them by node key. Prefer one flow direction and short labels. Write the JSON spec beside the intended output.
4. Check the spec without writing a document:

   ```bash
   uv run "$SKILL_DIR/scripts/build_diagram.py" output/order-flow.spec.json
   ```

5. Fix errors and layout warnings. Optionally write a **new** wireframe SVG to inspect spacing and routes; it shows frames rather than the library artwork:

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

- Each node needs a page-unique `key`, a `shape`, and either grid `col`/`row` or point `x`/`y`. Set `width`/`height` for labeled boxes; use `scale` and `label_position: "below"` for pictorial library shapes.
- Each edge names a source and target node. The builder routes it and adds a target arrow by default. Use `source_side`/`target_side` only when the automatic route needs correction.
- Keep colors and shape meanings consistent. Leave connected shapes unrotated.
- The output is a folder with `manifest.json`, `document.json`, and an empty `assets/` directory. Let the builder write it; do not edit the generated files.
