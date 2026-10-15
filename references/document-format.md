# The `.simplediagram` document format, version 15

This describes what the skill writes. The exact statement of it is `scripts/sd_format.py` (Pydantic models) and the generated `schema/simplediagram-document-15.schema.json`; if this page and the models ever disagree, the models are right.

The app itself writes package 17 / schema 16 and reads every version from 1. The skill keeps writing 15 / 14 so its documents open in 5.0.8 and later. The complete structure of a diagram file in every version, including what the skill leaves out, is described in SimpleDiagrams' project documentation (`desktop/diagram-document-structure.md`); this page covers only what the skill writes.

Write a diagram spec and let `build_diagram.py` produce the document. This reference explains the generated package and build diagnostics.

## What this covers

The **authoring profile**: shapes drawn by the app (`rectangle`, `ellipse`, `note`, `text`, `path`), shapes from the libraries built into the app (`symbol`), connectors, groups, guides, drawing order, grid and a solid page background.

Not covered, and rejected by the skill's models although the app can read them: embedded images, shapes from downloaded or personal libraries (stored as embedded artwork files), shape data, image backgrounds, print layout, and content imported from older versions.

## The package

A document is a **folder** whose name ends in `.simplediagram`. It is not a zip.

```
Order flow.simplediagram/
  manifest.json
  document.json
  assets/              must exist; empty in this profile
```

The app refuses the document if the folder has any other member, including `.DS_Store`, if `assets/` is missing, or if `assets/` contains anything it was not told about. Tools that drop empty folders (git, zip) and Finder's **Show Package Contents** are the usual ways a good document gets broken.

`manifest.json` is always exactly:

```json
{"format": "com.simplediagrams.document", "format_version": 15, "contains_legacy_source": false}
```

## Two version numbers

`manifest.json` has `format_version` **15**. `document.json` has `schema_version` **14**. They are different counters and the second is always the first minus one. Writing 15 in both is refused.

## Shape of `document.json`

Nine top-level keys, all required, no others allowed:

| Key | Value |
|---|---|
| `id` | UUID |
| `schema_version` | `14` |
| `revision` | `0` for a new document |
| `name` | Text, up to 512 bytes |
| `selected_page_id` | The `id` of one of the pages |
| `pages` | 1 to 100 pages |
| `quick_styles` | Up to 32 presets; `[]` is valid, the builder writes the app's six defaults |
| `embedded_assets` | `[]` |
| `shape_data_definitions` | `[]` |

Each format version wraps the previous one's record under a `content` key instead of adding keys to it. That is why pages and elements are nested, and why several arrays exist at more than one level with only one of them in use.

### A page

```
page
├─ elements: [ element, ... ]            the page's shapes
└─ content
   ├─ background: {"kind": "none"}       or {"kind": "solid", "color_hex": "#FFF9DB"}
   ├─ groups: [ ... ]                    the page's groups
   ├─ elements: []                       always empty
   ├─ drawableOrder, guides              optional; note the camelCase
   └─ content
      ├─ connections: [ connection, ... ]   the page's connectors
      ├─ elements: []                    always empty
      ├─ groups: []                      always empty
      └─ content
         ├─ id, name, width, height
         ├─ grid: {"spacing_x": 20, "spacing_y": 20, "origin": {"x": 0, "y": 0}}
         ├─ elements: []                 always empty
         ├─ connections: []              always empty
         └─ export_frame                 optional
```

`width` and `height` are a reference size (the app uses 2000 by 1200). The canvas is unbounded and nothing is clipped.

### An element

```
element
├─ shape_data_definition_id: null        the key must be present
├─ shape_data_values: []
└─ content
   ├─ flip_horizontal, flip_vertical     required booleans
   ├─ text_layout, note_style, preserves_aspect_ratio    optional
   └─ content
      ├─ is_locked                       required boolean
      └─ content
         ├─ id                           UUID
         ├─ kind                         rectangle | ellipse | note | text | symbol | path
         ├─ frame                        {"x", "y", "width", "height"}, sizes above zero
         ├─ rotation_degrees, z_index
         ├─ text_content                 see below; required even when the text is empty
         ├─ style                        {"fill_hex", "stroke_hex", "line_width"}
         ├─ connection_points            anchors a connector can attach to
         ├─ symbol_reference             required for symbol, forbidden otherwise
         └─ path                         required for path, forbidden otherwise
```

A path's node coordinates are relative to the top left corner of its `frame`, not to the page.

A library shape:

```json
"symbol_reference": {"library_id": "com.simplediagrams.shapeLibrary.basic", "item_id": "Cylinder", "asset_version": 1}
```

All three values must match `assets/built-in-shapes.json` exactly. A reference the app cannot resolve does not stop the document opening: the shape is drawn as a dashed placeholder showing the item name. Nothing reports this at open time, which is why the skill's validator treats it as an error.

A library shape's `connection_points` and `text_layout` are written as its library gives them, which is what the app gives a copy dragged from the Library panel. Most shapes have the standard eight anchors and no layout. A few differ: BPMN's task marks have `"connection_points": []`, its events have a `text_layout` with position `below`, and its tasks have a text area that keeps clear of the picture in their corner.

