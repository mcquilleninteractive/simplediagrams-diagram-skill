# Versions

The skill writes package 15 by default, and package 16 only for a document that uses a shape from a downloadable library. The builder and bundled shape catalog need to agree with the versions named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.2.0 | `.claude-plugin/plugin.json` |
| Package format | 15 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 14 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Package format, downloadable shapes | 16 | `REQUIRED_LIBRARIES_FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema, downloadable shapes | 15 | `REQUIRED_LIBRARIES_SCHEMA_VERSION` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Catalogue API | 1 | `https://simplediagrams.com/shape-libraries/catalog.json` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams after 5.0.16 (unreleased) | `assets/built-in-shapes.json` |

The document format began in SimpleDiagrams for macOS 5.0.8, and every document the skill writes opens there unless it uses one of the newer things listed below. Released SimpleDiagrams 5.0.16 writes package 17 / schema 16, and development builds after it write 18 / 17; the app reads every version from 1. The skill keeps writing 15 / 14 so its documents open in more versions.

The offline catalog was regenerated on 15 October 2026 from the desktop bundle and its published identity table: seven libraries, 516 shapes. It preserves every earlier reference and adds the 89 shapes of the BPMN library, which the desktop bundles from the first release after 5.0.16. Each packaged shape added after 5.0.8 records the release that first shipped it as `first_release` (58 Biz shapes 5.0.16, 89 UI Flow shapes 5.0.12, the BPMN shapes "after 5.0.16 (unreleased)"), and the builder prints a `needs` line for each release a document's shapes require. `update_catalog.py` keeps these values and gives a shape new to the list the `--app-version` it was run with. When the next release is published, regenerate the catalog with its version number, which turns each "unreleased" value into that number, and replace the wording in `NEXT_RELEASE` in `scripts/sd_spec.py` and wherever the docs say "the first release after 5.0.16". The 58 newer Biz shapes require 5.0.16 and the added UI Flow shapes 5.0.12. An earlier app shows a dashed placeholder for a shape it does not contain.

Each library also lists `published_library_id`, and each shape `published_item_id`: the same shape's identifiers on the SimpleDiagrams website. They are for matching against the website's catalogue. A `symbol_reference` for a packaged shape is still written with `library_id`, `item_id` and `asset_version`, which every version from 5.0.8 understands.

A packaged shape may also carry its library's `connection_points` (an empty list means none, as on BPMN's task marks), `text_region` and `text_position` (BPMN events put their name below). The builder gives a placed shape exactly these, as the app does for a shape dragged from the Library panel. The app is the source of truth for its packaged libraries and the website copies them, sometimes later, so these facts come from this list even when the website catalogue is used, and a packaged library the website does not list yet is offered from it.

The search, build and preview commands read the website catalogue. It supersedes the fallback for every downloadable library and for the names, descriptions and search words of packaged ones. Each command makes one request and stores nothing; offline, or when the request fails, the skill uses this packaged fallback. The pure compiler's `Catalog.load()` remains an offline operation for deterministic tests and callers.

Downloadable shapes are placeable by their published references (desktop ADR 0039). A document that uses one names each such library in `required_libraries` and is written at package 16 / schema 15, which SimpleDiagrams reads from 5.0.16. From the first release after 5.0.16, opening it with the library installed puts the artwork in place and the document no longer needs the library once saved; without the library, the shapes are dashed boxes and the app names the library and links to its page. The skill does not embed downloaded artwork. Every other document stays at package 15 / schema 14.

## What needs a newer app

The builder prints a `needs` line for each, after its findings. They are not warnings, so `--strict` does not fail on them.

| A document that uses | Opens in |
|---|---|
| Line endings `circlePlus`, `cross` or `halfArrow` | 5.0.11 and later; earlier versions refuse the file |
| BPMN shapes | the first release after 5.0.16; earlier versions draw dashed placeholders |
| A shape from a downloadable library | 5.0.16 and later (package 16); its artwork appears from the first release after 5.0.16 with the library installed, and is a dashed box otherwise |
| UI Flow shapes added in 5.0.12, Biz shapes added in 5.0.16 | those versions; earlier versions draw dashed placeholders |

Not offered by the skill, though the app reads them: right-angle connectors that route themselves (package 16) and a connector's routing orientation (package 17). The skill writes package 16 only for the required-libraries list; its own routes already use right angles.

## Compatibility rules

- A skill release writes package 15, and package 16 only for a document that names required libraries. Writing any other package format requires a major skill release (before 1.0, a new minor version).
- Spec version 1 keeps its meaning. Add a later version alongside it instead of silently changing version 1.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 15/14 and 16/15 version pairs, generated schemas, required fields, catalog size, and the version statements in the release files. They do not establish compatibility with future desktop releases.
