# Versions

The skill writes package 15 by default, and package 16 only for a document that uses a shape from a downloadable library. The builder and bundled shape catalog need to agree with the versions named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.3.0 | `.claude-plugin/plugin.json` |
| Package format | 15 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 14 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Package format, downloadable shapes | 16 | `REQUIRED_LIBRARIES_FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema, downloadable shapes | 15 | `REQUIRED_LIBRARIES_SCHEMA_VERSION` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Catalogue API | 1 | `https://simplediagrams.com/shape-libraries/catalog.json` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams 5.1.0 (not yet released) | `assets/built-in-shapes.json` |

**SimpleDiagrams 5.1.0 is not released yet (18 October 2026).** This version of the skill names 5.1.0 as the release that brings the BPMN and UML libraries, ten newer Basic shapes, and downloaded shapes put in place. Its catalog was regenerated from the final 5.1.0 bundle on 18 October 2026. Publish it only once 5.1.0 ships, then remove this paragraph and "(not yet released)" above.

The document format began in SimpleDiagrams for macOS 5.0.8, and every document the skill writes opens there unless it uses one of the newer things listed below. SimpleDiagrams 5.0.16 writes package 17 / schema 16, and 5.1.0 writes 18 / 17; the app reads every version from 1. The skill keeps writing 15 / 14 so its documents open in more versions.

The offline catalog was regenerated on 18 October 2026 from the final 5.1.0 desktop bundle and its published identity table: eight libraries, 534 shapes. It preserves every earlier reference and adds ten Basic shapes and the eight shapes of the UML library. Each packaged shape added after 5.0.8 records the release that first shipped it as `first_release` (89 UI Flow shapes 5.0.12; 58 Biz shapes 5.0.16; 89 BPMN, 10 Basic and 8 UML shapes 5.1.0), and the builder prints a `needs` line for each release a document's shapes require. An earlier app shows a dashed placeholder for a shape it does not contain. Regenerating the catalog keeps every recorded `first_release` and gives a shape new to the list the release that regeneration names, so regenerating for 5.1.0 again from a later 5.1.0 bundle changes nothing already recorded. When the next release's number is not decided, the release is named "after X (unreleased)", which the builder words as "the first SimpleDiagrams release after X".

Each library also lists `published_library_id`, and each shape `published_item_id`: the same shape's identifiers on the SimpleDiagrams website. They are for matching against the website's catalogue. A `symbol_reference` for a packaged shape is still written with `library_id`, `item_id` and `asset_version`, which every version from 5.0.8 understands.

A packaged shape may also carry its library's `connection_points` (an empty list means none, as on BPMN's task marks), `text_region` and `text_position` (BPMN events put their name below), and `resizing`. The builder gives a placed shape these, as the app does for a shape dragged from the Library panel, with two differences that come from the older package it writes:

- From 5.1.0 a packaged library may centre a name wider than its shape, starting left of it, as for BPMN events and the UML Actor. Only package 18 can hold such a region, and the app refuses an older file that has one, so the builder keeps the name to the shape's width. A name too long for that becomes a caption grouped with the shape.
- `resizing: width_only` (the UML Fork / Join Bar) means the shape's height is its thickness, which the app keeps whatever a person does. The builder keeps it too: a spec gives such a shape a `width` or `scale`, which lengthens it, and a `height` is an error.

The app is the source of truth for its packaged libraries and the website copies them, sometimes later, so these facts come from this list even when the website catalogue is used, and a packaged library the website does not list yet is offered from it. The catalogue reader accepts a label region in either of the app's two forms, inside the shape or centred and wider, so a website catalogue listing the 5.1.0 libraries is not rejected.

The search, build and preview commands read the website catalogue. It supersedes the fallback for every downloadable library and for the names, descriptions and search words of packaged ones. Each command makes one request and stores nothing; offline, or when the request fails, the skill uses this packaged fallback. The pure compiler's `Catalog.load()` remains an offline operation for deterministic tests and callers.

Downloadable shapes are placeable by their published references: the library's and shape's published UUIDs. A document that uses one names each such library in `required_libraries` and is written at package 16 / schema 15, which SimpleDiagrams reads from 5.0.16. From 5.1.0, opening it with the library installed puts the artwork in place, and the app saves the document in its own current format, after which it no longer needs the library. Without the library, the shapes are placeholder boxes, and 5.1.0 names the library and links to its page; 5.0.16 shows the boxes only. The skill does not embed downloaded artwork. Every other document stays at package 15 / schema 14.

## What needs a newer app

The builder prints a `needs` line for each, after its findings. They are not warnings, so `--strict` does not fail on them.

| A document that uses | Opens in |
|---|---|
| Line endings `circlePlus`, `cross` or `halfArrow` | 5.0.11 and later; earlier versions refuse the file |
| BPMN shapes, UML shapes, or the ten Basic shapes added in 5.1.0 | 5.1.0 and later; earlier versions draw dashed placeholders |
| A connector attached to a flipped shape | 5.1.0 and later; earlier versions attach it where the point would be on the unflipped shape |
| A shape from a downloadable library | 5.0.16 and later (package 16); its artwork appears from 5.1.0 with the library installed, and is a placeholder box otherwise |
| UI Flow shapes added in 5.0.12, Biz shapes added in 5.0.16 | those versions; earlier versions draw dashed placeholders |

Not offered by the skill, though the app reads them: right-angle connectors that route themselves (package 16), a connector's routing orientation (package 17), and what package 18 adds: Complex Shapes (containers, swimlanes, tables, callouts and UML lifelines, including BPMN's pools and UML's boxes, which are built from them) and names that start outside their shape. The skill writes package 16 only for the required-libraries list; its own routes already use right angles.

## Compatibility rules

- A skill release writes package 15, and package 16 only for a document that names required libraries. Writing any other package format requires a major skill release (before 1.0, a new minor version).
- Spec version 1 keeps its meaning. Add a later version alongside it instead of silently changing version 1.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 15/14 and 16/15 version pairs, generated schemas, required fields, catalog size, that every label region the builder writes starts inside its shape, and the version statements in the release files. They do not establish compatibility with future desktop releases.