The app does not size a shape for you. `frame` is always required and the artwork is stretched to it; the natural size in the catalogue is only a starting point.

Text, with every key shown required:

```json
"text_content": {
  "string": "Orders",
  "base_alignment": "center",
  "character_runs": [],
  "paragraph_runs": [],
  "base_style": {"font_size": 15, "weight": "medium", "is_italic": false, "is_underlined": false, "color_hex": "#212529"}
}
```

Run ranges are counted in UTF-16 units and must start and end between whole user-perceived characters: not inside an emoji, an accented letter written as two code points, or a `\r\n` pair. That cannot be checked reliably outside the app, so this profile allows runs only when the text is plain ASCII. Leave both arrays empty otherwise; the text itself may contain any characters.

The eight standard anchors, as fractions of the frame:

| id | Place | id | Place |
|---|---|---|---|
| 0 | left middle | 4 | top left |
| 1 | right middle | 5 | bottom left |
| 2 | top middle | 6 | top right |
| 3 | bottom middle | 7 | bottom right |

### A connector

```json
{
  "is_locked": false,
  "content": {
    "id": "…",
    "points": [{"x": 270, "y": 160, "kind": "straight"}, {"x": 370, "y": 160, "kind": "straight"}],
    "start_attachment": {"element_id": "…", "connection_point_id": 1},
    "end_attachment": {"element_id": "…", "connection_point_id": 0},
    "stroke_hex": "#495057", "line_width": 2, "stroke_pattern": "solid",
    "start_ending": "none", "end_ending": "arrow"
  }
}
```

- `points` is the entire route, at least two. A right-angled connector here is simply points that form right angles. A point of kind `curve` between two others makes a smooth bend through it. Package 16 added connectors that route themselves (`routing: right_angle`); the skill does not write them, because a package 16 document does not open in 5.0.8 to 5.0.14.
- An attachment binds an end to an anchor on an element of the same page. The app then draws that end at the anchor wherever the shape moves. Still store the anchor's position as the end point.
- An attachment to an element or anchor that does not exist stops the document opening.
- Optional: `label` (`{"content": text, "position": 0 to 1, "normal_offset": points}`) and `stroke_texture`.

## Rules that are easy to break

- **Coordinates** are points, 72 to the inch, origin top left, y downward. Rotation is clockwise in degrees about the frame's centre; `frame` is the unrotated rectangle.
- **Colors** are `#RRGGBB` or `#RRGGBBAA`. Transparent is `#00000000`. `none`, `transparent`, color names and `#FFF` are all refused.
- **Identifiers** are UUIDs, and every one in the document must be distinct across pages, elements, connectors, groups, guides and quick styles together. The app writes upper case and reads either.
- **Unknown keys** are refused at the document, page and element wrappers, and silently discarded elsewhere. The skill's models refuse them everywhere. `drawable_order` in snake_case is a discarded unknown key, not the drawing order.
- **Optional keys are omitted, not set to null**, with one exception: `shape_data_definition_id` must be present and `null`.
- **Whole numbers** (`z_index`, `revision`, anchor ids, `asset_version`) should be written without a decimal point and must fit in 64 bits.
- **A key must not appear twice** in one object. The app and most other parsers disagree about which copy wins.
- **Font family and Quick Style names** may not contain Unicode control or format characters, which includes invisible ones such as the soft hyphen and zero-width space. JSON Schema cannot express this rule, nor the ones about identifiers, attachments, groups and runs; the Pydantic models check them.
- **A label placed `above` or `below`** is confined to the width of its shape's label region and wraps inside it. For a caption wider than the shape, use a separate `text` element grouped with the shape, which is what the builder does.
- **Drawing order**: without `drawableOrder`, connectors draw behind shapes and shapes stack by `z_index`. If you write `drawableOrder` it must list every shape and connector on the page exactly once, back to front.
- **Groups** need at least two members on the same page, each member in only one group, no cycles.

## Enumerated values

- **Endings**: `none`, `stop`, `arrow`, `solidArrow`, `filledArrow`, `circle`, `solidCircle`, `openDiamond`, `diamond`, `halfCircle`, `slash`, and for data models `crowFoot`, `one`, `oneAndOnlyOne`, `zeroOrOne`, `oneOrMany`, `zeroOrMany`. Since 5.0.11 also `circlePlus`, `cross` and `halfArrow`, with no format change: an earlier app refuses a document that uses one, and the builder says so.
- **Stroke pattern**: `solid`, `dashed`, `dotted`.
- **Font weight**: `regular`, `medium`, `bold`. **Alignment**: `leading`, `center`, `trailing`, `justified`.
- **Label position**: `above`, `top`, `middle`, `bottom`, `below`.
- **Note style**: `stickyNote`, `indexCard`.
- **Textures**: `Horizontal`, `Vertical`, `Grid`, `SingleHatch`, `TripleHatch`, `PencilFill`, `PencilThinHoriztonalHatch` (spelt this way in the app), `PencilThinSquareHatch`, `PencilThinCrossHatch`, `PencilThinDiagonalHatch`, `WatercolorFill`, `Grain`, `PencilVerticalHatch`, `PencilTriangleHatch`, `PencilRandomHatch`, `PencilHorizontal`, `Chalk`.
