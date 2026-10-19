# The `.simplediagram` document format, version 18

This describes what the skill writes. The exact statement of it is `scripts/sd_format.py` (Pydantic models) and the generated `schema/simplediagram-document-18.schema.json`; if this page and the models ever disagree, the models are right.

The skill writes package 18 / schema 17, the format SimpleDiagrams 5.1.0 writes, so every document needs SimpleDiagrams 5.1.0 or later. This page covers only what the skill writes.

Write a diagram spec and let `build_diagram.py` produce the document. This reference explains the generated package and build diagnostics.

## What this covers

The **authoring profile**: shapes drawn by the app (`rectangle`, `ellipse`, `note`, `text`, `path`), shapes from the app's libraries and downloaded ones (`symbol`), complex shapes (`complex_shape`), connectors, groups, guides, drawing order, grid and a solid page background.

Not covered, and rejected by the skill's models although the app can read them: embedded images, embedded shape artwork (how the app stores a personal library's shape, or a downloaded one once it is in place; the skill places downloaded shapes by reference instead), shape data, image backgrounds, print layout, content imported from older versions, an Automatic container layout, a container wearing a drawing, connectors that route themselves, and the optional list of readable `library_shape_names`.

## The package

A document is a **folder** whose name ends in `.simplediagram`. It is not a zip.

```
Order flow.simplediagram/
  manifest.json
  document.json
  assets/              must exist; empty in this profile
```

The app refuses the document if the folder has any other member, including `.DS_Store`, if `assets/` is missing, or if `assets/` contains anything it was not told about. Tools that drop empty folders (git, zip) and Finder's **Show Package Contents** are the usual ways a good document gets broken.

`manifest.json` is always exactly this:

```json
{"format": "com.simplediagrams.document", "format_version": 18, "contains_legacy_source": false}
```

## Two version numbers

`manifest.json` has `format_version` **18**. `document.json` has `schema_version` **17**. They are different counters and the second is always the first minus one. Writing 18 in both is refused.

## The libraries a document needs

A shape from a downloadable library is a `symbol` whose `symbol_reference` holds the library's and shape's published UUIDs and the shape's asset version, exactly as the catalogue gives them. The document then names each such library once, in the order its shapes first appear, under a top-level `required_libraries` key:

```json
"required_libraries": [
  {"library_id": "79FFE4B7-EA0D-87C3-AE89-D4CD62AF5202", "display_name": "Hobby Electronics Notebook"}
]
```

- Only when the list is not empty; never `null`.
- `library_id`: the identifier the references use. ASCII letters, digits, `.`, `-` and `_`, beginning and ending with a letter or digit, at most 256 bytes.
- `display_name`: not blank, at most 200 characters, no control characters, line breaks or text-direction controls.
- `minimum_revision` is optional (1 to 1,000,000). The skill leaves it out: the catalogue gives a library's current revision, which is not necessarily the lowest that holds the shapes.
- At most 64 entries, no library twice (ignoring case).

The list is advisory to the app: it names the library to a person who lacks it, and nothing is drawn or refused because of it. These are the app's own rules, so a list written here is never trimmed when it is read.

## Complex shapes

A complex shape is an element of kind `complex_shape` with a `complex_shape` record beside its `content`, holding only the keys its `type` uses. It has no `symbol_reference`, `path` or `text_layout`; its text sits in a fixed place. Each optional key is written only when it differs from the value the app reads in its place, as the app writes it:

| Key | Type | Meaning |
|---|---|---|
| `type` | all | `container`, `swimlanes`, `table`, `callout` or `lifeline` |
| `hand_drawn` | all | `false` for exact lines; left out when hand-drawn |
| `members` | container | Always written. What it holds, in order: `{"kind": "element" or "group", "id": …}` |
| `title_style` | container | `corner_tag` for a UML frame's tag; left out for the band |
| `direction` | swimlanes | `horizontal` (lanes are rows) or `vertical` (columns) |
| `lanes` | swimlanes | 1 to 50, each `{"id", "title", "size", "members"}`: an id unique in the shape, a text record, a share, and what it holds |
| `title_strip_size`, `title_band_size` | swimlanes | Points, 28 to 10,000; left out when 28 |
| `row_sizes`, `column_sizes` | table | One share per row (1 to 200) and per column (1 to 50), at most 2,000 cells |
| `cells` | table | One text record per cell, row by row |
| `header_row` | table | `false` when the first row is not a header; left out otherwise |
| `tail_tip` | callout | `{"x", "y"}`, points from the frame's centre along the bubble's own axes before flipping; left out for no tail |
| `tail_attachment` | callout | A connection point of another shape on the page, as a connector end's; it needs `tail_tip`, saved where the tail is drawn |
| `head_style` | lifeline | `actor` for a stick figure; left out for a box |
| `ends_in_destroy_mark` | lifeline | `true` when the line ends in an X; left out otherwise |

A share is any number from 0.000001 to 1,000,000; a lane, row or column is its share of the whole. The app also holds:

- A table's own text is empty; a table is at least 16 points a column and 12 a row. A lane is at least 28 thick, and swimlanes at least as long as their title strips. A lifeline is its head (40, or 72 for an actor), 20 points of line, and half a 24-point destroy mark when it has one.
- Only a callout is flipped.
- Every member is on the same page and held once at most; a member is a shape in no group, or a whole group in no other group, never the holder, never swimlanes and never a connector. A container or swimlanes is in no group. Containers nest four deep at most, never in a loop.
- A lifeline offers one numbered point, 2, at the top of its head, and one attach line, 0, its dashed line from the bottom of its head to the frame's bottom, or to half a destroy mark above it.

Containers and swimlanes draw behind what they hold. The skill also writes a `drawableOrder` on a page with any, listing them first, outermost first, then the connectors, then the other shapes, so a UML fragment never covers the messages it is drawn around.

## Shape of `document.json`

Nine top-level keys, all required, and a tenth, `required_libraries`, when the document names a library. No others are allowed:

| Key | Value |
|---|---|
| `id` | UUID |
| `schema_version` | `17` |
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

All three values must match a catalogue shape exactly: a packaged shape's are the app's own names, as in `assets/built-in-shapes.json`, and a downloadable shape's are its published UUIDs, as in the API. A reference the app cannot resolve does not stop the document opening: the shape is drawn as a dashed placeholder showing the item name. For a downloadable library named in `required_libraries`, SimpleDiagrams says which library is missing and links to its page. Nothing reports a mistyped reference, which is why the skill's validator treats a reference in neither catalogue as an error.

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

- `points` is the entire route, at least two. A right-angled connector here is simply points that form right angles. A point of kind `curve` between two others makes a smooth bend through it. The app also has connectors that route themselves (`routing: right_angle`); the skill does not write them, and draws its own right-angled routes instead.
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
- **Note style**: `stickyNote`, `indexCard`.
- **Textures**: `Horizontal`, `Vertical`, `Grid`, `SingleHatch`, `TripleHatch`, `PencilFill`, `PencilThinHoriztonalHatch` (spelt this way in the app), `PencilThinSquareHatch`, `PencilThinCrossHatch`, `PencilThinDiagonalHatch`, `WatercolorFill`, `Grain`, `PencilVerticalHatch`, `PencilTriangleHatch`, `PencilRandomHatch`, `PencilHorizontal`, `Chalk`.
