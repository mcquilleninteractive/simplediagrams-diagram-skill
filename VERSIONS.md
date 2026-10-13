# Versions

The skill writes one fixed document format. The builder and bundled shape catalog need to agree with the version named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.1.0 | `.claude-plugin/plugin.json` |
| Package format | 15 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 14 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Catalogue API | 1 | `https://simplediagrams.com/shape-libraries/catalog.json` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams 5.0.16 | `assets/built-in-shapes.json` |

The document format began in SimpleDiagrams for macOS 5.0.8. The offline catalog was regenerated on 13 October 2026 from the desktop bundle and its published identity table: six libraries, 427 shapes, including all 83 Biz shapes. It preserves the original 280 references and the 89 UI Flow additions. The 58 new Biz shapes require 5.0.16; the added UI Flow shapes require 5.0.12. An earlier app shows a dashed placeholder for a shape it does not contain. Check compatibility with each release before claiming support for it.

Each library also lists `published_library_id`, and each shape `published_item_id`: the same shape's identifiers on the SimpleDiagrams website. They are for matching against the website's catalogue. A `symbol_reference` for a packaged shape is still written with `library_id`, `item_id` and `asset_version`, which every version from 5.0.8 understands.

The search, build and preview commands now read the website catalogue. It supersedes the fallback for every library it covers. A validated API cache is usable offline; with no such cache the skill uses this packaged fallback. The pure compiler's `Catalog.load()` remains an offline operation for deterministic tests and callers.

Downloadable shapes are discoverable, but are not placeable by this profile. Desktop 5.0.16's document resolver only handles packaged references; installing a downloadable library does not enable UUID reference resolution. The builder refuses those placements. Package 15 / schema 14 remain unchanged, and the skill does not write a required-libraries list or claim to embed downloaded artwork.

## Compatibility rules

- One skill release writes one package format. A new package format requires a major skill release.
- Spec version 1 keeps its meaning. Add a later version alongside it instead of silently changing version 1.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 15/14 version pair, generated schemas, required fields, catalog size, and the version statements in the release files. They do not establish compatibility with future desktop releases.
