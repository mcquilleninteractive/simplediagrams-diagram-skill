# Versions

Every document the skill writes is package format 18, the format SimpleDiagrams 5.1.0 writes, and needs SimpleDiagrams 5.1.0 or later. The builder and the bundled shape catalog need to agree with the versions named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.4.0 | `.claude-plugin/plugin.json` |
| Package format | 18 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 17 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Catalogue API | 1 | `https://simplediagrams.com/shape-libraries/catalog.json` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams 5.1.0 | `assets/built-in-shapes.json` |

## The bundled catalog

The offline catalog was made from the SimpleDiagrams 5.1.0 desktop bundle and its published identity table: eight libraries, 534 shapes. Each library lists `published_library_id` and each shape `published_item_id`, the same shape's identifiers on the SimpleDiagrams website, for matching against the website's catalogue. A packaged shape's `symbol_reference` is written with the app's own `library_id`, `item_id` and `asset_version`. The `first_release` some entries carry is not used.

A packaged shape may carry its library's `connection_points` (an empty list means none, as on BPMN's task marks), `text_region` and `text_position`, and `resizing`. The builder gives a placed shape these, as the app does for a shape dragged from the Library panel. A label region may be wider than its shape and centred on it, as for BPMN events and the UML Actor. `resizing: width_only` (the UML Fork / Join Bar) means the shape's height is its thickness, which the app keeps, so a spec gives such a shape a `width` or `scale` and never a `height`.

The app is the source of truth for its packaged libraries and the website copies them, sometimes later, so these facts come from this list even when the website catalogue is used, and a packaged library the website does not list yet is offered from it. A downloadable shape takes the connection points and label placement its library gives it in the catalogue.

The search, build and preview commands read the website catalogue, which supersedes the fallback for every downloadable library and for the names, descriptions and search words of packaged ones. Each command makes one request and stores nothing; offline, or when the request fails, the skill uses the bundled list. The pure compiler's `Catalog.load()` makes no request, for deterministic tests and callers.

## What a document holds

Shapes, text and connectors; shapes from the packaged libraries; shapes from downloadable libraries, placed by their published references and named in `required_libraries`, which the app puts in place when the library is installed and otherwise draws as placeholder boxes, naming the library; and complex shapes, which the app draws itself: containers, swimlanes, tables, callouts and UML lifelines, whose messages attach anywhere along their lines. The builder prints a `needs` line for each downloadable library a document uses, so whoever sends the file can say which library shows its shapes.

Not offered by the skill, though the app reads them: connectors that route themselves, an Automatic container layout, a container wearing a drawing, swimlanes' title strips and band made wider than new ones, the optional list of readable `library_shape_names`, and connector ends attached along anything but a lifeline's line.

## Compatibility rules

- A skill release writes one package format. Writing another requires a major skill release (before 1.0, a new minor version).
- Spec version 1 keeps its meaning. Additions to it are optional fields that leave every earlier spec valid; a change of meaning needs a later version alongside it.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 18/17 version pair, generated schemas, required fields, catalog size, the complex-shape records and rules, and the version statements in the release files. `tests/fixtures.py` holds a document using every optional key and one using every key complex shapes add, so they and the built examples can be shown to SimpleDiagrams' own reader before a release. The tests do not establish compatibility with future desktop releases.
