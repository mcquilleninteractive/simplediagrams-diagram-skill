# The `.simplediagram` document format, version 19

This describes what the skill writes. The exact statement of it is `scripts/sd_format.py` (Pydantic models) and the generated `schema/simplediagram-document-19.schema.json`; if this page and the models ever disagree, the models are right.

The skill writes package 19 / schema 18, the format SimpleDiagrams 5.2 writes, so every document needs SimpleDiagrams 5.2.0 or later. This page covers only what the skill writes.

Write a diagram spec and let `build_diagram.py` produce the document. This reference explains the generated package and build diagnostics.

## What this covers

The **authoring profile**: shapes drawn by the app (`rectangle`, `ellipse`, `note`, `text`, `path`), shapes from the libraries packaged with the app (`symbol`), complex shapes (`complex_shape`), connectors, groups, guides, drawing order, grid and a solid page background.

Not covered, and rejected by the skill's models although the app can read them: embedded images, embedded shape artwork (how the app stores a shape from a personal or downloaded library), the `required_libraries` list that names downloadable libraries, shape data, image backgrounds, print layout, content imported from older versions, an Automatic container layout, a container wearing a drawing, a place chosen by hand for a part's words, right-angle connectors left for the app to route around other shapes, and the optional list of readable `library_shape_names`. The skill places only shapes packaged with the app; its validator reports a reference to any other library shape as an error.

## The package

A document is a **folder** whose name ends in `.simplediagram`. It is not a zip.

```
Order flow.simplediagram/
  manifest.json
  document.json
  assets/              must exist; empty in this profile
```

The app refuses the document if the folder has any other member, including `.DS_Store`, or if `assets/` contains anything it was not told about. A missing `assets/` is read as empty and put back on saving. Finder's **Show Package Contents** is the usual way a good document gets broken.

`manifest.json` is always exactly this:

```json
{"format": "com.simplediagrams.document", "format_version": 19, "contains_legacy_source": false}
```

## Two version numbers

`manifest.json` has `format_version` **19**. `document.json` has `schema_version` **18**. They are different counters and the second is always the first minus one. Writing 19 in both is refused.

## Complex shapes

A complex shape is an element of kind `complex_shape` with a `complex_shape` record beside its `content`. Every type is saved in one structure, and nothing drawn is saved: the app draws the shape from these and the element's frame each time. It has no `symbol_reference`, `path` or `text_layout`.

| Key | Meaning |
|---|---|
| `type`, `version` | One of the types below, always version 1 |
| `settings` | The shape-wide values. Every one its type declares is written, even at its default, except where marked optional |
| `parts` | What a person can touch, in the order and roles its type declares. How many lanes, rows or steps it has is the number of its parts |
| `members` | A container only, always written: what it holds, in order, `{"kind": "element" or "group", "id": …}` |
| `hand_drawn` | `false` for exact lines; left out when hand-drawn |

| `type` | Settings | Parts, in order |
|---|---|---|
| `container` | `layout` (`free`, `proportional`), `title_style` (`band`, `corner_tag`) | None |
| `swimlanes` | `direction` (`horizontal`, `vertical`), `title_strip_size`, `title_band_size` (28 to 10,000) | 1 to 50 `lane`: `id`, `text`, `size`, `members` |
| `table` | `header_row` | 1 to 50 `column`: `size`; then 1 to 200 `row`: `size`, `cells` |
| `entity_table` | None | 2 `column`: `size`; 1 `header`: `id`, `size`, `cells` (the name, then empty); 1 to 60 `field`: `id`, `size`, `cells` (name, type), `marks`, `point_ids` (2) |
| `callout` | Optional `tail_tip` `{"x", "y"}`, points from the frame's centre along the bubble's own axes before flipping; optional `tail_attachment`, a numbered point of another shape, which needs `tail_tip` | None |
| `lifeline` | `head_style` (`box`, `actor`), `ends_in_destroy_mark` | None |
| `ring` | `ring_width`: a multiple of 10 up to 10,000, or `full` | 1 to 12 `section`: `id`, `text`, `point_ids` (1) |
| `flow` | `base_shape`, `direction` (`across`, `down`), `spacing` (`gap`, `touch`, `overlap`), `pointer` | 2 to 12 `step`: `id`, `text`, `point_ids` (2) |
| `pyramid` | `form` (`pyramid`, `funnel`) | 2 to 8 `layer`: `id`, `text`, `point_ids` (2) |
| `cycle` | `ring_width`, a number as above; `direction` (`clockwise`, `anticlockwise`); `arrow_style` (`arrow`, `chevron`) | 3 to 8 `step`: `id`, `text`, `point_ids` (1) |
| `gauge` | `minimum`, `maximum`, `value`, `auto_rotate_labels` | 1 to 5 `band`: `id`, `text`; 1 `needle`: `id` |

