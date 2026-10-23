# Versions

Every document the skill writes is package format 18, the format SimpleDiagrams 5.1.0 writes, and needs SimpleDiagrams 5.1.0 or later. The builder and the bundled shape catalog need to agree with the versions named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.5.0 | `.claude-plugin/plugin.json` |
| Package format | 18 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 17 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams 5.1.0 | `assets/built-in-shapes.json` |

## The bundled catalog

The catalog was made from the SimpleDiagrams 5.1.0 desktop bundle: eight libraries, 534 shapes. It is the skill's only source of library shapes; the skill makes no network request and cannot place a shape from a downloadable library. A shape's `symbol_reference` is written with the app's own `library_id`, `item_id` and `asset_version`. Each shape's `slug` is searched with its name; the `first_release` some entries carry is not used.

A packaged shape may carry its library's `connection_points` (an empty list means none, as on BPMN's task marks), `text_region` and `text_position`, and `resizing`. The builder gives a placed shape these, as the app does for a shape dragged from the Library panel. A label region may be wider than its shape and centred on it, as for BPMN events and the UML Actor. `resizing: width_only` (the UML Fork / Join Bar) means the shape's height is its thickness, which the app keeps, so a spec gives such a shape a `width` or `scale` and never a `height`.

## What a document holds

Shapes, text and connectors; shapes from the packaged libraries; and complex shapes, which the app draws itself: containers, swimlanes, tables, callouts and UML lifelines, whose messages attach anywhere along their lines.

Not offered by the skill, though the app reads them: shapes from downloadable libraries and the `required_libraries` list naming them, connectors that route themselves, an Automatic container layout, a container wearing a drawing, swimlanes' title strips and band made wider than new ones, the optional list of readable `library_shape_names`, and connector ends attached along anything but a lifeline's line.

## Compatibility rules

- A skill release writes one package format. Writing another requires a major skill release (before 1.0, a new minor version).
- Spec version 1 keeps its meaning. Additions to it are optional fields that leave every earlier spec valid; a change of meaning needs a later version alongside it.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 18/17 version pair, generated schemas, required fields, catalog size, the complex-shape records and rules, and the version statements in the release files. `tests/fixtures.py` holds a document using every optional key and one using every key complex shapes add, so they and the built examples can be shown to SimpleDiagrams' own reader before a release. The tests do not establish compatibility with future desktop releases.
