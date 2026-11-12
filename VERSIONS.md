# Versions

Every document the skill writes is package format 21, the format SimpleDiagrams 5.4 writes, and needs SimpleDiagrams 5.4.0 or later. The builder and the bundled shape catalog need to agree with the versions named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.7.0 | `.claude-plugin/plugin.json` |
| Package format | 21 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 20 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Complex-shape catalogue | Thirteen types, each written with version 1 | `CATALOGUE` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams 5.4.0 | `assets/built-in-shapes.json` |

## The bundled catalog

The catalog lists the shapes of the SimpleDiagrams 5.4.0 desktop bundle: eight libraries, 535 shapes. It is the 5.2.0 list, whose 534 shapes 5.4.0 packages unchanged, with the one shape 5.4.0 added, Biz's Trophy. It is the skill's only source of library shapes; the skill makes no network request and cannot place a shape from a downloadable library. A shape's `symbol_reference` is written with the app's own `library_id`, `item_id` and `asset_version`. Each shape's `slug` is searched with its name; the `first_release` some entries carry is not used.

A packaged shape may carry its library's `connection_points` (an empty list means none, as on BPMN's task marks), `text_region` and `text_position`, and `resizing`. The builder gives a placed shape these, as the app does for a shape dragged from the Library panel. A label region may be wider than its shape and centred on it, as for BPMN events and the UML Actor. `resizing: width_only` (the UML Fork / Join Bar) means the shape's height is its thickness, which the app keeps, so a spec gives such a shape a `width` or `scale` and never a `height`.

## What a document holds

Shapes, text and connectors; shapes from the packaged libraries; notes in any of their nine looks, shown in full or collapsed to an icon; a highlight behind a label; bulleted and numbered lists in a shape's own label; a label beside each end of a connector; and all thirteen complex shapes, which the app draws itself: containers, swimlanes, tables, entity tables, callouts, UML lifelines, rings, flows, pyramids and funnels, cycles, gauges, audiences and Gantt charts. A ring's sections may hold shares, a table says which UML box it stands for, lifeline messages attach anywhere along their lines, and a connector may end on a part such as a field, a step or a task.

Not offered by the skill, though the app reads them: shapes from downloadable libraries and the `required_libraries` list naming them, right-angle connectors left for the app to route around other shapes, a container's Automatic layout, a container wearing a drawing, swimlanes' title strips and band made wider than new ones, a place chosen by hand for a part's words, a gauge's caption or a Gantt chart's title, texture on a part, paint on a gauge's needle, styled stretches inside a label, lists in a connector's label, a lane's title, a table's cell or a part's words, a first task that starts after a later one, an end label placed anywhere but where the app starts a new one, the manifest's `app_version` and `app_build`, the optional list of readable `library_shape_names`, and connector ends attached along anything but a lifeline's line.

## Compatibility rules

- A skill release writes one package format. Writing another requires a major skill release (before 1.0, a new minor version).
- Spec version 1 keeps its meaning. Additions to it are optional fields that leave every earlier spec valid; a change of meaning needs a later version alongside it.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- A later SimpleDiagrams may add complex-shape types within format 21; the skill writes only the ones in its `CATALOGUE`, and each stays valid.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 21/20 version pair, generated schemas, required fields, catalog size, what each complex-shape type holds, how much a shape and a page may hold, and the version statements in the release files. `tests/fixtures.py` holds a document using every optional key and one using every complex-shape type. Before a release, `maintainers/check_against_app.py` shows these, the built examples, and every kind of complex shape in many settings to SimpleDiagrams' own reader, and compares where the builder ends connectors with where the app puts those points; the tests alone cannot establish that, nor compatibility with future desktop releases. The app may refine how it draws a complex shape without a new format, as it does a ring with a thin section, drawn on a smaller circle; such a change moves connection points, and only this run shows it.