A `section`, `step`, `layer`, `band` or `needle` may also hold a `style`, its own paint: any of `fill_hex`, `fill_texture`, `stroke_hex`, `stroke_texture` and `line_width`, at least one, a texture only beside its colour. A missing channel follows the element's, except that a part's own colour with no texture of its own is drawn flat, whatever texture the element has. The builder writes colours and a line width, never a part's texture.

A `size` is any number from 0.000001 to 1,000,000; a lane, row or column is its share of the whole. A word in a record is lower-case letters and digits in groups joined by single underscores, and a word its type does not list refuses the document. The app also holds:

- A `chevron`, `arrow_box`, `block_arrow` or `hexagon` flow has no `overlap` and no `pointer`. A gauge's `minimum` is below its `maximum`, and its `value` between them.
- A table or entity table is at least 16 points a column and 12 a row, and a table at most 2,000 cells. A lane is at least 28 thick, and swimlanes at least as long as their title strips. A lifeline is its head (40, or 72 for an actor), 20 points of line, and half a 24-point destroy mark when it has one.
- A table, entity table, ring, flow, pyramid and cycle keep their own `text_content.string` empty. A gauge's own text is its caption.
- Only a callout is flipped.
- Every member is on the same page and held once at most; a member is a shape in no group, or a whole group in no other group, never the holder, never swimlanes and never a connector. A container or swimlanes is in no group. Containers nest four deep at most, never in a loop.
- A lifeline offers one numbered point, 2, at the top of its head, and one attach line, 0, its dashed line from the bottom of its head to the frame's bottom, or to half a destroy mark above it.

**Points a shape places itself.** An entity table, ring, flow, pyramid, cycle and gauge list none: `"connection_points": []`. The app works them out as it reads the document, and the builder works out the same places, `shape_points` in the models, to end a connector there. A part owns the numbers from 8 up that its `point_ids` list; the first eight are the shape's, on its circle or the box around what it draws. A pyramid has only 2 and 3 of them, and a gauge's parts own none.

**How much a shape and a page hold.** A document over any of these is refused whole. Characters are Unicode scalars.

| What | Most |
|---|---|
| Members of a container, or of a lane | 1,000 |
| Members of all the lanes of one swimlanes | 2,000 |
| A lane title | 1,000 characters, 100 runs |
| A table cell, in a table or an entity table | 2,000 characters, 200 runs |
| All of one table's cells | 100,000 characters, 10,000 runs |
| A section's, step's, layer's or band's words, or a gauge's caption | 500 characters |
| Complex shapes on one page | 2,000 |
| Containers and swimlanes on one page | 500 |
| All the part texts and cells of one page | 1,000,000 characters |
| Part texts and cells in a document | 100,000 |

Containers and swimlanes draw behind what they hold. The skill also writes a `drawableOrder` on a page with any, listing them first, outermost first, then the connectors, then the other shapes, so a UML fragment never covers the messages it is drawn around.

## Shape of `document.json`

Nine top-level keys, all required. No others are allowed:

