# Versions

The skill writes one document format by default. The builder and bundled shape catalog need to agree with the version named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.1.0 | `.claude-plugin/plugin.json` |
| Package format | 15 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 14 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Catalogue API | 1 | `https://simplediagrams.com/shape-libraries/catalog.json` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams after 5.0.16 (unreleased) | `assets/built-in-shapes.json` |

The document format began in SimpleDiagrams for macOS 5.0.8, and every document the skill writes opens there unless it uses one of the newer things listed below. The app itself now writes package 17 / schema 16; the skill keeps writing 15 / 14 so its documents open in more versions. The full structure of a diagram file, every version included, is in `simplediagrams-project/desktop/diagram-document-structure.md`.

The offline catalog was regenerated on 14 October 2026 from the desktop bundle and its published identity table: seven libraries, 510 shapes. It preserves every earlier reference and adds the 83 shapes of the BPMN library, which the desktop bundles from the first release after 5.0.16. When that release is published, regenerate the catalog with its version number and replace the wording in `LIBRARY_FIRST_RELEASE` in `scripts/sd_spec.py`. The 58 newer Biz shapes require 5.0.16 and the added UI Flow shapes 5.0.12. An earlier app shows a dashed placeholder for a shape it does not contain.

Each library also lists `published_library_id`, and each shape `published_item_id`: the same shape's identifiers on the SimpleDiagrams website. They are for matching against the website's catalogue. A `symbol_reference` for a packaged shape is still written with `library_id`, `item_id` and `asset_version`, which every version from 5.0.8 understands.

A packaged shape may also carry its library's `connection_points` (an empty list means none, as on BPMN's task marks), `text_region` and `text_position` (BPMN events put their name below). The builder gives a placed shape exactly these, as the app does for a shape dragged from the Library panel. The app is the source of truth for its packaged libraries and the website copies them, sometimes later, so these facts come from this list even when the website catalogue is used, and a packaged library the website does not list yet is offered from it.

The search, build and preview commands read the website catalogue. It supersedes the fallback for every downloadable library and for the names, descriptions and search words of packaged ones. A validated API cache is usable offline; with no such cache the skill uses this packaged fallback. The pure compiler's `Catalog.load()` remains an offline operation for deterministic tests and callers.

Downloadable shapes are discoverable, but are not placeable by this profile. The desktop's document resolver only handles packaged references; installing a downloadable library does not enable UUID reference resolution. The builder refuses those placements, and the skill does not write a required-libraries list or claim to embed downloaded artwork.

## What needs a newer app

The builder prints a `needs` line for each, after its findings. They are not warnings, so `--strict` does not fail on them.

| A document that uses | Opens in |
|---|---|
| Line endings `circlePlus`, `cross` or `halfArrow` | 5.0.11 and later; earlier versions refuse the file |
| BPMN shapes | the first release after 5.0.16; earlier versions draw dashed placeholders |
| UI Flow shapes added in 5.0.12, Biz shapes added in 5.0.16 | those versions; earlier versions draw dashed placeholders |

Not offered by the skill, though the app reads them: right-angle connectors that route themselves (package 16), a connector's routing orientation (package 17), and the required-libraries list (package 16). Writing any of them means writing a newer package that 5.0.8 to 5.0.14 cannot open; the skill's own routes already use right angles.

## Compatibility rules

- One skill release writes one package format. A new package format requires a major skill release.
- Spec version 1 keeps its meaning. Add a later version alongside it instead of silently changing version 1.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 15/14 version pair, generated schemas, required fields, catalog size, and the version statements in the release files. They do not establish compatibility with future desktop releases.
