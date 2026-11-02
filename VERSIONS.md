# Versions

Every document the skill writes is package format 19, the format SimpleDiagrams 5.2 writes, and needs SimpleDiagrams 5.2.0 or later. The builder and the bundled shape catalog need to agree with the versions named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.6.1 | `.claude-plugin/plugin.json` |
| Package format | 19 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 18 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Complex-shape catalogue | Eleven types, each at version 1 | `CATALOGUE` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams 5.2.0 | `assets/built-in-shapes.json` |

## The bundled catalog

The catalog was made from the SimpleDiagrams 5.2.0 desktop bundle: eight libraries, 534 shapes. It is the skill's only source of library shapes; the skill makes no network request and cannot place a shape from a downloadable library. A shape's `symbol_reference` is written with the app's own `library_id`, `item_id` and `asset_version`. Each shape's `slug` is searched with its name; the `first_release` some entries carry is not used.

A packaged shape may carry its library's `connection_points` (an empty list means none, as on BPMN's task marks), `text_region` and `text_position`, and `resizing`. The builder gives a placed shape these, as the app does for a shape dragged from the Library panel. A label region may be wider than its shape and centred on it, as for BPMN events and the UML Actor. `resizing: width_only` (the UML Fork / Join Bar) means the shape's height is its thickness, which the app keeps, so a spec gives such a shape a `width` or `scale` and never a `height`.

## What a document holds

Shapes, text and connectors; shapes from the packaged libraries; notes in any of their six looks; a highlight behind a label; and all eleven complex shapes, which the app draws itself: containers, swimlanes, tables, entity tables, callouts, UML lifelines, rings, flows, pyramids and funnels, cycles and gauges. Lifeline messages attach anywhere along their lines, and a connector may end on a part such as a field or a step.

Not offered by the skill, though the app reads them: shapes from downloadable libraries and the `required_libraries` list naming them, connectors that route themselves, a container's Automatic layout, a container wearing a drawing, swimlanes' title strips and band made wider than new ones, a place chosen by hand for a part's words or a gauge's caption, texture on a part, paint on a gauge's needle, styled stretches inside a label, the manifest's `app_version` and `app_build`, the optional list of readable `library_shape_names`, and connector ends attached along anything but a lifeline's line.

## Compatibility rules

- A skill release writes one package format. Writing another requires a major skill release (before 1.0, a new minor version).
- Spec version 1 keeps its meaning. Additions to it are optional fields that leave every earlier spec valid; a change of meaning needs a later version alongside it.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- A later SimpleDiagrams may add complex-shape types within format 19; the skill writes only the ones in its `CATALOGUE`, and each stays valid.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 19/18 version pair, generated schemas, required fields, catalog size, what each complex-shape type holds, how much a shape and a page may hold, and the version statements in the release files. `tests/fixtures.py` holds a document using every optional key and one using every complex-shape type. Before a release, `maintainers/check_against_app.py` shows these, the built examples, and every kind of complex shape in many settings to SimpleDiagrams' own reader, and compares where the builder ends connectors with where the app puts those points; the tests alone cannot establish that, nor compatibility with future desktop releases.