| Key | Value |
|---|---|
| `id` | UUID |
| `schema_version` | `18` |
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
├─ complex_shape                         on kind complex_shape only
└─ content
   ├─ flip_horizontal, flip_vertical     required booleans
   ├─ text_layout, note_style, preserves_aspect_ratio    optional
   └─ content
      ├─ is_locked                       required boolean
      └─ content
         ├─ id                           UUID
         ├─ kind                         rectangle | ellipse | note | text | symbol | path | complex_shape
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

All three values must match a packaged shape exactly, as the app names it in `assets/built-in-shapes.json`. A reference the app cannot resolve does not stop the document opening: the shape is drawn as a dashed placeholder showing the item name. Nothing reports a mistyped reference, which is why the skill's validator treats a reference not in that list as an error.

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

A style may also hold `highlight_hex`, a color drawn behind its characters. Format 19 has no whole-text `background_hex`.

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

- `points` is the entire route, at least two. A point of kind `curve` between two others makes a smooth bend through it.
- The outer record's `routing` is absent for a direct line, which passes through every point, and `right_angle` for the app's right-angle connector, which a person edits by its segments and which stays square as its shapes move. The skill writes `right_angle` for every orthogonal route it works out between two shapes: with more than two points the app keeps them as a hand-adjusted route, exactly as stored; with two, the app routes the connector itself, so a straight run is a right-angle connector only when both its anchors lie on facing frame edges, where the app draws it straight too, and otherwise stays a direct line. Every segment is horizontal or vertical and every point `straight`. A loop from a shape to itself, a connector to a turned shape, and straight or curved lines stay direct.
- An attachment binds an end to an anchor on an element of the same page. The app then draws that end at the anchor wherever the shape moves. Still store the anchor's position as the end point.
- An end may instead attach anywhere along a lifeline's dashed line: `{"element_id": "…", "attach_line_id": 0, "distance": 40}`, `distance` points down the line from the bottom of the head. An attachment holds `connection_point_id`, or `attach_line_id` with `distance`, never both.
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
- **A label placed `above` or `below`** is confined to the width of its shape's label region and wraps inside it. A region may start outside its shape while it still touches it (`x` at least `-width`, `y` at least `-height`, each side at most 8 times the shape's). The builder writes a library's own region as the app does, such as the wider, centred name of a BPMN event or the UML Actor, and gives any other label wider than its shape a region as wide as it needs, centred on the shape.
- **Drawing order**: without `drawableOrder`, connectors draw behind shapes and shapes stack by `z_index`. If you write `drawableOrder` it must list every shape and connector on the page exactly once, back to front.
- **Groups** need at least two members on the same page, each member in only one group, no cycles.

## Enumerated values

- **Endings**: `none`, `stop`, `arrow`, `solidArrow`, `filledArrow`, `circle`, `solidCircle`, `openDiamond`, `diamond`, `halfCircle`, `slash`, and for data models `crowFoot`, `one`, `oneAndOnlyOne`, `zeroOrOne`, `oneOrMany`, `zeroOrMany`. Also `circlePlus`, `cross` and `halfArrow`.
- **Stroke pattern**: `solid`, `dashed`, `dotted`.
- **Font weight**: `regular`, `medium`, `bold`. **Alignment**: `leading`, `center`, `trailing`, `justified`.
- **Label position**: `above`, `top`, `middle`, `bottom`, `below`.
- **Note style**: `stickyNote`, `indexCard`, `tapedNote`, `tag`, `notebookPage`, `pinnedNote`.
- **Textures**: `Horizontal`, `Vertical`, `Grid`, `SingleHatch`, `TripleHatch`, `PencilFill`, `PencilThinHoriztonalHatch` (spelt this way in the app), `PencilThinSquareHatch`, `PencilThinCrossHatch`, `PencilThinDiagonalHatch`, `WatercolorFill`, `Grain`, `PencilVerticalHatch`, `PencilTriangleHatch`, `PencilRandomHatch`, `PencilHorizontal`, `Chalk`.
